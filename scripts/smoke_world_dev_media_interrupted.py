#!/usr/bin/env python3
"""Smoke: World Dev free mode — an interrupted run renders nothing before
Accept (plan docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md,
Task 1 / F1).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render: ``get_image_service``
raises, the task queue's ``submit`` only COUNTS (the lane never runs), so
every media row stays where scheduling put it. Tools run through
``world_dev_tools.run_tool`` (the real journal + the real _Step hooks).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_interrupted.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The plugin registry holds one species for "human-roleplay" without a hair
slot, and ``figure_build.on_pipeline`` is patched to False for the smoke's
characters (the off-pipeline branch, as smoke_world_dev_media_plan (d) does
for "Demo Lean"). So a created character's steps are, by
``world_dev_media._character_steps``: no hairstyle (off the pipeline),
"portrait" (label "portrait"), "mesh" (label "T-pose + 3D model") — and a
created character has the baseline None, so both steps are due.

No submit ever records a task, so ``_pending_lane_task`` is always False and
every ``_ensure_lane_locked`` call submits exactly once.

Run 1, "Demo Ivy" created in a running run:
  (c) ``RunManager._interrupt`` on the running run (a fresh ``_RunState``)
      -> status ``interrupted``; the old code scheduled here, the fix does
      not: rows 0, submits 0. (Run first: (a) needs the interrupted run.)
  (a) ``schedule(run)`` on the interrupted run -> [] (SCHEDULE_STATUSES is
      only awaiting_review); rows [], submits 0.
  (b) ``media_status(run)["waiting"]`` == [{"kind": "character", "id":
      "Demo Ivy", "name": "Demo Ivy", "steps": [{"id": "portrait", "label":
      "portrait"}, {"id": "mesh", "label": "T-pose + 3D model"}]}] (from
      plan(); a character's name is its id); "elements" == [] (no row).
  (d) ``set_run_switch(run, True)`` -> {"enabled": True, "cancelled": 0,
      "queued": []} (the switch is stored, schedule refuses by status);
      rows still 0.
  (e) ``retry(run)`` raises MediaConflict (rows still []).
  (f) ``await mgr.accept(run)`` -> status ``accepted``, media_state
      ``accepted``, exactly 1 row: kind character, target "Demo Ivy", status
      queued, step ids ["portrait", "mesh"]; submits == 1 (the one schedule
      of the Accept). The row is then marked done by hand (as the lane would)
      so no queued row is left for the boot cases.
Run 2, "Demo Juno":
  (g) interrupted, then ``await mgr.discard(run2)`` -> ``rolled_back``,
      media_rows(run2) == [] (nothing was ever scheduled), submits still 1.
Boot (rows inserted by hand; an accepted run stands in for the "other" run
because the store allows ONE open run at a time — reset_on_boot requeues a
running row of an accepted run exactly like one of an awaiting_review run,
media state accepted is not closed):
  (e2) run 3 interrupted holds a done row whose "portrait" step failed with
      fp "x": ``retry(run3)`` raises MediaConflict and the step's fp is
      still "x" (checked BEFORE any fingerprint is cleared).
  (h) a running row (steps portrait done, mesh running) of run 3
      (interrupted, media open) + a running row of an accepted run ->
      reset_on_boot: held 1, requeued 1, removed 0, submitted 1 (the
      requeued row is the one queued row left); run 3's row cancelled with
      note NOTE_WAIT_ACCEPT, step statuses ["done", "cancelled"]; the
      accepted run's row queued.
  (h2) after every queued row is done: a QUEUED row (steps [portrait
      queued]) of run 5 (interrupted, media open), no other queued row ->
      held 1, requeued 0, submitted 0, submits unchanged; the row cancelled
      with NOTE_WAIT_ACCEPT, step statuses ["cancelled"]. (Before the fix
      the queued row made oldest_queued_row() non-None and the lane was
      submitted -> submitted 1.)
  (h3) (h) and (h2) in ONE call: run 6 (interrupted) holds a running row and
      a queued row, an accepted run a running row -> held 2, requeued 1,
      submitted 1 (the accepted run's requeued row is the one queued row
      left).
  (h4) the server's early hold: a QUEUED row of run 8 (interrupted, media
      open), no other queued row -> ``hold_on_boot()`` returns 1 and submits
      nothing (it only writes rows); the row cancelled with NOTE_WAIT_ACCEPT;
      a following ``reset_on_boot`` -> held 0, requeued 0, submitted 0.
      app/server.py calls ``hold_on_boot()`` (as ``_wdm_hold()``) BEFORE ``get_task_queue().start()``
      and ``reset_on_boot()`` after it (source offsets in that order) — the
      start turns the old lane task back to pending, so a leftover must be
      held before any worker exists. This also assumes nothing earlier in
      the lifespan submits to the task queue (a submit would start the
      workers before the hold) — none does today.
Run 7, "Demo Kai":
  (i) awaiting_review control -> schedule(run7) returns 1 id (unchanged
      behaviour), media_status waiting == [].
"""
from __future__ import annotations

