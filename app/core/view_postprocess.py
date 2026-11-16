"""CPU post-processing of a stored reference view (Ruling A146) — generic; a package supplies the operation.

A reference view (today: the base-body views that feed the base mesh and the dressed edits) may be handed
through an OPERATION after it is accepted: an image-in, image-out step on the CPU, no image job. The core
names no operation. A package registers a contributor of ``CAPABILITY``
(``hooks.register_provider(CAPABILITY, describe, owner=<package>, multiple=True)``); ``describe()`` answers::

    {"id": str, "label": str, "description": str,
     "views": [view, ...],                        # the views it applies to
     "params": {name: {type, label, default, min, max, step, description}},
     "apply": fn(image: PIL.Image, *, view: str, params: dict) -> {"image": PIL.Image | None,
                                                                   "found": int, "regions": list,
                                                                   "seconds": float}}

``image`` None = nothing to change in this view. The alpha channel of the result must equal the input's (the
silhouette is not the operation's to change); ``process`` refuses a result whose matte differs.

STORAGE, like the side-view mirror (``view_facing``): the stored file is replaced in place, so every reader
of its CONTENT (the base model's ``view_images_sha256``, a dressed view's ``base_image_sha256``) follows; the
original bytes stay in ``<dir>/postprocessed/<file name>`` (``KEEP_DIR``) and the sidecar records
``postprocess``: ``{op, params, found, at, original_sha256, result_sha256}``. ``restore`` writes the original
back byte for byte. A view mirrored after its processing (``view_facing.toggle_mirror``) is still restored:
the original is mirrored the same way and the mirror record follows.

SETTING. Per world ``base_body.reference_postprocess`` (operation ids, comma separated) is the default; a
character may turn one operation on or off for itself (profile ``reference_postprocess``: ``{op id: bool}``).
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("view_postprocess")

#: The hook capability whose contributors describe the operations.
CAPABILITY = "reference_postprocess"
#: Subfolder beside a processed view that keeps its original bytes.
KEEP_DIR = "postprocessed"
#: Sidecar key of the record.
RECORD_KEY = "postprocess"
#: Profile key of the per-character choices.
PROFILE_KEY = "reference_postprocess"
#: World config key of the default operations.
CONFIG_KEY = "base_body.reference_postprocess"

NOT_RESTORABLE = ("The view changed since it was processed (rendered or edited again) — its kept original "
                  "no longer belongs to it")
SILHOUETTE_CHANGED = "The operation changed the silhouette of the view — result discarded"


class NotRestorable(RuntimeError):
    """The stored view is no longer the processed result (re-rendered meanwhile)."""


# --- Operations ---------------------------------------------------------------

def operations() -> Dict[str, Dict[str, Any]]:
    """id -> descriptor of every operation a package supplies now (a contributor that fails is skipped)."""
    from app.core import hooks
    out: Dict[str, Dict[str, Any]] = {}
    for fn in hooks.get_providers(CAPABILITY):
        try:
            desc = fn()
        except Exception:  # noqa: BLE001 — one package never breaks the others
            logger.exception("A %s contributor failed", CAPABILITY)
            continue
        if isinstance(desc, dict) and desc.get("id") and callable(desc.get("apply")):
            out[str(desc["id"])] = desc
    return out


def public_descriptor(desc: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON-safe part of a descriptor (no callable)."""
    return {k: v for k, v in desc.items() if k != "apply"}


def default_params(desc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: spec.get("default") for k, spec in (desc.get("params") or {}).items() if isinstance(spec, dict)}


