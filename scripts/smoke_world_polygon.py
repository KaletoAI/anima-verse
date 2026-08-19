"""Smoke check: polygon region primitives (contract v6 "Gebiete").

Usage:
    ./.venv/bin/python scripts/smoke_world_polygon.py

Standalone — no server, no world DB. Every expected number below is derived
BY HAND from the v6 contract (docs/schnittstellen-3d.md, v6 preamble), never
from running the code first.

The main fixture is the concave L-shape (map view, x east / z south):

        (0,0) ──── (4,0)
          │  wide     │
          │  arm    (4,2)
          │    (2,2)──┘
          │      │  notch at (3,3)
        (0,4)─(2,4)

  * Walking (0,0)→(4,0)→(4,2)→(2,2)→(2,4)→(0,4) is CLOCKWISE in map view;
    the shoelace sum with x east / z south is then POSITIVE:
    Σ(x_j·z_i − x_i·z_j) = 0+8+4+4+8+0 = 24 → signed area +12.
    Enclosed area: 4×4 minus the 2×2 notch = 12. ✓ cross-check.
  * Distances: (5,1) is 1 m east of the x=4 edge → 1.  (3,3) sits in the
    notch, 1 m from both notch edges → 1.  (-3,-4) is past the (0,0)
    corner → hypot(3,4) = 5.
  * Centroid: 6·A·Cx = Σ(x_j+x_i)·cross = 64+24+16+16 = 120 → Cx = 120/72
    = 5/3; Cz likewise 5/3. (5/3, 5/3) lies in the wide arm → the interior
    point IS the centroid here.
  * Segment (-1,3)→(5,3) crosses the thin arm (x ∈ [0,2] at z=3) → hit.
    Segment (3,3)→(5,3) starts in the notch and stays east of the thin arm;
    the right arm only reaches down to z=2 → no hit.

The U-shape forces the scan-row path of the interior point (its centroid
falls into the opening): points (0,0) (6,0) (6,4) (4,4) (4,1) (2,1) (2,4)
(0,4) — two 2 m columns joined by a 1 m top bar; area 6×4 − 2×3 = 18;
centroid z = (24·2 − 6·2.5)/18 = 11/6 ≈ 1.83 at x = 3 → inside the opening,
NOT the polygon. First scan row is height/2 → z = 2, crossings x = [0, 2,
4, 6], two spans of width 2; the FIRST widest span [0,2] wins → (1.0, 2.0).

Pin transform (§ A1.1, unchanged in v6): pin (100, 50), yaw 90 → local
(4,0) lands at x = 100 + 4·cos90 = 100, z = 50 − 4·sin90 = 46.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.world_geometry import (  # noqa: E402
    effective_boundary,
    placed_boundary,
    polygon_signed_area as _psa,
    point_in_polygon,
    polygon_area,
    polygon_bounds,
    polygon_distance,
    polygon_hits_aabb,
    polygon_interior_point,
    polygon_local_to_world,
    polygon_signed_area,
    polygons_overlap,
    segment_hits_polygon,
)

L_SHAPE = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]]
U_SHAPE = [[0, 0], [6, 0], [6, 4], [4, 4], [4, 1], [2, 1], [2, 4], [0, 4]]

FAILED = 0


def check(label, actual, expected, tol=1e-9):
    global FAILED
    if isinstance(expected, float) or isinstance(actual, float):
        ok = isinstance(actual, (int, float)) and (
            actual == expected or abs(actual - expected) <= tol)
    else:
        ok = actual == expected
    mark = "ok  " if ok else "FAIL"
    print(f"  {mark} {label}: {actual!r} (expected {expected!r})")
    if not ok:
        FAILED += 1


print("winding / area (hand: +12 CW, 16 - 4 notch)")
check("signed area L", polygon_signed_area(L_SHAPE), 12.0)
check("area L", polygon_area(L_SHAPE), 12.0)
check("signed area CW triangle", polygon_signed_area([[0, 0], [1, 0], [0, 1]]), 0.5)
check("signed area CCW triangle", polygon_signed_area([[0, 0], [0, 1], [1, 0]]), -0.5)
check("closed ring tolerated", polygon_area(L_SHAPE + [[0, 0]]), 12.0)
check("degenerate (2 points)", polygon_area([[0, 0], [4, 0]]), 0.0)
check("bounds L", polygon_bounds(L_SHAPE), (0.0, 0.0, 4.0, 4.0))

print("containment (notch is outside)")
check("(1,1) wide arm", point_in_polygon(1, 1, L_SHAPE), True)
check("(3,1) right arm", point_in_polygon(3, 1, L_SHAPE), True)
check("(3,3) notch", point_in_polygon(3, 3, L_SHAPE), False)
check("(5,5) far outside", point_in_polygon(5, 5, L_SHAPE), False)

print("distance (hand: 1 / 1 / 5 / 0)")
check("(5,1) east of edge", polygon_distance(5, 1, L_SHAPE), 1.0)
check("(3,3) in notch", polygon_distance(3, 3, L_SHAPE), 1.0)
check("(-3,-4) past corner", polygon_distance(-3, -4, L_SHAPE), 5.0)
check("(1,1) inside = 0", polygon_distance(1, 1, L_SHAPE), 0.0)
check("degenerate = inf", polygon_distance(0, 0, [[0, 0]]), math.inf)

print("interior point")
ip = polygon_interior_point(L_SHAPE)
check("L: centroid x = 5/3", ip[0], 5.0 / 3.0)
check("L: centroid z = 5/3", ip[1], 5.0 / 3.0)
check("L: verifiably inside", point_in_polygon(ip[0], ip[1], L_SHAPE), True)
ip_u = polygon_interior_point(U_SHAPE)
check("U: scan row -> (1, 2)", ip_u, (1.0, 2.0))
check("U: verifiably inside", point_in_polygon(ip_u[0], ip_u[1], U_SHAPE), True)
check("degenerate -> None", polygon_interior_point([[0, 0], [1, 1]]), None)

print("segment vs polygon (hand cases from the docstring)")
check("(-1,3)->(5,3) crosses thin arm",
      segment_hits_polygon(-1, 3, 5, 3, L_SHAPE), True)
check("(3,3)->(5,3) stays in/east of notch",
      segment_hits_polygon(3, 3, 5, 3, L_SHAPE), False)
check("(5,3)->(6,3) fully outside",
      segment_hits_polygon(5, 3, 6, 3, L_SHAPE), False)
check("endpoint inside counts",
      segment_hits_polygon(1, 1, 9, 9, L_SHAPE), True)

print("polygon vs AABB")
check("box in the notch region", polygon_hits_aabb(L_SHAPE, 3, 3, 5, 5), False)
check("box over right arm", polygon_hits_aabb(L_SHAPE, 3.5, 0.5, 4.5, 1.5), True)
check("box fully inside wide arm",
      polygon_hits_aabb(L_SHAPE, 0.5, 0.5, 1.5, 1.5), True)
check("box far away", polygon_hits_aabb(L_SHAPE, 10, 10, 12, 12), False)

print("polygon overlap (warning primitive; touch counts)")
check("square in notch: disjoint",
      polygons_overlap(L_SHAPE, [[3, 3], [5, 3], [5, 5], [3, 5]]), False)
check("square over wide arm: overlap",
      polygons_overlap(L_SHAPE, [[1, 1], [3, 1], [3, 3], [1, 3]]), True)
check("shared edge x=4: touch counts",
      polygons_overlap(L_SHAPE, [[4, 0], [6, 0], [6, 2], [4, 2]]), True)

print("placed boundary + pin transform (§ A1.1: yaw 90, local (4,0) -> (100,46))")
loc = {"pos_x": 100, "pos_z": 50, "yaw_deg": 90, "map3d": {"boundary": L_SHAPE}}
pb = placed_boundary(loc)
check("placed", pb is not None, True)
cx, cz, yaw, pts = pb
world = polygon_local_to_world(pts, cx, cz, yaw)
check("world x of local (4,0)", world[1][0], 100.0)
check("world z of local (4,0)", world[1][1], 46.0)
check("no boundary -> None",
      placed_boundary({"pos_x": 1, "pos_z": 2, "map3d": {}}), None)
check("unplaced -> None",
      placed_boundary({"pos_x": None, "pos_z": 5,
                       "map3d": {"boundary": L_SHAPE}}), None)
check("NaN pos -> None",
      placed_boundary({"pos_x": float("nan"), "pos_z": 5,
                       "map3d": {"boundary": L_SHAPE}}), None)

print("effective boundary (square dial -> its four corners, CW)")
eb = effective_boundary({"pos_x": 0, "pos_z": 0,
                         "map3d": {"plan_width_m": 10}})
check("square synthesized", eb is not None, True)
check("corners", eb[3], [(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)])
check("winding CW (positive shoelace, hand: 100)", _psa(eb[3]), 100.0)
check("drawn boundary wins",
      effective_boundary(loc)[3], [tuple(p) for p in L_SHAPE])
check("no width, no boundary -> None",
      effective_boundary({"pos_x": 0, "pos_z": 0, "map3d": {}}), None)

print()
if FAILED:
    print(f"FAILED: {FAILED} check(s) diverge from the hand-derived values")
    sys.exit(1)
print("all polygon primitives match the hand-derived values")
