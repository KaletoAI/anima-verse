"""Offline full-planner check on a rigged GLB fixture; all outputs are temporary.

Usage: .venv/bin/python scripts/smoke_extension_rig_robustness.py
       --model FIXTURE.glb --declaration MANIFEST.yaml --group GROUP
       [--target-height-m 1.86]

Hand derivation: a square section with corners (+/-30,+/-30) mm has
radius sqrt(2)*30 = 42.426 mm and arclength centre (0,0). It fits a
43 mm tube, but cannot fit a 42 mm tube. Splitting each planar triangle
into four triangles leaves the contour, radius and centre unchanged.
An open three-sided section is not a closed ring. These checks establish
what the stop measures without taking expected numbers from the solver.
For a square prism with 0.2 mm axial spacing, five rows lie between adjacent
1 mm cuts. All rows before the stop must be captured; selecting only faces
that touch a cut would miss the three interior rows. Its 12 mm open end must
stop at 11--12 mm with a 1 mm probe spacing, at either coarse or fine density.
An asymmetric open continuation below a 10.4 mm end fails the first probe
of the next slab: depth stays 10 mm and the last ring centre stays (0,0).

The supplied fixture also goes through appendage_plan, including selection,
axis estimation, segmentation and weight planning. Move the declared anchor
and reference frames by +/-2 mm with geometry fixed. A stable geometry stop
must stay within 3 mm (three 1 mm sampling steps), or 25 percent of the
smaller depth; captured membership must remain positive with max/min <=1.5.
Every captured negative-section point must fit the same recorded tube used
by growth and completion. These bounds are acceptance requirements, not
snapshots of one fixture's output.

For successful growth at zero frame shift, only the root moves into the torso.
The back/up bisector (0,1,1) has length sqrt(2), so the solved pivot depth s gives
head = attachment + (0,s/sqrt(2),s/sqrt(2)), with s>=root_depth=.03 m.
The torso chord can require more than .03 m to reach root_wall_margin.
With root_depth=0 and root_wall_margin=-1 the root equals attachment.
All subsequent heads and
the tip must be identical within 1e-9 m: splits, slab recentring and axis
length still use the attachment station, independently of root_depth.
Compare explicit minimum depths .03 and 0, regardless of the declaration. Per-link
weights must agree within 1e-9 and affected sets must be identical: weight
planning continues to use the attachment polyline when the root moves.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

PROBE = r'''
import bpy, json, math, sys, types
from pathlib import Path
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
p=job['params']; source=Path(p['operation'])
scope={'__file__':str(source)}
exec(compile(source.read_text().split('_common.main(')[0],str(source),'exec'),scope)
# A square prism has four side quads; cuts at z=0 are the square above.
points=[Vector((x,y,z)) for z in (-.01,.01) for x,y in ((-.03,-.03),(.03,-.03),(.03,.03),(-.03,.03))]
triangles=[]
for a in range(4):
    b=(a+1)%4
    for ids in ((a,b,b+4),(a,b+4,a+4)):
        triangles.append((tuple(points[i] for i in ids),tuple(points[i].z for i in ids),ids))
ring=scope['section_ring'](triangles,Vector(),Vector((0,0,1)),0,.043)
assert ring and ring[1].length<1e-8 and abs(ring[2]-math.sqrt(2)*.03)<1e-8, ring
assert scope['section_ring'](triangles,Vector(),Vector((0,0,1)),0,.042) is None
assert scope['section_ring'](triangles[:-2],Vector(),Vector((0,0,1)),0,.043) is None
subdivided=[]
for vertices,heights,ids in triangles:
    a,b,c=vertices; ab,bc,ca=(a+b)/2,(b+c)/2,(c+a)/2
    for tri in ((a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)):
        subdivided.append((tri,tuple(v.z for v in tri),ids))
r=scope['section_ring'](subdivided,Vector(),Vector((0,0,1)),0,.043)
assert r and (r[1]-ring[1]).length<1e-8 and abs(r[2]-ring[2])<1e-8, r
# A second square touching the first at a corner introduces a degree-four
# branch. The combined cut is not a separate ring around the axis.
touching=[]
for vertices,heights,ids in triangles:
    shifted=tuple(v+Vector((.06,.06,0)) for v in vertices)
    touching.append((shifted,heights,ids))
assert scope['section_ring'](triangles+touching,Vector(),Vector((0,0,1)),0,.1) is None
growth_depths=[]
for spacing in (.002,.0002):
    positions,links,polygons,ns=[],[],[],[]
    for k in range(round(.032/spacing)+1):
        z=-.012+k*spacing
        for x,y in ((-.03,-.03),(.03,-.03),(.03,.03),(-.03,.03)):
            positions.append(Vector((x,y,z))); ns.append(Vector((x,y,0)).normalized())
        off=4*k
        links.extend((off+j,off+(j+1)%4) for j in range(4))
        if k:
            links.extend((off+j-4,off+j) for j in range(4))
            polygons.extend((off+j-4,off+(j+1)%4-4,off+(j+1)%4,off+j) for j in range(4))
    part={i for i,c in enumerate(positions) if c.z>=0}
    settings={'base_slice_size':.01,'base_radius_margin':1.1,'base_extension_max':.75,
              'cut':.15,'weld_distance':.00001,'weld_normal_min':.5}
    captured,welded,centres,t,reason,table=scope['grow_attachment'](
        positions,links,part,Vector(),Vector((0,0,1)),.02,settings,ns,polygons)
    depth=-t*.02*1000; growth_depths.append(depth)
    assert 11-1e-6<=depth<=12+1e-6, (spacing,depth,reason)
    expected={i for i,c in enumerate(positions) if t*.02+1e-7<=c.z<0}
    assert expected<=captured, (spacing,len(expected-captured))
    for i in expected:
        high=math.ceil(settings['cut']*.02/.01)*.01/.02
        matched=False
        for row in table:
            if row['accepted'] and row['t']<=positions[i].z/.02<high:
                assert i in row['_surface'], (spacing,i)
                matched=True; break
            high=row['t']
        assert matched, (spacing,i)
assert max(growth_depths)-min(growth_depths)<=1+1e-6, growth_depths
positions,links,polygons,ns=[],[],[],[]
for k in range(17):
    z=-.0104+k*.002
    for x,y in ((-.03,-.03),(.03,-.03),(.03,.03),(-.03,.03)):
        positions.append(Vector((x,y,z))); ns.append(Vector((x,y,0)).normalized())
    off=4*k
    links.extend((off+j,off+(j+1)%4) for j in range(4))
    if k:
        links.extend((off+j-4,off+j) for j in range(4))
        polygons.extend((off+j-4,off+(j+1)%4-4,off+(j+1)%4,off+j) for j in range(4))
links.append((1,len(positions)))
positions.append(Vector((.04,-.02,-.0106))); ns.append(Vector((1,0,0)))
part={i for i,c in enumerate(positions) if c.z>=0}
result=scope['grow_attachment'](positions,links,part,Vector(),Vector((0,0,1)),.02,settings,ns,polygons)
assert abs(result[3]*.02+.01)<1e-8, result[3]
assert abs(result[2][-1].x)<1e-6 and abs(result[2][-1].y)<1e-6, result[2][-1]
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
g=p['group']; params=scope['parameters'](g)
original={scope['bone_key'](b.name):b for b in arm.data.bones}
keys={scope['bone_key'](params[k]) for k in ('anchor_bone','up_from_bone','up_to_bone','lateral_positive_bone','lateral_negative_bone','front_from_bone','front_to_bone')}
results=[]
for shift in (-.002,0,.002):
    bones={k:types.SimpleNamespace(name=b.name,head_local=b.head_local.copy(),tail_local=b.tail_local.copy()) for k,b in original.items()}
    for key in keys:
        bones[key].head_local+=Vector((shift,-shift,shift))
        bones[key].tail_local+=Vector((shift,-shift,shift))
    run_params=dict(params,root_depth=.03) if shift==0 else params
    plan=scope['appendage_plan'](g,run_params,co,edges,bones,normals,faces)
    m=plan[2]; base=Vector(m['segment_axis_base']); axis=(Vector(m['segment_axis_tip'])-base).normalized()
    assert not m['leak'], m
    assert m['stem_vertices_captured']>0, m
    if shift==0:
        attachment=Vector(m['attachment'])
        depth=m['pivot']['depth']
        assert depth>=run_params['root_depth'], m['pivot']
        expected=attachment+Vector((0,1,1)).normalized()*depth
        head=Vector(m['placement'][0]['head'])
        assert (head-expected).length<=1e-6, (list(head),list(expected))
        unmoved=[Vector(v) for v in m['weight_joints']]
        ceiling=Vector(m['pivot']['gap_apex'])
        assert attachment.y < ceiling.y < attachment.y+.12, m['pivot']
        assert abs(ceiling.z-attachment.z)<=.03, m['pivot']
        for start in (1,2):
            _,found,gap=scope['torso_chord'](co,faces,attachment,unmoved,start_index=start)
            assert gap['joint_index']==start and (found-ceiling).length<=1e-6, gap
        zero_params=dict(run_params,root_depth=0.,root_wall_margin=-1.)
        zero_plan=scope['appendage_plan'](g,zero_params,co,edges,bones,normals,faces)
        zero=zero_plan[2]
        assert zero['pivot']['depth']==0., zero['pivot']
        assert plan[1].keys()==zero_plan[1].keys()
        for name,weights in plan[1].items():
            unshifted_weights=zero_plan[1][name]
            assert weights.keys()==unshifted_weights.keys(), name
            for i,value in weights.items():
                assert abs(value-unshifted_weights[i])<=1e-9, (name,i,value,unshifted_weights[i])
        assert plan[3]==zero_plan[3], (len(plan[3]),len(zero_plan[3]))
        assert (Vector(zero['placement'][0]['head'])-attachment).length<=1e-9, zero['placement'][0]
        assert len(m['placement'])==len(zero['placement'])
        for placed,unshifted in zip(m['placement'][1:],zero['placement'][1:]):
            assert (Vector(placed['head'])-Vector(unshifted['head'])).length<=1e-9, (placed,unshifted)
        assert (Vector(m['placement'][-1]['tip'])-Vector(zero['placement'][-1]['tip'])).length<=1e-9
        assert abs(m['axis_length']-zero['axis_length'])<=1e-9
        assert (Vector(m['root_offset'])-(head-attachment)).length<=1e-9, m['root_offset']
    for i in plan[3]:
        t=(co[i]-base).dot(axis)/m['segment_axis_length']
        if t>=0: continue
        high=math.ceil(params['cut']*m['segment_axis_length']/params['base_slice_size'])*params['base_slice_size']/m['segment_axis_length']
        matched=False
        for row in m['base_slice_table']:
            if row['accepted'] and row['t']<=t<high:
                delta=co[i]-Vector(row['tube_centre'])
                assert (delta-axis*delta.dot(axis)).length<=row['tube_radius']+1e-6
                matched=True; break
            high=row['t']
        assert matched, (i,t,m['base_slice_table'])
    results.append({'shift_mm':shift*1000,'depth_mm':m['base_stop_depth_mm'],'capture':m['stem_vertices_captured'],
                    'root_head':m['placement'][0]['head'],'attachment':m['attachment'],'pivot':m['pivot']})
depths=[r['depth_mm'] for r in results]; counts=[r['capture'] for r in results]
assert max(depths)-min(depths)<=max(3,.25*min(depths))+1e-6, results
assert max(counts)/min(counts)<=1.5, results
Path(job['result']).write_text(json.dumps({'ok':True,'data':{'perturbations':results},'outputs':{}}))
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
    group=next(copy.deepcopy(rig) for s in manifest['body_slots'] for rig in s.get('rigs',[]) if rig.get('id')==args.group)
    group.update(enabled=True,flip=False)
    with tempfile.TemporaryDirectory(prefix='extension-robustness-') as tmp:
        root=Path(tmp)
        os.environ['STORAGE_DIR']=str(root/'storage'); os.environ['INSTANCE_DIR']=str(root/'instance')
        from app.core import paths
        paths.init(root/'storage')
        paths.init_instance(root/'instance')
        from app.blender import runner
        normalized=runner.run('normalize',inputs={'model':args.model},params={'target_height_m':args.target_height_m},out_dir=root/'normalized',timeout_s=180)
        assert normalized['ok'], normalized
        operation=runner.SCRIPTS_DIR/'extension_bones.py'
        scripts=root/'scripts'; scripts.mkdir(); (scripts/'probe.py').write_text(PROBE)
        original_scripts=runner.SCRIPTS_DIR
        runner.SCRIPTS_DIR=scripts
        try:
            result=runner.run('probe',inputs={'model':Path(normalized['outputs']['model'])},params={'operation':str(operation),'group':group},out_dir=root/'probe',timeout_s=600)
        finally:
            runner.SCRIPTS_DIR=original_scripts
        assert result['ok'], result
        print('PASS closed-section analytic and subdivision checks')
        print('PASS appendage_plan frame perturbations',json.dumps(result['data']))

if __name__=='__main__':
    main()
