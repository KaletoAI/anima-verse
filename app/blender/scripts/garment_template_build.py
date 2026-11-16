"""Drape one garment template onto a plain rigged body (P1, Ruling A138).

Runner contract (``app/blender/runner.py``): ``inputs`` {body: the plain rigged
base GLB, front / back: the piece's views (cut-outs or the item picture)},
``params`` from ``app.core.garment_template.build_args``:

* ``spec``    the sampled pygarment panels (``panel_spec``): rows x cols grids per
              panel (front, back; each half the circumference), ``row_y`` = the
              world height of every row (Blender Z = glTF Y), row 0 = the pinned top;
* ``fabric``  bending / mass / quality / shrink of the cloth run;
* ``slit``    {side: none|left|right|front|back, depth_m}: vertical edges at that
              angle are split from the hem up;
* ``node``    the name of the exported garment node (``garment_…``);
* ``poses``   the poses measured after the drape (spike evaluator), ``render``.

Steps: wrap the panel rows round the body axis (radius = the pattern's own, never
closer than 2 cm outside the body; the pinned top row FOLLOWS the body at 6 mm —
the spike's open point), merge the side seams, split the slit, pin the top row,
cloth-drape on the voxel-remeshed posed body (spike ``drape``), measure stretch,
Solidify 1.5 mm, project the views onto the panel UVs, skin by Data Transfer,
measure the poses, export armature + garment. Wall and CPU seconds are reported
for the drape and the whole script.
"""
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
from _common import main  # noqa: E402
import garment_template_drape as gd  # noqa: E402
sys.path.pop(0)

#: Angle of each slit side (0 = +X = the character's left, front = -Y).
SLIT_ANGLE = {"left": 0.0, "back": math.pi / 2, "right": math.pi, "front": 3 * math.pi / 2}
TOP_CLEAR_M = 0.006
ROW_CLEAR_M = 0.02


def wrap(spec, btree, centre):
    """Vertices / quads / UVs of the panels wrapped round the body axis."""
    rows, cols = spec["rows"], spec["cols"]
    row_y = spec["row_y"]
    spans = {"front": (math.pi, 2 * math.pi), "back": (0.0, math.pi)}
    verts, faces, uvs, angles = [], [], [], []
    allg = np.array([p["grid_m"] for p in spec["panels"]])
    xmin, xmax = allg[..., 0].min(), allg[..., 0].max()
    ymax = allg[..., 1].max()
    for pi_, p in enumerate(spec["panels"]):
        g = np.array(p["grid_m"])
        a0, a1 = spans[p["name"]]
        for r in range(rows):
            row = g[r]
            circ = 2 * float(np.sum(np.linalg.norm(np.diff(row, axis=0), axis=1)))
            z = row_y[r]
            for c in range(cols):
                ang = a0 + (a1 - a0) * c / (cols - 1)
                body_r = gd.body_radius(btree, centre, ang, z)
                if r == 0:
                    rad = body_r + TOP_CLEAR_M if body_r > 0 else circ / (2 * math.pi)
                else:
                    rad = max(circ / (2 * math.pi), body_r + ROW_CLEAR_M)
                verts.append((centre[0] + rad * math.cos(ang), centre[1] + rad * math.sin(ang), z))
                uvs.append((0.02 + 0.47 * (row[c, 0] - xmin) / max(1e-6, xmax - xmin) + 0.5 * pi_,
                            0.02 + 0.96 * row[c, 1] / max(1e-6, ymax)))
                angles.append(ang)
        base = pi_ * rows * cols
        for r in range(rows - 1):
            for c in range(cols - 1):
                i = base + r * cols + c
                faces.append((i, i + 1, i + cols + 1, i + cols))
    return verts, faces, uvs, angles


def split_slit(obj, angles, slit, hem_z, centre):
    """Split the vertical edges at the slit's angle from the hem up to ``depth_m``."""
    side, depth = slit.get("side"), float(slit.get("depth_m") or 0)
    if side not in SLIT_ANGLE or depth <= 0:
        return 0
    target = SLIT_ANGLE[side]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()

    def ang_of(v):
        a = math.atan2(v.co.y - centre[1], v.co.x - centre[0]) % (2 * math.pi)
        d = abs(a - target)
        return min(d, 2 * math.pi - d)
    step = 2 * math.pi / 80
    cut = [e for e in bm.edges
           if all(ang_of(v) < step * 0.5 for v in e.verts)
           and max(v.co.z for v in e.verts) <= hem_z + depth + 1e-4
           and abs(e.verts[0].co.z - e.verts[1].co.z) > 1e-4]
    if cut:
        bmesh.ops.split_edges(bm, edges=cut)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(cut)


