"""Pure world-coordinate geometry (Seamless World E1; polygon regions v6).

The world is a continuous plane measured in metres. Since contract v6
("Gebiete", 2026-08-19) a location is a drawn POLYGON: ``map3d.boundary``
holds its outline in local metres around the anchor pin (``pos_x``,
``pos_z``), rotated by ``yaw_deg`` around the vertical axis. The square
footprint (edge ``map3d.plan_width_m``) is the legacy special case and its
helpers remain only until every consumer has switched (stage 1 of
``plan-assets-im-szenenkontext.md``). Everything here is pure math — no DB,
no config — so the smoke checks derive every number by hand
(``scripts/smoke_world_polygon.py`` for the polygon half).

Axes follow the 3D client (three.js ground plane): x grows east, z grows
south. ``yaw_deg`` rotates clockwise when looking down onto the map, so at
yaw 90 the local +x axis points at world -z.

``ground_y`` is THE v2 reservation (plan-freie-weltkarte.md): terrain height
as a function of (x, z). Every consumer — placement, journeys, renderers —
derives y through this function and never persists it. E8 task 2 filled it in:
it is no longer 0.0 but the authored world relief, and it is the ONE function
that had to change for the world to become hilly.

That one function is also the ONE thing in this module that is not pure math:
it reads the rastered heightfield (``app.core.heightfield``, a cached grid over
the DB). The import is local to the function, so everything else here stays
DB-free and hand-checkable.
"""

import math
from typing import Any, Dict, List, Optional, Tuple


def ground_y(x: float, z: float) -> float:
    """Ground height at (x, z) in WORLD metres — the authored relief (E8).

    Bilinear over the rastered heightfield; 0.0 wherever nothing was authored,
    which is the whole world until someone paints a height area. The height of
    a DETAIL SCENE is not in here — a location's own relief is a second field
    on top of this one, and ``relief.ground_lift_at`` is where the two meet.
    """
    from app.core.heightfield import world_height
    return world_height(x, z)


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


def footprint_distance(x: float, z: float, cx: float, cz: float,
                       width_m: float, yaw_deg: float) -> float:
    """Shortest distance in metres from world point (x, z) to the rotated
    footprint square — **0 anywhere inside it**, edge inclusive.

    The exact companion of :func:`point_in_footprint`: same transform, same
    inclusive edge, and ``distance == 0`` is precisely what that function
    calls "inside". In the footprint's own frame the answer is the classic
    box distance — overshoot per axis, clamped at zero, combined by Pythagoras
    — which is why a point beside a face measures straight to that face while
    a point past a corner measures diagonally to the corner.

    Hand-derived, footprint at (50, 50) with edge 10 (so x, z ∈ [45, 55]):
      (50, 50) → 0        the centre
      (55, 50) → 0        ON the east edge
      (60, 50) → 5        5 m past that edge
      (58, 58) → hypot(3, 3) = 4.2426…   past the corner, both axes overshoot
    Turned by 45°, the same square around (200, 50) has its corners at
    (200 ± 5√2, 50) and (200, 50 ± 5√2):
      (207.0711, 50) → 0        exactly the rotated east corner
      (210, 50)      → 2.9289   = 10 − 5√2; via the transform (10, 0) becomes
                                local (7.0711, 7.0711), both 2.0711 past the
                                half-edge, hypot(2.0711, 2.0711) = 2.9289.

    A footprint without a size claims no point (``point_in_footprint`` says
    False, ``placed_footprint`` refuses it) — its distance is ``inf``, so no
    range can ever reach it and no caller needs a second "is it placed" test.
    """
    if not width_m or width_m <= 0:
        return math.inf
    lx, lz = world_to_local(x, z, cx, cz, yaw_deg)
    half = width_m / 2.0
    return math.hypot(max(abs(lx) - half, 0.0), max(abs(lz) - half, 0.0))


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


