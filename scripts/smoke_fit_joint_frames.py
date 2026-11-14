#!/usr/bin/env python3
"""Ruling A35: the fit transfer follows the skeleton's joints; coverage counts the outer skin; sleeves sit on the
arms and keep their cuffs; the inside seen through an opening is left out; a shoe on a body shape rides the
plain fit's foot joints.

Usage:
    ./.venv/bin/python scripts/smoke_fit_joint_frames.py

Runs against a THROWAWAY storage directory (``paths.init`` first) on synthetic bodies built here (``BodyMesh``
arrays, the footwear fixture GLB of ``scripts/_footwear_fixtures.py``) — no world, no hub, no GPU, no server.
Every expected number is derived by hand below.

[1] Limb frames (``garment_fit.limb_frames``). A left leg: thigh rings (radius 0.07 around x 0.09, z 0, y 0.52 ..
    0.90) on LeftUpLeg, shin rings (radius 0.05, y 0.12 .. 0.48) on LeftLeg, foot rings (y 0.02 .. 0.08) on
    LeftFoot; the blend rings of the rigger: hip ring Hips / LeftUpLeg 0.5 / 0.5 centred at x 0.04 (reaching into
    the groin, radius 0.03, y 0.92), knee ring UpLeg / Leg at (0.09, 0.50, 0), ankle ring Leg / Foot at
    (0.09, 0.10, 0). Bind joints: LeftUpLeg (0.09, 0.92, 0), LeftLeg (0.09, 0.50, 0), LeftFoot (0.09, 0.10, 0).
    - basis "joints": points = the three joints; the thigh axis is vertical — tilt 0.000 deg; the thigh radius =
      the median distance of the UpLeg vertices to the vertical segment = 0.07 exactly.
    - basis "weights": the hip point = the hip ring's centroid (0.04, 0.92, 0); thigh tilt = atan(0.05 / 0.42)
      = 6.789 deg (Kai's plain body: 8.6 / 9.1 deg).
    - a source frame stored without a basis (before A35) is "weights" (``frame_basis``), and ``_frames_like``
      builds the target from the weight rings too: its hip point (0.04, 0.92, 0).
[2] Torso coverage counts the outer skin (``garment_source.torso_cover``). Trunk on Spine1: an outer cylinder
    (radius 0.15) and an inner one (radius 0.10, a hidden double wall), 26 rings each (y 0.95 .. 1.45, step 0.02)
    of 48 points at (i + 0.5) x 7.5 deg; joints Hips (0, 0.92, 0), Left/RightUpLeg (+-0.09, 0.92, 0), Spine
    (0, 1.0, 0), Spine1 (0, 1.15, 0), Spine2 (0, 1.30, 0), Neck (0, 1.50, 0) -> hip = (0, 0.92, 0), v = (y - 0.92)
    / 0.58 in [0.052, 0.914] (inside TORSO_V_RANGE). The garment: a half cylinder of radius 0.17 over the front
    (|theta| <= 90 deg). The inner wall lies 0.05 inside the outer (> TORSO_COVER_OUTER_M 0.02): counted are the
    26 x 48 = 1248 outer vertices only; every front sector (centre within 60 deg of +z) is covered 1.0 (outer skin
    0.02 from the garment <= TORSO_COVER_M 0.04) — counting the inner wall (0.07 away, never covered) halved it to
    0.5; every back sector 0.0.
[3] Sleeve centring (``garment_fit.center_sleeves``). A left arm along +x at y 1.40, z 0: skin cylinder radius 0.04,
    x 0.20 .. 0.80, rings every 0.01 of 24 points (LeftArm below x 0.48, LeftForeArm to 0.73, LeftHand beyond);
    joints LeftShoulder (0.10, 1.4, 0), LeftArm (0.20, ...), LeftForeArm (0.48, ...), LeftHand (0.73, ...). The
    sleeve: a tube radius 0.07 around y 1.35 (5 cm BELOW the arm), x 0.20 .. 0.70, rings every 0.01, its weights
    the arm's bones (Arm below x 0.48, ForeArm above). Per station the excess over the slack: 0.05 - 0.01 = 0.04,
    ramped in over half the upper arm (0.14 m from the Arm joint: full from x 0.34). The mid-forearm ring (x 0.55)
    ends 0.010 below the arm (the slack), within 0.001; the shoulder ring (x 0.20, ramp 0) moves less than 0.01.
[4] Sleeve backstop (``garment_source.check_sleeves``) on the body of [3]: the centred sleeve (axis on the arm's)
    is off nothing; the sleeve 0.10 below the arm: a ring point at angle phi from "up" lies sqrt(0.10^2 + 0.07^2 +
    2 x 0.10 x 0.07 cos phi) from the axis; off = beyond radius 0.04 + LIMB_OFF_M 0.04 (and 0.04 from the skin, the
    same condition on a cylinder) <=> cos phi > -0.6071 <=> |phi| < 127.4 deg: of the 24 angles 7.5 + 15 k, 16
    (0.6667) per ring — refused on both segments (limit 0.10).
[5] Cuffs (``garment_fit.sleeve_cuffs``). A sleeve tube (radius 0.03 around x 0.25, z 0) hanging from y 1.30 to
    0.95, rings every 0.01 of 16 points; the body: an arm line (part 1) at x 0.25, z 0.06 from y 1.35 to 1.10 and a
    thigh line (part 0) at the same x / z from y 1.05 to 0.80 (step 0.005). A ring's nearest body point is the
    line point at its own height: rings y >= 1.08 are arm-nearest (1.08: 0.02 to the arm's end, 0.03 to the
    thigh's), y <= 1.07 thigh-nearest; with the waist at 1.20 the sleeve (``sleeve_vertices``) is the rings y >=
    1.08. Along the mesh a ring y lies 1.08 - y from the sleeve (vertical edges of 0.01): rings 1.07 .. 0.99 (0.01
    .. 0.09) are the cuff, part 1; rings 0.97 .. 0.95 (0.11 .. 0.13) beyond SLEEVE_CUFF_REACH_M 0.10 are not;
    a separate skirt panel next to the thigh is never reached.
[6] The inside seen through an opening (``garment_fit.opening_lining``). Garment (metres, its own frame): a front
    panel at z +0.10 (x -0.20 .. 0.20, y 0 .. 0.60, grid 0.005) without its faces (and the vertices only they
    used) over the opening |x| < 0.05, 0.10 < y < 0.40; behind it a lining panel at z +0.06 (x -0.08 .. 0.08, y 0.08 .. 0.42); a back panel at z -0.10.
    Masks 400 x 400: the garment rows 50 .. 350, cols 100 .. 300 (0.002 m per px, centre (200, 200) <-> (0, 0.30));
    the opening rows 150 .. 300, cols 175 .. 225. Depth (px toward the viewer, centre z 0): front 50, lining 30,
    back -50. The component's recess = 50 - 30 = 20.0 px (>= OPEN_RECESS_PX 15); the lining is layered (30 - -50 =
    80 >= OPEN_LAYER_PX 30). Inside: the lining vertices in the opening's interior, |x| <= 0.045 (19 columns) x
    0.105 <= y <= 0.395 (59 rows) = 1121 — the edge columns |x| = 0.05 lie under the front panel's hole edge (front
    20 px ahead > OPEN_FRONT_TOL_PX 12), the lining under the panel is not front, the panels are never recessed:
    1121 vertices, (19 - 1) x (59 - 1) x 2 = 2088 faces. Without the back panel the lining is the only layer: no
    vertex is left out (a hole through the piece otherwise).
[7] A shoe on a body shape rides the plain fit (``garment_footwear.derive_compute``). The clog on
    ``foot_body_glb()`` (fit_compute: accepted). (a) Derived onto the SAME body: the lifts, the root lift and the
    shoe vertices are the fit's (difference 0 within 1e-6). (b) Onto that body RAISED 0.05 (every vertex and joint
    +0.05 in y): the floor, the joints and the soles rise alike — sole shift 0, the lifts unchanged, every shoe
    vertex +0.05 in y. (c) Onto a body whose foot boxes alone rise 0.004 (the soles 4 mm higher under unchanged
    joints, the leg columns kept): the sole shift is +0.004 per side, every vertex of the foot part +0.004 in y,
    and the floor (the soles' lowest point, 0 -> 0.004) rises by as much as the shoe ground: the lifts unchanged.
"""
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
_TMP = tempfile.mkdtemp(prefix="smoke_fit_joint_frames_")
os.environ["STORAGE_DIR"] = _TMP
from app.core import paths  # noqa: E402

