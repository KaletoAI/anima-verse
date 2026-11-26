#!/usr/bin/env python3
"""Smoke: World Dev free mode — F10 polish (plan
docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md, Task 12).

A temp world and instance (STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR /
ANIMATION_RIG_FILE temp, paths.init BEFORE any world-DB import); no server, no
LLM, no render. Tool calls go through ``world_dev_tools.run_tool`` exactly as
the agent loop calls them; the gate readers of (a) are stubbed on their modules.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_polish.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (a) ``step_gate`` never raises. The run is the dict {"media_enabled": True}
      (the run switch passes), ``media_generation_enabled`` -> True and
      ``generation_pause.is_paused`` -> False (both pass), and
      ``BUILD_EXPLICIT`` is pinned False (the automatic lane mode — in the
      explicit mode, the default since complete-characters-budget Task 7,
      these two switches are not read), so the first check that can answer
      is the Build's world switch:
      - ``model_refs.auto_renders_enabled`` stubbed False -> the gate of the
        "build" step of "Demo Ada" is exactly
        "automatic outfit renders are off for this world" (checked BEFORE the
        character's "Build automatically", which is stubbed True and must not
        be reached: its call list stays empty).
      - stubbed raising RuntimeError("x") -> exactly
        "the world's automatic-render switch could not be read (x)".
      - the portrait step (occasions ("profile",)) with ``route_check``
        stubbed raising RuntimeError("y") -> exactly
        "the route of profile could not be read (y)", no exception escapes.
      - ``model_refs.auto_renders_enabled()`` is the public reader of the
        world switch ``model_ref_renders_enabled``: the empty temp config has
        no value -> the default True; equal to ``model_refs._enabled()``.
  (b) ``_count_outside`` counts world props (their point (x, z)): one prop
      "Demo Well" placed at (1000, 0) through the core writer, no place, no
      area; box x 0…300, z -100…100 (sides 300 and 200, within 50…20 000).
      1000 > 300 -> 1 outside, so the line is exactly
      "build bounds of this run: x 0…300, z -100…100; warning: 1 place /
      area / prop lies outside — they stay, the box only guides new writes"
      (singular wording for a count of 1).
  (c) The update_location npc_slots pre-check names a kept room by its STORED
      name: place "Demo Keep" upserted with the stored room r1 "Demo Hall";
      patch {rooms: [{id: "r1"}], npc_slots: [{role: "Demo guard", room:
      "rX"}]} -> refused; rX is no room of the place, so the refusal lists the
      rooms a slot may name — it contains 'r1 "Demo Hall"' (before the fix
      the sent room had no name, the list read 'r1 "r1"').
      A sent room id the place does not have is named as such already in the
      pre-check: patch {rooms: [{id: "rZ"}], npc_slots: [{role: "Demo guard",
      room: "rZ"}]} -> refused with "room id 'rZ' does not exist in
      loc_demo_keep — omit the id for a new room" (the wording of the check
      under the lock; before, the pre-check dropped rZ and refused the slot
      with "must be a room id of this place").
  (d) ``_check_npc_slots`` refuses unusable values itself, BEFORE
      ``normalize_slots`` (which would log a WARNING and rewrite them). Each
      patch is one slot {role: "Demo guard", <field>} on "Demo Keep"; every
      refusal starts "error: '<field path>' must" (its own explicit wording,
      never the generic "would be stored as" of the rewrite check, which is
      what these values got before), and a capturing handler on the
      npc_spawn logger records 0 WARNING records over all of them:
        when "whenever"   -> "'npc_slots[0].when'" (normalize_when gives "")
        count_max 25      -> "'npc_slots[0].count_max'" (25 > SLOT_COUNT_MAX 20)
        count_min -1      -> "'npc_slots[0].count_min'" (below 0)
        count_min 1.5     -> "'npc_slots[0].count_min'" (not whole)
        count_min inf     -> "'npc_slots[0].count_min'" (not finite)
        count_min True    -> "'npc_slots[0].count_min'" (a bool is no count)
        count_min 3, count_max 2 -> "'npc_slots[0].count_max'" (max < min)
        count_max 0 (min absent = its default 1) -> "'npc_slots[0].count_max'"
        radius_m -5       -> "'npc_slots[0].radius_m'"  (below 0)
        radius_m "10"     -> "'npc_slots[0].radius_m'"  (not a number)
      Control: {role, when "18:00-02:00", count_min 0, count_max 20,
      radius_m 0} -> ok (the canonical span, both bounds inclusive).
      ``npc_spawn.SLOT_COUNT_MAX`` == 20, and ``normalize_slot`` clamps with
      it: patched to 3, {role, count_max 5} normalizes to count_max 3 (the
      check and the clamp read the same constant, they cannot drift).
  (e) Verify-only items (no code change by Task 12):
      - app/core/world_dev_media.py compiles under -W error::SyntaxWarning
        (a subprocess, the byte code written to the temp dir);
      - app/models/events.py ``add_stat_hit`` holds
        keyed_lock("world_event", …) (AST: a with item calling keyed_lock
        whose first argument is the constant "world_event").
"""
import ast
import atexit
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_polish_"))
# Removed on every exit, a failed assert or an exception included.
atexit.register(shutil.rmtree, ROOT, True)
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402

