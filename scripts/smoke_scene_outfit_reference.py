"""Smoke: a scene that names its own outfit gets a reference image without
clothes (PromptBuilder._bare_reference_for_scene_outfit +
expression_regen.find_bare_expression).

Usage:
    ./.venv/bin/python scripts/smoke_scene_outfit_reference.py

Runs without the server and without a world DB: temp storage, the outfit
renderer, the mood and the expression lookup are stubbed.

Expected values, derived by hand from the user report (2026-11-01: Kira wore
blouse and skirt — the decency rule had just dressed her — when her photo
tool described a nude mirror scene "wearing a gold necklace"; the prompt said
nude, the reference was her expression render in blouse and skirt, and a
regenerate that keeps the source references dressed her):

Fixture: person 1 = Kira (agent), reference DRESSED.png, equipped pieces
render as "white blouse, short skirt"; her cached render without clothes is
BARE.png; mood "aroused".

A) Scene outfit "a gold necklace" lacks the equipped pieces -> reference
   BARE.png; the lookup got Kira's name and mood "aroused".
B) Scene outfit "white blouse, short skirt, heels" contains every equipped
   piece -> reference stays DRESSED.png, no lookup.
C) Nothing equipped (pieces "") -> stays, no lookup.
D) No render without clothes (lookup returns None) or the lookup raises
   ValueError -> stays DRESSED.png.
E) The user's avatar and a person without a reference -> unchanged.
F) find_bare_expression asks expression_snapshot for equipped_pieces={},
   equipped_items=[] with the mood, and hands that request to
   find_compatible_expression.
G) End to end through sanitize_scene_prompt: "Kira looking into a mirror,
   wearing a gold necklace" -> prompt_outfits[1] = "Kira is wearing a gold
   necklace" and reference BARE.png.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_scene_outfit_ref_")
os.environ["STORAGE_DIR"] = _tmp
os.environ["INSTANCE_DIR"] = _tmp

from app.core import paths  # noqa: E402
paths.init(_tmp)

import app.core.prompt_builder as pb  # noqa: E402
import app.core.expression_regen as er  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


state = {"pieces": "white blouse, short skirt", "bare": "/x/BARE.png", "raise": False}
lookups = []


def fake_find_bare(name, mood=""):
    lookups.append((name, mood))
    if state["raise"]:
        raise ValueError("no set")
    return state["bare"]


REAL_FIND_BARE = er.find_bare_expression
pb.render_outfit = lambda character_name="", **_kw: {"pieces": state["pieces"]}
pb.get_character_current_feeling = lambda name: "aroused"
er.find_bare_expression = fake_find_bare

builder = object.__new__(pb.PromptBuilder)
builder.character_name = "Kira"


def variables(user=False, ref="/x/DRESSED.png"):
    pv = pb.PromptVariables()
    pv.persons = [pb.Person(name="Kira", appearance="", gender="female", is_agent=not user, is_user=user)]
    if ref:
        pv.ref_images[1] = ref
    return pv


def run(scene, **kw):
    lookups.clear()
    pv = variables(**kw)
    builder._bare_reference_for_scene_outfit(pv, 1, scene)
    return pv.ref_images.get(1)


print("A) scene outfit differs")
check("reference without clothes", run("a gold necklace") == "/x/BARE.png")
check("lookup got name and mood", lookups == [("Kira", "aroused")], f"{lookups}")

print("B) scene wears the equipped outfit")
check("reference stays", run("white blouse, short skirt, heels") == "/x/DRESSED.png")
check("no lookup", lookups == [])

print("C) nothing equipped")
state["pieces"] = ""
check("reference stays", run("a gold necklace") == "/x/DRESSED.png")
check("no lookup", lookups == [])
state["pieces"] = "white blouse, short skirt"

print("D) no render without clothes")
state["bare"] = None
check("None -> reference stays", run("a gold necklace") == "/x/DRESSED.png")
state["bare"], state["raise"] = "/x/BARE.png", True
check("ValueError -> reference stays", run("a gold necklace") == "/x/DRESSED.png")
state["raise"] = False

print("E) avatar and missing reference")
check("user avatar unchanged", run("a gold necklace", user=True) == "/x/DRESSED.png")
check("no reference stays none", run("a gold necklace", ref="") is None)

print("F) find_bare_expression")
asked = {}
er.expression_snapshot = lambda character, mood="", **kw: asked.update(c=character, m=mood, **kw) or "REQ"
er.find_compatible_expression = lambda request: f"found:{request}"
result = REAL_FIND_BARE("Kira", "aroused")
check("asks for nothing equipped",
      asked == {"c": "Kira", "m": "aroused", "equipped_pieces": {}, "equipped_items": []}, f"{asked}")
check("returns the compatible lookup", result == "found:REQ", f"{result}")

print("G) end to end through sanitize_scene_prompt")
lookups.clear()
pv = variables()
pv.prompt_outfits[1] = "Kira is wearing white blouse, short skirt"
builder.sanitize_scene_prompt("Kira looking into a mirror, wearing a gold necklace", pv)
check("outfit replaced", pv.prompt_outfits.get(1) == "Kira is wearing a gold necklace",
      f"{pv.prompt_outfits}")
check("reference without clothes", pv.ref_images.get(1) == "/x/BARE.png", f"{pv.ref_images}")

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
