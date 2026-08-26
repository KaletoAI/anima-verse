#!/usr/bin/env python3
"""Smoke run for addressability in the open, real arrival rooms and the
"no walking away mid-conversation" guards (plan-npc-leben-bugs, task 4).

Throwaway storage, throwaway world DB, throwaway task queue — no server, no
real world is touched. No LLM runs: every NPC either comes out of the pool or
is written by ``apply_npc`` with the finish gate switched off, and the respond
lane is only BUMPED (``bump_respond`` is pure in-memory bookkeeping).

THE WORLD, drawn by hand — one grass rectangle from (−60, −60) to (300, 300)
and two placed locations, both a 10 m square around their anchor:

    INN     anchor (0, 0)     footprint x,z ∈ [−5, 5]     rooms taproom+cellar,
                                                          entry_room "taproom",
                                                          opening on edge 2
    MARKET  anchor (100, 0)   footprint x,z ∈ [95, 105]   room hall,
                                                          NO entry_room,
                                                          opening on edge 3

``game.hearing_radius_m`` is left unset, so the radius is the default 20.0 m
(``perception.DEFAULT_HEARING_RADIUS_M``). Every distance below is a plain
Euclidean metre distance in the x/z plane, computed by hand.

Hand-derived expectations:

  (a) OUT IN THE OPEN THE ROOM IS NOT THE RULE — the radius is.
      Avatar "Wren" stands at (0, 200): no location covers that point, so
      ``current_location`` derives to "". Two location-less NPCs:
        Roon    (10, 200)  → |(10,200)−(0,200)| = 10.0 m ≤ 20 → addressable
        Baldric (200, 200) → 200.0 m > 20            → NOT addressable
      ``addressable_for("Wren")`` is therefore exactly ["Roon"]. Before this
      task the answer was [] for every avatar without a location — which is
      what made a wanderer on the road unaddressable.

  (b) INSIDE A LOCATION THE ROOM RULE STAYS, AND THE RADIUS IS ADDED.
      The avatar walks to (0, 0) — inside INN's footprint, so its location
      derives to INN and its room to the entry room "taproom". Four others:
        Mira    INN / taproom          → same room            → addressable
        Osric   INN / cellar           → another room         → NOT
        Tove    (12, 0), no location   → 12.0 m ≤ 20 from the avatar's own
                                         point                → addressable
        Baldric (200, 200)             → 200.0 m … 283 m out  → NOT
      so ``addressable_for("Wren")`` is sorted ["Mira", "Tove"] — the room
      list and the earshot circle, one rule, never the avatar itself.
      ``play._present_characters`` is that same list (it IS the /play/others
      roster and the give/cast target gate), AND SO IS ``/play/scene.present``:
      the player UI builds the ADDRESSEE CHIPS from that field and clips the
      selection to it, so a room-only answer there made this whole mixed case
      unreachable through the UI — the gate would have taken Tove, the fan-out
      reached her (b2), and no chip ever offered her. ``present_detail`` is the
      same names with a portrait each; a location-less NPC needs no location in
      it. Out in the open (a) the field always did answer the circle, and it
      still does — that arm is checked too, so the collapse into one rule
      cannot quietly cost the wilderness roster.
      ``character_ops.build_characters_at_location(INN)`` — which is asked for
      a LOCATION, not for an avatar — measures its circle from the LOCATION's
      anchor (0, 0) instead: Tove at 12.0 m comes along with
      ``same_room`` False and an empty ``room``, Roon at
      |(10,200)−(0,0)| = 200.25 m does not.

  (b2) AND THE LINE ACTUALLY ARRIVES — the gate and the fan-out are one rule.
      An addressee that never hears the line is worse than no addressee: the
      answer never comes and the storyteller narrates over the silence. So the
      avatar SPEAKS in the taproom: ``record_utterance`` must produce perception
      rows for the room (Mira, and the avatar's own self-line) AND for Tove at
      the gate — three, not two — and ``dispatch_room_reactions`` with
      ``location_id`` INN must bump Tove obligatorily (addressed) and Mira as a
      chime. Osric in the cellar hears nothing either way (another room, and he
      is not location-less).
      A WHISPER is the one thing that does not cross the wall: the same line
      whispered at Tove reaches Mira (``whisper_meta``, the bare fact) and the
      avatar itself, never Tove, and bumps nobody. Otherwise the private volume
      would be the one that carries furthest.

  (b3) AND THE ANSWER TRAVELS BACK THE WAY THE QUESTION CAME.
      Half a round trip is no round trip: if the reply from the gate does not
      reach the avatar behind the wall, the player sees their line go out and
      nothing come back. Tove (12, 0), location-less, answers the avatar (0, 0)
      inside the inn — 12.0 m <= 20, so the ADDRESSED line arrives regardless of
      the wall, with kind ``addressed`` (not ``nearby``: it crossed a wall, and
      the kind says why it was heard). Mira gets nothing — she is not addressed,
      and an unaddressed line from outside does not reach into a room.
      Checked at the CONSUMER as well, not only in the perceptions table: the
      line shows up in ``get_character_room_stream(avatar, INN, "taproom")``,
      which is what ``/play/scene`` renders. Without that arm the row exists and
      the player still sees nothing.
      Two counter-probes keep the rule narrow: the SAME speaker at the SAME spot
      saying something UNADDRESSED reaches nobody but itself (the E6 wall rule
      that ``smoke_earshot`` [1] pins is untouched), and an addressed WHISPER
      does not cross the wall either.

  (c) A WANDERER DOES NOT LEAVE MID-SENTENCE.
      ``_settle_wanderer`` runs on every wanderer tick and ends the arrival
      immediately — 50 % turn around, otherwise into the pool. Cass has
      ARRIVED at MARKET (target MARKET, standing there, no journey) and its
      origin is the INN, and ``random.random`` is pinned to 0.1 < 0.5, so the
      turn-around branch would fire.
      THE IN-CHAT STATE IS PRODUCED THE WAY ``/play`` PRODUCES IT: one recorded
      utterance from the avatar to the NPC, NOT a hand-written
      ``chat_messages`` row. Room mode writes no chat rows at all (``chat_engine``
      skips every ``save_message`` when ``room_mode`` is set, and every respond
      turn is room mode), so a fixture that writes one would prove the guard on
      a path the player never takes. The avatar therefore stands at (100, 0),
      i.e. in MARKET's ground room next to Cass and Bede, and speaks.
      The window is the AgentLoop's own: ``_IN_CHAT_HOT_MIN`` = 10 minutes of
      SYSTEM time (the technical clock ``_minutes_since_last_chat_with_avatar``
      measures against, not game time). Inside it the tick has to answer False
      and leave every field alone: wander_target stays MARKET, wander_origin
      stays the INN, no journey, status still ''. Stamping the utterance 20
      minutes back puts Cass outside the window, and the tick then does exactly
      what it did before this task: target ↔ origin swap to INN/MARKET and a
      fresh journey to the INN.
      The TTL sweep gets the same guard: Bede is expired ("Y0001-D001T00:00:00"
      against a game clock pinned to Y0002-D100T12:00:00) and mid-conversation
      → ``sweep_expired_npcs()`` returns 0 and Bede is still alive; 20 minutes
      later the very same call returns 1 and pools it. Cass carries NO stamp
      at all, so it is invisible to both sweeps and cannot make the count lie.
      The OTHER source is proven too: with the stream emptied, a single
      ``chat_messages`` row (what DM/phone/TalkTo/Telegram still write) is
      enough to hold Bede back — the perception stream is the new primary
      source, not a replacement.

  (d) AN ADDRESSED WANDERER STOPS WALKING.
      Kestrel stands at (40, 0) — between the two squares, so location-less —
      and is sent to MARKET the ordinary way (``_send_wanderer`` →
      ``start_journey``), which stamps a ``journey`` and ``movement_target``
      MARKET. The avatar stands at (45, 0): 5.0 m ≤ 20, so the open-world
      dispatch reaches it. Addressing Kestrel bumps the obligatory answer AND
      cancels the journey — journey gone, ``movement_target`` back to "" —
      while ``wander_target`` MARKET survives on the profile, because the road
      is not cancelled, only the walking. Two counter-probes, both needed to
      prove the hook reads the flag and not the situation: an ordinary
      temporary NPC (Fenna, same road, no ``npc_wanderer``) addressed exactly
      the same way KEEPS its journey, and a wanderer merely OVERHEARING the
      line (not addressed → chime) keeps its journey too.
      Afterwards the retry path picks the road back up: with a fresh utterance
      from the avatar ``_settle_wanderer`` refuses (still no journey), and once
      that line is 20 minutes old the same call starts a NEW journey to the OLD
      target MARKET.

  (e) A SLOT WITHOUT A ROOM LANDS IN THE ARRIVAL ROOM, NOT NOWHERE.
      ``spawn_for_slot`` used to hand ``room = slot.get("room") or ""`` to the
      placement, and ``place_npc`` writes no room for "" — which is how a temp
      NPC ended up standing "in" a location but in none of its rooms, invisible
      to every room-based gate. The rule is now the ONE arrival rule,
      ``world.get_arrival_room_id``: the declared entry room, else the ground.
        Perrin, slot "cook" at the INN,   no room in the slot → "taproom"
        Dell,   slot "porter" at MARKET,  no room in the slot → "__ground__"
        Elga,   slot "guard" at the INN,  slot room "cellar"  → "cellar"
      All three come out of the pool (their sheets are pooled with the matching
      ``npc_slot_role``), so not one LLM turn runs.

Usage:  ./.venv/bin/python scripts/smoke_npc_addressable.py
"""
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcaddr-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcaddr-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()
from app.core.task_queue import get_task_queue  # noqa: E402
get_task_queue()._started = True

