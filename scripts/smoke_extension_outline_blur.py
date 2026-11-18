#!/usr/bin/env python3
"""Smoke (Blender): the marker-free chest outline's blur keeps the grid's shape on a narrow grid (review 03, below
the cut-off: ``extension_bones.outline_locate`` / ``outline_blur``).

Usage:  ./.venv/bin/python scripts/smoke_extension_outline_blur.py

Headless Blender (``app.blender.runner``, CPU), no world, no model: a probe execs extension_bones.py.

By hand: step .0025, sigma .04 -> reach ceil(3 x .04 / .0025) = 48, a 97-tap kernel with k[48] = 1 and
k[49] = exp(-.5 x (.0025/.04)^2) = exp(-.001953125) = .99804878.
[1] a 120 x 150 grid (longer than the kernel both ways): ``outline_blur`` equals the old per-axis
    ``np.convolve(row, kernel, 'same')`` within 1e-12 — no output change where the old code worked.
[2] a 3 x 5 grid with one 1 at (1, 2): the result is 3 x 5, value 1 at (1, 2) and k[49] = .99804878 at (1, 3)
    and (0, 2), k[49]^2 at (0, 3).
[3] ``outline_locate`` with lateral_max .05 on a flat front (y = -.1, no colour): the grid is 29 + 48 = 77 columns,
    narrower than the kernel; it returns ``(None, "outline: 0/0 crease points")`` (flat: no crease) instead of
    raising. On 69aeeba75 there is no ``outline_blur``, and ``outline_locate`` raises ValueError (broadcast).
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROBE = r'''
import json, math, sys
from pathlib import Path
from mathutils import Vector
import numpy as np
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(job['params']['source']); scope={'__file__':str(source)}
exec(compile(source.read_text(),str(source),'exec'),scope)
fails=[]
step,sigma=.0025,.04
reach=math.ceil(3*sigma/step); kernel=np.exp(-.5*(np.arange(-reach,reach+1)*step/sigma)**2)
a=np.random.default_rng(3).random((120,150))
old=np.apply_along_axis(lambda r:np.convolve(r,kernel,'same'),0,a)
old=np.apply_along_axis(lambda r:np.convolve(r,kernel,'same'),1,old)
if not np.allclose(scope['outline_blur'](a,sigma,step),old,atol=1e-12,rtol=0): fails.append('1')
g=np.zeros((3,5)); g[1,2]=1.
b=scope['outline_blur'](g,sigma,step); k1=math.exp(-.001953125)
if b.shape!=(3,5) or abs(b[1,2]-1)>1e-12 or abs(b[1,3]-k1)>1e-9 or abs(b[0,2]-k1)>1e-9 or abs(b[0,3]-k1*k1)>1e-9:
 fails.append(('2',b.shape,b.tolist()))
p=dict(marker_grid_step=.0025,lateral_min=.03,lateral_max=.05,side_margin=.005,boundary_s_min=.03,boundary_s_max=.13)
try:
 got=scope['outline_locate'](p,lambda x,z,*a:(Vector((x,-.1,z)),None),0.,1.3,1.45)
 if got!=(None,'outline: 0/0 crease points'): fails.append(('3',got))
except ValueError as e:
 fails.append(('3 raised',str(e)))
Path(job['result']).write_text(json.dumps({'ok':not fails,'error':repr(fails),'data':{},'outputs':{}}))
'''


def main():
    from app.blender import runner
    if not runner.status()['executable']:
        raise RuntimeError('Blender executable unavailable; no checks ran')
    with tempfile.TemporaryDirectory(prefix='outline-blur-') as tmp:
        root = Path(tmp)
        (root/'probe.py').write_text(PROBE)
        source = runner.SCRIPTS_DIR/'extension_bones.py'
        with patch.object(runner, 'SCRIPTS_DIR', root):
            result = runner.run('probe', params={'source': str(source)}, out_dir=root/'out', timeout_s=300)
    print('all passed' if result['ok'] else f"FAILED {result.get('error')}")
    sys.exit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
