#!/usr/bin/env python3
"""Smoke run for the nav grid: A* routing + string-pulling + segment costs
(Seamless World, E3 Task 1).

Runs against a THROWAWAY storage directory — never touches a real world.

Grid rules used to derive every number below by hand:
  NAV_CELL_M = 2.0; cell index i = floor(x / 2), its centre is 2*i + 1
  (same for z), its square is [2*i, 2*i+2]. A cell is blocked when the
  TERRAIN at its centre is not passable, or when a FOREIGN placed
  footprint OVERLAPS the cell square (footprints containing the start or
  the goal are exempt). Costs are game-seconds at 1 m/s: metres /
  speed_factor. Shared catalog: grass 1.0 · forest 0.7 · path 1.2 ·
  water impassable (0.0).

Hand-derived expectations:

  [1] Empty world (no areas, no locations). route((0,0), (20,0)):
      A* walks the cell row, string-pulling then drops every intermediate
      centre because the straight line (0,0)->(20,0) is grass all the way
      -> exactly [(0,0), (20,0)]. segment_costs -> [20.0]
      (20 m / factor 1.0 = 20 game-seconds).
      route((4,4), (4,4)) collapses to ONE waypoint, costs []: (4,4) is
      NOT a cell centre (its cell (2,2) is centred on (5,5)), so the raw
      point list is start/centre/goal and must survive smoothing as a
      single point. Non-finite coordinates raise ValueError.

  [2] Water barrier x in [8,12], z in [-6,6] between the same two points.
      Its blocked cells are the centres 9/11 (i=4,5) and -5..5 (j=-3..2),
      so the grid barrier spans x [8,12] x z [-6,6] and the route has to
      round a corner at |z| >= 7: roughly (0,0) -> (7,-7) -> (13,-7) ->
      (20,0), about 9.9 + 6 + 9.9 = 25.8 m. Checked: route exists, every
      waypoint is passable, the whole polyline sampled every 0.3 m never
      touches water, and the length is > the 20 m airline (and < 40 m).
      Repeating the call gives the IDENTICAL polyline (determinism), with
      and without a rebuilt context.

  [3] Path corridor x in [0,20], z in [98,102] (speed_factor 1.2).
      segment_costs([(0,100), (20,100)]) samples the midpoints of ten 2 m
      sub-segments (n = ceil(20 / 2)), all inside the corridor
      -> 20 / 1.2 = 16.6667 s. route over the corridor is the straight
      2-point line with the same cost.

  [4] Lake x in [100,140], z in [-20,20]; goal (120,0) sits 18 m deep
      inside it — far beyond the 2-cell (<= ~4 m) rescue radius
      -> route((0,0), (120,0)) is None.

  [5] Barn at (60,0), plan_width_m 10, yaw 0 -> footprint x [55,65],
      z [-5,5]:
      a) route((40,0), (80,0)): the barn is FOREIGN to both endpoints, so
         the route rounds it — no waypoint inside the footprint, NO
         SEGMENT intersecting it (exact segment-vs-rectangle test, not
         sampling), length > the 40 m airline.
      b) route((40,0), (60,0)): the goal lies inside the barn, so that
         footprint is exempt -> straight [(40,0), (60,0)], cost [20.0].
      c) route((60,0), (80,0)): same for a start inside the barn.

  [6] Rescue: water patch x in [198,202], z in [-2,2]. The start (200,0)
      lies in it and its own cell centre (201,1) is blocked; the nearest
      passable cell (201,3) is 1 cell away, inside the 2-cell rescue
      radius -> route((200,0), (220,0)) exists, keeps (200,0) as its first
      waypoint (the character really stands there) and every LATER
      waypoint is passable. Costs stay finite (the factor is clamped at
      MIN_SPEED_FACTOR, so leaving the puddle is expensive, not infinite).

  [7] Slow terrain must survive the smoothing. Forest x in [40,60],
      z in [190,210] (factor 0.7), route (0,200) -> (100,200):
      the straight line is 100 m, 20 m of it forest
      -> 80/1.0 + 20/0.7 = 80 + 28.571 = 108.571 s.
      Rounding the forest on grass costs roughly
      2*sqrt(40^2 + 11^2) + 20 = 2*41.48 + 20 = 102.96 s (the crossing
      has to happen at |z-200| >= 11, the first free cell row).
      A cost-blind string-pull would replace the detour by the straight
      line (shorter, but 5.6 s slower) — so: > 2 waypoints and a total
      cost below the 108.571 s of the straight line.

  [8] The two geometry helpers, hand-derived (see their docstrings):
      segment_hits_footprint over the unit-ish square at (0,0) w 2 yaw 0
      -> (-5,0)->(5,0) True (enters at t=0.4), (-5,2)->(5,2) False.
      footprint_hits_aabb for (0,0) w 2 yaw 45 (corners at ±sqrt(2) on the
      axes) -> cell [0,2]x[0,2] True, cell [1,3]x[1,3] False.
      placed_footprint refuses a non-finite position.

  [9] Rotated footprint (the corner-cutting repro): mill at (500,0),
      plan_width_m 14, yaw 45 -> a diamond with corners at
      (500 ± 9.90, 0) and (500, ±9.90) (7*sqrt(2) = 9.90). The straight
      line (480,0)->(520,0) runs through its centre, so the route must
      round it: no segment may intersect the footprint (exact test) and
      the length must exceed the 40 m airline.

 [10] Diagonal squeeze: water at x [300,302] z [300,302] (cell centre
      (301,301)) and x [302,304] z [302,304] (centre (303,303)) touch at
      the corner (302,302). route((301,303), (303,301)) may NOT step
      through that corner: both diagonal orthogonals are blocked, so the
      2.83 m airline is impossible and the route has to walk around one of
      the blocks (> 4.5 m).

 [11] Cache: build_nav_context() returns the SAME object twice;
      invalidate_nav_cache() forces a rebuild; painting an area (terrain
      signature) and moving a placed location (placement hash) each
      invalidate it on their own.

Usage:  ./.venv/bin/python scripts/smoke_nav_grid.py
"""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="nav-grid-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="nav-grid-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import nav_grid, terrain_query  # noqa: E402
from app.core.world_geometry import (  # noqa: E402
    footprint_hits_aabb, placed_footprint, point_in_footprint,
    segment_hits_footprint)
