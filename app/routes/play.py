"""Player-UI — eigene Seite unter ``/play`` (plan-room-conversation Phase 2).

Bewusst getrennt vom Game-Admin: die Player-UI ist in-world und User-gated
(nicht admin). Sie zeigt die *wahrgenommene* aktuelle Raum-Szene des aktiven
Avatars — read-only in diesem Schritt; Äußerungen senden kommt als Nächstes.

Die gebaute Shell liegt (wie game-admin) unter ``static/game_admin/play.html``
— derselbe ``frontend/``-Build, aber eine eigene Seite/Route.
"""
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.core import users
from app.core.auth_dependency import get_current_user, require_admin
from app.core.log import get_logger
from app.core.perception import STORYTELLER_SPEAKER

logger = get_logger("play")

router = APIRouter()

_SHELL = Path("static/game_admin/play.html")


def _expr_version(name: str) -> str:
    """Cache-buster token for the expression image: changes on a mood, pose or
    outfit change AND when a new variant finished generating (mtime of the
    cached variant). The frontend appends it to the outfit-expression URL, so
    the image only reloads on a real change (event-driven, no blind polling)."""
    import hashlib
    import os
    from app.models.character import (get_character_current_feeling,
                                      get_effective_pose_key)
    from app.models.inventory import get_equipped_pieces, get_equipped_items
    mood = pose_key = ""
    eqp: dict = {}
    eqi: list = []
    try:
        mood = get_character_current_feeling(name) or ""
        pose_key = get_effective_pose_key(name) or ""
        eqp = get_equipped_pieces(name) or {}
        eqi = get_equipped_items(name) or []
    except Exception:
        pass
    mtime = ""
    try:
        from app.core.expression_regen import peek_cached_expression
        p = peek_cached_expression(name, mood, pose_key,
                                   equipped_pieces=eqp, equipped_items=eqi)
        if p:
            mtime = str(int(os.path.getmtime(p)))
    except Exception:
        pass
    eq_sig = ",".join(f"{k}:{v}" for k, v in sorted(eqp.items())) + "|" + ",".join(sorted(eqi))
    return hashlib.md5(f"{mood}|{pose_key}|{eq_sig}|{mtime}".encode("utf-8")).hexdigest()[:10]


def _bg_version(location_id: str, room: str) -> str:
    """Cache-Buster-Token fürs Hintergrundbild: ändert sich, wenn ein Event-Bild
    aktiv wird/fertig generiert ist (oder das normale Background-File wechselt)."""
    import hashlib
    import os
    from app.core.timeutils import game_local_now
    p = None
    try:
        from app.core.event_images import get_effective_background_event
        p = get_effective_background_event(location_id)
    except Exception:
        p = None
    if not p or not p.exists():
        try:
            from app.models.world import get_background_path
            p = get_background_path(location_id, room=room, hour=game_local_now().hour,
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
    from app.core.timeutils import game_local_now
    try:
        from app.core.event_images import get_effective_background_event
        p = get_effective_background_event(location_id)
        if p and p.exists():
            return p.name
    except Exception:
        pass
    try:
        from app.models.world import get_background_path
        p = get_background_path(location_id, room=room, hour=game_local_now().hour,
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
    # no-cache: a cached shell keeps loading the OLD hashed bundle after a
    # deploy (ETag revalidation makes this cheap).
    return FileResponse(_SHELL, headers={"Cache-Control": "no-cache"})


def _player_capabilities(avatar: str) -> list:
    """Skill IDs available to the avatar — per-character enablement plus the
    manager's role filters (party follower etc.). The player UI gates its
    skill-bound surfaces (panels, buttons) on this list, so removing a skill
    package degrades the UI automatically. Generic: only IDs from the skill
    manager, no skill names in this code (F8, plan-skill-plugin-architecture.md)."""
    try:
        from app.core.dependencies import get_skill_manager
        sm = get_skill_manager()
        skills = sm._get_agent_skills(avatar, check_limits=False)
        return sorted({getattr(s, "SKILL_ID", "") for s in skills} - {""})
    except Exception as e:
        logger.debug("player capabilities failed for %s: %s", avatar, e)
        return []


@router.get("/play/scene")
async def play_scene(user=Depends(get_current_user), limit: int = 100):
    """The avatar's PERCEIVED room scene plus its movement context (rooms,
    who is around)."""
    from app.core.perception import nearby_in_the_open
    from app.core.room_entry import _list_characters_in_room
    from app.models import perception_store
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                       get_character_current_room)
    from app.models.world import get_location_by_id

    empty = {"avatar": "", "location_id": "", "location_name": "",
             "room_id": "", "room_name": "", "present": [], "present_detail": [],
             "scene": [], "rooms": [], "travel": None,
             "avatar_expr_version": "", "bg_version": "",
             "bg_id": "", "capabilities": []}
    avatar = (get_active_character() or "").strip()
    if not avatar:
        return empty

    loc = get_character_current_location(avatar) or ""
    room = get_character_current_room(avatar) or ""
    # Out in the WILDERNESS there is no room to list — the neighbours are
    # everyone within the hearing radius (E6), and that is ONE roster shared
    # with the prompt builders and TalkTo, never a second distance rule here.
    # It never contains the asker itself, so it needs no filter of its own.
    # Without this the avatar stood alone outdoors while its own perception
    # stream carried the very people it was told were not there.
    present = ([c for c in _list_characters_in_room(loc, room) if c != avatar]
               if loc else nearby_in_the_open(avatar))
    scene = perception_store.get_character_room_stream(
        avatar, loc, room, limit, include_meta_lines=True)

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
    from app.core.world_ops import build_avatar_rooms
    from app.models.character import get_character_language
    lang = get_character_language(avatar) or "de"
    # Each room carries its lock state FOR THIS AVATAR (enterable + reason) —
    # the same check /play/enter-room refuses with, so the UI never offers a
    # room the route would turn away (plan-betreten-und-tueren.md § 5 C).
    rooms_out = build_avatar_rooms(avatar, loc_obj, lang)
    room_name = ""
    for r in rooms_out:
        if room and (r["id"] == room or r["name"] == room):
            room_name = r["name"]

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
            if not sp or sp == avatar or sp == STORYTELLER_SPEAKER or sp in present_set or sp in _seen:
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

    # Localise the storyteller speaker label for the player's UI — the stored
    # value stays the canonical STORYTELLER_SPEAKER; only the display shows the
    # translated name (the localized German label). SceneView renders meta.speaker.
    try:
        from app.core.i18n import t as _t
        _st_label = _t("Storyteller", lang)
        if _st_label != STORYTELLER_SPEAKER:
            for _ln in scene:
                _m = _ln.get("meta")
                if isinstance(_m, dict) and _m.get("speaker") == STORYTELLER_SPEAKER:
                    _m["speaker"] = _st_label
    except Exception as _le:
        logger.debug("storyteller label localisation failed: %s", _le)

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
        # The avatar's own journey — the travel panel's poll channel (it is
        # already polling this route for the room chips). Null while standing
        # still. The worldmap payload carries the same journey for EVERY
        # character, in metres, for the map to draw (E3 Task 6).
        "travel": _travel_block(avatar),
        "capabilities": _player_capabilities(avatar),
    }


@router.post("/play/enter-room")
async def play_enter_room(request: Request, user=Depends(get_current_user)):
    """Changes the room within the current location, subject to room-scoped
    block rules (the entry-room constraint only applies to leaving the
    location). Going onto the ground is an ordinary room change like any
    other and runs through the same check — a rule may lock the ground too."""
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                       get_character_language,
                                       clear_pose_intent,
                                       is_character_sleeping,
                                       save_character_current_room,
                                       set_is_sleeping)
    from app.models.world import GROUND_ROOM_ID, get_location_by_id

    body = await request.json()
    # An empty room_id means "onto the location's ground" — and since the
    # ground is a room of its own it is addressed by its id from here on, so
    # exactly one path exists and the checks below apply to it as well.
    room_id = (str(body.get("room_id") or "").strip()
               if isinstance(body, dict) else "") or GROUND_ROOM_ID
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    # A party follower cannot move on its own (not even between rooms) — the
    # leader drags it along. The UI hides the controls; this is the hard
    # backstop. Same sentence as the travel route's refusal, translated the
    # same way: one refusal, one wording.
    from app.core.i18n import t
    from app.core.party_engine import is_party_follower
    if is_party_follower(avatar):
        lang = get_character_language(avatar) or "de"
        raise HTTPException(status_code=403, detail={
            "reason": "party_follower",
            "message": t("You are part of a party and your leader takes you "
                         "along — you cannot move on your own.", lang)})
    loc = (get_character_current_location(avatar) or "").strip()
    loc_obj = get_location_by_id(loc) if loc else None
    valid = {(r.get("id") or "") for r in ((loc_obj.get("rooms") if loc_obj else None) or [])}
    if room_id not in valid:
        raise HTTPException(status_code=400, detail="room not in current location")
    # The second of the two gates (plan-betreten-und-tueren.md § 5 A): a
    # block rule may forbid a ROOM, not just a location. The location step
    # has checked this since it was written; the room change never did, so
    # every room rule was bypassed by walking.
    from app.models.rules import check_access
    ok_enter, enter_msg = check_access(avatar, loc, room_id=room_id)
    if not ok_enter:
        raise HTTPException(status_code=403, detail={
            "reason": "block_enter", "message": enter_msg})
    save_character_current_room(avatar, room_id)
    # Movement interrupts the running pose — otherwise the avatar keeps
    # "cooking" although they just changed rooms.
    clear_pose_intent(avatar)
    # Player-driven movement is the clearest wake signal there is: without
    # this, a sleeping avatar keeps "Sleeping" (flag + sleep expression) after
    # walking to another room. set_is_sleeping(False) also drops the sleep
    # pose/variant. Deliberately ONLY here (player-initiated move) — model-
    # level auto-wake would break offmap-sleep transfers and rule-driven
    # moves of sleeping characters.
    if is_character_sleeping(avatar):
        set_is_sleeping(avatar, False)
        logger.info("enter-room: %s woke up by moving to %s", avatar, room_id)
    return {"ok": True, "room_id": room_id}


