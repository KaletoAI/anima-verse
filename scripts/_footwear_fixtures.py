"""Synthetic shoe meshes shared by the footwear smoke scripts; no storage imports.

The wedge pump (plan docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md, Task 5 Step 1), in the
mesher's own coordinates (Y up, x heel -> toe, z lateral), length 0.26, width 0.08:

- sole solid over the full width: top h(x) = 0.09 on [0, 0.05], linear to 0.01 at 0.15, 0.01 on
  [0.15, 0.26]; bottom at 0 (facing down); end faces at x = 0 and x = 0.26;
- zero-thickness side walls at z = +-0.04 from the ground up to h(x) + 0.03, tessellated every 0.01;
- a vamp roof (facing up) at h(x) + 0.03 over x in [roof_from, 0.26] (0.18 = the closed pump,
  0.24 = the sandal variant);
- optionally a thin vertical fin at z = 0 over the toe end rising to 0.15 (vertical, so no ray hits it and
  the topline ignores it because it sits at z = 0) that makes the TOE end the taller one for the
  provisional heel rule;
- ``shaft``: a boot variant — the side walls over x in [0, 0.10] rise to ``shaft``;
- ``solid=True``: the closed solid wedge — the sole alone (side faces from the ground to h(x), no walls above
  it, no roof), i.e. a mesher result whose top surface would be read as the insole.

``clog`` is the closed flat clog of the cut smokes (its docstring): the one fixture shoe a rigid box foot
passes the cut gates in.

Every quad is two triangles over the 0.01 x-grid; each face is wound so its normal points outward
(up for the sole top and the roof, down for the bottom, +-z for the walls).
"""
import numpy as np

LENGTH = 0.26
HALF_W = 0.04
WALL = 0.03


def h(x: float) -> float:
    """Top of the sole (the insole) at ``x``."""
    if x <= 0.05:
        return 0.09
    if x <= 0.15:
        return 0.09 - 0.8 * (x - 0.05)
    return 0.01


def wedge(roof_from: float = 0.18, *, fin: bool = False, rotate_180: bool = False, solid: bool = False,
          shaft: float = 0.0):
    """``(positions (N, 3), faces (M, 3))`` of the wedge pump (module docstring); ``shaft`` > 0 raises the
    side walls over the rear x in [0, 0.10] to that height (a boot shaft; topline there = ``shaft``)."""
    P, F = [], []

    def tri(a, b, c, facing):
        a, b, c = (np.asarray(v, np.float64) for v in (a, b, c))
        n = np.cross(b - a, c - a)
        if np.dot(n, facing) < 0:
            b, c = c, b
        base = len(P)
        P.extend([a, b, c])
        F.append((base, base + 1, base + 2))

    def quad(p00, p10, p11, p01, facing):
        tri(p00, p10, p11, facing)
        tri(p00, p11, p01, facing)

    xs = [round(0.01 * i, 10) for i in range(27)]
    up, down = (0, 1, 0), (0, -1, 0)
    wall = 0.0 if solid else WALL
    for x0, x1 in zip(xs[:-1], xs[1:]):
        h0, h1 = h(x0), h(x1)
        # sole top and bottom over the full width
        quad((x0, h0, -HALF_W), (x1, h1, -HALF_W), (x1, h1, HALF_W), (x0, h0, HALF_W), up)
        quad((x0, 0, -HALF_W), (x1, 0, -HALF_W), (x1, 0, HALF_W), (x0, 0, HALF_W), down)
        # side walls from the ground to h + WALL (to h for the solid wedge)
        t0, t1 = h0 + wall, h1 + wall
        if shaft and x1 <= 0.10 + 1e-9:
            t0, t1 = max(t0, shaft), max(t1, shaft)
        for z, facing in ((HALF_W, (0, 0, 1)), (-HALF_W, (0, 0, -1))):
            quad((x0, 0, z), (x1, 0, z), (x1, t1, z), (x0, t0, z), facing)
        if not solid and x0 >= roof_from - 1e-9:
            quad((x0, h0 + WALL, -HALF_W), (x1, h1 + WALL, -HALF_W), (x1, h1 + WALL, HALF_W),
                 (x0, h0 + WALL, HALF_W), up)
    # end faces of the sole
    quad((0, 0, -HALF_W), (0, h(0), -HALF_W), (0, h(0), HALF_W), (0, 0, HALF_W), (-1, 0, 0))
    quad((LENGTH, 0, -HALF_W), (LENGTH, h(LENGTH), -HALF_W), (LENGTH, h(LENGTH), HALF_W), (LENGTH, 0, HALF_W),
         (1, 0, 0))
    if fin:
        quad((0.24, 0.04, 0), (LENGTH, 0.04, 0), (LENGTH, 0.15, 0), (0.24, 0.15, 0), (0, 0, 1))
    positions = np.asarray(P, np.float64)
    if rotate_180:                        # 180 deg about Y: (x, y, z) -> (-x, y, -z), winding kept
        positions = positions * np.array([-1.0, 1.0, -1.0])
    return positions, np.asarray(F, np.int64)


