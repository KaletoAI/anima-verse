"""Garment drape spike (A135 S0): cloth-drape a worn piece onto a rigged base body.

Runs headless (``blender -b --factory-startup --python <this> -- args.json``),
same job contract as the other scripts (``_common.main``). Nothing is wired into
the Build yet; ``app/core/garment_template.py`` builds the args and reads the result.

Modes (``args["mode"]``):

* ``mesh``      an EXISTING generated piece (the fit GLB: body + armature + fitted
                garment). Clean (drop fragments < ``min_part_share`` of the area,
                merge by distance), voxel-remesh to ``voxel_m`` edges, keep the outer
                wall only (single-layer shell), bake the original texture onto the
                remesh (Cycles, selected-to-active), pin a ring (``pin``: waist |
                shoulders), cloth-drape on the body, transfer weights, export.
                The un-draped fit is measured by the SAME evaluator as the baseline.
* ``panels``    a pygarment pattern sampled to quad grids (``gen_skirt`` JSON):
                wrap the panels round the body axis, pre-inflate outside the body,
                merge the seams, pin the waistband, drape; texture = projection of
                the piece's front/back cut-out views onto the panel UVs.
* ``from_body`` a tight piece cut from the body itself: region = bone weights x cut
                planes, normal offset, Solidify; weights and UVs inherited.
* ``necklace``  a closed chain (+ a pendant disc) dropped as a cloth string on the
                neck/chest, against the procedural surface curve.

Every mode measures the same numbers in four poses (rest, walk, sit, kneel; arms
lowered in all but rest): body vertices poking through the piece, piece edge
vertices inside the body (hem/cuff vs leg/arm), edge stretch vs the pre-drape
lengths; plus drape CPU seconds and pin drift. Renders one image per pose.
"""
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).parent))
from _common import main  # noqa: E402
sys.path.pop(0)

#: A172: the live progress side channel of a run — ``progress_file`` of the job params (the server reads it while the
#: run is in flight, the dialog shows it). A small JSON object, replaced atomically; never part of the result.
PROGRESS = {"file": None, "state": {}}


def progress(**fields):
    """Merge ``fields`` into the run's progress record and write it (no-op without a ``progress_file``; a write that
    fails is ignored — progress is never worth a failed drape)."""
    path = PROGRESS["file"]
    if not path:
        return
    PROGRESS["state"].update(fields)
    try:
        import json
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps(PROGRESS["state"]), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


P = "mixamorig:"
# world-axis rotations (deg) per pose; the glTF import faces -Y, so a NEGATIVE X
# rotation flexes a thigh forward and a positive one bends a knee back
POSES = {
    "rest": [],
    "walk": [("LeftUpLeg", "X", -25), ("RightUpLeg", "X", 20), ("RightLeg", "X", 30), ("LeftLeg", "X", 10)],
    "sit": [("LeftUpLeg", "X", -85), ("RightUpLeg", "X", -85), ("LeftLeg", "X", 90), ("RightLeg", "X", 90)],
    "kneel": [("LeftUpLeg", "X", -10), ("RightUpLeg", "X", -10), ("LeftLeg", "X", 100), ("RightLeg", "X", 100)],
    # Ruling A142 — arm poses (the bind pose is the T-pose): a positive Y rotation lowers the left arm (+X), a
    # negative Z rotation swings it forward (-Y); the right arm mirrored.
    "arms_down": [("LeftArm", "Y", 72), ("RightArm", "Y", -72), ("LeftForeArm", "X", -15), ("RightForeArm", "X", -15)],
    "arms_forward": [("LeftArm", "Z", -80), ("RightArm", "Z", 80), ("LeftForeArm", "Z", -10), ("RightForeArm", "Z", 10)],
    "arms_up": [("LeftArm", "Y", -60), ("RightArm", "Y", 60)],
}
#: Poses that set the arms themselves (ARMS_DOWN is not added to them).
ARM_POSES = ("rest", "arms_down", "arms_forward", "arms_up")
COLLIDER_VOXEL_M = 0.005  # closed, outward-wound collider (see drape)
RIM_BAND_M = 0.02   # body vertices this close to a piece opening are not judged
#: Ruling A142: a body vertex with other skin within this distance outward (arm on the flank, thigh on thigh) is a
#: contact, not judged — no cloth fits between (two layers of 1.5 mm + the 4 mm collision distance each side).
CONTACT_M = 0.012
ARMS_DOWN = [("LeftArm", "Y", 30), ("RightArm", "Y", -30), ("LeftForeArm", "X", -20), ("RightForeArm", "X", -20)]


