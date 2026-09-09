#!/usr/bin/env python3
"""Smoke check: every used storey of a location owns a corridor room.

Usage:  ./.venv/bin/python scripts/smoke_floor_rooms.py

Pure functions, no server, no world.db. Every expectation below is derived
BY HAND from docs/superpowers/specs/2026-09-09-etagen-flur-design.md § 2,
never recorded from output.

Part 1 — ids (§ 2.1):
    floor_room_id(-1)  -> "__floor__-1"     the level rides in the id, sign included
    floor_room_id(0)   -> "__floor__0"
    floor_room_level("__floor__-1") -> -1
    floor_room_level("__floor__x")  -> None  not an int, not a corridor
    floor_room_level("__ground__")  -> None  the ground is not a corridor
    is_floor_room("abc12345")       -> False
    is_floor_room("__floor__-1")    -> True   the prefix plus a whole number

Part 2 — which storeys get a corridor (§ 2.2, floor_levels):
    rooms: k1 (layout level -1), eg (layout level 0), ground (props only)
      map3d {}                       -> {-1}       storey 0 only on opt-in
      map3d {ground_corridor: true}  -> {-1, 0}    opt-in AND a room on 0
    rooms: only k1 (level -1), map3d {ground_corridor: true}
                                     -> {-1}       opt-in without a room on 0 is nothing
    rooms: eg without layout         -> set()      no layout, no used storey
    the ground's reduced layout (props, no level) never counts as a storey

Part 2b — ensure_floor_rooms is a two-way sync:
    [] with k1                       -> appends {"id": "__floor__-1", "level": -1,
                                        "name": "", "description": "", "activities": []}
                                        and returns [] (nothing removed)
    run twice                        -> second run appends nothing (idempotent)
    previous had __floor__-1 named "Kellerflur" -> the name comes back
    previous entry with description "dark"       -> the description comes back too
                                        (the editor submits whole lists; a
                                        corridor it never sent must not lose
                                        the text an author wrote for it)
    rooms carry __floor__2 but no room on level 2 -> entry removed,
                                        returns ["__floor__2"]
    an authored __floor__-1 (id present, room on -1) -> left untouched

Part 3 — get_floor_name (§ 2.1): English defaults, lang "" = English
    level 0  -> "Hallway"
    level -1 -> "Corridor (basement)"
    level -2 -> "Corridor (basement -2)"
    level 1  -> "Corridor (floor 1)"
    floor_room_display_name({"id": "__floor__-1", "name": ""})
             -> "Corridor (basement)"   no name of its own = the default of its level
    floor_room_display_name({"id": "__floor__-1", "name": "Kellerflur"})
             -> "Kellerflur"            an authored name always wins

Part 4 — entry room (§ 4): __floor__0 may be the arrival room, no other corridor
    valid_entry_room([eg, __floor__0], "__floor__0")  -> "__floor__0"
    valid_entry_room([k1, __floor__-1], "__floor__-1") -> ""
    valid_entry_room([eg], "zzz")                      -> ""   unknown room
    valid_entry_room([eg], "eg")                       -> "eg"

Part 4b — sanitizers (§ 2.1/§ 2.3): the write path keeps the two invariants
    the corridor rooms rest on. The ground-floor opt-in is a FLAG, not a truthy
    value — only the literal True is stored, so "yes" or 1 never switches a
    hallway on by accident; and a corridor carries NO layout, because its plate
    and hull are the location's.
    _sanitize_map3d({"ground_corridor": True})["ground_corridor"] -> True
    _sanitize_map3d({"ground_corridor": "yes"})  -> no such key
    _sanitize_map3d({"ground_corridor": 1})      -> no such key
    _sanitize_map3d({"ground_corridor": False})  -> no such key
    _sanitize_rooms_layout([{"id": "__floor__-1", "layout": {"x": 0}}])
             -> the entry has no "layout" key left

Part 5 — the door rule (§ 3.1), through compose_scene on a hand-built
    location. A door nobody linked leads into the storey's corridor where
    there is one, so it stops being an exterior door and cuts no hole into
    the building hull.
    Contour 10 x 10 (corners (-5,-5) (5,-5) (5,5) (-5,5)), storey 3 m; each
    room carries ONE door on its south edge ("S", at 0.5, 0.9 x 2.0 m) and
    none of them names a `to`:
      k1  level -1  x -4 y -4 w 3 d 3   (world x -4..-1, z -4..-1)
      k2  level -1  x  1 y -4 w 3 d 3   (world x  1.. 4, z -4..-1)
      eg  level  0  x -4 y -4 w 4 d 3   (world x -4.. 0, z -4..-1)
    rooms[] also carries __ground__ and __floor__-1, the way the server
    stores them (Task 2). The two cellar doors sit on the same line z = -1
    but 5 m apart (centres x -2.5 and 2.5, 0.9 m wide), so the gap dedup
    never merges them into one threshold.
      k1 doorway rooms -> ["k1", "__floor__-1"], outside False
      k2 doorway rooms -> ["k2", "__floor__-1"], outside False
      eg doorway rooms -> ["eg"],                outside True
                                        (level 0 has no corridor room)
      hull leaves on level -1 -> 0      no hole in the hull downstairs
      hull leaves on level  0 -> 1      the front door
      problems carry no "no_building_entrance": eg's door is still one
    HULL vs ROOM wall: a piece cut from a ROOM's shell carries a "room_id"
    (_room_walls), a piece of the building hull carries none
    (_contour_walls) — that is how the leaf count tells the two apart. Each
    of the three doors always puts a leaf into its own room wall; only the
    hull's leaf is at stake here.
    The same location WITHOUT the __floor__-1 entry (red probe, old rule):
      k1 outside True, hull leaves on level -1 -> 2
    The same location with EG'S OPENING REMOVED (companion probe): no doorway
    on level 0 leads outside any more, so problems DO carry
    "no_building_entrance" — the assertion above states something real.

Part 5b — a PARTY WALL, same contour and storey (§ 3.1): the corridor is the
    second room only of a gap no other room claims, so it must lose against a
    neighbour — which is decided after the gap dedup, not while a doorway is
    built.
      k1  level -1  x -4 y -4 w 3 d 3   door on its EAST edge ("E", at 0.5,
                                        0.9 x 2.0), no `to`
      k3  level -1  x -1 y -4 w 3 d 3   no opening of its own
      __floor__-1 present, so the corridor rule is armed
    Both rects meet on the line x = -1 (k1 runs x -4..-1, k3 x -1..2, both
    z -4..-1), so room_recipe._mirrored_openings hands k3 a copy of that door
    stamped `to: "k1"`. The two candidates are the same gap and the dedup
    melts them into ONE doorway carrying both rooms:
      doorways on level -1 -> 1, its rooms -> ["k1", "k3"], outside False
      no "__floor__-1" anywhere in that doorway's rooms
      hull leaves on level -1 -> 0   (an interior gap pierces no hull)
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import world  # noqa: E402
# Pure import too — world_ops opens no world at import time (checked: the
# storage dir stays unset), so the sanitizers are callable without a world.db.
from app.core.world_ops import (  # noqa: E402
    _sanitize_map3d, _sanitize_rooms_layout)
from app.core import scene_recipe  # noqa: E402

FAILS = 0


def check(label, actual, expected):
    global FAILS
    ok = actual == expected
    print(("  ok   " if ok else "  FAIL ") + f"{label}: {actual!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILS += 1


def room(rid, level=None, layout=True, name=""):
    r = {"id": rid, "name": name, "description": "", "activities": []}
    if layout and level is not None:
        r["layout"] = {"level": level, "x": -4, "y": -4, "w": 3, "d": 3}
    return r


def rm(rid, level, x, y, w, d, edge="S"):
    """A rectangular room with ONE unlinked door on the named edge.

    Shaped like ``scripts/smoke_scene_recipe.py::fixture``: plan coordinates
    are local metres, and the legacy edge letters are N/E/S/W. ``edge=None``
    gives a room without any opening.
    """
    layout = {"level": level, "x": x, "y": y, "w": w, "d": d}
    if edge:
        layout["openings"] = [{"edge": edge, "at": 0.5, "width_m": 0.9,
                               "height_m": 2.0, "type": "door"}]
    return {"id": rid, "name": rid, "layout": layout}


def location(rooms):
    """The 10 x 10 contour of Part 5 around a list of rooms."""
    return {"id": "loc1", "name": "Cellar house", "rooms": list(rooms),
            "map3d": {"outline": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
                      "storey_height_m": 3}}


def cellar_fixture(with_corridor=True, eg_door=True):
    """Two cellar rooms and a ground-floor room, each with one unlinked door."""
    rooms = [rm("k1", -1, -4, -4, 3, 3), rm("k2", -1, 1, -4, 3, 3),
             rm("eg", 0, -4, -4, 4, 3, edge="S" if eg_door else None),
             {"id": world.GROUND_ROOM_ID, "name": ""}]
    if with_corridor:
        rooms.append({"id": "__floor__-1", "level": -1, "name": ""})
    return location(rooms)


def party_wall_fixture():
    """Two cellar rooms sharing the wall x = -1, the door drawn by k1."""
    return location([rm("k1", -1, -4, -4, 3, 3, edge="E"),
                     rm("k3", -1, -1, -4, 3, 3, edge=None),
                     {"id": world.GROUND_ROOM_ID, "name": ""},
                     {"id": "__floor__-1", "level": -1, "name": ""}])


def hull_leaves(sc, level):
    """Door leaves in the BUILDING HULL on one storey — a hull piece carries
    no ``room_id``, a room's own wall piece does (see the docstring)."""
    return sum(1 for w in sc["walls"] if w.get("leaf")
               and not w.get("room_id") and w.get("level") == level)


