#!/usr/bin/env python3
"""Smoke run for the WORLD WRITE PATH: upsert, delete, full replace, lock.

Runs against a THROWAWAY storage directory — never touches a real world.

THE HOLE THIS CLOSES (review 2026-09-20, DATA-1). Every writer used to hand
the WHOLE world snapshot to ``_save_world_data``, which deleted every location
the snapshot did not mention, and nothing serialized the load against the
save. Two threads that had both read the world before either wrote therefore
deleted each other's fresh locations: an NPC dropping an item into a room
(``inventory.add_item_to_room`` → ``_save_locations`` → whole-world write)
erased a place the editor had created a moment earlier, silently and without a
log line. Since 2026-09-21 delete-by-absence exists in ONE function
(``replace_all_locations``), everything else upserts what it touched, and the
read-modify-write blocks hold ``world_write_lock`` from the load to the write.

Hand-derived expectations — each one is a statement about the contract, not a
recording of current output:

  [1] ``upsert_location`` writes ONE place. Seed two locations A and B, load
      the world, drop B out of the snapshot, change A, upsert A: A carries the
      change, B is STILL THERE (2 locations). Under the old semantics the same
      three lines left 1 location. Room delete-by-absence WITHIN the upserted
      location stays: a room removed from A's list is removed from the DB, and
      B's rooms are untouched.

  [2] The reserved rooms survive an upsert. ``add_location`` brings the ground
      ``__ground__`` (CLAUDE.md: the server brings it along on every location
      write). After a room add and an unrelated upsert the ground is still in
      the room list — the upsert must not be the write that loses it.

  [3] ``delete_location_row`` deletes exactly its own row plus its rooms, and
      answers False for an id that is not there. ``delete_location`` (the
      public path) still removes the place.

  [4] ``replace_all_locations`` still replaces: a snapshot with one of two
      locations leaves exactly that one. Delete-by-absence has to keep
      working — it is what a world import and a test fixture need; it is only
      no longer what a room edit gets.

  [5] CONCURRENCY. Two threads each create 25 locations of their own through
      the public API at the same time: afterwards all 50 are there. The same
      scenario played with the OLD semantics (each thread loads the world,
      appends its own place and calls ``replace_all_locations``) is run first
      as a CONTROL and MUST lose locations — that is the bug this check is
      sensitive to, demonstrated with running code rather than asserted.

  [6] An item drop while another location is created loses nothing:
      ``inventory.add_item_to_room`` on location A in one thread against
      ``add_location`` in the other, 25 rounds — all created places survive
      and the item is on A's room afterwards.

Usage:  ./.venv/bin/python scripts/smoke_world_write.py
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="world-write-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="world-write-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, add_location, add_room, delete_location,
    delete_location_row, get_location_by_id, list_locations,
    replace_all_locations, upsert_location)

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


def clear_world():
    replace_all_locations({"locations": []})


def room_ids(loc_id):
    loc = get_location_by_id(loc_id) or {}
    return sorted(str(r.get("id") or "") for r in loc.get("rooms") or [])


print("\n[1] upsert_location writes ONE place — the rest of the world stays")
clear_world()
A = add_location(name="Alpha", description="a")["id"]
B = add_location(name="Beta", description="b")["id"]
check("two places seeded", len(list_locations()), 2)

data = _load_world_data()
snapshot = [l for l in data["locations"] if l["id"] == A]   # B dropped
snapshot[0]["description"] = "a changed"
upsert_location(snapshot[0])
check("the upserted place carries the change",
      (get_location_by_id(A) or {}).get("description"), "a changed")
check("the place missing from the snapshot survives", len(list_locations()), 2)
check("…and is still readable by id", (get_location_by_id(B) or {}).get("name"),
      "Beta")

# Room delete-by-absence WITHIN the upserted location stays.
r1 = add_room(A, "Kitchen")["id"]
add_room(A, "Cellar")
check("A has ground + 2 rooms", len(room_ids(A)), 3)
loc_a = get_location_by_id(A)
loc_a["rooms"] = [r for r in loc_a["rooms"] if r["id"] != r1]
upsert_location(loc_a)
check("a room dropped from the location's list is deleted",
      r1 in room_ids(A), False)
check("…and the other rooms stay", len(room_ids(A)), 2)
check("B's rooms are untouched by A's write", len(room_ids(B)), 1)

print("\n[2] the reserved ground room survives every write")
check("a new place has the ground", GROUND_ROOM_ID in room_ids(B), True)
check("…and still has it after a room add and an upsert",
      GROUND_ROOM_ID in room_ids(A), True)
loc_a = get_location_by_id(A)
loc_a["description"] = "a again"
upsert_location(loc_a)
check("…and after one more upsert", GROUND_ROOM_ID in room_ids(A), True)

print("\n[3] deleting is explicit")
check("delete_location_row removes the row", delete_location_row(B), True)
check("…the place is gone", get_location_by_id(B), None)
check("…and only that one went", len(list_locations()), 1)
check("an unknown id answers False", delete_location_row("does-not-exist"),
      False)
check("an empty id answers False", delete_location_row(""), False)
check("delete_location (public path) removes the place",
      delete_location(A), True)
check("…world is empty", len(list_locations()), 0)

print("\n[4] replace_all_locations still replaces")
A = add_location(name="Alpha", description="a")["id"]
B = add_location(name="Beta", description="b")["id"]
replace_all_locations({"locations": [get_location_by_id(A)]})
check("the snapshot's place stays", (get_location_by_id(A) or {}).get("name"),
      "Alpha")
check("the place missing from the snapshot is deleted",
      get_location_by_id(B), None)
check("…exactly one location left", len(list_locations()), 1)

print("\n[5] two threads creating places at the same time")
ROUNDS = 25


def run_threads(fn_a, fn_b):
    barrier = threading.Barrier(2)
    errors = []

    def wrap(fn, tag):
        try:
            barrier.wait()
            for i in range(ROUNDS):
                fn(i)
        except Exception as e:                      # noqa: BLE001
            errors.append(f"{tag}: {e!r}")

    ta = threading.Thread(target=wrap, args=(fn_a, "A"))
    tb = threading.Thread(target=wrap, args=(fn_b, "B"))
    ta.start(); tb.start(); ta.join(); tb.join()
    return errors


# CONTROL: the OLD semantics — load the whole world, append, full replace.
# This is what every writer did before 2026-09-21 and it MUST lose places,
# or this check could not tell the two apart.
clear_world()


def old_style(tag):
    def _add(i):
        data = _load_world_data()
        data["locations"].append({"id": f"{tag}{i:03d}", "name": f"{tag}{i}",
                                  "description": "", "rooms": []})
        replace_all_locations(data)
    return _add


errs = run_threads(old_style("oldA"), old_style("oldB"))
check("control run raised nothing", errs, [])
control_count = len(list_locations())
check("CONTROL: the old full-replace semantics loses places",
      control_count < 2 * ROUNDS, True)
print(f"      (control kept {control_count} of {2 * ROUNDS})")

# The real API.
clear_world()


def new_style(tag):
    def _add(i):
        add_location(name=f"{tag}{i}", description="", create_new=True)
    return _add


errs = run_threads(new_style("newA"), new_style("newB"))
check("concurrent run raised nothing", errs, [])
check("every concurrently created place is there",
      len(list_locations()), 2 * ROUNDS)
names = sorted(l["name"] for l in list_locations())
check("…and they are the expected names",
      names == sorted([f"newA{i}" for i in range(ROUNDS)]
                      + [f"newB{i}" for i in range(ROUNDS)]), True)

print("\n[6] an item drop against a place being created")
clear_world()
from app.models.inventory import (  # noqa: E402
    add_item, add_item_to_room, get_room_items)

HOME = add_location(name="Home", description="")["id"]
ROOM = add_room(HOME, "Hall")["id"]
ITEM = add_item(name="Lantern", description="", item_id="item_lantern")["id"]


def drop(i):
    add_item_to_room(HOME, ROOM, ITEM, quantity=1)


def create(i):
    add_location(name=f"Place{i}", description="", create_new=True)


errs = run_threads(drop, create)
check("run raised nothing", errs, [])
check("every created place survived the item drops",
      len([l for l in list_locations() if l["name"].startswith("Place")]),
      ROUNDS)
check("the place the item went into is still there",
      (get_location_by_id(HOME) or {}).get("name"), "Home")
check("the item is on the room", [i["item_id"] for i in
                                  get_room_items(HOME, ROOM)], [ITEM])
check("…with every drop counted",
      get_room_items(HOME, ROOM)[0]["quantity"], ROUNDS)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