paths.init(_TMP)

import numpy as np  # noqa: E402

from app.core import garment_fit as gf, garment_source as gsrc, glb_mesh  # noqa: E402
from app.core.glb_mesh import BodyMesh  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def ring(centre, radius, axis, n, *, offset=0.5):
    """``n`` points around ``centre`` (3,) perpendicular to ``axis`` ("x" or "y"), at (i + offset) x 360 / n deg."""
    t = (np.arange(n) + offset) * 2 * np.pi / n
    c = np.asarray(centre, np.float64)
    if axis == "y":   # angle from +z toward +x
        return np.stack([c[0] + radius * np.sin(t), np.full(n, c[1]), c[2] + radius * np.cos(t)], 1)
    # axis x: angle from +y ("up") toward +z
    return np.stack([np.full(n, c[0]), c[1] + radius * np.cos(t), c[2] + radius * np.sin(t)], 1)


def body(groups, names, joints):
    """A BodyMesh of point groups ``[(points, {joint name: weight})]`` (no faces needed by these readers)."""
    P, J, W = [], [], []
    for pts, wts in groups:
        cols = [names.index(n) for n in wts] + [0] * (4 - len(wts))
        ws = list(wts.values()) + [0.0] * (4 - len(wts))
        P.append(pts)
        J.append(np.tile(cols, (len(pts), 1)))
        W.append(np.tile(ws, (len(pts), 1)))
    from app.core.rig_contract import norm_bone_name
    P = np.concatenate(P)
    return BodyMesh(positions=P, faces=np.zeros((0, 3), np.int64), uvs=np.zeros((len(P), 2)),
                    joints=np.concatenate(J).astype(np.int64), weights=np.concatenate(W), joint_names=list(names),
                    joint_positions={norm_bone_name(n): np.asarray(p, np.float64) for n, p in joints.items()})


