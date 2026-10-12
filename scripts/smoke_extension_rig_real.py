"""Opt-in, read-only source check; every output stays in a temporary directory.

Usage: RUN_EXTENSION_RIG_REAL=1 .venv/bin/python scripts/smoke_extension_rig_real.py
       --model SOURCE.glb --declaration MANIFEST.yaml --group GROUP_ID
       [--contact-follow-distance .025 --contact-follow-weight .6 --out-dir /tmp/follow]
       [--normalize --target-height-m METRES]

The declaration is read unchanged. The first link is posed 70 degrees about
the armature-space lateral axis; both runs use the same contact-edge mask.
Version-7 example parameters are injected
into an in-memory copy; obsolete blend fields are removed there. All other
declaration values are preserved. Use --normalize
only for a raw source that has not already been normalized.

Hand derivation: at axial distance d from the measured stop, a grown part
has total weight smooth(d/min(weight_ramp*axis_length, attachment_ring_max)).
Thus the stop has zero weight and the completed ramp has unit weight. A
fixed -.3<=t<0 cylinder includes points behind that stop, separate surfaces,
and the zero-to-one ramp; requiring all of them to have weight >=.5 is false.
That broad cylinder remains a diagnostic only. A fixture with no eligible
contact followers has identical runs and requires no stretch reduction.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


FOLLOW_PROBE = r"""
import bpy, heapq, json, math, sys
from pathlib import Path
from mathutils import Vector, Quaternion
from mathutils.kdtree import KDTree
job=json.loads(Path(sys.argv[-1]).read_text())
g=job['group']; p=g['params']; m=job['metrics']; names={b['bone'] for b in g['chains'][0]}
scope={'__file__':job['operation']}
exec(Path(job['operation']).read_text().split('_common.main(')[0],scope)
station=scope['polyline_station']
joints=[Vector(m['placement'][0]['head'])]+[Vector(r['tip']) for r in m['placement']]
boundaries=[0]+p['chain_split']+[1]
base=Vector(m['segment_axis_base']); axis=(Vector(m['segment_axis_tip'])-base).normalized()
def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(md.type=='ARMATURE' for md in o.modifiers)]
    co=[]; weights=[]; edges=[]; faces=[]
    for mesh in meshes:
        off=len(co); indices={vg.index for vg in mesh.vertex_groups if vg.name in names}
        co.extend(mesh.matrix_world@v.co for v in mesh.data.vertices)
        weights.extend(sum(ge.weight for ge in v.groups if ge.group in indices) for v in mesh.data.vertices)
        edges.extend(tuple(i+off for i in e.vertices) for e in mesh.data.edges)
        faces.extend(tuple(i+off for i in f.vertices) for f in mesh.data.polygons)
    return arm,meshes,co,weights,edges,faces
def pose(arm,meshes,angle):
    pb=arm.pose.bones[g['chains'][0][0]['bone']]
    local_axis=arm.data.bones[pb.name].matrix_local.to_3x3().inverted()@Vector((1,0,0))
    pb.rotation_mode='QUATERNION'; pb.rotation_quaternion=Quaternion(local_axis,math.radians(-angle))
    bpy.context.view_layer.update()
    dg=bpy.context.evaluated_depsgraph_get(); co=[]
    for mesh in meshes:
        ev=mesh.evaluated_get(dg); data=ev.to_mesh()
        co.extend(mesh.matrix_world@v.co for v in data.vertices); ev.to_mesh_clear()
    return co
arm,meshes,co,ws,edges,faces=load(job['before'])
tube={i for i,w in enumerate(ws) if w>=.9}
outside={i for i in tube if station(co[i],joints,boundaries)[1]>p['attachment_ring_max']}
if m['base_extension_t']<0:
    outside={i for i in tube if (co[i]-Vector(m['attachment'])).dot(axis)>p['attachment_ring_max']}
