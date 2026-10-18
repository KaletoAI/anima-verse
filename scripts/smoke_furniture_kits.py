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

Planner hand derivation: 5 x 4, s door .9 + .4 leaves s 3.7;
e window 1.2 + .4 leaves e 2.4 only above sill .9.
Bed .5: n 5.0, e 4.0, w 4.0, s 3.7; wardrobe 2.0:
n 5.0, w 4.0, s 3.7, e 2.4. Two n windows leave n 1.8.
Bedroom 4.5 x 4: n 4.5, e/w 4.0, s 3.2. Bed [2.25, 1.05]
yaw 0; wardrobe [4.15, 2.0] yaw 270; nightstands [3.45, 1.05]
and [1.05, 1.05]; rug [2.25, 2.6] yaw 180; light [2.25, 2.0].
Five floor pieces, one ceiling. Hall 6 x 3: n/s 4.6, e/w 3.0,
but each door side is 2.3 < shelf 2.4: n and s fail, e fits
at [5.75, 1.5]. Corners allocate ne, nw, se, sw. Full n/e blockers
stop both ne slides; reserved nw makes the next alternative se.

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


def demo_library(rows):
    """Own dimensions keep regressions independent of seed prop content."""
    return {role: {"name": role, "width_m": w, "depth_m": d, "height_m": h,
                   "mount": "ceiling" if role == "ceiling_light" else "floor",
                   "tags": ["kit:rustic", f"role:{role}"]}
            for role, w, d, h in rows}


def rectangle(w, d, openings=()):
    return {"outline_m": [[0, 0], [w, 0], [w, d], [0, d]],
            "openings": list(openings), "area_m2": w * d, "w_m": w, "d_m": d}


