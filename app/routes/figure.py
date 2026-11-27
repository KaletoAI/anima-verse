"""Figure routes — the Build of a character's figure (``app/core/figure_build.py``;
plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 7).

Admin-only (``Depends(require_admin)`` on each, like the base-body and outfit
body actions):

* ``GET  /characters/open-steps`` — the character list's badges (Ruling A112):
  ``{characters: {name: figure_build.open_steps}}``, only characters with an
  open step or a running Build.

* ``GET  /characters/build-all`` · ``GET /characters/build-all/preview`` · ``POST /characters/build-all/start``
  · ``POST /characters/build-all/cancel`` — the character list's "Build all open" (``app/core/figure_batch.py``):
  per character with open work its base body (Run all until current), then its figure Build, at most three
  characters at once. Start answers 409 while one runs or with media generation switched off; cancel stops
  scheduling the characters that have not begun.

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
* ``GET  /characters/{c}/figure/accessory/{item_id}`` — an accessory piece's section (Ruling A118, A216):
  ``{item_id, name, mode, jewellery (None: no kind chosen), suggested (``accessory_spec.suggest_kind``), kinds,
  built_kinds, drop_presets, metals, cords + cord_thickness_mm + pendant_defaults + pendant (A225:
  ``accessory_build.pendant_row``), ranges, state, reason, metrics, built_at, cost {hub_jobs: 0}, glb_url (the
  preview GLB, its query names the build)}``; 404 for an unknown character or item.
* ``PUT  /characters/{c}/figure/accessory/{item_id} {jewellery}`` — store the description on the ITEM (every wearer,
  ``accessory_spec.normalize``); 400 for an unknown kind. Spends nothing — the accessory step becomes due.
* ``POST /characters/{c}/figure/accessory/{item_id}/switch {mode, kind}`` — a too-thin piece's switch to In body or
  to Accessory with a buildable kind (one locked write); 400 otherwise.
* ``POST /characters/{c}/figure/accessory/{item_id}/curve {drop_cm, thickness_mm}`` — the chain's centre line for
  those settings on the plain body (``accessory_build.preview_curve``, with the pendant's ``anchor`` and the skin's
  ``anchor_outward`` there — A225), nothing stored; 400 without a plain body.
* The explicit part / drop mesh job is ``POST /inventory/items/{item}/part-mesh`` since design G (plan-anhaenger
  Task 6; a necklace's pendant and a belt's buckle / charms are linked part items, earrings mesh their drop there).
* ``GET  /characters/{c}/figure/accessory/{item_id}/preview.glb`` — the plain body with the current build grafted (the
  plain body alone while not built); 404 without a plain body.
* ``GET  /characters/{c}/figure/template/{item_id}`` — a template piece's parameter dialog (Ruling A138,
  ``garment_template``): ``{item_id, name, params (None: none stored), source, updated_at, spec (the field
  schema: ``{field: {type, choices | min/max, default}}``), built (the kinds draped today), cost {llm_calls,
  hub_jobs, cpu_s}, progress (A168: this character's drape — ``garment_template.piece_progress``, with ``live``
  while it drapes, A172), default_kind + kind_defaults (A172: the starting values with nothing stored)}``; 404 for an
  unknown character or item.
* ``POST /characters/{c}/figure/template/{item_id}/suggest`` — ONE queued vision call (``TASK``) reads the item's
  picture and text: ``{params, errors, raw}``; saves nothing. 400 without a picture / for no outfit piece, 502
  when the LLM fails or answers no JSON.
* ``POST /characters/{c}/figure/template/{item_id}/preview {params}`` — A188: the draft drawn on the plain base-body
  front (``garment_preview.overlay``), pixel polygons; nothing saved.
* ``PUT  /characters/{c}/figure/template/{item_id} {params, source}`` — store the parameters on the ITEM
  (every wearer; ``garment_template.set_params``); spends no hub job — the next Build re-drapes, and a top's cut
  is started on the CPU at once (``garment_template_cut.schedule``). 400 with the validation errors (nothing stored).
* ``GET  /characters/{c}/figure/template/{item_id}/cut`` — the dialog's Texture tab
  (``garment_cut_texture.dialog_state`` + picture URLs; starts the piece's cut on the CPU when it is missing):
  ``{running, step, error, csig, record, can_generate, blocked_reason, pattern_reason, cutting, cut_at, current, plan, texture, applied, upscale, has_back, islands_sha, files, urls, pattern_url, answers,
  sleeve_print, has_sleeves, trim ("sleeves" / "pieces"), option_stale, back_detail, back_plain, back_measured_plain,
  back_forced, plain_back_limit}``.
* ``POST /characters/{c}/figure/template/{item_id}/cut/generate {only?}`` — the cut flow in the background (the back
  view when missing, the front job, the back job, the atlas applied; ``only`` "front" / "back" redoes one job) and
  the texture set to "cut"; 409 media off / already running / another hub-job flow of the piece (``piece_jobs``),
  503 empty chain (``NoRouteError`` text), 400 without a cut pattern or an item picture (never waits for a drape).
* ``POST /characters/{c}/figure/template/{item_id}/cut/use {job}`` — "Use this answer": the job's stored answer, also
  a rejected one, is accepted and the atlas composed on the CPU (0 image jobs); 400 without an answer, 409 running.
* ``POST /characters/{c}/figure/template/{item_id}/cut/sleeves {sleeve_print}`` — the sleeve option of the texture
  ("plain" / "picture"), a made atlas composed again on the CPU; 400 unknown value.
* ``POST /characters/{c}/figure/template/{item_id}/cut/back-job {back_job, render?}`` — the back-job option
  ("auto" / "render" / "front": kind default, always a back job, or front fabric over a plain back; part of the atlas
  key), ``render`` starts the back job.
* ``GET  /characters/{c}/figure/template/{item_id}/cut/<kind>.png[?v=<csig>]`` — the record's pictures (``kind``
  one of ``garment_cut_texture.CUT_FILES``); 404 when missing.
* ``GET  /characters/{c}/figure/template/{item_id}/pattern.png`` — the debug pattern sheet of the current cut
  (written by the cut-only run, rendered when missing); 404 while the piece is not cut.
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
* ``GET  /characters/{c}/base-body/pose-motion?poses=<group>:<pose>,…`` — the Poses → Places preview's pose pickers:
  ``{"poses", "motion"}``, the bare base model's motion with ONLY those group poses applied
  (``motion_payload(apply_clothing=False, preview_states=[], preview_poses=…)``); no poses = at rest. Nothing is
  saved; 400 for a pair whose group does not declare the pose, 404 for an unknown character. Each
  ``plain_body.extension.groups[i]`` carries ``poses`` (its declared pose ids) and ``preview_pose`` (pre-selected).
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
* ``POST /characters/{c}/figure/shape-view {view}`` — Regenerate ONE view of the body shape the worn figure stands
  on (round 2026-11-25, ``base_body.start_shape_view``): a forced render in the background — the front 1 image job,
  a back / side view 2 (the turn and the draft); the new view makes the stored shape outdated, the next Build meshes
  it again. 202 ``{status: "started", shape, view, jobs}``; 400 for a view that is not dressed, 409 off the
  pipeline, while a Build, a base step or another shape view runs, with nothing worn in the body or (back / side)
  without the shape's front, or with media generation switched off. ``body.shape.views`` / ``body.shape.regenerate``
  of ``GET …/figure`` are its thumbnails and its state.
* ``GET  /characters/{c}/figure/shape/{key}/views/{view}`` — one stored view picture of the body shape ``key``
  (``ob…``), ETag; 404 when absent, 400 for a key that is no body shape or an unknown view.
* ``GET  /characters/{c}/figure/stored`` — the stored body shapes and the
  plain body's texture bodies (``figure.stored``): ``{"stored": [{key, kind, bytes, built_for,
  built_for_name, outfits, last_used, reason, unneeded, deletable, refusal, history, spare, meshed, running,
  current}]}`` — a shape is kept only for the worn combination and the saved outfit sets
  (``figure.needed_shapes``, round 2026-11-25); the UI's bulk "Delete all not needed…" runs one DELETE per entry
  after its confirmation.
* ``GET /characters/{c}/figure/stored/{key}/preview`` — what that Delete
  would do (``figure.delete_preview``, Ruling A64): the files with their size,
  the outfit models deleted with a shape, whether it is deletable and why
  not; 404 when nothing of it is stored, 400 for a key of neither shape.
* ``DELETE /characters/{c}/figure/stored/{key}`` — delete ONE of them
  (``figure.delete_stored``, an explicit collect, Ruling 5a): 409 while an
  outfit would be built on it or the worn figure stands on it (a shape:
  ``figure.SHAPE_NEEDED`` / ``figure.SHAPE_CURRENT``, a texture
  body: ``outfit_bodies.TEXTURE_NEEDED``), a run works on it or a Build of
  the character runs (``figure.BUILD_RUNNING``), 404 when nothing of it is
  stored, 400 for a key of neither shape.
* ``GET /characters/{c}/base-body/full-body-reference`` — the Base body tab's
  "Full-body reference" tile (Ruling A87, ``full_body_reference.base_tile``).
* ``POST …/base-body/full-body-reference {image}`` (pick from the gallery),
  ``POST …/base-body/full-body-reference/upload`` (multipart ``file``; capped
  by ``guard_content_length`` / ``read_upload_capped``, checked by its bytes), ``DELETE …/base-body/full-body-reference``
  (clear) — SAVE ONLY: the front then shows as outdated with its cost.
* ``POST …/base-body/full-body-reference/generate`` — generate it from the
  profile image (``full_body_reference.start_base``, one image job). 202; 409
  without a profile image or while a reference of the character is generated.
* ``POST /characters/{c}/model3d/build-current`` — the 3D tab's "Build current
  outfit" while it serves a stand-in (``model3d_pipeline.build_current_outfit``:
  the character's Build, a click — ``{status: started | queued | current}``);
  400 off the pipeline.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.core.auth_dependency import require_admin
from app.core.log import get_logger
from app.core.route_limits import FIGURE_POLLS, FIGURE_POLLS_LIMIT, limited
from app.core.single_flight import SerialFlight
from app.models.character import get_character_dir

logger = get_logger("figure_routes")

router = APIRouter(prefix="/characters", tags=["figure"])

#: ``GET /characters/open-steps``: one roster computation at a time plus one follower (slot = the roster).
_ROSTER_FLIGHT = SerialFlight()


def _require_character(character_name: str) -> None:
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")


@router.get("/open-steps")
@limited(FIGURE_POLLS, FIGURE_POLLS_LIMIT)
def get_open_steps(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The character list's badges (Ruling A112): ``{"characters": {name: figure_build.open_steps(name)}}`` for
    every character of the roster (dormant included) — only those with an open step or a running Build.
    Concurrent polls share one computation (``_ROSTER_FLIGHT``, slot = the roster, key = the figure
    generation): a poll that finds a run with the same key waits for it, one with a newer key waits for the
    slot's single follower. Every caller gets its own copy. Stale badges are re-planned by
    ``figure_build``'s two background workers. The wait happens in this sync handler's worker thread, never on
    the event loop."""
    from app.core import figure, figure_build
    from app.models.character import list_available_characters
    names = list(list_available_characters(include_dormant=True))
    out = _ROSTER_FLIGHT.run(tuple(names), lambda: figure._generation[0],
                             lambda: figure_build.open_steps_roster(names))
    return {"characters": out}


