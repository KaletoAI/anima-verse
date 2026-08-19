#!/usr/bin/env python3
"""Smoke run for the PLATEAU AS A POLYGON DISTANCE FIELD (contract v6 no. 7).

Throwaway storage, no server, no real world. Every number below is derived BY
HAND in this header from the rules, never recorded from the current output.

WHAT CHANGED IN v6
------------------
A levelling location used to hand the raster a SQUARE ``(cx, cz, w, yaw)``.
It now hands it a POLYGON — ``(cx, cz, yaw_deg, boundary points in local
metres)``, straight out of ``world_geometry.effective_boundary`` — and the
plateau pass tests each raster point with ``polygon_distance`` in the
location's own local frame instead of with the box distance of a square:

    d == 0            inside the outline   -> pinned to the plateau height
    0 < d <= one cell the dilation ring    -> pinned as well (§ A16.1)
    d >  one cell     untouched landscape

THE PLATEAU HEIGHT is read at ``polygon_interior_point`` mapped through the
pin, NOT at the pin: a concave outline may leave its own anchor (and its own
centroid) outside itself, and the plateau would then stand at a height nobody
inside the place ever touches. The L below is exactly that case — its anchor
is a polygon CORNER.

OVERLAP is resolved by AREA now (v6 no. 6, "the smallest area wins"), because
a polygon has no single edge to compare; ``smoke_heightfield.py`` [14] keeps
that half honest with its four squares.

WHAT THE RAMP IS — READ THIS BEFORE EXPECTING A BLEND
-----------------------------------------------------
§ A16.1 builds the ramp out of the RASTER, not out of a per-point blend: the
footprint dilated by ONE CELL is pinned to the FULL plateau height, and the
ramp is the bilinear span between the outermost pinned lattice point and the
first untouched one. So a ring lattice point reads exactly the plateau, and
the linear plateau -> terrain interpolation is what ``sample_height`` returns
BETWEEN those two points. Case (c) below measures precisely that.

THE FIXTURE
-----------
ONE height area, chosen so the landscape is a clean plane over the whole
region of interest:

    SLOPE   square (0,0)-(200,200), height_m 20, falloff_m 200

    h_area(p) = 20 · min(1, d(p)/200)   with d = distance to the outline
              = 20 · min(x, z, 200−x, 200−z) / 200

Everything below lives in x ∈ [6, 22], z ∈ [64, 76], where the west edge is
always the nearest one (x < 60 ≤ z, 200−x, 200−z), so

    TERRAIN(x, z) = 20 · x / 200 = x / 10           (independent of z)

ONE levelling location, an L, anchored at the pin (8, 66) with yaw 0 and the
boundary in LOCAL metres

    (0,0) (8,0) (8,4) (4,4) (4,8) (0,8)        clockwise, area 8·4 + 4·4 = 48

so in WORLD metres it covers the wide arm x ∈ [8,16] × z ∈ [66,70] plus the
north arm x ∈ [8,12] × z ∈ [70,74]. The NOTCH — local x ∈ [4,8], z ∈ [4,8],
world x ∈ [12,16], z ∈ [70,74] — is OUTSIDE the location.

The raster is ONE tile, ``rasterize_tile(0, 0, …)``: origin (0,0), 129 × 129
support points at the 2 m tile step, so the world point (x, z) is the stored
index (i, j) = (x/2, z/2) and ONE CELL — the ramp width — is 2 m.

THE HAND-DERIVED NUMBERS
------------------------
1) THE INTERIOR POINT. The L's centroid, by the shoelace rule on the local
   points (cross_i = x_i·z_{i+1} − x_{i+1}·z_i):

     crosses  0, 32, 16, 16, 32, 0            Σ = 96, so the area is 48
     Σ (x_i + x_{i+1})·cross_i = 0 + 16·32 + 12·16 + 8·16 + 4·32 + 0 = 960
     Σ (z_i + z_{i+1})·cross_i = 0 +  4·32 +  8·16 + 12·16 + 16·32 + 0 = 960
     centroid = (960 / (6·48), 960 / (6·48)) = (10/3, 10/3) ≈ (3.333, 3.333)

   which lies INSIDE the L (both coordinates below 4), so
   ``polygon_interior_point`` returns it. In world metres:

     (8 + 10/3, 66 + 10/3) = (34/3, 208/3) ≈ (11.3333, 69.3333)

2) THE PLATEAU HEIGHT. ``plateau_height`` mixes the four lattice points of
   the enclosing 2 m cell bilinearly. The cell is x ∈ [10,12], z ∈ [68,70]
   (tx = tz = (34/3 − 10)/2 = 2/3); the kernel there is TERRAIN, which is
   linear in x, and bilinear interpolation reproduces a linear function
   exactly, so

     h0 = TERRAIN(34/3) = 34/30 = 17/15 = 1.13333…   ->  stored as 1.133

   THE PIN WOULD SAY SOMETHING ELSE: TERRAIN(8) = 0.8. That is the whole
   point of reading at an interior point, and the red counter-probe below
   asserts the plateau is NOT 0.8.

3) (a) INSIDE THE WIDE ARM: world (14, 68) = local (6, 2), inside the L, so
   distance 0 -> pinned. Stored index (7, 34) must be 1.133, where the
   untouched landscape would have been TERRAIN(14) = 1.4.

4) (b) THE NOTCH: world (16, 74) = local (8, 8). The nearest outline points
   are the corner (8,4) — hypot(0,4) = 4 — and the edges x = 4 (z ∈ [4,8])
   and z = 4 (x ∈ [4,8]), both 4 m away, so d = 4 > 2: NO plateau and NO ramp
   bleed. Stored index (8, 37) must be pure TERRAIN(16) = 1.6. Had the pass
   treated the outline as its BOUNDING BOX, this point would be 1.133 — the
   second red counter-probe.

   The ring DOES reach into the notch where it should: world (14, 72) =
   local (6, 6) is exactly 2 m from the edge x = 4 (and from z = 4), i.e.
   d = one cell -> pinned. Stored index (7, 36) = 1.133, not TERRAIN = 1.4.

5) (c) THE RAMP, east of the wide arm along the lattice row z = 68
   (local z = 2, so no z mixing at all — the row IS a lattice row):

     x = 16  local (8, 2)   ON the outline, d = 0    -> 1.133
     x = 18  local (10, 2)  d = 2 = one cell (ring)  -> 1.133
     x = 20  local (12, 2)  d = 4 > 2                -> TERRAIN(20) = 2.0

   so the ramp is the cell x ∈ [18, 20] and ``sample_height`` interpolates
   linearly across it between the two STORED values 1.133 and 2.0:

     x = 19    -> 1.133 + 0.50·(2.0 − 1.133) = 1.133 + 0.4335 = 1.5665
     x = 18.5  -> 1.133 + 0.25·(2.0 − 1.133) = 1.133 + 0.21675 = 1.34975
     x = 19.5  -> 1.133 + 0.75·(2.0 − 1.133) = 1.133 + 0.65025 = 1.78325

7) A DRAWN SQUARE is a polygon like any other; a location that carries only
   the legacy ``plan_width_m`` dial has NO area since 2026-08-19 and is no
   input of the plateau pass at all (the map editor's "Seed missing
   boundaries" is what turns such a dial into a real outline).

6) (d) THE SIGNATURE hashes the polygon POINTS. ``placed_footprints`` rounds
   to the centimetre, so moving the boundary point (8,4) to (8.01,4) — one
   centimetre, the location itself standing perfectly still — must change
   ``height_sig``. Redrawing an outline invalidates every client's raster
   exactly like moving the place used to.

INJECTION POINTS — no world DB is queried for any of this. The geometry runs
on ``rasterize_tile``, which is pure and takes literals. The signature half
patches ``app.models.world.list_locations`` with PLAIN DICT locations, so the
real ``placed_footprints`` runs over them; the empty throwaway world provides
only the (empty) height areas and terrain the signature also hashes.

Usage:  ./.venv/bin/python scripts/smoke_plateau_polygon.py
"""
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

