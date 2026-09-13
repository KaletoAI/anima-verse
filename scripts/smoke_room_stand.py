#!/usr/bin/env python3
"""Smoke run for the free standing point in a room
(plan-animationen-echtzeit-stehplatz.md T4, docs/schnittstellen-3d.md § A1.4).

Pure geometry, no world, no DB: hand-built polygons, footprint boxes, door
zones and mates go straight into ``room_stand.pick_stand``. EVERY expected
number below is derived BY HAND from the rule — the script only measures
whether the code produces it.

THE RULE (the four constants are the contract):

    STAND_GRID_M 0.25   candidate raster over the polygon's bounding box,
                        anchored on the grid (floor(min / 0.25) * 0.25)
    WALL_CLEAR_M 0.35   minimum distance to every polygon edge
    BODY_R_M     0.30   every floor-prop footprint grows by this
    MATE_CLEAR_M 0.70   minimum distance to everybody else in the room

    free candidate nearest to `near` wins; tie -> larger wall clearance,
    then smallest x, then smallest z. `near` itself, when free, wins outright.

THE FIXTURES AND THEIR HAND-DERIVED ANSWERS

[1] SQUARE 6 x 6, (0,0)…(6,6), nothing in it, near = (3, 3).
    (3, 3) is 3 m from every edge, in no footprint, in no zone, alone in the
    room -> FREE -> returned unchanged, no walk.

[2] L-ROOM 6 x 6 with the 3 x 3 notch at x > 3, z < 3:
    (0,0) (3,0) (3,3) (6,3) (6,6) (0,6). Its VERTEX MEAN is (3, 3) — the
    notch's own corner, 0.00 m from two walls and therefore never free: the
    very case the client's bounding-box middle got wrong.
    near = (5.5, 1.0) lies IN THE NOTCH, outside the room.
    The two arms, trimmed by the 0.35 wall clearance:
      arm A (the west leg)   x <= 2.65 -> grid x = 2.50, z free from 0.35 up
      arm B (the south leg)  z >= 3.35 -> grid z = 3.50, x <= 5.65 -> 5.50
    distance from (5.5, 1.0): arm A at (2.50, 1.00) = 3.00 m,
                              arm B at (5.50, 3.50) = 2.50 m.
    Nothing in the room is nearer: any point with x <= 2.65 is already 2.85 m
    away in x alone, and any point with z >= 3.35 is 2.50 m away in z alone,
    with equality only at x = 5.5. -> (5.50, 3.50).

[3] TABLE 1.2 x 0.8, turned 30 degrees, centred in the 6 x 6 square.
    A world point is tested in the table's own frame (props._footprint_contains):
    the front axis is local +z, so the point (3 + t*sin30, 3 + t*cos30) has
    local (0, t). Grown half depth = 0.8/2 + 0.30 = 0.70.
      t = 0.60 (0.20 m in front of the table edge): 0.60 <= 0.70 -> BLOCKED.
        world (3.300, 3.5196152) — 0.6*sin30 = 0.300, 0.6*cos30 = 0.5196152
      t = 0.80 (0.40 m in front of the edge):       0.80 >  0.70 -> FREE.
        world (3.400, 3.6928203)
    With near = the blocked point the nearest free grid candidate is
    (3.25, 3.75): its local coordinates are
      lx = 0.25*cos30 − 0.75*sin30 = 0.2165 − 0.3750 = −0.1585  (|lx| <= 0.90)
      lz = 0.25*sin30 + 0.75*cos30 = 0.1250 + 0.6495 =  0.7745  (> 0.70) -> free
    at sqrt(0.05^2 + 0.2303848^2) = 0.2357 m from near, while every nearer
    grid point — (3.25, 3.50),
    (3.50, 3.50), (3.00, 3.50) — still has |lz| <= 0.70 and is blocked.

[4] TWO MATES at 0.5 m: (2.5, 3.0) and (3.5, 3.0), near = (3, 3).
    near is 0.50 m from both < 0.70 -> blocked. On the raster every candidate
    at 0.25 and at 0.3536 m from near is still inside 0.70 of one mate; the
    first free ones are (3.0, 2.5) and (3.0, 3.5), both at 0.50 m and both
    0.7071 m from either mate (sqrt(0.25 + 0.25)). The tie runs: equal
    distance, equal wall clearance (2.50 m), equal x -> smallest z wins
    -> (3.00, 2.50).

[5] DOOR ZONE on the south edge of the square, opening {edge 0, at 0.5,
    width 1.0, type door}. furnish_geometry.opening_zones: depth
    max(0.6, width) = 1.0, half width (1.0 + 0.4)/2 = 0.7, on edge
    (0,0)->(6,0) at t = 0.5 -> the point (3, 0), inward normal (0, 1):
    the quad (3.7, 0) (3.7, 1) (2.3, 1) (2.3, 0).
    near = (3.0, 0.5) is in it -> blocked; (3.0, 1.25) is not and keeps
    1.25 m from the wall -> free, returned unchanged.

[6] RED COUNTER-CHECK: a 0.6 x 0.6 room has no point 0.35 m from every edge
    -> None, and the caller leaves the position alone.

[7] IDEMPOTENCE — asking twice costs nothing. Every answer of [2]…[5] is FREE
    by construction (that is what made it an answer), and a free `near` is
    returned unchanged by rule, so feeding a result back in yields itself.
    That is why the write paths may ask more than once for one arrival: the
    location write, the room write and the travel engine all call the same
    thing, and only the first of them can move anybody.

Usage:  ./.venv/bin/python scripts/smoke_room_stand.py
"""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The storage root MUST be redirected BEFORE the first app import: paths.init
# otherwise falls back to worlds/demo — the world that is tracked in git.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="room-stand-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="room-stand-storage-"))

