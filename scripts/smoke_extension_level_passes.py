#!/usr/bin/env python3
"""Smoke (Blender): the source levelling's flat subdivision counts what the stub's passes COVER, not whether they
reach the source point (review 03, below the cut-off: ``extension_bones.level_sides``; ``source_passes``).

Usage:  ./.venv/bin/python scripts/smoke_extension_level_passes.py

Runs headless Blender (``app.blender.runner``, CPU), no world, no model: a probe execs extension_bones.py and calls
``source_passes`` directly.

Numbers, by hand: radius R = .0045, tip_diameter .009, tip_wall .0015 -> ``level_full`` = max(1.2 R = .0054,
NEUTRAL_MIN_M .012, .0045 + .0015 + .003 = .009) = .012; neutral pass radii 1.9 x .012 = .0228 and 1.5 x .012 = .018.
Stub passes subdivide_radii [2.4, 1.8, 1] x R = .0108 / .0081 / .0045. A midpoint at distance x from the source
(on a line); pass i cuts it when x <= r_i and fewer than i + 1 stub passes cover it. Answers as (pass 0, pass 1):
[1] no placed tip: x = .015 -> (yes, yes); x = .02 -> (yes, no); x = .03 -> (no, no).
[2] a tip AT the source: x = .005 (stub cuts 2: .0108, .0081) -> (no, no); x = .009 (stub cuts 1) -> (no, yes);
    x = .015 (stub cuts 0) -> (yes, yes); x = .02 -> (yes, no). Every point ends with max(neutral, stub) cuts.
    On 69aeeba75 all three stub passes "reach" the source point, so no neutral pass ran at all: x = .015 kept 0
    cuts where the levelling wants 2.
[3] a tip 20 mm away (stub covers the source side up to .0108 from it): x = .015 toward the tip (5 mm from it,
    stub cuts 2) -> (no, no); x = .015 away from it (35 mm off) -> (yes, yes).
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROBE = r'''
import json, sys
from pathlib import Path
from mathutils import Vector
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
source=Path(job['params']['source']); scope={'__file__':str(source)}
exec(compile(source.read_text(),str(source),'exec'),scope)
R=.0045; base=dict(tip_diameter=.009,tip_wall=.0015,subdivide_radii=[2.4,1.8,1.])
full=scope['level_full'](base,R)
assert abs(full-.012)<1e-12,full
o=Vector((0,0,0))
def run(tips,x):
 return tuple(bool(f(Vector((x,0,0)))) for f in scope['source_passes'](o,tips,base,R,full))
far=[Vector((.02,0,0))]
cases=[('1a',[],.015,(True,True)),('1b',[],.02,(True,False)),('1c',[],.03,(False,False)),
 ('2a',[o],.005,(False,False)),('2b',[o],.009,(False,True)),('2c',[o],.015,(True,True)),('2d',[o],.02,(True,False)),
 ('3a',far,.015,(False,False)),('3b',far,-.015,(True,True))]
fails=[(label,run(t,x),want) for label,t,x,want in cases if run(t,x)!=want]
Path(job['result']).write_text(json.dumps({'ok':not fails,'error':repr(fails),'data':{},'outputs':{}}))
'''


def main():
    from app.blender import runner
    if not runner.status()['executable']:
        raise RuntimeError('Blender executable unavailable; no checks ran')
    with tempfile.TemporaryDirectory(prefix='level-passes-') as tmp:
        root = Path(tmp)
        (root/'probe.py').write_text(PROBE)
        source = runner.SCRIPTS_DIR/'extension_bones.py'
        with patch.object(runner, 'SCRIPTS_DIR', root):
            result = runner.run('probe', params={'source': str(source)}, out_dir=root/'out', timeout_s=120)
    print('all passed' if result['ok'] else f"FAILED {result.get('error')}")
    sys.exit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
