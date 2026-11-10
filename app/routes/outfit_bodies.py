"""Outfit body routes — the character tab "Outfit body" (app/core/outfit_bodies.py;
plan docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md, Task 4).

All admin-only (``Depends(require_admin)``) like the base-body actions:

* ``GET  /characters/{c}/outfit-bodies`` — the tab payload (``outfit_bodies.info``).
* ``GET  /characters/{c}/outfit-bodies/{key}/views/{view}`` — a body's view
  image (``ob…``) or a painted body's texture view (``tex…``).
* ``POST /characters/{c}/outfit-bodies/{body_id}/regenerate`` — mesh again
  from its dressed views (routed occasions of the old path, hub jobs).
* ``POST …/{body_id}/rerig`` — the rig chain on the retained unrigged mesh.
* ``POST …/{body_id}/refit`` ``{item_id?}`` — every fit on the body (or one)
  anew (CPU).
  The three runs answer 202 ``{kind, body_id, started, queued, position,
  behind}`` and queue behind a running 3D run of the character (never 409
  for a run in progress); 409 when the run has nothing to work on.
* ``POST …/{body_id}/delete`` — the body and its chain through the artefact
  graph (``artefact_graph.delete_body``); 409 while a run of the tab is on it.
"""
import mimetypes
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.auth_dependency import require_admin
from app.core.http_files import etag_file_response
from app.models.character import get_character_dir

router = APIRouter(prefix="/characters", tags=["outfit-bodies"])


def _require_character(character_name: str) -> None:
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")


@router.get("/{character_name}/outfit-bodies")
def get_outfit_bodies(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import outfit_bodies
    _require_character(character_name)
    return outfit_bodies.info(character_name)


@router.get("/{character_name}/outfit-bodies/{key}/views/{view}")
def get_outfit_body_view(character_name: str, key: str, view: str, request: Request,
                         _: Dict[str, Any] = Depends(require_admin)):
    from fastapi.responses import Response
    from app.core import outfit_bodies
    _require_character(character_name)
    path = outfit_bodies.view_path(character_name, key, view)
    if path is None:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _encoding = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "application/octet-stream")


def _start(character_name: str, kind: str, body_id: str, item_id: str = "") -> Dict[str, Any]:
    from app.core import outfit_bodies
    _require_character(character_name)
    try:
        return outfit_bodies.start(character_name, kind, body_id, item_id)
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{character_name}/outfit-bodies/{body_id}/regenerate", status_code=202)
def regenerate_outfit_body(character_name: str, body_id: str,
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return _start(character_name, "regenerate", body_id)


@router.post("/{character_name}/outfit-bodies/{body_id}/rerig", status_code=202)
def rerig_outfit_body(character_name: str, body_id: str,
                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return _start(character_name, "rerig", body_id)


class RefitRequest(BaseModel):
    #: one garment on the body; empty = every garment on it
    item_id: str = ""


@router.post("/{character_name}/outfit-bodies/{body_id}/refit", status_code=202)
def refit_outfit_body(character_name: str, body_id: str, body: Optional[RefitRequest] = None,
                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return _start(character_name, "refit", body_id, (body.item_id if body else "") or "")


@router.post("/{character_name}/outfit-bodies/{body_id}/delete")
def delete_outfit_body(character_name: str, body_id: str,
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import outfit_bodies
    _require_character(character_name)
    try:
        return outfit_bodies.delete(character_name, body_id)
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
