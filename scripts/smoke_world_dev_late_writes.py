#!/usr/bin/env python3
"""Smoke check: no late write for a character that was deleted (World Dev free mode, plan
2026-11-25-world-dev-free-p2 Task 1, decision E16).

A World Dev undo deletes a character the run created. A Build (``figure_build._run``) or a reference
render (``model_refs._run_generation``) that was queued before the delete must not write for it
afterwards: ``figure_build._run`` starts with ``garment_hair.ensure_hairstyle``, which can MINT a
hairstyle item (and with it rows/files) for a name that has no row any more; ``_run_generation``
renders reference images and then fires the T-pose auto-mesh hook.

WHAT IS CHECKED, and where every expected value comes from (no expectation is read at runtime):

  Temp world (``paths.init(<tmpdir>)`` before any world-DB import, ``ANIMATION_CLIPS_DIR`` temp).
  Characters ``Demo Late`` and ``Demo Alive`` are saved with ``create_new=True``; ``Demo Late`` is
  then deleted with ``delete_character`` (returns True — a plain character, no linked family).
  The writers are replaced by recorders (one list entry per call):
  ``garment_hair.ensure_hairstyle``, ``figure_build._run_planned``,
  ``model_refs.generate_model_ref_images``, ``model3d.maybe_auto_generate_for_outfit``.

  (a) ``figure_build._run("Demo Late", "outfit_change")`` → ensure_hairstyle calls 0, _run_planned
      calls 0 — the new row check returns before both. No directory ``get_character_dir("Demo Late")``
      exists afterwards (delete_character removed it; nothing re-created it).
  (b) ``model_refs._run_generation("Demo Late", "tpose")`` → generate calls 0, auto-mesh calls 0
      (``_character_still_exists`` is False, the run returns before the render and the hook).
  (c) control, the living ``Demo Alive``: (a) records exactly 1 ensure_hairstyle + 1 _run_planned
      (one Build = one call of each, ``_run`` body); (b) records exactly 1 generate (kinds ("tpose",))
      + 1 auto-mesh call (the hook runs once, only for kind "tpose").
  (c2) control for the hook gate: ``_run_generation("Demo Alive", "pose")`` → 1 generate, 0 auto-mesh
      (the hook is T-pose-only, unchanged).
  (e) a row check that RAISES is no verdict "gone" (same rule as ``model_refs._character_still_exists``,
      whose docstring says a read error fires as before): with ``character_row_exists`` raising,
      ``figure_build._character_gone("Demo Alive")`` is False and ``_run`` records 1 + 1 again.
  (f) the window between the hairstyle mint and the plan: ensure_hairstyle's recorder deletes the
      character (the delete lands while the Build runs) → _run_planned calls 0 (the second check) and
      ``figure_build._last`` holds no entry for it: the run is skipped, not a failure. (On the old code the
      strict profile read raised "Character not found" and recorded a PROFILE_FAILED state.)
  (a) likewise leaves no ``_last`` entry for ``Demo Late``. In (a) the recorder ALSO calls the real
      ``ensure_hairstyle``, so a gate that regressed would really mint: the item catalog
      (``inventory.list_items()``) has the same length before and after (a) — +0 items.

  The worker (``figure_build._worker``, called synchronously after seeding ``_queues``/``_active`` the way
  ``request``/``request_refit`` do; ``generation_pause.hold_build``, ``figure_build.refit_refused`` and
  ``_notify_build_changed`` replaced by recorders, hold_build answering False = not held):
  (g) deleted, automatic Build → hold_build calls 0 (a deleted name is not recorded as held), hair 0,
      planned 0; deleted, queued re-fit → refit_refused calls 0. Both leave ``Demo Late`` out of
      ``_active`` with an empty queue (the loop ran to its empty-queue return; ``_worker`` leaves the
      emptied deque in ``_queues``, as it always did) and its re-fit item popped.
  (g2) control, alive automatic Build → hold_build 1, hair 1, planned 1; alive re-fit → refit_refused 1
      with the item queued (``("Demo Alive", ["piece-x"])``) and hold_build 0 (a re-fit is never held).
  (e2) one Build logs a read error once: with ``character_row_exists`` raising, a manual Build through
      ``_worker`` calls the check three times (worker, before the hairstyle, before the plan) and leaves
      exactly 1 WARNING record "row check failed" on the ``figure_build`` logger (the two ``_run``
      re-checks log at debug).

  (d) "fails on the old code": at commit 2f5289260 ``figure_build._run`` calls
      ``garment_hair.ensure_hairstyle(character_name)`` as its first statement, without any row check
      (``git show 2f5289260:app/core/figure_build.py``), so case (a) records 1 ensure_hairstyle call there;
      and ``model_refs._run_generation`` at 2f5289260 calls ``generate_model_ref_images`` directly,
      so case (b) records 1 generate call there. Not re-run here (stated, read from the source).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_late_writes.py
"""
import atexit
import logging
import os
import shutil
import sys
import tempfile
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = tempfile.mkdtemp(prefix="smoke_wd_late_clips_")
os.environ["ANIMATION_CLIPS_DIR"] = CLIPS

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_late_"))
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)
paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import figure_build, garment_hair, generation_pause, model3d, model_refs  # noqa: E402
from app.models import inventory  # noqa: E402
from app.models import character as character_mod  # noqa: E402
from app.models.character import (delete_character, get_character_dir,  # noqa: E402
                                  save_character_profile)