#: Ruling A141 — pose-space corrective shapes. The skinned drape is right only near the pose it was
#: draped in; a pose that bends the legs far (sit, kneel) lifts the hem off like a plate. Each pose of
#: ``SHAPE_POSES`` is draped again (cloth, starting from the skinned drape in that pose, against the
#: posed body + a floor, and a seat for sit), the result taken back through the inverse skinning into
#: the bind pose and stored as a morph target. ``ANCHOR_POSES`` are samples WITHOUT a shape (the
#: skinned drape is kept there). The renderers blend the targets by the leg directions
#: (``driver_features`` / ``blend``; the same rule in ``packages/scene-render/src/poseShapes.ts``).
SHAPE_POSES = ("sit", "kneel")
ANCHOR_POSES = ("rest", "walk")
#: The driver: four leg segments (joint head to joint head), thighs first.
DRIVER_SEGMENTS = (("LeftUpLeg", "LeftLeg"), ("RightUpLeg", "RightLeg"),
                   ("LeftLeg", "LeftFoot"), ("RightLeg", "RightFoot"))
#: Gaussian width of the sample blend (radians of summed segment angle).
DRIVER_SIGMA = 0.5
SHAPE_FRAMES = 40
#: Weight inpainting: a cloth vertex within NEAR_M of the body keeps its transferred weights, beyond
#: FAR_M it takes the weights diffused from its neighbours (linear in between).
NEAR_M = 0.02
FAR_M = 0.05
SMOOTH_ITER = 600
#: A hem vertex higher than its upward neighbour by more than this is flipped up.
HEM_UP_M = 0.005
#: A hem vertex stands off like a plate when the cloth runs into it less than PLATE_DEG below the
#: horizontal while it is more than PLATE_OFF_M from the body (nothing holds it up there).
PLATE_DEG = 30.0
PLATE_OFF_M = 0.03
#: The corrective drapes use at least this bending (a settle from the skinned pose crumples a soft
#: fabric into folds a static shape cannot carry well).
SHAPE_MIN_BENDING = 0.5


def to_gltf(v):
    """Blender Z-up world -> glTF Y-up model axes."""
    return (float(v[0]), float(v[2]), float(-v[1]))


def driver_features(arm):
    """The four leg segment directions with the hips' rotation since rest taken out, glTF axes."""
    P = gd.P
    hb = arm.pose.bones[P + "Hips"]
    rot = ((arm.matrix_world @ hb.matrix).to_3x3().normalized()
           @ (arm.matrix_world @ hb.bone.matrix_local).to_3x3().normalized().inverted())
    inv = rot.inverted()
    out = []
    for a, b in DRIVER_SEGMENTS:
        ha = arm.matrix_world @ arm.pose.bones[P + a].head
        hb2 = arm.matrix_world @ arm.pose.bones[P + b].head
        d = inv @ (hb2 - ha)
        d.normalize()
        out.append([round(x, 5) for x in to_gltf(d)])
    return out


def mirror_features(f):
    """The pose mirrored left <-> right (glTF x negated, the sides swapped)."""
    m = [[-x, y, z] for x, y, z in f]
    return [m[1], m[0], m[3], m[2]]


def blend(features, samples, sigma=DRIVER_SIGMA):
    """``{target: influence}``: normalised Gaussian weights of the samples by the summed squared
    segment angles; a target's influence = the share of its samples (anchors carry none)."""
    g = []
    for s in samples:
        d2 = 0.0
        for u, v in zip(features, s["dirs"]):
            c = max(-1.0, min(1.0, sum(a * b for a, b in zip(u, v))))
            d2 += math.acos(c) ** 2
        g.append(math.exp(-d2 / (2 * sigma * sigma)))
    total = sum(g) or 1.0
    out = {}
    for s, w in zip(samples, g):
        if s.get("target"):
            out[s["target"]] = out.get(s["target"], 0.0) + w / total
    return out


