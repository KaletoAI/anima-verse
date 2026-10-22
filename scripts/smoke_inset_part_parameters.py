#!/usr/bin/env python3
"""Hand-derived inset settings: cleft .10 m, depth .009 m, two scales in [0,1].

A partial inner override preserves its .014 m ramp. Unknown settings, nonfinite
numbers, nonpositive or fractional fill counts, zero widths and reversed
intervals must fail before scene allocation. The fill defaults to 1500 steps;
a positive integer override is accepted.
"""
import ast
import copy
import math
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[1] / 'app/blender/scripts/inset_part.py'
    module = ast.parse(source.read_text())
    definitions = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'parameters'
                   or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)]
    scope = {'copy': copy, 'math': math}
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
    print('PASS inset_part defaults, nested overrides and invalid parameter cases')


if __name__ == '__main__':
    main()
