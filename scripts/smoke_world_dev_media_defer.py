#!/usr/bin/env python3
"""Smoke: World Dev free mode — no automatic render during a turn: the
deferral of the characters a run touches (plan
docs/superpowers/plans/2026-11-25-world-dev-free-media.md, Task 2).

A temp world (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render: ``figure_build.start``
and ``model_refs._fire_kinds`` are replaced by recorders, so nothing this
smoke reaches can start a Build or a reference render.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_defer.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

Default config: ``model_ref_renders_enabled`` missing = on (``model_refs._enabled``),
no ``model_ref_auto`` key = every reference kind on, debounce 60 s — so an
untouched character's ``schedule_outfit_render`` arms at least the "pose"
timer (the "pose" kind is never dropped, on or off the pipeline;
smoke_world_dev_outfits (m) shows the full sets).

The plugin registry is cleared and one fake species with the slots
["top", "feet"] is registered (as smoke_world_dev_outfits), so a starting
outfit of two NEW pieces is valid.

  (a) create_character "Demo Defer" with outfit Daily = [Demo Shirt [top],
      Demo Clogs [feet]] through run_tool (turn 1 of run R) -> ok; right after
      it NO model_refs timer of Demo Defer is armed (the create's
      apply_equipped_pieces called schedule_outfit_render — that is what
      armed {"pose", ...} before this task, smoke_world_dev_outfits (m) — and
      the guard swallowed it), ``figure_build.start`` was called 0 times,
      ``is_deferred("Demo Defer")`` is True and the recorded suppressed
      triggers contain "model_refs.schedule_outfit_render".
  (b) ``figure_build.request("Demo Defer", "outfit_change")`` while deferred
      -> False and still 0 start calls; the suppressed triggers now contain
      "figure_build.request". ``garment_assembly.schedule("Demo Defer")`` ->
      False, suppressed contains "garment_assembly.schedule", recorded with
      the arguments ((None,), {"retry": False}) although the call passed the
      signature "sig-stale" (the replay re-resolves the serving model). A
      timer body of Demo Defer kind "pose" that had already started (the
      armed entry's timer IS the running thread) -> ``_fire_kinds`` NOT
      called (0 calls), recorded as "model_refs._fire_kind:pose".
  (c) with ``figure_build.on_pipeline`` / ``auto_build_on`` patched to True and
      ``generation_pause.hold_build`` to False: ``release_all(R, replay=True)``
      (the discard's release, Task 9) returns ["Demo Defer"]; its replay
      re-issues each suppressed trigger ONCE per (name, trigger) — the
      request of (b) (and any request the create made, same key) is one
      entry, so ``start`` is called exactly once, with ("Demo Defer", reason
      "outfit_change", automatic True). Afterwards ``is_deferred`` is False
      and a direct ``request`` calls ``start`` again -> 2 calls in total.
      ``release_all(R, replay=True)`` again -> [] and no further start (the
      deferral and its record are gone): still 2.
  (c0) ``release_turn`` (every turn end, Task 9) replays NOTHING: Demo Defer
      deferred again, a suppressed request -> release_turn returns
      ["Demo Defer"], still 2 start calls, the record is dropped (a later
      release_all replays nothing either).
  (d) a character NOT touched by any run ("Demo Other", saved directly):
      ``schedule_outfit_render`` arms timers as before (>= 1, "pose" among
      them); ``cancel_character_timers`` disarms them (0 left).
  (e) a character deferred and then deleted before the release (``defer``
      "Demo Gone" under run R2, a suppressed request, the row deleted):
      ``release_all(R2, replay=True)`` returns ["Demo Gone"] but replays nothing — 0 new
      start calls (a gone character gets no render).
  (f) ``defer`` of one name by a second run moves it: ``release_turn`` of the
      first run returns [] for it, the second run's returns it.
  (g) ``suppress_if_deferred`` checks and records in ONE step: for a name no
      run defers it returns False and records nothing (suppressed_triggers
      stays []); for a deferred one it returns True and the trigger is
      recorded. A release between check and record is therefore impossible
      by construction (one lock acquisition), not by timing.
  (i) the replay of a swallowed timer body re-arms ONLY that kind: "Demo
      Other" deferred under "run-i", a started "pose" timer body swallowed ->
      the suppressed triggers are exactly ["model_refs._fire_kind:pose"];
      ``release_all("run-i", replay=True)`` -> the armed timers are exactly {"pose"} (a
      schedule_outfit_render replay would also arm the T-pose or the Build
      timer, (d)).
  (j) the off-pipeline auto-mesh hook is guarded itself (plan
      2026-11-25-world-dev-free-fixes, Task 4 / F5): ``model3d.trigger_generation``
      and ``figure_build.request`` are replaced by counters,
      ``base_body.is_base_pipeline`` by False (off the pipeline) and
      ``model3d.get_model3d_options`` by a counter returning
      {"auto_generate": False} — so a call that gets PAST the guard reads the
      options exactly once and then returns False without a render.
      "Demo Hal" saved directly, deferred under "run-j":
      j1 ``maybe_auto_generate_for_outfit("Demo Hal")`` -> False, options read
         0 times, trigger 0, request 0, suppressed_triggers ==
         ["model3d.maybe_auto_generate_for_outfit"] (the guard is the FIRST
         statement, before the pipeline check).
      j2 ``release_all("run-j", replay=True)`` -> ["Demo Hal"]; the replay calls
         the hook once: options read 1 time, trigger still 0 (auto_generate
         off), request 0.
      j3 not deferred any more: a direct call -> False, options read 2 times,
         suppressed_triggers("Demo Hal") == [] (the guard records nothing).
  (h) the agent releases at EVERY turn end WITHOUT a replay and schedules
      the run's media instead (Task 9; RunManager with a scripted FakeLLM as
      in smoke_world_dev_agent; ``world_dev_media.schedule`` is replaced by a
      recorder, so no lane task is queued; the (c) patches stay).
      h1 final turn [create_character "Demo H1" + outfit, (probe), "Done."]:
         the probe, run inside the 2nd LLM call (= still in the turn), sees
         H1 deferred and no timer armed -> awaiting_review; afterwards H1 is
         not deferred, NO timer is armed (no replay) and schedule was called
         for the run.
      The run starts with max_steps=1 (per turn): a final reply after one
      step still ends the turn normally (smoke_world_dev_agent (t)/(e)).
      h2 budget cut: [create_character "Demo H2", create_character "Demo H2b"]
         -> the turn is cut after H2 (awaiting_review, H2b never written);
         H2 not deferred, no timer, schedule called again.
      h3 failed turn [create_character "Demo H3", RuntimeError("down")] ->
         turn 3 rolled back (awaiting_review), H3 gone, not deferred, no
         timer armed, schedule called (the rollback re-plans).
      h4 _interrupt: wr.set_status raises once for "awaiting_review":
         [create_character "Demo H4", "ok"] -> interrupted; H4 not deferred,
         no timer, schedule NOT called (still 3 calls): the raise comes
         before the turn end's schedule, and _interrupt schedules nothing
         since an interrupted run renders nothing before Accept (plan
         2026-11-25-world-dev-free-fixes, Task 1 / F1).
      h5 _close: "Demo Other" deferred by hand under the run, then discard
         -> rolled_back, "Demo Other" no longer deferred (release_all), H1,
         H2 and H4 gone and none of them has a timer left.
"""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CLIPS = Path(tempfile.mkdtemp(prefix="smoke_wd_defer_clips_"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)
os.environ["ANIMATION_RIG_FILE"] = str(CLIPS / "reference.fbx")

from app.core import paths  # noqa: E402

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_defer_"))
paths.init(STORAGE)
atexit.register(shutil.rmtree, CLIPS, ignore_errors=True)
atexit.register(shutil.rmtree, STORAGE, ignore_errors=True)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import base_body  # noqa: E402
from app.core import figure_build  # noqa: E402
from app.core import garment_assembly  # noqa: E402
from app.core import generation_pause  # noqa: E402
from app.core import model3d  # noqa: E402
from app.core import model_refs  # noqa: E402
from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.models.character import (character_row_exists,  # noqa: E402
                                  delete_character, save_character_profile)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.core.llm_client import LLMChunk  # noqa: E402
from app.plugins.registry import Package  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=STORAGE, manifest={}, apply_to=["human-roleplay"],
    piece_slots=["top", "feet"]))