import asyncio
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_intr_"))
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

from app.core import figure_build  # noqa: E402
from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.character_template import clear_template_cache  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=TMP, manifest={}, apply_to=["human-roleplay"],
    piece_slots=["top"], body_slots=[]))
clear_template_cache()

OFF_PIPELINE = {"Demo Ivy", "Demo Juno", "Demo Kai"}
_orig_on = figure_build.on_pipeline
figure_build.on_pipeline = lambda name, **kw: False if name in OFF_PIPELINE else _orig_on(name, **kw)

TQ = get_task_queue()
TQ._started = True
SUBMITS = {"n": 0}


def fake_submit(task_type, payload=None, *a, **k):
    SUBMITS["n"] += 1
    return f"fake-{SUBMITS['n']}"


TQ.submit = fake_submit

STEPS_EXPECTED = [{"id": "portrait", "label": "portrait"},
                  {"id": "mesh", "label": "T-pose + 3D model"}]
WAIT_NOTE = getattr(wdm, "NOTE_WAIT_ACCEPT", "<NOTE_WAIT_ACCEPT missing>")


def new_run_with(name):
    run = wr.create_run("build", "m", "p", "u", 80, 300000)
    if name:
        res = wt.run_tool(wt.ToolCtx(run_id=run, turn=1), "create_character",
                          {"data": {"name": name, "gender": "female"}})
        check(f"create {name} ok", res.ok and res.wrote, res)
    return run


def accepted_run():
    """A closed-by-Accept run (media state accepted) for the boot control."""
    run = wr.create_run("other", "m", "p", "u", 80, 300000)
    wr.set_status(run, "accepted")
    wdm.set_media_state(run, "accepted")
    return run


def step_statuses(row_id):
    return [s.get("status") for s in (wr.media_row(row_id) or {}).get("steps") or []]


def finish_queued():
    """What the lane would do: every queued row of every run -> done."""
    for row in wr.media_rows_with_status(("queued",)):
        wr.update_media_row(row["id"], status="done")


def conflict(fn, *args):
    try:
        fn(*args)
    except wdm.MediaConflict as e:
        return e
    return None


def running_row(run_id, kind, target, steps):
    rid = wr.add_media_row(run_id, kind, target, steps)
    wr.update_media_row(rid, status="running")
    return rid


