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
at stone outer .54+.02=.56. Top margin is .25. Density zero and
low tier have no filler frames/shutters. Ground sink remains -.14. Each timber blind window has 3 frame blocks
and 2 shutters at density 1 (.5*1*2=1); density 0 removes both.
Full-tier casement rings and sills remain at density 0.

Hand expectations: inner offset .07/2+.005=.04; stone outer .04+.50=.54.
The fixture has four apertures (two windows, one door, one passage), hence
16 reveals, two glass parts, one leaf. A unit cube has 6 quads = 12 triangles.
Stone frames extend .05 each side: width 1.2+.10=1.3; height .15,
depth .10. Cornice is .12 high and .08 deep. Full glass recess is .12:
front glass z=-.42; low is flush. Door frame depth .50+.04=.54 spans
rear depths 8+.04-.02=8.02 through 8+.54+.02=8.56 in both tiers.
Timber shutters .5 * density 1 * 2 = 1, hence two leaves per window (4).
Ground sink is .14, so ground facade height is 3.22.
The rounded-normal stress rectangle is 100x8, rotated 30 degrees;
its outer perimeter is 2*(100+8)+8*.54=220.32. Its facade area is
220.32*(3+.14)-1.44 for the single window.
A 2x2 square offset by .5 has bounds -.5..2.5 on both axes.
"""
# 3a: Blender doors
import json
import math
import sys
import tempfile
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from _hull_fixtures import (stepped_house, opening_edge_cases, count, total_openings,
    windows, doors, polygon_case_facts, no_face_overlaps_openings, no_degenerate_faces, outer_face_distance)


def main():
    check_modern()
    check_facades()
    from app.core.hull_styles import validate_style
    from app.core.hull_mesh import PartBuilder, offset_ring, rng, bounds, tri_count
    from app.core.hull_walls import build_walls, wall_offsets
    styles = {key: validate_style(json.loads((root / "shared/building_styles" / f"{key}.json").read_text()), key)
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
        assert sum(p['tag']=='door' and p.get('node')=='frame' for p in parts) == doors(facts) == 1
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
    for tier,window_z in (('full',-.42),('low',-.54)):
        parts = build_walls(facts,styles['steinhaus'],desc,tier=tier)
        glass = next(p for p in parts if p['tag'] == 'glass')
        door = next(p for p in parts if p['tag'] == 'door' and p['node']=='frame')
        assert all(abs(v[2]-window_z) < 1e-5 for v in glass['vertices'])
        assert bounds([door])['min'][2] == 8.02 and bounds([door])['max'][2] == 8.56
    timber = build_walls(facts,styles['fachwerk'],desc,tier='full')
    assert count(timber,tag='shutter') == 4
    assert count(timber,tag='frame') == 4*total_openings(facts)-windows(facts)
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
    styles = {name: validate_style(json.loads((root / "shared/building_styles" / f"{name}.json").read_text()),name)
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
               and all(v[2]==-.56 for v in p['vertices']) for p in wide_parts)
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
                    if all(abs((v[0]-edge['a'][0])*edge['normal'][0]+(v[2]-edge['a'][1])*edge['normal'][1]-.56)<1e-4 for v in p['vertices']):
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
    assert count(timber,tag='frame') == 3*panes and count(timber,tag='shutter') == 2*panes
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

def check_modern():
    """Hand derivations for Task 4.

    7/2=3.5 differs from 3.1 by .4, beating 7/1 and 7/3;
    2.3<.75*3.1=2.325, while 2.4 exceeds it. At span 4 and
    pitch 3, n=1 and 2 tie at error 1, so choose 1.
    Width 5 gives ceil(5/1.6)-1=3 centres at 5*i/4;
    width 1.8 has none. Modern outer=.07/2+.005+.3=.34.
    Five-metre window at s=2..7,y=.9..2.1: four .05 strips,
    one sill x=1.95..7.05,y=.85...9,depth .34...40, and three
    mullions x=3.25,4.5,5.75 +/- .025,depth .24...34.
    Door gets four strips and no sill/mullions. Blind mullions
    use depth .34+.02=.36 to .34+.03=.37; blind panes are at .36
    in both tiers. Module UVs cover n fields and v=0..1;
    filler ground starts v=.15/top, without stretching the image.
    A 1x7 rectangle has short outer spans 1+2*.34=1.68<2.325;
    its two long edges carry modules and two short edges carry wall.
    Upper floor is 3.08: band y=2.93..3.23,depth .34...39.
    A lower hole y=2.9..3.08 removes band area below 3.08;
    upper hole y=3.08..3.3 removes area above 3.08.
    Module fillers 1 and 2 each have four edges with no real holes:
    one unsplit band per edge gives 4 blocks at full tier.
    With 40 storeys there are 39*4=156 band blocks when no real
    hole reaches a boundary; blind apertures add no subdivisions.
    Stepped gable: shed footprint starts x=6+.04+.01=6.05;
    flush front/back bands retain x=-.34..6.05, y=2.93..3.23,
    z=-.39..-.34 and 8.34..8.39. Covered pieces must be absent.
    """
    from copy import deepcopy
    from _hull_fixtures import gap_house
    from app.core.hull_facades import module_bays, mullions
    from app.core.hull_facts import hull_facts
    from app.core.hull_geometry import prepare_facts, build_hull
    from app.core.hull_styles import validate_style
    from app.core.hull_walls import build_walls, _span
    from app.core.hull_mesh import bounds, offset_ring
    assert [module_bays(s,3.1) for s in (7,2.3,2.4)] == [2,0,1]
    assert module_bays(4,3)==1
    assert mullions(0,5)==[1.25,2.5,3.75]
    assert mullions(0,1.5)==mullions(0,1.8)==[]
    style=validate_style(json.loads((root/'shared/building_styles/modern.json').read_text()),'modern')
    desc=dict(seed=7,overrides=dict(ornament_density=1))
    resolved=frozenset({'facade_module'})
    raw=hull_facts(gap_house())
    for tier in ('full','low'):
        facts=prepare_facts(raw,style,desc,resolved)
        for level in facts['levels']:
            isolated=build_walls(dict(facts,levels=[level]),style,desc,tier=tier,resolved=resolved,
                                 uv_sizes={'facade_module':99})
            modules=[p for p in isolated if p['tag']=='facade_module']
            assert len(modules)==(4 if level['filler'] else 0)
            if not level['filler']:
                continue
            if tier == 'full' and level['level'] in (1,2):
                assert count(isolated,tag='band') == 4
            assert not any(e['openings'] for e in level['edges'])
            assert not any(p['material']=='blind' or p['tag']=='frame' for p in isolated)
            for edge,part in zip(level['edges'],modules):
                lo,hi=_span(offset_ring(level['outline'],level['ccw'],.34),edge,.34)
                assert part['material']=='facade_module' and len(part['faces'])==1
                assert sorted(part['uvs'][0])==sorted([[0,0],[module_bays(hi-lo,3.1),0],
                                                       [module_bays(hi-lo,3.1),1],[0,1]])
        fallback=prepare_facts(raw,style,desc,frozenset())
        assert any(p['material']=='blind' for p in build_walls(fallback,style,desc,tier=tier))
    ground_raw=deepcopy(raw)
    ground_raw['levels']=ground_raw['levels'][1:2]
    ground=ground_raw['levels'][0]
    ground.update(level=0,floor_y=0,filler=True)
    ground=prepare_facts(ground_raw,style,desc,resolved)
    modules=[p for p in build_walls(ground,style,desc,tier='low',resolved=resolved) if p['tag']=='facade_module']
    assert len(modules)==4
    for p in modules:
        assert min(v[1] for v in p['vertices'])==.15
        assert math.isclose(min(uv[1] for uv in p['uvs'][0]),.15/ground['levels'][0]['top_y'])
    acute=polygon_case_facts([[0,0],[4,0],[.01,.01]])
    acute['storey_m']=3.1
    acute['levels'][0]['filler']=True
    acute=prepare_facts(acute,style,desc,resolved)
    parts=build_walls(acute,style,desc,tier='low',resolved=resolved)
    assert any(p['tag']=='wall' for p in parts)
    assert len([p for p in parts if p['tag']=='facade_module'])==2
    narrow=polygon_case_facts([[0,0],[1,0],[1,7],[0,7]])
    narrow['storey_m']=3.1
    narrow['levels'][0]['filler']=True
    narrow=prepare_facts(narrow,style,desc,resolved)
    parts=build_walls(narrow,style,desc,tier='low',resolved=resolved)
    assert count(parts,tag='facade_module')==2 and count(parts,tag='wall')==2
    test=deepcopy(hull_facts(stepped_house()))
    test['levels']=test['levels'][:1]
    for edge in test['levels'][0]['edges']:
        edge['openings']=[]
    edge=test['levels'][0]['edges'][0]
    edge['openings']=[dict(kind='window',s0=2,s1=7,y0=.9,y1=2.1)]
    parts=build_walls(test,style,desc,tier='full')
    frames=[bounds([p]) for p in parts if p['tag']=='frame']
    assert len(frames)==8, frames
    for box in ({'min':[1.95,.9,-.37],'max':[2,2.1,-.34]},
                {'min':[7,.9,-.37],'max':[7.05,2.1,-.34]},
                {'min':[1.95,2.1,-.37],'max':[7.05,2.15,-.34]},
                {'min':[1.95,.85,-.37],'max':[7.05,.9,-.34]}):
        assert box in frames
    assert {'min':[1.95,.85,-.4],'max':[7.05,.9,-.34]} in frames
    for x in (3.25,4.5,5.75):
        assert {'min':[x-.025,.9,-.34],'max':[x+.025,2.1,-.24]} in frames
    edge['openings'][0]['kind']='door'
    assert count(build_walls(test,style,desc,tier='full'),tag='frame')==4
    edge['openings'][0].update(kind='window',blind=True)
    frames=[bounds([p]) for p in build_walls(test,style,desc,tier='full') if p['tag']=='frame']
    for x in (3.25,4.5,5.75):
        assert {'min':[x-.025,.9,-.37],'max':[x+.025,2.1,-.36]} in frames
    for tier in ('full','low'):
        panes=[p for p in build_walls(test,style,desc,tier=tier) if p['material']=='blind']
        assert len(panes)==1 and all(v[2]==-.36 for v in panes[0]['vertices'])
    tall_desc=dict(seed=7,overrides=dict(storeys_total=40,ornament_density=0))
    tall=prepare_facts(raw,style,tall_desc,frozenset())
    bands=[p for p in build_walls(tall,style,tall_desc,tier='full') if p['tag']=='band']
    assert len(bands)==156, len(bands)
    stepped=hull_facts(stepped_house())
    stepped['levels'][1]['outline']=deepcopy(stepped['levels'][0]['outline'])
    stepped['levels'][1]['edges']=deepcopy(stepped['levels'][0]['edges'])
    for edge in stepped['levels'][1]['edges']:
        edge['openings']=[]
    stepped['levels'][0]['edges'][0]['openings']=[dict(kind='window',s0=1,s1=2,y0=2.9,y1=3.08)]
    stepped['levels'][1]['edges'][0]['openings']=[dict(kind='window',s0=3,s1=4,y0=3.08,y1=3.3)]
    bands=[p for p in build_walls(stepped,style,desc,tier='full') if p['tag']=='band'
           and all(-.391<=v[2]<=-.339 for v in p['vertices'])]
    assert bands
    for p in bands:
        box=bounds([p])
        assert not (box['min'][0]<2 and box['max'][0]>1 and box['min'][1]<3.08)
        assert not (box['min'][0]<4 and box['max'][0]>3 and box['max'][1]>3.08)
    # A differently directed endpoint must not contribute lower holes.
    stepped['levels'][0]['edges'][0]['b']=[9,0]
    unmatched=[p for p in build_walls(stepped,style,desc,tier='full') if p['tag']=='band'
               and all(-.391<=v[2]<=-.339 for v in p['vertices'])]
    assert any(bounds([p])['min'][0]<2 and bounds([p])['max'][0]>1
               and bounds([p])['min'][1]==2.93 for p in unmatched)
    module_hull=build_hull(raw,style,desc,tier='full',resolved=resolved)
    assert all(c==1 for p in module_hull['parts'] if p['tag']=='facade_module'
               for colors in p['colors'] for c in colors)
    result=build_hull(hull_facts(stepped_house()),style,
                      dict(seed=7,overrides=dict(roof_form='gable',pitch_deg=45)),tier='full')
    for front in (-.39,8.39):
        spans=[]
        for p in result['parts']:
            if p['tag']!='band' or p.get('detail_level')!=1:
                continue
            box=bounds([p])
            if not any(abs(v[2]-front)<1e-4 for v in p['vertices']):
                continue
            if box['max'][2]-box['min'][2]>.051:
                continue
            assert math.isclose(box['min'][1],2.93,abs_tol=1e-4)
            assert math.isclose(box['max'][1],3.23,abs_tol=1e-4)
            spans.append((box['min'][0],box['max'][0]))
        assert spans and min(a for a,b in spans)==-.34 and max(b for a,b in spans)==6.05, spans
    print('PASS: Modern module UVs, fallback, metal frames, sills, mullions, bands, lean-to clipping')


if __name__ == '__main__':
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='hull-walls-smoke-') as storage:
        paths.init(storage)
        main()