clear_template_cache()

starts = []
fired = []
_orig = {"start": figure_build.start, "fire": model_refs._fire_kinds,
         "on_pipeline": figure_build.on_pipeline, "auto": figure_build.auto_build_on,
         "hold": generation_pause.hold_build}


def _rec_start(name, *, reason, automatic=False):
    starts.append((name, reason, automatic))
    return {"status": "started"}


figure_build.start = _rec_start
model_refs._fire_kinds = lambda name, kinds, *a, **kw: fired.append((name, kinds))


def armed(name):
    with model_refs._lock:
        return {k[1] for k in model_refs._pending_timers if k[0] == name}


async def _no_active(_llm_instance):
    return None


wa._chat_active = _no_active
wa._chat_done = lambda _task_id: None


class FakeLLM:
    """Plays a script: a string, an Exception (provider error) or a callable
    (run inside the call, returns the string)."""

    def __init__(self, replies):
        self.replies = list(replies)

    async def astream(self, messages):
        reply = self.replies.pop(0) if self.replies else "Done."
        if callable(reply):
            reply = reply()
        if isinstance(reply, BaseException):
            raise reply
        yield LLMChunk(content=reply)


def make_char(name):
    body = {"data": {"name": name, "outfits": [{"name": "Daily", "pieces": [
        {"name": f"{name} Shirt", "slots": ["top"], "prompt_fragment": "a shirt"}]}]}}
    return f'<tool name="create_character">{json.dumps(body)}</tool>'


