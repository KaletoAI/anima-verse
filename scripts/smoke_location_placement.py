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
  [5] clone_location(template_id, 30.0, 40.0) places the clone at
      (30.0, 40.0) with its own new id.
  [6] Persistence survives a fresh connection: values read back from the DB
      columns equal the dict values (truth in meta blob AND columns agree).
  [7] A location placed WITHOUT a yaw still HAS the key: "yaw_deg" in loc is
      True and the value is 0.0. Checked with `in`, not `.get(..., 0.0)` —
      the default in a .get would mask exactly the missing key. The contract
      is `yaw_deg: float`, never absent, never None.
  [8] Rounding: update_location_position(id, 1.005678, 2.0, -90.0) stores
      pos_x 1.01 (2 decimals = centimetres) and yaw_deg 270.0
      (1 decimal, modulo 360 — so a negative angle comes back positive).
  [9] cleanup_orphan_clones (runs at every server boot) and the v7->v8
      upgrade: a clone that still carries the legacy grid_x/grid_y keys and
      has no metre position is STALE, not off-map — it survives. A clone
      born on the metre model without a position is off-map and is removed.
      The placed clone from [5] is untouched either way.
 [10] Non-finite positions raise ValueError and persist NOTHING. NaN and
      Infinity are legal JSON literals for stdlib json.loads (which parses
      every request body), and round(nan) is still NaN — so without an
      explicit isfinite guard ONE PATCH stores NaN, after which every
      response containing that location 500s (Starlette encodes with
      allow_nan=False). Vectors: pos_x NaN, pos_z inf, yaw_deg NaN on
      update_location_position, and pos NaN on clone_location. After each
      one the location is re-read: it must still sit at the values from [8]
      (1.01 / 2.0 / 270.0), and the whole location list must render under
      allow_nan=False. clone_location additionally must not have appended a
      clone (location count unchanged).

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
    _load_world_data, _save_world_data, add_location, cleanup_orphan_clones,
    clone_location, get_location, update_location_position)

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

print("[5] clone at metres")
clone = clone_location(lid, 30.0, 40.0)
check("clone placed x", (clone or {}).get("pos_x"), 30.0)
check("clone placed z", (clone or {}).get("pos_z"), 40.0)
check("clone new id", bool(clone and clone["id"] != lid), True)

print("[6] columns agree with dict")
conn = db.get_connection()
row = conn.execute("SELECT pos_x, pos_z, yaw_deg FROM locations WHERE id=?",
                   (clone["id"],)).fetchone()
check("col pos_x", row[0], 30.0)
check("col pos_z", row[1], 40.0)
check("col yaw", row[2], 0.0)

print("[7] placed without yaw still carries the key")
other = add_location(name="Yawless Probe", description="smoke")
oid = other["id"]
update_location_position(oid, 10.0, 10.0)
other = get_location(oid)
check("key present", "yaw_deg" in other, True)
check("yaw value", other.get("yaw_deg"), 0.0)

print("[8] rounding")
update_location_position(oid, 1.005678, 2.0, -90.0)
other = get_location(oid)
check("pos_x rounded", other.get("pos_x"), 1.01)
check("yaw normalized", other.get("yaw_deg"), 270.0)

print("[9] boot cleanup keeps stale grid clones, drops metre off-map clones")
_data = _load_world_data()
_data["locations"].append({
    "id": "legacy_clone", "template_location_id": lid,
    "grid_x": 3, "grid_y": 4, "rooms": [],
})
_data["locations"].append({
    "id": "metre_clone_offmap", "template_location_id": lid, "rooms": [],
})
_save_world_data(_data)
cleanup_orphan_clones()
_ids = {l.get("id") for l in _load_world_data().get("locations", [])}
check("legacy grid clone survives", "legacy_clone" in _ids, True)
check("metre off-map clone removed", "metre_clone_offmap" in _ids, False)
check("placed clone untouched", clone["id"] in _ids, True)

print("[10] non-finite positions are rejected, nothing persists")
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

_before_count = len(_load_world_data().get("locations", []))
for label, args in (("clone pos_x NaN", (lid, NAN, 1.0)),
                    ("clone pos_z Infinity", (lid, 1.0, INF))):
    CHECKED += 1
    try:
        clone_location(*args)
        print(f"  ✗ {label}: no ValueError")
        FAILURES.append(label)
    except ValueError as e:
        print(f"  ✓ {label}: ValueError({e})")
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {label}: {type(e).__name__}({e}) instead of ValueError")
        FAILURES.append(label)
check("no clone appended",
      len(_load_world_data().get("locations", [])), _before_count)
# The whole point of the guard: the world map must still serialize.
import json as _json  # noqa: E402
check("locations render under allow_nan=False",
      bool(_json.dumps(_load_world_data().get("locations", []),
                       allow_nan=False, default=str)), True)

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
