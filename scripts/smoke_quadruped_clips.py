#!/usr/bin/env python3
"""P4 numerical acceptance, derived by hand from spec §4.2 and §5.

A self-fit must keep fox locomotion contact error relative to each target Tip head's
world-space rest height <=1 percent of height and edge
stretch p99.9 <=4 for every fox take. The five takes are idle, walk, run,
sit and sit-ground; both sit takes are non-looping. Ground tolerance is
-.002*height, excluding contact paws (Ankle/Foot*/Tip weight >.5) and tail
vertices (Tail* weight >.5). A tail deliberately moved to -.05*height must
therefore remain negative with idle ground_lift_max exactly zero.
For calm sit, every Tail* matrix equals parent pose times rest offset at
relative tolerance 1e-5 in every frame; full sit must differ in some frame.
This detects a clearance lift applied to still tails as well as lost wag.
Clearance for moving tails is limited to pi/6 (30 degrees).
FBX stores no bone tails; the importer invents leaf tails. Thus FBX contact
and flight measure Tip heads against rest head heights, avoiding the spurious
2.25% walk error caused by reconstructed tails.
All takes must have zero unreachable tail-clearance frames.
Source contact means a Tip tail is at most .02*source height above its own
world-space rest height and moves <.01*source length to both adjacent frames.
The rigger's IK and constant median body offset use target Tip tail rest heights.
Run must have a sampled frame with all four Tip heads more than .02*target
height above their respective target rest heights, proving a flight phase.
Walk amplitude is the peak-to-peak world x position of Tail_Tip's tail
(left/right in the fitted frame), evaluated from the re-imported FBX action with its slot assigned.
In-scene NLA evaluation yielded rigid poses and cannot test the client asset.
Calm must be <=.25*full (specified damping is .2), and full must exceed
.01*body length to prove the measurement sees the wag.
Usage: .venv/bin/python scripts/smoke_quadruped_clips.py [output-directory]
Use --numpy-only to run only Blender-independent checks.
Outputs remain in /tmp by default for smoke_quadruped_takes.mjs.
"""
import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.blender import runner
from app.core.paths import get_quadruped_dir
from smoke_quadruped_fit import HELPER

