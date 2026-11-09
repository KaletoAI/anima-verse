#!/usr/bin/env python3
"""Garment fit math (``app/core/garment_fit.py``) on synthetic meshes, expectations derived by hand.

Usage: ./.venv/bin/python scripts/smoke_garment_fit.py

No world, no server, no external assets: every mesh below is built in this file.

(w) Weld + components.
    Two triangles share an edge through duplicated seam vertices (same position, other UV): 6 vertices weld to 4,
    both faces survive, a face that collapses onto two welded vertices is dropped.
    Three loose squares with areas 0.99, 0.009 and 0.001 (shares of the total 1.0): the largest share is 0.99;
    ``drop_small`` at the default 0.002 removes only the 0.001 square; at 0.01 it removes the 0.009 one too.

(a) Framing (spike ``mmap``: mesh units per pixel = mesh height / mask pixel height).
    Body mesh bbox y [0, 1.0], x [-0.2, 0.2], z [-0.1, 0.1]; body mask bbox x [400, 600), y [100, 900)
    -> s_b = 1.0 / 800, body mask centre (500, 500), body mesh centre (0, 0.5, 0).
    Garment mesh bbox y [-1, 1], x [-0.5, 0.5], z [-0.1, 0.1]; garment mask x [450, 550), y [100, 300)
    -> s_d = 2 / 200 = 0.01, mask centre (500, 200), mesh centre (0, 0, 0).
    Vertex (0.5, 1.0, 0): px = 500 + 0.5 / 0.01 = 550, py = 200 - 1.0 / 0.01 = 100
    -> x = 0 + (550 - 500) / 800 = 0.0625, y = 0.5 - (100 - 500) / 800 = 1.0, z = 0.
    The z scale equals the xy scale s_b / s_d = 0.125: vertex (0, 0, 0.1) -> z 0.0125.
    ``align_depth``: a head of points at z in [-0.05, 0.15] (centre 0.05) everywhere and a garment with its
    crown band at z in [-0.2, 0.0] (centre -0.1) -> every garment z shifts by +0.15.

(b) Push-out on a double-walled sphere head.
    Body = outer UV sphere R 0.100 at (0, 0.9, 0) + inner sphere R 0.098 with reversed winding (normals and winding
    are never trusted: the voxel fill closes both walls into one solid). Units: clear 0.004, vox 0.002.
    The SDF's zero level is the body surface, so a vertex ends at radius R + clear = 0.104.
    - An inner cap shell (elevation >= 0) at r 0.095 ends at r = 0.104 +- 0.001.
    - An outer cap shell at r 0.120 has clearance 0.020 > 0.004 and stays put (+- 1e-6).
    - Spread 0.005, outer shell at 0.107 instead: after the first push the inner shell is at 0.104, 0.003 below the
      outer one (< 0.005), so the outer one takes the inner displacement 0.009 and ends at 0.116 +- 0.0015.
      Without spread it has clearance 0.007 > 0.004 and stays at 0.107.
    The caps use 3-degree steps (31 rings, 120 longitudes): the displacement is smoothed 6 passes in each of the
    first 6 iterations, and averaging radial vectors 3 degrees apart keeps (1 + cos 3deg) / 2 = 0.99931 of the
    magnitude per pass, 0.99931^36 = 0.975 overall, so the outer shell (never pushed again once it is clear) keeps
    ~0.975 * 0.0087 = 0.0085 (the first push comes from the voxel EDT inside, ~0.3 voxel short) -> ~0.1155,
    inside the tolerance (6-degree steps would lose 9 %).

(c) Transfer.
    Unrigged body = the double-walled head of (b) + a closed torso cylinder (radius 0.12, y 0.55..0.8,
    weighted Spine2); the rigged body = 1.7 * unrigged + (0, 0.05, 0) with identical UVs and topology.
    - A cap at r 0.110 (clearance 0.010 units = 0.017 m >= clear_m 0.0068 m): every vertex ends at 1.7 * Q + t
      +- 1e-4, ``scale_k`` = 1.700 +- 0.001, no neighbourhood is bad, the rigged clearance pass moves nothing
      (max rigged push < 1e-6).
    - A cap at r 0.101 (clearance 0.001 units = 0.0017 m < 0.0068 m): the rigged pass pushes it out to radius
      >= 1.7 * 0.1 + 0.0068 - 0.001 = 0.1758 m around the rigged head centre (0, 1.58, 0).

(d) Weights. Head vertices at y >= 1.45, so chin = 1.45 and blend 0.15 ends at 1.30:
    y 1.375 -> Head 0.5 / Spine2 0.5; y 1.50 -> Head 1; y 1.20 -> Spine2 1.

(e) Metrics (metres).
    - Bib: chin 1.45, neck cylinder radius 0.05 (front z 0.05). A 5 x 5 cm plate at z 0.07, x [-0.025, 0.025],
      y [1.37, 1.42] (its top edge 3 cm below the chin) is in front of the neck and inside the bib box
      (|x| < 0.06, chin - 0.16 < y < chin, z > front - 0.01) -> 25 cm^2 +- 0.5.
    - Poke: 100 crown bins of 3 vertices each (3-degree bins, directions at bin centres around (0, 1.6, 0); the
      top bin's radii 0.100/0.101/0.102 set the crown top so the derived centre is exactly (0, 1.6, 0)).
      Pre radii 0.10/0.11/0.12; in 75 bins all post radii are pre + 0.01 (outermost stays the outermost), in 25
      bins the 0.10 vertex ends at 0.13 (an inner layer outside) -> poke share 25 / 100 = 0.25.
    - Scalp: a flat head top (disc radius 0.2 at y 1.6, the only head vertices within 5 cm of the top) and a hair
      sheet 0.019 above it covering x > 0 only. A scalp vertex at x < 0 is within 2 cm of the sheet only when
      |x| < sqrt(0.02^2 - 0.019^2) = 0.0062, a strip of share ~ 2 * 0.0062 * 2 * 0.2 / (pi * 0.2^2) / 2 = 0.02 of
      the disc -> uncovered ~ 0.48, inside 0.5 +- 0.05.
    - The gate passes the spike's best numbers and names every limit it refuses (R7).

(f) ``fit_hair`` end to end on synthetic GLBs: a hair cap at r 0.108 units is generated in its own frame
    (x4, shifted by (3, -2, 1)) and placed through the shared image framing (1000 px per unit for both masks),
    centred in depth on the head, pushed (nothing to push: clearance 0.008 units = 0.0136 m > CLEAR_M 0.0119 m),
    transferred to the rigged body. The scalp metric counts the inner wall too (r 0.098 -> 0.1666 m): the hair at
    1.7 * 0.108 = 0.1836 m is 0.017 m from it, within the 2 cm, so nothing is uncovered.
    every vertex ends within 0.005 m of 1.7 * cap + (0, 0.05, 0), k = 1.700 +- 0.002, the gate passes, all weights
    are Head (the cap is above the chin 1.7 * 0.8 + 0.05 = 1.41). Masks of different sizes (no shared framing) are
    refused.
"""
import io
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# --- synthetic meshes --------------------------------------------------------

