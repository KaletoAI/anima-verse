#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_outdoor_backstop_carry.py

Hand-derived: alternating A/B replies at cells 0,0,1,1,2 consume five
hops, so reply five dispatches one winddown. Moving again must preserve
that marker. An avatar clears both carry sources; two subsequent replies
consume only two hops. A new NPC conversation clears its own carry source.
Indoor room changes keep independent counters, and max preserves a larger
budget already in the destination cell. All storage is temporary.
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
paths.init(tempfile.mkdtemp(prefix="outdoor-carry-"))
from app.core import config, db
config.load(paths.get_storage_dir() / "config.json")
db.init_schema()
from app.core import agent_loop as al, chat_engine, perception, room_entry, stat_sources
from app.models import character, account

loop = al.AgentLoop()
point = {"x": 1, "z": 1}
async def inline(fn, *args, **kwargs):
    return fn(*args, **kwargs)

def dispatch(speaker, avatar=False, loc="", room=""):
    return loop.dispatch_room_reactions(speaker=speaker, content="Hello", volume="normal",
        location_id=loc, room_id=room, is_avatar=avatar)

def chat(*args, **kwargs):
    kwargs["publish_reply"]("A reply.")
    return "A reply."

def reply(speaker):
    other = "B" if speaker == "A" else "A"
    asyncio.run(loop._run_respond_turn(speaker, {
        "speaker": other, "content": "Hello", "volume": "normal",
        "obligatory": True, "cascade": True}))

with patch.object(character, "get_character_pos", side_effect=lambda *a: dict(point)), \
     patch.object(character, "get_character_current_location", return_value=""), \
     patch.object(character, "get_character_current_room", return_value=""), \
     patch.object(perception, "nearby_in_the_open", return_value=["A", "B"]), \
     patch.object(room_entry, "characters_in_room", return_value=["A", "B"]), \
     patch.object(account, "is_player_controlled", return_value=False), \
     patch.object(al, "_is_respond_eligible", return_value=True), \
     patch.object(al, "_is_agent_eligible", return_value=True), \
     patch.object(chat_engine, "run_chat_turn", side_effect=chat), \
     patch.object(perception, "record_utterance", return_value=1), \
     patch.object(stat_sources, "source_from_utterance", return_value=SimpleNamespace(location_id="", room_id="", event_id="room:1")), \
     patch.object(asyncio, "to_thread", inline), \
     patch.object(loop, "bump_respond", return_value=True) as bump:
    for i in range(5):
        point["x"] = 1 + (i // 2) * 50
        reply("A" if i % 2 == 0 else "B")
        key = loop._room_key("", "", "A")
        assert loop._room_ai_turns[key] == i + 1, (i, loop._room_ai_turns)
    assert key in loop._room_winddown_done
    assert sum(bool(c.kwargs.get("winding_down")) for c in bump.call_args_list) == 1
    point["x"] += 50
    dispatch("A")
    key = loop._room_key("", "", "A")
    assert key in loop._room_winddown_done
    dispatch("Player", True)
    point["x"] += 50
    reply("A")
    reply("B")
    key = loop._room_key("", "", "A")
    assert loop._room_ai_turns[key] == 2
    loop.reset_room_energy("", "", "A")
    point["x"] += 50
    dispatch("A")
    key = loop._room_key("", "", "A")
    assert loop._room_ai_turns.get(key, 0) == 0
    loop._room_ai_turns[key] = 8
    dispatch("A")
    point["x"] += 50
    dest = loop._room_key("", "", "A")
    loop._room_ai_turns[dest] = 10
    dispatch("A")
    assert loop._room_ai_turns[dest] == 10
    loop._room_ai_turns["inn/a"] = 4
    dispatch("A", loc="inn", room="b")
    assert loop._room_ai_turns.get("inn/b", 0) == 0
    assert loop._room_ai_turns["inn/a"] == 4
print("OK: outdoor carry, winddown, resets, max merge and indoor isolation")
