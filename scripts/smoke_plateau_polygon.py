#!/usr/bin/env python3
"""Smoke run for the AUTO-PLATEAU ON A CONCAVE OUTLINE (§ G5, Ein Boden).

Throwaway storage, no server, no real world. Every number below is derived BY
HAND in this header from the rules, never recorded from the current output.

WHAT THIS SCRIPT IS FOR
-----------------------
``scripts/smoke_height_bake.py`` proves the pure height function on a SQUARE
plot. This one keeps the POLYGON half honest — a concave L, whose notch, whose
own anchor and whose median are all places a "the footprint is a box" mistake
shows up immediately.

WHAT CHANGED WITH "EIN BODEN" E1
--------------------------------
A built location no longer asks to be levelled (``level_ground`` is gone) and
the stamp is no longer a raster operation:

    who stamps   every location that draws a BUILT floor — a ``map3d.outline``
                 or at least one CLOSED room. Nothing else, no flag.
    how high     the MEDIAN of the natural ground over the footprint, sampled
                 on the 2 m world lattice (it was a single interior probe)
    how wide     a smoothstep ramp of w = clamp(0.5·sqrt(area/pi), 2, 8) METRES
                 OUTSIDE the outline (it was "one grid cell", i.e. 2 m on a
                 tile and up to 32 m on a coarsened overview — the "zwei
                 Böden" bug), widened where the rim step would exceed 35°
    what it is   h = h0 + (h_before − h0)·smoothstep(d/w),  d = polygon
                 distance in the location's own LOCAL frame; d = 0 inside

THE FIXTURE
-----------
ONE height area, chosen so the landscape is a clean plane over the region of
interest:

    SLOPE   square (0,0)-(200,200), height_m 20, falloff_m 200

    h_area(p) = 20 · min(x, z, 200−x, 200−z) / 200

Everything below lives in x ∈ [6, 22], z ∈ [64, 76], where the west edge is
always the nearest one, so

    TERRAIN(x, z) = 20 · x / 200 = x / 10           (independent of z)

ONE built location, an L, anchored at the pin (8, 66) with yaw 0 and the
boundary in LOCAL metres

    (0,0) (8,0) (8,4) (4,4) (4,8) (0,8)        clockwise, area 8·4 + 4·4 = 48

so in WORLD metres it covers the wide arm x ∈ [8,16] × z ∈ [66,70] plus the
north arm x ∈ [8,12] × z ∈ [70,74]. The NOTCH — local x ∈ [4,8], z ∈ [4,8],
world x ∈ [12,16], z ∈ [70,74] — is OUTSIDE the location.

The raster is ONE tile, ``rasterize_tile(0, 0, …)``: origin (0,0), 129 × 129
support points at the 2 m tile step, so the world point (x, z) is the stored
index (i, j) = (x/2, z/2).

THE HAND-DERIVED NUMBERS
------------------------
1) THE TARGET HEIGHT is the MEDIAN over the 2 m world lattice inside the
   outline. The footprint box is (8,66)-(16,74), so the candidate lattice
   points are local (lx, lz) with lx, lz ∈ {0, 2, 4, 6, 8}; those with
   ``polygon_distance == 0`` (inside OR on the outline) are

     lz = 0   lx = 0,2,4,6,8    (the whole south edge)      5 points
     lz = 2   lx = 0,2,4,6,8    (inside the wide arm)       5
     lz = 4   lx = 0,2,4,6,8    (interior + the edge z=4)   5
     lz = 6   lx = 0,2,4        (lx = 6, 8 are 2 and 4 m out)   3
     lz = 8   lx = 0,2,4        (the north edge)            3
                                                           = 21 samples

   with TERRAIN = (lx + 8)/10, i.e. the multiset

     0.8 ×5,  1.0 ×5,  1.2 ×5,  1.4 ×3,  1.6 ×3

   The median of 21 values is the 11th; the cumulative count is 5, 10, 15, so
   the 11th is

     h0 = 1.2                       (and the tile stores exactly 1.2)

   TWO OLDER ANSWERS ARE WRONG NOW, and both are asserted absent:
     * the PIN would say TERRAIN(8) = 0.8 — an L may leave its own anchor
       outside itself, which is why the pin was never the probe;
     * the INTERIOR POINT (the centroid (10/3, 10/3), world x = 34/3) would
       say 34/30 = 1.1333… — the pre-E1 rule. A single probe is decided by
       whatever one square metre happens to do; the median has to be outvoted
       by half the plot.

2) THE RAMP WIDTH. area = 48 m², so
     0.5·sqrt(48/pi) = 0.5·3.908820… = 1.954410… m
   which is UNDER the 2 m floor, so w = 2.0 m exactly.
   SLOPE CAP: the rim is sampled every 2 m (perimeter 32 m -> 16 samples) and
   carries TERRAIN(x) for x ∈ {8, 10, 12, 14, 16}, so the biggest rim step is
   |1.2 − 1.6| = |1.2 − 0.8| = 0.4 m. tan(35°)·2.0 = 1.400415… m > 0.4, so the
   width is NOT widened.

3) (a) INSIDE: world (14, 68) = local (6, 2), d = 0 -> 1.2, where the
   untouched landscape carries TERRAIN(14) = 1.4.

4) (b) THE NOTCH: world (16, 74) = local (8, 8). The nearest outline points
   are the corner (8,4) — hypot(0,4) = 4 — and the edges x = 4 and z = 4, both
   4 m away, so d = 4 > w: untouched, TERRAIN(16) = 1.6. Had the pass treated
   the outline as its BOUNDING BOX this point would be 1.2.

   The ramp DOES reach into the notch:
     world (14, 72) = local (6, 6), d = 2 = w exactly
        -> smoothstep(1) = 1 -> the landscape again, TERRAIN(14) = 1.4
     world (13, 71) = local (5, 5), d = 1
        -> t = 0.5, smoothstep = 0.25·(3−1) = 0.5
        -> 1.2 + (TERRAIN(13) − 1.2)·0.5 = 1.2 + 0.1·0.5 = 1.25
   RED COUNTER-PROBE: the OLD one-cell ring PINNED (14,72) to the plateau —
   d = 2 ≤ one cell — so it read 1.133 there. It is 1.4 now.

5) (c) THE RAMP east of the wide arm, along z = 68 (local z = 2, so the row is
   a lattice row and no z mixing is involved). d = local x − 8:

     x = 16     d = 0     -> 1.2
     x = 16.5   d = 0.5   -> t = 0.25, ss = 0.0625·2.5 = 0.15625
                             1.2 + (1.65−1.2)·0.15625 = 1.2703125
     x = 17     d = 1     -> t = 0.5, ss = 0.5
                             1.2 + (1.70−1.2)·0.5 = 1.45
     x = 17.5   d = 1.5   -> t = 0.75, ss = 0.5625·1.5 = 0.84375
                             1.2 + (1.75−1.2)·0.84375 = 1.6640625
     x = 18     d = 2 = w -> TERRAIN(18) = 1.8
     x = 20     d = 4     -> TERRAIN(20) = 2.0

   RED COUNTER-PROBE: the OLD ring pinned x = 18 to the plateau (1.133) and,
   on a 4 m overview, x = 20 as well — two rasters, two landscapes. Now the
   whole ramp is 2 m wide whoever asks.

   THE STORED TILE IS A SAMPLING OF THAT, not a second opinion: it carries the
   lattice points 1.2 (x=16) and 1.8 (x=18), and ``sample_height`` mixes them
   linearly, so the tile answers 1.5 at x = 17 where the function itself says
   1.45. That 0.05 m is the tile's own mip error, and it is checked here so
   the difference is on the record rather than a surprise.

6) (d) WHO STAMPS AT ALL. ``placed_footprints`` hands out a location with a
   CLOSED room (or a drawn ``map3d.outline``) and no other. The same L with
   only an ``always_visible`` zone is a natural place and stamps nothing —
   and the dead ``level_ground`` flag changes neither answer.

7) (e) THE SIGNATURE hashes the polygon POINTS. ``placed_footprints`` rounds
   to the centimetre, so moving the boundary point (8,4) to (8.01,4) — one
   centimetre, the location itself standing perfectly still — must change
   ``height_sig``.

8) A DRAWN SQUARE is a polygon like any other; a location that carries only
   the legacy ``plan_width_m`` dial has NO area since 2026-08-19 and is no
   input at all (the map editor's "Seed missing boundaries" turns such a dial
   into a real outline).

INJECTION POINTS — no world DB is queried for the geometry. It runs on
``rasterize_tile``/``build_model``, which are pure and take literals. The
signature half patches ``app.models.world.list_locations`` with PLAIN DICT
locations, so the real ``placed_footprints`` runs over them.

Usage:  ./.venv/bin/python scripts/smoke_plateau_polygon.py
"""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="plateau-polygon-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="plateau-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import heightfield as hf  # noqa: E402
from app.core.world_geometry import (effective_boundary,  # noqa: E402
                                     local_to_world, polygon_area,
                                     polygon_distance,
                                     polygon_interior_point)
