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

THE STAND POINT AFTER A BRIDGE CLIP (plan-bruecken-root-motion Task 7)

A bridge clip with root motion (``get-up-chair``) carries the figure off its
seat; its sidecar says how far: ``travel_m`` in the CLIP frame (+Z forward,
+X the figure's LEFT), metres of the reference rig, ``ref_height_m`` tall.
The server turns it by the seat's compass facing f (0 = south +z, 90 = east
+x) with the rotation of the client's ``toWorld``
(``client3d/src/scene/bridgeTravel.ts``):

    x' = x·cos f + z·sin f        z' = −x·sin f + z·cos f

and scales it by height_cm/100 / ref_height_m.

[8]  bridge_offset((0, 0.4), facing 0, scale 1) -> (0, 0.4): cos 0 = 1,
     sin 0 = 0, so x' = 0, z' = 0.4 — facing 0 is south (+z) and the clip's
     forward is +z.
[9]  bridge_offset((0, 0.4), 90, 1): cos 90 = 0, sin 90 = 1 ->
     x' = 0·0 + 0.4·1 = 0.4, z' = −0·1 + 0.4·0 = 0 -> (0.4, 0), east.
     bridge_offset((0, 0.4), 180, 1): cos = −1, sin = 0 -> (0, −0.4).
[10] bridge_offset((0.1, 0), 90, 1): x' = 0.1·0 + 0 = 0,
     z' = −0.1·1 + 0 = −0.1 -> (0, −0.1): the figure's left at facing east
     is −z (north) — a figure looking east has north on its left.
     bridge_offset((0, 0.4), 0, 1.1) -> (0, 0.44): the scale multiplies.
[11] pick_stand with near = the stand point. Room: the square (−3,−3)…(3,3),
     seat (0, 0) facing 0, stand point (0, 0.4).
     a) nobody else there: (0, 0.4) is 2.6 m from the nearest wall, in no
        footprint and no zone -> FREE -> returned unchanged.
     b) a mate stands exactly ON (0, 0.4). The raster is anchored at
        floor(−3/0.25)·0.25 = −3, so candidates are multiples of 0.25. A
        candidate is free when it is >= 0.70 from the mate (walls are 2+ m
        away for everything near). Distance from near = distance from the
        mate, so the answer is the grid point nearest (0, 0.4) that is
        >= 0.70 from it. dz = z − 0.4 takes ... −0.65, −0.4, −0.15, 0.1,
        0.35, 0.6, 0.85 ...
          x = 0      : |dz| >= 0.70 first at dz 0.85 -> 0.8500
          x = ±0.25  : needs dz² >= 0.49 − 0.0625 = 0.4275; dz −0.65 gives
                       0.4225 (0.6964 m, blocked) -> dz 0.85 -> 0.8860
          x = ±0.50  : needs dz² >= 0.24; dz 0.6 -> sqrt(0.61) = 0.7810
          x = ±0.75  : 0.5625 >= 0.49, any dz; dz 0.1 (z 0.5)
                       -> sqrt(0.5725) = 0.7566   <- the minimum
          |x| >= 1.0 : >= 1.0
        (−0.75, 0.5) and (0.75, 0.5) tie at 0.7566 m, both 2.25 m from the
        nearest wall -> smallest x -> (−0.75, 0.50).
        The same room searched from the SEAT (0, 0) instead answers
        (0, −0.50): (0, −0.25) is 0.65 m from the mate (blocked), (0, −0.5)
        is 0.90 m from it (free) at 0.50 m from the seat, and every nearer
        grid point — (±0.25, 0), (0, ±0.25), (±0.25, ±0.25) — lies inside
        0.70 of the mate. The two answers differ: the search starts at the
        stand point.
[12] scale: 190 cm over a 1.75 m rig -> 1.90 / 1.75 = 1.085714; height
     unset or ref missing -> 1.0. Through ``bridge_stand_point`` (seat
     (2, 3) facing 90, travel (0, 0.4)): 190 cm -> (2 + 0.4·1.085714, 3)
     = (2.434286, 3.0); no height -> (2.4, 3.0).
