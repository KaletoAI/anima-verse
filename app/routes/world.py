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
from app.core import world_ops

router = APIRouter(prefix="/world", tags=["world"])


# === Avatar-Movement (Direction-Pad) ===

@router.get("/avatar/neighbors")
def avatar_neighbors_route() -> Dict[str, Any]:
    """Liefert die Nachbar-Locations des Avatars in jede Himmelsrichtung.

    Response: { "north": {id, name} | null, "south": ..., "east": ..., "west": ... }
    Damit kann das Direction-Pad nicht-erreichbare Richtungen ausblenden,
    statt erst auf der 404-Antwort zu reagieren.
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
    """Flaches 2D-Karten-Icon — per-Zelle waehlbar via map_image_2d, sonst erstes 'map_2d'."""
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
        # Terrain-Hint nur, wenn das Backend ihn will (terrain_hint) — sonst beschreibt
        # der Prompt nur den Zielstil, der graue Canvas liefert den Kontext selbst.
        if _map_blend and not custom_prompt and getattr(backend, "terrain_hint", False):
            # Terrain-Analyse macht blockierende LLM-Submits (describe_map_tile,
            # bis zu einer pro Nachbarseite) → in einen Thread, damit die
            # Event-Loop frei bleibt. War die Ursache des Watchdog-Blocks.
            if edge_match:
                _ep = await asyncio.to_thread(world_ops._edge_transition_prompt, location, edge_sides)
                if _ep:
                    prompt = _ep
                    logger.info("Edge-Match Auto-Prompt: %s", _ep)
            else:
                _hint = await asyncio.to_thread(world_ops._neighbor_terrain_hint, location)
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
            _uc_name, getattr(backend, "image_family", "") or "",
            backend_model=getattr(backend, "model", "") or "")
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
        params: Dict[str, Any] = {"width": world_ops._location_image_width(), "height": world_ops._location_image_height()}
        if prompt_type == "map_2d":
            params["image_use_case"] = "map"
            # 2D-Map-Tiles quadratisch (1:1, Flux-native 1024) generieren statt
            # im 16:9 Location-Format — fuellt das Tile. Sonst Querformat.
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
        # Inpaint mask parameters come purely from the backend fields (no flag,
        # no per-model special casing). Only applies when the backend is an
        # inpaint backend (category=="inpaint").
        if getattr(backend, "category", "") == "inpaint":
            _grow = float(getattr(backend, "mask_grow", world_ops.MAP_BLEND_MASK_GROW_GRAY))
            _full = bool(getattr(backend, "full_mask", True))
            _inner = float(getattr(backend, "inner_crop", world_ops.MAP_FIT_INNER_CROP))
        else:
            _grow = world_ops.MAP_BLEND_MASK_GROW_FILL
            _full = False
            _inner = world_ops.MAP_FIT_INNER_CROP
        if edge_match:
            # GENAU zwei benachbarte Tiles, EINE Kante. Naht hart grau, Maske =
            # Streifen * mask_grow. Der Backend gibt EIN Bild zurueck — world.py
            # zerschneidet es mittig und legt beide Haelften in die Nachbar-Locations.
            _side = (edge_sides[0] if isinstance(edge_sides, (list, tuple)) and edge_sides
                     else (edge_sides if isinstance(edge_sides, str) else ""))
            _ep = world_ops._compose_edge_pair(location, _side, mask_grow=_grow)
            if _ep:
                _cpath, _mpath, _edge_pair = _ep
                params["image_use_case"] = "mapfit"  # 400-Cap umgehen: voller Output zum Zerschneiden
        elif fit_neighbors:
            _fit_comp = world_ops._compose_neighbor_canvas(location, crop_empty=True, mask_grow=_grow,
                                                 full_mask=_full, inner_crop=_inner)
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
                    if _crop.size != (world_ops.MAP_FIT_OUT_TILE, world_ops.MAP_FIT_OUT_TILE):
                        _crop = _crop.resize((world_ops.MAP_FIT_OUT_TILE, world_ops.MAP_FIT_OUT_TILE), _Img.LANCZOS)
                    _buf = _io.BytesIO()
                    _crop.save(_buf, format="PNG")
                    images = [_buf.getvalue()]
                    logger.info("Map-Fit: Mitte %s aus %dx%d -> %dpx", _box, _w, _h, world_ops.MAP_FIT_OUT_TILE)
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
        params = {"width": world_ops._location_image_width(), "height": world_ops._location_image_height()}

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
