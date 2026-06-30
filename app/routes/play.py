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
                                      get_effective_activity)
    from app.models.inventory import get_equipped_pieces, get_equipped_items
    mood = activity = ""
    eqp: dict = {}
    eqi: list = []
    try:
        mood = get_character_current_feeling(name) or ""
        activity = get_effective_activity(name) or ""
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
            p = get_background_path(location_id, room=room, hour=utc_now().hour,
                                    stable=True)
        except Exception:
            p = None
    if p and p.exists():
        return hashlib.md5(f"{p}:{int(os.path.getmtime(p))}".encode("utf-8")).hexdigest()[:10]
    return ""


def _bg_id(location_id: str, room: str) -> str:
    """Dateiname (bg_id) des aktuell gewaehlten Hintergrundbilds — Event-Bild hat
    Vorrang, sonst die regulaere Auswahl. Das Frontend pinnt damit das <img>
    (``/background?file=<bg_id>``) und koppelt die Figuren-Positionen an genau
    dieses Bild. Tageszeit via UTC, konsistent zu :func:`_bg_version`."""
    from app.core.timeutils import utc_now
    try:
        from app.core.event_images import get_effective_background_event
        p = get_effective_background_event(location_id)
        if p and p.exists():
            return p.name
    except Exception:
        pass
    try:
        from app.models.world import get_background_path
        p = get_background_path(location_id, room=room, hour=utc_now().hour,
                                stable=True)
        if p and p.exists():
            return p.name
    except Exception:
        pass
    return ""


@router.get("/play", include_in_schema=False)
async def play_page():
    # Shell wird BEWUSST ohne Auth ausgeliefert: das ist nur das statische
    # React-Bundle (kein Secret). Die SPA gated sich selbst client-seitig ueber
    # <AuthGate> (zeigt das Login-Formular bei fehlender Session). Eine
    # Server-Auth-Dependency hier wuerde 401-JSON zurueckgeben, bevor die SPA
    # laedt -> kein Login-Dialog. Alle Daten-Endpoints (/play/*) bleiben gegated.
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
             "entry_room_name": "", "avatar_expr_version": "", "bg_version": "",
             "bg_id": ""}
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

    # C2a: Folgen-Vorschläge — kürzlich aktive Gesprächspartner, die den Raum
    # gerade verlassen haben (gleiche Location, anderer Raum). Avatar folgt per
    # Klick (/play/enter-room). So bricht das Gespräch beim Raumwechsel nicht ab.
    follow_suggestions = []
    try:
        from datetime import timedelta
        from app.core.timeutils import parse_iso, utc_now as _utc_now
        cutoff = _utc_now() - timedelta(minutes=5)
        present_set = set(present)
        _seen: set = set()
        for ln in (scene or [])[-15:]:
            sp = ((ln.get("meta") or {}).get("speaker") or "").strip()
            if not sp or sp == avatar or sp == "Erzähler" or sp in present_set or sp in _seen:
                continue
            try:
                if parse_iso(ln.get("ts") or "") < cutoff:
                    continue
            except Exception:
                pass
            c_loc = get_character_current_location(sp) or ""
            c_room = get_character_current_room(sp) or ""
            if c_loc == loc and c_room and c_room != room:
                _seen.add(sp)
                rn = next((r["name"] for r in rooms_out if r["id"] == c_room), c_room)
                follow_suggestions.append({"character": sp, "room_id": c_room, "room_name": rn})
    except Exception as _fe:
        logger.debug("follow_suggestions failed: %s", _fe)

    # Party-Status (Kompass ausblenden wenn Follower) + offene Einladungen an den
    # Avatar (Ja/Nein-Frage im Chat-Fenster).
    party = _party_block(avatar)
    try:
        from app.core.party_engine import get_pending_invites_for
        party_invites = [{"invite_id": i["invite_id"], "inviter": i["inviter"]}
                         for i in get_pending_invites_for(avatar)]
    except Exception:
        party_invites = []

    return {
        "avatar": avatar,
        "location_id": loc, "location_name": location_name,
        "room_id": room, "room_name": room_name,
        "present": present, "present_detail": present_detail, "scene": scene,
        "follow_suggestions": follow_suggestions,
        "party": party, "party_invites": party_invites,
        "avatar_expr_version": _expr_version(avatar),
        "bg_version": _bg_version(loc, room) if loc else "",
        "bg_id": _bg_id(loc, room) if loc else "",
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
                                       clear_pose_intent,
                                       save_character_current_room)
    from app.models.world import get_location_by_id

    body = await request.json()
    room_id = str(body.get("room_id") or "").strip() if isinstance(body, dict) else ""
    if not room_id:
        raise HTTPException(status_code=400, detail="room_id required")
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    # Party-Follower kann sich nicht selbst bewegen (auch keinen Raum wechseln) —
    # er wird vom Leader mitgezogen. UI versteckt den Kompass; harter Backstop hier.
    from app.core.party_engine import is_party_follower
    if is_party_follower(avatar):
        raise HTTPException(status_code=403, detail={
            "reason": "party_follower",
            "message": "Du bist Teil einer Party und wirst vom Leader mitgenommen — eigene Bewegung gesperrt."})
    loc = (get_character_current_location(avatar) or "").strip()
    loc_obj = get_location_by_id(loc) if loc else None
    valid = {(r.get("id") or "") for r in ((loc_obj.get("rooms") if loc_obj else None) or [])}
    if room_id not in valid:
        raise HTTPException(status_code=400, detail="room not in current location")
    save_character_current_room(avatar, room_id)
    # Bewegung unterbricht die laufende Pose — sonst „kocht" der Avatar
    # weiter, obwohl er gerade den Raum gewechselt hat.
    clear_pose_intent(avatar)
    return {"ok": True, "room_id": room_id}


