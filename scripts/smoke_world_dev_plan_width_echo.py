#!/usr/bin/env python3
"""Smoke: World Dev free mode — a stored map3d sent back with its derived
``plan_width_m`` is accepted (follow-up to plan
docs/superpowers/plans/2026-11-25-world-dev-free-fixes.md, Task 11 / F9).

A temp world (paths.init BEFORE any world-DB import), an empty
ANIMATION_CLIPS_DIR; no server, no LLM. Every call goes through
``world_dev_tools.run_tool`` as the agent loop calls it.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_plan_width_echo.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------
``plan_width_m`` is derived by world_ops._sanitize_map3d as the wider side of
the boundary's bounding box (world_geometry.polygon_plan_width_m). The seed
square of create_location without an outline is map_layout_apply.SEED_BOUNDARY_M
= 10 m wide (±5 around the pin) -> plan_width_m 10.0.

  (a) create_location "Demo Hut" at (100,100), no boundary -> ok; stored
      map3d.plan_width_m == 10.0.
  (b) update_location{hut, patch {map3d: <the stored map3d, unchanged>}} -> ok
      (before the fix: "unknown map3d key(s) plan_width_m"); plan_width_m
      still 10.0.
  (c) patch {map3d: {plan_width_m: 10}} (no boundary: compared with the stored
      outline, 10 m) -> ok.
  (d) patch {map3d: {plan_width_m: 12}} -> refused; the line has
      "derived by the writer from map3d.boundary (here 10 m)"; plan_width_m
      still 10.0.
  (e) patch {map3d: {plan_width_m: true}} -> refused (a bool is no width).
  (f) patch {map3d: {boundary ±8 square, plan_width_m: 16}} -> box 16 × 16,
      derived 16 -> ok; stored plan_width_m == 16.0.
  (g) patch {map3d: {boundary ±8 square, plan_width_m: 10}} -> refused
      "(here 16 m)".
  (h) create_location "Demo Shed" at (200,100), data.map3d {plan_width_m: 10}
      and no boundary -> the seed square, 10 m -> ok, stored 10.0.
  (i) create_location "Demo Shack" at (300,100), data.map3d {plan_width_m: 7}
      -> refused "(here 10 m)"; no place Demo Shack.
  (j) create_location "Demo Barn" at (400,100), boundary [[0,0],[6,0],[6,4]],
      data.map3d {plan_width_m: 6} -> box 6 × 4 -> 6 -> ok.
  (k) undo(run) -> complete; no Demo place is left.

A place WITH a floor plan (stored outside any run through models.world
.upsert_location, which keeps map3d as given): boundary ±5 square, outline
±4 square, wall_kind "stone", level_walls {"0": "wood"}. The same run again
(its first part is already undone):
  (l) update_location{plot, patch {map3d: <the stored map3d> + floors 2}} -> ok
      (before: "map3d.outline is part of the floor plan"); floors 2 stored,
      outline / wall_kind / level_walls unchanged.
  (m) patch {map3d: {wall_kind: "brick"}} -> refused "set in the floor-plan
      editor"; wall_kind still "stone".
  (n) patch {map3d: {outline: ±3 square}} -> refused "part of the floor plan";
      outline still the ±4 square.
  (o) undo(run) -> complete; floors absent again, outline unchanged.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_pw_echo_"))
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

from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models.world import get_location_by_id, list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


run = wr.create_run("pw-echo", "m", "p", "u", 80, 300000)


def call(tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=1), tool, args)


def by_name(name):
    return [loc for loc in list_locations() if loc.get("name") == name]


def width(lid):
    return ((get_location_by_id(lid) or {}).get("map3d") or {}).get("plan_width_m")


SQ8 = [[-8, -8], [8, -8], [8, 8], [-8, 8]]

r = call("create_location", {"data": {"name": "Demo Hut"}, "x": 100, "z": 100})
check("(a) ok", r.ok, r.line)
hut = (by_name("Demo Hut") or [{}])[0].get("id", "")
check("(a) seed width 10", width(hut) == 10.0, width(hut))

stored = dict(get_location_by_id(hut).get("map3d") or {})
r = call("update_location", {"id": hut, "patch": {"map3d": stored}})
check("(b) echo of the stored map3d ok", r.ok, r.line)
check("(b) width still 10", width(hut) == 10.0, width(hut))

r = call("update_location", {"id": hut, "patch": {"map3d": {"plan_width_m": 10}}})
check("(c) plan_width_m 10 alone ok", r.ok, r.line)

r = call("update_location", {"id": hut, "patch": {"map3d": {"plan_width_m": 12}}})
check("(d) refused", not r.ok, r.line)
check("(d) says derived, here 10 m",
      "derived by the writer from map3d.boundary (here 10 m)" in r.line, r.line)
check("(d) width still 10", width(hut) == 10.0, width(hut))

r = call("update_location", {"id": hut, "patch": {"map3d": {"plan_width_m": True}}})
check("(e) bool refused", not r.ok, r.line)

r = call("update_location", {"id": hut, "patch": {"map3d": {"boundary": SQ8,
                                                            "plan_width_m": 16}}})
check("(f) redraw with matching width ok", r.ok, r.line)
check("(f) width 16", width(hut) == 16.0, width(hut))

r = call("update_location", {"id": hut, "patch": {"map3d": {"boundary": SQ8,
                                                            "plan_width_m": 10}}})
check("(g) refused", not r.ok, r.line)
check("(g) here 16 m", "(here 16 m)" in r.line, r.line)

r = call("create_location", {"data": {"name": "Demo Shed", "map3d": {"plan_width_m": 10}},
                             "x": 200, "z": 100})
check("(h) ok", r.ok, r.line)
shed = (by_name("Demo Shed") or [{}])[0].get("id", "")
check("(h) width 10", width(shed) == 10.0, width(shed))

r = call("create_location", {"data": {"name": "Demo Shack", "map3d": {"plan_width_m": 7}},
                             "x": 300, "z": 100})
check("(i) refused", not r.ok, r.line)
check("(i) here 10 m", "(here 10 m)" in r.line, r.line)
check("(i) no Demo Shack", by_name("Demo Shack") == [])

r = call("create_location", {"data": {"name": "Demo Barn", "map3d": {"plan_width_m": 6}},
                             "x": 400, "z": 100, "boundary": [[0, 0], [6, 0], [6, 4]]})
check("(j) ok", r.ok, r.line)
barn = (by_name("Demo Barn") or [{}])[0].get("id", "")
check("(j) width 6", width(barn) == 6.0, width(barn))

res = wu.undo(run)
check("(k) undo complete", res.get("complete"), res)
check("(k) no Demo place left",
      not [loc for loc in list_locations() if str(loc.get("name", "")).startswith("Demo ")])

from app.models.world import upsert_location  # noqa: E402

SQ4 = [[-4, -4], [4, -4], [4, 4], [-4, 4]]
upsert_location({"id": "plot_a", "name": "Plot A", "x": 600, "z": 100,
                 "rooms": [{"id": "plot_a_yard", "name": "Yard"}],
                 "map3d": {"boundary": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
                           "outline": SQ4, "wall_kind": "stone",
                           "level_walls": {"0": "wood"}}}, sync_world=False)


def m3(lid):
    return (get_location_by_id(lid) or {}).get("map3d") or {}


echo = dict(m3("plot_a"))
echo["floors"] = 2
r = call("update_location", {"id": "plot_a", "patch": {"map3d": echo}})
check("(l) floor-plan echo + floors ok", r.ok, r.line)
check("(l) floors 2", m3("plot_a").get("floors") == 2, m3("plot_a"))
check("(l) plan keys unchanged",
      m3("plot_a").get("outline") == SQ4 and m3("plot_a").get("wall_kind") == "stone"
      and m3("plot_a").get("level_walls") == {"0": "wood"}, m3("plot_a"))

r = call("update_location", {"id": "plot_a", "patch": {"map3d": {"wall_kind": "brick"}}})
check("(m) changed editor key refused", not r.ok and "floor-plan editor" in r.line, r.line)
check("(m) wall_kind still stone", m3("plot_a").get("wall_kind") == "stone")

r = call("update_location", {"id": "plot_a", "patch": {"map3d": {
    "outline": [[-3, -3], [3, -3], [3, 3], [-3, 3]]}}})
check("(n) changed outline refused", not r.ok and "part of the floor plan" in r.line, r.line)
check("(n) outline still ±4", m3("plot_a").get("outline") == SQ4)

res = wu.undo(run)
check("(o) undo complete", res.get("complete"), res)
check("(o) floors absent again", "floors" not in m3("plot_a"), m3("plot_a"))
check("(o) outline unchanged", m3("plot_a").get("outline") == SQ4)

print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
