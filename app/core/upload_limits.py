"""Size and type limits for user uploads (SEC-7).

Every upload route used to call ``await file.read()`` on an unbounded body and
write the bytes straight to disk. Two consequences: one ordinary logged-in user
could fill the world's storage with a single request, and an "image" was only
ever checked by its FILE NAME — a ``.png`` carrying a ZIP, an HTML page or a
decompression bomb landed in the gallery unquestioned.

This module is the one place that says how big an upload may be and what an
image has to look like:

- :func:`guard_content_length` refuses an oversized request BEFORE the body is
  parsed (the only point where nothing has been spooled to disk yet); use it
  wherever the handler has the ``Request`` in hand.
- :func:`read_upload_capped` reads an ``UploadFile`` chunk by chunk and stops
  at the cap, so the process never holds more than the cap in memory.
- :func:`ensure_image` decides by MAGIC BYTES, not by the file name, and
  rejects an image whose pixel count would blow up on decode.

The cap is ``server.max_upload_mb`` (Admin → Settings → Server), default 25.
Two kinds of upload have their own, deliberately larger ceiling:
:data:`MODEL_UPLOAD_MAX_BYTES` for a 3D model (GLB/FBX + texture) and
:func:`max_pack_bytes` for a ZIP import, which is the marketplace's own cap.
``config.get`` returns ``None`` for a plain scalar until the settings page has
been saved once — ``migrate_file()`` seeds no scalar defaults — so the schema
default is the fallback, the same shape ``server._cors_origins`` uses.
"""
from __future__ import annotations

import io
from typing import Optional

from fastapi import HTTPException

from app.core import config

#: Read granularity for :func:`read_upload_capped`.
_CHUNK = 1024 * 1024

#: Hard ceiling on the pixel count of an uploaded image. 64 MP is four times a
#: 4K frame (3840*2160 = 8.3 MP) and still only ~256 MB of RGBA once decoded —
#: above that an "image" is a decompression bomb, not a picture. Pillow's own
#: ``MAX_IMAGE_PIXELS`` (~178 MP) stays untouched: it is a process-wide global
#: and the generation pipeline must not be re-tuned from an upload guard.
MAX_IMAGE_PIXELS = 64_000_000

#: Cap for an uploaded 3D MODEL (GLB/FBX + its texture). Deliberately its own
#: number and not ``server.max_upload_mb``: a rigged character mesh with an
#: embedded 2K texture is tens of megabytes, while the player-facing image cap
#: is meant to stay small. It is the ONE ceiling for every model upload route
#: (character, location, room, prop) — each of them used to carry its own copy
#: of the same 100 MB.
MODEL_UPLOAD_MAX_BYTES = 100 * 1024 * 1024

#: Magic-byte prefixes per image format. WebP needs the second check below
#: ("RIFF" + 4 size bytes + "WEBP"), so it is not in this table.
_MAGIC = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
}

#: File-name extension → the format its bytes must actually have.
EXT_FORMAT = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".webp": "webp",
}


def max_upload_bytes() -> int:
    """The configured per-file upload cap in bytes (``server.max_upload_mb``).

    Unset, empty or unparsable falls back to the schema default; the value is
    clamped into [1, 4096] MB so a typo cannot disable the cap.
    """
    from app.core.config_schema import SECTIONS
    field = SECTIONS["server"]["fields"]["max_upload_mb"]
    raw = config.get("server.max_upload_mb", None)
    if raw is None or raw == "":
        raw = field["default"]
    try:
        mb = int(raw)
    except (TypeError, ValueError):
        mb = int(field["default"])
    return max(int(field["min"]), min(int(field["max"]), mb)) * 1024 * 1024


def max_pack_bytes() -> int:
    """The configured cap for an uploaded ZIP pack, in bytes.

    An import route takes a whole content pack (a character, a location, a
    prop, an item bundle, a states block), which is legitimately far bigger
    than a picture — so it gets the marketplace's cap
    (``content_marketplace.max_pack_mb``, default 500 MB) instead of
    ``server.max_upload_mb``. Delegates to the ONE function that reads that
    field, so an upload and a catalog download can never drift apart; the
    import is local because that function lives in the marketplace route.
    """
    from app.routes.content_packs import _max_pack_mb
    return _max_pack_mb() * 1024 * 1024