# ---------------------------------------------------------------- scene helpers
def load_fit(path, plain_body=None):
    """The fit GLB (armature + body + fitted piece). Its body is the COVERED variant
    (skin under the piece pulled in), so measurements and the collider use the PLAIN
    rigged base body (plain_body), re-targeted onto the fit's armature by bone name."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    body = next(o for o in bpy.data.objects if o.type == "MESH" and o.name == "mesh")
    garment = next((o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("garment_")), None)
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o not in (body, garment):
            bpy.data.objects.remove(o)
    if plain_body:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(plain_body))
        new = [o for o in bpy.data.objects if o not in before]
        nbody = max((o for o in new if o.type == "MESH"), key=lambda o: len(o.data.vertices))
        mw = nbody.matrix_world.copy()
        nbody.parent = arm
        nbody.matrix_world = mw
        for m in nbody.modifiers:
            if m.type == "ARMATURE":
                m.object = arm
        for o in new:
            if o is not nbody:
                bpy.data.objects.remove(o)
        bpy.data.objects.remove(body)
        body = nbody
        body.name = "plain_body"
    arm.data.pose_position = "POSE"
    return arm, body, garment


def world_coords(obj, evaluated=True):
    dg = bpy.context.evaluated_depsgraph_get()
    ob = obj.evaluated_get(dg) if evaluated else obj
    me = ob.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(obj.matrix_world)
    co = co @ mw[:3, :3].T + mw[:3, 3]
    nr = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("normal", nr)
    nr = nr.reshape(-1, 3) @ mw[:3, :3].T
    nr /= np.linalg.norm(nr, axis=1, keepdims=True) + 1e-12
    tris = [tuple(p.vertices) for p in me.polygons]
    ob.to_mesh_clear()
    return co, nr, tris


_FLIPS = {}


def oriented_bmesh(obj):
    """Posed body with CONSISTENT outward winding (generated meshes mix windings; the
    raw normals disagree with their neighbours on ~18 % of Kira's vertices)."""
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    bm.from_object(obj, dg)
    bm.transform(obj.matrix_world)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # recalc orients each island on its own and can get one wrong; check every island of
    # >= 50 faces by ray parity once (rest) and replay the flips on posed states (same
    # topology, recalc is deterministic)
    bm.faces.ensure_lookup_table()
    key = (obj.name, len(bm.faces))
    if key not in _FLIPS:
        tree = BVHTree.FromBMesh(bm)
        seen, flips = set(), []
        for f0 in bm.faces:
            if f0.index in seen:
                continue
            isl, stack = [], [f0]
            seen.add(f0.index)
            while stack:
                f = stack.pop()
                isl.append(f)
                for e in f.edges:
                    for g in e.link_faces:
                        if g.index not in seen:
                            seen.add(g.index)
                            stack.append(g)
            if len(isl) < 10:
                continue
            votes = 0
            for f in isl[:: max(1, len(isl) // 9)][:9]:
                o, d, hits = f.calc_center_median() + f.normal * 1e-4, f.normal.copy(), 0
                for _ in range(40):
                    h = tree.ray_cast(o, d, 5.0)
                    if h[0] is None:
                        break
                    hits += 1
                    o = h[0] + d * 1e-4
                votes += 1 if hits % 2 == 0 else -1
            if votes < 0:
                flips.extend(f.index for f in isl)
        _FLIPS[key] = flips
    if _FLIPS[key]:
        bmesh.ops.reverse_faces(bm, faces=[bm.faces[i] for i in _FLIPS[key]])
    bm.normal_update()
    return bm


def body_state(obj):
    """Posed body (world space) with consistent outward winding."""
    bm = oriented_bmesh(obj)
    co = np.array([v.co for v in bm.verts], np.float32)
    nr = np.array([v.normal for v in bm.verts], np.float32)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    return co, nr, tree


def bvh_of(co, tris):
    return BVHTree.FromPolygons([Vector(c) for c in co], tris)


def set_pose(arm, name):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    steps = list(POSES[name]) + (ARMS_DOWN if name not in ARM_POSES else [])
    for bone, axis, deg in steps:
        pb = arm.pose.bones.get(P + bone)
        if pb is None:
            continue
        mw = arm.matrix_world @ pb.matrix
        head = mw.translation.copy()
        rot = Matrix.Rotation(math.radians(deg), 4, axis)
        new = Matrix.Translation(head) @ rot @ Matrix.Translation(-head) @ mw
        pb.matrix = arm.matrix_world.inverted() @ new
        bpy.context.view_layer.update()


def bind_to_armature(obj, body, arm):
    """Data Transfer of the body's bone weights (nearest face interpolated), limit 4."""
    for g in list(obj.vertex_groups):
        obj.vertex_groups.remove(g)
    for g in body.vertex_groups:
        obj.vertex_groups.new(name=g.name)
    dt = obj.modifiers.new("dt", "DATA_TRANSFER")
    dt.object = body
    dt.use_vert_data = True
    dt.data_types_verts = {"VGROUP_WEIGHTS"}
    dt.vert_mapping = "POLYINTERP_NEAREST"
    dt.layers_vgroup_select_src = "ALL"
    dt.layers_vgroup_select_dst = "NAME"
    bpy.context.view_layer.objects.active = obj
    # body must be in rest for a correct transfer
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    bpy.ops.object.modifier_apply(modifier=dt.name)
    arm.data.pose_position = "POSE"
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
    bpy.ops.object.vertex_group_normalize_all(lock_active=False)
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    m = obj.modifiers.new("arm", "ARMATURE")
    m.object = arm


def freeze(obj):
    """Replace the mesh by its evaluated state (cloth last frame) and drop modifiers."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    old = obj.data
    obj.modifiers.clear()
    obj.data = me
    bpy.data.meshes.remove(old)


def boundary_verts(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    idx = sorted({v.index for e in bm.edges if e.is_boundary for v in e.verts})
    bm.free()
    return np.array(idx, int)


def edges_of(obj):
    e = np.empty(len(obj.data.edges) * 2, np.int64)
    obj.data.edges.foreach_get("vertices", e)
    return e.reshape(-1, 2)


# ---------------------------------------------------------------- measurement
def bone_segments(arm, names=None):
    segs = []
    for pb in arm.pose.bones:
        if "Hand" in pb.name and not pb.name.endswith("Hand"):
            continue                                 # finger bones: no piece reaches them
        segs.append((np.array(arm.matrix_world @ pb.head), np.array(arm.matrix_world @ pb.tail)))
        if names is not None:
            names.append(pb.name.replace(P, ""))
    return np.array(segs)


def axis_index(pts, segs):
    """Index of the nearest bone segment for every point."""
    a, b = segs[:, 0], segs[:, 1]
    ab = b - a
    t = np.einsum("pkd,kd->pk", pts[:, None, :] - a[None], ab) / np.maximum((ab * ab).sum(1), 1e-12)
    t = np.clip(t, 0, 1)
    q = a[None] + t[..., None] * ab[None]
    return np.linalg.norm(pts[:, None, :] - q, axis=2).argmin(1)


def axis_points(pts, segs):
    """Nearest point on the skeleton (bone segments) for every point."""
    a, b = segs[:, 0], segs[:, 1]
    ab = b - a
    t = np.einsum("pkd,kd->pk", pts[:, None, :] - a[None], ab) / np.maximum((ab * ab).sum(1), 1e-12)
    t = np.clip(t, 0, 1)
    q = a[None] + t[..., None] * ab[None]
    d = np.linalg.norm(pts[:, None, :] - q, axis=2)
    k = d.argmin(1)
    return q[np.arange(len(pts)), k]


_DOMINANT = {}


def dominant_segments(obj, seg_names):
    """Ruling A144: per vertex of ``obj`` the segment index of its strongest bone weight (-1 without one). The
    nearest bone axis is the wrong ray origin where limbs lie against the torso: with the arms lowered the side of
    the bust is nearer the upper-arm axis than the spine, and the ray from the arm crossed the shirt lying on the
    flank (arms_down "poke" 4.7 %, A142 — a measuring artefact, uneven left / right with the body's own asymmetry)."""
    key = (obj.name, len(obj.data.vertices), tuple(seg_names))
    if key in _DOMINANT:
        return _DOMINANT[key]
    by_name = {n: k for k, n in enumerate(seg_names)}
    gmap = {g.index: by_name.get(g.name.replace(P, ""), -1) for g in obj.vertex_groups}
    out = np.full(len(obj.data.vertices), -1)
    for v in obj.data.vertices:
        best, w = -1, 0.0
        for ge in v.groups:
            k = gmap.get(ge.group, -1)
            if k >= 0 and ge.weight > w:
                best, w = k, ge.weight
        out[v.index] = best
    _DOMINANT[key] = out
    return out


def axis_points_on(pts, segs, idx):
    """Nearest point of segment ``idx[i]`` for every point (the nearest segment where ``idx`` is -1)."""
    q = axis_points(pts, segs)
    ok = idx >= 0
    if ok.any():
        a, b = segs[idx[ok], 0], segs[idx[ok], 1]
        ab = b - a
        t = np.clip(np.einsum("pd,pd->p", pts[ok] - a, ab) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
        q[ok] = a + t[:, None] * ab
    return q


def measure_pose(arm, body, piece, pose, rest_edges_len, edges, rim):
    """Winding-free tests (the generated bodies mix face windings, so no normal is
    trusted): every ray starts on the SKELETON and runs out through the point.
    * a body vertex POKES when the piece is met between its bone (the strongest weight, Ruling A144) and the vertex
      (piece under the skin) and COVERED when it is met within 8 cm beyond it;
      skin within RIM_BAND_M of a piece opening is not judged;
    * a piece vertex is INSIDE when the body surface is met beyond it on that ray."""
    set_pose(arm, pose)
    bco, _bn, _tri = world_coords(body)
    bb = bvh_of(bco, _tri)
    gco, _gn, gtri = world_coords(piece)
    gb = bvh_of(gco, gtri)
    seg_names = []
    segs = bone_segments(arm, seg_names)
    from mathutils.kdtree import KDTree
    kd = KDTree(max(1, len(rim)))
    for j, ri in enumerate(rim):
        kd.insert(Vector(gco[ri]), j)
    kd.balance()
    lo, hi = gco.min(0) - 0.04, gco.max(0) + 0.04
    cand = np.where(np.all((bco > lo) & (bco < hi), axis=1))[0]
    vbone = np.full(len(bco), -1)
    near = np.where(np.all((bco > lo - 0.05) & (bco < hi + 0.05), axis=1))[0]
    for s0 in range(0, len(near), 20000):
        part = near[s0:s0 + 20000]
        vbone[part] = axis_index(bco[part], segs)
    tri_bone = vbone[np.asarray(_tri)[:, 0]]

    def limb_of(k):
        if k < 0:
            return "?"
        n = seg_names[k]
        for side in ("Left", "Right"):
            if n.startswith(side) and any(x in n for x in ("Arm", "Hand", "Shoulder")):
                return side + "Arm"
            if n.startswith(side) and any(x in n for x in ("Leg", "Foot", "Toe")):
                return side + "Leg"
        return "Trunk"
    dom = dominant_segments(body, seg_names)
    ax = axis_points_on(bco[cand], segs, dom[cand]) if len(cand) else np.zeros((0, 3))
    region = poke = contact = 0
    poked = []
    for i, q in zip(cand, ax):
        v = Vector(bco[i])
        if len(rim) and kd.find(v)[2] < RIM_BAND_M:
            continue
        o = Vector(q)
        d = v - o
        L = d.length
        if L < 1e-4:
            continue
        d /= L
        h = gb.ray_cast(o, d, L + 0.08)
        if h[0] is None:
            continue
        # skin pressed against OTHER skin (an arm lowered onto the flank): no room for cloth between them. Only a
        # surface of another limb counts (the same limb's own folds and inner islands are no contact).
        c = bb.ray_cast(v + d * 0.002, d, CONTACT_M)
        if c[0] is not None and limb_of(tri_bone[c[2]]) != limb_of(vbone[i]):
            contact += 1
            continue
        region += 1
        if h[3] < L - 0.0005:
            poke += 1
            poked.append(i)

    def inside(idx):
        if len(idx) == 0:
            return 0.0, 0.0
        q = axis_points(gco[idx], segs)
        depth = []
        for i, qq in zip(idx, q):
            g, o = Vector(gco[i]), Vector(qq)
            d = g - o
            L = d.length
            if L < 1e-4:
                continue
            d /= L
            h = bb.ray_cast(o, d, L + 0.2)
            # the body surface lies BEYOND the piece point on this ray -> point inside
            depth.append(h[3] - L if (h[0] is not None and h[3] > L + 0.002) else 0.0)
        dd = np.array(depth) if depth else np.zeros(1)
        return float((dd > 0).mean()), float(dd.max() * 1000)
    rim_share, rim_mm = inside(np.asarray(rim, int))
    sample = np.arange(0, len(gco), max(1, len(gco) // 4000))
    all_share, all_mm = inside(sample)
    ln = np.linalg.norm(gco[edges[:, 0]] - gco[edges[:, 1]], axis=1)
    ratio = np.where(rest_edges_len < 0.001, 1.0, ln / np.maximum(rest_edges_len, 1e-6))   # Ruling A144: < 1 mm = no fabric
    by_bone = {}
    if poked:
        pk = np.asarray(poked)
        for k in np.where(dom[pk] >= 0, dom[pk], axis_index(bco[pk], segs)):
            by_bone[seg_names[k]] = by_bone.get(seg_names[k], 0) + 1
    return {
        "poke_share": round(poke / max(region, 1), 5), "region_body_verts": int(region),
        "contact_verts": int(contact),
        "poke_bones": dict(sorted(by_bone.items(), key=lambda kv: -kv[1])[:4]),
        "rim_inside_share": round(rim_share, 4), "rim_inside_max_mm": round(rim_mm, 1),
        "piece_inside_share": round(all_share, 4), "piece_inside_max_mm": round(all_mm, 1),
        "stretch_max": round(float(ratio.max()), 3), "stretch_p99": round(float(np.percentile(ratio, 99)), 3),
    }


def measure_all(arm, body, piece, rest_len, edges, rim, render_dir, tag, cam_target):
    out = {}
    for pose in POSES:
        out[pose] = measure_pose(arm, body, piece, pose, rest_len, edges, rim)
        if render_dir:
            render(Path(render_dir) / f"{tag}_{pose}.png", cam_target)
    set_pose(arm, "rest")
    return out


# ---------------------------------------------------------------- render
def render(path, target, side=-0.55):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 12
    sc.render.resolution_x, sc.render.resolution_y = 420, 560
    if "cam" not in bpy.data.objects:
        cd = bpy.data.cameras.new("cam")
        cd.type = "ORTHO"
        cam = bpy.data.objects.new("cam", cd)
        sc.collection.objects.link(cam)
        sc.camera = cam
        ld = bpy.data.lights.new("sun", "SUN")
        ld.energy = 3.0
        sun = bpy.data.objects.new("sun", ld)
        sun.rotation_euler = (math.radians(50), 0, math.radians(30))
        sc.collection.objects.link(sun)
        w = bpy.data.worlds.new("w")
        w.color = (0.8, 0.8, 0.8)
        sc.world = w
    cam = bpy.data.objects["cam"]
    c, size = Vector(target[0]), target[1]
    cam.data.ortho_scale = size
    d = Vector((side, -1.0, 0.25)).normalized()   # front three-quarter (front = -Y); side > 0 = from the left
    cam.location = c + d * 4
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------- cloth
#: A lower garment layer joins the collider as a solid this thick, grown INWARD from its outer surface (a 1.5 mm cloth
#: shell would fall between the 5 mm voxels of the remesh; grown outward or centred it filled the armpit and the
#: jacket above it exploded — A142 first layered run).
EXTRA_SOLID_M = 0.008
#: Wall seconds of each collider build (remesh, decimate, crop, pre-inflate), for the cost record.
COLLIDER_S = []


def _join_extra(col, extra, dg):
    """Join the evaluated mesh of ``extra`` (a lower garment, Ruling A142) into the collider object ``col``,
    thickened to EXTRA_SOLID_M so the voxel remesh keeps it."""
    tmp = bpy.data.objects.new("extra_col", bpy.data.meshes.new_from_object(extra.evaluated_get(dg)))
    tmp.matrix_world = extra.matrix_world.copy()
    bpy.context.scene.collection.objects.link(tmp)
    so = tmp.modifiers.new("so", "SOLIDIFY")
    so.thickness = EXTRA_SOLID_M
    so.offset = -1.0
    bpy.context.view_layer.objects.active = tmp
    bpy.ops.object.modifier_apply(modifier=so.name)
    bm = bmesh.new()
    bm.from_mesh(col.data)
    m = col.matrix_world.inverted() @ tmp.matrix_world
    me2 = tmp.data.copy()
    me2.transform(m)
    bm.from_mesh(me2)
    bm.to_mesh(col.data)
    bm.free()
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(me2)


def _remesh(col, faces):
    vox = col.modifiers.new("vox", "REMESH")
    vox.mode = "VOXEL"
    vox.voxel_size = COLLIDER_VOXEL_M
    bpy.context.view_layer.objects.active = col
    bpy.ops.object.modifier_apply(modifier=vox.name)
    dec = col.modifiers.new("dec", "DECIMATE")
    dec.ratio = min(1.0, faces / max(1, len(col.data.polygons)))
    bpy.context.view_layer.objects.active = col
    bpy.ops.object.modifier_apply(modifier=dec.name)


def skinned_collider(body, arm, faces=80000):
    """Ruling A144: the body remeshed ONCE in the rest pose (closed, wound outward) and skinned like the body, so a
    pose's collider is an armature evaluation instead of a remesh + decimate (~2 s each)."""
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    col = bpy.data.objects.new("collider_rest", bpy.data.meshes.new_from_object(body.evaluated_get(dg)))
    col.matrix_world = body.matrix_world.copy()
    bpy.context.scene.collection.objects.link(col)
    arm.data.pose_position = "POSE"
    _remesh(col, faces)
    bind_to_armature(col, body, arm)
    col.hide_render = True
    return col


def signed_out(tree, p, reach):
    """A178 — the nearest collider point to ``p`` and the unit direction "out" there: from that point towards ``p``
    when ``p`` lies on the outer side of the nearest face, else the face normal. The plain offset . normal read a
    point 33 mm in front of a navel as 8 mm out (the nearest face is the navel's side wall), and the push then moved
    it INTO the navel. Returns ``(None, None)`` when nothing is within ``reach``."""
    loc, nrm, _f, _d = tree.find_nearest(p, reach)
    if loc is None:
        return None, None
    off = p - loc
    if off.dot(nrm) > 0 and off.length > 1e-9:
        return loc, off.normalized()
    return loc, nrm


#: A178: how far out of the collider a built vertex is laid before the drape (above the pre-inflate's
#: thickness + 3 mm, so that one finds nothing left to push).
BUILD_CLEAR_EXTRA_M = 0.004
#: A178: passes of the clearance pass (edge relaxation + projection out of the collider).
BUILD_CLEAR_PASSES = 80
#: A178: how many edge rings round a pushed vertex the relaxation may move (the rest of the piece stays as built).
BUILD_CLEAR_RINGS = 4


def rest_collider(body, extra=(), faces=80000):
    """A179 — the drape's collider in the rest pose, built ONCE per piece: the body (+ the ``extra`` lower layers,
    thickened) voxel-remeshed, so it is closed and wound outward. The bodice builder reads its sections from it, the
    clearance pass projects onto it and ``drape`` collides with it (``collider=``): what is built outside it starts
    outside the collider the cloth meets. Returns ``(object, BVH tree)``; ``drape`` takes the object over."""
    t0 = time.time()
    dg = bpy.context.evaluated_depsgraph_get()
    col = bpy.data.objects.new("collider", bpy.data.meshes.new_from_object(body.evaluated_get(dg)))
    col.matrix_world = body.matrix_world.copy()
    bpy.context.scene.collection.objects.link(col)
    for ex in extra:
        _join_extra(col, ex, dg)
    _remesh(col, faces)
    tree = BVHTree.FromObject(col, bpy.context.evaluated_depsgraph_get())
    COLLIDER_S.append(round(time.time() - t0, 2))
    return col, tree


def signed_depth(tree, pts, reach=0.15):
    """A179 — per point its signed distance to the collider surface (metres; negative = inside the body, ``reach``
    when nothing is that close)."""
    out = np.full(len(pts), float(reach))
    for i, p in enumerate(pts):
        v = Vector(p)
        loc, o = signed_out(tree, v, reach)
        if loc is not None:
            out[i] = float((v - loc).dot(o))
    return out


def clear_of_body(obj, tree, *, thickness):
    """A178 — lay every built vertex outside the drape's collider BEFORE the rest lengths are taken. The pre-inflate in
    ``drape`` pushes each vertex inside the body on its own (23-32 mm at an armhole cut through a high shoulder),
    while its neighbours stay: that alone read as stretch 1.8. Here the vertices are moved like a cloth without
    gravity (position-based): per pass every edge SHORTER than built pushes its ends half-way apart again (Jacobi,
    averaged per vertex; a longer edge is left alone, or the pass would pull the cloth back into the body), then
    every vertex short of ``thickness + BUILD_CLEAR_EXTRA_M`` outside the closed, outward-wound collider (``tree`` of
    ``rest_collider``) is projected out along the surface normal. A push in a crease (the armpit) thus slides the
    neighbours along instead of squeezing the edges between them. Returns
    ``{moved, passes, max_push_mm, inside, left, min_ratio}`` (``inside`` = vertices short before the first pass,
    ``left`` = still short after the last, ``min_ratio`` = the shortest edge over its built length)."""
    t0 = time.time()
    mw = obj.matrix_world
    mwi = mw.inverted()
    co = np.array([tuple(mw @ v.co) for v in obj.data.vertices])
    start = co.copy()
    n = len(co)
    e = edges_of(obj)
    deg = np.bincount(e.ravel(), minlength=n).astype(float)
    built = np.linalg.norm(co[e[:, 1]] - co[e[:, 0]], axis=1)
    target = thickness + BUILD_CLEAR_EXTRA_M

    hit = np.zeros(n, bool)                # every vertex ever projected

    def project():
        short = 0
        for i in range(n):
            p = Vector(co[i])
            loc, out = signed_out(tree, p, 0.1)
            if loc is None:
                continue
            sd = float((p - loc).dot(out))
            if sd < target - 1e-5:
                co[i] = np.array(loc + out * target)
                hit[i] = True
                short += 1
        return short

    passes = 0
    left = first = project()
    while left and passes < BUILD_CLEAR_PASSES:
        passes += 1
        free = hit.copy()                  # the relaxation moves only BUILD_CLEAR_RINGS rings round the pushed ones
        for _ in range(BUILD_CLEAR_RINGS):
            grow = free.copy()
            grow[e[free[e[:, 0]], 1]] = True
            grow[e[free[e[:, 1]], 0]] = True
            free = grow
        d = co[e[:, 1]] - co[e[:, 0]]
        L = np.maximum(np.linalg.norm(d, axis=1), 1e-9)
        corr = d * (np.minimum(L - built, 0.0) / L)[:, None] * 0.5   # only a squeezed edge pushes apart
        acc = np.zeros((n, 3))
        np.add.at(acc, e[:, 0], corr)
        np.add.at(acc, e[:, 1], -corr)
        co += np.where(free[:, None], acc / np.maximum(deg, 1.0)[:, None], 0.0)
        left = project()
    for v, p in zip(obj.data.vertices, co):
        v.co = mwi @ Vector(p)
    obj.data.update()
    push = np.linalg.norm(co - start, axis=1)
    ratio = np.linalg.norm(co[e[:, 1]] - co[e[:, 0]], axis=1) / np.maximum(built, 1e-9)
    return {"moved": int((push > 1e-4).sum()), "passes": passes, "max_push_mm": round(float(push.max()) * 1000, 1),
            "inside": int(first), "left": int(left), "min_ratio": round(float(ratio[built > 1e-3].min()), 3),
            "wall_s": round(time.time() - t0, 2)}


def drape(obj, body, pin_idx, frames, *, quality, bending, shrink, self_collision, thickness, extra=(),
          collider_faces=80000, collision_quality=4, crop_m=None, prebuilt=None, collider=None):
    """Collider = decimated rest copy of the body (+ the ``extra`` lower garment layers). Returns CPU seconds and
    pin drift (mm). ``crop_m`` (Ruling A144): collider faces farther than this outside the cloth's box are dropped
    after the remesh (a jacket never reaches the shins; the collision tests scale with the faces)."""
    sc = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    # the collider must be wound OUTWARD everywhere: Blender's cloth collision is
    # one-sided, and the generated bodies mix windings (13 % of Kira's faces point in
    # even after recalc + parity) - a flipped patch pulls the cloth INTO the body.
    # A voxel remesh of the posed body is closed and wound outward by construction.
    t_col = time.time()
    if collider is not None:
        col = collider                     # A179: ``rest_collider`` of this piece (body + extra), taken over
    elif prebuilt is not None and not extra:
        # Ruling A144: the remeshed rest collider skinned to the armature (``skinned_collider``), evaluated in the pose
        col = bpy.data.objects.new("collider", bpy.data.meshes.new_from_object(prebuilt.evaluated_get(dg)))
        col.matrix_world = prebuilt.matrix_world.copy()
        sc.collection.objects.link(col)
    else:
        col = bpy.data.objects.new("collider", bpy.data.meshes.new_from_object(body.evaluated_get(dg)))
        col.matrix_world = body.matrix_world.copy()
        sc.collection.objects.link(col)
        for ex in extra:
            _join_extra(col, ex, dg)
        _remesh(col, collider_faces)
    if crop_m is not None:
        gco = np.array([obj.matrix_world @ v.co for v in obj.data.vertices])
        lo, hi = gco.min(0) - crop_m, gco.max(0) + crop_m
        cco, _cn, _ct = world_coords(col, evaluated=False)
        near = np.all((cco > lo) & (cco < hi), axis=1)
        bm = bmesh.new()
        bm.from_mesh(col.data)
        far = [f for f in bm.faces if not any(near[v.index] for v in f.verts)]
        bmesh.ops.delete(bm, geom=far, context="FACES")
        bm.to_mesh(col.data)
        bm.free()
    cm = col.modifiers.new("col", "COLLISION")
    col.collision.thickness_outer = thickness
    col.collision.cloth_friction = 5.0
    body.hide_render = body.hide_viewport = False
    vg = obj.vertex_groups.get("pin") or obj.vertex_groups.new(name="pin")
    vg.add([int(i) for i in pin_idx], 1.0, "REPLACE")
    cl = obj.modifiers.new("cloth", "CLOTH")
    s = cl.settings
    s.quality = quality
    s.mass = 0.3
    s.tension_stiffness = s.compression_stiffness = 15
    s.shear_stiffness = 5
    s.bending_stiffness = bending
    s.vertex_group_mass = "pin"
    s.pin_stiffness = 1.0
    s.shrink_min = shrink
    cs = cl.collision_settings
    cs.distance_min = thickness
    cs.use_self_collision = self_collision
    cs.collision_quality = collision_quality
    s.air_damping = 5.0
    cs.self_distance_min = 0.003
    cl.point_cache.frame_start = 1
    cl.point_cache.frame_end = frames
    sc.frame_start, sc.frame_end = 1, frames
    # pre-inflate: nothing may start inside the collider (an initial intersection is
    # what explodes a cloth); push to thickness + 3 mm along the collider normal
    ctree = BVHTree.FromObject(col, bpy.context.evaluated_depsgraph_get())
    mwi = obj.matrix_world.inverted()
    pushed = 0
    pin_set = set(int(i) for i in pin_idx)
    for v in obj.data.vertices:
        w = obj.matrix_world @ v.co
        loc, out = signed_out(ctree, w, 0.05)
        if loc is None:
            continue
        sd = (w - loc).dot(out)
        if sd < thickness + 0.003:
            v.co = mwi @ (loc + out * (thickness + 0.003))
            pushed += 1
    obj.data.update()
    bpy.context.view_layer.update()
    COLLIDER_S.append(round(time.time() - t_col, 2))
    print("DRAPE collider faces", len(col.data.polygons), "cloth verts", len(obj.data.vertices), "col mods", [m.type for m in col.modifiers])
    before = np.array([obj.matrix_world @ obj.data.vertices[int(i)].co for i in pin_idx])
    t0, c0 = time.time(), time.process_time()
    for f in range(1, frames + 1):
        sc.frame_set(f)
        progress(frame=f, frames=frames)
    cpu, wall = time.process_time() - c0, time.time() - t0
    freeze(obj)
    sc.frame_set(1)
    after = np.array([obj.matrix_world @ obj.data.vertices[int(i)].co for i in pin_idx])
    bpy.data.objects.remove(col)
    drift = float(np.linalg.norm(after - before, axis=1).max() * 1000) if len(pin_idx) else 0.0
    drape.last_pushed = pushed
    return round(cpu, 2), round(wall, 2), round(drift, 2)


def pin_ring(co, kind, body_arm):
    """Pin set by kind: waist (top 2.5 cm of the piece), shoulders (top 3 cm within the
    shoulder/collar width), none."""
    if kind == "waist":
        return np.where(co[:, 2] > co[:, 2].max() - 0.025)[0]
    if kind == "shoulders":
        neck_x = body_arm["shoulder_half"]
        top = co[:, 2].max()
        return np.where((co[:, 2] > top - 0.04) & (np.abs(co[:, 0]) < neck_x))[0]
    return np.zeros(0, int)


def bone_head(arm, name):
    return arm.matrix_world @ arm.data.bones[P + name].head_local


# ---------------------------------------------------------------- remesh + bake (mode mesh)
def clean_and_remesh(src, voxel, min_part, body_tree, target_faces=12000):
    bpy.ops.object.select_all(action="DESELECT")
    src.select_set(True)
    bpy.context.view_layer.objects.active = src
    dup = src.copy()
    dup.data = src.data.copy()
    dup.modifiers.clear()
    dup.parent = None
    dup.matrix_world = src.matrix_world.copy()
    bpy.context.scene.collection.objects.link(dup)
    bm = bmesh.new()
    bm.from_mesh(dup.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
    # fragments: islands by area share
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, isl = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            isl.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        islands.append(isl)
    areas = [sum(f.calc_area() for f in isl) for isl in islands]
    tot = sum(areas)
    dropped = [isl for isl, a in zip(islands, areas) if a < min_part * tot]
    for isl in dropped:
        bmesh.ops.delete(bm, geom=isl, context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    boundary_before = sum(1 for e in bm.edges if e.is_boundary)
    bm.to_mesh(dup.data)
    bm.free()
    dup.vertex_groups.clear()
    dup.data.materials.clear()
    for u in list(dup.data.uv_layers):
        dup.data.uv_layers.remove(u)
    bpy.context.view_layer.objects.active = dup
    if voxel > 0:
        rm = dup.modifiers.new("vox", "REMESH")
        rm.mode = "VOXEL"
        rm.voxel_size = voxel
        rm.adaptivity = 0
        bpy.ops.object.modifier_apply(modifier=rm.name)
    else:
        # no voxel pass: orient the generated solid consistently, then split walls
        bm = bmesh.new()
        bm.from_mesh(dup.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(dup.data)
        bm.free()
    # outer wall: the voxel surface of a thick shell is a closed solid wound outward;
    # its INNER wall faces the body. Keep a face when its normal points away from the
    # nearest body point (the generated pieces are solids whose inner wall sits 1-2 cm
    # INSIDE the skin - measured on Kira's blazer: 20 % of the fit's vertices).
    me = dup.data
    mw = dup.matrix_world
    tris = [tuple(p.vertices) for p in me.polygons]
    keep = []
    for p in me.polygons:
        c = mw @ p.center
        n = (mw.to_3x3() @ p.normal).normalized()
        loc, _bn, _f, _d = body_tree.find_nearest(c)
        if (c - loc).normalized().dot(n) > 0.0:
            keep.append(p.index)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    ks = set(keep)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in ks], context="FACES")
    # largest island only (drop loose crumbs the wall split left)
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        stack, isl = [f], []
        seen.add(f)
        while stack:
            g = stack.pop()
            isl.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        islands.append(isl)
    islands.sort(key=len, reverse=True)
    for isl in islands[1:]:
        if len(isl) < 0.02 * len(islands[0]):
            bmesh.ops.delete(bm, geom=isl, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(me)
    bm.free()
    if len(me.polygons) > target_faces:
        dm = dup.modifiers.new("dec", "DECIMATE")
        dm.ratio = target_faces / len(me.polygons)
        bpy.ops.object.modifier_apply(modifier=dm.name)
    me = dup.data
    elen = np.linalg.norm(np.diff(np.array([[me.vertices[i].co for i in e.vertices] for e in me.edges]), axis=1)[:, 0], axis=1)
    return dup, {"fragments_dropped": len(dropped), "islands_before": len(islands) and len(areas),
                 "boundary_edges_before": boundary_before, "voxel_m": voxel,
                 "edge_mean_m": round(float(elen.mean()), 4), "edge_cv": round(float(elen.std() / elen.mean()), 3), "verts": len(me.vertices),
                 "outer_faces_kept_share": round(len(keep) / max(1, len(tris)), 3)}


def bake_from(src, dst, size, out_png):
    """Cycles selected-to-active DIFFUSE COLOR bake of src's material onto dst's new UVs."""
    bpy.context.view_layer.objects.active = dst
    bpy.ops.object.select_all(action="DESELECT")
    dst.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")
    img = bpy.data.images.new("baked", size, size, alpha=True)
    img.generated_color = (1, 0, 1, 0)
    mat = bpy.data.materials.new("baked")
    mat.use_nodes = True
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.nodes.active = tex
    nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    dst.data.materials.clear()
    dst.data.materials.append(mat)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 1
    sc.render.bake.use_selected_to_active = True
    sc.render.bake.cage_extrusion = 0.02
    sc.render.bake.max_ray_distance = 0.05
    sc.render.bake.margin = 0
    sc.render.bake.use_pass_direct = sc.render.bake.use_pass_indirect = False
    sc.render.bake.use_pass_color = True
    src.hide_render = False
    src.select_set(True)
    dst.select_set(True)
    bpy.context.view_layer.objects.active = dst
    t0 = time.process_time()
    bpy.ops.object.bake(type="DIFFUSE")
    cpu = time.process_time() - t0
    px = np.array(img.pixels[:]).reshape(size, size, 4)
    mask = island_mask(dst, size)
    hit = ~((px[..., 0] > 0.99) & (px[..., 1] < 0.01) & (px[..., 2] > 0.99))
    coverage = float((hit & mask).sum() / max(1, mask.sum()))
    # fill misses with the median hit colour (spec: unseen texels = median fabric colour)
    med = np.median(px[hit & mask][:, :3], axis=0) if (hit & mask).any() else np.array([0.5, 0.5, 0.5])
    px[~hit, :3] = med
    px[..., 3] = 1
    img.pixels[:] = px.ravel()
    img.filepath_raw = str(out_png)
    img.file_format = "PNG"
    img.save()
    return img, round(coverage, 4), round(cpu, 2)


def island_mask(obj, size):
    """Texels covered by UV triangles (numpy raster)."""
    me = obj.data
    uv = me.uv_layers.active.data
    mask = np.zeros((size, size), bool)
    me.calc_loop_triangles()
    for t in me.loop_triangles:
        p = np.array([uv[i].uv for i in t.loops]) * size
        x0, y0 = np.floor(p.min(0)).astype(int)
        x1, y1 = np.ceil(p.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        a, b, c = p
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        l3 = 1 - l1 - l2
        ins = (l1 >= -1e-3) & (l2 >= -1e-3) & (l3 >= -1e-3)
        mask[y0:y1 + 1, x0:x1 + 1] |= ins
    return mask


def colour_error(src, dst, dst_img, n=3000):
    """Mean abs RGB error (0..255) between dst's baked texel and src's own texture at the
    nearest src surface point, over n random dst vertices (before the drape)."""
    def tex_of(obj):
        for m in obj.data.materials:
            if m and m.use_nodes:
                for nd in m.node_tree.nodes:
                    if nd.type == "TEX_IMAGE" and nd.image:
                        return nd.image
    simg = tex_of(src)
    if simg is None:
        return None
    sw, sh = simg.size
    spx = np.array(simg.pixels[:]).reshape(sh, sw, simg.channels)
    dw, dh = dst_img.size
    dpx = np.array(dst_img.pixels[:]).reshape(dh, dw, 4)
    sme = src.data
    sme.calc_loop_triangles()
    sco = [src.matrix_world @ v.co for v in sme.vertices]
    tris = [tuple(t.vertices) for t in sme.loop_triangles]
    tree = BVHTree.FromPolygons(sco, tris)
    suv = sme.uv_layers.active.data
    dme = dst.data
    duv = dme.uv_layers.active.data
    vloop = {}
    for lp in dme.loops:
        vloop.setdefault(lp.vertex_index, lp.index)
    rng = np.random.default_rng(1)
    errs = []
    for vi in rng.choice(len(dme.vertices), min(n, len(dme.vertices)), replace=False):
        p = dst.matrix_world @ dme.vertices[int(vi)].co
        loc, _n, fi, _d = tree.find_nearest(p, 0.05)
        if loc is None:
            continue
        t = sme.loop_triangles[fi]
        a, b, c = (sco[i] for i in t.vertices)
        from mathutils.geometry import barycentric_transform
        uvs = [Vector((*suv[i].uv, 0)) for i in t.loops]
        u = barycentric_transform(loc, a, b, c, *uvs)
        s = spx[int(np.clip(u.y * sh, 0, sh - 1)), int(np.clip(u.x * sw, 0, sw - 1)), :3]
        du = duv[vloop[int(vi)]].uv
        d = dpx[int(np.clip(du.y * dh, 0, dh - 1)), int(np.clip(du.x * dw, 0, dw - 1)), :3]
        errs.append(np.abs(s - d).mean())
    return round(float(np.mean(errs) * 255), 2) if errs else None


# ---------------------------------------------------------------- modes
def frame_of(co):
    lo, hi = co.min(0), co.max(0)
    return ((lo + hi) / 2).tolist(), float(max(hi[2] - lo[2], hi[0] - lo[0]) * 1.35 + 0.1)


def export(path, objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(path), use_selection=True, export_skins=True)


def run_mesh(a):
    arm, body, fit = load_fit(a["fit_glb"], a.get("plain_body"))
    out = Path(a["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    fit_edges = edges_of(fit)
    fit_rest, _n, _t = world_coords(fit)
    fit_len = np.linalg.norm(fit_rest[fit_edges[:, 0]] - fit_rest[fit_edges[:, 1]], axis=1)
    view = frame_of(fit_rest)
    tag = a["tag"]
    baseline = measure_all(arm, body, fit, fit_len, fit_edges, boundary_verts(fit),
                           out if a.get("render") else None, f"{tag}_fit", view)
    # remesh from the REST-state fitted surface
    set_pose(arm, "rest")
    fit_frozen = fit.copy()
    fit_frozen.data = bpy.data.meshes.new_from_object(fit.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    fit_frozen.modifiers.clear()
    fit_frozen.parent = None
    fit_frozen.matrix_world = Matrix.Identity(4)
    bpy.context.scene.collection.objects.link(fit_frozen)
    fit.hide_render = True
    t0 = time.process_time()
    _bc, _bn, btree = body_state(body)
    cloth, rinfo = clean_and_remesh(fit_frozen, a.get("voxel_m", 0.006), a.get("min_part_share", 0.02), btree,
                                    a.get("target_faces", 12000))
    rinfo["cpu_s"] = round(time.process_time() - t0, 2)
    img, coverage, bake_cpu = bake_from(fit_frozen, cloth, a.get("tex_size", 1024), out / f"{tag}_atlas.png")
    try:
        cerr = colour_error(fit_frozen, cloth, img)
    except Exception as e:                           # noqa: BLE001 - a metric, not the product
        cerr = f"n/a ({type(e).__name__})"
    fit_frozen.hide_render = True
    co0 = np.array([v.co for v in cloth.data.vertices])
    edges = edges_of(cloth)
    rest_len = np.linalg.norm(co0[edges[:, 0]] - co0[edges[:, 1]], axis=1)
    shoulder = abs(bone_head(arm, "LeftArm").x) * a.get("pin_width", 0.75)
    pin = pin_ring(co0, a["pin"], {"shoulder_half": shoulder})
    cpu, wall, drift = drape(cloth, body, pin, a.get("frames", 40), quality=a.get("quality", 6),
                             bending=a.get("bending", 0.5), shrink=a.get("shrink", 0.0),
                             self_collision=a.get("self_collision", False), thickness=a.get("thickness", 0.004))
    rinfo["pre_inflated_verts"] = drape.last_pushed
    co1 = np.array([v.co for v in cloth.data.vertices])
    drape_len = np.linalg.norm(co1[edges[:, 0]] - co1[edges[:, 1]], axis=1) / np.maximum(rest_len, 1e-6)
    bind_to_armature(cloth, body, arm)
    draped = measure_all(arm, body, cloth, rest_len, edges, boundary_verts(cloth),
                         out if a.get("render") else None, f"{tag}_drape", view)
    export(out / f"{tag}_drape.glb", [arm, cloth])
    return {"tag": tag, "remesh": rinfo, "bake": {"coverage": coverage, "cpu_s": bake_cpu, "colour_err_255": cerr},
            "drape": {"cpu_s": cpu, "wall_s": wall, "pin_drift_mm": drift, "pins": int(len(pin)),
                      "stretch_max": round(float(drape_len.max()), 3),
                      "stretch_p99": round(float(np.percentile(drape_len, 99)), 3)},
            "fit_baseline": baseline, "draped": draped}, {"glb": str(out / f"{tag}_drape.glb")}


def body_radius(tree, centre, ang, z):
    d = Vector((math.cos(ang), math.sin(ang), 0))
    o = Vector((centre[0], centre[1], z)) + d * 0.6
    hit = tree.ray_cast(o, -d, 0.6)
    return (0.6 - hit[3]) if hit[0] is not None else 0.0


def run_panels(a):
    import json
    arm, body, _g = load_fit(a["fit_glb"], a.get("plain_body"))
    out = Path(a["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads(Path(a["panels_json"]).read_text())
    bco, _bn, btri = world_coords(body)
    btree = bvh_of(bco, btri)
    zw = a["waist_z"]
    sl = bco[np.abs(bco[:, 2] - zw) < 0.01]
    centre = sl[:, :2].mean(0)
    rows, cols = spec["rows"], spec["cols"]
    verts, faces, uvs = [], [], []
    # front panel spans 180..360 deg through -Y (front), back 0..180 through +Y
    spans = {"front": (math.pi, 2 * math.pi), "back": (0.0, math.pi)}
    W = sum(p["waist_len_m"] for p in spec["panels"])
    for pi_, p in enumerate(spec["panels"]):
        g = np.array(p["grid_m"])                 # rows x cols x 2 (pattern plane)
        a0, a1 = spans[p["name"]]
        for r in range(rows):
            row = g[r]
            width = np.sum(np.linalg.norm(np.diff(row, axis=0), axis=1))
            circ = 2 * width
            z = zw - (r / (rows - 1)) * a["length_m"]
            for c in range(cols):
                ang = a0 + (a1 - a0) * c / (cols - 1)
                rad = circ / (2 * math.pi)
                rad = max(rad, body_radius(btree, centre, ang, z) + (0.006 if r == 0 else 0.02))
                verts.append((centre[0] + rad * math.cos(ang), centre[1] + rad * math.sin(ang), z))
                uvs.append(((row[c, 0] - g[..., 0].min()) / 2.2 + 0.5 * pi_, row[c, 1] / 1.2 + 0.2))
        base = pi_ * rows * cols
        for r in range(rows - 1):
            for c in range(cols - 1):
                i = base + r * cols + c
                faces.append((i, i + 1, i + cols + 1, i + cols))
    me = bpy.data.meshes.new("skirt")
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name="UVMap")
    for lp in me.loops:
        uvl.data[lp.index].uv = uvs[lp.vertex_index]
    obj = bpy.data.objects.new("garment_template_skirt", me)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.004)   # sew the two side seams
    bm.to_mesh(me)
    bm.free()
    co0 = np.array([v.co for v in me.vertices])
    edges = edges_of(obj)
    rest_len = np.linalg.norm(co0[edges[:, 0]] - co0[edges[:, 1]], axis=1)
    pin = np.where(co0[:, 2] > zw - 0.004)[0]
    cpu, wall, drift = drape(obj, body, pin, a.get("frames", 50), quality=a.get("quality", 6),
                             bending=a.get("bending", 0.3), shrink=a.get("shrink", 0.0),
                             self_collision=False, thickness=a.get("thickness", 0.004))
    me = obj.data                               # freeze() replaced the mesh datablock
    co1 = np.array([v.co for v in me.vertices])
    st = np.linalg.norm(co1[edges[:, 0]] - co1[edges[:, 1]], axis=1) / np.maximum(rest_len, 1e-6)
    sol = obj.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.0015
    sol.offset = 1
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=sol.name)
    tex = project_bake(obj, a, out / "skirt_template_atlas.png")
    edges2 = edges_of(obj)
    co2 = np.array([v.co for v in obj.data.vertices])
    rest2 = np.linalg.norm(co2[edges2[:, 0]] - co2[edges2[:, 1]], axis=1)
    rim = boundary_verts(obj)
    bind_to_armature(obj, body, arm)
    view = frame_of(co2)
    m = measure_all(arm, body, obj, rest2, edges2, rim, out if a.get("render") else None, "skirt_template", view)
    export(out / "skirt_template.glb", [arm, obj])
    return {"tag": "skirt_template", "verts": len(me.vertices),
            "drape": {"cpu_s": cpu, "wall_s": wall, "pin_drift_mm": drift, "pins": int(len(pin)),
                      "stretch_max": round(float(st.max()), 3), "stretch_p99": round(float(np.percentile(st, 99)), 3)},
            "bake": tex, "draped": m}, {"glb": str(out / "skirt_template.glb")}


def project_bake(obj, a, out_png, size=1024, co=None, nr=None):
    """Projection bake of the front/back cut-out views onto obj's UVs (orthographic,
    registered by bounding box: the piece's projected bbox = the view's alpha bbox). ``co`` / ``nr`` = world
    positions / normals to project from instead of the rest mesh (Ruling A142: a top is projected in the arm pose
    its picture shows)."""
    me = obj.data
    me.calc_loop_triangles()
    if co is None:
        co = np.array([obj.matrix_world @ v.co for v in me.vertices])
    if nr is None:
        nr = np.array([(obj.matrix_world.to_3x3() @ v.normal).normalized() for v in me.vertices])
    views = {}
    for side in ("front", "back"):
        im = bpy.data.images.load(a[f"view_{side}"])
        w, h = im.size
        px = np.array(im.pixels[:]).reshape(h, w, im.channels)
        alpha = px[..., 3] if im.channels == 4 else np.ones((h, w))
        ys, xs = np.where(alpha > 0.5)
        views[side] = (px, alpha, (xs.min(), xs.max(), ys.min(), ys.max()), w, h)
    lo, hi = co.min(0), co.max(0)
    img = np.zeros((size, size, 4))
    valid = np.zeros((size, size), bool)
    mask = np.zeros((size, size), bool)
    uv = me.uv_layers.active.data
    for t in me.loop_triangles:
        p = np.array([uv[i].uv for i in t.loops]) * size
        P3 = co[list(t.vertices)]
        N3 = nr[list(t.vertices)].mean(0)
        x0, y0 = np.maximum(np.floor(p.min(0)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(p.max(0)).astype(int), size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        A, B, C = p
        d = (B[1] - C[1]) * (A[0] - C[0]) + (C[0] - B[0]) * (A[1] - C[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((B[1] - C[1]) * (xs - C[0]) + (C[0] - B[0]) * (ys - C[1])) / d
        l2 = ((C[1] - A[1]) * (xs - C[0]) + (A[0] - C[0]) * (ys - C[1])) / d
        l3 = 1 - l1 - l2
        ins = (l1 >= -1e-3) & (l2 >= -1e-3) & (l3 >= -1e-3)
        if not ins.any():
            continue
        pos = l1[ins, None] * P3[0] + l2[ins, None] * P3[1] + l3[ins, None] * P3[2]
        side = "front" if N3[1] <= 0 else "back"
        vpx, valpha, (bx0, bx1, by0, by1), w, h = views[side]
        # front (camera on -Y): image right = +X ; back: image right = -X ; row 0 = bottom
        fx = (pos[:, 0] - lo[0]) / (hi[0] - lo[0]) if side == "front" else (hi[0] - pos[:, 0]) / (hi[0] - lo[0])
        fz = (pos[:, 2] - lo[2]) / (hi[2] - lo[2])
        ix = np.clip((bx0 + fx * (bx1 - bx0)).astype(int), 0, w - 1)
        iy = np.clip((by0 + fz * (by1 - by0)).astype(int), 0, h - 1)
        ty, tx = ys[ins].astype(int), xs[ins].astype(int)
        mask[ty, tx] = True
        ok = valpha[iy, ix] > 0.5
        img[ty[ok], tx[ok], :3] = vpx[iy[ok], ix[ok], :3]
        valid[ty[ok], tx[ok]] = True
    coverage = float((valid & mask).sum() / max(1, mask.sum()))
    med = np.median(img[valid][:, :3], axis=0) if valid.any() else np.array([.5, .5, .5])
    img[~valid, :3] = med
    img[..., 3] = 1
    bi = bpy.data.images.new("template_tex", size, size, alpha=True)
    bi.pixels[:] = img.ravel()
    bi.filepath_raw = str(out_png)
    bi.file_format = "PNG"
    bi.save()
    mat = bpy.data.materials.new("template")
    mat.use_nodes = True
    tn = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tn.image = bi
    mat.node_tree.links.new(tn.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    me.materials.clear()
    me.materials.append(mat)
    return {"coverage": round(coverage, 4), "method": "orthographic projection, bbox-registered"}


def run_from_body(a):
    arm, body, _g = load_fit(a["fit_glb"], a.get("plain_body"))
    out = Path(a["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.process_time()
    me = body.data
    gi = {g.name: g.index for g in body.vertex_groups}
    region_bones = [gi[P + b] for b in a.get("bones", ["Hips", "LeftUpLeg", "RightUpLeg"]) if P + b in gi]
    co = np.array([v.co for v in me.vertices])          # body object is unscaled at identity in these files
    co = co @ np.array(body.matrix_world)[:3, :3].T + np.array(body.matrix_world)[:3, 3]
    w = np.zeros(len(co))
    for v in me.vertices:
        for g in v.groups:
            if g.group in region_bones:
                w[v.index] += g.weight
    top, crotch, rise = a["top_z"], a["crotch_z"], a.get("leg_rise", 0.5)
    ax = np.abs(co[:, 0] - a.get("centre_x", 0.0))
    keep = (w > 0.5) & (co[:, 2] <= top) & (co[:, 2] >= crotch + rise * np.maximum(0, ax - 0.03))
    keep_idx = set(np.where(keep)[0].tolist())
    _c, fixed_n, _t = body_state(body)      # rest pose; same vertex order as the mesh
    sl = body.copy()
    sl.data = body.data.copy()
    sl.name = "garment_from_body_slip"
    sl.modifiers.clear()
    bpy.context.scene.collection.objects.link(sl)
    bm = bmesh.new()
    bm.from_mesh(sl.data)
    src = bm.verts.layers.int.new("src")
    for v in bm.verts:
        v[src] = v.index
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not all(v.index in keep_idx for v in f.verts)], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    # offset along the parity-checked body normals (the raw ones point inward on a
    # whole island of this body: measured 34 % poke-through with them)
    for v in bm.verts:
        v.co += Vector(fixed_n[v[src]]) * a.get("offset_m", 0.003)
    bm.to_mesh(sl.data)
    bm.free()
    sol = sl.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.0015
    sol.offset = 1
    bpy.context.view_layer.objects.active = sl
    bpy.ops.object.modifier_apply(modifier=sol.name)
    cpu = round(time.process_time() - t0, 2)
    mat = bpy.data.materials.new("slip")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = a.get("colour", (0.05, 0.05, 0.06, 1))
    sl.data.materials.clear()
    sl.data.materials.append(mat)
    for m in sl.modifiers:
        pass
    am = sl.modifiers.new("arm", "ARMATURE")
    am.object = arm
    sl.parent = arm
    edges = edges_of(sl)
    c0 = np.array([v.co for v in sl.data.vertices])
    rest = np.linalg.norm(c0[edges[:, 0]] - c0[edges[:, 1]], axis=1)
    view = frame_of(c0)
    view = (view[0], max(view[1], 0.9))
    m = measure_all(arm, body, sl, rest, edges, boundary_verts(sl), out if a.get("render") else None, "slip", view)
    export(out / "slip_from_body.glb", [arm, sl])
    return {"tag": "slip", "cpu_s": cpu, "verts": len(sl.data.vertices), "uv_inherited": bool(sl.data.uv_layers),
            "groups_inherited": len(sl.vertex_groups), "draped": m}, {"glb": str(out / "slip_from_body.glb")}


def run_necklace(a):
    arm, body, g = load_fit(a["fit_glb"], a.get("plain_body"))
    if g is not None:
        bpy.data.objects.remove(g)
    out = Path(a["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    bco, bn, btri = world_coords(body)
    btree = bvh_of(bco, btri)
    neck = bone_head(arm, "Neck")
    s2 = bone_head(arm, "Spine2")
    zc = neck.z + a.get("start_above_neck_m", 0.05)   # mid-neck: narrower than the ring
    sl = bco[np.abs(bco[:, 2] - zc) < 0.006]
    sl = sl[np.linalg.norm(sl[:, :2] - np.array([neck.x, neck.y]), axis=1) < 0.12]
    cx, cy = sl[:, 0].mean(), sl[:, 1].mean()
    L = a.get("length_m", 0.50)
    n = a.get("links", 96)
    r = L / (2 * math.pi)
    z0 = zc
    # a 3 mm ribbon, not a bare edge loop: Blender cloth collides by triangles, so an
    # edge-only string falls straight through the collider (measured: drop 8.9 m)
    verts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z0) for i in range(n)]
    verts += [(x, y, z - 0.003) for x, y, z in verts]
    edges = []
    rib = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    # pendant: small disc hung below the front-most link (heavier: many vertices)
    front = min(range(n), key=lambda i: verts[i][1])
    px, py, pz = verts[front]
    pr = a.get("pendant_r", 0.012)
    pc = len(verts)
    ring = 16
    verts.append((px, py - 0.004, pz - pr))
    for k in range(ring):
        t = 2 * math.pi * k / ring
        verts.append((px + pr * math.cos(t), py - 0.004, pz - pr + pr * math.sin(t)))
    faces = rib + [(pc, pc + 1 + k, pc + 1 + (k + 1) % ring) for k in range(ring)]
    edges.append((n + front, pc + 1 + ring // 4))
    me = bpy.data.meshes.new("chain")
    me.from_pydata(verts, edges, faces)
    obj = bpy.data.objects.new("necklace_chain", me)
    bpy.context.scene.collection.objects.link(obj)
    chain_idx = np.arange(n)
    cpu, wall, drift = drape(obj, body, np.zeros(0, int), a.get("frames", 60), quality=10, bending=0.05,
                             shrink=0.0, self_collision=False, thickness=0.004)
    co = np.array([v.co for v in obj.data.vertices])
    ch = co[chain_idx]
    seg = np.linalg.norm(ch - np.roll(ch, -1, 0), axis=1)
    rest_seg = L / n

    segs = bone_segments(arm)

    def contact(pts):
        """Share of points within 5 mm of the skin, and points inside (skeleton rays)."""
        q = axis_points(np.asarray(pts), segs)
        near, ins = [], 0
        for p, qq in zip(pts, q):
            g, o = Vector(p), Vector(qq)
            d = g - o
            L = d.length
            d /= max(L, 1e-6)
            h = btree.ray_cast(o, d, L + 0.2)
            if h[0] is None:
                near.append(1.0)
                continue
            near.append(abs(h[3] - L))
            ins += h[3] > L + 0.001
        return float((np.array(near) < 0.005).mean()), int(ins)
    notch_z = s2.z + (neck.z - s2.z) * 0.6
    c_share, c_in = contact(ch)
    pend = co[pc:]
    p_share, p_in = contact(pend)
    # procedural reference: surface curve at the same drop (spec option C)
    drop = notch_z - ch[:, 2].min()
    proc = procedural_curve(btree, bco, cx, cy, neck.z, ch[:, 2].min(), n)
    pc_share, pc_in = contact(proc)
    res = {"tag": "necklace", "chain_z": [round(float(ch[:, 2].min()), 3), round(float(ch[:, 2].max()), 3)], "neck_z": round(neck.z, 3), "drape": {"cpu_s": cpu, "wall_s": wall},
           "chain": {"length_m": L, "links": n, "drop_cm": round(drop * 100, 1),
                     "contact_share_5mm": round(c_share, 3), "inside_links": c_in,
                     "segment_stretch_max": round(float(seg.max() / rest_seg), 3)},
           "pendant": {"contact_share_5mm": round(p_share, 3), "inside_verts": p_in,
                       "lowest_z": round(float(pend[:, 2].min()), 3)},
           "procedural": {"contact_share_5mm": round(pc_share, 3), "inside_points": pc_in}}
    sk = obj.modifiers.new("sk", "SKIN") if False else None
    tube = curve_tube(ch, "necklace_tube", 0.0012)
    bpy.data.objects.remove(obj)
    mat = bpy.data.materials.new("gold")
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.9, 0.7, 0.2, 1)
    b.inputs["Metallic"].default_value = 1
    tube.data.materials.append(mat)
    pm = bpy.data.meshes.new("pendant")
    pm.from_pydata(pend.tolist(), [], [(0, 1 + k, 1 + (k + 1) % ring) for k in range(ring)])
    po = bpy.data.objects.new("pendant", pm)
    bpy.context.scene.collection.objects.link(po)
    so = po.modifiers.new("s", "SOLIDIFY")
    so.thickness = 0.003
    po.data.materials.append(mat)
    proc_tube = curve_tube(proc, "procedural_tube", 0.0012)
    pmat = bpy.data.materials.new("silver")
    pmat.use_nodes = True
    pmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.2, 0.4, 1.0, 1)
    proc_tube.data.materials.append(pmat)
    view = (((neck.x), neck.y, notch_z - 0.08), 0.45)
    if a.get("render"):
        render(out / "necklace_rest.png", view)
    return res, {}


def procedural_curve(btree, bco, cx, cy, ztop, zlow, n):
    """Option C reference: per angle, the body surface at a height that falls from ztop
    at the back to zlow at the front (cosine), offset 1.5 mm outward."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        f = (1 - math.sin(t)) / 2                       # 0 back (+Y) .. 1 front (-Y)
        z = ztop - (ztop - zlow) * f ** 1.5
        d = Vector((math.cos(t), math.sin(t), 0))
        o = Vector((cx, cy, z)) + d * 0.4
        hit = btree.ray_cast(o, -d, 0.4)
        p = hit[0] + hit[1] * 0.0015 if hit[0] is not None else Vector((cx, cy, z)) + d * 0.06
        pts.append(tuple(p))
    return np.array(pts)


def curve_tube(pts, name, radius):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        sp.points[i].co = (*p, 1)
    sp.use_cyclic_u = True
    cu.bevel_depth = radius
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _plain(x):
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    return x


def run(a):
    data, outputs = {"mesh": run_mesh, "panels": run_panels, "from_body": run_from_body,
            "necklace": run_necklace}[a["mode"]](a)
    return _plain(data), outputs


if __name__ == "__main__":
    main(run)
