#!/usr/bin/env python3
"""Smoke: World Dev free mode — appearance fields require template placeholder leads.

A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_appearance_lead.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Template facts (shared/templates/character/human-roleplay.json):
  - character_appearance declares "lead": "{age} year old {gender}, "
  - face_appearance declares "lead": "{gender}, {age} years old, "
  - dialogue_style has no "lead"

Cases:
  (a) create_character with literal "man, around 46 years old, angular weathered face"
      in face_appearance -> refused, nothing created, refusal names the lead.
      Same for literal character_appearance -> refused, nothing created.
  (b) create_character with the exact leads for both fields -> accepted, stored.
  (c) update_character patch face_appearance without lead -> refused, stored
      value unchanged.
  (d) update_character patch character_appearance with correct lead -> accepted,
      stored value updated.
  (e) describe_template for human-roleplay contains both lead strings.
  (f) character_gaps reports "appearance without placeholders: face_appearance"
      for a stored literal value (full scope and scope {"appearance"}), and
      reports no appearance gap for a character with correct leads.
      Updating a field of a pre-existing character with a bad stored
      face_appearance puts "appearance" into its scope and reports the gap.
  (g) A template field without "lead" (dialogue_style) is unaffected by the check.
  (h) With the tracked `human` package enabled (plugins/human/plugin.yaml:
      hair "{length} {color} hair", eyes "{color} eyes", build "{height}, {type} build"),
      get_character with fields ["face_appearance", "body_slots"] prints
      "packages append to the image prompts (do not repeat in the appearance texts): ..."
      with "long gray hair", "brown eyes", and "; portrait: long gray hair, brown eyes".
      A character without any slot values prints no such line; requesting only a
      non-appearance field (dialogue_style) prints no such line.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_al_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_al_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)
paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.plugins.loader import discover_packages  # noqa: E402

discover_packages()

from app.core import world_dev_completeness as completeness  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.character import (character_row_exists,  # noqa: E402
                                  get_character_profile,
                                  save_character_profile)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


CHAR_LEAD = "{age} year old {gender}, "
FACE_LEAD = "{gender}, {age} years old, "

run = wr.create_run("appearance lead", "m", "p", "u", 40, 300000)


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


# ── (a) create_character with literal gender/age refused ──────────────────
res = call(1, "create_character", {"data": {
    "name": "Demo BadFace",
    "gender": "male",
    "age": 46,
    "face_appearance": "man, around 46 years old, angular weathered face",
}})
check("(a) literal face_appearance refused", not res.ok and not res.wrote, res)
check("(a) refusal names the face lead", FACE_LEAD in res.line, res.line)
check("(a) Demo BadFace not created", not character_row_exists("Demo BadFace"))

res = call(1, "create_character", {"data": {
    "name": "Demo BadChar",
    "gender": "male",
    "age": 46,
    "character_appearance": "46 year old man, broad shoulders, weathered hands",
}})
check("(a) literal character_appearance refused", not res.ok and not res.wrote, res)
check("(a) refusal names the character lead", CHAR_LEAD in res.line, res.line)
check("(a) Demo BadChar not created", not character_row_exists("Demo BadChar"))

# ── (b) create_character with correct leads accepted ──────────────────────
good_char = f"{CHAR_LEAD}weathered hands, upright posture"
good_face = f"{FACE_LEAD}angular weathered face, calm expression"
res = call(1, "create_character", {"data": {
    "name": "Demo Good",
    "gender": "male",
    "age": 46,
    "character_appearance": good_char,
    "face_appearance": good_face,
}})
check("(b) create with correct leads accepted", res.ok and res.wrote, res)
prof_good = get_character_profile("Demo Good") or {}
check("(b) character_appearance stored",
      prof_good.get("character_appearance") == good_char,
      prof_good.get("character_appearance"))
check("(b) face_appearance stored",
      prof_good.get("face_appearance") == good_face,
      prof_good.get("face_appearance"))

# ── (c) update_character face_appearance without lead refused ─────────────
res = call(2, "update_character", {
    "name": "Demo Good",
    "patch": {"face_appearance": "angular weathered face, faint scar"},
})
check("(c) update face without lead refused", not res.ok and not res.wrote, res)
check("(c) refusal names face lead", FACE_LEAD in res.line, res.line)
check("(c) stored face_appearance unchanged",
      (get_character_profile("Demo Good") or {}).get("face_appearance") == good_face,
      (get_character_profile("Demo Good") or {}).get("face_appearance"))

# ── (d) update_character character_appearance with correct lead accepted ──
updated_char = f"{CHAR_LEAD}narrow shoulders, calloused palms"
res = call(2, "update_character", {
    "name": "Demo Good",
    "patch": {"character_appearance": updated_char},
})
check("(d) update character_appearance with lead accepted", res.ok and res.wrote, res)
check("(d) stored character_appearance updated",
      (get_character_profile("Demo Good") or {}).get("character_appearance") == updated_char,
      (get_character_profile("Demo Good") or {}).get("character_appearance"))

# ── (e) describe_template contains both lead strings ──────────────────────
res = call(2, "describe_template", {"template": "human-roleplay", "gender": "male"})
check("(e) describe_template ok", res.ok, res.line[:200])
check("(e) describe_template shows character_appearance lead",
      f'starts with "{CHAR_LEAD}"' in res.line, res.line)
check("(e) describe_template shows face_appearance lead",
      f'starts with "{FACE_LEAD}"' in res.line, res.line)

# ── (f) character_gaps checks stored appearance fields ────────────────────
check("(f) Demo Good has no appearance gap (full scope)",
      not any("appearance without placeholders" in g
              for g in completeness.character_gaps("Demo Good")),
      completeness.character_gaps("Demo Good"))
check("(f) Demo Good has no appearance gap (appearance scope)",
      completeness.character_gaps("Demo Good", {"appearance"}) == [],
      completeness.character_gaps("Demo Good", {"appearance"}))

save_character_profile("Demo Legacy", {
    "name": "Demo Legacy",
    "template": "human-roleplay",
    "gender": "male",
    "age": 50,
    "character_appearance": f"{CHAR_LEAD}upright posture",
    "face_appearance": "man, around 50 years old, square jaw",
}, create_new=True)
gaps_full = completeness.character_gaps("Demo Legacy")
check("(f) character_gaps full scope reports face_appearance",
      "appearance without placeholders: face_appearance" in gaps_full, gaps_full)
gaps_scoped = completeness.character_gaps("Demo Legacy", {"appearance"})
check("(f) character_gaps appearance scope reports face_appearance",
      gaps_scoped == ["appearance without placeholders: face_appearance"], gaps_scoped)

res = call(3, "update_character", {
    "name": "Demo Legacy",
    "patch": {"importance": 2},
})
check("(f) update_character on legacy char puts appearance in scope",
      res.ok and "appearance without placeholders: face_appearance" in res.line, res.line)

# ── (g) template field without lead is unaffected ─────────────────────────
res = call(3, "update_character", {
    "name": "Demo Good",
    "patch": {"dialogue_style": "short, dry, never raises his voice"},
})
check("(g) field without lead accepted", res.ok and res.wrote, res)
check("(g) dialogue_style stored",
      (get_character_profile("Demo Good") or {}).get("dialogue_style")
      == "short, dry, never raises his voice",
      (get_character_profile("Demo Good") or {}).get("dialogue_style"))

# ── (h) get_character shows package-appended image-prompt fragments ───────
res = call(4, "get_character", {
    "name": "Demo Good",
    "fields": ["face_appearance", "body_slots"],
})
check("(h) no slot values -> no packages-append line",
      res.ok and "packages append to the image prompts" not in res.line, res.line)

res = call(4, "create_character", {"data": {
    "name": "Demo Slotted",
    "gender": "male",
    "age": 46,
    "character_appearance": f"{CHAR_LEAD}upright posture",
    "face_appearance": f"{FACE_LEAD}angular weathered face",
    "body_slots": {
        "hair": {"length": "long", "color": "gray"},
        "eyes": {"color": "brown"},
        "build": {"type": "athletic"},
    },
}})
check("(h) Demo Slotted created", res.ok and res.wrote, res)

res = call(4, "get_character", {
    "name": "Demo Slotted",
    "fields": ["face_appearance", "body_slots"],
})
check("(h) slotted get_character contains packages-append line",
      res.ok and "packages append to the image prompts" in res.line, res.line)
check("(h) rendered hair fragment 'long gray hair' shown",
      "long gray hair" in res.line, res.line)
check("(h) rendered eyes fragment 'brown eyes' shown",
      "brown eyes" in res.line, res.line)
check("(h) portrait suffix shown when full and face differ",
      "; portrait: long gray hair, brown eyes" in res.line, res.line)

res = call(4, "get_character", {
    "name": "Demo Slotted",
    "fields": ["dialogue_style"],
})
check("(h) unrelated field read omits packages-append line",
      res.ok and "packages append to the image prompts" not in res.line, res.line)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all ok")
