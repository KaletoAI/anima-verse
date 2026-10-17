"""Wall hull checks. Usage: ./.venv/bin/python scripts/smoke_hull_walls.py

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

if __name__ == '__main__':
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='hull-walls-smoke-') as storage:
        paths.init(storage)
        main()
