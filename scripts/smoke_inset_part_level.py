#!/usr/bin/env python3
"""The inset part levels the skin the mesher modelled in its region before the part is built (Ruling A77).

Usage:
    ./.venv/bin/python scripts/smoke_inset_part_level.py

Synthetic fixture in temporary storage, no world, no server — the closed-skin fixture of
``smoke_inset_part_blender.py``: a 150 mm sphere around (0, 0, 1.02) with an inward shell 5 mm under it (a
double-walled body), two cube legs, Hips at z 1.10, a UV seam on the midline.

The modelled detail: a plateau 6 mm high (.5 mm ramp) of radius 7 mm on the outer skin only, pushed out along the
sphere normal, centred on the midline at 72.534 degrees below the sphere's equator (y -.04502, z .87691 — the
region's centre in ``smoke_inset_part_blender.py``); seen from the chart axis (0, 0, .94) that is 54.5 degrees and
.95 of the 6 mm, 5.7 mm, along the chart's radial direction.

Hand-derived expectations:
[1] No walls: the sphere falls away from the midline, so the outer envelope never rises 15 mm (``level.wall_rise``)
    inside the 32 mm half width — the region's half width is ``region.u`` = 32 mm on both sides everywhere.
[2] The surface: a local quadratic with Gaussian weights exp(-d^2 / sigma^2), sigma 15 mm. On the plain sphere its
    error is the fourth-order term, about sigma^4 / (8 r^3) = .015^4 / (8 x .13^3) = .02 mm; the 1.5 mm grid adds
    h'' step^2 / 8 = (1 / .13) .0015^2 / 8 = .002 mm. Once the plateau's residual (5.7 mm) exceeds ``level.tukey``
    = 4 mm it weighs nothing; what still pulls is the ramp below 4 mm: a ring 7.17-7.5 mm from the centre holding
    exp(-7.17^2 / 225) - exp(-7.5^2 / 225) = .015 of the Gaussian's mass at a mean lift of 2 mm, a pull of
    .015 x 2 = .03 mm on a constant, a few times that on a quadratic. The levelled outer skin over the region — the
    plateau's top included — therefore lies within .3 mm of the sphere (the tip's limit, ``smoke_tip_neutralise``).
[3] The record: ``source_level.bump_mm`` before = the plateau above the fit, 5.7 mm along the chart's radial
    direction up to 6 mm where a vertex's own radial meets the sphere normal, less the pull, plus the fit's
    own error (<= .3 mm), so in [5.6, 6.3]; after <= .3 mm. ``source_smooth.moved`` > 0.
[4] Nothing outside the region and its 12 mm fade moves: every source vertex further than 32 + 12 + 1 mm from the
    midline keeps its place (1e-9 m); subdivision only appends vertices.
[5] The inner shell is never above the levelled skin: within the region it follows it NEUTRAL_GAP_M = 1 mm under,
    so every inner-shell vertex (facing the sphere's centre) stays at radius <= .149 m + the .3 mm of [2].
[6] The part built from the fixture (levelling first, as in production) welds closed (``open_border_edges`` 0,
    ``border_max_abs_h`` 0) and reports the levelling in its metrics.

No expected value is recorded from a run. Fails on 0d1ed6f4d5e2155feb82f3c618f658cb6ac9a04c: ``inset_part`` has no
``level_region`` (the part was built on the skin as the mesher left it).
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path('/home/dev/tools/blender-5.2.2-linux-x64/blender')
PLATEAU_M, RAMP_M, RADIUS_M = .006, .0005, .007
CENTRE = (0., -.04502, .87691)


def fixture(directory):
    import bpy
    import bmesh
    import numpy as np
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import _common
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
    # The modelled detail: a plateau along the sphere normal, outer skin only.
    centre = np.array(CENTRE)
    for v in body.data.vertices:
        p = np.array(tuple(v.co))
        d = np.linalg.norm(p - centre)
        lift = PLATEAU_M * float(np.clip((RADIUS_M + RAMP_M - d) / RAMP_M, 0, 1))
        if lift:
            n = (p - np.array([0, 0, 1.02])) / .15
            v.co = tuple(p + n * lift)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=96, radius=.145, location=(0, 0, 1.02))
    shell = bpy.context.object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bm = bmesh.new(); bm.from_mesh(shell.data)
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:]); bm.to_mesh(shell.data); bm.free()
    body.select_set(True); bpy.context.view_layer.objects.active = body; bpy.ops.object.join()
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
        for name, weight in [('Hips', .3), ('LeftUpLeg', .35 + .1 * v.co.x), ('RightUpLeg', .35 - .1 * v.co.x)]:
            body.vertex_groups[name].add([v.index], weight, 'REPLACE')
    body.parent = arm
    body.modifiers.new('Armature', 'ARMATURE').object = arm
    image = bpy.data.images.new('Skin', 32, 32)
    image.generated_color = (.65, .48, .38, 1)
    image.pack()
    mat = bpy.data.materials.new('Skin'); mat.use_nodes = True
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage'); tex.image = image
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    me.materials.append(mat)
    uv = me.uv_layers.active or me.uv_layers.new(name='UVMap')
    for polygon in me.polygons:
        polygon.use_smooth = True
        side = polygon.center.x >= 0
        for li in polygon.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((co.x + .2) / .8 + (.5 if side else 0), (co.z - .2) / 1.1)
    path = Path(directory) / 'input.glb'
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', export_animations=False)
    return path


def probe(directory):
    import bpy
    import numpy as np
    from mathutils import Vector
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import _common
    import extension_bones
    import inset_part
    path = fixture(directory)
    _common.reset_scene()
    _common.import_model(path)
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups)
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    M = body.matrix_world
    before = np.array([tuple(M @ v.co) for v in body.data.vertices])
    sphere = np.array([0, 0, 1.02])
    P = inset_part.parameters({})
    c = inset_part.surface_chart(body, arm, P)['c']
    metrics = inset_part.level_region(body, arm, P)
    print(json.dumps(metrics))
    level, smooth = metrics['source_level'], metrics['source_smooth']
    # [1] no walls
    assert level['half_width_mm'] == [32.0, 32.0], level
    # [3] the record
    assert 5.6 <= level['bump_mm'][0] <= 6.3, level
    assert level['bump_mm'][1] <= .3, level
    assert smooth['moved'] > 0, smooth
    after = np.array([tuple(M @ v.co) for v in body.data.vertices])
    count = len(before)
    radius = np.linalg.norm(after - sphere, axis=1)
    # Outer skin and inner shell by their facing (the levelled inner shell lies 1 mm under the skin); not the legs.
    normals = np.array([tuple((M.to_3x3() @ v.normal).normalized()) for v in body.data.vertices])
    facing = np.einsum('ij,ij->i', normals, after - sphere)
    outer = (facing > 0) & (radius > .1) & (radius < .16)
    inner = (facing < 0) & (radius > .1) & (radius < .16)
    t = np.degrees(np.arctan2(-(after[:, 2] - c.z), -(after[:, 1] - c.y)))
    t0, t1 = level['angle_deg']
    region = (t >= t0) & (t <= t1) & (np.abs(after[:, 0]) <= .032) & (after[:, 2] < c.z)
    # [2] the levelled outer skin within .3 mm of the sphere, the plateau's top included
    deviation = np.abs(radius - .15)[outer & region]
    assert deviation.size > 100 and deviation.max() <= .0003, (deviation.size, deviation.max())
    lifted = np.array(CENTRE) + (np.array(CENTRE) - sphere) / .15 * PLATEAU_M
    top = int(np.argmin(np.linalg.norm(before - lifted, axis=1)))
    assert np.linalg.norm(before[top] - lifted) < .003
    assert abs(radius[top] - .15) <= .0003, radius[top]
    # [4] nothing moves outside the region and its fade
    far = np.abs(before[:, 0]) > .045
    assert np.abs(after[:count][far] - before[far]).max() <= 1e-9
    # [5] the inner shell never above the levelled skin
    assert radius[inner].max() <= .149 + .0003, radius[inner].max()
    # [6] the part, built on a fresh copy (it levels the region itself), welds closed
    _common.reset_scene()
    _common.import_model(path)
    metrics = inset_part.build_part({'id': 'inset', 'op': 'inset_part', 'chains': [], 'params': {'bake': 64}},
                                    Path(directory) / 'model.glb')
    assert metrics['open_border_edges'] == 0 and metrics['border_max_abs_h'] == 0, metrics
    assert metrics['source_level']['bump_mm'][1] <= .3, metrics['source_level']
    print('PASS inset levelling: plateau %.2f -> %.2f mm, skin within %.3f mm of the sphere, inner shell <= %.4f m, '
          'part welded' % (level['bump_mm'][0], level['bump_mm'][1], deviation.max() * 1000, radius[inner].max()))


if __name__ == '__main__':
    if '--fixture' in sys.argv:
        try:
            probe(sys.argv[-1])
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush(); sys.stderr.flush()
            os._exit(1)
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
    with tempfile.TemporaryDirectory(prefix='inset-level-') as directory:
        subprocess.run([str(BLENDER), '-b', '-noaudio', '--factory-startup', '--python-exit-code', '1', '-t', '2',
                        '-P', __file__, '--', '--fixture', directory], check=True)
