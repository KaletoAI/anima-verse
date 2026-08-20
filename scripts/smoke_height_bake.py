#!/usr/bin/env python3
"""Smoke run for the PURE HEIGHT FUNCTION — the bake of "Ein Boden" E1.

Throwaway storage, no server, no real world. Every number below is derived BY
HAND in this header from the rules, never recorded from the current output.

WHAT CHANGED, AND WHY THERE IS A NEW SCRIPT
-------------------------------------------
``h_final`` used to be a RASTER PROCESS with two steps that measured in GRID
CELLS: the micro-relief's edge rule asked about the four grid NEIGHBOURS, and
a plateau's ramp was ONE CELL wide. A cell is 2 m on a tile and up to 32 m on
a coarsened overview, so the same world came out as two different landscapes
depending on who asked — the measured "zwei Böden" finding (max 1.104 m apart
at the same world point).

Since E1 every step is evaluated PER POINT with METRE parameters
(``core.heightfield.HeightModel``), in this order::

    areas (strongest deflection)  ->  micro-relief (additive)
      ->  water carve  ->  location plateaus

so ANY lattice is the same function sampled more or less finely, and two
lattices agree at their shared points BY CONSTRUCTION. That is claim (a).

THE FIXTURE (pure literals; the model never touches a DB)
---------------------------------------------------------
ONE height area, shaped so the landscape is an exact plane where it matters:

    SLOPE   rectangle (0,-400)-(200,400), height_m 20, falloff_m 200

    h_area(p) = 20 · min(1, d(p)/200),  d = distance to the OUTLINE
              = 20 · min(x, 200-x, z+400, 400-z) / 200

For |z| <= 200 the two z-edges are at least 200 m away, so

    NATURAL(x, z) = min(x, 200-x) / 10          (independent of z)

i.e. x/10 on the west half and (200-x)/10 on the east half. Everything below
lives inside that band.

    WATER_SET   square (20,20)-(60,60), kind "lake",
                water_level 3.0, water_depth_m 2.0, shore_ramp_m 3.0
    WATER_AUTO  square (120,120)-(160,160), kind "lake", NO water_level
    GRASS       band (100,-100)-(180,-20), kind "g",
                relief_amplitude_m 1.0, relief_wave_m 16
    PLOT        a BUILT location, pin (80,-140), yaw 0, local outline the
                centred 20 m square -> world (70,-150)-(90,-130)

The catalog is two entries: "lake" carries ``meta.water`` (that flag, never the
NAME, is what makes a kind carve — kinds are an open vocabulary) and "g"
carries the two relief numbers.

[1] THE WATER CARVE (§ G4).  Inside a water polygon

        h = min(h, water_level - depth · smoothstep(min(d_in/shore_ramp, 1)))

    with d_in the distance to the polygon OUTLINE and
    smoothstep(t) = t²·(3-2t). MIN, never assignment: the carve may only
    ever LOWER the ground.

    WATER_SET, mirror 3.0, depth 2.0, ramp 3.0. d_in at (x,40) for
    x in [20,60] is min(x-20, 60-x, 20, 20):
      (40,40) d_in 20 >= 3 -> profile 2.0, bed 1.0; NATURAL 4.0   -> 1.0
      (23,40) d_in  3      -> profile 2.0, bed 1.0; NATURAL 2.3   -> 1.0
      (22,40) d_in  2 -> t = 2/3, smoothstep = (4/9)·(3-4/3) = 20/27
                      -> profile 40/27 = 1.481481481481,
                         bed 3 - 40/27 = 41/27 = 1.518518518519;
                         NATURAL 2.2 -> 1.518518518519
      (21,40) d_in  1 -> t = 1/3, smoothstep = (1/9)·(3-2/3) = 7/27
                      -> profile 14/27 = 0.518518518519,
                         bed 3 - 14/27 = 67/27 = 2.481481481481;
                         NATURAL 2.1 -> the MIN keeps 2.1, NOT 2.4814…
                         (the west shore already lies under the mirror; a
                          carve that assigned would RAISE the ground there)
      (60,40) d_in  0 -> profile 0, bed 3.0; NATURAL 6.0          -> 3.0
      (59,40) d_in  1 -> bed 67/27; NATURAL 5.9                   -> 67/27
      (20,40) d_in  0 -> bed 3.0;  NATURAL 2.0                    -> 2.0

    THE INVARIANT, checked over the WHOLE polygon on a dense grid: every
    sample deeper inside than shore_ramp_m (3 m) has
        h_final <= water_level - eps,   eps = min(water_depth_m, 0.25) = 0.25
    i.e. h <= 2.75 there. It holds with margin: the bed is 1.0 out there, and
    the natural ground is at most 6.0 which the MIN cuts to 1.0.

[2] THE DERIVED MIRROR (§ G4, "auto (rim)").  WATER_AUTO has no authored
    level, so the bake takes the MEDIAN of NATURAL along the rim, sampled
    every 2 m (``_rim_samples``). The square (120,120)-(160,160) has four
    20-sample edges, and NATURAL = (200-x)/10 on all of them:
      south  z=120, x = 120,122,…,158  -> 8.0, 7.8, …, 4.2
      east   x=160, z = 120,…,158      -> 4.0  (20x)
      north  z=160, x = 160,158,…,122  -> 4.0, 4.2, …, 7.8
      west   x=120, z = 160,…,122      -> 8.0  (20x)
    Sorted that is 21x 4.0, then 2x each of 4.2, 4.4, … 7.8, then 21x 8.0
    (21 + 38 + 21 = 80). The median of 80 values is the mean of the 40th and
    the 41st: the cumulative count reaches 39 at 5.8 and 41 at 6.0, so BOTH
    are 6.0 and the derived mirror is exactly

        water_level(WATER_AUTO) = 6.0

    Centre (140,140): d_in 20 >= 3 -> bed 6.0 - 2.0 = 4.0, NATURAL 6.0 -> 4.0.
    The EFFECTIVE level is reported for both lakes (E1b): 3.0 for the authored
    one, 6.0 for the derived one — and it is OUTPUT, never written back into
    the authored ``meta.water_level``.

[3] THE AUTO-PLATEAU (§ G5).  PLOT draws a built floor, so it stamps — no
    flag anywhere.

    TARGET = the MEDIAN of NATURAL over the footprint, sampled on the 2 m
    world lattice. Inside (70,-150)-(90,-130) that lattice holds x =
    70,72,…,90 (11 columns) x 11 rows, NATURAL = x/10 in every row, so the
    multiset is 11 copies each of 7.0, 7.2, …, 9.0 — 121 values whose median
    (the 61st) is the middle column:

        h0 = 8.0

    RAMP WIDTH: area = 20·20 = 400 m²,
        w = clamp(0.5·sqrt(400/pi), 2, 8) = 0.5·20/sqrt(pi) = 10/sqrt(pi)
          = 5.641895835477563 m
    SLOPE CAP: the biggest rim step is |8.0 - NATURAL| over x in [70,90],
    i.e. 1.0 m, and tan(35°)·w = 0.700207538·5.641895835 = 3.950567 m. 1.0 is
    under that, so the width is NOT widened.

    RAMP SHAPE outside the outline, blending back to what the pipeline holds:
        h = h0 + (h_before - h0)·smoothstep(d/w)
      (80,-140) inside, d = 0                     -> 8.0
      (70,-150) a corner, d = 0                   -> 8.0
      (92,-140) d = 2:  t = 2/w = 2·sqrt(pi)/10 = 0.354490770181103,
                        t² = 4·pi/100 = 0.125663706143592,
                        smoothstep = t²·(3-2t) = 0.28789787048…,
                        h_before = 9.2 -> 8.0 + 1.2·0.28789787 = 8.34547744458
      (90+w, -140) d = w exactly -> smoothstep 1 -> h_before = 9.5641895835…
      (96,-140) d = 6 > w -> untouched -> 9.6

    A TURNED PLOT is measured too ([3b2]): the model inlines the inverse pin
    transform (cos/sin precomputed once) instead of calling ``world_to_local``
    per point, so a 30° square is checked against the shared function at 729
    probes. Its median is STILL 8.0 — this landscape is a plane symmetric
    about x = 80, so a turn moves the samples and not their middle — while the
    SHAPE moves: the axis-aligned corner (89,-149) is (9,-9) from the pin, and
        lx = 9·cos30 + 9·sin30 = 7.7942286341 + 4.5 = 12.2942286341
        lz = 9·sin30 − 9·cos30 = 4.5 − 7.7942286341 = −3.2942286341
    put it 2.294229 m OUTSIDE the turned outline, i.e. on the ramp.

    RED COUNTER-PROBE (the OLD behaviour must now FAIL). The old pass pinned
    every point within ONE GRID CELL of the outline to the full plateau
    height. Rebuilt in this script from the module's own pieces, at (96,-140):
        old rule at step  2: d = 6 >  2 -> untouched   -> 9.6
        old rule at step 32: d = 6 <= 32 -> pinned      -> 8.0
    1.6 m apart at the SAME world point, which IS the "zwei Böden" bug. The
    new function answers 9.6 on both lattices.

[4] PURITY / COHERENCE (§ G1, claim (a)).  ``model.grid`` is evaluated over
    the window whose origin is (0,-256) at the steps 2, 4, 8, 16, 32 and 64 m,
    each covering the same 256 m square, and every coarse lattice point is
    compared with the 2 m value at the SAME world point. The lattices are
    nested (each step divides 64 and the origin is a multiple of it), so the
    equality is over 16 641 / 4 225 / 1 089 / 289 / 81 / 25 points and must be
    EXACT — not "within a tolerance": the same function, called twice.

    The same equality is then measured where it used to fail hardest: the
    overview raster (its own default 4 m step) against the two rastered tiles,
    at every point they share. That comparison is on the ROUNDED payload
    values, so it is exact too.

[5] THE MICRO-RELIEF EDGE RULE, now metre-based (§ G1).  The rule is
    unchanged in substance — a DIP is cut to 0 where the relief-carrying
    region ends — but it probes at a fixed 2 m instead of at "one grid cell".

    The noise is re-derived in this script from the documented formulas, NOT
    read from the module:
        seed(kind) = FNV-1a-32 over the UTF-8 bytes of the name
        rnd(u,v)   = XorShift32((seed + u·73856093 + v·19349663) mod 2^32)
                     .next01()·2 - 1
        noise(x,z) = bilinear of the four corners of the wave lattice · amp
    and the pipeline must reproduce it exactly inside the band.

    RED COUNTER-PROBE for the ruler: at (160,-64) the nearest band edge is
    the east one, 20 m away (the others are 36, 44 and 60 m), and the noise
    there is a DIP of -0.884847892448…
        the OLD rule on a 32 m raster probes (192,-64) -> outside the band
            -> the dip is CLAMPED to 0
        the OLD rule on a 2 m raster probes (158/162,-64) -> inside
            -> the dip is KEPT
    Two landscapes again, in the same place. The metre rule probes 2 m in
    every raster, so the dip is kept in all of them.

[6] THE PYRAMID (§ G2, claim (d)).  A tile reports ``min``/``max`` and, per
    mip level 4/8/16/32/64 m, the largest vertical error of drawing that level
    instead of the 2 m base.

    IT IS AN EXACT BOUND, not a sample, and the reason is arithmetic: the mip
    lattice is a SUBSET of the base lattice (every level is a multiple of 2 m
    and divides 256), so inside ONE base cell both fields are bilinear — the
    coarse one because a bilinear function stays bilinear on a sub-rectangle —
    and their difference is bilinear too. A bilinear function on a rectangle
    takes its extremes AT THE CORNERS, so the maximum over the base support
    points IS the maximum over the continuum.

    The check therefore samples the two interpolated fields on a lattice 4x
    finer than the base (a 513x513 sweep over the tile, i.e. 0.5 m) and
    asserts every sample is within the reported bound. Monotonicity is
    asserted too: a coarser level can only cost more.

[7] WHO STAMPS (§ G5). ``placed_footprints`` hands out every location that
    draws a BUILT floor and no other: a ``map3d.outline`` or at least one room
    that is not ``always_visible``; the yard (``__ground__``) never counts. A
    location with only open zones, or with no rooms at all, is natural and
    stamps nothing — and a leftover ``level_ground`` key in stored data
    changes neither answer (red counter-probe; there is no fallback reader).
    Closing a room therefore moves ``height_sig`` while the place stands
    perfectly still, and opening it again restores the signature exactly.

Usage:  ./.venv/bin/python scripts/smoke_height_bake.py
"""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="height-bake-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="hb-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import heightfield as hf  # noqa: E402
from app.core.world_geometry import (point_in_polygon,  # noqa: E402
                                     polygon_distance, world_to_local)

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


