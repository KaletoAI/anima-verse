#!/usr/bin/env python3
"""Usage: .venv/bin/python scripts/smoke_head_twist.py

Hand-derived expectations: R_y(30) turns +Z toward +X, hence +30 degrees.
R_x(20) pitches +Y/+Z together; projected hips +Z still agrees, hence zero.
Neck +10 and Head world +40 give raw angles 10/40 (not relative-child 30).
The JSON fixture writes sin(15)=.2588190451, cos(15)=.9659258263,
and sin(5)=.08715574275, cos(5)=.9961946981 by hand; 10+30=40 world.

Blender fixture: head pivot (0,0,1.7), nose (0,-.3,1.8). Long axis +Z
(Blender), forward -Y. A +30-degree turn puts nose at (.15,-.2598076,1.8).
Undoing it restores (0,-.3,1.8). Bounds x +/-.1, y -.3..+.1,
z 0..2 imply normalize(target=2) scale 1, shift y +.1: nose (0,-.2,1.8).
The straight fixture must retain every vertex within 1e-6 after this same
translation. Two armature modifiers must skip correction and preserve all
vertex coordinates and pose matrices exactly. A side view with changed bytes
is stale even with an older mtime; matching bytes stay current regardless of age.
A recorded side view that no longer exists is stale, with or without hashes.
The output geometry is checked independently from pose reports.
"""
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.head_twist import read_head_twist, twist_degrees, twists_from_json, tpose_status
from app.blender import runner

FIXTURE = r'''
import bpy, math, sys
from mathutils import Matrix
out = sys.argv[sys.argv.index('--')+1]
for angle in (0, 30):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    arm = bpy.data.armatures.new('rig')
    obj = bpy.data.objects.new('rig', arm)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    parent = None
    for name, z in [('Hips',.5),('Spine',1),('Neck',1.4),('Head',1.7)]:
        b = arm.edit_bones.new('mixamorig:'+name)
        b.head = (0,0,z); b.tail = (0,0,z+.1); b.parent = parent
        parent = b
    bpy.ops.object.mode_set(mode='OBJECT')
    vertices = [(x,y,z) for z in (0,2) for y in (-.1,.1) for x in (-.1,.1)]
    vertices += [(0,-.3,1.8)]
    mesh = bpy.data.meshes.new('head')
    mesh.from_pydata(vertices, [], [(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3),(4,5,8)])
    body = bpy.data.objects.new('head',mesh); bpy.context.collection.objects.link(body)
    for name, indices in [('Hips',list(range(4))),('Head',list(range(4,9)))]:
        body.vertex_groups.new(name='mixamorig:'+name).add(indices,1,'REPLACE')
    mod = body.modifiers.new('arm','ARMATURE'); mod.object = obj
    body.parent = obj
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='POSE')
    p = obj.pose.bones['mixamorig:Head']
    p.rotation_mode = 'XYZ'; p.rotation_euler.y = math.radians(angle)
    bpy.context.view_layer.update()
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_copy(modifier=mod.name)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='POSE'); bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.export_scene.gltf(filepath=out+'/'+str(angle)+'.glb',export_format='GLB')
# GLB export collapses modifier stacks, so exercise the real helper in-scene.
    if angle == 30:
        body.modifiers.new('second_arm','ARMATURE').object = obj
        before = [v.co.copy() for v in body.data.vertices]
        pose_before = [p.matrix.copy() for p in obj.pose.bones]
        import runpy
        from pathlib import Path
        scripts = Path.cwd()/'app/blender/scripts'
        sys.path.insert(0, str(scripts))
        import _common
        _common.main = lambda fn: None
        untwist = runpy.run_path(str(scripts/'normalize.py'))['_untwist_head']
        report = untwist()
        assert report['corrected'] is False, report
        assert report['error'] == 'several armature modifiers; head twist left as is', report
        assert report['after'] == report['before'], report
        assert all(v.co == old for v, old in zip(body.data.vertices, before))
        assert all(p.matrix == old for p, old in zip(obj.pose.bones, pose_before))
        print('PASS duplicate armature modifiers preserve geometry and pose')
print('FIXTURES_OK')
'''


def positions(path):
    raw = Path(path).read_bytes()
    length = struct.unpack_from('<I',raw,12)[0]
    doc = json.loads(raw[20:20+length])
    start = 28+length
    result = []
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            a = doc['accessors'][primitive['attributes']['POSITION']]
            v = doc['bufferViews'][a['bufferView']]
            offset = start+v.get('byteOffset',0)+a.get('byteOffset',0)
            stride = v.get('byteStride',12)
            result += [struct.unpack_from('<3f',raw,offset+i*stride) for i in range(a['count'])]
    return result


