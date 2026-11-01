#!/usr/bin/env python3
"""ChangeOutfit takes the piece a free name most likely means, and takes off
pieces by their menu name.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_change_names.py

Runs against a THROWAWAY storage directory — no real world, no server.
On 2026-11-01 a tool model wrote what the roleplay said ("eine lange Bluse
und Shorts") instead of a menu name: {"equip":["long blouse","shorts"],
"unequip_slots":["top","bottom"]}. Both slots were emptied, nothing went on.
Another call took off "Red lace bra (underwear_top)" — a menu line with its
note — and found nothing. Hand-derived from
``OutfitChangeSkill._match_inventory`` / ``_closest_piece``:

Fixture "sample": Sheer silk blouse (top, worn), Business Skirt (bottom,
worn), Long sport top (top), Short skirt (bottom), Red Corset Top (top),
Red Off-Shoulder Top (top), Red lace bra (underwear_top, worn).
  [1] The real call: "long blouse" — last word "blouse" is the last word of
      "Sheer silk blouse" only ("Long sport top" shares just "long") ->
      that one; "shorts" — no piece ends in "short", "Short skirt" is the
      only name containing it -> that one. Worn afterwards: Short skirt,
      Sheer silk blouse, Red lace bra; no "FEHLER" in the answer.
      (Fails on 4a3f3b91: both "nicht im Inventar", top and bottom empty.)
  [2] "red top": three names end in "top" -> no guess, "nicht im Inventar".
  [3] "red cup": no name contains "cup" -> no guess (a colour alone never
      matches).
  [4] unequip_items ["Red lace bra (underwear_top)"] -> the bra is taken off
      ("'Red lace bra' abgelegt"). (Fails on 4a3f3b91: not_equipped.)
  [5] unequip_items ["lace"] guesses nothing: the old substring rule takes
      it as "Red lace bra" (already off -> not_equipped), never another
      piece, and "Sheer silk blouse" stays on.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="outfit-names-") as tmp:
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
        from app.models.inventory import (add_item, add_to_inventory, equip_piece,
                                          get_character_inventory)
        save_character_profile("sample", {"template": "human-roleplay"}, create_new=True)
        for name, slots, worn in (
                ("Sheer silk blouse", ["top"], True), ("Business Skirt", ["bottom"], True),
                ("Long sport top", ["top"], False), ("Short skirt", ["bottom"], False),
                ("Red Corset Top", ["top"], False), ("Red Off-Shoulder Top", ["top"], False),
                ("Red lace bra", ["underwear_top"], True)):
            item = add_item(name, category="outfit_piece", prompt_fragment=name.lower(),
                            outfit_piece={"slots": slots})
            add_to_inventory("sample", item["id"])
            if worn:
                equip_piece("sample", item["id"])

        from app.skills.outfit_change_skill import OutfitChangeSkill
        skill = OutfitChangeSkill({})

        def run(**spec):
            return skill.execute(json.dumps({"agent_name": "sample", "user_id": "", **spec}))

        def worn():
            inv = get_character_inventory("sample", include_equipped=True)["inventory"]
            return sorted(e["item_name"] for e in inv if e.get("equipped"))

        print("[1] the real call")
        out = run(equip=["long blouse", "shorts"], unequip_slots=["top", "bottom"])
        print("      " + out)
        check("worn", worn(), ["Red lace bra", "Sheer silk blouse", "Short skirt"])
        check("no error", "FEHLER" in out, False)

        print("[2] ambiguous kind")
        out = run(equip=["red top"])
        check("not found", "'red top' nicht im Inventar" in out, True)

        print("[3] a colour alone")
        out = run(equip=["red cup"])
        check("not found", "'red cup' nicht im Inventar" in out, True)

        print("[4] take off by menu line")
        out = run(unequip_items=["Red lace bra (underwear_top)"])
        check("taken off", "'Red lace bra' abgelegt" in out, True)
        check("worn", worn(), ["Sheer silk blouse", "Short skirt"])

        print("[5] no guess when taking off")
        out = run(unequip_items=["lace"])
        check("worn", worn(), ["Sheer silk blouse", "Short skirt"])

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