async def settle(rm, run_id):
    for _ in range(1000):
        run = wr.get_run(run_id)
        if run["status"] != "running" and not rm.is_busy(run_id):
            return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} still running")


async def agent_cases():
    rm = wa.RunManager()
    fake = FakeLLM([])
    rm.llm_factory = lambda model, provider, max_tokens: (fake, None)
    seen = {}
    scheduled = []
    real_schedule = wdm.schedule
    wdm.schedule = lambda run_id_: scheduled.append(run_id_) or []

    def probe():
        seen["deferred"] = wdm.is_deferred("Demo H1")
        seen["armed"] = armed("Demo H1")
        return "Done."

    # h1
    fake.replies = [make_char("Demo H1"), probe]
    rid = await rm.start("build", "fake-model", "fake", "u1", max_steps=1)
    run = await settle(rm, rid)
    check("(h1) awaiting_review", run["status"] == "awaiting_review", run)
    check("(h1) deferred during the turn", seen.get("deferred") is True, seen)
    check("(h1) no timer during the turn", seen.get("armed") == set(), seen)
    check("(h1) released after the turn", not wdm.is_deferred("Demo H1"))
    check("(h1) no replay at the turn end", armed("Demo H1") == set(), armed("Demo H1"))
    check("(h1) the turn end scheduled the media", scheduled == [rid], scheduled)

    # h2
    fake.replies = [make_char("Demo H2"), make_char("Demo H2b")]
    await rm.message(rid, "more")
    run = await settle(rm, rid)
    check("(h2) cut -> awaiting_review", run["status"] == "awaiting_review"
          and "budget reached" in (run["note"] or ""), run)
    check("(h2) H2b never written", not character_row_exists("Demo H2b"))
    check("(h2) released", not wdm.is_deferred("Demo H2"))
    check("(h2) no replay", armed("Demo H2") == set(), armed("Demo H2"))
    check("(h2) scheduled", scheduled == [rid] * 2, scheduled)

    # h3
    fake.replies = [make_char("Demo H3"), RuntimeError("down")]
    await rm.message(rid, "more")
    run = await settle(rm, rid)
    check("(h3) rolled back turn -> awaiting_review", run["status"] == "awaiting_review"
          and "down" in (run["note"] or ""), run)
    check("(h3) H3 gone", not character_row_exists("Demo H3"))
    check("(h3) released", not wdm.is_deferred("Demo H3"))
    check("(h3) no replay for a gone character", armed("Demo H3") == set(), armed("Demo H3"))
    check("(h3) the rollback re-planned", scheduled == [rid] * 3, scheduled)

    # h4
    orig_set_status = wr.set_status
    flag = {"raised": False}

    def flaky(run_id_, status, note=None):
        if status == "awaiting_review" and not flag["raised"]:
            flag["raised"] = True
            raise RuntimeError("store down")
        return orig_set_status(run_id_, status, note)

    fake.replies = [make_char("Demo H4"), "ok"]
    wr.set_status = flaky
    try:
        await rm.message(rid, "more")
        run = await settle(rm, rid)
    finally:
        wr.set_status = orig_set_status
    check("(h4) interrupted", run["status"] == "interrupted", run)
    check("(h4) released", not wdm.is_deferred("Demo H4"))
    check("(h4) no replay", armed("Demo H4") == set(), armed("Demo H4"))
    check("(h4) not scheduled (F1)", scheduled == [rid] * 3, scheduled)
    wdm.schedule = real_schedule

    # h5
    wdm.defer("Demo Other", rid)
    await rm.discard(rid)
    run = wr.get_run(rid)
    check("(h5) rolled_back", run["status"] == "rolled_back", run["status"])
    check("(h5) close releases everything", not wdm.is_deferred("Demo Other"))
    for nm in ("Demo H1", "Demo H2", "Demo H4"):
        check(f"(h5) {nm} gone", not character_row_exists(nm))
        check(f"(h5) {nm} has no timer", armed(nm) == set(), armed(nm))