def _travel_block(name: str):
    """The character's running journey for the player UI, or None.

    Derived from the STORED journey and the game clock (``journey_state`` is
    a pure function of it) — nothing is recomputed, no route is walked here.
    The ETA is formatted as the world's own wall clock: the game clock has a
    timezone of its own and the browser knows nothing about it, so ``HH:MM``
    is produced here and shown verbatim.

    ONE vocabulary with the worldmap block (§ A11): ``target_id``,
    ``eta_game``, ``progress_m`` and ``total_m`` mean the same thing in both
    payloads — ``eta_game`` therefore carries the WORLD-timezone offset here
    too (it used to be the raw UTC stamp), so a client that slices HH:MM out
    of it gets game wall-clock time either way. ``eta_hhmm``, ``target_name``
    and ``arrived`` are this block's extras: the single-avatar panel needs a
    ready-made label, the worldmap has ``movement_target_name`` and reports
    arrival by dropping the block.
    """
    try:
        from app.core.timeutils import game_now, to_world_tz
        from app.core.travel_engine import get_journey, journey_state
        from app.models.world import get_location_name
        j = get_journey(name)
        if not j:
            return None
        st = journey_state(j["waypoints"], j["started_at_game"], game_now())
        target_id = j["target"]
        eta_world = to_world_tz(st["eta_game"])
        return {
            "target_id": target_id,
            "target_name": get_location_name(target_id) or target_id,
            "eta_game": eta_world.isoformat(),
            "eta_hhmm": f"{eta_world:%H:%M}",
            "progress_m": st["progress_m"],
            "total_m": st["total_m"],
            "arrived": st["arrived"],
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("travel block failed for %s: %s", name, e)
        return None


@router.post("/play/travel")
async def play_travel(request: Request, user=Depends(get_current_user)):
    """The avatar sets off for a named location (Seamless World, E3).

    Body: ``{"target_id": "<location-id>"}``. The avatar walks the same
    timed journey an NPC walks — the position is a pure function of the game
    clock and the travel ticker settles the arrival. Nothing moves here.

    The gate sequence is the one the SetLocation skill applies before it
    journeys (its twin: ``plugins/movement/skill_set_location.py``,
    "Leave-Check" → "Restrictions-Check" → "Rules-Engine"), copied rather
    than shared because the skill's gates sit in the middle of its name
    matching and its LLM-facing wording:

      1. a party FOLLOWER owns no movement at all (the hard backstop behind
         the panel's hint — the leader drags it along),
      2. transit tiles are no destinations (the skill refuses them too; the
         pathfinder still walks THROUGH them),
      3. ``rules.check_leave`` — may the avatar leave where it stands,
      4. ``accessible_when`` at the target — the condition the world map
         greys a place out with. A WALL, not a hint (backend-status-3d.md,
         commit bdd8598): no rule engine reads that field, so it is only ever
         as strong as the paths that ask for it, and there are FOUR of them —
         this route, ``POST /play/pos`` (a free walker crossing into a place),
         ``travel_engine._arrival_gate`` (the ticker's arrival, which is what
         makes it bite for NPCs and for conditions that flip while someone is
         on the road) and the SetLocation skill. All four read the same
         ``world_ops.conditions_pass``.
         The SetLocation skill still does not ask before it sets off; the
         arrival gate refuses at the door (ledgered separately),
      5. ``danger_system.check_location_access`` — may it enter the target.
         The skill asks ``rules.check_access`` a second time right after;
         that is the very predicate the danger façade delegates to, so it is
         asked ONCE here.

    A rule refusal is a 403 with the rule's own sentence (like every other
    blocked move in the player UI). The engine's own reasons — the target is
    unknown, unplaced, or no walkable route exists — are ANSWERS, not
    errors: 200 with ``journey: null`` and the reason, which the UI words.
    The ticker's arrival gate stays the second net: rules can change while
    someone is on the road.
    """
    from app.core.i18n import t
    from app.core.travel_engine import start_journey
    from app.models.account import get_active_character
    from app.models.character import (get_character_language,
                                      is_character_sleeping, set_is_sleeping)
    from app.models.world import get_location_by_id

    body = await request.json()
    target_id = (str(body.get("target_id") or "").strip()
                 if isinstance(body, dict) else "")
    if not target_id:
        raise HTTPException(status_code=400, detail="target_id required")
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    # Every player-facing sentence below is translated into the avatar's
    # language — a rule's own message arrives localized from the rule engine,
    # the ones this route words itself go through t().
    lang = get_character_language(avatar) or "de"

    from app.core.party_engine import is_party_follower
    if is_party_follower(avatar):
        raise HTTPException(status_code=403, detail={
            "reason": "party_follower",
            "message": t("You are part of a party and your leader takes you "
                         "along — you cannot move on your own.", lang)})

    target = get_location_by_id(target_id)
    if not target:
        # Reported like an unknown place, not as a 404: from inside the world
        # "there is no such place" and "you were never told about it" are the
        # same statement, and the UI has one sentence for both.
        return {"journey": None, "reason": "unknown_target"}
    if target.get("passable"):
        return {"journey": None, "reason": "passable_target"}

    from app.models.rules import check_leave
    leave_ok, leave_reason = check_leave(avatar, target_location_id=target_id)
    if not leave_ok:
        logger.info("Travel refused (leave rule): %s -> %s: %s",
                    avatar, target_id, leave_reason)
        raise HTTPException(status_code=403, detail={
            "reason": "block_leave", "message": leave_reason})

    # ``accessible_when`` — the same field the world map greys a place out
    # with, read by the same reader (``world_ops.conditions_pass``). No rule
    # row backs it, so it is exactly as strong as the movement paths that ask:
    # this route, the free-walker gate in ``play_pos`` below, the ticker's
    # ``travel_engine._arrival_gate`` and the SetLocation skill. Four places,
    # one reader — a missing check in any of them makes the condition
    # decoration for that path.
    from app.core.world_ops import conditions_pass
    if not conditions_pass(target.get("accessible_when") or [],
                           avatar, target_id):
        logger.info("Travel refused (accessible_when): %s -> %s",
                    avatar, target_id)
        raise HTTPException(status_code=403, detail={
            "reason": "not_accessible",
            "message": t("This place is not accessible to you.", lang)})

    from app.core.danger_system import check_location_access
    enter_ok, enter_reason = check_location_access(avatar, target)
    if not enter_ok:
        logger.info("Travel refused (access rule): %s -> %s: %s",
                    avatar, target_id, enter_reason)
        raise HTTPException(status_code=403, detail={
            "reason": "block_enter", "message": enter_reason})

    # The mechanics — OFF the event loop. Measured (E3 Task 5 report): a
    # straight run over open ground is cheap (100 m ≈ 13 ms, 1300 m ≈ 0.5 s),
    # but the A* pays for OBSTACLES, and buildings are obstacles: in a 1 km²
    # world with 30 placed locations the same call took 2.7 s (730 m) and
    # 7.0 s (1290 m). That is CPU work inside an async handler, so run
    # synchronously it would stall every other request of the server, not
    # just this one. No timeout: the thread finishes and writes its journey
    # either way, and a half-started journey is worse than a slow answer.
    import asyncio
    journey, reason = await asyncio.to_thread(start_journey, avatar, target_id)
    if journey is None:
        logger.info("No journey for avatar %s -> %s: %s",
                    avatar, target_id, reason)
        return {"journey": None, "reason": reason}

    # Setting off is player-driven movement, and that is the clearest wake
    # signal there is — the same rule ``/play/enter-room`` applies (a
    # sleeping avatar must not walk a road in its sleep).
    if is_character_sleeping(avatar):
        set_is_sleeping(avatar, False)
        logger.info("travel: %s woke up by setting off for %s",
                    avatar, target_id)
    return {"journey": _travel_block(avatar), "reason": ""}


@router.post("/play/travel/cancel")
async def play_travel_cancel(user=Depends(get_current_user)):
    """The avatar calls off its journey and stays where it is.

    Idempotent: without a running journey nothing happens and
    ``cancelled`` is false — a double click is not an error.
    """
    from app.core.travel_engine import cancel_journey, get_journey
    from app.models.account import get_active_character
    from app.models.world import get_location_name
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    j = get_journey(avatar)
    if not j:
        return {"ok": True, "cancelled": False, "target_id": "",
                "target_name": ""}
    target_id = j.get("target") or ""
    cancel_journey(avatar)
    logger.info("Travel cancelled by the player: %s (target was %s)",
                avatar, target_id)
    return {"ok": True, "cancelled": True, "target_id": target_id,
            "target_name": get_location_name(target_id) or target_id}


# ── Free walking (Seamless World, E4 task 5) ────────────────────────────────
# The metre world has no cells, so it has no compass step either: the client
# walks freely and REPORTS where it stands. Everything below is the price of
# that freedom — the gates that used to sit on the step have to sit on the
# report, all of them (the E3-C1 lesson: a location change derived from a
# point, without the entry gates, is a hole in every rule the world has).

#: Minimum real-time distance between two ACCEPTED reports of one avatar
#: (~4 a second). The client reports ~3 a second while it moves plus one on
#: stop, so this is headroom, not a budget — a client that reported per frame
#: would just have most of them dropped. Read as a module attribute so a smoke
#: can turn wall-clock behaviour off for the cases that are not about it.
_POS_REPORT_INTERVAL_S = 0.25
#: Nobody is refused a step shorter than this, whatever the clock says (metres).
_POS_STEP_FLOOR_M = 5.0
#: How many times the world's travel speed a free walker may make. Generous on
#: purpose: this is an ANTI-TELEPORT bound, not a precision anticheat — the
#: client's own walk is 3.4 m/s and every honest report stays far below.
_POS_STEP_FACTOR = 3.0
#: The client's own walking pace in REAL metres per second — a mirror of
#: ``WALK_SPEED`` in ``client3d/src/scene/npcs.ts``, kept here for one reason:
#: the travel-speed term above is coupled to the GAME clock, and free walking
#: is not. In a frozen world (factor 0) or a slow one that term collapses to
#: nothing while the player still walks 3.4 m every second, and an honest
#: walker would collect 409s. The allowance is the LARGEST of the three
#: (floor, game-speed term, real-speed term), so neither clock can strand it.
_POS_WALK_SPEED_M_S = 3.4
#: How close to an authored boundary opening a point has to be to count as
#: crossing THROUGH it (metres). The client offers the entry at 3 m and walks
#: the figure to the opening point, so an accepted crossing lands well inside.
_POS_OPENING_TOLERANCE_M = 1.5
#: When each avatar's last ACCEPTED report came in (``time.monotonic``).
#: Process-local on purpose: it is a rate limit and a plausibility baseline,
#: not world state — a restart simply grants everyone one free first report,
#: which is the same grace a takeover gets.
_pos_report_at: Dict[str, float] = {}


@router.post("/play/pos")
async def play_pos(request: Request, user=Depends(get_current_user)):
    """The avatar reports where it is standing (free walking, E4 task 5).

    Body: ``{"x": <metres>, "z": <metres>}``. The client walks the figure
    itself and sends the result; this judges the point and writes it. There is
    no server-side route computation and no per-boundary permission any more —
    the answer is the accepted point, its location and its room.

    The chain, in order:

      1. a party FOLLOWER owns no movement at all (403 ``party_follower``, the
         same backstop ``/play/travel`` applies),
      2. the numbers are finite (400): a NaN sails through every comparison
         below and poisons the JSON encoder afterwards,
      3. THROTTLE — at most ~4 accepted reports a second. Excess is dropped
         SILENTLY (200 ``{ok: false, throttled: true}``): a client that reports
         too eagerly must not collect error toasts for it,
      4. plausible step against the real time since the last ACCEPTED report,
         allowance ``max(5 m, 3 × travel_speed × game_factor × elapsed,
         3 × 3.4 m/s × elapsed)`` — THREE terms, and the last one is why a
         frozen or slow world does not strand an honest walker (409
         ``too_far``),
      5. the LOCATION of the point (``location_at_point``) — derived FIRST,
         because it decides whether step 6 applies at all,
      6. terrain ``passability_at`` at the point, ONLY OUT IN THE WILDERNESS
         (409 ``impassable``) — inside a placed footprint the FOOTPRINT WINS
         (decision 2026-08-13), see below. PASSABILITY only: the terrain's
         ``speed_factor`` is not gated anywhere in this chain — it applies
         everywhere, footprint included (finding 3, § A15), and the client
         walks it,
      7. the LOCATION TRANSITION through the FULL gate (below),
      8. the HEIGHT of the point against the last valid one (409
         ``too_steep``) — a step higher than ``game.max_step_height_m`` over
         less than a metre, or a slope steeper than ``game.max_slope_deg``
         over more (``core/relief.slope_blocks``). Last because the height of
         a point depends on which location owns it; exempt within
         ``_POS_OPENING_TOLERANCE_M`` of an opening, which IS the ramp onto a
         place.

    Every refusal carries ``{reason, message, pos, location_id}`` where ``pos``
    is the LAST VALID point — the client snaps the figure back onto it, so a
    refusal never leaves the two views disagreeing.

    FOOTPRINT WINS — FOR THE PASSABILITY (decision 2026-08-13, narrowed by
    finding 3). Painted terrain judges whether one MAY STAND out in the
    WILDERNESS, not inside a placed location: a point inside ANY footprint
    skips the terrain check entirely. What it does NOT skip is the pace and
    the movement animation — those belong to the topmost terrain everywhere,
    so a village on a lake is waded through instead of being strolled over
    (§ A15). A location is placed ON the
    world, it does not inherit the ground somebody painted under it — a hall
    on a rock plateau or an island of a village on water would otherwise be a
    place one can never stand in (acceptance finding B1), and entry there is
    gated by openings and rules already, which is the gate that belongs to a
    place. It is also the PREREQUISITE for the E8 heightmap plateau: the
    ground under a footprint is levelled there, and painted rock under that
    levelling must not keep refusing the flattened ground.

    THE TRANSITION GATE. ``location_at_point`` derives the location of the
    reported point. Same location, or wilderness → wilderness, is accepted as
    it stands. Otherwise:

      * ENTRY (a different, non-empty location): across an authored boundary
        opening — the point must lie within ``_POS_OPENING_TOLERANCE_M`` of
        one of the target's opening world points (§ A1.1) — and only when
        ``accessible_when`` and the access rules pass. Those two are the very
        gates ``/play/travel`` applies before it sets off; a free walker that
        could stroll past them would make every one of them decoration
        (E3-C1). A location with NO authored opening at all has a FREE
        boundary (decision E4 task 5): it never said where its way in is, the
        mirror of ``may_leave``'s "no entry room = leave anywhere" — the rule
        gates still apply,
      * EXIT: ``boundary_entry.may_leave`` with the room the avatar stands in
        — across a NEAR opening from the room it links to, from the entry room
        over any edge, or freely when the location declares no entry room —
        AND ``rules.check_leave``, the same rule gate every other movement
        path asks before it moves anybody,
      * location → location (adjacent or NESTED footprints — a hut on a
        village square) is both: the exit check of the old one, then the
        entry check of the new one.

    ONLY THE REPORTED POINT IS JUDGED, never the way to it. That is by
    design, not an oversight: a client reporting three times a second moves
    about a metre between reports, which cannot hop anything the world has,
    and reconstructing the path server-side would be a SECOND movement model
    beside the one the client walks — the model that would then disagree with
    the picture. The step-plausibility bound is what keeps the gap small
    enough for that to hold.

    A running journey is cancelled by the first accepted report — free walking
    OVERRIDES travel deliberately (``set_character_pos`` does it for every
    position write that is not a travel step; the ticker would otherwise pull
    the figure back onto its baked polyline on the next tick).

    Gates hand-derived in ``scripts/smoke_play_pos.py``.
    """
    import math
    import time
    from app.core.i18n import t
    from app.models.account import get_active_character
    from app.models.character import (get_character_current_location,
                                      get_character_current_room,
                                      get_character_language,
                                      get_character_pos,
                                      is_character_sleeping,
                                      save_character_current_room,
                                      set_is_sleeping,
                                      set_character_pos)

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="x/z required")
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="no active avatar")
    lang = get_character_language(avatar) or "de"

    from app.core.party_engine import is_party_follower
    if is_party_follower(avatar):
        raise HTTPException(status_code=403, detail={
            "reason": "party_follower",
            "message": t("You are part of a party and your leader takes you "
                         "along — you cannot move on your own.", lang)})

    try:
        x, z = float(body.get("x")), float(body.get("z"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="x/z must be numbers")
    if not (math.isfinite(x) and math.isfinite(z)):
        raise HTTPException(status_code=400, detail="x/z must be finite")

    now = time.monotonic()
    last_at = _pos_report_at.get(avatar)
    if last_at is not None and now - last_at < _POS_REPORT_INTERVAL_S:
        return {"ok": False, "throttled": True}

    here = get_character_pos(avatar)
    current_id = get_character_current_location(avatar) or ""

    def refuse(status: int, reason: str, message: str):
        """Refuse with the last VALID point — the client snaps back onto it."""
        raise HTTPException(status_code=status, detail={
            "reason": reason, "message": message,
            "pos": here, "location_id": current_id})

    # The step. Measured against the last ACCEPTED report, because that is the
    # last point this route vouched for; without one (a fresh session, a
    # takeover, an admin move) there is no baseline and the point is taken as
    # given — the terrain and the transition gate still judge it.
    if here is not None and last_at is not None:
        from app.core.timeutils import game_speed_factor
        from app.core.travel_engine import get_travel_speed_m_s
        elapsed = max(0.0, now - last_at)
        allowance = max(_POS_STEP_FLOOR_M,
                        _POS_STEP_FACTOR * get_travel_speed_m_s()
                        * game_speed_factor() * elapsed,
                        _POS_STEP_FACTOR * _POS_WALK_SPEED_M_S * elapsed)
        if math.hypot(x - here["x"], z - here["z"]) > allowance:
            logger.info("pos refused (too far): %s %.2f,%.2f -> %.2f,%.2f "
                        "in %.2fs (allowance %.2f m)", avatar,
                        here["x"], here["z"], x, z, elapsed, allowance)
            refuse(409, "too_far",
                   t("You cannot get there that quickly.", lang))

    from app.core.world_geometry import location_at_point
    from app.models.world import get_location_by_id, list_locations
    # ONE snapshot for the whole report — the terrain gate below, the
    # transition gate and the sight discovery at the end ask the same question
    # of the same table, and a walking client sends up to four reports a
    # second. Reading it twice costs a full table read plus the per-row meta
    # parsing every time.
    _locs = list_locations()
    derived = location_at_point(x, z, _locs)
    derived_id = (derived.get("id") or "") if derived else ""

    # TERRAIN — AND ONLY OUT IN THE WILDERNESS (decision 2026-08-13,
    # "footprint wins"). The location is derived FIRST on purpose: painted
    # ground is the surface of the world BETWEEN the places, not the floor of
    # a placed one. Inside a footprint the place brings its own floor and its
    # own gate (openings + rules, below), so a hall on a rock plateau or a
    # village on a lake stays a place one can stand in instead of a spot every
    # single report is refused on (acceptance finding B1). It is also what E8's
    # heightmap plateau needs: the ground under a footprint is levelled there,
    # and the rock painted under that levelling must not veto the flat top.
    if not derived_id:
        # ONE terrain read for the check AND for the answer. Both functions
        # take the areas and the catalog as parameters (the nav grid prefetches
        # them the same way); without hoisting them the refusal path would
        # re-read every painted area and rebuild the catalog a second time.
        from app.core.terrain_query import kind_at, passability_at
        from app.core.terrain_types import effective_catalog
        from app.models.terrain import list_areas
        _areas = list_areas()
        _catalog = effective_catalog()
        if not passability_at(x, z, areas=_areas, catalog=_catalog)[0]:
            # NAME THE GROUND. "You cannot walk there." was true and useless:
            # the player sees a spot that looks like every other one and gets
            # no way to tell a painted rock from a rule, a party lock or a
            # missing opening. The display name is the terrain catalog's, the
            # kind slug is the fallback for an area whose type was deleted.
            kind = kind_at(x, z, areas=_areas)
            entry = _catalog.get(kind) or {}
            ground = str(entry.get("name") or "").strip() or kind
            # …and it LOGS like every other refusal reason. This was the only
            # one without a line, which is exactly why the finding needed the
            # user to explain the world to us.
            logger.info("pos refused (impassable): %s at %.2f,%.2f on %s",
                        avatar, x, z, kind)
            refuse(409, "impassable",
                   t("You cannot walk there — that is {ground}.", lang)
                   .format(ground=ground))

    entry_room = ""
    if derived_id != current_id:
        from app.core.boundary_entry import (may_leave, opening_entry_room,
                                             opening_world_points)
        if current_id:
            # LEAVING. The exit edge is not a step direction any more, so it is
            # read off the point: every opening the crossing happens AT is a
            # candidate, and ``may_leave`` answers for each. With none nearby
            # the empty edge letter matches no opening, which is exactly right
            # — the entry-room rule and the "no entry room at all" rule are
            # what is left, and those are the other two ways out.
            current_loc = get_location_by_id(current_id) or {}
            current_room = get_character_current_room(avatar) or ""
            entry_gate = str(current_loc.get("entry_room") or "").strip()
            edges = [edge for edge, (ox, oz)
                     in opening_world_points(current_loc)
                     if math.hypot(ox - x, oz - z) <= _POS_OPENING_TOLERANCE_M]
            if not any(may_leave(current_loc, current_room, entry_gate, edge)
                       for edge in (edges or [""])):
                logger.info("pos refused (leave): %s out of %s from room %r",
                            avatar, current_id, current_room)
                refuse(403, "leave_blocked",
                       t("You cannot leave the place here — take the way you "
                         "came in.", lang))
            # ``rules.check_leave`` — the RULE side of leaving, and the one
            # every other movement path in this world asks: ``/play/travel``
            # before it sets off, the travel ticker at the arrival, the
            # SetLocation skill, the scheduler, and the grid step that used to
            # sit here. Geometry alone is not the gate: a ``confine`` or
            # danger rule that holds the avatar in place must hold it when it
            # WALKS out too, or the movement channel quietly undoes what
            # ``/play/notices`` is telling the player at that very moment.
            from app.models.rules import check_leave
            leave_ok, leave_reason = check_leave(avatar,
                                                 target_location_id=derived_id)
            if not leave_ok:
                logger.info("pos refused (leave rule): %s out of %s: %s",
                            avatar, current_id, leave_reason)
                refuse(403, "block_leave", leave_reason)
        if derived_id:
            # ENTERING. Through an authored opening, and past the gates the
            # travel route applies to the very same destination.
            best_edge, best_dist = "", None
            for edge, (ox, oz) in opening_world_points(derived):
                dist = math.hypot(ox - x, oz - z)
                if best_dist is None or dist < best_dist:
                    best_edge, best_dist = edge, dist
            if best_dist is None:
                # NO AUTHORED OPENINGS AT ALL = a free boundary (controller
                # decision, E4 task 5 review). The mirror of ``may_leave``'s
                # third rule: a location that declares no entry room lets one
                # out anywhere, and a location that draws no opening has not
                # said where its way in is either. Without this a painted
                # square, a meadow or any ``passable`` transit place would be
                # a wall to a free walker, which is the opposite of what those
                # places are for — and one CANNOT author an opening around
                # them for every direction a walker may come from.
                # The rule gates below are untouched: an openingless place is
                # still subject to ``accessible_when`` and the access rules.
                # ``opening_entry_room("")`` answers '' and the ordinary
                # arrival rule decides the room.
                pass
            elif best_dist > _POS_OPENING_TOLERANCE_M:
                # It HAS openings — then those are the ways in, and this is
                # not one of them (strictness decision 2026-08-04).
                logger.info("pos refused (no opening): %s into %s at %.2f,%.2f",
                            avatar, derived_id, x, z)
                refuse(403, "no_opening",
                       t("There is no way in here.", lang))
            from app.core.world_ops import conditions_pass
            if not conditions_pass(derived.get("accessible_when") or [],
                                   avatar, derived_id):
                logger.info("pos refused (accessible_when): %s into %s",
                            avatar, derived_id)
                refuse(403, "not_accessible",
                       t("This place is not accessible to you.", lang))
            from app.core.danger_system import check_location_access
            enter_ok, enter_reason = check_location_access(avatar, derived)
            if not enter_ok:
                logger.info("pos refused (access rule): %s into %s: %s",
                            avatar, derived_id, enter_reason)
                refuse(403, "block_enter", enter_reason)
            # Arrival semantics, the same ones every other arrival path uses:
            # the location is written by ``set_character_pos`` through
            # ``save_character_current_location`` (which discovers the place
            # and lands the avatar in the arrival room), and an opening that
            # names a room overrides that — it answers the question itself.
            entry_room = opening_entry_room(derived, best_edge)

    # THE GROUND PUSHES BACK (E8 task 1). Height is a RULE from here on: a
    # step too high or a slope too steep refuses the report, on the relief the
    # detail scenes already carry. It sits AFTER the transition gate on
    # purpose — the height of a point depends on WHICH location owns it, and
    # entering through a door that the geometry allows must not be answered
    # with "too steep" when the real reason is a rule.
    #
    # Δh is measured between the last valid point and the reported one, and
    # that is computable without reconstructing any path: two points, two
    # samples. It is the same "only the reported point is judged" contract as
    # everywhere else in this route — over one report the walker moves about a
    # metre, which cannot hop a cliff.
    #
    # Without a previous point (a fresh session, a takeover, an admin move)
    # there is no height to compare against and the gate skips, exactly like
    # the step-plausibility bound above.
    if here is not None:
        from app.core.boundary_entry import opening_world_points
        from app.core.relief import (STEP_DISTANCE_M, get_max_slope_deg,
                                     get_max_step_height_m, ground_lift_at,
                                     slope_blocks)
        # ``ground_lift_at`` asks the WORLD, not the derived location: a place
        # without a relief of its own stands ON the ground under it instead of
        # flattening it, so the innermost ENCLOSING relief answers. Without
        # that a hut on a relief square would sit in a hole of its own making
        # and seal itself off (finding F3).
        dh = ground_lift_at(x, z, _locs) \
            - ground_lift_at(here["x"], here["z"], _locs)
        dist = math.hypot(x - here["x"], z - here["z"])
        def _at_an_opening() -> bool:
            """OPENINGS ARE RAMP ENDS. An authored opening sits on the edge
            of a place, which is exactly where the ground steps up onto it —
            and an opening is by definition the way in. Refusing the crossing
            for its height would lock a place behind its own door, so a point
            within the entry tolerance of an opening of either location is
            exempt, at BOTH ends of the step (a crossing has one foot on each
            side). Asked only once the rule has already said "blocked": the
            openings are parsed out of ``map3d``, and this route runs up to
            four times a second per walker."""
            # Both ends are resolved GEOMETRICALLY, out of the snapshot this
            # report already read: the location the previous point lies in,
            # not the avatar's recorded ``current_location``. The two can
            # disagree — an admin move, a takeover, a teleport — and it is the
            # POINT whose door this is about.
            was = location_at_point(here["x"], here["z"], _locs)
            for loc in (derived, was):
                for _edge, (ox, oz) in opening_world_points(loc or {}):
                    if min(math.hypot(ox - x, oz - z),
                           math.hypot(ox - here["x"], oz - here["z"])) \
                            <= _POS_OPENING_TOLERANCE_M:
                        return True
            return False

        max_step = get_max_step_height_m()
        if slope_blocks(dh, dist, max_step,
                        get_max_slope_deg()) and not _at_an_opening():
            # NAME THE OBSTACLE (the B1 lesson: "you cannot walk there" tells
            # the player nothing they can act on). A step and a slope are two
            # different things to look at, so they get two different sentences
            # — and the sentence follows WHICH limit actually fired, not the
            # distance: a short report can be refused by the SLOPE limit with
            # its step well inside the cap, and calling that "a step too high"
            # would send the player looking for the wrong obstacle.
            # The refusal LOGS, like every other reason here.
            step = dist < STEP_DISTANCE_M and abs(dh) > max_step
            logger.info("pos refused (too steep): %s %.2f,%.2f -> %.2f,%.2f "
                        "dh %.2f m over %.2f m (%s)", avatar, here["x"],
                        here["z"], x, z, dh, dist,
                        "step" if step else "slope")
            refuse(409, "too_steep",
                   t("That step is too high to climb.", lang) if step else
                   t("That slope is too steep to climb.", lang))

    written = set_character_pos(avatar, x, z)
    if entry_room:
        save_character_current_room(avatar, entry_room)
    # DISCOVERY BY SIGHT (E6): walking past a place reveals it, the same rule
    # the travel ticker applies to everybody else. AFTER the gates on purpose
    # — a refused report moved nobody and must reveal nothing, and every
    # refusal above leaves through ``refuse`` before this line. The avatar
    # gets it here rather than from the ticker alone so the map fills in at
    # walking pace instead of at tick pace. It reuses the snapshot the
    # transition gate already read — see ``_locs`` above.
    try:
        from app.core.discovery import discover_in_range
        discover_in_range(avatar, x, z, locations=_locs)
    except Exception as e:
        logger.debug("sight discovery failed for %s: %s", avatar, e)
    # Walking is player-driven movement, and that is the clearest wake signal
    # there is — the same rule ``/play/enter-room`` and ``/play/travel`` apply
    # (a sleeping avatar must not walk a road in its sleep). It sits AFTER the
    # gates on purpose: a refused report moved nobody, so it wakes nobody.
    if is_character_sleeping(avatar):
        set_is_sleeping(avatar, False)
        logger.info("pos: %s woke up by walking", avatar)
    _pos_report_at[avatar] = now
    return {"ok": True, "pos": written["pos"],
            "location_id": written["location_id"],
            "room_id": get_character_current_room(avatar) or ""}


@router.post("/play/scene-photo/prepare")
async def play_scene_photo_prepare(user=Depends(get_current_user)):
    """📷 step 1: distills the photo prompt from the recent room
    conversation (+ person descriptions) WITHOUT generating — feeds the
    image-gen dialog (model/LoRA/prompt selection)."""
    import asyncio
    from app.models.account import get_active_character
    from app.core.scene_photo import prepare_scene_photo
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=404, detail="no active avatar")
    result = await asyncio.to_thread(prepare_scene_photo, avatar)
    if not result.get("ok"):
        raise HTTPException(status_code=502,
                            detail=result.get("error", "prepare failed"))
    return result


