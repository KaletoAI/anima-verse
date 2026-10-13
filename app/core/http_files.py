"""Conditional file serving — the shared ETag/If-None-Match plumbing.

For large, practically immutable files (3D models, textures, animation
clips): a cheap stat-based ETag lets clients revalidate instead of
re-downloading 5–30 MB. One implementation for every route that serves such
files (characters, assets).
"""
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, Response


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

    Cache mtimes track retention, so their content-addressed names supply a
    stable ETag across touches. The original uses the normal stat-based ETag.
    """
    from app.core.glb_delivery import delivery_path
    served = path if disposition == "attachment" else delivery_path(path)
    etag = f'"meshopt-{served.stem}"' if served != path else None
    return etag_file_response(served, request, "model/gltf-binary",
                              cache_control=cache_control, disposition=disposition,
                              filename=path.name, etag=etag)
