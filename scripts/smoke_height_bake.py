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

THE FIFTH STAGE IS GONE since W1 ("Ein Wasser-Gesetz", 2026-08-21). A room
whose floor kind was water used to carve its own bed AFTER the plateaus; water
left the room plan entirely, so the stage, its inputs and its signature basis
are deleted without a fallback reader — asserted BY NAME in section [9].

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
    GRASS       band (100,-100)-(180,-20), kind "g", with its OWN
                relief_amplitude_m 1.0, relief_wave_m 16
    PLOT        a BUILT location, pin (80,-140), yaw 0, local outline the
                centred 20 m square -> world (70,-150)-(90,-130)

The catalog is two entries: "lake" carries ``meta.water`` (that flag, never the
NAME, is what makes a kind carve — kinds are an open vocabulary) and "g"
carries NOTHING. The two relief numbers are the AREA's since 2026-08-23: a
kind-level amplitude made every meadow of a world equally bumpy, and section
[5c] is the case the old model could not express at all.

Section [8] adds the SLOPED MIRROR of W1 on its own model: a water area may
declare a ``flow_dir_deg``, and then its mirror is not one number but a plane
tilted along that axis, interpolated between an UPSTREAM and a DOWNSTREAM level
that are each the rim median of their own third of the axis span. The carve
runs against that LOCAL level, so the invariant becomes a pointwise statement.
Section [8k] is W4a on top of it: an area DRAWN AS A LINE flows along that line
(``meta.flow_along``), so the axis is a POLYLINE with one knot per drawn point
— and the two laws above are its one-knot and its two-knot case, read by the
same function. Section [9] is the deletion proof of the fifth stage.

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
        h_final <= level_at(x, z) - eps,  eps = min(water_depth_m, 0.25) = 0.25
    which for this still lake is the constant 3.0 it always was (section [8g]
    restates it on a river, where the two are not the same number)
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
    the authored ``meta.water_level``. Beside it rides the effective DEPTH
    (``water_depth_effective``, W4b): the kind's default with the area's
    override applied, 2.0 for these lakes and 1.0 for the river of [8j], which
    is the number a renderer draws the shore's opacity from (¾ of it).

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

[5c] TWO AREAS OF ONE KIND, TWO RELIEFS (decision 2026-08-23) — the case the
    kind-level model could not express at all. Three bands of the SAME kind
    "g", side by side, outside every height area, so h_final IS the relief:

        C  x in [140,200]  amplitude 1.00, wave 16
        A  x in [200,300]  amplitude 1.00, wave 16
        B  x in [300,400]  amplitude 0.25, wave 16

    The seed is STILL hashed from the kind name, so all three sample the ONE
    noise field of "g"; only how tall it stands is theirs. Both probe points
    are lattice CORNERS (x a multiple of the 16 m wave), where the bilinear
    mix collapses to the single draw rnd(u, v) — and both draws are positive,
    so the edge rule cannot touch them:

        (240,-64)  u=15, v=-4  rnd = +0.601476330776 -> h = 0.601476330776
        (368,-64)  u=23, v=-4  rnd = +0.329562937841 -> h = 0.082390734460
                                                          = rnd · 0.25

    RED COUNTER-PROBE, THE OLD MODEL: put the two numbers back on the KIND and
    leave the areas silent — the state every world was in before this change —
    and the ground is FLAT at both points, because nothing reads the kind any
    more (`relief_inputs` answers an empty list). And where the old model DID
    work it had one amplitude for both bands: it would give B the full draw,
    4 × the 0.082390734460 the area asks for.

    THE SEAMS, both of them, out of the same field:
        C | A (x=200, SAME numbers): 0.051160196017 -> 0.156314309512, a step
            of 0.105154113495 m over 2 m — the field's own slope, no seam
        A | B (x=300, DIFFERENT amplitudes): -0.170306254062 -> the same field
            at a quarter, -0.048629130266; a step of 0.121677123796 m. That is
            the authored price of a per-area relief and not a defect: the
            amplitude changes where the author drew the contour.

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
         "meta": {"relief_amplitude_m": 1.0, "relief_wave_m": 16.0}}

