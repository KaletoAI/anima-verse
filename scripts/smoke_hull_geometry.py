"""Assembly checks. Usage: ./.venv/bin/python scripts/smoke_hull_geometry.py

Hand derivation: L corners (0,0),(20,0),(20,6),(8,6),(8,14),(0,14)
span 20 by 14 m. Each of three floors has 3+2+1+2=8 windows;
ground has two additional doors, hence 24 windows and 2 doors.
Budgets are 90000 full / 12000 low triangles. Padding is thickness +
jetty + .15 (logs) or .06 (other) + .05 as a minimum. Actual padding
is max(minimum, full nonprotruding vertex distance) + .02, rounded
up to .01 m; orthogonal corners must stay within 1.5 * minimum.
At weathering 1 the ground
shade is .75, middle shade 1, eaves shade .88. At y=.75, smoothstep
is .5, giving .875; at eaves-.4 it gives .94. Wall box UVs divide
projected world coordinates by 2.5, so 2.5 metres is one UV unit.
"""
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _hull_fixtures import doors, l_shaped_house, no_degenerate_faces, windows
from app.core import paths
# hull_styles reads world overrides from the world DB: redirect before import.
_STORAGE = tempfile.TemporaryDirectory(prefix="hull-geometry-import-")
paths.init(_STORAGE.name)
from app.core.hull_geometry import TRI_BUDGET, build_hull, cutout_padding_m
from app.core.hull_mesh import PartBuilder, bounds, tri_count
from app.core.hull_styles import validate_style
from app.core.world_geometry import polygon_distance

STYLES = ("fachwerk", "holzhuette", "burg", "steinhaus")


def description(style: str, seed: int) -> dict:
    """Supply a deterministic description without overriding the style."""
    return {"style": style, "seed": seed, "overrides": {"ornament_density": .5}}


