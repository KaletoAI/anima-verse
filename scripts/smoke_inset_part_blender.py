#!/usr/bin/env python3
"""Synthetic closed skin fixture, generated entirely in temporary storage.

A 150 mm sphere under Hips provides a continuous midline and two skinned legs.
A UV-island seam crosses the patch; a GLB roundtrip creates coincident copies.
Weights Hips=.3, Left=.35+.1*x, Right=.35-.1*x sum to one; linear barycentric
interpolation preserves these affine values (displacement x changes <.001).
With pocket starting at s=.07, the cleft centre s=.05 has depth 9 mm, within
10 percent after the small mound/ridge contributions. A welded border has
one vertex per position, so opposing 30 degree walk/spread poses cannot crack.
"""
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path('/home/dev/tools/blender-5.2.2-linux-x64/blender')


def probe(directory):
    import bpy
    import bmesh
    import math
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import _common
    import inset_part
    _common.reset_scene()
    arm = bpy.data.objects.new('Rig', bpy.data.armatures.new('Rig'))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, x in [('Hips', 0), ('LeftUpLeg', -.09), ('RightUpLeg', .09)]:
        bone = arm.data.edit_bones.new(name)
        bone.head = (x, 0, 1.10)
        bone.tail = (x, 0, 1.20 if name == 'Hips' else .70)
        if name != 'Hips':
            bone.parent = arm.data.edit_bones['Hips']
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=96, radius=.15, location=(0, 0, 1.02))
    body = bpy.context.object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # Separate closed leg components exercise inherited skinning without affecting midline rays.
    for x in (-.10, .10):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0, .57))
        leg = bpy.context.object
        leg.scale = (.065, .07, .30)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        body.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.join()
    me = body.data
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:]); bm.to_mesh(me); bm.free()
    for name in ('Hips', 'LeftUpLeg', 'RightUpLeg'):
        body.vertex_groups.new(name=name)
    for v in me.vertices:
        for name, weight in [('Hips', .3), ('LeftUpLeg', .35 + .1*v.co.x), ('RightUpLeg', .35 - .1*v.co.x)]:
            body.vertex_groups[name].add([v.index], weight, 'REPLACE')
    body.parent = arm
    body.modifiers.new('Armature', 'ARMATURE').object = arm
    image = bpy.data.images.new('Skin', 32, 32)
    image.generated_color = (.65, .48, .38, 1); image.pack()
    mat = bpy.data.materials.new('Skin'); mat.use_nodes = True
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage'); tex.image = image
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    me.materials.append(mat)
    if not me.uv_layers.active:
        me.uv_layers.new(name='UVMap')
    # Give the two midline sides separate UV islands, forcing coincident seam
    # copies through glTF export/import before the production operation runs.
    uv = me.uv_layers.active
    for polygon in me.polygons:
        polygon.use_smooth = True
        side = polygon.center.x >= 0
        for li in polygon.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((co.x + .2) / .8 + (.5 if side else 0), (co.z - .2) / 1.1)
    fixture = Path(directory) / 'input.glb'
    bpy.ops.export_scene.gltf(filepath=str(fixture), export_format='GLB', export_animations=False)
    _common.reset_scene()
    _common.import_model(fixture)
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups)
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    me = body.data
    positions = [body.matrix_world @ v.co for v in me.vertices]
    seam_positions = {}
    for position in positions:
        key = tuple(round(x / 1e-5) for x in position)
        seam_positions[key] = seam_positions.get(key, 0) + 1
    assert any(count > 1 and abs(key[0]) == 0 for key, count in seam_positions.items())
    original = BVHTree.FromPolygons(positions, [tuple(p.vertices) for p in me.polygons])
    group = {'id': 'inset', 'op': 'inset_part', 'chains': [], 'params': {'pocket': {'s0': .07}, 'bake': 64}}
    metrics = inset_part.build_part(group, Path(directory) / 'model.glb')
    assert metrics['border_max_abs_h'] == 0 and metrics['open_border_edges'] == 0, metrics
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert meshes == [body] and len(body.data.materials) == 2
    assert body.data.materials[1]['attached_part'] == 'inset'
    blob = (Path(directory) / 'model.glb').read_bytes()
    size = struct.unpack_from('<I', blob, 12)[0]
    doc = json.loads(blob[20:20 + size])
    marked = [i for i, material in enumerate(doc['materials']) if material.get('extras', {}).get('attached_part') == 'inset']
    assert len(marked) == 1 and 'baseColorTexture' in doc['materials'][marked[0]]['pbrMetallicRoughness']
    assert len(doc['meshes']) == 1 and len(doc['meshes'][0]['primitives']) == 2
    assert all('bufferView' in image for image in doc['images'])
    patch = {i for p in body.data.polygons if p.material_index == 1 for i in p.vertices}
    for i in patch:
        v = body.data.vertices[i]
        weights = {body.vertex_groups[g.group].name: g.weight for g in v.groups}
        assert abs(sum(weights.values()) - 1) < 1e-6
        assert abs(weights['Hips'] - .3) < 1e-6
        assert abs(weights['LeftUpLeg'] - (.35 + .1*v.co.x)) < 1e-3
    # Recover the same sampled arc chart independently from original source rays.
    c = Vector((0, 0, 1.02))
    theta = np.radians(np.arange(-70, 170.01, .5))
    profile = np.array([tuple(original.ray_cast(c, Vector((0, -math.cos(t), -math.sin(t))))[0]) for t in theta])
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(profile[:, 1:], axis=0), axis=1))])
    anchor = int(np.argmax(profile[:, 2] <= 1.10 - .105))
    arc -= arc[anchor] + .046
    sample = Vector(tuple(profile[np.argmin(abs(arc - .05))]))
    direction = (sample-c).normalized()
    candidates = [body.data.vertices[i].co for i in patch if abs(body.data.vertices[i].co.x) < .0008]
    point = min(candidates, key=lambda p: ((p-c).normalized()-direction).length)
    depth = (sample-c).length - (point-c).length
    assert .0081 < depth < .0099, depth
    bm = bmesh.new(); bm.from_mesh(body.data)
    border = {v.index for e in bm.edges if len(e.link_faces) == 2 and {f.material_index for f in e.link_faces} == {0, 1} for v in e.verts}
    assert border
    bad = [e for e in bm.edges if len(e.link_faces) != 2 and any(f.material_index == 1 for f in e.link_faces)]
    assert not bad
    border_corners = {0: {}, 1: {}}
    for polygon in body.data.polygons:
        for index in polygon.vertices:
            if index in border:
                border_corners[polygon.material_index][index] = index
    assert all(set(corners) == border for corners in border_corners.values())
    bm.free()
    max_crack = 0.
    for axis in ('X', 'Y'):
        for name, angle in [('LeftUpLeg', 30), ('RightUpLeg', -30)]:
            bone = arm.pose.bones[name]; bone.rotation_mode = 'XYZ'
            bone.rotation_euler = (0, 0, 0); bone.rotation_euler['XYZ'.index(axis)] = math.radians(angle)
        bpy.context.view_layer.update()
        evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        assert all(all(math.isfinite(x) for x in evaluated.vertices[i].co) for i in border)
        crack = max((evaluated.vertices[border_corners[0][i]].co - evaluated.vertices[border_corners[1][i]].co).length for i in border)
        max_crack = max(max_crack, crack)
        assert crack == 0.
        body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    assert max_crack == 0.
    print('PASS inset geometry, material marker, normalized interpolated weights, 9 mm depth, walk/spread crack 0.000 mm', json.dumps(metrics))


if __name__ == '__main__':
    if '--fixture' in sys.argv:
        # The host audio destructor stalls; flush finished artifacts before exit.
        try:
            probe(sys.argv[-1])
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush(); sys.stderr.flush()
            os._exit(1)
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
    else:
        with tempfile.TemporaryDirectory(prefix='inset-smoke-') as directory:
            subprocess.run([str(BLENDER), '-b', '-noaudio', '--python-exit-code', '1', '-t', '2', '-P', __file__, '--', '--fixture', directory], check=True)
