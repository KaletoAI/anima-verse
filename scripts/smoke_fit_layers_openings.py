#!/usr/bin/env python3
"""Smoke: a piece's sheets keep their order through the push, and a recess opening's inside lies nearer its inside
than its rim (Ruling A76, Kai's leather jacket: purple patches and a hole on the chest).

Usage:
    ./.venv/bin/python scripts/smoke_fit_layers_openings.py

No server, no world DB, no hub: every mesh is built in this file, the storage is a temp dir. Every number below is
derived by hand. The fails-on-old proofs load ``app/core/garment_fit.py`` of commit
77c655f75937576d5e14c921c2ccaaa6fe8e6f89 (the main HEAD this fix starts from) as its own module.

BODY (as smoke_body_field [F7]): a closed box x -0.20 .. 0.20, y 0 .. 0.60, z -0.06 .. 0.06 (a flat trunk), vox
0.004, crop (-0.26, -0.06, -0.12) .. (0.26, 0.66, 0.12). In front (z > 0, at least 0.04 m from every other wall)
the field is s = z - 0.06 and its gradient +z.

[1] Two sheets (a leather sheet over a lining sheet, as the mesher builds them): grids x -0.05 .. 0.05, y 0.25 ..
    0.35, step 0.005 (21 x 21 = 441 vertices each, two faces per cell, no face between the sheets): OUTER at
    z 0.050 (1.0 cm inside the front wall, s -0.010), INNER at z 0.046 (s -0.014), 4 mm under it.
    ``layer_lift`` (CARRY_M 0.012): an outer vertex's UNDER neighbours lie deeper along +z (along > 0) within 45 deg
    (along >= across) and at most 0.006 across: only the inner vertex straight under it (along 0.004, across 0; the
    next is 0.005 across > 0.004). Lift = s(outer) - s(inner) = 0.004 (+- 0.0005). An inner vertex has nothing under
    it (the outer lies above, its own sheet at along 0): lift 0 exactly.
[2] ``push_kept`` with the unrigged numbers (CLEAR_M 0.0119, 8 iterations, smoothed in the first 6, margin
    SIDE_MARGIN_M) and that lift: each sheet is uniform, so the smoothing changes nothing; the last iterations set
    each vertex to its clearance: INNER at z 0.06 + 0.0119 = 0.0719, OUTER at 0.0719 + 0.004 = 0.0759 (+- 0.0015
    each, the voxel field's error at the wall; both read the same): the outer stays over the inner by 0.004
    (+- 0.0005), every vertex, the order kept.
    - The old code (no lift): both sheets end at 0.0719 — the gap <= 0.0005: the sheets meet, and wherever the
      field's error orders them the wrong way the lining shows through the leather.
[3] The push numbers count the push beyond the lift (``lift_spread``: the larger of the lift and the lift smoothed
    LIFT_SPREAD_PASSES 3 passes over the mesh; each sheet is uniform, so the spread is the lift itself): the outer
    sheet moved 0.0759 - 0.050 = 0.0259 and counts 0.0259 - 0.004 = 0.0219 (+- 0.001) — its 1.0 cm in the body +
    the clearance, as a single sheet at its place; the inner moved 0.0719 - 0.046 = 0.0259 and counts all of it
    (+- 0.0015 each, as [2]).
[4] A single sheet tilted against the field lifts nothing: a grid x -0.03 .. 0.03, y 0.25 .. 0.35 (step 0.005) at
    z = 0.04 + tan(30 deg) x. A neighbour d away in x lies 0.577 d further out but d across (along < across), one in y
    lies level (along 0): no vertex has an UNDER neighbour, every lift 0 exactly.

OPENINGS (``opening_lining``, as smoke_fit_joint_frames [6]). Garment (metres, its own frame): x -0.20 .. 0.20,
y 0 .. 0.60, grid 0.005. Masks 400 x 400: the garment rows 50 .. 349, cols 100 .. 299 -> 0.002 m per px, the mask
centre (200, 200) <-> the mesh bbox centre (0, 0.30, 0): col = 200 + x / 0.002, row = 200 - (y - 0.30) / 0.002,
depth = z / 0.002 px toward the viewer.

[5] Kai's open jacket, reduced: a FRONT panel at z 0.10 (depth 50) with a hole |x| < 0.05, 0.10 < y < 0.40, whose
    edge rolls back — every front vertex at most 0.005 from the hole (the edge itself and the next ring) at z 0.08
    (depth 40); a BACK panel at z -0.10 (depth -50); nothing else: through the hole one sees the back panel, a single
    layer. The opening mask overlaps the edge by 3 px (the mesh's projection is not the ghost's): rows 147 .. 302,
    cols 172 .. 227. The component's ring (6 px around it) is the flat front at depth 50; its front-most vertices are
    the back panel (the majority, depth -50) and the rolled edge (40): recess = 50 - (-50) = 100 px >= 15 —
    ``by: recess``.
    - The old code: the rolled edge is layered (40 - (-50) = 90 >= OPEN_LAYER_PX 30) and recessed (the front 50
      within OPEN_LOCAL_PX: 50 - 40 = 10 >= OPEN_STEP_PX 10), so its vertices in the opening are seeds; the growth
      takes the whole rolled edge: the band between the hole's rectangle and the one 0.005 around it, (22 x 62) -
      (20 x 60) = 164 cells. The band's four outer corners lie 0.005 x sqrt 2 = 0.0071 from the hole: flat, not
      grown. The pinhole fill (a region vertex with at least half its neighbours inside) takes two of them: with the
      cells' diagonal running (+x, +y), the corner at (+0.055, 0.405) has 3 of its 6 neighbours on the edge
      ((0.05, 0.405), (0.055, 0.40), the diagonal (0.05, 0.40)), likewise (-0.055, 0.095); the corners at
      (-0.055, 0.405) and (+0.055, 0.095) have 2 of 6 and stay out, each losing one of its cell's two faces.
      160 x 2 + 2 x 2 + 2 x 1 = 326 faces left out: a hole beside the edge, the jacket's chest.
    - New: a seed (and a vertex the growth passes) lies at least OPEN_INSIDE_SHARE 0.5 of the recess behind the ring:
      depth <= 50 - 0.5 x 100 = 0. The edge at 40 is not; the back panel has no garment behind it (never layered):
      nothing is left out, 0 faces.
[6] The inside A35 leaves out stays: smoke_fit_joint_frames [6]'s piece — the front panel at z 0.10 with the hole,
    a lining panel at z 0.06 (x -0.08 .. 0.08, y 0.08 .. 0.42, depth 30), the back panel at -0.10; the opening
    rows 150 .. 299, cols 175 .. 224. Recess 50 - 30 = 20; the lining lies 50 - 30 = 20 >= 0.5 x 20 = 10 behind the
    ring: the same 1121 lining vertices and 2088 faces as the old code.
"""
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smoke_fit_layers_openings_")
os.environ["STORAGE_DIR"] = _TMP
os.environ["INSTANCE_DIR"] = _TMP
from app.core import paths  # noqa: E402

