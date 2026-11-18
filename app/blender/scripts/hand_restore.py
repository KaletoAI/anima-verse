"""Puts the fingers of a rigged humanoid back where the mesher had them (step ``hands``).

    inputs.model    the rigged, normalised GLB (the step runs right after normalize)
    inputs.source   the UNRIGGED mesh the rigger was given (``unrigged/<signature>.glb``)

The method and the per-hand gate live in ``_hand_restore.py`` (numpy only); this script reads the scene into
arrays, counts self-intersections with a BVH for the gate, writes the accepted hands back and moves the finger
joints. Only the finger joints' POSITIONS change: every edit bone keeps its rotation (``EditBone.matrix`` is
set with the old rotation and the new head), so each joint's local rest rotation — what the clients' rest
correction and ``refine.apply_script``'s frame gate compare — stays as it was. Weights are not touched.

No hand accepted (none moved by the rigger, a refused gate, no finger bones, no source): no output, the model
stays byte-identical. ``data`` reports per side ``status`` (applied | refused | untouched | skipped | error),
the reason, the displacement the rigger had added and what is left, and the gate numbers before/after.
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
_common.app_root_on_path()
import _hand_restore                                          # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
import numpy as np                                            # noqa: E402
from mathutils import Vector                                  # noqa: E402
from mathutils.bvhtree import BVHTree                         # noqa: E402

from app.core.head_twist import bone_name                     # noqa: E402

WELD = 1e-6   # positions closer than this are one vertex for the adjacency test of the intersection count


def _arrays(objects):
    """World positions, UVs (first layer, per vertex) and triangles of ``objects``, concatenated."""
    pos, uvs, tris, spans = [], [], [], []
    offset = 0
    for obj in objects:
        me = obj.data
        n = len(me.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        mw = np.array(obj.matrix_world, dtype=np.float64)
        pos.append(co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3])
        uv = np.full((n, 2), np.nan)
        if me.uv_layers:
            lv = np.empty(len(me.loops), dtype=np.int64)
            me.loops.foreach_get("vertex_index", lv)
            luv = np.empty(len(me.loops) * 2)
            me.uv_layers[0].data.foreach_get("uv", luv)
            uv[lv] = luv.reshape(-1, 2)
        uvs.append(uv)
        me.calc_loop_triangles()
        t = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
        me.loop_triangles.foreach_get("vertices", t)
        tris.append(t.reshape(-1, 3) + offset)
        spans.append((obj, offset, n))
        offset += n
    if not pos:
        return np.zeros((0, 3)), np.zeros((0, 2)), np.zeros((0, 3), dtype=np.int64), []
    return np.concatenate(pos), np.concatenate(uvs), np.concatenate(tris), spans


def _weights(spans, total):
    """Normalised group name -> per-vertex weight (hand and finger groups only), and each vertex's total."""
    wanted = {f"{s}hand" for s in ("left", "right")} | {
        f"{s}hand{f.lower()}{k}" for s in ("left", "right") for f in _hand_restore.FINGERS for k in (1, 2, 3)}
    out = {}
    wtot = np.zeros(total)
    for obj, offset, _ in spans:
        names = {g.index: bone_name(g.name) for g in obj.vertex_groups}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight <= 0:
                    continue
                wtot[offset + v.index] += g.weight
                key = names.get(g.group)
                if key in wanted:
                    out.setdefault(key, np.zeros(total))[offset + v.index] += g.weight
    return out, wtot


def _intersections_counter(tris):
    def count(rows, before, after):
        inside = np.zeros(len(before), bool)
        inside[rows] = True
        t = tris[inside[tris].all(1)]
        key = np.round(before / WELD).astype(np.int64)
        _, ident = np.unique(key, axis=0, return_inverse=True)
        ident = ident.ravel()
        out = []
        for pos in (before, after):
            tree = BVHTree.FromPolygons([Vector(p) for p in pos], [tuple(int(i) for i in tri) for tri in t],
                                        all_triangles=True)
            n = 0
            for a, b in tree.overlap(tree):
                if a >= b:
                    continue
                if set(ident[t[a]].tolist()) & set(ident[t[b]].tolist()):
                    continue            # neighbours (a shared corner, or a seam copy of one) touch by design
                n += 1
            out.append(n)
        return out[0], out[1]
    return count


def hand_restore(args):
    src = args["inputs"].get("model")
    source = args["inputs"].get("source")
    if not src:
        raise ValueError("no input 'model'")
    report = {"Left": {}, "Right": {}, "error": ""}
    if not source:
        report["error"] = "no unrigged source"
        return report, {}
    _common.reset_scene()
    _common.import_model(src)
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        report["error"] = "needs exactly one armature"
        return report, {}
    arm = arms[0]
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"
              and any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]
    if not meshes:
        report["error"] = "no skinned mesh"
        return report, {}
    if any(o.data.shape_keys for o in meshes):
        report["error"] = "shape keys present; hands left as is"
        return report, {}
    verts, uv, tris, spans = _arrays(meshes)
    weights, wtot = _weights(spans, len(verts))
    heads = {bone_name(b.name): np.array(arm.matrix_world @ b.head_local, dtype=np.float64)
             for b in arm.data.bones}

    # The source mesh: imported, read, removed again (normalize._restore_posture does the same).
    _common.progress("hand_source")
    before_names = {o.name for o in bpy.data.objects}
    _common.import_model(source)
    new_objects = [o for o in bpy.data.objects if o.name not in before_names]
    src_verts, src_uv, _, _ = _arrays([o for o in new_objects if o.type == "MESH"])
    for obj in new_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.view_layer.update()
    if len(src_verts) < 100:
        report["error"] = "source holds no mesh"
        return report, {}

    _common.progress("hand_fit")
    new, new_heads, sides = _hand_restore.restore(verts, tris, uv, weights, wtot, heads, src_verts, src_uv,
                                                  intersections=_intersections_counter(tris))
    report.update(sides)
    if new is None:
        return report, {}

    for obj, offset, n in spans:
        inv = np.array(obj.matrix_world.inverted(), dtype=np.float64)
        local = new[offset:offset + n] @ inv[:3, :3].T + inv[:3, 3]
        obj.data.vertices.foreach_set("co", local.astype(np.float64).ravel())
        obj.data.update()

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    to_arm = arm.matrix_world.inverted()
    by_key = {bone_name(eb.name): eb for eb in arm.data.edit_bones}
    for key in new_heads:
        if key in by_key:
            by_key[key].use_connect = False   # a connected child would snap its head to the moved tail
    for key, head in new_heads.items():
        eb = by_key.get(key)
        if eb is None:
            continue
        matrix = eb.matrix.copy()                 # rotation kept, only the head moves
        matrix.translation = to_arm @ Vector(head.tolist())
        eb.matrix = matrix
    bpy.ops.object.mode_set(mode="OBJECT")

    path = Path(args["out_dir"]) / Path(src).name
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")
    return report, {"model": str(path)}


_common.main(hand_restore)
