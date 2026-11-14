"""Character routes - Character management, images, and profile"""
import io
import os
import time
import mimetypes
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Literal, Optional
from app.core.auth_dependency import get_current_user_from_ctx, require_admin
from app.core.explicit_backend import require_explicit_backend
from app.core.http_files import etag_file_response, etag_matches
from app.core.portrait_images import (
    PortraitProcessingError, character_image_path, transparent_portrait_path)
from app.core.log import get_logger
from app.core.upload_limits import (MODEL_UPLOAD_MAX_BYTES, ensure_image,
                                    ensure_mp4, guard_content_length,
                                    max_pack_bytes, read_upload_capped)

logger = get_logger("characters")

from app.models.character import (
    get_character_appearance,
    save_character_current_location,
    get_effective_activity,
    set_pose_intent,
    clear_pose_intent,
    get_character_current_feeling,
    save_character_current_feeling,
    update_outfit_image,
    get_character_dir,
    get_character_images_dir,
    add_character_image,
    get_character_images,
    get_character_image_comments,
    get_character_image_prompts,
    get_character_image_metadata,
    get_character_profile_image,
    set_character_profile_image,
    delete_character,
    delete_character_image,
    get_character_skill_config,
    save_character_skill_config,
    get_character_profile,
    save_character_profile,
    get_character_config,
    save_character_config,
    get_character_current_room,
    add_character_image_prompt,
    add_character_image_metadata,
    get_character_outfits_dir,
    MODEL_RIG_VALUES)
from app.core import character_ops

from app.core.timeutils import utc_now, utc_now_iso

router = APIRouter(prefix="/characters", tags=["characters"])


def _can_view_rule_details() -> bool:
    user = get_current_user_from_ctx()
    return bool(user and user.get("role") == "admin")


class OutfitLockBody(BaseModel):
    """Body of ``POST /characters/{name}/outfit-lock``."""
    locked: bool


@router.get("/available-models")
def get_available_models() -> Dict[str, Any]:
    """Lists available models from all configured providers.

    Returns model lists grouped by provider, plus current task defaults.
    Used by the frontend for per-character model selection dropdowns.
    """
    return character_ops.build_available_models()


@router.get("/list")
def list_characters() -> Dict[str, Any]:
    """List all available characters, including temporary NPCs.

    Each row contains name, template and temporary, allowing the UI to filter
    by template without loading individual profiles. Avatar selection uses
    /account/characters and filters allowed_characters and playable_avatar.
    Use one roster query (DATA-11); never load a profile per character."""
    return {"characters": _roster_rows()}


def _roster_rows() -> List[Dict[str, Any]]:
    """``[{name, template, temporary, status}]`` for the whole roster from ONE query.

    Both fields sit in the ``characters`` table, so nothing here needs a
    profile load (DATA-11: ``get_character_profile`` + ``is_temporary_npc``
    were two full profile loads plus a template deepcopy PER character —
    80 loads for a 40-character roster).

    ``template`` is resolved exactly the way ``get_character_profile`` does:
    a ``template`` key IN the profile blob wins (even when it is empty or
    null), the ``template`` COLUMN is the fallback. ``temporary`` is
    ``character_template.template_feature(…, "temporary_npc")`` — a property
    of the KIND of character, so the template features are read ONCE per
    distinct template name, not once per character.

    Roster gate = the one of ``list_available_characters``: reserved and
    underscore names are no characters, a POOLED NPC is not in the world. A
    DORMANT character (a linked family member standing nowhere right now) IS
    listed — the admin edits it while it is dormant — with its ``status``, so
    the list can show the badge.
    """
    from app.core.db import get_connection
    from app.models.character import DORMANT_STATUS, _is_real_character, is_out_of_world
    from app.models.character_template import get_template
    try:
        rows = get_connection().execute(
            "SELECT name, COALESCE(status, ''), COALESCE(template, ''), "
            "       json_valid(profile_json), "
            "       CASE WHEN json_valid(profile_json) "
            "            THEN json_type(profile_json, '$.template') END, "
            "       CASE WHEN json_valid(profile_json) "
            "            THEN json_extract(profile_json, '$.template') END "
            "FROM characters ORDER BY name ASC"
        ).fetchall()
    except Exception as e:
        logger.error("characters/list roster query failed: %s", e, exc_info=True)
        return []
    feature_cache: Dict[str, bool] = {}

    def _temporary(template_name: str) -> bool:
        key = template_name or "human-default"
        if key not in feature_cache:
            try:
                tmpl = get_template(key) or {}
                feature_cache[key] = bool((tmpl.get("features") or {}).get(
                    "temporary_npc", False))
            except Exception:
                feature_cache[key] = False
        return feature_cache[key]

    out: List[Dict[str, Any]] = []
    for name, status, tmpl_col, blob_ok, blob_type, blob_value in rows:
        if not _is_real_character(name) or (
                is_out_of_world(status) and status != DORMANT_STATUS):
            continue
        if not blob_ok:
            template = ""            # an unreadable blob has no template
        elif blob_type is not None:  # the key EXISTS in the blob and wins
            template = blob_value or ""
        else:
            template = (tmpl_col or "").strip()
        out.append({"name": name, "template": template,
                    "temporary": _temporary(template), "status": status})
    return out


@router.get("/at-location")
def characters_at_location(location: str, room: str = "") -> Dict[str, Any]:
    """Return characters at a location ID or name.

    An optional room adds a same_room flag without filtering the result,
    so the UI can dim characters in other rooms at the same location."""
    return character_ops.build_characters_at_location(location, room)


@router.get("/chatbots")
def list_chatbots() -> Dict[str, Any]:
    """List chatbots whose templates disable locations.

    These characters have no world position and are always available."""
    return character_ops.build_chatbots_list()


