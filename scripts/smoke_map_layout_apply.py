#!/usr/bin/env python3
"""Smoke run for LLM map layouts (Free world map, E10 task 1).

Throwaway storage, throwaway world DB. Every number below is derived BY HAND
from the spec it checks — the ribbon builder from the TS docstring it is a
port of (`frontend/src/tabs/map/mapMath.ts`), the rest from the geometry.

  [1] The ribbon builder (`stroke_to_polygon`), pinned to the very cases the
      TS twin lists, because a river drawn by the model and the same river
      re-generated in the editor must be ONE shape:
        straight [(0,0),(10,0)] width 4 -> offset 2, nA = (0,-1), nB = (0,1)
                 -> [(0,-2),(10,-2),(10,2),(0,2)]      (a plain rectangle)
        90° bend [(0,0),(10,0),(10,10)] width 4: at (10,0) side A joins
                 n1 = (0,-1) with n2 = (1,0); m̂ = (0.7071,-0.7071),
                 cos(θ/2) = 0.7071, miter 2/0.7071 = 2.8284 <= 2×4
                 -> (12,-2), side B mirrors to (8,2)
                 -> [(0,-2),(12,-2),(12,10),(8,10),(8,2),(0,2)]
        collinear [(0,0),(5,0),(10,0)] width 4 -> 2n = 6 points
        hairpin [(0,0),(10,0),(0.4,2.8)] width 4: cos(θ/2) = sqrt(0.02),
                 miter 14.14 > 8 -> BEVEL, 2n+2 = 8 points
        [(0,0),(0,0),(10,0),(10,0)] -> the straight case (dupes dropped)
        [(0,0),(3.14159,0)] width 1.111 -> 2 decimals, always
        [(0,0),(0.001,0)] width 4 -> None (collapses on the 2-decimal grid)
        width 0 / a NaN coordinate / one point -> None

  [2] The decorator (`decorate_stroke`), same source:
        [(0,0),(100,0)] jagged spacing 10 amplitude 2: length 100, deflections
              at 5, 15, …, 95 -> 10 of them, 12 points in all. Normal (0,-1),
              so side A is NEGATIVE z and the sides alternate; every |z| lies
              in [0.8, 2] (DEFLECTION_MIN_FACTOR 0.4 × amplitude … amplitude).
        the same line wavy: the SAME point count and the same positions, but
              NOT the alternating sequence — that is what tells them apart.
        [(0,0),(10,0),(10,10)] jagged: the clicked corner (10,0) survives, at
              index 2 of 5 points.
        [(0,0),(1000,0)] jagged spacing 2: 500 deflections would be 502 points,
              so the cap bites — room = 120 − 2 = 118, spacing 1000/118 =
              8.4745…, 120 points, capped True.
        amplitude 0 / style "straight" -> the input array itself.
      And the PRNG underneath is bit-exact with the editor's
      (`@anima/scene-render.seededRandom`, FNV-1a + xorshift), verified in
      node: seed "terrain:stroke:0,0:100,0" yields
      0.9629154971335083, 0.6272964510135353, 0.04343539662659168, …

  [3] `simplify_polygon` — vertex decimation to a POINT BUDGET.
        a 100-point circle of radius 100 -> exactly 12 points, and the area
              stays within 5 % (regular 12-gon inscribed: 3R² vs πR² = 4.44 %,
              the achievable floor; measured 4.78 %)
        a 4-point square -> untouched (already inside the budget)
        2 points / junk vertices -> [] (never was an area)
      Plus `polygon_self_intersects`: the square False, the bow-tie
      [(0,0),(10,10),(10,0),(0,10)] True (edges 0 and 2 cross at (5,5)).

  [4] `sanitize_map_layout` — the warning vocabulary, all on a hand-built
      catalog + location table, no DB:
        two 40 m footprints 30 m apart (spans [-20,20] and [10,50], sharing
              [10,20])            -> footprint_overlap
        the same two 50 m apart (spans [-20,20] and [30,70], a 10 m gap)
                                  -> NO warning
        TWO INTERLOCKING Ls (contract v6 "Gebiete", the concave case). Both
              carry the outline [[0,0],[8,0],[8,4],[4,4],[4,8],[0,8]], both at
              yaw 0, so a pin at (px, pz) fills
                  wide arm    x in [px, px+8], z in [pz, pz+4]
                  upright arm x in [px, px+4], z in [pz+4, pz+8]
              and leaves the NOTCH x in (px+4, px+8), z in (pz+4, pz+8) empty.
              A at (0,0), B at (5,5): B's wide arm ([5,13] x [5,9]) runs
              straight THROUGH A's notch ((4,8) x (4,8)) and out the far side,
              and nothing touches — A's wide arm stops at z = 4 < 5, A's
              upright arm at x = 4 < 5, so the closest approach is a full
              metre. -> NO warning, although the two BOUNDING BOXES
              ([0,8]² and [5,13]²) share the whole square [5,8]²; that shared
              square lies inside B and in A's notch, which is what makes it
              the red probe of every box-shaped overlap test.
              Slide B to (3,3) instead and its wide arm ([3,11] x [3,7])
              overlaps A's wide arm ([0,8] x [0,4]) on [3,8] x [3,4], 5 m by
              1 m — e.g. the point (5, 3.5) lies in both. -> footprint_overlap
        a place inside a deep_water polygon (impassable in the seed catalog;
              plain "water" is passable and must NOT warn)
                                  -> on_impassable
        kind "lava"               -> dropped + unknown_kind
        an id no location has     -> dropped + unknown_location
        a point outside the bounds box -> out_of_bounds, area KEPT
        the bow-tie polygon       -> self_intersecting, area KEPT
        a 300-point polygon       -> dropped + too_many_points
        a 2-point polygon         -> dropped + invalid_geometry
        a stroke entry            -> meta.stroke is the RECIPE, polygon is the
              ribbon (the [1] rectangle), meta.source "world_dev"
        {} / a list / no usable entry -> ValueError (the only hard errors)

  [5] Apply / snapshot / restore against a throwaway world:
        merge      -> counts, and the areas that were there survive
        replace_terrain -> the old areas are gone, only the new ones remain
        positions  -> update_location_position was called for each named place
        an invalid polygon in the batch -> ValueError and NOTHING was written
        snapshot -> restore puts back the EXACT ids, polygons and positions
              that were there before the apply (ids included: a restore must
              return the very rows, not look-alikes)

Usage:  ./.venv/bin/python scripts/smoke_map_layout_apply.py
"""
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="map-layout-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="map-layout-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import map_layout_apply as mla  # noqa: E402
from app.core.world_geometry import (  # noqa: E402
    point_in_polygon, polygon_bounds)
