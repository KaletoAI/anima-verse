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

Constants: SHOE_TOP_M = SHAFT_CLASS_M["knee"] 0.48; [S1]..[S5] pass overlap_m 0.20 explicitly (the A122 rule)
-> cut 0.28; the default overlap since A177 is 10 cm ([S8]).

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
[S8] (A177) default overlap 10 cm: split(..) without overlap_m -> cut 0.38: leg bands k = 38..79 = 42 bands = 1344
     per side, 2688 total; overlap k = 38..47 = 10 bands = 320 per side, 640 total; report cut_mm 380, overlap_mm
     100. Settings: normalise({})["shaft_overlap"] 10; validate({"shaft_overlap": 15}) -> 15; 1, 31, 7.5, True and
     "10" -> ValueError; overlap_cm({"shaft_overlap": 99}) -> 30 (clamped), ({}) -> 10.
[S9] (A177) push_exempt on the boot pair with ring spacing 0.0099 m (ring i at h = 0.0099 i; ring 48 at 0.4752 <=
     0.48, ring 49 at 0.4851 > 0.48) and translated by (0.3, 1.0, 0.2) (the rule is frame-free): split -> rings
     0..48 = 49 rings x 16 x 2 sides = 1568 of 2592 vertices; cut -> all 2592.
[S10] (A182) split(.., "whole"): one part, every face: shoe 2 x 80 bands x 32 = 5120, leg 0, dropped 0. The top
     ring (h 0.80) is the highest vertex of every sector -> rim_low = rim_high = 800 mm; body_overlap 20 cm (default)
     -> body_cut_mm 600, body_cut_y_m 0.6 (sole y 0); body_overlap_m 0.15 -> 650. The whole boot's shaft weights:
     a vertex on ring 0.30 carries Leg 1.0 as in [S4].
[S11] (A182) push_exempt "whole" on the [S9] pair (top ring 80 at 0.792): below 0.792 - 0.20 = 0.592 -> rings
     0..59 (ring 59 at 0.5841, ring 60 at 0.594) = 60 rings x 32 = 1920 (the shoe rings 0..48 are inside them).
     gate_exempt "whole" on the unscaled pair, body_overlap 0.205 (cut 0.595, clear of a ring): rings 0..59 = 1920;
     gate_exempt "split" -> None.
[S12] (A182) garment_assembly.cut_legs: a left strip (x 0.10/0.11) and a right strip (x -0.10/-0.11), vertex pairs
     at y = 0.0 .. 0.5 step 0.1, two faces per segment (10 per strip), weighted LeftLeg / RightLeg 1.0, and one Hips
     triangle at y 0.05: 21 faces. Cut {"left": 0.25}: the left segments whose 4 corners lie below 0.25 = segments
     0 (0.0-0.1) and 1 (0.1-0.2) -> 4 faces dropped, 17 kept; vertices left unused: the 4 at y 0.0 and 0.1; skin
     ends at 0.2 (ring 2 is still used by segment 2). The right strip and the Hips triangle (below the cut, but no
     leg weight) stay.
[S13] (A182) settings: normalise({})["body_overlap"] 20; validate({"body_overlap": 25}) -> 25; 4, 41, 7.5, True
     refused; body_overlap_cm({"body_overlap": 99}) -> 40; "whole" in SHAFT_CHOICES; leg_cut_of reads a whole
     record's body_cut_y_m per side and gives None for a split record.
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
    g, rep = garment_shaft.split(boot(), B, JOINTS, mode, overlap_m=0.20)
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

_g, rep = garment_shaft.split(boot(), B, JOINTS, "split")
f = rep["faces"]
check("[S8] default overlap faces", (f["leg"], f["overlap"]) == (2688, 640), str(f))
check("[S8] default overlap report", (rep["cut_mm"], rep["overlap_mm"]) == (380, 100), str(rep["cut_mm"]))
check("[S8] normalise default 10", garment_fit_settings.normalise({})["shaft_overlap"] == 10)
check("[S8] validate 15", garment_fit_settings.validate({"shaft_overlap": 15}) == {"shaft_overlap": 15})
for bad in (1, 31, 7.5, True, "10"):
    try:
        garment_fit_settings.validate({"shaft_overlap": bad}); check(f"[S8] {bad!r} refused", False)
    except ValueError:
        check(f"[S8] {bad!r} refused", True)
check("[S8] overlap_cm clamps / defaults", garment_shaft.overlap_cm({"shaft_overlap": 99}) == 30
      and garment_shaft.overlap_cm({}) == 10)

g9 = boot()
P9 = np.asarray(g9.positions, np.float64) * np.array([1.0, 0.99, 1.0]) + np.array([0.3, 1.0, 0.2])
ex = garment_shaft.push_exempt(P9, g9.indices, "split")
check("[S9] split exempts rings 0..48", int(ex.sum()) == 1568 and len(ex) == 2592, f"{int(ex.sum())} / {len(ex)}")
ex = garment_shaft.push_exempt(P9, g9.indices, "cut")
check("[S9] cut exempts all", int(ex.sum()) == 2592, str(int(ex.sum())))

