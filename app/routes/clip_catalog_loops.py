"""Loop suggestions for the CMU clip catalog — a router of its own so the
assets router (edited in parallel elsewhere) stays untouched.

``GET /assets/clip-catalog/{take}/loop-suggestions`` → the best-closing
windows of a take for several minimum lengths (``cmu_import.loop_suggestions``):
what the catalog offers as Start/End presets.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.core import clip_catalog
from app.core.auth_dependency import require_admin

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/clip-catalog/{take_id}/loop-suggestions")
def get_clip_catalog_loop_suggestions(take_id: str,
                                      _: Dict[str, Any] = Depends(require_admin)
                                      ) -> Dict[str, Any]:
    from app.core.cmu_import import loop_suggestions
    take = clip_catalog.find_take(take_id.strip())
    if not take:
        raise HTTPException(status_code=404, detail=f"unknown take {take_id}")
    try:
        return loop_suggestions(take_id.strip())
    except FileNotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))
