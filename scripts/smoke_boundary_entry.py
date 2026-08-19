#!/usr/bin/env python3
"""Smoke check: boundary openings — payload transform + entry gate (Etappe 3).

Usage:  ./.venv/bin/python scripts/smoke_boundary_entry.py

Pure functions, no server, no world.db. Like every smoke here, the expected
numbers are derived BY HAND from the contract (docs/schnittstellen-3d.md
§ B1 Nr. 13), never recorded from output.

AN EDGE IS AN INDEX (contract v6 Nr. 5): an opening names the 0-based index
of the boundary edge it sits on. A location without a drawn boundary has the
reference square as its effective one, clockwise in map view — with
plan_width_m 10 that is (−5,−5) (5,−5) (5,5) (−5,5), so edge 0 runs
west→east along the north side, 1 north→south on the east side, 2 east→west
on the south side and 3 south→north on the west side.

Part 1 — at_world on that square (Nr. 13), plan_width_m 10:
    edge 1, at 0.25  → (5, −5 + 0.25·10) = [ 5.0, -2.5], inward [-1, 0]
    edge 0, at 0.30  → (−5 + 0.30·10, −5) = [-2.0, -5.0], inward [ 0, 1]
  Both normals are (−dz, dx)/|d| verified by the inside probe.
  The CLIENT adds only the pin position (30, -20):
    world(edge-1 opening) = (30 + 5.0, -20 - 2.5) = (35.0, -22.5).

Part 2 — a DRAWN, CONCAVE boundary (v6 Nr. 1/5). The L
    (−5,−5) (5,−5) (5,0) (0,0) (0,5) (−5,5) has edge 2 running
    (5,0) → (0,0), direction (−5, 0). At `at` 0.5 that is (2.5, 0); the
    candidate normal (−dz, dx)/|d| = (0, −1) probed at (2.5, −0.001) lies
    inside the L, so INWARD is (0, −1) — into the arm, away from the notch.
    An index the outline does not have is dropped, not guessed.

Part 3 — entry gate (app/core/boundary_entry.py; wired into
    POST /play/pos). The edge INDEX is what identifies an opening for the
    gate; the route reads it off the crossing point, never off a compass.
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
    2026-08-04). An opening lies ON a boundary edge, and the location is
    ``plan_width_m`` wide, so THAT is the
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
    has_entrance, may_leave, opening_entry_room, opening_on_edge,
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
    {"edge": 1, "at": 0.25, "width_m": 2.0, "type": "passage", "room": "road"},
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
                "x": 0.1, "y": 0.1, "w": 0.4, "d": 0.3, "level": 0}},
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
        check("edge 1 room link passes through", e.get("room_id") == "road")
        # The client's whole transform: the pin (30, -20) + at_world.
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
        {"edge": 2, "at": 0.5, "width_m": 2.0, "room": "road"},
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
        check("the room link survives", lo[2].get("room_id") == "road")

    print("Part 3 — entry gate decisions (pure, no DB)")
    loc = {
        "map3d": {"boundary_openings": [dict(op) for op in OPENINGS]},
        "rooms": [{"id": "road"}, {"id": "clearing"}, {"id": GROUND_ROOM_ID}],
        "entry_room": "clearing",
    }
    check("entry at the edge-1 opening routes into 'road'",
          opening_entry_room(loc, 1) == "road")
    check("edge without opening routes nowhere (→ entry_room fallback)",
          opening_entry_room(loc, 3) == "")
    check("opening without room link routes nowhere",
          opening_entry_room(loc, 0) == "")
    check("no edge at all (the free-boundary case) routes nowhere",
          opening_entry_room(loc, None) == "")
    ghost = {"map3d": {"boundary_openings": [
        {"edge": 1, "at": 0.5, "room": "nonexistent"}]},
        "rooms": [{"id": "road"}]}
    check("room link to a room that does not exist is ignored",
          opening_entry_room(ghost, 1) == "")
    # Part 3b — the two gates (plan-betreten-und-tueren.md § 5 A).
    # Fixture: edge 1 carries an opening linked to room "road", edge 0 one
    # WITHOUT a room link. Entry room of the location is "square".
    check("edge with a linked opening is a way in",
          opening_on_edge(loc, 1) is True)
    check("edge with a ROOMLESS opening is a way in too",
          opening_on_edge(loc, 0) is True)
    check("edge without an opening is not",
          opening_on_edge(loc, 2) is False)
    check("a location with any opening has an entrance",
          has_entrance(loc) is True)
    check("a location without map3d has none",
          has_entrance({}) is False)

    # Leaving. Three ways out, in the order of the rule. A roomless opening
    # leads onto the GROUND room, so that is the room it lets out of.
    check("leaving from the opening's linked room",
          may_leave(loc, "road", "square", 1) is True)
    check("leaving FROM THE GROUND over a roomless opening",
          may_leave(loc, GROUND_ROOM_ID, "square", 0) is True)
    check("on the ground: NO exit over an edge without an opening",
          may_leave(loc, GROUND_ROOM_ID, "square", 2) is False)
    check("a room is not the ground: no exit over a roomless opening",
          may_leave(loc, "kitchen", "square", 0) is False)
    check("the entry room remains the gate everywhere else",
          may_leave(loc, "square", "square", 2) is True)
    check("another room may not leave over a plain edge",
          may_leave(loc, "kitchen", "square", 2) is False)
    check("no entry room declared = leaving is free",
          may_leave(loc, "kitchen", "", 2) is True
          and may_leave(loc, GROUND_ROOM_ID, "", 2) is True)
    check("wrong room, right edge: the opening's link decides",
          may_leave(loc, "kitchen", "square", 1) is False)
    check("no edge at all: the entry-room rule is what is left",
          may_leave(loc, "square", "square", None) is True
          and may_leave(loc, "kitchen", "square", None) is False)

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
          (opening_entry_room(loc, 1) or get_arrival_room_id(loc)) == "road")
    check("a roomless opening falls back to the entry room",
          (opening_entry_room(loc, 0) or get_arrival_room_id(loc)) == "clearing")
    open_no_entry = {"map3d": {"boundary_openings": [dict(op) for op in OPENINGS]},
                     "rooms": [{"id": "road"}, {"id": GROUND_ROOM_ID}]}
    check("…and without an entry room onto the ground",
          (opening_entry_room(open_no_entry, 0)
           or get_arrival_room_id(open_no_entry)) == GROUND_ROOM_ID)

    print("Part 5 — the width cap is the location edge, and it clamps")
    from app.core.world_ops import _sanitize_map3d  # noqa: E402

    def widths(plan_width_m, *raw_widths):
        raw = {"boundary_openings": [
            {"edge": 0, "at": 0.5, "width_m": w} for w in raw_widths]}
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
        {"edge": 3, "at": 1.4, "width_m": 60, "room": "road"}]})
    check("clamping keeps the rest of the entry intact",
          over["boundary_openings"] == [{"edge": 3, "at": 1.0,
                                         "width_m": 40.0, "type": "passage",
                                         "room": "road"}],
          over.get("boundary_openings"))
    # v6 Nr. 5: no alias reader for the deleted letters, and no index the
    # boundary does not have — both are DROPPED (with a log line), never
    # translated into something plausible.
    lettered = _sanitize_map3d({"plan_width_m": 40, "boundary_openings": [
        {"edge": "N", "at": 0.5, "width_m": 3}]})
    check("an edge LETTER is dropped by the sanitizer",
          "boundary_openings" not in lettered, str(lettered))
    outside = _sanitize_map3d({"plan_width_m": 40, "boundary_openings": [
        {"edge": 4, "at": 0.5, "width_m": 3}]})
    check("...and so is index 4 on a four-edge square",
          "boundary_openings" not in outside, str(outside))
    six = _sanitize_map3d({"boundary": [list(p) for p in L_BOUNDARY],
                           "boundary_openings": [
                               {"edge": 4, "at": 0.5, "width_m": 3}]})
    check("on the six-edge L, index 4 is perfectly legal",
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