def _party_block(avatar: str):
    """Party-Status des Avatars fuer die UI (None = in keiner Party)."""
    try:
        from app.core.party_engine import get_party_of
        p = get_party_of(avatar)
        if not p:
            return None
        return {"role": p["role"], "leader": p["leader"], "members": p["members"]}
    except Exception:
        return None


@router.post("/play/party/respond")
async def play_party_respond(request: Request, user=Depends(get_current_user)):
    """Avatar beantwortet eine Party-Einladung (Ja/Nein) aus dem Chat-Fenster."""
    from app.models.account import get_active_character
    from app.core.party_engine import get_invite, resolve_pending_invite
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    body = await request.json()
    invite_id = str(body.get("invite_id") or "").strip() if isinstance(body, dict) else ""
    accept = bool(body.get("accept")) if isinstance(body, dict) else False
    if not invite_id:
        raise HTTPException(status_code=400, detail="invite_id required")
    inv = get_invite(invite_id)
    # Nur eigene Einladungen beantworten (kein Fremd-Resolve).
    if not inv or inv.get("invitee") != avatar:
        raise HTTPException(status_code=404, detail="invite not found")
    res = resolve_pending_invite(invite_id, accept)
    return {"ok": res.get("status") in ("accepted", "declined"), **res}


@router.post("/play/party/leave")
async def play_party_leave(user=Depends(get_current_user)):
    """Avatar verlaesst seine Party (Follower steigt aus, Leader = Aufloesung)."""
    from app.models.account import get_active_character
    from app.core.party_engine import leave_party, clear_invites_for
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    res = leave_party(avatar)
    try:
        clear_invites_for(avatar)
    except Exception:
        pass
    return {"ok": res.get("status") == "ok", **res}


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
        # perform_act schreibt Narration + Event-Verdikt jetzt SELBST als
        # "Erzähler" in den Stream (act_skill._record_act_to_stream) — hier kein
        # zweites record_utterance mehr, sonst doppelte Einträge.
        scope = "location" if volume == "shout" else "here"
        await perform_act(actor, text, scope)
        logger.info("Storyteller-Fallback narrierte für %s (scope=%s)", actor, scope)
    except Exception as e:  # noqa: BLE001
        logger.warning("storyteller fallback failed: %s", e)


