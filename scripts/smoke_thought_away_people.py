#!/usr/bin/env python3
"""Away characters in thought prompts; uses only temporary storage.

Usage: ./.venv/bin/python scripts/smoke_thought_away_people.py

Expectations derived by hand from the feature: Ava is in Studio of Workshop.
Kai and Lia carry ``avatar_only_presence`` and nobody controls them, so they
are out of the world. Kai has the away note "is travelling and will be back
soon", Lia none, so she gets the default "is away right now and cannot be
reached". Ben is an ordinary character at Library, so he stays an absent
person (message him or go to him). Ava's prompt names all three:
- absent_people == ["Ben"]  (Kai and Lia move out of that list)
- away_people   == [("Kai", note), ("Lia", default)] in first-mention order
- the system prompt carries the AWAY section with "- Kai is travelling …",
  the user-turn presence line says "Kai is travelling … — away from this world".
Once a player controls Kai, he is a normal absent person again and his note
vanishes. With the flag off, the note is ignored even if it is filled in.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
STORAGE = tempfile.TemporaryDirectory(prefix="thought-away-")
paths.init(Path(STORAGE.name))
from app.core import db
db.init_schema()
from app.core import thought_context as tc
from app.core.prompt_templates import render
from app.models import account
from app.models.character import save_character_profile, save_character_config
from app.models.world import add_location, add_room

home = add_location(name="Workshop", description="")["id"]
library = add_location(name="Library", description="")["id"]
studio = add_room(home, "Studio", sync_world=False)["id"]

KAI_NOTE = "is travelling and will be back soon"


def seed(name, location="", room="", **extra):
    assert save_character_profile(name, dict(current_location=location,
        current_room=room, **extra), create_new=True)


seed("Ava", home, studio, character_task="Meet Ben, Kai and Lia", character_language="en")
seed("Ben", library)
seed("Kai")
seed("Lia")
assert save_character_config("Kai", {"avatar_only_presence": "true", "away_note": KAI_NOTE})
assert save_character_config("Lia", {"avatar_only_presence": "true"})

# The helper itself.
assert account.away_note("Kai") == KAI_NOTE
assert account.away_note("Lia") == account.AWAY_NOTE_DEFAULT
assert account.away_note("Ben") == ""
with patch.object(account, "get_all_avatars", return_value={"Kai"}):
    assert account.away_note("Kai") == "", "a controlled avatar is not away"

absent, away = tc.split_away(["Kai", "Ben", "Lia"])
assert absent == ["Ben"], absent
assert away == [("Kai", KAI_NOTE), ("Lia", account.AWAY_NOTE_DEFAULT)], away

# Full thought context + both system templates + the user-turn presence line.
with patch.object(tc, "_build_skill_context_blocks", return_value=[]):
    ctx = tc.build_thought_context("Ava")
assert ctx["absent_people"] == ["Ben"], ctx["absent_people"]
assert [n for n, _ in ctx["away_people"]] == ["Kai", "Lia"], ctx["away_people"]
assert ctx["away_block"] == f"- Kai {KAI_NOTE}\n- Lia {account.AWAY_NOTE_DEFAULT}"
for template in ("chat/agent_thought.md", "chat/agent_thought_in_chat.md"):
    out = render(template, **ctx)
    assert "AWAY — out of the world for now" in out, template
    assert f"- Kai {KAI_NOTE}" in out, template
    assert "- Ben" in out.split("AWAY —")[0], "Ben stays in the absent section"
    assert "- Kai" not in out.split("AWAY —")[0], "Kai must not be in the absent section"
line = render("chat/thought_presence.md", **ctx)
assert "Ben are NOT here" in line, line
assert f"Kai {KAI_NOTE} — away from this world, Kai cannot answer" in line, line

# A controlled Kai is an ordinary absent person again.
with patch.object(account, "get_all_avatars", return_value={"Kai"}), patch.object(
        tc, "_build_skill_context_blocks", return_value=[]):
    ctx = tc.build_thought_context("Ava")
assert "Kai" in ctx["absent_people"], ctx["absent_people"]
assert [n for n, _ in ctx["away_people"]] == ["Lia"], ctx["away_people"]

# Flag off: the note alone does nothing.
assert save_character_config("Kai", {"avatar_only_presence": "false", "away_note": KAI_NOTE})
assert account.away_note("Kai") == ""

# No away people: the section is absent, the presence line unchanged.
assert save_character_config("Lia", {"avatar_only_presence": "false"})
with patch.object(tc, "_build_skill_context_blocks", return_value=[]):
    ctx = tc.build_thought_context("Ava")
assert ctx["away_people"] == [] and ctx["away_block"] == ""
assert "AWAY —" not in render("chat/agent_thought.md", **ctx)
assert "away from this world" not in render("chat/thought_presence.md", **ctx)
print("OK — away characters leave the absent list and get their own note")
