#!/usr/bin/env python3
"""Expression images per outfit: one base image, every other expression edited from it.

Spec (2026-11-07, user decision after the Glut finding — a face-trained set
LoRA pulled the waist-up frame onto the face; with the LoRA-free neutral
image as the reference the frame held, and a short edit prompt gave the
stronger expressions):
  * the set's default member is the outfit's BASE image: full character
    prompt, the profile image as reference, never the set LoRA;
  * every other member is DERIVED: the base image is its only reference,
    the prompt is the `expression_edit` instruction + the member's prompt,
    and only the set LoRA applies;
  * on demand: a derived request renders the missing base first, in the
    same job — nothing is rendered ahead for every outfit;
  * applies to every set; a backend without a reference slot renders the
    derived expression from scratch (full prompt + set LoRA);
  * the Expressions tab shows one row per outfit, the base first.

Expected values, derived by hand from that spec (set "emote": default
"emote_neutral" "make the woman neutral", member "emote_happy" "make the
woman happy", member "emote_sad" "make the woman sad", LoRA
"emote_v2.safetensors" 0.8):
  A base contract == render_contract([], "make the woman neutral", f, p);
    happy contract == render_contract([emote 0.8], "make the woman happy",
    f, p, base=<base contract>); it differs from the same contract without
    base (the base is part of it).
  B empty cache, request "emote_happy" -> exactly 2 renders, in order:
    1. use case "expression", no reference image, set LoRAs [], no bare
       prompt (the base);
    2. use case "expression_edit", bare prompt "make the woman happy",
       set LoRAs [emote 0.8], reference image inside the character's
       model_refs directory, RGB, the base's transparent corner white.
  C the happy sidecar records base_file == the base image's name,
    base_sha256 == sha256 of the base bytes, expression_mode "edit";
    the base sidecar records expression_base True.
  D base cached, request "emote_sad" -> exactly 1 render (the edit).
  E forcing the base again with new bytes -> both derived images (happy,
    sad) are removed, the base stays: 3 images -> 1.
  F a backend without reference slot -> request "emote_happy" renders 1
    image (base cached) with use case "expression", no bare prompt, set
    LoRAs [emote 0.8], no reference image; sidecar expression_mode "full".
  G the inventory marks the base row is_base True, the derived False.

Usage: ./.venv/bin/python scripts/smoke_expression_base_chain.py
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = tempfile.TemporaryDirectory(prefix="expression-base-chain-")
STORAGE = Path(TMP.name)
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(STORAGE / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(STORAGE / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(STORAGE / "rig.fbx")
from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()
from app.core.expression_sets_migration import migrate_catalog_metadata  # noqa: E402
migrate_catalog_metadata()

from unittest.mock import patch  # noqa: E402
from PIL import Image  # noqa: E402
from app.core import expression_sets as es, expression_regen as er  # noqa: E402
from app.models.character import save_character_profile, get_character_profile  # noqa: E402

failures = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        failures.append(label)


es.replace_set("emote", {"label": "Emote", "default": "emote_neutral",
                         "members": ["emote_neutral", "emote_happy", "emote_sad"],
                         "lora": "emote_v2.safetensors", "lora_strength": 0.8,
                         "entries": {"emote_neutral": {"prompt": "make the woman neutral", "synonyms": ["neutral"]},
                                     "emote_happy": {"prompt": "make the woman happy", "synonyms": ["emote happy"]},
                                     "emote_sad": {"prompt": "make the woman sad", "synonyms": ["emote sad"]}}},
               store="world")
assert save_character_profile("demo", {"template": "human-roleplay", "face_appearance": "oval face",
                                       "expression_set": "emote"}, create_new=True)
EMOTE = [{"name": "emote_v2.safetensors", "strength": 0.8}]
calls = []
colour = {"base": (200, 30, 30, 255)}


def render(character, *, output_stem, **kw):
    ref = kw.get("reference_image")
    seen = {"use_case": kw.get("image_use_case"), "bare": kw.get("bare_prompt"),
            "loras": kw.get("expression_set_loras"), "ref": None}
    if ref is not None:
        with Image.open(ref) as im:
            seen["ref"] = {"path": Path(ref).resolve(), "mode": im.mode, "corner": im.getpixel((0, 0))}
    calls.append(seen)
    p = output_stem.with_suffix(".png")
    img = Image.new("RGBA", (8, 8), colour["base"] if ref is None else (10, 120, 10, 255))
    img.putpixel((0, 0), (0, 0, 0, 0))     # a matted, transparent corner
    img.save(p)
    p.with_suffix(".json").write_text(json.dumps({"prompt": kw.get("bare_prompt") or kw["expression_prompt"],
                                                  "equipped_pieces": kw["equipped_pieces"],
                                                  "equipped_items": kw["equipped_items"]}))
    return p


print("A contracts")
prof = get_character_profile("demo")
base_req = er.expression_snapshot("demo", "")
happy_req = er.expression_snapshot("demo", "emote_happy")
f = base_req.framing
check(base_req.is_base and base_req.contract == er.render_contract([], "make the woman neutral", f, prof),
      "the base contract has no LoRA")
check(not happy_req.is_base and happy_req.contract == er.render_contract(
    EMOTE, "make the woman happy", f, prof, base=base_req.contract), "the derived contract carries the base")
check(happy_req.contract != er.render_contract(EMOTE, "make the woman happy", f, prof),
      "the base is part of the derived contract")

with patch.object(er, "render_character_image", render), \
        patch.object(er, "_edit_reference_supported", lambda c: True):
    print("B empty cache: base first, then the edit")
    happy = er.generate_expression_image(happy_req)
    check(happy is not None and len(calls) == 2, f"2 renders ({len(calls)})")
    b, e = (calls + [{}, {}])[:2]
    check(b.get("use_case") == "expression" and b.get("ref") is None and b.get("loras") == [] and not b.get("bare"),
          f"1st render is the base ({b})")
    refs_dir = (STORAGE / "characters" / "demo" / "model_refs").resolve()
    check(e.get("use_case") == "expression_edit" and e.get("bare") == "make the woman happy"
          and e.get("loras") == EMOTE, f"2nd render is the edit with the set LoRA ({e.get('use_case')}, {e.get('loras')})")
    ref = e.get("ref") or {}
    check(bool(ref) and ref["path"].is_relative_to(refs_dir) and ref["mode"] == "RGB"
          and ref["corner"] == (255, 255, 255), f"the base is the reference, flattened onto white ({ref})")

    print("C provenance of the derived image")
    folder = er._get_expressions_dir("demo")
    base_img = er.get_cached_expression(base_req)
    meta = json.loads(happy.with_suffix(".json").read_text())
    check(base_img is not None and meta.get("base_file") == base_img.name
          and meta.get("base_sha256") == hashlib.sha256(base_img.read_bytes()).hexdigest()
          and meta.get("expression_mode") == "edit", "the derived sidecar records its base")
    check(json.loads(base_img.with_suffix(".json").read_text()).get("expression_base") is True,
          "the base sidecar is marked")

    print("D base cached: only the edit renders")
    calls.clear()
    sad = er.generate_expression_image(er.expression_snapshot("demo", "emote_sad"))
    check(sad is not None and len(calls) == 1 and calls[0]["use_case"] == "expression_edit", f"1 render ({len(calls)})")

    print("G inventory rows")
    rows = {r["expression_key"]: r for r in er.list_expressions("demo")}
    check(rows.get("emote_neutral", {}).get("is_base") is True
          and rows.get("emote_happy", {}).get("is_base") is False, "the base row is marked")

    print("E a new base drops the expressions edited from the old one")
    count = lambda: len([p for p in folder.iterdir() if p.suffix == ".png"])  # noqa: E731
    before = count()
    colour["base"] = (30, 30, 200, 255)
    er.generate_expression_image(er.expression_snapshot("demo", ""), force=True)
    check((before, count()) == (3, 1) and er.get_cached_expression(base_req) is not None,
          f"3 images -> 1, the base stays ({before} -> {count()})")

with patch.object(er, "render_character_image", render), \
        patch.object(er, "_edit_reference_supported", lambda c: False):
    print("F a backend without reference slot renders from scratch")
    calls.clear()
    happy = er.generate_expression_image(er.expression_snapshot("demo", "emote_happy"))
    c = (calls + [{}])[0]
    check(len(calls) == 1 and c.get("use_case") == "expression" and not c.get("bare")
          and c.get("loras") == EMOTE and c.get("ref") is None, f"full render with the set LoRA ({calls})")
    check(happy is not None and json.loads(happy.with_suffix(".json").read_text()).get("expression_mode") == "full",
          "the sidecar records the full render")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("PASS expression base image per outfit, every other expression edited from it")
