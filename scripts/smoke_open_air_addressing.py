#!/usr/bin/env python3
"""Open-air addressability across room boundaries (task 113).

Usage: ./.venv/bin/python scripts/smoke_open_air_addressing.py

Hand-derived geometry: hearing radius is configured to 5 m. Wren stands at
(0, 0) in Courtyard, Reed on the same location's ground at (3, 0): distance
3 m <= 5, so both can address each other. Fern at (0, 4) is also outdoors;
sqrt(3**2 + 4**2) = 5 pins the inclusive boundary from Reed. Far on the ground
at (6, 0) is outside Wren's circle. Indoor Ivo and corridor Cora at (1, 0)
are NOT open, despite being only 1 m away. Location-less Vale at (3, 4) is
exactly 5 m from Wren and 4 m from Reed. Same-room Moss at (100, 0) remains
addressable through the room half regardless of distance. No-point and
half-point characters cannot join an earshot circle.

Existing wall rule is directional: an indoor speaker can address open-air
targets within the radius, but an open-air speaker does not acquire indoor
targets through the circle. Normal ambient speech does not enter an indoor
room. Whispers from a location stay in their room, including outdoor rooms
(the existing location-based whisper gate is deliberately preserved).
Moving Wren into Study without changing (0,0) pins that directional wall
rule for an actual avatar exactly 3 m from the ground NPC Reed.

These probes catch a wilderness-only roster, room-only HUD/TalkTo/presence,
an exclusive radius, inherited outdoor flags leaking indoor/corridor targets,
stale room metadata after writes, per-character profile reads in the new
roster, and a selected addressee whose actual spoken line never arrives.
Only temporary world/instance storage is used; no server or LLM is started.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="open-air-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(STORAGE / "clips")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()
config._CONFIG.setdefault("game", {})["hearing_radius_m"] = 5.0

from app.core import agent_loop, npc_actions, perception, streaming  # noqa: E402
from app.core.auth_dependency import current_user_ctx  # noqa: E402
from app.core.system_prompt_builder import _load_presence  # noqa: E402
from app.core.thought_context import room_presence_names  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.core.users import create_user, get_user_by_id, update_user  # noqa: E402
from app.models import character, perception_store, world  # noqa: E402
from app.plugins.context import PluginContext  # noqa: E402
from app.routes import play  # noqa: E402
from plugins.talk_to.skill import TalkToSkill  # noqa: E402

get_task_queue()._started = True  # Keep real background workers/LLMs stopped.
LOC = world.add_location("Gate", "A gate and courtyard.", rooms=[
    {"id": "yard", "name": "Courtyard", "indoor": "outdoor"},
    {"id": "patio", "name": "Patio", "indoor": "outdoor"},
    {"id": "inside", "name": "Study", "indoor": "indoor"},
])["id"]


def place(name, location, room, x, z, *, pooled=False):
    character.save_character_profile(name, {
        "character_name": name, "template": "human-roleplay",
        "current_location": location, "current_room": room,
    }, create_new=True)
    with db.transaction() as conn:
        conn.execute("UPDATE character_state SET pos_x=?, pos_z=? WHERE character_name=?",
                     (x, z, name))
        if pooled:
            conn.execute("UPDATE characters SET status='pooled' WHERE name=?", (name,))


place("Wren", LOC, "yard", 0, 0)
place("Reed", LOC, world.GROUND_ROOM_ID, 3, 0)
place("Fern", LOC, "patio", 0, 4)
place("Far", LOC, world.GROUND_ROOM_ID, 6, 0)
place("Ivo", LOC, "inside", 1, 0)
place("Cora", LOC, world.floor_room_id(0), 1, 0)
place("Vale", "", "", 3, 4)
place("Moss", LOC, "yard", 100, 0)
place("Unplaced", "", "", None, None)
place("Halfpoint", LOC, world.GROUND_ROOM_ID, 1, None)
place("Pooled", LOC, world.GROUND_ROOM_ID, 1, 0, pooled=True)
character._write_character_pos("_system", 1, 0)
uid = create_user("demo", "smoke-password", allowed_characters=["Wren"])
update_user(uid, settings={"active_character": "Wren"})
current_user_ctx.set(get_user_by_id(uid))

CHECKS = 0
FAILURES = []


def check(label, actual, expected):
    global CHECKS
    CHECKS += 1
    if actual != expected:
        FAILURES.append(label)
        print(f"FAIL {label}: {actual!r}; expected {expected!r}")
    else:
        print(f"OK {label}")


check("configured radius", perception.get_hearing_radius_m(), 5.0)
check("room first, then open circle, deduped, no self/pooled/system/partial point",
      perception.addressable_for("Wren"), ["Moss", "Reed", "Fern", "Vale"])
check("ground can address outdoor-room avatar", "Wren" in perception.addressable_for("Reed"), True)
check("inclusive 3-4-5 boundary between outdoor areas", "Fern" in perception.addressable_for("Reed"), True)
check("beyond circle and different room", "Far" in perception.addressable_for("Wren"), False)
check("location-less to ground", "Reed" in perception.addressable_for("Vale"), True)
check("ground to location-less", "Vale" in perception.addressable_for("Reed"), True)
check("corridor is not open", "Cora" in perception.nearby_in_the_open("Wren"), False)
check("indoor is not open", "Ivo" in perception.addressable_for("Reed"), False)
check("indoor speaker retains outward circle", "Reed" in perception.addressable_for("Ivo"), True)
check("no point has no circle", perception.addressable_for("Unplaced"), [])
check("no point retains room half", perception._addressable(LOC, "yard", None, "Wren"), ["Moss"])

scene = play.play_scene(limit=30)
check("HUD present offers cross-area addressee", "Reed" in scene["present"], True)
check("Others offers cross-area addressee", "Reed" in [r["name"] for r in play.play_others()["characters"]], True)
check("thought presence offers cross-area avatar", "Wren" in room_presence_names("Reed", LOC, world.GROUND_ROOM_ID)[0], True)
lines, elsewhere, anyone = _load_presence("Reed", LOC)
check("system prompt offers cross-area avatar", any("Wren" in line and "NOT" not in line for line in lines), True)
check("reachable avatar is not elsewhere", any("Wren" in line for line in elsewhere), False)
check("tool availability offers cross-area avatar", "Wren" in streaming.tool_step_presence("Reed"), True)


class SayRequest:
    async def json(self):
        return {"content": "Hello across the courtyard.", "addressees": ["Reed"]}


async def say():
    # Keep the actual dispatch/recording; only suppress the delayed LLM fallback.
    async def no_fallback(*args, **kwargs):
        pass
    async def inline_worker(func, /, *args, **kwargs):
        return func(*args, **kwargs)
    with patch.object(play, "_storyteller_after_silence", no_fallback), \
         patch.object(play, "_storyteller_fallback", no_fallback), \
         patch.object(asyncio, "to_thread", inline_worker):
        return await asyncio.wait_for(play.play_say(SayRequest()), timeout=10)


loop = agent_loop.AgentLoop()
with patch.object(agent_loop, "get_agent_loop", return_value=loop):
    result = asyncio.run(say())
    check("play_say records line", result["ok"], True)
    stored = db.get_connection().execute("SELECT addressees FROM utterances WHERE id=?",
                                         (result["utterance_id"],)).fetchone()
    check("play_say retains selected ground addressee", json.loads(stored[0]), ["Reed"])
    rows = perception_store.get_character_room_stream("Reed", LOC, world.GROUND_ROOM_ID, limit=50)
    check("ground listener actually reads avatar line", any(r["content"] == "Hello across the courtyard." for r in rows), True)
    check("perception stores content for selected listener", db.get_connection().execute(
        "SELECT content FROM perceptions WHERE utterance_id=? AND perceiver='Reed'",
        (result["utterance_id"],)).fetchone()[0], "Hello across the courtyard.")
    check("addressed NPC owes response", "Reed" in result["bumped"], True)
    talk = TalkToSkill({"enabled": True}, PluginContext("talk_to"))
    for sender, target in [("Reed", "Wren"), ("Wren", "Reed"), ("Vale", "Reed"), ("Reed", "Vale")]:
        outcome = talk.execute(json.dumps({"agent_name": sender, "name": target,
                                           "message": "Hello from the open."}))
        check(f"TalkTo {sender} to {target}", outcome.startswith("Spoke to "), True)
        target_loc = character.get_character_current_location(target)
        target_room = character.get_character_current_room(target)
        heard = perception_store.get_character_room_stream(target, target_loc, target_room, limit=50)
        check(f"TalkTo {sender} to {target} reaches recipient transcript",
              any(r["content"] == "Hello from the open." and r["meta"].get("speaker") == sender
                  for r in heard), True)

# The existing named-listener distance path still crosses a wall, without a
# second range rule: Vale (3,4) to Ivo (1,0) is sqrt(20) < 5 m.
line = perception.record_utterance(speaker="Vale", content="Named through a wall.", addressees=["Ivo"])
check("existing named-listener distance path delivers through wall",
      db.get_connection().execute(
          "SELECT kind, content FROM perceptions WHERE utterance_id=? AND perceiver='Ivo'",
          (line,)).fetchone()[:], ("addressed", "Named through a wall."))

# Trace real SQL on two warmed polls: one bulk position query each, no
# profile SELECT and no location re-read while the generation is unchanged.
world.get_location_by_id(LOC)
queries = []
conn = db.get_connection()
conn.set_trace_callback(queries.append)
try:
    for _ in range(2):
        perception.nearby_in_the_open("Wren", {"x": 0, "z": 0})
finally:
    conn.set_trace_callback(None)
selects = [q for q in queries if q.lstrip().upper().startswith("SELECT")]
check("two warm polls perform exactly two position SELECTs", len(selects), 2)
check("open roster has no per-character profile reads", any("profile_json" in q for q in selects), False)

for name in ("Reed", "Fern"):
    profile = character.get_character_profile(name)
    profile["template"] = "npc-temporary"
    character.save_character_profile(name, profile)
check("NPC conversation partners include neighbouring outdoor room",
      "Fern" in [p["name"] for p in npc_actions.present_partners("Reed")], True)

with db.transaction() as conn:
    conn.execute("UPDATE character_state SET current_room='inside' WHERE character_name='Wren'")
check("indoor avatar addresses ground NPC 3 m away under existing wall rule",
      "Reed" in perception.addressable_for("Wren"), True)
check("ground NPC does not acquire indoor avatar 3 m away",
      "Wren" in perception.addressable_for("Reed"), False)
with db.transaction() as conn:
    conn.execute("UPDATE character_state SET current_room='yard' WHERE character_name='Wren'")

line = perception.record_utterance(speaker="Reed", content="Ambient outside.")
check("ambient outside cannot enter indoor room", db.get_connection().execute(
    "SELECT count(*) FROM perceptions WHERE utterance_id=? AND perceiver='Ivo'", (line,)).fetchone()[0], 0)
line = perception.record_utterance(speaker="Wren", content="Private.", volume="whisper", addressees=["Reed"])
check("existing location-based whisper wall retained", db.get_connection().execute(
    "SELECT count(*) FROM perceptions WHERE utterance_id=? AND perceiver='Reed'", (line,)).fetchone()[0], 0)

# A room name is tolerated by the room half, so the open half must resolve it too.
with db.transaction() as conn:
    conn.execute("UPDATE character_state SET current_room='Patio' WHERE character_name='Fern'")
check("historical room name stays open", "Fern" in perception.addressable_for("Wren"), True)
data = world._load_world_data()
loc = next(loc for loc in data["locations"] if loc["id"] == LOC)
loc["indoor"] = "outdoor"
for room in loc["rooms"]:
    if room["id"] == "patio":
        room["indoor"] = "indoor"
    if room["id"] == world.floor_room_id(0):
        room["indoor"] = "outdoor"  # Reserved corridors still are not open.
world._save_world_data(data)
check("location write invalidates open-room metadata", "Fern" in perception.addressable_for("Wren"), False)
check("outdoor location cannot turn explicit indoor room open", "Ivo" in perception.addressable_for("Reed"), False)
check("outdoor corridor flag cannot make corridor open", "Cora" in perception.nearby_in_the_open("Wren"), False)

print(f"{CHECKS} checks, {len(FAILURES)} failed")
sys.exit(bool(FAILURES))
