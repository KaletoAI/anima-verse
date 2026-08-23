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
        the same line WAVY: a continuous curve, not one point per deflection.
              offset(d) = A(d)·sin(phase + 2π·d/(4·spacing)) sampled every
              min(spacing/3, 3) = 3 m, so the arc positions are 0, 3, …, 99
              plus the end at 100 -> 35 points. A(d) cosine-eases through the
              deflection heights and is 0 at both ends, so z(0) = z(100) = 0
              and |z| <= 2 throughout. The two styles read the SAME random
              stream (phase, then the heights), which is why switching between
              them keeps the heights.
        [(0,0),(10,0),(10,10)] jagged: the clicked corner (10,0) survives, at
              index 2 of 5 points. The corner-normal blend does not reach
              either deflection — both sit exactly spacing/2 = 5 away and the
              window is half-open — so this case is unchanged by it.
        [(0,0),(1000,0)] jagged spacing 2: 500 deflections, 502 points, inside
              the 1024-point budget — `capped` False. Ten times that line does
              bite: room = 1024 − 2 = 1022, spacing 10000/1022 = 9.7847…,
              1024 points, capped True.
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
        a 2100-point polygon      -> dropped + too_many_points (the cap is
                                     2050, and above 400 points the O(n²)
                                     self-intersection HINT is skipped, so
                                     "too_many_points" is the only warning)
        a 2-point polygon         -> dropped + invalid_geometry
        a stroke entry            -> meta.stroke is the RECIPE, polygon is the
              ribbon (the [1] rectangle), meta.source "world_dev"
        {} / a list / no usable entry -> ValueError (the only hard errors)

  [4b] NEW PLACE STUBS (`name` instead of `id`), the v2 half of the schema.
        The outline goes through the ONE boundary judge
        (`world_ops._sanitize_map3d`), so the hand numbers are the contract's:
          the L (0,0) (4,0) (4,2) (2,2) (2,4) (0,4) has the shoelace sum
              0 + 8 + 4 + 4 + 8 + 0 = +24, i.e. it is already CLOCKWISE in
              storage winding (x east, z south -> positive sum), and its
              bounding box is 4 × 4 -> plan_width_m 4.0
              (`world_geometry.polygon_plan_width_m`, same hand case).
              Handed in REVERSED (counter-clockwise, sum −24) it must come
              back as that very sequence — that is the winding fix, measured.
          centimetres: [[0,0],[3.456,0],[3.456,3.456]] -> 3.46 everywhere,
              width 3.46.
          NO boundary at all -> the seed square, edge SEED_BOUNDARY_M = 10,
              i.e. [[-5,-5],[5,-5],[5,5],[-5,5]] (sum +200, clockwise) and
              plan_width_m 10.0 — a place is never area-less.
          a 2-point "outline" -> seed square + a `seed_boundary` warning.
          a stub named like an existing place -> `duplicate_name`, KEPT.
          neither id nor name -> `nameless_location`, dropped.
          an UNKNOWN id stays `unknown_location` (dropped): a guessed id must
              never turn into a new place.
          the seed square of a stub at (0,0) and the 10 m square of `loc_c`
              at (8,0) span [-5,5] and [3,13] -> they share [3,5]
                                  -> footprint_overlap
          layout_counts splits the two promises: one existing place moved and
              one stub -> {"positions": 1, "created": 1}

  [5b] Stub apply / restore:
        apply -> the place EXISTS, with the ground room every location has,
              its boundary stored clockwise, plan_width_m derived, indoor and
              danger_level set, and positioned at the stub's pin
        a stub named exactly like an existing place -> a SECOND place with its
              own id (names are not keys), the first one untouched
        restore -> the created places are DELETED again ("removed": 2) while
              the moved existing one is put back where it was; a place created
              BY HAND after the apply survives the restore, because the
              snapshot only takes back what it recorded

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
check("wavy: sampled every 3 m — 34 positions + the end", len(WAV["points"]),
      35)
check("wavy: the arc positions are 0, 3, …, 99, 100",
      [p[0] for p in WAV["points"]], [float(k * 3) for k in range(34)] + [100.0])
