#!/usr/bin/env python3
"""Smoke run: a journey ARRIVES in the room it was asked for.

Runs against a THROWAWAY storage directory — never touches a real world.

The bug this pins (2026-09-28): ``SetLocation "Cafe, Hauptraum"`` from another
location started a journey that only carried the LOCATION; the room (and the
pose) were dropped on the floor, and the arrival fell back to the arrival rule
— with no ``entry_room`` declared, that is the ground. Every NPC walked to the
right place and then stood outside it ("sits outside the café"), because the
character believes it has arrived and never asks for the room again.

Rules every expectation below is derived from BY HAND:

  * ``journey_state`` is a pure function of the GAME clock, pinned here
    (``set_game_factor(0.0)`` + ``set_game_time``). The goal window reads the
    clock FACTOR, which is injected as 1.0 (same trick as
    ``smoke_travel_ticker.py``).
  * The hand-written route (1 m per game second):
        W0 [60, 0, 0]  → W1 [95, 0, 35]
    CAFE sits at (100, 0) with edge 10 → footprint x ∈ [95, 105],
    z ∈ [−5, 5]; its only opening is the W edge at 0.5 → (95, 0), WITHOUT a
    room link, and CAFE declares no ``entry_room`` — so the arrival rule
    (``get_arrival_room_id``) answers the ground, ``__ground__``.
    Arrival = t = 35 (the last waypoint's t_cum).
  * The requested room outranks the arrival rule when — and only when — its
    own access check passes. Refused, the character still enters the
    location (the location itself is open) and lands where the arrival rule
    says, with an ``access_denied`` diary entry naming the room.

Hand-derived expectations:

  [1] ``start_journey(name, CAFE, target_room=HAUPTRAUM, target_pose="sitting")``
      stores both on the journey dict; without them neither key is written.
  [2] Baseline, no target room: arrival room ``__ground__`` (unchanged).
  [3] ``target_room`` HAUPTRAUM → current_location CAFE, current_room
      HAUPTRAUM, journey and movement_target gone.
  [4] ``target_room`` BACK with a block rule (enter, scope room, BACK only)
      → location CAFE, room ``__ground__`` (the arrival rule), NOT blocked at
      the door, and an ``access_denied`` entry whose location label names
      "Back".
  [5] ``target_room`` that is no room of CAFE (a stale id) → ``__ground__``.
  [6] ``target_pose`` "sitting" → pose key ``sitting`` after arrival (the
      arrival clears the old pose first, then applies the carried one).
  [7] The SKILL: ``SetLocation "Smoke Cafe, Hauptraum"`` from HOME starts a
      journey that carries HAUPTRAUM; ``"Smoke Cafe, Back"`` under the block
      rule refuses BEFORE setting off (no journey, no movement target) —
      exactly like the same-location room change refuses.

Usage:  ./.venv/bin/python scripts/smoke_journey_target_room.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="journey-room-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="journey-room-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import travel_engine  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_current_room,
    get_character_pose_key, get_character_profile, get_movement_target,
    save_character_current_location, save_character_profile,
    set_character_pos, set_known_locations)
from app.models.rules import add_rule  # noqa: E402
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location, add_room,
    update_location_position)
from app.plugins.context import PluginContext  # noqa: E402

FAILURES = []
CHECKED = 0

START = "Y0001-D001T12:00:00"
START_GT = GameTime.parse(START)
ROUTE = [[60.0, 0.0, 0.0], [95.0, 0.0, 35.0]]


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


def set_map3d(location_id: str, **fields) -> None:
    """Merge fields into a location's map3d blob; a ``plan_width_m`` is drawn
    as the centred square of that edge (see smoke_travel_ticker.py)."""
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


def new_npc(name, location="", x=None, z=None):
    save_character_profile(name, {"current_location": ""}, create_new=True)
    if location:
        save_character_current_location(name, location)
    if x is not None:
        set_character_pos(name, x, z)
    set_known_locations(name, [HOME, CAFE])


def give_journey(name, **extra):
    """Hand-written journey — the ticker's INPUT, independent of routing."""
    prof = get_character_profile(name)
    prof["movement_target"] = CAFE
    prof["journey"] = {"target": CAFE, "waypoints": [list(w) for w in ROUTE],
                       "started_at_game": START, "speed_m_s": 1.0,
                       "entry_edge": 3, **extra}
    save_character_profile(name, prof)


def tick_at(seconds):
    set_game_time(START_GT + GameDuration.of(seconds=seconds))
    travel_engine.advance_all_journeys()


def denials(name):
    rows = db.get_connection().execute(
        "SELECT state_json FROM state_history WHERE character_name=? "
        "ORDER BY id DESC LIMIT 20", (name,)).fetchall()
    out = []
    for (raw,) in rows:
        st = json.loads(raw or "{}")
        if st.get("type") == "access_denied":
            out.append(st)
    return out