def uv_sphere(radius, centre, nlat=48, nlon=96, flip=False):
    lat = np.linspace(-np.pi / 2, np.pi / 2, nlat + 1)
    lon = np.linspace(0, 2 * np.pi, nlon, endpoint=False)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    P = np.stack([np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)], -1).reshape(-1, 3)
    P = P * radius + np.asarray(centre, float)
    F = []
    for i in range(nlat):
        for j in range(nlon):
            a, b = i * nlon + j, i * nlon + (j + 1) % nlon
            c, d = (i + 1) * nlon + (j + 1) % nlon, (i + 1) * nlon + j
            F += [(a, b, c), (a, c, d)]
    F = np.array(F)
    return P, (F[:, ::-1] if flip else F)


def cap(radius, centre, n_el=16, nlon=60):
    """Upper half sphere shell (elevation 0..90 degrees in n_el rings), same angular grid for every radius."""
    el = np.radians(np.linspace(0, 90, n_el))
    lon = np.radians(np.arange(nlon) * 360 / nlon)
    e, lo = np.meshgrid(el, lon, indexing="ij")
    P = np.stack([np.cos(e) * np.cos(lo), np.sin(e), np.cos(e) * np.sin(lo)], -1).reshape(-1, 3)
    P = P * radius + np.asarray(centre, float)
    F = []
    for i in range(n_el - 1):
        for j in range(nlon):
            a, b = i * nlon + j, i * nlon + (j + 1) % nlon
            c, d = (i + 1) * nlon + (j + 1) % nlon, (i + 1) * nlon + j
            F += [(a, b, c), (a, c, d)]
    return P, np.array(F)