check("wavy: both ends stay where they were clicked",
      [WAV["points"][0], WAV["points"][-1]], [[0, 0], [100, 0]])
check_true("wavy: |z| <= 2 throughout",
           all(abs(p[1]) <= 2.0 for p in WAV["points"]))
check("wavy: not capped", WAV["capped"], False)
# The very curve, re-derived from the rule and the shared PRNG: phase, then
# the deflection heights at 5, 15, …, 95, cosine-eased and pinned to 0 at both
# ends, times sin(phase + 2π·d/40). The normal of a west→east line is (0,-1),
# so x IS the arc position and the whole offset lands in z.
_r = mla.seeded_random(mla.stroke_seed([[0, 0], [100, 0]]))
_phase = _r() * math.pi * 2
_aD = [0.0] + [5.0 + 10 * i for i in range(10)] + [100.0]
_aH = [0.0] + [2 * (0.4 + 0.6 * _r()) for _ in range(10)] + [0.0]


def _env(d: float) -> float:
    i = 0
    while i + 2 < len(_aD) and _aD[i + 1] < d:
        i += 1
    t = (d - _aD[i]) / (_aD[i + 1] - _aD[i])
    return _aH[i] + (_aH[i + 1] - _aH[i]) * (1 - math.cos(math.pi * t)) / 2


check("wavy: every point IS A(d)·sin(phase + π·d/20)",
      [p[1] for p in WAV["points"][1:-1]],
      [mla._round2(-_env(k * 3) * math.sin(_phase + math.pi * (k * 3) / 20))
       for k in range(1, 34)])

COR = mla.decorate_stroke([[0, 0], [10, 0], [10, 10]], "jagged", 10, 2)
check("corner survives the weave", len(COR["points"]), 5)
check("the clicked corner is still there", COR["points"][2], [10.0, 0.0])
check("...and the blend reached neither deflection (both 5 away)",
      [COR["points"][1][0], COR["points"][3][1]], [5.0, 5.0])
# …but a corner NEARER than half a spacing does blend: [(0,0),(7,0),(7,7)],
# one deflection at 5, half = min(5, 3.5, 3.5) = 3.5, b = ease(1.5/7)
# = 0.1090843 -> normal (0.1215330, -0.9925874) instead of (0, -1).
BENT = mla.decorate_stroke([[0, 0], [7, 0], [7, 7]], "jagged", 10, 2)
_b = (1 - math.cos(math.pi * (1.5 / 7))) / 2
_n = (_b / math.hypot(_b, 1 - _b), -(1 - _b) / math.hypot(_b, 1 - _b))
near("blended normal x", _n[0], 0.1215330, 1e-6)
near("blended normal z", _n[1], -0.9925874, 1e-6)
near("the deflection rides it", BENT["points"][1][0],
     5 + (BENT["points"][1][1] / _n[1]) * _n[0], 0.011)

FIT = mla.decorate_stroke([[0, 0], [1000, 0]], "jagged", 2, 2)
check("1000 m at spacing 2 now fits: 502 points", len(FIT["points"]), 502)
check("...uncapped", FIT["capped"], False)
CAP = mla.decorate_stroke([[0, 0], [10000, 0]], "jagged", 2, 2)
check("cap: 1024 points", len(CAP["points"]), mla.MAX_DECORATED_POINTS)
check("cap: flagged", CAP["capped"], True)
near("cap: spacing 10000/1022", CAP["spacing_m"], 10000 / 1022, 1e-9)
KM = mla.decorate_stroke([[0, 0], [1000, 0]], "wavy", 10, 2)
check("a kilometre of wavy river is 335 points, uncapped",
      [len(KM["points"]), KM["capped"], KM["spacing_m"]], [335, False, 10])

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
    {"kind": "grass",
     "polygon": [[i * 0.1, (i % 7) * 0.1] for i in range(2100)]}]})
check("2100 points warned", codes(warns), ["too_many_points"])
check("2100 points dropped", norm["terrain_areas"], [])

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
      {"areas": 1, "heights": 1, "positions": 1, "created": 0})

