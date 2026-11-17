"""Smoke: body faces hidden under own-mesh clothing (``app/core/body_cover.py``, Ruling A133, rule of A192).

Usage: ./.venv/bin/python scripts/smoke_body_cover.py   (no server, no world, no storage)

Hand-derived (constants VOXEL_M 0.004, one voxel thick either way; CONE_DEG 65: cos 0.4226, sin 0.9063, tan 2.1445;
INSIDE_TOL_M 0.02, RAY_REACH_M 0.12, SEEN_BAND_M = HEM_BAND_M 0.02). A voxel grid has no exact edge: a surface at
distance d is occupied somewhere in [d - 0.008, d + 0.008]; every expectation below keeps clear of that tolerance,
and a ring that falls inside it is not asserted.

[1] Rays against a plate (``rays_blocked``), the piece a square z = 0.01 over |x|, |y| <= 0.2, the point's normal +z:
  * at the origin every one of the 17 rays meets it (a rim ray is 0.01 x tan 65 = 0.021 off axis at the plate);
  * at x = 0.21, 0.01 past the plate's edge (more than the 0.008 tolerance), the normal ray passes it, and so do
    the rim rays pointing away from it -> not blocked;
  * a plate at z = 0.20 (> RAY_REACH_M) blocks none; a plate at z = -0.015 (under the skin, within INSIDE_TOL_M)
    blocks the normal ray.
[2] ``Occupancy.fill``: a closed box shell of side 0.1 — its centre is free before ``fill`` and solid after.
[3] Leg: body = open cylinder r 0.10, axis y, rings y = 0.00 .. 1.00 every 0.01 (101 x 32); piece = coaxial
  cylinder r 0.11, rings 0.30 .. 0.70. A rim ray along the axis meets the piece's shell (r 0.102 .. 0.118)
  between 0.002 / 0.4226 x 0.9063 = 0.004 and 0.018 x 2.1445 = 0.039 further along; so a ring more than 0.039 +
  0.008 inside the piece's end is covered by every ray: rings 0.35 .. 0.65. A ring at the end or beyond it
  (<= 0.30, >= 0.70) has a ray past the end AND lies in the 2 cm bands -> never covered; the rings between are
  the tolerance (0.31 .. 0.34). hide_under drops exactly the faces between covered rings and no vertex.
[4] A192, the closed thick shell: the same sleeve as a wall r 0.11 .. 0.12 closed at both ends by a cap — NO border
  edge (rim count 0). The commit before (e3e56a1ae: nearest piece vertex within a 45 degree cone, the band only at
  border edges) hid the rings 0.28 .. 0.72 (run against that commit), which shows as a hole through the cuff; now, as in [3], no ring <= 0.30
  or >= 0.70 is covered and the rings 0.35 .. 0.65 are.
[5] Open front: the piece of [3] over the back half only (the 17 columns 90 .. 270 degrees). Every body vertex of
  the front half stays, and so do the two columns at the piece's edges and their inside neighbours (chord to the
  edge column 2 x 0.10 x sin(5.625 deg) = 0.0196 < SEEN_BAND_M); the columns 135 .. 225 degrees (>= 4 steps =
  0.078 m of arc from an edge, > 0.039 + 0.02 + 0.008) of the rings 0.35 .. 0.65 are covered.
[6] Winding does not matter (the inside of a jacket hides the skin as well): the piece of [3] wound inward covers
  the same vertices. A piece 0.15 m out (> RAY_REACH_M) covers nothing; no piece, nothing.
[7] Seam split (the piece's angle-0 column duplicated, as a UV seam): welded, the open border is the two rims
  = 2 x 32 = 64 vertices; unwelded 2 x 33 + 2 x 39 = 144.
[8] Garment under garment (``covered_under``): lower = cylinder r 0.115, rings 0.20 .. 0.80; upper = r 0.132, rings
  0.30 .. 0.70; the outward direction of a lower vertex is radial (from its nearest body vertex). Standoff 0.017:
  a rim ray meets the upper shell (r 0.124 .. 0.140) between 0.009 x 2.1445 = 0.019 and 0.025 x 2.1445 = 0.054
  along the axis -> rings more than 0.054 + 0.008 inside the upper end are covered: 0.37 .. 0.63; rings <= 0.30 /
  >= 0.70 never. The lower piece wound inward gives the same set (the direction comes from the body). A lower
  piece OUTSIDE the upper (r 0.16) is not covered (the rays start at the point itself).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import body_cover  # noqa: E402
from app.core.glb_mesh import Prim  # noqa: E402

FAILS: list = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got}" + ("" if ok else f" — expected {want}"))
    if not ok:
        FAILS.append(label)


def cylinder(r, y0, y1, rings, seg=32, inward=False, seam=False):
    ang = np.arange(seg) * 2 * np.pi / seg
    ys = np.linspace(y0, y1, rings)
    cols = seg + (1 if seam else 0)                   # seam: column ``seg`` repeats angle 0 as separate vertices
    a = np.concatenate([ang, ang[:1]]) if seam else ang
    P = np.array([[r * np.cos(t), y, r * np.sin(t)] for y in ys for t in a])
    F = []
    for i in range(rings - 1):
        for k in range(seg):
            k1 = k + 1 if seam else (k + 1) % seg
            a0, b0, a1, b1 = i * cols + k, i * cols + k1, (i + 1) * cols + k, (i + 1) * cols + k1
            F += [[a0, a1, b0], [b0, a1, b1]]         # outward for y up, angle toward +z
    F = np.array(F, np.int64)
    if inward:
        F = F[:, ::-1]
    return P, F


def plate(z, half=0.2):
    P = np.array([[-half, -half, z], [half, -half, z], [half, half, z], [-half, half, z]], float)
    return P, np.array([[0, 1, 2], [0, 2, 3]])


def ring_set(P, mask):
    """The ring heights (2 decimals) where EVERY vertex of the ring is in ``mask`` / where ANY is."""
    y = np.round(P[:, 1], 2)
    every = {float(v) for v in np.unique(y) if mask[y == v].all()}
    some = {float(v) for v in np.unique(y) if mask[y == v].any()}
    return every, some


def span(lo, hi):
    return {round(lo + 0.01 * i, 2) for i in range(int(round((hi - lo) / 0.01)) + 1)}


# [1]
up = np.array([[0.0, 0.0, 1.0]])
occ = body_cover.Occupancy([plate(0.01)])
check("[1] cone size", len(body_cover.CONE), 17)
check("[1] under the plate: all rays blocked", bool(body_cover.rays_blocked(np.zeros((1, 3)), up, occ).all()), True)
edge = body_cover.rays_blocked(np.array([[0.21, 0.0, 0.0]]), up, occ)[0]
check("[1] 1 cm past the edge: the normal ray is free", (bool(edge[0]), bool(edge.all())), (False, False))
check("[1] plate 0.20 away: none", bool(body_cover.rays_blocked(np.zeros((1, 3)), up,
                                                               body_cover.Occupancy([plate(0.20)])).any()), False)
check("[1] plate 0.015 under the skin: normal ray blocked",
      bool(body_cover.rays_blocked(np.zeros((1, 3)), up, body_cover.Occupancy([plate(-0.015)]))[0, 0]), True)

# [2]
c = 0.05
BP = np.array([[x, y, z] for x in (-c, c) for y in (-c, c) for z in (-c, c)], float)
BF = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
               [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
box = body_cover.Occupancy([(BP, BF)])
before = bool(box.hit(np.zeros((1, 3)))[0])
check("[2] box centre free, then solid", (before, bool(box.fill().hit(np.zeros((1, 3)))[0])), (False, True))

# [3]
body_P, body_F = cylinder(0.10, 0.0, 1.0, 101)
piece = cylinder(0.11, 0.30, 0.70, 41)
check("[3] body normals point out", bool((np.einsum("ij,ij->i", body_cover.vertex_normals(body_P, body_F)[:, [0, 2]],
                                                    body_P[:, [0, 2]]) > 0).all()), True)
cov, stats = body_cover.covered_vertices(body_P, body_F, [piece])
every, some = ring_set(body_P, cov)
check("[3] rings 0.35 .. 0.65 covered", span(0.35, 0.65) <= every, True)
check("[3] no ring <= 0.30 or >= 0.70 covered", some <= span(0.31, 0.69), True)
prim = Prim(positions=body_P, faces=body_F)
replaced, st = body_cover.hide_under([prim], [piece])
want_hidden = int(body_cover.hidden_faces(body_F, cov).sum())
check("[3] hide_under: faces left", len(replaced[0].faces), 6400 - want_hidden)
check("[3] hide_under: at least the 30 bands 0.35 .. 0.65", want_hidden >= 30 * 32 * 2, True)
check("[3] hide_under: vertices untouched", len(replaced[0].positions), len(body_P))
check("[3] hide_under: stats", (st["hidden_faces"], st["faces"], st["version"]), (want_hidden, 6400, body_cover.VERSION))

# [4]
oP, oF = cylinder(0.12, 0.30, 0.70, 41)
iP, iF = cylinder(0.11, 0.30, 0.70, 41, inward=True)
n = len(oP)
caps = []
for row in (0, 40):
    for k in range(32):
        a0, b0 = row * 32 + k, row * 32 + (k + 1) % 32
        caps += [[a0, b0, n + a0], [b0, n + b0, n + a0]]
thick = (np.concatenate([oP, iP]), np.concatenate([oF, iF + n, np.array(caps)]))
check("[4] closed shell has no border", len(body_cover.boundary_vertices(body_cover.weld(*thick))), 0)
cov_t, _ = body_cover.covered_vertices(body_P, body_F, [thick])
every_t, some_t = ring_set(body_P, cov_t)
check("[4] closed shell: rings 0.35 .. 0.65 covered", span(0.35, 0.65) <= every_t, True)
check("[4] closed shell: nothing hidden at or past the cuff", some_t <= span(0.31, 0.69), True)

# [5]
hP, hF = cylinder(0.11, 0.30, 0.70, 41)
col_of = np.arange(len(hP)) % 32                     # column k = angle k x 11.25 degrees
keep_f = ((col_of[hF] >= 8) & (col_of[hF] <= 24)).all(axis=1)
half = (hP, hF[keep_f])
cov_h, _ = body_cover.covered_vertices(body_P, body_F, [half])
bcol = np.arange(len(body_P)) % 32
by = np.round(body_P[:, 1], 2)
check("[5] open front: the front half and the edge columns stay",
      bool(cov_h[(bcol <= 9) | (bcol >= 23)].any()), False)
core = (bcol >= 12) & (bcol <= 20) & (by >= 0.35) & (by <= 0.65)
check("[5] open front: the back's middle is covered", bool(cov_h[core].all()), True)

# [6]
inward = cylinder(0.11, 0.30, 0.70, 41, inward=True)
check("[6] wound inward covers the same", bool((body_cover.covered_vertices(body_P, body_F, [inward])[0] == cov).all()),
      True)
far = cylinder(0.25, 0.30, 0.70, 41)
check("[6] piece 0.15 m out -> 0 covered", int(body_cover.covered_vertices(body_P, body_F, [far])[0].sum()), 0)
check("[6] no pieces -> nothing", body_cover.hide_under([prim], [])[0], {})

# [7]
sP, sF = cylinder(0.11, 0.30, 0.70, 41, seam=True)
check("[7] seam split, welded rim", len(body_cover.boundary_vertices(body_cover.weld(sP, sF))), 64)
check("[7] seam split, unwelded rim", len(body_cover.boundary_vertices(sF)), 2 * 33 + 2 * 39)
check("[7] seam split piece covers the same", bool((body_cover.covered_vertices(body_P, body_F, [(sP, sF)])[0] == cov).all()),
      True)

# [8]
lower = cylinder(0.115, 0.20, 0.80, 61)
upper = cylinder(0.132, 0.30, 0.70, 41)
cov_u, st_u = body_cover.covered_under(lower[0], body_P, [upper])
every_u, some_u = ring_set(lower[0], cov_u)
check("[8] covered_under: rings 0.37 .. 0.63", span(0.37, 0.63) <= every_u, True)
check("[8] covered_under: none <= 0.30 or >= 0.70", some_u <= span(0.31, 0.69), True)
check("[8] covered_under: inner shell the same",
      bool((body_cover.covered_under(cylinder(0.115, 0.20, 0.80, 61, inward=True)[0], body_P, [upper])[0] == cov_u).all()),
      True)
check("[8] covered_under: lower outside the upper -> 0",
      int(body_cover.covered_under(cylinder(0.16, 0.20, 0.80, 61)[0], body_P, [upper])[0].sum()), 0)

print("\nALL OK" if not FAILS else f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
