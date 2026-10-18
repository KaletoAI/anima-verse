"""Analytic pair wall checks in headless Blender.

Usage: .venv/bin/python scripts/smoke_extension_rig_pair_wall.py

A: y=-.10+.25*(z-1.40), n=(0,-1,.25)/sqrt(1.0625).
A radius-.09 spherical cap of height .05 has sphere radius
(.09**2+.05**2)/.10=.106 and centre .056 behind the plane.
Its tip is (.15,-.1,1.4)+.05*n, depth .05, tilt atan(.25)=14.036 deg.
At z=1.485 the plane is -.07875; probe y=-.08875 is 1 cm in front.
The old front-most apex has z=1.4-.056*.25/sqrt(1.0625)=1.386418.
Its wall .12 below samples z=1.266418, y=-.133396;
wall+.03=-.103396 rejects that probe. The new signed distance is
.01/sqrt(1.0625)>0 and radius .073<.09*1.15, so weight is positive.
B: oval axes .06,.09, height .05; disc radius .009 at z=1.41.
Area pi*.009**2=.0002545, RMS .009/sqrt(2), fit marker limits.
Skin sRGB (.72,.52,.40), disc (.62,.28,.30) yield Lab approximately
(59.6,16.3,24.4),(41.5,36.7,13.9): score=25.6>6, L>32.8.
C: right disc at 1.37 differs by .04>.02, rejecting both markers.
D: a one-sided front sheet cannot deepen the pair wall: maximum paired
wall offsets selects the unobstructed side; normal.x mirrors exactly.
Exclusion .3/.3 gives multiplier zero, including descendants.
E (clothing, no marker): plane y=-.1 with oval bumps at x=+-.06, z=1.4,
axes .05/.09, height .05, plus one spike vertex at (.035,-.17,1.35) in front
of the bump tips (-.15), like a bow or fold. SideLeft/SideRight at x=+-.2 put
the midline at 0. The protrusion (blur .05 minus blur .015) of the plane is
zero and of each bump symmetric about its centre, so the 4-connected crest
averages to the tip (+-.06,-.15,1.4); the spike covers about four 2.5 mm
cells, after sigma .015 it shifts the map by under .2 mm. The front-most
vertex (the old start) is the spike.
Reach on the .0025 grid from .03: medial boundary .05 (slope 1; the midline
stop at .055 comes later), up/down .09, diagonal ellipse boundary
1/sqrt(.5/.05**2+.5/.09**2)=.0618 -> first step beyond .0625 (slope .8,
.769 at .065); the mesh facet across the steep bump edge can lift the hit
at .0625 by ~2 mm, which moves it one step to .065. The round outline takes
the median of [.09,d,.05,d]x2 = d with d in {.0625,.065}.
Every wall point lies on the plane, so the wall is y=-.1, depth .05.
Midline cap: for x<=.0075, |rx|>=.0525 and R<=.055*r/|rx|, so
1-r/R<=1-.0525/.055=.04545 and weight<=smooth(.04545/.4)=.03581 (+fp). Without the
cap R=1.15*d>=.071875 gives at least smooth((1-.055/.071875)/.4)=.626 at the margin.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROBE = r"""
import bpy, json, math, sys
from pathlib import Path
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(job['params']['source']); scope={'__file__':str(source)}
exec(compile(source.read_text().split('_common.main(')[0],str(source),'exec'),scope)
p=dict(band_lower_bone='Lower',band_upper_bone='Upper',band_lower_offset=0.,band_upper_offset=0.,
 lateral_min=.03,lateral_max=.25,side_margin=.005,marker_search_radius=.07,marker_grid_step=.0025,
 marker_score_min=6.,marker_yellow_weight=.5,marker_dark_min=.55,marker_light_max=3.,
 marker_area_min=.0001,marker_area_max=.003,marker_spread_max=.02,marker_pair_dz=.02,marker_pair_dx=.03,
 apex_smooth_radius=.015,apex_plateau_depth=.003,apex_context_radius=.05,
 boundary_directions=8,boundary_s_min=.03,boundary_s_max=.13,boundary_step=.0025,
 radius_plateau=.6,radius_scale=1.15,front_margin=.03,depth_ramp=.02,head_wall_depth=.04,
 weight_min=.003,exclude_bones=['Exclude'],exclude_weight=.3,
 lateral_positive_bone='SideLeft',lateral_negative_bone='SideRight')
