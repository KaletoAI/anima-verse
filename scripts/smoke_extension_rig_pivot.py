"""Offline chord-pivot check; source fixtures stay unchanged, outputs are temporary.

Usage: .venv/bin/python scripts/smoke_extension_rig_pivot.py
       --model FIXTURE.glb --declaration MANIFEST.yaml --group GROUP
       [--target-height-m 1.86]

Part A, hand derivation in (y,z): F=(0,.03), K=(.08,0), anchor=(.04,.1)
is on the inward side. The chord is .03*y+.08*z=.0024, so signed distance
is (.03*y+.08*z-.0024)/sqrt(.03**2+.08**2). At A=(0,-.01), the numerator
is -.0032. Along u=(1,1)/sqrt(2), it increases by .11*s/sqrt(2).
For root_depth=.03 and margin=.01, the smallest satisfying depth is
s=(.0032+.01*sqrt(.0073))*sqrt(2)/.11=.05212534542684875 m.
At root_depth=.06 the margin already holds, so s=.06. A target .04 m
from A caps the first case at .04, leaving margin below .01. Missing
endpoints or a chord parallel to u must retain the declared .03 depth.
Plane cuts and clipped segment endpoints also check F on triangles.
A box spans y=[-.06,-.02], z=[-.08,0]. A +Y ray from (0,-.04,-.03)
exits at E=(0,-.02,-.03). From Q=(0,-.018,-.03), +Z hits a roof
z=.04+.5*(y+.04) at H=(0,-.018,.051). Its connected contour rises
to K=(0,.04,.08), then falls before a higher distant peak. A separate
roof at z=.15 cannot change this local maximum. Shared edges and
coincident seam copies both connect the contour.
Review cases additionally isolate a closer disconnected strip, an outside
entry before the exit, a 1 mm blocked gap, a flat ledge with a cycle and a
self-neighbour, and a 30 mm fallback capped by a 20 mm anchor distance.

Part B normalizes to 1.86 m and compares the real appendage_plan against
the pinned 76767576 planner on the same fixture: weights, affected set,
attachment and every head after the first agree within 1e-9. It also compares
weights, membership, internal joints, tip and axis length against an
unmoved pivot (root_depth=0, root_wall_margin=-1 in memory only). Every
root must equal A+s*u within 1e-6 m, meet the declared margin, and use F
in front of A and K behind A. Measure signed distance from the actual head
independently of the solver's margin metric, and compare contact followers
as well as part weights. A full extension run also reports edge stretch.
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
BASELINE_COMMIT = '76767576'

PROBE = r'''
import bpy, json, math, sys
from pathlib import Path
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(job['params']['operation'])
scope={'__file__':str(source)}
exec(compile(source.read_text().split('_common.main(')[0],str(source),'exec'),scope)
solve=scope['solve_pivot']
A=Vector((0,0,-.01)); F=Vector((0,0,.03)); K=Vector((0,.08,0))
anchor=Vector((0,.04,.1)); target=A+Vector((0,.2,0))
p={'root_depth':.03,'root_wall_margin':.01}
head,m=solve(A,F,K,anchor,target,p)
assert abs(m['depth']-.05212534542684875)<1e-8, m
assert abs(m['margin']-.01)<1e-8 and not m['capped'] and m['reason']=='', m
head,m=solve(A,F,K,anchor,target,dict(p,root_depth=.06))
assert abs(m['depth']-.06)<1e-9 and m['margin']>.01, m
head,m=solve(A,F,K,anchor,A+Vector((0,.04,0)),p)
assert abs(m['depth']-.04)<1e-8 and m['capped'] and m['margin']<.01, m
for f,k in ((None,K),(F,None),(Vector(),Vector((0,.08,.08)))):
    head,m=solve(A,f,k,anchor,target,p)
    assert m['depth']==.03 and m['reason'] and not m['capped'], m
# Front segment crosses the z band: F must be interpolated, not a vertex.
co=[Vector(v) for v in ((-1,-.04,0),(1,-.04,0),(0,.02,.06),
                       (-1,.06,.025),(0,.1,.025),(1,.06,.025),
                       (-1,.06,.035),(1,.06,.035),(0,.1,.035))]
f,k,gap=scope['torso_chord'](co,[(0,1,2),(3,4,5),(6,7,8)],A,[])
assert (f-Vector((0,-.03,.01))).length<1e-8, list(f)
co=[Vector((x,y,z)) for z in (-.08,0) for x,y in
    ((-.05,-.06),(.05,-.06),(.05,-.02),(-.05,-.02))]
box=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
roof=[(-.04,.04),(.01,.065),(.04,.08),(.10,.02),(.14,.12)]
co.extend(Vector((x,y,z)) for y,z in roof for x in (-.05,.05))
faces=box+[(8+i*2,9+i*2,11+i*2,10+i*2) for i in range(3)]
# The first rising segment meets the next through coincident seam copies.
off=len(co)
co.extend(v.copy() for v in co[10:12])
faces[len(box)]=(8,9,off+1,off)
# Last rising segment has separate coincident vertex copies at the valley.
off=len(co)
co.extend(Vector((x,y,z)) for y,z in roof[3:] for x in (-.05,.05))
faces.append((off,off+1,off+3,off+2))
off=len(co)
co.extend(Vector((x,y,.15)) for y in (-.04,.14) for x in (-.05,.05))
faces.append((off,off+1,off+3,off+2))
j=[Vector(),Vector((.03,-.04,-.03)),Vector((-.03,-.04,-.05)),Vector((0,-.04,-.07))]
for start in (1,2):
    f,k,gap=scope['torso_chord'](co,faces,Vector(),j,start_index=start)
    assert (k-Vector((0,.04,.08))).length<1e-8, k
    assert (Vector(gap['gap_exit'])-Vector((0,-.02,j[start].z))).length<1e-8, gap
    assert (Vector(gap['gap_ceiling'])-Vector((0,-.018,.051))).length<1e-8, gap
    assert gap['joint_index']==start, gap
retry=[j[0],Vector((0,.2,-.03)),j[2],j[3]]
f,k,gap=scope['torso_chord'](co,faces,Vector(),retry)
assert gap['joint_index']==2 and (k-Vector((0,.04,.08))).length<1e-8, gap
for missing_co,missing_faces in ((co,faces),(co[:8],box)):
    probes=retry[:2]+[retry[1]] if missing_faces is faces else j
    f,k,gap=scope['torso_chord'](missing_co,missing_faces,Vector(),probes)
    assert k is None and gap['joint_index'] is None, gap
    head,m=solve(Vector(),f,k,anchor,target,p)
    assert m['depth']==.03 and m['reason']=='gap ceiling not found', m
# Review regressions use real face cuts and BVH rays, with literal answers.
review_failures=[]
def review_case(name, check):
    try:
        check()
    except AssertionError as exc:
        review_failures.append(name)
        print('FAIL synthetic',name,str(exc),flush=True)
    else:
        print('PASS synthetic',name,flush=True)

def hit_face_start():
    # H=(-.018,.051) lies inside the long rising face. A disconnected
    # 2 mm strip at z=.052 has closer endpoints, but is above the first hit.
    # Only the hit face's contour reaches the hand-known peak (.04,.08).
    points=[v.copy() for v in co]; polygons=list(faces); off=len(points)
    points.extend(Vector((x,y,.052)) for y in (-.019,-.017) for x in (-.05,.05))
    polygons.append((off,off+1,off+3,off+2))
    _,k,gap=scope['torso_chord'](points,polygons,Vector(),j)
    assert (k-Vector((0,.04,.08))).length<1e-8, (list(k),gap)

def outside_entry():
    # From y=-.08, the box is entered at -.06 and exited at -.02.
    # The entry's +Z hit would be the box top, rather than the roof above air.
    outside=[j[0],Vector((0,-.08,-.03)),j[2],j[3]]
    _,k,gap=scope['torso_chord'](co,faces,Vector(),outside)
    assert (Vector(gap['gap_exit'])-Vector((0,-.02,-.03))).length<1e-8, gap
    assert (k-Vector((0,.04,.08))).length<1e-8, (list(k),gap)
    assert gap['entry_walked'] and gap['joint_index']==1, gap

def blocked_clearance():
    # A second box begins only 1 mm beyond E=-.02: Q=-.018 is inside it.
    # Neither internal joint has the required uninterrupted 2 mm of air.
    points=[v.copy() for v in co]; off=len(points)
    points.extend(Vector((x,y,z)) for z in (-.08,0) for x,y in
                  ((-.05,-.019),(.05,-.019),(.05,-.005),(-.05,-.005)))
    polygons=faces+[tuple(off+i for i in face) for face in box]
    f,k,gap=scope['torso_chord'](points,polygons,Vector(),j)
    assert k is None and gap['joint_index'] is None, (k,gap)
    assert len(gap['attempts'])==2 and all(
        row['reason']=='gap clearance below 2 mm' for row in gap['attempts']), gap
    assert gap['gap_reason']=='gap clearance below 2 mm', gap
    # Raising the second box's floor to -.04 frees the second joint at -.05.
    # Its +Z ceiling is now that floor; the connected box peaks at z=0.
    # The failed first attempt must be retained when the retry succeeds.
    for point in points[off:off+4]:
        point.z=-.04
    _,k,gap=scope['torso_chord'](points,polygons,Vector(),j)
    assert k is not None and abs(k.z)<1e-8 and -.019-1e-8<=k.y<=-.005+1e-8, (k,gap)
    assert gap['joint_index']==2 and abs(gap['gap_ceiling'][2]+.04)<1e-8, gap
    assert len(gap['attempts'])==2 and gap['attempts'][0]['reason']=='gap clearance below 2 mm', gap
    assert gap['attempts'][1]['reason']=='' and not gap['entry_walked'], gap

def connected_plateau():
    # The slope reaches (.01,.065), crosses a flat ledge to (.025,.065),
    # then rises to (.04,.08). A 0.2 micrometre segment welds to itself;
    # the duplicate ledge forms a cycle. Neither can stop or loop the climb.
    points=[v.copy() for v in co[:8]]
    ledge=[(-.04,.04),(.01,.065),(.0100002,.065),(.025,.065),
           (.04,.08),(.10,.02)]
    points.extend(Vector((x,y,z)) for y,z in ledge for x in (-.05,.05))
    polygons=box+[(8+2*i,9+2*i,11+2*i,10+2*i) for i in range(5)]
    polygons.append((10,11,15,14))
    for height in (.065,.06499995):
        # A 50 nm drop also counts as equal height under the 1e-7 tolerance.
        points[14].z=points[15].z=height
        _,k,gap=scope['torso_chord'](points,polygons,Vector(),j)
        assert (k-Vector((0,.04,.08))).length<1e-8, (list(k),gap)

def fallback_cap():
    # The fallback requests 30 mm, but the anchor target is only 20 mm away.
    # Every reason must survive the common cap; head offsets are 20/sqrt(2).
    for f,k,reason in ((None,K,'front point missing'),
                       (F,None,'gap ceiling not found'),
                       (F,F,'degenerate chord'),
                       (Vector(),Vector((0,.08,.08)),'pivot direction parallel to chord')):
        head,m=solve(A,f,k,anchor,A+Vector((0,.02,0)),p)
        assert abs(m['depth']-.02)<1e-8 and m['capped'] and m['reason']==reason, m
        assert (head-(A+Vector((0,.01414213562373095,.01414213562373095)))).length<1e-8, list(head)

for name,check in (('hit-face contour start',hit_face_start),
                   ('entry then exit',outside_entry),('2 mm air clearance',blocked_clearance),
                   ('plateau, cycle and self-neighbour',connected_plateau),
                   ('cap every fallback',fallback_cap)):
    review_case(name,check)
assert not review_failures, review_failures
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job['inputs']['model'])
arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
co,edges,normals,faces=[],[],[],[]
for mesh in (o for o in bpy.context.scene.objects if o.type=='MESH'
             and any(md.type=='ARMATURE' and md.object==arm for md in o.modifiers)):
    off=len(co); normal_matrix=mesh.matrix_world.to_3x3().inverted().transposed()
    co.extend(mesh.matrix_world@v.co for v in mesh.data.vertices)
    normals.extend((normal_matrix@v.normal).normalized() for v in mesh.data.vertices)
    edges.extend(tuple(off+i for i in e.vertices) for e in mesh.data.edges)
    faces.extend(tuple(off+i for i in f.vertices) for f in mesh.data.polygons)
g=job['params']['group']; p=scope['parameters'](g)
bones={scope['bone_key'](b.name):b for b in arm.data.bones}
plan=scope['appendage_plan'](g,p,co,edges,bones,normals,faces)
# Pinned pre-pivot planner, loaded and executed with the same source protocol.
baseline_source=Path(job['params']['baseline_operation'])
baseline_scope={'__file__':str(source)}
exec(compile(baseline_source.read_text().split('_common.main(')[0],str(baseline_source),'exec'),baseline_scope)
baseline=baseline_scope['appendage_plan'](g,p,co,edges,bones,normals,faces)
assert plan[1].keys()==baseline[1].keys()
baseline_weights_delta=0.
for name,weights in plan[1].items():
    assert weights.keys()==baseline[1][name].keys(), name
    for i,value in weights.items():
        delta=abs(value-baseline[1][name][i]); baseline_weights_delta=max(baseline_weights_delta,delta)
        assert delta<=1e-9, (name,i,value,baseline[1][name][i])
assert plan[3]==baseline[3], (len(plan[3]),len(baseline[3]))
baseline_attachment_delta=(Vector(plan[2]['attachment'])-Vector(baseline[2]['attachment'])).length
assert baseline_attachment_delta<=1e-9, baseline_attachment_delta
assert len(plan[2]['placement'])==len(baseline[2]['placement'])
baseline_heads_delta=max(((Vector(row['head'])-Vector(original['head'])).length
    for row,original in zip(plan[2]['placement'][1:],baseline[2]['placement'][1:])),default=0.)
assert baseline_heads_delta<=1e-9, baseline_heads_delta
m=plan[2]; pivot=m['pivot']; A=Vector(m['weight_joints'][0])  # pivot base: the unmoved root
head=Vector(m['placement'][0]['head']); u=Vector((0,1,1)).normalized()
assert not m['leak'] and pivot['reason']=='', m
assert pivot['margin']>=p['root_wall_margin']-1e-6, pivot
assert pivot['depth']>=p['root_depth'], pivot
assert (head-A-u*pivot['depth']).length<=1e-6, (list(head),list(A),pivot)
assert pivot['front'][1]<A.y+.005 and pivot['gap_apex'][1]>A.y, (list(A),pivot)
F=Vector(pivot['front']); K=Vector(pivot['gap_apex'])
assert A.z-.03 <= K.z <= A.z+.03, (list(A),list(K))
assert A.y < K.y < A.y+.12, (list(A),list(K))
normal=Vector((0,F.z-K.z,K.y-F.y)).normalized()
anchor=scope['lookup'](bones,p['anchor_bone']).head_local
if normal.dot(anchor-F)<0:
    normal.negate()
measured_margin=normal.dot(head-F)
assert measured_margin>=p['root_wall_margin']-1e-6, (measured_margin,pivot)
assert abs(measured_margin-pivot['margin'])<=1e-6, (measured_margin,pivot)
zero=scope['appendage_plan'](g,dict(p,root_depth=0.,root_wall_margin=-1.),co,edges,bones,normals,faces)
assert zero[2]['pivot']['depth']==0., zero[2]['pivot']
assert (Vector(zero[2]['placement'][0]['head'])-A).length<=1e-9
assert plan[1].keys()==zero[1].keys()
max_delta=0.
for name,weights in plan[1].items():
    assert weights.keys()==zero[1][name].keys(), name
    for i,value in weights.items():
        delta=abs(value-zero[1][name][i]); max_delta=max(max_delta,delta)
        assert delta<=1e-9, (name,i,value,zero[1][name][i])
assert plan[3]==zero[3], (len(plan[3]),len(zero[3]))
followers,count=scope['contact_follow_weights'](p,co,edges,faces,plan)
zero_followers,zero_count=scope['contact_follow_weights'](p,co,edges,faces,zero)
assert count==zero_count and followers.keys()==zero_followers.keys()
for name,weights in followers.items():
    assert weights.keys()==zero_followers[name].keys(), name
    for i,value in weights.items():
        assert abs(value-zero_followers[name][i])<=1e-9, (name,i,value,zero_followers[name][i])
assert m['weight_joints']==zero[2]['weight_joints']
unmoved=[Vector(v) for v in m['weight_joints']]
for start in (1,2):
    f,k,gap=scope['torso_chord'](co,faces,A,unmoved,start_index=start)
    assert gap['joint_index']==start, gap
    assert (k-K).length<=1e-6, (start,list(k),list(K))
assert pivot['joint_index']==1 and pivot['gap_exit'] and pivot['gap_ceiling'], pivot
assert len(m['placement'])==len(zero[2]['placement'])
for row,original in zip(m['placement'][1:],zero[2]['placement'][1:]):
    assert (Vector(row['head'])-Vector(original['head'])).length<=1e-9
assert (Vector(m['placement'][-1]['tip'])-Vector(zero[2]['placement'][-1]['tip'])).length<=1e-9
assert abs(m['axis_length']-zero[2]['axis_length'])<=1e-9
assert (Vector(m['root_offset'])-(head-A)).length<=1e-9
Path(job['result']).write_text(json.dumps({'ok':True,'data':{
    'pivot':pivot,'root_head':list(head),'attachment':list(A),
    'base_stop_reason':m['base_stop_reason'],'base_extension_t':m['base_extension_t'],
    'affected':len(plan[3]),'weights_max_delta':max_delta,
    'baseline_commit':job['params']['baseline_commit'],
    'baseline_weights_max_delta':baseline_weights_delta,
    'baseline_attachment_delta':baseline_attachment_delta,
    'baseline_heads_max_delta':baseline_heads_delta,
    'review_cases_passed':5,
    'measured_margin':measured_margin,'contact_faces':count,
    'contact_followers':len({i for weights in followers.values() for i in weights})},'outputs':{}}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--declaration',type=Path,required=True)
    parser.add_argument('--group',required=True)
    parser.add_argument('--target-height-m',type=float,default=1.86)
    args=parser.parse_args()
    import yaml
    manifest=yaml.safe_load(args.declaration.read_text())
    group=next(copy.deepcopy(rig) for s in manifest['body_slots'] for rig in s.get('rigs',[])
               if rig.get('id')==args.group)
    group.update(enabled=True,flip=False)
    source_hash=hashlib.sha256(args.model.read_bytes()).hexdigest()
    declaration_hash=hashlib.sha256(args.declaration.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='extension-pivot-') as tmp:
        root=Path(tmp)
        os.environ['STORAGE_DIR']=str(root/'storage')
        os.environ['INSTANCE_DIR']=str(root/'instance')
        from app.core import paths
        paths.init(root/'storage')
        paths.init_instance(root/'instance')
        from app.blender import refine, runner
        normalized=runner.run('normalize',inputs={'model':args.model},
            params={'target_height_m':args.target_height_m},out_dir=root/'normalized',timeout_s=180)
        assert normalized['ok'], normalized
        source=Path(normalized['outputs']['model'])
        scripts=root/'scripts'; scripts.mkdir(); (scripts/'probe.py').write_text(PROBE)
        baseline=scripts/'baseline.py'
        baseline.write_text(subprocess.check_output(['git','show',
            BASELINE_COMMIT+':app/blender/scripts/extension_bones.py'],
            cwd=Path(__file__).resolve().parents[1],text=True))
        original_scripts=runner.SCRIPTS_DIR
        runner.SCRIPTS_DIR=scripts
        try:
            result=runner.run('probe',inputs={'model':source},params={
                'operation':str(original_scripts/'extension_bones.py'),'group':group,
                'baseline_operation':str(baseline),'baseline_commit':BASELINE_COMMIT},
                out_dir=root/'probe',timeout_s=600)
        finally:
            runner.SCRIPTS_DIR=original_scripts
        assert result['ok'], result
        print('PASS Part A analytic checks and 5/5 review regressions')
        print('PASS pivot, both ray starts and unchanged weights/membership',json.dumps(result['data']))
        full=refine.apply_script(source,'extension_bones',{'groups':[group]},
            validator=None,require_smaller=False,keep_original=False,base_joints_only=True)
        assert full['applied'], full
        metrics=full['data']['metrics'][args.group]
        assert metrics['pivot']==result['data']['pivot'], metrics['pivot']
        print('PASS full extension',json.dumps({
            'pivot':metrics['pivot'],'root_head':metrics['placement'][0]['head'],
            'edge_stretch_p01_p50_p99_max':metrics['edge_stretch_p01_p50_p99_max']}))
    assert hashlib.sha256(args.model.read_bytes()).hexdigest()==source_hash
    assert hashlib.sha256(args.declaration.read_bytes()).hexdigest()==declaration_hash
    print('PASS source fixture and declaration unchanged')


if __name__=='__main__':
    main()
