"""Generic external image API (under the shared /api namespace).

Lets an authenticated external service write an image back into this project's
storage. Used e.g. by the external post-processing service to deliver a
processed image. Reading images is already covered by the existing public
gallery/profile endpoints, so only writing is exposed here.

Auth: X-API-Key header must match server.api_key. Unlike the marketplace
publish-token (open when unset), this endpoint stays CLOSED when no key is
configured — writing images from outside must be deliberately enabled.

Endpoint:
  POST /api/images?path=<world-relative>   (X-API-Key required)
        body = raw image bytes (image/png|jpeg|webp)
        -> overwrites the image in place; marks its sidecar postprocessed=true

`path` is relative to the active world storage dir, e.g.
  characters/Vallerie/images/Vallerie_177....png
covering every image kind (characters, events, instagram, world_gallery, items).
"""
import json
from datetime import datetime

from app.core.timeutils import utc_now_iso
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.core import config
from app.core.log import get_logger
from app.core.paths import get_storage_dir

logger = get_logger("api_images")

router = APIRouter(prefix="/api", tags=["api"])

_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _resolve_in_storage(rel_path: str) -> Path:
    """Resolve a world-relative path safely inside the storage dir.

    Rejects absolute paths and any attempt to escape the storage root
    (e.g. ../../etc/passwd). Returns the absolute, normalized path.
    """
    if not rel_path or not rel_path.strip():
        raise HTTPException(status_code=400, detail="path required")
    if rel_path.startswith("/") or rel_path.startswith("\\") or (len(rel_path) > 1 and rel_path[1] == ":"):
        raise HTTPException(status_code=400, detail="path must be relative")
    base = get_storage_dir().resolve()
    target = (base / rel_path).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(status_code=400, detail="path escapes storage")
    if target.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="unsupported file type")
    return target


def _require_api_key(provided: Optional[str]) -> None:
    expected = (config.get("server.api_key") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="server api_key not configured")
    if not provided or provided.strip() != expected:
        raise HTTPException(status_code=401, detail="invalid api key")


@router.post("/images")
async def write_image(
    request: Request,
    path: str = Query(..., description="world-relative image path to overwrite"),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Write an image back in place and flag its sidecar as externally processed.

    Because this write comes from outside (not internal generation), the sidecar
    JSON is automatically marked postprocessed=true.
    """
    _require_api_key(x_api_key)
    target = _resolve_in_storage(path)
    if not target.parent.is_dir():
        raise HTTPException(status_code=404, detail="target directory not found")

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty body")

    try:
        target.write_bytes(data)
    except OSError as e:
        logger.exception("api image write failed: %s", target)
        raise HTTPException(status_code=500, detail=f"write failed: {e}")

    flagged = _mark_sidecar_postprocessed(target.with_suffix(".json"))
    logger.info("api image write: %s (%d bytes, sidecar_flagged=%s)", target, len(data), flagged)
    return JSONResponse({"status": "ok", "path": path, "bytes": len(data), "sidecar_flagged": flagged})


def _mark_sidecar_postprocessed(sidecar: Path) -> bool:
    """Set postprocessed=true + timestamp in the sidecar JSON if it exists."""
    if not sidecar.is_file():
        return False
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        meta = {}
    meta["postprocessed"] = True
    meta["postprocessed_at"] = utc_now_iso()
    try:
        sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        logger.exception("failed to flag sidecar %s", sidecar)
        return False
