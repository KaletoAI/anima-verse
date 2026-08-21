"""The CMU trial catalog — browse pool, review state, import into the library.

Three files under ``shared/models/clips-trial`` (``paths.get_trial_clips_dir``,
gitignored, per installation) carry everything:

* ``_catalog.json`` — EVERY take of the CMU database, measured and tagged by
  ``scripts/cmu_enrich_index.py``: description, tags, duplicate group, capture
  rate, a 40-point hip-height sparkline and the ``metrics`` block (posture,
  energy, travel, duration class, loop seam). Its ``clip`` field points at the
  converted trial FBX — ``null`` while the bulk conversion has not reached that
  take yet, which is a NORMAL state the browser shows as "not converted yet".
* the converted clips themselves, ``<main>/<sub>/<id>.fbx`` (a pair adds
  ``__a``/``__b``). They are NOT a clip library: nothing scans them, nothing in
  the game plays them, and they never appear in ``/assets/animation-clips``.
  They exist to be previewed and picked from.
* ``_status.json`` — this module's own file: the REVIEW state a human adds on
  top (favorite, rejected, and what was already imported from a take).

Importing turns a take into a real clip: ``cmu_import.convert_take`` re-cuts it
(window, loop, in place) onto the library rig and writes ``<kind>.fbx`` +
sidecar into ``shared/models/clips``. The catalog keeps the trace, so the same
take is not imported twice by accident.

Both catalog and status are read through a MTIME cache — the catalog is a
multi-megabyte file and an admin browsing it hits the route constantly, but a
background enrich run must still become visible without a restart.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core import cmu_import
from app.core.animation_clips import CLIP_EXTS, clip_entries
from app.core.log import get_logger
from app.core.paths import get_trial_clips_dir
from app.core.timeutils import utc_now

logger = get_logger(__name__)

CATALOG_NAME = "_catalog.json"
STATUS_NAME = "_status.json"

#: A trial clip path is ``<main>/<sub>/<file>`` — three segments, no more.
MAX_TRIAL_SEGMENTS = 3

_catalog_cache: Dict[str, Any] = {"mtime": None, "data": None}
_status_cache: Dict[str, Any] = {"mtime": None, "data": None}


class ClipKindExists(cmu_import.ClipImportError):
    """The target library already has this kind — a 409, not a 422."""


def catalog_path() -> Path:
    return get_trial_clips_dir() / CATALOG_NAME


def status_path() -> Path:
    return get_trial_clips_dir() / STATUS_NAME


def _read_json(path: Path, cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Cached JSON read, invalidated by the file's mtime+size.

    Returns None when the file is not there; a corrupt file is logged and
    treated as absent, never raised at a caller browsing a catalog.
    """
    try:
        st = path.stat()
    except OSError:
        cache["mtime"], cache["data"] = None, None
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    if cache["mtime"] == stamp and cache["data"] is not None:
        return cache["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("unreadable %s: %s", path.name, e)
        return None
    if not isinstance(data, (dict, list)):
        return None
    cache["mtime"], cache["data"] = stamp, data
    return data


def load_catalog() -> Optional[Dict[str, Any]]:
    """The raw ``_catalog.json`` document, None when there is none."""
    data = _read_json(catalog_path(), _catalog_cache)
    return data if isinstance(data, dict) else None


def load_status() -> Dict[str, Dict[str, Any]]:
    """The review state per take id — an empty dict is the normal start."""
    data = _read_json(status_path(), _status_cache) or {}
    takes = data.get("takes") if isinstance(data, dict) else None
    return takes if isinstance(takes, dict) else {}


def _write_status(takes: Dict[str, Dict[str, Any]]) -> None:
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"takes": takes}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    _status_cache["mtime"] = None      # re-read on the next load


def _blank_status() -> Dict[str, Any]:
    return {"favorite": False, "rejected": False, "imported": []}


def take_status(take_id: str) -> Dict[str, Any]:
    """One take's review state, with every field present."""
    row = load_status().get(take_id) or {}
    out = _blank_status()
    out["favorite"] = bool(row.get("favorite"))
    out["rejected"] = bool(row.get("rejected"))
    imported = row.get("imported")
    out["imported"] = imported if isinstance(imported, list) else []
    return out