def main():
    print("Part 1 — ids")
    check("floor_room_id(-1)", world.floor_room_id(-1), "__floor__-1")
    check("floor_room_id(0)", world.floor_room_id(0), "__floor__0")
    check("level of __floor__-1", world.floor_room_level("__floor__-1"), -1)
    check("level of __floor__x", world.floor_room_level("__floor__x"), None)
    check("level of ground", world.floor_room_level(world.GROUND_ROOM_ID), None)
    check("is_floor_room(abc12345)", world.is_floor_room("abc12345"), False)
    check("is_floor_room(__floor__-1)", world.is_floor_room("__floor__-1"), True)

    print("Part 2 — floor_levels")
    ground = {"id": world.GROUND_ROOM_ID, "name": "", "layout": {"props": []}}
    rooms = [room("k1", -1), room("eg", 0), ground]
    check("no opt-in", world.floor_levels(rooms, {}), {-1})
    check("opt-in", world.floor_levels(rooms, {"ground_corridor": True}), {-1, 0})
    check("opt-in without room on 0",
          world.floor_levels([room("k1", -1)], {"ground_corridor": True}), {-1})
    check("no layout", world.floor_levels([room("eg", layout=False)], {}), set())

    print("Part 2b — ensure_floor_rooms")
    rs = [room("k1", -1)]
    removed = world.ensure_floor_rooms(rs, {})
    check("appended", [r["id"] for r in rs], ["k1", "__floor__-1"])
    check("entry shape", rs[1], {"id": "__floor__-1", "level": -1, "name": "",
                                 "description": "", "activities": []})
    check("nothing removed", removed, [])
    world.ensure_floor_rooms(rs, {})
    check("idempotent", [r["id"] for r in rs], ["k1", "__floor__-1"])
    rs2 = [room("k1", -1)]
    world.ensure_floor_rooms(rs2, {}, previous=[{"id": "__floor__-1", "name": "Kellerflur"}])
    check("name restored", rs2[1]["name"], "Kellerflur")
    rs2b = [room("k1", -1)]
    world.ensure_floor_rooms(rs2b, {}, previous=[
        {"id": "__floor__-1", "name": "X", "description": "dark"}])
    check("description restored", rs2b[1]["description"], "dark")
    rs3 = [room("k1", -1), {"id": "__floor__2", "level": 2, "name": ""}]
    removed = world.ensure_floor_rooms(rs3, {})
    check("stale corridor removed", [r["id"] for r in rs3], ["k1", "__floor__-1"])
    check("removed ids", removed, ["__floor__2"])
    rs4 = [room("k1", -1), {"id": "__floor__-1", "level": -1, "name": "Mine"}]
    world.ensure_floor_rooms(rs4, {})
    check("present entry untouched", rs4[1]["name"], "Mine")

    print("Part 3 — get_floor_name")
    check("0", world.get_floor_name(0), "Hallway")
    check("-1", world.get_floor_name(-1), "Corridor (basement)")
    check("-2", world.get_floor_name(-2), "Corridor (basement -2)")
    check("1", world.get_floor_name(1), "Corridor (floor 1)")
    check("display name default",
          world.floor_room_display_name({"id": "__floor__-1", "name": ""}),
          "Corridor (basement)")
    check("display name authored",
          world.floor_room_display_name({"id": "__floor__-1",
                                         "name": "Kellerflur"}),
          "Kellerflur")

    print("Part 4 — valid_entry_room")
    check("hallway ok", world.valid_entry_room(
        [room("eg", 0), {"id": "__floor__0"}], "__floor__0"), "__floor__0")
    check("basement corridor refused", world.valid_entry_room(
        [room("k1", -1), {"id": "__floor__-1"}], "__floor__-1"), "")
    check("unknown", world.valid_entry_room([room("eg", 0)], "zzz"), "")
    check("plain", world.valid_entry_room([room("eg", 0)], "eg"), "eg")

    print("Part 4b — sanitizers")
    # Dropping a corridor layout is logged for the author — not here, where it
    # is the expected outcome and would only litter the run. The previous
    # level comes back afterwards, so the parts below keep their logging.
    world_log = logging.getLogger("world")
    previous_level = world_log.level
    world_log.setLevel(logging.WARNING)
    try:
        check("opt-in True kept",
              _sanitize_map3d({"ground_corridor": True}).get("ground_corridor"),
              True)
        for bad in ("yes", 1, False):
            check(f"opt-in {bad!r} dropped",
                  "ground_corridor" in _sanitize_map3d({"ground_corridor": bad}),
                  False)
        corridor = [{"id": "__floor__-1", "layout": {"x": 0}}]
        _sanitize_rooms_layout(corridor)
        check("corridor layout dropped", corridor[0], {"id": "__floor__-1"})
    finally:
        world_log.setLevel(previous_level)

    print("Part 5 — the door rule in the scene recipe")
    sc = scene_recipe.compose_scene(cellar_fixture())
    dw = {d["rooms"][0]: d for d in sc["doorways"]}
    check("k1 doorway rooms", dw["k1"]["rooms"], ["k1", "__floor__-1"])
    check("k1 not outside", dw["k1"]["outside"], False)
    check("k2 doorway rooms", dw["k2"]["rooms"], ["k2", "__floor__-1"])
    check("k2 not outside", dw["k2"]["outside"], False)
    check("eg doorway rooms", dw["eg"]["rooms"], ["eg"])
    check("eg outside", dw["eg"]["outside"], True)
    check("hull leaves level -1", hull_leaves(sc, -1), 0)
    check("hull leaves level 0", hull_leaves(sc, 0), 1)
    check("no entrance problem",
          [p for p in sc.get("problems") or []
           if p.get("kind") == "no_building_entrance"], [])

    # Red probe: the same location without the corridor room keeps the old
    # rule — an unlinked door is an exterior door and pierces the hull.
    sc0 = scene_recipe.compose_scene(cellar_fixture(with_corridor=False))
    dw0 = {d["rooms"][0]: d for d in sc0["doorways"]}
    check("no corridor: k1 outside", dw0["k1"]["outside"], True)
    check("no corridor: hull leaves level -1", hull_leaves(sc0, -1), 2)

    # Companion probe: without eg's door nobody can get into the building any
    # more, so the finding above is a real assertion and not a tautology.
    sc1 = scene_recipe.compose_scene(cellar_fixture(eg_door=False))
    check("no front door: entrance problem",
          [p["kind"] for p in sc1.get("problems") or []
           if p.get("kind") == "no_building_entrance"],
          ["no_building_entrance"])

    print("Part 5b — a party wall beats the corridor")
    sc2 = scene_recipe.compose_scene(party_wall_fixture())
    cellar = [d for d in sc2["doorways"] if d["level"] == -1]
    check("one doorway for the shared gap", len(cellar), 1)
    check("party wall rooms", cellar[0]["rooms"] if cellar else None,
          ["k1", "k3"])
    check("party wall not outside",
          cellar[0]["outside"] if cellar else None, False)
    check("hull untouched on level -1", hull_leaves(sc2, -1), 0)

    print("FAILED" if FAILS else "ALL OK")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
