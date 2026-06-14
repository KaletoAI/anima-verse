"""World routes - Orte und Aktivitaeten verwalten (User-Level)"""
import asyncio
import io
import os
from fastapi import APIRouter, Request, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, Response
from pathlib import Path
from typing import Any, Dict, Optional
from app.core.log import get_logger

logger = get_logger("world")

from app.models.world import (
    list_locations, add_location, delete_location,
    rename_location, resolve_location, get_location_by_id,
    get_entry_room_id,
    update_location_position,
    list_all_activities,
    get_background_path, get_background_file_path,
    get_background_images, toggle_background_image, remove_background_image,
    get_gallery_dir, list_gallery_images,
    save_gallery_prompt, get_all_gallery_prompts,
    set_gallery_image_room, get_gallery_image_rooms, remove_gallery_image_room,
    set_gallery_image_type, get_gallery_image_types, remove_gallery_image_type,
    set_gallery_image_meta, get_gallery_image_metas,
    get_room_by_id,
    clear_room_prompt_changed, clear_location_prompt_changed)

router = APIRouter(prefix="/world", tags=["world"])


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


# === Avatar-Movement (Direction-Pad) ===

@router.get("/avatar/neighbors")
def avatar_neighbors_route() -> Dict[str, Any]:
    """Liefert die Nachbar-Locations des Avatars in jede Himmelsrichtung.

    Response: { "north": {id, name} | null, "south": ..., "east": ..., "west": ... }
    Damit kann das Direction-Pad nicht-erreichbare Richtungen ausblenden,
    statt erst auf der 404-Antwort zu reagieren.
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

    # Departure-Gate: Frontend kann die Richtungs-Pfeile ausblenden, wenn der
    # Avatar nicht im Entry-Room steht. Server-seitige Sperre liegt im
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


@router.post("/avatar/step")
async def avatar_step_route(request: Request) -> Dict[str, Any]:
    """Bewegt den Avatar um einen Grid-Schritt in die angegebene Richtung.

    Body: { "direction": "north"|"south"|"east"|"west" }

    Sucht die Nachbar-Location anhand der Grid-Koordinaten der aktuellen
    Avatar-Position. Gibt 404 zurueck wenn dort keine Location liegt.
    """
    data = await request.json()
    direction = (data.get("direction") or "").strip().lower()
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

    cur_loc_id = (get_character_current_location(avatar) or "").strip()
    if not cur_loc_id:
        raise HTTPException(status_code=400, detail="avatar has no current location")

    cur = get_location_by_id(cur_loc_id)
    if not cur:
        raise HTTPException(status_code=404, detail="current location not found")

    # Departure-Gate: Avatar darf eine Location nur ueber den Entry-Room verlassen.
    cur_entry = get_entry_room_id(cur)
    cur_room = (get_character_current_room(avatar) or "").strip()
    if cur_entry and cur_room and cur_room != cur_entry:
        # Entry-Room-Name zur Meldung holen
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

    # Nachbar-Location suchen
    target = None
    for loc in list_locations():
        if int(loc.get("grid_x") or 0) == target_x and int(loc.get("grid_y") or 0) == target_y:
            target = loc
            break
    if not target:
        raise HTTPException(status_code=404, detail="no location in that direction")

    target_id = target.get("id") or ""

    # Block-Regeln: Avatar unterliegt denselben Restrictions wie NPCs.
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
    # Ortswechsel unterbricht die laufende Pose (sonst bleibt die alte am
    # neuen Ort stehen). Avatar ist spielergesteuert → leeren, nicht neu zuweisen.
    clear_pose_intent(avatar)

    # Roll-on-Entry: bei Eintritt an einer Location sofort wuerfeln, ob ein
    # Event fuer den Avatar entsteht (z.B. "Wölfe versperren den Weg").
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


# === Orte ===

@router.get("/locations")
def get_locations_route(character_name: str = Query("", alias="agent_name")
) -> Dict[str, Any]:
    """Listet Orte aus Sicht eines Characters auf.

    Wenn `character_name` gesetzt ist, werden Orte mit `visible_when`/
    `accessible_when` gegen das Character-Inventar/-State gefiltert. Unsichtbare
    Orte (visible_when schlaegt fehl) werden entfernt; unzugaengliche Orte
    (accessible_when schlaegt fehl) bekommen ein `accessible: false` Flag.
    Ohne `character_name` werden alle Orte ungefiltert zurueckgegeben (Admin-View).
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
                continue  # Ort nicht sichtbar
            aw = loc.get("accessible_when") or []
            loc["accessible"] = _all_pass(aw, character_name, loc_id) if aw else True
            filtered.append(loc)
        locations = filtered

    for loc in locations:
        loc_id = loc.get("id", "")
        loc["image_count"] = len(list_gallery_images(loc_id)) if loc_id else 0
    return {"locations": locations}


