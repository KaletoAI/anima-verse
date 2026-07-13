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
import re
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.core.log import get_logger
from app.core.paths import get_animation_clips_dir

logger = get_logger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])

CLIP_EXTS = (".fbx", ".glb", ".gltf")


def _kind_of(filename: str) -> str:
    """Kind = file stem up to the first separator or digit, lowercased
    ('Walk_02.fbx' -> 'walk', 'idle-breathing.fbx' -> 'idle')."""
    stem = Path(filename).stem.strip().lower()
    token = re.split(r"[\s_\-.0-9]", stem, maxsplit=1)[0]
    return token or stem


def _clip_files() -> List[Path]:
    d = get_animation_clips_dir()
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in CLIP_EXTS)


@router.get("/animation-clips")
def list_animation_clips() -> Dict[str, Any]:
    """Lists the shared animation clips ([{kind, name, filename, url, size}])."""
    clips = []
    for p in _clip_files():
        clips.append({
            "kind": _kind_of(p.name),
            "name": p.stem,
            "filename": p.name,
            "url": f"/assets/animation-clips/{p.name}",
            "size": p.stat().st_size,
        })
    return {"clips": clips, "kinds": sorted({c["kind"] for c in clips})}


@router.get("/animation-clips/{filename}")
def get_animation_clip(filename: str, request: Request):
    """Serves a clip file. ETag + If-None-Match; clips are immutable in
    practice, so they may be cached hard."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = get_animation_clips_dir() / filename
    if not path.exists() or path.suffix.lower() not in CLIP_EXTS:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    stat = path.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        path, media_type=media_type or "application/octet-stream",
        filename=path.name,
        headers={"ETag": etag, "Cache-Control": "public, max-age=86400"})