@router.get("/build-all")
def get_build_all(lang: str = "en", _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Build all open (``figure_batch.status``): the last or current run, per character its phase and its
    reason in ``lang``."""
    from app.core import figure_batch
    return figure_batch.status(lang)


@router.get("/build-all/preview")
def preview_build_all(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """What a start would run (``figure_batch.candidates``) and whether media generation is on — the
    confirmation's numbers."""
    from app.core import figure_batch
    from app.imagegen.base import media_generation_enabled
    return {**figure_batch.candidates(), "media_generation_enabled": bool(media_generation_enabled())}


@router.post("/build-all/start", status_code=202)
def start_build_all(lang: str = "en", _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Start Build all open in the background; 409 while one runs or with media generation switched off (the
    detail in ``lang``)."""
    from app.core import figure_batch
    from app.core.i18n import t
    result = figure_batch.start()
    if result.get("status") != "started":
        raise HTTPException(status_code=409, detail=t(str(result.get("reason") or result.get("status")), lang))
    return figure_batch.status(lang)


@router.post("/build-all/cancel")
def cancel_build_all(lang: str = "en", _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Stop scheduling characters that have not begun; the running ones finish. 409 when none runs."""
    from app.core import figure_batch
    from app.core.i18n import t
    if not figure_batch.cancel():
        raise HTTPException(status_code=409, detail=t(figure_batch.NOT_RUNNING, lang))
    return figure_batch.status(lang)


@router.get("/{character_name}/figure")
@limited(FIGURE_POLLS, FIGURE_POLLS_LIMIT)
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
        from app.core import mouth_channel
        from app.models.character import get_character_profile
        # The mouth's teeth options (Ruling A206), complete; the Channels panel's mouth tab edits them.
        info["mouth_teeth"] = mouth_channel.teeth_options(get_character_profile(character_name) or {})
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
    ``prompt_filters.bone_pose_states`` over the model's groups — empty without groups). None stays None.

    Each group also gets what the Poses → Places preview's pose picker offers: ``poses`` (the pose ids the group's
    declaration names, sorted; [] without one) and ``preview_pose`` (the declaration's ``preview_pose`` when it
    names one of them, else "")."""
    if extension is None:
        return None
    from app.core.extension_rig import declared_motion_groups
    from app.core.prompt_filters import bone_pose_states
    groups = extension.get("groups") or []
    extension["states"] = bone_pose_states([group["id"] for group in groups])
    declared = {group["id"]: group for group in declared_motion_groups()}
    for group in groups:
        declaration = declared.get(group["id"]) or {}
        poses = sorted(declaration.get("poses") or {})
        group["poses"] = poses
        preview = declaration.get("preview_pose") or ""
        group["preview_pose"] = preview if preview in poses else ""
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


@router.get("/{character_name}/base-body/pose-motion")
def base_pose_motion(character_name: str, poses: str = "",
                     _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The base model's motion with the picked group poses applied — a preview, never stored (module docstring)."""
    from app.core.extension_rig import declared_motion_groups, motion_payload
    from app.models.character import get_character_profile
    _require_character(character_name)
    declared = {group["id"]: group.get("poses") or {} for group in declared_motion_groups()}
    picked: Dict[str, str] = {}
    for pair in (part.strip() for part in poses.split(",")):
        if not pair:
            continue
        group_id, sep, pose_id = pair.partition(":")
        if not sep or pose_id not in declared.get(group_id, {}):
            raise HTTPException(status_code=400, detail=f"Not a declared group pose: {pair}")
        picked[group_id] = pose_id
    profile = get_character_profile(character_name) or {}
    return {"poses": picked, "motion": motion_payload(character_name, profile=profile, apply_clothing=False,
                                                      preview_states=[], preview_poses=picked)}


@router.post("/{character_name}/figure/build", status_code=202)
def build_figure(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    _require_character(character_name)
    return start_manual_build(character_name)


@router.post("/{character_name}/figure/dismiss-failure")
def dismiss_figure_failure(character_name: str, body: Dict[str, Any] = Body(...),
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """A166: forget a failed step of the last Build (``figure_build.dismiss_failure``); ``{step}``."""
    from app.core import figure_build
    _require_character(character_name)
    step = str((body or {}).get("step") or "")
    if not step:
        raise HTTPException(status_code=400, detail="step missing")
    return {"ok": True, "dismissed": figure_build.dismiss_failure(character_name, step)}


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


class AccessoryRequest(BaseModel):
    jewellery: Dict[str, Any]


class AccessoryCurveRequest(BaseModel):
    drop_cm: float = 4.0
    thickness_mm: float = 1.5
    #: A234: the unsaved description of a kind other than the necklace (its rings are previewed instead).
    jewellery: Optional[Dict[str, Any]] = None


@router.get("/{character_name}/figure/accessory/{item_id}")
def get_accessory(character_name: str, item_id: str,
                  _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    import hashlib
    from urllib.parse import quote
    from app.core import accessory_build, accessory_spec, garment_set
    item = _template_item(character_name, item_id)
    state = accessory_build.accessory_state(character_name, item_id, item=item)
    record = state.get("record") or {}
    # the material is not in the asig (a change re-assembles, never rebuilds) but the preview shows it: a look-only
    # save (lens tint, frame colour, metal) must give a new URL, or the viewer keeps the cached model
    msig = hashlib.sha1(accessory_build.material_key(item).encode("utf-8")).hexdigest()[:8]
    glb_url = (f"/characters/{quote(character_name, safe='')}/figure/accessory/{quote(item_id, safe='')}"
               f"/preview.glb?v={state.get('asig') or ''}-{state['state']}-{record.get('built_at') or ''}"
               f"-{(record.get('base_model_sha256') or accessory_build.base_sha(character_name) or '')[:12]}-{msig}")
    return {"item_id": item_id, "name": str(item.get("name") or item_id), "mode": garment_set.mesh_mode_of(item),
            "jewellery": accessory_spec.of_item(item), "suggested": accessory_spec.suggest_kind(item),
            "kinds": list(accessory_spec.KINDS), "built_kinds": list(accessory_spec.BUILT_KINDS),
            "drop_presets": dict(accessory_spec.DROP_PRESETS), "metals": list(accessory_spec.METALS),
            "cords": list(accessory_spec.CORDS), "cord_thickness_mm": accessory_spec.CORD_THICKNESS_MM,
            "pendant_defaults": dict(accessory_spec.PENDANT_DEFAULTS),
            "pendant": accessory_build.pendant_row(state, accessory_spec.of_item(item), record),
            # design G: the linked parts (buckle / pendant / charms), one row per link
            "parts": _part_rows_with_mentions(item, state, record),
            "part_options": _part_options(),
            "ranges": {k: list(v) for k, v in accessory_spec.RANGES.items()},
            "strap_at": list(accessory_spec.STRAP_AT), "earring_styles": list(accessory_spec.EARRING_STYLES),
            "band_materials": list(accessory_spec.BAND_MATERIALS), "fingers": list(accessory_spec.FINGERS),
            "sides": list(accessory_spec.SIDES), "ring_sides": list(accessory_spec.RING_SIDES),
            "kind_widths": dict(accessory_spec.KIND_WIDTH_CM),
            "kind_thickness": dict(accessory_spec.KIND_THICKNESS_MM),
            "glasses": {"shapes": list(accessory_spec.GLASSES_SHAPES), "sizes": list(accessory_spec.GLASSES_SIZES),
                        "frames": list(accessory_spec.GLASSES_FRAMES), "temples": list(accessory_spec.GLASSES_TEMPLES),
                        "tints": list(accessory_spec.LENS_TINTS), "rim_mm": dict(accessory_spec.GLASSES_RIM_MM),
                        "clear_opacity": accessory_spec.CLEAR_OPACITY, "sun_opacity": accessory_spec.SUN_OPACITY,
                        "tint_colors": dict(accessory_spec.LENS_COLORS),
                        "acetate_color": accessory_spec.ACETATE_COLOR},
            "part_name": accessory_spec.part_name(accessory_spec.of_item(item)),
            "state": state["state"], "reason": state["reason"], "metrics": record.get("metrics") or None,
            "built_at": record.get("built_at") or "", "cost": {"hub_jobs": 0}, "glb_url": glb_url}


def _part_rows_with_mentions(item: Dict[str, Any], state: Dict[str, Any],
                             record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """``accessory_build.part_rows`` plus ``host_mentions`` per link: the host's own text already describes the part
    (``accessory_parts.host_mentions_part``) — the Wardrobe says so; nothing is changed automatically."""
    from app.core import accessory_build, accessory_parts, accessory_spec
    from app.models.inventory import get_item
    host_frag = str(item.get("prompt_fragment") or "")
    rows = accessory_build.part_rows(state, accessory_spec.of_item(item), record)
    for row in rows:
        part = get_item(row["item"]) or {}
        row["host_mentions"] = accessory_parts.host_mentions_part(host_frag, str(part.get("prompt_fragment") or ""))
    return rows


def _part_options() -> List[Dict[str, Any]]:
    """Every part item of the world and the shared library, for the link pickers: ``{id, name, image_url, state}``
    (``state`` the part mesh's, ``accessory_pendant.pendant_state``), sorted by id."""
    from app.core import accessory_parts, accessory_pendant
    out = []
    for item in accessory_parts.all_items():
        if not accessory_parts.is_part(item):
            continue
        iid = str(item.get("id") or "")
        try:
            st = accessory_pendant.pendant_state(iid)["state"]
        except ValueError:
            continue
        out.append({"id": iid, "name": str(item.get("name") or iid), "state": st,
                    "image_url": f"/inventory/items/{iid}/image" if item.get("image") else ""})
    return sorted(out, key=lambda o: o["id"])


@router.put("/{character_name}/figure/accessory/{item_id}")
def put_accessory(character_name: str, item_id: str, body: AccessoryRequest,
                  _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import accessory_spec
    from app.models.inventory import get_item, outfit_piece_lock, update_item
    _template_item(character_name, item_id)
    try:
        spec = accessory_spec.normalize(body.jewellery)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    with outfit_piece_lock(item_id):   # A216 review L5: the read and the write of the shared piece together
        piece = dict((get_item(item_id) or {}).get("outfit_piece") or {})
        piece["jewellery"] = spec
        try:
            saved = update_item(item_id, {"outfit_piece": piece})
        except ValueError as e:     # a link to a missing item or to an item that is no part (design G)
            raise HTTPException(status_code=400, detail=str(e))
        if saved is None:
            raise HTTPException(status_code=500, detail="The item could not be saved")
    return {"item_id": item_id, "jewellery": spec}


class ModeSwitchRequest(BaseModel):
    mode: str
    kind: str = ""


@router.post("/{character_name}/figure/accessory/{item_id}/switch")
def switch_piece_mode(character_name: str, item_id: str, body: ModeSwitchRequest,
                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Ruling A118 J6 (A216 review M2/L5): a too-thin piece's one-click switch — ``mode`` ``in_body``, or
    ``accessory`` with the buildable ``kind`` it is stored with; one locked read-modify-write of the piece, spends
    nothing. 400 for another mode or a kind this version does not build."""
    from app.core import accessory_spec, garment_set
    from app.models.inventory import get_item, outfit_piece_lock, update_item
    _template_item(character_name, item_id)
    if body.mode not in (garment_set.IN_BODY, garment_set.ACCESSORY):
        raise HTTPException(status_code=400, detail="Only In body or Accessory")
    if body.mode == garment_set.ACCESSORY and body.kind not in accessory_spec.BUILT_KINDS:
        raise HTTPException(status_code=400, detail="This kind of accessory is not built yet")
    with outfit_piece_lock(item_id):
        piece = dict((get_item(item_id) or {}).get("outfit_piece") or {})
        piece["mesh_mode"] = body.mode
        if body.mode == garment_set.ACCESSORY:
            raw = piece.get("jewellery") if isinstance(piece.get("jewellery"), dict) else {}
            piece["jewellery"] = accessory_spec.normalize({**raw, "kind": body.kind})
        if update_item(item_id, {"outfit_piece": piece}) is None:
            raise HTTPException(status_code=500, detail="The item could not be saved")
    return {"item_id": item_id, "mode": body.mode, "jewellery": piece.get("jewellery")}


@router.post("/{character_name}/figure/accessory/{item_id}/curve")
def preview_accessory_curve(character_name: str, item_id: str, body: AccessoryCurveRequest,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import accessory_build, accessory_spec
    _template_item(character_name, item_id)
    if body.jewellery and body.jewellery.get("kind") not in (None, "necklace"):
        try:
            spec = accessory_spec.normalize(body.jewellery)
            return accessory_build.preview_rings(character_name, spec)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=accessory_build.failure_text(e))
    drop = min(max(float(body.drop_cm), accessory_spec.RANGES["drop_cm"][0]), accessory_spec.RANGES["drop_cm"][1])
    thick = min(max(float(body.thickness_mm), accessory_spec.RANGES["thickness_mm"][0]),
                accessory_spec.RANGES["thickness_mm"][1])
    try:
        return accessory_build.preview_curve(character_name, item_id, drop_cm=drop, thickness_mm=thick)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=accessory_build.failure_text(e))


@router.get("/{character_name}/figure/accessory/{item_id}/preview.glb")
def accessory_preview_glb(character_name: str, item_id: str,
                          _: Dict[str, Any] = Depends(require_admin)) -> Response:
    from app.core import accessory_build
    _template_item(character_name, item_id)
    glb = accessory_build.preview_glb(character_name, item_id)
    if glb is None:
        raise HTTPException(status_code=404, detail=accessory_build.REASON_NO_BODY)
    return Response(glb, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{character_name}/figure/template/{item_id}")
def get_template_params(character_name: str, item_id: str, picture: bool = True,
                        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import garment_template as gt, piece_material
    item = _template_item(character_name, item_id)
    stored = gt.template_of(item)
    progress = gt.piece_progress(character_name, item_id, item=item)
    spec = {}
    for key, (kind, rule, default) in gt.PARAM_SPEC.items():
        spec[key] = ({"type": "choice", "choices": list(rule), "default": default} if kind == "choice"
                     else {"type": "number", "min": rule[0], "max": rule[1], "default": default})
    return {"item_id": item_id, "name": str(item.get("name") or item_id),
            # plan E6: the stored dict (a top's parked field set included) — the dialog shows ``fields_of`` of it
            "params": gt.stored_of(item),
            "source": stored.get("source") or "", "updated_at": stored.get("updated_at") or "", "spec": spec,
            "built": list(gt.BUILT_KINDS), "kind_fields": {**{k: list(v) for k, v in gt.KIND_FIELDS.items()}, "top:cups": list(gt.TOP_CUPS_FIELDS)},
            # A172: with nothing stored the dialog starts from the kind the item most likely is (slots / name),
            # and a kind change starts from that kind's values
            "default_kind": gt.default_kind(item),
            # A223: the piece's material preset (the Wardrobe's select, also shown in the dialog): a metal preset
            # stays metal on every fabric but a leather finish, which sets its own surface
            "material": piece_material.describe(item),
            "kind_defaults": {k: gt.kind_defaults(k) for k in gt.KINDS},
            "back_job_defaults": dict(gt.BACK_JOB_DEFAULTS),
            # bug round 2026-11-20: named presets the dialog offers per kind (trousers: leggings)
            "presets": {"trousers": {"leggings": dict(gt.LEGGINGS)}},
            "cost": {"llm_calls": 1, "hub_jobs": 0, "cpu_s": gt.CPU_ESTIMATE_S},
            # A168: this character's drape of the piece — state, reason and the step list (``piece_progress``)
            "progress": progress,
            # A205: the piece-only views the bake reads (``garment_template_views.status``)
            "views": _template_views(character_name, item_id),
            # the item picture beside the fields — the source of the texture (user finding 2026-11-20)
            # (``picture=0``: the dialog's progress poll, which keeps the picture it has)
            "front_picture": (_front_picture(character_name, item_id, item)
                              if picture else None)}


def _front_picture(character_name: str, item_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """The picture the template dialog shows beside its fields: the item's own picture — the source of the piece's
    texture (the piece-only views and the texture from cut are both made from it; user finding 2026-11-20: a template
    piece never gets the clothing chain's worn front, so that lookup is gone). ``{source ("item" / ""), url}``;
    nothing is generated."""
    from urllib.parse import quote
    if item.get("image"):
        return {"source": "item", "url": f"/inventory/items/{quote(item_id, safe='')}/image"}
    return {"source": "", "url": ""}


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
    _schedule_cut(character_name, item_id)
    return {"item_id": item_id, **record}


def _schedule_cut(character_name: str, item_id: str) -> None:
    """Cut-first (2026-11-21): start the piece's cut-only run when its pattern is missing (``garment_template_cut``,
    CPU, 0 hub jobs, no piece claim) — after a parameter save and whenever the dialog reads its Texture tab. Never
    fails the request."""
    from app.core import garment_template_cut as gtc
    try:
        gtc.schedule(character_name, item_id)
    except Exception as e:  # noqa: BLE001 — the dialog shows the missing cut and its reason
        logger.warning("Cut of %s for %s not scheduled: %s", item_id, character_name, e)


class TemplatePreviewRequest(BaseModel):
    params: Dict[str, Any]


@router.post("/{character_name}/figure/template/{item_id}/preview")
def preview_template_params(character_name: str, item_id: str, body: TemplatePreviewRequest,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """A188: the dialog's draft drawn on the character's plain base-body front (``garment_preview.overlay``): the
    picture, its pixel <-> metre registration and the piece as pixel polygons. Nothing saved or generated."""
    from app.core import garment_preview
    _template_item(character_name, item_id)
    try:
        return garment_preview.overlay(character_name, item_id, body.params)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}


@router.get("/{character_name}/figure/template/{item_id}/front/{key}.png")
def template_front_picture(character_name: str, item_id: str, key: str,
                           _: Dict[str, Any] = Depends(require_admin)):
    """A195: the dressed front without the piece (``garment_preview_front``), by its content key — immutable."""
    from fastapi.responses import FileResponse
    from app.core import garment_preview_front
    _template_item(character_name, item_id)
    hit = garment_preview_front.cached(character_name, key)
    if hit is None:
        raise HTTPException(status_code=404, detail="no such picture")
    return FileResponse(hit[0], media_type="image/png", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.post("/{character_name}/figure/template/{item_id}/front/retry")
def retry_template_front(character_name: str, item_id: str,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """A195: forget a failed dressed-front render so the next preview starts it again."""
    from app.core import garment_preview_front
    _template_item(character_name, item_id)
    garment_preview_front.retry(character_name, item_id)
    return {"ok": True}


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


class ShapeViewRequest(BaseModel):
    view: str


@router.post("/{character_name}/figure/shape-view", status_code=202)
def regenerate_shape_view(character_name: str, body: ShapeViewRequest,
                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    from app.core import base_body
    from app.imagegen.base import MediaGenerationDisabled
    _require_character(character_name)
    try:
        return base_body.start_shape_view(character_name, body.view)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (LookupError, MediaGenerationDisabled) as e:
        raise HTTPException(status_code=409, detail=str(e.args[0] if e.args else e))


@router.get("/{character_name}/figure/shape/{key}/views/{view}")
def get_shape_view_image(character_name: str, key: str, view: str, request: Request,
                         _: Dict[str, Any] = Depends(require_admin)):
    import mimetypes
    from app.core import base_body
    from app.core.http_files import etag_file_response
    from app.core.model_refs import find_ref_image
    if not base_body.is_outfit_body_signature(key):
        raise HTTPException(status_code=400, detail="not a body shape key")
    if view not in base_body.BASE_VIEWS:
        raise HTTPException(status_code=400, detail=f"view must be one of {', '.join(base_body.BASE_VIEWS)}")
    _require_character(character_name)
    path = find_ref_image(character_name, base_body._kind(view), key)
    if path is None:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _encoding = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "application/octet-stream")


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


class ReferenceRequest(BaseModel):
    image: str


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
def set_base_reference(character_name: str, body: ReferenceRequest,
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
    from app.core.reference_images import references_dir
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
        from app.core.reference_images import store_reference
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


# --- A205: the piece-only views of a template piece ------------------------------------------------

def _template_views(character_name: str, item_id: str) -> Dict[str, Any]:
    from app.core import garment_template_views as tv
    return tv.status(character_name, item_id)


def _template_view_name(view: str) -> str:
    from app.core import garment_template_views as tv
    if view not in tv.VIEWS:
        raise HTTPException(status_code=400, detail=f"view must be one of {', '.join(tv.VIEWS)}")
    return view


@router.get("/{character_name}/figure/template/{item_id}/views")
def get_template_views(character_name: str, item_id: str,
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """A205: the template piece's piece-only views — per view the accepted view, its attempts and whether a
    render runs; ``hub_jobs`` = the first attempts of the missing views."""
    _template_item(character_name, item_id)
    return _template_views(character_name, item_id)


@router.post("/{character_name}/figure/template/{item_id}/views/{view}/generate")
def generate_template_view(character_name: str, item_id: str, view: str,
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """A205, Generate / Regenerate: up to 2 image jobs (occasion ``garment_view``) for ONE view, in the
    background. 409 while that view already renders."""
    from app.core import garment_template_views as tv
    from app.imagegen.base import media_generation_enabled
    _template_item(character_name, item_id)
    _template_view_name(view)
    if not media_generation_enabled():
        raise HTTPException(status_code=409, detail="Media generation is switched off")
    try:
        started = tv.start(character_name, item_id, view)
    except tv.Busy as e:          # another hub-job flow of this piece runs (``piece_jobs``)
        raise HTTPException(status_code=409, detail=str(e))
    if not started:
        raise HTTPException(status_code=409, detail="This view is being made already")
    return _template_views(character_name, item_id)


def _piece_free(character_name: str, item_id: str) -> None:
    """409 while a hub-job flow of the piece runs (``piece_jobs``): a view changed under a running cut would key its
    record with a back view the back job never read."""
    from app.core import piece_jobs
    held = piece_jobs.reason(character_name, item_id)
    if held:
        raise HTTPException(status_code=409, detail=held)


@router.post("/{character_name}/figure/template/{item_id}/views/{view}/use/{attempt}")
def use_template_view(character_name: str, item_id: str, view: str, attempt: int,
                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """A205, "Use this": a stored attempt becomes the view (a refused one accepted by the user). No job. 409 while a
    hub-job flow of the piece runs."""
    from app.core import garment_template_views as tv
    _template_item(character_name, item_id)
    _template_view_name(view)
    _piece_free(character_name, item_id)
    try:
        tv.use_attempt(character_name, item_id, view, attempt)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _template_views(character_name, item_id)


@router.post("/{character_name}/figure/template/{item_id}/views/{view}/upload")
async def upload_template_view(character_name: str, item_id: str, view: str, request: Request,
                               _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """A205, Upload: an image file (multipart ``file``) becomes the view — cut out and checked like a render; a
    refused upload is accepted by the user with its reasons recorded. No job. 413 / 415 for an oversized or
    non-image body; 409 while a hub-job flow of the piece runs."""
    from starlette.concurrency import run_in_threadpool
    from app.core import garment_template_views as tv
    from app.core.upload_limits import ensure_image, guard_content_length, read_upload_capped
    _template_item(character_name, item_id)
    _template_view_name(view)
    _piece_free(character_name, item_id)
    guard_content_length(request, what="Piece-only view")
    form = await request.form()
    file = form.get("file")
    if file is None or isinstance(file, str):
        raise HTTPException(status_code=400, detail="No file uploaded")
    data = await read_upload_capped(file, what="Piece-only view")
    ensure_image(data, filename=str(getattr(file, "filename", "") or ""), what="Piece-only view")
    try:
        return await run_in_threadpool(tv.upload, character_name, item_id, view, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{character_name}/figure/template/{item_id}/views/{view}")
def delete_template_view(character_name: str, item_id: str, view: str,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """A205: drop the accepted view (the bake falls back to the item picture; a sheer piece reads due). 409 while a
    hub-job flow of the piece runs."""
    from app.core import garment_template_views as tv
    _template_item(character_name, item_id)
    _piece_free(character_name, item_id)
    return tv.remove(character_name, item_id, _template_view_name(view))


@router.get("/{character_name}/figure/template/{item_id}/views/{view}.png")
def template_view_image(character_name: str, item_id: str, view: str, attempt: int = 0,
                        _: Dict[str, Any] = Depends(require_admin)):
    """A205: the accepted view (``attempt`` 0) or a stored attempt's cut-out."""
    from fastapi.responses import FileResponse
    from app.core import garment_template_views as tv
    _template_item(character_name, item_id)
    _template_view_name(view)
    path = (tv.view_path(character_name, item_id, view) if attempt <= 0
            else tv.attempt_path(character_name, item_id, view, attempt).with_name(
                f"{item_id}_{view}.try{int(attempt)}.cut.png"))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No such view")
    return FileResponse(str(path), media_type="image/png", headers={"Cache-Control": "no-cache"})


# --- texture from cut (plan 2026-11-20-template-cut-uv-texture, Task 10) -----------------------------------------

def _template_cut_payload(character_name: str, item_id: str) -> Dict[str, Any]:
    """``_template_cut_body`` inside one read scope (``read_scope``, plan 2026-11-24-figure-poll-caches, Task 5): the
    cut key the schedule, the pattern state and the dialog ask for is computed once per request."""
    from app.core import read_scope
    with read_scope.scope():
        return _template_cut_body(character_name, item_id)


def _template_cut_body(character_name: str, item_id: str) -> Dict[str, Any]:
    """``garment_cut_texture.dialog_state`` plus the picture URLs (``urls``: template / raw / atlas of the current
    csig, "" for a missing file; the query names the csig, so a new attempt is a new URL) and ``pattern_url`` (the
    debug sheet of the current islands, "" without islands)."""
    from urllib.parse import quote
    from app.core import garment_cut_texture as gct
    _schedule_cut(character_name, item_id)
    state = gct.dialog_state(character_name, item_id)
    base = f"/characters/{quote(character_name, safe='')}/figure/template/{quote(item_id, safe='')}"
    sig = state.get("csig")
    state["urls"] = {k: f"{base}/cut/{k}.png?v={sig}" if sig and state["files"].get(k) else ""
                     for k in gct.CUT_FILES}
    sha = state.get("islands_sha") or ""
    state["pattern_url"] = f"{base}/pattern.png?v={sha[:12]}" if sha else ""
    return state


@router.get("/{character_name}/figure/template/{item_id}/cut")
def get_template_cut(character_name: str, item_id: str,
                     _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The template dialog's "Texture from cut" box: ``{running, error, csig, record, can_generate, blocked_reason,
    upscale, islands_sha, files, urls, pattern_url}`` (``_template_cut_payload``)."""
    _template_item(character_name, item_id)
    return _template_cut_payload(character_name, item_id)


class TemplateCutRequest(BaseModel):
    #: "" = the whole flow (Run all); "front" / "back" = redo that one image job (the other job's answer is re-used).
    only: str = ""


@router.post("/{character_name}/figure/template/{item_id}/cut/generate")
def generate_template_cut(character_name: str, item_id: str, body: Optional[TemplateCutRequest] = None,
                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """"Make texture from cut": the flow in the background (``garment_cut_texture`` module comment: the back view when
    missing, a routed upscale of a small item picture, the front job, the back job, then the atlas applied to the
    figure; ``only`` redoes one job). Selects the texture "cut" on the piece. Checked before the thread starts: media
    off -> 409 through the global ``MediaGenerationDisabled`` handler, an empty chain -> 503 with the ``NoRouteError``
    text, no cut pattern or no item picture -> 400, already running or another hub-job flow of this
    piece running (``piece_jobs``) -> 409 with its reason. Answers the box's payload."""
    from app.core import garment_cut_texture as gct
    from app.imagegen.routing import NoRouteError
    _template_item(character_name, item_id)
    only = (body.only if body else "") or None
    try:
        started = gct.start(character_name, item_id, only=only)
    except NoRouteError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (gct.NotReady, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except gct.Busy as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not started:
        raise HTTPException(status_code=409, detail="The texture from cut is being made already")
    return _template_cut_payload(character_name, item_id)


class TemplateCutUseRequest(BaseModel):
    #: The job whose shown answer goes on the figure ("front" / "back") — also a rejected one.
    job: str
    #: The render attempt whose answer it is (``attempts`` of the job's record entry); None = the job's current one.
    attempt: Optional[int] = None


@router.post("/{character_name}/figure/template/{item_id}/cut/use")
def use_template_cut_answer(character_name: str, item_id: str, body: TemplateCutUseRequest,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """"Use this answer" (user test 2026-11-21): the job's stored answer — passed or rejected by a gate — is accepted
    and the atlas composed with it on the CPU in the background (``garment_cut_texture.recompose``, 0 image jobs),
    then applied to the figure; a job without an answer yet stays for Run all. 400 when the job has no answer or the
    piece no cut pattern, 409 while a flow of this piece runs. Answers the box's payload."""
    from app.core import garment_cut_texture as gct
    _template_item(character_name, item_id)
    try:
        started = gct.start_recompose(character_name, item_id, accept=body.job, attempt=body.attempt)
    except (gct.NotReady, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except gct.Busy as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not started:
        raise HTTPException(status_code=409, detail="The texture from cut is being made already")
    return _template_cut_payload(character_name, item_id)


class TemplateCutSleevesRequest(BaseModel):
    #: ``garment_template.SLEEVE_PRINTS``: "plain" (the front panel's fabric) / "picture" (the model's sleeves).
    sleeve_print: str


@router.post("/{character_name}/figure/template/{item_id}/cut/sleeves")
def set_template_cut_sleeves(character_name: str, item_id: str, body: TemplateCutSleevesRequest,
                             _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The Texture tab's sleeve option: stores the piece's ``sleeve_print`` (texture only — no drape) and composes a
    made atlas again on the CPU (``garment_cut_texture.set_sleeve_print``, 0 image jobs). 400 for an unknown value or
    a piece without parameters, 409 while a flow of this piece runs. Answers the box's payload plus ``recompose``."""
    from app.core import garment_cut_texture as gct
    _template_item(character_name, item_id)
    try:
        result = gct.set_sleeve_print(character_name, item_id, body.sleeve_print)
    except (gct.NotReady, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except gct.Busy as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {**_template_cut_payload(character_name, item_id), "recompose": result["recompose"]}


class TemplateCutBackJobRequest(BaseModel):
    #: ``garment_template.BACK_JOBS``: "auto" (kind default) / "render" (always a back job) / "front" (a plain back view gets the front's fabric).
    back_job: str
    #: Start the back job right away ("Render back job…"): the front answer is kept.
    render: bool = False


@router.post("/{character_name}/figure/template/{item_id}/cut/back-job")
def set_template_cut_back_job(character_name: str, item_id: str, body: TemplateCutBackJobRequest,
                              _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The Texture tab's back-job option: stores the piece's ``back_job`` (part of the atlas key, no drape —
    ``garment_cut_texture.set_back_job``) and, with ``render``, starts the back job (``only="back"``). The setting is
    stored before the start is checked: media off -> 409, an empty chain -> 503, no cut / unknown value -> 400,
    another flow of the piece -> 409, as ``/cut/generate``. Answers the box's payload plus ``started``."""
    from app.core import garment_cut_texture as gct
    from app.imagegen.routing import NoRouteError
    _template_item(character_name, item_id)
    try:
        result = gct.set_back_job(character_name, item_id, body.back_job, render=body.render)
    except NoRouteError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (gct.NotReady, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except gct.Busy as e:
        raise HTTPException(status_code=409, detail=str(e))
    if body.render and not result["started"]:
        raise HTTPException(status_code=409, detail="The texture from cut is being made already")
    return {**_template_cut_payload(character_name, item_id), "started": result["started"]}


@router.get("/{character_name}/figure/template/{item_id}/cut/{kind}.png")
def template_cut_image(character_name: str, item_id: str, kind: str, request: Request, v: Optional[str] = None,
                       _: Dict[str, Any] = Depends(require_admin)):
    """One picture of the cut record (``kind`` one of ``garment_cut_texture.CUT_FILES``: each job's template, its
    Picture 2 and its answer, and the atlas) of csig ``v`` (else the current one); 404 when it does not exist."""
    from app.core import garment_cut_texture as gct
    from app.core.http_files import etag_file_response
    _template_item(character_name, item_id)
    path = gct.cut_file(character_name, item_id, kind, v)
    if path is None:
        raise HTTPException(status_code=404, detail="No such picture")
    return etag_file_response(path, request, "image/png")


@router.get("/{character_name}/figure/template/{item_id}/pattern.png")
def template_pattern_image(character_name: str, item_id: str, request: Request,
                           _: Dict[str, Any] = Depends(require_admin)):
    """The debug pattern sheet of the piece's current cut (``garment_cut_texture.pattern_sheet_file``: written by the
    cut-only run beside its islands, rendered when missing); 404 while the piece is not cut."""
    from app.core import garment_cut_texture as gct
    from app.core.http_files import etag_file_response
    _template_item(character_name, item_id)
    path = gct.pattern_sheet_file(character_name, item_id)
    if path is None:
        raise HTTPException(status_code=404, detail="The piece's pattern is not cut yet")
    return etag_file_response(path, request, "image/png")