group={'chains':[[{'bone':'ExampleLeft','parent':'Base'}],[{'bone':'ExampleRight','parent':'Base'}]]}
validated=dict(p,test_rotation_deg=[0,0,0],test_scale=[1,1,1],up_from_bone='Lower',up_to_bone='Upper',
 up_distance_min=.1,up_distance_max=2.,
 front_from_bone='Lower',front_to_bone='Upper',front_distance_min=0.)
scope['parameters']({'op':'pair_protrusion','params':validated})
for key,value in [('boundary_directions',4.5),('boundary_directions',6),('boundary_directions',True),
 ('marker_dark_min',0),('marker_dark_min',1),('marker_yellow_weight',-1),('marker_light_max',-1),
 ('marker_grid_step',0),('apex_smooth_radius',0),('apex_plateau_depth',0),('apex_context_radius',0),('marker_search_radius',0),('marker_area_max',p['marker_area_min']),
 ('boundary_s_max',p['boundary_s_min']),('boundary_step',0),('exclude_weight',0),('exclude_bones',[1])]:
 try:
  scope['parameters']({'op':'pair_protrusion','params':dict(validated,**{key:value})})
 except ValueError as error:
  assert key in str(error), error
 else:
  raise AssertionError((key,value,'must reject'))
for key in p:
 if key.startswith(('marker_','boundary_','exclude_','apex_')):
  missing=dict(validated); del missing[key]
  try: scope['parameters']({'op':'pair_protrusion','params':missing})
  except ValueError as error: assert key in str(error), error
  else: raise AssertionError((key,'must be required'))
