#!/usr/bin/env python3
"""Outfit compliance notices: free-text wardrobes follow their switch, and an
identical notice is stored once while it is unread.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_compliance_notices.py

Runs against a THROWAWAY storage directory — no real world, no server. The
room's decency is pinned per case (``resolve_decency`` is replaced), the rest
is the real code (``app/core/outfit_compliance.py``,
``app/models/notifications.py``). Hand-derived from the rules:

  required slots = top + bottom (no body-slot package narrows them);
  public wants both covered, private (alone) and nude_ok want nothing.

  [1] A temporary NPC (npc-temporary: outfit_system_enabled false) with a
      described outfit, outfit_worn "true", in a public room: covered, no
      violation, no notice — it used to read "missing: bottom, top" because
      it has no pieces (172 such rows in one world, 2026-10-31).
  [2] Same NPC with outfit_worn "false" (the switch), public: violations
      bottom + top, reason outfit_not_worn; ONE notice, in the character's
      language (default German, shared/languages/de.json):
      "⚠️ Outfit passt nicht in einen public-Raum — nicht angezogen, es fehlt:
      bottom, top."
  [3] The same check twice more: still one row (unread, same text).
  [4] After marking it read, the next check stores a second row.
  [5] Undressed in a private room (alone): no violation, no new row.
  [6] A piece-wardrobe character (human-roleplay) without pieces and with an
      empty inventory in a public room: bottom + top, no_inventory_piece;
      text "… es fehlt: bottom, top. Keine passende Kleidung im Inventar."
      — twice, one row.
  [7] The same character in a private room with a forced bottom that is not
      worn still gets its notice (missing trousers are a reason even where
      underwear would do; unchanged): "… private-Raum — es fehlt: bottom. …"
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
    with tempfile.TemporaryDirectory(prefix="outfit-notices-") as tmp:
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

        from app.core import outfit_compliance as oc
        from app.models.character import save_character_profile, set_outfit_intent
        from app.models.notifications import _load, mark_read
        room = {"decency": "public"}
        oc.resolve_decency = lambda name, is_intimate=False: (room["decency"], {})

        def rows(name):
            return [n for n in _load() if n["character"] == name and n["type"] == "outfit_mismatch"]

        save_character_profile("npc", {"template": "npc-temporary", "outfit_description": "grey apron",
                                       "outfit_worn": "true"}, create_new=True)
        print("[1] dressed temporary NPC, public")
        res = oc.apply_outfit_compliance("npc", is_intimate=False, is_wet=False, is_sleeping=False)
        check("violations", res["violations"], [])
        check("notices", len(rows("npc")), 0)

        print("[2] undressed temporary NPC, public")
        save_character_profile("npc", {"template": "npc-temporary", "outfit_description": "grey apron",
                                       "outfit_worn": "false"})
        res = oc.apply_outfit_compliance("npc", is_intimate=False, is_wet=False, is_sleeping=False)
        check("violations", res["violations"], [{"slot": "bottom", "reason": "outfit_not_worn"},
                                                {"slot": "top", "reason": "outfit_not_worn"}])
        check("text", [n["content"] for n in rows("npc")],
              ["⚠️ Outfit passt nicht in einen public-Raum — nicht angezogen, es fehlt: bottom, top."])

        print("[3] the same check again")
        for _ in range(2):
            oc.apply_outfit_compliance("npc", is_intimate=False, is_wet=False, is_sleeping=False)
        check("notices", len(rows("npc")), 1)

        print("[4] read, then again")
        mark_read(rows("npc")[0]["id"])
        oc.apply_outfit_compliance("npc", is_intimate=False, is_wet=False, is_sleeping=False)
        check("notices", len(rows("npc")), 2)

        print("[5] undressed, private room")
        room["decency"] = "private"
        res = oc.apply_outfit_compliance("npc", is_intimate=False, is_wet=False, is_sleeping=False)
        check("violations", res["violations"], [])
        check("notices", len(rows("npc")), 2)

        print("[6] piece wardrobe without pieces, public")
        room["decency"] = "public"
        save_character_profile("rp", {"template": "human-roleplay"}, create_new=True)
        for _ in range(2):
            res = oc.apply_outfit_compliance("rp", is_intimate=False, is_wet=False, is_sleeping=False)
        check("violations", res["violations"], [{"slot": "bottom", "reason": "no_inventory_piece"},
                                                {"slot": "top", "reason": "no_inventory_piece"}])
        check("text", [n["content"] for n in rows("rp")],
              ["⚠️ Outfit passt nicht in einen public-Raum — es fehlt: bottom, top. "
               "Keine passende Kleidung im Inventar."])

        print("[7] forced trousers not worn, private")
        room["decency"] = "private"
        set_outfit_intent("rp", {"forced_pieces": {"bottom": "item_x"}})
        res = oc.apply_outfit_compliance("rp", is_intimate=False, is_wet=False, is_sleeping=False)
        check("reason", [v["reason"] for v in res["violations"]], ["forced_piece_not_equipped"])
        check("text", rows("rp")[0]["content"],
              "⚠️ Outfit passt nicht in einen private-Raum — es fehlt: bottom. "
              "Keine passende Kleidung im Inventar.")

    print("FAIL: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
