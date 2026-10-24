#!/usr/bin/env python3
"""Smoke: World-Dev knows the species body slots (prompt + apply + patch).

Body details (hair, eyes, build, …) are not template fields — species packages
declare them as body slots, and the template only carries the empty
``body_editor`` section. World-Dev used to read nothing but template fields, so
the LLM never heard of the slots and every World-Dev character started with an
empty body editor.

A FAKE species package is registered (no dependency on the private packs):

    id smoke_species, apply_to ["human-roleplay"], body_slots:
      hair         color  select [blonde, red], allow_custom
                   length select [short, long]
                   lora   lora_select
      eyes         color  select [blue, green]
      facial_hair  applies_to gender=male; style select [short beard]
      chest        applies_to gender=male; no attributes

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (a) THE PROMPT BLOCK for ``human-roleplay``, line by line: every slot with at
      least one fillable attribute, the slot condition as "(only when …)",
      ``allow_custom`` as the extra note. ``lora`` is a ``lora_select`` and is
      left out; ``chest`` has no attribute at all and is left out:

          - `hair`:
            - `color`: one of: blonde | red (another short English value is allowed)
            - `length`: one of: short | long
          - `eyes`:
            - `color`: one of: blue | green
          - `facial_hair` (only when gender=male):
            - `style`: one of: short beard

      ``animal-default`` does not match ``apply_to`` → the block is "".
      An attribute condition {"attributes.type": ["vagina", None]} renders as
      " (only when type=vagina)": the prefix goes, the null entry is dropped
      (checked through ``_format_conditions`` directly).
      The block is part of ``_format_generable_fields_for_templates`` — that
      is what fills ``{generable_fields}`` in the character schema.

  (b) THE APPLY of a new female ``human-roleplay`` character with

          hair        {color: copper-red, length: medium, lora: x.safetensors}
          eyes        {color: amber}
          facial_hair {style: short beard}
          tail        {length: long}

      by hand: copper-red is custom but allowed → stored; medium is not in
      [short, long] and length has no allow_custom → skipped; lora is not
      offered → skipped; amber is not in [blue, green] → skipped (eyes stores
      nothing); facial_hair applies only to gender=male → skipped; tail is no
      slot → skipped. Stored: {"hair": {"color": "copper-red"}}, 5 warnings.

  (c) THE PROFILE PATCH with {age: 30, body_slots: {hair: {length: long}}}:
      the slot merges per attribute → {"hair": {"color": "copper-red",
      "length": "long"}}, age 30, applied_fields ["age", "body_slots"], no
      warning. A patch with ONLY body_slots {eyes: {color: green}} adds
      {"eyes": {"color": "green"}} and reports ["body_slots"].

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_body_slots.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="wd-bodyslots-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="wd-bodyslots-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402
from app.models.character import get_character_profile  # noqa: E402
from app.models.character_template import clear_template_cache  # noqa: E402
from app.routes.world_dev import (  # noqa: E402
    _apply_character_internal, _apply_profile_patch_data_sync,
    _format_body_slots_for_template, _format_conditions, _format_generable_fields_for_templates)

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"[{'OK' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"    want: {want!r}\n    got:  {got!r}")
        FAILS.append(label)


registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=STORAGE, manifest={}, apply_to=["human-roleplay"],
    body_slots=[
        BodySlotSpec(id="hair", package_id="smoke_species", attributes={
            "color": {"type": "select", "options": ["blonde", "red"], "allow_custom": True},
            "length": {"type": "select", "options": ["short", "long"]},
            "lora": {"type": "lora_select"},
        }),
        BodySlotSpec(id="eyes", package_id="smoke_species", attributes={
            "color": {"type": "select", "options": ["blue", "green"]},
        }),
        BodySlotSpec(id="facial_hair", package_id="smoke_species",
                     applies_to={"gender": ["male"]}, attributes={
                         "style": {"type": "select", "options": ["short beard"]},
                     }),
        BodySlotSpec(id="chest", package_id="smoke_species",
                     applies_to={"gender": ["male"]}, attributes={}),
    ]))
clear_template_cache()

# (a) prompt block
block = _format_body_slots_for_template("human-roleplay")
check("(a) slot lines", [line for line in block.splitlines() if line.startswith(("- ", "  - "))], [
    "- `hair`:",
    "  - `color`: one of: blonde | red (another short English value is allowed)",
    "  - `length`: one of: short | long",
    "- `eyes`:",
    "  - `color`: one of: blue | green",
    "- `facial_hair` (only when gender=male):",
    "  - `style`: one of: short beard",
])
check("(a) header", block.splitlines()[0], "### Body (`body_slots`, template `human-roleplay`)")
check("(a) animal-default has no block", _format_body_slots_for_template("animal-default"), "")
check("(a) attribute condition", _format_conditions({"attributes.type": ["vagina", None]}),
      " (only when type=vagina)")
check("(a) block is part of {generable_fields}",
      block in _format_generable_fields_for_templates("human-roleplay"), True)

# (b) apply of a new character
NAME = "Smoke Ylva"
result = _apply_character_internal({
    "character_name": NAME, "template": "human-roleplay", "gender": "female",
    "body_slots": {
        "hair": {"color": "copper-red", "length": "medium", "lora": "x.safetensors"},
        "eyes": {"color": "amber"},
        "facial_hair": {"style": "short beard"},
        "tail": {"length": "long"},
    },
}, created_by="smoke")
check("(b) stored slots", get_character_profile(NAME).get("body_slots"),
      {"hair": {"color": "copper-red"}})
check("(b) warning count", len(result["warnings"]), 5)

# (c) profile patch
patch = _apply_profile_patch_data_sync({"character_name": NAME, "fields": {
    "age": 30, "body_slots": {"hair": {"length": "long"}}}})
profile = get_character_profile(NAME)
check("(c) merged slot", profile.get("body_slots"),
      {"hair": {"color": "copper-red", "length": "long"}})
check("(c) age patched", profile.get("age"), 30)
check("(c) applied fields", patch["applied_fields"], ["age", "body_slots"])
check("(c) no warnings", patch["warnings"], [])
patch = _apply_profile_patch_data_sync({"character_name": NAME, "fields": {
    "body_slots": {"eyes": {"color": "green"}}}})
check("(c) body_slots-only patch", get_character_profile(NAME).get("body_slots"),
      {"hair": {"color": "copper-red", "length": "long"}, "eyes": {"color": "green"}})
check("(c) body_slots-only applied fields", patch["applied_fields"], ["body_slots"])

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