paths.init(STORAGE)
paths.init_instance(ROOT / "instance")

from app.core import config, db  # noqa: E402

config.load(STORAGE / "config.json")
db.init_schema()

from app.core import figure_build, generation_pause, model_refs, npc_spawn, props  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.imagegen import base as imagegen_base  # noqa: E402
from app.models import world_props as wp  # noqa: E402
from app.models.world import upsert_location  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


def gate(step):
    try:
        return wdm.step_gate({"media_enabled": True}, "character", "Demo Ada", step)
    except Exception as e:  # noqa: BLE001 — the contract under test
        return f"RAISED {type(e).__name__}: {e}"


# ── (a) step_gate never raises ───────────────────────────────────────────
print("(a) step_gate")
BUILD = wdm.StepSpec("build", "Build", (), "fp-build", "build")
PORTRAIT = wdm.StepSpec("portrait", "portrait", ("profile",), "fp-portrait", "portrait")
auto_calls = []
orig = {
    "mge": imagegen_base.media_generation_enabled,
    "paused": generation_pause.is_paused,
    "auto": figure_build.auto_build_on,
    "route": wdm.route_check,
    "renders": getattr(model_refs, "auto_renders_enabled", None),
    "explicit": wdm.BUILD_EXPLICIT,
}
imagegen_base.media_generation_enabled = lambda: True
generation_pause.is_paused = lambda name: False
figure_build.auto_build_on = lambda name, **kw: auto_calls.append(name) or True
try:
    # The world/character switches gate only the AUTOMATIC lane mode (the
    # lane's Build is explicit since plan 2026-11-25 complete-characters-budget
    # Task 7, decision 13); that mode stays selectable, so it is pinned here.
    wdm.BUILD_EXPLICIT = False
    model_refs.auto_renders_enabled = lambda: False
    check("(a) auto renders off", gate(BUILD) == "automatic outfit renders are off for this world",
          gate(BUILD))

    def _boom():
        raise RuntimeError("x")
    model_refs.auto_renders_enabled = _boom
    check("(a) auto renders unreadable",
          gate(BUILD) == "the world's automatic-render switch could not be read (x)", gate(BUILD))
    check("(a) Build automatically not reached", auto_calls == [], auto_calls)

    def _route_boom(occasion, character="", **kw):
        raise RuntimeError("y")
    wdm.route_check = _route_boom
    check("(a) route unreadable", gate(PORTRAIT) == "the route of profile could not be read (y)",
          gate(PORTRAIT))
finally:
    imagegen_base.media_generation_enabled = orig["mge"]
    generation_pause.is_paused = orig["paused"]
    figure_build.auto_build_on = orig["auto"]
    wdm.route_check = orig["route"]
    wdm.BUILD_EXPLICIT = orig["explicit"]
    if orig["renders"] is not None:
        model_refs.auto_renders_enabled = orig["renders"]
    else:
        delattr(model_refs, "auto_renders_enabled")
reader = getattr(model_refs, "auto_renders_enabled", None)
check("(a) public reader exists", callable(reader))
check("(a) public reader = world switch", callable(reader)
      and reader() is True and reader() == model_refs._enabled())

# ── (b) world props count outside the box ────────────────────────────────
print("(b) set_build_bounds counts world props")
WELL = props.create_prop(name="Demo Well", category="outdoor", width_m=2, depth_m=2,
                         height_m=1.5, tags=["water", "stone"], mount="floor")["id"]
wp.save_world_prop({"prop_id": WELL, "x": 1000, "z": 0})
run = wr.create_run("polish", "m", "p", "u", 80, 300000)


def call(tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=1), tool, args)


r = call("set_build_bounds", {"min_x": 0, "min_z": -100, "max_x": 300, "max_z": 100})
check("(b) exact line", r.ok and r.line == (
    "build bounds of this run: x 0…300, z -100…100; warning: 1 place / area / prop lies "
    "outside — they stay, the box only guides new writes"), r.line)

