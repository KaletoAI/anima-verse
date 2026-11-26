#!/usr/bin/env python3
"""Smoke: World Dev free mode — the media lane's Build is a manual (explicit)
Build (plan docs/superpowers/plans/2026-11-25-world-dev-free-complete-characters-budget.md,
Task 7, gap C5, decision 13).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render: ``get_image_service``
raises. The routing is stubbed through ``routing.chain_for`` /
``routing.intended_spec_for`` (the two readers ``route_check`` calls),
``figure_build.planned_work`` returns a hand-made plan, and
``figure_build.start`` / ``state`` are fakes — no Build thread starts.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_explicit_build.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (0) ``world_dev_media.BUILD_EXPLICIT`` is True (decision 13).
  (a) plan = [Step("plain_body", manual=figure.BASE_MISSING)] — a character
      without a base body. The stub answers (plan, plan) for explicit=True and
      (plan, []) for explicit=False (``figure_build._runnable``: an automatic
      Build drops a manual step). ``build_gate`` must ask with explicit=True,
      so the plain body runs and its occasions are
      ``BUILD_STEP_OCCASIONS["plain_body"]`` = (base_front, base_view,
      outfit_front, mesh_humanoid, rig_humanoid, face_retexture, tpose_view,
      upscale) minus the conditional ones (``CONDITIONAL_OCCASIONS``: for
      plain_body face_retexture, tpose_view and upscale, all keyed on
      ``model3d.face_before_rig_planned``). Face stubbed False ->
      (["base_front", "base_view", "outfit_front", "mesh_humanoid",
      "rig_humanoid"], None) — never GATE_MANUAL. Face stubbed True -> all
      eight, in that order. The stub saw explicit=True.
  (a2) plan = [Step("pendant", failed="F-cached")] — a chain that failed
      earlier. The stub answers (plan, figure_build._runnable(plan, explicit))
      (the real predicate: a manual Build retries a cached failure, an
      automatic one drops it). Explicit -> BUILD_STEP_OCCASIONS["pendant"] =
      (["jewellery_mesh"], None) — never GATE_ONLY_FAILED, so the failed Build
      is re-attempted on every lane pass. With BUILD_EXPLICIT patched False ->
      (None, GATE_ONLY_FAILED with name "Demo Explicit" and labels "Pendant
      — failed") — that note exists only in the automatic mode.
  (b) step_gate of the build step (run media on, master switch on, not
      paused, both automatic switches on):
      (b1) every chain set except mesh_humanoid -> the (a) order's first empty
           chain is mesh_humanoid -> "no routing chain for mesh_humanoid —
           configure it in /admin/settings → Media Generation → Routing".
      (b2) ONLY mesh_humanoid set -> the first empty chain in the (a) order is
           base_front -> the same note for base_front.
  (c) all chains set, ``figure_build.auto_build_on`` -> False and
      ``model_refs.auto_renders_enabled`` -> False -> step_gate is None (the
      lane's Build is the admin's click; the automatic switches do not apply).
      ``generation_pause.is_paused`` -> True -> "automatic generation of Demo
      Explicit is paused — Retry media after Resume" (the pause still applies).
  (d) the producer (``PRODUCERS["build"]``): ``figure_build.start`` returns
      {"status": "base_busy", "reason": "R-busy"} -> StepError status
      "skipped" whose note contains "R-busy"; {"status": "current"} (no
      reason) -> skipped, the note names "current"; {"status": "started"},
      then ``state`` idle -> done (note ""). Every start call was
      (name, reason "world_dev", automatic False); ``figure_build.request``
      was never called.
  (e) get_image_service never reached.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_explicit_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
(TMP / "clips").mkdir()
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

import app.imagegen.service as image_service  # noqa: E402

_service_calls = []


def _no_render(*_a, **_k):
    _service_calls.append(1)
    raise AssertionError("render reached")


image_service.get_image_service = _no_render

from app.core import config  # noqa: E402
from app.core import figure, figure_build, generation_pause, model3d, model_refs  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.imagegen import routing  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def no_chain(occ):
    return (f"no routing chain for {occ} — configure it in /admin/settings → Media Generation → "
            f"Routing")


NAME = "Demo Explicit"
ig = config._CONFIG.setdefault("image_generation", {})
ig["enabled"] = True
save_character_profile(NAME, {"name": NAME, "template": "human-roleplay", "gender": "female", "age": 30})
run = wr.create_run("explicit build", "m", "p", "u", 80, 300000)
wr.set_media_enabled(run, True)
build = wdm.StepSpec("build", "Figure Build", (), "fp", "build")

# ── (0) ──
check("(0) BUILD_EXPLICIT is True", wdm.BUILD_EXPLICIT is True, wdm.BUILD_EXPLICIT)

# ── (a) build_gate ──
print("(a) build_gate reads the explicit plan")
PLAIN = figure_build.Step("plain_body", "Plain body", 6, manual=figure.BASE_MISSING)
SEEN = []


def fake_planned(name, *, explicit, profile=None):
    SEEN.append(explicit)
    return [PLAIN], ([PLAIN] if explicit else [])


figure_build.planned_work = fake_planned
model3d.face_before_rig_planned = lambda *_a, **_k: False
FIVE = ["base_front", "base_view", "outfit_front", "mesh_humanoid", "rig_humanoid"]
g = wdm.build_gate(NAME)
check("(a) face off -> the five plain-body occasions, no note", g == (FIVE, None), g)
check("(a) planned_work asked with explicit=True", SEEN == [True], SEEN)
model3d.face_before_rig_planned = lambda *_a, **_k: True
g = wdm.build_gate(NAME)
check("(a) face on -> all eight", g == (FIVE + ["face_retexture", "tpose_view", "upscale"], None), g)
model3d.face_before_rig_planned = lambda *_a, **_k: False

print("(a2) a cached failure: explicit retries it, automatic notes it")
FAILED = figure_build.Step("pendant", "Pendant — failed", 0, failed="F-cached")
_runnable = figure_build._runnable


def fake_failed(name, *, explicit, profile=None):
    return [FAILED], _runnable([FAILED], explicit)


figure_build.planned_work = fake_failed
g = wdm.build_gate(NAME)
check("(a2) explicit -> the failed step's occasion, no note", g == (["jewellery_mesh"], None), g)
wdm.BUILD_EXPLICIT = False
try:
    g = wdm.build_gate(NAME)
finally:
    wdm.BUILD_EXPLICIT = True
check("(a2) automatic -> GATE_ONLY_FAILED",
      g == (None, "Demo Explicit: only failed steps are left (Pendant — failed) — a manual Build "
                  "retries them (Characters → Figure)"), g)
figure_build.planned_work = fake_planned

# ── (b) step_gate routes ──
print("(b) step_gate: the plain body's routes")
CHAINS = {}
routing.chain_for = lambda occasion, character="", *a, **k: list(CHAINS.get(occasion) or [])
routing.intended_spec_for = lambda occasion, character="", *a, **k: (
    "fake-backend" if CHAINS.get(occasion) else "")
generation_pause.is_paused = lambda *_a, **_k: False
figure_build.auto_build_on = lambda *_a, **_k: True
model_refs.auto_renders_enabled = lambda *_a, **_k: True
CHAINS.update({o: ["fake-*"] for o in FIVE if o != "mesh_humanoid"})
g = wdm.step_gate(run, "character", NAME, build)
check("(b1) only mesh_humanoid empty -> its no-chain note", g == no_chain("mesh_humanoid"), g)
CHAINS.clear()
CHAINS["mesh_humanoid"] = ["fake-*"]
g = wdm.step_gate(run, "character", NAME, build)
check("(b2) only mesh_humanoid set -> base_front's no-chain note", g == no_chain("base_front"), g)

# ── (c) the automatic switches do not apply ──
print("(c) the automatic switches do not gate the lane's Build")
CHAINS.update({o: ["fake-*"] for o in FIVE})
figure_build.auto_build_on = lambda *_a, **_k: False
model_refs.auto_renders_enabled = lambda *_a, **_k: False
g = wdm.step_gate(run, "character", NAME, build)
check("(c) automatic switches off -> None", g is None, g)
generation_pause.is_paused = lambda *_a, **_k: True
g = wdm.step_gate(run, "character", NAME, build)
check("(c) paused -> GATE_PAUSED",
      g == f"automatic generation of {NAME} is paused — Retry media after Resume", g)
generation_pause.is_paused = lambda *_a, **_k: False

# ── (d) the producer ──
print("(d) the producer starts a manual Build")
wdm.BUILD_POLL_S = 0.01
STARTS = []
REQUESTS = []
ANSWER = {}


def fake_start(name, *, reason, automatic=False):
    STARTS.append((name, reason, automatic))
    return dict(ANSWER)


figure_build.start = fake_start
figure_build.request = lambda *a, **k: REQUESTS.append(a) or True
figure_build.state = lambda name: {"running": False, "queued": 0, "deferred": None, "failed": {},
                                   "skipped": [], "paused": None, "superseded": None}
ctx = wdm.ProduceCtx(run, 1)


def produce():
    try:
        return wdm.PRODUCERS["build"](ctx, "character", NAME, build), None
    except wdm.StepError as e:
        return None, e


ANSWER.update({"status": "base_busy", "reason": "R-busy"})
out, err = produce()
check("(d) base_busy -> skipped naming its reason",
      err is not None and err.status == "skipped" and "R-busy" in err.note,
      (out, err and (err.status, err.note)))
ANSWER.clear()
ANSWER.update({"status": "current"})
out, err = produce()
check("(d) current -> skipped naming the status",
      err is not None and err.status == "skipped" and "current" in err.note,
      (out, err and (err.status, err.note)))
ANSWER.clear()
ANSWER.update({"status": "started"})
out, err = produce()
check("(d) started, then idle -> done", err is None and out is not None and out[0] == "",
      (out, err and (err.status, err.note)))
check("(d) every start: reason world_dev, automatic False",
      STARTS == [(NAME, "world_dev", False)] * 3, STARTS)
check("(d) request never called", REQUESTS == [], REQUESTS)

# ── (e) ──
check("(e) get_image_service never reached", not _service_calls, len(_service_calls))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