# --------------------------------------------------------------------------
# Polygon regions (contract v6 "Gebiete", 2026-08-19)
#
# A boundary is ``[[x, z], …]`` in LOCAL metres around the pin, auto-closed
# (no repeated last point stored). Winding: with x east and z south, a
# positive shoelace sum is CLOCKWISE in map view — the stored convention.
# Concave outlines are allowed (decision E1.1), so nothing below assumes
# convexity; overlap stays legal and the smallest AREA wins (E1.2).
# --------------------------------------------------------------------------


def _poly_points(points: Any) -> Optional[List[Tuple[float, float]]]:
    """Parse ``[[x, z], …]`` into float tuples; None on any malformed or
    non-finite entry or fewer than 3 points (a line claims no area)."""
    pts: List[Tuple[float, float]] = []
    for pt in (points or []):
        try:
            x, z = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not (math.isfinite(x) and math.isfinite(z)):
            return None
        pts.append((x, z))
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]          # tolerate an explicitly closed ring
    if len(pts) < 3:
        return None
    return pts


def polygon_points(points: Any) -> Optional[List[Tuple[float, float]]]:
    """The public reader for a stored outline: ``[[x, z], …]`` parsed into
    float tuples, an explicit closing point dropped, None when it is no
    polygon (malformed, non-finite, fewer than 3 points).

    Everything that has to ask "is there an outline here, and which points
    are it" goes through this one parse — the scene composer as much as the
    geometry below it."""
    return _poly_points(points)


def polygon_signed_area(points: Any) -> float:
    """Shoelace sum — POSITIVE means clockwise in map view (x east, z south).

    Hand-derived on the triangle (0,0) (1,0) (0,1): east, then south-west,
    then north — clockwise on the map — and the sum is +0.5.
    """
    pts = _poly_points(points)
    if pts is None:
        return 0.0
    total = 0.0
    j = len(pts) - 1
    for i, (xi, zi) in enumerate(pts):
        xj, zj = pts[j]
        total += xj * zi - xi * zj
        j = i
    return total / 2.0


def polygon_area(points: Any) -> float:
    """Enclosed area in m² regardless of winding; 0.0 when degenerate."""
    return abs(polygon_signed_area(points))


def polygon_bounds(points: Any) -> Optional[Tuple[float, float, float, float]]:
    """Axis-aligned bounds (min_x, min_z, max_x, max_z), or None."""
    pts = _poly_points(points)
    if pts is None:
        return None
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    return (min(xs), min(zs), max(xs), max(zs))


def _point_segment_distance(px: float, pz: float, ax: float, az: float,
                            bx: float, bz: float) -> float:
    """Distance from point to the closed segment a→b."""
    dx, dz = bx - ax, bz - az
    length_sq = dx * dx + dz * dz
    if length_sq < 1e-18:
        return math.hypot(px - ax, pz - az)
    t = ((px - ax) * dx + (pz - az) * dz) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def polygon_distance(x: float, z: float, points: Any) -> float:
    """Shortest distance to the polygon — **0 anywhere inside**, edges
    inclusive; ``inf`` for a degenerate outline (nothing can reach it).

    The polygon companion of :func:`footprint_distance`, and the primitive
    the plateau ramp ring (§ A16.1 v6) is built on. Hand-derived on the
    L-shape (0,0) (4,0) (4,2) (2,2) (2,4) (0,4):
      (1, 1)   → 0        inside the wide arm
      (5, 1)   → 1        1 m east of the x=4 edge
      (3, 3)   → 1        in the notch; both notch edges are 1 m away
      (-3, -4) → 5        past the (0,0) corner, hypot(3, 4)
    """
    pts = _poly_points(points)
    if pts is None:
        return math.inf
    if point_in_polygon(x, z, pts):
        return 0.0
    best = math.inf
    j = len(pts) - 1
    for i, (xi, zi) in enumerate(pts):
        xj, zj = pts[j]
        best = min(best, _point_segment_distance(x, z, xj, zj, xi, zi))
        j = i
    return best


def _orient(ax: float, az: float, bx: float, bz: float,
            cx: float, cz: float) -> float:
    """Twice the signed area of triangle abc (orientation predicate)."""
    return (bx - ax) * (cz - az) - (bz - az) * (cx - ax)