def cylinder(radius, y0, y1, nseg=64, nrings=20):
    """Closed cylinder around the y axis (side + two fan caps)."""
    ys = np.linspace(y0, y1, nrings)
    ang = np.arange(nseg) * 2 * np.pi / nseg
    side = np.array([(radius * math.cos(a), y, radius * math.sin(a)) for y in ys for a in ang])
    F = []
    for i in range(nrings - 1):
        for j in range(nseg):
            a, b = i * nseg + j, i * nseg + (j + 1) % nseg
            c, d = (i + 1) * nseg + (j + 1) % nseg, (i + 1) * nseg + j
            F += [(a, b, c), (a, c, d)]
    P = list(side)
    for y, ring in ((y0, 0), (y1, nrings - 1)):
        rings = []
        for r in np.linspace(radius, 0, 12)[1:]:
            rings.append(len(P))
            P += [(r * math.cos(a), y, r * math.sin(a)) for a in ang]
        prev = ring * nseg
        for start in rings:
            for j in range(nseg):
                a, b = prev + j, prev + (j + 1) % nseg
                c, d = start + (j + 1) % nseg, start + j
                F += [(a, b, c), (a, c, d)]
            prev = start
    return np.array(P, float), np.array(F)


def merge(*parts):
    P, F, off = [], [], 0
    for p, f in parts:
        P.append(p)
        F.append(f + off)
        off += len(p)
    return np.concatenate(P), np.concatenate(F)


def head_body():
    outer = uv_sphere(0.100, (0, 0.9, 0))
    inner = uv_sphere(0.098, (0, 0.9, 0), flip=True)
    return merge(outer, inner)


def body_mesh(P, F, head_mask, names=("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head")):
    from app.core.glb_mesh import BodyMesh
    n = len(P)
    J = np.zeros((n, 4), np.int64)
    W = np.zeros((n, 4))
    J[:, 0] = np.where(head_mask, 2, 1)
    W[:, 0] = 1.0
    uv = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
    return BodyMesh(positions=P.astype(float), faces=F.astype(np.int64), uvs=uv,
                    joints=J, weights=W, joint_names=list(names))


def radii(X, centre):
    return np.linalg.norm(X - np.asarray(centre, float), axis=1)


# --- (w) weld + components -----------------------------------------------------

