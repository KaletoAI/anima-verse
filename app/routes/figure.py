"""Figure routes — the Build of a character's figure (``app/core/figure_build.py``;
plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 7).

Admin-only (``Depends(require_admin)`` on each, like the base-body and outfit
body actions):

* ``GET  /characters/{c}/figure`` — the Figure tab's payload
  (``figure_build.figure_info``): ``{pipeline, humanoid, auto_build, status
  ("up_to_date" | "changes" | "building" | "failed"), changes
  (``figure.pending_changes``), cost (``figure_build.cost``), build
  (``figure_build.state``), wanted, delivered, served_url, worn: [{slot,
  item_id, name, mode, state, note, interim, left_out, failure, piece_state
  ("open" | "closed" | null — null: not closable; ``state`` is the
  readiness), other_state_jobs (own mesh only: the hub jobs of the other
  state's mesh, null unknown)}], hair:
  {mode, state, note}, body: {plain, shape, texture}}``. 404 for an unknown
  character. With ``?plain=1`` it also carries ``plain_body``: the plain
  (base) body's own payload — ``{pipeline, humanoid, signature, images,
  status, model, now, outfit, …}`` of ``base_body.base_info`` with the base
  model's ``steps`` / ``freshness`` (``model_overview.annotate_base_info``),
  its face fields, collision capsules, ``collision_scales``,
  ``face_cleanup`` and ``extension_tips`` (``_plain_body_extras``) — what the
  Figure tab's collapsed "Plain body" details and the Pose tab's outfit
  status read. It is computed for every character (off the pipeline too),
  and only when asked, because it is heavier than the Build's own poll.
* ``POST /characters/{c}/figure/build`` — 202 ``figure_build.start(reason=
  "manual")``: ``{"status": "started" | "queued" | "current"}``; 409 off the
  pipeline or while a base-body step runs, with the reason; 503 when the
  profile could not be read (the Build's failure state records it, ruling
  F13 e). ``POST /characters/{c}/model3d/generate`` answers the same for a
  character on the pipeline (Ruling FR-I4, ``start_manual_build``).
* ``POST /characters/{c}/figure/refit {item_id}`` — the worn row's "Re-fit" of
  a piece whose fit on the body shape was refused (Rulings A23 b, FR-I2,
  ``figure_build.refit``): under the Build lock its cached refusal is dropped,
  the piece is fitted on the CPU and the figure assembled on the CPU — never a
  hub step; steps that need the hub stay due for Build (the run's
  ``failed.assemble`` says which) — ``{"status": "started"}``; 400 when the
  piece's fit is not refused, 409 off the pipeline, while a Build of the
  character runs or a base step is in flight, 503 when the profile could not
  be read.
* ``POST /characters/{c}/base-body/run-all`` — the Base body tab's "Run all"
  (``figure_build.start_base_run_all``, Task UI1 rule R1): the plain body's
  refresh — only the steps that are not current — else the face cleanup or the
  face retexture the stored base mesh misses. 202 ``{"status": "started",
  "kind"}`` or ``{"status": "current"}``; 409 off the pipeline, while a Build
  of the character runs, while a base render / 3D run goes or when a face
  redo is refused (``detail`` says which); 503 when the profile could not be
  read. ``plain_body.run_all`` of ``GET …/figure?plain=1`` is its plan
  (``figure_build.base_run_all``: kind, steps, hub_jobs, note, running, last).
* ``POST /characters/{c}/base-body/mesh-repair`` — the Base body tab's "Repair again" (Ruling A34,
  ``base_mesh_repair.start_repair``): the stored base model's mesh repair with the saved settings, then its
  extension rig on the repaired mesh — local, no hub job. 202 ``{"started": True}``; 404 without a stored base
  model, 409 off the pipeline, while a Build, a base render / 3D run or another repair of the character goes.
  ``plain_body.mesh_repair`` of ``GET …/figure?plain=1`` is its state (``model3d.mesh_repair_state``).
* ``POST /characters/{c}/figure/auto-build {enabled}`` — "Build
  automatically" (``figure_build.set_auto_build``): ``{"auto_build":
  figure_build.auto_build_on(c)}`` (off as well while the world switch of
  the automatic renders is off). Switching it off never stops a run.
* ``POST /characters/{c}/figure/generation-pause {paused}`` — "Pause
  automatic generation" (Ruling A42, ``generation_pause.set_paused``): while
  paused nothing automatic starts for the character, its waiting automatic
  jobs are held, a running job finishes, clicks still run; Resume releases
  the held jobs in their original order. Answers ``generation_pause.state``
  — also carried by ``GET …/figure`` as ``generation_pause``: ``{paused,
  since, waiting: [{id, source, tab, label, detail, jobs}], running,
  resume_jobs, resume_unknown}``.
* ``POST /characters/{c}/figure/waiting/cancel {id}`` — Cancel ONE waiting
  entry of ``generation_pause.waiting`` through its queue's own cancel
  (``generation_pause.cancel``); 404 when it does not wait any more.
* ``GET  /characters/{c}/figure/stored`` — the stored body shapes and painted
  bodies (``figure.stored``): ``{"stored": [{key, kind, bytes, built_for,
  built_for_name, outfits, last_used, reason, unneeded, deletable, running,
  current}]}``.
* ``DELETE /characters/{c}/figure/stored/{key}`` — delete ONE of them
  (``figure.delete_stored``, an explicit collect, Ruling 5a): 409 while an
  outfit would be built on it (a shape: ``figure.SHAPE_NEEDED``, a painted
  body: ``outfit_bodies.PAINTED_NEEDED``), a run works on it or a Build of
  the character runs (``figure.BUILD_RUNNING``), 404 when nothing of it is
  stored, 400 for a key of neither shape.
* ``POST /characters/{c}/model3d/build-current`` — the 3D tab's "Build current
  outfit" while it serves a stand-in (``model3d_pipeline.build_current_outfit``:
  the character's Build, a click — ``{status: started | queued | current}``);
  400 off the pipeline.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth_dependency import require_admin
from app.core.log import get_logger
from app.models.character import get_character_dir

logger = get_logger("figure_routes")

router = APIRouter(prefix="/characters", tags=["figure"])


def _require_character(character_name: str) -> None:
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")


@router.get("/{character_name}/figure")
def get_figure(character_name: str, plain: bool = False,
               _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure_build
    _require_character(character_name)
    info = figure_build.figure_info(character_name)
    # Ruling A42: outside the memoised payload — the pause and its waiting list move on their own.
    from app.core import generation_pause
    info["generation_pause"] = generation_pause.state(character_name)
    if plain:
        info["plain_body"] = _plain_body(character_name)
    return info


def _plain_body(character_name: str) -> Dict[str, Any]:
    """The plain (base) body's payload: ``base_body.base_info`` with the
    model's ``steps`` / ``freshness`` (``model_overview.annotate_base_info``)
    and ``_plain_body_extras``."""
    from app.core.base_body import base_info
    from app.core.model_overview import annotate_base_info
    return _plain_body_extras(character_name, annotate_base_info(character_name, base_info(character_name)))


def _plain_body_extras(character_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """What the plain-body details act on besides the views: the base
    model's face fields (``model3d.face_info``) and collision capsules
    (``collision.ensure`` — the set the outfit models inherit), the stored
    region scales (``collision_scales``), the face cleanup of the base
    source (``face_cleanup``, ``model3d.face_cleanup_state``), the base mesh
    repair (``mesh_repair``, ``model3d.mesh_repair_state``), the tip
    smoothing (``tip_smoothing``, ``extension_tip.tip_smoothing_state``,
    Ruling A43 — None hides the row), the tip
    panels of its ``pair_tip`` groups (``extension_tips``,
    ``extension_tip.tip_panels``), its extension bones (``extension``,
    ``model3d.model_extension_state``, Ruling A45 — the "Extension bones" box
    and the viewer's motion preview) and the Base body tab's "Run all" plan
    (``run_all``, ``figure_build.base_run_all``). Never raises."""
    from app.core import collision, extension_tip, figure_build
    from app.core.model3d import (face_cleanup_state, face_info, find_model3d, get_model3d_options,
                                  mesh_repair_state, model_extension_state)
    try:
        bsig = info.get("signature") or ""
        info["collision_scales"] = get_model3d_options(character_name).get("collision_scales") or {}
        info["face_cleanup"] = face_cleanup_state(character_name, bsig) if bsig and info.get("humanoid") else None
        model = info.get("model")
        path = find_model3d(character_name, bsig) if bsig and isinstance(model, dict) else None
        info["extension_tips"] = []
        info["mesh_repair"] = None
        info["tip_smoothing"] = None
        info["extension"] = None
        if path is not None and model.get("status") != "running":
            info["mesh_repair"] = mesh_repair_state(character_name, bsig)
            info["tip_smoothing"] = extension_tip.tip_smoothing_state(character_name, bsig)
            model.update(face_info(character_name, path))
            model["collision"] = collision.ensure(character_name, bsig)
            info["extension_tips"] = extension_tip.tip_panels(character_name, bsig)
            info["extension"] = model_extension_state(character_name, bsig)
    except Exception:  # noqa: BLE001 — the poll never fails on the extras
        logger.exception("Plain body extras of %s failed", character_name)
    info["run_all"] = figure_build.base_run_all(character_name)
    return info


@router.post("/{character_name}/figure/build", status_code=202)
def build_figure(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_character(character_name)
    return start_manual_build(character_name)


def start_manual_build(character_name: str) -> Dict[str, Any]:
    """A click's Build (``figure_build.start(reason="manual")``) with the answers of ``figure/build``: the
    result, or ``HTTPException`` 409 (a base-body step runs, off the pipeline) / 503 (the profile could not be
    read). Also what ``POST /characters/{c}/model3d/generate`` does for a character on the pipeline (Ruling
    FR-I4) — the caller checks the admin role first."""
    from app.core import figure_build
    result = figure_build.start(character_name, reason="manual")
    if result.get("status") == "base_busy":   # Ruling A26 a: a base-body step of the character runs
        raise HTTPException(status_code=409, detail=str(result.get("reason") or "A base-body step runs"))
    if result.get("status") == "off":
        raise HTTPException(status_code=409, detail=str(result.get("reason") or figure_build.OFF_PIPELINE))
    if result.get("status") == "failed":
        raise HTTPException(status_code=503, detail=str(result.get("reason") or "Build failed"))
    return result


class RefitRequest(BaseModel):
    item_id: str


@router.post("/{character_name}/figure/refit", status_code=202)
def refit_figure_piece(character_name: str, body: RefitRequest,
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure_build
    _require_character(character_name)
    try:
        result = figure_build.refit(character_name, body.item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result.get("status") in ("base_busy", "building"):   # Ruling A26 a / a Build runs (FR-I2)
        raise HTTPException(status_code=409, detail=str(result.get("reason") or "A base-body step runs"))
    if result.get("status") == "off":
        raise HTTPException(status_code=409, detail=str(result.get("reason") or figure_build.OFF_PIPELINE))
    if result.get("status") == "failed":
        raise HTTPException(status_code=503, detail=str(result.get("reason") or "Build failed"))
    return result


@router.post("/{character_name}/base-body/run-all", status_code=202)
def run_all_base_body(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure_build
    _require_character(character_name)
    try:
        result = figure_build.start_base_run_all(character_name)
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    status = result.get("status")
    if status in ("off", "building", "busy"):
        raise HTTPException(status_code=409, detail=str(result.get("reason") or status))
    if status == "failed":
        raise HTTPException(status_code=503, detail=str(result.get("reason") or "Run all failed"))
    return result


@router.post("/{character_name}/base-body/mesh-repair", status_code=202)
def repair_base_mesh(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import base_body, base_mesh_repair, figure_build, model3d
    _require_character(character_name)
    if not figure_build.on_pipeline(character_name):
        raise HTTPException(status_code=409, detail=figure_build.OFF_PIPELINE)
    bsig = base_body.base_signature(character_name)
    if not bsig or model3d.mesh_repair_state(character_name, bsig) is None:
        raise HTTPException(status_code=404, detail="No stored humanoid base model to repair")
    if figure_build.running(character_name):
        raise HTTPException(status_code=409, detail=figure_build.RUN_ALL_BUILD_RUNNING)
    if model3d.generation_running(character_name):
        raise HTTPException(status_code=409, detail=figure_build.RUN_ALL_BUSY)
    try:
        started = base_mesh_repair.start_repair(character_name, bsig)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not started:
        raise HTTPException(status_code=409, detail="A base mesh repair of this character runs")
    return {"started": True}


class AutoBuildRequest(BaseModel):
    enabled: bool


@router.post("/{character_name}/figure/auto-build")
def set_auto_build(character_name: str, body: AutoBuildRequest,
                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure_build
    _require_character(character_name)
    if not figure_build.set_auto_build(character_name, body.enabled):
        raise HTTPException(status_code=500, detail="The setting was not saved")
    return {"auto_build": figure_build.auto_build_on(character_name)}


class GenerationPauseRequest(BaseModel):
    paused: bool


@router.post("/{character_name}/figure/generation-pause")
def set_generation_pause(character_name: str, body: GenerationPauseRequest,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import generation_pause
    _require_character(character_name)
    return generation_pause.set_paused(character_name, body.paused)


class WaitingCancelRequest(BaseModel):
    id: str


@router.post("/{character_name}/figure/waiting/cancel")
def cancel_waiting(character_name: str, body: WaitingCancelRequest,
                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import generation_pause
    _require_character(character_name)
    try:
        return generation_pause.cancel(character_name, body.id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{character_name}/figure/stored")
def get_figure_stored(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure
    _require_character(character_name)
    return {"stored": figure.stored(character_name)}


@router.delete("/{character_name}/figure/stored/{key}")
def delete_figure_stored(character_name: str, key: str,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure, outfit_bodies
    _require_character(character_name)
    try:
        return figure.delete_stored(character_name, key)
    except outfit_bodies.UnknownBody as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
