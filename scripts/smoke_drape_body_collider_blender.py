"""Blender half of the drape body-collider check (plan anatomy, task 8): runs INSIDE Blender, on COPIES of base GLBs.

Usage: blender -b --factory-startup --python scripts/smoke_drape_body_collider_blender.py -- <chain.glb> <tip.glb> <out.json>
       (``scripts/smoke_drape_body_collider.py --blender <chain.glb> <tip.glb>`` runs it and judges the numbers)

<chain.glb> a base model with an attached part node (extras ``attached_part``) of group ``genital_chain`` whose
companion sack bone is ``mixamorig:GenitalSack``; <tip.glb> a base model with the tip bone ``mixamorig:LeftBreastTip``.
Writes the raw measurements; the judging (hand-derived bounds) is in the caller.
"""
import json
import sys
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "blender" / "scripts"))
import garment_template_drape as gd  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
chain_glb, tip_glb, out_path = argv[:3]
out = {}

# B1 import
arm, body, _g, parts = gd.load_fit(chain_glb, keep_parts=["genital_chain"])
out["b1_parts"] = len(parts)
if parts:
    part = parts[0]
    out["b1_prop"] = str(part.get("attached_part") or "")
    out["b1_faces"] = len(part.data.polygons)
    out["b1_verts"] = len(part.data.vertices)
    bm = bmesh.new()
    bm.from_mesh(part.data)
    # the glTF import splits vertices along UV / normal seams: weld them first (1e-6 m), else every seam is a rim
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    edges = [e for e in bm.edges if e.is_boundary]
    seen, loops, sizes = set(), 0, []
    adj = {}
    for e in edges:
        for v in e.verts:
            adj.setdefault(v.index, []).append(e)
    for e in edges:
        if e.index in seen:
            continue
        loops += 1
        sizes.append(0)
        stack = [e]
        while stack:
            cur = stack.pop()
            if cur.index in seen:
                continue
            seen.add(cur.index)
            sizes[-1] += 1
            for v in cur.verts:
                stack += [n for n in adj[v.index] if n.index not in seen]
    bm.free()
    out["b1_boundary_loops"] = loops
    out["b1_loop_edges"] = sorted(sizes, reverse=True)
    sack = part.vertex_groups.get("mixamorig:GenitalSack")
    heavy = 0
    if sack is not None:
        for v in part.data.vertices:
            total = sum(g.weight for g in v.groups) or 1.0
            w = next((g.weight for g in v.groups if g.group == sack.index), 0.0)
            heavy += (w / total) > 0.5
    out["b1_sack_verts"] = int(heavy)

    # B2 / B3: collider with the part (inflate 3 mm) vs without keep
    t0 = time.time()
    dg = bpy.context.evaluated_depsgraph_get()
    pco = np.array([tuple(part.matrix_world @ v.co) for v in part.evaluated_get(dg).to_mesh().vertices])
    part.evaluated_get(dg).to_mesh_clear()
    col, tree = gd.rest_collider(body, body_parts=[(part, 0.003)], spheres=[])
    out["b2_collider_s"] = round(time.time() - t0, 2)
    depth = np.asarray(gd.signed_depth(tree, [Vector(p) for p in pco]), float)
    # only the part's VISIBLE surface counts: a vertex whose ray along its own normal leaves into the open (no part
    # or body face within 3 cm) — the part's inner wall and the root inside the body are no cloth contact
    me = part.evaluated_get(dg).to_mesh()
    pn = np.array([tuple((part.matrix_world.to_3x3() @ v.normal).normalized()) for v in me.vertices])
    part.evaluated_get(dg).to_mesh_clear()
    bco, _bn, btri = gd.world_coords(body)
    qco, _qn, qtri = gd.world_coords(part)
    allco = np.vstack([bco, qco])
    alltri = [tuple(t) for t in btri] + [tuple(np.asarray(t) + len(bco)) for t in qtri]
    atree = gd.bvh_of(allco, alltri)
    visible = np.array([atree.ray_cast(Vector(p) + Vector(n) * 0.0005, Vector(n), 0.03)[0] is None
                        for p, n in zip(pco, pn)], bool)
    out["b2_visible_verts"] = int(visible.sum())
    out["b2_all_depth_max_mm"] = round(float(depth.max()) * 1000, 2)
    out["b2_all_over_1mm"] = int((depth > 0.001).sum())
    depth = depth[visible]
    out["b2_visible_over_1mm"] = int((depth > 0.001).sum())
    out["b2_depth_max_mm"] = round(float(depth.max()) * 1000, 2)
    out["b2_dist_p95_mm"] = round(float(np.percentile(np.abs(depth), 95)) * 1000, 2)
    out["b3_kept"] = list(gd.BODY_COLLIDER_KEPT)

    def region_faces(keep):
        """Faces near the part (centre within the margin of the joined part) before / after ``drop_outer_shells``."""
        c = bpy.data.objects.new("c", bpy.data.meshes.new_from_object(body.evaluated_get(dg)))
        c.matrix_world = body.matrix_world.copy()
        bpy.context.scene.collection.objects.link(c)
        kt = gd._join_body_collider(c, [(part, 0.003)], [], dg, arm)
        gd._remesh(c, 80000, gd.core_segments(arm))
        margin = gd._body_collider_margin([(part, 0.003)], [])

        def count():
            _co, _p, cen, _n = gd._mesh_arrays(c)
            return sum(kt.find_nearest(Vector(x), margin)[0] is not None for x in cen)
        before = count()
        gd.drop_outer_shells(c, body, layered=False, keep=(kt, margin) if keep else None)
        after = count()
        bpy.data.objects.remove(c)
        return before, after
    out["b3_with_keep"] = region_faces(True)
    out["b3_without_keep"] = region_faces(False)

