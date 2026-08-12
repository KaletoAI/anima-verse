#!/usr/bin/env python3
"""Smoke run for the pure world-geometry helpers (Seamless World, E1 Task 1).

No DB, no storage — pure functions only.

Hand-derived expectations (all numbers worked out by hand, § B5a style):

  [1] ground_y is the ONE v1 constant: ground_y(0, 0) == 0.0 and
      ground_y(123.4, -56.7) == 0.0.

  [2] Rotation round-trip. Centre (10, 20), yaw 90° (clockwise around +y,
      i.e. local +x maps onto world -z):
        local (3, 0)  -> world (10 + 3*cos90, 20 - 3*sin90) = (10, 17)
      world_to_local must invert local_to_world exactly (within 1e-9).

  [3] Footprint membership. Centre (10, 20), width 10 (half = 5):
        yaw 0:  (14.9, 24.9) inside;  (16.0, 20.0) OUTSIDE (|dx| = 6 > 5)
        yaw 45: (16.0, 20.0) INSIDE — local coords are
                (6*cos45, 6*sin45) = (4.2426, 4.2426), both <= 5.
      The yaw-45 case is the discriminator: an unrotated check would say no.

  [4] Corners. Centre (0, 0), width 10, yaw 0 ->
      {(-5,-5), (5,-5), (5,5), (-5,5)} in some order.

  [5] Polygon. Triangle [(0,0), (10,0), (0,10)]:
        (2, 2) inside, (8, 8) outside, (20, 0) outside.
      Degenerate polygon (< 3 points) -> always False.

  [6] location_at_point, smallest footprint wins. Village centre (0, 0),
      plan_width_m 50; hut centre (10, 10), plan_width_m 6.
        (10, 10)  -> hut  (both contain it — 6 < 50, hut wins)
        (-20, 0)  -> village
        (100, 100)-> None
        unplaced location (pos_x None) and location without plan_width_m
        never match.

Usage:  ./.venv/bin/python scripts/smoke_world_geometry.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.world_geometry import (  # noqa: E402
    footprint_corners, ground_y, local_to_world, location_at_point,
    point_in_footprint, point_in_polygon, world_to_local)

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


print("[1] ground_y")
check("origin", ground_y(0.0, 0.0), 0.0)
check("anywhere", ground_y(123.4, -56.7), 0.0)

print("[2] rotation round-trip")
wx, wz = local_to_world(3.0, 0.0, 10.0, 20.0, 90.0)
close("local(3,0)@yaw90 -> world x", wx, 10.0)
close("local(3,0)@yaw90 -> world z", wz, 17.0)
lx, lz = world_to_local(wx, wz, 10.0, 20.0, 90.0)
close("round-trip x", lx, 3.0)
close("round-trip z", lz, 0.0)

print("[3] footprint membership")
check("yaw0 inside", point_in_footprint(14.9, 24.9, 10, 20, 10, 0), True)
check("yaw0 outside", point_in_footprint(16.0, 20.0, 10, 20, 10, 0), False)
check("yaw45 inside", point_in_footprint(16.0, 20.0, 10, 20, 10, 45), True)

print("[4] corners")
corners = {(round(x), round(z)) for x, z in footprint_corners(0, 0, 10, 0)}
check("axis-aligned corners", corners,
      {(-5, -5), (5, -5), (5, 5), (-5, 5)})

print("[5] polygon")
tri = [[0, 0], [10, 0], [0, 10]]
check("inside", point_in_polygon(2, 2, tri), True)
check("outside diag", point_in_polygon(8, 8, tri), False)
check("outside far", point_in_polygon(20, 0, tri), False)
check("degenerate", point_in_polygon(0, 0, [[0, 0], [1, 1]]), False)

print("[6] location_at_point")
village = {"id": "village", "pos_x": 0.0, "pos_z": 0.0, "yaw_deg": 0.0,
           "map3d": {"plan_width_m": 50.0}}
hut = {"id": "hut", "pos_x": 10.0, "pos_z": 10.0, "yaw_deg": 0.0,
       "map3d": {"plan_width_m": 6.0}}
unplaced = {"id": "ghost", "pos_x": None, "pos_z": None,
            "map3d": {"plan_width_m": 6.0}}
unsized = {"id": "unsized", "pos_x": 10.0, "pos_z": 10.0, "map3d": {}}
locs = [village, hut, unplaced, unsized]
check("hut wins", (location_at_point(10, 10, locs) or {}).get("id"), "hut")
check("village", (location_at_point(-20, 0, locs) or {}).get("id"), "village")
check("nowhere", location_at_point(100, 100, locs), None)

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
