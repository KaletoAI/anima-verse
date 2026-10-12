"""Offline inside-contact ramp check; fixtures and declarations remain unchanged.

Usage: .venv/bin/python scripts/smoke_extension_rig_contact_ramp.py
       [--model-l FIXTURE.glb --model-p FIXTURE.glb --model-m FIXTURE.glb]
       [--declaration MANIFEST.yaml --group GROUP]
       [--normalize --target-height-m 1.86]

Part A needs no fixture. Along a tube at z=.015, seam vertex 0 has an
eligible outside neighbour 2 mm away. D=20 mm and b=.6 give f=.6 at
0 mm, .6625 at 5 mm (smooth(1/4)=5/32), .8 at 10 mm and 1 at
20 mm and beyond (the endpoint is at 25 mm). Vertex 2 duplicates vertex 1
within weld_distance and has the only edge to vertex 3: both copies must receive d=5 mm and b=.6.
An isolated copy 0.05 mm away shares the same distance and value.
Link shares 3/4 and 1/4 must remain proportional to these totals.
A separate seam has its outside neighbour at z=0, inside the 10 mm
attachment ring: b=0 gives f=0 at 0 mm, .5 at 10 mm and 1 at
20 mm and beyond (the endpoint is at 25 mm). A contact face at z=5 mm
cannot seed the ramp, including through its edge to a full vertex at z=20 mm.
A partial ring vertex at z=5 mm with total .5 stays unchanged. A full tube
vertex at z=7.5 mm with total .95 connects to the first seam at z=15 mm:
d=7.5 mm, smooth(3/8)=81/256, f=.7265625 and total=.690234375.
Propagation includes this full vertex inside the ring distance; seeding does not.
Hand-derived tube answers (distances in mm, f is the multiplier):
  vertex       d_in       b       f
  0            0          .6      .6
  1,2,26       5          .6      .6625
  3            10         .6      .8
  4            25         .6      1
  6            0          0       0
  7            10         0       .5
  8            25         0       1
  10,12        unreached  --      1 (ring-only face cannot seed)
  13           0          .6      .6
  17           0          .2      .2
  18           10         .2      .6 (equal paths choose seed 17)
  19           0          .6      .6
  22           0          .6      .6
  24           19         .6      .9971 (smooth(.95)=.99275)
  23           33         .6      1 (5 mm geometric shortcut has no edge)
  27           partial    --      1 (original total .5)
  28           7.5        .6      .7265625 (original total .95)
A third seam has two eligible outside vertices (b=.2 and .6) and an
ineligible vertex: its maximum boundary value is .6. Tied seeds choose
by actual seed index, independent of edge/face order and lower-index UV copies.
Two seeds with b=.2 and b=.6 are each 10 mm from a midpoint: the lower
actual seed wins, giving .2+.8*smooth(1/2)=.6 even when the other seed
has a coincident non-contact copy with a lower index. A Euclidean shortcut
without an edge cannot shorten the distance. D=0, missing contacts and
fallback must leave the plan untouched. Removing a link's last core vertex
must raise the existing core failure rather than shortening D.
An export check isolates weight application with a hand-planned seam total
.2 and link ratio 3:1. Original shares .4,.35,.25 leave .32,.28,.20.
With four influence slots, both links (.15,.05) must survive; the largest
two original shares divide the .8 remainder as .8*8/15 and .8*7/15.

The analytic export case starts with chain shares 3/4 and 1/4 at a b=.2
seam, so the exported chain weights must be .15 and .05. Original body
weights .4, .35, .25 compete for the two remaining slots: keep .4 and .35,
normalize their ratio to 8/15 and 7/15, then multiply by the remainder .8.
Thus the exported original weights are .8*8/15 and .8*7/15. The smaller
chain share must survive the four-influence limit. This check builds a real
skinned mesh, supplies the hand-derived plan and reloads the exported GLB.

A second export case enables reweight_from=['Body1','Body2','Body3'] on
the same tube vertex, with declared parent Anchor. At d=0 and D=.02,
f=.2+(1-.2)*smooth(0)=.2, so chain shares are .75*.2=.15 and
.25*.2=.05. Source weights sum to .4+.35+.25=1; transferring that sum
to Anchor before applying the chain leaves Anchor=1*(1-.15-.05)=.8.
All three source weights must be zero after export, and the chain ratio
must remain 3:1. Resolving the parent from stale body bone references
would instead leave the .8 remainder on Body3, which this case rejects.

Part B uses the real planner and exported weights at the supplied scale.
Use --normalize for raw fixtures; its default target height is 1.86 m.
L requires the inside ramp to reduce p99 stretch without increasing the max
under the declared measure pose, compared with D=0 using the same final
coincident-copy invariant. Unifying a crease can replace a tear with stretch,
so the former absolute max<6/p99<3.2 bounds only identify the pinned old defect.
P/M require no contact faces and bit-identical weights for D=0/.02.
All runs preserve membership, placement, attachment and pivot. Current D=0/.02
runs preserve planned followers; final follower weights can change when their
coincident tube copy is ramped and the exported copies are averaged.
Before final copy unification, source transfer and tube checks must have zero
defects. Averaging with a body-side copy can subsequently restore body weights
or partial tube weights on a captured copy; final counters report those values.
Each link retains a core vertex (> .9). The old-code proof pins f27a8e47: P/M disabled weights must
match that implementation, while its analytic seam stays 1 instead of .6
and its L stretch must fail at least one acceptance bound. Expected
analytic values above are derived by hand, never from recorded output.
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
BASELINE_COMMIT = 'f27a8e4796e061c22c6999a19219d43135e635da'

ANALYTIC = r'''
import copy
from mathutils import Vector

def analytic(scope):
    co=[Vector(v) for v in ((0,0,.015),(.005,0,.015),(.005,0,.015),
        (.01,0,.015),(.025,0,.015),(0,.002,.015),
        (.1,0,.04),(.11,0,.04),(.125,0,.04),(.1,0,0),
        (.7,0,.005),(.7,.002,.005),(.7,0,.02),
        (.2,0,.04),(.2,.002,.04),(.2,-.002,.04),(.2,0,0),
        (.3,-.01,.04),(.3,0,.04),(.3,.01,.04),(.302,-.01,.04),(.302,.01,.04),
        (.4,0,.04),(.405,0,.04),(.419,0,.04),(.4,.002,.04),(.00505,0,.015),(0,0,.005),(0,0,.0075))]
    tube=set(range(len(co)))-{5,9,11,14,15,16,20,21,25}
    edges=[(0,1),(2,3),(3,4),(0,5),(6,7),(7,8),(6,9),
           (0,27),(0,28),(10,12),(10,11),(13,14),(13,15),(13,16),
           (17,18),(18,19),(17,20),(19,21),(22,24),(24,23),(22,25)]
    faces=[(0,5,27),(6,9,16),(10,11,9),(13,14,15,16),(17,20,9),(19,21,9),(22,25,9)]
    edges=sorted(set(tuple(sorted(edge)) for edge in edges) |
                 {tuple(sorted((a,b))) for face in faces for a,b in zip(face,face[1:]+face[:1])})
    p={'contact_inside_distance':.02,'contact_follow_distance':.025,
       'contact_follow_weight':.6,'weld_distance':.0005,
       'attachment_ring_max':.01,'chain_split':[.5]}
    m={'leak':False,'base_extension_t':0.,'segment_axis_base':[0,0,0],
       'segment_axis_tip':[0,0,.1],'segment_axis_length':.1,
       'attachment':[0,0,0],'weight_joints':[[0,0,0],[0,0,.05],[0,0,.1]],
       'placement':[{'head':[0,0,0],'tip':[0,0,.05]},
                    {'head':[0,0,.05],'tip':[0,0,.1]}]}
    plan=([],{'Chain1':{i:.75 for i in tube},'Chain2':{i:.25 for i in tube}},m,tube,[])
    # Separate core points keep this two-link plan valid after the ramp.
    plan[1]['Chain1'][4]=1.; plan[1]['Chain2'][4]=0.
    plan[1]['Chain1'][8]=0.; plan[1]['Chain2'][8]=1.
    for i,total in ((27,.5),(28,.95)):
        plan[1]['Chain1'][i]=.75*total; plan[1]['Chain2'][i]=.25*total
    follow={'Chain1':{5:.45,14:.15,15:.45,20:.15,21:.45,25:.45},
            'Chain2':{5:.15,14:.05,15:.15,20:.05,21:.15,25:.15}}
    ramp=scope.get('contact_inside_weights',lambda *args:set())
    before=copy.deepcopy(plan); followers=copy.deepcopy(follow)
    scaled=ramp(p,co,edges,faces,plan,follow)
    expected={0:.6,1:.6625,2:.6625,3:.8,4:1.,6:0.,7:.5,8:1.,
              10:1.,12:1.,13:.6,17:.2,18:.6,19:.6,22:.6,23:1.,24:.9971,26:.6625,27:.5,28:.690234375}
    for i,total in expected.items():
        actual=sum(w.get(i,0.) for w in plan[1].values())
        assert abs(actual-total)<2e-7, ('inside ramp',i,actual,total)
        if i not in (4,8):
            assert abs(plan[1]['Chain1'].get(i,0.)-.75*total)<2e-7, ('link shares',i)
    assert scaled=={0,1,2,3,6,7,13,17,18,19,22,24,26,28}, scaled
    assert follow==followers and plan[2]==before[2] and plan[3]==before[3]
    reversed_plan=copy.deepcopy(before)
    assert ramp(p,co,list(reversed(edges)),list(reversed(faces)),reversed_plan,follow)==scaled
    assert reversed_plan==plan, 'iteration order changed result'
    tied_co=[Vector(v) for v in ((0,.01,.04),(0,-.01,.04),(0,0,.04),
        (0,.01,.04),(.002,-.01,.04),(.002,.01,.04),(.025,.01,.04))]
    tied_tube={0,1,2,3,6}
    tied_plan=([],{'Chain1':{i:1. for i in tied_tube}},copy.deepcopy(m),tied_tube,[])
    tied_follow={'Chain1':{4:.2,5:.6}}
    ramp(p,tied_co,[(1,2),(2,3),(3,6),(1,4),(3,5)],[(1,4),(3,5)],
         tied_plan,tied_follow)
    assert abs(tied_plan[1]['Chain1'][2]-.6)<2e-7, ('actual seed tie',tied_plan[1])
    assert tied_plan[1]['Chain1'][0]==tied_plan[1]['Chain1'][3], 'UV seed copies differ'
    grown=copy.deepcopy(before); grown[2]['base_extension_t']=-.1
    assert ramp(p,co,edges,faces,grown,follow)==scaled
    assert grown[1]==plan[1] and grown[3]==before[3], 'grown attachment station differs'
    for settings,polygons in ((dict(p,contact_inside_distance=0.),faces),(p,[])):
        unchanged=copy.deepcopy(before)
        assert not ramp(settings,co,edges,polygons,unchanged,follow)
        assert unchanged==before, 'off path changed plan'
    fallback=copy.deepcopy(before); fallback[2]['leak']=True
    fallback_before=copy.deepcopy(fallback)
    assert not ramp(p,co,edges,faces,fallback,follow) and fallback==fallback_before
    no_core=copy.deepcopy(before)
    no_core[1]['Chain1']={0:1.}; no_core[1]['Chain2']={6:1.}
    try:
        ramp(p,co,edges,faces,no_core,follow)
    except ValueError as exc:
        assert 'chain link has no core vertices' in str(exc), str(exc)
    else:
        raise AssertionError('inside ramp must fail when a link loses its core')
'''

EXPORT_ANALYTIC = r'''
def analytic_export(scope,transfer=False):
    common=scope['_common']
    original_reset,original_import=common.reset_scene,common.import_model
    saved={key:scope[key] for key in ('parameters','appendage_plan','measure')}
    co=[(0,0,.04),(.002,0,.04),(0,.002,.04),
        (.1,0,.04),(.1,.002,.04),(.102,0,.04),
        (.2,0,.04),(.2,.002,.04),(.202,0,.04)]
    def fixture():
        original_reset()
        data=bpy.data.armatures.new('AnchorRig')
        arm=bpy.data.objects.new('AnchorRig',data)
        bpy.context.collection.objects.link(arm)
        bpy.context.view_layer.objects.active=arm; arm.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        for name,head in (('Anchor',(0,0,0)),('Up',(0,0,1)),('Left',(1,0,0)),
                          ('Right',(-1,0,0)),('Front',(0,-1,0)),
                          ('Body1',(0,0,0)),('Body2',(0,0,0)),('Body3',(0,0,0))):
            bone=data.edit_bones.new(name)
            bone.head=head; bone.tail=Vector(head)+Vector((0,0,.05))
        bpy.ops.object.mode_set(mode='OBJECT')
        mesh_data=bpy.data.meshes.new('Surface')
        mesh_data.from_pydata(co,[],[(0,1,2),(3,4,5),(6,7,8)]); mesh_data.update()
        mesh=bpy.data.objects.new('Surface',mesh_data)
        bpy.context.collection.objects.link(mesh)
        mesh.modifiers.new('Skin','ARMATURE').object=arm
        for name,value in (('Body1',.4),('Body2',.35),('Body3',.25)):
            mesh.vertex_groups.new(name=name).add(list(range(len(co))),value,'REPLACE')
    sources=['Body1','Body2','Body3'] if transfer else []
    p={'contact_inside_distance':.02,'contact_follow_distance':.025,
       'contact_follow_weight':.2,'weld_distance':.0005,'attachment_ring_max':.01,
       'chain_split':[.5],'up_from_bone':'Anchor','up_to_bone':'Up',
       'up_distance_min':.1,'up_distance_max':2.,'lateral_positive_bone':'Left',
       'lateral_negative_bone':'Right','front_from_bone':'Anchor','front_to_bone':'Front',
       'front_distance_min':.1,'reweight_from':sources}
    m={'leak':False,'base_extension_t':0.,'segment_axis_base':[0,0,0],
       'segment_axis_tip':[0,0,.1],'segment_axis_length':.1,'attachment':[0,0,0],
       'weight_joints':[[0,0,0],[0,0,.05],[0,0,.1]],
       'placement':[{'head':[0,0,0],'tip':[0,0,.05]},
                    {'head':[0,0,.05],'tip':[0,0,.1]}]}
    links=[('Chain1',Vector((0,0,0)),Vector((0,0,.05)),'Anchor'),
           ('Chain2',Vector((0,0,.05)),Vector((0,0,.1)),'Chain1')]
    weights={'Chain1':{0:.75,3:1.,4:1.,5:1.},'Chain2':{0:.25,6:1.,7:1.,8:1.}}
    planned=(links,weights,m,{0,3,4,5,6,7,8},sources)
    group={'id':'export_chain','op':'appendage_chain','chains':[[
        {'bone':'Chain1','parent':'Anchor'},{'bone':'Chain2','parent':'Chain1'}]]}
    out=Path(job['out_dir'])/('analytic-export-transfer' if transfer else 'analytic-export'); out.mkdir()
    common.reset_scene=fixture; common.import_model=lambda path:None
    scope.update(parameters=lambda group:p,appendage_plan=lambda *args:copy.deepcopy(planned),
                 measure=lambda *args:{'export_chain':{}})
    try:
        data,outputs=scope['extension_bones']({'inputs':{'model':'synthetic'},
            'params':{'groups':[group]},'out_dir':str(out)})
    finally:
        common.reset_scene,common.import_model=original_reset,original_import
        scope.update(saved)
    assert data['status']=='applied', data
    original_reset(); original_import(outputs['model'])
    mesh=next(o for o in bpy.context.scene.objects if o.type=='MESH')
    vertex=next(v for v in mesh.data.vertices if (v.co-Vector(co[0])).length<1e-6)
    actual={mesh.vertex_groups[ge.group].name:ge.weight for ge in vertex.groups if ge.weight>0}
    if transfer:
        expected={'Anchor':.8,'Chain1':.15,'Chain2':.05}
        assert actual.keys()==expected.keys(), ('exported parent transfer',actual,expected)
        assert all(abs(actual[name]-value)<2e-7 for name,value in expected.items()), actual
        assert all(actual.get(name,0.)==0. for name in sources), ('exported source weights',actual)
        chain_total=actual['Chain1']+actual['Chain2']
        assert abs(actual['Anchor']-(1.-chain_total))<2e-7, ('exported parent remainder',actual)
        assert abs(actual['Chain1']/chain_total-.75)<2e-7, ('exported transfer link shares',actual)
        assert abs(actual['Chain2']/chain_total-.25)<2e-7, ('exported transfer link shares',actual)
        return
    expected={'Chain1':.15,'Chain2':.05,'Body1':.8*8/15,'Body2':.8*7/15}
    assert actual.keys()==expected.keys(), ('exported ramp shares',actual,expected)
    assert all(abs(actual[name]-value)<2e-7 for name,value in expected.items()), actual
'''

PROBE = r'''
import bpy, hashlib, json, math, sys
from pathlib import Path
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(job['params']['operation'])
def load_scope(path):
    scope={'__file__':str(source)}
    exec(compile(Path(path).read_text().split('_common.main(')[0],str(path),'exec'),scope)
    return scope
scope=load_scope(source)
''' + ANALYTIC + EXPORT_ANALYTIC + r'''
analytic(scope)
baseline=load_scope(job['params']['baseline_operation'])
try:
    analytic(baseline)
except AssertionError as exc:
    assert exc.args[0][:2]==('inside ramp',0), str(exc)
else:
    raise AssertionError('pinned old code passed the analytic seam')
analytic_export(scope)
analytic_export(scope,transfer=True)
summary={'analytic':True,'baseline_commit':job['params']['baseline_commit']}
if 'model' in job['inputs']:
    g=job['params']['group']
    def run(implementation,distance,out_dir,old=False):
        group=copy.deepcopy(g); group['params']['contact_inside_distance']=distance
        if old:
            group['params'].pop('contact_inside_distance')
        snapshot={}
        planner=implementation['appendage_plan']
        follow=implementation['contact_follow_weights']
        measure=implementation['measure']
        unify=implementation.get('unify_coincident_weights')
        ramp=implementation.get('contact_inside_weights')
        def planned(*args):
            plan=planner(*args)
            snapshot['membership']=sorted(plan[3])
            snapshot['geometry']={k:copy.deepcopy(plan[2][k]) for k in
                ('placement','pivot','attachment','weight_joints','axis_length','root_offset',
                 'base_extension_t','segment_axis_base','segment_axis_tip')}
            return plan
        def followed(*args):
            values,count=follow(*args)
            snapshot['followers']=copy.deepcopy(values); snapshot['contacts']=count
            return values,count
        def ramped(*args):
            indices=ramp(*args)
            snapshot['ramped']=set(indices)
            return indices
        def unified(co,owners,joint_index,final_weights):
            # The export invariant runs after transfer and packing. Verify
            # their original contracts at that boundary, before averaging.
            params=implementation['parameters'](group)
            geometry=snapshot['geometry']
            joints=[Vector(v) for v in geometry['weight_joints']]
            axis=(Vector(geometry['segment_axis_tip'])-Vector(geometry['segment_axis_base'])).normalized()
            sources={implementation['bone_key'](n) for n in params['reweight_from']}
            for i in snapshot['membership']:
                mesh,vi=owners[i]
                source_weight=sum(ge.weight for ge in mesh.data.vertices[vi].groups
                    if implementation['bone_key'](mesh.vertex_groups[ge.group].name) in sources)
                assert source_weight<=.1, ('source transfer before unification',i,source_weight)
                station=implementation['polyline_station'](co[i],joints,[0]+params['chain_split']+[1])[1]
                if geometry['base_extension_t']<0:
                    station=max(0.,(co[i]-Vector(geometry['attachment'])).dot(axis))
                if station>params['attachment_ring_max']+1e-6 and i not in snapshot['ramped']:
                    total=sum(w.get(i,0.) for w in final_weights.values())
                    assert total>=.9, ('tube weight before unification',i,total)
            snapshot['pre_unification_contracts']=True
            return unify(co,owners,joint_index,final_weights)
        def measured(arm,meshes,edges,plans):
            result=measure(arm,meshes,edges,plans)
            def evaluated():
                dg=bpy.context.evaluated_depsgraph_get(); out=[]
                for mesh in meshes:
                    ev=mesh.evaluated_get(dg); data=ev.to_mesh()
                    out.extend(mesh.matrix_world@v.co for v in data.vertices); ev.to_mesh_clear()
                return out
            rest=evaluated()
            for group,params,plan in plans:
                for i,(name,_,_,_) in enumerate(plan[0]):
                    pb=arm.pose.bones[name]; pb.rotation_mode='XYZ'
                    pb.rotation_euler=[math.radians(v)*params['test_rotation_decay']**i
                                       for v in params['test_rotation_deg']]
                    pb.scale=params['test_scale']
                bpy.context.view_layer.update(); posed=evaluated()
                weighted={i for weights in plan[1].values() for i in weights}
                ratios=[(posed[a]-posed[b]).length/(rest[a]-rest[b]).length for a,b in edges
                        if (a in weighted or b in weighted) and (rest[a]-rest[b]).length>1e-6]
                result[group['id']]['edges_gt3']=sum(v>3 for v in ratios)
                result[group['id']]['edges_gt5']=sum(v>5 for v in ratios)
                snapshot['follower_weights']={name:{i:values.get(i,0.) for i in
                    sorted({i for weights in snapshot['followers'].values() for i in weights})}
                    for name,values in plan[1].items()}
                for name,_,_,_ in plan[0]:
                    arm.pose.bones[name].rotation_euler=(0,0,0); arm.pose.bones[name].scale=(1,1,1)
                bpy.context.view_layer.update()
            return result
        implementation.update(appendage_plan=planned,contact_follow_weights=followed,measure=measured)
        if unify is not None:
            implementation.update(unify_coincident_weights=unified,contact_inside_weights=ramped)
        Path(out_dir).mkdir()
        try:
            data,outputs=implementation['extension_bones']({'inputs':job['inputs'],
                'params':{'groups':[group]},'out_dir':out_dir})
        finally:
            implementation.update(appendage_plan=planner,contact_follow_weights=follow,measure=measure)
            if unify is not None:
                implementation.update(unify_coincident_weights=unify,contact_inside_weights=ramp)
        assert data['status']=='applied', data['reason']
        snapshot['metrics']=data['metrics'][group['id']]
        # Compare every exported influence, including the original remainder.
        snapshot['weights']=[sorted((mesh.vertex_groups[ge.group].name,ge.weight)
                                    for ge in v.groups if ge.weight>0)
            for mesh in bpy.context.scene.objects if mesh.type=='MESH'
            for v in mesh.data.vertices]
        return snapshot
    root=Path(job['out_dir'])
    disabled=run(scope,0.,str(root/'disabled'))
    enabled=run(scope,.02,str(root/'enabled'))
    old=run(baseline,0.,str(root/'pinned'),old=True)
    label=job['params']['label']
    for key in ('membership','geometry','contacts'):
        assert disabled[key]==enabled[key]==old[key], ('changed invariant',key)
    assert disabled['followers']==enabled['followers'], 'inside ramp changed planned followers'
    if label!='L':
        assert disabled['weights']==old['weights'], 'P/M D=0 differs from pinned weights'
        for key in ('followers','follower_weights'):
            assert disabled[key]==enabled[key]==old[key], ('P/M changed invariant',key)
    for sample in (disabled,enabled):
        m=sample['metrics']
        assert sample['pre_unification_contracts'], 'pre-unification checks missing'
        assert all(v>0 for v in m['core_verts_per_link'].values()), 'missing core'
        if not m['coincident_groups_unified']:
            assert m['thigh_weight_in_part']==0, 'source weight remains in part'
            assert m['partial_outside_attachment_ring']==m['uncaptured_in_part']==0, 'defect counters'
    def report(sample):
        m=sample['metrics']; stretch=m['edge_stretch_p01_p50_p99_max']
        return {'max':stretch[3],'p99':stretch[2],'>3':m['edges_gt3'],'>5':m['edges_gt5'],
                'core_per_link':list(m['core_verts_per_link'].values()),
                'contact_inside_ramped':m.get('contact_inside_ramped',0),
                'contact_inside_weight_min':m.get('contact_inside_weight_min',1.),
                'contact_faces':sample['contacts'],
                'coincident_groups_unified':m.get('coincident_groups_unified',0),
                'thigh_weight_in_part':m['thigh_weight_in_part'],
                'partial_outside_attachment_ring':m['partial_outside_attachment_ring'],
                'uncaptured_in_part':m['uncaptured_in_part'],
                'weights_sha256':hashlib.sha256(json.dumps(sample['weights']).encode()).hexdigest()}
    if label=='L':
        before=old['metrics']['edge_stretch_p01_p50_p99_max']
        after=enabled['metrics']['edge_stretch_p01_p50_p99_max']
        disabled_stretch=disabled['metrics']['edge_stretch_p01_p50_p99_max']
        assert before[3]>=6 or before[2]>=3.2, 'pinned L did not fail acceptance'
        assert after[2]<disabled_stretch[2] and after[3]<=disabled_stretch[3]+1e-6, (
            'inside ramp stretch reduction',report(disabled),report(enabled))
        assert enabled['metrics']['contact_inside_ramped']>0
    else:
        assert enabled['contacts']==0, 'P/M unexpectedly has contact faces'
        assert disabled['weights']==enabled['weights'], 'no-contact weights changed'
        assert enabled['metrics']['contact_inside_ramped']==0
    summary.update(label=label,before=report(disabled),after=report(enabled),pinned=report(old),
                   planned_followers_identical=True,membership_identical=True,
                   pinned_disabled_identical=disabled['weights']==old['weights'])
Path(job['result']).write_text(json.dumps({'ok':True,'data':summary,'outputs':{}}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for label in ('l','p','m'):
        parser.add_argument('--model-'+label,type=Path)
    parser.add_argument('--declaration',type=Path)
    parser.add_argument('--group')
    parser.add_argument('--target-height-m',type=float,default=1.86)
    parser.add_argument('--normalize',action='store_true')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='extension-contact-ramp-') as tmp:
        root=Path(tmp)
        os.environ['STORAGE_DIR']=str(root/'storage'); os.environ['INSTANCE_DIR']=str(root/'instance')
        from app.core import paths
        paths.init(root/'storage'); paths.init_instance(root/'instance')
        from app.blender import runner
        scripts=root/'scripts'; scripts.mkdir(); (scripts/'probe.py').write_text(PROBE)
        operation=runner.SCRIPTS_DIR/'extension_bones.py'
        baseline=scripts/'baseline.py'
        baseline.write_text(subprocess.check_output(['git','show',
            BASELINE_COMMIT+':app/blender/scripts/extension_bones.py'],
            cwd=Path(__file__).resolve().parents[1],text=True))
        probe_params={'operation':str(operation),'baseline_operation':str(baseline),
                      'baseline_commit':BASELINE_COMMIT}
        original_scripts=runner.SCRIPTS_DIR
        runner.SCRIPTS_DIR=scripts
        try:
            result=runner.run('probe',inputs={},params=probe_params,out_dir=root/'analytic',timeout_s=600)
        finally:
            runner.SCRIPTS_DIR=original_scripts
        assert result['ok'], result
        print('PASS Part A analytic inside ramp and exported parent transfer; old-code failure pinned to '+BASELINE_COMMIT)
        for label in ('p','m','l'):
            fixture=getattr(args,'model_'+label)
            if fixture is None or not fixture.is_file():
                print('SKIP Part B '+label.upper()+': fixture missing')
                continue
            if args.declaration is None or not args.group:
                parser.error('present fixtures require --declaration and --group')
            import yaml
            manifest=yaml.safe_load(args.declaration.read_text())
            group=next(copy.deepcopy(slot['rig']) for slot in manifest['body_slots']
                       if (slot.get('rig') or {}).get('id')==args.group)
            group.update(enabled=True,flip=False)
            hashes=[hashlib.sha256(path.read_bytes()).hexdigest() for path in (fixture,args.declaration)]
            normalized={'outputs':{'model':str(fixture)}}
            if args.normalize:
                normalized=runner.run('normalize',inputs={'model':fixture},
                    params={'target_height_m':args.target_height_m},out_dir=root/('normalized-'+label),timeout_s=180)
                assert normalized['ok'], normalized
            runner.SCRIPTS_DIR=scripts
            try:
                result=runner.run('probe',inputs={'model':Path(normalized['outputs']['model'])},
                    params={**probe_params,'group':group,'label':label.upper()},
                    out_dir=root/('fixture-'+label),timeout_s=600)
            finally:
                runner.SCRIPTS_DIR=original_scripts
            assert result['ok'], result
            assert hashes==[hashlib.sha256(path.read_bytes()).hexdigest() for path in (fixture,args.declaration)]
            print('PASS Part B '+label.upper(),json.dumps(result['data'],sort_keys=True))


if __name__=='__main__':
    main()
