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

Part 6 — the corridor anchor (§ 3.2), floor_anchor() is pure:
    outline = the 10 x 10 square, one hull = k1's shell x -4..-1, z -4..-1
    (a) no lift, no pads -> grid rule. Clearance of a candidate = min distance
        to any hull edge or outline edge. Outline clearance >= 3.5 needs
        x, z in [-1.5, 1.5]; in that box the hull distance is
        sqrt((x+1)^2 + (z+1)^2) for x, z > -1, and only (1.5, 1.5) reaches
        3.536 >= 3.5. Every other grid point scores below 3.5 (e.g. (1.0, 1.5)
        -> hull 3.20; (2.0, 2.0) -> outline 3.0). So: anchor [1.5, 1.5], free.
    (b) lift at (3, -3): inside the outline, outside the hull -> [3, -3]
        (rule 1)
    (c) lift at (-2.5, -2.5): inside the hull -> ignored; pad at (2, 3)
        -> [2, 3]
    (d) hull = the whole square -> no free point -> centroid [0, 0], free False
    (e) no outline -> (None, False)

Part 6b — corridors[] through compose_scene on cellar_fixture():
    one entry {room_id "__floor__-1", level -1, anchor [-2.0, 2.0],
    outline [[-5, -5], [5, -5], [5, 5], [-5, 5]]}.
    The outline is the storey footprint the anchor was measured on: the
    fixture declares no level_outlines, so outline_source_level falls back to
    map3d.outline, i.e. the location's own 10 x 10 contour, verbatim and
    without a closing duplicate.
    Derivation: the level -1 hulls are k1 (x -4..-1, z -4..-1) and k2
    (x 1..4, z -4..-1). Clearance(x, z) = min(outline clearance
    5 - max(|x|, |z|), dist to k1, dist to k2). For a value v the outline
    needs |x|, |z| <= 5 - v, and standing above the rooms the hull distance
    is at most z + 1 over a room, so v <= z + 1 <= 6 - v, i.e. v <= 3. v = 3
    is reached exactly on the row z = 2.0 for every x with |x| <= 2 (outline
    3.0; the hull distance is 3.0 vertically over a room, and between the two
    it is sqrt((1 - |x|)^2 + 9) >= 3). Between the rooms and beside them
    (|x| < 1, -4 <= z <= -1) the hull distance is at most 1, and the
    neighbouring rows stay under 3.0: (0, 1.5) -> min(3.5, sqrt(1 + 6.25)
    = 2.69) = 2.69, over a room at z = 1.5 the hull gives 2.5, and (0, 2.5)
    -> outline 2.5. So the maximum 3.0 ties along z = 2.0,
    x in {-2.0, ..., 2.0}, and the tie rule (smallest x, then smallest z)
    picks [-2.0, 2.0].
    no "corridor_without_floor" problem
    …and the SIGNATURE moves with the corridor (review 2026-09-09): a corridor
    room has no layout, so it reaches neither map3d nor a room recipe nor a
    room meta — without its own term in the hash a client polling `signature`
    would keep the old corridors[] AND the old door rule.
      signature(with_corridor=True) != signature(with_corridor=False)
      the same fixture composed twice -> the same signature
    …and the same fixture with ONE staircase, at [3, 3], dir_deg 0 (= +z),
    from_level -1: rule 2 beats the raster. A pad sits a pad-half plus the
    pad gap clear of the flight (STAIR_PAD_M / 2 + STAIR_PAD_GAP_M
    = 0.45 + 0.05 = 0.5 m), so the FOOT — the landing on level -1 — is
    [3, 3] - (0, 1) * 0.5 = [3.0, 2.5], inside the contour and clear of both
    cellar rooms. The HEAD lands on level 0, which owns no corridor here.
      corridors anchor -> [3.0, 2.5]

