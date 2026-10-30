"""Opt-in house hull geometry.

Usage: ./.venv/bin/python scripts/smoke_hull_house_overrides.py

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
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
_STORAGE = tempfile.TemporaryDirectory(prefix='house-overrides-')
paths.init(_STORAGE.name)
from app.core import hull_styles as hs, hull_walls as hw, hull_roofs as hr
from app.core.hull_geometry import prepare_facts, build_hull
from app.core.hull_facts import hull_facts
from app.core.house_props import validate_house_spec, synthetic_locations, unit_description


def main():
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

if __name__=='__main__':
    main()
