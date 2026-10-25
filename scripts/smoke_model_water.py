#!/usr/bin/env python3
"""Water storage checks, no Blender or world DB.

Hand calculation: box [-1,0,-1]..[1,2,1], max_m=4 gives s=2.
Vertex (-1,-1) relative to centre (0,0), yaw +90 maps (x,z) to
(z,-x)*2 = (-2,2); anchor (2,3) makes (0,5). Level .5 and
bottom_y .25 give y=1.25; clarity .75 gives opacity 1-.6*.75=.55.
Usage: ./.venv/bin/python scripts/smoke_model_water.py
"""
import copy
import ast
import math
import heapq
from collections import defaultdict, deque
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import model_water as w
from app.core.model_surface import _source_of


def fixture(model):
    return dict(version=1, source=_source_of(model), rotation={},
                box_min=[-1, 0, -1], box_max=[1, 2, 1], extent_snapped=[2, 2, 2],
                step=.02, step_world=.02, regions=[dict(
                    id='r1', kind='basin', confidence='sure', enabled=True,
                    outline=[[-1, -1], [1, -1], [1, 1], [-1, 1]], holes=[],
                    level=.5, bed=0, area_m2=4, depth_m=.5, level_user=False,
                    look=w.sanitize_look({'preset': 'pool'}))])


