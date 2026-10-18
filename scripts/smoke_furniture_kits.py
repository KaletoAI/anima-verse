#!/usr/bin/env python3
"""Pure furniture-kit contract smoke; no storage or real world modules.

Hand derivation: three kits times twenty unique roles = sixty props. The
21-role union omits toilet in rustic/castle and workbench in modern. Bedroom
has five distinct roles; with only bed present its other four are missing.
Counts: 2 + floor(30 * .04) = 3; 2 + floor(200 * .04) = 10,
clamped to 6. Four chairs times two tables = 8; times six = 24,
clamped to 12. Integers 5 and 20 yield 5 and 12; absent yields 1.
SHA1(r1|chair) = 5dd9216b...971c: final hex c is even, so modulo 2
selects index zero. Keyword dining (6) beats hall (4); short bad must
match a whole word. Equal-length matches follow seed order.

Usage: ./.venv/bin/python scripts/smoke_furniture_kits.py
"""
import sys
import json
import os
import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import furniture_kits as f
from app.core import furnish_solver as solver


def main():
    kits, types = f.load_kits(), f.load_room_types()
    assert list(kits) == ["rustic", "castle", "modern"]
    assert len(f.ROLES) == 21 and len(set(f.ROLES)) == 21
    suffix = "isolated on a plain white background, front three-quarter view, no people, no room, even lighting"
    for kid, kit in kits.items():
        roles = [p["role"] for p in kit["props"]]
        assert len(roles) == len(set(roles)) == 20
        assert set(roles) == set(f.ROLES) - ({"workbench"} if kid == "modern" else {"toilet"})
        for p in kit["props"]:
            assert p["prompt"].endswith(suffix)
            assert all(p[d] > 0 for d in ("width_m", "depth_m", "height_m"))
            assert p["mount"] == ("ceiling" if p["role"] == "ceiling_light" else "floor")
            assert p["role"] != "rug" or p["height_m"] <= .05
    assert len(types) == 10
    assert f.load_room_types() is types
    assert {k: v["hull_styles"] for k, v in kits.items()} == {
        "rustic": ["fachwerk", "steinhaus", "holzhuette"],
        "castle": ["burg"], "modern": ["modern"]}
    assert f.guess_room_type({"name": "living bedroom"}) == "bedroom"
    assert f.guess_room_type({"name": "bedroom kitchen"}) == "bedroom"
    anchors = (solver._FLOOR_ANCHORS | solver._WALL_PASS_ANCHORS |
               solver._CEILING_PASS_ANCHORS | solver._SURFACE_PASS_ANCHORS | {"wall", "corner"})
    for t in types.values():
        for entry in t["template"]:
            assert entry["role"] in f.ROLES and entry.get("ref", "bed") in f.ROLES
            assert entry["anchor"] in anchors
            assert entry["anchor"] != "wall" or entry["wall"] in {"main", "other", "any"}
    for name, expected in [("Schlafzimmer", "bedroom"), ("Hauptschlafzimmer", "bedroom"),
                           ("demo’s Bedroom", "bedroom"), ("Dining hall", "dining"),
                           ("Lobby", "hall"), ("Bad", "bathroom"), ("Raum 3", ""), ("badger", "")]:
        assert f.guess_room_type({"name": name}) == expected, name
    assert f.guess_room_type({"name": "demo", "description": "a cosy kitchen"}) == "kitchen"
    assert f.guess_room_type({"name": "Bedroom", "description": "kitchen"}) == "bedroom"
    assert f.guess_room_type({"activity_hint": "kueche"}) == "kitchen"
    assert f.room_type_of({"name": "Bedroom", "room_type": "study"}) == "study"
    assert f.room_type_of({"name": "Bedroom", "room_type": "unknown"}) == "bedroom"
    library = {"bed-demo": {"tags": ["Kit:Rustic", " ROLE:bed "]}}
    assert f.kit_candidates(library, " RUSTIC ", " Bed ") == ["bed-demo"]
    assert f.kit_candidates(library, "modern", "bed") == []
    for _ in range(2):
        assert f.pick_prop(["a-111111", "b-222222"], "r1", "chair") == "a-111111"
    for spec, area, refs, expected in [({"base": 2, "per_m2": .04, "max": 6}, 30, 0, 3),
        ({"base": 2, "per_m2": .04, "max": 6}, 200, 0, 6),
        ({"per_ref": 4, "max": 12}, 0, 2, 8), ({"per_ref": 4, "max": 12}, 0, 6, 12),
        (5, 0, 0, 5), (20, 0, 0, 12), (None, 0, 0, 1)]:
        assert f.resolve_count(spec, area_m2=area, ref_instances=refs) == expected
    result = f.catalog(library=library)
    assert set(result) == {"kits", "room_types", "location_kit", "room_type", "room_type_guess", "missing_roles"}
    assert next(t["roles"] for t in result["room_types"] if t["id"] == "bedroom") == ["bed", "nightstand", "rug", "wardrobe", "ceiling_light"]
    assert result["location_kit"] is result["room_type"] is result["room_type_guess"] is None
    assert result["missing_roles"]["rustic"]["bedroom"] == ["nightstand", "rug", "wardrobe", "ceiling_light"]
    # Bedroom has five roles (bed + four missing); two nightstands are instances.
    hull = ModuleType("app.core.hull_model")
    world = ModuleType("app.models.world")
    hull.hull_status = lambda lid: {"active": True, "stale": True, "description": {"style": "burg"}}
    world.find_location_by_room = lambda rid: {"id": "demo", "rooms": [{"id": rid, "name": "Bedroom", "room_type": ""}]}
    world.get_room_by_id = lambda loc, rid: loc["rooms"][0]
    world.get_location_by_id = world.find_location_by_room
    with patch.dict(sys.modules, {"app.core.hull_model": hull, "app.models.world": world}):
        assert f.kit_for_location("demo") == "castle"
        result = f.catalog("demo", "demo", library=library)
        assert result["room_type"] is None and result["room_type_guess"] == "bedroom"
        assert result["location_kit"] == "castle"
        hull.hull_status = lambda lid: {"active": False, "description": {"style": "burg"}}
        assert f.kit_for_location("demo") is None
        hull.hull_status = lambda lid: {"active": True, "description": {"style": "unknown"}}
        assert f.kit_for_location("demo") is None
    # Redirect only shared JSON seeds; these checks never initialise storage.
    with tempfile.TemporaryDirectory(prefix="furniture-seeds-") as tmp:
        seed_dir = Path(tmp)
        seed = seed_dir / "kits.json"
        seed.write_text(json.dumps({"kits": kits}), encoding="utf-8")
        with patch.object(f, "_SEED_DIR", seed_dir):
            first = f.load_kits()
            assert f.load_kits() is first
            changed = json.loads(seed.read_text())
            changed["kits"]["rustic"]["name"] = "demo"
            stamp = seed.stat().st_mtime_ns
            seed.write_text(json.dumps(changed), encoding="utf-8")
            os.utime(seed, ns=(stamp + 1000000, stamp + 1000000))
            assert f.load_kits()["rustic"]["name"] == "demo"
            changed["kits"]["rustic"]["props"][0]["width_m"] = -1
            seed.write_text(json.dumps(changed), encoding="utf-8")
            os.utime(seed, ns=(stamp + 2000000, stamp + 2000000))
            try:
                f.load_kits()
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid dimensions accepted")
    assert f.pick_prop([], "demo", "bed") == ""
    assert f.kit_for_location("") is None
    world.find_location_by_room = lambda rid: None
    def unavailable(lid):
        raise LookupError("demo missing")
    hull.hull_status = unavailable
    with patch.dict(sys.modules, {"app.core.hull_model": hull, "app.models.world": world}):
        assert f.kit_for_location("demo") is None
        assert f.catalog(room_id="demo", library={})["room_type"] is None
    print("PASS furniture kits: seeds, guesses, tags, deterministic pick, counts, catalog, lazy hull")


if __name__ == "__main__":
    main()
