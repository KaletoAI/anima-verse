#!/usr/bin/env python3
"""Ruling A72 — a body vertex whose UV match lies elsewhere on the rigged body no longer drags the piece along
(``garment_fit.trusted_donor_weights`` in ``transfer_skinned``), and the fit is gated on its longest new edge
(``new_edge_max``, ``NEW_EDGE_MAX_M``, the ``new_edge_max_m`` gate) — on a synthetic skirt with a slit, no world, no
hub, no external asset. Every number below is derived by hand.

Usage:
    ./.venv/bin/python scripts/smoke_fit_uv_mismatch.py

The bodies are ``smoke_garment_clothing_fit.bodies()`` with the arms of the unrigged body turned A_POSE_DEG = 70
degrees down about the shoulders (+-0.15, 1.34) instead of 45 (the generated bases turn them 60 - 77: Kai 59.8, Ylva
75.9, Kira 76.8): rigged in metres, T-pose, facing +z; unrigged = that pose minus (0, 0.05, 0), over 1.7 -> k 1.700.
Every bone moves rigidly, so the body's own linear-blend residual is 0 for every correctly matched vertex. Each vertex
has its own UV ((i + 0.5) / n, 0.5).

The MISMATCH (Kira's ``base20d5701a``: 54 vertices at the navel whose nearest rigged UV lies on the right arm): the
unrigged Hips-tube vertices with z > 0, |x| <= 0.06 and 0.97 <= y <= 1.05 (rigged frame) take the UVs of the first
right-forearm vertices. The Hips tube is r 0.15 with 96 vertices per ring (3.75 deg apart): |x| = 0.15 sin(d) <= 0.06
holds for d <= 23.58 deg from the front, i.e. 13 angles (0, +-3.75 .. +-22.5; 26.25 gives x 0.0663) on each of the 9
rings y 0.97 .. 1.05 -> 117 vertices (Kira's skirt: 118 sleeve vertices). Their correspondence is exact in UV
(distance 0) and wrong in place: their skin is the right forearm's (RightForeArm 1).

[1] ``trusted_donor_weights``: the bones carry a mismatched vertex by the right arm's turn about (-0.15, 1.34); seen
    from that pivot the patch lies 0.304 .. 0.424 m away, 37.7 .. 49.3 deg off the A-pose arm's direction (-110 deg;
    the patch's corners (-0.0574, 1.05) at -72.3 deg and (0.0574, 0.97) at -60.7 deg), and the turn keeps both — so
    it lands at least 0.304 x sin(37.7 deg) - 0.035 (the forearm's radius) = 0.151 m from every forearm vertex, its
    match among them: beyond BONE_CORE_OUTLIER_M 0.05. Every other vertex is carried exactly onto its match (residual
    0; the forearm's bone core is refitted without the 117 outliers). -> exactly 117 mismatched, each given the skin
    of the nearest matched unrigged vertex — a Hips-tube neighbour 1 cm away (Hips 1); every other skin unchanged.
[2] The skirt: an open surface of revolution about the y axis, radius 0.17 from y 1.06 to 0.95 (2 cm clear of the
    Hips tube), then widening linearly to 0.20 at the hem 0.75 (>= 4 cm clear of the legs), 96 around, rings every
    1 cm; the SLIT: the faces of the 3 segments at 112.5 .. 123.75 deg of the ring (x = r cos t < 0, z = r sin t > 0:
    front, the character's right side) below y 0.86. Placed by the same box masks as ``smoke_garment_clothing_fit``
    [5] (k = 1.700). Nothing is pushed (clear by more than CLEAR_M 0.0119 everywhere).
    New code: report ``uv_mismatched_donors`` 117, ``sleeve_vertices`` 0 (no arm-nearest donor is left at the
    waist), every vertex within 5 mm of its design position (the framing's pixel rounding, as [5] there),
    ``new_edge_max_m`` <= 0.005 (no edge grows by more than the placement error), the gate passes.
[3] The gate ``new_edge_max_m`` ("max", NEW_EDGE_MAX_M) with NEW_EDGE_MAX_M = 0.17: the armpit's opening
    2 r sin(theta / 2) on the three bases, the largest Kai's 2 x 0.168 x sin(29.9 deg) = 0.1675 rounded up (the
    comment in garment_fit.py). ``new_edge_max`` by hand: a triangle (0,0,0) (0.01,0,0) (0,0.01,0) whose second
    vertex moves to (0.20,0,0): the edge 0-1 grows 0.20 - 0.01 = 0.19, the edge 1-2 from 0.014142 to
    sqrt(0.2^2 + 0.01^2) = 0.200250 (0.186107) -> 0.19; the gate refuses 0.19 and passes 0.17 (the limit itself).
    It is a gate on a body shape too (not a placement key).
[4] The old code (pinned at 954235bda3e16b13245e76835df57f2e9039b497, the main HEAD this fix starts from) on the same
    skirt: the waistband's front faces the 117 mismatched donors (2 cm away, the nearest part = the right arm), so
    ``sleeve_vertices`` marks them as a right sleeve connected above the waist and they ride the right arm's turn
    of 70 deg: a waistband vertex 0.30 - 0.42 m from the pivot moves 2 r sin(35 deg) = 0.35 - 0.49 m, its neighbours
    beside the patch stay (the stretched-triangle relaxation spreads part of it). Measured that day: 117 sleeve
    vertices and a longest new edge of 0.238 m (this module's ``new_edge_max``) — beyond NEW_EDGE_MAX_M 0.17, so the
    new gate refuses it; at the fixture's own 45 deg it is 0.158 m (the A-pose of the generated bases is 60 - 77).
"""
import importlib.util
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import smoke_garment_clothing_fit as scf  # noqa: E402
from smoke_garment_clothing_fit import SHOULDER_Y, T, bodies, masks_for  # noqa: E402
from smoke_garment_fit import make_glb, png  # noqa: E402