Part 6c — a level -1 room filling the square (x -5 y -5 w 10 d 10) plus
    __floor__-1: every free-point candidate lies in that room's hull, so the
    grid finds nothing and rule 4 falls back to the outline centroid.
      corridors -> one entry, anchor [0, 0]
      problems  -> exactly ONE "corridor_without_floor", level -1
    And the corridor is out of the room census (§ 3.4): a location whose only
    rooms are __ground__ and __floor__-1 has nothing an author could draw a
    layout for, so "rooms_without_layout" must stay silent. Red probe: the
    same location plus a normal room without a layout -> the finding fires.

Part 6d — A BOUNDARY IS A FOOTPRINT TOO (review 2026-09-09). ``_plates``
    resolves a storey's shape as `_outline_world(map3d, level) or plot`, the
    drawn `map3d.boundary`; `_corridors` read the outline alone, so a building
    that was only given a boundary drew its cellar plate and shipped NO
    corridor entry — every figure of that corridor stood in the yard. Spec
    § 3.2 ties the two together: "no outline AND no boundary → no plate and no
    anchor", so a boundary alone must yield an anchor.
    Fixture = cellar_fixture() with `map3d.outline` DELETED and the very same
    10 x 10 square drawn as `map3d.boundary`. Nothing else moves, so every
    number of Part 6b holds verbatim — the hulls are k1 and k2, the footprint
    is the same square, and the maximum clearance 3.0 ties along z = 2.0 with
    the tie rule picking the smallest x:
      corridors -> one entry, room_id "__floor__-1", level -1,
                   anchor [-2.0, 2.0], outline the square
      no "corridor_without_floor"
    And the WALLS keep their outline-only rule: a boundary is a plot line, not
    a shell, so `_hull_doorways`/`_contour_walls` build nothing from it.
      contour wall pieces on level -1 -> 0
    Red probe: neither outline nor boundary -> no plate and no entry.
      corridors -> []

Part 7 — the migration's door count (§ 3.5, count_corridor_doors). It is what
    the boot log reports per location as "doors that now lead into a
    corridor": a door or passage nobody linked, in a drawn room standing on a
    storey that gets a corridor. Pure — the migration itself touches rows and
    is not run here.
      cellar_fixture(): k1 and k2 carry an unlinked door on level -1, eg one
        on level 0, and level 0 owns no corridor without the opt-in     -> 2
      the same fixture with map3d.ground_corridor true: eg's door joins  -> 3
      one room on -1 with a plain unlinked door                         -> 1
        (the probe below is a real one)
      the same door with to "outside": it is linked, the hull keeps it   -> 0
      the same opening as a window: a window is no way through          -> 0
    …and the boot log NAMES them (corridor_door_rooms, review 2026-09-09):
    the same walk, one entry per room in `rooms[]` order, the name where the
    room has one and the id where it has not. cellar_fixture()'s k1 and k2 are
    named after their ids, eg's door sits on the corridor-less level 0.
      cellar_fixture() -> ["k1", "k2"]

