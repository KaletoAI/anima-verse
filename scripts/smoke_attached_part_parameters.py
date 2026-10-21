#!/usr/bin/env python3
"""Hand-derived parameter checks, loading only stdlib parameter definitions.

Tip start = 1-.32*.85 = .728; minimum size uses length .095 and radius .0165.
Nested voxel/flatten controls must preserve the other defaults. Every unknown
key (including list-item keys), bool, nonfinite value and degenerate interval
must fail before Blender scene allocation. Empty ridges and pods are valid.
"""
import ast
import copy
import math
from pathlib import Path


def main():
    source=Path(__file__).resolve().parents[1]/'app/blender/scripts/attached_part.py'
    module=ast.parse(source.read_text())
    definitions=[node for node in module.body if
        isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DEFAULTS' for t in node.targets)
        or isinstance(node,ast.FunctionDef) and node.name=='parameters']
    scope={'math':math,'copy':copy}
    exec(compile(ast.Module(body=definitions,type_ignores=[]),str(source),'exec'),scope)
    parameters=scope['parameters']
    defaults=parameters({})
    assert abs(defaults['tip_start']-.728)<1e-12
    assert defaults['length']==.095 and defaults['radius']==.0165 and defaults['girth_max']==1.0 and defaults['tip_girth']==1.05 and defaults['tip_rim']==.012
    values=parameters({'flatten':{'iterations':0},'texture':{'bake':128}})
    assert values['flatten']['lateral']==.055 and values['texture']['blur']==9
    assert parameters({'pods':{'ellipsoids':[]},'ridges':[]})['ridges']==[]
    invalid=[{'unknown':1},{'flatten':{'unknown':1}}, {'ridges':[{'unknown':1}]},
             {'size_factor':True},{'radius':float('nan')},{'length':float('inf')},
             {'voxel':0},{'girth_max':0},{'bend':[[0,0,.38],[.25,.97,.7]]},
             {'bend':[[.85,.5,0],[.25,.97,.7]]},{'tip_start':.99},
             {'reweight':{'from':.1,'to':.01}},{'texture':{'blur':8}},
             {'texture':{'bake':1.5}},{'smooth':{'iterations':-1}},
             {'pods':{'ellipsoids':[{'radii':[0,.01,.01]}]}}]
    for raw in invalid:
        try: parameters(raw)
        except ValueError: pass
        else: raise AssertionError('Accepted invalid params: '+str(raw))
    build = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'build_part')
    weight_function = next(node for node in build.body if isinstance(node, ast.FunctionDef) and node.name == 'shaft_weights')
    tip = defaults['tip_start']
    edges = [.1 + (tip - .1)*k/4 for k in range(5)] + [1.]
    scope.update(anchor_name='Anchor', chain=[{'bone': 'Link'+str(i)} for i in range(5)],
                 link_count=5, link_centers=[(a+b)/2 for a,b in zip(edges,edges[1:])],
                 tip_start=tip, base_fraction=.15)
    exec(compile(ast.Module(body=[weight_function], type_ignores=[]), str(source), 'exec'), scope)
    weights = scope['shaft_weights']
    assert weights(0) == {'Link0': 0., 'Anchor': 1.}
    assert weights(.075) == {'Link0': .5, 'Anchor': .5}
    assert weights(tip) == {'Link4': .5, 'Link3': .5}
    assert abs(weights(tip+.0075)['Link4']-.75) < 1e-12
    assert weights(tip+.015) == {'Link4': 1.}
    print('PASS attached_part defaults, nested overrides, optional pods/ridges, 16 invalid parameter cases and continuous base/tip weight blends')


if __name__=='__main__': main()
