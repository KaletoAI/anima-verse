"""Character routes - Character management, images, and profile"""
import io
import os
import time
import mimetypes
import zipfile
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from typing import Dict, Any, List, Optional
from app.core.log import get_logger

logger = get_logger("characters")

from app.models.account import set_current_character
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
    get_character_outfits_dir)
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
    from app.core.provider_manager import get_provider_manager
    from app.core.model_capabilities import (get_model_capabilities,
                                             get_all_suitability)

    pm = get_provider_manager()
    providers = pm.list_all_models()
    suit_all = get_all_suitability()  # Key: "provider::model" (lowercased)

    # Capabilities an jedes Model anhaengen. Vision-Spalte vorbelegen: ist nichts
    # gespeichert (None) und erkennt der Name ein Vision-Modell, mit True
    # vorbelegen. (Name-Heuristik kann Vision nur bestaetigen, nicht ausschliessen
    # → bei nicht-Vision-Namen bleibt es unbekannt.) Caps KOPIEREN, sonst wuerde
    # der gecachte _default-/Substring-Eintrag mutiert.
    # Suitability-Test (HW-abhaengig) wird per vollem provider::model EXAKT
    # gemergt → gleiches Modell auf anderer Hardware bekommt eigene Werte.
    for provider_name, provider_data in providers.items():
        for model in provider_data.get("models", []):
            caps = dict(get_model_capabilities(model.get("name", "")))
            if caps.get("vision") is None and model.get("vision"):
                caps["vision"] = True
            sd = suit_all.get(f"{provider_name}::{model.get('name', '')}".lower())
            if sd:
                caps.update(sd)
            model["capabilities"] = caps

    return {
        "providers": providers,
        "task_defaults": {},
    }


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
    from app.models.world import resolve_location, get_room_by_id
    from app.models.character import get_character_current_room
    loc = resolve_location(location)
    loc_id = loc.get("id", "") if loc else ""
    loc_name = loc.get("name", location) if loc else location

    # Avatar-Raum auf {id, name} aufloesen — char_room kann historisch entweder
    # ID oder Name sein, daher matchen wir gegen beides.
    room_norm = (room or "").strip()
    avatar_room_id = ""
    avatar_room_name = ""
    if room_norm and loc:
        _r = get_room_by_id(loc, room_norm)
        if _r:
            avatar_room_id = _r.get("id", "") or room_norm
            avatar_room_name = _r.get("name", "")
        else:
            for _r in (loc.get("rooms") or []):
                if _r.get("name") == room_norm:
                    avatar_room_id = _r.get("id", "")
                    avatar_room_name = room_norm
                    break
            else:
                avatar_room_name = room_norm
                avatar_room_id = room_norm

    all_chars = list_available_characters()
    result = []
    for name in all_chars:
        char_loc = get_character_current_location(name)
        if not (char_loc and (char_loc == loc_id or char_loc == location)):
            continue
        char_room = (get_character_current_room(name) or "").strip()
        # Default same_room=True; nur wenn Avatar in einem Raum ist UND der
        # Character explizit in einem ANDEREN Raum, gilt er als "anderswo".
        # Character ohne Raum-Angabe = ueberall in der Location praesent.
        if room_norm and char_room:
            same_room = char_room in (avatar_room_id, avatar_room_name)
        else:
            same_room = True
        profile_img = get_character_profile_image(name)
        result.append({
            "name": name,
            "profile_image": profile_img or "",
            "avatar_url": f"/characters/{name}/images/{profile_img}" if profile_img else "",
            "same_room": same_room,
            "room": char_room,
        })
    return {"characters": result, "location": loc_name, "location_id": loc_id, "room": room_norm}


@router.get("/chatbots")
def list_chatbots() -> Dict[str, Any]:
    """Listet alle Chatbots (Characters ohne Location-System).

    Ein Chatbot ist ein Character dessen Template `locations_enabled: false`
    hat — er hat keine Weltposition und ist immer ansprechbar.
    """
    from app.models.character_template import is_feature_enabled
    all_chars = list_available_characters()
    result = []
    for name in all_chars:
        # Kein Location-System = Chatbot
        if is_feature_enabled(name, "locations_enabled"):
            continue
        profile_img = get_character_profile_image(name)
        result.append({
            "name": name,
            "profile_image": profile_img or "",
            "avatar_url": f"/characters/{name}/images/{profile_img}" if profile_img else "",
        })
    return {"characters": result}


@router.get("/animate/services")
async def list_animate_services() -> List[Dict[str, Any]]:
    """Liefert die verfuegbaren Animation-Services fuer das Frontend."""
    from app.skills.animate import get_animate_services
    return get_animate_services()


DEFAULT_NEW_CHARACTER_SKILLS = (
    # Skill-IDs aus app/skills/skill_manager.py:SKILL_REGISTRY.
    # Defaults fuer neu angelegte Characters — Liste entspricht den Haken
    # im Skills-Tab fuer einen "frisch geborenen" Character (alles Wesentliche
    # an, Spezial-/Nischen-Skills wie OutfitCreation, VideoGenerator,
    # Retrospect, MarkdownWriter, KnowledgeExtract bleiben aus, weil sie
    # Token-Kosten/Setup brauchen und nicht jeder NPC sie braucht).
    "imagegen", "setlocation", "talk_to", "send_message", "notify_user",
    "instagram_comment", "instagram_reply",
    "consume_item", "outfit_change", "setactivity",
    "invite_to_party", "join_party", "leave_party",
)


@router.post("/create")
async def create_character(request: Request) -> Dict[str, Any]:
    """Erstellt einen neuen Character mit leerem Profil und zugewiesenem Template"""
    try:
        data = await request.json()
        character_name = data.get("character_name", "").strip()
        template_name = data.get("template", "human-default")
        if not character_name:
            raise HTTPException(status_code=400, detail="character_name fehlt")
        # Reservierte / problematische Namen abfangen — z.B. "undefined" oder
        # "null" entstehen wenn JS-Code irgendwo einen Wert nicht initialisiert
        # und ihn dann String-konvertiert. Das soll keinen Character-Ordner anlegen.
        if character_name.lower() in ("undefined", "null", "none", "nan"):
            raise HTTPException(status_code=400,
                detail=f"'{character_name}' ist als Character-Name nicht erlaubt")

        # Check if character already exists
        existing = list_available_characters()
        if character_name in existing:
            raise HTTPException(status_code=409, detail=f"Character '{character_name}' existiert bereits")

        # Create character with initial profile + template reference
        initial_profile = {
            "character_name": character_name,
            "template": template_name,
        }
        # Explizite Erstellung — save_character_profile blockiert sonst
        # unbekannte Namen (Schutz gegen Geister-Characters aus LLM-Output).
        save_character_profile(character_name, initial_profile, create_new=True)

        # known_locations explizit als leere Liste initialisieren. Ohne dieses
        # Feld greift im SetLocation-Skill der Legacy-Bypass und der Char darf
        # zu beliebigen Orten teleportieren (Pfad-Validation wird uebersprungen).
        # Frische Chars sollen nirgends hin koennen, bis sie aktiv platziert
        # oder gefuehrt werden — auto-discovery in save_character_current_location
        # befuellt die Liste danach automatisch.
        try:
            cfg = get_character_config(character_name) or {}
            if "known_locations" not in cfg:
                cfg["known_locations"] = []
                save_character_config(character_name, cfg)
        except Exception as _e:
            logger.warning("create_character: known_locations init fehlgeschlagen: %s", _e)

        # Skill-Defaults schreiben — ohne diese Files greift die ALWAYS_LOAD-
        # Filter-Logik (skill_manager._get_agent_skills) und schaltet alle
        # Skills standardmaessig AUS. Mit der Default-Liste hat der frische
        # Char direkt das uebliche Repertoire (chat, set_location, magic
        # konsumieren, outfit-wechsel, ...).
        for _sid in DEFAULT_NEW_CHARACTER_SKILLS:
            try:
                save_character_skill_config(character_name, _sid, {"enabled": True})
            except Exception as _e:
                logger.warning("create_character: skill-default '%s' nicht gesetzt: %s",
                               _sid, _e)

        # Auto-assign the new character to the creator's allowed_characters list
        # so they can immediately see and use it without a separate admin step.
        from app.core.auth_dependency import get_current_user_optional
        from app.core.users import update_user
        creator = get_current_user_optional(request)
        if creator and creator.get("id"):
            allowed = list(creator.get("allowed_characters") or [])
            if character_name not in allowed:
                allowed.append(character_name)
                try:
                    update_user(creator["id"], allowed_characters=allowed)
                except Exception as e:
                    logger.warning(
                        "create_character: konnte allowed_characters fuer "
                        "user=%s nicht aktualisieren: %s",
                        creator.get("username"), e,
                    )

        # Set as current character
        set_current_character(character_name)

        return {
            "status": "success",
            "character": character_name,
            "template": template_name,
            "message": f"Character '{character_name}' erstellt"
        }
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
    from app.models.world import get_location_name as _get_loc_name, get_room_by_id, _load_world_data
    from app.models.character_template import is_feature_enabled
    locations_on = is_feature_enabled(character_name, "locations_enabled")
    activities_on = is_feature_enabled(character_name, "activities_enabled")
    location_id = get_character_current_location(character_name) if locations_on else ""
    location_name = _get_loc_name(location_id) if location_id else ""
    from app.models.character import get_effective_activity
    activity = get_effective_activity(character_name) if activities_on else ""
    from app.models.character import get_character_current_room
    current_room = get_character_current_room(character_name) if locations_on else ""
    # Resolve room: could be an ID or a name — normalize to ID + name
    current_room_id = ""
    current_room_name = ""
    if current_room and location_id:
        world_data = _load_world_data()
        for loc in world_data.get("locations", []):
            if loc.get("id") == location_id:
                # Try by ID first
                room = get_room_by_id(loc, current_room)
                if room:
                    current_room_id = room.get("id", current_room)
                    current_room_name = room.get("name", "")
                else:
                    # Fallback: match by name
                    for r in loc.get("rooms", []):
                        if r.get("name", "").lower() == current_room.lower():
                            current_room_id = r.get("id", "")
                            current_room_name = r.get("name", "")
                            break
                break
    # Detail-Beschreibung der Aktivitaet
    from app.models.character import get_character_profile, get_movement_target
    profile = get_character_profile(character_name)
    activity_detail = ""  # current_activity_detail entfernt (Pose-Modell)
    movement_target_id = get_movement_target(character_name) if locations_on else ""
    movement_target_name = _get_loc_name(movement_target_id) if movement_target_id else ""
    return {
        "character": character_name,
        "current_location": location_name or location_id or "",
        "current_location_id": location_id or "",
        "current_activity": activity or "",
        "current_activity_detail": activity_detail,
        "current_room": current_room_id or current_room or "",
        "current_room_name": current_room_name or current_room or "",
        "movement_target_id": movement_target_id,
        "movement_target_name": movement_target_name,
    }


@router.get("/{character_name}/notice")
def get_character_notice_route(character_name: str) -> Dict[str, Any]:
    """Liefert die persistenten Hinweise fuer den Avatar-Header-Banner.

    - ``force_warning``: aktive Force-Regel (rule_name + message + go_to + set_activity)
      ODER ``None``. Fuer den Avatar wird die Regel NICHT automatisch ausgefuehrt.
    - ``critical_events``: ungeloeste Events der Kategorien ``disruption``/``danger``
      an der aktuellen Avatar-Location, neueste zuerst.
    """
    out: Dict[str, Any] = {"force_warning": None, "critical_events": []}
    try:
        from app.models.rules import check_force_rules, resolve_force_destination
        force = check_force_rules(character_name)
        if force:
            go_loc, go_room = resolve_force_destination(character_name,
                                                         force.get("go_to", "stay"))
            out["force_warning"] = {
                "rule_id": force.get("rule_id", ""),
                "rule_name": force.get("rule_name", ""),
                "message": force.get("message", ""),
                "go_to": force.get("go_to", "stay"),
                "go_to_location_id": go_loc,
                "go_to_room_id": go_room,
                "set_activity": force.get("set_activity", ""),
            }
    except Exception as e:
        logger.debug("notice: force_rules failed for %s: %s", character_name, e)

    try:
        from app.models.character import get_character_current_location
        from app.models.events import list_events
        loc_id = (get_character_current_location(character_name) or "").strip()
        if loc_id:
            for ev in list_events(location_id=loc_id) or []:
                cat = (ev.get("category") or "").lower()
                if cat not in ("disruption", "danger"):
                    continue
                if ev.get("resolved"):
                    continue
                out["critical_events"].append({
                    "id": ev.get("id", ""),
                    "category": cat,
                    "text": ev.get("text", ""),
                    "created_at": ev.get("created_at", ""),
                })
            out["critical_events"].sort(key=lambda e: e.get("created_at", ""), reverse=True)
    except Exception as e:
        logger.debug("notice: critical_events failed for %s: %s", character_name, e)

    return out


