"""Check extension operations and the real publication lifecycle.

Usage: .venv/bin/python scripts/smoke_extension_rig_p1.py

Hand-derived fixture values (metres, Blender front -Y/up +Z): surface front
is y=-.10. Two radius-.05 spheres centred at (+/-.10,-.18,1.40)
have geometric apex (+/-.10,-.23,1.40), with no UV texture.
Tangent slope (.13/s) is maximal at the first sample outside the
sphere, s=.051 (1 mm beyond the sphere rim). All five non-lateral wall points have y=-.10.
Their mean x offset is -(1+sqrt(2))*.051/5=-.02462498 per side,
so heads are (+/-.07537502,-.06,1.40), depth=.13. The cylinder has radius .03,
centre y=-.16, rings z=.80,.81,...,.98. The anchor z=.98 selects its
UPPER end as attachment. A cut .15 along length .18 falls at z=.953:
rings .80 through .95 remain connected; the attachment ring adds .96
through .98. Near rings .95-.98 average z=.965; inset .02 gives root
z=.985. Far rings .80-.82 average .81, so chain length=.175 and a
.45 split gives first length=.07875. At cylinder vertex (x=.03,y=-.16,z=.91), t=(.985-.91)/.175=3/7.
With ramp=.25, w=1 at t=3/7. The linear joint blend is
(3/7-(.45-.06))/.12, hence Link1=1-blend, Link2=blend.
Source weights: Hips=.20, Spine=.35, Spine1=.25, LeftUpLeg=.20.
The entire .20 LeftUpLeg weight moves to Hips before attenuation:
Hips=.40(1-w); Spine=.35(1-w); Spine1=.25(1-w);
LeftUpLeg=0. This interior blend probe has only the two extension influences.
The separate radial probe verifies full surface weight independent of contact_ramp. At (.2,.1,1.1), outside both
operation envelopes, the four original per-joint weights stay unchanged.
At the pair apex (.1,-.23,1.4), envelope w=1 leaves only ExampleLeft=1.
Probe (.12,-.23,1.4): R=.051, scaled R=.05865, r=.02; inside .6 plateau, w=1.
Probe (.14,-.23,1.4): radial t=(1-.04/.05865)/.4=1865/2346;
w=t*t*(3-2*t), depth factor=1. Retain the new joint and the three
largest source influences (.35,.25,.20), divide by w+.8*(1-w).
A second source assigns five equal .20 weights outside both envelopes.
Its lowest four joint indices survive with .25 each (joint-index tie rule).
All exported vertices have at most four influences and weights sum to 1; source
base-joint frames remain unchanged. Repetition preserves bytes; changing
only the test angle reconstructs the same weights from the clean prerig.
The contact fixture joins the radius-.03 cylinder to a radius-.06 cylinder
centred at x=.0902,y=-.16 along z=.80-.98, across a .0002 gap within
weld_distance=.0005. Opposing normals keep the surfaces separate. The 19*32=608 part samples
are all inside pass-0 R=1.35*.03=.0405. No sample beyond the final R is captured.
Every captured vertex loses all declared source-joint weights.
A single-link radial-ramp probe declares protrusion_threshold=.02 so all
angular samples enter the axis fit, centred at y=-.16. Both opposite
(+/-.03,-.16,.91) probes have chain weight 1 even with contact_ramp=.011.
The physical attachment transition is capped at .01 m from the root; all
interior surface vertices have chain weight 1, including the contact side.
The second contact fixture has radius .03, centre y=-.0998; its nearest
surface is .0002 m behind the tube's back y=-.13. Opposing normals prohibit
welding. All 608 blob positions stay unweighted even with contact_ramp=.08.
For exact contact (body centre y=-.10), the tangent copies at y=-.13
share exported weights despite separate segmentation. With following disabled,
flat side normals give two tube and two body copies at z=.91: their average
has chain total .5 and body shares .175,.125,.1,.1. Both chain links and the
two largest body shares survive, so normalize .5+.175+.125=.8 to obtain
chain total 5/8. At z=.80 the cap adds a third full tube copy: three tube
and two body copies average to chain total .6 and body .14,.1,.08,.08.
One chain link and three body influences survive, giving .6/.92=15/23.
Body positions away from this seam stay unweighted.
The offset fixture adds a 2 mm front bulge: for theta_j=2*pi*j/32,
x=.03*cos(theta_j), y=-.16+.03*sin(theta_j)-.002*max(0,-sin(theta_j)).
The reference is -.10 and threshold .061 selects the 15 negative-sine samples.
Their mean offset is -.032*sum(sin(pi*j/16),j=1..15)/15=-.02166010 m;
half-width=.03*cos(pi/16), hence R0=.03972180. On each ring C0 contains
17 angular positions. With q=.95 and margin=1.2, the next centroid offsets,
radii and angular counts (ordinary finite sums and interpolated sorted distances)
are (-.01911185,.04268464,21), (-.01382072,.04503358,32), and
(-.00063457,.03756308,32). Every ring has the same cross-section, so PCA
is vertical and both axis ends lie only .635 mm from (x=0,y=-.16), below 2 mm.
The touching radius-.06 cylinder uses eight angular positions here: only its
contact at x=.0302 lies inside these radii; its next samples have radial distance
sqrt((.0902-.06/sqrt(2))**2+(.06/sqrt(2))**2)>.063 m. Opposing normals
prevent that contact from joining the part. All 19*32=608
part positions, including the back y=-.13, must carry positive extension weights
with the declared .25 axial ramp, while all other contact-cylinder positions
retain their source weights. Inside the cut window, 0.9*R_final=.03380677
exceeds the largest part radial distance .03136543, hence uncaptured_in_part=0;
bounded selection implies captured_beyond_radius=0 and full transfer implies
thigh_weight_in_part=0. The old unrefined axis misses the back by .05166010>R0.
The older exact attenuation probes explicitly keep margin=1.35 (R=.0405),
while refinement fixtures use the documented margin=1.2.
The curved tube has radius .006 around a circular centreline of R=.36 and
angle30 degrees: C(theta)=(0,-.20+.36*(cos(theta)-cos15),.89-.36*sin(theta)),
theta=-15..15. Nineteen equally spaced angle rings include -15,-5,5,15.
Splits=(1-sin5/sin15)/2 and its complement select those inner joints.
Equal 10-degree arc segments give chord directions differing by10 degrees.
Slab averaging may differ from C by at most2 mm; bends must stay within1 degree.
The .01 m physical attachment cap shortens the declared t=.2 ramp.
The second-ring chord length is 2*.36*sin(30/18/2 degrees)=.0104716 m.
First-ring probe weights are zero, second-ring probes are fully on link1;
interior cores on all three links are fully weighted outside the blend zones.
The offset coverage fixture also verifies that contact_ramp=.005 cannot
reduce the weight of a retained surface vertex.
All storage and clip/rig paths are temporary. Missing Blender is a skip.
"""
import copy
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

DECLARED_PARAMS = {'pair_protrusion': {'band_lower_bone': 'Spine1',
                     'band_upper_bone': 'LeftArm',
                     'band_lower_offset': 0.02,
                     'band_upper_offset': -0.04,
                     'lateral_min': 0.03,
                     'lateral_max': 0.17,
                     'marker_search_radius': 0.07,
                     'marker_grid_step': 0.0025,
                     'marker_score_min': 6.0,
                     'marker_yellow_weight': 0.5,
                     'marker_dark_min': 0.55,
                     'marker_light_max': 3.0,
                     'marker_area_min': 0.0001,
                     'marker_area_max': 0.003,
                     'marker_spread_max': 0.02,
                     'marker_pair_dz': 0.02,
                     'marker_pair_dx': 0.03,
                     'boundary_directions': 8,
                     'boundary_s_min': 0.051,
                     'boundary_s_max': 0.13,
                     'boundary_step': 0.0025,
                     'exclude_bones': [],
                     'exclude_weight': 0.3,
                     'head_wall_depth': 0.04,
                     'radius_plateau': 0.6,
                     'radius_scale': 1.15,
                     'side_margin': 0.005,
                     'front_margin': 0.03,
                     'depth_ramp': 0.04,
                     'weight_min': 0.003,
                     'test_rotation_deg': [-15, 0, 0],
                     'test_scale': [1, 1.12, 1]},
 'appendage_chain': {'anchor_bone': 'Hips',
                     'anchor_offset': [0, 0, -0.09],
                     'search_z_min': -0.26,
                     'search_z_max': 0.06,
                     'reference_lateral_min': 0.09,
                     'reference_lateral_max': 0.13,
                     'slice_size': 0.01,
                     'candidate_lateral_max': 0.1,
                     'part_half_width': 0.06,
                     'protrusion_threshold': 0.035,
                     'axis_initial': [0, -0.5, -1],
                     'axis_iterations': 50,
                     'root_depth': 0.03,
                     'root_wall_margin': 0.01,
                     'chain_split': [0.45],
                     'cut': 0.15,
                     'weld_distance': 0.0005,
                     'window_length_factor': 0.6,
                     'window_margin': 0.08,
                     'leak_t_limit': 1.6,
                     'leak_radius_limit': 0.09,
                     'segment_radius_factor': 1.35,
                     'segment_radius_percentile': .95,
                     'segment_radius_margin': 1.2,
                     'segment_radius_growth_max': 1.5,
                     'segment_passes': 3,
                     'segment_min_vertices': 3,
                     'contact_ramp': 0.01,
                     'contact_follow_distance': .025,
                     'contact_inside_distance': 0.,
                     'contact_follow_weight': 0.,
                     'base_slice_size': .01,
                     'base_radius_margin': 1.6,
                     'base_growth_max': 1.8,
                     'base_extension_max': .35,
                     'base_history_slices': 5,
                     'attachment_ring_max': .01,
                     'weld_normal_min': .5,
                     'ring_radius_percentile': 0.9,
                     'ring_radius_scale': 1.15,
                     'near_slice_margin': 0.05,
                     'far_slice_fraction': 0.85,
                     'attachment_inset': 0.02,
                     'weight_ramp': 0.25,
                     'fallback_half_width': 0.075,
                     'fallback_z_margin': 0.04,
                     'fallback_front_fraction': 0.3,
                     'fallback_front_ramp': 0.02,
                     'fallback_side_ramp': 0.025,
                     'fallback_top_margin': 0.02,
                     'fallback_top_ramp': 0.03,
                     'centerline_slab': 0.08,
                     'link_blend': 0.06,
                     'reweight_factor': 2.0,
                     'reweight_from': [],
                     'weight_min': 0.003,
                     'test_rotation_deg': [-35, 0, 0],
                     'test_rotation_decay': 0.4,
                     'test_scale': [1, 1, 1]}}