@router.post("/play/scene-photo")
async def play_scene_photo(request: Request, user=Depends(get_current_user)):
    """📷 step 2: renders the photo into the avatar's gallery. Body may
    carry dialog overrides (prompt, backend, loras, negative_prompt,
    character_names, use_room) — without them the one-click defaults run.
    The action is announced as a narrator line so present characters can
    react."""
    import asyncio
    from app.models.account import get_active_character
    from app.core.scene_photo import take_scene_photo
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=404, detail="no active avatar")
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    result = await asyncio.to_thread(
        take_scene_photo, avatar,
        str(body.get("prompt") or ""),
        str(body.get("backend") or ""),
        body.get("loras"),
        str(body.get("negative_prompt") or ""),
        body.get("character_names"),
        bool(body.get("use_room", True)))
    if not result.get("ok"):
        raise HTTPException(status_code=502,
                            detail=result.get("error", "photo failed"))
    return result


@router.post("/play/scene-render")
async def play_scene_render(request: Request, user=Depends(get_current_user)):
    """Renders the current scene (room background + present characters) as
    one composed image — the environment panel's "Rendered" view. Manual
    trigger only; force=true bypasses the signature cache (fresh seed)."""
    import asyncio
    from app.models.account import get_active_character
    from app.core.scene_render import render_scene
    avatar = (get_active_character() or "").strip()
    if not avatar:
        raise HTTPException(status_code=404, detail="no active avatar")
    force = False
    try:
        body = await request.json()
        force = bool((body or {}).get("force"))
    except Exception:
        pass
    result = await asyncio.to_thread(render_scene, avatar, force)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error") or "render failed")
    return result


