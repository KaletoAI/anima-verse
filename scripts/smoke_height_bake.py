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
(``meta.flow_along``), so the axis is a POLYLINE along the drawn line — and the
two laws above are its one-knot and its two-knot case, read by the same
function.

Section [8l] is W5b, and it is a BUG FIX with a number: the knots used to sit
only where the author CLICKED, so a river drawn over a cliff with two clicks got
one straight ramp between them — the mirror hung in the air past the edge and
carved a canyon into the plateau before it, and nothing downstream could see the
cliff because no knot was near it. The drawn line is now SAMPLED by arc length
every ``core.heightfield.WATER_AXIS_STEP_M`` = 2 m (the tile step, and the run
at which the two waterfall thresholds meet) BEFORE the cross-section medians are
taken, and the resulting level polyline is SIMPLIFIED again — Douglas-Peucker on
``(s, level)`` with a 5 cm tolerance, per drawn leg, clicked points fixed — so
the payload carries the knots the mirror actually bends at and no others. The
sampled knots lie ON the drawn legs, so dropping one cannot move the axis; only
the clicks are bends, and they are never dropped.

Section [9] is the deletion proof of the fifth stage.

Section [12] is THE WATER RASTER (Wasser v2, K-A E1). The tile grew a SECOND
field beside ``heights``: per lattice point the local mirror and the flow
vector of the topmost water covering it, written two lattice steps PAST every
outline. ``h_final`` does not move by a millimetre — the mirror was always an
input of the carve and is now shipped as well — so every number above this
section is unchanged. The dilation width is a DIAGONAL argument (a corner of a
wet sample's cell lies at most sqrt(2) steps outside the outline, so one step
is not enough and two are), and [12d] is the measurement the research asked
for: on the inside of the hairpin the 2 m raster is off by 3.43 m, the same
sweep at 1 m and 0.5 m is off by just as much, and away from the medial axis
the 2 m raster is already within 1.8 cm — i.e. the error is a STEP in
``water_level_at`` itself and a finer water raster would buy nothing.