def _on_segment(ax: float, az: float, bx: float, bz: float,
                px: float, pz: float) -> bool:
    """Whether collinear point p lies within the closed box of segment a→b."""
    return (min(ax, bx) - 1e-12 <= px <= max(ax, bx) + 1e-12
            and min(az, bz) - 1e-12 <= pz <= max(az, bz) + 1e-12)


def _segments_intersect(p0x: float, p0z: float, p1x: float, p1z: float,
                        q0x: float, q0z: float, q1x: float, q1z: float) -> bool:
    """Whether two closed segments touch — a grazing contact counts (the
    conservative answer, matching :func:`segment_hits_footprint`)."""
    d1 = _orient(q0x, q0z, q1x, q1z, p0x, p0z)
    d2 = _orient(q0x, q0z, q1x, q1z, p1x, p1z)
    d3 = _orient(p0x, p0z, p1x, p1z, q0x, q0z)
    d4 = _orient(p0x, p0z, p1x, p1z, q1x, q1z)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) \
            and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return True
    if d1 == 0 and _on_segment(q0x, q0z, q1x, q1z, p0x, p0z):
        return True
    if d2 == 0 and _on_segment(q0x, q0z, q1x, q1z, p1x, p1z):
        return True
    if d3 == 0 and _on_segment(p0x, p0z, p1x, p1z, q0x, q0z):
        return True
    if d4 == 0 and _on_segment(p0x, p0z, p1x, p1z, q1x, q1z):
        return True
    return False


def segment_hits_polygon(x0: float, z0: float, x1: float, z1: float,
                         points: Any) -> bool:
    """Whether the straight segment touches the polygon (interior or rim).

    Edge-exact like :func:`segment_hits_footprint` — per-edge intersection
    plus an endpoint-containment test, so no sampling gap. Works unchanged
    for concave outlines (E1.1: no convex decomposition, tested edge-wise).

    Hand-derived on the L-shape above: (-1,3)→(5,3) crosses the thin arm
    -> True; (3,3)→(5,3) starts in the notch and stays east of it, and the
    right arm only reaches down to z=2 -> False.
    """
    pts = _poly_points(points)
    if pts is None:
        return False
    if point_in_polygon(x0, z0, pts) or point_in_polygon(x1, z1, pts):
        return True
    j = len(pts) - 1
    for i, (xi, zi) in enumerate(pts):
        xj, zj = pts[j]
        if _segments_intersect(x0, z0, x1, z1, xj, zj, xi, zi):
            return True
        j = i
    return False


def polygon_hits_aabb(points: Any, min_x: float, min_z: float,
                      max_x: float, max_z: float) -> bool:
    """Whether the polygon overlaps an axis-aligned box (edge touch counts).

    Exact for concave polygons: a vertex inside the box, a box corner inside
    the polygon, or any edge pair crossing. The nav-grid cell test (v6
    successor of :func:`footprint_hits_aabb`).
    """
    pts = _poly_points(points)
    if pts is None:
        return False
    bounds = polygon_bounds(pts)
    if bounds is None or bounds[0] > max_x or bounds[2] < min_x \
            or bounds[1] > max_z or bounds[3] < min_z:
        return False
    for x, z in pts:
        if min_x <= x <= max_x and min_z <= z <= max_z:
            return True
    box = [(min_x, min_z), (max_x, min_z), (max_x, max_z), (min_x, max_z)]
    for bx, bz in box:
        if point_in_polygon(bx, bz, pts):
            return True
    for k in range(4):
        b0x, b0z = box[k]
        b1x, b1z = box[(k + 1) % 4]
        if segment_hits_polygon(b0x, b0z, b1x, b1z, pts):
            return True
    return False