@router.post("/{character_name}/current-location")
async def update_character_current_location(character_name: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert den aktuellen virtuellen Aufenthaltsort"""
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        location = data.get("current_location", "")
        room = data.get("current_room", "")

        # Name → ID aufloesen falls noetig
        from app.models.world import resolve_location as _resolve_loc, get_entry_room_id
        from app.models.character import get_character_current_location, get_character_current_room, save_character_current_room, clear_pose_intent
        loc_obj = _resolve_loc(location)
        location_to_save = loc_obj["id"] if loc_obj and loc_obj.get("id") else location
        location_name_resp = loc_obj.get("name", location) if loc_obj else location
        old_loc = get_character_current_location(character_name)
        old_room = get_character_current_room(character_name) or ""
        # Default-Raum fuer Cross-Location-Move: Entry-Room des Ziels.
        if not room and loc_obj and location_to_save != old_loc:
            room = get_entry_room_id(loc_obj) or ""
        # Avatar: Outfit NICHT automatisch umstellen (manuelle User-Wahl bleibt).
        from app.models.account import get_active_character
        _is_avatar = (get_active_character() == character_name)

        # Block-Regeln: Avatar darf nicht in geblockte Locations/Raeume.
        # Gleiche Gates wie der SetLocation-Skill der NPCs durchlaeuft.
        if _is_avatar and (location_to_save != old_loc or (room and room != old_room)):
            from app.models.rules import check_leave, check_access
            if old_loc and location_to_save != old_loc:
                ok_leave, leave_msg = check_leave(character_name)
                if not ok_leave:
                    raise HTTPException(status_code=403,
                        detail={"reason": "block_leave", "message": leave_msg})
            ok_enter, enter_msg = check_access(character_name, location_to_save,
                                               room_id=room or "")
            if not ok_enter:
                raise HTTPException(status_code=403,
                    detail={"reason": "block_enter", "message": enter_msg})
        save_character_current_location(character_name, location_to_save,
            _skip_compliance=_is_avatar)
        # Raum und Aktivitaet: bei Ortswechsel loeschen, es sei denn Raum wurde mitgegeben
        if location_to_save != old_loc:
            save_character_current_room(character_name, room or '')
            if not room:
                clear_pose_intent(character_name)
        elif room:
            save_character_current_room(character_name, room)

        # Avatar-Eintritts-Hook: andere Characters im neuen Raum bemerken den
        # Eintritt und reagieren ggf. (forced_thought + TalkTo). Nur wenn:
        # - es der Avatar ist (sonst ist's der Auto-Move eines NPCs)
        # - tatsaechlich Raum oder Location gewechselt hat (nicht nur Re-Save)
        new_room = room or ''
        room_changed = (location_to_save != old_loc) or (new_room and new_room != old_room)
        from app.core.log import get_logger as _gl_route
        _gl_route("characters_route").info(
            "current-location POST: char=%s is_avatar=%s old_loc=%s -> new_loc=%s old_room=%s -> new_room=%s room_changed=%s",
            character_name, _is_avatar, old_loc, location_to_save, old_room, new_room, room_changed)
        room_entry_result = {"reactor": "", "silent_noticers": []}
        # Roll-on-Entry: bei echtem Cross-Location-Move sofort wuerfeln, ob ein
        # Event fuer den Avatar entsteht. Nur fuer Avatar (nicht fuer NPC-Moves).
        if _is_avatar and location_to_save != old_loc and loc_obj:
            try:
                from app.core.random_events import try_roll_on_entry
                try_roll_on_entry(character_name, location_to_save, loc_obj)
            except Exception as _re:
                logger.debug("try_roll_on_entry fehlgeschlagen: %s", _re)
        if _is_avatar and room_changed:
            try:
                from app.core.room_entry import on_avatar_room_entry
                # Room-Label aufloesen
                _room_label = ""
                if new_room and loc_obj:
                    from app.models.world import get_room_by_id
                    _r = get_room_by_id(loc_obj, new_room)
                    if _r and _r.get("name"):
                        _room_label = _r["name"]
                import asyncio as _asyncio
                room_entry_result = await _asyncio.to_thread(
                    on_avatar_room_entry,
                    avatar_name=character_name,
                    location_id=location_to_save,
                    room_id=new_room,
                    location_label=location_name_resp,
                    room_label=_room_label,
                ) or room_entry_result
            except Exception as _re:
                from app.core.log import get_logger as _gl
                _gl("characters_route").debug("avatar_room_entry hook failed: %s", _re)

        return {
            "status": "success",
            "character": character_name,
            "current_location": location_name_resp,
            "reactor": room_entry_result.get("reactor", ""),
            "silent_noticers": room_entry_result.get("silent_noticers", []),
        }
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
        data = await request.json()
        location = (data.get("location_id") or data.get("current_location") or "").strip()
        room = (data.get("current_room") or "").strip()
        if not location:
            raise HTTPException(status_code=400, detail="location_id fehlt")

        from app.models.world import resolve_location as _resolve_loc, get_entry_room_id
        from app.models.character import (
            add_known_location, get_character_current_room,
            save_character_current_room, clear_pose_intent)

        loc_obj = _resolve_loc(location)
        location_to_save = loc_obj["id"] if loc_obj and loc_obj.get("id") else location
        location_name_resp = loc_obj.get("name", location) if loc_obj else location

        # Kein Raum mitgegeben → Entry-Room der Ziel-Location nehmen.
        if not room and loc_obj:
            room = get_entry_room_id(loc_obj) or ""

        old_loc = get_character_current_location(character_name)
        old_room = get_character_current_room(character_name) or ""
        from app.models.account import get_active_character
        _is_avatar = (get_active_character() == character_name)

        # Block-Regeln: Avatar darf nicht in geblockte Locations/Raeume.
        if _is_avatar and (location_to_save != old_loc or (room and room != old_room)):
            from app.models.rules import check_leave, check_access
            if old_loc and location_to_save != old_loc:
                ok_leave, leave_msg = check_leave(character_name)
                if not ok_leave:
                    raise HTTPException(status_code=403,
                        detail={"reason": "block_leave", "message": leave_msg})
            ok_enter, enter_msg = check_access(character_name, location_to_save,
                                               room_id=room or "")
            if not ok_enter:
                raise HTTPException(status_code=403,
                    detail={"reason": "block_enter", "message": enter_msg})

        add_known_location(character_name, location_to_save)
        save_character_current_location(character_name, location_to_save,
            _skip_compliance=_is_avatar)
        if location_to_save != old_loc:
            save_character_current_room(character_name, room or '')
            if not room:
                clear_pose_intent(character_name)
        elif room:
            save_character_current_room(character_name, room)

        new_room = room or ''
        room_changed = (location_to_save != old_loc) or (new_room and new_room != old_room)
        room_entry_result = {"reactor": "", "silent_noticers": []}
        # Roll-on-Entry: Cross-Location-Drop-on-Map löst sofort Würfel aus.
        if _is_avatar and location_to_save != old_loc and loc_obj:
            try:
                from app.core.random_events import try_roll_on_entry
                try_roll_on_entry(character_name, location_to_save, loc_obj)
            except Exception as _re:
                logger.debug("try_roll_on_entry fehlgeschlagen: %s", _re)
        if _is_avatar and room_changed:
            try:
                from app.core.room_entry import on_avatar_room_entry
                _room_label = ""
                if new_room and loc_obj:
                    from app.models.world import get_room_by_id
                    _r = get_room_by_id(loc_obj, new_room)
                    if _r and _r.get("name"):
                        _room_label = _r["name"]
                import asyncio as _asyncio
                room_entry_result = await _asyncio.to_thread(
                    on_avatar_room_entry,
                    avatar_name=character_name,
                    location_id=location_to_save,
                    room_id=new_room,
                    location_label=location_name_resp,
                    room_label=_room_label,
                ) or room_entry_result
            except Exception as _re:
                logger.debug("avatar_room_entry hook failed: %s", _re)

        return {
            "status": "success",
            "character": character_name,
            "current_location": location_name_resp,
            "current_location_id": location_to_save,
            "reactor": room_entry_result.get("reactor", ""),
            "silent_noticers": room_entry_result.get("silent_noticers", []),
        }
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
    """Aktualisiert die aktuelle Aktivitaet"""
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        activity = data.get("current_activity", "")

        # Freie Pose setzen (kein Library-Matching, kein Auto-Raum-Move mehr —
        # Raum/Ort bleiben unveraendert, die Pose ist freier Text).
        set_pose_intent(character_name, activity)

        return {"status": "success", "character": character_name,
                "current_activity": activity, "current_room": "", "current_room_id": ""}
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

        from app.skills.act_skill import perform_act
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
        from app.models.character_template import is_feature_enabled
        if not is_feature_enabled(character_name, "status_effects_enabled"):
            return {"status_effects": {}, "traits": {}, "bar_meta": {}}
        from app.models.character import get_character_profile, get_character_config, save_character_profile
        profile = get_character_profile(character_name)
        config = get_character_config(character_name)
        status = profile.get("status_effects", {})

        # Template laden — Quelle fuer Stat-Defaults und Bar-Metadaten
        bar_meta = {}
        stat_defaults = {}  # stat_key -> default_value aus Template
        stat_order: List[str] = []  # Template-Reihenfolge der Stats
        try:
            from app.models.character_template import get_template
            template_name = profile.get("template", "human-default")
            template = get_template(template_name)
            if template:
                for section in template.get("sections", []):
                    for field in section.get("fields", []):
                        if field.get("store") != "status_effects":
                            continue
                        stat_key = field.get("key", "")
                        if not stat_key:
                            continue
                        if stat_key not in stat_order:
                            stat_order.append(stat_key)
                        # Default aus Template
                        if field.get("default") is not None:
                            try:
                                stat_defaults[stat_key] = int(field["default"])
                            except (ValueError, TypeError):
                                pass
                        # Bar-Metadaten
                        meta = {}
                        if field.get("bar_color"):
                            meta["color"] = field["bar_color"]
                        if field.get("bar_label"):
                            meta["label"] = field["bar_label"]
                        if field.get("label"):
                            meta["name"] = field["label"]
                        if field.get("label_de"):
                            meta["name_de"] = field["label_de"]
                        if meta:
                            bar_meta[stat_key] = meta
        except Exception:
            pass

        # Fehlende status_effects aus Template-Defaults initialisieren und persistieren
        status_changed = False
        for stat_key, stat_default in stat_defaults.items():
            if stat_key not in status:
                status[stat_key] = stat_default
                status_changed = True

        if status_changed:
            profile["status_effects"] = status
            save_character_profile(character_name, profile)

        # In Template-Reihenfolge zurueckgeben — sonst zeigen Self/Others-Panels
        # dieselben Stats in verschiedenen (gespeicherten) Reihenfolgen.
        ordered_status = {k: status[k] for k in stat_order if k in status}
        for k, v in status.items():  # nicht im Template definierte Keys anhaengen
            if k not in ordered_status:
                ordered_status[k] = v

        return {"status_effects": ordered_status, "bar_meta": bar_meta}
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
        user_id = data.get("user_id", "").strip()
        new_template_name = data.get("new_template", "").strip()
        mode = data.get("mode", "diff")

        if not new_template_name:
            raise HTTPException(status_code=400, detail="user_id und new_template erforderlich")

        from app.models.character import get_character_profile, get_character_config, save_character_profile, save_character_config
        from app.models.character_template import get_template

        profile = get_character_profile(character_name)
        config = get_character_config(character_name)
        old_template_name = profile.get("template", "")
        old_template = get_template(old_template_name) if old_template_name else None
        new_template = get_template(new_template_name)

        if not new_template:
            raise HTTPException(status_code=404, detail=f"Template '{new_template_name}' nicht gefunden")

        # ALLE Felder aus altem und neuem Template sammeln (nicht nur traits)
        def _collect_all_fields(tmpl):
            fields = {}
            if not tmpl:
                return fields
            for section in tmpl.get("sections", []):
                for field in section.get("fields", []):
                    fkey = field.get("key", "")
                    if fkey:
                        fields[fkey] = field
            return fields

        old_fields = _collect_all_fields(old_template)
        new_fields = _collect_all_fields(new_template)

        # Diff berechnen
        added = []
        for key, field in new_fields.items():
            if key not in old_fields:
                added.append({
                    "key": key,
                    "label": field.get("label", key),
                    "label_de": field.get("label_de", ""),
                    "default": field.get("default"),
                    "store": field.get("store", ""),
                    "is_stat": field.get("store") == "status_effects",
                })

        removed = []
        for key, field in old_fields.items():
            if key not in new_fields:
                store = field.get("store", "")
                # Aktuellen Wert aus dem richtigen Speicher lesen
                if store == "status_effects":
                    current_val = profile.get("status_effects", {}).get(key, "")
                elif store == "config":
                    current_val = config.get(key, "")
                else:
                    current_val = profile.get(key, "")
                removed.append({
                    "key": key,
                    "label": field.get("label", key),
                    "label_de": field.get("label_de", ""),
                    "current_value": current_val,
                    "store": store,
                    "is_stat": store == "status_effects",
                })

        if mode == "diff":
            return {
                "old_template": old_template_name,
                "new_template": new_template_name,
                "added": added,
                "removed": removed,
            }

        # mode == "apply": Migration durchfuehren

        # 1. Neue Felder mit Defaults fuellen
        status = profile.get("status_effects", {})
        for item in added:
            default_val = item.get("default")
            key = item["key"]
            store = item.get("store", "")
            if store == "status_effects":
                if default_val is not None and key not in status:
                    status[key] = default_val
            elif store == "config":
                config[key] = default_val if default_val is not None else ""
            else:
                profile[key] = default_val if default_val is not None else ""

        # 2. Alte Felder entfernen
        for item in removed:
            key = item["key"]
            store = item.get("store", "")
            if store == "status_effects":
                status.pop(key, None)
                config.pop(key + "_hourly", None)
            elif store == "config":
                config.pop(key, None)
            else:
                profile.pop(key, None)

        profile["status_effects"] = status

        # 4. Template im Profil setzen
        profile["template"] = new_template_name

        # 5. Speichern
        save_character_profile(character_name, profile)
        save_character_config(character_name, config)

        return {
            "ok": True,
            "old_template": old_template_name,
            "new_template": new_template_name,
            "added": added,
            "removed": removed,
        }
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
        loras: LoRA list (without 'None')
    """
    sm = get_skill_manager()
    imagegen = sm.get_skill("image_generation")
    if not imagegen:
        return {"loras": []}

    # LoRA-library entries for the backend resolved for this character at
    # generation time (endpoint-filtered) — never the LoRAs of a foreign backend.
    try:
        from app.core.config import get_lora_library_names
        eff = imagegen._select_backend_for_agent(character_name) if character_name else None
        lib_names = get_lora_library_names(eff.name if eff else None)
    except Exception:
        lib_names = []

    return {"loras": list(dict.fromkeys(lib_names))}


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
    """Loescht alle gecachten Expression-Bilder dieses Characters. Sie werden
    bei Bedarf neu erzeugt (jetzt limitiert via Pose-Varianten + LRU)."""
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
    """Generiert ein neues Profilbild via ImageGenerationSkill."""
    import os
    import json as _json
    data = await request.json()
    user_id = data.get("user_id", "")

    # Character-Profil laden. Profilbild-Prompt = FACE PROMPT (face_appearance),
    # NICHT die Body-Appearance. Fallback auf Body-Appearance, falls leer.
    from app.models.character import get_character_profile, get_character_appearance, set_character_profile_image
    from app.models.character_template import resolve_profile_tokens, get_template
    profile = get_character_profile(character_name)
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    appearance = character_ops._resolve_face_prompt(profile, character_name, tmpl)

    # Prompt aus Dialog oder Face Prompt (Style kommt aus dem "profile"-Use-Case).
    prompt_text = data.get("prompt", "").strip() or (appearance or "").strip()

    # ImageGenerationSkill holen
    try:
        skill_manager = get_skill_manager()
        image_skill = skill_manager.get_skill("image_generation")
    except Exception:
        image_skill = None
    if not image_skill:
        raise HTTPException(status_code=500, detail="ImageGenerationSkill nicht verfuegbar")

    # Workflow/Backend/Modell aus Request
    workflow_name = data.get("workflow", "").strip()
    backend_name = data.get("backend", "").strip()
    loras_override = data.get("loras")
    model_override = data.get("model_override", "").strip()

    payload = {
        "prompt": prompt_text,
        "agent_name": character_name,
        "user_id": "",
        "auto_enhance": False,
        "set_profile": True,
        "image_use_case": "profile",
        "workflow": workflow_name,
        "backend": backend_name,
    }
    if loras_override is not None:
        payload["loras"] = loras_override
    if model_override:
        payload["model_override"] = model_override
    input_data = _json.dumps(payload)

    try:
        import asyncio
        result = await asyncio.to_thread(image_skill.execute, input_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bildgenerierung fehlgeschlagen: {str(e)}")

    # Dateiname aus dem Ergebnis extrahieren
    import re
    image_match = re.search(r'/characters/[^/]+/images/([^?)\n]+)', result)
    if not image_match:
        raise HTTPException(status_code=500, detail=f"Kein Bild im Ergebnis: {result[:200]}")

    image_filename = image_match.group(1)

    # Als Profilbild setzen
    set_character_profile_image(character_name, image_filename)

    image_url = f"/characters/{character_name}/images/{image_filename}"
    return {"status": "success", "image": image_filename, "image_url": image_url}


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
    """Generiert ein Bild fuer ein Outfit via ImageGenerationSkill."""
    import os
    import json as _json
    data = await request.json()
    user_id = data.get("user_id", "")

    # Outfit suchen
    outfits = get_character_outfits(character_name)
    outfit_obj = next((o for o in outfits if o.get("id") == outfit_id), None)
    if not outfit_obj:
        raise HTTPException(status_code=404, detail="Outfit nicht gefunden")

    outfit_description = outfit_obj.get("outfit", "")
    if not outfit_description:
        raise HTTPException(status_code=400, detail="Outfit hat keine Beschreibung")

    # Character-Profil laden: Appearance + Geschlecht (Tokens auflösen)
    from app.models.character import get_character_profile, get_character_appearance
    from app.models.character_template import resolve_profile_tokens, get_template
    profile = get_character_profile(character_name)
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    appearance = get_character_appearance(character_name)
    if appearance and "{" in appearance:
        appearance = resolve_profile_tokens(appearance, profile, template=tmpl, target_key="character_appearance")
    if outfit_description and "{" in outfit_description:
        outfit_description = resolve_profile_tokens(outfit_description, profile, template=tmpl, target_key="outfit")

    # Prompt: aus Dialog (wenn vorhanden) oder via Hilfsfunktion aufbauen
    prompt_text = data.get("prompt", "").strip()
    if not prompt_text:
        prompt_text = character_ops._build_outfit_image_prompt(character_name, outfit_description)

    # ImageGenerationSkill holen
    try:
        skill_manager = get_skill_manager()
        image_skill = skill_manager.get_skill("image_generation")
    except Exception:
        image_skill = None

    if not image_skill:
        raise HTTPException(status_code=500, detail="ImageGenerationSkill nicht verfuegbar")

    # Workflow/Backend/LoRA/Modell-Auswahl:
    #   1) explizit aus Request
    #   2) per-Character-Override (profile.outfit_imagegen) — MUSS vor dem
    #      Skill-Default greifen, sonst generiert ein Character mit konfiguriertem
    #      Flux faelschlich mit dem ersten geladenen Workflow (z.B. Z-Image).
    #   3) ENV OUTFIT_IMAGEGEN_DEFAULT
    workflow_name = data.get("workflow", "").strip()
    backend_name = data.get("backend", "").strip()
    loras_override = data.get("loras")
    model_override = data.get("model_override", "").strip()
    if not workflow_name and not backend_name:
        try:
            from app.models.character import get_character_profile as _gcp
            _ovr = (_gcp(character_name) or {}).get("outfit_imagegen") or {}
            if isinstance(_ovr, dict):
                workflow_name = (_ovr.get("workflow") or "").strip()
                if not model_override:
                    model_override = (_ovr.get("model") or "").strip()
                if loras_override is None and isinstance(_ovr.get("loras"), list):
                    loras_override = _ovr.get("loras")
        except Exception as _e:
            logger.debug("outfit-image per-char override read failed: %s", _e)
    if not workflow_name and not backend_name:
        _outfit_default = os.environ.get("OUTFIT_IMAGEGEN_DEFAULT", "").strip()
        if _outfit_default.startswith("workflow:"):
            workflow_name = _outfit_default[len("workflow:"):].strip()
        elif _outfit_default.startswith("backend:"):
            backend_name = _outfit_default[len("backend:"):].strip()
    # The spec (glob) is resolved by the skill itself at generation time
    # (resolve_imagegen_target) — no pre-resolution here.

    # Resolution from .env (portrait format for full-body outfits)
    outfit_w = int(os.environ.get("OUTFIT_IMAGE_WIDTH", 0) or 0) or None
    outfit_h = int(os.environ.get("OUTFIT_IMAGE_HEIGHT", 0) or 0) or None

    # Appearance mitgeben damit Reference-Bilder aufgeloest werden (Flux2 braucht sie)
    payload = {
        "prompt": prompt_text,
        "agent_name": character_name,
        "user_id": "",
        "auto_enhance": False,
        "skip_gallery": True,
        "image_use_case": "outfit",
        "workflow": workflow_name,
        "backend": backend_name,
        "appearances": [{"name": character_name, "appearance": appearance or ""}],
        "profile_only": True,
    }
    if outfit_w:
        payload["override_width"] = outfit_w
    if outfit_h:
        payload["override_height"] = outfit_h
    if loras_override is not None:
        payload["loras"] = loras_override
    if model_override:
        payload["model_override"] = model_override
    input_data = _json.dumps(payload)

    try:
        import asyncio
        result = await asyncio.to_thread(image_skill.execute, input_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bildgenerierung fehlgeschlagen: {str(e)}")

    # Dateiname aus dem Ergebnis extrahieren (Skill gibt Markdown-Links zurueck)
    import re
    image_match = re.search(r'/characters/[^/]+/images/([^?)\n]+)', result)
    if not image_match:
        raise HTTPException(status_code=500, detail=f"Kein Bild im Ergebnis: {result[:200]}")

    image_filename = image_match.group(1)

    # Generiertes Bild von images/ nach outfits/ verschieben
    from app.models.character import get_character_outfits_dir, postprocess_outfit_image
    import shutil
    images_dir = get_character_images_dir(character_name)
    outfits_dir = get_character_outfits_dir(character_name)
    src_path = images_dir / image_filename
    dst_path = outfits_dir / image_filename
    if src_path.exists():
        shutil.move(str(src_path), str(dst_path))

    # Hintergrund entfernen + transparente Raender abschneiden
    # rembg/ONNX-Inferenz ist CPU-bound → Threadpool damit der Event-Loop nicht blockiert.
    import asyncio as _asyncio
    final_path = await _asyncio.to_thread(postprocess_outfit_image, dst_path)
    final_filename = final_path.name

    # Altes Outfit-Bild loeschen
    old_image = outfit_obj.get("image", "")
    if old_image and old_image != final_filename:
        old_path = outfits_dir / old_image
        if old_path.exists():
            old_path.unlink()

    # Outfit-Image-Feld + Metadaten aktualisieren
    # Vollstaendige Metadaten aus der Generierung uebernehmen (Spec 1.2)
    _gen_meta = getattr(image_skill, 'last_image_meta', {}) or {}
    _image_meta = {
        "provider": _gen_meta.get("backend_type", ""),
        "service": _gen_meta.get("backend", ""),
        "model": _gen_meta.get("model", ""),
        "loras": _gen_meta.get("loras", loras_override or []),
        "prompt": prompt_text,
        "negative_prompt": _gen_meta.get("negative_prompt", ""),
        "seed": _gen_meta.get("seed", 0),
        "width": outfit_w or _gen_meta.get("width", 0),
        "height": outfit_h or _gen_meta.get("height", 0),
        "created_at": _gen_meta.get("created_at", ""),
        "duration_s": _gen_meta.get("duration_s", 0),
        "reference_images": _gen_meta.get("reference_images", {}),
        "workflow": _gen_meta.get("workflow", workflow_name),
        "model_override": model_override,
    }
    # Bild verknuepfen (loescht automatisch alte Variants).
    # update_outfit_image schreibt die Sidecar-JSON neben dem PNG (Spec 1.2).
    update_outfit_image(character_name, outfit_id, final_filename, image_meta=_image_meta)

    image_url = f"/characters/{character_name}/outfits/{final_filename}"
    return {"status": "success", "image": final_filename, "image_url": image_url}


@router.post("/{character_name}/outfits/generate-all-images")
async def generate_all_outfit_images_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Generiert Bilder fuer alle Outfits eines Characters (Bulk, im Hintergrund).

    Verwendet die gleiche Pipeline wie generate_outfit_image_route,
    aber fuer jedes Outfit einzeln. Laeuft im Hintergrund ueber die Task-Queue.
    """
    import os
    import json as _json
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

    def _generate_all():
        from app.core.task_queue import get_task_queue
        from app.models.character_template import resolve_profile_tokens, get_template
        from app.models.character import (
            get_character_outfits_dir, postprocess_outfit_image, update_outfit_image)
        import shutil
        import re

        _tq = get_task_queue()
        _track_id = _tq.track_start(
            "bulk_outfit_images", f"Outfit-Bilder ({len(eligible)})",
            agent_name=character_name)

        profile = get_character_profile(character_name)
        tmpl = get_template(profile.get("template", "")) if profile.get("template") else None

        skill_manager = get_skill_manager()
        image_skill = skill_manager.get_skill("image_generation")
        if not image_skill:
            _tq.track_finish(_track_id, error="ImageGenerationSkill nicht verfuegbar")
            return

        success_count = 0
        for idx, outfit_obj in enumerate(eligible, 1):
            outfit_id = outfit_obj.get("id", "")
            outfit_name = outfit_obj.get("name", outfit_id[:8])
            outfit_description = outfit_obj.get("outfit", "")

            _tq.track_update_label(_track_id, f"Outfit {idx}/{len(eligible)}: {outfit_name}")
            logger.info("Bulk Outfit %d/%d: %s (%s)", idx, len(eligible), outfit_name, outfit_id[:8])

            # Tokens aufloesen
            if outfit_description and "{" in outfit_description:
                outfit_description = resolve_profile_tokens(
                    outfit_description, profile, template=tmpl, target_key="outfit")

            # Prompt via Hilfsfunktion
            prompt_text = character_ops._build_outfit_image_prompt(character_name, outfit_description)

            # Appearance fuer Reference-Bilder
            appearance = get_character_appearance(character_name)
            if appearance and "{" in appearance:
                appearance = resolve_profile_tokens(
                    appearance, profile, template=tmpl, target_key="character_appearance")

            payload = {
                "prompt": prompt_text,
                "agent_name": character_name,
                "user_id": "",
                "auto_enhance": False,
                "skip_gallery": True,
                "appearances": [{"name": character_name, "appearance": appearance or ""}],
                "profile_only": True,
            }
            if workflow_name:
                payload["workflow"] = workflow_name
            if backend_name:
                payload["backend"] = backend_name
            if loras_override is not None:
                payload["loras"] = loras_override
            if model_override:
                payload["model_override"] = model_override

            try:
                result = image_skill.execute(_json.dumps(payload))
                match = re.search(r'/characters/[^/]+/images/([^?)\n]+)', result)
                if not match:
                    logger.warning("Bulk Outfit %s: Kein Bild im Ergebnis", outfit_name)
                    continue

                image_filename = match.group(1)
                images_dir = get_character_images_dir(character_name)
                outfits_dir = get_character_outfits_dir(character_name)
                src_path = images_dir / image_filename
                dst_path = outfits_dir / image_filename
                if src_path.exists():
                    shutil.move(str(src_path), str(dst_path))

                final_path = postprocess_outfit_image(dst_path)
                final_filename = final_path.name

                # Altes Bild loeschen
                old_image = outfit_obj.get("image", "")
                if old_image and old_image != final_filename:
                    old_path = outfits_dir / old_image
                    if old_path.exists():
                        old_path.unlink()

                # Metadaten
                _gen_meta = getattr(image_skill, 'last_image_meta', {}) or {}
                _image_meta = {
                    "provider": _gen_meta.get("backend_type", ""),
                    "service": _gen_meta.get("backend", ""),
                    "model": _gen_meta.get("model", ""),
                    "loras": _gen_meta.get("loras", []),
                    "prompt": prompt_text,
                    "negative_prompt": _gen_meta.get("negative_prompt", ""),
                    "seed": _gen_meta.get("seed", 0),
                    "workflow": _gen_meta.get("workflow", workflow_name),
                    "model_override": model_override,
                }
                # update_outfit_image schreibt PNG-Verknuepfung + Sidecar-JSON
                update_outfit_image(character_name, outfit_id, final_filename, image_meta=_image_meta)

                success_count += 1
                logger.info("Bulk Outfit %s: Bild generiert -> %s", outfit_name, final_filename)

            except Exception as e:
                logger.error("Bulk Outfit %s fehlgeschlagen: %s", outfit_name, e)

        _tq.track_finish(_track_id)
        logger.info("Bulk Outfit-Bilder fertig: %d/%d erfolgreich", success_count, len(eligible))

    threading.Thread(target=_generate_all, daemon=True, name=f"bulk-outfit-{character_name}").start()
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
def get_outfit_expression(character_name: str, mood: str = "", activity: str = "",
                          pieces: str = "", items: str = "",
                          piece_colors: str = "",
                          override: int = 0, trigger: int = 0, force: int = 0,
                          fallback: str = ""):
    """Returns the expression/pose variant for current mood + activity + equipped.

    Variant = Character-Appearance + angelegte Items (Pieces + Equipped-Items) +
    Pose (aus activity, Default wenn leer) + Expression (aus mood, Default wenn
    leer). Cache-Key haengt NICHT mehr von einem Outfit-Objekt ab — es gibt
    kein Basis-Outfitbild mehr.

    Query params:
        pieces: Optional "slot1:itemId1,slot2:itemId2" — ueberschreibt den
                real-equipped Piece-State (z.B. Wardrobe-Preview eines Sets
                das noch nicht angezogen ist).
        items: Optional "id1,id2" — ueberschreibt equipped_items.
        override: 1 erzwingt Verwendung von pieces/items auch wenn leer
                  (= "leerer Equipped-State"); ohne override werden leere
                  pieces/items als "nicht mitgegeben" interpretiert und der
                  Real-State aus dem Profil geladen.
        fallback: "default" — wenn keine Variant im Cache (aber Generierung
                  laeuft), wird das Profilbild als Platzhalter zurueckgegeben
                  (200 statt 202). Frontend zeigt damit ein sinnvolles Bild
                  bis der echte Variant fertig ist.

    Antworten: 200 mit Bild, 202 wenn Generierung laeuft, 404 wenn fehl-
    geschlagen / kein Generator verfuegbar.
    """
    from app.core.expression_regen import (
        get_cached_expression, trigger_expression_generation, is_generating, has_failed)

    # Mood/Activity: Wenn nicht explizit uebergeben, Character-State als Default
    # nehmen — damit Frontend den zu Chat/Scheduler passenden Variant-Cache
    # findet. Override-Modus laesst Leer-Params zu (Set-Vorschau ist generisch).
    _is_override = bool(override or pieces or items or piece_colors)
    if not _is_override:
        if not mood:
            try:
                from app.models.character import get_character_current_feeling
                mood = get_character_current_feeling(character_name) or ""
            except Exception:
                mood = ""
        if not activity:
            try:
                # Effektive Aktivitaet (B1): spiegelt den is_sleeping-Flag → ein
                # schlafender Char bekommt die Sleeping-Pose/Expression, passend
                # zur _expr_version in /play/scene.
                from app.models.character import get_effective_activity
                activity = get_effective_activity(character_name) or ""
            except Exception:
                activity = ""

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
    cached = get_cached_expression(character_name, mood, activity,
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

    # Helper: Fallback-Bild wenn die gesuchte Variant noch nicht bereit ist.
    # Profilbild ist NIE eine Option — Profilbild = Roster-Avatar, nicht Scene.
    # Reihenfolge:
    #   1) Default-Variant (mood="" + activity="") mit aktuellem Equipped-State.
    #   2) Neuestes beliebiges Expression-Variant des Characters.
    # Wenn beides fehlt: None → Aufrufer liefert 202 (Generierung laeuft) und
    # FE pollt weiter bis das echte Variant kommt.
    def _serve_fallback():
        from app.core.expression_regen import _get_expressions_dir, _safe_name

        def _serve_file(path, status):
            media_type = mimetypes.guess_type(str(path))[0] or "image/png"
            return FileResponse(
                path=str(path),
                media_type=media_type,
                headers={
                    "Cache-Control": "no-cache",
                    "X-Variant-Status": status,
                })

        # 1) Default-Variant: gleicher Equipped-State, mood+activity leer
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

        # 2) Neuestes beliebiges Expression-Variant des Characters
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

        # KEIN Profilbild-Fallback — lieber nichts als das falsche Bild.
        return None

    _want_fallback = (fallback or "").strip().lower() == "default"

    # Override-Modus: per default nur Cache lesen. Mit trigger=1 wird die
    # Generierung fuer genau diese Equipped-Kombination explizit angestossen
    # (z.B. Wardrobe-Vorschau-Button, der fuer das ausgewaehlte Set die
    # Variant vorberechnen soll ohne vorher anzuziehen).
    if _is_override and not trigger:
        if is_generating(character_name, mood, activity,
                         equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                         equipped_pieces_meta=_eq_meta):
            if _want_fallback:
                fb = _serve_fallback()
                if fb is not None:
                    return fb
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=202,
                content={"status": "generating", "mood": mood, "activity": activity})
        raise HTTPException(status_code=404, detail="Keine Variant im Cache")

    if has_failed(character_name, mood, activity,
                  equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                  equipped_pieces_meta=_eq_meta):
        if force or trigger:
            # Force/Trigger: failed-Marker loeschen damit ein Retry moeglich ist
            from app.core.expression_regen import clear_failed_marker
            clear_failed_marker(character_name, mood, activity,
                                equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                                equipped_pieces_meta=_eq_meta)
        else:
            raise HTTPException(status_code=404, detail="Variant-Generierung fehlgeschlagen")

    if is_generating(character_name, mood, activity,
                     equipped_pieces=_eq_pieces, equipped_items=_eq_items):
        if _want_fallback:
            fb = _serve_fallback()
            if fb is not None:
                return fb
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content={"status": "generating", "mood": mood, "activity": activity})

    # Prefix uebernimmt trigger_expression_generation per Default aus dem Env
    # (OUTFIT_IMAGE_PROMPT_PREFIX) — Auto-Regen + Vorschau identisch.
    # Cooldown wird umgangen wenn kein Cache existiert (sonst zeigt die Scene nie
    # ein Variant-Bild), oder wenn explizit per trigger=1 angefordert.
    # Explizit-Trigger (trigger=1, Garderobe-Preview-Button): kein Debounce,
    # User erwartet sofortige Generierung. Auto-Pfade (cache-miss beim Render)
    # coalescen, damit ein Chat-Turn nicht 3 Varianten erzeugt.
    started = trigger_expression_generation(character_name, mood, activity,
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
            content={"status": "generating", "mood": mood, "activity": activity})
    # Konkurrierender Request: andere Anfrage hat gerade schon gestartet → 202 statt 404
    if is_generating(character_name, mood, activity,
                     equipped_pieces=_eq_pieces, equipped_items=_eq_items,
                     equipped_pieces_meta=_eq_meta):
        if _want_fallback:
            fb = _serve_fallback()
            if fb is not None:
                return fb
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content={"status": "generating", "mood": mood, "activity": activity})
    raise HTTPException(status_code=404, detail="Keine Variant verfuegbar")


@router.delete("/{character_name}/outfit-expression/cache")
async def clear_expression_cache_route(character_name: str, request: Request) -> Dict[str, Any]:
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
    from app.models.character import get_character_profile, save_character_profile
    body = await request.json()
    workflow = (body.get("workflow") or "").strip()
    model = (body.get("model") or "").strip()
    loras = body.get("loras") or []
    if not isinstance(loras, list):
        loras = []
    clean_loras = []
    for l in loras:
        if not isinstance(l, dict):
            continue
        nm = (l.get("name") or "").strip()
        if not nm or nm == "None":
            continue
        try:
            st = float(l.get("strength", 1.0))
        except Exception:
            st = 1.0
        clean_loras.append({"name": nm, "strength": st})
    prof = get_character_profile(character_name) or {}
    # Immer schreiben (auch leer) — sonst persistiert ein Clear nicht: outfit_imagegen
    # lebt in config_json und wird beim Save nur uebertragen, wenn der Key im Profile
    # PRAESENT ist. Ein del laesst den alten Config-Wert stehen. Leeres workflow +
    # keine LoRAs = Override geloescht. ``model`` faellt weg (kommt aus dem Workflow).
    if workflow or clean_loras:
        prof["outfit_imagegen"] = {"workflow": workflow, "loras": clean_loras}
    else:
        prof["outfit_imagegen"] = {}
    save_character_profile(character_name, prof)
    return {"status": "ok", "workflow": workflow, "loras": clean_loras}


@router.get("/{character_name}/slot-overrides")
async def get_slot_overrides_route(character_name: str) -> Dict[str, Any]:
    """Liefert per-Slot Prompt+LoRA-Overrides (9 Slots).

    Struktur: {slot: {prompt: str, lora: {name, strength}}}.
    Greifen nur wenn der Slot leer und nicht verdeckt ist.
    """
    from app.models.character import get_character_profile
    from app.models.inventory import VALID_PIECE_SLOTS
    prof = get_character_profile(character_name) or {}
    raw = prof.get("slot_overrides") or {}
    if not isinstance(raw, dict):
        raw = {}
    out: Dict[str, Any] = {}
    for slot in VALID_PIECE_SLOTS:
        entry = raw.get(slot) or {}
        if not isinstance(entry, dict):
            entry = {}
        lora = entry.get("lora") or {}
        if not isinstance(lora, dict):
            lora = {}
        out[slot] = {
            "prompt": (entry.get("prompt") or "").strip(),
            "lora": {
                "name": (lora.get("name") or "").strip(),
                "strength": float(lora.get("strength", 1.0) or 1.0),
            },
        }
    return {"slots": out, "order": list(VALID_PIECE_SLOTS)}


@router.put("/{character_name}/slot-overrides")
async def set_slot_overrides_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Speichert per-Slot Prompt+LoRA-Overrides.

    Body: {slots: {slot: {prompt: str, lora: {name, strength}}}}.
    Leere Eintraege (kein Prompt + kein LoRA) werden entfernt.
    """
    from app.models.character import get_character_profile, save_character_profile
    from app.models.inventory import VALID_PIECE_SLOTS
    body = await request.json()
    slots_in = body.get("slots") or {}
    if not isinstance(slots_in, dict):
        slots_in = {}
    cleaned: Dict[str, Any] = {}
    for slot in VALID_PIECE_SLOTS:
        entry = slots_in.get(slot) or {}
        if not isinstance(entry, dict):
            continue
        prompt = (entry.get("prompt") or "").strip()
        lora_raw = entry.get("lora") or {}
        lora_name = ""
        lora_strength = 1.0
        if isinstance(lora_raw, dict):
            lora_name = (lora_raw.get("name") or "").strip()
            if lora_name.lower() == "none":
                lora_name = ""
            try:
                lora_strength = float(lora_raw.get("strength", 1.0))
            except Exception:
                lora_strength = 1.0
        if not prompt and not lora_name:
            continue
        out: Dict[str, Any] = {}
        if prompt:
            out["prompt"] = prompt
        if lora_name:
            out["lora"] = {"name": lora_name, "strength": lora_strength}
        cleaned[slot] = out
    prof = get_character_profile(character_name) or {}
    if cleaned:
        prof["slot_overrides"] = cleaned
    elif "slot_overrides" in prof:
        del prof["slot_overrides"]
    save_character_profile(character_name, prof)
    return {"status": "ok", "slots": cleaned}


# --- Profile (bulk read/update) ---

@router.get("/{character_name}/profile")
def get_profile_route(character_name: str) -> Dict[str, Any]:
    """Gibt das vollstaendige Character-Profil zurueck"""
    profile = get_character_profile(character_name)

    # Token-aufgeloeste Varianten der Appearance-Felder beilegen, damit das
    # Frontend (z.B. Profilbild-Generierung) den fertigen Text bekommt ohne
    # selbst Tokens parsen zu muessen.
    try:
        from app.models.character_template import (
            get_template, resolve_profile_tokens)
        _tmpl_id = profile.get("template", "") or ""
        _tmpl = get_template(_tmpl_id) if _tmpl_id else None
        for _key in ("character_appearance", "face_appearance"):
            _raw = (profile.get(_key) or "").strip()
            if not _raw or "{" not in _raw:
                continue
            _resolved = resolve_profile_tokens(
                _raw, profile, template=_tmpl, target_key="character_appearance")
            if _resolved and _resolved != _raw:
                if not isinstance(profile, dict):
                    profile = dict(profile)
                profile[f"{_key}_resolved"] = _resolved
    except Exception:
        pass

    # Ortsname auflösen damit der Editor den Namen zeigt statt der ID
    loc_id = profile.get("current_location", "")
    if loc_id:
        try:
            from app.models.world import get_location_name as _get_loc_name
            resolved = _get_loc_name(loc_id)
            if resolved:
                profile = dict(profile)
                profile["current_location"] = resolved
        except Exception:
            pass
    # Raumname auflösen (Room-ID → Name)
    room_id = profile.get("current_room", "")
    if room_id and loc_id:
        try:
            from app.models.world import get_location, get_room_by_id
            loc_data = get_location(loc_id)
            if loc_data:
                room = get_room_by_id(loc_data, room_id)
                if room and room.get("name"):
                    if not isinstance(profile, dict):
                        profile = dict(profile)
                    profile["current_room"] = room["name"]
        except Exception:
            pass
    return {"character": character_name, "profile": profile}


@router.post("/{character_name}/resolve-tokens")
async def resolve_tokens_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Live-Vorschau der Token-Ersetzungen ({hair_color} → "blonde", …).

    Nimmt einen Draft-Text (z.B. der gerade getippte Aussehen-Prompt) + den
    target_key (z.B. "character_appearance") und löst die Tokens gegen das
    aktuelle Profil + Template auf — kein Frontend-Nachbau, eine Backend-Quelle.
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
    from datetime import datetime as _dt
    from app.core.prompt_filters import load_filters

    profile = get_character_profile(character_name)
    active = profile.get("active_conditions", []) or []

    # Index: condition_name (lowercased) -> {icon, label, image_modifier}.
    # Filter-`id` ist der kanonische Condition-Name (neues Modell): wenn der
    # Tag in active_conditions auftaucht, triggert der Filter implizit. Wir
    # bauen den Lookup primaer ueber id; legacy-Filter mit `condition:<name>`-
    # Expression werden zusaetzlich als Alias indexiert, damit alte Daten
    # weiter ein Icon bekommen.
    meta_by_name: Dict[str, Dict[str, str]] = {}
    for f in load_filters():
        meta = {
            "icon": f.get("icon", "") or "",
            "label": f.get("label", "") or "",
            "image_modifier": f.get("image_modifier", "") or "",
        }
        fid = (f.get("id") or "").strip().lower()
        if fid:
            meta_by_name.setdefault(fid, dict(meta, label=meta["label"] or fid))
        cond_str = (f.get("condition") or "").strip()
        if cond_str.lower().startswith("condition:"):
            name = cond_str[10:].strip().lower()
            if name:
                meta_by_name.setdefault(name, dict(meta, label=meta["label"] or name))

    now = _dt.now()
    result = []
    for cond in active:
        name = (cond.get("name") or "").strip()
        if not name:
            continue
        # Abgelaufen?
        duration_h = cond.get("duration_hours", 0) or 0
        remaining_h = None
        if duration_h:
            try:
                started = _dt.fromisoformat(cond["started_at"])
                elapsed_s = (now - started).total_seconds()
                total_s = duration_h * 3600
                if elapsed_s > total_s:
                    continue
                remaining_h = round((total_s - elapsed_s) / 3600, 1)
            except (ValueError, KeyError):
                pass
        meta = meta_by_name.get(name.lower(), {})
        result.append({
            "name": name,
            "label": meta.get("label") or name,
            "icon": meta.get("icon", ""),
            "remaining_hours": remaining_h,
            "source": cond.get("source", ""),
        })
    return {"character": character_name, "conditions": result}


@router.post("/{character_name}/profile")
async def update_profile_route(character_name: str, request: Request) -> Dict[str, Any]:
    """Aktualisiert Character-Profil Felder (bulk update)"""
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        fields = data.get("fields", {})
        if not fields:
            raise HTTPException(status_code=400, detail="fields fehlt")

        profile = get_character_profile(character_name)

        # current_location: Name zurueck in ID aufloesen, damit die
        # Weltkarte den Character weiterhin findet (GET liefert den
        # aufgeloesten Namen, POST bekommt ihn zurueck).
        if "current_location" in fields:
            loc_val = fields["current_location"]
            if loc_val:
                from app.models.world import resolve_location, get_location_id
                loc_id = get_location_id(loc_val)
                if loc_id:
                    fields["current_location"] = loc_id
                else:
                    loc_obj = resolve_location(loc_val)
                    if loc_obj and loc_obj.get("id"):
                        fields["current_location"] = loc_obj["id"]

        # Filter out __custom__ sentinel values (UI placeholder for custom input)
        for k, v in list(fields.items()):
            if v == "__custom__":
                fields[k] = ""

        # Felder mit source_file gehoeren in MD-Files, NICHT ins JSON-Profil.
        # Falls jemand sie hier reinschickt, ignorieren — der Soul-Editor ist
        # zustaendig (siehe /characters/{char}/soul/*).
        _sf_keys = character_ops._soul_field_keys(profile.get("template", ""))
        for k in list(fields.keys()):
            if k in _sf_keys:
                fields.pop(k, None)

        profile.update(fields)
        save_character_profile(character_name, profile)
        return {"status": "success", "character": character_name,
                "updated_fields": list(fields.keys())}
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
        user_id = data.get("user_id", "")
        fields = data.get("fields", {})
        if not fields:
            raise HTTPException(status_code=400, detail="fields fehlt")

        config = get_character_config(character_name)
        config.update(fields)
        save_character_config(character_name, config)

        # Sofort-Wirkung des avatar_only_presence-Flags: an + ungesteuert ->
        # verschwinden; aus -> wieder auftauchen (idempotent).
        if "avatar_only_presence" in fields:
            try:
                from app.models.account import is_player_controlled
                from app.models.character import enter_offmap_sleep, appear_in_world
                on = str(fields.get("avatar_only_presence")).strip().lower() == "true"
                if on:
                    if not is_player_controlled(character_name):
                        enter_offmap_sleep(character_name)
                else:
                    appear_in_world(character_name)
            except Exception:
                pass

        return {"status": "success", "character": character_name, "updated_fields": list(fields.keys())}
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

    images_dir = get_character_images_dir(character_name)
    stem = Path(image_filename).stem
    video_path = images_dir / f"{stem}.mp4"

    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Keine Animation vorhanden")

    video_path.unlink()
    logger.info("Animation geloescht: %s", video_path.name)

    # animate_prompt und animate_created_at aus Metadaten entfernen
    from app.models.character import _load_single_image_meta, _save_single_image_meta
    meta = _load_single_image_meta(character_name, image_filename)
    changed = False
    for key in ("animate_prompt", "animate_created_at"):
        if key in meta:
            del meta[key]
            changed = True
    if changed:
        _save_single_image_meta(character_name, image_filename, meta)

    return {"status": "success", "deleted_video": f"{stem}.mp4"}


@router.post("/{character_name}/cleanup-images")
def cleanup_images_endpoint(character_name: str) -> Dict[str, Any]:
    """Loescht verwaiste Bilddateien die nicht im Profil registriert sind."""
    try:
        return cleanup_orphaned_images(character_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Reset Endpoints ---

@router.post("/reset/user/{user_id}")
def reset_user_profile() -> Dict[str, str]:
    """Setzt das komplette User-Profil zurueck"""
    try:
        import json
        from app.core.paths import get_storage_dir
        profile_path = get_storage_dir()

        for file in profile_path.glob("*.json"):
            if "_chat_" in file.name:
                continue
            try:
                data = json.loads(file.read_text())
                if isinstance(data, dict) and "_user_id" in data:
                    file.unlink()
                    break
            except:
                pass

        return {"status": "success", "message": "User profile reset"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset/character/{user_id}")
def reset_character_selection() -> Dict[str, str]:
    """Setzt die Character-Auswahl zurueck"""
    try:
        set_current_character("")
        return {"status": "success", "message": "Character selection reset"}
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
        skill_manager = get_skill_manager()
        skills = []
        for skill in skill_manager.skills:
            skill_id = skill.SKILL_ID
            if not skill_id:
                continue
            config = get_character_skill_config(character_name, skill_id)
            # Default: ALWAYS_LOAD Skills starten deaktiviert, andere aktiviert
            default_enabled = not getattr(skill, 'ALWAYS_LOAD', False)
            enabled = default_enabled
            if config and "enabled" in config:
                enabled = bool(config["enabled"])

            # Config fields with defaults, types, and current values
            config_fields = skill.get_config_fields()
            if config_fields:
                for field_name, field_info in config_fields.items():
                    if config and field_name in config:
                        field_info["value"] = config[field_name]
                    else:
                        field_info["value"] = field_info["default"]

            skills.append({
                "skill_id": skill_id,
                "name": skill.name,
                "description": skill.description,
                "enabled": enabled,
                "config_fields": config_fields if config_fields else None,
            })

        # Location-Liste fuer Skill-Config-Felder vom Typ "locations"
        from app.models.world import list_locations
        all_locations = [{"id": loc.get("id", ""), "name": loc.get("name", "")}
                         for loc in list_locations() if loc.get("id")]

        return {"skills": skills, "locations": all_locations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Soul Editor — MD-Files unter characters/{Char}/soul/
# ---------------------------------------------------------------------------

# File-Default-Whitelist (single source of truth fuer Soul-Editor-UI)
from app.core.soul_sections import (
    EDITABLE_SECTIONS as _SOUL_EDITABLE,
    LOCKED_SECTIONS as _SOUL_LOCKED,
    SECTION_FILE_MAP as _SOUL_FILE_MAP,
    EDITABLE_MARKER as _SOUL_EDITABLE_MARKER)


def _parse_soul_sections(text: str) -> List[Dict[str, Any]]:
    """Zerlegt MD-Text in {heading, body, has_editable_marker} Sections.

    Top-`# Heading` wird als 'top' Section markiert. Body ist Roh-Inhalt
    OHNE den EDITABLE-Marker (UI rendert Status-Indikator separat).
    """
    sections = []
    cur_h = None
    cur_lvl = 0
    cur_body: List[str] = []

    def _flush():
        if cur_h is None and not cur_body:
            return
        body_lines = list(cur_body)
        # EDITABLE-Marker erkennen + aus body entfernen
        has_marker = any(_SOUL_EDITABLE_MARKER in ln for ln in body_lines)
        clean_body = [ln for ln in body_lines if _SOUL_EDITABLE_MARKER not in ln]
        body_text = "\n".join(clean_body).strip()
        sections.append({
            "level": cur_lvl,
            "heading": cur_h or "",
            "body": body_text,
            "editable_marker": has_marker,
        })

    for line in text.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            _flush()
            cur_h = line[2:].strip()
            cur_lvl = 1
            cur_body = []
        elif line.startswith("## "):
            _flush()
            cur_h = line[3:].strip()
            cur_lvl = 2
            cur_body = []
        else:
            cur_body.append(line)
    _flush()
    return sections


def _soul_file_meta(section_id: str) -> Dict[str, Any]:
    """Gibt Meta zu einer Soul-Datei: file-default lock-status + path."""
    if section_id in _SOUL_EDITABLE:
        default = "editable"
    elif section_id in _SOUL_LOCKED:
        default = "locked"
    else:
        default = "unknown"
    return {
        "section": section_id,
        "file_default": default,
        "path": _SOUL_FILE_MAP.get(section_id, ""),
    }


def _is_soul_section_enabled(character_name: str, section_id: str) -> bool:
    """Prueft ob die Soul-Section per Template-Feature aktiviert ist.

    'personality' / 'tasks' / 'presence' sind ungated → immer.
    Andere ueber Template-Feature. beliefs/lessons/goals sind zusaetzlich
    an den Retrospect-Master-Switch gekoppelt — wenn der Char per UI
    Retrospect deaktiviert hat, fallen die drei Sections aus dem Soul-Tab
    raus, unabhaengig davon was das Template fuer beliefs/lessons/goals
    sagt.
    """
    if section_id in ("personality", "tasks", "presence"):
        return True
    feature_map = {
        "roleplay_rules": "roleplay_rules_enabled",
        "beliefs":        "beliefs_enabled",
        "lessons":        "lessons_enabled",
        "goals":          "goals_enabled",
        "soul":           "soul_enabled",
    }
    feature = feature_map.get(section_id)
    if not feature:
        return False
    try:
        from app.models.character_template import is_feature_enabled
        # Retrospect-Master-Switch: schaltet die drei Output-Sections
        # gemeinsam ab.
        if section_id in ("beliefs", "lessons", "goals"):
            if not is_feature_enabled(character_name, "retrospect_enabled"):
                return False
        return is_feature_enabled(character_name, feature)
    except Exception:
        return True


@router.get("/{character_name}/soul/files")
def get_soul_files(character_name: str) -> Dict[str, Any]:
    """Listet die fuer diesen Character verfuegbaren Soul-MD-Dateien auf.

    Berucksichtigt Template-Feature-Gates. Gibt pro Datei: section-id,
    file_default lock-status, ob die Datei existiert.
    """
    from app.models.character import get_character_dir, get_character_profile
    char_dir = get_character_dir(character_name)

    # Freundliche Labels aus dem Template: source_file-Basename (= section-id) →
    # Feld-Label/-label_de. Damit zeigt der Soul-Tab „Roleplay Rules" statt
    # „Roleplay_rules".
    import os as _os
    label_map: Dict[str, Dict[str, str]] = {}
    try:
        from app.models.character_template import get_template
        _prof = get_character_profile(character_name) or {}
        _tmpl = get_template(_prof.get("template", "")) if _prof.get("template") else None
        for _sec in (_tmpl or {}).get("sections", []):
            for _f in _sec.get("fields", []):
                _sf = _f.get("source_file") or ""
                if not _sf:
                    continue
                _sid = _os.path.basename(_sf)
                if _sid.endswith(".md"):
                    _sid = _sid[:-3]
                label_map[_sid] = {
                    "label": _f.get("label") or "",
                    "label_de": _f.get("label_de") or "",
                }
    except Exception:
        pass

    files = []
    for section_id in ("personality", "tasks", "presence", "roleplay_rules",
                        "beliefs", "lessons", "goals", "soul"):
        if not _is_soul_section_enabled(character_name, section_id):
            continue
        meta = _soul_file_meta(section_id)
        meta["exists"] = (char_dir / meta["path"]).exists()
        _lbl = label_map.get(section_id, {})
        meta["label"] = _lbl.get("label", "")
        meta["label_de"] = _lbl.get("label_de", "")
        files.append(meta)
    return {"character": character_name, "files": files}


@router.get("/{character_name}/soul/file/{section_id}")
def get_soul_file(character_name: str, section_id: str) -> Dict[str, Any]:
    """Liefert Inhalt + parsed Sections einer Soul-MD-Datei."""
    if section_id not in _SOUL_FILE_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section_id}")
    if not _is_soul_section_enabled(character_name, section_id):
        raise HTTPException(status_code=403, detail=f"Section '{section_id}' nicht im Template aktiv")

    from app.models.character import get_character_dir
    char_dir = get_character_dir(character_name)
    md_path = char_dir / _SOUL_FILE_MAP[section_id]

    raw = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    sections = _parse_soul_sections(raw)
    meta = _soul_file_meta(section_id)
    return {
        "character": character_name,
        "section": section_id,
        "path": meta["path"],
        "file_default": meta["file_default"],
        "raw": raw,
        "sections": sections,
        "editable_marker_token": _SOUL_EDITABLE_MARKER,
    }


@router.post("/{character_name}/soul/file/{section_id}")
async def save_soul_file(character_name: str, section_id: str, request: Request) -> Dict[str, Any]:
    """Schreibt komplette Soul-MD-Datei.

    Body: {"user_id": "...", "content": "...full MD text..."}
    """
    if section_id not in _SOUL_FILE_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section_id}")
    data = await request.json()
    user_id = data.get("user_id", "")
    content = data.get("content", "")
    if not _is_soul_section_enabled(character_name, section_id):
        raise HTTPException(status_code=403, detail=f"Section '{section_id}' nicht im Template aktiv")

    from app.models.character import get_character_dir
    char_dir = get_character_dir(character_name)
    md_path = char_dir / _SOUL_FILE_MAP[section_id]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    # Trailing newline garantieren, ohne ueberflüssige zu sammeln
    md_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {"status": "success", "section": section_id, "size": len(content)}


@router.put("/{character_name}/skills/{skill_name}/enabled")
async def toggle_character_skill(character_name: str, skill_name: str, request: Request) -> Dict[str, Any]:
    """Toggles a skill enabled/disabled for a character."""
    try:
        data = await request.json()
        user_id = data.get("user_id", "")
        enabled = data.get("enabled", True)

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
    from app.models.account import get_user_profile, get_active_character
    from app.models.character import get_single_image_meta

    body = await request.json()
    user_id = body.get("user_id", "")

    all_chars = list_available_characters()
    user_profile = get_user_profile()
    # user_name = Login-Name (z.B. "admin") — ist KEINE Person die in einem
    # Bild auftauchen kann. Avatar ist der vom User gespielte Character.
    avatar_name = (get_active_character() or "").strip()
    user_name = avatar_name  # Fuer Detection (Filename-Match etc.) den Avatar nutzen

    # 1. Primaer: explizit gespeicherte character_names aus vorheriger Auswahl
    meta = get_single_image_meta(character_name, image_name)
    saved_names = (meta or {}).get("character_names")
    detected_names = []
    if saved_names and isinstance(saved_names, list):
        detected_names = saved_names
    else:
        # 2. Fallback: canonical.persons aus dem Generate-Zeitpunkt — das ist
        #    die zuverlaessigste Quelle, weil sie genau die Personen enthaelt
        #    die der Prompt-Builder ins Bild gepackt hat. Nur Nicht-Agent
        #    persons (= im Bild sichtbar, nicht der Photographer-Avatar).
        canonical = (meta or {}).get("canonical") or {}
        canon_persons = canonical.get("persons") or []
        if isinstance(canon_persons, list):
            for p in canon_persons:
                if not isinstance(p, dict):
                    continue
                _n = (p.get("name") or "").strip()
                if _n and _n not in detected_names:
                    detected_names.append(_n)

        # 3. Fallback: aus reference_images ableiten — aber NUR Person-Slots,
        #    keine Background-/Location-Refs (sonst wird der Avatar faelschlich
        #    detected weil das BG-Bild zufaellig im User-Image-Dir liegt).
        if not detected_names:
            ref_images = meta.get("reference_images", {}) if meta else {}
            _BG_SLOT_HINTS = ("background", "location", "scene", "_4", "room")
            for _slot, ref_filename in ref_images.items():
                _slot_lower = (_slot or "").lower()
                if any(h in _slot_lower for h in _BG_SLOT_HINTS):
                    continue  # Background/Location-Slot, keine Person
                matched = False
                # a) Dateiname beginnt mit Character-Name
                for c in all_chars:
                    if ref_filename.startswith(c + "_"):
                        if c not in detected_names:
                            detected_names.append(c)
                        matched = True
                        break
                if matched:
                    continue
                # b) Datei in Character-Verzeichnissen suchen (Images, Outfits, Variants)
                for c in all_chars:
                    _imgs_dir = get_character_images_dir(c)
                    _outfits_dir = get_character_outfits_dir(c)
                    _variants_dir = _outfits_dir / "variants"
                    if ((_imgs_dir / ref_filename).exists()
                            or (_outfits_dir / ref_filename).exists()
                            or (_variants_dir / ref_filename).exists()):
                        if c not in detected_names:
                            detected_names.append(c)
                        matched = True
                        break
                # c) User-Profilbild — nur wenn Slotname NICHT als BG identifiziert wurde
                #    (oben schon abgefangen)
                if not matched and user_name and user_name not in detected_names:
                    from app.models.account import get_user_images_dir
                    _user_imgs = get_user_images_dir()
                    if (_user_imgs / ref_filename).exists():
                        detected_names.append(user_name)

        # 4. Letzter Fallback: Prompt-basierte Erkennung
        if not detected_names:
            prompts = get_character_image_prompts(character_name)
            prompt = prompts.get(image_name, "")
            if prompt:
                from app.core.prompt_builder import PromptBuilder
                _pb = PromptBuilder(character_name)
                _persons = _pb.detect_persons(prompt)
                appearances = [{"name": p.name, "appearance": p.appearance} for p in _persons]
                detected_names = [p["name"] for p in appearances]

    # Underscore-Prefix-Filter (Sicherheitsnetz fuer System-Characters wie
    # _messaging_frame, falls list_available_characters cached o.ae.)
    all_chars = [c for c in all_chars if not c.startswith("_")]

    # "Agent" = der Charakter der das Bild ERSTELLT hat. Bei Bildern die ein
    # NPC dem Avatar geschickt hat (gallery_character != ersteller), steht
    # der Ersteller in meta.from_character. Sonst ist es der gallery_owner.
    agent_name = (meta or {}).get("from_character") or character_name
    available = []
    if agent_name and agent_name in all_chars:
        available.append({"name": agent_name, "type": "agent"})
    if user_name and user_name != agent_name:
        available.append({"name": user_name, "type": "user"})
    for c in all_chars:
        if c != agent_name and c != user_name:
            available.append({"name": c, "type": "character"})

    # Rooms der aktuellen Location (fuer Room-Auswahl im Dialog)
    rooms = []
    current_room_id = ""
    location_id = (meta or {}).get("location", "")
    if not location_id:
        location_id = get_character_current_location(character_name) or ""
    if location_id:
        from app.models.world import get_location
        loc_data = get_location(location_id)
        if loc_data:
            for room in loc_data.get("rooms", []):
                rooms.append({"id": room.get("id", ""), "name": room.get("name", "")})
        current_room_id = (meta or {}).get("room_id", "")
        # Room aus Slot-4 Hintergrundbild ableiten wenn nicht explizit gespeichert
        if not current_room_id:
            ref_images = meta.get("reference_images", {}) if meta else {}
            slot4_filename = ref_images.get("input_reference_image_4", "")
            if slot4_filename and loc_data:
                from app.models.world import get_gallery_image_rooms
                _img_rooms = get_gallery_image_rooms(location_id)
                _matched_room = _img_rooms.get(slot4_filename, "")
                if _matched_room:
                    current_room_id = _matched_room
        # Kein Fallback auf aktuellen Raum — wenn nicht bekannt, leer lassen

    return {
        "detected": detected_names,
        "available": available,
        "rooms": rooms,
        "current_room_id": current_room_id,
        "location_id": location_id,
    }


@router.post("/{character_name}/images/{image_name}/regenerate")
async def regenerate_character_image(character_name: str, image_name: str, request: Request) -> Dict[str, Any]:
    """Regeneriert ein Bild mit der ImageGenerationSkill-Pipeline.

    Nutzt den gespeicherten Prompt, optional verbessert durch User-Feedback,
    und generiert ein neues Bild das das alte ersetzt.
    """
    from app.skills.image_regenerate import regenerate_image
    from app.models.character import add_character_image_prompt

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

    def _run_regen():
        try:
            _success, final_prompt, actual_path = regenerate_image(character_name, str(image_path),
                prompt, improvement_request, workflow_name, backend_name, agent_config,
                loras=loras,
                model_override=model_override,
                character_names=character_names,
                room_id=room_id,
                location_id=original_location_id,
                negative_prompt_override=negative_prompt_override,
                track_id=_track_id,
                create_new=bool(create_new),
                use_room=bool(use_room),
                use_source_as_reference=use_source_as_reference,
                source_image_path=str(image_path))
            _actual_filename = Path(actual_path).name
            if final_prompt != prompt:
                add_character_image_prompt(character_name, _actual_filename, final_prompt)
            _tq.track_finish(_track_id)
        except Exception as e:
            logger.error("Bild-Regenerierung fehlgeschlagen: %s", e)
            _tq.track_finish(_track_id, error=str(e))

    import threading
    threading.Thread(target=_run_regen, daemon=True).start()
    return {"status": "started", "image": image_name, "track_id": _track_id}


@router.post("/{character_name}/enhance-image-prompt")
async def enhance_image_prompt(character_name: str, request: Request) -> Dict[str, Any]:
    """Verbessert einen Image-Prompt via LLM direkt im Dialog.

    Body: { user_id, prompt, improvement_request, llm_override? }
    Returns: { prompt: "verbesserter prompt" }
    """
    body = await request.json()
    user_id = body.get("user_id", "")

    prompt = body.get("prompt", "").strip()
    improvement_request = body.get("improvement_request", "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt fehlt")
    if not improvement_request:
        raise HTTPException(status_code=400, detail="improvement_request fehlt")

    agent_config = get_character_config(character_name)
    from app.skills.image_regenerate import enhance_prompt
    # enhance_prompt macht einen blocking LLM-Call → Threadpool, sonst
    # blockiert der Event-Loop bis das Tool-LLM antwortet (~1s+).
    import asyncio as _asyncio
    enhanced = await _asyncio.to_thread(
        enhance_prompt, prompt, improvement_request, agent_config)
    return {"prompt": enhanced}


@router.post("/{character_name}/rebuild-image-prompt")
async def rebuild_image_prompt(character_name: str, request: Request) -> Dict[str, Any]:
    """Rebuilds the image prompt based on the adapter of the target backend.

    Source of the values (mood, outfit, expression, location, ...):
      1. PRIMARY: saved `canonical` dict from the image.json (from creation time)
      2. FALLBACK: current character state (only for old images without canonical)

    Body: { user_id, workflow? (backend match spec), canonical?, scene_text? }
    Returns: { prompt, target_model, source: "saved"|"current" }
    """
    import asyncio

    body = await request.json()
    user_id = body.get("user_id", "")
    workflow_name = body.get("workflow", "").strip()
    saved_canonical = body.get("canonical") or None
    scene_text = body.get("scene_text", "").strip()
    location_id = body.get("location_id", "").strip()
    room_id = body.get("room_id", "").strip()
    reference_images = body.get("reference_images") or {}

    def _build():
        # Closure: location_id/room_id sind im outer scope nonlocal
        nonlocal location_id, room_id

        # Fallback: location_id/room_id aus reference_image_4 (Slot 4 = Raum-Hintergrund) ableiten
        if not (location_id or room_id) and reference_images:
            ref_room_img = reference_images.get("input_reference_image_4", "")
            if ref_room_img:
                try:
                    from app.models.world import find_room_by_gallery_image
                    _loc_from_ref, _room_from_ref = find_room_by_gallery_image(ref_room_img)
                    if _loc_from_ref:
                        location_id = location_id or _loc_from_ref
                        room_id = room_id or _room_from_ref
                        logger.info("rebuild: location/room aus Reference-Image '%s' aufgeloest (loc=%s room=%s)",
                                    ref_room_img, location_id, room_id)
                except Exception as _e:
                    logger.debug("Reference-Image-Aufloesung fehlgeschlagen: %s", _e)

        from app.core.dependencies import get_skill_manager
        sm = get_skill_manager()
        img_skill = None
        for skill in sm.skills:
            if skill.__class__.__name__ == "ImageGenerationSkill":
                img_skill = skill
                break
        if not img_skill:
            raise HTTPException(status_code=503, detail="ImageGenerationSkill nicht verfuegbar")

        from app.core.prompt_adapters import (
            get_target_model, render as adapter_render,
            maybe_enhance_via_llm, dict_to_canonical)

        # Target model from the backend that would render for this character
        # (explicit spec from the request wins, otherwise the agent's backend).
        _be = img_skill.resolve_imagegen_target(workflow_name) if workflow_name else None
        if not _be:
            _be = img_skill._select_backend_for_agent(character_name)
        target_model = get_target_model(
            getattr(_be, "image_family", "") if _be else "",
            getattr(_be, "model", "") if _be else "")

        # 1) PRIMAERE Quelle: gespeichertes canonical
        if saved_canonical and isinstance(saved_canonical, dict):
            pv = dict_to_canonical(saved_canonical)
            # Style/Negative bleiben wie gespeichert; der finale Style kommt beim
            # echten Generieren aus dem Use-Case (image_generation_skill).

            # sanitize_scene_prompt auch beim Rebuild ausfuehren — damit der
            # neue Outfit-Extraction-Filter (wearing/posing/dressed) auch fuer
            # Re-Creations greift. Sanitize ist idempotent: bei bereits
            # bereinigten scenes findet es nichts und bleibt no-op.
            if pv.scene_prompt:
                from app.core.prompt_builder import PromptBuilder as _PB
                _rebuild_builder = _PB(character_name)
                pv.scene_prompt = _rebuild_builder.sanitize_scene_prompt(pv.scene_prompt, pv)

            # Outfit-Enrichment: Wenn canonical.outfits leer aber reference_image_1
            # vorhanden, das Outfit ueber die Bild-Datei aufloesen
            if not pv.prompt_outfits and reference_images:
                ref1 = reference_images.get("input_reference_image_1", "")
                if ref1:
                    try:
                        from app.models.character import find_outfit_by_image
                        _outfit = find_outfit_by_image(character_name, ref1)
                        if _outfit:
                            _outfit_text = (_outfit.get("outfit") or "").strip()
                            if _outfit_text:
                                _label = pv.persons[0].actor_label if pv.persons else character_name
                                pv.prompt_outfits[1] = f"{_label} is wearing {_outfit_text}"
                                logger.info("rebuild: Outfit '%s' aus Reference-Image '%s' aufgeloest",
                                            _outfit.get("name", "?"), ref1)
                    except Exception as _e:
                        logger.debug("Outfit-Enrichment fehlgeschlagen: %s", _e)
            # Location-Enrichment: wenn canonical.location zu kurz (nur Name, keine Description),
            # aus world.json den Raum-Description nachladen
            if pv.prompt_location and len(pv.prompt_location) < 30 and (location_id or room_id):
                try:
                    from app.models.world import get_location, get_room_by_id
                    from datetime import datetime as _dt
                    _loc_data = get_location(location_id) if location_id else None
                    if _loc_data:
                        _hour = _dt.now().hour
                        _is_day = 6 <= _hour < 18
                        _desc = ""
                        # Raum bevorzugt
                        if room_id:
                            _room = get_room_by_id(_loc_data, room_id)
                            if _room:
                                _desc = (_room.get("image_prompt_day", "") if _is_day else _room.get("image_prompt_night", "")) \
                                        or _room.get("description", "")
                        if not _desc:
                            _desc = (_loc_data.get("image_prompt_day", "") if _is_day else _loc_data.get("image_prompt_night", "")) \
                                    or _loc_data.get("description", "")
                        if _desc:
                            pv.prompt_location = f"{pv.prompt_location}, {_desc}"
                            logger.info("rebuild: Location enriched fuer kurze canonical.location (room=%s loc=%s)",
                                        room_id, location_id)
                except Exception as _e:
                    logger.debug("Location-Enrichment fehlgeschlagen: %s", _e)
            source = "saved"
        else:
            # 2) FALLBACK: aktueller State (nur fuer alte Bilder ohne canonical)
            from app.core.prompt_builder import PromptBuilder, EntryPointConfig
            builder = PromptBuilder(character_name)
            persons = builder.detect_persons(scene_text or "")
            pv = builder.collect_context(
                persons, EntryPointConfig.chat(),
                prompt_text=scene_text or "",
                photographer_mode=False,
                set_profile=False)
            if scene_text:
                pv.scene_prompt = builder.sanitize_scene_prompt(scene_text, pv)
            # The final style/negative comes from the use-case at real
            # generation time (image_generation_skill) — plain default here.
            pv.prompt_style = "photorealistic"
            pv.negative_prompt = ""
            source = "current"

            # Outfit-Enrichment auch im current-state Pfad: bei Bildern ohne canonical
            # versuchen das ORIGINAL-Outfit ueber reference_image_1 wiederherzustellen
            # (statt das aktuelle Char-Outfit zu nutzen).
            if reference_images:
                ref1 = reference_images.get("input_reference_image_1", "")
                if ref1:
                    try:
                        from app.models.character import find_outfit_by_image
                        _outfit = find_outfit_by_image(character_name, ref1)
                        if _outfit:
                            _outfit_text = (_outfit.get("outfit") or "").strip()
                            if _outfit_text and persons:
                                _label = persons[0].actor_label or character_name
                                pv.prompt_outfits[1] = f"{_label} is wearing {_outfit_text}"
                                logger.info("rebuild (current): Outfit '%s' aus Reference-Image '%s' aufgeloest",
                                            _outfit.get("name", "?"), ref1)
                                source = "current+ref_outfit"
                    except Exception as _e:
                        logger.debug("Outfit-Enrichment fehlgeschlagen: %s", _e)

        assembled = adapter_render(pv, target_model)
        template_prompt = assembled["input_prompt_positiv"]

        # No LLM enhancement for the rebuild preview — the instruction lives
        # in the use-case config and is applied at real generation time.
        final_prompt, _method = maybe_enhance_via_llm(
            template_prompt, pv,
            target_model=target_model,
            prompt_instruction="")
        return {"prompt": final_prompt, "target_model": target_model, "source": source}

    return await asyncio.to_thread(_build)


@router.post("/{character_name}/images/{image_name}/suggest-animate-prompt")
async def suggest_animate_prompt(character_name: str, image_name: str, request: Request) -> Dict[str, str]:
    """Generiert einen Animation-Prompt basierend auf der Bildanalyse via Tools-LLM."""
    import asyncio

    body = await request.json()
    user_id = body.get("user_id", "")
    custom_system_prompt = body.get("system_prompt", "")
    llm_override = body.get("llm_override", "").strip()

    images_dir = get_character_images_dir(character_name)
    image_path = images_dir / image_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")

    def _generate_prompt() -> str:
        from app.models.character import _load_single_image_meta
        meta = _load_single_image_meta(character_name, image_name)

        # Bildanalyse aus Metadaten lesen oder neu generieren
        image_analysis = meta.get("image_analysis", "")
        if not image_analysis:
            logger.info("[suggest-animate] Keine Bildanalyse vorhanden, generiere neu...")
            try:
                from app.skills.image_generation_skill import ImageGenerationSkill
                skill = ImageGenerationSkill({})
                image_analysis = skill._generate_image_analysis(str(image_path), character_name)
                if image_analysis:
                    logger.info("[suggest-animate] Bildanalyse generiert (%d Zeichen)", len(image_analysis))
                    add_character_image_metadata(character_name, image_name, {
                        "image_analysis": image_analysis,
                    })
            except Exception as e:
                logger.warning("[suggest-animate] Bildanalyse fehlgeschlagen: %s", e)

        if not image_analysis:
            raise ValueError("Bildanalyse nicht verfuegbar")

        logger.info("[suggest-animate] Bildanalyse vorhanden (%d Zeichen), rufe LLM auf... (llm_override=%s)", len(image_analysis), llm_override or "")

        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        default_system, user_prompt = render_task(
            "animation_prompt", image_analysis=image_analysis)
        system_content = custom_system_prompt or default_system
        response = llm_call(
            task="instagram_caption",
            system_prompt=system_content,
            user_prompt=user_prompt,
            agent_name=character_name)
        result = (response.content or "").strip().strip('"').strip("'")
        logger.info("[suggest-animate] Prompt generiert: %s", result[:100])
        return result

    try:
        prompt = await asyncio.get_event_loop().run_in_executor(None, _generate_prompt)
        return {"prompt": prompt}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("[suggest-animate] Fehlgeschlagen: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


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

    from app.core.task_queue import get_task_queue
    _tq = get_task_queue()
    _track_id = _tq.track_start(
        "image_animate", "Bild animieren", agent_name=character_name,
        start_running=False)

    def _run_animate():
        _tq.track_activate(_track_id)
        try:
            from app.skills.animate import animate_image
            from datetime import datetime
            from app.core.llm_queue import get_llm_queue, Priority as _P

            stem = Path(image_name).stem
            video_name = f"{stem}.mp4"
            output_path = str(images_dir / video_name)

            # Run via provider queue (serialization + queue-panel visibility).
            # gpu_type = the animation service id ("together"), which matches
            # a channel of the same type if one exists.
            success = get_llm_queue().submit_gpu_task(
                provider_name=service,
                task_type="image_animate",
                priority=_P.IMAGE_GEN,
                callable_fn=lambda: animate_image(
                    str(image_path), prompt, output_path, service=service),
                agent_name=character_name,
                label="Animation",
                gpu_type=service)

            if not success:
                _tq.track_finish(_track_id, error="Animation fehlgeschlagen")
                return

            # Video-Info in bestehende Bild-Metadaten schreiben
            add_character_image_metadata(character_name, image_name, {
                "animate_prompt": prompt,
                "animate_created_at": utc_now_iso(),
            })
            _tq.track_finish(_track_id)
        except Exception as e:
            logger.error("Animation fehlgeschlagen: %s", e)
            _tq.track_finish(_track_id, error=str(e))

    import threading
    threading.Thread(target=_run_animate, daemon=True).start()
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
    sm = get_skill_manager()
    imagegen = sm.get_skill("image_generation")
    if not imagegen:
        raise HTTPException(status_code=404, detail="ImageGeneration skill not found")

    # Re-probe currently unavailable backends — otherwise the dialog keeps
    # showing a backend as "not available" even though the service came back
    # online in the meantime. The recovery hook in check_availability also
    # triggers channel_health.force_poll(), so downstream GPU routing
    # decisions see the fresh status too.
    for _b in imagegen.backends:
        if _b.instance_enabled and not _b.available:
            try:
                _b.check_availability()
            except Exception:
                pass

    agent_config = get_character_skill_config(character_name, "image_generation") or {}

    # Collect all available generation options (backends only).
    options = []
    agent_instances = agent_config.get("instances", {})
    for b in imagegen.backends:
        if not b.available:
            continue
        # Per-agent enabled check
        agent_inst = agent_instances.get(b.name, {})
        is_enabled = bool(agent_inst["enabled"]) if "enabled" in agent_inst else b.instance_enabled
        if not is_enabled:
            continue
        # Derive target style from image family / backend model name (e.g.
        # Qwen-Image -> qwen, FLUX -> flux, Z-Image URN -> z_image).
        try:
            from app.core.prompt_adapters import get_target_model as _gtm
            _target_style = _gtm(
                getattr(b, "image_family", "") or "", getattr(b, 'model', "") or "")
        except Exception:
            _target_style = "z_image"
        opt = {
            "type": "backend",
            "name": b.name,
            "label": b.name,
            "negative_prompt": getattr(b, 'negative_prompt', ""),
            "cost": b.cost,
            "available": True,
            "target_model": _target_style,
            "ref_slot_count": int(getattr(b, "ref_slot_count", 0) or 0),
        }
        # Backend with a model list (e.g. Together.ai) — offer as a selection.
        backend_models = getattr(b, 'available_models', [])
        if backend_models:
            opt["models"] = backend_models
            opt["default_model"] = getattr(b, 'model', backend_models[0])
        options.append(opt)

    # Sort by cost — the UI can show "cheapest first".
    options.sort(key=lambda o: (o.get("cost") if o.get("cost") is not None else 999999, o.get("label", "")))

    # Default preselection per area from .env
    defaults = {}
    for env_key, area in [
        ("OUTFIT_IMAGEGEN_DEFAULT", "outfit"),
        ("EXPRESSION_IMAGEGEN_DEFAULT", "expression"),
        ("LOCATION_IMAGEGEN_DEFAULT", "location"),
        ("SKILL_INSTAGRAM_IMAGEGEN_DEFAULT", "instagram"),
    ]:
        val = os.environ.get(env_key, "").strip()
        if val:
            defaults[area] = val  # e.g. "backend:CivitAI"

    return {
        "character": character_name,
        "options": options,
        "defaults": defaults,
    }


# --- VideoGeneration Skill Config ---

@router.get("/{character_name}/skills/video_generation/options")
def get_videogen_options(character_name: str) -> Dict[str, Any]:
    """Returns all selection options for the VideoGen config:
    ImageGen backends/models/LoRAs + animation services/LoRAs."""
    sm = get_skill_manager()

    # --- ImageGen options (backends) ---
    imagegen = sm.get_skill("image_generation")
    imagegen_options = []
    if imagegen:
        for b in imagegen.backends:
            if not b.available:
                continue
            opt: Dict[str, Any] = {
                "type": "backend",
                "name": b.name,
                "label": b.name,
            }
            backend_models = getattr(b, 'available_models', [])
            if backend_models:
                opt["models"] = backend_models
                opt["default_model"] = getattr(b, 'model', backend_models[0])
            imagegen_options.append(opt)

    # --- Animation options ---
    from app.skills.animate import get_animate_services
    animate_services = get_animate_services()

    # --- Current per-character config ---
    current_config = get_character_skill_config(character_name, "video_generation") or {}

    return {
        "imagegen_options": imagegen_options,
        "animate_services": animate_services,
        "current_config": {
            "imagegen_backend": current_config.get("imagegen_backend", ""),
            "imagegen_workflow": current_config.get("imagegen_workflow", ""),
            "imagegen_model": current_config.get("imagegen_model", ""),
            "imagegen_loras": current_config.get("imagegen_loras", []),
            "animate_service": current_config.get("animate_service", ""),
        },
    }


@router.post("/{character_name}/skills/video_generation/config")
async def save_videogen_config(character_name: str, request: Request) -> Dict[str, Any]:
    """Speichert die VideoGen-Config (ImageGen + Animation Einstellungen)."""
    data = await request.json()
    user_id = data.get("user_id", "").strip()

    config = get_character_skill_config(character_name, "video_generation") or {}

    # ImageGen-Felder
    for key in ("imagegen_backend", "imagegen_workflow", "imagegen_model", "animate_service"):
        if key in data:
            config[key] = str(data[key]).strip()

    # LoRA-Listen normalisieren
    def _normalize_loras(loras):
        if not loras:
            return []
        out = []
        for l in loras:
            name = (l.get("name") or "").strip() or "None"
            try:
                strength = float(l.get("strength", 1.0))
            except (TypeError, ValueError):
                strength = 1.0
            out.append({"name": name, "strength": strength})
        return out

    for key in ("imagegen_loras",):
        if key in data:
            config[key] = _normalize_loras(data[key])

    save_character_skill_config(character_name, "video_generation", config)
    return {"status": "success"}


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
                   offset: int = 0) -> Dict[str, Any]:
    """Tab "Verlauf": daily | weekly | monthly | history | diary | evolution.

    Standard: `daily` (letzte 60 Eintraege ueber alle Partner).
    """
    return character_ops.build_memory_history(
        character_name, kind=kind, limit=limit, offset=offset)