def test_weld():
    from app.core import garment_fit as gf
    P = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],          # triangle A
                  [1, 0, 0], [0, 1, 0], [1, 1, 0],          # triangle B, seam duplicates of A's 1 and 2
                  [1, 0, 0.0000001]], float)                 # rounds onto vertex 1
    F = np.array([[0, 1, 2], [3, 5, 4], [1, 6, 2]])
    U = np.arange(14, dtype=float).reshape(7, 2)
    Pw, Fw, inv = gf.weld(P, F, U)
    check(len(Pw) == 4, f"weld: 7 vertices -> 4 (got {len(Pw)})")
    check(len(Fw) == 2, f"weld: degenerate face dropped, 2 faces left (got {len(Fw)})")
    check(np.allclose(Pw[inv], np.round(P, 6), atol=1e-6), "weld: inv maps every vertex onto its welded twin")

    def square(x0, side):
        p = np.array([[x0, 0, 0], [x0 + side, 0, 0], [x0 + side, side, 0], [x0, side, 0]], float)
        return p, np.array([[0, 1, 2], [0, 2, 3]])
    Pc, Fc = merge(square(0, math.sqrt(0.99)), square(5, math.sqrt(0.009)), square(9, math.sqrt(0.001)))
    labels, share = gf.components(Pc, Fc)
    check(len(share) == 3 and abs(share.max() - 0.99) < 1e-9, f"components: largest share 0.99 (got {share.max():.4f})")
    check(len(set(labels.tolist())) == 3, "components: three labels")
    Pk, Fk, keep = gf.drop_small(Pc, Fc)
    check(len(Fk) == 4 and len(Pk) == 8, f"drop_small(0.002): only the 0.001 square goes ({len(Fk)} faces)")
    check(np.array_equal(Pk, Pc[keep]), "drop_small: keep indexes the kept vertices")
    Pk, Fk, keep = gf.drop_small(Pc, Fc, min_share=0.01)
    check(len(Fk) == 2 and len(Pk) == 4, f"drop_small(0.01): 0.009 square goes too ({len(Fk)} faces)")


# --- (a) framing ------------------------------------------------------------------

def test_framing():
    from app.core import garment_fit as gf
    body = np.array([[x, y, z] for x in (-0.2, 0.2) for y in (0.0, 1.0) for z in (-0.1, 0.1)])
    bm = np.zeros((1000, 1000), bool)
    bm[100:900, 400:600] = True
    gar = np.array([[x, y, z] for x in (-0.5, 0.5) for y in (-1.0, 1.0) for z in (-0.1, 0.1)]
                   + [[0.5, 1.0, 0.0], [0.0, 0.0, 0.1]])
    gm = np.zeros((1000, 1000), bool)
    gm[100:300, 450:550] = True
    Q = gf.place_by_framing(gar, body, bm, gm)
    check(np.allclose(Q[8], [0.0625, 1.0, 0.0], atol=1e-9), f"framing: (0.5, 1, 0) -> (0.0625, 1, 0) (got {Q[8]})")
    check(abs(Q[9, 2] - 0.0125) < 1e-9, f"framing: z scale = xy scale 0.125 (got {Q[9, 2] / 0.1:.4f})")
    check(abs(np.ptp(Q[:, 0]) - 0.125) < 1e-9, "framing: garment width 1.0 -> 0.125")

    head = np.array([[x, y, z] for x in (-0.05, 0.05) for y in np.linspace(0.9, 1.0, 51) for z in (-0.05, 0.15)])
    garm = np.array([[x, y, z] for x in (-0.06, 0.06) for y in np.linspace(0.85, 1.01, 81) for z in (-0.2, 0.0)])
    out = gf.align_depth(garm, head, probe_u=0.04)
    check(np.allclose(out[:, 2] - garm[:, 2], 0.15), "align_depth: crown band centred on the head band (+0.15)")
    check(np.array_equal(out[:, :2], garm[:, :2]), "align_depth: x/y untouched")


# --- (b) push-out ----------------------------------------------------------------

