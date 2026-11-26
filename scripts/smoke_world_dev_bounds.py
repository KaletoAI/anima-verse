#!/usr/bin/env python3
"""Smoke: World Dev free mode — build bounds per run (P3 Task 2, gap 27, E3).

Plan docs/superpowers/plans/2026-11-25-world-dev-free-p3-world-systems.md, Task 2.
A temp world (STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR temp, paths.init
BEFORE any world-DB import), empty; no server, no LLM. Tool calls go through
``world_dev_tools.run_tool`` exactly as the agent loop calls them.

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_bounds.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The box of every case is B = x -150…150, z -150…150 (300 × 300 m, the
manual's "small village"). A point is outside when x < min_x or x > max_x or
z < min_z or z > max_z (map_layout_apply.point_outside — the box edge itself is
inside).

create_location without a boundary STORES the seed square
(map_layout_apply.seed_boundary: SEED_BOUNDARY_M = 10, a square ±5 m around the
pin, 4 corners), so such a place yields 5 points: its pin + the 4 world corners
(yaw 0: pin ± 5 on both axes). A place made elsewhere without a stored outline
is its pin only (case k).

  (a) empty world: world_overview{} has the line "extent: none yet" (no place,
      no area — current_world_bounds() is None) and the line
      "build bounds: none — set_build_bounds{min_x, min_z, max_x, max_z} first
      in an empty world" (no box on the run yet); no line starts "bounds:".
  (b) set_build_bounds{B} -> ok, the line is exactly
      "build bounds of this run: x -150…150, z -150…150" (nothing built, so
      no warning); wr.get_run(run)["bounds"] == {"min_x": -150.0, "min_z":
      -150.0, "max_x": 150.0, "max_z": 150.0}; the call's journal row is kind
      "read" and no write row exists.
  (c) refused, the stored box unchanged: x side 10 (0…10, < 50); min_x 5 >
      max_x -5; x side 20002 (-10001…10001, > 20000); min_x "a" (not a
      number); max_z missing; an unknown key.
  (d) create_location "Demo Hut" at (140, 0) -> outline x 135…145, z -5…5,
      all inside B -> ok, no "build bounds" in the line. "Demo Hut" again at
      (200, 0): pin 200 > 150, corners x 195 and 205 > 150 -> all 5 points
      outside -> ok with 'place "Demo Hut": 5 of 5 points lie outside the
      build bounds'. world_overview{} then: "extent: x 135…205, z -5…5" — a
      place without a drawn outline counts with its pin and seed square
      (hut 1 x 135…145, hut 2 x 195…205, both z -5…5).
  (e) add_terrain_area forest [[100,0],[200,0],[200,50],[100,50]] -> ok with
      ": 2 of 4 points lie outside the build bounds" ((200,0) and (200,50)
      have x 200 > 150; the 100s are inside).
  (e2) add_height_area [[300,300],[400,300],[400,400]] height 5 -> ok with
      ": 3 of 3 points lie outside the build bounds" (every x >= 300 > 150).
  (e3) set_build_bounds{B} again -> ok, the line ends
      "; warning: 3 places / areas / props lie outside — they stay, the box
      only guides new writes" (plural for a count other than 1; no world prop
      yet — props count since F10) (the second hut, the forest, the height area; the
      first hut lies wholly inside).
  (e4) world_overview{}: "extent: x 100…205, z -5…50" — current_world_bounds
      reads place outlines and terrain areas (not height areas): huts x
      135…145 and 195…205, z -5…5; forest x 100…200, z 0…50 -> min x 100,
      max x 205, min z -5, max z 50. "build bounds: x -150…150, z -150…150".
  (f) place_world_prop at (0, 0) -> ok, no "warnings" (open grass, inside B).
      At (160, -20) -> ok with "(160,-20) lies outside the build bounds"
      (one point: the single-point wording; x 160 > 150).
  (f2) place_location second hut -> (0, 60): pin and corners x -5…5, z 55…65,
      inside -> no "build bounds" in the line. update_terrain_area forest
      polygon [[100,0],[140,0],[140,50],[100,50]] -> inside, no warning.
      update_height_area {height_m 6} (no new outline) -> no warning: only
      a call that sends a new outline is judged.
      update_height_area polygon [[300,0],[310,0],[310,10]] -> "3 of 3".
  (g) undo(run) -> complete; no location, terrain area, height area or world
      prop is left; wr.get_run(run)["bounds"] is still B (run metadata, E3 —
      not world data, the undo does not touch it).

After (g) the world is empty again and the run still carries B.

  (h) Areas are judged ONLY against the run's box, never against the built
      extent (E3; _sanitize_layout hands bounds=None to sanitize_map_layout,
      so its "agreed map bounds" line never appears in free mode):
      add_terrain_area forest [[-100,-100],[-80,-100],[-80,-80],[-100,-80]]
      -> inside B, no "bounds" at all in the line. Then forest
      [[50,50],[70,50],[70,70]]: the built extent is now x -100…-80,
      z -100…-80, so this area lies wholly outside the EXTENT but inside B
      -> no "bounds" at all. add_height_area [[0,0],[10,0],[10,10]] height 3
      -> inside B, no "bounds" at all.
  (h2) Outside B: add_terrain_area forest [[140,0],[160,0],[160,10]] ->
      (160,0) and (160,10) have x 160 > 150 -> exactly one out-of-bounds
      line ": 2 of 3 points lie outside the build bounds", "outside" occurs
      once in the line. add_height_area [[140,20],[160,20],[140,30]] -> only
      (160,20) is out -> ": 1 of 3 points lies outside the build bounds"
      (singular verb), "outside" once. update_height_area on the inside hill
      polygon [[20,20],[30,20],[30,30]] -> no "bounds" at all; polygon
      [[200,200],[210,200],[210,210]] -> ": 3 of 3 points lie outside",
      "outside" once. update_terrain_area on the outside forest above with
      only kind "grass" (no polygon/stroke) -> ok, no "bounds" at all: only
      a call that sends a new outline is judged against the box.
  (i) Rotated place: create_location "Demo Tower" at (145, 0) yaw 45. The
      seed square ±5 rotated by 45° puts its corners at distance
      5·√2 = 7.07 on the axes: (152.07,0), (137.93,0), (145,±7.07). Only
      x 152.07 > 150 -> 'place "Demo Tower": 1 of 5 points lies outside the
      build bounds'.
      Box edge is inside: "Demo Mill" at (150, 150), yaw 0: pin (150,150) on
      the edge = inside; corners (145,145) inside, (155,145), (145,155),
      (155,155) outside -> "3 of 5 points lie outside".
  (j) Side limits (50 … 20 000 m, inclusive): x side 50 (0…50) ok; 49.99
      (0…49.99) refused; x side 20000 (-10000…10000) ok; 20000.5 refused;
      min_x NaN / inf / True / "-150" refused ("must be a number" — a bool
      or a numeric string is not a coordinate). Last ok call: the 20000 box;
      after the refusals it is still stored. set_build_bounds{B} restores B.
  (k) F9 (plan 2026-11-25-world-dev-free-fixes.md, Task 11): a place made
      elsewhere WITHOUT a stored outline has no area on the map, so it counts
      with its pin only. undo(run) -> complete, the world is empty again. "Demo
      Post" upserted directly at (148, 0) without map3d. world_overview{}:
      "extent: x 148…148, z 0…0" (before: its assumed seed square gave
      x 143…153, z -5…5). set_build_bounds{B} -> the exact line without a
      warning: the pin x 148 <= 150 is inside (before: the corner x 153 was
      out). place_location{post, 160, 0} -> one point, the single-point
      wording 'place "Demo Post" (160,0) lies outside the build bounds'.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="smoke_wd_bounds_"))
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

from app.core import props  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.models import world_props as wp  # noqa: E402
from app.models.heightfield import list_height_areas  # noqa: E402
from app.models.terrain import list_areas  # noqa: E402
from app.models.world import list_locations  # noqa: E402

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


WELL = props.create_prop(name="Demo Well", category="outdoor", width_m=2, depth_m=2,
                         height_m=1.5, tags=["water", "stone"], mount="floor")["id"]

run = wr.create_run("bounds", "m", "p", "u", 80, 300000)
B = {"min_x": -150, "min_z": -150, "max_x": 150, "max_z": 150}
B_STORED = {"min_x": -150.0, "min_z": -150.0, "max_x": 150.0, "max_z": 150.0}


def call(tool, args):
    return wt.run_tool(wt.ToolCtx(run_id=run, turn=1), tool, args)


def line_of(text, prefix):
    return next((ln for ln in text.splitlines() if ln.startswith(prefix)), None)


def new_id(before, after):
    added = sorted(set(after) - set(before))
    return added[0] if added else ""


# ── (a) empty world ──────────────────────────────────────────────────────
print("(a) empty world")
r = call("world_overview", {})
check("(a) ok", r.ok, r.line)
check("(a) extent none yet", line_of(r.line, "extent: ") == "extent: none yet", r.line)
check("(a) build bounds none", line_of(r.line, "build bounds: ") ==
      "build bounds: none — set_build_bounds{min_x, min_z, max_x, max_z} first in an "
      "empty world", r.line)
check("(a) no old bounds line", line_of(r.line, "bounds:") is None, r.line)

# ── (b) set the box ──────────────────────────────────────────────────────
print("(b) set_build_bounds")
r = call("set_build_bounds", dict(B))
check("(b) ok", r.ok, r.line)
check("(b) exact line", r.line == "build bounds of this run: x -150…150, z -150…150", r.line)
check("(b) stored on the run", (wr.get_run(run) or {}).get("bounds") == B_STORED,
      (wr.get_run(run) or {}).get("bounds"))
last = wr.steps(run)[-1]
check("(b) journal row read", (last.get("tool"), last.get("kind")) ==
      ("set_build_bounds", "read"), (last.get("tool"), last.get("kind")))
check("(b) no write row", wr.entries(run) == [], wr.entries(run))

# ── (c) refusals ─────────────────────────────────────────────────────────
print("(c) refusals")
for label, args in (("side 10", {**B, "min_x": 0, "max_x": 10}),
                    ("min > max", {**B, "min_x": 5, "max_x": -5}),
                    ("side 20002", {**B, "min_x": -10001, "max_x": 10001}),
                    ("not a number", {**B, "min_x": "a"}),
                    ("missing max_z", {k: v for k, v in B.items() if k != "max_z"}),
                    ("unknown key", {**B, "height": 3})):
    r = call("set_build_bounds", args)
    check(f"(c) {label} refused", not r.ok, r.line)
check("(c) box unchanged", (wr.get_run(run) or {}).get("bounds") == B_STORED,
      (wr.get_run(run) or {}).get("bounds"))

# ── (d) places ───────────────────────────────────────────────────────────
print("(d) create_location")
r = call("create_location", {"data": {"name": "Demo Hut"}, "x": 140, "z": 0})
check("(d) inside ok", r.ok, r.line)
check("(d) inside: no bounds warning", "build bounds" not in r.line, r.line)
ids0 = [l["id"] for l in list_locations()]
r = call("create_location", {"data": {"name": "Demo Hut"}, "x": 200, "z": 0})
check("(d) outside ok", r.ok, r.line)
check("(d) 5 of 5 points", 'place "Demo Hut": 5 of 5 points lie outside the build bounds'
      in r.line, r.line)
hut2 = new_id(ids0, [l["id"] for l in list_locations()])
check("(d) second hut id", bool(hut2), hut2)
r = call("world_overview", {})
check("(d) extent of the seed squares", line_of(r.line, "extent: ") ==
      "extent: x 135…205, z -5…5", r.line)

# ── (e) areas ────────────────────────────────────────────────────────────
print("(e) areas")
r = call("add_terrain_area", {"kind": "forest",
                              "polygon": [[100, 0], [200, 0], [200, 50], [100, 50]]})
check("(e) terrain ok", r.ok, r.line)
check("(e) 2 of 4", ": 2 of 4 points lie outside the build bounds" in r.line, r.line)
forest = (list_areas() or [{}])[0].get("id")
r = call("add_height_area", {"polygon": [[300, 300], [400, 300], [400, 400]], "height_m": 5})
check("(e2) height ok", r.ok, r.line)
check("(e2) 3 of 3", ": 3 of 3 points lie outside the build bounds" in r.line, r.line)
hill = (list_height_areas() or [{}])[0].get("id")

r = call("set_build_bounds", dict(B))
check("(e3) ok", r.ok, r.line)
check("(e3) warning names 3", r.line == (
    "build bounds of this run: x -150…150, z -150…150; warning: 3 places / areas / props "
    "lie outside — they stay, the box only guides new writes"), r.line)

r = call("world_overview", {})
check("(e4) extent", line_of(r.line, "extent: ") == "extent: x 100…205, z -5…50", r.line)
check("(e4) build bounds", line_of(r.line, "build bounds: ") ==
      "build bounds: x -150…150, z -150…150", r.line)

# ── (f) world props ──────────────────────────────────────────────────────
print("(f) world props")
r = call("place_world_prop", {"prop_id": WELL, "x": 0, "z": 0})
check("(f) inside ok, no warnings", r.ok and "warnings" not in r.line, r.line)
r = call("place_world_prop", {"prop_id": WELL, "x": 160, "z": -20})
check("(f) outside ok", r.ok, r.line)
check("(f) one point wording", "(160,-20) lies outside the build bounds" in r.line, r.line)

# ── (f2) updates ─────────────────────────────────────────────────────────
print("(f2) updates")
r = call("place_location", {"id": hut2, "x": 0, "z": 60})
check("(f2) place_location inside", r.ok and "build bounds" not in r.line, r.line)
r = call("update_terrain_area", {"id": forest,
                                 "polygon": [[100, 0], [140, 0], [140, 50], [100, 50]]})
check("(f2) terrain inside", r.ok and "build bounds" not in r.line, r.line)
r = call("update_height_area", {"id": hill, "height_m": 6})
check("(f2) height without outline: no warning", r.ok and "build bounds" not in r.line,
      r.line)
r = call("update_height_area", {"id": hill, "polygon": [[300, 0], [310, 0], [310, 10]]})
check("(f2) height new outline 3 of 3",
      r.ok and ": 3 of 3 points lie outside the build bounds" in r.line, r.line)

# ── (g) undo ─────────────────────────────────────────────────────────────
print("(g) undo")
u = wu.undo(run)
check("(g) complete", u.get("complete"), u)
check("(g) nothing left", (len(list_locations()), len(list_areas()), len(list_height_areas()),
                           len(wp.list_world_props())) == (0, 0, 0, 0),
      (len(list_locations()), len(list_areas()), len(list_height_areas()),
       len(wp.list_world_props())))
check("(g) bounds stay", (wr.get_run(run) or {}).get("bounds") == B_STORED,
      (wr.get_run(run) or {}).get("bounds"))

# ── (h) areas judged against the box only, never the built extent ────────
print("(h) areas inside B, outside the built extent")
r = call("add_terrain_area", {"kind": "forest",
                              "polygon": [[-100, -100], [-80, -100], [-80, -80], [-100, -80]]})
check("(h) first forest ok, no bounds", r.ok and "bounds" not in r.line, r.line)
r = call("add_terrain_area", {"kind": "forest", "polygon": [[50, 50], [70, 50], [70, 70]]})
check("(h) forest outside the extent, inside B: no bounds",
      r.ok and "bounds" not in r.line, r.line)
r = call("add_height_area", {"polygon": [[0, 0], [10, 0], [10, 10]], "height_m": 3})
check("(h) height inside B: no bounds", r.ok and "bounds" not in r.line, r.line)
hill2 = next((a.get("id") for a in list_height_areas()), None)

print("(h2) areas outside B: one voice")
r = call("add_terrain_area", {"kind": "forest", "polygon": [[140, 0], [160, 0], [160, 10]]})
check("(h2) terrain 2 of 3, one line",
      r.ok and ": 2 of 3 points lie outside the build bounds" in r.line
      and r.line.count("outside") == 1 and "agreed map bounds" not in r.line, r.line)
out_forest = next((a.get("id") for a in list_areas()
                   if any(p[0] == 160 for p in (a.get("polygon") or []))), None)
r = call("add_height_area", {"polygon": [[140, 20], [160, 20], [140, 30]], "height_m": 3})
check("(h2) height 1 of 3 lies, one line",
      r.ok and ": 1 of 3 points lies outside the build bounds" in r.line
      and r.line.count("outside") == 1, r.line)
r = call("update_height_area", {"id": hill2, "polygon": [[20, 20], [30, 20], [30, 30]]})
check("(h2) update inside: no bounds", r.ok and "bounds" not in r.line, r.line)
r = call("update_height_area", {"id": hill2,
                                "polygon": [[200, 200], [210, 200], [210, 210]]})
check("(h2) update outside 3 of 3, one line",
      r.ok and ": 3 of 3 points lie outside the build bounds" in r.line
      and r.line.count("outside") == 1, r.line)
r = call("update_terrain_area", {"id": out_forest, "kind": "grass"})
check("(h2) kind-only update of the outside forest: no bounds",
      out_forest is not None and r.ok and "bounds" not in r.line, r.line)

# ── (i) rotated place, box edge ──────────────────────────────────────────
print("(i) places: yaw and the box edge")
r = call("create_location", {"data": {"name": "Demo Tower"}, "x": 145, "z": 0, "yaw": 45})
check("(i) yaw 45: 1 of 5 lies",
      r.ok and 'place "Demo Tower": 1 of 5 points lies outside the build bounds' in r.line,
      r.line)
r = call("create_location", {"data": {"name": "Demo Mill"}, "x": 150, "z": 150})
check("(i) edge: 3 of 5",
      r.ok and 'place "Demo Mill": 3 of 5 points lie outside the build bounds' in r.line,
      r.line)

# ── (j) side limits and non-numbers ──────────────────────────────────────
print("(j) side limits")
r = call("set_build_bounds", {**B, "min_x": 0, "max_x": 50})
check("(j) side 50 ok", r.ok, r.line)
r = call("set_build_bounds", {**B, "min_x": 0, "max_x": 49.99})
check("(j) side 49.99 refused", not r.ok, r.line)
r = call("set_build_bounds", {**B, "min_x": -10000, "max_x": 10000})
check("(j) side 20000 ok", r.ok, r.line)
r = call("set_build_bounds", {**B, "min_x": -10000, "max_x": 10000.5})
check("(j) side 20000.5 refused", not r.ok, r.line)
for label, bad in (("nan", float("nan")), ("inf", float("inf")), ("bool", True),
                   ("numeric string", "-150")):
    r = call("set_build_bounds", {**B, "min_x": bad})
    check(f"(j) {label} refused", not r.ok and "must be a number" in r.line, r.line)
check("(j) last ok box kept", (wr.get_run(run) or {}).get("bounds") ==
      {**B_STORED, "min_x": -10000.0, "max_x": 10000.0}, (wr.get_run(run) or {}).get("bounds"))
r = call("set_build_bounds", dict(B))
check("(j) B restored", r.ok and (wr.get_run(run) or {}).get("bounds") == B_STORED, r.line)

# ── (k) an outline-less place counts with its pin only ───────────────────
print("(k) outline-less place: pin only")
u = wu.undo(run)
check("(k) undo complete", u.get("complete"), u)
check("(k) world empty", (len(list_locations()), len(list_areas())) == (0, 0),
      (len(list_locations()), len(list_areas())))
from app.models.world import upsert_location  # noqa: E402

upsert_location({"id": "loc_demo_post", "name": "Demo Post", "pos_x": 148.0, "pos_z": 0.0,
                 "yaw_deg": 0.0}, sync_world=False)
r = call("world_overview", {})
check("(k) extent is the pin", line_of(r.line, "extent: ") == "extent: x 148…148, z 0…0",
      r.line)
r = call("set_build_bounds", dict(B))
check("(k) pin inside: no warning",
      r.line == "build bounds of this run: x -150…150, z -150…150", r.line)
r = call("place_location", {"id": "loc_demo_post", "x": 160, "z": 0})
check("(k) one point wording",
      r.ok and 'place "Demo Post" (160,0) lies outside the build bounds' in r.line, r.line)

if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all ok")
