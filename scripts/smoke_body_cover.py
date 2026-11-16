"""Smoke: body faces hidden under own-mesh clothing (``app/core/body_cover.py``, Ruling A133).

Usage: ./.venv/bin/python scripts/smoke_body_cover.py   (no server, no world, no storage)

Hand-derived on a synthetic leg (constants REACH_M 0.06, FACING_MIN 0.3, INSIDE_TOL_M 0.02, HEM_BAND_M 0.02,
LATERAL_SLACK_M 0.005):

* body = open cylinder r 0.10 m, axis y, rings y = 0.00 .. 1.00 every 0.01 (101 rings x 32 segments), outward
  faces; piece = coaxial cylinder r 0.11, rings y = 0.30 .. 0.70 every 0.01 (41 rings), same 32 angles, outward.
* A body vertex at ring y in [0.30, 0.70] has the piece vertex at the same angle and height 0.01 m straight out:
  ahead 0.01, sideways 0, facing 1 -> over the piece. Below/above the piece the nearest piece vertex is the rim one
  at the same angle: at y = 0.29 ahead 0.01, sideways 0.01 > 0.01 + 0.005 -> not over; further out more sideways.
* Hem band: rim rings y = 0.30 and 0.70. Distance to the rim vertex at the same angle = sqrt(0.01^2 + dy^2)
  < 0.02  <=>  dy < 0.0173 -> the rings y = 0.30, 0.31, 0.69, 0.70 stay.
* Covered rings y = 0.32 .. 0.68 = 37 rings x 32 = 1184 vertices; hidden faces = quads between two covered rings:
  36 bands x 32 quads x 2 = 2304 triangles. Total body faces 100 x 32 x 2 = 6400.
* Piece with its faces wound inward (normals toward the body, facing -1, as a sleeve wall seen from the torso)
  -> 0 covered.
* Seam split (the piece's angle-0 column duplicated, as a UV seam): welded, the open border is only the two rims
  = 2 x 32 = 64 vertices; unwelded both rims hold 33 vertices (2 x 33 = 66) and both seam columns
  add their 41 - 2 = 39 inner vertices (78) -> 144.
* A piece far away (r 0.20, 0.10 m out > REACH_M) -> 0 covered.

Garment under garment (``covered_under``, Ruling A144): lower = cylinder r 0.115, rings y = 0.20 .. 0.80 (61 rings);
upper = r 0.132, rings 0.30 .. 0.70. The outward direction of a lower vertex = from its nearest body vertex (same
angle and height, 0.015 m in) = radial. Upper vertex at the same angle: ahead 0.017.
* y in [0.30, 0.70]: sideways 0 -> over. y = 0.29 / 0.28: sideways 0.01 / 0.02 <= 0.017 + 0.005 -> over; y = 0.27:
  0.03 > 0.022 -> not (and symmetric above: 0.71, 0.72 over, 0.73 not).
* Band at the UPPER piece's rims (y 0.30, 0.70): sqrt(0.017^2 + dy^2) < 0.02 <=> dy < 0.0105 -> rings 0.29, 0.30,
  0.31 and 0.69, 0.70, 0.71 stay. Covered: rings 0.28 .. 0.72 = 45 rings - 6 = 39 x 32 = 1248.
* The lower piece wound inward (its inner shell) -> the same 1248 (the direction comes from the body, not the
  shell's normals).
* Lower r 0.16 over the upper (ahead -0.025 < -INSIDE_TOL_M) -> 0 covered.
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


body_P, body_F = cylinder(0.10, 0.0, 1.0, 101)
piece = cylinder(0.11, 0.30, 0.70, 41)
check("body normals point out", bool((np.einsum("ij,ij->i", body_cover.vertex_normals(body_P, body_F)[:, [0, 2]],
                                                body_P[:, [0, 2]]) > 0).all()), True)

cov, stats = body_cover.covered_vertices(body_P, body_F, [piece])
check("covered vertices", int(cov.sum()), 37 * 32)
rings = np.unique(np.round(body_P[cov, 1], 2))
check("covered rings", (float(rings.min()), float(rings.max()), len(rings)), (0.32, 0.68, 37))
check("hidden faces", int(body_cover.hidden_faces(body_F, cov).sum()), 36 * 32 * 2)

prim = Prim(positions=body_P, faces=body_F)
replaced, st = body_cover.hide_under([prim], [piece])
check("hide_under: faces left", len(replaced[0].faces), 6400 - 2304)
check("hide_under: vertices untouched", len(replaced[0].positions), len(body_P))
check("hide_under: stats", (st["hidden_faces"], st["faces"], st["version"]), (2304, 6400, body_cover.VERSION))

inward = cylinder(0.11, 0.30, 0.70, 41, inward=True)
check("piece facing the body (inner wall) -> 0 covered", int(body_cover.covered_vertices(body_P, body_F, [inward])[0].sum()), 0)

sP, sF = cylinder(0.11, 0.30, 0.70, 41, seam=True)
check("seam split, welded rim", len(body_cover.boundary_vertices(body_cover.weld(sP, sF))), 64)
check("seam split, unwelded rim", len(body_cover.boundary_vertices(sF)), 2 * 33 + 2 * 39)
check("seam split piece covers the same", int(body_cover.covered_vertices(body_P, body_F, [(sP, sF)])[0].sum()), 37 * 32)

far = cylinder(0.20, 0.30, 0.70, 41)
check("piece 0.10 m out -> 0 covered", int(body_cover.covered_vertices(body_P, body_F, [far])[0].sum()), 0)
check("no pieces -> nothing", body_cover.hide_under([prim], [])[0], {})

lower = cylinder(0.115, 0.20, 0.80, 61)
upper = cylinder(0.132, 0.30, 0.70, 41)
cov_u, st_u = body_cover.covered_under(lower[0], body_P, [upper])
check("covered_under: 39 rings x 32", int(cov_u.sum()), 1248)
check("covered_under: 0.27 no, 0.28 yes, 0.30 band, 0.72 yes, 0.73 no",
      [bool(cov_u[r * 32]) for r in (7, 8, 10, 52, 53)], [False, True, False, True, False])
check("covered_under: inner shell the same",
      int(body_cover.covered_under(cylinder(0.115, 0.20, 0.80, 61, inward=True)[0], body_P, [upper])[0].sum()), 1248)
check("covered_under: lower outside the upper -> 0",
      int(body_cover.covered_under(cylinder(0.16, 0.20, 0.80, 61)[0], body_P, [upper])[0].sum()), 0)

print("\nALL OK" if not FAILS else f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