def digest(value: dict) -> str:
    """Hash the complete serializable result, rejecting nonfinite numbers."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def check_hull(result: dict, facts: dict, style: dict, tier: str) -> None:
    """Verify metadata, padding, colors and all polygon payloads."""
    digest(result)
    assert result["bounds"] == bounds(result["parts"])
    assert result["tris"] == tri_count(result["parts"]) <= TRI_BUDGET[tier]
    assert result["materials"] == sorted({part["material"] for part in result["parts"]})
    assert result["padding_m"] >= cutout_padding_m(style) + .02 - 1e-12
    assert no_degenerate_faces(result["parts"])
    for part in result["parts"]:
        if not part["protrudes"]:
            for x, _, z in part["vertices"]:
                assert min(polygon_distance(x, z, level["outline"]) for level in facts["levels"]) <= result["padding_m"] + 1e-4, part["tag"]
        for face, colors in zip(part["faces"], part["colors"]):
            assert len(face) == len(colors)
            for index, shade in zip(face, colors):
                y = part["vertices"][index][1]
                bottom = max(0, min(1, y / 1.5))
                top = max(0, min(1, (y - facts["eaves_y"] + .8) / .8))
                expected = 1.0
                if part["material"] in ("wall", "wall_ground", "plinth", "trim", "chimney"):
                    expected -= style["weathering"] * (.25 * (1 - bottom * bottom * (3 - 2 * bottom)) + .12 * top * top * (3 - 2 * top))
                assert math.isclose(shade, expected, abs_tol=1e-12)


def check_uvs(result: dict) -> None:
    """Check actual box projection on wall faces at supplied metre scale."""
    checked = 0
    for part in result["parts"]:
        if part["tag"] != "wall":
            continue
        for face, uvs in zip(part["faces"], part["uvs"]):
            points = [part["vertices"][index] for index in face]
            spans = [max(point[axis] for point in points) - min(point[axis] for point in points) for axis in range(3)]
            axis = min(range(3), key=lambda index: spans[index])
            axes = [index for index in range(3) if index != axis]
            for point, uv in zip(points, uvs):
                assert all(math.isclose(value, point[index] / 2.5, abs_tol=1e-4) for value, index in zip(uv, axes))
            checked += 1
    assert checked > 0


def check_extremes_and_shades() -> None:
    """Pin missing-extreme restoration and independently calculated shades."""
    low_builder = PartBuilder("wall", "wall")
    low_builder.box([0, 4.5, 0], [2, 9, 2])
    low_part = low_builder.part()
    extreme_parts = []
    for center in ([-2, 4, 0], [2, 4, 0], [0, 4, -2], [0, 4, 2], [0, -1, 0]):
        builder = PartBuilder("frame", "trim")
        builder.box(center, [1, 1, 1])
        extreme_parts.append(builder.part())
    # Six coplanar corners pin both weathering transitions.
    shade_builder = PartBuilder("shade-probe", "wall")
    shade_builder.poly([[0, 0, 0], [1, .75, 0], [2, 1.5, 0],
                        [2, 8.2, 0], [1, 8.6, 0], [0, 9, 0]])
    shade_part = shade_builder.part()
    full_parts = [low_part, shade_part, *extreme_parts]
    supplied = {"levels": [{"outline": [[-10, -10], [10, -10], [10, 10], [-10, 10]]}], "eaves_y": 9}
    style = {"wall_thickness_m": .3, "weathering": 1}
    from app.core import hull_geometry
    with patch.object(hull_geometry, "_build_parts", side_effect=[([low_part.copy()], {}), (full_parts, {})]):
        low = build_hull(supplied, style, {}, tier="low")
    assert low["bounds"] == bounds(full_parts)
    assert [part["vertices"] for part in low["parts"][1:]] == [part["vertices"] for part in extreme_parts]
    assert all(copied is not original for copied, original in zip(low["parts"][1:], extreme_parts))
    with patch.object(hull_geometry, "_build_parts", return_value=([shade_part], {})):
        result = build_hull(supplied, style, {}, tier="full")
    expected = [.75, .875, 1, 1, .94, .88]
    assert all(math.isclose(actual, shade, abs_tol=1e-12)
               for actual, shade in zip(result["parts"][0]["colors"][0], expected))
    assert math.isclose(cutout_padding_m({"wall_thickness_m": .3, "jetty_m": .25}), .66)
    assert math.isclose(cutout_padding_m({"wall_thickness_m": .3, "log_walls": True}), .5)


def main() -> None:
    """Exercise all shipped styles, both tiers and assembly failure paths."""
    check_extremes_and_shades()
    with tempfile.TemporaryDirectory(prefix="hull-geometry-") as storage:
        paths.init(storage)
        from app.core.hull_facts import hull_facts

        facts = hull_facts(l_shaped_house())
        assert facts["ok"] and len(facts["levels"]) == 3
        assert windows(facts) == 24 and doors(facts) == 2
        root = Path(__file__).resolve().parents[1]
        for name in STYLES:
            style = validate_style(json.loads((root / "shared/building_styles" / f"{name}.json").read_text()), name)
            desc = description(name, 7)
            full = build_hull(facts, style, desc, tier="full")
            low = build_hull(facts, style, desc, tier="low")
            from app.core.hull_geometry import _build_parts
            original_parts, _ = _build_parts(facts, style, desc, "full", None)
            assert [part["protrudes"] for part in full["parts"]] == [part["protrudes"] for part in original_parts], "builder flags changed"
            drivers = sorted((
                (max(min(polygon_distance(x, z, level["outline"]) for level in facts["levels"])
                     for x, _, z in part["vertices"]), part["tag"])
                for part in original_parts if not part["protrudes"] and part["vertices"]), reverse=True)
            expected_padding = math.ceil((max(cutout_padding_m(style), drivers[0][0]) + .02) * 100) / 100
            assert full["padding_m"] == low["padding_m"] == expected_padding
            assert full["padding_m"] <= cutout_padding_m(style) * 1.5, (name, full["padding_m"], drivers[:10])
            for tier, result in (("full", full), ("low", low)):
                check_hull(result, facts, style, tier)
            for key, axes in (("min", (0, 1, 2)), ("max", (0, 2))):
                assert all(abs(full["bounds"][key][axis] - low["bounds"][key][axis]) <= 1e-4 for axis in axes)
            assert digest(full) == digest(build_hull(facts, style, desc, tier="full"))
            assert digest(full) != digest(build_hull(facts, style, description(name, 8), tier="full"))
            check_uvs(build_hull(facts, style, desc, tier="full", uv_sizes={"wall": 2.5, "wall_ground": 2.5}))
            rotated = hull_facts(l_shaped_house(rotated=True))
            assert windows(rotated) == 24 and doors(rotated) == 2
            check_hull(build_hull(rotated, style, description(name, 1), tier="full"), rotated, style, "full")
            print(f"PASS: {name} full={full['tris']} low={low['tris']} padding={full['padding_m']:.2f} d_max={drivers[0][0]:.6f} driver={drivers[0][1]}")
        assert TRI_BUDGET == {"full": 90000, "low": 12000}
        for tier in ("full", "low"):
            with patch.dict(TRI_BUDGET, {tier: 1}):
                try:
                    build_hull(facts, style, desc, tier=tier)
                except ValueError as error:
                    assert "budget" in str(error).lower()
                else:
                    raise AssertionError("over-budget hull accepted")
        try:
            build_hull(facts, style, desc, tier="bad")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid tier accepted")
        print("PASS: hull geometry budgets, AABB, padding, weathering, UVs, determinism, rotated L")


if __name__ == "__main__":
    main()