from app.core import furnish_geometry as fg  # noqa: E402
from app.core import room_stand  # noqa: E402
from app.core.room_stand import pick_stand  # noqa: E402

FAILURES = []

SQUARE = [[0, 0], [6, 0], [6, 6], [0, 6]]
L_ROOM = [[0, 0], [3, 0], [3, 3], [6, 3], [6, 6], [0, 6]]
TABLE = {"at": [3.0, 3.0], "yaw": 30.0, "width_m": 1.2, "depth_m": 0.8}
SIN30, COS30 = 0.5, math.sqrt(3) / 2


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def at(point, x: float, z: float, eps: float = 1e-6) -> bool:
    return (point is not None and abs(point[0] - x) <= eps
            and abs(point[1] - z) <= eps)


def test_constants() -> None:
    print("\n[0] the four constants of the rule")
    check("the raster is 0.25 m", room_stand.STAND_GRID_M == 0.25)
    check("the wall clearance is 0.35 m", room_stand.WALL_CLEAR_M == 0.35)
    check("the body radius is 0.30 m", room_stand.BODY_R_M == 0.30)
    check("mates keep 0.70 m", room_stand.MATE_CLEAR_M == 0.70)


def test_near_is_free() -> None:
    print("\n[1] a free `near` is returned unchanged — nobody walks for nothing")
    got = pick_stand(SQUARE, [], [], [], (3.0, 3.0))
    check("the middle of an empty 6 x 6 room stands", at(got, 3.0, 3.0), str(got))


def test_l_room() -> None:
    print("\n[2] the L-room: `near` in the notch, the answer in the nearer arm")
    check("the vertex mean (3, 3) has no wall clearance at all",
          room_stand._edge_clearance((3.0, 3.0),
                                     [(p[0], p[1]) for p in L_ROOM]) == 0.0)
    got = pick_stand(L_ROOM, [], [], [], (5.5, 1.0))
    check("the south arm at (5.50, 3.50) wins", at(got, 5.5, 3.5), str(got))
    check("…at 2.50 m from `near`",
          got is not None and abs(math.dist(got, (5.5, 1.0)) - 2.5) < 1e-9)
    check("…and it keeps 0.50 m from both walls of that arm",
          got is not None
          and abs(room_stand._edge_clearance(
              got, [(p[0], p[1]) for p in L_ROOM]) - 0.5) < 1e-9)


