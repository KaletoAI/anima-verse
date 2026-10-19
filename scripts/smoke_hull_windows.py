"""Hand-derived §3.1/3.2 window checks; run with ./.venv/bin/python."""
from copy import deepcopy
import math
import hashlib
import json
import tempfile
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from _hull_fixtures import rect_facts, no_degenerate_faces, waldkante_house, stepped_house, gap_house
from app.core import paths, hull_facades, hull_roofs
_STORAGE = tempfile.TemporaryDirectory(prefix="hull-windows-import-")
paths.init(_STORAGE.name)
from app.core.hull_facts import hull_facts
from app.core.hull_geometry import prepare_facts, fit_budget, build_hull, TRI_BUDGET
from app.core.hull_facades import mullions
from app.core.hull_styles import validate_style
from app.core.hull_walls import build_walls, wall_offsets

# Pre-task wall parts at f2fce906, captured before implementation (seed 17, density 1).
BASELINE = {
    "modern:full": "7035fecd2fdee4411a6873d843f8286c4b372a37dd951d927b528a4f46c43cbf",
    "modern:low": "e64e4683cc3e272ee64c75011545e88a54c5b849fc38e197eb45aa51d5767212",
    "fachwerk:low": "38d1ac402a22fb70315c81f85b29c215e8f86729b4deaf3356d0adf3fbaa168e",
    "steinhaus:low": "0df90dbf6422b343df0167e4a17f1bac78b4fbf51267ba05697ae229a4685daa",
    "holzhuette:low": "8590d0c23ffad349c89c25ebb9ebf049ded60821efb6a565b9c52f028f136161",
    "burg:low": "b00ad2fe8b6dd470dbf8ba36e3f5b02bb6b101c0d6e40c1feb0561bc17e9897a"
}


def style(name):
    return validate_style(json.loads((root/'shared/building_styles'/f'{name}.json').read_text()),name)


def build(name='fachwerk', *, facts=None, density=1, tier='full'):
    config = style(name)
    config['shutters'] = 0
    return build_walls(rect_facts() if facts is None else facts,config,
                       dict(seed=17,overrides=dict(ornament_density=density)),tier=tier)


def box(part):
    # Edge 0 tangent +x, outward -z: compare (s,y,outward depth).
    points = [(x,y,-z) for x,y,z in part['vertices']]
    return tuple(round(f(p[k] for p in points),4) for k in range(3) for f in (min,max))


def expected_ring(d0,d1):
    return {(6,6.06,.9,2.1,d0,d1),(7.14,7.2,.9,2.1,d0,d1),
            (6.06,7.14,.9,.96,d0,d1),(6.06,7.14,2.04,2.1,d0,d1)}


def check_glass():
    outer = wall_offsets(style('fachwerk'),0)[1]
    assert {round(-v[2],4) for p in build() if p['tag']=='glass' for v in p['vertices']} == {round(outer-.12,4)}


def check_details():
    outer = wall_offsets(style('fachwerk'),0)[1]
    d0,d1 = round(outer-.14,4),round(outer-.08,4)
    parts = build()
    casements = [p for p in parts if p['tag']=='casement']
    assert len(casements)==6 and all(p['material']=='window_frame' for p in casements)
    assert {box(p) for p in casements} == expected_ring(d0,d1) | {
        (6.58,6.62,.96,2.04,d0,d1),(6.06,7.14,1.624,1.664,d0,d1)}
    sills = [p for p in parts if p['tag']=='sill']
    assert len(sills)==1 and sills[0]['material']=='trim'
    assert box(sills[0]) == (5.92,7.28,.83,.9,round(outer,4),round(outer+.1,4))
    assert no_degenerate_faces(parts)


def check_density():
    for filler in (False,True):
        facts = rect_facts()
        facts['levels'][0]['filler'] = filler
        if filler:
            facts['levels'][0]['edges'][0]['openings'][1]['blind'] = True
        parts = build(facts=facts,density=0)
        assert sum(p['tag']=='casement' for p in parts)==4
        assert sum(p['tag']=='sill' for p in parts)==1


def check_blind():
    facts = rect_facts()
    facts['levels'][0]['filler'] = True
    facts['levels'][0]['edges'][0]['openings'][1]['blind'] = True
    outer = wall_offsets(style('fachwerk'),0)[1]
    parts = build(facts=facts,density=0)
    assert {box(p) for p in parts if p['tag']=='casement'} == expected_ring(round(outer+.02,4),round(outer+.06,4))


def check_surrounds():
    for name in ('fachwerk','holzhuette','steinhaus','burg'):
        parts = build(name)
        frames = [box(p) for p in parts if p['tag']=='frame']
        assert not any(a < 7.2 and b > 6 and c < .9 and d <= .9 for a,b,c,d,_,_ in frames)
        assert sum(p['tag']=='sill' for p in parts)==1
        assert all(min(v[0] for v in p['vertices'])>5 for p in parts if p['tag'] in ('sill','casement'))
        assert any(a < 3.2 and b > 2 for a,b,_,_,_,_ in frames)


