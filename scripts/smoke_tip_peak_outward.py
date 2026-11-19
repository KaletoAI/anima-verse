#!/usr/bin/env python3
"""Smoke (Blender): a switched-on tip stands on the skin's own peak, its ops only raise the skin, and a tip whose ops
still sink, over-raise or fold the skin is dropped (A209; ``extension_bones.local_peak``, ``level_heights``
``outward_cap``, ``crater_census`` / ``crater_gate``).

Usage:  ./.venv/bin/python scripts/smoke_tip_peak_outward.py

Runs headless Blender (``app.blender.runner``, CPU), no world, no model: a probe execs extension_bones.py (and the
pre-fix copy of commit ffe2bc03c, read with ``git show``) and calls the functions directly.

Numbers, by hand:
[1] ``level_heights`` with a fit that returns Q = 0 everywhere, full = .012 (blend = .8 x .012 = .0096). 12 ring rows
    (outside .012 >= (1.8 - 1) x .012 = .0096, h = 0, RMS 0) keep k = 0 and shift 0. Region rows (outside -.005:
    k = clip((.0096 + .005) / .0096) = 1): h = +.010 -> target Q = 0; h = -.002 -> 0; h = -.005 -> 0; an inner row
    h = -.004.
    Pre-fix (ffe2bc03c, no cap): shifts -.010, +.002, +.005, inner min(-.004, 0) - .001 - (-.004) = -.001 — the bump
    row sinks 10 mm (the Ylva ring: 14.5 mm).
    outward_cap .003 with that exact ring (RMS 0 <= TIP_LEVEL_EXACT_RMS_M .0005): mode replace, the pre-fix shifts
    (Ruling A53: a tip modelled on a smooth skin is replaced).
    outward_cap .003 with the ring at h = +-.001 alternating (RMS .001, in (.0005, .002]): mode raise — shifts 0 (no
    sinking), +.002, +.003 (capped), inner 0; ring rows k = 0, shift 0.
    Same rows with the ring at h = +-.003 alternating: RMS .003 > TIP_LEVEL_FIT_RMS_MAX_M .002 -> every shift 0.
[2] ``local_peak`` on a sphere of radius .05 centred at (.01, 0, 0), wall normal (0, -1, 0), wall centre at the
    origin, source apex on the sphere at x = 0, z = 0 (y = -sqrt(.05^2 - .01^2) = -.04899). The most protruding
    point along -Y is (.01, -.05, 0), 10 mm from the source in the plane across the normal, inside the 30 mm disc;
    the 0.5 mm plateau is the disc of radius sqrt(.05^2 - .0495^2) = 7.05 mm around it, symmetric, so its mean is
    the peak. Expected within 1 mm (grid 1 mm, icosphere edge ~1.2 mm). A row without ``wall_normal`` -> None.
[3] ``crater_gate`` (TIP_GATE_SINK_AREA_MM2 20, TIP_GATE_RAISE_M 2 x .003 + .0005 = .0065): sunk 25 mm2 -> 'sank';
    raised 6.6 mm -> 'raised'; folded 1 after 0 before -> 'folded'; sunk 0, raised 3.0, folded 0 -> ''.
[4] ``crater_census`` on a 41 x 41 grid of 1 mm spacing in the plane y = 0 facing -Y (vertex area 1 mm2 inside),
    centre at the origin: unchanged -> sunk 0. A 5 x 5 block at the centre pushed 3 mm back (+Y): every moved vertex
    lies 3 mm behind the old plane. Vertex area = the sum of its quads' areas / 4 AFTER the move; a quad across the
    step is a 1 x sqrt(1 + 9) = 3.162 mm2 rectangle. The 3 x 3 inside: 4 flat quads -> 1 mm2 each, d = -3 mm: 9 mm2.
    The 12 rim edge vertices: (2 x 1 + 2 x 3.162) / 4 = 2.081 mm2 each = 24.97 mm2; their normal (corner-angle mean
    of -Y, -Y and two faces tilted atan 3 = 71.6 deg) has |n.y| = .658 / sqrt(.658^2 + .474^2) = .811, so
    d = -2.43 mm, sunk. The 4 corners: (1 + 2 x 3.162 + A) / 4 with the corner quad's A in [1, 3.162] -> 2.08..2.62
    mm2 each, 8.33..10.47. Total 42.3..44.5 mm2, max sink 3.0 mm.
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
ring_h=[0.]*12
def rows(ring):
    h=np.array(ring+[.010,-.002,-.005,-.004]); outside=np.array([.012]*12+[-.005]*4)
    inner=np.array([False]*15+[True]); return h,outside,inner
fit=lambda ring: np.zeros(16)
h,o,i=rows(ring_h)
s_old,_=old['level_heights'](h,o,i,full,fit)
check('1 pre-fix',list(s_old[12:]),[-.010,.002,.005,-.001])
check('1 pre-fix ring',list(s_old[:12]),[0.]*12)
s_ex,lvl=new['level_heights'](h,o,i,full,fit,outward_cap=.003)
check('1 exact',list(s_ex[12:]),[-.010,.002,.005,-.001])
if lvl.get('mode')!='replace': fails.append(('1 exact mode',lvl.get('mode'),'replace'))
h,o,i=rows([.001,-.001]*6)
s_new,lvl=new['level_heights'](h,o,i,full,fit,outward_cap=.003)
check('1 capped',list(s_new[12:]),[0.,.002,.003,0.])
check('1 capped ring',list(s_new[:12]),[0.]*12)
if lvl.get('mode')!='raise': fails.append(('1 capped mode',lvl.get('mode'),'raise'))
h,o,i=rows([.003,-.003]*6)
s_rms,lvl=new['level_heights'](h,o,i,full,fit,outward_cap=.003)
check('1 rms',list(s_rms),[0.]*16)
check('1 rms value',lvl['fit_rms_mm'],3.,1e-6)
# [2]
bm=bmesh.new(); bmesh.ops.create_icosphere(bm,subdivisions=7,radius=.05)
for v in bm.verts: v.co+=Vector((.01,0,0))
me=bpy.data.meshes.new('s'); bm.to_mesh(me); bm.free()
ob=bpy.data.objects.new('s',me); bpy.context.scene.collection.objects.link(ob)
tree=new['world_tree']([ob])
src=[0.,-math.sqrt(.05**2-.01**2),0.]
peak=new['local_peak'](tree,{'tip':src,'wall_centre':[0,0,0],'wall_normal':[0,-1,0]})
check('2 peak',list(peak),[.01,-.05,0.],.001)
check('2 no normal',0. if new['local_peak'](tree,{'tip':src,'wall_centre':[0,0,0]}) is None else 1.,0.)
# [3]
g=new['crater_gate']; b={'folded':0}
c=lambda **k: {'sunk_area_mm2':0.,'max_sunk_mm':0.,'max_raised_mm':0.,'folded':0,**k}
check('3 raise const',new['TIP_GATE_RAISE_M'],.0065,1e-12)
for label,after,word in (('3 sank',c(sunk_area_mm2=25.,max_sunk_mm=3.),'sank'),('3 raised',c(max_raised_mm=6.6),'raised'),
                         ('3 folded',c(folded=1),'folded'),('3 clean',c(max_raised_mm=3.),'')):
    reason=g(b,after)
    if (word and word not in reason) or (not word and reason): fails.append((label,reason,word))
# [4]
n=41; verts=[(( (k%n)-20)*.001,0.,((k//n)-20)*.001) for k in range(n*n)]
faces=[(r*n+q,r*n+q+1,(r+1)*n+q+1,(r+1)*n+q) for r in range(n-1) for q in range(n-1)]
pm=bpy.data.meshes.new('p'); pm.from_pydata(verts,[],faces); pm.update()
po=bpy.data.objects.new('p',pm); bpy.context.scene.collection.objects.link(po)
if pm.polygons[0].normal.y > 0:
    pm.flip_normals(); pm.update()
before=new['world_tree']([po]); centres=[Vector((0,0,0))]
cen=new['crater_census']([po],centres,before)
check('4 unchanged',cen['sunk_area_mm2'],0.)
for v in pm.vertices:
    if abs(v.co.x)<=.0021 and abs(v.co.z)<=.0021: v.co.y+=.003
pm.update()
cen=new['crater_census']([po],centres,before)
if not 42.3 <= cen['sunk_area_mm2'] <= 44.5: fails.append(('4 area',cen['sunk_area_mm2'],'42.3..44.5'))
check('4 max',cen['max_sunk_mm'],3.,1e-3)
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