from app.core import (npc_actions, npc_ops, npc_spawn,  # noqa: E402
                      perception, travel_engine)
from app.core.agent_loop import AgentLoop  # noqa: E402
from app.core.character_ops import build_characters_at_location  # noqa: E402
from app.core.game_time import GameTime  # noqa: E402
from app.core.npc_ops import apply_npc, sweep_expired_npcs  # noqa: E402
from app.core.npc_pool import pool_npc  # noqa: E402
from app.core.perception import addressable_for  # noqa: E402
from app.core.timeutils import (set_game_factor, set_game_time,  # noqa: E402
                                utc_now)
from app.models import perception_store, terrain  # noqa: E402
from app.core.auth_dependency import current_user_ctx  # noqa: E402
from app.core.users import (create_user, get_user_by_id,  # noqa: E402
                            update_user)
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_current_room,
    get_character_profile, get_character_status, get_movement_target,
    save_character_profile, set_character_pos)
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location,
    get_location_by_id, update_location_position)
from app.routes.play import _present_characters, play_scene  # noqa: E402

FAILURES = []
CHECKED = 0

# The pinned instant. Everything game-timed is measured from here; the factor
# is 0 so no journey ever advances on its own during the run.
T0 = "Y0002-D100T12:00:00"
PAST = "Y0001-D001T00:00:00"


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'✓' if ok else '✗'} {label}" + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


