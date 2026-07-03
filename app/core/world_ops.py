"""World-domain operations behind app/routes/world.py.

Logic moved 1:1 out of the route handlers (code-review section 5b); the
routes remain thin HTTP adapters (auth, request parsing, response types).
HTTPExceptions that were embedded mid-logic moved along unchanged.
"""
import os
from fastapi import HTTPException
from typing import Any, Dict
from app.core.log import get_logger

logger = get_logger("world")

from app.models.world import (
    list_locations, add_location,
    rename_location, resolve_location, get_location_by_id,
    get_entry_room_id,
    get_background_images, remove_background_image,
    get_gallery_dir, list_gallery_images,
    get_all_gallery_prompts,
    set_gallery_image_room, get_gallery_image_rooms, remove_gallery_image_room,
    set_gallery_image_type, get_gallery_image_types, remove_gallery_image_type,
    get_gallery_image_metas,
    toggle_background_image)


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
