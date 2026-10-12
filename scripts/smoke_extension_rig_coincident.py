"""Offline crease-copy regression; inputs stay unchanged and outputs are temporary.

Usage: .venv/bin/python scripts/smoke_extension_rig_coincident.py
       [--model-l2 FIXTURE.glb --model-p FIXTURE.glb --model-m FIXTURE.glb]
       [--declaration MANIFEST.yaml --group GROUP]
       [--normalize --target-height-m 1.86]

Part A builds and imports a real skinned GLB through the runner. A vertical
tube side and horizontal body strip meet at separate copies with perpendicular
normals; no face spans the copies. The supplied analytic plan isolates weight
application from segmentation. With distance 20 mm and weight .6, the body
copy seeds d=0: total .6. At 5 mm smooth(3/4)=27/32 gives .50625;
at 10 mm smooth(1/2)=1/2 gives .3. Tube link shares are 3/4 and 1/4.
Original body weights .4,.35,.25 compete for two slots, keeping the ratio
8:7. At the crease the tube exports (.75,.25), the body copy exports
(.45,.15,.4*8/15,.4*7/15). Their average is therefore Chain1=.6,
Chain2=.2, Body1=8/75, Body2=7/75, on BOTH copies.

Four additional changed groups isolate the final export rule: pure Body1
and pure Body2 average to .5 each, even with zero chain weight; two disjoint
four-body sets of .25 average to eight .125 shares, whose top four tie by
lower joint index and normalize to .25 each; a captured partial tube with
total .5 transfers its original body weights to Anchor before applying the
chain. Averaging (Anchor=.5, Chain1=.375, Chain2=.125) with pure Body3
gives Body3=.5, Anchor=.25, Chain1=.1875, Chain2=.0625. Three copies with
{A:.5,B:.5}, {A:.5,D:.4375,E:.0625}, {C:.5,D:.0625,E:.4375}, where
A=Body1 through E=Body5 and joint indices A<B<C<D<E, have sums A=1 and
B=C=D=E=.5. Keeping A,B,C,D by lower joint index gives total 2.5, hence
exported shares A=2/5, B=C=D=1/5 on all three copies. Thus the global
changed-group count is FIVE, including the three groups with no chain weight.
A separate already-agreeing crease retains its exported bytes. A variant
with no contact and only agreeing copies must match pinned old export bytes.
Checks also cover the 10 micrometre fixed epsilon, ring/axis eligibility,
outside full-tube seeding, disabled following and deterministic input order.

Part B accepts optional P/M/L2 fixture paths, with a clear skip when missing.
It runs the pinned e8d512db implementation from a temporary script export.
P/M exported JOINTS_0/WEIGHTS_0 accessor bytes must remain bit-identical.
L2 must have zero coincident groups with different exported weights and zero
copy gaps above .1 mm at root local-X rotations -90,-60,+60,+90 degrees.
Pose evaluation uses Blender's dependency graph, as measure() does. Reports
include before/after differing groups, maximum posed gap and test-pose edge
stretch. Analytic expectations above are hand-derived, never recorded output.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
BASELINE_COMMIT = 'e8d512db'

PROBE = r'''
import bpy, copy, itertools, json, math, struct, sys
from pathlib import Path
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(job['params']['operation'])
def load_scope(path):
    scope={'__file__':str(path)}
    # Each implementation uses its own sibling boilerplate from the export.
    cached=sys.modules.pop('_common',None)
    try:
        exec(compile(Path(path).read_text().split('_common.main(')[0],str(path),'exec'),scope)
    finally:
        sys.modules.pop('_common',None)
        if cached is not None:
            sys.modules['_common']=cached
    return scope
scope=load_scope(source)
baseline=load_scope(job['params']['baseline_operation'])

def skin_bytes(path):
    blob=Path(path).read_bytes(); size=struct.unpack_from('<I',blob,12)[0]
    doc=json.loads(blob[20:20+size]); binary=blob[28+size:]
    result=[]
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            for name in ('JOINTS_0','WEIGHTS_0'):
                a=doc['accessors'][primitive['attributes'][name]]
                view=doc['bufferViews'][a['bufferView']]
                width={5121:1,5123:2,5126:4}[a['componentType']]*4
                start=view.get('byteOffset',0)+a.get('byteOffset',0)
                stride=view.get('byteStride',width)
                result.append((name,a['componentType'],a['count'],b''.join(
                    binary[start+i*stride:start+i*stride+width] for i in range(a['count']))))
    return result

def scene_data():
    arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH'
            and any(md.type=='ARMATURE' and md.object==arm for md in o.modifiers)]
    co=[]; weights=[]
    for mesh in meshes:
        co.extend(mesh.matrix_world@v.co for v in mesh.data.vertices)
        weights.extend({mesh.vertex_groups[g.group].name:g.weight
                        for g in v.groups if g.weight>0} for v in mesh.data.vertices)
    return arm,meshes,co,weights

def coincident_groups(co):
    # Independent spatial-grid connected components, rather than the operation's KDTree.
    epsilon=1e-5; cells={}; parent=list(range(len(co)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]; i=parent[i]
        return i
    for i,point in enumerate(co):
        cell=tuple(math.floor(v/epsilon) for v in point)
        for delta in itertools.product((-1,0,1),repeat=3):
            for j in cells.get(tuple(a+b for a,b in zip(cell,delta)),()):
                if (point-co[j]).length<=epsilon:
                    a,b=root(i),root(j); parent[max(a,b)]=min(a,b)
        cells.setdefault(cell,[]).append(i)
    groups={}
    for i in range(len(co)):
        groups.setdefault(root(i),[]).append(i)
    return [g for g in groups.values() if len(g)>1]

def evaluate(meshes):
    bpy.context.view_layer.update(); dg=bpy.context.evaluated_depsgraph_get(); out=[]
    for mesh in meshes:
        ev=mesh.evaluated_get(dg); data=ev.to_mesh()
        out.extend(mesh.matrix_world@v.co for v in data.vertices); ev.to_mesh_clear()
    return out

def exported_report(path,group):
    scope['_common'].reset_scene(); scope['_common'].import_model(str(path))
    arm,meshes,co,weights=scene_data(); groups=coincident_groups(co)
    differing=sum(any(weights[i]!=weights[g[0]] for i in g[1:]) for g in groups)
    differing_pairs=sum(weights[a]!=weights[b] for g in groups
                        for a,b in itertools.combinations(g,2))
    gaps={}; above={}
    root=arm.pose.bones[group['chains'][0][0]['bone']]; root.rotation_mode='XYZ'
    for degrees in (-90,-60,60,90):
        root.rotation_euler=(math.radians(degrees),0,0)
        posed=evaluate(meshes)
        distances=[max((posed[a]-posed[b]).length for a,b in itertools.combinations(g,2))
                   for g in groups]
        gaps[str(degrees)]=max(distances,default=0.)*1000
        above[str(degrees)]=sum(d>.0001 for d in distances)
    root.rotation_euler=(0,0,0); bpy.context.view_layer.update()
    return {'coincident_groups':len(groups),'differing_groups':differing,
            'differing_pairs':differing_pairs,
            'max_gap_mm_by_root_deg':gaps,'groups_gap_gt_point1_mm':above,
            'weights_sha256':__import__('hashlib').sha256(repr(skin_bytes(path)).encode()).hexdigest()}

def run(implementation,model,group,label,planner=None):
    out=Path(job['out_dir'])/label; out.mkdir()
    original_plan=implementation['appendage_plan']; original_measure=implementation['measure']
    snapshot={}
    def measured(arm,meshes,edges,plans):
        snapshot['final_weights']=copy.deepcopy(plans[0][2][1])
        if planner is not None:
            # Analytic placement has no segmentation diagnostics; poses are
            # evaluated independently after importing the exported GLB below.
            return {g['id']:copy.deepcopy(plan[2]) for g,_,plan in plans}
        return original_measure(arm,meshes,edges,plans)
    if planner is not None:
        implementation['appendage_plan']=planner
    implementation['measure']=measured
    try:
        data,outputs=implementation['extension_bones']({'inputs':{'model':str(model)},
            'params':{'groups':[group]},'out_dir':str(out)})
    finally:
        implementation['appendage_plan']=original_plan; implementation['measure']=original_measure
    assert data['status']=='applied', data
    return Path(outputs['model']),data['metrics'][group['id']],snapshot

def analytic_fixture(noop=False):
    scope['_common'].reset_scene()
    data=bpy.data.armatures.new('AnchorRig'); arm=bpy.data.objects.new('AnchorRig',data)
    bpy.context.collection.objects.link(arm); bpy.context.view_layer.objects.active=arm
    arm.select_set(True); bpy.ops.object.mode_set(mode='EDIT')
    for name,head in [('Anchor',(0,0,0)),('Up',(0,0,1)),('Left',(1,0,0)),
                      ('Right',(-1,0,0)),('Front',(0,-1,0))]+[
                      ('Body'+str(i),(0,0,0)) for i in range(1,9)]:
        bone=data.edit_bones.new(name); bone.head=head; bone.tail=Vector(head)+Vector((0,0,.05))
    bpy.ops.object.mode_set(mode='OBJECT')
    points=[]; faces=[]; initial=[]
    body={'Body1':.4,'Body2':.35,'Body3':.25}
    def polygon(co,weights):
        off=len(points); points.extend(co); faces.append(tuple(range(off,len(points))))
        initial.extend(dict(weights) for _ in co)
    polygon([(0,0,.04),(0,0,.06),(0,.002,.06),(0,.002,.04)],body)
    start=.03 if noop else 0.
    off=len(points)
    points.extend((x,y,.04) for x in (start,start+.005,start+.01,start+.025) for y in (0,-.002))
    initial.extend(dict(body) for _ in range(8))
    faces.extend((off+2*i,off+2*i+2,off+2*i+3,off+2*i+1) for i in range(3))
    for x in (.1,.2):
        polygon([(x,0,.04),(x+.002,0,.04),(x,.002,.04)],body)
    for x,first,second in ((.3,body,body),(.4,{'Body1':1.},{'Body2':1.}),
            (.5,{f'Body{i}':.25 for i in range(1,5)},{f'Body{i}':.25 for i in range(5,9)})):
        polygon([(x,0,.04),(x+.002,0,.04),(x,.002,.04)],first)
        polygon([(x,0,.04),(x,0,.042),(x+.002,0,.042)],first if noop else second)
    if not noop:
        polygon([(.6,0,.04),(.602,0,.04),(.6,.002,.04)],body)
        polygon([(.6,0,.04),(.6,0,.042),(.602,0,.042)],{'Body3':1.})
        polygon([(.7,0,.04),(.702,0,.04),(.7,.002,.04)],{'Body1':.5,'Body2':.5})
        polygon([(.7,0,.04),(.7,0,.042),(.702,0,.042)],
                {'Body1':.5,'Body4':.4375,'Body5':.0625})
        polygon([(.7,0,.04),(.7,-.002,.04),(.702,-.002,.04)],
                {'Body3':.5,'Body4':.0625,'Body5':.4375})
    mesh_data=bpy.data.meshes.new('Surface'); mesh_data.from_pydata(points,[],faces); mesh_data.update()
    mesh=bpy.data.objects.new('Surface',mesh_data); bpy.context.collection.objects.link(mesh)
    mesh.modifiers.new('Skin','ARMATURE').object=arm
    for i,values in enumerate(initial):
        for name,value in values.items():
            vg=mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
            vg.add([i],value,'REPLACE')
    output=Path(job['out_dir'])/('noop.glb' if noop else 'crease.glb')
    bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',export_all_influences=False)
    return output

p={'contact_inside_distance':.02,'contact_follow_distance':.02,'contact_follow_weight':.6,
   'weld_distance':.0005,'attachment_ring_max':.01,'chain_split':[.5],
   'up_from_bone':'Anchor','up_to_bone':'Up','up_distance_min':.1,'up_distance_max':2.,
   'lateral_positive_bone':'Left','lateral_negative_bone':'Right',
   'front_from_bone':'Anchor','front_to_bone':'Front','front_distance_min':.1,
   'reweight_from':['Body1','Body2','Body3'],'test_rotation_deg':[-35,0,0],
   'test_rotation_decay':.4,'test_scale':[1,1,1]}
group={'id':'example_chain','op':'appendage_chain','chains':[[
    {'bone':'Chain1','parent':'Anchor'},{'bone':'Chain2','parent':'Chain1'}]]}
m={'leak':False,'base_extension_t':0.,'segment_axis_base':[0,0,0],
   'segment_axis_tip':[0,0,.1],'segment_axis_length':.1,'attachment':[0,0,0],
   'weight_joints':[[0,0,0],[0,0,.05],[0,0,.1]],
   'placement':[{'head':[0,0,0],'tip':[0,0,.05]},{'head':[0,0,.05],'tip':[0,0,.1]}]}
links=[('Chain1',Vector((0,0,0)),Vector((0,0,.05)),'Anchor'),
       ('Chain2',Vector((0,0,.05)),Vector((0,0,.1)),'Chain1')]

def planned(g,params,co,edges,bones,normals,faces):
    tube={i for i,v in enumerate(co) if v.x<.001 and normals[i].x<-.9
          or .099<v.x<.103 or .199<v.x<.203 or .599<v.x<.603 and normals[i].z>.9}
    weights={'Chain1':{},'Chain2':{}}
    for i in tube:
        a,b=(1.,0.) if .099<co[i].x<.103 else ((0.,1.) if .199<co[i].x<.203 else (.75,.25))
        total=.5 if co[i].x>.59 else 1.
        weights['Chain1'][i]=a*total; weights['Chain2'][i]=b*total
    return copy.deepcopy(links),weights,copy.deepcopy(m),tube,params['reweight_from']

def inspect_follow(implementation,model):
    implementation['_common'].reset_scene(); implementation['_common'].import_model(str(model))
    arm,meshes,co,_=scene_data(); normals=[]; edges=[]; faces=[]
    for mesh in meshes:
        off=len(normals); normals.extend(v.normal.copy() for v in mesh.data.vertices)
        edges.extend(tuple(off+i for i in e.vertices) for e in mesh.data.edges)
        faces.extend(tuple(off+i for i in f.vertices) for f in mesh.data.polygons)
    plan=planned(group,p,co,edges,{},normals,faces)
    follow,count=implementation['contact_follow_weights'](p,co,edges,faces,plan)
    assert count==0, ('unexpected shared contact face',count)
    for x,total in ((0.,.6),(.005,.50625),(.01,.3)):
        ids=[i for i,v in enumerate(co) if (v-Vector((x,0,.04))).length<1e-7 and i not in plan[3]]
        assert ids, ('body strip copy missing',x)
        for i in ids:
            actual=sum(w.get(i,0.) for w in follow.values())
            assert abs(actual-total)<2e-7, ('coincident follower',x,actual,total)
            assert abs(follow['Chain1'][i]-.75*total)<2e-7
            assert abs(follow['Chain2'][i]-.25*total)<2e-7
    reversed_follow,reversed_count=implementation['contact_follow_weights'](
        p,co,list(reversed(edges)),list(reversed(faces)),plan)
    assert follow==reversed_follow and count==reversed_count
    return follow

def guard_checks():
    # Independent points isolate fixed epsilon and the existing eligibility rule.
    co=[Vector(v) for v in ((0,0,.04),(0,0,.005),(0,0,-.001),
                           (.000009,0,.04),(.000011,0,.04),(0,0,.005),(0,0,-.001))]
    plan=(links,{'Chain1':{0:1.,1:1.,2:1.}},copy.deepcopy(m),{0,1,2},[])
    values,count=scope['contact_follow_weights'](p,co,[],[],plan)
    assert count==0 and set(values['Chain1'])=={3}, ('epsilon/ring/axis guards',values)
    partial=copy.deepcopy(plan); partial[1]['Chain1'][0]=.89
    assert not any(scope['contact_follow_weights'](p,co,[],[],partial)[0].values())
    assert not any(scope['contact_follow_weights'](dict(p,contact_follow_weight=0.),co,[],[],plan)[0].values())

def analytic():
    model=analytic_fixture(); follow=inspect_follow(scope,model); guard_checks()
    try:
        inspect_follow(baseline,model)
    except AssertionError as exc:
        assert exc.args[0][:2]==('coincident follower',0.), str(exc)
    else:
        raise AssertionError('pinned old code passed coincident follower check')
    saved=scope['parameters']; old_saved=baseline['parameters']
    scope['parameters']=lambda g:copy.deepcopy(p); baseline['parameters']=lambda g:copy.deepcopy(p)
    try:
        output,metrics,snapshot=run(scope,model,group,'analytic-current',planned)
        old,_,_=run(baseline,model,group,'analytic-old',planned)
        scope['_common'].reset_scene(); scope['_common'].import_model(str(output))
        _,_,co,weights=scene_data()
        for x,expected,count in ((0.,{'Chain1':.6,'Chain2':.2,'Body1':8/75,'Body2':7/75},2),
                (.4,{'Body1':.5,'Body2':.5},2),
                (.5,{f'Body{i}':.25 for i in range(1,5)},2),
                (.6,{'Body3':.5,'Anchor':.25,'Chain1':.1875,'Chain2':.0625},2),
                (.7,{'Body1':2/5,'Body2':1/5,'Body3':1/5,'Body4':1/5},3)):
            copies=[i for i,v in enumerate(co) if (v-Vector((x,0,.04))).length<1e-7]
            assert len(copies)==count, ('crease copies',x,copies)
            for i in copies:
                actual=weights[i]
                assert actual.keys()==expected.keys() and all(abs(actual[k]-v)<2e-7 for k,v in expected.items()), (
                    'exported average',x,actual,expected)
            assert all(weights[i]==weights[copies[0]] for i in copies[1:]), ('exported copies differ',x)
        assert metrics['coincident_groups_unified']==5, metrics
        for x,total in ((.005,.50625),(.01,.3)):
            copies=[i for i,v in enumerate(co) if (v-Vector((x,0,.04))).length<1e-7]
            assert copies, ('exported follower missing',x)
            for i in copies:
                assert abs(weights[i]['Chain1']-.75*total)<2e-7
                assert abs(weights[i]['Chain2']-.25*total)<2e-7
        # Counts must use unified values, including the formerly pure body copy.
        # GLB order may change: compare totals as a multiset across all original vertices.
        for name in ('Chain1','Chain2'):
            assert sorted(round(v,6) for v in snapshot['final_weights'][name].values())==sorted(
                round(w[name],6) for w in weights if name in w), ('stale final_weights',name)
        agreed=[w for v,w in zip(co,weights) if (v-Vector((.3,0,.04))).length<1e-7]
        scope['_common'].reset_scene(); scope['_common'].import_model(str(old))
        _,_,old_co,old_weights=scene_data()
        assert agreed==[w for v,w in zip(old_co,old_weights) if (v-Vector((.3,0,.04))).length<1e-7], 'agreeing group changed'
        old_report=exported_report(old,group); report=exported_report(output,group)
        assert old_report['differing_groups']>0 and old_report['max_gap_mm_by_root_deg']['90']>.1, old_report
        assert report['differing_groups']==0 and not any(report['groups_gap_gt_point1_mm'].values()), report
        noop=analytic_fixture(noop=True)
        current_noop,noop_metrics,_=run(scope,noop,group,'noop-current',planned)
        old_noop,_,_=run(baseline,noop,group,'noop-old',planned)
        assert skin_bytes(current_noop)==skin_bytes(old_noop), 'no-op exported weights changed'
        assert noop_metrics['coincident_groups_unified']==0, noop_metrics
        return {'analytic':True,'baseline_commit':job['params']['baseline_commit'],
                'before':old_report,'after':report,'coincident_groups_unified':5,
                'noop_bit_identical':True,'agreeing_group_unchanged':True}
    finally:
        scope['parameters']=saved; baseline['parameters']=old_saved

if 'model' not in job['inputs']:
    summary=analytic()
else:
    g=job['params']['group']; label=job['params']['label']
    model=Path(job['inputs']['model'])
    old,old_metrics,_=run(baseline,model,g,'pinned')
    output,metrics,_=run(scope,model,g,'current')
    before=exported_report(old,g); after=exported_report(output,g)
    if label in ('P','M'):
        assert skin_bytes(old)==skin_bytes(output), ('P/M exported weights changed',label)
        assert metrics['coincident_groups_unified']==0, metrics
    else:
        assert before['differing_groups']>0, ('pinned L2 did not reproduce tear',before)
        assert after['differing_groups']==0, after
        assert not any(after['groups_gap_gt_point1_mm'].values()), after
    for report,metric in ((before,old_metrics),(after,metrics)):
        report['edge_stretch_p01_p50_p99_max']=metric['edge_stretch_p01_p50_p99_max']
        report['coincident_groups_unified']=metric.get('coincident_groups_unified',0)
        report['contact_tissue_vertices_weighted']=metric['contact_tissue_vertices_weighted']
    summary={'label':label,'baseline_commit':job['params']['baseline_commit'],
             'before':before,'after':after,'weights_bit_identical':skin_bytes(old)==skin_bytes(output)}
Path(job['result']).write_text(json.dumps({'ok':True,'data':summary,'outputs':{}}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for label in ('l2', 'p', 'm'):
        parser.add_argument('--model-' + label, type=Path)
    parser.add_argument('--declaration', type=Path)
    parser.add_argument('--group')
    parser.add_argument('--normalize', action='store_true')
    parser.add_argument('--target-height-m', type=float, default=1.86)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='extension-coincident-') as tmp:
        root = Path(tmp)
        os.environ['STORAGE_DIR'] = str(root / 'storage')
        os.environ['INSTANCE_DIR'] = str(root / 'instance')
        from app.core import paths
        paths.init(root / 'storage'); paths.init_instance(root / 'instance')
        from app.blender import runner
        operation = runner.SCRIPTS_DIR / 'extension_bones.py'
        scripts = root / 'scripts'; scripts.mkdir()
        (scripts / 'probe.py').write_text(PROBE)
        # Export both scripts from the pinned commit; never use HEAD as baseline.
        for name in ('extension_bones.py', '_common.py'):
            (scripts / name).write_text(subprocess.check_output(
                ['git', 'show', BASELINE_COMMIT + ':app/blender/scripts/' + name],
                cwd=Path(__file__).resolve().parents[1], text=True))
        params = {'operation': str(operation),
                  'baseline_operation': str(scripts / 'extension_bones.py'),
                  'baseline_commit': BASELINE_COMMIT}
        def probe(inputs, extra, destination):
            original = runner.SCRIPTS_DIR
            runner.SCRIPTS_DIR = scripts
            try:
                result = runner.run('probe', inputs=inputs, params={**params, **extra},
                                    out_dir=destination, timeout_s=600)
            finally:
                runner.SCRIPTS_DIR = original
            assert result['ok'], result
            return result['data']
        print('PASS Part A', json.dumps(probe({}, {}, root / 'analytic'), sort_keys=True))
        for label in ('p', 'm', 'l2'):
            fixture = getattr(args, 'model_' + label)
            if fixture is None or not fixture.is_file():
                print('SKIP Part B ' + label.upper() + ': fixture missing')
                continue
            if args.declaration is None or not args.group:
                parser.error('present fixtures require --declaration and --group')
            import yaml
            manifest = yaml.safe_load(args.declaration.read_text())
            group = next(copy.deepcopy(s['rig']) for s in manifest['body_slots']
                         if (s.get('rig') or {}).get('id') == args.group)
            group.update(enabled=True, flip=False)
            originals = (fixture, args.declaration)
            hashes = [hashlib.sha256(p.read_bytes()).digest() for p in originals]
            model = fixture
            if args.normalize:
                normalized = runner.run('normalize', inputs={'model': fixture},
                    params={'target_height_m': args.target_height_m},
                    out_dir=root / ('normalized-' + label), timeout_s=180)
                assert normalized['ok'], normalized
                model = Path(normalized['outputs']['model'])
            data = probe({'model': model}, {'group': group, 'label': label.upper()},
                         root / ('fixture-' + label))
            assert hashes == [hashlib.sha256(p.read_bytes()).digest() for p in originals]
            print('PASS Part B ' + label.upper(), json.dumps(data, sort_keys=True))


if __name__ == '__main__':
    main()