Part 8 — the hull door (§ 6), through compose_scene. A corridor has no walls,
    so a ground floor whose complement is a hallway carries its front door on
    the BUILDING OUTLINE. Fixture = cellar_fixture() plus
      map3d.ground_corridor true AND a __floor__0 entry in rooms[] — together
        they are what makes level 0 a corridor storey,
      eg's own door given to "outside": with the hallway on, an unlinked door
        would lead into the corridor (§ 3.1) and cut no hull at all,
      ONE hull opening {level 0, edge 0, at 0.5, 1.0 x 2.1 m, door}.

    THE WINDING, by the shoelace _contour_walls measures it with (the sum of
    x1*z2 - x2*z1 around the ring): the 10 x 10 square (-5,-5) (5,-5) (5,5)
    (-5,5) gives 50 + 50 + 50 + 50 = 200 > 0, so `ccw` holds and the outward
    side of a directed edge (ux, uz) is (uz, -ux) — the very formula
    _hull_doorways uses. Edge 0 runs (-5,-5) -> (5,-5), so ux, uz = 1, 0,
    length 10 and the outward normal is [0, -1]: away from the square, which
    lies at z > -5. (Fixture ground truth, not the assumption in the brief:
    both give the same sign here.)
    at 0.5 -> t = 5, and the clamp into [half, length - half] = [0.5, 9.5]
    leaves it there, so at_world = (-5, -5) + (1, 0) * 5 = [0, -5].
      hull doorway: rooms ["__floor__0"], outside True, hull True, along
        [1, 0], width_m 1.0, height_m min(2.1, wall 3 - 0.15 = 2.85) = 2.1,
        base_y storey_floor_y(0, 3) = 0.0, and no internal key left over

    WHICH CONTOUR EDGES ARE CUT ON LEVEL 0 — the two outside doors sit on
    OPPOSITE sides of the building:
      the hull door cuts edge 0 (z = -5) at t 4.5..5.5, i.e. x -0.5..0.5;
      eg's front door cuts edge 2 (z = +5). eg is x -4..0, z -4..-1 and its
        opening sits on the letter edge "S" = a room rect's BR->BL side
        (room_recipe._normalize_opening), i.e. the line z = -1. So the door
        looks along +z from (-2, -1), and _contour_hit walks it to (-2, +5):
        a 0.9 m cut, x -2.45..-1.55.
    Per edge then, with MIN_WALL_PIECE_M = 0.06 dropping nothing:
      edge 0: full pieces (0, 4.5) and (5.5, 10) -> 4.5 m each
        (x -5..-0.5 and x 0.5..5);
      edge 2, running (5,5) -> (-5,5): the cut lies at t 6.55..7.45, so the
        full pieces are 6.55 m (x 5..-1.55) and 2.55 m (x -2.45..-5).
    Both doors carry a leaf (neither names door_prop "none"), so each cut also
    holds one lintel and one leaf:
      the hull door's leaf runs from the wall foot 0.0 to its head 2.1 over
        x -0.5..0.5, and its lintel starts at that head and is
        foot + wall - top_y = 0 + 2.85 - 2.1 = 0.75 m tall.
      hull leaves on level 0 -> 2, their centres x -2.0 and 0.0
      hull leaves on level -1 -> 0   (the cellar doors lead into __floor__-1)

    A hull opening on level 2, where no room and therefore no corridor stands:
      no doorway of its own, and problems[] carries
      "hull_opening_without_corridor" with level 2.

    THE HULL DOOR IS AN ENTRANCE: the same fixture WITHOUT eg's opening keeps
    no_building_entrance silent, because the hull door is then the only
    outside door on level 0 — and dropping the hull opening as well makes the
    finding fire, which is what turns the first half into an assertion.

    A hull opening on EDGE 7 of a footprint that has four edges (the outline
    could have been redrawn with fewer corners, or the level_outlines cascade
    could now resolve elsewhere): no doorway, and problems[] carries
    "hull_opening_off_the_outline" with level 0 and edge 7 — a door the author
    drew must never vanish in silence.

    THE SAME HULL DOOR ON A RING LISTED THE OTHER WAY ROUND. Reversing the
    square gives (-5,5) (5,5) (5,-5) (-5,-5) with shoelace -200, so `ccw` is
    False and the outward side of (ux, uz) is (-uz, ux). The z = -5 line is
    edge 2 there, running (5,-5) -> (-5,-5), i.e. ux, uz = -1, 0 — so the
    outward normal is (-0, -1) = [0, -1], the same physical direction, as it
    must be; at 0.5 -> t = 5 -> at_world = (5,-5) + (-1,0)*5 = [0, -5], the
    same hole, only `along` is now [-1, 0].
    THE LEAF therefore hangs on the other jamb: hinge "left" is the end
    `along` comes from, x = +0.5 instead of x = -0.5, and turning the group
    positively about y moves its free end along (uz, -ux) = (0, +1) — INTO
    the building. So `door.swing` is -1 where the other ring gives +1: what
    is preserved is not the sign but the BEHAVIOUR, and the sign is how the
    renderer is told which way to turn. The old rule read the outward side off
    `along` alone and answered +1 here, swinging the leaf into the house.
      swing * (along_z, -along_x) == outward_normal, on BOTH rings -> [0, -1]
    The prop library is stubbed for this probe (no world, no props on disk),
    the way smoke_scene_recipe stubs it.

    THE SANITIZER (world_ops._sanitize_map3d): a hull opening is a room
    opening (_sanitize_opening) plus the storey it stands on, and a building
    contour is a polygon —
      a valid entry survives, defaulting to level 0,
      "2" as a level is parsed to the int 2,
      edge "S" is dropped: letters name a rectangle's sides, not a contour,
      a nine-entry list keeps the first eight.
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


