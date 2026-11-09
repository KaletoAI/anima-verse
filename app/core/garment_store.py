"""The garment store — where a character's own-mesh garments live on disk
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md``, R10,
R11, R13; spec ``2026-11-08-base-body-outfits-design.md`` § C.4).

Per owner, under ``characters/<name>/garments/``::

    images/{item}_{fsig}_{step}_{view}.png  + .json   steps haired/ghost/cutout;
    images/{item}_{fsig}_{step}_{view}.try{n}.png     the attempts of a step
    raw/{item}_{fsig}.glb                             generator output
    prepared/{item}_{fsig}.glb                        decimated
    {item}_{fsig}.glb + .json                         the fit: rigged base with the
                                                      garment grafted on; its record
                                                      holds gates + base_model_sha256
    low/{item}_{fsig}.glb                             the distance tier

``fsig`` = md5[:12] over the garment kind's own inputs (hair: description,
behind-the-shoulders flag, pronouns), ``GARMENT_VERSION[kind]``, the base
signature and the content of the base front + back view. The base MODEL is not
in it: a base model regenerated under the same base signature keeps images and
mesh and only re-fits; the fit record's ``base_model_sha256`` decides that.

Run status is in memory (like ``base_body``): a restart reruns only the step
that was in flight, every finished step is cached on disk under ``fsig``.
"""
import hashlib
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_store")

GARMENT_VERSION: Dict[str, int] = {"hair": 1}
GARMENT_STEPS: Dict[str, Tuple[str, ...]] = {"hair": ("haired", "ghost", "cutout", "mesh", "fit")}
GARMENT_VIEWS: Tuple[str, ...] = ("front", "back")
#: The steps that store images (the rest store meshes).
IMAGE_STEPS: Tuple[str, ...] = ("haired", "ghost", "cutout")
#: part -> sub-folder of ``garments/`` ("" = the folder itself).
PART_DIRS: Dict[str, str] = {"image": "images", "raw": "raw", "prepared": "prepared",
                             "fit": "", "low": "low"}

_FSIG_RE = re.compile(r"[0-9a-f]{12}")
_ITEM = r"(?P<item>[A-Za-z0-9][A-Za-z0-9_-]*)"
_FSIG = r"(?P<fsig>[0-9a-f]{12})"
#: images/: {item}_{fsig}_{step}_{view}[.try{n}].{png,json}
_IMAGE_NAME_RE = re.compile(_ITEM + "_" + _FSIG + r"_[a-z]+_[a-z]+(?:\.try[0-9]+)?\.(?:png|json)")
#: the mesh folders and the fit: {item}_{fsig}.{glb,json}
_MESH_NAME_RE = re.compile(_ITEM + "_" + _FSIG + r"\.(?:glb|json)")


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


# --- Paths ------------------------------------------------------------------

def _root(character_name: str) -> Path:
    """``characters/<name>/garments`` without creating anything."""
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "garments"


def garments_dir(character_name: str) -> Path:
    """``characters/<name>/garments`` — created only when the character's own
    directory exists (a read path must never mint a ghost character)."""
    path = _root(character_name)
    if path.parent.is_dir():
        path.mkdir(exist_ok=True)
    return path


def garment_path(character_name: str, item_id: str, fsig: str, part: str, *,
                 step: str = "", view: str = "", attempt: int = 0) -> Path:
    """The file of one garment part (see the module docstring for the layout).

    ``part`` is ``image`` (needs an image ``step`` and a ``view``; ``attempt``
    > 0 names that attempt's file), ``raw``, ``prepared``, ``fit`` or ``low``.
    ValueError for an invalid item id, fsig, part, step or view, and for any
    path that would resolve outside ``garments/``. Creates nothing."""
    from app.models.inventory import safe_item_id
    iid = safe_item_id(item_id)
    if not iid or iid != item_id:
        raise ValueError(f"invalid garment item id {str(item_id)[:80]!r}")
    if not isinstance(fsig, str) or not _FSIG_RE.fullmatch(fsig):
        raise ValueError(f"invalid garment fingerprint {str(fsig)[:40]!r}")
    if part not in PART_DIRS:
        raise ValueError(f"unknown garment part {part!r}")
    root = _root(character_name)
    if part == "image":
        if step not in IMAGE_STEPS:
            raise ValueError(f"no image step {step!r}")
        if view not in GARMENT_VIEWS:
            raise ValueError(f"no garment view {view!r}")
        tail = f".try{int(attempt)}.png" if attempt else ".png"
        path = root / PART_DIRS[part] / f"{iid}_{fsig}_{step}_{view}{tail}"
    else:
        folder = root / PART_DIRS[part] if PART_DIRS[part] else root
        path = folder / f"{iid}_{fsig}.glb"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"garment path escapes {root}")
    return path


def parse_name(path: Path) -> Optional[Tuple[str, str]]:
    """``(item_id, fsig)`` of a stored garment file, None for any other name."""
    pattern = _IMAGE_NAME_RE if path.parent.name == PART_DIRS["image"] else _MESH_NAME_RE
    match = pattern.fullmatch(path.name)
    return (match.group("item"), match.group("fsig")) if match else None