paths.init(_TMP)

import numpy as np  # noqa: E402

from app.core import garment_fit as gf  # noqa: E402

OLD_COMMIT = "77c655f75937576d5e14c921c2ccaaa6fe8e6f89"
FAILS = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def old_module():
    """``app/core/garment_fit.py`` of ``OLD_COMMIT``, loaded as its own module (None when git cannot show it)."""
    try:
        src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/garment_fit.py"])
    except (subprocess.CalledProcessError, OSError) as e:
        check("the pinned old garment_fit.py is readable", False, str(e))
        return None
    mod = types.ModuleType("garment_fit_a76_old")
    mod.__file__ = f"<{OLD_COMMIT}:app/core/garment_fit.py>"
    sys.modules[mod.__name__] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def grid(x0, x1, y0, y1, z, step=0.005, skip=None):
    """A planar grid, ``z`` a number or a function of (x, y), two faces per cell; ``skip(cx, cy)`` drops a cell's
    faces and with them the vertices only they used."""
    nx, ny = int(round((x1 - x0) / step)) + 1, int(round((y1 - y0) / step)) + 1
    gx, gy = np.meshgrid(np.linspace(x0, x1, nx), np.linspace(y0, y1, ny), indexing="ij")
    zz = np.vectorize(z)(gx, gy) if callable(z) else np.full(gx.shape, float(z))
    P = np.stack([gx.ravel(), gy.ravel(), zz.ravel()], 1)
    F = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            a, b, c, d = i * ny + j, (i + 1) * ny + j, i * ny + j + 1, (i + 1) * ny + j + 1
            cx, cy = 0.5 * (P[a, 0] + P[d, 0]), 0.5 * (P[a, 1] + P[d, 1])
            if skip is not None and skip(cx, cy):
                continue
            F += [(a, b, d), (a, d, c)]
    F = np.asarray(F, np.int64)
    used = np.unique(F)
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    return P[used], remap[F]