async def _handle_party_invite(avatar: str, invitee: str, content: str,
                               location_id: str, room_id: str) -> None:
    """Hintergrund (Flow 1): laesst den eingeladenen NPC per LLM entscheiden
    (ask_to_join_party) und macht seine Antwort im Raum sichtbar — run_chat_turn
    schreibt selbst NICHT in den Wahrnehmungs-Stream. Bei Ja ist der Beitritt
    bereits erfolgt; eine Erzaehler-Zeile bestaetigt es."""
    import asyncio as _asyncio
    from app.core.party_engine import ask_to_join_party
    from app.core.perception import record_utterance, VOLUME_NORMAL
    try:
        accepted, reply = await _asyncio.to_thread(
            ask_to_join_party, avatar, invitee, content)
    except Exception as e:  # noqa: BLE001
        logger.warning("party invite handler %s->%s failed: %s", avatar, invitee, e)
        return
    # reply ist die echte NPC-Antwort (oder "" bei Pre-Check-Skip) — nur dann
    # als Sprechzeile in den Raum schreiben.
    if reply:
        record_utterance(speaker=invitee, content=reply, volume=VOLUME_NORMAL,
                         location_id=location_id, room_id=room_id, source="party_invite")
    if accepted:
        record_utterance(speaker="Erzähler",
                         content=f"{invitee} schließt sich {avatar}s Party an.",
                         volume=VOLUME_NORMAL, location_id=location_id,
                         room_id=room_id, source="party")
        logger.info("Party: %s ist %s beigetreten (Natural-Speech-Einladung)",
                    invitee, avatar)


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
    # Attached image (uploaded id or character-library url). An image alone is a
    # valid message — the avatar can "show" something without saying a word.
    image_id = str(body.get("image_id") or "")
    image_url = str(body.get("image_url") or "")
    has_image = bool(image_id or image_url)
    if not content.strip() and not has_image:
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

    # 0) Bild-Anhang auflösen + (nur dann) synchron analysieren. Die Beschreibung
    #    muss VOR dem Fan-Out feststehen, damit die wahrnehmenden Agents das Bild
    #    „sehen". Die sichtbare Avatar-Zeile bleibt sauber (nur der Text); das Bild
    #    reist als Thumbnail über perception_meta mit, die Beschreibung nur in die
    #    Reaktions-Wahrnehmung (wie im alten /chat: Bild im UI, Beschreibung im
    #    Prompt). Nur bei tatsächlichem Bild blockiert der POST.
    import asyncio
    img_display_url = ""
    img_block = ""
    if has_image:
        from app.routes.chat import resolve_chat_image, analyze_chat_image_blocking
        img_path, img_display_url = resolve_chat_image(image_id, image_url)
        if img_path:
            _vision_agent = next((a for a in addressees if a and a != avatar), "") or avatar
            try:
                _desc = await asyncio.wait_for(
                    asyncio.to_thread(analyze_chat_image_blocking,
                                      img_path, _vision_agent, content),
                    timeout=15) or ""
            except asyncio.TimeoutError:
                logger.warning("play_say: Bild-Analyse Timeout (15s) — fahre ohne Beschreibung fort")
                _desc = ""
            except Exception as _ie:  # noqa: BLE001
                logger.error("play_say: Bild-Analyse fehlgeschlagen: %s", _ie)
                _desc = ""
            img_block = (f"[Bildbeschreibung: {_desc.strip()}]" if _desc.strip()
                         else "[Der Avatar zeigt ein Bild.]")
        else:
            logger.info("play_say: Bild-Anhang nicht auflösbar (id=%s url=%s)", image_id, image_url)
            img_display_url = ""

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
            spell = await asyncio.to_thread(detect_and_cast, avatar, spell_target, content, volume)
            if spell and spell.get("hint"):
                logger.info("play_say: spell %s by %s on %s — %s",
                            spell.get("spell_id"), avatar, spell_target,
                            "SUCCESS" if spell.get("success") else "FAIL")
        except Exception as e:  # noqa: BLE001
            logger.debug("play_say spell detect failed: %s", e)

    # 1b) Spell-Cast (Port der alten chat.py-Logik): die ROHEN Zauberworte werden
    #     NICHT gezeigt — `chat_substitute` (narrative Beschreibung des Wirkens)
    #     ersetzt sie, damit das Ziel auf die WIRKUNG reagiert, nicht auf die
    #     Worte (sonst „Was bedeutet das?"). Der `hint` (success_/fail_text) wird
    #     als Erzähler-Ergebniszeile sichtbar gemacht UND dem Ziel beim Reagieren
    #     mitgegeben. Die komplette Mechanik (Effekte, Anchor-Teleport, Item,
    #     Modus, cast_activity) lief bereits in detect_and_cast→execute_cast.
    _is_spell = bool(spell and spell.get("hint"))
    say_content = ((spell.get("chat_substitute") or "").strip() or content) if _is_spell else content

    # 2) Avatar-Äußerung in den Stream (bei Spell: Narration statt Beschwörung).
    #    Bei Bild-Anhang reist die Display-URL als perception_meta mit, damit die
    #    Scene-Zeile ein Thumbnail zeigt — der sichtbare Text bleibt unverändert.
    _pmeta = {"image_url": img_display_url} if img_display_url else None
    uid = record_utterance(speaker=avatar, content=say_content, volume=volume,
                           addressees=addressees, source="play",
                           perception_meta=_pmeta)

    # 2b) Spell-Ergebnis (success_/fail_text) als Erzähler-Zeile sichtbar machen.
    #     location_id explizit — „Erzähler" hat keinen eigenen Ort.
    if _is_spell:
        _hint = (spell.get("hint") or "").strip()
        if _hint:
            record_utterance(speaker="Erzähler", content=_hint, volume=VOLUME_NORMAL,
                             location_id=loc, room_id=room, source="spell")

    # 2c) Party-Einladung per Natural Speech (Flow 1): erkennt der Avatar eine
    #     Einladung ("komm mit …") an einen anwesenden NPC, entscheidet dieser im
    #     Hintergrund per LLM (ask_to_join_party) und faellt aus dem normalen
    #     Reaktions-Dispatch (exclude) — sonst antwortet er doppelt.
    _party_invitee = ""
    if content.strip() and not _is_spell:
        try:
            from app.core.party_engine import detect_invite_target
            _party_invitee = detect_invite_target(avatar, content, present)
        except Exception as _pe:  # noqa: BLE001
            logger.debug("party invite detect failed: %s", _pe)
    if _party_invitee:
        addressees = [a for a in addressees if a != _party_invitee]
        try:
            asyncio.create_task(
                _handle_party_invite(avatar, _party_invitee, content, loc, room))
        except Exception as _pe:  # noqa: BLE001
            logger.debug("party invite schedule failed: %s", _pe)

    # 3) Reaktionen über den Loop verteilen: Adressierte → Pflicht-Antwort,
    #    übrige Anwesende → Chime. Bei Spell reagiert das Ziel auf die WIRKUNG
    #    (Inhalt = chat_substitute + hint), nicht auf die rohen Zauberworte.
    reactions = {"obligatory": [], "chime": []}
    try:
        from app.core.agent_loop import get_agent_loop
        hints = {spell_target: spell["hint"]} if (_is_spell and spell_target) else None
        # Den Agents die Bildbeschreibung mitgeben (vor den Text gestellt), damit
        # sie auf das gezeigte Bild reagieren — die aufgezeichnete Zeile bleibt
        # davon unberührt (clean text + Thumbnail).
        _react_content = f"{img_block}\n\n{say_content}".strip() if img_block else say_content
        reactions = get_agent_loop().dispatch_room_reactions(
            speaker=avatar, content=_react_content, volume=volume,
            location_id=loc, room_id=room, addressees=addressees,
            is_avatar=True, hints=hints,
            exclude=[_party_invitee] if _party_invitee else None)
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
                "delivered_item_name": spell.get("delivered_item_name") or "",
                "teleport": spell.get("teleport") or {},
            } if _is_spell else None}


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
                                      get_effective_activity,
                                      get_character_outfits,
                                      get_character_profile_image)
    out = dict(empty, avatar=avatar)
    out["mood"] = get_character_current_feeling(avatar) or ""
    out["activity"] = get_effective_activity(avatar) or ""
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
    from app.models.character import (get_effective_activity,
                                      get_character_current_feeling,
                                      get_character_profile_image)
    blk = {"name": name, "mood": "", "activity": "", "status_effects": {},
           "bar_meta": {}, "conditions": [], "profile_image": ""}
    try:
        blk["mood"] = get_character_current_feeling(name) or ""
    except Exception:
        pass
    try:
        blk["activity"] = get_effective_activity(name) or ""
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
           "force_warning": None, "notifications": [], "unread_count": 0,
           "party": None}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    out["avatar"] = avatar
    out["party"] = _party_block(avatar)
    # Aktive Force-Regel (z.B. "Erschöpfung: Bin erschöpft, gehe schlafen") —
    # fuer den Avatar NICHT automatisch ausgefuehrt, nur als Hinweis + Apply.
    try:
        from app.models.rules import check_force_rules, resolve_force_destination
        force = check_force_rules(avatar)
        if force and force.get("message"):
            go_loc, go_room = resolve_force_destination(avatar, force.get("go_to", "stay"))
            out["force_warning"] = {
                "rule_id": force.get("rule_id", ""),
                "rule_name": force.get("rule_name", ""),
                "message": force.get("message", ""),
                "go_to": force.get("go_to", "stay"),
                "go_to_location_id": go_loc,
                "go_to_room_id": go_room,
                "set_activity": force.get("set_activity", ""),
            }
    except Exception as ex:
        logger.debug("play_notices force failed: %s", ex)
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
        # _row_to_notification liefert content/type/character (NICHT body/kind/
        # title) — sonst bleiben die Banner-Zeilen leer.
        out["notifications"] = [{"id": n.get("id"), "kind": n.get("type", ""),
                                 "body": n.get("content", "")}
                                for n in items]
        out["unread_count"] = get_unread_count(character_whitelist=[avatar])
    except Exception as ex:
        logger.debug("play_notices notifications failed: %s", ex)
    return out


