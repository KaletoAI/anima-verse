#!/usr/bin/env python3
"""outfit_renderer.set_outfit_worn — the public writer of a free-text
wardrobe's "Dressed" switch.

Usage:
    ./.venv/bin/python scripts/smoke_set_outfit_worn.py

Runs against a THROWAWAY storage directory — no real world, no server, no
package (so the undressed text is the core's "no clothes"). Every expectation
is derived by hand from the rules in ``app/core/outfit_renderer.py``:
the editor's select stores the STRINGS "true"/"false", ``is_outfit_worn``
reads both strings and bools, ``free_text_outfit`` is "wearing: <text>"
dressed and "no clothes" undressed, and ``save_character_profile`` hands
(old worn text, new worn text) of a temporary NPC to
``npc_assets.on_outfit_description_changed``.

  [1] Temporary NPC "npc a", outfit_worn "true", description "grey apron":
      set_outfit_worn(False) → True; stored outfit_worn == "false" (the
      editor's string); one profile_patched({"outfit_worn": "true"} →
      {"outfit_worn": "false"}); the asset hook sees
      ("wearing: grey apron" → "no clothes"); one compliance round.
  [2] The same call again → True (already undressed), and NOTHING happens:
      no profile_patched, no compliance round.
  [3] The NPC pipeline's bool shape: outfit_worn True (bool) → set False →
      True, stored "false".
  [4] set_outfit_worn(True) → True, stored "true".
  [5] A character with the piece-based wardrobe (human-roleplay, no
      outfit_worn key) → False, the profile still has no outfit_worn key, no
      signal.
  [6] No such character → False.
  [7] A failed save (save_character_profile → False) → False, no signal.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="set-outfit-worn-") as tmp:
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

        from app.core import sync_topics
        from app.core.outfit_renderer import set_outfit_worn
        from app.models import character as ch

        ch.save_character_profile("npc a", {
            "template": "npc-temporary", "outfit_description": "grey apron",
            "outfit_worn": "true"}, create_new=True)
        ch.save_character_profile("roleplay b", {"template": "human-roleplay"},
                                  create_new=True)

        patched, assets, compliance = [], [], []

        def run(name, worn):
            with patch.object(sync_topics, "profile_patched",
                              lambda c, b, a: patched.append((c, b, a))), \
                    patch("app.core.npc_assets.on_outfit_description_changed",
                          lambda n, o, w: assets.append((n, o, w))), \
                    patch("app.core.outfit_compliance.apply_outfit_compliance",
                          lambda n, **kw: compliance.append(n)):
                return set_outfit_worn(name, worn)

        def stored(name, key="outfit_worn"):
            return (ch.get_character_profile(name) or {}).get(key, "<missing>")

        print("[1] dressed temporary NPC is undressed")
        check("returns", run("npc a", False), True)
        check("stored", stored("npc a"), "false")
        check("profile_patched", patched,
              [("npc a", {"outfit_worn": "true"}, {"outfit_worn": "false"})])
        check("asset hook", assets, [("npc a", "wearing: grey apron", "no clothes")])
        check("compliance", compliance, ["npc a"])

        print("[2] already undressed: nothing happens")
        patched.clear(); assets.clear(); compliance.clear()
        check("returns", run("npc a", False), True)
        check("no signal", (patched, assets, compliance), ([], [], []))

        print("[3] bool shape of the NPC pipeline")
        profile = ch.get_character_profile("npc a")
        profile["outfit_worn"] = True
        with patch("app.core.npc_assets.on_outfit_description_changed", lambda *a: None):
            ch.save_character_profile("npc a", profile)
        check("returns", run("npc a", False), True)
        check("stored", stored("npc a"), "false")

        print("[4] dressed again")
        check("returns", run("npc a", True), True)
        check("stored", stored("npc a"), "true")

        print("[5] piece-based wardrobe is never touched")
        patched.clear(); assets.clear(); compliance.clear()
        check("returns", run("roleplay b", False), False)
        check("stored", stored("roleplay b"), "<missing>")
        check("no signal", (patched, compliance), ([], []))

        print("[6] unknown character")
        check("returns", run("nobody here", False), False)

        print("[7] failed save")
        patched.clear(); compliance.clear()
        with patch.object(ch, "save_character_profile", lambda *a, **k: False):
            check("returns", run("npc a", False), False)
        check("stored", stored("npc a"), "true")
        check("no signal", (patched, compliance), ([], []))

    print("FAIL: " + ", ".join(FAILS) if FAILS else "PASS: set_outfit_worn [1]-[7]")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