def planner_smoke():
    # Catch height-insensitive ranking, incorrect tie order and fixed other walls.
    assert callable(getattr(f, "wall_ranking", None)), "wall_ranking is missing"
    geom = rectangle(5, 4, [
        {"edge": 2, "at": .5, "width_m": .9},
        {"edge": 1, "at": .5, "type": "window", "width_m": 1.2, "sill_m": .9}])
    assert f.wall_ranking(geom["outline_m"], geom["openings"], .5) == [
        ("n", 5.0), ("e", 4.0), ("w", 4.0), ("s", 3.7)]
    assert f.wall_ranking(geom["outline_m"], geom["openings"], 2) == [
        ("n", 5.0), ("w", 4.0), ("s", 3.7), ("e", 2.4)]
    rows = [("bed", 1.6, 2, .5), ("nightstand", .5, .4, .6),
            ("rug", 1.6, .8, .02), ("wardrobe", 1.2, .6, 2),
            ("ceiling_light", .4, .4, .5)]
    library = demo_library(rows)

    def plan(geom, library, room_type="bedroom", template=None):
        return f.plan_room(kit="rustic", room_type=room_type, geom=geom,
                           library=library, room_id="demo", template=template)

    planned = plan(geom, library)
    assert planned["entries"][0]["anchor"] == "wall_n"
    assert planned["entries"][3]["anchor"] == "wall_w"
    assert [e["slot"] for e in planned["entries"]] == ["main", None, None, "other", None]
    windows = rectangle(5, 4, [
        {"edge": 0, "at": at, "type": "window", "width_m": 1.2, "sill_m": .9}
        for at in (.3, .7)] + [{"edge": 2, "at": .5, "width_m": .9}])
    assert f.wall_ranking(windows["outline_m"], windows["openings"], 2) == [
        ("e", 4.0), ("w", 4.0), ("s", 3.7), ("n", 1.8)]
    assert plan(windows, library)["entries"][3]["anchor"] == "wall_e"
    missing = plan(geom, demo_library(rows[1:]))
    assert missing["missing_roles"] == ["bed"]
    # The bedroom rug lies in the room's middle, so it survives a missing bed.
    assert [e["prop"] for e in missing["entries"]] == ["rug", "wardrobe", "ceiling_light"]
    assert len(missing["needs"]) == 3
    living = demo_library([("coffee_table", 1, .5, .5), ("rug", 2, 1, .02),
                           ("armchair", .7, .7, 1), ("shelf", 1, .4, 1.8),
                           ("ceiling_light", .4, .4, .5)])
    missing = plan(windows, living, "living")
    assert missing["missing_roles"] == ["sofa"]
    assert [e["prop"] for e in missing["entries"]] == ["shelf", "ceiling_light"]
    # The surviving shelf fixes main=e, then its other slot selects w.
    assert missing["entries"][0]["anchor"] == "wall_w"
    storage = demo_library([("chest", .8, .5, .6), ("shelf", 1, .4, 1.8)])
    stored = plan(rectangle(4, 4), storage, "storage")
    assert [e["prop"] for e in stored["entries"]] == ["shelf", "chest", "chest"]
    assert [e["anchor"] for e in stored["entries"]] == ["wall_n", "wall_e", "corner_ne"]
    assert len(stored["needs"]) == 3
    corners = [{"role": "chest", "anchor": "corner"}] * 2
    assert [e["anchor"] for e in plan(rectangle(4, 4), storage, "storage", corners)
            ["entries"]] == ["corner_ne", "corner_nw"]

    def solve(geom, library, room_type="bedroom", template=None, existing=()):
        return f.solve_kit(kit="rustic", room_type=room_type, geom=geom,
                           library=library, room_id="demo", existing=list(existing),
                           storey_height_m=3, template=template)

    # The probed numbers below are for the bedside-rug variant of the
    # template, pinned here so a seed tuning cannot move them.
    bedside = [{"role": "bed", "anchor": "wall", "wall": "main", "facing": "room"},
               {"role": "nightstand", "anchor": "beside", "ref": "bed", "count": 2},
               {"role": "rug", "anchor": "in_front_of", "ref": "bed"},
               {"role": "wardrobe", "anchor": "wall", "wall": "other"},
               {"role": "ceiling_light", "anchor": "center"}]
    geom = rectangle(4.5, 4, [{"edge": 2, "at": .5, "width_m": .9}])
    result = solve(geom, library, template=bedside)
    assert result["unplaced"] == []
    assert result["phase_counts"]["floor"]["placed"] == 5
    assert result["phase_counts"]["ceiling"]["placed"] == 1
    by_prop = {role: [p for p in result["placed"] if p["prop_id"] == role]
               for role in library}
    for role, at, yaw in [("bed", [2.25, 1.05], 0),
                          ("wardrobe", [4.15, 2.0], 270),
                          ("rug", [2.25, 2.6], 180),
                          ("ceiling_light", [2.25, 2.0], 0)]:
        assert by_prop[role][0]["at"] == at, (role, by_prop[role])
        assert by_prop[role][0]["yaw"] == yaw
    assert [p["at"] for p in by_prop["nightstand"]] == [[3.45, 1.05], [1.05, 1.05]]
    from app.core import furnish_geometry as fg
    floor = [p for p in result["placed"] if library[p["prop_id"]]["mount"] == "floor"]
    quads = [fg.rect_corners(*p["at"], library[p["prop_id"]]["width_m"],
                             library[p["prop_id"]]["depth_m"], p["yaw"]) for p in floor]
    assert all(not fg.rects_overlap(a, b) for i, a in enumerate(quads) for b in quads[i+1:])
    assert json.dumps(result, sort_keys=True) == json.dumps(solve(geom, library, template=bedside), sort_keys=True)
    assert result["needs"][0] == {
        "key": "n1", "kind": "bed", "category": "", "count": 1, "mount": "floor",
        "width_m": 1.6, "depth_m": 2, "height_m": .5, "style": "", "description": "",
        "marker": None, "key_areas": [], "from_description": False,
        "prop_id": "bed", "build": False}
    assert solve(geom, demo_library(rows[1:]))["unplaced"] == []
    hall = demo_library([("shelf", 2.4, .4, 2), ("rug", 2, 1.5, .02)])
    geom = rectangle(6, 3, [{"edge": edge, "at": .5, "width_m": 1}
                            for edge in (0, 2)])
    result = solve(geom, hall, "hall", [
        {"role": "shelf", "anchor": "wall", "wall": "main"},
        {"role": "rug", "anchor": "center"}])
    assert result["unplaced"] == []
    assert result["plan"][0]["anchor"] == "wall_e"
    assert next(p["at"] for p in result["placed"] if p["prop_id"] == "shelf") == [5.75, 1.5]
    stored = solve(rectangle(4, 4), storage, "storage")
    assert len(stored["plan"]) == 3 and len(stored["items"]) == 2
    assert next(i["count"] for i in stored["items"] if i["id"] == "chest") == 2
    blockers = demo_library([("north", 3.9, .8, 1), ("east", .8, 3.9, 1)])
    corner_library = {**demo_library([("chest", .8, .5, .6)]), **blockers}
    existing = [{"prop_id": "north", "id": "demo-n", "at": [2, .45], "yaw": 0},
                {"prop_id": "east", "id": "demo-e", "at": [3.55, 2], "yaw": 0}]
    result = solve(rectangle(4, 4), corner_library, "storage", corners, existing)
    assert result["plan"][0]["anchor"] == "corner_se"
    assert result["plan"][1]["anchor"] == "corner_nw"
    assert result["unplaced"] == []
    # A sibling failure must not move a corner entry that already fitted.
    duplicate_library = demo_library([("chest", .8, .5, .6),
                                      ("north", 3.9, .8, 1), ("west", .8, 3.9, 1)])
    existing = [{"prop_id": "north", "id": "demo-n", "at": [2, .45], "yaw": 0},
                {"prop_id": "west", "id": "demo-w", "at": [.45, 2], "yaw": 0}]
    result = solve(rectangle(4, 4), duplicate_library, "storage", corners, existing)
    assert result["plan"][0]["anchor"] == "corner_ne"
    assert result["plan"][1]["anchor"] == "corner_se"
    assert result["unplaced"] == []
    # Counts refer to all planned tables, even when their entries appear later.
    counted = demo_library([("chair", .4, .4, 1), ("dining_table", 1, 1, .8)])
    counted_plan = plan(rectangle(10, 10), counted, "dining", [
        {"role": "chair", "anchor": "around", "ref": "dining_table",
         "count": {"per_ref": 4}},
        {"role": "dining_table", "anchor": "center", "count": 2}])
    assert [e["count"] for e in counted_plan["entries"]] == [8, 2]
    capped = plan(rectangle(10, 10), counted, "dining", [
        {"role": "chair", "anchor": "center", "count": 8},
        {"role": "chair", "anchor": "corner", "count": 8}])
    assert [e["count"] for e in capped["entries"]] == [8, 4]
    assert solve(rectangle(4, 4), {}, "bedroom")["placed"] == []
    # A floor improvement that loses a wall piece must be rejected. The shelf
    # covers 2.4 of the 3m east wall, leaving no 1m wall-piece spot; west is safe.
    guarded = demo_library([("shelf", 2.4, .4, 2), ("ceiling_light", 1, .2, .5)])
    guarded["ceiling_light"]["mount"] = "wall"
    guarded_template = [{"role": "shelf", "anchor": "wall", "wall": "main"},
                        {"role": "ceiling_light", "anchor": "wall_e", "base_m": .5}]
    guarded_geom = rectangle(6, 3, [{"edge": edge, "at": .5, "width_m": 1}
                                   for edge in (0, 2)])
    result = solve(guarded_geom, guarded, "hall", guarded_template)
    assert result["plan"][0]["anchor"] == "wall_w"
    assert result["phase_counts"]["wall"]["placed"] == 1
    assert result["phase_counts"]["floor"]["placed"] == 1
    assert result["unplaced"] == []
    print("PASS furniture planner: rankings, transitive drops, entries, bedroom, fallback, corners")


def main():
    planner_smoke()
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