def test_table() -> None:
    print("\n[3] the turned table: 0.20 m in front of the edge falls, 0.40 m stands")
    blocked = (3.0 + 0.6 * SIN30, 3.0 + 0.6 * COS30)
    free = (3.0 + 0.8 * SIN30, 3.0 + 0.8 * COS30)
    check("the blocked point is (3.300, 3.5196152)",
          abs(blocked[0] - 3.3) < 1e-9 and abs(blocked[1] - 3.5196152) < 1e-6)
    check("0.20 m in front of the edge is inside the grown footprint",
          room_stand._in_footprint(blocked[0], blocked[1], TABLE, room_stand.BODY_R_M))
    check("0.40 m in front of it is not",
          not room_stand._in_footprint(free[0], free[1], TABLE, room_stand.BODY_R_M))
    check("…so the free point is returned unchanged",
          at(pick_stand(SQUARE, [TABLE], [], [], free), free[0], free[1]),
          str(free))
    got = pick_stand(SQUARE, [TABLE], [], [], blocked)
    check("…and the blocked one steps to (3.25, 3.75)", at(got, 3.25, 3.75), str(got))
    check("…which is 0.2357 m away",
          got is not None and abs(math.dist(got, blocked) - 0.2357) < 1e-4)


def test_mates() -> None:
    print("\n[4] two mates at 0.50 m")
    mates = [(2.5, 3.0), (3.5, 3.0)]
    got = pick_stand(SQUARE, [], [], mates, (3.0, 3.0))
    check("the tie ladder ends at (3.00, 2.50)", at(got, 3.0, 2.5), str(got))
    check("…0.7071 m from either mate",
          got is not None
          and all(abs(math.dist(got, m) - math.sqrt(0.5)) < 1e-9 for m in mates))
    check("…and 0.50 m from `near`",
          got is not None and abs(math.dist(got, (3.0, 3.0)) - 0.5) < 1e-9)


def test_door_zone() -> None:
    print("\n[5] the door zone in front of a 1.0 m door")
    poly = [(p[0], p[1]) for p in SQUARE]
    zones = fg.opening_zones(poly, (3.0, 3.0),
                             [{"edge": 0, "at": 0.5, "width_m": 1.0, "type": "door"}])
    quad = [(round(c[0], 6), round(c[1], 6)) for c in zones[0].corners]
    check("the quad is (3.7,0) (3.7,1) (2.3,1) (2.3,0)",
          quad == [(3.7, 0.0), (3.7, 1.0), (2.3, 1.0), (2.3, 0.0)], str(quad))
    door = [list(zones[0].corners)]
    got = pick_stand(SQUARE, [], door, [], (3.0, 0.5))
    check("a point on the doorstep does not stay there",
          got is not None and not at(got, 3.0, 0.5), str(got))
    check("…and the point behind the zone does",
          at(pick_stand(SQUARE, [], door, [], (3.0, 1.25)), 3.0, 1.25))


def test_no_room() -> None:
    print("\n[6] red counter-check: a room too small for anybody")
    check("a 0.6 x 0.6 room offers no standing point",
          pick_stand([[0, 0], [0.6, 0], [0.6, 0.6], [0, 0.6]], [], [], [],
                     (0.3, 0.3)) is None)
    check("a degenerate polygon offers none either",
          pick_stand([[0, 0], [1, 1]], [], [], [], (0.0, 0.0)) is None)


def test_idempotent() -> None:
    print("\n[7] asking twice moves nobody — every answer is itself free")
    cases = [
        ("the L-room", L_ROOM, [], [], [], (5.5, 1.0)),
        ("the turned table", SQUARE, [TABLE], [], [],
         (3.0 + 0.6 * SIN30, 3.0 + 0.6 * COS30)),
        ("two mates", SQUARE, [], [], [(2.5, 3.0), (3.5, 3.0)], (3.0, 3.0)),
    ]
    for label, poly, blockers, zones, mates, near in cases:
        first = pick_stand(poly, blockers, zones, mates, near)
        again = pick_stand(poly, blockers, zones, mates, first)
        check(f"{label}: the second ask returns the first answer",
              first is not None and again is not None
              and at(again, first[0], first[1]), f"{first} -> {again}")


def main() -> int:
    print("Smoke: the free standing point in a room (T4)")
    test_constants()
    test_near_is_free()
    test_l_room()
    test_table()
    test_mates()
    test_door_zone()
    test_no_room()
    test_idempotent()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