def polygons_overlap(points_a: Any, points_b: Any) -> bool:
    """Whether two polygons share any point (edge touch counts).

    The map-apply overlap WARNING (never an error — overlap is legal, E1.2).
    Covers containment both ways plus every edge crossing, so it is exact
    for concave shapes too.
    """
    pts_a = _poly_points(points_a)
    pts_b = _poly_points(points_b)
    if pts_a is None or pts_b is None:
        return False
    if any(point_in_polygon(x, z, pts_b) for x, z in pts_a):
        return True
    if any(point_in_polygon(x, z, pts_a) for x, z in pts_b):
        return True
    j = len(pts_a) - 1
    for i, (xi, zi) in enumerate(pts_a):
        xj, zj = pts_a[j]
        if segment_hits_polygon(xj, zj, xi, zi, pts_b):
            return True
        j = i
    return False


def polygon_self_intersects(points: Any) -> bool:
    """Whether the outline crosses itself (contract v6 Nr. 1 — a WARNING,
    never a rejection: the sanitizer stores such an outline unchanged).

    Every pair of NON-ADJACENT edges is tested with the exact segment
    predicate; adjacent edges are skipped because they share a vertex by
    construction and a grazing touch already counts as a hit there. Edge i
    runs from point i to point i+1, the last one back to point 0, so on
    ``n`` points edge 0 and edge n-1 are adjacent too.

    Hand-derived on the bow tie (0,0) (4,4) (4,0) (0,4): the only
    non-adjacent pairs are (e0, e2) and (e1, e3). e0 is the diagonal z = x,
    e2 runs (4,0) → (0,4) i.e. x + z = 4 — they meet at (2,2), inside both
    segments -> True. The L-shape of the polygon smoke has no such pair.
    """
    pts = _poly_points(points)
    if pts is None:
        return False
    n = len(pts)
    for i in range(n):
        a0, a1 = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue        # adjacent edges share a vertex by design
            b0, b1 = pts[j], pts[(j + 1) % n]
            if _segments_intersect(a0[0], a0[1], a1[0], a1[1],
                                   b0[0], b0[1], b1[0], b1[1]):
                return True
    return False


# Deterministic scan rows for the interior-point search: binary fractions,
# widest spacing first, never 0 or 1 (those rows graze the outline).
_INTERIOR_ROWS = (0.5, 0.25, 0.75, 0.375, 0.625, 0.125, 0.875,
                  0.0625, 0.9375, 0.3125, 0.6875, 0.1875, 0.8125)


def polygon_interior_point(points: Any) -> Optional[Tuple[float, float]]:
    """A DETERMINISTIC point guaranteed inside the polygon, or None.

    The plateau height (§ A16.1 v6) is read here instead of at the centroid:
    a concave polygon's centroid may lie outside it (the L-shape's centroid
    sits at (5/3, 5/3) — inside — but a U-shape's does not). Strategy: take
    the centroid when it verifiably lies inside; otherwise scan horizontal
    rows at fixed binary fractions of the height, collect the ray-casting
    crossings, and return the midpoint of the widest span. Same input, same
    answer — ``height_sig`` and both renderers can rely on it.
    """
    pts = _poly_points(points)
    if pts is None:
        return None
    area2 = polygon_signed_area(pts) * 2.0
    if abs(area2) > 1e-12:
        cx = cz = 0.0
        j = len(pts) - 1
        for i, (xi, zi) in enumerate(pts):
            xj, zj = pts[j]
            cross = xj * zi - xi * zj
            cx += (xj + xi) * cross
            cz += (zj + zi) * cross
            j = i
        cx /= 3.0 * area2
        cz /= 3.0 * area2
        if point_in_polygon(cx, cz, pts):
            return (cx, cz)
    bounds = polygon_bounds(pts)
    if bounds is None:
        return None
    min_x, min_z, max_x, max_z = bounds
    height = max_z - min_z
    if height <= 0:
        return None
    for frac in _INTERIOR_ROWS:
        row_z = min_z + height * frac
        crossings: List[float] = []
        j = len(pts) - 1
        for i, (xi, zi) in enumerate(pts):
            xj, zj = pts[j]
            j = i
            if (zi > row_z) != (zj > row_z):
                crossings.append((xj - xi) * (row_z - zi) / (zj - zi) + xi)
        if len(crossings) < 2 or len(crossings) % 2:
            continue        # row grazes a vertex — take the next row
        crossings.sort()
        best_mid: Optional[float] = None
        best_span = 0.0
        for k in range(0, len(crossings) - 1, 2):
            span = crossings[k + 1] - crossings[k]
            if span > best_span:
                best_span = span
                best_mid = (crossings[k] + crossings[k + 1]) / 2.0
        if best_mid is not None and best_span > 1e-9:
            candidate = (best_mid, row_z)
            if point_in_polygon(candidate[0], candidate[1], pts):
                return candidate
    return None


