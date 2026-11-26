#!/usr/bin/env python3
"""Smoke: World Dev free mode sets every body attribute the character editor
shows; the mesh-part switch is listed and settable only on the base-body
pipeline (gap C2).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-complete-characters-budget.md,
Task 3. A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_body_editor_attrs.py

A FAKE species package (no dependency on the private packs), declaration
order kept:

    id smoke_species, apply_to ["human-roleplay"], body_slots:
      chest  applies_to gender=female;
             size   select [small, medium, large], allow_custom, llm_generable: false
      hair   color  select [blonde, red], allow_custom
             lora   lora_select
      part   type   select [a, b]
             size   select [s, m], llm_generable: false
             extra  select [x, y], llm_generable: false,
                    applies_to {attributes.type: [a, null]}
             switch select ["off", "on"]
             mesh_part {switch: switch}

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The body line format is derived from ``world_dev_tools._body_schema``: per
slot ``f"{spec.id}: "`` + the applicable attributes joined by ``"; "``, each
``f"{key}={cur} [{takes}]"``, ``cur`` = the stored value or ``"-"``, ``takes``
= ``"|".join(options)`` + ``"|other"`` when ``allow_custom`` (``"text"``
without options). The editor's set = every attribute except ``lora_select``
(``body_slots.editable_attributes``); the switch only on the base-body
pipeline (a humanoid, non-temporary character — human-roleplay is humanoid
through base-character.json ``features.humanoid: true``).

  (a) describe_template{template: "human-roleplay", gender: "female"}, body
      lines in declaration order:
        chest: size=- [small|medium|large|other]
        hair: color=- [blonde|red|other]                 (no lora)
        part: type=- [a|b]; size=- [s|m]; extra=- [x|y]; switch=- [off|on]
      (extra is shown: type unset = null matches [a, null]). On 8962e4d04 the
      chest line was missing (its only attribute is llm_generable: false) and
      the part line was "part: type=- [a|b]".
  (b) create_character "Demo Chest" (female) with body_slots
      {chest: {size: medium}, part: {type: a, size: m, extra: y}} -> ok,
      profile.body_slots == exactly those four values, the result line
      carries no "skipped" warning. On 8962e4d04 chest.size was refused
      "attribute 'size' cannot be set here".
  (b') create_character "Demo Switch" (female) with body_slots
      {part: {switch: on}} ON the pipeline -> ok, stored {part: {switch: on}},
      figure.invalidate was called exactly once during the create
      (apply_character -> apply_body_slot_values: switch changed from absent
      to "on", on the pipeline) and the mesh-part thread counter stays 0
      (a build is the Figure tab's job). Off the pipeline
      (is_base_pipeline -> False), create_character "Demo Switch Off" with
      the same body_slots -> refused, the line ends with the pipeline text of
      (d), the newest journal row is kind "refused", the write-row count is
      unchanged and character_exists("Demo Switch Off") is False (the draft-name
      branch of the pipeline check refuses before any claim).
  (d') ON the pipeline (Demo Chest after (b)): the full-scope completeness
      gap is "body slots unset: hair.color, part.switch" (chest.size,
      part.type/size/extra are set; lora is no editor attribute here).
  (c) turn 2: update_character{Demo Chest, body_slots: {part: {switch: on}}}
      -> ok, stored "on", the newest write row's inverse is
      restore_body_slots with before {part: {switch: ABSENT}};
      figure.invalidate (monkeypatched counter) was called exactly once
      during the call (apply_body_slot_values: switch changed, on the
      pipeline). discard_preview is EXACTLY the two created-character lines
      (oldest first, no "changed since" line — the body-slot row is put back
      on a character the discard deletes anyway, so it gets no line of its
      own): 'character "Demo Chest" — 0 chat messages, 0 memory rows of
      other characters name it' and the same for "Demo Switch" (no chat,
      no memories, no outfit pieces, so no pieces suffix; "Demo Switch Off"
      was never created). undo(run, turn=2) -> complete, part.switch gone (the
      other part values stay), the counter is +1 (the undo's own invalidate).
  (d) off the pipeline (base_body.is_base_pipeline monkeypatched to False):
      turn 3: update_character{Demo Chest, body_slots: {part: {switch: on}}}
      -> refused, the line ends "body_slots.part.switch switches a separately
      built part — only for a character on the base-body pipeline"; the
      newest journal row is kind "refused", the number of write rows is
      unchanged, the profile is unchanged,
      character_ops._schedule_mesh_part_regeneration (counter) was never
      called.
  (d') still off the pipeline: describe_template's part line is
        part: type=- [a|b]; size=- [s|m]; extra=- [x|y]
      get_character{fields: ["body_slots"]} of Demo Chest shows
        part: type=a [a|b]; size=m [s|m]; extra=y [x|y]
      and the completeness gap reads "body slots unset: hair.color" (never
      part.switch).
  (e) update_character{Demo Chest, body_slots: {hair: {lora: x}}} -> refused
      "attribute 'lora' cannot be set here" (unchanged).
  (f) the temp-NPC path keeps llm_fillable_attributes: see
      smoke_world_dev_body_slots.py (green without edits).
  (g) discard_preview agrees with undo (phase review): "Demo Pre" saved
      directly (NOT by the run) with body_slots {part: {type: b}}; turn 5:
      update_character{part: {switch: on}} -> ok. discard_preview has no line
      naming Demo Pre (the value still is what the step wrote; a body slot put
      back is no line). The smoke then stores switch "off" from outside (under
      the profile lock): discard_preview names Demo Pre in exactly one line,
        body slots part.switch of "Demo Pre" were changed since — the discard leaves them alone
      (_body_slot_preview_lines, mirroring _undo_restore_body_slots: "off" !=
      written "on"); undo(run, turn=5) skips exactly that entry with reason
      REASON_CHANGED and key body_slots.part.switch, and the profile keeps
      {part: {type: b, switch: off}}. Before the fix discard_preview had no
      line at all for it.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_bea_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_bea_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import config, db  # noqa: E402

config.load(paths.get_config_path())
db.init_schema()

from app.core import base_body, character_ops, figure  # noqa: E402
from app.core import world_dev_completeness as wc  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models.character import (character_exists, get_character_profile,  # noqa: E402
                                  save_character_profile)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, MeshPartSpec, Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


# The skill manager loads (and re-registers) the packages on its first use;
# the completeness line of a character write asks it for the skill groups
# (plan 2026-11-25-world-dev-free-complete-characters-budget, Task 5), so it
# is loaded before the fake package is registered.
from app.core.dependencies import get_skill_manager  # noqa: E402

get_skill_manager()
registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=STORAGE, manifest={}, apply_to=["human-roleplay"],
    body_slots=[
        BodySlotSpec(id="chest", package_id="smoke_species",
                     applies_to={"gender": ["female"]}, attributes={
                         "size": {"type": "select", "options": ["small", "medium", "large"],
                                  "allow_custom": True, "llm_generable": False}}),
        BodySlotSpec(id="hair", package_id="smoke_species", attributes={
            "color": {"type": "select", "options": ["blonde", "red"], "allow_custom": True},
            "lora": {"type": "lora_select"}}),
        BodySlotSpec(id="part", package_id="smoke_species", attributes={
            "type": {"type": "select", "options": ["a", "b"]},
            "size": {"type": "select", "options": ["s", "m"], "llm_generable": False},
            "extra": {"type": "select", "options": ["x", "y"], "llm_generable": False,
                      "applies_to": {"attributes.type": ["a", None]}},
            "switch": {"type": "select", "options": ["off", "on"]}},
            mesh_part=MeshPartSpec(switch="switch", tpose_prompt="", lora_patterns=[],
                                   rigs={})),
    ]))
clear_template_cache()

invalidations = [0]
_real_invalidate = figure.invalidate


def _count_invalidate():
    invalidations[0] += 1
    _real_invalidate()


figure.invalidate = _count_invalidate
scheduled = []
character_ops._schedule_mesh_part_regeneration = lambda name: scheduled.append(name)

run = wr.create_run("body editor attrs", "m", "p", "u", 40, 300000)
NAME = "Demo Chest"


def call(turn, tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=turn), tool, args)


def slots():
    return (get_character_profile(NAME) or {}).get("body_slots")


def body_gap():
    return next((g for g in wc.character_gaps(NAME) if g.startswith("body slots unset")), None)


def write_rows():
    return [s for s in wr.steps(run) if s["kind"] == "write"]


CHEST = "chest: size=- [small|medium|large|other]"
HAIR = "hair: color=- [blonde|red|other]"
PART_ON = "part: type=- [a|b]; size=- [s|m]; extra=- [x|y]; switch=- [off|on]"
PART_OFF = "part: type=- [a|b]; size=- [s|m]; extra=- [x|y]"

# ── (a) ────────────────────────────────────────────────────────────────
res = call(1, "describe_template", {"template": "human-roleplay", "gender": "female"})
lines = res.line.splitlines() if res.ok else []
check("(a) describe ok", res.ok, res.line[:300])
check("(a) chest line", CHEST in lines, lines[:8])
check("(a) hair line without lora", HAIR in lines, lines[:8])
check("(a) part line with the switch", PART_ON in lines, lines[:8])
check("(a) slot order chest, hair, part",
      [ln.split(":")[0] for ln in lines if ln.split(":")[0] in ("chest", "hair", "part")]
      == ["chest", "hair", "part"], lines[:8])

# ── (b) ────────────────────────────────────────────────────────────────
res = call(1, "create_character", {"data": {
    "name": NAME, "gender": "female",
    "body_slots": {"chest": {"size": "medium"},
                   "part": {"type": "a", "size": "m", "extra": "y"}}}})
check("(b) create ok", res.ok and res.wrote, res.line)
check("(b) stored exactly the four values", slots() == {
    "chest": {"size": "medium"}, "part": {"type": "a", "size": "m", "extra": "y"}}, slots())
check("(b) no skipped warning", "skipped" not in res.line, res.line)

# ── (b') create with the switch ───────────────────────────────────────
PIPELINE_TEXT = ("body_slots.part.switch switches a separately built part — only for a "
                 "character on the base-body pipeline")
n0 = invalidations[0]
res = call(1, "create_character", {"data": {
    "name": "Demo Switch", "gender": "female",
    "body_slots": {"part": {"switch": "on"}}}})
check("(b') create with the switch ok", res.ok and res.wrote, res.line)
check("(b') stored the switch",
      (get_character_profile("Demo Switch") or {}).get("body_slots")
      == {"part": {"switch": "on"}},
      (get_character_profile("Demo Switch") or {}).get("body_slots"))
check("(b') figure.invalidate once", invalidations[0] - n0 == 1, invalidations[0] - n0)
check("(b') no mesh thread", scheduled == [], scheduled)
_real_pipeline_b = base_body.is_base_pipeline
base_body.is_base_pipeline = lambda *a, **k: False
try:
    n_writes = len(write_rows())
    res = call(1, "create_character", {"data": {
        "name": "Demo Switch Off", "gender": "female",
        "body_slots": {"part": {"switch": "on"}}}})
    check("(b') off the pipeline: create refused", not res.ok and not res.wrote, res.line)
    check("(b') off the pipeline: refusal text", res.line.endswith(PIPELINE_TEXT), res.line)
    check("(b') off the pipeline: newest row refused",
          wr.steps(run)[-1]["kind"] == "refused", wr.steps(run)[-1]["kind"])
    check("(b') off the pipeline: no write row", len(write_rows()) == n_writes,
          len(write_rows()))
    check("(b') off the pipeline: no character", not character_exists("Demo Switch Off"),
          character_exists("Demo Switch Off"))
finally:
    base_body.is_base_pipeline = _real_pipeline_b

# ── (d') on the pipeline ───────────────────────────────────────────────
check("(d') on the pipeline: gap lists part.switch",
      body_gap() == "body slots unset: hair.color, part.switch", body_gap())

# ── (c) ────────────────────────────────────────────────────────────────
n0 = invalidations[0]
res = call(2, "update_character", {"name": NAME,
                                   "patch": {"body_slots": {"part": {"switch": "on"}}}})
check("(c) update ok", res.ok and res.wrote, res.line)
check("(c) stored on", (slots() or {}).get("part", {}).get("switch") == "on", slots())
inv = (write_rows()[-1].get("inverse") or {})
check("(c) inverse restore_body_slots",
      inv.get("op") == "restore_body_slots" and list(inv.get("before") or {}) == ["part"]
      and list(inv["before"]["part"]) == ["switch"]
      and wu.is_absent(inv["before"]["part"]["switch"]), inv)
check("(c) figure.invalidate once", invalidations[0] - n0 == 1, invalidations[0] - n0)
check("(c) no mesh thread", scheduled == [], scheduled)
prev = wu.discard_preview(run)
check("(c) discard_preview: nothing changed since",
      not any("changed since" in ln for ln in prev), prev)
check("(c) discard_preview: exactly the two created characters", prev == [
    'character "Demo Chest" — 0 chat messages, 0 memory rows of other characters name it',
    'character "Demo Switch" — 0 chat messages, 0 memory rows of other characters name it',
], prev)
n1 = invalidations[0]
rep = wu.undo(run, turn=2)
check("(c) undo complete", rep["complete"], rep)
check("(c) switch gone, the rest stays", slots() == {
    "chest": {"size": "medium"}, "part": {"type": "a", "size": "m", "extra": "y"}}, slots())
check("(c) undo invalidated the figure once", invalidations[0] - n1 == 1,
      invalidations[0] - n1)

# ── (d) off the pipeline ───────────────────────────────────────────────
_real_pipeline = base_body.is_base_pipeline
base_body.is_base_pipeline = lambda *a, **k: False
try:
    before = slots()
    n_writes = len(write_rows())
    res = call(3, "update_character", {"name": NAME,
                                       "patch": {"body_slots": {"part": {"switch": "on"}}}})
    check("(d) refused", not res.ok and not res.wrote, res.line)
    check("(d) refusal text", res.line.endswith(
        "body_slots.part.switch switches a separately built part — only for a "
        "character on the base-body pipeline"), res.line)
    check("(d) newest row refused", wr.steps(run)[-1]["kind"] == "refused",
          wr.steps(run)[-1]["kind"])
    check("(d) no write row", len(write_rows()) == n_writes, len(write_rows()))
    check("(d) profile unchanged", slots() == before, slots())
    check("(d) no mesh thread", scheduled == [], scheduled)
    # ── (d') off the pipeline ──────────────────────────────────────────
    res = call(3, "describe_template", {"template": "human-roleplay", "gender": "female"})
    lines = res.line.splitlines() if res.ok else []
    check("(d') describe: part without the switch", PART_OFF in lines, lines[:8])
    res = call(3, "get_character", {"name": NAME, "fields": ["body_slots"]})
    check("(d') get_character: part without the switch",
          "part: type=a [a|b]; size=m [s|m]; extra=y [x|y]" in res.line.splitlines(),
          res.line)
    check("(d') gap never names part.switch",
          body_gap() == "body slots unset: hair.color", body_gap())
finally:
    base_body.is_base_pipeline = _real_pipeline

# ── (e) ────────────────────────────────────────────────────────────────
res = call(4, "update_character", {"name": NAME,
                                   "patch": {"body_slots": {"hair": {"lora": "x"}}}})
check("(e) lora refused", not res.ok and "attribute 'lora' cannot be set here" in res.line,
      res.line)

# ── (g) discard_preview agrees with undo on an outside change ──────────
PRE = "Demo Pre"
check("(g) setup: Demo Pre saved", save_character_profile(
    PRE, {"name": PRE, "template": "human-roleplay", "gender": "female",
          "body_slots": {"part": {"type": "b"}}}, create_new=True))
res = call(5, "update_character", {"name": PRE,
                                   "patch": {"body_slots": {"part": {"switch": "on"}}}})
check("(g) update ok", res.ok and res.wrote, res.line)
prev = wu.discard_preview(run)
check("(g) unchanged since: no body-slot line",
      not any(PRE in ln for ln in prev), prev)
with keyed_lock("character_profile", PRE):
    prof = get_character_profile(PRE)
    prof["body_slots"]["part"]["switch"] = "off"
    check("(g) outside change stored", save_character_profile(PRE, prof))
LINE_G = ('body slots part.switch of "Demo Pre" were changed since — the discard '
          "leaves them alone")
prev = wu.discard_preview(run)
check("(g) discard_preview: exactly one changed-since line for Demo Pre",
      [ln for ln in prev if PRE in ln] == [LINE_G], prev)
rep = wu.undo(run, turn=5)
skipped = rep.get("skipped") or []
check("(g) undo skips it as changed since",
      len(skipped) == 1 and skipped[0].get("reason") == wu.REASON_CHANGED
      and "body_slots.part.switch" in (skipped[0].get("keys") or []), rep)
check("(g) the outside value stays",
      (get_character_profile(PRE) or {}).get("body_slots") == {
          "part": {"type": "b", "switch": "off"}},
      (get_character_profile(PRE) or {}).get("body_slots"))

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("\nALL OK")
