"""CPU post-processing of the plain body's REFERENCE picture (Ruling A146, corrected by A149) — generic; a
package supplies the operation.

WHAT IS PROCESSED (A149, the user: "the goal was to do it on the REFERENCE image, and the rest should come by itself
in image generation"): the ONE picture at the start of the chain every base view is generated from — the plain
body's full-body reference (``full_body_reference.base_image``). The base front is an edit of it, back/left/right
are edits of that front, an outfit's full-body reference is generated from it; so the processed picture is handed
to those generations (``full_body_reference.base_source``) and its content flows into every view by itself. A
generated view is never post-processed. Without a full-body reference nothing is processed: the profile image is a
portrait used everywhere else, and a generated view is not the reference.

An OPERATION is an image-in, image-out step on the CPU, no image job. The core names no operation. A package
registers a contributor of ``CAPABILITY``
(``hooks.register_provider(CAPABILITY, describe, owner=<package>, multiple=True)``); ``describe()`` answers one
descriptor or a list of them (A196 — one contributor per owner)::

    {"id": str, "label": str, "description": str,
     "views": [view, ...],                        # the views it applies to; the reference is a "front" picture
     "params": {name: {type, label, default, min, max, step, description}},
     "apply": fn(image: PIL.Image, *, view: str, params: dict) -> {"image": PIL.Image | None,
                                                                   "found": int, "regions": list,
                                                                   "seconds": float}}

``image`` handed to ``apply`` is RGBA whose alpha is the FIGURE MATTE: a picture with a real matte keeps its own,
an opaque one (a full-body reference on a plain background) gets the figure matte of ``figure_matte``. ``image``
None = nothing to change. The alpha channel of the result must equal the input's (the silhouette is not the
operation's to change); ``run`` refuses a result whose matte differs and stores the result with the picture's own
alpha (an opaque picture stays opaque).

STORAGE: the original is never touched (it may be a gallery picture). The processed picture is a derived copy in
``model_refs/references/postprocessed/<original stem>_pp<key>.png`` with a sidecar (``.json``) that records
``{source_image, source_sha256, steps: [{op, params, found, seconds}], result_sha256 | None, error, at}``; ``key``
is over the original's content and the operations with their params, so another picture or another choice is
another copy (the previous copies of that original are dropped). Turning the operation off = the original is used
again, byte for byte. Nothing found = the original is used (``result_sha256`` None).

SETTING (Ruling A196, user 2026-11-18): per character only — one checkbox per operation (profile
``reference_postprocess``: ``{op id: True}``); an operation the character has not checked is off. There is no
world default any more.

PROMPT-ONLY OPTIONS (A196): a descriptor without ``apply`` changes no picture; it only adds its ``edit_prompt`` /
``edit_negative`` (str or ``fn(profile) -> str``, Ruling A157) to the base front edit while checked. Such an option
is offered beside the CPU operations, never processes the reference and has no preview. The one-time
``scripts/migrate_reference_postprocess_a196.py`` checks explicitly what a character followed from the old world default.

A146 LEFTOVERS: A146 processed the stored base VIEWS in place, keeping their originals in
``model_refs/postprocessed/``. ``restore_legacy_views`` gives those originals back (first touch of the character's
base body, ``base_body.restore_postprocessed_views``).
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("view_postprocess")

#: The hook capability whose contributors describe the operations.
CAPABILITY = "reference_postprocess"
#: A146 leftovers: the subfolder of ``model_refs`` that kept the original bytes of a view processed in place.
KEEP_DIR = "postprocessed"
#: A146 leftovers: the view sidecar key of that record.
RECORD_KEY = "postprocess"
#: The subfolder of ``model_refs/references`` that holds the processed reference copies (A149).
PROCESSED_DIR = "postprocessed"
#: The view the reference picture is handed to an operation as (it shows the figure from the front).
REFERENCE_VIEW = "front"
#: Profile key of the per-character choices.
PROFILE_KEY = "reference_postprocess"

NOT_RESTORABLE = ("The view changed since it was processed (rendered or edited again) — its kept original "
                  "no longer belongs to it")
#: A picture whose alpha leaves less than this share of its pixels transparent has no matte of its own: a generated
#: full-body reference is RGBA with alpha 252..254 everywhere (A152), and as its own "matte" the whole frame was the
#: figure — the operation then searched the background and the upper arms.
OPAQUE_SHARE = 0.001
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
        # Ruling A196: one contributor per package (hooks keys contributors by owner) may describe several.
        for one in (desc if isinstance(desc, list) else [desc]):
            if isinstance(one, dict) and one.get("id"):
                out[str(one["id"])] = one
    return out


def is_image_op(desc: Dict[str, Any]) -> bool:
    """Ruling A196: the descriptor changes the picture (it has ``apply``); else it is a prompt-only option."""
    return callable((desc or {}).get("apply"))


def public_descriptor(desc: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON-safe part of a descriptor (no callable)."""
    return {k: v for k, v in desc.items() if k != "apply" and not callable(v)}


