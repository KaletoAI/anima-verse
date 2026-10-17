"""Hull facts derived from composer walls, without a server or Blender.

Usage: ./.venv/bin/python scripts/smoke_hull_facts.py

Hand calculation: ground outline is 10 x 8, upper outline is 6 x 8.
Both run (0,0) -> (w,0) -> (w,8) -> (0,8), hence outward normals
(0,-1), (1,0), (0,1), (-1,0). Boundary bbox centre is (5,4).
For storey 3.0, wall height is 3.0 - 0.15 = 2.85. Storey floors
are 0 and 3 + 0.08 = 3.08; top_y are 3.08 and 3.08 + 2.85 = 5.93.
Room B stands on its room plate at 3 + 0.10 = 3.10. The 0.02 gap
below its walls is less than 0.05 and ignored, not a facade opening.
Ground window edge 0: 10*0.5 +/- 1.2/2 = [4.4,5.6], y=[0.9,2.1].
Ground door edge 2: 10*0.3 +/- 1/2 = [2.5,3.5], y=[0,2.1].
Upper window edge 1: 8*0.5 +/- 1.2/2 = [3.4,4.6],
y=[3.10+0.9,3.10+0.9+1.2]=[4.0,5.2].
Upper passage edge 3: 8*0.5 +/- 1/2 = [3.5,4.5],
y=[3.08,3.10+2.4]=[3.08,5.5]; its uncovered band starts at 3.08.
All other edges are solid. The sunk ground walls are clipped to y=0.
Moving window at to 0.6 shifts its span to [5.4,6.6].
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory(prefix="hull-facts-smoke-") as storage:
        paths.init(storage)
        from app.core.hull_facts import hull_facts
        from app.core.scene_recipe import compose_scene
        from _hull_fixtures import stepped_house, without_outline

        loc = stepped_house()
        scene = compose_scene(loc, plan_width_m=10)
        assert scene['doorways'][0]['outside'] is True
        f = hull_facts(loc)
        assert f['ok'] and f['error'] == ''
        assert f['location_id'] == 'hull-demo'
        assert f['storey_m'] == 3.0
        assert f['boundary_center'] == [5.0, 4.0]
        assert [l['level'] for l in f['levels']] == [0, 1]
        assert [l['floor_y'] for l in f['levels']] == [0.0, 3.08]
        assert [l['top_y'] for l in f['levels']] == [3.08, 5.93]
        assert f['eaves_y'] == 5.93
        expected = {
            (0, 0): [dict(s0=4.4, s1=5.6, y0=0.9, y1=2.1, kind='window')],
            (0, 2): [dict(s0=2.5, s1=3.5, y0=0.0, y1=2.1, kind='door')],
            (1, 1): [dict(s0=3.4, s1=4.6, y0=4.0, y1=5.2, kind='window')],
            (1, 3): [dict(s0=3.5, s1=4.5, y0=3.08, y1=5.5, kind='passage')],
        }
        for lv in f['levels']:
            assert lv['outline'] == (loc['map3d']['outline'] if lv['level'] == 0
                                     else loc['map3d']['level_outlines']['1'])
            assert lv['ccw'] is True
            for i, edge in enumerate(lv['edges']):
                assert edge['index'] == i
                assert edge['a'] == lv['outline'][i]
                assert edge['b'] == lv['outline'][(i+1) % 4]
                assert edge['length'] == ([10,8,10,8] if lv['level']==0 else [6,8,6,8])[i]
                assert edge['normal'] == [[0,-1],[1,0],[0,1],[-1,0]][i]
                assert edge['openings'] == expected.get((lv['level'], i), []), edge
        packed = json.dumps(dict(storey_m=f['storey_m'], levels=f['levels']),
                            sort_keys=True, separators=(',', ':'))
        assert f['fingerprint'] == hashlib.sha256(packed.encode()).hexdigest()[:16]
        moved = copy.deepcopy(loc)
        moved['rooms'][0]['layout']['props'] = [{'id': 'demo', 'x': 2, 'y': 2}]
        assert hull_facts(moved)['fingerprint'] == f['fingerprint']
        moved['rooms'][0]['layout']['props'][0]['x'] = 3
        moved['map3d']['wall_kind'] = 'demo-wall'
        assert hull_facts(moved)['fingerprint'] == f['fingerprint']
        shifted = copy.deepcopy(loc)
        shifted['rooms'][0]['layout']['openings'][0]['at'] = 0.6
        f3 = hull_facts(shifted)
        assert f3['fingerprint'] != f['fingerprint']
        assert f3['levels'][0]['edges'][0]['openings'][0]['s0'] == 5.4
        assert hull_facts(without_outline())['error'] == 'no_outline'
        assert hull_facts({})['error'] == 'no_outline'
        assert hull_facts(loc) == f
        print('PASS: hull footprints, contour openings, floor datums, fingerprint, no_outline')


if __name__ == '__main__':
    main()