def fixture(kind):
 bpy.ops.wm.read_factory_settings(use_empty=True)
 data=bpy.data.armatures.new('Rig'); arm=bpy.data.objects.new('Rig',data)
 bpy.context.collection.objects.link(arm); bpy.context.view_layer.objects.active=arm
 bpy.ops.object.mode_set(mode='EDIT')
 for name,x,z,parent in [('Base',0,1.,None),('Lower',0,1.2,None),('Upper',0,1.6,None),('Exclude',0,1.,None),('Child',0,1.1,'Exclude'),
                         ('SideLeft',.2,1.4,None),('SideRight',-.2,1.4,None)]:
  b=data.edit_bones.new(name); b.head=(x,0,z); b.tail=(x,0,z+.05)
  if parent: b.parent=data.edit_bones[parent]
 bpy.ops.object.mode_set(mode='OBJECT')
 vertices=[]; faces=[]; tilt=.25 if kind=='A' else 0.
 n=Vector((0,-1,tilt)).normalized()
 for iz in range(241):
  z=1.1+iz*.0025
  for ix in range(241):
   x=-.3+ix*.0025; sign=1 if x>=0 else -1
   dx=x-sign*.15; dz=z-1.4
   if kind=='A':
    centre=Vector((sign*.15,-.1,1.4))-n*.056
    q=.106**2-(x-centre.x)**2-(z-centre.z)**2
    y=min(-.1+tilt*dz,centre.y-math.sqrt(q)) if q>=0 else -.1+tilt*dz
   elif kind=='E':
    r2=((x-sign*.06)/.05)**2+(dz/.09)**2
    y=-.1-.05*max(0.,1-r2)**.5
    if (ix,iz)==(134,100):
     y=-.17
   else:
    r2=(dx/.06)**2+(dz/.09)**2
    y=-.1-.05*max(0.,1-r2)**.5
   vertices.append((x,y,z))
 for iz in range(240):
  for ix in range(240):
   a=iz*241+ix; faces.append((a,a+1,a+242,a+241))
 probe=len(vertices); vertices.append((.15,-.08875,1.485))
 excluded=len(vertices); vertices.append((.151,-.15,1.401))
 if kind=='D':
  a=len(vertices); vertices.extend(((.045,-.12,1.43),(.14,-.12,1.43),(.14,-.12,1.515),(.045,-.12,1.515)))
  faces.append((a,a+1,a+2,a+3))
 me=bpy.data.meshes.new('Surface'); me.from_pydata(vertices,[],faces); me.update()
 obj=bpy.data.objects.new('Surface',me); bpy.context.collection.objects.link(obj)
 mod=obj.modifiers.new('Skin','ARMATURE'); mod.object=arm
 vg=obj.vertex_groups.new(name='Base'); vg.add(list(range(len(vertices))),1.,'REPLACE')
 vg=obj.vertex_groups.new(name='Child'); vg.add([excluded],.3,'REPLACE')
 if kind not in ('A','E'):
  uv=me.uv_layers.new()
  for loop in me.loops:
   v=me.vertices[loop.vertex_index].co
   uv.data[loop.index].uv=((v.x+.3)/.6,(v.z-1.1)/.6)
  import numpy as np
  size=1024; yy,xx=np.mgrid[:size,:size]; xx=(xx+.5)/size*.6-.3; yy=(yy+.5)/size*.6+1.1
  mask=((xx-.15)**2+(yy-1.41)**2<.009**2)|((xx+.15)**2+(yy-(1.37 if kind=='C' else 1.41))**2<.009**2)
  pixels=np.empty((size,size,4),np.float32); pixels[:]=(.72,.52,.40,1); pixels[mask]=(.62,.28,.30,1)
  image=bpy.data.images.new('Marker',width=size,height=size); image.pixels.foreach_set(pixels.ravel())
  mat=bpy.data.materials.new('Colour'); mat.use_nodes=True
  tex=mat.node_tree.nodes.new('ShaderNodeTexImage'); tex.image=image
  mat.node_tree.links.new(tex.outputs['Color'],mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
  me.materials.append(mat)
 co=[obj.matrix_world@v.co for v in me.vertices]
 surface=scope['pair_surface']([obj]); bones={scope['bone_key'](b.name):b for b in data.bones}
 plan=scope['pair_plan'](group,p,co,bones,surface,[(obj,v.index) for v in me.vertices])
 sides=plan[2]['placement']
 assert all(s['apex_source']==('geometry' if kind in ('A','C','E') else 'colour') for s in sides), sides
 assert excluded not in plan[1]['ExampleLeft'], plan[1]['ExampleLeft'].get(excluded)
 if kind=='A':
  expected=Vector((.15,-.1,1.4))+n*.05
  assert (Vector(sides[0]['tip'])-expected).length<.003, sides
  assert abs(math.degrees(math.atan2(sides[0]['wall_normal'][2],-sides[0]['wall_normal'][1]))-math.degrees(math.atan(.25)))<1, sides
  assert abs(sides[0]['depth']-.05)<.0025, sides
  assert plan[1]['ExampleLeft'].get(probe,0)>0
 if kind=='B':
  for sign,s in zip((1,-1),sides):
   assert math.hypot(s['tip'][0]-sign*.15,s['tip'][2]-1.41)<=.0025, s
   assert abs(s['reach'][0]-s['reach'][2])>.01, s
   assert s['reach'][2]==s['reach'][6], s
 if kind=='D':
  assert sides[0]['reach'][7]<.13, sides
  a,b=[s['wall_normal'] for s in sides]
  assert max(abs(a[0]+b[0]),abs(a[1]-b[1]),abs(a[2]-b[2]))<1e-6, sides
 if kind=='E':
  spike=vertices[100*241+134]; assert abs(spike[0]-.035)<1e-9 and abs(spike[2]-1.35)<1e-9 and spike[1]==-.17
  for sign,s in zip((1,-1),sides):
   assert (Vector(s['tip'])-Vector((sign*.06,-.15,1.4))).length<.0025, s
   assert len(set(s['reach']))==1 and min(abs(s['reach'][0]-d) for d in (.0625,.065))<1e-9, s
   assert abs(s['depth']-.05)<.001, s
  for name,sign in (('ExampleLeft',1),('ExampleRight',-1)):
   near=[w for i,w in plan[1][name].items() if sign*co[i].x<=.0075+1e-9]
   assert max(near,default=0.)<=.0359, (name,max(near))
 print('PASS fixture',kind)
for kind in ('A','B','C','D','E'): fixture(kind)
Path(job['result']).write_text(json.dumps({'ok':True,'data':{},'outputs':{}}))
"""


def main():
    from app.blender import runner
    if not runner.status()['executable']:
        print('SKIP pair wall: no Blender executable found')
        return
    with tempfile.TemporaryDirectory(prefix='pair-wall-') as tmp:
        script=Path(tmp)/'probe.py'; script.write_text(PROBE)
        source=runner.SCRIPTS_DIR/'extension_bones.py'
        with patch.object(runner,'SCRIPTS_DIR',Path(tmp)):
            result=runner.run('probe', params={'source':str(source)}, out_dir=Path(tmp)/'out',timeout_s=180)
        assert result['ok'], result
        print('PASS pair wall: tilt, oval colour, pair rejection, occluder, descendant exclusion, clothing crest')

if __name__ == '__main__':
    main()