@router.post("/locations")
async def create_location_route(request: Request) -> Dict[str, Any]:
    """Erstellt oder aktualisiert einen Ort."""
    try:
        data = await request.json()
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
        map_z_offset = data.get("map_z_offset")
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

        # Extra-Felder direkt in der Location setzen
        _has_extra = (danger_level is not None or event_settings is not None
                      or outfit_type is not None or knowledge_item_id is not None
                      or passable is not None or map_z_offset is not None
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
                    if map_z_offset is not None:
                        try:
                            _l["map_z_offset"] = max(-10, min(10, int(map_z_offset)))
                        except (TypeError, ValueError):
                            pass
                    if entry_room is not None:
                        _l["entry_room"] = (entry_room or "").strip()
                    if indoor is not None:
                        _v = (indoor or "").strip().lower()
                        _l["indoor"] = _v if _v in ("indoor", "outdoor") else ""
                    break
            _save_world_data(wdata)
            location = get_location_by_id(location["id"])

        return {"status": "success", "location": location}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/locations/{location_id}")
async def update_location_route(location_id: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert einen Ort (Umbenennung per ID)."""
    try:
        data = await request.json()
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
        map_z_offset = data.get("map_z_offset")
        entry_room = data.get("entry_room")
        indoor = data.get("indoor")

        loc = get_location_by_id(location_id)
        if not loc:
            raise HTTPException(status_code=404, detail="Ort nicht gefunden")

        if new_name:
            rename_location(location_id, new_name)

        # Description, Rooms und Image-Prompts aktualisieren falls mitgegeben
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
                    location_id=location_id)  # per ID updaten — eindeutig bei doppelten Namen

        # Extra-Felder (inkl. knowledge_item_id) direkt in der Location setzen
        _has_extra = (danger_level is not None or event_settings is not None
                      or outfit_type is not None or knowledge_item_id is not None
                      or passable is not None or map_z_offset is not None
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
                    if map_z_offset is not None:
                        try:
                            _l["map_z_offset"] = max(-10, min(10, int(map_z_offset)))
                        except (TypeError, ValueError):
                            pass
                    if entry_room is not None:
                        _l["entry_room"] = (entry_room or "").strip()
                    if indoor is not None:
                        _v = (indoor or "").strip().lower()
                        _l["indoor"] = _v if _v in ("indoor", "outdoor") else ""
                    break
            _save_world_data(wdata)

        updated = get_location_by_id(location_id)
        return {"status": "success", "location": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/locations/{template_id}/clone")
async def clone_location_route(template_id: str, request: Request) -> Dict[str, Any]:
    """Erzeugt eine Klon-Instanz eines (passable) Templates an einer Grid-
    Position. Aufgerufen vom Worldmap-Drag&Drop, wenn der User ein passable
    Template aus dem Tray auf die Karte zieht.
    """
    try:
        data = await request.json()
        grid_x = data.get("grid_x")
        grid_y = data.get("grid_y")
        if grid_x is None or grid_y is None:
            raise HTTPException(status_code=400,
                detail="grid_x/grid_y fehlen")
        from app.models.world import clone_location as _clone
        clone = _clone(template_id, int(grid_x), int(grid_y))
        if not clone:
            raise HTTPException(status_code=404,
                detail="Template nicht gefunden")
        return {"status": "success", "location": clone}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- World-Level Settings (Schritt 7, May 2026) ---------------------------
# Temperature/Weather/Pose-Variant-Settings leben in world_kv. Eigener
# Endpunkt damit der Setup-Tab eine kompakte Form rendern kann ohne ueber
# die generische admin-config-Maschinerie zu gehen.

@router.get("/settings")
async def get_world_settings() -> Dict[str, Any]:
    """Gibt Welt-Settings + Pose-Settings zurueck."""
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
        "choices": {
            "temperature": list(WORLD_TEMPERATURE_VALUES),
            "weather":     list(WORLD_WEATHER_VALUES),
        },
    }


@router.put("/settings")
async def put_world_settings(request: Request) -> Dict[str, Any]:
    """Setzt Welt-Settings + Pose-Settings."""
    from app.models.world import (
        set_world_temperature, set_world_weather, set_pose_system_active,
        set_world_setting, WORLD_TEMPERATURE_VALUES, WORLD_WEATHER_VALUES,
    )
    data = await request.json()
    world = data.get("world") or {}
    pose = data.get("pose") or {}
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


@router.patch("/locations/{location_id}/position")
async def update_location_position_route(location_id: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert die Raster-Position eines Ortes."""
    try:
        data = await request.json()
        user_id = data.get("user_id", "").strip()
        grid_x = data.get("grid_x")
        grid_y = data.get("grid_y")
        if grid_x is None or grid_y is None:
            raise HTTPException(status_code=400, detail="grid_x und grid_y erforderlich")

        loc = update_location_position(location_id, int(grid_x), int(grid_y))
        if not loc:
            raise HTTPException(status_code=404, detail="Ort nicht gefunden")
        return {"status": "success", "location": loc}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/locations/{location_name}")
def delete_location_route(
    location_name: str,
    character_name: str = Query("", alias="agent_name")
) -> Dict[str, Any]:
    """Loescht einen Ort (per ID oder Name)."""
    if delete_location(location_name):
        return {"status": "success", "deleted": location_name}
    raise HTTPException(status_code=404, detail="Ort nicht gefunden")


# ── Map Layout Import / Export ──

@router.get("/map/export")
def export_map_layout_route() -> StreamingResponse:
    """Stream a map-layout ZIP (positions only, no locations themselves)."""
    from app.core.content_io import export_map_layout_to_zip
    zip_bytes = export_map_layout_to_zip()
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="map_layout.zip"'},
    )


@router.post("/map/import")
async def import_map_layout_route(
    file: UploadFile = File(...),
    match_by: str = Query("auto", description="auto / id / name"),
) -> Dict[str, Any]:
    """Apply a saved map layout. Locations not present locally are skipped."""
    from app.core.content_io import import_map_layout_from_zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    try:
        return import_map_layout_from_zip(content, match_by=match_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Location Import / Export ──

@router.get("/locations/{location_id}/export")
def export_location_route(location_id: str) -> StreamingResponse:
    """Streams a single-location ZIP (DB row + rooms + gallery files)."""
    from app.core.content_io import export_location_to_zip
    try:
        zip_bytes = export_location_to_zip(location_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="location_{location_id}.zip"'},
    )


@router.post("/locations/import")
async def import_location_route(
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Import a location ZIP. Always creates a new location (new UUID)."""
    from app.core.content_io import import_location_from_zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    try:
        return import_location_from_zip(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# === Aktivitaeten (flache Compat-Liste) ===

@router.get("/activities")
def get_activities_route(character_name: str = Query("", alias="agent_name")
) -> Dict[str, Any]:
    """Listet alle Aktivitaeten eines Users auf (flat, dedupliziert)."""
    return {"activities": list_all_activities()}


@router.get("/conditions/list")
def list_conditions() -> Dict[str, Any]:
    """Liste aller Filter-IDs aus prompt_filters (shared + world overlay).

    Die Filter-`id` ist gleichzeitig der kanonische Condition-Name:
    sobald sie als Tag im Profil (active_conditions) steht, triggert der
    zugehoerige Filter implizit. Eine zusaetzliche `condition`-Expression
    am Filter (z.B. ``stamina<10``) wirkt als zweiter Auto-Trigger.

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


# === Hintergrundbilder ===

@router.head("/locations/{location_name}/background")
@router.get("/locations/{location_name}/background")
def get_location_background(
    location_name: str,
    room: str = Query("", description="Raum-ID fuer Bild-Filterung"),
    hour: int = Query(-1, description="Aktuelle Stunde (0-23) fuer Tag/Nacht-Auswahl"),
    file: str = Query("", description="Konkreter Hintergrund-Dateiname (bg_id) — Pin statt Zufallswahl")):
    """Liefert das Hintergrundbild eines Ortes (per ID oder Name).

    Bei aktivem disruption/danger-Event mit gerendertem image_path wird
    das Event-Bild ausgeliefert. Innerhalb des Resolve-Linger-Fensters
    das resolved_image_path. Sonst das normale Location-Background.
    Multi-Room: der Swap gilt fuer alle Raeume der Location (konsistent
    zur location-weiten Block-Rule).

    ``file`` pinnt ein konkretes Hintergrundbild (vom /play-Frontend genutzt,
    damit Figuren-Positionen am exakt angezeigten Bild haften). Ein aktives
    Event-Bild hat Vorrang und ignoriert ``file``.
    """
    # location_name kann ID oder Name sein — fuer den Event-Swap brauchen wir die ID.
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
    if not bg_path or not bg_path.exists():
        raise HTTPException(status_code=404, detail="Kein Hintergrundbild vorhanden")
    suffix = bg_path.suffix.lower()
    media_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
    return FileResponse(
        str(bg_path),
        media_type=media_types.get(suffix, 'image/png'),
        headers={"Cache-Control": "no-cache"}
    )


_MAP_MEDIA_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg', '.webp': 'image/webp'}


def _serve_map_icon(location_name: str, image_type: str, override_field: str):
    """Liefert das Karten-Icon eines Ortes fuer den gegebenen Galerie-Typ.

    Per-Zellen-Wahl: ist auf dem (geklonten) Ort ``override_field`` gesetzt und
    die Datei existiert in der owner-Galerie, wird GENAU dieses Bild geliefert —
    so kann jeder Kartenabschnitt bei mehreren Bildern ein eigenes zeigen.
    Sonst Fallback auf das erste als ``image_type`` getaggte Bild.
    """
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    loc_id = loc.get("id", "")
    if not loc_id:
        raise HTTPException(status_code=404, detail="Kein Karten-Bild vorhanden")

    # Klone teilen die Galerie ihres Templates (owner_id = Template-ID).
    from app.models.world import _gallery_owner_id
    owner_id = _gallery_owner_id(location_name) or loc_id
    gallery_dir = get_gallery_dir(owner_id)

    # 1) Per-Ort/Klon explizit gewaehltes Bild (wenn vorhanden + Datei existiert).
    chosen = (loc.get(override_field) or "").strip()
    if chosen:
        p = gallery_dir / chosen
        if p.exists():
            return FileResponse(str(p),
                                media_type=_MAP_MEDIA_TYPES.get(p.suffix.lower(), 'image/png'),
                                headers={"Cache-Control": "no-cache"})

    # 2) Fallback: erstes als image_type getaggtes Bild.
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


@router.head("/locations/{location_name}/map-icon-2d")
@router.get("/locations/{location_name}/map-icon-2d")
def get_location_map_icon_2d(location_name: str):
    """Flaches 2D-Karten-Icon — per-Zelle waehlbar via map_image_2d, sonst erstes 'map_2d'."""
    return _serve_map_icon(location_name, "map_2d", "map_image_2d")


# Map-Fit (Nachbar-Inpaint): Generier-Canvas-Groesse (16-GB-tauglich) + Ziel-
# Kachelgroesse, auf die die ausgeschnittene Mitte hochskaliert wird.
MAP_FIT_GEN_SIZE = 1024
MAP_FIT_OUT_TILE = 1024
# Wenn True: der ComfyUI-Workflow schneidet die Mitte selbst aus UND skaliert
# hoch (z.B. per Modell-Upscaler — besser als LANCZOS); das Backend speichert
# das Ergebnis dann unveraendert. False: Backend croppt+skaliert (LANCZOS).
# Der produktive Flux.1-Fill-Fit-Workflow (output_final = gecroppte, modell-
# hochskalierte Mitte) macht das selbst -> True.
MAP_FIT_WORKFLOW_HANDLES_CROP = True


def _resolve_map_icon_path(loc: Dict[str, Any], field: str = "map_image_2d",
                           image_type: str = "map_2d"):
    """Pfad des per-Zelle gewaehlten 2D-Karten-Tiles (sonst erstes getaggtes).
    Wiederverwendete Logik aus :func:`_serve_map_icon`, ohne FileResponse."""
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
    """Speichert den Canvas als RGBA mit der Maske im ALPHA-Kanal: Inpaint-Region
    (Maske weiss) -> transparent (alpha 0), Rest opak. Passt zu ComfyUI-LoadImage
    (``MASK = 1 - alpha``). Der RGB-Teil bleibt unveraendert (non-breaking)."""
    from PIL import ImageOps
    rgba = canvas.convert("RGBA")
    rgba.putalpha(ImageOps.invert(mask.convert("L")))
    rgba.save(path)


def _save_rgba_mask(mask, path: str) -> None:
    """RGBA-Maskenbild (gleiche Dimension wie der Canvas): weisse Flaeche, die
    markierte Region (``mask`` weiss) liegt im ALPHA-Kanal als transparent — wie
    beim Canvas. ComfyUI ``MASK = 1 - alpha`` ergibt genau diese Region (z.B. die
    Center-Zelle fuer den Crop, unabhaengig von der Inpaint-Maske)."""
    from PIL import Image, ImageOps
    rgba = Image.new("RGBA", mask.size, (255, 255, 255, 255))
    rgba.putalpha(ImageOps.invert(mask.convert("L")))
    rgba.save(path)


def _place_neighbors(location: Dict[str, Any]):
    """Baut den 3x3-Canvas (grau, Mitte=(1,1)) mit allen 8 Nachbar-Tiles
    (orthogonal + diagonal, je mit Anzeige-Rotation). Rueckgabe
    ``(canvas, tile, placed_imgs)`` oder ``None`` (keine Grid-Position/kein Nachbar)."""
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
    tile = MAP_FIT_GEN_SIZE // 3
    canvas = Image.new("RGB", (tile * 3, tile * 3), (128, 128, 128))
    dirs = {
        (-1, -1): (0, 0), (0, -1): (1, 0), (1, -1): (2, 0),
        (-1, 0): (0, 1),                   (1, 0): (2, 1),
        (-1, 1): (0, 2), (0, 1): (1, 2), (1, 1): (2, 2),
    }
    placed_imgs = {}
    for (dx, dy), (col, row) in dirs.items():
        nb = by_pos.get((gx + dx, gy + dy))
        p = _resolve_map_icon_path(nb) if nb else None
        if not p:
            continue
        try:
            img = Image.open(p).convert("RGB").resize((tile, tile))
            rot = int(nb.get("map_rotation_2d") or 0)
            if rot:
                img = img.rotate(-rot, expand=False, fillcolor=(128, 128, 128))
            canvas.paste(img, (col * tile, row * tile))
            placed_imgs[(dx, dy)] = img
        except Exception as _e:
            logger.warning("Nachbar-Tile %s nicht ladbar: %s", p, _e)
    if not placed_imgs:
        return None
    return canvas, tile, placed_imgs


def _finalize_blend(canvas, inpaint_mask, tile, placed_imgs, crop_empty: bool):
    """Gemeinsamer Abschluss fuer Fit/Edge. Erzeugt zusaetzlich eine CROP-Maske
    (immer die Center-Zelle, unabhaengig von der Inpaint-Maske), schneidet bei
    ``crop_empty`` KOMPLETT leere Aussen-Zeilen/-Spalten weg (auch fuer Edge am
    Kartenrand) und speichert:
      - Canvas als RGBA (Inpaint-Maske im Alpha)   -> cpath
      - Inpaint-Maske als L                        -> mpath
      - Crop-Maske als RGBA (Center-Zelle im Alpha) -> crop_path
    Rueckgabe ``(cpath, mpath, tile, crop_path)``."""
    import tempfile
    from PIL import Image, ImageDraw
    crop_mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(crop_mask).rectangle([tile, tile, tile * 2 - 1, tile * 2 - 1], fill=255)
    if crop_empty:
        # Aussen-Zeile/-Spalte nur abschneiden, wenn sie KOMPLETT leer ist
        # (auch keine Ecke) — sonst blieben Ecken-Tiles erhalten.
        left = 0 if any(d in placed_imgs for d in ((-1, -1), (-1, 0), (-1, 1))) else tile
        right = tile * 3 if any(d in placed_imgs for d in ((1, -1), (1, 0), (1, 1))) else tile * 2
        top = 0 if any(d in placed_imgs for d in ((-1, -1), (0, -1), (1, -1))) else tile
        bottom = tile * 3 if any(d in placed_imgs for d in ((-1, 1), (0, 1), (1, 1))) else tile * 2
        if (left, top, right, bottom) != (0, 0, tile * 3, tile * 3):
            canvas = canvas.crop((left, top, right, bottom))
            inpaint_mask = inpaint_mask.crop((left, top, right, bottom))
            crop_mask = crop_mask.crop((left, top, right, bottom))
            logger.info("Map-Blend: leere Kanten abgeschnitten -> Canvas %dx%d",
                        right - left, bottom - top)
    cpath = tempfile.NamedTemporaryFile(suffix="_mapblend_canvas.png", delete=False).name
    mpath = tempfile.NamedTemporaryFile(suffix="_mapblend_mask.png", delete=False).name
    crop_path = tempfile.NamedTemporaryFile(suffix="_mapblend_crop.png", delete=False).name
    # Canvas OHNE Alpha-Maske (reines RGB) — die Inpaint-Maske wird separat als
    # input_mask ausgegeben (Verdacht: Alpha-im-Bild macht Probleme).
    canvas.convert("RGB").save(cpath)
    inpaint_mask.save(mpath)
    _save_rgba_mask(crop_mask, crop_path)
    return cpath, mpath, tile, crop_path


def _compose_neighbor_canvas(location: Dict[str, Any], crop_empty: bool = False):
    """Fit: 3x3-Canvas (8 Nachbarn, graue Mitte) + Inpaint-Maske = Mitte. Schneidet
    bei ``crop_empty`` leere Aussenkanten weg. Canvas traegt die Maske im Alpha,
    zusaetzlich eine separate Crop-Maske (Center-Zelle, RGBA). Rueckgabe
    ``(canvas, mask, tile, crop_mask)`` (Pfade) oder ``None``."""
    from PIL import Image, ImageDraw
    placed = _place_neighbors(location)
    if not placed:
        return None
    canvas, tile, placed_imgs = placed
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).rectangle([tile, tile, tile * 2 - 1, tile * 2 - 1], fill=255)
    return _finalize_blend(canvas, mask, tile, placed_imgs, crop_empty)


# Edge-Match (Kanten angleichen): Rahmen-Maskenbreite + solider Kern an der Kante.
MAP_EDGE_BLEND_FRAC = 0.45
MAP_EDGE_CORE_FRAC = 0.30
_EDGE_DIRS = (("north", 0, -1), ("south", 0, 1), ("east", 1, 0), ("west", -1, 0))


def _analyze_tile_terrain(loc: Dict[str, Any]):
    """Vision-Terrain-Phrase des AKTUELLEN 2D-Tiles, gecached pro Tile-Dateiname
    in der Galerie-Meta. ``None`` wenn Vision aus / kein Tile / Fehler. So
    beschreiben north/south/east/west das echte Bild, nicht die evtl. veraltete
    Textbeschreibung. Re-Analyse nur bei neuem Tile (anderer Dateiname)."""
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
    """Kurzer Terrain-Begriff eines Tiles: Vision-Analyse des AKTUELLEN Tiles
    (wenn aktiviert), sonst eigener 2D-Map-Prompt, sonst Beschreibung, sonst Name
    — erste Aussage, ~80 Zeichen an Wortgrenze, ohne haengende Funktionswoerter."""
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
    """{seite: nachbar-loc} fuer die 4 orthogonalen Seiten mit Nachbar, der ein
    2D-Tile hat (sonst kein Eintrag)."""
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
    """Auto-Prompt fuer Map-Fit (graue Mitte NEU erzeugen): ein Tile, das alle
    Nachbar-Terrains verschmilzt — gleiche Qualitaets-Sprache wie der Edge-Prompt
    (Farb-/Ton-/Stil-Angleich), nur aufs ganze Tile statt nur die Kanten."""
    parts = [f"{_terrain_term(nb)} to the {side}" for side, nb in _neighbor_sides(location).items()
             if _terrain_term(nb)]
    if not parts:
        return ""
    return ("top-down orthographic map tile blending together the surrounding "
            "terrain — " + ", ".join(parts) + "; colors, tones and art style merge "
            "smoothly across the whole tile, cohesive unified palette and lighting, "
            "no hard seams")


def _edge_transition_prompt(location: Dict[str, Any], sides=None) -> str:
    """Prompt fuer „Kanten angleichen": das bestehende Mittel-Tile, dessen Raender
    in die gewaehlten Nachbar-Terrains uebergehen (Farbe/Ton/Stil verschmelzen)."""
    avail = _neighbor_sides(location)
    use = [s for s in (sides or list(avail)) if s in avail]
    if not use:
        return ""
    parts = [f"{_terrain_term(avail[s])} to the {s}" for s in use if _terrain_term(avail[s])]
    return ("top-down orthographic map tile; its edges blend into the adjacent "
            "terrain — " + ", ".join(parts) + "; colors, tones and art style merge "
            "smoothly across the edges, cohesive unified palette and lighting, no hard seams")


def _compose_edge_canvas(location: Dict[str, Any], sides=None):
    """Wie :func:`_compose_neighbor_canvas` (3x3, echte Nachbarn rundum), ABER die
    Mitte ist das ECHTE Tile und die Maske ist ein RAHMEN (Distanz-Transform) nur
    fuer die gewaehlten Seiten mit Nachbar: an der Kante solide, gleichmaessig zur
    Mitte hin auf 0. Rueckgabe (canvas_path, mask_path, tile) oder None."""
    import numpy as np
    from PIL import Image
    avail = _neighbor_sides(location)
    use = [s for s in (sides or list(avail)) if s in avail]
    placed = _place_neighbors(location)
    if not placed or not use:
        return None
    canvas, tile, placed_imgs = placed
    # Mitte mit dem echten Tile fuellen (statt grau).
    tp = _resolve_map_icon_path(location)
    if tp:
        t_img = Image.open(tp).convert("RGB").resize((tile, tile))
        rot = int(location.get("map_rotation_2d") or 0)
        if rot:
            t_img = t_img.rotate(-rot, expand=False, fillcolor=(128, 128, 128))
        canvas.paste(t_img, (tile, tile))
    # Rahmen-Maske via Distanz-Transform.
    W, H = canvas.size
    cx0, cy0, cx1, cy1 = tile, tile, 2 * tile, 2 * tile
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
    # Auch Edge schneidet leere Kanten weg (z.B. am Kartenrand).
    return _finalize_blend(canvas, mask, tile, placed_imgs, crop_empty=True)


@router.patch("/locations/{location_id}/map-image")
async def set_location_map_image_route(location_id: str, request: Request) -> Dict[str, Any]:
    """Setzt das pro Kartenabschnitt angezeigte 2D-Tile eines Ortes/Klons.

    Body: ``{"type": "map_2d", "file": "<gallery-filename>"|""}``.
    Leerer ``file`` entfernt die Wahl (Fallback auf first-match). Das Bild muss
    in der Galerie des Owners (Template bei Klonen) liegen.
    """
    from app.models.world import set_location_map_image
    data = await request.json()
    image_type = (data.get("type") or "").strip()
    filename = (data.get("file") or "").strip()
    if image_type != "map_2d":
        raise HTTPException(status_code=400, detail="type muss 'map_2d' sein")
    loc = set_location_map_image(location_id, "map_image_2d", filename)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    return {"status": "success", "location": loc}


@router.get("/locations/{location_name}/fit-prompt")
def get_location_fit_prompt(location_name: str) -> Dict[str, Any]:
    """Auto-Prompt fuer „Fit to neighbors": der Richtungs-Hinweis aus den 4
    orthogonalen Nachbarn (north/south/east/west; „blend seamlessly…"). Leerer
    String, wenn keine Nachbarn/Grid-Position. Der Dialog zeigt ihn als
    editierbaren Prompt — beim Submit zaehlt er als custom_prompt, der Server
    haengt ihn dann NICHT erneut an."""
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    return {"prompt": _neighbor_terrain_hint(loc)}


@router.get("/locations/{location_name}/fit-canvas")
def get_location_fit_canvas(location_name: str):
    """Vorschau des 3×3-Nachbar-Canvas, der bei „Fit to neighbors" als
    input_reference_image in den Workflow geht (Mitte grau = wird inpaintet).
    404 wenn keine Nachbarn mit Tile / keine Grid-Position."""
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    comp = _compose_neighbor_canvas(loc)
    if not comp:
        raise HTTPException(status_code=404, detail="Keine Nachbarn mit Tile")
    cpath = comp[0]
    try:
        data = Path(cpath).read_bytes()
    finally:
        for _p in comp[:2] + comp[3:]:  # cpath, mpath, crop_path (Pfade)
            try:
                os.remove(_p)
            except Exception:
                pass
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@router.get("/locations/{location_name}/edges")
def get_location_edges(location_name: str) -> Dict[str, Any]:
    """Welche der 4 Seiten haben einen Nachbarn mit 2D-Tile (fuer den Kanten-
    Angleich-Dialog): {sides: {north: "<name>", east: "<name>", ...}}."""
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    return {"sides": {s: nb.get("name", "") for s, nb in _neighbor_sides(loc).items()}}


@router.get("/locations/{location_name}/edge-prompt")
def get_location_edge_prompt(location_name: str, sides: str = Query("")) -> Dict[str, Any]:
    """Dynamischer Uebergangs-Prompt fuer „Kanten angleichen" — aus den gewaehlten
    Seiten (kommagetrennt; leer = alle vorhandenen). Im Dialog editierbar."""
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    _sides = [s.strip() for s in sides.split(",") if s.strip()] or None
    return {"prompt": _edge_transition_prompt(loc, _sides)}


@router.patch("/locations/{location_id}/map-rotation")
async def set_location_map_rotation_route(location_id: str, request: Request) -> Dict[str, Any]:
    """Setzt die 90°-Drehung des 2D-Karten-Icons eines Ortes/Klons (Anzeige-Transform).

    Body: ``{"rotation": 0|90|180|270}``. Nur Anzeige (CSS rotate), das Bild
    selbst bleibt unveraendert.
    """
    from app.models.world import set_location_map_rotation
    data = await request.json()
    try:
        rotation = int(data.get("rotation", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="rotation muss 0/90/180/270 sein")
    if rotation % 360 not in (0, 90, 180, 270):
        raise HTTPException(status_code=400, detail="rotation muss 0/90/180/270 sein")
    loc = set_location_map_rotation(location_id, rotation)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    return {"status": "success", "location": loc}


@router.post("/locations/{location_name}/background")
async def generate_location_background(location_name: str, request: Request) -> Dict[str, Any]:
    """Generiert ein Hintergrundbild fuer einen Ort per Image-Backend (per ID oder Name)."""
    try:
        data = await request.json()
        user_id = data.get("user_id", "").strip()
        custom_prompt = data.get("prompt", "").strip()

        # Location per ID oder Name aufloesen
        location = resolve_location(location_name)
        if not location:
            raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

        description = location.get("description", location_name)

        # Prompt zusammenbauen
        if custom_prompt:
            prompt = custom_prompt
        else:
            prompt = (
                f"{description}, wide angle establishing shot, no people, "
                f"atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio"
            )

        # Image-Backend holen (guenstigstes verfuegbares)
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

        # Bild generieren (blockierend in Thread)
        full_prompt = prompt
        if backend.prompt_prefix:
            full_prompt = f"{backend.prompt_prefix}, {full_prompt}"

        negative = backend.negative_prompt or ""
        # Location-Background: volle Aufloesung — wird als Hintergrund-Szenenbild
        # genutzt, kein Downscale.
        params = {"width": _location_image_width(), "height": _location_image_height()}
        # Default-Workflow und Model ermitteln
        active_wf = getattr(img_skill, '_default_workflow', None)
        if active_wf and active_wf.workflow_file:
            params["workflow_file"] = active_wf.workflow_file
        # Model setzen (input_unet vs input_model)
        if active_wf and active_wf.model:
            _model_key = "unet" if active_wf.has_input_unet else "model"
            params[_model_key] = active_wf.model
            # Model-Verfuegbarkeit pruefen und ggf. aehnlichstes Modell finden
            _resolved = img_skill.resolve_model_for_backend(
                params[_model_key], backend, active_wf.model_type if active_wf else "")
            if _resolved and _resolved != params[_model_key]:
                logger.info("Model-Resolve: %s -> %s (Backend: %s)", params[_model_key], _resolved, backend.name)
                params[_model_key] = _resolved
        # CLIP-Pairing fuer Flux2-Workflows
        if active_wf and active_wf.clip:
            params["clip_name"] = active_wf.clip

        # Frischer Seed pro Aufruf gegen ComfyUI Cache-Hit
        # (Memory feedback_no_new_image_sentinel).
        if active_wf and active_wf.has_seed:
            import random as _rnd
            params["seed"] = _rnd.randint(1, 2**31 - 1)

        # Backend-Fallback-Engine: probiert primary, faellt bei Fehler auf
        # backend.fallback_mode (none/next_cheaper/specific) zurueck.
        def _op(b):
            return b.generate(full_prompt, negative, params)
        try:
            images, backend = await asyncio.to_thread(
                lambda: img_skill.run_with_fallback(
                    primary_backend=backend,
                    op=_op,
                    workflow=active_wf,
                    character_name=""))
        except RuntimeError as _err:
            raise HTTPException(status_code=500, detail=str(_err))

        # ComfyUI Cache-Hit: Backend gibt String-Sentinel zurueck.
        if images == "NO_NEW_IMAGE":
            raise HTTPException(
                status_code=409,
                detail="ComfyUI hat das Bild bereits mit diesem Seed/Model erzeugt "
                       "(Cache-Hit). Erneut versuchen oder Backend neu starten.")

        if not images:
            raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

        # In Gallery speichern + als Hintergrund referenzieren
        import time
        loc_id = location.get("id", location_name)
        gallery_dir = get_gallery_dir(loc_id)
        gallery_dir.mkdir(parents=True, exist_ok=True)
        image_name = f"{int(time.time())}.png"
        image_path = gallery_dir / image_name
        image_path.write_bytes(images[0])

        # Automatisch als Hintergrund markieren
        toggle_background_image(loc_id, image_name)

        logger.info("Bild generiert + als Hintergrund markiert: %s (%s) -> gallery/%s/%s", location['name'], loc_id, loc_id, image_name)
        return {"status": "success", "location": location["name"], "location_id": loc_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Background Fehler: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/locations/{location_name}/background")
async def delete_location_background(request: Request, location_name: str) -> Dict[str, Any]:
    """Loescht die Hintergrundbild-Referenz eines Ortes (per ID oder Name)."""
    try:
        data = await request.json()
        user_id = data.get("user_id", "").strip()

        loc = resolve_location(location_name)
        loc_id = loc["id"] if loc and loc.get("id") else location_name
        # Alle Hintergrund-Markierungen entfernen
        for img in get_background_images(loc_id):
            toggle_background_image(loc_id, img)
        return {"status": "success", "location": location_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Location-Galerie ===

@router.get("/locations/{location_name}/gallery")
def get_location_gallery(
    location_name: str) -> Dict[str, Any]:
    """Listet alle Galerie-Bilder eines Ortes auf (mit Hintergrund-Status)."""
    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name
    images = list_gallery_images(location_name)
    bg_images = get_background_images(loc_id)
    image_rooms = get_gallery_image_rooms(loc_id)
    image_types = get_gallery_image_types(loc_id)
    image_metas = get_gallery_image_metas(loc_id)
    prompts = get_all_gallery_prompts(loc_id)
    # Raeume fuer Dropdown im Frontend
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


@router.get("/locations/{location_name}/gallery/{image_name}")
def get_gallery_image(
    location_name: str,
    image_name: str):
    """Liefert ein einzelnes Galerie-Bild."""
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")
    gallery_dir = get_gallery_dir(location_name)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    suffix = image_path.suffix.lower()
    media_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
    return FileResponse(
        str(image_path),
        media_type=media_types.get(suffix, 'image/png'),
        headers={"Cache-Control": "no-cache"}
    )


@router.get("/imagegen-options")
def get_imagegen_options() -> Dict[str, Any]:
    """Gibt verfuegbare Image-Generation-Backends/Workflows zurueck (ohne Character-Bindung)."""
    from app.core.dependencies import get_skill_manager

    sm = get_skill_manager()
    imagegen = sm.get_skill("image_generation")
    if not imagegen:
        return {"options": []}

    options = []
    # ComfyUI-Workflows
    for wf in imagegen.get_comfy_workflows():
        options.append({
            "type": "workflow",
            "name": wf["name"],
            "label": f"ComfyUI: {wf['name']}",
            "has_loras": wf.get("has_loras", False),
            "default_loras": wf.get("default_loras", []),
            "model_type": wf.get("model_type", ""),
            "default_model": wf.get("model", ""),
            "filter": wf.get("filter", ""),
            "ref_slot_count": wf.get("ref_slot_count", 0),
        })
    # Nicht-ComfyUI Backends
    for b in imagegen.backends:
        if b.api_type == "comfyui":
            continue
        if not b.available or not b.instance_enabled:
            continue
        opt = {
            "type": "backend",
            "name": b.name,
            "label": b.name,
        }
        # Backend mit Modellliste (z.B. Together.ai) — direkt als Auswahl anbieten
        backend_models = getattr(b, 'available_models', [])
        if backend_models:
            opt["models"] = backend_models
            opt["default_model"] = getattr(b, 'model', backend_models[0])
        options.append(opt)
    # Default-Vorauswahl fuer Location aus .env
    loc_default = os.environ.get("LOCATION_IMAGEGEN_DEFAULT", "").strip()
    result = {"options": options}
    # Unabhaengige Config-Prompt-Teile, damit der Dialog sie EDITIERBAR zeigen kann
    # (statt sie serverseitig anzuhaengen): Karten-Icon-Suffixe.
    result["map_2d_image_prompt_suffix"] = (os.environ.get("MAP_2D_IMAGE_PROMPT_SUFFIX") or "").strip()
    # Fit/Match-edges: imagegen-Target (Match-Spec, read-only im Fit-Dialog).
    result["mapfit_imagegen_default"] = (os.environ.get("MAPFIT_IMAGEGEN_DEFAULT") or "workflow:Flux Inpaint*").strip()
    if loc_default:
        result["default_location"] = loc_default
    return result


@router.get("/imagegen-models")
def get_imagegen_models(model_type: str = Query("", description="unet|checkpoint")) -> Dict[str, Any]:
    """Gibt verfuegbare Modelle zurueck (aus Startup-Cache, ohne Character-Bindung)."""
    from app.core.dependencies import get_skill_manager

    sm = get_skill_manager()
    imagegen = sm.get_skill("image_generation")
    if not imagegen:
        return {"models": []}

    models = imagegen.get_cached_checkpoints(model_type)
    models_by_service = imagegen.get_cached_checkpoints_by_service(model_type)
    return {"models": models, "models_by_service": models_by_service}


@router.get("/imagegen-loras")
def get_imagegen_loras() -> Dict[str, Any]:
    """Gibt verfuegbare LoRAs zurueck (aus Startup-Cache, ohne Character-Bindung)."""
    from app.core.dependencies import get_skill_manager

    sm = get_skill_manager()
    imagegen = sm.get_skill("image_generation")
    if not imagegen:
        return {"loras": []}

    loras = imagegen.get_cached_loras()
    return {"loras": ["None"] + loras}


@router.post("/locations/{location_name}/gallery/batch")
async def generate_gallery_batch(location_name: str, request: Request) -> Dict[str, Any]:
    """Startet Batch-Generierung aller Bilder fuer einen Ort (Background-Task)."""
    data = await request.json()
    user_id = data.get("user_id", "").strip()
    jobs = data.get("jobs", [])
    workflow = data.get("workflow", "").strip()
    backend_name = data.get("backend", "").strip()
    loras = data.get("loras")
    model_override = data.get("model_override", "").strip()
    if not jobs:
        raise HTTPException(status_code=400, detail="Keine Jobs angegeben")

    location = resolve_location(location_name)
    if not location:
        raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

    # Alle Jobs vorab als pending Tracked-Tasks registrieren,
    # damit sie im Queue-Panel sichtbar sind
    from app.core.task_queue import get_task_queue
    _tq = get_task_queue()
    _batch_track_ids = []
    for job in jobs:
        _tid = _tq.track_start(
            "image_gen",
            job.get("label", "Ort-Bild"),
            agent_name=location.get("name", location_name),
            start_running=False)
        _batch_track_ids.append(_tid)

    async def _run_batch():
        for i, job in enumerate(jobs):
            _track_id = _batch_track_ids[i]
            try:
                body = {"user_id": "", "_batch_track_id": _track_id}
                if job.get("room_id"):
                    body["room_id"] = job["room_id"]
                if job.get("prompt_type"):
                    body["prompt_type"] = job["prompt_type"]
                if workflow:
                    body["workflow"] = workflow
                if backend_name:
                    body["backend"] = backend_name
                if loras:
                    body["loras"] = loras
                if model_override:
                    body["model_override"] = model_override

                class _MockRequest:
                    async def json(self):
                        return body

                await generate_gallery_image(location_name, _MockRequest())
                logger.info("Batch-Job fertig: %s / %s", location.get("name"), job.get("label", ""))
            except Exception as e:
                _tq.track_finish(_track_id, error=str(e))
                logger.warning("Batch-Job fehlgeschlagen: %s / %s: %s",
                               location.get("name"), job.get("label", ""), e)

    # Background-Task starten
    asyncio.ensure_future(_run_batch())

    return {
        "status": "started",
        "location": location.get("name"),
        "job_count": len(jobs),
    }


@router.post("/locations/{location_name}/gallery")
async def generate_gallery_image(location_name: str, request: Request) -> Dict[str, Any]:
    """Generiert ein neues Galerie-Bild fuer einen Ort (per ID oder Name).

    Single-Mode (kein ``_batch_track_id`` im Body) ist fire-and-forget:
    Vorab-Validierung + Track-Start, Heavy-Lifting laeuft als
    ``asyncio.create_task``, die HTTP-Antwort kommt sofort mit
    ``status=started`` und ``track_id``. Die UI pollt die Galerie
    bzw. das Queue-Panel auf Fertigstellung.

    Batch-Mode (mit vorhandenem ``_batch_track_id``) bleibt synchron,
    damit der Batch-Handler die Jobs sequentialisieren kann.
    """
    import time

    try:
        data = await request.json()
        batch_track_id = data.get("_batch_track_id", "")

        # Batch-Mode: synchron — Batch-Loop oben (``generate_gallery_batch``)
        # awaitet jeden Job. Hier rein in den Inner-Body, ohne Fire-and-Forget.
        if batch_track_id:
            return await _generate_gallery_image_inner(location_name, data)

        # Single-Mode: fire-and-forget.
        # Frueh-Validierung damit 404/400 sofort am Client landen, nicht im
        # Background-Task verloren gehen.
        location = resolve_location(location_name)
        if not location:
            raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

        from app.core.task_queue import get_task_queue
        _tq = get_task_queue()
        # Pending-Track anlegen (analog zu Batch). Der Inner-Body ruft
        # track_activate sobald das Backend bekannt ist.
        _track_id = _tq.track_start(
            "image_gen", "Ort-Bild",
            agent_name=location.get("name", location_name),
            start_running=False)
        data["_batch_track_id"] = _track_id  # nutzt den Batch-Aktivierungspfad im Inner-Body

        async def _bg():
            # Inner-Body handhabt track_finish in seinen except-Blocks. Hier
            # nur loggen, damit nichts stillschweigend verschwindet.
            try:
                await _generate_gallery_image_inner(location_name, data)
            except HTTPException as he:
                logger.warning("Gallery Background-Generierung HTTP-Fehler: %s", he.detail)
            except Exception as e:
                logger.error("Gallery Background-Generierung Fehler: %s", e, exc_info=True)

        asyncio.create_task(_bg())
        return {
            "status": "started",
            "track_id": _track_id,
            "location": location["name"],
            "location_id": location.get("id", location_name),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Gallery Fehler: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


async def _generate_gallery_image_inner(location_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Eigentliche Generierungslogik — wird vom Single-Mode als Background-
    Task gefeuert und vom Batch-Mode direkt awaited.
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
        # Kanten angleichen: gleicher mapfit-Workflow wie Fit, nur Maske (Rahmen)
        # + Prompt (Uebergang) unterscheiden sich. edge_sides = gewaehlte Seiten.
        edge_match = bool(data.get("edge_match"))
        edge_sides = data.get("edge_sides") or None
        _map_blend = fit_neighbors or edge_match

        location = resolve_location(location_name)
        if not location:
            raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

        # Prompt-Quelle: custom_prompt > Raum+Typ > Raum > Prompt-Typ > Ortsbeschreibung
        if custom_prompt:
            prompt = custom_prompt
        else:
            description = ""
            if room_id:
                room = get_room_by_id(location, room_id)
                if room:
                    # Raum mit Prompt-Typ: Tag/Nacht-Prompt des Raums bevorzugen
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

            if prompt_type == "map_2d":
                # Subject only — the admin-managed style suffix is appended below.
                prompt = description
            else:
                prompt = (
                    f"{description}, wide angle establishing shot, no people, "
                    f"atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio"
                )

        # Map-icon style suffix (config). Nur noch serverseitig anhaengen, wenn der
        # Aufrufer ihn NICHT schon im Prompt mitliefert (``settings_applied`` =
        # Dialog hat den editierbaren Suffix bereits eingebaut → kein Doppeln).
        if not data.get("settings_applied"):
            if prompt_type == "map_2d":
                _sfx = (os.environ.get("MAP_2D_IMAGE_PROMPT_SUFFIX") or "").strip()
                if _sfx:
                    prompt = f"{prompt}, {_sfx}"

        from app.core.dependencies import get_skill_manager

        skill_manager = get_skill_manager()
        img_skill = None
        for skill in skill_manager.skills:
            if getattr(skill, 'SKILL_ID', '') == "image_generation":
                img_skill = skill
                break

        if not img_skill:
            raise HTTPException(status_code=503, detail="ImageGeneration Skill nicht verfuegbar")

        # Verfuegbarkeit aller Backends frisch pruefen — Netzwerk-Calls in einen
        # Thread, sonst blockieren sie die Event-Loop (Watchdog schlaegt an).
        await asyncio.to_thread(
            lambda: [b.check_availability()
                     for b in img_skill.backends if b.instance_enabled])

        # Backend-Auswahl: explizit > Workflow > Auto (guenstigster)
        backend = None
        active_wf = None  # via Match aufgeloester Workflow — unten fuer workflow_file wiederverwendet
        _fit_file = ""    # roher Fit-Workflow-Pfad (festverdrahtete Funktion)
        if _map_blend:
            # Fit UND Kanten-Angleich nutzen das normale ComfyUI-Workflow-Matching
            # (Default: "workflow:Flux Inpaint*"). Der gewaehlte Workflow muss die
            # Inpaint-Nodes haben (input_reference_image=Canvas, input_mask,
            # input_crop, output_final). Model/Clip/Clip2/LoRA werden normal injiziert.
            _fit_spec = (os.environ.get("MAPFIT_IMAGEGEN_DEFAULT") or "workflow:Flux Inpaint*").strip()
            backend, active_wf = img_skill.resolve_imagegen_target(
                _fit_spec, rotation_prefix="mapfit")
            if active_wf and not backend:
                raise HTTPException(
                    status_code=503,
                    detail=f"Kein ComfyUI-Backend fuer Map-Fit-Workflow '{active_wf.name}' verfuegbar")
            logger.info("Map-Blend (%s): spec=%s -> Workflow=%s Backend=%s",
                        "edge" if edge_match else "fit", _fit_spec,
                        active_wf.name if active_wf else "-",
                        backend.name if backend else "-")
        elif workflow_name:
            # Match-Konzept: Glob + Verfuegbarkeit statt exaktem Workflow-Namen.
            backend, active_wf = img_skill.resolve_imagegen_target(
                workflow_name, rotation_prefix="world_image")
            if active_wf and not backend:
                raise HTTPException(
                    status_code=503,
                    detail=f"Kein ComfyUI-Backend fuer Workflow '{active_wf.name}' verfuegbar")
            if not active_wf:
                logger.warning(
                    "Workflow '%s' nicht gefunden, verfuegbar: [%s]",
                    workflow_name, ", ".join(w.name for w in img_skill.comfy_workflows))
            else:
                logger.info("Workflow (match): %s -> %s -> Backend: %s",
                            workflow_name, active_wf.name, backend.name if backend else "-")
        elif backend_name:
            backend = img_skill.match_backend(backend_name)  # Backend-Glob via Match-Konzept
            logger.debug("Explizites Backend: %s -> %s", backend_name, backend.name if backend else 'nicht verfuegbar')

        if not backend:
            backend = img_skill._select_backend()
        if not backend:
            raise HTTPException(status_code=503, detail="Kein Image-Backend verfuegbar")

        # Map-Blend: Auto-Prompt nur als Fallback, wenn KEIN Prompt mitkam (der
        # Dialog liefert ihn bereits editierbar via .../fit-prompt bzw. .../edge-prompt).
        if _map_blend and not custom_prompt:
            # Terrain-Analyse macht blockierende LLM-Submits (describe_map_tile,
            # bis zu einer pro Nachbarseite) → in einen Thread, damit die
            # Event-Loop frei bleibt. War die Ursache des Watchdog-Blocks.
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

        full_prompt = prompt
        if backend.prompt_prefix:
            full_prompt = f"{backend.prompt_prefix}, {full_prompt}"

        negative = backend.negative_prompt or ""
        # Map-Icons sind kleine Thumbnails fuer die Welt-Uebersicht und werden
        # runtergerechnet. Day/Night/Description bleiben in voller Aufloesung
        # als Hintergrund-Bilder.
        params: Dict[str, Any] = {"width": _location_image_width(), "height": _location_image_height()}
        if prompt_type == "map_2d":
            params["image_use_case"] = "map"
            # 2D-Map-Tiles quadratisch (1:1, Flux-native 1024) generieren statt
            # im 16:9 Location-Format — fuellt das Tile. Sonst Querformat.
            params["width"] = 1024
            params["height"] = 1024
        if _map_blend:
            # Festverdrahtet: roher Workflow-File direkt, kein active_wf, KEIN
            # Model/Clip/LoRA-Override — alles ist im File. Frischer Seed gegen
            # den NO_NEW_IMAGE-Cache-Hit (input_seed-Node im File).
            if _fit_file:
                params["workflow_file"] = _fit_file
            import random as _rnd
            params["seed"] = _rnd.randint(1, 2**31 - 1)
        else:
            # Workflow-File: expliziter Workflow hat Vorrang vor Default-Workflow
            # Workflow-File: den oben (Match) aufgeloesten active_wf wiederverwenden,
            # damit Backend-Wahl und workflow_file denselben Workflow nutzen; ohne
            # expliziten Workflow den Default-Workflow nehmen.
            if not workflow_name:
                active_wf = getattr(img_skill, '_default_workflow', None)
            if active_wf and active_wf.workflow_file:
                params["workflow_file"] = active_wf.workflow_file
            # Model-Override (input_unet Workflows brauchen "unet" statt "model")
            _model_key = "unet" if (active_wf and active_wf.has_input_unet) else "model"
            if model_override:
                params[_model_key] = model_override
            elif active_wf and active_wf.model:
                params[_model_key] = active_wf.model
            # Model-Verfuegbarkeit pruefen und ggf. aehnlichstes Modell finden
            _current_model = params.get(_model_key, "")
            if _current_model and backend.api_type == "comfyui" and img_skill:
                _resolved = img_skill.resolve_model_for_backend(
                    _current_model, backend, active_wf.model_type if active_wf else "")
                if _resolved and _resolved != _current_model:
                    logger.info("Model-Resolve: %s -> %s (Backend: %s)", _current_model, _resolved, backend.name)
                    params[_model_key] = _resolved
            # CLIP-Pairing fuer Flux2-Workflows
            if active_wf and active_wf.clip:
                params["clip_name"] = active_wf.clip
            # LoRA-Inputs
            if active_wf and active_wf.has_loras:
                if loras_override is not None:
                    params["lora_inputs"] = loras_override
                elif active_wf.default_loras:
                    params["lora_inputs"] = active_wf.default_loras

            # Frischer Seed pro Aufruf — sonst gibt ComfyUI bei identischem
            # Prompt+Seed den NO_NEW_IMAGE-Sentinel und das Bild wird nie
            # neu erzeugt (Memory feedback_no_new_image_sentinel).
            if active_wf and active_wf.has_seed:
                import random as _rnd
                params["seed"] = _rnd.randint(1, 2**31 - 1)

        # Selbst-Referenz: das bestehende (Karten-)Bild als Referenz in Slot 1 —
        # fuer „Regenerate mit aktuellem Bild" (z.B. damit 2D-Tiles besser
        # zusammenpassen). Nur wenn der Workflow Ref-Slots hat.
        if (data.get("use_source_as_reference") and data.get("reference_image")
                and active_wf and active_wf.ref_slot_count):
            _ref_name = (data.get("reference_image") or "").strip()
            if _ref_name and "/" not in _ref_name and ".." not in _ref_name:
                # get_gallery_dir ist modulweit importiert (oben). KEIN lokaler
                # Import hier — der wuerde get_gallery_dir funktionsweit zur
                # lokalen Variable machen und den Save-Pfad (unten) mit
                # UnboundLocalError sprengen, sobald dieser Block nicht laeuft.
                _ref_path = get_gallery_dir(location_name) / _ref_name
                if _ref_path.exists():
                    params["reference_images"] = {"input_reference_image_1": str(_ref_path)}
                    logger.info("Map-Selbst-Referenz in Slot 1: %s", _ref_name)

        # Nachbar-Kontext-Inpainting: 3x3-Canvas + Maske bauen und als
        # input_reference_image/input_mask injizieren. Fit = graue Mitte (ganzes
        # Tile neu); Edge = echtes Tile + Rahmen-Maske der gewaehlten Seiten.
        _fit_comp = None
        if _map_blend:
            _fit_comp = (_compose_edge_canvas(location, edge_sides) if edge_match
                         else _compose_neighbor_canvas(location, crop_empty=True))
            if _fit_comp:
                _cpath, _mpath, _ctile, _crop = _fit_comp
                # Canvas (reines RGB) -> input_reference_image, Inpaint-Maske
                # SEPARAT -> input_mask, Crop-Maske (Center-Zelle) -> input_crop.
                params["reference_images"] = {
                    "input_reference_image": _cpath, "input_mask": _mpath,
                    "input_crop": _crop}
                params["width"] = MAP_FIT_OUT_TILE
                params["height"] = MAP_FIT_OUT_TILE
                logger.info("Map-Blend: Canvas + Inpaint-/Crop-Maske injiziert, Ziel %dpx",
                            MAP_FIT_OUT_TILE)
                # Debug: das, was REAL in den Workflow geht, zum Inspizieren ablegen
                # (letzter Lauf). So vergleichbar mit dem manuellen ComfyUI-Test.
                try:
                    import shutil as _sh
                    from app.core.paths import get_storage_dir as _gsd
                    _dbg = _gsd() / "mapblend_debug"
                    _dbg.mkdir(parents=True, exist_ok=True)
                    _sh.copy(_cpath, _dbg / "last_canvas.png")
                    _sh.copy(_mpath, _dbg / "last_mask.png")
                    _sh.copy(_crop, _dbg / "last_crop_mask.png")
                    (_dbg / "last_prompt.txt").write_text(
                        f"mode: {'edge' if edge_match else 'fit'}\n"
                        f"location: {location.get('name', '')} ({location.get('id', '')})\n"
                        f"edge_sides: {edge_sides}\n\n"
                        f"PROMPT:\n{full_prompt}\n\nNEGATIVE:\n{negative}\n",
                        encoding="utf-8")
                    logger.info("Map-Blend Debug (%s): %s",
                                "edge" if edge_match else "fit", _dbg)
                except Exception as _de:
                    logger.debug("Map-Blend Debug-Copy fehlgeschlagen: %s", _de)
            else:
                logger.info("Map-Fit: keine Nachbarn/Grid-Position — normaler Lauf")

        from app.core.task_queue import get_task_queue
        _tq = get_task_queue()
        if batch_track_id:
            # Batch-Modus: vorregistrierten pending Track aktivieren
            _track_id = batch_track_id
            from app.core.task_router import match_queue_name
            _queue = match_queue_name(backend.name) or "default"
            _tq.track_activate(_track_id, queue_name=_queue, provider=backend.name)
        else:
            _track_id = _tq.track_start(
                "image_gen", "Ort-Bild", agent_name=location.get("name", location_name),
                provider=backend.name)

        _gen_start = time.time()
        try:
            # Backend-Fallback-Engine: bei Fehler auf backend.fallback_mode wechseln
            def _op(b):
                return b.generate(full_prompt, negative, params)
            try:
                images, backend = await asyncio.to_thread(
                    lambda: img_skill.run_with_fallback(
                        primary_backend=backend, op=_op,
                        workflow=active_wf, character_name=""))
            except RuntimeError as _err:
                _tq.track_finish(_track_id, error=str(_err)[:200])
                raise HTTPException(status_code=500, detail=str(_err))

            # ComfyUI Cache-Hit: Backend gibt String-Sentinel zurueck. Ohne diese
            # Pruefung wuerde write_bytes(images[0]) ein einzelnes Char schreiben
            # und einen memoryview-TypeError werfen.
            if images == "NO_NEW_IMAGE":
                _tq.track_finish(_track_id, error="Duplikat")
                raise HTTPException(
                    status_code=409,
                    detail="ComfyUI hat das Bild bereits mit diesem Seed/Model erzeugt "
                           "(Cache-Hit). Erneut versuchen oder Backend neu starten.")

            if not images:
                _tq.track_finish(_track_id, error="Bildgenerierung fehlgeschlagen")
                raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

            # Map-Fit: aus dem inpainteten 3x3-Ergebnis die Mitte (das neue Tile)
            # herausschneiden + hochskalieren — ausser der Workflow macht das selbst
            # (MAP_FIT_WORKFLOW_HANDLES_CROP, z.B. mit Modell-Upscaler).
            if _fit_comp and not MAP_FIT_WORKFLOW_HANDLES_CROP:
                try:
                    import io as _io
                    from PIL import Image as _Img
                    _full = _Img.open(_io.BytesIO(images[0])).convert("RGB")
                    _w, _h = _full.size
                    _tx, _ty = _w // 3, _h // 3
                    _crop = _full.crop((_tx, _ty, _tx * 2, _ty * 2))
                    # Mitte auf Ziel-Kachelgroesse hochskalieren (Gen lief kleiner).
                    if _crop.size != (MAP_FIT_OUT_TILE, MAP_FIT_OUT_TILE):
                        _crop = _crop.resize((MAP_FIT_OUT_TILE, MAP_FIT_OUT_TILE), _Img.LANCZOS)
                    _buf = _io.BytesIO()
                    _crop.save(_buf, format="PNG")
                    images = [_buf.getvalue()]
                    logger.info("Map-Fit: Mitte %dx%d -> %dpx", _tx, _ty, MAP_FIT_OUT_TILE)
                except Exception as _ce:
                    logger.warning("Map-Fit Crop fehlgeschlagen: %s", _ce)
                finally:
                    for _tmp in (_fit_comp[0], _fit_comp[1]):
                        try:
                            os.remove(_tmp)
                        except Exception:
                            pass

            # Map-Blend: Canvas wird in DISPLAY-Orientierung gebaut (Center + Nachbarn
            # je um ihre map_rotation_2d gedreht). Das Ergebnis-Tile muss daher VOR
            # dem Speichern um genau diese Drehung ZURUECK nach Norden, sonst dreht
            # die Anzeige (map_rotation_2d) es ein zweites Mal -> doppelt verdreht.
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
            image_name = f"{int(time.time())}.png"
            image_path = gallery_dir / image_name
            image_path.write_bytes(images[0])

            # Prompt speichern fuer spaeteres Upgrade
            save_gallery_prompt(loc_id, image_name, full_prompt)

            # Neues Bild standardmaessig als Hintergrund markieren
            toggle_background_image(loc_id, image_name)

            # Raum-Zuordnung setzen wenn room_id angegeben
            if room_id:
                set_gallery_image_room(loc_id, image_name, room_id)
                # prompt_changed Flag entfernen — Bild wurde aus dem Prompt erzeugt
                from app.models.world import clear_room_prompt_changed
                clear_room_prompt_changed(loc_id, room_id)
            elif not custom_prompt:
                # Location-Level Prompt verwendet — Flag dort entfernen
                from app.models.world import clear_location_prompt_changed
                clear_location_prompt_changed(loc_id)

            # Erzeugungs-Metadaten speichern (Service + Model)
            _model_used = (getattr(backend, 'last_used_checkpoint', '')
                           or getattr(backend, 'model', '')
                           or getattr(backend, 'checkpoint', '') or '')
            set_gallery_image_meta(loc_id, image_name, {
                "backend": backend.name,
                "backend_type": backend.api_type,
                "model": _model_used,
            })

            # Bild-Typ setzen wenn prompt_type angegeben (day/night/map_2d)
            if prompt_type in ("day", "night", "map_2d"):
                set_gallery_image_type(loc_id, image_name, prompt_type)

            _tq.track_finish(_track_id)
            _gen_duration = time.time() - _gen_start
            logger.info("Bild generiert: %s (%s)/%s%s", location['name'], loc_id, image_name,
                        f" room={room_id}" if room_id else "")

            # Image-Prompt in JSONL loggen
            try:
                from app.utils.image_prompt_logger import log_image_prompt
                _model_name = (getattr(backend, 'last_used_checkpoint', '')
                               or getattr(backend, 'model', '')
                               or getattr(backend, 'checkpoint', '') or '')
                log_image_prompt(
                    agent_name=location.get("name", location_name),
                    original_prompt=prompt,
                    final_prompt=full_prompt,
                    negative_prompt=negative,
                    backend_name=backend.name,
                    backend_type=backend.api_type,
                    model=_model_name,
                    auto_enhance=False,
                    duration_s=_gen_duration,
                    loras=params.get("lora_inputs", []),
                    reference_images=params.get("reference_images", {}))
            except Exception as _log_err:
                logger.error("Image-Logging Fehler: %s", _log_err)
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


@router.delete("/locations/{location_name}/gallery/{image_name}")
async def delete_gallery_image(
    location_name: str,
    image_name: str) -> Dict[str, Any]:
    """Loescht ein Galerie-Bild (per ID oder Name)."""
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    image_path.unlink()

    # Falls das Bild als Hintergrund markiert war, Markierung entfernen
    remove_background_image(loc_id, image_name)
    remove_gallery_image_room(loc_id, image_name)
    remove_gallery_image_type(loc_id, image_name)
    # Haengende map_image/map_image_2d-Wahl auf dieses Bild aus allen Zellen loesen
    # (sonst zeigt die Zelle danach das erste statt des gewollten Tiles).
    from app.models.world import clear_map_image_references
    clear_map_image_references(image_name)

    return {"status": "success", "deleted": image_name}


@router.post("/locations/{location_name}/gallery/{image_name}/move")
async def move_gallery_image_route(
    location_name: str, image_name: str, request: Request) -> Dict[str, Any]:
    """Verschiebt ein Galerie-Bild in eine andere Location (Datei + Prompt/Typ/Meta)."""
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")
    body = await request.json()
    target = (body.get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target (Ziel-Location) fehlt")
    if not resolve_location(location_name):
        raise HTTPException(status_code=404, detail="Quell-Ort nicht gefunden")
    if not resolve_location(target):
        raise HTTPException(status_code=404, detail="Ziel-Ort nicht gefunden")
    from app.models.world import move_gallery_image
    new_name = move_gallery_image(location_name, target, image_name)
    if not new_name:
        raise HTTPException(status_code=404, detail="Bild nicht gefunden / Verschieben fehlgeschlagen")
    return {"status": "success", "image": new_name, "target": target}


@router.post("/locations/{location_name}/gallery/{image_name}/toggle-background")
async def toggle_gallery_background(
    location_name: str,
    image_name: str,
    request: Request) -> Dict[str, Any]:
    """Toggled ob ein Galerie-Bild als Hintergrund in Frage kommt."""
    body = await request.json()
    user_id = body.get("user_id", "").strip()
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    is_eligible = toggle_background_image(loc_id, image_name)

    return {"status": "success", "image": image_name, "is_background": is_eligible}


@router.post("/locations/{location_name}/gallery/{image_name}/room")
async def set_gallery_image_room_route(
    location_name: str,
    image_name: str,
    request: Request) -> Dict[str, Any]:
    """Setzt den Raum eines Galerie-Bildes."""
    body = await request.json()
    user_id = body.get("user_id", "").strip()
    room_id = body.get("room", "").strip()
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

    loc = resolve_location(location_name)
    loc_id = loc["id"] if loc and loc.get("id") else location_name

    gallery_dir = get_gallery_dir(loc_id)
    image_path = gallery_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    set_gallery_image_room(loc_id, image_name, room_id)
    return {"status": "success", "image": image_name, "room": room_id}


@router.post("/locations/{location_name}/gallery/{image_name}/type")
async def set_gallery_image_type_route(
    location_name: str,
    image_name: str,
    request: Request) -> Dict[str, Any]:
    """Setzt den Typ eines Galerie-Bildes (day/night/map oder leer)."""
    body = await request.json()
    user_id = body.get("user_id", "").strip()
    image_type = body.get("type", "").strip()
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")
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


@router.post("/locations/{location_name}/gallery/{image_name}/time-variant")
async def generate_time_variant(
    location_name: str,
    image_name: str,
    request: Request) -> Dict[str, Any]:
    """Erzeugt eine Tag- oder Nachtansicht aus einem bestehenden Bild per img2img (Referenzbild).

    Nutzt einen Qwen-kompatiblen Workflow mit dem Originalbild als Referenz.
    Body-Parameter 'target_type': 'night' (default) oder 'day'.
    """
    import time

    try:
        body = await request.json()
        user_id = body.get("user_id", "").strip()
        target_type = body.get("target_type", "night").strip()
        workflow_name = body.get("workflow", "").strip()
        backend_name = body.get("backend", "").strip()
        custom_prompt = body.get("prompt", "").strip()
        if target_type not in ("day", "night"):
            raise HTTPException(status_code=400, detail="target_type muss 'day' oder 'night' sein")
        if ".." in image_name or "/" in image_name:
            raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

        location = resolve_location(location_name)
        if not location:
            raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")

        loc_id = location.get("id", location_name)
        gallery_dir = get_gallery_dir(loc_id)
        source_path = gallery_dir / image_name
        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Quellbild nicht gefunden")

        # Prompt: custom oder automatisch aus Tag/Nacht-Prompt / Beschreibung
        prompt_field = f"image_prompt_{target_type}"
        if custom_prompt:
            prompt = custom_prompt
        else:
            # Raum-Zuordnung des Quellbilds pruefen
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
                # Innenraum: kein Himmel/Sterne, stattdessen Beleuchtung anpassen
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
                # Aussenbereich / Ort
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

        # Verfuegbarkeit pruefen — Netzwerk-Calls in einen Thread, sonst
        # blockieren sie die Event-Loop (Watchdog schlaegt an).
        await asyncio.to_thread(
            lambda: [b.check_availability()
                     for b in img_skill.backends if b.instance_enabled])

        # Backend-Auswahl: explizit > Workflow > Qwen-faehig > Auto
        backend = None
        active_wf = None
        if workflow_name:
            # Match-Konzept: Glob + Verfuegbarkeit statt exaktem Namen.
            backend, active_wf = img_skill.resolve_imagegen_target(
                workflow_name, rotation_prefix="time_variant")
        elif backend_name:
            backend = img_skill.match_backend(backend_name)  # Backend-Glob via Match-Konzept

        if not backend:
            # Qwen-Workflow bevorzugen (unterstuetzt Referenzbilder)
            for wf in img_skill.comfy_workflows:
                if "qwen" in wf.name.lower():
                    compat = wf.compatible_backends or []
                    candidates = [b for b in img_skill.backends if b.available and b.instance_enabled
                                  and b.api_type == "comfyui"
                                  and (not compat or b.name in compat)]
                    _picked = img_skill.pick_lowest_cost(
                        candidates, rotation_key=f"time_variant:{wf.name}")
                    if _picked:
                        backend = _picked
                        active_wf = wf
                        break

        # Kein Fallback auf Nicht-ComfyUI Backends — Time-Variant-Convert braucht
        # zwingend ein Backend mit Reference-Image-Support (Qwen via ComfyUI).
        # Cloud-Backends wie Together-Flux koennen kein img2img mit lokalem
        # Reference-Bild + ComfyUI-Workflow.
        if not backend:
            raise HTTPException(
                status_code=503,
                detail="Kein ComfyUI-Backend mit Referenzbild-Support verfuegbar "
                       "(z.B. Qwen-Workflow). Bitte ComfyUI-Backend starten.")

        full_prompt = prompt
        if backend.prompt_prefix:
            full_prompt = f"{backend.prompt_prefix}, {full_prompt}"

        negative = backend.negative_prompt or ""
        # Day/Night-Variants sind Hintergrund-Bilder — voll, kein Downscale.
        params = {"width": _location_image_width(), "height": _location_image_height()}

        # Workflow-Datei setzen
        if active_wf and active_wf.workflow_file:
            params["workflow_file"] = active_wf.workflow_file
        elif not workflow_name:
            _default_wf = getattr(img_skill, '_default_workflow', None)
            if _default_wf and _default_wf.workflow_file:
                active_wf = _default_wf
                params["workflow_file"] = _default_wf.workflow_file

        # Model (input_unet Workflows brauchen "unet" statt "model")
        _model_key = "unet" if (active_wf and active_wf.has_input_unet) else "model"
        if active_wf and active_wf.model:
            params[_model_key] = active_wf.model
        # Model-Verfuegbarkeit pruefen und ggf. aehnlichstes Modell finden
        _current_model = params.get(_model_key, "")
        if _current_model and backend.api_type == "comfyui" and img_skill:
            _resolved = img_skill.resolve_model_for_backend(
                _current_model, backend, active_wf.model_type if active_wf else "")
            if _resolved and _resolved != _current_model:
                logger.info("Model-Resolve: %s -> %s (Backend: %s)", _current_model, _resolved, backend.name)
                params[_model_key] = _resolved

        # CLIP — sonst scheitert ComfyUI mit value_not_in_list bei input_clip
        if active_wf and active_wf.clip:
            params["clip_name"] = active_wf.clip

        # LoRAs
        if active_wf and active_wf.has_loras and active_wf.default_loras:
            params["lora_inputs"] = active_wf.default_loras

        # Frischer Seed pro Aufruf — Time-Variant soll immer ein neues Bild
        # erzeugen, sonst cached ComfyUI bei identischem Prompt+Seed.
        if active_wf and active_wf.has_seed:
            import random as _rnd
            params["seed"] = _rnd.randint(1, 2**31 - 1)

        # Das Source-Bild ist das zu editierende Bild (primaere Edit-Referenz).
        # Qwen erwartet primary Edit-Referenzen auf image1 (Node
        # input_reference_image_1). Slot 4 ist laut Spec fuer separate
        # Location-Referenzen — hier ist das Bild selbst die Location.
        params["reference_images"] = {
            "input_reference_image_1": str(source_path),
        }
        params["string_inputs"] = {
            "input_reference_image_1_type": "location",
        }

        from app.core.task_queue import get_task_queue
        _tq = get_task_queue()
        _variant_label = "Nachtansicht" if target_type == "night" else "Tagansicht"
        _track_id = _tq.track_start(
            "image_gen", _variant_label, agent_name=location.get("name", location_name),
            provider=backend.name)

        _gen_start = time.time()
        try:
            def _op(b):
                return b.generate(full_prompt, negative, params)
            try:
                images, backend = await asyncio.to_thread(
                    lambda: img_skill.run_with_fallback(
                        primary_backend=backend, op=_op,
                        workflow=active_wf, character_name=""))
            except RuntimeError as _err:
                _tq.track_finish(_track_id, error=str(_err)[:200])
                raise HTTPException(status_code=500, detail=str(_err))

            # ComfyUI Cache-Hit: Backend gibt String-Sentinel zurueck. Ohne diese
            # Pruefung wuerde write_bytes(images[0]) ein einzelnes Char schreiben
            # und einen memoryview-TypeError werfen.
            if images == "NO_NEW_IMAGE":
                _tq.track_finish(_track_id, error="Duplikat")
                raise HTTPException(
                    status_code=409,
                    detail="ComfyUI hat das Bild bereits mit diesem Seed/Model erzeugt "
                           "(Cache-Hit). Erneut versuchen oder Backend neu starten.")

            if not images:
                _tq.track_finish(_track_id, error="Bildgenerierung fehlgeschlagen")
                raise HTTPException(status_code=500, detail="Bildgenerierung fehlgeschlagen")

            gallery_dir.mkdir(parents=True, exist_ok=True)
            new_image_name = f"{int(time.time())}.png"
            new_image_path = gallery_dir / new_image_name
            new_image_path.write_bytes(images[0])

            # Prompt speichern
            save_gallery_prompt(loc_id, new_image_name, full_prompt)

            # Als Hintergrund markieren
            toggle_background_image(loc_id, new_image_name)

            # Typ setzen (day/night)
            set_gallery_image_type(loc_id, new_image_name, target_type)

            # Raum-Zuordnung vom Quellbild uebernehmen
            image_rooms = get_gallery_image_rooms(loc_id)
            source_room = image_rooms.get(image_name, "")
            if source_room:
                set_gallery_image_room(loc_id, new_image_name, source_room)

            # Meta speichern
            _model_used = (getattr(backend, 'last_used_checkpoint', '')
                           or getattr(backend, 'model', '')
                           or getattr(backend, 'checkpoint', '') or '')
            set_gallery_image_meta(loc_id, new_image_name, {
                "backend": backend.name,
                "backend_type": backend.api_type,
                "model": _model_used,
                "source": image_name,
            })

            _tq.track_finish(_track_id)
            _gen_duration = time.time() - _gen_start
            logger.info("%s generiert: %s (%s)/%s -> %s", _variant_label, location['name'], loc_id, image_name, new_image_name)

            try:
                from app.utils.image_prompt_logger import log_image_prompt
                log_image_prompt(
                    agent_name=location.get("name", location_name),
                    original_prompt=prompt,
                    final_prompt=full_prompt,
                    negative_prompt=negative,
                    backend_name=backend.name,
                    backend_type=backend.api_type,
                    model=_model_used,
                    auto_enhance=False,
                    duration_s=_gen_duration,
                    loras=params.get("lora_inputs", []),
                    reference_images=params.get("reference_images", {}))
            except Exception as _log_err:
                logger.error("Image-Logging Fehler: %s", _log_err)

            return {"status": "success", "location_id": loc_id, "image": new_image_name, "source": image_name}
        except HTTPException:
            raise
        except Exception as e:
            _tq.track_finish(_track_id, error=str(e))
            raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Time-Variant Fehler: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/locations/{location_id}/prompt-changed")
async def set_prompt_changed_flag(
    location_id: str,
    request: Request) -> Dict[str, Any]:
    """Setzt oder entfernt das prompt_changed Flag fuer eine Location oder einen Raum.

    Body: {"user_id": "...", "room_id": "..." (optional), "value": true/false}
    Ohne room_id wird das Flag auf Location-Ebene gesetzt/entfernt.
    """
    from app.models.world import _load_world_data, _save_world_data

    try:
        body = await request.json()
        user_id = body.get("user_id", "").strip()
        room_id = body.get("room_id", "").strip()
        value = body.get("value", False)

        if not value:
            # Flag entfernen
            if room_id:
                ok = clear_room_prompt_changed(location_id, room_id)
            else:
                ok = clear_location_prompt_changed(location_id)
            if not ok:
                raise HTTPException(status_code=404, detail="Location/Raum nicht gefunden")
            return {"status": "success", "prompt_changed": False}
        else:
            # Flag setzen
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error("prompt-changed Fehler: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# === Messaging-Frame (Phone-Chat-Layout) ===

@router.get("/messaging-frame")
async def get_messaging_frame() -> Dict[str, Any]:
    """Liefert Frame-Status + bbox-Metadaten fuer Frontend-Composite.

    Returns:
        {has_frame, path, bbox, frame_size, prompt, backend, generated_at}
        oder {has_frame: False} wenn noch nicht generiert.
    """
    from app.core.messaging_frame import has_frame, load_frame_meta
    if not has_frame():
        return {"has_frame": False}
    meta = load_frame_meta() or {}
    return {
        "has_frame": True,
        "url": "/world/messaging-frame.png",
        **meta,
    }


@router.get("/messaging-frame.png")
async def get_messaging_frame_image() -> FileResponse:
    """Liefert das prozessierte Frame-Bild (PNG mit transparenter Anzeigeflaeche)."""
    from app.core.messaging_frame import get_frame_path, has_frame
    if not has_frame():
        raise HTTPException(status_code=404, detail="Frame nicht generiert")
    return FileResponse(str(get_frame_path()), media_type="image/png")


@router.post("/messaging-frame/generate")
async def post_messaging_frame_generate(request: Request) -> Dict[str, Any]:
    """Generiert das Messaging-Frame neu via image_skill.

    Body: {"prompt": "...", "backend": "Together-Fast" (optional)}

    Pipeline: image_skill.generate -> rembg (aussen) -> Chroma-Key (gruen) -> bbox.
    Laeuft synchron im Worker-Thread (kann 30-90s dauern je nach Backend).
    """
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    target = (body.get("target") or "").strip()  # "workflow:Name" oder "backend:Name"
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt fehlt")
    from app.core.messaging_frame import generate_frame
    result = await asyncio.to_thread(generate_frame, prompt, target)
    if result.get("status") != "ok":
        raise HTTPException(status_code=500, detail=result.get("error", "Generierung fehlgeschlagen"))
    return result


@router.delete("/messaging-frame")
async def delete_messaging_frame() -> Dict[str, Any]:
    """Loescht das aktuelle Frame (Frontend faellt auf CSS-Default zurueck)."""
    from app.core.messaging_frame import get_frame_path, get_frame_meta_path
    for p in (get_frame_path(), get_frame_meta_path()):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    return {"status": "deleted"}