def main():
    assert w.sanitize_look({'preset': 'bath', 'tint': 'bad', 'clarity': 4}) == {
        'preset': 'bath', 'tint': '#bfe3ea', 'clarity': 1.0}
    assert w.sanitize_look({'preset': 'unknown'})['preset'] == 'pool'
    assert w.sanitize_look({'preset': []})['preset'] == 'pool'
    assert w.sanitize_look({'preset': 'unknown', 'tint': '#AbCdEf'})['preset'] == 'custom'
    assert len(w.manual_region('ellipse', [0, 0], [2, 1], .5)['outline']) == 32
    assert w.manual_region('rect', [0, 0], [2, 1], .5)['outline'][0] == [-1, -.5]
    with tempfile.TemporaryDirectory() as tmp:
        model = Path(tmp) / 'pool.glb'
        model.write_bytes(b'model')
        data = fixture(model)
        w.water_path(model).write_text(json.dumps(data))
        assert w.water_status(model, {})['status'] == 'valid'
        assert w.read_water(model, {'x': 90}) is None
        spec = dict(anchor=[2, 3], yaw_deg=90, max_m=4, measure='xyz', bottom_y=.25)
        block = w.compose_regions(w.read_water(model, {}), spec)
        r = block['regions'][0]
        assert all(abs(a-b) < 1e-8 for a, b in zip(r['outline'][0], [0, 5]))
        assert r['y'] == 1.25 and abs(r['opacity']-.55) < 1e-8
        oldsig = w.block_sig(block)
        result = w.patch_water(model, {}, {'regions': [{'id': 'r1', 'enabled': False,
                                     'level': 99, 'look': {'preset': 'bath'}}],
                                     'add': {'shape': 'rect', 'center': [0, 0],
                                             'size': [.5, .5], 'level': .2}})
        assert result['regions'][0]['level'] == 2
        assert result['regions'][0]['level_user']
        assert w.block_sig(w.compose_regions(result, spec)) != oldsig
        try:
            w.patch_water(model, {}, {'regions': [{'id': 'missing', 'enabled': True}]})
            raise AssertionError('unknown id accepted')
        except ValueError:
            pass
        # Blender is mocked at the process boundary; the real wrapper writes and merges.
        detected = copy.deepcopy(data)
        detected['regions'][0]['id'] = 'r99'
        detected['regions'][0]['outline'] = [[-.8, -.8], [.8, -.8], [.8, .8], [-.8, .8]]
        with patch('app.blender.runner.is_available', return_value=True), \
             patch('app.blender.runner.run', side_effect=lambda *a, **k: {'ok': True, 'data': copy.deepcopy(detected)}), \
             patch('app.blender.refine.take_lod_slot', return_value=True), \
             patch('app.blender.refine.free_lod_slot'):
            merged, reason = w.detect_water(model, {}, target_m=2, measure='xyz')
        assert reason == 'ok'
        assert [r['id'] for r in merged['regions']] == ['r1', 'm1']
        assert not merged['regions'][0]['enabled']
        assert merged['regions'][0]['level'] == 2
        assert merged['regions'][0]['depth_m'] == 2
        assert merged['regions'][0]['look']['preset'] == 'bath'
        assert merged['regions'][1] == result['regions'][1]
        # Rewrites preserve choices only in the same orientation frame.
        model.write_bytes(b'rewritten model')
        assert w.water_status(model, {})['status'] == 'stale'
        with patch('app.blender.runner.is_available', return_value=True), \
             patch('app.blender.runner.run', side_effect=lambda *a, **k: {'ok': True, 'data': copy.deepcopy(detected)}), \
             patch('app.blender.refine.take_lod_slot', return_value=True), \
             patch('app.blender.refine.free_lod_slot'):
            refreshed, reason = w.detect_water(model, {}, target_m=2, measure='xyz')
            assert reason == 'ok'
            assert refreshed['regions'] == merged['regions']
            model.write_bytes(b'rewritten again')
            rotated, reason = w.detect_water(model, {'x':90}, target_m=2, measure='xyz')
            assert reason == 'ok'
            assert len(rotated['regions']) == 1
            assert rotated['regions'][0]['enabled']
            assert not rotated['regions'][0]['level_user']
            assert rotated['regions'][0]['look']['preset'] == 'pool'
        for corrupt in ('level', 'look', 'outline'):
            broken = copy.deepcopy(merged)
            broken['regions'][0][corrupt] = {'level':'0.5', 'look':{'preset':[]},
                                             'outline':[['0',0],[1,0],[1,1]]}[corrupt]
            w.water_path(model).write_text(json.dumps(broken))
            assert w.read_water(model, {}) is None, corrupt
        model.write_bytes(b'changed model')
        assert w.read_water(model, {}) is None
        assert w.water_status(model, {})['status'] == 'stale'
        w.water_path(model).write_text('{broken')
        assert w.read_water(model, {}) is None
    # Execute only the pure raster functions: no bpy import or Blender process.
    tree = ast.parse(Path('app/blender/scripts/waterdetect.py').read_text())
    names = {'_neighbors', '_flood', '_components', '_percentile', '_simplify',
             '_area', '_outlines', '_regions'}
    pure = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                            and n.name in names], type_ignores=[])
    ns = dict(math=math, heapq=heapq, defaultdict=defaultdict, deque=deque)
    exec(compile(pure, 'waterdetect-pure', 'exec'), ns)
    # 2x1 interior sampled on a .02 grid, enclosed by a one-node rim at y=1.
    cols, rows = 103, 53
    h = [1. if i % cols in (0, cols-1) or i // cols in (0, rows-1) else 0.
         for i in range(cols*rows)]
    blue = [v == 0 for v in h]
    regions = ns['_regions'](h, [1.]*len(h), blue, cols, rows,
                             [0,0,0], .02, 1., 'xyz')
    assert len(regions) == 1 and regions[0]['enabled']
    assert abs(regions[0]['level']-.92) < 1e-8
    assert abs(regions[0]['area_m2']-2) < .2
    assert ns['_area'](regions[0]['outline']) > 0
    assert ns['_regions'](h, [1.]*len(h), [False]*len(h), cols, rows,
                          [0,0,0], .02, 1., 'xz') == []
    # A submerged ridge connects the depression but emerges above its water
    # level: the remaining two pockets need separate outer rings.
    split_h = list(h)
    for z in range(1, rows-1):
        split_h[z*cols+cols//2] = .95
    split = ns['_regions'](split_h, [1.]*len(h), blue, cols, rows,
                           [0,0,0], .02, 1., 'xyz')
    assert len(split) == 2 and all(not r['holes'] for r in split)
    # 56 nodes at .1 m have .56 m² area, over 60% of a .9x.9 box
    # (.486 m²). The denominator is the box footprint, not 100 nodes.
    wide = [0. if 1 <= i % 10 <= 7 and 1 <= i // 10 <= 8 else 1.
            for i in range(100)]
    assert ns['_regions'](wide, [1.]*100, [False]*100, 10, 10,
                          [0,0,0], .1, 1., 'xyz') == []
    # A dry elevated island creates a clockwise hole in a painted film.
    mask = {z*10+x for z in range(1,9) for x in range(1,9)
            if not (3 <= x <= 5 and 3 <= z <= 5)}
    outer, holes = ns['_outlines'](mask, 10, 10, [0,0,0], .1)
    assert ns['_area'](outer) > 0 and len(holes) == 1 and ns['_area'](holes[0]) < 0
    print('smoke_model_water: PASS')


if __name__ == '__main__':
    main()