# ── the world ───────────────────────────────────────────────────────────
HOME = add_location(name="Smoke Home", description="journey room smoke")["id"]
update_location_position(HOME, 0.0, 0.0)
set_map3d(HOME, plan_width_m=10.0,
          boundary_openings=[{"edge": 1, "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])
CAFE = add_location(name="Smoke Cafe", description="journey room smoke")["id"]
update_location_position(CAFE, 100.0, 0.0)
HAUPTRAUM = add_room(CAFE, "Hauptraum", "the guest room")["id"]
BACK = add_room(CAFE, "Back", "staff only")["id"]
set_map3d(CAFE, plan_width_m=10.0,
          boundary_openings=[{"edge": 3, "at": 0.5, "width_m": 4.0,
                              "type": "passage"}])

set_game_factor(0.0)
set_game_time(START_GT)
travel_engine.game_speed_factor = lambda: 1.0

# ── [1] start_journey carries room + pose ───────────────────────────────
print("[1] start_journey stores target_room / target_pose")
new_npc("carry_npc", HOME, 0.0, 0.0)
j, reason = travel_engine.start_journey("carry_npc", CAFE,
                                        target_room=HAUPTRAUM,
                                        target_pose="sitting")
check("journey started", reason, "")
check("target_room stored", (j or {}).get("target_room"), HAUPTRAUM)
check("target_pose stored", (j or {}).get("target_pose"), "sitting")
travel_engine.cancel_journey("carry_npc")
new_npc("plain_npc", HOME, 0.0, 0.0)
j, _ = travel_engine.start_journey("plain_npc", CAFE)
check("no target_room key without one", "target_room" in (j or {}), False)
check("no target_pose key without one", "target_pose" in (j or {}), False)
travel_engine.cancel_journey("plain_npc")

# ── [2] baseline: the arrival rule ──────────────────────────────────────
print("[2] no target room → the ground")
new_npc("base_npc", "", 60.0, 0.0)
give_journey("base_npc")
tick_at(35)
check("location", get_character_current_location("base_npc"), CAFE)
check("room", get_character_current_room("base_npc"), GROUND_ROOM_ID)

# ── [3] the requested room wins ─────────────────────────────────────────
print("[3] target_room HAUPTRAUM → arrives in Hauptraum")
set_game_time(START_GT)
new_npc("room_npc", "", 60.0, 0.0)
give_journey("room_npc", target_room=HAUPTRAUM)
tick_at(35)
check("location", get_character_current_location("room_npc"), CAFE)
check("room", get_character_current_room("room_npc"), HAUPTRAUM)
check("journey gone", travel_engine.get_journey("room_npc"), None)
check("movement_target gone", get_movement_target("room_npc"), "")

# ── [4] a refused room falls back to the arrival rule ───────────────────
print("[4] target_room BACK under a room block → ground, not blocked")
RULE = add_rule({"name": "staff only", "type": "block", "action": "enter",
                 "target": {"scope": "room", "location_id": CAFE,
                            "room_ids": [BACK]},
                 "condition": "always", "message": "Staff only."})
set_game_time(START_GT)
new_npc("back_npc", "", 60.0, 0.0)
give_journey("back_npc", target_room=BACK)
tick_at(35)
check("location (the place itself is open)",
      get_character_current_location("back_npc"), CAFE)
check("room = arrival rule", get_character_current_room("back_npc"),
      GROUND_ROOM_ID)
d = denials("back_npc")
check_true("an access_denied entry names the room",
           any("Back" in json.dumps(x, ensure_ascii=False) for x in d),
           json.dumps(d, ensure_ascii=False)[:200])

# ── [5] a stale room id ─────────────────────────────────────────────────
print("[5] target_room not a room of the target → ground")
set_game_time(START_GT)
new_npc("stale_npc", "", 60.0, 0.0)
give_journey("stale_npc", target_room="deadbeef")
tick_at(35)
check("room", get_character_current_room("stale_npc"), GROUND_ROOM_ID)

# ── [6] the carried pose ────────────────────────────────────────────────
print("[6] target_pose applied on arrival")
set_game_time(START_GT)
new_npc("pose_npc", "", 60.0, 0.0)
give_journey("pose_npc", target_room=HAUPTRAUM, target_pose="sitting")
tick_at(35)
check("room", get_character_current_room("pose_npc"), HAUPTRAUM)
check("pose key", get_character_pose_key("pose_npc"), "sitting")

# ── [7] the skill hands the room to the journey ─────────────────────────
print("[7] SetLocation across locations with a room")
from plugins.movement.skill_set_location import SetLocationSkill  # noqa: E402
skill = SetLocationSkill({"enabled": True}, PluginContext("movement"))
set_game_time(START_GT)
new_npc("skill_npc", HOME, 0.0, 0.0)
answer = skill.execute(json.dumps({"input": "Smoke Cafe, Hauptraum",
                                   "agent_name": "skill_npc"}))
j = travel_engine.get_journey("skill_npc")
check_true("a journey exists", j is not None, answer)
check("journey carries the room", (j or {}).get("target_room"), HAUPTRAUM)
travel_engine.cancel_journey("skill_npc")

new_npc("skill_back_npc", HOME, 0.0, 0.0)
answer = skill.execute(json.dumps({"input": "Smoke Cafe, Back",
                                   "agent_name": "skill_back_npc"}))
check("refused before setting off: no journey",
      travel_engine.get_journey("skill_back_npc"), None)
check("no movement target", get_movement_target("skill_back_npc"), "")
check_true("the answer is the rule's message", "Staff only" in answer, answer)

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks")
