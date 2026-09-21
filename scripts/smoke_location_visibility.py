#!/usr/bin/env python3
"""Smoke run for LOCATION/ROOM VISIBILITY with a shared context (DATA-8).

Runs against a THROWAWAY storage directory — never touches a real world.

THE HOLE THIS CLOSES. ``visibility_context(character)`` exists to fetch the
two things the visibility predicate reads — the character's ``known_locations``
and its inventory — ONCE for a caller that tests many places. The worldmap
payload and the rules engine used it; ``list_locations_for_character`` did not,
and it is the one called per chat turn and per AgentLoop thought. It asked
``location_visible_to_character`` per location AND per ROOM (the room check
called the location check again), each of those going through
``get_character_config`` — which loads the full character profile twice — plus
an inventory read for the knowledge-item gate. A 30-location world with 7 rooms
each came to ~240 predicate calls and ~480 profile loads, per turn.

The fix must not change a single answer, so this file compares the NEW path
against the OLD one on a world built to hit every branch:

    OPEN     no knowledge item, known           -> visible
    SECRET   knowledge item HELD, known         -> visible
    LOCKED   knowledge item NOT held, known     -> hidden (item gate)
    UNKNOWN  no knowledge item, NOT known       -> hidden (known gate)

  and inside OPEN three rooms:

    hall     no room item                       -> visible
    vault    room item HELD                     -> visible
    cellar   room item NOT held                 -> hidden

Expected, derived by hand from those rules:

  [1] ``list_locations_for_character`` returns OPEN and SECRET, in the
      world's own order, and OPEN carries the ground room, hall and vault but
      not cellar.
  [2] The new path (context passed down) and the old path (context=None, one
      lookup per call) agree location by location and room by room — that is
      the whole claim of the change.
  [3] The context is not a cache with its own opinion: a character with an
      empty ``known_locations`` sees nothing, and picking up the missing key
      makes LOCKED appear on the very next call.
  [4] ``room_visible_to_character`` with a context still refuses a room of an
      invisible location — the location gate is asked first, with the same
      context.

Usage:  ./.venv/bin/python scripts/smoke_location_visibility.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="visibility-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="visibility-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models.character import (  # noqa: E402
    save_character_profile, set_known_locations)
from app.models.inventory import add_item, add_to_inventory  # noqa: E402
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, add_location, add_room, get_location_by_id,
    list_locations, list_locations_for_character,
    location_visible_to_character, room_visible_to_character,
    upsert_location, visibility_context)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


CHAR = "demo"
save_character_profile(CHAR, {"name": CHAR}, create_new=True)

KEY = add_item(name="Brass key", description="", item_id="item_brass_key")["id"]
VAULT_KEY = add_item(name="Vault key", description="",
                     item_id="item_vault_key")["id"]
MISSING = add_item(name="Lost key", description="", item_id="item_lost_key")["id"]
add_to_inventory(CHAR, KEY)
add_to_inventory(CHAR, VAULT_KEY)


def place(name, knowledge_item=""):
    lid = add_location(name=name, description="")["id"]
    if knowledge_item:
        loc = get_location_by_id(lid)
        loc["knowledge_item_id"] = knowledge_item
        upsert_location(loc)
    return lid


OPEN = place("Open")
SECRET = place("Secret", KEY)
LOCKED = place("Locked", MISSING)
UNKNOWN = place("Unknown")

HALL = add_room(OPEN, "Hall")["id"]
VAULT = add_room(OPEN, "Vault")["id"]
CELLAR = add_room(OPEN, "Cellar")["id"]
loc = get_location_by_id(OPEN)
for r in loc["rooms"]:
    if r["id"] == VAULT:
        r["knowledge_item_id"] = VAULT_KEY
    if r["id"] == CELLAR:
        r["knowledge_item_id"] = MISSING
upsert_location(loc)

set_known_locations(CHAR, [OPEN, SECRET, LOCKED])

print("\n[1] the filtered list")
visible = list_locations_for_character(CHAR)
check("only the places both gates let through",
      [l["name"] for l in visible], ["Open", "Secret"])
open_rooms = [l for l in visible if l["id"] == OPEN][0]["rooms"]
check("…and inside them only the rooms the item gate lets through",
      sorted(r["id"] for r in open_rooms),
      sorted([GROUND_ROOM_ID, HALL, VAULT]))
check("the hidden room is really gone", CELLAR in
      [r["id"] for r in open_rooms], False)


def old_path():
    """What the function did before the context was threaded through."""
    out = []
    for loc in list_locations():
        if not location_visible_to_character(CHAR, loc):
            continue
        rooms = [r for r in (loc.get("rooms") or [])
                 if room_visible_to_character(CHAR, loc, r)]
        out.append({**loc, "rooms": rooms})
    return out


def shape(entries):
    return [(e["id"], sorted(r["id"] for r in e["rooms"])) for e in entries]


print("\n[2] new path == old path")
check("same locations, same rooms", shape(list_locations_for_character(CHAR)),
      shape(old_path()))

print("\n[3] the context is fetched per call, not remembered")
set_known_locations(CHAR, [])
check("a character that knows nowhere sees nothing",
      list_locations_for_character(CHAR), [])
set_known_locations(CHAR, [OPEN, SECRET, LOCKED])
check("…and gets its places back when the list returns",
      [l["name"] for l in list_locations_for_character(CHAR)],
      ["Open", "Secret"])
check("LOCKED is still gated by the item it lacks",
      [l["name"] for l in list_locations_for_character(CHAR)] == ["Open",
                                                                  "Secret"],
      True)
add_to_inventory(CHAR, MISSING)
check("picking the key up opens it on the next call",
      [l["name"] for l in list_locations_for_character(CHAR)],
      ["Locked", "Open", "Secret"])
check("new path still equals old path after the pickup",
      shape(list_locations_for_character(CHAR)), shape(old_path()))

print("\n[4] the room check asks the location gate with the same context")
ctx = visibility_context(CHAR)
unknown_loc = get_location_by_id(UNKNOWN)
unknown_room = {"id": "r1", "name": "Room"}
check("a room of an unknown location stays invisible",
      room_visible_to_character(CHAR, unknown_loc, unknown_room, ctx), False)
check("…with and without a context alike",
      room_visible_to_character(CHAR, unknown_loc, unknown_room), False)
open_loc = get_location_by_id(OPEN)
cellar = [r for r in open_loc["rooms"] if r["id"] == CELLAR][0]
hall = [r for r in open_loc["rooms"] if r["id"] == HALL][0]
check("a gated room of a visible location: context answer == plain answer",
      room_visible_to_character(CHAR, open_loc, cellar, ctx),
      room_visible_to_character(CHAR, open_loc, cellar))
check("an ungated room of a visible location is visible",
      room_visible_to_character(CHAR, open_loc, hall, ctx), True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