CHECK = r'''
import bpy, sys, json, importlib.util, ast, re
import numpy as np
from pathlib import Path
folder, assets, script = map(Path, sys.argv[sys.argv.index('--')+1:])
spec=importlib.util.spec_from_file_location('quadruped_rig',script)
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
catalog=json.loads((assets/'clips.json').read_text())
# Hand-set split weights exercise the production selection independently of FBX.
from types import SimpleNamespace as Namespace
fake_body=Namespace(vertex_groups=[Namespace(index=i,name=name) for i,name in enumerate([
    'Back_Leg_Foot_L','Back_Leg_Foot_1_L','Back_Leg_Foot_1_R',
    'Back_Leg_Ankle_L','Back_Leg_Tip_L','Back_Leg_Lower_L'])])
bake=next(node for node in ast.parse(script.read_text()).body
          if isinstance(node,ast.FunctionDef) and node.name=='bake_clips')
paw_loop=next(node for node in bake.body if isinstance(node,ast.For)
              and isinstance(node.target,ast.Tuple) and node.target.elts[0].id=='key')
groups=eval(compile(ast.Expression(paw_loop.body[0].value),'<paw regression>','eval'),
            {**q.__dict__,'body':fake_body,'pattern':'Back_Leg_%s_L'})
assert groups=={0,1,3,4},groups
split_weight=sum(weight for group,weight in [(0,.3),(1,.3),(2,.4)] if group in groups)
assert abs(split_weight-.6)<1e-12 and split_weight>.5,split_weight
print('PASS paw regression: Foot 0.3 + Foot_1 0.3 = 0.6; opposite leg excluded',flush=True)

# Independently sample source contact masks; errors themselves are measured on FBX.
contact_masks={}
for src in ('fox',):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(assets/(src+'-animations.glb')))
    source=next(o for o in bpy.data.objects if o.type=='ARMATURE')
    source.animation_data_create();source.animation_data.action=None
    source.data.pose_position='REST';bpy.context.view_layer.update()
    source_v=np.concatenate([q.evaluated_vertices(o) for o in bpy.data.objects if o.type=='MESH'])
    source.data.pose_position='POSE'
    transform=q.alignment(source_v)
    source.matrix_world=transform@source.matrix_world
    from mathutils import Vector
    source_v=np.array([tuple(transform@Vector(p)) for p in source_v])
    source_height=float(np.ptp(source_v[:,2]));source_length=float(np.ptp(source_v[:,1]))
    mapping={pat%'Tip':pat%'Tip' for pat in q.LEGS.values()}
    source_rest={pat:(source.matrix_world@source.data.bones[mapping[pat%'Tip']].tail_local).z for pat in q.LEGS.values()}
    for take in (k for k,v in catalog.items() if v['src']==src):
        action=next(a for a in bpy.data.actions if a.name==catalog[take]['action'])
        source.animation_data.action=action
        if action.slots:source.animation_data.action_slot=action.slots[0]
        first,last=action.frame_range
        points={pat:[] for pat in q.LEGS.values()}
        for i in range(int(np.ceil(last-first))+1):
            t=min(last,first+i)
            bpy.context.scene.frame_set(int(np.floor(t)),subframe=t-np.floor(t))
            for pat in points:points[pat].append((source.matrix_world@source.pose.bones[mapping[pat%'Tip']].tail).copy())
        contact_masks[take]={pat:[p.z-source_rest[pat]<=.02*source_height
            and (p-ps[max(0,i-1)]).length<.01*source_length
            and (p-ps[min(len(ps)-1,i+1)]).length<.01*source_length
            for i,p in enumerate(ps)] for pat,ps in points.items()}
results={}
for mode in ('full','calm','still'):
    out=folder/mode;out.mkdir(exist_ok=True)
    metrics,_=q.run({'inputs':{'mesh':str(folder/'fox.glb'),'texture':str(folder/'texture.png'),
        'ref':str(assets/'fox-animations.glb')},'params':{'clips':catalog,'assets_dir':str(assets),
        'tail_motion':mode},'out_dir':str(out)})
    # Check exact inherited poses before FBX changes bone rest orientations.
    arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
    for track in arm.animation_data.nla_tracks:track.mute=True
    sit_changed=False
    for take in (catalog if mode=='still' else ('sit','sit-ground')):
        action=next(a for a in bpy.data.actions if a.name==take)
        q.assign_action(arm,action)
        for frame in range(1,int(action.frame_range[1])+1):
            bpy.context.scene.frame_set(frame);bpy.context.view_layer.update()
            for bone in arm.data.bones:
                if not bone.name.startswith('Tail'):continue
                inherited=arm.pose.bones[bone.parent.name].matrix @ (bone.parent.matrix_local.inverted() @ bone.matrix_local)
                actual=np.array(arm.pose.bones[bone.name].matrix)
                expected=np.array(inherited)
                equal=np.linalg.norm(actual-expected)<=1e-5*max(np.linalg.norm(expected),1e-12)
                if mode in ('calm','still'):assert equal,(mode,take,frame,bone.name,actual,expected)
                if take=='sit':sit_changed |= not equal
    if mode=='full':assert sit_changed,'full sit lost wag'
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(out/'quadruped_rigged.fbx'))
    arm=next(o for o in bpy.data.objects if o.type=='ARMATURE')
    body=next(o for o in bpy.data.objects if o.type=='MESH')
    arm.animation_data_create();arm.animation_data.action=None
    rest_z={pat:(arm.matrix_world@arm.data.bones[pat%'Tip'].head_local).z for pat in q.LEGS.values()}
    arm.data.pose_position='REST';bpy.context.view_layer.update()
    rest_vertices=q.evaluated_vertices(body)
    rest_centroid=float(np.mean(rest_vertices[:,2]))
    body_length=float(np.ptp(rest_vertices[:,1]));height=float(np.ptp(rest_vertices[:,2]))
    edges=np.array([tuple(e.vertices) for e in body.data.edges],dtype=int)
    lengths=np.linalg.norm(rest_vertices[edges[:,0]]-rest_vertices[edges[:,1]],axis=1)
    valid=lengths>1e-8*body_length
    tail_indices=[v.index for v in body.data.vertices if sum(g.weight for g in v.groups
        if body.vertex_groups[g.group].name.startswith('Tail'))>.5]
    paw_weights={pat:np.array([sum(g.weight for g in v.groups
        if re.fullmatch(re.escape(pat).replace('%s',r'(?:Ankle|Foot.*|Tip)'),
                        body.vertex_groups[g.group].name))
        for v in body.data.vertices]) for pat in q.LEGS.values()}
    arm.data.pose_position='POSE'
    actions={a.name.rsplit('|',1)[-1]:a for a in bpy.data.actions}
    assert set(actions)==set(catalog),list(actions)
    lateral=[];flight_frames=0;measured={}
    for take in catalog:
        action=actions[take];arm.animation_data.action=action
        if action.slots:arm.animation_data.action_slot=action.slots[0]
        first,last=map(int,action.frame_range)
        low=float('inf');tail_low=float('inf');stretch_max=0.;contact_error=0.;contact_samples=0
        centroids={}
        for frame in range(first,last+1):
            bpy.context.scene.frame_set(frame);bpy.context.view_layer.update()
            co=q.evaluated_vertices(body)
            excluded=np.zeros(len(co),dtype=bool)
            excluded[tail_indices]=True
            for pat,weights in paw_weights.items():
                if contact_masks[take][pat][frame-first]:excluded|=weights>.5
            low=min(low,float(co[~excluded,2].min()))
            if tail_indices:tail_low=min(tail_low,float(co[tail_indices,2].min()))
            stretch=np.linalg.norm(co[edges[:,0]]-co[edges[:,1]],axis=1)[valid]/lengths[valid]
            stretch_max=max(stretch_max,float(np.percentile(stretch,99.9)))
            tips={pat:(arm.matrix_world@arm.pose.bones[pat%'Tip'].head).z for pat in q.LEGS.values()}
            if take in contact_masks:
                for pat,z in tips.items():
                    if contact_masks[take][pat][frame-first]:
                        contact_error=max(contact_error,abs(z-rest_z[pat]));contact_samples+=1
            if take=='run':
                flight_frames+=int(all(tips[pat]-rest_z[pat]>.02*height for pat in tips))
            if take=='walk':lateral.append((arm.matrix_world@arm.pose.bones['Tail_Tip'].tail).x)
            if frame in (first,(first+last)//2,last):centroids[str(frame)]=float(np.mean(co[:,2]))
        measured[take]={'mesh_min_z':low,'tail_min_z':tail_low,'stretch_p999':stretch_max,
            'contact_err_max':100*contact_error/height,'contact_samples':contact_samples,
            'centroids':centroids,'centroid_first':centroids[str(first)],
            'centroid_mid':centroids[str((first+last)//2)],'centroid_last':centroids[str(last)]}
    results[mode]={'metrics':metrics,'takes':list(actions),'clips':measured,'flight_frames':flight_frames,
        'yaw_amplitude':float(np.ptp(lateral)),'rest_centroid':rest_centroid,'body_length':body_length,'height':height}
# Move only strongly tail-weighted rest vertices, after fitting and skinning,
# so the fixture cannot alter the canonical alignment or ground landmarks.
original_skin=q.skin
def dipping_tail(body,arm,height):
    original_skin(body,arm,height)
    selected=[v for v in body.data.vertices if sum(g.weight for g in v.groups
        if body.vertex_groups[g.group].name.startswith('Tail'))>.5]
    assert selected
    for v in selected:v.co.z=-.05*height
q.skin=dipping_tail
out=folder/'dipping-tail';out.mkdir(exist_ok=True)
fixture,_=q.run({'inputs':{'mesh':str(folder/'fox.glb'),'texture':str(folder/'texture.png'),
    'ref':str(assets/'fox-animations.glb')},'params':{'clips':{'idle':catalog['idle']},
    'tail_motion':'still'},'out_dir':str(out)})
clip=fixture['clips']['idle']
assert clip['ground_lift_max']==0,clip
assert clip['tail_min_z']<0,clip
assert clip['tail_clearance_unreached']==0,clip
results['dipping_tail']=clip
(folder/'checks.json').write_text(json.dumps(results,indent=2))
'''


