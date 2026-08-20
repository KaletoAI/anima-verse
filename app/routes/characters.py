"""Character routes - Character management, images, and profile"""
import io
import os
import time
import mimetypes
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from typing import Dict, Any, List, Optional
from app.core.auth_dependency import require_admin
from app.core.http_files import etag_file_response
from app.core.log import get_logger

logger = get_logger("characters")

from app.models.character import (
    list_available_characters,
    generate_random_appearance,
    get_character_appearance,
    get_character_current_location,
    save_character_current_location,
    get_effective_activity,
    set_pose_intent,
    clear_pose_intent,
    get_character_current_feeling,
    save_character_current_feeling,
    get_character_outfits,
    add_character_outfit,
    delete_character_outfit,
    update_outfit_image,
    get_character_dir,
    get_character_images_dir,
    add_character_image,
    get_character_images,
    get_character_image_comments,
    add_character_image_comment,
    get_character_image_prompts,
    get_character_image_metadata,
    get_character_profile_image,
    set_character_profile_image,
    delete_character,
    delete_character_image,
    cleanup_orphaned_images,
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
from app.core.dependencies import reload_skill_manager, get_skill_manager

from app.core.timeutils import utc_now, utc_now_iso

router = APIRouter(prefix="/characters", tags=["characters"])


@router.get("/available-models")
def get_available_models() -> Dict[str, Any]:
    """Lists available models from all configured providers.

    Returns model lists grouped by provider, plus current task defaults.
    Used by the frontend for per-character model selection dropdowns.
    """
    return character_ops.build_available_models()


@router.get("/list")
def list_characters() -> Dict[str, Any]:
    """Listet alle verfuegbaren Characters (NPCs im System — nicht gefiltert).

    Avatar-Auswahl (wer der User spielen KANN) laeuft ueber /account/characters
    und ist dort nach allowed_characters gefiltert.
    """
    return {"characters": list_available_characters()}


@router.get("/at-location")
def characters_at_location(location: str, room: str = "") -> Dict[str, Any]:
    """Gibt alle Characters zurueck die sich am angegebenen Ort befinden.

    - `location`: ID oder Name der Location.
    - `room` (optional): wenn gesetzt, bekommen Characters ein `same_room`-
      Flag (true wenn sie in genau diesem Raum sind). Es wird **nicht**
      gefiltert — Frontend kann ausgegraut darstellen wer in einem anderen
      Raum derselben Location ist.
    """
    return character_ops.build_characters_at_location(location, room)


@router.get("/chatbots")
def list_chatbots() -> Dict[str, Any]:
    """Listet alle Chatbots (Characters ohne Location-System).

    Ein Chatbot ist ein Character dessen Template `locations_enabled: false`
    hat — er hat keine Weltposition und ist immer ansprechbar.
    """
    return character_ops.build_chatbots_list()


@router.get("/animate/services")
async def list_animate_services() -> List[Dict[str, Any]]:
    """Liefert die verfuegbaren Animation-Services fuer das Frontend."""
    from app.skills.animate import get_animate_services
    return get_animate_services()


@router.post("/create")
async def create_character(request: Request) -> Dict[str, Any]:
    """Erstellt einen neuen Character mit leerem Profil und zugewiesenem Template"""
    try:
        return await character_ops.create_character_core(request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/generate-appearance")
def generate_character_appearance(character_name: str) -> Dict[str, Any]:
    """Generiert ein zufaelliges Aussehen"""
    appearance = generate_random_appearance()
    return {"character": character_name, "appearance": appearance}


@router.get("/{character_name}/profile-image-prompt")
def profile_image_prompt(character_name: str) -> Dict[str, Any]:
    """Aufgeloester Face Prompt als Default-Prompt fuer den Profilbild-Dialog
    (identisch zum Fallback in generate-profile-image)."""
    from app.models.character import get_character_profile
    from app.models.character_template import get_template
    profile = get_character_profile(character_name) or {}
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    return {"prompt": character_ops._resolve_face_prompt(profile, character_name, tmpl)}


@router.get("/{character_name}/current-location")
def get_character_current_location_route(character_name: str) -> Dict[str, Any]:
    """Gibt den aktuellen virtuellen Aufenthaltsort zurueck"""
    return character_ops.build_current_location_payload(character_name)


@router.get("/{character_name}/notice")
def get_character_notice_route(character_name: str) -> Dict[str, Any]:
    """Liefert die persistenten Hinweise fuer den Avatar-Header-Banner.

    - ``force_warning``: aktive Force-Regel (rule_name + message + go_to + set_activity)
      ODER ``None``. Fuer den Avatar wird die Regel NICHT automatisch ausgefuehrt.
    - ``critical_events``: ungeloeste Events der Kategorien ``disruption``/``danger``
      an der aktuellen Avatar-Location, neueste zuerst.
    """
    return character_ops.build_character_notice(character_name)


@router.post("/{character_name}/current-location")
async def update_character_current_location(character_name: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert den aktuellen virtuellen Aufenthaltsort"""
    try:
        return await character_ops.apply_current_location(character_name, request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/place-on-map")
async def place_character_on_map(character_name: str, request: Request) -> Dict[str, Any]:
    """Drag&Drop-Platzierung: setzt current_location UND fuegt die Location
    in die known_locations-Liste des Characters ein. Damit aktiviert der erste
    Drop strict-mode (Listen-basierte Sichtbarkeit) — bis dahin ist der
    Character auf Legacy-Verhalten (knowledge_item-Gating only).
    """
    try:
        return await character_ops.apply_place_on_map(character_name, request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/current-activity")
def get_effective_activity_route(character_name: str) -> Dict[str, Any]:
    """Gibt die aktuelle Aktivitaet zurueck"""
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
        await _aio.to_thread(set_pose_intent, character_name, activity)

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
    """Gibt das aktuelle Gefuehl zurueck"""
    feeling = get_character_current_feeling(character_name)
    return {"character": character_name, "current_feeling": feeling or ""}


@router.post("/{character_name}/current-feeling")
async def update_character_current_feeling(character_name: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert das aktuelle Gefuehl"""
    try:
        data = await request.json()
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
    """Gibt die aktuellen Status-Werte eines Characters zurueck.

    Beim ersten Aufruf: Initialisiert status_effects aus Trait-Defaults
    und persistiert sie im Profil. Danach werden immer die gespeicherten
    Werte zurueckgegeben.
    """
    try:
        return character_ops.build_status_effects(character_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Template-Wechsel ===

@router.post("/{character_name}/switch-template")
async def switch_template_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Template-Wechsel mit Diff: Zeigt neue/wegfallende Felder und fuehrt Migration durch.

    mode="diff": Gibt nur den Diff zurueck (keine Aenderung)
    mode="apply": Fuehrt den Wechsel durch (neue Defaults setzen, alte Felder loeschen)
    """
    try:
        data = await request.json()
        return character_ops.apply_template_switch(character_name, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Erlaubte Orte ===

@router.get("/{character_name}/home-location")
def get_home_location_route(
    character_name: str) -> Dict[str, Any]:
    """Gibt Home-Location und Home-Room eines Characters zurueck."""
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
    """Speichert Home-Location und Home-Room eines Characters."""
    try:
        data = await request.json()
        user_id = data.get("user_id", "").strip()
        if not character_name:
            raise HTTPException(status_code=400, detail="user_id und character_name fehlen")
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
def get_outfit_lora_options(character_name: str = "") -> Dict[str, Any]:
    """Returns the LoRA list for the outfit-piece editor.

    Response:
        loras: [{name, missing}] from the LoRA library, scoped to the backend
        the outfit/variant render would resolve (no 'None' entry).
    """
    from app.imagegen.service import get_image_service
    imagegen = get_image_service()
    if not imagegen.enabled:
        return {"loras": []}

    # LoRA-library entries for the backend that the VARIANT/OUTFIT generation
    # would actually resolve for this character — mirror of the chain in
    # expression_regen: per-character match glob (outfit_imagegen.workflow)
    # → expression/outfit default spec → cheapest enabled agent backend.
    # Without this, the Add-LoRA list ignored the page's "Backend match".
    try:
        import os as _os
        from app.core.config import get_lora_options
        from app.imagegen.service import render_has_reference_image
        # These are outfit/variant renders: they pin the profile image as
        # identity reference. Resolve the SAME img2img preference the render
        # applies (from the profile image), so this LoRA list matches the
        # backend that will actually run.
        _has_ref = render_has_reference_image(character_name)
        eff = None
        if character_name:
            try:
                from app.models.character import get_character_profile
                _ovr = (get_character_profile(character_name) or {}).get("outfit_imagegen") or {}
                _glob = (_ovr.get("workflow") or "").strip() if isinstance(_ovr, dict) else ""
                if _glob:
                    eff = imagegen.match_backend(_glob, has_input_image=_has_ref)
            except Exception:
                eff = None
        if not eff:
            _default = (_os.environ.get("EXPRESSION_IMAGEGEN_DEFAULT", "").strip()
                        or _os.environ.get("OUTFIT_IMAGEGEN_DEFAULT", "").strip())
            if _default:
                eff = imagegen.resolve_imagegen_target(_default)
        if not eff and character_name:
            eff = imagegen._select_backend_for_agent(character_name,
                                                     has_input_image=_has_ref)
        lib_options = get_lora_options(
            eff.name if eff else "",
            lora_filter=(getattr(eff, "lora_filter", "") or "") if eff else "")
    except Exception:
        lib_options = []

    return {"loras": lib_options}


@router.get("/outfit-rules")
def get_outfit_rules_route() -> Dict[str, Any]:
    """Deprecated: outfit_types-Regeln durch Decency ersetzt (Variante A).
    Liefert leer, damit alte UI-Fetches kein 404 sehen."""
    return {"outfit_types": {}}


@router.get("/{character_name}/decency-preference")
def get_decency_preference(character_name: str) -> Dict[str, Any]:
    """Liefert die free-text decency_preference des Characters (Stil-Hinweis,
    ersetzt das alte outfit_exceptions-Modell)."""
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    return {"character": character_name,
            "decency_preference": profile.get("decency_preference", "") or ""}


@router.put("/{character_name}/decency-preference")
async def set_decency_preference(character_name: str, request: Request) -> Dict[str, Any]:
    """Speichert die free-text decency_preference (z.B. "often barefoot, no
    underwear"). Reiner Stil-Hinweis fuer die Outfit-Erstellung — Bedeckung
    entscheidet Decency."""
    from app.models.character import get_character_profile, save_character_profile
    body = await request.json()
    pref = str((body or {}).get("decency_preference") or "").strip()
    profile = get_character_profile(character_name) or {}
    if pref:
        profile["decency_preference"] = pref
    else:
        profile.pop("decency_preference", None)
    save_character_profile(character_name, profile)
    return {"status": "ok", "character": character_name, "decency_preference": pref}


@router.post("/{character_name}/clear-expression-cache")
def clear_expression_cache_route(character_name: str) -> Dict[str, Any]:
    """Deletes every cached expression image of this character. They are
    re-rendered on demand; the key space is bounded by the pose/expression
    catalogs. The world-wide variant lives in ``poses.py``."""
    from app.core.expression_regen import clear_expression_cache
    count = clear_expression_cache(character_name)
    return {"status": "ok", "character": character_name, "deleted": count}


@router.get("/{character_name}/outfits")
def get_character_outfits_route(character_name: str) -> Dict[str, Any]:
    """Gibt alle definierten Outfits zurueck"""
    outfits = get_character_outfits(character_name)
    return {"character": character_name, "outfits": outfits}


@router.post("/{character_name}/outfits")
async def add_character_outfit_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Fuegt ein neues Outfit hinzu oder aktualisiert ein bestehendes.

    Akzeptiert neues Format: {user_id, id?, name, outfit, locations[], activities[]}
    """
    try:
        data = await request.json()
        user_id = data.get("user_id", "")

        outfit_data = {
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "outfit": data.get("outfit", ""),
            "pieces": data.get("pieces", []),
            "remove_slots": data.get("remove_slots", []),
            "pieces_colors": data.get("pieces_colors", {}),
            "locations": data.get("locations", []),
            "activities": data.get("activities", []),
            "excluded_locations": data.get("excluded_locations", []),
        }

        outfit_id = add_character_outfit(character_name, outfit_data)
        return {"status": "success", "character": character_name, "id": outfit_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{character_name}")
async def delete_character_route(character_name: str) -> Dict[str, Any]:
    """Loescht einen Character vollstaendig (DB + Storage-Verzeichnis)."""
    if not character_name:
        raise HTTPException(status_code=400, detail="character_name fehlt")
    success = delete_character(character_name)
    if not success:
        raise HTTPException(status_code=404,
                            detail=f"Character '{character_name}' nicht gefunden oder geschuetzt")
    return {"status": "success", "deleted": character_name}


@router.delete("/{character_name}/outfits")
async def delete_character_outfit_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Loescht ein Outfit per ID."""
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        outfit_id = data.get("id", "")
        if not outfit_id:
            raise HTTPException(status_code=400, detail="id fehlt")

        success = delete_character_outfit(character_name, outfit_id=outfit_id)
        if success:
            return {"status": "success", "character": character_name, "id": outfit_id}
        else:
            raise HTTPException(status_code=404, detail="Outfit nicht gefunden")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/generate-profile-image")
async def generate_profile_image_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Generates a new profile image via the core image service."""
    return await character_ops.generate_profile_image_core(character_name, request)


@router.get("/{character_name}/outfits/{outfit_id}/image-prompt")
async def get_outfit_image_prompt(character_name: str, outfit_id: str) -> Dict[str, str]:
    """Berechnet den Prompt fuer ein Outfit-Bild (Vorschau fuer Dialog)."""

    outfits = get_character_outfits(character_name)
    outfit_obj = next((o for o in outfits if o.get("id") == outfit_id), None)
    if not outfit_obj:
        raise HTTPException(status_code=404, detail="Outfit nicht gefunden")

    outfit_description = outfit_obj.get("outfit", "")
    from app.models.character_template import resolve_profile_tokens, get_template
    profile = get_character_profile(character_name)
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    if outfit_description and "{" in outfit_description:
        outfit_description = resolve_profile_tokens(outfit_description, profile, template=tmpl, target_key="outfit")

    return {"prompt": character_ops._build_outfit_image_prompt(character_name, outfit_description)}


@router.post("/{character_name}/outfits/{outfit_id}/generate-image")
async def generate_outfit_image_route(character_name: str, outfit_id: str, request: Request) -> Dict[str, Any]:
    """Generates an outfit image via the core image service."""
    return await character_ops.generate_outfit_image_core(character_name, outfit_id, request)


@router.post("/{character_name}/outfits/generate-all-images")
async def generate_all_outfit_images_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Generiert Bilder fuer alle Outfits eines Characters (Bulk, im Hintergrund).

    Verwendet die gleiche Pipeline wie generate_outfit_image_route,
    aber fuer jedes Outfit einzeln. Laeuft im Hintergrund ueber die Task-Queue.
    """
    import threading
    data = await request.json()
    user_id = data.get("user_id", "")

    outfits = get_character_outfits(character_name)
    if not outfits:
        return {"status": "error", "detail": "Keine Outfits vorhanden"}

    # Einstellungen aus Dialog (ohne Prompt — wird pro Outfit berechnet)
    workflow_name = data.get("workflow", "").strip()
    backend_name = data.get("backend", "").strip()
    loras_override = data.get("loras")
    model_override = data.get("model_override", "").strip()

    # Outfits mit Beschreibung filtern
    eligible = [o for o in outfits if o.get("outfit", "").strip()]
    if not eligible:
        return {"status": "error", "detail": "Keine Outfits mit Beschreibung vorhanden"}

    logger.info("Bulk Outfit-Bild Generierung: %s, %d Outfits", character_name, len(eligible))

    threading.Thread(
        target=character_ops.generate_all_outfit_images_worker,
        args=(character_name, eligible, workflow_name, backend_name, loras_override, model_override),
        daemon=True, name=f"bulk-outfit-{character_name}").start()
    return {"status": "started", "count": len(eligible)}


@router.get("/{character_name}/current-outfit")
def get_current_outfit_route(character_name: str) -> Dict[str, Any]:
    """Gibt das aktuelle Outfit basierend auf Location und Activity zurueck"""
    from app.models.world import get_location_name as _get_loc_name
    from app.models.character import get_character_current_room
    from app.core.outfit_renderer import render_outfit
    outfit = (render_outfit(character_name=character_name).get("full", "") or "").removeprefix("wearing: ")
    current_location_id = get_character_current_location(character_name)
    current_activity = get_effective_activity(character_name)
    current_room = get_character_current_room(character_name)
    return {
        "character": character_name,
        "current_outfit_description": outfit or "",
        "current_location": _get_loc_name(current_location_id) if current_location_id else "",
        "current_location_id": current_location_id or "",
        "current_activity": current_activity or "",
        "current_room": current_room or "",
    }


@router.post("/{character_name}/current-outfit/refresh")
async def refresh_current_outfit(character_name: str, request: Request) -> Dict[str, Any]:
    """Decency-Compliance auf den Char anwenden und Outfit-Beschreibung zurueckliefern."""
    from app.core.outfit_compliance import apply_outfit_compliance
    from app.core.outfit_renderer import render_outfit
    result = apply_outfit_compliance(character_name)
    outfit_text = render_outfit(character_name=character_name).get("full", "")
    return {"character": character_name,
            "current_outfit_description": outfit_text,
            "compliance": result}


@router.get("/{character_name}/outfit-lock")
def get_outfit_lock_route(character_name: str) -> Dict[str, Any]:
    """Gibt den Sperrstatus des Outfits zurueck."""
    from app.models.character import is_outfit_locked
    return {"character": character_name, "locked": is_outfit_locked(character_name)}


@router.post("/{character_name}/outfit-lock")
async def set_outfit_lock_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Setzt/entfernt die Outfit-Sperre (blockiert Auto-Outfit-Aenderungen)."""
    from app.models.character import set_outfit_locked, is_outfit_locked
    data = await request.json()
    user_id = data.get("user_id", "").strip()
    locked = bool(data.get("locked"))
    set_outfit_locked(character_name, locked)
    return {"character": character_name, "locked": is_outfit_locked(character_name)}


@router.get("/{character_name}/decency-exempt")
def get_decency_exempt_route(character_name: str) -> Dict[str, Any]:
    """Gibt den decency_exempt-Status zurueck (Decency-Override auf nude_ok)."""
    from app.models.character import get_state_flags
    return {"character": character_name,
            "exempt": bool(get_state_flags(character_name).get("decency_exempt"))}


@router.post("/{character_name}/decency-exempt")
async def set_decency_exempt_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Setzt/entfernt decency_exempt. Gesetzt = Decency-Regeln aufgehoben
    (nude_ok), unabhaengig von Anwesenheit. Compliance reagiert sofort."""
    from app.models.character import set_decency_exempt, get_state_flags
    data = await request.json()
    exempt = bool(data.get("exempt"))
    set_decency_exempt(character_name, exempt)
    try:
        from app.core.outfit_compliance import apply_outfit_compliance
        apply_outfit_compliance(character_name)
    except Exception:
        pass
    return {"character": character_name,
            "exempt": bool(get_state_flags(character_name).get("decency_exempt"))}


@router.get("/{character_name}/default-outfit")
def get_default_outfit_route(character_name: str) -> Dict[str, Any]:
    """Gibt das Default-Outfit zurueck"""
    from app.models.character import get_character_default_outfit
    outfit = get_character_default_outfit(character_name)
    return {"character": character_name, "default_outfit": outfit or ""}


@router.post("/{character_name}/default-outfit")
async def update_default_outfit(character_name: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert das Default-Outfit"""
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        outfit = data.get("default_outfit", "")

        from app.models.character import save_character_default_outfit
        save_character_default_outfit(character_name, outfit)
        return {"status": "success", "character": character_name, "default_outfit": outfit}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Expression Image (mood + pose variants) ---

@router.get("/{character_name}/outfit-expression")
def get_outfit_expression(character_name: str, mood: str = "", pose_key: str = "",
                          pieces: str = "", items: str = "",
                          piece_colors: str = "",
                          override: int = 0, trigger: int = 0, force: int = 0,
                          fallback: str = ""):
    """Returns the expression/pose variant for current mood + pose + equipped.

    Variant = character appearance + worn items (pieces + equipped items) +
    pose (from the pose CATALOG KEY, default when empty) + expression (from
    the mood, resolved to its catalog key). The cache key does not depend on
    an outfit object — there is no base outfit image any more.

    Query params:
        pose_key: Optional pose catalog key (see /poses). Empty = the
                character's effective pose key; an unknown key falls back to
                the catalog default.
        pieces: Optional "slot1:itemId1,slot2:itemId2" — overrides the
                really equipped piece state (e.g. a wardrobe preview of a set
                that is not worn yet).
        items: Optional "id1,id2" — overrides equipped_items.
        override: 1 forces the use of pieces/items even when empty
                  (= "empty equipped state"); without override, empty
                  pieces/items mean "not supplied" and the real state is
                  loaded from the profile.
        fallback: "default" — when no variant is cached (but a generation is
                  running), a placeholder image is returned (200 instead of
                  202) so the frontend shows something sensible until the real
                  variant is ready.

    Responses: 200 with the image, 202 while a generation runs, 404 on
    failure / when no generator is available.
    """
    from app.core.expression_regen import (
        get_cached_expression, trigger_expression_generation, is_generating, has_failed)

    # Mood/pose: when not passed explicitly, take the character state as the
    # default — so the frontend finds the variant cache that matches
    # chat/scheduler. Override mode allows empty params (a set preview is
    # generic).
    _is_override = bool(override or pieces or items or piece_colors)
    if not _is_override:
        if not mood:
            try:
                from app.models.character import get_character_current_feeling
                mood = get_character_current_feeling(character_name) or ""
            except Exception:
                mood = ""
        if not pose_key:
            try:
                # Effective pose key (B1): mirrors the is_sleeping flag → a
                # sleeping character gets the sleeping pose/expression, in
                # step with _expr_version in /play/scene.
                from app.models.character import get_effective_pose_key
                pose_key = get_effective_pose_key(character_name) or ""
            except Exception:
                pose_key = ""

    # Equipped-State: Override-Params haben Prioritaet, sonst Real-State aus Profil.
    # Override-Modus ist read-only: es wird nur im Cache gesucht, keine Generierung
    # getriggert — Vorschau-Flows (z.B. Set-Durchschalten in der Garderobe) sollen
    # nicht massenweise Generierungen anstossen.
    _eq_pieces: Optional[Dict[str, str]] = None
    _eq_items: Optional[List[str]] = None
    _eq_meta: Optional[Dict[str, Dict[str, Any]]] = None
    if _is_override:
        _eq_pieces = {}
        for pair in pieces.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            slot, iid = pair.split(":", 1)
            slot, iid = slot.strip(), iid.strip()
            if slot and iid:
                _eq_pieces[slot] = iid
        _eq_items = [s.strip() for s in items.split(",") if s.strip()]
        # piece_colors: "slot:color,slot:color" — nur fuer Slots die auch in pieces sind
        _eq_meta = {}
        for pair in piece_colors.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            slot, color = pair.split(":", 1)
            slot, color = slot.strip(), color.strip()
            if slot and color and slot in _eq_pieces:
                _eq_meta[slot] = {"color": color}
    else:
        try:
            from app.models.inventory import get_equipped_pieces, get_equipped_items
            _eq_pieces = get_equipped_pieces(character_name)
            _eq_items = get_equipped_items(character_name)
            # equipped_pieces_meta (Farb-Override) wurde in Schritt 3 abgeschafft.
            _eq_meta = None
        except Exception:
            _eq_pieces, _eq_items, _eq_meta = None, None, None

    # Check cache
    cached = get_cached_expression(character_name, mood, pose_key,
                                    equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                                    equipped_pieces_meta=_eq_meta)
    if cached and force:
        # Force-Regenerate: gecachtes PNG + Sidecar loeschen, damit der
        # folgende Trigger-Pfad die Variant neu erzeugt.
        try:
            cached.unlink()
            _sidecar = cached.with_suffix(".json")
            if _sidecar.exists():
                _sidecar.unlink()
            logger.info("Force-Regenerate Expression: %s", cached.name)
        except OSError as e:
            logger.warning("Force-Regenerate konnte Cache nicht loeschen: %s", e)
        cached = None
    if cached:
        media_type = mimetypes.guess_type(str(cached))[0] or "image/png"
        return FileResponse(
            path=str(cached),
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"})

    # Helper: fallback image while the requested variant is not ready yet.
    # The profile image is NEVER an option — that is the roster avatar, not a
    # scene. Order:
    #   1) The variant with the MOST SIMILAR outfit combination (equal
    #      expression key as tie-break) — covers the default variant of the
    #      same outfit as well.
    #   2) The default variant (mood="" + pose_key="", i.e. the catalog
    #      defaults) with the current equipped state — only bites when
    #      sidecars record no outfit.
    #   3) The newest expression variant of the character, whatever it shows.
    # If all of that is missing: None → the caller answers 202 (generation
    # running) and the frontend keeps polling until the real variant lands.
    def _serve_fallback():
        from app.core.expression_regen import (_get_expressions_dir, _safe_name,
                                               find_nearest_expression)

        def _serve_file(path, status):
            media_type = mimetypes.guess_type(str(path))[0] or "image/png"
            return FileResponse(
                path=str(path),
                media_type=media_type,
                headers={
                    "Cache-Control": "no-cache",
                    "X-Variant-Status": status,
                })

        # 1) Nearest outfit variant (app/core/outfit_match.py)
        try:
            nearest = find_nearest_expression(character_name, mood,
                                              _eq_pieces, _eq_items)
        except Exception:
            nearest = None
        if nearest is not None:
            return _serve_file(nearest, "fallback-nearest")

        # 2) Default variant: same equipped state, mood + pose key empty
        try:
            default_cached = get_cached_expression(
                character_name, "", "",
                equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                equipped_pieces_meta=_eq_meta,
            )
        except Exception:
            default_cached = None
        if default_cached and default_cached.exists():
            return _serve_file(default_cached, "fallback-default")

        # 3) Newest expression variant of the character, whatever it is
        try:
            expr_dir = _get_expressions_dir(character_name)
            prefix = _safe_name(character_name)
            candidates = []
            if expr_dir.exists():
                for ext in ("*.png", "*.jpg", "*.webp"):
                    candidates.extend(expr_dir.glob(f"{prefix}_{ext}"))
            if candidates:
                newest = max(candidates, key=lambda p: p.stat().st_mtime)
                return _serve_file(newest, "fallback-variant-any")
        except Exception:
            pass

        # NO profile-image fallback — better nothing than the wrong image.
        return None

    _want_fallback = (fallback or "").strip().lower() == "default"

    # Override-Modus: per default nur Cache lesen. Mit trigger=1 wird die
    # Generierung fuer genau diese Equipped-Kombination explizit angestossen
    # (z.B. Wardrobe-Vorschau-Button, der fuer das ausgewaehlte Set die
    # Variant vorberechnen soll ohne vorher anzuziehen).
    if _is_override and not trigger:
        if is_generating(character_name, mood, pose_key,
                         equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                         equipped_pieces_meta=_eq_meta):
            if _want_fallback:
                fb = _serve_fallback()
                if fb is not None:
                    return fb
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=202,
                content={"status": "generating", "mood": mood, "pose_key": pose_key})
        raise HTTPException(status_code=404, detail="Keine Variant im Cache")

    if has_failed(character_name, mood, pose_key,
                  equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                  equipped_pieces_meta=_eq_meta):
        if force or trigger:
            # Force/Trigger: failed-Marker loeschen damit ein Retry moeglich ist
            from app.core.expression_regen import clear_failed_marker
            clear_failed_marker(character_name, mood, pose_key,
                                equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                                equipped_pieces_meta=_eq_meta)
        else:
            raise HTTPException(status_code=404, detail="Variant-Generierung fehlgeschlagen")

    if is_generating(character_name, mood, pose_key,
                     equipped_pieces=_eq_pieces, equipped_items=_eq_items):
        if _want_fallback:
            fb = _serve_fallback()
            if fb is not None:
                return fb
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content={"status": "generating", "mood": mood, "pose_key": pose_key})

    # Prefix uebernimmt trigger_expression_generation per Default aus dem Env
    # (OUTFIT_IMAGE_PROMPT_PREFIX) — Auto-Regen + Vorschau identisch.
    # Cooldown wird umgangen wenn kein Cache existiert (sonst zeigt die Scene nie
    # ein Variant-Bild), oder wenn explizit per trigger=1 angefordert.
    # Explizit-Trigger (trigger=1, Garderobe-Preview-Button): kein Debounce,
    # User erwartet sofortige Generierung. Auto-Pfade (cache-miss beim Render)
    # coalescen, damit ein Chat-Turn nicht 3 Varianten erzeugt.
    started = trigger_expression_generation(character_name, mood, pose_key,
                                             equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                                             equipped_pieces_meta=_eq_meta,
                                             ignore_cooldown=True,
                                             ignore_feature_gate=bool(trigger),
                                             coalesce=not bool(trigger))
    if started:
        if _want_fallback:
            fb = _serve_fallback()
            if fb is not None:
                return fb
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content={"status": "generating", "mood": mood, "pose_key": pose_key})
    # Konkurrierender Request: andere Anfrage hat gerade schon gestartet → 202 statt 404
    if is_generating(character_name, mood, pose_key,
                     equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                     equipped_pieces_meta=_eq_meta):
        if _want_fallback:
            fb = _serve_fallback()
            if fb is not None:
                return fb
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content={"status": "generating", "mood": mood, "pose_key": pose_key})
    raise HTTPException(status_code=404, detail="Keine Variant verfuegbar")


@router.delete("/{character_name}/outfit-expression/cache")
async def clear_outfit_expression_cache_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Clears the expression image cache for a character."""
    from app.core.expression_regen import clear_expression_cache
    data = await request.json()
    user_id = data.get("user_id", "")
    count = clear_expression_cache(character_name)
    return {"status": "success", "cleared": count}


@router.get("/{character_name}/expressions")
async def list_expressions_route(character_name: str) -> Dict[str, Any]:
    """Lists all cached expression variants of a character with their
    parameters (mood, activity, equipped, model, seed, backend, workflow, …).
    """
    from app.core.expression_regen import list_expressions
    items = list_expressions(character_name)
    return {"character": character_name, "expressions": items}


@router.get("/{character_name}/expressions/{filename}")
async def serve_expression_route(character_name: str, filename: str):
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
                        headers={"Cache-Control": "public, max-age=3600"})


@router.delete("/{character_name}/expressions/{filename}")
async def delete_expression_route(character_name: str, filename: str) -> Dict[str, Any]:
    """Deletes a single expression variant image + its JSON sidecar."""
    from app.core.expression_regen import delete_expression
    ok = delete_expression(character_name, filename)
    if not ok:
        raise HTTPException(status_code=404, detail="Expression not found")
    return {"status": "success", "deleted": filename}


@router.get("/{character_name}/outfit-imagegen")
async def get_outfit_imagegen_route(character_name: str) -> Dict[str, Any]:
    """Liefert die per-Character Overrides fuer den Outfit-/Variant-Image-
    Service (Workflow + Model + LoRAs). Leere Werte = Defaults."""
    from app.models.character import get_character_profile
    prof = get_character_profile(character_name) or {}
    override = prof.get("outfit_imagegen") or {}
    if not isinstance(override, dict):
        override = {}
    return {
        "workflow": override.get("workflow", "") or "",
        "model": override.get("model", "") or "",
        "loras": override.get("loras", []) or [],
    }


@router.put("/{character_name}/outfit-imagegen")
async def set_outfit_imagegen_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Speichert Workflow/Model/LoRA-Override fuer den Outfit-Image-Service.
    Alle Felder leer loescht den Override komplett."""
    body = await request.json()
    return character_ops.apply_outfit_imagegen(character_name, body)


@router.get("/{character_name}/profile")
def get_profile_route(character_name: str) -> Dict[str, Any]:
    """Gibt das vollstaendige Character-Profil zurueck"""
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
    from app.models.character_template import resolve_profile_tokens, get_template
    data = await request.json()
    text = str(data.get("text", "") or "")
    target_key = str(data.get("target_key", "") or "character_appearance")
    profile = get_character_profile(character_name)
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    resolved = resolve_profile_tokens(text, profile, template=tmpl, target_key=target_key)
    return {"character": character_name, "resolved": resolved}


@router.get("/{character_name}/belongings")
def get_belongings_route(character_name: str) -> Dict[str, Any]:
    """Inventar + Outfit (Paper-Doll) eines Characters — gleiche Form wie
    /play/belongings, für den Game-Admin-Garderoben-Tab."""
    from app.routes.play import build_belongings
    return build_belongings(character_name)


@router.get("/{character_name}/active-conditions")
def get_active_conditions_route(character_name: str) -> Dict[str, Any]:
    """Gibt aktive Conditions mit Icon/Label/Restdauer zurueck.

    Abgelaufene Conditions werden gefiltert. Icons/Labels kommen aus den
    Prompt-Filtern (Game Admin → Zustaende).
    """
    return character_ops.build_active_conditions(character_name)


@router.post("/{character_name}/profile")
async def update_profile_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert Character-Profil Felder (bulk update)"""
    try:
        data = await request.json()
        return character_ops.apply_profile_update(character_name, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Config (character_config.json) ---

@router.get("/{character_name}/config")
def get_config_route(character_name: str) -> Dict[str, Any]:
    """Gibt die Character-Config zurueck (TTS, Extraction, etc.)"""
    config = get_character_config(character_name)
    return {"character": character_name, "config": config}


@router.post("/{character_name}/config")
async def update_config_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert Character-Config Felder (bulk update)"""
    try:
        data = await request.json()
        return character_ops.apply_config_update(character_name, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Images ---

@router.post("/{character_name}/images")
async def upload_character_image(character_name: str, request: Request) -> Dict[str, Any]:
    """Laedt ein Bild hoch"""
    try:
        form = await request.form()
        file = form.get("file")

        if not file:
            raise HTTPException(status_code=400, detail="Keine Datei hochgeladen")

        allowed_extensions = {"png", "jpg", "jpeg", "gif", "webp", "mp4"}
        filename = file.filename.lower()
        if not any(filename.endswith(ext) for ext in allowed_extensions):
            raise HTTPException(status_code=400, detail="Format nicht unterstuetzt")

        images_dir = get_character_images_dir(character_name)

        timestamp = int(time.time())
        file_ext = Path(filename).suffix
        image_filename = f"{character_name}_{timestamp}{file_ext}"
        image_path = images_dir / image_filename

        contents = await file.read()
        image_path.write_bytes(contents)

        add_character_image(character_name, image_filename)

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
    """Gibt Liste aller Bilder zurueck"""
    try:
        images = get_character_images(character_name)
        profile_image = get_character_profile_image(character_name)
        comments = get_character_image_comments(character_name)
        prompts = get_character_image_prompts(character_name)
        metadata = get_character_image_metadata(character_name)

        # Pruefen welche Bilder ein zugehoeriges Video haben ({stem}.mp4)
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
def get_character_profile_image_file(character_name: str):
    """Serves the character's profile image directly (shortcut for notifications/avatars)."""
    from fastapi.responses import Response
    try:
        profile_img = get_character_profile_image(character_name)
        if not profile_img:
            return Response(status_code=404)
        images_dir = get_character_images_dir(character_name)
        image_path = images_dir / profile_img
        if not image_path.exists():
            return Response(status_code=404)
        media_type, _ = mimetypes.guess_type(str(image_path))
        return FileResponse(
            image_path,
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=300"}
        )
    except Exception:
        return Response(status_code=404)


@router.get("/{character_name}/images/{image_filename}")
def get_character_image(character_name: str, image_filename: str):
    """Ruft ein spezifisches Bild ab"""
    from fastapi.responses import Response
    try:
        if ".." in image_filename or "/" in image_filename:
            raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

        images_dir = get_character_images_dir(character_name)
        image_path = images_dir / image_filename

        if not image_path.exists():
            return Response(
                status_code=404,
                headers={"Cache-Control": "public, max-age=300"}
            )

        media_type, _ = mimetypes.guess_type(str(image_path))
        return FileResponse(
            image_path,
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "no-cache"}
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/outfits/{image_filename}")
def get_character_outfit_image(character_name: str, image_filename: str):
    """Liefert ein Outfit-Referenzbild aus dem outfits/ Verzeichnis."""
    from fastapi.responses import Response
    try:
        if ".." in image_filename or "/" in image_filename:
            raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

        from app.models.character import get_character_outfits_dir
        outfits_dir = get_character_outfits_dir(character_name)
        image_path = outfits_dir / image_filename

        if not image_path.exists():
            return Response(status_code=404)

        media_type, _ = mimetypes.guess_type(str(image_path))
        return FileResponse(
            image_path,
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "no-cache"}
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

_MODEL_MAX_BYTES = 100 * 1024 * 1024


def _resolve_character_model(character_name: str):
    """(path, meta, texture_path) of the character's current-outfit model —
    uploaded or generated, whichever is stored. (None, None, None) when there is
    none: a normal state, not an error. (The pre-per-outfit global upload store
    was migrated into the per-outfit store at boot — no serving fallback.)

    Only the META route needs this: get_model3d_info re-reads the profile and
    enumerates the mesh backends. The byte routes below resolve the file path
    directly."""
    from app.core.model3d import find_model3d_serving, find_texture, get_model3d_info
    path, _match = find_model3d_serving(character_name)
    if path:
        info = get_model3d_info(character_name).get("model") or {}
        meta = {"format": path.suffix.lstrip(".").lower(),
                "rig": info.get("rig", "mixamo"),
                "filename": path.name,
                "size": path.stat().st_size,
                "has_texture": bool(info.get("texture_url")),
                "created_at": info.get("created_at", ""),
                "backend": info.get("backend", ""),
                "source": info.get("source", "generated")}
        # FBX case only — a GLB embeds its textures; a stray image next to a
        # GLB is an auxiliary material map, never the basecolor.
        tex = (find_texture(character_name, path.stem)
               if path.suffix.lower() == ".fbx" else None)
        return path, meta, tex
    return None, None, None


# ETag/If-None-Match serving is shared: app.core.http_files.etag_file_response.


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
    enc = quote(character_name)
    meta = {**meta, "url": f"/characters/{enc}/model"}
    if tex:
        meta["texture_url"] = f"/characters/{enc}/model/texture"
    # Body height in cm — the client scales the figures against each other
    # with it (models come out of the generator at arbitrary scale). None =
    # unset, the client keeps its default.
    from app.core.height import height_cm
    meta["height_cm"] = height_cm(get_character_profile(character_name) or {})
    # Resolution tiers of THIS model, in fallback order. A client may request
    # any of them via ?tier= — an unbuilt one falls back to the full mesh, so
    # this list only says which ones actually save anything.
    from app.core.model3d import available_tiers
    meta["tiers"] = available_tiers(_path)
    return meta


@router.get("/{character_name}/model")
def get_character_model_file(character_name: str, request: Request,
                             tier: str = ""):
    """Serves the 3D model bytes (uploaded one, else the generated mesh).
    404 lets clients degrade to the portrait marker.

    ``tier=low`` asks for the reduced distance mesh; a tier that was never
    built falls back to the full one, so a client may always ask.
    """
    from fastapi.responses import Response
    from app.core.model3d import find_model3d_serving_tier
    path, _, _served = find_model3d_serving_tier(character_name, tier)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type = ("model/gltf-binary" if path.suffix.lower() == ".glb"
                  else "application/octet-stream")
    return etag_file_response(path, request, media_type)


@router.get("/{character_name}/model/texture")
def get_character_model_texture_file(character_name: str, request: Request):
    """Serves the basecolor image of a generic/FBX model — PNG or JPEG, the
    gateway prefers JPEG since 2026-07-17 (a GLB embeds its textures and has
    none here). 404 when absent."""
    from fastapi.responses import Response
    from app.core.model3d import find_model3d_serving, find_texture
    path, _ = find_model3d_serving(character_name)
    tex = find_texture(character_name, path.stem) if path else None
    if not tex:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media = "image/jpeg" if tex.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return etag_file_response(tex, request, media)


# --- 3D reference renders (T-pose / default pose, app/core/model_refs.py) ---

@router.get("/{character_name}/model-refs")
def get_character_model_refs(character_name: str) -> Dict[str, Any]:
    """Info about the stored reference renders ({tpose, pose, pending})."""
    from app.core.model_refs import get_model_refs_info
    return get_model_refs_info(character_name)


@router.post("/{character_name}/model-refs/generate")
async def generate_character_model_refs(character_name: str,
                                        request: Request) -> Dict[str, Any]:
    """Manually fires the reference render (debounce skipped). Body
    ``{"kinds": ["pose"]}`` narrows to specific images — each tab sends its
    own kind, so wardrobe (pose) and 3D (tpose) generate independently.
    Without kinds the per-image auto toggles decide."""
    from app.core.model_refs import REF_KINDS, trigger_now
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    kinds = body.get("kinds") if isinstance(body, dict) else None
    if kinds is not None:
        if not isinstance(kinds, list):
            raise HTTPException(status_code=422, detail="kinds must be a list")
        kinds = tuple(k for k in kinds if k in REF_KINDS)
        if not kinds:
            raise HTTPException(status_code=422,
                                detail=f"kinds must contain one of {list(REF_KINDS)}")
    trigger_now(character_name, kinds=kinds)
    return {"status": "generating"}


@router.post("/{character_name}/model-refs/auto")
async def set_character_model_refs_auto(character_name: str, request: Request) -> Dict[str, Any]:
    """Per-image toggles for the automatic outfit-change render
    (body: {tpose?: bool, pose?: bool})."""
    from app.core.model_refs import set_auto_kinds
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    return {"auto": set_auto_kinds(character_name, body)}


@router.get("/{character_name}/model-refs/{kind}")
def get_character_model_ref_image(character_name: str, kind: str, request: Request):
    """Serves the reference render (kind: tpose|pose) of the CURRENT outfit
    combination; 404 when absent. ETag so a re-render of the same combination
    (or an outfit switch) is picked up instead of a stale cached image."""
    from fastapi.responses import Response
    from app.core.model_refs import REF_KINDS, find_ref_image
    if kind not in REF_KINDS:
        raise HTTPException(status_code=400, detail="kind must be tpose|pose")
    path = find_ref_image(character_name, kind)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type, _ = mimetypes.guess_type(str(path))
    return etag_file_response(path, request, media_type or "application/octet-stream")


# --- Generated 3D model (img2mesh from the T-pose render, per outfit) ---

@router.get("/{character_name}/model3d")
def get_character_model3d(character_name: str) -> Dict[str, Any]:
    """Status of the generated mesh for the CURRENT outfit combination
    ({signature, has_input, model, pending}) + the character's animation set
    (explicit or derived), so the preview can offer the matching clips."""
    from app.core.animation_sets import derive_set, resolve_sets
    from app.core.model3d import get_model3d_info
    info = get_model3d_info(character_name)
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
    """
    try:
        from app.core.model_validate import validate_fbx, validate_glb
        from app.core.model3d import save_uploaded_model
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

        contents = await file.read()
        if len(contents) > _MODEL_MAX_BYTES:
            raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
        tex_file = form.get("texture")
        texture = await tex_file.read() if tex_file else None
        if texture is not None and len(texture) > _MODEL_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Texture too large")

        if filename.endswith(".glb"):
            result = validate_glb(contents)
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
        meta = save_uploaded_model(character_name, file.filename, contents,
                                   rig=rig, texture=texture)
        return {"status": "success", **meta,
                "warnings": result["warnings"],
                "joint_count": result.get("joint_count", 0)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/model3d/rig")
async def set_character_model3d_rig(character_name: str, request: Request) -> Dict[str, Any]:
    """Updates the rig of the current outfit's model (mixamo|generic)."""
    from app.core.model3d import set_model3d_rig
    body = await request.json()
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
def generate_character_model3d(character_name: str, force: bool = False,
                               backend: str = "", face_num: int = 0,
                               texture_size: int = 0) -> Dict[str, Any]:
    """Starts the mesh generation for the current outfit (T-pose render as
    input). ``backend`` picks the mesh backend (empty = admin default);
    ``face_num``/``texture_size`` override the backend defaults for THIS run
    (0 = default; texture size reaches the gateway once its alias declares
    the param). Cached per combination — ``force=1`` re-generates."""
    from app.core.model3d import trigger_generation
    from app.core.model_refs import find_ref_image
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    if not find_ref_image(character_name, "tpose"):
        raise HTTPException(
            status_code=409,
            detail="No T-pose render for the current outfit — generate it first")
    if not trigger_generation(character_name, force=force,
                              backend_glob=(backend or "").strip(),
                              face_num=face_num or None,
                              texture_size=texture_size or None):
        return {"status": "already_running"}
    return {"status": "generating"}


@router.post("/{character_name}/model3d/options")
async def set_character_model3d_options(character_name: str, request: Request) -> Dict[str, Any]:
    """Per-character overrides for the mesh generation.
    Body: {"no_fingers": true|false|null} (null clears the override — the
    backend's configured default applies again) and/or
    {"auto_generate": true|false} (generate the mesh automatically on the
    cheapest backend once a new combination's T-pose render succeeded)."""
    from app.core.model3d import set_model3d_options
    if not get_character_dir(character_name).exists():
        raise HTTPException(status_code=404, detail="Character not found")
    body = await request.json()
    if not isinstance(body, dict) or not (
            "no_fingers" in body or "auto_generate" in body):
        raise HTTPException(status_code=400,
                            detail="no_fingers or auto_generate missing")
    updates = {}
    if "no_fingers" in body:
        nf = body["no_fingers"]
        if nf is not None and not isinstance(nf, bool):
            raise HTTPException(status_code=400,
                                detail="no_fingers must be bool or null")
        updates["no_fingers"] = nf
    if "auto_generate" in body:
        updates["auto_generate"] = bool(body["auto_generate"])
    return {"options": set_model3d_options(character_name, updates)}


@router.get("/{character_name}/model3d/file")
def get_character_model3d_file(character_name: str, request: Request,
                               tier: str = ""):
    """Serves the mesh for the current outfit combination — exact entry,
    else the nearest stored one (find_model3d_serving). ETag +
    If-None-Match — the files are several MB. 404 when absent.

    ``tier=low`` serves the reduced version of the SAME combination, falling
    back to the full mesh when none was built."""
    from fastapi.responses import Response
    from app.core.model3d import find_model3d_serving_tier
    path, _, _served = find_model3d_serving_tier(character_name, tier)
    if not path:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media_type = ("model/gltf-binary" if path.suffix.lower() == ".glb"
                  else "application/octet-stream")
    return etag_file_response(path, request, media_type)


@router.get("/{character_name}/model3d/texture")
def get_character_model3d_texture(character_name: str, request: Request):
    """Serves the basecolor PNG of the generated mesh (generic/FBX case only —
    a GLB embeds its textures). Follows the same serving chain as the mesh
    route so file and texture always belong together. 404 when absent."""
    from fastapi.responses import Response
    from app.core.model3d import find_model3d_serving, find_texture
    path, _ = find_model3d_serving(character_name)
    tex = find_texture(character_name, path.stem) if path else None
    if not tex:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    return etag_file_response(tex, request, "image/png")


@router.delete("/{character_name}/model3d")
def delete_character_model3d(character_name: str) -> Dict[str, Any]:
    """Deletes the cached mesh of the current outfit combination."""
    from app.core.model3d import delete_model3d
    if not delete_model3d(character_name):
        raise HTTPException(status_code=404, detail="No model")
    return {"status": "success"}


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


@router.post("/{character_name}/images/{image_filename}/comment")
async def save_image_comment_endpoint(character_name: str, image_filename: str, request: Request) -> Dict[str, Any]:
    """Speichert einen Kommentar fuer ein Bild"""
    try:
        body = await request.json()
        comment = body.get("comment", "")
        add_character_image_comment(character_name, image_filename, comment)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{character_name}/profile-image/{image_filename}")
def set_character_profile_image_endpoint(character_name: str, image_filename: str) -> Dict[str, Any]:
    """Setzt das Profilbild"""
    try:
        if set_character_profile_image(character_name, image_filename):
            return {
                "status": "success",
                "character": character_name,
                "profile_image": image_filename
            }
        else:
            raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{character_name}/images/{image_filename}")
def delete_character_image_endpoint(character_name: str, image_filename: str) -> Dict[str, Any]:
    """Loescht ein Bild"""
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
            raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{character_name}/images/{image_filename}/animation")
def delete_image_animation(character_name: str, image_filename: str) -> Dict[str, Any]:
    """Loescht nur die Animation (Video) eines Bildes, nicht das Bild selbst."""
    if ".." in image_filename or "/" in image_filename:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

    from app.models.character import remove_image_animation
    deleted = remove_image_animation(character_name, image_filename)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Keine Animation vorhanden")
    return {"status": "success", "deleted_video": deleted}


@router.post("/{character_name}/cleanup-images")
def cleanup_images_endpoint(character_name: str) -> Dict[str, Any]:
    """Loescht verwaiste Bilddateien die nicht im Profil registriert sind."""
    try:
        return cleanup_orphaned_images(character_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Skills Management ---

@router.post("/skills/reload")
def reload_skills() -> Dict[str, Any]:
    """Laedt alle Skills neu ohne Server-Neustart."""
    try:
        from app.skills.animate import reload_animate_services
        reload_animate_services()
        result = reload_skill_manager()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills/list")
def list_skills() -> Dict[str, Any]:
    """Listet alle aktuell geladenen Skills auf"""
    try:
        skill_manager = get_skill_manager()
        return {
            "skills": skill_manager.get_skill_info(),
            "count": len(skill_manager.skills)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/skills/available")
def get_available_skills_for_character(character_name: str) -> Dict[str, Any]:
    """Returns all globally loaded skills with per-character enabled state and config fields."""
    try:
        return character_ops.build_available_skills(character_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{character_name}/prompt-preview")
async def get_prompt_preview_route(character_name: str) -> Dict[str, Any]:
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
    data = await request.json()
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
    """Listet die fuer diesen Character verfuegbaren Soul-MD-Dateien auf.

    Berucksichtigt Template-Feature-Gates. Gibt pro Datei: section-id,
    file_default lock-status, ob die Datei existiert.
    """
    return character_ops.build_soul_files(character_name)


@router.get("/{character_name}/soul/file/{section_id}")
def get_soul_file(character_name: str, section_id: str) -> Dict[str, Any]:
    """Liefert Inhalt + parsed Sections einer Soul-MD-Datei."""
    return character_ops.read_soul_file(character_name, section_id)


@router.post("/{character_name}/soul/file/{section_id}")
async def save_soul_file(character_name: str, section_id: str, request: Request) -> Dict[str, Any]:
    """Schreibt komplette Soul-MD-Datei.

    Body: {"user_id": "...", "content": "...full MD text..."}
    """
    return await character_ops.write_soul_file(character_name, section_id, request)


@router.put("/{character_name}/skills/{skill_name}/enabled")
async def toggle_character_skill(character_name: str, skill_name: str, request: Request) -> Dict[str, Any]:
    """Toggles a skill enabled/disabled for a character."""
    try:
        data = await request.json()
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
    """Gibt die character-spezifische Skill-Konfiguration zurueck"""
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
    """Speichert die character-spezifische Skill-Konfiguration (Merge)."""
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        config = data.get("config", {})
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="config muss ein Objekt sein")

        # Merge: Bestehende Config laden und nur uebergebene Felder updaten
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
    """Erkennt im Bild verwendete Characters aus reference_images Metadaten."""
    return await character_ops.detect_characters_core(character_name, image_name, request)


@router.post("/{character_name}/images/{image_name}/regenerate")
async def regenerate_character_image(character_name: str, image_name: str, request: Request) -> Dict[str, Any]:
    """Regenerates an image via the core image-service pipeline.

    Nutzt den gespeicherten Prompt, optional verbessert durch User-Feedback,
    und generiert ein neues Bild das das alte ersetzt.
    """
    body = await request.json()
    user_id = body.get("user_id", "")
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail=f"Ungueltiger Dateiname: {image_name}")

    images_dir = get_character_images_dir(character_name)
    image_path = images_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail=f"Bild nicht gefunden: {image_name}")

    prompts = get_character_image_prompts(character_name)
    prompt = prompts.get(image_name, "")
    if not prompt:
        raise HTTPException(status_code=422, detail="Kein Prompt fuer dieses Bild gespeichert.")

    # Custom-Prompt aus Dialog uebernimmt gespeicherten Prompt
    custom_prompt = body.get("custom_prompt", "").strip()
    if custom_prompt:
        prompt = custom_prompt

    improvement_request = body.get("improvement_request", "").strip()
    workflow_name = body.get("workflow", "").strip()
    backend_name = body.get("backend", "").strip()
    loras = body.get("loras")  # Optional: [{name, strength}, ...]
    model_override = body.get("model_override", "").strip()
    character_names = body.get("character_names")  # Optional: explizite Character-Auswahl
    room_id = body.get("room_id", "").strip()  # Optional: Raum-Override
    negative_prompt_override = body.get("negative_prompt", "").strip()  # Optional: Negativ-Prompt aus Dialog
    create_new = body.get("create_new", False)
    use_room = body.get("use_room", True)
    use_source_as_reference = bool(body.get("use_source_as_reference", False))
    # Originale Location aus Bild-Metadaten (nicht aktuelle Character-Position)
    from app.models.character import get_single_image_meta
    _img_meta = get_single_image_meta(character_name, image_name) or {}
    original_location_id = _img_meta.get("location", "")
    agent_config = get_character_config(character_name)

    from app.core.task_queue import get_task_queue
    from app.core.task_router import resolve_queue
    _tq = get_task_queue()
    _queue = resolve_queue("image_regenerate", {}, agent_name=character_name)
    _track_id = _tq.track_start(
        "image_regenerate", "Bild regenerieren", agent_name=character_name,
        provider=backend_name or workflow_name or "",
        queue_name=_queue,
        start_running=False)

    import threading
    threading.Thread(
        target=character_ops.regenerate_image_worker,
        args=(character_name, image_path, prompt, improvement_request, workflow_name,
              backend_name, agent_config, loras, model_override, character_names, room_id,
              original_location_id, negative_prompt_override, _track_id, create_new,
              use_room, use_source_as_reference, _tq),
        daemon=True).start()
    return {"status": "started", "image": image_name, "track_id": _track_id}


@router.post("/{character_name}/enhance-image-prompt")
async def enhance_image_prompt(character_name: str, request: Request) -> Dict[str, Any]:
    """Verbessert einen Image-Prompt via LLM direkt im Dialog.

    Body: { user_id, prompt, improvement_request, llm_override? }
    Returns: { prompt: "verbesserter prompt" }
    """
    return await character_ops.enhance_image_prompt_core(character_name, request)


@router.post("/{character_name}/rebuild-image-prompt")
async def rebuild_image_prompt(character_name: str, request: Request) -> Dict[str, Any]:
    """Rebuilds the image prompt based on the adapter of the target backend.

    Source of the values (mood, outfit, expression, location, ...):
      1. PRIMARY: saved `canonical` dict from the image.json (from creation time)
      2. FALLBACK: current character state (only for old images without canonical)

    Body: { user_id, workflow? (backend match spec), canonical?, scene_text? }
    Returns: { prompt, target_model, source: "saved"|"current" }
    """
    return await character_ops.rebuild_image_prompt_core(character_name, request)


@router.post("/{character_name}/images/{image_name}/suggest-animate-prompt")
async def suggest_animate_prompt(character_name: str, image_name: str, request: Request) -> Dict[str, str]:
    """Generiert einen Animation-Prompt basierend auf der Bildanalyse via Tools-LLM."""
    return await character_ops.suggest_animate_prompt_core(character_name, image_name, request)


@router.post("/{character_name}/images/{image_name}/animate")
async def animate_character_image(character_name: str, image_name: str, request: Request) -> Dict[str, Any]:
    """Animiert ein Galerie-Bild als Video."""
    body = await request.json()
    user_id = body.get("user_id", "")
    if ".." in image_name or "/" in image_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")

    images_dir = get_character_images_dir(character_name)
    image_path = images_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    prompt = body.get("prompt", "").strip()
    if not prompt:
        prompts = get_character_image_prompts(character_name)
        prompt = prompts.get(image_name, "")
    if not prompt:
        raise HTTPException(status_code=422, detail="Kein Prompt angegeben")

    service = body.get("service", "").strip()
    try:
        seconds = int(body.get("seconds") or 0)
    except (TypeError, ValueError):
        seconds = 0
    # Optional LoRA slots from the animate dialog (gateway video aliases).
    data = body
    loras = []
    for _l in (data.get("loras") or []):
        if isinstance(_l, dict) and (_l.get("name") or "").strip() not in ("", "None"):
            try:
                _s = float(_l.get("strength", 1.0))
            except (TypeError, ValueError):
                _s = 1.0
            loras.append({"name": _l["name"].strip(), "strength": _s})

    from app.core.task_queue import get_task_queue
    _tq = get_task_queue()
    _track_id = _tq.track_start(
        "image_animate", "Bild animieren", agent_name=character_name,
        start_running=False)

    import threading
    threading.Thread(
        target=character_ops.animate_image_worker,
        args=(character_name, image_name, images_dir, image_path, prompt, service, _tq, _track_id, loras, seconds or None),
        daemon=True).start()
    return {"status": "started", "image": image_name, "track_id": _track_id}


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

    content = await file.read()
    try:
        return import_character_from_zip(content, overwrite=overwrite)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Import failed")
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")


# --- Image-Generation Option Endpoints ---

@router.get("/{character_name}/skills/image_generation/workflows")
def get_imagegen_workflows(character_name: str) -> Dict[str, Any]:
    """Returns all available generation options (image backends)."""
    return character_ops.build_imagegen_workflows(character_name)


# --- VideoGeneration Skill Config ---

@router.get("/{character_name}/skills/video_generation/options")
def get_videogen_options(character_name: str) -> Dict[str, Any]:
    """Returns all selection options for the VideoGen config:
    ImageGen backends/models/LoRAs + animation services/LoRAs."""
    return character_ops.build_videogen_options(character_name)


@router.post("/{character_name}/skills/video_generation/config")
async def save_videogen_config(character_name: str, request: Request) -> Dict[str, Any]:
    """Speichert die VideoGen-Config (ImageGen + Animation Einstellungen)."""
    data = await request.json()
    return character_ops.apply_videogen_config(character_name, data)


# --- Memory/Knowledge Endpoints ---

@router.delete("/{character_name}/knowledge/{entry_id}")
def delete_single_knowledge(character_name: str, entry_id: str) -> Dict[str, Any]:
    """Loescht einen einzelnen Memory-Eintrag."""
    from app.models.memory import delete_memory
    if delete_memory(character_name, entry_id):
        return {"status": "success", "deleted": entry_id}
    raise HTTPException(status_code=404, detail="Entry not found")


@router.delete("/{character_name}/knowledge")
def clear_character_knowledge(character_name: str) -> Dict[str, Any]:
    """Loescht alle Memory-Eintraege eines Characters."""
    from app.models.memory import clear_memories
    m_count = clear_memories(character_name)
    return {"status": "success", "deleted_count": m_count}


# ---------------------------------------------------------------------------
# Memory-Modal v2 — Tab-spezifische Endpoints
# Plan: development_instructions/plan-memory-window-redesign.md
# ---------------------------------------------------------------------------

@router.get("/{character_name}/memory/today")
def memory_today(character_name: str) -> Dict[str, Any]:
    """Tab "Heute": Status, 24h-Lanes, Top-K aktuell relevante Memories.

    Read-only — kein access_count-Bump beim Anzeigen.
    """
    return character_ops.build_memory_today(character_name)


@router.get("/{character_name}/debug-activity")
def debug_activity(character_name: str) -> Dict[str, Any]:
    """Game-Admin-Debug: warum verhaelt sich ein (Nicht-Avatar-)Character so?

    Aggregiert read-only: aktuelles Gefuehl + Quelle, juengste Mood-/State-/Thought-
    Aktivitaet und aktive Block-/Force-Regeln zu einer „Why"-Begruendung. Keine
    Avatar-Bindung — der Name kommt aus dem Pfad.
    """
    return character_ops.build_debug_activity(character_name)


@router.get("/{character_name}/memory/locations")
def memory_locations(character_name: str) -> Dict[str, Any]:
    """Tab "Bekannte Orte": Karte mit allen Welt-Orten + bekannt/aktuell/Besuchszahlen.

    Liefert sowohl alle Welt-Orte (fuer Layout-Kontext) als auch die
    Auswahl, die der Character laut `known_locations` kennt. Frontend
    entscheidet, ob es nur die bekannten oder alles zeigt.
    """
    return character_ops.build_memory_locations(character_name)


@router.put("/{character_name}/known-locations")
async def set_known_locations_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Setzt die known_locations-Liste eines Characters (Editor, voller Soll-State).

    Body: {"known_locations": ["loc_id", ...]}. Leere Liste = kennt nichts
    (strict mode bleibt aktiv). Auto-Discovery beim Betreten ergaenzt spaeter.
    """
    from app.models.character import set_known_locations
    data = await request.json()
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


@router.post("/{character_name}/memory/consolidate")
async def memory_consolidate_now(character_name: str,
                                 _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Runs the full 5-phase memory consolidation for ONE character right now
    (admin test tool — exercise the per-NPC amount caps without waiting for
    the 6h background cycle). Synchronous; returns the removal counts."""
    import asyncio as _aio
    from app.models.character import list_available_characters
    if character_name not in list_available_characters():
        raise HTTPException(status_code=404,
                            detail=f"Character '{character_name}' not found")
    from app.core.memory_service import handle_memory_consolidation
    return await _aio.to_thread(handle_memory_consolidation,
                                {"character_name": character_name})


@router.get("/{character_name}/memory/relationships")
def memory_relationships(character_name: str,
                         history_limit: int = 10) -> Dict[str, Any]:
    """Tab "Beziehungen": Sentiment, Strength, Tension + letzte N Events.

    `memories_count` = wie viele Memories haben diesen Partner als
    related_character gesetzt — Klick im Frontend filtert Tab 2.
    """
    return character_ops.build_memory_relationships(
        character_name, history_limit=history_limit)


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