for _params in DECLARED_PARAMS.values():
    _params.update(up_from_bone='Hips', up_to_bone='Head', up_distance_min=.15,
                   up_distance_max=2., lateral_positive_bone='LeftArm',
                   lateral_negative_bone='RightArm', front_from_bone='LeftFoot',
                   front_to_bone='LeftToeBase', front_distance_min=.0001)


FIXTURE = r'''
import bpy, json, math, sys
from pathlib import Path
args=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
p=args['params']
bpy.ops.wm.read_factory_settings(use_empty=True)
armdata=bpy.data.armatures.new('Rig')
arm=bpy.data.objects.new('Rig',armdata)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active=arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for i,name in enumerate(p['bones']):
    b=armdata.edit_bones.new('mixamorig:'+name)
    x,y,z=0,0,1.05
    if name=='Head': z=1.7
    elif name=='Spine1': z=1.2
    elif name=='Spine2': z=1.35
    elif name=='Spine': z=1.12
    elif name=='LeftArm': x,z=.25,1.5
    elif name=='RightArm': x,z=-.25,1.5
    elif name.endswith('Foot'): x,y,z=(.1 if name.startswith('Left') else -.1),0,.1
    elif name.endswith('ToeBase'): x,y,z=(.1 if name.startswith('Left') else -.1),-.12,.08
    elif name!='Hips': x,z=(.2 if name.startswith('Left') else -.2),.5+i*.01
    b.head=(x,y,z); b.tail=(x,y,z+.04)
for b in armdata.edit_bones:
    if b.name!='mixamorig:Hips': b.parent=armdata.edit_bones['mixamorig:Hips']
bpy.ops.object.mode_set(mode='OBJECT')
vertices=[]; faces=[]
# Regular reference-box samples make the per-slice surface exact.
for y in (-.1,.1):
    off=len(vertices)
    for iz in range(71):
        for ix in range(41): vertices.append((-.2+ix*.01,y,.8+iz*.01))
    for iz in range(70):
        for ix in range(40):
            a=off+iz*41+ix
            faces.append((a,a+1,a+42,a+41))
# Close the grid-backed box at its sides, top and bottom.
layer=71*41
for iz in range(70):
    for ix in (0,40):
        a=iz*41+ix; b=(iz+1)*41+ix
        faces.append((a,b,b+layer,a+layer))
for ix in range(40):
    for iz in (0,70):
        a=iz*41+ix; b=a+1
        faces.append((a,b,b+layer,a+layer))
for sign in (1,-1):
    # UV sphere with exact equatorial -Y sample, .05 radius.
    off=len(vertices)
    for iz in range(17):
        phi=math.pi*iz/16
        for j in range(32):
            theta=2*math.pi*j/32
            vertices.append((sign*.1+.05*math.sin(phi)*math.cos(theta),-.18+.05*math.sin(phi)*math.sin(theta),1.4+.05*math.cos(phi)))
    for iz in range(16):
        for j in range(32):
            a=off+iz*32+j; b=off+iz*32+(j+1)%32
            faces.append((a,b,b+32,a+32))
start=len(vertices)
for iz in range(19):
    for j in range(32):
        a=2*math.pi*j/32
        if p.get('curved'):
            theta=math.radians(-15+30*iz/18)
            vertices.append((.006*math.cos(a),-.20+.36*(math.cos(theta)-math.cos(math.radians(15)))+.006*math.sin(a),.89-.36*math.sin(theta)))
        else:
            vertices.append((.03*math.cos(a),-.16+.03*math.sin(a)-(.002*max(0,-math.sin(a)) if p.get('bulged') else 0),.8+iz*.01))
for iz in range(18):
    for j in range(32):
        a=start+iz*32+j; b=start+iz*32+(j+1)%32
        faces.append((a,b,b+32,a+32))
# Cylinder attaches to the wall only at its upper ring.
for j in range(0 if p.get('curved') else 32):
    a=start+18*32+j; b=start+18*32+(j+1)%32
    c=len(vertices); vertices.extend(((vertices[a][0],-.1,.98),(vertices[b][0],-.1,.98)))
    faces.append((a,b,c+1,c))
if p.get('shared_blob'):
    # Shared faces fuse the tube's x=.03 side to a strip at x=.06.
    # D=.1; boundary x=.06 gives d=0, x=.11 gives d=D/2, x=.16 d=D.
    # The .05 outward edges keep the nearest-tube guard satisfied at D/2.
    a=start+11*32; b=start+12*32
    off=len(vertices)
    for x in (.06,.11,.16,.21):
        vertices.extend(((x,-.16,.91),(x,-.16,.92)))
    faces.append((a,b,off+1,off))
    for k in range(3):
        c=off+2*k; faces.append((c,c+1,c+3,c+2))
if p.get('fused'):
    # Tangent contact; coarse samples in the offset fixture isolate the centre proof.
    count=8 if p.get('bulged') else 32
    off=len(vertices)
    for iz in range(19):
        for j in range(count):
            angle=2*math.pi*j/count
            vertices.append((.0902+.06*math.cos(angle),-.16+.06*math.sin(angle),.8+iz*.01))
    for iz in range(18):
        for j in range(count):
            a=off+iz*count+j; b=off+iz*count+(j+1)%count
            faces.append((a,b,b+count,a+count))
if p.get('under_contact'):
    # A sharp end cap exports separate normal copies at the same positions.
    faces.append(tuple(start+j for j in reversed(range(32))))
    # The .03 tube rests against another .03 surface across a .0002 gap.
    # This is inside the .0005 weld tolerance, but the facing normals oppose.
    off=len(vertices)
    for iz in range(19):
        for j in range(32):
            angle=2*math.pi*j/32
            vertices.append((.03*math.cos(angle),(-.1 if p.get('exact_contact') else -.0998)+.03*math.sin(angle),.8+iz*.01))
    for iz in range(18):
        for j in range(32):
            a=off+iz*32+j; b=off+iz*32+(j+1)%32
            faces.append((a,b,b+32,a+32))
off=len(vertices); vertices.extend(((.12,-.23,1.4),(.14,-.23,1.4),(.14,-.23,1.401))); faces.append((off,off+1,off+2))
off=len(vertices); vertices.extend(((0,.23,0),(0,.23,1.7),(.001,.23,0))); faces.append((off,off+1,off+2))
meshdata=bpy.data.meshes.new('Surface')
meshdata.from_pydata(vertices,[],faces); meshdata.update()
obj=bpy.data.objects.new('Surface',meshdata); bpy.context.collection.objects.link(obj)
mod=obj.modifiers.new('Skin','ARMATURE'); mod.object=arm
obj.parent=arm
source_weights=[('Hips',.2),('Spine',.35),('Spine1',.25),('LeftUpLeg',.2)]
if p.get('shared_blob'): source_weights=[('Hips',.08),('Spine',.2),('Spine1',.12),('LeftUpLeg',.6)]
if p.get('ties'): source_weights=[('Hips',.2),('Spine',.2),('Spine1',.2),('Spine2',.2),('LeftUpLeg',.2)]
for name,weight in source_weights:
    vg=obj.vertex_groups.new(name='mixamorig:'+name); vg.add(list(range(len(vertices))),weight,'REPLACE')
mat=bpy.data.materials.new('Surface')
image=bpy.data.images.new('Colour',width=8,height=8)
image.pixels=[.5,.6,.7,1]*64
tex=mat.node_tree.nodes.new('ShaderNodeTexImage'); tex.image=image
mat.node_tree.links.new(tex.outputs['Color'],mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
obj.data.materials.append(mat)
out=Path(args['out_dir'])/'model.glb'
bpy.ops.export_scene.gltf(filepath=str(out),export_format='GLB',export_yup=True,export_all_influences=True)
Path(args['result']).write_text(json.dumps({'ok':True,'data':{},'outputs':{'model':str(out)}}))
'''


# Hand values for the shared-face strip below: D=.1, w0=.6.
# Seed, D/2, D and beyond give .6,.3,0,0; original .6 source-joint
# weight qualifies locally and remains present after the four-slot truncation.
FOLLOW_FIXTURE = r'''
import json, sys, types
from pathlib import Path
from mathutils import Vector
args=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(args['params']['scripts'])/'extension_bones.py'
m=types.ModuleType('operation'); m.__file__=str(source)
exec(compile(source.read_text().replace('_common.main(extension_bones)', ''),str(source),'exec'),m.__dict__)
# Shared quad joins tube 0,1 to blob 2,3. Boundary d=0, then D/2 edges.
# smoothstep(1,.5,0)=(1,.5,0), so .6*(1,.5,0)=(.6,.3,0).
D=.025
co=[Vector(c) for c in [(0,0,.2),(0,.001,.2),(0,0,.2),(0,.001,.2),
                       (D/2,0,.2),(D,0,.2),(1.5*D,0,.2),(0,0,.005),(0,0,-.01)]]
edges=[(0,1),(1,3),(3,2),(2,0),(2,4),(4,5),(5,6),(2,7),(2,8)]
faces=[(0,1,3,2)]
p={'contact_follow_distance':D,'contact_follow_weight':.6,'attachment_ring_max':.01,'chain_split':[]}
weights={'Link':{0:1.,1:1.}}
metrics={'placement':[{'head':[0,0,0],'tip':[0,0,.3]}],
         'segment_axis_base':[0,0,0],'segment_axis_tip':[0,0,.3],
         'segment_axis_length':.3,'base_extension_t':0.,'leak':False}
plan=([('Link',co[0],co[1],'Base')],weights,metrics,{0,1},[])
follow,count=m.contact_follow_weights(p,co,edges,faces,plan)
assert count==1, count
for i,expected in [(2,.6),(3,.6),(4,.3),(5,0),(6,0),(7,0),(8,0)]:
    actual=sum(w.get(i,0) for w in follow.values())
    assert abs(actual-expected)<1e-7,(i,actual,expected)
assert weights=={'Link':{0:1.,1:1.}}, weights
p['contact_follow_weight']=0
assert not any(m.contact_follow_weights(p,co,edges,faces,plan)[0].values())
# Multiple groups may overlap: preserve the combined chain total, cap slots,
# and keep the largest original remainder. Four .2 extensions total .8;
# three retained shares are .8/3, leaving one original influence of .2.
import bpy
obj=bpy.data.objects.new('Budget',bpy.data.meshes.new('Budget'))
ext=[obj.vertex_groups.new(name='E'+str(i)) for i in range(5)]
original=[obj.vertex_groups.new(name='O'+str(i)) for i in range(2)]
entries=[(vg,.2) for vg in ext[:4]]+[(original[0],.12),(original[1],.08)]
kept=m.contact_follow_entries(entries,{vg.name for vg in ext})
assert len(kept)==4 and abs(sum(w for _,w in kept)-1)<1e-7
assert kept[-1][0]==original[0] and abs(kept[-1][1]-.2)<1e-7
assert all(abs(w-.8/3)<1e-7 for _,w in kept[:3])
# Fully overlapping envelopes have no original remainder; five .2 shares
# are truncated to four normalized .25 shares, without an exception.
kept=m.contact_follow_entries([(vg,.2) for vg in ext],{vg.name for vg in ext})
assert len(kept)==4 and all(abs(w-.25)<1e-7 for _,w in kept)
Path(args['result']).write_text(json.dumps({'ok':True,'data':{'follow':'0.6, 0.3, 0; ring/stop/beyond excluded'},'outputs':{}}))
'''