STEP = hf.TILE_STEP_M                    # 2 m — one cell, i.e. the ramp width
H0 = 34.0 / 30.0                         # the plateau, 1.13333…
H0_STORED = round(H0, 3)                 # 1.133 — what the tile carries


def terrain(x):
    """The authored landscape of this fixture, by hand: x / 10."""
    return x / 10.0


def idx(x, z):
    """The stored index of a world point on tile (0, 0)."""
    return (int(x / STEP), int(z / STEP))


def at(tile, x, z):
    i, j = idx(x, z)
    return tile["heights"][j][i]


PLAIN = hf.rasterize_tile(0, 0, [SLOPE], footprints=())
TILE = hf.rasterize_tile(0, 0, [SLOPE], footprints=[L_FP])

print("[1] the landscape under the L is the plane x / 10")
check("the tile is 129 x 129 at the 2 m step",
      (TILE["rows"], TILE["cols"], TILE["step_m"]), (129, 129, 2.0))
for _x in (8, 10, 12, 14, 16, 18, 20, 22):
    near(f"TERRAIN({_x}) without any place", at(PLAIN, _x, 68), terrain(_x))
near("...and it does not depend on z", at(PLAIN, 14, 74), terrain(14))

print("\n[2] the plateau height comes from the INTERIOR point, not the pin")
check("the L encloses 48 m²", polygon_area(L_FP[3]), 48.0)
_inner = polygon_interior_point(L_FP[3])
near("the interior point is the centroid (10/3, 10/3) — inside the L",
     _inner[0], 10.0 / 3.0, 1e-12)