def shoe_garment(positions, faces):
    """The wedge as an unskinned ``glb_mesh.GarmentMesh`` (what the fit gets from the prepared GLB), each
    vertex carrying its face's unit normal (the wedge's vertices are not shared)."""
    from app.core import glb_mesh
    P = np.asarray(positions, np.float64)
    F = np.asarray(faces, np.int64)
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    N = np.zeros_like(P)
    N[F.ravel()] = np.repeat(n, 3, axis=0)
    return glb_mesh.GarmentMesh(positions=P, normals=N, uvs=np.zeros((len(P), 2)), indices=F,
                                joints=np.zeros((len(P), 4), np.int64), weights=np.zeros((len(P), 4)),
                                joint_names=[])


# --- the closed flat clog (Task 14 / 15) ---------------------------------------------------------------------------

def clog():
    """``(positions, faces)`` of the closed flat clog (smoke_footwear_cut.py [X7], smoke_footwear_fit_step.py), in
    the mesher's coordinates: a sole solid x in [0.01, 0.26] with its top (the insole) at 0.01, a floor plate
    from x = 0, side walls z = +-0.04 from the ground to 0.05 over x < 0.04 (the heel counter stands taller than
    the toe box: the analysis' heel rule), 0.035 behind the throat, 0.04 from x = 0.1825 on, a roof at 0.04 over
    [0.1825, 0.26], a heel-counter face at x = 0, the sole's rear end at 0.01, the toe-box front at 0.26 (walls
    tessellated every 0.0025). Closed everywhere, so the cut gates' flood fill stays outside."""
    L, HW, TOP, X0, STEP, W_LO, W_HI, ROOF = 0.26, 0.04, 0.01, 0.01, 0.1825, 0.035, 0.04, 0.04
    COUNTER, COUNTER_TO = 0.05, 0.04          # the heel counter stands taller than the toe box: the heel rule
    P, F = [], []

    def tri(a, b, c, facing):
        a, b, c = (np.asarray(v, np.float64) for v in (a, b, c))
        if np.dot(np.cross(b - a, c - a), facing) < 0:
            b, c = c, b
        base = len(P)
        P.extend([a, b, c])
        F.append((base, base + 1, base + 2))

    def quad(p00, p10, p11, p01, facing):
        tri(p00, p10, p11, facing)
        tri(p00, p11, p01, facing)

    def wall(x):
        if x < COUNTER_TO - 1e-9:
            return COUNTER
        return W_LO if x < STEP - 1e-9 else W_HI

    xs = [round(0.0025 * i, 10) for i in range(105)]
    for x0, x1 in zip(xs[:-1], xs[1:]):
        if x0 >= X0 - 1e-9:
            quad((x0, TOP, -HW), (x1, TOP, -HW), (x1, TOP, HW), (x0, TOP, HW), (0, 1, 0))
        quad((x0, 0, -HW), (x1, 0, -HW), (x1, 0, HW), (x0, 0, HW), (0, -1, 0))
        for z, facing in ((HW, (0, 0, 1)), (-HW, (0, 0, -1))):
            quad((x0, 0, z), (x1, 0, z), (x1, wall(x1), z), (x0, wall(x0), z), facing)
        if x0 >= STEP - 1e-9:
            quad((x0, ROOF, -HW), (x1, ROOF, -HW), (x1, ROOF, HW), (x0, ROOF, HW), (0, 1, 0))
    quad((0, 0, -HW), (0, COUNTER, -HW), (0, COUNTER, HW), (0, 0, HW), (-1, 0, 0))        # heel counter
    quad((X0, 0, -HW), (X0, TOP, -HW), (X0, TOP, HW), (X0, 0, HW), (-1, 0, 0))          # sole's rear end
    quad((L, 0, -HW), (L, ROOF, -HW), (L, ROOF, HW), (L, 0, HW), (1, 0, 0))              # toe box front
    return np.asarray(P, np.float64), np.asarray(F, np.int64)