@router.get("/play/news")
async def play_news(user=Depends(get_current_user)):
    """News-Channel für den Avatar: aktive (nicht-resolvte) Events am eigenen Ort
    + globale Events, neueste zuerst. danger/disruption = "breaking". Liefert auch
    den welt-konfigurierten Präsentations-Stil (modern/newspaper/flyer)."""
    from app.models.account import get_active_character
    from app.models.world import get_world_setting
    out = {"avatar": "", "style": get_world_setting("news.style", "modern") or "modern",
           "title": get_world_setting("news.title", "") or "", "items": []}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    out["avatar"] = avatar
    try:
        from app.models.character import get_character_current_location
        from app.models.events import list_events
        loc = get_character_current_location(avatar) or ""
        items = []
        for e in (list_events(location_id=loc) or []):
            if e.get("resolved"):
                continue
            cat = (e.get("category") or "").lower()
            items.append({
                "id": e.get("id", ""),
                "text": e.get("text", "") or "",
                "category": cat,
                "created_at": e.get("created_at", "") or "",
                "location_id": e.get("location_id") or "",
                "global": e.get("location_id") is None,
                "breaking": cat in ("danger", "disruption"),
            })
        items.sort(key=lambda x: x["created_at"], reverse=True)
        out["items"] = items
    except Exception as ex:
        logger.debug("play_news failed: %s", ex)
    return out


