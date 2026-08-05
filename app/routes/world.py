"""World routes - Orte und Aktivitaeten verwalten (User-Level)"""
import asyncio
import io
import os
from fastapi import (APIRouter, Request, HTTPException, Query, UploadFile,
                     File, Form, Depends)
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
from app.core import world_ops

router = APIRouter(prefix="/world", tags=["world"])


# === Avatar-Movement (Direction-Pad) ===

@router.get("/avatar/neighbors")
def avatar_neighbors_route() -> Dict[str, Any]:
    """Return the avatar's neighbor locations for each compass direction.

    Response: { "north": {id, name, may_leave} | null, "south": ..., "east":
    ..., "west": ... }. Lets the direction pad hide unreachable directions
    instead of reacting to the 404 response, and grey out exactly the ones
    the departure gate refuses (``may_leave``, the step route's own rule).
    """
    return world_ops.compute_avatar_neighbors()


@router.post("/avatar/step")
async def avatar_step_route(request: Request) -> Dict[str, Any]:
    """Bewegt den Avatar um einen Grid-Schritt in die angegebene Richtung.

    Body: { "direction": "north"|"south"|"east"|"west" }

    Sucht die Nachbar-Location anhand der Grid-Koordinaten der aktuellen
    Avatar-Position. Gibt 404 zurueck wenn dort keine Location liegt.
    """
    data = await request.json()
    direction = (data.get("direction") or "").strip().lower()
    return world_ops.move_avatar_step(direction)


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


@router.get("/game-time")
async def get_game_time() -> Dict[str, Any]:
    """Game clock info: both nows, anchors, factor, frozen (for the header
    clock — the frontend ticks locally from the anchors)."""
    from app.core.timeutils import get_game_clock_info
    return get_game_clock_info()