def near(label, actual, expected, tol=1e-9):
    global CHECKED
    CHECKED += 1
    ok = abs(float(actual) - float(expected)) <= tol
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r} (tol {tol})"))
    if not ok:
        FAILURES.append(label)


def check_true(label, value, expected=True):
    check(label, bool(value), expected)


def check_not(label, actual, forbidden):
    """The other half of a red counter-probe: the value a MUTANT would
    produce, asserted absent."""
    global CHECKED
    CHECKED += 1
    ok = actual != forbidden
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — this is the mutant's {forbidden!r}"))
    if not ok:
        FAILURES.append(label)


# ── The fixture ─────────────────────────────────────────────────────────

SLOPE = {"id": "ha_slope", "polygon": [[0, -400], [200, -400],
                                       [200, 400], [0, 400]],
         "height_m": 20.0, "falloff_m": 200.0, "meta": {}}

WATER_SET = {"id": "ta_lake_set", "kind": "lake", "z_order": 0,
             "polygon": [[20, 20], [60, 20], [60, 60], [20, 60]],
             "meta": {"water_level": 3.0, "water_depth_m": 2.0,
                      "shore_ramp_m": 3.0}}
WATER_AUTO = {"id": "ta_lake_auto", "kind": "lake", "z_order": 0,
              "polygon": [[120, 120], [160, 120], [160, 160], [120, 160]],
              "meta": {}}