Sections [10] and [11] are THE SHORE GUARDS, RETIRED (v8, Wasser v2 K-A E6).
Between v4 and v7 two stamps shaped the ground around every water — a BANK
CLAMP that held the band outside the outline at ``water_level_at(nearest
outline point) + WATER_BANK_LIP_M`` (0.10 m, the minimum fading to nothing at
the band's outer edge) and a RELIEF FADE that took the micro-relief to zero
over a collar of ``max(shore_ramp_m, 16 m)``. Both were written against ONE
symptom of the mesh era: the mirror was a separate, transparent SURFACE, so
land above it at the rim was a hole in the water and land below it was water
standing in the air.

E3 answered both in the renderer: the terrain VERTEX is lifted to
``max(h, w_level)`` wherever the water raster has a value, and E5 deleted the
mirror mesh. So the two sections are now DELETION PROOFS plus the rewritten
§ G4 rim half:

* [10] the names are gone (no fallback reader), the band outside the outline
  is the authored step again, ``h_final`` IS ``natural -> carve -> plateaus``
  over 10 611 probes, and the raster's decimation is a SUBSET at every level a
  renderer draws (K-A E2), so "a water texel's surface is the mirror" holds at
  every one of them. [10g] states the price of the removal as a number: a bank
  under the mirror is drawn as water for as far as the raster reaches, i.e. up
  to ``WATER_RASTER_DILATION_M`` = 4 m outside the authored outline.
* [11] the relief reaches the waterline again (the ground IS the hand noise at
  d = 0 m), the derived mirror is the median of a WOBBLING rim once more — the
  1.344 m spread and the 0.466 m rim point that the fade was written for, back
  and now legal, because a rim point above its own mirror is drawn as the rock
  it is and nothing is drawn UNDER the mirror where the raster says water.

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
# (160,140) is on the EAST edge, and by the same ray-cast rule that is OUTSIDE
# the ring — so it is not a carve probe at all, and since v8 (K-A E6) nothing
# in the bake touches it: its natural height is the authored 4.0, two metres
# UNDER the mirror 6.0. That is the shape the retired bank clamp used to lift
# to level + lip; the renderer lifts it to the mirror instead (section [10e]),
# so the bake leaves the landscape as authored.
near("…while (160,140) on the east rim keeps its NATURAL 4.0, two metres "
     "under the mirror", MODEL.final(160.0, 140.0), 4.0)
check_not("…and is NOT the 6.1 the bank clamp wrote there",
          round(MODEL.final(160.0, 140.0), 9), 6.1)
near("…because the LIFT covers it: max(h, w) at that point is the mirror",
     max(MODEL.final(160.0, 140.0), MODEL.water_at(160.0, 140.0)[0]), 6.0,
     1e-12)

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

check("the axis ships the knots the line was DRAWN with — a leg whose level "
      "falls evenly needs no knot in the middle of it",
      [[round(v, 6) for v in knot] for knot in U.axis],
      [[150.0, 300.0, 0.0, 10.0], [249.0, 280.0, 101.0, 8.0],
       [201.0, 260.0, 153.0, 6.0]])
# …and it is not that the line was never SAMPLED (W5b): the levels were
# measured every 2 m and every one of them sat on the straight line between its
# neighbours, so the simplification put the three drawn points back. 101 m of
# leg 1 is ceil(101/2) = 51 equal parts of 1.9803… m, 52 m of leg 2 is 26 parts
# of exactly 2 m, and the knots are one more than the parts: 1 + 51 + 26 = 78.
_dense, _clicks = hf._stroke_knots(hf.water_meta(U_RIVER, (1.0, 3.0)))
check("the line IS sampled — 78 knots before the level simplifies them away",
      len(_dense), 78)
check("...and the clicked points are among them, at these indices", _clicks,
      (0, 51, 77))
near("...leg 1 is sampled every 101/51 m", _dense[1][2], 101.0 / 51.0, 1e-12)
near("...and leg 2 every 52/26 = 2 m exactly", _dense[52][2] - _dense[51][2],
     2.0, 1e-12)
check("no knot of the sampled line is further from the last than the step",
      max(round(_dense[i][2] - _dense[i - 1][2], 9)
          for i in range(1, len(_dense))) <= hf.WATER_AXIS_STEP_M, True)
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
# The same hairpin with the middle CLICK lifted to z = 310, i.e. BOWL 11.0:
# the clicked levels are 10 / 11 / 6 and the running minimum gives 10 / 10 / 6.
# ON THE DENSIFIED LINE (W5b) that is a sharper statement than it used to be,
# because the minimum is now clamped knot by knot and the simplification says
# where it stops clamping:
#
#   LEG 1  A(150,300) -> B(249,310):  |AB| = sqrt(99² + 10²) = sqrt(9901)
#          = 99.50376877…  The raw level RISES 10 -> 11 along it, so every
#          sampled knot is pinned to the source level 10 — the whole leg is
#          flat, and a flat run between two kept knots deviates by nothing and
#          is dropped again.
#
#   LEG 2  B(249,310) -> C(201,260):  |BC| = sqrt(48² + 50²) = sqrt(4804)
#          = 69.31089380…, subdivided into ceil(69.31/2) = 35 equal parts of
#          1.98031… m. The SEVENTH of them is exactly one fifth of the leg
#          (7/35), which is exactly where the line comes back down through
#          z = 300 — the raw level is 10 again there and the clamp lets go:
#              x = 249 - 48/5 = 239.4      z = 310 - 50/5 = 300
#              s = sqrt(9901) + sqrt(4804)/5 = 113.36594753…
#          Before it the profile is flat at 10, after it the raw level falls
#          linearly to 6 (BOWL is a plane and z is linear in s), so BOTH sides
#          are straight and only this ONE corner survives the simplification.
#
# FOUR KNOTS, then, and the third is the corner the old rule could not see at
# all: with knots only at the clicks the mirror fell from 10 to 6 in ONE ramp
# across the whole of leg 2, so at that very corner it read 10 - 4/5 = 9.2 —
# 0.8 m BELOW the ground it was supposed to lie on, which is 0.8 m of bank the
# carve would have dug away.
UP_HILL = u_river("ta_u_up", {"flow_along": "forward"})
UP_HILL["meta"]["stroke"]["points"] = [[150, 300], [249, 310], [201, 260]]
_up = hf.build_model([BOWL], [], [UP_HILL], CATALOG_R
                     ).water_profile_by_area["ta_u_up"]
_l1, _l2 = math.sqrt(9901.0), math.sqrt(4804.0)
check("a knot that measures HIGHER than the one above it is pulled down",
      [round(knot[3], 6) for knot in _up.axis], [10.0, 10.0, 10.0, 6.0])
check("...and the level stays pinned until the LINE comes back down to it — "
      "one corner knot, not one long ramp",
      [[round(knot[0], 6), round(knot[1], 6)] for knot in _up.axis],
      [[150.0, 300.0], [249.0, 310.0], [239.4, 300.0], [201.0, 260.0]])
near("the corner sits at sqrt(9901) + sqrt(4804)/5 along the line",
     _up.axis[2][2], _l1 + _l2 / 5.0, 1e-9)
near("...i.e. the mirror is still 10.0 there", hf.water_level_at(_up, 239.4,
                                                                300.0),
     10.0, 1e-12)
near("RED: the ONE-RAMP reading of the same two clicks is 9.2 there — 0.8 m "
     "UNDER the ground the water lies on",
     10.0 + (6.0 - 10.0) * ((_l2 / 5.0) / _l2), 9.2, 1e-12)
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


# ── [8l] THE CLIFF BETWEEN TWO CLICKS (W5b) ─────────────────────────────
print("\n[8l] a river over a 3 m step — the knots are where the GROUND bends")
# THE LANDSCAPE is one height area with NO falloff, which is the module's own
# spelling of a hard edge (``_area_value``: ``falloff <= 0 -> height``):
#
#     PLATEAU  (-100,-100)-(41,100), height_m 3.0, falloff_m 0.0
#     STEP(x)  = 3.0  for x < 41   (inside the outline)
#              = 0.0  for x > 41   (outside it)
#
# THE RIVER is drawn with TWO clicks straight across that edge, (0,0) -> (100,0),
# 6 m wide, kind "river" (depth 1.0, shore ramp 3.0). Its carve mask is the
# ribbon (0,-3)-(100,3). Two clicks is the case the author actually draws and
# the case the old rule was blindest in: the only two knots WERE the ends.
#
# THE SAMPLED LINE: one leg of 100 m at a 2 m step is ceil(100/2) = 50 equal
# parts, so knots at s = 0, 2, 4, …, 100 and s IS x here. Each level is the
# median of 9 probes ACROSS the river (z from -6 to +6 at that x), and STEP does
# not depend on z at all, so the median is STEP(x):
#
#     x <= 40  ->  3.0          x >= 42  ->  0.0
#
# (no knot lands on 41, the edge itself). Monotone already, nothing authored.
#
# THE SIMPLIFICATION then keeps first, last and every knot whose level is more
# than 5 cm off the line between the knots kept around it:
#     the chord (0,3) -> (100,0) is 3 - 0.03·s; the worst deviation on it is at
#     s = 40 (3.0 against 1.8, i.e. 1.2 m) -> KEEP 40
#     then (40,3) -> (100,0) is 3 - 0.05·(s-40); the worst is at s = 42
#     (0.0 against 2.9) -> KEEP 42
#     what is left is flat on both sides -> nothing else survives
#
#     axis = [(0,0,0,3), (40,0,40,3), (42,0,42,0), (100,0,100,0)]
#
# FOUR KNOTS, and the drop of the whole 3 m sits in ONE 2 m segment.
STEP_AREA = {"id": "ha_step", "polygon": [[-100, -100], [41, -100],
                                          [41, 100], [-100, 100]],
             "height_m": 3.0, "falloff_m": 0.0, "meta": {}}
CLIFF_RIVER = {"id": "ta_cliff", "kind": "river", "z_order": 0,
               "polygon": [[0, -3], [100, -3], [100, 3], [0, 3]],
               "meta": {"flow_along": "forward",
                        "stroke": {"points": [[0, 0], [100, 0]],
                                   "width_m": 6.0}}}
CMODEL_W5 = hf.build_model([STEP_AREA], [], [CLIFF_RIVER], CATALOG_R)
CLIFF = CMODEL_W5.water_profile_by_area["ta_cliff"]
check("the plateau really is a hard step: 3.0 up to the edge, 0.0 past it",
      [CMODEL_W5.natural(x, 0.0) for x in (0.0, 20.0, 40.0, 42.0, 100.0)],
      [3.0, 3.0, 3.0, 0.0, 0.0])
check("the axis has a knot on each side of the edge and nowhere else",
      [[round(v, 6) for v in knot] for knot in CLIFF.axis],
      [[0.0, 0.0, 0.0, 3.0], [40.0, 0.0, 40.0, 3.0],
       [42.0, 0.0, 42.0, 0.0], [100.0, 0.0, 100.0, 0.0]])
near("the mirror hugs the plateau right up to the lip", CLIFF.axis[1][3], 3.0)
near("...and has arrived at the low ground 2 m later", CLIFF.axis[2][3], 0.0)
check("the whole 3 m drop is ONE segment of the axis, 2 m long",
      [round(CLIFF.axis[1][3] - CLIFF.axis[2][3], 6),
       round(CLIFF.axis[2][2] - CLIFF.axis[1][2], 6)], [3.0, 2.0])
# THE FALL, read the way `@anima/scene-render.waterfallsFrom` reads it — both
# thresholds, both strict, on every consecutive pair. Only the middle segment
# passes, so the client twin draws exactly ONE curtain (its own smoke pins the
# same axis: `client3d/scripts/smoke_waterfall.mjs`).
_segments = [(round(CLIFF.axis[i - 1][3] - CLIFF.axis[i][3], 6),
              round(CLIFF.axis[i][2] - CLIFF.axis[i - 1][2], 6))
             for i in range(1, len(CLIFF.axis))]
check("drop and run per segment", _segments, [(0.0, 40.0), (3.0, 2.0),
                                              (0.0, 58.0)])
check("exactly one of them is a fall: drop > 1.0 AND drop/run > 0.5",
      [drop > 1.0 and drop / run > 0.5 for drop, run in _segments],
      [False, True, False])
near("...and the water leaves at 3.0", CLIFF.axis[1][3], 3.0)
near("...and arrives at 0.0", CLIFF.axis[2][3], 0.0)

print("\n[8l-red] the two-knot ramp: a canyon before the lip, air past it")
# THE MUTANT is the axis the clicked-points-only rule produced for this very
# river — two knots, 3.0 at x = 0 and 0.0 at x = 100, i.e. level_at = 3 - 0.03x.
# It is built here by hand from the module's own type, exactly like the straight
# W1 counter-probe of [8k].
RAMP = hf.WaterProfile(level_up=3.0, level_down=0.0, flow_dir_deg=90.0,
                       axis_x=0.0, axis_z=0.0, dir_x=1.0, dir_z=0.0,
                       s_min=0.0, s_max=100.0,
                       axis=((0.0, 0.0, 0.0, 3.0),
                             (100.0, 0.0, 100.0, 0.0)))
near("RED: 20 m before the edge the ramp reads 2.4", hf.water_level_at(
    RAMP, 20.0, 0.0), 2.4, 1e-12)
check_true("...which is 0.6 m UNDER the plateau it is running over",
           CMODEL_W5.natural(20.0, 0.0) - hf.water_level_at(RAMP, 20.0, 0.0)
           > 0.5)
near("RED: 19 m past the edge it reads 1.2", hf.water_level_at(RAMP, 60.0, 0.0),
     1.2, 1e-12)
check_true("...over a ground of 0.0 — the mirror hanging in the air, which is "
           "the reported symptom",
           hf.water_level_at(RAMP, 60.0, 0.0) - CMODEL_W5.natural(60.0, 0.0)
           > 1.0)
near("the sampled axis answers the plateau's own 3.0 there instead",
     hf.water_level_at(CLIFF, 20.0, 0.0), 3.0, 1e-12)
near("...and the low ground's own 0.0 past the edge",
     hf.water_level_at(CLIFF, 60.0, 0.0), 0.0, 1e-12)
near("...and 1.5 at the lip itself, halfway between its two knots",
     hf.water_level_at(CLIFF, 41.0, 0.0), 1.5, 1e-12)
# THE CARVE, which is what the author sees as a canyon. 20 m in, d_in is 3 m
# (the ribbon is 6 m wide), i.e. exactly the shore ramp, so the full depth 1.0
# applies: the bed is level - 1.0 either way, but the LEVEL differs.
near("the carve now cuts a 1.0 m bed into the plateau: 3.0 - 1.0",
     CMODEL_W5.final(20.0, 0.0), 2.0, 1e-12)
near("RED: the ramp cut 1.4 there — 1.6 m of canyon into a 3 m plateau",
     hf.water_level_at(RAMP, 20.0, 0.0) - 1.0, 1.4, 1e-12)
near("...and the bed past the edge is the low ground's own, 0.0 - 1.0",
     CMODEL_W5.final(60.0, 0.0), -1.0, 1e-12)
check_true("INVARIANT 2 still holds at both probes: h <= level_at - 0.25",
           all(CMODEL_W5.final(px, 0.0)
               <= hf.water_level_at(CLIFF, px, 0.0) - 0.25
               for px in (20.0, 60.0)))

print("\n[8l-lip] ten metres either side of the lip — the reported symptom")
# THE TWO PROBES THE REPORT NAMES, one on each side of the edge at x = 41:
#
#   UPSTREAM  x = 31  ground 3.0 (plateau)
#       sampled axis : level 3.0  — the mirror lies ON the plateau it crosses
#       two-knot ramp: level = 3 - 0.03·31 = 2.07, i.e. 0.93 m BELOW the banks
#                      it runs between. That is "the water is almost gone": the
#                      mirror has sunk into a slot 20 m before the fall, with a
#                      0.93 m wall of untouched plateau on either side of it.
#   DOWNSTREAM x = 51  ground 0.0 (past the step)
#       sampled axis : level 0.0  — the mirror lies ON the low ground
#       two-knot ramp: level = 3 - 0.03·51 = 1.47, i.e. 1.47 m ABOVE a ground
#                      of zero. That is "the mound of water": a slab hanging in
#                      the air with nothing under it.
#
# AND THE CARVE UPSTREAM, which is the same statement in bed metres. The ribbon
# is 6 m wide, so at z = 0 the distance to its outline is 3 m — exactly the
# shore ramp — and the full depth applies:
#       sampled axis : bed = 3.0 - 1.0 = 2.0, i.e. exactly water_depth_m of
#                      water in a bed cut into the plateau, banks at 3.0
#       two-knot ramp: bed = min(3.0, 2.07 - 1.0) = 1.07, i.e. the SAME 1.0 m
#                      of water, but 1.93 m down a trench — the mirror dived
#                      under the ground it should be lying on, taking the bed
#                      with it.
near("upstream (10 m before the lip) the mirror is the plateau's own 3.0",
     hf.water_level_at(CLIFF, 31.0, 0.0), 3.0, 1e-12)
near("...flush with the ground beside it, to the centimetre",
     CMODEL_W5.natural(31.0, 0.0) - hf.water_level_at(CLIFF, 31.0, 0.0), 0.0,
     0.01)
near("RED: the two-knot ramp read 2.07 there", hf.water_level_at(RAMP, 31.0,
                                                                0.0),
     2.07, 1e-12)
near("...0.93 m BELOW its own banks — 'the water is almost gone'",
     CMODEL_W5.natural(31.0, 0.0) - hf.water_level_at(RAMP, 31.0, 0.0), 0.93,
     1e-12)
near("downstream (10 m past the lip) the mirror is the low ground's own 0.0",
     hf.water_level_at(CLIFF, 51.0, 0.0), 0.0, 1e-12)
near("...flush with it as well", hf.water_level_at(CLIFF, 51.0, 0.0)
     - CMODEL_W5.natural(51.0, 0.0), 0.0, 0.01)
near("RED: the two-knot ramp read 1.47 there", hf.water_level_at(RAMP, 51.0,
                                                                0.0),
     1.47, 1e-12)
near("...1.47 m ABOVE a ground of zero — 'a mound of water'",
     hf.water_level_at(RAMP, 51.0, 0.0) - CMODEL_W5.natural(51.0, 0.0), 1.47,
     1e-12)
near("the upstream bed is cut exactly water_depth_m below the mirror",
     hf.water_level_at(CLIFF, 31.0, 0.0) - CMODEL_W5.final(31.0, 0.0), 1.0,
     1e-12)
near("...at 2.0, one metre under the plateau", CMODEL_W5.final(31.0, 0.0), 2.0,
     1e-12)
near("RED: the ramp put that same 1 m of water at 1.07 — 1.93 m down a trench",
     min(CMODEL_W5.natural(31.0, 0.0), hf.water_level_at(RAMP, 31.0, 0.0)
         - 1.0), 1.07, 1e-12)


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


# ── [10] THE SHORE GUARDS ARE RETIRED (v8, Wasser v2 K-A E6) ────────────
print("\n[10] the bank clamp and the relief fade are GONE — the shore is "
      "authored ground again")
# WHAT THEY WERE. Between v4 and v7 two stamps guarded the rim of every water,
# and both were written against ONE symptom of the mesh era: the mirror was a
# separate, transparent SURFACE, and the ground beside and under it knew
# nothing about it, so land above the mirror at the rim was a hole in the water
# and land below it was water standing in the air.
#
#   the BANK CLAMP (v4): in the `shore_ramp_m` band OUTSIDE the outline the
#       ground was held at at least `water_level_at(nearest outline point)`
#       + WATER_BANK_LIP_M (0.1 m), the minimum fading to nothing at the band's
#       outer edge;
#   the RELIEF FADE (v5/v6): the micro-relief was multiplied by a weight that
#       was 0 inside the polygon and on its outline and smoothstepped back to 1
#       over `max(shore_ramp_m, RELIEF_SHORE_FADE_M)` = at least 16 m outside.
#
# WHY THEY GO. E3 lifts the terrain VERTEX to `max(h, w_level)` wherever the
# water raster has a value, and E4/E5 deleted the mirror mesh: there is no
# second surface left that could stand on nothing, and ground under the mirror
# is drawn AS the mirror. Both guards therefore answer a question that no
# longer exists, while the price they charged is real — a 16 m flattened collar
# around every lake and a lip nobody authored along every shore.
#
# THE FIXTURE IS THE ONE THE CLAMP WAS WRITTEN ON, unchanged, so the numbers
# below are the same probes with the guard taken out:
#
#   BANK_WATER  square (0,0)-(40,40), kind "lake", water_level 1.0,
#               water_depth_m 2.0, shore_ramp_m 3.0
#   DIP         height area (40,0)-(60,20), height_m -0.4, falloff_m 0
#   RISE        height area (40,20)-(60,40), height_m  2.0, falloff_m 0
#
# The probes sit on the EAST edge (x >= 40), which the ray-cast rule counts as
# OUTSIDE, so "at the outline" is a probe and not a limit. With no clamp the
# whole band is the authored step:
#
#   (40.0, 10) -> -0.4     (v4 drew 1.1  = level + lip)
#   (40.5, 10) -> -0.4     (v4 drew 0.85)
#   (41.5, 10) -> -0.4     (v4 drew 0.35)
#   (43.0, 10) -> -0.4     (v4 drew -0.4: the band closed there)
#   (40.5, 30) ->  2.0     (unchanged: the clamp never lowered anything)
#
# INSIDE the polygon nothing moves at all — the carve is untouched:
#   (20, 20) -> level - depth = -1.0
#   (39, 20) -> the MIN keeps the natural 0.0
BANK_WATER = {"id": "ta_bank_lake", "kind": "lake", "z_order": 0,
              "polygon": [[0, 0], [40, 0], [40, 40], [0, 40]],
              "meta": {"water_level": 1.0, "water_depth_m": 2.0,
                       "shore_ramp_m": 3.0}}
DIP = {"id": "ha_dip", "polygon": [[40, 0], [60, 0], [60, 20], [40, 20]],
       "height_m": -0.4, "falloff_m": 0.0, "meta": {}}
RISE = {"id": "ha_rise", "polygon": [[40, 20], [60, 20], [60, 40], [40, 40]],
        "height_m": 2.0, "falloff_m": 0.0, "meta": {}}

BMODEL = hf.build_model([DIP, RISE], [], [BANK_WATER], CATALOG)

print("\n[10a] RED: the guards are gone by NAME — no fallback reader")
# The deletion proof of [9]'s kind: a reader that still existed would keep the
# old shore alive silently, and no test of a height could tell.
for _name in ("WATER_BANK_LIP_M", "RELIEF_SHORE_FADE_M", "_relief_fade_width",
              "_ring_nearest_point"):
    check(f"red: heightfield.{_name} is gone", hasattr(hf, _name), False)
for _name in ("_bank_clamp", "_relief_weight", "water_bank_box",
              "_relief_fade", "_relief_fade_index"):
    check(f"red: HeightModel.{_name} is gone", hasattr(BMODEL, _name), False)
check("red: `final` names three stages, not four",
      "_bank_clamp" in inspect.getsource(hf.HeightModel.final), False)
check("HEIGHT_BAKE_VERSION", hf.HEIGHT_BAKE_VERSION, 10)

print("\n[10b] the band outside the outline is the authored step, probe by "
      "probe")
near("NATURAL east of the water is the authored step",
     BMODEL.natural(40.5, 10.0), -0.4, 1e-12)
for _x, _v4 in ((40.0, 1.1), (40.5, 0.85), (41.5, 0.35)):
    near(f"at ({_x}, 10) the ground is the meadow's own -0.4",
         BMODEL.final(_x, 10.0), -0.4, 1e-12)
    check_not(f"…and NOT the {_v4} the clamp drew there",
              round(BMODEL.final(_x, 10.0), 9), _v4)
near("at the band's old outer edge nothing ever changed",
     BMODEL.final(43.0, 10.0), -0.4, 1e-12)
near("ground already at 2.0 is still 2.0 — the clamp only ever raised",
     BMODEL.final(40.5, 30.0), 2.0, 1e-12)

print("\n[10c] h_final is now natural -> carve -> plateaus, exactly")
# The clamp used to sit between the carve and the stamps. Its removal is not a
# tweak of a number but a stage taken out of the pipeline, so the whole
# function must equal the three remaining stages composed by hand — measured
# over the fixture's shore rather than at one lucky probe.
_stages = [(x / 2.0, z / 2.0) for x in range(-10, 121) for z in range(0, 81)]
_worst_stage = max(abs(BMODEL.final(px, pz)
                       - BMODEL._stamp(BMODEL._carve(BMODEL.natural(px, pz),
                                                     px, pz), px, pz))
                   for px, pz in _stages)
near(f"over {len(_stages)} probes the two agree to the bit", _worst_stage, 0.0,
     0.0)

print("\n[10d] INSIDE the polygon the bed is the carve's, unchanged")
near("deep water: level - depth", BMODEL.final(20.0, 20.0), -1.0, 1e-12)
near("a metre inside the rim: the MIN keeps the natural 0.0",
     BMODEL.final(39.0, 20.0), 0.0, 1e-12)

print("\n[10e] § G4, RIM HALF — the guarantee is the LIFT's now, not the "
      "bake's")
# THE NEW RULE, and it is constructive rather than measured: what a renderer
# draws over water is `max(h, w_level)` per morph tap (K-A E3), so at every
# drawn level a water texel's surface IS the mirror the raster carries there.
# Ground below the mirror is therefore drawn AS the mirror — the case the bank
# clamp existed for cannot produce a gap — and ground above it is drawn as what
# it is, a rock in the lake, which needs no guard either because there is no
# plate for it to hole.
#
# THE SERVER'S HALF OF THAT SENTENCE is the raster, and it is what this section
# pins: the mirror EXISTS wherever the mask says water, at every level a
# renderer draws, because the decimation is a SUBSET of a piecewise-linear
# field and a coarse texel is water exactly when its own base texel is
# (K-A E2, `client3d/src/scene/terrainLod.buildWaterPyramid`). A subset needs
# no second evaluation — but `water_at` is a pure function of the point, so the
# subset can be checked against the field itself, which is what makes the
# statement numeric here instead of on the client.
_W0 = BMODEL.water_raster(-8.0, -8.0, 2.0, 33, 33)
check_true("the window carries water at all", _W0 is not None)
for _stride in (2, 4, 8):
    _Wk = BMODEL.water_raster(-8.0, -8.0, 2.0 * _stride,
                              (32 // _stride) + 1, (32 // _stride) + 1)
    _diff = [(i, j) for j in range(len(_Wk[0]))
             for i in range(len(_Wk[0][0]))
             if _Wk[0][j][i] != _W0[0][j * _stride][i * _stride]]
    check(f"the {2.0 * _stride} m lattice IS every {_stride}th base texel — "
          "level and dry sentinel alike", _diff, [])
# …and with that, the drawn surface over water is the mirror, to the bit. The
# probe is the whole shore of the fixture at the base lattice: wherever the
# raster answers a level, `max(h_final, level)` is at least that level, and
# where the bed lies under it the two are EQUAL — there is nothing left for a
# lip to guarantee.
_wet = [(px, pz) for px in [x / 2.0 for x in range(-8, 97)]
        for pz in [z / 2.0 for z in range(0, 81)]
        if BMODEL.water_at(px, pz) is not None]
_under = [(px, pz) for px, pz in _wet
          if BMODEL.final(px, pz) < BMODEL.water_at(px, pz)[0]]
_worst_draw = min(max(BMODEL.final(px, pz), BMODEL.water_at(px, pz)[0])
                  - BMODEL.water_at(px, pz)[0] for px, pz in _wet)
near(f"over {len(_wet)} wet probes nothing is drawn UNDER its own mirror",
     _worst_draw, 0.0, 0.0)
check_true(f"…and {len(_under)} of them lie under it in the BAKE, which is "
           "exactly what the lift is for", len(_under) > 0)
near("the retired clamp's own probe: the bank at (40, 10) is 1.4 m under the "
     "mirror…", 1.0 - BMODEL.final(40.0, 10.0), 1.4, 1e-12)
near("…and is drawn AT the mirror, 1.0", max(BMODEL.final(40.0, 10.0),
                                             BMODEL.water_at(40.0, 10.0)[0]),
     1.0, 1e-12)

print("\n[10f] what a water still WRITES outside its outline: the ring")
# The box the tile index and the grid growth read is grown by the DILATION now
# and no longer by `shore_ramp_m`: the clamp is gone, and what a water still
# puts outside its own rim is the raster's ring — 2 steps = 4 m.
check("the water's shaped box = outline grown by WATER_RASTER_DILATION_M",
      [b for b in BMODEL.shaped_boxes()
       if b == (-4.0, -4.0, 44.0, 44.0)], [(-4.0, -4.0, 44.0, 44.0)])
_sb = BMODEL.shaped_bounds()
check("…and shaped_bounds contains it", _sb[0] <= -4.0 and _sb[2] >= 60.0,
      True)
near("the ring is 2 lattice steps wide", hf.WATER_RASTER_DILATION_M, 4.0,
     1e-12)

print("\n[10g] THE PRICE, MEASURED: the drawn water reaches into the ring")
# A bank below the mirror is drawn as water for as long as the raster has a
# level there, i.e. up to WATER_RASTER_DILATION_M outside the authored outline
# — and it STOPS there, with a step as tall as the water it was carrying. That
# is the honest cost of retiring the clamp, stated as a number rather than
# discovered later: on this fixture the dip is 1.4 m under the mirror, so the
# lake is drawn 4 m into the meadow and its surface ends in a 1.4 m step.
# The clamp did not really prevent this either (its band is `shore_ramp_m`
# = 3 m < 4 m, and a legal ramp of 0 covers nothing at all) — it only made the
# ground it did cover high enough not to lift.
_spill = [d / 4.0 for d in range(0, 25)]
_wet_out = [d for d in _spill
            if BMODEL.water_at(40.0 + d, 10.0) is not None]
_lifted = [d for d in _wet_out
           if BMODEL.final(40.0 + d, 10.0) < BMODEL.water_at(40.0 + d,
                                                             10.0)[0]]
near("the raster's last wet probe east of the rim is 4 m out", max(_wet_out),
     4.0, 1e-12)
near("…and every one of them lifts, to the ring's edge", max(_lifted), 4.0,
     1e-12)
near("the step where the water ends is the depth it carried there",
     BMODEL.water_at(44.0, 10.0)[0] - BMODEL.final(44.0, 10.0), 1.4, 1e-12)
check("…and half a metre further out there is no water at all",
      BMODEL.water_at(44.5, 10.0), None)


# ── [11] THE RELIEF REACHES THE WATERLINE AGAIN (v8) ────────────────────
print("\n[11] the micro-relief runs up to the water again — no 16 m collar")
# THE FIXTURE of the fade sections, unchanged, so every number is the same
# probe with the guard taken out:
#
#   FADE_LAKE    square (0,0)-(40,40), kind "lake", NO water_level,
#                water_depth_m 2.0, shore_ramp_m 4.0
#   FADE_MEADOW  kind "g" over (-40,-40)-(80,80), amplitude 1.0, wave 16,
#                painted AFTER the lake, so `_kind_at` answers "g" inside the
#                polygon too
#
# There is no height area under this fixture, so `natural` IS the relief —
# and since v8 it is the relief at FULL amplitude everywhere, inside the
# polygon included. The weight table of v6 (0 at the outline, 0.011 one metre
# out, 0.5 at 8 m, 1 at 16 m) is gone with the function that computed it.
FADE_LAKE = {"id": "ta_fade_lake", "kind": "lake", "z_order": 0,
             "polygon": [[0, 0], [40, 0], [40, 40], [0, 40]],
             "meta": {"water_depth_m": 2.0, "shore_ramp_m": 4.0}}
FADE_MEADOW = {"id": "ta_fade_meadow", "kind": "g", "z_order": 1,
               "polygon": [[-40, -40], [80, -40], [80, 80], [-40, 80]],
               "meta": {"relief_amplitude_m": 1.0, "relief_wave_m": 16.0}}
FMODEL = hf.build_model([], [], [FADE_LAKE, FADE_MEADOW], CATALOG)


def v6_weight(d):
    """The RETIRED curve, re-derived here so the red probes still have it:
    smoothstep(d / 16), 0 inside the polygon."""
    t = min(max(d / 16.0, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


print("  [11a] the ground east of the outline IS the noise, undamped")
for d in (0.0, 1.0, 2.0, 4.0, 8.0, 12.0, 16.0, 17.0):
    x = 40.0 + d
    near(f"natural at d = {d} m = the hand noise, weight 1",
         FMODEL.natural(x, 10.0), hand_noise(x, 10.0, SEED_G), 1e-12)
    if 0.0 < d < 16.0:
        # (at 16 m and past it the retired weight was 1 too — nothing to tell
        #  apart there, which is precisely why the band was 16 m wide)
        check_not(f"…and NOT the {round(v6_weight(d), 6)} of it v6 left",
                  round(FMODEL.natural(x, 10.0), 12),
                  round(hand_noise(x, 10.0, SEED_G) * v6_weight(d), 12))
near("…and INSIDE the polygon the relief is back too",
     FMODEL.natural(20.0, 20.0), hand_noise(20.0, 20.0, SEED_G), 1e-12)
check_not("…which is not the flat 0.0 the fade left there",
          round(FMODEL.natural(20.0, 20.0), 12), 0.0)
near("the CARVE is what removes it under the water: level - depth",
     FMODEL.final(20.0, 20.0),
     FMODEL.water_profile_by_area["ta_fade_lake"].level_up - 2.0, 1e-12)

print("  [11b] the mirror is the median of a WOBBLING rim again")
# The derived level is the median of `natural` over the 80 rim samples, and
# with the relief back those 80 numbers are the hand noise itself. The median
# of an even count is the mean of the two middle values.
FPROF = FMODEL.water_profile_by_area["ta_fade_lake"]
FRIM = hf._rim_samples(FADE_LAKE["polygon"])
check("…over 80 rim samples", len(FRIM), 80)
_rim_h = sorted(hand_noise(px, pz, SEED_G) for px, pz in FRIM)
_rim_median = (_rim_h[39] + _rim_h[40]) / 2.0
near(f"the derived mirror is that hand median ({round(_rim_median, 6)})",
     FPROF.level_up, _rim_median, 1e-12)
check_not("…and NOT the exact 0.0 a relief-free rim gave v6",
          round(FPROF.level_up, 12), 0.0)
_over = max(hand_noise(px, pz, SEED_G) for px, pz in FRIM) - _rim_median
check_true(f"the rim spreads {round(_rim_h[-1] - _rim_h[0], 3)} m over one "
           "lake again", _rim_h[-1] - _rim_h[0] > 1.0)
check_true(f"…and its highest point stands {round(_over, 3)} m over its own "
           "mirror — which is now a ROCK, not a hole", _over > 0.4)

print("  [11c] § G4 says that is legal: the water is drawn AT the mirror "
      "wherever it is water")
# The v6 sections measured "drawn − mirror" INSIDE the polygon and needed it
# under the lip, because a plate was drawn over the terrain and anything above
# the plate hid it. Under K-A the drawn surface is `max(h, w)`, so the quantity
# that matters is the other one: is anything drawn UNDER the mirror where the
# raster says water? It cannot be, and the number is exact.
_probe_xy = [(x / 2.0, z / 2.0) for x in range(-8, 97) for z in range(-8, 97)]
_wet_f = [(px, pz) for px, pz in _probe_xy
          if FMODEL.water_at(px, pz) is not None]
near(f"over {len(_wet_f)} wet probes: min(max(h, w) − w)",
     min(max(FMODEL.final(px, pz), FMODEL.water_at(px, pz)[0])
         - FMODEL.water_at(px, pz)[0] for px, pz in _wet_f), 0.0, 0.0)
# The rocks are counted, not wished away: rim points above the mirror are drawn
# as ground, which is what they are.
_rocks = [(px, pz) for px, pz in _wet_f
          if FMODEL.final(px, pz) > FMODEL.water_at(px, pz)[0] + 1e-12]
check_true(f"{len(_rocks)} probes stand above their own mirror and are drawn "
           "as the ground they are", len(_rocks) > 0)

print("  [11d] the collar the fade flattened is landscape again")
# The 16 m band around this lake carried NO relief at all between v5 and v7.
# The measurement that convicted the 1 m band in [11h] of the fade era, run
# the other way round: how much wave stands in the first 4 m of the collar now.
_collar = []
_gx = -8.0
_ring_lake = hf._ring(FADE_LAKE["polygon"])
while _gx <= 48.0 + 1e-9:
    _gz = -8.0
    while _gz <= 48.0 + 1e-9:
        if not hf._inside_ring(_gx, _gz, _ring_lake) \
                and hf._ring_edge_distance(_gx, _gz, _ring_lake) <= 4.0:
            _collar.append((abs(FMODEL.natural(_gx, _gz)),
                            abs(FMODEL.natural(_gx, _gz)) * v6_weight(
                                hf._ring_edge_distance(_gx, _gz, _ring_lake))))
        _gz += 0.5
    _gx += 0.5
_worst_v8 = max(c[0] for c in _collar)
_worst_v6 = max(c[1] for c in _collar)
check_true(f"the 4 m collar carries {round(_worst_v8, 4)} m of wave again",
           _worst_v8 > 0.5)
check_true(f"…where v6 left {round(_worst_v6, 4)} m of it — the flattening "
           "nobody authored", _worst_v6 < 0.5 * _worst_v8)

print("  [11e] a 0-ramp basin is still a basin — the CARVE never moved")
STEP_LAKE = {"id": "ta_step_lake", "kind": "lake", "z_order": 0,
             "polygon": [[0, 0], [40, 0], [40, 40], [0, 40]],
             "meta": {"water_depth_m": 2.0, "shore_ramp_m": 0.0}}
SMODEL = hf.build_model([], [], [STEP_LAKE, FADE_MEADOW], CATALOG)
near("the BED of a 0-ramp basin is full depth at the rim",
     SMODEL.final(39.0, 20.0), SMODEL.water_profile_by_area[
         "ta_step_lake"].level_up - 2.0, 1e-12)
near("…and the ground half a metre outside it is the meadow, untouched",
     SMODEL.natural(40.5, 10.0), hand_noise(40.5, 10.0, SEED_G), 1e-12)

print("  [11f] the stored raster cannot survive the rule change")
# THE ONE THING THAT HAS TO KEEP WORKING when a bake rule is deleted: the bake
# result is persisted in `world_heightfield` and only rebuilt when the row's
# `sig` no longer matches `height_sig()`. Without the version bump every
# running world would keep the collar and the lip for ever.
from app.models import heightfield as store2  # noqa: E402
_before = store2.height_sig()
_bumped = hf.HEIGHT_BAKE_VERSION + 1
try:
    hf.HEIGHT_BAKE_VERSION = _bumped
    _after = store2.height_sig()
finally:
    hf.HEIGHT_BAKE_VERSION = _bumped - 1
check_not("moving ONLY the code version moves the signature", _after, _before)
near("…and it is exactly 10 characters, like the other one", len(_after), 10,
     0)
check("the restored version is the one this bake ships",
      hf.HEIGHT_BAKE_VERSION, 10)
_get_field_src = inspect.getsource(hf.get_field)
check_true("get_field rejects a stored raster whose sig differs",
           'stored.get("sig") == sig' in _get_field_src)
check_true("…and there is no second, unversioned store: the tiles the client "
           "renders are never persisted",
           "NOTHING IS STORED IN THE DB" in inspect.getsource(hf.get_tile))
check("water_basis names no lip",
      "lip" in inspect.getsource(store2.water_basis).lower(), False)
check("height_sig hashes the code version",
      "code_version" in inspect.getsource(store2.height_sig), True)


# ── [12] THE WATER RASTER (Wasser v2, K-A E1) ───────────────────────────
#
# The tile carries a SECOND field: per lattice point the local mirror and the
# flow vector, written N steps PAST every outline. `h_final` does not move — the
# mirror was always an input of the carve — so everything above this section is
# unchanged and this one only asks what the new field says.
#
# THE THREE RULES, and every number below follows from them:
#
#   level(p) = water_level_at(profile, p)      of the TOPMOST water covering p
#   flow(p)  = water_flow_at(profile, p) · factor          of that same water
#   covered  = inside the outline, OR within WATER_RASTER_DILATION_M of it
#
# "Topmost" is the ground's own rule (the LAST painted area wins), and inside
# beats dilated: the ring is a filter fix, not authorship.
print("\n[12a] the raster IS the mirror, sampled — the still lake")
# WATER_SET is the square (20,20)-(60,60) with an AUTHORED level of 3.0, so its
# profile is one knot at the centroid (40,40) carrying 3.0 and `water_level_at`
# answers 3.0 at every point of the plane. A one-knot axis has no segment, so
# the flow is exactly (0, 0) — every still water, by construction.
check("inside: the authored mirror, no flow at all, and 20 m of sd",
      [round(v, 6) for v in MODEL.water_at(40.0, 40.0)[:4]],
      [3.0, 0.0, 0.0, 20.0])
check("...and the fifth answer is the painted KIND (v10)",
      MODEL.water_at(40.0, 40.0)[4], "lake")
check("ON the outline the point is covered, and its sd is exactly 0",
      [round(v, 6) for v in MODEL.water_at(20.0, 40.0)[:4]],
      [3.0, 0.0, 0.0, 0.0])
near("dry ground far from any water answers nothing at all",
     1.0 if MODEL.water_at(-50.0, -50.0) is None else 0.0, 1.0)

print("\n[12b] the DILATION — two lattice steps, and the number is a diagonal")
near("the band is WATER_RASTER_DILATION_STEPS · TILE_STEP_M",
     hf.WATER_RASTER_DILATION_M,
     hf.WATER_RASTER_DILATION_STEPS * hf.TILE_STEP_M, 1e-12)
near("...which is 2 steps = 4 m", hf.WATER_RASTER_DILATION_M, 4.0, 1e-12)
# West of the lake's rim at x = 20, on the lattice (even metres): the distance
# to the OUTLINE is 20 - x.
check("4 m out — exactly the band — is still written, sd NEGATIVE",
      [round(v, 6) for v in MODEL.water_at(16.0, 40.0)[:4]],
      [3.0, 0.0, 0.0, -4.0])
check("...and the ring carries the same KIND — one decision, all five channels",
      MODEL.water_at(16.0, 40.0)[4], "lake")
check_true("...and 6 m out is dry", MODEL.water_at(14.0, 40.0) is None)
# THE VALUE IN THE RING IS THE FUNCTION CONTINUED, not the rim value carried
# outward — which is what makes the bilinear mix inside the outline reproduce
# the profile. For the still lake both readings are 3.0, so the CLIFF river
# says it instead: its axis lies on z = 0 and its mask is (0,-3)-(100,3), so a
# ring point at (50, 6) is 3 m outside the rim and `water_level_at` there is
# the level at s = 50, i.e. the low ground's 0.0 — not the 0.0 + something a
# nearest-outline-point rule would have produced. Both happen to be 0.0 here;
# the point that CAN differ is the level at x = 41 (see [8l]).
near("the ring carries water_level_at OF THE RING POINT",
     CMODEL_W5.water_at(41.0, 5.0)[0],
     hf.water_level_at(CLIFF, 41.0, 5.0), 1e-12)
near("...which is the mid-drop 1.5, the same number the axis gives",
     CMODEL_W5.water_at(41.0, 5.0)[0], 1.5, 1e-12)
# THE DIAGONAL, which is why the band is TWO steps and not one. Let P be any
# point INSIDE an outline. A bilinear read at P mixes the four corners of P's
# lattice cell; if a corner C lies outside, the segment P->C crosses the
# outline at some Q, so d(C, outline) <= |CQ| <= |CP| <= one cell diagonal =
# sqrt(2) steps = 2.8284 m. One step does not cover that. THE FIXTURE: a lake
# whose south-west corner sits at (1.99, 1.99), a hair inside the lattice cell
# [0,2]^2. The point (1.995, 1.995) is inside it and reads the corner (0, 0),
# which is hypot(1.99, 1.99) = 2.8143 m outside the outline.
CORNER_LAKE = {"id": "ta_corner", "kind": "lake", "z_order": 0,
               "polygon": [[1.99, 1.99], [40, 1.99], [40, 40], [1.99, 40]],
               "meta": {"water_level": 1.0}}
CORNER_MODEL = hf.build_model([], [], [CORNER_LAKE], CATALOG)
near("the worst corner of a wet cell is one cell DIAGONAL out",
     math.hypot(1.99, 1.99), 1.99 * math.sqrt(2.0), 1e-12)
near("...and a full diagonal is sqrt(2) steps = 2.8284 m",
     hf.TILE_STEP_M * math.sqrt(2.0), 2.8284271, 1e-6)
check_true("...more than ONE step (2 m), so a 1-step band would leave it dry",
           math.hypot(1.99, 1.99) > hf.TILE_STEP_M)
check_true("...and under TWO (4 m), which is why the band covers it",
           math.hypot(1.99, 1.99) < hf.WATER_RASTER_DILATION_M)
check_true("the corner (0,0) really is written", CORNER_MODEL.water_at(0.0, 0.0)
           is not None)
check_true("...and the point (1.995, 1.995) really is INSIDE the lake",
           hf._inside_ring(1.995, 1.995, [(1.99, 1.99), (40.0, 1.99),
                                          (40.0, 40.0), (1.99, 40.0)]))
check_true("RED: at one step of dilation that same corner would be dry",
           math.hypot(1.99, 1.99) > 1 * hf.TILE_STEP_M)

print("\n[12c] the FLOW — the server owns the blended tangent now")
# The cliff river's axis is four knots on z = 0 running east, so every segment
# tangent is (1, 0) and the blend at a knot mixes (1, 0) with (1, 0): the flow
# is the unit east vector everywhere, at every knot included.
check("a straight river flows along itself, length 1",
      [round(v, 6) for v in CMODEL_W5.water_at(50.0, 0.0)[1:3]], [1.0, 0.0])
check("...at a knot too, where the two legs are the same direction",
      [round(v, 6) for v in CMODEL_W5.water_at(40.0, 0.0)[1:3]], [1.0, 0.0])
# THE HAIRPIN, and these are the numbers the client's own `waterFlowAt` used to
# pin before Wasser v2 K-A E5 deleted it with the water mesh — the rule moved to
# the server, the answers did not, and this docstring is now the only place they
# are derived. Leg 1 is (99, -20)/101, leg 2 is (-48, -20)/52 = (-12, -5)/13,
# and AT the middle knot the tangent is their normalised bisector.
near("halfway along leg 1: the leg's own tangent, x",
     hf.water_flow_at(U, 199.5, 290.0)[0], 99.0 / 101.0, 1e-15)
near("...and z", hf.water_flow_at(U, 199.5, 290.0)[1], -20.0 / 101.0, 1e-15)
near("halfway along leg 2: x", hf.water_flow_at(U, 225.0, 270.0)[0],
     -12.0 / 13.0, 1e-15)
near("...and z", hf.water_flow_at(U, 225.0, 270.0)[1], -5.0 / 13.0, 1e-15)
near("AT the hairpin knot: the bisector the client pins, x",
     hf.water_flow_at(U, 249.0, 280.0)[0], 0.09757142403137047, 1e-12)
near("...and z", hf.water_flow_at(U, 249.0, 280.0)[1], -0.9952285251199801,
     1e-12)
near("...and it is a UNIT vector — the factor is applied after the mix",
     math.hypot(*hf.water_flow_at(U, 249.0, 280.0)), 1.0, 1e-12)
# THE SPEED FACTOR is the area's own speed over its KIND's dial, the twin of
# `@anima/scene-render waterFlowFactor`. An area that authors nothing is
# exactly 1, which is what keeps every existing water the plain unit tangent.
# The 0.15 below is this river kind's AUTHORED dial (the `{"river": 0.15}` the
# model is built with), not `WATER_FLOW_SPEED_DEFAULT_M_S` — the ratio is what
# is being derived, so the numbers stand whatever the default is dialled to.
near("no authored speed -> factor exactly 1",
     hf.water_flow_factor(None, 0.15), 1.0, 1e-15)
near("half the kind's speed -> half the length",
     hf.water_flow_factor(0.075, 0.15), 0.5, 1e-15)
near("the kind's own number cancels", hf.water_flow_factor(0.3, 0.3), 1.0,
     1e-15)
near("an authored 0 is FLOORED, never a zero-length vector",
     hf.water_flow_factor(0.0, 0.15), hf.WATER_FLOW_FACTOR_MIN, 1e-18)
near("a kind that cannot flow cannot be made to", hf.water_flow_factor(1.0,
                                                                       0.0),
     1.0, 1e-15)
near("...and the area is clamped to the ceiling the kind's dial has",
     hf.water_flow_factor(99.0, 0.15),
     hf.WATER_FLOW_SPEED_MAX_M_S / 0.15, 1e-12)
# …and it reaches the raster: the same hairpin at half its kind's speed.
U_SLOW = u_river("ta_u_slow", {"flow_along": "forward",
                               "flow_speed_m_s": 0.075})
USMODEL = hf.build_model([BOWL], [], [U_SLOW], CATALOG_R,
                         {"river": 0.15})
near("the raster carries the factor as the vector's LENGTH",
     math.hypot(*USMODEL.water_at(199.5, 290.0)[1:3]), 0.5, 1e-12)

print("\n[12d] THE CURVE-INSIDE MEASUREMENT — does 2 m have to get finer?")
# THE QUESTION (recherche-wasser-v2.md § 7 no. 2): a raster is read BILINEARLY,
# so between its support points it is not the function. How far off is it on the
# inside of a tight curve, where `water_level_at` changes fastest?
#
# STEP 1: ON its own lattice the raster is not "close to" the function, it IS
# the function — `water_at` returns `water_level_at` unrounded.
_lattice_worst = 0.0
for _i in range(70, 151):
    for _j in range(125, 158):
        _w = UMODEL.water_at(_i * 2.0, _j * 2.0)
        if _w is None:
            continue
        _lattice_worst = max(_lattice_worst,
                             abs(_w[0] - hf.water_level_at(U, _i * 2.0,
                                                           _j * 2.0)))
near("on the 2 m lattice the deviation is EXACTLY zero", _lattice_worst, 0.0,
     0.0)


def _raster_deviation(step, n=321):
    """(worst, worst on cells that do NOT straddle a kink) over the U mask.

    The raster is built on the world-anchored lattice of `step`, read
    bilinearly, and compared against `water_level_at` at n x n probes inside
    the mask. A cell is "smooth" when its four corners AND the probe all
    project onto the same axis SEGMENT — i.e. no medial axis runs through it.
    """
    cache = {}

    def lat(i, j):
        key = (i, j)
        if key not in cache:
            found = UMODEL.water_at(i * step, j * step)
            cache[key] = None if found is None else found[0]
        return cache[key]

    ring = [(140.0, 250.0), (300.0, 250.0), (300.0, 315.0), (140.0, 315.0)]
    worst = 0.0
    smooth = 0.0
    for a in range(n):
        x = 140.0 + 160.0 * a / (n - 1)
        for b in range(n):
            z = 250.0 + 65.0 * b / (n - 1)
            if not hf._inside_ring(x, z, ring):
                continue
            fi, fj = x / step, z / step
            i, j = math.floor(fi), math.floor(fj)
            tx, tz = fi - i, fj - j
            corners = (lat(i, j), lat(i + 1, j), lat(i, j + 1),
                       lat(i + 1, j + 1))
            weights = ((1 - tx) * (1 - tz), tx * (1 - tz), (1 - tx) * tz,
                       tx * tz)
            value = 0.0
            usable = True
            for corner, weight in zip(corners, weights):
                if weight == 0.0:
                    continue
                if corner is None:
                    usable = False
                    break
                value += corner * weight
            if not usable:
                continue
            err = abs(value - hf.water_level_at(U, x, z))
            worst = max(worst, err)
            segs = {hf._axis_nearest(U.axis, i * step, j * step)[1],
                    hf._axis_nearest(U.axis, (i + 1) * step, j * step)[1],
                    hf._axis_nearest(U.axis, i * step, (j + 1) * step)[1],
                    hf._axis_nearest(U.axis, (i + 1) * step,
                                     (j + 1) * step)[1],
                    hf._axis_nearest(U.axis, x, z)[1]}
            if len(segs) == 1:
                smooth = max(smooth, err)
    return worst, smooth


_dev2, _smooth2 = _raster_deviation(2.0)
_dev1, _smooth1 = _raster_deviation(1.0)
_dev05, _smooth05 = _raster_deviation(0.5)
print(f"    measured: 2 m -> worst {_dev2:.4f} m (smooth {_smooth2:.4f} m); "
      f"1 m -> {_dev1:.4f} (smooth {_smooth1:.4f}); "
      f"0.5 m -> {_dev05:.4f} (smooth {_smooth05:.4f})")
# STEP 2: WHERE THE THE WORST NUMBER COMES FROM — a STEP in the function
# itself. A hairpin's two legs both run near the inside of the bend, and a point
# a hair to one side projects onto leg 1 while a hair to the other projects onto
# leg 2; the two arc coordinates differ by most of the bend, so the level JUMPS.
# On the fixture at z = 277.727 the level falls from 8.44 to 7.15 between
# x = 225.8 and x = 225.9 — over one tenth of a metre.
_jump = abs(hf.water_level_at(U, 225.8, 277.727)
            - hf.water_level_at(U, 225.9, 277.727))
check_true("`water_level_at` STEPS across the hairpin's medial axis "
           f"({_jump:.4f} m over 0.1 m)", _jump > 1.0)
check_true("...and no lattice resolves a step: halving it does not halve the "
           "error", _dev1 > 0.9 * _dev2 and _dev05 > 0.9 * _dev2)
check_true("...nor does quartering it", _dev05 > 0.9 * _dev2)
# STEP 3: AWAY FROM THE STEP the 2 m raster is already exact to the centimetre,
# and there it behaves as a bilinear reading must — second order in the step.
check_true(f"the smooth part is under 5 cm at 2 m ({_smooth2:.4f} m)",
           _smooth2 < 0.05)
check_true("...and it really is second order: halving the step at least "
           "halves it", _smooth1 < 0.6 * _smooth2)
check_true("...quartering it takes it under a fifth", _smooth05 < 0.2 * _smooth2)
# THE VERDICT, stated as the check it is: the water raster does NOT need a step
# finer than the height field's. What limits it is a discontinuity of the
# authored mirror, which a finer lattice cannot touch and which the client's
# fragment MASK (K-A E4) is what will hide.
check_true("VERDICT: 2 m stands — the error is the mirror's own step, not the "
           "lattice's", _dev2 > 10 * _smooth2)

print("\n[12e] the payload — additive, and absent where there is no water")
_wet_tile = hf.rasterize_tile(0, 0, [SLOPE], [PLOT], TERRAIN, CATALOG)
_dry_tile = hf.rasterize_tile(3, 3, [SLOPE], [PLOT], TERRAIN, CATALOG)
check("the wet tile carries the second field", "water" in _wet_tile, True)
check("a tile without a drop of water carries no key at all",
      "water" in _dry_tile, False)
check("the water field is on the tile's OWN lattice",
      [len(_wet_tile["water"]["level"]),
       len(_wet_tile["water"]["level"][0])],
      [hf.TILE_POINTS, hf.TILE_POINTS])
check("dry lattice points are the null sentinel",
      _wet_tile["water"]["level"][0][0], None)
# (40, 40) is the lake's middle: lattice index 20, 20.
check("...and wet ones the mirror, rounded like the heights",
      _wet_tile["water"]["level"][20][20], 3.0)
check("STILL water ships no flow arrays — they would be lattices of zeros",
      [k for k in sorted(_wet_tile["water"])],
      ["kind_idx", "kinds", "level", "sd"])
_cliff_tile = hf.rasterize_tile(0, 0, [STEP_AREA], [], [CLIFF_RIVER],
                                CATALOG_R)
check("a FLOWING water ships all four",
      sorted(_cliff_tile["water"]),
      ["flow_x", "flow_z", "kind_idx", "kinds", "level", "sd"])
check("...and the flow is the unit tangent at (50, 0), lattice (25, 0)",
      [_cliff_tile["water"]["flow_x"][0][25],
       _cliff_tile["water"]["flow_z"][0][25]], [1.0, 0.0])

print("\n[12f] the tile STATISTICS are heights-only — water changes none")
_stats_with = hf.tile_stats_from(_wet_tile)
_stats_without = hf.tile_stats_from({k: v for k, v in _wet_tile.items()
                                     if k != "water"})
check("min/max/err are read off `heights` and nothing else",
      _stats_with, _stats_without)
check_true("...so a stored `world_height_tile_stats` row stays a true "
           "statement about its raster",
           _stats_with["err"] == _stats_without["err"])

print("\n[12g] the sd CHANNEL — where the author drew the water (bake v9)")
# THE FINDING IT ANSWERS (F-A, "the lake is only a sand surface"). Until v9 the
# renderer asked the GROUND COMPOSITOR's material mask whether a pixel stands
# inside a water: that mask names the topmost painted KIND and the one under it,
# so a lake whose BED is painted — a sand shape inside the outline, which is
# what `bed_kind` describes and what a generated map draws — reads (sand, sand)
# over its whole interior and the gate answered "no water" for the whole lake.
# The red probe for that is in `app.core.terrain_layers` and is measured below;
# the fix is this channel, which is a statement about the WATER's own outline
# and knows nothing about what is painted over it.
#
# THE RULE: sd = +d(p, outline) inside, -d(p, outline) in the dilation ring,
# None where the level is None. The winning water's own outline — the same
# "topmost painted wins" that picks the level, one decision for all four
# channels.
check("mid-lake: 20 m from the square (20,20)-(60,60)",
      round(MODEL.water_at(40.0, 40.0)[3], 6), 20.0)
check("...on the outline it is exactly 0 — the zero level set IS the outline",
      round(MODEL.water_at(20.0, 40.0)[3], 6), 0.0)
check("...4 m out (the dilation's own width) it is -4",
      round(MODEL.water_at(16.0, 40.0)[3], 6), -4.0)
check("...a corner probe: (24, 24) is 4 m from BOTH edges, so 4",
      round(MODEL.water_at(24.0, 24.0)[3], 6), 4.0)
check_true("...and outside the ring there is no tuple to read at all",
           MODEL.water_at(14.0, 40.0) is None)
# THE PAINTED BED CHANGES NOTHING HERE, which is the whole point: the water
# raster is built from the WATER stamps, and a sand area painted inside the lake
# is not one. Same lake, same numbers, with a bed area drawn over it.
_BED = {"id": "ta_bed", "kind": "meadow", "z_order": 5,
        "polygon": [[24, 24], [56, 24], [56, 56], [24, 56]], "meta": {}}
_BEDMODEL = hf.build_model([SLOPE], [PLOT], list(TERRAIN) + [_BED], CATALOG)
check("a lake with a PAINTED BED answers the same sd mid-lake",
      round(_BEDMODEL.water_at(40.0, 40.0)[3], 6), 20.0)
check("...and the same level",
      round(_BEDMODEL.water_at(40.0, 40.0)[0], 6),
      round(MODEL.water_at(40.0, 40.0)[0], 6))
# THE GUARANTEE THE GATE RESTS ON: every point INSIDE an outline reads four
# corners that all carry a real distance, so a bilinear sd can never be dragged
# negative there by a dry corner. It is the dilation argument of [12b], read
# once more for the new channel.
_sd_worst = 0.0
for _a in range(0, 81):
    _x = 20.0 + 40.0 * _a / 80.0
    for _b in range(0, 81):
        _z = 20.0 + 40.0 * _b / 80.0
        _fi, _fj = math.floor(_x / 2.0), math.floor(_z / 2.0)
        _tx, _tz = _x / 2.0 - _fi, _z / 2.0 - _fj
        _c = [MODEL.water_at(_i * 2.0, _j * 2.0)
              for _i, _j in ((_fi, _fj), (_fi + 1, _fj), (_fi, _fj + 1),
                             (_fi + 1, _fj + 1))]
        _w = ((1 - _tx) * (1 - _tz), _tx * (1 - _tz), (1 - _tx) * _tz,
              _tx * _tz)
        _v = 0.0
        for _corner, _weight in zip(_c, _w):
            if _weight == 0.0:
                continue
            if _corner is None:
                _v = -1e9
                break
            _v += _corner[3] * _weight
        _sd_worst = min(_sd_worst, _v)
check_true("the bilinear sd is >= 0 at all 6561 probes inside the outline "
           f"(worst {_sd_worst:.4f} m)", _sd_worst >= 0.0)
# …and the payload carries it, masked exactly like the level.
check("the tile ships `sd` on the tile's own lattice",
      [len(_wet_tile["water"]["sd"]), len(_wet_tile["water"]["sd"][0])],
      [hf.TILE_POINTS, hf.TILE_POINTS])
check("dry lattice points are null in BOTH arrays",
      [_wet_tile["water"]["level"][0][0], _wet_tile["water"]["sd"][0][0]],
      [None, None])
check("...and (40, 40) = lattice (20, 20) carries the 20 m",
      _wet_tile["water"]["sd"][20][20], 20.0)
_mask_same = all((_wet_tile["water"]["level"][_j][_i] is None)
                 == (_wet_tile["water"]["sd"][_j][_i] is None)
                 for _j in range(hf.TILE_POINTS)
                 for _i in range(hf.TILE_POINTS))
check_true("the two masks are the SAME mask, texel for texel", _mask_same)

print("\n[12h] the FLOW BLUR — the medial-axis tangent jump, measured")
# THE FINDING (F-C, "the water does not flow and is structured differently every
# few metres"). `water_flow_at` reads the tangent at the NEAREST point of the
# axis, and "nearest" FLIPS across a medial axis, so the tangent jumps there —
# the same discontinuity [12d] measured on the level (1.2951 m over 0.1 m). The
# client draws its ripple in the frame that tangent spans, so two neighbouring
# lattice points hand it two very different frames.
near("the blur radius IS the dilation, so the kernel of any point inside an "
     "outline stays inside the written footprint",
     hf.WATER_FLOW_BLUR_M, hf.WATER_RASTER_DILATION_M, 1e-12)
near("...which is 2 texels at TILE_STEP_M, i.e. a 5 x 5 box spanning 8 m",
     hf.WATER_FLOW_BLUR_M / hf.TILE_STEP_M, 2.0, 1e-12)


def _flow_angles(model, i0, j0, cols, rows, step=2.0):
    """(worst, p99, mean) angle in degrees between the flow of two ADJACENT
    lattice points that are both INSIDE an outline — raw and as shipped.

    The raw field is `water_at` on the same lattice, i.e. exactly what the
    payload carried before v9; the shipped one is `water_raster`, blur and all.
    """
    lvl, fx, fz, sd, _kinds, _kidx = model.water_raster(
        i0 * step, j0 * step, step, cols, rows)
    raw = {}
    for j in range(rows):
        for i in range(cols):
            found = model.water_at((i + i0) * step, (j + j0) * step)
            raw[(i, j)] = (0.0, 0.0) if found is None else (found[1], found[2])
    inside = {(i, j) for j in range(rows) for i in range(cols)
              if sd[j][i] is not None and sd[j][i] >= 0}
    out = []
    for field in (raw, {(i, j): (fx[j][i], fz[j][i])
                        for j in range(rows) for i in range(cols)}):
        vals = []
        for (i, j) in inside:
            for di, dj in ((1, 0), (0, 1)):
                if (i + di, j + dj) not in inside:
                    continue
                a = field[(i, j)]
                b = field[(i + di, j + dj)]
                la, lb = math.hypot(*a), math.hypot(*b)
                if la < 1e-9 or lb < 1e-9:
                    continue
                dot = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (la * lb)))
                vals.append(math.degrees(math.acos(dot)))
        vals.sort()
        out.append((vals[-1], vals[int(len(vals) * 0.99)],
                    sum(vals) / len(vals)) if vals else (0.0, 0.0, 0.0))
    lens = [math.hypot(fx[j][i], fz[j][i]) for (i, j) in inside]
    return out[0], out[1], (min(lens), max(lens))


# FIXTURE 1 — A RIVER DRAWN AS A RIVER: the meander's polygon is its own line
# offset by half the width, which is how every authored river looks. The medial
# axis of the LINE lies outside such a ribbon for every bend gentler than the
# half-width, so there is no jump inside it at all — and this is the measurement
# that says how much of F-C the blur can be responsible for.
_MW = 8.0
_MPTS = [(60.0 + _t * 4.0, 60.0 + 18.0 * math.sin(_t * 4.0 * math.pi / 120.0))
         for _t in range(31)]


def _offset(points, d):
    out = []
    for i, (x, z) in enumerate(points):
        ax, az = points[max(i - 1, 0)]
        bx, bz = points[min(i + 1, len(points) - 1)]
        tx, tz = bx - ax, bz - az
        length = math.hypot(tx, tz) or 1.0
        out.append((x - tz / length * d, z + tx / length * d))
    return out


_MEANDER = {"id": "ta_meander", "kind": "river", "z_order": 0,
            "polygon": ([list(p) for p in _offset(_MPTS, _MW / 2)]
                        + [list(p) for p in reversed(_offset(_MPTS, -_MW / 2))]),
            "meta": {"flow_along": "forward",
                     "stroke": {"points": [list(p) for p in _MPTS],
                                "width_m": _MW}}}
_MBOWL = {"id": "ha_mb", "polygon": [[0, 0], [300, 0], [300, 200], [0, 200]],
          "height_m": 20.0, "falloff_m": 300.0, "meta": {}}
_MMODEL = hf.build_model([_MBOWL], [], [_MEANDER], CATALOG_R)
_m_raw, _m_ship, _m_len = _flow_angles(_MMODEL, 25, 15, 71, 41)
print(f"    meander: raw worst {_m_raw[0]:.2f} deg (p99 {_m_raw[1]:.2f}, mean "
      f"{_m_raw[2]:.2f}) -> shipped worst {_m_ship[0]:.2f} deg "
      f"(p99 {_m_ship[1]:.2f}, mean {_m_ship[2]:.2f}); "
      f"|flow| {_m_len[0]:.4f}..{_m_len[1]:.4f}")
check_true("an authored river's tangent field has NO jump to begin with — the "
           f"worst adjacent pair is under 2 deg ({_m_raw[0]:.2f})",
           _m_raw[0] < 2.0)
check_true("...and the blur leaves it smoother still, never rougher",
           _m_ship[0] <= _m_raw[0])
check_true("...well under the 10 deg the frame needs", _m_ship[0] < 10.0)
# FIXTURE 2 — THE HAIRPIN, where the axis doubles back INSIDE one wide polygon:
# the medial axis really does run through the water, and this is the case the
# blur exists for. The two legs are 146 deg apart where they meet.
_u_raw, _u_ship, _u_len = _flow_angles(UMODEL, 70, 125, 81, 34)
print(f"    hairpin: raw worst {_u_raw[0]:.2f} deg (p99 {_u_raw[1]:.2f}, mean "
      f"{_u_raw[2]:.2f}) -> shipped worst {_u_ship[0]:.2f} deg "
      f"(p99 {_u_ship[1]:.2f}, mean {_u_ship[2]:.2f}); "
      f"|flow| {_u_len[0]:.4f}..{_u_len[1]:.4f}")
check_true("the hairpin's RAW field really does jump — over 100 deg between "
           f"two lattice points 2 m apart ({_u_raw[0]:.2f})", _u_raw[0] > 100.0)
check_true("...and the blur more than halves it "
           f"({_u_raw[0]:.2f} -> {_u_ship[0]:.2f} deg)",
           _u_ship[0] < 0.55 * _u_raw[0])
check_true("...the mean falls with it", _u_ship[2] < _u_raw[2])
# NOT RE-NORMALISED: the shortening IS the answer where two directions really
# disagree, and it never reaches the still-water floor (1e-4) that would turn a
# river into a lake.
check_true(f"the shortest shipped vector is {_u_len[0]:.4f}, far above the "
           "1e-4 still floor", _u_len[0] > 1e-3)
check_true("...and no vector was lengthened past 1", _u_len[1] <= 1.0 + 1e-12)
# STILL WATER STAYS EXACTLY STILL — a box over zeros is zero, which is what
# keeps `water_raster_payload` able to drop the flow arrays entirely.
check("a still lake's blurred flow is exactly (0, 0)",
      [_wet_tile["water"].get("flow_x"), _wet_tile["water"].get("flow_z")],
      [None, None])
# THE FIELD DOES NOT DIVERGE ACROSS A RIVER (finding G2, 2026-08-25: "the
# authored 1 m/s moves, but in different directions within the river"). The
# adjacent-pair numbers above bound the ROUGHNESS of the field; this bounds its
# SPREAD — the worst angle between ANY two in-river texels of one window, which
# is what a viewer sees at a glance.
#
# BY HAND: a straight stroke has ONE segment, `_flow_from` finds no interior
# knot window to ease in, and every point of the ribbon takes that segment's own
# unit tangent — so the raw field is one constant vector and the box blur of a
# constant is that constant. The spread is EXACTLY 0 deg, axis-aligned or not.
# The meander's spread is its own shape: the sine turns +-31 deg over the drawn
# line, so the field must turn with it; ACROSS the ribbon at one station it must
# not, and a 4 m blur over a ribbon 8 m wide is what keeps that under a degree.
def _flow_spread(model, i0, j0, cols, rows, step=2.0):
    """Worst angle in degrees between ANY two in-river texels of one window."""
    lvl, fx, fz, sd, _kinds, _kidx = model.water_raster(
        i0 * step, j0 * step, step, cols, rows)
    vecs = [(fx[j][i], fz[j][i]) for j in range(rows) for i in range(cols)
            if sd[j][i] is not None and sd[j][i] >= 0
            and math.hypot(fx[j][i], fz[j][i]) > 1e-9]
    worst = 0.0
    for a in range(len(vecs)):
        for b in range(a + 1, len(vecs)):
            u, v = vecs[a], vecs[b]
            dot = ((u[0] * v[0] + u[1] * v[1])
                   / (math.hypot(*u) * math.hypot(*v)))
            worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, dot)))))
    return worst, len(vecs)


