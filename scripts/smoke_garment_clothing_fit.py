#!/usr/bin/env python3
"""Clothing fit (``garment_fit.fit_clothing``, ``clothing_weights``, ``CLOTHING_GATES``) on a synthetic body with hips,
legs and arms; expectations derived by hand (plan ``2026-11-09-base-body-phase5-mesh-items.md``, Task 3).

Usage: ./.venv/bin/python scripts/smoke_garment_clothing_fit.py

No world, no server, no external assets: every mesh is built below (GLB writer + texture from
``smoke_garment_fit.py``).

The fixture body, RIGGED, metres, T-pose, facing +z (closed cylinders, rings every 0.01 m):
    Hips       r 0.15 around the y axis, y 0.95..1.10                      -> Hips 1
    crotch plug r 0.025 around the y axis, y 0.85..0.95                    -> Hips 1  (its bottom cap centre (0, 0.85, 0)
                                                                               is the lowest |x| < 0.03 vertex with Hips
                                                                               weight > 0.3: crotch = 0.85)
    torso      r 0.15, y 1.10..1.40                                        -> Spine2 1, except the chest patch
               (z > 0.12, 1.25 < y < 1.35): x > 0 LeftBreast 1 (extension bone only), x < 0 RightBreast 0.6 + Spine2 0.4
    upper legs r 0.06 around x = +-0.10, y 0.42..0.95                     -> Left/RightUpLeg 1   (+x = the left side)
    lower legs r 0.05 around x = +-0.10, y 0.08..0.38                     -> Left/RightLeg 1
    upper arms r 0.04 along x from +-0.15 to +-0.42 at y 1.34             -> Left/RightArm 1
    forearms   r 0.035 along x from +-0.44 to +-0.70 at y 1.34            -> Left/RightForeArm 1
The UNRIGGED body is the same mesh (same UVs) with the arms turned 45 degrees down about the shoulder (+-0.15, 1.34)
(A-pose), then ``(P - (0, 0.05, 0)) / 1.7``. Height rigged 1.40 - 0.08 = 1.32 m, unrigged 1.32 / 1.7 units
-> k = 1.700 (the arms reach neither the top nor the bottom in either pose).

[1] Skirt blend (``skirt_leg_weights`` / ``clothing_weights`` skirt=True; collision ruling C5, 2026-11-10): zone below
    crotch + 0.05; the leg columns of each zone vertex become the Gaussian average (sigma = 0.16 / 2 = 0.08) of the
    leg columns of the zone vertices within 0.16 m, the other columns are rescaled to the rest (all on Hips when it
    had none); then keep 1.0 at the crotch falling linearly to 0.75 at the hem, the rest of the leg weight to Hips.
    (a) keep alone (smooth_m 0: every vertex its own neighbourhood), crotch 0.85, hem = the lowest point 0.47, a
        vertex LeftUpLeg 1:
        y 0.92 (above the zone 0.90)            -> LeftUpLeg 1 (untouched)
        y 0.87 (zone, above the crotch, t 0)     -> keep 1     -> LeftUpLeg 1
        y 0.66: t = (0.85 - 0.66) / (0.85 - 0.47) = 0.5 -> keep 1 - 0.25 x 0.5 = 0.875 -> LeftUpLeg 0.875, Hips 0.125
        y 0.47 (the hem, t 1)                   -> keep 0.75  -> LeftUpLeg 0.75, Hips 0.25
    (b) smoothing across the legs (keep 1 everywhere), three vertices at y 0.70 on a line: A x -0.05 RightUpLeg 1,
        B x 0 Left 0.5 + Right 0.5, C x +0.05 LeftUpLeg 1, and D x +0.30 LeftUpLeg 1 (0.25 from C: outside 0.16).
        g(0.05) = exp(-0.5 (0.05/0.08)^2) = 0.82258, g(0.10) = exp(-0.5 (0.10/0.08)^2) = 0.45783.
        A: Left = (0.5 x 0.82258 + 0.45783) / (1 + 0.82258 + 0.45783) = 0.86912 / 2.28041 = 0.38113, Right 0.61887;
        C mirrored; B: (0.5 + 0.82258) / 2.64516 = 0.5 each; D alone -> LeftUpLeg 1.
    (c) the rest of the weight: P (0, 0.70, 0) Hips 1, Q (0.05, 0.70, 0) LeftUpLeg 1 (keep 1):
        P: Left = 0.82258 / 1.82258 = 0.45133, its Hips rescaled to the rest 0.54867;
        Q: Left = 1 / 1.82258 = 0.54867, no non-leg weight of its own -> the rest 0.45133 on Hips.
    (d) ``clothing_weights`` on the fixture, points 1 cm outside the upper legs (the 8 nearest body vertices all
        Left/RightUpLeg, the hips rim >= 0.036 m away), all more than 0.16 m apart -> (a)'s numbers:
        (0.17, 0.92) LeftUpLeg 1; (0.17, 0.87) LeftUpLeg 1; (0.17, 0.66) LeftUpLeg 0.875 / Hips 0.125;
        (0.17, 0.47) LeftUpLeg 0.75 / Hips 0.25; (-0.17, 0.66) RightUpLeg 0.875 / Hips 0.125.
        skirt=False: y 0.66 -> LeftUpLeg 1.
[2] Sleeves. A point 1 cm above the left upper arm (0.28, 1.39, 0) -> LeftArm 1; above the forearm
    (0.57, 1.385, 0) -> LeftForeArm 1. ``transfer_skinned`` (the clothing path) and ``transfer`` (the hair path) with
    ``split_y`` below the sleeve (only forearm/hand excluded): a sleeve tube r 0.06 m around the A-pose upper arm
    (40..75 % of its length, 2 cm clear of it) lands on the T-pose arm: every vertex within 5 mm of the same tube
    around the rigged arm, weights LeftArm 1. (From 40 %: at 30 % the ring's inner side, centre (0.207, 1.283) - 0.06 *
    (0.707, 0.707) = (0.165, 1.241), is 0.015 from the torso, nearer than the arm, and rides the torso — the armpit;
    at 40 % it is 0.034 away.) With the hair rule (``split_y=None``: every arm bone excluded) ``transfer`` rides the
    torso instead and misses by > 3 cm.
[3] No extension bone. In front of the LeftBreast-only patch (0.05, 1.30, 0.16): all 8 nearest body vertices carry
    only the extension bone -> the weights come from the nearest vertices with >= 0.5 contract weight -> Spine2 1.
    In front of the right patch (-0.05, 1.30, 0.16): RightBreast 0.6 + Spine2 0.4 restricted to Spine2 0.4,
    renormalised -> Spine2 1. No output joint outside the rig contract.
[4] Gates: the keys are max_push_m / moved_share / largest_component_share / rigged_inside_share; the spike dress
    numbers (max push 0.0293 units x 1.70 = 0.0498 m, moved 38720 / 44950 = 0.861, one component, inside 0.0) and the
    product's on the same dress (0.0501 m, 0.929, 0.9888, 0.0; ``garment_fit.CLOTHING_GATES`` comment) pass, every
    limit refuses by name, NaN refuses.
[5] ``fit_clothing`` end to end: a dress = open surface of revolution around the y axis, radius 0.18 m for
    y 1.20..0.95 and widening linearly to 0.22 m at the hem 0.55 (>= 2 cm clear of hips, torso and legs everywhere,
    so nothing is pushed), generated in its own frame (x4 + shift) and framed through masks at 1000 px per unit.
    Every vertex ends within 5 mm of its design position, k = 1.700 +- 0.002, moved share 0, the gate passes.
    ``is_skirt``: slots top+bottom and the cut below the crotch surrounds the centre line front and back -> True;
    the side vertex (0.20, 0.75, 0): its dress neighbours within 0.16 m all have x > 0.04 and only left-leg donors
    (LeftUpLeg 1 at these heights), so smoothing keeps LeftUpLeg 1; t = (0.85 - 0.75) / (0.85 - 0.55) = 1/3 ->
    keep 1 - 0.25 / 3 = 0.917 -> LeftUpLeg 0.917, Hips 0.083 (+- 0.01, the framing's pixel rounding). Every hem
    vertex (y < 0.56, t 0.97..1, below the crotch: only leg donors, leg total 1) -> Hips 1 - keep = 0.242..0.25 (+-
    0.01); the centre-front hem vertex (0, 0.55, 0.22) lies between the legs -> by symmetry LeftUpLeg = RightUpLeg
    = 0.375 (+- 0.02).
    Slots ["top"] -> no skirt. Two trouser tubes (r 0.075 around each leg: nothing within 0.02 of the centre
    line) -> no skirt even with slot "bottom". Masks of different sizes are refused.
[6] Mesh step: ``garment_mesh.target_tris`` = 25000 for hair (unchanged ``TARGET_TRIS``), 60000 for clothing.
[7] Shoulder blend (the sleeve fix of 2026-11-09, ``transfer_skinned`` / ``bone_transforms``). Own fixture: a torso
    tube r 0.10 around x = -0.16 (y 1.00..1.60, Spine2 1) and a left upper arm r 0.04 along +x from (0, 1.30, 0) to
    (0.30, 1.30, 0), rings every 1 cm, whose skin weight is a BLEND over the first 6 cm: LeftArm w = clip(x / 0.06,
    0, 1), the rest Spine2 — the real deltoid in miniature. The unrigged body is that body posed by linear blend
    skinning (arm turned 45 degrees down about the shoulder (0, 1.30, 0) with those weights), minus (0, 0.05, 0),
    over 1.7; both heights are the torso's 0.60 -> k = 1.700. The sleeve is a tube r 0.06 around the T-pose arm
    from x 0.04 to 0.24 (rings 1 cm, 48 around), posed into the A-pose source with the skin weight of its own x.
    By hand: ``bone_transforms`` fits LeftArm from the rings x >= 0.05 (w >= 0.8, exactly rotated) and Spine2 from
    the torso plus the rings x <= 0.01 (Spine2 >= 0.8) -> both exact up to the 32 vertices of ring x = 0.01, which
    moved 0.167 of the arm motion (0.167 x 2 sin(22.5 deg) x 0.041 = 5.2 mm) and are the body's re-skinning
    residual at p99 (< 6 mm; p50 < 1 mm); the donor part of every sleeve vertex is the arm (its skin 2 cm away, the torso >= 2.6 cm);
    its transfer weight is an inverse-distance mean over arm rings within +-1 cm of its x, i.e. w(x) +- 0.01 / 0.06
    = +- 0.167, and w is 1 for x >= 0.10, so
      - the RIGID part (design x >= 0.12) lands exactly: every vertex within 1 mm of its design, radius about the
        arm axis 0.060 +- 0.001;
      - the BLEND part (x < 0.12) is off by at most 0.167 x |rot - id| <= 0.167 x 2 sin(22.5 deg) x 0.117 (the
        farthest blend vertex from the pivot) = 15 mm;
      - no edge of the sleeve has its two faces fold against each other (the weights are monotone along the arm).
    The nearest-donor transfer of 0b532d33 (``transfer``, still the hair path) on the same fixture is off by
    16.4 mm in the blend part (its 25 smoothing passes of the position delta pull the first rings up: the x = 0.04
    ring centre rises 5.0 mm, the skinned one 1.7 mm) — the smoke demonstrates that it misses the 15 mm bound.
    Real numbers (``~/claude-out/sleeves/report.md``): on the e2e dress the old transfer left 591 of 3975 left-sleeve
    triangles flipped against the A-pose mesh and the cap 32 mm above the skin (A-pose 21 mm); skinned: cap max
    20.5 mm, 16 fold edges of 784, all in the armpit band.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

from smoke_garment_fit import make_glb, png  # noqa: E402

FAILS = []

JOINTS = ["mixamorig:Hips", "mixamorig:Spine2", "mixamorig:LeftUpLeg", "mixamorig:LeftLeg",
          "mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:LeftArm", "mixamorig:LeftForeArm",
          "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:LeftBreast", "mixamorig:RightBreast"]
J = {n.split(":")[1]: i for i, n in enumerate(JOINTS)}
T = np.array([0.0, 0.05, 0.0])
SHOULDER_Y = 1.34


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# --- fixture ---------------------------------------------------------------------------------------------------

def tube(p0, p1, radius, *, nlon=48, step=0.01, caps=True):
    """Cylinder from ``p0`` to ``p1`` (rings every ``step``), closed by fan caps whose centre vertices sit on the axis."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    axis = p1 - p0
    length = np.linalg.norm(axis)
    a = axis / length
    ref = np.array([0.0, 0.0, 1.0]) if abs(a[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(a, ref)
    u /= np.linalg.norm(u)
    v = np.cross(a, u)
    rings = int(round(length / step)) + 1
    ang = np.arange(nlon) * 2 * np.pi / nlon
    P = [p0 + a * s + radius * (np.cos(t) * u + np.sin(t) * v) for s in np.linspace(0, length, rings) for t in ang]
    F = []
    for i in range(rings - 1):
        for j in range(nlon):
            q, r = i * nlon + j, i * nlon + (j + 1) % nlon
            F += [(q, r, r + nlon), (q, r + nlon, q + nlon)]
    if caps:
        for centre, ring in ((p0, 0), (p1, rings - 1)):
            c = len(P)
            P.append(centre)
            F += [(c, ring * nlon + (j + 1) % nlon, ring * nlon + j) for j in range(nlon)]
    return np.array(P), np.array(F, np.int64)


def revolution(profile, *, nlon=96):
    """Open surface of revolution around the y axis through ``[(y, r), ...]`` (top first)."""
    ang = np.arange(nlon) * 2 * np.pi / nlon
    P = np.array([(r * math.cos(t), y, r * math.sin(t)) for y, r in profile for t in ang])
    F = []
    for i in range(len(profile) - 1):
        for j in range(nlon):
            q, r = i * nlon + j, i * nlon + (j + 1) % nlon
            F += [(q, r, r + nlon), (q, r + nlon, q + nlon)]
    return P, np.array(F, np.int64)


def a_pose(P, side):
    """Turn arm points 45 degrees down about the shoulder (side +1 = left arm along +x)."""
    pivot = np.array([0.15 * side, SHOULDER_Y, 0.0])
    th = -side * math.pi / 4
    c, s = math.cos(th), math.sin(th)
    d = P - pivot
    return pivot + np.stack([d[:, 0] * c - d[:, 1] * s, d[:, 0] * s + d[:, 1] * c, d[:, 2]], 1)


def bodies():
    """``(unrigged BodyMesh, rigged BodyMesh)`` of the fixture."""
    from app.core.glb_mesh import BodyMesh
    parts = []   # (P, F, joint, side) side: 0 body, +-1 arm

    def add(mesh, joint, side=0):
        parts.append((mesh[0], mesh[1], joint, side))
    add(tube((0, 0.95, 0), (0, 1.10, 0), 0.15, nlon=96), "Hips")
    add(tube((0, 0.85, 0), (0, 0.95, 0), 0.025, nlon=16), "Hips")
    add(tube((0, 1.10, 0), (0, 1.40, 0), 0.15, nlon=96), "Spine2")
    for side, name in ((1, "Left"), (-1, "Right")):
        add(tube((0.10 * side, 0.42, 0), (0.10 * side, 0.95, 0), 0.06), name + "UpLeg")
        add(tube((0.10 * side, 0.08, 0), (0.10 * side, 0.38, 0), 0.05), name + "Leg")
        add(tube((0.15 * side, SHOULDER_Y, 0), (0.42 * side, SHOULDER_Y, 0), 0.04, nlon=32), name + "Arm", side)
        add(tube((0.44 * side, SHOULDER_Y, 0), (0.70 * side, SHOULDER_Y, 0), 0.035, nlon=32), name + "ForeArm",
            side)
    Pr, Pu, F, Jn, Wn, off = [], [], [], [], [], 0
    for P, Fp, joint, side in parts:
        n = len(P)
        jj = np.zeros((n, 4), np.int64)
        ww = np.zeros((n, 4))
        jj[:, 0] = J[joint]
        ww[:, 0] = 1.0
        if joint == "Spine2":
            patch = (P[:, 2] > 0.12) & (P[:, 1] > 1.25) & (P[:, 1] < 1.35)
            left, right = patch & (P[:, 0] > 0), patch & (P[:, 0] < 0)
            jj[left, 0] = J["LeftBreast"]
            jj[right, 0], ww[right, 0] = J["RightBreast"], 0.6
            jj[right, 1], ww[right, 1] = J["Spine2"], 0.4
        Pr.append(P)
        Pu.append((a_pose(P, side) if side else P) - T)
        F.append(Fp + off)
        Jn.append(jj)
        Wn.append(ww)
        off += n
    Pr, Pu, F = np.concatenate(Pr), np.concatenate(Pu) / 1.7, np.concatenate(F)
    n = len(Pr)
    uv = np.stack([(np.arange(n) + 0.5) / n, np.full(n, 0.5)], 1)
    rig = BodyMesh(positions=Pr, faces=F, uvs=uv, joints=np.concatenate(Jn), weights=np.concatenate(Wn),
                   joint_names=list(JOINTS))
    unrig = BodyMesh(positions=Pu, faces=F, uvs=uv, joints=np.zeros((n, 4), np.int64), weights=np.zeros((n, 4)),
                     joint_names=[])
    return unrig, rig


def dense(Jx, Wx, names):
    out = np.zeros((len(Jx), len(names)))
    np.add.at(out, (np.repeat(np.arange(len(Jx)), 4), Jx.ravel()), Wx.ravel())
    return out


def weight_of(D, names, i, bone):
    return float(D[i, names.index("mixamorig:" + bone)]) if "mixamorig:" + bone in names else 0.0


# --- [1] skirt blend -------------------------------------------------------------------------------------------

def test_skirt_blend(rig):
    from app.core import garment_fit as gf
    check(abs(gf.crotch_height(rig) - 0.85) < 1e-6, f"[1] crotch = 0.85 (got {gf.crotch_height(rig):.4f})")
    check((gf.SKIRT_KEEP_TOP, gf.SKIRT_KEEP_HEM, gf.SKIRT_SMOOTH_M, gf.SKIRT_ZONE_M) == (1.0, 0.75, 0.16, 0.05),
          "[1] constants keep 1.0 -> 0.75, smooth 0.16 m, zone 0.05 m")
    # columns: 0 Hips, 1 LeftUpLeg, 2 RightUpLeg
    legs, hips = [1, 2], 0

    def run(pts, W, **kw):
        return gf.skirt_leg_weights(np.asarray(pts, float), np.asarray(W, float), legs=legs, hips=hips,
                                    crotch=0.85, **kw)

    def near(a, b):
        return bool(np.allclose(a, b, atol=1e-4))
    # (a) keep alone
    pts = [[0.17, 0.92, 0], [0.17, 0.87, 0], [0.17, 0.66, 0], [0.17, 0.47, 0]]
    out = run(pts, [[0, 1, 0]] * 4, smooth_m=0.0)
    for i, want in enumerate([[0, 1, 0], [0, 1, 0], [0.125, 0.875, 0], [0.25, 0.75, 0]]):
        check(near(out[i], want), f"[1a] keep y {pts[i][1]} -> {want} (got {np.round(out[i], 4).tolist()})")
    # (b) smoothing across the legs
    pts = [[-0.05, 0.7, 0], [0, 0.7, 0], [0.05, 0.7, 0], [0.30, 0.7, 0]]
    out = run(pts, [[0, 0, 1], [0, 0.5, 0.5], [0, 1, 0], [0, 1, 0]], keep_top=1.0, keep_hem=1.0)
    for i, want in enumerate([[0, 0.38113, 0.61887], [0, 0.5, 0.5], [0, 0.61887, 0.38113], [0, 1, 0]]):
        check(near(out[i], want), f"[1b] smooth x {pts[i][0]} -> {want} (got {np.round(out[i], 5).tolist()})")
    # (c) the rest of the weight
    out = run([[0, 0.7, 0], [0.05, 0.7, 0]], [[1, 0, 0], [0, 1, 0]], keep_top=1.0, keep_hem=1.0)
    check(near(out[0], [0.54867, 0.45133, 0]) and near(out[1], [0.45133, 0.54867, 0]),
          f"[1c] rest: Hips rescaled / all on Hips (got {np.round(out, 5).tolist()})")
    check(np.allclose(out.sum(1), 1), "[1c] rows sum to 1")
    # (d) clothing_weights on the fixture
    pts = np.array([[0.17, 0.92, 0], [0.17, 0.87, 0], [0.17, 0.66, 0], [0.17, 0.47, 0], [-0.17, 0.66, 0]])
    Jx, Wx = gf.clothing_weights(pts, rig, skirt=True)
    D = dense(Jx, Wx, rig.joint_names)
    names = rig.joint_names
    want = [(0, {"LeftUpLeg": 1.0}), (1, {"LeftUpLeg": 1.0, "Hips": 0.0}), (2, {"LeftUpLeg": 0.875, "Hips": 0.125}),
            (3, {"LeftUpLeg": 0.75, "Hips": 0.25}), (4, {"RightUpLeg": 0.875, "Hips": 0.125})]
    for i, bones in want:
        got = {b: round(weight_of(D, names, i, b), 4) for b in bones}
        ok = all(abs(got[b] - w) <= 1e-3 for b, w in bones.items()) and abs(D[i].sum() - 1) < 1e-6
        check(ok, f"[1d] skirt y {pts[i, 1]} x {pts[i, 0]}: {bones} (got {got})")
    Jn, Wn = gf.clothing_weights(pts[2:3], rig, skirt=False)
    Dn = dense(Jn, Wn, names)
    check(abs(weight_of(Dn, names, 0, "LeftUpLeg") - 1) < 1e-3, "[1d] no skirt: y 0.66 stays LeftUpLeg 1")


# --- [2] sleeves -------------------------------------------------------------------------------------------------

def sleeve():
    """Rigged T-pose sleeve tube (open) around the left upper arm, 40..75 % of its length, r 0.06."""
    L0, L1 = 0.15 + 0.4 * 0.27, 0.15 + 0.75 * 0.27
    P, F = tube((L0, SHOULDER_Y, 0), (L1, SHOULDER_Y, 0), 0.06, nlon=48, caps=False)
    return P, F


def test_sleeves(unrig, rig):
    from app.core import garment_fit as gf
    names = rig.joint_names
    pts = np.array([[0.28, 1.39, 0], [0.57, 1.385, 0]])
    D = dense(*gf.clothing_weights(pts, rig, skirt=False), names)
    check(abs(weight_of(D, names, 0, "LeftArm") - 1) < 1e-3, "[2] point above the upper arm -> LeftArm 1")
    check(abs(weight_of(D, names, 1, "LeftForeArm") - 1) < 1e-3, "[2] point above the forearm -> LeftForeArm 1")
    P, F = sleeve()
    Q = (a_pose(P, 1) - T) / 1.7
    X, report = gf.transfer_skinned(Q, unrig, rig, faces=F, k=1.7, split_y=Q[:, 1].min() - 1.0)
    err = np.abs(X - P).max()
    check(err <= 0.005, f"[2] skinned: sleeve follows the arm A -> T within 5 mm (max err {err:.4f}; {report})")
    Xt, report_t = gf.transfer(Q, unrig, rig, faces=F, split_y=Q[:, 1].min() - 1.0)
    err_t = np.abs(Xt - P).max()
    check(err_t <= 0.005, f"[2] hair-path transfer: sleeve within 5 mm too (max err {err_t:.4f})")
    Ds = dense(*gf.clothing_weights(X, rig, skirt=False), names)
    check(np.all(Ds[:, names.index("mixamorig:LeftArm")] > 0.999), "[2] every sleeve vertex weighted LeftArm 1")
    Xh, _ = gf.transfer(Q, unrig, rig, faces=F)
    err_h = np.linalg.norm(Xh - P, axis=1).max()
    check(err_h > 0.03, f"[2] the hair rule (every arm bone excluded) misses the arm (max err {err_h:.3f} m)")


# --- [3] extension bones -----------------------------------------------------------------------------------------

def test_extension(rig):
    from app.core import garment_fit as gf
    from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
    names = rig.joint_names
    pts = np.array([[0.05, 1.30, 0.16], [-0.05, 1.30, 0.16]])
    Jx, Wx = gf.clothing_weights(pts, rig, skirt=False)
    D = dense(Jx, Wx, names)
    for i in range(2):
        check(abs(weight_of(D, names, i, "Spine2") - 1) < 1e-3,
              f"[3] chest point {pts[i].tolist()} -> Spine2 1 (got {D[i].round(3).tolist()})")
    used = {names[j] for j, w in zip(Jx.ravel(), Wx.ravel()) if w > 0}
    check(all(norm_bone_name(n) in BASE_JOINT_KEYS for n in used), f"[3] only contract bones weighted ({used})")


# --- [4] gates ---------------------------------------------------------------------------------------------------

def test_gates():
    from app.core import garment_fit as gf
    G = gf.CLOTHING_GATES
    check(set(G) == {"max_push_m", "moved_share", "largest_component_share", "rigged_inside_share"},
          f"[4] clothing gate keys ({sorted(G)})")
    spike = {"max_push_m": 0.0498, "moved_share": 0.861, "largest_component_share": 1.0, "rigged_inside_share": 0.0}
    ok, reasons = gf.gate(spike, G)
    check(ok, f"[4] the spike dress numbers pass ({reasons})")
    product = {"max_push_m": 0.0501, "moved_share": 0.929, "largest_component_share": 0.9888,
               "rigged_inside_share": 0.0}
    ok, reasons = gf.gate(product, G)
    check(ok, f"[4] the product numbers on the spike dress pass ({reasons})")
    for key, (kind, limit, _label) in G.items():
        bad = dict(spike, **{key: limit * 1.5 + 0.01 if kind == "max" else limit * 0.5})
        ok, reasons = gf.gate(bad, G)
        check(not ok and len(reasons) == 1 and reasons[0].startswith(key), f"[4] {key} beyond its limit refuses "
              f"({reasons})")
    check(not gf.gate(dict(spike, moved_share=float("nan")), G)[0], "[4] NaN refuses")


# --- [5] fit_clothing end to end ---------------------------------------------------------------------------------

def dress():
    profile = [(round(1.20 - 0.01 * i, 4), 0.18) for i in range(25)]                     # 1.20 .. 0.96
    profile += [(round(0.95 - 0.01 * i, 4), 0.18 + 0.04 * (0.01 * i) / 0.40) for i in range(41)]   # 0.95 .. 0.55
    return revolution(profile)


def masks_for(unrig, design_u):
    def rect(lo, hi):
        m = np.zeros((1200, 1000), bool)
        m[int(round(100 + (1.0 - hi[1]) * 1000)):int(round(100 + (1.0 - lo[1]) * 1000)),
          int(round(500 + lo[0] * 1000)):int(round(500 + hi[0] * 1000))] = True
        return m
    return rect(unrig.positions.min(0), unrig.positions.max(0)), rect(design_u.min(0), design_u.max(0))


def test_fit_clothing(unrig, rig):
    from app.core import garment_fit as gf
    from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
    P, F = dress()
    design_u = (P - T) / 1.7
    n = len(P)
    U = np.stack([(np.arange(n) + 0.5) / n, np.full(n, 0.25)], 1)
    prepared = make_glb(4 * design_u + np.array([3, -2, 1]), F, U, image=png())
    unrigged = make_glb(unrig.positions, unrig.faces, unrig.uvs)
    rigged = make_glb(rig.positions, rig.faces, rig.uvs, joints=rig.joints, weights=rig.weights,
                      joint_names=rig.joint_names)
    bm, gm = masks_for(unrig, design_u)
    res = gf.fit_clothing(prepared, unrigged, rigged, masks={"body": bm, "garment": gm}, slots=["top", "bottom"])
    g = res.garment
    check(len(g.positions) == n, f"[5] all {n} vertices kept (got {len(g.positions)})")
    err = np.abs(g.positions - P).max()
    check(err <= 0.005, f"[5] dress placed within 5 mm of its design (max err {err:.4f})")
    check(abs(res.report["k"] - 1.7) <= 0.002, f"[5] k 1.700 (got {res.report['k']:.4f})")
    check(res.metrics["moved_share"] == 0 and res.metrics["max_push_m"] < 1e-3,
          f"[5] nothing pushed ({res.metrics})")
    check(res.ok, f"[5] gate passes ({res.reasons}; {res.metrics})")
    check(res.report.get("skirt") is True, f"[5] the dress is a skirt (report skirt {res.report.get('skirt')})")
    check(all(norm_bone_name(x) in BASE_JOINT_KEYS for x in g.joint_names), f"[5] contract joints ({g.joint_names})")
    D = dense(g.joints, g.weights, g.joint_names)
    i = int(np.argmin(np.linalg.norm(P - np.array([0.20, 0.75, 0.0]), axis=1)))
    got = (weight_of(D, g.joint_names, i, "LeftUpLeg"), weight_of(D, g.joint_names, i, "Hips"))
    check(abs(got[0] - 11 / 12) <= 0.01 and abs(got[1] - 1 / 12) <= 0.01,
          f"[5] side vertex y 0.75 -> LeftUpLeg 0.917 / Hips 0.083 (got {got[0]:.3f} / {got[1]:.3f})")
    hem = P[:, 1] < 0.56
    hips = D[:, g.joint_names.index("mixamorig:Hips")]
    check(np.all((hips[hem] > 0.232) & (hips[hem] < 0.26)),
          f"[5] every hem vertex Hips 0.242..0.25 (+-0.01) (min {hips[hem].min():.4f} max {hips[hem].max():.4f})")
    i = int(np.argmin(np.linalg.norm(P - np.array([0.0, 0.55, 0.22]), axis=1)))
    lr = (weight_of(D, g.joint_names, i, "LeftUpLeg"), weight_of(D, g.joint_names, i, "RightUpLeg"))
    check(abs(lr[0] - 0.375) <= 0.02 and abs(lr[1] - 0.375) <= 0.02,
          f"[5] centre-front hem vertex: LeftUpLeg = RightUpLeg = 0.375 (got {lr[0]:.3f} / {lr[1]:.3f})")
    check(g.image == png() and g.mime == "image/png", "[5] the garment image is carried")

    Xr = g.positions
    check(gf.is_skirt(Xr, rig, ["top", "bottom"]) is True, "[5] is_skirt: slots top+bottom, one surface -> True")
    check(gf.is_skirt(Xr, rig, ["top"]) is False, "[5] is_skirt: slot top only -> False")
    left, lf = tube((0.10, 0.45, 0), (0.10, 0.95, 0), 0.075, caps=False)
    right, rf = tube((-0.10, 0.45, 0), (-0.10, 0.95, 0), 0.075, caps=False)
    trousers = np.concatenate([left, right])
    check(gf.is_skirt(trousers, rig, ["bottom"]) is False, "[5] is_skirt: two leg tubes -> False")
    try:
        gf.fit_clothing(prepared, unrigged, rigged, masks={"body": bm, "garment": gm[:1000]}, slots=["top"])
        check(False, "[5] masks of different sizes refused")
    except ValueError:
        check(True, "[5] masks of different sizes refused (no shared framing)")


# --- [7] shoulder blend --------------------------------------------------------------------------------------------

BLEND_PIVOT = np.array([0.0, 1.30, 0.0])
BLEND_M = 0.06


def _turn45(P):
    th = -math.pi / 4
    c, s = math.cos(th), math.sin(th)
    d = P - BLEND_PIVOT
    return BLEND_PIVOT + np.stack([d[:, 0] * c - d[:, 1] * s, d[:, 0] * s + d[:, 1] * c, d[:, 2]], 1)


def _pose(P, w):
    """Linear blend skinning of ``P`` between the turned arm (weight ``w``) and rest, into the unrigged frame."""
    return (w[:, None] * _turn45(P) + (1 - w)[:, None] * P - T) / 1.7


def shoulder_bodies():
    from app.core.glb_mesh import BodyMesh
    Pt, Ft = tube((-0.16, 1.00, 0), (-0.16, 1.60, 0), 0.10, nlon=64)
    Pa, Fa = tube((0.0, 1.30, 0), (0.30, 1.30, 0), 0.04, nlon=32)
    P = np.concatenate([Pt, Pa])
    F = np.concatenate([Ft, Fa + len(Pt)])
    w = np.concatenate([np.zeros(len(Pt)), np.clip(Pa[:, 0] / BLEND_M, 0, 1)])
    names = ["mixamorig:Spine2", "mixamorig:LeftArm"]
    Jn = np.zeros((len(P), 4), np.int64)
    Wn = np.zeros((len(P), 4))
    Jn[:, 0], Wn[:, 0] = 1, w
    Jn[:, 1], Wn[:, 1] = 0, 1 - w
    n = len(P)
    uv = np.stack([(np.arange(n) + 0.5) / n, np.full(n, 0.5)], 1)
    rig = BodyMesh(positions=P, faces=F, uvs=uv, joints=Jn, weights=Wn, joint_names=names)
    unrig = BodyMesh(positions=_pose(P, w), faces=F, uvs=uv, joints=np.zeros((n, 4), np.int64),
                     weights=np.zeros((n, 4)), joint_names=[])
    return unrig, rig


def fold_edges(F, P0, P1):
    """Edges whose two faces agree in orientation in ``P0`` but not in ``P1`` (or the reverse)."""
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E.sort(1)
    keys = E[:, 0] * (E.max() + 1) + E[:, 1]
    order = np.argsort(keys, kind="stable")
    ks = keys[order]
    same = ks[1:] == ks[:-1]
    f = np.repeat(np.arange(len(F)), 3)[order]
    a, b = f[:-1][same], f[1:][same]

    def nrm(P):
        N = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
        return N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-14)
    N0, N1 = nrm(P0), nrm(P1)
    return int((((N0[a] * N0[b]).sum(1) > 0) != ((N1[a] * N1[b]).sum(1) > 0)).sum())


def test_shoulder_blend():
    from app.core import garment_fit as gf
    unrig, rig = shoulder_bodies()
    check(abs(np.ptp(rig.positions[:, 1]) / np.ptp(unrig.positions[:, 1]) - 1.7) < 1e-9, "[7] fixture k = 1.700")
    P, F = tube((0.04, 1.30, 0), (0.24, 1.30, 0), 0.06, nlon=48, caps=False)
    Q = _pose(P, np.clip(P[:, 0] / BLEND_M, 0, 1))
    X, report = gf.transfer_skinned(Q, unrig, rig, faces=F, k=1.7, split_y=Q[:, 1].min() - 1.0)
    err = np.linalg.norm(X - P, axis=1)
    rigid = P[:, 0] >= 0.12
    radius = np.linalg.norm((X - BLEND_PIVOT)[:, 1:], axis=1)
    check(err[rigid].max() <= 0.001, f"[7] rigid part of the sleeve lands exactly (max err {err[rigid].max()*1000:.2f} mm)")
    check(abs(radius[rigid] - 0.06).max() <= 0.001,
          f"[7] rigid part radius 0.060 +- 0.001 (got {radius[rigid].min():.4f}..{radius[rigid].max():.4f})")
    check(err[~rigid].max() <= 0.015, f"[7] blend part within the 15 mm bound (max err {err[~rigid].max()*1000:.1f} mm)")
    folds = fold_edges(F, Q, X)
    check(folds == 0, f"[7] no folded sleeve edge ({folds})")
    check(report.get("method") == "skinned" and report.get("bones") == 2 and report.get("body_lbs_res_p50_m", 1) < 0.001
          and report.get("body_lbs_res_p99_m", 1) < 0.006,
          f"[7] both bones fitted, the body re-skinned to p50 < 1 mm, p99 < 6 mm "
          f"({ {k: round(report.get(k, -1), 5) for k in ('bones', 'body_lbs_res_p50_m', 'body_lbs_res_p99_m')} })")
    first = np.abs(P[:, 0] - 0.04) < 1e-6
    rise = X[first, 1].mean() - 1.30
    Xo, _ = gf.transfer(Q, unrig, rig, faces=F, split_y=Q[:, 1].min() - 1.0)
    err_o = np.linalg.norm(Xo - P, axis=1)
    rise_o = Xo[first, 1].mean() - 1.30
    check(err_o[~rigid].max() > 0.015,
          f"[7] the 0b532d33 transfer misses the bound on the same fixture (max err {err_o[~rigid].max()*1000:.1f} mm, "
          f"first ring rises {rise_o*1000:.1f} mm vs {rise*1000:.1f} mm skinned)")


# --- [6] mesh step target ----------------------------------------------------------------------------------------

def test_mesh_target():
    from app.core import garment_mesh as gm
    check(gm.TARGET_TRIS == 25000 and gm.target_tris("hair") == 25000, "[6] hair decimation target 25000")
    check(gm.target_tris("clothing") == 60000, f"[6] clothing decimation target 60000 (got {gm.target_tris('clothing')})")


def main():
    unrig, rig = bodies()
    test_skirt_blend(rig)
    test_sleeves(unrig, rig)
    test_extension(rig)
    test_gates()
    test_fit_clothing(unrig, rig)
    test_mesh_target()
    test_shoulder_blend()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()
