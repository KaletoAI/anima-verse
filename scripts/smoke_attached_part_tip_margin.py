#!/usr/bin/env python3
"""The attached part's tip stays inside the voxel grid and on the chain (build 15).

Usage: ./.venv/bin/python scripts/smoke_attached_part_tip_margin.py
Runs Blender 5.2 on the CPU against the script's pure helpers; no world, no server, no network.

Hand-derived expectations (defaults: radius .0165 m, girth_max 1.0, tip_girth 1.05, tip_start 1 - .32 * .85 = .728):
[1] grid_margin = .02 + ceil(radius * size_factor * max(girth_max, tip_girth) / voxel) * voxel, voxel .0014:
      size 1.0: .0165 * 1.05 = .017325 = 12.375 voxels -> 13 -> .0182 -> .0382;
      size 1.6: .0264 * 1.05 = .02772 = 19.8 voxels -> 20 -> .028 -> .048;
      size 1.8 ('massive'): .0297 * 1.05 = .031185 = 22.275 voxels -> 23 -> .0322 -> .0522.
    At 1.8 the margin leaves .0522 - .031185 = .021015 >= .02 beyond the tip's widest radius, where the fixed .02 of
    build 14 left .02 - .031185 = -.011185 (the surface ran out of the grid). The extra is a whole number of voxels
    (13, 20, 23), so the lattice keeps the phase of the .02 grid. Proof on the old code, pinned to f70077f3c: its
    source has `lo, hi = pts.min(0) - .02, pts.max(0) + .02`.
[2] border_loops_of: two quads sharing no vertex, (0,1,2,3) and (4,5,6,7), each edge in one face -> 2 loops of 4.
    A third quad (2,3,8,9) glued to the first along edge (2,3) (now in 2 faces) makes one open strip whose border is
    0-1-2-9-8-3 (6 vertices): loops of 4 and 6.
[3] attachment_loop with root (0, 0, 0): loop A at x = 0..1 (nearest point 0 m away), loop B at x = 5..6 -> A.
[4] off_chain_tip_vertices with tip_start .728, stations (.5, .8, .9, .95, .73), shaft nearer (T, T, T, F, T),
    chain share (.2, .4, .9, .1, .49): .5 is before the tip (not counted although .2), .8 counts (.4 < .5), .9 not
    (.9), .95 is on the pods' side (not counted), .73 counts (.49 < .5) -> 2.
[5] The build fails on such vertices and reports `tip_off_chain_vertices`; PART_BUILDS['attached_part'] is 15.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'
OLD = 'f70077f3c'


def blender_side(scripts, out):
    sys.path.insert(0, scripts)
    import attached_part as ap
    margins = {str(f): ap.grid_margin(.0165 * f, 1.0, 1.05, .0014) for f in (1.0, 1.6, 1.8)}
    two = {(0, 1): 1, (1, 2): 1, (2, 3): 1, (0, 3): 1, (4, 5): 1, (5, 6): 1, (6, 7): 1, (4, 7): 1}
    strip = {(0, 1): 1, (1, 2): 1, (2, 3): 2, (0, 3): 1, (2, 9): 1, (8, 9): 1, (3, 8): 1,
             (4, 5): 1, (5, 6): 1, (6, 7): 1, (4, 7): 1}
    pts = [(x, 0, 0) for x in (0, 1, 1, 0)] + [(x, 0, 0) for x in (5, 6, 6, 5)]
    loops_two = ap.border_loops_of(two)
    attach = ap.attachment_loop(loops_two, pts, (0, 0, 0))
    count = ap.off_chain_tip_vertices([.5, .8, .9, .95, .73], [True, True, True, False, True],
                                      [.2, .4, .9, .1, .49], .728)
    Path(out).write_text(json.dumps({
        'margins': margins, 'loops_two': sorted(len(x) for x in loops_two),
        'loops_strip': sorted(len(x) for x in ap.border_loops_of(strip)), 'attach': sorted(attach),
        'count': count}))


def main():
    failures = []

    def check(label, ok, detail=''):
        print(('ok   ' if ok else 'FAIL ') + label + (f'  ({detail})' if detail else ''))
        if not ok:
            failures.append(label)
    with tempfile.TemporaryDirectory(prefix='tip-margin-') as directory:
        out = Path(directory) / 'out.json'
        log = Path(directory) / 'log.txt'
        with log.open('w') as stream:
            r = subprocess.run(['nice', '-n', '15', 'timeout', '600', str(BLENDER), '-b', '-noaudio', '--factory-startup',
                                '--python-exit-code', '1', '--python', str(Path(__file__).resolve()), '--', '--blender',
                                str(ROOT / 'app/blender/scripts'), str(out)], stdout=stream, stderr=subprocess.STDOUT,
                               env={**os.environ, 'PYTHONNOUSERSITE': '1'})
        if r.returncode:
            print(log.read_text()[-4000:])
            raise SystemExit(r.returncode)
        d = json.loads(out.read_text())
    for size, want, steps in (('1.0', .0382, 13), ('1.6', .048, 20), ('1.8', .0522, 23)):
        check(f'[1] grid_margin at size {size} = {want}', abs(d['margins'][size] - want) < 1e-9, d['margins'][size])
        check(f'[1] at size {size} the extra is {steps} whole voxels',
              abs((d['margins'][size] - .02) / .0014 - steps) < 1e-6)
    check('[1] at 1.8 the margin leaves .021015 beyond the tip radius .031185',
          abs(d['margins']['1.8'] - .031185 - .021015) < 1e-9)
    old = subprocess.run(['git', '-C', str(ROOT), 'show', f'{OLD}:app/blender/scripts/attached_part.py'],
                         capture_output=True, text=True)
    check(f'[1] old code ({OLD}) used the fixed .02 margin',
          old.returncode == 0 and 'lo, hi = pts.min(0) - .02, pts.max(0) + .02' in old.stdout)
    check('[2] two separate quads -> loops of 4 and 4', d['loops_two'] == [4, 4], d['loops_two'])
    check('[2] a glued quad -> loops of 4 and 6', d['loops_strip'] == [4, 6], d['loops_strip'])
    check('[3] the attachment loop is the one at the root', d['attach'] == [0, 1, 2, 3], d['attach'])
    check('[4] two tip vertices off the chain', d['count'] == 2, d['count'])
    src = (ROOT / 'app/blender/scripts/attached_part.py').read_text()
    check('[5] the build fails on a tip off the chain',
          "if tip_off_chain:\n        raise ValueError" in src and "'tip_off_chain_vertices': tip_off_chain" in src)
    check('[5] the grid uses the margin', 'lo, hi = pts.min(0) - margin, pts.max(0) + margin' in src)
    sys.path.insert(0, str(ROOT))
    from app.core.extension_rig import PART_BUILDS
    check('[5] PART_BUILDS attached_part 15', PART_BUILDS['attached_part'] == 15, PART_BUILDS)
    if failures:
        raise SystemExit('FAIL attached part tip margin: ' + ', '.join(failures))
    print('PASS attached part tip margin: the grid holds the tip, the tip rides the chain')


if __name__ == '__main__':
    if '--blender' in sys.argv:
        i = sys.argv.index('--blender')
        blender_side(sys.argv[i + 1], sys.argv[i + 2])
    else:
        main()
