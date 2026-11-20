"""Reference pictures of a character's figure — where they are stored and how they are read (Ruling A125, user rule
2026-11-16): the plain body's full-body reference (``full_body_reference``) generated or uploaded lives in
``model_refs/references``, never in the gallery; a picture PICKED from the gallery stays there. A record is
``{image, sha256, origin, …}`` (``full_body_reference._record``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("reference_images")


def _valid(record: Any) -> bool:
    return (isinstance(record, dict) and isinstance(record.get("image"), str) and bool(record["image"])
            and Path(record["image"]).name == record["image"] and isinstance(record.get("sha256"), str)
            and bool(record["sha256"]))


#: The sub-folder of ``model_refs`` that holds the reference pictures made FOR a figure — generated or uploaded
#: as a reference: never the gallery (user rule 2026-11-16, with Ruling A125). A folder,
#: so no file name in it is read as a signature of ``model_refs``. A picture PICKED from the gallery (origin
#: "gallery", or an older record without an origin) stays in the gallery.
REFERENCES_DIR = "references"
#: Record origins whose file lives in ``REFERENCES_DIR``.
STORED_ORIGINS = ("generated", "upload")


def references_dir(character_name: str) -> Path:
    """``model_refs/references`` of the character (not created)."""
    from app.core.model_refs import get_model_refs_dir
    return get_model_refs_dir(character_name) / REFERENCES_DIR


def _folder(character_name: str, record: Dict[str, Any]) -> Path:
    from app.models.character import get_character_images_dir
    return (references_dir(character_name) if record.get("origin") in STORED_ORIGINS
            else get_character_images_dir(character_name))


def image_path(character_name: str, record: Optional[Dict[str, Any]]) -> Optional[Path]:
    """The file of ``record``: in ``references_dir`` for a generated or uploaded reference
    (``STORED_ORIGINS``), else in the gallery (a pick); None when it is gone or the name points outside."""
    if not record or not _valid(record):
        return None
    try:
        root = _folder(character_name, record).resolve()
        path = (root / record["image"]).resolve()
        return path if path.is_relative_to(root) and path.is_file() else None
    except (OSError, RuntimeError, ValueError):
        return None


def reference_url(character_name: str, path: Optional[Path]) -> str:
    """The URL of a reference file (``image_path``): one in ``references_dir`` through the figure route
    ``/characters/<c>/figure/reference-image/<name>``, a gallery one through ``/characters/<c>/images/<name>``;
    ``?v=`` its mtime. "" for None or a file gone."""
    from urllib.parse import quote
    if path is None:
        return ""
    try:
        stamp = path.stat().st_mtime_ns
        stored = path.parent.resolve() == references_dir(character_name).resolve()
    except OSError:
        return ""
    where = "figure/reference-image" if stored else "images"
    return f"/characters/{quote(character_name, safe='')}/{where}/{quote(path.name, safe='')}?v={stamp}"


def store_reference(character_name: str, data: bytes, suffix: str, tag: str) -> str:
    """Bytes (a generated picture, or an upload already capped and checked by its route) into
    ``references_dir`` as ``<name>_<stamp>_<tag><suffix>`` — never the gallery. Returns the file name."""
    import time
    suffix = (suffix or ".png").lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("Format not supported — PNG, JPEG or WebP")
    folder = references_dir(character_name)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{character_name}_{int(time.time())}_{tag}"
    target = folder / f"{stem}{suffix}"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"{stem}{n}{suffix}"
    target.write_bytes(data)
    return target.name


def move_gallery_references(character_name: str) -> List[str]:
    """One-time move (user rule 2026-11-16, idempotent): the plain body's full-body reference, when it is still
    in the GALLERY although its origin stores it in ``references_dir`` (``STORED_ORIGINS`` — generated or
    uploaded before the rule), is moved there with its ``.json`` sidecar (``os.replace``, one log line). The
    record keeps the file NAME, which now resolves in ``references_dir`` (``image_path``) — so no pointer
    changes. The profile image is never moved; unreferenced pictures stay in the gallery. Returns the moved
    names."""
    import os
    from app.core.keyed_lock import keyed_lock
    from app.core import full_body_reference
    from app.models.character import get_character_images_dir, get_character_profile
    moved: List[str] = []
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        records = [profile.get(full_body_reference.PROFILE_KEY)]
        gallery = get_character_images_dir(character_name)
        target_dir = references_dir(character_name)
        for record in records:
            if not isinstance(record, dict) or record.get("origin") not in STORED_ORIGINS:
                continue
            name = str(record.get("image") or "")
            if not name or Path(name).name != name or name == profile.get("profile_image"):
                continue
            source = gallery / name
            if not source.is_file() or (target_dir / name).exists():
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            os.replace(source, target_dir / name)
            sidecar = source.with_suffix(".json")
            if sidecar.is_file():
                os.replace(sidecar, (target_dir / name).with_suffix(".json"))
            logger.info("Reference picture of %s moved out of the gallery: %s", character_name, name)
            moved.append(name)
    if moved:
        from app.core import figure
        figure.invalidate()
    return moved


def move_all_gallery_references() -> int:
    """``move_gallery_references`` for every character (boot); a failing character is logged and skipped."""
    from app.models.character import list_available_characters
    total = 0
    for name in list_available_characters():
        try:
            total += len(move_gallery_references(name))
        except Exception as e:  # noqa: BLE001 — one character never stops the boot
            logger.warning("Reference pictures of %s not moved: %s", name, e)
    return total
