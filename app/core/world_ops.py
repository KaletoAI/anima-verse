"""World-domain operations behind app/routes/world.py.

Logic moved 1:1 out of the route handlers (code-review section 5b); the
routes remain thin HTTP adapters (auth, request parsing, response types).
HTTPExceptions that were embedded mid-logic moved along unchanged.
"""
import asyncio
import os
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Any, Dict, Optional
from app.core.log import get_logger

logger = get_logger("world")

from app.models.world import (
    list_locations, add_location,
    rename_location, resolve_location, get_location_by_id,
    get_entry_room_id,
    get_background_path, get_background_file_path,
    get_background_images, remove_background_image,
    get_gallery_dir, list_gallery_images,
    save_gallery_prompt, get_all_gallery_prompts,
    set_gallery_image_room, get_gallery_image_rooms, remove_gallery_image_room,
    set_gallery_image_type, get_gallery_image_types, remove_gallery_image_type,
    set_gallery_image_meta, get_gallery_image_metas,
    get_room_by_id,
    toggle_background_image,
    clear_room_prompt_changed, clear_location_prompt_changed)


# === Avatar movement (direction pad) ===

def compute_avatar_neighbors() -> Dict[str, Any]:
    """Return the avatar's neighbor locations for each compass direction.

    Response: { "north": {id, name} | null, "south": ..., "east": ..., "west": ... }
    Lets the direction pad hide unreachable directions instead of reacting
    to the 404 response.
    """
    from app.models.account import get_active_character
    from app.models.character import (
        get_character_current_location, get_character_current_room)

    out = {"north": None, "south": None, "east": None, "west": None,
           "current_location_id": "", "current_location_name": "",
           "at_entry_room": True, "entry_room_name": ""}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    cur_loc_id = (get_character_current_location(avatar) or "").strip()
    if not cur_loc_id:
        return out
    cur = get_location_by_id(cur_loc_id)
    if not cur:
        return out
    out["current_location_id"] = cur.get("id", "") or ""
    out["current_location_name"] = cur.get("name", "") or ""

    # Departure gate: the frontend can hide the direction arrows when the
    # avatar is not in the entry room. The server-side block lives in
    # avatar_step_route.
    cur_entry = get_entry_room_id(cur)
    cur_room = (get_character_current_room(avatar) or "").strip()
    if cur_entry and cur_room and cur_room != cur_entry:
        out["at_entry_room"] = False
    for _r in (cur.get("rooms") or []):
        if isinstance(_r, dict) and _r.get("id") == cur_entry:
            out["entry_room_name"] = _r.get("name", "") or ""
            break

    cx = int(cur.get("grid_x") or 0)
    cy = int(cur.get("grid_y") or 0)
    deltas = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
    targets = {(cx + dx, cy + dy): direction
               for direction, (dx, dy) in deltas.items()}
    for loc in list_locations():
        key = (int(loc.get("grid_x") or 0), int(loc.get("grid_y") or 0))
        direction = targets.get(key)
        if direction and not out[direction]:
            out[direction] = {
                "id": loc.get("id", "") or "",
                "name": loc.get("name", "") or "",
            }
    return out


def move_avatar_step(direction: str) -> Dict[str, Any]:
    """Move the avatar one grid step in the given direction.

    Looks up the neighbor location via the grid coordinates of the current
    avatar position. Raises 404 if no location lies there.
    """
    deltas = {
        "north": (0, -1),  # screen-up = decreasing grid_y
        "south": (0, 1),
        "east": (1, 0),
        "west": (-1, 0),
    }
    if direction not in deltas:
        raise HTTPException(status_code=400, detail="invalid direction")

    from app.models.account import get_active_character
    from app.models.character import (
        get_character_current_location,
        get_character_current_room,
        clear_pose_intent,
        save_character_current_location,
        save_character_current_room,
    )
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")

    # Party follower: the avatar follows the leader and cannot move on its
    # own (the UI hides the compass, this is the hard backstop).
    from app.core.party_engine import is_party_follower
    if is_party_follower(avatar):
        raise HTTPException(status_code=403, detail={
            "reason": "party_follower",
            "message": "Du bist Teil einer Party und wirst vom Leader mitgenommen — eigene Bewegung gesperrt."})

    cur_loc_id = (get_character_current_location(avatar) or "").strip()
    if not cur_loc_id:
        raise HTTPException(status_code=400, detail="avatar has no current location")

    cur = get_location_by_id(cur_loc_id)
    if not cur:
        raise HTTPException(status_code=404, detail="current location not found")

    # Departure gate: the avatar may only leave a location via the entry room.
    cur_entry = get_entry_room_id(cur)
    cur_room = (get_character_current_room(avatar) or "").strip()
    if cur_entry and cur_room and cur_room != cur_entry:
        # Fetch the entry-room name for the message
        _entry_name = ""
        for _r in (cur.get("rooms") or []):
            if isinstance(_r, dict) and _r.get("id") == cur_entry:
                _entry_name = _r.get("name", "") or ""
                break
        raise HTTPException(status_code=403,
            detail={"reason": "not_at_entry_room",
                    "message": f"Du musst zuerst zum Entry-Room ({_entry_name or cur_entry}) gehen, um diesen Ort zu verlassen."})

    cur_x = int(cur.get("grid_x") or 0)
    cur_y = int(cur.get("grid_y") or 0)
    dx, dy = deltas[direction]
    target_x, target_y = cur_x + dx, cur_y + dy

    # Find the neighbor location
    target = None
    for loc in list_locations():
        if int(loc.get("grid_x") or 0) == target_x and int(loc.get("grid_y") or 0) == target_y:
            target = loc
            break
    if not target:
        raise HTTPException(status_code=404, detail="no location in that direction")

    target_id = target.get("id") or ""

    # Block rules: the avatar is subject to the same restrictions as NPCs.
    target_entry_room = get_entry_room_id(target)
    from app.models.rules import check_leave, check_access
    ok_leave, leave_msg = check_leave(avatar)
    if not ok_leave:
        raise HTTPException(status_code=403,
            detail={"reason": "block_leave", "message": leave_msg})
    ok_enter, enter_msg = check_access(avatar, target_id, room_id=target_entry_room)
    if not ok_enter:
        raise HTTPException(status_code=403,
            detail={"reason": "block_enter", "message": enter_msg})

    save_character_current_location(avatar, target_id)
    if target_entry_room:
        save_character_current_room(avatar, target_entry_room)
    # A location change interrupts the running pose (otherwise the old one
    # persists at the new place). The avatar is player-controlled → clear,
    # do not reassign.
    clear_pose_intent(avatar)

    # Roll-on-entry: on entering a location, immediately roll whether an
    # event arises for the avatar (e.g. "wolves block the path").
    try:
        from app.core.random_events import try_roll_on_entry
        try_roll_on_entry(avatar, target_id, target)
    except Exception as _re:
        logger.debug("try_roll_on_entry fehlgeschlagen: %s", _re)

    return {
        "ok": True,
        "direction": direction,
        "location_id": target_id,
        "location_name": target.get("name", ""),
        "room_id": target_entry_room,
    }


# === Locations ===

def build_locations_payload(character_name: str) -> Dict[str, Any]:
    """List locations from a character's point of view.

    If ``character_name`` is set, locations with ``visible_when``/
    ``accessible_when`` are filtered against the character inventory/state.
    Invisible locations (visible_when fails) are removed; inaccessible
    locations (accessible_when fails) get an ``accessible: false`` flag.
    Without ``character_name`` all locations are returned unfiltered
    (admin view).
    """
    locations = list_locations()

    if character_name:
        from app.core.activity_engine import evaluate_condition

        def _all_pass(conditions, char: str, loc_id: str) -> bool:
            if not conditions:
                return True
            if isinstance(conditions, str):
                conditions = [conditions]
            for c in conditions:
                if not c:
                    continue
                ok, _ = evaluate_condition(str(c), char, loc_id)
                if not ok:
                    return False
            return True

        filtered = []
        for loc in locations:
            loc_id = loc.get("id", "")
            vw = loc.get("visible_when") or []
            if vw and not _all_pass(vw, character_name, loc_id):
                continue  # location not visible
            aw = loc.get("accessible_when") or []
            loc["accessible"] = _all_pass(aw, character_name, loc_id) if aw else True
            filtered.append(loc)
        locations = filtered

    for loc in locations:
        loc_id = loc.get("id", "")
        loc["image_count"] = len(list_gallery_images(loc_id)) if loc_id else 0
    return {"locations": locations}


