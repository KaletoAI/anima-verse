"""Door geometry checks derived from spec 3.2/3.3 and Task-1 rulings.

Panel .9 x 2.1 x .07: casing adds 2*.07 => 1.04; head 2.1+.07
=> 2.17; depth .07+.04=.11 => z +/-.055. Clearances give leaf
x .07+.005=.075 to .07+.9-.005=.965, y .02+.005=.025 to
2.1-.005=2.095, z +/-.045/2=.0225. Four raised panels per face
add .012, within the .015 detail envelope. Handle centre .965-.06=.905,
y 1.0. Double 1.8: (1.8-.010-.005)/2=.8925; A ends .9675;
B starts at its own (0,0), placer lifts .025, translated x .9725
leaves a .005 gap. Cellar .6x1.8 has 2 panels (width >=.55 but
not >=.7 and height >=1.9); .5 has none. Wall .6 gives depth .64.
Each box has 8 shared vertices, 6 outward quads, each edge twice.
UVs project the two in-plane metre axes; a size 2 halves every UV.
Low tier has 4 frame boxes and 1 solid leaf, with no details.
These rows catch lost clearances, inward/open faces, omitted details,
wrong outside signs, oversized cellar ornament and UV scaling errors.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.door_styles import load_door_styles, validate_door_style
from app.core.door_geometry import build_door, leaves_for


def close(actual, expected):
    assert len(actual) == len(expected)
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(actual, expected)), (actual, expected)


def boxes(model, node=None, material=None):
    for part in model['parts']:
        if node and part['node'] != node or material and part['material'] != material:
            continue
        for i in range(0, len(part['vertices']), 8):
            vs = part['vertices'][i:i+8]
            yield [min(p[k] for p in vs) for k in range(3)], [max(p[k] for p in vs) for k in range(3)]


def mesh_check(model):
    for part in model['parts']:
        assert set(part) == {'node', 'material', 'vertices', 'faces', 'uvs', 'colors'}
        assert len(part['faces'])*8 == len(part['vertices'])*6
        edges = Counter()
        for face, uv, colors in zip(part['faces'], part['uvs'], part['colors']):
            assert len(face) == len(uv) == len(colors) == 4
            assert colors == [1.0]*4
            for a,b in zip(face, face[1:]+face[:1]):
                edges[tuple(sorted((a,b)))] += 1
            pts = [part['vertices'][i] for i in face]
            a,b,c = pts[:3]
            u,v = [b[k]-a[k] for k in range(3)], [c[k]-b[k] for k in range(3)]
            n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
            base = min(face)//8*8
            centre = [sum(p[k] for p in part['vertices'][base:base+8])/8 for k in range(3)]
            assert sum(n[k]*(a[k]-centre[k]) for k in range(3)) > 0
        assert set(edges.values()) == {2}


def main():
    styles = load_door_styles()
    assert list(styles) == ['castle','glass','glazed','interior','panel','plank']
    for path in (ROOT/'shared/door_styles').glob('*.json'):
        raw = json.loads(path.read_text())
        assert validate_door_style(raw) == raw == styles[path.stem]
    bad = validate_door_style({'leaf': [], 'hardware': 'bad', 'panels': 3,
                               'glass_rows': 99, 'glass_cols': 0, 'leaf_material':'#ABC'})
    assert (bad['leaf'], bad['hardware'], bad['panels']) == ('panel','lever',4)
    assert (bad['glass_rows'],bad['glass_cols'],bad['leaf_material']) == (4,1,'#aabbcc')
    print('PASS shipped styles and validation')
    panel = build_door(styles['panel'], .9, 2.1, .07)
    close(panel['bounds']['min'], [0,0,-.055]); close(panel['bounds']['max'],[1.04,2.17,.055])
    close(panel['leaf_bbox']['min'], [.075,.025,-.0225]); close(panel['leaf_bbox']['max'],[.965,2.095,.0225])
    close(panel['size_m'], [1.04,2.17])
    raised = [(a,b) for a,b in boxes(panel,'leaf','door_leaf') if a[2] >= .0225-1e-9 or b[2] <= -.0225+1e-9]
    assert len(raised) == 8
    for a,b in boxes(panel,'leaf','hardware'):
        close([(a[k]+b[k])/2 for k in (0,1)], [.905,1.0])
    print('PASS panel bounds, eight raised panels and hardware centres')
    assert leaves_for(styles['castle'], 1.8) == 2
    assert leaves_for(styles['castle'], 1.49) == 1
    a = build_door(styles['castle'],1.8,2.1,.07,piece='double_a')
    b = build_door(styles['castle'],1.8,2.1,.07,piece='double_b')
    close([a['leaf_bbox']['min'][0],a['leaf_bbox']['max'][0]],[.075,.9675])
    close([b['bounds']['min'][0],b['bounds']['max'][0]],[0,.8925])
    assert b['bounds']['min'][1] == 0
    assert a['leaf_bbox']['max'][0] < b['leaf_bbox']['min'][0]+.9725
    print('PASS double leaf widths, own origin and clearance')
    for sign in (-1,1):
        p = build_door(styles['plank'],.9,2.1,.07,outside=sign)
        straps = [(lo,hi) for lo,hi in boxes(p,'leaf','hardware') if hi[0]-lo[0] > .2]
        assert len(straps) == 2
        assert all(lo[2]>0 if sign==1 else hi[2]<0 for lo,hi in straps)
    for width,count in ((.6,4),(.5,0)):
        p = build_door(styles['panel'],width,1.8,.07)
        assert len(list(boxes(p,'leaf','door_leaf'))) == 1+count
        lo,hi = p['leaf_bbox']['min'],p['leaf_bbox']['max']
        for a,b in boxes(p,'leaf'):
            assert all(a[k]>=lo[k]-.015-1e-9 and b[k]<=hi[k]+.015+1e-9 for k in range(3))
    thick = build_door(styles['panel'],.9,2.1,.6)
    close([thick['bounds']['max'][2]-thick['bounds']['min'][2]],[.64])
    low = build_door(styles['panel'],.9,2.1,.07,tier='low')
    assert len(list(boxes(low,'frame'))) == 4 and len(list(boxes(low,'leaf'))) == 1
    print('PASS outside hinges, cellar panels, detail envelope, thick frame and low tier')
    for style in styles.values():
        for piece in ('single','double_a','double_b'):
            p = build_door(style,1.8,2.1,.07,piece=piece)
            mesh_check(p)
            assert p == build_door(style,1.8,2.1,.07,piece=piece)
    scaled = build_door(styles['panel'],.9,2.1,.07,uv_sizes={k:2 for k in ('door_leaf','door_frame','hardware')})
    for p,q in zip(panel['parts'],scaled['parts']):
        for face,uv,scaled_uv in zip(p['faces'],p['uvs'],q['uvs']):
            points = [p['vertices'][i] for i in face]
            axes = [k for k in range(3) if len({v[k] for v in points})>1]
            for point,pair,small in zip(points,uv,scaled_uv):
                close(pair,[point[k] for k in axes]); close(small,[v/2 for v in pair])
    for name in ('glazed','glass'):
        p = build_door(styles[name],.9,2.1,.07)
        assert len(list(boxes(p,'leaf','glass'))) == (6 if name=='glazed' else 1)
        assert all(math.isclose(b[2]-a[2],.01) for a,b in boxes(p,'leaf','glass'))
    print('PASS closed outward boxes, determinism, metre UVs and glass panes')
    for kwargs in ({'piece':'bad'}, {'tier':'bad'}, {'outside':0},
                   {'uv_sizes':{'door_leaf':0}}):
        try:
            build_door(styles['panel'],.9,2.1,.07,**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(('accepted invalid arguments',kwargs))
    for dimensions in ((0,2.1,.07),(.9,float('nan'),.07),(.9,2.1,-1)):
        try:
            build_door(styles['panel'],*dimensions)
        except ValueError:
            pass
        else:
            raise AssertionError(('accepted invalid dimensions',dimensions))
    print('PASS invalid geometry arguments rejected')
    print('PASS smoke_door_geometry')


if __name__ == '__main__':
    main()
