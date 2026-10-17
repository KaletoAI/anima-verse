"""Roof geometry checks. Usage: ./.venv/bin/python scripts/smoke_hull_roofs.py

Hand calculations: L/T/U require 2/2/3 rectangles with areas 56/50/60.
Fachwerk outer offset = .07/2+.005+.30=.34, so 10x8 at 45 degrees
rises (8+2*.34)/2=4.34 above y=3. With .40 overhang, eaves end at
z=-.74 and y=2.60. Hip ridge length is (10+.68)-(8+.68)=2.
Stone stepped house exposes a 4x8 strip beside its 6x8 upper storey;
that strip gets a shed falling away from the covered side, capped at 25°.
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


def main() -> None:
    """Exercise decomposition, fallbacks, metrics, details and determinism."""
    from app.core.hull_facts import hull_facts
    root = Path(__file__).resolve().parents[1]
    styles = {name: json.loads((root / "shared/building_styles" / f"{name}.json").read_text())
              for name in ("fachwerk", "steinhaus", "holzhuette", "burg")}
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
    close(shed["ridge_y"], stepped["levels"][0]["top_y"] + (4 + 2 * .54) * math.tan(math.radians(25)))
    # The covered neighbor is left of the exposed strip: high edge x=6-.54.
    assert all(abs(point[0] - (6 - .54)) < .0003 for point in shed["ridge"])
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
            assert part["protrudes"] == (part["tag"] == "roof")
            assert part["material"] != "glass"
            if part["tag"] != "gable":
                closed(part)
    print(f"smoke_hull_roofs: PASS ({len(cases)} cases; decomposition, forms/fallbacks, stepped, details, closed slabs)")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temporary:
        from app.core import paths
        paths.init(temporary)
        main()
