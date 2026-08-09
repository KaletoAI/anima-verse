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


def segment_hits_footprint(x0: float, z0: float, x1: float, z1: float,
                           cx: float, cz: float, width_m: float,
                           yaw_deg: float) -> bool:
    """Whether the straight segment (x0,z0)→(x1,z1) touches the footprint.

    EXACT (Liang-Barsky slab clip in the footprint's local frame), not
    sampled: point sampling along a segment misses sub-metre intrusions,
    and "the path clips the corner of a building" is exactly that case.
    A grazing touch counts as a hit — the conservative answer.

    Hand-derived: footprint at (0, 0), width 2, yaw 0 (so x, z ∈ [-1, 1]).
    The segment (-5, 0)→(5, 0) enters at t=0.4 and leaves at t=0.6 -> True.
    The segment (-5, 2)→(5, 2) has local z = 2 for its whole length, outside
    the [-1, 1] slab -> False.
    """
    if not width_m or width_m <= 0:
        return False
    lx0, lz0 = world_to_local(x0, z0, cx, cz, yaw_deg)
    lx1, lz1 = world_to_local(x1, z1, cx, cz, yaw_deg)
    half = width_m / 2.0
    t_enter, t_exit = 0.0, 1.0
    for p0, p1 in ((lx0, lx1), (lz0, lz1)):
        delta = p1 - p0
        if abs(delta) < 1e-12:
            # Parallel to this slab: either inside it for the whole segment
            # or the segment can never be inside the rectangle.
            if p0 < -half or p0 > half:
                return False
            continue
        t_a, t_b = (-half - p0) / delta, (half - p0) / delta
        if t_a > t_b:
            t_a, t_b = t_b, t_a
        t_enter = max(t_enter, t_a)
        t_exit = min(t_exit, t_b)
        if t_enter > t_exit:
            return False
    return True


def footprint_hits_aabb(cx: float, cz: float, width_m: float, yaw_deg: float,
                        min_x: float, min_z: float, max_x: float,
                        max_z: float) -> bool:
    """Whether the rotated footprint overlaps an axis-aligned box.

    Separating-axis test over the 4 axes two rectangles can be separated
    on (both world axes + both footprint axes). Used to decide whether a
    nav cell is blocked: testing only the cell CENTRE lets a route cut the
    corner of a building between two "free" centres.
    A shared edge counts as an overlap — the conservative answer, matching
    the inclusive :func:`point_in_footprint`.

    Hand-derived: footprint at (0, 0), width 2, yaw 45 — its corners sit at
    (±√2, 0) and (0, ±√2). The cell [0,2]×[0,2] overlaps it (the corner
    (√2, 0) ≈ (1.41, 0) is inside the box's x-range and the box reaches the
    origin), while the cell [1,3]×[1,3] does not: projected on the
    footprint's local axis (0.707, 0.707) the footprint spans [-1, 1] and
    the box spans [1.41, 4.24] — a gap.
    """
    if not width_m or width_m <= 0:
        return False
    rad = math.radians(yaw_deg or 0.0)
    cos_y, sin_y = math.cos(rad), math.sin(rad)
    corners = footprint_corners(cx, cz, width_m, yaw_deg)
    box = [(min_x, min_z), (max_x, min_z), (max_x, max_z), (min_x, max_z)]
    axes = ((1.0, 0.0), (0.0, 1.0), (cos_y, -sin_y), (sin_y, cos_y))
    for ax, az in axes:
        a_vals = [x * ax + z * az for x, z in corners]
        b_vals = [x * ax + z * az for x, z in box]
        if max(a_vals) < min(b_vals) or max(b_vals) < min(a_vals):
            return False
    return True


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
        px, pz = float(px), float(pz)
        width = float((loc.get("map3d") or {}).get("plan_width_m"))
        yaw = float(loc.get("yaw_deg") or 0.0)
    except (TypeError, ValueError):
        return None
    # isfinite first: every NaN comparison is False, so the width check
    # below would wave a NaN through and every consumer downstream (bounds,
    # nav grid, JSON encoding with allow_nan=False) inherits the poison.
    if not (math.isfinite(px) and math.isfinite(pz)
            and math.isfinite(width) and math.isfinite(yaw)):
        return None
    if width <= 0:
        return None
    return (px, pz, width, yaw)


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
