#!/usr/bin/env python3
"""Smoke check: the ground of a location is a room of its own.

Usage:  ./.venv/bin/python scripts/smoke_ground_room.py

Pure functions, no server, no world.db — the migration itself touches rows and
is therefore not smoke-able; its DECISIONS are, and those are what this checks.
Every expectation below is derived BY HAND from the rules in
development_instructions/plan-grundflaeche.md § 3 / § 9, never recorded from
output.

The rule, in one line: every location owns a room with the reserved id
GROUND_ROOM_ID, and whoever stands in no valid room of their location stands
on it.

Part 1 — which location gets the room (ground_room_action):
    no rooms at all          -> "add"      the ground exists in every location
    rooms of its own         -> "add"      same rule, the ground is extra
    already has the id       -> "present"  report, never overwrite
    a clone (rooms: [])      -> "skip"     it inherits the template's rooms

  "already has the id" is one case, not two: nothing tells this migration
  apart an id it wrote itself on an earlier run from one an author assigned
  by hand. Both mean "do not touch", which is also the idempotency: running
  the decision on its own result must never add a second room.

Part 2 — which character moves (ground_room_target):
    no room                  -> the ground   it stood there all along
    a room of its location   -> stays        ("")
    a room its location does not have -> the ground   it stood nowhere
    already the ground       -> stays        ("")

Part 3 — does the rooms table still carry the old key (rooms_rebuild_needed):
  One reserved id in EVERY location only works when room ids are unique per
  LOCATION, which is what the plan states in § 3. `rooms.id TEXT PRIMARY KEY`
  says something else — one global row per id — so the table has to be
  rebuilt to PRIMARY KEY (location_id, id). The input is the rows of
  `PRAGMA table_info(rooms)`: (cid, name, type, notnull, dflt_value, pk),
  where pk is the 1-based position in the primary key and 0 means "not in it".
    pk on `id` alone                 -> rebuild        the old shape
    pk on `location_id` + `id`       -> no rebuild     already done
    no columns at all                -> no rebuild     no such table

Part 4 — the ground OUTSIDE takes its texture kind from `terrain` (§ 5).
  Two pure functions, one rule each. The library is passed in, so nothing
  here reads a world.

  (a) `surface_textures.resolve_terrain_kind(terrain, known)` — the library
      lookup that used to live in the client (`tiles.ts surfaceKindOf`):
      lowercase + trim, then membership. A miss is '' — never a guess.
        "grass" in {grass, water, floor}  -> "grass"    a hit
        " Grass "                         -> "grass"    normalised first
        "gras" (typo)                     -> ""         a miss stays a miss
        ""                                -> ""         nothing to resolve
        "grass" against an empty library  -> ""         no entries, no kind

  (b) `scene_recipe.level_plate_kind(level, level_floors, ground_kind)` —
      which kind ONE storey plate carries. `level_floors` is the author's
      explicit word and always wins; only storey 0 is the ground outside;
      everything else is the default "floor" (a first-storey plank floor is
      not terrain).
        level 0, {},           ground "grass"  -> "grass"   the ground outside
        level 0, {"0":"road"}, ground "grass"  -> "road"    the author wins
        level 0, {},           ground ""       -> "floor"   nothing resolved
        level 1, {},           ground "grass"  -> "floor"   not the ground
        level 1, {"1":"tiles"},ground "grass"  -> "tiles"   the author wins
        level -1, {},          ground "grass"  -> "floor"   a cellar neither

  (c) The same rule seen at the consumer — `compose_scene` on a fixture with
      an upper storey: plate level 0 carries the terrain kind, plate level 1
      carries "floor", and a location whose terrain misses the library gets
      "floor" on both. The signature moves with the resolved kind, because
      the payload does.

Part 5 — the ground room carries no GEOMETRY (`_sanitize_rooms_layout`,
  § A13a). The ground is the location's open surface: a floor plan on it would
  put GROUND_ROOM_ID into the recipe's rooms and give it walls and doorways.
  Since § A13a it may carry a REDUCED layout — props and markers, positioned
  in location-local metres — so the sanitizer strips the geometry and keeps
  the placements, for the editor and a hand-made API call alike.
    ground WITH a room layout    -> layout gone, the room itself stays
    a normal room, SAME layout   -> layout kept  (proves it is the ID, not the
                                                  layout, that is refused)
    ground without a layout      -> untouched
    ground with geometry + props -> only the props survive
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, ground_room_action, ground_room_target)
from app.core.world_db_schema import rooms_rebuild_needed  # noqa: E402
from app.core.surface_textures import resolve_terrain_kind  # noqa: E402
from app.core import scene_recipe  # noqa: E402
from app.core.world_ops import _sanitize_rooms_layout  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main():
    print("Part 1 — which location gets the ground room")
    roomless = {"id": "loc1", "name": "Clearing", "rooms": []}
    check("a location without rooms needs it",
          ground_room_action(roomless) == "add",
          ground_room_action(roomless))

    with_rooms = {"id": "loc2", "name": "Inn",
                  "rooms": [{"id": "hall", "name": "Hall"},
                            {"id": "cellar", "name": "Cellar"}]}
    check("a location with rooms needs it just as much",
          ground_room_action(with_rooms) == "add",
          ground_room_action(with_rooms))

    already = {"id": "loc3", "name": "Inn",
               "rooms": [{"id": "hall", "name": "Hall"},
                         {"id": GROUND_ROOM_ID, "name": "Market square"}]}
    check("a location that already has it is left alone",
          ground_room_action(already) == "present",
          ground_room_action(already))

    # Technically the same case as above — an author who assigned the
    # reserved id by hand. Report it, never overwrite it.
    occupied = {"id": "loc4", "name": "Cave",
                "rooms": [{"id": GROUND_ROOM_ID, "name": "Back chamber",
                           "layout": {"x": -5, "y": -5, "w": 10, "d": 10}}]}
    check("an author's room on the reserved id is a collision, not a target",
          ground_room_action(occupied) == "present",
          ground_room_action(occupied))

    clone = {"id": "loc5", "template_location_id": "loc2", "rooms": []}
    check("a clone skips it — it inherits the template's rooms",
          ground_room_action(clone) == "skip",
          ground_room_action(clone))

    # Idempotency: apply the decision to the result of a first run.
    migrated = {"id": "loc1", "name": "Clearing",
                "rooms": [{"id": GROUND_ROOM_ID, "name": ""}]}
    check("a second run does not add a second ground room",
          ground_room_action(migrated) == "present",
          ground_room_action(migrated))

    print("Part 2 — which character moves onto the ground")
    room_ids = ["hall", "cellar", GROUND_ROOM_ID]
    check("no room at all -> the ground",
          ground_room_target("", room_ids) == GROUND_ROOM_ID,
          ground_room_target("", room_ids))
    check("a room of its location -> stays",
          ground_room_target("hall", room_ids) == "",
          ground_room_target("hall", room_ids))
    check("a room its location does not have -> the ground",
          ground_room_target("attic", room_ids) == GROUND_ROOM_ID,
          ground_room_target("attic", room_ids))
    check("already on the ground -> stays",
          ground_room_target(GROUND_ROOM_ID, room_ids) == "",
          ground_room_target(GROUND_ROOM_ID, room_ids))

    print("Part 3 — does the rooms table still carry the old key")
    # PRAGMA table_info rows: (cid, name, type, notnull, dflt_value, pk).
    old_shape = [
        (0, "id", "TEXT", 0, None, 1),
        (1, "location_id", "TEXT", 1, None, 0),
        (2, "name", "TEXT", 1, None, 0),
        (3, "meta", "TEXT", 0, "'{}'", 0),
    ]
    check("the id alone as key -> rebuild",
          rooms_rebuild_needed(old_shape) is True)

    new_shape = [
        (0, "id", "TEXT", 1, None, 2),
        (1, "location_id", "TEXT", 1, None, 1),
        (2, "name", "TEXT", 1, None, 0),
        (3, "meta", "TEXT", 0, "'{}'", 0),
    ]
    check("location_id + id as key -> nothing to do",
          rooms_rebuild_needed(new_shape) is False)

    check("no such table -> nothing to do",
          rooms_rebuild_needed([]) is False)

    print("Part 4a — terrain resolved against the surface library")
    library = {"grass", "water", "floor"}
    check("a terrain that names an entry -> that entry",
          resolve_terrain_kind("grass", library) == "grass",
          resolve_terrain_kind("grass", library))
    check("case and blanks are normalised away",
          resolve_terrain_kind(" Grass ", library) == "grass",
          resolve_terrain_kind(" Grass ", library))
    check("a typo names no entry -> ''",
          resolve_terrain_kind("gras", library) == "",
          repr(resolve_terrain_kind("gras", library)))
    check("no terrain -> ''",
          resolve_terrain_kind("", library) == "",
          repr(resolve_terrain_kind("", library)))
    check("an empty library resolves nothing",
          resolve_terrain_kind("grass", set()) == "",
          repr(resolve_terrain_kind("grass", set())))

    print("Part 4b — which kind one storey plate carries")
    plate_kind = scene_recipe.level_plate_kind
    check("storey 0 without an entry -> the ground outside",
          plate_kind(0, {}, "grass") == "grass",
          plate_kind(0, {}, "grass"))
    check("level_floors beats terrain on its own storey",
          plate_kind(0, {"0": "road"}, "grass") == "road",
          plate_kind(0, {"0": "road"}, "grass"))
    check("storey 0 with nothing resolved -> the default",
          plate_kind(0, {}, "") == "floor",
          plate_kind(0, {}, ""))
    check("storey 1 is no terrain -> the default",
          plate_kind(1, {}, "grass") == "floor",
          plate_kind(1, {}, "grass"))
    check("storey 1 keeps its own level_floors entry",
          plate_kind(1, {"1": "tiles"}, "grass") == "tiles",
          plate_kind(1, {"1": "tiles"}, "grass"))
    check("a cellar is no terrain either",
          plate_kind(-1, {}, "grass") == "floor",
          plate_kind(-1, {}, "grass"))

    print("Part 4c — the same rule in the scene payload")

    def ground_fixture(terrain):
        return {
            "id": "loc", "terrain": terrain,
            "map3d": {"plan_width_m": 20.0,
                      "outline": [[0, 0], [1, 0], [1, 1], [0, 1]]},
            "rooms": [
                {"id": "a", "name": "A", "layout": {
                    "x": -8.0, "y": -8.0, "w": 8.0, "d": 6.0, "level": 0}},
                {"id": "b", "name": "B", "layout": {
                    "x": -8.0, "y": -8.0, "w": 8.0, "d": 6.0, "level": 1}},
            ],
        }

    def level_kinds(terrain, known=("grass", "floor")):
        sc = scene_recipe.compose_scene(ground_fixture(terrain),
                                        plan_width_m=20.0,
                                        surface_kinds=set(known))
        return {p["level"]: p.get("texture_kind") for p in sc["plates"]
                if "room_id" not in p}, sc["signature"]

    # "EIN BODEN" E5a: STOREY 0 HAS NO LEVEL PLATE ANY MORE. The rule above is
    # unchanged and still answers "grass" for level 0 (Part 4b measures it
    # directly) — it simply has no plate left to paint there, because the floor
    # of the terrain storey IS the terrain: its height is `h_final` and its
    # material is the layer bake. What the payload still carries is the plate of
    # every DECLARED storey, which is level 1 here.
    hit, sig_hit = level_kinds("grass")
    check("the ground storey draws no plate at all",
          0 not in hit, str(hit))
    check("the storey above it stays 'floor'",
          hit.get(1) == "floor", str(hit))
    miss, sig_miss = level_kinds("gras")
    check("a terrain that misses the library changes no plate",
          0 not in miss and miss.get(1) == "floor", str(miss))
    check("the signature follows the resolved kind",
          sig_hit != sig_miss, f"{sig_hit[:8]} vs {sig_miss[:8]}")
    without, _ = level_kinds("grass", known=())
    check("no library, no terrain kind — and still no ground plate",
          0 not in without and without.get(1) == "floor", str(without))

    print("Part 5 — the ground room carries no GEOMETRY (§ A13a)")
    # ONE valid layout, handed to both rooms: everything but the id is equal,
    # so only the id can explain the different outcome.
    plan = {"x": -8.0, "y": -6.0, "w": 6.0, "d": 8.0, "level": 0}
    rooms = _sanitize_rooms_layout([
        {"id": GROUND_ROOM_ID, "name": "Market square", "layout": dict(plan)},
        {"id": "hall", "name": "Hall", "layout": dict(plan)},
        {"id": GROUND_ROOM_ID, "name": "Yard"},
        {"id": GROUND_ROOM_ID, "name": "Court", "layout": dict(
            plan, props=[{"prop_id": "bench", "id": "b1", "at": [3.0, -2.0]}])},
    ])
    check("a geometry-only layout on the ground is dropped whole",
          "layout" not in rooms[0], str(rooms[0]))
    check("the ground room itself survives",
          rooms[0].get("id") == GROUND_ROOM_ID and rooms[0].get("name"),
          str(rooms[0]))
    check("the very same layout on a normal room is kept",
          isinstance(rooms[1].get("layout"), dict)
          and rooms[1]["layout"]["w"] == 6.0, str(rooms[1].get("layout")))
    check("a ground room without a layout is untouched",
          rooms[2] == {"id": GROUND_ROOM_ID, "name": "Yard"}, str(rooms[2]))
    # The yard (§ A13a): the placements stay, the room geometry around them
    # is stripped — `at` is a LOCATION-local metre and needs no min corner.
    check("a yard keeps its placements and loses the rest",
          rooms[3].get("layout") == {"props": [{"prop_id": "bench", "id": "b1",
                                                "at": [3.0, -2.0]}]},
          str(rooms[3].get("layout")))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
