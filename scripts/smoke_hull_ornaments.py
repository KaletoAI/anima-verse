"""Ornament checks. Usage: ./.venv/bin/python scripts/smoke_hull_ornaments.py

Hand calculations: the rectangle has four convex corners and one door.
At density 1 castle tower probability min(1, 1*(.5+1)) is 1: four towers.
Timber members are .16 wide and .05 deep; upper outer face is
.07/2+.005+.30+.25=.59, hence their front is .64 from the contour.
Intermediate posts split each free span into fields <=1.6 m. Logs have
radius .14 and pitch .28: (.5+.14)+8*.28=2.88 is the ninth row center.
The porch is 1.2+1.2=2.4 wide, 1.6 deep, its low roof edge is 2.1+.3=2.4.
Flat plate y=3.25, parapet top=4.25, merlon top=4.85. Merlons are
.6 wide with .5 gaps. Quoins start at .35 and have .3-high rows; row 9 ends at 3.05,
so the first upper-storey fragment spans 3.0..3.05.
An L has five convex corners and one reentrant corner, in either winding.
Padding is wall thickness + .2: 1.1 for burg and .5 for holzhuette.
Porch outer depth .34+1.6=1.94 exceeds .5; tower caps/crowns also
exceed their padding and must be preserved. Flat parapet crenels stay skin.
Blind panes sit at outer+.02; timber spans outer..outer+.05 and logs
outer..outer+.14, so a face with an overlapping s/y bounding box
in front of outer+.02 covers the pane even with all vertices outside.
Blanking filler openings must yield violations with the same test. Both filler storeys (1,2) must be clear. With rooms only on level 2,
upper framing starts at level 1 floor 3.1+.08=3.18, leaving ground
level framing absent just as for an occupied ground floor.
All generated solids must have finite planar faces and outward winding.
"""
import json
import math
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from _hull_fixtures import (count, doors, no_degenerate_faces, opening_edge_cases,
                            polygon_case_facts, rect_facts, roof_shapes)
from app.core.hull_ornaments import build_ornaments
from app.core.hull_roofs import build_roofs
from app.core.hull_walls import wall_offsets


def closed(part: dict) -> None:
    """Check outward volume and paired edges, allowing touching solid components."""
    edges = Counter()
    volume = 0
    for face in part["faces"]:
        points = [tuple(part["vertices"][index]) for index in face]
        for first, second in zip(points, points[1:] + points[:1]):
            edges[tuple(sorted((first, second)))] += 1
        first = points[0]
        for i in range(1, len(points) - 1):
            second, third = points[i:i + 2]
            cross = [second[1] * third[2] - second[2] * third[1],
                     second[2] * third[0] - second[0] * third[2],
                     second[0] * third[1] - second[1] * third[0]]
            volume += sum(first[axis] * cross[axis] for axis in range(3)) / 6
    assert all(value % 2 == 0 for value in edges.values()), part["tag"]
    assert volume > 0, (part["tag"], volume)



def description(seed: int = 1, density: float = 0.5) -> dict:
    """Return the clamped description consumed by hull generators."""
    return {"seed": seed, "overrides": {"ornament_density": density}}


def projected(part: dict, edge: dict) -> tuple:
    """Measure a part in an edge's supplied facade frame."""
    tangent = [(edge["b"][axis] - edge["a"][axis]) / edge["length"] for axis in (0, 1)]
    spans = [sum((point[axis * 2] - edge["a"][axis]) * tangent[axis]
                 for axis in (0, 1)) for point in part["vertices"]]
    depths = [sum((point[axis * 2] - edge["a"][axis]) * edge["normal"][axis]
                  for axis in (0, 1)) for point in part["vertices"]]
    heights = [point[1] for point in part["vertices"]]
    return min(spans), max(spans), min(heights), max(heights), min(depths), max(depths)


def framing(parts: list, facts: dict, style: dict) -> None:
    """Find real vertical posts, verify field spacing and opening flanks."""
    for level in facts["levels"]:
        for edge in level["edges"]:
            outer = wall_offsets(style, level["level"])[1]
            posts = []
            for part in parts:
                if part["tag"] != "timber":
                    continue
                left, right, bottom, top, back, front = projected(part, edge)
                if abs(back - outer) > .0003 or abs(front - outer - .05) > .0003:
                    continue
                for hole in edge["openings"]:
                    assert min(right, hole["s1"]) - max(left, hole["s0"]) < .0003 or min(top, hole["y1"]) - max(bottom, hole["y0"]) < .0003
                if abs(right - left - .16) < .0003 and top - bottom > 1:
                    posts.append((left + right) / 2)
            assert posts
            posts = sorted(set(round(value, 4) for value in posts))
            for left, right in zip(posts, posts[1:]):
                if any(hole["s0"] < right and hole["s1"] > left for hole in edge["openings"]):
                    continue
                assert right - left <= 1.6003, (left, right)
            for hole in edge["openings"]:
                assert any(abs(post - (hole["s0"] - .08)) < .0003 for post in posts)
                assert any(abs(post - (hole["s1"] + .08)) < .0003 for post in posts)