from app.models import terrain  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location,
    update_location_position)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'✓' if ok else '✗'} {label}"
          + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def approx(label, actual, expected, tol=1e-6):
    global CHECKED
    CHECKED += 1
    ok = isinstance(actual, (int, float)) and abs(actual - expected) <= tol
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected ≈{expected!r}"))
    if not ok:
        FAILURES.append(label)


def raises_value_error(label, fn):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except ValueError as e:
        print(f"  ✓ {label}: ValueError({str(e)!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  ✗ {label}: {type(e).__name__}({e}) — expected ValueError")
        FAILURES.append(label)
        return
    print(f"  ✗ {label}: no exception — expected ValueError")
    FAILURES.append(label)


def set_plan_width(location_id: str, width: float) -> None:
    """Scale anchor of a location (map3d.plan_width_m) — the footprint edge."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d["plan_width_m"] = width
            loc["map3d"] = map3d
    _save_world_data(data)


def set_yaw(location_id: str, yaw_deg: float) -> None:
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc["yaw_deg"] = yaw_deg
    _save_world_data(data)


def polyline_length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def polyline_samples(pts, step=0.3):
    """Every point along the polyline at `step` metres, endpoints included."""
    out = []
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        length = math.dist(pts[i], pts[i + 1])
        n = max(1, int(math.ceil(length / step)))
        for k in range(n + 1):
            t = k / n
            out.append((x0 + (x1 - x0) * t, z0 + (z1 - z0) * t))
    return out


def all_passable(pts):
    """(ok, first offending point) — independent terrain check per point."""
    for x, z in pts:
        if not terrain_query.passability_at(x, z)[0]:
            return False, (round(x, 2), round(z, 2))
    return True, None


def segments_hitting(pts, cx, cz, width, yaw):
    """Segments of the polyline that intersect a footprint — EXACT test."""
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)
            if segment_hits_footprint(pts[i][0], pts[i][1], pts[i + 1][0],
                                      pts[i + 1][1], cx, cz, width, yaw)]


# ── [1] empty world ─────────────────────────────────────────────────────
print("[1] empty world: the straight line survives string-pulling")
r = nav_grid.route((0, 0), (20, 0))
check("route((0,0),(20,0))", r, [(0.0, 0.0), (20.0, 0.0)])
costs = nav_grid.segment_costs(r, nav_grid.build_nav_context())
check("segment count", len(costs), 1)
approx("segment_costs[0]", costs[0], 20.0)

r0 = nav_grid.route((4, 4), (4, 4))
check("same-point route is ONE waypoint (off-centre point)", r0,
      [(4.0, 4.0)])
check("degenerate costs", nav_grid.segment_costs(r0), [])

raises_value_error("NaN start raises",
                   lambda: nav_grid.route((float("nan"), 0), (10, 0)))
raises_value_error("inf goal raises",
                   lambda: nav_grid.route((0, 0), (float("inf"), 0)))

# ── [2] water barrier ───────────────────────────────────────────────────
print("[2] a water barrier forces a detour")
terrain.save_area({"kind": "water",
                   "polygon": [[8, -6], [12, -6], [12, 6], [8, 6]],
                   "z_order": 0})
r = nav_grid.route((0, 0), (20, 0))
check_true("route exists", r is not None, f"{r}")
if r:
    check_true("first waypoint is the start", r[0] == (0.0, 0.0), f"{r[0]}")
    check_true("last waypoint is the goal", r[-1] == (20.0, 0.0), f"{r[-1]}")
    ok, bad = all_passable(r)
    check_true("every waypoint is passable", ok, f"blocked at {bad}")
    ok, bad = all_passable(polyline_samples(r))
    check_true("polyline never enters the water (0.3 m samples)", ok,
               f"blocked at {bad}")
    length = polyline_length(r)
    check_true("longer than the 20 m airline", length > 20.0,
               f"{length:.2f} m")
    check_true("detour stays near the hand estimate (~25.8 m)",
               length < 40.0, f"{length:.2f} m")
    check("deterministic on repeat", nav_grid.route((0, 0), (20, 0)), r)
    nav_grid.invalidate_nav_cache()
    check("deterministic with a rebuilt context",
          nav_grid.route((0, 0), (20, 0)), r)

# ── [3] path corridor ───────────────────────────────────────────────────
print("[3] a faster corridor is worth 1/1.2 of the time")
terrain.save_area({"kind": "path",
                   "polygon": [[0, 98], [20, 98], [20, 102], [0, 102]],
                   "z_order": 1})
costs = nav_grid.segment_costs([(0, 100), (20, 100)])
check("segment count", len(costs), 1)
approx("20 m of path cost 20/1.2 s", costs[0], 20.0 / 1.2)
r = nav_grid.route((0, 100), (20, 100))
check("corridor route", r, [(0.0, 100.0), (20.0, 100.0)])
approx("corridor route cost", nav_grid.segment_costs(r)[0], 20.0 / 1.2)

# ── [4] goal inside a lake ──────────────────────────────────────────────
print("[4] a goal deep inside water is unreachable")
terrain.save_area({"kind": "water",
                   "polygon": [[100, -20], [140, -20], [140, 20], [100, 20]],
                   "z_order": 0})
check("route into the lake", nav_grid.route((0, 0), (120, 0)), None)

# ── [5] footprints ──────────────────────────────────────────────────────
print("[5] a foreign footprint blocks, the endpoint's own does not")
barn = add_location(name="Smoke Barn", description="nav-grid smoke")
BARN_ID = barn["id"]
update_location_position(BARN_ID, 60.0, 0.0)
set_plan_width(BARN_ID, 10.0)

r = nav_grid.route((40, 0), (80, 0))
check_true("route around the barn exists", r is not None, f"{r}")
if r:
    inside = [p for p in r if point_in_footprint(p[0], p[1], 60, 0, 10, 0)]
    check("no waypoint inside the foreign footprint", inside, [])
    check("no SEGMENT intersects the footprint (exact test)",
          segments_hitting(r, 60, 0, 10, 0), [])
    length = polyline_length(r)
    check_true("longer than the 40 m airline", length > 40.0,
               f"{length:.2f} m")

r = nav_grid.route((40, 0), (60, 0))
check("goal footprint is exempt", r, [(40.0, 0.0), (60.0, 0.0)])
approx("straight cost", nav_grid.segment_costs(r)[0], 20.0)
r = nav_grid.route((60, 0), (80, 0))
check("start footprint is exempt", r, [(60.0, 0.0), (80.0, 0.0)])

# ── [6] blocked start cell ──────────────────────────────────────────────
print("[6] a start on a blocked cell is rescued to the nearest passable one")
terrain.save_area({"kind": "water",
                   "polygon": [[198, -2], [202, -2], [202, 2], [198, 2]],
                   "z_order": 0})
check("the start really stands in water",
      terrain_query.passability_at(200, 0)[0], False)
r = nav_grid.route((200, 0), (220, 0))
check_true("route out of the puddle exists", r is not None, f"{r}")
if r:
    check("first waypoint stays the real start", r[0], (200.0, 0.0))
    check("last waypoint is the goal", r[-1], (220.0, 0.0))
    ok, bad = all_passable(r[1:])
    check_true("every waypoint after the start is passable", ok,
               f"blocked at {bad}")
    costs = nav_grid.segment_costs(r)
    check_true("costs are finite and positive",
               costs and all(math.isfinite(c) and c > 0 for c in costs),
               f"{[round(c, 2) for c in costs]}")

# ── [7] cost-aware smoothing ────────────────────────────────────────────
print("[7] the detour around slow terrain survives the string-pulling")
terrain.save_area({"kind": "forest",
                   "polygon": [[40, 190], [60, 190], [60, 210], [40, 210]],
                   "z_order": 0})
straight = nav_grid.segment_costs([(0, 200), (100, 200)])[0]
approx("straight line through the forest costs 80 + 20/0.7",
       straight, 80.0 + 20.0 / 0.7, tol=1e-6)
r = nav_grid.route((0, 200), (100, 200))
check_true("route exists", r is not None, f"{r}")
if r:
    total = sum(nav_grid.segment_costs(r))
    check_true("the route is NOT the straight line", len(r) > 2,
               f"{len(r)} waypoints: {r}")
    check_true("and it is cheaper than crossing the forest",
               total < straight - 1.0,
               f"{total:.2f} s vs {straight:.2f} s "
               f"(hand estimate for rounding it: ~102.96 s)")
    length = polyline_length(r)
    check_true("longer in METRES than the 100 m airline", length > 100.0,
               f"{length:.2f} m")

# ── [8] geometry helpers ────────────────────────────────────────────────
print("[8] the exact geometry helpers, hand-derived")
check("segment through the footprint",
      segment_hits_footprint(-5, 0, 5, 0, 0, 0, 2, 0), True)
check("segment passing 2 m beside it",
      segment_hits_footprint(-5, 2, 5, 2, 0, 0, 2, 0), False)
check("segment ending before it",
      segment_hits_footprint(-5, 0, -2, 0, 0, 0, 2, 0), False)
check("cell [0,2]x[0,2] overlaps the yaw-45 square",
      footprint_hits_aabb(0, 0, 2, 45, 0, 0, 2, 2), True)
check("cell [1,3]x[1,3] does not",
      footprint_hits_aabb(0, 0, 2, 45, 1, 1, 3, 3), False)
check("a non-finite position has no footprint",
      placed_footprint({"pos_x": float("nan"), "pos_z": 0.0,
                        "map3d": {"plan_width_m": 10}}), None)
check("a sane position still has one",
      placed_footprint({"pos_x": 5.0, "pos_z": 6.0,
                        "map3d": {"plan_width_m": 10}}), (5.0, 6.0, 10.0, 0.0))

# ── [9] rotated footprint ───────────────────────────────────────────────
print("[9] a rotated footprint is rounded, not clipped")
mill = add_location(name="Smoke Mill", description="nav-grid smoke")
MILL_ID = mill["id"]
update_location_position(MILL_ID, 500.0, 0.0)
set_plan_width(MILL_ID, 14.0)
set_yaw(MILL_ID, 45.0)
check_true("the airline really crosses the mill",
           segment_hits_footprint(480, 0, 520, 0, 500, 0, 14, 45), "")
r = nav_grid.route((480, 0), (520, 0))
check_true("route around the mill exists", r is not None, f"{r}")
if r:
    check("no SEGMENT intersects the rotated footprint",
          segments_hitting(r, 500, 0, 14, 45), [])
    inside = [p for p in r if point_in_footprint(p[0], p[1], 500, 0, 14, 45)]
    check("no waypoint inside it", inside, [])
    length = polyline_length(r)
    check_true("longer than the 40 m airline", length > 40.0,
               f"{length:.2f} m")

# ── [10] diagonal squeeze ───────────────────────────────────────────────
print("[10] no squeezing diagonally between two corner-touching blocks")
terrain.save_area({"kind": "rock",
                   "polygon": [[300, 300], [302, 300], [302, 302], [300, 302]],
                   "z_order": 0})
terrain.save_area({"kind": "rock",
                   "polygon": [[302, 302], [304, 302], [304, 304], [302, 304]],
                   "z_order": 0})
check("cell centre (301,301) is blocked",
      terrain_query.passability_at(301, 301)[0], False)
check("cell centre (303,303) is blocked",
      terrain_query.passability_at(303, 303)[0], False)
r = nav_grid.route((301, 303), (303, 301))
check_true("route exists", r is not None, f"{r}")
if r:
    length = polyline_length(r)
    check_true("it walks around instead of through the corner "
               "(airline is 2.83 m)", length > 4.5, f"{length:.2f} m")
    inside = [p for p in r if not terrain_query.passability_at(*p)[0]]
    check("no waypoint on rock", inside, [])

# ── [11] cache ──────────────────────────────────────────────────────────
print("[11] the context is cached on terrain + placement signature")
ctx_a = nav_grid.build_nav_context()
check_true("second build hits the cache",
           nav_grid.build_nav_context() is ctx_a, "")
nav_grid.invalidate_nav_cache()
ctx_b = nav_grid.build_nav_context()
check_true("invalidate_nav_cache() forces a rebuild", ctx_b is not ctx_a, "")
check("the default ground is resolved once into the context",
      ctx_b.default_kind, terrain_query.default_kind())
area = terrain.save_area({"kind": "sand",
                          "polygon": [[400, 400], [410, 400], [410, 410],
                                      [400, 410]],
                          "z_order": 0})
ctx_c = nav_grid.build_nav_context()
check_true("painting an area invalidates the cache", ctx_c is not ctx_b, "")
terrain.delete_area(area["id"])
nav_grid.build_nav_context()
update_location_position(BARN_ID, 61.0, 0.0)
ctx_d = nav_grid.build_nav_context()
check_true("moving a placed location invalidates the cache",
           ctx_d is not ctx_c, "")

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
