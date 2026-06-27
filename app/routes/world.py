"""World routes - Orte und Aktivitaeten verwalten (User-Level)"""
import asyncio
import io
import os
from fastapi import APIRouter, Request, HTTPException, Query, UploadFile, File, Depends
from fastapi.responses import FileResponse, StreamingResponse, Response
from pathlib import Path
from typing import Any, Dict, Optional
from app.core.log import get_logger
from app.core.auth_dependency import require_admin

logger = get_logger("world")

from app.models.world import (
    list_locations, add_location, delete_location,
    rename_location, resolve_location, get_location_by_id,
    get_entry_room_id,
    update_location_position,
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

@router.get("/freeze-status")
async def get_freeze_status() -> Dict[str, Any]:
    """Aktueller World-Freeze-Status (autonome Simulation eingefroren?)."""
    from app.models.world import is_world_frozen
    return {"frozen": is_world_frozen()}


@router.post("/freeze")
async def freeze_world(
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Friert die Welt ein: AgentLoop, hourly Ticks, Scheduler-Jobs und
    Telegram-Polling pausieren. TaskQueue (Bildgenerierung) + LLM-Tools bleiben
    aktiv. Persistent (ueberlebt Neustart)."""
    from app.models.world import set_world_frozen
    set_world_frozen(True)
    logger.info("World freeze AKTIVIERT (autonome Simulation angehalten)")
    return {"frozen": True}


@router.post("/unfreeze")
async def unfreeze_world(
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Taut die Welt wieder auf — autonome Simulation laeuft weiter."""
    from app.models.world import set_world_frozen
    set_world_frozen(False)
    logger.info("World freeze DEAKTIVIERT (autonome Simulation laeuft)")
    return {"frozen": False}


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
        "news": {
            # Praesentations-Stil des Player-News-Channels.
            "style": get_world_setting("news.style", "modern") or "modern",
            "title": get_world_setting("news.title", "") or "",
        },
        "choices": {
            "temperature": list(WORLD_TEMPERATURE_VALUES),
            "weather":     list(WORLD_WEATHER_VALUES),
            "news_style":  ["modern", "newspaper", "flyer"],
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
# Standard-Ausgabegroesse: das Fit/Edge-Ergebnis (Mittel-Zelle) wird IMMER auf
# diese Kantenlaenge skaliert (1024). Der 3x3-Canvas wird dagegen in der
# ORIGINAL-Aufloesung der Quell-Tiles komponiert (siehe _place_neighbors) — der
# Input wird NICHT mehr reduziert; nur die gecroppte Mitte wird am Ende auf
# MAP_FIT_OUT_TILE normiert. (Frueher wurde der ganze Canvas auf 1024 begrenzt,
# also jedes Tile auf ~341px verkleinert.)
MAP_FIT_OUT_TILE = 1024
# Sicherheits-Obergrenze pro Tile (verhindert absurd grosse Canvas/OOM bei
# untypisch hochaufloesenden Quell-Tiles). 0 = keine Grenze.
MAP_FIT_MAX_TILE = 1536
# Fit: Anteil des Nachbar-Tiles, der als Kontext-Rand um die Mitte gelegt wird.
# Kleiner = naeher an nativ und schaerfer, aber weniger Blend-Kontext. Flexibel.
# 0.1875 → bei nativem 1024-Tile bleibt die Mitte voll 1024 und der Canvas ~1408.
MAP_FIT_NEIGHBOR_FRAC = 0.1875
# Fit: Flux-vertraegliche Obergrenze fuer den GANZEN Canvas (Generierungs-
# Aufloesung). Flux ist um ~1 MP (1024px) optimal; deutlich darueber wird das
# Bild weich. Das Tile wird so gewaehlt, dass tile + 2*border <= dieser Wert
# bleibt (Mitte so gross wie moeglich, max. nativ). Auf Vielfaches von 16
# gerundet (Flux/VAE-Anforderung). 1408 = ~2 MP, passt zu frac 0.1875 mit
# voller 1024-Mitte. Nur fuer Fit — Edge nutzt weiter volle Tiles.
MAP_FIT_CANVAS_MAX = 1408
# Fit (nur Edit-Modelle wie Qwen): nur den inneren Anteil der Mitte ausschneiden.
# Edit-Modelle erfinden am Rand der regenerierten Flaeche „mehr drumherum" — der
# innere Kern ist sauber. 1.0 = ganze Mitte (wie Fill-Modelle), 0.7 = innere 70 %.
MAP_FIT_INNER_CROP = 0.7
# Die Inpaint-Workflows bekommen KEINE Crop-Maske mehr — der Workflow gibt das
# volle (inpaintete) Canvas zurueck und das BACKEND schneidet die Mitte aus und
# skaliert sie auf MAP_FIT_OUT_TILE.
# Maskenrand ueber den grauen Bereich hinaus (damit das Modell die Kanten
# einblendet) — getestet: Gray-Fill/Edit-Modelle (Qwen/Flux2) +5%, Flux-Dev-Fill
# (Fill-Modell) +2% (etwas besser).
MAP_BLEND_MASK_GROW_GRAY = 1.05
MAP_BLEND_MASK_GROW_FILL = 1.02


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


def _place_neighbors(location: Dict[str, Any], border_frac: float = 1.0,
                     canvas_max: Optional[int] = None):
    """Baut den Canvas (grau, Mitte = eigenes Tile) mit den Nachbar-Tiles ringsum.

    ``border_frac`` = Anteil des Nachbar-Tiles, der als Kontext-Rand verwendet
    wird (1.0 = ganzes Tile → klassischer 3*tile-Canvas; 0.25 = schmaler Rand).
    Pro Nachbar wird NUR der zur Mitte zeigende Streifen (orthogonal) bzw. die
    Ecke (diagonal) eingesetzt — so bleibt die Generierung naeher an der nativen
    Aufloesung und damit schaerfer.

    ``canvas_max`` (optional): Obergrenze fuer den GANZEN Canvas (tile + 2*border).
    Ist sie gesetzt, wird das Tile so gewaehlt, dass der Canvas darunter bleibt
    (Mitte so gross wie moeglich, max. nativ) und Tile/Border auf Vielfache von 16
    gerundet (Flux-/VAE-tauglich). None = altes Verhalten (Edge).

    Rueckgabe ``(canvas, tile, border, present)`` oder ``None``. ``border`` = Rand
    in px, ``present`` = Set der vorhandenen Nachbar-Richtungen (dx, dy)."""
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
    # Tiles in ORIGINAL-Aufloesung laden (kein Downscale). Einheitliche Zellgroesse
    # = groesste native Kantenlaenge (eigenes Tile + Nachbarn); kleinere werden
    # hochskaliert.
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
        # Tile so begrenzen, dass der ganze Canvas (tile + 2*border) <= canvas_max
        # bleibt → Flux-vertraegliche Generierungsaufloesung. Mitte so gross wie
        # moeglich (max. nativ). Vielfache von 16 (Flux/VAE).
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
        # Quell-Crop: nur der zur Mitte zeigende Streifen/Eck des Nachbarn.
        sx0 = (tile - border) if dx < 0 else 0
        sx1 = tile if dx < 0 else (border if dx > 0 else tile)
        sy0 = (tile - border) if dy < 0 else 0
        sy1 = tile if dy < 0 else (border if dy > 0 else tile)
        strip = im.crop((sx0, sy0, sx1, sy1))
        # Ziel-Position im Canvas (links/oben = 0, Mitte = border, rechts/unten = border+tile).
        px = 0 if dx < 0 else (border + tile if dx > 0 else border)
        py = 0 if dy < 0 else (border + tile if dy > 0 else border)
        canvas.paste(strip, (px, py))
        present.add((dx, dy))
    logger.info("Map-Fit: Canvas komponiert — Tile %dpx, Border %dpx (frac %.2f), Canvas %dpx",
                tile, border, frac, csize)
    return canvas, tile, border, present


def _finalize_blend(canvas, inpaint_mask, tile, border, present, crop_empty: bool,
                    inner_crop: float = 1.0):
    """Gemeinsamer Abschluss fuer Fit/Edge. Schneidet bei ``crop_empty`` KOMPLETT
    leere Aussen-Raender weg (auch fuer Edge am Kartenrand) und speichert:
      - Canvas (reines RGB)        -> cpath  (input_reference_image)
      - Inpaint-Maske als L        -> mpath  (input_mask)
    KEINE Crop-Maske mehr — die Mitte wird NICHT mehr im Workflow ausgeschnitten,
    sondern vom Backend aus dem zurueckgegebenen Bild. Dafuer liefern wir die
    Center-Zelle als FRAKTIONEN (x0,y0,x1,y1) des (ggf. getrimmten) Canvas, robust
    gegen die Ausgabe-Aufloesung des Workflows.

    ``inner_crop`` < 1.0 schneidet nur den inneren Anteil der Mitte aus (um den
    Mittelpunkt) — gegen den „aussen erfundenen" Ring von Edit-Modellen.

    Geometrie: Mitte (eigenes Tile) liegt bei ``border``, Canvas = tile + 2*border.
    Rueckgabe ``(cpath, mpath, tile, crop_frac)``."""
    import tempfile
    csize = tile + 2 * border
    left, top, right, bottom = 0, 0, csize, csize
    if crop_empty:
        # Aussen-Rand nur abschneiden, wenn auf der Seite KEIN Nachbar liegt
        # (orthogonal oder diagonal) — sonst blieben Ecken erhalten.
        left = 0 if any(d[0] < 0 for d in present) else border
        right = csize if any(d[0] > 0 for d in present) else csize - border
        top = 0 if any(d[1] < 0 for d in present) else border
        bottom = csize if any(d[1] > 0 for d in present) else csize - border
        if (left, top, right, bottom) != (0, 0, csize, csize):
            canvas = canvas.crop((left, top, right, bottom))
            inpaint_mask = inpaint_mask.crop((left, top, right, bottom))
            logger.info("Map-Blend: leere Raender abgeschnitten -> Canvas %dx%d",
                        right - left, bottom - top)
    # Center-Zelle (Mitte) als Fraktionen des getrimmten Canvas — optional nur der
    # innere Anteil (inner_crop) um den Mittelpunkt.
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
                             full_mask: bool = False):
    """Fit: Canvas (Nachbar-Raender, graue Mitte) + Inpaint-Maske = Mitte * mask_grow.
    ``border_frac`` steuert die Rand-Breite (kleiner = naeher an nativ, schaerfer).
    Schneidet bei ``crop_empty`` leere Aussenraender weg. Rueckgabe
    ``(cpath, mpath, tile, crop_frac)`` oder ``None``.

    ``mask_grow``: wie weit die Maske ueber die Mittel-Zelle hinausreicht
    (1.05 = +5% fuer Gray-Fill/Edit-Modelle, 1.02 = +2% fuer Flux-Dev-Fill).
    ``full_mask``: GANZE Flaeche maskieren statt nur die Mitte — noetig fuer
    Edit-Modelle (Qwen-Edit), die bei einer Teil-Maske den schmalen Nachbar-
    Streifen in die Mitte kopieren („Nachbar-Rand ins Bild gezogen")."""
    from PIL import Image, ImageDraw
    placed = _place_neighbors(location, border_frac=border_frac,
                             canvas_max=MAP_FIT_CANVAS_MAX)
    if not placed:
        return None
    canvas, tile, border, present = placed
    if full_mask:
        # Edit-Modell (Qwen): ganze Flaeche editierbar → kohaerente Regenerierung
        # statt Streifen-Kopie. Der Center-Crop (crop_frac) bleibt unveraendert.
        mask = Image.new("L", canvas.size, 255)
    else:
        mask = Image.new("L", canvas.size, 0)
        # Maske ueberlappt leicht in die Nachbarn, damit das Modell die Tile-
        # Kanten einblendet. Ausgeschnitten wird trotzdem nur die EXAKTE Mitte.
        _m = int(round(tile * (mask_grow - 1) / 2))
        ImageDraw.Draw(mask).rectangle(
            [border - _m, border - _m, border + tile - 1 + _m, border + tile - 1 + _m], fill=255)
    # Edit-Modelle (full_mask): nur den inneren Kern ausschneiden — der aussen
    # erfundene Ring faellt weg. Fill-Modelle behalten die ganze Mitte.
    _inner = MAP_FIT_INNER_CROP if full_mask else 1.0
    return _finalize_blend(canvas, mask, tile, border, present, crop_empty, inner_crop=_inner)


# Edge-Match (Kanten angleichen): Rahmen-Maskenbreite + solider Kern an der Kante.
# BLEND_FRAC = wie weit das Inpaint-Band von jeder gewaehlten Kante nach innen
# reicht (Anteil der Tile-Breite). Niedrig halten — bei MEHREREN Kanten ueber-
# lappen die Baender, ein zu breites Band (0.45) frisst bei 2 Nachbarn ~70% der
# Tile (alles grau). 0.22 -> schmales Kanten-Frame, Mitte bleibt erhalten.
MAP_EDGE_BLEND_FRAC = 0.22
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


def _compose_edge_canvas(location: Dict[str, Any], sides=None, gray_fill: bool = False):
    """Wie :func:`_compose_neighbor_canvas` (3x3, echte Nachbarn rundum), ABER die
    Mitte ist das ECHTE Tile und die Maske ist ein RAHMEN (Distanz-Transform) nur
    fuer die gewaehlten Seiten mit Nachbar: an der Kante solide, gleichmaessig zur
    Mitte hin auf 0. Rueckgabe (canvas_path, mask_path, tile) oder None."""
    import numpy as np
    from PIL import Image
    avail = _neighbor_sides(location)
    use = [s for s in (sides or list(avail)) if s in avail]
    # Edge nutzt volle Nachbar-Tiles (border_frac=1.0 → border == tile, klassischer
    # 3*tile-Canvas) — die Rahmen-Maske braucht den vollen Nachbar-Kontext.
    placed = _place_neighbors(location, border_frac=1.0)
    if not placed or not use:
        return None
    canvas, tile, border, present = placed
    # Mitte mit dem echten Tile fuellen (statt grau).
    tp = _resolve_map_icon_path(location)
    if tp:
        t_img = Image.open(tp).convert("RGB").resize((tile, tile))
        rot = int(location.get("map_rotation_2d") or 0)
        if rot:
            t_img = t_img.rotate(-rot, expand=False, fillcolor=(128, 128, 128))
        canvas.paste(t_img, (border, border))
    # Rahmen-Maske via Distanz-Transform.
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
    # NUR fuer Edit-Modell-Inpaint (gray_fill, z.B. Qwen-Edit): die maskierte Kante
    # SOLIDE grau einfaerben (gleiches (128,128,128) wie die leere Fit-Mitte), denn
    # Qwen "ergaenzt die grauen Flaechen" und liest sie direkt aus dem Referenzbild.
    # Solides Grau mit HARTER Kante (binaere Maske >0, NICHT die fadende Inpaint-
    # Maske — kein Verlauf). Fill-Modelle (Flux DevFill) bekommen KEIN Grau: sie
    # nutzen die separate input_mask und behalten den echten Tile-Inhalt.
    if gray_fill:
        _gray = Image.new("RGB", canvas.size, (128, 128, 128))
        _solid = mask.point(lambda v: 255 if v > 0 else 0)
        canvas = Image.composite(_gray, canvas.convert("RGB"), _solid)
    # Auch Edge schneidet leere Kanten weg (z.B. am Kartenrand).
    return _finalize_blend(canvas, mask, tile, border, present, crop_empty=True)


# Edge-Match (neues Modell): GENAU zwei benachbarte Tiles nebeneinander, die Naht
# hart grau gefuellt; Maske = grauer Streifen + 5%. Der Workflow gibt EIN Bild
# (gleiche Groesse) zurueck, das Backend zerschneidet es mittig und legt beide
# Haelften in den jeweiligen Locations ab. KEIN Fill-Modell mehr.
def _compose_edge_pair(location: Dict[str, Any], side: str):
    """Baut den 2-Tile-Canvas (location + Nachbar in ``side``) in Display-
    Orientierung, fuellt die Naht hart grau und erzeugt die Inpaint-Maske
    (grauer Streifen + 5%). Rueckgabe ``(cpath, mpath, info)`` oder None.

    ``info`` = dict(axis='x'|'y', a_first(bool), a_loc, b_loc, a_rot, b_rot, tile):
      - axis: Naht-Achse (x = vertikale Naht, Tiles links/rechts; y = horizontale).
      - a_first: ist ``location`` die erste Haelfte (links bzw. oben)?
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

    horizontal = side in ("east", "west")  # Tiles links/rechts -> vertikale Naht
    if horizontal:
        canvas = Image.new("RGB", (tile * 2, tile), (128, 128, 128))
        a_first = (side == "east")           # east: Nachbar rechts -> A links
        canvas.paste(a_img, (0, 0) if a_first else (tile, 0))
        canvas.paste(b_img, (tile, 0) if a_first else (0, 0))
        axis, W_, H_, seam = "x", tile * 2, tile, tile
    else:
        canvas = Image.new("RGB", (tile, tile * 2), (128, 128, 128))
        a_first = (side == "south")          # south: Nachbar unten -> A oben
        canvas.paste(a_img, (0, 0) if a_first else (0, tile))
        canvas.paste(b_img, (0, tile) if a_first else (0, 0))
        axis, W_, H_, seam = "y", tile, tile * 2, tile

    blend = max(1, int(tile * MAP_EDGE_BLEND_FRAC))
    coord = np.mgrid[0:H_, 0:W_][1 if axis == "x" else 0]
    dist = np.abs(coord - seam)
    # Naht hart grau fuellen (grauer Streifen ±blend).
    gray_band = dist < blend
    arr = np.array(canvas)
    arr[gray_band] = (128, 128, 128)
    canvas = Image.fromarray(arr, "RGB")
    # Maske = Streifen + 5% (hart).
    mask_w = blend * MAP_BLEND_MASK_GROW_GRAY
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
        for _p in comp[:2]:  # cpath, mpath (Pfade; comp[3] ist die Crop-Fraktion)
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


@router.post("/locations/{location_name}/background/upload")
async def upload_location_background(location_name: str, request: Request) -> Dict[str, Any]:
    """Lädt ein Hintergrundbild für einen Ort (optional Raum) hoch.

    Multipart: file (Bild) + optional room_id. Speichert in die Galerie des
    Orts, registriert es als Background und mappt es ggf. auf den Raum —
    derselbe Speicher-/Registrierpfad wie die Generierung.
    """
    from app.models.world import (get_gallery_dir, toggle_background_image,
                                   set_gallery_image_room)
    from app.core.timeutils import utc_now
    from pathlib import Path as _Path

    form = await request.form()
    file = form.get("file")
    room_id = (form.get("room_id") or "").strip() if isinstance(form.get("room_id"), str) else ""
    if not file:
        raise HTTPException(status_code=400, detail="file fehlt")

    location = resolve_location(location_name)
    if not location:
        raise HTTPException(status_code=404, detail=f"Ort '{location_name}' nicht gefunden")
    loc_id = location.get("id") or location_name

    fname = (getattr(file, "filename", "") or "").lower()
    ext = _Path(fname).suffix or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail="Format nicht unterstützt")

    gallery_dir = get_gallery_dir(loc_id)
    gallery_dir.mkdir(parents=True, exist_ok=True)
    image_name = f"{loc_id}_{utc_now().strftime('%Y%m%d%H%M%S')}{ext}"
    (gallery_dir / image_name).write_bytes(await file.read())

    toggle_background_image(loc_id, image_name)
    if room_id:
        try:
            set_gallery_image_room(location_name, image_name, room_id)
        except Exception as e:
            logger.debug("set_gallery_image_room beim Upload fehlgeschlagen: %s", e)
    return {"status": "success", "image": image_name, "room_id": room_id}


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

        # Bild generieren (blockierend in Thread) — Style/Negative aus Use-Case.
        from app.core import config as _cfg
        _ucp = _cfg.resolve_use_case_style(
            "location", "", "", getattr(backend, "model", "") or "", getattr(backend, "image_family", ""))
        full_prompt = f"{_ucp['prompt_style']}, {prompt}" if _ucp.get("prompt_style") else prompt
        negative = _ucp.get("prompt_negative", "")
        # Location-Background: volle Aufloesung — wird als Hintergrund-Szenenbild
        # genutzt, kein Downscale.
        params = {"width": _location_image_width(), "height": _location_image_height()}
        # Default-Workflow und Model ermitteln
        active_wf = getattr(img_skill, '_default_workflow', None)
        if active_wf and active_wf.workflow_file:
            params["workflow_file"] = active_wf.workflow_file
        # Model setzen (input_unet vs input_model)
        if active_wf and active_wf.model:
            _model_key = "unet" if (active_wf.has_input_unet or active_wf.has_input_safetensors) else "model"
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
        if active_wf and getattr(active_wf, "clip_type", ""):
            params["clip_type"] = active_wf.clip_type
        if active_wf and getattr(active_wf, "vae", ""):
            params["vae_name"] = active_wf.vae

        # Frischer Seed pro Aufruf gegen ComfyUI Cache-Hit
        # (Memory feedback_no_new_image_sentinel).
        if active_wf and active_wf.has_seed:
            import random as _rnd
            params["seed"] = _rnd.randint(1, 2**31 - 1)

        # Backend-Fallback-Engine: probiert primary, faellt bei Fehler auf
        # backend.fallback_mode (none/next_cheaper/specific) zurueck. Lokale
        # Backends ueber die GPU-Provider-Queue → nie zwei parallel pro Backend.
        def _op(b):
            if getattr(b, "api_type", "") in ("comfyui", "a1111"):
                from app.core.llm_queue import get_llm_queue, Priority as _P
                return get_llm_queue().submit_gpu_task(
                    provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                    callable_fn=lambda: b.generate(full_prompt, negative, params),
                    agent_name=location.get("name", location_name), gpu_type="comfyui")
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
    # ComfyUI-Workflows — nur die, deren kompatible ComfyUI-Backends auch
    # erreichbar sind. Ohne verfuegbares ComfyUI-Backend koennen sie nicht laufen
    # und gehoeren nicht in den Image-Gen-Dialog (sonst waehlt man ein totes Ziel).
    for wf in imagegen.get_comfy_workflows(only_available=True):
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
            # Zweck-Kategorie (z.B. "inpaint") — steuert, welche Workflows in
            # Spezial-Dialogen (Fit/Edge) angeboten werden.
            "category": wf.get("category", ""),
            # Style-Familie (natural/keywords) — Fallback fuer den mapfit-Default-
            # Prompt, falls der Workflow keinen eigenen prompt hat.
            "image_family": wf.get("image_family", ""),
            # Per-Workflow Default-Prompt fuer den Fit/Edge-Dialog (leer = Fallback).
            "prompt": wf.get("prompt", ""),
            # Edit-Modell-Inpaint (Qwen): kein dynamischer Terrain-Hint anhaengen
            # (das Modell sieht die Umgebung im grauen Canvas selbst).
            "inpaint_gray": wf.get("inpaint_gray", False),
            # Kompatible ComfyUI-Instanzen (leer = alle) — fuer die „gepinnter
            # Endpoint"-Eintraege im Dialog.
            "compatible_backends": wf.get("compatible_backends", []),
        })
    # Nicht-ComfyUI Backends (CivitAI, Together, …). Symmetrisch zu den Workflows
    # oben: angeboten wird jedes AKTIVIERTE Backend — die Verfuegbarkeit loest der
    # Server beim Generieren via match_backend (Match) auf. NICHT auf b.available
    # vorfiltern, sonst verschwindet ein frisch konfiguriertes/noch nicht
    # geprobtes Cloud-Backend aus der "Service (match)"-Auswahl.
    for b in imagegen.backends:
        if b.api_type == "comfyui":
            continue
        if not b.instance_enabled:
            continue
        opt = {
            "type": "backend",
            "name": b.name,
            "label": b.name if b.available else f"{b.name} (offline?)",
            "available": b.available,
        }
        # Backend mit Modellliste (z.B. Together.ai) — direkt als Auswahl anbieten
        backend_models = getattr(b, 'available_models', [])
        if backend_models:
            opt["models"] = backend_models
            opt["default_model"] = getattr(b, 'model', backend_models[0])
        # LoRAs aus der per-Welt LoRA-Library, gefiltert nach DIESEM Backend (endpoint),
        # damit der Image-Gen-Dialog passende LoRA-Felder zeigt. Beide Cloud-Library-
        # Backends: localai uebertraegt als <lora:>-Prompt-Syntax, openai_diffusion
        # (Gateway) dynamisch als lora_NN/strength_NN-Params.
        if b.api_type in ("localai", "openai_diffusion"):
            from app.core.config import get_lora_library_names
            opt["has_loras"] = True
            opt["lora_options"] = get_lora_library_names(b.name)
        options.append(opt)
    # Konkrete ComfyUI-Instanzen (fuer „gepinnter Endpoint"-Eintraege im Dialog).
    comfy_backends = [
        {"name": b.name, "available": bool(getattr(b, "available", False))}
        for b in imagegen.backends
        if b.api_type == "comfyui" and b.instance_enabled
    ]
    # mapfit-Default-Prompts pro Familie — der Fit/Edge-Dialog belegt damit das
    # Prompt-Feld vor (statt des frueheren Terrain-/Edge-Hints).
    from app.core import config as _cfg
    mapfit_prompts = {}
    for _fam in ("natural", "keywords"):
        try:
            _r = _cfg.resolve_use_case_style("mapfit", _fam, "", "", "")
            mapfit_prompts[_fam] = _r.get("prompt_style", "")
        except Exception:
            mapfit_prompts[_fam] = ""
    # Default-Vorauswahl fuer Location aus .env
    loc_default = os.environ.get("LOCATION_IMAGEGEN_DEFAULT", "").strip()
    result = {"options": options, "comfy_backends": comfy_backends,
              "mapfit_prompts": mapfit_prompts}
    # Fit/Match-edges: imagegen-Target (Match-Spec, read-only im Fit-Dialog).
    result["mapfit_imagegen_default"] = (os.environ.get("MAPFIT_IMAGEGEN_DEFAULT") or "workflow:Flux Inpaint*").strip()
    # Globaler Outfit-Default (Match-Spec, z.B. "backend:LocalAI-Flux") — die
    # Character-Render-Match-UI zeigt ihn an, wenn kein Override gesetzt ist.
    result["outfit_imagegen_default"] = (os.environ.get("OUTFIT_IMAGEGEN_DEFAULT") or "").strip()
    if loc_default:
        result["default_location"] = loc_default
    return result


@router.post("/imagegen-enhance-prompt")
async def imagegen_enhance_prompt(request: Request) -> Dict[str, Any]:
    """Schreibt einen Image-Prompt per LLM um — generisch (ohne Character-Bindung).

    Body: { prompt, improvement_request }
    Returns: { prompt: "<umgeschriebener Prompt>" }

    Gleiche enhance_prompt-Funktion wie beim Character-/Instagram-Regenerate,
    damit der Dialog-Button „Improve" ueberall denselben Mechanismus nutzt.
    """
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    improvement_request = (body.get("improvement_request") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt fehlt")
    if not improvement_request:
        raise HTTPException(status_code=400, detail="improvement_request fehlt")
    from app.skills.image_regenerate import enhance_prompt
    enhanced = await asyncio.to_thread(enhance_prompt, prompt, improvement_request, None)
    return {"prompt": enhanced}


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

            # Subject only — Framing/Style kommen aus dem Use-Case (map/location).
            prompt = description

        # Map-/Location-Style kommt jetzt aus dem Use-Case (unten via
        # resolve_use_case_style angewandt) — kein separater Suffix mehr.
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
        if _map_blend:
            # Fit UND Kanten-Angleich nutzen das normale ComfyUI-Workflow-Matching.
            # Der im Dialog gewaehlte Inpaint-Workflow (data["workflow"], category=
            # "inpaint") hat Vorrang; ohne Auswahl Fallback auf MAPFIT_IMAGEGEN_DEFAULT.
            # Der Workflow muss die Inpaint-Nodes haben (input_reference_image=Canvas,
            # input_mask, input_crop, output_final).
            _fit_spec = ((data.get("workflow") or "").strip()
                         or (os.environ.get("MAPFIT_IMAGEGEN_DEFAULT") or "workflow:Flux Inpaint*").strip())
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
            # Wird zusaetzlich ein explizites Backend gewaehlt (gepinnter Endpoint),
            # bleibt der Workflow-Match, aber diese Instanz wird erzwungen.
            backend, active_wf = img_skill.resolve_imagegen_target(
                workflow_name, rotation_prefix="world_image",
                preferred_backend=backend_name)
            if active_wf and not backend:
                _pin = f" auf Endpoint '{backend_name}'" if backend_name else ""
                raise HTTPException(
                    status_code=503,
                    detail=f"Kein ComfyUI-Backend fuer Workflow '{active_wf.name}'{_pin} verfuegbar")
            if not active_wf:
                logger.warning(
                    "Workflow '%s' nicht gefunden, verfuegbar: [%s]",
                    workflow_name, ", ".join(w.name for w in img_skill.comfy_workflows))
            else:
                logger.info("Workflow (match): %s -> %s -> Backend: %s",
                            workflow_name, active_wf.name, backend.name if backend else "-")
        elif backend_name:
            # Backend-Glob via Match-Konzept. _wait_for_explicit_backend probt die
            # passenden Backends FRISCH (statt auf stale b.available zu vertrauen) —
            # noetig fuer frisch konfigurierte Cloud-Backends (CivitAI/Together).
            backend = (img_skill._wait_for_explicit_backend(backend_name)
                       or img_skill.match_backend(backend_name))
            logger.debug("Explizites Backend: %s -> %s", backend_name, backend.name if backend else 'nicht verfuegbar')
            # Explizite Wahl + nicht verfuegbar -> KLARER Fehler statt stillem
            # ComfyUI-Fallback (sonst denkt der User, CivitAI sei genutzt worden).
            if not backend:
                raise HTTPException(
                    status_code=503,
                    detail=f"Gewaehltes Backend '{backend_name}' ist nicht verfuegbar "
                           f"(z.B. ungueltiger API-Key / offline). Kein automatischer Fallback.")

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

        # Regenerate (Selbst-Referenz): der Prompt ist eine woertliche Anpass-
        # Anweisung fuer den Referenz-Workflow (z.B. "road turns right") — KEIN
        # Use-Case-Praefix, KEIN Use-Case-Negative, keine sonstige Manipulation.
        _is_regen = bool(data.get("use_source_as_reference"))
        # Optionaler "Was willst Du aendern"-Wunsch: dieselbe LLM-Funktion wie
        # beim Character-/Instagram-Regenerate baut daraus den finalen Prompt.
        # Leer gelassen -> Prompt bleibt woertlich.
        _improve = (data.get("improvement_request") or "").strip()
        if _is_regen and _improve:
            from app.skills.image_regenerate import enhance_prompt
            prompt = await asyncio.to_thread(enhance_prompt, prompt, _improve, None)
            logger.info("Regenerate-Prompt via enhance_prompt umgeschrieben: %s", prompt[:120])
        # Use-Case-Style/Negative: Map-Blend (Inpaint) -> "mapfit" (graue Flaechen
        # nahtlos ergaenzen, kein „neues Tile"-Stil), normales Tile -> "map",
        # sonst Location-Background.
        from app.core import config as _cfg
        _uc_name = "mapfit" if _map_blend else ("map" if prompt_type == "map_2d" else "location")
        _ucp = _cfg.resolve_use_case_style(
            _uc_name,
            getattr(active_wf, "image_family", "") if active_wf else "",
            getattr(active_wf, "workflow_file", "") if active_wf else "",
            getattr(backend, "model", "") or "", getattr(backend, "image_family", ""))
        if _is_regen:
            full_prompt = prompt
            negative = ""
        elif _map_blend and custom_prompt:
            # Fit/Edge-Dialog liefert den (mapfit-)Prompt bereits fertig editiert —
            # woertlich uebernehmen, KEIN Stil-Praefix doppeln. Negative bleibt aus
            # dem mapfit-Use-Case. Ohne Dialog-Prompt (Batch) faellt es unten auf
            # Stil+Auto-Hint zurueck.
            full_prompt = prompt
            negative = _ucp.get("prompt_negative", "")
        else:
            full_prompt = f"{_ucp['prompt_style']}, {prompt}" if _ucp.get("prompt_style") else prompt
            negative = _ucp.get("prompt_negative", "")
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
        # Workflow-File + Model/CLIP/LoRA — config-getrieben, fuer Map-Blend
        # (Inpaint) GENAUSO wie fuer normale Generierung. Map-Blend hat active_wf
        # schon via MAPFIT_IMAGEGEN_DEFAULT aufgeloest; sonst ohne expliziten
        # Workflow den Default-Workflow nehmen. Ist ein Config-Wert leer (z.B. ein
        # bewusst leeres NSFW-Model), bleibt der im Workflow-File gebackene Wert.
        if not _map_blend and not workflow_name:
            active_wf = getattr(img_skill, '_default_workflow', None)
        if active_wf and active_wf.workflow_file:
            params["workflow_file"] = active_wf.workflow_file
        # Model-Override (input_unet/safetensors Workflows brauchen "unet" statt "model")
        _model_key = "unet" if (active_wf and (active_wf.has_input_unet or active_wf.has_input_safetensors)) else "model"
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
        # CLIP (clip_name1 + clip_name2 fuer DualCLIPLoader, z.B. Flux Inpaint)
        if active_wf and active_wf.clip:
            params["clip_name"] = active_wf.clip
        if active_wf and active_wf.clip2:
            params["clip_name2"] = active_wf.clip2
        if active_wf and getattr(active_wf, "clip_type", ""):
            params["clip_type"] = active_wf.clip_type
        if active_wf and getattr(active_wf, "vae", ""):
            params["vae_name"] = active_wf.vae
        # LoRA-Inputs
        if active_wf and active_wf.has_loras:
            if loras_override is not None:
                params["lora_inputs"] = loras_override
            elif active_wf.default_loras:
                params["lora_inputs"] = active_wf.default_loras

        # Frischer Seed pro Aufruf — sonst gibt ComfyUI bei identischem Prompt+Seed
        # den NO_NEW_IMAGE-Sentinel (Memory feedback_no_new_image_sentinel). Bei
        # Map-Blend IMMER neu, sonst wenn der Workflow einen input_seed-Node hat.
        if _map_blend or (active_wf and active_wf.has_seed):
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
        _edge_pair = None
        _cpath = _mpath = None
        if edge_match:
            # Neues Edge-Modell: GENAU zwei benachbarte Tiles, EINE Kante. Naht hart
            # grau, Maske = Streifen +5%. Der Workflow gibt EIN Bild zurueck — das
            # Backend zerschneidet es mittig und legt beide Haelften in den jeweiligen
            # Locations ab. KEIN Fill-Modell (nur Gray-Fill-Workflows).
            _side = (edge_sides[0] if isinstance(edge_sides, (list, tuple)) and edge_sides
                     else (edge_sides if isinstance(edge_sides, str) else ""))
            _ep = _compose_edge_pair(location, _side)
            if _ep:
                _cpath, _mpath, _edge_pair = _ep
                params["image_use_case"] = "mapfit"  # 400-Cap umgehen: voller Output zum Zerschneiden
        elif fit_neighbors:
            # Maskenrand pro Modell: Gray-Fill/Edit (Qwen/Flux2) +5%, Flux-Dev-Fill +2%.
            _is_gray = bool(active_wf and getattr(active_wf, "inpaint_gray", False))
            _grow = MAP_BLEND_MASK_GROW_GRAY if _is_gray else MAP_BLEND_MASK_GROW_FILL
            # Edit-Modelle (inpaint_gray, z.B. Qwen-Edit) brauchen eine VOLLE Maske,
            # sonst kopieren sie den schmalen Nachbar-Streifen in die Mitte.
            _fit_comp = _compose_neighbor_canvas(location, crop_empty=True, mask_grow=_grow,
                                                 full_mask=_is_gray)
            if _fit_comp:
                _cpath, _mpath, _ctile, _cfrac = _fit_comp
                # 400-Cap umgehen: das Backend soll den VOLLEN Canvas zurueckgeben,
                # damit die Mitte in voller Aufloesung herausgeschnitten wird. Ohne
                # das wird der Output vorab auf 400px (Map-Cap) verkleinert → der
                # Center-Crop liefert nur ~290px hochskaliert (unscharf).
                params["image_use_case"] = "mapfit"
        if _cpath and _mpath:
            # Canvas (reines RGB) -> input_reference_image, Inpaint-Maske -> input_mask.
            # Beides in Original-Aufloesung; dem Workflow die echten Canvas-Maße geben.
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
                # md5 mitloggen → 1:1-Abgleich mit der "Ref-Inject"-Logzeile des
                # Backends: so ist belegt, dass die mapblend_debug-Dateien exakt
                # die sind, die an ComfyUI gehen.
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
            # Ueber die GPU-Provider-Queue generieren — serialisiert pro Backend
            # (nie zwei parallel) und aktiviert den Track erst, wenn der Kanal die
            # Arbeit aufnimmt; wartende World-Gens bleiben so korrekt "pending".
            # Kontext fuers ZENTRALE Logging in backend.generate() (final_prompt,
            # Backend, Model, LoRAs, Refs, Dauer setzt generate() selbst).
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
                if getattr(b, "api_type", "") in ("comfyui", "a1111"):
                    from app.core.llm_queue import get_llm_queue, Priority as _P
                    return get_llm_queue().submit_gpu_task(
                        provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                        callable_fn=_gen, agent_name=location.get("name", location_name),
                        gpu_type="comfyui")
                return _gen()
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

            # Edge-Pair (neues Modell): das zurueckgegebene EINE Bild mittig
            # zerschneiden, jede Haelfte um ihre eigene Rotation nach Norden
            # zurueckdrehen, auf Map-Thumbnail (400) bringen und in der jeweiligen
            # Location als neues map_2d-Tile ablegen. Dann sofort fertig.
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
                        _hl = _hl.rotate(_rot2, expand=False)  # zurueck nach Norden
                    _bb = _io2.BytesIO(); _hl.save(_bb, format="PNG")
                    _png = downscale_bytes(_bb.getvalue(), "map")  # Map-Thumbnail (400)
                    _lid2 = _loc2.get("id", "")
                    _gd2 = get_gallery_dir(_lid2); _gd2.mkdir(parents=True, exist_ok=True)
                    _nm2 = f"{int(time.time())}_{_lid2[:6]}.png"
                    (_gd2 / _nm2).write_bytes(_png)
                    save_gallery_prompt(_lid2, _nm2, full_prompt)
                    set_gallery_image_type(_lid2, _nm2, "map_2d")
                    set_gallery_image_meta(_lid2, _nm2, {
                        "backend": backend.name, "backend_type": backend.api_type,
                        "model": (getattr(backend, 'model', '') or ''), "loras": []})
                    set_location_map_image(_lid2, "map_image_2d", _nm2)  # neues Tile anzeigen
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

            # Map-Fit/Edge: das Backend schneidet die Mitte (das neue Tile) aus dem
            # zurueckgegebenen vollen Canvas heraus (per Fraktions-Box, robust gegen
            # die Ausgabe-Aufloesung) und skaliert sie auf MAP_FIT_OUT_TILE. Der
            # Workflow bekommt KEINE Crop-Maske mehr.
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
            # Replace (Haken "neues Bild" aus): das Quellbild in-place ueber-
            # schreiben — behaelt Dateiname und damit Raum-/Typ-/Map-Zuordnung
            # und das Hintergrund-Flag. Sonst neues Bild mit Timestamp.
            _replace_src = (data.get("reference_image") or "").strip() if data.get("replace_source") else ""
            _is_replace = bool(
                _replace_src and "/" not in _replace_src and ".." not in _replace_src
                and (gallery_dir / _replace_src).exists())
            image_name = _replace_src if _is_replace else f"{int(time.time())}.png"
            image_path = gallery_dir / image_name
            image_path.write_bytes(images[0])

            # Prompt speichern fuer spaeteres Upgrade
            save_gallery_prompt(loc_id, image_name, full_prompt)

            # Neues Bild standardmaessig als Hintergrund markieren — beim In-Place-
            # Replace NICHT togglen (sonst kippt ein bereits gesetztes Flag um).
            if not _is_replace:
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

            # Erzeugungs-Metadaten speichern (Service + Model + LoRAs)
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

            # Bild-Typ setzen wenn prompt_type angegeben (day/night/map_2d)
            if prompt_type in ("day", "night", "map_2d"):
                set_gallery_image_type(loc_id, image_name, prompt_type)
            # Neu erzeugtes Map-Tile sofort als angezeigtes Karten-Item setzen
            # (Fit/Nachbar + normale map_2d-Gen) — sonst bliebe das alte Tile aktiv.
            if prompt_type == "map_2d":
                from app.models.world import set_location_map_image
                set_location_map_image(loc_id, "map_image_2d", image_name)

            _tq.track_finish(_track_id)
            _gen_duration = time.time() - _gen_start
            logger.info("Bild generiert: %s (%s)/%s%s", location['name'], loc_id, image_name,
                        f" room={room_id}" if room_id else "")

            # Image-Prompt-Logging passiert jetzt ZENTRAL in backend.generate()
            # (mit dem finalen, trigger-injizierten Prompt) — via log_meta unten.
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
            # Edit-Workflow mit Referenzbild-Slot bevorzugen (Qwen). KEINE
            # Inpaint-Workflows: die brauchen input_mask/input_crop, die der
            # Tag/Nacht-Convert nicht liefert → ComfyUI ResizeImageMaskNode wirft
            # "required_input_missing".
            for wf in img_skill.comfy_workflows:
                if ("qwen" in wf.name.lower()
                        and (wf.category or "") != "inpaint"
                        and (wf.ref_slot_count or 0) >= 1):
                    compat = wf.compatible_backends or []
                    # skill/compat LEER = deaktiviert -> kein Backend zugeordnet.
                    candidates = [b for b in img_skill.backends if b.available and b.instance_enabled
                                  and b.api_type == "comfyui"
                                  and b.name in compat]
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

        # Time-Variant braucht einen Edit-Workflow mit Referenzbild-Slot
        # (input_reference_image_1). Ein Inpaint-Workflow (input_mask/input_crop)
        # passt NICHT — sonst scheitert ComfyUI an fehlenden Masken-Inputs.
        if active_wf and ((active_wf.category or "") == "inpaint"
                          or (active_wf.ref_slot_count or 0) < 1):
            raise HTTPException(
                status_code=400,
                detail=(f"Workflow '{active_wf.name}' ist fuer Tag/Nacht-Varianten "
                        "ungeeignet (Inpaint bzw. ohne Referenzbild-Slot). Bitte einen "
                        "Qwen-Edit-Workflow mit input_reference_image_1 waehlen."))

        from app.core import config as _cfg
        _ucp = _cfg.resolve_use_case_style(
            "location",
            getattr(active_wf, "image_family", "") if active_wf else "",
            getattr(active_wf, "workflow_file", "") if active_wf else "",
            getattr(backend, "model", "") or "", getattr(backend, "image_family", ""))
        full_prompt = f"{_ucp['prompt_style']}, {prompt}" if _ucp.get("prompt_style") else prompt
        negative = _ucp.get("prompt_negative", "")
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
        _model_key = "unet" if (active_wf and (active_wf.has_input_unet or active_wf.has_input_safetensors)) else "model"
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
        if active_wf and getattr(active_wf, "clip_type", ""):
            params["clip_type"] = active_wf.clip_type
        if active_wf and getattr(active_wf, "vae", ""):
            params["vae_name"] = active_wf.vae

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
            provider=backend.name, start_running=False)

        _gen_start = time.time()
        try:
            # GPU-Provider-Queue: serialisiert pro Backend + Track erst aktiv,
            # wenn der Kanal die Arbeit aufnimmt (wartende stehen "pending").
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
                if getattr(b, "api_type", "") in ("comfyui", "a1111"):
                    from app.core.llm_queue import get_llm_queue, Priority as _P
                    return get_llm_queue().submit_gpu_task(
                        provider_name=b.name, task_type="image_gen", priority=_P.IMAGE_GEN,
                        callable_fn=_gen, agent_name=location.get("name", location_name),
                        gpu_type="comfyui")
                return _gen()
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

            # Image-Prompt-Logging passiert jetzt ZENTRAL in backend.generate()
            # (final, trigger-injiziert) — via log_meta beim generate-Aufruf.
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