# How far off an edge the inside test is taken (metres). Small enough to stay
# inside the thinnest sane notch, large enough to survive the float noise of a
# rotated edge.
_INWARD_PROBE_M = 1e-3


def polygon_edge_count(points: Any) -> int:
    """How many edges the outline has — edge i runs point i → point i+1, the
    last one back to point 0. 0 for a degenerate outline."""
    pts = _poly_points(points)
    return 0 if pts is None else len(pts)


def polygon_edge_frame(points: Any, edge: Any, at: Any = 0.5
                       ) -> Optional[Tuple[Tuple[float, float],
                                           Tuple[float, float]]]:
    """``((x, z), (nx, nz))`` — a point on edge ``edge`` at fraction ``at``
    plus the UNIT INWARD normal there; None for a bad index or outline.

    The v6 successor of the four edge letters (contract v6 Nr. 5): a boundary
    opening names an edge INDEX and a fraction along it, and this is the ONE
    place that turns the pair into geometry. Both the scene payload
    (``scene_recipe._boundary_openings``) and the entry gate
    (``boundary_entry``) read it here, so the picture and the rule cannot
    disagree about where a gate is.

    ``at`` runs from point i to point i+1 and is clamped to [0, 1]; anything
    unreadable degrades to the edge MIDPOINT 0.5, the same degradation both
    consumers have always applied.

    INSIDE is measured, not assumed: the midpoint is probed a millimetre off
    the edge in both normal directions and the one that lands inside the
    polygon wins (ray casting, so concave outlines answer correctly). Only
    when neither or both probes land inside — a notch thinner than the probe,
    a self-intersecting bow tie — does the winding decide: with the stored
    clockwise winding (positive shoelace, x east / z south) the inward normal
    of edge (dx, dz) is ``(−dz, dx)``. Hand-derived on the square
    (−5,−5) (5,−5) (5,5) (−5,5): edge 0 runs east, ``(−dz, dx) = (0, +10)``
    normalized (0, 1) — south, i.e. into the square.
    """
    pts = _poly_points(points)
    if pts is None:
        return None
    try:
        idx = int(edge)
    except (TypeError, ValueError):
        return None
    if isinstance(edge, bool) or idx < 0 or idx >= len(pts):
        return None
    try:
        t = float(at)
    except (TypeError, ValueError):
        t = 0.5
    if not math.isfinite(t):
        t = 0.5
    t = min(max(t, 0.0), 1.0)
    ax, az = pts[idx]
    bx, bz = pts[(idx + 1) % len(pts)]
    dx, dz = bx - ax, bz - az
    length = math.hypot(dx, dz)
    if length < 1e-12:
        return None                     # a degenerate edge has no direction
    point = (ax + t * dx, az + t * dz)
    nx, nz = -dz / length, dx / length
    mid_x, mid_z = ax + dx / 2.0, az + dz / 2.0
    plus = point_in_polygon(mid_x + nx * _INWARD_PROBE_M,
                            mid_z + nz * _INWARD_PROBE_M, pts)
    minus = point_in_polygon(mid_x - nx * _INWARD_PROBE_M,
                             mid_z - nz * _INWARD_PROBE_M, pts)
    if minus and not plus:
        nx, nz = -nx, -nz
    return (point, (nx, nz))


