#!/usr/bin/env python3
"""Usage: ./.venv/bin/python scripts/smoke_inset_part_pelvis.py

The pelvis rule of the inset part (Ruling A117), on synthetic weights; every number hand-derived.

``pelvis_level(x, inner=.02, outer=.04)`` is the smoothstep of t = (x + .04) / .06:
* x = -.05 and x = -.04 (outer edge and beyond): 0; x = .02 and .03 (inner edge and deeper): 1.
* x = -.01: t = .5, level .5. x = 0 (the welded border): t = 2/3, level 3(4/9) - 2(8/27) = 20/27 = .740741.
* sampled from -.06 to .04 the level never decreases.

``pelvis_weights(weights, floors, 'Hips')`` raises Hips' share of the vertex's total to the floor and scales the rest:
* {Hips .2, L .5, R .3}, floor .7: Hips .7, the rest x (1 - .7)/.8 = .375 -> L .1875, R .1125 (sum 1).
* {Hips .2, L .6} (total .8), floor .5: Hips .5 x .8 = .4, L .6 x (.5 x .8 / .6) = .4 (total .8 stays).
* {L 1} (no Hips), floor .9: Hips .9, L .1.
* {Hips .8, L .2} with floor .7, and any vertex with floor 0: unchanged.
A line of vertices with Hips .2 / L .8 at x = -.05 .. .03 under share .9: the outside (x <= -.04) is unchanged, the
Hips share never decreases with x, and from x = .02 (the rim and deeper) it is exactly .9.

``skin_distance`` on a path 0-1-2-3 at x = 0, .01, .03, .06, seed 0, limit .04: {0: 0, 1: .01, 2: .03}; 3 is
past the limit. Vertex 4 coincides with 2 (a seam copy, joined at length 0): .03. Vertex 5 at (.01, .01) joined to
0 and 2: |5| = .014142, and the path to 2 through it (.014142 + sqrt(.02^2 + .01^2) = .036503) loses to .03.
``harmonic_fill`` (A169, the band's blend on the welded mesh) on a path 0-1-2-3-4 of equal edges, 0 fixed at 1 and 4
at 0: the free nodes take the straight line .75 / .5 / .25. On 0-1-2 with edges .01 and .03 (weights 100 and 100/3),
0 fixed at 1, 2 at 0: node 1 = 100 / (100 + 100/3) = .75. Two columns are solved at once (the second, 0 -> 0 and
2 -> 1, gives .25). A free node 5 joined only to a free node 6 keeps its start value .4.
Parameters: share 0 (off), ring .5, spread .5 by default; share 1.1, ring 0, ring 1.5, spread -.1, spread 4.5 fail.
"""
import ast
import copy
import math
from pathlib import Path

import numpy as np


def main():
    source = Path(__file__).resolve().parents[1] / 'app/blender/scripts/inset_part.py'
    module = ast.parse(source.read_text())
    names = ('parameters', 'pelvis_level', 'pelvis_weights', 'skin_distance', 'harmonic_fill')
    definitions = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in names
                   or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('DEFAULTS', 'HARMONIC_ITERATIONS', 'HARMONIC_TOLERANCE') for t in n.targets)]
    scope = {'copy': copy, 'math': math, 'np': np}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), 'exec'), scope)
    level, weights, distance, parameters = (scope[n] for n in ('pelvis_level', 'pelvis_weights', 'skin_distance', 'parameters'))
    harmonic = scope['harmonic_fill']
    close = lambda a, b: abs(a - b) < 1e-9

    got = level(np.array([-.05, -.04, -.01, 0., .02, .03]), .02, .04)
    for g, want in zip(got, (0, 0, .5, 20 / 27, 1, 1)):
        assert close(g, want), (got, want)
    xs = np.linspace(-.06, .04, 201)
    assert (np.diff(level(xs, .02, .04)) >= -1e-12).all(), 'level decreases'

    w = weights([{'Hips': .2, 'L': .5, 'R': .3}, {'Hips': .2, 'L': .6}, {'L': 1.}, {'Hips': .8, 'L': .2}, {'Hips': .1, 'L': .9}],
                [.7, .5, .9, .7, 0.], 'Hips')
    assert close(w[0]['Hips'], .7) and close(w[0]['L'], .1875) and close(w[0]['R'], .1125)
    assert close(w[1]['Hips'], .4) and close(w[1]['L'], .4)
    assert close(w[2]['Hips'], .9) and close(w[2]['L'], .1)
    assert w[3] == {'Hips': .8, 'L': .2} and w[4] == {'Hips': .1, 'L': .9}

    x = np.linspace(-.05, .03, 81)
    line = weights([{'Hips': .2, 'L': .8}] * len(x), .9 * level(x, .02, .04), 'Hips')
    share = np.array([v['Hips'] / sum(v.values()) for v in line])
    assert all(v == {'Hips': .2, 'L': .8} for v, xi in zip(line, x) if xi <= -.04), 'outside changed'
    assert (np.diff(share) >= -1e-12).all(), 'ring blend not monotone'
    assert all(close(s, .9) for s, xi in zip(share, x) if xi >= .02 - 1e-12), 'rim below the share'
    assert all(close(sum(v.values()), 1.) for v in line)

    pos = np.array([[0, 0, 0], [.01, 0, 0], [.03, 0, 0], [.06, 0, 0], [.03, 0, 0], [.01, .01, 0]], float)
    adjacency = [[1, 5], [0, 2], [1, 3, 4, 5], [2], [2], [0, 2]]
    d = distance(adjacency, pos, [0], .04)
    assert set(d) == {0, 1, 2, 4, 5}, d
    assert close(d[0], 0) and close(d[1], .01) and close(d[2], .03) and close(d[4], .03) and close(d[5], math.sqrt(2) * .01)

    line5 = harmonic(5, [[0, 1], [1, 2], [2, 3], [3, 4]], [1.] * 4, [False, True, True, True, False], np.array([[1.], [0], [0], [0], [0]]))
    assert np.allclose(line5[:, 0], [1, .75, .5, .25, 0], atol=1e-6), line5
    two = harmonic(7, [[0, 1], [1, 2], [5, 6]], [.01, .03, .01], [False, True, False, False, False, True, True],
                   np.array([[1., 0], [0, 0], [0, 1], [0, 0], [0, 0], [.4, .4], [.4, .4]]))
    assert abs(two[1, 0] - .75) < 1e-6 and abs(two[1, 1] - .25) < 1e-6, two
    assert np.allclose(two[5], .4) and np.allclose(two[6], .4), two

    p = parameters({})['pelvis']
    assert p == {'bone': 'Hips', 'share': 0.0, 'ring': .5, 'spread': .5}, p
    assert parameters({'pelvis': {'share': .9, 'spread': 2.0}})['pelvis']['ring'] == .5
    for bad in ({'share': 1.1}, {'ring': 0}, {'ring': 1.5}, {'spread': -.1}, {'spread': 4.5}, {'bone': ''}):
        try:
            parameters({'pelvis': bad})
        except ValueError:
            continue
        raise AssertionError('accepted ' + str(bad))
    print('smoke_inset_part_pelvis: OK')


if __name__ == '__main__':
    main()