def _cross_spread(model, i0, j0, cols, rows, columns, step=2.0):
    """Worst angle across the ribbon at each of `columns` — the same measure
    taken along ONE cross-section, where a river may not turn at all."""
    lvl, fx, fz, sd, _kinds, _kidx = model.water_raster(
        i0 * step, j0 * step, step, cols, rows)
    worst = 0.0
    for i in columns:
        col = [(fx[j][i], fz[j][i]) for j in range(rows)
               if sd[j][i] is not None and sd[j][i] >= 0
               and math.hypot(fx[j][i], fz[j][i]) > 1e-9]
        for a in range(len(col)):
            for b in range(a + 1, len(col)):
                u, v = col[a], col[b]
                dot = ((u[0] * v[0] + u[1] * v[1])
                       / (math.hypot(*u) * math.hypot(*v)))
                worst = max(worst,
                            math.degrees(math.acos(max(-1.0, min(1.0, dot)))))
    return worst


_STRAIGHT = {"id": "ta_straight", "kind": "river", "z_order": 0,
             "polygon": [[20, 96], [180, 96], [180, 104], [20, 104]],
             "meta": {"flow_along": "forward",
                      "stroke": {"points": [[20, 100], [180, 100]],
                                 "width_m": 8.0}}}
_SMODEL = hf.build_model([_MBOWL], [], [_STRAIGHT], CATALOG_R)
_s_spread, _s_n = _flow_spread(_SMODEL, 10, 42, 81, 17)
print(f"    straight river: {_s_n} in-river texels, worst pair {_s_spread:.3f} deg")
check("a STRAIGHT river's shipped flow points ONE way over its whole length",
      round(_s_spread, 9), 0.0)
