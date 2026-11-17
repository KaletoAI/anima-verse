#!/usr/bin/env python3
"""attached_part places each link bone at the ARC-LENGTH fraction its weights use (review 03#7).

The weights cut the links by ``part_station`` (arc-length fraction of the sweep);
the bones used to be looked up by curve parameter (sample index), which on the
real sweep (speed differs 1.84x between its ends) put every joint 2-8 mm short.
``arc_point`` is loaded by AST (no Blender needed).

Hand-derived fixture: a polyline along x through 0, 1, 3, 6 (segment lengths
1, 2, 3, total 6), so the arc fractions are 0, 1/6, 1/2, 1.
  t = .25 -> on segment 1..3: 1 + (.25 - 1/6) / (1/3) * 2 = 1.5
  t = .75 -> on segment 3..6: 3 + (.75 - .5) / .5 * 3 = 4.5
  t = 0 -> 0, t = 1 -> 6, t = 1/2 -> 3 (a sample itself).
The old lookup centerline[round(t * 3)] gives 1 for t = .25 and 3 for t = .75
(0.5 and 1.5 short), which the check shows with the old formula inline.

Usage: ./.venv/bin/python scripts/smoke_attached_part_bone_stations.py
"""
import ast
from pathlib import Path

import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / 'app/blender/scripts/attached_part.py'


def main():
    module = ast.parse(SOURCE.read_text(encoding='utf-8'))
    body = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'arc_point']
    assert body, 'arc_point missing'
    scope = {'np': np}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), 'exec'), scope)
    arc_point = scope['arc_point']
    points = np.array([(0., 0., 0.), (1., 0., 0.), (3., 0., 0.), (6., 0., 0.)])
    length = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    stations = length / length[-1]
    assert np.allclose(stations, [0, 1 / 6, .5, 1])
    for t, want in ((0, 0), (.25, 1.5), (.5, 3), (.75, 4.5), (1, 6)):
        got = arc_point(t, stations, points)
        assert abs(got[0] - want) < 1e-12 and got[1] == 0 and got[2] == 0, (t, got)

    def old(t):  # the replaced lookup: sample index by curve parameter
        return points[int(round(t * (len(points) - 1)))]
    assert old(.25)[0] == 1 and old(.75)[0] == 3, 'old lookup lands short of the arc fraction'
    src = SOURCE.read_text(encoding='utf-8')
    assert 'idx_t = lambda t: Vector(arc_point(t, stations[12:], centerline[12:]))' in src, \
        'bone placement must use the arc-length stations of the sweep'
    print('PASS attached_part bone stations: bones at the arc fractions of their weight boundaries (5 points)')


if __name__ == '__main__':
    main()
