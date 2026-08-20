"""World routes - Orte und Aktivitaeten verwalten (User-Level)"""
import asyncio
import io
import os
from fastapi import (APIRouter, Request, HTTPException, Query, UploadFile,
                     File, Form, Depends)
from fastapi.responses import FileResponse, StreamingResponse
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
from app.core import world_ops

router = APIRouter(prefix="/world", tags=["world"])


# Avatar movement lives at POST /play/travel (app/routes/play.py): the world
# is a metre plane since E1, so the avatar walks a timed journey to a NAMED
# place instead of stepping from grid cell to grid cell. The two compass
# routes that used to sit here are gone without replacement.


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
    return world_ops.build_locations_payload(character_name)


@router.post("/locations")
async def create_location_route(request: Request) -> Dict[str, Any]:
    """Erstellt oder aktualisiert einen Ort."""
    try:
        data = await request.json()
        return world_ops.create_location_with_extras(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/locations/seed-boundaries")
def seed_boundaries_route() -> Dict[str, Any]:
    """Draw the missing location boundaries — one explicit repair gesture.

    Every PLACED location without a drawn ``map3d.boundary`` but with a
    legacy ``plan_width_m`` gets that centred square written as its real,
    editable outline (contract v6; the transition synthesis that used to hand
    such a location a square on the fly ended 2026-08-19, so without this it
    has no area at all). Locations that already carry an outline are never
    touched, and one without a width has nothing to seed FROM — it is
    reported in ``skipped`` instead.

    Answers ``{"seeded": [id, …], "skipped": [id, …]}``.
    """
    try:
        return world_ops.seed_missing_boundaries()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/locations/{location_id}")
async def update_location_route(location_id: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert einen Ort (Umbenennung per ID)."""
    try:
        data = await request.json()
        return world_ops.update_location_with_extras(location_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/locations/{template_id}/clone")
async def clone_location_route(template_id: str, request: Request) -> Dict[str, Any]:
    """Create a clone instance of a (passable) template at a metre position.

    Called by the worldmap drag&drop when the user pulls a passable template
    out of the tray onto the map.
    """
    try:
        data = await request.json()
        pos_x = data.get("pos_x")
        pos_z = data.get("pos_z")
        if pos_x is None or pos_z is None:
            raise HTTPException(status_code=400,
                detail="pos_x/pos_z missing")
        try:
            pos_x = float(pos_x)
            pos_z = float(pos_z)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400,
                detail="pos_x/pos_z must be numbers")
        from app.models.world import clone_location as _clone
        clone = _clone(template_id, pos_x, pos_z)
        if not clone:
            raise HTTPException(status_code=404,
                detail="Template not found")
        return {"status": "success", "location": clone}
    except HTTPException:
        raise
    except ValueError as e:
        # Rejected position (NaN/Infinity — json.loads accepts both literals).
        # Nothing was written; a bad body is the client's fault, not a 500.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- World-Level Settings (Schritt 7, May 2026) ---------------------------
# Temperature/weather settings live in world_kv. Own endpoint so the setup tab
# can render a compact form without going through the generic admin-config
# machinery.

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


@router.get("/game-time")
async def get_game_time(lang: str = Query("en")) -> Dict[str, Any]:
    """Game clock info: system now, the world instant fully rendered, anchors,
    factor, freeze and the world CALENDAR.

    The clients tick locally from `game.total_seconds` + `factor` and derive
    their display with the `calendar` block — they never parse a date."""
    from app.core.timeutils import get_game_clock_info
    return get_game_clock_info(lang or "en")


def _game_time_from_body(raw: Any) -> Any:
    """Read the `game_time` field of the POST body into a ``GameTime``.

    Two accepted shapes — a canonical world stamp ``"Y0002-D109T14:00:00"``
    or the structured form ``{year, season, day, hour, minute}`` the header
    popover sends. Real dates/ISO strings are NOT accepted any more: the game
    clock runs on the world calendar (plan-game-calendar §2.7). Every problem
    raises ``ValueError`` with a message the caller turns into a 400.
    """
    from app.core.game_time import GameTime
    if isinstance(raw, str):
        return GameTime.parse(raw.strip())
    if not isinstance(raw, dict):
        raise ValueError("game_time must be a canonical stamp or an object")

    def _int(key: str, required: bool = True, default: int = 0) -> int:
        value = raw.get(key)
        if value is None or value == "":
            if required:
                raise ValueError(f"game_time.{key} is required")
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"game_time.{key} must be a number")

    season = str(raw.get("season") or "").strip()
    if not season:
        raise ValueError("game_time.season is required")
    year = _int("year")
    if year < 1:
        raise ValueError("game_time.year is 1-based")
    return GameTime.from_season(
        year, season, _int("day"),
        _int("hour", required=False), _int("minute", required=False),
        _int("second", required=False))


@router.post("/game-time")
async def post_game_time(
    request: Request,
    lang: str = Query("en"),
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Sets game time and/or tick factor.

    Body: ``{game_time?: {year, season, day, hour, minute} | "Y0002-D109T14:00:00",
    factor?: number}``."""
    from app.core.timeutils import (get_game_clock_info, set_game_factor,
                                    set_game_time)
    data = await request.json()
    raw_time = data.get("game_time")
    if isinstance(raw_time, str) and not raw_time.strip():
        raw_time = None
    raw_factor = data.get("factor")
    if raw_time is None and raw_factor is None:
        raise HTTPException(status_code=400, detail="game_time or factor required")
    # Factor first: set_game_factor re-anchors at the CURRENT game time; an
    # explicit game_time afterwards wins as the new anchor.
    if raw_factor is not None:
        try:
            factor = float(raw_factor)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="factor must be a number")
        if factor < 0:
            raise HTTPException(status_code=400, detail="factor must be >= 0")
        set_game_factor(factor)
    if raw_time is not None:
        try:
            set_game_time(_game_time_from_body(raw_time))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    info = get_game_clock_info(lang or "en")
    logger.info("Game time set: game=%s factor=%s",
                info["game"]["canonical"], info["factor"])
    return info


@router.get("/sleep-status")
async def get_sleep_status() -> Dict[str, Any]:
    """Aktueller World-Sleep-Status (alle NPCs schlafen?)."""
    from app.models.world import is_world_sleeping
    return {"sleeping": is_world_sleeping()}


@router.post("/sleep")
async def sleep_world_route(
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Schlafmodus AN: alle NPCs schlafen sofort ein — keine NPC-LLM-Chat-Calls
    mehr. Ticks, Memory-Konsolidierung, Scheduler, TaskQueue und die Game-Uhr
    laufen weiter (anders als Freeze)."""
    return world_ops.sleep_world()


@router.post("/wake")
async def wake_world_route(
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Schlafmodus AUS: vom Schlafmodus eingeschlaefte NPCs wachen auf;
    natuerlich Schlafende schlafen weiter."""
    return world_ops.wake_world()


@router.get("/settings")
async def get_world_settings() -> Dict[str, Any]:
    """World-level settings (news channel presentation)."""
    return world_ops.build_world_settings_payload()


@router.put("/settings")
async def put_world_settings(request: Request) -> Dict[str, Any]:
    """Set world-level settings from the request body."""
    data = await request.json()
    return world_ops.apply_world_settings(data)


@router.patch("/locations/{location_id}/position")
async def update_location_position_route(location_id: str, request: Request) -> Dict[str, Any]:
    """Place a location on the world map (metres) or unplace it.

    Body: ``{"pos_x": float|null, "pos_z": float|null, "yaw_deg": float?}``.
    A null or missing coordinate unplaces the location; a missing ``yaw_deg``
    leaves the stored rotation untouched.
    """
    try:
        data = await request.json()
        pos_x = data.get("pos_x")
        pos_z = data.get("pos_z")
        yaw_deg = data.get("yaw_deg")
        try:
            pos_x = None if pos_x is None else float(pos_x)
            pos_z = None if pos_z is None else float(pos_z)
            yaw_deg = None if yaw_deg is None else float(yaw_deg)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400,
                                detail="pos_x/pos_z must be numbers or null")

        loc = update_location_position(location_id, pos_x, pos_z, yaw_deg)
        if not loc:
            raise HTTPException(status_code=404, detail="Location not found")
        return {"status": "success", "location": loc}
    except HTTPException:
        raise
    except ValueError as e:
        # The model rejects non-finite values (NaN/Infinity pass the float()
        # above unharmed and would otherwise be persisted, after which every
        # worldmap response 500s under allow_nan=False). Nothing was written.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Terrain types (seamless world) ===

@router.get("/terrain-types")
def get_terrain_types_route() -> Dict[str, Any]:
    """Effective terrain-type catalog (shared overlaid by world rows)."""
    from app.core import terrain_types
    catalog = terrain_types.effective_catalog()
    return {"types": sorted(catalog.values(), key=lambda t: t["kind"]),
            "sources": terrain_types.sources()}


@router.put("/terrain-types/{kind}")
async def put_terrain_type_route(kind: str, request: Request) -> Dict[str, Any]:
    """Create/replace the WORLD override of one terrain kind."""
    from app.core import terrain_types
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    data["kind"] = kind
    try:
        return {"status": "success", "type": terrain_types.save_world_type(data)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/terrain-types/{kind}")
def delete_terrain_type_route(kind: str) -> Dict[str, Any]:
    """Remove the world override; a shared entry of the same kind returns."""
    from app.core import terrain_types
    if not terrain_types.delete_world_type(kind):
        raise HTTPException(status_code=404, detail="no world override")
    return {"status": "success"}


# === Terrain areas (seamless world) ===

@router.get("/terrain-areas")
def get_terrain_areas_route() -> Dict[str, Any]:
    """All painted areas bottom-to-top, plus the change signature.

    A water area carries one ADDITIVE, server-computed field alongside its
    authored ones: ``meta.water_level_effective`` — the mirror height the bake
    really carved with (E1, § G4). The author's ``meta.water_level`` may be
    unset ("auto (rim)"), and then this is the rim median the bake derived; set
    it and the two are equal. It is output only and is never written back into
    the authored field.
    """
    from app.core.heightfield import with_effective_water_level
    from app.models import terrain
    return {"areas": with_effective_water_level(terrain.list_areas()),
            "sig": terrain.terrain_sig()}


@router.post("/terrain-areas")
async def post_terrain_area_route(request: Request) -> Dict[str, Any]:
    """Paint a new area; the id is assigned by the server."""
    from app.models import terrain
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    data.pop("id", None)
    try:
        return {"status": "success", "area": terrain.save_area(data)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/terrain-areas/{area_id}")
async def put_terrain_area_route(area_id: str, request: Request) -> Dict[str, Any]:
    """Replace one EXISTING area (kind, outline, z_order, meta); 404 otherwise.

    The store is an upsert, so without this check a PUT on an unknown id would
    silently create the area — and a client repeating a stale PUT would bring a
    just-deleted area back. Creating is POST's job (which assigns the id).
    """
    from app.models import terrain
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    if not terrain.area_exists(area_id):
        raise HTTPException(status_code=404, detail="terrain area not found")
    data["id"] = area_id
    try:
        return {"status": "success", "area": terrain.save_area(data)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/terrain-areas/{area_id}")
def delete_terrain_area_route(area_id: str) -> Dict[str, Any]:
    """Erase one painted area."""
    from app.models import terrain
    if not terrain.delete_area(area_id):
        raise HTTPException(status_code=404, detail="terrain area not found")
    return {"status": "success"}


# === World props (single authored props on the world plane) ===
#
# The CRUD shape of the terrain areas next door, and deliberately a SECOND set
# of routes rather than a flag on those: a painted area says how DENSELY a
# ground grows things, a world prop says "this prop, at this point, turned this
# way". Deco only — nothing here blocks a step (§ A9a).

@router.get("/world-props")
def get_world_props_route() -> Dict[str, Any]:
    """Every placement for the map editor, plus the two cap numbers.

    Each row carries the library ``name`` of its prop and ``missing``: a
    placement whose prop was deleted renders nothing and cannot be repaired —
    the editor is where it becomes visible instead of silently occupying a
    slot of the cap."""
    from app.core import props as prop_store
    from app.models import world_props
    facts: Dict[str, Dict[str, Any]] = {}
    rows = world_props.list_world_props()
    for row in rows:
        pid = row["prop_id"]
        if pid not in facts:
            meta = prop_store.read_sidecar(pid)
            facts[pid] = {
                "name": str(meta.get("name") or "") if meta else "",
                # How many meshes there are to CHOOSE from — the editor offers
                # exactly that many indices instead of holding a ceiling of
                # its own (`prop_variant_max` is configurable).
                "variants": (len(prop_store.active_variant_tiers(pid))
                             if meta else 0),
            }
        row["name"] = facts[pid]["name"]
        row["variant_count"] = facts[pid]["variants"]
        row["missing"] = not facts[pid]["name"]
    return {"world_props": rows, "count": len(rows),
            "max": world_props.MAX_WORLD_PROPS,
            "warn_at": world_props.WARN_WORLD_PROPS,
            "sig": world_props.world_props_sig()}


@router.post("/world-props")
async def post_world_prop_route(request: Request) -> Dict[str, Any]:
    """Place a new prop; the id is assigned by the server. 400 at the cap."""
    from app.models import world_props
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    data.pop("id", None)
    try:
        return {"status": "success",
                "world_prop": world_props.save_world_prop(data)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/world-props/{placement_id}")
async def put_world_prop_route(placement_id: str,
                               request: Request) -> Dict[str, Any]:
    """Replace one EXISTING placement (prop, point, yaw, lift, variant); 404
    otherwise.

    The store is an upsert, so without this check a PUT on an unknown id would
    silently create the placement — and a client repeating a stale PUT would
    bring a just-deleted one back. Creating is POST's job (which assigns the
    id and is the only path that meets the cap)."""
    from app.models import world_props
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    if not world_props.world_prop_exists(placement_id):
        raise HTTPException(status_code=404, detail="world prop not found")
    data["id"] = placement_id
    try:
        return {"status": "success",
                "world_prop": world_props.save_world_prop(data)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/world-props/{placement_id}")
def delete_world_prop_route(placement_id: str) -> Dict[str, Any]:
    """Remove one placement."""
    from app.models import world_props
    if not world_props.delete_world_prop(placement_id):
        raise HTTPException(status_code=404, detail="world prop not found")
    return {"status": "success"}


# === Height areas (world relief, E8) ===
#
# The same CRUD shape as the terrain areas next door — and deliberately a
# SECOND set of routes rather than a flag on those: a height area carries no
# kind, no layer and no scatter, and the ground under a painted meadow may
# well rise. Mixing the two would put passability questions and height
# questions into one body where every write has to say something about both.

#
# THE GRID STEP TRAVELS WITH EVERY ONE OF THEM (finding 14, 2026-08-13). It is
# not authored anywhere: the raster doubles it until the world's whole painted
# extent fits inside the point budget, so a single hill drawn far out coarsens
# the relief everywhere — measured live, a 16 160 × 5 876 m union box forced 4 m
# to 32 m and wiped out a forest's 8…12 m micro-relief, with nothing on screen
# to connect the two. The editor shows the current step and warns when a save
# moves it, and BOTH numbers come from here (``heightfield.current_step_m``)
# rather than from a second implementation of the doubling in the client.

@router.get("/height-areas")
def get_height_areas_route() -> Dict[str, Any]:
    """All authored height areas, the change signature, the grid steps and the
    two walk limits.

    The limits ride along because every editor that shows a relief number has
    to say what it COSTS, and both halves of that sentence are server settings:
    an amplitude is harmless until ``tan(max_slope_deg) · tile_step_m`` is
    exceeded. They are the same two values ``/play/worldmap`` carries, out of
    the same ``core.relief`` getters — sending them here spares the terrain
    editor a second, far heavier fetch of the whole map for two floats.
    """
    from app.core.heightfield import (DEFAULT_STEP_M, TILE_STEP_M,
                                      current_step_m)
    from app.core.relief import get_max_slope_deg, get_max_step_height_m
    from app.models import heightfield
    return {"areas": heightfield.list_height_areas(),
            "sig": heightfield.height_sig(),
            "step_m": current_step_m(),
            # The finest the OVERVIEW gets, so the editor can say "coarser than
            # normal" without a constant of its own.
            "default_step_m": DEFAULT_STEP_M,
            # …and the step of the TILES, which is a different number since
            # 2026-08-14. The editor needs it for the one authoring limit that
            # hangs on a cell width: the ramp around a levelling footprint is
            # ONE CELL wide (§ A16.1), so the rim it can bridge is
            # tan(max_slope_deg) · tile_step_m — 1,68 m at the defaults. That
            # sentence must not carry a constant of its own either; the number
            # halved the day the tiles did, and a pinned 3,36 would have gone
            # on promising twice the climb.
            "tile_step_m": TILE_STEP_M,
            # The walk gate, so the editor can turn an amplitude into "this
            # becomes unwalkable" instead of just showing a number.
            "max_slope_deg": get_max_slope_deg(),
            "max_step_height_m": get_max_step_height_m()}


@router.post("/height-areas")
async def post_height_area_route(request: Request) -> Dict[str, Any]:
    """Draw a new height area; the id is assigned by the server.

    Answers the grid step the world has AFTERWARDS: the write re-rasters
    synchronously (``models.heightfield._invalidate``), so this is the real new
    step and not a forecast — the editor compares it with the one it held and
    says out loud when the drawing just coarsened the world.
    """
    from app.core.heightfield import current_step_m
    from app.models import heightfield
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    data.pop("id", None)
    try:
        area = heightfield.save_height_area(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "area": area, "step_m": current_step_m()}


@router.put("/height-areas/{area_id}")
async def put_height_area_route(area_id: str, request: Request) -> Dict[str, Any]:
    """Replace one EXISTING height area (outline, height, falloff, meta).

    404 on an unknown id, for the reason the terrain route has it: the store is
    an upsert, so a repeated stale PUT would otherwise raise a deleted hill
    from the dead under its old id.

    Carries ``step_m`` like the POST does — dragging one vertex 8 km east
    coarsens the world's grid exactly as drawing a new area there would.
    """
    from app.core.heightfield import current_step_m
    from app.models import heightfield
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    if not heightfield.height_area_exists(area_id):
        raise HTTPException(status_code=404, detail="height area not found")
    data["id"] = area_id
    try:
        area = heightfield.save_height_area(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "area": area, "step_m": current_step_m()}


@router.delete("/height-areas/{area_id}")
def delete_height_area_route(area_id: str) -> Dict[str, Any]:
    """Erase one height area — the ground there falls back to the flat world."""
    from app.models import heightfield
    if not heightfield.delete_height_area(area_id):
        raise HTTPException(status_code=404, detail="height area not found")
    return {"status": "success"}


@router.delete("/locations/{location_name}")
def delete_location_route(
    location_name: str,
    character_name: str = Query("", alias="agent_name")
) -> Dict[str, Any]:
    """Loescht einen Ort (per ID oder Name)."""
    if delete_location(location_name):
        return {"status": "success", "deleted": location_name}
    raise HTTPException(status_code=404, detail="Ort nicht gefunden")


# ── Location 3D building model (AV3D-9) ──
# ONE unrigged GLB per location, keyed by the gallery owner (clones share it).
# Source is a gallery image of type "building"; generation goes through the
# mesh backend (rig "none") on the queue channel. Auth matches the other
# location-content routes (create/update/delete) — no separate admin gate.

_LOCATION_MODEL_MAX_BYTES = 100 * 1024 * 1024


@router.get("/locations/{location_id}/model3d/status")
def location_model3d_status(location_id: str) -> Dict[str, Any]:
    """Building-model status: {exists, pending, meta, backends, default,
    shrink_backends}. ``backends`` = the available rig-'none' img2mesh
    backends; ``default`` = the admin default only when its rig is 'none';
    ``shrink_backends`` = the mesh→mesh aliases behind "Create low variant"
    (empty = none configured)."""
    from app.core.location_model3d import get_building_info
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    return get_building_info(location_id)


def _mesh_int(val) -> int:
    """Optional per-run mesh override from a JSON body (0/invalid = unset)."""
    try:
        return max(0, int(float(val)))
    except (TypeError, ValueError):
        return 0


def _tier(val) -> str:
    """Requested resolution tier from a body/form field ('' = the default
    tier). Unknown names are not rejected — the store answers with what it
    has (plan-3d-lod-und-betreten.md)."""
    from app.core.model_store import DEFAULT_TIER, normalize_tier
    return normalize_tier(val) or DEFAULT_TIER


@router.post("/locations/{location_id}/model3d/generate")
async def location_model3d_generate(location_id: str, request: Request) -> Dict[str, Any]:
    """Generate the location's 3D building model from a gallery image
    (body: {source_image, backend?, face_num?, texture_size?, tier?,
    lod_faces?}). ``tier`` says which resolution slot the result fills
    (default ``full``); ``lod_faces`` additionally asks the alias to bake a
    reduced stage in the SAME job, which lands as the ``low`` variant.
    Background job — poll status for pending."""
    from app.core.location_model3d import trigger_generation
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    source_image = str(data.get("source_image") or "").strip()
    if not source_image:
        raise HTTPException(status_code=400,
                            detail="source_image required (a building gallery image of the location)")
    backend = str(data.get("backend") or "").strip()
    if not trigger_generation(location_id, source_image=source_image,
                              backend_glob=backend,
                              face_num=_mesh_int(data.get("face_num")) or None,
                              texture_size=_mesh_int(data.get("texture_size")) or None,
                              tier=_tier(data.get("tier")),
                              lod_faces=_mesh_int(data.get("lod_faces")) or None):
        return {"status": "already_running"}
    return {"status": "generating"}


def _shrink_body(data: Any) -> Dict[str, Any]:
    """Parsed body of a low-variant request (body: {file, backend?, face_num?,
    texture_size?}). ``file`` is a STORED gallery file of the subject — the
    reduction reads a mesh, not an image."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    source_file = str(data.get("file") or "").strip()
    if not source_file:
        raise HTTPException(status_code=400,
                            detail="file required (a stored model of this subject)")
    return {"source_file": source_file,
            "backend_glob": str(data.get("backend") or "").strip(),
            "face_num": _mesh_int(data.get("face_num")) or None,
            "texture_size": _mesh_int(data.get("texture_size")) or None}


def _shrink_start(trigger, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Run a ``trigger_shrink`` and map its outcome to the HTTP answer.

    A source mesh the reduction cannot use (no UVs / no texture) is a bad
    REQUEST, not a failure to report later: the gateway job would die with a
    permanent input error, so the reason goes back as a 400 instead."""
    from app.core.model_validate import MeshNotShrinkable
    try:
        started = trigger(*args, **kwargs)
    except MeshNotShrinkable as e:
        raise HTTPException(status_code=400, detail=e.reason) from e
    return {"status": "generating" if started else "already_running"}


def _lod_result(build, *args: Any, ratio: float = 0.0,
                kind: str = "prop") -> Dict[str, Any]:
    """Run a store's ``build_low_tier`` for the admin's explicit rebuild and
    map its outcome to the HTTP answer.

    Blocking on purpose (the character twin does the same): a CPU reduction
    takes seconds, not the minutes a GPU mesh job takes, so the panel gets the
    triangle counts back instead of polling for them. ``force`` is always set —
    the button IS the decision, so it also overrides the "build distance meshes
    on demand" switch and an existing low tier (whose file stays in the
    gallery; the new one is a fresh entry, not an overwrite)."""
    from app.blender import refine, runner
    ratio = float(ratio or refine.lod_ratio(kind))
    if not 0.02 <= ratio < 1:
        # A nonsensical request stays a 400 even on a host without Blender —
        # the request is wrong either way, and saying so is more useful than
        # blaming the environment.
        raise HTTPException(status_code=400,
                            detail="ratio must be between 0.02 and 1")
    # The same gate the panel shows the button behind: usable = switched on,
    # binary found AND it answers with a version.
    if not runner.status()["usable"]:
        raise HTTPException(status_code=503,
                            detail=refine.unavailable_reason()
                            or "blender is not usable")
    res = build(*args, ratio=ratio, force=True)
    if not res.get("ok"):
        err = res.get("error", "")
        raise HTTPException(status_code=404 if err == "no_model" else 503,
                            detail=err or "distance mesh build failed")
    return res


@router.post("/locations/{location_id}/model3d/shrink")
async def location_model3d_shrink(location_id: str, request: Request) -> Dict[str, Any]:
    """Reduce a STORED building model to a low variant (body: {file, backend?,
    face_num?, texture_size?}) via a mesh→mesh backend. The result is a NEW
    gallery file, always selected for tier ``low``. Background job — poll
    status for pending. A source mesh without UVs/texture answers 400 with
    the reason (it can never be reduced)."""
    from app.core.location_model3d import model_file_path, trigger_shrink
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    body = _shrink_body(await request.json())
    if not model_file_path(location_id, body["source_file"]):
        raise HTTPException(status_code=404, detail="Model not found")
    return _shrink_start(trigger_shrink, location_id, **body)


@router.post("/locations/{location_id}/model3d/lod")
def location_model3d_lod(location_id: str, ratio: float = 0) -> Dict[str, Any]:
    """Build the location's distance mesh from its full building model on the
    CPU (Blender Decimate) — the "Build distance mesh" button.

    ``ratio`` is the target fraction of the triangle count (default: the
    configured one for buildings). The result is a NEW gallery file selected
    as ``low``; an existing low model stays stored and can be selected back."""
    from app.core.location_model3d import build_low_tier
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    return _lod_result(build_low_tier, location_id, "", ratio=ratio,
                       kind="building")


@router.post("/locations/{location_id}/model3d/upload")
async def location_model3d_upload(location_id: str, request: Request) -> Dict[str, Any]:
    """Upload a GLB as the location's building model (validated as an unrigged
    GLB with an embedded texture; force=1 stores despite validation errors)."""
    from app.core.location_model3d import save_uploaded_building
    from app.core.model_validate import validate_static_glb
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")
    if not (file.filename or "").lower().endswith(".glb"):
        raise HTTPException(status_code=400,
                            detail="Building models must be a GLB (embedded texture, no rig)")
    contents = await file.read()
    if len(contents) > _LOCATION_MODEL_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    result = validate_static_glb(contents)
    force = str(form.get("force") or "").strip().lower() in ("1", "true", "yes")
    if not result["ok"] and not force:
        raise HTTPException(status_code=422, detail={
            "reason": "invalid_model",
            "errors": result["errors"],
            "warnings": result["warnings"],
        })
    meta = save_uploaded_building(location_id, contents,
                                  source_image=str(form.get("source_image") or ""),
                                  tier=_tier(form.get("tier")))
    return {"status": "success", **meta, "warnings": result["warnings"]}


# ── The generated ROOF (docs/llm-blender-models.md) ──
# Two steps, deliberately: PROPOSE hands the admin a validated description to
# look at and edit, BUILD executes exactly what comes back. Nothing here is
# silent — the roof is a parametric building part, and its parameters are the
# feature.

@router.post("/locations/{location_id}/roof/propose")
def location_roof_propose(location_id: str) -> Dict[str, Any]:
    """Propose a roof for this location: one LLM call over the known facts.

    Returns the footprint (with the source it came from), the storey count,
    the eaves height and a VALIDATED build description — plus ``llm`` saying
    whether the description really came from a model or is the clamped
    default (an unrouted task is not an error here). 409 = the location has
    nothing to roof."""
    from app.core.roof_model import propose_roof
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    res = propose_roof(location_id)
    if not res.get("ok"):
        raise HTTPException(
            status_code=409,
            detail="This location has no footprint to roof — draw a building "
                   "outline, a boundary, or give it a room with a floor plan.")
    return res


@router.post("/locations/{location_id}/roof/generate")
async def location_roof_generate(location_id: str, request: Request) -> Dict[str, Any]:
    """Build the roof from a description (body: the description object, or
    ``{description: {...}}``) and store it as the location's building model.

    Background job — poll ``model3d/status`` for ``pending``. The description
    is validated and clamped again here: what the UI sends is a suggestion,
    not a contract."""
    from app.blender import runner
    from app.core.roof_model import trigger_roof_generation, validate_description
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    if not runner.is_available():
        raise HTTPException(status_code=503,
                            detail="Blender is not available — the roof is "
                                   "built locally, not on a backend.")
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    raw = data.get("description") if isinstance(data.get("description"), dict) else data
    desc = validate_description(raw)
    if not trigger_roof_generation(location_id, desc):
        return {"status": "already_running", "description": desc}
    return {"status": "generating", "description": desc}


@router.delete("/locations/{location_id}/model3d")
def location_model3d_delete(location_id: str, file: str = "") -> Dict[str, Any]:
    """Remove ONE stored building model (?file=<name>) or all of them (no
    param). Deleting the active one re-points the selection."""
    from app.core.location_model3d import delete_building_model
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    return {"status": "success",
            "removed": delete_building_model(location_id, filename=file)}


@router.post("/locations/{location_id}/model3d/select")
async def location_model3d_select(location_id: str, request: Request) -> Dict[str, Any]:
    """Make a stored model the ACTIVE building model of a resolution tier
    (body: {file, tier?}) — the one the clients get via
    /play/locations/{id}/model?tier=. An empty {file} deselects: on the
    default tier nothing is rendered until another one is chosen/generated,
    on any other tier that tier ceases to exist."""
    from app.core.location_model3d import select_model
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    data = await request.json()
    filename = str((data or {}).get("file") or "").strip()
    tier = _tier((data or {}).get("tier"))
    if not select_model(location_id, filename, tier=tier):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"status": "success", "active": filename, "tier": tier}


@router.get("/locations/{location_id}/model3d/files/{filename}")
def location_model3d_file(location_id: str, filename: str, request: Request):
    """Serve ONE stored building model by filename — the admin viewer previews
    non-active models with it (clients only ever see the active one)."""
    from app.core.location_model3d import model_file_path
    from app.core.http_files import etag_file_response
    p = model_file_path(location_id, filename)
    if not p:
        raise HTTPException(status_code=404, detail="Model not found")
    media = ("model/gltf-binary" if p.suffix.lower() == ".glb"
             else "application/octet-stream")
    return etag_file_response(p, request, media)


@router.post("/locations/{location_id}/model3d/rotation")
async def location_model3d_rotation(location_id: str, request: Request) -> Dict[str, Any]:
    """Persist a building model's orientation fix (body: {x,y,z} in degrees,
    snapped to 90-degree steps; optional {file} targets a stored model, default
    the active one). Delivered to every client via /model/meta — generated
    meshes come out arbitrarily oriented, the admin dials the fix in the
    viewer."""
    from app.core.location_model3d import set_rotation
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    try:
        meta = set_rotation(location_id, data,
                            filename=str(data.get("file") or "").strip())
    except ValueError:
        raise HTTPException(status_code=404, detail="No model")
    return {"meta": meta}


@router.post("/locations/{location_id}/model3d/offset")
async def location_model3d_offset(location_id: str, request: Request) -> Dict[str, Any]:
    """Persist a building model's vertical placement offset (body:
    {offset_y}/{offset_x}/{offset_z}/{walk_y} in metres, ±, each optional; {file} targets a stored model, default
    the active one). Delivered via /model/meta — a model property (socket
    thickness varies); negative sinks the model into the terrain. ``walk_y``
    is the walkable surface above the model bottom (stand height of overlay
    zones on an area location)."""
    from app.core.location_model3d import set_offset_y
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    try:
        meta = set_offset_y(location_id, data.get("offset_y"),
                            offset_x=data.get("offset_x"),
                            offset_z=data.get("offset_z"),
                            walk_y=data.get("walk_y"),
                            filename=str(data.get("file") or "").strip())
    except ValueError:
        raise HTTPException(status_code=404, detail="No model")
    return {"meta": meta}


@router.post("/locations/{location_id}/model3d/width")
async def location_model3d_width(location_id: str, request: Request) -> Dict[str, Any]:
    """Persist a building model's real-world width in metres (body:
    {width_m}, 0/empty = undeclared; optional {file}). THE scale dial since
    contract v6 Nr. 3: the model's largest side — measured after the yaw —
    becomes this many metres. Undeclared, the location's own width
    (map3d.plan_width_m) stands in, which is exactly what the retired
    map3d.size produced at its default 1."""
    from app.core.location_model3d import set_width_m
    if not get_location_by_id(location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    try:
        meta = set_width_m(location_id, data.get("width_m"),
                           filename=str(data.get("file") or "").strip())
    except ValueError:
        raise HTTPException(status_code=404, detail="No model")
    return {"meta": meta}


# The former /model3d/floors and /model3d/height endpoints are gone
# (2026-07-28): both existed to squash a building model in Y. A model is
# scaled by ONE factor on all three axes now, and since v6 Nr. 3 that factor
# comes from its DECLARED REAL WIDTH (/model3d/width above); the storey
# height is a location dial in real metres (map3d.storey_height_m).


# --- Room models (AV3D-2) — same store/contract as the building model, one
# per room (stem room_<room_id>, shared with clones via the template rooms).

def _require_room(location_id: str, room_id: str) -> None:
    loc = get_location_by_id(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    from app.models.world import get_room_by_id
    if not get_room_by_id(loc, room_id):
        raise HTTPException(status_code=404, detail="Room not found")


@router.get("/locations/{location_id}/rooms/{room_id}/model3d/status")
def room_model3d_status(location_id: str, room_id: str) -> Dict[str, Any]:
    """Room-model status: {exists, pending, meta, backends, default,
    shrink_backends} — same shape as the building twin."""
    from app.core.location_model3d import get_building_info
    _require_room(location_id, room_id)
    return get_building_info(location_id, room_id=room_id)


@router.post("/locations/{location_id}/rooms/{room_id}/model3d/generate")
async def room_model3d_generate(location_id: str, room_id: str,
                                request: Request) -> Dict[str, Any]:
    """Generate the room's 3D model from a gallery image assigned to the room
    (body: {source_image, backend?, face_num?, texture_size?, tier?,
    lod_faces?}). Same tier contract as the building model. Background job —
    poll status."""
    from app.core.location_model3d import trigger_generation
    _require_room(location_id, room_id)
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    source_image = str(data.get("source_image") or "").strip()
    if not source_image:
        raise HTTPException(status_code=400,
                            detail="source_image required (a gallery image assigned to the room)")
    backend = str(data.get("backend") or "").strip()
    if not trigger_generation(location_id, source_image=source_image,
                              backend_glob=backend, room_id=room_id,
                              face_num=_mesh_int(data.get("face_num")) or None,
                              texture_size=_mesh_int(data.get("texture_size")) or None,
                              tier=_tier(data.get("tier")),
                              lod_faces=_mesh_int(data.get("lod_faces")) or None):
        return {"status": "already_running"}
    return {"status": "generating"}


@router.post("/locations/{location_id}/rooms/{room_id}/model3d/shrink")
async def room_model3d_shrink(location_id: str, room_id: str,
                              request: Request) -> Dict[str, Any]:
    """Reduce a STORED room model to a low variant (body: {file, backend?,
    face_num?, texture_size?}). Same contract as the building twin —
    including the 400 on a source mesh that cannot be reduced."""
    from app.core.location_model3d import model_file_path, trigger_shrink
    _require_room(location_id, room_id)
    body = _shrink_body(await request.json())
    if not model_file_path(location_id, body["source_file"], room_id):
        raise HTTPException(status_code=404, detail="Model not found")
    return _shrink_start(trigger_shrink, location_id, room_id=room_id, **body)


@router.post("/locations/{location_id}/rooms/{room_id}/model3d/lod")
def room_model3d_lod(location_id: str, room_id: str,
                     ratio: float = 0) -> Dict[str, Any]:
    """Build the room diorama's distance mesh on the CPU (Blender Decimate) —
    same contract as the building twin, with the room's own default ratio (a
    diorama is mostly flat walls and tolerates far less reduction than a
    compact prop)."""
    from app.core.location_model3d import build_low_tier
    _require_room(location_id, room_id)
    return _lod_result(build_low_tier, location_id, room_id, ratio=ratio,
                       kind="room")


@router.post("/locations/{location_id}/rooms/{room_id}/model3d/upload")
async def room_model3d_upload(location_id: str, room_id: str,
                              request: Request) -> Dict[str, Any]:
    """Upload a GLB as the room's 3D model (validated as an unrigged GLB with
    an embedded texture; force=1 stores despite validation errors)."""
    from app.core.location_model3d import save_uploaded_building
    from app.core.model_validate import validate_static_glb
    _require_room(location_id, room_id)
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")
    if not (file.filename or "").lower().endswith(".glb"):
        raise HTTPException(status_code=400,
                            detail="Room models must be a GLB (embedded texture, no rig)")
    contents = await file.read()
    if len(contents) > _LOCATION_MODEL_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    result = validate_static_glb(contents)
    force = str(form.get("force") or "").strip().lower() in ("1", "true", "yes")
    if not result["ok"] and not force:
        raise HTTPException(status_code=422, detail={
            "reason": "invalid_model",
            "errors": result["errors"],
            "warnings": result["warnings"],
        })
    meta = save_uploaded_building(location_id, contents,
                                  source_image=str(form.get("source_image") or ""),
                                  room_id=room_id, tier=_tier(form.get("tier")))
    return {"status": "success", **meta, "warnings": result["warnings"]}


@router.delete("/locations/{location_id}/rooms/{room_id}/model3d")
def room_model3d_delete(location_id: str, room_id: str, file: str = "") -> Dict[str, Any]:
    """Remove ONE stored room model (?file=<name>) or all of them (no param)."""
    from app.core.location_model3d import delete_building_model
    _require_room(location_id, room_id)
    return {"status": "success",
            "removed": delete_building_model(location_id, room_id=room_id,
                                             filename=file)}


@router.post("/locations/{location_id}/rooms/{room_id}/model3d/select")
async def room_model3d_select(location_id: str, room_id: str,
                              request: Request) -> Dict[str, Any]:
    """Make a stored model the ACTIVE room model of a resolution tier (body:
    {file, tier?}). An empty {file} on the default tier selects NO model — the
    room renders without a diorama."""
    from app.core.location_model3d import select_model
    _require_room(location_id, room_id)
    data = await request.json()
    filename = str((data or {}).get("file") or "").strip()
    tier = _tier((data or {}).get("tier"))
    if not select_model(location_id, filename, room_id=room_id, tier=tier):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"status": "success", "active": filename, "tier": tier}


@router.get("/locations/{location_id}/rooms/{room_id}/model3d/files/{filename}")
def room_model3d_file(location_id: str, room_id: str, filename: str, request: Request):
    """Serve ONE stored room model by filename (admin preview)."""
    from app.core.location_model3d import model_file_path
    from app.core.http_files import etag_file_response
    p = model_file_path(location_id, filename, room_id=room_id)
    if not p:
        raise HTTPException(status_code=404, detail="Model not found")
    media = ("model/gltf-binary" if p.suffix.lower() == ".glb"
             else "application/octet-stream")
    return etag_file_response(p, request, media)


@router.post("/locations/{location_id}/rooms/{room_id}/model3d/rotation")
async def room_model3d_rotation(location_id: str, room_id: str,
                                request: Request) -> Dict[str, Any]:
    """Persist a room model's orientation fix ({x,y,z} in 90-degree steps;
    optional {file} targets a stored model, default the active one) — same
    contract as the building model."""
    from app.core.location_model3d import set_rotation
    _require_room(location_id, room_id)
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    try:
        meta = set_rotation(location_id, data, room_id=room_id,
                            filename=str(data.get("file") or "").strip())
    except ValueError:
        raise HTTPException(status_code=404, detail="No model")
    return {"meta": meta}


@router.post("/locations/{location_id}/rooms/{room_id}/model3d/walk_y")
async def room_model3d_walk_y(location_id: str, room_id: str,
                              request: Request) -> Dict[str, Any]:
    """Persist a room model's WALKABLE floor height (body: {walk_y} in world
    metres above the diorama's final lower edge, 0..5; empty/null removes it;
    optional {file}). Diorama floors are modelled — podiums, sunken lounges
    or holes make the standing height unmeasurable from outside, so the admin
    dials it against the reference figure. Delivered via /model/meta and as
    ``walk_y_world`` on the room's spec in /play/locations/{id}/scene."""
    from app.core.location_model3d import set_walk_y
    _require_room(location_id, room_id)
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    try:
        meta = set_walk_y(location_id, room_id, data.get("walk_y"),
                          filename=str(data.get("file") or "").strip())
    except ValueError:
        raise HTTPException(status_code=404, detail="No model")
    return {"meta": meta}


@router.post("/locations/{location_id}/rooms/{room_id}/model3d/width")
async def room_model3d_width(location_id: str, room_id: str,
                             request: Request) -> Dict[str, Any]:
    """Persist a room model's real-world width in metres (body: {width_m},
    0/empty = undeclared; optional {file}). The admin estimates the
    largest side from the source image; placement stays untouched — the
    value makes the room's content scale explicit (rect extent / width_m)
    and figures in the room derive from it (1.7 m × scale)."""
    from app.core.location_model3d import set_width_m
    _require_room(location_id, room_id)
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    try:
        meta = set_width_m(location_id, data.get("width_m"), room_id=room_id,
                           filename=str(data.get("file") or "").strip())
    except ValueError:
        raise HTTPException(status_code=404, detail="No model")
    return {"meta": meta}


# ── Surface textures (AV3D-13) ──
# Global tileable ground materials for terrain tiles; the 3D client reads
# them via GET /assets/surface-textures. ONE texture per kind (open
# vocabulary matching `terrain`); managed from the Map tab.

@router.get("/surface-textures")
def surface_textures_admin() -> Dict[str, Any]:
    """Admin listing: textures + running generations + backends with their
    resolved use-case style, so the dialog can show and edit the COMPLETE
    final prompt before generating (final-prompt rule).

    ``world_seasons`` / ``current_season`` are the world's season names and
    the one it is in now (E2c): a version can be selected FOR a season, and
    the picker offers exactly those names. An empty list = a world without
    seasons, and then the season controls stay away."""
    from app.core.surface_textures import (admin_list, compose_prompt,
                                            is_pending)
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    backends = []
    try:
        for b in svc.list_available_backends(media="image"):
            style = compose_prompt("", b)
            # False = no negative input (auto/yes/no resolved in
            # negation_fold): the form hides the field, and the handoff folds
            # whatever negative is submitted into the prompt as negations.
            backends.append({"name": b.name,
                             "prompt_style": style["style"],
                             "prompt_negative": style["negative"],
                             "supports_negative_prompt": bool(
                                 getattr(b, "supports_negative_prompt", True))})
    except Exception:
        pass
    from app.core.surface_textures import get_blends
    # No `subjects` map any more: the description is a plain field on the
    # kind (admin_list), and it is the only text that reaches a prompt. The
    # curated wording is seeded INTO that field when a kind is created, so
    # there is nothing left for the dialog to merge.
    from app.core.game_time import get_calendar
    from app.core.timeutils import game_time
    cal = get_calendar()
    try:
        current = (cal.seasons[game_time().parts(cal).season_index].name
                   if cal.seasons else "")
    except Exception:
        current = ""
    return {"textures": admin_list(), "pending": is_pending(),
            "backends": backends, "blends": get_blends(),
            "world_seasons": [s.name for s in cal.seasons],
            "current_season": current}


@router.post("/surface-textures/generate")
async def surface_texture_generate(request: Request) -> Dict[str, Any]:
    """Generate ONE kind's texture via the image pipeline (body: {name?,
    kind?, description?, backend?, prompt?, negative?} — prompt/negative come
    verbatim from the dialog, empty = server-composed use-case default).

    A NEW kind needs only a name: the server derives the id from it and
    answers with the id it used. Sending an explicit ``kind`` overrides that
    — the caller never has to slugify anything itself."""
    from app.core.surface_textures import trigger_generation
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    kind = trigger_generation(
        str(data.get("kind") or ""),
        name=str(data.get("name") or ""),
        description=str(data.get("description") or ""),
        backend_glob=str(data.get("backend") or "").strip(),
        prompt=str(data.get("prompt") or ""),
        negative=str(data.get("negative") or ""))
    if not kind:
        raise HTTPException(
            status_code=400,
            detail="a name (or an id) is required — the id is derived from the name")
    if kind == "busy":
        return {"status": "already_running"}
    return {"status": "generating", "kind": kind}


@router.post("/surface-textures/{kind}/meta")
async def surface_texture_meta(kind: str, request: Request) -> Dict[str, Any]:
    """Name (free text, spaces welcome), description and material class of a
    kind (body: {name?, description?, material?}; '' clears a field, a matte
    material clears the declaration). The id is NOT editable — it
    sits in file names and in world data (terrain, level_floors, room floor
    kinds, blend toward), so changing it would be a data migration."""
    from app.core.surface_textures import set_kind_meta
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    entry = set_kind_meta(kind, name=data.get("name"),
                          description=data.get("description"),
                          material=data.get("material"))
    if entry is None:
        raise HTTPException(status_code=400, detail="invalid kind")
    return {"status": "ok", "meta": entry}


@router.post("/surface-textures/blends/{kind}")
async def surface_texture_blend_set(kind: str, request: Request) -> Dict[str, Any]:
    """Create/replace a COMPOSITION entry (AV3D-13 v2, body: {blend}) —
    a zone gradient toward a neighbor kind instead of a texture; the
    client mixes it generically. A blend wins over texture files of the
    same kind in the client list."""
    from app.core.surface_textures import set_blend
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    clean = set_blend(kind, data.get("blend"))
    if clean is None:
        raise HTTPException(status_code=400,
                            detail="bad kind or blend (toward + ordered zones required)")
    return {"status": "ok", "blend": clean}


@router.delete("/surface-textures/blends/{kind}")
def surface_texture_blend_delete(kind: str) -> Dict[str, Any]:
    from app.core.surface_textures import delete_blend
    if not delete_blend(kind):
        raise HTTPException(status_code=404, detail="No blend for this kind")
    return {"status": "deleted"}


@router.post("/surface-textures/{kind}/upload")
async def surface_texture_upload(kind: str, file: UploadFile = File(...),
                                 name: str = Form("")) -> Dict[str, Any]:
    """Upload a texture for a kind (JPEG/PNG/WebP, sniffed; ≤ 10 MB). Like a
    generation this may CREATE the kind: pass ``kind`` as ``-`` and a ``name``
    form field, and the server derives the id and answers with it."""
    from app.core.surface_textures import save_uploaded
    contents = await file.read()
    res = save_uploaded("" if kind == "-" else kind, contents, name=name)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "upload failed")
    return res


@router.post("/surface-textures/{kind}/size")
async def surface_texture_size(kind: str, request: Request) -> Dict[str, Any]:
    """Set the physical edge length in metres (body: {size_m}, optional
    {file} targets a stored version, default the active one; 3 = default)."""
    from app.core.surface_textures import set_size_m
    data = await request.json()
    if not isinstance(data, dict) or not set_size_m(
            kind, data.get("size_m"), filename=str(data.get("file") or "").strip()):
        raise HTTPException(status_code=400, detail="bad kind or size_m")
    return {"status": "ok"}


@router.post("/surface-textures/{kind}/select")
async def surface_texture_select(kind: str, request: Request) -> Dict[str, Any]:
    """Make a stored version the ACTIVE one (body: {file, season?}) — the one
    the 3D client gets via /assets/surface-textures.

    ``season`` targets one SEASON SLOT of the kind instead of its seasonless
    default (E2c): the world shows that version while that season lasts and
    falls back to the default otherwise. An empty ``file`` WITH a season clears
    that slot again. The answer carries the kind's slots as they now stand, so
    the strip re-draws from the server rather than from a guess."""
    from app.core.surface_textures import select_texture, selection_slots
    data = await request.json()
    if not isinstance(data, dict) or not select_texture(
            kind, str(data.get("file") or "").strip(),
            season=str(data.get("season") or "").strip()):
        raise HTTPException(status_code=404, detail="No such texture version")
    return {"status": "ok", "slots": selection_slots(kind)}


@router.delete("/surface-textures/{kind}")
def surface_texture_delete(kind: str, file: str = "") -> Dict[str, Any]:
    """Remove ONE version (?file=) or ALL versions of the kind. Deleting
    the active version moves the selection to the newest remaining one."""
    from app.core.surface_textures import delete_texture
    if not delete_texture(kind, filename=file.strip()):
        raise HTTPException(status_code=404, detail="No texture for this kind")
    return {"status": "deleted"}


# ── Props (plan-room-props.md) ──
# Prop library CRUD (single furnishing objects). Read-serving is /assets/props;
# the 3D map client reads the library from there. Placement into a room (the
# room recipe) is Fable's part and lives elsewhere.

_PROP_MODEL_MAX_BYTES = 100 * 1024 * 1024
#: A product shot is stored downscaled to 1024 px — anything beyond this is a
#: file that was never meant to be one.
_PROP_SOURCE_MAX_BYTES = 20 * 1024 * 1024


@router.get("/props")
def props_admin() -> Dict[str, Any]:
    """Admin listing: all props (full sidecar detail) + running generations +
    the available backends. ``image_backends`` carry their resolved ``prop``
    use-case style so the dialog can show and edit the COMPLETE final source
    prompt (final-prompt rule); ``mesh_backends`` are the rig-'none' img2mesh
    aliases."""
    from app.core.props import (compose_prompt, is_pending, list_props,
                                pending_variants)
    from app.core.model3d import list_mesh_backends
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    image_backends = []
    try:
        for b in svc.list_available_backends(media="image"):
            style = compose_prompt("", b)
            # False = no negative input (auto/yes/no resolved in
            # negation_fold): the form hides the field, and the handoff folds
            # whatever negative is submitted into the prompt as negations.
            image_backends.append({"name": b.name,
                                   "prompt_style": style["style"],
                                   "prompt_negative": style["negative"],
                                   "supports_negative_prompt": bool(
                                       getattr(b, "supports_negative_prompt",
                                               True))})
    except Exception:
        pass
    return {"props": list_props(full=True), "pending": is_pending(),
            # WHICH variant of a pending prop is running, by store index — the
            # strip puts its spinner on that chip, while `pending` stays the
            # aggregate the library row shows.
            "generating_variants": pending_variants(),
            "image_backends": image_backends,
            "mesh_backends": list_mesh_backends("none").get("backends", [])}


@router.post("/props/generate")
async def prop_generate(request: Request) -> Dict[str, Any]:
    """Create a prop from a prompt and kick off the source→mesh chain (body:
    {name, category?, width_m?, depth_m?, height_m?, prompt?, negative?,
    image_backend?, mesh_backend?}). Missing dims become the largest given one;
    they are refined from the mesh proportions once the model exists.
    Background job — poll /world/props for pending."""
    from app.core.props import create_prop, trigger_generation
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    prop = create_prop(name=name, category=str(data.get("category") or ""),
                       width_m=data.get("width_m"), depth_m=data.get("depth_m"),
                       height_m=data.get("height_m"),
                       description=str(data.get("description") or ""),
                       prompt=str(data.get("prompt") or ""),
                       source="generated")
    trigger_generation(prop["id"],
                        prompt=str(data.get("prompt") or ""),
                        negative=str(data.get("negative") or ""),
                        image_backend_glob=str(data.get("image_backend") or "").strip(),
                        mesh_backend_glob=str(data.get("mesh_backend") or "").strip(),
                        face_num=_mesh_int(data.get("face_num")) or None,
                        texture_size=_mesh_int(data.get("texture_size")) or None,
                        tier=_tier(data.get("tier")),
                        lod_faces=_mesh_int(data.get("lod_faces")) or None)
    return {"status": "generating", "prop": prop}


@router.post("/props")
async def prop_create(request: Request) -> Dict[str, Any]:
    """Create a prop record (body: {name, category?, width_m?, depth_m?,
    height_m?, tags?}). Missing dims become the largest given one. The
    model/source files follow via upload or the generation chain."""
    from app.core.props import create_prop
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    prop = create_prop(name=name, category=str(data.get("category") or ""),
                       width_m=data.get("width_m"), depth_m=data.get("depth_m"),
                       height_m=data.get("height_m"), tags=data.get("tags"),
                       description=str(data.get("description") or ""))
    return {"status": "ok", "prop": prop}


# ── Prop Import / Export ──
# Registered BEFORE the /props/{prop_id} routes: "import" is a literal path
# and would otherwise be swallowed by the id placeholder.

@router.post("/props/import")
async def import_prop_route(
    file: UploadFile = File(...),
    overwrite: bool = Form(False),
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Import a prop ZIP. The prop id is kept; an existing id answers
    ``{"status": "exists"}`` unless `overwrite` is set."""
    from app.core.content_io import import_prop_from_zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    try:
        return import_prop_from_zip(content, overwrite=overwrite)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/props/{prop_id}/export")
def export_prop_route(prop_id: str,
                      _: Dict[str, Any] = Depends(require_admin)) -> StreamingResponse:
    """Streams a single-prop ZIP (the whole props/<prop_id>/ directory)."""
    from app.core.content_io import export_prop_to_zip
    from app.core.props import safe_prop_id
    try:
        zip_bytes = export_prop_to_zip(prop_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # The normalized id in the header — the raw path segment never reaches it.
    pid = safe_prop_id(prop_id)
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="prop_{pid}.zip"'},
    )


@router.get("/props/{prop_id}")
def prop_detail(prop_id: str) -> Dict[str, Any]:
    """Full detail of ONE prop."""
    from app.core.props import get_prop
    prop = get_prop(prop_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"prop": prop}


@router.post("/props/{prop_id}")
async def prop_update(prop_id: str, request: Request) -> Dict[str, Any]:
    """Update the editable sidecar fields (body: {name?, description?,
    category?, width_m?, depth_m?, height_m?, tags?, sway_factor?,
    ground_offset_m?}). Patching a
    dim marks the prop's dims as admin-set — they are never redistributed from
    the mesh again. `sway_factor` at its default 1.0 (and any junk) clears the
    key rather than storing it, and `ground_offset_m` does the same at its
    default 0.0 — the prop then simply stands on the ground."""
    from app.core.props import update_prop
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    prop = update_prop(prop_id, data)
    if not prop:
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"status": "ok", "prop": prop}


@router.post("/props/{prop_id}/generate")
async def prop_regenerate(prop_id: str, request: Request) -> Dict[str, Any]:
    """Re-run the source→mesh chain for an EXISTING prop (body:
    {prompt?, negative?, image_backend?, mesh_backend?, face_num?,
    texture_size?, tier?, lod_faces?} — empty prompt = composed from the
    stored description/name). ``lod_faces`` asks the mesh alias for a reduced
    stage of the same bake, which lands as the ``low`` variant.
    ``mesh_only`` re-meshes the
    existing source image; ``image_only`` renders a new source image and
    stops (re-meshing is its own step). Background job — poll /world/props
    for pending."""
    from app.core.props import get_prop, trigger_generation
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    data = await request.json() if (request.headers.get("content-length") or "0") != "0" else {}
    if not isinstance(data, dict):
        data = {}
    if bool(data.get("mesh_only")) and bool(data.get("image_only")):
        raise HTTPException(status_code=400,
                            detail="mesh_only and image_only are exclusive")
    if not trigger_generation(prop_id,
                              prompt=str(data.get("prompt") or ""),
                              negative=str(data.get("negative") or ""),
                              image_backend_glob=str(data.get("image_backend") or "").strip(),
                              mesh_backend_glob=str(data.get("mesh_backend") or "").strip(),
                              face_num=_mesh_int(data.get("face_num")) or None,
                              texture_size=_mesh_int(data.get("texture_size")) or None,
                              mesh_only=bool(data.get("mesh_only")),
                              image_only=bool(data.get("image_only")),
                              tier=_tier(data.get("tier")),
                              lod_faces=_mesh_int(data.get("lod_faces")) or None):
        return {"status": "already_running"}
    return {"status": "generating"}


@router.post("/props/{prop_id}/rotation")
async def prop_rotation(prop_id: str, request: Request) -> Dict[str, Any]:
    """Persist the prop's orientation fix (body: {x,y,z} in degrees, free
    values with 0.1° resolution — the 3D client applies it on load)."""
    from app.core.props import set_rotation
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    prop = set_rotation(prop_id, data)
    if not prop:
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"status": "ok", "prop": prop}


@router.post("/props/{prop_id}/markers")
async def prop_markers(prop_id: str, request: Request) -> Dict[str, Any]:
    """Replace the object-local marker list (body: {markers: [{animation, at:
    [u,v,w], facing?}]}) — same vocabulary as room markers, object-local frame."""
    from app.core.props import set_markers
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    prop = set_markers(prop_id, data.get("markers"))
    if not prop:
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"status": "ok", "prop": prop}


@router.post("/props/{prop_id}/upload")
async def prop_upload(prop_id: str, file: UploadFile = File(...),
                      force: str = "", tier: str = "") -> Dict[str, Any]:
    """Upload a GLB as a NEW model of the prop and make it the active one of
    its resolution tier (validated as an unrigged GLB with an embedded
    texture, like the building models; force=1 stores despite errors)."""
    from app.core.props import get_prop, save_uploaded_glb
    from app.core.model_validate import validate_static_glb
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    if not (file.filename or "").lower().endswith(".glb"):
        raise HTTPException(status_code=400,
                            detail="Props must be a GLB (embedded texture, no rig)")
    contents = await file.read()
    if len(contents) > _PROP_MODEL_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    result = validate_static_glb(contents)
    forced = str(force or "").strip().lower() in ("1", "true", "yes")
    if not result["ok"] and not forced:
        raise HTTPException(status_code=422, detail={
            "reason": "invalid_model",
            "errors": result["errors"],
            "warnings": result["warnings"],
        })
    if not save_uploaded_glb(prop_id, contents, _tier(tier)):
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"status": "ok", "warnings": result["warnings"]}


async def _prop_source_upload(prop_id: str, file: UploadFile,
                              variant: Any = None) -> Dict[str, Any]:
    """Store an uploaded image as ONE variant's source image — the body of
    both source-upload routes (unqualified = the primary variant, the twin in
    ``routes/prop_variants.py`` = the one the admin has open).

    The caller has already validated the prop (and the variant index), so a
    refusal here can only mean unreadable bytes."""
    from app.core.props import get_prop, save_source_image
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    contents = await file.read()
    if len(contents) > _PROP_SOURCE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 20 MB)")
    if not save_source_image(prop_id, contents, variant):
        raise HTTPException(status_code=400, detail="Not a readable image")
    return {"status": "ok"}


@router.post("/props/{prop_id}/source")
async def prop_source_upload(prop_id: str,
                             file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload the product-shot image of the prop's PRIMARY variant — the
    picture a re-mesh ("3D from this image") then works from. Any readable
    image format; it is stored as a PNG of at most 1024 px, alpha kept."""
    return await _prop_source_upload(prop_id, file)


@router.get("/props/{prop_id}/models")
def prop_models(prop_id: str) -> Dict[str, Any]:
    """The prop's mesh gallery: ``{models, tiers, none_selected,
    shrink_backends}`` — the same shape the building/room panel reads from
    /model3d/status, minus the img2mesh backend list (the props tab already
    carries that one)."""
    from app.core.props import get_model_info, get_prop
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    return get_model_info(prop_id)


@router.post("/props/{prop_id}/models/select")
async def prop_model_select(prop_id: str, request: Request) -> Dict[str, Any]:
    """Make a stored mesh the ACTIVE one of a resolution tier (body:
    {file, tier?}) — what the clients get via /assets/props/{id}/model?tier=.
    An empty {file} deselects: on the default tier nothing is rendered until
    another one is chosen/generated, on any other tier that tier ceases to
    exist."""
    from app.core.props import get_prop, select_model
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    data = await request.json()
    filename = str((data or {}).get("file") or "").strip()
    tier = _tier((data or {}).get("tier"))
    if not select_model(prop_id, filename, tier=tier):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"status": "success", "active": filename, "tier": tier}


@router.post("/props/{prop_id}/models/shrink")
async def prop_model_shrink(prop_id: str, request: Request) -> Dict[str, Any]:
    """Reduce a STORED mesh of the prop to a low variant (body: {file,
    backend?, face_num?, texture_size?}) via a mesh→mesh backend. The result
    is a NEW gallery file, always selected for tier ``low``. Background job —
    poll /world/props for pending. A source mesh without UVs/texture answers
    400 with the reason (it can never be reduced)."""
    from app.core.props import get_prop, model_file_path, trigger_shrink
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    body = _shrink_body(await request.json())
    if not model_file_path(prop_id, body["source_file"]):
        raise HTTPException(status_code=404, detail="Model not found")
    return _shrink_start(trigger_shrink, prop_id, **body)


@router.post("/props/{prop_id}/models/lod")
def prop_model_lod(prop_id: str, ratio: float = 0) -> Dict[str, Any]:
    """Build the prop's distance mesh from its full mesh on the CPU (Blender
    Decimate) — the "Build distance mesh" button.

    ``ratio`` is the target fraction of the triangle count (default: the
    configured one for props). The result is a NEW gallery file selected as
    ``low``; an existing low mesh stays stored and can be selected back."""
    from app.core.props import build_low_tier, get_prop
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    return _lod_result(build_low_tier, prop_id, ratio=ratio, kind="prop")


@router.delete("/props/{prop_id}/models")
def prop_model_delete(prop_id: str, file: str = "") -> Dict[str, Any]:
    """Remove ONE stored mesh (?file=<name>) or all of them (no param).
    Deleting a selected file re-points the selection."""
    from app.core.props import delete_model, get_prop
    if not get_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"status": "success", "removed": delete_model(prop_id, file.strip())}


@router.get("/props/{prop_id}/models/files/{filename}")
def prop_model_file(prop_id: str, filename: str, request: Request):
    """Serve ONE stored mesh by filename — the admin gallery previews
    non-active files with it (clients only ever see the selected ones)."""
    from app.core.http_files import etag_file_response
    from app.core.props import model_file_path
    p = model_file_path(prop_id, filename)
    if not p:
        raise HTTPException(status_code=404, detail="Model not found")
    return etag_file_response(p, request, "model/gltf-binary")


@router.delete("/props/{prop_id}")
def prop_delete(prop_id: str) -> Dict[str, Any]:
    """Delete a prop (model + source + sidecar) and every WORLD PLACEMENT of
    it (§ A9a).

    The placements go with it because they can never be repaired: a placement
    without a prop renders nothing, and leaving it would only keep a slot of
    the 500-cap busy for a mesh that no longer exists."""
    from app.core.props import delete_prop
    from app.models.world_props import delete_world_props_of
    if not delete_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"status": "deleted",
            "world_props_removed": delete_world_props_of(prop_id)}


# ── Room furnishing job ("✨ Furnish", plan-room-furnish.md) ──
# Thin adapters over app/core/room_furnish.py — the whole workflow is ONE
# persisted job per room, so every route either reads its status or pushes it
# through a transition. Job errors carry their own HTTP status.
# ``room_id`` is a plain room id — or, for a location's YARD (§ A13a), the
# composite ``__ground__@<location_id>``: the reserved ground id is the only
# one that is not unique across locations.


def _furnish_call(fn, *args) -> Dict[str, Any]:
    from app.core.room_furnish import FurnishError
    try:
        return fn(*args)
    except FurnishError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


async def _furnish_body(request: Request) -> Dict[str, Any]:
    if (request.headers.get("content-length") or "0") == "0":
        return {}
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@router.get("/rooms/{room_id}/furnish")
def furnish_status(room_id: str,
                   _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Status of the room's furnishing job: state, proposal, placements,
    error, progress (n/m over the new pieces), running/stalled. 404 = no job."""
    from app.core.room_furnish import get_status
    status = get_status(room_id)
    if not status:
        raise HTTPException(status_code=404, detail="No furnishing job for this room")
    return status


@router.post("/rooms/{room_id}/furnish/start")
async def furnish_start(room_id: str, request: Request,
                        _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Open a job and run stage 1 (furnish_select + furnish_new) in the
    background — body (optional): {exclude: {prop_ids, categories, keywords}}
    pre-filters what the LLM gets offered as available. 409 when the room has
    no layout (the yard: the location no drawn boundary) or a job is already
    open."""
    body = await _furnish_body(request)
    from app.core.room_furnish import start
    return _furnish_call(start, room_id, body.get("exclude"))


@router.post("/rooms/{room_id}/furnish/direct")
async def furnish_direct(room_id: str, request: Request,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Skip the LLM proposal and the generation: place ONLY admin-picked
    library props — body: {proposal: {existing: [{prop_id, count}]}}. The
    job enters at placement; review/accept as usual."""
    body = await _furnish_body(request)
    from app.core.room_furnish import start_direct
    return _furnish_call(start_direct, room_id, body.get("proposal") or body)


@router.post("/rooms/{room_id}/furnish/confirm")
async def furnish_confirm(room_id: str, request: Request,
                          _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Confirm the (edited) proposal — body: {proposal: {existing: [...],
    new: [...]}}, absent = the stored one. Starts generation + placement."""
    body = await _furnish_body(request)
    from app.core.room_furnish import confirm
    return _furnish_call(confirm, room_id, body.get("proposal"))


@router.post("/rooms/{room_id}/furnish/accept")
async def furnish_accept(room_id: str, request: Request,
                         _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Accept the proposed furnishing — body: {placements: [...]} (the ghost
    layer's CURRENT positions), absent = the solver's result. Appends to
    layout.props and closes the job."""
    body = await _furnish_body(request)
    from app.core.room_furnish import accept
    return _furnish_call(accept, room_id, body.get("placements"))


@router.post("/rooms/{room_id}/furnish/discard")
def furnish_discard(room_id: str,
                    _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Drop the job. Generated props stay in the library."""
    from app.core.room_furnish import discard
    return _furnish_call(discard, room_id)


@router.post("/rooms/{room_id}/furnish/reset")
def furnish_reset(room_id: str,
                  _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Throw away a stage-1 proposal so a new one can be requested."""
    from app.core.room_furnish import reset
    return _furnish_call(reset, room_id)


@router.post("/rooms/{room_id}/furnish/retry")
def furnish_retry(room_id: str,
                  _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Re-enter a failed job at its persisted state."""
    from app.core.room_furnish import retry
    return _furnish_call(retry, room_id)


@router.post("/rooms/{room_id}/furnish/continue")
def furnish_continue(room_id: str,
                     _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Continue a job whose orchestrator thread died with the server
    (status ``stalled``)."""
    from app.core.room_furnish import resume
    return _furnish_call(resume, room_id)


# ── Map Layout Import / Export ──

@router.get("/map/export")
def export_map_layout_route(
        _: Dict[str, Any] = Depends(require_admin)) -> StreamingResponse:
    """Stream a map-layout ZIP — where every location stands, in metres."""
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
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Apply a saved map layout. Matching is by id; ids this world does not
    have are reported as ``skipped_unknown`` and nothing is created."""
    from app.core.content_io import import_map_layout_from_zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    try:
        return import_map_layout_from_zip(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Location Import / Export ──

@router.get("/locations/{location_id}/export")
def export_location_route(location_id: str,
                          _: Dict[str, Any] = Depends(require_admin)) -> StreamingResponse:
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
    _: Dict[str, Any] = Depends(require_admin),
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
    return world_ops.list_condition_filters()


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
    bg_path = world_ops.resolve_background_path(location_name, room=room,
                                                hour=hour, file=file)
    if not bg_path or not bg_path.exists():
        raise HTTPException(status_code=404, detail="Kein Hintergrundbild vorhanden")
    suffix = bg_path.suffix.lower()
    media_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
    return FileResponse(
        str(bg_path),
        media_type=media_types.get(suffix, 'image/png'),
        headers={"Cache-Control": "no-cache"}
    )


@router.head("/locations/{location_name}/map-icon-2d")
@router.get("/locations/{location_name}/map-icon-2d")
def get_location_map_icon_2d(location_name: str):
    """Flat 2D map icon — per-cell choice via map_image_2d, else first 'map_2d'."""
    return world_ops._serve_map_icon(location_name, "map_2d", "map_image_2d")


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
    form = await request.form()
    file = form.get("file")
    room_id = (form.get("room_id") or "").strip() if isinstance(form.get("room_id"), str) else ""
    if not file:
        raise HTTPException(status_code=400, detail="file fehlt")

    return world_ops.save_uploaded_background(
        location_name, getattr(file, "filename", "") or "",
        await file.read(), room_id)


@router.post("/locations/{location_name}/background")
async def generate_location_background(location_name: str, request: Request) -> Dict[str, Any]:
    """Generiert ein Hintergrundbild fuer einen Ort per Image-Backend (per ID oder Name)."""
    try:
        data = await request.json()
        user_id = data.get("user_id", "").strip()
        custom_prompt = data.get("prompt", "").strip()
        return await world_ops.generate_location_background(location_name, custom_prompt)
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
        return world_ops.clear_location_backgrounds(location_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Location-Galerie ===

@router.get("/locations/{location_name}/gallery")
def get_location_gallery(
    location_name: str) -> Dict[str, Any]:
    """Listet alle Galerie-Bilder eines Ortes auf (mit Hintergrund-Status)."""
    return world_ops.build_gallery_payload(location_name)


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
    """Returns available image-generation backends (without character binding)."""
    return world_ops.build_imagegen_options()


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


@router.get("/compose-cache")
async def compose_cache_status(_u=Depends(require_admin)) -> Dict[str, Any]:
    """Size of the LLM prompt-compose cache (admin use-case editor)."""
    from app.core.prompt_compose_llm import cache_size
    return {"entries": cache_size()}


@router.post("/compose-cache/clear")
async def compose_cache_clear(_u=Depends(require_admin)) -> Dict[str, Any]:
    """Drop every cached LLM-composed prompt — the only way to make "Compose
    with AI" start over for prompts whose inputs did not change."""
    from app.core.prompt_compose_llm import clear_cache
    return {"status": "success", "cleared": clear_cache()}


@router.post("/compose-preview")
async def compose_preview(request: Request) -> Dict[str, Any]:
    """Composes the final render prompt WITHOUT generating anything.

    Body: { use_case?, prompt_type?, subject?, location_id, room_id?, backend }
    Returns: { prompt, negative, warnings, use_case }

    The render dialog prefills from here, so its prompt and the batch path
    come out of the same composer (app/core/prompt_compose.py) — including
    the use-case decision, which the client no longer guesses.
    """
    data = await request.json()
    # Into a thread: resolving the scale anchor may read the building GLB.
    return await asyncio.to_thread(world_ops.compose_preview_core, data)


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
    try:
        data = await request.json()
        batch_track_id = data.get("_batch_track_id", "")

        # Batch-Mode: synchron — Batch-Loop oben (``generate_gallery_batch``)
        # awaitet jeden Job. Hier rein in den Inner-Body, ohne Fire-and-Forget.
        if batch_track_id:
            return await world_ops.generate_gallery_image_core(location_name, data)

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
                await world_ops.generate_gallery_image_core(location_name, data)
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


@router.delete("/locations/{location_name}/gallery/{image_name}")
async def delete_gallery_image(
    location_name: str,
    image_name: str) -> Dict[str, Any]:
    """Loescht ein Galerie-Bild (per ID oder Name)."""
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")
    return world_ops.delete_gallery_image(location_name, image_name)


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
    return world_ops.toggle_gallery_background(location_name, image_name)


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
    return world_ops.assign_gallery_image_room(location_name, image_name, room_id)


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
    return world_ops.assign_gallery_image_type(location_name, image_name, image_type)


@router.post("/locations/{location_name}/gallery/{image_name}/time-variant")
async def generate_time_variant(
    location_name: str,
    image_name: str,
    request: Request) -> Dict[str, Any]:
    """Creates a day or night variant from an existing image via img2img (reference image).

    Uses a reference-capable image backend with the original image as reference.
    Body parameter 'target_type': 'night' (default) or 'day'.
    """
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

        return await world_ops.generate_time_variant_core(
            location_name, image_name, target_type=target_type,
            workflow_name=workflow_name, backend_name=backend_name,
            custom_prompt=custom_prompt)
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
    try:
        body = await request.json()
        user_id = body.get("user_id", "").strip()
        room_id = body.get("room_id", "").strip()
        value = body.get("value", False)
        return world_ops.set_location_prompt_changed(location_id, room_id, value)
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
    target = (body.get("target") or "").strip()  # backend-name glob, or empty = auto
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt missing")
    from app.core.messaging_frame import generate_frame
    result = await asyncio.to_thread(generate_frame, prompt, target)
    if result.get("status") != "ok":
        raise HTTPException(status_code=500, detail=result.get("error", "Generation failed"))
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