check_true("...measured over a real number of texels", _s_n > 300)
_DIAG = {"id": "ta_diag", "kind": "river", "z_order": 0,
         "polygon": ([list(p) for p in _offset([(30.0, 30.0), (170.0, 170.0)], 4.0)]
                     + [list(p) for p in reversed(
                         _offset([(30.0, 30.0), (170.0, 170.0)], -4.0))]),
         "meta": {"flow_along": "forward",
                  "stroke": {"points": [[30, 30], [170, 170]], "width_m": 8.0}}}
_DMODEL = hf.build_model([_MBOWL], [], [_DIAG], CATALOG_R)
_d_spread, _d_n = _flow_spread(_DMODEL, 10, 10, 81, 81)
print(f"    diagonal river: {_d_n} in-river texels, worst pair {_d_spread:.3f} deg")
# A MILLIONTH OF A DEGREE, and it is float noise and not a bend: the diagonal
# ribbon is built by offsetting the line numerically, so its two tangents differ
# in the last bits. Anything a viewer could see would be orders of magnitude up.
check_true("...and a DIAGONAL one too — the blur cannot bend a constant field "
           f"({_d_spread:.2e} deg)", _d_spread < 1e-5)
# ACROSS the meander's own width the field is coherent; ALONG it, it turns with
# the drawn line, which is the river and not a defect.
_m_cross = _cross_spread(_MMODEL, 25, 15, 71, 41, (30, 40, 50))
_m_spread, _m_n = _flow_spread(_MMODEL, 25, 15, 71, 41)
print(f"    meander: worst pair {_m_spread:.3f} deg over the whole window, "
      f"{_m_cross:.3f} deg ACROSS the ribbon")
