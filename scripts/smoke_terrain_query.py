#!/usr/bin/env python3
"""Smoke run for terrain point queries + metre character position
(Seamless World, E1 Task 5).

Runs against a THROWAWAY storage directory — never touches a real world.

Seed: default kind "grass" (no config override). Areas:
  water  polygon [[0,0],[20,0],[20,20],[0,20]]  z_order 0
  path   polygon [[5,5],[15,5],[15,15],[5,15]]  z_order 1
Locations: inn at (50, 50) plan_width_m 10.

Hand-derived expectations:

  [1] kind_at(30, 30)  -> "grass"  (no area)
  [2] kind_at(2, 2)    -> "water"  (only water contains it)
  [3] kind_at(10, 10)  -> "path"   (both contain it, path has higher z)
  [4] passability_at(2, 2)  -> (False, 0.0); passability_at(30, 30)
      -> (True, 1.0); passability_at(10, 10) -> (True, 1.2). Plus the
      catalog hole: an area whose kind was deleted from the catalog
      afterwards degrades to (True, 1.0) — a missing type must never
      strand a character behind an impassable ghost.
  [5] set_character_pos("probe_npc", 50, 50) -> location_id == inn id;
      get_character_pos -> {"x": 50.0, "z": 50.0};
      get_character_current_location("probe_npc") == inn id
  [6] set_character_pos("probe_npc", 30, 30) -> location_id "" (wilderness),
      current_location "" — outside any footprint is a LEGAL state.
  [7] save_character_current_location("probe_npc", inn_id) syncs pos
      back to the inn centre (50.0, 50.0); moving the character to an
      UNPLACED location clears the position to None (both columns NULL),
      because an unplaced location has no metre centre to stand on.
  [8] The pos-sync is gated on a REAL location change, or it silently
      re-centres freely positioned characters:
      a) character at the off-centre point (52, 53) inside the inn; a
         room-/status-only update re-saves the SAME location
         (character_ops does this unconditionally) -> pos stays
         (52.0, 53.0), NOT the centre.
      b) the off-map sleep path (periodic_jobs) resolves the sentinel to
         an EMPTY location and calls the setter with "" -> pos stays
         (52.0, 53.0). Clearing it there would lose the point forever.
  [9] Stepping OUT of every footprint clears the ROOM too. The setter's
      location_changed is False for "" (bool("") is False), so the room
      write is skipped and the character would keep current_room of the
      room it just left — room-filtered perception/chat would still place
      it in there. Expected: current_location "" AND current_room "".
      Stepping back IN goes through the normal setter again (location set,
      arrival room per the existing rules).
 [10] set_character_pos with a non-finite coordinate raises ValueError.
      A range check alone does not catch NaN (every NaN comparison is
      False), and one NaN in pos_x poisons every later JSON response
      (Starlette encodes with allow_nan=False -> 500).

Usage:  ./.venv/bin/python scripts/smoke_terrain_query.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="terrain-query-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="terrain-query-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import terrain_query, terrain_types  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_current_location, get_character_current_room,
    get_character_pos, save_character_current_location,
    save_character_current_room, save_character_profile, set_character_pos)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location,
    update_location_position)

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


def raises_value_error(label, fn):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except ValueError as e:
        print(f"  ✓ {label}: ValueError({str(e)!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  ✗ {label}: {type(e).__name__}({e}) — expected ValueError")
        FAILURES.append(label)
        return
    print(f"  ✗ {label}: no exception — expected ValueError")
    FAILURES.append(label)


def set_plan_width(location_id: str, width: float) -> None:
    """Scale anchor of a location (map3d.plan_width_m) — the footprint edge."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d["plan_width_m"] = width
            loc["map3d"] = map3d
    _save_world_data(data)


# ── Seed ────────────────────────────────────────────────────────────────
terrain.save_area({"kind": "water",
                   "polygon": [[0, 0], [20, 0], [20, 20], [0, 20]],
                   "z_order": 0})
terrain.save_area({"kind": "path",
                   "polygon": [[5, 5], [15, 5], [15, 15], [5, 15]],
                   "z_order": 1})

inn = add_location(name="Smoke Inn", description="terrain-query smoke")
INN_ID = inn["id"]
update_location_position(INN_ID, 50.0, 50.0)
set_plan_width(INN_ID, 10.0)

nowhere = add_location(name="Unplaced Hut", description="never placed")
NOWHERE_ID = nowhere["id"]

save_character_profile("probe_npc", {"current_location": ""}, create_new=True)

print("[1] unpainted ground falls back to the default kind")
check("kind_at(30, 30)", terrain_query.kind_at(30, 30), "grass")

print("[2] a single containing area wins")
check("kind_at(2, 2)", terrain_query.kind_at(2, 2), "water")

print("[3] the topmost containing area wins")
check("kind_at(10, 10)", terrain_query.kind_at(10, 10), "path")