def world_default_ids() -> List[str]:
    from app.core import config
    raw = config.get(CONFIG_KEY, "") or ""
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def character_choices(profile: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    raw = (profile or {}).get(PROFILE_KEY)
    return {str(k): bool(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def enabled_ids(profile: Optional[Dict[str, Any]], available: Optional[Dict[str, Any]] = None) -> List[str]:
    """The operations on for a character: its own choice, else the world default — only supplied ones."""
    available = operations() if available is None else available
    own = character_choices(profile)
    world = set(world_default_ids())
    return [op for op in available if own.get(op, op in world)]


def set_character_choice(character_name: str, op_id: str, enabled: Optional[bool]) -> bool:
    """Store a character's own choice for ``op_id`` (None = follow the world default)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        choices = character_choices(profile)
        if enabled is None:
            choices.pop(op_id, None)
        else:
            choices[op_id] = bool(enabled)
        if choices:
            profile[PROFILE_KEY] = choices
        else:
            profile.pop(PROFILE_KEY, None)
        return save_character_profile(character_name, profile)


# --- Files --------------------------------------------------------------------

def original_path(path: Path) -> Path:
    return Path(path).parent / KEEP_DIR / Path(path).name


def record_of(path: Path) -> Optional[Dict[str, Any]]:
    from app.core.view_facing import read_sidecar
    rec = read_sidecar(path).get(RECORD_KEY)
    return rec if isinstance(rec, dict) else None


def _sha(data: bytes) -> str:
    from app.core.view_facing import sha256_bytes
    return sha256_bytes(data)


def _lock(path: Path):
    # The mirror's lock: a mirror and a post-process of one file never interleave.
    from app.core.keyed_lock import keyed_lock
    return keyed_lock("view_mirror", str(Path(path).resolve()))


def _unprocessed(path: Path, current: bytes, record: Optional[Dict[str, Any]]) -> Optional[bytes]:
    """The bytes the view would have without its processing; None when that cannot be known any more."""
    if not record:
        return current
    original = original_path(path)
    if not original.is_file():
        return None
    kept = original.read_bytes()
    if _sha(kept) != record.get("original_sha256"):
        return None
    sha = _sha(current)
    if sha == record.get("result_sha256"):
        return kept
    from app.core import view_facing
    mirror = view_facing.mirror_record(path)
    if mirror and mirror.get("original_sha256") == record.get("result_sha256") and mirror.get("mirrored_sha256") == sha:
        return view_facing.mirrored_bytes(kept)
    return None


def _encode(image, fmt: str) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **({"quality": 95} if fmt in ("JPEG", "WEBP") else {}))
    return out.getvalue()


def run(data: bytes, view: str, desc: Dict[str, Any], params: Optional[Dict[str, Any]] = None
        ) -> Dict[str, Any]:
    """Run one operation on image bytes, nothing stored: ``{data|None, found, regions, seconds}``. Raises
    ``ValueError`` when the result's matte differs from the input's."""
    import numpy as np
    from PIL import Image
    merged = {**default_params(desc), **(params or {})}
    with Image.open(io.BytesIO(data)) as opened:
        fmt = opened.format or "PNG"
        src = opened.convert("RGBA")
    result = desc["apply"](src, view=view, params=merged) or {}
    image = result.get("image")
    out = {"found": int(result.get("found") or 0), "regions": result.get("regions") or [],
           "seconds": round(float(result.get("seconds") or 0.0), 3), "params": merged, "data": None}
    if image is None:
        return out
    if not np.array_equal(np.asarray(image.convert("RGBA"))[..., 3], np.asarray(src)[..., 3]):
        raise ValueError(SILHOUETTE_CHANGED)
    out["data"] = _encode(image if fmt == "PNG" else image.convert("RGB"), fmt)
    return out


def process(path: Path, view: str, op_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Process a stored view in place (from its unprocessed bytes when it is processed already). Returns the
    record (``found`` 0 = nothing changed; then no original is kept). Raises ``KeyError`` for an operation
    nobody supplies, ``NotRestorable`` when the unprocessed bytes are not known any more."""
    from app.core import view_facing
    from app.core.timeutils import utc_now_iso
    desc = operations().get(op_id)
    if desc is None:
        raise KeyError(op_id)
    path = Path(path)
    with _lock(path):
        current = path.read_bytes()
        meta = view_facing.read_sidecar(path)
        old = meta.get(RECORD_KEY) if isinstance(meta.get(RECORD_KEY), dict) else None
        base = _unprocessed(path, current, old)
        if base is None:
            raise NotRestorable(NOT_RESTORABLE)
        res = run(base, view, desc, params)
        record = {"op": op_id, "params": res["params"], "found": res["found"], "seconds": res["seconds"],
                  "at": utc_now_iso()}
        if res["data"] is None:
            if old:
                view_facing._atomic_write(path, base)
                original_path(path).unlink(missing_ok=True)
            meta[RECORD_KEY] = record
        else:
            view_facing._atomic_write(original_path(path), base)
            view_facing._atomic_write(path, res["data"])
            record.update(original_sha256=_sha(base), result_sha256=_sha(res["data"]))
            meta[RECORD_KEY] = record
        _follow_mirror(meta, path, current)
        view_facing._atomic_write(path.with_suffix(".json"),
                                  json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    view_facing._invalidate_figure()
    logger.info("View %s: %s found %d (%.2fs)", path.name, op_id, record["found"], record["seconds"])
    return record


def restore(path: Path) -> bool:
    """Write a processed view's original back; False when it was not processed. ``NotRestorable`` when the
    stored view is no longer the processed result."""
    from app.core import view_facing
    path = Path(path)
    with _lock(path):
        meta = view_facing.read_sidecar(path)
        old = meta.get(RECORD_KEY) if isinstance(meta.get(RECORD_KEY), dict) else None
        if old is None:
            return False
        current = path.read_bytes()
        base = _unprocessed(path, current, old)
        if base is None:
            raise NotRestorable(NOT_RESTORABLE)
        if base != current:
            view_facing._atomic_write(path, base)
        original_path(path).unlink(missing_ok=True)
        meta.pop(RECORD_KEY, None)
        _follow_mirror(meta, path, current)
        view_facing._atomic_write(path.with_suffix(".json"),
                                  json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    view_facing._invalidate_figure()
    logger.info("View %s restored to its original", path.name)
    return True


def _follow_mirror(meta: Dict[str, Any], path: Path, before: bytes) -> None:
    """A mirrored view whose content changed here: its mirror record and kept pre-mirror bytes follow (so a
    later "turn back" gives the matching pixels, not the bytes from before this step)."""
    from app.core import view_facing
    mirror = meta.get("mirrored") if isinstance(meta.get("mirrored"), dict) else None
    if not mirror:
        return
    now = path.read_bytes()
    if now == before:
        return
    unmirrored = view_facing.mirrored_bytes(now)
    if mirror.get("original_kept", True):
        view_facing._atomic_write(view_facing.original_path(path), unmirrored)
    mirror.update(original_sha256=_sha(unmirrored), mirrored_sha256=_sha(now))


# --- Hooks into the view pipeline ------------------------------------------------

def after_view_accepted(character_name: str, view: str, path: Optional[Path], *,
                        profile: Optional[Dict[str, Any]] = None) -> None:
    """Run every operation that is on for the character over a just-stored view. Never raises: a failing
    operation leaves the view as rendered (logged)."""
    if path is None:
        return
    try:
        if profile is None:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
        available = operations()
        for op_id in enabled_ids(profile, available):
            if view in (available[op_id].get("views") or [view]):
                process(Path(path), view, op_id)
    except Exception:  # noqa: BLE001 — the rendered view stays usable
        logger.exception("Post-process of %s %s view failed", character_name, view)


def tile_state(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """The record of a stored view for the UI, with whether a restore is possible."""
    if path is None:
        return None
    rec = record_of(path)
    if rec is None:
        return None
    out = dict(rec)
    try:
        out["restorable"] = _unprocessed(Path(path), Path(path).read_bytes(), rec) is not None
    except OSError:
        out["restorable"] = False
    return out


def preview(path: Path, view: str, op_id: str, params: Optional[Dict[str, Any]] = None
            ) -> Dict[str, Any]:
    """``{before, after|None, found, seconds}`` (PNG bytes) of the operation over the UNPROCESSED view; nothing
    stored. ``NotRestorable`` when the unprocessed bytes are unknown."""
    desc = operations().get(op_id)
    if desc is None:
        raise KeyError(op_id)
    current = Path(path).read_bytes()
    base = _unprocessed(Path(path), current, record_of(path))
    if base is None:
        raise NotRestorable(NOT_RESTORABLE)
    res = run(base, view, desc, params)
    return {"before": base, "after": res["data"], "found": res["found"], "seconds": res["seconds"]}

