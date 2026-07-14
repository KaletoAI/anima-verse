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
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.core.log import get_logger
from app.core.paths import get_animation_clips_dir

logger = get_logger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])

CLIP_EXTS = (".fbx", ".glb", ".gltf")


def parse_clip_name(filename: str) -> Tuple[str, str]:
    """(kind, set) from the file name: ``<kind>[_<set>][_<n>].fbx``, lowercased.

    The KIND is the semantic category the activity maps to (walk, sit, …).
    The SET is the figure it was made for (lady, man, dog, …) — a character
    picks its set once and thereby gets walk_lady, sit_lady, sleep_lady …
    without anyone assigning clips per character. Numeric tokens are just
    variants of the same clip and carry no meaning.

        walk.fbx          -> ("walk", "")
        walk_lady.fbx     -> ("walk", "lady")
        Sit_Lady_02.fbx   -> ("sit", "lady")
        walk_02.fbx       -> ("walk", "")
    """
    stem = Path(filename).stem.strip().lower()
    tokens = [t for t in re.split(r"[\s_\-.]+", stem) if t]
    if not tokens:
        return (stem, "")
    kind = tokens[0]
    rest = [t for t in tokens[1:] if not t.isdigit()]
    return (kind, rest[0] if rest else "")


def _clip_files() -> List[Path]:
    d = get_animation_clips_dir()
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in CLIP_EXTS)


@router.get("/animation-clips")
def list_animation_clips() -> Dict[str, Any]:
    """Lists the shared animation clips.

    Per clip: ``kind`` (the activity category), ``set`` (the figure it was made
    for — empty = the default figure), plus name/url/size. ``kinds`` and
    ``sets`` list the vocabularies actually present; both are OPEN — a new one
    is just a new file name, nothing is hardcoded.
    """
    clips = []
    for p in _clip_files():
        kind, cset = parse_clip_name(p.name)
        clips.append({
            "kind": kind,
            "set": cset,
            "name": p.stem,
            "filename": p.name,
            "url": f"/assets/animation-clips/{p.name}",
            "size": p.stat().st_size,
        })
    return {"clips": clips,
            "kinds": sorted({c["kind"] for c in clips}),
            "sets": sorted({c["set"] for c in clips if c["set"]})}


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
