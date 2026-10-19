"""Roof geometry checks. Usage: ./.venv/bin/python scripts/smoke_hull_roofs.py

Hand calculations: L/T/U require 2/2/3 rectangles with areas 56/50/60.
Fachwerk outer offset = .07/2+.005+.30=.34, so 10x8 at 45 degrees
rises (8+2*.34)/2=4.34 above y=3. With .40 overhang, eaves end at
z=-.74 and y=2.60. Hip ridge length is (10+.68)-(8+.68)=2.
Stone stepped house exposes a 4x8 strip beside its 6x8 upper storey;
that strip gets a shed falling away from the covered side, capped at 25°.
Upper inner=.07/2+.005=.04; the high edge stops at x=6+.04+.01=6.05,
so its unchanged plane rises (4+.54-.05)*tan(25°), not (4+2*.54)*tan(25°).
Stepped stone chimneys use only the upper roof: 5.93+(6/2+.54)+.9=10.37.
Upper flat caps instead give 5.93+.25+.9=7.08. With no topmost candidate,
the original shed fallback gives 3.08+4.49*tan(25)+.9.
Chimney widths come from chimney_width_m, independent of description style.
Triangle centroid=(13/3,8/3); nearest edge distance=80/(3*sqrt(113));
its tent rise at 45° is that distance + .34 outer offset. Chimney top
on the rectangle is 3+4.34+.9=8.24, width .6 (.9 for holzhuette).
Flat plates are .25 thick, parapets 1 high. Density 1 gives two chimneys;
probability 1 gives two dormers on the eligible 10x8 gable, none at low.
Every slab is closed: each welded undirected edge occurs twice and its
signed volume is positive. These checks catch winding and missing caps.
"""
import json
import math
import sys
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _hull_fixtures import no_degenerate_faces, roof_shapes, stepped_house
from app.core.hull_roofs import build_roofs, decompose, orthogonal_frame


def close(actual: float, expected: float) -> None:
    """Check geometry within the mesh's four-decimal rounding tolerance."""
    assert abs(actual - expected) < 0.0003, (actual, expected)


def closed(part: dict) -> None:
    """Check closed, outward slab topology after welding face corners."""
    edges = Counter()
    volume = 0
    for face in part["faces"]:
        points = [tuple(part["vertices"][index]) for index in face]
        for first, second in zip(points, points[1:] + points[:1]):
            edges[tuple(sorted((first, second)))] += 1
        first = points[0]
        for index in range(1, len(points) - 1):
            second, third = points[index:index + 2]
            cross = [second[1] * third[2] - second[2] * third[1],
                     second[2] * third[0] - second[0] * third[2],
                     second[0] * third[1] - second[1] * third[0]]
            volume += sum(first[axis] * cross[axis] for axis in range(3)) / 6
    assert set(edges.values()) == {2}, part["tag"]
    assert volume > 0, (part["tag"], volume)


def check_coordinate_snap():
    """Four-centimetre near-equal coordinates must not create sliver wings."""
    from app.core.hull_roofs import _rotate
    clean = [[0,0],[12,0],[12,6],[6,6],[6,12],[0,12]]
    jitter = [[0,0],[12,0],[12,6],[6.04,6],[6,12],[0,12]]
    for angle in (0, 31):
        for covered in (None, [[0,0],[6.02,0],[6.02,6],[0,6]]):
            cover = [_rotate(p, angle) for p in covered] if covered else None
            expected = decompose([_rotate(p, angle) for p in clean], cover, angle)
            actual = decompose([_rotate(p, angle) for p in jitter], cover, angle)
            assert len(actual) == len(expected), actual
            if angle == 0 and covered is None:
                assert any(abs(w["rect"]["length"] - 6.02) < 1e-6 for w in actual), actual
            assert all(min(w["rect"]["length"], w["rect"]["depth"]) >= .15 for w in actual), actual
    print("PASS coordinate snap: jitter, covered outline, rotated frame")