def rectangle_padding(parts: list, facts: dict, style: dict) -> None:
    """Require preservation outside the rectangle's mitered padding ring."""
    outline = facts["levels"][0]["outline"]
    minimum_x, maximum_x = min(point[0] for point in outline), max(point[0] for point in outline)
    minimum_z, maximum_z = min(point[1] for point in outline), max(point[1] for point in outline)
    padding = style["wall_thickness_m"] + .2
    for part in parts:
        for x, _, z in part["vertices"]:
            distance = max(minimum_x - x, x - maximum_x,
                           minimum_z - z, z - maximum_z, 0)
            if distance > padding + .0003:
                assert part["protrudes"], (part["tag"], distance, padding)


def check_modern_ornaments():
    """10x8 plate top=3.25. Housing at (5,4) spans x=3.8..6.2,
    z=2.8..5.2 and y=3.25..5.85; .05 cap ends at 5.90.
    Rooftop counts round(1+2*density) = 1,2,3. Door top 2.1 gives
    canopy underside 2.35, top 2.50, width 1.2+1=2.2, depth 1.2.
    For a horizontal pitched slab at y=2.6, underside=2.45, allowed
    canopy top=2.43, so drop=2.50-2.43=.07 and underside=2.28.
    At roof y=2.4 the required underside=2.08 is below 2.1+.05=2.15:
    omit the canopy. A wall head of 2.4 caps its underside at 2.4-.15=2.25.
    Housing clamped at (1.5,1.5) has minimum corners .3 from both edges.
    U-notch x=3..7,z=3..8 rejects housing centred at (5,5): its
    corners x=3.8/6.2,z=3.8/6.2 lie outside. An upper floor at y=6
    places every roof box at 6+.25=6.25, never the ground top 3.25.
    A 2x2 roof cannot fit a .8-wide unit plus two 1m margins (2.8>2).
    A 2x2 roof cannot fit housing plus two .3 margins (3>2).
    Module filler spans 11.18/9.18 at height 3 choose 4/3 bays;
    zero timber on those edges; occupied upper edges retain framing.
    """
    root = Path(__file__).resolve().parents[1]
    style=json.loads((root/'shared/building_styles/modern.json').read_text())
    facts=rect_facts()
    facts['elevator']=[5,4]
    desc={'seed':1,'overrides':{'roof_form':'flat','ornament_density':1}}
    _, info=build_roofs(facts,style,desc,tier='full')
    parts=build_ornaments(facts,style,desc,info,tier='full')
    housing=[p for p in parts if p['tag']=='housing']
    assert len(housing)==2
    wall=next(p for p in housing if p['material']=='wall')
    for a,lo,hi in ((0,3.8,6.2),(1,3.25,5.85),(2,2.8,5.2)):
        assert abs(min(v[a] for v in wall['vertices'])-lo)<.0003
        assert abs(max(v[a] for v in wall['vertices'])-hi)<.0003
    canopy=[p for p in parts if p['tag']=='canopy']
    assert len(canopy)==1
    assert canopy[0]['protrudes'] and canopy[0]['detail_level']==0
    assert abs(min(v[1] for v in canopy[0]['vertices'])-2.35)<.0003
    assert abs(max(v[1] for v in canopy[0]['vertices'])-2.50)<.0003
    cap=next(p for p in housing if p['material']=='trim')
    assert abs(min(v[1] for v in cap['vertices'])-5.85)<.0003
    assert abs(max(v[1] for v in cap['vertices'])-5.90)<.0003
    for axis,size in ((0,2.2),(1,.15),(2,1.2)):
        assert abs(max(v[axis] for v in canopy[0]['vertices'])-min(v[axis] for v in canopy[0]['vertices'])-size)<.0003
    for part in housing+canopy:
        closed(part)
        assert no_degenerate_faces([part])
    from app.core.hull_ornaments import _canopies
    for eaves,expected in ((2.6,2.28),(2.4,None)):
        colliding=deepcopy(facts)
        colliding['eaves_y']=eaves
        overhanging=deepcopy(style); overhanging['roof']['overhang_m']=[.4,.4]
        _, pitched=build_roofs(colliding,overhanging,{'overrides':{'roof_form':'gable','pitch_deg':0}},tier='low')
        result=[]
        _canopies(colliding['levels'][0],style,{},result,pitched)
        if expected is None:
            assert not result
        else:
            assert len(result)==1
            assert abs(min(v[1] for v in result[0]['vertices'])-expected)<.0003
            assert abs(max(v[1] for v in result[0]['vertices'])-expected-.15)<.0003
    short=deepcopy(facts['levels'][0]); short['top_y']=2.4
    result=[]
    _canopies(short,style,{},result,{})
    assert abs(min(v[1] for v in result[0]['vertices'])-2.25)<.0003
    for point in ([0,0],[10,8]):
        clamped=deepcopy(facts); clamped['elevator']=point
        result=build_ornaments(clamped,style,desc,info,tier='low')
        wall=next(p for p in result if p['tag']=='housing' and p['material']=='wall')
        for axis,lo,hi in ((0,.3,2.7),(2,.3,2.7)) if point==[0,0] else ((0,7.3,9.7),(2,5.3,7.7)):
            assert abs(min(v[axis] for v in wall['vertices'])-lo)<.0003
            assert abs(max(v[axis] for v in wall['vertices'])-hi)<.0003
    concave=deepcopy(roof_shapes()['U']); concave['elevator']=[5,5]
    _, roof=build_roofs(concave,style,desc,tier='low')
    assert not any(p['tag']=='housing' for p in build_ornaments(concave,style,desc,roof,tier='low'))
    stacked=deepcopy(facts)
    upper=deepcopy(stacked['levels'][0]); upper.update(level=1,floor_y=3,top_y=6)
    for edge in upper['edges']:
        edge['openings']=[]
    stacked['levels'].append(upper); stacked['eaves_y']=6
    _, roof=build_roofs(stacked,style,desc,tier='low')
    result=build_ornaments(stacked,style,desc,roof,tier='low')
    for part in result:
        if part['tag'] in ('housing','rooftop') and part['material']!='trim':
            assert abs(min(v[1] for v in part['vertices'])-6.25)<.0003
    tiny=polygon_case_facts([[0,0],[2,0],[2,2],[0,2]])
    tiny['elevator']=[1,1]
    _, roof=build_roofs(tiny,style,desc,tier='low')
    assert not any(p['tag'] in ('housing','rooftop') for p in build_ornaments(tiny,style,desc,roof,tier='low'))
    _, pitched=build_roofs(facts,style,{'overrides':{'roof_form':'gable'}},tier='low')
    assert not any(p['tag'] in ('housing','rooftop') for p in build_ornaments(facts,style,desc,pitched,tier='low'))
    from app.core.world_geometry import point_segment_distance
    boxes=[p for p in parts if p['tag'] in ('housing','rooftop') and p['material']!='trim']
    for box in boxes:
        if box['tag']=='rooftop':
            assert box['material']=='chimney'
            for axis,lo,hi in ((0,.8,1.6),(2,.8,1.6),(1,.8,1.4)):
                size=max(v[axis] for v in box['vertices'])-min(v[axis] for v in box['vertices'])
                assert lo-.0003<=size<=hi+.0003
            for x,_,z in box['vertices']:
                assert min(point_segment_distance(x,z,*a,*b) for a,b in
                    zip(facts['levels'][0]['outline'],facts['levels'][0]['outline'][1:]+facts['levels'][0]['outline'][:1]))>=1-.0003
        for other in boxes:
            if box is other:
                continue
            assert any(max(v[a] for v in box['vertices'])<=min(v[a] for v in other['vertices'])
                       or max(v[a] for v in other['vertices'])<=min(v[a] for v in box['vertices']) for a in (0,2))
    for density,count in ((0,1),(.5,2),(1,3)):
        desc['overrides']['ornament_density']=density
        roomy=polygon_case_facts([[0,0],[40,0],[40,40],[0,40]])
        _, roof=build_roofs(roomy,style,desc,tier='low')
        result=build_ornaments(roomy,style,desc,roof,tier='low')
        assert sum(p['tag']=='rooftop' for p in result)==count
        assert not any(p['tag']=='housing' for p in result)
        assert result==build_ornaments(roomy,style,desc,roof,tier='low')
    style['porch']=True
    assert not any(p['tag']=='canopy' for p in build_ornaments(facts,style,desc,info,tier='low'))
    style=json.loads((root/'shared/building_styles/fachwerk.json').read_text())
    style['materials']['facade_module']='test'
    prepared=rect_facts()
    prepared['storey_m']=3
    for i in (1,2):
        level=deepcopy(prepared['levels'][0])
        level.update(level=i,floor_y=3*i,top_y=3*(i+1),filler=i==1)
        for edge in level['edges']:
            edge['openings']=[]
        prepared['levels'].append(level)
    prepared['eaves_y']=9
    result=build_ornaments(prepared,style,desc,{},tier='full',resolved=frozenset({'facade_module'}))
    assert not any(p['tag']=='timber' and p['detail_level']==1 for p in result)
    assert any(p['tag']=='timber' and p['detail_level']==2 for p in result)
    from app.core.hull_walls import build_walls
    walls=build_walls(prepared,style,desc,tier='full',resolved=frozenset({'facade_module'}))
    assert sum(p['tag']=='facade_module' for p in walls)==4
    fallback=build_ornaments(prepared,style,desc,{},tier='full')
    assert any(p['tag']=='timber' and p['detail_level']==1 for p in fallback)