from app.models import heightfield, terrain, world  # noqa: E402

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


def check_true(label, actual):
    check(label, bool(actual), True)


def near(label, actual, expected, tol):
    global CHECKED
    CHECKED += 1
    ok = abs(actual - expected) <= tol
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r} ± {tol}"))
    if not ok:
        FAILURES.append(label)


def raises_value_error(label, fn):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except ValueError as e:
        print(f"  ✓ {label}: ValueError({str(e)[:70]!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  ✗ {label}: {type(e).__name__}({e}) — expected ValueError")
        FAILURES.append(label)
        return
    print(f"  ✗ {label}: no exception — expected ValueError")
    FAILURES.append(label)


def codes(warnings):
    return sorted(w["code"] for w in warnings)


# ── [1] the ribbon builder ──────────────────────────────────────────────────
print("[1] stroke_to_polygon — the TS twin's hand-derived cases")
check("straight, width 4", mla.stroke_to_polygon([[0, 0], [10, 0]], 4),
      [[0.0, -2.0], [10.0, -2.0], [10.0, 2.0], [0.0, 2.0]])
check("90° bend (miter)", mla.stroke_to_polygon([[0, 0], [10, 0], [10, 10]], 4),
      [[0.0, -2.0], [12.0, -2.0], [12.0, 10.0], [8.0, 10.0], [8.0, 2.0],
       [0.0, 2.0]])
check("collinear -> 2n points",
      mla.stroke_to_polygon([[0, 0], [5, 0], [10, 0]], 4),
      [[0.0, -2.0], [5.0, -2.0], [10.0, -2.0], [10.0, 2.0], [5.0, 2.0],
       [0.0, 2.0]])
