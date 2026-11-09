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

Hair has two methods (``garment_hair.hair_method``; plan
``docs/superpowers/plans/2026-11-09-hairdeck-hair.md``, Task 4): the edit chain
above, and HairDeck — steps ``("hairdeck", "fit")`` (``steps_for``). HairDeck
turns the profile picture into hair cards; its files live in ONE folder per
``hsig``::

    raw/{item}_{hsig}/                                every file of the job +
                                                      record.json {accepted,
                                                      attempt, seed, notes, error}

``hsig`` = md5[:12] over the profile picture's sha256, the ``extra_params`` of
the backend the ``hair_mesh`` occasion is meant to run on and
``HAIRDECK_VERSION`` — no base, no colour: a base change or a colour change
re-fits from the cached job. The HairDeck fsig is the edit-chain payload plus
``method``, ``hsig`` and the colour override (profile ``hair_colour``); the
edit-chain fsig carries no ``method`` key, so it stays what it always was.
The fit is the same ``{item}_{fsig}.glb`` + record (its record says
``method: "hairdeck"``; a record without ``method`` is an edit-chain fit);
``prepared/`` is not used by HairDeck.

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
#: The steps of hair made by HairDeck (``steps_for``).
HAIRDECK_STEPS: Tuple[str, ...] = ("hairdeck", "fit")
#: Bumped when the HairDeck job's inputs change meaning (part of ``hsig``).
HAIRDECK_VERSION = 1
#: The record of a HairDeck job folder (``hairdeck_dir``).
HAIRDECK_RECORD = "record.json"
EDIT_CHAIN = "edit_chain"
HAIRDECK = "hairdeck"
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


def hairdeck_dir(character_name: str, item_id: str, hsig: str) -> Path:
    """``garments/raw/{item}_{hsig}/`` — the folder of a HairDeck job (every
    result file + ``record.json``). ValueError like ``garment_path``.
    Creates nothing."""
    from app.models.inventory import safe_item_id
    iid = safe_item_id(item_id)
    if not iid or iid != item_id:
        raise ValueError(f"invalid garment item id {str(item_id)[:80]!r}")
    if not isinstance(hsig, str) or not _FSIG_RE.fullmatch(hsig):
        raise ValueError(f"invalid HairDeck fingerprint {str(hsig)[:40]!r}")
    root = _root(character_name)
    path = root / PART_DIRS["raw"] / f"{iid}_{hsig}"
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


def kind_method(kind: str, character_name: str, profile: Dict[str, Any]) -> str:
    """The method a garment of ``kind`` is made with: hair follows
    ``garment_hair.hair_method``, every other kind the edit chain."""
    if kind == "hair":
        from app.core import garment_hair
        return garment_hair.hair_method(character_name, profile=profile)
    return EDIT_CHAIN


def steps_for(kind: str, method: str) -> Tuple[str, ...]:
    """The step order of ``kind`` made with ``method``: hair by HairDeck is
    ``HAIRDECK_STEPS``, anything else ``GARMENT_STEPS[kind]``. ValueError for
    an unknown kind or method."""
    if kind not in GARMENT_STEPS:
        raise ValueError(f"unknown garment kind {kind!r}")
    if method == HAIRDECK and kind == "hair":
        return HAIRDECK_STEPS
    if method != EDIT_CHAIN:
        raise ValueError(f"unknown {kind} method {method!r}")
    return GARMENT_STEPS[kind]


def _garment_kind(item_id: str) -> str:
    from app.models.inventory import get_item
    item = get_item(item_id) or {}
    kind = str((item.get("garment") or {}).get("kind") or "")
    if item.get("category") != "garment" or kind not in GARMENT_VERSION:
        raise ValueError(f"{item_id!r} is no garment item of a known kind")
    return kind


def garment_method(character_name: str, item_id: str, *,
                   profile: Optional[Dict[str, Any]] = None) -> str:
    """``kind_method`` of a garment item. ValueError when ``item_id`` is no
    garment of a known kind."""
    kind = _garment_kind(item_id)
    return kind_method(kind, character_name, _profile_of(character_name, profile))


def hairdeck_backend_params(character_name: str) -> Dict[str, Any]:
    """The ``extra_params`` of the backend the ``hair_mesh`` occasion is meant
    to run on for the character (``routing.intended_backend``: configuration
    only, so a cooldown never changes it); {} when there is none."""
    from app.imagegen import routing, service
    pool = getattr(service.get_image_service(), "pool", None)
    if pool is None:
        return {}
    try:
        backend = routing.intended_backend("hair_mesh", character_name, pool=pool)
    except Exception:  # noqa: BLE001 — a fingerprint never fails on the routing config
        logger.exception("HairDeck backend of %s unresolvable", character_name)
        return {}
    params = getattr(backend, "extra_params", None) if backend is not None else None
    return dict(params) if isinstance(params, dict) else {}


