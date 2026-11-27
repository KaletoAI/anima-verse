#!/usr/bin/env python3
"""Smoke: location block caches entry_geometry per scene_etag without touching _scene_cache.

Usage:  ./.venv/bin/python scripts/smoke_location_block_doors_cache.py

Hand-derived expectations (40 placed buildings, index i = 0..39):
- Building i sits at (i * 20, 0), yaw 0, boundary +-4 m, with one walled room
  "hall" (x=-4, y=-4, w=8, d=8, level=0) carrying a south outside door
  (edge="S", at=0.5, width_m=1.2, type="door", to="outside") -> local (0, 4),
  world (i * 20, 4.0), outward (0, 1).
- First _location_block() build: all 40 buildings miss _entry_geo_cache ->
  40 calls to scene_recipe._compose_stored; scene_recipe._scene_cache stays
  empty (0 entries, because compose_uncached never writes to the 32-slot LRU).
- Unrelated world write (adding a bare location without layout) bumps
  world_generation and forces _location_block() to rebuild; every building's
  scene_etag still matches its cached entry -> 0 additional composes on the
  first and second unrelated rebuilds; _scene_cache stays empty; building 0's
  door (0.0, 4.0, w=1.2) is still present in the rebuilt block.
- Editing ONE building's layout (building 0 door width 1.2 -> 1.4) changes only
  building 0's scene_etag -> rebuilding the block composes exactly 1 scene
  (total 41), _scene_cache stays empty, and building 0's door reports width 1.4.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="loc-block-doors-cache-"))
CLIPS = Path(tempfile.mkdtemp(prefix="loc-block-doors-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import scene_recipe, world_ops  # noqa: E402
from app.models.world import (  # noqa: E402
    GROUND_ROOM_ID, _load_world_data, _save_world_data, add_location,
    update_location_position,
)

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


def main() -> int:
    bldg_ids = []
    for i in range(40):
        lid = add_location(name=f"Building {i}", description="cache smoke")["id"]
        update_location_position(lid, float(i * 20), 0.0, 0.0)
        bldg_ids.append(lid)

    data = _load_world_data()
    idx_by_id = {lid: i for i, lid in enumerate(bldg_ids)}
    for loc in data.get("locations", []):
        lid = loc.get("id")
        if lid not in idx_by_id:
            continue
        loc["map3d"] = {
            "boundary": [[-4.0, -4.0], [4.0, -4.0], [4.0, 4.0], [-4.0, 4.0]],
            "plan_width_m": 8.0,
        }
        loc["rooms"] = [
            {"id": GROUND_ROOM_ID, "name": "Ground"},
            {
                "id": "hall",
                "name": "Hall",
                "layout": {
                    "x": -4.0, "y": -4.0, "w": 8.0, "d": 8.0, "level": 0,
                    "openings": [
                        {"edge": "S", "at": 0.5, "width_m": 1.2,
                         "type": "door", "to": "outside"},
                    ],
                },
            },
        ]
    _save_world_data(data)

    # Clear caches and wrap _compose_stored with a call counter.
    scene_recipe._scene_cache.clear()
    world_ops._loc_block_cache = None
    world_ops._entry_geo_cache.clear()

    compose_calls = 0
    real_compose = scene_recipe._compose_stored

    def counted_compose(loc, lid):
        nonlocal compose_calls
        compose_calls += 1
        return real_compose(loc, lid)

    scene_recipe._compose_stored = counted_compose
    try:
        print("[1] cold block build over 40 buildings")
        block1 = world_ops._location_block()
        check("initial build composes all 40 buildings", compose_calls, 40)
        check("_scene_cache LRU stays empty (0 entries)",
              len(scene_recipe._scene_cache), 0)
        row0 = next(entry for _loc, entry in block1.rows if entry["id"] == bldg_ids[0])
        check("building 0 door in block", row0["doors"],
              [{"x": 0.0, "z": 4.0, "out_x": 0.0, "out_z": 1.0,
                "width_m": 1.2, "room": "hall", "level": 0}])

        print("[2] unrelated world writes bump generation; rebuilds compose 0")
        add_location(name="Bare Pin 1", description="no layout")
        block2 = world_ops._location_block()
        check("first unrelated rebuild composes 0", compose_calls, 40)
        add_location(name="Bare Pin 2", description="no layout")
        block3 = world_ops._location_block()
        check("second unrelated rebuild composes 0", compose_calls, 40)
        check("_scene_cache LRU still empty", len(scene_recipe._scene_cache), 0)
        row0_hit = next(entry for _loc, entry in block3.rows if entry["id"] == bldg_ids[0])
        check("building 0 doors survive cache hit", row0_hit["doors"],
              [{"x": 0.0, "z": 4.0, "out_x": 0.0, "out_z": 1.0,
                "width_m": 1.2, "room": "hall", "level": 0}])

        print("[3] editing ONE building layout recomposes exactly 1")
        data2 = _load_world_data()
        for loc in data2.get("locations", []):
            if loc.get("id") == bldg_ids[0]:
                for r in loc.get("rooms") or []:
                    if r.get("id") == "hall":
                        r["layout"]["openings"][0]["width_m"] = 1.4
        _save_world_data(data2)
        block4 = world_ops._location_block()
        check("editing one building composes exactly 1 more (40 + 1 = 41)",
              compose_calls, 41)
        check("_scene_cache LRU still empty", len(scene_recipe._scene_cache), 0)
        row0_new = next(entry for _loc, entry in block4.rows if entry["id"] == bldg_ids[0])
        check("building 0 door reflects new width 1.4", row0_new["doors"],
              [{"x": 0.0, "z": 4.0, "out_x": 0.0, "out_z": 1.0,
                "width_m": 1.4, "room": "hall", "level": 0}])
    finally:
        scene_recipe._compose_stored = real_compose

    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
        return 1
    print(f"OK — {CHECKED} checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
        shutil.rmtree(CLIPS, ignore_errors=True)
