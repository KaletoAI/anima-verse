#!/usr/bin/env python3
"""Building style seed, validation and world replacement smoke.

Usage: ./.venv/bin/python scripts/smoke_hull_styles.py

Hand-derived expectations: storeys_total 41 clamps to upper bound 40;
0, missing, invalid "x", and negative values omit the optional key.
Other positive values are converted to int before clamping (3.9 -> 3).
Hand-derived expectations: four shipped styles; 9 m clamps to 1.2 m;
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
        assert set(s) == {"fachwerk", "steinhaus", "holzhuette", "burg"}
        assert all(v["origin"] == "shared" for v in s.values())
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