@router.get("/play/scene-render/image")
async def play_scene_render_image(sig: str, user=Depends(get_current_user)):
    """Serves a rendered scene image by its cache signature."""
    import re as _re
    from app.core.scene_render import get_scene_image_path
    if not _re.fullmatch(r"[0-9a-f]{8,64}", (sig or "").strip()):
        raise HTTPException(status_code=400, detail="invalid sig")
    p = get_scene_image_path(sig.strip())
    if not p.exists():
        raise HTTPException(status_code=404, detail="not rendered")
    return FileResponse(p, media_type="image/png",
                        headers={"Cache-Control": "no-cache"})


# --- Location 3D building model (AV3D-9) — consumed by the 3D map client ---
# Open like the character /model route so the external client can fetch them;
# 404 stays normal (the client keeps rendering the location procedurally).

@router.get("/play/locations/{location_id}/model")
def play_location_model(location_id: str, request: Request, tier: str = ""):
    """Serves the location's 3D building model (GLB bytes) in the requested
    resolution tier (``full`` = default, ``low`` = the distance mesh). A tier
    the location does not have falls back to the best available one; 404 = no
    model at all. ETag/If-None-Match — the file changes rarely.

    A request for a low variant that does not exist yet ALSO starts the
    background build (like the character twin ``find_model3d_serving_tier``):
    this answer stays the full model, the next one has the real thing. The
    store checks its own gates — switched off or already built does nothing."""
    from fastapi.responses import Response
    from app.core.location_model3d import (LOW_TIER, find_building_model,
                                           request_low_tier)
    from app.core.http_files import etag_file_response
    from app.core.model_store import normalize_tier
    p = find_building_model(location_id, tier=tier)
    if not p:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    if normalize_tier(tier) == LOW_TIER:
        request_low_tier(location_id)
    media = ("model/gltf-binary" if p.suffix.lower() == ".glb"
             else "application/octet-stream")
    return etag_file_response(p, request, media)


