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
Gap ladder: floor(0)=0; floor(L)=3.1*L+0.08 for L>0; wall=3.1-0.15=2.95.
Thus pairs are (0,3.18), (3.18,6.28), (6.28,9.38), (9.38,12.33).
Ten levels extend top(3) to 4*3.1+.08=12.48; appended pairs are
(12.48,15.58), (15.58,18.68), (18.68,21.78), (21.78,24.88),
(24.88,27.98), (27.98,30.93), last top=9*3.1+.08+2.95.
Forty levels: 39*3.1+.08+2.95=123.93. Stepped extension: floor(2)=6.08,
floor(3)=9.08; eaves=9.08+2.85=11.93. Four levels minus two occupied
leaves two fillers. Rooms only on 2 leave fillers 0,1; rooms on -1,1
leave filler 0 and occupied 1. No rooms uses composer's occupied fallback 0.
Cutouts: widths 10,6,8 by depth 8 are three distinct contours over 0..3;
occupied-only 0,3 sees only widths 10,8, hence two contours.
Baseline commands (worktree denied by read-only .git):
  mkdir -p /tmp/hull-task1-baseline
  git show 8b5f1124:app/core/hull_facts.py > /tmp/hull-task1-baseline/hull_facts.py
  git show 8b5f1124:app/core/scene_recipe.py > /tmp/hull-task1-baseline/scene_recipe.py
  git show 8b5f1124:scripts/_hull_fixtures.py > /tmp/hull-task1-baseline/_hull_fixtures.py
  STORAGE_DIR=$(mktemp -d) ./.venv/bin/python - <<'PYBASE'
  import importlib.util, sys, os
  from app.core import paths
  paths.init(os.environ['STORAGE_DIR'])
  import app.core
  spec = importlib.util.spec_from_file_location(
      'app.core.scene_recipe', '/tmp/hull-task1-baseline/scene_recipe.py')
  sr = importlib.util.module_from_spec(spec)
  sys.modules[spec.name] = sr
  spec.loader.exec_module(sr)
  app.core.scene_recipe = sr
  sys.path.insert(0, '/tmp/hull-task1-baseline')
  from hull_facts import hull_facts
  from _hull_fixtures import stepped_house
  print(hull_facts(stepped_house())['fingerprint'])
  PYBASE
Remove the two-space docstring indentation when running the shell block.
Its SHA256 geometry prefix is df35445505db09c7 (verified independently).

