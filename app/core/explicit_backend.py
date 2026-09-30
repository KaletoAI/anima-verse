"""Route-side guard for an EXPLICIT backend pick (image routing, ruling N3).

A dialog that names a concrete backend asks for exactly that backend — no
routing, no fallback (``development_instructions/plan-image-routing.md``).
The render itself runs in a background thread/task, so a dead pick found
THERE could only be logged: the route had already answered "started" and
its tracked task stayed pending. Every route that starts such a render
therefore resolves the pick FIRST, through this ONE helper, and answers 503
before it creates a track or starts a thread.

The background path keeps its own check (the backend may drop out in
between); this guard only moves the common case to the HTTP answer.

``require_explicit_backend`` is blocking (it probes the matching backends,
network I/O) — call it from sync route bodies that already run in the
threadpool; async route bodies use ``require_explicit_backend_async``, which
runs the same probe off the event loop.
"""
import asyncio

from fastapi import HTTPException

from app.core.log import get_logger

logger = get_logger("explicit_backend")

_MEDIA_LABEL = {"image": "", "video": "video ", "mesh": "mesh "}


def require_explicit_backend(name: str, media: str = "image", *,
                             has_input_image: bool = False):
    """The available backend an explicit pick ``name`` (exact name or glob)
    resolves to within ``media`` (``"image"`` / ``"video"`` / ``"mesh"``).

    Raises ``HTTPException(503)`` when nothing matching is available — the
    detail names the pick and says there is no automatic fallback. A mesh
    pick is checked for availability only; whether its rig fits stays with
    ``generate_mesh`` (the rig is known there, not in the route)."""
    from app.imagegen.service import get_image_service
    pick = (name or "").strip()
    backend = get_image_service()._wait_for_explicit_backend(
        pick, media=media, has_input_image=has_input_image)
    if not backend:
        raise HTTPException(
            status_code=503,
            detail=f"Selected {_MEDIA_LABEL.get(media, media + ' ')}backend "
                   f"'{pick}' is not available (disabled, offline, or cooling "
                   f"down) — no automatic fallback")
    return backend


async def require_explicit_backend_async(name: str, media: str = "image", *,
                                         has_input_image: bool = False):
    """``require_explicit_backend`` for async route bodies: the probe is
    network I/O and runs in a worker thread (a blocked event loop trips the
    watchdog)."""
    return await asyncio.to_thread(
        require_explicit_backend, name, media, has_input_image=has_input_image)