_SLOT_ORDER = ["head", "neck", "outer", "top", "underwear_top",
               "bottom", "underwear_bottom", "legs", "feet"]
_SLOT_LABELS = {"head": "Kopf", "neck": "Hals", "outer": "Mantel & Jacke",
                "top": "Oberteil", "underwear_top": "Unterwäsche oben",
                "bottom": "Unterteil", "underwear_bottom": "Unterwäsche unten",
                "legs": "Beine", "feet": "Füße"}


def build_belongings(character_name: str) -> dict:
    """Inventar + Outfit (Paper-Doll) eines Characters — Single-Source für das
    Avatar-Panel (/play) UND den Game-Admin-Garderoben-Tab.
    Liefert die getragenen Pieces pro Slot (für die Figur) und die volle
    Item-Liste mit Filter-Attributen (Kategorie/Slot/Outfit-Typ/Spell)."""
    avatar = (character_name or "").strip()
    out = {"avatar": "", "slot_order": _SLOT_ORDER, "slot_labels": _SLOT_LABELS,
           "equipped": {}, "items": [], "outfit_sets": [], "max_slots": 0}
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


@router.get("/play/belongings")
async def play_belongings(user=Depends(get_current_user)):
    """Belongings des aktiven Avatars."""
    from app.models.account import get_active_character
    return build_belongings((get_active_character() or "").strip())


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
    # Effekt als Erzähler-Zeile sichtbar machen (location_id explizit — „Erzähler"
    # hat keinen eigenen Ort, sonst läuft der Fan-Out ins Leere).
    try:
        from app.core.perception import record_utterance, VOLUME_NORMAL
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        _loc = get_character_current_location(avatar) or ""
        _room = get_character_current_room(avatar) or ""
        _hint = (res.get("hint") or "").strip()
        if _loc and _hint:
            record_utterance(speaker="Erzähler", content=_hint,
                             volume=VOLUME_NORMAL, location_id=_loc, room_id=_room,
                             source="spell")
    except Exception as _e:  # noqa: BLE001
        logger.debug("self-cast narration failed: %s", _e)
    return {"ok": True, "spell_name": spell.get("name") or item_id,
            "success": bool(res.get("success")),
            "chance": int(res.get("chance") or 0), "roll": int(res.get("roll") or 0),
            "hint": res.get("hint") or ""}


def _build_gallery_payload(character: str) -> dict:
    """Baut die Galerie-Nutzlast (Bilder + Meta) fuer einen Character.

    Gleiche Form wie ``/play/gallery`` (images[], profile_image). Kein Zugriffs-
    Check hier — der gehoert in die aufrufende Route."""
    out = {"character": character, "images": [], "profile_image": ""}
    if not character:
        return out
    try:
        from app.routes.characters import get_character_images_list
        d = get_character_images_list(character)
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
                "url": f"/characters/{character}/images/{n}",
                "is_profile": n == prof,
                "video": (f"/characters/{character}/images/{vids[n]}" if vids.get(n) else ""),
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
        logger.debug("gallery payload failed for %s: %s", character, e)
    return out


@router.get("/play/gallery")
async def play_gallery(user=Depends(get_current_user)):
    """Bilder-Galerie des eigenen Avatars (Tier 2, read-only). Avatar serverseitig."""
    from app.models.account import get_active_character
    avatar = (get_active_character() or "").strip()
    out = _build_gallery_payload(avatar)
    out["avatar"] = avatar
    return out


@router.get("/play/galleries")
async def play_galleries(user=Depends(get_current_user)):
    """Liste der Galerien, die der aktive Avatar durchstoebern darf
    (eigene zuerst, danach freigegebene fremde)."""
    from app.models.account import get_active_character
    from app.models.character import (
        list_available_characters, can_view_gallery, get_character_profile_image,
    )
    avatar = (get_active_character() or "").strip()
    out = {"avatar": avatar, "galleries": []}
    if not avatar:
        return out
    for name in list_available_characters():
        if not can_view_gallery(avatar, name):
            continue
        prof = get_character_profile_image(name) or ""
        out["galleries"].append({
            "character": name,
            "is_self": name == avatar,
            "profile_url": (f"/characters/{name}/images/{prof}" if prof else ""),
        })
    # Eigene Galerie immer zuerst.
    out["galleries"].sort(key=lambda g: (not g["is_self"], g["character"].lower()))
    return out


