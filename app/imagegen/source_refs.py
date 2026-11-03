"""Reference images of a SOURCE image — what a regenerate renders with.

A regenerate repeats an existing image, so the people in it keep the
reference images they were rendered with: the outfit, nudity and look of
THAT moment, not the character's current outfit (2026-11-01: a nude scene
came back in the white dress the character wears today). Only a person the
dialog adds, or a room the dialog changes, resolves live.

An image's meta names its references twice:
  * ``reference_images`` — {slot: file name}, what the image info, the
    character detection and the logs read;
  * ``reference_paths`` — {slot: path relative to the world's storage dir},
    written since 2026-11-01 so the exact file is found again.
Older images carry only the names; ``source_references`` looks those up in
the characters' directories and the location's gallery.
"""
import glob
from pathlib import Path
from typing import Dict, Iterable, Optional

from app.core.log import get_logger

logger = get_logger("source_refs")


def _storage() -> Path:
    from app.core.paths import get_storage_dir
    return get_storage_dir().resolve()


def meta_paths(refs: Dict[str, str]) -> Dict[str, str]:
    """``reference_paths`` for an image meta: {slot: storage-relative path}.
    A slot whose file lies outside the world's storage is left out."""
    storage = _storage()
    out: Dict[str, str] = {}
    for slot, path in (refs or {}).items():
        if not path:
            continue
        try:
            out[slot] = Path(path).resolve().relative_to(storage).as_posix()
        except (ValueError, OSError):
            continue
    return out


def _inside_storage(path: Path) -> Optional[Path]:
    """The resolved file when it exists inside the storage dir, else None —
    a meta value never reaches a file outside the world."""
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(_storage())
    except (ValueError, OSError):
        return None
    from app.core.screenshot_sources import SOURCE_DIR
    if SOURCE_DIR in relative.parts:
        # Composition inputs depict the scene, never a person's appearance.
        return None
    return resolved if resolved.is_file() else None


def _find_by_name(filename: str, names: Iterable[str], location_id: str) -> Optional[Path]:
    """An old meta's bare file name: search the named characters' directories,
    then the location's gallery, then every gallery."""
    if not filename or Path(filename).name != filename or filename in (".", ".."):
        return None
    from app.models.character import get_user_characters_dir
    pattern = glob.escape(filename)
    chars = get_user_characters_dir()
    for name in names:
        if not name or Path(name).name != name:
            continue
        base = chars / name
        if base.is_dir():
            hit = next(base.rglob(pattern), None)
            if hit is not None:
                return _inside_storage(hit)
    gallery = _storage() / "world_gallery"
    if location_id and Path(location_id).name == location_id:
        candidate = gallery / location_id / filename
        if candidate.is_file():
            return _inside_storage(candidate)
    hit = next(gallery.glob(f"*/{pattern}"), None) if gallery.is_dir() else None
    return _inside_storage(hit) if hit is not None else None


def source_references(meta: Dict, *, names: Iterable[str] = (),
                      location_id: str = "") -> Dict:
    """``{"persons": {name: path}, "room": path}`` — the existing reference
    files of a source image, sorted by what they show: a file under
    ``characters/<name>/`` belongs to that person, one under ``world_gallery/``
    is the room. Missing files are left out (that slot resolves live)."""
    meta = meta or {}
    rel_paths = meta.get("reference_paths") or {}
    file_names = meta.get("reference_images") or {}
    names = [n for n in dict.fromkeys(
        list(names) + list(meta.get("character_names") or [])) if n]
    location_id = location_id or str(meta.get("location") or "")
    storage = _storage()
    from app.models.character import get_user_characters_dir
    chars = get_user_characters_dir().resolve()
    gallery = storage / "world_gallery"
    out: Dict = {"persons": {}, "room": ""}
    for slot in dict.fromkeys(list(rel_paths) + list(file_names)):
        path = None
        rel = rel_paths.get(slot)
        if isinstance(rel, str) and rel:
            path = _inside_storage(storage / rel)
        if path is None and isinstance(file_names.get(slot), str):
            path = _find_by_name(file_names[slot], names, location_id)
        if path is None:
            continue
        try:
            parts = path.relative_to(chars).parts
            person = parts[0] if len(parts) > 1 else ""
        except ValueError:
            person = ""
        if person:
            out["persons"].setdefault(person, str(path))
            continue
        try:
            path.relative_to(gallery)
        except ValueError:
            continue  # an item or other reference — resolved live
        out["room"] = out["room"] or str(path)
    return out