def check_housing_slit():
    """A 10x8 roof has slit x=4.5..5.5, z=3.5..8.

    Elevator (5,4) stays inside the bbox clamp x=1.5..8.5,z=1.5..6.5,
    so the housing stays at x=3.8..6.2,z=2.8..5.2. All four corners
    lie inside and at least .7 from slit edges, exceeding the .3 margin,
    but its footprint crosses the slit for 5.2-3.5=1.7 m in z.
    Clamping does not search for alternate positions: drop both housing
    wall and cap. Expected housing count is zero in both tiers.
    """
    root=Path(__file__).resolve().parents[1]
    style=json.loads((root/'shared/building_styles/modern.json').read_text())
    facts=polygon_case_facts([[0,0],[10,0],[10,8],[5.5,8],
                              [5.5,3.5],[4.5,3.5],[4.5,8],[0,8]])
    facts['elevator']=[5,4]
    desc={'seed':1,'overrides':{'roof_form':'flat'}}
    for tier in ('full','low'):
        _,roof=build_roofs(facts,style,desc,tier=tier)
        parts=build_ornaments(facts,style,desc,roof,tier=tier)
        assert not any(p['tag']=='housing' for p in parts), tier
    print('PASS: lift housing crossing narrow roof slit is dropped in both tiers')


