#!/usr/bin/env python3
"""Smoke (Blender): a switched-on tip stands on the skin's own peak, its ops only raise the skin, and a tip whose ops
still sink, over-raise or fold the skin is dropped (A209; ``extension_bones.local_peak``, ``level_heights``
``outward_cap``, ``crater_census`` / ``crater_gate``).

Usage:  ./.venv/bin/python scripts/smoke_tip_peak_outward.py

Runs headless Blender (``app.blender.runner``, CPU), no world, no model: a probe execs extension_bones.py (and the
pre-fix copy of commit ffe2bc03c, read with ``git show``) and calls the functions directly.

Numbers, by hand:
[1] ``level_heights`` with a fit that returns Q = 0 everywhere, full = .012 (blend = .8 x .012 = .0096). 12 ring rows
    (outside .012 >= (1.8 - 1) x .012 = .0096) keep k = 0 and shift 0. Region rows (outside -.005:
    k = clip((.0096 + .005) / .0096) = 1, target Q = 0): h = +.010, -.002, -.005 and an inner row h = -.004.
    Pre-fix (ffe2bc03c, no cap), ring at h = 0: shifts -.010, +.002, +.005, inner min(-.004, 0) - .001 - (-.004) =
    -.001 — the bump row sinks 10 mm (the Ylva ring: 14.5 mm).
    outward_cap .003, ring at +-.001 alternating (RMS .001 <= TIP_LEVEL_FIT_RMS_MAX_M .002, mode raise), no
    footprint: 0 (no sinking), +.002, +.003 (capped), inner 0.
    Same with the bump row AND the inner row inside a modelled tip's footprint of depth .004: the bump row goes down
    by at most .004 -> -.004; the inner row's -.001 lies within [-(.004 + .001), 0] -> -.001; others as above.
    Ring at +-.003 (RMS .003 > .002, mode none), no footprint: every shift 0.
[2] ``local_peak`` on a sphere of radius .05 centred at (.01, 0, 0), wall normal (0, -1, 0), wall centre at the
    origin, source apex on the sphere at x = 0, z = 0 (y = -sqrt(.05^2 - .01^2) = -.04899). No reach -> radius .03.
    The most protruding point along -Y is (.01, -.05, 0), 10 mm from the source in the plane across the normal (rim
    test: 10 <= 30 - 2.5); the 0.5 mm plateau is the disc of radius sqrt(.05^2 - .0495^2) = 7.05 mm around it,
    connected and symmetric, so its mean is the peak; gain .05 - .04899 = 1.01 mm >= 1 mm. Expected within 1 mm.
    A plate in front at y = -.08 (another mesh, 30 mm off the source; the sphere is the source's own mesh) changes
    nothing. Kept (None): mid .02 on side +1 -> the peak x .01 is across the midline; reach [.02] x 8 -> radius
    max(.01, min(.03, .5 x .02)) = .01, top 10 mm out > .01 - .0025 -> at the rim; a source ON the top -> gain 0;
    no ``wall_normal``.
[3] ``crater_gate`` (TIP_GATE_SINK_AREA_MM2 20, TIP_GATE_RAISE_M 2 x .003 + .0005 = .0065, new folds above 1 mm2 in all):
    sunk 25 mm2 -> 'sank'; raised 6.6 mm -> 'raised'; new folds 1.2 mm2 -> 'folded'; .8 mm2 -> ''; clean -> ''.
[4] ``crater_census`` on a 41 x 41 grid of 1 mm spacing in the plane y = 0 facing -Y (front (0, -1, 0)), quads
    split into triangles along one diagonal, centre at the origin.
    a) unchanged -> sunk 0, folds 0.
    b) a 5 x 5 block at the centre pushed 3 mm back (+Y). Vertex area = the sum of its triangles' areas / 3 AFTER
       the move. Inside 3 x 3: six flat triangles of .5 mm2 -> 1 mm2 each, d = -3 mm: 9 mm2. Each of the 16 rim
       vertices also touches triangles across the 3 mm step (1 x sqrt(10) / 2 = 1.581 mm2): an edge vertex
       (2 x .5 + 2 x 1.581 + 2 x x) / 3 with the two remaining triangles in [.5, 1.581] -> 1.72..2.44 mm2, a corner
       the same range; their normals keep |n.y| > 1/3, so d < -1 mm and they count. Total 9 + 16 x [1.72, 2.44] =
       36.5..48.0 mm2, max sink 3.0 mm. With an exempt disc of 5 mm around the centre every moved vertex lies
       within sqrt(2.83^2 + 3^2) = 4.12 mm of it -> sunk 0.
    c) folds, pre-existing + new: two triangles reversed BEFORE the BVH is taken (their old face already opposes
       the smooth normal: not new), then the vertex at (10, 0, 10) mm moved 3 mm in +X past its neighbour at
       11 mm and .5 mm out (-Y; a vertex counts as moved by its distance off the old skin, and the tip ops move
       along the normal): every triangle that has it as a corner and the x = 11 mm edge opposite flips (base 1 mm, apex 2 mm
       beyond it: area 1 mm2 each); there are 2 such -> folds >= 2, fold area >= 2 mm2, gate 'folded'.
    d) folds, pre-existing only: the same reversed triangles, one of their corners raised 1 mm (-Y) — it moved,
       its face still opposes, but so did the old one -> folds 0, gate ''; the raise is 1 mm x |n.y| of a vertex
       normal tilted by the reversed faces next to it: .3..1 mm.
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PRE_FIX = 'ffe2bc03c'

PROBE = r'''
import json, sys, math
from pathlib import Path
import numpy as np
import bpy, bmesh
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
def load(path):
    scope={'__file__':str(path)}
    exec(compile(Path(path).read_text(),str(path),'exec'),scope)
    return scope
new=load(job['params']['source']); old=load(job['params']['old'])
fails=[]
def check(label,got,want,tol=1e-9):
    if isinstance(want,(list,tuple)):
        ok=len(got)==len(want) and all(abs(g-w)<=tol for g,w in zip(got,want))
    else:
        ok=abs(got-want)<=tol
    if not ok: fails.append((label,[round(float(g),6) for g in got] if isinstance(got,(list,tuple,np.ndarray)) else got,want))
# [1]
full=.012
def rows(ring):
    h=np.array(ring+[.010,-.002,-.005,-.004]); outside=np.array([.012]*12+[-.005]*4)
    inner=np.array([False]*15+[True]); return h,outside,inner
fit=lambda ring: np.zeros(16)
h,o,i=rows([0.]*12)
s_old,_=old['level_heights'](h,o,i,full,fit)
check('1 pre-fix',list(s_old[12:]),[-.010,.002,.005,-.001])
h,o,i=rows([.001,-.001]*6)
s_new,lvl=new['level_heights'](h,o,i,full,fit,outward_cap=.003)
check('1 raise',list(s_new),[0.]*12+[0.,.002,.003,0.])
if lvl.get('mode')!='raise': fails.append(('1 raise mode',lvl.get('mode')))
foot=np.array([False]*12+[True,False,False,True])
s_ft,_=new['level_heights'](h,o,i,full,fit,outward_cap=.003,footprint=(foot,.004))
check('1 footprint',list(s_ft),[0.]*12+[-.004,.002,.003,-.001])
h,o,i=rows([.003,-.003]*6)
s_rms,lvl=new['level_heights'](h,o,i,full,fit,outward_cap=.003)
check('1 none',list(s_rms),[0.]*16)
if lvl.get('mode')!='none': fails.append(('1 none mode',lvl.get('mode')))
# [2]
def sphere(name,centre,radius):
    bm=bmesh.new(); bmesh.ops.create_icosphere(bm,subdivisions=7,radius=radius)
    for v in bm.verts: v.co+=Vector(centre)
    me=bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob=bpy.data.objects.new(name,me); bpy.context.scene.collection.objects.link(ob); return ob
ball=sphere('s',(.01,0,0),.05)
pm=bpy.data.meshes.new('plate'); pm.from_pydata([(-.02,-.08,-.02),(.04,-.08,-.02),(.04,-.08,.02),(-.02,-.08,.02)],[],[(0,1,2,3)])
plate=bpy.data.objects.new('plate',pm); bpy.context.scene.collection.objects.link(plate)
src=[0.,-math.sqrt(.05**2-.01**2),0.]
row={'tip':src,'wall_centre':[0,0,0],'wall_normal':[0,-1,0]}
peak,info=new['local_peak']([ball,plate],row,1,-1.)
check('2 peak',list(peak) if peak else [9,9,9],[.01,-.05,0.],.001)
check('2 gain',info['gain_mm'],1.01,.05)
for label,args,want in (('2 midline',(row,1,.02),'across the midline'),
                        ('2 rim',(dict(row,reach=[.02]*8),1,-1.),'top at the rim'),
                        ('2 gain0',(dict(row,tip=[.01,-.05,0.]),1,-1.),'gain below 1 mm'),
                        ('2 no normal',({'tip':src,'wall_centre':[0,0,0]},1,-1.),'no wall normal')):
    got,info=new['local_peak']([ball,plate],*args)
    if got is not None or info.get('kept')!=want: fails.append((label,got,info))
# [3]
g=new['crater_gate']
c=lambda **k: {'sunk_area_mm2':0.,'max_sunk_mm':0.,'max_raised_mm':0.,'folds':0,'fold_area_mm2':0.,**k}
check('3 raise const',new['TIP_GATE_RAISE_M'],.0065,1e-12)
for label,after,word in (('3 sank',c(sunk_area_mm2=25.,max_sunk_mm=3.),'sank'),('3 raised',c(max_raised_mm=6.6),'raised'),
                         ('3 folded',c(folds=1,fold_area_mm2=1.2),'folded'),('3 small fold',c(folds=3,fold_area_mm2=.8),''),
                         ('3 clean',c(max_raised_mm=3.),'')):
    reason=g(after)
    if (word and word not in reason) or (not word and reason): fails.append((label,reason,word))
# [4]
def grid(name):
    n=41; verts=[(((k%n)-20)*.001,0.,((k//n)-20)*.001) for k in range(n*n)]
    faces=[]
    for r in range(n-1):
        for q in range(n-1):
            a,b,c2,d=r*n+q,r*n+q+1,(r+1)*n+q+1,(r+1)*n+q
            faces+= [(a,b,c2),(a,c2,d)]
    me=bpy.data.meshes.new(name); me.from_pydata(verts,[],faces); me.update()
    if me.polygons[0].normal.y > 0: me.flip_normals(); me.update()
    ob=bpy.data.objects.new(name,me); bpy.context.scene.collection.objects.link(ob); return ob
FRONT=Vector((0,-1,0)); around=[(Vector((0,0,0)),FRONT)]
po=grid('p'); pm=po.data
before=new['world_tree']([po])
cen=new['crater_census']([po],around,before)
check('4a sunk',cen['sunk_area_mm2'],0.); check('4a folds',cen['folds'],0.)
for v in pm.vertices:
    if abs(v.co.x)<=.0021 and abs(v.co.z)<=.0021: v.co.y+=.003
pm.update()
cen=new['crater_census']([po],around,before)
if not 36.5 <= cen['sunk_area_mm2'] <= 48.: fails.append(('4b area',cen['sunk_area_mm2'],'36.5..48'))
check('4b max',cen['max_sunk_mm'],3.,1e-3)
ex=new['crater_census']([po],around,before,[(Vector((0,0,0)),.005)])
check('4b exempt',ex['sunk_area_mm2'],0.)
def reversed_grid(name):
    ob=grid(name); bm=bmesh.new(); bm.from_mesh(ob.data); bm.faces.ensure_lookup_table()
    centre=[f for f in bm.faces if all(abs(v.co.x+.010)<.0025 and abs(v.co.z+.010)<.0025 for v in f.verts)][:2]
    corners=[tuple(v.co) for f in centre for v in f.verts]
    bmesh.ops.reverse_faces(bm,faces=centre); bm.to_mesh(ob.data); bm.free(); ob.data.update()
    return ob,corners
qo,rev=reversed_grid('q')
before=new['world_tree']([qo])
pre=new['crater_census']([qo],around,before)
check('4c pre-existing not new',pre['folds'],0.)
for v in qo.data.vertices:
    if abs(v.co.x-.010)<1e-6 and abs(v.co.z-.010)<1e-6: v.co.x+=.003; v.co.y-=.0005
qo.data.update()
cen=new['crater_census']([qo],around,before)
if not (cen['folds']>=2 and cen['fold_area_mm2']>=2. and 'folded' in g(cen)): fails.append(('4c new folds',cen))
ro,rev=reversed_grid('r')
before=new['world_tree']([ro])
lift=next(v for v in ro.data.vertices if (v.co-Vector(rev[0])).length<1e-7)
lift.co.y-=.001; ro.data.update()
cen=new['crater_census']([ro],around,before)
if cen['folds']!=0 or g(cen)!='' or not .3<=cen['max_raised_mm']<=1.: fails.append(('4d pre-existing raised',cen))
Path(job['result']).write_text(json.dumps({'ok':not fails,'error':repr(fails),'data':{},'outputs':{}}))
'''


def main():
    from app.blender import runner
    if not runner.status()['executable']:
        raise RuntimeError('Blender executable unavailable; no checks ran')
    with tempfile.TemporaryDirectory(prefix='tip-peak-') as tmp:
        root = Path(tmp)
        (root/'probe.py').write_text(PROBE)
        old = root/'extension_bones_prefix.py'
        old.write_text(subprocess.run(['git', 'show', f'{PRE_FIX}:app/blender/scripts/extension_bones.py'], cwd=ROOT,
                                      check=True, capture_output=True, text=True).stdout)
        source = runner.SCRIPTS_DIR/'extension_bones.py'
        with patch.object(runner, 'SCRIPTS_DIR', root):
            result = runner.run('probe', params={'source': str(source), 'old': str(old)}, out_dir=root/'out',
                                timeout_s=300)
    print('all passed' if result['ok'] else f"FAILED {result.get('error')}")
    sys.exit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
