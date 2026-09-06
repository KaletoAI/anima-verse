#!/usr/bin/env python3
"""Smoke run for metre-based location placement (Seamless World, E1 Task 2).

Runs against a THROWAWAY storage directory — never touches a real world.

Hand-derived expectations:

  [1] A new location starts unplaced: pos_x is None, pos_z is None,
      yaw_deg 0.0; the dict carries NO grid_x/grid_y keys.
  [2] update_location_position(id, 12.5, -3.25, 90.0) -> reloaded dict has
      exactly these values (floats, not ints).
  [3] update_location_position(id, 100.0, 100.0) (yaw omitted) keeps
      yaw_deg 90.0 — position and rotation are independent dials.
  [4] update_location_position(id, None, None) unplaces: pos_x/pos_z None,
      yaw_deg reset to 0.0 (an unplaced location has no orientation).
  [5] Persistence survives a fresh connection: a SECOND location placed at
      (30.0, 40.0) without a yaw reads back from the DB columns as
      pos_x 30.0, pos_z 40.0, yaw_deg 0.0 — truth in the meta blob AND in
      the columns agree. Derived by hand: update_location_position writes
      both, and a location that never had a rotation keeps the contract's
      0.0 when the yaw argument is omitted.
  [6] A location placed WITHOUT a yaw still HAS the key: "yaw_deg" in loc is
      True and the value is 0.0. Checked with `in`, not `.get(..., 0.0)` —
      the default in a .get would mask exactly the missing key. The contract
      is `yaw_deg: float`, never absent, never None.
  [7] Rounding: update_location_position(id, 1.005678, 2.0, -90.0) stores
      pos_x 1.01 (2 decimals = centimetres) and yaw_deg 270.0
      (1 decimal, modulo 360 — so a negative angle comes back positive).
  [8] Non-finite positions raise ValueError and persist NOTHING. NaN and
      Infinity are legal JSON literals for stdlib json.loads (which parses
      every request body), and round(nan) is still NaN — so without an
      explicit isfinite guard ONE PATCH stores NaN, after which every
      response containing that location 500s (Starlette encodes with
      allow_nan=False). Vectors: pos_x NaN, pos_z inf, yaw_deg NaN on
      update_location_position. After each one the location is re-read: it
      must still sit at the values from [7] (1.01 / 2.0 / 270.0), and the
      whole location list must render under allow_nan=False.

  Transit places, templates and their copies are gone (2026-09-06,
  plan-rueckbau-2d-karte.md E5), so there is no clone placement, no boot
  clone cleanup and no clone NaN vector left to check here.

Usage:  ./.venv/bin/python scripts/smoke_location_placement.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="placement-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="placement-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.models.world import (  # noqa: E402
    _load_world_data, add_location, get_location, update_location_position)

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


print("[1] fresh location is unplaced")
loc = add_location(name="Placement Probe", description="smoke")
lid = loc["id"]
loc = get_location(lid)
check("pos_x", loc.get("pos_x"), None)
check("pos_z", loc.get("pos_z"), None)
check("yaw_deg", loc.get("yaw_deg", 0.0), 0.0)
check("no grid keys", "grid_x" in loc or "grid_y" in loc, False)

print("[2] place with yaw")
update_location_position(lid, 12.5, -3.25, 90.0)
loc = get_location(lid)
check("pos_x", loc.get("pos_x"), 12.5)
check("pos_z", loc.get("pos_z"), -3.25)
check("yaw_deg", loc.get("yaw_deg"), 90.0)

print("[3] move keeps yaw")
update_location_position(lid, 100.0, 100.0)
loc = get_location(lid)
check("pos_x", loc.get("pos_x"), 100.0)
check("yaw kept", loc.get("yaw_deg"), 90.0)

print("[4] unplace resets yaw")
update_location_position(lid, None, None)
loc = get_location(lid)
check("pos_x", loc.get("pos_x"), None)
check("yaw reset", loc.get("yaw_deg", 0.0), 0.0)

print("[5] columns agree with dict")
second = add_location(name="Column Probe", description="smoke")
sid = second["id"]
update_location_position(sid, 30.0, 40.0)
conn = db.get_connection()
row = conn.execute("SELECT pos_x, pos_z, yaw_deg FROM locations WHERE id=?",
                   (sid,)).fetchone()
check("col pos_x", row[0], 30.0)
check("col pos_z", row[1], 40.0)
check("col yaw", row[2], 0.0)

print("[6] placed without yaw still carries the key")
other = add_location(name="Yawless Probe", description="smoke")
oid = other["id"]
update_location_position(oid, 10.0, 10.0)
other = get_location(oid)
check("key present", "yaw_deg" in other, True)
check("yaw value", other.get("yaw_deg"), 0.0)

print("[7] rounding")
update_location_position(oid, 1.005678, 2.0, -90.0)
other = get_location(oid)
check("pos_x rounded", other.get("pos_x"), 1.01)
check("yaw normalized", other.get("yaw_deg"), 270.0)

print("[8] non-finite positions are rejected, nothing persists")
NAN, INF = float("nan"), float("inf")
for label, args in (
        ("pos_x NaN", (oid, NAN, 2.0, None)),
        ("pos_z Infinity", (oid, 1.0, INF, None)),
        ("pos_z -Infinity", (oid, 1.0, -INF, None)),
        ("yaw_deg NaN", (oid, 5.0, 6.0, NAN)),
        ("yaw_deg Infinity", (oid, 5.0, 6.0, INF)),
):
    CHECKED += 1
    try:
        update_location_position(*args)
        print(f"  ✗ {label}: no ValueError")
        FAILURES.append(label)
    except ValueError as e:
        print(f"  ✓ {label}: ValueError({e})")
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {label}: {type(e).__name__}({e}) instead of ValueError")
        FAILURES.append(label)
_after = get_location(oid)
check("pos_x unchanged", _after.get("pos_x"), 1.01)
check("pos_z unchanged", _after.get("pos_z"), 2.0)
check("yaw unchanged", _after.get("yaw_deg"), 270.0)

# The whole point of the guard: the world map must still serialize.
import json as _json  # noqa: E402
check("locations render under allow_nan=False",
      bool(_json.dumps(_load_world_data().get("locations", []),
                       allow_nan=False, default=str)), True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