# --- the synthetic feet (Task 9) ------------------------------------------------------------------------------------
#
# A skinned body GLB, Y up, facing +x (lateral z: right = forward x up = +z), joints with identity rotation:
# Hips (0, 0.90, 0) -> <Side>Leg (0, 0.45, zc) -> <Side>Foot (0, 0.08, zc) -> <Side>ToeBase (0.13, 0.01, zc),
# zc = -0.10 left, +0.10 right. Per side a foot box x in [-0.06, 0.19], y in [0, FOOT_H], z in zc +- width / 2,
# each face its own welded grid (x every 0.01, z in 4 columns, y one row) so every vertex normal is its face's:
# x <= 0.13 weighted 100 % Foot, x > 0.13 100 % ToeBase; plus a leg column x in [-0.03, 0.03], z in zc +- 0.03,
# y in [0.10, 0.45] weighted 100 % Leg. Joint names without a prefix ("LeftFoot").
#
# Two knobs make the heel-up male bodies of the boots plan (spec 2026-11-11 § 5, F1 / F2):
# ``heel_up`` raises the rear of the foot box (every face of it, so the box stays FOOT_H thick): the heel band
# x <= HEEL_UP_FLAT_X (-0.02) by the full ``heel_up``, then linearly down to 0 at x = HEEL_UP_TO (0.03); the
# forefoot x >= 0.03 stays on y = 0. The plateau under the heel band is what gives the heel contact one height
# (the rule reads the lowest down-facing vertex of the rear 0.045 and everything within 0.01 of it) and the
# ramp's 38.7 deg keeps the sole down-facing (normal up -0.78 < -0.4).
# ``shin_foot_weight`` gives the leg column's vertices that share of Foot weight (the rest Leg), as the
# auto-weighted male shins carry it: with it > FOOT_WEIGHT_MIN the shipped rule counted the shin as foot.
FOOT_H = 0.02
FOOT_ZC = {"Left": -0.10, "Right": 0.10}
FOOT_JOINTS = {"Hips": (0.0, 0.90, 0.0)}
for _side, _zc in FOOT_ZC.items():
    FOOT_JOINTS[f"{_side}Leg"] = (0.0, 0.45, _zc)
    FOOT_JOINTS[f"{_side}Foot"] = (0.0, 0.08, _zc)
    FOOT_JOINTS[f"{_side}ToeBase"] = (0.13, 0.01, _zc)
_FOOT_PARENT = {"Hips": None, "LeftLeg": "Hips", "LeftFoot": "LeftLeg", "LeftToeBase": "LeftFoot",
                "RightLeg": "Hips", "RightFoot": "RightLeg", "RightToeBase": "RightFoot"}


def _grid(P, F, J, origin, u, v, nu, nv, facing, joint_of):
    """A welded (nu+1) x (nv+1) grid origin + i u + j v, wound to face ``facing``."""
    origin, u, v = (np.asarray(t, np.float64) for t in (origin, u, v))
    base = len(P)
    for i in range(nu + 1):
        for j in range(nv + 1):
            p = origin + i * u + j * v
            P.append(p)
            J.append(joint_of(p))
    flip = np.dot(np.cross(u, v), facing) < 0
    for i in range(nu):
        for j in range(nv):
            a, b = base + i * (nv + 1) + j, base + (i + 1) * (nv + 1) + j
            c, d = b + 1, a + 1
            for t in ((a, b, c), (a, c, d)):
                F.append((t[0], t[2], t[1]) if flip else t)


HEEL_UP_FLAT_X = -0.02
HEEL_UP_TO = 0.03


def heel_raise(x: float, heel_up: float) -> float:
    """The ``heel_up`` raise of the foot box at ``x`` (block above): ``heel_up`` behind HEEL_UP_FLAT_X, a linear
    ramp to 0 at HEEL_UP_TO, 0 in front of it."""
    if heel_up <= 0.0 or x >= HEEL_UP_TO - 1e-9:
        return 0.0
    if x <= HEEL_UP_FLAT_X + 1e-9:
        return heel_up
    return heel_up * (HEEL_UP_TO - x) / (HEEL_UP_TO - HEEL_UP_FLAT_X)


