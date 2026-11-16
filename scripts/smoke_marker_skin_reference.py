"""Colour marker reference skin tone ignores dark hair cells (Ruling A120).

Usage: ./.venv/bin/python scripts/smoke_marker_skin_reference.py
Runs ``extension_bones.marker_accept`` inside Blender (the module imports bpy)
on a hand-built window of CIE Lab cells, b = 12 everywhere so the yellow term
is 0 and the score is a - a_ref (pack values: score_min 6, dark_min .55,
light_max 3):

  40 skin cells  L 70 a 2
  20 skin cells  L 70 a 8
  40 hair cells  L 30 a 10
   6 tip cells   L 45 a 13

All 106 cells, sorted by a: 40 x 2 (1-40), 20 x 8 (41-60), 40 x 10, 6 x 13 —
the median is the mean of the 53rd and 54th, a_ref = 8; sorted by L:
40 x 30, 6 x 45, 60 x 70 -> L_ref = 70, gate .55 * 70 = 38.5. The old plain
median gives the tip cells 13 - 8 = 5 < 6: no marker at all.
Gated: the 40 hair cells (L 30 < 38.5) leave; 66 cells, a sorted 40 x 2,
20 x 8, 6 x 13 -> 33rd/34th = 2, L_ref 70. Tip: 13 - 2 = 11 > 6 and
38.5 < 45 < 73 -> accepted; skin a 8: 8 - 2 = 6, not > 6 -> rejected; skin
a 2: 0; hair: 10 - 2 = 8 but L 30 < 38.5 -> rejected. So exactly the 6 tip
cells. A window without dark cells (the 60 skin + 6 tip cells only) has the
same gated and plain median (a_ref 2), so nothing changes there."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROBE = r'''
import sys, json
sys.path.insert(0, SCRIPTS)
import numpy as np
import extension_bones as eb
p = {'marker_score_min': 6, 'marker_yellow_weight': .5, 'marker_dark_min': .55, 'marker_light_max': 3}
rows = [(70,2,12)]*40 + [(70,8,12)]*20 + [(30,10,12)]*40 + [(45,13,12)]*6
ok = eb.marker_accept(np.array(rows,float), p)
clean = eb.marker_accept(np.array(rows[:60]+rows[100:],float), p)
json.dump({'ok': ok.tolist(), 'clean': clean.tolist()}, open(OUT, 'w'))
'''


def main():
    from app.blender import runner
    exe = runner.status()['executable']
    if not exe:
        raise RuntimeError('Blender executable unavailable; no checks ran')
    with tempfile.TemporaryDirectory(prefix='marker-ref-') as tmp:
        out = Path(tmp) / 'out.json'
        script = Path(tmp) / 'probe.py'
        script.write_text('SCRIPTS=%r\nOUT=%r\n' % (str(runner.SCRIPTS_DIR), str(out)) + PROBE)
        subprocess.run([exe, '-b', '--factory-startup', '--python-exit-code', '1', '--python', str(script)],
                       check=True, capture_output=True, timeout=120)
        data = json.loads(out.read_text())
    ok, clean = data['ok'], data['clean']
    assert ok == [False] * 100 + [True] * 6, ok
    assert clean == [False] * 60 + [True] * 6, clean
    print('PASS marker skin reference: hair cells left out of the reference, 6 tip cells accepted')


if __name__ == '__main__':
    main()
