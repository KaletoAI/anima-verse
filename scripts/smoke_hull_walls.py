"""Wall hull checks. Usage: ./.venv/bin/python scripts/smoke_hull_walls.py

Facade hand derivation: 10/2.5=4 fields, centres 1.25,3.75,6.25,8.75;
2/2.4<1 gives none; 5/2.5=2 fields caps width at 2.5-.3=2.2.
Gap storey pitch is 3.1, with .08 upper floor datum: floors 0,3.18,
6.28,9.38. Last wall head 9.38+(3.1-.15)=12.33; extension changes
level 3 top to 4*3.1+.08=12.48. Ground ceiling is 3.18.
For span [-.54,10.54], bay 2 gives 5 fields of 2.216, capped width
1.916; the first left is -.54+.15=-.39 and last right is 10.39.
A sill of 1.5 and requested height 3 must stop at top-.25.
Each filler rectangle has 4 edges: 1 cornice block per edge gives
4 blocks, each 6 quads / 12 triangles, hence 48 cornice triangles.
Blind panes end at top-.25, below cornice bottom top-.12.
Each filler rectangle has 4 shell quads, zero reveals/interiors, panes
at stone outer .54+.005=.545. Top margin is .25. Density zero and
low tier have no filler frames/shutters. Ground sink remains -.14. Each timber blind window has 4 frame blocks
and 2 shutters at density 1 (.5*1*2=1); density 0 removes both.

Hand expectations: inner offset .07/2+.005=.04; stone outer .04+.50=.54.
The fixture has four apertures (two windows, one door, one passage), hence
16 reveals, two glass parts, one leaf. A unit cube has 6 quads = 12 triangles.
Stone frames extend .05 each side: width 1.2+.10=1.3; height .15,
depth .10. Cornice is .12 high and .08 deep. Full glass/door recesses
are .10/.08: front glass z=-.44 and rear door z=8.46; low is flush.
Timber shutters .5 * density 1 * 2 = 1, hence two leaves per window (4).
Ground sink is .14, so ground facade height is 3.22.
The rounded-normal stress rectangle is 100x8, rotated 30 degrees;
its outer perimeter is 2*(100+8)+8*.54=220.32. Its facade area is
220.32*(3+.14)-1.44 for the single window.
A 2x2 square offset by .5 has bounds -.5..2.5 on both axes.
"""
import json
import math
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _hull_fixtures import (stepped_house, opening_edge_cases, count, total_openings,
    windows, doors, polygon_case_facts, no_face_overlaps_openings, no_degenerate_faces, outer_face_distance)