def polygon_local_to_world(points: Any, cx: float, cz: float,
                           yaw_deg: float) -> Optional[List[Tuple[float, float]]]:
    """A local-metre boundary mapped through the ONE § A1.1 transform."""
    pts = _poly_points(points)
    if pts is None:
        return None
    return [local_to_world(lx, lz, cx, cz, yaw_deg) for lx, lz in pts]


def placed_boundary(loc: Dict[str, Any]) -> Optional[Tuple[float, float, float,
                                                           List[Tuple[float, float]]]]:
    """(cx, cz, yaw_deg, local boundary points) of a placed v6 location.

    Placed means: numeric, finite ``pos_x``/``pos_z`` AND a valid
    ``map3d.boundary`` (≥ 3 finite points). Without a boundary the location
    has no area and claims no point — the v6 successor of the missing
    scale anchor (there is NO 10 m fallback any more).
    """
    px, pz = loc.get("pos_x"), loc.get("pos_z")
    if px is None or pz is None:
        return None
    try:
        px, pz = float(px), float(pz)
        yaw = float(loc.get("yaw_deg") or 0.0)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(px) and math.isfinite(pz) and math.isfinite(yaw)):
        return None
    pts = _poly_points((loc.get("map3d") or {}).get("boundary"))
    if pts is None:
        return None
    return (px, pz, yaw, pts)


def effective_boundary(loc: Dict[str, Any]) -> Optional[Tuple[float, float, float,
                                                              List[Tuple[float, float]]]]:
    """(cx, cz, yaw_deg, local points) of a placed location — polygon ALWAYS.

    The v6 sentence "a square is just a special case of the polygon" made
    executable, and the ONE place that says so: a location with a drawn
    ``map3d.boundary`` returns it; one that still carries only the legacy
    square dial (``plan_width_m`` > 0) returns that square as its four
    corners, clockwise in map view. Consumers therefore reason about
    polygons only — no dual code paths anywhere downstream.

    TRANSITION (stage 1, plan-assets-im-szenenkontext.md): the square
    synthesis exists so worlds stay playable until every location has a
    drawn boundary; it dies together with the ``plan_width_m`` dial in the
    metric wave. It is NOT a 10 m fallback — a location without a boundary
    AND without a positive width has no area and returns None.
    """
    pb = placed_boundary(loc)
    if pb is not None:
        return pb
    fp = placed_footprint(loc)
    if fp is None:
        return None
    cx, cz, width, yaw = fp
    half = width / 2.0
    return (cx, cz, yaw, [(-half, -half), (half, -half),
                          (half, half), (-half, half)])


def boundary_world_points(loc: Dict[str, Any]) -> Optional[List[Tuple[float, float]]]:
    """The location's effective boundary in WORLD metres, or None."""
    eff = effective_boundary(loc)
    if eff is None:
        return None
    cx, cz, yaw, pts = eff
    return [local_to_world(lx, lz, cx, cz, yaw) for lx, lz in pts]


# Rim inclusion tolerance: a point ON a polygon edge measures distance 0.0
# exactly on axis-aligned edges and within float noise on rotated ones.
_RIM_EPS = 1e-9


def boundary_contains(loc: Dict[str, Any], x: float, z: float) -> bool:
    """Whether world point (x, z) lies inside the location's effective
    boundary, RIM INCLUSIVE on every edge — the v6 successor of
    :func:`point_in_footprint`, which was edge-inclusive on all four sides.

    The raw ray-cast (:func:`point_in_polygon`) is half-open (min edges in,
    max edges out) — good enough for raster cells, wrong for game state:
    travel ARRIVES exactly on the rim (``_arrival_point``), and a character
    standing on that point must be in the place they just reached. So the
    test is ``polygon_distance <= eps``: 0 inside by definition, 0 on the rim
    by geometry. Runs in the LOCAL frame (one inverse pin transform), where
    the polygon needs no per-query rotation.
    """
    eff = effective_boundary(loc)
    if eff is None:
        return False
    cx, cz, yaw, pts = eff
    lx, lz = world_to_local(x, z, cx, cz, yaw)
    return polygon_distance(lx, lz, pts) <= _RIM_EPS