@router.get("/play/locations/{location_id}/model/meta")
def play_location_model_meta(location_id: str):
    """Meta of the location's building model ({format, rig, tiers, url}).
    ``tiers`` names the resolution tiers that exist, each with its own
    signature; ``url`` serves the default tier, ``?tier=`` any other.
    404 = none."""
    from urllib.parse import quote
    from app.core.location_model3d import get_client_meta
    meta = get_client_meta(location_id)
    if not meta:
        raise HTTPException(status_code=404, detail="No model")
    base = f"/play/locations/{quote(location_id)}/model"
    return {**meta, "url": base,
            "tiers": {t: {**info, "url": f"{base}?tier={t}"}
                      for t, info in (meta.get("tiers") or {}).items()}}


def _test_figure_file():
    """The preview test figure, in priority order: a user-provided Mixamo
    STANDARD character (X Bot & Co.) from shared/models/figure/ — else the
    first humanoid character model as the fallback. Returns (path,
    format, source) or (None, '', '')."""
    import json as _json
    from app.core.paths import get_test_figure_dir
    d = get_test_figure_dir()
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in (".glb", ".gltf", ".fbx"):
                fmt = "fbx" if p.suffix.lower() == ".fbx" else "glb"
                return p, fmt, "standard"
    from app.models.character import list_available_characters
    from app.core.model3d import find_model3d
    for name in list_available_characters():
        p = find_model3d(name)
        if not p or p.suffix.lower() not in (".glb", ".gltf"):
            continue
        try:
            meta = _json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        if (meta.get("rig") or "mixamo") != "mixamo":
            continue
        return p, "glb", "character"
    return None, "", ""


