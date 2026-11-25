"""Smoke: a linked part is described exactly once, through its host (plan-anhaenger Task 7,
``accessory_parts.compose_text`` / ``host_mentions_part``, ``outfit_renderer.piece_text``).

Usage: ./.venv/bin/python scripts/smoke_part_prompt_text.py   (no server; a temp world and shared library)

Expected texts, by hand:

[1] "copper belt" + ["a copper oak-leaf buckle"] → "copper belt with a copper oak-leaf buckle".
[2] "gold necklace with gemstone pendant" + ["gemstone pendant"] → unchanged (the part text stands in the host).
[3] a belt with buckle P ("a copper oak-leaf buckle") and two charms on the same part Q ("a silver bell") →
    "copper belt with a copper oak-leaf buckle and a silver bell" (Q once) — through ``piece_text`` of the stored belt.
[4] "gold necklace with gemstone" + ["a gemstone pendant"] → "gold necklace with gemstone, a gemstone pendant" (no
    second "with"); ``host_mentions_part`` True ("gemstone").
[5] "gold necklace" + ["a gemstone pendant"] → "gold necklace with a gemstone pendant"; ``host_mentions_part`` False.
[6] "belt without buckle" + ["a bell"] → "belt without buckle with a bell" ("without" is not the word "with").
[7] a part with an empty text → the host text alone.
[8] ``render_outfit`` of a profile wearing the belt of [3] (slot outer): "a silver bell" stands in ``full`` exactly once,
    "a copper oak-leaf buckle" once; the part's own name never (it has no slot, it is no piece of its own).
[9] the LLM text (``for_llm``) carries the parts too: ``render_outfit(..., for_llm=True)["full"]`` has "a silver bell"
    once.
[10] a change of the part's ``prompt_fragment`` invalidates its host's renders: ``_invalidate_renders_for_item`` is
    called for "item_belt" (monkeypatched to record; the host once per change).
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="smoke_part_text_")
SHARED = Path(tempfile.mkdtemp(prefix="smoke_part_text_shared_"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_part_text_clips_")
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core import db  # noqa: E402

db.init_schema()
import app.models.inventory as inv  # noqa: E402

inv._get_shared_dir = lambda: SHARED
from app.core import accessory_parts as parts, outfit_renderer  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


c = parts.compose_text
check("[1]", c("copper belt", ["a copper oak-leaf buckle"]), "copper belt with a copper oak-leaf buckle")
check("[2]", c("gold necklace with gemstone pendant", ["gemstone pendant"]), "gold necklace with gemstone pendant")
check("[4]", c("gold necklace with gemstone", ["a gemstone pendant"]), "gold necklace with gemstone, a gemstone pendant")
check("[4] mentions", parts.host_mentions_part("gold necklace with gemstone", "a gemstone pendant"), True)
check("[5]", c("gold necklace", ["a gemstone pendant"]), "gold necklace with a gemstone pendant")
check("[5] mentions", parts.host_mentions_part("gold necklace", "a gemstone pendant"), False)
check("[6]", c("belt without buckle", ["a bell"]), "belt without buckle with a bell")
check("[7]", c("copper belt", [""]), "copper belt")


def part(item_id, name, text):
    inv.add_item(name, item_id=item_id, category="outfit_piece", prompt_fragment=text,
                 outfit_piece={"slots": [], "jewellery": {"kind": "charm"}})


part("item_p", "Oak Buckle", "a copper oak-leaf buckle")
part("item_q", "Bell Charm", "a silver bell")
inv.add_item("Copper Belt", item_id="item_belt", category="outfit_piece", prompt_fragment="copper belt",
             outfit_piece={"slots": ["outer"], "mesh_mode": "accessory",
                           "jewellery": {"kind": "belt", "buckle": {"item": "item_p"},
                                         "charms": [{"item": "item_q", "at": "left_hip"},
                                                    {"item": "item_q", "at": "right_hip"}]}})
belt = inv.get_item("item_belt")
check("[3] piece_text", outfit_renderer.piece_text(belt, "closed"),
      "copper belt with a copper oak-leaf buckle and a silver bell")

save_character_profile("demo", {"name": "demo", "equipped_pieces": {"outer": "item_belt"}}, create_new=True)
full = outfit_renderer.render_outfit(character_name="demo")["full"]
check("[8] bell once", full.count("a silver bell"), 1)
check("[8] buckle once", full.count("a copper oak-leaf buckle"), 1)
check("[8] no part name", ("Oak Buckle" in full, "Bell Charm" in full), (False, False))
full_llm = outfit_renderer.render_outfit(character_name="demo", for_llm=True)["full"]
check("[9] LLM text", full_llm.count("a silver bell"), 1)

CALLS = []
inv._invalidate_renders_for_item = lambda item_id, *a, **k: CALLS.append(item_id)
with inv.outfit_piece_lock("item_q"):
    inv.update_item("item_q", {"prompt_fragment": "a small silver bell"})
check("[10] host invalidated", CALLS.count("item_belt"), 1)

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
