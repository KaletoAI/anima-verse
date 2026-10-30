"""Pure house specification and synthetic location checks.

Usage: ./.venv/bin/python scripts/smoke_house_props.py

Hand derivations:
[1] Half of 6 x 9 is (3, 4.5): the CCW ring is (-3,-4.5),
    (3,-4.5), (3,4.5), (-3,4.5). Edge 2 faces front (+z).
[2] Three storeys use real level 0 and filler levels 1,2. Nominal floors
    are 0,3,6; the existing pipeline adds its 0.08 m plate above ground,
    so actual floor_y values are 0,3.08,6.08 (brief discrepancy).
[3] The shipped door fallback is panel. Edge 2 runs from x=3 to -3 at z=4.5: 3 - 6*0.5 = 0.
    A 1 m door spans edge distances 2.5..3.5 and rises 2.1 m.
[4] 16/4=4: unit intervals are [-8,-4],[-4,0],[0,4],[4,8].
    Edge 1 is +x, edge 3 is -x: party edges are [1],[3,1],[3,1],[3].
[5] floor(12/2.5)=floor(4.8)=4, hence requested 8 units becomes 4.
[6] A zero (or negative) side has no footprint and must raise ValueError.
[7] Every raw unit description forces blind windows, recesses and total
    storeys; rows alone force the ridge along width. Seed 7+i gives 7..10.
[8] Two storeys at 3.5 m on 6 x 9 keep facts storey_m=3.5;
    ground floor_y=0 and upper floor_y=3.5+0.08=3.58 m.
Additional validation bounds come directly from the brief: 1..12 floors,
2.6..4.5 m height, door fraction .1...9, balcony depth .5..1.6 m;
only upper floors below the total, three colour keys and known ids survive.
"""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory(prefix='house-props-smoke-') as storage:
        paths.init(storage)
        from app.core.house_props import (HOUSE_DEFAULTS, validate_house_spec,
                                          synthetic_locations, unit_description)
        from app.core.hull_facts import hull_facts, with_storeys
        from app.core.scene_recipe import compose_scene

        assert HOUSE_DEFAULTS == dict(style='steinhaus', storeys=2, storey_m=3.0,
            units=1, unit_overrides=[], wall='', door=dict(style='', at=.5),
            balconies=None, overrides={})
        spec = validate_house_spec({'storeys': 3}, (6, 9))
        loc, = synthetic_locations(spec, (6, 9))
        assert loc['id'] == 'house-unit-0'
        assert loc['map3d']['outline'] == [[-3,-4.5],[3,-4.5],[3,4.5],[-3,4.5]]
        assert 'wall_kind' not in loc['map3d']
        assert loc['rooms'][0]['id'] == '__floor__0'
        facts = with_storeys(hull_facts(loc), 3)
        assert facts['ok']
        assert [l['level'] for l in facts['levels']] == [0,1,2]
        assert [l['filler'] for l in facts['levels']] == [False,True,True]
        assert [l['floor_y'] for l in facts['levels']] == [0,3.08,6.08]
        edge = facts['levels'][0]['edges'][2]
        assert edge['normal'] == [0,1]
        assert edge['openings'] == [dict(s0=2.5,s1=3.5,y0=0.,y1=2.1,kind='door',door_style='panel')]
        scene = compose_scene(loc, plan_width_m=6, read_only=True)
        assert not any(f['kind'] == 'hull_opening_without_corridor' for f in scene['problems'])
        door, = [d for d in scene['doorways'] if d.get('hull')]
        assert door['at_world'] == [0,4.5] and door['rooms'] == ['__floor__0']
        row = validate_house_spec({'units':4, 'seed':7}, (16,10))
        locations = synthetic_locations(row, (16,10))
        for i, (lo, hi) in enumerate([(-8,-4),(-4,0),(0,4),(4,8)]):
            assert locations[i]['map3d']['outline'] == [[lo,-5],[hi,-5],[hi,5],[lo,5]]
            desc = unit_description(row, i)
            assert set(desc['overrides']['party_edges']) == [{1},{1,3},{1,3},{3}][i]
            assert desc['seed'] == 7+i and desc['overrides']['ridge'] == 'width'
        assert validate_house_spec({'units':8}, (12,9))['units'] == 4
        for footprint in ((0,9), (6,0), (-1,9)):
            try:
                validate_house_spec({}, footprint)
            except ValueError as error:
                assert str(error) == 'footprint'
            else:
                raise AssertionError('invalid footprint accepted')
        for case in (spec,row):
            overrides = unit_description(case,0)['overrides']
            assert overrides['blind_windows'] is True and overrides['blind_recess'] is True
            assert overrides['storeys_total'] == case['storeys']
        assert 'ridge' not in unit_description(spec,0)['overrides']
        clean = validate_house_spec(dict(storeys=99,storey_m=0,units=0,
            style='missing', wall=' BAD/KIND ', door={'style':'missing','at':9},
            unit_overrides=[{'tint':'#abc','door_color':'invalid','extra':'#fff'}],
            balconies={'edge':'front','storeys':[0,1,11,12,'2',True],
                       'layout':'continuous','depth_m':9,'railing':'glass'},
            overrides={'tint':'#123','unknown':True}), (6,9))
        assert (clean['storeys'],clean['storey_m'],clean['units']) == (12,2.6,1)
        assert clean['style'] == 'steinhaus' and clean['wall'] == ''
        assert clean['door'] == {'style':'','at':.9}
        assert clean['unit_overrides'] == [{'tint':'#aabbcc'}]
        assert clean['balconies'] == dict(edge='front',storeys=[1,11],layout='continuous',depth_m=1.6,railing='glass')
        assert clean['overrides']['tint'] == '#112233' and 'unknown' not in clean['overrides']
        assert validate_house_spec({'units':3},(9,9))['unit_overrides'] == [{},{},{}]
        styled = validate_house_spec({'wall':'dark_stone','door':{'style':'panel','at':.25}},(6,9))
        styled_loc, = synthetic_locations(styled,(6,9))
        assert styled_loc['map3d']['wall_kind'] == 'dark_stone'
        assert hull_facts(styled_loc)['levels'][0]['edges'][2]['openings'][0]['door_style'] == 'panel'
        assert validate_house_spec(None,(6,9))['storeys'] == 2
        assert validate_house_spec({'storeys':0},(6,9))['storeys'] == 1
        assert validate_house_spec({'storey_m':99},(6,9))['storey_m'] == 4.5
        assert validate_house_spec({'door':{'at':0}},(6,9))['door']['at'] == .1
        assert validate_house_spec({'balconies':{'edge':'back'}},(6,9))['balconies'] is None
        raw_desc = unit_description(clean,0)
        assert raw_desc['overrides']['balconies'] == clean['balconies']
        assert raw_desc['overrides']['tint'] == '#aabbcc'
        raw_desc['overrides']['balconies']['storeys'].append(99)
        assert clean['balconies']['storeys'] == [1,11]
        assert 'balconies' not in clean['overrides']
        taller = validate_house_spec({'storeys':2, 'storey_m':3.5}, (6,9))
        taller_loc, = synthetic_locations(taller, (6,9))
        taller_facts = with_storeys(hull_facts(taller_loc), 2)
        assert taller_facts['storey_m'] == 3.5
        assert [lv['floor_y'] for lv in taller_facts['levels']] == [0,3.58]
        print('smoke_house_props: PASS')


if __name__ == '__main__':
    main()