CATALOG = {
    "lake": {"kind": "lake", "name": "Lake", "passable": True,
             "speed_factor": 0.4, "meta": {"water": True}},
    "g": {"kind": "g", "name": "Grass", "passable": True, "speed_factor": 1.0,
          "meta": {}},
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
profiles = MODEL.water_profile_by_area
near("WATER_SET keeps the authored 3.0",
     profiles["ta_lake_set"].level_up, 3.0)
near("WATER_AUTO derives the rim median 6.0",
     profiles["ta_lake_auto"].level_up, 6.0)
check("...and STILL water carries the same number at BOTH ends of its "
      "profile — the lake is the degenerate river",
      [profiles[k].level_up == profiles[k].level_down
       and profiles[k].flow_dir_deg is None
       and profiles[k].s_min == profiles[k].s_max
       for k in ("ta_lake_set", "ta_lake_auto")], [True, True])
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
check("...and the PROFILE rides along additively (W1): still water, both "
      "ends equal, no flow, and (W4a) ONE axis knot at the centroid",
      payload["ta_lake_set"]["meta"]["water_profile"],
      {"level_up": 3.0, "level_down": 3.0, "flow_dir_deg": None,
       "axis_x": 40.0, "axis_z": 40.0, "dir_x": 0.0, "dir_z": 0.0,
       "s_min": 0.0, "s_max": 0.0, "axis": [[40.0, 40.0, 0.0, 3.0]]})
near("...and so does the bed DEPTH the carve used (W4b): the renderer draws "
     "a water fully at ¾ of it and must not resolve kind-vs-area a second time",
     payload["ta_lake_set"]["meta"]["water_depth_effective"], 2.0)
check("a non-water area gains no effective field at all",
      "water_level_effective" in payload["ta_grass"]["meta"], False)
check("...and no effective depth either",
      "water_depth_effective" in payload["ta_grass"]["meta"], False)
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


print("\n[5c] TWO AREAS, ONE KIND, TWO RELIEFS — the case the kind could not say")
# THE FIXTURE (pure literals again, no DB): three bands of the SAME kind "g",
# side by side, at z in [-100,-20] and outside every height area, so h_final IS
# the micro-relief and nothing else.
#     C  x in [140,200]  amplitude 1.0,  wave 16
#     A  x in [200,300]  amplitude 1.0,  wave 16
#     B  x in [300,400]  amplitude 0.25, wave 16
C5 = {"id": "ta_c", "kind": "g", "z_order": 0,
      "polygon": [[140, -100], [200, -100], [200, -20], [140, -20]],
      "meta": {"relief_amplitude_m": 1.0, "relief_wave_m": 16.0}}
A5 = {"id": "ta_a", "kind": "g", "z_order": 0,
      "polygon": [[200, -100], [300, -100], [300, -20], [200, -20]],
      "meta": {"relief_amplitude_m": 1.0, "relief_wave_m": 16.0}}
B5 = {"id": "ta_b", "kind": "g", "z_order": 0,
      "polygon": [[300, -100], [400, -100], [400, -20], [300, -20]],
      "meta": {"relief_amplitude_m": 0.25, "relief_wave_m": 16.0}}
M5 = hf.build_model([], [], [C5, A5, B5], CATALOG)

# THE SEED IS STILL THE KIND'S, the two numbers are the AREA's — which is the
# whole sentence of the move, read off the parameter tuple.
check("both areas answer the SAME seed, hashed from the one kind name",
      (hf.relief_params("g", A5)[0], hf.relief_params("g", B5)[0]),
      (SEED_G, SEED_G))
check("...and two DIFFERENT amplitudes, each its own area's",
      (hf.relief_params("g", A5)[1:], hf.relief_params("g", B5)[1:]),
      ((1.0, 16.0), (0.25, 16.0)))

# THE TWO POINTS, both lattice CORNERS (x a multiple of the 16 m wave), where
# the bilinear mix collapses to the single corner draw rnd(u, v) — so the
# expected height is one hand-derived number times the area's own amplitude.
# Both draws are POSITIVE, so the edge rule cannot reach them either way.
#   (240,-64): u = 15, v = -4, rnd = +0.601476330776 -> h = 0.601476330776
#   (368,-64): u = 23, v = -4, rnd = +0.329562937841 -> h = 0.082390734460
RND_15_M4 = rnd(SEED_G, 15, -4)
RND_23_M4 = rnd(SEED_G, 23, -4)
near("rnd(15,-4), the corner under A, derived by hand",
     RND_15_M4, 0.601476330776, 1e-11)
near("rnd(23,-4), the corner under B", RND_23_M4, 0.329562937841, 1e-11)
near("A stands at the full draw — amplitude 1.0",
     M5.final(240.0, -64.0), 0.601476330776, 1e-11)
near("B stands at a QUARTER of its own draw — amplitude 0.25",
     M5.final(368.0, -64.0), 0.082390734460, 1e-11)
near("...i.e. exactly the area's own amplitude, not the kind's",
     M5.final(368.0, -64.0) / RND_23_M4, 0.25, 1e-12)
check_true("the two areas of ONE kind are two different grounds",
           abs(M5.final(240.0, -64.0)) > 4.0 * abs(M5.final(368.0, -64.0)))

# RED COUNTER-PROBE, THE OLD MODEL: put the two numbers back on the KIND and
# leave the areas silent. That is what every world looked like before
# 2026-08-23 — and now it is FLAT, because nothing reads the kind any more.
OLD_CATALOG = {**CATALOG,
               "g": {**CATALOG["g"],
                     "meta": {"relief_amplitude_m": 1.0,
                              "relief_wave_m": 16.0}}}
SILENT = [{**A5, "meta": {}}, {**B5, "meta": {}}]
check("red: with the numbers on the KIND, nothing is an input at all",
      hf.relief_inputs(SILENT), [])
M5_OLD = hf.build_model([], [], SILENT, OLD_CATALOG)
near("red: ...and the ground under both areas is 0.0",
     abs(M5_OLD.final(240.0, -64.0)) + abs(M5_OLD.final(368.0, -64.0)), 0.0)
# …and the other half of the counter-probe: the old model could not tell the
# two bands apart even when it DID work — one kind, one amplitude, so the two
# points would have differed only by their draws.
near("red: the old model gives B the FULL draw, four times what it asks for",
     hf.micro_relief_at((SEED_G, 1.0, 16.0), 368.0, -64.0),
     4.0 * 0.082390734460, 1e-11)

# THE SEED STAYED SHARED, and that is what keeps a world in one piece: C and A
# ask for the same two numbers, so their common border at x = 200 carries no
# seam — the value on either side is the ONE noise field, sampled 1 m apart.
near("two areas with the same numbers continue each other: west of the seam",
     M5.final(199.0, -64.0), hand_noise(199.0, -64.0, SEED_G, 1.0, 16.0),
     1e-11)
near("...and east of it, out of the very same field",
     M5.final(201.0, -64.0), hand_noise(201.0, -64.0, SEED_G, 1.0, 16.0),
     1e-11)
near("…so the step across that seam is the FIELD's own slope and nothing "
     "else: 0.156314309512 - 0.051160196017",
     M5.final(201.0, -64.0) - M5.final(199.0, -64.0), 0.105154113495, 1e-11)

# AND THE OTHER SEAM, where the two numbers DIFFER (A | B at x = 300), is the
# honest price of the move: the amplitude jumps at the painted contour, so the
# ground does too. Both sides are hand-derived from the ONE noise field:
#   (299,-64)  noise -0.170306254062 x 1.00 = -0.170306254062
#   (301,-64)  noise -0.194516521064 x 0.25 = -0.048629130266
near("at the seam between two DIFFERENT amplitudes the west side is A's",
     M5.final(299.0, -64.0), -0.170306254062, 1e-11)
near("...and the east side is a quarter of the same field, B's",
     M5.final(301.0, -64.0), -0.048629130266, 1e-11)
near("...a step of 0.121677123796 m over 2 m — authored, not a bug",
     M5.final(301.0, -64.0) - M5.final(299.0, -64.0), 0.121677123796, 1e-11)


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



# ── [8] THE SLOPED MIRROR: a river is a plane, not a level (W1) ─────────
print("\n[8] the mirror PROFILE — a river's level is a function of the place")
# THE FIXTURE, on its OWN model so the arithmetic above stays untouched. The
# landscape is the same plane NATURAL(x, z) = min(x, 200-x)/10, i.e. x/10 on
# everything below, and it is z-independent for |z| <= 200.
#
#   RIVER_AUTO   rectangle (20,-40)-(80,-20), kind "river",
#                flow_dir_deg 270, NO authored level -> both ends derived
#   RIVER_SET    the same rectangle at z -80..-60, flow_dir_deg 270, with
#                water_level_up 9.5 / water_level_down 0.5 AUTHORED
#   CREEK        the same shape again at z -120..-100 painted with a kind that
#                carries the two water numbers but NOT the water flag: the
#                world-shaped case, and it must carve NOTHING
#
# The kind "river" carries the DEFAULTS water_depth_m 1.0 / shore_ramp_m 3.0.
# Neither area repeats them, so every number below is the KIND's.
#
# THE DIRECTION. ``flow_dir_deg`` is spelled like every other yaw in the
# contract: dir = (sin t, cos t). 270 deg -> (-1, 0), i.e. the water flows
# toward -x, which is downhill on this landscape.
#
# THE AXIS. Centroid of the rectangle = (50, -30); s(p) = (p - centroid) . dir
# = 50 - x. Over the polygon s runs from -30 (x = 80, UPSTREAM) to +30
# (x = 20, DOWNSTREAM), so span = 60 and a third is 20.
#     upstream third:   s <= -30 + 20 = -10  <=>  x >= 60
#     downstream third: s >=  30 - 20 =  10  <=>  x <= 40
#
# THE RIM SAMPLES (``_rim_samples``, 2 m apart, the START vertex of each edge
# included and the END one left to the next edge):
#     south (20,-40)->(80,-40): 30 samples, x = 20, 22, ..., 78
#     east  (80,-40)->(80,-20): 10 samples, x = 80
#     north (80,-20)->(20,-20): 30 samples, x = 80, 78, ..., 22
#     west  (20,-20)->(20,-40): 10 samples, x = 20
#
# UPSTREAM THIRD (x >= 60): south contributes 60,62,...,78 (10), east 10 x 80,
# north 80,78,...,60 (11) = 31 samples. As a multiset of x/10 that is
#     2 x each of 6.0, 6.2, ..., 7.8   (20 values)   and   11 x 8.0
# Sorted, the 16th of 31 is the median; the cumulative count reaches 16 at
# 7.4 (2+2+2+2+2+2+2 = 14 up to 7.2, then 7.4 takes 15 and 16), so
#
#     level_up = 7.4
#
# DOWNSTREAM THIRD (x <= 40): south 20,22,...,40 (11), north 40,38,...,22 (10),
# west 10 x 20 = 31 samples, i.e.
#     11 x 2.0   and   2 x each of 2.2, 2.4, ..., 4.0
# The 16th is 2.6 (11 at 2.0, 13 at 2.2, 15 at 2.4, 17 at 2.6), so
#
#     level_down = 2.6
#
# THE PROFILE, written out. t = (s - s_min)/span = (80 - x)/60, and
#     level_at(x) = 7.4 + (2.6 - 7.4) * (80 - x)/60
#                 = 7.4 - 0.08 * (80 - x)
#                 = 0.08 * x + 1.0
# which is 2.6 at x = 20, 5.0 at the centroid x = 50 and 7.4 at x = 80.
# The EFFECTIVE level (what a flat consumer draws one plane at) is the mean of
# the two ends, 5.0 — the level at the middle of the axis.
#
# THE CARVE against that LOCAL level, depth 1.0 over a 3 m shore ramp:
#     h = min(h, level_at(x) - 1.0 * smoothstep(min(d_in/3, 1)))
#   (50,-30) d_in = 10 >= 3 -> 5.00 - 1.0 = 4.00 ; NATURAL 5.0 -> 4.00
#   (26,-30) d_in =  6      -> 3.08 - 1.0 = 2.08 ; NATURAL 2.6 -> 2.08
#   (74,-30) d_in =  6      -> 6.92 - 1.0 = 5.92 ; NATURAL 7.4 -> 5.92
#   (22,-30) d_in =  2 -> t = 2/3, smoothstep = 20/27
#                      -> 2.76 - 20/27 = 2.019259259259...  ; NATURAL 2.2
#   (20,-30) ON the outline is not inside it (the ray-cast rule) -> NATURAL 2.0
CATALOG_R = dict(CATALOG)
CATALOG_R["river"] = {"kind": "river", "name": "River", "passable": True,
                      "speed_factor": 0.4,
                      "meta": {"water": True, "water_depth_m": 1.0,
                               "shore_ramp_m": 3.0}}
CATALOG_R["creek"] = {"kind": "creek", "name": "Creek (unflagged)",
                      "passable": True, "speed_factor": 0.6,
                      "meta": {"water_depth_m": 1.0, "shore_ramp_m": 3.0}}

RIVER_AUTO = {"id": "ta_river_auto", "kind": "river", "z_order": 0,
              "polygon": [[20, -40], [80, -40], [80, -20], [20, -20]],
              "meta": {"flow_dir_deg": 270}}
RIVER_SET = {"id": "ta_river_set", "kind": "river", "z_order": 0,
             "polygon": [[20, -80], [80, -80], [80, -60], [20, -60]],
             "meta": {"flow_dir_deg": 270, "water_level_up": 9.5,
                      "water_level_down": 0.5}}
CREEK = {"id": "ta_creek", "kind": "creek", "z_order": 0,
         "polygon": [[20, -120], [80, -120], [80, -100], [20, -100]],
         "meta": {"flow_dir_deg": 270}}

RMODEL = hf.build_model([SLOPE], [], [RIVER_AUTO, RIVER_SET, CREEK], CATALOG_R)

print("\n[8a] the bearing is the contract's own yaw: dir = (sin t, cos t)")
check("0 deg flows toward +z", hf.flow_direction(0.0), (0.0, 1.0))
check("90 deg toward +x", hf.flow_direction(90.0), (1.0, 0.0))
check("180 deg toward -z", hf.flow_direction(180.0), (0.0, -1.0))
check("270 deg toward -x — the fixture's downhill", hf.flow_direction(270.0),
      (-1.0, 0.0))
check("a bearing WRAPS, it does not clamp: 370 is 10", hf.sanitize_flow_dir(370),
      10.0)
check("...and -90 is 270", hf.sanitize_flow_dir(-90), 270.0)
check("junk and blanks are 'still', not 0", [hf.sanitize_flow_dir(x)
                                             for x in ("", None, "abc",
                                                       float("nan"))],
      [None, None, None, None])

print("\n[8b] the DERIVED ends: a rim median per THIRD of the axis")
AUTO = RMODEL.water_profile_by_area["ta_river_auto"]
near("the axis runs through the centroid, x", AUTO.axis_x, 50.0)
near("...and z", AUTO.axis_z, -30.0)
check("the direction is exactly (-1, 0)", (AUTO.dir_x, AUTO.dir_z), (-1.0, 0.0))
near("the polygon spans s = -30 (upstream)", AUTO.s_min, -30.0)
near("...to s = +30 (downstream)", AUTO.s_max, 30.0)
near("level_up  = the median of the upstream third = 7.4", AUTO.level_up, 7.4)
near("level_down = the median of the downstream third = 2.6", AUTO.level_down,
     2.6)

print("\n[8c] level_at(x, z) = 0.08 x + 1.0 — hand-derived, then measured")
for _x in (20.0, 26.0, 35.0, 50.0, 74.0, 80.0):
    near(f"level_at({_x}) = {0.08 * _x + 1.0}",
         hf.water_level_at(AUTO, _x, -30.0), 0.08 * _x + 1.0, 1e-12)
near("...and it does not depend on z at all (the axis is the x axis here)",
     hf.water_level_at(AUTO, 35.0, -21.0),
     hf.water_level_at(AUTO, 35.0, -39.0))
near("past the upstream extreme it CLAMPS to level_up",
     hf.water_level_at(AUTO, 200.0, -30.0), 7.4)
near("...and past the downstream one to level_down",
     hf.water_level_at(AUTO, -200.0, -30.0), 2.6)

print("\n[8d] the carve uses the LOCAL level")
near("(50,-30) mid-river: 5.00 - 1.0", RMODEL.final(50.0, -30.0), 4.0, 1e-12)
near("(26,-30) downstream: 3.08 - 1.0", RMODEL.final(26.0, -30.0), 2.08, 1e-12)
near("(74,-30) upstream: 6.92 - 1.0", RMODEL.final(74.0, -30.0), 5.92, 1e-12)
near("(22,-30) on the shore ramp: 2.76 - 20/27",
     RMODEL.final(22.0, -30.0), 2.76 - 20.0 / 27.0, 1e-12)
near("...which is 2.0192592592…", RMODEL.final(22.0, -30.0),
     2.0192592592592593, 1e-12)
near("(20,-30) ON the outline is not inside it, so nothing is carved",
     RMODEL.final(20.0, -30.0), 2.0)
near("the DEPTH is the KIND's default 1.0, not the module's 2.0 — the area "
     "repeats nothing", 5.0 - RMODEL.final(50.0, -30.0), 1.0, 1e-12)

print("\n[8e] an AREA still overrides the kind, and an unflagged kind carves "
      "nothing")
_over = dict(RIVER_AUTO, id="ta_river_deep",
             meta={"flow_dir_deg": 270, "water_depth_m": 4.0})
_omodel = hf.build_model([SLOPE], [], [_over], CATALOG_R)
near("an area depth of 4.0 beats the kind's 1.0: the bed is 5.0 - 4.0",
     _omodel.final(50.0, -30.0), 5.0 - 4.0, 1e-12)
near("the CREEK's kind carries both numbers but not the flag — NATURAL stands",
     RMODEL.final(50.0, -110.0), natural(50.0))
check("...and it never became a water stamp at all",
      "ta_creek" in RMODEL.water_profile_by_area, False)
check("flagging the very same kind makes it carve — the world-shaped case",
      round(hf.build_model([SLOPE], [], [CREEK],
                           {**CATALOG_R,
                            "creek": {**CATALOG_R["creek"],
                                      "meta": {**CATALOG_R["creek"]["meta"],
                                               "water": True}}}
                           ).final(50.0, -110.0), 6),
      round(0.08 * 50.0 + 1.0 - 1.0, 6))

print("\n[8f] the AUTHORED ends win outright (RIVER_SET)")
# level_at(x) = 9.5 - 9 * (80 - x)/60 = 0.15 x - 2.5, so 0.5 at x = 20 and
# 9.5 at x = 80; the mid level is 5.0. The bed past the ramp is that minus 1.0,
# and the MIN keeps the landscape wherever it is already lower — which happens
# at 0.15x - 3.5 >= 0.1x, i.e. from x = 70 upstream.
SET = RMODEL.water_profile_by_area["ta_river_set"]
near("level_up is the authored 9.5", SET.level_up, 9.5)
near("level_down is the authored 0.5", SET.level_down, 0.5)
for _x in (23.5, 50.0, 69.0):
    near(f"({_x},-70) bed = 0.15x - 3.5 = {0.15 * _x - 3.5}",
         RMODEL.final(_x, -70.0), 0.15 * _x - 3.5, 1e-12)
near("(76.5,-70) upstream the LANDSCAPE is already lower — the MIN keeps 7.65",
     RMODEL.final(76.5, -70.0), 7.65, 1e-12)

print("\n[8g] INVARIANT 2, restated LOCALLY: h <= level_at(x,z) - eps")
# eps = min(depth, 0.25) = 0.25. Deep means d_in > shore_ramp = 3 m, i.e.
# x in (23, 77) and z in (-77, -63) — on the 0.5 m lattice that is x = 23.5 …
# 76.5 (108 columns) x z = -76.5 … -63.5 (27 rows) = 2916 samples.
# The gap level_at - h is exactly the DEPTH, 1.0 m, wherever the carve wrote
# (x < 70, bed = level_at - 1.0), and 0.05x - 2.5 where the landscape is
# already lower (x >= 70) — which at x = 70 is 1.0 as well and grows upstream.
# So the WORST gap over the whole deep zone is exactly 1.0 m, hand-derived and
# not sampled, and it clears eps = 0.25 with 0.75 m to spare.
EPS_R = min(1.0, 0.25)
deep_n = 0
worst = 1e9
_i = 0
while _i < 108:
    px = 23.5 + _i * 0.5
    _j = 0
    while _j < 27:
        pz = -76.5 + _j * 0.5
        deep_n += 1
        worst = min(worst, hf.water_level_at(SET, px, pz)
                    - RMODEL.final(px, pz))
        _j += 1
    _i += 1
check("deep probes taken", deep_n, 2916)
near("the WORST local gap is exactly the depth, 1.0 m", worst, 1.0, 1e-9)
check_true(f"...so every one of them clears eps = {EPS_R}", worst >= EPS_R)

print("\n[8h] RED: the CONSTANT-level carve breaks what the sloped one keeps")
# THE MUTANT: the same river, the same depth, but ONE mirror at the mid level
# 5.0 — which is what every round before W1 could express. Its bed past the
# ramp is the constant 4.0, and the MIN keeps the landscape below x = 40.
CONST = {"id": "ta_river_set", "kind": "river", "z_order": 0,
         "polygon": RIVER_SET["polygon"], "meta": {"water_level": 5.0}}
CMODEL = hf.build_model([SLOPE], [], [CONST], CATALOG_R)
near("the mutant's mirror really is the constant 5.0",
     CMODEL.water_profile_by_area["ta_river_set"].level_up, 5.0)
near("...at BOTH ends", CMODEL.water_profile_by_area["ta_river_set"].level_down,
     5.0)
# (a) DOWNSTREAM the mutant leaves the ground ABOVE its own water line.
near("at (23.5,-70) the mutant's ground is the landscape 2.35",
     CMODEL.final(23.5, -70.0), 2.35, 1e-12)
near("...while the local mirror there is 0.15·23.5 - 2.5 = 1.025",
     hf.water_level_at(SET, 23.5, -70.0), 1.025, 1e-12)
check_true("...so the mutant VIOLATES h <= level_at - 0.25 by 1.575 m",
           CMODEL.final(23.5, -70.0) > 1.025 - EPS_R)
near("...and the sloped carve at the same point answers 0.025",
     RMODEL.final(23.5, -70.0), 0.025, 1e-12)
check_true("...which clears it", RMODEL.final(23.5, -70.0) <= 1.025 - EPS_R)
# (b) UPSTREAM the sloped bed stands ABOVE the constant plane — which is
# exactly what a flat mirror at 5.0 would have to cut through.
near("upstream the sloped ground is 7.65", RMODEL.final(76.5, -70.0), 7.65,
     1e-12)
near("...i.e. 2.65 m ABOVE the constant plane at 5.0",
     RMODEL.final(76.5, -70.0) - 5.0, 2.65, 1e-12)
near("...and the mutant had to gouge it down to 4.0 to hide that",
     CMODEL.final(76.5, -70.0), 4.0, 1e-12)

print("\n[8i] a river SETTLES its two ends, a lake settles its one level")
terrain_types.save_world_type(CATALOG_R["river"])
_before = terrain_store.save_area(dict(RIVER_AUTO))
check("a flowing area is frozen at BOTH ends, never into one water_level",
      sorted(k for k in _before["meta"] if k.startswith("water_level")),
      ["water_level_down", "water_level_up"])
near("...at the derived 7.4", _before["meta"]["water_level_up"], 7.4)
near("...and 2.6", _before["meta"]["water_level_down"], 2.6)
_half = terrain_store.save_area(dict(RIVER_AUTO, id="ta_river_half",
                                     meta={"flow_dir_deg": 270,
                                           "water_level_up": 3.0}))
check("an author who set ONE end keeps it and only the other is derived",
      [_half["meta"]["water_level_up"], _half["meta"]["water_level_down"]],
      [3.0, 2.6])

print("\n[8j] the profile in the PAYLOAD — the nine numbers, additively")
hf.invalidate_cache()
_areas = {a["id"]: a for a in
          hf.with_effective_water_level(terrain_store.list_areas())}
check("the river ships its whole tilted mirror — the nine numbers unchanged "
      "by W4a, plus the two knots they are the plane through",
      _areas["ta_river_auto"]["meta"]["water_profile"],
      {"level_up": 7.4, "level_down": 2.6, "flow_dir_deg": 270.0,
       "axis_x": 50.0, "axis_z": -30.0, "dir_x": -1.0, "dir_z": 0.0,
       "s_min": -30.0, "s_max": 30.0,
       "axis": [[80.0, -30.0, -30.0, 7.4], [20.0, -30.0, 30.0, 2.6]]})
near("...and the flat-consumer number beside it is the MID level",
     _areas["ta_river_auto"]["meta"]["water_level_effective"], 5.0)
near("...and the effective DEPTH is the KIND's 1.0, resolved — the area never "
     "repeated it, and no client has to look the kind up to draw the shore",
     _areas["ta_river_auto"]["meta"]["water_depth_effective"], 1.0)
# …and where the AREA overrides, the reported depth is the AREA's — the same
# `water_meta` resolution the carve of [8e] used, read off the model that
# `with_effective_water_level` ships from.
near("an area that DOES override reports its own 4.0, not the kind's 1.0",
     _omodel.water_depth_by_area["ta_river_deep"], 4.0)


# ── [8k] THE FLOW AXIS IS THE DRAWN LINE (W4a) ──────────────────────────
print("\n[8k] a river follows its own line — the axis is a POLYLINE")
# THE LANDSCAPE, on its own model again. ONE height area, a 400 x 400 square
# with a 400 m falloff, so inside it
#
#   BOWL(x, z) = 40 · min(1, d/400) = d/10,
#   d = min(x, 400-x, z-200, 600-z)      (distance to the OUTLINE)
#
# and in the band x in [140,300], z in [250,315] the smallest of the four is
# ALWAYS z-200 (it is at most 115 there, the others at least 140), so
#
#   BOWL = (z - 200)/10       — a plane that falls toward -z, 0.1 m per metre.
#
# THE RIVER, drawn with the LINE tool: three clicked points, width 6 m, and
# the kind's shore ramp 3 m. Its meta carries `flow_along: "forward"`, so the
# axis is that line in drawing order — the polygon below is only the carve's
# MASK and says nothing about the flow. That separation IS W4a.
#
#   A = (150, 300)   B = (249, 280)   C = (201, 260)
#
# a hairpin: 99 m east and 20 m down-slope, then 48 m back west and 20 m down.
#   |AB| = sqrt(99² + 20²) = sqrt(10201) = 101   -> s(B) = 101
#   |BC| = sqrt(48² + 20²) = sqrt(2704)  = 52    -> s(C) = 153
#
# THE KNOT LEVELS are the median of BOWL over a CROSS SECTION at each knot:
# 9 probes perpendicular to the local tangent, spread over width/2 + ramp = 6 m
# to either side. BOWL is LINEAR there and the probes are symmetric about the
# knot, so the median is the middle probe — the knot's own height:
#
#   level(A) = (300-200)/10 = 10      level(B) = 8      level(C) = 6
#
# (every probe stays inside the band above: the widest offset moves a knot by
# 6 m, and x never leaves [144, 253].)
#
# Monotone downstream (10 > 8 > 6), so the running minimum changes nothing
# here — [8k-mono] below is the case where it does.
BOWL = {"id": "ha_bowl", "polygon": [[0, 200], [400, 200], [400, 600],
                                     [0, 600]],
        "height_m": 40.0, "falloff_m": 400.0, "meta": {}}
U_POINTS = [[150, 300], [249, 280], [201, 260]]
U_MASK = [[140, 250], [300, 250], [300, 315], [140, 315]]


def u_river(area_id, meta):
    """The hairpin above with one meta — the polygon is the carve mask only."""
    return {"id": area_id, "kind": "river", "z_order": 0, "polygon": U_MASK,
            "meta": dict(meta, stroke={"points": U_POINTS, "width_m": 6.0})}


U_RIVER = u_river("ta_u", {"flow_along": "forward"})
UMODEL = hf.build_model([BOWL], [], [U_RIVER], CATALOG_R)
U = UMODEL.water_profile_by_area["ta_u"]

check("the axis has one knot per drawn point, (x, z, s, level) each",
      [[round(v, 6) for v in knot] for knot in U.axis],
      [[150.0, 300.0, 0.0, 10.0], [249.0, 280.0, 101.0, 8.0],
       [201.0, 260.0, 153.0, 6.0]])
near("AT the middle knot the mirror is that knot's level, 8.0",
     hf.water_level_at(U, 249.0, 280.0), 8.0, 1e-12)
near("halfway along the first leg it is the mean of its two knots, 9.0",
     hf.water_level_at(U, 199.5, 290.0), 9.0, 1e-12)
near("...and halfway along the second, 7.0",
     hf.water_level_at(U, 225.0, 270.0), 7.0, 1e-12)
near("upstream of the first knot the polyline CLAMPS to 10.0",
     hf.water_level_at(U, 150.0, 400.0), 10.0, 1e-12)
# THE RED COUNTER-PROBE: the same river as ONE tilted plane — which is exactly
# what the nine numbers beside the axis say, and all W1 could express. Its axis
# is the CHORD A -> C = (51, -40), |chord|² = 51² + 40² = 4201. The middle knot
# projects onto it at
#     u = ((249-150)·51 + (280-300)·(-40)) / 4201 = (5049 + 800)/4201 = 1.392…
# i.e. PAST the downstream end, where the clamp answers level_down = 6.0. The
# bend of a hairpin has no place on its own chord — that is the whole finding.
CHORD = math.sqrt(4201.0)
STRAIGHT = hf.WaterProfile(level_up=10.0, level_down=6.0,
                           flow_dir_deg=180.0 - math.degrees(
                               math.atan(51.0 / 40.0)),
                           axis_x=150.0, axis_z=300.0,
                           dir_x=51.0 / CHORD, dir_z=-40.0 / CHORD,
                           s_min=0.0, s_max=CHORD,
                           axis=((150.0, 300.0, 0.0, 10.0),
                                 (201.0, 260.0, CHORD, 6.0)))
near("RED: the STRAIGHT W1 axis answers 6.0 at that same point — the bend "
     "projects past its own downstream end", hf.water_level_at(STRAIGHT,
                                                               249.0, 280.0),
     6.0, 1e-12)
near("the carve uses the LOCAL level: 8.0 - the kind's depth 1.0",
     UMODEL.final(249.0, 280.0), 7.0, 1e-12)

print("\n[8k-nine] the nine numbers stay readable: the plane through the ends")
near("level_up is the FIRST knot", U.level_up, 10.0, 1e-12)
near("level_down is the LAST", U.level_down, 6.0, 1e-12)
near("the axis point is the first knot, x", U.axis_x, 150.0, 1e-12)
near("...and z", U.axis_z, 300.0, 1e-12)
near("the bearing is the CHORD's: 180° - atan(51/40)", U.flow_dir_deg,
     180.0 - math.degrees(math.atan(51.0 / 40.0)), 1e-3)
near("...and the span is the chord's own length sqrt(4201)", U.s_max, CHORD,
     1e-6)
near("the flat-consumer level stays the mean of the two ends",
     (U.level_up + U.level_down) * 0.5, 8.0, 1e-12)

print("\n[8k-mono] water never runs uphill — the running minimum")
# The same hairpin with the middle knot lifted to z = 310, i.e. BOWL 11.0:
# raw knots 10 / 11 / 6, and the running minimum downstream gives 10 / 10 / 6.
UP_HILL = u_river("ta_u_up", {"flow_along": "forward"})
UP_HILL["meta"]["stroke"]["points"] = [[150, 300], [249, 310], [201, 260]]
_up = hf.build_model([BOWL], [], [UP_HILL], CATALOG_R
                     ).water_profile_by_area["ta_u_up"]
check("a knot that measures HIGHER than the one above it is pulled down",
      [round(knot[3], 6) for knot in _up.axis], [10.0, 10.0, 6.0])
_rev = hf.build_model([BOWL], [],
                      [u_river("ta_u_rev", {"flow_along": "reverse"})],
                      CATALOG_R).water_profile_by_area["ta_u_rev"]
check("flowing the SAME line backwards runs it uphill — 6/8/10 flattens to "
      "the source level", [round(knot[3], 6) for knot in _rev.axis],
      [6.0, 6.0, 6.0])
check("...and its knots are the drawn points in reverse order",
      [[knot[0], knot[1]] for knot in _rev.axis],
      [[201.0, 260.0], [249.0, 280.0], [150.0, 300.0]])

print("\n[8k-authored] authored ends win, the inner shape is remapped")
# Derived 10 / 8 / 6 with authored ends 12 / 4: the span 10-6 = 4 becomes
# 12-4 = 8, so every knot is stretched by (12-4)/(10-6) = 2 about the LAST one:
#     12 = 4 + (10-6)·2      8 = 4 + (8-6)·2      4 = 4 + (6-6)·2
_ends = hf.build_model([BOWL], [],
                       [u_river("ta_u_ends", {"flow_along": "forward",
                                              "water_level_up": 12.0,
                                              "water_level_down": 4.0})],
                       CATALOG_R).water_profile_by_area["ta_u_ends"]
check("12 / 4 authored over a derived 10 / 8 / 6 gives 12 / 8 / 4",
      [round(knot[3], 6) for knot in _ends.axis], [12.0, 8.0, 4.0])
_still = hf.build_model([BOWL], [],
                        [u_river("ta_u_flat", {"flow_along": "forward",
                                               "water_level": 9.5})],
                        CATALOG_R).water_profile_by_area["ta_u_flat"]
check("a plain water_level makes every knot that number — drawn, but standing",
      [round(knot[3], 6) for knot in _still.axis], [9.5, 9.5, 9.5])

print("\n[8k-fallback] no flow_along = polygon water, unchanged")
_bearing = hf.build_model([BOWL], [],
                          [u_river("ta_u_deg", {"flow_dir_deg": 270})],
                          CATALOG_R).water_profile_by_area["ta_u_deg"]
check("a drawn area that is not flowed along its line keeps the W1 axis: two "
      "knots", len(_bearing.axis), 2)
near("...from the authored bearing, not from the line", _bearing.flow_dir_deg,
     270.0)
_both = hf.build_model([BOWL], [],
                       [u_river("ta_u_both", {"flow_along": "forward",
                                              "flow_dir_deg": 270})],
                       CATALOG_R).water_profile_by_area["ta_u_both"]
check("with BOTH authored the LINE wins and flow_dir_deg is ignored",
      [len(_both.axis), round(_both.flow_dir_deg, 3)],
      [3, round(180.0 - math.degrees(math.atan(51.0 / 40.0)), 3)])
check("the sanitizer keeps only the two words", [
    terrain_store.sanitize_area({"kind": "river", "polygon": U_MASK,
                                 "meta": {"flow_along": raw}})["meta"]
    .get("flow_along")
    for raw in ("forward", "reverse", "FORWARD", "sideways", "", None, 3)],
    ["forward", "reverse", "forward", None, None, None, None])
check("'flowing' is ONE predicate: a drawn line flowed along it needs no "
      "bearing at all",
      [hf.is_flowing(hf.water_meta(u_river("x", m)))
       for m in ({"flow_along": "forward"}, {"flow_along": "reverse"},
                 {"flow_dir_deg": 270}, {}, {"flow_along": "sideways"})],
      [True, True, True, False, False])
# The SETTLE path asks that predicate too (``models.terrain.settle_water_level``)
# — a line-drawn river must freeze its two ENDS, because freezing it into one
# ``water_level`` would flatten the very fall the author drew. The numbers come
# from the STORED landscape here, not from BOWL, so only the KEYS are asserted.
_settled = terrain_store.settle_water_level(terrain_store.sanitize_area(
    u_river("ta_u_settle", {"flow_along": "forward"})))
check("a river drawn as a LINE settles its two ENDS, never one water_level",
      sorted(k for k in _settled["meta"] if k.startswith("water_level")),
      ["water_level_down", "water_level_up"])


# ── [9] THE ZONE-WATER STAGE IS GONE — asserted BY NAME (W1) ────────────
print("\n[9] the fifth bake stage and everything that fed it is deleted")
# NO FALLBACK READERS, so the proof is that the NAMES are gone: a reader that
# still existed would keep a room's water alive silently.
import inspect  # noqa: E402
from app.core import terrain_layers as TL2  # noqa: E402
from app.core import world_ops as WO  # noqa: E402

for _name in ("ZoneWaterInput", "ZoneWaterStamp"):
    check(f"red: heightfield.{_name} is gone", hasattr(hf, _name), False)
for _name in ("_build_zone_water", "_carve_zone", "zone_water_level_by_room",
              "zone_water"):
    check(f"red: HeightModel.{_name} is gone", hasattr(MODEL, _name), False)
check("red: build_model takes no zone_waters any more",
      "zone_waters" in inspect.signature(hf.build_model).parameters, False)
check("red: and neither does rasterize_tile",
      "zone_waters" in inspect.signature(hf.rasterize_tile).parameters, False)
for _name in ("placed_zone_waters", "zone_water_basis"):
    check(f"red: models.heightfield.{_name} is gone", hasattr(store, _name),
          False)
check("red: the height signature basis names no zone water",
      "zone_water" in store.height_sig.__doc__.lower()
      or "zone_water" in inspect.getsource(store.height_sig), False)
for _name in ("waters_payload", "is_water_floor", "floor_water_meta",
              "surface_classes"):
    check(f"red: terrain_layers.{_name} is gone", hasattr(TL2, _name), False)
check("red: a Floor carries no water fields at all",
      [f for f in TL2.Floor._fields if "water" in f or "shore" in f], [])
check("red: the terrain-layers index ships no `waters` list",
      "waters" in inspect.getsource(TL2.index_payload), False)
_lay = WO._sanitize_room_layout({"x": 0, "y": 0, "w": 4, "d": 4,
                            "water_level": 1.0, "water_depth_m": 2.0,
                            "shore_ramp_m": 3.0,
                            "surfaces": {"floor": "water", "wall": "brick"}})
check("red: a room layout keeps NONE of the three water fields",
      [k for k in _lay if "water" in k or "shore" in k], [])
check("red: ...and a WATER floor kind is stripped at sanitize time",
      _lay.get("surfaces"), {"wall": "brick"})
_dry = WO._sanitize_room_layout({"x": 0, "y": 0, "w": 4, "d": 4,
                            "surfaces": {"floor": "sand"}})
check("...while a dry floor kind is untouched", _dry.get("surfaces"),
      {"floor": "sand"})


print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
for name in FAILURES:
    print(f"  FAILED: {name}")
sys.exit(1 if FAILURES else 0)
