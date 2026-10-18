"""Analytic pair tip checks, reusing the pair wall fixture builder.

The spherical cap has radius .106, height .05, centre y=-.044.
At the marker (x=.15,z=1.41), y=-.044-sqrt(.106**2-.01**2).
The omitted quadric term r^4/(8*.106^3) at r=.015 is .0054 mm;
linear interpolation at spacing 2.5 mm contributes below .03 mm.
The .3 mm tolerance covers fitting/interpolation, not a 4 mm crater.
rc=.0045, cap=.6*rc=.0027, lw=.005-cap=.0023. H at r=0,
rc/2, rc, rc+wall is .005, .0023+.0027*sqrt(3)/2, .0023, 0.
Full weight extends through a=rc+wall=.006; band b=.009 has midpoint
w=.5. With x=(r-a)/b, k=a/b=2/3, w+r*w'=1-4*x-5*x²+8*x³.
Its minimum is at x=2/3, giving -41/27 and Gmax=1+27/41=68/41.
Transfer T=w*S leaves S+T invariant. Test scale (1.4,1.6,1.4) gives
lift=.6*.005=.003 and diameter=1.4*.009=.0126. Extra subdivision
halves the 2.5 mm/8 spacing again to .15625 mm; the ring selection's
.75 mm half-width bounds diameter error by 2*1.4*.00075=.0021 m.
Top axial error includes sphere curvature and the .3 mm fit budget;
lift error is at most .6*.3 mm=.18 mm (use .3 mm).
Coincident copies receive identical positional fill, bake and weights.
Float32 positions at z~1.4 have <.12 micrometre error. Band weight error
is <1.5*.12e-6/.009=2e-5 (use 1e-4); at the cap edge the square
root amplifies this to <.0027*sqrt(2*.12e-6/.0045)=.020 mm
(use .025 mm for exact synthetic height probes).
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
 fill_depth=.03,fill_tolerance=.012,fill_rms_max=.0015,tip_diameter=.009,tip_length=.005,tip_round=.6,
 tip_wall=.0015,tip_band=.009,tip_subdivide=.009,weight_depth=.015,test_scale=[1.4,1.6,1.4])
tip_group=dict(id='Tip',op='pair_tip',depends_on='Pair',params=tp,
 chains=[[dict(bone='TipLeft',parent='ExampleLeft')],[dict(bone='TipRight',parent='ExampleRight')]])
scope['parameters'](tip_group)
for key,value in [('subdivide_radii',[1,2]),('subdivide_radii',[1]*5),('subdivide_radii',[0]),
 ('fill_blend',1.7),('fill_depth',-1),('tip_round',0),('tip_round',1.01),('tip_diameter',0),('tip_subdivide',-1),('tip_band',False)]:
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
original_plan=scope['tip_plan']; captured={}
def capture_plan(g,p,co,source,rows,before,meshes):
 captured['co']=[v.copy() for v in co]
 captured['source']={name:dict(values) for name,values in source[2][1].items()}
 return original_plan(g,p,co,source,rows,before,meshes)
scope['tip_plan']=capture_plan
bad_tip=dict(tip_group,params=dict(tp,up_from_bone='Missing'))
rejected,_=scope['extension_bones']({'params':{'groups':[bad_tip,group]},'inputs':{'model':'fixture'}})
assert rejected['status']=='failed',rejected
groups=[tip_group,group]
if job['params'].get('descendant',False):
 groups.insert(0,dict(group,id='Marker',chains=[[dict(bone='MarkerLeft',parent='TipLeft')],[dict(bone='MarkerRight',parent='TipRight')]]))
result,outputs=scope['extension_bones']({'params':{'groups':groups},'inputs':{'model':'fixture'},'out_dir':str(Path(job['result']).parent)})
scope['np'].linalg.lstsq=original_fit
scope['tip_plan']=original_plan
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
  assert (arm.data.bones[name].head_local-t).length<1e-4
  assert (arm.data.bones[name].tail_local-(t+axis*.005)).length<1e-4
  assert abs(row['girth_fold_free_max']-68/41)<1e-7
  assert arm.data.bones[name].parent.name==parent
  if job['params'].get('noise',False):
   assert row['fill'].startswith('skipped:'),row
   assert (t-Vector(placement[0 if side==1 else 1]['tip'])).length<1e-4
  else:
   assert row['fill']=='applied',row
   assert abs(metrics['lift'][0 if side==1 else 1]-.003)<.0003,metrics
   assert abs(row['stub_height']-.005)<.0003,row
   assert abs(row['diameter']-.0126)<.0021,row
   for v in obj.data.vertices:
    point=captured['co'][v.index]
    delta=point-t; axial=delta.dot(axis); r=(delta-axis*axial).length
    height=scope['tip_height'](r,tp) if axial>=-tp['weight_depth'] else 0.
    if r<.02:
     assert (v.co-point-axis*height).length<1e-6,(v.index,list(v.co),list(point),height)
    filled=v.co-axis*height
    if r<(tp['fill_radius']-tp['fill_blend'])*row['radius']:
     r2=(filled.x-side*.15)**2+(filled.z-1.4)**2
     analytic=-.044-math.sqrt(.106**2-r2)
     assert abs(filled.y-analytic)<.0003,(list(v.co),analytic,row)
  # Exported joint +Y must follow the planned axis after Y-up conversion.
 import struct
 from mathutils import Matrix,Quaternion
 raw=Path(outputs['model']).read_bytes(); size=struct.unpack_from('<I',raw,12)[0]; doc=json.loads(raw[20:20+size])
 parents={child:i for i,node in enumerate(doc['nodes']) for child in node.get('children',[])}
 def world(index):
  node=doc['nodes'][index]
  if 'matrix' in node:
   m=Matrix([node['matrix'][i:i+4] for i in range(0,16,4)]).transposed()
  else:
   q=node.get('rotation',[0,0,0,1]); m=Matrix.LocRotScale(Vector(node.get('translation',[0,0,0])),Quaternion((q[3],*q[:3])),Vector(node.get('scale',[1,1,1])))
  return world(parents[index])@m if index in parents else m
 for name,row in zip(('TipLeft','TipRight'),rows):
  index=next(i for i,n in enumerate(doc['nodes']) if n.get('name')==name)
  axis=Vector(row['axis']); converted=Vector((axis.x,axis.z,-axis.y))
  assert (world(index).to_3x3()@Vector((0,1,0))).normalized().angle(converted)<math.radians(1)
 # Exact height and transfer probes, independent of fixture vertex placement.
 synthetic=[]; source_weights={}; expected={}
 for j,(parent,row) in enumerate(zip(('ExampleLeft','ExampleRight'),rows)):
  t,axis=Vector(row['tip']),Vector(row['axis']); a=axis.orthogonal().normalized()
  source_weights[parent]={}
  rc=.0045
  for r,factor,height in ((0.,1.,.005),(rc/2,1.,.0023+.0027*math.sqrt(3)/2),(rc,1.,.0023),(.006,1.,0.),(.0105,.5,0.),(.015,0.,0.)):
   i=len(synthetic); synthetic.append(t+a*r); source_weights[parent][i]=.8
   expected[i]=(factor,t+a*r+axis*height)
 # Two skinned meshes with different local frames share the global coordinates.
 probes=[]
 for start in (0,6):
  data=bpy.data.meshes.new('Probe'); data.from_pydata([tuple(v-Vector((.02,0,0))) for v in synthetic[start:start+6]],[],[])
  mesh=bpy.data.objects.new('Probe',data); bpy.context.collection.objects.link(mesh)
  mesh.location.x=.02; mesh.vertex_groups.new(name='Base').add(list(range(6)),1.,'REPLACE')
  mesh.modifiers.new('Skin','ARMATURE').object=arm
  probes.append(mesh)
 bpy.context.view_layer.update()
 sample=scope['tip_plan'](tip_group,dict(tp,weight_min=0),synthetic,(group,tp,(None,source_weights)),[dict(row) for row in rows],len(synthetic),probes)
 for offset,mesh in zip((0,6),probes):
  assert all((mesh.matrix_world@v.co-synthetic[offset+v.index]).length<1e-7 for v in mesh.data.vertices)
  bpy.data.objects.remove(mesh,do_unlink=True)
 for parent,name in (('ExampleLeft','TipLeft'),('ExampleRight','TipRight')):
  for i,retained in source_weights[parent].items():
   taken=sample[1][name].get(i,0)
   assert abs(retained+taken-.8)<1e-7
   assert abs(taken/.8-expected[i][0])<1e-4,(i,taken/.8,expected[i][0],list(synthetic[i]))
   assert (synthetic[i]-expected[i][1]).length<.000025
 assert abs(sample[1]['TipLeft'][0]-.8)<1e-7
 empty={'ExampleLeft':{0:.8},'ExampleRight':{}}
 assert scope['tip_plan'](tip_group,tp,synthetic,(group,tp,(None,empty)),[dict(row) for row in rows],0,[]) is None
 assert empty['ExampleLeft'][0]==.8
 # Compare transfer to the pass-2 source weights before baking.
 for name,parent,row in zip(('TipLeft','TipRight'),('ExampleLeft','ExampleRight'),rows):
  t,axis=Vector(row['tip']),Vector(row['axis']); checked=0
  for v in obj.data.vertices:
   weights={obj.vertex_groups[g.group].name:g.weight for g in v.groups}
   S,T=weights.get(parent,0),weights.get(name,0)
   expected=captured['source'][parent].get(v.index,0)
   assert abs(S+T-expected)<1e-4,(S,T,expected)
   if S+T and T:
    q=v.co-t; r=(q-axis*q.dot(axis)).length
    factor=1. if r<=.006 else scope['smooth']((.015-r)/.009)
    assert abs(T/(S+T)-factor)<1e-3
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
    prefix=WALL_PROBE[:WALL_PROBE.index("for kind in ('A','B','C','D','E'):")]
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