contacts=[f for f in faces if any(i in outside for i in f) and any(ws[i]==0 for i in f)]
# The comparison mask includes every contact seed and its non-tube edge-path
# neighbourhood, even points excluded by ring/stop or nearest-distance guards.
seeds={i for f in contacts for i in f if ws[i]==0}
adj={}
for a,b in edges:
    adj.setdefault(a,[]).append(b); adj.setdefault(b,[]).append(a)
dist={i:0. for i in seeds}; queue=[(0.,i) for i in seeds]; heapq.heapify(queue)
while queue:
    d,i=heapq.heappop(queue)
    if d!=dist[i]: continue
    for j in adj.get(i,[]):
        nd=d+(co[i]-co[j]).length
        if ws[j]==0 and nd<=p['contact_follow_distance'] and nd<dist.get(j,float('inf')):
            dist[j]=nd; heapq.heappush(queue,(nd,j))
mask=[(a,b) for a,b in edges if (a in dist or b in dist) and (co[a]-co[b]).length>1e-6]
def stretch(posed):
    ratios=sorted((posed[a]-posed[b]).length/(co[a]-co[b]).length for a,b in mask)
    if not ratios: return {'max':1.,'p99':1.,'edges':0}
    return {'max':ratios[-1], 'p99':ratios[min(len(ratios)-1,int(.99*len(ratios)))], 'edges':len(ratios)}
before=stretch(pose(arm,meshes,70))
arm,meshes,after_co,after_ws,after_edges,after_faces=load(job['after'])
assert len(co)==len(after_co) and edges==after_edges and faces==after_faces, 'topology changed'
assert max((a-b).length for a,b in zip(co,after_co))<1e-6, 'rest geometry changed'
assert all(abs(w-after_ws[i])<1e-6 for i,w in enumerate(ws) if w>0), 'tube weights changed'
after=stretch(pose(arm,meshes,70))
kd=KDTree(len(tube))
for i in sorted(tube): kd.insert(co[i],i)
kd.balance()
far_max=max((w for i,w in enumerate(after_ws) if kd.find(co[i])[2]>p['contact_follow_distance']+1e-6),default=0.)
above=sum(w>1e-6 for c,w in zip(co,after_ws) if (c-base).dot(axis)/m['segment_axis_length']<m['base_extension_t']-1e-6)
# Existing independent hidden-stem criterion: -.3<=t<0 inside 1.1*R.
hidden=[i for i,c in enumerate(co) if -.3<=(c-base).dot(axis)/m['segment_axis_length']<0
        and (c-base-axis*(c-base).dot(axis)).length<=1.1*m['segment_radius']]
summary={'before':before,'after':after,'max_reduction':1-after['max']/before['max'],
         'contact_faces_outside_ring':len(contacts),'contact_tissue_vertices':len(dist),
         'far_chain_weight_max':far_max,'above_stop_weighted':above,
         'hidden_stem_total':len(hidden),'hidden_stem_weighted':sum(after_ws[i]>=.5 for i in hidden),
         'topology_unchanged':True,'tube_weights_unchanged':True}
Path(job['report']).write_text(json.dumps(summary,indent=2))
assert far_max==0 and above==0, summary
if m['base_extension_t']<0:
    ramp=min(p['weight_ramp']*m['axis_length'],p['attachment_ring_max'])
    # smooth'(x)<=1.5: a one-micrometre position roundtrip allows 1.5e-6/ramp.
    tolerance=max(1e-5,1.5e-6/ramp)
    checked=0
    for c,w in zip(co,ws):
        if w<=0: continue
        distance=max(0.,(c-Vector(m['attachment'])).dot(axis))
        fraction=min(1.,distance/ramp)
        expected=fraction*fraction*(3-2*fraction)
        assert abs(w-expected)<tolerance, (distance,w,expected)
        checked+=1
    assert checked and m['stem_vertices_captured']>0, summary