def main():
    c, s = math.sqrt(3)/2, .5
    assert abs(twist_degrees([[c,0,s],[0,1,0],[-s,0,c]],[0,0,1])-30)<1e-8
    c,s = math.cos(math.radians(20)),math.sin(math.radians(20))
    assert abs(twist_degrees([[1,0,0],[0,c,-s],[0,s,c]],[0,0,1]))<1e-8
    doc = {'nodes':[{'name':'Hips','children':[1]}, {'name':'Neck','children':[2]},
                    {'name':'Head','rotation':[0,.2588190451,0,.9659258263]}],
           'skins':[{'joints':[0,1,2]}]}
    assert abs(twists_from_json(doc)['head']-30)<1e-6
    doc['nodes'][1]['rotation'] = [0,.08715574275,0,.9961946981]
    measured = twists_from_json(doc)
    assert abs(measured['neck']-10)<1e-6
    assert abs(measured['head']-40)<1e-6
    # A parent matrix has the same composition as its TRS rotation.
    doc['nodes'][1].pop('rotation')
    doc['nodes'][1]['matrix'] = [.984807753,0,-.173648178,0, 0,1,0,0,
                               .173648178,0,.984807753,0, 0,0,0,1]
    assert abs(twists_from_json(doc)['head']-40)<1e-6
    def yaw(a):
        a=math.radians(a); return [[math.cos(a),0,math.sin(a)],[0,1,0],[-math.sin(a),0,math.cos(a)]]
    assert abs(twist_degrees(yaw(10),[0,0,1])-10)<1e-8
    assert abs(twist_degrees(yaw(40),[0,0,1])-40)<1e-8
    with tempfile.TemporaryDirectory(prefix='smoke-head-') as tmp:
        from app.core import paths
        paths.init(tmp)
        root = Path(tmp)
        photo = root/'tpose.png'; photo.write_bytes(b'original')
        meta = {'source_image_sha256':hashlib.sha256(b'original').hexdigest(),'created_at':'2100-01-01T00:00:00Z'}
        assert tpose_status('exact',meta,photo)=='current'
        photo.write_bytes(b'changed')
        assert tpose_status('exact',meta,photo)=='changed'
        assert tpose_status('exact',{},photo)=='unknown'
        assert tpose_status('nearest',meta,photo)=='other_outfit'
        photo.write_bytes(b'original')
        view = root/'side.png'; view.write_bytes(b'side')
        assert tpose_status('exact',{**meta, 'created_at':'2000-01-01T00:00:00Z',
                                     'view_images':{'side':'side.png'}},photo)=='changed'
        hashed = {**meta, 'view_images': {'side': 'side.png'},
                  'view_images_sha256': {'side': hashlib.sha256(b'side').hexdigest()}}
        assert tpose_status('exact',hashed,photo)=='current'
        view.write_bytes(b're-rendered side')
        os.utime(view, (1, 1))
        assert tpose_status('exact',hashed,photo)=='changed'
        view.unlink()
        assert tpose_status('exact',hashed,photo)=='changed'
        # Legacy meta (no view hashes): a recorded side view that is gone is stale too.
        assert tpose_status('exact',{**meta, 'view_images':{'side':'side.png'}},photo)=='changed'
        payload = json.dumps(doc).encode(); payload += b' '*((-len(payload))%4)
        glb = root/'json.glb'; glb.write_bytes(struct.pack('<4sIIII',b'glTF',2,20+len(payload),len(payload),0x4E4F534A)+payload)
        assert abs(read_head_twist(glb)['head']-40)<1e-6
        print('PASS pure twist math, GLB JSON reader, T-pose freshness/cache')
        st = runner.status()
        if not st['usable']:
            print('SKIP Blender:',st['error']); return
        script = root/'fixture.py'; script.write_text(FIXTURE)
        proc = subprocess.run([st['executable'],'-b','--factory-startup','--python-exit-code','1','--python',str(script),'--',tmp],capture_output=True,text=True,timeout=180)
        assert 'FIXTURES_OK' in proc.stdout, proc.stdout[-4000:]+proc.stderr[-2000:]
        print('PASS duplicate armature modifiers preserve geometry and pose')
        for angle in (0,30):
            source = root/f'{angle}.glb'
            res = runner.run('normalize',inputs={'model':source},params={'target_height_m':2},out_dir=root/f'out{angle}')
            assert res['ok'],res
            report = res['data']['head_twist']; print(angle,report)
            assert not report['error'],report
            assert report['corrected'] == bool(angle),report
            output = Path(res['outputs']['model'])
            assert abs(read_head_twist(output)['head'])<.5
            points = positions(output)
            # glTF Y up, Blender forward -Y maps to glTF +Z.
            nose = max(points,key=lambda p:p[2])
            assert max(abs(a-b) for a,b in zip(nose,(0,1.8,.2)))<.003,nose
            if angle==0:
                expected = [(x,y,z-.1) for x,y,z in positions(source)]
                assert len(expected)==len(points)
                assert max(min(max(abs(a-b) for a,b in zip(p,q)) for q in points) for p in expected)<1e-6
        print('PASS Blender corrected geometry, current twist, unchanged straight geometry')


if __name__=='__main__':
    main()
