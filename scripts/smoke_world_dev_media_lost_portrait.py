#!/usr/bin/env python3
"""Smoke: World Dev free mode — a stopped media row never loses a portrait;
a missing portrait / base body makes its step due (plan
docs/superpowers/plans/2026-11-25-world-dev-free-complete-characters-budget.md,
Task 6, gap C4).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render: get_image_service raises,
the media producers are stubs in world_dev_media.PRODUCERS, step_gate is
stubbed open. The REAL TaskQueue of the temp world is used with its workers
NOT started (_started set): the lane handler run_lane is called directly.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_lost_portrait.py

FIXTURE
-------
One fake species for "human-roleplay": piece slot "top" and ONE body slot
"eyes" (attribute color) WITHOUT a mesh item — so no character here has the
hairstyle step (world_dev_media._hairstyle_fp: no hair slot -> ""). Every
character is a humanoid human-roleplay character, which is on the base-body
pipeline in a temp world (base_body.is_base_pipeline: every humanoid that is
no temporary NPC), so its steps (world_dev_media._character_steps) are, in
order, exactly ["portrait", "build"].

Stubs: the portrait producer writes images/<name>_p<k>.png (k = 1, 2, ... per
character) through the real capture (_captured, roots [images], profile
keys) and calls set_character_profile_image; the build producer returns
("built", []) and writes nothing. A temp world has no stored base front, so
base_body.base_refresh_plan(missing=True) answers reason "missing" for every
character — the base body is ABSENT unless a case patches
world_dev_media._base_body_present.

STEP 0 — THE LIVE SEQUENCE (run wdr_8aab11858c36, main.log 13:46:27-13:50:08):
turn 1 cut by its budget -> turn-end schedule -> the lane runs Torvald's row
(hairstyle 13:48:26, portrait render started) -> turn 2 starts at 13:49:06
(cancel_queued flags the RUNNING row) -> the portrait lands at 13:49:11
("Set as profile image: Torvald_..._1.png") -> the row stops after that step
(cancelled, build not run) -> turn 2 writes other characters -> turn-2 end
schedule -> Accept 13:50:08. Replayed below with stubs (a)-(c), recording
profile_image, the image file, the row and plan() at each stage.

Finding (which link loses the portrait on 8962e4d04): NO link of the lane or
the run lifecycle does. After the stopped row (b) profile_image names the
new file and the file exists; the cancelled row keeps its portrait step
"done" with its artefacts (_stop_flagged_locked "cancel" removes nothing);
the turn-2 write of another character, the turn-2-end plan, the lane's next
row and finish_accepted_run (Accept removes nothing, releases without a
replay) leave both untouched — the stage checks of (b), (c) and (c') hold on
8962e4d04 as well. The live image file is still on disk
(characters/Torvald/images/Torvald_1795697351_1b366ae3_1.png, listed
read-only), so what the live world lost is the profile_image KEY (or the
character read no portrait for another reason outside the lane); the live
world DB is off limits here, so that cause is not pinned. The defect of the
lane itself is the plan rule: a step a stopped row finished counted as
"held" for good, so plan() never offered the portrait again once its output
was gone — and an element the run touched without changing the face prompt
(Ragna, never rendered) was never due at all. The fix (decision 12) makes a
finished step hold only while its output is present, which covers both a
lost profile key (d1) and a removed file (d2).

CASES (expected values by hand)
-------------------------------
  (a) run 1, turn 1 creates "Demo Torvald" -> element_steps ids
      ["portrait", "build"]; in review schedule -> one row whose step ids are
      ["portrait", "build"] (created: NULL baseline, every step due).
  (b) run_lane: inside the portrait stub (before it returns) the smoke starts
      turn 2 (status running, next_turn) and calls cancel_queued(run,
      "turn 2 started") -> the row ends "cancelled", portrait step "done",
      build step still "queued" (never run: one portrait call, no build
      call); profile_image == "Demo Torvald_p1.png" and that file exists.
  (c) turn 2 creates "Demo Other" only; in review plan() for Demo Torvald ==
      ["build"] (portrait: done + present -> held; build: never ran). On
      8962e4d04 the same ["build"] — plan alone is not the loss.
  (d) the portrait output disappears, each way from the (c) state and put
      back afterwards: (d1) profile_image "" -> ["portrait", "build"];
      (d2) the image file moved away, key kept -> ["portrait", "build"].
      On 8962e4d04 both give ["build"] (the loss stays).
  (e) with profile_image "" a QUEUED row of the run holding "portrait" with
      the current fp (in flight, not yet run) -> plan() == ["build"]: an
      in-flight step is never planned again. The row put "removed" -> back
      to ["portrait", "build"] (a removed row holds nothing).
  (g) a DONE row holding "build" with the current fp: _base_body_present
      patched False -> "build" due (["build"] with the portrait present);
      True -> [] (Demo Torvald not in the plan at all).
  (c') the rest of the live sequence: turn-2-end schedule -> rows for Demo
      Torvald (["build"]) and Demo Other (["portrait", "build"]); run_lane
      runs both (Demo Other's portrait = "Demo Other_p1.png"); Accept
      (finish_accepted_run + status accepted) -> Demo Torvald's profile_image
      is still "Demo Torvald_p1.png" and the file exists.
  (f) run 2: "Demo Ragna" saved OUTSIDE the run with no profile image; the
      run adds one outfit (update_character outfits) — the face prompt is
      unchanged, so the baseline portrait fp equals the current one ->
      plan() == ["portrait", "build"] (portrait: not present; build: base
      body absent). On 8962e4d04 only ["build"] (the outfit changes the
      wanted figure; the portrait fp is unchanged and nothing checked its
      output).
  (h) "only checked": "Demo Sigrun" saved OUTSIDE any run, no profile image,
      _base_body_present patched False. Run 3 (media on) only calls
      check_character{name: "Demo Sigrun"} -> turn-end plan() lists Demo
      Sigrun with ["portrait", "build"]. (h') "Demo Sigrid" (same fixture)
      gets its baseline the way a write step's begin takes it
      (note_touch, CURRENT fingerprints, no inverse) and nothing changes ->
      ["portrait", "build"] all the same (both outputs missing). Run 4
      (media OFF, create_run(media_enabled=False)): check_character{Demo
      Sigrun} -> no baseline for Demo Sigrun and plan(run 4) == [].
  (i) laziness: _base_body_present patched to count its calls. Run 5:
      note_touch(run 5, "character", "Demo Sigval", None) on a character
      saved outside the run -> 0 calls (note_touch builds steps, never
      presence); in review ONE plan(run 5) -> exactly 1 call (one character
      element with a build step).
  (j) a step that rendered NOTHING keeps holding with its output missing
      (it is re-run only by retry()). Run 1, Demo Torvald, after (g):
      key cleared, a DONE row whose portrait step is "skipped" with the
      current portrait fp -> the portrait is held, the base body is absent
      (temp world) -> plan == ["build"] (a held-only-while-present rule for
      every step of a done row gave ["portrait", "build"]). Row removed, key
      back; a DONE row whose build step is "done" with note "Build paused:
      demo" and the current build fp, base body absent -> the build is held,
      the portrait is held by (b)'s stopped row (output present) -> plan == [].
  (k) a step that ended done with NO artefact holds like a skipped one:
      key cleared, a DONE row whose portrait step is "done" with
      output False and the current fp -> plan == ["build"] (on the code
      before the output flag: ["portrait", "build"], the re-render loop).
      Removed, key back; a DONE row whose build step is "done" with output
      False and the current build fp, base absent -> plan == [] (portrait
      held by (b), present). retry(run) supersedes that step's fp
      (SUPERSEDED_FP, status stays "done") and queues Torvald ["build"] (a paused Build is
      retried the same way). Rows removed -> ["build"]. (The fixture's face
      prompt is empty, so the portrait fp is ""; before SUPERSEDED_FP a
      cleared "" fp equalled it — the retry proof uses the build step.) _produce_build with figure_build stubbed (request True,
      state {"paused": {"note": "demo"}}) -> note
      BUILD_PAUSED_NOTE + ": demo"; {"superseded": ...} -> "Build
      superseded: demo"; neither is _rendered (no artefacts). After the
      (c') lane run the steps carry output: Torvald build False (the stub
      writes nothing), Demo Other portrait True (an image), build False.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_lost_portrait_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

import app.imagegen.service as image_service  # noqa: E402


def _no_render(*_a, **_k):
    raise AssertionError("render reached")


image_service.get_image_service = _no_render

from app.core import figure_build, garment_assembly  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.character import (get_character_dir, get_character_profile,  # noqa: E402
                                  save_character_profile, set_character_profile_image)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

garment_assembly.schedule = lambda *a, **k: None
figure_build.request = lambda *a, **k: False

TQ = get_task_queue()
TQ._started = True  # never auto-start workers: the lane task stays pending

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


# The skill manager loads (and re-registers) the packages on its first use,
# so it is loaded before the fake package is registered.
from app.core.dependencies import get_skill_manager  # noqa: E402

get_skill_manager()
registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=TMP, manifest={}, apply_to=["human-roleplay"],
    piece_slots=["top"],
    body_slots=[BodySlotSpec(
        id="eyes", package_id="smoke_species", face=True,
        attributes={"color": {"type": "select", "options": ["green", "grey"]}},
        prompt={"always": "{color} eyes"})]))
clear_template_cache()

# ── stubs ────────────────────────────────────────────────────────────────
CALLS = []
HOOKS = {}  # character name -> callable run inside the portrait stub
PORTRAITS = {}


def fake_portrait(ctx, kind, ident, step):
    CALLS.append((ident, step.id))
    images = get_character_dir(ident) / "images"

    def run():
        hook = HOOKS.pop(ident, None)
        if hook:
            hook()
        PORTRAITS[ident] = PORTRAITS.get(ident, 0) + 1
        images.mkdir(parents=True, exist_ok=True)
        fname = f"{ident}_p{PORTRAITS[ident]}.png"
        (images / fname).write_bytes(b"png:" + fname.encode())
        set_character_profile_image(ident, fname)
        return ""
    return wdm._captured(ctx, kind, ident, run, roots=[images], profile=True)


def fake_build(ctx, kind, ident, step):
    CALLS.append((ident, step.id))
    return "built", []


wdm.PRODUCERS.update({"portrait": fake_portrait, "build": fake_build})
wdm.step_gate = lambda *a, **k: None
wdm.route_check = lambda *a, **k: None


def due(run_id, name):
    for k, i, steps in wdm.plan(run_id):
        if (k, i) == ("character", name):
            return [s.id for s in steps]
    return []


def review(run_id):
    wr.set_status(run_id, "awaiting_review")


def new_run(media=True):
    prev = wr.open_run()
    if prev:
        wr.set_status(prev["id"], "accepted")
    run_id = wr.create_run("fill", "m", "p", "u", 80, 300000, media_enabled=media)
    wr.next_turn(run_id)
    return run_id


def image_path(name):
    return get_character_dir(name) / "images" / str(
        (get_character_profile(name) or {}).get("profile_image") or "?")


def save_outside(name):
    ok = save_character_profile(name, {"name": name, "template": "human-roleplay",
                                       "gender": "female", "age": 30}, create_new=True)
    check(f"fixture: {name} saved outside the run", ok is True, ok)


def set_key(name, value):
    prof = dict(get_character_profile(name) or {})
    prof["profile_image"] = value
    check(f"fixture: profile_image of {name} = {value!r}", save_character_profile(name, prof) is True)


TORVALD = "Demo Torvald"

# (a)
print("(a) turn 1 creates the character, turn-end schedule")
run = new_run()
ctx = wt.ToolCtx(run_id=run, turn=1)
res = wt.run_tool(ctx, "create_character", {"data": {"name": TORVALD, "gender": "male"}})
check("(a) create ok", res.ok and res.wrote, res)
check("(a) steps", [s.id for s in wdm.element_steps("character", TORVALD) or []] == ["portrait", "build"],
      [s.id for s in wdm.element_steps("character", TORVALD) or []])
review(run)
rows = wdm.schedule(run)
check("(a) one row", len(rows) == 1, rows)
row1 = rows[0] if rows else -1
check("(a) row steps", [s["id"] for s in (wr.media_row(row1) or {}).get("steps") or []]
      == ["portrait", "build"], wr.media_row(row1))

# (b)
print("(b) the lane row is stopped by turn 2 while the portrait renders")


def _turn2_starts():
    wr.set_status(run, "running")
    wr.next_turn(run)
    wdm.cancel_queued(run, "turn 2 started")


HOOKS[TORVALD] = _turn2_starts
wdm.run_lane({})
row = wr.media_row(row1) or {}
check("(b) row cancelled", row.get("status") == "cancelled", row.get("status"))
check("(b) portrait done, build not run",
      [(s["id"], s["status"]) for s in row.get("steps") or []]
      == [("portrait", "done"), ("build", "queued")], row.get("steps"))
check("(b) one portrait call, no build call", CALLS == [(TORVALD, "portrait")], CALLS)
check("(b) profile_image set", (get_character_profile(TORVALD) or {}).get("profile_image")
      == "Demo Torvald_p1.png", (get_character_profile(TORVALD) or {}).get("profile_image"))
check("(b) the file exists", image_path(TORVALD).is_file(), str(image_path(TORVALD)))

# (c)
print("(c) turn 2 writes another character only")
ctx2 = wt.ToolCtx(run_id=run, turn=2)
res = wt.run_tool(ctx2, "create_character", {"data": {"name": "Demo Other", "gender": "female"}})
check("(c) create Demo Other ok", res.ok and res.wrote, res)
review(run)
check("(c) plan of Demo Torvald == [build]", due(run, TORVALD) == ["build"], due(run, TORVALD))
check("(c) profile_image intact", (get_character_profile(TORVALD) or {}).get("profile_image")
      == "Demo Torvald_p1.png")
check("(c) file intact", image_path(TORVALD).is_file())

# (d)
print("(d) the portrait output disappears")
set_key(TORVALD, "")
check("(d1) key cleared -> [portrait, build]", due(run, TORVALD) == ["portrait", "build"],
      due(run, TORVALD))
set_key(TORVALD, "Demo Torvald_p1.png")
check("(d) back to [build]", due(run, TORVALD) == ["build"], due(run, TORVALD))
_img = image_path(TORVALD)
_aside = TMP / "aside.png"
shutil.move(str(_img), str(_aside))
check("(d2) file gone -> [portrait, build]", due(run, TORVALD) == ["portrait", "build"],
      due(run, TORVALD))
shutil.move(str(_aside), str(_img))
check("(d2) back to [build]", due(run, TORVALD) == ["build"], due(run, TORVALD))

# (e)
print("(e) an in-flight row is never planned again")
set_key(TORVALD, "")
_fp = {s.id: s.fp for s in wdm.element_steps("character", TORVALD)}
flight = wr.add_media_row(run, "character", TORVALD, [
    {"id": "portrait", "label": "portrait", "status": "queued", "note": "", "fp": _fp["portrait"]}])
check("(e) queued row holds the portrait", due(run, TORVALD) == ["build"], due(run, TORVALD))
wr.update_media_row(flight, status="removed")
check("(e) removed -> [portrait, build]", due(run, TORVALD) == ["portrait", "build"], due(run, TORVALD))
set_key(TORVALD, "Demo Torvald_p1.png")

# (g)
print("(g) the build step holds only while the base body is present")
# The CURRENT build fp (the wanted figure can read the profile image, which
# (e) cleared and put back).
_fp = {s.id: s.fp for s in wdm.element_steps("character", TORVALD)}
built = wr.add_media_row(run, "character", TORVALD, [
    {"id": "build", "label": "Figure Build", "status": "done", "note": "", "fp": _fp["build"]}])
wr.update_media_row(built, status="done")
_real_present = wdm._base_body_present
try:
    wdm._base_body_present = lambda name, profile: False
    check("(g) base absent -> build due", due(run, TORVALD) == ["build"], due(run, TORVALD))
    wdm._base_body_present = lambda name, profile: True
    check("(g) base present -> nothing due", due(run, TORVALD) == [], due(run, TORVALD))
finally:
    wdm._base_body_present = _real_present
wr.update_media_row(built, status="removed")

# (j)
print("(j) a skipped / paused step holds with its output missing")
set_key(TORVALD, "")
_fp = {s.id: s.fp for s in wdm.element_steps("character", TORVALD)}
skipped = wr.add_media_row(run, "character", TORVALD, [
    {"id": "portrait", "label": "portrait", "status": "skipped", "note": "gate", "fp": _fp["portrait"]}])
wr.update_media_row(skipped, status="done")
check("(j) skipped portrait held -> [build]", due(run, TORVALD) == ["build"], due(run, TORVALD))
wr.update_media_row(skipped, status="removed")
set_key(TORVALD, "Demo Torvald_p1.png")
_fp = {s.id: s.fp for s in wdm.element_steps("character", TORVALD)}
paused = wr.add_media_row(run, "character", TORVALD, [
    {"id": "build", "label": "Figure Build", "status": "done", "note": "Build paused: demo",
     "fp": _fp["build"]}])
wr.update_media_row(paused, status="done")
_real_present = wdm._base_body_present
try:
    wdm._base_body_present = lambda name, profile: False
    check("(j) paused build held -> []", due(run, TORVALD) == [], due(run, TORVALD))
finally:
    wdm._base_body_present = _real_present
wr.update_media_row(paused, status="removed")

# (k)
print("(k) a done step that left no artefact holds; the paused note comes from the constant")
set_key(TORVALD, "")
_fp = {s.id: s.fp for s in wdm.element_steps("character", TORVALD)}
empty = wr.add_media_row(run, "character", TORVALD, [
    {"id": "portrait", "label": "portrait", "status": "done", "note": "", "output": False,
     "fp": _fp["portrait"]}])
wr.update_media_row(empty, status="done")
check("(k) empty portrait held -> [build]", due(run, TORVALD) == ["build"], due(run, TORVALD))
wr.update_media_row(empty, status="removed")
set_key(TORVALD, "Demo Torvald_p1.png")
_fp = {s.id: s.fp for s in wdm.element_steps("character", TORVALD)}
empty = wr.add_media_row(run, "character", TORVALD, [
    {"id": "build", "label": "Figure Build", "status": "done", "note": "built", "output": False,
     "fp": _fp["build"]}])
wr.update_media_row(empty, status="done")
check("(k) empty build held -> []", due(run, TORVALD) == [], due(run, TORVALD))
_retried = wdm.retry(run)
_estep = ((wr.media_row(empty) or {}).get("steps") or [{}])[0]
check("(k) retry supersedes its fp", _estep.get("fp") == wdm.SUPERSEDED_FP and _estep.get("status") == "done", _estep)
_rsteps = {(wr.media_row(r) or {}).get("target_id"): [s["id"] for s in (wr.media_row(r) or {}).get("steps") or []]
           for r in _retried}
check("(k) retry queues Torvald [build]", _rsteps.get(TORVALD) == ["build"], _rsteps)
for _r in _retried:
    wr.update_media_row(_r, status="removed")
wr.update_media_row(empty, status="removed")
set_key(TORVALD, "Demo Torvald_p1.png")
check("(k) back to [build]", due(run, TORVALD) == ["build"], due(run, TORVALD))

import app.core.figure_build as _fb  # noqa: E402
_real = (_fb.request, _fb.state, wdm._captured)
try:
    _fb.request = lambda name, trigger: True
    wdm._captured = lambda ctx, kind, name, fn, **k: (fn(), [])
    _spec = next(s for s in wdm.element_steps("character", TORVALD) if s.id == "build")
    for _key, _want in (("paused", wdm.BUILD_PAUSED_NOTE + ": demo"), ("superseded", "Build superseded: demo")):
        _fb.state = lambda name, _k=_key: {_k: {"note": "demo"}}
        _note, _arts = wdm._produce_build(None, "character", TORVALD, _spec)
        check(f"(k) {_key} build note", _note == _want, _note)
        check(f"(k) {_key} build not rendered",
              wdm._rendered({"status": "done", "note": _note, "output": bool(_arts)}) is False)
finally:
    _fb.request, _fb.state, wdm._captured = _real

# (c')
print("(c') turn-2-end schedule, lane, Accept")
rows = wdm.schedule(run)
_by = {(wr.media_row(r) or {}).get("target_id"): [s["id"] for s in (wr.media_row(r) or {}).get("steps") or []]
       for r in rows}
check("(c') rows", _by == {TORVALD: ["build"], "Demo Other": ["portrait", "build"]}, _by)
wdm.run_lane({})
check("(c') Demo Other's portrait", (get_character_profile("Demo Other") or {}).get("profile_image")
      == "Demo Other_p1.png", (get_character_profile("Demo Other") or {}).get("profile_image"))
_out = {((wr.media_row(r) or {}).get("target_id"), s["id"]): s.get("output")
        for r in rows for s in (wr.media_row(r) or {}).get("steps") or []}
check("(k) lane records output", _out == {(TORVALD, "build"): False, ("Demo Other", "portrait"): True,
                                          ("Demo Other", "build"): False}, _out)
wdm.finish_accepted_run(run)
wr.set_status(run, "accepted")
check("(c') after Accept: Torvald's key intact", (get_character_profile(TORVALD) or {}).get("profile_image")
      == "Demo Torvald_p1.png", (get_character_profile(TORVALD) or {}).get("profile_image"))
check("(c') after Accept: Torvald's file intact", image_path(TORVALD).is_file())

# (f)
print("(f) touched without a face change, never rendered")
save_outside("Demo Ragna")
run2 = new_run()
ctx = wt.ToolCtx(run_id=run2, turn=1)
res = wt.run_tool(ctx, "update_character", {"name": "Demo Ragna", "patch": {"outfits": [
    {"name": "Daily", "pieces": [{"name": "Demo Shirt", "slots": ["top"],
                                  "prompt_fragment": "demo shirt"}]}]}})
check("(f) outfit added", res.ok and res.wrote, res)
_base = wr.baselines(run2).get(("character", "Demo Ragna")) or {}
_now = {s.id: s.fp for s in wdm.element_steps("character", "Demo Ragna")}
check("(f) portrait fp unchanged", _base.get("portrait") == _now["portrait"], (_base, _now))
review(run2)
check("(f) [portrait, build]", due(run2, "Demo Ragna") == ["portrait", "build"], due(run2, "Demo Ragna"))

# (h)
print("(h) only checked")
save_outside("Demo Sigrun")
save_outside("Demo Sigrid")
_real_present = wdm._base_body_present
wdm._base_body_present = lambda name, profile: False
try:
    run3 = new_run()
    ctx = wt.ToolCtx(run_id=run3, turn=1)
    res = wt.run_tool(ctx, "check_character", {"name": "Demo Sigrun"})
    check("(h) check_character ok", res.ok and not res.wrote, res)
    wdm.note_touch(run3, "character", "Demo Sigrid", None)
    review(run3)
    check("(h) Demo Sigrun [portrait, build]", due(run3, "Demo Sigrun") == ["portrait", "build"],
          due(run3, "Demo Sigrun"))
    check("(h') Demo Sigrid [portrait, build]", due(run3, "Demo Sigrid") == ["portrait", "build"],
          due(run3, "Demo Sigrid"))
    run4 = new_run(media=False)
    ctx = wt.ToolCtx(run_id=run4, turn=1)
    res = wt.run_tool(ctx, "check_character", {"name": "Demo Sigrun"})
    check("(h) media off: check ok", res.ok, res)
    check("(h) media off: no baseline", ("character", "Demo Sigrun") not in wr.baselines(run4),
          wr.baselines(run4))
    review(run4)
    check("(h) media off: plan []", wdm.plan(run4) == [], wdm.plan(run4))
finally:
    wdm._base_body_present = _real_present

# (i)
print("(i) presence is computed lazily, in plan() only")
save_outside("Demo Sigval")
COUNT = {"n": 0}


def _counting(name, profile):
    COUNT["n"] += 1
    return False


wdm._base_body_present = _counting
try:
    run5 = new_run()
    wdm.note_touch(run5, "character", "Demo Sigval", None)
    check("(i) note_touch: baseline taken", isinstance(wr.baselines(run5).get(("character", "Demo Sigval")), dict),
          wr.baselines(run5))
    check("(i) note_touch: no presence check", COUNT["n"] == 0, COUNT["n"])
    review(run5)
    wdm.plan(run5)
    check("(i) one plan(): one presence check", COUNT["n"] == 1, COUNT["n"])
finally:
    wdm._base_body_present = _real_present

print("FAIL: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
