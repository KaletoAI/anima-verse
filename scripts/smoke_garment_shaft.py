#!/usr/bin/env python3
"""Smoke: a boot past the knee as shoe part + leg part, or cut off at the shoe top (Ruling A122,
app/core/garment_shaft.py), and the pair-aware component gate (garment_fit.pair_share).

Usage:  ./.venv/bin/python scripts/smoke_garment_shaft.py

No storage, no world DB, no hub, no server: numpy on a synthetic body and boot pair.

Body: per side a column of points on a ring of radius 0.05 about (x0, ., 0), x0 = +0.10 (Left) / -0.10 (Right),
16 points per ring, rings every 0.01 m from y = 0 to 0.90. Weights by height: y < 0.10 the side's Foot 1.0,
0.10 <= y < 0.50 its Leg 1.0, above its UpLeg 1.0. Joints (bind frames, translation only): Foot at (x0, 0.08, 0),
Leg (the knee) at (x0, 0.50, 0). Boot: per side an open tube of radius 0.07 about the same axis, 16 segments,
rings every 0.01 m from y = 0 to 0.80 -> 80 bands of 32 triangles; a band k (0..79) has its face centroids at
y = (k + 0.5) cm (two of three corners on one ring, one on the other: (2k + (k+1))/3 or (k + 2(k+1))/3 -> k + 1/3 or
k + 2/3 cm; the rule only needs which side of a whole-centimetre threshold they lie on).

Constants: SHOE_TOP_M = SHAFT_CLASS_M["knee"] 0.48, OVERLAP_M 0.20 -> CUT_M 0.28.

Expected, by hand:
[S1] faces per side: shoe = bands with centroid <= 0.48 -> k = 0..47 = 48 bands = 1536; leg (split) = centroid >=
     0.28 -> k = 28..79 = 52 bands = 1664; overlap k = 28..47 = 20 bands = 640. Totals x2: shoe 3072, leg 3328,
     overlap 1280, dropped 0. cut: leg 0, dropped k = 48..79 = 32 bands x 32 x 2 = 2048.
[S2] report: shoe_top_mm 480, cut_mm 280, overlap_mm 200; per side ankle_mm 80 (Foot y 0.08 - sole 0), knee_mm
     500, top_mm 800.
[S3] the leg part stands LEG_OVER_M = 2 mm outside: a leg-part vertex lies at radius 0.072 (+-1e-5: every face
     is vertical, so the vertex normals are horizontal; the quad diagonals tilt them by a few degrees tangentially,
     2 mm x (1 - cos) < 1e-5).
[S4] weights: a shoe vertex on ring 0 (y 0; ankle band 0.06..0.10, s = 0) carries only its side's Foot /
     ToeBase; a shoe vertex and its leg-part twin on ring 0.30 carry the SAME weights (both: Leg 1.0 — the 8
     nearest body points at y 0.30 are all Leg); no vertex carries a joint of the other side.
[S5] a knee bend of 90 deg (about x through the Leg joint, both parts' weights through LBS) keeps every
     overlap pair (shoe vertex on ring 0.30 .. 0.47 and its twin) 2 mm apart (+-1e-6): no seam opens.
[S6] pair_share: two equal squares at x = +-0.1 -> (sum 1.0, True); areas 1 : 0.8 (ratio < 0.85) -> (largest, False);
     squares at x 0.10..0.20 and 0.15..0.25 (midline 0.175: half of each one's corners lie across it, > 0.05)
     -> (largest 0.5, False).
[S7] settings: normalise({}) shaft "split"; validate({"shaft": "cut"}) -> {"shaft": "cut"}; "keep" -> ValueError;
     applies: feet+legs True, feet False, legs False.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402

from app.core import garment_fit, garment_fit_settings, garment_shaft  # noqa: E402
from app.core.glb_mesh import BodyMesh, GarmentMesh  # noqa: E402
from app.core.rig_contract import norm_bone_name  # noqa: E402

FAILS = []


def check(tag, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + tag + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(tag)


NAMES = ["Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "RightUpLeg", "RightLeg", "RightFoot",
         "RightToeBase"]
X0 = {"Left": 0.10, "Right": -0.10}


def body():
    P, J = [], []
    for side, x0 in X0.items():
        for i in range(91):
            y = i * 0.01
            j = NAMES.index(f"{side}Foot" if y < 0.10 - 1e-9 else f"{side}Leg" if y < 0.50 - 1e-9 else f"{side}UpLeg")
            for a in range(16):
                t = 2 * math.pi * a / 16
                P.append((x0 + 0.05 * math.cos(t), y, 0.05 * math.sin(t)))
                J.append(j)
    n = len(P)
    joints = np.zeros((n, 4), np.int64); joints[:, 0] = J
    weights = np.zeros((n, 4)); weights[:, 0] = 1.0
    return BodyMesh(positions=np.array(P), faces=np.zeros((0, 3), np.int64), uvs=np.zeros((n, 2)), joints=joints,
                    weights=weights, joint_names=list(NAMES))


def bind(x0, y):
    M = np.eye(4); M[:3, 3] = (x0, y, 0.0); return M


JOINTS = {f"{s.lower()}{b}": bind(x0, y) for s, x0 in X0.items() for b, y in (("foot", 0.08), ("leg", 0.50))}


def boot():
    P, F = [], []
    for x0 in X0.values():
        base = len(P)
        for i in range(81):
            for a in range(16):
                t = 2 * math.pi * a / 16
                P.append((x0 + 0.07 * math.cos(t), i * 0.01, 0.07 * math.sin(t)))
        for i in range(80):
            for a in range(16):
                p, q = base + i * 16 + a, base + i * 16 + (a + 1) % 16
                F += [(p, q, q + 16), (p, q + 16, p + 16)]
    P = np.array(P); F = np.array(F, np.int64); n = len(P)
    return GarmentMesh(positions=P, normals=None, uvs=np.zeros((n, 2)), indices=F, joints=np.zeros((n, 4), np.int64),
                       weights=np.zeros((n, 4)), joint_names=["Hips"])


B = body()
for mode in ("split", "cut"):
    g, rep = garment_shaft.split(boot(), B, JOINTS, mode)
    f = rep["faces"]
    if mode == "split":
        check("[S1] split faces", (f["shoe"], f["leg"], f["overlap"], f["dropped"]) == (3072, 3328, 1280, 0), str(f))
        check("[S1] per side", all((rep["sides"][s]["shoe_faces"], rep["sides"][s]["leg_faces"]) == (1536, 1664)
                                   for s in ("left", "right")), str(rep["sides"]))
        check("[S2] report", (rep["shoe_top_mm"], rep["cut_mm"], rep["overlap_mm"]) == (480, 280, 200)
              and all((rep["sides"][s]["ankle_mm"], rep["sides"][s]["knee_mm"], rep["sides"][s]["top_mm"])
                      == (80, 500, 800) for s in ("left", "right")), str(rep))
        n_leg = rep["leg_vertices"]; n = len(g.positions)
        leg = np.zeros(n, bool); leg[n - n_leg:] = True
        side_x = np.where(g.positions[:, 0] > 0, 0.10, -0.10)
        r = np.hypot(g.positions[:, 0] - side_x, g.positions[:, 2])
        check("[S3] leg part radius 0.072", np.allclose(r[leg], 0.072, atol=1e-5), f"{r[leg].min():.6f}..{r[leg].max():.6f}")
        check("[S3] shoe part radius 0.070", np.allclose(r[~leg], 0.070, atol=1e-6))

        def dense(i):
            out = {}
            for slot in range(4):
                if g.weights[i, slot] > 0:
                    out[norm_bone_name(g.joint_names[g.joints[i, slot]])] = round(float(g.weights[i, slot]), 9)
            return out
        ring0 = np.nonzero(~leg & (np.abs(g.positions[:, 1]) < 1e-9))[0]
        check("[S4] ring 0 foot only", all(set(dense(i)) <= {f"{'left' if g.positions[i, 0] > 0 else 'right'}foot",
                                                               f"{'left' if g.positions[i, 0] > 0 else 'right'}toebase"}
                                           for i in ring0), str(dense(ring0[0])))
        # twins: same (x, y) direction and ring height
        key = lambda i: (round(float(g.positions[i, 1]), 4), int(round(math.degrees(math.atan2(
            g.positions[i, 2], g.positions[i, 0] - side_x[i])) / 22.5)) % 16, side_x[i] > 0)
        shoe_of = {key(i): i for i in np.nonzero(~leg)[0]}
        twins = [(shoe_of[key(i)], i) for i in np.nonzero(leg)[0] if key(i) in shoe_of]
        check("[S1] overlap twins = 2 sides x 20 rings x 16 + top ring", len(twins) == 2 * 21 * 16, str(len(twins)))
        r30 = [(a, b) for a, b in twins if abs(g.positions[a, 1] - 0.30) < 1e-9]
        check("[S4] ring 0.30 same weights, Leg 1", all(dense(a) == dense(b) and len(dense(a)) == 1
                                                         and next(iter(dense(a).values())) == 1.0
                                                         and next(iter(dense(a))).endswith("leg") for a, b in r30),
              str(dense(r30[0][0])))
        other = all(all(norm_bone_name(g.joint_names[g.joints[i, s]]).startswith(
            "left" if g.positions[i, 0] > 0 else "right") for s in range(4) if g.weights[i, s] > 0)
            for i in range(n))
        check("[S4] no other-side joint", other)
        # [S5] knee bend 90 deg on both sides, LBS
        c, s_ = math.cos(math.pi / 2), math.sin(math.pi / 2)
        R = np.array([[1, 0, 0], [0, c, -s_], [0, s_, c]])
        mats = {}
        for side, x0 in X0.items():
            p = np.array([x0, 0.50, 0.0]); M = np.eye(4); M[:3, :3] = R; M[:3, 3] = p - R @ p
            mats[f"{side.lower()}leg"] = M; mats[f"{side.lower()}foot"] = M; mats[f"{side.lower()}toebase"] = M
        X = np.zeros_like(g.positions)
        for slot in range(4):
            for i_j, name in enumerate(g.joint_names):
                sel = (g.joints[:, slot] == i_j) & (g.weights[:, slot] > 0)
                T = mats.get(norm_bone_name(name), np.eye(4))
                X[sel] += g.weights[sel, slot, None] * (g.positions[sel] @ T[:3, :3].T + T[:3, 3])
        low = [(a, b) for a, b in twins if g.positions[a, 1] <= 0.47 + 1e-9]
        d = np.array([np.linalg.norm(X[a] - X[b]) for a, b in low])
        check("[S5] overlap pairs stay 2 mm apart at 90 deg knee", len(low) == 2 * 20 * 16
              and np.allclose(d, 0.002, atol=1e-6), f"n {len(low)} d {d.min():.6f}..{d.max():.6f}")
    else:
        check("[S1] cut faces", (f["shoe"], f["leg"], f["overlap"], f["dropped"]) == (3072, 0, 0, 2048), str(f))
        check("[S1] cut keeps nothing above the shoe top", float(g.positions[:, 1].max()) <= 0.48 + 1e-9,
              str(g.positions[:, 1].max()))


def square(x0, size):
    P = np.array([(x0, 0, 0), (x0 + size, 0, 0), (x0 + size, size, 0), (x0, size, 0)], float)
    return P, np.array([(0, 1, 2), (0, 2, 3)])


def pair(a, b):
    P1, F1 = square(*a); P2, F2 = square(*b)
    P = np.vstack([P1, P2]); F = np.vstack([F1, F2 + 4])
    labels, share = garment_fit.components(P, F)
    return garment_fit.pair_share(P, labels, share)


v, p = pair((0.1, 0.1), (-0.2, 0.1))
check("[S6] mirrored pair", p and abs(v - 1.0) < 1e-9, f"{v} {p}")
v, p = pair((0.1, 0.1), (-0.2, 0.1 * math.sqrt(0.8)))
check("[S6] ratio 0.8 refused", (not p) and abs(v - 1 / 1.8) < 1e-9, f"{v} {p}")
v, p = pair((0.1, 0.1), (0.15, 0.1))
check("[S6] overlapping in x refused", (not p) and abs(v - 0.5) < 1e-9, f"{v} {p}")

check("[S7] default split", garment_fit_settings.normalise({})["shaft"] == "split")
check("[S7] validate cut", garment_fit_settings.validate({"shaft": "cut"}) == {"shaft": "cut"})
try:
    garment_fit_settings.validate({"shaft": "keep"}); check("[S7] bad value refused", False)
except ValueError:
    check("[S7] bad value refused", True)
check("[S7] applies", garment_shaft.applies(["feet", "legs"]) and not garment_shaft.applies(["feet"])
      and not garment_shaft.applies(["legs"]))

print("FAILED: " + ", ".join(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