async def main():
    mgr = wa.RunManager()

    print("Run 1 — Demo Ivy")
    run = new_run_with("Demo Ivy")

    print("(c) _interrupt schedules nothing")
    await mgr._interrupt(run, mgr._state(run), "smoke interrupt", RuntimeError("smoke"))
    check("(c) interrupted", (wr.get_run(run) or {}).get("status") == "interrupted",
          (wr.get_run(run) or {}).get("status"))
    check("(c) no rows", wr.media_rows(run) == [], wr.media_rows(run))
    check("(c) no submit", SUBMITS["n"] == 0, SUBMITS)

    print("(a) schedule refuses an interrupted run")
    got = wdm.schedule(run)
    check("(a) schedule -> []", got == [], got)
    check("(a) rows []", wr.media_rows(run) == [], wr.media_rows(run))
    check("(a) submits 0", SUBMITS["n"] == 0, SUBMITS)

    print("(b) media_status lists what waits")
    ms = wdm.media_status(run) or {}
    check("(b) waiting", ms.get("waiting") == [{"kind": "character", "id": "Demo Ivy",
                                                 "name": "Demo Ivy", "steps": STEPS_EXPECTED}],
          ms.get("waiting"))
    check("(b) elements []", ms.get("elements") == [], ms.get("elements"))

    print("(d) switch on while interrupted")
    try:
        got = wdm.set_run_switch(run, True)
    except Exception as e:  # noqa: BLE001
        got = e
    check("(d) switch result", got == {"enabled": True, "cancelled": 0, "queued": []}, got)
    check("(d) rows still []", wr.media_rows(run) == [], wr.media_rows(run))

    print("(e) retry refused")
    raised = conflict(wdm.retry, run)
    check("(e) MediaConflict", raised is not None, raised)
    check("(e) rows still []", wr.media_rows(run) == [], wr.media_rows(run))
    check("(a-e) submits 0", SUBMITS["n"] == 0, SUBMITS)

    print("(f) Accept schedules what plan() listed")
    await mgr.accept(run)
    r = wr.get_run(run) or {}
    check("(f) accepted", r.get("status") == "accepted", r.get("status"))
    check("(f) media_state accepted", r.get("media_state") == "accepted", r.get("media_state"))
    rows = wr.media_rows(run)
    check("(f) exactly 1 row", len(rows) == 1, rows)
    if rows:
        row = rows[0]
        check("(f) row character Demo Ivy queued",
              (row["kind"], row["target_id"], row["status"]) == ("character", "Demo Ivy", "queued"),
              (row["kind"], row["target_id"], row["status"]))
        check("(f) step ids", [s["id"] for s in row["steps"]] == ["portrait", "mesh"], row["steps"])
    check("(f) submits 1", SUBMITS["n"] == 1, SUBMITS)
    finish_queued()

    print("Run 2 — Demo Juno, discard")
    run2 = new_run_with("Demo Juno")
    wr.set_status(run2, "interrupted")
    await mgr.discard(run2)
    check("(g) rolled_back", (wr.get_run(run2) or {}).get("status") == "rolled_back",
          (wr.get_run(run2) or {}).get("status"))
    check("(g) rows []", wr.media_rows(run2) == [], wr.media_rows(run2))
    check("(g) submits still 1", SUBMITS["n"] == 1, SUBMITS)

    print("(e2)/(h) boot: a running row of an interrupted run is held")
    acc_row = running_row(accepted_run(), "character", "Demo Other", [
        {"id": "portrait", "label": "portrait", "status": "running", "note": "", "fp": "a"}])
    run3 = new_run_with(None)
    wr.set_status(run3, "interrupted")
    done_row = wr.add_media_row(run3, "character", "Demo Gone", [
        {"id": "portrait", "label": "portrait", "status": "failed", "note": "boom", "fp": "x"}])
    wr.update_media_row(done_row, status="done")
    raised = conflict(wdm.retry, run3)
    check("(e2) MediaConflict", raised is not None, raised)
    check("(e2) fp untouched", [s.get("fp") for s in wr.media_row(done_row)["steps"]] == ["x"],
          wr.media_row(done_row)["steps"])
    run_row = running_row(run3, "character", "Demo Held", [
        {"id": "portrait", "label": "portrait", "status": "done", "note": "", "fp": "p"},
        {"id": "mesh", "label": "T-pose + 3D model", "status": "running", "note": "", "fp": "m"}])
    before = SUBMITS["n"]
    counts = wdm.reset_on_boot()
    check("(h) counts held/requeued/removed/submitted",
          (counts.get("held"), counts.get("requeued"), counts.get("removed"),
           counts.get("submitted")) == (1, 1, 0, 1), counts)
    row = wr.media_row(run_row)
    check("(h) held row cancelled + note", (row["status"], row["note"]) == ("cancelled", WAIT_NOTE),
          (row["status"], row["note"]))
    check("(h) step statuses", step_statuses(run_row) == ["done", "cancelled"], step_statuses(run_row))
    check("(h) accepted run's row requeued", wr.media_row(acc_row)["status"] == "queued",
          wr.media_row(acc_row)["status"])
    check("(h) one submit", SUBMITS["n"] == before + 1, SUBMITS)
    finish_queued()
    wr.set_status(run3, "rolled_back")

    print("(h2) boot: a queued leftover of an interrupted run is held, no lane")
    run5 = new_run_with(None)
    wr.set_status(run5, "interrupted")
    q_row = wr.add_media_row(run5, "character", "Demo Left", [
        {"id": "portrait", "label": "portrait", "status": "queued", "note": "", "fp": "p"}])
    check("(h2) the leftover is the only queued row",
          [r["id"] for r in wr.media_rows_with_status(("queued",))] == [q_row],
          wr.media_rows_with_status(("queued",)))
    before = SUBMITS["n"]
    counts = wdm.reset_on_boot()
    check("(h2) counts held/requeued/submitted",
          (counts.get("held"), counts.get("requeued"), counts.get("submitted")) == (1, 0, 0), counts)
    check("(h2) submits unchanged", SUBMITS["n"] == before, SUBMITS)
    row = wr.media_row(q_row)
    check("(h2) row cancelled + note", (row["status"], row["note"]) == ("cancelled", WAIT_NOTE),
          (row["status"], row["note"]))
    check("(h2) step statuses", step_statuses(q_row) == ["cancelled"], step_statuses(q_row))
    finish_queued()
    wr.set_status(run5, "rolled_back")

    print("(h3) both kinds in one call")
    acc2_row = running_row(accepted_run(), "character", "Demo Other2", [
        {"id": "portrait", "label": "portrait", "status": "running", "note": "", "fp": "a"}])
    run6 = new_run_with(None)
    wr.set_status(run6, "interrupted")
    r6_run = running_row(run6, "character", "Demo Six", [
        {"id": "portrait", "label": "portrait", "status": "done", "note": "", "fp": "p"},
        {"id": "mesh", "label": "T-pose + 3D model", "status": "running", "note": "", "fp": "m"}])
    r6_q = wr.add_media_row(run6, "location", "loc_demo_six", [
        {"id": "building-front", "label": "building", "status": "queued", "note": "", "fp": "b"}])
    before = SUBMITS["n"]
    counts = wdm.reset_on_boot()
    check("(h3) counts held/requeued/submitted",
          (counts.get("held"), counts.get("requeued"), counts.get("submitted")) == (2, 1, 1), counts)
    check("(h3) both of run 6 cancelled",
          [wr.media_row(i)["status"] for i in (r6_run, r6_q)] == ["cancelled", "cancelled"],
          [wr.media_row(i)["status"] for i in (r6_run, r6_q)])
    check("(h3) the queued row left is the accepted run's",
          [r["id"] for r in wr.media_rows_with_status(("queued",))] == [acc2_row],
          wr.media_rows_with_status(("queued",)))
    check("(h3) one submit", SUBMITS["n"] == before + 1, SUBMITS)
    finish_queued()
    wr.set_status(run6, "rolled_back")

    print("(h4) the early hold before the queue starts")
    run8 = new_run_with(None)
    wr.set_status(run8, "interrupted")
    q8 = wr.add_media_row(run8, "character", "Demo Early", [
        {"id": "portrait", "label": "portrait", "status": "queued", "note": "", "fp": "p"}])
    before = SUBMITS["n"]
    check("(h4) hold_on_boot -> 1", wdm.hold_on_boot() == 1)
    check("(h4) submits unchanged", SUBMITS["n"] == before, SUBMITS)
    row = wr.media_row(q8)
    check("(h4) row cancelled + note", (row["status"], row["note"]) == ("cancelled", WAIT_NOTE),
          (row["status"], row["note"]))
    counts = wdm.reset_on_boot()
    check("(h4) reset_on_boot after it: held/requeued/submitted 0",
          (counts.get("held"), counts.get("requeued"), counts.get("submitted")) == (0, 0, 0), counts)
    src = (Path(__file__).resolve().parent.parent / "app" / "server.py").read_text(encoding="utf-8")
    offs = [src.find("_wdm_hold()"), src.find("get_task_queue().start()"), src.find("_wdm_reset()")]
    check("(h4) server.py: hold_on_boot < queue start < reset_on_boot",
          -1 not in offs and offs == sorted(offs), offs)
    wr.set_status(run8, "rolled_back")

    print("(i) awaiting_review control")
    run7 = new_run_with("Demo Kai")
    wr.set_status(run7, "awaiting_review")
    got = wdm.schedule(run7)
    check("(i) schedule -> 1 id", len(got) == 1, got)
    check("(i) waiting []", (wdm.media_status(run7) or {}).get("waiting") == [],
          (wdm.media_status(run7) or {}).get("waiting"))


asyncio.run(main())
figure_build.on_pipeline = _orig_on

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nall ok")