def default_params(desc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: spec.get("default") for k, spec in (desc.get("params") or {}).items() if isinstance(spec, dict)}


def character_choices(profile: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    raw = (profile or {}).get(PROFILE_KEY)
    return {str(k): bool(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def enabled_ids(profile: Optional[Dict[str, Any]], available: Optional[Dict[str, Any]] = None) -> List[str]:
    """The operations checked for a character (Ruling A196: no world default) — only supplied, applying ones."""
    available = operations() if available is None else available
    own = character_choices(profile)
    return [op for op in available if applies(available[op], profile) and own.get(op, False)]


def applies(desc: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> bool:
    """Ruling A170: an operation may declare ``applies`` (profile -> bool); one that does not apply to the
    character is never on for it and is not offered — no processing, no edit text."""
    test = desc.get("applies")
    if not callable(test):
        return True
    try:
        return bool(test(profile or {}))
    except Exception:  # noqa: BLE001 — a package failure counts as "does not apply"
        return False


def set_character_choice(character_name: str, op_id: str, enabled: bool) -> bool:
    """Store a character's checkbox for ``op_id`` (unchecked = the key is dropped)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        choices = character_choices(profile)
        if enabled:
            choices[op_id] = True
        else:
            choices.pop(op_id, None)
        if choices:
            profile[PROFILE_KEY] = choices
        else:
            profile.pop(PROFILE_KEY, None)
        return save_character_profile(character_name, profile)


# --- Running an operation -------------------------------------------------------

def _sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _encode(image, fmt: str) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **({"quality": 95} if fmt in ("JPEG", "WEBP") else {}))
    return out.getvalue()


def figure_matte(data: bytes, size) -> "Any":
    """The figure matte (L image of ``size``) of an opaque picture — the cached BiRefNet mask the garment images use."""
    from app.core.garment_images import _mask_image
    return _mask_image(data, size)


def run(data: bytes, view: str, desc: Dict[str, Any], params: Optional[Dict[str, Any]] = None
        ) -> Dict[str, Any]:
    """Run one operation on image bytes, nothing stored: ``{data|None, found, regions, seconds, params}``. An opaque
    picture (no pixel transparent beyond ``OPAQUE_SHARE``) is handed over with its figure matte as alpha (``figure_matte``); the result keeps the picture's own
    alpha. Raises ``ValueError`` when the operation changed the matte it was given."""
    import numpy as np
    from PIL import Image
    merged = {**default_params(desc), **(params or {})}
    from app.core import cpu_progress
    cpu_progress.sub("postprocess")  # A194: the live step names the operation's run, never raises
    with Image.open(io.BytesIO(data)) as opened:
        fmt = opened.format or "PNG"
        src = opened.convert("RGBA")
    own_alpha = np.asarray(src)[..., 3]
    given = src
    if float((own_alpha < 128).mean()) < OPAQUE_SHARE:
        given = src.copy()
        given.putalpha(figure_matte(data, src.size).convert("L"))
    result = desc["apply"](given, view=view, params=merged) or {}
    image = result.get("image")
    out = {"found": int(result.get("found") or 0), "regions": result.get("regions") or [],
           "seconds": round(float(result.get("seconds") or 0.0), 3), "params": merged, "data": None}
    if image is None:
        return out
    rgba = np.asarray(image.convert("RGBA")).copy()
    if not np.array_equal(rgba[..., 3], np.asarray(given)[..., 3]):
        raise ValueError(SILHOUETTE_CHANGED)
    rgba[..., 3] = own_alpha
    stored = Image.fromarray(rgba, "RGBA")
    out["data"] = _encode(stored if fmt == "PNG" else stored.convert("RGB"), fmt)
    return out


# --- The processed reference (A149) ---------------------------------------------------

def processed_dir(character_name: str) -> Path:
    from app.core.outfit_references import references_dir
    return references_dir(character_name) / PROCESSED_DIR


def _key(source_sha: str, ops: List[str], available: Dict[str, Any]) -> str:
    import hashlib
    raw = json.dumps([source_sha, [[op, default_params(available[op])] for op in ops]], sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _copy_paths(character_name: str, original: Path, key: str) -> Tuple[Path, Path]:
    folder = processed_dir(character_name)
    image = folder / f"{original.stem}_pp{key}.png"
    return image, image.with_suffix(".json")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def reference_record(character_name: str, original: Optional[Path], ops: List[str],
                     available: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The stored record of ``original`` processed by ``ops`` (``{..., "path": copy | None}``), None when it was not
    made yet (or ``ops`` is empty). Read-only, cheap — what a poll uses."""
    available = operations() if available is None else available
    ops = [op for op in ops if op in available and is_image_op(available[op])]
    if original is None or not ops:
        return None
    try:
        source_sha = _sha(Path(original).read_bytes())
    except OSError:
        return None
    image, sidecar = _copy_paths(character_name, Path(original), _key(source_sha, ops, available))
    rec = _read_json(sidecar)
    if rec.get("source_sha256") != source_sha:
        return None
    rec = dict(rec)
    rec["path"] = image if rec.get("result_sha256") and image.is_file() and \
        _sha(image.read_bytes()) == rec["result_sha256"] else None
    return rec


def processed_reference(character_name: str, original: Optional[Path], ops: List[str],
                        available: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """The picture the base front (and an outfit reference) is generated from: ``original`` processed by every
    operation in ``ops`` in turn — made on the first ask (CPU), then read from its copy. The ORIGINAL when ``ops``
    is empty, nothing was found, or an operation failed (logged, recorded as ``error``). Never raises for an
    operation's failure."""
    from app.core.keyed_lock import keyed_lock
    from app.core.view_facing import _atomic_write
    from app.core.timeutils import utc_now_iso
    available = operations() if available is None else available
    ops = [op for op in ops if op in available and is_image_op(available[op])]
    if original is None or not ops:
        return original
    original = Path(original)
    try:
        data = original.read_bytes()
    except OSError:
        return original
    source_sha = _sha(data)
    key = _key(source_sha, ops, available)
    image, sidecar = _copy_paths(character_name, original, key)
    with keyed_lock("reference_postprocess", str(image)):
        rec = reference_record(character_name, original, ops, available)
        if rec is not None:
            return rec["path"] or original
        steps: List[Dict[str, Any]] = []
        current, error = data, ""
        for op in ops:
            try:
                res = run(current, REFERENCE_VIEW, available[op])
            except Exception as e:  # noqa: BLE001 — the original stays the reference
                logger.exception("Post-process %s of the reference %s failed", op, original.name)
                error = f"{op}: {e}"
                break
            steps.append({"op": op, "params": res["params"], "found": res["found"], "seconds": res["seconds"]})
            if res["data"] is not None:
                current = res["data"]
        changed = not error and current != data
        if changed:
            current = _as_png(current)
        folder = image.parent
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(f"{original.stem}_pp*"):
            if old not in (image, sidecar):
                old.unlink(missing_ok=True)
        if changed:
            _atomic_write(image, current)
        else:
            image.unlink(missing_ok=True)
        record = {"source_image": original.name, "source_sha256": source_sha, "steps": steps,
                  "result_sha256": _sha(current) if changed else None, "error": error, "at": utc_now_iso()}
        _atomic_write(sidecar, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"))
    logger.info("Reference %s post-processed (%s): %s", original.name, ", ".join(ops),
                "changed" if changed else ("failed" if error else "nothing found"))
    return image if changed else original


def _as_png(data: bytes) -> bytes:
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        if im.format == "PNG":
            return data
        return _encode(im.convert("RGBA") if im.mode in ("RGBA", "LA", "PA") else im.convert("RGB"), "PNG")


def preview(original: Path, op_id: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{before, after|None, found, seconds}`` (bytes) of ``op_id`` over the reference ``original``; nothing
    stored. ``KeyError`` for an operation nobody supplies."""
    desc = operations().get(op_id)
    if desc is None or not is_image_op(desc):
        raise KeyError(op_id)
    data = Path(original).read_bytes()
    res = run(data, REFERENCE_VIEW, desc, params)
    return {"before": data, "after": res["data"], "found": res["found"], "seconds": res["seconds"]}


# --- A146 leftovers: views processed in place --------------------------------------

def original_path(path: Path) -> Path:
    return Path(path).parent / KEEP_DIR / Path(path).name


def record_of(path: Path) -> Optional[Dict[str, Any]]:
    from app.core.view_facing import read_sidecar
    rec = read_sidecar(path).get(RECORD_KEY)
    return rec if isinstance(rec, dict) else None


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


def restore_legacy_views(refs_dir: Path, view_paths: List[Path]) -> Dict[str, str]:
    """Give every view A146 processed in place its original back: the views named (their sidecar carries a
    record) and every file kept in ``<refs_dir>/postprocessed/``. A record of a view in which nothing was found
    (no kept original) is only dropped from its sidecar. ``{file name: "restored" | "dropped" | error}``."""
    from app.core import view_facing
    done: Dict[str, str] = {}
    paths = {Path(p) for p in view_paths}
    keep = Path(refs_dir) / KEEP_DIR
    if keep.is_dir():
        for kept in keep.iterdir():
            if kept.is_file() and kept.suffix.lower() != ".json":
                paths.add(Path(refs_dir) / kept.name)
    for path in sorted(paths):
        if not path.is_file():
            original_path(path).unlink(missing_ok=True)
            continue
        rec = record_of(path)
        if rec is None:
            continue
        try:
            if not rec.get("result_sha256"):
                with _lock(path):
                    meta = view_facing.read_sidecar(path)
                    meta.pop(RECORD_KEY, None)
                    view_facing._atomic_write(path.with_suffix(".json"),
                                              json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
                done[path.name] = "dropped"
            else:
                restore(path)
                done[path.name] = "restored"
        except NotRestorable as e:
            done[path.name] = str(e)
            logger.warning("A146 view %s not restored: %s", path.name, e)
    try:
        if keep.is_dir() and not any(keep.iterdir()):
            keep.rmdir()
    except OSError:
        pass
    return done