def test_push():
    from app.core import garment_fit as gf
    c = np.array([0, 0.9, 0])
    Pb, Fb = head_body()
    sdf = gf.body_sdf(Pb, Fb, vox=0.002, bounds=(c - 0.15, c + 0.15))
    inner, outer = cap(0.095, c, n_el=31, nlon=120), cap(0.120, c, n_el=31, nlon=120)
    Q0, Fd = merge(inner, outer)
    Q, disp = gf.push_out(Q0, Fd, sdf, clear=0.004)
    n = len(inner[0])
    ri, ro = radii(Q[:n], c), radii(Q[n:], c)
    check(np.all(np.abs(ri - 0.104) <= 0.001), f"push: inner shell 0.095 -> 0.104 +- 0.001 "
          f"(got {ri.min():.4f}..{ri.max():.4f})")
    check(np.abs(Q[n:] - Q0[n:]).max() <= 1e-6, "push: outer shell at 0.120 unmoved")
    check(np.allclose(Q, Q0 + disp), "push: Q = Q0 + disp")

    Q0, Fd = merge(inner, cap(0.107, c, n_el=31, nlon=120))
    Q, _ = gf.push_out(Q0, Fd, sdf, clear=0.004, spread=0.005, spread_depth=0.3)
    ro = radii(Q[n:], c)
    check(np.all(np.abs(ro - 0.116) <= 0.0015), f"push+spread: outer shell 0.107 -> 0.116 +- 0.0015 "
          f"(got {ro.min():.4f}..{ro.max():.4f})")
    Q, _ = gf.push_out(Q0, Fd, sdf, clear=0.004)
    ro = radii(Q[n:], c)
    check(np.all(np.abs(ro - 0.107) <= 1e-6), f"push without spread: outer shell stays at 0.107 "
          f"(got {ro.min():.6f}..{ro.max():.6f})")
    return sdf


# --- (c) transfer --------------------------------------------------------------------

def torso_head_bodies():
    hP, hF = head_body()
    tP, tF = cylinder(0.12, 0.55, 0.8)
    P, F = merge((hP, hF), (tP, tF))
    head = np.arange(len(P)) < len(hP)
    bu = body_mesh(P, F, head)
    br = body_mesh(1.7 * P + np.array([0, 0.05, 0]), F, head)
    return bu, br


def test_transfer():
    from app.core import garment_fit as gf
    bu, br = torso_head_bodies()
    t = np.array([0, 0.05, 0])
    c = np.array([0, 0.9, 0])
    Q, Fd = cap(0.110, c)
    X, rep = gf.transfer(Q, bu, br, faces=Fd, res_max_m=0.006, clear_m=0.0068, vox_m=0.0034)
    err = np.abs(X - (1.7 * Q + t)).max()
    check(err <= 1e-4, f"transfer: X = 1.7 Q + t +- 1e-4 (max err {err:.2e})")
    check(abs(rep["scale_k"] - 1.7) <= 0.001, f"transfer: scale_k 1.700 (got {rep['scale_k']:.4f})")
    check(rep["bad_neighbourhoods"] == 0 and rep["borrowing"] == 0, "transfer: no bad neighbourhood, no borrowing")
    check(rep["rigged_push_max_m"] < 1e-6, f"transfer: clearance met -> rigged pass moves nothing "
          f"({rep['rigged_push_max_m']:.2e})")
    Q, Fd = cap(0.101, c)
    X, rep = gf.transfer(Q, bu, br, faces=Fd, res_max_m=0.006, clear_m=0.0068, vox_m=0.0034)
    r = radii(X, 1.7 * c + t)
    check(r.min() >= 0.1758, f"transfer: rigged pass restores clear_m (min radius {r.min():.4f} >= 0.1758)")


# --- (d) weights -------------------------------------------------------------------------

def test_weights():
    from app.core import garment_fit as gf
    ys = np.linspace(1.0, 1.7, 141)
    P = np.array([[x, y, 0.0] for y in ys for x in (-0.05, 0.05)])
    br = body_mesh(P, np.zeros((0, 3), np.int64), P[:, 1] >= 1.45 - 1e-9)
    X = np.array([[0, 1.375, 0], [0, 1.50, 0], [0, 1.20, 0]])
    names, J, W = gf.hair_weights(X, br, blend_m=0.15)
    check(names == ["mixamorig:Head", "mixamorig:Spine2"], f"weights: joint names Head, Spine2 (got {names})")

    def w(row, name):
        return float(sum(W[row, k] for k in range(4) if names[J[row, k]] == name and W[row, k] > 0))
    check(abs(w(0, "mixamorig:Head") - 0.5) < 1e-9 and abs(w(0, "mixamorig:Spine2") - 0.5) < 1e-9,
          "weights: y 1.375 -> Head 0.5 / Spine2 0.5")
    check(abs(w(1, "mixamorig:Head") - 1) < 1e-9 and w(1, "mixamorig:Spine2") == 0, "weights: y 1.50 -> Head 1")
    check(abs(w(2, "mixamorig:Spine2") - 1) < 1e-9 and w(2, "mixamorig:Head") == 0, "weights: y 1.20 -> Spine2 1")
    check(np.allclose(W.sum(1), 1), "weights: rows sum to 1")