def merged(*meshes):
    P, F, base = [], [], 0
    for p, f in meshes:
        P.append(p)
        F.append(f + base)
        base += len(p)
    return np.concatenate(P), np.concatenate(F)


def box(lo, hi, step=0.01):
    """A closed axis-aligned box, every side a grid of about ``step`` spacing (winding irrelevant to the field)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    parts = []
    for axis in range(3):
        u, v = [a for a in range(3) if a != axis]
        nu = max(2, int(np.ceil((hi[u] - lo[u]) / step)) + 1)
        nv = max(2, int(np.ceil((hi[v] - lo[v]) / step)) + 1)
        for value in (lo[axis], hi[axis]):
            uu, vv = np.meshgrid(np.linspace(lo[u], hi[u], nu), np.linspace(lo[v], hi[v], nv), indexing="ij")
            P = np.zeros((nu * nv, 3))
            P[:, axis], P[:, u], P[:, v] = value, uu.ravel(), vv.ravel()
            F = []
            for i in range(nu - 1):
                for j in range(nv - 1):
                    a, b, c, d = i * nv + j, (i + 1) * nv + j, i * nv + j + 1, (i + 1) * nv + j + 1
                    F += [(a, b, d), (a, d, c)]
            parts.append((P, np.asarray(F, np.int64)))
    return merged(*parts)


OLD = old_module()

# --- [1] .. [4] the sheets keep their order ---------------------------------------------------------------------------
BP, BF = box((-0.20, 0.0, -0.06), (0.20, 0.60, 0.06))
SDF = gf.body_sdf(BP, BF, vox=0.004, bounds=(np.array([-0.26, -0.06, -0.12]), np.array([0.26, 0.66, 0.12])))
outer = grid(-0.05, 0.05, 0.25, 0.35, 0.050)
inner = grid(-0.05, 0.05, 0.25, 0.35, 0.046)
Q, FQ = merged(outer, inner)
n_o = len(outer[0])
o, i_ = slice(0, n_o), slice(n_o, None)
check("[1] 441 vertices per sheet", n_o == 441 and len(Q) == 882, f"{n_o} / {len(Q)}")

lift = gf.layer_lift(Q, SDF, gf.CARRY_M)
check("[1] the outer sheet lies 0.004 over the inner: lift 0.004 +- 0.0005 at every outer vertex",
      bool(np.all(np.abs(lift[o] - 0.004) <= 0.0005)), f"{lift[o].min():.5f} .. {lift[o].max():.5f}")
check("[1] the inner sheet has nothing under it: lift 0", bool(np.all(lift[i_] == 0.0)), f"{lift[i_].max():.5f}")

A = gf._adjacency(FQ, len(Q))
KW = dict(clear=gf.CLEAR_M, iterations=gf.PUSH_ITERATIONS, smooth_until=gf.PUSH_SMOOTH_UNTIL, margin=gf.SIDE_MARGIN_M)
D = gf.push_kept(Q, A, SDF, **KW, lift=lift)
X = Q + D
zo, zi = X[o, 2], X[i_, 2]
check("[2] inner at 0.06 + 0.0119 = 0.0719 +- 0.0015", bool(np.all(np.abs(zi - 0.0719) <= 0.0015)),
      f"{zi.min():.4f} .. {zi.max():.4f}")
check("[2] outer at 0.0719 + 0.004 = 0.0759 +- 0.0015", bool(np.all(np.abs(zo - 0.0759) <= 0.0015)),
      f"{zo.min():.4f} .. {zo.max():.4f}")
gap = zo - zi
check("[2] every outer vertex stays 0.004 +- 0.0005 over the inner one under it",
      bool(np.all(np.abs(gap - 0.004) <= 0.0005)), f"{gap.min():.5f} .. {gap.max():.5f}")
if OLD is not None:
    D_old = OLD.push_kept(Q, OLD._adjacency(FQ, len(Q)), OLD.body_sdf(
        BP, BF, vox=0.004, bounds=(np.array([-0.26, -0.06, -0.12]), np.array([0.26, 0.66, 0.12]))), **KW)
    gap_old = (Q + D_old)[o, 2] - (Q + D_old)[i_, 2]
    check("[2] the old code: the sheets meet (gap <= 0.0005)", bool(np.all(np.abs(gap_old) <= 0.0005)),
          f"{gap_old.min():.5f} .. {gap_old.max():.5f}")

spread = gf.lift_spread(lift, A)
check("[3] the spread of a uniform sheet's lift is the lift", bool(np.allclose(spread, lift, atol=1e-12)),
      f"{np.abs(spread - lift).max():.2e}")
n_outer = gf.push_numbers(Q[o], X[o], lift=spread[o])
n_inner = gf.push_numbers(Q[i_], X[i_], lift=spread[i_])
check("[3] the outer sheet counts 0.0259 - 0.004 = 0.0219 +- 0.0015",
      abs(n_outer["max_push_m"] - 0.0219) <= 0.0015,
      f"{n_outer}")
check("[3] the inner sheet counts all of its 0.0259 +- 0.0015", abs(n_inner["max_push_m"] - 0.0259) <= 0.0015,
      f"{n_inner}")

tilted = grid(-0.03, 0.03, 0.25, 0.35, lambda x, y: 0.04 + np.tan(np.radians(30.0)) * x)
check("[4] a single sheet tilted 30 deg against the field: every lift 0",
      bool(np.all(gf.layer_lift(tilted[0], SDF, gf.CARRY_M) == 0.0)))

# --- [5] [6] openings -------------------------------------------------------------------------------------------------


def in_hole(x, y):
    return abs(x) < 0.05 and 0.10 < y < 0.40


def to_hole(x, y):
    """Distance of (x, y) to the hole's rectangle (0 inside and on it)."""
    return float(np.hypot(max(abs(x) - 0.05, 0.0), max(0.10 - y, y - 0.40, 0.0)))