GROWTH_FIXTURE = r'''
import json, math, sys, types
from pathlib import Path
from mathutils import Vector
args=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(args['params']['scripts'])/'extension_bones.py'
module=types.ModuleType('operation'); module.__file__=str(source)
exec(compile(source.read_text().replace('_common.main(extension_bones)', ''),str(source),'exec'),module.__dict__)
# Hand-derived: 32 positions per ring, radius .03; seven hidden rings
# occupy .98 < z < 1.05. Their centres move backward .006 m per ring.
# A wall at z=1.055 adds annuli .032,.034,...,.12. Its plane cut
# loses the separate radius-.03 closed ring, so growth stops before the wall.
# Side cylinders at x=+/- .10, radius .02 cannot enter that tube.
co=[]; edges=[]; normals=[]; faces=[]
def ring(x,y,z,r,n=32):
    start=len(co)
    for j in range(n):
        angle=2*math.pi*j/n
        co.append(Vector((x+r*math.cos(angle),y+r*math.sin(angle),z)))
        normals.append(Vector((math.cos(angle),math.sin(angle),0)))
        edges.append((start+j,start+(j+1)%n))
    return list(range(start,start+n))
def join(a,b):
    edges.extend(zip(a,b))
    faces.extend((a[j],a[(j+1)%len(a)],b[(j+1)%len(b)],b[j]) for j in range(len(a)))
part=set(); hidden=set(); previous=None
for k in range(26):
    y=-.16+.006*max(0,k-18)
    current=ring(0,y,.795+.01*k,.03)
    if previous is not None: join(previous,current)
    (part if k<19 else hidden).update(current)
    previous=current
wall=set()
for k in range(46):
    current=ring(0,-.118,1.055,.03+.002*k)
    join(previous,current); wall.update(current); previous=current
side=set()
for sign in (-1,1):
    previous=None
    for k in range(27):
        current=ring(sign*.10,-.10,.795+.01*k,.02)
        if previous is not None: join(previous,current)
        side.update(current); previous=current
    # A shared wall connects the surfaces, but cannot bridge through rejection.
    edges.append((previous[0],min(wall,key=lambda i:(co[i]-co[previous[0]]).length)))
p={'base_slice_size':.01,'base_radius_margin':1.25,'base_growth_max':1.8,
   'base_extension_max':.6,'base_history_slices':5,'cut':.15,'weld_distance':.0001,'weld_normal_min':0.}
result,welded,centres,t,reason,table=module.grow_attachment(co,edges,part,Vector((0,-.16,.98)),Vector((0,0,-1)),.18,p,normals,faces)
assert hidden <= result, ('hidden stem missing',len(hidden-result),table)
assert not result & (side|wall), ('side or wall captured',table)
assert abs(t+7/18)<=.01/.18+1e-6, (t,table)
assert reason=='closed section leaves tube band', (reason,table)
assert abs(centres[-1].y+.118)<1e-6, centres[-1]
assert any(co[i].y>=-.12 for i in hidden), 'stem must continue behind the threshold'
Path(args['result']).write_text(json.dumps({'ok':True,'data':{'t':t,'reason':reason,'hidden':len(hidden),'slice_table':table},'outputs':{}}))
'''


def check(condition, label):
    assert condition, label
    print('PASS', label)


def close(actual, expected, epsilon=.002):
    return all(abs(a-b) < epsilon for a,b in zip(actual,expected))


def skin_weights(data):
    """Read accessor data to verify actual exported normalisation."""
    import struct
    from app.core.model_validate import parse_glb
    parsed=parse_glb(data)
    doc=parsed['gltf']
    # The parser exposes the BIN chunk separately.
    offset=12
    binary=b''
    while offset<len(data):
        length,kind=struct.unpack_from('<II',data,offset)
        if kind==0x004E4942: binary=data[offset+8:offset+8+length]
        offset+=8+length
    rows=[]
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            attributes=primitive['attributes']
            packs=[]
            for key,index in attributes.items():
                if key.startswith('WEIGHTS_'):
                    accessor=doc['accessors'][index]; view=doc['bufferViews'][accessor['bufferView']]
                    formats={5126:('f',4),5121:('B',1),5123:('H',2)}
                    fmt,size=formats[accessor['componentType']]
                    stride=view.get('byteStride',size*4)
                    start=view.get('byteOffset',0)+accessor.get('byteOffset',0)
                    values=[struct.unpack_from('<'+fmt*4,binary,start+i*stride) for i in range(accessor['count'])]
                    divisor=255 if accessor['componentType']==5121 else 65535 if accessor['componentType']==5123 else 1
                    packs.append([sum(v)/divisor for v in values])
            rows.extend(sum(pack[i] for pack in packs) for i in range(len(packs[0])))
    return rows


def exported_vertices(data, with_normals=False):
    """Decode positions and all weights by skin joint identity, never slot order."""
    import struct
    from app.core.model_validate import parse_glb
    parsed = parse_glb(data); doc = parsed['gltf']; binary = parsed['bin']
    def read(index):
        accessor = doc['accessors'][index]; view = doc['bufferViews'][accessor['bufferView']]
        fmt, size = {5126: ('f', 4), 5121: ('B', 1), 5123: ('H', 2)}[accessor['componentType']]
        width = {'VEC3': 3, 'VEC4': 4}[accessor['type']]
        stride = view.get('byteStride', size*width)
        start = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
        divisor = (255 if size == 1 else 65535) if accessor.get('normalized') else 1
        return [tuple(v/divisor for v in struct.unpack_from('<'+fmt*width, binary, start+i*stride))
                for i in range(accessor['count'])]
    rows = []
    for node in doc['nodes']:
        if 'mesh' not in node or 'skin' not in node:
            continue
        names = [doc['nodes'][j]['name'] for j in doc['skins'][node['skin']]['joints']]
        for primitive in doc['meshes'][node['mesh']]['primitives']:
            attributes = primitive['attributes']; positions = read(attributes['POSITION'])
            normals = read(attributes['NORMAL']) if with_normals else None
            packs = [(read(index), read(attributes['WEIGHTS_'+key.split('_')[1]]))
                     for key,index in attributes.items() if key.startswith('JOINTS_')]
            for i, position in enumerate(positions):
                weights = {}
                for joints, values in packs:
                    for joint,weight in zip(joints[i], values[i]):
                        if weight > 1e-8:
                            name = names[int(joint)]
                            weights[name] = weights.get(name, 0) + weight
                rows.append((position, weights, normals[i]) if with_normals else (position, weights))
    return rows


def assert_joint_weights(rows, position, expected, label):
    matches = [weights for point,weights in rows if close(point, position, .0001)]
    check(bool(matches) and all(set(weights) == set(expected) and
          all(abs(weights[name]-value) < .002 for name,value in expected.items())
          for weights in matches), label)