# ── the world ───────────────────────────────────────────────────────────────

def patch_location(location_id: str, **fields) -> None:
    """Merge top-level fields into a stored location (rooms, entry_room, …)."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc.update(fields)
    _save_world_data(data)


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob (boundary, openings).

    A ``plan_width_m`` handed in is DRAWN as the centred square of that edge —
    since 2026-08-19 the width alone is no shape at all, so a fixture that
    wants ground has to say so (copied from ``smoke_journey_v2``).
    """
    width = fields.get("plan_width_m")
    if width:
        _h = round(float(width) / 2.0, 2)
        fields.setdefault("boundary", [[-_h, -_h], [_h, -_h],
                                       [_h, _h], [-_h, _h]])
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d.update(fields)
            loc["map3d"] = map3d
    _save_world_data(data)


terrain.save_area({"kind": "grass", "z_order": 0,
                   "polygon": [[-60, -60], [300, -60], [300, 300], [-60, 300]]})

INN = add_location("Crossroads Inn", "A stone house at the fork.")["id"]
update_location_position(INN, 0.0, 0.0)
set_map3d(INN, plan_width_m=10.0,
          boundary_openings=[{"edge": 2, "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
patch_location(INN,
               rooms=[{"id": "taproom", "name": "Taproom",
                       "description": "Benches."},
                      {"id": "cellar", "name": "Cellar",
                       "description": "Barrels."}],
               entry_room="taproom")

MARKET = add_location("Market Square", "Stalls and shouting.")["id"]
update_location_position(MARKET, 100.0, 0.0)
set_map3d(MARKET, plan_width_m=10.0,
          boundary_openings=[{"edge": 3, "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
patch_location(MARKET,
               rooms=[{"id": "hall", "name": "Hall",
                       "description": "A roofed stall row."}])

set_game_factor(0.0)
set_game_time(GameTime.parse(T0))
config._CONFIG.setdefault("game", {})["travel_speed_m_s"] = 3.0
config._CONFIG.setdefault("npc", {})["require_assets"] = False

AVATAR = "Wren"
save_character_profile(AVATAR, {"character_name": AVATAR,
                                "template": "human-roleplay"},
                       create_new=True)
_uid = create_user("demo", "smoke-password", allowed_characters=[AVATAR])
update_user(_uid, settings={"active_character": AVATAR})
# ``/play/scene`` asks ``get_active_character()``, which reads the logged-in
# user out of the request context var the auth middleware fills. There is no
# request here, so the smoke fills it once — the same dict the middleware would
# put there. Without it the route answers its empty payload and every check
# below would pass against nothing.
current_user_ctx.set(get_user_by_id(_uid))


def make_npc(name: str, *, location_id: str = "", room_id: str = "",
             wanderer: bool = False, wander_target: str = "") -> str:
    """One temporary NPC through the real apply path, the finish gate off."""
    apply_npc({"character_name": name,
               "character_appearance": "a weathered traveller",
               "face_appearance": "a broad face, grey stubble",
               "outfit_description": "a grey linen coat",
               "standing_task": "watching the road"},
              location_id, room_id=room_id, template="npc-temporary",
              created_by="smoke_npc_addressable", wanderer=wanderer,
              wander_target=wander_target)
    return name


def patch_profile(name: str, **fields) -> None:
    profile = get_character_profile(name) or {}
    profile.update(fields)
    save_character_profile(name, profile)


def sys_stamp(minutes_ago: float) -> str:
    """A SYSTEM-time ISO stamp N minutes back — the clock the HOT window is
    measured against (a technical "how long ago", not an in-world duration)."""
    return (utc_now() - timedelta(minutes=minutes_ago)).isoformat()


def player_says(npc: str, minutes_ago: float = 0.0) -> None:
    """What ``/play/say`` leaves behind: ONE recorded utterance from the avatar
    to the NPC. NOT a ``chat_messages`` row — room mode writes none (see
    ``chat_engine`` skipping ``save_message`` when ``room_mode`` is set), which
    is exactly why the in-chat rule has to read the perception stream."""
    perception.record_utterance(speaker=AVATAR, content="Wait a moment!",
                                addressees=[npc], source="play",
                                ts=sys_stamp(minutes_ago))


def dm_row(character: str, partner: str, minutes_ago: float) -> None:
    """One ``chat_messages`` row — the DM/phone/TalkTo/Telegram half of the
    in-chat rule, which still writes that table."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO chat_messages (character_name, partner, ts, role, "
            "content, channel) VALUES (?, ?, ?, 'user', 'Wait!', 'web')",
            (character, partner, sys_stamp(minutes_ago)))


def clear_chat() -> None:
    """Both sources of the in-chat rule, emptied."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM chat_messages")
        conn.execute("DELETE FROM perceptions")
        conn.execute("DELETE FROM utterances")


def perceivers_of(utterance_id) -> list:
    """Who got a perception row for this speech act — the fan-out, read at the
    consumer (the table), not at the earshot computation."""
    return [n for n, _k in kinds_of(utterance_id)]


def kinds_of(utterance_id) -> list:
    """``[(perceiver, kind), …]`` of one speech act."""
    rows = db.get_connection().execute(
        "SELECT perceiver, kind FROM perceptions WHERE utterance_id=?",
        (utterance_id,)).fetchall()
    return [(r[0], r[1]) for r in rows]


# ── (a) out in the open the radius is the rule ──────────────────────────────
print("(a) avatar in the open: 10 m is addressable, 200 m is not")
make_npc("Roon")
make_npc("Baldric")
set_character_pos("Roon", 10.0, 200.0)
set_character_pos("Baldric", 200.0, 200.0)
set_character_pos(AVATAR, 0.0, 200.0)
check("the avatar stands nowhere in particular",
      get_character_current_location(AVATAR), "")
check("only the neighbour 10 m away", addressable_for(AVATAR), ["Roon"])
check("and the panel roster says the same", _present_characters(AVATAR),
      ["Roon"])
check("/play/scene agrees out here as it always did",
      play_scene()["present"], ["Roon"])

# ── (b) inside a location: room list PLUS earshot ───────────────────────────
print("(b) avatar in the taproom: the room and whoever stands outside the gate")
make_npc("Mira", location_id=INN, room_id="taproom")
make_npc("Osric", location_id=INN, room_id="cellar")
make_npc("Tove")
set_character_pos("Tove", 12.0, 0.0)
set_character_pos(AVATAR, 0.0, 0.0)
check("the avatar is in the inn", get_character_current_location(AVATAR), INN)
check("in its entry room", get_character_current_room(AVATAR), "taproom")
check("Tove stands outside every wall",
      get_character_current_location("Tove"), "")
check("room mate + the one outside the gate",
      sorted(addressable_for(AVATAR)), ["Mira", "Tove"])
check("the panel roster is the same list",
      sorted(_present_characters(AVATAR)), ["Mira", "Tove"])
_at_loc = build_characters_at_location(INN)
check("the location query lists the same people plus the avatar",
      sorted(c["name"] for c in _at_loc["characters"]),
      ["Mira", "Osric", "Tove", "Wren"])
check("the one outside the gate is flagged as not in the room",
      [(c["same_room"], c["room"]) for c in _at_loc["characters"]
       if c["name"] == "Tove"], [(False, "")])
check("the room mate is in the room",
      [c["same_room"] for c in _at_loc["characters"] if c["name"] == "Mira"],
      [True])
_scene = play_scene()
check("/play/scene — the roster the addressee chips are built from",
      sorted(_scene["present"]), ["Mira", "Tove"])
check("and every chip has its portrait row",
      sorted(p["name"] for p in _scene["present_detail"]), ["Mira", "Tove"])
check("the scene still knows where the avatar itself stands",
      (_scene["location_id"], _scene["room_id"]), (INN, "taproom"))

# ── (b2) the same union all the way through: gate → fan-out → dispatch ──────
print("(b2) the line the avatar speaks in the taproom REACHES the gate")
_uid = perception.record_utterance(speaker=AVATAR, content="Come in, Tove!",
                                   addressees=["Tove"])
check("the room and the one outside the gate perceived it, nobody else",
      sorted(perceivers_of(_uid)), ["Mira", "Tove", "Wren"])
_loop = AgentLoop()
_res = _loop.dispatch_room_reactions(speaker=AVATAR, content="Come in, Tove!",
                                     volume="normal", location_id=INN,
                                     room_id="taproom", addressees=["Tove"],
                                     is_avatar=True)
check("the addressee at the gate is bumped for a mandatory answer",
      _res["obligatory"], ["Tove"])
check("and the room mate may chime in", _res["chime"], ["Mira"])

_uid = perception.record_utterance(speaker=AVATAR, content="psst",
                                   addressees=["Tove"], volume="whisper")
check("a whisper stays inside the walls — the gate hears nothing",
      sorted(perceivers_of(_uid)), ["Mira", "Wren"])
_res = _loop.dispatch_room_reactions(speaker=AVATAR, content="psst",
                                     volume="whisper", location_id=INN,
                                     room_id="taproom", addressees=["Tove"],
                                     is_avatar=True)
check("and nobody out there is bumped for it", _res,
      {"obligatory": [], "chime": []})

# ── (b3) THE ANSWER TRAVELS BACK THE WAY THE QUESTION CAME ──────────────────
print("(b3) the reply from the gate reaches the avatar behind the wall")
clear_chat()
_uid = perception.record_utterance(speaker="Tove", content="I am coming!",
                                   addressees=[AVATAR])
check("the avatar behind the wall perceives the addressed reply",
      sorted(perceivers_of(_uid)), ["Tove", "Wren"])
check("and it is marked as heard BECAUSE it was addressed",
      [k for n, k in kinds_of(_uid) if n == AVATAR], ["addressed"])
check("it also shows in the avatar's scene view, where /play reads it",
      [r["content"] for r in perception_store.get_character_room_stream(
          AVATAR, INN, "taproom", 20)], ["I am coming!"])
_uid = perception.record_utterance(speaker="Tove", content="what a night")
check("an UNADDRESSED line from the same spot does not cross the wall (E6)",
      sorted(perceivers_of(_uid)), ["Tove"])
_uid = perception.record_utterance(speaker="Tove", content="secret",
                                   addressees=[AVATAR], volume="whisper")
check("and an addressed WHISPER does not cross it either",
      sorted(perceivers_of(_uid)), ["Tove"])
clear_chat()

# ── (c) the arrival tick and the TTL sweep leave a conversation alone ───────
print("(c) a wanderer mid-conversation is neither turned around nor pooled")
make_npc("Cass", wanderer=True, wander_target=MARKET)
set_character_pos("Cass", 100.0, 0.0)
patch_profile("Cass", wander_origin=INN, wander_target=MARKET, expires_at="")
make_npc("Bede", wanderer=True, wander_target=MARKET)
set_character_pos("Bede", 100.0, 0.0)
patch_profile("Bede", wander_origin="", wander_target=MARKET, expires_at=PAST)
set_character_pos(AVATAR, 100.0, 0.0)
check("Cass has arrived at the market",
      get_character_current_location("Cass"), MARKET)
check("and the avatar is standing there with it",
      (get_character_current_location(AVATAR),
       get_character_current_room(AVATAR)), (MARKET, GROUND_ROOM_ID))
check("Bede's stamp is in the past",
      npc_ops.is_expired(get_character_profile("Bede")["expires_at"]), True)

_real_random = npc_spawn.random.random
npc_spawn.random.random = lambda: 0.1     # < 0.5 → the turn-around branch

player_says("Cass", 0.0)
check("the perception stream alone makes it 'in chat'",
      npc_actions._in_chat("Cass"), True)
check("the arrival tick stands down", npc_spawn._settle_wanderer("Cass"), False)
check("the road is untouched",
      (get_character_profile("Cass").get("wander_target"),
       get_character_profile("Cass").get("wander_origin")), (MARKET, INN))
check("and nobody set off", get_character_profile("Cass").get("journey"), None)
check("Cass is still standing there", get_character_status("Cass"), "")
check("the TTL sweep pools nobody", sweep_expired_npcs(), 0)
check("Bede is still alive", get_character_status("Bede"), "")

# The OTHER source still counts: DM/phone/TalkTo/Telegram write chat_messages,
# and nothing else does since room mode stopped calling save_message.
clear_chat()
dm_row("Bede", AVATAR, 0.0)
check("a DM row alone is 'in chat' too", npc_actions._in_chat("Bede"), True)
check("so the TTL sweep still leaves Bede", sweep_expired_npcs(), 0)
check("Bede is alive after the DM probe", get_character_status("Bede"), "")

clear_chat()
player_says("Cass", 20.0)
check("20 minutes later the tick turns Cass around",
      npc_spawn._settle_wanderer("Cass"), True)
check("target and origin have swapped",
      (get_character_profile("Cass").get("wander_target"),
       get_character_profile("Cass").get("wander_origin")), (INN, MARKET))
check("and Cass is walking to the inn",
      (get_character_profile("Cass").get("journey") or {}).get("target"), INN)
check("the TTL sweep now takes Bede", sweep_expired_npcs(), 1)
check("Bede is pooled", get_character_status("Bede"), "pooled")

npc_spawn.random.random = _real_random
clear_chat()

# ── (d) an addressed wanderer stops ─────────────────────────────────────────
print("(d) the addressed wanderer stops, keeps its road, and picks it up later")
make_npc("Kestrel", wanderer=True, wander_target=MARKET)
set_character_pos("Kestrel", 40.0, 0.0)
patch_profile("Kestrel", wander_origin=INN, wander_target=MARKET,
              expires_at="")
make_npc("Fenna")
set_character_pos("Fenna", 41.0, 0.0)
make_npc("Gwyn", wanderer=True, wander_target=MARKET)
set_character_pos("Gwyn", 42.0, 0.0)
patch_profile("Gwyn", wander_origin=INN, wander_target=MARKET, expires_at="")
set_character_pos(AVATAR, 45.0, 0.0)
check("the avatar is out on the road too",
      get_character_current_location(AVATAR), "")

check_true("Kestrel sets off", npc_spawn._send_wanderer("Kestrel", MARKET))
check_true("Gwyn sets off", npc_spawn._send_wanderer("Gwyn", MARKET))
travel_engine.start_journey_to_point("Fenna", 90.0, 0.0)
check("Kestrel is on the road", get_movement_target("Kestrel"), MARKET)
check_true("Fenna is on the road too",
           isinstance(get_character_profile("Fenna").get("journey"), dict))

loop = AgentLoop()
res = loop.dispatch_room_reactions(speaker=AVATAR, content="Wait a moment!",
                                   volume="normal", location_id="", room_id="",
                                   addressees=["Kestrel", "Fenna"],
                                   is_avatar=True)
check("both addressees must answer", sorted(res["obligatory"]),
      ["Fenna", "Kestrel"])
check("the wanderer's journey is gone",
      get_character_profile("Kestrel").get("journey"), None)
check("its travel target with it", get_movement_target("Kestrel"), "")
check("but the road it was on stays on the profile",
      (get_character_profile("Kestrel").get("wander_target"),
       get_character_profile("Kestrel").get("npc_wanderer")), (MARKET, True))
check_true("the ordinary NPC keeps walking",
           isinstance(get_character_profile("Fenna").get("journey"), dict))
check_true("the wanderer that only overheard keeps walking",
           isinstance(get_character_profile("Gwyn").get("journey"), dict))
check("Gwyn was a chime, not an addressee", res["chime"], ["Gwyn"])

player_says("Kestrel", 0.0)
check("mid-conversation the tick does not send it off again",
      npc_spawn._settle_wanderer("Kestrel"), False)
check("still standing", get_character_profile("Kestrel").get("journey"), None)
clear_chat()
player_says("Kestrel", 20.0)
check("20 minutes later it walks on", npc_spawn._settle_wanderer("Kestrel"),
      False)
check("towards the very target it had",
      (get_character_profile("Kestrel").get("journey") or {}).get("target"),
      MARKET)
clear_chat()

# ── (e) a slot without a room lands in the arrival room ─────────────────────
print("(e) a slot without a room puts the NPC in the location's arrival room")


def pooled_sheet(name: str, role: str) -> str:
    make_npc(name)
    patch_profile(name, npc_slot_role=role)
    pool_npc(name, reason="smoke fixture")
    return name


pooled_sheet("Perrin", "cook")
pooled_sheet("Dell", "porter")
pooled_sheet("Elga", "guard")

_inn = get_location_by_id(INN)
_market = get_location_by_id(MARKET)
check("the cook comes back out of the pool",
      npc_spawn.spawn_for_slot(_inn, npc_spawn.normalize_slot({"role": "cook"})),
      "Perrin")
check("and stands in the inn's entry room",
      (get_character_current_location("Perrin"),
       get_character_current_room("Perrin")), (INN, "taproom"))
check("the porter comes back too",
      npc_spawn.spawn_for_slot(_market,
                               npc_spawn.normalize_slot({"role": "porter"})),
      "Dell")
check("and stands on the market's ground, not nowhere",
      (get_character_current_location("Dell"),
       get_character_current_room("Dell")), (MARKET, GROUND_ROOM_ID))
check("the guard comes back as well",
      npc_spawn.spawn_for_slot(_inn, npc_spawn.normalize_slot(
          {"role": "guard", "room": "cellar"})), "Elga")
check("an authored room still wins",
      (get_character_current_location("Elga"),
       get_character_current_room("Elga")), (INN, "cellar"))


# ── verdict ────────────────────────────────────────────────────────────────
print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks")