def boundary_distance_m(loc: Dict[str, Any], x: float, z: float) -> float:
    """Distance from a world point to the effective boundary — 0 inside,
    ``inf`` for a location without area (v6 successor of
    :func:`footprint_distance`; rotation preserves distances, so the local
    frame answers for the world)."""
    eff = effective_boundary(loc)
    if eff is None:
        return math.inf
    cx, cz, yaw, pts = eff
    lx, lz = world_to_local(x, z, cx, cz, yaw)
    return polygon_distance(lx, lz, pts)


def boundary_segment_hits(loc: Dict[str, Any], x0: float, z0: float,
                          x1: float, z1: float) -> bool:
    """Whether a world segment touches the effective boundary (interior or
    rim) — v6 successor of :func:`segment_hits_footprint`. Both endpoints
    ride through the same inverse pin transform; straight lines stay
    straight, so the local-frame test is exact."""
    eff = effective_boundary(loc)
    if eff is None:
        return False
    cx, cz, yaw, pts = eff
    lx0, lz0 = world_to_local(x0, z0, cx, cz, yaw)
    lx1, lz1 = world_to_local(x1, z1, cx, cz, yaw)
    return segment_hits_polygon(lx0, lz0, lx1, lz1, pts)


def boundary_hits_aabb(loc: Dict[str, Any], min_x: float, min_z: float,
                       max_x: float, max_z: float) -> bool:
    """Whether the effective boundary overlaps a world-axis-aligned box —
    v6 successor of :func:`footprint_hits_aabb`. The box is axis-aligned in
    WORLD space, so here the polygon comes to the box (local→world), not
    the other way around."""
    pts = boundary_world_points(loc)
    if pts is None:
        return False
    return polygon_hits_aabb(pts, min_x, min_z, max_x, max_z)


def boundary_area_m2(loc: Dict[str, Any]) -> float:
    """Enclosed area of the effective boundary in m² (rotation-invariant),
    0.0 for a location without area — the tie-breaker of
    :func:`location_at_point`."""
    eff = effective_boundary(loc)
    if eff is None:
        return 0.0
    return polygon_area(eff[3])


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


def is_area_location(loc: Dict[str, Any]) -> bool:
    """Is this location OPEN GROUND rather than a built plate?

    The one server answer to "is that an area location" (user decision
    2026-08-13, round 2 of the E8 acceptance — the reach of the terrain pace
    and move-animation rule, ``terrain_query.ground_scope``). Two AUTHORED
    flags say it, and nothing else:

    * ``passable`` — a transit location one walks THROUGH (the road and
      forest clones of the terrain templates). It never had a building.
    * ``map3d.area_model`` — "the location model IS the ground of this
      place" (plan-area-locations.md; ``area_detail`` is only ever set on
      top of it, so it is covered).

    Deliberately NOT part of it: the style/terrain NAME vocabulary the 3D
    client uses to pick a procedural fallback texture (``forest``, ``water``,
    …). That is a guess from a word, and a guess must not decide how fast a
    character walks. A lake that should wade says so with the area flag.

    Pure math on a location dict, like everything else here — the client
    twin is ``client3d/src/scene/tiles.isAreaLocation``.
    """
    if bool(loc.get("passable")):
        return True
    map3d = loc.get("map3d")
    return bool(isinstance(map3d, dict) and map3d.get("area_model"))


def location_at_point(x: float, z: float,
                      locations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The location whose effective boundary contains (x, z) — the smallest
    AREA wins (contract v6, decision E1.2).

    Overlaps stay legal (a hut placed on a village square); the smallest
    enclosed area is the most specific answer — the polygon successor of the
    old smallest-width rule, and identical to it wherever both shapes are
    squares (width orders exactly like width²).
    """
    best: Optional[Dict[str, Any]] = None
    best_area = None
    for loc in locations or []:
        if not boundary_contains(loc, x, z):
            continue
        area = boundary_area_m2(loc)
        if best_area is None or area < best_area:
            best, best_area = loc, area
    return best
