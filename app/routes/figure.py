"""Figure routes — the Build of a character's figure (``app/core/figure_build.py``;
plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 7).

Admin-only (``Depends(require_admin)`` on each, like the base-body and outfit
body actions):

* ``GET  /characters/open-steps`` — the character list's badges (Ruling A112):
  ``{characters: {name: figure_build.open_steps}}``, only characters with an
  open step or a running Build.

* ``GET  /characters/{c}/figure`` — the Figure tab's payload
  (``figure_build.figure_info``): ``{pipeline, humanoid, auto_build, status
  ("up_to_date" | "changes" | "building" | "failed"), changes
  (``figure.pending_changes``), cost (``figure_build.cost``), build
  (``figure_build.state``), wanted, delivered, served_url, served_foot_pose
  (the served model's fitted-shoe pose, None without one — Ruling A52), worn: [{slot,
  item_id, name, mode, state, note, interim, left_out, failure, piece_state
  ("open" | "closed" | null — null: not closable; ``state`` is the
  readiness), other_state_jobs (own mesh only: the hub jobs of the other
  state's mesh, null unknown)}], hair:
  {mode, state, note}, body: {plain, shape, texture}, new_body (Ruling A131: a new body is built or the newest
  body has no fits of pieces fitted on the earlier one)}``. 404 for an unknown
  character. With ``?plain=1`` it also carries ``plain_body``: the plain
  (base) body's own payload — ``{pipeline, humanoid, signature, images,
  status, model, now, outfit, …}`` of ``base_body.base_info`` with the base
  model's ``steps`` / ``freshness`` (``model_overview.annotate_base_info``),
  its face fields, collision capsules, ``collision_scales``,
  ``face_cleanup`` and ``extension_tips`` (``_plain_body_extras``) — what the
  Figure tab's collapsed "Plain body" details and its Outfit model sub-tab
  read. It is computed for every character (off the pipeline too),
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
* ``GET  /characters/{c}/figure/template/{item_id}`` — a template piece's parameter dialog (Ruling A138,
  ``garment_template``): ``{item_id, name, params (None: none stored), source, updated_at, spec (the field
  schema: ``{field: {type, choices | min/max, default}}``), built (the kinds draped today), cost {llm_calls,
  hub_jobs, cpu_s}}``; 404 for an unknown character or item.
* ``POST /characters/{c}/figure/template/{item_id}/suggest`` — ONE queued vision call (``TASK``) reads the item's
  picture and text: ``{params, errors, raw}``; saves nothing. 400 without a picture / for no outfit piece, 502
  when the LLM fails or answers no JSON.
* ``PUT  /characters/{c}/figure/template/{item_id} {params, source}`` — store the parameters on the ITEM
  (every wearer; ``garment_template.set_params``); spends nothing — the next Build re-drapes. 400 with the
  validation errors (nothing stored).
* ``POST /characters/{c}/base-body/run-all`` — the Base body tab's "Run all"
  (``figure_build.start_base_run_all``, Task UI1 rule R1): the plain body's
  refresh — only the steps that are not current — else the face cleanup or the
  face retexture the stored base mesh misses. 202 ``{"status": "started",
  "kind"}`` or ``{"status": "current"}``; 409 off the pipeline, while a Build
  of the character runs, while a base render / 3D run goes or when a face
  redo is refused (``detail`` says which); 503 when the profile could not be
  read. ``plain_body.run_all`` of ``GET …/figure?plain=1`` is its plan
  (``figure_build.base_run_all``: kind, steps, hub_jobs, note, running, last).
* ``GET  /characters/{c}/base-body/state-motion?state=<id>`` — the Base body tab's state preview (Ruling A66):
  ``{"state", "motion"}``, the base model's motion as ``plain_body.extension.motion`` has it (no clothing — the
  base is bare) with ONLY that state's ``bone_pose`` applied (``extension_rig.motion_payload(apply_clothing=False,
  preview_states=[state])``). Nothing is saved and nothing runs; 404 for an unknown character or a state that
  carries no ``bone_pose``. ``plain_body.extension.states`` lists the states it offers
  (``prompt_filters.bone_pose_states`` over the base model's groups).
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
* ``GET /characters/{c}/figure/stored/{key}/preview`` — what that Delete
  would do (``figure.delete_preview``, Ruling A64): the files with their size,
  the outfit models deleted with a shape, whether it is deletable and why
  not; 404 when nothing of it is stored, 400 for a key of neither shape.
* ``DELETE /characters/{c}/figure/stored/{key}`` — delete ONE of them
  (``figure.delete_stored``, an explicit collect, Ruling 5a): 409 while an
  outfit would be built on it or the worn figure stands on it (a shape:
  ``figure.SHAPE_NEEDED`` / ``figure.SHAPE_CURRENT``, a painted
  body: ``outfit_bodies.PAINTED_NEEDED``), a run works on it or a Build of
  the character runs (``figure.BUILD_RUNNING``), 404 when nothing of it is
  stored, 400 for a key of neither shape.
* ``GET  /characters/{c}/figure/outfit-reference`` — the Figure tab's "Reference
  image" row of the outfit worn now (Ruling A74b, ``outfit_references.info``):
  ``{key, label, record, url, gone, applies, note, source, jobs, others}``.
* ``POST /characters/{c}/figure/outfit-reference {image}`` — pick a picture of
  the character's gallery as the worn outfit's full-body reference
  (``outfit_references.set_reference``): it SAVES ONLY — nothing renders; the
  dressed front shows as due with its cost until a Build. 400 for a file not
  in the gallery or not an image; 503 when the profile was not saved.
* ``POST /characters/{c}/figure/outfit-reference/upload`` (multipart ``file``)
  — the same with an uploaded picture: capped (``guard_content_length`` /
  ``read_upload_capped``) and checked by its bytes (``ensure_image``), stored
  in the gallery, then picked. 400/413/415 as the gallery upload.
* ``DELETE /characters/{c}/figure/outfit-reference/{key}`` — clear one
  outfit's reference (``outfit_references.clear_reference``); saves only.
  404 when that outfit has none.
  Ruling A87: these answers carry the tile's Generate part
  (``full_body_reference.outfit_tile``); the record keeps its ``origin``.
* ``POST /characters/{c}/figure/outfit-reference/generate`` — GENERATE the worn
  outfit's full-body reference (Ruling A87, ``full_body_reference.start_outfit``:
  one image job, an edit of the plain body's full-body reference, else of the
  profile image; recorded under the outfit worn at the click). 202; 409 without
  either picture or while a reference of the character is generated; 400 for a
  non-humanoid.
* ``GET /characters/{c}/base-body/full-body-reference`` — the Base body tab's
  "Full-body reference" tile (Ruling A87, ``full_body_reference.base_tile``).
* ``POST …/base-body/full-body-reference {image}`` (pick from the gallery),
  ``POST …/base-body/full-body-reference/upload`` (multipart ``file``; capped
  and checked as the outfit upload), ``DELETE …/base-body/full-body-reference``
  (clear) — SAVE ONLY: the front then shows as outdated with its cost.
* ``POST …/base-body/full-body-reference/generate`` — generate it from the
  profile image (``full_body_reference.start_base``, one image job). 202; 409
  without a profile image or while a reference of the character is generated.
* ``POST /characters/{c}/model3d/build-current`` — the 3D tab's "Build current
  outfit" while it serves a stand-in (``model3d_pipeline.build_current_outfit``:
  the character's Build, a click — ``{status: started | queued | current}``);
  400 off the pipeline.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.auth_dependency import require_admin
from app.core.log import get_logger
from app.models.character import get_character_dir

logger = get_logger("figure_routes")

router = APIRouter(prefix="/characters", tags=["figure"])


def _require_character(character_name: str) -> None:
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")


@router.get("/open-steps")
def get_open_steps(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The character list's badges (Ruling A112): ``{"characters": {name: figure_build.open_steps(name)}}`` for
    every character of the roster (dormant included) — only those with an open step or a running Build."""
    from app.core import figure_build
    from app.models.character import list_available_characters
    out: Dict[str, Any] = {}
    for name in list_available_characters(include_dormant=True):
        info = figure_build.open_steps(name)
        if info["building"] or info["base"]["count"] or info["outfit"]["count"]:
            out[name] = info
    return {"characters": out}


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
    region scales (``collision_scales``), the stored channel overrides (``collision_channels``) and the channels
    the base model's declarations ask for with their placement or the reason there is none
    (``channel_declarations``, ``collision_channels.declarations_info`` — without a base model the declarations
    alone, reason "No base model yet"), the face cleanup of the base
    source (``face_cleanup``, ``model3d.face_cleanup_state``), the base mesh
    repair (``mesh_repair``, ``model3d.mesh_repair_state``), the tip
    smoothing (``tip_smoothing``, ``extension_tip.tip_smoothing_state``,
    Ruling A43 — None hides the row), the tip
    panels of its ``pair_tip`` groups (``extension_tips``,
    ``extension_tip.tip_panels``), its extension bones (``extension``,
    ``model3d.model_extension_state``, Ruling A45 — the "Extension bones" box
    and the viewer's motion preview; with ``states``, the state picker's choices, Ruling A66; a tip group's light and motion controls
    sit in its tip panel, the box lists the rest — ``box_groups``,
    ``extension_tip.group_tip_settings``, Ruling A53), the Base body tab's "Run
    all" plan (``run_all``, ``figure_build.base_run_all``) and what of the
    character's 3D work runs now, base-body work apart from outfit work
    (``activity``, ``figure_build.base_activity``, Ruling A55). Never raises."""
    from app.core import collision, collision_channels, extension_tip, figure_build
    from app.core.model3d import (_read_sidecar, face_cleanup_state, face_info, find_model3d, get_model3d_options,
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
        info["collision_channels"] = get_model3d_options(character_name).get("collision_channels") or {}
        info["channel_declarations"] = []
        if path is not None and model.get("status") != "running":
            info["mesh_repair"] = mesh_repair_state(character_name, bsig)
            info["tip_smoothing"] = extension_tip.tip_smoothing_state(character_name, bsig)
            model.update(face_info(character_name, path))
            model["collision"] = collision.ensure(character_name, bsig)
            info["channel_declarations"] = collision_channels.declarations_info(
                character_name, path, {**_read_sidecar(path), "collision": model["collision"]})
            info["extension_tips"] = extension_tip.tip_panels(character_name, bsig)
            info["extension"] = _with_preview_states(model_extension_state(character_name, bsig))
            extension_tip.group_tip_settings(info["extension_tips"], info["extension"])
        elif path is None and info.get("humanoid") and info.get("pipeline"):
            info["channel_declarations"] = collision_channels.declarations_info(character_name, None, {})
    except Exception:  # noqa: BLE001 — the poll never fails on the extras
        logger.exception("Plain body extras of %s failed", character_name)
    info["run_all"] = figure_build.base_run_all(character_name)
    info["activity"] = figure_build.base_activity(character_name)
    return info


def _with_preview_states(extension):
    """The base model's extension state with ``states``: what the Base body tab's state picker offers (Ruling A66,
    ``prompt_filters.bone_pose_states`` over the model's groups — empty without groups). None stays None."""
    if extension is None:
        return None
    from app.core.prompt_filters import bone_pose_states
    extension["states"] = bone_pose_states([group["id"] for group in extension.get("groups") or []])
    return extension


@router.get("/{character_name}/base-body/state-motion")
def base_state_motion(character_name: str, state: str,
                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The base model's motion with one state applied — a preview, never stored (module docstring)."""
    from app.core.extension_rig import motion_payload
    from app.core.prompt_filters import load_filters
    from app.models.character import get_character_profile
    _require_character(character_name)
    if not any(row["id"] == state and row.get("bone_pose") for row in load_filters()):
        raise HTTPException(status_code=404, detail="State not found or without a bone pose")
    profile = get_character_profile(character_name) or {}
    return {"state": state, "motion": motion_payload(character_name, profile=profile, apply_clothing=False,
                                                     preview_states=[state])}


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


def _template_item(character_name: str, item_id: str) -> Dict[str, Any]:
    from app.models.inventory import get_item
    _require_character(character_name)
    item = get_item(item_id)
    if not item or item.get("category") != "outfit_piece":
        raise HTTPException(status_code=404, detail="Outfit piece not found")
    return item


@router.get("/{character_name}/figure/template/{item_id}")
def get_template_params(character_name: str, item_id: str,
                        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import garment_template as gt
    item = _template_item(character_name, item_id)
    stored = gt.template_of(item)
    spec = {}
    for key, (kind, rule, default) in gt.PARAM_SPEC.items():
        spec[key] = ({"type": "choice", "choices": list(rule), "default": default} if kind == "choice"
                     else {"type": "number", "min": rule[0], "max": rule[1], "default": default})
    return {"item_id": item_id, "name": str(item.get("name") or item_id), "params": gt.params_of(item),
            "source": stored.get("source") or "", "updated_at": stored.get("updated_at") or "", "spec": spec,
            "built": list(gt.BUILT_KINDS), "cost": {"llm_calls": 1, "hub_jobs": 0, "cpu_s": gt.CPU_ESTIMATE_S}}


@router.post("/{character_name}/figure/template/{item_id}/suggest")
def suggest_template_params(character_name: str, item_id: str,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import garment_template as gt
    _template_item(character_name, item_id)
    try:
        return gt.suggest_params(item_id, character_name=character_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


class TemplateParamsRequest(BaseModel):
    params: Dict[str, Any]
    source: str = "user"


@router.put("/{character_name}/figure/template/{item_id}")
def put_template_params(character_name: str, item_id: str, body: TemplateParamsRequest,
                        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import garment_template as gt
    _template_item(character_name, item_id)
    try:
        record = gt.set_params(item_id, body.params, source=body.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"item_id": item_id, **record}


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


@router.get("/{character_name}/figure/stored/{key}/preview")
def preview_figure_stored(character_name: str, key: str,
                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import figure, outfit_bodies
    _require_character(character_name)
    try:
        return figure.delete_preview(character_name, key)
    except outfit_bodies.UnknownBody as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


# --- Outfit reference images (Ruling A74b) ---------------------------------


class OutfitReferenceRequest(BaseModel):
    image: str


@router.get("/{character_name}/figure/outfit-reference")
def get_outfit_reference(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_character(character_name)
    return _outfit_tile(character_name)


def _outfit_tile(character_name: str) -> Dict[str, Any]:
    from app.core import full_body_reference, outfit_references
    return full_body_reference.outfit_tile(character_name, outfit_references.info(character_name))


def _set_outfit_reference(character_name: str, image: str, origin: str) -> Dict[str, Any]:
    from app.core import full_body_reference
    try:
        full_body_reference.set_outfit(character_name, image, origin=origin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return _outfit_tile(character_name)


@router.post("/{character_name}/figure/outfit-reference")
def set_outfit_reference(character_name: str, body: OutfitReferenceRequest,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import full_body_reference
    _require_character(character_name)
    return _set_outfit_reference(character_name, body.image, full_body_reference.ORIGIN_GALLERY)


async def _read_reference_upload(request: Request) -> tuple:
    """``(bytes, file name)`` of a reference upload: capped by its declared length and while reading, checked by
    its bytes (the gallery upload's rules)."""
    from app.core.upload_limits import ensure_image, guard_content_length, read_upload_capped
    guard_content_length(request, what="Reference image")
    form = await request.form()
    file = form.get("file")
    if file is None or not getattr(file, "filename", ""):
        raise HTTPException(status_code=400, detail="No file uploaded")
    data = await read_upload_capped(file, what="Reference image")
    ensure_image(data, filename=file.filename, what="Reference image")
    return data, file.filename


@router.post("/{character_name}/figure/outfit-reference/upload")
async def upload_outfit_reference(character_name: str, request: Request,
                                  _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from pathlib import Path
    from starlette.concurrency import run_in_threadpool
    from app.core import full_body_reference, outfit_references
    _require_character(character_name)
    data, filename = await _read_reference_upload(request)
    try:
        name = await run_in_threadpool(outfit_references.store_reference, character_name, data,
                                       Path(filename or "").suffix, "outfitref")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await run_in_threadpool(_set_outfit_reference, character_name, name, full_body_reference.ORIGIN_UPLOAD)


@router.post("/{character_name}/figure/outfit-reference/generate", status_code=202)
def generate_outfit_reference(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import base_body, full_body_reference
    _require_character(character_name)
    try:
        full_body_reference.start_outfit(character_name)
    except base_body.MissingInput as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _outfit_tile(character_name)


@router.delete("/{character_name}/figure/outfit-reference/{key}")
def clear_outfit_reference(character_name: str, key: str,
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import outfit_references
    _require_character(character_name)
    try:
        cleared = outfit_references.clear_reference(character_name, key)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not cleared:
        raise HTTPException(status_code=404, detail="This outfit has no reference image")
    return _outfit_tile(character_name)


# --- The plain body's full-body reference (Ruling A87) ---------------------------


@router.get("/{character_name}/base-body/full-body-reference")
def get_base_reference(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import full_body_reference
    _require_character(character_name)
    return full_body_reference.base_tile(character_name)


def _set_base_reference(character_name: str, image: str, origin: str) -> Dict[str, Any]:
    from app.core import full_body_reference
    try:
        full_body_reference.set_base(character_name, image, origin=origin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return full_body_reference.base_tile(character_name)


@router.post("/{character_name}/base-body/full-body-reference")
def set_base_reference(character_name: str, body: OutfitReferenceRequest,
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import full_body_reference
    _require_character(character_name)
    return _set_base_reference(character_name, body.image, full_body_reference.ORIGIN_GALLERY)


@router.get("/{character_name}/figure/reference-image/{name}")
def get_reference_image(character_name: str, name: str, request: Request,
                        _: Dict[str, Any] = Depends(require_admin)):
    """A generated full-body reference (plain body or outfit) from ``model_refs/references`` — those are never
    gallery pictures (user rule 2026-11-16). 404 for a name outside that folder or a file gone."""
    from pathlib import Path
    from app.core.http_files import etag_file_response
    from app.core.outfit_references import references_dir
    _require_character(character_name)
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    try:
        root = references_dir(character_name).resolve()
        path = (root / name).resolve()
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found")
    if Path(name).name != name or not path.is_relative_to(root) or not path.is_file() \
            or path.suffix.lower() not in media:
        raise HTTPException(status_code=404, detail="Not found")
    return etag_file_response(path, request, media[path.suffix.lower()])


@router.post("/{character_name}/base-body/full-body-reference/upload")
async def upload_base_reference(character_name: str, request: Request,
                                _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from pathlib import Path
    from starlette.concurrency import run_in_threadpool
    from app.core import full_body_reference
    _require_character(character_name)
    data, filename = await _read_reference_upload(request)
    try:
        from app.core.outfit_references import store_reference
        name = await run_in_threadpool(store_reference, character_name, data, Path(filename or "").suffix, "fullbody")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await run_in_threadpool(_set_base_reference, character_name, name, full_body_reference.ORIGIN_UPLOAD)


@router.post("/{character_name}/base-body/full-body-reference/generate", status_code=202)
def generate_base_reference(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import base_body, full_body_reference
    _require_character(character_name)
    try:
        full_body_reference.start_base(character_name)
    except base_body.MissingInput as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return full_body_reference.base_tile(character_name)


@router.delete("/{character_name}/base-body/full-body-reference")
def clear_base_reference(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import full_body_reference
    _require_character(character_name)
    try:
        cleared = full_body_reference.clear_base(character_name)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not cleared:
        raise HTTPException(status_code=404, detail="The plain body has no full-body reference")
    return full_body_reference.base_tile(character_name)