@router.get("/play/gallery/{character}")
async def play_gallery_of(character: str, user=Depends(get_current_user)):
    """Galerie eines bestimmten Characters — nur wenn der aktive Avatar in
    dessen Freigabeliste steht (oder es die eigene Galerie ist)."""
    from app.models.account import get_active_character
    from app.models.character import can_view_gallery
    avatar = (get_active_character() or "").strip()
    if not avatar or not can_view_gallery(avatar, character):
        raise HTTPException(status_code=403, detail="Gallery not accessible")
    out = _build_gallery_payload(character)
    out["avatar"] = avatar
    return out


@router.delete("/play/gallery/{character}/image/{filename}")
async def play_gallery_delete_image(character: str, filename: str, user=Depends(get_current_user)):
    """Loescht ein Bild aus der Galerie des EIGENEN aktiven Avatars.

    IDOR-Schutz: nur die eigene Galerie ist loeschbar — sonst koennte jeder
    eingeloggte User fremde Character-Bilder loeschen."""
    from app.models.account import get_active_character
    from app.models.character import delete_character_image

    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not character.strip():
        raise HTTPException(status_code=400, detail="character required")
    avatar = (get_active_character() or "").strip()
    if not avatar or character.strip() != avatar:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not delete_character_image(character, filename):
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


@router.get("/play/worldmap")
async def play_worldmap(user=Depends(get_current_user)):
    """Aggregierte 2D-Weltkarte: Orte (Grid/Passable/Rotation), Character-
    Positionen (+Avatar/Aktivitaet/Reiseziel) und aktive disruption/danger-Events.
    Eine Anfrage statt N×Fetch — read-only fuer das Player-Karten-Panel."""
    from app.models.account import get_active_character
    from app.models.world import list_locations
    from app.models.events import list_events
    from app.models.character import (
        list_available_characters, get_character_current_location,
        get_effective_activity, get_movement_target, get_character_profile_image,
    )

    avatar = (get_active_character() or "").strip()

    locations = []
    name_by_id = {}
    for loc in list_locations():
        lid = loc.get("id") or ""
        name_by_id[lid] = loc.get("name") or ""
        locations.append({
            "id": lid,
            "name": loc.get("name") or "",
            "grid_x": loc.get("grid_x"),
            "grid_y": loc.get("grid_y"),
            "passable": bool(loc.get("passable")),
            "template_location_id": (loc.get("template_location_id") or ""),
            "map_rotation_2d": int(loc.get("map_rotation_2d") or 0),
        })

    characters = []
    for name in list_available_characters():
        loc_id = get_character_current_location(name) or ""
        if not loc_id:
            continue  # offmap (z.B. avatar-only & ungesteuert) -> nicht auf der Karte
        mt = get_movement_target(name) or ""
        prof = get_character_profile_image(name) or ""
        characters.append({
            "name": name,
            "location_id": loc_id,
            "activity": get_effective_activity(name) or "",
            "movement_target_id": mt,
            "movement_target_name": name_by_id.get(mt, "") or mt,
            "avatar_url": (f"/characters/{name}/images/{prof}" if prof else ""),
        })

    events_by_location = {}
    for ev in list_events():
        if ev.get("resolved"):
            continue
        cat = ev.get("category") or ""
        if cat not in ("disruption", "danger"):
            continue
        lid = ev.get("location_id") or ""
        if not lid:
            continue
        events_by_location.setdefault(lid, []).append({
            "category": cat,
            "text": ev.get("text") or "",
        })

    return {
        "avatar": avatar,
        "current_location_id": (get_character_current_location(avatar) if avatar else ""),
        "locations": locations,
        "characters": characters,
        "events_by_location": events_by_location,
    }


