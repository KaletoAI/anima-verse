#!/usr/bin/env python3
"""Building style seed, validation and world replacement smoke.

Usage: ./.venv/bin/python scripts/smoke_hull_styles.py

Hand-derived expectations: storeys_total 41 clamps to upper bound 40;
0, missing, invalid "x", and negative values omit the optional key.
Other positive values are converted to int before clamping (3.9 -> 3).
Hand-derived expectations: 4 old styles + modern = 5 shipped styles.
New booleans default false; rooftop counts clamp 9 to 4 at both ends.
Blind bay endpoints 0.5 and 9 clamp to 1.5 and 6; missing ranges use
[2.4, 3.0], [0.9, 1.2], [1.3, 1.5] and sill 0.9 from spec 3.3.
Only wall and trim get existing files in the resolver fixture, so exactly
those two material keys resolve; a directory and missing file do not.
Old styles emit 7 texture slots + glass + interior + blind = 10 materials, since
the empty new facade slot contributes zero. Modern emits 8 + 3 = 11.
Blind uses palette.glass with roughness .1 and opaque alpha 1.0; glass
retains alpha .6, so the two panes have identical colors but distinct opacity.
Width -1/9 clamps to .4/4, height -1/9 to .6/3, sill 9 to 1.5.
New texture scales are 2/2/1/1.5/1 metres (spec 3.8/brief).
The module is 512 square: centre (256,256) is dark glass, while
(0,0) is concrete; matching opposite edge pixels ensure seamless tiling.
Modern values below are literal spec 3.7 values, not sampled output.
Hand-derived expectations: 9 m clamps to 1.2 m;
unsupported dome falls back to gable; deleting the 1.1 m castle override
restores the shipped 0.9 m wall. Pitch 99 clamps to 60, seed -5 to 0,
and #ABC expands each digit to #aabbcc. A partial world document gets
schema defaults (0.4 m), never the castle seed's 0.9 m. Every non-empty
material kind must resolve to a shared texture with a positive physical size.
"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core.db import get_connection, init_schema
        init_schema()
        from app.core.hull_styles import (
            load_styles, get_style, validate_style, validate_description,
            set_world_style, delete_world_style,
        )
        from app.core.surface_textures import base_texture_file, texture_size_m
        s = load_styles()
        for style in s.values():
            for kind in style["materials"].values():
                if kind:
                    texture = base_texture_file(kind)
                    assert texture is not None, kind
                    assert texture_size_m(texture) > 0, kind
        assert set(s) == {"fachwerk", "steinhaus", "holzhuette", "burg", "modern"}
        assert all(v["origin"] == "shared" for v in s.values())
        from PIL import Image
        # Regenerate deterministic fixtures in temporary storage: the live selected
        # facade texture may have been replaced (including its old placeholder).
        from make_hull_placeholder_textures import KINDS, make_texture
        placeholders = Path(tmp) / "placeholders"
        placeholders.mkdir()
        for kind, (_, _, size) in KINDS.items():
            texture = placeholders / f"{kind}.png"
            make_texture(kind).save(texture)
            texture.with_suffix(".json").write_text(json.dumps({"source": "placeholder", "size_m": size}))
        for kind, size in (("concrete_panel", 2.0), ("roof_gravel", 2.0),
                           ("brushed_metal", 1.0), ("metal_door", 1.5),
                           ("facade_module_modern", 1.0)):
            texture = placeholders / f"{kind}.png"
            assert texture_size_m(texture) == size, kind
            assert json.loads(texture.with_suffix(".json").read_text())["source"] == "placeholder"
        with Image.open(placeholders / "facade_module_modern.png") as image:
            assert image.size == (512, 512)
            assert sum(image.getpixel((256, 256))) < sum(image.getpixel((0, 0)))
            assert all(image.getpixel((0, i)) == image.getpixel((511, i))
                       and image.getpixel((i, 0)) == image.getpixel((i, 511)) for i in range(512))

        defaults = validate_style({}, "x")
        assert defaults["blind_windows"] == {
            "bay_m": [2.4, 3.0], "width_m": [0.9, 1.2],
            "height_m": [1.3, 1.5], "sill_m": 0.9}
        for key in ("storey_bands", "roof_housing", "entrance_canopy", "parapet_cap"):
            assert defaults[key] is False
            assert validate_style({key: "true"}, "x")[key] is False
        assert defaults["rooftop_units"] == [0, 0]
        assert defaults["materials"]["facade_module"] == ""
        assert validate_style({"rooftop_units": [9, 9]}, "x")["rooftop_units"] == [4, 4]
        assert validate_style({"blind_windows": {"bay_m": [0.5, 9]}}, "x")["blind_windows"]["bay_m"] == [1.5, 6]
        assert validate_style({"blind_windows": {"width_m": [-1, 9], "height_m": [-1, 9],
                                               "sill_m": 9}}, "x")["blind_windows"] == {
            "bay_m": [2.4, 3.0], "width_m": [0.4, 4], "height_m": [0.6, 3], "sill_m": 1.5}
        assert validate_style({"frames": "metal"}, "x")["frames"] == "metal"
        assert validate_style({"frames": "chrome"}, "x")["frames"] == "timber"
        modern = {
            "name": "Modern", "materials": {
                "wall": "concrete_panel", "wall_ground": "dark_stone", "plinth": "dark_stone",
                "roof": "roof_gravel", "trim": "brushed_metal", "door": "metal_door",
                "chimney": "brushed_metal", "facade_module": "facade_module_modern"},
            "palette": {"glass": "#2f3d47", "interior": "#5a5a58"},
            "wall_thickness_m": 0.3, "plinth_height_m": 0.15, "cornice": False,
            "corners": "none", "frames": "metal", "shutters": 0, "timber_frame": "none",
            "log_walls": False, "jetty_m": 0,
            "roof": {"forms": ["flat"], "pitch_deg": [5, 5], "overhang_m": [0, 0], "parapet": True},
            "crenellations": False, "chimneys": [0, 0], "dormers": 0, "porch": False,
            "storey_bands": True, "rooftop_units": [1, 3], "roof_housing": True,
            "entrance_canopy": True, "parapet_cap": True,
            "blind_windows": {"bay_m": [2.6, 3.2], "width_m": [1.6, 2.2],
                              "height_m": [1.6, 1.9], "sill_m": 0.6},
            "tint_jitter": 0.03, "weathering": 0.15}
        raw_modern = json.loads((Path(__file__).resolve().parents[1] /
                                "shared/building_styles/modern.json").read_text())
        for key, value in modern.items():
            assert raw_modern[key] == value, key
            # A flat style never reads the rise cap; validation still fills
            # its defaults (1c-B: max_rise_m 6.0, min_pitch_deg 20).
            expected = ({**value, "max_rise_m": 6.0, "min_pitch_deg": 20}
                        if key == "roof" else value)
            assert s["modern"][key] == expected, key
        assert raw_modern["towers"]["chance"] == s["modern"]["towers"]["chance"] == 0
        from unittest.mock import patch
        from app.core import hull_model
        existing = Path(tmp) / "existing.png"
        existing.touch()
        resolver_style = validate_style({"materials": {
            "wall": "exists", "trim": "exists", "roof": "missing", "door": "directory"}}, "x")
        def texture_file(kind):
            return {"exists": existing, "missing": Path(tmp) / "absent",
                    "directory": Path(tmp)}.get(kind)
        with patch.object(hull_model.surface_textures, "base_texture_file", side_effect=texture_file):
            assert hull_model.resolved_materials(resolver_style) == frozenset({"wall", "trim"})
        from app.core.hull_styles import MATERIAL_KEYS
        assert set(hull_model.FALLBACK_TONES) == set(MATERIAL_KEYS)
        desc = {"seed": 0, "overrides": {}}
        for name in ("fachwerk", "steinhaus", "holzhuette", "burg", "modern"):
            style = s[name]
            materials, _, _ = hull_model._materials(
                style, desc, Path(tmp) / name, hull_model.resolved_materials(style))
            assert len(materials) == (11 if name == "modern" else 10)
            by_name = {material["name"]: material for material in materials}
            assert by_name["blind"] == dict(name="blind", texture=None,
                color=by_name["glass"]["color"], roughness=.1, alpha=1.0)
            assert by_name["glass"]["alpha"] == .6


        assert s["fachwerk"]["materials"]["wall"] == "plaster_infill"
        assert s["burg"]["roof"]["forms"] == ["flat"]
        assert validate_style({"wall_thickness_m": 9}, "x")["wall_thickness_m"] == 1.2
        assert validate_style({"roof": {"forms": ["dome"]}}, "x")["roof"]["forms"] == ["gable"]
        set_world_style("burg", {**s["burg"], "wall_thickness_m": 1.1})
        assert get_style("burg")["wall_thickness_m"] == 1.1
        assert get_style("burg")["origin"] == "world"
        assert delete_world_style("burg")
        assert not delete_world_style("burg")
        assert get_style("burg")["wall_thickness_m"] == 0.9
        assert get_style("absent") is None
        d = validate_description({"style": "nope", "seed": -5, "overrides": {
            "pitch_deg": 99, "tint": "#ABC", "x": 1}}, s)
        assert d == {"style": "steinhaus", "seed": 0, "overrides": {
            "pitch_deg": 60.0, "ornament_density": 0.5, "tint": "#aabbcc"}}
        assert validate_description(None, s) == {
            "style": "steinhaus", "seed": 0, "overrides": {"ornament_density": 0.5}}
        assert validate_description({"seed": 2**40, "overrides": {
            "roof_form": "dome", "tint": "bad"}}, s)["seed"] == 2**31 - 1
        for value, expected in ((41, 40), (0, None), ('x', None),
                                (-1, None), (3.9, 3), ('10', 10)):
            overrides = validate_description({'overrides': {
                'storeys_total': value}}, s)['overrides']
            if expected is None:
                assert 'storeys_total' not in overrides
            else:
                assert overrides['storeys_total'] == expected
        raw = {"name": "n" * 250, "description": "d" * 650, "unknown": 1,
               "cornice": "false", "roof": {"pitch_deg": [70, -1]},
               "materials": {"wall": " New_Kind ", "door": "../bad"},
               "palette": {"glass": "#ABC"}, "chimneys": [9, -2]}
        v = validate_style(raw, "x")
        assert len(v["name"]) == 200 and len(v["description"]) == 600
        assert "unknown" not in v and v["cornice"] is False
        assert v["roof"]["pitch_deg"] == [5.0, 60.0]
        assert v["chimneys"] == [0, 4]
        assert v["materials"]["wall"] == "new_kind"
        assert v["materials"]["door"] == ""
        assert v["palette"]["glass"] == "#aabbcc"
        for raw in (None, [], "bad", {"roof": None, "towers": [], "materials": {"wall": []},
                                     "weathering": float("nan"), "jetty_m": float("inf")}):
            json.dumps(validate_style(raw, "x"), allow_nan=False)
        set_world_style("burg", {"name": "Replacement"})
        assert get_style("burg")["wall_thickness_m"] == 0.4
        assert get_style("burg")["roof"]["forms"] == ["gable"]
        set_world_style("custom", {})
        assert get_style("custom")["origin"] == "world"
        conn = get_connection()
        stored = conn.execute("SELECT doc, updated_at FROM building_styles_world WHERE id='custom'").fetchone()
        assert "origin" not in json.loads(stored[0]) and stored[1]
        conn.execute("DROP TABLE building_styles_world")
        conn.commit()
        assert load_styles() == s
        conn.execute("CREATE TABLE building_styles_world (wrong TEXT)")
        conn.commit()
        try:
            load_styles()
        except sqlite3.OperationalError as error:
            assert "no such column" in str(error)
        else:
            raise AssertionError("Non-missing-table SQLite errors must propagate")
    print("smoke_hull_styles: PASS")


if __name__ == "__main__":
    main()