def check_modern_roofs():
    """Plate top=3+.25=3.25; parapet top=4.25; cap top=4.30.

    Cap width=.30+.06=.36. Three identical triangular storeys expose
    only the last plate: 3 candidates minus 2 covered plates = 1.
    In the U notch x=3..7,z=3..8, the triangle edge (1,7)..(9,7)
    leaves the polygon although all three triangle corners lie inside.
    An inner triangle x=2..8,z=0..6 fits a 10x8 rectangular cover,
    including its z=0 boundary; reversing the cover changes no area.
    """
    from _hull_fixtures import polygon_case_facts
    root = Path(__file__).resolve().parents[1]
    style = json.loads((root/'shared/building_styles/burg.json').read_text())
    facts = polygon_case_facts([[0,0],[10,0],[10,8],[0,8]])
    desc = {'overrides': {'roof_form':'flat'}}
    old, _ = build_roofs(facts,style,desc,tier='full')
    assert not any(p['tag']=='parapet_cap' for p in old)
    style.update(parapet_cap=True, wall_thickness_m=.3)
    parts, _ = build_roofs(facts,style,desc,tier='full')
    caps = [p for p in parts if p['tag']=='parapet_cap']
    assert len(caps)==4
    for cap in caps:
        closed(cap)
        close(min(v[1] for v in cap['vertices']),4.25)
        close(max(v[1] for v in cap['vertices']),4.30)
        close(min(max(v[a] for v in cap['vertices'])-min(v[a] for v in cap['vertices']) for a in (0,2)),.36)
    triangle = polygon_case_facts([[0,0],[10,0],[3,8]])
    for i in (1,2):
        level = deepcopy(triangle['levels'][0])
        level.update(level=i, floor_y=3*i, top_y=3*(i+1))
        triangle['levels'].append(level)
    triangle['eaves_y']=9
    _, info = build_roofs(triangle,style,desc,tier='low')
    assert len(info['flat_tops'])==1

    from app.core.hull_roofs import _fully_covered
    u=[[0,0],[10,0],[10,8],[7,8],[7,3],[3,3],[3,8],[0,8]]
    assert not _fully_covered([[1,7],[9,7],[5,1]],u)
    inner=[[2,0],[8,0],[5,6]]
    rectangle=[[0,0],[10,0],[10,8],[0,8]]
    assert _fully_covered(inner,rectangle)
    assert _fully_covered(inner,rectangle[::-1])
    triangle['levels'][1]['outline']=rectangle
    triangle['levels'][2]['outline']=rectangle
    _, info=build_roofs(triangle,style,desc,tier='low')
    assert len(info['flat_tops'])==1