def tube(xs_or_ys, centre_fn, radius, axis, n):
    """Rings along a line + their quad faces (two triangles each), ring after ring."""
    rings = [ring(centre_fn(s), radius, axis, n) for s in xs_or_ys]
    P = np.concatenate(rings)
    F = []
    for r in range(len(rings) - 1):
        for i in range(n):
            a, b = r * n + i, r * n + (i + 1) % n
            c, d = a + n, b + n
            F += [(a, b, d), (a, d, c)]
    return P, np.asarray(F, np.int64)


# --- [1] limb frames ---------------------------------------------------------------------------------------------
LEG = ["Hips", "LeftUpLeg", "LeftLeg", "LeftFoot"]
legj = {"Hips": (0.0, 0.95, 0.0), "LeftUpLeg": (0.09, 0.92, 0.0), "LeftLeg": (0.09, 0.50, 0.0),
        "LeftFoot": (0.09, 0.10, 0.0)}
groups = [(ring((0.09, y, 0.0), 0.07, "y", 16), {"LeftUpLeg": 1.0}) for y in np.arange(0.52, 0.901, 0.02)]
groups += [(ring((0.09, y, 0.0), 0.05, "y", 16), {"LeftLeg": 1.0}) for y in np.arange(0.12, 0.481, 0.02)]
groups += [(ring((0.09, y, 0.0), 0.04, "y", 16), {"LeftFoot": 1.0}) for y in np.arange(0.02, 0.081, 0.02)]
groups += [(ring((0.04, 0.92, 0.0), 0.03, "y", 16), {"Hips": 0.5, "LeftUpLeg": 0.5}),
           (ring((0.09, 0.50, 0.0), 0.06, "y", 16), {"LeftUpLeg": 0.5, "LeftLeg": 0.5}),
           (ring((0.09, 0.10, 0.0), 0.045, "y", 16), {"LeftLeg": 0.5, "LeftFoot": 0.5})]
leg = body(groups, LEG, legj)


def tilt(points):
    a, b = np.asarray(points[0]), np.asarray(points[1])
    return math.degrees(math.atan2(math.hypot(b[0] - a[0], b[2] - a[2]), abs(b[1] - a[1])))