@router.post("/game-time")
async def post_game_time(
    request: Request,
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Sets game time and/or tick factor. Body: {game_time?: ISO, factor?: number}."""
    from app.core.timeutils import (get_game_clock_info, parse_iso,
                                    set_game_factor, set_game_time)
    data = await request.json()
    raw_time = (data.get("game_time") or "").strip() if isinstance(data.get("game_time"), str) else ""
    raw_factor = data.get("factor")
    if not raw_time and raw_factor is None:
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
    if raw_time:
        try:
            set_game_time(parse_iso(raw_time))
        except ValueError:
            raise HTTPException(status_code=400, detail="game_time must be an ISO datetime")
    info = get_game_clock_info()
    logger.info("Game time set: game_now=%s factor=%s",
                info["game_now"], info["factor"])
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
    """Gibt Welt-Settings + Pose-Settings zurueck."""
    return world_ops.build_world_settings_payload()


@router.put("/settings")
async def put_world_settings(request: Request) -> Dict[str, Any]:
    """Setzt Welt-Settings + Pose-Settings."""
    data = await request.json()
    return world_ops.apply_world_settings(data)


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


# The former /model3d/floors and /model3d/height endpoints are gone
# (2026-07-28): both existed to squash a building model in Y. A model is
# scaled by ONE factor on all three axes now (map3d.size × map3d.extent_m),
# and the storey height is a location dial in real metres
# (map3d.storey_height_m).


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
    final prompt before generating (final-prompt rule)."""
    from app.core.surface_textures import (admin_list, compose_prompt,
                                            is_pending)
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    backends = []
    try:
        for b in svc.list_available_backends(media="image"):
            style = compose_prompt("", b)
            backends.append({"name": b.name,
                             "prompt_style": style["style"],
                             "prompt_negative": style["negative"]})
    except Exception:
        pass
    from app.core.surface_textures import get_blends
    # No `subjects` map any more: the description is a plain field on the
    # kind (admin_list), and it is the only text that reaches a prompt. The
    # curated wording is seeded INTO that field when a kind is created, so
    # there is nothing left for the dialog to merge.
    return {"textures": admin_list(), "pending": is_pending(),
            "backends": backends, "blends": get_blends()}


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
    """Make a stored version the ACTIVE one (body: {file}) — the one the
    3D client gets via /assets/surface-textures."""
    from app.core.surface_textures import select_texture
    data = await request.json()
    if not isinstance(data, dict) or not select_texture(
            kind, str(data.get("file") or "").strip()):
        raise HTTPException(status_code=404, detail="No such texture version")
    return {"status": "ok"}


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


@router.get("/props")
def props_admin() -> Dict[str, Any]:
    """Admin listing: all props (full sidecar detail) + running generations +
    the available backends. ``image_backends`` carry their resolved ``prop``
    use-case style so the dialog can show and edit the COMPLETE final source
    prompt (final-prompt rule); ``mesh_backends`` are the rig-'none' img2mesh
    aliases."""
    from app.core.props import compose_prompt, is_pending, list_props
    from app.core.model3d import list_mesh_backends
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    image_backends = []
    try:
        for b in svc.list_available_backends(media="image"):
            style = compose_prompt("", b)
            image_backends.append({"name": b.name,
                                   "prompt_style": style["style"],
                                   "prompt_negative": style["negative"]})
    except Exception:
        pass
    return {"props": list_props(full=True), "pending": is_pending(),
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
    """Update the editable sidecar fields (body: {name?, category?, width_m?,
    depth_m?, height_m?, tags?}). Patching a dim marks the prop's dims as
    admin-set — they are never redistributed from the mesh again."""
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
    """Delete a prop (model + source + sidecar)."""
    from app.core.props import delete_prop
    if not delete_prop(prop_id):
        raise HTTPException(status_code=404, detail="Prop not found")
    return {"status": "deleted"}


# ── Room furnishing job ("✨ Furnish", plan-room-furnish.md) ──
# Thin adapters over app/core/room_furnish.py — the whole workflow is ONE
# persisted job per room, so every route either reads its status or pushes it
# through a transition. Job errors carry their own HTTP status.


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
    no layout, the location no scale anchor or a job is already open."""
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


@router.head("/locations/{location_name}/map-patch-2d")
@router.get("/locations/{location_name}/map-patch-2d")
def get_location_map_patch_2d(location_name: str):
    """Multi-tile map patch anchored at this cell (map_patch_2d) — no fallback."""
    return world_ops._serve_map_patch(location_name)


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


@router.patch("/locations/{location_id}/map-patch")
async def set_location_map_patch_route(location_id: str, request: Request) -> Dict[str, Any]:
    """Set/clear the 3x3 map patch anchored at this cell.

    Body: ``{"file": "<gallery-filename>"|"", "span": 3}``. The image must be
    in the owner gallery (the template's for clones). Setting the patch turns
    the own tile image of every covered same-template cell off
    (``map_image_off``), clearing turns them back on — ``affected`` lists the
    toggled cell ids so the UI can report/refresh them.
    """
    from app.models.world import set_location_map_patch, _gallery_owner_id, get_gallery_dir
    data = await request.json()
    filename = (data.get("file") or "").strip()
    try:
        span = int(data.get("span") or 3)
    except (TypeError, ValueError):
        span = 3
    if filename:
        if "/" in filename or ".." in filename:
            raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")
        owner = _gallery_owner_id(location_id) or location_id
        if not (get_gallery_dir(owner) / filename).exists():
            raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    res = set_location_map_patch(location_id, filename, span)
    if not res:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    return {"status": "success", **res}


@router.patch("/locations/{location_id}/map-image-off")
async def set_location_map_image_off_route(location_id: str, request: Request) -> Dict[str, Any]:
    """Per-cell toggle: ``{"off": true}`` hides the cell's own 2D tile (no
    first-image fallback either) so an underlying multi-tile patch shows;
    ``false`` restores it."""
    from app.models.world import set_location_map_image_off
    data = await request.json()
    loc = set_location_map_image_off(location_id, bool(data.get("off")))
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
    return {"prompt": world_ops._neighbor_terrain_hint(loc)}


@router.get("/locations/{location_name}/fit-canvas")
def get_location_fit_canvas(location_name: str):
    """Vorschau des 3×3-Nachbar-Canvas, der bei „Fit to neighbors" als
    input_reference_image in den Workflow geht (Mitte grau = wird inpaintet).
    404 wenn keine Nachbarn mit Tile / keine Grid-Position."""
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    data = world_ops.build_fit_canvas_png(loc)
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@router.get("/locations/{location_name}/edges")
def get_location_edges(location_name: str) -> Dict[str, Any]:
    """Welche der 4 Seiten haben einen Nachbarn mit 2D-Tile (fuer den Kanten-
    Angleich-Dialog): {sides: {north: "<name>", east: "<name>", ...}}."""
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    return {"sides": {s: nb.get("name", "") for s, nb in world_ops._neighbor_sides(loc).items()}}


@router.get("/locations/{location_name}/edge-prompt")
def get_location_edge_prompt(location_name: str, sides: str = Query("")) -> Dict[str, Any]:
    """Dynamischer Uebergangs-Prompt fuer „Kanten angleichen" — aus den gewaehlten
    Seiten (kommagetrennt; leer = alle vorhandenen). Im Dialog editierbar."""
    loc = resolve_location(location_name)
    if not loc:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    _sides = [s.strip() for s in sides.split(",") if s.strip()] or None
    return {"prompt": world_ops._edge_transition_prompt(loc, _sides)}


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