def started_timer(name, kind):
    """Run _fire_kind as a timer body that had already started."""
    from app.core.timeutils import utc_now
    t = threading.Thread(target=model_refs._fire_kind, args=[name, kind])
    with model_refs._lock:
        model_refs._pending_timers[(name, kind)] = model_refs._Scheduled(
            timer=t, scheduled_at=utc_now(), due_at=utc_now())
    t.start()
    t.join(10)


try:
    run = wr.create_run("defer", "m", "p", "u", 40, 300000)
    ctx = wt.ToolCtx(run_id=run, turn=1)

    # (a)
    res = wt.run_tool(ctx, "create_character", {"data": {"name": "Demo Defer", "outfits": [
        {"name": "Daily", "pieces": [
            {"name": "Demo Shirt", "slots": ["top"], "prompt_fragment": "a shirt"},
            {"name": "Demo Clogs", "slots": ["feet"], "prompt_fragment": "clogs"}]}]}})
    check("(a) create ok", res.ok, res.line)
    check("(a) no timer armed", armed("Demo Defer") == set(), armed("Demo Defer"))
    check("(a) no Build start", starts == [], starts)
    check("(a) deferred", wdm.is_deferred("Demo Defer"))
    check("(a) schedule_outfit_render recorded as suppressed",
          "model_refs.schedule_outfit_render" in wdm.suppressed_triggers("Demo Defer"),
          wdm.suppressed_triggers("Demo Defer"))

    # (b)
    check("(b) request while deferred -> False",
          figure_build.request("Demo Defer", "outfit_change") is False)
    check("(b) still no start", starts == [], starts)
    check("(b) request recorded",
          "figure_build.request" in wdm.suppressed_triggers("Demo Defer"),
          wdm.suppressed_triggers("Demo Defer"))
    check("(b) garment_assembly.schedule while deferred -> False",
          garment_assembly.schedule("Demo Defer", "sig-stale") is False)
    check("(b) assembly recorded",
          "garment_assembly.schedule" in wdm.suppressed_triggers("Demo Defer"),
          wdm.suppressed_triggers("Demo Defer"))
    with wdm._lock:
        rec = wdm._suppressed["Demo Defer"]["garment_assembly.schedule"]
    check("(b) assembly recorded without the signature", rec == ((None,), {"retry": False}), rec)
    started_timer("Demo Defer", "pose")
    check("(b) a started timer body renders nothing while deferred", fired == [], fired)
    check("(b) the timer body recorded with its kind",
          "model_refs._fire_kind:pose" in wdm.suppressed_triggers("Demo Defer"),
          wdm.suppressed_triggers("Demo Defer"))

    # (c)
    figure_build.on_pipeline = lambda *a, **kw: True
    figure_build.auto_build_on = lambda *a, **kw: True
    generation_pause.hold_build = lambda *a, **kw: False
    released = wdm.release_all(run, replay=True)
    check("(c) release_all returns the name", released == ["Demo Defer"], released)
    check("(c) replay starts the Build exactly once",
          starts == [("Demo Defer", "outfit_change", True)], starts)
    check("(c) no longer deferred", not wdm.is_deferred("Demo Defer"))
    figure_build.request("Demo Defer", "outfit_change")
    check("(c) a direct request starts again", len(starts) == 2, starts)
    check("(c) a second release replays nothing",
          wdm.release_all(run, replay=True) == [] and len(starts) == 2, starts)
    model_refs.cancel_character_timers("Demo Defer")

    # (c0)
    wdm.defer("Demo Defer", run)
    figure_build.request("Demo Defer", "outfit_change")
    check("(c0) release_turn names it", wdm.release_turn(run) == ["Demo Defer"])
    check("(c0) release_turn replays nothing", len(starts) == 2, starts)
    check("(c0) the record is dropped",
          wdm.release_all(run, replay=True) == [] and len(starts) == 2, starts)
    model_refs.cancel_character_timers("Demo Defer")

    # (d)
    save_character_profile("Demo Other", {"name": "Demo Other", "template": "human-roleplay"},
                           create_new=True)
    model_refs.schedule_outfit_render("Demo Other")
    got = armed("Demo Other")
    check("(d) untouched character: timers armed as before",
          len(got) >= 1 and "pose" in got, got)
    model_refs.cancel_character_timers("Demo Other")
    check("(d) cancel disarms them", armed("Demo Other") == set(), armed("Demo Other"))

    # (e) (one open run at a time: the first one is closed first)
    wr.set_status(run, "rolled_back")
    run2 = wr.create_run("defer2", "m", "p", "u", 40, 300000)
    save_character_profile("Demo Gone", {"name": "Demo Gone", "template": "human-roleplay"},
                           create_new=True)
    wdm.defer("Demo Gone", run2)
    check("(e) request of a deferred character -> False",
          figure_build.request("Demo Gone", "outfit_change") is False)
    delete_character("Demo Gone")
    check("(e) row gone", not character_row_exists("Demo Gone"))
    n = len(starts)
    rel = wdm.release_all(run2, replay=True)
    check("(e) release_all names it", rel == ["Demo Gone"], rel)
    check("(e) a gone character gets no replay", len(starts) == n, starts[n:])

    # (f)
    wdm.defer("Demo Other", run)
    wdm.defer("Demo Other", run2)
    check("(f) the first run releases nothing", wdm.release_turn(run) == [])
    check("(f) the second run releases it", wdm.release_turn(run2) == ["Demo Other"])
    model_refs.cancel_character_timers("Demo Other")

    # (g)
    check("(g) not deferred -> False",
          wdm.suppress_if_deferred("Demo Nobody", "figure_build.request", ("x",)) is False)
    check("(g) nothing recorded", wdm.suppressed_triggers("Demo Nobody") == [],
          wdm.suppressed_triggers("Demo Nobody"))
    wdm.defer("Demo Nobody", "run-g")
    check("(g) deferred -> True",
          wdm.suppress_if_deferred("Demo Nobody", "figure_build.request", ("x",)) is True)
    check("(g) recorded", wdm.suppressed_triggers("Demo Nobody") == ["figure_build.request"],
          wdm.suppressed_triggers("Demo Nobody"))
    wdm.release_all("run-g", replay=False)

    # (i)
    model_refs.cancel_character_timers("Demo Other")
    wdm.defer("Demo Other", "run-i")
    started_timer("Demo Other", "pose")
    check("(i) only the timer body recorded",
          wdm.suppressed_triggers("Demo Other") == ["model_refs._fire_kind:pose"],
          wdm.suppressed_triggers("Demo Other"))
    wdm.release_all("run-i", replay=True)
    check("(i) replay re-armed only that kind", armed("Demo Other") == {"pose"},
          armed("Demo Other"))
    model_refs.cancel_character_timers("Demo Other")

    # (j)
    save_character_profile("Demo Hal", {"name": "Demo Hal", "template": "human-roleplay"},
                           create_new=True)
    jcount = {"trigger": 0, "request": 0, "options": 0}
    j_orig = (model3d.trigger_generation, figure_build.request,
              base_body.is_base_pipeline, model3d.get_model3d_options)

    def _j_trigger(*a, **kw):
        jcount["trigger"] += 1
        return True

    def _j_request(*a, **kw):
        jcount["request"] += 1
        return True

    def _j_options(*a, **kw):
        jcount["options"] += 1
        return {"auto_generate": False}

    model3d.trigger_generation = _j_trigger
    figure_build.request = _j_request
    base_body.is_base_pipeline = lambda *a, **kw: False
    model3d.get_model3d_options = _j_options
    try:
        wdm.defer("Demo Hal", "run-j")
        got = model3d.maybe_auto_generate_for_outfit("Demo Hal")
        check("(j1) hook while deferred -> False", got is False, got)
        check("(j1) guard before everything", jcount == {"trigger": 0, "request": 0, "options": 0},
              jcount)
        check("(j1) recorded", wdm.suppressed_triggers("Demo Hal")
              == ["model3d.maybe_auto_generate_for_outfit"], wdm.suppressed_triggers("Demo Hal"))
        rel = wdm.release_all("run-j", replay=True)
        check("(j2) release_all names it", rel == ["Demo Hal"], rel)
        check("(j2) replay passed the guard once", jcount == {"trigger": 0, "request": 0,
                                                              "options": 1}, jcount)
        got = model3d.maybe_auto_generate_for_outfit("Demo Hal")
        check("(j3) not deferred -> proceeds", got is False and jcount["options"] == 2, jcount)
        check("(j3) nothing recorded", wdm.suppressed_triggers("Demo Hal") == [],
              wdm.suppressed_triggers("Demo Hal"))
    finally:
        (model3d.trigger_generation, figure_build.request,
         base_body.is_base_pipeline, model3d.get_model3d_options) = j_orig

    # (h)
    wr.set_status(run2, "rolled_back")
    asyncio.run(agent_cases())
finally:
    figure_build.start = _orig["start"]
    model_refs._fire_kinds = _orig["fire"]
    figure_build.on_pipeline = _orig["on_pipeline"]
    figure_build.auto_build_on = _orig["auto"]
    generation_pause.hold_build = _orig["hold"]
    for nm in ("Demo Defer", "Demo Other", "Demo Gone", "Demo H1", "Demo H2",
               "Demo H2b", "Demo H3", "Demo H4"):
        model_refs.cancel_character_timers(nm)

print()
if failures:
    print(f"FAILED ({len(failures)}): " + "; ".join(failures))
    sys.exit(1)
print("all deferral checks passed")