gm = np.zeros((400, 400), bool)
gm[50:350, 100:300] = True
front5 = grid(-0.20, 0.20, 0.0, 0.60, lambda x, y: 0.08 if to_hole(x, y) <= 0.005 + 1e-9 else 0.10, skip=in_hole)
back5 = grid(-0.20, 0.20, 0.0, 0.60, -0.10)
P5, F5 = merged(front5, back5)
op5 = np.zeros((400, 400), bool)
op5[147:303, 172:228] = True
lin5, rep5 = gf.opening_lining(P5, F5, op5, gm)
comp5 = rep5["components"]
check("[5] one opening, recess 100 px, by recess", len(comp5) == 1 and abs(comp5[0]["recess_px"] - 100.0) <= 1.0
      and comp5[0].get("by") == "recess", f"{comp5}")
check("[5] nothing left out: the rolled edge stays, 0 faces", not lin5.any() and rep5["faces"] == 0,
      f"{int(lin5.sum())} vertices, {rep5['faces']} faces")
if OLD is not None:
    lin5o, rep5o = OLD.opening_lining(P5, F5, op5, gm)
    nf = len(front5[1])
    band_faces = int(lin5o[F5].all(1)[:nf].sum())
    check("[5] the old code: the rolled edge's 326 faces left out (a hole beside the edge)",
          rep5o["faces"] == 326 and band_faces == 326, f"{rep5o['faces']} faces, {band_faces} of the front")

front6 = grid(-0.20, 0.20, 0.0, 0.60, 0.10, skip=in_hole)
lining6 = grid(-0.08, 0.08, 0.08, 0.42, 0.06)
P6, F6 = merged(front6, lining6, back5)
op6 = np.zeros((400, 400), bool)
op6[150:300, 175:225] = True
lin6, rep6 = gf.opening_lining(P6, F6, op6, gm)
check("[6] the lining seen through the opening still goes: 1121 vertices, 2088 faces",
      int(lin6.sum()) == 1121 and rep6["faces"] == 2088, f"{int(lin6.sum())} / {rep6['faces']}")
if OLD is not None:
    lin6o, rep6o = OLD.opening_lining(P6, F6, op6, gm)
    check("[6] ... exactly as the old code", np.array_equal(lin6, lin6o) and rep6o["faces"] == 2088,
          f"{int(lin6o.sum())} / {rep6o['faces']}")

print()
print("ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
