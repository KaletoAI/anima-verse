#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_read_item_verb.py

Hand-derived expectations: chronological p1..p4, p2 has no secret.
[a] R alone sees the verb without calling the provider. Reading Notebook
    returns Page 4 then Page 3 (newest unknown secrets), each text <=600 chars.
[b] Reading once hides the verb for that game day, and refuses repeats.
[c] Next day another character in the room hides/refuses reading, including
    an avatar; someone in a different room does not. No provider calls occur.
[d] R owning the notebook hides/refuses reading. An undiscovered placement,
    absent provider, or absent room placement also hides the verb.
[e] When visible, the real package loader and manager expose ReadItem only
    for thought turns, even with limits skipped; CONTENT_TOOL is true.
[f] Unknown/malformed input returns the plain missing-item error; a mixed-case
    name and an ID resolve. A failing provider returns an error, with no read.
    Reading creates no room perception/narrator line.
[g] As a temporary NPC (no memories), R gets no ReadItem verb in a thought
    turn and reading is refused with the missing-item error.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="read-item-verb-") as tmp:
        os.environ["STORAGE_DIR"] = tmp
        os.environ["INSTANCE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        paths.init_instance(tmp)
        from app.core import hooks
        from app.core.db import init_schema, transaction
        from app.core.game_time import GameTime, GameDuration
        from app.core.timeutils import set_game_time, set_game_factor
        from app.models.inventory import add_item, add_item_to_room, update_item, remove_item_from_room
        from app.models.world import add_location, add_room
        from app.models.secrets import add_secret
        from app.core.item_reading import npc_read_today
        from app.plugins.loader import discover_packages, load_plugin
        from app.skills.skill_manager import SkillManager
        init_schema()
        set_game_factor(0)
        now = GameTime.parse("Y0002-D109T12:00:00")
        set_game_time(now)
        with transaction() as conn:
            for name in ("O", "R", "Visitor"):
                conn.execute("INSERT INTO characters (name, created_at, updated_at) VALUES (?, '', '')", (name,))
        loc = add_location(name="Study", description="A quiet study")["id"]
        room = add_room(loc, "Desk", sync_world=True)["id"]
        other = add_room(loc, "Hall", sync_world=True)["id"]
        positions = {"R": room, "O": other, "Visitor": other}
        secrets = [add_secret("O", f"Note {i}")["id"] for i in range(1, 5)]
        pages = [{"ref": f"p{i}", "heading": f"Page {i}", "text": "x" * 700,
                  "secret_id": secrets[i-1] if i != 2 else ""} for i in range(1, 5)]
        calls = []
        def provider(item, reader):
            calls.append(reader)
            return pages
        hooks.register_provider("item_pages.test_pages", provider)
        iid = add_item("Notebook", category="document", owner="O", pages_source="test_pages", portable=False)["id"]
        add_item_to_room(loc, room, iid)
        from app.core import config
        real_get = config.get
        with patch("app.core.config.get", side_effect=lambda key, default=None: "read_item" if key == "packages.enabled" else real_get(key, default)):
            packages = discover_packages()
        pkg = next((p for p in packages if p.id == "read_item"), None)
        assert pkg is not None, "ReadItem package is missing"
        skill = dict(load_plugin(pkg))["read_item"]
        manager = SkillManager()
        manager.skills = [skill]
        def read(token):
            return skill.execute(json.dumps({"agent_name": "R", "input": json.dumps({"item": token})}))
        error = "There is nothing like that to read here."
        with patch("app.models.character.get_character_current_location", return_value=loc), patch("app.models.character.get_character_current_room", side_effect=lambda name: positions[name]), patch("app.models.character.get_character_language", return_value="en"), patch("app.core.perception.record_utterance") as narrator:
            assert skill.visible_for("R") and calls == []
            out = read("Notebook")
            assert out.startswith("You read in Notebook:\n[Page 4]\n")
            assert out.endswith("[Page 3]\n" + "x" * 600)
            assert out.count("x") == 1200
            print("PASS [a]")
            assert not skill.visible_for("R") and read(iid) == error
            print("PASS [b]")
            set_game_time(now + GameDuration.of(days=1))
            positions["Visitor"] = room
            before = len(calls)
            assert not skill.visible_for("R") and read(iid) == error
            with patch("app.models.account.get_active_character", return_value="Visitor"):
                assert not skill.visible_for("R")
            assert len(calls) == before
            positions["Visitor"] = other
            assert skill.visible_for("R")
            print("PASS [c]")
            update_item(iid, {"owner": "R"})
            assert not skill.visible_for("R") and read(iid) == error
            update_item(iid, {"owner": "O"})
            add_item_to_room(loc, room, iid, hidden=True, discovery_difficulty=999)
            assert not skill.visible_for("R")
            add_item_to_room(loc, room, iid, hidden=False)
            with patch("app.core.hooks.get_provider", return_value=None):
                assert not skill.visible_for("R")
            remove_item_from_room(loc, room, iid, quantity=999)
            assert not skill.visible_for("R")
            add_item_to_room(loc, room, iid)
            print("PASS [d]")
            assert skill.CONTENT_TOOL and skill.ALWAYS_LOAD
            for limits in (True, False):
                assert manager.get_agent_tools("R", check_limits=limits, turn="") == []
                assert manager.get_agent_tools("R", check_limits=limits, turn="chat") == []
                assert [t.name for t in manager.get_agent_tools("R", check_limits=limits, turn="thought")] == ["ReadItem"]
            print("PASS [e]")
            assert read("nothing") == error and read(None) == error
            def broken(item, reader):
                raise ValueError("test provider unavailable")
            hooks.register_provider("item_pages.test_pages", broken)
            assert read(iid) == error and not npc_read_today("R", iid)
            hooks.register_provider("item_pages.test_pages", provider)
            assert read("nOtEbOoK").startswith("You read in Notebook:")
            set_game_time(now + GameDuration.of(days=2))
            assert read(iid).startswith("You read in Notebook:")
            narrator.assert_not_called()
            print("PASS [f]")
            set_game_time(now + GameDuration.of(days=3))
            with patch("app.models.character.is_temporary_npc", side_effect=lambda name: name == "R"):
                assert manager.get_agent_tools("R", turn="thought") == []
                assert read(iid) == error
            assert [t.name for t in manager.get_agent_tools("R", turn="thought")] == ["ReadItem"]
            print("PASS [g]")
    print("PASS smoke_read_item_verb")


if __name__ == "__main__":
    main()