def check_junctions():
    """L: [0,8]x[0,14] and [8,20]x[0,6], so x_max/x_min.

    Stepped T: [0,4]x[0,5], [4,8]x[0,9], [8,12]x[0,3].
    Hence 0 x_max/1 x_min and 1 x_max/2 x_min, including two
    seam sides on rectangle 1. Indices follow returned rectangle order.
    """
    from _hull_fixtures import l_shaped_house
    from app.core.hull_facts import hull_facts
    from app.core.hull_roofs import roof_top_y
    facts = hull_facts(l_shaped_house())
    wings = decompose(facts['levels'][-1]['outline'], None, 0)
    assert [w['seam_sides'] for w in wings] == [
        [{'side':'x_max','neighbor':1}], [{'side':'x_min','neighbor':0}]]
    t = [[0,0],[12,0],[12,3],[8,3],[8,9],[4,9],[4,5],[0,5]]
    wings = decompose(t, None, 0)
    assert len(wings) == 3
    assert [w['seam_sides'] for w in wings] == [
        [{'side':'x_max','neighbor':1}],
        [{'side':'x_min','neighbor':0},{'side':'x_max','neighbor':2}],
        [{'side':'x_min','neighbor':1}]]
    style = json.loads((Path(__file__).resolve().parents[1]/'shared/building_styles/fachwerk.json').read_text())
    style['chimneys'] = [0,0]
    style['dormers'] = 0
    desc = {'seed':1, 'overrides':{'roof_form':'gable','pitch_deg':45}}
    parts, info = build_roofs(facts, style, desc, tier='low')
    higher, lower = info['wings']
    assert lower['ridge_y'] < higher['ridge_y']
    # Main wing rotates its ridge frame 90 degrees: original x_max is
    # local z_min=-4. Lower x_min extends from -6 to -10 (8/2=4 m).
    close(higher['limits'][2], -4)
    close(lower['limits'][0], -10)
    assert not any(p['tag']=='gable' and all(abs(v[0]-8)<1e-4 for v in p['vertices']) for p in parts)
    end = min(lower['ridge'], key=lambda p:p[0])
    top = roof_top_y(higher, end[0], end[2], style)
    assert top is not None and end[1] <= top + .15, (end, top)
    from app.core.hull_walls import wall_offsets
    padding = wall_offsets(style, 2)[1] + info['overhang_m'] + .0002
    for p in [p for p in parts if p['tag']=='roof'][2:]:
        for x,y,z in p['vertices']:
            assert (-padding<=x<=20+padding and -padding<=z<=6+padding or
                    -padding<=x<=8+padding and 6-padding<=z<=14+padding), (x,y,z)
    for name in ('T', 'U', 'rotated_L'):
        case = roof_shapes()[name]
        outline = case['levels'][0]['outline']
        tiles = decompose(outline, None, orthogonal_frame(outline))
        opposite = {'x_min':'x_max','x_max':'x_min','z_min':'z_max','z_max':'z_min'}
        for index, tile in enumerate(tiles):
            for seam in tile['seam_sides']:
                assert {'side':opposite[seam['side']], 'neighbor':index} in tiles[seam['neighbor']]['seam_sides']
        for form in ('gable', 'hip', 'shed'):
            desc['overrides']['roof_form'] = form
            built, metadata = build_roofs(case, style, desc, tier='low')
            assert no_degenerate_faces(built), (name, form)
            if name == 'U' and form == 'gable':
                # All spans are 3 m, so equal rises use the smaller index:
                # left 0 extends into base 1, base 1 into right 2 only.
                left, bar, right = metadata['wings']
                close(left['limits'][0], -4)
                close(bar['limits'][3], 4)
                close(right['limits'][0], -2.5)
                assert roof_top_y(bar,5,4,style) is None, 'courtyard notch filled'

            from app.core.hull_roofs import _rotate
            padding = wall_offsets(style,0)[1] + metadata['overhang_m'] + .0002
            for part in built:
                if part['tag'] != 'roof':
                    continue
                for x,y,z in part['vertices']:
                    assert any(
                        abs(local[0]) <= tile['rect']['length']/2+padding and
                        abs(local[1]) <= tile['rect']['depth']/2+padding
                        for tile in tiles
                        for local in [_rotate([x-tile['rect']['center'][0], z-tile['rect']['center'][1]],
                                              -tile['rect']['angle_deg'])]), (name,form,x,y,z)
            if form == 'shed':
                for wing in metadata['wings']:
                    for x,y,z in wing['ridge']:
                        top = roof_top_y(wing,x,z,style)
                        assert top is not None, (name,wing['limits'],x,y,z)
                        close(top,y)

            for part in built:
                if part['tag'] == 'roof':
                    closed(part)
    print('PASS: reciprocal L/T/U seams, rotated junctions and lower-wing roof junction')


