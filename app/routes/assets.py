"""Shared 3D assets — animation clips + surface textures (read-only).

Clips live in ``shared/models/clips`` (see the README there for the hard file
requirements: Mixamo FBX "Without Skin", one rig source, 52-bone rig). They
belong to the RIG, not to a character or a world, so every client — the
Game-Admin 3D preview and the external 3D map client — reads them from here.
Surface textures (AV3D-13) are the second asset family: per-world tileable
ground materials, managed via /world/surface-textures, served here because
the 3D client consumes them exactly like the clip library.

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


@router.get("/surface-textures")
def list_surface_textures():
    """Global surface-texture library (AV3D-13) — contract shape: a BARE
    array ``[{kind, url, size_m}, …]``. ``kind`` is the open vocabulary
    matching the location ``terrain`` field; an empty list is the normal
    state (the client falls back to its procedural materials)."""
    from app.core.surface_textures import list_textures
    out = []
    for t in list_textures():
        if "blend" in t:
            # Composition entry (AV3D-13 v2) — no url/size_m.
            out.append({"kind": t["kind"], "blend": t["blend"]})
        else:
            out.append({"kind": t["kind"], "url": t["url"],
                        "size_m": t["size_m"]})
    return out


@router.get("/surface-textures/{filename}")
def get_surface_texture(filename: str, request: Request):
    """Serves a texture image. ETag + If-None-Match; textures can be
    regenerated, so revalidation stays cheap but caching moderate."""
    from app.core.surface_textures import file_by_name
    path = file_by_name(filename)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _ = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "image/jpeg",
                              cache_control="public, max-age=3600")


# ── Props (plan-room-props.md) ──
# Global per-world prop library — single furnishing objects (chair, table, …)
# as their own GLB meshes + object-local markers. Managed via /world/props;
# served here because the 3D client consumes them like the other asset
# families. A prop's placement in a room is NOT here (that is the room recipe,
# Fable's part) — this is the raw library.

@router.get("/props")
def list_props():
    """Prop library — the lean client shape: a bare array
    ``[{id, name, category, width_m, depth_m, height_m, tags, marker_count,
    has_model}, …]``. The three dims are the object's REAL extent in metres
    after its orientation fix (x/y/z = width/height/depth). An empty list is
    the normal starting state."""
    from app.core.props import list_props as _list
    return _list()


@router.get("/props/{prop_id}/model")
def get_prop_model(prop_id: str, request: Request):
    """Serves a prop's GLB mesh. ETag + If-None-Match; a 404 is the normal
    "no model yet" state (the record may exist before the mesh does)."""
    from app.core.props import model_path
    path = model_path(prop_id)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "model/gltf-binary",
                              cache_control="public, max-age=3600")


@router.get("/props/{prop_id}/source")
def get_prop_source(prop_id: str, request: Request):
    """Serves the product-shot render a prop's mesh was made from (the
    library thumbnail). 404 when the prop was uploaded without a source."""
    from app.core.props import source_path
    path = source_path(prop_id)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "image/png",
                              cache_control="public, max-age=3600")