# --- A182: the whole boot, body leg cut off inside -------------------------------------------------------------
g10, rep = garment_shaft.split(boot(), B, JOINTS, "whole")
f = rep["faces"]
check("[S10] whole faces", (f["shoe"], f["leg"], f["dropped"]) == (5120, 0, 0), str(f))
sides = rep["sides"]
check("[S10] rim + body cut", all((sides[s]["rim_low_mm"], sides[s]["rim_high_mm"], sides[s]["body_cut_mm"],
                                   sides[s]["body_cut_y_m"]) == (800, 800, 600, 0.6) for s in ("left", "right")),
      str(sides["left"]))
_g, rep15 = garment_shaft.split(boot(), B, JOINTS, "whole", body_overlap_m=0.15)
check("[S10] body overlap 15", rep15["sides"]["left"]["body_cut_mm"] == 650, str(rep15["sides"]["left"]))
Pw = np.asarray(g10.positions); row = int(np.nonzero((np.abs(Pw[:, 1] - 0.30) < 1e-9) & (Pw[:, 0] > 0))[0][0])
names = {g10.joint_names[j]: w for j, w in zip(g10.joints[row], g10.weights[row]) if w > 0}
check("[S10] shaft weights Leg", list(names) == ["LeftLeg"] and abs(names["LeftLeg"] - 1) < 1e-9, str(names))
ex = garment_shaft.push_exempt(P9, g9.indices, "whole")
check("[S11] push_exempt whole rings 0..59", int(ex.sum()) == 1920, str(int(ex.sum())))
gb = boot()
ex = garment_shaft.gate_exempt(gb.positions, gb.indices, "whole", 0.1, -0.1, 0.205)
check("[S11] gate_exempt whole rings 0..59", ex is not None and int(ex.sum()) == 1920,
      str(None if ex is None else int(ex.sum())))
check("[S11] gate_exempt split None", garment_shaft.gate_exempt(gb.positions, gb.indices, "split", 0.1, -0.1) is None)

from app.core.garment_assembly import cut_legs  # noqa: E402
from app.core.glb_mesh import Prim  # noqa: E402
P12, F12, J12, W12 = [], [], [], []
for x0, dx, j in ((0.10, 0.01, 1), (-0.10, -0.01, 2)):
    base = len(P12)
    for i in range(6):
        P12 += [(x0, 0.1 * i, 0.0), (x0 + dx, 0.1 * i, 0.0)]
        J12 += [(j, 0, 0, 0)] * 2; W12 += [(1, 0, 0, 0)] * 2
    for i in range(5):
        a = base + 2 * i
        F12 += [(a, a + 1, a + 3), (a, a + 3, a + 2)]
base = len(P12)
P12 += [(0, 0.05, 0), (0.01, 0.05, 0), (0, 0.06, 0)]; J12 += [(0, 0, 0, 0)] * 3; W12 += [(1, 0, 0, 0)] * 3
F12 += [(base, base + 1, base + 2)]
prim = Prim(positions=np.array(P12, float), faces=np.array(F12, np.int64), joints=np.array(J12, np.int64),
            weights=np.array(W12, float), joint_names=["mixamorig:Hips", "mixamorig:LeftLeg", "mixamorig:RightLeg"])
out, st = cut_legs([prim], {"left": 0.25})
left = st["sides"]["left"]
check("[S12] 4 faces dropped, 17 kept", 0 in out and len(out[0].faces) == 17 and left["removed_faces"] == 4, str(st))
check("[S12] 4 vertices unused, skin ends at 0.2", left["removed_vertices"] == 4
      and abs(left["skin_end_y_m"] - 0.2) < 1e-9, str(left))
kept = {tuple(f) for f in out[0].faces.tolist()}
check("[S12] right strip + hips kept", all(tuple(f) in kept for f in F12[10:]))

check("[S13] default 20", garment_fit_settings.normalise({})["body_overlap"] == 20)
check("[S13] validate 25", garment_fit_settings.validate({"body_overlap": 25}) == {"body_overlap": 25})
for bad in (4, 41, 7.5, True):
    try:
        garment_fit_settings.validate({"body_overlap": bad}); check(f"[S13] {bad!r} refused", False)
    except ValueError:
        check(f"[S13] {bad!r} refused", True)
check("[S13] clamp + choices", garment_shaft.body_overlap_cm({"body_overlap": 99}) == 40
      and "whole" in garment_shaft.SHAFT_CHOICES)
check("[S13] leg_cut_of", garment_shaft.leg_cut_of({"report": {"shaft": rep}}) == {"left": 0.6, "right": 0.6}
      and garment_shaft.leg_cut_of({"report": {"shaft": {"mode": "split"}}}) is None)

print("FAILED: " + ", ".join(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
