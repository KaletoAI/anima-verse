#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_inset_part_blender.py

Synthetic closed skin fixture, generated entirely in temporary storage.

A 150 mm sphere under Hips provides a continuous midline and two skinned legs.
A UV-island seam crosses the patch; a GLB roundtrip creates coincident copies.
Weights Hips=.3, Left=.35+.1*x, Right=.35-.1*x sum to one; linear barycentric
interpolation preserves these affine values (displacement x changes <.001).
With pocket starting at s=.07, the cleft centre s=.05 has depth 9 mm, within
10 percent after the small mound/ridge contributions. A welded border has
one vertex per position, so opposing 30 degree walk/spread poses cannot crack.

The inward shell is 5 mm under the 150 mm outer sphere. Inside rays
continuing through the 5 mm gap must therefore give midline |r| < 1 mm, never the inner shell's 5 mm error.
For the round sphere L=.15*55*pi/180=.14399 m; the front corner is
y=-.15*cos(50)=-.09642, z=1.02-.15*sin(50)=.90509 (2 mm sampling tolerance).
A missing back corner uses .138 m and scale 1; a missing front corner fails.
A short variant scales outer Y by .4; the 50..105 degree normal interval
is shorter than .138*.75=.1035 m, so scale must clamp to .75. The cleft
midpoint is the underside midpoint minus .013 m, and its length is .075 m.
For the round sphere its angle is 77.5-.013/.15*180/pi=72.534 degrees,
giving y=-.04502, z=.87691. Arc lengths on the short ellipse integrate
sqrt(.06**2*sin(t)**2+.15**2*cos(t)**2) between the two sampled endpoints.
The tall variant stretches only the upper half to 750 mm and widens Y
by 1+2*(z-1.02)/.15: at -70 degrees
the outer hit is over 400 mm from the chart centre, while the lower half
and its placement stay unchanged. The fill variant has a green stripe at
|x| < 4 mm, z in [.88,.895], surrounded by constant (.65,.48,.38).
With unit tint, a constant boundary has the same constant harmonic fill;
fully clean, fully covered pixels must match that tone within .025 per channel
and raw stripe pixels must differ by > .1. The ramp and zero-clean border
must preserve raw pixels according to their blend weights. The same
expectations hold for 256 and 257 pixel bakes (partial 4x4 edge blocks).
Unit-tint pixels below 1 indicate partial raster coverage and are excluded
from the constant-tone check. Written RGB channels round to 8 bits, so the
blend has at most .5/255 error per channel.
UV coverage samples use strict triangle interiors, excluding shared edges;
a height field has at most one covering triangle at every sampled texel.
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
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import _common
    import inset_part
    _common.reset_scene()
    bake_size = 257 if '--fill-odd' in sys.argv else 256
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
    if '--short' in sys.argv:
        for v in body.data.vertices: v.co.y *= .4
    if '--tall' in sys.argv:
        for v in body.data.vertices:
            if v.co.z > 1.02:
                v.co.y *= 1 + 2*(v.co.z-1.02)/.15
                v.co.z = 1.02 + 5*(v.co.z-1.02)
    # Add an inward shell before the source UV seam roundtrip.
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=96, radius=.145, location=(0, 0, 1.02))
    shell = bpy.context.object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if '--short' in sys.argv:
        for v in shell.data.vertices: v.co.y *= .4
    if '--tall' in sys.argv:
        for v in shell.data.vertices:
            if v.co.z > 1.02:
                v.co.y *= 1 + 2*(v.co.z-1.02)/.15
                v.co.z = 1.02 + 5*(v.co.z-1.02)
    bm = bmesh.new(); bm.from_mesh(shell.data)
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:]); bm.to_mesh(shell.data); bm.free()
    body.select_set(True); bpy.context.view_layer.objects.active = body; bpy.ops.object.join()
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
    image.generated_color = (.65, .48, .38, 1)
    if '--fill' in sys.argv or '--fill-odd' in sys.argv:
        bpy.data.images.remove(image)
        image = bpy.data.images.new('Skin', 512, 512)
        yy, xx = np.mgrid[:512, :512]
        u, v = (xx+.5)/512, (yy+.5)/512
        pixels = np.empty((512,512,4), np.float32)
        pixels[:] = (.65,.48,.38,1)
        stripe = ((abs(u-.25)<.005)|(abs(u-.75)<.005)) & (v>(.88-.2)/1.1) & (v<(.895-.2)/1.1)
        pixels[stripe] = (.05,.95,.05,1)
        image.pixels.foreach_set(pixels.ravel())
    image.pack()
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
    source_faces = [tuple(p.vertices) for p in me.polygons]
    group = {'id': 'inset', 'op': 'inset_part', 'chains': [], 'params': {'pocket': {'s0': .07}, 'bake': 64}}
    if '--fill' in sys.argv or '--fill-odd' in sys.argv:
        group['params'].update(bake=bake_size, tone={k: [1,1,1] for k in inset_part.DEFAULTS['tone']})
    try:
        inset_part.build_part(dict(group, params={'under': [1000, 1001]}), Path(directory) / 'missing.glb')
    except ValueError as error:
        assert 'No front corner' in str(error), error
    else:
        raise AssertionError('Missing front corner must fail')
    if '--fallback' in sys.argv:
        group['params']['under'] = [50, 1000]
    captured = {}
    def trace(frame, event, arg):
        if frame.f_code is inset_part.build_part.__code__ and event == 'return':
            captured.update(frame.f_locals)
    sys.setprofile(trace)
    try:
        metrics = inset_part.build_part(group, Path(directory) / 'model.glb')
    finally:
        sys.setprofile(None)
    if '--tall' in sys.argv:
        assert np.linalg.norm(captured['prof'][0] - np.array(captured['c'])) > .4
    if '--fill' in sys.argv or '--fill-odd' in sys.argv:
        baked = np.array(captured['bimg'].pixels[:]).reshape(bake_size,bake_size,4)[..., :3]
        # z=.887 is inside the stripe and the fully clean central chart.
        index = int(np.argmin(abs(captured['Q'][:,2]-.887) + 20*abs(captured['u_q'])))
        uv_point = (captured['su'][index]-captured['lo'])/captured['span'] + .01
        x, y = (uv_point*bake_size).astype(int)
        assert np.max(abs(baked[y,x]-np.array([.65,.48,.38]))) < .025, baked[y,x]
        raw = captured['raw'][..., :3]
        clean = captured['clean_px']
        covered = captured['cover'] & (captured['tint_px'][...,:3].min(2) > .999)
        tone = np.array([.65,.48,.38])
        inside = covered & (clean > .999)
        assert inside.sum() > 100
        assert np.max(abs(raw[inside]-tone)) > .1, 'Stripe must reach the raw bake'
        assert np.max(abs(baked[inside]-tone)) < .025, np.max(abs(baked[inside]-tone))
        border_px = covered & (clean < 1e-6)
        assert border_px.any(), ('no zero-clean pixels', float(clean[covered].min()))
        assert np.all(captured['clean'][captured['border']] == 0)
        assert np.max(abs(baked[border_px]-raw[border_px])) < 1e-6
        ramp = covered & (clean > .05) & (clean < .95)
        assert ramp.any(), 'no ramp pixels'
        expected = (raw*(1-clean[...,None]) + captured['fill']*clean[...,None])*captured['tint_px'][...,:3]
        assert np.max(abs(baked[covered]-expected[covered])) < .5/255 + 1e-6, ('blend error', np.max(abs(baked[covered]-expected[covered])))
        print('PASS stripe fill, constant interior within .025, raw border and clean ramp')
    assert metrics['inner_wall_faces_removed'] > 0, metrics
    assert np.all(captured['fac_b'][captured['near']] > .2)
    assert np.max(np.abs(captured['r_b'][(np.abs(captured['u_b']) < 1e-6) & captured['near']])) < .001
    assert len(captured['inner_wall']) == metrics['inner_wall_faces_removed']
    assert not (captured['inner_wall'] & captured['sel_polys'])
    position_key = lambda p: tuple(round(float(x)/1e-6) for x in p)
    removed_faces = {frozenset(position_key(positions[v]) for v in source_faces[i])
                     for i in captured['inner_wall']}
    remaining_faces = {frozenset(position_key(body.matrix_world @ body.data.vertices[v].co) for v in face.vertices)
                       for face in body.data.polygons if face.material_index == 0}
    assert removed_faces.isdisjoint(remaining_faces)
    if '--fallback' in sys.argv:
        assert metrics['underside_m'] == .138 and metrics['scale'] == 1., metrics
    elif '--short' in sys.argv:
        assert metrics['scale'] == .75, metrics
    else:
        assert metrics['scale'] == 1., metrics
        # Sphere normals turn through 55 degrees: .15*55*pi/180=.14399 m.
        assert abs(metrics['underside_m'] - .14399) < .003
        assert abs(metrics['front_corner'][1] + .09642) < .002
        assert abs(metrics['front_corner'][2] - .90509) < .002
    assert abs(captured['s_start'] + .05 * metrics['scale'] -
               (captured['arc'][captured['i0']] + metrics['underside_m']/2 - .013)) < 1e-9
    # Measure the physical cleft interval on the analytic fixture, independent
    # of the chart's arc accumulator and scale implementation.
    endpoint_indices = [int(np.argmin(abs(captured['s_q']-s) + 20*abs(captured['u_q'])))
                        for s in (0., .05, .10)]
    points = captured['Q'][endpoint_indices]
    axis_y = .06 if '--short' in sys.argv else .15
    angles = np.arctan2(-(points[:,2]-1.02)/.15, -points[:,1]/axis_y)
    samples = np.linspace(angles[0], angles[2], 1001)
    speeds = np.sqrt(axis_y**2*np.sin(samples)**2 + .15**2*np.cos(samples)**2)
    physical_length = np.trapezoid(speeds, samples)
    assert abs(physical_length - .10*metrics['scale']) < .002, physical_length
    if '--short' not in sys.argv and '--fallback' not in sys.argv:
        assert abs(points[1,1] + .04502) < .002
        assert abs(points[1,2] - .87691) < .002
    coverage = np.zeros((128,128), dtype=int)
    uv = body.data.uv_layers.active.data
    baked_triangles = [np.array([tuple(uv[i].uv) for i in face.loop_indices])
                       for face in body.data.polygons if face.material_index == 1]
    for triangle in baked_triangles:
        a,b,c = triangle
        matrix = np.stack([b-a,c-a],1)
        if abs(np.linalg.det(matrix)) < 1e-14: continue
        low = np.maximum(0, np.floor(triangle.min(0)*128).astype(int))
        high = np.minimum(128, np.ceil(triangle.max(0)*128).astype(int)+1)
        yy, xx = np.mgrid[low[1]:high[1], low[0]:high[0]]
        samples = np.stack([(xx.ravel()+.371)/128, (yy.ravel()+.619)/128], 1)
        weights = (samples-a) @ np.linalg.inv(matrix).T
        inside = (weights[:,0]>1e-9)&(weights[:,1]>1e-9)&(weights.sum(1)<1-1e-9)
        coverage[yy.ravel()[inside], xx.ravel()[inside]] += 1
    assert coverage.max() == 1, coverage.max()
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
    # Locate the midpoint directly in the undisplaced chart captured at build time.
    index = int(np.argmin(abs(captured['s_q']-.05) + 20*abs(captured['u_q'])))
    assert .0081 < -captured['hq'][index] < .0099, captured['hq'][index]
    displaced = Vector(captured['Q'][index] + captured['qn'][index]*captured['hq'][index])
    assert min((body.matrix_world @ body.data.vertices[i].co-displaced).length for i in patch) < 1e-6
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
            for variant in ('--short', '--fallback', '--tall', '--fill', '--fill-odd'):
                subprocess.run([str(BLENDER), '-b', '-noaudio', '--python-exit-code', '1', '-t', '2', '-P', __file__, '--', '--fixture', variant, directory], check=True)