# ── (c) kept rooms carry their stored name in the refusal ────────────────
print("(c) room names in the slot refusal")
upsert_location({"id": "loc_demo_keep", "name": "Demo Keep", "pos_x": 50.0, "pos_z": 0.0,
                 "yaw_deg": 0.0, "rooms": [{"id": "r1", "name": "Demo Hall"}]},
                sync_world=False)
r = call("update_location", {"id": "loc_demo_keep", "patch": {
    "rooms": [{"id": "r1"}], "npc_slots": [{"role": "Demo guard", "room": "rX"}]}})
check("(c) refused", not r.ok, r.line)
check("(c) names r1 \"Demo Hall\"", 'r1 "Demo Hall"' in r.line, r.line)
r = call("update_location", {"id": "loc_demo_keep", "patch": {
    "rooms": [{"id": "rZ"}], "npc_slots": [{"role": "Demo guard", "room": "rZ"}]}})
check("(c) unknown sent room id named", not r.ok and (
    "room id 'rZ' does not exist in loc_demo_keep — omit the id for a new room") in r.line
      and "must be a room id" not in r.line, r.line)

# ── (d) explicit slot value refusals, no WARNING ─────────────────────────
print("(d) npc_slots values")


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


cap = _Capture()
npc_spawn.logger.addHandler(cap)
try:
    for label, extra, field in (
            ("when whenever", {"when": "whenever"}, "when"),
            ("count_max 25", {"count_max": 25}, "count_max"),
            ("count_min -1", {"count_min": -1}, "count_min"),
            ("count_min 1.5", {"count_min": 1.5}, "count_min"),
            ("count_min inf", {"count_min": float("inf")}, "count_min"),
            ("count_min True", {"count_min": True}, "count_min"),
            ("max below min", {"count_min": 3, "count_max": 2}, "count_max"),
            ("max below default min", {"count_max": 0}, "count_max"),
            ("radius -5", {"radius_m": -5}, "radius_m"),
            ("radius string", {"radius_m": "10"}, "radius_m")):
        r = call("update_location", {"id": "loc_demo_keep", "patch": {
            "npc_slots": [{"role": "Demo guard", **extra}]}})
        check(f"(d) {label} refused explicitly", not r.ok
              and r.line.startswith(f"error: 'npc_slots[0].{field}' must")
              and "would be stored as" not in r.line, r.line)
    warnings = [rec for rec in cap.records if rec.levelno >= logging.WARNING]
    check("(d) no WARNING logged", warnings == [], [rec.getMessage() for rec in warnings])
finally:
    npc_spawn.logger.removeHandler(cap)
r = call("update_location", {"id": "loc_demo_keep", "patch": {"npc_slots": [
    {"role": "Demo guard", "when": "18:00-02:00", "count_min": 0, "count_max": 20,
     "radius_m": 0}]}})
check("(d) control slot ok", r.ok, r.line)
check("(d) SLOT_COUNT_MAX 20", getattr(npc_spawn, "SLOT_COUNT_MAX", None) == 20,
      getattr(npc_spawn, "SLOT_COUNT_MAX", None))
_old_max = getattr(npc_spawn, "SLOT_COUNT_MAX", None)
npc_spawn.SLOT_COUNT_MAX = 3
try:
    clamped = (npc_spawn.normalize_slot({"role": "Demo guard", "count_max": 5}) or {}).get(
        "count_max")
finally:
    if _old_max is None:
        delattr(npc_spawn, "SLOT_COUNT_MAX")
    else:
        npc_spawn.SLOT_COUNT_MAX = _old_max
check("(d) clamp reads SLOT_COUNT_MAX", clamped == 3, clamped)

# ── (e) verify-only items ────────────────────────────────────────────────
print("(e) verify-only")
proc = subprocess.run(
    [sys.executable, "-W", "error::SyntaxWarning", "-c",
     "import py_compile, sys; py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)",
     str(REPO / "app/core/world_dev_media.py"), str(ROOT / "world_dev_media.pyc")],
    capture_output=True, text=True)
check("(e) world_dev_media compiles without SyntaxWarning", proc.returncode == 0,
      proc.stderr[-500:])

tree = ast.parse((REPO / "app/models/events.py").read_text(encoding="utf-8"))
fn = next((n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "add_stat_hit"), None)
locked = False
for node in ast.walk(fn) if fn else []:
    if isinstance(node, ast.With):
        for item in node.items:
            c = item.context_expr
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == "keyed_lock" and c.args
                    and isinstance(c.args[0], ast.Constant) and c.args[0].value == "world_event"):
                locked = True
check("(e) add_stat_hit holds keyed_lock(\"world_event\", …)", locked)

if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all ok")