def _mb(nbytes: int) -> str:
    """Render a byte cap as MB for an error message."""
    value = nbytes / (1024 * 1024)
    return str(int(value)) if float(value).is_integer() else f"{value:.3g}"


def guard_content_length(request, *, max_bytes: Optional[int] = None,
                         what: str = "upload") -> None:
    """Refuse an oversized request by its ``Content-Length`` header.

    Called BEFORE ``await request.form()`` this is the only check that keeps a
    huge body from being spooled to disk by the multipart parser at all. A
    missing or unparsable header is not an error — the chunked read downstream
    still enforces the same cap.
    """
    limit = max_upload_bytes() if max_bytes is None else int(max_bytes)
    raw = request.headers.get("content-length")
    if not raw:
        return
    try:
        declared = int(raw)
    except (TypeError, ValueError):
        return
    if declared > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{what} is too large ({_mb(declared)} MB); "
                   f"the limit is {_mb(limit)} MB (server.max_upload_mb)")


async def read_upload_capped(file, *, max_bytes: Optional[int] = None,
                             what: str = "upload") -> bytes:
    """Read an ``UploadFile`` in chunks and stop at the cap.

    Returns the bytes, or raises ``413`` as soon as the cap is exceeded — the
    process never holds more than ``max_bytes`` + one chunk in memory, and the
    remainder of the file is never read.
    """
    limit = max_upload_bytes() if max_bytes is None else int(max_bytes)
    buf = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"{what} exceeds the {_mb(limit)} MB limit "
                       "(server.max_upload_mb)")
    return bytes(buf)


def sniff_image_format(data: bytes) -> str:
    """The image format the BYTES declare, or "" when they declare none.

    Only the four formats the upload routes accept are recognised — anything
    else (ZIP, HTML, a script, a truncated file) returns "".
    """
    for fmt, prefixes in _MAGIC.items():
        if any(data.startswith(p) for p in prefixes):
            return fmt
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def ensure_mp4(data: bytes, *, what: str = "video") -> None:
    """Validate uploaded bytes as an MP4 by its ``ftyp`` box (415 otherwise).

    The character gallery accepts short clips beside its pictures, and a clip
    is checked the same way a picture is: by what the bytes say, not by the
    name. An ISO base-media file starts with a box length followed by the
    ``ftyp`` type at offset 4.
    """
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise HTTPException(status_code=415,
                            detail=f"{what} is not an MP4 file")


def ensure_image(data: bytes, *, filename: str = "",
                 what: str = "image") -> str:
    """Validate uploaded bytes as an image and return the detected format.

    - the magic bytes must name one of the supported formats (415 otherwise),
    - when ``filename`` carries a known extension, the bytes must match it
      (415 otherwise) — a ``.png`` whose body is a JPEG is a mislabelled file,
      a ``.png`` whose body is a ZIP is an attack,
    - the header must parse and stay under :data:`MAX_IMAGE_PIXELS` (413).

    Only the header is read; the pixel data is never decoded here.
    """
    fmt = sniff_image_format(data)
    if not fmt:
        raise HTTPException(
            status_code=415,
            detail=f"{what} is not a PNG, JPEG, GIF or WebP file")
    if filename:
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        expected = EXT_FORMAT.get(ext)
        if expected and expected != fmt:
            raise HTTPException(
                status_code=415,
                detail=f"{what} claims to be {ext} but its content is {fmt}")

    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
    except HTTPException:
        raise
    except Exception:
        # Includes Pillow's DecompressionBombError — an unreadable or absurdly
        # large header is refused the same way.
        raise HTTPException(status_code=415,
                            detail=f"{what} could not be read as an image")
    if width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(
            status_code=413,
            detail=f"{what} is {width}x{height} pixels; the limit is "
                   f"{MAX_IMAGE_PIXELS // 1_000_000} megapixels")
    return fmt