SQUARE = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
K1_HULL = [[-4, -4], [-1, -4], [-1, -1], [-4, -1]]


def full_floor_fixture(extra_rooms=()):
    """One level -1 room covering the whole contour, plus its corridor."""
    return location([rm("big", -1, -5, -5, 10, 10, edge=None),
                     {"id": world.GROUND_ROOM_ID, "name": ""},
                     {"id": "__floor__-1", "level": -1, "name": ""}]
                    + list(extra_rooms))


def boundary_only_fixture(square=True):
    """cellar_fixture() with the square DRAWN AS THE BOUNDARY, not as the
    contour — ``map3d.outline`` is gone. ``square=False`` drops both."""
    loc = cellar_fixture()
    m3 = dict(loc["map3d"])
    m3.pop("outline", None)
    if square:
        m3["boundary"] = [list(pt) for pt in SQUARE]
    loc["map3d"] = m3
    return loc


def hull_fixture(levels=(0,), eg_door=True, outline=None, edge=0,
                 prop_id=""):
    """cellar_fixture() with the ground floor's hallway switched on and a door
    drawn on the building outline for each level in ``levels``."""
    loc = cellar_fixture(eg_door=eg_door)
    loc["rooms"].append({"id": "__floor__0", "level": 0, "name": ""})
    if eg_door:
        # With the hallway on, an UNLINKED door leads into the corridor
        # (§ 3.1) — eg keeps its own front door, so the hull is cut twice.
        eg = next(r for r in loc["rooms"] if r["id"] == "eg")
        eg["layout"]["openings"][0]["to"] = "outside"
    opening = {"edge": edge, "at": 0.5, "width_m": 1.0, "height_m": 2.1,
               "sill_m": 0.0, "type": "door"}
    if prop_id:
        opening["prop_id"] = prop_id
    loc["map3d"] = dict(loc["map3d"], ground_corridor=True,
                        hull_openings=[dict(opening, level=lv)
                                       for lv in levels])
    if outline:
        loc["map3d"]["outline"] = [list(pt) for pt in outline]
    return loc


def stair_fixture():
    """cellar_fixture() plus one flight climbing out of the cellar."""
    loc = cellar_fixture()
    loc["map3d"] = dict(loc["map3d"],
                        stairs=[{"at": [3, 3], "from_level": -1,
                                 "dir_deg": 0}])
    return loc


def hull_leaves(sc, level):
    """Door leaves in the BUILDING HULL on one storey — a hull piece carries
    no ``room_id``, a room's own wall piece does (see the docstring)."""
    return sum(1 for w in sc["walls"] if w.get("leaf")
               and not w.get("room_id") and w.get("level") == level)


def hull_line(sc, level, z):
    """The BUILDING-HULL pieces standing on the contour line z = ``z`` of one
    storey — a hull piece carries no ``room_id`` (see hull_leaves)."""
    return [w for w in sc["walls"]
            if not w.get("room_id") and w.get("level") == level
            and w["from"][1] == z and w["to"][1] == z]


def piece_len(w):
    return round(abs(w["to"][0] - w["from"][0]), 4)


def hull_door(sc):
    """The one doorway drawn on the building outline."""
    return next(d for d in sc["doorways"] if d.get("hull"))


