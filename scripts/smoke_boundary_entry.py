#!/usr/bin/env python3
"""Smoke check: boundary openings — payload transform + entry gate (Etappe 3).

Usage:  ./.venv/bin/python scripts/smoke_boundary_entry.py

Pure functions, no server, no world.db. Like every smoke here, the expected
numbers are derived BY HAND from the contract (docs/schnittstellen-3d.md
§ B1 Nr. 13 + Nr. 15), never recorded from output.

Part 1 — at_world transform (Nr. 13), extent 10 (the default tile):
    _w(f) = (f - 0.5) * 10
    edge E, at 0.25  → point (1.0, 0.25) → at_world [ 5.0, -2.5], inward [-1, 0]
    edge N, at 0.30  → point (0.3, 0.0)  → at_world [-2.0, -5.0], inward [ 0, 1]
  The CLIENT adds only the tile centre (grid (3,-2) → centre (30, -20)):
    world(E-opening) = (30 + 5.0, -20 - 2.5) = (35.0, -22.5) — no other maths.

Part 2 — tile_rotation 90° CW (Nr. 15, "Rand-Öffnungen"):
    letters N→E→S→W; `at` flips on E and W (rotateOpeningCW).
    E at 0.25 → flip → S at 0.75 → point (0.75, 1.0) → at_world [ 2.5,  5.0];
      inward (x,z)→(−z,x): (-1,0) → (0,-1)  (= S's own inward: consistent).
    N at 0.30 → no flip → E at 0.30 → point (1.0, 0.3) → at_world [ 5.0, -2.0];
      inward (0,1) → (-1,0)          (= E's own inward).

Part 3 — entry gate (app/core/boundary_entry.py; wired into
    world_ops.move_avatar_step). A step "north" exits the current location's
    N edge and enters the target's S edge (EDGE_OF_DIRECTION / OPPOSITE_EDGE).
    Entering across an edge with an authored opening routes into the linked
    room (fallback entry_room); leaving across it is allowed from the linked
    room. Everything else keeps the entry_room gate.
    Since plan-grundflaeche.md the ground is a ROOM, so an opening without a
    room link leads onto the ground room — and whoever stands there may walk
    back out through it. Nobody is roomless any more.

Part 4 — where an arrival lands (plan-grundflaeche.md § 6, ``entry_room``
    is optional): entry_room set and existing → that room; entry_room empty,
    stale or the location roomless → the ground room; an opening WITH a room
    link beats both (it already says where one arrives).

Part 5 — the width of a pass-through (world_ops._sanitize_map3d, user test
    2026-08-04). An opening lies ON the location edge, and the reference
    square is a square: the edge is ``plan_width_m`` long, so THAT is the
    widest an opening can be. Without the anchor there is no known edge and
    10 m stands in. An out-of-range width is CLAMPED, never dropped — the
    author drags the bar wider, saves, and must not find the opening gone.
    Derived by hand:
      plan_width_m 40, width 60   → 40.0   (cap = the edge)
      plan_width_m 40, width 25   → 25.0   (inside the edge, kept as authored)
      plan_width_m 40, width 0.2  → 0.5    (lower bound, still not dropped)
      plan_width_m 0.5, width 3   → 0.5    (cap wins over the lower bound)
      no plan_width_m, width 25   → 10.0   (no anchor → the 10 m fallback)
      no plan_width_m, width 3    → 3.0    (untouched)
      width "wide" (not a number) → entry dropped (a structural reject, as
                                    before: there is nothing to clamp)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import scene_recipe  # noqa: E402
from app.core.boundary_entry import (  # noqa: E402
    EDGE_OF_DIRECTION, OPPOSITE_EDGE, has_entrance, may_leave,
    opening_entry_room, opening_on_edge,
)
from app.models.world import GROUND_ROOM_ID, get_arrival_room_id  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a, b, eps=1e-6):
    return abs(float(a) - float(b)) <= eps


OPENINGS = [
    {"edge": "E", "at": 0.25, "width_m": 2.0, "type": "passage", "room": "road"},
    {"edge": "N", "at": 0.30, "width_m": 2.0, "type": "passage"},
]


def fixture(tile_rotation=None):
    """Minimal composable location: contour + one room with a layout, so
    compose_scene has something to build; the openings are the subject."""
    map3d = {
        "plan_width_m": 10.0,
        "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
        "boundary_openings": [dict(op) for op in OPENINGS],
    }
    if tile_rotation:
        map3d["tile_rotation"] = tile_rotation
    return {
        "id": "loc",
        "map3d": map3d,
        "rooms": [
            {"id": "road", "name": "Road", "layout": {
                "x": 0.1, "y": 0.1, "w": 0.4, "d": 0.3, "level": 0}},
        ],
    }


def by_edge(scene):
    return {o["edge"]: o for o in scene.get("boundary_openings") or []}


def main():
    print("Part 1 — at_world unrotated (extent 10)")
    plain = by_edge(scene_recipe.compose_scene(fixture(), plan_width_m=10.0))
    e, n = plain.get("E"), plain.get("N")
    check("E opening emitted", e is not None)
    check("N opening emitted", n is not None)
    if e:
        check("E at_world = [5.0, -2.5]",
              near(e["at_world"][0], 5.0) and near(e["at_world"][1], -2.5),
              f"got {e['at_world']}")
        check("E inward = [-1, 0]", e["inward"] == [-1, 0])
        check("E room link passes through", e.get("room_id") == "road")
        # The client's whole transform: tile centre (grid 3,-2 → 30,-20) + at_world.
        check("client world pos = (35.0, -22.5)",
              near(30 + e["at_world"][0], 35.0) and near(-20 + e["at_world"][1], -22.5))
    if n:
        check("N at_world = [-2.0, -5.0]",
              near(n["at_world"][0], -2.0) and near(n["at_world"][1], -5.0),
              f"got {n['at_world']}")
        check("N inward = [0, 1]", n["inward"] == [0, 1])

    print("Part 2 — tile_rotation 90° CW")
    rot = by_edge(scene_recipe.compose_scene(fixture(90), plan_width_m=10.0))
    s, e2 = rot.get("S"), rot.get("E")
    check("letters rotated: {E, N} → exactly {S, E}", set(rot) == {"S", "E"})
    if s:
        check("S at_world = [2.5, 5.0] (at flipped 0.25→0.75)",
              near(s["at_world"][0], 2.5) and near(s["at_world"][1], 5.0),
              f"got {s['at_world']}")
        check("S inward = [0, -1] (vector rotated)", s["inward"] == [0, -1])
        check("room link survives rotation", s.get("room_id") == "road")
    if e2:
        check("E at_world = [5.0, -2.0] (no flip on N)",
              near(e2["at_world"][0], 5.0) and near(e2["at_world"][1], -2.0),
              f"got {e2['at_world']}")
        check("E inward = [-1, 0]", e2["inward"] == [-1, 0])

    print("Part 3 — entry gate decisions (pure, no DB)")
    loc = {
        "map3d": {"boundary_openings": [dict(op) for op in OPENINGS]},
        "rooms": [{"id": "road"}, {"id": "clearing"}, {"id": GROUND_ROOM_ID}],
        "entry_room": "clearing",
    }
    check("direction north exits edge N", EDGE_OF_DIRECTION["north"] == "N")
    check("…and enters the target's S edge", OPPOSITE_EDGE["N"] == "S")
    check("entry at E opening routes into 'road'",
          opening_entry_room(loc, "E") == "road")
    check("edge without opening routes nowhere (→ entry_room fallback)",
          opening_entry_room(loc, "W") == "")
    check("opening without room link routes nowhere",
          opening_entry_room(loc, "N") == "")
    ghost = {"map3d": {"boundary_openings": [
        {"edge": "E", "at": 0.5, "room": "nonexistent"}]},
        "rooms": [{"id": "road"}]}
    check("room link to a room that does not exist is ignored",
          opening_entry_room(ghost, "E") == "")
    # Part 3b — the two gates (plan-betreten-und-tueren.md § 5 A).
    # Fixture: E carries an opening linked to room "road", N carries one
    # WITHOUT a room link. Entry room of the location is "square".
    check("edge with a linked opening is a way in",
          opening_on_edge(loc, "E") is True)
    check("edge with a ROOMLESS opening is a way in too",
          opening_on_edge(loc, "N") is True)
    check("edge without an opening is not",
          opening_on_edge(loc, "S") is False)
    check("a location with any opening has an entrance",
          has_entrance(loc) is True)
    check("a location without map3d has none",
          has_entrance({}) is False)

    # Leaving. Three ways out, in the order of the rule. A roomless opening
    # leads onto the GROUND room, so that is the room it lets out of.
    check("leaving from the opening's linked room",
          may_leave(loc, "road", "square", "E") is True)
    check("leaving FROM THE GROUND over a roomless opening",
          may_leave(loc, GROUND_ROOM_ID, "square", "N") is True)
    check("on the ground: NO exit over an edge without an opening",
          may_leave(loc, GROUND_ROOM_ID, "square", "S") is False)
    check("a room is not the ground: no exit over a roomless opening",
          may_leave(loc, "kitchen", "square", "N") is False)
    check("the entry room remains the gate everywhere else",
          may_leave(loc, "square", "square", "S") is True)
    check("another room may not leave over a plain edge",
          may_leave(loc, "kitchen", "square", "S") is False)
    check("no entry room declared = leaving is free",
          may_leave(loc, "kitchen", "", "S") is True
          and may_leave(loc, GROUND_ROOM_ID, "", "S") is True)
    check("wrong room, right edge: the opening's link decides",
          may_leave(loc, "kitchen", "square", "E") is False)

    rot_loc = {"map3d": {"tile_rotation": 90,
                         "boundary_openings": [
                             {"edge": "E", "at": 0.25, "room": "road"}]},
               "rooms": [{"id": "road"}]}
    check("rotation 90: stored E gates the WORLD S edge",
          opening_entry_room(rot_loc, "S") == "road"
          and opening_entry_room(rot_loc, "E") == "")
    check("rotation 90: leaving follows the rotated edge too",
          may_leave(rot_loc, "road", "square", "S") is True
          and may_leave(rot_loc, "road", "square", "E") is False)

    print("Part 4 — where an arrival lands (§ 6: entry_room is optional)")
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
    # The consumer's expression (world_ops.move_avatar_step): the opening's
    # room link beats both, a roomless opening says nothing and lets the
    # entry_room / the ground decide.
    check("an opening WITH a link beats the entry room",
          (opening_entry_room(loc, "E") or get_arrival_room_id(loc)) == "road")
    check("a roomless opening falls back to the entry room",
          (opening_entry_room(loc, "N") or get_arrival_room_id(loc)) == "clearing")
    open_no_entry = {"map3d": {"boundary_openings": [dict(op) for op in OPENINGS]},
                     "rooms": [{"id": "road"}, {"id": GROUND_ROOM_ID}]}
    check("…and without an entry room onto the ground",
          (opening_entry_room(open_no_entry, "N")
           or get_arrival_room_id(open_no_entry)) == GROUND_ROOM_ID)

    print("Part 5 — the width cap is the location edge, and it clamps")
    from app.core.world_ops import _sanitize_map3d  # noqa: E402

    def widths(plan_width_m, *raw_widths):
        raw = {"boundary_openings": [
            {"edge": "N", "at": 0.5, "width_m": w} for w in raw_widths]}
        if plan_width_m is not None:
            raw["plan_width_m"] = plan_width_m
        return [op["width_m"]
                for op in _sanitize_map3d(raw).get("boundary_openings") or []]

    check("plan_width_m 40: a 60 m opening clamps to 40",
          widths(40, 60) == [40.0], widths(40, 60))
    check("plan_width_m 40: 25 m survives (the old 10 m cap dropped it)",
          widths(40, 25) == [25.0], widths(40, 25))
    check("plan_width_m 40: 0.2 m clamps up to 0.5, it is not dropped",
          widths(40, 0.2) == [0.5], widths(40, 0.2))
    check("plan_width_m 0.5: the cap wins over the lower bound",
          widths(0.5, 3) == [0.5], widths(0.5, 3))
    check("no anchor: 25 m clamps to the 10 m fallback",
          widths(None, 25) == [10.0], widths(None, 25))
    check("no anchor: 3 m passes untouched",
          widths(None, 3) == [3.0], widths(None, 3))
    check("a non-numeric width is still dropped (nothing to clamp)",
          widths(40, "wide", 3) == [3.0], widths(40, "wide", 3))
    over = _sanitize_map3d({"plan_width_m": 40, "boundary_openings": [
        {"edge": "n", "at": 1.4, "width_m": 60, "room": "road"}]})
    check("clamping keeps the rest of the entry intact",
          over["boundary_openings"] == [{"edge": "N", "at": 1.0,
                                         "width_m": 40.0, "type": "passage",
                                         "room": "road"}],
          over.get("boundary_openings"))

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
