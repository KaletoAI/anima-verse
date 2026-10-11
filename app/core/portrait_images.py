"""Display-only portrait cutouts, kept apart from original identity references.

The source bytes and processing version identify each cached PNG. No crop or
resize is applied: the complete canvas, including hair below the neck, stays.
Call from a worker thread, not the event loop; a cache miss runs rembg.
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path

from app.core.keyed_lock import keyed_lock
from app.core.paths import get_storage_dir
from app.core.upload_limits import MAX_IMAGE_PIXELS

_PROCESSING_VERSION = "u2net-full-canvas-v2"


class PortraitProcessingError(ValueError):
    """The source or segmentation cannot produce a usable alpha portrait."""


def _basename(name: str) -> None:
    if not name or name in (".", "..") or ".." in name or any(
            separator in name for separator in ("/", "\\", "\x00")):
        raise ValueError("Invalid filename or character name")


def _inside(directory: Path, path: Path) -> Path:
    try:
        base = directory.resolve()
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("Invalid image path") from exc
    if resolved == base or not resolved.is_relative_to(base):
        raise ValueError("Image path leaves its directory")
    return resolved


def character_image_path(character_name: str, image_filename: str) -> Path:
    """Resolve an existing gallery source with basename and containment checks."""
    from app.models.character import get_character_dir, get_character_images_dir

    _basename(character_name)
    _basename(image_filename)
    character_dir = _inside(get_storage_dir(), get_character_dir(character_name))
    images_dir = _inside(character_dir, get_character_images_dir(character_name))
    source = _inside(images_dir, images_dir / image_filename)
    if not source.is_file():
        raise FileNotFoundError("Image not found")
    return source


def _validate_alpha(image) -> None:
    low, high = image.getchannel("A").getextrema()
    if high == 0:
        raise PortraitProcessingError("Portrait cutout has no visible pixels")
    if low == 255:
        raise PortraitProcessingError("Portrait cutout is fully opaque")


def _cutout(source_bytes: bytes):
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(source_bytes)) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise PortraitProcessingError("Portrait source exceeds the image pixel limit")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise PortraitProcessingError("Portrait source is not a supported image") from exc

    # Existing cutouts retain every alpha value without a second segmentation.
    if image.getchannel("A").getextrema()[0] < 255:
        _validate_alpha(image)
        return image

    try:
        from app.models.character import _get_rembg_session

        session = _get_rembg_session()
        from rembg import remove

        result_bytes = remove(source_bytes, session=session)
        with Image.open(io.BytesIO(result_bytes)) as result:
            if result.size != image.size:
                raise PortraitProcessingError("Portrait cutout changed the source dimensions")
            cutout = result.convert("RGBA")
        _validate_alpha(cutout)
        return cutout
    except PortraitProcessingError:
        raise
    except Exception as exc:
        raise PortraitProcessingError("Portrait background removal failed") from exc


def transparent_portrait_path(character_name: str, image_filename: str) -> Path:
    """Return a cached full-canvas alpha PNG; never modify the original image.

    Missing sources raise FileNotFoundError, unsafe paths raise ValueError,
    and invalid images or failed segmentation raise PortraitProcessingError.
    The keyed lock serializes concurrent cache misses within this process.
    """
    from app.models.character import get_character_dir

    source = character_image_path(character_name, image_filename)
    source_bytes = source.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    character_dir = _inside(get_storage_dir(), get_character_dir(character_name))
    images_dir = _inside(character_dir, character_dir / "images")
    cache_root = _inside(character_dir, character_dir / ".cache")
    cache = _inside(cache_root, cache_root / "portraits")
    # A cache symlink must not turn cutouts into gallery images.
    if cache.is_relative_to(images_dir):
        raise ValueError("Portrait cache must not be inside the image gallery")
    target = _inside(cache, cache / f"{_PROCESSING_VERSION}-{digest}.png")
    if target.is_file():
        return target

    with keyed_lock("transparent_portrait", str(target)):
        if target.is_file():
            return target
        image = _cutout(source_bytes)
        cache.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=target.stem + ".", suffix=".tmp", dir=cache)
        try:
            with os.fdopen(fd, "wb") as output:
                image.save(output, format="PNG")
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return target
