#!/usr/bin/env python3
"""Hand-derived inset settings: cleft .10 m, depth .009 m, two scales in [0,1].

A partial inner override preserves its .014 m ramp. Unknown settings, nonfinite
numbers, zero widths and reversed intervals must fail before scene allocation.
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
    for value in ({'open': 0}, {'cleft': {'unknown': 1}}, {'inner_scale': 1.1}, {'nub_scale': -.1},
                  {'edge': [0, .002, .005]}, {'bake': 1.5}, {'shift': float('nan')},
                  {'theta': [2, 1]}, {'cleft': {'s1': -.1}}, {'mound': {'ss': 0}}, {'eps': True}, {'tone': {'inner': [0, .5, .5]}}):
        try:
            parameters(value)
        except ValueError:
            pass
        else:
            raise AssertionError('Accepted invalid settings: ' + str(value))
    print('PASS inset_part defaults, nested overrides and 12 invalid parameter cases')


if __name__ == '__main__':
    main()