if job['renders']:
    scene=bpy.context.scene; scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=640; scene.render.resolution_y=640; scene.render.resolution_percentage=100
    scene.world=bpy.data.worlds.new('Background')
    scene.display.shading.color_type='VERTEX'
    for mesh in meshes:
        indices={vg.index for vg in mesh.vertex_groups if vg.name in names}
        colour=mesh.data.color_attributes.new('follow_weight','FLOAT_COLOR','POINT')
        for v in mesh.data.vertices:
            w=sum(ge.weight for ge in v.groups if ge.group in indices)
            colour.data[v.index].color=(min(1,2*w),.15,max(0,1-2*w),1)
    focus=joints[0]+Vector((0,0,-.02))
    views={'front':(0,-.38,.02),'side':(-.38,0,.02),'below':(.12,-.22,-.28)}
    cameras={}
    for view,offset in views.items():
        data=bpy.data.cameras.new(view); cam=bpy.data.objects.new(view,data); bpy.context.collection.objects.link(cam)
        cam.location=focus+Vector(offset); cam.rotation_euler=(focus-cam.location).to_track_quat('-Z','Y').to_euler(); cameras[view]=cam
    for angle in (0,70):
        pose(arm,meshes,angle)
        for view,cam in cameras.items():
            scene.camera=cam; scene.render.filepath=str(Path(job['renders'])/('follow_%s_%s.png'%(angle,view)))
            bpy.ops.render.render(write_still=True)
    scene.render.engine='BLENDER_EEVEE_NEXT'; scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.8
    for name,offset,power in [('Key',(-.25,-.3,.3),35),('Fill',(.2,-.15,.1),15)]:
        data=bpy.data.lights.new(name,'AREA'); data.energy=power; data.size=.3
        light=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(light)
        light.location=focus+Vector(offset); light.rotation_euler=(focus-light.location).to_track_quat('-Z','Y').to_euler()
    scene.camera=cameras['side']; scene.render.filepath=str(Path(job['renders'])/'follow_70_side_tex.png')
    bpy.ops.render.render(write_still=True)