@router.post("/create")
async def create_character(request: Request) -> Dict[str, Any]:
    """Create a character with an empty profile and the assigned template."""
    try:
        return await character_ops.create_character_core(request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/profile-image-prompt")
def profile_image_prompt(character_name: str) -> Dict[str, Any]:
    """Resolve the face prompt used by the profile image dialog, matching generate-profile-image."""
    from app.models.character import get_character_profile
    from app.models.character_template import get_template
    profile = get_character_profile(character_name) or {}
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    return {"prompt": character_ops._resolve_face_prompt(profile, character_name, tmpl)}


@router.get("/{character_name}/current-location")
def get_character_current_location_route(character_name: str) -> Dict[str, Any]:
    """Return the current virtual location."""
    return character_ops.build_current_location_payload(character_name)


@router.get("/{character_name}/notice")
def get_character_notice_route(character_name: str) -> Dict[str, Any]:
    """Return persistent notices for the avatar header.

    force_warning contains the active force rule or None; avatars do not
    automatically execute it. critical_events contains unresolved disruption
    and danger events at the current location, newest first."""
    return character_ops.build_character_notice(character_name)


@router.post("/{character_name}/current-location")
async def update_character_current_location(character_name: str, request: Request) -> Dict[str, Any]:
    """Update the current virtual location."""
    try:
        return await character_ops.apply_current_location(character_name, request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/place-on-map")
async def place_character_on_map(
        character_name: str, request: Request,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Places a character by hand: location + room, as an admin TELEPORT.

    ADMIN-ONLY. Writes under ``/characters/...`` are open to any logged-in
    user for the characters they may touch; moving an arbitrary figure across
    the world is not one of those — hence the explicit dependency on top of
    the auth middleware.

    Body: ``{"location_id", "current_room"?, "leave_party"?}``; the behaviour
    and the gates are documented on ``character_ops.apply_place_on_map``.
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body must be JSON")
    try:
        return await character_ops.apply_place_on_map(character_name, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/current-activity")
def get_effective_activity_route(character_name: str) -> Dict[str, Any]:
    """Return the current activity."""
    activity = get_effective_activity(character_name)
    return {"character": character_name, "current_activity": activity or ""}


@router.post("/{character_name}/current-activity")
async def update_character_current_activity(character_name: str, request: Request) -> Dict[str, Any]:
    """Update the character's current activity."""
    import asyncio as _aio
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        activity = data.get("current_activity", "")

        # Explicitly setting an activity on a SLEEPING character wakes them
        # first — the is_sleeping flag is the display authority
        # (get_effective_activity returns "Sleeping" and would hide the new
        # pose, which read like "saving does not work" in the admin UI).
        woke = False
        if activity.strip():
            from app.models.character import is_character_sleeping, set_is_sleeping, wake_from_offmap
            if is_character_sleeping(character_name):
                set_is_sleeping(character_name, False)
                try:
                    wake_from_offmap(character_name)
                except Exception:
                    pass
                woke = True

        # Set the free-text pose (no library matching, no auto room move —
        # room/location stay unchanged, the pose is free text).
        # Off the event loop: set_pose_intent resolves the text against the
        # pose catalog, which may embed the text (a routed external embedding
        # endpoint is a blocking HTTP call) and writes the DB. Running that
        # inline would stall every SSE stream.
        from app.core.pose_catalog import PairPoseWithoutPartner
        try:
            await _aio.to_thread(set_pose_intent, character_name, activity)
        except PairPoseWithoutPartner as e:
            raise HTTPException(
                status_code=409,
                detail=f"'{e}' is a two-person pose — it is started as a pair "
                       f"interaction, not set on one character")

        return {"status": "success", "character": character_name,
                "current_activity": activity, "woke": woke,
                "current_room": "", "current_room_id": ""}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/actions")
def list_actions_route(character_name: str, limit: int = 30) -> Dict[str, Any]:
    """Recent actions for this character — from the character_action_log table.
    Sorted newest-first. Used by the avatar's Action panel for history.
    """
    try:
        from app.models.action_log import list_action_log
        entries = list_action_log(character_name, limit=limit)
        return {"character": character_name, "entries": entries}
    except Exception as e:
        logger.exception("list_actions_route failed for %s", character_name)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/act")
async def act_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Avatar (or any character) performs a concrete action visible to
    everyone in the chosen scope. Goes through the Storyteller-LLM and may
    resolve an active disruption/danger event.
    """
    try:
        data = await request.json()
        text = (data.get("text") or "").strip()
        scope = (data.get("scope") or "here").strip().lower()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        if scope not in ("here", "location"):
            raise HTTPException(status_code=400, detail="scope must be 'here' or 'location'")

        from app.core.act_engine import perform_act
        result = await perform_act(character_name, text, scope)
        if result.get("busy"):
            raise HTTPException(status_code=409, detail=result.get("summary", ""))

        return {
            "status": "success",
            "character": character_name,
            "scope": scope,
            "text": text,
            "narration": result.get("narration", ""),
            "resolved": bool(result.get("resolved")),
            "event_id": result.get("event_id"),
            "tools_fired": result.get("tools_fired", []),
            "summary": result.get("summary", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("act_route failed for %s", character_name)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/current-feeling")
def get_character_current_feeling_route(character_name: str) -> Dict[str, Any]:
    """Return the current feeling."""
    feeling = get_character_current_feeling(character_name)
    return {"character": character_name, "current_feeling": feeling or ""}


@router.post("/{character_name}/current-feeling")
async def update_character_current_feeling(character_name: str, request: Request) -> Dict[str, Any]:
    """Update the current feeling."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_update_character_current_feeling_sync,
                                   character_name, data)


def _update_character_current_feeling_sync(character_name: str,
                                           data: Any) -> Dict[str, Any]:
    """The blocking body of ``update_character_current_feeling`` — runs in the
    threadpool."""
    try:
        user_id = data.get("user_id", "")
        feeling = data.get("current_feeling", "")

        save_character_current_feeling(character_name, feeling)

        return {"status": "success", "character": character_name, "current_feeling": feeling}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/status-effects")
def get_status_effects_route(
                             character_name: str) -> Dict[str, Any]:
    """Return base status values and the active boosts used by the UI."""
    try:
        from app.core.stat_boosts import effective_stats
        from app.models.character import get_character_profile
        out = character_ops.build_status_effects(character_name)
        profile = get_character_profile(character_name)
        profile = dict(profile, status_effects=out.get("status_effects", {}))
        out["stat_boosts"] = {key: stat for key, stat in effective_stats(profile).items()
                              if stat["boost"] != 0}
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Template changes ===

@router.post("/{character_name}/switch-template")
async def switch_template_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Preview or apply a template change.

    Mode diff returns added and removed fields without changes. Mode apply
    sets new defaults and removes obsolete fields."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_switch_template_route_sync,
                                   character_name, data)


def _switch_template_route_sync(character_name: str,
                                data: Any) -> Dict[str, Any]:
    """The blocking body of ``switch_template_route`` — runs in the
    threadpool."""
    try:
        return character_ops.apply_template_switch(character_name, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Erlaubte Orte ===

@router.get("/{character_name}/home-location")
def get_home_location_route(
                            character_name: str) -> Dict[str, Any]:
    """Returns the home location and home room of a character.

    Deliberately NOT gated by ``activity_home_enabled``: a value that is
    already stored must stay readable, whatever the template says today."""
    if not character_name:
        return {"home_location": "", "home_room": ""}
    from app.models.character import get_character_config
    config = get_character_config(character_name)
    return {
        "home_location": config.get("home_location", ""),
        "home_room": config.get("home_room", ""),
    }


@router.post("/{character_name}/home-location")
async def save_home_location_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Stores the home location and home room of a character."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_save_home_location_route_sync,
                                   character_name, data)


def _save_home_location_route_sync(character_name: str,
                                   data: Any) -> Dict[str, Any]:
    """The blocking body of ``save_home_location_route`` — runs in the
    threadpool.

    A template can switch the whole activity/home subject off
    (``activity_home_enabled: false`` — a temporary NPC lives in the slot it
    was spawned for, it has no home to walk back to). The UI hides the sub-tab
    for it; this is the API-side backstop. Fail-open: only an explicit
    ``false`` refuses."""
    try:
        if not character_name:
            raise HTTPException(status_code=400, detail="character_name is missing")
        from app.models.character_template import is_feature_enabled
        if not is_feature_enabled(character_name, "activity_home_enabled"):
            raise HTTPException(status_code=409, detail=(
                f"'{character_name}' has no activity/home configuration — its "
                "template disables activity_home_enabled"))
        from app.models.character import get_character_config, save_character_config
        config = get_character_config(character_name)
        config["home_location"] = data.get("home_location", "")
        config["home_room"] = data.get("home_room", "")
        save_character_config(character_name, config)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/outfit-lora-options")
def get_outfit_lora_options(character_name: str = "",
                            target: str = "render",
                            backend: str = "",
                            workflow: Optional[str] = None,
                            tpose_workflow: Optional[str] = None) -> Dict[str, Any]:
    """Returns the LoRA list for the outfit-piece editor.

    Args:
        character_name: whose own backend match is position 0 of the chain.
        target: "render" (default) scopes the list to the backend of the
            image routing's "expression" occasion (outfit and variant
            renders); "tpose" to the "tpose" occasion (its position 0 is
            outfit_imagegen.tpose_workflow, else outfit_imagegen.workflow).
        backend: non-empty = skip the routing resolution and scope the list
            to the first ENABLED image backend whose name matches this value
            as an fnmatch glob (case-insensitive like the routing; an exact
            name works); no such backend → empty list. Used by panel fields
            whose LoRAs belong to a backend chosen in the same form.
        workflow / tpose_workflow: given (even empty) = the character's
            UNSAVED glob of that key, used in place of the stored one for
            this resolution — the editor's LoRA list follows the backend
            typed into its draft, not the one saved before it.

    Response:
        loras: [{name, missing}] from the LoRA library, scoped to the backend
        the render would resolve right now (no 'None' entry); empty when the
        chain resolves to nothing.
    """
    from app.imagegen.service import get_image_service
    imagegen = get_image_service()
    if not imagegen.enabled:
        return {"loras": []}

    pattern = (backend or "").strip().lower()
    if pattern:
        import fnmatch
        from app.core.config import get_lora_options
        eff = next((b for b in imagegen.backends
                    if getattr(b, "instance_enabled", False)
                    and getattr(b, "MEDIA_TYPE", "image") == "image"
                    and fnmatch.fnmatch(str(b.name).lower(), pattern)), None)
        if eff is None:
            return {"loras": []}
        try:
            return {"loras": get_lora_options(
                eff.name, lora_filter=getattr(eff, "lora_filter", "") or "")}
        except Exception:
            return {"loras": []}

    try:
        from app.core.config import get_lora_options
        from app.imagegen.routing import explain_occasion
        from app.imagegen.service import render_has_reference_image
        # The same backend the render would take: the occasion's chain with
        # the character's own match as position 0. Outfit/variant renders
        # pin the profile image as identity reference, so the same img2img
        # preference inside a glob applies as in the render
        # (render_has_reference_image — one rule for both).
        _occ = "tpose" if target == "tpose" else "expression"
        _drafts = {key: value for key, value in (("workflow", workflow),
                                                  ("tpose_workflow", tpose_workflow))
                   if value is not None}
        _name = str(explain_occasion(
            _occ, character=character_name or "",
            has_ref=render_has_reference_image(character_name),
            spec_overrides=_drafts).get("resolved") or "")
        eff = next((b for b in imagegen.backends if b.name == _name), None)
        lib_options = get_lora_options(
            eff.name if eff else "",
            lora_filter=(getattr(eff, "lora_filter", "") or "") if eff else "")
    except Exception:
        lib_options = []

    return {"loras": lib_options}


@router.get("/outfit-rules")
def get_outfit_rules_route() -> Dict[str, Any]:
    """Deprecated: decency replaced outfit_types rules. Return an empty result for old UI requests."""
    return {"outfit_types": {}}


@router.post("/{character_name}/clear-expression-cache")
def clear_expression_cache_route(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Deletes every cached expression image of this character. They are
    re-rendered on demand; the key space is bounded by the pose/expression
    catalogs. The world-wide variant lives in ``poses.py``."""
    from app.core.expression_regen import clear_expression_cache
    count = clear_expression_cache(character_name)
    return {"status": "ok", "character": character_name, "deleted": count}


@router.delete("/{character_name}")
def delete_character_route(character_name: str) -> Dict[str, Any]:
    """Delete a character from the database and storage directory."""
    if not character_name:
        raise HTTPException(status_code=400, detail="character_name fehlt")
    from app.core.linked_characters import delete_refusal
    refusal = delete_refusal(character_name)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    success = delete_character(character_name)
    if not success:
        raise HTTPException(status_code=404,
                            detail=f"Character '{character_name}' not found or protected")
    return {"status": "success", "deleted": character_name}


# ---------------------------------------------------------------------------
# Linked characters (app.core.linked_characters) — world authoring, admin-only
# ---------------------------------------------------------------------------

def _link_result(result: Dict[str, Any], name: str) -> Dict[str, Any]:
    from app.core.linked_characters import describe
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error") or "Refused.")
    return describe(name)


@router.get("/{character_name}/link")
def get_character_link(character_name: str,
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The link state: ``{leader, bodies, shared_soul_sections, status,
    shareable, candidates}``."""
    from app.core.linked_characters import describe
    from app.models.character import character_exists
    if not character_exists(character_name):
        raise HTTPException(status_code=404, detail=f"Character '{character_name}' not found")
    return describe(character_name)


@router.put("/{character_name}/link")
async def put_character_link(character_name: str, request: Request,
                             _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Link to a leader / change the shared soul sections:
    ``{leader, shared_soul_sections}``. Linking makes the character dormant."""
    from app.core.linked_characters import DEFAULT_SHARED_SOUL, link
    data = await request.json()
    shared = data.get("shared_soul_sections")
    return _link_result(link(character_name, str(data.get("leader") or ""),
                             shared=list(DEFAULT_SHARED_SOUL) if shared is None else shared),
                        character_name)


@router.delete("/{character_name}/link")
def delete_character_link(character_name: str,
                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Unlink a dormant body; it stands at its leader's place afterwards."""
    from app.core.linked_characters import unlink
    return _link_result(unlink(character_name), character_name)


@router.post("/{character_name}/linked")
async def create_linked_character(character_name: str, request: Request,
                                  _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Create a new linked character ``{name}`` for this leader (dormant)."""
    from app.core.linked_characters import create_linked
    data = await request.json()
    result = create_linked(character_name, str(data.get("name") or ""))
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error") or "Refused.")
    return {"status": "success", "character": result["name"]}


@router.post("/{character_name}/generate-profile-image")
async def generate_profile_image_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Generates a new profile image via the core image service."""
    return await character_ops.generate_profile_image_core(character_name, request)


@router.get("/{character_name}/outfit-lock")
def get_outfit_lock_route(character_name: str) -> Dict[str, Any]:
    """Whether this character's outfit is locked against automatic changes.

    Response: ``{"character": <name>, "locked": <bool>}``.
    """
    from app.models.character import is_outfit_locked
    return {"character": character_name, "locked": is_outfit_locked(character_name)}


@router.post("/{character_name}/outfit-lock")
def set_outfit_lock_route(character_name: str,
                          body: OutfitLockBody) -> Dict[str, Any]:
    """Locks/unlocks the outfit — a plain ``def``, so FastAPI runs it in the
    threadpool and the body needs no hand-rolled JSON parsing.

    The lock is honoured by the two paths that would otherwise re-dress the
    character on their own: ``outfit_compliance.apply_outfit_compliance``
    skips with status ``locked``, and ``outfit_creation_skill`` refuses.
    The write itself takes the per-character profile lock inside
    ``set_outfit_locked``.

    Body: ``{"locked": <bool>}``. Response: the stored state, read back.
    """
    from app.models.character import set_outfit_locked, is_outfit_locked
    set_outfit_locked(character_name, bool(body.locked))
    return {"character": character_name, "locked": is_outfit_locked(character_name)}


@router.get("/{character_name}/decency-exempt")
def get_decency_exempt_route(character_name: str) -> Dict[str, Any]:
    """Return decency_exempt, which overrides decency to nude_ok."""
    from app.models.character import get_state_flags
    return {"character": character_name,
            "exempt": bool(get_state_flags(character_name).get("decency_exempt"))}


@router.post("/{character_name}/decency-exempt")
async def set_decency_exempt_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Set or clear decency_exempt. When set, decency rules allow nude_ok
    regardless of presence; compliance reacts immediately."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_set_decency_exempt_route_sync,
                                   character_name, data)


def _set_decency_exempt_route_sync(character_name: str,
                                   data: Any) -> Dict[str, Any]:
    """The blocking body of ``set_decency_exempt_route`` — runs in the
    threadpool."""
    from app.models.character import set_decency_exempt, get_state_flags
    exempt = bool(data.get("exempt"))
    set_decency_exempt(character_name, exempt)
    try:
        from app.core.outfit_compliance import apply_outfit_compliance
        apply_outfit_compliance(character_name)
    except Exception:
        pass
    return {"character": character_name,
            "exempt": bool(get_state_flags(character_name).get("decency_exempt"))}


# --- Outfit-bound expression images ---

def _expression_request(character_name, mood="", pieces="", items="", override=False,
                        default_expression=False, wait=True):
    """``default_expression``: the set's default expression in the CURRENT
    outfit — no mood lookup, no outfit override (an override with empty
    pieces renders the character undressed).

    ``wait=False`` for the polled GETs (status, portrait image): the mood is
    resolved without waiting on embeddings — cold alias embeddings answer
    the set's default member until the background resolution is done."""
    from app.core.expression_regen import expression_snapshot
    from app.core.pose_catalog_edit import CatalogEditError
    explicit = bool(override or pieces or items)
    if not isinstance(pieces, (str, dict)) or not isinstance(items, (str, list, tuple)):
        raise HTTPException(400, "Invalid expression outfit override")
    eqp = dict(pieces) if isinstance(pieces, dict) else {
        pair.split(":", 1)[0].strip(): pair.split(":", 1)[1].strip()
        for pair in pieces.split(",") if ":" in pair}
    eqi = list(items) if isinstance(items, (list, tuple)) else [i.strip() for i in items.split(",") if i.strip()]
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in eqp.items()) or any(not isinstance(i, str) for i in eqi):
        raise HTTPException(400, "Expression outfit ids must be strings")
    if not explicit and not mood and not default_expression:
        mood = get_character_current_feeling(character_name) or ""
    try:
        return expression_snapshot(character_name, str(mood), equipped_pieces=eqp if explicit else None,
                                   equipped_items=eqi if explicit else None, wait=wait)
    except CatalogEditError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


def _expression_owner(request, character_name):
    from app.core.auth_dependency import get_current_user, filter_characters
    user = get_current_user(request)
    if user.get("role") != "admin" and character_name not in filter_characters(request, [character_name]):
        raise HTTPException(403, "Character access required")
    return user


@router.get("/{character_name}/expression-options")
def expression_options(character_name: str, request: Request):
    from app.core.expression_sets import catalog_snapshot, set_for_character, ExpressionSetError
    _expression_owner(request, character_name)
    profile = get_character_profile(character_name)
    if not profile:
        raise HTTPException(404, "Character not found")
    cat = catalog_snapshot()
    automatic = set_for_character(character_name, profile={**profile, "expression_set": ""}, catalog=cat).id
    selected = str(profile.get("expression_set") or "")
    error = ""
    try:
        effective = set_for_character(character_name, profile=profile, catalog=cat)
    except ExpressionSetError as exc:
        error = str(exc)
        effective = cat.sets[automatic]
    backend, on_backend = _expression_lora_fit(character_name, cat.sets.values())
    # The moods the character's own set renders: one per member. The stored
    # mood stays readable free text — the member's first synonym (the import
    # makes the label one), else its label; the mood resolver maps it back.
    moods = []
    for key in effective.members:
        entry = cat.entries.get(key) or {}
        label = str(entry.get("label") or key)
        synonyms = [s for s in (entry.get("synonyms") or ()) if s]
        moods.append({"key": key, "label": label, "value": synonyms[0] if synonyms else label})
    return {"options": [{"value": sid, "label": spec.label, "lora": spec.lora,
                         "lora_strength": spec.lora_strength,
                         "lora_on_backend": on_backend.get(sid)}
                        for sid, spec in cat.sets.items()],
            "lora_backend": backend,
            "automatic_set": automatic, "selected_set": selected, "error": error,
            "effective_set": effective.id, "moods": moods}


def _expression_lora_fit(character_name, sets):
    """The backend this character's expression images route to, and per set
    whether the LoRA library associates the set's LoRA with it (None = the
    set has no LoRA or no backend resolves). A preflight that never moves
    the routing rotation."""
    from app.core.expression_regen import set_loras
    try:
        from app.imagegen.routing import resolve_image_route
        backend = resolve_image_route("expression", character=character_name, has_ref=True,
                                      advance_rotation=False).backend
    except Exception as exc:  # no route, media switched off, empty pool
        logger.debug("Expression route preflight for %s failed: %s", character_name, exc)
        return "", {}
    from app.core.lora_library import unassociated_loras
    fit = {}
    for spec in sets:
        loras = set_loras(spec)
        fit[spec.id] = (not unassociated_loras(backend, loras)) if loras else None
    return getattr(backend, "name", "") or "", fit


@router.post("/{character_name}/expression-generation")
async def expression_generation(character_name: str, request: Request):
    import asyncio
    from dataclasses import asdict
    from fastapi.responses import JSONResponse
    from app.core.expression_regen import start_expression_attempt
    _expression_owner(request, character_name)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Expression generation expects an object")
    snap = await asyncio.to_thread(_expression_request, character_name, body.get("mood", ""),
                                   body.get("pieces", ""), body.get("items", ""), bool(body.get("override")),
                                   bool(body.get("default_expression")))
    attempt = await asyncio.to_thread(start_expression_attempt, snap, force=bool(body.get("force")),
                                     ignore_feature_gate=True)
    status = 202 if attempt.state in ("pending", "running") else 200 if attempt.state == "ready" else 409
    return JSONResponse({**asdict(attempt), **({"detail": attempt.error} if attempt.error else {})},
                        status_code=status, headers={"Cache-Control": "no-cache"})


@router.get("/{character_name}/expression-status")
def expression_status_route(character_name: str, request: Request, attempt_id: str = "",
                            mood: str = "", pieces: str = "", items: str = "", override: int = 0):
    from dataclasses import asdict
    from app.core.expression_regen import get_expression_attempt, expression_status
    _expression_owner(request, character_name)
    if attempt_id:
        if any(key in request.query_params for key in ("mood", "pieces", "items", "override")):
            raise HTTPException(400, "Attempt status cannot include a new expression selection")
        attempt = get_expression_attempt(character_name, attempt_id)
        if attempt is None:
            raise HTTPException(404, "Unknown expression attempt; the server may have restarted")
        return asdict(attempt)
    return expression_status(_expression_request(character_name, mood, pieces, items, bool(override),
                                                 wait=False))


@router.get("/{character_name}/expression-cleanup")
def expression_cleanup_preview(character_name: str, _: Dict[str, Any] = Depends(require_admin)):
    from app.core.expression_cleanup import preview_cleanup, CleanupError
    try:
        return preview_cleanup(character_name)
    except CleanupError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/{character_name}/expression-cleanup")
async def expression_cleanup_apply(character_name: str, request: Request,
                                    _: Dict[str, Any] = Depends(require_admin)):
    import asyncio
    from app.core.expression_cleanup import apply_cleanup, CleanupError
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("revision"), str):
        raise HTTPException(400, "Cleanup requires a preview revision")
    try:
        return await asyncio.to_thread(apply_cleanup, character_name, str(body.get("revision") or ""))
    except CleanupError as exc:
        raise HTTPException(exc.status, {"message": str(exc), "completed": exc.completed}) from exc

@router.get("/{character_name}/outfit-expression")
def get_outfit_expression(character_name: str, request: Request, mood: str = "",
                          pieces: str = "", items: str = "", override: int = 0,
                          fallback: str = "", v: str = ""):
    """Serve a set-local outfit image; only an ordinary miss may warm the cache."""
    from app.core import expression_regen as er
    from app.core.http_files import snapshot_response
    from app.core.keyed_lock import keyed_lock
    snap = _expression_request(character_name, mood, pieces, items, bool(override), wait=False)
    exact = er.get_cached_expression(snap)
    if exact is None and not (override or pieces or items):
        er.trigger_expression_generation(snap, ignore_cooldown=True)
    with keyed_lock("pose_catalog", "expression"):
        response = snapshot_response(None, request, media_type=lambda p: mimetypes.guess_type(str(p))[0] or "image/png",
            lock=er.publication_lock(character_name), resolve=lambda: er.find_compatible_expression(snap)
                if fallback == "default" else er.get_cached_expression(snap))
    if response.status_code != 404:
        return response
    from fastapi.responses import JSONResponse
    status = er.expression_status(snap)
    if status["state"] in ("pending", "running"):
        return JSONResponse(status, status_code=202, headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "No compatible expression image available")


@router.get("/{character_name}/expressions")
def list_expressions_route(character_name: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Lists all cached expression variants of a character with their
    parameters (mood, activity, equipped, model, seed, backend, workflow, …).
    """
    from app.core.expression_regen import list_expressions
    items = list_expressions(character_name)
    return {"character": character_name, "expressions": items}


@router.get("/{character_name}/expressions/{filename}")
def serve_expression_route(character_name: str, filename: str, _: Dict[str, Any] = Depends(require_admin)):
    """Serves a single expression variant image by filename."""
    from app.core.expression_regen import _get_expressions_dir
    expr_dir = _get_expressions_dir(character_name)
    if not filename or filename != os.path.basename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = expr_dir / filename
    try:
        if path.resolve().parent != expr_dir.resolve() or not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
    except OSError:
        raise HTTPException(status_code=404, detail="Not found")
    media_type = mimetypes.guess_type(str(path))[0] or "image/png"
    return FileResponse(path=str(path), media_type=media_type,
                        headers={"Cache-Control": "no-cache"})


@router.post("/{character_name}/expressions/{filename}/regenerate", status_code=202)
def regenerate_expression_route(character_name: str, filename: str,
                                _: Dict[str, Any] = Depends(require_admin)):
    """Re-render exactly this stored expression image from the inputs its sidecar stored — set, member, worn
    pieces/items, mood; never the current mood or outfit (Task UI2, rule R2; ``expression_regen.regenerate_stored``,
    the same producer as every expression render, forced). 202 with the attempt (poll ``…/expression-status
    ?attempt_id=``), 200 when it already ended; 404 for a missing image; 409 with the reason when the stored inputs
    are missing or no longer give this file (the tab disables the button with the same reason)."""
    from dataclasses import asdict
    from fastapi.responses import JSONResponse
    from app.core.expression_regen import regenerate_stored
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    try:
        attempt = regenerate_stored(character_name, filename)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    status = 202 if attempt.state in ("pending", "running") else 200 if attempt.state == "ready" else 409
    return JSONResponse({**asdict(attempt), **({"detail": attempt.error} if attempt.error else {})},
                        status_code=status, headers={"Cache-Control": "no-cache"})


@router.delete("/{character_name}/expressions/{filename}")
def delete_expression_route(character_name: str, filename: str, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Deletes a single expression variant image + its JSON sidecar."""
    from app.core.expression_regen import delete_expression
    ok = delete_expression(character_name, filename)
    if not ok:
        raise HTTPException(status_code=404, detail="Expression not found")
    return {"status": "success", "deleted": filename}


@router.get("/{character_name}/outfit-imagegen")
def get_outfit_imagegen_route(character_name: str) -> Dict[str, Any]:
    """Returns the per-character image-generation override record (backend
    globs + LoRA lists; empty values = the routing chains) plus what the
    editor shows beside them: the mesh occasion this character's rig selects
    with its world chain and backends, the hair_mesh chain and backends, and
    per glob the occasion chains that run when it stays empty."""
    from app.models.character import get_character_profile
    prof = get_character_profile(character_name) or {}
    override = prof.get("outfit_imagegen") or {}
    if not isinstance(override, dict):
        override = {}
    return {
        **{field: override.get(field, "") or "" for field in character_ops.IMAGEGEN_MATCH_FIELDS},
        **{field: override.get(field, []) or [] for field in character_ops.IMAGEGEN_LORA_FIELDS},
        **_mesh_match_context(character_name),
        **_hair_match_context(),
        "match_chains": _image_match_chains(),
    }


def _mesh_match_context(character_name: str) -> Dict[str, Any]:
    """What the 3D tab needs beside the mesh match: the mesh occasion this
    character's rig selects, its world chain (shown as the fallback) and every
    enabled img2mesh backend name (match preview; offline ones included, the
    glob still names them)."""
    from app.core import config
    from app.core.model3d import required_rig
    from app.imagegen.occasions import mesh_occasion_for_rig
    from app.imagegen.service import get_image_service
    try:
        occasion = mesh_occasion_for_rig(required_rig(character_name))
    except Exception:
        occasion = "mesh_humanoid"
    rules = config.get("image_generation.routing", {}) or {}
    chain = rules.get(occasion) if isinstance(rules, dict) else None
    names = [b.name for b in get_image_service().backends
             if b.instance_enabled and getattr(b, "MEDIA_TYPE", "image") == "mesh"
             and (getattr(b, "category", "") or "") == "img2mesh"]
    return {"mesh_occasion": occasion,
            "mesh_world_chain": [str(x) for x in chain] if isinstance(chain, list) else [],
            "mesh_backends": names}


def _hair_match_context() -> Dict[str, Any]:
    """The hair matches beside the mesh match: the hair_mesh (HairDeck) and hair_strands (HAAR) world chains (shown
    as the fallback) and every enabled img2hair / txt2hair backend name (match preview)."""
    from app.core import config
    from app.imagegen.backends.openai_mesh import HAIR_CATEGORY, STRANDS_CATEGORY
    from app.imagegen.service import get_image_service
    rules = config.get("image_generation.routing", {}) or {}

    def chain(occasion: str) -> List[str]:
        value = rules.get(occasion) if isinstance(rules, dict) else None
        return [str(x) for x in value] if isinstance(value, list) else []

    def names(category: str) -> List[str]:
        return [b.name for b in get_image_service().backends
                if b.instance_enabled and getattr(b, "MEDIA_TYPE", "image") == "mesh"
                and (getattr(b, "category", "") or "") == category]

    return {"hair_world_chain": chain("hair_mesh"), "hair_backends": names(HAIR_CATEGORY),
            "strands_world_chain": chain("hair_strands"), "strands_backends": names(STRANDS_CATEGORY)}


def _image_match_chains() -> Dict[str, List[Dict[str, Any]]]:
    """What runs behind each per-character match when it stays empty:
    ``{match field: [{occasion, label, chain}]}`` — every occasion that takes
    the field as position 0, with its world chain (positions 1..n, the
    character's own glob left out). An empty ``chain`` means the cheapest
    backend of the right kind. The character mesh and HairDeck matches show
    ``_mesh_match_context`` / ``_hair_match_context`` instead (the mesh one
    depends on the character's rig)."""
    from app.imagegen.occasions import OCCASIONS
    from app.imagegen.routing import chain_for
    out: Dict[str, List[Dict[str, Any]]] = {}
    for oid, occ in OCCASIONS.items():
        field = occ.get("char_spec_field") or ""
        if not field:
            continue
        try:
            chain = [spec for spec, _source, _pos in chain_for(oid)]
        except Exception:
            continue
        out.setdefault(field, []).append(
            {"occasion": oid, "label": occ.get("label") or oid, "chain": chain})
    return out


@router.put("/{character_name}/outfit-imagegen")
async def set_outfit_imagegen_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Saves the match/model/LoRA override for the outfit image service.
    All fields empty deletes the override completely."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_set_outfit_imagegen_route_sync,
                                   character_name, body)


def _set_outfit_imagegen_route_sync(character_name: str,
                                    body: Any) -> Dict[str, Any]:
    """The blocking body of ``set_outfit_imagegen_route`` — runs in the
    threadpool."""
    return character_ops.apply_outfit_imagegen(character_name, body)


@router.get("/{character_name}/profile")
def get_profile_route(character_name: str) -> Dict[str, Any]:
    """Return the complete character profile."""
    return character_ops.build_profile_payload(character_name)


@router.post("/{character_name}/resolve-tokens")
async def resolve_tokens_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Live preview of the token replacements ({gender} -> "female", ...).

    Takes a draft text (e.g. the appearance prompt being typed) plus the
    target_key (e.g. "character_appearance") and resolves the tokens against
    the current profile + template — no frontend re-implementation, one
    backend source. Only tokens a template field declares via a replacement
    block targeting target_key resolve; anything else stays literal.
    """
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_resolve_tokens_route_sync, character_name,
                                   data)


def _resolve_tokens_route_sync(character_name: str,
                               data: Any) -> Dict[str, Any]:
    """The blocking body of ``resolve_tokens_route`` — runs in the
    threadpool."""
    from app.models.character_template import resolve_profile_tokens, get_template
    text = str(data.get("text", "") or "")
    target_key = str(data.get("target_key", "") or "character_appearance")
    profile = get_character_profile(character_name)
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    resolved = resolve_profile_tokens(text, profile, template=tmpl, target_key=target_key)
    return {"character": character_name, "resolved": resolved}


@router.get("/{character_name}/belongings")
def get_belongings_route(character_name: str) -> Dict[str, Any]:
    """Character inventory and paper-doll outfit, matching /play/belongings
    for the Game-Admin wardrobe tab.
    """
    from app.routes.play import build_belongings
    return build_belongings(character_name)


@router.post("/{character_name}/profile")
async def update_profile_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Update character profile fields in bulk."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_update_profile_route_sync,
                                   character_name, data)


def _update_profile_route_sync(character_name: str,
                               data: Any) -> Dict[str, Any]:
    """The blocking body of ``update_profile_route`` — runs in the
    threadpool."""
    try:
        return character_ops.apply_profile_update(character_name, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Config (character_config.json) ---

@router.get("/{character_name}/config")
def get_config_route(character_name: str) -> Dict[str, Any]:
    """Return character configuration, including TTS and extraction."""
    config = get_character_config(character_name)
    return {"character": character_name, "config": config}


@router.post("/{character_name}/config")
async def update_config_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Update character configuration fields in bulk."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_update_config_route_sync,
                                   character_name, data)


def _update_config_route_sync(character_name: str,
                              data: Any) -> Dict[str, Any]:
    """The blocking body of ``update_config_route`` — runs in the
    threadpool."""
    try:
        return character_ops.apply_config_update(character_name, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Images ---

@router.post("/{character_name}/images")
async def upload_character_image(character_name: str, request: Request) -> Dict[str, Any]:
    """Upload an image."""
    try:
        guard_content_length(request, what="Gallery file")
        form = await request.form()
        file = form.get("file")

        if not file:
            raise HTTPException(status_code=400, detail="Keine Datei hochgeladen")

        allowed_extensions = {"png", "jpg", "jpeg", "gif", "webp", "mp4"}
        filename = file.filename.lower()
        if not any(filename.endswith(ext) for ext in allowed_extensions):
            raise HTTPException(status_code=400, detail="Format not supported")

        images_dir = get_character_images_dir(character_name)

        timestamp = int(time.time())
        file_ext = Path(filename).suffix
        image_filename = f"{character_name}_{timestamp}{file_ext}"
        image_path = images_dir / image_filename

        # Size and type from the BYTES, not from the name (SEC-7): the
        # gallery serves what lands here back to every client.
        contents = await read_upload_capped(file, what="Gallery file")
        if filename.endswith(".mp4"):
            ensure_mp4(contents, what="Gallery clip")
        else:
            ensure_image(contents, filename=filename, what="Gallery image")
        image_path.write_bytes(contents)

        add_character_image(character_name, image_filename)
        if filename.endswith(".mp4"):
            from app.core.video_webm import schedule_webm
            schedule_webm(image_path)

        return {
            "status": "success",
            "filename": image_filename,
            "url": f"/characters/{character_name}/images/{image_filename}"
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/images")
def get_character_images_list(character_name: str) -> Dict[str, Any]:
    """Return all character images."""
    try:
        images = get_character_images(character_name)
        profile_image = get_character_profile_image(character_name)
        comments = get_character_image_comments(character_name)
        prompts = get_character_image_prompts(character_name)
        metadata = get_character_image_metadata(character_name)

        # Find images with an accompanying video ({stem}.mp4).
        images_dir = get_character_images_dir(character_name)
        image_videos = {}
        for img_name in images:
            video_path = images_dir / (Path(img_name).stem + ".mp4")
            if video_path.exists():
                image_videos[img_name] = video_path.name

        return {
            "character": character_name,
            "images": images,
            "profile_image": profile_image,
            "urls": [f"/characters/{character_name}/images/{img}" for img in images],
            "image_comments": comments,
            "image_prompts": prompts,
            "image_metadata": metadata,
            "image_videos": image_videos,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/images/profile")
def get_character_profile_image_file(character_name: str, request: Request,
                                     transparent: bool = False):
    """Serves the character's profile image directly (shortcut for notifications/avatars)."""
    from fastapi.responses import Response
    try:
        profile_img = get_character_profile_image(character_name)
        if not profile_img:
            return Response(status_code=404)
        image_path = (transparent_portrait_path(character_name, profile_img)
                      if transparent else character_image_path(character_name, profile_img))
        if transparent:
            return etag_file_response(image_path, request, "image/png")
        media_type, _ = mimetypes.guess_type(str(image_path))
        return FileResponse(
            image_path,
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=300"}
        )
    except FileNotFoundError:
        return Response(status_code=404)
    except PortraitProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{character_name}/images/{image_filename}")
def get_character_image(character_name: str, image_filename: str, request: Request,
                        transparent: bool = False):
    """Serve an original gallery image or its display-only alpha portrait."""
    from fastapi.responses import Response
    try:
        image_path = (transparent_portrait_path(character_name, image_filename)
                      if transparent else character_image_path(character_name, image_filename))
        if transparent:
            return etag_file_response(image_path, request, "image/png")

        media_type, _ = mimetypes.guess_type(str(image_path))
        return FileResponse(
            image_path,
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "no-cache"}
        )
    except FileNotFoundError:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=300"})
    except PortraitProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{character_name}/images/{video_filename}/webm")
def get_character_video_webm(character_name: str, video_filename: str, request: Request):
    """WebM (VP9) companion of a gallery MP4, for engines without H.264 (CEF).

    Same classification as the MP4 itself (``images`` is a public segment) and
    the same file resolution. Created on first request when missing; a
    concurrent request waits for the single running encode. 404 = no such
    video, 503 + Retry-After = encode not (yet) available -- the player falls
    back to its MP4 source either way."""
    from fastapi.responses import Response
    from app.core.video_webm import WEBM_MEDIA_TYPE, ensure_webm
    try:
        video = character_image_path(character_name, video_filename)
    except FileNotFoundError:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=300"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if video.suffix.lower() != ".mp4":
        return Response(status_code=404)
    webm = ensure_webm(video, wait=30.0)
    if webm is None:
        return Response(status_code=503, headers={"Retry-After": "10"})
    return etag_file_response(webm, request, WEBM_MEDIA_TYPE)


# --- 3D model asset (AV3D-5 stage 1) ---
#
# The character's model for external 3D map clients. Two shapes:
#   humanoid -> ONE .glb (52-bone Mixamo rig, textures embedded)
#   generic  -> .fbx + its basecolor .png (an FBX embeds no texture)
# Files are 5-30 MB, so the GET routes serve with an ETag + conditional
# requests instead of re-sending the bytes. A character WITHOUT a model is a
# normal state (404) — the client falls back to the portrait marker.
#
# An uploaded model is the manual OVERRIDE; without one the routes serve the
# generated mesh of the currently worn outfit (app/core/model3d.py), so a
# client has exactly one place to ask.
# The size ceiling for an upload is upload_limits.MODEL_UPLOAD_MAX_BYTES.


def _resolve_character_model(character_name: str):
    return _resolve_character_model_snapshot(character_name)


def _resolve_character_model_snapshot(character_name: str):
    """(path, meta, texture_path) of the character's current-outfit model —
    uploaded or generated, whichever is stored. (None, None, None) when there is
    none: a normal state, not an error. (The pre-per-outfit global upload store
    was migrated into the per-outfit store at boot — no serving fallback.)

    Only the META route needs this: get_model3d_info re-reads the profile and
    enumerates the mesh backends. The byte routes below resolve the file path
    directly."""
    from app.core.model3d import find_texture, get_model3d_info
    status = get_model3d_info(character_name, _url_base=f"/characters/{quote(character_name)}/model")
    info = status.get("model") or {}
    if info:
        from app.core.model3d import get_model3d_dir
        path = get_model3d_dir(character_name) / info["filename"]
        meta = {"format": info["format"],
                "rig": info.get("rig", "mixamo"),
                "filename": path.name,
                "size": info["size"],
                "has_texture": bool(info.get("texture_url")),
                "created_at": info.get("created_at", ""),
                "backend": info.get("backend", ""),
                "mesh_backend": info.get("mesh_backend", ""),
                "rig_backend": info.get("rig_backend", ""),
                "mesh_route_meta": info.get("mesh_route_meta", {}),
                "rig_route_meta": info.get("rig_route_meta", {}),
                "has_unrigged_source": info.get("has_unrigged_source", False),
                "source": info.get("source", "generated"),
                "extension_rig": info.get("extension_rig"),
                "collision": info.get("collision"),
                "hair_strands": info.get("hair_strands"),
                "foot_pose": None,
                "motion": status["motion"],
                "model_rev": info["model_rev"], "tiers": info["tiers"],
                **{key: info[key] for key in ("url", "low_url", "texture_url") if key in info}}
        # The delivered file may be the garment assembly (bare model +
        # grafted garments): its size, garments and foot pose (footwear
        # spec § 6.1; None while the bare file is served) come from ITS sidecar.
        from app.core import garment_assembly
        from app.core.keyed_lock import keyed_lock
        with keyed_lock("model3d_publication", str(path.parent)):
            served = garment_assembly.served(character_name, path, "full")
            if served != path:
                try:
                    meta["size"] = served.stat().st_size
                    side = garment_assembly.read_sidecar(served)
                    meta["garments"] = side.get("garments") or {}
                    meta["foot_pose"] = side.get("foot_pose") if isinstance(side.get("foot_pose"), dict) else None
                except OSError:
                    pass
        # FBX case only — a GLB embeds its textures; a stray image next to a
        # GLB is an auxiliary material map, never the basecolor.
        tex = (find_texture(character_name, path.stem)
               if path.suffix.lower() == ".fbx" else None)
        return path, meta, tex
    return None, None, None


def _model_asset_response(character_name: str, request: Request, *, tier: str = "",
                          texture: bool = False, download: bool = False,
                          signature: str = ""):
    """Select and open under publication lock; stream the same descriptor.

    ``signature`` serves the stored full model of exactly that signature
    (no serving chain, no tier) — the caller has vetted it."""
    from app.core.http_files import snapshot_response
    from app.core.keyed_lock import keyed_lock
    from app.core.model3d import get_model3d_dir, find_model3d, find_model3d_serving_tier, find_texture
    publication = keyed_lock("model3d_publication", str(get_model3d_dir(character_name)))
    def serving():
        if signature:
            return find_model3d(character_name, signature)
        path, _match, resolved = find_model3d_serving_tier(character_name, tier)
        if path is None or texture or download:
            # A download is the stored (bare) model: re-uploaded, it must
            # never carry grafted garments into the store.
            return path
        from app.core import garment_assembly
        return garment_assembly.served(character_name, path, resolved)
    def pick():
        path = serving()
        if texture:
            return find_texture(character_name, path.stem) if path else None
        return path
    chosen: dict = {}
    def pick_and_remember():
        p = pick()
        chosen["path"] = p
        if p is not None:
            src = serving()
            chosen["filename"] = (src.name if (src is not None and not texture) else p.name)
        return p
    def media_for(p: Path) -> str:
        suf = p.suffix.lower()
        if suf == ".glb":
            return "model/gltf-binary"
        if suf == ".fbx":
            return "application/octet-stream"
        if suf in (".jpg", ".jpeg"):
            return "image/jpeg"
        return "image/png"
    return snapshot_response(None, request, media_type=media_for,
                             version=request.query_params.get("v"),
                             disposition="attachment" if download else "inline",
                             filename=lambda: chosen.get("filename"),
                             lock=publication, delivery=not texture and not download,
                             resolve=pick_and_remember)



@router.get("/{character_name}/model/meta")
def get_character_model_meta(character_name: str) -> Dict[str, Any]:
    """Meta of the character's 3D model — the uploaded one, else the generated
    mesh of the current outfit. 404 = the character simply has no model (a
    normal state; clients fall back to the portrait marker).

    Carries what a 3D client needs: ``format`` (glb|fbx), ``rig`` (mixamo =
    the shared animation clips apply, generic = they do not), ``url`` and — in
    the FBX case only — ``texture_url``.
    """
    _path, meta, tex = _resolve_character_model(character_name)
    if not meta:
        raise HTTPException(status_code=404, detail="No model")
    # Body height in cm — the client scales the figures against each other
    # with it (models come out of the generator at arbitrary scale). None =
    # unset, the client keeps its default.
    from app.core.height import height_cm
    meta["height_cm"] = height_cm(get_character_profile(character_name) or {})
    # Resolution tiers of THIS model, in fallback order. A client may request
    # any of them via ?tier= — an unbuilt one falls back to the full mesh, so
    # this list only says which ones actually save anything.
    return meta


@router.get("/{character_name}/model")
def get_character_model_file(character_name: str, request: Request,
                             tier: str = ""):
    """Serves the 3D model bytes (uploaded one, else the generated mesh).
    404 lets clients degrade to the portrait marker.

    ``tier=low`` asks for the reduced distance mesh; a tier that was never
    built falls back to the full one, so a client may always ask.
    """
    return _model_asset_response(character_name, request, tier=tier)


def _strands_response(request: Request, data: Optional[bytes], sha: str):
    """A strand record (``hair_strands.encode`` bytes) with ``ETag: "<sha256>"``: 304 on a matching
    ``If-None-Match`` (``http_files.etag_matches``), 404 — the normal "no strands" state — without one."""
    from fastapi.responses import Response
    headers = {"Cache-Control": "no-cache"}
    if not sha:
        return Response(status_code=404, headers=headers)
    etag = f'"{sha}"'
    headers["ETag"] = etag
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    if data is None:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return Response(content=data, media_type="application/json", headers=headers)


@router.get("/{character_name}/model/hair-strands")
def get_character_model_hair_strands(character_name: str, request: Request):
    """The strand record of the served model's hair (``hair_strands.served_file``, strand-hair spec § 6.2.3) —
    the record whose sha256 the current full-tier assembly carries. ``ETag`` = ``"<sha256>"``, 304 on a match
    (nothing is read or built), 404 = no strands (Swing off, no grafted hair, no record): the hair stays on its
    skin."""
    from app.core import hair_strands
    found = hair_strands.served_file(character_name)
    if found is None:
        return _strands_response(request, None, "")
    path, sha = found
    if etag_matches(request.headers.get("if-none-match"), f'"{sha}"'):
        return _strands_response(request, None, sha)
    try:
        data = path.read_bytes()
    except OSError:
        return _strands_response(request, None, "")
    import hashlib
    return _strands_response(request, data, hashlib.sha256(data).hexdigest())


@router.get("/{character_name}/model/texture")
def get_character_model_texture_file(character_name: str, request: Request):
    """Serves the basecolor image of a generic/FBX model — PNG or JPEG, the
    gateway prefers JPEG since 2026-07-17 (a GLB embeds its textures and has
    none here). 404 when absent."""
    return _model_asset_response(character_name, request, texture=True)


# --- 3D reference renders (T-pose / default pose, app/core/model_refs.py) ---

@router.get("/{character_name}/model-refs")
def get_character_model_refs(character_name: str) -> Dict[str, Any]:
    """Info about the stored reference renders.

    ``{tpose, pose, status, now}`` — ``status`` carries per kind whether a
    render is ``running`` and whether one is only ``scheduled`` (debounce
    timer armed), with the matching system stamps; ``now`` is the server
    clock, so a client measures a state's age without its own clock skew.
    Every image info carries a ``freshness``
    (``model_overview.annotate_model_refs_info``)."""
    from app.core.model_overview import annotate_model_refs_info
    from app.core.model_refs import get_model_refs_info
    return annotate_model_refs_info(character_name, get_model_refs_info(character_name))


@router.post("/{character_name}/model-refs/generate")
async def generate_character_model_refs(character_name: str,
                                        request: Request) -> Dict[str, Any]:
    """Manually fires the reference render (debounce skipped). Body
    ``{"kinds": ["pose"]}`` narrows to specific images — each tab sends its
    own kind, so wardrobe (pose) and 3D (tpose) generate independently.
    Without kinds the per-image auto toggles decide. ``view`` selects exactly
    main or one body-form T-pose view, leaving other renders untouched.
    With ``view: "face"`` the image dialog may add ``prompt``, ``backend``
    (explicit, no fallback), ``loras`` and ``negative_prompt`` — for this
    run only, nothing is stored. 409 ``figure_build.VIEWS_BUILD_RUNNING``
    for the dressed views of a base-body character while its Build runs
    (ruling F16). One dressed view of a pipeline character answers what
    the click does (Ruling A70, ``base_body.dressed_view_source``):
    ``{status: "generating", jobs: 1, source: "painted"}`` — an edit — or
    ``{status: "copying", jobs: 0, source: "shape" | "plain"}`` — nothing
    is painted on the figure, the view is its shape's view copied again."""
    from app.core.model_refs import (
        REF_KINDS, tpose_views_for_character, current_outfit_state, find_ref_image,
        trigger_now,
    )
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    kinds = body.get("kinds") if isinstance(body, dict) else None
    view = body.get("view") if isinstance(body, dict) else None
    if view is not None:
        if view not in ("main", *tpose_views_for_character(character_name)):
            raise HTTPException(status_code=422, detail="Unknown T-pose view")
        if kinds is not None and kinds != ["tpose"]:
            raise HTTPException(status_code=422, detail="view requires kinds ['tpose']")
        kinds = ["tpose"]
        _require_dressable_view(character_name, view, base_ready=False)
        _require_base_images(character_name, view)
        _require_dressable_view(character_name, view, base_ready=True)
        if view not in ("main", "face"):
            _, _, signature = current_outfit_state(character_name)
            if not find_ref_image(
                    character_name, "tpose", signature):
                raise HTTPException(status_code=409,
                                    detail="Generate the main T-pose render first")
    if kinds is not None:
        if not isinstance(kinds, list):
            raise HTTPException(status_code=422, detail="kinds must be a list")
        kinds = tuple(k for k in kinds if k in REF_KINDS)
        if not kinds:
            raise HTTPException(status_code=422,
                                detail=f"kinds must contain one of {list(REF_KINDS)}")
        if view is None and "tpose" in kinds:
            _require_base_images(character_name, None)
    dialog_keys = ("prompt", "backend", "loras", "negative_prompt")
    face_render = None
    if isinstance(body, dict) and any(k in body for k in dialog_keys):
        if view != "face":
            raise HTTPException(status_code=422,
                                detail="prompt/backend/loras/negative_prompt require view 'face'")
        face_render = await _face_dialog_render(body)
    if view == "face":
        from app.core.model_refs import current_profile_image
        if current_profile_image(character_name) is None:
            raise HTTPException(status_code=409,
                                detail="No profile picture. Set a profile picture, then render the face view")
    else:
        _refuse_views_while_building(character_name, kinds)
    source = _dressed_source(character_name, kinds, view)
    trigger_now(character_name, kinds=kinds, tpose_view=view, face_render=face_render)
    if source is not None and source["jobs"] == 0:
        # Ruling A70: nothing is painted on this figure — the view is copied from its shape's view again, no job.
        return {"status": "copying", "jobs": 0, "source": source["source"]}
    return {"status": "generating", **({"jobs": 1, "source": source["source"]} if source else {})}


def _dressed_source(character_name: str, kinds, view) -> Optional[Dict[str, Any]]:
    """Ruling A70: for ONE dressed view of a base-body-pipeline character (``view`` main / back / a side, kind
    ``tpose``), where its render comes from (``base_body.dressed_view_source``); None for anything else (all the
    views, the face view, the default pose, a character off the pipeline)."""
    from app.core import base_body
    if view in (None, "face") or kinds is None or "tpose" not in kinds:
        return None
    if not base_body.is_base_pipeline(character_name):
        return None
    return base_body.dressed_view_source(character_name)


def _refuse_views_while_building(character_name: str, kinds) -> None:
    """409 ``figure_build.VIEWS_BUILD_RUNNING`` for a manual render of the dressed views (kind ``tpose``; None
    = the auto toggles) of a base-body-pipeline character while its Build runs (ruling F16): never a 200 whose
    render waits unseen behind the Build."""
    from app.core import base_body, figure_build
    from app.core.model_refs import get_auto_kinds
    tpose = "tpose" in kinds if kinds is not None else bool(get_auto_kinds(character_name).get("tpose"))
    if tpose and base_body.is_base_pipeline(character_name) and figure_build.running(character_name):
        raise HTTPException(status_code=409, detail=figure_build.VIEWS_BUILD_RUNNING)


#: 409 of a pose render on the base-body pipeline without the base views.
BASE_FIRST = "Render the base body first (Base body tab) — the outfit views are edits of it"


def _require_dressable_view(character_name: str, view: str, *, base_ready: bool) -> None:
    """409 for a single-view render a base-body-pipeline character cannot
    make: a side view while the world dresses only the front and the back
    (``base_body.dressed_views()`` — ``base_body.SIDE_VIEW_NOT_DRESSED``;
    checked first) or, once the base views are known to exist
    (``base_ready``), a back/side view before a dressed front of the current
    base exists (``DRESSED_FRONT_FIRST`` — its draft is made from it)."""
    from app.core import base_body
    if view in ("main", "face") or not base_body.is_base_pipeline(character_name):
        return
    if not base_ready:
        if view not in base_body.dressed_views():
            raise HTTPException(status_code=409, detail=base_body.SIDE_VIEW_NOT_DRESSED)
        return
    from app.core.model_refs import current_outfit_state
    signature = current_outfit_state(character_name)[2]
    if base_body.dressed_image(character_name, "front", signature,
                               base_body.base_signature(character_name)) is None:
        raise HTTPException(status_code=409, detail=base_body.DRESSED_FRONT_FIRST)


def _require_base_images(character_name: str, view: Optional[str]) -> None:
    """409 ``BASE_FIRST`` when a T-pose render of a base-body-pipeline
    character would find no base view image of the CURRENT base signature
    to edit (``base_body.generate_dressed_images`` would only log it and
    return nothing). ``view`` None = every base view, "main" = the front;
    the face view is no edit of the base body. Checked before any thread
    starts; missing dressed images alone are fine (that is what the render
    makes)."""
    from app.core import base_body
    from app.core.model_refs import find_ref_image
    if view == "face" or not base_body.is_base_pipeline(character_name):
        return
    views = base_body.BASE_VIEWS if view is None else ("front" if view == "main" else view,)
    bsig = base_body.base_signature(character_name)
    if any(find_ref_image(character_name, "tpose" if v == "front" else f"tpose_{v}", bsig) is None
           for v in views if v in base_body.BASE_VIEWS):
        raise HTTPException(status_code=409, detail=BASE_FIRST)


async def _face_dialog_render(body: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the image dialog's picks for one face view render. The render
    runs in a background thread, so a dead explicit backend (503) or a LoRA
    the library does not associate with it (400) is answered HERE."""
    for key in ("prompt", "backend", "negative_prompt"):
        if not isinstance(body.get(key) or "", str):
            raise HTTPException(status_code=422, detail=f"{key} must be a string")
    loras = body.get("loras")
    if loras is not None:
        if not isinstance(loras, list) or not all(
                isinstance(l, dict) and isinstance(l.get("name"), str) and l["name"].strip()
                and isinstance(l.get("strength", 1.0), (int, float)) for l in loras):
            raise HTTPException(status_code=422,
                                detail="loras must be a list of {name, strength}")
        loras = [{"name": l["name"].strip(), "strength": float(l.get("strength", 1.0))}
                 for l in loras]
    backend_pick = (body.get("backend") or "").strip()
    if backend_pick:
        from app.core.explicit_backend import require_explicit_backend_async
        from app.core.lora_library import LoraNotAllowedError, assert_loras_allowed
        backend = await require_explicit_backend_async(backend_pick, has_input_image=True)
        try:
            assert_loras_allowed(backend, loras or [])
        except LoraNotAllowedError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"prompt": (body.get("prompt") or "").strip(), "backend": backend_pick,
            # [] = the dialog chose no LoRA (still a dialog pick); None = none sent.
            "loras": loras if loras is not None else [],
            "negative_prompt": (body.get("negative_prompt") or "").strip()}


@router.post("/{character_name}/model-refs/auto")
async def set_character_model_refs_auto(character_name: str, request: Request) -> Dict[str, Any]:
    """Per-image toggles for the automatic outfit-change render
    (body: {tpose?: bool, pose?: bool})."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_set_character_model_refs_auto_sync,
                                   character_name, body)


def _set_character_model_refs_auto_sync(character_name: str,
                                        body: Any) -> Dict[str, Any]:
    """The blocking body of ``set_character_model_refs_auto`` — runs in the
    threadpool."""
    from app.core.model_refs import set_auto_kinds
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    return {"auto": set_auto_kinds(character_name, body)}


@router.post("/{character_name}/model-refs/views")
async def set_character_model_refs_views(character_name: str,
                                         request: Request) -> Dict[str, Any]:
    """Per-character toggles for the extra T-pose views (multi-view img2mesh
    input; keys depend on character body form)."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_set_character_model_refs_views_sync,
                                   character_name, body)


def _set_character_model_refs_views_sync(character_name: str,
                                         body: Any) -> Dict[str, Any]:
    """The blocking body of ``set_character_model_refs_views`` — runs in the
    threadpool."""
    from app.core.model_refs import set_view_kinds
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    try:
        return {"views": set_view_kinds(character_name, body)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{character_name}/model-refs/{kind}")
def get_character_model_ref_image(character_name: str, kind: str, request: Request):
    """Serves the reference render of the CURRENT outfit combination; 404
    when absent. ``kind`` is ``tpose``/``pose`` or one of the extra T-pose
    view kinds (``tpose_front``/``tpose_back``/``tpose_left``/``tpose_right``/``face_view``), or
    ``tpose_<view>_draft`` (a base-body draft: back, left, right). ETag so a
    re-render of the same combination (or an outfit switch) is picked up
    instead of a stale cached image."""
    from fastapi.responses import Response
    from app.core.model_refs import REF_KINDS, VIEW_KINDS, find_ref_image
    from app.core.base_body import DRAFT_VIEWS
    draft_kinds = tuple(f"tpose_{v}_draft" for v in DRAFT_VIEWS)
    if kind in draft_kinds:
        # A base-body draft of the current outfit (a model_refs
        # subdirectory, not a ref kind of its own).
        from app.core.base_body import draft_path
        from app.core.model_refs import current_outfit_state
        path = draft_path(character_name, kind[len("tpose_"):-len("_draft")],
                          current_outfit_state(character_name)[2])
        if not path:
            return Response(status_code=404, headers={"Cache-Control": "no-cache"})
        media_type, _ = mimetypes.guess_type(str(path))
        return etag_file_response(path, request, media_type or "application/octet-stream")
    if kind not in REF_KINDS and kind not in VIEW_KINDS and kind != "face_view":
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {', '.join(REF_KINDS + VIEW_KINDS + ('face_view',) + draft_kinds)}")
    path = find_ref_image(character_name, kind)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _ = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "application/octet-stream")


# --- Base body (bald A-pose figure per humanoid, app/core/base_body.py) ---

class BaseBodyImagesRequest(BaseModel):
    view: Optional[Literal["front", "back", "left", "right"]] = None
    force: bool = False


def _require_character(character_name: str) -> None:
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")


def _refuse_during_build(character_name: str) -> None:
    """409 ``figure_build.BASE_BUILD_RUNNING`` while a Build of the character runs (Ruling A20): a base view,
    the skin step or the base model made beside it would change what the Build builds on."""
    from app.core import figure_build
    if figure_build.running(character_name):
        raise HTTPException(status_code=409, detail=figure_build.BASE_BUILD_RUNNING)


@router.post("/{character_name}/base-body/images", status_code=202)
def generate_character_base_body_images(character_name: str, body: BaseBodyImagesRequest,
                                        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Render the base-body views in a worker thread: all four (cached ones
    skipped unless ``force``) or one ``view``. 400 for a non-humanoid, 409
    when the profile picture or (for a single view) the front is missing, or
    while a Build of the character runs (Ruling A20)."""
    from app.core.base_body import MissingInput, check_renderable, start_base_images
    _require_character(character_name)
    _refuse_during_build(character_name)
    try:
        check_renderable(character_name, view=body.view)
    except MissingInput as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    start_base_images(character_name, view=body.view, force=body.force)
    return {"started": True}


class BaseBodyModelRequest(BaseModel):
    force: bool = False


@router.post("/{character_name}/base-body/model", status_code=202)
def generate_character_base_body_model(character_name: str, body: BaseBodyModelRequest,
                                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Build the rigged base model from the base images in a worker thread
    (cached per base signature unless ``force``). 400 for a non-humanoid,
    409 without a profile picture or base images, while a 3D model
    generation runs for the character, or while its Build runs (Ruling A20)."""
    from app.core.base_body import MissingInput, check_model_ready, start_base_model
    _require_character(character_name)
    _refuse_during_build(character_name)
    try:
        check_model_ready(character_name)
    except MissingInput as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not start_base_model(character_name, force=body.force):
        raise HTTPException(status_code=409,
                            detail="A 3D model generation is already running for this character")
    return {"started": True}


@router.get("/{character_name}/base-body/images/{view}")
def get_character_base_body_image(character_name: str, view: str, request: Request,
                                  variant: Optional[Literal["neutral"]] = None,
                                  _: Dict[str, Any] = Depends(require_admin)):
    """One stored base-body view of the CURRENT base signature; 404 when
    absent. ETag, so a re-render is picked up. ``variant=neutral`` (front
    only): the neutral front the skin detail step started from
    (``base_skin``)."""
    from fastapi.responses import Response
    from app.core.base_body import BASE_VIEWS, base_image_path, base_signature
    if view not in BASE_VIEWS:
        raise HTTPException(status_code=400, detail=f"view must be one of {', '.join(BASE_VIEWS)}")
    if variant and view != "front":
        raise HTTPException(status_code=400, detail="Only the front has a neutral variant")
    _require_character(character_name)
    if variant:
        from app.core.base_skin import neutral_path
        path = neutral_path(character_name, base_signature(character_name))
    else:
        path = base_image_path(character_name, view)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _encoding = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "application/octet-stream")


@router.post("/{character_name}/base-body/skin-step", status_code=202)
def rerun_character_base_body_skin_step(character_name: str,
                                        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Re-run the skin detail step of the base front from its stored neutral
    front, without re-rendering it (``base_skin.apply_skin_step``, a worker
    thread; one image edit). 400 for a non-humanoid, 409 without a front,
    while a base view renders, or while a Build of the character runs
    (Ruling A20)."""
    from app.core import base_body, base_skin
    _require_character(character_name)
    _refuse_during_build(character_name)
    try:
        base_body.check_renderable(character_name, view="back")
    except base_body.MissingInput as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if any(s.get("running") for s in base_body.base_status(character_name).values()):
        raise HTTPException(status_code=409, detail="A base view renders right now")
    base_skin.start_skin_step(character_name)
    return {"started": True}


# --- Garments: hair as its own mesh (app/core/garments.py, garment_hair.py) ---
# Plan 2026-11-09-base-body-phase4-hair. All admin-only; the chain runs in a
# worker thread (garments.start_garment), these routes only start and read.

class GarmentEquippedRequest(BaseModel):
    equipped: bool


class OutfitOptionsRequest(BaseModel):
    boot_hem: Optional[str] = None


class PieceStateRequest(BaseModel):
    # Plain strings, validated by outfit_options.set_piece_state (400 with its message, not a schema 422).
    item_id: str = ""
    state: Any = None


class HairMethodRequest(BaseModel):
    # Plain strings, validated by garment_hair.set_hairstyle_mode (400, not 422). ``item_id`` "" = the worn
    # hairstyle.
    method: str = ""
    item_id: str = ""


class HairstyleTextRequest(BaseModel):
    # The hairstyle's text; ``item_id`` "" = the worn hairstyle.
    description: str = ""
    item_id: str = ""


class HaarSeedRequest(BaseModel):
    # The HAAR seed to serve, or null for automatic (the best passing seed); validated by garment_hair.set_haar_seed
    # (400, not 422). ``item_id`` "" = the worn hairstyle.
    seed: Optional[Any] = None
    item_id: str = ""


class HairColourRequest(BaseModel):
    # "#rrggbb" or "" (automatic); validated by garment_hair.set_hair_colour. ``item_id`` "" = the worn hairstyle.
    hex: str = ""
    item_id: str = ""


class HairPlacementRequest(BaseModel):
    # Numbers or null (automatic); plain Any so garment_hair.set_hair_placement
    # validates (400 with its message, not a schema 422). ``item_id`` "" = the worn hairstyle.
    forward_m: Any = None
    tilt_deg: Any = None
    width_scale: Any = None
    item_id: str = ""


class HairMotionRequest(BaseModel):
    # Plain Any so hair_motion.set_hair_motion validates (400 with its message, not a schema 422).
    # ``item_id`` "" = the worn hairstyle.
    swing: Any = True
    stiffness: Any = None
    item_id: str = ""


class HairstyleCreateRequest(BaseModel):
    # Plain strings, validated by garment_hair.create_hairstyle (400 with its message, not a schema 422):
    # ``description`` "" = the Appearance's hair text, ``mode`` "" = the world's default mode.
    description: str = ""
    mode: str = ""


class FootwearWidthCapRequest(BaseModel):
    # A number or null (back to the default); plain Any so garment_footwear.set_width_cap validates (400 with
    # its message, not a schema 422).
    cap: Any = None


class GarmentFitSettingsRequest(BaseModel):
    # Ruling A47: any of sleeves_left / sleeves_right / allowance — plain Any so garment_fit_settings.validate
    # answers a 400 with its message (not a schema 422); a field left out is unchanged.
    sleeves_left: Any = None
    sleeves_right: Any = None
    allowance: Any = None


class PieceViewSourceRequest(BaseModel):
    # Ruling A46: "front" / "back" and "auto" / "generated" / "worn" — validated by garment_from_worn.set_choice.
    view: str
    choice: str


class GarmentRunRequest(BaseModel):
    # Plain strings, validated by garments.start_garment: an unknown step or
    # view is a 400 with its message, not a schema 422.
    step: Optional[str] = None
    view: Optional[str] = None
    force: bool = False
    # "open" / "closed" for a closable clothing piece (plan 2026-11-12-unified-worn-pieces Task 11b); None = the
    # state it is worn in when the run starts.
    state: Optional[str] = None
    # With a step: True runs the chain FROM it (Re-render, the hair row's Regenerate); False (default) runs only
    # that step (the steps dialog's buttons, fix round T12-F1 ruling F13 d). Without a step: always the chain.
    chain: bool = False
    # With a view (Ruling A33): run the view's missing prerequisite views first (the button's explicit "first"
    # action); without it a missing one is a 409 before anything is spent.
    prerequisites: bool = False
    # Ruling A50: with step "fit", the body shape the Re-fit fits on (an outfit body id; "plain" / None = the plain
    # body) — the piece dialog's selected body.
    body: Optional[str] = None


class GarmentMeshFetchRequest(BaseModel):
    # The gateway job id as pasted ("Job 466a4e41b73d" works too); model3d.normalize_job_id checks it.
    job_id: str = ""


def _gate_limits(gates: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Chip limits of a mesh gate table ``{key: (min|max, limit, label)}``."""
    return {key: {"op": "le" if kind == "max" else "ge", "value": limit}
            for key, (kind, limit, _label) in gates.items()}


def _footwear_gate_limits(gates: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Chip limits of a footwear gate table ``{key: (min|max|range, limit, label)}``."""
    return {key: ({"op": "range", "value": list(limit)} if kind == "range"
                  else {"op": "le" if kind == "max" else "ge", "value": limit})
            for key, (kind, limit, _label) in gates.items()}


def _garment_limits(kind: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """The gate limits per step of a garment ``kind`` for the chips, read
    from the gate constants themselves: clothing — the image gates
    (``garment_gates.limits``), the mesh component share and the fit gates
    (``garment_fit.CLOTHING_GATES``); hair — none here (HairDeck's fit gates
    are the hair GET's ``hairdeck_fit``). Footwear: the
    empty-shoe, mesh and insole gates of the shoe source (``footwear_gates``,
    ``footwear_insole``, the insole with the boot's ``SHAFT_GATES``) and the
    fit gates (``footwear_fit.FIT_GATES``, the split fit's ``SHAFT_GATES`` —
    the chips show a recorded-only one as "Reported, not gated" by the
    record's ``gating`` — plus the body-cut gates ``footwear_cut.CUT_GATES``,
    which the fit step runs and records under the same ``gates``)."""
    from app.core import garment_fit, garment_gates, garment_mesh
    if kind == "footwear":
        from app.core import footwear_cut, footwear_fit, footwear_gates, footwear_insole
        fit_gates = {key: (kind_, limit, footwear_fit.GATE_LABELS[key])
                     for key, (kind_, limit) in {**footwear_fit.FIT_GATES, **footwear_fit.SHAFT_GATES}.items()}
        fit_gates.update({key: (kind_, limit, footwear_cut.GATE_LABELS[key])
                          for key, (kind_, limit) in footwear_cut.CUT_GATES.items()})
        return {"empty": _footwear_gate_limits(footwear_gates.EMPTY_GATES),
                "mesh": _footwear_gate_limits(footwear_gates.MESH_GATES),
                "insole": _footwear_gate_limits({**footwear_insole.INSOLE_GATES, **footwear_insole.SHAFT_GATES}),
                "fit": _footwear_gate_limits(fit_gates)}
    if kind != "clothing":
        return {}
    return {**garment_gates.limits(kind),
            "mesh": {"largest_component_share": {"op": "ge", "value": garment_mesh.MIN_COMPONENT_SHARE}},
            "fit": _gate_limits(garment_fit.CLOTHING_GATES),
            # Ruling A50b: a fit on a body shape is placed from the plain body's fit — its placement push numbers
            # are recorded, not gated (``garment_fit.clothing_gates``); the chips of a selected body shape use these.
            "fit_body": _gate_limits(garment_fit.clothing_gates(torso_mapped=True))}


@router.get("/{character_name}/garments")
def get_character_garments(character_name: str,
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The Wardrobe's own-mesh overview (``garment_set.wardrobe``):
    ``{pipeline, items: {item_id: {state, step, painted, reason,
    queue_position, over, without}}, overlaps: [{items, slots}],
    queue_running, queue}`` — every own-mesh piece the character holds or
    wears (a worn piece over others names them), the worn pieces that are
    over each other (layered in slot rank order), and the character's
    garment queue (the item in flight, the waiting ones in run order)."""
    from app.core import garment_set
    _require_character(character_name)
    return garment_set.wardrobe(character_name)


@router.get("/{character_name}/garments/{item_id}")
def get_character_garment(character_name: str, item_id: str,
                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The Wardrobe's panel of one own-mesh piece (or any garment of the
    character): ``{pipeline, item_id, name, kind, mesh_mode, worn, status,
    garment, limits, run, view_runs, use_runs}`` (``run``: ``garments.run_estimate`` — the dialog's "Run all" label;
    ``use_runs``: ``garments.use_plans`` — "Use this" on each stored attempt, Ruling A37;
    ``view_runs``: ``garments.view_plans`` — each per-view button's jobs, follow-up and missing prerequisites,
    None without per-view runs; ``mesh_mode``: the item's mode,
    ``garment_set.mesh_mode_of``; None for hair) — ``garment`` is ``garments.garment_info`` (a
    footwear piece: ``garment_footwear.info``, the shoe source steps; every
    image with its ``freshness``, the preview with ``preview_freshness``,
    ``failed`` also after a restart), ``limits`` the chip limits of the
    item's kind (``_garment_limits``), ``status`` the row chip
    (``garment_set.piece_status``). 404 for an item that is no garment of
    this character (an outfit piece not in mode ``own_mesh``, a piece it
    does not hold, another character's hair)."""
    from app.core import base_body, garment_set, garments
    from app.models.character import get_character_profile
    from app.models.inventory import get_item
    _require_character(character_name)
    try:
        info = garments.garment_info(character_name, item_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    kind = str(info.get("kind") or "")
    item = get_item(item_id) or {}
    profile = get_character_profile(character_name) or {}
    pipeline = base_body.is_base_pipeline(character_name, profile=profile)
    base = base_body.current_base(character_name, profile=profile) if pipeline else None
    pieces = profile.get("equipped_pieces") if isinstance(profile.get("equipped_pieces"), dict) else {}
    mesh_pieces = profile.get("equipped_mesh_pieces") if isinstance(profile.get("equipped_mesh_pieces"), dict) else {}
    worn = item_id in pieces.values() or item_id in mesh_pieces.values()
    # A worn own-mesh clothing piece without its fit is in the body shape meanwhile (ruling A11, the delivered
    # figure's ``in_body_own``) or left out in the refusal branch; hair is simply absent and footwear is
    # missing until fitted (``piece_status``, spec § 9.1).
    worn_piece = bool(pipeline and worn and kind in garment_set.OWN_MESH_PIECE_KINDS)
    left_out = in_body = False
    if worn_piece:
        from app.core import figure
        delivered = figure.delivered_figure_cached(character_name, profile=profile)
        left_out = item_id in delivered.left_out
        in_body = item_id in delivered.in_body_own   # ruling A11: in the body until its own mesh is ready
    payload = {"pipeline": pipeline, "item_id": item_id, "name": str(item.get("name") or item_id),
               "kind": kind, "mesh_mode": garment_set.mesh_mode_of(item), "worn": bool(worn),
               "status": garment_set.piece_status(
                   info, worn=worn_piece, base_model_ready=bool(base and base[1]),
                   layers=garment_set.worn_layers(character_name, profile=profile,
                                                  base_model_sha=base[1] if base else "").get(item_id),
                   left_out=left_out, in_body=in_body),
               "garment": info, "limits": _garment_limits(kind),
               # Ruling A31: the Details preview's body switch — each body's fit attempt, its status and reason;
               # Ruling A67: the base body and the current body only (``fit_attempts.bodies``; [] off the pipeline
               # and for hair).
               "bodies": _fit_bodies(character_name, item_id, profile) if pipeline else [],
               # What the dialog's "Run all" runs now (Task UI1, rule R1): the chain from its first step that is
               # not current — ``garments.run_estimate``, the same plan the run takes; None off the pipeline.
               "run": garments.run_estimate(character_name, item_id, profile=profile) if pipeline else None,
               # Ruling A33: what each per-view button of the step grid spends and needs, before the click.
               "view_runs": garments.view_plans(character_name, item_id, profile=profile) if pipeline else None,
               # Ruling A37: "Use this" on each stored attempt — passing / by the user, why not, the cost after.
               "use_runs": garments.use_plans(character_name, item_id, profile=profile) if pipeline else None}
    from app.core.model_overview import annotate_garment
    return annotate_garment(payload)


@router.get("/{character_name}/hair")
def get_character_hair(character_name: str, item_id: str = "",
                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The hair GET (the Hairstyles tab's selected hairstyle): ``{pipeline, humanoid, description, behind_shoulders,
    item_id, equipped, garment, collision, limits, method, method_source,
    world_method, hairdeck, others, hair_in_body, base_prompts, plain, run, body_url}`` — ``description`` is
    the hairstyle's text (without one the Appearance's), ``item_id`` the hairstyle asked for by the query
    ``item_id`` (404 when it is no hairstyle of the character; Task 14), else the worn hair item or
    else the one the character owns (None: no item yet), ``garment`` its
    ``garments.garment_info`` (None without an item), ``collision`` the
    current base model's capsule set (``collision.ensure``) the preview
    pushes the hair out of, None without a preview or base model; ``limits`` the gate limits for the
    tab's chips: ``hairdeck_fit``, those of the hair's length class
    (``garment_hairdeck.gates_for``, from the gate constants themselves). ``method`` the hairstyle's mode
    (``method_source`` ``"hairstyle"``), ``world_method`` the world's default mode for a new hairstyle
    (``garment_hair.default_mode``); ``item_id`` / ``equipped`` the worn hairstyle (else the first owned one,
    not equipped); ``hairdeck`` the HairDeck section of the current
    ``hsig`` (``garments.hairdeck_panel``, None without an item), ``haar`` the HAAR variants of a HAAR
    hairstyle (``garments.haar_panel``: seeds with their verdicts, the served and the picked one, the next
    seeds; None for another mode) and
    ``others`` the kept results of the methods not selected, newest first
    (``garments.other_methods_info``, ``[]`` without an item). Every image carries a ``freshness`` and both previews a
    ``preview_freshness`` (``model_overview.annotate_hair``). ``hair_in_body``: the method is ``body`` — the hair
    is part of the body mesh, ``garment`` / ``hairdeck`` stay None and ``others`` empty even with a leftover item,
    and ``base_prompts`` is the stored base's prompt freshness (``base_body.base_prompts_freshness``; None off
    the pipeline or for another method). Task 14: ``hair_in_body`` is THIS hairstyle's mode being ``body``;
    ``plain`` this hairstyle is the plain body's (``garment_hair.BASE_HAIRSTYLE_KEY``); ``run`` what its "Run all"
    runs now (``garments.run_estimate`` of the hairstyle; None off the pipeline or without one); ``body_url`` the
    current base model (``base_body.base_model_info`` url; None without one) — the preview of a ``body``
    hairstyle that is the plain body's. Task UI4: ``step_jobs`` the hub jobs of each step of the hairstyle's
    mode on first attempts (``garments.HUB_JOBS``, ``{}`` for ``body``), ``preview_motion`` the previewed fit's
    spring chains for the live Stiffness preview (``hair_motion.preview_payload``; None without a preview),
    ``preview_strands_url`` the strand record of that previewed fit (``GET …/garments/{item}/hair-strands``, the
    per-strand preview, strand-hair spec § 6.2.3; None without a preview fit).
    ``alpha_cutoff``: the world's hair-card cutoff (``hair_cards.alpha_cutoff``, strand-hair spec § 6.1) the preview
    applies to the MASK cards it shows."""
    from app.core import base_body, garment_hair, garment_hairdeck, garments, hair_cards
    from app.core.model_refs import is_humanoid
    from app.models.character import get_character_profile
    from app.models.inventory import get_item
    _require_character(character_name)
    profile = get_character_profile(character_name) or {}
    humanoid = bool(is_humanoid(character_name, profile=profile))
    asked = str(item_id or "").strip()
    if asked:
        item = get_item(asked) if humanoid else None
        if not garment_hair.is_hairstyle(item, character_name):
            raise HTTPException(status_code=404, detail="No hairstyle of this character")
    else:
        item = (garment_hair.worn_hairstyle(character_name, profile)
                or next(iter(garment_hair.hairstyles(character_name)), None)) if humanoid else None
    in_body = bool(item and garment_hair.hairstyle_mode(item) == garment_hair.BODY_MODE)
    item_id = item["id"] if item else None
    worn = profile.get("equipped_mesh_pieces")
    equipped = bool(item_id and isinstance(worn, dict) and worn.get(garment_hair.HAIR_KIND) == item_id)
    info = hairdeck = haar = None
    others: List[Dict[str, Any]] = []
    # Hair in the body mesh: no hair item is run or served — the tab shows the
    # method and the base body's prompt freshness instead of the steps.
    if item_id and not in_body:
        try:
            info = garments.garment_info(character_name, item_id)
            hairdeck = garments.hairdeck_panel(character_name, item_id, profile=profile)
            haar = (garments.haar_panel(character_name, item_id, profile=profile)
                    if garment_hair.hairstyle_mode(item) == garment_hair.HAAR_MODE else None)
            others = garments.other_methods_info(character_name, item_id, profile=profile)
        except ValueError:
            info = hairdeck = haar = None
            others = []
    method = garment_hair.hairstyle_mode(item) if item else garment_hair.default_mode()
    method_source = "hairstyle" if item else "world"
    # The hairstyle's text; without one the Appearance's, which its first hairstyle will be made from.
    text = (garment_hair.hairstyle_description(item) if item
            else garment_hair.appearance_hair_text(character_name, profile=profile)) if humanoid else ""
    # The preview is the hair fitted on the current base model, so the base
    # model's capsule set is what the viewer pushes the hair out of (the
    # same set the outfit models inherit, the same push the 3D client runs).
    hair_collision = None
    if info and info.get("preview_url"):
        try:
            from app.core import collision
            from app.core.model3d import _current_base
            current = _current_base(character_name)
            if current:
                hair_collision = collision.ensure(character_name, current[0])
        except Exception:
            logger.exception("Hair GET: no capsule set for %s", character_name)
    pipeline = base_body.is_base_pipeline(character_name, profile=profile)
    run = None
    if pipeline and item_id:
        try:
            run = garments.run_estimate(character_name, item_id, profile=profile)
        except Exception:  # noqa: BLE001 — a label, never a failure of the GET
            logger.exception("Hair GET: no run estimate for %s/%s", character_name, item_id)
    model = base_body.base_model_info(character_name) if pipeline else None
    # The Hairstyles tab's live Stiffness preview of the previewed fit (``hair_motion.preview_payload``).
    preview_motion = None
    preview_strands_url = None
    if info and info.get("preview_url") and item_id:
        try:
            from app.core import garment_store as gs, hair_motion
            fit_path = garments.preview_path(character_name, item_id)
            if fit_path is not None:
                # The previewed fit's strand record (strand-hair spec § 6.2.3), whatever Swing says.
                preview_strands_url = f"/characters/{quote(character_name)}/garments/{quote(item_id)}/hair-strands"
                preview_motion = hair_motion.preview_payload(
                    character_name, fit_path, gs.read_record(fit_path.with_suffix(".json")), profile=profile)
        except Exception:  # noqa: BLE001 — a preview aid, never a failure of the GET
            logger.exception("Hair GET: no motion preview for %s/%s", character_name, item_id)
    payload = {"pipeline": pipeline,
                "humanoid": humanoid,
                "description": text,
                "behind_shoulders": bool(text and garment_hair.hair_behind_shoulders(
                    character_name, profile=profile, text=text)),
                "item_id": item_id, "equipped": equipped, "garment": info, "collision": hair_collision,
                "limits": {**_garment_limits("hair"),
                           "hairdeck_fit": _gate_limits(garment_hairdeck.gates_for(
                               garment_hair.hair_length_class(character_name, profile=profile, text=text)
                               if text else None))},
                "method": method, "method_source": method_source,
                "world_method": garment_hair.default_mode(),
                "hairdeck": hairdeck, "haar": haar, "others": others,
                "hair_in_body": in_body,
                "base_prompts": (base_body.base_prompts_freshness(character_name, profile=profile)
                                 if in_body and pipeline else None),
                "plain": bool(item_id and item_id == str(profile.get(garment_hair.BASE_HAIRSTYLE_KEY) or "")),
                "run": run,
                # The single steps' hub jobs on first attempts (``garments.HUB_JOBS``) — the buttons name them.
                "step_jobs": dict(garments.HUB_JOBS.get(f"hair:{method}") or {}),
                "preview_motion": preview_motion,
                # The previewed fit's strand record (``GET …/garments/{item}/hair-strands``); None without one.
                "preview_strands_url": preview_strands_url,
                "body_url": (model or {}).get("url"),
                # Ruling UI3 a: when the plain body shown there was built (the 3D preview's caption).
                "body_built_at": (model or {}).get("created_at") or None,
                # The world's hair-card cutoff (strand-hair spec § 6.1): the preview applies it to the MASK
                # cards of the fit it shows, so a changed setting shows at once without a refit.
                "alpha_cutoff": hair_cards.alpha_cutoff()}
    from app.core.model_overview import annotate_hair
    return annotate_hair(payload)


def _hairstyle_id(character_name: str, item_id: str) -> str:
    """``item_id``, else the worn hairstyle's; 404 without either."""
    from app.core import garment_hair
    found = str(item_id or "").strip() or garment_hair.worn_hair_id(character_name)
    if not found:
        raise HTTPException(status_code=404, detail="This character wears no hairstyle")
    return found


@router.get("/{character_name}/hairstyles")
def get_character_hairstyles(character_name: str,
                             _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The character's hairstyles (plan 2026-11-12-unified-worn-pieces Task 13):
    ``{hairstyles: [{id, name, description, mode, worn, plain, freshness:
    {state, reason}}], default_mode, modes, built_modes}`` — worn first
    (``garment_hair.hairstyle_list``); ``plain`` marks the hairstyle the
    plain body is the body of, ``default_mode`` the mode a new one gets,
    ``modes`` every mode, ``built_modes`` the ones that can be chosen
    (every mode since HAAR, strand-hair spec § 6.3). Task UI4: every hairstyle not worn carries
    ``wear`` — what its Wear button spends after the click
    (``garment_hair.wear_estimate``: ``{hub_jobs, automatic, note}``, None
    off the pipeline) and every HairDeck or HAAR hairstyle ``due`` — the steps its
    Run all would run now (``garments.run_estimate`` ``steps``; ``[]`` when
    current, off the pipeline or for another mode), so a saved setting shows
    in the list too; ``pipeline`` / ``auto_build`` the character's figure
    pipeline and "Build automatically". Ruling A54: ``appearance_hair_text``
    the standard text a new hairstyle starts from (``garment_hair.appearance_hair_text``,
    what ``create_hairstyle`` uses for an empty description; "" for a bald or
    non-humanoid character) — the "New hairstyle" dialog opens with it in its
    field. Read-only; admin only like its sibling hair routes (Ruling FR-minors)."""
    from app.core import figure_build, garment_hair, garments
    from app.core.model_refs import is_humanoid
    from app.models.character import get_character_profile
    _require_character(character_name)
    profile = get_character_profile(character_name) or {}
    rows = garment_hair.hairstyle_list(character_name, profile=profile)
    pipeline = figure_build.on_pipeline(character_name, profile=profile)
    for row in rows:
        row["wear"] = (garment_hair.wear_estimate(character_name, row["id"], profile=profile)
                       if pipeline and not row["worn"] else None)
        due: List[str] = []
        if pipeline and row["mode"] in (garment_hair.HAIRDECK_MODE, garment_hair.HAAR_MODE):
            try:
                due = list(garments.run_estimate(character_name, row["id"], profile=profile).get("steps") or [])
            except Exception:  # noqa: BLE001 — a list light, never a failure of the list
                logger.exception("Hairstyles GET: no run estimate for %s/%s", character_name, row["id"])
        row["due"] = due
    return {"hairstyles": rows,
            "default_mode": garment_hair.default_mode(),
            "modes": list(garment_hair.HAIR_MODES), "built_modes": list(garment_hair.BUILT_MODES),
            "pipeline": bool(pipeline),
            "auto_build": bool(pipeline and figure_build.auto_build_on(character_name, profile=profile)),
            "appearance_hair_text": (garment_hair.appearance_hair_text(character_name, profile=profile)
                                     if is_humanoid(character_name, profile=profile) else "")}


@router.post("/{character_name}/hairstyles", status_code=201)
def create_character_hairstyle(character_name: str, body: HairstyleCreateRequest,
                               _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Create a hairstyle (``description`` "" = the Appearance's hair text,
    ``mode`` "" = the world default). Starts nothing and wears nothing —
    except a character's first hairstyle, which is worn. 400 for an unknown
    mode, a non-humanoid or no text. ``{item_id}``."""
    from app.core import garment_hair
    _require_character(character_name)
    try:
        item_id = garment_hair.create_hairstyle(character_name, body.description, body.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"item_id": item_id}


@router.post("/{character_name}/hairstyles/{item_id}/wear")
def wear_character_hairstyle(character_name: str, item_id: str,
                             _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Wear the hairstyle ``item_id`` — an outfit change: the Build is
    requested (``figure_build.request``), nothing else starts. 400 for an
    item that is no hairstyle of the character. ``{worn}``."""
    from app.core import garment_hair
    _require_character(character_name)
    try:
        saved = garment_hair.wear_hairstyle(character_name, item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the character profile failed")
    return {"worn": item_id}


def _hairstyle_delete_errors(fn, *args):
    """``hairstyle_delete``'s errors as HTTP answers: 400 an invalid id or a shared item, 404 no hairstyle of the
    character, 409 a run or a Build works now, 500 a failed write."""
    from app.core import hairstyle_delete
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except hairstyle_delete.HairstyleBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/hairstyles/{item_id}/delete-preview")
def get_character_hairstyle_delete_preview(character_name: str, item_id: str,
                                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """What deleting the hairstyle ``item_id`` removes — the confirmation's content (Ruling A59,
    ``hairstyle_delete.delete_preview``): its files per group, the assembled models grafting it, the body shapes
    with its hair, the outfit sets that wear it, whether it is worn / the plain body's / the last one, and what the
    Build after it costs (``estimate``). Read-only; 400 for an invalid id, 404 for no hairstyle of the character."""
    from app.core import hairstyle_delete
    _require_character(character_name)
    return _hairstyle_delete_errors(hairstyle_delete.delete_preview, character_name, item_id)


@router.delete("/{character_name}/hairstyles/{item_id}")
def delete_character_hairstyle(character_name: str, item_id: str,
                               _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Delete the hairstyle ``item_id`` with its files (Ruling A59, ``hairstyle_delete.delete_hairstyle``): the
    item, its ownership, its generated files under ``garments/``, the assembled models grafting it and the body
    shapes only it stands on. The worn one may go (the character then wears no hairstyle; the Build is requested
    like a Wear), the last one too. 400 for an invalid id or a shared item, 404 for no hairstyle of the character,
    409 while a run of it or a Build works."""
    from app.core import hairstyle_delete
    _require_character(character_name)
    return _hairstyle_delete_errors(hairstyle_delete.delete_hairstyle, character_name, item_id)


@router.post("/{character_name}/hair/method")
def set_character_hair_method(character_name: str, body: HairMethodRequest,
                              _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Set a hairstyle's mode (``item_id`` "" = the worn one): ``""`` (the
    world default ``base_body.hairstyle_default_mode``), ``"body"`` (in the
    body mesh), ``"hairdeck"`` or ``"haar"``; anything else is a 400. No GPU
    work starts: the served model is re-assembled."""
    from app.core import garment_assembly, garment_hair
    _require_character(character_name)
    item_id = _hairstyle_id(character_name, body.item_id)
    try:
        saved = garment_hair.set_hairstyle_mode(character_name, item_id, body.method)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the hairstyle failed")
    try:
        garment_assembly.schedule(character_name)
    except Exception as e:  # noqa: BLE001 — a failed schedule must not undo the stored choice
        logger.warning("garment assembly schedule for %s failed: %s", character_name, e)
    from app.models.inventory import get_item
    return {"method": garment_hair.hairstyle_mode(get_item(item_id)), "method_source": "hairstyle",
            "item_id": item_id}


@router.post("/{character_name}/hair/haar-seed")
def set_character_haar_seed(character_name: str, body: HaarSeedRequest,
                            _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Pick the HAAR variant a hairstyle (``item_id`` "" = the worn one) serves: ``seed`` a stored seed, or null
    for automatic (the best passing seed, strand-hair spec § 6.3.1). A refused seed may be picked (its reasons
    stay shown). Runs nothing: the fit fingerprint names the served seed, so Re-fit applies it on the CPU — no
    hub job. 400 for a value that is no positive integer, or a seed the hairstyle has not stored. ``{seed,
    served}`` — the stored pick and the seed served once refitted."""
    from app.core import garment_hair, garment_store as gs, garments
    from app.models.inventory import get_item
    _require_character(character_name)
    item_id = _hairstyle_id(character_name, body.item_id)
    seed = body.seed
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise HTTPException(status_code=400, detail="HAAR seed must be a positive integer or null")
    try:
        if not garment_hair.is_hairstyle(get_item(item_id), character_name):
            raise ValueError(f"{item_id[:80]!r} is no hairstyle of {character_name}")
        if seed is not None:
            ssig = gs.garment_ssig(character_name, item_id)
            if seed not in gs.haar_seeds(character_name, item_id, ssig):
                raise ValueError(f"HAAR seed {seed} is not stored for this hairstyle")
        saved = garment_hair.set_haar_seed(character_name, item_id, seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the hairstyle failed")
    panel = garments.haar_panel(character_name, item_id) or {}
    return {"seed": panel.get("picked"), "served": panel.get("served"), "item_id": item_id}


@router.post("/{character_name}/hair/description")
def set_character_hairstyle_text(character_name: str, body: HairstyleTextRequest,
                                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Save a hairstyle's text (``item_id`` "" = the worn one; ``garment_hair.set_hairstyle_description``). Runs
    nothing: ``run`` is what its Run all would run afterwards (``garments.run_estimate``; None off the pipeline) —
    the tab writes it beside the text. 400 for an empty text or an item that is no hairstyle of the character."""
    from app.core import base_body, garment_hair, garments
    from app.models.inventory import get_item
    _require_character(character_name)
    item_id = _hairstyle_id(character_name, body.item_id)
    try:
        if not garment_hair.is_hairstyle(get_item(item_id), character_name):
            raise ValueError(f"{item_id[:80]!r} is no hairstyle of {character_name}")
        saved = garment_hair.set_hairstyle_description(character_name, item_id, body.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the hairstyle failed")
    run = None
    if base_body.is_base_pipeline(character_name):
        try:
            run = garments.run_estimate(character_name, item_id)
        except Exception:  # noqa: BLE001 — a label, never a failure of the save
            logger.exception("Hairstyle text: no run estimate for %s/%s", character_name, item_id)
    return {"item_id": item_id, "description": garment_hair.hairstyle_description(get_item(item_id)), "run": run}


@router.post("/{character_name}/hair/colour")
def set_character_hair_colour(character_name: str, body: HairColourRequest,
                              _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Set a hairstyle's (``item_id`` "" = the worn one) manual HairDeck hair
    colour (``"#rrggbb"``) or ``""`` for automatic (the hairstyle text's
    named colour, else HairDeck's own colours: ``source`` ``"profile"`` /
    ``"hairdeck"``). 400 on an invalid value. Only the fit fingerprint
    changes: the next run re-fits from the cached HairDeck job, without a
    HairDeck call (no run starts here)."""
    from app.core import garment_hair
    from app.models.inventory import get_item
    _require_character(character_name)
    item_id = _hairstyle_id(character_name, body.item_id)
    try:
        saved = garment_hair.set_hair_colour(character_name, item_id, body.hex)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the hairstyle failed")
    item = get_item(item_id)
    override = garment_hair.hair_colour_override(garment_hair.hairstyle_settings(item))
    named = garment_hair.profile_hair_colour(character_name, text=garment_hair.hairstyle_description(item))
    return {"target": override or None, "source": "override" if override else ("profile" if named else "hairdeck")}


@router.post("/{character_name}/hair/placement")
def set_character_hair_placement(character_name: str, body: HairPlacementRequest,
                                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Set a hairstyle's (``item_id`` "" = the worn one) HairDeck placement:
    ``forward_m`` (metres along +z), ``tilt_deg`` (forward pitch, degrees)
    and ``width_scale`` (the sides' reach beyond the head), each a number or
    null for automatic (forward ``garment_hairdeck.DEFAULT_FORWARD_M``, tilt
    solved to the brow line, width 1). 400 for a non-number or a value
    beyond its limit. Only the fit fingerprint changes: the next run re-fits
    from the cached HairDeck job, without a HairDeck call (no run starts
    here)."""
    from app.core import garment_hair
    from app.models.inventory import get_item
    _require_character(character_name)
    item_id = _hairstyle_id(character_name, body.item_id)
    try:
        saved = garment_hair.set_hair_placement(character_name, item_id, body.forward_m, body.tilt_deg,
                                                body.width_scale)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the hairstyle failed")
    return {"width_scale": None,
            **garment_hair.hair_placement(garment_hair.hairstyle_settings(get_item(item_id)))}


@router.post("/{character_name}/hair/motion")
def set_character_hair_motion(character_name: str, body: HairMotionRequest,
                              _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Set how a hairstyle's (``item_id`` "" = the worn one) HairDeck hair
    swings on its spring chains: ``swing`` (bool) and ``stiffness`` (a
    factor × HairDeck's per-chain stiffness within
    ``hair_motion.STIFFNESS_LIMITS``, null = 1). 400 for a non-bool swing or
    a stiffness beyond its limits. Stiffness changes only the motion payload.
    Swing is a fit input (Ruling H11): a changed Swing makes the hairstyle's
    fit stale — saved on its own, nothing runs (Task 14, the user's rule R3:
    settings independent of execution); the Hairstyles tab's Run all / Re-fit
    refits it on the CPU. ``{swing, stiffness}`` — the stored settings."""
    from app.core import garment_hair, hair_motion
    from app.models.inventory import get_item
    _require_character(character_name)
    item_id = _hairstyle_id(character_name, body.item_id)
    try:
        saved = hair_motion.set_hair_motion(character_name, item_id, body.swing, body.stiffness)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the hairstyle failed")
    return hair_motion.settings(garment_hair.hairstyle_settings(get_item(item_id)))


@router.post("/{character_name}/hair", status_code=202)
def create_character_hair(character_name: str,
                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Make sure the character wears a hairstyle (its first one is made from
    its Appearance, ``garment_hair.create_hairstyle``) and, for HairDeck
    hair, start its chain (every cached step is skipped).
    ``{item_id, started, queued, position, behind}``: ``started`` False =
    queued behind the character's running garment run, or nothing to run
    (hair in the body mesh). 400 for a non-humanoid, a character that wears
    no hairstyle but owns some, or one without any hair text."""
    from app.core import garment_hair, garments
    from app.models.inventory import get_item
    _require_character(character_name)
    from app.core.model_refs import is_humanoid
    try:
        if not is_humanoid(character_name):
            raise ValueError("Hairstyles are for humanoid characters only")
        item_id = garment_hair.worn_hair_id(character_name)
        if not item_id and garment_hair.hairstyles(character_name):
            raise ValueError("No hairstyle is worn — wear one first")
        item_id = item_id or garment_hair.create_hairstyle(character_name, "", "")
        if garment_hair.hairstyle_mode(get_item(item_id)) != garment_hair.HAIRDECK_MODE:
            return {"item_id": item_id, "started": False, "queued": False, "position": 0, "behind": None}
        queued = garments.start_garment(character_name, item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"item_id": item_id, **queued}


@router.post("/{character_name}/hair/equipped")
def set_character_hair_equipped(character_name: str, body: GarmentEquippedRequest,
                                _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Wear or take off the character's hairstyle (the worn one, else the
    first owned; its mesh-item slot only, no 2D path sees it, R2). 404 when
    the character has no hairstyle. No GPU work starts — the served model is
    re-assembled."""
    from app.core import garment_hair
    from app.models import inventory
    from app.models.character import get_character_profile
    _require_character(character_name)
    item = (garment_hair.worn_hairstyle(character_name, get_character_profile(character_name) or {})
            or next(iter(garment_hair.hairstyles(character_name)), None))
    if not item:
        raise HTTPException(status_code=404, detail="This character has no hairstyle")
    try:
        if body.equipped:
            saved = inventory.equip_mesh_piece(character_name, item["id"])
        else:
            slot = str((item.get("garment") or {}).get("slot") or garment_hair.HAIR_KIND)
            saved = inventory.unequip_mesh_piece(character_name, slot)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the character profile failed")
    return {"equipped": bool(body.equipped)}


@router.get("/{character_name}/outfit-options")
def get_character_outfit_options(character_name: str) -> Dict[str, Any]:
    """The per-outfit options (``app.core.outfit_options``, boots spec § 8.2, unified-worn-pieces Addendum A):
    ``{boot_hem, applicable, piece_state, closable}`` — ``boot_hem`` the stored choice (``tucked`` / ``over`` / null
    = over), ``applicable`` what the Wardrobe shows (``hem_applicable``: a worn boot and worn own-mesh trousers),
    ``piece_state`` the stored open map ``{item_id: "open"}``, ``closable`` the worn closable pieces
    ``[{item_id, name, state, names_state}]``. Character-scoped like the equip routes: admin and the character's
    player."""
    from app.core.outfit_options import BOOT_HEM_KEY, OPTIONS_KEY, hem_applicable
    from app.models.character import get_character_profile
    _require_character(character_name)
    profile = get_character_profile(character_name) or {}
    stored = (profile.get(OPTIONS_KEY) or {}).get(BOOT_HEM_KEY) if isinstance(profile.get(OPTIONS_KEY), dict) else None
    return {"boot_hem": stored, "applicable": hem_applicable(character_name, profile=profile),
            **_piece_state_payload(profile)}


def _piece_state_payload(profile: Dict[str, Any]) -> Dict[str, Any]:
    """``{piece_state, closable}`` of the outfit-options payload (see the GET)."""
    from app.core.outfit_options import OPTIONS_KEY, PIECE_STATE_KEY, clean_piece_state_map, closable_worn
    options = profile.get(OPTIONS_KEY) if isinstance(profile.get(OPTIONS_KEY), dict) else {}
    return {"piece_state": clean_piece_state_map(options.get(PIECE_STATE_KEY)), "closable": closable_worn(profile)}


@router.post("/{character_name}/outfit-options/piece-state")
def set_character_piece_state(character_name: str, body: PieceStateRequest) -> Dict[str, Any]:
    """Wear a closable piece open or closed: ``{item_id, state: "open" | "closed"}`` → 200 ``{piece_state,
    applicable}`` (the GET's shape, ``closable`` included); 400 with the reason for a bad state, an item that is not
    closable or not worn now. A worn-state change like an equip (plan 2026-11-12-unified-worn-pieces D-A5): history,
    SSE and the automatic Build through ``inventory._notify_outfit_changed``. Same rights as an equip."""
    from app.core.outfit_options import hem_applicable, set_piece_state
    from app.models import inventory
    from app.models.character import get_character_profile
    _require_character(character_name)
    item_id = str(body.item_id or "").strip()
    try:
        saved = set_piece_state(character_name, item_id, body.state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the character profile failed")
    inventory._notify_outfit_changed(character_name, "piece_state", action=str(body.state), item_ids=[item_id])
    profile = get_character_profile(character_name) or {}
    return {"applicable": hem_applicable(character_name, profile=profile), **_piece_state_payload(profile)}


@router.post("/{character_name}/outfit-options")
def set_character_outfit_options(character_name: str, body: OutfitOptionsRequest) -> Dict[str, Any]:
    """Store the boot hem for the worn outfit: ``{boot_hem: "tucked" | "over" | null}`` (null = the default,
    over) → 200 ``{boot_hem, applicable}``; 400 for another value. The served model is re-assembled (no GPU
    work: the trousers' layered fit is CPU). Same rights as an equip."""
    from app.core import garment_assembly
    from app.core.outfit_options import hem_applicable, normalise_hem, set_boot_hem
    from app.models.character import get_character_profile
    _require_character(character_name)
    try:
        mode = normalise_hem(body.boot_hem)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not set_boot_hem(character_name, mode):
        raise HTTPException(status_code=500, detail="Saving the character profile failed")
    garment_assembly.schedule(character_name)
    return {"boot_hem": mode, "applicable": hem_applicable(character_name, profile=get_character_profile(character_name) or {})}


@router.post("/{character_name}/garments/{item_id}/run", status_code=202)
def run_character_garment(character_name: str, item_id: str, body: GarmentRunRequest,
                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """(Re-)run a garment's chain in a worker thread: from the first missing
    step ("Run all"), or ONLY ``step`` (``force``: re-run it — only ``view``
    for an image step; ruling F13 d — the steps dialog's buttons), or with
    ``chain`` the chain FROM ``step`` (everything after it too: Re-render,
    the hair row's Regenerate). ``view`` (Ruling A33) runs that view of
    ``step`` alone, never a chain; 409 (nothing spent) while a view it needs
    is not accepted, unless ``prerequisites`` lets the run make them first
    (``garments.view_plan``). Footwear keeps the chain from ``step``: its
    step regenerate starts a new shoe source whose later steps do not exist
    yet. 400 for an unknown step/view, an item
    that is no garment of this character, or a character off the base-body
    pipeline. Never refused for a running run: the run is queued behind the
    character's running garment run (``garments.start_garment``) —
    ``{started, queued, position, behind}``. ``state`` (``open`` /
    ``closed``) builds that state's own mesh of a closable piece (the Figure
    tab's "Build the open mesh"); 400 for a state on a piece without one, or
    ``open`` for a piece not worn now. ``body`` (Ruling A50, with step ``fit``): the body shape the Re-fit fits
    on — the plain body's fit first when it is due, then the fit on that body (``garments.refit_on_body``); 400
    for a body that is not stored or a run that is not the fit alone."""
    from app.core import base_body, garments
    _require_character(character_name)
    try:
        garments.check_run(character_name, item_id, steps=body.step, view=body.view, state=body.state,
                           prerequisites=body.prerequisites)
        if base_body.current_base(character_name) is None:
            raise ValueError(f"{character_name} is not on the base-body pipeline")
        on = "" if body.body in (None, "", "plain") else str(body.body)
        return garments.start_garment(character_name, item_id, steps=body.step, view=body.view,
                                      force=body.force, state=body.state,
                                      only=bool(body.step) and (not body.chain or body.view is not None),
                                      prerequisites=body.prerequisites, body=on)
    except garments.PrerequisiteMissing as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{character_name}/garments/{item_id}/piece-views")
def set_character_garment_piece_view(character_name: str, item_id: str, body: PieceViewSourceRequest,
                                     _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Ruling A46, "Piece-only views from": store where the piece-only image of ``view`` of an own-mesh
    clothing piece comes from — ``auto``, ``generated`` (the image edit) or ``worn`` (the worn view minus the
    base view, no hub job) — on the ITEM (``garment_from_worn.set_choice``). Runs nothing: a view whose
    accepted image came from another source reads due, with its cut-out, the mesh and the fit after it.
    ``{piece_views}`` — ``garments.piece_views_info`` now (each view's source, reason and what is due).
    Admin-only. 404 for an item that is no clothing garment of the character, 400 for a bad view or choice."""
    from app.core import garment_from_worn, garments
    from app.core import garment_store as gs
    _require_character(character_name)
    try:
        _item_, kind = garments._item(character_name, item_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if kind != "clothing":
        raise HTTPException(status_code=404, detail="Only an own-mesh clothing piece has piece-only views")
    try:
        garment_from_worn.set_choice(character_name, item_id, body.view, body.choice)
        fsig = gs.garment_fsig(character_name, item_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"piece_views": garments.piece_views_info(character_name, item_id, fsig)}


@router.post("/{character_name}/garments/{item_id}/fit-settings")
def set_character_garment_fit_settings(character_name: str, item_id: str, body: GarmentFitSettingsRequest,
                                       _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Ruling A47 — the fit settings of an own-mesh clothing piece: ``sleeves_left`` / ``sleeves_right``
    (auto / generated / wider / fitted) and ``allowance`` (auto / 0 / 3 / 6 / 10, percent of width), stored on the
    character (``garment_fit_settings.set_fit_settings``). Runs nothing: a fit made with other settings reads due
    and the next run refits it on the CPU (no hub job). ``{fit_settings}`` — ``garments.fit_settings_info`` now.
    Admin-only. 404 for an item that is no clothing garment of the character, 400 for a bad value."""
    from app.core import base_body, garment_fit_settings, garments
    from app.core import garment_store as gs
    from app.models.character import get_character_profile
    _require_character(character_name)
    try:
        _item_, kind = garments._item(character_name, item_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if kind != "clothing":
        raise HTTPException(status_code=404, detail="Only an own-mesh clothing piece has fit settings")
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        saved = garment_fit_settings.set_fit_settings(character_name, item_id, changes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the character profile failed")
    profile = get_character_profile(character_name) or {}
    try:
        fsig = gs.garment_fsig(character_name, item_id, profile=profile)
    except ValueError:
        fsig = ""
    base = base_body.current_base(character_name, profile=profile) or ("", "")
    return {"fit_settings": garments.fit_settings_info(character_name, item_id, fsig, base[1], profile)}


def _fetch_garment_mesh_job(character_name: str, item_id: str, raw_job: str, *, footwear: bool) -> Dict[str, Any]:
    """The two mesh-job fetch routes (``garments.collect_mesh_job``). 200 for ``accepted`` / ``refused`` (the
    step's gate refused the delivered mesh: ``reasons``; an accepted mesh is kept untouched, ``kept: True`` —
    only without one is the refusal recorded like a run's) and ``queued`` / ``running``
    (nothing changed); 400 for an id that is no job id or an item that does not fit the route; 404 unknown
    job, 403 another gateway user's job, 409 a running step / a failed job / a missing input, 422 a rigged
    delivery, 502 a download or step failure."""
    from app.core import base_body, garments
    from app.core.model3d import normalize_job_id
    _require_character(character_name)
    job_id = normalize_job_id(raw_job)
    if not job_id:
        raise HTTPException(status_code=400, detail="Not a job id")
    try:
        res = garments.collect_mesh_job(character_name, item_id, job_id, footwear=footwear)
    except garments.StepBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (base_body.MissingInput, FileNotFoundError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    status = res.get("status")
    if status in ("accepted", "refused", "queued", "running"):
        res.pop("path", None)
        return res
    code = {"unknown": 404, "forbidden": 403, "failed": 409, "rig_mismatch": 422}.get(status, 502)
    raise HTTPException(status_code=code, detail=res.get("error") or f"job {job_id}: {status}")


@router.post("/{character_name}/garments/{item_id}/mesh/fetch")
def fetch_character_garment_mesh_job(character_name: str, item_id: str, body: GarmentMeshFetchRequest,
                                     _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Collect a FINISHED gateway mesh job by its id as the garment's mesh step (clothing: ``mesh``; hair has
    no mesh job) — for a mesh whose run outlived our own poll. The
    delivered mesh goes through the step's own prepare + gate and record (``collected_job``); nothing else
    runs (the next run reuses it and runs the fit). A running garment run of the character → 409.
    ``{status, step, fsig, job_id, record?, error?, progress?}`` (``_fetch_garment_mesh_job``)."""
    return _fetch_garment_mesh_job(character_name, item_id, body.job_id, footwear=False)


@router.post("/{character_name}/garments/{item_id}/cancel")
def cancel_character_garment(character_name: str, item_id: str,
                             _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Cancel the item's WAITING run(s) in the character's garment queue
    (hair and own-mesh pieces share it; ``garments.cancel_garment``): the
    runs behind move up, the item's queued mark ends. 409 when the item's
    run has already started (a running run is never cancelled), 404 when no
    run of the item waits. ``{item_id, cancelled, queue_running, queue}``."""
    from app.core import garments
    _require_character(character_name)
    try:
        return garments.cancel_garment(character_name, item_id)
    except garments.RunStarted as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{character_name}/garments/{item_id}/images/{step}/{view}")
def get_character_garment_image(character_name: str, item_id: str, step: str, view: str, request: Request,
                                attempt: int = 0, _: Dict[str, Any] = Depends(require_admin)):
    """One image of the garment's CURRENT fingerprint: the accepted final, or
    ``attempt`` 1..n. 400 for an unknown step/view/attempt, 404 for an item
    that is no garment of this character or an image that is not there."""
    from fastapi.responses import Response
    from app.core import garment_store as gs
    from app.core import garments
    from app.core.garment_images import ATTEMPTS
    if step not in gs.IMAGE_STEPS:
        raise HTTPException(status_code=400, detail=f"step must be one of {', '.join(gs.IMAGE_STEPS)}")
    if view not in gs.GARMENT_VIEWS:
        raise HTTPException(status_code=400, detail=f"view must be one of {', '.join(gs.GARMENT_VIEWS)}")
    if not 0 <= attempt <= ATTEMPTS:
        raise HTTPException(status_code=400, detail=f"attempt must be 0..{ATTEMPTS}")
    _require_character(character_name)
    try:
        path = garments.image_path(character_name, item_id, step, view, attempt)
    except ValueError:
        path = None
    if path is None or not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "image/png")


def _garment_mesh_args(character_name: str, item_id: str, which: str, attempt: int) -> None:
    """Shared checks of the Mesh row's 3D view routes (Ruling A48a): 400 for a bad ``which`` / ``attempt``, 404
    for an item id the item filter changes (``safe_item_id``) or an unknown character."""
    from app.core import garment_mesh, garment_mesh_view
    from app.models.inventory import safe_item_id
    if which not in garment_mesh_view.WHICH:
        raise HTTPException(status_code=400, detail=f"which must be one of {', '.join(garment_mesh_view.WHICH)}")
    if not 0 <= attempt <= garment_mesh.KEPT_MAX:
        raise HTTPException(status_code=400, detail=f"attempt must be 0..{garment_mesh.KEPT_MAX}")
    if safe_item_id(item_id) != item_id:
        raise HTTPException(status_code=404, detail="Unknown item")
    _require_character(character_name)


@router.get("/{character_name}/garments/{item_id}/mesh/{which}")
def get_character_garment_mesh(character_name: str, item_id: str, which: str, request: Request,
                               attempt: int = 0, _: Dict[str, Any] = Depends(require_admin)):
    """Ruling A48a: one mesh file of the piece's CURRENT fsig — ``prepared`` (the accepted decimated mesh) or
    ``raw`` (the generator output); ``attempt`` 1..n = that kept refused attempt's file
    (``garment_mesh_view.mesh_file``; Ruling A58: any kept mesh slot). Versioned by content (``snapshot_response``: ETag, 304, immutable with a
    matching ``v``). Admin-only. 400 for a bad which / attempt, 404 for a file that is not there or an item that
    is no garment of this character."""
    from app.core import garment_mesh_view
    from app.core.http_files import snapshot_response
    _garment_mesh_args(character_name, item_id, which, attempt)

    def resolve() -> Optional[Path]:
        try:
            return garment_mesh_view.mesh_file(character_name, item_id, which, attempt)
        except ValueError:
            return None
    return snapshot_response(None, request, media_type="model/gltf-binary",
                             version=request.query_params.get("v"), resolve=resolve)


@router.get("/{character_name}/garments/{item_id}/mesh/{which}/body")
def get_character_garment_mesh_body(character_name: str, item_id: str, which: str, request: Request,
                                    attempt: int = 0, _: Dict[str, Any] = Depends(require_admin)):
    """Ruling A48a: the body view of one mesh file (``garment_mesh_view.body_view``) — the share of its area
    inside the base body, the face counts and the placement — plus ``ghost_url`` (the base body as a ghost, in
    the mesh's frame) and ``inside_url`` (the faces inside the body at any allowance factor, Ruling A48c —
    ``allowance.mask`` says at which; None without any) and ``allowance`` (the axis the fit widens about and, per
    factor, the share inside and the trunk gap: ``garment_mesh_view.allowance_table``). Computed once per mesh
    and body and cached by content (``ETag`` = ``"<key>"``, 304 on a match). Admin-only. 400 for a bad which /
    attempt, 404 without the mesh, 409 with the plain reason when the body cannot be shown (no base model, no
    piece-only front view, a frame the fit refuses)."""
    from fastapi.responses import JSONResponse, Response
    from app.core import garment_mesh_view
    _garment_mesh_args(character_name, item_id, which, attempt)
    try:
        view = garment_mesh_view.body_view(character_name, item_id, which, attempt)
    except garment_mesh_view.ViewUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (LookupError, ValueError):
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    etag = f'"{view["key"]}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    base = (f"/characters/{quote(character_name, safe='')}/garments/{quote(item_id, safe='')}/mesh/{which}/body")
    extra = f"&attempt={attempt}" if attempt else ""
    return JSONResponse({**view, "ghost_url": f"{base}/ghost?v={view['key']}{extra}",
                         "inside_url": (f"{base}/inside?v={view['key']}{extra}"
                                        if (view.get("allowance") or {}).get("mask_faces") or view.get("inside_faces")
                                        else None)},
                        headers=headers)


@router.get("/{character_name}/garments/{item_id}/mesh/{which}/body/{overlay}")
def get_character_garment_mesh_overlay(character_name: str, item_id: str, which: str, overlay: str,
                                       request: Request, attempt: int = 0,
                                       _: Dict[str, Any] = Depends(require_admin)):
    """Ruling A48a: an overlay GLB of the body view — ``ghost`` (the base body in the mesh's frame) or ``inside``
    (the mesh's faces inside the body) — computed with the view when it is not cached
    (``garment_mesh_view.overlay_path``), versioned by content. Admin-only. 400 for a bad which / attempt /
    overlay, 404 when there is nothing to show."""
    from app.core import garment_mesh_view
    from app.core.http_files import snapshot_response
    if overlay not in garment_mesh_view.OVERLAYS:
        raise HTTPException(status_code=400, detail=f"overlay must be one of {', '.join(garment_mesh_view.OVERLAYS)}")
    _garment_mesh_args(character_name, item_id, which, attempt)

    def resolve() -> Optional[Path]:
        try:
            return garment_mesh_view.overlay_path(character_name, item_id, which, attempt, overlay)
        except (garment_mesh_view.ViewUnavailable, LookupError, ValueError):
            return None
    return snapshot_response(None, request, media_type="model/gltf-binary",
                             version=request.query_params.get("v"), resolve=resolve)


@router.post("/{character_name}/garments/{item_id}/mesh/attempts/{attempt}/use")
def use_character_garment_mesh(character_name: str, item_id: str, attempt: int,
                               _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Ruling A58, "Use this" on a kept mesh of the piece (slot ``attempt``: a refused attempt, an earlier mesh, a
    result that finished while another mesh was chosen): it becomes the piece's mesh and its fit starts on the CPU
    (``garments.use_mesh``) — no hub job. Allowed while the piece's mesh job runs (its result then stays a kept
    mesh). ``{item_id, n, user_accepted, during_job, fit}``. Admin-only. 400 for a bad slot, 404 for an item that is
    no clothing garment of this character, 409 when the slot holds no mesh or another step of the piece runs."""
    from app.core import garment_mesh, garments
    from app.models.inventory import safe_item_id
    if not 1 <= attempt <= garment_mesh.KEPT_MAX:
        raise HTTPException(status_code=400, detail=f"attempt must be 1..{garment_mesh.KEPT_MAX}")
    if safe_item_id(item_id) != item_id:
        raise HTTPException(status_code=404, detail="Unknown item")
    _require_character(character_name)
    try:
        return garments.use_mesh(character_name, item_id, attempt)
    except (garment_mesh.KeptUnusable, garments.UseBusy) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{character_name}/garments/{item_id}/images/{step}/{view}/attempts/{attempt}/use")
def use_character_garment_attempt(character_name: str, item_id: str, step: str, view: str, attempt: int,
                                  _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Ruling A37, "Use this": the stored ``attempt`` of ``view`` of the edit ``step`` becomes the view's accepted
    image — a refused one accepted by the user (``garments.use_attempt``). Spends no job; the view's later
    images and the mesh become due (``follow_up``: the chain's estimate now). Admin-only. 400 for a bad
    step / view / attempt, 409 when the attempt cannot be used or a garment run of the piece is in progress."""
    from app.core import garment_store as gs
    from app.core import garments
    from app.core.garment_images import ATTEMPTS, AttemptUnusable
    if step not in gs.IMAGE_STEPS:
        raise HTTPException(status_code=400, detail=f"step must be one of {', '.join(gs.IMAGE_STEPS)}")
    if view not in gs.GARMENT_VIEWS:
        raise HTTPException(status_code=400, detail=f"view must be one of {', '.join(gs.GARMENT_VIEWS)}")
    if not 1 <= attempt <= ATTEMPTS:
        raise HTTPException(status_code=400, detail=f"attempt must be 1..{ATTEMPTS}")
    _require_character(character_name)
    try:
        return garments.use_attempt(character_name, item_id, step, view, attempt)
    except (AttemptUnusable, garments.UseBusy) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{character_name}/garments/{item_id}/footwear/image/{which}")
def get_character_footwear_image(character_name: str, item_id: str, which: str, request: Request,
                                 attempt: int = 0, _: Dict[str, Any] = Depends(require_admin)):
    """One image of a footwear piece's SHOWN shoe source
    (``garment_footwear.image_path``): ``source`` (the item image),
    ``upscaled``, ``empty`` (``attempt`` 1..n = that edit attempt) or
    ``cutout``. 400 for another name or attempt, 404 for an item that is no
    footwear piece of this character or a file that is not there."""
    from fastapi.responses import Response
    from app.core import footwear_source, garment_footwear
    if which not in garment_footwear.IMAGES:
        raise HTTPException(status_code=400, detail=f"image must be one of {', '.join(garment_footwear.IMAGES)}")
    if not 0 <= attempt <= footwear_source.EMPTY_ATTEMPTS or (attempt and which != "empty"):
        raise HTTPException(status_code=400,
                            detail=f"attempt must be 0 (or 1..{footwear_source.EMPTY_ATTEMPTS} for the empty shoe)")
    _require_character(character_name)
    try:
        path = garment_footwear.image_path(character_name, item_id, which, attempt)
    except ValueError:
        path = None
    if path is None or not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _encoding = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "image/png")


@router.get("/{character_name}/garments/{item_id}/footwear/mesh")
def get_character_footwear_mesh(character_name: str, item_id: str, request: Request,
                                _: Dict[str, Any] = Depends(require_admin)):
    """The prepared shoe GLB of a footwear piece's SHOWN source
    (``garment_footwear.mesh_path``), versioned by content. 404 without one or
    for an item that is no footwear piece of this character."""
    from app.core import garment_footwear
    from app.core.http_files import snapshot_response
    _require_character(character_name)

    def resolve() -> Optional[Path]:
        try:
            return garment_footwear.mesh_path(character_name, item_id)
        except ValueError:
            return None
    return snapshot_response(None, request, media_type="model/gltf-binary",
                             version=request.query_params.get("v"), resolve=resolve)


@router.get("/{character_name}/garments/{item_id}/footwear/insole")
def get_character_footwear_insole(character_name: str, item_id: str, request: Request,
                                  _: Dict[str, Any] = Depends(require_admin)):
    """``insole.json`` of a footwear piece's SHOWN source
    (``garment_footwear.insole_path``). 404 without one or for an item that is
    no footwear piece of this character."""
    from fastapi.responses import Response
    from app.core import garment_footwear
    _require_character(character_name)
    try:
        path = garment_footwear.insole_path(character_name, item_id)
    except ValueError:
        path = None
    if path is None or not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "application/json")


@router.post("/{character_name}/garments/{item_id}/footwear/mesh/fetch")
def fetch_character_footwear_mesh_job(character_name: str, item_id: str, body: GarmentMeshFetchRequest,
                                      _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Collect a FINISHED gateway ``mesh_footwear`` job by its id as the ``mesh`` step of the footwear piece's
    shoe source (``footwear_source.collect_mesh_job``: the step's own decimation + gates and record, plus
    ``collected_job``; the insole and the fit run on the next run). A running step of the shoe source → 409.
    Answers like the garment route (``_fetch_garment_mesh_job``)."""
    return _fetch_garment_mesh_job(character_name, item_id, body.job_id, footwear=True)


@router.post("/{character_name}/garments/{item_id}/footwear/width-cap")
def set_character_footwear_width_cap(character_name: str, item_id: str, body: FootwearWidthCapRequest,
                                     _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Set the per-fit width cap of a footwear piece (``garment_footwear.set_width_cap``): a number in
    1.00..1.10, or null for the default 1.10. 400 for anything else or an item that is no footwear piece of
    this character. Only the fit fingerprint changes: the next run re-fits from the cached shoe source on the
    CPU (no run starts here). ``{item_id, width_cap, fsig}``."""
    from app.core import garment_footwear, garment_store as gs
    from app.models.character import get_character_profile
    _require_character(character_name)
    try:
        saved = garment_footwear.set_width_cap(character_name, item_id, body.cap)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not saved:
        raise HTTPException(status_code=500, detail="Saving the character profile failed")
    profile = get_character_profile(character_name) or {}
    return {"item_id": item_id, "width_cap": garment_footwear.width_cap(profile, item_id),
            "fsig": gs.garment_fsig(character_name, item_id, profile=profile)}


@router.get("/{character_name}/garments/{item_id}/hairdeck/{image}")
def get_character_garment_hairdeck_image(character_name: str, item_id: str, image: str, request: Request,
                                         _: Dict[str, Any] = Depends(require_admin)):
    """One HairDeck tile of the CURRENT hsig (``garments.hairdeck_image_path``):
    ``input`` (the profile picture), ``prep`` or ``model_input``. 400 for
    another name, 404 for an item that is no garment of this character or a
    file that is not there."""
    from fastapi.responses import Response
    from app.core import garments
    if image not in garments.HAIRDECK_IMAGES:
        raise HTTPException(status_code=400,
                            detail=f"image must be one of {', '.join(garments.HAIRDECK_IMAGES)}")
    _require_character(character_name)
    try:
        path = garments.hairdeck_image_path(character_name, item_id, image)
    except ValueError:
        path = None
    if path is None or not path.is_file():
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _encoding = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "image/png")


@router.get("/{character_name}/garments/{item_id}/haar/{seed}/tile.png")
def get_character_garment_haar_tile(character_name: str, item_id: str, seed: int, request: Request,
                                    _: Dict[str, Any] = Depends(require_admin)):
    """The tile of HAAR seed ``seed`` under the hairstyle's CURRENT ssig (``garments.haar_tile_path``: front | back
    of the fitted cards on the bald head, rendered on the CPU at fit time), with an ETag. 404 for an item that is
    no hair of this character or a seed without a tile."""
    from fastapi.responses import Response
    from app.core import garments
    _require_character(character_name)
    try:
        path = garments.haar_tile_path(character_name, item_id, seed)
    except ValueError:
        path = None
    if path is None:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(path, request, "image/png")


@router.get("/{character_name}/garments/{item_id}/model")
def get_character_garment_model(character_name: str, item_id: str, request: Request, method: str = "",
                                _: Dict[str, Any] = Depends(require_admin)):
    """The hair preview GLB (the rigged base with the garment grafted
    on, ``garments.preview_path``), versioned by content; ``method`` naming
    the method NOT selected = that method's newest accepted fit (the "Other
    method" preview). A HairDeck fit carries its strand binding
    (``hair_strands.preview_glb``, Ruling H-R5), versioned
    ``hair_strands.preview_version``: ``ETag`` = ``"<version>"``, 304 on a
    match (nothing is built), immutable when ``v`` names it. 400 for an
    unknown method; 404 without a fit or for an item that is no garment of
    this character."""
    from fastapi.responses import Response
    from app.core import garments, hair_strands
    from app.core.garment_hair import HAIR_MODES
    if method and method not in HAIR_MODES:
        raise HTTPException(status_code=400, detail=f"method must be one of {', '.join(HAIR_MODES)}")
    _require_character(character_name)
    fit = garments.preview_path(character_name, item_id, method)
    try:
        version = hair_strands.preview_version(fit) if fit is not None else ""
    except OSError:
        version = ""
    if not version:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    asked = request.query_params.get("v")
    if etag_matches(request.headers.get("if-none-match"), f'"{version}"'):
        cache = "public, max-age=31536000, immutable" if asked == version else "no-cache"
        return Response(status_code=304, headers={"ETag": f'"{version}"', "Cache-Control": cache})
    built = hair_strands.preview_glb(character_name, fit)
    if built is None:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    data, version = built
    cache = "public, max-age=31536000, immutable" if asked == version else "no-cache"
    return Response(content=data, media_type="model/gltf-binary",
                    headers={"ETag": f'"{version}"', "Cache-Control": cache})


@router.get("/{character_name}/garments/{item_id}/hair-strands")
def get_character_garment_hair_strands(character_name: str, item_id: str, request: Request,
                                       _: Dict[str, Any] = Depends(require_admin)):
    """The strand record of the Hairstyles preview's fit (``garments.preview_path``; built on the CPU when it is
    missing, ``hair_strands.record_for_fit``), regardless of Swing — the preview's own switch. ``ETag`` =
    ``"<sha256>"``, 304 on a match; 404 without a preview fit or a record (no HairDeck fit)."""
    import hashlib
    from app.core import garments, hair_strands
    _require_character(character_name)
    fit = garments.preview_path(character_name, item_id)
    record = hair_strands.record_for_fit(character_name, fit) if fit is not None else None
    if record is None:
        return _strands_response(request, None, "")
    data = hair_strands.encode(record)
    return _strands_response(request, data, hashlib.sha256(data).hexdigest())


def _fit_bodies(character_name: str, item_id: str, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    from app.core import fit_attempts
    try:
        return fit_attempts.bodies(character_name, item_id, profile=profile)
    except Exception:  # noqa: BLE001 — the panel shows without its body switch
        logger.exception("Fit bodies of %s/%s failed", character_name, item_id)
        return []


@router.get("/{character_name}/garments/{item_id}/fits/{body}/model")
def get_character_garment_fit_model(character_name: str, item_id: str, body: str, request: Request,
                                    _: Dict[str, Any] = Depends(require_admin)):
    """The Details preview's model of one body (Ruling A31, ``fit_attempts.shown_file``): ``body`` "plain" or an
    outfit body id — the body's kept refused attempt with the refusing gate's region marked, or its fit — or an
    outfit body id + ``-derived`` (its refused derived shoe, Ruling A40). 400 for a bad body, 404 when the body
    shows nothing."""
    from fastapi.responses import Response
    from app.core import fit_attempts
    from app.core.http_files import etag_matches, snapshot_response
    _require_character(character_name)
    try:
        shown = fit_attempts.shown_file(character_name, item_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if shown is None:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    path, marks = shown
    if marks is None:
        return snapshot_response(path, request, media_type="model/gltf-binary",
                                 version=request.query_params.get("v"))
    try:
        st, mst = path.stat(), marks.stat()
    except OSError:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    etag = f'"a31-{st.st_size:x}-{st.st_mtime_ns:x}-{mst.st_size:x}-{mst.st_mtime_ns:x}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=fit_attempts.marked_glb(path, marks, item_id), media_type="model/gltf-binary",
                    headers=headers)


def _fit_accept_call(fn, character_name: str, item_id: str, body: str) -> Dict[str, Any]:
    from app.core import fit_attempts
    _require_character(character_name)
    try:
        key, slot = fit_attempts.parse_key(body)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid body {body[:40]!r}")
    try:
        if fn is fit_attempts.accept:
            return fn(character_name, item_id, key, slot=slot)
        return fn(character_name, item_id, key)
    except fit_attempts.Busy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except fit_attempts.AcceptError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{character_name}/garments/{item_id}/fits/{body}/accept")
def accept_character_garment_fit(character_name: str, item_id: str, body: str,
                                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Ruling A31: accept the REFUSED fit of a clothing or footwear piece on one body ("plain", an outfit body
    id, or an outfit body id + ``-derived``: its refused derived shoe, Ruling A40) — ``fit_attempts.accept``. Spends no job; the figure becomes due for a re-assembly (CPU only), which this
    does not start (``follow_up``: the Build's estimate now). 409 when there is no current refused attempt to
    accept or a garment run holds the plain body's fits."""
    from app.core import fit_attempts
    return _fit_accept_call(fit_attempts.accept, character_name, item_id, body)


@router.post("/{character_name}/garments/{item_id}/fits/{body}/unaccept")
def unaccept_character_garment_fit(character_name: str, item_id: str, body: str,
                                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Ruling A31: undo the user's acceptance of a piece's fit on one body (``fit_attempts.undo``) — the
    refusal is back; the figure becomes due for a re-assembly (CPU only). 409 when none holds there."""
    from app.core import fit_attempts
    return _fit_accept_call(fit_attempts.undo, character_name, item_id, body)


# --- Generated 3D model (img2mesh from the T-pose render, per outfit) ---

@router.get("/{character_name}/animations")
def get_character_animations(character_name: str, pose: str = "") -> Dict[str, Any]:
    """Return played and public clips for this character's movement and activity."""
    from app.core.movement import character_animations
    return character_animations(character_name, pose)


@router.get("/{character_name}/model3d")
def get_character_model3d(character_name: str, request: Request, preview_states: Optional[str] = None) -> Dict[str, Any]:
    """Status of the generated mesh for the CURRENT outfit combination
    ({signature, has_input, model, pending}) + the character's animation set
    (explicit or derived), so the preview can offer the matching clips.
    ``model`` carries ``freshness`` and — for an outfit model on the
    base-body pipeline — its ``steps`` (``model_overview.annotate_model3d_info``);
    ``pipeline`` is ``model3d_pipeline.pipeline_state`` (None off it)."""
    from app.core.animation_sets import derive_set, resolve_sets
    from app.core.model3d import get_model3d_info
    selected = None
    if preview_states is not None:
        require_admin(request)
        selected = [] if preview_states == "none" else [value.strip() for value in preview_states.split(",") if value.strip()]
    from app.core.model_overview import annotate_model3d_info
    from app.core.model3d_pipeline import annotate as annotate_pipeline
    info = annotate_model3d_info(character_name, get_model3d_info(character_name, preview_states=selected))
    # ``pipeline``: what the tab's actions mean on the base-body pipeline.
    info = annotate_pipeline(character_name, info)
    # The face cleanup of the source the face acts on (the base body's on the
    # pipeline): state + what "Re-apply face cleanup" costs.
    try:
        from app.core.model3d import face_cleanup_signature, face_cleanup_state
        signature = face_cleanup_signature(character_name, (info.get("model") or {}).get("signature") or "")
        info["face_cleanup"] = face_cleanup_state(character_name, signature) if signature else None
    except Exception:  # noqa: BLE001 — the status read never fails on it
        logger.exception("Face cleanup state of %s failed", character_name)
        info["face_cleanup"] = None
    chain = resolve_sets(character_name)
    info["animation_set"] = chain[0] if chain else ""
    info["animation_sets"] = chain          # explicit first, then derived
    info["animation_set_derived"] = derive_set(character_name)
    return info


@router.post("/{character_name}/model3d/upload")
async def upload_character_model3d(character_name: str, request: Request) -> Dict[str, Any]:
    """Uploads a model AS the current outfit's model — replacing whatever is
    there (generated or a previous upload). Same two shapes as before,
    validated on the way in (app/core/model_validate.py):
      * ``file``=<name>.glb — humanoid: 52-joint Mixamo rig + embedded texture.
      * ``file``=<name>.fbx + ``texture``=<name>.png — generic FBX + basecolor.
    ``force=1`` stores despite validation errors; ``rig`` overrides the label.
    409 on the base-body pipeline (``model3d_pipeline.refusal``): its outfit
    model is built from the base body.
    """
    try:
        from app.core.model_validate import validate_fbx, validate_glb
        from app.core.model3d import save_uploaded_model
        # Model + texture together, so twice the ceiling is the honest bound.
        guard_content_length(request, max_bytes=2 * MODEL_UPLOAD_MAX_BYTES,
                             what="Character model")
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="No file uploaded")
        filename = (file.filename or "").lower()
        if not filename.endswith((".glb", ".fbx")):
            raise HTTPException(status_code=400,
                                detail="Format not supported (GLB or FBX + PNG)")
        if not get_character_dir(character_name).exists():
            raise HTTPException(status_code=404, detail="Character not found")
        from app.core.model3d_pipeline import refusal
        refused = refusal(character_name, "Uploading a model")
        if refused:
            raise HTTPException(status_code=409, detail=refused)

        contents = await read_upload_capped(
            file, max_bytes=MODEL_UPLOAD_MAX_BYTES, what="Character model")
        tex_file = form.get("texture")
        texture = await read_upload_capped(
            tex_file, max_bytes=MODEL_UPLOAD_MAX_BYTES,
            what="Model texture") if tex_file else None

        if filename.endswith(".glb"):
            from app.core.extension_rig import extension_bone_names
            result = validate_glb(contents, extension_names=extension_bone_names(character_name))
            texture = None  # a GLB carries its textures inside
        else:
            result = validate_fbx(contents, texture)
        force = str(form.get("force") or "").strip().lower() in ("1", "true", "yes")
        if not result["ok"] and not force:
            raise HTTPException(status_code=422, detail={
                "reason": "invalid_model",
                "errors": result["errors"],
                "warnings": result["warnings"],
                "joint_count": result.get("joint_count", 0),
            })
        rig = str(form.get("rig") or result["rig"]).strip().lower()
        if rig not in MODEL_RIG_VALUES:
            raise HTTPException(status_code=400,
                                detail="rig must be one of: " + "|".join(MODEL_RIG_VALUES))
        import asyncio
        meta = await asyncio.to_thread(save_uploaded_model, character_name, file.filename,
                                       contents, rig=rig, texture=texture)
        if meta.get("ok") is False:
            raise HTTPException(status_code=409, detail=meta.get("error") or "Model publication conflict")
        return {"status": "success", **meta,
                "warnings": result["warnings"],
                "joint_count": result.get("joint_count", 0)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/model3d/rig")
async def set_character_model3d_rig(character_name: str, request: Request) -> Dict[str, Any]:
    """Updates the rig of the current outfit's model (mixamo|generic).
    409 on the base-body pipeline (its outfit models carry the base's rig)."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_set_character_model3d_rig_sync,
                                   character_name, body)


def _set_character_model3d_rig_sync(character_name: str,
                                    body: Any) -> Dict[str, Any]:
    """The blocking body of ``set_character_model3d_rig`` — runs in the
    threadpool."""
    from app.core.model3d import set_model3d_rig
    from app.core.model3d_pipeline import refusal
    refused = refusal(character_name, "Changing the rig label")
    if refused:
        raise HTTPException(status_code=409, detail=refused)
    rig = str(body.get("rig") or "").strip().lower()
    if rig not in MODEL_RIG_VALUES:
        raise HTTPException(status_code=400,
                            detail="rig must be one of: " + "|".join(MODEL_RIG_VALUES))
    meta = set_model3d_rig(character_name, rig)
    if not meta:
        raise HTTPException(status_code=404, detail="No model")
    return meta


@router.post("/{character_name}/model3d/measure")
def measure_character_model3d(character_name: str,
                              force: bool = False) -> Dict[str, Any]:
    """Measures the served model with Blender and caches it in the sidecar.

    Reads only — the mesh is never modified. Generated and uploaded models are
    measured on arrival, so this is for stored models from before, or after a
    change that kept the file size identical (``force``).
    """
    from app.core.model3d import measure_model
    res = measure_model(character_name, force=force)
    if not res.get("ok"):
        err = res.get("error", "")
        raise HTTPException(status_code=404 if err == "no_model" else 503,
                            detail=err or "measurement failed")
    return res


@router.post("/{character_name}/model3d/diagnose")
def diagnose_character_model3d(character_name: str,
                               force: bool = False) -> Dict[str, Any]:
    """Runs the geometry-defect indicators over the served model and caches
    them in the sidecar. Reads only, and DISPLAY only: the suspect verdict
    needs all three markers together and is calibrated on one known case —
    the panel shows the finding, nothing acts on it.
    """
    from app.core.model3d import diagnose_model
    res = diagnose_model(character_name, force=force)
    if not res.get("ok"):
        err = res.get("error", "")
        raise HTTPException(status_code=404 if err == "no_model" else 503,
                            detail=err or "diagnosis failed")
    return res


@router.post("/{character_name}/model3d/lod")
def build_character_model3d_lod(character_name: str,
                                ratio: float = 0) -> Dict[str, Any]:
    """Builds the reduced (``low``) mesh of the served outfit combination.

    ``ratio`` is the target fraction of the triangle count. It is explicit
    because how far a model can be reduced before it shows depends on the
    model — measured so far: props take 0.25 well, room dioramas want 0.5.
    """
    from app.blender.refine import lod_ratio
    from app.core.model3d import build_lod
    ratio = ratio or lod_ratio("character")
    if not 0.02 <= ratio < 1:
        raise HTTPException(status_code=400,
                            detail="ratio must be between 0.02 and 1")
    res = build_lod(character_name, ratio=ratio)
    if not res.get("ok"):
        err = res.get("error", "")
        raise HTTPException(status_code=404 if err == "no_model" else 503,
                            detail=err or "LOD build failed")
    return res


@router.post("/{character_name}/model3d/retexture")
def retexture_character_model3d(character_name: str) -> Dict[str, Any]:
    """Re-encodes the stored model's textures to JPEG (geometry untouched).

    New models go through this on arrival; this is for what was stored before.
    The result replaces the file only if it is smaller AND passes the same
    validation a fresh delivery faces — otherwise the original stays and the
    reason is returned.
    """
    from app.core.model3d import retexture_model
    res = retexture_model(character_name)
    if not res.get("ok"):
        err = res.get("error", "")
        raise HTTPException(status_code=404 if err == "no_model" else 503,
                            detail=err or "re-encode failed")
    return res


@router.post("/{character_name}/model3d/generate")
def generate_character_model3d(character_name: str, request: Request, force: bool = False,
                               backend: str = "", face_num: int = 0,
                               texture_size: int = 0) -> Any:
    """Starts the mesh generation for the current outfit (T-pose render as
    input). ``backend`` picks the mesh backend (empty = the rig's mesh
    occasion chain of the image routing);
    ``face_num``/``texture_size`` override the backend defaults for THIS run
    (0 = default; texture size reaches the gateway once its alias declares
    the param). Cached per combination — ``force=1`` re-generates.

    Base-body pipeline (Ruling FR-I4): the character's Build, exactly as
    ``POST /characters/{c}/figure/build`` (``figure.start_manual_build``):
    admin only, 202 ``{"status": "started" | "queued" | "current"}``, 409
    while a base-body step runs, 503 when the profile could not be read —
    the Build's lock, plan and estimate, never a cascade of its own. A
    ``backend``/``face_num``/``texture_size`` is a 400 (no mesh backend
    applies)."""
    from app.core.model3d import trigger_generation
    from app.core.model_refs import find_ref_image
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    from app.core import figure_build, model3d_pipeline
    if figure_build.on_pipeline(character_name):
        require_admin(request)
        if (backend or "").strip() or face_num or texture_size:
            raise HTTPException(status_code=400, detail=model3d_pipeline.NO_BACKEND)
        from fastapi.responses import JSONResponse
        from app.routes.figure import start_manual_build
        return JSONResponse(status_code=202, content=start_manual_build(character_name))
    if not find_ref_image(character_name, "tpose"):
        raise HTTPException(
            status_code=409,
            detail="No pose render for the current outfit — generate it first")
    if (backend or "").strip():
        # The rig check stays in generate_mesh (the rig is known there).
        require_explicit_backend(backend.strip(), media="mesh")
    if not trigger_generation(character_name, force=force,
                              backend_glob=(backend or "").strip(),
                              face_num=face_num or None,
                              texture_size=texture_size or None):
        return {"status": "already_running"}
    return {"status": "generating"}


@router.post("/{character_name}/model3d/rerig")
def rerig_character_model3d(
        character_name: str, signature: str = "", backend: str = "",
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Start a tracked rig-only rebuild of the served or selected source.

    Base-body pipeline: the BASE body is re-rigged whatever ``signature``
    says — an outfit model has no unrigged source of its own; the re-rigged
    base marks every outfit model stale (rebuilt on its next trigger)."""
    from app.core.model3d import (find_model3d_serving, get_model3d_dir,
                                  required_rig, trigger_rerig)
    from app.imagegen.occasions import backend_fits
    from app.imagegen.routing import describe_backend
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    from app.core.model3d_pipeline import pipeline_state
    pipeline = pipeline_state(character_name)
    if pipeline is not None:
        signature = pipeline["base_signature"]
        if not pipeline["rerig_source"]:
            raise HTTPException(409, "The base body has no retained unrigged mesh. "
                                     "Generate the base model again (Base body tab).")
    if not signature:
        served = find_model3d_serving(character_name)[0]
        signature = served.stem if served else ""
    if not signature:
        raise HTTPException(409, "No retained unrigged mesh source. Generate a new model to enable re-rigging.")
    if any(c in signature for c in ("/", "\\", "\x00")) or signature in (".", ".."):
        raise HTTPException(400, "Invalid model signature")
    if not (get_model3d_dir(character_name) / "unrigged" / f"{signature}.glb").is_file():
        raise HTTPException(409, "No retained unrigged mesh source. Generate a new model to enable re-rigging.")
    pick = (backend or "").strip()
    if pick:
        selected = require_explicit_backend(pick, media="mesh")
        occasion = {"mixamo": "rig_humanoid", "generic": "rig_creature"}.get(required_rig(character_name))
        if not occasion or not backend_fits(occasion, describe_backend(selected)):
            raise HTTPException(400, "Selected backend has the wrong category — no automatic fallback")
        pick = selected.name
    return trigger_rerig(character_name, signature, backend_glob=pick)


@router.post("/{character_name}/model3d/face-cleanup")
def reapply_character_face_cleanup(
        character_name: str, signature: str = "",
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Re-apply the face cleanup to the STORED mesh (``model3d.trigger_face_cleanup``):
    clean the retained unrigged source in place, then rebuild what follows it
    (face retexture + rig, or a re-rig). On the base-body pipeline it acts on
    the base body whatever ``signature`` says. 409 when the state refuses it
    (switch off, already applied, no source, not humanoid) or the follow-up
    cannot run (``detail`` names why)."""
    from app.core.model3d import face_cleanup_signature, trigger_face_cleanup
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    if any(c in signature for c in ("/", "\\", "\x00")) or signature in (".", ".."):
        raise HTTPException(400, "Invalid model signature")
    target = face_cleanup_signature(character_name, signature)
    if not target:
        raise HTTPException(409, "No retained unrigged mesh — generate the model again.")
    try:
        return trigger_face_cleanup(character_name, target)
    except (ValueError, LookupError) as exc:
        raise HTTPException(409, str(exc)) from exc


def _face_retexture_signature(character_name: str, signature: str) -> str:
    """Resolve a selected outfit key and reject path/glob input.

    On the base-body pipeline the face belongs to the base body: every
    outfit model is painted onto it and has no unrigged source of its own,
    so dialog, preview, start, revert and comparison act on the BASE
    signature whatever was selected. A re-rigged base changes its model
    bytes, which marks every outfit model stale (``base_model_sha256``) —
    they are rebuilt on their next trigger."""
    from app.core.base_body import base_signature, is_base_pipeline
    from app.core.face_retexture import safe_signature
    from app.core.model_refs import current_outfit_state
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    try:
        if is_base_pipeline(character_name):
            return safe_signature(base_signature(character_name))
        return safe_signature(signature or current_outfit_state(character_name)[2])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _face_retexture_localize(value: dict, lang: str) -> dict:
    from app.core.i18n import t
    result = dict(value)
    for key in ("problems", "warnings"):
        if key in result:
            result[key] = [{**p, **{field: t(p[field], lang) for field in ("message", "fix") if field in p}}
                           for p in result[key]]
    if result.get("face_problem"):
        result["face_problem"] = {**result["face_problem"], **{
            key: t(result["face_problem"][key], lang) for key in ("message", "fix")}}
    if "error" in result:
        result["error"] = t(result["error"], lang)
    return result


@router.get("/{character_name}/model3d/face-retexture/check")
def check_character_face_retexture(character_name: str, signature: str = "",
                                   backend: str = "", lang: str = "en", reference: str = Query("", pattern="^(face|front)?$"),
                                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Keep permanent eligibility and temporary routing readiness distinct."""
    from app.core import face_retexture
    from app.core.keyed_lock import keyed_lock
    signature = _face_retexture_signature(character_name, signature)
    root = get_character_dir(character_name) / "model3d"
    with keyed_lock("model3d_publication", str(root)):
        eligibility = face_retexture.check(character_name, signature, reference)
        snapshot = face_retexture.snapshot_info(root, signature)
    ready = face_retexture.runnable(character_name, backend)
    return {**_face_retexture_localize(eligibility, lang), "signature": signature,
            "runnable": ready["ok"],
            "photo_controls": "hub" if face_retexture.photo_controls_supported(character_name, backend) else "local",
            "skin_recolor_supported": face_retexture.skin_recolor_supported(character_name, backend),
            "runnable_problems": _face_retexture_localize(ready, lang)["problems"],
            "snapshot": _face_retexture_localize(snapshot, lang)}


@router.get("/{character_name}/model3d/face-photo-preview")
def preview_character_face_photo(character_name: str, signature: str = "",
                                 reference: str = Query("face", pattern="^(face|front)$"),
                                 balance: float = Query(0, ge=0, le=1),
                                 brightness: float = Query(1, ge=0.5, le=1.5),
                                 _: Dict[str, Any] = Depends(require_admin), backend: str = ""):
    """Preview certified source bytes without taking the render lock."""
    import io
    from PIL import Image
    from fastapi.responses import Response
    from app.core import face_retexture
    from app.core.face_photo_adjust import validated_params, PROBLEM
    from app.core.keyed_lock import keyed_lock
    # keyed_lock keeps its entries: never allocate one for an unknown name.
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    with keyed_lock('face_photo_preview', character_name):
        signature = _face_retexture_signature(character_name, signature)
        snapshot = {}
        eligibility = face_retexture.check(character_name, signature, reference, _snapshot=snapshot)
        if not eligibility['ok']:
            raise HTTPException(409, '; '.join(p['message'] for p in eligibility['problems']))
        try:
            photo = validated_params({'balance': balance, 'brightness': brightness})
            hub = face_retexture.photo_controls_supported(character_name, backend)
            preview_reason = ''
            if hub:
                # Tone match requires the mesh. Local balance is only an
                # approximation and cannot handle a full front/opaque source.
                if reference == 'front':
                    photo['balance'] = 0.
                    preview_reason = 'Brightness-only approximation; light balance and tone match run on the hub.'
            elif reference == 'front' and balance:
                raise ValueError(PROBLEM)
            try:
                raw = face_retexture.flatten_photo(snapshot['rgba'], photo, max_size=512)
            except ValueError as exc:
                if not hub or str(exc) != PROBLEM:
                    raise
                photo['balance'] = 0.
                preview_reason = 'Brightness-only approximation; light balance and tone match run on the hub.'
                raw = face_retexture.flatten_photo(snapshot['rgba'], photo, max_size=512)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        image = Image.open(io.BytesIO(raw))
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, 'PNG')
        return Response(output.getvalue(), media_type='image/png', headers={
            'Cache-Control': 'no-store', **({'X-Face-Photo-Preview': preview_reason} if preview_reason else {})})

@router.post("/{character_name}/model3d/face-retexture")
def start_character_face_retexture(character_name: str, signature: str = "",
                                   backend: str = "", strength: float = Query(1, ge=0, le=1),
                                   feather: float = Query(0.18, ge=0, le=0.5),
                                   render_resolution: int = Query(768, ge=256, le=2048),
                                   balance: float = Query(1, ge=0, le=1),
                                   tone_match: float = Query(1, ge=0, le=1),
                                   skin_recolor: float = 1.,
                                   brightness: float = Query(1, ge=0.5, le=1.5),
                                   yaw: float = Query(0, ge=-180, le=180), lang: str = "en",
                                   upscale: Optional[bool] = None, upscale_backend: str = "",
                                   reference: str = Query("", pattern="^(face|front)?$"),
                                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Validate the preflight, then start a tracked correction job."""
    from app.core import face_retexture
    from app.core.model3d import trigger_face_retexture
    signature = _face_retexture_signature(character_name, signature)
    controls = {"strength": strength, "feather": feather,
                "render_resolution": render_resolution, "yaw": yaw}
    try:
        face_retexture.validated_params(controls)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    snapshot = {}
    eligibility = face_retexture.check(character_name, signature, reference, _snapshot=snapshot)
    ready = face_retexture.runnable(character_name, backend)
    if not eligibility["ok"] or not ready["ok"]:
        return _face_retexture_localize({"ok": False, "problems": eligibility["problems"] + ready["problems"]}, lang)
    from app.core.face_photo_adjust import validated_params as photo_params, PROBLEM, FIX
    try:
        photo = photo_params({'balance': balance, 'tone_match': tone_match, 'skin_recolor': skin_recolor, 'brightness': brightness})
        hub = face_retexture.photo_controls_supported(character_name, backend)
        if not hub and eligibility['reference'] == 'front' and balance:
            raise ValueError(PROBLEM)
        face_retexture.flatten_photo(snapshot['rgba'], None if hub else photo)
    except ValueError as exc:
        return _face_retexture_localize({'ok': False, 'problems': [
            {'code': 'face_photo', 'message': str(exc), 'fix': FIX}]}, lang)
    upscale = face_retexture.use_upscale(eligibility["reference"], upscale)
    if upscale and upscale_backend:
        from app.core.upscale_reference import require_upscale_backend
        try:
            upscale_backend = require_upscale_backend(upscale_backend, character_name).name
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
    return trigger_face_retexture(character_name, signature, backend_glob=backend, params=controls,
                                  photo=photo,
                                  upscale=upscale, reference=eligibility["reference"], upscale_backend_glob=upscale_backend)


@router.post("/{character_name}/model3d/face-retexture/revert")
def revert_character_face_retexture(character_name: str, signature: str = "", lang: str = "en",
                                    _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Restore a snapshot or re-rig the original, serialized against character jobs."""
    from app.core.model3d import revert_face_retexture, _char_lock, _generating, _lock
    signature = _face_retexture_signature(character_name, signature)
    with _lock:
        if character_name in _generating:
            raise HTTPException(409, "A model job is already running")
        _generating.add(character_name, "Face retexture revert")
    try:
        with _char_lock(character_name):
            result = revert_face_retexture(character_name, signature)
        if result.get("ok"):
            from app.core.model3d import after_base_face_change
            after_base_face_change(character_name, signature)
        return _face_retexture_localize(result, lang)
    finally:
        with _lock:
            _generating.discard(character_name)


@router.get("/{character_name}/model3d/face-retexture/compare")
def compare_character_face_retexture(character_name: str, request: Request, signature: str = "",
                                     _: Dict[str, Any] = Depends(require_admin)):
    """Serve the diagnostic image with the same publication lock as models."""
    from app.core.keyed_lock import keyed_lock
    signature = _face_retexture_signature(character_name, signature)
    root = get_character_dir(character_name) / "model3d"
    path = root / "facefix" / f"{signature}.png"
    with keyed_lock("model3d_publication", str(root)):
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise HTTPException(404, "Comparison image not found")
        from fastapi.responses import Response
        stat = path.stat()
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}-{stat.st_ino:x}"'
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        contents = path.read_bytes()
    return Response(contents, media_type="image/png", headers=headers)


@router.post("/{character_name}/model3d/fetch-job")
def fetch_character_model3d_job(character_name: str, job: str = "",
                                force: bool = False,
                                _: Dict[str, Any] = Depends(require_admin)
                                ) -> Dict[str, Any]:
    """Collects a finished gateway mesh job by its full id
    ("f3acdaed52ef428e881a51a9fadfd4bd", optionally prefixed with "Job ")
    or a unique prefix of at least 8 hex characters (e.g. "f3acdaed52ef",
    as shown on the gateway admin page) and stores it as the model of the
    current outfit — for a generation that outlived our own poll.
    A job that is not finished yet answers
    ``{"status": "queued"|"running", "progress"}`` and changes nothing;
    ``force=1`` stores a result that fails the model check. 409 on the
    base-body pipeline (``model3d_pipeline.refusal``)."""
    from app.core.model3d import fetch_job_for_current_outfit, normalize_job_id
    from app.core.model3d_pipeline import refusal
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    refused = refusal(character_name, "Fetching a mesh job")
    if refused:
        raise HTTPException(status_code=409, detail=refused)
    job_id = normalize_job_id(job)
    if not job_id:
        raise HTTPException(status_code=400, detail="Not a job id")
    res = fetch_job_for_current_outfit(character_name, job_id,
                                       force=force)
    status = res.get("status")
    if status in ("stored", "queued", "running"):
        return res
    if status == "invalid":
        raise HTTPException(status_code=422, detail={
            "reason": "invalid_model",
            "errors": res.get("errors") or [],
            "warnings": res.get("warnings") or [],
        })
    code = {"unknown": 404, "forbidden": 403, "busy": 409, "failed": 409,
            "rig_mismatch": 422}.get(status, 502)
    raise HTTPException(status_code=code,
                        detail=res.get("error") or f"job {job_id}: {status}")


@router.post("/{character_name}/model3d/extension-rig")
def rebuild_character_model3d_extension_rig(
        character_name: str, signature: str = "", tier: str = "full",
        force: bool = False,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Rebuild the selected tier from its clean source.

    Successful matching fingerprints are no-ops; force retries failed attempts.
    """
    from app.core.model3d import rebuild_extension_rig, get_model3d_info
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    if tier not in ("full", "low"):
        raise HTTPException(400, "tier must be full or low")
    signature = signature or (get_model3d_info(character_name).get("model") or {}).get("signature", "")
    if not signature:
        raise HTTPException(404, "No model")
    if any(char in signature for char in ("/", "\\", "\x00")) or signature in (".", ".."):
        raise HTTPException(400, "Invalid model signature")
    try:
        return rebuild_extension_rig(character_name, signature, tier=tier, force=force)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class ExtensionTipRequest(BaseModel):
    signature: str
    group: str
    tip: Optional[Dict[str, Any]] = None
    #: Given → only the group's per-model switch changes, the tip stays.
    enabled: Optional[bool] = None


@router.post("/{character_name}/model3d/extension-tip")
def save_character_model3d_extension_tip(character_name: str, body: ExtensionTipRequest,
                                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Store a ``pair_tip`` group's tip override on one stored model
    (``tip``: offsets per side, mirror, colour disc — None resets it; see
    ``extension_rig.validate_tip_override``) — or, with ``enabled`` given,
    only the group's per-model on/off switch (the 3D tab's, tip kept; off
    builds no tip bone, stub or disc). Saves ONLY (Task UI2, rule R3): nothing
    is rebuilt — ``{tip, due}``, ``due`` True when the model's extension rig
    is now older than its settings (``POST …/extension-tip/apply`` or the Base
    body tab's "Run all" rebuilds it). 400 for a malformed value or a group
    the model does not carry, 409 while a tip rebuild of the character runs."""
    from app.core import extension_tip
    from app.core.face_retexture import safe_signature
    from app.core.model3d import extension_settings_changed, find_model3d
    _require_character(character_name)
    try:
        signature = safe_signature(body.signature)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        if body.enabled is not None:
            stored = extension_tip.save_tip_override(character_name, signature, body.group, enabled=body.enabled)
        else:
            stored = extension_tip.save_tip_override(character_name, signature, body.group, body.tip)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        status = 409 if str(exc) == extension_tip.REBUILD_RUNNING else 500
        raise HTTPException(status, str(exc)) from exc
    path = find_model3d(character_name, signature)
    return {"tip": stored, "due": bool(path is not None and extension_settings_changed(character_name, path))}


class ExtensionTipApplyRequest(BaseModel):
    signature: str


@router.post("/{character_name}/model3d/extension-tip/apply", status_code=202)
def apply_character_model3d_extension_tip(character_name: str, body: ExtensionTipApplyRequest,
                                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Rebuild one stored model's extension rig with its saved tip settings
    in a worker thread (CPU, no hub job; ``extension_tip.start_tip_rebuild``):
    ``{started: True}``; the Base body poll reports the run
    (``extension_tips[].running``). 400 for a bad signature or a missing
    model, 409 while the base model or another tip rebuild of the character
    runs."""
    from app.core import base_body, extension_tip
    from app.core.face_retexture import safe_signature
    _require_character(character_name)
    try:
        signature = safe_signature(body.signature)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if (base_body.base_model_info(character_name, signature) or {}).get("status") == "running":
        raise HTTPException(409, "The base model is being generated")
    try:
        started = extension_tip.start_tip_rebuild(character_name, signature)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not started:
        raise HTTPException(409, extension_tip.REBUILD_RUNNING)
    return {"started": True}


@router.post("/{character_name}/model3d/collision")
def recompute_character_model3d_collision(
        character_name: str, signature: str = "",
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Recompute the collision capsules of a stored model (default: the
    served one) and store them in its sidecar. ``{ok, signature,
    collision}``; ``collision`` is None for a model that gets none (not a
    humanoid GLB)."""
    from app.core import collision
    from app.core.model3d import get_model3d_info
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    signature = signature or (get_model3d_info(character_name).get("model") or {}).get("signature", "")
    if not signature:
        raise HTTPException(404, "No model")
    try:
        record = collision.ensure(character_name, signature, force=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": bool(record) and not record.get("error"), "signature": signature, "collision": record}


@router.post("/{character_name}/model3d/collision/scales")
async def set_character_collision_scales(character_name: str, request: Request,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Per-character radius scale of the collision capsules, per region.
    Body: ``{"scales": {"leg"|"arm"|"torso"|"head": 0.5..1.5}}`` (a missing
    region = 1.0). Stores ``model3d_opts.collision_scales`` and recomputes
    the capsule set of every stored model (base body first, then the
    outfits' inherited sets): ``{options, scales, models}``."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_set_character_collision_scales_sync, character_name, body)


def _set_character_collision_scales_sync(character_name: str, body: Any) -> Dict[str, Any]:
    """The blocking body of ``set_character_collision_scales``."""
    from app.core import collision
    from app.core.model3d import set_model3d_options
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    if not isinstance(body, dict) or set(body) != {"scales"}:
        raise HTTPException(400, "collision scales required")
    try:
        collision.validate_scales(body["scales"])
        options = set_model3d_options(character_name, {"collision_scales": body["scales"]})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"options": options, **collision.recompute_character(character_name)}


@router.post("/{character_name}/model3d/extension-rig/batch")
def queue_character_extension_rigs(
        character_name: str,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Queue all stored models of this character in Improvements."""
    from app.core.improvements import engine, registry, store
    if not get_character_dir(character_name).exists():
        raise HTTPException(404, "Character not found")
    improvement_type = registry.get("extension_rig_rebuild")
    if improvement_type is None:
        raise HTTPException(503, "Extension rig improvement unavailable")
    try:
        params = improvement_type.validate({"character": character_name})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    entry = store.create(improvement_type.id,
                         f"Rebuild extension bones · {character_name}", params, "one_shot")
    engine.scan(entry["id"])
    return store.get(entry["id"]) or entry


@router.post("/{character_name}/model3d/options")
async def set_character_model3d_options(character_name: str, request: Request,
        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Per-character overrides for the mesh generation.
    Body: {"auto_generate": bool, "face_before_rig": bool, "face_cleanup": bool, "face_photo": {…},
    "face_controls": {strength, feather, render_resolution, yaw}, "mesh_repair": {enabled, max_hole_cm}}; each
    is optional. The face values are remembered for the next face retexture, the mesh repair settings for the
    next base mesh repair; both are saved without running anything (400 when out of range).
    Auto-generation uses the cheapest backend after the new T-pose succeeds."""
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_set_character_model3d_options_sync,
                                   character_name, body)


def _set_character_model3d_options_sync(character_name: str,
                                        body: Any) -> Dict[str, Any]:
    """The blocking body of ``set_character_model3d_options`` — runs in the
    threadpool."""
    from app.core.model3d import set_model3d_options
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    if not isinstance(body, dict) or not (
            "auto_generate" in body or "face_before_rig" in body or "face_cleanup" in body
            or "face_photo" in body or "face_controls" in body or "extension_rig" in body
            or "mesh_repair" in body):
        raise HTTPException(status_code=400,
                            detail="model options missing")
    updates = {}
    if "face_photo" in body:
        updates["face_photo"] = body["face_photo"]
    if "face_controls" in body:
        updates["face_controls"] = body["face_controls"]
    if "mesh_repair" in body:
        # The base mesh repair's settings (Ruling A34), validated by ``set_model3d_options``; saved without
        # running anything — the panel then shows the repair as due.
        updates["mesh_repair"] = body["mesh_repair"]
    if "face_before_rig" in body:
        if type(body["face_before_rig"]) is not bool:
            raise HTTPException(400, "face_before_rig must be a boolean")
        updates["face_before_rig"] = body["face_before_rig"]
    if "auto_generate" in body:
        updates["auto_generate"] = bool(body["auto_generate"])
    if "face_cleanup" in body:
        if type(body["face_cleanup"]) is not bool:
            raise HTTPException(400, "face_cleanup must be a boolean")
        updates["face_cleanup"] = body["face_cleanup"]
    if "extension_rig" in body:
        if not isinstance(body.get("signature"), str):
            raise HTTPException(400, "extension_rig requires a model signature")
        updates["signature"] = body["signature"]
        overrides = body["extension_rig"]
        # ``tip`` (a pair_tip group's position/disc override) is validated by
        # ``set_model3d_options``; it rides along so a switch never drops it.
        if not isinstance(overrides, dict) or any(
                not isinstance(group_id, str) or not group_id
                or not isinstance(values, dict)
                or any(key != "tip" and (key not in ("enabled", "flip") or not isinstance(value, bool))
                       for key, value in values.items())
                for group_id, values in overrides.items()):
            raise HTTPException(400, "extension_rig must map group ids to enabled/flip booleans")
        updates["extension_rig"] = overrides
    try:
        return {"options": set_model3d_options(character_name, updates)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{character_name}/model3d/file")
def get_character_model3d_file(character_name: str, request: Request,
                               tier: str = "", download: bool = False,
                               signature: str = ""):
    """Serves the mesh for the current outfit combination — exact entry,
    else the nearest stored one (find_model3d_serving). ETag +
    If-None-Match — the files are several MB. 404 when absent.

    ``tier=low`` serves the reduced version of the SAME combination, falling
    back to the full mesh when none was built. ``download=true`` serves
    the stored original with attachment disposition.

    ``signature`` accepts exactly three kinds of value: the current outfit
    signature (served as without it), the character's CURRENT base-body
    signature and an outfit body id (``ob…``, a stored body shape) of the
    character — the latter two admin only, that stored model itself, full
    tier. Anything else is 404."""
    if signature:
        from fastapi.responses import Response
        from app.core.model_refs import current_outfit_state
        try:
            outfit_signature = current_outfit_state(character_name)[2]
        except Exception:
            outfit_signature = ""
        if signature != outfit_signature:
            from app.core.base_body import base_signature, is_base_signature, is_outfit_body_signature
            from app.core.model_refs import is_humanoid
            if (not (is_base_signature(signature) or is_outfit_body_signature(signature))
                    or not get_character_dir(character_name).exists()
                    or not is_humanoid(character_name)
                    or (is_base_signature(signature) and signature != base_signature(character_name))):
                return Response(status_code=404, headers={"Cache-Control": "no-cache"})
            require_admin(request)
            return _model_asset_response(character_name, request, download=download,
                                         signature=signature)
    return _model_asset_response(character_name, request, tier=tier, download=download)


@router.get("/{character_name}/model3d/texture")
def get_character_model3d_texture(character_name: str, request: Request):
    """Serves the basecolor PNG of the generated mesh (generic/FBX case only —
    a GLB embeds its textures). Follows the same serving chain as the mesh
    route so file and texture always belong together. 404 when absent."""
    return _model_asset_response(character_name, request, texture=True)


@router.delete("/{character_name}/model3d")
def delete_character_model3d(character_name: str) -> Dict[str, Any]:
    """Deletes the cached mesh of the current outfit combination."""
    from app.core import artefact_graph
    from app.core.model3d import delete_model3d
    if not delete_model3d(character_name):
        raise HTTPException(status_code=404, detail="No model")
    artefact_graph.collect_quietly(character_name, "outfit model deleted")
    return {"status": "success"}


@router.get("/{character_name}/artefacts/orphans")
def get_character_artefact_orphans(character_name: str,
                                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Dry run of the artefact GC (``app/core/artefact_graph.py``): every
    derived file group no root reaches, with its parents and why — and what
    is kept although unreachable (running, grace). Deletes nothing."""
    from app.core import artefact_graph
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        return artefact_graph.collect(character_name, dry_run=True, explicit=True, reason="report")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{character_name}/artefacts/collect")
def collect_character_artefacts(character_name: str,
                                _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Delete every orphaned derived file group of the character now
    (explicit: no grace window; running work is never touched)."""
    from app.core import artefact_graph
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        return artefact_graph.collect(character_name, explicit=True, reason="admin collect")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Outfit batch: pre-warm T-pose + mesh for every saved outfit ---

@router.get("/{character_name}/thoughts")
def get_character_thoughts(character_name: str, limit: int = 50,
                           before: str = "",
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """The character's thought journal, newest first (plan-thought-journal.md).

    ADMIN ONLY, and that is the whole access story: thoughts are private
    cognition. They never reach the perception stream, another character's
    prompt, a chat history or a player surface — the only other readers are
    this character's own next thought prompt and its own consolidation.

    ``before`` is the ts of the oldest row you already have (paging cursor);
    ``limit`` is capped at 200. ``has_more`` says whether another page exists.

    Every row carries both clocks: ``ts`` = SYSTEM time (UTC), ``game_ts`` =
    GAME time as the canonical world-calendar stamp ``Y0002-D109T14:00:00``
    (empty for rows written before the column existed), plus ``game_label``
    — the rendered form of that stamp. The server renders, the client only
    displays; ``game_label`` is empty whenever ``game_ts`` is.
    """
    from app.core.character_ops import game_label
    from app.models.thought_store import list_thoughts
    from app.models.world import get_location_by_id
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    limit = max(1, min(int(limit or 50), 200))
    # One extra row decides has_more without a second count query.
    rows = list_thoughts(character_name, limit=limit + 1, before=before or None)
    has_more = len(rows) > limit

    # Resolve ids to NAMES for the UI (user feedback 2026-07-29 — the journal
    # showed raw ids). One location lookup per distinct id, not per row.
    _loc_cache: Dict[str, Dict[str, Any]] = {}

    def _names(loc_id: str, room_id: str) -> Dict[str, str]:
        if not loc_id:
            return {"location_name": "", "room_name": ""}
        if loc_id not in _loc_cache:
            _loc_cache[loc_id] = get_location_by_id(loc_id) or {}
        loc = _loc_cache[loc_id]
        room_name = ""
        if room_id:
            for room in (loc.get("rooms") or []):
                if str(room.get("id") or "") == room_id:
                    room_name = str(room.get("name") or "")
                    break
        return {"location_name": str(loc.get("name") or "") or loc_id,
                "room_name": room_name or room_id}

    return {"thoughts": [{"ts": r["ts"],
                          "game_ts": r.get("game_ts", "") or "",
                          "game_label": game_label(r.get("game_ts", "") or ""),
                          **_names(r.get("location_id", ""), r.get("room_id", "")),
                          "present": r.get("present") or [],
                          "nearby": r.get("nearby") or [],
                          "content": r.get("content", "")}
                         for r in rows[:limit]],
            "has_more": has_more}


async def _outfit_batch_body(request: Request) -> Dict[str, Any]:
    """Body of the two POSTs that carry a filter: ``{"slots": {slot: [item_id
    | null, …]}, "force": bool}``. A missing/empty ``slots`` means "every
    combination" — the filter is a restriction, never a requirement."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    slots = body.get("slots")
    if slots is not None and not isinstance(slots, dict):
        raise HTTPException(status_code=400,
                            detail="slots must be an object of slot -> options")
    # coherent_only defaults to TRUE server-side: cutting the combination set
    # down to what actually goes together is the point of the feature, so an
    # older client that does not send the field gets the filtered set.
    coherent = body.get("coherent_only")
    return {"slots": slots or None, "force": bool(body.get("force")),
            "coherent_only": True if coherent is None else bool(coherent)}


@router.get("/{character_name}/outfit-batch")
def get_character_outfit_batch(character_name: str) -> Dict[str, Any]:
    """The pieces available per slot (the dialog's filter matrix), the live
    progress of a running batch and the queue state of this character's task.
    The queue state is the restart-proof part — the in-process status is empty
    after a server restart while the task keeps going."""
    from app.core import outfit_batch
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    return {"options": outfit_batch.combo_options(character_name),
            "status": outfit_batch.get_status(character_name),
            "queue": outfit_batch.queue_state(character_name)}


@router.post("/{character_name}/outfit-batch/estimate")
async def estimate_character_outfit_batch(character_name: str,
                                          request: Request) -> Dict[str, Any]:
    """Count and duration for a filter — its own endpoint because the dialog
    recomputes on every checkbox and a GET with query parameters would be
    unwieldy at a dozen slots. Answer: ``{total, missing, missing_exact,
    est_seconds}``; an invalid filter is a 400."""
    from app.core import outfit_batch
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    body = await _outfit_batch_body(request)
    stats = outfit_batch.combo_stats(character_name, body["slots"], body["force"],
                                     body["coherent_only"])
    if stats.get("error"):
        raise HTTPException(status_code=400, detail=str(stats["error"]))
    return {k: v for k, v in stats.items() if k != "error"}


@router.post("/{character_name}/outfit-batch/start")
async def start_character_outfit_batch(character_name: str,
                                       request: Request) -> Dict[str, Any]:
    """Queues the batch for the filtered combinations at low priority.
    ``force`` re-renders reference and mesh of combinations that already have
    one. 409 while a batch of this character is still pending or running."""
    from app.core import outfit_batch
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    body = await _outfit_batch_body(request)
    res = outfit_batch.start(character_name, body["slots"], force=body["force"],
                             coherent_only=body["coherent_only"])
    if not res.get("ok"):
        error = str(res.get("error") or "")
        raise HTTPException(status_code=409 if error == "already running" else 400,
                            detail=error)
    return {"status": "started", "task_id": res.get("task_id", ""),
            "total": res.get("total", 0),
            "total_exact": bool(res.get("total_exact", True)),
            "missing": res.get("missing", 0),
            "missing_exact": bool(res.get("missing_exact", True)),
            "est_seconds": res.get("est_seconds", 0.0)}


@router.get("/{character_name}/outfit-batch/cache")
def verify_character_outfit_cache(character_name: str) -> Dict[str, Any]:
    """Cache report for this character: how many reference renders and meshes
    exist, how many of them no combination can reach any more, and what that
    would free. Read-only — deleting is the POST below.

    The enumeration behind it can take seconds on a large inventory, which is
    why this is an explicit call and not part of the batch GET. Its refusal
    above five million combinations is mapped to a 400 with the message."""
    from app.core import outfit_cache_gc
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        return outfit_cache_gc.verify_cache(character_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{character_name}/outfit-batch/cache/purge")
async def purge_character_outfit_cache(character_name: str,
                                       request: Request) -> Dict[str, Any]:
    """Deletes the cache entries of ``{"signatures": [...]}`` — the stale list
    the caller got from the report above. The core re-verifies before deleting,
    so a signature that has become valid in the meantime is skipped and
    counted, never removed."""
    from app.core import outfit_cache_gc
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    signatures = body.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        raise HTTPException(status_code=400,
                            detail="signatures must be a non-empty list")
    try:
        return outfit_cache_gc.purge_stale(character_name,
                                           [str(s) for s in signatures])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{character_name}/outfit-batch/stop")
def stop_character_outfit_batch(character_name: str) -> Dict[str, Any]:
    """Cancels the pending/running batch task. A running one stops BETWEEN two
    combinations — a GPU job already handed out runs to completion."""
    from app.core import outfit_batch
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    return {"status": "stopping" if outfit_batch.stop(character_name) else "idle"}


@router.post("/{character_name}/profile-image/{image_filename}")
def set_character_profile_image_endpoint(character_name: str, image_filename: str) -> Dict[str, Any]:
    """Set the profile image."""
    try:
        if set_character_profile_image(character_name, image_filename):
            return {
                "status": "success",
                "character": character_name,
                "profile_image": image_filename
            }
        else:
            raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{character_name}/images/{image_filename}")
def delete_character_image_endpoint(character_name: str, image_filename: str) -> Dict[str, Any]:
    """Delete an image."""
    try:
        if ".." in image_filename or "/" in image_filename:
            raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

        if delete_character_image(character_name, image_filename):
            return {
                "status": "success",
                "character": character_name,
                "deleted_image": image_filename
            }
        else:
            raise HTTPException(status_code=404, detail="Image not found")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{character_name}/images/{image_filename}/animation")
def delete_image_animation(character_name: str, image_filename: str) -> Dict[str, Any]:
    """Delete the animation video of an image while keeping the image."""
    if ".." in image_filename or "/" in image_filename:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

    from app.models.character import remove_image_animation
    deleted = remove_image_animation(character_name, image_filename)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Keine Animation vorhanden")
    return {"status": "success", "deleted_video": deleted}


# --- Skills Management ---

@router.get("/{character_name}/skills/available")
def get_available_skills_for_character(character_name: str) -> Dict[str, Any]:
    """Returns all globally loaded skills with per-character enabled state and config fields."""
    try:
        return character_ops.build_available_skills(character_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/prompt-preview")
def get_prompt_preview_route(character_name: str) -> Dict[str, Any]:
    """Effective prompts (scene person description / face / outfit line)
    as they would render right now — admin preview for the Appearance and
    Wardrobe editors."""
    return character_ops.build_prompt_preview(character_name)


@router.get("/{character_name}/body-slots")
def get_body_slots(character_name: str) -> Dict[str, Any]:
    """Applicable body slots (declarations + current values) + silhouette."""
    return character_ops.build_body_slots(character_name)


@router.post("/{character_name}/body-slots/{slot_id}")
async def save_body_slot(character_name: str, slot_id: str, request: Request) -> Dict[str, Any]:
    """Stores attribute values for one declared slot. Body: {"values": {attr: value}}."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_save_body_slot_sync, character_name,
                                   slot_id, data)


def _save_body_slot_sync(character_name: str, slot_id: str,
                         data: Any) -> Dict[str, Any]:
    """The blocking body of ``save_body_slot`` — runs in the threadpool."""
    values = data.get("values") if isinstance(data, dict) else None
    if not isinstance(values, dict):
        raise HTTPException(status_code=400, detail="values object required")
    return character_ops.apply_body_slot_values(character_name, slot_id, values)


@router.get("/{character_name}/silhouette")
def get_character_silhouette(character_name: str):
    """Serves the species package's silhouette asset (UI paper-doll)."""
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.core.body_slots import silhouette_for_character
    sil = silhouette_for_character(character_name)
    if not sil:
        raise HTTPException(status_code=404, detail="No species silhouette")
    root = Path(sil["dir"]).resolve()
    asset = (root / sil["asset"]).resolve()
    if not str(asset).startswith(str(root)) or not asset.is_file():
        raise HTTPException(status_code=404, detail="Silhouette asset missing")
    return FileResponse(asset)


# ---------------------------------------------------------------------------
# Soul Editor — MD-Files unter characters/{Char}/soul/
# ---------------------------------------------------------------------------


@router.get("/{character_name}/soul/files")
def get_soul_files(character_name: str) -> Dict[str, Any]:
    """List available soul Markdown files, respecting template feature gates.

    Each entry includes section ID, file_default lock status and file existence."""
    return character_ops.build_soul_files(character_name)


@router.get("/{character_name}/soul/file/{section_id}")
def get_soul_file(character_name: str, section_id: str) -> Dict[str, Any]:
    """Return the content and parsed sections of a soul Markdown file."""
    return character_ops.read_soul_file(character_name, section_id)


@router.post("/{character_name}/soul/file/{section_id}")
async def save_soul_file(character_name: str, section_id: str, request: Request) -> Dict[str, Any]:
    """Write an entire soul Markdown file from the request's content field."""
    return await character_ops.write_soul_file(character_name, section_id, request)


@router.put("/{character_name}/skills/{skill_name}/enabled")
async def toggle_character_skill(character_name: str, skill_name: str, request: Request) -> Dict[str, Any]:
    """Toggles a skill enabled/disabled for a character."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_toggle_character_skill_sync,
                                   character_name, skill_name, data)


def _toggle_character_skill_sync(character_name: str, skill_name: str,
                                 data: Any) -> Dict[str, Any]:
    """The blocking body of ``toggle_character_skill`` — runs in the
    threadpool."""
    try:
        user_id = data.get("user_id", "")
        enabled = data.get("enabled", True)

        # F9 package dependencies: enabling is refused while requires/
        # conflicts of the providing package are not satisfied.
        if bool(enabled):
            from app.core.character_ops import skill_dependency_block
            reason = skill_dependency_block(character_name, skill_name)
            if reason:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot enable '{skill_name}': {reason}")

        config = get_character_skill_config(character_name, skill_name)
        config["enabled"] = bool(enabled)
        save_character_skill_config(character_name, skill_name, config)
        return {"status": "success", "skill": skill_name, "enabled": bool(enabled)}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Per-Character Skill Config ---

@router.get("/{character_name}/skills/{skill_name}")
def get_character_skill_config_route(character_name: str, skill_name: str) -> Dict[str, Any]:
    """Return character-specific skill configuration."""
    try:
        config = get_character_skill_config(character_name, skill_name)
        return {
            "character": character_name,
            "skill": skill_name,
            "config": config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/skills/{skill_name}")
async def update_character_skill_config_route(character_name: str, skill_name: str, request: Request) -> Dict[str, Any]:
    """Merge character-specific skill configuration."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_update_character_skill_config_route_sync,
                                   character_name, skill_name, data)


def _update_character_skill_config_route_sync(character_name: str,
                                              skill_name: str,
                                              data: Any) -> Dict[str, Any]:
    """The blocking body of ``update_character_skill_config_route`` —
    runs in the threadpool."""
    try:
        user_id = data.get("user_id", "")
        config = data.get("config", {})
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="config muss ein Objekt sein")

        # Merge supplied fields into the existing configuration
        existing = get_character_skill_config(character_name, skill_name)
        if existing:
            existing.update(config)
            config = existing

        save_character_skill_config(character_name, skill_name, config)
        return {
            "status": "success",
            "character": character_name,
            "skill": skill_name,
            "config": config
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/images/{image_name}/detect-characters")
async def detect_image_characters(character_name: str, image_name: str, request: Request) -> Dict[str, Any]:
    """Detect depicted characters from reference_images metadata."""
    return await character_ops.detect_characters_core(character_name, image_name, request)


@router.post("/{character_name}/images/{image_name}/regenerate")
async def regenerate_character_image(character_name: str, image_name: str, request: Request) -> Dict[str, Any]:
    """Regenerates an image via the core image-service pipeline.

    Uses the stored prompt, optionally improved by user feedback, and
    renders a new image that replaces the old one (or lands beside it).
    """
    import asyncio
    body = await request.json()
    return await asyncio.to_thread(_regenerate_character_image_sync,
                                   character_name, image_name, body)


def _regenerate_character_image_sync(character_name: str, image_name: str,
                                     body: Any) -> Dict[str, Any]:
    """The blocking body of ``regenerate_character_image`` — runs in the
    threadpool."""
    user_id = body.get("user_id", "")
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail=f"Invalid file name: {image_name}")

    images_dir = get_character_images_dir(character_name)
    image_path = images_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {image_name}")

    prompts = get_character_image_prompts(character_name)
    prompt = prompts.get(image_name, "")
    if not prompt:
        raise HTTPException(status_code=422, detail="No prompt stored for this image.")

    # A custom prompt from the dialog replaces the stored one
    custom_prompt = body.get("custom_prompt", "").strip()
    if custom_prompt:
        prompt = custom_prompt

    improvement_request = body.get("improvement_request", "").strip()
    backend_name = body.get("backend", "").strip()
    loras = body.get("loras")  # Optional: [{name, strength}, ...]
    model_override = body.get("model_override", "").strip()
    character_names = body.get("character_names")  # Optional: explicit character selection
    room_id = body.get("room_id", "").strip()  # Optional: room override
    negative_prompt_override = body.get("negative_prompt", "").strip()  # Optional: negative prompt from the dialog
    create_new = body.get("create_new", False)
    use_room = body.get("use_room", True)
    use_source_as_reference = bool(body.get("use_source_as_reference", False))
    from app.imagegen.pose_check import parse_override
    pose_check = parse_override(body.get("pose_check"))  # None = routing switch
    # The original location from the image meta (not the character's current one)
    from app.models.character import get_single_image_meta
    _img_meta = get_single_image_meta(character_name, image_name) or {}
    original_location_id = _img_meta.get("location", "")
    original_room_id = _img_meta.get("room_id", "")
    agent_config = get_character_config(character_name)
    if backend_name:
        # A dead explicit pick is the caller's answer (503), not a track
        # that fails in the background thread.
        require_explicit_backend(backend_name)

    from app.core.task_queue import get_task_queue
    from app.core.task_router import resolve_queue
    _tq = get_task_queue()
    _queue = resolve_queue("image_regenerate", {}, agent_name=character_name)
    _track_id = _tq.track_start(
        "image_regenerate", "Bild regenerieren", agent_name=character_name,
        provider=backend_name or "",
        queue_name=_queue,
        start_running=False)

    import threading
    threading.Thread(
        target=character_ops.regenerate_image_worker,
        args=(character_name, image_path, prompt, improvement_request,
              backend_name, agent_config, loras, model_override, character_names, room_id,
              original_location_id, original_room_id, negative_prompt_override,
              _track_id, create_new,
              use_room, use_source_as_reference, _tq, pose_check),
        daemon=True).start()
    return {"status": "started", "image": image_name, "track_id": _track_id}


@router.post("/{character_name}/images/{image_name}/animate")
async def animate_character_image(character_name: str, image_name: str, request: Request,
                                  _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Animates a gallery still into a video (Game-Admin gallery, admin only).

    Body: { prompt, service?, loras?, seconds? } — see
    ``character_ops.start_gallery_animation``; the video lands next to the
    still as ``{stem}.mp4``. Answers ``{status, image, video, track_id}``."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(character_ops.start_gallery_animation,
                                   character_name, image_name, data or {})


@router.post("/{character_name}/images/{image_name}/suggest-animate-prompt")
async def suggest_character_animate_prompt(character_name: str, image_name: str,
                                           request: Request,
                                           _: Dict[str, Any] = Depends(require_admin)
                                           ) -> Dict[str, Any]:
    """Suggests a motion prompt for a gallery still from its image analysis
    (the animate dialog's "Suggest", admin only). Body: { system_prompt? }."""
    import asyncio
    data = await request.json()
    try:
        prompt = await asyncio.to_thread(character_ops.suggest_gallery_animate_prompt,
                                         character_name, image_name, data or {})
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"prompt": prompt}


# ---------------------------------------------------------------------------
# Character Export / Import
# ---------------------------------------------------------------------------

@router.get("/{character_name}/export")
def export_character(
                     character_name: str,
                     include_chats: bool = Query(False, description="Include chat history"),
                     include_stories: bool = Query(False, description="Include story progress"),
                     ) -> StreamingResponse:
    """Exports a character as a ZIP bundle (DB rows + filesystem dir).

    The ZIP carries a manifest.json plus `files/` (char dir contents) and
    `db/<table>.json` slices for every table the character owns rows in
    (profile/config, state, memories, summaries, knowledge, inventory,
    outfits, schedule, secrets, relationships, image metadata, ...).
    """
    from app.core.character_io import export_character_to_zip
    from app.core.db import get_connection

    char_dir = get_character_dir(character_name)
    conn = get_connection()
    db_row = conn.execute(
        "SELECT 1 FROM characters WHERE name=?", (character_name,)
    ).fetchone()
    if not char_dir.exists() and not db_row:
        raise HTTPException(
            status_code=404,
            detail=f"Character '{character_name}' not found",
        )

    try:
        zip_bytes = export_character_to_zip(
            character_name,
            include_chats=include_chats,
            include_stories=include_stories,
            include_rule_details=_can_view_rule_details(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Export failed for %s", character_name)
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

    filename = f"{character_name}_export.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_character(
    file: UploadFile = File(...),
    overwrite: bool = Query(False, description="Replace existing character"),
) -> Dict[str, Any]:
    """Imports a character ZIP produced by the export endpoint.

    Restores both the filesystem char dir and all owned DB rows. With
    overwrite=true, existing DB rows and the char dir are wiped first.
    """
    from app.core.character_io import import_character_from_zip

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")

    content = await read_upload_capped(file, max_bytes=max_pack_bytes(),
                                       what="Character ZIP")
    try:
        return import_character_from_zip(content, overwrite=overwrite)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Import failed")
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")


# --- Memory/Knowledge Endpoints ---

@router.delete("/{character_name}/knowledge/{entry_id}")
def delete_single_knowledge(character_name: str, entry_id: str) -> Dict[str, Any]:
    """Delete a single memory entry."""
    from app.models.memory import delete_memory
    if delete_memory(character_name, entry_id):
        return {"status": "success", "deleted": entry_id}
    raise HTTPException(status_code=404, detail="Entry not found")


@router.delete("/{character_name}/knowledge")
def clear_character_knowledge(character_name: str) -> Dict[str, Any]:
    """Delete all memory entries of a character. A linked body's memories are
    its leader's mind — refused with 409 (clear them on the leader)."""
    from app.models.memory import clear_memories
    try:
        m_count = clear_memories(character_name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "success", "deleted_count": m_count}


# ---------------------------------------------------------------------------
# Memory-Modal v2 — Tab-spezifische Endpoints
# Plan: development_instructions/plan-memory-window-redesign.md
# ---------------------------------------------------------------------------

@router.get("/{character_name}/memory/today")
def memory_today(character_name: str) -> Dict[str, Any]:
    """Today tab: status, 24-hour lanes and the most relevant memories.

    Reading this payload does not increment access_count.
    """
    return character_ops.build_memory_today(character_name)


@router.get("/{character_name}/debug-activity")
def debug_activity(character_name: str) -> Dict[str, Any]:
    """Explain a non-avatar character's behavior for Game-Admin debugging.

    Aggregate current feeling and source, recent mood/state/thought activity,
    and active block/force rules. Read-only; the path supplies the character.
    """
    return character_ops.build_debug_activity(
        character_name, include_rule_details=_can_view_rule_details())


@router.get("/{character_name}/memory/locations")
def memory_locations(character_name: str) -> Dict[str, Any]:
    """Return all world locations with known, current and visit information.

    Include both layout context and the known_locations selection; the UI
    decides whether to show all locations or only known ones."""
    return character_ops.build_memory_locations(character_name)


@router.put("/{character_name}/known-locations")
async def set_known_locations_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Replace known_locations with the complete editor selection.

    Body: {"known_locations": ["loc_id", ...]}. An empty list keeps strict
    mode active with no known locations. Entering a location discovers it later."""
    import asyncio
    data = await request.json()
    return await asyncio.to_thread(_set_known_locations_route_sync,
                                   character_name, data)


def _set_known_locations_route_sync(character_name: str,
                                    data: Any) -> Dict[str, Any]:
    """The blocking body of ``set_known_locations_route`` — runs in the
    threadpool."""
    from app.models.character import set_known_locations
    ids = data.get("known_locations")
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="known_locations must be a list")
    known = set_known_locations(character_name, ids)
    return {"status": "success", "character": character_name, "known_locations": known}


@router.get("/{character_name}/memory/list")
def memory_list(character_name: str,
                limit: int = 50,
                offset: int = 0,
                tier: str = "",
                min_importance: int = 0,
                q: str = "",
                related: str = "",
                source: str = "",
                sort: str = "recent",
                include_completed: bool = False) -> Dict[str, Any]:
    """Tab "Erinnerungen": gefilterte, paginierte Memory-Liste + Facets.

    Sort: 'recent' (default) | 'importance' | 'access' | 'score'
    """
    return character_ops.build_memory_list(
        character_name, limit=limit, offset=offset, tier=tier,
        min_importance=min_importance, q=q, related=related, source=source,
        sort=sort, include_completed=include_completed)


@router.post("/{character_name}/memory/wipe")
def memory_wipe(character_name: str,
                _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Wipes ALL derived memory of the character — memories, summaries
    (dailies + weekly/season rollups), diary entries, thoughts, mood/state/
    evolution history, the action log and the day cursor, i.e. the entire day
    timeline the character page shows. Admin test tool for the consolidation
    pipeline. chat_messages and shared scenes/utterances stay untouched.

    Runs ``character_reset.reset_character`` at scope ``memory`` — the same
    implementation the import's re-init runs at scope ``reinit``."""
    return character_ops.wipe_character_memory(character_name)


class FreshStartBody(BaseModel):
    """The text of the one memory the character starts with (may be empty)."""
    intro: str = ""


@router.post("/{character_name}/fresh-start")
def fresh_start(character_name: str, body: FreshStartBody,
                _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Re-initialize an existing character in place: everything it lived
    through in this world goes — memories, the day timeline, correspondence,
    knowledge, relationships in both directions, intents, the room record of
    its conversations, the explored map — and ``intro`` becomes its one
    memory. Identity (profile, authored soul files, outfits, inventory,
    secrets, routine, gallery) stays.

    Runs ``character_reset.reset_character`` at scope ``reinit`` — the same
    implementation the character import's fresh mode runs."""
    return character_ops.fresh_start_character(character_name, body.intro)


@router.post("/{character_name}/memory/consolidate")
async def memory_consolidate_now(character_name: str,
                                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Runs the full 5-phase memory consolidation for ONE character right now
    (admin test tool — exercise the per-NPC amount caps without waiting for
    the 6h background cycle). Synchronous; returns the removal counts.
    A dormant character exists; a linked body's run is its MIND's."""
    import asyncio as _aio
    from app.models.character import list_available_characters
    if character_name not in list_available_characters(include_dormant=True):
        raise HTTPException(status_code=404,
                            detail=f"Character '{character_name}' not found")
    from app.core.memory_service import handle_memory_consolidation
    return await _aio.to_thread(handle_memory_consolidation,
                                {"character_name": character_name})


@router.get("/{character_name}/memory/relationships")
def memory_relationships(character_name: str,
                         history_limit: int = 10,
                         lang: str = "en") -> Dict[str, Any]:
    """Tab "Relationships": sentiment, strength, tension + last N events.

    `memories_count` = how many memories have this partner set as
    related_character — a click in the frontend filters tab 2.

    ``lang`` picks the language of the readable world-date label that
    accompanies the pair's last meeting — the server renders it, the client
    only shows it.
    """
    return character_ops.build_memory_relationships(
        character_name, history_limit=history_limit, lang=lang)


class AddressUpdate(BaseModel):
    """One or both address directions of a pair. None = leave untouched."""
    outgoing: Optional[str] = None
    incoming: Optional[str] = None


@router.get("/{character_name}/relationships/addresses")
def relationship_addresses(character_name: str,
                           _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Every known pair of this character with both forms of address.

    `outgoing` = how {character_name} addresses the other one, `incoming` =
    how the other one addresses {character_name}. World authoring, so admin
    only — the rest of the /characters prefix is writable by a player for
    their own character.
    """
    return character_ops.build_relationship_addresses(character_name)


@router.put("/{character_name}/relationships/{other}/address")
def set_relationship_address(character_name: str, other: str,
                             body: AddressUpdate,
                             _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Set how the two address each other; creates the pair if needed.

    Free text, max 120 characters per direction, no line breaks. An empty
    string clears that direction, a missing field leaves it as it is.
    """
    return character_ops.set_relationship_address(
        character_name, other, outgoing=body.outgoing, incoming=body.incoming)


@router.get("/{character_name}/memory/history")
def memory_history(character_name: str,
                   kind: str = "daily",
                   limit: int = 60,
                   offset: int = 0,
                   lang: str = "en") -> Dict[str, Any]:
    """Tab "History": daily | weekly | monthly | history | diary | evolution.

    Default: `daily` (last 60 entries across all partners).

    ``lang`` picks the language of the readable world-date ``label`` that
    accompanies every game-calendar key — the server renders it, the client
    only displays it. Same query-parameter convention as ``/diary`` and
    ``/events``.
    """
    return character_ops.build_memory_history(
        character_name, kind=kind, limit=limit, offset=offset, lang=lang)


@router.get('/{character_name}/stat-history')
def get_stat_history(character_name: str, limit: int = Query(50, ge=1, le=200)):
    return character_ops.build_stat_history(
        character_name, limit, include_rule_details=_can_view_rule_details())