def main() -> None:
    """Exercise every ornament family and both tiers with supplied facts."""
    root = Path(__file__).resolve().parents[1]
    styles = {name: json.loads((root / "shared/building_styles" / f"{name}.json").read_text())
              for name in ("fachwerk", "holzhuette", "burg", "steinhaus")}
    facts = rect_facts()
    facts2 = deepcopy(facts)
    upper = deepcopy(facts["levels"][0])
    upper.update(level=1, floor_y=3, top_y=6)
    for edge in upper["edges"]:
        for hole in edge["openings"]:
            hole["y0"] += 3
            hole["y1"] += 3
    facts2["levels"].append(upper)
    facts2["eaves_y"] = 6
    timber = styles["fachwerk"]
    parts = build_ornaments(facts2, timber, description(3, 1), {}, tier="full")
    framing(parts, {"levels": [upper]}, timber)
    assert min(point[1] for part in parts for point in part["vertices"]) >= 3
    assert not build_ornaments(facts2, timber, description(), {}, tier="low")
    single = build_ornaments(facts, timber, description(3, 1), {}, tier="full")
    framing(single, facts, timber)
    assert min(point[1] for part in single for point in part["vertices"]) >= .45 - .0003
    assert single != build_ornaments(facts, timber, description(2, 1), {}, tier="full")
    assert single == build_ornaments(facts, timber, description(3, 1), {}, tier="full")
    assert single != build_ornaments(facts, timber, description(3, 0), {}, tier="full")
    castle = styles["burg"]
    _, info = build_roofs(facts, castle, description(1, 1), tier="low")
    battlements = build_ornaments(facts, castle, description(1, 1), info, tier="low")
    assert count(battlements, tag="tower") == 4
    assert count(battlements, tag="crenel") > 0
    bare = deepcopy(castle)
    bare["towers"]["chance"] = 0
    merlons = build_ornaments(facts, bare, description(), info, tier="low")
    assert all(abs(min(point[1] for point in part["vertices"]) - 4.25) < .0003
               and abs(max(point[1] for point in part["vertices"]) - 4.85) < .0003 for part in merlons)
    crown_style = deepcopy(castle)
    crown_style["towers"]["roof"] = ["crenel"]
    crown_low = build_ornaments(facts, crown_style, description(1, 1), {}, tier="low")
    crown_full = build_ornaments(facts, crown_style, description(1, 1), {}, tier="full")
    assert count(crown_full, tag="tower") == count(crown_low, tag="tower") == 4
    assert count(crown_low, tag="crenel") > 0
    assert [part for part in crown_low if part["tag"] == "crenel"] == [part for part in crown_full if part["tag"] == "crenel"]
    cone_style = deepcopy(castle)
    cone_style["towers"]["roof"] = ["cone"]
    for tier in ("full", "low"):
        cone_parts = build_ornaments(facts, cone_style, description(1, 1), {}, tier=tier)
        assert count(cone_parts, tag="roof") == 4
        rectangle_padding(cone_parts, facts, cone_style)
        crown_parts = crown_full if tier == "full" else crown_low
        rectangle_padding(crown_parts, facts, crown_style)
        assert all(part["protrudes"] for part in crown_parts if part["tag"] == "crenel")
        flat_crenels = build_ornaments(facts, bare, description(), info, tier=tier)
        assert flat_crenels and all(part["tag"] == "crenel" and not part["protrudes"]
                                   for part in flat_crenels)
    rectangle_padding(battlements, facts, castle)
    no_parapet = deepcopy(info)
    no_parapet["flat_tops"][0]["parapet"] = False
    assert not build_ornaments(facts, bare, description(), no_parapet, tier="low")
    cabin = styles["holzhuette"]
    logs = build_ornaments(facts, cabin, description(), {}, tier="full")
    low_logs = build_ornaments(facts, cabin, description(), {}, tier="low")
    rectangle_padding(logs, facts, cabin)
    rectangle_padding(low_logs, facts, cabin)
    assert count(logs, tag="porch") == doors(facts)
    assert count(logs, tag="log_end") == 4 * 9
    log_heights = sorted({round((min(point[1] for point in part["vertices"]) + max(point[1] for point in part["vertices"])) / 2, 4)
                          for part in logs if part["tag"] == "log_end"})
    assert log_heights == [round(.64 + index * .28, 4) for index in range(9)]
    porch_cap = next(part for part in logs if part["tag"] == "roof")
    assert min(point[1] for point in porch_cap["vertices"]) == 2.4
    assert max(point[0] for point in porch_cap["vertices"]) - min(point[0] for point in porch_cap["vertices"]) == 2.4
    assert abs(max(point[2] for point in porch_cap["vertices"]) - min(point[2] for point in porch_cap["vertices"]) - 1.6) < .0003
    assert count(low_logs, tag="log_end") == count(logs, tag="log_end")
    assert count(low_logs, tag="log") == 0
    edge = facts["levels"][0]["edges"][0]
    for part in logs:
        if part["tag"] != "log":
            continue
        left, right, bottom, top, back, front = projected(part, edge)
        if abs(back - .34) > .0003 or abs(front - .48) > .0003:
            continue
        for hole in edge["openings"]:
            assert min(right, hole["s1"]) - max(left, hole["s0"]) < .0003 or min(top, hole["y1"]) - max(bottom, hole["y0"]) < .0003
    stone = build_ornaments(facts, styles["steinhaus"], description(), {}, tier="full")
    assert count(stone, tag="quoin") > 0
    stone2 = build_ornaments(facts2, styles["steinhaus"], description(), {}, tier="full")
    upper_quoins = [part for part in stone2 if part["tag"] == "quoin"
                    and abs(min(point[1] for point in part["vertices"]) - 3) < .0003]
    assert upper_quoins and all(abs(max(point[1] for point in part["vertices"]) - 3.05) < .0003 for part in upper_quoins)
    assert not build_ornaments(facts, styles["steinhaus"], description(), {}, tier="low")
    post_style = deepcopy(timber)
    post_style["timber_frame"] = "none"
    posts = build_ornaments(facts, post_style, description(), {}, tier="full")
    assert count(posts, tag="timber") == 4
    all_style = deepcopy(timber)
    all_style["timber_frame"] = "all"
    framing(build_ornaments(facts2, all_style, description(3, 1), {}, tier="full"), facts2, all_style)
    for outline in (roof_shapes()["L"]["levels"][0]["outline"],
                    roof_shapes()["L"]["levels"][0]["outline"][::-1]):
        corner_towers = build_ornaments(polygon_case_facts(outline), castle, description(1, 1), {}, tier="low")
        assert count(corner_towers, tag="tower") == 5
    for case in opening_edge_cases(facts):
        for style in styles.values():
            assert no_degenerate_faces(build_ornaments(case, style, description(1, 1), {}, tier="full"))
    all_parts = parts + single + battlements + crown_low + crown_full + logs + low_logs + stone + posts
    for shape in roof_shapes().values():
        for style in styles.values():
            for tier in ("full", "low"):
                ornaments = build_ornaments(shape, style, description(1, 1), {}, tier=tier)
                assert no_degenerate_faces(ornaments)
                all_parts.extend(ornaments)
    assert no_degenerate_faces(all_parts)
    for part in all_parts:
        closed(part)
        if part["tag"] in ("log_end", "tower", "porch", "roof"):
            assert part["protrudes"]
        elif part["tag"] != "crenel":
            assert not part["protrudes"]
    scaled = build_ornaments(facts, timber, description(3, 1), {}, tier="full", uv_sizes={"trim": 4})
    assert scaled[0]["vertices"] == single[0]["vertices"]
    assert scaled[0]["uvs"] != single[0]["uvs"]
    try:
        build_ornaments(facts, timber, description(), {}, tier="bad")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid tier accepted")
    print("PASS: hull ornaments — framing, logs, corners, battlements, towers, porches, tiers, determinism, solids")