@router.get("/play/test-figure/model")
def play_test_figure_model(request: Request):
    """The preview TEST FIGURE (floor-plan marker/scale figures): a
    Mixamo standard character from shared/models/figure/ when provided,
    else the first humanoid character model. 404 when neither exists —
    the preview falls back to its mannequin."""
    from fastapi.responses import Response
    from app.core.http_files import etag_file_response
    p, fmt, _src = _test_figure_file()
    if not p:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    media = "model/gltf-binary" if fmt == "glb" else "application/octet-stream"
    return etag_file_response(p, request, media)


@router.get("/play/test-figure/meta")
def play_test_figure_meta():
    """Format/source of the test figure — the preview picks its loader
    (GLTF vs FBX) from it. 404 = no figure available."""
    p, fmt, src = _test_figure_file()
    if not p:
        raise HTTPException(status_code=404, detail="No test figure")
    return {"format": fmt, "source": src,
            "url": "/play/test-figure/model"}


# --- Room models (AV3D-2) — same contract as the building model, addressed
# by room id alone (room ids are template-identical across clones).
# ⚠ These three routes cannot address the GROUND room: its id is reserved and
# every location owns one, so the bare-id lookup (find_location_by_room) would
# answer with whichever location comes first. Deferred by design (C1) — the
# ground has neither a room model nor a room layout, its geometry comes from
# the location's scene recipe, so nothing asks for it today.

@router.get("/play/rooms/{room_id}/model")
def play_room_model(room_id: str, request: Request, tier: str = ""):
    """Serves the room's 3D model (GLB bytes) in the requested resolution tier
    (``full`` = default), falling back to the best available one. 404 = no
    model (the client keeps rendering the room as a plain slab).
    ETag/If-None-Match.

    A request for a low variant that does not exist yet ALSO starts the
    background build — same contract as the building twin above."""
    from fastapi.responses import Response
    from app.models.world import find_location_by_room
    from app.core.location_model3d import (LOW_TIER, find_building_model,
                                           request_low_tier)
    from app.core.http_files import etag_file_response
    from app.core.model_store import normalize_tier
    loc = find_location_by_room(room_id)
    p = (find_building_model(loc.get("id", ""), room_id=room_id, tier=tier)
         if loc else None)
    if not p:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    if normalize_tier(tier) == LOW_TIER:
        request_low_tier(loc.get("id", ""), room_id)
    media = ("model/gltf-binary" if p.suffix.lower() == ".glb"
             else "application/octet-stream")
    return etag_file_response(p, request, media)


@router.get("/play/rooms/{room_id}/recipe")
def play_room_recipe(room_id: str):
    """The furnished room in ONE payload (plan-room-props.md): hull outline
    in absolute plate fractions, openings on polygon edge indices — including
    the neighbours' openings on shared walls — prop placements joined with
    their real dims (REAL-SIZE rule) and the object-local markers composed
    into placement-relative world transforms. 404 = the room has no layout
    (client auto-grid as before). Contract:
    shared/backend-note-room-recipe.md."""
    from app.models.world import find_location_by_room
    from app.core.room_recipe import compose_recipe
    loc = find_location_by_room(room_id)
    room = None
    siblings = []
    plan_width_m = 0.0
    if loc:
        rooms = loc.get("rooms") or []
        room = next((r for r in rooms if r.get("id") == room_id), None)
        siblings = [r for r in rooms if r.get("id") != room_id]
        # Only the EXPLICIT scale anchor — deriving it from the building model
        # parses the whole GLB, far too much for a polled endpoint. Without it
        # the composer falls back to the 8 m reference plate, exactly like the
        # editor does when it has no plan width either.
        try:
            plan_width_m = float((loc.get("map3d") or {}).get("plan_width_m") or 0)
        except (TypeError, ValueError, AttributeError):
            plan_width_m = 0.0
    recipe = compose_recipe(room, siblings, plan_width_m) if room else None
    if not recipe:
        raise HTTPException(status_code=404, detail="No layout")
    return recipe


@router.get("/play/rooms/{room_id}/model/meta")
def play_room_model_meta(room_id: str):
    """Meta of the room's 3D model ({format, rig, rotation, tiers, url}) —
    same tier contract as the building model. 404 = none."""
    from urllib.parse import quote
    from app.models.world import find_location_by_room
    from app.core.location_model3d import get_client_meta
    loc = find_location_by_room(room_id)
    meta = get_client_meta(loc.get("id", ""), room_id=room_id) if loc else None
    if not meta:
        raise HTTPException(status_code=404, detail="No model")
    base = f"/play/rooms/{quote(room_id)}/model"
    return {**meta, "url": base,
            "tiers": {t: {**info, "url": f"{base}?tier={t}"}
                      for t, info in (meta.get("tiers") or {}).items()}}


# --- Scene recipe (shared/schnittstellen-3d.md part B) — the COMPLETE scene
# of a location as finished primitives + placement specs, so the renderers
# own no geometry decision of their own (app/core/scene_recipe.py).
# ⚠ Not to be confused with GET /play/scene above: that is the avatar's CHAT
# perception and has nothing to do with 3D.

def _scene_inputs(location: dict, location_id: str) -> tuple:
    """(plan_width_m, building_meta, room_metas) — everything the composer
    needs from disk. Clones need no special handling: the model store
    redirects them to their template (gallery owner) and room ids are
    template-identical, so the same call works for template and clone."""
    from app.core.location_model3d import derive_plan_width_m, get_client_meta
    map3d = location.get("map3d") or {}
    if not location_id:
        try:
            plan_width_m = float(map3d.get("plan_width_m") or 0)
        except (TypeError, ValueError):
            plan_width_m = 0.0
        return plan_width_m, {}, {}
    room_metas = {}
    for room in location.get("rooms") or []:
        if not isinstance(room, dict) or not room.get("layout"):
            continue
        rid = str(room.get("id") or "")
        meta = get_client_meta(location_id, room_id=rid) if rid else None
        if meta:
            room_metas[rid] = meta
    return (derive_plan_width_m(location_id, map3d),
            get_client_meta(location_id) or {}, room_metas)