check_true("the meander's flow turns only ALONG its own line — across the "
           f"ribbon the spread is under a degree ({_m_cross:.3f})",
           _m_cross < 1.0)
check_true("...while along it the field follows the drawn sine, +-31 deg, so "
           f"the window spread is the river's own shape ({_m_spread:.2f})",
           30.0 < _m_spread < 70.0)

# SEAMLESS ACROSS TILE BORDERS: the window is sampled with a margin and cropped,
# so one lattice point read from two different windows is ONE number (§ G1).
# The probe is ON the meander's axis (x = 136, z = 76, a wet lattice point) and
# lands on the LAST column of one window and the FIRST of the next.
_wa = _MMODEL.water_raster(98.0, 58.0, 2.0, 20, 20)
_wb = _MMODEL.water_raster(136.0, 58.0, 2.0, 20, 20)
check_true("...and the probe really is wet", _wa[0][9][19] is not None)
check_true("...and really flowing", math.hypot(_wa[1][9][19], _wa[2][9][19]) > 0.5)
check("the same point read from two WINDOWS is the same blurred vector",
      [round(_wa[1][9][19], 9), round(_wa[2][9][19], 9)],
      [round(_wb[1][9][0], 9), round(_wb[2][9][0], 9)])


# ── [12i] THE KIND CHANNEL (bake v10, finding F-A second half) ──────────
#
# WHAT IT ANSWERS. v9 gave the renderer a field that says WHETHER a pixel is
# inside painted water (`sd`). It still left WHICH water to the ground
# compositor's id mask — a pair (topmost painted kind, the one under it). That
# pair is a statement about the GROUND, and every look a water has (tint,
# wave_m, speed, flow_speed, opaque depth) is a property of its KIND. Wherever
# the water is not the topmost PAINTED kind the pair names no water at all and
# the pixel drew with somebody else's numbers: the wrong tint, the wrong opaque
# depth (rim transparency working in some spots and not in others) and the wrong
# flow_speed (a river drifting at a lake's dial, or standing still).
#
# THE RULE, and every number below follows from it:
#
#   kind(p) = the painted kind of the TOPMOST water covering p — the same
#             "topmost water wins" that already picks `level` and `sd`, so all
#             five channels of one texel come from ONE water.
#   kinds   = that window's own palette, in the order the kinds are first met
#             scanning the CROPPED window row by row (z ascending, then x).
#   kind_idx[j][i] = the index into it; 0 and MEANINGLESS where `level` is None.
print("\n[12i] the raster names its own KIND per texel (bake v10)")

