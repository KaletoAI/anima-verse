"""Figure routes — the Build of a character's figure (``app/core/figure_build.py``;
plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 7).

Admin-only (``Depends(require_admin)`` on each, like the base-body and outfit
body actions):

* ``GET  /characters/{c}/figure`` — the Figure tab's payload
  (``figure_build.figure_info``): ``{pipeline, humanoid, auto_build, status
  ("up_to_date" | "changes" | "building" | "failed"), changes
  (``figure.pending_changes``), cost (``figure_build.cost``), build
  (``figure_build.state``), wanted, delivered, served_url, worn: [{slot,
  item_id, name, mode, state, note, interim, left_out, failure}], hair:
  {mode, state, note}, body: {plain, shape, texture}}``. 404 for an unknown
  character.
* ``POST /characters/{c}/figure/build`` — 202 ``figure_build.start(reason=
  "manual")``: ``{"status": "started" | "queued" | "current"}``; 409 off the
  pipeline with the reason.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth_dependency import require_admin
from app.models.character import get_character_dir

router = APIRouter(prefix="/characters", tags=["figure"])


def _require_character(character_name: str) -> None:
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")


@router.get("/{character_name}/figure")
def get_figure(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure_build
    _require_character(character_name)
    return figure_build.figure_info(character_name)


@router.post("/{character_name}/figure/build", status_code=202)
def build_figure(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure_build
    _require_character(character_name)
    result = figure_build.start(character_name, reason="manual")
    if result.get("status") == "off":
        raise HTTPException(status_code=409, detail=str(result.get("reason") or figure_build.OFF_PIPELINE))
    return result