def foot_body(ball_width: float = 0.085, heel_up: float = 0.0, shin_foot_weight: float = 0.0):
    """``(positions, faces, joints (N, 2), weights (N, 2), joint names)`` of the synthetic feet (block above):
    every vertex has two joint slots, the second one unused (joint 0, weight 0) except on the leg column with a
    ``shin_foot_weight`` > 0 (Foot ``shin_foot_weight`` / Leg the rest) — the default body's GLB bytes are the
    round-1 fixture's."""
    names = list(_FOOT_PARENT)
    P, F, J = [], [], []
    for side, zc in FOOT_ZC.items():
        fi, ti, li = names.index(f"{side}Foot"), names.index(f"{side}ToeBase"), names.index(f"{side}Leg")
        n_box = len(P)

        def foot_joint(p, fi=fi, ti=ti):
            return (fi, 0, 1.0) if p[0] <= 0.13 + 1e-9 else (ti, 0, 1.0)

        x0, x1, z0, w = -0.06, 0.19, zc - ball_width / 2, ball_width
        nx = 25
        dx, dz = (x1 - x0) / nx, w / 4
        _grid(P, F, J, (x0, 0, z0), (dx, 0, 0), (0, 0, dz), nx, 4, (0, -1, 0), foot_joint)          # sole
        _grid(P, F, J, (x0, FOOT_H, z0), (dx, 0, 0), (0, 0, dz), nx, 4, (0, 1, 0), foot_joint)      # top
        _grid(P, F, J, (x0, 0, z0), (dx, 0, 0), (0, FOOT_H, 0), nx, 1, (0, 0, -1), foot_joint)     # sides
        _grid(P, F, J, (x0, 0, z0 + w), (dx, 0, 0), (0, FOOT_H, 0), nx, 1, (0, 0, 1), foot_joint)
        _grid(P, F, J, (x0, 0, z0), (0, 0, dz), (0, FOOT_H, 0), 4, 1, (-1, 0, 0), foot_joint)      # heel
        _grid(P, F, J, (x1, 0, z0), (0, 0, dz), (0, FOOT_H, 0), 4, 1, (1, 0, 0), foot_joint)       # toe
        if heel_up > 0.0:
            for p in P[n_box:]:
                p[1] += heel_raise(float(p[0]), heel_up)
        leg = (lambda p, fi=fi, li=li: (fi, li, float(shin_foot_weight))) if shin_foot_weight > 0.0 \
            else (lambda p, li=li: (li, 0, 1.0))                                                    # noqa: E731
        lo = np.array([-0.03, 0.10, zc - 0.03])
        for axis_u, axis_v, n_axis in ((0, 2, 1), (0, 1, 2), (2, 1, 0)):
            for top in (False, True):
                u = np.zeros(3)
                u[axis_u] = 0.06 if axis_u != 1 else 0.35
                v = np.zeros(3)
                v[axis_v] = 0.06 if axis_v != 1 else 0.35
                o = lo.copy()
                if top:
                    o[n_axis] += 0.06 if n_axis != 1 else 0.35
                facing = np.zeros(3)
                facing[n_axis] = 1.0 if top else -1.0
                _grid(P, F, J, o, u, v, 1, 1, facing, leg)
    ja = np.asarray([(a, b) for a, b, _ in J], np.int64)
    wa = np.asarray([(w, 1.0 - w) for _, _, w in J], np.float64)
    return np.asarray(P), np.asarray(F, np.int64), ja, wa, names


def foot_body_glb(ball_width: float = 0.085, heel_up: float = 0.0, shin_foot_weight: float = 0.0) -> bytes:
    """The synthetic feet as a skinned GLB (skin 0 = the joints above, inverse bind matrices = -translation)."""
    from app.core.glb_mesh import pack_glb
    pos, faces, jidx, wgts, names = foot_body(ball_width, heel_up, shin_foot_weight)
    blob = bytearray()
    accessors, views = [], []

    def add(array, comp, typ, target=None):
        data = np.ascontiguousarray(array).tobytes()
        while len(blob) % 4:
            blob.append(0)
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        blob.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": len(array), "type": typ}
        if typ == "VEC3" and comp == 5126:
            acc["min"] = np.asarray(array).min(0).tolist()
            acc["max"] = np.asarray(array).max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    jnt = np.zeros((len(pos), 4), "<u2")
    jnt[:, :2] = jidx
    wgt = np.zeros((len(pos), 4), "<f4")
    wgt[:, :2] = wgts
    prim = {"attributes": {"POSITION": add(pos.astype("<f4"), 5126, "VEC3", 34962),
                           "JOINTS_0": add(jnt, 5123, "VEC4", 34962),
                           "WEIGHTS_0": add(wgt, 5126, "VEC4", 34962)},
            "indices": add(faces.reshape(-1).astype("<u4"), 5125, "SCALAR", 34963)}
    nodes = []
    for n in names:
        parent = _FOOT_PARENT[n]
        local = np.subtract(FOOT_JOINTS[n], FOOT_JOINTS[parent] if parent else (0, 0, 0))
        nodes.append({"name": n, "translation": [float(c) for c in local]})
    for i, n in enumerate(names):
        kids = [j for j, m in enumerate(names) if _FOOT_PARENT[m] == n]
        if kids:
            nodes[i]["children"] = kids
    ibm = np.stack([np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [-x, -y, -z, 1]], "<f4")
                    for x, y, z in (FOOT_JOINTS[n] for n in names)]).reshape(-1, 16)
    skin = {"joints": list(range(len(names))), "inverseBindMatrices": add(ibm, 5126, "MAT4")}
    nodes.append({"name": "Body", "mesh": 0, "skin": 0})
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, len(nodes) - 1]}],
            "nodes": nodes, "meshes": [{"name": "Body", "primitives": [prim]}], "skins": [skin],
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob) + (-len(blob) % 4)}]}
    return pack_glb(gltf, bytes(blob))
