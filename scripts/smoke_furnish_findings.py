#!/usr/bin/env python3
"""Smoke run for the furnishing and reachability findings (2026-10-20).

Pure geometry, no world, no DB: a hand-built location goes through
``scene_recipe.compose_scene`` with a stubbed prop library, and every finding
of ``app/core/furnish_findings.py`` is provoked once — and once NOT, by the
same piece placed right. Each case is a defect the Anima Divide walk-through
found in a real room.

The fixture: one walled room "a" (x −4…0, z −4…−1, 4 × 3 m), storey 3 m,
so the wall top — the ceiling — is 2.85 m over the floor. Its door is in the
middle of the south wall (x −2, z −1) and leads outside; its window sits in
the north wall. In room-local metres (what a placement stores) the room runs
0…4 by 0…3: north wall at z 0, south wall at z 3, west x 0, east x 4.

Usage:  ./.venv/bin/python scripts/smoke_furnish_findings.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="furnish-findings-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="furnish-findings-storage-"))

from app.core import props as prop_store  # noqa: E402
from app.core import scene_recipe  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def rec(pid, w, d, h, mount, category, has_model=True):
    return {"id": pid, "name": pid.title(), "width_m": w, "depth_m": d, "height_m": h,
            "mount": mount, "category": category, "has_model": has_model,
            "rotation": {"x": 0, "y": 0, "z": 0}, "bbox": [w, h, d],
            "model_tiers": ["full"] if has_model else [], "model_signature": pid}


LIB = {
    "mirror": rec("mirror", 1.0, 0.1, 1.5, "wall", "mirror"),
    "shelf": rec("shelf", 1.2, 0.3, 0.3, "wall", "shelf"),
    "mantel": rec("mantel", 1.8, 0.5, 1.3, "wall", "fireplace"),
    "lamp": rec("lamp", 0.5, 0.5, 0.4, "ceiling", "lighting"),
    "wardrobe": rec("wardrobe", 1.6, 0.6, 2.0, "floor", "furniture"),
    "chair": rec("chair", 0.5, 0.5, 0.9, "floor", "chair"),
    "rug": rec("rug", 2.0, 2.0, 0.02, "floor", "textile"),
    "ghost": rec("ghost", 0.5, 0.5, 0.5, "floor", "decor", has_model=False),
}
prop_store.get_prop = lambda pid: dict(LIB[pid]) if pid in LIB else None


def location(props, *, rooms=(), elevator=None) -> dict:
    map3d = {"plan_width_m": 10.0, "storey_height_m": 3.0,
             "outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]]}
    if elevator:
        map3d["elevator"] = elevator
    return {"id": "loc", "map3d": map3d, "rooms": [
        {"id": "a", "name": "A", "layout": {
            "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 0,
            "openings": [
                {"edge": 0, "at": 0.5, "type": "window", "width_m": 1.0,
                 "height_m": 1.2, "sill_m": 0.9},
                {"edge": 2, "at": 0.5, "type": "door", "width_m": 1.0,
                 "height_m": 2.1, "to": "outside"}],
            "props": list(props)}},
        *rooms]}


def kinds(props, **kw) -> dict:
    sc = scene_recipe.compose_scene(location(props, **kw), plan_width_m=10.0)
    return {p["kind"]: p for p in sc["problems"]}


def p(pid, at, yaw=0, oy=0.0, ident=None):
    return {"prop_id": pid, "id": ident or pid, "at": at, "yaw": yaw, "offset_y": oy}


def test_wall_pieces() -> None:
    print("\n[1] wall pieces — height, facing, distance")
    # Badehaus: two mirrors and three towel racks hung at 0.00 m.
    k = kinds([p("mirror", [1.0, 0.1], yaw=0, oy=0.0)])
    check("a mirror at floor height is wall_prop_on_floor",
          "wall_prop_on_floor" in k, str(list(k)))
    check("...in the editor's scope, naming the placement",
          k.get("wall_prop_on_floor", {}).get("scope") == "editor"
          and k["wall_prop_on_floor"].get("prop_ids") == ["mirror"]
          and k["wall_prop_on_floor"].get("prop_names") == ["Mirror"], str(k.get("wall_prop_on_floor")))
    k = kinds([p("mirror", [1.0, 0.1], yaw=0, oy=0.6)])
    check("the same mirror at 0.6 m, back on the north wall: silent", k == {}, str(list(k)))
    # Apartment: two sconces on the east wall turned to face it (yaw 90).
    k = kinds([p("shelf", [3.8, 1.5], yaw=90, oy=1.5)])
    check("a shelf on the east wall facing it is wall_prop_facing_wall",
          "wall_prop_facing_wall" in k, str(list(k)))
    k = kinds([p("shelf", [3.8, 1.5], yaw=270, oy=1.5)])
    check("...turned round (yaw 270): silent", k == {}, str(list(k)))
    # Villa: a kitchen shelf 1.15 m in front of its wall.
    k = kinds([p("shelf", [3.0, 1.5], yaw=270, oy=1.5)])
    check("a shelf 0.8 m in front of the east wall is wall_prop_off_wall",
          "wall_prop_off_wall" in k, str(list(k)))
    # A fireplace is wall-mounted and stands on the floor on purpose.
    k = kinds([p("mantel", [0.3, 1.5], yaw=90, oy=0.0)])
    check("a fireplace on the floor is not wall_prop_on_floor", k == {}, str(list(k)))


def test_ceiling_pieces() -> None:
    print("\n[2] ceiling pieces — the ceiling is the wall top, 2.85 m")
    # Cafe: three ceiling lights at 3.15 m lay on the wall crowns.
    k = kinds([p("lamp", [2.0, 1.5], oy=2.7)])
    check("a lamp reaching 3.1 m is ceiling_prop_through_ceiling",
          "ceiling_prop_through_ceiling" in k, str(list(k)))
    k = kinds([p("lamp", [2.0, 1.5], oy=1.5)])
    check("a lamp topping out at 1.9 m is ceiling_prop_not_hanging",
          "ceiling_prop_not_hanging" in k, str(list(k)))
    k = kinds([p("lamp", [2.0, 1.5], oy=2.44)])
    check("a lamp flush under the ceiling: silent", k == {}, str(list(k)))


def test_floor_pieces() -> None:
    print("\n[3] floor pieces — walls, doors, the lift, the mesh")
    # Haus am See: a walk-in shower half a metre through the bathroom wall.
    k = kinds([p("wardrobe", [1.0, 0.1])])
    check("a wardrobe through the north wall is prop_outside_room",
          "prop_outside_room" in k, str(list(k)))
    k = kinds([p("wardrobe", [1.0, 0.345])])
    check("...pulled back to the wall surface: silent", k == {}, str(list(k)))
    # Gästezimmer: the bed in front of the door. The door is at local x 2,
    # the south wall z 3; its metre runs z 2…3.
    k = kinds([p("chair", [2.0, 2.6])])
    check("a chair in front of the door is prop_in_doorway", "prop_in_doorway" in k, str(list(k)))
    k = kinds([p("rug", [2.0, 2.0])])
    check("a rug in front of the door is walked over: silent", k == {}, str(list(k)))
    # Apartment lobby: something stood where the lift arrives.
    k = kinds([p("chair", [3.0, 1.5])], elevator=[-1.0, -2.5])
    check("a chair in the lift shaft is prop_in_elevator", "prop_in_elevator" in k, str(list(k)))
    k = kinds([p("chair", [1.0, 1.5])], elevator=[-1.0, -2.5])
    check("...beside the shaft: silent", "prop_in_elevator" not in k, str(list(k)))
    # Badehaus: the castle ceiling light that had no mesh.
    k = kinds([p("ghost", [1.0, 1.5])])
    check("a placement without a mesh is prop_without_model", "prop_without_model" in k, str(list(k)))
    k = kinds([{"prop_id": "nowhere", "id": "x", "at": [1.0, 1.5]}])
    check("...and so is one whose prop does not exist", "prop_without_model" in k, str(list(k)))


def test_reachability() -> None:
    print("\n[4] reachability")
    closed = {"id": "b", "name": "B", "layout": {
        "x": 0.0, "y": -4.0, "w": 3.0, "d": 3.0, "level": 0,
        "openings": [{"edge": 1, "at": 0.5, "type": "window", "width_m": 1.0,
                      "height_m": 1.2, "sill_m": 0.9}]}}
    k = kinds([], rooms=[closed])
    check("a room with windows only is room_unreachable",
          k.get("room_unreachable", {}).get("room_id") == "b", str(list(k)))
    check("...a building finding, not in the editor's scope",
          "scope" not in k.get("room_unreachable", {}), str(k.get("room_unreachable")))
    open_b = {**closed, "layout": {**closed["layout"], "openings": [
        {"edge": 3, "at": 0.5, "type": "door", "width_m": 1.0, "height_m": 2.1, "to": "a"}]}}
    k = kinds([], rooms=[open_b])
    check("a door into room a, which has the outside door: silent",
          "room_unreachable" not in k, str(list(k)))


def test_mirrored_opening() -> None:
    print("\n[5] openings_without_walls — the neighbour's door into a terrace")
    # Cafe: the terrace door, drawn on the café's wall, is mirrored into the
    # terrace zone — it is built in the café's wall and must not count.
    terrace = {"id": "t", "name": "T", "layout": {
        "x": 0.0, "y": -4.0, "w": 2.0, "d": 3.0, "level": 0, "always_visible": True}}
    loc = location([], rooms=[terrace])
    loc["rooms"][0]["layout"]["openings"].append(
        {"edge": 1, "at": 0.5, "type": "door", "width_m": 1.0, "height_m": 2.1, "to": "t"})
    sc = scene_recipe.compose_scene(loc, plan_width_m=10.0)
    check("a door drawn on the WALLED side stays silent",
          not [x for x in sc["problems"] if x["kind"] == "openings_without_walls"],
          str([x["kind"] for x in sc["problems"]]))
    check("...and it is built: a threshold between the café and the terrace",
          any(set(d.get("rooms") or []) == {"a", "t"} for d in sc["doorways"]),
          str([d.get("rooms") for d in sc["doorways"]]))


def main() -> int:
    test_wall_pieces()
    test_ceiling_pieces()
    test_floor_pieces()
    test_reachability()
    test_mirrored_opening()
    if FAILURES:
        print(f"\nFAILED: {', '.join(FAILURES)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