def set_status(take_id: str, *, favorite: Optional[bool] = None,
               rejected: Optional[bool] = None) -> Dict[str, Any]:
    """Sets the flags that are given and leaves the others alone.

    Favorite and rejected are deliberately independent booleans, not one
    tri-state: a reviewer may well flag a take as worth a look AND later reject
    it without the first click being erased.
    """
    takes = dict(load_status())
    row = dict(takes.get(take_id) or _blank_status())
    if favorite is not None:
        row["favorite"] = bool(favorite)
    if rejected is not None:
        row["rejected"] = bool(rejected)
    row.setdefault("imported", [])
    takes[take_id] = row
    _write_status(takes)
    return take_status(take_id)


def record_import(take_id: str, kind: str, clip_set: str = "",
                  source: str = "free") -> Dict[str, Any]:
    """Appends an import trace to the take. Re-importing the same kind into the
    same set REPLACES the old trace — it is one clip, not two."""
    takes = dict(load_status())
    row = dict(takes.get(take_id) or _blank_status())
    imported = [e for e in (row.get("imported") or [])
                if isinstance(e, dict)
                and not (e.get("kind") == kind and (e.get("set") or "") == clip_set)]
    imported.append({"kind": kind, "set": clip_set, "source": source,
                     "at": utc_now().isoformat()})
    row["imported"] = imported
    row.setdefault("favorite", False)
    row.setdefault("rejected", False)
    takes[take_id] = row
    _write_status(takes)
    return take_status(take_id)


_index_cache: Dict[str, Any] = {"mtime": None, "data": None}


def converted_clips() -> Dict[str, str]:
    """``take id → relative clip path`` from the converter's ``_index.json``
    (a list of records, or a dict keyed by id in older runs); empty when the
    file is missing. A pair's record names its A half."""
    data = _read_json(get_trial_clips_dir() / "_index.json", _index_cache)
    if not data:
        return {}
    records = data.values() if isinstance(data, dict) else data
    out: Dict[str, str] = {}
    for rec in records:
        if isinstance(rec, dict) and rec.get("id") and rec.get("clip"):
            out[str(rec["id"])] = str(rec["clip"])
            for partner in rec.get("pair_takes") or []:
                out.setdefault(str(partner), str(rec["clip"]))
    return out


def catalog_with_status() -> Optional[Dict[str, Any]]:
    """The catalog document with a ``status`` block merged into every take.

    The catalog file itself is never written by this module — the enrich run
    owns it and rebuilds it whole. The review state lives beside it and is
    joined here, at read time.
    """
    data = load_catalog()
    if data is None:
        return None
    status = load_status()
    # Clip paths come LIVE from the converter's _index.json: the enrich run
    # copies them into the catalog only when it runs, and a catalog built
    # while the conversion was still going says "not converted" for clips
    # that have long existed (2026-08-21: "nice UI, but without a preview it
    # is worth nothing"). The index is the converter's own ledger, so a
    # path found there is a file that exists.
    clips = converted_clips()
    takes = []
    for take in data.get("takes") or []:
        if not isinstance(take, dict):
            continue
        row = status.get(take.get("id")) or {}
        if not take.get("clip") and take.get("id") in clips:
            take = {**take, "clip": clips[take["id"]]}
        takes.append({**take, "status": {
            "favorite": bool(row.get("favorite")),
            "rejected": bool(row.get("rejected")),
            "imported": row.get("imported") if isinstance(row.get("imported"), list) else [],
        }})
    return {**data, "takes": takes}


def find_take(take_id: str) -> Optional[Dict[str, Any]]:
    """One take record out of the catalog, None when unknown."""
    data = load_catalog()
    if data is None:
        return None
    for take in data.get("takes") or []:
        if isinstance(take, dict) and take.get("id") == take_id:
            return take
    return None


def resolve_trial_path(rel: str) -> Optional[Path]:
    """``<main>/<sub>/<file>`` → the trial clip file, or None when the request
    is not a legal trial reference.

    Same rules as ``assets.resolve_clip_path``, one segment deeper because the
    trial archive mirrors the CMU category tree: at most three plain segments,
    no empty/``.``/``..``/backslash, only clip extensions, and the resolved
    path must stay inside the trial directory (``resolve()`` on both sides, so
    a symlink pointing out is refused too).
    """
    segments = str(rel or "").split("/")
    if not 1 <= len(segments) <= MAX_TRIAL_SEGMENTS:
        return None
    for seg in segments:
        if not seg or seg in (".", "..") or "\\" in seg:
            return None
    base = get_trial_clips_dir().resolve()
    path = base.joinpath(*segments).resolve()
    if not path.is_relative_to(base):
        return None
    if path.suffix.lower() not in CLIP_EXTS:
        return None
    return path


