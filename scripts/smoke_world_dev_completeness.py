#!/usr/bin/env python3
"""Smoke: World Dev free mode — completeness feedback and check_run (gap 8).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p1-characters.md, Task 9.
A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM. Every tool call goes through
``world_dev_tools.run_tool`` exactly as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_completeness.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The plugin registry is CLEARED and the FAKE species package of Task 3's smoke
is registered (scripts/smoke_world_dev_describe_template.py):

    id smoke_species, apply_to ["human-roleplay"], body_slots:
      hair         color  select [blonde, red], allow_custom
                   length select [short, long]
      facial_hair  applies_to gender=male; style select [short beard]

No character below is male, so the unset body attributes of an empty
character are exactly "hair.color, hair.length" (declaration order).
The package declares no clothing slots, so outfits use the core slots
(top, bottom, feet).

Locations stored directly before the runs (not by a run):
    H "Demo House" placed at (0, 0), P "Demo Park" placed at (50, 0),
    U "Demo Shed" without x/z.

The soul fields of human-roleplay (shared/templates/character/base-character.json
merged into human-roleplay.json, template field order): character_personality,
character_presence, character_task, character_soul, character_beliefs,
character_lessons, character_goals. Their default texts (the scaffold a new
character gets) hold only headings, except presence, whose two sections carry
an HTML comment as a writing hint — a comment is no content, so all seven
count as "without content". SOUL below = that list joined with ", ".

Run 1 (turn 1):
  (a) create_character{data: {name: "Demo Bare"}} -> the line ends with
        "; missing: no home — not in the world; no outfits; wears nothing;
        no daily schedule; soul sections without content: SOUL;
        body slots unset: hair.color, hair.length"
      (human-roleplay has a wardrobe, so "no outfits" and "wears nothing").
  (a') no "knows only its home": Demo Bare has no home, the precondition of
      that gap fails ("no home" already says it); "not placed" is absent for
      the same reason (it needs a home too).
  (b) Demo Full: home H, schedule [{0, sleep}, {10, P, role "walk"}], all
      seven soul fields with text, body_slots hair {color red, length long},
      2 outfits (Daily: top, bottom, feet; Night: a gown on top+bottom) ->
      "; complete". Placed at H (a NEW character is placed at its home,
      world_dev_apply._apply_home_and_schedule is_new), wears Daily (the
      first outfit), known places [H, P] (home + schedule place) — so not
      "knows only its home".
  (c) Demo Shedder with home U -> placed at U, known [U], so the line ends
        "; missing: home <U> is unplaced (no x/z); no outfits; wears nothing;
        no daily schedule; soul sections without content: SOUL;
        body slots unset: hair.color, hair.length; knows only its home"
  (d) create_location{data: {name: "Demo Mill"}} (no x/z) -> the line ends
      "; missing: unplaced (no x/z) — not a travel target"; place_location
      of it -> "; complete".
  (e) check_run{} -> exactly: the Demo Bare line, the Demo Shedder line
      ('character "<n>": missing: …' with the suffix lists of (a) and (c)),
      then "2 of 4 elements complete" (created: Demo Bare, Demo Full,
      Demo Shedder, Demo Mill; H, P, U pre-exist and were not touched).
      Its journal row is kind "read". check_run{x: 1} -> refused.

Run 2 (pre-existing hand-made Demo Hand, saved directly: human-roleplay,
no home, no schedule, no current location, one outfit "Daily" that is NOT
worn, scaffold soul sections, no body slots):
  (f) update_character{Demo Hand, {importance: 2}} -> "; complete": a config
      field is restore_character, which touches no gap group.
      update_character{Demo Hand, {home: H}} -> only the home group:
      _apply_home_and_schedule with is_new False never places anybody (only
      "if is_new and home") -> "not placed"; known_locations gains the home
      through add_known_location -> [H] -> "knows only its home"; no
      schedule -> "no daily schedule". So the line ends
        "; missing: not placed; no daily schedule; knows only its home"
      Never "wears nothing" (only for created characters), "no outfits",
      "soul sections" or "body slots" (groups the run did not touch).
      A later update_character{importance: 3} keeps the home group of the
      earlier call -> the same suffix.
  (g) update_location{U, {description}} -> "; complete": U was only updated
      and the run wrote no x/z for it (no restore_position).
  (h) check_run{} -> exactly
        'character "Demo Hand": missing: not placed; no daily schedule; knows only its home'
        "1 of 2 elements complete"   (Demo Hand and U; U complete under its scope)

Run 3 (hand-made Demo Loner: no home; Demo Homebody: config home_location H
saved directly, no known_locations; Demo Hand from run 2 knows [H]):
  (i) update_character{Demo Hand, {known_places: [H]}} -> H is already known,
      "known places unchanged"; the row's inverse names no id, so it widens
      no group -> "; complete" (before the fix: the home group's
      "not placed; no daily schedule; knows only its home"). It changed
      nothing, so Demo Hand is no element of run 3 at all.
  (j) update_character{Demo Loner, {known_places: [P]}} -> the "known" group
      only, which reports nothing but "knows only its home" and needs a home
      -> "; complete" (before: "no home — not in the world; no daily schedule").
  (k) update_character{Demo Homebody, {known_places: [H]}} -> H added, known
      [H] = only the home -> "; missing: knows only its home" (no "not placed",
      no "no daily schedule": the home group is not in scope).
  (l) turn 1 create_character{Demo Gone}; turn 2 delete_created{character,
      Demo Gone} (cross-turn: a done recreate_character row); then a
      hand-made "Demo Gone" saved directly. It is somebody else's (as
      discard_preview decides), its older rows widen nothing and the run
      changed nothing of it -> not listed, not counted.
  (m) check_run{} -> exactly
        'character "Demo Homebody": missing: knows only its home'
        "1 of 2 elements complete"   (Demo Loner — known places added, no
                                      home, so complete — and Demo Homebody;
                                      Demo Hand (i) and Demo Gone (l) are
                                      no elements)

Run 4 (same-turn delete and a no-op update):
  (n) turn 1 create_character{Demo Tmp}; update_character{Demo Tmp,
      {"soul:character_soul": "..."}} (a restore_soul row, which always counts);
      delete_created{character, Demo Tmp} in the SAME turn (the creating row
      is marked undone, the delete row has no inverse, the soul row stays
      live); then a hand-made "Demo Tmp" saved directly (scaffold soul).
      Before the fix the live soul row widened the scope to {soul} ->
      'character "Demo Tmp": missing: soul sections without content: SOUL'.
      Now the inverse-less done delete row resets it like a recreate_* row:
      Demo Tmp is no element.
  (o) update_character{Demo Full, {body_slots: {hair: {color: "red"}}}} —
      the value it already has -> the row's inverse names nothing changed
      ("before" empty) -> not an element; "; complete".
  (p) update_character{Demo Loner, {importance: 2}} -> a restore_character
      row (a real change, no gap group) -> counted, complete.
  (q) check_run{} -> exactly ["1 of 1 elements complete"] (only Demo Loner).

Run 5 (a no-op update alone):
  (r) update_character{Demo Loner, {importance: 2}} — the value (p) stored ->
      the restore_character row attaches empty profile/config maps (nothing
      changed) -> not an element; check_run{} -> exactly
      ["0 of 0 elements complete"].
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_compl_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_compl_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core.world_dev_apply import _apply_one_outfit  # noqa: E402
from app.core.world_ops import create_location_with_extras  # noqa: E402
from app.models.character import (get_character_outfits,  # noqa: E402
                                  save_character_profile)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.models.inventory import get_equipped_pieces  # noqa: E402
from app.models.world import update_location_position  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=STORAGE, manifest={}, apply_to=["human-roleplay"],
    body_slots=[
        BodySlotSpec(id="hair", package_id="smoke_species", attributes={
            "color": {"type": "select", "options": ["blonde", "red"], "allow_custom": True},
            "length": {"type": "select", "options": ["short", "long"]},
        }),
        BodySlotSpec(id="facial_hair", package_id="smoke_species",
                     applies_to={"gender": ["male"]}, attributes={
                         "style": {"type": "select", "options": ["short beard"]},
                     }),
    ]))
clear_template_cache()


def new_place(name, x=None, z=None):
    res = create_location_with_extras({"name": name, "rooms": [], "create_new": True})
    lid = str(res["location"]["id"])
    if x is not None:
        update_location_position(lid, x, z, None)
    return lid


H = new_place("Demo House", 0, 0)
P = new_place("Demo Park", 50, 0)
U = new_place("Demo Shed")

SOUL_KEYS = ["character_personality", "character_presence", "character_task",
             "character_soul", "character_beliefs", "character_lessons",
             "character_goals"]
SOUL = ", ".join(SOUL_KEYS)
BODY = "body slots unset: hair.color, hair.length"

run1 = wr.create_run("completeness 1", "m", "p", "u", 40, 300000)
ctx1 = wt.ToolCtx(run_id=run1, turn=1)


def call(ctx, name, args):
    return wt.run_tool(ctx, name, args)


# (a)
BARE = ("no home — not in the world; no outfits; wears nothing; no daily schedule; "
        f"soul sections without content: {SOUL}; {BODY}")
res = call(ctx1, "create_character", {"data": {"name": "Demo Bare"}})
check("(a) Demo Bare: full gap list", res.ok and res.line.endswith("; missing: " + BARE),
      res.line)
check("(a') no 'knows only its home' / 'not placed' without a home",
      "knows only its home" not in res.line and "not placed" not in res.line, res.line)

# (b)
OUTFITS = [
    {"name": "Daily", "pieces": [
        {"slots": ["top"], "name": "Demo Shirt", "prompt_fragment": "plain linen shirt"},
        {"slots": ["bottom"], "name": "Demo Trousers", "prompt_fragment": "brown trousers"},
        {"slots": ["feet"], "name": "Demo Boots", "prompt_fragment": "leather boots"}]},
    {"name": "Night", "pieces": [
        {"slots": ["top", "bottom"], "name": "Demo Gown", "prompt_fragment": "long gown"}]},
]
full_data = {"name": "Demo Full", "outfits": OUTFITS,
             "body_slots": {"hair": {"color": "red", "length": "long"}}}
for key in SOUL_KEYS:
    full_data[key] = f"Demo text of {key}."
res = call(ctx1, "create_character", {
    "data": full_data, "home": H,
    "schedule": [{"hour": 0, "sleep": True}, {"hour": 10, "location": P, "role": "walk"}]})
check("(b) Demo Full: complete", res.ok and res.line.endswith("; complete"), res.line)
check("(b) Demo Full wears its first outfit", bool(get_equipped_pieces("Demo Full")))

# (c)
SHEDDER = (f"home {U} is unplaced (no x/z); no outfits; wears nothing; no daily schedule; "
           f"soul sections without content: {SOUL}; {BODY}; knows only its home")
res = call(ctx1, "create_character", {"data": {"name": "Demo Shedder"}, "home": U})
check("(c) Demo Shedder: unplaced home", res.ok and f"home {U} is unplaced (no x/z)" in res.line,
      res.line)
check("(c) Demo Shedder: exact suffix", res.ok and res.line.endswith("; missing: " + SHEDDER),
      res.line)

# (d)
res = call(ctx1, "create_location", {"data": {"name": "Demo Mill"}})
check("(d) unplaced new location",
      res.ok and res.line.endswith("; missing: unplaced (no x/z) — not a travel target"),
      res.line)
mill = wr.entries(run1)[0]["target_id"]
res = call(ctx1, "place_location", {"id": mill, "x": 100, "z": 20})
check("(d) placed -> complete", res.ok and res.line.endswith("; complete"), res.line)

# (e)
res = call(ctx1, "check_run", {})
check("(e) check_run lines", res.ok and res.line.splitlines() == [
    f'character "Demo Bare": missing: {BARE}',
    f'character "Demo Shedder": missing: {SHEDDER}',
    "2 of 4 elements complete"], res.line)
check("(e) check_run is a read row", wr.steps(run1)[-1]["kind"] == "read",
      wr.steps(run1)[-1]["kind"])
res = call(ctx1, "check_run", {"x": 1})
check("(e) unknown argument refused", not res.ok and "x" in res.line, res.line)

# Run 2: a hand-made character and a pre-existing unplaced location.
check("setup: Demo Hand saved", save_character_profile(
    "Demo Hand", {"name": "Demo Hand", "template": "human-roleplay"}, create_new=True))
_apply_one_outfit("Demo Hand", {"name": "Daily", "pieces": [
    {"slots": ["top"], "name": "Demo Tunic", "prompt_fragment": "grey tunic"}]})
check("setup: Demo Hand has an outfit, wears nothing",
      len(get_character_outfits("Demo Hand")) == 1 and not get_equipped_pieces("Demo Hand"))

wr.set_status(run1, "accepted")
run2 = wr.create_run("completeness 2", "m", "p", "u", 40, 300000)
ctx2 = wt.ToolCtx(run_id=run2, turn=1)

# (f)
HAND = "not placed; no daily schedule; knows only its home"
res = call(ctx2, "update_character", {"name": "Demo Hand", "patch": {"importance": 2}})
check("(f) config-only update -> complete", res.ok and res.line.endswith("; complete"), res.line)
res = call(ctx2, "update_character", {"name": "Demo Hand", "patch": {"home": H}})
check("(f) home update -> home group only",
      res.ok and res.line.endswith("; missing: " + HAND), res.line)
for word in ("wears nothing", "no outfits", "soul sections", "body slots"):
    check(f"(f) never {word!r} for Demo Hand", word not in res.line, res.line)
res = call(ctx2, "update_character", {"name": "Demo Hand", "patch": {"importance": 3}})
check("(f) later update keeps the earlier call's group",
      res.ok and res.line.endswith("; missing: " + HAND), res.line)

# (g)
res = call(ctx2, "update_location", {"id": U, "patch": {"description": "A small shed."}})
check("(g) updated unplaced location -> complete",
      res.ok and res.line.endswith("; complete"), res.line)

# (h)
res = call(ctx2, "check_run", {})
check("(h) check_run of run 2", res.ok and res.line.splitlines() == [
    f'character "Demo Hand": missing: {HAND}', "1 of 2 elements complete"], res.line)

# Run 3
from app.models.character import get_character_config, save_character_config  # noqa: E402

check("setup: Demo Loner saved", save_character_profile(
    "Demo Loner", {"name": "Demo Loner", "template": "human-roleplay"}, create_new=True))
check("setup: Demo Homebody saved", save_character_profile(
    "Demo Homebody", {"name": "Demo Homebody", "template": "human-roleplay"}, create_new=True))
hb_cfg = dict(get_character_config("Demo Homebody") or {})
hb_cfg["home_location"] = H
hb_cfg.pop("known_locations", None)
check("setup: Demo Homebody home H, knows nothing",
      save_character_config("Demo Homebody", hb_cfg)
      and not (get_character_config("Demo Homebody") or {}).get("known_locations"))

wr.set_status(run2, "accepted")
run3 = wr.create_run("completeness 3", "m", "p", "u", 40, 300000)
ctx3 = wt.ToolCtx(run_id=run3, turn=1)

# (i)
res = call(ctx3, "update_character", {"name": "Demo Hand", "patch": {"known_places": [H]}})
check("(i) no-op known places -> complete",
      res.ok and "known places unchanged" in res.line and res.line.endswith("; complete"),
      res.line)

# (j)
res = call(ctx3, "update_character", {"name": "Demo Loner", "patch": {"known_places": [P]}})
check("(j) known places without a home -> complete",
      res.ok and res.line.endswith("; complete"), res.line)

# (k)
res = call(ctx3, "update_character", {"name": "Demo Homebody", "patch": {"known_places": [H]}})
check("(k) only the home known -> only that gap",
      res.ok and res.line.endswith("; missing: knows only its home"), res.line)

# (l)
res = call(ctx3, "create_character", {"data": {"name": "Demo Gone"}})
check("(l) Demo Gone created", res.ok, res.line)
res = call(wt.ToolCtx(run_id=run3, turn=2), "delete_created",
           {"kind": "character", "id": "Demo Gone"})
check("(l) Demo Gone deleted in turn 2", res.ok, res.line)
check("(l) hand-made Demo Gone saved", save_character_profile(
    "Demo Gone", {"name": "Demo Gone", "template": "human-roleplay"}, create_new=True))

# (m)
res = call(wt.ToolCtx(run_id=run3, turn=2), "check_run", {})
check("(m) check_run of run 3", res.ok and res.line.splitlines() == [
    'character "Demo Homebody": missing: knows only its home',
    "1 of 2 elements complete"], res.line)

# Run 4
wr.set_status(run3, "accepted")
run4 = wr.create_run("completeness 4", "m", "p", "u", 40, 300000)
ctx4 = wt.ToolCtx(run_id=run4, turn=1)

# (n)
res = call(ctx4, "create_character", {"data": {"name": "Demo Tmp"}})
check("(n) Demo Tmp created", res.ok, res.line)
res = call(ctx4, "update_character", {"name": "Demo Tmp",
                                      "patch": {"soul:character_soul": "Demo soul text."}})
check("(n) Demo Tmp soul written", res.ok, res.line)
check("(n) the soul row is restore_soul",
      (wr.entries(run4)[0].get("inverse") or {}).get("op") == "restore_soul",
      wr.entries(run4)[0].get("inverse"))
res = call(ctx4, "delete_created", {"kind": "character", "id": "Demo Tmp"})
check("(n) Demo Tmp deleted in the same turn", res.ok, res.line)
check("(n) hand-made Demo Tmp saved", save_character_profile(
    "Demo Tmp", {"name": "Demo Tmp", "template": "human-roleplay"}, create_new=True))

# (o)
res = call(ctx4, "update_character", {"name": "Demo Full",
                                      "patch": {"body_slots": {"hair": {"color": "red"}}}})
check("(o) unchanged body slot -> complete", res.ok and res.line.endswith("; complete"),
      res.line)

# (p)
res = call(ctx4, "update_character", {"name": "Demo Loner", "patch": {"importance": 2}})
check("(p) config update -> complete", res.ok and res.line.endswith("; complete"), res.line)

# (q)
res = call(ctx4, "check_run", {})
check("(q) check_run of run 4", res.ok and res.line.splitlines() == [
    "1 of 1 elements complete"], res.line)

# (r)
wr.set_status(run4, "accepted")
run5 = wr.create_run("completeness 5", "m", "p", "u", 40, 300000)
ctx5 = wt.ToolCtx(run_id=run5, turn=1)
res = call(ctx5, "update_character", {"name": "Demo Loner", "patch": {"importance": 2}})
check("(r) same importance -> ok, nothing changed",
      res.ok and "fields unchanged" in res.line, res.line)
check("(r) the row is restore_character with empty maps",
      (wr.entries(run5)[0].get("inverse") or {}) == {
          "op": "restore_character", "name": "Demo Loner", "profile": {}, "config": {}},
      wr.entries(run5)[0].get("inverse"))
res = call(ctx5, "check_run", {})
check("(r) check_run of run 5: no element", res.ok and res.line.splitlines() == [
    "0 of 0 elements complete"], res.line)

if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
    sys.exit(1)
print("smoke_world_dev_completeness: all checks passed")