OLD_COMMIT = "954235bda3e16b13245e76835df57f2e9039b497"
FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


A_POSE_DEG = 70.0


def a_pose_75(P, side):
    """``smoke_garment_clothing_fit.a_pose`` at A_POSE_DEG instead of 45 degrees (Kira's base turns its arms 76.8)."""
    pivot = np.array([0.15 * side, SHOULDER_Y, 0.0])
    th = -side * math.radians(A_POSE_DEG)
    c, s = math.cos(th), math.sin(th)
    d = P - pivot
    return pivot + np.stack([d[:, 0] * c - d[:, 1] * s, d[:, 0] * s + d[:, 1] * c, d[:, 2]], 1)


def mismatched_bodies():
    """The fixture (arms at A_POSE_DEG) with the navel vertices of the unrigged body matched (by UV) onto the right
    forearm."""
    from app.core.glb_mesh import BodyMesh
    scf.a_pose = a_pose_75
    unrig, rig = bodies()
    Pr = rig.positions
    belly = (Pr[:, 2] > 0) & (np.abs(Pr[:, 0]) <= 0.06 + 1e-9) & (Pr[:, 1] >= 0.97 - 1e-9) & (Pr[:, 1] <= 1.05 + 1e-9)
    belly &= np.abs(np.hypot(Pr[:, 0], Pr[:, 2]) - 0.15) < 1e-6          # on the Hips tube's wall
    forearm = np.nonzero(rig.joints[:, 0] == rig.joint_names.index("mixamorig:RightForeArm"))[0]
    uv = unrig.uvs.copy()
    rows = np.nonzero(belly)[0]
    uv[rows] = rig.uvs[forearm[:len(rows)]]
    unrig = BodyMesh(positions=unrig.positions, faces=unrig.faces, uvs=uv, joints=unrig.joints,
                     weights=unrig.weights, joint_names=unrig.joint_names)
    return unrig, rig, rows


def skirt():
    """Open surface of revolution with a slit at the front right (see [2]) -> (P, F)."""
    nlon = 96
    profile = [(round(1.06 - 0.01 * i, 4), 0.17) for i in range(12)]                          # 1.06 .. 0.95
    profile += [(round(0.94 - 0.01 * i, 4), 0.17 + 0.03 * (0.01 * (i + 1)) / 0.20) for i in range(20)]  # .. 0.75
    ang = np.arange(nlon) * 2 * np.pi / nlon
    P = np.array([(r * math.cos(t), y, r * math.sin(t)) for y, r in profile for t in ang])
    F = []
    for i in range(len(profile) - 1):
        for j in range(nlon):
            if 30 <= j <= 32 and profile[i + 1][0] < 0.86:      # 112.5 .. 123.75 deg, below y 0.86: the slit
                continue
            q, r = i * nlon + j, i * nlon + (j + 1) % nlon
            F += [(q, r, r + nlon), (q, r + nlon, q + nlon)]
    F = np.array(F, np.int64)
    used = np.unique(F)
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    return P[used], remap[F]


def fit(gf, unrig, rig):
    P, F = skirt()
    design_u = (P - T) / 1.7
    n = len(P)
    U = np.stack([(np.arange(n) + 0.5) / n, np.full(n, 0.25)], 1)
    prepared = make_glb(4 * design_u + np.array([3, -2, 1]), F, U, image=png())
    unrigged = make_glb(unrig.positions, unrig.faces, unrig.uvs)
    rigged = make_glb(rig.positions, rig.faces, rig.uvs, joints=rig.joints, weights=rig.weights,
                      joint_names=rig.joint_names)
    bm, gm = masks_for(unrig, design_u)
    return P, gf.fit_clothing(prepared, unrigged, rigged, masks={"body": bm, "garment": gm}, slots=["bottom"])


