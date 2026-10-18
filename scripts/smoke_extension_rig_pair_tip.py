"""Analytic pair tip checks, reusing the pair wall fixture builder.

The spherical cap has radius .106, height .05, centre y=-.044.
At the marker (x=.15,z=1.41), y=-.044-sqrt(.106**2-.01**2).
The omitted quadric term r^4/(8*.106^3) at r=.015 is .0054 mm;
linear interpolation at spacing 2.5 mm contributes below .03 mm.
The .3 mm tolerance covers fitting/interpolation, not a 4 mm crater.
The fixture has R<.012, hence rn=.5*R. The core gives w(0)=1;
w(.5*R)=.35*smooth(8/9)=.35*704/729; w(1.3*R)=0. Transfer T=w*S leaves S+T invariant. Scaling
local Y by 1.4 moves a fully weighted surface point .4*.01=.004 m.
Coincident copies receive identical positional fill and final weights.
No expected value is recorded from a run.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smoke_extension_rig_pair_wall import PROBE as WALL_PROBE

TIP_PROBE = r'''
fixture(job['params'].get('kind','B'))
obj=bpy.data.objects['Surface']; arm=bpy.data.objects['Rig']
# The wall fixture's isolated exclusion point is not part of the cap test.
obj.vertex_groups['Child'].remove(list(range(len(obj.data.vertices))))
bpy.context.view_layer.objects.active=arm
bpy.ops.object.mode_set(mode='EDIT')
for name,head in [('Positive',(.3,0,1)),('Negative',(-.3,0,1)),('Front',(0,-.1,1))]:
 bone=arm.data.edit_bones.new(name); bone.head=head; bone.tail=Vector(head)+Vector((0,0,.05))
bpy.ops.object.mode_set(mode='OBJECT')
validated.update(lateral_positive_bone='Positive',lateral_negative_bone='Negative',front_to_bone='Front')
group.update(id='Pair',op='pair_protrusion',params=validated)
tp={k:validated[k] for k in scope['PARAMETERS']['pair_tip'] if k in validated}
tp.update(subdivide_radii=[2.4,1.8,1.],normal_radius=2.,fill_radius=1.7,fill_ring=.7,fill_blend=.3,
 fill_depth=.03,fill_tolerance=.012,fill_rms_max=.0015,head_depth=.01,tail_length=.005,tip_radius=.5,
 tip_radius_max=.006,outer_level=.35,outer_radius=1.3,outer_ramp=.9,weight_depth=.015,test_scale=[1,1.4,1])
tip_group=dict(id='Tip',op='pair_tip',depends_on='Pair',params=tp,
 chains=[[dict(bone='TipLeft',parent='ExampleLeft')],[dict(bone='TipRight',parent='ExampleRight')]])
scope['parameters'](tip_group)
for key,value in [('subdivide_radii',[1,2]),('subdivide_radii',[1]*5),('subdivide_radii',[0]),
 ('fill_blend',1.7),('fill_depth',-1),('outer_level',1),('head_depth',0),('tip_radius_max',False)]:
 try: scope['parameters'](dict(tip_group,params=dict(tp,**{key:value})))
 except ValueError: pass
 else: raise AssertionError(('must reject',key,value))
bones={scope['bone_key'](b.name):b for b in arm.data.bones}
co,edges,owners,normals,faces=scope['mesh_arrays']([obj])
source_plan=scope['pair_plan'](group,validated,co,bones,scope['pair_surface']([obj]),owners)
placement=source_plan[2]['placement']
kind=job['params'].get('kind','B')
seam=job['params'].get('seam',False)
if kind!='C':
 tips=[Vector(row['tip']) for row in placement]
 R=math.sqrt(sum(row['marker_area'] for row in placement)/(2*math.pi))
 for vertex in obj.data.vertices:
  for t in tips:
   r=math.hypot(vertex.co.x-t.x,vertex.co.z-t.z)
   if r<.010:
    vertex.co.y+=.004*(1+.25*math.sin(r*math.pi/.002))
 if seam:
  import bmesh
  bm=bmesh.new(); bm.from_mesh(obj.data)
  selected=[e for e in bm.edges if all(abs(v.co.x-.15)<1e-6 for v in e.verts)]
  bmesh.ops.split_edges(bm,edges=selected)
  bm.to_mesh(obj.data); bm.free(); obj.data.update()
 if job['params'].get('noise',False):
  import random
  rng=random.Random(17)
  for vertex in obj.data.vertices:
   if any(tp['fill_radius']*R<=math.hypot(vertex.co.x-t.x,vertex.co.z-t.z)<=(tp['fill_radius']+tp['fill_ring'])*R for t in tips):
    vertex.co.y+=rng.uniform(-.008,.008)
  tp['fill_rms_max']=1e-5
obj.data.update()
co,edges,owners,normals,faces=scope['mesh_arrays']([obj])
placement=scope['pair_plan'](group,validated,co,bones,scope['pair_surface']([obj]),owners)[2]['placement']
# Keep the in-memory builder fixture, exercise the complete operation and export.
scope['_common'].reset_scene=lambda:None
scope['_common'].import_model=lambda path:None
before=len(obj.data.vertices)
seam_groups=[]
original_fit=scope['np'].linalg.lstsq
def capture_fit(*args,**kwargs):
 groups={}
 for v in obj.data.vertices: groups.setdefault(tuple(round(x,6) for x in v.co),[]).append(v.index)
 seam_groups.extend(indices for indices in groups.values() if len(indices)>1)
 return original_fit(*args,**kwargs)
scope['np'].linalg.lstsq=capture_fit
bad_tip=dict(tip_group,params=dict(tp,up_from_bone='Missing'))
rejected,_=scope['extension_bones']({'params':{'groups':[bad_tip,group]},'inputs':{'model':'fixture'}})
assert rejected['status']=='failed',rejected
groups=[tip_group,group]
if job['params'].get('descendant',False):
 groups.insert(0,dict(group,id='Marker',chains=[[dict(bone='MarkerLeft',parent='TipLeft')],[dict(bone='MarkerRight',parent='TipRight')]]))
result,outputs=scope['extension_bones']({'params':{'groups':groups},'inputs':{'model':'fixture'},'out_dir':str(Path(job['result']).parent)})
scope['np'].linalg.lstsq=original_fit
assert result['status']=='applied',result
if job['params'].get('descendant',False):
 assert arm.data.bones['MarkerLeft'].parent.name=='TipLeft'
 assert arm.data.bones['MarkerRight'].parent.name=='TipRight'
 assert 'Marker' in result['metrics'],result
elif kind=='C':
 assert result['groups']['Tip']['status']=='not_found',result
 assert len(obj.data.vertices)==before
 assert 'TipLeft' not in arm.data.bones and 'TipRight' not in arm.data.bones
 import struct
 raw=Path(outputs['model']).read_bytes(); size=struct.unpack_from('<I',raw,12)[0]; doc=json.loads(raw[20:20+size])
 assert not any(n.get('name') in ('TipLeft','TipRight') for n in doc['nodes'])
else:
 metrics=result['metrics']['Tip']; rows=metrics['placement']
 assert metrics['vertices_after']>metrics['vertices_before']
 for side,(name,parent),row in zip((1,-1),(('TipLeft','ExampleLeft'),('TipRight','ExampleRight')),rows):
  t,axis=Vector(row['tip']),Vector(row['axis'])
  assert (arm.data.bones[name].head_local-(t-axis*.01)).length<1e-4
  assert arm.data.bones[name].parent.name==parent
  if job['params'].get('noise',False):
   assert row['fill'].startswith('skipped:'),row
   assert (t-Vector(placement[0 if side==1 else 1]['tip'])).length<1e-4
  else:
   assert row['fill']=='applied',row
   assert abs(metrics['lift'][0 if side==1 else 1]-.004)<.0003,metrics
   for v in obj.data.vertices:
    delta=v.co-t; r=(delta-axis*delta.dot(axis)).length
    if r<(tp['fill_radius']-tp['fill_blend'])*row['radius']:
     r2=(v.co.x-side*.15)**2+(v.co.z-1.4)**2
     analytic=-.044-math.sqrt(.106**2-r2)
     assert abs(v.co.y-analytic)<.0003,(list(v.co),analytic,row)
  # Exact profile probes at core centre, core end and outer end.
 synthetic=[]; source_weights={}; expected={}
 for j,(parent,row) in enumerate(zip(('ExampleLeft','ExampleRight'),rows)):
  t,axis=Vector(row['tip']),Vector(row['axis']); a=axis.orthogonal().normalized()
  source_weights[parent]={}
  assert R<.012
  for r,factor in ((0.,1.),(.5*R,.35*704/729),(1.3*R,0.)):
   i=len(synthetic); synthetic.append(t+a*r); source_weights[parent][i]=.8
   expected[i]=factor
 sample=scope['tip_plan'](tip_group,dict(tp,weight_min=0),synthetic,(group,tp,(None,source_weights)),[dict(row) for row in rows],len(synthetic))
 for parent,name in (('ExampleLeft','TipLeft'),('ExampleRight','TipRight')):
  for i,retained in source_weights[parent].items():
   taken=sample[1][name].get(i,0)
   assert abs(retained+taken-.8)<1e-7
   assert abs(taken/.8-expected[i])<1e-6
 assert abs(sample[1]['TipLeft'][0]-.8)<1e-7
 empty={'ExampleLeft':{0:.8},'ExampleRight':{}}
 assert scope['tip_plan'](tip_group,tp,synthetic,(group,tp,(None,empty)),[dict(row) for row in rows],0) is None
 assert empty['ExampleLeft'][0]==.8
 # Re-plan the source alone on the same modified geometry: no top-four cut.
 co,edges,owners,normals,faces=scope['mesh_arrays']([obj])
 base_bones={scope['bone_key'](b.name):b for b in arm.data.bones}
 baseline=scope['pair_plan'](group,validated,co,base_bones,scope['pair_surface']([obj]),owners,pinned=placement)
 for name,parent,row in zip(('TipLeft','TipRight'),('ExampleLeft','ExampleRight'),rows):
  t,axis=Vector(row['tip']),Vector(row['axis']); checked=0
  for v in obj.data.vertices:
   weights={obj.vertex_groups[g.group].name:g.weight for g in v.groups}
   S,T=weights.get(parent,0),weights.get(name,0)
   expected=baseline[1][parent].get(v.index,0)
   assert abs(S+T-expected)<1e-4,(S,T,expected)
   if S+T and T:
    q=v.co-t; r=(q-axis*q.dot(axis)).length
    core=scope['smooth'](1-r/min(tp['tip_radius']*R,tp['tip_radius_max']))
    outer=scope['smooth']((tp['outer_radius']*R-r)/(tp['outer_ramp']*R))
    assert abs(T/(S+T)-(core+(1-core)*tp['outer_level']*outer))<1e-3
    checked+=1
  assert checked>10
 if seam: assert len(seam_groups)>10
 for indices in seam_groups:
  copies=[obj.data.vertices[i] for i in indices]
  if len(copies)<2: continue
  first=copies[0]
  weights=lambda v:{obj.vertex_groups[g.group].name:round(g.weight,6) for g in v.groups if g.weight>1e-7}
  assert all((v.co-first.co).length<1e-6 and weights(v)==weights(first) for v in copies)
 # Metrics-only accepts fully absent groups.
 missing=dict(tip_group,id='Absent',chains=[[dict(bone='AbsentLeft',parent='ExampleLeft')],[dict(bone='AbsentRight',parent='ExampleRight')]])
 data,_=scope['extension_bones']({'params':{'groups':[missing],'metrics_only':True},'inputs':{'model':'fixture'}})
 assert data['groups']['Absent']['status']=='not_found',data
Path(job['result']).write_text(json.dumps({'ok':True,'data':{},'outputs':{}}))
'''


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',choices=['crater','seam','geometry','refusal','descendant'])
    selected=parser.parse_args().case
    from app.blender import runner
    if not runner.status()['executable']:
        raise RuntimeError('Blender executable unavailable; no checks ran')
    prefix=WALL_PROBE[:WALL_PROBE.index("for kind in ('A','B','C','D'):")]
    prefix=prefix.replace("r2=(dx/.06)**2+(dz/.09)**2\n    y=-.1-.05*max(0.,1-r2)**.5", "q=.106**2-dx*dx-dz*dz\n    y=min(-.1,-.044-math.sqrt(q)) if q>=0 else -.1")
    prefix=prefix.replace("assert abs(s['reach'][0]-s['reach'][2])>.01, s", "assert s['marker_area']>0, s")
    with tempfile.TemporaryDirectory(prefix='pair-tip-') as tmp:
        root=Path(tmp)
        (root/'probe.py').write_text(prefix+TIP_PROBE)
        source=runner.SCRIPTS_DIR/'extension_bones.py'
        with patch.object(runner,'SCRIPTS_DIR',root):
            for label,options in [('crater',{}),('seam',{'seam':True}),('geometry',{'kind':'C'}),('refusal',{'noise':True}),('descendant',{'descendant':True})]:
                if selected and selected!=label: continue
                result=runner.run('probe',params={'source':str(source),**options},out_dir=root/label,timeout_s=120)
                assert result['ok'],(label,result)
                print('PASS pair tip',label)

if __name__=='__main__':
    main()
