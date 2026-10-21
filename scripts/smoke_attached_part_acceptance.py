#!/usr/bin/env python3
"""Opt-in pose regression on a local job, with no bundled fixture dependency.

ATTACHED_PART_ACCEPTANCE_JOB names a runner job JSON (inputs.model, params.groups).
Outputs go to temporary storage. Limits are externally accepted stretch ratios,
not snapshots: walk <=3.6, lift 35 <=5.8, lift 90 <=12, root slide <=0.5 mm.
A skin influence beyond 35 mm from the root indicates an incidental contact was
mistaken for the root fillet. Hidden shell must remain hidden in both walk poses.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'


def check(job, output):
    import bpy
    import math
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import attached_part
    import _common
    _common.reset_scene()
    _common.import_model(job['inputs']['model'])
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups)
    original = [body.matrix_world @ v.co for v in body.data.vertices]
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    group = next(g for g in job['params']['groups'] if g['op'] == 'attached_part')
    settings = attached_part.parameters(group.get('params', {}))
    anchor = attached_part.resolve_bone(arm.data.bones, settings['anchor_bone'])
    head = arm.matrix_world @ arm.pose.bones[anchor.name].head
    ray = head + Vector((0, -.15, -settings['anchor_drop'] - .01))
    inv = body.matrix_world.inverted()
    bvh = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())
    q, n, _, _ = bvh.ray_cast(inv @ ray, inv.to_3x3() @ Vector((0, 1, 0)))
    n = (body.matrix_world.to_3x3() @ n).normalized()
    n = Vector((0, n.y, n.z)).normalized()
    root = body.matrix_world @ q - n * settings['root_sink']
    if '--existing' not in sys.argv:
        attached_part.attached_part({**job, 'out_dir': output})
        source = str(Path(output) / 'model.glb')
    else:
        source = sys.argv[sys.argv.index('--existing') + 1]
    _common.reset_scene()
    _common.import_model(source)
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups]
    body = next(o for o in meshes if not o.get('attached_part') and o.name != 'Part')
    part = next(o for o in meshes if o != body)
    def evaluated(obj):
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = ev.to_mesh()
        points = [obj.matrix_world @ v.co for v in mesh.vertices]
        ev.to_mesh_clear()
        return points
    def signed(bvh, p):
        q, n, _, _ = bvh.find_nearest(p)
        return (p - q).dot(n)
    for pb in arm.pose.bones:
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
    rest = [p for m in meshes for p in evaluated(m)]
    edges = []
    offset = 0
    for m in meshes:
        edges.extend((offset + e.vertices[0], offset + e.vertices[1]) for e in m.data.edges)
        offset += len(m.data.vertices)
    edges = [(a, b) for a, b in edges if (rest[a]-root).length < .2
             and (rest[b]-root).length < .2 and (rest[a]-rest[b]).length > 1e-6]
    b0, p0 = evaluated(body), evaluated(part)
    body.data.calc_loop_triangles()
    triangles = [tuple(t.vertices) for t in body.data.loop_triangles]
    rest_bvh = BVHTree.FromPolygons(b0, triangles)
    hidden = [i for i, p in enumerate(p0) if signed(rest_bvh, p) < -.0005]
    kd = KDTree(len(b0))
    for i, p in enumerate(b0):
        kd.insert(p, i)
    kd.balance()
    pairs = [(i, j) for i, p in enumerate(p0) for _, j, d in [kd.find(p)]
             if d < .006 and (p-root).length < .05]
    seams = {}
    assert len(original) == len(b0)
    for i, p in enumerate(original):
        seams.setdefault(tuple(round(c / 1e-5) for c in p), []).append(i)
    cracks = sum(any((b0[i]-b0[indices[0]]).length > 1e-5 for i in indices)
                 for indices in seams.values() if len(indices) > 1)
    thigh = [(part.matrix_world @ v.co-root).length for v in part.data.vertices
             if any(part.vertex_groups[g.group].name.endswith('UpLeg') and g.weight > 1e-4 for g in v.groups)]
    metrics = {'cracked_seam_groups': cracks, 'thigh_vertices': len(thigh),
               'thigh_max_root_distance_mm': max(thigh, default=0)*1000}
    for label, angle, limit in [('walk A', 30, 3.6), ('walk B', -30, 3.6),
                                 ('lift 35', -35, 5.8), ('lift 90', -90, 12)]:
        for pb in arm.pose.bones:
            pb.rotation_euler = (0, 0, 0)
        if label.startswith('walk'):
            for name, sign in [('LeftUpLeg', 1), ('RightUpLeg', -1), ('LeftArm', -1), ('RightArm', 1)]:
                attached_part.resolve_bone(arm.pose.bones, name).rotation_euler[0] = math.radians(angle)*sign
        else:
            arm.pose.bones[group['chains'][0][0]['bone']].rotation_euler[0] = math.radians(angle)
        bpy.context.view_layer.update()
        posed = [p for m in meshes for p in evaluated(m)]
        stretch = sorted((posed[a]-posed[b]).length/(rest[a]-rest[b]).length for a, b in edges)
        metrics[label] = {'p99': stretch[int(.99*len(stretch))], 'max': stretch[-1]}
        if label.startswith('walk'):
            bp, pp = evaluated(body), evaluated(part)
            bv = BVHTree.FromPolygons(bp, triangles)
            metrics[label]['emergence'] = sum(signed(bv, pp[i]) > .001 for i in hidden)
            slides = sorted(((pp[i]-bp[j])-(p0[i]-b0[j])).length*1000 for i, j in pairs)
            assert slides, 'Fixture must exercise root contact'
            metrics[label]['root_slide_p95_mm'] = slides[int(.95*len(slides))]
    print('ACCEPTANCE', json.dumps(metrics), flush=True)
    Path(output, 'acceptance_metrics.json').write_text(json.dumps(metrics, indent=2))
    assert cracks == 0, metrics
    assert max(thigh, default=0) <= .035, metrics
    for label, limit in [('walk A', 3.6), ('walk B', 3.6), ('lift 35', 5.8), ('lift 90', 12)]:
        assert metrics[label]['max'] <= limit, metrics
        if label.startswith('walk'):
            assert metrics[label]['emergence'] == 0, metrics
            assert metrics[label]['root_slide_p95_mm'] <= .5, metrics
    print('PASS attached_part local acceptance: stretch, emergence, seams, root slide and skin-weight region', flush=True)


def main():
    job_path = os.environ.get('ATTACHED_PART_ACCEPTANCE_JOB')
    if not job_path:
        print('SKIP attached_part local acceptance: set ATTACHED_PART_ACCEPTANCE_JOB to a runner job JSON')
        return
    with tempfile.TemporaryDirectory(prefix='part-acceptance-') as directory:
        result = subprocess.run(['timeout', '600', str(BLENDER), '-b', '-P', str(Path(__file__).resolve()),
                                 '--', '--blender', job_path, directory],
                                env={**os.environ, 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'},
                                timeout=610)
        assert result.returncode == 0, result.returncode


if __name__ == '__main__':
    if '--blender' in sys.argv:
        try:
            index = sys.argv.index('--blender')
            check(json.loads(Path(sys.argv[index+1]).read_text()), sys.argv[index+2])
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush(); sys.stderr.flush(); os._exit(1)
        sys.stdout.flush(); sys.stderr.flush(); os._exit(0)
    else:
        main()