def publication_checks(root, model3d, rigged_source):
    """Pause real upload processing; concurrent readers must see old or final.

    These bytes stand for processing milestones (not synthetic GLB geometry).
    Only expensive processors are replaced, so persistence, staging, locking,
    revision checks, route byte capture and cleanup are the production paths.
    Generation has two deliveries: an unskinned GLB followed by a valid rigged
    GLB. Removing skins from the fixture yields zero source skins; keeping the
    original yields all required joints. Invalid sentinel bytes cannot reach
    processing through these two validation gates. Sentinels still represent
    the later processing milestones, whose byte visibility is under test.
    """
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.core.keyed_lock import keyed_lock
    from app.routes.characters import _model_asset_response, upload_character_model3d
    from app.core import outfit_cache_gc
    directory=model3d.get_model3d_dir('demo')
    signature='publication'; path=directory/(signature+'.glb')
    path.write_bytes(b'old-final')
    path.with_suffix('.json').write_text(json.dumps({'rig':'mixamo','marker':'old'}))
    low=directory/'low'/path.name; low.parent.mkdir(exist_ok=True); low.write_bytes(b'old-low')
    low.with_suffix('.json').write_text(json.dumps({'marker':'old-low'}))
    old_revision=model3d.model_revision(path)
    entered=threading.Event(); proceed=threading.Event()
    def process(name, staged, meta):
        staged.write_bytes(b'intermediate')
        entered.set()
        assert proceed.wait(10), 'reader did not release processing'
        staged.write_bytes(b'final')
        meta['marker']='final'
    def low_processor(name, staged):
        target=staged.parent/'low'/staged.name; target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'final-low')
        model3d._publish_sidecar(target,{'marker':'final-low'})
        return True
    class Request:
        headers={}
        query_params={}
    async def streamed_bytes(response):
        return b"".join([chunk async for chunk in response.body_iterator])
    with patch.object(model3d,'current_outfit_state',return_value=({},[],signature)), \
            patch.object(model3d,'_auto_retexture',side_effect=process), \
            patch.object(model3d,'_auto_normalize'), patch.object(model3d,'_auto_extension_rig'), \
            patch.object(model3d,'_attach_measurement'), patch.object(model3d,'request_lod',side_effect=low_processor):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(model3d.save_uploaded_model,'demo','mesh.glb',b'delivered',rig='mixamo')
            assert entered.wait(10)
            try:
                response=_model_asset_response('demo',Request())
                check(run_async(streamed_bytes(response))==b'old-final' and path.read_bytes()==b'old-final','concurrent route reader cannot see delivered or intermediate bytes')
                check(model3d.model_revision(path)==old_revision and json.loads(path.with_suffix('.json').read_text())['marker']=='old','processing leaves revision and metadata unchanged')
                with keyed_lock('model3d',f'demo:{signature}'):
                    check(not future.done(),'long processing leaves publication lock available')
            finally:
                proceed.set()
            future.result(timeout=10)
        check(path.read_bytes()==b'final' and low.read_bytes()==b'final-low' and json.loads(path.with_suffix('.json').read_text())['marker']=='final','full low and matching sidecars publish as final set')
        check(model3d.model_revision(path)!=old_revision,'revision changes on final publication')
        # A competing publisher wins; the older staging snapshot is discarded.
        entered.clear(); proceed.clear()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(model3d.save_uploaded_model,'demo','mesh.glb',b'delivered',rig='mixamo')
            assert entered.wait(10)
            try:
                with keyed_lock('model3d_publication',str(directory)):
                    model3d._publish_model_bytes(path,b'concurrent-final')
            finally:
                proceed.set()
            result=future.result(timeout=10)
        check(result.get('status')=='stale' and path.read_bytes()==b'concurrent-final','stale processor cannot overwrite competing publication')
        # Generation exposes its validated static mesh while the rig is processed;
        # a fetched rigged model stays staged until its processing succeeds.
        from types import SimpleNamespace
        ref=root/'reference.png'; ref.write_bytes(b'reference')
        import struct
        from app.core.model_validate import parse_glb
        parsed=parse_glb(rigged_source)
        document=parsed['gltf']; document.pop('skins',None)
        for node in document.get('nodes',[]):
            node.pop('skin',None)
        raw=json.dumps(document).encode(); raw+=b' '*(-len(raw)%4)
        binary=parsed['bin']; binary+=b'\0'*(-len(binary)%4)
        chunks=struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary
        unrigged_source=b'glTF'+struct.pack('<II',2,12+len(chunks))+chunks
        def deliver(output, payload=b'delivered'):
            target=Path(output).with_suffix('.glb'); target.write_bytes(payload)
            return {'ok':True,'status':'stored','path':str(target),'rig':'mixamo'}
        service=SimpleNamespace(
            generate_mesh=lambda **kwargs:deliver(kwargs['output_path'],unrigged_source),
            generate_rig=lambda **kwargs:deliver(kwargs['output_path'],rigged_source),
            fetch_mesh_job=lambda job,output,**kwargs:deliver(output))
        queue=SimpleNamespace(track_start=lambda *args,**kwargs:'',track_finish=lambda *args,**kwargs:None)
        with patch('app.imagegen.service.get_image_service',return_value=service), \
                patch('app.core.task_queue.get_task_queue',return_value=queue), \
                patch.object(model3d,'find_ref_image',return_value=ref), \
                patch.object(model3d,'_validator_for',return_value=lambda blob:{'ok':True,'warnings':[]}):
            for label,entry in (
                    ('generation',lambda:model3d.generate_for_current_outfit('demo',force=True,signature=signature)),
                    ('job retrieval',lambda:model3d.fetch_job_for_current_outfit('demo','example-job',force=True,signature=signature))):
                entered.clear(); proceed.clear(); path.write_bytes(b'old-final')
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future=executor.submit(entry)
                    if not entered.wait(10):
                        raise AssertionError((label,'processing not entered',future.result(timeout=1)))
                    try:
                        response = _model_asset_response('demo', Request())
                        if label == 'generation':
                            check(run_async(streamed_bytes(response)) == unrigged_source and
                                  json.loads(path.with_suffix('.json').read_text())['rig'] == 'none' and
                                  not low.exists(), 'generation serves the new static mesh, never partial rig output')
                        else:
                            check(run_async(streamed_bytes(response)) == b'old-final', 'job retrieval stages rigged delivery before processing')
                    finally:
                        proceed.set()
                    outcome=future.result(timeout=10)
                check((outcome.get('ok') or outcome.get('status')=='stored') and path.read_bytes()==b'final' and low.read_bytes()==b'final-low',label+' publishes processed full and low')
        # All backup files count towards GC and signature deletion.
        backups=[directory/'prerig'/path.name,directory/'low'/'prerig'/path.name]
        for backup in backups:
            backup.parent.mkdir(parents=True,exist_ok=True); backup.write_bytes(b'clean-source')
        files=outfit_cache_gc._mesh_files('demo')[signature]
        check(set(backups)<=set(files) and outfit_cache_gc._bytes_of(files)>=24,'GC accounts for full and low prerig bytes')
        check(model3d.delete_model3d('demo',signature) and all(not p.exists() for p in backups),'signature deletion removes full and low prerig')
    # The async HTTP adapter must allow a heartbeat while persistence blocks.
    async def responsiveness():
        upload_entered=threading.Event(); release=threading.Event(); beat=False
        def persist(*args,**kwargs):
            upload_entered.set(); assert release.wait(10); return {'rig':'mixamo'}
        class Upload:
            filename='fixture.glb'
            remaining=b'fixture'
            async def read(self,size):
                data=self.remaining; self.remaining=b''; return data
        class UploadRequest:
            headers={}
            async def form(self): return {'file':Upload()}
        async def heartbeat():
            nonlocal beat
            for _ in range(100):
                if upload_entered.is_set():
                    beat=True; release.set(); return
                await asyncio.sleep(.01)
            release.set()
        with patch.object(model3d,'save_uploaded_model',side_effect=persist), \
                patch('app.core.model_validate.validate_glb',return_value={'ok':True,'rig':'mixamo','warnings':[]}):
            await asyncio.gather(upload_character_model3d('demo',UploadRequest()),heartbeat())
        check(beat,'async upload persistence does not stall event loop')
    run_async(responsiveness())


def run_async(coroutine):
    """Keep executor completions observable in restricted smoke environments.

    Some runners do not wake a blocked selector on a worker's self-pipe write;
    a bounded selector wait also services completions without changing the app.
    """
    import asyncio
    import selectors
    class SmokeSelector(selectors.DefaultSelector):
        def select(self, timeout=None):
            return super().select(.05 if timeout is None else min(timeout, .05))
    with asyncio.Runner(loop_factory=lambda: asyncio.SelectorEventLoop(SmokeSelector())) as runner:
        return runner.run(coroutine)