def check_wide_and_thresholds():
    for width,height,vertical,horizontal in ((2,1.2,1,1),(3.6,1.2,2,1),(.7,.9,1,1),(.69,.89,0,0)):
        facts = rect_facts()
        h = facts['levels'][0]['edges'][0]['openings'][1]
        h.update(s1=6+width,y1=.9+height)
        parts = [p for p in build(facts=facts) if p['tag']=='casement']
        assert len(parts)==4+vertical+horizontal
        centres = mullions(6,6+width) if width>1.8 else [6+width/2]
        for centre in centres if vertical else []:
            assert any(abs((box(p)[0]+box(p)[1])/2-centre)<1e-4 and abs(box(p)[1]-box(p)[0]-.04)<1e-4 for p in parts)


def check_identity():
    for name in ('modern','fachwerk','steinhaus','holzhuette','burg'):
        for tier in ('full','low') if name=='modern' else ('low',):
            parts = build_walls(rect_facts(),style(name),dict(seed=17,overrides=dict(ornament_density=1)),tier=tier)
            digest = hashlib.sha256(json.dumps(parts,sort_keys=True,allow_nan=False).encode()).hexdigest()
            assert digest == BASELINE[name+':'+tier], (name,tier,digest)



def prepared_windows(location=None, config=None, **overrides):
    facts = hull_facts(waldkante_house() if location is None else location)
    desc = dict(seed=17,overrides=dict(blind_windows=True,**overrides))
    return prepare_facts(facts,style('fachwerk') if config is None else config,desc,frozenset())


def check_real_storey_raster():
    """Seed 17 bay=2.4634947653. Upper outer=.59, spans [-.59,L+.59].
    L=10.4: 4 candidates, centres .8575,3.7525,6.6475,9.5425;
    L=9.1: 4 candidates, centres .695,3.265,5.835,8.405.
    Width=1.2: first/last end clearance .8475/.685, so no end drops.
    Edge 2 real centres 3.12,7.28: middle candidates overlap (drop 2),
    outside candidates have gap 1.0625/1.0625 (keep). Counts [4,4,2,4].
    Ground outer=.34: 4,3,4,3 raster candidates; door centre 5.2
    drops middle two on edge 2, giving [4,3,2,3].
    """
    facts = prepared_windows()
    upper = facts['levels'][1]
    counts = []
    for edge in upper['edges']:
        blinds = [h for h in edge['openings'] if h.get('blind')]
        counts.append(len(blinds))
        for h in blinds:
            assert math.isclose(h['s1']-h['s0'],1.2)
            assert math.isclose(h['y0']-upper['floor_y'],.92)
            assert math.isclose(h['y1']-h['y0'],1.2)
            assert h['s0'] >= -.59+.6-1e-8 and h['s1'] <= edge['length']+.59-.6+1e-8
            for real in edge['openings']:
                if not real.get('blind'):
                    assert max(real['s0']-h['s1'],h['s0']-real['s1']) >= .5-1e-8
    assert counts == [4,4,2,4], counts
    ground = facts['levels'][0]
    assert [sum(h.get('blind',False) for h in e['openings']) for e in ground['edges']] == [4,3,2,3]
    dims = hull_facades.blind_dims(style('fachwerk'),17)
    for edge in ground['edges']:
        for h in edge['openings']:
            if h.get('blind'):
                assert math.isclose(h['s1']-h['s0'],dims['width'])
                assert math.isclose(h['y1']-h['y0'],dims['height'])
                assert h['y0'] >= style('fachwerk')['plinth_height_m']+.1


def check_real_storey_flag_and_medians():
    facts = hull_facts(gap_house())
    original = deepcopy(facts)
    off = prepare_facts(facts,style('fachwerk'),dict(seed=17),frozenset())
    on = prepared_windows(gap_house())
    for a,b in zip(off['levels'],on['levels']):
        if a.get('filler'):
            assert a == b
        else:
            assert not any(h.get('blind') for e in a['edges'] for h in e['openings'])
    assert facts == original
    assert on == prepared_windows(gap_house())
    loc = waldkante_house()
    holes = loc['rooms'][1]['layout']['openings']
    holes[0].update(width_m=1.0,sill_m=.78,height_m=1.0)
    holes[1].update(width_m=1.4,sill_m=1.02,height_m=1.4)
    upper = prepared_windows(loc)['levels'][1]
    blinds = [h for e in upper['edges'] for h in e['openings'] if h.get('blind')]
    assert blinds
    for h in blinds:
        assert math.isclose(h['s1']-h['s0'],1.2)
        assert math.isclose(h['y0']-upper['floor_y'],.92)
        assert math.isclose(h['y1']-h['y0'],1.2)
    for edge in upper['edges']:
        for h in edge['openings']:
            if h.get('blind'):
                assert all(max(r['s0']-h['s1'],h['s0']-r['s1']) >= .5-1e-8
                           for r in edge['openings'] if not r.get('blind'))


