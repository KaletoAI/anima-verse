"""Hand-derived §3.1 window checks; run with ./.venv/bin/python."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from _hull_fixtures import rect_facts, no_degenerate_faces
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


def main():
    failed = []
    for check in (check_glass,check_details,check_density,check_blind,check_surrounds,check_wide_and_thresholds,check_identity):
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