# ── [4b] new place stubs ────────────────────────────────────────────────────
print("[4b] sanitize_map_layout — NEW PLACE STUBS")
# The contract's own L (world_geometry.polygon_plan_width_m): box 4 × 4.
L4 = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]]
L4_CCW = list(reversed(L4))
SEED = [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0]]

norm, warns = sane({"locations": [
    {"name": "The Old Mill", "description": "A water mill.",
     "pos_x": 100, "pos_z": 100, "yaw_deg": 90, "boundary": L4_CCW,
     "indoor": "indoor", "danger_level": 2, "why": "at the bend"}]})
check("a stub is clean", codes(warns), [])
STUB = norm["locations"][0]
check("the stub is marked new", STUB.get("is_new"), True)
check("a stub carries no id", "id" in STUB, False)
check("CCW L flipped to storage winding (clockwise)", STUB["boundary"],
      [[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [2.0, 2.0], [2.0, 4.0], [0.0, 4.0]])
check("derived width of the 4 × 4 box", STUB["plan_width_m"], 4.0)
check("pin, yaw, name, description, indoor, danger",
      (STUB["pos_x"], STUB["pos_z"], STUB["yaw_deg"], STUB["name"],
       STUB["description"], STUB["indoor"], STUB["danger_level"]),
      (100.0, 100.0, 90.0, "The Old Mill", "A water mill.", "indoor", 2))
check("why survives", STUB["why"], "at the bend")

norm, _ = sane({"locations": [
    {"name": "Cm Hut", "pos_x": 0, "pos_z": 0,
     "boundary": [[0, 0], [3.456, 0], [3.456, 3.456]]}]})
check("centimetres, not micrometres", norm["locations"][0]["boundary"],
      [[0.0, 0.0], [3.46, 0.0], [3.46, 3.46]])
check("...and the width with them", norm["locations"][0]["plan_width_m"], 3.46)

norm, warns = sane({"locations": [
    {"name": "Bare Stub", "pos_x": 0, "pos_z": 0}]})
check("no outline -> the 10 m seed square, silently",
      (codes(warns), norm["locations"][0]["boundary"],
       norm["locations"][0]["plan_width_m"]),
      ([], SEED, 10.0))
check("SEED_BOUNDARY_M is that square's edge", mla.SEED_BOUNDARY_M, 10.0)

norm, warns = sane({"locations": [
    {"name": "Broken Stub", "pos_x": 0, "pos_z": 0,
     "boundary": [[0, 0], [4, 0]]}]})
check("an unusable outline -> seed square + a warning",
      (codes(warns), norm["locations"][0]["boundary"]),
      (["seed_boundary"], SEED))

norm, warns = sane({"locations": [
    {"name": "tavern", "pos_x": 300, "pos_z": 300}]})
check("a stub named like an existing place warns", codes(warns),
      ["duplicate_name"])
check("...and is created anyway", len(norm["locations"]), 1)

norm, warns = sane({"locations": [
    {"pos_x": 0, "pos_z": 0},
    {"name": "Real Stub", "pos_x": 200, "pos_z": 200}]})
check("neither id nor name -> dropped", codes(warns), ["nameless_location"])
check("...the named one survives", len(norm["locations"]), 1)

norm, warns = sane({"locations": [
    {"id": "loc_nope", "name": "Guessed", "pos_x": 0, "pos_z": 0}]})
check("an unknown id never becomes a stub", codes(warns),
      ["unknown_location"])
check("...and nothing is placed", norm["locations"], [])

norm, warns = sane({"locations": [
    {"name": "Seeded", "pos_x": 0, "pos_z": 0},
    {"id": "loc_c", "pos_x": 8, "pos_z": 0}]})
check("seed square [-5,5] and the 10 m square [3,13] share [3,5]",
      codes(warns), ["footprint_overlap"])

check("layout_counts splits moved from created",
      mla.layout_counts(sane({"locations": [
          {"id": "loc_c", "pos_x": 0, "pos_z": 0},
          {"name": "Mill", "pos_x": 200, "pos_z": 200}]})[0]),
      {"areas": 0, "heights": 0, "positions": 1, "created": 1})

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
      {"areas": 1, "heights": 1, "positions": 2, "created": 0})
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
      {"areas": 2, "heights": 1, "positions": 1, "created": 0})
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