fj = gf.limb_frames(leg, basis="joints")["left_leg"]
fw = gf.limb_frames(leg, basis="weights")["left_leg"]
check("[1] joints basis: the chain points are the bind joints",
      np.allclose(fj["points"], [[0.09, 0.92, 0.0], [0.09, 0.50, 0.0], [0.09, 0.10, 0.0]], atol=1e-9)
      and fj["basis"] == "joints", f"{fj['points']} {fj['basis']}")
check("[1] joints basis: thigh tilt 0.000 deg, radius 0.070", abs(tilt(fj["points"])) < 1e-6
      and abs(fj["radii"][0] - 0.07) < 1e-9, f"{tilt(fj['points']):.4f} {fj['radii'][0]:.5f}")
check("[1] weights basis: hip point (0.04, 0.92, 0), tilt 6.789 deg",
      np.allclose(fw["points"][0], [0.04, 0.92, 0.0], atol=1e-9) and abs(tilt(fw["points"]) - 6.789) < 0.001
      and fw["basis"] == "weights", f"{fw['points'][0]} {tilt(fw['points']):.4f}")
old = {k: v for k, v in fw.items() if k != "basis"}
like = gf._frames_like(leg, {"left_leg": old})["left_leg"]
check("[1] a pre-A35 source frame is 'weights' and its target is made from the weight rings",
      gf.frame_basis(old) == "weights" and like["basis"] == "weights"
      and np.allclose(like["points"][0], [0.04, 0.92, 0.0], atol=1e-9), f"{like['basis']} {like['points'][0]}")

# --- [2] torso coverage: the outer skin only ------------------------------------------------------------------------
TR = ["Hips", "LeftUpLeg", "RightUpLeg", "Spine", "Spine1", "Spine2", "Neck"]
trj = {"Hips": (0.0, 0.92, 0.0), "LeftUpLeg": (0.09, 0.92, 0.0), "RightUpLeg": (-0.09, 0.92, 0.0),
       "Spine": (0.0, 1.0, 0.0), "Spine1": (0.0, 1.15, 0.0), "Spine2": (0.0, 1.30, 0.0), "Neck": (0.0, 1.50, 0.0)}
ys = np.round(np.arange(0.95, 1.4501, 0.02), 6)
groups = [(ring((0.0, y, 0.0), 0.15, "y", 48), {"Spine1": 1.0}) for y in ys]
groups += [(ring((0.0, y, 0.0), 0.10, "y", 48), {"Spine1": 1.0}) for y in ys]
trunk = body(groups, TR, trj)
G = np.concatenate([ring((0.0, y, 0.0), 0.17, "y", 96) for y in np.arange(0.90, 1.50, 0.01)])
G = G[G[:, 2] >= -1e-9]                                  # the front half: theta in [-90, 90] deg
cov = gsrc.torso_cover(G, trunk)
count = np.asarray(cov["count"])
shares = np.asarray(cov["covered"])
front = [k for k in range(gsrc.TORSO_SECTORS) if gsrc._sector_group(k) == "front"]
back = [k for k in range(gsrc.TORSO_SECTORS) if gsrc._sector_group(k) == "back"]
filled = count > 0
check("[2] counted: the 1248 outer vertices, the inner wall left out", int(count.sum()) == 26 * 48,
      f"{int(count.sum())}")
check("[2] front sectors covered 1.0", np.all(shares[:, front][filled[:, front]] == 1.0),
      f"{shares[:, front][filled[:, front]].min()}")
check("[2] back sectors covered 0.0", np.all(shares[:, back][filled[:, back]] == 0.0))

# --- [3] / [4] sleeves on the arm ------------------------------------------------------------------------------------
ARM = ["Hips", "Spine", "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand"]
armj = {"Hips": (0.0, 1.0, 0.0), "Spine": (0.0, 1.1, 0.0), "LeftShoulder": (0.10, 1.4, 0.0),
        "LeftArm": (0.20, 1.4, 0.0), "LeftForeArm": (0.48, 1.4, 0.0), "LeftHand": (0.73, 1.4, 0.0)}