[13] a RAMPING exit rule (accel > 0) gives no stand point (None): the
     figure walks off during the clip, the travel is not a separate leg. A
     clip in mode ``strip`` (no travel) gives None as well.

FIX ROUND 1

[14] STILL ON THE SEAT (SEAT_MATCH_M = 0.05). The seat (2, 3) facing 90 with
     travel (0, 0.4) and no height: the current point (2, 3) is 0.00 m from
     it <= 0.05 -> the stand point (2.4, 3.0) is used, and ``stand_up``
     searches from it: ``free_stand_point`` is asked with near (2.4, 3.0)
     and (stubbed to hand `near` back) the character is written there.
[15] THE ROOM-CHANGE CASE. The same-id seat resolves in the room the
     character is in NOW, but the character stands 1 m away at (3, 3):
     dist((3, 3), (2, 3)) = 1.00 > 0.05 -> ``bridge_stand_point`` answers
     None, and ``stand_up`` searches from the CURRENT point (3, 3) exactly as
     without a seat — which is free and already where the character is, so
     nothing is written.
[16] THE EFFECTIVE POSE. A sleeping character (``is_sleeping`` true) whose
     STORED pose_key is ``lying``: in the fixture ``lying`` plays ``lie``,
     whose exit clip ``smoke-rise-strip`` has no travel, and ``sleeping``
     plays ``sleep``, whose exit clip ``smoke-rise`` carries (0, 0.4).
     ``clear_pose_intent`` and ``places.release`` must hand ``stand_up`` the
     EFFECTIVE key ``sleeping`` (what journeys, the payload and the client
     use), so the stand point comes from the sleeping clip: seat (2, 3)
     facing 90 -> (2.4, 3.0); the stored key would give None.

