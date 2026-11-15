#!/usr/bin/env python3
"""Hand-derived inset settings: cleft .10 m, depth .009 m, two scales in [0,1].

A partial inner override preserves its .014 m ramp. Unknown settings, nonfinite
numbers, nonpositive or fractional fill counts, zero widths and reversed
intervals must fail before scene allocation. The fill defaults to 1500 steps;
a positive integer override is accepted.

The opening (Task 11) on a synthetic 3-point profile, hand-derived:
prof = (0,0,0), (0,-.1,-.2), (0,-.3,-.2) at S = 0, .1, .3; outward normals pn = (0,0,-1), (0,-1,0), (0,-1,0);
xm = .5, s_mid = .05 (halfway between the first two points).
* Identity matrices: the midline point is (xm, -.05, -.1); glTF (x, z, -y) gives centre (.5, -.1, .05). The
  interpolated outward normal is (0, -.5, -.5), inward (0, .5, .5), unit (0, .707107, .707107); glTF
  (0, .707107, -.707107).
* Mi = scale 2 plus translation (1, 2, 3), Ni3 = scale 2: the point becomes (2, 1.9, 2.8), glTF (2, 2.8, -1.9);
  the uniform scale leaves the unit axis as before.
The opening's interval is the pocket as built: [s0, s1] without a part end; with one, the pocket's depth fades to
zero over ``region.fall`` before ``s_end`` (smoothstep, half depth at s_end - fall/2), so the interval ends there:
* pocket .048 to .094, no end: s_mid = (.048 + .094)/2 = .071.
* s_end .0592, fall .012: the end .0592 - .006 = .0532 < .094, s_mid = (.048 + .0532)/2 = .0506.
* s_end .10, fall .012: the end .10 - .006 = .094 does not cut s1 = .094, so s_mid stays .071.
* s_end .05, fall .012: .044 <= .048, no pocket is built -> None.
"""
import ast
import copy
import math

import numpy as np
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[1] / 'app/blender/scripts/inset_part.py'
    module = ast.parse(source.read_text())
    definitions = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in ('parameters', '_gltf', 'opening_metric', 'opening_s')
                   or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)]
    scope = {'copy': copy, 'math': math, 'np': np}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), 'exec'), scope)
    parameters = scope['parameters']
    p = parameters({'inner': {'w': .5}})
    assert p['cleft']['s1'] - p['cleft']['s0'] == .10
    assert p['cleft']['depth'] == .009 and p['inner']['ramp'] == .014
    assert p['inner_scale'] == 0 and p['nub_scale'] == .5 and p['bake'] == 512
    assert p['centre_height'] == .07 and p['under'] == [50, 105]
    assert p['under_ref'] == .138 and p['scale_min'] == .75 and p['centre_offset'] == -.013
    assert p['fill_iterations'] == 1500
    assert parameters({'fill_iterations': 7})['fill_iterations'] == 7
    for value in ({'fill_iterations': 0}, {'fill_iterations': -1},
                  {'fill_iterations': 1.5}, {'fill_iterations': True},
                  {'anchor_drop': .1}, {'shift': .01}, {'under': [105, 50]}, {'under': [50, 50]},
                  {'centre_height': 0}, {'under_ref': 0}, {'scale_min': 0}, {'scale_min': 1.1}, {'open': 0}, {'cleft': {'unknown': 1}}, {'inner_scale': 1.1}, {'nub_scale': -.1},
                  {'edge': [0, .002, .005]}, {'bake': 1.5}, {'shift': float('nan')},
                  {'theta': [2, 1]}, {'cleft': {'s1': -.1}}, {'mound': {'ss': 0}}, {'eps': True}, {'tone': {'inner': [0, .5, .5]}}):
        try:
            parameters(value)
        except ValueError:
            pass
        else:
            raise AssertionError('Accepted invalid settings: ' + str(value))
    opening_metric, opening_s = scope['opening_metric'], scope['opening_s']
    prof = np.array([[0, 0, 0], [0, -.1, -.2], [0, -.3, -.2]], float)
    pn = np.array([[0, 0, -1], [0, -1, 0], [0, -1, 0]], float)
    S = np.array([0, .1, .3])
    r = .5 ** .5
    opening = opening_metric(prof, pn, S, .05, .5, np.eye(4), np.eye(3))
    assert set(opening) == {'centre', 'axis'}, opening
    assert np.allclose(opening['centre'], [.5, -.1, .05], atol=1e-9), opening
    assert np.allclose(opening['axis'], [0, r, -r], atol=1e-9), opening
    assert all(isinstance(v, float) for v in opening['centre'] + opening['axis'])
    Mi = np.diag([2., 2, 2, 1]); Mi[:3, 3] = (1, 2, 3)
    opening = opening_metric(prof, pn, S, .05, .5, Mi, np.diag([2., 2, 2]))
    assert np.allclose(opening['centre'], [2, 2.8, -1.9], atol=1e-9), opening
    assert np.allclose(opening['axis'], [0, r, -r], atol=1e-9), opening
    pocket = {'s0': .048, 's1': .094}
    assert abs(opening_s(pocket, None, .012) - .071) < 1e-12
    assert abs(opening_s(pocket, .0592, .012) - .0506) < 1e-12
    assert abs(opening_s(pocket, .10, .012) - .071) < 1e-12
    assert opening_s(pocket, .05, .012) is None
    print('PASS inset_part defaults, nested overrides, invalid parameter cases, opening metric and interval')


if __name__ == '__main__':
    main()