print("[4] passability comes from the catalog, never from hardcoded kinds")
check("passability_at(2, 2)", terrain_query.passability_at(2, 2), (False, 0.0))
check("passability_at(30, 30)", terrain_query.passability_at(30, 30), (True, 1.0))
check("passability_at(10, 10)", terrain_query.passability_at(10, 10), (True, 1.2))
# Catalog hole: paint an area, then delete its type from the catalog.
terrain_types.save_world_type({"kind": "ghost", "name": "Ghost",
                               "color": "#123456", "passable": False,
                               "speed_factor": 0.0})
ghost = terrain.save_area({"kind": "ghost",
                           "polygon": [[100, 100], [110, 100], [110, 110],
                                       [100, 110]],
                           "z_order": 9})
check("painted ghost kind", terrain_query.kind_at(105, 105), "ghost")
check("ghost is impassable while the type exists",
      terrain_query.passability_at(105, 105), (False, 0.0))
terrain_types.delete_world_type("ghost")
check("kind survives the type deletion", terrain_query.kind_at(105, 105), "ghost")
check("catalog hole degrades to walkable",
      terrain_query.passability_at(105, 105), (True, 1.0))
terrain.delete_area(ghost["id"])

print("[5] a position inside a footprint derives the location")
res = set_character_pos("probe_npc", 50, 50)
check("derived location_id", res["location_id"], INN_ID)
check("returned pos", res["pos"], {"x": 50.0, "z": 50.0})
check("get_character_pos", get_character_pos("probe_npc"), {"x": 50.0, "z": 50.0})
check("current_location", get_character_current_location("probe_npc"), INN_ID)

print("[6] wilderness is a legal state")
res = set_character_pos("probe_npc", 30, 30)
check("derived location_id", res["location_id"], "")
check("returned pos", res["pos"], {"x": 30.0, "z": 30.0})
check("get_character_pos", get_character_pos("probe_npc"), {"x": 30.0, "z": 30.0})
check("current_location", get_character_current_location("probe_npc"), "")

print("[7] a teleport keeps the metre position as the truth")
save_character_current_location("probe_npc", INN_ID)
check("current_location", get_character_current_location("probe_npc"), INN_ID)
check("pos synced to the inn centre",
      get_character_pos("probe_npc"), {"x": 50.0, "z": 50.0})
save_character_current_location("probe_npc", NOWHERE_ID)
check("current_location", get_character_current_location("probe_npc"), NOWHERE_ID)
check("unplaced location clears the position",
      get_character_pos("probe_npc"), None)

print("[8] the pos-sync only fires on a REAL location change")
res = set_character_pos("probe_npc", 52, 53)
check("off-centre point inside the inn", res["location_id"], INN_ID)
check("pos is off-centre", get_character_pos("probe_npc"), {"x": 52.0, "z": 53.0})
# a) room-/status-only update: same location saved again (character_ops
#    does exactly this on every room change / status write).
save_character_current_location("probe_npc", INN_ID)
check("same-location write keeps the free point",
      get_character_pos("probe_npc"), {"x": 52.0, "z": 53.0})
# b) off-map sleep path: periodic_jobs resolves the sentinel to "" and calls
#    the setter with an empty location.
save_character_current_location("probe_npc", "")
check("empty-location write keeps the free point",
      get_character_pos("probe_npc"), {"x": 52.0, "z": 53.0})

print("[9] leaving every footprint clears location AND room")
set_character_pos("probe_npc", 52, 53)          # back inside, location set
save_character_current_room("probe_npc", "ground")
check("room set before the step out",
      get_character_current_room("probe_npc"), "ground")
res = set_character_pos("probe_npc", 30, 30)
check("derived location_id", res["location_id"], "")
check("current_location cleared",
      get_character_current_location("probe_npc"), "")
check("current_room cleared", get_character_current_room("probe_npc"), "")
check("pos kept", get_character_pos("probe_npc"), {"x": 30.0, "z": 30.0})
# The reverse step still runs through the normal setter.
res = set_character_pos("probe_npc", 50, 50)
check("re-entering sets the location", res["location_id"], INN_ID)
check("current_location restored",
      get_character_current_location("probe_npc"), INN_ID)
check("arrival room assigned by the normal setter",
      bool(get_character_current_room("probe_npc")), True)

print("[10] non-finite coordinates raise ValueError")
for bad in (float("nan"), float("inf"), float("-inf")):
    raises_value_error(f"x={bad!r} raises",
                       lambda bad=bad: set_character_pos("probe_npc", bad, 0))
    raises_value_error(f"z={bad!r} raises",
                       lambda bad=bad: set_character_pos("probe_npc", 0, bad))
raises_value_error("non-numeric x raises",
                   lambda: set_character_pos("probe_npc", "here", 0))

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