Usage:  ./.venv/bin/python scripts/smoke_room_stand.py
"""
import contextlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The storage root MUST be redirected BEFORE the first app import: without a
# storage root every world access raises StorageNotInitialised — there is no
# default world any more, so nothing here can land in the tracked worlds/demo.
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="room-stand-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="room-stand-storage-"))
from app.core import db  # noqa: E402
db.init_schema()

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


# ── the bridge fixture: two hand-made sidecars in the TEMP clip directory and
# the three table lookups stood in for (the real tables live in shared/config).
_CLIPS = Path(os.environ["ANIMATION_CLIPS_DIR"])
for _kind, _mode in (("smoke-rise", "foot_lock"), ("smoke-rise-strip", "strip")):
    (_CLIPS / f"{_kind}.json").write_text(json.dumps({
        "kind": _kind, "duration_s": 2.0, "loop": False,
        "geometry": {"root_motion": {"mode": _mode, "travel_m": [0.0, 0.4],
                                     "ref_height_m": 1.75}}}), encoding="utf-8")


#: pose key -> the animation it plays, and animation -> its exit clip.
_ANIM = {"sitting": "sit", "lying": "lie", "sleeping": "sleep"}


@contextlib.contextmanager
def _bridge_fixture(accel: float, kind: str = "smoke-rise"):
    import app.core.animation_clips as ac
    import app.core.expression_pose_maps as epm
    keep = (epm.resolve_pose_animation, ac.load_locomotion_clips, ac.resolve_transition)
    exits = {"sit": kind, "lie": "smoke-rise-strip", "sleep": "smoke-rise"}
    try:
        epm.resolve_pose_animation = lambda k: _ANIM.get(k, "idle")
        ac.load_locomotion_clips = lambda *a, **k: {"walk": "walk"}
        ac.resolve_transition = lambda a, b, rules=None: (
            {"from": a, "to": b, "kind": exits[a], "accel": accel}
            if a in exits and b == "walk" else None)
        yield
    finally:
        epm.resolve_pose_animation, ac.load_locomotion_clips, ac.resolve_transition = keep


def near_xz(point, x: float, z: float, eps: float = 1e-6) -> bool:
    return at(point, x, z, eps)


def test_bridge_offset() -> None:
    print("\n[8]-[10] the clip travel turned by the seat's facing")
    bo = room_stand.bridge_offset
    check("(0, 0.4) at facing 0 is (0, 0.4) — south", near_xz(bo((0, 0.4), 0, 1), 0.0, 0.4),
          str(bo((0, 0.4), 0, 1)))
    check("(0, 0.4) at facing 90 is (0.4, 0) — east", near_xz(bo((0, 0.4), 90, 1), 0.4, 0.0),
          str(bo((0, 0.4), 90, 1)))
    check("(0, 0.4) at facing 180 is (0, −0.4) — north",
          near_xz(bo((0, 0.4), 180, 1), 0.0, -0.4), str(bo((0, 0.4), 180, 1)))
    check("(0.1, 0) at facing 90 is (0, −0.1) — the left of an east-facer is north",
          near_xz(bo((0.1, 0), 90, 1), 0.0, -0.1), str(bo((0.1, 0), 90, 1)))
    check("(0, 0.4) at facing 0, scale 1.1 is (0, 0.44)",
          near_xz(bo((0, 0.4), 0, 1.1), 0.0, 0.44), str(bo((0, 0.4), 0, 1.1)))


def test_stand_from_bridge_point() -> None:
    print("\n[11] the search starts at the STAND point, not at the seat")
    room = [[-3, -3], [3, -3], [3, 3], [-3, 3]]
    got = pick_stand(room, [], [], [], (0.0, 0.4))
    check("a free stand point is returned unchanged", at(got, 0.0, 0.4), str(got))
    mate = [(0.0, 0.4)]
    got = pick_stand(room, [], [], mate, (0.0, 0.4))
    check("a mate on it -> the nearest free raster point to it: (−0.75, 0.50)",
          at(got, -0.75, 0.5), str(got))
    check("…0.7566 m from the stand point",
          got is not None and abs(math.dist(got, (0.0, 0.4)) - math.sqrt(0.5725)) < 1e-9)
    seat = pick_stand(room, [], [], mate, (0.0, 0.0))
    check("from the SEAT the same room answers (0, −0.50) — a different point",
          at(seat, 0.0, -0.5), str(seat))


def test_bridge_scale() -> None:
    print("\n[12] the travel scales with the figure")
    check("190 cm over a 1.75 m rig is 1.085714",
          abs(room_stand.bridge_scale(190, 1.75) - 1.9 / 1.75) < 1e-12,
          str(room_stand.bridge_scale(190, 1.75)))
    check("no height is 1.0", room_stand.bridge_scale(None, 1.75) == 1.0)
    check("no reference height is 1.0", room_stand.bridge_scale(190, None) == 1.0)
    seat = {"x": 2.0, "z": 3.0, "facing": 90.0}
    with _bridge_fixture(accel=0.0):
        got = room_stand.bridge_stand_point("smoke", seat, "sitting",
                                            profile={"height": 190}, at=(2.0, 3.0))
        check("190 cm from a seat at (2, 3) facing east lands at (2.434286, 3.0)",
              at(got, 2.0 + 0.4 * 1.9 / 1.75, 3.0), str(got))
        got = room_stand.bridge_stand_point("smoke", seat, "sitting", profile={},
                                            at=(2.0, 3.0))
        check("no height lands at (2.4, 3.0)", at(got, 2.4, 3.0), str(got))


def test_ramping_rule() -> None:
    print("\n[13] a ramping exit rule and a clip without travel give no stand point")
    seat = {"x": 2.0, "z": 3.0, "facing": 90.0}
    with _bridge_fixture(accel=0.6):
        check("accel 0.6 -> None",
              room_stand.bridge_stand_point("smoke", seat, "sitting", profile={},
                                            at=(2.0, 3.0)) is None)
    with _bridge_fixture(accel=0.0, kind="smoke-rise-strip"):
        check("a strip clip -> None",
              room_stand.bridge_stand_point("smoke", seat, "sitting", profile={},
                                            at=(2.0, 3.0)) is None)


@contextlib.contextmanager
def _stand_up_stubs(pos, seat):
    """``stand_up`` with the world stood in for: the room, the current point,
    the resolved seat, the free-point search (hands `near` back, recording
    it), the location check and the write (recorded)."""
    from app.core import places
    import app.models.character as ch
    seen = {}
    keep = (places.where, places.resolve_place, places.inside, ch.get_character_pos,
            ch.set_character_pos, room_stand.free_stand_point)
    try:
        places.where = lambda n: ("L", "R")
        places.resolve_place = lambda n, pl: dict(seat) if pl else None
        places.inside = lambda *a: True
        ch.get_character_pos = lambda n: {"x": pos[0], "z": pos[1]}
        ch.set_character_pos = lambda n, x, z, **k: seen.setdefault("written", (x, z))
        room_stand.free_stand_point = lambda loc, room, near, exclude="": (
            seen.setdefault("near", tuple(near)) and tuple(near))
        yield seen
    finally:
        (places.where, places.resolve_place, places.inside, ch.get_character_pos,
         ch.set_character_pos, room_stand.free_stand_point) = keep


def test_still_on_the_seat() -> None:
    print("\n[14]-[15] the stand point only while the character is ON the seat")
    seat = {"id": "s1", "slot": 0, "room_id": "r1", "x": 2.0, "z": 3.0, "facing": 90.0}
    check("SEAT_MATCH_M is 0.05", room_stand.SEAT_MATCH_M == 0.05)
    with _bridge_fixture(accel=0.0):
        with _stand_up_stubs((2.0, 3.0), seat) as seen:
            got = room_stand.stand_up("smoke", from_place={"id": "s1"},
                                      from_pose_key="sitting")
        check("[14] on the seat: the search starts at (2.4, 3.0)",
              at(seen.get("near"), 2.4, 3.0), str(seen.get("near")))
        check("[14] …and the character is written there",
              at(got, 2.4, 3.0) and at(seen.get("written"), 2.4, 3.0), str(got))
        check("[15] 1 m off a same-id seat: no stand point",
              room_stand.bridge_stand_point("smoke", seat, "sitting", profile={},
                                            at=(3.0, 3.0)) is None)
        with _stand_up_stubs((3.0, 3.0), seat) as seen:
            got = room_stand.stand_up("smoke", from_place={"id": "s1"},
                                      from_pose_key="sitting")
        check("[15] …stand_up searches from the current point (3, 3)",
              at(seen.get("near"), 3.0, 3.0), str(seen.get("near")))
        check("[15] …and, already standing there, writes nothing",
              got is None and "written" not in seen, str(got))


def test_effective_pose() -> None:
    print("\n[16] a sleeper stands up with the SLEEPING pose's exit clip")
    from app.core import places
    from app.models.character import get_character_profile, save_character_profile
    seat = {"id": "s1", "slot": 0, "room_id": "r1", "x": 2.0, "z": 3.0, "facing": 90.0}
    held = {"id": "s1", "slot": 0, "room_id": "r1"}
    keep = room_stand.stand_up
    for label, clear in (("clear_pose_intent", None), ("places.release", places.release)):
        name = "sleeper_" + label.split(".")[-1]
        save_character_profile(name, {"current_location": "", "pose_key": "lying",
                                      "is_sleeping": True, "place": dict(held)},
                               create_new=True)
        seen = {}
        room_stand.stand_up = lambda n, **k: seen.update(k)
        try:
            if clear is None:
                from app.models.character import clear_pose_intent
                clear_pose_intent(name)
            else:
                clear(name)
        finally:
            room_stand.stand_up = keep
        check(f"{label} hands stand_up the effective key 'sleeping'",
              seen.get("from_pose_key") == "sleeping", str(seen))
        check(f"{label} …and the seat it held", seen.get("from_place") == held,
              str(seen.get("from_place")))
        check(f"{label} …and the place is gone from the profile",
              not (get_character_profile(name) or {}).get("place"))
    with _bridge_fixture(accel=0.0):
        got = room_stand.bridge_stand_point("smoke", seat, "sleeping", profile={},
                                            at=(2.0, 3.0))
        check("the sleeping clip carries the figure to (2.4, 3.0)",
              at(got, 2.4, 3.0), str(got))
        check("…the stored key 'lying' would have given None",
              room_stand.bridge_stand_point("smoke", seat, "lying", profile={},
                                            at=(2.0, 3.0)) is None)


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
    test_bridge_offset()
    test_stand_from_bridge_point()
    test_bridge_scale()
    test_ramping_rule()
    test_still_on_the_seat()
    test_effective_pose()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