def check_blind_ornaments():
    import tempfile
    from app.core import paths
    from app.core.hull_facts import hull_facts
    from app.core.hull_geometry import prepare_facts
    from app.core.hull_styles import validate_style
    from _hull_fixtures import gap_house
    with tempfile.TemporaryDirectory() as storage:
        paths.init(storage)
        for name in ('fachwerk','holzhuette'):
            style = validate_style(json.loads((root / "shared/building_styles" / f"{name}.json").read_text()),name)
            desc = description(7,1)
            facts = prepare_facts(hull_facts(gap_house()),style,desc,frozenset())
            parts = build_ornaments(facts,style,desc,{},tier='full')
            def violations(parts):
                hits = 0
                for level in facts['levels']:
                    if not level.get('filler',False):
                        continue
                    outer = wall_offsets(style,level['level'])[1]
                    for edge in level['edges']:
                        u = [(edge['b'][k]-edge['a'][k])/edge['length'] for k in (0,1)]
                        for part in parts:
                            if part['tag'] not in ('timber','log'):
                                continue
                            for face in part['faces']:
                                points = [part['vertices'][i] for i in face]
                                spans = [(x-edge['a'][0])*u[0]+(z-edge['a'][1])*u[1] for x,y,z in points]
                                heights = [y for x,y,z in points]
                                depths = [(x-edge['a'][0])*edge['normal'][0]+(z-edge['a'][1])*edge['normal'][1] for x,y,z in points]
                                if max(depths) <= outer+.0203 or min(depths) >= outer+.15:
                                    continue
                                for hole in edge['openings']:
                                    if (min(max(spans),hole['s1'])-max(min(spans),hole['s0']) > 3e-4
                                            and min(max(heights),hole['y1'])-max(min(heights),hole['y0']) > 3e-4):
                                        hits += 1
                return hits

            assert any(e['openings'] for l in facts['levels'] if l.get('filler') for e in l['edges'])
            assert violations(parts) == 0, name
            blank = deepcopy(facts)
            for level in blank['levels']:
                if level.get('filler',False):
                    for edge in level['edges']:
                        edge['openings'] = []
            hits = violations(build_ornaments(blank,style,desc,{},tier='full'))
            assert hits > 0, (name,'clearance test missed blanked openings')
            print(f'PASS: {name} face clearance, blanked openings detected {hits} overlaps')
            if name == 'fachwerk':
                loc = gap_house()
                loc['rooms'] = [loc['rooms'][1]]
                loc['rooms'][0]['layout']['level'] = 2
                ground_filler = prepare_facts(hull_facts(loc),style,desc,frozenset())
                framing_parts = [p for p in build_ornaments(ground_filler,style,desc,{},tier='full') if p['tag']=='timber']
                assert framing_parts and all(v[1]>=3.18 for p in framing_parts for v in p['vertices'])
    print('PASS: timber and logs clear blind pane rectangles')

if __name__ == "__main__":
    check_housing_slit()
    check_modern_ornaments()
    check_blind_ornaments()
    main()
