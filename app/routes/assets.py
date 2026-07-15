"""Shared 3D assets — animation clips (world-independent, read-only).

Clips live in ``shared/models/clips`` (see the README there for the hard file
requirements: Mixamo FBX "Without Skin", one rig source, 52-bone rig). They
belong to the RIG, not to a character or a world, so every client — the
Game-Admin 3D preview and the external 3D map client — reads them from here.

``kind`` (idle / walk / run / sit / dance / wave / …) is derived from the file
name; the vocabulary is OPEN — no list of kinds exists in the code, a new kind
is just a new file. Clips practically never change → served with an ETag and a
long max-age.
"""
import mimetypes
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.core.animation_clips import CLIP_EXTS, clip_files, parse_clip_name
from app.core.http_files import etag_file_response
from app.core.log import get_logger
from app.core.paths import get_animation_clips_dir

logger = get_logger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/animation-clips")
def list_animation_clips() -> Dict[str, Any]:
    """Lists the shared animation clips.

    Per clip: ``kind`` (the activity category), ``set`` (the figure it was made
    for — empty = the default figure), plus name/url/size. ``kinds`` and
    ``sets`` list the vocabularies actually present; both are OPEN — a new one
    is just a new file name, nothing is hardcoded.
    """
    clips = []
    for p in clip_files():
        kind, cset = parse_clip_name(p.name)
        clips.append({
            "kind": kind,
            "set": cset,
            "name": p.stem,
            "filename": p.name,
            "url": f"/assets/animation-clips/{p.name}",
            "size": p.stat().st_size,
        })
    from app.core.animation_sets import available_sets
    return {"clips": clips,
            "kinds": sorted({c["kind"] for c in clips}),
            # Sets that HAVE clips …
            "clip_sets": sorted({c["set"] for c in clips if c["set"]}),
            # … and everything selectable on a character: the base sets
            # (female/male/animal, which follow from gender + the humanoid
            # feature) plus any further set found in the files.
            "sets": available_sets()}


@router.get("/animation-clips/{filename}")
def get_animation_clip(filename: str, request: Request):
    """Serves a clip file. ETag + If-None-Match; clips are immutable in
    practice, so they may be cached hard."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = get_animation_clips_dir() / filename
    if not path.exists() or path.suffix.lower() not in CLIP_EXTS:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _ = mimetypes.guess_type(str(path))
    return etag_file_response(path, request,
                              media_type or "application/octet-stream",
                              cache_control="public, max-age=86400")