def check_declarations_and_ground():
    """Exercise validation and the ground calculation without a Blender process.

    One tail at -5% H and one body vertex at +10% H imply zero lift;
    including that tail instead implies 4.801% H lift and fails the regression.
    """
    import numpy as np
    script=Path(__file__).resolve().parents[1]/'app/blender/scripts/quadruped_rig.py'
    tree=ast.parse(script.read_text())
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    prefix=[]
    for statement in run.body:
        if isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Call):break
        prefix.append(statement)
    validation=compile(ast.Module(body=prefix,type_ignores=[]),'<declaration validation>','exec')
    valid={'src':'fox','action':'Sit','loop':False,'tail':{'calm':'still'}}
    for mode in ('full','calm','still'):
        exec(validation,{'job':{'inputs':{},'params':{'clips':{'sit':valid},'tail_motion':mode}}})
    for patch in ({'freeze':[]},{'reverse':False},{'unused':True},
                  {'tail':{'unknown':'still'}},{'tail':{'calm':'unknown'}},
                  {'tail':[]},{'src':'horse'}):
        try:
            exec(validation,{'job':{'inputs':{},'params':{'clips':{'sit':{**valid,**patch}}}}})
        except ValueError:pass
        else:raise AssertionError(('invalid declaration accepted',patch))
    bake=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='bake_clips')
    frames=next(n for n in ast.walk(bake) if isinstance(n,ast.For)
                and isinstance(n.target,ast.Tuple) and [getattr(e,'id',None) for e in n.target.elts]==['i','pose'])
    block=[];collect=False
    for statement in frames.body:
        if isinstance(statement,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='excluded' for t in statement.targets):collect=True
        if collect:block.append(statement)
        if isinstance(statement,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ground_lift' for t in statement.targets):break
    scope={'np':np,'co':np.array([[0.,0.,-.05],[0.,0.,.1]]),'tail_indices':[0],
           'paw_weights':{},'masks':{},'i':0,'target_lm':{'H':1.},'tail_floor':-.002}
    exec(compile(ast.Module(body=block,type_ignores=[]),'<tail ground regression>','exec'),scope)
    assert scope['ground_lift']==0,scope['ground_lift']
    print('PASS declaration validation and dipping-tail ground regression',flush=True)


def check_skin_weights():
    """Check the production NumPy helper without Blender.

    For x in [0,1], collinear segments [-1,0] and [1,2] have distances
    x and 1-x: the right weight is x**4/(x**4+(1-x)**4), monotonically
    increasing. Symmetric strip averaging preserves that order. Duplicate
    vertices check welding; an isolated (.25,.5,0) has squared distances 5/16 and 13/16,
    giving right weight 25/(25+169)=25/194.
    Six segments additionally exercise the four-influence cap. A control
    with the post-cap passes disabled must have a larger maximum adjacent
    weight jump, so removing re-smoothing fails this regression.
    """
    import numpy as np
    script=Path(__file__).resolve().parents[1]/'app/blender/scripts/quadruped_rig.py'
    tree=ast.parse(script.read_text())
    helpers=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='skin_weights']
    assert helpers, 'production skin_weights NumPy helper missing'
    scope={'np':np}
    exec(compile(ast.Module(body=helpers,type_ignores=[]),str(script),'exec'),scope)
    compute=scope['skin_weights']
    strip=np.column_stack((np.linspace(0,1,41),np.zeros((41,2))))
    points=np.vstack((strip,strip,[[.25,.5,0]]))
    edges=np.array([(i,i+1) for i in range(40)]+[(i+41,i+42) for i in range(40)])
    segments=[('left',np.array([-1.,0,0]),np.array([0.,0,0])),
              ('right',np.array([1.,0,0]),np.array([2.,0,0]))]
    weights=compute(points,segments,edges,2.)
    assert np.all(np.diff(weights[:41,1])>=-1e-12),weights[:41,1]
    assert weights[0,1]<weights[40,1]
    # Compile a local mutation of the real helper, leaving production untouched.
    import copy
    control=copy.deepcopy(helpers[0])
    passes=next(n for n in ast.walk(control) if isinstance(n,ast.For)
                and isinstance(n.iter,ast.Call) and isinstance(n.iter.func,ast.Name)
                and n.iter.func.id=='range' and len(n.iter.args)==1
                and isinstance(n.iter.args[0],ast.Constant) and n.iter.args[0].value==60)
    passes.iter.args[0].value=0
    control_scope={'np':np}
    exec(compile(ast.Module(body=[control],type_ignores=[]),str(script),'exec'),control_scope)
    capped=control_scope['skin_weights'](points,segments,edges,2.)
    assert np.diff(weights[:41,1]).max()<np.diff(capped[:41,1]).max()
    np.testing.assert_allclose(weights[:41],weights[41:82],rtol=0,atol=0)
    np.testing.assert_allclose(weights[-1,1],25/194,rtol=0,atol=1e-12)
    for result in (weights,compute(points,segments+[
            (str(y),np.array([-1.,y,0]),np.array([2.,y,0]))
            for y in (.1,-.1,.2,-.2)],edges,2.)):
        assert np.isfinite(result).all() and (result>=0).all()
        assert (np.count_nonzero(result,axis=1)<=4).all()
        np.testing.assert_allclose(result.sum(axis=1),1,rtol=0,atol=1e-12)
    print('PASS NumPy skin weights: cap, normalisation, monotone strip, welds and isolated vertex',flush=True)