check("hairpin -> bevel, 2n+2 points",
      mla.stroke_to_polygon([[0, 0], [10, 0], [0.4, 2.8]], 4),
      [[0.0, -2.0], [10.0, -2.0], [10.56, 1.92], [0.96, 4.72],
       [-0.16, 0.88], [9.44, -1.92], [10.0, 2.0], [0.0, 2.0]])
check("duplicate clicks dropped",
      mla.stroke_to_polygon([[0, 0], [0, 0], [10, 0], [10, 0]], 4),
      [[0.0, -2.0], [10.0, -2.0], [10.0, 2.0], [0.0, 2.0]])
check("2 decimals always",
      mla.stroke_to_polygon([[0, 0], [3.14159, 0]], 1.111),
      [[0.0, -0.56], [3.14, -0.56], [3.14, 0.56], [0.0, 0.56]])
check("sub-grid line -> None",
      mla.stroke_to_polygon([[0, 0], [0.001, 0]], 4), None)
check("width 0 -> None", mla.stroke_to_polygon([[0, 0], [10, 0]], 0), None)
check("one point -> None", mla.stroke_to_polygon([[0, 0]], 4), None)
check("NaN coordinate -> None",
      mla.stroke_to_polygon([[0, 0], [float("nan"), 0]], 4), None)

# ── [2] the decorator + its PRNG ────────────────────────────────────────────
print("[2] decorate_stroke — same source, same numbers")
check("PRNG matches the editor's (node-verified)",
      [mla.seeded_random("terrain:stroke:0,0:100,0")() for _ in range(1)][0],
      0.9629154971335083)
_rnd = mla.seeded_random("terrain:stroke:0,0:100,0")
check("PRNG stream", [round(_rnd(), 12) for _ in range(3)],
      [0.962915497134, 0.627296451014, 0.043435396627])
check("seed string", mla.stroke_seed([[0, 0], [100, 0]]),
      "terrain:stroke:0,0:100,0")

JAG = mla.decorate_stroke([[0, 0], [100, 0]], "jagged", 10, 2)
check("jagged: 10 deflections + 2 clicks", len(JAG["points"]), 12)
check("jagged: not capped", JAG["capped"], False)
check("jagged: deflection x positions",
      [p[0] for p in JAG["points"][1:-1]],
      [5.0, 15.0, 25.0, 35.0, 45.0, 55.0, 65.0, 75.0, 85.0, 95.0])
check("jagged: sides alternate, side A first (normal (0,-1))",
      [1 if p[1] > 0 else -1 for p in JAG["points"][1:-1]],
      [-1, 1, -1, 1, -1, 1, -1, 1, -1, 1])
check_true("jagged: every |z| in [0.8, 2]",
           all(0.8 <= abs(p[1]) <= 2.0 for p in JAG["points"][1:-1]))

WAV = mla.decorate_stroke([[0, 0], [100, 0]], "wavy", 10, 2)
check("wavy: same point count", len(WAV["points"]), 12)
check("wavy: same deflection positions",
      [p[0] for p in WAV["points"]], [p[0] for p in JAG["points"]])
check_true("wavy: |z| <= 2 throughout",
           all(abs(p[1]) <= 2.0 for p in WAV["points"]))
check_true("wavy differs from jagged",
           [p[1] for p in WAV["points"]] != [p[1] for p in JAG["points"]])

COR = mla.decorate_stroke([[0, 0], [10, 0], [10, 10]], "jagged", 10, 2)
check("corner survives the weave", len(COR["points"]), 5)
check("the clicked corner is still there", COR["points"][2], [10.0, 0.0])

CAP = mla.decorate_stroke([[0, 0], [1000, 0]], "jagged", 2, 2)
check("cap: 120 points", len(CAP["points"]), mla.MAX_DECORATED_POINTS)
check("cap: flagged", CAP["capped"], True)
near("cap: spacing 1000/118", CAP["spacing_m"], 1000 / 118, 1e-9)

check("amplitude 0 -> untouched",
      mla.decorate_stroke([[0, 0], [100, 0]], "jagged", 10, 0)["points"],
      [[0, 0], [100, 0]])