def weight_matrix(obj):
    names = [g.name for g in obj.vertex_groups]
    W = np.zeros((len(obj.data.vertices), len(names)))
    for v in obj.data.vertices:
        for ge in v.groups:
            W[v.index, ge.group] = ge.weight
    return names, W


def write_weights(obj, W):
    for j, g in enumerate(obj.vertex_groups):
        g.remove(list(range(len(obj.data.vertices))))
        idx = np.where(W[:, j] > 0)[0]
        for i in idx:
            g.add([int(i)], float(W[i, j]), "REPLACE")


def smooth_weights(obj, body):
    """Inpaint the bone weights of the cloth that hangs free (robust weight transfer): vertices near
    the body keep the nearest-face weights, the rest take weights diffused over the mesh (Jacobi,
    the near ones fixed). Between the legs a skirt no longer jumps from one thigh to the other.
    Returns ``{fixed_share, free_share}``."""
    names, W = weight_matrix(obj)
    used = np.where(W.max(0) > 0)[0]
    Wu = W[:, used]
    n = len(Wu)
    bco, _bn, btri = gd.world_coords(body)
    tree = gd.bvh_of(bco, btri)
    co = np.array([obj.matrix_world @ v.co for v in obj.data.vertices])
    d = np.array([(tree.find_nearest(Vector(c))[3] or 1.0) for c in co])
    conf = np.clip((FAR_M - d) / (FAR_M - NEAR_M), 0.0, 1.0)
    fixed = conf >= 0.999
    E = gd.edges_of(obj)
    deg = np.bincount(E.ravel(), minlength=n).astype(float)
    S = Wu.copy()
    if fixed.any():
        for _ in range(SMOOTH_ITER):
            acc = np.zeros_like(S)
            np.add.at(acc, E[:, 0], S[E[:, 1]])
            np.add.at(acc, E[:, 1], S[E[:, 0]])
            S = np.where(fixed[:, None], Wu, acc / np.maximum(deg, 1.0)[:, None])
    out = conf[:, None] * Wu + (1 - conf[:, None]) * S
    # four strongest, normalised
    order = np.argsort(-out, axis=1)[:, 4:]
    np.put_along_axis(out, order, 0.0, axis=1)
    out /= np.maximum(out.sum(1, keepdims=True), 1e-9)
    W2 = np.zeros_like(W)
    W2[:, used] = out
    write_weights(obj, W2)
    return {"fixed_share": round(float(fixed.mean()), 4), "free_share": round(float((conf <= 0).mean()), 4)}


