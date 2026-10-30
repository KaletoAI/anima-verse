"""Opt-in balconies, without Blender.

Usage: ./.venv/bin/python scripts/smoke_hull_balconies.py

Hand derivations: a 6 x 9 house has front z=4.5 and x=-3..3.
Outer offset .2 extends the raster to 6.4 m; floor(6.4/2)=3
fields give centres at x=-32/15,0,32/15 with 1 m windows;
each slab is 1+.4=1.4 m wide. Two selected storeys give six slabs.
Their s intervals are (1/6,47/30),(2.3,3.7),(133/30,35/6).
Wall thickness .16 plus the existing .04 inner offset gives outer .20.
The .08 m floor plate puts their tops at 3.08 and 6.08, bottoms at
2.93 and 5.93. Outer wall offset .2 plus .9 depth puts fronts at 5.6.
Continuous spans .3..5.7 have length 5.4. A party boundary at x=3
removes that corner's .3 setback, giving x=-2.7..3 (length 5.7).
Rail tops are floor+1; solid thickness is .12, iron top rail .05.
Iron front post spacing: (1.4-.05)/ceil(1.35)=.675 m or
(5.4-.05)/ceil(5.35)=5.35/6 m, both at most 1 m.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
_STORAGE = tempfile.TemporaryDirectory(prefix='hull-balconies-')
paths.init(_STORAGE.name)
from app.core import hull_styles as hs
from app.core.hull_facts import hull_facts
from app.core.hull_geometry import prepare_facts, build_hull
from app.core.house_props import validate_house_spec, synthetic_locations, unit_description


def near(a, b):
    assert abs(a-b)<1e-4, (a,b)


def main():
    styles=hs.load_styles(); style=deepcopy(styles['steinhaus'])
    style['wall_thickness_m']=.16  # .04 inner offset + .16 = .20 outer
    style['blind_windows'].update(bay_m=[2,2],width_m=[1,1],height_m=[1.4,1.4])
    spec=validate_house_spec({'storeys':3,'balconies':{'storeys':[1,2]}},(6,9))
    facts=hull_facts(synthetic_locations(spec,(6,9))[0])
    desc=hs.validate_description(unit_description(spec,0),styles)
    assert desc['overrides'].get('balconies')==spec['balconies'], 'balcony override discarded'
    from app.core.hull_balconies import build_balconies, balcony_bays
    for layout in ('per_window','continuous'):
        desc['overrides']['balconies']['layout']=layout
        prepared=prepare_facts(facts,style,desc,frozenset())
        for level in prepared['levels'][1:]:
            front=level['edges'][2]
            assert len(front['openings'])==3
            assert all(h['y0']==level['floor_y'] for h in front['openings'])
            assert all(h['y0']>level['floor_y'] for h in level['edges'][0]['openings'])
            bays=balcony_bays(level,front,desc['overrides']['balconies'],0,6)
            expected = [(.3,5.7)] if layout=='continuous' else [(1/6,47/30),(2.3,3.7),(133/30,35/6)]
            assert len(bays)==len(expected)
            for actual, want in zip(bays,expected):
                near(actual[0],want[0]); near(actual[1],want[1])
        for railing,material in (('iron','window_frame'),('solid','trim'),('glass','glass')):
            desc['overrides']['balconies']['railing']=railing
            for tier in ('full','low'):
                parts=build_balconies(prepared,style,desc,tier=tier,uv_sizes={})
                slabs=[p for p in parts if max(v[1] for v in p['vertices'])-min(v[1] for v in p['vertices'])<.151 and p['material']=='trim']
                assert len(slabs)==(6 if layout=='per_window' else 2)
                for p in slabs:
                    ys=[v[1] for v in p['vertices']]; xs=[v[0] for v in p['vertices']]
                    assert round(max(ys),2) in (3.08,6.08)
                    near(max(ys)-min(ys),.15); near(max(v[2] for v in p['vertices']),5.6)
                    near(max(xs)-min(xs),1.4 if layout=='per_window' else 5.4)
                assert material in {p['material'] for p in parts}
                rails=[p for p in parts if p not in slabs]
                if railing=='solid':
                    for p in rails:
                        near(max(v[1] for v in p['vertices'])-min(v[1] for v in p['vertices']),1)
                        widths=[max(v[k] for v in p['vertices'])-min(v[k] for v in p['vertices']) for k in (0,2)]
                        near(min(widths),.12)
                else:
                    tops=[p for p in rails if .049 < max(v[1] for v in p['vertices'])-min(v[1] for v in p['vertices']) < .051]
                    assert len(tops)==3*len(slabs)
                    if railing=='iron':
                        posts=[p for p in rails
                               if abs(max(v[1] for v in p['vertices'])-min(v[1] for v in p['vertices'])-.95)<1e-4
                               and min(v[2] for v in p['vertices'])>5.54
                               and min(v[1] for v in p['vertices'])<4]
                        xs=sorted({round(min(v[0] for v in p['vertices']),4) for p in posts})
                        assert len(xs)==(9 if layout=='per_window' else 7)
                        assert all(b-a<=1.0001 for a,b in zip(xs,xs[1:]))
                    if railing=='glass':
                        assert len([p for p in rails if p['material']=='glass'])==3*len(slabs)
                assert all(p['tag']=='balcony' and p['protrudes'] for p in parts)
                near(max(v[1] for p in parts for v in p['vertices']),7.08)
                hull=build_hull(facts,style,desc,tier=tier)
                assert any(p['tag']=='balcony' for p in hull['parts'])
        print('PASS',layout,'all railings and tiers')
    desc['overrides']['party_edges']=[1]
    prepared=prepare_facts(facts,style,desc,frozenset())
    parts=build_balconies(prepared,style,desc,tier='full',uv_sizes=None)
    near(max(v[0] for p in parts for v in p['vertices']),3)
    near(min(v[0] for p in parts for v in p['vertices']),-2.7)
    legacy=deepcopy(desc); legacy['overrides'].pop('balconies')
    assert not build_balconies(prepared,style,legacy,tier='full',uv_sizes=None)
    assert 'balconies' not in hs.validate_description({},styles)['overrides']
    for raw in ({'edge':'back'},None,[],{}):
        assert 'balconies' not in hs.validate_description({'overrides':{'balconies':raw}},styles)['overrides']
    clamped=hs.validate_description({'overrides':{'storeys_total':3,'balconies':{'storeys':[True,0,1,2,3,'1',2],'depth_m':9,'layout':'bad','railing':'bad'}}},styles)['overrides']['balconies']
    assert clamped==dict(edge='front',storeys=[1,2],depth_m=1.6,layout='per_window',railing='iron')
    assert not any(p['tag']=='balcony' for p in build_hull(facts,style,legacy,tier='full')['parts'])
    # The shared opening metadata must produce a real wall cut below the old sill.
    test=deepcopy(desc); test['overrides']['party_edges']=[]
    prepared=prepare_facts(facts,style,test,frozenset())
    for tier in ('full','low'):
        parts=build_hull(facts,style,test,tier=tier)['parts']
        for p in parts:
            if p['tag']!='wall':
                continue
            for face in p['faces']:
                vv=[p['vertices'][i] for i in face]
                if all(abs(v[2]-4.7)<1e-5 for v in vv):
                    assert not (min(v[0] for v in vv)<0<max(v[0] for v in vv)
                                and min(v[1] for v in vv)<3.3<max(v[1] for v in vv)), 'wall covers balcony door'
    from app.core.hull_balconies import front_edges
    location=deepcopy(prepared); location['location_id']='ordinary-location'
    assert front_edges(location,location['levels'][1])=={2}, 'street-edge fallback follows ground entrance'
    # Resolved facade modules must not paint over the new door-height openings.
    module_style=deepcopy(style); module_style['materials']['facade_module']='facade_module_modern'
    resolved=frozenset({'facade_module'})
    module_facts=prepare_facts(facts,module_style,test,resolved)
    assert all(len(lv['edges'][2]['openings'])==3 for lv in module_facts['levels'][1:])
    for tier in ('full','low'):
        parts=build_hull(facts,module_style,test,tier=tier,resolved=resolved)['parts']
        assert any(p['tag']=='balcony' for p in parts)
        assert not any(p['tag']=='facade_module' and all(v[2]>4.5 for v in p['vertices']) for p in parts)
        assert any(p['tag']=='facade_module' for p in parts), 'other edges retain their modules'
    print('PASS party clipping, opt-in, validation, door cuts and resolved modules')

if __name__=='__main__':
    main()