# THE TWO-KIND FIXTURE. A lake and a river that OVERLAP, with the river painted
# later, so the "topmost wins" tie-break is exercised inside one window.
#
#   lake  : the square (-1,-1)-(21,21), kind "lake",  painted first
#   river : the box   (15,9)-(59,13),   kind "river", painted second
#
# Both outlines are deliberately at ODD coordinates so no even lattice point of
# the window ever lands ON an outline and no answer depends on the ray-cast
# tie-break at a boundary.
_K_LAKE = {"id": "ta_k_lake", "kind": "lake", "z_order": 0,
           "polygon": [[-1, -1], [21, -1], [21, 21], [-1, 21]],
           "meta": {"water_level": 1.0}}
_K_RIVER = {"id": "ta_k_river", "kind": "river", "z_order": 1,
            "polygon": [[15, 9], [59, 9], [59, 13], [15, 13]],
            "meta": {"water_level": 1.0}}
_KMODEL = hf.build_model([], [], [_K_LAKE, _K_RIVER], CATALOG_R)
# WINDOW: origin (0,0), step 2, 31 x 11 points — x = 0,2,…,60 and z = 0,2,…,20.
_KW = _KMODEL.water_raster(0.0, 0.0, 2.0, 31, 11)
_k_level, _k_fx, _k_fz, _k_sd, _k_kinds, _k_idx = _KW
# BY HAND, the palette. Scanning j = 0 (z = 0) first: x = 0…20 lie inside the
# lake (its outline runs to 21), so the FIRST kind met is "lake". The river is
# first met at j = 5 (z = 10), i = 8 (x = 16) — the first lattice point inside
# its outline, and inside the lake's as well, where the later paint wins.
check("the window's palette is its own two kinds, in first-met order",
      _k_kinds, ["lake", "river"])
