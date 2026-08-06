"""Pure world-coordinate geometry (Seamless World, E1).

The world is a continuous plane measured in metres. Locations are squares
of edge ``map3d.plan_width_m`` centred on (``pos_x``, ``pos_z``), rotated by
``yaw_deg`` around the vertical axis. Everything here is pure math — no DB,
no config — so the smoke checks derive every number by hand.

Axes follow the 3D client (three.js ground plane): x grows east, z grows
south. ``yaw_deg`` rotates clockwise when looking down onto the map, so at
yaw 90 the local +x axis points at world -z.

``ground_y`` is THE v2 reservation (plan-freie-weltkarte.md): terrain height
as a function of (x, z), constant 0.0 in v1. Every consumer — placement,
journeys, renderers — must derive y through this function and never persist
it; the relief stage (E8) swaps ONLY this implementation.
"""

import math
from typing import Any, Dict, List, Optional, Tuple


def ground_y(x: float, z: float) -> float:
    """Terrain height at (x, z) in world metres. v1: a flat world."""
    return 0.0


def local_to_world(lx: float, lz: float, cx: float, cz: float,
                   yaw_deg: float) -> Tuple[float, float]:
    """Map a point from a location's local frame into world coordinates."""
    rad = math.radians(yaw_deg or 0.0)
    cos_y, sin_y = math.cos(rad), math.sin(rad)
    return (cx + lx * cos_y + lz * sin_y,
            cz - lx * sin_y + lz * cos_y)


def world_to_local(x: float, z: float, cx: float, cz: float,
                   yaw_deg: float) -> Tuple[float, float]:
    """Inverse of :func:`local_to_world` (rotate by -yaw around the centre)."""
    rad = math.radians(yaw_deg or 0.0)
    cos_y, sin_y = math.cos(rad), math.sin(rad)
    dx, dz = x - cx, z - cz
    return (dx * cos_y - dz * sin_y,
            dx * sin_y + dz * cos_y)


def point_in_footprint(x: float, z: float, cx: float, cz: float,
                       width_m: float, yaw_deg: float) -> bool:
    """Whether world point (x, z) lies inside the rotated footprint square."""
    if not width_m or width_m <= 0:
        return False
    lx, lz = world_to_local(x, z, cx, cz, yaw_deg)
    half = width_m / 2.0
    return abs(lx) <= half and abs(lz) <= half


def footprint_corners(cx: float, cz: float, width_m: float,
                      yaw_deg: float) -> List[Tuple[float, float]]:
    """The four footprint corners in world metres (local-frame order
    (-h,-h), (h,-h), (h,h), (-h,h))."""
    half = (width_m or 0.0) / 2.0
    return [local_to_world(lx, lz, cx, cz, yaw_deg)
            for lx, lz in ((-half, -half), (half, -half),
                           (half, half), (-half, half))]


def point_in_polygon(x: float, z: float, points: Any) -> bool:
    """Ray-casting point-in-polygon over ``[[x, z], …]`` (auto-closed).

    Fewer than 3 valid points can never contain anything -> False.
    """
    pts: List[Tuple[float, float]] = []
    for pt in (points or []):
        try:
            pts.append((float(pt[0]), float(pt[1])))
        except (TypeError, ValueError, IndexError):
            return False
    if len(pts) < 3:
        return False
    inside = False
    j = len(pts) - 1
    for i, (xi, zi) in enumerate(pts):
        xj, zj = pts[j]
        if (zi > z) != (zj > z):
            cross_x = (xj - xi) * (z - zi) / (zj - zi) + xi
            if x < cross_x:
                inside = not inside
        j = i
    return inside


def placed_footprint(loc: Dict[str, Any]) -> Optional[Tuple[float, float,
                                                            float, float]]:
    """(cx, cz, width_m, yaw_deg) of a placed location, or None.

    Placed means: numeric ``pos_x``/``pos_z`` AND a scale anchor
    (``map3d.plan_width_m``). Without the anchor the footprint has no size,
    so the location cannot claim any point.
    """
    px, pz = loc.get("pos_x"), loc.get("pos_z")
    if px is None or pz is None:
        return None
    try:
        width = float((loc.get("map3d") or {}).get("plan_width_m"))
    except (TypeError, ValueError):
        return None
    if width <= 0:
        return None
    return (float(px), float(pz), width, float(loc.get("yaw_deg") or 0.0))


def location_at_point(x: float, z: float,
                      locations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The location whose footprint contains (x, z) — smallest wins.

    Overlaps are legal (a hut placed on a village square); the SMALLEST
    matching footprint is the most specific answer, mirroring how the old
    grid resolved "the cell you stand on".
    """
    best: Optional[Dict[str, Any]] = None
    best_width = None
    for loc in locations or []:
        fp = placed_footprint(loc)
        if fp is None:
            continue
        cx, cz, width, yaw = fp
        if not point_in_footprint(x, z, cx, cz, width, yaw):
            continue
        if best_width is None or width < best_width:
            best, best_width = loc, width
    return best