def garment_hsig(character_name: str, item_id: str, *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """md5[:12] over ``{profile_image, extra_params, version}``: the sha256
    of the character's current profile picture ("" without one), the
    ``extra_params`` of the intended ``hair_mesh`` backend
    (``hairdeck_backend_params``) and ``HAIRDECK_VERSION``. Names the HairDeck
    job folder (``hairdeck_dir``). Neither the base nor the colour override is
    in it: changing them re-fits, never re-runs HairDeck."""
    from app.core import base_body
    from app.core.model_refs import current_profile_image
    profile = _profile_of(character_name, profile)
    payload = {"profile_image": base_body.file_sha256(current_profile_image(character_name, profile=profile)),
               "extra_params": hairdeck_backend_params(character_name),
               "version": HAIRDECK_VERSION}
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return digest.hexdigest()[:12]


def garment_fsig(character_name: str, item_id: str, *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """md5[:12] over ``{kind, <kind inputs>, version, bsig, base_images}``
    (R10); hair made by HairDeck adds ``{method, hsig, colour}`` (the colour
    override, "" = automatic). ValueError when ``item_id`` is no garment of a
    known kind."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    kind = _garment_kind(item_id)
    profile = _profile_of(character_name, profile)
    bsig = base_body.base_signature(character_name, profile=profile)
    images = {view: base_body.file_sha256(find_ref_image(character_name, base_body._kind(view), bsig))
              for view in GARMENT_VIEWS}
    payload = {"kind": kind, **_kind_inputs(kind, character_name, profile),
               "version": GARMENT_VERSION[kind], "bsig": bsig, "base_images": images}
    if kind_method(kind, character_name, profile) == HAIRDECK:
        from app.core import garment_hair
        payload.update(method=HAIRDECK, hsig=garment_hsig(character_name, item_id, profile=profile),
                       colour=garment_hair.hair_colour_override(profile))
    digest = hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()[:12]


def fit_method(record: Dict[str, Any]) -> str:
    """The method a fit record was made with; a record without ``method``
    (every fit from before HairDeck) is an edit-chain fit."""
    return str(record.get("method") or EDIT_CHAIN)


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


def accepted_fit(character_name: str, item_id: str, *, base_model_sha: str,
                 profile: Optional[Dict[str, Any]] = None) -> Optional[Tuple[Path, Dict[str, Any]]]:
    """The fit to serve for a garment item on the base model ``base_model_sha``
    (R11): the current-fsig fit when its record is accepted on that model,
    else the newest (GLB mtime) accepted fit of the item on that model made
    with the CURRENT method (``fit_method``; a switched method never serves
    the other method's hair), else None. An empty ``base_model_sha`` (no base
    model) has no fit."""
    if not base_model_sha:
        return None
    profile = _profile_of(character_name, profile)
    try:
        current: Optional[str] = garment_fsig(character_name, item_id, profile=profile)
        method = garment_method(character_name, item_id, profile=profile)
    except ValueError:
        current, method = None, EDIT_CHAIN
    if current is not None:
        path = garment_path(character_name, item_id, current, "fit")
        record = read_record(path.with_suffix(".json"))
        if path.is_file() and _accepted_on(record, base_model_sha):
            return path, record
    return newest_accepted_fits(character_name, item_id, base_model_sha=base_model_sha).get(method)


def newest_accepted_fits(character_name: str, item_id: str, *,
                         base_model_sha: str = "") -> Dict[str, Tuple[Path, Dict[str, Any]]]:
    """method -> ``(fit GLB, record)`` of the item's newest (GLB mtime)
    accepted fit made with that method (``fit_method``); with
    ``base_model_sha`` only fits accepted on that base model. Read-only:
    never creates ``garments/``."""
    best: Dict[str, Tuple[int, Path, Dict[str, Any]]] = {}
    root = _root(character_name)
    for (iid, _fsig), files in stored_groups(character_name).items():
        if iid != item_id:
            continue
        for path in files:
            if path.suffix != ".glb" or path.parent != root:
                continue
            record = read_record(path.with_suffix(".json"))
            if record.get("accepted") is not True:
                continue
            if base_model_sha and not _accepted_on(record, base_model_sha):
                continue
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            method = fit_method(record)
            if method not in best or mtime > best[method][0]:
                best[method] = (mtime, path, record)
    return {method: (path, record) for method, (_mtime, path, record) in best.items()}


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
    """Mark ``step`` of the item running (SYSTEM time). A running run
    replaces the previous run's failure: the status never shows a step
    running together with an older ``failed`` record."""
    from app.core.timeutils import utc_now
    with _status_lock:
        _running[(character_name, item_id)] = (step, utc_now())
        _failed.pop((character_name, item_id), None)


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