check("mid-lake (10, 10) — lattice (5, 5) — is the lake",
      _k_kinds[_k_idx[5][5]], "lake")
check("mid-river (40, 10) — lattice (20, 5) — is the river",
      _k_kinds[_k_idx[5][20]], "river")
# THE OVERLAP, and it is the same tie-break the level takes: (16, 10) lies
# inside BOTH outlines and the river was painted later.
check_true("(16, 10) really is inside both outlines",
           hf._inside_ring(16.0, 10.0, [(-1.0, -1.0), (21.0, -1.0),
                                        (21.0, 21.0), (-1.0, 21.0)])
           and hf._inside_ring(16.0, 10.0, [(15.0, 9.0), (59.0, 9.0),
                                            (59.0, 13.0), (15.0, 13.0)]))
check("...and the TOPMOST water wins the kind, exactly as it wins the level",
      _k_kinds[_k_idx[5][8]], "river")
# THE WHOLE ROW z = 10, by hand: x = 0…14 are lake only (8 texels, i = 0…7),
# x = 16…58 are river (inside), and x = 60 is 1 m past the river's east rim,
# i.e. in its DILATION ring, which carries the ring water's kind like every
# other channel. 8 zeros, then 23 ones.
check("the row z = 10 is 8 lake texels and then 23 river ones",
      _k_idx[5], [0] * 8 + [1] * 23)
