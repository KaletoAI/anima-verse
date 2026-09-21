"""On-disk thumbnails for gallery tiles (UI-8).

WHY. Every render the image pipeline produces lands in a gallery at its full
resolution — 1024x1536 PNGs and upwards, 1-4 MB each. The player gallery shows
them as ~72-100 px tiles, and until now the tile loaded the ORIGINAL file: a
date block with 80 images pulled tens of megabytes over the wire and decoded
each one at full size (1024*1536*4 B = 6 MB of RGBA per image, regardless of
how small it is drawn).

WHAT THIS IS. One resize path for every image kind a tile view shows. The
route layer (``app/routes/thumbnails.py``) resolves a URL to a source FILE —
through the same sanitising the full-size route uses — and hands it here.

RULES, and why each one is the way it is:

* **Fixed width buckets** (:data:`THUMB_WIDTHS`). An arbitrary ``?w=`` would
  let one caller fill the disk with 4000 variants of the same picture; three
  buckets cap it at three files per source. Anything else is a 400.
* **Never upscale.** A source narrower than the bucket is re-encoded at its
  own width — a blown-up thumbnail is bigger than the original AND worse.
* **WebP output.** It carries alpha, so no per-image format decision is needed
  (a PNG cut-out stays a cut-out) and it is far smaller than a JPEG at the
  same quality. Universally supported by browsers since 2020.
* **EXIF orientation is applied** (``ImageOps.exif_transpose``) — a phone photo
  uploaded into a gallery would otherwise show sideways in the tile and
  upright in the lightbox.
* **Decode guard.** The header's pixel count is checked against
  ``upload_limits.MAX_IMAGE_PIXELS`` BEFORE any pixel is decoded, and the
  magic bytes must name a real image format. A file that is not an image is a
  415, not a traceback.
* **Cache key = source path + mtime + size + width.** A regenerated image
  (same file name, new content) gets a new key, so a stale thumbnail can never
  be served. The old entries of that source and width are unlinked right after
  the new one is written — that is the whole cache-size policy: lazy, and it
  never grows past three files per live source. Thumbnails of a source that
  has VANISHED are dropped on the next request for it.
* **The cache lives beside the world's other caches** — ``<storage>/.cache/
  thumbs`` (as ``content_packs``, ``layout_apply`` and ``map_layout_apply``
  do), NEVER inside the gallery directory itself: galleries are listed by
  directory scan, so a thumbnail dropped there would show up as an image.
* **One generation per key.** Rendering is CPU work on a threadpool thread;
  ``keyed_lock`` makes concurrent first requests for the same thumbnail wait
  for the one that is already rendering instead of all decoding the same 6 MB.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.paths import get_storage_dir
from app.core.upload_limits import MAX_IMAGE_PIXELS, sniff_image_format

logger = get_logger("thumbnails")

#: The only widths a caller may ask for. Derived from the tile sizes in the
#: UI: ~24-48 px icons (96 covers them at DPR 2), the 72-100 px gallery tiles
#: (192 at DPR 2), and the 100-160 px admin cards on a HiDPI screen (384).
THUMB_WIDTHS = (96, 192, 384)

#: Media type of every thumbnail this module writes.
THUMB_MEDIA_TYPE = "image/webp"

_SUFFIX = ".webp"
#: Enough bytes for every magic-byte prefix in ``upload_limits`` (WebP needs 12).
_HEADER_BYTES = 32
_WEBP_QUALITY = 78
#: Hard ceiling on a thumbnail's HEIGHT. A picture far taller than it is wide
#: would otherwise scale to an edge the WebP encoder refuses (its limit is
#: 16383 px); 4096 is far beyond anything a tile needs and keeps the aspect
#: ratio intact for every real image.
_MAX_EDGE = 4096


def parse_width(raw: Any) -> int:
    """The requested bucket width, or a 400.

    Deliberately strict: an unknown width is refused rather than snapped to
    the nearest bucket, because silently serving 192 px for ``?w=200`` would
    hide a client bug forever.
    """
    try:
        width = int(str(raw).strip())
    except (TypeError, ValueError):
        width = -1
    if width not in THUMB_WIDTHS:
        allowed = ", ".join(str(x) for x in THUMB_WIDTHS)
        raise HTTPException(
            status_code=400,
            detail=f"w must be one of {allowed}")
    return width


def cache_dir() -> Path:
    """``<storage>/.cache/thumbs`` — created on first use."""
    d = get_storage_dir() / ".cache" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _source_token(src: Path) -> str:
    """Stable per-SOURCE part of the cache name (its absolute path)."""
    return hashlib.sha256(str(src).encode("utf-8")).hexdigest()[:16]


def _version_token(stat: os.stat_result) -> str:
    """Per-CONTENT part of the cache name (mtime + size)."""
    raw = f"{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def _cache_name(token: str, width: int, version: str) -> str:
    return f"{token}_{width}_{version}{_SUFFIX}"


def _prune_older(token: str, width: int, keep: str) -> None:
    """Drop the thumbnails of the SAME source and width from earlier content."""
    try:
        for old in cache_dir().glob(f"{token}_{width}_*{_SUFFIX}"):
            if old.name != keep:
                old.unlink(missing_ok=True)
    except OSError as exc:  # a cache that cannot be tidied is not an error
        logger.debug("thumb prune failed (%s): %s", token, exc)


def _forget_source(token: str) -> None:
    """Drop every thumbnail of a source file that no longer exists."""
    try:
        for old in cache_dir().glob(f"{token}_*{_SUFFIX}"):
            old.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("thumb forget failed (%s): %s", token, exc)


def _render(src: Path, width: int, out: Path) -> None:
    """Decode ``src``, scale it to at most ``width`` and write ``out``.

    Written to a temp file in the same directory and moved into place, so a
    concurrent reader never sees a half-written thumbnail.
    """
    from PIL import Image, ImageOps

    with src.open("rb") as fh:
        head = fh.read(_HEADER_BYTES)
    if not sniff_image_format(head):
        raise HTTPException(status_code=415,
                            detail="source is not a PNG, JPEG, GIF or WebP file")

    tmp_name = ""
    with Image.open(src) as im:
        # ``Image.open`` is lazy — the size comes from the header, nothing is
        # decoded yet, which is exactly where a bomb has to be caught.
        src_w, src_h = im.size
        if src_w <= 0 or src_h <= 0:
            raise HTTPException(status_code=415, detail="source has no pixels")
        if src_w * src_h > MAX_IMAGE_PIXELS:
            raise HTTPException(
                status_code=413,
                detail=f"source is {src_w}x{src_h} pixels; the limit is "
                       f"{MAX_IMAGE_PIXELS // 1_000_000} megapixels")
        try:
            oriented = ImageOps.exif_transpose(im) or im
        except Exception:  # a broken EXIF block must not lose the thumbnail
            oriented = im
        has_alpha = (oriented.mode in ("RGBA", "LA", "PA")
                     or "transparency" in oriented.info)
        # One scale factor for both edges, so the aspect ratio is kept: the
        # width bucket, never above 1.0 (no upscale), and never so tall that
        # the WebP encoder's own edge limit is hit — a 100x100000 strip is
        # under the megapixel guard but would blow up on save.
        scale = min(width / oriented.width, _MAX_EDGE / oriented.height, 1.0)
        target_w = max(1, min(width, round(oriented.width * scale)))
        target_h = max(1, min(_MAX_EDGE, round(oriented.height * scale)))
        small = oriented.convert("RGBA" if has_alpha else "RGB")
        small = small.resize((target_w, target_h), Image.LANCZOS)
        fd, tmp_name = tempfile.mkstemp(prefix=out.stem + ".", suffix=".tmp",
                                        dir=str(out.parent))
        os.close(fd)
        try:
            small.save(tmp_name, "WEBP", quality=_WEBP_QUALITY, method=4)
        except Exception:
            # A failed encode must not leave a stray .tmp behind in the cache.
            Path(tmp_name).unlink(missing_ok=True)
            raise
    os.replace(tmp_name, out)


def get_thumbnail(src: Path, width: int) -> Path:
    """The cached thumbnail of ``src`` at ``width``, generated on first ask.

    ``width`` must already be one of :data:`THUMB_WIDTHS` (use
    :func:`parse_width`). Raises 404 when the source is gone, 415 when it is
    not an image and 413 when it is too large to decode.
    """
    src = Path(src)
    token = _source_token(src)
    try:
        stat = src.stat()
    except OSError:
        _forget_source(token)
        raise HTTPException(status_code=404, detail="Image not found")

    out = cache_dir() / _cache_name(token, width, _version_token(stat))
    if out.is_file():
        return out
    # Two threads asking for the same missing thumbnail must not both decode
    # the source; the second one finds it finished behind the lock.
    with keyed_lock("thumbnail", out.name):
        if out.is_file():
            return out
        _render(src, width, out)
        _prune_older(token, width, out.name)
    return out