def check_eaves_trim():
    """Timber outer=.34, overhang=.4, tan(45)=1: slab eave=3-.4=2.6.

    Fascia y=2.42..2.60, .03 thick; gutter y=2.32..2.42, .10 thick.
    Gable counts=2/2/4; hip=4/4/0; shed=1/1/2. Cap=3+1=4.
    L loses one main eave and one branch rake end => 3/3/6.
    Tent triangle has 3 eaves, thus 3/3/0; trapezoid has 4/4/0.
    Stepped lower shed loses its covered high side: 1/1/2.
    Low/density zero: 2/0/0; gutters appear at exactly .15 overhang.
    """
    from _hull_fixtures import l_shaped_house
    from app.core.hull_facts import hull_facts
    style=json.loads((Path(__file__).resolve().parents[1]/'shared/building_styles/fachwerk.json').read_text())
    style['roof'].update(overhang_m=[.4,.4],max_rise_ratio=3)
    style.update(chimneys=[0,0],dormers=0)
    desc={'seed':1,'overrides':{'pitch_deg':45,'ornament_density':1}}
    def build(facts=None,tier='full'):
        parts,_=build_roofs(facts or roof_shapes()['rectangle'],style,desc,tier=tier)
        trim=[p for p in parts if p['tag']=='roof_trim']
        for p in trim:
            assert p['material']=='trim'
            closed(p)
        return trim
    def counts(trim):
        c=Counter(p['trim_kind'] for p in trim)
        return tuple(c[k] for k in ('fascia','gutter','verge'))
    for form,want in [('gable',(2,2,4)),('hip',(4,4,0)),('shed',(1,1,2))]:
        desc['overrides']['roof_form']=form
        assert counts(build())==want,form
    desc['overrides']['roof_form']='gable'
    for p in build():
        k=p['trim_kind']
        if k!='verge':
            close(max(v[1] for v in p['vertices']),2.6 if k=='fascia' else 2.42)
            close(min(v[1] for v in p['vertices']),2.42 if k=='fascia' else 2.32)
            close(max(v[2] for v in p['vertices'])-min(v[2] for v in p['vertices']),.03 if k=='fascia' else .10)
    assert counts(build(tier='low'))==(2,0,0)
    desc['overrides']['ornament_density']=0
    assert counts(build())==(2,0,0)
    desc['overrides']['ornament_density']=1
    style['roof']['overhang_m']=[.1,.1]
    assert counts(build())==(2,0,4)
    style['roof']['overhang_m']=[.15,.15]
    assert counts(build())==(2,2,4)
    style['roof']['overhang_m']=[.4,.4]
    desc['overrides']['max_rise_m']=1
    for p in build():
        if p['trim_kind']=='verge': close(max(v[1] for v in p['vertices']),4)
    del desc['overrides']['max_rise_m']
    trim=build(hull_facts(l_shaped_house()))
    assert counts(trim)==(3,3,6)
    for p in trim:
        if p['trim_kind']=='fascia' and max(v[0] for v in p['vertices'])>20:
            close(min(v[0] for v in p['vertices']),8)
    assert counts(build(roof_shapes()['triangle']))==(3,3,0)
    from _hull_fixtures import polygon_case_facts
    assert counts(build(polygon_case_facts([[0,0],[10,0],[8,8],[0,8]])))==(4,4,0)
    lower=[p for p in build(hull_facts(stepped_house())) if p['roof_level']==0]
    assert counts(lower)==(1,1,2)
    # No board lies on the covered high edge x=6.05.
    assert not any(all(abs(v[0]-6.05)<.0003 for v in p['vertices']) for p in lower)
    for name in ('burg','modern'):
        other=json.loads((Path(__file__).resolve().parents[1]/f'shared/building_styles/{name}.json').read_text())
        parts,_=build_roofs(roof_shapes()['rectangle'],other,desc,tier='full')
        assert not any(p['tag']=='roof_trim' for p in parts),name
    desc['overrides']['roof_form']='flat'
    assert not build()
    print('PASS eaves trim: counts, dimensions, cap, tier/density, seams, tent, flat')