# --- (e) metrics ---------------------------------------------------------------------------

def grid_sheet(x0, x1, z0, z1, y, n):
    xs, zs = np.linspace(x0, x1, n + 1), np.linspace(z0, z1, n + 1)
    P = np.array([[x, y, z] for x in xs for z in zs])
    F = []
    for i in range(n):
        for j in range(n):
            a, b, c, d = i * (n + 1) + j, (i + 1) * (n + 1) + j, (i + 1) * (n + 1) + j + 1, i * (n + 1) + j + 1
            F += [(a, b, c), (a, c, d)]
    return P, np.array(F)


def neck_body():
    head = np.array([[0.08 * math.cos(a), y, 0.08 * math.sin(a)]
                     for y in np.linspace(1.45, 1.70, 26) for a in np.linspace(0, 2 * np.pi, 48, endpoint=False)])
    neck = np.array([[0.05 * math.cos(a), y, 0.05 * math.sin(a)]
                     for y in np.arange(1.25, 1.445, 0.005) for a in np.linspace(0, 2 * np.pi, 48, endpoint=False)])
    P = np.concatenate([head, neck])
    return body_mesh(P, np.zeros((0, 3), np.int64), np.arange(len(P)) < len(head))


def test_metrics():
    from app.core import garment_fit as gf
    br = neck_body()
    xs, ys = np.linspace(-0.025, 0.025, 11), np.linspace(1.37, 1.42, 11)
    P = np.array([[x, y, 0.07] for y in ys for x in xs])
    F = []
    for i in range(10):
        for j in range(10):
            a, b, c, d = i * 11 + j, i * 11 + j + 1, (i + 1) * 11 + j + 1, (i + 1) * 11 + j
            F += [(a, b, c), (a, c, d)]
    F = np.array(F)
    bib = gf.bib_area_cm2(P, F, br)
    check(abs(bib - 25) <= 0.5, f"metrics: bib plate 25 cm^2 +- 0.5 (got {bib:.2f})")

    centre = np.array([0, 1.6, 0])
    rng = np.random.default_rng(1)
    bins = [(el, th) for el in range(12, 34, 3) for th in range(-180, 180, 9)][:99]
    pre, post = [], []
    bad = set(rng.choice(99, 25, replace=False).tolist())
    for k, (el, th) in enumerate(bins):
        e, t = math.radians(el), math.radians(th)
        u = np.array([math.cos(e) * math.sin(t), math.sin(e), math.cos(e) * math.cos(t)])
        for r in (0.10, 0.11, 0.12):
            pre.append(centre + r * u)
            post.append(centre + ((0.13 if r == 0.10 else r + 0.01) if k in bad else r + 0.01) * u)
    for r in (0.100, 0.101, 0.102):
        pre.append(centre + r * np.array([0, 1.0, 0]))
        post.append(centre + (r + 0.01) * np.array([0, 1.0, 0]))
    poke = gf.poke_share(np.array(pre), np.array(post))
    check(abs(poke - 0.25) < 1e-9, f"metrics: poke share 25 / 100 = 0.25 (got {poke})")

    disc = np.array([[x, 1.6, z] for x in np.arange(-0.2, 0.2001, 0.004) for z in np.arange(-0.2, 0.2001, 0.004)
                     if x * x + z * z <= 0.04 and abs(x) > 1e-9])
    below = np.array([[0.1 * math.cos(a), 1.40, 0.1 * math.sin(a)] for a in np.linspace(0, 6.28, 40)])
    Pb = np.concatenate([disc, below])
    sb = body_mesh(Pb, np.zeros((0, 3), np.int64), np.ones(len(Pb), bool))
    hp, hf = grid_sheet(0.0, 0.25, -0.25, 0.25, 1.619, 50)
    unc = gf.scalp_uncovered_share(hp, hf, sb)
    check(abs(unc - 0.5) <= 0.05, f"metrics: hair on the x > 0 half -> uncovered ~ 0.5 (got {unc:.3f})")

    m = gf.metrics(P, F, P, P, br)
    for key in ("bib_cm2", "poke_share", "scalp_uncovered_share", "max_push_m", "moved_share",
                "largest_component_share", "drop_below_chin_m", "tris"):
        check(key in m, f"metrics: key {key}")
    check(m["tris"] == 200 and m["max_push_m"] == 0 and m["moved_share"] == 0, "metrics: tris 200, nothing moved")
    check(abs(m["drop_below_chin_m"] - (1.45 - 1.37)) < 1e-9, "metrics: drop below chin 0.08")

    best = dict(bib_cm2=8.2, poke_share=0.001, scalp_uncovered_share=0.048, max_push_m=0.118,
                moved_share=0.789, largest_component_share=0.9919, drop_below_chin_m=0.113, tris=95604)
    ok, reasons = gf.gate(best)
    check(ok and reasons == [], f"gate: spike best run passes ({reasons})")
    worst = dict(best, bib_cm2=60, poke_share=0.03, scalp_uncovered_share=0.2, max_push_m=0.2,
                 moved_share=0.95, largest_component_share=0.9)
    ok, reasons = gf.gate(worst)
    text = " ".join(reasons)
    check(not ok and len(reasons) == 6 and all(k in text for k in ("bib", "poke", "scalp", "push", "moved",
                                                                       "component")),
          f"gate: six refusals named ({reasons})")
    check(not gf.gate(dict(best, bib_cm2=float("nan")))[0], "gate: a NaN refuses")


