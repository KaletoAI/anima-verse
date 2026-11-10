"""Outfit body routes — the character tab "Outfit body" (app/core/outfit_bodies.py;
plan docs/superpowers/plans/2026-11-10-outfit-body-mesh-mode.md, Task 4).

All admin-only (``Depends(require_admin)``) like the base-body actions:

* ``GET  /characters/{c}/outfit-bodies`` — the tab payload (``outfit_bodies.info``).
* ``GET  /characters/{c}/outfit-bodies/{key}/views/{view}`` — a body's view
  image (``ob…``) or a painted body's texture view (``tex…``).
* ``GET  /characters/{c}/outfit-bodies/{tsig}/model?v=`` — a painted body's
  stored GLB (``base_body.texture_body_path``: the texture body, without
  own-mesh garments), ``http_files.snapshot_response`` (ETag = content,
  immutable only when ``v`` matches); 404 for no painted body / no ``tex…``.
* ``POST /characters/{c}/outfit-bodies/{body_id}/regenerate`` — mesh again
  from its dressed views (routed occasions of the old path, hub jobs).
* ``POST …/{body_id}/rerig`` — the rig chain on the retained unrigged mesh.
* ``POST …/{body_id}/refit`` ``{item_id?}`` — every fit on the body (or one)
  anew (CPU).
* ``POST …/{body_id}/views/{view}/regenerate`` — render ONE dressed view of
  the body anew (``outfit_bodies.render_view``, image jobs only — the mesh
  is not touched; it shows "Dressed views changed" until its own
  Regenerate).
* ``POST …/{body_id}/generate-views`` — the WORN outfit's missing dressed
  views (``outfit_bodies.render_worn_views``, image jobs only, never chained
  to the mesh) when the worn outfit stands, or will stand, on ``body_id``
  (``outfit_bodies.worn_body``); 404 for any other body.
  The five runs answer 202 ``{kind, body_id, item_id, view, started, queued,
  position, behind}`` and queue behind a running 3D run of the character
  (never 409 for a run in progress); 409 when the run has nothing to work on
  (for a view: ``outfit_bodies.view_blocked``), 400 for an unknown view.
* Retexture mode (``outfit_bodies.textures``, key = texture signature, or the
  worn outfit's signature while its painted body is pending):
  ``POST …/{key}/paint`` — Generate / Build outfit model of the WORN outfit
  (``outfit_bodies.paint_worn``: missing dressed views, then its model never
  forced — a stored painted body is reused; 404 for another key);
  ``POST …/{key}/repaint`` — Regenerate a painted body
  (``outfit_bodies.repaint_texture``: dressed views anew, body painted again).
  Both 202 in the same queue, Cancel included.
* ``POST /characters/{c}/model3d/build-current`` — the 3D tab's "Build current
  outfit" while it serves a stand-in (``model3d_pipeline.build_current_outfit``:
  the outfit-change trigger, never forced); 400 off the pipeline, 409
  without a ready base model.
* ``POST …/{body_id}/cancel`` ``{view?}`` — take the body's waiting runs (or
  only that view's) out of the queue (``outfit_bodies.cancel``); 409 when
  its run has already started, 404 when none waits.
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


@router.get("/{character_name}/outfit-bodies/{tsig}/model")
def get_painted_body_model(character_name: str, tsig: str, request: Request,
                           _: Dict[str, Any] = Depends(require_admin)):
    from app.core import base_body
    from app.core.http_files import snapshot_response
    _require_character(character_name)

    def resolve():
        try:
            path = base_body.texture_body_path(character_name, tsig)
        except ValueError:
            return None
        return path if path.is_file() else None
    return snapshot_response(None, request, media_type="model/gltf-binary",
                             version=request.query_params.get("v"), resolve=resolve)


def _start(character_name: str, kind: str, body_id: str, item_id: str = "", view: str = "") -> Dict[str, Any]:
    from app.core import outfit_bodies
    _require_character(character_name)
    try:
        return outfit_bodies.start(character_name, kind, body_id, item_id, view)
    except outfit_bodies.UnknownBody as e:
        raise HTTPException(status_code=404, detail=str(e))
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


@router.post("/{character_name}/outfit-bodies/{body_id}/views/{view}/regenerate", status_code=202)
def regenerate_outfit_body_view(character_name: str, body_id: str, view: str,
                                _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return _start(character_name, "view", body_id, view=view)


@router.post("/{character_name}/outfit-bodies/{body_id}/generate-views", status_code=202)
def generate_worn_outfit_views(character_name: str, body_id: str,
                               _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return _start(character_name, "views", body_id)


@router.post("/{character_name}/outfit-bodies/{key}/paint", status_code=202)
def paint_worn_outfit(character_name: str, key: str,
                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return _start(character_name, "paint", key)


@router.post("/{character_name}/outfit-bodies/{key}/repaint", status_code=202)
def repaint_painted_body(character_name: str, key: str,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return _start(character_name, "repaint", key)


@router.post("/{character_name}/model3d/build-current")
def build_current_outfit_model(character_name: str,
                               _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import model3d_pipeline
    _require_character(character_name)
    try:
        return model3d_pipeline.build_current_outfit(character_name)
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class CancelRequest(BaseModel):
    #: only the waiting run of this dressed view; empty = every waiting run of the body
    view: str = ""


@router.post("/{character_name}/outfit-bodies/{body_id}/cancel")
def cancel_outfit_body_run(character_name: str, body_id: str, body: Optional[CancelRequest] = None,
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import outfit_bodies
    _require_character(character_name)
    try:
        return outfit_bodies.cancel(character_name, body_id, (body.view if body else "") or "")
    except outfit_bodies.RunStarted as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