def main() -> None:
    """Exercise decomposition, fallbacks, metrics, details and determinism."""
    from app.core.hull_facts import hull_facts
    root = Path(__file__).resolve().parents[1]
    styles = {name: json.loads((root / "shared/building_styles" / f"{name}.json").read_text())
              for name in ("fachwerk", "steinhaus", "holzhuette", "burg")}
    # Preserve these form/detail rows independently of the relative cap.
    for style in styles.values():
        style["roof"]["max_rise_ratio"] = 3
    shapes = roof_shapes()
    close(orthogonal_frame(shapes["rotated_L"]["levels"][0]["outline"]), 30)
    assert orthogonal_frame(shapes["triangle"]["levels"][0]["outline"]) is None
    for name, count, area in (("L", 2, 56), ("T", 2, 50), ("U", 3, 60)):
        wings = decompose(shapes[name]["levels"][0]["outline"], None, 0)
        assert len(wings) == count, (name, wings)
        close(sum(wing["rect"]["length"] * wing["rect"]["depth"] for wing in wings), area)
    timber = deepcopy(styles["fachwerk"])
    timber["roof"]["overhang_m"] = [.4, .4]
    timber["dormers"] = 1
    desc = {"style": "fachwerk", "seed": 1, "overrides": {
        "roof_form": "gable", "pitch_deg": 45, "ornament_density": 1}}
    parts, info = build_roofs(shapes["rectangle"], timber, desc, tier="full")
    close(info["wings"][0]["ridge_y"], 7.34)
    roof_vertices = [point for part in parts if part["tag"] == "roof" for point in part["vertices"]]
    close(min(point[2] for point in roof_vertices), -.74)
    assert any(abs(point[1] - 2.6) < .0003 for point in roof_vertices)
    gables = [part for part in parts if part["tag"] == "gable"]
    assert len(gables) == 2 and all(part["material"] == "wall_ground" for part in gables)
    assert all(all(abs(point[0] + .34) < .0003 for point in part["vertices"])
               or all(abs(point[0] - 10.34) < .0003 for point in part["vertices"]) for part in gables)
    assert sum(part["tag"] == "chimney" for part in parts) == 2
    for chimney in (part for part in parts if part["tag"] == "chimney"):
        close(max(point[1] for point in chimney["vertices"]), 8.24)
        close(max(point[0] for point in chimney["vertices"]) - min(point[0] for point in chimney["vertices"]), .6)
    assert sum(part["tag"] == "dormer" and part["material"] == "trim" for part in parts) >= 2
    low, low_info = build_roofs(shapes["rectangle"], timber, desc, tier="low")
    assert low_info == info and not any(part["tag"] == "dormer" for part in low)
    assert (parts, info) == build_roofs(shapes["rectangle"], timber, desc, tier="full")
    cases = [parts, low]
    from _hull_fixtures import polygon_case_facts
    shapes["square"] = polygon_case_facts([[0, 0], [8, 0], [8, 8], [0, 8]])
    shapes["pentagon"] = polygon_case_facts([[0, 0], [8, 0], [10, 4], [5, 9], [0, 5]])
    shapes["triangle_cw"] = polygon_case_facts(list(reversed(shapes["triangle"]["levels"][0]["outline"])))
    for form in ("gable", "hip", "shed", "flat"):
        current = deepcopy(desc)
        current["overrides"]["roof_form"] = form
        for name, facts in shapes.items():
            result, metadata = build_roofs(facts, timber, current, tier="full", uv_sizes={"roof": 2})
            cases.append(result)
            assert metadata["form"] == form
            if name == "triangle" and form != "flat":
                assert metadata["wings"][0]["form"] == "tent"
                # Centroid=(13/3,8/3); closest edge is 8x+7z-80=0.
                close(metadata["wings"][0]["ridge_y"], 3 + (80 / (3 * math.sqrt(113)) + .34))
            if name == "concave" or form == "flat":
                assert metadata["flat_tops"]
            if name == "rectangle" and form == "hip":
                close(math.dist(*metadata["wings"][0]["ridge"]), 2)
    stepped = hull_facts(stepped_house())
    result, metadata = build_roofs(stepped, styles["steinhaus"], desc, tier="full")
    shed = next(wing for wing in metadata["wings"] if wing["form"] == "shed" and wing["level"] == 0)
    close(shed["ridge_y"], stepped["levels"][0]["top_y"] + (4 + .54 - .05) * math.tan(math.radians(25)))
    # Inner upper face=.04; .01 clearance gives x=6.05; plane rise=(4+.54-.05)*tan(25).
    assert all(abs(point[0] - (6 + .05)) < .0003 for point in shed["ridge"])
    # Upper stone roof: short span=6+2*.54, rise=3.54 at 45 degrees.
    # All chimneys must therefore end at 5.93+3.54+.9=10.37.
    for chimney in (part for part in result if part['tag']=='chimney'):
        close(max(v[1] for v in chimney['vertices']),10.37)
    # Upper flat cap=5.93+.25=6.18; its chimney top=6.18+.9=7.08.
    # A lower pitched wing must not take precedence over that upper flat top.
    flat_desc=deepcopy(desc); flat_desc['overrides']['roof_form']='flat'
    _,flat_info=build_roofs(stepped,styles['steinhaus'],flat_desc,tier='low')
    flat_info['wings']=[shed]
    from app.core.hull_roofs import _chimneys
    flat_chimneys=[]
    _chimneys(flat_info,styles['steinhaus'],desc,1,{},flat_chimneys)
    assert len(flat_chimneys)==2
    for chimney in flat_chimneys:
        close(max(v[1] for v in chimney['vertices']),7.08)
    # Only when neither topmost wings nor topmost flats exist, use old candidates.
    fallback_info={**flat_info,'topmost_level':99}
    fallback=[]
    _chimneys(fallback_info,styles['steinhaus'],desc,1,{},fallback)
    assert len(fallback)==2
    for chimney in fallback:
        close(max(v[1] for v in chimney['vertices']),3.08+4.49*math.tan(math.radians(25))+.9)
    # The .15 m slope slabs use perpendicular thickness, not vertical drop.
    from app.core.hull_mesh import _normal
    for part in result:
        if part["tag"] != "roof":
            continue
        top, bottom = part["faces"][:2]
        points = [part["vertices"][index] for index in top]
        normal = _normal(points)
        magnitude = math.sqrt(sum(value * value for value in normal))
        opposite = part["vertices"][bottom[-1]]
        separation = abs(sum(normal[axis] * (points[0][axis] - opposite[axis]) for axis in range(3))) / magnitude
        close(separation, .15)
    cases.append(result)
    castle, metadata = build_roofs(shapes["U"], styles["burg"], {
        "seed": 3, "overrides": {"roof_form": "flat"}}, tier="full")
    assert all(top["parapet"] for top in metadata["flat_tops"])
    assert len(metadata["flat_tops"]) == 1  # No parapets on internal U-wing seams.
    close(metadata["flat_tops"][0]["y"], 3.25)
    parapets = [part for part in castle if part["tag"] == "parapet"]
    assert parapets
    close(max(point[1] for part in parapets for point in part["vertices"]), 4.25)
    cases.append(castle)
    nonorthogonal_steps = deepcopy(shapes["concave"])
    upper = deepcopy(shapes["triangle"]["levels"][0])
    upper.update(level=1, floor_y=3, top_y=6)
    nonorthogonal_steps["levels"].append(upper)
    nonorthogonal_steps["eaves_y"] = 6
    result, metadata = build_roofs(nonorthogonal_steps, timber, desc, tier="full")
    assert any(top["level"] == 0 and not top["parapet"] for top in metadata["flat_tops"])
    cases.append(result)
    hut_desc = deepcopy(desc)
    hut_desc["style"] = "holzhuette"
    result, _ = build_roofs(shapes["rectangle"], styles["holzhuette"], hut_desc, tier="low")
    for chimney in (part for part in result if part["tag"] == "chimney"):
        close(max(point[0] for point in chimney["vertices"]) - min(point[0] for point in chimney["vertices"]), .9)
    cases.append(result)
    random_desc = {"seed": 19}
    first = build_roofs(shapes["rectangle"], timber, random_desc, tier="low")
    assert first == build_roofs(shapes["rectangle"], timber, random_desc, tier="low")
    close(first[1]["pitch_deg"] * 2, round(first[1]["pitch_deg"] * 2))
    close(first[1]["overhang_m"] * 20, round(first[1]["overhang_m"] * 20))
    for result in cases:
        assert no_degenerate_faces(result)
        json.dumps(result, allow_nan=False)
        for part in result:
            assert part["protrudes"] == (part["tag"] in ("roof", "roof_trim"))
            assert part["material"] != "glass"
            if part["tag"] != "gable":
                closed(part)
    print(f"smoke_hull_roofs: PASS ({len(cases)} cases; decomposition, forms/fallbacks, stepped, details, closed slabs)")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temporary:
        from app.core import paths
        paths.init(temporary)
        check_coordinate_snap()
        check_junctions()
        check_modern_roofs()
        check_eaves_trim()
        main()