def test_trusted(gf, unrig, rig, rows):
    corr, _dist = gf.uv_correspondence(unrig, rig)
    k = float(np.ptp(rig.positions[:, 1]) / np.ptp(unrig.positions[:, 1]))
    check(f"[0] k 1.700 (got {k:.4f})", abs(k - 1.7) < 1e-6)
    check(f"[0] 117 navel vertices matched onto the right forearm (got {len(rows)})", len(rows) == 117)
    bones = gf.bone_transforms(unrig, rig, corr, k)
    Wb = bones.fold_weights(gf.dense_weights(rig)[corr])
    Wb /= np.maximum(Wb.sum(1, keepdims=True), 1e-12)
    W2, bad = gf.trusted_donor_weights(unrig.positions, rig.positions[corr], bones, Wb, k)
    check(f"[1] exactly the 117 are mismatched (got {int(bad.sum())})",
          int(bad.sum()) == 117 and set(np.nonzero(bad)[0]) == set(rows.tolist()))
    hips = rig.joint_names.index("mixamorig:Hips")
    check("[1] each takes its matched neighbour's skin: Hips 1",
          bool(np.allclose(W2[rows, hips], 1.0)), f"{np.round(W2[rows, hips], 3).tolist()}")
    check("[1] every other vertex keeps its skin", bool(np.array_equal(W2[~bad], Wb[~bad])))


def test_new(gf, unrig, rig):
    P, res = fit(gf, unrig, rig)
    tr = res.report["transfer"]
    check(f"[2] uv_mismatched_donors 117 (got {tr.get('uv_mismatched_donors')})", tr.get("uv_mismatched_donors") == 117)
    check(f"[2] no sleeve at the waist (sleeve_vertices {tr.get('sleeve_vertices')})", tr.get("sleeve_vertices") == 0)
    err = float(np.abs(res.garment.positions - P).max())
    check(f"[2] every vertex within 5 mm of its design (max err {err:.4f})", err <= 0.005)
    check(f"[2] new_edge_max_m <= 0.005 (got {res.metrics.get('new_edge_max_m')})",
          res.metrics.get("new_edge_max_m") is not None and res.metrics["new_edge_max_m"] <= 0.005)
    check(f"[2] the gate passes ({res.reasons})", res.ok)
    return P


def test_gate(gf):
    check(f"[3] NEW_EDGE_MAX_M 0.17 (got {gf.NEW_EDGE_MAX_M})", gf.NEW_EDGE_MAX_M == 0.17)
    check("[3] new_edge_max_m is a clothing gate (max 0.17)",
          gf.CLOTHING_GATES.get("new_edge_max_m", (None, None))[:2] == ("max", 0.17))
    check("[3] ... on a body shape too (not a placement key)", "new_edge_max_m" in gf.clothing_gates(torso_mapped=True))
    X0 = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.0, 0.01, 0.0]])
    X = X0.copy()
    X[1] = (0.20, 0.0, 0.0)
    got = gf.new_edge_max(X, X0, [[0, 1, 2]])
    check(f"[3] new_edge_max by hand 0.19 (got {got:.6f})", abs(got - 0.19) < 1e-9)
    check("[3] new_edge_max of no faces is 0.0", gf.new_edge_max(X, X0, np.zeros((0, 3), np.int64)) == 0.0)
    base = {key: (0.0 if kind == "max" else 1.0) for key, (kind, _l, _t) in gf.CLOTHING_GATES.items()}
    ok19, reasons = gf.gate({**base, "new_edge_max_m": 0.19}, gf.CLOTHING_GATES)
    ok17, _ = gf.gate({**base, "new_edge_max_m": 0.17}, gf.CLOTHING_GATES)
    check("[3] 0.19 refuses, 0.17 passes", not ok19 and ok17, f"{reasons}")


def test_old(gf_new, unrig, rig):
    try:
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/garment_fit.py"],
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError) as e:
        check("[4] the pinned old garment_fit.py is readable", False, str(e))
        return
    path = Path(tempfile.mkdtemp(prefix="a72_old_")) / "garment_fit_old.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("garment_fit_old", path)
    old = importlib.util.module_from_spec(spec)
    sys.modules["garment_fit_old"] = old      # its dataclasses look their module up
    spec.loader.exec_module(old)
    check("[4] the old code has no donor repair", not hasattr(old, "trusted_donor_weights"))
    P, res = fit(old, unrig, rig)
    tr = res.report["transfer"]
    longest = gf_new.new_edge_max(res.garment.positions, P, res.garment.indices)
    check(f"[4] old: the waistband is taken for a sleeve (sleeve_vertices {tr.get('sleeve_vertices')})",
          (tr.get("sleeve_vertices") or 0) > 0)
    check(f"[4] old: its longest new edge {longest:.3f} m > NEW_EDGE_MAX_M 0.17 (the new gate refuses it)",
          longest > gf_new.NEW_EDGE_MAX_M)


def main() -> int:
    from app.core import garment_fit as gf
    unrig, rig, rows = mismatched_bodies()
    test_trusted(gf, unrig, rig, rows)
    test_new(gf, unrig, rig)
    test_gate(gf)
    test_old(gf, unrig, rig)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} — " + "; ".join(FAILS))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