def check_real_storey_roof_and_short_wall():
    facts = prepared_windows(stepped_house())
    _, info = hull_roofs.build_roofs(facts,style('fachwerk'),dict(seed=17),tier='full')
    upper = facts['levels'][1]
    # Lean-to touches edge 1; all three candidates are below its high side.
    assert not any(h.get('blind') for h in upper['edges'][1]['openings'])
    assert any(h.get('blind') for e in upper['edges'] for h in e['openings'])
    for edge in upper['edges']:
        for h in edge['openings']:
            if not h.get('blind'):
                continue
            centre = (h['s0']+h['s1'])/2
            x,z = [edge['a'][k]+(edge['b'][k]-edge['a'][k])*centre/edge['length'] for k in range(2)]
            for wing in info['wings']:
                if wing['level'] < upper['level']:
                    top = hull_roofs.roof_top_y(wing,x,z,style('fachwerk'))
                    assert top is None or h['y0'] >= top+.1-1e-8
    loc = waldkante_house()
    loc['map3d']['outline'] = [[0,0],[1.5,0],[1.5,9.1],[0,9.1]]
    facts = prepared_windows(loc,config=style('modern'))
    assert all(not h.get('blind') for l in facts['levels'] for e in (l['edges'][0],l['edges'][2]) for h in e['openings'])



def check_real_storey_filters():
    """A 6 m span/bay 2 has slots [.4,1.6],[2.4,3.6],[4.4,5.6].
    End slots drop at .6 clearance. A centre door with overlapping height
    drops the middle; a door ending at the sill does not. Roof equality
    at bottom-.1 is allowed; anything higher drops it. Ground plinth .81
    rejects sill .9, whereas .8 allows it. No medians from blind windows.
    """
    level = dict(level=0,floor_y=0,top_y=3,edges=[])
    edge = dict(openings=[])
    level['edges'] = [edge]
    dims = dict(width=1.2,sill=.9,height=1.2,plinth=.8)
    def slots():
        return hull_facades.wall_blind_windows(level,edge,dims,2,0,6,lambda s: [None,.8])
    assert [(h['s0'],h['s1']) for h in slots()] == [(2.4,3.6)]
    edge['openings'] = [dict(kind='door',s0=3.9,s1=4.5,y0=0,y1=2)]
    assert slots() == []  # .3 m horizontal gap
    edge['openings'][0]['y1'] = .9
    assert len(slots()) == 1
    assert hull_facades.wall_blind_windows(level,edge,dims,2,0,6,lambda s: [.8001]) == []
    dims['plinth'] = .81
    assert slots() == []
    edge['openings'] = [dict(kind='window',blind=True,s0=1,s1=2,y0=1,y1=2)]
    assert hull_facades.storey_window_dims(level) is None
    assert hull_facades.wall_blind_windows(level,edge,dims,2,0,1.5,lambda s: []) == []

def check_real_storey_budget():
    loc = gap_house()
    loc['map3d']['outline'] = [[0,0],[30,0],[30,20],[0,20]]
    loc['rooms'] = [loc['rooms'][0]]
    loc['rooms'][0]['layout'].update(w=30,d=20,openings=[])
    facts = hull_facts(loc)
    desc = dict(seed=7,overrides=dict(storeys_total=40,blind_windows=True,ornament_density=.5))
    original = deepcopy(desc)
    prepared = prepare_facts(facts,style('modern'),desc,frozenset())
    assert sum(h.get('blind',False) for e in prepared['levels'][0]['edges'] for h in e['openings']) == 30
    for resolved in (frozenset(),frozenset({'facade_module'})):
        fitted = fit_budget(facts,style('modern'),desc,resolved=resolved)
        for tier in ('full','low'):
            result = build_hull(facts,style('modern'),fitted,tier=tier,resolved=resolved)
            assert result['tris'] <= TRI_BUDGET[tier]
            print(f"PASS: blind budget {tier}={result['tris']} resolved={sorted(resolved)}")
    assert desc == original

def main():
    failed = []
    for check in (check_glass,check_details,check_density,check_blind,check_surrounds,check_wide_and_thresholds,check_identity,
                  check_real_storey_raster,check_real_storey_flag_and_medians,
                  check_real_storey_roof_and_short_wall,check_real_storey_filters,check_real_storey_budget):
        try:
            check()
        except AssertionError as error:
            failed.append(check.__name__)
            print(f'FAIL: {check.__name__}: {error}')
        else:
            print(f'PASS: {check.__name__}')
    assert not failed, failed


if __name__ == '__main__':
    main()
