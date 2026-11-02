#!/usr/bin/env python3
"""Smoke: a character put back into a room stands IN that room
(docs/schnittstellen-3d.md § A1.4, the standing-point rule T4).

Usage:  ./.venv/bin/python scripts/smoke_room_return_point.py

The finding (2026-11-02, reported by the native 3D client): two characters
were drawn in the bathroom while their ``current_room`` named the guest room
next door. Waking from the off-map sleep wrote the LOCATION CENTRE as the
point and the stored return room as the room — the centre lies in whichever
room the plan puts there, and nobody looked for a point in the return room.

THE FIXTURE (world metres = location pin + layout coordinate, no yaw):
    pin (100, 50)
    bath   layout x -3, y -4, 6 x 8  -> (97, 46) .. (103, 54)  holds the pin
    guest  layout x  3, y -4, 6 x 8  -> (103, 46) .. (109, 54)
    closet layout x -3, y  4, .6 x .6 -> (97, 54) .. (97.6, 54.6)
    no furniture, no openings, nobody else in the rooms.

THE RULE (room_stand.pick_stand): grid 0.25 anchored on the grid, wall
clearance 0.35, the free candidate nearest the current point wins.

[1] WAKE INTO THE GUEST ROOM. The return point is the pin (100, 50), outside
    the guest room. Guest candidates need x >= 103 + 0.35 = 103.35, so the
    first grid column is x = 103.50; z = 50.00 is a grid row 4 m from both z
    walls. Nearest: (103.50, 50.00), 3.50 m away. Old code: (100, 50), in the
    bath.
[2] APPEAR IN THE WORLD (avatar takeover of a never-placed character). The
    world's only location is the Villa, its declared entry room the guest
    room, so the search starts from the pin again — but [1]'s character
    stands on (103.50, 50.00) and a neighbour needs 0.70 m (MATE_CLEAR_M).
    Column x = 103.50 then needs |z - 50| >= 0.70: grid rows 49.25 and 50.75,
    both sqrt(3.5^2 + 0.75^2) = 3.58 m from the pin; column 103.75 needs
    |dz| >= sqrt(0.49 - 0.0625) = 0.65, i.e. the same rows, farther away. The
    tie: wall clearance 0.50 for both (the x wall at 103), equal x, smaller z
    wins -> (103.50, 49.25). Old code: no point at all.
[3] A ROOM WITH NO FREE POINT. The closet is 0.6 m wide: no point keeps
    0.35 m from both side walls (0.6 < 0.7), so pick_stand answers None. A
    character walking in from (100, 50) must still land inside it: the
    interior point is the area centroid of the square, (97.30, 54.30). Old
    code: stays at (100, 50), in the bath.
[4] COUNTER-CHECK. A point already inside a room with no free point is left
    alone: ``_inside_fallback`` answers None for (97.30, 54.30) in the closet,
    and for any point in a room without a hull (the ground).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="room-return-point-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
(ROOT / "clips").mkdir()
from app.core import paths  # noqa: E402
paths.init(ROOT / "world")
from app.core import config  # noqa: E402
(ROOT / "world" / "config.json").write_text(json.dumps({"random_events": {
    "enabled": False, "entry_roll_enabled": False, "resolution_proactive": False}}))
config.load(ROOT / "world" / "config.json")
from app.core import db  # noqa: E402
db.init_schema()

from app.core import room_stand as S  # noqa: E402
from app.models import character as C, world as W  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(pos, x: float, z: float) -> bool:
    return pos is not None and abs(pos["x"] - x) < 1e-6 and abs(pos["z"] - z) < 1e-6


loc = W.add_location("Villa", "Throwaway geometry", rooms=[
    {"id": "bath", "name": "Bath", "layout": {"x": -3, "y": -4, "w": 6, "d": 8}},
    {"id": "guest", "name": "Guest", "layout": {"x": 3, "y": -4, "w": 6, "d": 8}},
    {"id": "closet", "name": "Closet", "layout": {"x": -3, "y": 4, "w": .6, "d": .6}}])
loc.update(pos_x=100, pos_z=50, entry_room="guest",
           map3d={"plan_width_m": 20, "boundary": [[-6, -6], [12, -6], [12, 8], [-6, 8]]})
W.upsert_location(loc, sync_world=True)
LOC = loc["id"]


def person(name: str, room: str = "") -> str:
    assert C.save_character_profile(name, {"character_name": name, "template": "npc-temporary"},
                                    create_new=True)
    if room:
        C.save_character_current_location(name, LOC)
        C.save_character_current_room(name, room)
    return name


def test_wake() -> None:
    print("\n[1] waking from the off-map sleep into the guest room")
    name = person("wake_person", "guest")
    check("the fixture's guest room holds the character before the sleep",
          C.get_character_current_room(name) == "guest")
    check("the off-map sleep clears the point", C.enter_offmap_sleep(name)
          and C.get_character_pos(name) is None)
    check("waking brings the character back", C.wake_from_offmap(name))
    pos = C.get_character_pos(name)
    check("…into the guest room", C.get_character_current_room(name) == "guest")
    check("…standing at (103.50, 50.00), not on the pin in the bath", near(pos, 103.5, 50.0), str(pos))


def test_appear() -> None:
    print("\n[2] appearing in the world")
    name = person("appear_person")
    check("appear_in_world places the character", C.appear_in_world(name))
    pos = C.get_character_pos(name)
    check("…in the entry room", C.get_character_current_room(name) == "guest")
    check("…standing at (103.50, 49.25), clear of [1]'s character", near(pos, 103.5, 49.25), str(pos))


def test_no_free_point() -> None:
    print("\n[3] a room with no free standing point")
    poly = S.room_geometry(LOC, "closet")[0]
    check("the closet offers no free point", S.pick_stand(poly, [], [], [], (97.3, 54.3)) is None)
    name = person("closet_person", "bath")
    C.set_character_pos(name, 100, 50)
    C.save_character_current_room(name, "closet")
    pos = C.get_character_pos(name)
    check("walking in from the bath lands on the closet's interior point (97.30, 54.30)",
          near(pos, 97.3, 54.3), str(pos))


def test_counter() -> None:
    print("\n[4] counter-check: nothing to fix")
    check("a point inside the closet stays", S._inside_fallback(LOC, "closet", (97.3, 54.3)) is None)
    check("the ground has no hull, nothing is moved",
          S._inside_fallback(LOC, "__ground__", (0.0, 0.0)) is None)


def main() -> int:
    print("Smoke: a character put back into a room stands in that room")
    test_wake()
    test_appear()
    test_no_free_point()
    test_counter()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
