"""Conditional file serving — the shared ETag/If-None-Match plumbing.

For large, practically immutable files (3D models, textures, animation
clips): a cheap stat-based ETag lets clients revalidate instead of
re-downloading 5–30 MB. One implementation for every route that serves such
files (characters, assets). Content-addressed clips and character models use
snapshot_response; the stat-based helpers remain for other callers.
"""
import contextlib
import hashlib
import os
import threading
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import FileResponse, Response, StreamingResponse


def etag_file_response(path: Path, request: Request, media_type: str,
                       cache_control: str = "no-cache",
                       disposition: str = "inline",
                       filename: str | None = None, etag: str | None = None):
    """FileResponse with ETag + If-None-Match. ``cache_control`` is sent on
    both the 304 and the full response ("no-cache" = always revalidate;
    immutable assets may pass e.g. "public, max-age=86400").

    The default ETag combines mtime_ns, size and inode so an atomic
    replacement invalidates it even when size and mtime are preserved.
    Callers may supply an explicit ``etag`` for content-addressed files.

    ``disposition`` is INLINE by default, and that is a deliberate default
    rather than an option nobody sets: everything served through here is an
    asset a client CONSUMES — a texture in a material, a mesh in a scene, a
    PNG in an ``<img>``, a clip in a mixer. Starlette's own default is
    ``attachment``, which turned every such link into a download: clicking a
    picture in an admin strip saved a file instead of showing it (user
    finding 2026-08-21). ``filename`` still rides along, so a save the USER
    asks for (an ``<a download>``, "save image as") keeps the proper name.
    Pass ``"attachment"`` for a route whose whole purpose IS a download.
    """
    stat = path.stat()
    etag = etag or f'"{stat.st_mtime_ns:x}-{stat.st_size:x}-{stat.st_ino:x}"'
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=media_type, filename=filename or path.name,
                        headers=headers, content_disposition_type=disposition)


def glb_file_response(path: Path, request: Request,
                      cache_control: str = "no-cache",
                      disposition: str = "inline"):
    """Serve a delivery GLB with the original filename; downloads keep source bytes.

    Content-addressed delivery names supply a stable ETag. The original uses the normal stat-based ETag.
    """
    from app.core.glb_delivery import delivery_path
    served = path if disposition == "attachment" else delivery_path(path)
    etag = f'"meshopt-{served.stem}"' if served != path else None
    return etag_file_response(served, request, "model/gltf-binary",
                              cache_control=cache_control, disposition=disposition,
                              filename=path.name, etag=etag)


# Byte identity cache: ctime catches edits with restored mtime; bounded to 4096 files.
_versions: OrderedDict[tuple, str] = OrderedDict()
_version_lock = threading.Lock()


