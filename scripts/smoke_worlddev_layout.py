#!/usr/bin/env python3
"""Smoke run for LLM room layouts ("Prop-Welt statt Dioramen", stage 3).

Throwaway storage, throwaway world DB. Every number below is derived BY HAND
from the metric room contract (`docs/schnittstellen-3d.md`, v6 preamble Nr. 2
and Nr. 9) — none of it is a recording of what the implementation happened to
print.

THE SEED — one location, hand-built:

    "Tavern", plot outline (map3d.boundary) in LOCATION-LOCAL metres:

        [(-6,-4), (6,-4), (6,4), (0,4), (0,8), (-6,8)]

    An L: the big hall [-6,6] x [-4,4] plus a left arm [-6,0] x [4,8].
    Shoelace sum 48+48+24+0+48+72 = 240, so the signed area is +120 m^2 —
    already CLOCKWISE in map view (positive sum, x east / y south), which is
    the one winding `_sanitize_map3d` stores, so the sanitizer leaves the
    point order alone. Bounding box 12 x 12 -> plan_width_m = 12.
    Six points = SIX EDGES: edge 0 = (-6,-4)->(6,-4) (the north side),
    edge 1 = (6,-4)->(6,4), edge 2 = (6,4)->(0,4), edge 3 = (0,4)->(0,8),
    edge 4 = (0,8)->(-6,8), edge 5 = (-6,8)->(-6,-4).

    Two rooms exist: "Taproom" and "Kitchen", neither with a plan yet.

THE DRAFT — hand-built as an LLM would emit it, and the hand expectations:

  [1] The 4 x 3 room at (-2, 1). Taproom: x -2, y 1, w 4, d 3 -> it covers
      x in [-2, 2], y in [1, 4]. Every probe (4 corners + 4 edge midpoints)
      lies inside the plot or exactly on its edge: (2,4) sits ON edge 2
      (the segment y = 4, x in [0,6]), (0,4) IS the vertex between edges 2
      and 3, and (-2,4) is interior because the left arm continues to y = 8.
      `polygon_distance` is 0 anywhere inside including the edges, so NO
      room_outside_boundary. The layout survives the sanitizer verbatim:
      x -2.0, y 1.0, w 4.0, d 3.0, level 0.

  [2] Openings get the building defaults the schema promises. The Taproom's
      door {"edge": 1, "at": 0.5, "width_m": 0.9, "type": "door"} carries no
      height at all; `OPENING_DEFAULTS["door"]` is (2.1, 0.0), so it comes out
      as height_m 2.1, sill_m 0.0 — WITHOUT that fill-in the sanitizer would
      refuse it (height_m is mandatory there) and the plan would silently lose
      its only way in. Its `to` is "kitchen-id", a real room -> no warning.
      A second opening on edge 9 is refused by the sanitizer (a room with no
      outline has exactly 4 edges) -> ONE opening left, and one
      `opening_dropped` warning. A third one, on edge 2 with to "ghost",
      survives as a plain hole and raises `unknown_opening_target`.

  [3] Surfaces are checked against the library that is handed IN (the function
      is pure). Library = {"wood_planks", "plaster"}; the Taproom asks for
      floor "wood_planks" (kept) and wall "marble_hall" (not in the library)
      -> surfaces == {"floor": "wood_planks"} plus one `unknown_surface`.

  [4] A room sticking out WARNS, it is not rejected. "Cellar Store" at
      x 3, y 2, w 4, d 4 covers x in [3,7], y in [2,6]. Its corner (7,2) lies
      1 m east of the plot's widest point (x = 6) -> distance 1 m > the 0.01 m
      tolerance -> `room_outside_boundary`. It is STILL in `normalized.rooms`
      and STILL written by the apply — that is the whole point of the warning
      system.

  [5] Two rooms sharing floor warn, two rooms sharing a WALL do not.
      "Pantry" (new, no id) at x 1, y 1, w 1.5, d 2 covers x in [1, 2.5],
      y in [1, 3].
        vs Taproom [-2,2] x [1,4]:  overlap_x = min(2, 2.5) - max(-2, 1)
                                              = 2 - 1   = 1 m    > 0.01
                                    overlap_y = min(4, 3) - max(1, 1)
                                              = 3 - 1   = 2 m    > 0.01
                                    -> `room_overlap`
        vs Cellar Store [3,7] x [2,6]: overlap_x = min(2.5, 7) - max(1, 3)
                                              = 2.5 - 3 = -0.5 m -> no finding
      And directly on the predicate: a room at x 2, y 1, w 2, d 3 shares the
      wall x = 2 with the Taproom -> overlap_x = min(2,4) - max(-2,2) = 0,
      which is NOT greater than the tolerance -> False. Neighbouring rooms are
      made of shared walls; a warning there would fire on every real plan.
      The Pantry is inside the plot ([1,2.5] x [1,3] sits in the big hall),
      so it contributes exactly one finding and no boundary complaint. The
      finding names BOTH rooms by ID — a room the plan creates gets its id up
      front, so every warning points at a shape the preview can actually draw.

  [6] An unknown room id is an ERROR ENTRY, not a silent create. A fourth
      draft room with id "r-nope" -> one `unknown_room` warning and the entry
      is DROPPED (a guessed id would otherwise overwrite the wrong room).
      Same for the reserved ground id `__ground__`.

  [7] boundary_openings ride the map3d whitelist. {"edge": 0, "at": 0.5,
      "width_m": 3} -> kept as {"edge": 0, "at": 0.5, "width_m": 3.0,
      "type": "passage"}; the width clamp is the plot's own 12 m, so 3 passes
      untouched. {"edge": 9, ...} names an edge the 6-point outline does not
      have -> dropped, one `boundary_opening_dropped`. Counted from the ONE
      list: 2 sent, 1 kept, so exactly 1 lost.

 [7b] STAIRCASES ride the very same whitelist — one flight per STOREY JUMP,
      and the plan hands them to `world_ops._sanitize_map3d` exactly as it
      hands over the boundary openings, so there is no second rule set to
      disagree with.
      {"at": [-5, -3], "from_level": 0, "dir_deg": 90} is legal on all three
      counts — two finite metres, an integer storey, and a direction that IS
      one of the four quarter turns — so it survives verbatim, with `at` at
      the centimetre every plan coordinate is stored at: [-5.0, -3.0].
      Where that puts it, by hand: the plot's big hall is x in [-6, 6],
      y in [-4, 4]; dir 90 climbs east (+x). The seed's storey_height_m is
      3.0, so the climb is 1*3.0 + 0.08 = 3.08 m (the upper floor datum,
      `scene_recipe.storey_floor_y`), 3.08 / 0.20 = 15.4 -> 15 steps, and
      15 * 0.26 = 3.90 m of run. The flight therefore covers x in
      [-5, -1.1] and, 1.2 m wide across the climb, y in [-3.6, -2.4]:
      inside the hall and clear of every room of this draft (the Taproom
      starts at y = 1, the Pantry at y = 1, the Kitchen at y = 2).
      {"at": [0, 0], "from_level": 0, "dir_deg": 45} is NOT one of the four
      turns -> DROPPED, not turned to the nearest one, and reported once as
      `stair_dropped`. Counted from the ONE list, like the boundary
      openings: 2 sent, 1 kept, so exactly 1 lost.
      `layout_counts` therefore says stairs 1 — a dialog that does not name
      them would let a storey connection through unread — the apply writes
      the surviving flight into `map3d.stairs`, and the restore takes it
      away again with the rest of the plan.

  [8] entry_room. "Taproom" is given by NAME; it resolves to the Taproom's id.
      A draft naming "nowhere" instead keeps the location's entry room as it
      was and raises `unknown_entry_room`.

  [9] The apply writes through `update_location_with_extras` — the writer
      behind `PUT /world/locations/{id}`, i.e. the floor-plan editor's own save
      path. Afterwards: the Taproom carries the metric layout of [1], the
      Cellar Store the one of [4] (warned, written), the Pantry EXISTS as a
      new room with a generated id, the Kitchen — which the plan never
      mentioned — still has its description and no layout at all, and
      entry_room is the Taproom's id. `map3d.boundary_openings` holds the one
      surviving entry, `map3d.boundary` is untouched.

 [10] Snapshot / restore round trip. The snapshot is taken BEFORE the apply,
      so restoring it must undo all of it: the Pantry is gone again (the room
      list is replaced, not merged), the Taproom has no layout, entry_room is
      empty, and map3d carries no boundary_openings — while the boundary and
      the room count of the seed are back exactly as they were.

 [11] Junk still raises. A draft that is not an object, and one with no rooms
      at all, raise ValueError (the route turns those into a 400); an apply
      naming a location that does not exist raises too, and a snapshot id with
      a path traversal in it never opens a file.

Usage:  ./.venv/bin/python scripts/smoke_worlddev_layout.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="layout-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="layout-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import layout_apply as la  # noqa: E402
from app.core.world_ops import update_location_with_extras  # noqa: E402
from app.models import world  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, actual):
    check(label, bool(actual), True)


def raises_value_error(label, fn):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except ValueError as e:
        print(f"  OK  {label}: ValueError({str(e)[:70]!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  FAIL {label}: {type(e).__name__}({e}) — expected ValueError")
        FAILURES.append(label)
        return
    print(f"  FAIL {label}: no exception — expected ValueError")
    FAILURES.append(label)


def codes(warnings):
    return sorted(w["code"] for w in warnings)


def code_count(warnings, code):
    return sum(1 for w in warnings if w["code"] == code)


# ── the seed ────────────────────────────────────────────────────────────────
BOUNDARY = [[-6, -4], [6, -4], [6, 4], [0, 4], [0, 8], [-6, 8]]
LIBRARY = ["wood_planks", "plaster"]

loc = world.add_location(
    "Tavern", "A low timber house at the crossroads.",
    rooms=[{"name": "Taproom", "description": "Long tables, a big hearth."},
           {"name": "Kitchen", "description": "Soot, copper pots, heat."}])
LOC_ID = loc["id"]
update_location_with_extras(LOC_ID, {"map3d": {"boundary": BOUNDARY,
                                               "storey_height_m": 3.0}})
loc = world.get_location_by_id(LOC_ID)
ROOMS = {r["name"]: r["id"] for r in loc["rooms"] if r.get("name")}
TAPROOM, KITCHEN = ROOMS["Taproom"], ROOMS["Kitchen"]

print("[0] the seed")
check("boundary stored unreversed (already clockwise)",
      loc["map3d"]["boundary"],
      [[-6.0, -4.0], [6.0, -4.0], [6.0, 4.0], [0.0, 4.0], [0.0, 8.0],
       [-6.0, 8.0]])
check("plan_width_m is the 12 m bounding box", loc["map3d"]["plan_width_m"],
      12.0)
check("no room has a plan yet",
      [r.get("layout") for r in loc["rooms"] if r["id"] in (TAPROOM, KITCHEN)],
      [None, None])

DRAFT = {
    "summary": "Taproom to the west, cellar store east, pantry squeezed in.",
    "entry_room": "Taproom",
    "rooms": [
        {"id": TAPROOM, "x": -2, "y": 1, "w": 4, "d": 3, "level": 0,
         "surfaces": {"floor": "wood_planks", "wall": "marble_hall"},
         "openings": [
             {"edge": 1, "at": 0.5, "width_m": 0.9, "type": "door",
              "to": KITCHEN},
             {"edge": 9, "at": 0.5, "width_m": 0.9, "type": "door"},
             {"edge": 2, "at": 0.25, "width_m": 0.9, "type": "door",
              "to": "ghost"},
         ]},
        {"id": KITCHEN, "x": 3, "y": 2, "w": 4, "d": 4, "level": 0,
         "name": "", "openings": []},
        {"name": "Pantry", "description": "Shelves, cool and dim.",
         "x": 1, "y": 1, "w": 1.5, "d": 2, "level": 0},
        {"id": "r-nope", "x": 0, "y": 0, "w": 3, "d": 3},
        {"id": "__ground__", "x": 0, "y": 0, "w": 3, "d": 3},
    ],
    "boundary_openings": [
        {"edge": 0, "at": 0.5, "width_m": 3, "room": TAPROOM},
        {"edge": 9, "at": 0.5, "width_m": 3},
    ],
    "stairs": [
        {"at": [-5, -3], "from_level": 0, "dir_deg": 90},
        {"at": [0, 0], "from_level": 0, "dir_deg": 45},
    ],
}
# The "Cellar Store" of the hand derivation IS the Kitchen entry above — the
# seed's second room, moved to (3, 2) so it sticks out. Naming it in the plan
# keeps the test on ONE existing-room path instead of inventing a second.
NORM, WARN = la.sanitize_layout(DRAFT, location=loc, surface_kinds=LIBRARY)


def entry_of(room_id):
    return next(e for e in NORM["rooms"] if e["room_id"] == room_id)


print("[1] the 4 x 3 room at (-2, 1)")
TAP = entry_of(TAPROOM)
check("metric rectangle",
      (TAP["layout"]["x"], TAP["layout"]["y"], TAP["layout"]["w"],
       TAP["layout"]["d"]), (-2.0, 1.0, 4.0, 3.0))
check("level", TAP["layout"]["level"], 0)
check("no outline was invented", "outline" in TAP["layout"], False)
check("the room is inside the L — no boundary finding for it",
      [w for w in WARN
       if w["code"] == "room_outside_boundary" and w["ref"] == TAPROOM], [])
check("the world-frame shell is the plain rectangle",
      la.room_outline_local(TAP["layout"]),
      [[-2.0, 1.0], [2.0, 1.0], [2.0, 4.0], [-2.0, 4.0]])

print("[2] openings — building defaults, refusals, dangling targets")
check("two of the three openings survive",
      len(TAP["layout"]["openings"]), 2)
check("the door got height 2.1 / sill 0 from OPENING_DEFAULTS",
      TAP["layout"]["openings"][0],
      {"edge": 1, "at": 0.5, "width_m": 0.9, "height_m": 2.1, "sill_m": 0.0,
       "type": "door", "to": KITCHEN})
check("edge 9 on a rectangle was dropped",
      code_count(WARN, "opening_dropped"), 1)
check("the door to 'ghost' is kept and reported once",
      (code_count(WARN, "unknown_opening_target"),
       TAP["layout"]["openings"][1]["to"]), (1, "ghost"))

print("[3] surfaces against the handed-in library")
check("only the known kind survives", TAP["layout"]["surfaces"],
      {"floor": "wood_planks"})
check("and it is reported", code_count(WARN, "unknown_surface"), 1)

print("[4] a room sticking out warns, it is not rejected")
CELLAR = entry_of(KITCHEN)
check("it is still in the plan",
      (CELLAR["layout"]["x"], CELLAR["layout"]["y"], CELLAR["layout"]["w"],
       CELLAR["layout"]["d"]), (3.0, 2.0, 4.0, 4.0))
check("with exactly one boundary finding, on it",
      [w["ref"] for w in WARN if w["code"] == "room_outside_boundary"],
      [KITCHEN])

print("[5] overlap — shared floor warns, a shared wall does not")
PANTRY_DRAFT_ID = next(e["room_id"] for e in NORM["rooms"]
                       if e["name"] == "Pantry")
check("one overlap finding", code_count(WARN, "room_overlap"), 1)
check("between the Taproom and the Pantry — by ID on both sides, because a "
      "new room gets its id up front",
      sorted(next(w["ref"] for w in WARN
                  if w["code"] == "room_overlap").split("|")),
      sorted([TAPROOM, PANTRY_DRAFT_ID]))
check("a shared wall at x = 2 is not an overlap",
      la.rooms_overlap({"x": -2, "y": 1, "w": 4, "d": 3},
                       {"x": 2, "y": 1, "w": 2, "d": 3}), False)
check("1 m of shared floor is",
      la.rooms_overlap({"x": -2, "y": 1, "w": 4, "d": 3},
                       {"x": 1, "y": 1, "w": 1.5, "d": 2}), True)
check("different levels never overlap",
      code_count([w for w in WARN if w["code"] == "room_overlap"
                  and "Kitchen" in w["ref"]], "room_overlap"), 0)

print("[6] unknown / reserved room ids are dropped entries")
check("two entries were refused",
      code_count(WARN, "unknown_room"), 2)
check("and neither reached the plan",
      sorted(e["room_id"] for e in NORM["rooms"]),
      sorted([TAPROOM, KITCHEN, PANTRY_DRAFT_ID]))
check("the Pantry is flagged new",
      next(e["is_new"] for e in NORM["rooms"] if e["name"] == "Pantry"), True)

print("[7] boundary openings ride the map3d whitelist")
check("one survives, unclamped", NORM["boundary_openings"],
      [{"edge": 0, "at": 0.5, "width_m": 3.0, "type": "passage",
        "room": TAPROOM}])
check("the other is reported",
      code_count(WARN, "boundary_opening_dropped"), 1)

print("[7b] staircases ride the same whitelist")
check("the legal flight survives verbatim", NORM["stairs"],
      [{"at": [-5.0, -3.0], "from_level": 0, "dir_deg": 90}])
check("dir_deg 45 is dropped, not turned to the nearest quarter",
      code_count(WARN, "stair_dropped"), 1)
check("the location's storey height rides along, so a preview can draw the "
      "flight at its true 3.90 m", NORM["storey_height_m"], 3.0)

print("[8] entry room by name")
check("resolved to the id", NORM["entry_room"], TAPROOM)
_N2, _W2 = la.sanitize_layout({**DRAFT, "entry_room": "nowhere"},
                              location=loc, surface_kinds=LIBRARY)
check("an unknown one is dropped and reported",
      (_N2["entry_room"], code_count(_W2, "unknown_entry_room")), ("", 1))

print("[8b] the whole warning vocabulary of this draft")
check("codes", codes(WARN),
      ["boundary_opening_dropped", "opening_dropped", "room_outside_boundary",
       "room_overlap", "stair_dropped", "unknown_opening_target",
       "unknown_room", "unknown_room", "unknown_surface"])
check("counts", la.layout_counts(NORM),
      {"rooms": 3, "new_rooms": 1, "openings": 2, "boundary_openings": 1,
       "stairs": 1})

print("[9] the apply writes through the editor's own save path")
SNAP = la.layout_snapshot(LOC_ID)
APPLIED = la.apply_layout(NORM)
check("two existing rooms updated", sorted(APPLIED["updated"]),
      sorted([TAPROOM, KITCHEN]))
check("one room created", len(APPLIED["created"]), 1)
after = world.get_location_by_id(LOC_ID)
rooms_after = {r["id"]: r for r in after["rooms"]}
check("the Taproom carries the metric layout",
      {k: rooms_after[TAPROOM]["layout"][k] for k in ("x", "y", "w", "d")},
      {"x": -2.0, "y": 1.0, "w": 4.0, "d": 3.0})
check("the warned room was written anyway",
      {k: rooms_after[KITCHEN]["layout"][k] for k in ("x", "y", "w", "d")},
      {"x": 3.0, "y": 2.0, "w": 4.0, "d": 4.0})
PANTRY_ID = APPLIED["created"][0]
check("the Pantry exists with its description",
      (rooms_after[PANTRY_ID]["name"],
       rooms_after[PANTRY_ID]["description"]),
      ("Pantry", "Shelves, cool and dim."))
check("entry_room points at the Taproom", after.get("entry_room"), TAPROOM)
check("the boundary opening landed", after["map3d"].get("boundary_openings"),
      [{"edge": 0, "at": 0.5, "width_m": 3.0, "type": "passage",
        "room": TAPROOM}])
# Both plan-authored map3d keys in ONE write: written separately, the second
# copy of the stored map3d would drop the first one's field.
check("and so did the flight, beside it",
      after["map3d"].get("stairs"),
      [{"at": [-5.0, -3.0], "from_level": 0, "dir_deg": 90}])
check("the plot outline is untouched", after["map3d"]["boundary"],
      loc["map3d"]["boundary"])
check("the storey height the seed set is untouched too",
      after["map3d"].get("storey_height_m"), 3.0)

print("[9b] a room the plan never mentioned keeps everything")
loc2 = world.add_location("Barn", "A barn.",
                          rooms=[{"name": "Threshing floor",
                                  "description": "Dust and straw."},
                                 {"name": "Loft", "description": "Hay."}])
update_location_with_extras(loc2["id"], {"map3d": {"boundary": BOUNDARY}})
loc2 = world.get_location_by_id(loc2["id"])
B_ROOMS = {r["name"]: r["id"] for r in loc2["rooms"] if r.get("name")}
N3, _ = la.sanitize_layout(
    {"rooms": [{"id": B_ROOMS["Threshing floor"], "x": -4, "y": -2,
                "w": 6, "d": 5}]},
    location=loc2, surface_kinds=LIBRARY)
la.apply_layout(N3)
loc2_after = world.get_location_by_id(loc2["id"])
loft = next(r for r in loc2_after["rooms"] if r["id"] == B_ROOMS["Loft"])
check("the untouched room keeps its description and has no plan",
      (loft["description"], loft.get("layout")), ("Hay.", None))

print("[10] snapshot / restore round trip")
RESTORED = la.restore_layout_snapshot(SNAP)
check("restore report", RESTORED,
      {"location_id": LOC_ID, "rooms": len(loc["rooms"]), "entry_room": ""})
back = world.get_location_by_id(LOC_ID)
check("the Pantry is gone again",
      [r["id"] for r in back["rooms"] if r["id"] == PANTRY_ID], [])
check("the Taproom has no plan again",
      next(r for r in back["rooms"] if r["id"] == TAPROOM).get("layout"), None)
check("entry_room is empty again", back.get("entry_room", ""), "")
check("map3d carries no boundary openings again",
      back["map3d"].get("boundary_openings"), None)
check("and no staircase again", back["map3d"].get("stairs"), None)
check("the plot outline survived the round trip", back["map3d"]["boundary"],
      loc["map3d"]["boundary"])
check("the snapshot list names the location",
      [(s["location_id"], s["rooms"]) for s in la.list_layout_snapshots(LOC_ID)],
      [(LOC_ID, len(loc["rooms"]))])
check("filtering by another location yields nothing",
      la.list_layout_snapshots("no-such-location"), [])

print("[11] junk still raises")
raises_value_error("a draft that is not an object",
                   lambda: la.sanitize_layout([1, 2, 3], location=loc))
raises_value_error("a draft with no rooms",
                   lambda: la.sanitize_layout({"summary": "x", "rooms": []},
                                              location=loc))
raises_value_error("an apply for a location that is gone",
                   lambda: la.apply_layout({**NORM,
                                            "location_id": "no-such-id"}))
raises_value_error("a traversing snapshot id",
                   lambda: la.restore_layout_snapshot("../../etc/passwd"))
raises_value_error("an unknown snapshot id",
                   lambda: la.restore_layout_snapshot("nope"))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
