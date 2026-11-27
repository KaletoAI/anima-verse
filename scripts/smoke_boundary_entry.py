#!/usr/bin/env python3
"""Smoke check: plot gates, building outside doors, and entry/exit gate.

Usage:  ./.venv/bin/python scripts/smoke_boundary_entry.py

Pure functions, no server, no world.db. Expected numbers are derived BY HAND
from the contract (docs/schnittstellen-3d.md § B1 Nr. 13), never recorded from
output.

AN EDGE IS AN INDEX (contract v6 Nr. 5): a plot gate names the 0-based index
of the boundary edge it sits on. A location without a drawn boundary has the
reference square as its effective one, clockwise in map view — with
plan_width_m 10 that is (-5,-5) (5,-5) (5,5) (-5,5), so edge 0 runs
west->east along the north side, 1 north->south on the east side, 2 east->west
on the south side and 3 south->north on the west side.

Part 1 — at_world on that square (Nr. 13), plan_width_m 10:
    edge 1, at 0.25  -> (5, -5 + 0.25*10) = [ 5.0, -2.5], inward [-1, 0]
    edge 0, at 0.30  -> (-5 + 0.30*10, -5) = [-2.0, -5.0], inward [ 0, 1]
    No room_id field on boundary_openings.
    Both normals are (-dz, dx)/|d| verified by the inside probe.
    The CLIENT adds only the pin position (30, -20):
      world(edge-1 opening) = (30 + 5.0, -20 - 2.5) = (35.0, -22.5).

Part 2 — a DRAWN, CONCAVE boundary (v6 Nr. 1/5). The L
    (-5,-5) (5,-5) (5,0) (0,0) (0,5) (-5,5) has edge 2 running
    (5,0) -> (0,0), direction (-5, 0). At `at` 0.5 that is (2.5, 0); the
    candidate normal (-dz, dx)/|d| = (0, -1) probed at (2.5, -0.001) lies
    inside the L, so INWARD is (0, -1) — into the arm, away from the notch.
    An index the outline does not have (edge 9) is dropped, not guessed.

Part 3 — outside_door_frames (yaw 0 & yaw 90), room_at_point, and entry/exit
    gate table (fenced/unfenced x room open/walled x at door/gate or beside),
    plus the no-trap rule (unfenced, zero level-0 outside doors, walled room
    -> leave anywhere).
    Fixture B at (100, 100), boundary +-5 x +-3 (x 95..105, z 97..103), unfenced:
      hall: local x -5..1, z -3..3, south door local (-2, 3), w 1.2, out (0, 1)
        along-limit = 0.6 + 0.3 = 0.9 m, across-limit = 1.5 m
        yaw 0  -> world (98, 103), outward (0, 1)
        yaw 90 -> x = 100 + (-2)*0 + 3*1 = 103, z = 100 - (-2)*1 + 3*0 = 102
                  -> world (103, 102), outward (1, 0)
      kitchen: local x 1..5, z -3..3, east door local (5, 0), w 0.9, out (1, 0)
        along-limit = 0.45 + 0.3 = 0.75 m, across-limit = 1.5 m
        yaw 0  -> world (105, 100), outward (1, 0)
        yaw 90 -> x = 100 + 5*0 + 0*1 = 100, z = 100 - 5*1 + 0*0 = 95
                  -> world (100, 95), outward (0, -1)

    Gate table rows (fenced? | op | room | point | along / across or dist | result):
      unfenced B | enter | hall      | (98, 102.6)   | along 0.0 <= 0.9, across -0.4   -> (True, "", "hall")
      unfenced B | enter | hall      | (99.2, 102.6) | along 1.2 > 0.9,  across -0.4   -> (False, "no_door", "")
      unfenced B | enter | kitchen   | (104.6, 100)  | along 0.0 <= 0.75, across -0.4  -> (True, "", "kitchen")
      unfenced B | leave | kitchen   | (105.8, 100)  | along 0.0 <= 0.75, across 0.8   -> (True, "")
      unfenced B | leave | kitchen   | (105.6, 102.4)| along 2.4 > 0.75,  across 0.6   -> (False, "leave_blocked")
      unfenced B | leave | hall      | (101.0, 104.0)| along 3.0 > 0.9,   across 1.0   -> (False, "leave_blocked")
      unfenced B | leave | __ground__| (101.0, 104.0)| open room, unfenced             -> (True, "")
      fenced F   | enter | __ground__| (300, 81.4)   | dist 1.4 <= 1.5 to gate (300,80)-> (True, "", "__ground__")
      fenced F   | enter | __ground__| (310, 81.0)   | dist 10.05 > 1.5                -> (False, "no_opening", "")
      fenced F   | leave | __ground__| (310, 79.0)   | dist 10.05 > 1.5                -> (False, "leave_blocked")
      fenced F   | leave | __ground__| (300, 79.0)   | dist 1.0 <= 1.5                 -> (True, "")
      fenced F   | leave | lawn(open)| (300, 79.0)   | dist 1.0 <= 1.5                 -> (True, "")
      fenced F   | leave | lawn(open)| (310, 79.0)   | dist 10.05 > 1.5                -> (False, "leave_blocked")
      fenced F   | leave | shed(wall)| (300, 79.0)   | at gate, 0 doors (no-trap)      -> (True, "")
      fenced F   | leave | hall(wall)| (300, 80.0)   | at gate, 0 doors (no-trap)      -> (True, "")
      unfenced 0 | leave | cell(wall)| (0, 0)        | unfenced + 0 doors (no-trap)    -> (True, "")

Part 4 — arrival room (entry_room is only for travel/teleport/scheduler):
    entry_room set and existing -> that room; empty, stale or roomless -> __ground__.

Part 5 — width clamping and room drop in world_ops._sanitize_map3d:
    An opening sits ON a boundary edge, capped at the derived plan_width_m
    (10 m fallback without a drawn boundary). Out-of-range widths clamp rather
    than drop; a submitted `room` key is dropped without keeping an alias.
    Derived by hand:
      40 m square, width 60    -> 40.0   (cap = the edge)
      40 m square, width 25    -> 25.0   (inside the edge, kept as authored)
      40 m square, width 0.2   -> 0.5    (lower bound, still not dropped)
      0.5 m square, width 3    -> 0.5    (cap wins over the lower bound)
      no boundary, width 25    -> 10.0   (no area -> the 10 m fallback)
      no boundary, width 3     -> 3.0    (untouched)
      width "wide"             -> entry dropped (structural reject)
      {"edge": 3, "at": 1.4, "width_m": 60, "room": "road"} on 40 m square
                               -> {"edge": 3, "at": 1.0, "width_m": 40.0,
                                   "type": "passage"} (room dropped)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The storage root and the clip library MUST be redirected BEFORE the first
# app import: app.models.world reaches its world.db through paths, and without
# a storage root every world access raises StorageNotInitialised — there is no
# default world any more, so nothing here can land in the tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="boundary-entry-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="boundary-entry-storage-"))

from app.core import scene_recipe  # noqa: E402
from app.core.boundary_entry import (  # noqa: E402
    at_door, at_gate, entry_geometry, fenced, may_enter, may_leave,
    opening_world_frames, outside_door_frames, room_at_point, room_is_open,
)
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, floor_room_id, get_arrival_room_id,
)

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a, b, eps=1e-6):
    return abs(float(a) - float(b)) <= eps


OPENINGS = [
    {"edge": 1, "at": 0.25, "width_m": 2.0, "type": "passage"},
    {"edge": 0, "at": 0.30, "width_m": 2.0, "type": "passage"},
]

# The concave fixture of Part 2 — the L of the module docstring.
L_BOUNDARY = [[-5.0, -5.0], [5.0, -5.0], [5.0, 0.0],
              [0.0, 0.0], [0.0, 5.0], [-5.0, 5.0]]


def fixture(boundary=None):
    """Minimal composable location: contour + one room with a layout, so
    compose_scene has something to build; the openings are the subject."""
    map3d = {
        "plan_width_m": 10.0,
        "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
        "boundary_openings": [dict(op) for op in OPENINGS],
    }
    if boundary is not None:
        map3d["boundary"] = boundary
    return {
        "id": "loc",
        "map3d": map3d,
        "rooms": [
            {"id": "road", "name": "Road", "layout": {
                "x": -4.0, "y": -4.0, "w": 4.0, "d": 3.0, "level": 0}},
        ],
    }


def fixture_b(yaw_deg=0.0, gates=None):
    map3d = {
        "boundary": [[-5.0, -3.0], [5.0, -3.0], [5.0, 3.0], [-5.0, 3.0]],
        "plan_width_m": 10.0,
    }
    if gates:
        map3d["boundary_openings"] = [dict(g) for g in gates]
    return {
        "id": "b",
        "pos_x": 100.0,
        "pos_z": 100.0,
        "yaw_deg": yaw_deg,
        "entry_room": "hall",
        "map3d": map3d,
        "rooms": [
            {
                "id": "hall",
                "name": "Hall",
                "layout": {
                    "x": -5.0, "y": -3.0, "w": 6.0, "d": 6.0, "level": 0,
                    "openings": [
                        {"edge": "S", "at": 0.5, "width_m": 1.2,
                         "type": "door", "to": "outside"},
                    ],
                },
            },
            {
                "id": "kitchen",
                "name": "Kitchen",
                "layout": {
                    "x": 1.0, "y": -3.0, "w": 4.0, "d": 6.0, "level": 0,
                    "openings": [
                        {"edge": "E", "at": 0.5, "width_m": 0.9,
                         "type": "door", "to": "outside"},
                    ],
                },
            },
        ],
    }


def by_edge(scene):
    return {o["edge"]: o for o in scene.get("boundary_openings") or []}


def main():
    print("Part 1 — at_world on the reference square (plan_width_m 10)")
    plain = by_edge(scene_recipe.compose_scene(fixture(), plan_width_m=10.0))
    e, n = plain.get(1), plain.get(0)
    check("edge-1 opening emitted", e is not None)
    check("edge-0 opening emitted", n is not None)
    if e:
        check("edge 1 at_world = [5.0, -2.5]",
              near(e["at_world"][0], 5.0) and near(e["at_world"][1], -2.5),
              f"got {e['at_world']}")
        check("edge 1 inward = [-1, 0]", e["inward"] == [-1.0, 0.0])
        check("edge 1 carries no room_id", "room_id" not in e, str(e))
        check("client world pos = (35.0, -22.5)",
              near(30 + e["at_world"][0], 35.0) and near(-20 + e["at_world"][1], -22.5))
    if n:
        check("edge 0 at_world = [-2.0, -5.0]",
              near(n["at_world"][0], -2.0) and near(n["at_world"][1], -5.0),
              f"got {n['at_world']}")
        check("edge 0 inward = [0, 1]", n["inward"] == [0.0, 1.0])

    print("Part 2 — a drawn, CONCAVE boundary")
    ell = fixture(L_BOUNDARY)
    ell["map3d"].pop("outline")
    ell["map3d"]["boundary_openings"] = [
        {"edge": 2, "at": 0.5, "width_m": 2.0},
        {"edge": 9, "at": 0.5, "width_m": 2.0},
    ]
    lo = by_edge(scene_recipe.compose_scene(ell, plan_width_m=10.0))
    check("the index the L does not have is dropped", set(lo) == {2},
          str(sorted(lo)))
    if 2 in lo:
        check("edge 2 at 0.5 = [2.5, 0.0]",
              near(lo[2]["at_world"][0], 2.5) and near(lo[2]["at_world"][1], 0.0),
              f"got {lo[2]['at_world']}")
        check("...inward [0, -1] — measured, not guessed from the winding",
              lo[2]["inward"] == [0.0, -1.0], str(lo[2]["inward"]))
        check("no room_id emitted", "room_id" not in lo[2], str(lo[2]))

    print("Part 3 — outside_door_frames (yaw 0 & yaw 90), room_at_point, gate table")
    b0 = fixture_b(yaw_deg=0.0)
    scene_b0 = scene_recipe.compose_scene(b0, plan_width_m=10.0)
    doors_0 = {d["room"]: d for d in outside_door_frames(b0, scene_b0)}
    check("yaw 0 hall door at (98, 103), outward (0, 1), w 1.2",
          doors_0["hall"]["at_world"] == [98.0, 103.0]
          and doors_0["hall"]["outward"] == [0.0, 1.0]
          and doors_0["hall"]["width_m"] == 1.2,
          str(doors_0.get("hall")))
    check("yaw 0 kitchen door at (105, 100), outward (1, 0), w 0.9",
          doors_0["kitchen"]["at_world"] == [105.0, 100.0]
          and doors_0["kitchen"]["outward"] == [1.0, 0.0]
          and doors_0["kitchen"]["width_m"] == 0.9,
          str(doors_0.get("kitchen")))

    b90 = fixture_b(yaw_deg=90.0)
    doors_90 = {d["room"]: d for d in outside_door_frames(b90, scene_b0)}
    check("yaw 90 hall door at (103, 102), outward (1, 0)",
          doors_90["hall"]["at_world"] == [103.0, 102.0]
          and doors_90["hall"]["outward"] == [1.0, 0.0],
          str(doors_90.get("hall")))
    check("yaw 90 kitchen door at (100, 95), outward (0, -1)",
          doors_90["kitchen"]["at_world"] == [100.0, 95.0]
          and doors_90["kitchen"]["outward"] == [0.0, -1.0],
          str(doors_90.get("kitchen")))
    check("outside_door_frames with scene=None -> []",
          outside_door_frames(b0, None) == [])

    # room_at_point: inside hall, between rooms (in contour -> __floor__0), outside -> __ground__
    geo_b0 = entry_geometry(b0, scene_b0)
    check("room_at_point inside hall -> 'hall'",
          room_at_point(geo_b0, 98.0, 100.0) == "hall")
    check("room_at_point inside kitchen -> 'kitchen'",
          room_at_point(geo_b0, 103.0, 100.0) == "kitchen")
    check("room_at_point outside -> __ground__",
          room_at_point(geo_b0, 120.0, 120.0) == GROUND_ROOM_ID)
    geo_gap = {
        "doors": [],
        "rooms": [
            {"room": "left", "outline": [[0, 0], [4, 0], [4, 4], [0, 4]], "walled": True},
            {"room": "right", "outline": [[6, 0], [10, 0], [10, 4], [6, 4]], "walled": True},
        ],
        "contour": [[0, 0], [10, 0], [10, 4], [0, 4]],
    }
    check("room_at_point between rooms inside contour -> __floor__0",
          room_at_point(geo_gap, 5.0, 2.0) == floor_room_id(0))
    check("room_at_point outside contour -> __ground__",
          room_at_point(geo_gap, 5.0, 6.0) == GROUND_ROOM_ID)

    # fenced() and opening_world_frames() without room
    check("unfenced B -> fenced False", fenced(b0) is False)
    check("empty location -> fenced False", fenced({}) is False)
    fenced_plot = {
        "pos_x": 300.0, "pos_z": 100.0, "yaw_deg": 0.0,
        "map3d": {
            "boundary": [[-20, -20], [20, -20], [20, 20], [-20, 20]],
            "boundary_openings": [{"edge": 0, "at": 0.5, "width_m": 3.0}],
        },
        "rooms": [
            {"id": "lawn", "layout": {"no_walls": True}},
            {"id": "shed", "layout": {"level": 0}},
            {"id": GROUND_ROOM_ID},
        ],
    }
    check("fenced plot -> fenced True", fenced(fenced_plot) is True)
    frames = opening_world_frames(fenced_plot)
    check("opening_world_frames drops room key",
          frames == [{"edge": 0, "at_world": [300.0, 80.0], "inward": [0.0, 1.0]}],
          str(frames))
    check("at_gate within 1.5m -> True", at_gate(fenced_plot, 300.0, 81.4) is True)
    check("at_gate 10m away -> False", at_gate(fenced_plot, 310.0, 81.0) is False)

    # Table: unfenced B (walled hall/kitchen with doors)
    check("unfenced B: enter hall at door (98, 102.6) -> ok, 'hall'",
          may_enter(b0, geo_b0, 98.0, 102.6) == (True, "", "hall"))
    check("unfenced B: enter hall beside door (99.2, 102.6) -> no_door",
          may_enter(b0, geo_b0, 99.2, 102.6) == (False, "no_door", ""))
    check("unfenced B: enter kitchen at door (104.6, 100) -> ok, 'kitchen'",
          may_enter(b0, geo_b0, 104.6, 100.0) == (True, "", "kitchen"))
    check("unfenced B: leave kitchen at door (105.8, 100) -> ok",
          may_leave(b0, geo_b0, "kitchen", 105.8, 100.0) == (True, ""))
    check("unfenced B: leave kitchen beside door (105.6, 102.4) -> leave_blocked",
          may_leave(b0, geo_b0, "kitchen", 105.6, 102.4) == (False, "leave_blocked"))
    check("unfenced B: leave hall beside door (101.0, 104.0) -> leave_blocked",
          may_leave(b0, geo_b0, "hall", 101.0, 104.0) == (False, "leave_blocked"))
    check("unfenced B: leave from ground anywhere -> ok",
          may_leave(b0, geo_b0, GROUND_ROOM_ID, 101.0, 104.0) == (True, ""))

    # Table: fenced plot (open ground / open room / walled room)
    empty_geo = {"doors": [], "rooms": [], "contour": []}
    check("fenced plot: enter at gate (300, 81.4) -> ok, __ground__",
          may_enter(fenced_plot, empty_geo, 300.0, 81.4) == (True, "", GROUND_ROOM_ID))
    check("fenced plot: enter beside gate (310, 81) -> no_opening",
          may_enter(fenced_plot, empty_geo, 310.0, 81.0) == (False, "no_opening", ""))
    check("fenced plot: leave from ground beside gate (310, 79) -> leave_blocked",
          may_leave(fenced_plot, empty_geo, GROUND_ROOM_ID, 310.0, 79.0) == (False, "leave_blocked"))
    check("fenced plot: leave from ground at gate (300, 79) -> ok",
          may_leave(fenced_plot, empty_geo, GROUND_ROOM_ID, 300.0, 79.0) == (True, ""))
    check("fenced plot: leave from open room at gate -> ok, beside gate -> blocked",
          may_leave(fenced_plot, empty_geo, "lawn", 300.0, 79.0) == (True, "")
          and may_leave(fenced_plot, empty_geo, "lawn", 310.0, 79.0) == (False, "leave_blocked"))
    check("fenced plot: walled room with 0 doors at gate -> allowed (no-trap at gate)",
          may_leave(fenced_plot, empty_geo, "shed", 300.0, 79.0) == (True, ""))
    fenced_hall = {
        **fenced_plot,
        "entry_room": "hall",
        "rooms": [{"id": "hall"}, {"id": GROUND_ROOM_ID}],
    }
    check("fenced plot: entry_room 'hall' without layout leaving at gate (300, 80) -> allowed",
          may_leave(fenced_hall, empty_geo, "hall", 300.0, 80.0) == (True, ""))
    # Reviewer case: the plot ALSO holds a building with an outside door
    # (geo doors non-empty, so the no-trap rule does not apply); the
    # layout-less 'hall' has no walls to pass -> leaving at the gate is allowed.
    shop_geo = {"doors": [{"at_world": [310.0, 95.0], "outward": [0.0, 1.0],
                           "width_m": 1.0, "room": "shop", "level": 0, "hull": False}],
                "rooms": [], "contour": []}
    fenced_hall_shop = {**fenced_hall, "rooms": fenced_hall["rooms"] + [
        {"id": "shop", "layout": {"x": 5, "y": 10, "w": 4, "d": 4}}]}
    check("fenced plot + shop door: layout-less 'hall' leaving at gate (300, 80) -> allowed",
          may_leave(fenced_hall_shop, shop_geo, "hall", 300.0, 80.0) == (True, ""))
    check("fenced plot + shop door: walled 'shop' leaving at gate away from its door -> leave_blocked",
          may_leave(fenced_hall_shop, shop_geo, "shop", 300.0, 80.0) == (False, "leave_blocked"))
    check("fenced plot: entry_room 'hall' leaving beside gate (310, 80) -> leave_blocked",
          may_leave(fenced_hall, empty_geo, "hall", 310.0, 80.0) == (False, "leave_blocked"))

    # No-trap rule: unfenced, zero level-0 outside doors, walled room -> leave anywhere
    no_trap_loc = {
        "rooms": [{"id": "cell", "layout": {"level": 0}}, {"id": GROUND_ROOM_ID}],
        "entry_room": "other",
    }
    check("no-trap: unfenced, 0 doors, walled room -> leave anywhere",
          may_leave(no_trap_loc, empty_geo, "cell", 0.0, 0.0) == (True, ""))

    # room_is_open checks
    open_loc = {
        "rooms": [{"id": "square"},
                  {"id": "lake", "layout": {"no_walls": True}},
                  {"id": "terrace", "layout": {"always_visible": True}},
                  {"id": "hut", "layout": {"level": 0}},
                  {"id": GROUND_ROOM_ID}],
    }
    check("room_is_open: ground, no_walls, always_visible",
          room_is_open(open_loc, GROUND_ROOM_ID) is True
          and room_is_open(open_loc, "lake") is True
          and room_is_open(open_loc, "terrace") is True)
    check("room_is_open: walled room and unknown room are not open",
          room_is_open(open_loc, "hut") is False
          and room_is_open(open_loc, "kitchen") is False)

    print("Part 4 — where an arrival lands (entry_room is optional)")
    loc = {
        "rooms": [{"id": "road"}, {"id": "clearing"}, {"id": GROUND_ROOM_ID}],
        "entry_room": "clearing",
    }
    check("entry_room set and existing: one arrives there",
          get_arrival_room_id(loc) == "clearing")
    no_entry = {"rooms": [{"id": "road"}, {"id": GROUND_ROOM_ID}]}
    check("no entry_room: one arrives on the ground",
          get_arrival_room_id(no_entry) == GROUND_ROOM_ID,
          get_arrival_room_id(no_entry))
    stale = {"rooms": [{"id": "road"}, {"id": GROUND_ROOM_ID}],
             "entry_room": "torn_down"}
    check("entry_room pointing at no room: the ground, not the first room",
          get_arrival_room_id(stale) == GROUND_ROOM_ID,
          get_arrival_room_id(stale))
    check("a location without rooms: the ground it always has",
          get_arrival_room_id({}) == GROUND_ROOM_ID)

    print("Part 5 — sanitizer width clamping and room drop")
    from app.core.world_ops import _sanitize_map3d  # noqa: E402

    def square(edge_m):
        h = edge_m / 2.0
        return [[-h, -h], [h, -h], [h, h], [-h, h]]

    def widths(edge_m, *raw_widths):
        raw = {"boundary_openings": [
            {"edge": 0, "at": 0.5, "width_m": w} for w in raw_widths]}
        if edge_m is not None:
            raw["boundary"] = square(edge_m)
        return [op["width_m"]
                for op in _sanitize_map3d(raw).get("boundary_openings") or []]

    check("40 m square: a 60 m opening clamps to 40",
          widths(40, 60) == [40.0], widths(40, 60))
    check("40 m square: 25 m survives",
          widths(40, 25) == [25.0], widths(40, 25))
    check("40 m square: 0.2 m clamps up to 0.5",
          widths(40, 0.2) == [0.5], widths(40, 0.2))
    check("0.5 m square: the cap wins over the lower bound",
          widths(0.5, 3) == [0.5], widths(0.5, 3))
    check("no boundary: 25 m clamps to the 10 m fallback",
          widths(None, 25) == [10.0], widths(None, 25))
    check("no boundary: 3 m passes untouched",
          widths(None, 3) == [3.0], widths(None, 3))
    check("a non-numeric width is dropped",
          widths(40, "wide", 3) == [3.0], widths(40, "wide", 3))
    over = _sanitize_map3d({"boundary": square(40), "boundary_openings": [
        {"edge": 3, "at": 1.4, "width_m": 60, "room": "road"}]})
    check("clamping keeps the entry and drops room",
          over["boundary_openings"] == [{"edge": 3, "at": 1.0,
                                         "width_m": 40.0, "type": "passage"}],
          over.get("boundary_openings"))
    lettered = _sanitize_map3d({"boundary": square(40), "boundary_openings": [
        {"edge": "N", "at": 0.5, "width_m": 3}]})
    check("an edge LETTER is dropped by the sanitizer",
          "boundary_openings" not in lettered, str(lettered))
    outside = _sanitize_map3d({"boundary": square(40), "boundary_openings": [
        {"edge": 4, "at": 0.5, "width_m": 3}]})
    check("index 4 on a four-edge square is dropped",
          "boundary_openings" not in outside, str(outside))
    six = _sanitize_map3d({"boundary": [list(p) for p in L_BOUNDARY],
                           "boundary_openings": [
                               {"edge": 4, "at": 0.5, "width_m": 3}]})
    check("on the six-edge L, index 4 is legal",
          [op["edge"] for op in six.get("boundary_openings") or []] == [4],
          str(six.get("boundary_openings")))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
