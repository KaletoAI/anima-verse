#!/usr/bin/env python3
"""Where the attached part's lower pouch hangs relative to the chain root (Ruling A65).

Usage: ./.venv/bin/python scripts/smoke_attached_part_placement.py
Runs Blender 5.2 on the CPU against a synthetic body written to a temp dir; no
world, no server, no network.

Fixture (metres, front -Y, up +Z): Hips head at z 1.10, so the anchor ray runs
at z = 1.10 - .09 - .01 = 1.00. The front skin above z .997 is the tilted plane
y = -.065 + .3 (z - 1.0): its outward normal is (0, -1, .3)/|.| =
(0, -.958, .287), facing up and forward like a torso sloping back below the waist.
Below z .997 the skin recedes by 65 mm over 12 mm, a ledge just under the
root, so nothing but the sweep itself hides the pouch. The root is the ray
hit (0, -.065, 1.0) minus root_sink .006 along that normal:
R = (0, -.065 + .00575, 1.0 - .00172).

Hand-derived expectations from the declared defaults (pods.down .024,
pods.back .010, pod scale (1 + .55 (s - 1)) x 1.2):
- size 1.0: pod factor f = 1.2. The companion bone (the pod centre) sits at
  R + (0, +.010, -.024 f) = R + (0, 10.0, -28.8) mm, plumb below the root and
  10 mm behind it, whatever the skin's tilt.
- size 1.6: f = 1.33 x 1.2 = 1.596, so R + (0, 10.0, -38.3) mm.
- The union's top is the last ellipsoid's: its centre is .008 f above the pod
  centre and its z radius .016 f, so its top is at the pod centre + .024 f =
  exactly the root's height (0 mm, both sizes); the other three tops lie
  .006 f, .002 f and .023 f below it. The ellipsoid frame's third axis is
  world up, so a top is its centre's z plus its z radius whatever the skin
  normal.
- Built mesh: the pouch is the part surface nearer the declared ellipsoid union
  than the sweep (sweep = the chain bones from the root, minus the radius
  .0165 s) and within .004 s + 1 mm of that union: the web between them
  (pod_web.blend .016 s) bulges the surface out by at most k/4 = .004 s, plus
  1 mm for voxels and smoothing. The two lateral ellipsoids (centres
  (.024 + .006) f and (.024 + .002) f below the root, z radius .024 f) top out
  .006 f and .002 f below the root (at most 7.2 / 9.6 mm), beside the sweep,
  which hides the part of the union above them. So the pouch's highest vertex
  lies at most .006 f + 5 mm below the root (12.2 / 14.6 mm; 5 mm for the
  sweep's flank) and at most the smooth-union bulge k/4 = .008 f / 4 (2.4 / 3.2 mm) plus 2 mm
  above it: no gap and no deep overlap.

Old-code proof: the builder at commit e557f8a65e1a59b18ec93af5200699b1ac7abfcc
(.046 f down, .018 back along the skin normal) puts the pod centre at
R + .018 x (0, .958, -.287) - (0, 0, .046 f), i.e. (0, 17.2, -60.4) mm at
size 1.0; its declared union top is .022 f below the root (26.4 mm) and its
lateral tops .028 f and .024 f (33.6 / 28.8 mm), so its pouch top misses the
12.2 / 14.6 mm limit. All six checks (two sizes x three) fail there.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'
OLD_COMMIT = 'e557f8a65e1a59b18ec93af5200699b1ac7abfcc'
SIZES = (1.0, 1.6)


def skin_y(z, ledge=True):
    """The fixture's front skin at height z (see the docstring); without the
    ledge the tilted plane runs on below the root."""
    if z >= .997 or not ledge:
        return -.065 + .3 * (z - 1.0)
    return -.065 + .3 * (.997 - 1.0) + .065 * min(1., (.997 - z) / .012)


def make_fixture(scripts, out, ledge=True):
    """Write the tilted synthetic body (see the docstring) to ``out``/fixture.glb.

    Returns the fixture path and the root and skin normal found by the
    builder's ray, independently of the builder. Runs inside Blender; the seam
    smoke shares it."""
    import bpy
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, scripts)
    import _common
    _common.reset_scene()
    arm = bpy.data.objects.new('Rig', bpy.data.armatures.new('Rig'))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for i, name in enumerate(json.loads((ROOT / 'shared/models/rig/joints.json').read_text())):
        bone = arm.data.edit_bones.new('mixamorig:' + name)
        bone.head = (0, 0, 1.10 + i * .002)
        bone.tail = bone.head + Vector((0, 0, .02))
        if name != 'Hips':
            bone.parent = arm.data.edit_bones['mixamorig:Hips']
        if name.endswith('UpLeg'):
            bone.head = ((-.09 if name.startswith('Left') else .09), 0, .96)
            bone.tail = bone.head + Vector((0, 0, -.25))
    bpy.ops.object.mode_set(mode='OBJECT')
    vertices, faces = [], []
    for z in np.linspace(.72, 1.34, 125):
        for x in np.linspace(-.18, .18, 73):
            vertices.append((x, skin_y(z, ledge), z))
    for iz in range(124):
        for ix in range(72):
            a = iz * 73 + ix
            faces.append((a, a + 1, a + 74, a + 73))
    start = len(vertices)
    vertices.extend([(-.18, .065, .72), (.18, .065, .72), (.18, .065, 1.34), (-.18, .065, 1.34)])
    faces.append((start + 3, start + 2, start + 1, start))
    me = bpy.data.meshes.new('Body')
    me.from_pydata(vertices, [], faces)
    me.update()
    body = bpy.data.objects.new('Body', me)
    bpy.context.collection.objects.link(body)
    uv = me.uv_layers.new(name='UVMap')
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = ((co.x + .2) / .4, (co.z - .15) / 1.25)
    image = bpy.data.images.new('fixture_skin', 128, 128)
    pixels = np.ones((128, 128, 4), np.float32)
    pixels[..., :3] = [.65, .48, .38]
    image.pixels.foreach_set(pixels.ravel())
    image.pack()
    material = bpy.data.materials.new('Body')
    material.use_nodes = True
    tex = material.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = image
    bsdf = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    material.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    me.materials.append(material)
    for name in ('Hips', 'LeftUpLeg', 'RightUpLeg'):
        body.vertex_groups.new(name='mixamorig:' + name)
    for v in me.vertices:
        for name, w in (('Hips', .3), ('LeftUpLeg', .35), ('RightUpLeg', .35)):
            body.vertex_groups['mixamorig:' + name].add([v.index], w, 'REPLACE')
    body.parent = arm
    body.modifiers.new('Armature', 'ARMATURE').object = arm
    fixture = out / 'fixture.glb'
    bpy.ops.export_scene.gltf(filepath=str(fixture), export_format='GLB')
    # The root, independently of the builder: the same ray on the fixture.
    _common.reset_scene()
    _common.import_model(fixture)
    skin = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups)
    rig = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    head = rig.matrix_world @ rig.pose.bones['mixamorig:Hips'].head
    inv = skin.matrix_world.inverted()
    hit, normal, _, _ = BVHTree.FromObject(skin, bpy.context.evaluated_depsgraph_get()).ray_cast(
        inv @ (head + Vector((0, -.15, -.10))), inv.to_3x3() @ Vector((0, 1, 0)))
    normal = (skin.matrix_world.to_3x3() @ normal).normalized()
    normal = Vector((0, normal.y, normal.z)).normalized()
    root = skin.matrix_world @ hit - normal * .006
    return fixture, root, normal


def blender_side(scripts, directory):
    import bpy
    import numpy as np
    sys.path.insert(0, scripts)
    import attached_part
    out = Path(directory)
    fixture, root, normal = make_fixture(scripts, out)
    results = {'root': list(root), 'normal': list(normal), 'sizes': {}}
    chain = [{'bone': 'PartLink' + str(i + 1), 'parent': 'Hips' if i == 0 else 'PartLink' + str(i)} for i in range(5)]
    companion = {'id': 'pods', 'op': 'attached_part_bone', 'chains': [[{'bone': 'PartPods', 'parent': 'Hips'}]], 'params': {}}
    settings = attached_part.parameters({})
    for size in SIZES:
        group = {'id': 'part', 'op': 'attached_part', 'chains': [chain],
                 'params': {'size_factor': size, 'voxel': .002, 'texture': {'bake': 128}}}
        target = out / ('size-' + str(size))
        target.mkdir()
        attached_part.attached_part({'inputs': {'model': str(fixture)},
                                     'params': {'groups': [group, companion]}, 'out_dir': str(target)})
        rig = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
        part = next(o for o in bpy.context.scene.objects if o.get('attached_part') == 'part')
        pods = rig.matrix_world @ rig.data.bones['PartPods'].head_local
        links = [rig.matrix_world @ rig.data.bones['PartLink' + str(i + 1)].head_local for i in range(5)]
        links.append(rig.matrix_world @ rig.data.bones['PartLink5'].tail_local)
        f = (1 + .55 * (size - 1)) * settings['pod_scale']
        # The DECLARED ellipsoids around the built companion: the old builder's
        # offsets ran along the skin normal, the new ones are plumb.
        frame = np.array([(1, 0, 0), tuple(normal), (0, 0, 1)])
        P = np.array([tuple(part.matrix_world @ v.co) for v in part.data.vertices])

        def union_distance(back):
            best = np.full(len(P), 1e9)
            for e in settings['pods']['ellipsoids']:
                c = np.array(tuple(pods)) + np.array([e['lateral'] * f, 0, -e['down'] * f]) + back * e['back']
                r = np.array(e['radii']) * f
                q = (P - c) @ frame.T / r
                best = np.minimum(best, (np.linalg.norm(q, axis=1) - 1) * r.min())
            return best
        line = np.array([tuple(root)] + [tuple(p) for p in links])
        sweep = np.full(len(P), 1e9)
        for a, b in zip(line[:-1], line[1:]):
            h = np.clip(((P - a) @ (b - a)) / ((b - a) @ (b - a)), 0, 1)
            sweep = np.minimum(sweep, np.linalg.norm(P - (a + h[:, None] * (b - a)), axis=1) - .0165 * size)
        tops = {}
        for label, back in (('plumb', np.array([0, 1., 0])), ('normal', -np.array(tuple(normal)))):
            near = union_distance(back)
            # The web (pod_web.blend .016 s) fuses the pods onto the sweep and
            # can push the surface out by k/4 = .004 s; 1 mm for the voxels.
            pouch = P[(near < sweep) & (near < .004 * size + .001)]
            tops[label] = float(pouch[:, 2].max()) if len(pouch) else None
        results['sizes'][str(size)] = {'pods': list(pods), 'pod_factor': f, 'pouch_top': tops,
                                       'union_top_declared': max(-e['down'] + e['radii'][2] for e in settings['pods']['ellipsoids']) * f - settings['pods']['down'] * f}
    (out / 'placement.json').write_text(json.dumps(results))


def run_blender(scripts, directory):
    env = {**os.environ, 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '1', 'PYTHONUNBUFFERED': '1'}
    Path(directory).mkdir()
    log = Path(directory) / 'blender.log'
    with log.open('w') as stream:
        result = subprocess.run(['nice', '-n', '15', 'timeout', '900', str(BLENDER), '-b', '-noaudio', '--factory-startup',
                                 '--python-exit-code', '1', '--python', str(Path(__file__).resolve()), '--',
                                 '--blender', scripts, directory], stdout=stream, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        print(log.read_text()[-6000:])
        raise SystemExit(result.returncode)
    return json.loads((Path(directory) / 'placement.json').read_text())


def failures(data):
    """Every hand-derived expectation the build misses, in millimetres."""
    out = []
    root = data['root']
    for size, expected_drop in ((1.0, 28.8), (1.6, 38.3)):
        row = data['sizes'][str(size)]
        dx, dy, dz = ((row['pods'][i] - root[i]) * 1000 for i in range(3))
        if abs(dx) > .5 or abs(dy - 10.0) > .5 or abs(dz + expected_drop) > .5:
            out.append(f'size {size}: pod centre {dx:.1f} / {dy:.1f} / {dz:.1f} mm from the root, '
                       f'expected 0 / 10.0 / -{expected_drop}')
        if abs(row['union_top_declared']) > 1e-9:
            out.append(f'size {size}: declared union top {row["union_top_declared"] * 1000:.1f} mm from the root, expected 0')
        top = row['pouch_top']['plumb']
        if top is None:
            out.append(f'size {size}: no pouch surface found')
            continue
        rise = (top - root[2]) * 1000
        low, high = -(6 * row['pod_factor'] + 5), 2 * row['pod_factor'] + 2
        if not low <= rise <= high:
            out.append(f'size {size}: pouch top {rise:.1f} mm from the root, expected between '
                       f'{low:.1f} and +{high:.1f}')
    return out


def main():
    with tempfile.TemporaryDirectory(prefix='attached-part-placement-') as directory:
        data = run_blender(str(ROOT / 'app/blender/scripts'), str(Path(directory) / 'new'))
        root = data['root']
        normal = data['normal']
        assert abs(root[1] - (-.065 + .00575)) < .0005 and abs(root[2] - .99828) < .0005, root
        assert abs(normal[1] + .958) < .005 and abs(normal[2] - .287) < .005, normal
        problems = failures(data)
        assert not problems, problems
        for size in SIZES:
            row = data['sizes'][str(size)]
            print(f'size {size}: pod centre', [round((row['pods'][i] - root[i]) * 1000, 1) for i in range(3)],
                  'mm from the root; pouch top', round((row['pouch_top']['plumb'] - root[2]) * 1000, 1), 'mm')
        # The same checks against the builder before Ruling A65.
        old = Path(directory) / 'old-scripts'
        old.mkdir()
        for name in ('attached_part.py', '_common.py'):
            source = subprocess.run(['git', '-C', str(ROOT), 'show', f'{OLD_COMMIT}:app/blender/scripts/{name}'],
                                    capture_output=True, text=True, check=True).stdout
            (old / name).write_text(source)
        old_data = run_blender(str(old), str(Path(directory) / 'old'))
        # The old builder offset the neck ellipsoid along the skin normal; read
        # its pouch with that union so the proof measures the old shape.
        for size in SIZES:
            row = old_data['sizes'][str(size)]
            row['pouch_top']['plumb'] = row['pouch_top']['normal']
        old_problems = failures(old_data)
        assert len(old_problems) >= 6, old_problems
        print('old builder', OLD_COMMIT[:9], 'fails', len(old_problems), 'checks, e.g.', old_problems[0])
    print('PASS attached_part placement: the pouch hangs plumb from the chain root, its top at the root')


if __name__ == '__main__':
    if '--blender' in sys.argv:
        try:
            index = sys.argv.index('--blender')
            blender_side(sys.argv[index + 1], sys.argv[index + 2])
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    else:
        main()