def trial_clip_urls(take: Dict[str, Any]) -> Dict[str, str]:
    """The preview URLs of a take's converted trial clip(s): ``{"solo"}`` for a
    solo take, ``{"a", "b"}`` for a pair — empty while it is not converted.

    A pair's ``clip`` field already names the A half (``…/18_01__a.fbx``); the
    B half is the same path with the role flipped, exactly the naming rule of
    ``animation_clips.parse_clip_role``.
    """
    clip = str(take.get("clip") or "")
    if not clip:
        return {}
    prefix = "/assets/animation-clips/trial/"
    if take.get("pair") and clip.lower().endswith("__a.fbx"):
        return {"a": f"{prefix}{clip}",
                "b": f"{prefix}{clip[:-len('__a.fbx')]}__b.fbx"}
    return {"solo": f"{prefix}{clip}"}


def pair_takes(take: Dict[str, Any]) -> Tuple[str, str]:
    """``(take_a, take_b)`` for a pair record — the A role first, whichever half
    was selected. ``("", "")`` for a solo take."""
    if not take.get("pair") or not take.get("pair_partner"):
        return "", ""
    me, partner = str(take.get("id")), str(take.get("pair_partner"))
    return (me, partner) if str(take.get("pair_role") or "a") == "a" else (partner, me)


def existing_kinds(clip_set: str = "", source: str = "free") -> List[str]:
    """Kinds the target library already has in that set — what an import would
    overwrite."""
    return sorted({e["kind"] for e in clip_entries()
                   if e["set"] == clip_set and e["source"] == source})


def import_take(take_id: str, kind: str, *, clip_set: str = "",
                start_s: float = 0.0, end_s: Optional[float] = None,
                loop_s: Optional[float] = None, in_place: bool = True,
                overwrite: bool = False, speed: float = 1.0) -> Dict[str, Any]:
    """Converts one catalog take into the FREE library and records the trace.

    A PAIR take always imports BOTH halves — one clip kind, two files — with
    the A role first regardless of which half was selected; ``in_place`` is
    meaningless there (the two roots carry the contact geometry) and ignored.

    Raises ``cmu_import.ClipImportError`` for everything refusable; the
    "kind exists" case raises ``ClipKindExists`` so the route can answer 409.
    """
    take = find_take(take_id)
    if take is None:
        raise cmu_import.ClipImportError(f"unknown take: {take_id}")
    kind = cmu_import.validate_kind(kind)
    cset = str(clip_set or "").strip().lower()
    if not overwrite and kind in existing_kinds(cset):
        raise ClipKindExists(
            f"'{kind}' already exists in the free library"
            f"{f' (set {cset})' if cset else ''} — tick overwrite to replace it")

    take_a, take_b = pair_takes(take)
    if not take_a:
        take_a, take_b = take_id, ""
    res = cmu_import.convert_take(
        kind, take_a, take_b, clip_set=cset, start_s=start_s, end_s=end_s,
        loop_s=loop_s, in_place=bool(in_place) and not take_b,
        source_fps=take.get("framerate") or None, speed=float(speed or 1.0))
    status = record_import(take_id, kind, cset, "free")

    # The pose dropdown and the animation-set fallback both read from the
    # preset caches — a fresh kind has to be selectable at once, not after a
    # restart (same reload the poses editor does after a write).
    try:
        from app.core import expression_pose_maps as epm
        epm.reload_presets()
    except Exception as e:                                   # pragma: no cover
        logger.warning("preset reload after clip import failed: %s", e)

    entry = next((e for e in clip_entries()
                  if e["kind"] == kind and e["set"] == cset and e["source"] == "free"),
                 None)
    logger.info("clip imported: take %s -> %s%s (%.1fs)", take_id,
                f"{cset}/" if cset else "", kind, res["seconds"])
    return {
        "take_id": take_id,
        "kind": kind,
        "set": cset,
        "pair": bool(take_b),
        "sidecar": res["sidecar"],
        "files": [Path(p).name for p in res["outputs"].values()],
        "seconds": res["seconds"],
        "status": status,
        "clip": None if entry is None else {
            "kind": entry["kind"], "role": entry["role"], "set": entry["set"],
            "source": entry["source"], "filename": entry["path"].name,
            "url": "/assets/animation-clips/" + entry["rel"],
        },
    }
