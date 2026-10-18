"""Assembly checks. Usage: ./.venv/bin/python scripts/smoke_hull_geometry.py

Identity literals: 2 fixtures * 4 styles * 2 tiers = 16 SHA256 digests.
Reproduce from the repository root (export avoids writing .git):

    mkdir -p /tmp/hull-task3-baseline
    git archive 8b5f1124 | tar -x -C /tmp/hull-task3-baseline
    STORAGE_DIR=$(mktemp -d) ./.venv/bin/python - <<'PY'
    import sys,json,os
    from pathlib import Path
    root=Path('/tmp/hull-task3-baseline')
    sys.path[:0]=[str(root/'scripts'),str(root)]
    from smoke_hull_geometry import digest,description,STYLES
    from _hull_fixtures import stepped_house,l_shaped_house
    from app.core.hull_facts import hull_facts
    from app.core.hull_styles import validate_style
    from app.core.hull_geometry import build_hull
    from app.core import paths
    paths.init(os.environ['STORAGE_DIR'])
    out={}
    for fixture in (stepped_house,l_shaped_house):
     for name in STYLES:
      style=validate_style(json.loads((root/'shared/building_styles'/f'{name}.json').read_text()),name)
      for tier in ('full','low'):
       out[f'{fixture.__name__}:{name}:{tier}']=digest(build_hull(hull_facts(fixture()),style,description(name,7),tier=tier))
    Path('/tmp/hull-task3-identity.json').write_text(json.dumps(out,indent=4))
    print(json.dumps(out,indent=4))
    PY

Forty-storey blind-window bound: Modern outer offset .04+.30=.34 gives
spans 30.68 and 20.68. Bay range [2.6,3.2] gives 30..36 windows per
filler floor: 2*(9+6)..2*(11+7). Thus 39 filler floors give 1170..1404
panes, 2340..2808 pane triangles; 40*4*2=320 shell triangles, plus
8 ground plinth triangles. Roof/ground interior leave ample room below
12000 low and 90000 full. Full bands add 39*4*12=1872 triangles;
metal filler frames disappear at density 0 if needed to fit 90000.
This check uses no resolved module. Density can only decrease from .5.

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
from _hull_fixtures import stepped_house, doors, l_shaped_house, no_degenerate_faces, windows
from app.core import paths
# hull_styles reads world overrides from the world DB: redirect before import.
_STORAGE = tempfile.TemporaryDirectory(prefix="hull-geometry-import-")
paths.init(_STORAGE.name)
from app.core.hull_geometry import TRI_BUDGET, build_hull, cutout_padding_m
from app.core.hull_mesh import PartBuilder, bounds, tri_count
from app.core.hull_styles import validate_style
from app.core.world_geometry import polygon_distance

STYLES = ("fachwerk", "holzhuette", "burg", "steinhaus")


IDENTITY = {
    "stepped_house:fachwerk:full": "70679bb2431c51841eb5dc21f77783462bae0abb4cd4a525f13bb2d31b70bf54",
    "stepped_house:fachwerk:low": "bbdd67458d31e68c85838a8e1b625dad6bcc22cc5eb9e4da387e0bb3cdbae96a",
    "stepped_house:holzhuette:full": "3f5b3b269f38e602639fff04943ca3699581d4c5df333f1279fdb26f1f61728b",
    "stepped_house:holzhuette:low": "868168549cf18f801f6260c4d145da8098ca2b37f837ab6d0889711e2b052742",
    "stepped_house:burg:full": "8baf7d4939833f41dae46fb6e70e77a7012ba5522df833ba27848a680c7e2a74",
    "stepped_house:burg:low": "1f268acef9a014d379b45766b1a97e9b9fab81ae85a1373c63ef0b56b30fccca",
    "stepped_house:steinhaus:full": "44cf16d866edf552b7766aabf3938748d084b284decf30c7028009e73cd5f1da",
    "stepped_house:steinhaus:low": "416fb42ee9764a473304b5b8a3ce760622d73c3b5a12ee17762e75926a72a2f6",
    "l_shaped_house:fachwerk:full": "b9a43a043dd6df2c1c027767803989b8366d322de30b9531be1808d30a9bb4ed",
    "l_shaped_house:fachwerk:low": "d023160d26aa730a3e923969d3a54bac2c29cb53acea4415d489bcc087b4f24c",
    "l_shaped_house:holzhuette:full": "545907b1358772a89564491c4d317a34ae7cb7f92055bc8fd23233d73eeb38a4",
    "l_shaped_house:holzhuette:low": "9424e28258074a0c3f9ef3b3747c789c23d9f36abc97e3b4aabe85abdb511bac",
    "l_shaped_house:burg:full": "7b8d98b5706e2c7ce14735cde9404b222c764010309f6773106231574ef46786",
    "l_shaped_house:burg:low": "95c2234bfadc26b68a46d349d33d4d9248f01bec79fd9a1beeb51033c69573d2",
    "l_shaped_house:steinhaus:full": "eb284aa7554d855861977916d4ad48bad109fce8b0ccfb252631b4a522434066",
    "l_shaped_house:steinhaus:low": "00aa3c403ac3b732e41fc500202d14556cc286bfdb45abd86e2c53b0143d6aa5"
}


def check_identity():
    from app.core.hull_facts import hull_facts
    for fixture in (stepped_house, l_shaped_house):
        for name in STYLES:
            style = validate_style(json.loads(Path(f"shared/building_styles/{name}.json").read_text()), name)
            for tier in ("full", "low"):
                assert digest(build_hull(hull_facts(fixture()), style, description(name, 7), tier=tier)) == IDENTITY[f"{fixture.__name__}:{name}:{tier}"]
    print("PASS: 16 baseline byte-identity literals (8b5f1124)")


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
        if part["tag"] == "facade_module":
            continue
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



def check_forty_storeys():
    from copy import deepcopy
    from _hull_fixtures import gap_house
    from app.core.hull_facts import hull_facts
    from app.core.hull_geometry import fit_budget
    loc = gap_house()
    loc['map3d']['outline'] = [[0,0],[30,0],[30,20],[0,20]]
    loc['rooms'] = [loc['rooms'][0]]
    loc['rooms'][0]['layout'].update(w=30,d=20,openings=[])
    facts = hull_facts(loc)
    original = deepcopy(facts)
    style = validate_style(json.loads(Path('shared/building_styles/modern.json').read_text()),'modern')
    desc = description('modern',7)
    desc['overrides']['storeys_total'] = 40
    fitted = fit_budget(facts,style,desc)
    assert fitted['overrides']['ornament_density'] <= .5
    for tier in ('full','low'):
        result = build_hull(facts,style,fitted,tier=tier)
        assert 1170 <= sum(p['material']=='blind' for p in result['parts']) <= 1404
        assert result['tris'] <= TRI_BUDGET[tier]
        print(f"PASS: 40 storeys {tier}={result['tris']} density={fitted['overrides']['ornament_density']}")
    assert facts == original and desc['overrides']['ornament_density'] == .5

def main() -> None:
    """Exercise all shipped styles, both tiers and assembly failure paths."""
    check_extremes_and_shades()
    with tempfile.TemporaryDirectory(prefix="hull-geometry-") as storage:
        paths.init(storage)
        from app.core.hull_facts import hull_facts

        check_identity()
        check_forty_storeys()
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
            original_parts, _ = _build_parts(facts, style, desc, "full", None, frozenset())
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