from app.models import heightfield as store  # noqa: E402
from app.models import world as world_store  # noqa: E402

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
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


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


def square(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


# ── The fixture ────────────────────────────────────────────────────────

SLOPE = {"id": "slope", "polygon": square(0, 0, 200, 200),
         "height_m": 20.0, "falloff_m": 200.0}

L_LOCAL = [[0, 0], [8, 0], [8, 4], [4, 4], [4, 8], [0, 8]]
PIN_X, PIN_Z = 8.0, 66.0
L_FP = (PIN_X, PIN_Z, 0.0, [(0.0, 0.0), (8.0, 0.0), (8.0, 4.0),
                            (4.0, 4.0), (4.0, 8.0), (0.0, 8.0)])

STEP = hf.TILE_STEP_M                    # 2 m — the tile lattice
H0 = 1.2                                 # the MEDIAN target, exactly
W = 2.0                                  # the ramp width, exactly (clamped up)
OLD_H0 = round(34.0 / 30.0, 3)           # 1.133 — the pre-E1 interior probe


def terrain(x):
    """The authored landscape of this fixture, by hand: x / 10."""
    return x / 10.0


def ss(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def idx(x, z):
    """The stored index of a world point on tile (0, 0)."""
    return (int(x / STEP), int(z / STEP))


def at(tile, x, z):
    i, j = idx(x, z)
    return tile["heights"][j][i]


PLAIN = hf.rasterize_tile(0, 0, [SLOPE], footprints=())
MODEL = hf.build_model([SLOPE], [L_FP])
TILE = hf.rasterize_tile(0, 0, (), model=MODEL)

print("[1] the landscape under the L is the plane x / 10")
check("the tile is 129 x 129 at the 2 m step",
      (TILE["rows"], TILE["cols"], TILE["step_m"]), (129, 129, 2.0))
for _x in (8, 10, 12, 14, 16, 18, 20, 22):
    near(f"TERRAIN({_x}) without any place", at(PLAIN, _x, 68), terrain(_x))
near("...and it does not depend on z", at(PLAIN, 14, 74), terrain(14))

print("\n[2] the target height is the MEDIAN over the footprint")
check("the L encloses 48 m²", polygon_area(L_FP[3]), 48.0)
_inside = [(lx, lz) for lz in (0, 2, 4, 6, 8) for lx in (0, 2, 4, 6, 8)
           if polygon_distance(float(lx), float(lz), L_FP[3]) <= 0.0]
check("21 of the 25 lattice points of the box are inside or on the outline",
      len(_inside), 21)
check("...the four that are not are the notch corners",
      sorted(set((lx, lz) for lz in (0, 2, 4, 6, 8) for lx in (0, 2, 4, 6, 8))
             - set(_inside)), [(6, 6), (6, 8), (8, 6), (8, 8)])
_samples = sorted(terrain(8 + lx) for lx, _lz in _inside)
check("their heights are 0.8×5, 1.0×5, 1.2×5, 1.4×3, 1.6×3",
      [round(v, 1) for v in _samples],
      [0.8] * 5 + [1.0] * 5 + [1.2] * 5 + [1.4] * 3 + [1.6] * 3)
near("...so the 11th, the median, is 1.2", _samples[10], H0)
near("the stamp really carries it", MODEL.plateaus[0][5], H0, 1e-12)
check_not("RED COUNTER-PROBE: the PIN would have said TERRAIN(8) = 0.8",
          round(MODEL.plateaus[0][5], 3), 0.8)
near("...and the pin really sits that low in the landscape",
     at(PLAIN, PIN_X, PIN_Z), 0.8)
_inner = polygon_interior_point(L_FP[3])
near("the interior point (the pre-E1 probe, now a fallback) is (10/3,10/3)",
     _inner[0], 10.0 / 3.0, 1e-12)
_inner_world = local_to_world(_inner[0], _inner[1], PIN_X, PIN_Z, 0.0)
near("...its world x is 34/3", _inner_world[0], 34.0 / 3.0, 1e-12)
near("...where the landscape is 34/30", MODEL.natural(_inner_world[0],
                                                      _inner_world[1]),
     34.0 / 30.0, 1e-12)
check_not("RED COUNTER-PROBE: that single probe (1.133) is NOT the target",
          round(MODEL.plateaus[0][5], 3), OLD_H0)

print("\n[2b] the ramp width is 2 m — the floor of the clamp")
near("0.5·sqrt(48/pi) = 1.95441…", 0.5 * math.sqrt(48.0 / math.pi),
     1.9544100476116797, 1e-12)
check("...which is under the 2 m floor",
      0.5 * math.sqrt(48.0 / math.pi) < hf.PLATEAU_RAMP_MIN_M, True)
near("so the stamp's width is exactly 2.0", MODEL.plateaus[0][6], W, 1e-12)
near("the biggest rim step is |1.2 − 1.6| = 0.4",
     max(abs(H0 - terrain(x)) for x in (8, 10, 12, 14, 16)), 0.4, 1e-12)
check("...well under tan(35°)·2 m = 1.4004…, so no widening",
      0.4 < math.tan(math.radians(35.0)) * W, True)

print("\n[3] (a) a point inside the wide arm IS the plateau")
near("d(local (6,2)) = 0 — inside", polygon_distance(6.0, 2.0, L_FP[3]), 0.0)
near("(14, 68) is stamped to 1.2", at(TILE, 14, 68), H0)
near("...where the untouched landscape had 1.4", at(PLAIN, 14, 68),
     terrain(14))
near("(10, 68) too — local (2, 2)", at(TILE, 10, 68), H0)
near("(10, 72) in the north arm — local (2, 6)", at(TILE, 10, 72), H0)
check("...and the plot is EXACTLY flat over all 21 lattice points",
      sorted(set(round(MODEL.final(8.0 + lx, 66.0 + lz), 12)
                 for lx, lz in _inside)), [H0])

print("\n[4] (b) the notch keeps the pure landscape")
near("d(local (8,8)) = 4 — the corner (8,4) is the nearest outline point",
     polygon_distance(8.0, 8.0, L_FP[3]), 4.0)
near("(16, 74) is TERRAIN(16) = 1.6, no stamp and no ramp bleed",
     at(TILE, 16, 74), terrain(16))
check("...exactly the value the place-less raster carries",
      at(TILE, 16, 74), at(PLAIN, 16, 74))
check_not("RED COUNTER-PROBE: a BOUNDING-BOX plateau would have put 1.2 here",
          at(TILE, 16, 74), H0)
near("the ramp DOES reach into the notch: d(local (6,6)) = 2 = w",
     polygon_distance(6.0, 6.0, L_FP[3]), 2.0)
near("...and at d = w the landscape is back: (14,72) = 1.4",
     at(TILE, 14, 72), terrain(14))
check_not("RED COUNTER-PROBE: the OLD one-cell ring pinned it to 1.133",
          round(at(TILE, 14, 72), 3), OLD_H0)
near("halfway in, (13,71) — d = 1 -> 1.2 + 0.1·smoothstep(0.5)",
     MODEL.final(13.0, 71.0), 1.25, 1e-12)

print("\n[5] (c) the ramp east of the wide arm, along z = 68")
near("(16, 68) — ON the outline, d = 0", polygon_distance(8.0, 2.0, L_FP[3]),
     0.0)
near("...stamped", at(TILE, 16, 68), H0)
for _x, _d, _want in ((16.5, 0.5, 1.2 + 0.45 * ss(0.25)),
                      (17.0, 1.0, 1.45),
                      (17.5, 1.5, 1.2 + 0.55 * ss(0.75)),
                      (18.0, 2.0, terrain(18.0))):
    near(f"({_x}, 68) — d = {_d} -> {_want}", MODEL.final(_x, 68.0), _want,
         1e-12)
near("...(16.5,68) is 1.2703125", MODEL.final(16.5, 68.0), 1.2703125, 1e-12)
near("...(17.5,68) is 1.6640625", MODEL.final(17.5, 68.0), 1.6640625, 1e-12)
near("(20, 68) — d = 4, untouched", at(TILE, 20, 68), terrain(20))
check_not("RED COUNTER-PROBE: the OLD ring pinned (18,68) to the plateau",
          round(at(TILE, 18, 68), 3), OLD_H0)

print("\n[5b] the TILE is a sampling of that function, and says so")
near("the tile carries 1.2 at x = 16 and 1.8 at x = 18",
     at(TILE, 16, 68) + at(TILE, 18, 68), 3.0, 1e-12)
near("...so sample_height at x = 17 mixes them to 1.5",
     hf.sample_height(TILE, 17.0, 68.0), 1.5, 1e-12)
near("...while the function itself says 1.45", MODEL.final(17.0, 68.0), 1.45,
     1e-12)
near("...a 0.05 m sampling error, which is what the mip pyramid measures",
     abs(hf.sample_height(TILE, 17.0, 68.0) - MODEL.final(17.0, 68.0)), 0.05,
     1e-12)

print("\n[6] (d) only a BUILT location stamps")

BOUNDARY = [[0, 0], [8, 0], [8, 4], [4, 4], [4, 8], [0, 8]]


def as_location(boundary, rooms=None, **extra):
    """A PLAIN DICT location — the injection point of the signature half.

    The pin is the L's, so the boundary points ARE the local metres above.
    """
    loc = {"id": "l_shape", "name": "L", "pos_x": PIN_X, "pos_z": PIN_Z,
           "yaw_deg": 0.0, "map3d": {"boundary": boundary},
           "rooms": [{"id": "r1", "layout": {}}] if rooms is None else rooms}
    loc.update(extra)
    return loc


def with_locations(locs):
    world_store.list_locations = lambda: list(locs)


with_locations([as_location(BOUNDARY)])
check("a CLOSED room makes the place built — the polygon comes out",
      store.placed_footprints(), [L_FP])
with_locations([as_location(BOUNDARY, rooms=[{"id": "r1",
                                              "layout": {"always_visible":
                                                         True}}])])
check("only an OPEN zone: natural, no stamp", store.placed_footprints(), [])
with_locations([as_location(BOUNDARY, rooms=[{"id": "r1",
                                              "layout": {"always_visible":
                                                         True}},
                                             {"id": "r2", "layout": {}}])])
check("...one closed room among open ones is enough",
      store.placed_footprints(), [L_FP])
with_locations([as_location(BOUNDARY, rooms=[], level_ground=True)])
check("RED COUNTER-PROBE: the dead level_ground flag stamps nothing",
      store.placed_footprints(), [])

print("\n[7] (e) height_sig hashes the polygon points")
with_locations([as_location(BOUNDARY)])
_sig = store.height_sig()

_moved = [list(p) for p in BOUNDARY]
_moved[2] = [8.01, 4]
with_locations([as_location(_moved)])
check("ONE boundary point moved by 1 cm — the place never moved",
      store.placed_footprints()[0][:3], L_FP[:3])
check("...but the outline is a different one", store.placed_footprints()[0][3],
      [(0.0, 0.0), (8.0, 0.0), (8.01, 4.0), (4.0, 4.0), (4.0, 8.0),
       (0.0, 8.0)])
check_not("...so the signature moved with it", store.height_sig(), _sig)

with_locations([as_location(BOUNDARY, rooms=[])])
check("a NATURAL location is no input at all", store.placed_footprints(), [])
check_not("...which is again a different signature", store.height_sig(), _sig)

with_locations([as_location(BOUNDARY)])
check("putting the room back restores the signature exactly",
      store.height_sig(), _sig)

print("\n[8] a DRAWN square gets its plateau — a bare width gets none")
# The square as an OUTLINE: the centred 8 m square, corners ±4. These are the
# very four corners the transition synthesis used to hand out for
# ``plan_width_m`` 8 — and since 2026-08-19 they only exist when somebody drew
# them (the map editor's "Seed missing boundaries" writes exactly this).
_square = {"id": "sq", "name": "Square", "pos_x": 40.0, "pos_z": 40.0,
           "yaw_deg": 0.0, "rooms": [{"id": "r1", "layout": {}}],
           "map3d": {"plan_width_m": 8.0,
                     "boundary": [[-4, -4], [4, -4], [4, 4], [-4, 4]]}}
check("effective_boundary hands out the drawn corners",
      effective_boundary(_square),
      (40.0, 40.0, 0.0, [(-4.0, -4.0), (4.0, -4.0), (4.0, 4.0), (-4.0, 4.0)]))
with_locations([_square])
check("...and placed_footprints passes them on",
      store.placed_footprints(),
      [(40.0, 40.0, 0.0, [(-4.0, -4.0), (4.0, -4.0), (4.0, 4.0),
                          (-4.0, 4.0)])])
# THE CLOSING CHECK: the same location WITHOUT the outline stamps nothing —
# it has no area, so the model never sees it, built or not.
_dial_only = {**_square, "map3d": {"plan_width_m": 8.0}}
check("a width dial alone is no plateau input",
      effective_boundary(_dial_only), None)
with_locations([_dial_only])
check("...and placed_footprints hands out nothing for it",
      store.placed_footprints(), [])

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
for name in FAILURES:
    print(f"  FAILED: {name}")
sys.exit(1 if FAILURES else 0)