def _key(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _cached_version(key: tuple) -> str | None:
    """Read and promote one LRU entry atomically."""
    with _version_lock:
        version = _versions.get(key)
        if version is not None:
            _versions.move_to_end(key)
        return version


def _hash_fd(f, st) -> str:
    """Hash the opened snapshot, rewind it, and remember its byte identity."""
    digest = hashlib.sha256()
    while chunk := f.read(1 << 20):
        digest.update(chunk)
    f.seek(0)
    version = digest.hexdigest()[:16]
    with _version_lock:
        _versions[_key(st)] = version
        _versions.move_to_end(_key(st))
        while len(_versions) > 4096:
            _versions.popitem(last=False)
    return version


def content_version(path: Path, st: os.stat_result | None = None) -> str:
    """First 16 SHA256 hex digits; cache by device, inode, size and both times."""
    if st is not None:
        version = _cached_version(_key(st))
        if version is not None:
            return version
    with open(path, "rb") as f:
        opened = os.fstat(f.fileno())
        version = _cached_version(_key(opened))
        return version if version is not None else _hash_fd(f, opened)


@contextlib.contextmanager
def sibling_stage(dest: Path):
    """Own a unique sibling until its closed contents are published or discarded."""
    fd, name = tempfile.mkstemp(dir=dest.parent, prefix="." + dest.name + ".", suffix=".tmp")
    os.close(fd)
    stage = Path(name)
    try:
        yield stage
    finally:
        stage.unlink(missing_ok=True)


def opened_content_version(f, st) -> str:
    version = _cached_version(_key(st))
    return version if version is not None else _hash_fd(f, st)


def select_opened_delivery(target, f, st, lock=None):
    """Select delivery after releasing publication lock; keep the source snapshot."""
    from app.core.glb_delivery import delivery_path
    served = delivery_path(target, source=f)
    if served == target:
        return target, f, st
    with lock if lock is not None else contextlib.nullcontext():
        try:
            delivery = open(served, "rb")
        except FileNotFoundError:
            return target, f, st
        try:
            delivery_stat = os.fstat(delivery.fileno())
        except BaseException:
            delivery.close()
            raise
    f.close()
    return served, delivery, delivery_stat


def atomic_replace(tmp: Path, dest: Path) -> None:
    """Publish a staged sibling; never copy across filesystems over live bytes."""
    if tmp.parent.resolve() != dest.parent.resolve():
        raise ValueError("atomic replacement requires staging beside the destination")
    os.replace(tmp, dest)


def etag_matches(value: str | None, etag: str) -> bool:
    """Match an exact ETag, a comma-separated list, or a wildcard."""
    return bool(value and any(tag.strip() in (etag, "*") for tag in value.split(",")))


class _SnapshotResponse(StreamingResponse):
    """Close even when an ASGI disconnect happens before body iteration."""
    def __init__(self, body, *, file, **kwargs):
        super().__init__(body, **kwargs)
        self._file = file

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._file.close()


def snapshot_response(path: Path | None, request: Request, *,
                      media_type: str | Callable[[Path], str],
                      version: str | None = None, disposition: str = "inline",
                      filename: str | Callable[[], str | None] | None = None,
                      lock=None, delivery: bool = False, resolve: Callable[[], Path | None] | None = None,
                      _before_stream: Callable[[Path], None] | None = None) -> Response:
    """Choose/open under the publication lock and stream that same descriptor.

    Callable media_type(target) and filename() resolve after path selection.
    _before_stream is a smoke-only hook for atomic replacement after opening.
    Writers must publish sibling staged files with atomic_replace.
    """
    ctx = lock if lock is not None else contextlib.nullcontext()
    with ctx:
        target = resolve() if resolve else path
        if target is None:
            return Response(status_code=404, headers={"Cache-Control": "no-cache"})
        try:
            f = open(target, "rb")
        except FileNotFoundError:
            return Response(status_code=404, headers={"Cache-Control": "no-cache"})
        try:
            st = os.fstat(f.fileno())
            media = media_type(target) if callable(media_type) else media_type
            name = filename() if callable(filename) else filename
        except BaseException:
            f.close()
            raise
    try:
        if delivery and target.suffix.lower() == ".glb":
            target, f, st = select_opened_delivery(target, f, st, lock)
        ver = opened_content_version(f, st)
        if _before_stream is not None:
            _before_stream(target)
        etag = f'"{ver}"'
        cache = "public, max-age=31536000, immutable" if version and version == ver else "no-cache"
        headers = {"ETag": etag, "Cache-Control": cache}
        if etag_matches(request.headers.get("if-none-match"), etag):
            f.close()
            return Response(status_code=304, headers=headers)
        headers["Content-Length"] = str(st.st_size)
        if name:
            encoded = quote(name)
            headers["Content-Disposition"] = (f"{disposition}; filename*=utf-8''{encoded}"
                if encoded != name else f'{disposition}; filename="{name}"')
        def body():
            try:
                while chunk := f.read(1 << 20):
                    yield chunk
            finally:
                f.close()
        return _SnapshotResponse(body(), file=f, media_type=media, headers=headers)
    except BaseException:
        f.close()
        raise
