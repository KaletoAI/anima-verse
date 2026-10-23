#!/usr/bin/env python3
"""Force destinations walk before applying flags.

Usage: ./.venv/bin/python scripts/smoke_stat_force_journey.py

Hand-derived expectations: two places 100 metres apart on open ground require
one journey, zero location jumps and zero sleeping flags before arrival. A
second tick must retain that journey and its single diary entry. Arrival sets
sleep and the home room. Missing/unplaced/unreachable homes and confinement
set sleep at the origin, so later ticks cannot restart the failed trip.
A follower leaves its party before walking independently. Offmap and players
retain their existing semantics. All storage is temporary; no server needed.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory(prefix="force-journey-")
root = Path(_tmp.name)
os.environ["STORAGE_DIR"] = str(root)
os.environ["INSTANCE_DIR"] = str(root)
from app.core import paths
paths.init(root)
from app.core import config, db
(root / "config.json").write_text('{"packages":{"enabled":"movement,party,sleep"}}')
config.load(root / "config.json")
db.init_schema()
from app.core import travel_engine, party_engine
from app.core.periodic_jobs import _sub_force_rules
from app.core.game_time import GameTime, GameDuration
from app.core.timeutils import set_game_factor, set_game_time
from app.models import character as ch, rules, terrain
from app.models.world import add_location, update_location_position, _load_world_data, _save_world_data, add_room
from app.core.db import get_connection

set_game_factor(0)
start = GameTime.parse("Y0001-D001T12:00:00")
set_game_time(start)
a = add_location(name="Origin", description="fixture")["id"]
b = add_location(name="Home", description="fixture")["id"]
isle = add_location(name="Island", description="fixture")["id"]
unplaced = add_location(name="Unplaced", description="fixture")["id"]
bedroom = add_room(b, "Bedroom", sync_world=False)["id"]
for loc, x, z in [(a, 0, 0), (b, 100, 0), (isle, 0, 200)]:
    update_location_position(loc, x, z)
data = _load_world_data()
for loc in data["locations"]:
    loc["map3d"] = {"boundary": [[-5,-5],[-5,5],[5,5],[5,-5]],
                    "boundary_openings": [{"edge": i, "at": .5, "width_m": 4,
                                           "type": "passage"} for i in range(4)]}
_save_world_data(data)
terrain.save_area({"kind": "deep_water", "polygon": [[-40,160],[40,160],[40,240],[-40,240]], "z_order": 0})
force = {"id": "home", "name": "Go home", "type": "force", "condition": "always",
         "force_action": {"go_to": "home", "set_flags": {"is_sleeping": True}}}
_disabled_shared = [{"id": r["id"], "type": "info"} for r in rules.load_rules()]


def save_test_rules(entries):
    rules.save_rules(_disabled_shared + entries)


save_test_rules([force])

def npc(name, home=b, loc=a, room=""):
    ch.save_character_profile(name, {"current_location": "", "is_sleeping": False}, create_new=True)
    if loc:
        ch.save_character_current_location(name, loc)
        ch.set_character_pos(name, 100 if loc == b else 0, 0)
    ch.set_known_locations(name, [a,b,isle,unplaced])
    ch.save_character_config(name, {**ch.get_character_config(name), "home_location": home, "home_room": room})

def sleeping(name):
    return bool(ch.get_character_profile(name).get("is_sleeping"))

def diary(name):
    rows = get_connection().execute("SELECT state_json FROM state_history WHERE character_name=?", (name,)).fetchall()
    return [json.loads(r[0]) for r in rows if json.loads(r[0]).get("type") == "forced_action"]

def check(label, condition):
    assert condition, label
    print("PASS", label)

npc("walker", room=bedroom)
_sub_force_rules()
j = travel_engine.get_journey("walker")
check("reachable home starts a journey without teleport or sleep", j is not None and ch.get_character_current_location("walker") == a and not sleeping("walker"))
check("home room travels with journey", j.get("target_room") == bedroom)
check("journey start has a forced action diary entry", len(diary("walker")) == 1 and "journey to" in diary("walker")[0].get("value", ""))
_sub_force_rules()
check("second tick retains journey and single diary entry", travel_engine.get_journey("walker") == j and len(diary("walker")) == 1 and not sleeping("walker"))
set_game_time(start + GameDuration.of(seconds=10000))
travel_engine.advance_all_journeys()
_sub_force_rules()
check("arrival sleeps in home room", ch.get_character_current_location("walker") == b and ch.get_character_current_room("walker") == bedroom and sleeping("walker"))
for name, home in [("unknown", "missing"), ("unplaced", unplaced), ("unreachable", isle)]:
    npc(name, home, room=bedroom)
    _sub_force_rules()
    check(name + " sleeps in place", sleeping(name) and ch.get_character_current_location(name) == a and travel_engine.get_journey(name) is None)
    _sub_force_rules()
    check(name + " does not loop", len(diary(name)) == 1)
    check(name + " keeps its origin room", ch.get_character_current_room(name) != bedroom)
npc("confined", room=bedroom)
save_test_rules([force, {"id": "pin", "type": "block", "action": "leave", "character": "confined", "target": {"scope": "location", "location_id": a}}])
_sub_force_rules()
check("confined sleeps in place", sleeping("confined") and ch.get_character_current_location("confined") == a and travel_engine.get_journey("confined") is None)
check("confinement keeps the origin room", ch.get_character_current_room("confined") != bedroom)
save_test_rules([force])
npc("leader", home=a)
npc("follower")
check("party fixture", bool(party_engine.add_to_party("leader", "follower")))
_sub_force_rules()
check("follower leaves party before journey", party_engine.get_party_of("follower") is None and travel_engine.get_journey("follower") is not None and not sleeping("follower"))
npc("at_home", home=a)
_sub_force_rules()
check("already home sleeps without journey", sleeping("at_home") and travel_engine.get_journey("at_home") is None)
npc("offmap", home=ch.OFFMAP_SLEEP_SENTINEL)
npc("already_offmap", loc="")
_sub_force_rules()
check("offmap home detaches and sleeps", not ch.get_character_current_location("offmap") and sleeping("offmap"))
check("already offmap sleeps in place", not ch.get_character_current_location("already_offmap") and sleeping("already_offmap") and travel_engine.get_journey("already_offmap") is None)
npc("room_change", home=b, loc=b, room=bedroom)
_sub_force_rules()
check("already home applies configured room and flags", ch.get_character_current_room("room_change") == bedroom and sleeping("room_change"))
from app.models.account import save_user_profile
npc("avatar_npc")
save_user_profile({"active_character": "avatar_npc"})
_sub_force_rules()
check("player remains untouched", not sleeping("avatar_npc") and travel_engine.get_journey("avatar_npc") is None and ch.get_character_current_location("avatar_npc") == a)
save_user_profile({"active_character": ""})
npc("gated_home")
save_test_rules([force, {"id": "home_gate", "type": "block", "action": "enter", "target": {"scope": "location", "location_id": b}, "condition": "always"}])
_sub_force_rules()
check("home enter rules do not block forced departure", travel_engine.get_journey("gated_home") is not None and not sleeping("gated_home"))
npc("redirected")
old_journey, reason = travel_engine.start_journey_to_point("redirected", 10, 10)
check("other journey fixture", old_journey is not None)
_sub_force_rules()
redirected = travel_engine.get_journey("redirected")
check("other journeys are redirected home", redirected is not None and redirected.get("target") == b and redirected != old_journey and not sleeping("redirected"))
save_test_rules([force])
npc("in_the_open", loc="")
ch.set_character_pos("in_the_open", 0, 10)
_sub_force_rules()
check("a character in the open (no location, metre point) walks home",
      travel_engine.get_journey("in_the_open") is not None and not sleeping("in_the_open"))
print("All force journey checks passed")