check("replace_terrain counts",
      mla.apply_map_layout(NORM, mode="replace_terrain"),
      {"areas": 2, "heights": 1, "positions": 1, "created": 0})
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
check("restore counts", RESTORED,
      {"areas": 1, "heights": 1, "positions": 2, "removed": 0})
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

# ── [5b] stubs against the real world ───────────────────────────────────────
print("[5b] stubs — create through the ordinary path, then take them back")
STUB_DRAFT = {
    "locations": [
        {"id": ID_A, "pos_x": 60, "pos_z": 60, "yaw_deg": 0},
        {"name": "The Old Mill", "description": "A water mill.",
         "pos_x": 200, "pos_z": 0, "yaw_deg": 90, "boundary": L4_CCW,
         "indoor": "indoor", "danger_level": 2, "why": "at the bend"},
        {"name": "Tavern", "description": "A second house, same name.",
         "pos_x": 400, "pos_z": 0},
    ],
}
SNORM, SWARN = mla.sanitize_map_layout(STUB_DRAFT, catalog=WORLD_CATALOG,
                                       locations_by_id=WORLD_LOCS, bounds=None)
check("only the repeated name is complained about", codes(SWARN),
      ["duplicate_name"])
SNAP2 = mla.map_snapshot()
check("stub apply counts",
      mla.apply_map_layout(SNORM, mode="merge", snapshot_id=SNAP2),
      {"areas": 0, "heights": 0, "positions": 1, "created": 2})

MILLS = [loc for loc in world.list_locations()
         if loc.get("name") == "The Old Mill"]
check("the mill was created, once", len(MILLS), 1)
MILL = MILLS[0]
check("the CCW outline is stored clockwise", MILL["map3d"]["boundary"],
      [[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [2.0, 2.0], [2.0, 4.0], [0.0, 4.0]])
check("plan_width_m derived from its 4 × 4 box",
      MILL["map3d"]["plan_width_m"], 4.0)
check("pin and yaw", (MILL["pos_x"], MILL["pos_z"], MILL["yaw_deg"]),
      (200.0, 0.0, 90.0))
check("description, indoor and danger_level",
      (MILL["description"], MILL["indoor"], MILL["danger_level"]),
      ("A water mill.", "indoor", 2))
check("it has the ground room every location has",
      [r.get("id") for r in MILL.get("rooms") or []], [world.GROUND_ROOM_ID])

TAVERNS = [loc for loc in world.list_locations() if loc.get("name") == "Tavern"]
check("a repeated name creates a SECOND place", len(TAVERNS), 2)
check("...with two distinct ids", len({t["id"] for t in TAVERNS}), 2)
_a = world.get_location_by_id(ID_A)
check("...and the first one was NOT overwritten", _a["description"],
      "A tavern.")
check("the existing place moved", (_a["pos_x"], _a["pos_z"]), (60.0, 60.0))
check("the snapshot knows what to take back",
      [s["counts"]["created"] for s in mla.list_snapshots()
       if s["id"] == SNAP2], [2])

HAND = world.add_location("Hand Made", "Drawn by a person after the apply.")
RESTORED2 = mla.restore_snapshot(SNAP2)
check("restore removes exactly the created places", RESTORED2["removed"], 2)
check("the mill is gone",
      [loc for loc in world.list_locations()
       if loc.get("name") == "The Old Mill"], [])
check("one Tavern again",
      len([loc for loc in world.list_locations()
           if loc.get("name") == "Tavern"]), 1)
check("the moved Tavern is back where it stood",
      (world.get_location_by_id(ID_A)["pos_x"],
       world.get_location_by_id(ID_A)["pos_z"]), (5.0, 5.0))
check("a place made BY HAND after the apply survives the restore",
      bool(world.get_location_by_id(HAND["id"])), True)

raises_value_error("unknown snapshot id",
                   lambda: mla.restore_snapshot("nope"))
raises_value_error("a traversing snapshot id",
                   lambda: mla.restore_snapshot("../../etc/passwd"))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
