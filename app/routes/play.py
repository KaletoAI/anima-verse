"""Player-UI — eigene Seite unter ``/play`` (plan-room-conversation Phase 2).

Bewusst getrennt vom Game-Admin: die Player-UI ist in-world und User-gated
(nicht admin). Sie zeigt die *wahrgenommene* aktuelle Raum-Szene des aktiven
Avatars — read-only in diesem Schritt; Äußerungen senden kommt als Nächstes.

Die gebaute Shell liegt (wie game-admin) unter ``static/game_admin/play.html``
— derselbe ``frontend/``-Build, aber eine eigene Seite/Route.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.core.auth_dependency import get_current_user
from app.core.log import get_logger

logger = get_logger("play")

router = APIRouter()

_SHELL = Path("static/game_admin/play.html")


def _expr_version(name: str) -> str:
    """Cache-Buster-Token für das Expression-Bild: ändert sich bei Mood-, Activity-
    oder Outfit-Wechsel UND wenn eine neue Variante fertig generiert wurde (Mtime
    der gecachten Variante). Frontend hängt ihn an die outfit-expression-URL →
    Bild lädt nur bei echter Änderung neu (event-getrieben, kein Blind-Polling)."""
    import hashlib
    import os
    from app.models.character import (get_character_current_feeling,
                                      get_character_current_activity)
    from app.models.inventory import get_equipped_pieces, get_equipped_items
    mood = activity = ""
    eqp: dict = {}
    eqi: list = []
    try:
        mood = get_character_current_feeling(name) or ""
        activity = get_character_current_activity(name) or ""
        eqp = get_equipped_pieces(name) or {}
        eqi = get_equipped_items(name) or []
    except Exception:
        pass
    mtime = ""
    try:
        from app.core.expression_regen import peek_cached_expression
        p = peek_cached_expression(name, mood, activity,
                                   equipped_pieces=eqp, equipped_items=eqi)
        if p:
            mtime = str(int(os.path.getmtime(p)))
    except Exception:
        pass
    eq_sig = ",".join(f"{k}:{v}" for k, v in sorted(eqp.items())) + "|" + ",".join(sorted(eqi))
    return hashlib.md5(f"{mood}|{activity}|{eq_sig}|{mtime}".encode("utf-8")).hexdigest()[:10]


def _bg_version(location_id: str, room: str) -> str:
    """Cache-Buster-Token fürs Hintergrundbild: ändert sich, wenn ein Event-Bild
    aktiv wird/fertig generiert ist (oder das normale Background-File wechselt)."""
    import hashlib
    import os
    from app.core.timeutils import utc_now
    p = None
    try:
        from app.core.event_images import get_effective_background_event
        p = get_effective_background_event(location_id)
    except Exception:
        p = None
    if not p or not p.exists():
        try:
            from app.models.world import get_background_path
            p = get_background_path(location_id, room=room, hour=utc_now().hour)
        except Exception:
            p = None
    if p and p.exists():
        return hashlib.md5(f"{p}:{int(os.path.getmtime(p))}".encode("utf-8")).hexdigest()[:10]
    return ""


@router.get("/play", include_in_schema=False)
async def play_page(user=Depends(get_current_user)):
    if not _SHELL.is_file():
        return HTMLResponse(
            "<h1>Player UI build missing</h1>"
            "<p>From the repo root: <code>cd frontend &amp;&amp; npm run build</code></p>",
            status_code=503)
    return FileResponse(_SHELL)


@router.get("/play/scene")
async def play_scene(user=Depends(get_current_user), limit: int = 100):
    """Wahrgenommene Raum-Szene + Bewegungs-Kontext (Räume, Nachbarn) des Avatars."""
    from app.core.room_entry import _list_characters_in_room
    from app.models import perception_store
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                       get_character_current_room)
    from app.models.world import get_entry_room_id, get_location_by_id

    empty = {"avatar": "", "location_id": "", "location_name": "",
             "room_id": "", "room_name": "", "present": [], "present_detail": [],
             "scene": [], "rooms": [], "neighbors": {}, "at_entry_room": True,
             "entry_room_name": "", "avatar_expr_version": "", "bg_version": ""}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return empty

    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    present = ([c for c in _list_characters_in_room(loc, room) if c != avatar]
               if loc else [])
    scene = perception_store.get_character_room_stream(avatar, loc, room, limit)

    # Porträts der Anwesenden fürs Umgebungs-Fenster
    from app.models.character import get_character_profile_image

    def _portrait(name: str) -> str:
        img = get_character_profile_image(name) or ""
        return f"/characters/{name}/images/{img}" if img else ""
    present_detail = [{"name": c, "avatar_url": _portrait(c),
                       "expr_version": _expr_version(c)} for c in present]

    # Bewegungs-Kontext: Räume des Orts + aktueller Raumname
    loc_obj = get_location_by_id(loc) if loc else None
    location_name = (loc_obj.get("name", "") if loc_obj else "")
    entry_id = get_entry_room_id(loc_obj) if loc_obj else ""
    rooms_out, room_name = [], ""
    for r in ((loc_obj.get("rooms") if loc_obj else None) or []):
        rid = r.get("id", "") or ""
        rn = r.get("name", "") or ""
        rooms_out.append({"id": rid, "name": rn, "is_entry": rid == entry_id})
        if room and (rid == room or rn == room):
            room_name = rn

    # Nachbar-Orte + Entry-Gate aus der bestehenden Route-Funktion wiederverwenden
    nb = {}
    try:
        from app.routes.world import avatar_neighbors_route
        nb = avatar_neighbors_route() or {}
    except Exception:
        nb = {}

    return {
        "avatar": avatar,
        "location_id": loc, "location_name": location_name,
        "room_id": room, "room_name": room_name,
        "present": present, "present_detail": present_detail, "scene": scene,
        "avatar_expr_version": _expr_version(avatar),
        "bg_version": _bg_version(loc, room) if loc else "",
        "rooms": rooms_out,
        "neighbors": {k: nb.get(k) for k in ("north", "south", "east", "west")},
        "at_entry_room": bool(nb.get("at_entry_room", True)),
        "entry_room_name": nb.get("entry_room_name", "") or "",
    }


@router.post("/play/enter-room")
async def play_enter_room(request: Request, user=Depends(get_current_user)):
    """Wechselt den Raum innerhalb des aktuellen Orts (freie Bewegung im Ort;
    der Entry-Room-Zwang gilt nur fürs Verlassen des Orts)."""
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                       save_character_current_activity,
                                       save_character_current_room)
    from app.models.world import get_location_by_id

    body = await request.json()
    room_id = str(body.get("room_id") or "").strip() if isinstance(body, dict) else ""
    if not room_id:
        raise HTTPException(status_code=400, detail="room_id required")
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    loc = (get_character_current_location(avatar) or "").strip()
    loc_obj = get_location_by_id(loc) if loc else None
    valid = {(r.get("id") or "") for r in ((loc_obj.get("rooms") if loc_obj else None) or [])}
    if room_id not in valid:
        raise HTTPException(status_code=400, detail="room not in current location")
    save_character_current_room(avatar, room_id)
    # Bewegung unterbricht die laufende Aktivität — sonst „kocht" der Avatar
    # weiter, obwohl er gerade den Raum gewechselt hat.
    save_character_current_activity(avatar, "")
    return {"ok": True, "room_id": room_id}


async def _storyteller_fallback(actor: str, text: str, location_id: str,
                                room_id: str, volume: str) -> None:
    """Storyteller-Fallback (plan-room-conversation, Option 3): reagiert kein
    anwesender Character auf eine Avatar-Äußerung (z.B. allein mit einem Bären),
    springt der Erzähler ein und narriert die Umgebung/Konsequenz. Die Narration
    landet als Erzähler-Wahrnehmung im Stream (erscheint im nächsten /play/scene).

    Lautstärke = Reichweite: schreien narriert ortsweit (scope=location), sonst
    nur den aktuellen Raum (scope=here) — konsistent mit der Utterance-Hörweite.
    """
    try:
        from app.skills.act_skill import perform_act
        from app.core.perception import record_utterance
        scope = "location" if volume == "shout" else "here"
        result = await perform_act(actor, text, scope) or {}
        narration = (result.get("narration") or "").strip()
        if narration:
            record_utterance(speaker="Erzähler", content=narration, volume=volume,
                             location_id=location_id, room_id=room_id,
                             addressees=[], source="storyteller")
            logger.info("Storyteller-Fallback narrierte für %s (scope=%s)", actor, scope)
        # Event-Verdikt (gelöst/ungelöst + Grund) als eigener Stream-Eintrag unter
        # dem Erzähler — markiert via perception_meta, vom SceneView farbig gerendert.
        if result.get("event_id"):
            resolved = bool(result.get("resolved"))
            reason = (result.get("reason") or "").strip()
            verdict_content = reason or (
                "Das Ereignis wurde gelöst." if resolved else "Das Ereignis bleibt ungelöst.")
            record_utterance(
                speaker="Erzähler", content=verdict_content, volume=volume,
                location_id=location_id, room_id=room_id, addressees=[],
                source="event_verdict",
                perception_meta={"event_verdict": "resolved" if resolved else "unresolved",
                                 "reason": reason})
    except Exception as e:  # noqa: BLE001
        logger.warning("storyteller fallback failed: %s", e)


@router.post("/play/say")
async def play_say(request: Request, user=Depends(get_current_user)):
    """Der Avatar äußert etwas in seinen aktuellen Raum.

    Phase 3: Avatar-Äußerung wird sofort aufgezeichnet; adressierte Charaktere
    werden im Agent-Loop ge-bumpt und antworten ASYNCHRON (zustands-bewusst,
    als Raum-Utterance). Der POST blockiert nicht mehr auf die LLM-Antwort —
    die Antworten erscheinen im nächsten /play/scene-Poll.
    """
    from app.core.perception import VOLUME_NORMAL, record_utterance
    from app.models.account import get_active_character

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    content = str(body.get("content") or "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="content is required")

    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")

    raw_addr = body.get("addressees") or []
    addressees = [str(a) for a in raw_addr] if isinstance(raw_addr, list) else []
    volume = str(body.get("volume") or VOLUME_NORMAL).strip()

    # Aktuellen Ort/Raum + Anwesende einmal auflösen (für Adressaten-Filter,
    # Reaktions-Dispatch und Storyteller-Fallback).
    loc = room = ""
    present: set = set()
    try:
        from app.core.room_entry import _list_characters_in_room
        from app.models.character import (get_character_current_location,
                                           get_character_current_room)
        loc = get_character_current_location(avatar) or ""
        room = get_character_current_room(avatar) or ""
        present = set(_list_characters_in_room(loc, room)) if loc else set()
    except Exception as e:  # noqa: BLE001
        logger.debug("play_say location/presence lookup failed: %s", e)

    # Adressaten auf TATSÄCHLICH ANWESENDE beschränken: nach einem Orts-/Raum-
    # wechsel kann die UI noch alte Auswahl mitschicken (z.B. Rosi/Thalion vom
    # Dorfplatz, während der Avatar längst im Wald ist). Abwesende zu adressieren
    # ist sinnlos (dafür gibt es Phone/TalkTo) und erzeugt falsche Daten.
    _dropped = [a for a in addressees if a and a != avatar and a not in present]
    if _dropped:
        logger.info("play_say: abwesende Adressaten verworfen: %s", _dropped)
    addressees = [a for a in addressees if a in present and a != avatar]

    # 1) Spell-Cast-Detection (wie der alte Chat-Pfad): wirkt die Äußerung einen
    #    Zauber auf das (erste) adressierte Ziel? Wenn ja, führt detect_and_cast
    #    den Cast sofort aus (Effekt-Item ans Ziel etc.) und liefert einen Hint,
    #    den das Ziel beim Antworten narrativ verarbeitet.
    import asyncio
    spell = None
    spell_target = next((a for a in addressees if a and a != avatar), "")
    if spell_target and content.strip():
        try:
            from app.core.spell_engine import detect_and_cast
            spell = await asyncio.to_thread(detect_and_cast, avatar, spell_target, content)
            if spell and spell.get("hint"):
                logger.info("play_say: spell %s by %s on %s — %s",
                            spell.get("spell_id"), avatar, spell_target,
                            "SUCCESS" if spell.get("success") else "FAIL")
        except Exception as e:  # noqa: BLE001
            logger.debug("play_say spell detect failed: %s", e)

    # 2) Avatar-Äußerung in den Stream
    uid = record_utterance(speaker=avatar, content=content, volume=volume,
                           addressees=addressees, source="play")

    # 3) Reaktionen über den Loop verteilen: Adressierte → Pflicht-Antwort,
    #    übrige Anwesende → Chime-Gelegenheit (Phase 3b). Avatar-Input lädt die
    #    Raum-Energie neu auf (setzt den Kaskaden-Backstop zurück). Spell-Hint
    #    geht gezielt an das Ziel.
    reactions = {"obligatory": [], "chime": []}
    try:
        from app.core.agent_loop import get_agent_loop
        hints = {spell_target: spell["hint"]} if (spell and spell.get("hint")) else None
        reactions = get_agent_loop().dispatch_room_reactions(
            speaker=avatar, content=content, volume=volume,
            location_id=loc, room_id=room, addressees=addressees,
            is_avatar=True, hints=hints)
    except Exception as e:  # noqa: BLE001
        logger.warning("play_say dispatch_room_reactions failed: %s", e)

    # 4) Storyteller-Fallback (Option 3): klinkt sich NIEMAND ein (kein anwesender
    #    Character — z.B. allein mit einem Bären), reagiert die Welt. Hintergrund,
    #    blockiert den POST nicht. Lautstärke → Scope (schreien = ortsweit).
    if not reactions.get("obligatory") and not reactions.get("chime"):
        try:
            asyncio.create_task(_storyteller_fallback(avatar, content, loc, room, volume))
        except Exception as e:  # noqa: BLE001
            logger.debug("play_say storyteller fallback schedule failed: %s", e)

    return {"ok": uid is not None, "utterance_id": uid,
            "bumped": reactions.get("obligatory", []),
            "chimed": reactions.get("chime", []),
            "spell": {
                "spell_id": spell.get("spell_id") or "",
                "spell_name": spell.get("spell_name") or spell.get("spell_id") or "",
                "target": spell_target,
                "success": bool(spell.get("success")),
            } if (spell and spell.get("hint")) else None}


@router.get("/play/self")
async def play_self(user=Depends(get_current_user)):
    """Eigener Zustand des Avatars (B Tier 1): Mood, Activity, Status-Bars,
    Conditions, aktuelles Outfit + Auswahl-Listen für die Steuerung. Ein Call."""
    from app.models.account import get_active_character
    empty = {"avatar": "", "mood": "", "activity": "", "status_effects": {},
             "bar_meta": {}, "conditions": [], "outfit": "", "profile_image": "",
             "activities": [], "outfit_sets": []}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return empty
    from app.models.character import (get_character_current_feeling,
                                      get_character_current_activity,
                                      get_character_outfits,
                                      get_character_profile_image)
    out = dict(empty, avatar=avatar)
    out["mood"] = get_character_current_feeling(avatar) or ""
    out["activity"] = get_character_current_activity(avatar) or ""
    out["profile_image"] = get_character_profile_image(avatar) or ""
    try:
        from app.routes.characters import get_status_effects_route
        s = get_status_effects_route(avatar)
        out["status_effects"] = s.get("status_effects", {}) or {}
        out["bar_meta"] = s.get("bar_meta", {}) or {}
    except Exception as e:
        logger.debug("play_self status-effects failed: %s", e)
    try:
        from app.routes.characters import get_active_conditions_route
        out["conditions"] = get_active_conditions_route(avatar).get("conditions", []) or []
    except Exception as e:
        logger.debug("play_self conditions failed: %s", e)
    try:
        from app.core.outfit_renderer import render_outfit
        out["outfit"] = render_outfit(character_name=avatar).get("full", "") or ""
    except Exception as e:
        logger.debug("play_self outfit render failed: %s", e)
    try:
        from app.models.world import list_all_activities
        out["activities"] = sorted({(a.get("name") or "").strip()
                                     for a in (list_all_activities() or [])
                                     if a.get("name")})
    except Exception as e:
        logger.debug("play_self activities failed: %s", e)
    try:
        out["outfit_sets"] = [{"id": o.get("id", ""), "name": o.get("name", "")}
                              for o in (get_character_outfits(avatar) or [])
                              if o.get("name")]
    except Exception as e:
        logger.debug("play_self outfit_sets failed: %s", e)
    return out


def _state_block(name: str) -> dict:
    """Mood + Status-Bars + Conditions + Profilbild eines Characters (geteilt von
    /play/self-Logik, genutzt von /play/others)."""
    from app.models.character import (get_character_current_feeling,
                                      get_character_profile_image)
    blk = {"name": name, "mood": "", "status_effects": {}, "bar_meta": {},
           "conditions": [], "profile_image": ""}
    try:
        blk["mood"] = get_character_current_feeling(name) or ""
    except Exception:
        pass
    try:
        blk["profile_image"] = get_character_profile_image(name) or ""
    except Exception:
        pass
    try:
        from app.routes.characters import get_status_effects_route
        s = get_status_effects_route(name)
        blk["status_effects"] = s.get("status_effects", {}) or {}
        blk["bar_meta"] = s.get("bar_meta", {}) or {}
    except Exception:
        pass
    try:
        from app.routes.characters import get_active_conditions_route
        blk["conditions"] = get_active_conditions_route(name).get("conditions", []) or []
    except Exception:
        pass
    return blk


@router.get("/play/others")
async def play_others(user=Depends(get_current_user)):
    """Zustand ALLER anwesenden anderen Charaktere (wie /play/self, je Character).
    Für das Others-Panel — read-only."""
    from app.models.account import get_active_character
    out = {"avatar": "", "characters": []}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    out["avatar"] = avatar
    try:
        from app.core.room_entry import _list_characters_in_room
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        loc = get_character_current_location(avatar) or ""
        room = get_character_current_room(avatar) or ""
        present = ([c for c in _list_characters_in_room(loc, room) if c and c != avatar]
                   if loc else [])
        out["characters"] = [_state_block(c) for c in present]
    except Exception as e:
        logger.debug("play_others failed: %s", e)
    return out


@router.get("/play/notices")
async def play_notices(user=Depends(get_current_user)):
    """Banner-relevante Hinweise für den Avatar (B Tier 1): kritische Events am
    Ort, aktive Bewegungs-Sperre (Block/Force), ungelesene Notifications."""
    from app.models.account import get_active_character
    out = {"avatar": "", "events": [], "leave_blocked": None,
           "notifications": [], "unread_count": 0}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    out["avatar"] = avatar
    from app.models.character import (get_character_current_location,
                                      get_character_current_room)
    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    try:
        from app.models.events import list_events
        crit = []
        for e in (list_events(location_id=loc) or []):
            if e.get("resolved"):
                continue
            cat = (e.get("category") or "").lower()
            if cat in ("danger", "disruption"):
                crit.append({"id": e.get("id", ""), "category": cat,
                             "text": e.get("text", "") or ""})
        out["events"] = crit
    except Exception as ex:
        logger.debug("play_notices events failed: %s", ex)
    try:
        from app.models.rules import check_leave
        ok, reason = check_leave(avatar)
        if not ok:
            out["leave_blocked"] = reason or "blocked"
    except Exception as ex:
        logger.debug("play_notices leave failed: %s", ex)
    try:
        from app.models.notifications import get_notifications, get_unread_count
        items = get_notifications(limit=10, unread_only=True,
                                  character_whitelist=[avatar]) or []
        out["notifications"] = [{"id": n.get("id"), "kind": n.get("kind", ""),
                                 "body": n.get("body", "") or n.get("title", "")}
                                for n in items]
        out["unread_count"] = get_unread_count(character_whitelist=[avatar])
    except Exception as ex:
        logger.debug("play_notices notifications failed: %s", ex)
    return out


_SLOT_ORDER = ["head", "neck", "outer", "top", "underwear_top",
               "bottom", "underwear_bottom", "legs", "feet"]
_SLOT_LABELS = {"head": "Kopf", "neck": "Hals", "outer": "Mantel & Jacke",
                "top": "Oberteil", "underwear_top": "Unterwäsche oben",
                "bottom": "Unterteil", "underwear_bottom": "Unterwäsche unten",
                "legs": "Beine", "feet": "Füße"}


@router.get("/play/belongings")
async def play_belongings(user=Depends(get_current_user)):
    """Inventar + Outfit (Paper-Doll) des Avatars (B Tier 1).
    Liefert die getragenen Pieces pro Slot (für die Figur) und die volle
    Item-Liste mit Filter-Attributen (Kategorie/Slot/Outfit-Typ/Spell)."""
    from app.models.account import get_active_character
    out = {"avatar": "", "slot_order": _SLOT_ORDER, "slot_labels": _SLOT_LABELS,
           "equipped": {}, "items": [], "outfit_sets": [], "max_slots": 0}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    out["avatar"] = avatar
    from app.models.inventory import (get_character_inventory, get_equipped_pieces,
                                      get_item)
    from app.models.character import get_character_outfits
    spells = {}
    try:
        from app.core.spell_engine import build_spell_catalog
        for s in (build_spell_catalog(avatar) or []):
            spells[s.get("clone_item_id") or s.get("id")] = s
    except Exception as e:
        logger.debug("belongings spell catalog failed: %s", e)
    try:
        for slot, iid in (get_equipped_pieces(avatar) or {}).items():
            it = get_item(iid) or {}
            out["equipped"][slot] = {"item_id": iid, "name": it.get("name", "") or iid,
                                     "image": bool(it.get("image"))}
    except Exception as e:
        logger.debug("belongings equipped failed: %s", e)
    try:
        inv = get_character_inventory(avatar) or {}
        out["max_slots"] = inv.get("max_slots", 0) or 0
        for entry in (inv.get("inventory") or []):
            iid = entry.get("item_id")
            it = get_item(iid) or {}
            op = it.get("outfit_piece") or {}
            sp = spells.get(iid)
            out["items"].append({
                "item_id": iid, "name": it.get("name", "") or iid,
                "description": (it.get("description") or "").strip(),
                "quantity": entry.get("quantity", 1),
                "category": (it.get("category") or ""),
                "consumable": bool(it.get("consumable")),
                "equipped": bool(entry.get("equipped")),
                "is_outfit": bool(op), "slots": op.get("slots") or [],
                "outfit_types": op.get("outfit_types") or [],
                "is_spell": bool(sp),
                "incantation": (sp or {}).get("incantation", "") if sp else "",
                "image": bool(it.get("image")), "rarity": (it.get("rarity") or ""),
            })
    except Exception as e:
        logger.debug("belongings inventory failed: %s", e)
    try:
        out["outfit_sets"] = [{"id": o.get("id", ""), "name": o.get("name", "")}
                              for o in (get_character_outfits(avatar) or []) if o.get("name")]
    except Exception as e:
        logger.debug("belongings outfit_sets failed: %s", e)
    return out


@router.post("/play/equip")
async def play_equip(request: Request, user=Depends(get_current_user)):
    """Zieht EIN Outfit-Piece an — merged mit dem Rest (nur die Slots dieses
    Pieces, inkl. Multi-Slot), verdrängt nur Konflikte. NICHT das ganze Outfit
    ersetzen (dafür ist apply-outfit-set)."""
    from app.models.inventory import equip_piece
    avatar = _require_avatar()
    body = await request.json()
    item_id = str((body or {}).get("item_id") or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id required")
    res = equip_piece(avatar, item_id)
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("reason", "equip failed"))
    return {"ok": True, "item_id": item_id, "slots": res.get("slots", [])}


@router.post("/play/unequip")
async def play_unequip(request: Request, user=Depends(get_current_user)):
    """Legt das Piece eines Slots ab (inkl. aller Mirror-Slots des Pieces)."""
    from app.models.inventory import unequip_piece
    avatar = _require_avatar()
    body = await request.json()
    slot = str((body or {}).get("slot") or "").strip()
    item_id = str((body or {}).get("item_id") or "").strip()
    if not slot and not item_id:
        raise HTTPException(status_code=400, detail="slot or item_id required")
    res = unequip_piece(avatar, slot=slot, item_id=item_id)
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("reason", "unequip failed"))
    return {"ok": True, "slot": slot}


@router.post("/play/use-item")
async def play_use_item(request: Request, user=Depends(get_current_user)):
    """Benutzt/konsumiert ein Item."""
    from app.models.inventory import consume_item
    avatar = _require_avatar()
    body = await request.json()
    item_id = str((body or {}).get("item_id") or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id required")
    res = consume_item(avatar, item_id)
    return {"ok": bool(res), "result": res}


@router.post("/play/cast-self")
async def play_cast_self(request: Request, user=Depends(get_current_user)):
    """Wirkt einen Spell aus dem Inventar auf den Avatar selbst — über
    spell_engine.execute_cast (respektiert copy_on_give, Effekt-Item-Übergabe,
    Cast-Activity). NICHT consume_item (Spell verschwindet sonst trotz copy_on_give)."""
    from app.core.spell_engine import build_spell_catalog, execute_cast
    avatar = _require_avatar()
    body = await request.json()
    item_id = str((body or {}).get("item_id") or "").strip()
    spell = next((s for s in build_spell_catalog(avatar) if s.get("id") == item_id), None)
    if not spell:
        raise HTTPException(status_code=404, detail="not a spell or not in inventory")
    res = execute_cast(avatar, avatar, spell)
    return {"ok": True, "spell_name": spell.get("name") or item_id,
            "success": bool(res.get("success")),
            "chance": int(res.get("chance") or 0), "roll": int(res.get("roll") or 0),
            "hint": res.get("hint") or ""}


@router.get("/play/gallery")
async def play_gallery(user=Depends(get_current_user)):
    """Bilder-Galerie des Avatars (Tier 2, read-only). Avatar serverseitig."""
    from app.models.account import get_active_character
    out = {"avatar": "", "images": [], "profile_image": ""}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    out["avatar"] = avatar
    try:
        from app.routes.characters import get_character_images_list
        d = get_character_images_list(avatar)
        prof = d.get("profile_image") or ""
        vids = d.get("image_videos") or {}
        meta_all = d.get("image_metadata") or {}
        prompts = d.get("image_prompts") or {}
        comments = d.get("image_comments") or {}
        out["profile_image"] = prof
        imgs = []
        for n in (d.get("images") or []):
            m = meta_all.get(n) or {}
            imgs.append({
                "name": n,
                "url": f"/characters/{avatar}/images/{n}",
                "is_profile": n == prof,
                "video": (f"/characters/{avatar}/images/{vids[n]}" if vids.get(n) else ""),
                "postprocessed": bool(m.get("postprocessed")),
                "info": {
                    "prompt": (prompts.get(n) or m.get("prompt") or ""),
                    "model": (m.get("model") or ""),
                    "backend": (m.get("backend") or ""),
                    "from_character": (m.get("from_character") or ""),
                    "created_at": (m.get("created_at") or ""),
                    "postprocessed_at": (m.get("postprocessed_at") or ""),
                    "analysis": (m.get("image_analysis") or ""),
                    "comment": (comments.get(n) or ""),
                },
            })
        out["images"] = imgs
    except Exception as e:
        logger.debug("play_gallery failed: %s", e)
    return out


@router.get("/play/journal")
async def play_journal(user=Depends(get_current_user)):
    """Gedächtnis + Tagebuch des Avatars (Tier 2, read-only). Avatar serverseitig
    aufgelöst; reused load_memories + diary.get_diary_entries."""
    from app.models.account import get_active_character
    out = {"avatar": "", "memories": [], "diary": []}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    out["avatar"] = avatar
    try:
        from app.models.memory import load_memories
        mem = sorted((load_memories(avatar) or []),
                     key=lambda m: m.get("timestamp", "") or "", reverse=True)[:40]
        out["memories"] = [{
            "content": m.get("content", "") or "",
            "type": m.get("memory_type", "") or "",
            "importance": m.get("importance", 0) or 0,
            "with": m.get("related_character", "") or "",
            "ts": m.get("timestamp", "") or "",
            "tags": m.get("tags") or [],
        } for m in mem]
    except Exception as e:
        logger.debug("play_journal memories failed: %s", e)
    try:
        from app.routes.diary import get_diary_entries
        d = get_diary_entries(avatar, limit=40)
        out["diary"] = [{"type": e.get("type", ""), "content": e.get("content", ""),
                         "ts": e.get("timestamp", "")} for e in (d.get("entries") or [])]
    except Exception as e:
        logger.debug("play_journal diary failed: %s", e)
    return out


def _require_avatar() -> str:
    from app.models.account import get_active_character
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    return avatar


@router.post("/play/self/mood")
async def play_set_mood(request: Request, user=Depends(get_current_user)):
    """Avatar setzt seine eigene Stimmung."""
    from app.models.character import save_character_current_feeling
    avatar = _require_avatar()
    body = await request.json()
    feeling = str((body or {}).get("mood") or "").strip()
    save_character_current_feeling(avatar, feeling)
    return {"ok": True, "mood": feeling}


@router.post("/play/self/activity")
async def play_set_activity(request: Request, user=Depends(get_current_user)):
    """Avatar setzt seine eigene Aktivität (wechselt ggf. den Raum automatisch)."""
    from app.models.character import save_character_current_activity
    avatar = _require_avatar()
    body = await request.json()
    activity = str((body or {}).get("activity") or "").strip()
    save_character_current_activity(avatar, activity)
    return {"ok": True, "activity": activity}


@router.post("/play/self/outfit")
async def play_set_outfit(request: Request, user=Depends(get_current_user)):
    """Avatar zieht ein gespeichertes Outfit-Set an (reused apply_equipped_pieces)."""
    from app.models.character import get_character_outfits
    from app.models.inventory import apply_equipped_pieces, get_item
    avatar = _require_avatar()
    body = await request.json()
    outfit_id = str((body or {}).get("outfit_id") or "").strip()
    name = str((body or {}).get("name") or "").strip()
    if not outfit_id and not name:
        raise HTTPException(status_code=400, detail="outfit_id or name required")
    target = None
    for o in (get_character_outfits(avatar) or []):
        if (outfit_id and o.get("id") == outfit_id) or \
           (name and (o.get("name") or "").lower() == name.lower()):
            target = o
            break
    if not target:
        raise HTTPException(status_code=404, detail="outfit not found")
    pieces_by_slot = {}
    for pid in (target.get("pieces") or []):
        slots = (((get_item(pid) or {}).get("outfit_piece") or {}).get("slots") or [])
        if slots:
            pieces_by_slot[slots[0]] = pid
    pieces_meta = {}
    for _slot, _color in (target.get("pieces_colors") or {}).items():
        if _color and pieces_by_slot.get(_slot):
            pieces_meta[_slot] = {"color": str(_color).strip()}
    apply_equipped_pieces(avatar, pieces=pieces_by_slot,
                          remove_slots=list(target.get("remove_slots") or []),
                          pieces_meta=pieces_meta, source="play_outfit")
    return {"ok": True, "name": target.get("name", "")}


@router.get("/play/layout")
async def play_get_layout(user=Depends(get_current_user)):
    """Gespeichertes UI-Layout des Users (react-grid-layout breakpoint-map) oder
    None, wenn noch keins gespeichert wurde."""
    from app.models.account import _current_user_settings
    us = _current_user_settings() or {}
    return {"layout": us.get("play_layout")}


@router.put("/play/layout")
async def play_put_layout(request: Request, user=Depends(get_current_user)):
    """Persistiert das UI-Layout im User-Profil (folgt dem User über Geräte)."""
    from app.models.account import _update_current_user_settings
    body = await request.json()
    layout = body.get("layout") if isinstance(body, dict) else None
    if layout is None:
        raise HTTPException(status_code=400, detail="layout required")
    ok = _update_current_user_settings({"play_layout": layout})
    return {"ok": ok}


@router.get("/play/figures")
async def play_get_figures(user=Depends(get_current_user)):
    """Figuren-Standpunkte im Umgebungsfenster (Name → {x, y} als Bruchteile
    0..1) fuer den AKTUELLEN Raum + das aktuelle Expression-Bild jeder Figur.

    Quelle sind die Character-Daten (nicht User-Settings) → die Platzierung gilt
    fuer alle Spieler. Pos ist an (Raum, expr_version) gekoppelt: bei neuem Bild
    fehlt der Eintrag → Frontend nutzt seine Default-Position."""
    from app.core.room_entry import _list_characters_in_room
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                       get_character_current_room,
                                       get_scene_position)
    positions: dict = {}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return {"positions": positions}
    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    names = list(_list_characters_in_room(loc, room)) if loc else []
    if avatar not in names:
        names.append(avatar)
    for name in names:
        nloc = get_character_current_location(name) or ""
        nroom = get_character_current_room(name) or ""
        p = get_scene_position(name, nloc, nroom, _expr_version(name))
        if p:
            positions[name] = p
    return {"positions": positions}


@router.put("/play/figures")
async def play_save_figures(request: Request, user=Depends(get_current_user)):
    """Persistiert Figuren-Standpunkte in den Character-Daten, gekoppelt an Raum
    + Expression-Bild-Hash. Nur Figuren, die im Raum des Avatars anwesend sind."""
    from app.core.room_entry import _list_characters_in_room
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                       get_character_current_room,
                                       set_scene_position)
    body = await request.json()
    positions = body.get("positions") if isinstance(body, dict) else None
    if not isinstance(positions, dict):
        raise HTTPException(status_code=400, detail="positions object required")
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return {"ok": True}
    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    allowed = set(_list_characters_in_room(loc, room)) if loc else set()
    allowed.add(avatar)
    for name, p in positions.items():
        if name not in allowed or not isinstance(p, dict):
            continue
        nloc = get_character_current_location(name) or ""
        nroom = get_character_current_room(name) or ""
        set_scene_position(name, nloc, nroom, _expr_version(name),
                           p.get("x"), p.get("y"))
    return {"ok": True}


@router.get("/play/layouts")
async def play_list_layouts(user=Depends(get_current_user)):
    """Alle benannten Layout-Presets des Users (Name → {grid, open})."""
    from app.models.account import _current_user_settings
    us = _current_user_settings() or {}
    presets = us.get("play_layout_presets")
    return {"presets": presets if isinstance(presets, dict) else {}}


@router.put("/play/layouts")
async def play_save_layout(request: Request, user=Depends(get_current_user)):
    """Speichert das aktuelle Layout unter einem Namen."""
    from app.models.account import (_current_user_settings,
                                    _update_current_user_settings)
    body = await request.json()
    name = str((body or {}).get("name") or "").strip() if isinstance(body, dict) else ""
    layout = body.get("layout") if isinstance(body, dict) else None
    if not name or layout is None:
        raise HTTPException(status_code=400, detail="name and layout required")
    us = _current_user_settings() or {}
    presets = dict(us.get("play_layout_presets") or {})
    presets[name] = layout
    _update_current_user_settings({"play_layout_presets": presets})
    return {"ok": True, "names": sorted(presets.keys())}


@router.delete("/play/layouts/{name}")
async def play_delete_layout(name: str, user=Depends(get_current_user)):
    """Löscht einen benannten Layout-Preset."""
    from app.models.account import (_current_user_settings,
                                    _update_current_user_settings)
    us = _current_user_settings() or {}
    presets = dict(us.get("play_layout_presets") or {})
    presets.pop(name, None)
    _update_current_user_settings({"play_layout_presets": presets})
    return {"ok": True, "names": sorted(presets.keys())}