# THE RING BELONGS TO THE WATER THAT WROTE IT. At (22, 14) neither outline
# contains the point: it is 1 m outside the lake's east rim AND 1 m outside the
# river's north rim, and the second pass walks the candidates topmost-first.
check_true("(22, 14) is inside neither outline",
           _KMODEL.water_at(22.0, 14.0) is not None
           and _KMODEL.water_at(22.0, 14.0)[3] < 0)
check("...so its ring texel carries the topmost water's kind — the river",
      _k_kinds[_k_idx[7][11]], "river")
# DRY TEXELS INDEX 0 AND MEAN NOTHING — the level is the mask, and it is the
# only mask this raster has. (26, 0) is 5 m past the lake and 9 m from the
# river: outside both dilations.
check("a dry texel is null in `level`", _k_level[0][13], None)
check("...and its kind index is a plain 0, not a second sentinel",
      _k_idx[0][13], 0)
# THE PALETTE IS THE WINDOW'S, NOT THE WORLD'S: a window over the lake alone
# names one kind, however many waters the world holds.
_KW_LAKE = _KMODEL.water_raster(0.0, 0.0, 2.0, 5, 4)
check("a window that only touches the lake ships a ONE-entry palette",
      _KW_LAKE[4], ["lake"])
check("...and its grid indexes that one entry", _KW_LAKE[5][0], [0] * 5)

print("\n[12j] THE CONVICTION — a river through a forest painted over it")
# THE USER'S CASE, 2026-08-25: "lake AND river show patches that look like
# forest floor, and at the river the flow direction reads wrong". A generated
# map paints a wood over the whole valley and draws the river into it; whichever
# was painted LAST is the topmost PAINTED kind, and that is the only thing the
# id mask could report.
#
#   forest : the box (-1,-1)-(121,81), kind "g", painted LAST (topmost)
#   river  : the box (15,37)-(105,43), kind "river", painted first
_FA_RIVER = {"id": "ta_fa_river", "kind": "river", "z_order": 0,
             "polygon": [[15, 37], [105, 37], [105, 43], [15, 43]],
             "meta": {"water_level": 1.0, "flow_dir_deg": 90.0}}
_FA_FOREST = {"id": "ta_fa_forest", "kind": "g", "z_order": 9,
              "polygon": [[-1, -1], [121, -1], [121, 81], [-1, 81]],
              "meta": {}}
_FA_AREAS = [_FA_RIVER, _FA_FOREST]
_FAMODEL = hf.build_model([], [], _FA_AREAS, CATALOG_R)
# THE RED PROBE, measured on the very mechanism that was asked: the ground
# compositor's own model. At mid-river the TOPMOST PAINTED kind is the forest,
# and the forest layer is not water — so the id pair the fragment fetched there
# was (forest, forest), both halves failed `is_water`, and the pick fell to the
# stand-in row: the world's PRIMARY water, with a lake's tint, a lake's opaque
# depth and a lake's flow_speed.
_FA_LM = TL2.LayerModel(_FA_AREAS, CATALOG_R, "meadow")
_FA_TOP = _FA_LM.layer_at(60.0, 40.0)
_FA_TOP_ROW = _FA_LM.layers[_FA_TOP]
_FA_RIVER_ROW = next(e for e in _FA_LM.layers if e["kind"] == "river")
print(f"    mid-river (60, 40): id pair ({_FA_TOP}, {_FA_TOP}) = "
      f"({_FA_TOP_ROW['kind']}, {_FA_TOP_ROW['kind']}); the river's own layer "
      f"is {_FA_RIVER_ROW['index']}")
check("RED: the topmost PAINTED kind at mid-river is the forest, not the water",
      _FA_TOP_ROW["kind"], "g")
check("RED: ...and that layer is not water, so BOTH halves of the id pair fail "
      "the `is_water` test the fragment picked its row with",
      _FA_TOP_ROW["water"], False)
check_true("RED: ...while the river's own layer exists and IS water — the mask "
           "simply never names it here",
           _FA_RIVER_ROW["water"] is True
           and _FA_RIVER_ROW["index"] != _FA_TOP_ROW["index"])
# THE FIX, on the same point: the water field names the river, because the water
# field is built from the WATER stamps and a forest is not one.
check("the water raster names the RIVER at mid-river, whatever is painted over "
      "it", _FAMODEL.water_at(60.0, 40.0)[4], "river")
_FAW = _FAMODEL.water_raster(0.0, 30.0, 2.0, 61, 11)
check("...the window's palette holds exactly that one water", _FAW[4], ["river"])
check("...and every WET texel of the window indexes it",
      sorted({_FAW[5][_j][_i] for _j in range(11) for _i in range(61)
              if _FAW[0][_j][_i] is not None}), [0])
# The forest is painted over the whole window, so the id mask names it at EVERY
# one of those texels — which is the measure of how much of the river the old
# rule got wrong: all of it.
check("RED: the id mask names the forest at every wet texel of that window — "
      "the whole river drew with the wrong water",
      sorted({_FA_LM.layer_at(_i * 2.0, 30.0 + _j * 2.0)
              for _j in range(11) for _i in range(61)
              if _FAW[0][_j][_i] is not None}), [_FA_TOP])

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
for name in FAILURES:
    print(f"  FAILED: {name}")
sys.exit(1 if FAILURES else 0)
