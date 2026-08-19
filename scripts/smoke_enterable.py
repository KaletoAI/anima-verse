#!/usr/bin/env python3
"""Smoke check: the server names the lock state, per avatar (Etappe C1).

Usage:  ./.venv/bin/python scripts/smoke_enterable.py

Runs against a THROWAWAY storage directory — it never touches a real world.
Every expectation below is derived BY HAND from the rules in
development_instructions/plan-betreten-und-tueren.md § 5 Etappe C, never
recorded from an implementation run.

The rule, in one line: what the player UI may offer is what the route would
allow — so `enterable` comes from the very functions the room change and the
step decide with, and it lives in the per-avatar payload, never in the
signature-cached scene recipe.

The seed (hand-built):

    A "Alder Camp"    grid (2, 2)  entry_room "hall"
        rooms: hall, cellar, __ground__ (the ground room, unnamed)
    B "Birch Hollow"  grid (2, 1)  north of A,  opening on its S edge
    C "Cedar Ridge"   grid (3, 2)  east  of A,  opening on its N edge only
    D "Dusk Hollow"   grid (1, 2)  west  of A,  opening on its E edge,
                                   accessible_when ["has_item:silver_key"]
    E "Ember Gate"    grid (2, 3)  south of A,  opening on its N edge

  (grid coordinates stay non-negative: a negative one means "unplaced" to
  update_location_position, which would leave the neighbour off the map.)

    demo_avatar stands at A in room "hall", language "en", owns nothing.

    block rule "Locked cellar"  scope room, A/["cellar"], condition "always",
                                message "The cellar door is locked."
    block rule "Barred gate"    scope location, E,        condition "always",
                                message "The gate is barred."

Part 1 — rooms of the avatar's location (world_ops.build_avatar_rooms).
  A room chip carries {id, name, is_entry, is_ground, enterable, reason};
  `reason` is empty exactly when `enterable` is true.
    hall       -> True,  ""                         no rule names it
    cellar     -> False, "The cellar door is locked."   the rule's message,
                                                    localized by check_access
    __ground__ -> True,  ""                         no rule names it either;
                                                    the ground is a room and
                                                    is CHECKED like any other
  Names: the unnamed ground falls back to the translated word ("Outside"),
  is_entry is true for "hall" alone, is_ground for "__ground__" alone.

Part 2 — the ground is not exempt. Adding
    block rule "Yard closed" scope room, A/["__ground__"], "always",
                             message "Guards keep you off the yard."
  flips exactly one chip:
    hall       -> True,  ""
    cellar     -> False, "The cellar door is locked."
    __ground__ -> False, "Guards keep you off the yard."

Part 3 — a rule that forbids LEAVING says nothing about the rooms INSIDE
  the location: /play/enter-room does not call check_leave. Adding
    block rule "Locked in"  action leave, scope location, A, "always",
                            message "The guards will not let you out."
  leaves every chip exactly as Part 2 left it:
    hall -> True, cellar -> locked, __ground__ -> locked.

  (The grid compass this check once covered — neighbours, per-direction
  gates, the step route — is GONE since E3 Task 5: the world is a metre
  plane and the avatar travels to a NAMED place over POST /play/travel,
  covered by scripts/smoke_avatar_travel.py.)

"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="enterable-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="enterable-smoke-clips-"))
# Never look at the repo's real animation clips (they are user data).
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core.world_ops import build_avatar_rooms  # noqa: E402
from app.models.account import set_active_character  # noqa: E402
from app.models.character import save_character_profile  # noqa: E402
from app.models.rules import add_rule  # noqa: E402
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location,
    get_location_by_id, update_location_position)

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def place(name: str, grid, **extra) -> str:
    loc = add_location(name=name, description=f"{name} for the enterable smoke.")
    loc_id = loc["id"]
    update_location_position(loc_id, grid[0], grid[1])
    if extra:
        data = _load_world_data()
        for entry in data.get("locations", []):
            if entry.get("id") == loc_id:
                entry.update(extra)
                break
        _save_world_data(data)
    return loc_id


A = place("Alder Camp", (2, 2),
          entry_room="hall",
          rooms=[{"id": "hall", "name": "Hall"},
                 {"id": "cellar", "name": "Cellar"},
                 {"id": GROUND_ROOM_ID, "name": ""}])
B = place("Birch Hollow", (2, 1),
          map3d={"boundary_openings": [{"edge": 2}]})
C = place("Cedar Ridge", (3, 2),
          map3d={"boundary_openings": [{"edge": 0}]})
D = place("Dusk Hollow", (1, 2),
          map3d={"boundary_openings": [{"edge": 1}]},
          accessible_when=["has_item:silver_key"])
E = place("Ember Gate", (2, 3),
          map3d={"boundary_openings": [{"edge": 0}]})

save_character_profile("demo_avatar",
                       {"current_location": A, "current_room": "hall",
                        "language": "en"},
                       create_new=True)
set_active_character("demo_avatar")

add_rule({"type": "block", "action": "enter", "name": "Locked cellar",
          "condition": "always", "message": "The cellar door is locked.",
          "target": {"scope": "room", "location_id": A, "room_ids": ["cellar"]}})
add_rule({"type": "block", "action": "enter", "name": "Barred gate",
          "condition": "always", "message": "The gate is barred.",
          "target": {"scope": "location", "location_id": E}})


def rooms(lang: str = "en") -> dict:
    out = build_avatar_rooms("demo_avatar", get_location_by_id(A), lang)
    return {r["id"]: r for r in out}


def patch(loc_id: str, **fields) -> None:
    """Overwrite fields of a stored location (seed edits, part 6)."""
    data = _load_world_data()
    for entry in data.get("locations", []):
        if entry.get("id") == loc_id:
            entry.update(fields)
            break
    _save_world_data(data)


def main() -> int:
    print("\n[1] the rooms of the avatar's location")
    r = rooms()
    check("chips", sorted(r), sorted(["hall", "cellar", GROUND_ROOM_ID]))
    check("hall enterable", (r["hall"]["enterable"], r["hall"]["reason"]),
          (True, ""))
    check("cellar enterable",
          (r["cellar"]["enterable"], r["cellar"]["reason"]),
          (False, "The cellar door is locked."))
    check("ground enterable",
          (r[GROUND_ROOM_ID]["enterable"], r[GROUND_ROOM_ID]["reason"]),
          (True, ""))
    check("is_entry marks the hall alone",
          sorted(k for k, v in r.items() if v["is_entry"]), ["hall"])
    check("is_ground marks the ground alone",
          sorted(k for k, v in r.items() if v["is_ground"]), [GROUND_ROOM_ID])
    check("the unnamed ground falls back to the translated word",
          r[GROUND_ROOM_ID]["name"], "Outside")

    print("\n[2] a rule on the ground locks the ground")
    add_rule({"type": "block", "action": "enter", "name": "Yard closed",
              "condition": "always", "message": "Guards keep you off the yard.",
              "target": {"scope": "room", "location_id": A,
                         "room_ids": [GROUND_ROOM_ID]}})
    r = rooms()
    check("hall untouched", (r["hall"]["enterable"], r["hall"]["reason"]),
          (True, ""))
    check("cellar untouched",
          (r["cellar"]["enterable"], r["cellar"]["reason"]),
          (False, "The cellar door is locked."))
    check("ground now locked",
          (r[GROUND_ROOM_ID]["enterable"], r[GROUND_ROOM_ID]["reason"]),
          (False, "Guards keep you off the yard."))

    print("\n[3] a leave rule leaves the room chips alone")
    add_rule({"type": "block", "action": "leave",
              "name": "Locked in", "condition": "always",
              "message": "The guards will not let you out.",
              "target": {"scope": "location", "location_id": A}})
    r = rooms()
    check("the room chips are untouched by a leave rule",
          {k: (v["enterable"], v["reason"]) for k, v in sorted(r.items())},
          {GROUND_ROOM_ID: (False, "Guards keep you off the yard."),
           "cellar": (False, "The cellar door is locked."),
           "hall": (True, "")})

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} of {CHECKED} checks: {FAILURES}")
        return 1
    print(f"All {CHECKED} checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(CLIPS, ignore_errors=True)