# --- (f) fit_hair end to end ----------------------------------------------------------

def make_glb(P, F, U, *, image=None, joints=None, weights=None, joint_names=None):
    blob = bytearray()
    doc = {"asset": {"version": "2.0"}, "bufferViews": [], "accessors": [], "scene": 0}

    def acc(arr, ctype, typ, target=None, minmax=False):
        raw = arr.tobytes()
        blob.extend(b"\0" * (-len(blob) % 4))
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)}
        if target:
            view["target"] = target
        doc["bufferViews"].append(view)
        blob.extend(raw)
        a = {"bufferView": len(doc["bufferViews"]) - 1, "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        doc["accessors"].append(a)
        return len(doc["accessors"]) - 1
    attrs = {"POSITION": acc(P.astype("<f4"), 5126, "VEC3", 34962, True),
             "TEXCOORD_0": acc(U.astype("<f4"), 5126, "VEC2", 34962)}
    if joints is not None:
        attrs["JOINTS_0"] = acc(joints.astype("<u2"), 5123, "VEC4", 34962)
        attrs["WEIGHTS_0"] = acc(weights.astype("<f4"), 5126, "VEC4", 34962)
    prim = {"attributes": attrs, "indices": acc(F.astype("<u4").reshape(-1), 5125, "SCALAR", 34963)}
    if image is not None:
        blob.extend(b"\0" * (-len(blob) % 4))
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(image)})
        blob.extend(image)
        doc["images"] = [{"bufferView": len(doc["bufferViews"]) - 1, "mimeType": "image/png"}]
        doc["textures"] = [{"source": 0}]
        doc["materials"] = [{"name": "hair", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
                             "alphaMode": "BLEND", "doubleSided": True}]
        prim["material"] = 0
    doc["meshes"] = [{"primitives": [prim]}]
    doc["nodes"] = [{"name": "Body", "mesh": 0}]
    doc["scenes"] = [{"nodes": [0]}]
    if joint_names:
        doc["nodes"][0]["skin"] = 0
        doc["nodes"] += [{"name": n} for n in joint_names]
        doc["skins"] = [{"joints": list(range(1, 1 + len(joint_names)))}]
        doc["scenes"][0]["nodes"] += list(range(1, 1 + len(joint_names)))
    blob.extend(b"\0" * (-len(blob) % 4))
    doc["buffers"] = [{"byteLength": len(blob)}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def png(size=16):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (size, size), (120, 80, 40)).save(out, "PNG")
    return out.getvalue()


