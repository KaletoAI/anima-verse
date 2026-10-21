#!/usr/bin/env python3
"""Synthetic metre fixture: a textured box grid and two skinned leg boxes.

Hand-derived checks: five declared links plus one companion add six joints to
52 base joints. Distal tip chain weights belong to the last link; geometric pod
blends remain. The root border follows skin while incidental pod borders keep
part weights. Coincident front-grid copies must share
one displacement and dot(displacement, original normal) <= 1e-6. Hidden means
signed distance < -0.0005 m; after opposing +/-30 degree leg rotations, no such
vertex may exceed +0.001 m. One material owns one embedded part image.
All files, including the source fixture, are generated in temporary storage.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'


def blender_smoke(directory):
    import bpy
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    import math
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import _common
    import attached_part
    from collections import Counter
    root = Path(directory)
    _common.reset_scene()
    arm = bpy.data.objects.new('Rig', bpy.data.armatures.new('Rig'))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    names = json.loads((ROOT / 'shared/models/rig/joints.json').read_text())
    for i, name in enumerate(names):
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
    # Independent left/right grids create actual coincident seam copies at x=0.
    for left, right in ((-.18, 0), (0, .18)):
        start = len(vertices)
        for z in np.linspace(.72, 1.34, 63):
            for x in np.linspace(left, right, 19):
                y = -.065 + .065 * min(1., max(0., (.99-z)/.09)) - .004 * math.exp(-((x / .035) ** 2 + ((z - .98) / .03) ** 2))
                vertices.append((x, y, z))
        for iz in range(62):
            for ix in range(18):
                a = start + iz * 19 + ix
                faces.append((a, a + 1, a + 20, a + 19))
    # Back and sides close the torso; grid normals point to the front.
    start = len(vertices)
    vertices.extend([(-.18,.065,.72),(.18,.065,.72),(.18,.065,1.34),(-.18,.065,1.34)])
    faces.append((start + 3,start + 2,start + 1,start))
    # Leg boxes are independent components, as permitted for an input mesh.
    for x in (-.09,.09):
        a = len(vertices)
        vertices.extend([(x+dx,y,z) for z in (.2,.72) for y in (-.055,.055) for dx in (-.065,.065)])
        faces.extend(tuple(a+i for i in face) for face in
                     ((0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)))
    me = bpy.data.meshes.new('Body')
    me.from_pydata(vertices, [], faces); me.update()
    body = bpy.data.objects.new('Body', me)
    bpy.context.collection.objects.link(body)
    uv = me.uv_layers.new(name='UVMap')
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = ((co.x + .2) / .4, (co.z - .15) / 1.25)
    image = bpy.data.images.new('fixture_skin', 256, 256)
    pixels = np.ones((256,256,4),np.float32)
    pixels[...,:3] = [.65,.48,.38]
    pixels[...,:3] *= (1 + .02 * np.sin(np.arange(256)[None,:,None] * .4))
    image.pixels.foreach_set(pixels.ravel()); image.pack()
    material = bpy.data.materials.new('Body'); material.use_nodes = True
    tex = material.node_tree.nodes.new('ShaderNodeTexImage'); tex.image = image
    bsdf = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    material.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    me.materials.append(material)
    for name in ('Hips','LeftUpLeg','RightUpLeg'):
        body.vertex_groups.new(name='mixamorig:' + name)
    for v in me.vertices:
        if v.co.z < .72:
            body.vertex_groups['mixamorig:' + ('LeftUpLeg' if v.co.x < 0 else 'RightUpLeg')].add([v.index],1,'REPLACE')
        else:
            for name,w in (('Hips',.3),('LeftUpLeg',.35),('RightUpLeg',.35)):
                body.vertex_groups['mixamorig:'+name].add([v.index],w,'REPLACE')
    body.parent = arm
    body.modifiers.new('Armature','ARMATURE').object = arm
    fixture = root / 'fixture.glb'
    bpy.ops.export_scene.gltf(filepath=str(fixture),export_format='GLB')
    _common.reset_scene(); _common.import_model(fixture)
    before = next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.vertex_groups)
    original = [(v.co.copy(),v.normal.copy()) for v in before.data.vertices]
    imported_arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    head = imported_arm.matrix_world @ imported_arm.pose.bones['mixamorig:Hips'].head
    inv = before.matrix_world.inverted()
    initial_bvh = BVHTree.FromObject(before, bpy.context.evaluated_depsgraph_get())
    q, n, _, _ = initial_bvh.ray_cast(inv @ (head + Vector((0, -.15, -.10))),
                                     inv.to_3x3() @ Vector((0, 1, 0)))
    n = (before.matrix_world.to_3x3() @ n).normalized()
    n = Vector((0, n.y, n.z)).normalized()
    attachment_root = before.matrix_world @ q - n * .006
    chain = [{'bone': 'PartLink'+str(i+1), 'parent': 'Hips' if i==0 else 'PartLink'+str(i)} for i in range(5)]
    group = {'id':'part','op':'attached_part','chains':[chain],'params':{}}
    companion = {'id':'pods','op':'attached_part_bone','chains':[[{'bone':'PartPods','parent':'Hips'}]],'params':{}}
    for invalid in ({'unknown':1},{'flatten':{'unknown':1}},{'voxel':0},{'size_factor':True},{'texture':{'blur':8}},{'girth_max':0},{'bend':[[0,0,.38],[.25,.97,.7]]}):
        try: attached_part.parameters(invalid)
        except ValueError: pass
        else: raise AssertionError('Invalid parameters accepted: '+str(invalid))
    job = {'inputs': {'model': str(fixture)}, 'params': {'groups': [group, companion]},
           'out_dir': str(root), 'result': str(root / 'result.json')}
    (root / 'args.json').write_text(json.dumps(job))
    saved_argv = sys.argv
    try:
        sys.argv = ['blender', '--', str(root / 'args.json')]
        _common.main(attached_part.attached_part)
    finally:
        sys.argv = saved_argv
    result = json.loads((root / 'result.json').read_text())
    assert result['ok'], result
    data, outputs = result['data'], result['outputs']
    assert outputs['model'] == str(root / 'model.glb')
    arm = next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    body = next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.vertex_groups and not o.get('attached_part'))
    part = next(o for o in bpy.context.scene.objects if o.get('attached_part')=='part')
    assert len(original)==len(body.data.vertices)
    seam_groups = {}
    outward = 0.
    for v,(co,n) in zip(body.data.vertices,original):
        seam_groups.setdefault(tuple(round(c/1e-5) for c in co),[]).append(v.co.copy())
        outward = max(outward,(v.co-co).dot(n))
    cracks = sum(any((p-ps[0]).length>1e-6 for p in ps) for ps in seam_groups.values() if len(ps)>1)
    assert cracks==0, cracks
    assert outward <= 1e-6, outward
    for link in chain + companion['chains'][0]:
        b = arm.data.bones[link['bone']]
        assert b.parent.name.rsplit(':',1)[-1] == link['parent']
    kd = KDTree(len(body.data.vertices))
    for v in body.data.vertices: kd.insert(body.matrix_world@v.co,v.index)
    kd.balance()
    def weights(obj,v):
        return {obj.vertex_groups[g.group].name:g.weight for g in v.groups if g.weight>1e-7}
    counts = Counter(edge for poly in part.data.polygons for edge in poly.edge_keys)
    border = {vi for edge,count in counts.items() if count==1 for vi in edge}
    border_error = 0.
    tip_count = pod_count = root_border_count = 0
    tip_bone = arm.data.bones['PartLink5']
    tip_head = arm.matrix_world @ tip_bone.head_local
    tip_axis = (arm.matrix_world.to_3x3() @ (tip_bone.tail_local-tip_bone.head_local)).normalized()
    pod_center = arm.matrix_world @ arm.data.bones['PartPods'].head_local

    for v in part.data.vertices:
        w = weights(part,v)
        point = part.matrix_world @ v.co
        if any(name.endswith('UpLeg') for name in w):
            assert (point - attachment_root).length <= .035, (tuple(point), w)
        # At the root the body's 45 mm full radial reweight makes it pure
        # anchor. The root border must stay anchor-dominated after interpolation:
        # the anchor itself plus the pods bone, which is parented to the anchor and
        # does not follow a chain lift (a straight sweep brings the pods up to the
        # root border). Pod contacts elsewhere do not need skin weights.
        if v.index in border and (point - attachment_root).length < .025:
            assert w.get('mixamorig:Hips', 0) + w.get('PartPods', 0) > .5, (tuple(point), w)
            root_border_count += 1
        if v.index in border:
            _,bi,_ = kd.find(part.matrix_world@v.co)
            bw = weights(body,body.data.vertices[bi])
            border_error = max(border_error,max(abs(w.get(n,0)-bw.get(n,0)) for n in w.keys()|bw.keys()))
        point = part.matrix_world @ v.co
        delta = point-tip_head
        station = delta.dot(tip_axis)
        radial = (delta-tip_axis*station).length
        if station > .018 and radial < .017 and point.y < pod_center.y-.02:
            # The reference blends pod/link-1 skin into the cap where the two
            # fields overlap. Reassigning these vertices rigidly after decimate
            # introduces a discontinuity and fails the lift stretch acceptance.
            assert w.get('PartLink5', 0) > .5, (tuple(point), w)
            assert set(w) <= {'PartLink5', 'PartLink1', 'PartPods', 'mixamorig:Hips'}, w
            assert abs(sum(w.values()) - 1) < 1e-3, w
            residual = w.get('PartLink1', 0) + w.get('PartPods', 0)
            if residual > 1e-3:
                # On the sweep surface ds <= 0: the declared pod_link=.7
                # splits the residual 70:30. Interpolation/relief can lower it.
                assert .65 < w.get('PartLink1', 0)/residual < .701, w
            tip_count += 1
        delta = point-pod_center
        if .012 < abs(delta.x) < .03 and -.025 < delta.z < -.012 and -.025 < delta.y < -.008 and v.index not in border:
            assert w.get('PartPods',0)>.5, (tuple(point),w)
            assert set(w)<={'PartPods','PartLink1','mixamorig:Hips'}, w
            pod_count += 1
    assert border and root_border_count > 10, (len(border), root_border_count)
    assert tip_count>10 and pod_count>10,(tip_count,pod_count)
    def evaluated(obj):
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); mesh=ev.to_mesh()
        points=[obj.matrix_world@v.co for v in mesh.vertices]; ev.to_mesh_clear(); return points
    body.data.calc_loop_triangles()
    triangles=[tuple(t.vertices) for t in body.data.loop_triangles]
    def distance(bvh,point):
        q,n,_,_=bvh.find_nearest(point); return (point-q).dot(n)
    rest_bvh=BVHTree.FromPolygons(evaluated(body),triangles)
    hidden=[i for i,point in enumerate(evaluated(part)) if distance(rest_bvh,point)<-.0005]
    assert hidden, 'Fixture must exercise the hidden band'
    emerge=[]
    for sign in (-1,1):
        for name,factor in (('LeftUpLeg',1),('RightUpLeg',-1)):
            bone=arm.pose.bones['mixamorig:'+name];bone.rotation_mode='XYZ'
            bone.rotation_euler=(math.radians(30)*sign*factor,0,0)
        bpy.context.view_layer.update()
        bvh=BVHTree.FromPolygons(evaluated(body),triangles); points=evaluated(part)
        emerge.append(sum(distance(bvh,points[i])>.001 for i in hidden))
    assert emerge==[0,0],emerge
    metrics={**data['metrics']['part'],'border_weight_error':border_error,'checked_tip_vertices':tip_count, 'checked_root_border_vertices':root_border_count,
             'checked_pod_vertices':pod_count,'checked_seam_groups':sum(len(ps)>1 for ps in seam_groups.values()),
             'cracked_seam_groups':cracks,'flatten_outward_m':outward,'hidden_vertices':len(hidden),'walk_emergence':emerge}
    (root/'metrics.json').write_text(json.dumps(metrics))
    (root/'extensions.json').write_text(json.dumps({link['bone']:{'parent':link['parent'],'group':g['id']}
        for g in (group,companion) for c in g['chains'] for link in c}))
    # A separate build exercises the no-companion path at a cheaper resolution.
    anchor_dir = root / 'anchor'; anchor_dir.mkdir()
    anchor_group = {**group, 'params': {'voxel': .0028, 'texture': {'bake': 128}}}
    anchor_data, _ = attached_part.attached_part({'inputs': {'model': str(fixture)},
        'params': {'groups': [anchor_group]}, 'out_dir': str(anchor_dir)})
    anchor_part = next(o for o in bpy.context.scene.objects if o.get('attached_part') == 'part')
    assert anchor_part.vertex_groups.get('PartPods') is None
    anchor_pods = 0
    for vertex in anchor_part.data.vertices:
        point = anchor_part.matrix_world @ vertex.co
        delta = point - pod_center
        if .012 < abs(delta.x) < .03 and -.025 < delta.z < -.012 and -.025 < delta.y < -.008:
            w = weights(anchor_part, vertex)
            assert w.get('mixamorig:Hips', 0) > .5, (tuple(point), w)
            anchor_pods += 1
    assert anchor_pods > 10, anchor_pods
    (root / 'anchor_metrics.json').write_text(json.dumps({**anchor_data['metrics']['part'],
                                                        'checked_pod_vertices': anchor_pods}))
    # LOD must reduce both meshes, preserve the node marker and keep body first.
    main_entry = _common.main
    try:
        _common.main = lambda fn: None
        import lod
    finally:
        _common.main = main_entry
    lod_data, lod_outputs = lod.lod({'inputs': {'model': str(root / 'model.glb')},
        'params': {'ratios': [.5]}, 'out_dir': str(root)})
    reduced = Path(next(iter(lod_outputs.values())))
    reduced.rename(root / 'lod.glb')
    assert lod_data['stages'][0]['tris'] < lod_data['source_tris']
    print('PASS Blender geometry, declared parents, tip/root-border blends, pods, seams and walk')


def main():
    sys.path.insert(0,str(ROOT))
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='attached-part-') as directory:
        paths.init(Path(directory)/'world')
        env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
        log=Path('/tmp/attached-part-blender-detail.log')
        with log.open('w') as stream:
            result=subprocess.run(['timeout','600',str(BLENDER),'-b','-noaudio','--factory-startup','--python-exit-code','1','--python',str(Path(__file__).resolve()),'--','--blender',directory],stdout=stream,stderr=subprocess.STDOUT,text=True,env={**env,'PYTHONUNBUFFERED':'1'})
        if result.returncode:
            print(log.read_text()[-14000:]); raise SystemExit(result.returncode)
        from app.core.model_validate import validate_glb,parse_glb
        raw=(Path(directory)/'model.glb').read_bytes()
        verdict=validate_glb(raw,extension_names=json.loads((Path(directory)/'extensions.json').read_text()))
        assert verdict['ok'] and verdict['joint_count'] == 58, verdict
        doc=parse_glb(raw)['gltf']
        nodes=[n for n in doc['nodes'] if 'attached_part' in n.get('extras',{})]
        assert len(nodes)==1 and nodes[0]['mesh']!=0
        images={doc['textures'][doc['materials'][p['material']]['pbrMetallicRoughness']['baseColorTexture']['index']]['source']
                for p in doc['meshes'][nodes[0]['mesh']]['primitives']}
        assert len(images)==1 and 'bufferView' in doc['images'][next(iter(images))]
        assert len(doc['images'])==2, doc['images']
        for filename in ('anchor/model.glb', 'lod.glb'):
            variant = (Path(directory) / filename).read_bytes()
            variant_verdict = validate_glb(variant, extension_names=json.loads((Path(directory)/'extensions.json').read_text()))
            assert variant_verdict['ok'] and variant_verdict['joint_count'] == (57 if filename.startswith('anchor') else 58), variant_verdict
            variant_doc = parse_glb(variant)['gltf']
            assert len(variant_doc['meshes']) == 2
            assert all(n['mesh'] != 0 for n in variant_doc['nodes'] if 'attached_part' in n.get('extras', {}))
        print('ANCHOR_METRICS', (Path(directory)/'anchor_metrics.json').read_text())
        print('METRICS', (Path(directory)/'metrics.json').read_text())
        print('PASS attached_part synthetic Blender export validates; one embedded part texture')


if __name__=='__main__':
    if '--blender' in sys.argv:
        # This host's PulseAudio destructor stalls even with -noaudio. All
        # artifacts are explicitly written first; skip only process teardown.
        try:
            blender_smoke(sys.argv[sys.argv.index('--blender')+1])
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush(); sys.stderr.flush()
            os._exit(1)
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
    else:
        main()