def main():
    check_facades()
    from app.core.hull_styles import validate_style
    from app.core.hull_mesh import PartBuilder, offset_ring, rng, bounds, tri_count
    from app.core.hull_walls import build_walls, wall_offsets
    styles = {key: validate_style(json.loads(Path(f'shared/building_styles/{key}.json').read_text()), key)
              for key in ('steinhaus', 'fachwerk')}
    from app.core.hull_facts import hull_facts
    facts = hull_facts(stepped_house())
    desc = dict(seed=17, overrides=dict(ornament_density=1))
    for tier in ('full', 'low'):
        parts = build_walls(facts, styles['steinhaus'], desc, tier=tier)
        assert no_face_overlaps_openings(parts, facts)
        assert no_degenerate_faces(parts)
        assert abs(outer_face_distance(parts, facts)-.54) < 1e-4
        assert count(parts, tag='glass') == windows(facts) == 2
        assert count(parts, tag='door') == doors(facts) == 1
        assert parts == build_walls(facts, styles['steinhaus'], desc, tier=tier)
        if tier == 'full':
            assert count(parts, tag='reveal') == 4*total_openings(facts) == 16
        else:
            assert not any(p['tag'] in ('reveal','frame','shutter','interior','cornice') for p in parts)
    for case in opening_edge_cases(facts):
        for tier in ('full', 'low'):
            parts = build_walls(case, styles['fachwerk'], desc, tier=tier)
            assert no_degenerate_faces(parts)
            assert no_face_overlaps_openings(parts, case)
            if tier == 'full':
                assert count(parts,tag='reveal') == 4*total_openings(case)
    b = PartBuilder('wall', 'wall')
    b.box([0,0,0], [1,1,1])
    assert tri_count([b.part()]) == 12
    assert bounds([b.part()]) == dict(min=[-.5]*3, max=[.5]*3)
    for face in b.part()['faces']:
        from _hull_fixtures import face_normal
        pts = [b.part()['vertices'][i] for i in face]
        assert sum(n*sum(p[k] for p in pts) for k,n in enumerate(face_normal(pts))) > 0
    ring = offset_ring([[0,0],[2,0],[2,2],[0,2]], True, .5)
    assert ring == [[-.5,-.5],[2.5,-.5],[2.5,2.5],[-.5,2.5]]
    assert rng(17,'x').random() == rng(17,'x').random()
    assert wall_offsets(styles['fachwerk'], 1) == (.04, .59)
    for tier,window_z,door_z in (('full',-.44,8.46),('low',-.54,8.54)):
        parts = build_walls(facts,styles['steinhaus'],desc,tier=tier)
        glass = next(p for p in parts if p['tag'] == 'glass')
        door = next(p for p in parts if p['tag'] == 'door')
        assert all(abs(v[2]-window_z) < 1e-5 for v in glass['vertices'])
        assert all(abs(v[2]-door_z) < 1e-5 for v in door['vertices'])
    timber = build_walls(facts,styles['fachwerk'],desc,tier='full')
    assert count(timber,tag='shutter') == 4
    assert count(timber,tag='frame') == 4*total_openings(facts)
    bare = build_walls(facts,styles['fachwerk'],dict(seed=17,overrides={'ornament_density':0}),tier='full')
    assert count(bare,tag='shutter') == 0
    full = build_walls(facts,styles['steinhaus'],desc,tier='full')
    # Stone lintel is .10 longer in total than the 1.2 m aperture.
    assert any(bounds([p]) == {'min':[4.35,2.1,-.64], 'max':[5.65,2.25,-.54]}
               for p in full if p['tag'] == 'frame')
    assert any(bounds([p]) == {'min':[-.54,2.96,-.62], 'max':[4.4,3.08,-.54]}
               for p in full if p['tag'] == 'cornice')
    # Full edge-0 area: (10+2*.54)*(3.08+.14) - 1.2*1.2.
    low = build_walls(facts, styles['steinhaus'], desc, tier='low')
    area = 0
    for part in low:
        if part['tag'] not in ('wall','plinth'):
            continue
        for face in part['faces']:
            pts = [part['vertices'][i] for i in face]
            if all(abs(p[2]+.54) < 1e-5 for p in pts) and max(p[1] for p in pts) <= 3.08:
                area += math.sqrt(sum(v*v for v in face_normal(pts)))/2
    assert abs(area-34.2376) < 1e-5, area
    tiled = build_walls(facts, styles['steinhaus'], desc, tier='low', uv_sizes={'wall':4})
    wall = next(p for p in tiled if p['material'] == 'wall')
    for face,uv in zip(wall['faces'],wall['uvs']):
        pts = [wall['vertices'][i] for i in face]
        for i in range(len(pts)):
            assert abs(math.dist(pts[i-1],pts[i])/4 - math.dist(uv[i-1],uv[i])) < 1e-6
    for outline in ([[0,0],[4,0],[.01,.01]], [[0,0],[4,0],[4,1],[1,1],[1,4],[0,4]]):
        for ccw in (True,False):
            source = outline if ccw else outline[::-1]
            ring = offset_ring(source,ccw,.5)
            assert all(math.isfinite(v) for p in ring for v in p)
            assert all(min(math.dist(p,q) for q in source) <= 1.5001 for p in ring)
    # A sharp triangular corner must have a vertical wall on its bevel.
    acute = polygon_case_facts([[0,0],[4,0],[.01,.01]])
    shell = build_walls(acute,styles['steinhaus'],desc,tier='low')
    ring = offset_ring(acute['levels'][0]['outline'],True,.54)
    for a,b in zip(ring,ring[1:]+ring[:1]):
        assert any(all(any(math.dist([v[0],v[2]],q) < 1e-4 for v in part['vertices'])
                       for q in (a,b)) for part in shell if part['tag'] in ('wall','plinth')), (a,b)
    assert no_degenerate_faces(build_walls(acute,styles['fachwerk'],desc,tier='full'))
    for outline in ([[0,0],[4,0],[4,1],[1,1],[1,4],[0,4]],
                    [[0,0],[3,0],[4,2],[2,4],[-1,2]]):
        rotated = [[x*math.cos(.5236)-z*math.sin(.5236),x*math.sin(.5236)+z*math.cos(.5236)] for x,z in outline]
        for ring in (rotated,rotated[::-1]):
            for tier in ('full','low'):
                assert no_degenerate_faces(build_walls(polygon_case_facts(ring),styles['fachwerk'],desc,tier=tier))
    rounded = polygon_case_facts([[0,0],[86.6025,50],[82.6025,56.9282],[-4,6.9282]])
    for edge in rounded['levels'][0]['edges']:
        edge['normal'] = [round(v,4) for v in edge['normal']]
    assert no_degenerate_faces(build_walls(rounded,styles['steinhaus'],desc,tier='full'))
    rounded['levels'][0]['edges'][0]['openings'] = [dict(s0=49.4,s1=50.6,y0=.9,y1=2.1,kind='window')]
    rounded_parts = build_walls(rounded,styles['steinhaus'],desc,tier='low')
    area = sum(math.sqrt(sum(v*v for v in face_normal([p['vertices'][i] for i in face])))/2
               for p in rounded_parts if p['tag'] in ('wall','plinth') for face in p['faces'])
    # Rotated 100x8 rectangle: outer perimeter 216 + 8*.54 = 220.32.
    assert abs(area-(220.32*3.14-1.44)) < .01, area
    for shape in ('prism','cylinder','cone'):
        b = PartBuilder('wall','wall',uv_size_m=2)
        if shape == 'prism':
            b.prism([[0,0],[2,0],[2,1],[1,1],[1,2],[0,2]],0,1)
        else:
            b.cylinder(0,0,0,1,1,8,r_top=0 if shape == 'cone' else .5)
        assert no_degenerate_faces([b.part()])
        for face,uv,colors in zip(b.part()['faces'],b.part()['uvs'],b.part()['colors']):
            assert len(face) == len(uv) == len(colors)
            assert all(v == 1.0 for v in colors)
    print('PASS smoke_hull_walls: full/low holes, details, clipping, helpers, determinism')