def swing_out(sc):
    """Where the leaf's free end TRAVELS once the renderer applies `swing`:
    turning (+along) about y moves it along (along_z, -along_x), times the
    sign. It must be the doorway's outward normal, whatever the winding."""
    door = next(m["door"] for m in sc["models"] if m.get("door"))
    along = hull_door(sc)["along"]
    return [round(door["swing"] * along[1], 4) + 0.0,
            round(-door["swing"] * along[0], 4) + 0.0]


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

    print("Part 6 — the corridor anchor")
    check("(a) freest grid point",
          scene_recipe.floor_anchor(SQUARE, [K1_HULL], None, []),
          ([1.5, 1.5], True))
    check("(b) the lift wins",
          scene_recipe.floor_anchor(SQUARE, [K1_HULL], [3, -3], []),
          ([3.0, -3.0], True))
    check("(c) lift in a room, stair pad next",
          scene_recipe.floor_anchor(SQUARE, [K1_HULL], [-2.5, -2.5],
                                    [[2, 3]]),
          ([2.0, 3.0], True))
    check("(d) rooms fill the storey",
          scene_recipe.floor_anchor(SQUARE, [SQUARE], None, []),
          ([0.0, 0.0], False))
    check("(e) no outline, no anchor",
          scene_recipe.floor_anchor([], [], None, []), (None, False))

    print("Part 6b — corridors[] in the payload")
    check("corridors", sc["corridors"],
          [{"room_id": "__floor__-1", "level": -1, "anchor": [-2.0, 2.0],
            "outline": [[-5.0, -5.0], [5.0, -5.0], [5.0, 5.0], [-5.0, 5.0]]}])
    check("no corridor_without_floor",
          [p for p in sc.get("problems") or []
           if p.get("kind") == "corridor_without_floor"], [])

    check("the corridor moves the signature",
          sc["signature"] != sc0["signature"], True)
    check("composing twice is stable",
          scene_recipe.compose_scene(cellar_fixture())["signature"],
          sc["signature"])
    sc2b = scene_recipe.compose_scene(stair_fixture())
    check("stair foot beats the raster",
          [c["anchor"] for c in sc2b["corridors"]], [[3.0, 2.5]])

    print("Part 6c — no floor left for the corridor")
    sc3 = scene_recipe.compose_scene(full_floor_fixture())
    check("centroid anchor", [c["anchor"] for c in sc3["corridors"]],
          [[0.0, 0.0]])
    check("corridor_without_floor levels",
          [p.get("level") for p in sc3.get("problems") or []
           if p.get("kind") == "corridor_without_floor"], [-1])

    # The corridor is not a room somebody forgot to draw (§ 3.4).
    sc4 = scene_recipe.compose_scene(location(
        [{"id": world.GROUND_ROOM_ID, "name": ""},
         {"id": "__floor__-1", "level": -1, "name": ""}]))
    check("corridor alone: no rooms_without_layout",
          [p["kind"] for p in sc4.get("problems") or []
           if p.get("kind") == "rooms_without_layout"], [])
    # Red probe: a NORMAL room without a layout still speaks up.
    sc5 = scene_recipe.compose_scene(location(
        [{"id": world.GROUND_ROOM_ID, "name": ""},
         {"id": "__floor__-1", "level": -1, "name": ""},
         room("r9")]))
    check("undrawn room: rooms_without_layout",
          [p["kind"] for p in sc5.get("problems") or []
           if p.get("kind") == "rooms_without_layout"],
          ["rooms_without_layout"])

    print("Part 6d — a drawn boundary is a footprint too")
    sc6 = scene_recipe.compose_scene(boundary_only_fixture())
    check("boundary-only corridors",
          [(c["room_id"], c["level"], c["anchor"]) for c in sc6["corridors"]],
          [("__floor__-1", -1, [-2.0, 2.0])])
    check("boundary is the entry's outline",
          [c["outline"] for c in sc6["corridors"]], [SQUARE])
    check("no corridor_without_floor",
          [p["kind"] for p in sc6.get("problems") or []
           if p.get("kind") == "corridor_without_floor"], [])
    # A boundary is no shell: the contour walls stay outline-only.
    check("no contour walls from a boundary",
          sum(1 for w in sc6["walls"] if not w.get("room_id")), 0)
    # Red probe: no outline AND no boundary -> no plate, no anchor (§ 3.2).
    check("no footprint at all -> no entry",
          scene_recipe.compose_scene(boundary_only_fixture(square=False))
          ["corridors"], [])

    print("Part 7 — count_corridor_doors")
    check("cellar fixture", world.count_corridor_doors(cellar_fixture()), 2)
    opt_in = cellar_fixture()
    opt_in["map3d"] = dict(opt_in["map3d"], ground_corridor=True)
    check("ground floor opts in", world.count_corridor_doors(opt_in), 3)

    def one_cellar_door(**opening):
        """One room on level -1 whose single door carries `opening`."""
        loc = location([rm("k1", -1, -4, -4, 3, 3),
                        {"id": world.GROUND_ROOM_ID, "name": ""}])
        loc["rooms"][0]["layout"]["openings"][0].update(opening)
        return loc

    check("a plain unlinked door counts",
          world.count_corridor_doors(one_cellar_door()), 1)
    check("a linked door does not",
          world.count_corridor_doors(one_cellar_door(to="outside")), 0)
    check("a window does not",
          world.count_corridor_doors(one_cellar_door(type="window")), 0)

    check("corridor_door_rooms names them",
          world.corridor_door_rooms(cellar_fixture()), ["k1", "k2"])

    print("Part 8 — the hull door")
    op = {"edge": 0, "at": 0.5, "width_m": 1.0, "height_m": 2.1,
          "type": "door"}
    # The dropped letter edge is logged for the author; here it is the
    # expected outcome and would only litter the run (as in Part 4b).
    world_log = logging.getLogger("world")
    previous_level = world_log.level
    world_log.setLevel(logging.WARNING)
    try:
        check("hull opening stored",
              _sanitize_map3d({"hull_openings": [op]}).get("hull_openings"),
              [{"edge": 0, "at": 0.5, "width_m": 1.0, "height_m": 2.1,
                "sill_m": 0.0, "type": "door", "level": 0}])
        check("level parsed",
              [o["level"] for o in _sanitize_map3d(
                  {"hull_openings": [dict(op, level="2")]})["hull_openings"]],
              [2])
        check("letter edge dropped",
              "hull_openings" in _sanitize_map3d(
                  {"hull_openings": [dict(op, edge="S")]}), False)
        check("at most eight",
              len(_sanitize_map3d({"hull_openings": [op] * 9})
                  ["hull_openings"]), 8)
    finally:
        world_log.setLevel(previous_level)

    sc6 = scene_recipe.compose_scene(hull_fixture())
    hull_dw = [d for d in sc6["doorways"] if d.get("hull")]
    check("one hull doorway", len(hull_dw), 1)
    h = hull_dw[0] if hull_dw else {}
    check("hull doorway",
          {k: h.get(k) for k in ("level", "at_world", "along",
                                 "outward_normal", "rooms", "outside", "hull",
                                 "type", "width_m", "height_m", "base_y")},
          {"level": 0, "at_world": [0.0, -5.0], "along": [1.0, 0.0],
           "outward_normal": [0.0, -1.0], "rooms": ["__floor__0"],
           "outside": True, "hull": True, "type": "door", "width_m": 1.0,
           "height_m": 2.1, "base_y": 0.0})
    check("no internal key survives", [k for k in h if k.startswith("_")], [])

    south = hull_line(sc6, 0, -5.0)
    north = hull_line(sc6, 0, 5.0)
    check("edge 0 full pieces",
          sorted(piece_len(w) for w in south
                 if not w.get("leaf") and not w.get("lintel")),
          [4.5, 4.5])
    check("edge 2 full pieces",
          sorted(piece_len(w) for w in north
                 if not w.get("leaf") and not w.get("lintel")),
          [2.55, 6.55])
    check("the hull door's lintel",
          [(w["base_y"], w["height"], piece_len(w))
           for w in south if w.get("lintel")], [(2.1, 0.75, 1.0)])
    check("the hull door's leaf",
          [(sorted([w["from"][0], w["to"][0]]), w["base_y"], w["height"])
           for w in south if w.get("leaf")], [([-0.5, 0.5], 0.0, 2.1)])
    check("hull leaves level 0", hull_leaves(sc6, 0), 2)
    check("their centres",
          sorted(round((w["from"][0] + w["to"][0]) / 2, 4)
                 for w in sc6["walls"] if w.get("leaf")
                 and not w.get("room_id") and w["level"] == 0),
          [-2.0, 0.0])
    check("hull leaves level -1", hull_leaves(sc6, -1), 0)

    sc7 = scene_recipe.compose_scene(hull_fixture(levels=(0, 2)))
    check("still one hull doorway",
          len([d for d in sc7["doorways"] if d.get("hull")]), 1)
    check("hull_opening_without_corridor",
          [(p.get("kind"), p.get("level")) for p in sc7.get("problems") or []
           if p.get("kind") == "hull_opening_without_corridor"],
          [("hull_opening_without_corridor", 2)])
    check("the corridor storey is quiet",
          [p["kind"] for p in sc6.get("problems") or []
           if p.get("kind") == "hull_opening_without_corridor"], [])

    # The hull door IS the building entrance: without eg's opening it is the
    # only outside door on level 0 …
    sc8 = scene_recipe.compose_scene(hull_fixture(eg_door=False))
    check("the hull door lets one in",
          [p["kind"] for p in sc8.get("problems") or []
           if p.get("kind") == "no_building_entrance"], [])
    # … and red probe: drop it too and nobody can get in any more.
    sc9 = scene_recipe.compose_scene(hull_fixture(levels=(), eg_door=False))
    check("no door at all: entrance problem",
          [p["kind"] for p in sc9.get("problems") or []
           if p.get("kind") == "no_building_entrance"],
          ["no_building_entrance"])

    sc10 = scene_recipe.compose_scene(hull_fixture(edge=7))
    check("edge 7: no hull doorway",
          [d for d in sc10["doorways"] if d.get("hull")], [])
    check("hull_opening_off_the_outline",
          [(p.get("kind"), p.get("level"), p.get("edge"))
           for p in sc10.get("problems") or []
           if p.get("kind") == "hull_opening_off_the_outline"],
          [("hull_opening_off_the_outline", 0, 7)])

    # The prop library is the ONE accessor the recipe asks (as in
    # smoke_scene_recipe.stub_library) — stubbed, so no world is needed.
    from app.core import props as prop_store
    real_get_prop = prop_store.get_prop
    prop_store.get_prop = lambda pid: {"id": pid, "has_model": False}
    try:
        left = scene_recipe.compose_scene(hull_fixture(prop_id="d1"))
        flip = scene_recipe.compose_scene(
            hull_fixture(prop_id="d1", outline=SQUARE[::-1], edge=2))
    finally:
        prop_store.get_prop = real_get_prop
    check("the clockwise ring keeps the hole and the outward normal",
          [(hull_door(flip)["at_world"], hull_door(flip)["along"],
            hull_door(flip)["outward_normal"])],
          [([0.0, -5.0], [-1.0, 0.0], [0.0, -1.0])])
    check("counter-clockwise: left hinge swings +1",
          [(m["room_id"], m["door"]["hinge"], m["door"]["swing"])
           for m in left["models"] if m.get("door")],
          [("__floor__0", "left", 1)])
    check("clockwise: the other jamb, the other sign",
          [(m["room_id"], m["door"]["hinge"], m["door"]["swing"])
           for m in flip["models"] if m.get("door")],
          [("__floor__0", "left", -1)])
    check("the leaf opens outward on either ring",
          [swing_out(left), swing_out(flip)], [[0.0, -1.0], [0.0, -1.0]])

    print("FAILED" if FAILS else "ALL OK")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
