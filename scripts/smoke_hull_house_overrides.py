#!/usr/bin/env python3
"""Opt-in house hull geometry and opt-in balconies, without Blender.

Usage: ./.venv/bin/python scripts/smoke_hull_house_overrides.py

Two sections on one throwaway storage; a failed assert ends its section only, the run exits non-zero and names
every failed section.

[O] HOUSE OVERRIDES.
Hand derivations: [1] 4/2=2 and 10/2=5; party edge 1 ends at x=2,
while edge 3 stays at -2-outer. [2] Width ridge endpoints have z=0;
automatic longer-axis ridge has x=0. [3] Party roof ends at 2; free end
is -2-outer-overhang (overhang is measured from the outer wall).
[4] Blind pane depths are outer-.10 recessed, outer+.02 otherwise;
recess casements span outer-.14..outer-.08, with four reveal faces.
[5] Metal bars have width .05, replacing stone frames for this build.
[6] Empty overrides retain only the existing ornament_density=.5 default.
Shutters=1 at density=1 gives min(1,1*1*2)=1; shutters=0 gives 0.
Three 3 m storeys have floors 0,3.08,6.08 (existing .08 m plate).

[B] BALCONIES (formerly smoke_hull_balconies).
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
import traceback
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
_STORAGE = tempfile.TemporaryDirectory(prefix='house-overrides-')
paths.init(_STORAGE.name)
from app.core import hull_styles as hs, hull_walls as hw, hull_roofs as hr
from app.core.hull_geometry import prepare_facts, build_hull
from app.core.hull_facts import hull_facts
from app.core.house_props import validate_house_spec, synthetic_locations, unit_description

FAILED = []


def near(a, b):
    assert abs(a-b)<1e-4, (a,b)


def section(name, fn):
    """Run one section; a failed assert or a crash is recorded and the next section still runs."""
    print(f"\n=== {name}")
    try:
        fn()
    except Exception:  # noqa: BLE001 — a failed assert ends its section only
        traceback.print_exc()
        print(f"FAIL {name}")
        FAILED.append(name)


def section_overrides():
    styles = hs.load_styles()
    style = styles['steinhaus']
    original = deepcopy(style)
    spec = validate_house_spec({'storeys':3}, (4,10))
    facts = hull_facts(synthetic_locations(spec,(4,10))[0])
    raw = unit_description(spec,0)
    raw['overrides'].update(party_edges=[1], ridge='width', roof_form='gable', shutters=0)
    desc = hs.validate_description(raw,styles)
    prepared = prepare_facts(facts,style,desc,frozenset())
    assert [l['floor_y'] for l in prepared['levels']] == [0,3.08,6.08]
    assert all(not l['edges'][1]['openings'] for l in prepared['levels']), 'party openings'
    for tier in ('full','low'):
        parts = hw.build_walls(prepared,style,desc,tier=tier)
        assert max(v[0] for p in parts for v in p['vertices']) <= 2+1e-6
        assert any(abs(v[0]-(-2-hw.wall_offsets(style,0)[1]))<1e-6
                   for p in parts if p['tag']=='wall' for v in p['vertices'])
    # A second party plane passes through vertices introduced by the first.
    from app.core.hull_mesh import PartBuilder
    probe=PartBuilder('wall','wall'); probe.box([2,1,5],[2,2,2])
    probe.poly([[1,0,0],[2,0,1],[3,0,0]])
    clipped=hw.clip_party_parts([probe.part()], [prepared['levels'][0]['edges'][1],
                                               prepared['levels'][0]['edges'][2]])
    for part in clipped:
        for face in part['faces']:
            vv=[part['vertices'][i] for i in face]
            assert all(a!=b for a,b in zip(vv,vv[1:]+vv[:1])), 'duplicate clipping corner'
    print('[1] PASS party shell and openings')
    roofs,info = hr.build_roofs(prepared,style,desc,tier='full')
    assert all(abs(p[2])<1e-6 for p in info['wings'][0]['ridge'])
    automatic = deepcopy(desc); automatic['overrides'].pop('ridge')
    _,auto = hr.build_roofs(prepared,style,automatic,tier='full')
    assert all(abs(p[0])<1e-6 for p in auto['wings'][0]['ridge'])
    print('[2] PASS forced and automatic ridge')
    vertices = [v for p in roofs if p['tag']=='roof' for v in p['vertices']]
    assert abs(max(v[0] for v in vertices)-2)<1e-6
    expected = -2-hw.wall_offsets(style,2)[1]-info['overhang_m']
    assert abs(min(v[0] for v in vertices)-expected)<1e-4
    assert not any(p['tag']=='gable' and all(abs(v[0]-2)<1e-6 for v in p['vertices']) for p in roofs)
    for form in ('gable','hip','shed','flat'):
        for axis in ('width','depth'):
            test=deepcopy(desc); test['overrides'].update(roof_form=form,ridge=axis)
            for tier in ('full','low'):
                rp,ri=hr.build_roofs(prepared,style,test,tier=tier)
                assert max(v[0] for p in rp for v in p['vertices'])<=2+1e-4, (form,axis,tier)
    print('[3] PASS roof seam limits, all roof forms and both axes')
    for recessed,delta in ((True,-.10),(False,.02)):
        test = deepcopy(desc)
        test['overrides']['blind_recess'] = recessed
        for tier in ('full','low'):
            parts = hw.build_walls(prepared,style,test,tier=tier)
            panes = [p for p in parts if p['material']=='blind']
            assert panes
            for pane in panes:
                matches=[]
                for level in prepared['levels']:
                    for edge in level['edges']:
                        _,n=hw._axes(edge)
                        depth=hw.wall_offsets(style,level['level'])[1]+delta
                        if all(level['floor_y']<=v[1]<=level['top_y'] and
                               abs((v[0]-edge['a'][0])*n[0]+(v[2]-edge['a'][1])*n[1]-depth)<1e-4
                               for v in pane['vertices']):
                            matches.append(edge)
                assert matches, (recessed,pane)
            if recessed:
                assert len([p for p in parts if p['tag']=='reveal']) >= 4*len(panes)
    # The back-edge bay is away from corners: no wall face may cover its centre.
    back=prepared['levels'][0]['edges'][0]
    hole=next(h for h in back['openings'] if h.get('blind'))
    mid_s=(hole['s0']+hole['s1'])/2; mid_y=(hole['y0']+hole['y1'])/2
    for tier in ('full','low'):
        parts=hw.build_walls(prepared,style,desc,tier=tier)
        outer=hw.wall_offsets(style,0)[1]
        for part in parts:
            if part['tag']!='wall': continue
            for face in part['faces']:
                vv=[part['vertices'][i] for i in face]
                if all(abs(v[2]-(-5-outer))<1e-6 for v in vv):
                    assert not (min(v[0] for v in vv)<-2+mid_s<max(v[0] for v in vv)
                                and min(v[1] for v in vv)<mid_y<max(v[1] for v in vv))
        if tier=='full':
            casements=[p for p in parts if p['tag']=='casement' and
                       all(v[2]<-5 and v[1]<3 for v in p['vertices'])]
            assert casements
            depths=[-v[2]-5 for p in casements for v in p['vertices']]
            assert abs(min(depths)-(outer-.14))<1e-4
            assert abs(max(depths)-(outer-.08))<1e-4
    print('[4] PASS recessed and legacy depths, real holes, casements, reveals')
    metal = deepcopy(desc); metal['overrides']['frames']='metal'
    actual_bars = hw.casement_bars
    with patch.object(hw,'casement_bars',wraps=actual_bars) as bars:
        parts=hw.build_walls(prepared,style,metal,tier='full')
        assert bars.call_count and all(c.args[-1]=='metal' for c in bars.call_args_list)
        assert all(actual_bars(*c.args)[2]==.05 for c in bars.call_args_list)
    shutters=deepcopy(desc); shutters['overrides'].update(shutters=1,ornament_density=1)
    assert any(p['tag']=='shutter' for p in hw.build_walls(prepared,style,shutters,tier='full'))
    shutters['overrides']['shutters']=0
    assert not any(p['tag']=='shutter' for p in hw.build_walls(prepared,style,shutters,tier='full'))
    assert style==original
    print('[5] PASS per-build metal frames')
    assert hs.validate_description({'overrides':{}},styles)==dict(style='steinhaus',seed=0,overrides={'ornament_density':.5})
    invalid=hs.validate_description({'overrides':{'party_edges':[True,-1,1,1,'2'], 'ridge':'bad','frames':'bad','shutters':2}},styles)['overrides']
    assert invalid['party_edges']==[1] and 'ridge' not in invalid
    assert invalid['frames']=='timber' and invalid['shutters']==1
    complete=build_hull(facts,style,desc,tier='full')['parts']
    assert complete
    assert not any(p['tag']=='quoin' and any(v[0]>=2-1e-6 for v in p['vertices']) for p in complete)
    logs=build_hull(facts,styles['holzhuette'],desc,tier='full')['parts']
    assert any(p['tag']=='log' and all(v[2]>5 for v in p['vertices']) for p in logs), 'free facade logs survive'

    print('[6] PASS legacy schema, validation, complete hull')
    print('PASS hull house overrides')


def section_balconies():
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


def main():
    section("[O] house overrides", section_overrides)
    section("[B] balconies", section_balconies)
    if FAILED:
        print(f"\nFAILED {len(FAILED)} section(s): " + ", ".join(FAILED))
        sys.exit(1)


if __name__=='__main__':
    main()
