"""Loop suggestions for the CMU clip catalog — a router of its own so the
assets router (edited in parallel elsewhere) stays untouched.

``GET /assets/clip-catalog/{take}/loop-suggestions`` → the best-closing
windows of a take for several minimum lengths (``cmu_import.loop_suggestions``):
what the catalog offers as Start/End presets.

``GET /assets/clip-catalog/{take}/frame-yaw?at_s=`` → how far the import's
frame of reference turns against the trial clip the preview plays
(``cmu_import.framing_yaw_delta``): the number the preview adds to the
orientation dial so the dial is set on the body the import will write.
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


@router.get("/clip-catalog/{take_id}/frame-yaw")
def get_clip_catalog_frame_yaw(take_id: str, at_s: float = 0.0,
                               _: Dict[str, Any] = Depends(require_admin)
                               ) -> Dict[str, Any]:
    """``delta_deg``: turn the trial clip by this to see the import's framing.

    The trial clip is the take framed on its frame 0, the import is framed on
    the first frame of its own window — see ``cmu_import.framing_yaw_delta``.
    """
    from app.core.cmu_import import framing_yaw_delta
    take = clip_catalog.find_take(take_id.strip())
    if not take:
        raise HTTPException(status_code=404, detail=f"unknown take {take_id}")
    try:
        return framing_yaw_delta(take_id.strip(), at_s)
    except FileNotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))