def arm_bone(x):
    return "LeftArm" if x < 0.48 - 1e-9 else ("LeftForeArm" if x < 0.73 - 1e-9 else "LeftHand")


groups = [(ring((x, 1.4, 0.0), 0.04, "x", 24), {arm_bone(x): 1.0}) for x in np.round(np.arange(0.20, 0.801, 0.01), 6)]
arm = body(groups, ARM, armj)
xs = np.round(np.arange(0.20, 0.7001, 0.01), 6)
S, SF = tube(xs, lambda x: (x, 1.35, 0.0), 0.07, "x", 24)
Wg = np.zeros((len(S), len(ARM)))
Wg[np.arange(len(S)), [ARM.index(arm_bone(x)) for x in S[:, 0]]] = 1.0
X, rep = gf.center_sleeves(S, Wg, arm, adjacency=gf._adjacency(SF, len(S)))


def ring_dy(Y, x):
    m = np.abs(S[:, 0] - x) < 1e-6
    return float(0.5 * (Y[m, 1].max() + Y[m, 1].min()) - 1.4)


check("[3] the mid-forearm ring ends 0.010 below the arm (the slack)", abs(ring_dy(X, 0.55) + 0.010) <= 0.001,
      f"{ring_dy(S, 0.55):+.4f} -> {ring_dy(X, 0.55):+.4f}")
check("[3] the shoulder ring (ramp 0) moves less than 0.01", abs(ring_dy(X, 0.20) - ring_dy(S, 0.20)) < 0.01,
      f"{ring_dy(S, 0.20):+.4f} -> {ring_dy(X, 0.20):+.4f}")
_orig_body_arrays = glb_mesh.body_arrays
glb_mesh.body_arrays = lambda blob: arm if blob == b"ARM" else _orig_body_arrays(blob)
try:
    S0, _ = tube(xs, lambda x: (x, 1.40, 0.0), 0.07, "x", 24)
    S10, _ = tube(xs, lambda x: (x, 1.30, 0.0), 0.07, "x", 24)
    good, bad = gsrc.check_sleeves(S0, b"ARM"), gsrc.check_sleeves(S10, b"ARM")
finally:
    glb_mesh.body_arrays = _orig_body_arrays
check("[4] the centred sleeve passes, off [0, 0]", good["ok"] and good["fit"]["left_arm"]["off"] == [0.0, 0.0],
      f"{good['fit']['left_arm']['off']}")
check("[4] the sleeve 0.10 below: off 0.6667 on both segments, refused", (not bad["ok"])
      and bad["fit"]["left_arm"]["off"] == [0.6667, 0.6667] and len(bad["reasons"]) == 2,
      f"{bad['fit']['left_arm']['off']} {bad['reasons']}")

# --- [5] cuffs ---------------------------------------------------------------------------------------------------------
cys = np.round(np.arange(1.30, 0.9499, -0.01), 6)
C, CF = tube(cys, lambda y: (0.25, y, 0.0), 0.03, "y", 16)
skirt = ring((0.25, 0.90, -0.12), 0.02, "y", 16)          # a separate panel beside the thigh, no edge to the sleeve
Q = np.concatenate([C, skirt])
QF = CF
armline = np.stack([np.full(51, 0.25), np.linspace(1.35, 1.10, 51), np.full(51, 0.06)], 1)
thigh = np.stack([np.full(51, 0.25), np.linspace(1.05, 0.80, 51), np.full(51, 0.06)], 1)
BP = np.concatenate([armline, thigh])
parts = np.concatenate([np.ones(51, np.int64), np.zeros(51, np.int64)])
upper = Q[:, 1] >= 1.20
sleeve = gf.sleeve_vertices(Q, BP, parts, QF, upper)
cuff = gf.sleeve_cuffs(Q, BP, parts, QF, upper, sleeve, 1.0)
ring_y = np.round(Q[:, 1], 6)
in_tube = np.arange(len(Q)) < len(C)
check("[5] the sleeve: the rings y >= 1.08", np.array_equal(sleeve[in_tube], ring_y[in_tube] >= 1.08 - 1e-9))
cuff_rings = in_tube & (ring_y <= 1.07 + 1e-9) & (ring_y >= 0.99 - 1e-9)
far_rings = in_tube & (ring_y <= 0.97 + 1e-9)
check("[5] the cuff: rings 1.07 .. 0.99 on part 1", np.all(cuff[cuff_rings] == 1), f"{np.unique(cuff[cuff_rings])}")
check("[5] beyond the reach: rings 0.97 .. 0.95 no cuff", np.all(cuff[far_rings] == 0))
check("[5] the skirt panel is never reached", np.all(cuff[~in_tube] == 0) and not sleeve[~in_tube].any())