def check_facades():
    from copy import deepcopy
    from _hull_fixtures import gap_house, face_normal
    from app.core.hull_facts import hull_facts
    from app.core.hull_geometry import prepare_facts
    from app.core.hull_facades import blind_raster, blind_dims
    from app.core.hull_walls import build_walls, wall_offsets, _span
    from app.core.hull_mesh import offset_ring, rng
    from app.core.hull_styles import validate_style
    assert blind_raster(0,10,2.5,1) == [(.75,1.75),(3.25,4.25),(5.75,6.75),(8.25,9.25)]
    assert blind_raster(0,2,2.4,1) == []
    assert all(abs(b-a-2.2) < 1e-9 for a,b in blind_raster(0,5,2.5,2.4))
    styles = {name: validate_style(json.loads(Path(f'shared/building_styles/{name}.json').read_text()),name)
              for name in ('steinhaus','fachwerk')}
    style = styles['steinhaus']
    random = rng(17,'blind_windows')
    dims = blind_dims(style,17)
    assert [dims[k] for k in ('bay','width','height')] == [random.uniform(*style['blind_windows'][k+'_m']) for k in ('bay','width','height')]
    raw = hull_facts(gap_house())
    original = deepcopy(raw)
    wide = deepcopy(style)
    wide['blind_windows'].update(bay_m=[2,2],width_m=[4,4],height_m=[3,3],sill_m=1.5)
    wide_facts = prepare_facts(raw,wide,dict(seed=17),frozenset())
    level = wide_facts['levels'][1]
    holes = level['edges'][0]['openings']
    assert abs(holes[0]['s0']+.39)<1e-9 and abs(holes[-1]['s1']-10.39)<1e-9
    assert all(h['y1']==level['top_y']-.25 for h in holes)
    wide_parts = build_walls(dict(wide_facts,levels=[level]),wide,dict(seed=17),tier='low')
    assert any(p['material']=='blind' and min(v[0] for v in p['vertices'])==-.39
               and all(v[2]==-.545 for v in p['vertices']) for p in wide_parts)
    assert wide_facts['levels'][3]['edges'][1]['openings'] == raw['levels'][3]['edges'][1]['openings']
    for total in (0,10):
        desc = dict(seed=17,overrides=dict(ornament_density=0,storeys_total=total))
        facts = prepare_facts(raw,style,desc,frozenset())
        assert raw == original
        parts = build_walls(facts,style,desc,tier='full')
        ceilings = [p for p in parts if p['tag']=='interior' and all(abs(v[1]-p['vertices'][0][1])<1e-6 for v in p['vertices'])
                    and face_normal(p['vertices'])[1]<0 and len(p['vertices'])==4
                    and max(v[0] for v in p['vertices'])-min(v[0] for v in p['vertices'])==10]
        assert sorted(p['vertices'][0][1] for p in ceilings) == [3.18,12.48 if total else 12.33]
        for level in facts['levels']:
            if not level.get('filler',False):
                continue
            inside = [p for p in parts if min(v[1] for v in p['vertices']) >= level['floor_y'] and max(v[1] for v in p['vertices']) <= level['top_y']]
            isolated = build_walls(dict(facts,levels=[level]),style,desc,tier='full')
            assert not any(p['tag'] in ('interior','reveal','frame','shutter') for p in isolated)
            cornices = [p for p in isolated if p['tag']=='cornice']
            assert len(cornices) == len(level['edges']) == 4, len(cornices)
            assert all(len(p['faces'])==6 for p in cornices)
            for edge in level['edges']:
                depths = [[(v[0]-edge['a'][0])*edge['normal'][0]+(v[2]-edge['a'][1])*edge['normal'][1]
                           for v in p['vertices']] for p in cornices]
                assert sum(abs(min(d)-.54)<1e-4 and abs(max(d)-.62)<1e-4 for d in depths) == 1
            shell = [p for p in inside if p['tag']=='wall']
            assert len(shell)==4 and all(len(p['faces'])==1 and len(p['vertices'])==4 for p in shell)
            panes = [p for p in inside if p['material']=='blind']
            assert panes and all(p['tag']=='glass' for p in panes)
            for edge in level['edges']:
                lo,hi = _span(offset_ring(level['outline'],level['ccw'],.54),edge,.54)
                assert all(lo<=h['s0']<h['s1']<=hi and h['y1']<=level['top_y']-.25 for h in edge['openings'])
                for p in panes:
                    if all(abs((v[0]-edge['a'][0])*edge['normal'][0]+(v[2]-edge['a'][1])*edge['normal'][1]-.545)<1e-4 for v in p['vertices']):
                        break
                else:
                    raise AssertionError('missing proud pane')
        assert any(p['material']=='glass' and min(v[1] for v in p['vertices'])>9 for p in parts)
        assert no_face_overlaps_openings(parts,facts)
    desc = dict(seed=17,overrides=dict(ornament_density=1))
    facts = prepare_facts(raw,style,desc,frozenset())
    low = build_walls(facts,style,desc,tier='low')
    assert any(p['material']=='blind' for p in low)
    assert not any(p['tag'] in ('frame','shutter') for p in low)
    timber_style = styles['fachwerk']
    timber_facts = prepare_facts(raw,timber_style,desc,frozenset())
    filler = timber_facts['levels'][1]
    panes = sum(len(e['openings']) for e in filler['edges'])
    timber = build_walls(dict(timber_facts,levels=[filler]),timber_style,desc,tier='full')
    assert count(timber,tag='frame') == 4*panes and count(timber,tag='shutter') == 2*panes
    bare = build_walls(dict(timber_facts,levels=[filler]),timber_style,dict(seed=17,overrides=dict(ornament_density=0)),tier='full')
    assert not any(p['tag'] in ('frame','shutter','interior','reveal') for p in bare)
    assert sum(p['material']=='blind' for p in bare) == panes
    loc = gap_house(); loc['rooms'] = [loc['rooms'][1]]; loc['rooms'][0]['layout']['level']=2
    facts = prepare_facts(hull_facts(loc),styles['fachwerk'],desc,frozenset())
    ground = facts['levels'][0]
    assert ground['filler'] and all(h['y0']>=styles['fachwerk']['plinth_height_m'] for e in ground['edges'] for h in e['openings'])
    parts = build_walls(facts,styles['fachwerk'],desc,tier='full')
    assert any(p['material']=='wall_ground' for p in parts)
    assert any(p['tag']=='plinth' for p in parts)
    assert min(v[1] for p in parts for v in p['vertices']) == -.14
    regular = prepare_facts(hull_facts(stepped_house()),style,desc,frozenset())
    assert not any(p['tag']=='interior' and all(v[1]==regular['levels'][0]['top_y'] for v in p['vertices'])
                   and face_normal(p['vertices'])[1]<0 and max(v[0] for v in p['vertices'])-min(v[0] for v in p['vertices'])==10
                   for p in build_walls(regular,style,desc,tier='full'))
    print('PASS: facade raster, solid shells, blind panes, ceilings, density, ground filler')

if __name__ == '__main__':
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='hull-walls-smoke-') as storage:
        paths.init(storage)
        main()