check("style straight -> untouched",
      mla.decorate_stroke([[0, 0], [100, 0]], "straight", 10, 2)["points"],
      [[0, 0], [100, 0]])

# ── [3] simplify + self-intersection ────────────────────────────────────────
print("[3] simplify_polygon + polygon_self_intersects")
R = 100.0
CIRCLE = [[R * math.cos(2 * math.pi * i / 100), R * math.sin(2 * math.pi * i / 100)]
          for i in range(100)]


def ring_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % len(poly)]
        s += x1 * z2 - x2 * z1
    return abs(s) / 2.0


SIMPLE = mla.simplify_polygon(CIRCLE, 12)
check("100-gon -> 12 points", len(SIMPLE), 12)
_loss = 100 * (1 - ring_area(SIMPLE) / ring_area(CIRCLE))
check_true(f"area within 5 % (lost {_loss:.2f} %, floor 4.44 %)", _loss <= 5.0)
check("square already inside the budget",
      mla.simplify_polygon([[0, 0], [10, 0], [10, 10], [0, 10]], 12),
      [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
check("2 points is not an area", mla.simplify_polygon([[0, 0], [1, 1]], 12), [])
check("junk vertex -> []", mla.simplify_polygon([[0, 0], "x", [1, 1]], 12), [])
check("square does not self-intersect",
      mla.polygon_self_intersects([[0, 0], [10, 0], [10, 10], [0, 10]]), False)
check("bow-tie self-intersects",
      mla.polygon_self_intersects([[0, 0], [10, 10], [10, 0], [0, 10]]), True)

# ── [4] the sanitizer, pure ─────────────────────────────────────────────────
print("[4] sanitize_map_layout — warnings, drops and hard errors")
CATALOG = {
    "grass": {"name": "Grass", "passable": True, "speed_factor": 1.0},
    "forest": {"name": "Forest", "passable": True, "speed_factor": 0.7},
    "water": {"name": "Water", "passable": True, "speed_factor": 0.4},
    "deep_water": {"name": "Deep water", "passable": False, "speed_factor": 0.4},
}
L_SHAPE = [[0, 0], [8, 0], [8, 4], [4, 4], [4, 8], [0, 8]]
# Every outline is DRAWN (contract v6, closing wave 2026-08-19): a width
# alone is no shape and its place would simply have no area. The two square
# ones are the centred 40 m / 10 m squares, i.e. the very spans the overlap
# cases below are derived from (±20 and ±5).
SQ_40 = [[-20, -20], [20, -20], [20, 20], [-20, 20]]
SQ_10 = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
LOCS = {
    "loc_a": {"name": "Tavern", "boundary": SQ_40, "plan_width_m": 40.0},
    "loc_b": {"name": "Smithy", "boundary": SQ_40, "plan_width_m": 40.0},
    "loc_c": {"name": "Shrine", "boundary": SQ_10, "plan_width_m": 10.0},
    # The concave pair: only the polygon can answer whether they share ground.
    "loc_l1": {"name": "L Yard", "boundary": L_SHAPE, "plan_width_m": 8.0},
    "loc_l2": {"name": "L Barn", "boundary": L_SHAPE, "plan_width_m": 8.0},
    # A location that was never drawn: no area, so it overlaps nothing.
    "loc_bare": {"name": "Bare Pin", "boundary": None, "plan_width_m": 0.0},
}
BOX = {"min_x": -500, "min_z": -500, "max_x": 500, "max_z": 500}


def sane(data, bounds=BOX):
    return mla.sanitize_map_layout(data, catalog=CATALOG,
                                   locations_by_id=LOCS, bounds=bounds)


norm, warns = sane({"locations": [
    {"id": "loc_a", "pos_x": 0, "pos_z": 0},
    {"id": "loc_b", "pos_x": 30, "pos_z": 0}]})
check("40 m footprints 30 m apart overlap", codes(warns), ["footprint_overlap"])
check("both survive the overlap", len(norm["locations"]), 2)

norm, warns = sane({"locations": [
    {"id": "loc_a", "pos_x": 0, "pos_z": 0},
    {"id": "loc_b", "pos_x": 50, "pos_z": 0}]})
check("40 m footprints 50 m apart do not", codes(warns), [])

# A location that was NEVER DRAWN has no area (2026-08-19), so it cannot
# overlap anything — not even a 40 m square placed on the very same point.
norm, warns = sane({"locations": [
    {"id": "loc_a", "pos_x": 0, "pos_z": 0},
    {"id": "loc_bare", "pos_x": 0, "pos_z": 0}]})
check("a boundary-less location overlaps nothing", codes(warns), [])
check("...and is still placed", len(norm["locations"]), 2)

# The concave pair — two Ls, arm through notch.
norm, warns = sane({"locations": [
    {"id": "loc_l1", "pos_x": 0, "pos_z": 0},
    {"id": "loc_l2", "pos_x": 5, "pos_z": 5}]})
check("two INTERLOCKING Ls do not overlap", codes(warns), [])
check("...and both are placed", len(norm["locations"]), 2)
check("RED COUNTER-PROBE: their bounding boxes DO share [5,8]²",
      (polygon_bounds([[0, 0], [8, 0], [8, 4], [4, 4], [4, 8], [0, 8]]),
       polygon_bounds([[5, 5], [13, 5], [13, 9], [9, 9], [9, 13],
                           [5, 13]])),
      ((0.0, 0.0, 8.0, 8.0), (5.0, 5.0, 13.0, 13.0)))
norm, warns = sane({"locations": [
    {"id": "loc_l1", "pos_x": 0, "pos_z": 0},
    {"id": "loc_l2", "pos_x": 3, "pos_z": 3}]})
check("...but 2 m further in their wide arms cross",
      codes(warns), ["footprint_overlap"])
check("the shared point (5, 3.5) is really in both",
      (point_in_polygon(5, 3.5, [[0, 0], [8, 0], [8, 4], [4, 4], [4, 8],
                                     [0, 8]]),
       point_in_polygon(5, 3.5, [[3, 3], [11, 3], [11, 7], [7, 7],
                                     [7, 11], [3, 11]])),
      (True, True))

DEEP = {"kind": "deep_water", "label": "The lake",
        "polygon": [[-50, -50], [50, -50], [50, 50], [-50, 50]]}
norm, warns = sane({"terrain_areas": [DEEP],
                    "locations": [{"id": "loc_c", "pos_x": 0, "pos_z": 0}]})
check("a place in deep water", codes(warns), ["on_impassable"])
check("the place is still placed", len(norm["locations"]), 1)

norm, warns = sane({"terrain_areas": [dict(DEEP, kind="water")],
                    "locations": [{"id": "loc_c", "pos_x": 0, "pos_z": 0}]})
check("plain water is passable — no warning", codes(warns), [])

norm, warns = sane({"terrain_areas": [
    {"kind": "lava", "polygon": [[0, 0], [10, 0], [10, 10]]}],
    "locations": [{"id": "loc_c", "pos_x": 200, "pos_z": 200}]})
check("unknown kind warned", codes(warns), ["unknown_kind"])
check("unknown kind dropped", norm["terrain_areas"], [])

norm, warns = sane({"terrain_areas": [
    {"kind": "grass", "polygon": [[0, 0], [10, 0], [10, 10]]}],
    "locations": [{"id": "loc_nope", "pos_x": 0, "pos_z": 0}]})
check("unknown location warned", codes(warns), ["unknown_location"])
check("unknown location dropped", norm["locations"], [])

norm, warns = sane({"terrain_areas": [
    {"kind": "grass", "label": "Far field",
     "polygon": [[0, 0], [900, 0], [900, 100]]}]})
check("out of bounds warned", codes(warns), ["out_of_bounds"])
check("out of bounds area KEPT", len(norm["terrain_areas"]), 1)

norm, warns = sane({"terrain_areas": [
    {"kind": "grass", "polygon": [[0, 0], [10, 10], [10, 0], [0, 10]]}]})
check("bow-tie warned", codes(warns), ["self_intersecting"])
check("bow-tie area KEPT", len(norm["terrain_areas"]), 1)

norm, warns = sane({"terrain_areas": [
    {"kind": "grass", "polygon": [[i * 0.1, (i % 7) * 0.1] for i in range(300)]}]})
check("300 points warned", codes(warns), ["too_many_points"])
check("300 points dropped", norm["terrain_areas"], [])

norm, warns = sane({"terrain_areas": [
    {"kind": "grass", "polygon": [[0, 0], [10, 0]]}],
    "locations": [{"id": "loc_c", "pos_x": 0, "pos_z": 0}]})
check("2-point polygon warned", codes(warns), ["invalid_geometry"])
check("2-point polygon dropped", norm["terrain_areas"], [])

norm, warns = sane({"summary": "a river",
                    "terrain_areas": [{"kind": "water", "label": "River",
                                       "stroke": {"points": [[0, 0], [10, 0]],
                                                  "width_m": 4}}]})
check("stroke -> the [1] rectangle", norm["terrain_areas"][0]["polygon"],
      [[0.0, -2.0], [10.0, -2.0], [10.0, 2.0], [0.0, 2.0]])
check("stroke recipe kept", norm["terrain_areas"][0]["meta"]["stroke"],
      {"points": [[0.0, 0.0], [10.0, 0.0]], "width_m": 4.0})
check("label + source in meta",
      (norm["terrain_areas"][0]["meta"]["label"],
       norm["terrain_areas"][0]["meta"]["source"]), ("River", "world_dev"))
check("summary carried", norm["summary"], "a river")

norm, warns = sane({"height_areas": [
    {"label": "Hill", "polygon": [[0, 0], [40, 0], [40, 40], [0, 40]],
     "height_m": 12, "falloff_m": 30}]})
check("height area normalized",
      {k: norm["height_areas"][0][k] for k in ("height_m", "falloff_m")},
      {"height_m": 12.0, "falloff_m": 30.0})
check("height area source", norm["height_areas"][0]["meta"]["source"],
      "world_dev")

norm, warns = sane({"terrain_areas": [
    {"kind": "grass", "polygon": [[0, 0], [10, 0], [10, 10]]}]},
    bounds=None)
check("no bounds anywhere -> no bounds warning", codes(warns), [])

norm, warns = sane({"bounds": {"min_x": -2000, "min_z": -2000,
                               "max_x": 2000, "max_z": 2000},
                    "terrain_areas": [
                        {"kind": "grass",
                         "polygon": [[0, 0], [900, 0], [900, 100]]}]})
check("a proposed bigger box covers the point", codes(warns), [])

raises_value_error("a list is not a layout", lambda: sane([]))
raises_value_error("an empty layout", lambda: sane({}))
raises_value_error("nothing usable in it",
                   lambda: sane({"terrain_areas": [], "locations": []}))
check("layout_counts",
      mla.layout_counts(sane({"terrain_areas": [
          {"kind": "grass", "polygon": [[0, 0], [10, 0], [10, 10]]}],
          "height_areas": [{"polygon": [[0, 0], [5, 0], [5, 5]],
                            "height_m": 3}],
          "locations": [{"id": "loc_c", "pos_x": 0, "pos_z": 200}]})[0]),
      {"areas": 1, "heights": 1, "positions": 1})

# ── [5] apply / snapshot / restore against a real (throwaway) world ─────────
print("[5] apply_map_layout / map_snapshot / restore_snapshot")
LOC_A = world.add_location("Tavern", "A tavern.", rooms=[{"name": "Bar"}])
LOC_B = world.add_location("Smithy", "A smithy.", rooms=[{"name": "Forge"}])
ID_A, ID_B = LOC_A["id"], LOC_B["id"]
_data = world._load_world_data()
for _loc in _data["locations"]:
    _loc["map3d"] = {"plan_width_m": 40.0, "boundary": SQ_40}
world._save_world_data(_data)
world.update_location_position(ID_A, 5.0, 5.0, 0.0)

OLD = terrain.save_area({"kind": "grass",
                         "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]})
OLD_HEIGHT = heightfield.save_height_area(
    {"polygon": [[0, 0], [8, 0], [8, 8]], "height_m": 4, "falloff_m": 2})

SNAP = mla.map_snapshot()
check("snapshot id shape", len(SNAP.split("-")), 2)
_listed = mla.list_snapshots()
check("snapshot listed", [s["id"] for s in _listed], [SNAP])
check("snapshot counts", _listed[0]["counts"],
      {"areas": 1, "heights": 1, "positions": 2})
check_true("snapshot has a created_at", _listed[0]["created_at"])

WORLD_CATALOG = {}
from app.core.terrain_types import effective_catalog  # noqa: E402
WORLD_CATALOG = effective_catalog()
WORLD_LOCS = {ID_A: {"name": "Tavern", "boundary": SQ_40, "plan_width_m": 40.0},
              ID_B: {"name": "Smithy", "boundary": SQ_40, "plan_width_m": 40.0}}

DRAFT = {
    "summary": "forest and a road",
    "terrain_areas": [
        {"kind": "forest", "label": "Woods",
         "polygon": [[100, 100], [200, 100], [200, 200], [100, 200]]},
        {"kind": "path", "label": "Road",
         "stroke": {"points": [[0, 300], [200, 300]], "width_m": 6}},
    ],
    "height_areas": [{"label": "Knoll",
                      "polygon": [[300, 300], [340, 300], [340, 340]],
                      "height_m": 6, "falloff_m": 20}],
    "locations": [{"id": ID_B, "pos_x": 400, "pos_z": 400, "yaw_deg": 90}],
}
NORM, WARN = mla.sanitize_map_layout(DRAFT, catalog=WORLD_CATALOG,
                                     locations_by_id=WORLD_LOCS, bounds=None)
check("draft is clean", codes(WARN), [])
check("merge counts", mla.apply_map_layout(NORM, mode="merge"),
      {"areas": 2, "heights": 1, "positions": 1})
check("merge kept the old area",
      sorted(a["kind"] for a in terrain.list_areas()),
      ["forest", "grass", "path"])
check("merge kept the old height area", len(heightfield.list_height_areas()), 2)
_b = world.get_location_by_id(ID_B)
check("position written", (_b["pos_x"], _b["pos_z"], _b["yaw_deg"]),
      (400.0, 400.0, 90.0))
check("meta.source on every written area",
      sorted({(a["meta"].get("source") or "-") for a in terrain.list_areas()}),
      ["-", "world_dev"])

check("replace_terrain counts", mla.apply_map_layout(NORM, mode="replace_terrain"),
      {"areas": 2, "heights": 1, "positions": 1})
check("replace_terrain wiped the old ground",
      sorted(a["kind"] for a in terrain.list_areas()), ["forest", "path"])
check("replace_terrain wiped the old heights",
      len(heightfield.list_height_areas()), 1)

BAD = dict(NORM, terrain_areas=list(NORM["terrain_areas"])
           + [{"kind": "forest", "polygon": [[0, 0], [1, 1]], "z_order": 0,
               "meta": {}}])
_before = [a["id"] for a in terrain.list_areas()]
raises_value_error("a broken polygon in the batch",
                   lambda: mla.apply_map_layout(BAD, mode="merge"))
check("nothing was written", [a["id"] for a in terrain.list_areas()], _before)

RESTORED = mla.restore_snapshot(SNAP)
check("restore counts", RESTORED, {"areas": 1, "heights": 1, "positions": 2})
check("restore put back the EXACT area id",
      [(a["id"], a["kind"], a["polygon"]) for a in terrain.list_areas()],
      [(OLD["id"], "grass", [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0],
                             [0.0, 10.0]])])
check("restore put back the EXACT height area id",
      [(h["id"], h["height_m"]) for h in heightfield.list_height_areas()],
      [(OLD_HEIGHT["id"], 4.0)])
_a = world.get_location_by_id(ID_A)
_b = world.get_location_by_id(ID_B)
check("restore put the Tavern back", (_a["pos_x"], _a["pos_z"]), (5.0, 5.0))
check("restore unplaced the Smithy again",
      (_b.get("pos_x"), _b.get("pos_z")), (None, None))

check("world bounds from the restored world",
      mla.current_world_bounds(),
      {"min_x": -15.0, "min_z": -15.0, "max_x": 25.0, "max_z": 25.0})

raises_value_error("unknown snapshot id",
                   lambda: mla.restore_snapshot("nope"))
raises_value_error("a traversing snapshot id",
                   lambda: mla.restore_snapshot("../../etc/passwd"))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