# B4 tips (sphere r 4.5 mm + inflate 2 mm)
arm, body, _g, _p = gd.load_fit(tip_glb)
pb = arm.pose.bones.get("mixamorig:LeftBreastTip")
out["b4_bone"] = pb is not None
if pb is not None:
    head = arm.matrix_world @ pb.head
    d = (arm.matrix_world @ pb.tail - head).normalized()

    def reach(spheres):
        col, tree = gd.rest_collider(body, body_parts=[], spheres=spheres)
        hit = tree.ray_cast(head + d * 0.05, -d, 0.1)
        bpy.data.objects.remove(col)
        return None if hit[0] is None else round(float((hit[0] - head).dot(d)) * 1000, 2)
    def tip_region(keep):
        sp = [{"bone": "mixamorig:LeftBreastTip", "radius": 0.0045, "inflate": 0.002}]
        dg = bpy.context.evaluated_depsgraph_get()
        c = bpy.data.objects.new("c", bpy.data.meshes.new_from_object(body.evaluated_get(dg)))
        c.matrix_world = body.matrix_world.copy()
        bpy.context.scene.collection.objects.link(c)
        kt = gd._join_body_collider(c, [], sp, dg, arm)
        gd._remesh(c, 80000, gd.core_segments(arm))
        margin = gd._body_collider_margin([], sp)

        def count():
            _co, _p, cen, _n = gd._mesh_arrays(c)
            return sum(kt.find_nearest(Vector(x), margin)[0] is not None for x in cen)
        before = count()
        gd.drop_outer_shells(c, body, layered=False, keep=(kt, margin) if keep else None)
        after = count()
        bpy.data.objects.remove(c)
        return before, after
    out["b3_tip_with_keep"] = tip_region(True)
    out["b3_tip_without_keep"] = tip_region(False)
    out["b4_reach_with_mm"] = reach([{"bone": "mixamorig:LeftBreastTip", "radius": 0.0045, "inflate": 0.002}])
    out["b4_reach_without_mm"] = reach([])
Path(out_path).write_text(json.dumps(out, indent=1))
print("B-RESULT", json.dumps(out))