# --- [6] the inside seen through an opening ---------------------------------------------------------------------------
def grid(x0, x1, y0, y1, z, step=0.005, skip=None):
    nx, ny = int(round((x1 - x0) / step)) + 1, int(round((y1 - y0) / step)) + 1
    gx, gy = np.meshgrid(np.linspace(x0, x1, nx), np.linspace(y0, y1, ny), indexing="ij")
    P = np.stack([gx.ravel(), gy.ravel(), np.full(gx.size, z)], 1)
    F = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            a, b, c, d = i * ny + j, (i + 1) * ny + j, i * ny + j + 1, (i + 1) * ny + j + 1
            cx, cy = 0.5 * (P[a, 0] + P[d, 0]), 0.5 * (P[a, 1] + P[d, 1])
            if skip is not None and skip(cx, cy):
                continue
            F += [(a, b, d), (a, d, c)]
    F = np.asarray(F, np.int64)
    used = np.unique(F)                                   # a mesher leaves no vertex without a face
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    return P[used], remap[F]


def in_opening(x, y):
    return abs(x) < 0.05 and 0.10 < y < 0.40


Pf, Ff = grid(-0.20, 0.20, 0.0, 0.60, 0.10, skip=in_opening)
Pl, Fl = grid(-0.08, 0.08, 0.08, 0.42, 0.06)
Pb, Fb = grid(-0.20, 0.20, 0.0, 0.60, -0.10)


def merged(*meshes):
    P, F, base = [], [], 0
    for p, f in meshes:
        P.append(p)
        F.append(f + base)
        base += len(p)
    return np.concatenate(P), np.concatenate(F)


gm = np.zeros((400, 400), bool)
gm[50:350, 100:300] = True
op = np.zeros((400, 400), bool)
op[150:300, 175:225] = True
P6, F6 = merged((Pf, Ff), (Pl, Fl), (Pb, Fb))
lining, rep6 = gf.opening_lining(P6, F6, op, gm)
lin_part = np.zeros(len(P6), bool)
lin_part[len(Pf):len(Pf) + len(Pl)] = True
expect = lin_part & (np.abs(P6[:, 0]) <= 0.045 + 1e-9) & (P6[:, 1] >= 0.105 - 1e-9) & (P6[:, 1] <= 0.395 + 1e-9)
check("[6] one opening, recess 20.0 px", len(rep6["components"]) == 1
      and abs(rep6["components"][0]["recess_px"] - 20.0) <= 0.5 and rep6["components"][0]["dropped"],
      f"{rep6['components']}")
check("[6] the inside: exactly the 1121 lining vertices in the opening", int(lining.sum()) == 1121
      and np.array_equal(lining, expect), f"{int(lining.sum())} / {int(expect.sum())}")
check("[6] 2088 faces left out, none of the panels", rep6["faces"] == 2088
      and gf._open_faces(F6, lining).sum() == len(F6) - 2088, f"{rep6['faces']}")
P6b, F6b = merged((Pf, Ff), (Pl, Fl))
lining_b, rep6b = gf.opening_lining(P6b, F6b, op, gm)
check("[6] without the back panel the lining is a single layer: nothing left out", not lining_b.any(),
      f"{int(lining_b.sum())}")

# --- [7] a shoe on a body shape --------------------------------------------------------------------------------------
import _footwear_fixtures as fx  # noqa: E402
from app.core import footwear_insole, garment_footwear  # noqa: E402