near("...both coordinates", _inner[1], 10.0 / 3.0, 1e-12)
_inner_world = local_to_world(_inner[0], _inner[1], PIN_X, PIN_Z, 0.0)
near("in world metres that is x = 34/3", _inner_world[0], 34.0 / 3.0, 1e-12)
near("...and z = 208/3", _inner_world[1], 208.0 / 3.0, 1e-12)
near("the plateau reads 17/15 there",
     hf.plateau_height(_inner_world[0], _inner_world[1], STEP,
                       hf.area_boxes([SLOPE]), ()), H0, 1e-12)
check_not("RED COUNTER-PROBE: the PIN would have said TERRAIN(8) = 0.8",
          H0_STORED, 0.8)
near("...and the pin really sits that low in the landscape",
     at(PLAIN, PIN_X, PIN_Z), 0.8)

print("\n[3] (a) a point inside the wide arm IS the plateau")
near("d(local (6,2)) = 0 — inside", polygon_distance(6.0, 2.0, L_FP[3]), 0.0)
near("(14, 68) is levelled to 1.133", at(TILE, 14, 68), H0_STORED)
near("...where the untouched landscape had 1.4", at(PLAIN, 14, 68),
     terrain(14))
near("(10, 68) too — local (2, 2)", at(TILE, 10, 68), H0_STORED)
near("(10, 72) in the north arm — local (2, 6)", at(TILE, 10, 72), H0_STORED)

print("\n[4] (b) the notch keeps the pure landscape")
near("d(local (8,8)) = 4 — the corner (8,4) is the nearest outline point",
     polygon_distance(8.0, 8.0, L_FP[3]), 4.0)
near("(16, 74) is TERRAIN(16) = 1.6, no plateau and no ramp bleed",
     at(TILE, 16, 74), terrain(16))
check("...exactly the value the place-less raster carries",
      at(TILE, 16, 74), at(PLAIN, 16, 74))
check_not("RED COUNTER-PROBE: a BOUNDING-BOX plateau would have put 1.133 here",
          at(TILE, 16, 74), H0_STORED)
near("but the ring DOES reach into the notch: d(local (6,6)) = 2 = one cell",
     polygon_distance(6.0, 6.0, L_FP[3]), 2.0)