def main():
    with tempfile.TemporaryDirectory(prefix='extension-p1-') as tmp:
        root=Path(tmp)
        paths.init(root/'world')
        paths.get_config_path().write_text(json.dumps({
            'packages': {'enabled': 'example'},
        }))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root/'instance/config.json')
        os.environ['ANIMATION_CLIPS_DIR']=str(root/'clips')
        os.environ['ANIMATION_RIG_FILE']=str(root/'reference.fbx')
        from app.blender import refine, runner
        st=runner.status()
        if not st['executable']:
            print('SKIP extension rig P1: no Blender executable found')
            return
        from app.core import db, model3d
        db.init_schema()
        from app.core.model_validate import parse_glb, validate_glb
        from app.core.rig_contract import BASE_JOINT_NAMES
        from app.models.character import get_character_dir,save_character_profile
        from app.plugins.loader import discover_packages
        from app.plugins import registry
        import yaml
        groups=[{'id':'example_pair','op':'pair_protrusion','chains':[
                    [{'bone':'ExampleLeft','parent':'mixamorig:Spine2'}],
                    [{'bone':'ExampleRight','parent':'mixamorig:Spine2'}]],'params':copy.deepcopy(DECLARED_PARAMS['pair_protrusion'])},
                {'id':'example_chain','op':'appendage_chain','chains':[[
                    {'bone':'ExampleLink1','parent':'mixamorig:Hips'},
                    {'bone':'ExampleLink2','parent':'ExampleLink1'}]],
                 'params':{**DECLARED_PARAMS['appendage_chain'],'segment_radius_margin':1.35,'search_z_min':-.35,'anchor_offset':[0,0,-.07],'weight_ramp':.25,'reweight_from':['LeftUpLeg']}}]
        package=root/'plugins'/'example'
        package.mkdir(parents=True)
        manifest={'name':'Example package','apply_to':['demo'],'body_slots':[
            {'id':g['id'],'rigs':[{**g, 'templates':['npc-temporary']}]} for g in groups]}
        (package/'plugin.yaml').write_text(yaml.safe_dump(manifest))
        discover_packages(root/'plugins',force=True)
        check(save_character_profile('demo',{'template':'npc-temporary','outfit_worn':'plain outfit'},create_new=True),'isolated profile')
        from app.core import extension_rig
        with patch.object(extension_rig, 'rig_groups_for', return_value=[]), \
                patch.object(extension_rig, 'resolved_extension_groups', return_value=[]), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected mesh read')), \
                patch.object(model3d, '_publish_model_bytes', side_effect=AssertionError('unexpected copy')):
            fast = model3d._auto_extension_rig('demo', root/'absent.glb', {'rig':'mixamo'})
        check(fast['ok'], 'no-rig fast path performs no read or copy')
        fixtures=root/'fixtures'; fixtures.mkdir()
        (fixtures/'fixture.py').write_text(FIXTURE)
        (fixtures/'growth.py').write_text(GROWTH_FIXTURE)
        (fixtures/'follow.py').write_text(FOLLOW_FIXTURE)
        operation_scripts=runner.SCRIPTS_DIR
        with patch.object(runner,'SCRIPTS_DIR',fixtures):
            follow=runner.run('follow',params={'scripts':str(operation_scripts)},out_dir=root/'follow',timeout_s=180)
            check(follow['ok'],'shared-face follow: hand weights .6/.3/0, tube unchanged: '+str(follow))
            growth=runner.run('growth',params={'scripts':str(operation_scripts)},out_dir=root/'growth',timeout_s=180)
            check(growth['ok'],'hidden tube captures seven rings, stops at wall, excludes side cylinders: '+str(growth['data']))
            normal=runner.run('fixture',params={'bones':list(BASE_JOINT_NAMES)},out_dir=root/'fixture',timeout_s=180)
            ties=runner.run('fixture',params={'bones':list(BASE_JOINT_NAMES),'ties':True},out_dir=root/'ties',timeout_s=180)
            bulged=runner.run('fixture',params={'bones':list(BASE_JOINT_NAMES),'fused':True,'bulged':True},out_dir=root/'bulged',timeout_s=180)
            fused=runner.run('fixture',params={'bones':list(BASE_JOINT_NAMES),'fused':True},out_dir=root/'fused',timeout_s=180)
            resting=runner.run('fixture',params={'bones':list(BASE_JOINT_NAMES),'under_contact':True},out_dir=root/'resting',timeout_s=180)
            exact=runner.run('fixture',params={'bones':list(BASE_JOINT_NAMES),'under_contact':True,'exact_contact':True},out_dir=root/'exact',timeout_s=180)
        check(normal['ok'] and fused['ok'],'synthetic GLBs built through runner')
        with patch.object(runner,'SCRIPTS_DIR',fixtures):
            shared=runner.run('fixture',params={'bones':list(BASE_JOINT_NAMES),'shared_blob':True},out_dir=root/'shared',timeout_s=180)
        shared_group=copy.deepcopy(groups[1])
        shared_group['params'].update(contact_follow_distance=.1,contact_follow_weight=.6)
        shared_result=runner.run('extension_bones',inputs={'model':Path(shared['outputs']['model'])},
                                 params={'groups':[shared_group]},out_dir=root/'shared-rig',timeout_s=180)
        check(shared_result['ok'] and shared_result['data']['status']=='applied','shared-face tube/blob operation applies')
        rows=exported_vertices(Path(shared_result['outputs']['model']).read_bytes())
        for x,expected in ((.06,.6),(.11,.3),(.16,0),(.21,0)):
            probes=[w for point,w in rows if close(point,[x,.91,.16],.0001)]
            check(bool(probes),'shared-face probe exists: '+str(x))
            for w in probes:
                actual=sum(v for n,v in w.items() if n.startswith('ExampleLink'))
                check(abs(actual-expected)<1e-5,'exported shared-face follow '+str((x,actual,expected)))
                check(len(w)<=4 and abs(sum(w.values())-1)<1e-6,'follow preserves four normalized influences')
                if expected:
                    original={n:v for n,v in w.items() if not n.startswith('ExampleLink')}
                    check('mixamorig:LeftUpLeg' in original and 'mixamorig:Spine' in original,
                          'follow retains largest original bones, including dominant source joint')
        baseline_shared=copy.deepcopy(shared_group); baseline_shared['params']['contact_follow_weight']=0
        unchanged=runner.run('extension_bones',inputs={'model':Path(shared['outputs']['model'])},
                             params={'groups':[baseline_shared]},out_dir=root/'shared-baseline',timeout_s=180)
        tube_before=[(point,w) for point,w in exported_vertices(Path(unchanged['outputs']['model']).read_bytes())
                     if sum(v for n,v in w.items() if n.startswith('ExampleLink'))>=.9]
        for point,w in tube_before:
            matches=[aw for ap,aw in rows if close(point,ap,1e-7)]
            assert matches and any(all(abs(aw.get(n,0)-v)<1e-6 for n,v in w.items()) for aw in matches)
        check(True,'shared-face tube weights unchanged')
        contact_group=copy.deepcopy(groups[1])
        contact_group['params'].update(contact_ramp=.08,protrusion_threshold=.02)
        contact_result=runner.run('extension_bones',inputs={'model':Path(resting['outputs']['model'])},
                                 params={'groups':[contact_group]},out_dir=root/'resting-rig',timeout_s=180)
        check(contact_result['data']['status']=='applied','resting tube retains full surface cores with a large radial ramp: '+str(contact_result['data']))
        contact_rows=exported_vertices(Path(contact_result['outputs']['model']).read_bytes())
        contact_side=[weights for point,weights in contact_rows if close(point,[0,.91,.13],.0001)]
        check(bool(contact_side) and all(sum(w for n,w in row.items() if n.startswith('ExampleLink'))>=.9
                                        for row in contact_side),'contact side is fully weighted')
        cap=[weights for point,weights in contact_rows if abs(point[1]-.8)<.0001
             and abs((point[0]**2+(point[2]-.16)**2)**.5-.03)<.0000001]
        check(len(cap)>=64 and all(sum(w for n,w in row.items() if n.startswith('ExampleLink'))>=.9
                                  for row in cap),'sharp end-cap seam and side copies are fully weighted')
        surface=[weights for point,weights in contact_rows if .7999<point[1]<=.9701
                 and abs((point[0]**2+(point[2]-.16)**2)**.5-.03)<.0000001]
        check(len(surface)>=18*32 and all(sum(w for n,w in row.items() if n.startswith('ExampleLink'))>=.9
                                         for row in surface),'all hand-derived tube rings outside attachment are fully weighted')
        blob=[weights for point,weights in contact_rows if .7999<point[1]<.9801
              and abs((point[0]**2+(point[2]-.0998)**2)**.5-.03)<.0000001]
        check(len(blob)>=608 and all(not any(n.startswith('ExampleLink') for n in row) for row in blob),
              'all 608 contact-blob positions retain zero chain weight')
        exact_result=runner.run('extension_bones',inputs={'model':Path(exact['outputs']['model'])},
                               params={'groups':[contact_group]},out_dir=root/'exact-rig',timeout_s=180)
        check(exact_result['data']['status']=='applied','exact capped contact applies')
        exact_rows=exported_vertices(Path(exact_result['outputs']['model']).read_bytes(),with_normals=True)
        exact_blob=[(point,weights) for point,weights,normal in exact_rows if .7999<point[1]<.9801
                    and abs((point[0]**2+(point[2]-.1)**2)**.5-.03)<.0000001
                    and normal[0]*point[0]+normal[2]*(point[2]-.1)>.025]
        check(len(exact_blob)>=608 and all(not any(n.startswith('ExampleLink') for n in row)
              for point,row in exact_blob if abs(point[0])>1e-7 or abs(point[2]-.13)>1e-7),
              'exact contact body positions away from the coincident seam stay unweighted')
        for z,count,expected in ((.91,4,5/8),(.8,5,15/23)):
            seam=[w for point,w,_ in exact_rows if close(point,[0,z,.13],1e-6)]
            check(len(seam)==count and all(w==seam[0] for w in seam),
                  'exact contact copies share one exported weight set at '+str(z))
            check(all(abs(sum(v for n,v in w.items() if n.startswith('ExampleLink'))-expected)<1e-6
                      for w in seam),'exact contact averaged chain total '+str((z,expected)))
        with patch.object(runner,'SCRIPTS_DIR',fixtures):
            curved=runner.run('fixture',params={'bones':list(BASE_JOINT_NAMES),'curved':True},out_dir=root/'curved',timeout_s=180)
        arc_group=copy.deepcopy(groups[1])
        arc_group['chains'][0].append({'bone':'ExampleLink3','parent':'ExampleLink2'})
        import math
        split=(1-math.sin(math.radians(5))/math.sin(math.radians(15)))/2
        arc_group['params'].update(chain_split=[split,1-split],cut=.001,near_slice_margin=.001,
                                  far_slice_fraction=.999,attachment_inset=0,segment_radius_factor=4,
                                  segment_radius_margin=3,contact_ramp=.001,weight_ramp=.2,ring_radius_scale=3)
        arc=runner.run('extension_bones',inputs={'model':Path(curved['outputs']['model'])},
                       params={'groups':[arc_group]},out_dir=root/'arc-rig',timeout_s=180)
        check(arc['data']['status']=='applied','curved three-link fixture applied: '+str(arc['data']))
        am=arc['data']['metrics']['example_chain']
        # R=.36, theta=-15,-5,5,15: chord bends are 10 degrees.
        # Axial fractions use sin(theta); each slab is .08 of axial length.
        expected_arc=[[0,-.20+.36*(math.cos(math.radians(a))-math.cos(math.radians(15))),
                       .89-.36*math.sin(math.radians(a))] for a in (-15,-5,5,15)]
        # The +Y exit is near y=-.183; Q remains below y=-.18. The tube
        # reaches at most y=-.181733 and the box begins at y=-.10, so +Z
        # finds no ceiling. Thus s=.03 and the head gains .03/sqrt(2) in
        # y and z: (0,-.178786797,1.004388059).
        expected_arc[0][1]+=.03/math.sqrt(2)
        expected_arc[0][2]+=.03/math.sqrt(2)
        joints=[am['placement'][0]['head']]+[v['tip'] for v in am['placement']]
        check(all(close(a,b) for a,b in zip(joints,expected_arc)),'analytic arc centreline joints within 2 mm')
        check(am['pivot']['reason']=='gap ceiling not found' and abs(am['pivot']['depth']-.03)<1e-9,
              'analytic arc uses the declared minimum depth without a ceiling')
        directions=[[b[i]-a[i] for i in range(3)] for a,b in zip(expected_arc,expected_arc[1:])]
        expected_bends=[math.degrees(math.acos(sum(x*y for x,y in zip(a,b))/
                        math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))))
                        for a,b in zip(directions,directions[1:])]
        check(all(abs(a-b)<1 for a,b in zip(am['bind_bend_deg'],expected_bends)),
              'analytic moved-root arc bind bends within 1 degree')
        check(all(n>0 for n in am['core_verts_per_link'].values()),'every curved link has core vertices')
        print('ARC METRICS',json.dumps(am,sort_keys=True))
        arc_rows=exported_vertices(Path(arc['outputs']['model']).read_bytes())
        for angle,name in [(0,'ExampleLink2'),(10,'ExampleLink3')]:
            point=[.006,.89-.36*math.sin(math.radians(angle)),.20-.36*(math.cos(math.radians(angle))-math.cos(math.radians(15)))]
            assert_joint_weights(arc_rows,point,{name:1.},'arc interior has no attachment attenuation')
        def arc_weights(angle):
            point=[.006,.89-.36*math.sin(math.radians(angle)),.20-.36*(math.cos(math.radians(angle))-math.cos(math.radians(15)))]
            matches=[w for c,w in arc_rows if close(c,point,.0001)]
            check(bool(matches),'arc ring probe present')
            return matches[0]
        root_weights=arc_weights(-15)
        check(root_weights.get('ExampleLink1',0)<.01 and not any(root_weights.get(n,0) for n in ('ExampleLink2','ExampleLink3')),'attachment start only ramps link1')
        ramp_weights=arc_weights(-15+30/18)
        check(ramp_weights.get('ExampleLink1',0)>.99 and not any(ramp_weights.get(n,0) for n in ('ExampleLink2','ExampleLink3')),'second ring lies 10.47 mm from root and has full weight')
        assert_joint_weights(arc_rows,[.006,.89-.36*math.sin(math.radians(-15+4*30/18)),.20-.36*(math.cos(math.radians(-15+4*30/18))-math.cos(math.radians(15)))],{'ExampleLink1':1.},'first link retains full core after ramp')
        for angle in (-5,5):
            w=arc_weights(angle)
            pair=('ExampleLink1','ExampleLink2') if angle<0 else ('ExampleLink2','ExampleLink3')
            check(all(abs(w.get(n,0)-.5)<.02 for n in pair),'joint-centred linear blend shares one half')
        soft=copy.deepcopy(arc_group)
        soft['params'].update(chain_split=[.249,.251],link_blend=.0005,weight_ramp=.01)
        no_core=runner.run('extension_bones',inputs={'model':Path(curved['outputs']['model'])},params={'groups':[soft]},out_dir=root/'no-core')
        check(no_core['data']['status']!='applied' and 'no core vertices' in no_core['data']['reason'] and not no_core['outputs'],'link without core rejects output with reason')
        overlap=copy.deepcopy(arc_group)
        overlap['params']['chain_split']=[.4,.5]
        overlapping=runner.run('extension_bones',inputs={'model':Path(curved['outputs']['model'])},params={'groups':[overlap]},out_dir=root/'overlap')
        check(overlapping['data']['status']=='failed' and 'must not overlap' in overlapping['data']['reason'],'overlapping joint blend zones fail validation')
        bad=copy.deepcopy(arc_group)
        bad['params']['weight_ramp']=split-.06
        rejected=runner.run('extension_bones',inputs={'model':Path(curved['outputs']['model'])},params={'groups':[bad]},out_dir=root/'bad-ramp')
        check(rejected['data']['status']=='failed' and 'weight_ramp + link_blend' in rejected['data']['reason'],'ramp consuming first core fails validation')

        tied=runner.run('extension_bones',inputs={'model':Path(ties['outputs']['model'])},params={'groups':groups},out_dir=root/'tied')
        check(tied['data']['status']=='applied','five-influence source processed')
        tie_doc=parse_glb(Path(ties['outputs']['model']).read_bytes())['gltf']
        tie_names=[tie_doc['nodes'][j]['name'] for j in tie_doc['skins'][0]['joints']]
        wanted={'mixamorig:'+name for name in ('Hips','Spine','Spine1','Spine2','LeftUpLeg')}
        tie_expected={name:.25 for name in [n for n in tie_names if n in wanted][:4]}
        tied_rows=exported_vertices(Path(tied['outputs']['model']).read_bytes())
        assert_joint_weights(tied_rows,[.2,1.1,-.1],tie_expected,'whole-mesh equal-weight reduction ties by joint index')
        normalized=runner.run('normalize',inputs={'model':Path(normal['outputs']['model'])},params={'target_height_m':1.7},out_dir=root/'normalized')
        check(normalized['ok'],'fixture normalized before rig')
        normal=normalized
        source=Path(normal['outputs']['model']).read_bytes()
        check(validate_glb(source)['ok'],'fixture has full base contract')
        model_dir=get_character_dir('demo')/'model3d'; model_dir.mkdir()
        full=model_dir/'example.glb'; full.write_bytes(source)
        from app.core.extension_rig import extension_metadata
        from app.core.improvements.base import Candidate
        from app.core.improvements.types.extension_rig_rebuild import ExtensionRigRebuild
        placeholder = extension_metadata('demo')
        full.with_suffix('.json').write_text(json.dumps({'extension_rig':placeholder,'rig':'mixamo','pieces':{},'items':[],'blender':{'steps':['normalize']}}))
        check(not ExtensionRigRebuild().is_done(Candidate('character:demo','demo'),{'character':'demo'}),'placeholder is pending in Improvements')
        from app.core.model_refs import is_humanoid
        info = model3d.get_model3d_info('demo')
        check(is_humanoid('demo') and len(info['extension_groups']) == 2,
              'temporary NPC resolves humanoid pipeline and Extension bones panel groups')
        from app.core.body_slots import slots_for_character
        check(not slots_for_character('demo'), 'temporary NPC pipeline does not activate package slots')
        before_doc=parse_glb(source)['gltf']
        before_frames={n['name']:{k:n.get(k) for k in ('translation','rotation','scale','matrix')} for n in before_doc['nodes'] if n.get('name','').startswith('mixamorig:')}
        from app.routes.characters import rebuild_character_model3d_extension_rig
        result=rebuild_character_model3d_extension_rig('demo', signature='example', tier='full', force=False)
        meta=json.loads(full.with_suffix('.json').read_text())
        state=meta['extension_rig']
        check(state['status']=='applied' and state['attempted'] and state['attempted_at'],'placeholder fingerprint does not suppress first attempt')
        metrics=state['metrics']
        pair=metrics['example_pair']['placement']
        check(close(pair[0]['tip'],[.1,-.23,1.4]) and close(pair[1]['tip'],[-.1,-.23,1.4]),'hand-derived mirrored apex positions')
        check(close(pair[0]['head'],[.0753750217,-.06,1.4]) and close(pair[1]['head'],[-.0753750217,-.06,1.4]),'hand-derived wall bone heads')
        chain=metrics['example_chain']
        check(abs(chain['attachment'][2]-.98)<.002,'attachment is nearer declared anchor')
        check(abs(chain['axis_length']-.175)<.004,'hand-derived chain length .175 m')
        unmoved=chain['weight_joints'][0]
        check(abs(unmoved[2]-.985)<.004,'hand-derived attachment inset')
        # Only the first head moves to the pivot: A + depth*normalize(0,1,1).
        depth=chain['pivot']['depth']/math.sqrt(2)
        check(close(chain['placement'][0]['head'],[unmoved[0],unmoved[1]+depth,unmoved[2]+depth],1e-6),
              'first head lies on the pivot ray from the unmoved root')
        check(not chain['leak'],'separate cylinder has no leak')
        check(abs((chain['placement'][0]['tip'][2]-unmoved[2])+.07875)<.002,'hand-derived first segment .07875 m from the unmoved root')
        check(all(abs(w-1)<.0001 for w in skin_weights(full.read_bytes())),'exported weights normalised')
        rows=exported_vertices(full.read_bytes())
        check(all(len(weights)<=4 for _,weights in rows),'whole exported mesh has at most four influences')
        blend=(3/7-(.45-.06))/.12
        expected={'ExampleLink1':1-blend,'ExampleLink2':blend}
        total=sum(expected.values()); expected={name:value/total for name,value in expected.items()}
        assert_joint_weights(rows,[.03,.91,.16],expected,'hand-derived attenuation, transfer, chain split and top-four weights by joint')
        radial_group=copy.deepcopy(groups[1])
        radial_group['chains'][0]=radial_group['chains'][0][:1]
        radial_group['params'].update(chain_split=[],segment_radius_margin=1.35,contact_ramp=.011,protrusion_threshold=.02,reweight_factor=0)
        radial_result=runner.run('extension_bones',inputs={'model':Path(normal['outputs']['model'])},
                                 params={'groups':[radial_group]},out_dir=root/'radial-ramp',timeout_s=180)
        ramp_rows=exported_vertices(Path(radial_result['outputs']['model']).read_bytes())
        probes=[]
        for x in (.03,-.03):
            matches=[weights for point,weights in ramp_rows if close(point,[x,.91,.16],.0001)]
            check(bool(matches) and all(abs(weights.get('ExampleLink1',0)-1)<.0001 and
                  weights.get('mixamorig:LeftUpLeg',0)==0 for weights in matches),
                  'radial boundary probe has full extension and zero source weight')
            probes.append(matches[0])
        averaged={name:sum(weights.get(name,0) for weights in probes)/2
                  for name in set(probes[0])|set(probes[1])}
        assert_joint_weights([([0,.91,.16],averaged)],
                             [0,.91,.16],{'ExampleLink1':1.},
                             'connected tube surface has unit total weight independent of contact_ramp')
        assert_joint_weights(rows,[.2,1.1,-.1],{'mixamorig:Hips':.2,'mixamorig:Spine':.35,'mixamorig:Spine1':.25,'mixamorig:LeftUpLeg':.2},'unaffected mixed source weights by joint')
        assert_joint_weights(rows,[.1,1.4,.23],{'ExampleLeft':1.},'pair apex weight by joint')
        assert_joint_weights(rows,[.12,1.4,.23],{'ExampleLeft':1.},'plateau full weight before reduction')
        t=1865/2346; radial=t*t*(3-2*t)
        ramp={'ExampleLeft':radial,'mixamorig:Spine':.35*(1-radial),'mixamorig:Spine1':.25*(1-radial),'mixamorig:Hips':.20*(1-radial)}
        total=sum(ramp.values()); ramp={k:v/total for k,v in ramp.items()}
        assert_joint_weights(rows,[.14,1.4,.23],ramp,'hand-derived radial ramp and reduction')
        after_doc=parse_glb(full.read_bytes())['gltf']
        after_frames={n['name']:{k:n.get(k) for k in ('translation','rotation','scale','matrix')} for n in after_doc['nodes'] if n.get('name','').startswith('mixamorig:')}
        defaults={'translation':[0,0,0],'rotation':[0,0,0,1],'scale':[1,1,1],'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}
        frames_ok=set(before_frames)==set(after_frames) and all(close(before_frames[name][key] or defaults[key],after_frames[name][key] or defaults[key],1e-6) for name in before_frames for key in defaults)
        check(frames_ok,'all 52 base joint frames unchanged within roundtrip precision')
        original=full.read_bytes()
        model3d.rebuild_extension_rig('demo','example')
        check(full.read_bytes()==original,'same fingerprint is byte-identical no-op')
        clean=model_dir/'prerig'/'example.glb'
        check(clean.read_bytes()==source,'prerig retains clean source')
        changed=registry.get_package('example').body_slots[0].rigs[0]
        changed.params['test_rotation_deg']=[-10,0,0]
        model3d.rebuild_extension_rig('demo','example')
        check(full.read_bytes()==original,'declaration change rebuilds without double attenuation')
        low=model_dir/'low'/'example.glb'
        check(low.is_file(),'low rebuilt after full rig')
        low_names={n.get('name') for n in parse_glb(low.read_bytes())['gltf']['nodes']}
        check({'ExampleLeft','ExampleRight','ExampleLink1','ExampleLink2'}<=low_names,'low inherits extension bones')
        low_measure=runner.run('extension_bones',inputs={'model':low},params={'groups':groups,'metrics_only':True},timeout_s=180)
        check(low_measure['ok'] and not low_measure['outputs'],'low metrics measured without publication')
        check(low_measure['data']['metrics']['example_pair']['verts_per_group']!=metrics['example_pair']['verts_per_group'],'low reports actual reduced vertex counts')
        # An unchanged full still repairs an absent or stale distance tier.
        low.unlink()
        repair=model3d.rebuild_extension_rig('demo','example')
        check(repair['ok'] and low.is_file() and full.read_bytes()==original,'full no-op repairs missing low')
        low_meta=json.loads(low.with_suffix('.json').read_text())
        low_meta['extension_rig']['fingerprint']='stale'
        low.with_suffix('.json').write_text(json.dumps(low_meta))
        repair=model3d.rebuild_extension_rig('demo','example')
        check(repair['ok'] and json.loads(low.with_suffix('.json').read_text())['extension_rig']['fingerprint']!='stale','full no-op repairs stale low')
        low_meta=json.loads(low.with_suffix('.json').read_text())
        low_meta['extension_rig']['fingerprint']='stale'
        low.with_suffix('.json').write_text(json.dumps(low_meta))
        low_bytes=low.read_bytes()
        with patch.object(model3d,'build_lod',return_value={'ok':False,'error':'synthetic LOD failure'}):
            failed_lod=model3d.rebuild_extension_rig('demo','example')
        check(not failed_lod['ok'] and 'synthetic LOD failure' in failed_lod['error'],'LOD failure propagates to rebuild result')
        check(low.read_bytes()==low_bytes and full.read_bytes()==original,'LOD failure preserves complete full and low files')
        check(json.loads(full.with_suffix('.json').read_text())['extension_rig']['per_tier']['low']['status']=='failed','LOD failure persists tier reason')
        retry=model3d.rebuild_extension_rig('demo','example')
        check(retry['ok'] and json.loads(full.with_suffix('.json').read_text())['extension_rig']['per_tier']['low']['status']!='failed','retry repairs failed low')
        # Character flags persist through the real options API and fingerprint.
        from app.core.extension_rig import extension_metadata
        from app.core.improvements.base import Candidate
        from app.core.improvements.types.extension_rig_rebuild import ExtensionRigRebuild
        fingerprint=extension_metadata('demo', signature='example')['fingerprint']
        model3d.set_model3d_options('demo',{'signature':'example','extension_rig':{'example_chain':{'flip':True}}})
        check(model3d.get_model3d_options('demo')['extension_rig_models']['example']['example_chain']['flip'] and extension_metadata('demo', signature='example')['fingerprint']!=fingerprint,'profile flip persists and changes fingerprint')
        disabled={g['id']:{'enabled':False} for g in groups}
        model3d.set_model3d_options('demo',{'signature':'example','extension_rig':disabled})
        check(model3d.get_model3d_options('demo')['extension_rig_models']['example']==disabled and extension_metadata('demo', signature='example')['fingerprint']!=fingerprint,'disabled overrides persist and change fingerprint')
        low_before=low.read_bytes()
        with patch.object(model3d,'build_lod',return_value={'ok':False,'error':'disabled tier failure'}):
            reset_failed=model3d.rebuild_extension_rig('demo','example')
        reset_meta=json.loads(full.with_suffix('.json').read_text())['extension_rig']
        check(not reset_failed['ok'] and full.read_bytes()==original and low.read_bytes()==low_before,'disable LOD failure preserves complete published full and low')
        check(reset_meta['status']=='applied' and reset_meta['per_tier']['low']['status']=='failed','disable records failed low beside unchanged full')
        improvement=ExtensionRigRebuild()
        candidate=Candidate('character:demo','demo')
        check(not improvement.is_done(candidate,{'character':'demo'}),'improvement remains pending after disable LOD failure')
        reset_retry=model3d.rebuild_extension_rig('demo','example')
        low_after_names={n.get('name') for n in parse_glb(low.read_bytes())['gltf']['nodes']}
        check(reset_retry['ok'] and not {'ExampleLeft','ExampleRight','ExampleLink1','ExampleLink2'}&low_after_names,'disable retry removes extension bones from low')
        check(improvement.is_done(candidate,{'character':'demo'}),'improvement completes after clean low recovery')
        from app.routes.characters import queue_character_extension_rigs
        queued = queue_character_extension_rigs('demo')
        check(queued['params']['character'] == 'demo', 'temporary NPC Improvements batch route accepts character')
        check(improvement.validate({'character': 'demo'}) == {'character': 'demo'},
              'temporary NPC Improvements validation is template-independent')

        model3d.set_model3d_options('demo',{'signature':'example','extension_rig':{}})
        restored=model3d.rebuild_extension_rig('demo','example')
        check(restored['ok'] and full.read_bytes()==original and clean.read_bytes()==source,'restoring overrides reapplies from clean source without attenuation')
        fingerprint=json.loads(full.with_suffix('.json').read_text())['extension_rig']['fingerprint']
        changed.params['radius_scale']=1.0
        rebuilt=model3d.rebuild_extension_rig('demo','example')
        check(rebuilt['ok'] and full.read_bytes()!=original and clean.read_bytes()==source,'radius scale rebuilds from clean prerig')
        check(json.loads(full.with_suffix('.json').read_text())['extension_rig']['fingerprint']!=fingerprint,'radius parameter changes fingerprint')
        changed.params['radius_scale']=1.15
        rebuilt=model3d.rebuild_extension_rig('demo','example')
        check(rebuilt['ok'] and full.read_bytes()==original,'restoring radius reconstructs original weights')
        changed.params['lateral_min']=3
        changed.params['lateral_max']=4
        keep=full.read_bytes()
        model3d.rebuild_extension_rig('demo','example')
        check(full.read_bytes()==keep,'failed request keeps original bytes')
        failed=json.loads(full.with_suffix('.json').read_text())['extension_rig']
        check(failed['status'] in ('not_found','failed') and bool(failed['reason']),'failure reports reason')
        # A valid operation rejected by the publication validator never replaces source.
        rejected=root/'rejected.glb'; rejected.write_bytes(source)
        gate=refine.apply_script(rejected,'extension_bones',{'groups':groups},require_smaller=False,validator=lambda _: {'ok':False,'errors':['synthetic gate rejection']})
        check(not gate['applied'] and rejected.read_bytes()==source,'failed validation gate keeps original')
        for key in ('band_lower_bone','radius_plateau'):
            missing=copy.deepcopy(groups); del missing[0]['params'][key]
            absent=runner.run('extension_bones',inputs={'model':Path(normal['outputs']['model'])},params={'groups':missing},out_dir=root/('missing-'+key))
            check(absent['data']['status']=='failed' and 'missing required params' in absent['data']['reason'] and key in absent['data']['reason'] and not absent['outputs'],'missing required '+key+' fails with explicit reason')
        invalid=copy.deepcopy(groups)
        invalid[0]['params']['depth_ramp']=0
        res=runner.run('extension_bones',inputs={'model':Path(normal['outputs']['model'])},params={'groups':invalid},out_dir=root/'invalid',timeout_s=180)
        check(res['ok'] and res['data']['status']=='failed' and not res['outputs'],'invalid declaration aborts whole request')
        check(all(v.get('reason') for v in res['data']['groups'].values()),'abort carries reason for every group')
        for key,value in (('radius_plateau',-0.1),('radius_plateau',1),('radius_scale',0)):
            invalid=copy.deepcopy(groups); invalid[0]['params'][key]=value
            res=runner.run('extension_bones',inputs={'model':Path(normal['outputs']['model'])},params={'groups':invalid},out_dir=root/('invalid-'+key+str(value)),timeout_s=180)
            check(res['data']['status']=='failed' and key in res['data']['reason'] and not res['outputs'],'range validation '+key+str(value))
        missing=copy.deepcopy(groups); del missing[0]['params']['radius_scale']
        res=runner.run('extension_bones',inputs={'model':Path(normal['outputs']['model'])},params={'groups':missing},out_dir=root/'missing-scale',timeout_s=180)
        check(res['data']['status']=='failed' and 'radius_scale' in res['data']['reason'],'missing required radius scale')
        flipped=copy.deepcopy(groups[1]); flipped['flip']=True
        res=runner.run('extension_bones',inputs={'model':Path(normal['outputs']['model'])},params={'groups':[flipped]},out_dir=root/'flipped',timeout_s=180)
        check(res['ok'] and res['data']['status']=='applied','flipped fixture applied: '+str(res['data']))
        check(abs(res['data']['metrics']['example_chain']['attachment'][2]-.8)<.002,'flip swaps attachment and tip')
        # Run the same generic operation against a side-connected surface.
        chain_group=copy.deepcopy(groups[1])
        chain_group['params'].update(segment_radius_margin=1.2,reference_lateral_min=.16, reference_lateral_max=.19, candidate_lateral_max=.0301)
        res=runner.run('extension_bones',inputs={'model':Path(fused['outputs']['model'])},params={'groups':[chain_group]},out_dir=root/'leak',timeout_s=180)
        check(res['ok'] and res['data']['status']=='applied','leak fixture still produces valid chain')
        check(not res['data']['metrics']['example_chain']['leak'],'bounded side-contact cylinder has no leak')
        contact=res['data']['metrics']['example_chain']
        print('CONTACT METRICS',json.dumps(contact,sort_keys=True))
        check(abs(contact['segment_pass_history'][0]['radius']-.0405)<.0001,'hand-derived pass-0 segment radius .0405')
        check(contact['part_vertex_count']>=608,'all 608 cylinder samples captured')
        check(contact['thigh_weight_in_part']==0,'contact part has no source-joint weight')
        contact_rows=exported_vertices(Path(res['outputs']['model']).read_bytes())
        def segment_radial(point):
            # glTF is Y-up: convert to the operation's metre Z-up frame.
            c=(point[0],-point[2],point[1])
            base=contact['segment_axis_base']; tip=contact['segment_axis_tip']
            axis=[tip[j]-base[j] for j in range(3)]
            length=sum(v*v for v in axis)**.5
            axis=[v/length for v in axis]
            delta=[c[j]-base[j] for j in range(3)]
            axial=sum(delta[j]*axis[j] for j in range(3))
            return sum((delta[j]-axis[j]*axial)**2 for j in range(3))**.5
        body_rows=[(point,weights) for point,weights in contact_rows
                   if .7999<point[1]<.9801 and segment_radial(point)>contact['segment_radius']*1.05
                   and abs(((point[0]-.0902)**2+(point[2]-.16)**2)**.5-.06)<.0001]
        check(bool(body_rows) and all(weights.get('mixamorig:LeftUpLeg',0)>.1 and
              not any(name.startswith('ExampleLink') for name in weights) for _,weights in body_rows),
              'contact cylinder vertices beyond radius stay unchanged')
        for point,weights in body_rows:
            assert all(abs(weights.get('mixamorig:'+name,0)-value)<.0001
                       for name,value in [('Hips',.2),('Spine',.35),('Spine1',.25),('LeftUpLeg',.2)])
        cylinder=[(point,weights) for point,weights in contact_rows if
                  .7999<point[1]<.9801 and abs((point[0]**2+(point[2]-.16)**2)**.5-.03)<.0001]
        unique={tuple(round(v,5) for v in point) for point,_ in cylinder}
        check(len(unique)==608 and all(weights.get('mixamorig:LeftUpLeg',0)==0
              for point,weights in cylinder if point[1]<=.9701),
              '608 unique tube positions; source weights vanish outside the attachment ring')
        offset_group=copy.deepcopy(chain_group)
        offset_group['params'].update(protrusion_threshold=.061,segment_radius_margin=1.2,weight_ramp=.25,contact_ramp=.005)
        offset_result=runner.run('extension_bones',inputs={'model':Path(bulged['outputs']['model'])},
                                 params={'groups':[offset_group]},out_dir=root/'offset',timeout_s=180)
        check(offset_result['data']['status']=='applied','offset fixture applied: '+str(offset_result['data']))
        offset_metrics=offset_result['data']['metrics']['example_chain']
        print('REFINED METRICS',json.dumps(offset_metrics,sort_keys=True))
        check(all((end[0]**2+(end[1]+.16)**2)**.5<.002
                  for end in (offset_metrics['segment_axis_base'],offset_metrics['segment_axis_tip'])),
              'front-offset axis returns within 2 mm of cylinder centre')
        offset_rows=exported_vertices(Path(offset_result['outputs']['model']).read_bytes())
        samples=[(point,weights) for point,weights in offset_rows if .7999<point[1]<.9801 and abs(point[0])<=.03001 and .1279<=point[2]<=.1921]
        check(len({tuple(round(v,5) for v in point) for point,_ in samples})==608
              and all(sum(w for name,w in weights.items() if name.startswith('ExampleLink'))>=.9
              for point,weights in samples if point[1]<=.9701),
              'full bulged cylinder including contact side has full weight outside attachment ring')
        outside=[weights for point,weights in offset_rows if .7999<point[1]<.9801
                 and point[0]>.0301 and abs(((point[0]-.0902)**2+(point[2]-.16)**2)**.5-.06)<.0001]
        check(bool(outside) and all(weights.get('mixamorig:LeftUpLeg',0)>.1
              and not any(name.startswith('ExampleLink') for name in weights) for weights in outside),
              'offset fixture contact-cylinder samples beyond final radius remain unchanged')
        check(all(abs(row['radius']-expected)<.0001 for row,expected in
              zip(offset_metrics['segment_pass_history'],[.03972180,.04268464,.04503358,.03756308]))
              and len(offset_metrics['segment_pass_history'])==4,
              'hand-derived radii for pass 0 and three refinement passes')
        check(offset_metrics['uncaptured_in_part']==0 and offset_metrics['captured_beyond_radius']==0
              and offset_metrics['thigh_weight_in_part']==0,'refined coverage and transfer metrics are zero')
        guard=copy.deepcopy(offset_group)
        guard['params'].update(segment_radius_margin=2.,segment_radius_growth_max=1.01)
        guarded=runner.run('extension_bones',inputs={'model':Path(bulged['outputs']['model'])},
                           params={'groups':[guard]},out_dir=root/'growth-guard',timeout_s=180)
        gm=guarded['data']['metrics']['example_chain']
        check(gm['segment_passes']==0 and 'growth_max' in gm['segment_stop_reason']
              and gm['segment_radius']==gm['segment_pass_history'][0]['radius']
              and gm['segment_axis_base']==gm['segment_pass_history'][0]['axis_base'],
              'growth guard retains the entire previous segmentation state')
        fallback=copy.deepcopy(chain_group); fallback['params']['segment_min_vertices']=100000
        fb=runner.run('extension_bones',inputs={'model':Path(fused['outputs']['model'])},
                      params={'groups':[fallback]},out_dir=root/'fallback',timeout_s=180)
        fm=fb['data']['metrics']['example_chain']
        check(fm['leak'] and 'too few' in fm['leak_reason'] and fm['thigh_weight_in_part']==0,
              'implausible bounded component falls back with reason and full transfer')
        for key in ('segment_radius_factor','segment_min_vertices','contact_ramp',
                    'segment_radius_percentile','segment_radius_margin',
                    'segment_radius_growth_max','segment_passes','centerline_slab','link_blend',
                    'base_slice_size','base_radius_margin','base_growth_max','base_extension_max','base_history_slices',
                    'attachment_ring_max','weld_normal_min','contact_follow_distance','contact_follow_weight','contact_inside_distance'):
            missing=copy.deepcopy(chain_group); del missing['params'][key]
            bad=runner.run('extension_bones',inputs={'model':Path(fused['outputs']['model'])},
                           params={'groups':[missing]},out_dir=root/('missing-'+key),timeout_s=180)
            check(bad['data']['status']=='failed' and key in bad['data']['reason'],
                  'new parameter is required: '+key)
        for key,value in [('segment_radius_factor',0),('contact_ramp',0),
                          ('segment_min_vertices',0),('segment_min_vertices',2.5),
                          ('segment_radius_percentile',0),('segment_radius_percentile',1),
                          ('segment_radius_margin',0),('segment_radius_growth_max',0),
                          ('segment_passes',0),('segment_passes',1.5),
                          ('base_slice_size',0),('base_radius_margin',.9),
                          ('base_growth_max',1),('base_extension_max',0),
                          ('base_history_slices',0),('base_history_slices',1.5),
                          ('contact_follow_distance',0),('contact_follow_weight',-.1),('contact_follow_weight',1),
                          ('contact_inside_distance',-.01),
                          ('attachment_ring_max',0),('weld_normal_min',-1.1),('weld_normal_min',1.1),
                          ('centerline_slab',0),('centerline_slab',1),('link_blend',0),('link_blend',1)]:
            invalid=copy.deepcopy(chain_group); invalid['params'][key]=value
            bad=runner.run('extension_bones',inputs={'model':Path(fused['outputs']['model'])},
                           params={'groups':[invalid]},out_dir=root/'invalid-new',timeout_s=180)
            check(bad['data']['status']=='failed' and key in bad['data']['reason'],
                  'new parameter range validation: '+key+'='+str(value))
        fresh=model_dir/'prepare.glb'; fresh.write_bytes(source)
        fresh.with_suffix('.json').write_text(json.dumps({'rig':'mixamo'}))
        with patch.object(refine,'normalize',return_value={'applied':False,'error':'synthetic preparation failure'}):
            preparation=model3d.rebuild_extension_rig('demo','prepare')
        check(not preparation['ok'] and 'synthetic preparation failure' in preparation['error'] and fresh.read_bytes()==source,'failed normalization keeps published bytes and reports reason')
        check(not (model_dir/'prerig'/'prepare.glb').exists(),'failed preparation creates no prerig asset')
        publication_checks(root,model3d,source)
        # Restore the declaration mutated by the earlier failed-detection check.
        changed.params = copy.deepcopy(groups[0]['params'])
        # Exercise the production upload pipeline for the temporary NPC too.
        order = []
        original_normalize, original_extension = model3d._auto_normalize, model3d._auto_extension_rig
        def normalize_upload(*args, **kwargs):
            if not kwargs.get('required'):
                order.append('normalize')
            return original_normalize(*args, **kwargs)
        def extend_upload(*args, **kwargs):
            check(order == ['normalize'] and 'normalize' in args[2].get('blender', {}).get('steps', []),
                  'temporary NPC extension runs after normalize')
            order.append('extension')
            return original_extension(*args, **kwargs)
        with patch.object(model3d, '_auto_retexture'), patch.object(model3d, '_attach_measurement'), \
                patch.object(model3d, 'request_lod'), \
                patch.object(model3d, '_auto_normalize', side_effect=normalize_upload), \
                patch.object(model3d, '_auto_extension_rig', side_effect=extend_upload):
            uploaded = model3d.save_uploaded_model('demo', 'pipeline.glb', source, rig='mixamo')
        check(order == ['normalize', 'extension'] and uploaded['extension_rig']['status'] == 'applied',
              'temporary NPC production upload publishes applicable extension rig')
        print('PASS extension rig P1: all checks')


if __name__=='__main__':
    main()