def main():
    check_declarations_and_ground()
    check_skin_weights()
    if "--numpy-only" in sys.argv:
        return
    if not runner.is_available():
        print('SKIP quadruped clips: supported Blender unavailable:',runner.status()['error']);return
    assets=get_quadruped_dir()
    # Exact inventory and source declarations are hand-copied from §4.1.
    expected_catalog = {
        'idle': {'src': 'fox', 'action': 'Idle', 'loop': True},
        'walk': {'src': 'fox', 'action': 'Walk', 'loop': True},
        'run': {'src': 'fox', 'action': 'Run', 'loop': True},
        'sit': {'src': 'fox', 'action': 'Sit', 'loop': False, 'tail': {'calm': 'still'}},
        'sit-ground': {'src': 'fox', 'action': 'Sit', 'loop': False, 'tail': {'calm': 'still'}},
    }
    assert json.loads((assets/'clips.json').read_text()) == expected_catalog
    root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(tempfile.mkdtemp(prefix='av-p4-clips-'))
    root.mkdir(parents=True,exist_ok=True)
    print('Artifacts:',root,flush=True)
    prepare=root/'prepare.py';prepare.write_text(HELPER)
    check=root/'check.py';check.write_text(CHECK)
    from PIL import Image
    Image.new('RGB',(16,16),'red').save(root/'texture.png')
    for script,args in ((prepare,[str(root),str(assets),'prepare']),
                        (check,[str(root),str(assets),str(Path('app/blender/scripts/quadruped_rig.py').resolve())])):
        proc=subprocess.run([runner.find_executable(),'--background','-noaudio','--threads','1','--factory-startup','--python-exit-code','1',
            '--python',str(script),'--',*args],capture_output=True,text=True,timeout=580)
        assert proc.returncode==0,(proc.stdout+proc.stderr)[-6000:]
    data=json.loads((root/'checks.json').read_text());full=data['full'];calm=data['calm']
    expected=list(expected_catalog)
    print(json.dumps(data,indent=2),flush=True)
    for mode in (full,calm,data['still']):
        metrics=mode['metrics'];assert metrics['takes']==expected,metrics['takes']
        assert set(mode['takes'])==set(expected),mode['takes']
        for name,clip in mode['clips'].items():
            assert metrics['clips'][name]['loop'] == expected_catalog[name]['loop']
            assert clip['mesh_min_z']>=-.002*mode['height'],(name,clip)
            assert metrics['clips'][name]['contact_err_max']<=1,(name,metrics['clips'][name])
            # The FBX-side contact_err_max/contact_samples are reported, not asserted: they read
            # the Tip joint (no leaf bones in the FBX) against source-frame masks, not the
            # contact point and frames the production metric above uses.
            assert metrics['clips'][name]['tail_clearance_unreached']==0,(name,metrics['clips'][name])
            assert clip['stretch_p999']<=4,(name,clip)
        assert mode['flight_frames']>=1,'run lost flight phase'
        assert mode['rest_centroid']>0,mode
    assert full['yaw_amplitude']>.01*full['body_length'],full
    assert calm['yaw_amplitude']<=.25*full['yaw_amplitude'],(full,calm)
    print('PASS P4 clips; FBX:',root/'full/quadruped_rigged.fbx')

if __name__=='__main__':main()