print(json.dumps(summary,sort_keys=True))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--declaration', type=Path, required=True)
    parser.add_argument('--group', required=True)
    parser.add_argument('--contact-follow-distance', type=float, default=.025)
    parser.add_argument('--contact-follow-weight', type=float, default=.6)
    parser.add_argument('--out-dir', type=Path, help='Keep report, models and seven renders here')
    parser.add_argument('--normalize', action='store_true')
    parser.add_argument('--target-height-m', type=float)
    args = parser.parse_args()
    if os.environ.get('RUN_EXTENSION_RIG_REAL') != '1':
        parser.error('requires RUN_EXTENSION_RIG_REAL=1')
    if args.normalize and (args.target_height_m is None or args.target_height_m <= 0):
        parser.error('--normalize requires positive --target-height-m')
    import yaml
    manifest = yaml.safe_load(args.declaration.read_text())
    matches = [slot['rig'] for slot in manifest.get('body_slots', [])
               if (slot.get('rig') or {}).get('id') == args.group]
    if len(matches) != 1:
        parser.error('expected one matching rig declaration')
    group = copy.deepcopy(matches[0])
    group['params'].update(segment_radius_factor=1.35, contact_ramp=.01,
                           segment_min_vertices=3, segment_radius_percentile=.95,
                           segment_radius_margin=1.2, segment_radius_growth_max=1.5,
                           segment_passes=3, base_slice_size=.01, base_radius_margin=1.8,
                           base_growth_max=1.8, base_extension_max=.35, base_history_slices=5,
                           attachment_ring_max=.01, weld_normal_min=.5,
                           centerline_slab=.08, link_blend=.06,
                           contact_follow_distance=args.contact_follow_distance,
                           contact_inside_distance=0.,
                           contact_follow_weight=args.contact_follow_weight)
    group['params'].pop('blend_start', None)
    group['params'].pop('blend_width', None)
    source_hash = hashlib.sha256(args.model.read_bytes()).hexdigest()
    declaration_hash = hashlib.sha256(args.declaration.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='extension-real-') as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root/'storage')
        os.environ['ANIMATION_CLIPS_DIR'] = str(root/'clips')
        os.environ['ANIMATION_RIG_FILE'] = str(root/'reference.fbx')
        from app.blender import runner
        source = root/'source.glb'
        shutil.copy2(args.model, source)
        if args.normalize:
            result = runner.run('normalize', inputs={'model': source},
                                params={'target_height_m': args.target_height_m},
                                out_dir=root/'normalized', timeout_s=180)
            if not result['ok']:
                raise RuntimeError(result['error'])
            source = Path(result['outputs']['model'])
        baseline_group = copy.deepcopy(group)
        baseline_group['params']['contact_follow_weight'] = 0
        baseline = runner.run('extension_bones', inputs={'model': source},
                              params={'groups': [baseline_group]}, out_dir=root/'baseline', timeout_s=600)
        if not baseline['ok'] or baseline['data'].get('status') != 'applied':
            raise RuntimeError(json.dumps(baseline))
        result = runner.run('extension_bones', inputs={'model': source},
                            params={'groups': [group]}, out_dir=root/'output',
                            timeout_s=600)
        if not result['ok'] or result['data'].get('status') != 'applied':
            raise RuntimeError(json.dumps(result))
        print(json.dumps(result['data']['metrics'][args.group], indent=2, sort_keys=True))
        for key in ('thigh_weight_in_part', 'uncaptured_in_part',
                    'captured_outside_base_tube', 'partial_outside_attachment_ring',
                    'captured_beyond_tube_radius', 'weighted_outside_part'):
            assert result['data']['metrics'][args.group][key] == 0, key
        output = args.out_dir or root/'probe'
        output.mkdir(parents=True, exist_ok=True)
        (output/'follow_metrics.json').write_text(json.dumps(result['data']['metrics'][args.group],indent=2))
        (output/'follow_params.json').write_text(json.dumps(group['params'],indent=2))
        before = output/'follow_before.glb'; after = output/'follow_after.glb'
        shutil.copy2(baseline['outputs']['model'], before)
        shutil.copy2(result['outputs']['model'], after)
        probe = root/'probe.py'; probe.write_text(FOLLOW_PROBE)
        job = root/'probe.json'
        job.write_text(json.dumps({'group':group, 'metrics':result['data']['metrics'][args.group],
                                  'operation':str(runner.SCRIPTS_DIR/'extension_bones.py'),
                                  'before':str(before), 'after':str(after),
                                  'report':str(output/'follow_report.json'),
                                  'renders':str(output) if args.out_dir else ''}))
        run = subprocess.run(['timeout','900',runner.find_executable(),'--background',
                              '--factory-startup','--python-exit-code','1','--python',str(probe),'--',str(job)],
                             capture_output=True,text=True,timeout=900)
        if run.returncode:
            raise RuntimeError(run.stdout[-4000:]+run.stderr[-4000:])
        report=json.loads((output/'follow_report.json').read_text())
        print(json.dumps(report,indent=2,sort_keys=True))
    assert hashlib.sha256(args.model.read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256(args.declaration.read_bytes()).hexdigest() == declaration_hash
    print('PASS real source and declaration unchanged; outputs stayed outside source storage')
    if result['data']['metrics'][args.group]['contact_tissue_vertices_weighted']:
        assert report['max_reduction'] >= .5, 'contact stretch reduction below 50 percent'
        print('PASS contact stretch reduction >=50 percent')
    else:
        assert report['before']==report['after'], 'runs without followers must have identical stretch'
        print('PASS no eligible contact followers; identical comparison runs')


if __name__ == '__main__':
    main()
