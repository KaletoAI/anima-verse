#!/usr/bin/env python3
"""Party room/location invariants against a disposable world.

Usage: ./.venv/bin/python scripts/smoke_party_room_guard.py

Hand-derived expectations: A owns a1/a2, ground and floor 1; B owns b1.
[a] Writing b1 at A preserves a1, with one warning and no writes/events.
Outdoors every nonempty room is foreign. [b] a2, ground, floor 1 and empty
are accepted at A; floor 9 is absent and refused. [c] A leader entering a2
pulls its A follower, while a stale B follower retains b1 (even when the
leader enters the shared reserved ground id). [d] An independent A->B move
removes a follower: with two followers the other survives, with one the party
dissolves. A same-location write retains membership. [e] A leader's A->B move
pulls its follower to B/b1 and preserves both roles, including a programmed
arrival (_preserve_movement_target=True). Removing each corresponding guard
breaks these observations; expectations use fixture literals, not helpers.
"""
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="party-room-guard-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(STORAGE / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(STORAGE / "rig.fbx")
from app.core import paths
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import db
db.init_schema()
from app.core import party_engine as P
from app.models import character as C
from app.models.world import upsert_location

FAILURES = []
CHECKED = 0


def check(label, ok):
    global CHECKED
    CHECKED += 1
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok:
        FAILURES.append(label)


def seed():
    for name in ("demo", "demo_near", "demo_far"):
        P.leave_party(name)
        assert C.save_character_profile(name, {
            "character_name": name, "current_location": "A", "current_room": "a1",
        }, create_new=True)


def main():
    for loc, rooms in (("A", ["a1", "a2", "__ground__", "__floor__1"]),
                       ("B", ["b1", "__ground__"])):
        assert upsert_location({"id": loc, "name": loc, "entry_room": rooms[0],
                                "rooms": [{"id": r, "name": r} for r in rooms]},
                               sync_world=False)
    seed()
    before = C.get_character_profile("demo")
    with patch.object(C, "save_character_profile", wraps=C.save_character_profile) as writes, \
            patch("app.core.hooks.emit") as emits, \
            patch.object(C.logger, "warning") as warnings:
        result = C.save_character_current_room("demo", "b1")
        check("[a] foreign room leaves whole profile unchanged",
              C.get_character_profile("demo") == before)
        check("[a] refusal returns None and writes/emits nothing",
              result is None and not writes.called and not emits.called)
        check("[a] exactly one warning", warnings.call_count == 1)
    for room in ("a2", "__ground__", "__floor__1", ""):
        C.save_character_current_room("demo", room)
        check(f"[b] accepts {room!r}", C.get_character_current_room("demo") == room)
    C.save_character_current_room("demo", "__floor__9")
    check("[b] absent corridor refused", C.get_character_current_room("demo") == "")
    C.save_character_profile("demo", {"current_location": "", "current_room": ""})
    C.save_character_current_room("demo", "__ground__")
    check("[a] outdoors refuses reserved room", C.get_character_current_room("demo") == "")
    seed()
    P.add_to_party("demo", "demo_near")
    P.add_to_party("demo", "demo_far")
    # Reproduce legacy inconsistent membership without the independent-move setter.
    C.save_character_profile("demo_far", {"current_location": "B", "current_room": "b1"})
    C.save_character_current_room("demo", "a2")
    check("[c] nearby follower follows", C.get_character_current_room("demo_near") == "a2")
    check("[c] distant follower untouched", C.get_character_current_room("demo_far") == "b1")
    C.save_character_current_room("demo", "__ground__")
    check("[c] distant follower ignores shared reserved id",
          C.get_character_current_room("demo_far") == "b1")
    seed()
    P.add_to_party("demo", "demo_near")
    P.add_to_party("demo", "demo_far")
    C.save_character_current_location("demo_near", "A", _skip_compliance=True)
    check("[d] same-location write keeps follower", P.is_party_follower("demo_near"))
    C.save_character_current_location("demo_near", "B", _skip_compliance=True)
    check("[d] independent follower leaves", not P.is_in_party("demo_near"))
    check("[d] remaining party survives", P.party_followers("demo") == ["demo_far"])
    C.save_character_current_location("demo_far", "B", _skip_compliance=True)
    check("[d] last follower leaving dissolves party", not P.is_in_party("demo"))
    for programmed in (False, True):
        seed()
        P.add_to_party("demo", "demo_near")
        C.save_character_current_location("demo", "B", _skip_compliance=True,
                                         _preserve_movement_target=programmed)
        check(f"[e] leader move drags follower (programmed={programmed})",
              C.get_character_current_location("demo_near") == "B"
              and C.get_character_current_room("demo_near") == "b1")
        check(f"[e] membership retained (programmed={programmed})",
              P.is_party_leader("demo") and P.is_party_follower("demo_near"))
    print(f"{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    return bool(FAILURES)


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