failures = []


def check(label, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


calls = {"hair": [], "planned": [], "generate": [], "automesh": [], "hold": [], "refit": []}
on_hair = []   # optional side effect of the ensure_hairstyle recorder (cases a, f)
_real_hair = garment_hair.ensure_hairstyle


def _rec_hair(name):
    calls["hair"].append(name)
    for fn in on_hair:
        fn(name)
    return ""


def _rec_hold(name, reason):
    calls["hold"].append((name, reason))
    return False


def _rec_refit(name, item_ids=None):
    calls["refit"].append((name, list(item_ids or [])))
    return {i: "still refused" for i in (item_ids or [])}


def _rec_planned(name, reason, profile, *, automatic):
    calls["planned"].append((name, reason))


def _rec_generate(name, kinds=(), force=False, tpose_view=None, **_kw):
    calls["generate"].append((name, tuple(kinds)))


def _rec_automesh(name):
    calls["automesh"].append(name)


garment_hair.ensure_hairstyle = _rec_hair
figure_build._run_planned = _rec_planned
model_refs.generate_model_ref_images = _rec_generate
model3d.maybe_auto_generate_for_outfit = _rec_automesh
generation_pause.hold_build = _rec_hold
figure_build.refit_refused = _rec_refit
figure_build._notify_build_changed = lambda: None


def run_worker(name, reason, automatic, refit_item=""):
    """Seed the worker state like ``request`` / ``request_refit`` and run ``_worker`` on this thread."""
    with figure_build._lock:
        figure_build._queues[name] = deque([(reason, automatic)])
        if refit_item:
            figure_build._refit_items[name] = refit_item
        figure_build._active.add(name)
    figure_build._worker(name)

def reset():
    for v in calls.values():
        v.clear()
    on_hair.clear()


check("setup: Demo Late created", save_character_profile("Demo Late", {"name": "Demo Late"}, create_new=True))
check("setup: Demo Alive created", save_character_profile("Demo Alive", {"name": "Demo Alive"}, create_new=True))
check("setup: Demo Late deleted", delete_character("Demo Late") is True)
check("setup: Demo Late row gone", not character_mod.character_row_exists("Demo Late"))

# (a) Build of a deleted character
reset()
items_before = len(inventory.list_items())
on_hair.append(_real_hair)   # a regressed gate would really mint here
figure_build._run("Demo Late", "outfit_change")
check("(a) deleted: item catalog +0", len(inventory.list_items()) == items_before,
      f"{items_before} -> {len(inventory.list_items())}")
check("(a) deleted: ensure_hairstyle not called", calls["hair"] == [], str(calls["hair"]))
check("(a) deleted: _run_planned not called", calls["planned"] == [], str(calls["planned"]))
check("(a) deleted: no failure state recorded", "Demo Late" not in figure_build._last,
      str(figure_build._last.get("Demo Late")))
check("(a) deleted: no character directory", not get_character_dir("Demo Late").exists(),
      str(get_character_dir("Demo Late")))

# (b) reference render of a deleted character
reset()
model_refs._run_generation("Demo Late", "tpose")
check("(b) deleted: no render", calls["generate"] == [], str(calls["generate"]))
check("(b) deleted: no auto-mesh", calls["automesh"] == [], str(calls["automesh"]))
check("(b) deleted: no character directory", not get_character_dir("Demo Late").exists())

# (c) control: the living character
reset()
figure_build._run("Demo Alive", "outfit_change")
check("(c) alive: 1 ensure_hairstyle", calls["hair"] == ["Demo Alive"], str(calls["hair"]))
check("(c) alive: 1 _run_planned", calls["planned"] == [("Demo Alive", "outfit_change")], str(calls["planned"]))
reset()
model_refs._run_generation("Demo Alive", "tpose")
check("(c) alive: 1 render", calls["generate"] == [("Demo Alive", ("tpose",))], str(calls["generate"]))
check("(c) alive: 1 auto-mesh", calls["automesh"] == ["Demo Alive"], str(calls["automesh"]))
reset()
model_refs._run_generation("Demo Alive", "pose")
check("(c2) alive pose: 1 render", calls["generate"] == [("Demo Alive", ("pose",))], str(calls["generate"]))
check("(c2) alive pose: no auto-mesh", calls["automesh"] == [], str(calls["automesh"]))

# (e) a failing row check is no verdict "gone"
reset()
_orig_exists = character_mod.character_row_exists


def _raising(_name):
    raise RuntimeError("database is locked")


character_mod.character_row_exists = _raising
try:
    check("(e) read error: not gone", figure_build._character_gone("Demo Alive") is False)
    figure_build._run("Demo Alive", "outfit_change")
    check("(e) read error: Build runs (1 + 1)",
          calls["hair"] == ["Demo Alive"] and calls["planned"] == [("Demo Alive", "outfit_change")],
          str(calls))
finally:
    character_mod.character_row_exists = _orig_exists

# (g) the worker: a deleted character is neither held, built nor re-fitted
reset()
run_worker("Demo Late", "outfit_change", True)
check("(g) deleted automatic: not held", calls["hold"] == [], str(calls["hold"]))
check("(g) deleted automatic: no hairstyle, no plan", calls["hair"] == [] and calls["planned"] == [], str(calls))
reset()
run_worker("Demo Late", figure_build.REFIT_REASON, True, refit_item="piece-x")
check("(g) deleted re-fit: refit_refused not called", calls["refit"] == [], str(calls["refit"]))
check("(g) deleted: worker state empty", "Demo Late" not in figure_build._active
      and not figure_build._queues.get("Demo Late") and "Demo Late" not in figure_build._refit_items)

# (g2) control: the living character through the worker
reset()
run_worker("Demo Alive", "outfit_change", True)
check("(g2) alive automatic: hold asked once", calls["hold"] == [("Demo Alive", "outfit_change")], str(calls["hold"]))
check("(g2) alive automatic: 1 + 1", calls["hair"] == ["Demo Alive"]
      and calls["planned"] == [("Demo Alive", "outfit_change")], str(calls))
reset()
run_worker("Demo Alive", figure_build.REFIT_REASON, True, refit_item="piece-x")
check("(g2) alive re-fit: refit_refused once", calls["refit"] == [("Demo Alive", ["piece-x"])], str(calls["refit"]))
check("(g2) alive re-fit: never held", calls["hold"] == [], str(calls["hold"]))

# (e2) a read error is logged once per Build
reset()


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


_handler = _Collect()
_fb_logger = figure_build.logger
_fb_logger.addHandler(_handler)
_old_level = _fb_logger.level
_fb_logger.setLevel(logging.DEBUG)
character_mod.character_row_exists = _raising
try:
    run_worker("Demo Alive", "outfit_change", False)
finally:
    character_mod.character_row_exists = _orig_exists
    _fb_logger.removeHandler(_handler)
    _fb_logger.setLevel(_old_level)
_row_msgs = [r for r in _handler.records if "row check failed" in r.getMessage()]
check("(e2) read error: Build runs (1 + 1)", calls["hair"] == ["Demo Alive"]
      and calls["planned"] == [("Demo Alive", "outfit_change")], str(calls))
check("(e2) read error: 1 warning", sum(r.levelno == logging.WARNING for r in _row_msgs) == 1,
      str([(r.levelname, r.getMessage()) for r in _row_msgs]))
check("(e2) read error: 3 checks (1 warning + 2 debug)", len(_row_msgs) == 3,
      str([(r.levelname, r.getMessage()) for r in _row_msgs]))

# (f) the delete lands between the hairstyle and the plan
reset()
check("(f) setup: Demo Gone created", save_character_profile("Demo Gone", {"name": "Demo Gone"}, create_new=True))
on_hair.append(lambda name: delete_character(name))
figure_build._run("Demo Gone", "outfit_change")
check("(f) deleted mid-run: 1 ensure_hairstyle", calls["hair"] == ["Demo Gone"], str(calls["hair"]))
check("(f) deleted mid-run: _run_planned not called", calls["planned"] == [], str(calls["planned"]))
check("(f) deleted mid-run: no failure state recorded", "Demo Gone" not in figure_build._last,
      str(figure_build._last.get("Demo Gone")))

print()
if failures:
    print(f"FAILED {len(failures)}: " + "; ".join(failures))
    sys.exit(1)
print("all late-write checks passed")
