#!/usr/bin/env python3
"""Smoke run for the WORLD READ CACHE (review 2026-09-20, DATA-9).

Runs against a THROWAWAY storage directory — never touches a real world.

THE HOLE THIS CLOSES. ``get_location_by_id`` (90 call sites), ``list_locations``
(54) and ``resolve_location`` (36) each re-read and re-parsed the WHOLE world:
one SELECT over all locations, a ``json.loads`` per ``meta`` blob and a rooms
query per column-backed place — the travel ticker did it once per traveller
every five seconds, a chat turn dozens of times. The parse is now cached and
invalidated by a generation counter that every writer bumps.

The cache is only allowed to exist if it cannot be TOLD APART from a fresh
read, which is what this file pins:

  [1] The reader owns what it gets. Half the callers mutate the result (load →
      change one location → save), so a mutation of a returned dict — and of a
      nested room/layout dict, which a shallow copy would share — must not be
      visible to the next reader. Expected: the next read shows the STORED
      value, in both cases.

  [2] A write is visible immediately: upsert, delete and full replace each
      change what the very next ``list_locations``/``get_location_by_id``
      answers. (Without the generation bump the reader would keep serving the
      pre-write parse for the rest of the process's life.)

  [3] Two readers do not share objects: mutating reader A's result leaves
      reader B's untouched.

  [4] A STORAGE SWITCH is not a stale cache. After ``paths.init`` to a second
      throwaway world the reader must answer with THAT world's places, not the
      first one's — the cache is keyed by the DB path for exactly this, and
      the smoke scripts re-init storage all the time. Note what the switch
      costs: ``db.get_connection`` keeps ONE connection per thread, opened
      against the path of the first call, so a real in-process world switch
      also has to drop those connections (the server does it by restarting).
      The check clears them by hand — its subject is the cache, not the
      connection pool.

  [5] Timing, printed not asserted (a smoke must not fail on a busy machine):
      1000 ``get_location_by_id`` calls on a 30-location world, cold vs warm,
      plus the deepcopy alternative for the record. Expected shape: the warm
      run is faster by a wide margin, because it parses ONE location instead
      of thirty.

Usage:  ./.venv/bin/python scripts/smoke_world_cache.py
"""
import copy
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="world-cache-smoke-"))
STORAGE2 = Path(tempfile.mkdtemp(prefix="world-cache-smoke-2-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="world-cache-smoke-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models.world import (  # noqa: E402
    _load_world_data, add_location, add_room, delete_location_row,
    get_location_by_id, list_locations, replace_all_locations,
    upsert_location)

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


print("\n[1] a reader owns what it gets")
A = add_location(name="Alpha", description="stored")["id"]
ROOM = add_room(A, "Hall")["id"]
loc = get_location_by_id(A)
loc["description"] = "mutated by the caller"
loc["rooms"][0]["name"] = "mutated room"
loc.setdefault("map3d", {})["plan_width_m"] = 99
check("a mutated result does not reach the next reader",
      (get_location_by_id(A) or {}).get("description"), "stored")
check("…not through a nested room either",
      [r["name"] for r in (get_location_by_id(A) or {}).get("rooms") or []
       if r["id"] == ROOM], ["Hall"])
check("…and no key appears that was never written",
      "map3d" in (get_location_by_id(A) or {}), False)
lst = list_locations()
lst[0]["description"] = "mutated via list_locations"
check("list_locations hands out copies too",
      list_locations()[0]["description"], "stored")
wd = _load_world_data()
wd["locations"][0]["description"] = "mutated via _load_world_data"
check("_load_world_data hands out copies too",
      _load_world_data()["locations"][0]["description"], "stored")

print("\n[2] a write is visible to the very next read")
loc = get_location_by_id(A)
loc["description"] = "written"
upsert_location(loc)
check("upsert is visible", (get_location_by_id(A) or {}).get("description"),
      "written")
check("…in list_locations as well", list_locations()[0]["description"],
      "written")
B = add_location(name="Beta", description="b")["id"]
check("a new place is visible", len(list_locations()), 2)
delete_location_row(B)
check("a delete is visible", get_location_by_id(B), None)
check("…and the list follows", len(list_locations()), 1)
replace_all_locations({"locations": []})
check("a full replace is visible", list_locations(), [])

print("\n[3] two readers do not share objects")
A = add_location(name="Alpha", description="stored")["id"]
r1 = get_location_by_id(A)
r2 = get_location_by_id(A)
r1["description"] = "only mine"
check("reader B is unaffected", r2["description"], "stored")
check("…and they are two objects", r1 is r2, False)

print("\n[4] switching storage does not serve the old world")
check("world one has its place", [l["name"] for l in list_locations()],
      ["Alpha"])


def switch_to(storage):
    """What a world switch means in this process: the storage root AND the
    thread-local DB connections, which are opened once per thread."""
    paths.init(storage)
    db._connections.clear()
    db.init_schema()


switch_to(STORAGE2)
check("world two starts empty", list_locations(), [])
add_location(name="Gamma", description="")
check("world two has its own place", [l["name"] for l in list_locations()],
      ["Gamma"])
switch_to(STORAGE)
check("back in world one, its place is there again",
      [l["name"] for l in list_locations()], ["Alpha"])

print("\n[5] timing — 1000 get_location_by_id calls on a 30-location world")
switch_to(STORAGE2)
replace_all_locations({"locations": []})
ids = []
for i in range(30):
    lid = add_location(name=f"Place{i}", description="x" * 400)["id"]
    for r in range(6):
        add_room(lid, f"Room{r}")
    ids.append(lid)
target = ids[len(ids) // 2]

# Cold: no cache at all — what every call paid before the fix.
import app.models.world as world_mod  # noqa: E402

t0 = time.perf_counter()
for _ in range(1000):
    for location in world_mod._read_world_data_uncached().get("locations", []):
        if location.get("id") == target:
            break
cold = time.perf_counter() - t0

get_location_by_id(target)          # warm it
t0 = time.perf_counter()
for _ in range(1000):
    get_location_by_id(target)
warm = time.perf_counter() - t0

one = get_location_by_id(target)
t0 = time.perf_counter()
for _ in range(1000):
    copy.deepcopy(one)
deep = time.perf_counter() - t0

whole = list_locations()
t0 = time.perf_counter()
for _ in range(100):
    list_locations()
list_warm = (time.perf_counter() - t0) * 10
t0 = time.perf_counter()
for _ in range(100):
    copy.deepcopy(whole)
list_deep = (time.perf_counter() - t0) * 10

print(f"      get_location_by_id, uncached : {cold * 1000:8.1f} ms / 1000")
print(f"      get_location_by_id, cached   : {warm * 1000:8.1f} ms / 1000")
print(f"      (deepcopy of one location    : {deep * 1000:8.1f} ms / 1000)")
print(f"      list_locations, cached       : {list_warm * 1000:8.1f} ms / 1000")
print(f"      (deepcopy of the whole world : {list_deep * 1000:8.1f} ms / 1000)")
check("the cached single-id read is the cheaper one", warm < cold, True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
for f in FAILURES:
    print(f"  FAILED: {f}")
sys.exit(1 if FAILURES else 0)
