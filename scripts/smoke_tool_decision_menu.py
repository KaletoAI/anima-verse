#!/usr/bin/env python3
"""The tool decision sees the names a verb takes: the outfit verb's clothes.

Usage:
    ./.venv/bin/python scripts/smoke_tool_decision_menu.py

Runs against a THROWAWAY storage directory — no real world, no server.
On 2026-10-31 a character's roleplay said "ein rotes Mieder"; the separate
tool LLM, whose prompt carried no clothing list, called ChangeOutfit with
"rotes Mieder" and the item "Red Mieder" was not found. Hand-derived from
``OutfitChangeSkill.decision_menu`` and ``streaming.decision_menu_note``:

Fixture: "sample" owns "Red Mieder" (top), "Black pencil skirt" (bottom),
"Silk Slip Dress" (top+bottom) and a lamp (category tool); the skirt is worn.
  [1] decision_menu, outfit pieces only, sorted by name:
      "Black pencil skirt (bottom, worn)", "Red Mieder (top)",
      "Silk Slip Dress (top+bottom)" — no lamp, no item id.
  [2] decision_menu_note with ChangeOutfit offered (indent 3 spaces):
      "   ChangeOutfit takes these names — copy one exactly (a part in brackets is
      a note, not part of the name):\\n" — the note appears because [1] has brackets.
      + one "   - <line>\\n" per [1] line.
  [3] A verb without a menu and an unknown tool name add nothing; with only
      those offered the note is "".
  [4] tool_state_note carries the same block (it is what every tool-decision
      prompt calls).
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


class Plain:
    """A verb without a menu (BaseSkill default)."""
    name = "Plain"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="decision-menu-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text("{}")
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()

        from app.models.character import save_character_profile
        from app.models.inventory import add_item, add_to_inventory, equip_piece
        save_character_profile("sample", {"template": "human-roleplay"}, create_new=True)
        for name, slots in (("Red Mieder", ["top"]), ("Black pencil skirt", ["bottom"]),
                            ("Silk Slip Dress", ["top", "bottom"])):
            item = add_item(name, category="outfit_piece", prompt_fragment=name.lower(),
                            outfit_piece={"slots": slots})
            add_to_inventory("sample", item["id"])
            if name == "Black pencil skirt":
                equip_piece("sample", item["id"])
        add_to_inventory("sample", add_item("Lamp", category="tool")["id"])

        from app.skills.base import BaseSkill
        from app.skills.outfit_change_skill import OutfitChangeSkill
        skill = OutfitChangeSkill({})
        Plain.decision_menu = BaseSkill.decision_menu
        menu = skill.decision_menu("sample")
        print("[1] decision_menu")
        check("lines", menu, ["Black pencil skirt (bottom, worn)", "Red Mieder (top)",
                              "Silk Slip Dress (top+bottom)"])

        from app.core import streaming
        skills = {skill.name: skill, "Plain": Plain()}
        manager = mock.Mock(get_skill_by_name=lambda n: skills.get(n))
        with mock.patch("app.core.dependencies.get_skill_manager", lambda: manager):
            print("[2] decision_menu_note")
            check("note", streaming.decision_menu_note("sample", {skill.name: 1, "Plain": 1}),
                  f"   {skill.name} takes these names — copy one exactly"
                  " (a part in brackets is a note, not part of the name):\n"
                  + "".join(f"   - {line}\n" for line in menu))
            print("[3] no menu, unknown tool")
            check("note", streaming.decision_menu_note("sample", {"Plain": 1, "Nope": 1}), "")
            print("[4] tool_state_note carries it")
            check("contained", "   - Red Mieder (top)\n" in streaming.tool_state_note("sample", {skill.name: 1}), True)

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
