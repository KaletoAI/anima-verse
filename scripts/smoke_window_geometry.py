"""Hand-derived window geometry checks (metres).

A 1.5 x 1.2 hole starts at (.08,.07): size is 1.5+.16=1.66 by
1.2+.13=1.33. Wall half-depth .035 plus inner .18 gives -.215;
outer .10 gives +.135, mirrored for outside=-1. Casing half-depth
(.07+.04)/2=.055. Casement width .06 (.05 metal), depth +/-.03.
Timber vertical centre .08+.75=.83, width .04, transom
.07+.62*1.2=.814. Width 2 gives mullions [1], shifted to 1.08;
width .6 gives none. Metal bars are .05 wide and have no transom.
Each ring has four boxes; two sills, two bars
and one glass give 13 closed boxes. No bars gives 11. Each box has
8 vertices and 6 outward quads, every edge twice. Glass depth .01.
At minimum valid .151 square, size is .311 by .281; .7 wide and .9
high meet the inclusive bar/transom thresholds (.35 and .558).
Low tier has 11 boxes, metal with a mullion has 12. UV size 2 halves the projected metre coordinates.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.window_geometry import build_window
from app.core.window_styles import load_window_styles, validate_window_style
from app.core.hull_facades import casement_bars
from smoke_door_geometry import boxes, close, mesh_check


def main():
    styles = load_window_styles()
    assert list(styles) == ['metal', 'plain', 'stone', 'timber']
    for path in (ROOT/'shared/window_styles').glob('*.json'):
        raw = json.loads(path.read_text())
        assert raw == validate_window_style(raw) == styles[path.stem]
    bad = validate_window_style({'frame': [], 'bars': 'yes', 'glass_tint': 'invalid', 'frame_material': '#ABC'})
    assert (bad['frame'], bad['bars'], bad['glass_tint'], bad['frame_material']) == ('plain', False, '#3a4a55', '#aabbcc')
    assert casement_bars(0, 1.5, 0, 1.2, 'timber') == ([.75], .744, .04)
    assert casement_bars(0, 2., 0, 1., 'metal') == ([1.], None, .05)
    assert casement_bars(0, .6, 0, .8, 'stone') == ([], None, .04)
    for sign in (1, -1):
        model = build_window(styles['timber'], 1.5, 1.2, .07, outside=sign)
        close(model['size_m'], [1.66, 1.33])
        close(model['bounds']['min'], [0, 0, -.215 if sign == 1 else -.135])
        close(model['bounds']['max'], [1.66, 1.33, .135 if sign == 1 else .215])
        solids = list(boxes(model))
        assert len(solids) == 13
        close(solids[0][0], [.02,.01,-.055])
        close(solids[0][1], [.08,1.33,.055])
        close(solids[4][0], [.08,.07,-.03])
        close(solids[4][1], [.14,1.27,.03])
        sills = list(boxes(model, 'frame', 'trim'))
        close(sills[0][0], [0,0,.035 if sign == 1 else -.135])
        close(sills[0][1], [1.66,.07,.135 if sign == 1 else -.035])
        close(sills[1][0], [0,0,-.215 if sign == 1 else .035])
        close(sills[1][1], [1.66,.07,-.035 if sign == 1 else .215])
        bars = [(a,b) for a,b in boxes(model) if math.isclose(a[2], -.02) and math.isclose(b[2], .02)]
        close([(bars[0][0][0]+bars[0][1][0])/2, bars[0][1][0]-bars[0][0][0]], [.83,.04])
        close([(bars[1][0][1]+bars[1][1][1])/2], [.814])
    for style in styles.values():
        for tier in ('full', 'low'):
            model = build_window(style, 2., 1.2, .07, tier=tier)
            mesh_check(model)
            assert len(list(boxes(model))) == (11 if tier == 'low' or not style['bars'] else 12 if style['frame'] == 'metal' else 13)
            assert model == build_window(style, 2., 1.2, .07, tier=tier)
            glass = list(boxes(model, 'glass', 'glass'))
            assert len(glass) == 1
            close([glass[0][0][2],glass[0][1][2]], [-.005,.005])
            assert {p['node'] for p in model['parts']} == {'frame','glass'}
            assert {p['material'] for p in model['parts']} == {'window_frame','glass','trim'}
    for width, style_id, enabled, count in ((2.,'timber',True,2),(.6,'timber',True,1),(2.,'metal',True,1),(1.5,'metal',True,0),(1.5,'timber',False,0),(1.5,'plain',True,0)):
        model = build_window(styles[style_id], width, 1.2, .07, bars=enabled)
        bars = [(a,b) for a,b in boxes(model) if a[2] == -.02 and b[2] == .02]
        assert len(bars) == count
        if width == 2 and enabled and style_id != 'plain':
            close([(bars[0][0][0]+bars[0][1][0])/2], [1.08])
            close([bars[0][1][0]-bars[0][0][0]], [.05 if style_id == 'metal' else .04])
    narrow = build_window(styles['timber'],.151,.151,.07)
    mesh_check(narrow)
    close(narrow['size_m'], [.311,.281])
    centres, transom, bar_width = casement_bars(0,.7,0,.9,'timber')
    assert centres == [.35] and bar_width == .04
    close([transom], [.558])
    base = build_window(styles['timber'],1.5,1.2,.07)
    scaled = build_window(styles['timber'],1.5,1.2,.07,uv_sizes={m:2 for m in ('window_frame','glass','trim')})
    for p,q in zip(base['parts'],scaled['parts']):
        for uv,small in zip(p['uvs'],q['uvs']):
            for pair,half in zip(uv,small):
                close(half,[v/2 for v in pair])
    for dimensions in ((.15,1,.07),(1,.15,.07),(1,1,0),(float('nan'),1,.07),(1,float('inf'),.07),(1,1,-1)):
        try:
            build_window({},*dimensions)
        except ValueError:
            pass
        else:
            raise AssertionError(dimensions)
    for kwargs in ({'tier':'bad'},{'outside':0},{'uv_sizes':{'glass':0}}):
        try:
            build_window({},1,1,.07,**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(kwargs)
    print('PASS styles, shared bars, mirrored bounds, bar placement, closed boxes, glass, UVs and invalid arguments')
    print('PASS smoke_window_geometry')


if __name__ == '__main__':
    main()