@router.get("/play/scenes")
async def play_scenes(user=Depends(get_current_user), limit: int = 5):
    """„Was bisher geschah" — zuletzt konsolidierte Szenen, an denen der Avatar
    beteiligt war (Zeit · Ort/Raum · Mit-Teilnehmer · Summary). Recap-Leiste im
    Chat, neueste zuerst."""
    from app.models.account import get_active_character
    from app.models import scene_store
    from app.models.world import get_location_by_id
    out = {"avatar": "", "scenes": []}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return out
    out["avatar"] = avatar
    for sc in scene_store.get_recent_scenes_for(avatar, limit=limit):
        loc = get_location_by_id(sc.get("location_id", "")) or {}
        loc_name = loc.get("name", "") or sc.get("location_id", "")
        room_name = ""
        for r in (loc.get("rooms") or []):
            if (r.get("id") or "") == sc.get("room_id", ""):
                room_name = r.get("name", "") or ""
                break
        others = [p for p in (sc.get("participants") or [])
                  if p and p != avatar and p != "Erzähler"]
        out["scenes"].append({
            "ts": sc.get("last_activity_ts", ""),
            "location_name": loc_name, "room_name": room_name,
            "participants": others, "summary": sc.get("summary", ""),
        })
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
    """Avatar setzt seine eigene Pose/Tätigkeit (freie Pose)."""
    from app.models.character import set_pose_intent
    avatar = _require_avatar()
    body = await request.json()
    activity = str((body or {}).get("activity") or "").strip()
    set_pose_intent(avatar, activity)
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
async def play_get_figures(bg: str = "", user=Depends(get_current_user)):
    """Figuren-Standpunkte im Umgebungsfenster (Name → {x, y, scale}, x/y als
    Bruchteile 0..1) fuer den AKTUELLEN Raum + Hintergrundbild (``bg`` = bg_id)
    + das aktuelle Expression-Bild jeder Figur.

    Quelle sind die Character-Daten (nicht User-Settings) → die Platzierung gilt
    fuer alle Spieler. Pos ist an (Raum, bg_id, expr_version) gekoppelt: bei
    neuem Bild fehlt der Eintrag → Frontend nutzt seine Default-Position."""
    from app.core.room_entry import _list_characters_in_room
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                       get_character_current_room,
                                       get_scene_position,
                                       get_last_scene_position)
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
        nroom = get_character_current_room(name) or ""
        # Exakter Eintrag fuer das aktuelle Bild — sonst die letzte Platzierung
        # fuer (Character, Raum) erben (neues Expression-Bild ohne eigene Pos).
        p = (get_scene_position(name, nroom, _expr_version(name), bg)
             or get_last_scene_position(name, nroom, bg))
        if p:
            positions[name] = p
    return {"positions": positions}


@router.put("/play/figures")
async def play_save_figures(request: Request, user=Depends(get_current_user)):
    """Persistiert Figuren-Standpunkte + Groesse in den Character-Daten, gekoppelt
    an Raum + Hintergrundbild (``bg``) + Expression-Bild-Hash. Nur Figuren, die im
    Raum des Avatars anwesend sind."""
    from app.core.room_entry import _list_characters_in_room
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                       get_character_current_room,
                                       set_scene_position)
    body = await request.json()
    positions = body.get("positions") if isinstance(body, dict) else None
    bg = str(body.get("bg") or "") if isinstance(body, dict) else ""
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
        nroom = get_character_current_room(name) or ""
        set_scene_position(name, nroom, _expr_version(name), bg,
                           p.get("x"), p.get("y"), p.get("scale", 1.0))
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


# ---- Phone / Messaging (Säule B: 1:1-DMs, medium="messaging") -----------
# Async-Modell: eine Avatar-DM landet als chat_messages-Zeile (= Inbox des
# Charakters) und bumpt ihn. Er sieht sie auf seinem nächsten Turn und kann
# per send_message-Maschinerie antworten — DARF aber ignorieren. Das Panel
# pollt Verlauf + Status; Lesestand pro Konversation in world_kv.

def _msg_portrait(name: str) -> str:
    from app.models.character import get_character_profile_image
    img = get_character_profile_image(name) or ""
    return f"/characters/{name}/images/{img}" if img else ""


def _messaging_partners(avatar: str) -> list:
    """Distinct 1:1-Konversationspartner des Avatars (beide Speicher-Richtungen)."""
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(
            "SELECT partner AS other FROM chat_messages "
            "WHERE character_name=? AND partner!='' "
            "UNION "
            "SELECT character_name AS other FROM chat_messages "
            "WHERE partner=? AND character_name!=''",
            (avatar, avatar)).fetchall()
    except Exception as e:
        logger.debug("messaging partners query failed: %s", e)
        return []
    return [r[0] for r in rows if r[0] and r[0] != avatar]


def _phone_read_key(avatar: str, partner: str) -> str:
    return f"phone_read:{avatar}:{partner}"


def _phone_read_ts(avatar: str, partner: str) -> str:
    from app.core.db import get_connection
    try:
        row = get_connection().execute(
            "SELECT value FROM world_kv WHERE key=?",
            (_phone_read_key(avatar, partner),)).fetchone()
        return (row[0] or "") if row else ""
    except Exception:
        return ""


def _phone_set_read(avatar: str, partner: str, ts: str) -> None:
    from app.core.db import transaction
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO world_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_phone_read_key(avatar, partner), ts or ""))
    except Exception as e:
        logger.debug("phone read marker write failed: %s", e)


