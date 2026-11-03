"""Private, image-owned composition inputs for screenshot photos.

The hidden subdirectory is outside flat gallery/media/thumb scans. Names bind
each input to exactly one gallery file, so variants never share ownership.
"""
from pathlib import Path
import shutil
from typing import Optional

from app.core.portrait_images import _basename, _inside, character_image_path

SOURCE_DIR = ".screenshot-sources"
_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _companion_path(character: str, filename: str, source_name: str) -> Path:
    _basename(source_name)
    suffix = Path(source_name).suffix.lower()
    if suffix not in _EXTENSIONS or source_name != f"{filename}.source{suffix}":
        raise ValueError("Screenshot source does not belong to this image")
    image = character_image_path(character, filename)
    directory = image.parent / SOURCE_DIR
    if directory.is_symlink():
        raise ValueError("Screenshot source directory is a symlink")
    directory = _inside(image.parent, directory)
    target = directory / source_name
    if target.is_symlink():
        raise ValueError("Screenshot source is a symlink")
    return _inside(directory, target)


def resolve_screenshot_source(character: str, filename: str, meta: dict) -> Optional[Path]:
    """Resolve only a recorded, existing companion; never search for old photos."""
    source_name = meta.get("screenshot_source")
    if not isinstance(source_name, str) or not source_name:
        return None
    try:
        path = _companion_path(character, filename, source_name)
        return path if path.is_file() else None
    except (ValueError, OSError, RuntimeError):
        return None


def store_screenshot_source(character: str, filename: str, source: Path) -> str:
    """Copy an input after successful generation, before disposable upload cleanup."""
    suffix = source.suffix.lower()
    name = f"{filename}.source{suffix}"
    target = _companion_path(character, filename, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return name