@router.get("/play/locations/{location_id}/scene")
def play_location_scene(location_id: str):
    """The whole location as a ready-to-render scene: plates, walls, extras,
    model placement specs, figures, markers, doorways and problems — all in
    world metres around the tile centre (contract § B1). Poll ``signature``
    for changes.

    404 = nothing to compose (no building outline, no room with a layout and
    no building model) — that is the legacy auto-grid case, the client keeps
    rendering the location procedurally as before."""
    from app.models.world import get_location_by_id
    from app.core.scene_recipe import compose_scene
    from app.core.surface_textures import library_kinds
    loc = get_location_by_id(location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    plan_width_m, building_meta, room_metas = _scene_inputs(loc, location_id)
    map3d = loc.get("map3d") or {}
    has_layout = any(isinstance(r, dict) and r.get("layout")
                     for r in loc.get("rooms") or [])
    if not has_layout and len(map3d.get("outline") or []) < 3 \
            and not building_meta:
        raise HTTPException(status_code=404, detail="No scene")
    return compose_scene(loc, plan_width_m=plan_width_m,
                         building_meta=building_meta, room_metas=room_metas,
                         surface_kinds=library_kinds())


@router.post("/play/scene-preview")
async def play_scene_preview(request: Request, _=Depends(require_admin)):
    """The same payload for an UNSAVED location draft (contract § B3) — the
    Game-Admin floor-plan preview renders from the same composer as the 3D
    client instead of reimplementing the geometry. Body = a location entry
    ({id?, map3d, rooms:[{id, name, layout}]}); nothing is persisted.

    The draft runs through the world editor's own sanitizers first — no
    unchecked user payload reaches the composer. With a known ``id`` the
    stored model metas (scale anchor, orientation fixes, width_m) are pulled
    in, so the preview matches what the client will see."""
    from app.models.world import get_location_by_id
    from app.core.scene_recipe import compose_scene
    from app.core.surface_textures import library_kinds
    from app.core.world_ops import _sanitize_map3d, _sanitize_rooms_layout
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    rooms = [{"id": str(r.get("id") or ""),
              "name": r.get("name") or "",
              "layout": r.get("layout")}
             for r in (data.get("rooms") or []) if isinstance(r, dict)]
    try:
        rotation_2d = int(data.get("map_rotation_2d") or 0)
    except (TypeError, ValueError):
        rotation_2d = 0
    draft = {
        "id": str(data.get("id") or ""),
        "map_rotation_2d": rotation_2d,
        # The ground outside is part of the draft: an edited terrain must
        # change the preview's ground plate, or the editor would show one
        # ground and the client another — the very split § 5 closes.
        "terrain": str(data.get("terrain") or "").strip(),
        "map3d": _sanitize_map3d(data.get("map3d")),
        "rooms": _sanitize_rooms_layout(rooms),
    }
    known = bool(draft["id"] and get_location_by_id(draft["id"]))
    plan_width_m, building_meta, room_metas = _scene_inputs(
        draft, draft["id"] if known else "")
    return compose_scene(draft, plan_width_m=plan_width_m,
                         building_meta=building_meta, room_metas=room_metas,
                         surface_kinds=library_kinds())


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
    """Storyteller fallback (plan-room-conversation, option 3): if no present
    character reacts to an avatar utterance (e.g. alone with a bear), the
    storyteller steps in and narrates the surroundings/consequence. The narration
    lands as a storyteller perception in the stream (appears in the next /play/scene).

    Lautstärke = Reichweite: schreien narriert ortsweit (scope=location), sonst
    nur den aktuellen Raum (scope=here) — konsistent mit der Utterance-Hörweite.
    """
    try:
        from app.core.act_engine import perform_act
        # perform_act writes narration + event verdict ITSELF as the
        # storyteller line into the stream (act_engine._record_act_to_stream)
        # — no second record_utterance here or entries duplicate.
        scope = "location" if volume == "shout" else "here"
        await perform_act(actor, text, scope)
        logger.info("Storyteller-Fallback narrierte für %s (scope=%s)", actor, scope)
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
    # Spell detection has NO model routed while the avatar carries spell items:
    # `detect_and_cast` then fails silently (`resolve_llm` returns None, the
    # except below swallows it) and the incantation lands in the room as plain
    # words. Without this flag the player is left guessing why nothing happens
    # — the 1:1 chat path has warned about it since `chat.py:794`, /play did not
    # (A3 of plan-room-conversation-ergaenzungsplan.md).
    spell_routing_missing = False
    spell_target = next((a for a in addressees if a and a != avatar), "")
    if spell_target and content.strip():
        try:
            from app.core.spell_engine import (
                build_spell_catalog, detect_and_cast, has_spell_detect_routing)
            if build_spell_catalog(avatar) and not has_spell_detect_routing(avatar):
                spell_routing_missing = True
                logger.warning(
                    "play_say: no LLM routed for spell_detect — %s carries spell "
                    "items, no cast can run", avatar)
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
    #     made visible as a storyteller result line AND passed to the target when it reacts
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

    # 2b) Make the spell result (success_/fail_text) visible as a storyteller line.
    #     location_id explicit — the storyteller has no own location; the anchor
    #     gives it the caster's point, without which the line reaches nobody out
    #     in the open (it has no circle of its own).
    if _is_spell:
        _hint = (spell.get("hint") or "").strip()
        if _hint:
            record_utterance(speaker=STORYTELLER_SPEAKER, content=_hint, volume=VOLUME_NORMAL,
                             location_id=loc, room_id=room, source="spell",
                             anchor=avatar)

    # 3) Reaktionen über den Loop verteilen: Adressierte → Pflicht-Antwort,
    #    übrige Anwesende → Chime. Bei Spell reagiert das Ziel auf die WIRKUNG
    #    (Inhalt = chat_substitute + hint), nicht auf die rohen Zauberworte.
    #    Party-Einladung (Flow 1): KEINE Sonderbehandlung mehr — lädt der Avatar
    #    einen NPC per Natural Speech ein ("komm mit …"), antwortet der NPC ganz
    #    normal und ruft bei Zustimmung in seinem Turn das JoinParty-Skill auf.
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
            "spell_routing_missing": spell_routing_missing,
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
             "outfit_sets": []}
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
        # Relationship of the avatar TO each present character. Built ONCE
        # per request, then looked up per character.
        try:
            from app.core.world_ops import build_relation_map
            relations = build_relation_map(avatar)
            for blk in out["characters"]:
                blk["relation"] = relations.get(blk["name"])
        except Exception as e:
            logger.debug("play_others relations failed: %s", e)
            for blk in out["characters"]:
                blk.setdefault("relation", None)
        # Party-Hervorhebung: markiere Anwesende, die zur Party des Avatars gehoeren.
        try:
            from app.core.party_engine import get_party_of
            p = get_party_of(avatar)
            members = {p["leader"], *p["members"]} if p else set()
            for blk in out["characters"]:
                blk["in_party"] = blk["name"] in members
        except Exception:
            pass
    except Exception as e:
        logger.debug("play_others failed: %s", e)
    return out


@router.get("/play/story-arcs")
async def play_story_arcs(user=Depends(get_current_user)):
    """The avatar's quest book: running arcs first, then the last finished
    ones. Spoiler-free by construction — see build_player_story_arcs."""
    from app.core.world_ops import build_player_story_arcs
    from app.models.account import get_active_character
    return build_player_story_arcs(get_active_character() or "")


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


# Core default display order + labels (English source; the UI localizes).
# A species package's `piece_slots` declaration replaces both (F2 —
# plan-body-slots.md): topology, order and labels then come from the package.
_SLOT_ORDER = ["head", "neck", "outer", "top", "underwear_top",
               "bottom", "underwear_bottom", "legs", "feet"]
_SLOT_LABELS = {"head": "Head", "neck": "Neck", "outer": "Coat & jacket",
                "top": "Top", "underwear_top": "Underwear top",
                "bottom": "Bottom", "underwear_bottom": "Underwear bottom",
                "legs": "Legs", "feet": "Feet"}


def build_belongings(character_name: str) -> dict:
    """Inventar + Outfit (Paper-Doll) eines Characters — Single-Source für das
    Avatar-Panel (/play) UND den Game-Admin-Garderoben-Tab.
    Liefert die getragenen Pieces pro Slot (für die Figur) und die volle
    Item-Liste mit Filter-Attributen (Kategorie/Slot/Outfit-Typ/Spell)."""
    avatar = (character_name or "").strip()
    out = {"avatar": "", "slot_order": _SLOT_ORDER, "slot_labels": _SLOT_LABELS,
           "equipped": {}, "items": [], "outfit_sets": [], "max_slots": 0,
           "silhouette_url": "", "slot_anchors": {}}
    if not avatar:
        return out
    out["avatar"] = avatar
    # Species topology + silhouette (body-slot core). Without a species
    # package the core defaults above stay in effect.
    try:
        from app.core.body_slots import declared_piece_slots, silhouette_for_character
        declared = declared_piece_slots(avatar)
        if declared:
            slots, labels = declared
            out["slot_order"] = list(slots)
            out["slot_labels"] = {s: labels.get(s, s) for s in slots}
        sil = silhouette_for_character(avatar)
        if sil:
            out["silhouette_url"] = f"/characters/{avatar}/silhouette"
            anchors = sil.get("anchors")
            if isinstance(anchors, dict):
                out["slot_anchors"] = anchors
    except Exception as e:
        logger.debug("belongings species topology failed: %s", e)
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
    res = equip_piece(avatar, item_id, source="avatar")
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("reason", "equip failed"))
    # Direct action is world-visible: narrator line -> NPCs can react.
    try:
        from app.models.inventory import get_item
        from app.core.perception import announce_action
        _nm = (get_item(item_id) or {}).get("name") or "etwas"
        announce_action(avatar, f"{avatar} zieht {_nm} an.", source="wardrobe")
    except Exception:
        pass
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
    res = unequip_piece(avatar, slot=slot, item_id=item_id, source="avatar")
    if res.get("status") != "ok":
        raise HTTPException(status_code=400, detail=res.get("reason", "unequip failed"))
    # Direct action is world-visible: narrator line -> NPCs can react.
    try:
        from app.models.inventory import get_item
        from app.core.perception import announce_action
        # Name the removed PIECE (the shoes), never the slot ("feet"). The
        # unequip result carries the removed item id — the request may only
        # have passed a slot.
        _removed_id = res.get("item_id") or item_id
        _nm = ((get_item(_removed_id) or {}).get("name") if _removed_id else "") or slot
        announce_action(avatar, f"{avatar} legt {_nm} ab.", source="wardrobe")
    except Exception:
        pass
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
    """Cast a spell from the inventory on the avatar itself — through
    spell_engine.execute_cast (honours copy_on_give, effect-item handover, cast
    activity). NOT consume_item (the spell would vanish despite copy_on_give)."""
    import asyncio
    from app.core.spell_engine import build_spell_catalog, execute_cast
    avatar = _require_avatar()
    body = await request.json()
    item_id = str((body or {}).get("item_id") or "").strip()
    spell = next((s for s in build_spell_catalog(avatar) if s.get("id") == item_id), None)
    if not spell:
        raise HTTPException(status_code=404, detail="not a spell or not in inventory")
    # Off the event loop: execute_cast sets the spell's cast activity via
    # set_pose_intent, which resolves it against the pose catalog and may
    # block on an embedding call. The result is used below, so it is awaited.
    res = await asyncio.to_thread(execute_cast, avatar, avatar, spell)
    # Make the effect visible as a storyteller line (location_id explicit — the
    # storyteller has no own location, otherwise the fan-out goes nowhere; the
    # anchor gives it the caster's point out in the open, where an empty
    # location is a place and not a missing value).
    try:
        from app.core.perception import record_utterance, VOLUME_NORMAL
        from app.models.character import (get_character_current_location,
                                          get_character_current_room)
        _loc = get_character_current_location(avatar) or ""
        _room = get_character_current_room(avatar) or ""
        _hint = (res.get("hint") or "").strip()
        if _hint:
            record_utterance(speaker=STORYTELLER_SPEAKER, content=_hint,
                             volume=VOLUME_NORMAL, location_id=_loc, room_id=_room,
                             source="spell", anchor=avatar)
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
        # Structured game-block detail: the frontend api layer treats a bare
        # 403 as an auth failure and kicks the user to the login screen —
        # this is a game rule, not an auth problem.
        raise HTTPException(status_code=403, detail={
            "reason": "block_foreign_gallery",
            "message": "Only images of your own gallery can be deleted."})
    if not delete_character_image(character, filename):
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}


