#!/usr/bin/env python3
"""Smoke run for the pure world-geometry helpers (Seamless World, E1 Task 1).

Pure functions — with ONE exception that decides how this file has to start:
``ground_y`` reads the world heightfield since E8 task 2 (see
``app/core/world_geometry``), and the heightfield reads ``world.db``. Without a
storage override this smoke therefore opened the RUNNING server's world — which
made it fail with ``no such column`` after every schema change until the next
restart, while claiming in this very docstring that it used no DB at all. So
``STORAGE_DIR`` points at a throwaway directory BEFORE any app import
(``smoke_dead_config_fields.py`` is where that pattern is written out) and the
empty world it creates is what section [1] measures: an unshaped world is flat.

Hand-derived expectations (all numbers worked out by hand, § B5a style):

  [1] ground_y over an UNSHAPED world is 0 everywhere — nobody painted a height
      area, so there is no relief: ground_y(0, 0) == 0.0 and
      ground_y(123.4, -56.7) == 0.0.

  [2] Rotation round-trip. Centre (10, 20), yaw 90° (clockwise around +y,
      i.e. local +x maps onto world -z):
        local (3, 0)  -> world (10 + 3*cos90, 20 - 3*sin90) = (10, 17)
      world_to_local must invert local_to_world exactly (within 1e-9).

  [3]/[4] THE SQUARE SECTIONS ARE GONE (2026-08-19). ``point_in_footprint``
      and ``footprint_corners`` were deleted with the transition square: a
      location is a drawn polygon, and there is no width-shaped geometry left
      to check. Both guarantees were RE-DERIVED onto the polygon path, with
      the very same numbers, in ``scripts/smoke_world_polygon.py``:
        * the rotation discriminator (centre (10, 20), edge 10, yaw 45, point
          (16, 20) inside — an unrotated test says outside) is the
          "rotation discriminator" section there;
        * the corner set of the axis-aligned square (centre (0,0), edge 10,
          yaw 0 -> {(-5,-5), (5,-5), (5,5), (-5,5)}) is the
          "square boundary corners" section there.

  [5] Polygon. Triangle [(0,0), (10,0), (0,10)]:
        (2, 2) inside, (8, 8) outside, (20, 0) outside.
      Degenerate polygon (< 3 points) -> always False.

  [6] location_at_point, the smallest AREA wins. Village centre (0, 0) with a
      centred 50 m square boundary (±25, area 2500 m²); hut centre (10, 10)
      with a centred 6 m one (±3, area 36 m²).
        (10, 10)  -> hut  (both contain it — 36 < 2500, hut wins)
        (-20, 0)  -> village   (|dx| = 20 <= 25; the hut ends at x = 13)
        (100, 100)-> None
        An unplaced location (pos_x None) and one WITHOUT A BOUNDARY never
        match — since 2026-08-19 the latter has no area at all, and its
        legacy ``plan_width_m`` buys it nothing.

Usage:  ./.venv/bin/python scripts/smoke_world_geometry.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The storage root, pointed at a throwaway world BEFORE any app import — see
# the docstring. `paths.get_storage_dir()` auto-initializes on first call and
# falls back to ./worlds/demo, so an import that touches paths at module level
# would reach the running server's DB.
_TMP_STORAGE = tempfile.TemporaryDirectory(prefix="smoke_world_geometry_")
os.environ["STORAGE_DIR"] = _TMP_STORAGE.name

from app.core import paths  # noqa: E402

paths.init(_TMP_STORAGE.name)

from app.core import db  # noqa: E402

# The empty world needs its TABLES: `ground_y` asks the heightfield, which asks
# the terrain-type catalog, which reads a table. A missing one is the same
# `OperationalError` a stale schema was.
db.init_schema()

from app.core.world_geometry import (  # noqa: E402
    ground_y, local_to_world, location_at_point, point_in_polygon,
    world_to_local)

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


def close(label, actual, expected, tol=1e-9):
    check(label, abs(actual - expected) <= tol, True)


print("[1] ground_y — an unshaped world is flat")
check("origin", ground_y(0.0, 0.0), 0.0)
check("anywhere", ground_y(123.4, -56.7), 0.0)

print("[2] rotation round-trip")
wx, wz = local_to_world(3.0, 0.0, 10.0, 20.0, 90.0)
close("local(3,0)@yaw90 -> world x", wx, 10.0)
close("local(3,0)@yaw90 -> world z", wz, 17.0)
lx, lz = world_to_local(wx, wz, 10.0, 20.0, 90.0)
close("round-trip x", lx, 3.0)
close("round-trip z", lz, 0.0)

# [3] + [4] deleted with the square helpers — see the docstring; both
# guarantees live on in scripts/smoke_world_polygon.py.

print("[5] polygon")
tri = [[0, 0], [10, 0], [0, 10]]
check("inside", point_in_polygon(2, 2, tri), True)
check("outside diag", point_in_polygon(8, 8, tri), False)
check("outside far", point_in_polygon(20, 0, tri), False)
check("degenerate", point_in_polygon(0, 0, [[0, 0], [1, 1]]), False)

print("[6] location_at_point")
SQ50 = [[-25.0, -25.0], [25.0, -25.0], [25.0, 25.0], [-25.0, 25.0]]
SQ6 = [[-3.0, -3.0], [3.0, -3.0], [3.0, 3.0], [-3.0, 3.0]]
village = {"id": "village", "pos_x": 0.0, "pos_z": 0.0, "yaw_deg": 0.0,
           "map3d": {"boundary": SQ50, "plan_width_m": 50.0}}
hut = {"id": "hut", "pos_x": 10.0, "pos_z": 10.0, "yaw_deg": 0.0,
       "map3d": {"boundary": SQ6, "plan_width_m": 6.0}}
unplaced = {"id": "ghost", "pos_x": None, "pos_z": None,
            "map3d": {"boundary": SQ6, "plan_width_m": 6.0}}
# The legacy dial WITHOUT an outline: no area since 2026-08-19, so it can
# never be the answer even though it sits right under the query point.
unsized = {"id": "unsized", "pos_x": 10.0, "pos_z": 10.0,
           "map3d": {"plan_width_m": 6.0}}
locs = [village, hut, unplaced, unsized]
check("hut wins", (location_at_point(10, 10, locs) or {}).get("id"), "hut")
check("village", (location_at_point(-20, 0, locs) or {}).get("id"), "village")
check("nowhere", location_at_point(100, 100, locs), None)

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
