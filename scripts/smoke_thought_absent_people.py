#!/usr/bin/env python3
"""Explicit thought presence smoke; uses only temporary storage.

Usage: ./.venv/bin/python scripts/smoke_thought_absent_people.py

Expectations derived by hand: Ava and Cleo share Studio, Ben is at Library:
only Ben is absent. Ben in Hall is elsewhere, in Studio present, so neither
is absent. Bens/Ben's/Ben’s mention Ben; Benches and ben do not. Unplaced
Dara knows no presence; self is never absent. First textual mentions order
results, capped at six. Both prompts must show Studio, exhaustive presence,
and Ben's absence. Extraction shows presence only if known, including
nobody for an empty room, and rejects imagined joint actions/completions.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
STORAGE = tempfile.TemporaryDirectory(prefix="thought-absence-")
paths.init(Path(STORAGE.name))
from app.core import db
db.init_schema()
from app.core import thought_context as tc
from app.core.prompt_templates import render, render_task
from app.models.character import save_character_profile, set_character_pos
from app.models.world import add_location, add_room
home = add_location(name="Workshop", description="")["id"]
away = add_location(name="Library", description="")["id"]
studio = add_room(home, "Studio", sync_world=False)["id"]
hall = add_room(home, "Hall", sync_world=False)["id"]

def seed(name, location="", room="", **extra):
    assert save_character_profile(name, dict(current_location=location,
        current_room=room, **extra), create_new=True)

seed("Ava", home, studio, character_task="Meet Ben", character_language="en")
seed("Ben", away)
seed("Cleo", home, studio)
seed("Dara")
assert hasattr(tc, "absent_named_people"), "missing absent-people helper"
assert tc.absent_named_people("Ava", home, studio, ["Ava Cleo Ben"]) == ["Ben"]
for text in ("Bens book", "Ben's book", "Ben’s book"):
    assert tc.absent_named_people("Ava", home, studio, [text]) == ["Ben"]
assert tc.absent_named_people("Ava", home, studio, ["Benches ben Ava Cleo"]) == []
assert tc.absent_named_people("Dara", "", "", ["Ben"]) == []
assert tc.room_presence_names("Dara", "", "") is None
with patch.object(tc, "location_presence_split", side_effect=RuntimeError("lookup")):
    assert tc.absent_named_people("Ava", home, studio, ["Ben"]) == []
for room in (hall, studio):
    seed("Ben", home, room)
    assert tc.absent_named_people("Ava", home, studio, ["Ben"]) == []
seed("Ben", away)
for name in ("Eli", "Finn", "Gia", "Hugo", "Iris", "Jade"):
    seed(name, away)
assert tc.absent_named_people("Ava", home, studio,
    ["Jade Ben", "Iris Hugo Gia Finn Eli"]) == ["Jade", "Ben", "Iris", "Hugo", "Gia", "Finn"]
set_character_pos("Dara", 100, 100)
assert tc.room_presence_names("Dara", "", "") == ([], [])
assert tc.absent_named_people("Dara", "", "", ["Ben"]) == ["Ben"]
with patch("app.models.account.get_active_character", return_value="Ben"), patch.object(
        tc, "_build_skill_context_blocks", return_value=[("demo", "Remember Iris")]):
    ctx = tc.build_thought_context("Ava", tools_hint="Jade")
assert ctx["absent_people"] == ["Ben", "Iris"], ctx["absent_people"]
assert "- Ben (avatar)" in ctx["absent_block"]
assert ctx["room_name"] == "Studio"
for template in ("chat/agent_thought.md", "chat/agent_thought_in_chat.md"):
    out = render(template, **ctx)
    assert "NOT with you — not at this place at all" in out
    assert "— room: Studio" in out
    assert "Only these are with you." in out
kwargs = dict(speaker_b="Ava", text_b="I touched Ben", existing_summary="",
              open_plans_block="", lang_instruction="", present_names="Cleo", absent_names="Ben")
_, out = render_task("extraction_thought", presence_known=True, **kwargs)
assert "Who was really in the room with Ava: Cleo." in out
assert "NOT there: Ben." in out
assert "never put its id into completed_ids" in out
_, out = render_task("extraction_thought", presence_known=False, **kwargs)
assert "Who was really" not in out and "NOT there:" not in out
_, out = render_task("extraction_thought", presence_known=True,
                     **dict(kwargs, present_names="", absent_names=""))
assert "Who was really in the room with Ava: nobody." in out
# Capture the real monologue call: current profile presence must reach extraction.
from types import SimpleNamespace
from app.core.memory_service import extract_memories_from_exchange
with patch("app.core.llm_router.llm_call", return_value=SimpleNamespace(
        content='{"memories": [], "completed_ids": []}')) as llm:
    extract_memories_from_exchange("Ava", "", "", "I touched Ben", None)
    prompt = llm.call_args.kwargs["user_prompt"]
    assert "Who was really in the room with Ava: Cleo." in prompt
    assert "NOT there: Ben." in prompt
    extract_memories_from_exchange("Dara", "", "", "I touched Ben", None)
    assert "Who was really in the room with Dara: nobody." in llm.call_args.kwargs["user_prompt"]
seed("Nia")
with patch("app.core.llm_router.llm_call", return_value=SimpleNamespace(
        content='{"memories": [], "completed_ids": []}')) as llm:
    extract_memories_from_exchange("Nia", "", "", "I touched Ben", None)
    assert "Who was really" not in llm.call_args.kwargs["user_prompt"]
print("OK — thought absence, room, roster and extraction checks passed")