@router.get("/play/messages")
async def play_messages_list(user=Depends(get_current_user)):
    """Kontaktliste: 1:1-Konversationen des Avatars mit Vorschau, Unread, Status."""
    from app.models.account import get_active_character
    from app.models.chat import get_chat_history
    from app.models.character import (is_character_sleeping,
                                      get_character_current_location,
                                      list_available_characters)
    from app.models.world import get_location_by_id
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return {"avatar": "", "conversations": [], "available": []}
    convs = []
    for partner in _messaging_partners(avatar):
        hist = [m for m in (get_chat_history(avatar, partner_name=partner) or [])
                if (m.get("content") or "").strip()]
        if not hist:
            continue
        last = hist[-1]
        read_ts = _phone_read_ts(avatar, partner)
        unread = sum(1 for m in hist if m.get("role") == "user"
                     and (m.get("timestamp") or "") > read_ts)
        loc_id = get_character_current_location(partner) or ""
        loc = (get_location_by_id(loc_id) or {}) if loc_id else {}
        convs.append({
            "partner": partner,
            "avatar_url": _msg_portrait(partner),
            "last": (last.get("content") or "")[:80],
            "last_ts": last.get("timestamp") or "",
            "mine_last": last.get("role") == "assistant",
            "unread": unread,
            "status": "sleeping" if is_character_sleeping(partner) else "awake",
            "location": loc.get("name", ""),
        })
    convs.sort(key=lambda c: c.get("last_ts") or "", reverse=True)
    # Für "neue Konversation": alle Charaktere außer dem Avatar selbst.
    try:
        available = sorted(c for c in (list_available_characters() or [])
                           if c and c != avatar)
    except Exception:
        available = []
    return {"avatar": avatar, "conversations": convs, "available": available}


@router.post("/play/messages/read-all")
async def play_messages_read_all(user=Depends(get_current_user)):
    """Markiert alle 1:1-Konversationen des Avatars als gelesen (Unread → 0)."""
    from app.models.account import get_active_character
    from app.models.chat import get_chat_history
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=404, detail="Kein aktiver Avatar")
    count = 0
    for partner in _messaging_partners(avatar):
        hist = [m for m in (get_chat_history(avatar, partner_name=partner) or [])
                if (m.get("content") or "").strip()]
        if not hist:
            continue
        _phone_set_read(avatar, partner, hist[-1].get("timestamp") or "")
        count += 1
    return {"ok": True, "conversations": count}


@router.get("/play/messages/thread")
async def play_messages_thread(partner: str, user=Depends(get_current_user)):
    """1:1-Verlauf mit einem Partner. Markiert die Konversation als gelesen."""
    from app.models.account import get_active_character
    from app.models.chat import get_chat_history
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=404, detail="Kein aktiver Avatar")
    partner = (partner or "").strip()
    if not partner:
        raise HTTPException(status_code=400, detail="partner erforderlich")
    hist = [m for m in (get_chat_history(avatar, partner_name=partner) or [])
            if (m.get("content") or "").strip()]
    msgs = [{"mine": m.get("role") == "assistant",
             "content": m.get("content") or "",
             "ts": m.get("timestamp") or ""} for m in hist]
    if hist:
        _phone_set_read(avatar, partner, hist[-1].get("timestamp") or "")
    return {"avatar": avatar, "partner": partner, "messages": msgs}


@router.post("/play/messages/send")
async def play_messages_send(request: Request, user=Depends(get_current_user)):
    """Avatar sendet eine DM: symmetrisch speichern (Empfänger-Inbox + Avatar-
    History) und den Charakter bumpen — er darf antworten oder ignorieren."""
    from app.models.account import get_active_character
    from app.models.chat import save_message
    from app.core.timeutils import utc_now_iso
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=404, detail="Kein aktiver Avatar")
    body = await request.json()
    partner = (body.get("partner") or "").strip()
    content = (body.get("content") or "").strip()
    if not partner or not content:
        raise HTTPException(status_code=400, detail="partner + content erforderlich")
    if partner == avatar:
        raise HTTPException(status_code=400, detail="Kein Selbstgespräch")
    ts = utc_now_iso()
    # Empfänger-Inbox: vom Avatar eingehend (role=user)
    save_message({"role": "user", "content": content, "timestamp": ts,
                  "speaker": avatar, "medium": "messaging"},
                 character_name=partner, partner_name=avatar)
    # Avatar-eigene History (role=assistant aus Avatar-Sicht)
    save_message({"role": "assistant", "content": content, "timestamp": ts,
                  "speaker": avatar, "medium": "messaging"},
                 character_name=avatar, partner_name=partner)
    _phone_set_read(avatar, partner, ts)
    # Charakter bumpen (antwortet in eigener Zeit, darf ignorieren)
    try:
        from app.core.agent_loop import get_agent_loop
        get_agent_loop().bump(
            partner,
            hint=f"{avatar} hat dir gerade eine Nachricht aufs Handy geschrieben "
                 f"(Messaging, nicht persönlich): \"{content[:300]}\". Du kannst "
                 f"{avatar} zurückschreiben (SendMessage) oder es lassen.")
    except Exception as e:
        logger.debug("bump after phone send failed: %s", e)
    return {"ok": True, "ts": ts}
