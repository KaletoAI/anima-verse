#!/usr/bin/env python3
"""Ruling A84 — the armpit seam: which garment vertices ride an arm and which the trunk, laid by a minimum cut over
the edge growth the pose change brings (app/core/garment_fit.py: ``seam_cut``, ``armpit_seam``, its step 2b in
``transfer_skinned``, ``seam_may_change`` / ``expected_fit_version``) on synthetic geometry — no world, no hub, no GLB.

Usage:
    ./.venv/bin/python scripts/smoke_armpit_seam.py

Expected numbers, derived by hand:

[1] ``seam_cut`` on a path of five vertices 0 - 1 - 2 - 3 - 4, every edge of rest length 1. Riding the trunk vertex i
    lands at (i, 0, 0), riding the arm at (i, h_i, 0) with h = (0, 1.0, 0.75, 2.4, 0). Vertex 0 is pinned to the
    trunk, vertex 4 to the arm. One seam between i (trunk) and i + 1 (arm) costs |(i + 1, h_{i+1}) - (i, 0)| - 1 =
    sqrt(1 + h_{i+1}^2) - 1: before 1 -> sqrt(2) - 1 = 0.4142, before 2 -> 1.25 - 1 = 0.25, before 3 -> 2.6 - 1 = 1.6,
    before 4 -> 0 (h_4 = 0). A second seam only adds cost (an arm vertex below a trunk one pays sqrt(1 + h_i^2) - 1
    >= 0 as well), and ``SEAM_PREFER_M`` = 0.001 per vertex that leaves the part it had.
    (a) It had arm = (F, F, T, T, T): the seam before 2 costs 0.25, before 4 0.0 + 2 x 0.001 (2 and 3 leave the arm)
        -> the seam goes before 4: arm = (F, F, F, F, T). (The cheapest place, not where the nearest skin put it.)
    (b) h = (0, 1.0, 0.75, 2.4, 2.4) — now before 4 costs 2.6 - 1 = 1.6 like before 3. It had arm = (F, F, F, T, T)
        (the seam before 3, 1.6): before 2 costs 0.25 + 0.001 (vertex 2 joins the arm) = 0.251 -> arm = (F, F, T, T,
        T): the "bat-wing" vertex 2 goes to the arm because its seam opens less there.
    (c) h = (0, 0, 0, 0, 0): every seam costs 0, so only the preference counts. It had arm = (F, T, F, T, T) — two
        seams around vertex 1, both free — and keeps it exactly: any change pays 0.001 per vertex and saves nothing.
[2] ``transfer_skinned`` end to end on the fixture body of ``smoke_garment_clothing_fit`` (torso r 0.15 around the y
    axis, left upper arm r 0.04 along +x from the shoulder (0.15, 1.34, 0), turned 45 deg down about it in the A-pose
    source; k 1.7): a sleeve tube r 0.06 around the T-pose upper arm from 10 % to 75 % of its 0.27 m (x 0.177 ..
    0.3525, rings every 1 cm, 19 rings x 48 = 912 vertices), turned into the A-pose. There the inner wall of the rings
    near the shoulder dips into the torso: the ring at 10 % has its centre 0.027 down the arm from the pivot, (0.169,
    1.321), and its inner point 0.06 toward the torso, (0.169 - 0.042, 1.321 - 0.042) = (0.127, 1.279), lies 2.3 cm
    inside the torso's r 0.15 — its nearest skin is the torso's, so the nearest-part rule gives it the trunk.
    - Old (the nearest part alone): those vertices keep Spine2 and stay beside the torso while the arm turns 45 deg
      up: their error against the T-pose design is 2 r sin 22.5 deg = 0.765 r with r >= 0.06 (the ring's radius)
      -> >= 0.046 m; the fixture gives 0.057 (> 0.03 checked), some vertices with LeftArm < 0.5.
    - New (``armpit_seam``): the vertices on the outer side are nearer the arm than the torso by more than
      ``SEAM_SEED_M`` (pinned to the arm). Labelling every vertex "arm" costs only 0.001 per vertex it moves (at most
      912 x 0.001 = 0.91); leaving a patch of n of them on the trunk cuts at least 2 sqrt(n) grid edges, each growing
      by >= 0.765 x 0.06 - 0.0079 (its rest length, 2 pi 0.06 / 48) = 0.038 m, and 0.038 x 2 sqrt(n) > 0.001 n for
      every n < 5776 > 912 -> the whole tube rides the arm: every vertex LeftArm 1 (clothing_weights), the arm's
      transform is the exact rotation, so every vertex lands on its T-pose design (< 1 mm) and no edge grows (< 1 mm);
      the report moves vertices to the arm and none to the trunk.
[3] A piece with nothing on an arm — a skirt ring r 0.18 around the hips, y 0.90 .. 1.05 — is returned as it is:
    ``armpit_seam`` hands back the very weight array and an empty report (so a skirt's fit is the same bit for bit).
[4] Versions: FIT_VERSION clothing 18 (17 stays current without a seeded opening, Ruling A114), CLOTHING_SEAM_UNCHANGED 16, CLOTHING_TRUNK_UNCHANGED 15.
    ``expected_fit_version`` of a clothing record:
      v16 with ``report.transfer.sleeve_share`` 0 -> 16 (current: nothing rode an arm);
      v16 with sleeve_share 0.3762 (Kira's blazer) -> 17; v16 without a report -> 17 (may have sleeves);
      v15, sleeve_share 0, trunk kept (torso_gap 0.0138 / front 0.0126) -> 15; v15, sleeve_share 0, the blouse's
      trunk numbers (0.0232 / 0.0381) -> 17; v15, sleeve_share 0.2960, trunk kept -> 17; v14, sleeve_share 0 -> 17;
      v17 -> 17; a hair record keeps FIT_VERSION hair.
[5] Fails on the old code: at commit 5dce3120d (before Ruling A84) the same fixture as [2] leaves the inner wall on
    the trunk — its module, loaded from that commit, puts some vertex more than 3 cm off its design, and it has no
    ``seam_cut`` and FIT_VERSION clothing 16.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILED = []
OLD = "5dce3120d"


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f" ({detail})" if detail else ""))
    if not ok:
        FAILED.append(label)


def test_cut(gf):
    print("[1] seam_cut on a path")
    E = np.array([[0, 1], [1, 2], [2, 3], [3, 4]])
    rest = np.ones(4)

    def run(h, had):
        h = np.asarray(h, float)
        trunk = np.stack([np.arange(5.0), np.zeros(5), np.zeros(5)], 1)
        arm = trunk + np.stack([np.zeros(5), h, np.zeros(5)], 1)
        seed_arm = np.array([0, 0, 0, 0, 1], bool)
        seed_trunk = np.array([1, 0, 0, 0, 0], bool)
        return gf.seam_cut(arm, trunk, rest, E, np.asarray(had, bool), seed_arm, seed_trunk).tolist()
    got = run([0, 1.0, 0.75, 2.4, 0], [0, 0, 1, 1, 1])
    check("[1a] the seam goes where it opens least (before 4)", got == [False, False, False, False, True], got)
    got = run([0, 1.0, 0.75, 2.4, 2.4], [0, 0, 0, 1, 1])
    check("[1b] the bat-wing vertex 2 goes to the arm (seam before 2: 0.251 < 1.6)",
          got == [False, False, True, True, True], got)
    got = run([0, 0, 0, 0, 0], [0, 1, 0, 1, 1])
    check("[1c] no growth anywhere: the labelling it had is kept", got == [False, True, False, True, True], got)


def sleeve_case(gf, C, unrig, rig):
    L0, L1 = 0.15 + 0.10 * 0.27, 0.15 + 0.75 * 0.27
    P, F = C.tube((L0, C.SHOULDER_Y, 0), (L1, C.SHOULDER_Y, 0), 0.06, nlon=48, caps=False)
    Q = (C.a_pose(P, 1) - C.T) / 1.7
    X, report = gf.transfer_skinned(Q, unrig, rig, faces=F, k=1.7, split_y=Q[:, 1].min() - 1.0)
    D = C.dense(*gf.clothing_weights(X, rig, skirt=False), rig.joint_names)
    left_arm = D[:, rig.joint_names.index("mixamorig:LeftArm")]
    return P, F, Q, X, report, left_arm


def test_sleeve(gf, C, unrig, rig):
    print("[2] a sleeve whose inner wall lies nearer the torso")
    P, F, Q, X, report, left_arm = sleeve_case(gf, C, unrig, rig)
    check("[2] 912 vertices", len(P) == 912, len(P))
    err = float(np.abs(X - P).max())
    check("[2] every vertex lands on its T-pose design (< 1 mm)", err < 0.001, f"{err:.5f}")
    check("[2] every vertex LeftArm 1", bool(np.all(left_arm > 0.999)), int((left_arm <= 0.999).sum()))
    grow = gf.new_edge_max(X, Q * 1.7, F)
    check("[2] no edge grows (< 1 mm)", grow < 0.001, f"{grow:.5f}")
    seam = (report.get("armpit_seam") or {}).get("left") or {}
    check("[2] the seam moved vertices to the arm, none to the trunk",
          seam.get("to_arm", 0) > 0 and seam.get("to_trunk") == 0, seam)


def test_identity(gf, C, unrig, rig):
    print("[3] nothing on an arm: returned as it is")
    P, F = C.revolution([(1.05, 0.18), (1.00, 0.18), (0.95, 0.18), (0.90, 0.18)])
    Q = (P - C.T) / 1.7
    Wg = np.zeros((len(Q), len(rig.joint_names)))
    Wg[:, rig.joint_names.index("mixamorig:Hips")] = 1.0
    calls = []

    def blend(cand, rows):
        calls.append(1)
        return np.zeros((len(rows), Wg.shape[1]))
    out, rep = gf.armpit_seam(Q, Wg, 1.7, faces=F, bones=None, Pb=unrig.positions, parts=np.zeros(len(unrig.positions),
                              np.int64), joint_names=rig.joint_names, blend=blend, top_donors=np.arange(1),
                              low_donors=np.arange(1), upper=np.ones(len(Q), bool))
    check("[3] the very weight array, an empty report, no blend", out is Wg and rep == {} and not calls,
          (out is Wg, rep, len(calls)))


def test_versions(gf):
    print("[4] versions")
    check("[4] FIT_VERSION clothing 18 (Ruling A114), CLOTHING_SEAM_UNCHANGED 16, CLOTHING_TRUNK_UNCHANGED 15",
          gf.FIT_VERSION["clothing"] == 18 and gf.CLOTHING_SEAM_UNCHANGED == 16 and gf.CLOTHING_TRUNK_UNCHANGED == 15,
          gf.FIT_VERSION)

    def rec(version, share=None, room=None, front=None, kind="clothing"):
        r = {"kind": kind, "fit_version": version,
             "metrics": {} if room is None else {"torso_gap_p50_m": room, "trunk_front_gap_p50_m": front}}
        if share is not None:
            r["report"] = {"transfer": {"sleeve_share": share}}
        return r
    cases = [("v16 nothing on an arm stays current", rec(16, 0.0), 16),
             ("v16 Kira's blazer (0.3762) is due", rec(16, 0.3762), 18),
             ("v16 without a report is due", rec(16), 18),
             ("v15 nothing on an arm, trunk kept stays current", rec(15, 0.0, 0.0138, 0.0126), 15),
             ("v15 nothing on an arm, the blouse's trunk is due", rec(15, 0.0, 0.0232, 0.0381), 18),
             ("v15 with sleeves, trunk kept is due", rec(15, 0.2960, 0.0138, 0.0126), 18),
             ("v14 is due", rec(14, 0.0), 18),
             ("v17 is current", rec(17, 0.3762), 17),
             ("hair keeps its own", rec(16, kind="hair"), gf.FIT_VERSION["hair"])]
    for label, record, want in cases:
        got = gf.expected_fit_version(record)
        check(f"[4] {label}", got == want, got)


def test_old_code(C, unrig, rig):
    print(f"[5] fails on the old code ({OLD})")
    try:
        src = subprocess.run(["git", "show", f"{OLD}:app/core/garment_fit.py"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        check("[5] old source readable", False, e)
        return
    check("[5] no seam_cut, FIT_VERSION clothing 16", "def seam_cut" not in src and '"clothing": 16' in src)
    name = "garment_fit_before_a84"
    spec = importlib.util.spec_from_loader(name, loader=None)
    old = importlib.util.module_from_spec(spec)
    sys.modules[name] = old
    try:
        exec(compile(src, f"{OLD}:app/core/garment_fit.py", "exec"), old.__dict__)
        P, _F, _Q, X, _report, left_arm = sleeve_case(old, C, unrig, rig)
    finally:
        sys.modules.pop(name, None)
    err = float(np.abs(X - P).max())
    check("[5] old: the inner wall stays on the trunk (a vertex > 3 cm off its design, LeftArm < 0.5)",
          err > 0.03 and bool((left_arm < 0.5).any()), f"{err:.4f}, {int((left_arm < 0.5).sum())} off the arm")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.setdefault("STORAGE_DIR", tmp)
        from app.core import paths
        paths.init(tmp)
        from app.core import garment_fit as gf
        import smoke_garment_clothing_fit as C
        unrig, rig = C.bodies()
        test_cut(gf)
        test_sleeve(gf, C, unrig, rig)
        test_identity(gf, C, unrig, rig)
        test_versions(gf)
        test_old_code(C, unrig, rig)
    print()
    if FAILED:
        print(f"FAILED {len(FAILED)}: " + "; ".join(FAILED))
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