def hem_sets(obj, top_z):
    """Hem vertices (boundary, not the waistband) and, per hem vertex, its upward neighbour."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    hem, up = [], []
    for v in bm.verts:
        if v.co.z > top_z - 0.03 or not any(e.is_boundary for e in v.link_edges):
            continue
        best = max((e.other_vert(v) for e in v.link_edges), key=lambda o: o.co.z)
        if best.co.z > v.co.z + 0.002:
            hem.append(v.index)
            up.append(best.index)
    bm.free()
    return np.array(hem, int), np.array(up, int)


def hem_metrics(obj, body, hem, up):
    """The hem in the current pose: ``hem_plate_share`` (see PLATE_DEG), ``hem_up_share`` = hem vertices above their upward neighbour
    by > HEM_UP_M (the cloth climbs to the hem = flipped up), ``hem_lift_p90_mm`` = that rise,
    ``hem_standoff_mm`` = median distance of the hem from the body surface."""
    if not len(hem):
        return {}
    gco, _gn, _gt = gd.world_coords(obj)
    bco, _bn, btri = gd.world_coords(body)
    tree = gd.bvh_of(bco, btri)
    rise = gco[hem, 2] - gco[up, 2]
    dist = np.array([tree.find_nearest(Vector(gco[i]))[3] or 0.0 for i in hem])
    seg = gco[hem] - gco[up]
    descent = np.degrees(np.arcsin(np.clip(-seg[:, 2] / np.maximum(np.linalg.norm(seg, axis=1), 1e-9), -1, 1)))
    plate = (descent < PLATE_DEG) & (dist > PLATE_OFF_M)
    return {"hem_plate_share": round(float(plate.mean()), 4),
            "hem_up_share": round(float((rise > HEM_UP_M).mean()), 4),
            "hem_lift_p90_mm": round(float(max(0.0, np.percentile(rise, 90)) * 1000), 1),
            "hem_standoff_mm": round(float(np.median(dist) * 1000), 1)}


def skin_matrices(arm, names):
    amw = arm.matrix_world
    inv = amw.inverted()
    M = np.zeros((len(names), 4, 4))
    for j, nm in enumerate(names):
        pb = arm.pose.bones.get(nm)
        M[j] = np.eye(4) if pb is None else np.array(amw @ pb.matrix @ pb.bone.matrix_local.inverted() @ inv)
    return M


def _box(name, lo, hi):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector([lo[k] + (v.co[k] + 0.5) * (hi[k] - lo[k]) for k in range(3)])
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new("col", "COLLISION")
    ob.collision.thickness_outer = 0.004
    ob.collision.cloth_friction = 5.0
    return ob


def supports(arm, body, pose):
    """What the pose rests on: the floor under the body's lowest point; for sit a seat under the
    thighs from the knee pits back."""
    bco, _bn, _bt = gd.world_coords(body)
    lo = bco.min(0)
    hi = bco.max(0)
    out = [_box("floor", (lo[0] - 1, lo[1] - 1, lo[2] - 0.1), (hi[0] + 1, hi[1] + 1, lo[2] - 0.002))]
    if pose == "sit":
        names = [gd.P + n for n in ("Hips", "LeftUpLeg", "RightUpLeg")]
        idx = set()
        for nm in names:
            g = body.vertex_groups.get(nm)
            if g is None:
                continue
            for v in body.data.vertices:
                for ge in v.groups:
                    if ge.group == g.index and ge.weight > 0.5:
                        idx.add(v.index)
        if idx:
            pts = bco[sorted(idx)]
            knee_y = max((arm.matrix_world @ arm.pose.bones[gd.P + s + "Leg"].head).y for s in ("Left", "Right"))
            top = float(pts[:, 2].min()) - 0.002
            out.append(_box("seat", (pts[:, 0].min() - 0.08, knee_y + 0.06, top - 0.05),
                            (pts[:, 0].max() + 0.08, pts[:, 1].max() + 0.25, top)))
    return out


def pose_shape(arm, body, obj, pose, pin, names, W, rest_world, fab, thickness):
    """The corrective of one pose, as world-space deltas at the bind pose (n x 3) + its numbers."""
    gd.set_pose(arm, pose)
    M = skin_matrices(arm, names)
    Mv = np.einsum("ng,gij->nij", W, M)
    ph = np.c_[rest_world, np.ones(len(rest_world))]
    skinned = np.einsum("nij,nj->ni", Mv, ph)[:, :3]
    ev, _n, _t = gd.world_coords(obj)
    skin_err = float(np.abs(ev[:len(skinned)] - skinned).max() * 1000)
    me = bpy.data.meshes.new("pose_" + pose)
    me.from_pydata(skinned.tolist(), [], [tuple(p.vertices) for p in obj.data.polygons])
    tmp = bpy.data.objects.new("pose_" + pose, me)
    bpy.context.scene.collection.objects.link(tmp)
    held = supports(arm, body, pose)
    cpu, wall, drift = gd.drape(tmp, body, pin, SHAPE_FRAMES, quality=int(fab["quality"]),
                                bending=max(float(fab["bending"]), SHAPE_MIN_BENDING),
                                shrink=float(fab.get("shrink", 0.0)), self_collision=False, thickness=thickness)
    draped = np.array([tmp.matrix_world @ v.co for v in tmp.data.vertices])
    for o in [tmp, *held]:
        bpy.data.objects.remove(o)
    back = np.einsum("nij,nj->ni", np.linalg.inv(Mv), np.c_[draped, np.ones(len(draped))])[:, :3]
    delta = back - rest_world
    moved = np.linalg.norm(draped - skinned, axis=1)
    return delta, {"cpu_s": cpu, "wall_s": wall, "pin_drift_mm": drift, "skin_err_mm": round(skin_err, 3),
                   "moved_p90_mm": round(float(np.percentile(moved, 90) * 1000), 1),
                   "moved_max_mm": round(float(moved.max() * 1000), 1)}


def export_glb(path, objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(path), use_selection=True, export_skins=True, export_morph=True,
                              export_morph_normal=False, export_animations=False)


def run(a):
    t_all, c_all = time.time(), time.process_time()
    inp, prm = a["inputs"], a["params"]
    out = Path(a["out_dir"])
    arm, body, _g = gd.load_fit(inp["body"])
    spec = prm["spec"]
    bco, _bn, btri = gd.world_coords(body)
    # the radius tree is the torso + legs only: a T-posed arm beside the chest band would
    # otherwise be the "body" a ray from outside meets first (the band then spans the arms)
    half = float(prm.get("torso_half_m") or 0.24)
    tri = np.asarray(btri)
    keep = np.all(np.abs(bco[tri][..., 0]) < half, axis=1)
    btree = gd.bvh_of(bco, [tuple(t) for t in tri[keep]])
    top_z = spec["row_y"][0]
    sl = bco[np.abs(bco[:, 2] - top_z) < 0.01]
    centre = sl[:, :2].mean(0) if len(sl) else bco[:, :2].mean(0)
    verts, faces, uvs, angles = wrap(spec, btree, centre)
    me = bpy.data.meshes.new("template")
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name="UVMap")
    for lp in me.loops:
        uvl.data[lp.index].uv = uvs[lp.vertex_index]
    obj = bpy.data.objects.new(prm["node"], me)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.004)   # the two side seams
    bm.to_mesh(me)
    bm.free()
    hem_z = spec["row_y"][-1]
    slit_edges = split_slit(obj, angles, prm.get("slit") or {}, hem_z, centre)
    me = obj.data
    co0 = np.array([v.co for v in me.vertices])
    edges = gd.edges_of(obj)
    rest_len = np.linalg.norm(co0[edges[:, 0]] - co0[edges[:, 1]], axis=1)
    pin = np.where(co0[:, 2] > top_z - 0.004)[0]
    fab = prm["fabric"]
    thickness = float(prm.get("thickness", 0.004))
    cpu, wall, drift = gd.drape(obj, body, pin, int(prm.get("frames", 50)), quality=int(fab["quality"]),
                                bending=float(fab["bending"]), shrink=float(fab.get("shrink", 0.0)),
                                self_collision=False, thickness=thickness)
    me = obj.data
    co1 = np.array([v.co for v in me.vertices])
    st = np.linalg.norm(co1[edges[:, 0]] - co1[edges[:, 1]], axis=1) / np.maximum(rest_len, 1e-6)
    worst = co0[edges[int(st.argmax())]].mean(0)
    worst_at = {"z": round(float(worst[2]), 3),
                "deg": round(math.degrees(math.atan2(worst[1] - centre[1], worst[0] - centre[0])) % 360, 1),
                "over_1_3": int((st > 1.3).sum())}
    n_single = len(me.vertices)
    hem, up = hem_sets(obj, top_z)
    # skin the single layer (the corrective drapes need it), inpaint the free cloth's weights
    gd.bind_to_armature(obj, body, arm)
    weights = smooth_weights(obj, body) if prm.get("smooth_weights", True) else {}
    names, W = weight_matrix(obj)
    rest_world = np.array([obj.matrix_world @ v.co for v in obj.data.vertices])
    shape_poses = [p for p in (prm.get("shape_poses") if prm.get("shape_poses") is not None else SHAPE_POSES)]
    deltas, shape_info = {}, {}
    t_shape = time.time()
    for pose in shape_poses:
        deltas[pose], shape_info[pose] = pose_shape(arm, body, obj, pose, pin, names, W, rest_world, fab, thickness)
    gd.set_pose(arm, "rest")
    shape_wall = round(time.time() - t_shape, 2)
    # Solidify without the armature in the stack: its copy layer follows the original vertex order
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    sol = obj.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.0015
    sol.offset = 1
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=sol.name)
    # cloth is smooth: flat faces would also split every vertex four ways in the export (four times the
    # morph data)
    obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))
    co2 = np.array([v.co for v in obj.data.vertices])
    layers = len(co2) // n_single if len(co2) % n_single == 0 else 0
    ref = rest_world_local(obj, rest_world)
    layer_err = [float(np.abs(co2[k * n_single:(k + 1) * n_single] - ref).max()) for k in range(layers)]
    if deltas and not (layers >= 1 and min(layer_err) < 0.003):
        raise RuntimeError(f"solidify changed the vertex order ({len(co2)} verts from {n_single}, {layer_err})")
    arm_mod = obj.modifiers.new("arm", "ARMATURE")
    arm_mod.object = arm
    rot_inv = np.array(obj.matrix_world.to_3x3().inverted())
    targets = []
    if deltas:
        obj.shape_key_add(name="Basis", from_mix=False)
        for pose in shape_poses:
            kb = obj.shape_key_add(name=pose, from_mix=False)
            dl = (deltas[pose] @ rot_inv.T)
            full = np.tile(dl, (layers, 1))
            flat = (co2 + full).astype(np.float32).ravel()
            kb.data.foreach_set("co", flat)
            kb.value = 0.0
            targets.append(pose)
    samples = []
    for pose in [*ANCHOR_POSES, *shape_poses]:
        gd.set_pose(arm, pose)
        f = driver_features(arm)
        target = pose if pose in deltas else None
        samples.append({"pose": pose, "target": target, "dirs": f})
        mf = mirror_features(f)
        if max(abs(a - b) for u, v in zip(f, mf) for a, b in zip(u, v)) > 1e-3:
            samples.append({"pose": pose + "_mirror", "target": target, "dirs": mf})
    gd.set_pose(arm, "rest")
    pose_shapes = {"version": 1, "segments": [list(s) for s in DRIVER_SEGMENTS], "sigma": DRIVER_SIGMA,
                   "targets": targets, "samples": samples} if targets else None
    t_bake = time.time()
    tex = gd.project_bake(obj, {"view_front": inp["front"], "view_back": inp["back"]},
                          out / "template_atlas.png", size=1024)
    tex["wall_s"] = round(time.time() - t_bake, 2)
    edges2 = gd.edges_of(obj)
    rest2 = np.linalg.norm(co2[edges2[:, 0]] - co2[edges2[:, 1]], axis=1)
    rim = gd.boundary_verts(obj)
    view = gd.frame_of(co2)
    t_meas = time.time()
    measured = {}
    for pose in prm.get("poses") or ["rest"]:
        gd.set_pose(arm, pose)
        inf = blend(driver_features(arm), samples) if pose_shapes else {}
        for name in targets:
            obj.data.shape_keys.key_blocks[name].value = float(inf.get(name, 0.0))
        measured[pose] = gd.measure_pose(arm, body, obj, pose, rest2, edges2, rim)
        measured[pose].update(hem_metrics(obj, body, hem, up))
        measured[pose]["shapes"] = {k: round(v, 4) for k, v in inf.items()}
        if prm.get("render"):
            gd.render(out / f"template_{pose}.png", view)
            # the posed garment (glTF axes, float32) for checks of a renderer against this pose
            gco, _gn, _gt = gd.world_coords(obj)
            np.ascontiguousarray(np.c_[gco[:, 0], gco[:, 2], -gco[:, 1]], np.float32).tofile(
                str(out / f"template_{pose}_posed.f32"))
    for name in targets:
        obj.data.shape_keys.key_blocks[name].value = 0.0
    gd.set_pose(arm, "rest")
    meas_s = round(time.time() - t_meas, 2)
    glb = out / "template.glb"
    export_glb(glb, [arm, obj])
    outputs = {"glb": str(glb), "atlas": str(out / "template_atlas.png")}
    for pose in measured:
        p = out / f"template_{pose}.png"
        if p.is_file():
            outputs[f"render_{pose}"] = str(p)
        q = out / f"template_{pose}_posed.f32"
        if q.is_file():
            outputs[f"posed_{pose}"] = str(q)
    data = {"verts": len(obj.data.vertices), "pins": int(len(pin)), "slit_edges": int(slit_edges),
            "drape": {"cpu_s": cpu, "wall_s": wall, "pin_drift_mm": drift,
                      "stretch_max": round(float(st.max()), 3), "stretch_at": worst_at, "stretch_p99": round(float(np.percentile(st, 99)), 3),
                      "quality": int(fab["quality"])},
            "weights": weights, "shapes": {"wall_s": shape_wall, **shape_info}, "pose_shapes": pose_shapes,
            "hem_verts": int(len(hem)),
            "bake": tex, "draped": measured, "measure_wall_s": meas_s,
            "script_wall_s": round(time.time() - t_all, 2), "script_cpu_s": round(time.process_time() - c_all, 2)}
    return gd._plain(data), outputs


def rest_world_local(obj, rest_world):
    """The bind-pose world coordinates in the object's own space."""
    inv = np.array(obj.matrix_world.inverted())
    return rest_world @ inv[:3, :3].T + inv[:3, 3]


if __name__ == "__main__":
    main(run)
