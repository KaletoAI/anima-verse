#!/usr/bin/env python3
"""Smoke turn-specific tools and thought context.

Usage: ./.venv/bin/python scripts/smoke_skill_turn_kinds.py

Hand-derived expectations: Ana enables dummy_note, whose sole turn is thought.
Thus thought tools contain it and default/chat tools do not, even with limits
skipped. Its block appears once in thought context. Unflagged talk_to remains
available in both turns. Ben explicitly disables dummy_note and sees none.
A false visibility condition hides it even on a thought turn.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="skill-turns-"))
from app.core import paths
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db
config.load(STORAGE / "config.json")
db.init_schema()
from app.models.character import save_character_profile, save_character_skill_config
from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.skill_manager import SkillManager
from app.core import thought_context


class DummyNote(PluginSkill):
    SKILL_ID = "dummy_note"
    ALWAYS_LOAD = True
    TURN_KINDS = ("thought",)

    def execute(self, raw_input):
        return "ok"

    def thought_context_block(self, character_name):
        return "DUMMY-BLOCK"


class TalkTo(PluginSkill):
    SKILL_ID = "talk_to"

    def execute(self, raw_input):
        return "ok"


for name in ("Ana", "Ben"):
    assert save_character_profile(name, {"name": name, "language": "en"}, create_new=True)
save_character_skill_config("Ana", "dummy_note", {"enabled": True})
save_character_skill_config("Ben", "dummy_note", {"enabled": False})
note = DummyNote({"enabled": True}, PluginContext("notes"))
note.name = "dummy_note"
talk = TalkTo({"enabled": True}, PluginContext("conversation"))
talk.name = "talk_to"
# Avoid loading unrelated installed packages; exercise the real filtering methods.
sm = SkillManager.__new__(SkillManager)
sm.skills = [note, talk]


def names(tools):
    return {tool.name for tool in tools}


assert "dummy_note" in names(sm.get_agent_tools("Ana", turn="thought"))
assert "dummy_note" not in names(sm.get_agent_tools("Ana", check_limits=False))
assert "talk_to" in names(sm.get_agent_tools("Ana", check_limits=False))
assert "talk_to" in names(sm.get_agent_tools("Ana", turn="thought"))
assert "dummy_note" not in names(sm.get_agent_tools("Ben", turn="thought"))
assert "dummy_note" not in names(sm.get_agent_tools("", check_limits=False))
with patch("app.core.dependencies.get_skill_manager", return_value=sm):
    blocks = thought_context._build_skill_context_blocks("Ana")
assert [block for _, block in blocks].count("DUMMY-BLOCK") == 1
# Usage lines follow the same turn filter as the tool list.
captured = []
with patch.object(DummyNote, "get_usage_instructions",
                  lambda self, fmt="", character_name="": captured.append("thought") or "DUMMY-USAGE"):
    assert "DUMMY-USAGE" not in sm.get_agent_usage_instructions("Ana", "", check_limits=False)
    assert "DUMMY-USAGE" in sm.get_agent_usage_instructions("Ana", "", turn="thought")
with patch.object(note, "visible_for", return_value=False):
    assert "dummy_note" not in names(sm.get_agent_tools("Ana", turn="thought"))
print("PASS: skill turn kinds")