near("...so (14, 72) is pinned to 1.133", at(TILE, 14, 72), H0_STORED)
check_not("...and is NOT the landscape's 1.4", at(TILE, 14, 72), terrain(14))

print("\n[5] (c) the ramp ring interpolates plateau -> terrain")
near("(16, 68) — ON the outline, d = 0", polygon_distance(8.0, 2.0, L_FP[3]),
     0.0)
near("...pinned", at(TILE, 16, 68), H0_STORED)
near("(18, 68) — d = 2, the ring", polygon_distance(10.0, 2.0, L_FP[3]), 2.0)
near("...carries the FULL plateau (§ A16.1: the ring is pinned, not blended)",
     at(TILE, 18, 68), H0_STORED)
near("(20, 68) — d = 4, untouched", polygon_distance(12.0, 2.0, L_FP[3]), 4.0)
near("...so it is TERRAIN(20) = 2.0", at(TILE, 20, 68), terrain(20))
near("the ramp cell mid-point (19, 68) is the mean of 1.133 and 2.0",
     hf.sample_height(TILE, 19.0, 68.0), 1.5665, 1e-12)
near("...a quarter in, (18.5, 68)", hf.sample_height(TILE, 18.5, 68.0),
     1.34975, 1e-12)
near("...three quarters in, (19.5, 68)", hf.sample_height(TILE, 19.5, 68.0),
     1.78325, 1e-12)
_ramp = [hf.sample_height(TILE, 18.0 + STEP * t / 8.0, 68.0)
         for t in range(9)]
check("...and the whole cell is one straight line, 1.133 -> 2.0",
      all(abs(_ramp[t] - (H0_STORED + (2.0 - H0_STORED) * t / 8.0)) < 1e-12
          for t in range(9)), True)

print("\n[6] (d) height_sig hashes the polygon points")


def as_location(boundary, level=True):
    """A PLAIN DICT location — the injection point of the signature half."""
    return {"id": "l_shape", "name": "L", "pos_x": PIN_X, "pos_z": PIN_Z,
            "yaw_deg": 0.0, "level_ground": level,
            "map3d": {"boundary": boundary}}


def with_locations(locs):
    world_store.list_locations = lambda: list(locs)


with_locations([as_location(L_LOCAL)])
check("placed_footprints hands out the polygon, rounded to the centimetre",
      store.placed_footprints(), [L_FP])
_sig = store.height_sig()

_moved = [list(p) for p in L_LOCAL]
_moved[2] = [8.01, 4]
with_locations([as_location(_moved)])
check("ONE boundary point moved by 1 cm — the place never moved",
      store.placed_footprints()[0][:3], L_FP[:3])
check("...but the outline is a different one", store.placed_footprints()[0][3],
      [(0.0, 0.0), (8.0, 0.0), (8.01, 4.0), (4.0, 4.0), (4.0, 8.0),
       (0.0, 8.0)])
check_not("...so the signature moved with it", store.height_sig(), _sig)

with_locations([as_location(L_LOCAL, level=False)])
check("an UNFLAGGED location is no input at all", store.placed_footprints(),
      [])
check_not("...which is again a different signature", store.height_sig(), _sig)

with_locations([as_location(L_LOCAL)])
check("putting the outline back restores the signature exactly",
      store.height_sig(), _sig)

print("\n[7] a DRAWN square gets its plateau — a bare width gets none")
# The square as an OUTLINE: the centred 8 m square, corners ±4. These are the
# very four corners the transition synthesis used to hand out for
# ``plan_width_m`` 8 — and since 2026-08-19 they only exist when somebody drew
# them (the map editor's "Seed missing boundaries" writes exactly this).
_square = {"id": "sq", "name": "Square", "pos_x": 40.0, "pos_z": 40.0,
           "yaw_deg": 0.0, "level_ground": True,
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
# THE CLOSING CHECK: the same location WITHOUT the outline levels nothing —
# it has no area, so the plateau pass never sees it, flag or no flag.
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
