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

[1] Skirt blend (``clothing_weights``, skirt=True; crotch 0.85, zone below crotch + 0.05 = 0.90, keep 0.5 from the
    crotch up, 0.0 at the hem, linear in between). Points 1 cm outside the left upper leg (x 0.17, z 0), where the 8
    nearest body vertices are all LeftUpLeg (the hips rim (0.15, 0.95) is >= 0.036 m away, the leg vertices within
    0.013 m), hem = the lowest point 0.47:
        y 0.92 (above the zone)                 -> LeftUpLeg 1
        y 0.87 (zone, above the crotch)          -> keep 0.5   -> LeftUpLeg 0.5, Hips 0.5
        y 0.66: t = (0.85 - 0.66) / (0.85 - 0.47) = 0.5 -> keep 0.25 -> LeftUpLeg 0.25, Hips 0.75
        y 0.47 (the hem)                        -> keep 0     -> Hips 1
    The mirrored point (-0.17, 0.66, 0) -> RightUpLeg 0.25, Hips 0.75. skirt=False: y 0.87 -> LeftUpLeg 1.
[2] Sleeves. A point 1 cm above the left upper arm (0.28, 1.39, 0) -> LeftArm 1; above the forearm
    (0.57, 1.385, 0) -> LeftForeArm 1. ``transfer`` with ``split_y`` below the sleeve (only forearm/hand excluded):
    a sleeve tube r 0.06 m around the A-pose upper arm (40..75 % of its length, 2 cm clear of it) lands on the T-pose
    arm: every vertex within 5 mm of the same tube around the rigged arm, weights LeftArm 1. (From 40 %: at 30 % the
    ring's inner side, centre (0.207, 1.283) - 0.06 * (0.707, 0.707) = (0.165, 1.241), is 0.015 from the torso, nearer
    than the arm, and rides the torso — the armpit; at 40 % it is 0.034 away.) With the hair rule
    (``split_y=None``: every arm bone excluded) it rides the torso instead and misses by > 3 cm.
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
    the side vertex (0.20, 0.75, 0): t = (0.85 - 0.75) / (0.85 - 0.55) = 1/3 -> keep 1/3 -> LeftUpLeg 0.333,
    Hips 0.667 (+- 0.01, the vertex moves by the framing's pixel rounding); every hem vertex (y < 0.56) Hips 1.
    Slots ["top"] -> no skirt. Two trouser tubes (r 0.075 around each leg: nothing within 0.02 of the centre
    line) -> no skirt even with slot "bottom". Masks of different sizes are refused.
[6] Mesh step: ``garment_mesh.target_tris`` = 25000 for hair (unchanged ``TARGET_TRIS``), 60000 for clothing.
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
    pts = np.array([[0.17, 0.92, 0], [0.17, 0.87, 0], [0.17, 0.66, 0], [0.17, 0.47, 0], [-0.17, 0.66, 0]])
    Jx, Wx = gf.clothing_weights(pts, rig, skirt=True)
    D = dense(Jx, Wx, rig.joint_names)
    names = rig.joint_names
    want = [(0, {"LeftUpLeg": 1.0}), (1, {"LeftUpLeg": 0.5, "Hips": 0.5}), (2, {"LeftUpLeg": 0.25, "Hips": 0.75}),
            (3, {"Hips": 1.0}), (4, {"RightUpLeg": 0.25, "Hips": 0.75})]
    for i, bones in want:
        got = {b: round(weight_of(D, names, i, b), 4) for b in bones}
        ok = all(abs(got[b] - w) <= 1e-3 for b, w in bones.items()) and abs(D[i].sum() - 1) < 1e-6
        check(ok, f"[1] skirt y {pts[i, 1]} x {pts[i, 0]}: {bones} (got {got})")
    Jn, Wn = gf.clothing_weights(pts[1:2], rig, skirt=False)
    Dn = dense(Jn, Wn, names)
    check(abs(weight_of(Dn, names, 0, "LeftUpLeg") - 1) < 1e-3, "[1] no skirt: y 0.87 stays LeftUpLeg 1")


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
    X, report = gf.transfer(Q, unrig, rig, faces=F, split_y=Q[:, 1].min() - 1.0)
    err = np.abs(X - P).max()
    check(err <= 0.005, f"[2] sleeve follows the arm A -> T within 5 mm (max err {err:.4f}; {report})")
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
    check(abs(got[0] - 1 / 3) <= 0.01 and abs(got[1] - 2 / 3) <= 0.01,
          f"[5] side vertex y 0.75 -> LeftUpLeg 0.333 / Hips 0.667 (got {got[0]:.3f} / {got[1]:.3f})")
    hem = P[:, 1] < 0.56
    hips = D[:, g.joint_names.index("mixamorig:Hips")]
    check(np.all(hips[hem] > 0.999), f"[5] every hem vertex Hips 1 (min {hips[hem].min():.4f})")
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
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()