def test_fit_hair():
    from app.core import garment_fit as gf
    bu, br = torso_head_bodies()
    unrigged = make_glb(bu.positions, bu.faces, bu.uvs)
    rigged = make_glb(br.positions, br.faces, br.uvs, joints=br.joints, weights=br.weights,
                      joint_names=br.joint_names)
    c = np.array([0, 0.9, 0])
    hair, hf = cap(0.108, c, n_el=31, nlon=120)  # 3-degree grid: a ring lies in the +-0.004 probe band at y 0.96,
    # and the rigged spacing (~1 cm at r 0.187 m) keeps every scalp vertex within 2 cm of hair
    hu = np.stack([np.linspace(0, 1, len(hair)), np.linspace(1, 0, len(hair))], 1)
    prepared = make_glb(4 * (hair - c) + np.array([3, -2, 1]), hf, hu, image=png())
    # 1000 px per unit, column 500 = x 0, row 100 = y 1.0 (the head top)
    lo, hi = bu.positions.min(0), bu.positions.max(0)
    bm = np.zeros((1200, 1000), bool)
    bm[int(round(100 + (1.0 - hi[1]) * 1000)):int(round(100 + (1.0 - lo[1]) * 1000)),
       int(round(500 + lo[0] * 1000)):int(round(500 + hi[0] * 1000))] = True
    gm = np.zeros((1200, 1000), bool)
    hlo, hhi = hair.min(0), hair.max(0)
    gm[int(round(100 + (1.0 - hhi[1]) * 1000)):int(round(100 + (1.0 - hlo[1]) * 1000)),
       int(round(500 + hlo[0] * 1000)):int(round(500 + hhi[0] * 1000))] = True
    res = gf.fit_hair(prepared, unrigged, rigged, bm, gm)
    g = res.garment
    expect = 1.7 * hair + np.array([0, 0.05, 0])
    # the 120 copies of the pole weld into one vertex: every copy stays (each is used by a surviving face), only the
    # 120 faces with two pole corners collapse
    check(len(g.positions) == len(hair), f"fit_hair: all {len(hair)} vertices kept (got {len(g.positions)})")
    err = np.abs(g.positions - expect).max()
    check(err <= 0.005, f"fit_hair: placed within 5 mm of 1.7 * cap + t (max err {err:.4f})")
    check(abs(res.report["k"] - 1.7) <= 0.002, f"fit_hair: k 1.700 (got {res.report['k']:.4f})")
    check(res.ok, f"fit_hair: gate passes ({res.reasons}; {res.metrics})")
    check(g.joint_names == ["mixamorig:Head", "mixamorig:Spine2"] and np.allclose(g.weights[:, 0], 1),
          "fit_hair: all weights Head")
    check(g.image == png() and g.mime == "image/png" and g.material.get("doubleSided") is True,
          "fit_hair: image + material carried")
    try:
        gf.fit_hair(prepared, unrigged, rigged, bm, gm[:1000])
        check(False, "fit_hair: masks of different sizes refused")
    except ValueError:
        check(True, "fit_hair: masks of different sizes refused (no shared framing)")
    check(len(g.indices) == len(hf) - 120, f"fit_hair: the 120 faces collapsing onto the welded pole are dropped "
          f"({len(hf)} -> {len(g.indices)})")


def main():
    test_weld()
    test_framing()
    test_push()
    test_transfer()
    test_weights()
    test_metrics()
    test_fit_hair()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()