"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def check_storeys(hull_facts, gap_house, stepped_house, compose_scene):
    """Two finite coordinates yield a fresh float pair; malformed lifts yield no housing.

    A lift requires exactly two coordinates: lengths 1/3, mappings and strings
    fail shape; None, NaN and infinities fail finite conversion. No lift means
    zero housing parts, independently of the four rectangular roof edges.
    """
    from app.core.hull_geometry import build_hull
    from app.core.hull_styles import validate_style
    import json
    style = validate_style(json.loads((Path(__file__).resolve().parents[1]/'shared/building_styles/modern.json').read_text()), 'modern')
    for lift in ([5], 'x', [5,4,3], {'x':5,'z':4}, [None,4],
                 [float('nan'),4], [5,float('inf')], [float('-inf'),4]):
        malformed = gap_house()
        malformed['map3d']['elevator'] = lift
        clean = hull_facts(malformed)
        assert clean['elevator'] is None, lift
        result = build_hull(clean,style,dict(seed=7,overrides={}),tier='full')
        assert not any(p['tag']=='housing' for p in result['parts'])
    valid = gap_house()
    valid['map3d']['elevator'] = ['5',4]
    clean = hull_facts(valid)
    assert clean['elevator'] == [5.,4.] and all(type(v) is float for v in clean['elevator'])
    assert clean['elevator'] is not valid['map3d']['elevator']
    from app.core.hull_facts import with_storeys
    from app.core.scene_recipe import _hull_cutouts
    loc = gap_house()
    f = hull_facts(loc)
    original = copy.deepcopy(f)
    assert [l['level'] for l in f['levels']] == [0, 1, 2, 3]
    assert [l['filler'] for l in f['levels']] == [False, True, True, False]
    assert [(l['floor_y'], l['top_y']) for l in f['levels']] == [
        (0, 3.18), (3.18, 6.28), (6.28, 9.38), (9.38, 12.33)]
    assert f['eaves_y'] == 12.33 and f['elevator'] == [5, 4]
    assert all(e['openings'] == [] for l in f['levels'][1:3] for e in l['edges'])
    full = copy.deepcopy(loc)
    for level in (1, 2):
        room = copy.deepcopy(loc['rooms'][0])
        room['id'] = f'filled-{level}'
        room['layout']['level'] = level
        full['rooms'].append(room)
    assert hull_facts(full)['fingerprint'] != f['fingerprint']
    for occupied, want_levels, want_filler in (([], [0], [False]),
            ([2], [0, 1, 2], [True, True, False]),
            ([-1, 1], [0, 1], [True, False])):
        case = gap_house()
        case['rooms'] = []
        for level in occupied:
            room = copy.deepcopy(loc['rooms'][0])
            room['id'] = str(level)
            room['layout']['level'] = level
            case['rooms'].append(room)
        facts = hull_facts(case)
        assert [l['level'] for l in facts['levels']] == want_levels
        assert [l['filler'] for l in facts['levels']] == want_filler
    a, b = [[0,0],[6,0],[6,8],[0,8]], [[0,0],[8,0],[8,8],[0,8]]
    loc['map3d']['level_outlines'] = {'1': a, '3': b}
    contours = [loc['map3d']['outline'], a, b]
    assert _hull_cutouts(loc['map3d'], range(0, 4)) == contours
    assert _hull_cutouts(loc['map3d'], [0, 3]) == [contours[0], b]
    scene = compose_scene(loc, plan_width_m=10, building_meta={'plan_hull': True})
    building = next(m for m in scene['models'] if m['role'] == 'building')
    assert building['cutouts'] == contours
    shaped = hull_facts(loc)
    assert shaped['levels'][1]['outline'] == a
    extended = with_storeys(f, 10)
    assert f == original and extended['fingerprint'] == f['fingerprint']
    assert [l['level'] for l in extended['levels']] == list(range(10))
    assert extended['levels'][3] == {**f['levels'][3], 'top_y': 12.48}
    assert [(l['floor_y'], l['top_y']) for l in extended['levels'][4:]] == [
        (12.48,15.58), (15.58,18.68), (18.68,21.78),
        (21.78,24.88), (24.88,27.98), (27.98,30.93)]
    assert extended['eaves_y'] == 30.93
    for l in extended['levels'][4:]:
        assert l['filler'] and l['outline'] == f['levels'][3]['outline']
        assert all(e['openings'] == [] for e in l['edges'])
    shaped_extension = with_storeys(shaped, 10)
    assert all(l['outline'] == b for l in shaped_extension['levels'][4:])
    unchanged = with_storeys(f, 2)
    assert unchanged == f and unchanged is not f
    assert with_storeys(f, 40)['eaves_y'] == 123.93
    step = hull_facts(stepped_house())
    up = with_storeys(step, 4)
    assert step['levels'][1]['top_y'] == 5.93
    assert up['levels'][1]['top_y'] == 6.08 and up['eaves_y'] == 11.93
    assert all(l['outline'] == step['levels'][1]['outline'] and l['filler']
               for l in up['levels'][2:])
    extended['levels'][4]['outline'][0][0] = 999
    extended['levels'][4]['edges'][0]['a'][0] = 999
    extended['elevator'][0] = 999
    assert f == original
    assert extended['levels'][5]['outline'] == f['levels'][3]['outline']


def main():
    with tempfile.TemporaryDirectory(prefix="hull-facts-smoke-") as storage:
        paths.init(storage)
        from app.core.hull_facts import hull_facts
        from app.core.scene_recipe import compose_scene
        from _hull_fixtures import stepped_house, without_outline, gap_house

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
        packed = json.dumps(dict(storey_m=f['storey_m'], levels=[{k: v for k, v in l.items() if k != 'filler'}
                                    for l in f['levels']]),
                            sort_keys=True, separators=(',', ':'))
        assert f['fingerprint'] == hashlib.sha256(packed.encode()).hexdigest()[:16]
        assert f['fingerprint'] == 'df35445505db09c7'
        assert f['elevator'] is None
        check_storeys(hull_facts, gap_house, stepped_house, compose_scene)
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