@router.get("/play/worldmap")
async def play_worldmap(user=Depends(get_current_user),
                        show_all: int = Query(0, alias="all")):
    """Aggregated 2D world map — fog of war by default (§ A12).

    Default: only what the active avatar knows (`known_locations`, strict).
    `?all=1` lifts the fog and is reserved for admins (403 otherwise) — the
    unfiltered view for world building and debugging.
    """
    from app.models.account import get_active_character
    from app.core.world_ops import build_worldmap_payload

    is_admin = (user.get("role") == users.ROLE_ADMIN)
    if show_all and not is_admin:
        raise HTTPException(status_code=403,
                            detail="all=1 is reserved for admins")
    avatar = (get_active_character() or "").strip()
    return build_worldmap_payload(avatar, show_all=bool(show_all) and is_admin)


@router.get("/play/terrain")
def get_terrain_route(user=Depends(get_current_user)):
    """Painted terrain for map clients: areas + effective type catalog.

    Never fogged by design — terrain is always visible, only locations
    hide. Clients poll /play/worldmap and refetch this when terrain_sig
    changes.

    The scatter entries are enriched with what their prop knows on the way out
    (`variants` = the resolution tiers it HAS, `prop_height_m` = its real
    height, `sway_factor` = how much of its ground's wind it takes part in,
    § A9) — derived here, not stored, so a low variant generated later or a
    corrected height reaches the clients with the next refetch.
    """
    from app.core.terrain_query import default_kind
    from app.core.terrain_types import effective_catalog
    from app.models import terrain
    return {
        # ONE source of truth for the unpainted ground: the same resolver the
        # point queries use, so the map never paints a different default than
        # the walk rules apply.
        "default_kind": default_kind(),
        "types": sorted(effective_catalog().values(),
                        key=lambda t: t["kind"]),
        "areas": terrain.with_scatter_props(terrain.list_areas()),
        "sig": terrain.terrain_sig(),
    }


@router.get("/play/heightfield")
def get_heightfield_route(user=Depends(get_current_user)):
    """The world relief as a grid of support points (§ A16).

    Auth and fog exactly like ``/play/terrain``: any logged-in user, never
    fogged. A relief is not local knowledge — the ridge on the horizon is
    visible from far outside anything the avatar has discovered, and hiding it
    would only make the ground disagree with the picture.

    Its own endpoint (not a block in the worldmap poll) because it is by far
    the largest thing the map has: the payload is refetched when the worldmap's
    ``height_sig`` changes, and never otherwise.

    ``heights[j][i]`` is the height in metres at
    ``(origin_x + i·step_m, origin_z + j·step_m)``; between the points the
    field is BILINEAR (``@anima/scene-render`` ``sampleWorldHeight``, the twin
    of ``app/core/heightfield.sample_height``). An empty world answers
    ``rows``/``cols`` 0 and an empty ``heights`` — a flat world, not an error.

    IT IS THE DISTANT VIEW SINCE v2 (§ A16.3): this grid may stand at a
    coarsened ``step_m``, and the near ground plus every rule reads the TILES
    instead. ``tiles`` is the index — every tile the world has a ground in —
    and a client fetches those from ``/play/heightfield/tiles``. The two are
    never mixed: a reader takes either the tiles or the overview.
    """
    from app.core.heightfield import (TILE_M, TILE_STEP_M, get_field,
                                      tile_index_keys)
    field = get_field()
    return {
        "origin_x": field.get("origin_x", 0.0),
        "origin_z": field.get("origin_z", 0.0),
        "step_m": field.get("step_m", 0.0),
        "rows": field.get("rows", 0),
        "cols": field.get("cols", 0),
        "heights": field.get("heights", []),
        "sig": field.get("sig", ""),
        "tile_m": TILE_M,
        "tile_step_m": TILE_STEP_M,
        "tiles": tile_index_keys(),
    }


#: One-shot state of the two warnings below, one flag per channel — the route
#: is a client fetch path, so a warning per request would drown the log (the
#: ``backdrop.py`` pattern).
_TILE_KEY_WARNED: Dict[str, bool] = {}


@router.get("/play/heightfield/tiles")
def get_heightfield_tiles_route(keys: str = "", user=Depends(get_current_user)):
    """A batch of FINE height tiles — the ground the rules read (§ A16.3).

    Auth and fog exactly like ``/play/heightfield``: any logged-in user, never
    fogged. ``keys`` is ``tx:tz,tx:tz`` (colon inside a key, comma between
    them), at most ``TILE_BATCH_MAX`` keys per request.

    Tiles the index does not know are LEFT OUT — the client already has the
    index from ``/play/heightfield`` and treats a missing tile as flat ground,
    so there is nothing to report and nothing to ship. Unreadable tokens and
    keys past the cap are dropped for the same reason, and BOTH are said once
    here: a dropped tile is indistinguishable from flat ground on the other
    side, so the only place it can still be noticed is the log.
    """
    from app.core.heightfield import (TILE_BATCH_MAX, overflow_tile_keys,
                                      parse_tile_keys, tiles_payload,
                                      unusable_tile_tokens)
    junk = unusable_tile_tokens(keys)
    if junk and not _TILE_KEY_WARNED.get("junk"):
        _TILE_KEY_WARNED["junk"] = True
        logger.warning(
            "/play/heightfield/tiles: unreadable key%s '%s' skipped — the "
            "query is keys=tx:tz,tx:tz with integer tile indices",
            "s" if len(junk) > 1 else "", "', '".join(junk))
    dropped = overflow_tile_keys(keys)
    if dropped and not _TILE_KEY_WARNED.get("overflow"):
        _TILE_KEY_WARNED["overflow"] = True
        logger.warning(
            "/play/heightfield/tiles: %d key%s past the cap of %d dropped "
            "(first %s) — ask in several batches; the missing tiles read as "
            "flat ground on the client",
            len(dropped), "s" if len(dropped) > 1 else "", TILE_BATCH_MAX,
            ",".join(f"{tx}:{tz}" for tx, tz in dropped[:3]))
    return tiles_payload(parse_tile_keys(keys))


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
                  if p and p != avatar and p != STORYTELLER_SPEAKER]
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
    """The avatar sets its own pose/activity (free-text pose)."""
    import asyncio
    from app.models.character import (set_pose_intent, is_character_sleeping,
                                      set_is_sleeping, wake_from_offmap)
    avatar = _require_avatar()
    body = await request.json()
    activity = str((body or {}).get("activity") or "").strip()
    # Setting an activity while asleep wakes the avatar — the sleeping flag
    # otherwise overrides the displayed activity ("Sleeping").
    if activity and is_character_sleeping(avatar):
        set_is_sleeping(avatar, False)
        try:
            wake_from_offmap(avatar)
        except Exception:
            pass
    # Off the event loop: set_pose_intent resolves the text against the pose
    # catalog, which may embed it (a routed external embedding endpoint is a
    # blocking HTTP call) and writes the DB — that would stall every SSE stream.
    await asyncio.to_thread(set_pose_intent, avatar, activity)
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
    # Direct action is world-visible: narrator line -> NPCs can react.
    try:
        from app.core.perception import announce_action
        _onm = target.get("name") or ""
        announce_action(avatar,
                        f"{avatar} zieht sich um" + (f" — {_onm}." if _onm else "."),
                        source="wardrobe")
    except Exception:
        pass
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
    """Figure anchors in the environment panel (name → {x, y, scale}; x as a
    fraction 0..1, y may exceed 1 — the figure may overhang the stage bottom
    up to the frontend's FIG_OVERHANG boundary) for the CURRENT room +
    background image (``bg`` = bg_id) + each figure's current expression image.

    Source is the character data (not user settings) → the placement applies
    to all players. A position is keyed to (room, bg_id, expr_version): for a
    new image the entry is missing → the frontend uses its default position."""
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
    """Persists figure anchors + size in the character data, keyed to room +
    background image (``bg``) + expression image hash. Only figures present in
    the avatar's room."""
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
            if (m.get("content") or "").strip()
            or (m.get("metadata") or {}).get("image")]
    msgs = [{"mine": m.get("role") == "assistant",
             "content": m.get("content") or "",
             "ts": m.get("timestamp") or "",
             "image": (m.get("metadata") or {}).get("image") or ""} for m in hist]
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