Pc, Fc = fx.clog()
prepared = glb_mesh.static_glb(Pc, Fc, np.zeros((len(Pc), 2)))
insole = footwear_insole.analyse(prepared)
base_glb = fx.foot_body_glb()
out = os.path.join(_TMP, "base_fit.glb")
fit = garment_footwear.fit_compute(prepared, insole, base_glb, None, "footwear", "clog", "f" * 12, out)
check("[7] the clog fits the fixture feet", fit["ok"], str(fit.get("reasons")))
base_fit = Path(out).read_bytes()
base_record = {**fit["record"], "foot_pose": {**fit["foot_pose"], "rest": fit["rest"]}}


def shoe(blob, side):
    return glb_mesh.garment_arrays(blob, node_prefix=garment_footwear.node_name("clog", side, "foot"),
                                   exact=True).positions


def shaped(dy_all=0.0, dy_feet=0.0):
    """``foot_body_glb()`` with every vertex and joint raised ``dy_all`` and the foot boxes ``dy_feet`` more."""
    orig_body, orig_joints = fx.foot_body, dict(fx.FOOT_JOINTS)

    def body_fn(*a, **k):
        P, F, J, W, names = orig_body(*a, **k)
        P = P.copy()
        feet = np.isin(J[:, 0], [names.index(n) for n in names if n.endswith(("Foot", "ToeBase"))]) & (W[:, 0] > 0.5)
        P[:, 1] += dy_all
        P[feet, 1] += dy_feet
        return P, F, J, W, names
    try:
        fx.foot_body = body_fn
        fx.FOOT_JOINTS.update({n: (x, y + dy_all, z) for n, (x, y, z) in orig_joints.items()})
        return fx.foot_body_glb()
    finally:
        fx.foot_body = orig_body
        fx.FOOT_JOINTS.clear()
        fx.FOOT_JOINTS.update(orig_joints)


def derive(target, tag):
    path = os.path.join(_TMP, f"derived_{tag}.glb")
    res = garment_footwear.derive_compute(base_fit, base_record, base_glb, insole, target, "footwear", "clog",
                                          "f" * 12, path)
    return res, (Path(path).read_bytes() if res["ok"] else b"")


lifts0 = {s: base_record["sides"][s]["lift_m"] for s in ("left", "right")}
ra, ba = derive(base_glb, "same")
check("[7a] onto the same body: accepted, the lifts and the root lift the fit's",
      ra["ok"] and all(abs(ra["record"]["sides"][s]["lift_m"] - lifts0[s]) < 1e-6 for s in lifts0)
      and abs(ra["record"]["root_lift_m"] - base_record["root_lift_m"]) < 1e-6,
      f"{ra.get('reasons')} {[ra['record']['sides'][s]['lift_m'] for s in lifts0] if ra['ok'] else ''}")
check("[7a] ... and the shoe vertices the fit's", ra["ok"] and all(
    np.abs(shoe(ba, s) - shoe(base_fit, s)).max() < 1e-6 for s in ("left", "right")))
rb, bb = derive(shaped(dy_all=0.05), "raised")
check("[7b] onto the body raised 0.05: sole shift 0, the lifts unchanged",
      rb["ok"] and all(abs(rb["record"]["sides"][s]["sole_shift_m"]) < 1e-6
                       and abs(rb["record"]["sides"][s]["lift_m"] - lifts0[s]) < 1e-6 for s in lifts0),
      str(rb.get("reasons")))
check("[7b] ... every shoe vertex +0.05 in y", rb["ok"] and all(
    np.abs(shoe(bb, s) - shoe(base_fit, s) - [0.0, 0.05, 0.0]).max() < 1e-6 for s in ("left", "right")))
rc, bc = derive(shaped(dy_feet=0.004), "soles")
check("[7c] the soles 4 mm higher: sole shift +0.004 per side, the lifts unchanged",
      rc["ok"] and all(abs(rc["record"]["sides"][s]["sole_shift_m"] - 0.004) < 1e-6
                       and abs(rc["record"]["sides"][s]["lift_m"] - lifts0[s]) < 1e-6 for s in lifts0),
      f"{rc.get('reasons')} {[rc['record']['sides'][s].get('sole_shift_m') for s in lifts0] if rc['ok'] else ''}")
check("[7c] ... every vertex of the foot part +0.004 in y", rc["ok"] and all(
    np.abs(shoe(bc, s) - shoe(base_fit, s) - [0.0, 0.004, 0.0]).max() < 1e-6 for s in ("left", "right")))

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