GRASS = {"id": "ta_grass", "kind": "g", "z_order": 0,
         "polygon": [[100, -100], [180, -100], [180, -20], [100, -20]],
         "meta": {}}

CATALOG = {
    "lake": {"kind": "lake", "name": "Lake", "passable": True,
             "speed_factor": 0.4, "meta": {"water": True}},
    "g": {"kind": "g", "name": "Grass", "passable": True, "speed_factor": 1.0,
          "meta": {"relief_amplitude_m": 1.0, "relief_wave_m": 16.0}},
}

PLOT_LOCAL = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
PLOT = (80.0, -140.0, 0.0, PLOT_LOCAL)

TERRAIN = [WATER_SET, WATER_AUTO, GRASS]

MODEL = hf.build_model([SLOPE], [PLOT], TERRAIN, CATALOG)


def natural(x):
    """The hand formula of the fixture: NATURAL(x, z) = min(x, 200-x)/10."""
    return min(x, 200.0 - x) / 10.0


W = 10.0 / math.sqrt(math.pi)          # the plateau ramp width, exactly
H0 = 8.0                               # the plateau target, exactly


def ss(t):
    """smoothstep, re-derived here rather than imported."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


print("\n[0] the landscape under everything is the plane min(x, 200-x)/10")
for probe in (10.0, 40.0, 80.0, 92.0, 120.0, 160.0):
    near(f"NATURAL({probe}, -300) = {natural(probe)}",
         MODEL.natural(probe, -300.0), natural(probe))
near("…and the micro-relief does not reach there",
     MODEL.natural(128.0, -300.0), natural(128.0))


print("\n[0b] the model's PARSED-RING primitives == the shared ones")
# The bake parses every outline ONCE and works on the result, because
# ``world_geometry.point_in_polygon``/``polygon_distance`` re-parse theirs on
# every call and a raster calls them hundreds of thousands of times per tile.
# Two implementations of one rule is exactly what this plan exists to remove,
# so the two are measured against each other here — on a CONCAVE outline,
# where a "the polygon is its box" mistake shows up, and on its edges, where
# the ray-cast rule decides.
from app.core.world_geometry import polygon_distance  # noqa: E402
L_SHAPE = [[0, 0], [8, 0], [8, 4], [4, 4], [4, 8], [0, 8]]
L_RING = hf._ring(L_SHAPE)
_probe = [(x / 2.0, z / 2.0) for x in range(-4, 26) for z in range(-4, 26)]
check("point_in_polygon agrees at all 900 probes",
      [p for p in _probe
       if hf._inside_ring(p[0], p[1], L_RING)
       != point_in_polygon(p[0], p[1], L_SHAPE)], [])
check("polygon_distance agrees at all 900 probes",
      [p for p in _probe
       if abs(hf._ring_distance(p[0], p[1], L_RING)
              - polygon_distance(p[0], p[1], L_SHAPE)) > 1e-12], [])
check("edge_distance agrees too (the OUTLINE, 0 nowhere but on it)",
      [p for p in _probe
       if abs(hf._ring_edge_distance(p[0], p[1], L_RING)
              - hf.edge_distance(p[0], p[1], L_SHAPE)) > 1e-12], [])
near("...and the notch is really 4 m from the outline",
     hf._ring_distance(8.0, 8.0, L_RING), 4.0)


print("\n[1] the water carve — an authored mirror at 3.0 (§ G4)")
near("(40,40) deep: bed = 3.0 - 2.0", MODEL.final(40.0, 40.0), 1.0)
near("(23,40) d_in = 3, the full depth", MODEL.final(23.0, 40.0), 1.0)
near("(22,40) d_in = 2 -> 3 - 40/27", MODEL.final(22.0, 40.0), 3.0 - 40.0 / 27)
near("(59,40) d_in = 1 -> 3 - 14/27", MODEL.final(59.0, 40.0), 3.0 - 14.0 / 27)
near("(59.9,40) d_in = 0.1 -> 3 - 2·smoothstep(1/30)",
     MODEL.final(59.9, 40.0), 3.0 - 2.0 * ss(0.1 / 3.0), 1e-12)
near("…which is 2.99348148…", MODEL.final(59.9, 40.0), 2.9934814814814814,
     1e-12)
near("(60,40) EXACTLY on the outline is not inside it (the ray-cast rule),"
     " so nothing is carved", MODEL.final(60.0, 40.0), natural(60.0))
near("(20,40) on the west outline likewise — and there NATURAL is lower"
     " anyway", MODEL.final(20.0, 40.0), 2.0)
near("(21,40) d_in = 1, and the carve may only LOWER: NATURAL 2.1 stands",
     MODEL.final(21.0, 40.0), 2.1)
near("…the bed it did NOT write there would have been 3 - 14/27",
     3.0 - 14.0 / 27, 2.4814814814814814, 1e-12)
near("just OUTSIDE the polygon nothing is carved",
     MODEL.final(61.0, 40.0), natural(61.0))

print("\n[1b] the invariant, over the WHOLE polygon (0.5 m grid)")
EPS = min(2.0, 0.25)
deep_worst = -1e9
deep_count = 0
shallow_count = 0
POLY_SET = WATER_SET["polygon"]
x = 20.0
while x <= 60.0 + 1e-9:
    z = 20.0
    while z <= 60.0 + 1e-9:
        if point_in_polygon(x, z, POLY_SET):
            d_in = hf.edge_distance(x, z, POLY_SET)
            h = MODEL.final(x, z)
            if d_in > 3.0:
                deep_count += 1
                deep_worst = max(deep_worst, h)
            else:
                shallow_count += 1
        z += 0.5
    x += 0.5
# The 0.5 m lattice from 20 to 60 holds x = 23.5 … 56.5 (67 values) with
# d_in > 3 on each axis, so exactly 67² = 4489 samples are "deep".
check("exactly 67² samples are deeper than the 3 m shore ramp",
      deep_count, 4489)
near(f"…the HIGHEST of them ({deep_worst}) is at or under 3.0 - {EPS}",
     min(deep_worst, 3.0 - EPS), deep_worst, 1e-12)
check_true(f"…and {shallow_count} shore samples were skipped by the rule",
           shallow_count > 0)


print("\n[2] the DERIVED mirror of a lake without an authored level (§ G4)")
levels = MODEL.water_level_by_area
near("WATER_SET keeps the authored 3.0", levels["ta_lake_set"], 3.0)
near("WATER_AUTO derives the rim median 6.0", levels["ta_lake_auto"], 6.0)
near("…so its centre bed is 6.0 - 2.0", MODEL.final(140.0, 140.0), 4.0)
near("…and its west rim (120,140) keeps NATURAL 8.0 (already under 6.0? no)",
     MODEL.final(120.0, 140.0), 6.0)
# (120,140) is ON the outline: profile 0, bed = 6.0, NATURAL = 8.0 -> 6.0.
near("…while (160,140) on the east rim is already at 4.0 and stands",
     MODEL.final(160.0, 140.0), 4.0)

print("\n[2b] the EFFECTIVE level is reported additively (E1b)")
from app.core import terrain_types  # noqa: E402
from app.models import heightfield as store  # noqa: E402
from app.models import terrain as terrain_store  # noqa: E402

terrain_types.save_world_type(CATALOG["lake"])
terrain_types.save_world_type(CATALOG["g"])
store.save_height_area(SLOPE)
saved_set = terrain_store.save_area(WATER_SET)
saved_auto = terrain_store.save_area(WATER_AUTO)
terrain_store.save_area(GRASS)

near("saving an AUTHORED lake keeps its level",
     saved_set["meta"]["water_level"], 3.0)
near("saving an AUTO lake PERSISTS the derived rim median 6.0",
     saved_auto["meta"]["water_level"], 6.0)
payload = {a["id"]: a for a in
           hf.with_effective_water_level(terrain_store.list_areas())}
near("the authored lake reports 3.0 as its effective level",
     payload["ta_lake_set"]["meta"]["water_level_effective"], 3.0)
near("the settled lake reports 6.0", 
     payload["ta_lake_auto"]["meta"]["water_level_effective"], 6.0)
check("a non-water area gains no effective field at all",
      "water_level_effective" in payload["ta_grass"]["meta"], False)
check("the authored fields are untouched",
      [payload["ta_lake_set"]["meta"]["water_depth_m"],
       payload["ta_lake_set"]["meta"]["shore_ramp_m"]], [2.0, 3.0])

# A lake whose level is still UNSET in the DB (an area written before the
# field existed, or one the author cleared) still reports the derived one.
terrain_store.save_area({"id": "ta_lake_bare", "kind": "lake", "z_order": 0,
                         "polygon": WATER_AUTO["polygon"], "meta": {}})
import sqlite3  # noqa: E402
from app.core.db import transaction  # noqa: E402
with transaction() as conn:
    conn.execute("UPDATE terrain_areas SET meta='{}' WHERE id=?",
                 ("ta_lake_bare",))
hf.invalidate_cache()
bare = {a["id"]: a for a in
        hf.with_effective_water_level(terrain_store.list_areas())}
check("an UNSET lake carries no authored level…",
      "water_level" in bare["ta_lake_bare"]["meta"], False)
near("…and still reports the derived 6.0 as effective",
     bare["ta_lake_bare"]["meta"]["water_level_effective"], 6.0)

check("the sanitizer clamps the two widths and keeps a finite level",
      terrain_store.sanitize_area(
          {"kind": "lake", "polygon": WATER_SET["polygon"],
           "meta": {"water_level": 2.5, "water_depth_m": 99.0,
                    "shore_ramp_m": -4.0}})["meta"],
      {"water_level": 2.5, "water_depth_m": 20.0, "shore_ramp_m": 0.0})
check("the server's own output is dropped on the way back in",
      "water_level_effective" in terrain_store.sanitize_area(
          {"kind": "lake", "polygon": WATER_SET["polygon"],
           "meta": {"water_level": 2.5,
                    "water_level_effective": 2.5}})["meta"], False)
check("…and drops a junk level rather than storing NaN",
      "water_level" in terrain_store.sanitize_area(
          {"kind": "lake", "polygon": WATER_SET["polygon"],
           "meta": {"water_level": "later"}})["meta"], False)


print("\n[3] the auto-plateau: target = MEDIAN, ramp = metres (§ G5)")
stamp = MODEL.plateaus[0]
check("exactly one plateau stamp", len(MODEL.plateaus), 1)
near("its target is the median 8.0", stamp[5], H0)
near("its ramp is 10/sqrt(pi) m", stamp[6], W, 1e-12)
near("(80,-140) inside -> the target", MODEL.final(80.0, -140.0), H0)
near("(70,-150) a corner, d = 0 -> the target",
     MODEL.final(70.0, -150.0), H0)
near("(90,-140) ON the east edge -> the target",
     MODEL.final(90.0, -140.0), H0)
near("(92,-140) d = 2 -> 8.0 + 1.2·smoothstep(2/w)",
     MODEL.final(92.0, -140.0), H0 + (natural(92.0) - H0) * ss(2.0 / W), 1e-12)
near("…which is 8.34547744…", MODEL.final(92.0, -140.0),
     8.345477444577762, 1e-12)
near("(90+w,-140) d = w exactly -> the landscape again",
     MODEL.final(90.0 + W, -140.0), natural(90.0 + W), 1e-12)
near("(96,-140) d = 6 > w -> untouched", MODEL.final(96.0, -140.0),
     natural(96.0))
check_true("…and the whole plot is EXACTLY flat",
           max(abs(MODEL.final(70.0 + 0.5 * k, -150.0 + 0.5 * m) - H0)
               for k in range(41) for m in range(41)) < 1e-12)

print("\n[3b] the slope cap widens a ramp it has to")
# The same footprint on a landscape 6x as steep: SLOPE with height_m 120 makes
# NATURAL = 6·x/10, the plot spans x in [70,90] -> 42.0 … 54.0, median 48.0,
# rim step 6.0 m. The cap is on the STEEPEST metre and a smoothstep peaks at
# 1.5x its mean, so the test is 1.5·6.0 = 9.0 > tan(35°)·w = 3.950567… and the
# width has to become 1.5·6.0/tan(35°) = 12.853332… m — wider than the 8 m
# clamp, which is exactly what the cap is for.
STEEP = dict(SLOPE, height_m=120.0)
steep_model = hf.build_model([STEEP], [PLOT], (), None)
TAN35 = math.tan(math.radians(35.0))
near("the target is the median 48.0", steep_model.plateaus[0][5], 48.0)
near("the ramp is widened to 1.5·6.0/tan(35°)", steep_model.plateaus[0][6],
     1.5 * 6.0 / TAN35, 1e-12)
check_true("…which is wider than the 8 m clamp",
           steep_model.plateaus[0][6] > hf.PLATEAU_RAMP_MAX_M)
_w = steep_model.plateaus[0][6]
near("…so the ramp's PEAK gradient 1.5·6.0/w is exactly tan(35°)",
     1.5 * 6.0 / _w, TAN35, 1e-12)
near("…while the plot itself is flat at the median 48.0",
     steep_model.final(80.0, -140.0), 48.0)

print("\n[3b2] a TURNED plot — the inverse pin transform, spelled out twice")
# The stamp tests in the location's own LOCAL frame, and the model inlines the
# inverse pin transform (cos/sin precomputed once) instead of calling
# ``world_to_local`` per point. Two spellings of one rotation is exactly the
# kind of thing that drifts, so the turned case is measured against the shared
# function. 30° around the pin (80,-140), the same 20 m square.
TURNED = (80.0, -140.0, 30.0, PLOT_LOCAL)
turned_model = hf.build_model([SLOPE], [TURNED], (), None)
_probe = [(80.0 + 0.5 * a, -140.0 + 0.5 * b)
          for a in range(-40, 41, 3) for b in range(-40, 41, 3)]
_cx, _cz, _yaw, _pts, _box, _h0, _w = turned_model.plateaus[0]
_off = []
for px, pz in _probe:
    lx, lz = world_to_local(px, pz, _cx, _cz, _yaw)
    d = polygon_distance(lx, lz, _pts)
    want = _h0 if d <= 0.0 else (
        _h0 + (turned_model.natural(px, pz) - _h0) * ss(d / _w)
        if d < _w else turned_model.natural(px, pz))
    if abs(turned_model.final(px, pz) - want) > 1e-12:
        _off.append((px, pz))
check(f"the turned stamp matches world_to_local + polygon_distance at all "
      f"{len(_probe)} probes", _off, [])
near("...and the plot is still flat at its own median",
     turned_model.final(80.0, -140.0), turned_model.plateaus[0][5], 1e-12)
near("...and the median is STILL 8.0, because this landscape is a plane that "
     "is symmetric about x = 80 — a turn moves the samples, not their middle",
     turned_model.plateaus[0][5], H0, 1e-12)
# What the turn DOES move is the shape: the axis-aligned corner (89,-149) is
# inside the square and flat at 8.0, while the turned outline has swung away
# from it — 30° puts that corner 3.5 m outside, on the ramp.
near("the corner (89,-149) is inside the axis-aligned plot",
     MODEL.final(89.0, -149.0), H0)
_lx, _lz = world_to_local(89.0, -149.0, _cx, _cz, _yaw)
# By hand: (89,-149) is (dx, dz) = (9, -9) from the pin, and with cos 30° =
# 0.8660254038, sin 30° = 0.5 the inverse transform gives
#   lx = 9·0.8660254038 − (−9)·0.5 = 7.7942286341 + 4.5 = 12.2942286341
#   lz = 9·0.5 + (−9)·0.8660254038 = 4.5 − 7.7942286341 = −3.2942286341
# lz is inside [-10,10], lx is 2.2942286341 past the east edge.
near("...but 2.294229 m outside the turned one",
     polygon_distance(_lx, _lz, _pts), 12.2942286341 - 10.0, 1e-9)
check_not("...so the turned model answers something else there",
          round(turned_model.final(89.0, -149.0), 6), round(H0, 6))


print("\n[3c] RED COUNTER-PROBE: the OLD one-cell ramp, rebuilt here")


def old_plateau(x, z, step):
    """The pass as it was: everything within ONE GRID CELL of the outline is
    pinned to the full plateau height, no blend at all."""
    h = MODEL.natural(x, z)
    lx, lz = world_to_local(x, z, PLOT[0], PLOT[1], PLOT[2])
    if polygon_distance(lx, lz, PLOT_LOCAL) <= step + 1e-9:
        return H0
    return h


near("old rule, 2 m raster, (96,-140): 6 m out, untouched",
     old_plateau(96.0, -140.0, 2.0), 9.6)
near("old rule, 32 m raster, the SAME point: pinned",
     old_plateau(96.0, -140.0, 32.0), H0)
near("…the two landscapes are 1.6 m apart",
     old_plateau(96.0, -140.0, 32.0) - old_plateau(96.0, -140.0, 2.0), -1.6,
     1e-12)
check_true("the NEW function does not answer the old 8.0 there",
           abs(MODEL.final(96.0, -140.0) - H0) > 1.0)
near("…it answers 9.6 whichever lattice asks",
     MODEL.final(96.0, -140.0), 9.6)


print("\n[4] PURITY: six lattices over the same 256 m square must AGREE")
WIN_X, WIN_Z = 0.0, -256.0
base = MODEL.grid(WIN_X, WIN_Z, 2.0, 129, 129)
for level in (4.0, 8.0, 16.0, 32.0, 64.0):
    stride = int(level / 2.0)
    n = 128 // stride + 1
    coarse = MODEL.grid(WIN_X, WIN_Z, level, n, n)
    worst = 0.0
    for j in range(n):
        for i in range(n):
            worst = max(worst, abs(coarse[j][i]
                                   - base[j * stride][i * stride]))
    near(f"{level:g} m lattice == 2 m lattice at all {n * n} shared points",
         worst, 0.0, 0.0)

print("\n[4b] …and the OVERVIEW agrees with the TILES point for point")
overview = hf.rasterize([SLOPE], footprints=[PLOT], terrain_areas=TERRAIN,
                        terrain_catalog=CATALOG, model=MODEL)
check("the overview stands at the default 4 m step", overview["step_m"], 4.0)
shared = 0
worst = 0.0
for tx, tz in ((0, 0), (0, -1)):
    tile = hf.rasterize_tile(tx, tz, (), model=MODEL)
    for j in range(tile["rows"]):
        pz = tile["origin_z"] + j * hf.TILE_STEP_M
        for i in range(tile["cols"]):
            px = tile["origin_x"] + i * hf.TILE_STEP_M
            fi = (px - overview["origin_x"]) / overview["step_m"]
            fj = (pz - overview["origin_z"]) / overview["step_m"]
            if abs(fi - round(fi)) > 1e-9 or abs(fj - round(fj)) > 1e-9:
                continue
            oi, oj = int(round(fi)), int(round(fj))
            if not (0 <= oi < overview["cols"] and 0 <= oj < overview["rows"]):
                continue
            shared += 1
            worst = max(worst, abs(overview["heights"][oj][oi]
                                   - tile["heights"][j][i]))
check_true(f"{shared} points are shared by the overview and the two tiles",
           shared > 4000)
near("…and every one of them carries the same number", worst, 0.0, 0.0)


print("\n[5] the micro-relief, re-derived from the documented formulas")


def fnv1a(name):
    h = 2166136261
    for byte in name.encode("utf-8"):
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return h


def xorshift01(state):
    state &= 0xFFFFFFFF
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    state &= 0xFFFFFFFF
    return state / 4294967296.0


def rnd(seed, u, v):
    return xorshift01((seed + u * 73856093 + v * 19349663) & 0xFFFFFFFF) \
        * 2.0 - 1.0


def hand_noise(x, z, seed, amp=1.0, wave=16.0):
    fx, fz = x / wave, z / wave
    u, v = math.floor(fx), math.floor(fz)
    tx, tz = fx - u, fz - v
    north = rnd(seed, u, v) * (1 - tx) + rnd(seed, u + 1, v) * tx
    south = rnd(seed, u, v + 1) * (1 - tx) + rnd(seed, u + 1, v + 1) * tx
    return (north * (1 - tz) + south * tz) * amp


SEED_G = fnv1a("g")
check("the seed of the kind is its FNV-1a hash", SEED_G, hf.relief_seed("g"))
for px, pz in ((160.0, -64.0), (140.0, -55.0), (110.0, -30.0)):
    near(f"the pipeline carries the hand noise at ({px},{pz})",
         MODEL.natural(px, pz) - natural(px), hand_noise(px, pz, SEED_G),
         1e-12)
DIP = hand_noise(160.0, -64.0, SEED_G)
check_true(f"…and that value ({DIP:.6f}) is a DIP, which the probe is about",
           DIP < 0.0)

print("\n[5b] RED COUNTER-PROBE: the OLD grid-neighbour edge rule")


def in_band(x, z):
    return point_in_polygon(x, z, GRASS["polygon"])


def old_edge(x, z, step):
    """The rule as it was: probe the four GRID neighbours, i.e. at ±step."""
    n = hand_noise(x, z, SEED_G)
    if n < 0.0 and not (in_band(x - step, z) and in_band(x + step, z)
                        and in_band(x, z - step) and in_band(x, z + step)):
        return 0.0
    return n


near("old rule at 2 m keeps the dip", old_edge(160.0, -64.0, 2.0), DIP, 1e-12)
near("old rule at 32 m clamps it away", old_edge(160.0, -64.0, 32.0), 0.0)
near("…which is a step of |DIP| between the two rasters",
     abs(old_edge(160.0, -64.0, 32.0) - old_edge(160.0, -64.0, 2.0)),
     abs(DIP), 1e-12)
near("the NEW rule probes 2 m whoever asks — the dip survives",
     MODEL.natural(160.0, -64.0) - natural(160.0), DIP, 1e-12)
check("the probe distance is a metre constant", hf.RELIEF_EDGE_PROBE_M, 2.0)
# …and the rule itself is intact: a dip ON the band edge is still cut off.
near("a dip 1 m inside the band edge is still clamped to 0",
     MODEL.natural(101.0, -60.0) - natural(101.0),
     max(0.0, hand_noise(101.0, -60.0, SEED_G)), 1e-12)


print("\n[6] the pyramid: min/max and a TRUE error bound per mip level")
TILE = hf.rasterize_tile(0, -1, (), model=MODEL)
stats = hf.tile_stats_from(TILE)
flat = [v for row in TILE["heights"] for v in row]
near("min is the tile's own minimum", stats["min"], round(min(flat), 3))
near("max is the tile's own maximum", stats["max"], round(max(flat), 3))
check("one error per mip level", len(stats["err"]), len(hf.MIP_LEVELS_M))
check_true("a coarser level can only cost more",
           all(stats["err"][k] <= stats["err"][k + 1] + 1e-9
               for k in range(len(stats["err"]) - 1)))


def bilinear(grid, step, ox, oz, x, z):
    """The sampler of the payload, spelled out here."""
    n = len(grid)
    fx = min(max((x - ox) / step, 0.0), n - 1.0)
    fz = min(max((z - oz) / step, 0.0), n - 1.0)
    i = min(int(math.floor(fx)), n - 2)
    j = min(int(math.floor(fz)), n - 2)
    tx, tz = fx - i, fz - j
    north = grid[j][i] * (1 - tx) + grid[j][i + 1] * tx
    south = grid[j + 1][i] * (1 - tx) + grid[j + 1][i + 1] * tx
    return north * (1 - tz) + south * tz


OX, OZ = TILE["origin_x"], TILE["origin_z"]
BASE = TILE["heights"]
for k, level in enumerate(hf.MIP_LEVELS_M):
    stride = int(level / hf.TILE_STEP_M)
    mip = [[BASE[j][i] for i in range(0, 129, stride)]
           for j in range(0, 129, stride)]
    bound = stats["err"][k]
    worst = 0.0
    steps = 512
    for j in range(steps + 1):
        z = OZ + 256.0 * j / steps
        for i in range(steps + 1):
            x = OX + 256.0 * i / steps
            a = bilinear(BASE, hf.TILE_STEP_M, OX, OZ, x, z)
            b = bilinear(mip, level, OX, OZ, x, z)
            worst = max(worst, abs(a - b))
    check_true(f"{level:g} m: {worst:.4f} m measured on a 0.5 m sweep "
               f"<= the reported bound {bound:.4f} m",
               worst <= bound + 5e-4)
    check_true(f"…and the bound is TIGHT (within a millimetre of the sweep)",
               bound - worst < 1e-3)


print("\n[7] a BUILT location stamps, a NATURAL one does not (§ G5)")
from app.models import world as world_store  # noqa: E402

BOUNDARY = [[-10, -10], [10, -10], [10, 10], [-10, 10]]


def loc(**kw):
    base = {"id": "l1", "name": "Place", "pos_x": 80.0, "pos_z": -140.0,
            "yaw_deg": 0.0, "map3d": {"boundary": BOUNDARY}, "rooms": []}
    base.update(kw)
    return base


def with_locations(locs):
    world_store.list_locations = lambda: list(locs)


with_locations([loc(rooms=[{"id": "r1", "layout": {}}])])
check("a location with a CLOSED room stamps", store.placed_footprints(),
      [(80.0, -140.0, 0.0, [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0),
                            (-10.0, 10.0)])])
with_locations([loc(rooms=[{"id": "r1",
                            "layout": {"always_visible": True}}])])
check("a location whose only room is an OPEN zone does not",
      store.placed_footprints(), [])
with_locations([loc(rooms=[{"id": "r1", "layout": {"always_visible": True}}],
                    map3d={"boundary": BOUNDARY,
                           "outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]]})])
check("…unless it draws a BUILDING outline", len(store.placed_footprints()), 1)
with_locations([loc(rooms=[])])
check("a location with no rooms and no outline is natural",
      store.placed_footprints(), [])
from app.models.world import GROUND_ROOM_ID  # noqa: E402
with_locations([loc(rooms=[{"id": GROUND_ROOM_ID, "layout": {}}])])
check("the YARD is not a closed room (§ A13a)",
      store.placed_footprints(), [])
_flagged = loc(rooms=[], level_ground=True)
with_locations([_flagged])
check("RED COUNTER-PROBE: the dead level_ground flag stamps nothing now",
      store.placed_footprints(), [])

print("\n[7b] …and the signature follows the built/natural answer")
with_locations([loc(rooms=[{"id": "r1", "layout": {}}])])
sig_built = store.height_sig()
with_locations([loc(rooms=[{"id": "r1",
                            "layout": {"always_visible": True}}])])
sig_open = store.height_sig()
check("closing a room changes the height signature", sig_built != sig_open,
      True)
with_locations([loc(rooms=[{"id": "r1", "layout": {}}])])
check("…and reopening it restores the old one", store.height_sig(), sig_built)


print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
for name in FAILURES:
    print(f"  FAILED: {name}")
sys.exit(1 if FAILURES else 0)