def create_location_with_extras(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a location from a parsed request body (incl. extra fields)."""
    user_id = data.get("user_id", "").strip()
    location_name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    rooms = data.get("rooms", [])
    image_prompt_day = data.get("image_prompt_day")
    image_prompt_night = data.get("image_prompt_night")
    image_prompt_map = data.get("image_prompt_map")
    image_prompt_map_2d = data.get("image_prompt_map_2d")
    danger_level = data.get("danger_level")
    event_settings = data.get("event_settings")
    outfit_type = data.get("outfit_type")
    decency = data.get("decency")
    style_hint = data.get("style_hint")
    swim_allowed = data.get("swim_allowed")
    activity_hint = data.get("activity_hint")
    knowledge_item_id = data.get("knowledge_item_id")
    passable = data.get("passable")
    entry_room = data.get("entry_room")
    indoor = data.get("indoor")
    if not location_name:
        raise HTTPException(status_code=400, detail="Name fehlt")
    if not isinstance(rooms, list):
        raise HTTPException(status_code=400, detail="rooms muss eine Liste sein")

    location = add_location(location_name, description, rooms=rooms,
                            image_prompt_day=image_prompt_day,
                            image_prompt_night=image_prompt_night,
                            image_prompt_map=image_prompt_map,
                            image_prompt_map_2d=image_prompt_map_2d)

    # Set extra fields directly in the location
    _has_extra = (danger_level is not None or event_settings is not None
                  or outfit_type is not None or knowledge_item_id is not None
                  or passable is not None
                  or entry_room is not None or indoor is not None
                  or decency is not None or style_hint is not None
                  or swim_allowed is not None or activity_hint is not None)
    if _has_extra and location:
        from app.models.world import _load_world_data, _save_world_data
        wdata = _load_world_data()
        for _l in wdata.get("locations", []):
            if _l.get("id") == location.get("id"):
                if danger_level is not None:
                    try:
                        _l["danger_level"] = max(0, min(5, int(danger_level)))
                    except (TypeError, ValueError):
                        pass
                if event_settings is not None:
                    _l["event_settings"] = event_settings
                if outfit_type is not None:
                    _l["outfit_type"] = (outfit_type or "").strip()
                if decency is not None:
                    _v = (decency or "").strip().lower()
                    _l["decency"] = _v if _v in ("public", "private", "nude_ok") else ""
                if style_hint is not None:
                    _l["style_hint"] = (style_hint or "").strip()
                if swim_allowed is not None:
                    _l["swim_allowed"] = bool(swim_allowed)
                if activity_hint is not None:
                    _l["activity_hint"] = (activity_hint or "").strip()
                if knowledge_item_id is not None:
                    _l["knowledge_item_id"] = (knowledge_item_id or "").strip()
                if passable is not None:
                    _l["passable"] = bool(passable)
                if entry_room is not None:
                    _l["entry_room"] = (entry_room or "").strip()
                if indoor is not None:
                    _v = (indoor or "").strip().lower()
                    _l["indoor"] = _v if _v in ("indoor", "outdoor") else ""
                break
        _save_world_data(wdata)
        location = get_location_by_id(location["id"])

    return {"status": "success", "location": location}


def update_location_with_extras(location_id: str,
                                data: Dict[str, Any]) -> Dict[str, Any]:
    """Update a location by id from a parsed request body (incl. extra fields)."""
    user_id = data.get("user_id", "").strip()
    new_name = data.get("name", "").strip()
    description = data.get("description")
    rooms = data.get("rooms")
    image_prompt_day = data.get("image_prompt_day")
    image_prompt_night = data.get("image_prompt_night")
    image_prompt_map = data.get("image_prompt_map")
    image_prompt_map_2d = data.get("image_prompt_map_2d")
    danger_level = data.get("danger_level")
    event_settings = data.get("event_settings")
    outfit_type = data.get("outfit_type")
    decency = data.get("decency")
    style_hint = data.get("style_hint")
    swim_allowed = data.get("swim_allowed")
    activity_hint = data.get("activity_hint")
    knowledge_item_id = data.get("knowledge_item_id")
    passable = data.get("passable")
    entry_room = data.get("entry_room")
    indoor = data.get("indoor")

    loc = get_location_by_id(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")

    if new_name:
        rename_location(location_id, new_name)

    # Update description, rooms and image prompts if provided
    has_updates = any(v is not None for v in [description, rooms, image_prompt_day, image_prompt_night, image_prompt_map, image_prompt_map_2d])
    if has_updates:
        loc = get_location_by_id(location_id)
        if loc:
            add_location(loc["name"],
                description if description is not None else loc.get("description", ""),
                rooms=rooms if rooms is not None else loc.get("rooms", []),
                image_prompt_day=image_prompt_day if image_prompt_day is not None else loc.get("image_prompt_day", ""),
                image_prompt_night=image_prompt_night if image_prompt_night is not None else loc.get("image_prompt_night", ""),
                image_prompt_map=image_prompt_map if image_prompt_map is not None else loc.get("image_prompt_map", ""),
                image_prompt_map_2d=image_prompt_map_2d if image_prompt_map_2d is not None else loc.get("image_prompt_map_2d", ""),
                location_id=location_id)  # update by id — unambiguous with duplicate names

    # Set extra fields (incl. knowledge_item_id) directly in the location
    _has_extra = (danger_level is not None or event_settings is not None
                  or outfit_type is not None or knowledge_item_id is not None
                  or passable is not None
                  or entry_room is not None or indoor is not None
                  or decency is not None or style_hint is not None
                  or swim_allowed is not None or activity_hint is not None)
    if _has_extra:
        from app.models.world import _load_world_data, _save_world_data
        wdata = _load_world_data()
        for _l in wdata.get("locations", []):
            if _l.get("id") == location_id:
                if danger_level is not None:
                    try:
                        _l["danger_level"] = max(0, min(5, int(danger_level)))
                    except (TypeError, ValueError):
                        pass
                if event_settings is not None:
                    _l["event_settings"] = event_settings
                if outfit_type is not None:
                    _l["outfit_type"] = (outfit_type or "").strip()
                if decency is not None:
                    _v = (decency or "").strip().lower()
                    _l["decency"] = _v if _v in ("public", "private", "nude_ok") else ""
                if style_hint is not None:
                    _l["style_hint"] = (style_hint or "").strip()
                if swim_allowed is not None:
                    _l["swim_allowed"] = bool(swim_allowed)
                if activity_hint is not None:
                    _l["activity_hint"] = (activity_hint or "").strip()
                if knowledge_item_id is not None:
                    _l["knowledge_item_id"] = (knowledge_item_id or "").strip()
                if passable is not None:
                    _l["passable"] = bool(passable)
                if entry_room is not None:
                    _l["entry_room"] = (entry_room or "").strip()
                if indoor is not None:
                    _v = (indoor or "").strip().lower()
                    _l["indoor"] = _v if _v in ("indoor", "outdoor") else ""
                break
        _save_world_data(wdata)

    updated = get_location_by_id(location_id)
    return {"status": "success", "location": updated}


# --- World-level settings ---------------------------------------------------

def build_world_settings_payload() -> Dict[str, Any]:
    """Return world settings + pose settings."""
    from app.models.world import (
        get_world_temperature, get_world_weather,
        get_world_setting, is_pose_system_active,
        WORLD_TEMPERATURE_VALUES, WORLD_WEATHER_VALUES,
    )
    return {
        "world": {
            "temperature": get_world_temperature(),
            "weather": get_world_weather(),
        },
        "pose": {
            "system_active": is_pose_system_active(),
            "variant_match_threshold": float(
                get_world_setting("pose.variant_match_threshold", "0.75")
                or "0.75"
            ),
            "max_variants_per_char": int(
                get_world_setting("pose.max_variants_per_char", "20")
                or "20"
            ),
        },
        "news": {
            # Presentation style of the player news channel.
            "style": get_world_setting("news.style", "modern") or "modern",
            "title": get_world_setting("news.title", "") or "",
        },
        "choices": {
            "temperature": list(WORLD_TEMPERATURE_VALUES),
            "weather":     list(WORLD_WEATHER_VALUES),
            "news_style":  ["modern", "newspaper", "flyer"],
        },
    }


def apply_world_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    """Set world settings + pose settings from a parsed request body."""
    from app.models.world import (
        set_world_temperature, set_world_weather, set_pose_system_active,
        set_world_setting, WORLD_TEMPERATURE_VALUES, WORLD_WEATHER_VALUES,
    )
    world = data.get("world") or {}
    pose = data.get("pose") or {}
    news = data.get("news") or {}
    if "style" in news:
        v = (news.get("style") or "").strip().lower()
        if v in ("modern", "newspaper", "flyer"):
            set_world_setting("news.style", v)
    if "title" in news:
        set_world_setting("news.title", (news.get("title") or "").strip())
    if "temperature" in world:
        v = (world.get("temperature") or "").strip().lower()
        if v in WORLD_TEMPERATURE_VALUES:
            set_world_temperature(v)
    if "weather" in world:
        v = (world.get("weather") or "").strip().lower()
        if v in WORLD_WEATHER_VALUES:
            set_world_weather(v)
    if "system_active" in pose:
        set_pose_system_active(bool(pose.get("system_active")))
    if "variant_match_threshold" in pose:
        try:
            t = float(pose.get("variant_match_threshold"))
            t = max(0.0, min(1.0, t))
            set_world_setting("pose.variant_match_threshold", str(t))
        except (TypeError, ValueError):
            pass
    if "max_variants_per_char" in pose:
        try:
            n = int(pose.get("max_variants_per_char"))
            n = max(1, min(200, n))
            set_world_setting("pose.max_variants_per_char", str(n))
        except (TypeError, ValueError):
            pass
    return {"status": "ok"}


def list_condition_filters() -> Dict[str, Any]:
    """List all filter ids from prompt_filters (shared + world overlay).

    The filter ``id`` is at the same time the canonical condition name:
    as soon as it appears as a tag in the profile (active_conditions), the
    corresponding filter triggers implicitly. An additional ``condition``
    expression on the filter (e.g. ``stamina<10``) acts as a second
    auto-trigger.

    Returns: {"conditions": [{"name": "drunk", "label": "...", "icon": "🍺"}, ...]}
    """
    from app.core.prompt_filters import load_filters
    seen: Dict[str, Dict[str, Any]] = {}
    for f in load_filters():
        if not f.get("enabled", True):
            continue
        fid = (f.get("id") or "").strip().lower()
        if not fid or fid in seen:
            continue
        seen[fid] = {
            "name": fid,
            "label": (f.get("label") or "").strip(),
            "icon": (f.get("icon") or "").strip(),
        }
    return {"conditions": sorted(seen.values(), key=lambda e: e["name"])}


# === Location gallery ===

def build_gallery_payload(location_name: str) -> Dict[str, Any]:
    """List all gallery images of a location (with background status)."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name
    images = list_gallery_images(location_name)
    bg_images = get_background_images(loc_id)
    image_rooms = get_gallery_image_rooms(loc_id)
    image_types = get_gallery_image_types(loc_id)
    image_metas = get_gallery_image_metas(loc_id)
    prompts = get_all_gallery_prompts(loc_id)
    # Rooms for the dropdown in the frontend
    location_rooms = []
    if loc:
        for room in loc.get("rooms", []):
            location_rooms.append({
                "id": room.get("id", ""),
                "name": room.get("name", ""),
            })
    return {
        "images": images,
        "background_images": bg_images,
        "image_prompts": prompts,
        "image_rooms": image_rooms,
        "image_types": image_types,
        "image_metas": image_metas,
        "location_rooms": location_rooms,
        "location": location_name,
    }


def build_imagegen_options() -> Dict[str, Any]:
    """Returns available image-generation backends (without character binding)."""
    from app.core.dependencies import get_skill_manager
    from app.core.prompt_adapters import get_target_model

    sm = get_skill_manager()
    imagegen = sm.get_skill("image_generation")
    if not imagegen:
        return {"options": []}

    options = []
    # Backends (CivitAI, Together, LocalAI, …). Every ENABLED backend is
    # offered — availability is resolved by the server at generation time via
    # match_backend. Do NOT pre-filter on b.available, otherwise a freshly
    # configured / not-yet-probed cloud backend disappears from the
    # "Service (match)" selection.
    for b in imagegen.backends:
        if not b.instance_enabled:
            continue
        opt = {
            "type": "backend",
            "name": b.name,
            "label": b.name if b.available else f"{b.name} (offline?)",
            "available": b.available,
            # Purpose category (e.g. "inpaint") + default prompt — lets the
            # Fit/Edge dialog offer inpaint backends and prefill the prompt.
            "category": getattr(b, "category", "") or "",
            "image_family": getattr(b, "image_family", "") or "",
            "prompt": getattr(b, "default_prompt", "") or "",
            "ref_slot_count": int(getattr(b, "ref_slot_count", 0) or 0),
            "target_model": get_target_model(
                getattr(b, "image_family", "") or "", getattr(b, "model", "") or ""),
            # Terrain-hint parameter — the dialog only appends the hint if True.
            "terrain_hint": bool(getattr(b, "terrain_hint", False)),
        }
        # Backend with a model list (e.g. Together.ai) — offer as a selection.
        backend_models = getattr(b, 'available_models', [])
        if backend_models:
            opt["models"] = backend_models
            opt["default_model"] = getattr(b, 'model', backend_models[0])
        # LoRA selection in the image-gen dialog. Source: with lora_url set, the
        # LoRAs fetched from the backend endpoint, otherwise the per-world
        # LoRA library (endpoint-filtered). Transfer: localai as <lora:> prompt
        # tag, openai_diffusion dynamically as lora_NN/strength_NN params.
        if b.api_type in ("localai", "openai_diffusion"):
            opt["has_loras"] = True
            _be_loras = getattr(b, "available_loras", None)
            if getattr(b, "lora_url", "") and _be_loras:
                opt["lora_options"] = _be_loras
            else:
                from app.core.config import get_lora_library_names
                opt["lora_options"] = get_lora_library_names(b.name)
        options.append(opt)
    # mapfit default prompts per family — the Fit/Edge dialog prefills the
    # prompt field with these (instead of the former terrain/edge hint).
    from app.core import config as _cfg
    mapfit_prompts = {}
    for _fam in ("natural", "keywords"):
        try:
            _r = _cfg.resolve_use_case_style("mapfit", _fam)
            mapfit_prompts[_fam] = _r.get("prompt_style", "")
        except Exception:
            mapfit_prompts[_fam] = ""
    # Default preselection for locations
    loc_default = os.environ.get("LOCATION_IMAGEGEN_DEFAULT", "").strip()
    result = {"options": options, "mapfit_prompts": mapfit_prompts}
    # Fit/match-edges: imagegen target (backend match spec, read-only in the Fit dialog).
    result["mapfit_imagegen_default"] = (os.environ.get("MAPFIT_IMAGEGEN_DEFAULT") or "").strip()
    # Global outfit default (match spec, e.g. "backend:LocalAI-Flux") — the
    # character-render match UI shows it when no override is set.
    result["outfit_imagegen_default"] = (os.environ.get("OUTFIT_IMAGEGEN_DEFAULT") or "").strip()
    if loc_default:
        result["default_location"] = loc_default
    return result


def delete_gallery_image(location_name: str, image_name: str) -> Dict[str, Any]:
    """Delete a gallery image (by id or name); the route checks path traversal."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    image_path.unlink()

    # If the image was marked as a background, remove the marker
    remove_background_image(loc_id, image_name)
    remove_gallery_image_room(loc_id, image_name)
    remove_gallery_image_type(loc_id, image_name)
    # Detach any dangling map_image/map_image_2d choice of this image from all
    # cells (otherwise the cell shows the first tile instead of the chosen one).
    from app.models.world import clear_map_image_references
    clear_map_image_references(image_name)

    return {"status": "success", "deleted": image_name}


def toggle_gallery_background(location_name: str, image_name: str) -> Dict[str, Any]:
    """Toggle whether a gallery image is eligible as a background."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    is_eligible = toggle_background_image(loc_id, image_name)

    return {"status": "success", "image": image_name, "is_background": is_eligible}


def assign_gallery_image_room(location_name: str, image_name: str,
                              room_id: str) -> Dict[str, Any]:
    """Set the room of a gallery image."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    set_gallery_image_room(loc_id, image_name, room_id)
    return {"status": "success", "image": image_name, "room": room_id}


def assign_gallery_image_type(location_name: str, image_name: str,
                              image_type: str) -> Dict[str, Any]:
    """Set the type of a gallery image (day/night/map or empty)."""
    if image_type and image_type not in ("day", "night", "map_2d"):
        raise HTTPException(status_code=400, detail="Typ muss 'day', 'night', 'map_2d' oder leer sein")

    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    set_gallery_image_type(loc_id, image_name, image_type)
    return {"status": "success", "image": image_name, "type": image_type}


# === Background images ===

def _location_image_width() -> int:
    try:
        return int(os.environ.get("LOCATION_IMAGE_WIDTH", "1280"))
    except (TypeError, ValueError):
        return 1280


def _location_image_height() -> int:
    try:
        return int(os.environ.get("LOCATION_IMAGE_HEIGHT", "720"))
    except (TypeError, ValueError):
        return 720


def resolve_background_path(location_name: str, room: str = "", hour: int = -1,
                            file: str = "") -> Optional[Path]:
    """Resolve the background image of a location (by id or name).

    With an active disruption/danger event that has a rendered image_path,
    the event image is served. Within the resolve-linger window the
    resolved_image_path. Otherwise the normal location background.
    Multi-room: the swap applies to all rooms of the location (consistent
    with the location-wide block rule).

    ``file`` pins a concrete background image (used by the /play frontend so
    that figure positions stick to the exact displayed image). An active
    event image takes precedence and ignores ``file``.
    """
    # location_name can be an id or a name — the event swap needs the id.
    bg_path: Optional[Path] = None
    try:
        from app.core.event_images import get_effective_background_event
        from app.models.world import resolve_location
        _loc = resolve_location(location_name)
        _loc_id = _loc.get("id", "") if _loc else ""
        if _loc_id:
            bg_path = get_effective_background_event(_loc_id)
    except Exception as _e:
        logger.debug("event-bg lookup failed: %s", _e)

    if (not bg_path or not bg_path.exists()) and file:
        bg_path = get_background_file_path(location_name, file)
    if not bg_path or not bg_path.exists():
        bg_path = get_background_path(location_name, room=room, hour=hour)
    return bg_path


def save_uploaded_background(location_name: str, filename: str, content: bytes,
                             room_id: str) -> Dict[str, Any]:
    """Store an uploaded background image for a location (optional room).

    Saves into the location's gallery, registers it as a background and maps
    it to the room if given — the same save/register path as generation.
    """
    from app.models.world import (get_gallery_dir, toggle_background_image,
                                   set_gallery_image_room)
    from app.core.timeutils import utc_now
    from pathlib import Path as _Path

    location = resolve_location(location_name)
    if not location:
        raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")
    loc_id = location.get("id") or location_name

    fname = (filename or "").lower()
    ext = _Path(fname).suffix or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail="Format nicht unterstützt")

    gallery_dir = get_gallery_dir(loc_id)
    gallery_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{loc_id}_{utc_now().strftime('%Y%m%d%H%M%S')}{ext}"
    (gallery_dir / image_name).write_bytes(content)

    toggle_background_image(loc_id, image_name)
    if room_id:
        try:
            set_gallery_image_room(location_name, image_name, room_id)
        except Exception as e:
            logger.debug("set_gallery_image_room beim Upload fehlgeschlagen: %s", e)
    return {"status": "success", "image": image_name, "room_id": room_id}


async def generate_location_background(location_name: str,
                                       custom_prompt: str) -> Dict[str, Any]:
    """Generate a background image for a location via an image backend (by id or name)."""
    # Resolve the location by id or name
    location = resolve_location(location_name)
    if not location:
        raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

    description = location.get("description", location_name)

    # Build the prompt
    if custom_prompt:
        prompt = custom_prompt
    else:
        prompt = (
            f"{description}, wide angle establishing shot, no people, "
            f"atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio"
        )

    # Get the image backend (cheapest available one)
    from app.core.dependencies import get_skill_manager

    skill_manager = get_skill_manager()
    img_skill = None
    for skill in skill_manager.skills:
        if getattr(skill, 'SKILL_ID', '') == "image_generation":
            img_skill = skill
            break

    if not img_skill:
        raise HTTPException(status_code=503, detail="ImageGeneration Skill nicht verfuegbar")

    backend = img_skill._select_backend()
    if not backend:
        raise HTTPException(status_code=503, detail="Kein Image-Backend verfuegbar")

    # Generate image (blocking, in a thread) — style/negative from the use case.
    from app.core import config as _cfg
    _ucp = _cfg.resolve_use_case_style(
        "location", getattr(backend, "image_family", "") or "",
        backend_model=getattr(backend, "model", "") or "")
    full_prompt = f"{_ucp['prompt_style']}, {prompt}" if _ucp.get("prompt_style") else prompt
    negative = _ucp.get("prompt_negative", "")
    # Location background: full resolution — used as a background scene
    # image, no downscale.
    params = {"width": _location_image_width(), "height": _location_image_height()}

    # Fresh seed per call — avoids backend-side cache hits
    # (memory: feedback_no_new_image_sentinel).
    import random as _rnd
    params["seed"] = _rnd.randint(1, 2**31 - 1)

    # Backend fallback engine: tries primary, falls back to the next
    # available backend on failure. Local GPU backends go through the
    # GPU provider queue → never two in parallel per backend.
    def _op(b):
        if getattr(b, "api_type", "") == "a1111":
            from app.core.llm_queue import get_llm_queue, Priority as _P
            return get_llm_queue().submit_gpu_task(
                provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                callable_fn=lambda: b.generate(full_prompt, negative, params),
                agent_name=location.get("name", location_name), gpu_type=b.api_type)
        return b.generate(full_prompt, negative, params)
    try:
        images, backend = await asyncio.to_thread(
            lambda: img_skill.run_with_fallback(
                primary_backend=backend,
                op=_op,
                character_name=""))
    except RuntimeError as _err:
        raise HTTPException(status_code=500, detail=str(_err))

    if not images:
        raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

    # Save into the gallery + reference as background
    import time
    loc_id = location.get("id", location_name)
    gallery_dir = get_gallery_dir(loc_id)
    gallery_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{int(time.time())}.png"
    image_path = gallery_dir / image_name
    image_path.write_bytes(images[0])

    # Automatically mark as background
    toggle_background_image(loc_id, image_name)

    logger.info("Bild generiert + als Hintergrund markiert: %s (%s) -> gallery/%s/%s", location['name'], loc_id, loc_id, image_name)
    return {"status": "success", "location": location["name"], "location_id": loc_id}


def clear_location_backgrounds(location_name: str) -> Dict[str, Any]:
    """Delete the background-image references of a location (by id or name)."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name
    # Remove all background markers
    for img in get_background_images(loc_id):
        toggle_background_image(loc_id, img)
    return {"status": "success", "location": location_name}


# === Map / tiles / map-fit helpers ===

_MAP_MEDIA_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg', '.webp': 'image/webp'}


def _serve_map_icon(location_name: str, image_type: str, override_field: str):
    """Serves the map icon of a location for the given gallery type.

    Per-cell choice: if ``override_field`` is set on the (cloned) location and
    the file exists in the owner gallery, EXACTLY this image is served — so
    with several images every map cell can show its own one. Otherwise fall
    back to the first image tagged as ``image_type``.
    """
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    loc_id = loc.get("id", "")
    if not loc_id:
        raise HTTPException(status_code=404, detail="Kein Karten-Bild vorhanden")

    # Clones share the gallery of their template (owner_id = template id).
    from app.models.world import _gallery_owner_id
    owner_id = _gallery_owner_id(location_name) or loc_id
    gallery_dir = get_gallery_dir(owner_id)

    # 1) Image explicitly chosen per location/clone (if set + file exists).
    chosen = (loc.get(override_field) or "").strip()
    if chosen:
        p = gallery_dir / chosen
        if p.exists():
            return FileResponse(str(p),
                                media_type=_MAP_MEDIA_TYPES.get(p.suffix.lower(), 'image/png'),
                                headers={"Cache-Control": "no-cache"})

    # 2) Fallback: first image tagged as image_type.
    image_types = get_gallery_image_types(owner_id)
    map_images = [img for img, t in image_types.items() if t == image_type]
    if not map_images:
        raise HTTPException(status_code=404, detail="Kein Karten-Bild vorhanden")
    for img_name in map_images:
        img_path = gallery_dir / img_name
        if img_path.exists():
            return FileResponse(str(img_path),
                                media_type=_MAP_MEDIA_TYPES.get(img_path.suffix.lower(), 'image/png'),
                                headers={"Cache-Control": "max-age=300"})
    raise HTTPException(status_code=404, detail="Kein Karten-Bild vorhanden")


# Map fit (neighbor inpaint): generation canvas size (16-GB-friendly) + target
# tile size the cut-out center is upscaled to.
# Default output size: the fit/edge result (center cell) is ALWAYS scaled to
# this edge length (1024). The 3x3 canvas, however, is composed in the
# ORIGINAL resolution of the source tiles (see _place_neighbors) — the input
# is NOT reduced anymore; only the cropped center is normalized to
# MAP_FIT_OUT_TILE at the end. (Previously the whole canvas was capped at
# 1024, i.e. every tile shrunk to ~341px.)
MAP_FIT_OUT_TILE = 1024
# Safety cap per tile (prevents an absurdly large canvas/OOM with unusually
# high-resolution source tiles). 0 = no limit.
MAP_FIT_MAX_TILE = 1536
# Fit: fraction of the neighbor tile placed as context border around the
# center. Smaller = closer to native and sharper, but less blend context.
# Flexible. 0.1875 → with a native 1024 tile the center stays full 1024 and
# the canvas ~1408.
MAP_FIT_NEIGHBOR_FRAC = 0.1875
# Fit: Flux-friendly upper bound for the WHOLE canvas (generation
# resolution). Flux is optimal around ~1 MP (1024px); noticeably above that
# the image gets soft. The tile is chosen so that tile + 2*border <= this
# value (center as large as possible, at most native). Rounded to a multiple
# of 16 (Flux/VAE requirement). 1408 = ~2 MP, matches frac 0.1875 with a full
# 1024 center. Fit only — edge keeps using full tiles.
MAP_FIT_CANVAS_MAX = 1408
# Fit (edit models like Qwen only): cut out only the inner fraction of the
# center. Edit models invent "more surroundings" at the border of the
# regenerated area — the inner core is clean. 1.0 = whole center (like fill
# models), 0.7 = inner 70 %.
MAP_FIT_INNER_CROP = 0.7
# The inpaint workflows no longer receive a crop mask — the workflow returns
# the full (inpainted) canvas and the BACKEND cuts out the center and scales
# it to MAP_FIT_OUT_TILE.
# Mask margin beyond the gray area (so the model blends in the edges) —
# tested: gray-fill/edit models (Qwen/Flux2) +5%, Flux-Dev-Fill (fill model)
# +2% (slightly better).
MAP_BLEND_MASK_GROW_GRAY = 1.05
MAP_BLEND_MASK_GROW_FILL = 1.02


def _resolve_map_icon_path(loc: Dict[str, Any], field: str = "map_image_2d",
                           image_type: str = "map_2d"):
    """Path of the per-cell chosen 2D map tile (otherwise first tagged one).
    Reused logic from :func:`_serve_map_icon`, without FileResponse."""
    from app.models.world import _gallery_owner_id, get_gallery_image_types
    loc_id = loc.get("id", "")
    if not loc_id:
        return None
    owner_id = _gallery_owner_id(loc_id) or loc_id
    gallery_dir = get_gallery_dir(owner_id)
    chosen = (loc.get(field) or "").strip()
    if chosen and (gallery_dir / chosen).exists():
        return gallery_dir / chosen
    for fn, tp in (get_gallery_image_types(owner_id) or {}).items():
        if tp == image_type and (gallery_dir / fn).exists():
            return gallery_dir / fn
    return None


def _save_canvas_with_alpha(canvas, mask, path: str) -> None:
    """Saves the canvas as RGBA with the mask in the ALPHA channel: inpaint
    region (mask white) -> transparent (alpha 0), rest opaque. Matches
    ComfyUI-LoadImage (``MASK = 1 - alpha``). The RGB part stays unchanged
    (non-breaking)."""
    from PIL import ImageOps
    rgba = canvas.convert("RGBA")
    rgba.putalpha(ImageOps.invert(mask.convert("L")))
    rgba.save(path)


def _save_rgba_mask(mask, path: str) -> None:
    """RGBA mask image (same dimension as the canvas): white area, the marked
    region (``mask`` white) sits in the ALPHA channel as transparent — like
    the canvas. ComfyUI ``MASK = 1 - alpha`` yields exactly this region (e.g.
    the center cell for the crop, independent of the inpaint mask)."""
    from PIL import Image, ImageOps
    rgba = Image.new("RGBA", mask.size, (255, 255, 255, 255))
    rgba.putalpha(ImageOps.invert(mask.convert("L")))
    rgba.save(path)


def _place_neighbors(location: Dict[str, Any], border_frac: float = 1.0,
                     canvas_max: Optional[int] = None):
    """Builds the canvas (gray, center = own tile) with the neighbor tiles around it.

    ``border_frac`` = fraction of the neighbor tile used as context border
    (1.0 = whole tile → classic 3*tile canvas; 0.25 = narrow border).
    Per neighbor ONLY the strip facing the center (orthogonal) or the corner
    (diagonal) is inserted — this keeps the generation closer to the native
    resolution and therefore sharper.

    ``canvas_max`` (optional): upper bound for the WHOLE canvas (tile + 2*border).
    If set, the tile is chosen so the canvas stays below it (center as large
    as possible, at most native) and tile/border are rounded to multiples of
    16 (Flux/VAE-compatible). None = old behavior (edge).

    Returns ``(canvas, tile, border, present)`` or ``None``. ``border`` =
    border in px, ``present`` = set of the present neighbor directions (dx, dy)."""
    from PIL import Image
    from app.models.world import list_locations
    gx, gy = location.get("grid_x"), location.get("grid_y")
    if gx is None or gy is None:
        return None
    by_pos = {}
    for loc in list_locations():
        lx, ly = loc.get("grid_x"), loc.get("grid_y")
        if lx is not None and ly is not None:
            by_pos[(lx, ly)] = loc
    # Load tiles in ORIGINAL resolution (no downscale). Uniform cell size
    # = largest native edge length (own tile + neighbors); smaller ones are
    # upscaled.
    loaded = {}   # (dx, dy) -> (img, rot)
    native_max = 0
    own_p = _resolve_map_icon_path(location)
    if own_p:
        try:
            with Image.open(own_p) as _o:
                native_max = max(native_max, _o.width, _o.height)
        except Exception:
            pass
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nb = by_pos.get((gx + dx, gy + dy))
            p = _resolve_map_icon_path(nb) if nb else None
            if not p:
                continue
            try:
                img = Image.open(p).convert("RGB")
                native_max = max(native_max, img.width, img.height)
                loaded[(dx, dy)] = (img, int(nb.get("map_rotation_2d") or 0))
            except Exception as _e:
                logger.warning("Nachbar-Tile %s nicht ladbar: %s", p, _e)
    if not loaded:
        return None
    tile = native_max or MAP_FIT_OUT_TILE
    if MAP_FIT_MAX_TILE and tile > MAP_FIT_MAX_TILE:
        logger.info("Map-Fit: Tile-Aufloesung %dpx auf MAP_FIT_MAX_TILE=%dpx begrenzt",
                    tile, MAP_FIT_MAX_TILE)
        tile = MAP_FIT_MAX_TILE
    frac = max(0.05, min(1.0, border_frac))
    if canvas_max:
        # Cap the tile so the whole canvas (tile + 2*border) stays <= canvas_max
        # → Flux-compatible generation resolution. Center as large as
        # possible (at most native). Multiples of 16 (Flux/VAE).
        tile = min(tile, int(canvas_max / (1 + 2 * frac)))
        tile = max(256, (tile // 16) * 16)
        border = max(16, (int(round(tile * frac)) // 16) * 16)
    else:
        border = max(1, int(round(tile * frac)))
    csize = tile + 2 * border
    canvas = Image.new("RGB", (csize, csize), (128, 128, 128))
    present = set()
    for (dx, dy), (img, rot) in loaded.items():
        im = img if img.size == (tile, tile) else img.resize((tile, tile))
        if rot:
            im = im.rotate(-rot, expand=False, fillcolor=(128, 128, 128))
        # Source crop: only the neighbor's strip/corner facing the center.
        sx0 = (tile - border) if dx < 0 else 0
        sx1 = tile if dx < 0 else (border if dx > 0 else tile)
        sy0 = (tile - border) if dy < 0 else 0
        sy1 = tile if dy < 0 else (border if dy > 0 else tile)
        strip = im.crop((sx0, sy0, sx1, sy1))
        # Target position in the canvas (left/top = 0, center = border, right/bottom = border+tile).
        px = 0 if dx < 0 else (border + tile if dx > 0 else border)
        py = 0 if dy < 0 else (border + tile if dy > 0 else border)
        canvas.paste(strip, (px, py))
        present.add((dx, dy))
    logger.info("Map-Fit: Canvas komponiert — Tile %dpx, Border %dpx (frac %.2f), Canvas %dpx",
                tile, border, frac, csize)
    return canvas, tile, border, present


def _finalize_blend(canvas, inpaint_mask, tile, border, present, crop_empty: bool,
                    inner_crop: float = 1.0):
    """Common finish for fit/edge. With ``crop_empty`` cuts off COMPLETELY
    empty outer borders (also for edge at the map border) and saves:
      - canvas (pure RGB)          -> cpath  (input_reference_image)
      - inpaint mask as L          -> mpath  (input_mask)
    NO crop mask anymore — the center is NOT cut out in the workflow anymore
    but by the backend from the returned image. Instead we deliver the center
    cell as FRACTIONS (x0,y0,x1,y1) of the (possibly trimmed) canvas, robust
    against the workflow's output resolution.

    ``inner_crop`` < 1.0 cuts out only the inner fraction of the center
    (around the midpoint) — against the "invented outside" ring of edit models.

    Geometry: center (own tile) sits at ``border``, canvas = tile + 2*border.
    Returns ``(cpath, mpath, tile, crop_frac)``."""
    import tempfile
    csize = tile + 2 * border
    left, top, right, bottom = 0, 0, csize, csize
    if crop_empty:
        # Only cut off the outer border if NO neighbor lies on that side
        # (orthogonal or diagonal) — otherwise corners would remain.
        left = 0 if any(d[0] < 0 for d in present) else border
        right = csize if any(d[0] > 0 for d in present) else csize - border
        top = 0 if any(d[1] < 0 for d in present) else border
        bottom = csize if any(d[1] > 0 for d in present) else csize - border
        if (left, top, right, bottom) != (0, 0, csize, csize):
            canvas = canvas.crop((left, top, right, bottom))
            inpaint_mask = inpaint_mask.crop((left, top, right, bottom))
            logger.info("Map-Blend: leere Raender abgeschnitten -> Canvas %dx%d",
                        right - left, bottom - top)
    # Center cell (middle) as fractions of the trimmed canvas — optionally
    # only the inner fraction (inner_crop) around the midpoint.
    cw, ch = canvas.size  # = (right-left, bottom-top)
    cx0, cy0 = border - left, border - top
    _icf = max(0.05, min(1.0, inner_crop))
    _cxc, _cyc = cx0 + tile / 2.0, cy0 + tile / 2.0
    _half = (tile / 2.0) * _icf
    crop_frac = ((_cxc - _half) / cw, (_cyc - _half) / ch,
                 (_cxc + _half) / cw, (_cyc + _half) / ch)
    cpath = tempfile.NamedTemporaryFile(suffix="_mapblend_canvas.png", delete=False).name
    mpath = tempfile.NamedTemporaryFile(suffix="_mapblend_mask.png", delete=False).name
    canvas.convert("RGB").save(cpath)
    inpaint_mask.save(mpath)
    return cpath, mpath, tile, crop_frac


def _compose_neighbor_canvas(location: Dict[str, Any], crop_empty: bool = False,
                             mask_grow: float = MAP_BLEND_MASK_GROW_GRAY,
                             border_frac: float = MAP_FIT_NEIGHBOR_FRAC,
                             full_mask: bool = False,
                             inner_crop: float = MAP_FIT_INNER_CROP):
    """Fit: canvas (neighbor borders, gray center) + inpaint mask = center * mask_grow.
    ``border_frac`` controls the border width (smaller = closer to native,
    sharper). With ``crop_empty`` cuts off empty outer borders. Returns
    ``(cpath, mpath, tile, crop_frac)`` or ``None``.

    ``mask_grow``: how far the mask extends beyond the center cell
    (1.05 = +5% for gray-fill/edit models, 1.02 = +2% for Flux-Dev-Fill).
    ``full_mask``: mask the WHOLE area instead of only the center — needed for
    edit models (Qwen-Edit), which with a partial mask copy the narrow
    neighbor strip into the center ("neighbor border pulled into the image")."""
    from PIL import Image, ImageDraw
    placed = _place_neighbors(location, border_frac=border_frac,
                             canvas_max=MAP_FIT_CANVAS_MAX)
    if not placed:
        return None
    canvas, tile, border, present = placed
    if full_mask:
        # Edit model (Qwen): whole area editable → coherent regeneration
        # instead of strip copy. The center crop (crop_frac) stays unchanged.
        mask = Image.new("L", canvas.size, 255)
    else:
        mask = Image.new("L", canvas.size, 0)
        # The mask slightly overlaps into the neighbors so the model blends
        # the tile edges. Still only the EXACT center is cut out.
        _m = int(round(tile * (mask_grow - 1) / 2))
        ImageDraw.Draw(mask).rectangle(
            [border - _m, border - _m, border + tile - 1 + _m, border + tile - 1 + _m], fill=255)
    # inner_crop: cut out only the inner core of the center (freely
    # configurable per backend). With a partial mask (full_mask=False) the
    # ring is real anyway → 1.0.
    _inner = inner_crop if full_mask else 1.0
    return _finalize_blend(canvas, mask, tile, border, present, crop_empty, inner_crop=_inner)


def build_fit_canvas_png(loc: Dict[str, Any]) -> bytes:
    """Preview PNG of the 3x3 neighbor canvas that goes into the workflow as
    input_reference_image for "fit to neighbors" (gray center = gets
    inpainted). 404 if no neighbors with a tile / no grid position."""
    comp = _compose_neighbor_canvas(loc)
    if not comp:
        raise HTTPException(status_code=404, detail="Keine Nachbarn mit Tile")
    cpath = comp[0]
    try:
        data = Path(cpath).read_bytes()
    finally:
        for _p in comp[:2]:  # cpath, mpath (paths; comp[3] is the crop fraction)
            try:
                os.remove(_p)
            except Exception:
                pass
    return data


# Edge match (align edges): frame mask width + solid core at the edge.
# BLEND_FRAC = how far the inpaint band reaches inward from each chosen edge
# (fraction of the tile width). Keep it low — with SEVERAL edges the bands
# overlap; a band that is too wide (0.45) eats ~70% of the tile with 2
# neighbors (everything gray). 0.22 -> narrow edge frame, center is kept.
MAP_EDGE_BLEND_FRAC = 0.22
MAP_EDGE_CORE_FRAC = 0.30
_EDGE_DIRS = (("north", 0, -1), ("south", 0, 1), ("east", 1, 0), ("west", -1, 0))


def _analyze_tile_terrain(loc: Dict[str, Any]):
    """Vision terrain phrase of the CURRENT 2D tile, cached per tile filename
    in the gallery meta. ``None`` if vision is off / no tile / error. This way
    north/south/east/west describe the real image, not the possibly outdated
    text description. Re-analysis only for a new tile (different filename)."""
    if str(os.environ.get("MAP_TILE_VISION_ANALYSIS", "")).strip().lower() not in ("1", "true", "yes", "on"):
        return None
    tp = _resolve_map_icon_path(loc)
    if not tp:
        return None
    from app.models.world import (_gallery_owner_id, get_gallery_image_metas,
                                  set_gallery_image_meta)
    owner_id = _gallery_owner_id(loc.get("id", "")) or loc.get("id", "")
    fname = tp.name
    metas = get_gallery_image_metas(owner_id) or {}
    cached = (metas.get(fname) or {}).get("terrain")
    if cached:
        return cached
    from app.core.dependencies import get_skill_manager
    skill = get_skill_manager().get_skill("image_generation")
    if not skill:
        return None
    term = skill.describe_map_tile(str(tp))
    if term:
        _m = dict(metas.get(fname) or {})
        _m["terrain"] = term
        set_gallery_image_meta(owner_id, fname, _m)
        logger.info("Map-Tile-Vision: %s -> %s", fname, term)
    return term


def _terrain_term(loc: Dict[str, Any]) -> str:
    """Short terrain term of a tile: vision analysis of the CURRENT tile (if
    enabled), otherwise its own 2D map prompt, otherwise description,
    otherwise name — first statement, ~80 chars at a word boundary, without
    dangling function words."""
    term = " ".join((_analyze_tile_terrain(loc) or loc.get("image_prompt_map_2d")
                     or loc.get("description") or loc.get("name") or "").split())
    for _sep in (".", ";"):
        if _sep in term:
            term = term.split(_sep)[0]
    if len(term) > 80:
        _head = term[:80]
        term = _head.rsplit(",", 1)[0] if "," in _head else _head.rsplit(" ", 1)[0]
    term = term.rstrip(",.; ")
    _fw = {"with", "on", "in", "a", "an", "the", "of", "and", "to", "at",
           "for", "from", "by", "as", "or"}
    _words = term.split()
    while _words and _words[-1].lower() in _fw:
        _words.pop()
    return " ".join(_words)


def _neighbor_sides(location: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{side: neighbor-loc} for the 4 orthogonal sides with a neighbor that
    has a 2D tile (no entry otherwise)."""
    from app.models.world import list_locations
    gx, gy = location.get("grid_x"), location.get("grid_y")
    if gx is None or gy is None:
        return {}
    by_pos = {(l.get("grid_x"), l.get("grid_y")): l for l in list_locations()
              if l.get("grid_x") is not None and l.get("grid_y") is not None}
    out: Dict[str, Dict[str, Any]] = {}
    for side, dx, dy in _EDGE_DIRS:
        nb = by_pos.get((gx + dx, gy + dy))
        if nb and _resolve_map_icon_path(nb):
            out[side] = nb
    return out


def _neighbor_terrain_hint(location: Dict[str, Any]) -> str:
    """Auto prompt for map fit (regenerate the gray center): one tile that
    merges all neighbor terrains — same quality language as the edge prompt
    (color/tone/style alignment), just for the whole tile instead of only the
    edges."""
    parts = [f"{_terrain_term(nb)} to the {side}" for side, nb in _neighbor_sides(location).items()
             if _terrain_term(nb)]
    if not parts:
        return ""
    return ("top-down orthographic map tile blending together the surrounding "
            "terrain — " + ", ".join(parts) + "; colors, tones and art style merge "
            "smoothly across the whole tile, cohesive unified palette and lighting, "
            "no hard seams")


def _edge_transition_prompt(location: Dict[str, Any], sides=None) -> str:
    """Prompt for "align edges": the existing center tile whose borders
    transition into the chosen neighbor terrains (color/tone/style merge)."""
    avail = _neighbor_sides(location)
    use = [s for s in (sides or list(avail)) if s in avail]
    if not use:
        return ""
    parts = [f"{_terrain_term(avail[s])} to the {s}" for s in use if _terrain_term(avail[s])]
    return ("top-down orthographic map tile; its edges blend into the adjacent "
            "terrain — " + ", ".join(parts) + "; colors, tones and art style merge "
            "smoothly across the edges, cohesive unified palette and lighting, no hard seams")


def _compose_edge_canvas(location: Dict[str, Any], sides=None, gray_fill: bool = False):
    """Like :func:`_compose_neighbor_canvas` (3x3, real neighbors around), BUT
    the center is the REAL tile and the mask is a FRAME (distance transform)
    only for the chosen sides with a neighbor: solid at the edge, evenly down
    to 0 towards the center. Returns (canvas_path, mask_path, tile) or None."""
    import numpy as np
    from PIL import Image
    avail = _neighbor_sides(location)
    use = [s for s in (sides or list(avail)) if s in avail]
    # Edge uses full neighbor tiles (border_frac=1.0 → border == tile, classic
    # 3*tile canvas) — the frame mask needs the full neighbor context.
    placed = _place_neighbors(location, border_frac=1.0)
    if not placed or not use:
        return None
    canvas, tile, border, present = placed
    # Fill the center with the real tile (instead of gray).
    tp = _resolve_map_icon_path(location)
    if tp:
        t_img = Image.open(tp).convert("RGB").resize((tile, tile))
        rot = int(location.get("map_rotation_2d") or 0)
        if rot:
            t_img = t_img.rotate(-rot, expand=False, fillcolor=(128, 128, 128))
        canvas.paste(t_img, (border, border))
    # Frame mask via distance transform.
    W, H = canvas.size
    cx0, cy0, cx1, cy1 = border, border, border + tile, border + tile
    blend = max(1, int(tile * MAP_EDGE_BLEND_FRAC))
    core = max(0, int(blend * MAP_EDGE_CORE_FRAC))
    ys, xs = np.mgrid[0:H, 0:W]
    dist = np.full((H, W), float(blend + 1))
    if "west" in use:
        dist = np.minimum(dist, xs - cx0)
    if "east" in use:
        dist = np.minimum(dist, (cx1 - 1) - xs)
    if "north" in use:
        dist = np.minimum(dist, ys - cy0)
    if "south" in use:
        dist = np.minimum(dist, (cy1 - 1) - ys)
    inside = (xs >= cx0) & (xs < cx1) & (ys >= cy0) & (ys < cy1)
    dist = np.where(inside, dist, float(blend + 1))
    f = np.clip((dist - core) / max(1, blend - core), 0.0, 1.0)
    sm = f * f * (3 - 2 * f)
    val = np.where(dist < core, 255.0, 255.0 * (1.0 - sm))
    val = np.where((dist >= blend) | (~inside), 0.0, val)
    mask = Image.fromarray(val.astype("uint8"), "L")
    # ONLY for edit-model inpaint (gray_fill, e.g. Qwen-Edit): color the
    # masked edge SOLID gray (same (128,128,128) as the empty fit center),
    # because Qwen "completes the gray areas" and reads them straight from the
    # reference image. Solid gray with a HARD edge (binary mask >0, NOT the
    # fading inpaint mask — no gradient). Fill models (Flux DevFill) get NO
    # gray: they use the separate input_mask and keep the real tile content.
    if gray_fill:
        _gray = Image.new("RGB", canvas.size, (128, 128, 128))
        _solid = mask.point(lambda v: 255 if v > 0 else 0)
        canvas = Image.composite(_gray, canvas.convert("RGB"), _solid)
    # Edge also cuts off empty borders (e.g. at the map border).
    return _finalize_blend(canvas, mask, tile, border, present, crop_empty=True)


# Edge match (new model): EXACTLY two adjacent tiles side by side, the seam
# filled hard gray; mask = gray strip + 5%. The workflow returns ONE image
# (same size), the backend cuts it in the middle and stores both halves in
# their respective locations. NO fill model anymore.
def _compose_edge_pair(location: Dict[str, Any], side: str,
                       mask_grow: float = MAP_BLEND_MASK_GROW_GRAY):
    """Builds the 2-tile canvas (location + neighbor in ``side``) in display
    orientation, fills the seam hard gray and creates the inpaint mask
    (gray strip + 5%). Returns ``(cpath, mpath, info)`` or None.

    ``info`` = dict(axis='x'|'y', a_first(bool), a_loc, b_loc, a_rot, b_rot, tile):
      - axis: seam axis (x = vertical seam, tiles left/right; y = horizontal).
      - a_first: is ``location`` the first half (left resp. top)?
    """
    import tempfile
    from PIL import Image
    import numpy as np
    avail = _neighbor_sides(location)
    nb = avail.get(side)
    if not nb:
        return None
    pa = _resolve_map_icon_path(location)
    pb = _resolve_map_icon_path(nb)
    if not pa or not pb:
        return None
    ia = Image.open(pa).convert("RGB")
    ib = Image.open(pb).convert("RGB")
    tile = max(ia.width, ia.height, ib.width, ib.height)
    if MAP_FIT_MAX_TILE and tile > MAP_FIT_MAX_TILE:
        tile = MAP_FIT_MAX_TILE
    a_rot = int(location.get("map_rotation_2d") or 0)
    b_rot = int(nb.get("map_rotation_2d") or 0)

    def _disp(img, rot):
        im = img if img.size == (tile, tile) else img.resize((tile, tile))
        return im.rotate(-rot, expand=False, fillcolor=(128, 128, 128)) if rot else im
    a_img = _disp(ia, a_rot)
    b_img = _disp(ib, b_rot)

    horizontal = side in ("east", "west")  # tiles left/right -> vertical seam
    if horizontal:
        canvas = Image.new("RGB", (tile * 2, tile), (128, 128, 128))
        a_first = (side == "east")           # east: neighbor right -> A left
        canvas.paste(a_img, (0, 0) if a_first else (tile, 0))
        canvas.paste(b_img, (tile, 0) if a_first else (0, 0))
        axis, W_, H_, seam = "x", tile * 2, tile, tile
    else:
        canvas = Image.new("RGB", (tile, tile * 2), (128, 128, 128))
        a_first = (side == "south")          # south: neighbor below -> A on top
        canvas.paste(a_img, (0, 0) if a_first else (0, tile))
        canvas.paste(b_img, (0, tile) if a_first else (0, 0))
        axis, W_, H_, seam = "y", tile, tile * 2, tile

    blend = max(1, int(tile * MAP_EDGE_BLEND_FRAC))
    coord = np.mgrid[0:H_, 0:W_][1 if axis == "x" else 0]
    dist = np.abs(coord - seam)
    # Fill the seam hard gray (gray strip ±blend).
    gray_band = dist < blend
    arr = np.array(canvas)
    arr[gray_band] = (128, 128, 128)
    canvas = Image.fromarray(arr, "RGB")
    # Mask = strip * mask_grow (hard).
    mask_w = blend * mask_grow
    mask = Image.fromarray(np.where(dist < mask_w, 255, 0).astype("uint8"), "L")

    cpath = tempfile.NamedTemporaryFile(suffix="_edgepair_canvas.png", delete=False).name
    mpath = tempfile.NamedTemporaryFile(suffix="_edgepair_mask.png", delete=False).name
    canvas.save(cpath)
    mask.save(mpath)
    info = {"axis": axis, "a_first": a_first, "a_loc": location, "b_loc": nb,
            "a_rot": a_rot, "b_rot": b_rot, "tile": tile}
    logger.info("Edge-Pair: %s <-%s-> %s | Canvas %dx%d, Naht %s",
                location.get("name"), side, nb.get("name"), W_, H_, axis)
    return cpath, mpath, info


# === prompt-changed flag ===

def set_location_prompt_changed(location_id: str, room_id: str,
                                value: Any) -> Dict[str, Any]:
    """Sets or removes the prompt_changed flag for a location or a room.

    Without ``room_id`` the flag is set/removed at location level.
    """
    from app.models.world import _load_world_data, _save_world_data

    if not value:
        # Remove the flag
        if room_id:
            ok = clear_room_prompt_changed(location_id, room_id)
        else:
            ok = clear_location_prompt_changed(location_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Location/Raum nicht gefunden")
        return {"status": "success", "prompt_changed": False}
    else:
        # Set the flag
        data = _load_world_data()
        for loc in data.get("locations", []):
            if loc.get("id") == location_id:
                if room_id:
                    for room in loc.get("rooms", []):
                        if room.get("id") == room_id:
                            room["prompt_changed"] = True
                            _save_world_data(data)
                            return {"status": "success", "prompt_changed": True}
                    raise HTTPException(status_code=404, detail="Raum nicht gefunden")
                else:
                    loc["prompt_changed"] = True
                    _save_world_data(data)
                    return {"status": "success", "prompt_changed": True}
        raise HTTPException(status_code=404, detail="Location nicht gefunden")


# === Gallery image generation ===

async def generate_gallery_image_core(location_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Actual generation logic — fired by the single mode as a background
    task and awaited directly by the batch mode (dispatchers in
    app/routes/world.py).
    """
    import time

    try:
        custom_prompt = data.get("prompt", "").strip()
        room_id = data.get("room_id", "").strip()
        prompt_type = data.get("prompt_type", "").strip()  # day/night/map/description
        workflow_name = data.get("workflow", "").strip()
        backend_name = data.get("backend", "").strip()
        loras_override = data.get("loras")
        model_override = data.get("model_override", "").strip()
        batch_track_id = data.get("_batch_track_id", "")
        fit_neighbors = bool(data.get("fit_neighbors"))
        # Edge matching: same mapfit workflow as Fit, only the mask (frame)
        # + prompt (transition) differ. edge_sides = the selected sides.
        edge_match = bool(data.get("edge_match"))
        edge_sides = data.get("edge_sides") or None
        _map_blend = fit_neighbors or edge_match

        location = resolve_location(location_name)
        if not location:
            raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

        # Prompt source: custom_prompt > room+type > room > prompt type > location description
        if custom_prompt:
            prompt = custom_prompt
        else:
            description = ""
            if room_id:
                room = get_room_by_id(location, room_id)
                if room:
                    # Room with prompt type: prefer the room's day/night prompt
                    if prompt_type == "day":
                        description = (room.get("image_prompt_day", "") or "").strip()
                    elif prompt_type == "night":
                        description = (room.get("image_prompt_night", "") or "").strip()
                    if not description:
                        description = room.get("image_prompt_day", "") or room.get("description", "")
            if not description and prompt_type == "day":
                description = location.get("image_prompt_day", "").strip()
            elif not description and prompt_type == "night":
                description = location.get("image_prompt_night", "").strip()
            elif not description and prompt_type == "map_2d":
                description = location.get("image_prompt_map_2d", "").strip()
            if not description:
                description = location.get("description", location.get("name", location_name))

            # Subject only — framing/style come from the use case (map/location).
            prompt = description

        # The map/location style now comes from the use case (applied below
        # via resolve_use_case_style) — no separate suffix anymore.
        from app.core.dependencies import get_skill_manager

        skill_manager = get_skill_manager()
        img_skill = None
        for skill in skill_manager.skills:
            if getattr(skill, 'SKILL_ID', '') == "image_generation":
                img_skill = skill
                break

        if not img_skill:
            raise HTTPException(status_code=503, detail="ImageGeneration Skill nicht verfuegbar")

        # Freshly check the availability of all backends — network calls go into
        # a thread, otherwise they block the event loop (the watchdog trips).
        await asyncio.to_thread(
            lambda: [b.check_availability()
                     for b in img_skill.backends if b.instance_enabled])

        # Backend selection: map-blend (inpaint) > match spec > explicit > auto (cheapest)
        backend = None
        if _map_blend:
            # Fit AND edge blending need an inpaint-capable backend. The backend
            # picked in the dialog (data["backend"]) has priority; without a
            # pick fall back to MAPFIT_IMAGEGEN_DEFAULT (a backend match spec).
            # Legacy "workflow:*" specs resolve to None and drop through.
            _fit_spec = ((data.get("backend") or "").strip()
                         or (os.environ.get("MAPFIT_IMAGEGEN_DEFAULT") or "").strip())
            if _fit_spec:
                backend = img_skill.resolve_imagegen_target(_fit_spec)
            if not backend:
                # No (usable) spec — cheapest available inpaint-category backend.
                _inpaint = [b for b in img_skill.backends
                            if b.available and b.instance_enabled
                            and (getattr(b, "category", "") or "") == "inpaint"]
                backend = img_skill.pick_lowest_cost(_inpaint, rotation_key="mapfit")
            if not backend:
                raise HTTPException(
                    status_code=503,
                    detail="Kein Inpaint-faehiges Backend fuer Map-Fit/Edge verfuegbar")
            logger.info("Map-Blend (%s): spec=%s -> Backend=%s",
                        "edge" if edge_match else "fit", _fit_spec, backend.name)
        elif workflow_name:
            # Match concept: glob + availability instead of an exact name.
            # An additionally pinned endpoint (backend_name) forces that instance.
            backend = img_skill.resolve_imagegen_target(
                workflow_name, preferred_backend=backend_name)
            if not backend and backend_name:
                # Explicitly pinned endpoint not available -> CLEAR error
                # instead of a silent fallback to another instance.
                raise HTTPException(
                    status_code=503,
                    detail=f"Gewaehltes Backend '{backend_name}' ist nicht verfuegbar")
            if not backend:
                logger.warning(
                    "Imagegen-Spec '%s' ergab kein verfuegbares Backend", workflow_name)
            else:
                logger.info("Imagegen-Spec (match): %s -> Backend: %s",
                            workflow_name, backend.name)
        elif backend_name:
            # Backend glob via the match concept. _wait_for_explicit_backend probes
            # the matching backends FRESH (instead of trusting stale b.available) —
            # needed for freshly configured cloud backends (CivitAI/Together).
            backend = (img_skill._wait_for_explicit_backend(backend_name)
                       or img_skill.match_backend(backend_name))
            logger.debug("Explizites Backend: %s -> %s", backend_name, backend.name if backend else 'nicht verfuegbar')
            # Explicit choice + not available -> CLEAR error instead of a silent
            # ComfyUI fallback (otherwise the user thinks CivitAI was used).
            if not backend:
                raise HTTPException(
                    status_code=503,
                    detail=f"Gewaehltes Backend '{backend_name}' ist nicht verfuegbar "
                           f"(z.B. ungueltiger API-Key / offline). Kein automatischer Fallback.")

        if not backend:
            backend = img_skill._select_backend()
        if not backend:
            raise HTTPException(status_code=503, detail="Kein Image-Backend verfuegbar")

        # Map blend: auto-prompt only as a fallback when NO prompt came along (the
        # dialog already delivers it editable via .../fit-prompt or .../edge-prompt).
        # Terrain hint only when the backend wants it (terrain_hint) — otherwise the
        # prompt only describes the target style, the gray canvas supplies the context itself.
        if _map_blend and not custom_prompt and getattr(backend, "terrain_hint", False):
            # The terrain analysis makes blocking LLM submits (describe_map_tile,
            # up to one per neighbor side) → into a thread so the event loop
            # stays free. This was the cause of the watchdog block.
            if edge_match:
                _ep = await asyncio.to_thread(_edge_transition_prompt, location, edge_sides)
                if _ep:
                    prompt = _ep
                    logger.info("Edge-Match Auto-Prompt: %s", _ep)
            else:
                _hint = await asyncio.to_thread(_neighbor_terrain_hint, location)
                if _hint:
                    prompt = _hint
                    logger.info("Map-Fit Auto-Prompt: %s", _hint)

        # Regenerate (self-reference): the prompt is a literal adjustment
        # instruction for the reference workflow (e.g. "road turns right") — NO
        # use-case prefix, NO use-case negative, no other manipulation.
        _is_regen = bool(data.get("use_source_as_reference"))
        # Optional "what do you want to change" request: the same LLM function
        # as in the character/Instagram regenerate builds the final prompt from
        # it. Left empty -> the prompt stays literal.
        _improve = (data.get("improvement_request") or "").strip()
        if _is_regen and _improve:
            from app.skills.image_regenerate import enhance_prompt
            prompt = await asyncio.to_thread(enhance_prompt, prompt, _improve, None)
            logger.info("Regenerate-Prompt via enhance_prompt umgeschrieben: %s", prompt[:120])
        # Use-case style/negative: map blend (inpaint) -> "mapfit" (fill gray
        # areas seamlessly, no "new tile" style), normal tile -> "map",
        # otherwise location background.
        from app.core import config as _cfg
        _uc_name = "mapfit" if _map_blend else ("map" if prompt_type == "map_2d" else "location")
        _ucp = _cfg.resolve_use_case_style(
            _uc_name, getattr(backend, "image_family", "") or "",
            backend_model=getattr(backend, "model", "") or "")
        if _is_regen:
            full_prompt = prompt
            negative = ""
        elif _map_blend and custom_prompt:
            # The Fit/Edge dialog delivers the (mapfit) prompt already fully edited
            # — take it literally, do NOT double the style prefix. The negative
            # still comes from the mapfit use case. Without a dialog prompt (batch)
            # it falls back to style+auto-hint below.
            full_prompt = prompt
            negative = _ucp.get("prompt_negative", "")
        else:
            full_prompt = f"{_ucp['prompt_style']}, {prompt}" if _ucp.get("prompt_style") else prompt
            negative = _ucp.get("prompt_negative", "")
        # Map icons are small thumbnails for the world overview and get
        # downscaled. Day/night/description stay at full resolution
        # as background images.
        params: Dict[str, Any] = {"width": _location_image_width(), "height": _location_image_height()}
        if prompt_type == "map_2d":
            params["image_use_case"] = "map"
            # Generate 2D map tiles square (1:1, Flux-native 1024) instead of
            # the 16:9 location format — fills the tile. Otherwise landscape.
            params["width"] = 1024
            params["height"] = 1024
        # Model override from the dialog — backends read params["model"].
        if model_override:
            params["model"] = model_override
        # LoRA selection from the dialog.
        if loras_override is not None:
            params["lora_inputs"] = loras_override

        # Fresh seed per call so a regenerate produces a new image.
        import random as _rnd
        params["seed"] = _rnd.randint(1, 2**31 - 1)

        # Self-reference: the existing (map) image as reference in slot 1 —
        # for "regenerate with current image" (e.g. so 2D tiles fit together
        # better). Only if the backend has reference slots.
        if (data.get("use_source_as_reference") and data.get("reference_image")
                and int(getattr(backend, "ref_slot_count", 0) or 0) >= 1):
            _ref_name = (data.get("reference_image") or "").strip()
            if _ref_name and "/" not in _ref_name and ".." not in _ref_name:
                # get_gallery_dir is imported module-wide (top). NO local import
                # here — it would turn get_gallery_dir into a function-wide local
                # variable and blow up the save path (below) with an
                # UnboundLocalError as soon as this block does not run.
                _ref_path = get_gallery_dir(location_name) / _ref_name
                if _ref_path.exists():
                    params["reference_images"] = {"input_reference_image_1": str(_ref_path)}
                    logger.info("Map-Selbst-Referenz in Slot 1: %s", _ref_name)

        # Neighbor-context inpainting: build the 3x3 canvas + mask and inject
        # them as input_reference_image/input_mask. Fit = gray center (whole
        # tile new); Edge = real tile + frame mask of the selected sides.
        _fit_comp = None
        _edge_pair = None
        _cpath = _mpath = None
        # Inpaint mask parameters come purely from the backend fields (no flag,
        # no per-model special casing). Only applies when the backend is an
        # inpaint backend (category=="inpaint").
        if getattr(backend, "category", "") == "inpaint":
            _grow = float(getattr(backend, "mask_grow", MAP_BLEND_MASK_GROW_GRAY))
            _full = bool(getattr(backend, "full_mask", True))
            _inner = float(getattr(backend, "inner_crop", MAP_FIT_INNER_CROP))
        else:
            _grow = MAP_BLEND_MASK_GROW_FILL
            _full = False
            _inner = MAP_FIT_INNER_CROP
        if edge_match:
            # EXACTLY two adjacent tiles, ONE edge. Seam hard gray, mask =
            # strip * mask_grow. The backend returns ONE image — this module
            # cuts it down the middle and puts both halves into the neighbor locations.
            _side = (edge_sides[0] if isinstance(edge_sides, (list, tuple)) and edge_sides
                     else (edge_sides if isinstance(edge_sides, str) else ""))
            _ep = _compose_edge_pair(location, _side, mask_grow=_grow)
            if _ep:
                _cpath, _mpath, _edge_pair = _ep
                params["image_use_case"] = "mapfit"  # bypass the 400 cap: full output for cutting
        elif fit_neighbors:
            _fit_comp = _compose_neighbor_canvas(location, crop_empty=True, mask_grow=_grow,
                                                 full_mask=_full, inner_crop=_inner)
            if _fit_comp:
                _cpath, _mpath, _ctile, _cfrac = _fit_comp
                # Bypass the 400 cap: the backend shall return the FULL canvas so
                # that the center is cropped out at full resolution. Without this
                # the output is shrunk to 400px (map cap) beforehand → the
                # center crop yields only ~290px upscaled (blurry).
                params["image_use_case"] = "mapfit"
        if _cpath and _mpath:
            # Canvas (pure RGB) -> input_reference_image, inpaint mask -> input_mask.
            # Both at original resolution; give the workflow the real canvas dimensions.
            params["reference_images"] = {
                "input_reference_image": _cpath, "input_mask": _mpath}
            from PIL import Image as _ImgSz
            with _ImgSz.open(_cpath) as _cv:
                _cw, _ch = _cv.size
            params["width"] = _cw
            params["height"] = _ch
            logger.info("Map-Blend: Canvas + Inpaint-Maske injiziert (%dx%d)", _cw, _ch)
            try:
                import shutil as _sh
                from app.core.paths import get_storage_dir as _gsd
                _dbg = _gsd() / "mapblend_debug"
                _dbg.mkdir(parents=True, exist_ok=True)
                _sh.copy(_cpath, _dbg / "last_canvas.png")
                _sh.copy(_mpath, _dbg / "last_mask.png")
                (_dbg / "last_prompt.txt").write_text(
                    f"mode: {'edge' if edge_match else 'fit'}\n"
                    f"location: {location.get('name', '')} ({location.get('id', '')})\n"
                    f"edge_sides: {edge_sides}\n\n"
                    f"PROMPT:\n{full_prompt}\n\nNEGATIVE:\n{negative}\n",
                    encoding="utf-8")
                # Log the md5 too → 1:1 comparison with the backend's "Ref-Inject"
                # log line: this proves that the mapblend_debug files are exactly
                # the ones that go to ComfyUI.
                import hashlib as _hl
                _cmd5 = _hl.md5(Path(_cpath).read_bytes()).hexdigest()[:12]
                _mmd5 = _hl.md5(Path(_mpath).read_bytes()).hexdigest()[:12]
                logger.info("Map-Blend Debug (%s): %s | canvas md5=%s mask md5=%s",
                            "edge" if edge_match else "fit", _dbg, _cmd5, _mmd5)
            except Exception as _de:
                logger.debug("Map-Blend Debug-Copy fehlgeschlagen: %s", _de)
        elif _map_blend:
            logger.info("Map-Fit/Edge: kein Nachbar/Grid-Position — normaler Lauf")

        from app.core.task_queue import get_task_queue
        _tq = get_task_queue()
        if batch_track_id:
            _track_id = batch_track_id
        else:
            _track_id = _tq.track_start(
                "image_gen", "Ort-Bild", agent_name=location.get("name", location_name),
                provider=backend.name, start_running=False)

        _gen_start = time.time()
        try:
            # Generate via the GPU provider queue — serialized per backend
            # (never two in parallel); activates the track only once the channel
            # picks up the work; waiting world gens thus stay correctly "pending".
            # Context for the CENTRAL logging in backend.generate() (final_prompt,
            # backend, model, LoRAs, refs, duration are set by generate() itself).
            _log_meta = {"agent_name": location.get("name", location_name),
                         "original_prompt": prompt, "auto_enhance": False}
            def _op(b):
                def _gen():
                    try:
                        from app.core.task_router import match_queue_name
                        _tq.track_activate(_track_id, queue_name=match_queue_name(b.name) or "", provider=b.name)
                    except Exception:
                        pass
                    return b.generate(full_prompt, negative, params, log_meta=_log_meta)
                if getattr(b, "api_type", "") == "a1111":
                    from app.core.llm_queue import get_llm_queue, Priority as _P
                    return get_llm_queue().submit_gpu_task(
                        provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                        callable_fn=_gen, agent_name=location.get("name", location_name),
                        gpu_type=b.api_type)
                return _gen()
            try:
                images, backend = await asyncio.to_thread(
                    lambda: img_skill.run_with_fallback(
                        primary_backend=backend, op=_op,
                        character_name=""))
            except RuntimeError as _err:
                _tq.track_finish(_track_id, error=str(_err)[:200])
                raise HTTPException(status_code=500, detail=str(_err))

            if not images:
                _tq.track_finish(_track_id, error="Bildgenerierung fehlgeschlagen")
                raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

            # Edge pair (new model): cut the returned ONE image down the middle,
            # rotate each half back to north by its own rotation, bring it to the
            # map thumbnail (400) and store it in the respective location as a
            # new map_2d tile. Then done immediately.
            if _edge_pair:
                import io as _io2
                from PIL import Image as _ImgE
                from app.core.image_postprocess import downscale_bytes
                from app.models.world import set_location_map_image
                _full = _ImgE.open(_io2.BytesIO(images[0])).convert("RGB")
                _W, _H = _full.size
                if _edge_pair["axis"] == "x":
                    _mid = _W // 2
                    _first = _full.crop((0, 0, _mid, _H))
                    _second = _full.crop((_mid, 0, _W, _H))
                else:
                    _mid = _H // 2
                    _first = _full.crop((0, 0, _W, _mid))
                    _second = _full.crop((0, _mid, _W, _H))
                _a_half = _first if _edge_pair["a_first"] else _second
                _b_half = _second if _edge_pair["a_first"] else _first
                _saved = []
                for _hl, _loc2, _rot2 in ((_a_half, _edge_pair["a_loc"], _edge_pair["a_rot"]),
                                          (_b_half, _edge_pair["b_loc"], _edge_pair["b_rot"])):
                    if _rot2:
                        _hl = _hl.rotate(_rot2, expand=False)  # back to north
                    _bb = _io2.BytesIO(); _hl.save(_bb, format="PNG")
                    _png = downscale_bytes(_bb.getvalue(), "map")  # map thumbnail (400)
                    _lid2 = _loc2.get("id", "")
                    _gd2 = get_gallery_dir(_lid2); _gd2.mkdir(parents=True, exist_ok=True)
                    _nm2 = f"{int(time.time())}_{_lid2[:6]}.png"
                    (_gd2 / _nm2).write_bytes(_png)
                    save_gallery_prompt(_lid2, _nm2, full_prompt)
                    set_gallery_image_type(_lid2, _nm2, "map_2d")
                    set_gallery_image_meta(_lid2, _nm2, {
                        "backend": backend.name, "backend_type": backend.api_type,
                        "model": (getattr(backend, 'model', '') or ''), "loras": []})
                    set_location_map_image(_lid2, "map_image_2d", _nm2)  # show the new tile
                    toggle_background_image(_lid2, _nm2)
                    _saved.append({"location_id": _lid2, "image": _nm2})
                for _tmp in (_cpath, _mpath):
                    try:
                        os.remove(_tmp)
                    except Exception:
                        pass
                _tq.track_finish(_track_id)
                logger.info("Edge-Pair gespeichert: %s", _saved)
                return {"status": "success", "edge": True, "saved": _saved}

            # Map-Fit/Edge: the backend crops the center (the new tile) out of the
            # returned full canvas (via a fraction box, robust against the output
            # resolution) and scales it to MAP_FIT_OUT_TILE. The workflow no
            # longer gets a crop mask.
            if _fit_comp:
                try:
                    import io as _io
                    from PIL import Image as _Img
                    _full = _Img.open(_io.BytesIO(images[0])).convert("RGB")
                    _w, _h = _full.size
                    _fx0, _fy0, _fx1, _fy1 = _cfrac
                    _box = (round(_fx0 * _w), round(_fy0 * _h),
                            round(_fx1 * _w), round(_fy1 * _h))
                    _crop = _full.crop(_box)
                    if _crop.size != (MAP_FIT_OUT_TILE, MAP_FIT_OUT_TILE):
                        _crop = _crop.resize((MAP_FIT_OUT_TILE, MAP_FIT_OUT_TILE), _Img.LANCZOS)
                    _buf = _io.BytesIO()
                    _crop.save(_buf, format="PNG")
                    images = [_buf.getvalue()]
                    logger.info("Map-Fit: Mitte %s aus %dx%d -> %dpx", _box, _w, _h, MAP_FIT_OUT_TILE)
                except Exception as _ce:
                    logger.warning("Map-Fit Crop fehlgeschlagen: %s", _ce)
                finally:
                    for _tmp in (_fit_comp[0], _fit_comp[1]):
                        try:
                            os.remove(_tmp)
                        except Exception:
                            pass

            # Map blend: the canvas is built in DISPLAY orientation (center + neighbors
            # each rotated by their map_rotation_2d). The result tile therefore must be
            # rotated BACK to north by exactly this rotation BEFORE saving, otherwise
            # the display (map_rotation_2d) rotates it a second time -> doubly twisted.
            _rot = int(location.get("map_rotation_2d") or 0) if _map_blend else 0
            if _rot:
                try:
                    import io as _io3
                    from PIL import Image as _Img3
                    _im = _Img3.open(_io3.BytesIO(images[0])).rotate(_rot, expand=False)
                    _b = _io3.BytesIO()
                    _im.save(_b, format="PNG")
                    images = [_b.getvalue()]
                    logger.info("Map-Blend: Ergebnis um %d° nach Norden zurueckgedreht", _rot)
                except Exception as _re:
                    logger.warning("Map-Blend Rueckdrehung fehlgeschlagen: %s", _re)

            loc_id = location.get("id", location_name)
            gallery_dir = get_gallery_dir(loc_id)
            gallery_dir.mkdir(parents=True, exist_ok=True)
            # Replace ("new image" checkbox off): overwrite the source image
            # in place — keeps the file name and thus the room/type/map assignment
            # and the background flag. Otherwise a new image with a timestamp.
            _replace_src = (data.get("reference_image") or "").strip() if data.get("replace_source") else ""
            _is_replace = bool(
                _replace_src and "/" not in _replace_src and ".." not in _replace_src
                and (gallery_dir / _replace_src).exists())
            image_name = _replace_src if _is_replace else f"{int(time.time())}.png"
            image_path = gallery_dir / image_name
            image_path.write_bytes(images[0])

            # Save the prompt for a later upgrade
            save_gallery_prompt(loc_id, image_name, full_prompt)

            # Mark the new image as background by default — do NOT toggle on an
            # in-place replace (otherwise an already-set flag flips over).
            if not _is_replace:
                toggle_background_image(loc_id, image_name)

            # Set the room assignment when room_id is given
            if room_id:
                set_gallery_image_room(loc_id, image_name, room_id)
                # Remove the prompt_changed flag — the image was created from the prompt
                from app.models.world import clear_room_prompt_changed
                clear_room_prompt_changed(loc_id, room_id)
            elif not custom_prompt:
                # Location-level prompt was used — remove the flag there
                from app.models.world import clear_location_prompt_changed
                clear_location_prompt_changed(loc_id)

            # Save generation metadata (service + model + LoRAs)
            _model_used = (getattr(backend, 'last_used_checkpoint', '')
                           or getattr(backend, 'model', '')
                           or getattr(backend, 'checkpoint', '') or '')
            _loras_used = [str(l.get("name")).strip()
                           for l in (params.get("lora_inputs") or params.get("loras") or [])
                           if isinstance(l, dict) and (l.get("name") or "").strip()
                           and l.get("name") != "None"]
            set_gallery_image_meta(loc_id, image_name, {
                "backend": backend.name,
                "backend_type": backend.api_type,
                "model": _model_used,
                "loras": _loras_used,
            })

            # Set the image type when prompt_type is given (day/night/map_2d)
            if prompt_type in ("day", "night", "map_2d"):
                set_gallery_image_type(loc_id, image_name, prompt_type)
            # Set the newly created map tile as the displayed map item right away
            # (fit/neighbor + normal map_2d gen) — otherwise the old tile would stay active.
            if prompt_type == "map_2d":
                from app.models.world import set_location_map_image
                set_location_map_image(loc_id, "map_image_2d", image_name)

            _tq.track_finish(_track_id)
            _gen_duration = time.time() - _gen_start
            logger.info("Bild generiert: %s (%s)/%s%s", location['name'], loc_id, image_name,
                        f" room={room_id}" if room_id else "")

            # Image-prompt logging now happens CENTRALLY in backend.generate()
            # (with the final, trigger-injected prompt) — via log_meta below.
            return {"status": "success", "location": location["name"], "location_id": loc_id, "image": image_name}
        except HTTPException:
            raise
        except Exception as e:
            _tq.track_finish(_track_id, error=str(e))
            raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Gallery Fehler: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


async def generate_time_variant_core(location_name: str, image_name: str,
                                     target_type: str, workflow_name: str,
                                     backend_name: str,
                                     custom_prompt: str) -> Dict[str, Any]:
    """Logic core of the day/night time variant (img2img with the source
    image as the reference). The route keeps parsing/traversal/HTTP mapping;
    the 404 guards for location/source image sit mid-logic here.
    """
    import time

    location = resolve_location(location_name)
    if not location:
        raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

    loc_id = location.get("id", location_name)
    gallery_dir = get_gallery_dir(loc_id)
    source_path = gallery_dir / image_name
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Quellbild nicht gefunden")

    # Prompt: custom or automatically from the day/night prompt / description
    prompt_field = f"image_prompt_{target_type}"
    if custom_prompt:
        prompt = custom_prompt
    else:
        # Check the room assignment of the source image
        image_rooms = get_gallery_image_rooms(loc_id)
        source_room_id = image_rooms.get(image_name, "")
        description = ""
        is_room = False
        if source_room_id:
            room = get_room_by_id(location, source_room_id)
            if room:
                is_room = True
                description = (room.get(prompt_field, "") or
                               room.get("description", ""))
        if not description:
            description = (location.get(prompt_field, "") or
                           location.get("description", location.get("name", location_name)))

        if is_room:
            # Interior: no sky/stars, adjust the lighting instead
            if target_type == "night":
                prompt = (
                    f"{description}, nighttime interior, dim warm lighting, "
                    f"lamp light, evening atmosphere, cozy shadows, "
                    f"window showing dark sky outside, "
                    f"wide angle interior shot, no people, "
                    f"atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio"
                )
            else:
                prompt = (
                    f"{description}, daytime interior, bright natural light, "
                    f"sunlight through windows, warm daylight atmosphere, "
                    f"wide angle interior shot, no people, "
                    f"atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio"
                )
        else:
            # Outdoor area / location
            if target_type == "night":
                prompt = (
                    f"{description}, nighttime, dark sky, moonlight, "
                    f"night atmosphere, dim lighting, stars, evening mood, "
                    f"wide angle establishing shot, no people, "
                    f"atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio"
                )
            else:
                prompt = (
                    f"{description}, daytime, bright sunlight, clear sky, "
                    f"warm daylight atmosphere, natural lighting, "
                    f"wide angle establishing shot, no people, "
                    f"atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio"
                )

    from app.core.dependencies import get_skill_manager

    skill_manager = get_skill_manager()
    img_skill = None
    for skill in skill_manager.skills:
        if getattr(skill, 'SKILL_ID', '') == "image_generation":
            img_skill = skill
            break

    if not img_skill:
        raise HTTPException(status_code=503, detail="ImageGeneration Skill nicht verfuegbar")

    # Check availability — network calls go into a thread, otherwise
    # they block the event loop (the watchdog trips).
    await asyncio.to_thread(
        lambda: [b.check_availability()
                 for b in img_skill.backends if b.instance_enabled])

    # Backend selection: explicit spec > explicit backend > reference-capable auto
    backend = None
    if workflow_name:
        # Match concept: glob + availability instead of an exact name.
        # Legacy "workflow:*" specs resolve to None and drop through.
        backend = img_skill.resolve_imagegen_target(workflow_name)
    elif backend_name:
        backend = img_skill.match_backend(backend_name)  # backend glob via match concept

    if not backend:
        # Prefer an edit-capable backend with at least one reference-image
        # slot. NO inpaint backends: they expect a mask, which the
        # day/night convert does not provide.
        candidates = [b for b in img_skill.list_available_backends()
                      if int(getattr(b, "ref_slot_count", 0) or 0) >= 1
                      and (getattr(b, "category", "") or "") != "inpaint"]
        backend = img_skill.pick_lowest_cost(candidates, rotation_key="time_variant")

    # No fallback to backends without reference-image support — the
    # time-variant convert strictly needs img2img with a local reference image.
    if not backend:
        raise HTTPException(
            status_code=503,
            detail="Kein Image-Backend mit Referenzbild-Support verfuegbar. "
                   "Bitte ein Backend mit Referenz-Slots konfigurieren/starten.")

    # The time variant needs an edit backend with a reference-image slot.
    # An inpaint backend does NOT fit — it expects mask inputs.
    if ((getattr(backend, "category", "") or "") == "inpaint"
            or int(getattr(backend, "ref_slot_count", 0) or 0) < 1):
        raise HTTPException(
            status_code=400,
            detail=(f"Backend '{backend.name}' ist fuer Tag/Nacht-Varianten "
                    "ungeeignet (Inpaint bzw. ohne Referenzbild-Slot)."))

    from app.core import config as _cfg
    _ucp = _cfg.resolve_use_case_style(
        "location", getattr(backend, "image_family", "") or "",
        backend_model=getattr(backend, "model", "") or "")
    full_prompt = f"{_ucp['prompt_style']}, {prompt}" if _ucp.get("prompt_style") else prompt
    negative = _ucp.get("prompt_negative", "")
    # Day/night variants are background images — full size, no downscale.
    params = {"width": _location_image_width(), "height": _location_image_height()}

    # Fresh seed per call — the time variant should always produce a new
    # image instead of hitting a backend-side prompt+seed cache.
    import random as _rnd
    params["seed"] = _rnd.randint(1, 2**31 - 1)

    # The source image is the image being edited (primary edit reference)
    # in reference slot 1.
    params["reference_images"] = {
        "input_reference_image_1": str(source_path),
    }

    from app.core.task_queue import get_task_queue
    _tq = get_task_queue()
    _variant_label = "Nachtansicht" if target_type == "night" else "Tagansicht"
    _track_id = _tq.track_start(
        "image_gen", _variant_label, agent_name=location.get("name", location_name),
        provider=backend.name, start_running=False)

    _gen_start = time.time()
    try:
        # GPU provider queue: serialized per backend + track only active
        # once the channel picks up the work (waiting ones stay "pending").
        _log_meta = {"agent_name": location.get("name", location_name),
                     "original_prompt": prompt, "auto_enhance": False}
        def _op(b):
            def _gen():
                try:
                    from app.core.task_router import match_queue_name
                    _tq.track_activate(_track_id, queue_name=match_queue_name(b.name) or "", provider=b.name)
                except Exception:
                    pass
                return b.generate(full_prompt, negative, params, log_meta=_log_meta)
            if getattr(b, "api_type", "") == "a1111":
                from app.core.llm_queue import get_llm_queue, Priority as _P
                return get_llm_queue().submit_gpu_task(
                    provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                    callable_fn=_gen, agent_name=location.get("name", location_name),
                    gpu_type=b.api_type)
            return _gen()
        try:
            images, backend = await asyncio.to_thread(
                lambda: img_skill.run_with_fallback(
                    primary_backend=backend, op=_op,
                    character_name=""))
        except RuntimeError as _err:
            _tq.track_finish(_track_id, error=str(_err)[:200])
            raise HTTPException(status_code=500, detail=str(_err))

        if not images:
            _tq.track_finish(_track_id, error="Bildgenerierung fehlgeschlagen")
            raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

        gallery_dir.mkdir(parents=True, exist_ok=True)
        new_image_name = f"{int(time.time())}.png"
        new_image_path = gallery_dir / new_image_name
        new_image_path.write_bytes(images[0])

        # Save the prompt
        save_gallery_prompt(loc_id, new_image_name, full_prompt)

        # Mark as background
        toggle_background_image(loc_id, new_image_name)

        # Set the type (day/night)
        set_gallery_image_type(loc_id, new_image_name, target_type)

        # Take over the room assignment from the source image
        image_rooms = get_gallery_image_rooms(loc_id)
        source_room = image_rooms.get(image_name, "")
        if source_room:
            set_gallery_image_room(loc_id, new_image_name, source_room)

        # Save the meta
        _model_used = (getattr(backend, 'last_used_checkpoint', '')
                       or getattr(backend, 'model', '')
                       or getattr(backend, 'checkpoint', '') or '')
        _loras_used = [str(l.get("name")).strip()
                       for l in (params.get("lora_inputs") or params.get("loras") or [])
                       if isinstance(l, dict) and (l.get("name") or "").strip()
                       and l.get("name") != "None"]
        set_gallery_image_meta(loc_id, new_image_name, {
            "backend": backend.name,
            "backend_type": backend.api_type,
            "model": _model_used,
            "loras": _loras_used,
            "source": image_name,
        })

        _tq.track_finish(_track_id)
        _gen_duration = time.time() - _gen_start
        logger.info("%s generiert: %s (%s)/%s -> %s", _variant_label, location['name'], loc_id, image_name, new_image_name)

        # Image-prompt logging now happens CENTRALLY in backend.generate()
        # (final, trigger-injected) — via log_meta on the generate call.
        return {"status": "success", "location_id": loc_id, "image": new_image_name, "source": image_name}
    except HTTPException:
        raise
    except Exception as e:
        _tq.track_finish(_track_id, error=str(e))
        raise