def stored_groups(character_name: str) -> Dict[Tuple[str, str], List[Path]]:
    """Every recognised garment file of the character, grouped by
    ``(item_id, fsig)``. Files with any other name are not listed."""
    root = _root(character_name)
    out: Dict[Tuple[str, str], List[Path]] = {}
    if not root.is_dir():
        return out
    folders = [root] + [root / sub for sub in sorted(set(PART_DIRS.values())) if sub]
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            key = parse_name(path)
            if key is not None:
                out.setdefault(key, []).append(path)
    return out


# --- Fingerprint --------------------------------------------------------------

def _kind_inputs(kind: str, character_name: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "hair":
        from app.core import garment_hair
        return garment_hair.fsig_inputs(character_name, profile=profile)
    raise ValueError(f"unknown garment kind {kind!r}")


def garment_fsig(character_name: str, item_id: str, *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """md5[:12] over ``{kind, <kind inputs>, version, bsig, base_images}``
    (R10). ValueError when ``item_id`` is no garment of a known kind."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    kind = str((item.get("garment") or {}).get("kind") or "")
    if item.get("category") != "garment" or kind not in GARMENT_VERSION:
        raise ValueError(f"{item_id!r} is no garment item of a known kind")
    profile = _profile_of(character_name, profile)
    bsig = base_body.base_signature(character_name, profile=profile)
    images = {view: base_body.file_sha256(find_ref_image(character_name, base_body._kind(view), bsig))
              for view in GARMENT_VIEWS}
    payload = {"kind": kind, **_kind_inputs(kind, character_name, profile),
               "version": GARMENT_VERSION[kind], "bsig": bsig, "base_images": images}
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()[:12]


# --- Records ------------------------------------------------------------------

def read_record(path: Path) -> Dict[str, Any]:
    """A sidecar's JSON object, {} when missing, unreadable or not an object."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_record(path: Path, record: Dict[str, Any]) -> None:
    """Write a sidecar atomically (temp file in the same folder + replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _accepted_on(record: Dict[str, Any], base_model_sha: str) -> bool:
    return record.get("accepted") is True and record.get("base_model_sha256") == base_model_sha


def accepted_fit(character_name: str, item_id: str, *,
                 base_model_sha: str) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """The fit to serve for a garment item on the base model ``base_model_sha``
    (R11): the current-fsig fit when its record is accepted on that model,
    else the newest (GLB mtime) accepted fit of the item on that model, else
    None. An empty ``base_model_sha`` (no base model) has no fit."""
    if not base_model_sha:
        return None
    try:
        current: Optional[str] = garment_fsig(character_name, item_id)
    except ValueError:
        current = None
    if current is not None:
        path = garment_path(character_name, item_id, current, "fit")
        record = read_record(path.with_suffix(".json"))
        if path.is_file() and _accepted_on(record, base_model_sha):
            return path, record
    best: Optional[Tuple[int, Path, Dict[str, Any]]] = None
    root = _root(character_name)
    for (iid, _fsig), files in stored_groups(character_name).items():
        if iid != item_id:
            continue
        for path in files:
            if path.suffix != ".glb" or path.parent != root:
                continue
            record = read_record(path.with_suffix(".json"))
            if not _accepted_on(record, base_model_sha):
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            if best is None or mtime > best[0]:
                best = (mtime, path, record)
    return (best[1], best[2]) if best else None


# --- Run status (in memory) ---------------------------------------------------

_status_lock = threading.Lock()
_running: Dict[Tuple[str, str], Tuple[str, datetime]] = {}
_failed: Dict[Tuple[str, str], Dict[str, Any]] = {}
# One garment run per character at a time: the steps of one garment build on
# each other, and two items of one character share its base files.
_char_locks: Dict[str, threading.Lock] = {}


def char_lock(character_name: str) -> threading.Lock:
    """The lock a garment run of this character holds."""
    with _status_lock:
        return _char_locks.setdefault(character_name, threading.Lock())


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def start(character_name: str, item_id: str, step: str) -> None:
    """Mark ``step`` of the item running (SYSTEM time)."""
    from app.core.timeutils import utc_now
    with _status_lock:
        _running[(character_name, item_id)] = (step, utc_now())


def end(character_name: str, item_id: str, step: str, error: Optional[str] = None,
        gates: Optional[Any] = None) -> None:
    """Step finished. With ``error`` the item's failure becomes
    ``{step, error, gates, failed_at}``; without, a failure of the same step
    is cleared."""
    from app.core.timeutils import utc_now
    key = (character_name, item_id)
    with _status_lock:
        if (_running.get(key) or ("",))[0] == step:
            _running.pop(key, None)
        if error is not None:
            _failed[key] = {"step": step, "error": error, "gates": gates, "failed_at": utc_now()}
        elif (_failed.get(key) or {}).get("step") == step:
            _failed.pop(key, None)


def status(character_name: str, item_id: str) -> Dict[str, Any]:
    """``{running_step, started_at, failed: {step, error, gates, failed_at} | None}``."""
    key = (character_name, item_id)
    with _status_lock:
        step, started = _running.get(key, (None, None))
        failure = _failed.get(key)
        failed = None
        if failure:
            failed = {**failure, "failed_at": _iso(failure.get("failed_at"))}
    return {"running_step": step, "started_at": _iso(started), "failed": failed}
