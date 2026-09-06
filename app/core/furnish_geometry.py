"""Plan-view geometry primitives for the furnishing solver (plan-furnish-v2.md
§ 2 B1/B4, task 2).

Pure functions, no I/O, no randomness, no state — everything the solver needs to
turn metres into quads, project them onto axes and ask whether two things touch.
The solver itself (:mod:`app.core.furnish_solver`) keeps only the passes.

THE FRAME. Metres from the room polygon's min corner, ``x`` → east, ``z`` →
south (plan view, z grows downwards on screen). Compass follows the room-marker
vocabulary: **0 = S, 90 = E, 180 = N, 270 = W**, so a compass angle ``c`` is the
unit vector ``(sin c, cos c)``.

THE TURN (ruling 2026-09-06 — this fixes a v1 bug). A placement ``yaw`` turns
like the renderer, ``rotation.y = +rad(yaw)`` = ``R_y(+yaw)``::

    (x, z) → (x·cos r + z·sin r, −x·sin r + z·cos r),  r = radians(yaw)

which is exactly what ``room_recipe.compose_prop_marker`` and
``docs/schnittstellen-3d.md`` § B2 do. Two consequences the whole solver rests
on:

* a prop's front points SOUTH at yaw 0 and its **front compass is
  ``(0 + yaw) mod 360``** — a yaw-90 desk faces EAST (v1 used the transpose and
  faced it west);
* the object-local axes land as ``local +z`` = the front (depth) axis and
  ``local +x`` = compass ``yaw + 90``, i.e. the piece's own LEFT when it looks
  along its front. That is the same child frame ``room_recipe.compose_on_chain``
  composes, so a surface child's ``at`` needs no second convention.

The wall table follows from the front rule alone — a wall piece looks INTO the
room, so its front compass is the wall's opposite direction::

    wall_n → front S → yaw   0      wall_s → front N → yaw 180
    wall_w → front E → yaw  90      wall_e → front W → yaw 270
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vec = Tuple[float, float]

# Touching is not overlapping — every interval/SAT test opens by this much.
EPS = 1e-9

# Compass unit vectors (0 = S, 90 = E, 180 = N, 270 = W).
COMPASS_VEC: Dict[str, Vec] = {
    "s": (0.0, 1.0), "e": (1.0, 0.0), "n": (0.0, -1.0), "w": (-1.0, 0.0)}
COMPASS_DEG: Dict[str, float] = {"s": 0.0, "e": 90.0, "n": 180.0, "w": 270.0}
# Wall class → yaw that points the front INTO the room (see module docstring).
WALL_YAW_ROOM: Dict[str, float] = {"n": 0.0, "e": 270.0, "s": 180.0, "w": 90.0}


def compass_vec(deg: float) -> Vec:
    """Unit vector for a compass angle (0 = S, 90 = E, 180 = N, 270 = W)."""
    r = math.radians(deg % 360.0)
    return (math.sin(r), math.cos(r))


def compass_of(vec: Vec) -> float:
    """Inverse of :func:`compass_vec` — the compass angle a vector points at."""
    return math.degrees(math.atan2(vec[0], vec[1])) % 360.0


def rect_corners(cx: float, cz: float, w: float, d: float,
                 yaw_deg: float) -> List[Vec]:
    """Corners of a w×d rectangle centred at (cx, cz), turned by ``R_y(+yaw)``.

    Local corner (dx, dz) lands at ``(cx + dx·cos r + dz·sin r,
    cz − dx·sin r + dz·cos r)`` — so local ``+z`` is the front axis and local
    ``+x`` points at compass ``yaw + 90``.
    """
    r = math.radians(yaw_deg % 360.0)
    c, s = math.cos(r), math.sin(r)
    out: List[Vec] = []
    for dx, dz in ((-w / 2, -d / 2), (w / 2, -d / 2),
                   (w / 2, d / 2), (-w / 2, d / 2)):
        out.append((cx + dx * c + dz * s, cz - dx * s + dz * c))
    return out


def local_to_world(sx: float, sz: float, syaw: float,
                   dx: float, dz: float) -> Vec:
    """A point of the support's UNTURNED local frame in room metres — the very
    transform ``room_recipe.compose_on_chain`` applies to a child placement."""
    r = math.radians(syaw % 360.0)
    c, s = math.cos(r), math.sin(r)
    return (sx + dx * c + dz * s, sz - dx * s + dz * c)


def aabb_extents(w: float, d: float, yaw_deg: float) -> Tuple[float, float]:
    """Axis-aligned extents of the turned rectangle (x extent, z extent)."""
    r = math.radians(yaw_deg % 360.0)
    c, s = abs(math.cos(r)), abs(math.sin(r))
    return (w * c + d * s, w * s + d * c)


def half_extent(w: float, d: float, yaw_deg: float, axis: Vec) -> float:
    """Half the rectangle's extent projected on a UNIT axis — the distance from
    its centre to its silhouette in that direction."""
    r = math.radians(yaw_deg % 360.0)
    c, s = math.cos(r), math.sin(r)
    # Local +x lands at (c, −s), local +z at (s, c).
    return (abs((w / 2) * (c * axis[0] - s * axis[1]))
            + abs((d / 2) * (s * axis[0] + c * axis[1])))


def poly_area(pts: Sequence[Vec]) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, z1 = pts[i]
        x2, z2 = pts[(i + 1) % len(pts)]
        a += x1 * z2 - x2 * z1
    return abs(a) / 2.0


def point_in_poly(pt: Vec, poly: Sequence[Vec]) -> bool:
    x, z = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        if (z1 > z) != (z2 > z):
            xi = x1 + (z - z1) / (z2 - z1) * (x2 - x1)
            if x < xi:
                inside = not inside
    return inside


def rect_in_poly(corners: Sequence[Vec], poly: Sequence[Vec]) -> bool:
    """Corners plus edge midpoints inside — a cheap, adequate containment test
    for convex furniture rectangles in drawn hulls."""
    for i, c in enumerate(corners):
        if not point_in_poly(c, poly):
            return False
        nxt = corners[(i + 1) % len(corners)]
        if not point_in_poly(((c[0] + nxt[0]) / 2, (c[1] + nxt[1]) / 2), poly):
            return False
    return True


def project(corners: Sequence[Vec], axis: Vec) -> Tuple[float, float]:
    dots = [c[0] * axis[0] + c[1] * axis[1] for c in corners]
    return min(dots), max(dots)


def rects_overlap(a: Sequence[Vec], b: Sequence[Vec]) -> bool:
    """Separating-axis test for two convex quads (touching ≠ overlap)."""
    for quad in (a, b):
        for i in range(4):
            ex = quad[(i + 1) % 4][0] - quad[i][0]
            ez = quad[(i + 1) % 4][1] - quad[i][1]
            axis = (-ez, ex)
            a_lo, a_hi = project(a, axis)
            b_lo, b_hi = project(b, axis)
            if a_hi <= b_lo + EPS or b_hi <= a_lo + EPS:
                return False
    return True


def spans_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    """Height intervals — touching (a shelf ON a table) is not an overlap."""
    return a1 > b0 + EPS and b1 > a0 + EPS


def point_segment_distance(p: Vec, a: Vec, b: Vec) -> float:
    ax, az = a
    bx, bz = b
    dx, dz = bx - ax, bz - az
    ll = dx * dx + dz * dz
    if ll <= EPS:
        return math.hypot(p[0] - ax, p[1] - az)
    t = ((p[0] - ax) * dx + (p[1] - az) * dz) / ll
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (az + t * dz))


def normalize_outline(outline_m: Sequence[Sequence[float]]
                      ) -> Tuple[List[Vec], float, float]:
    """Polygon shifted onto its own min corner, plus its bounding extents."""
    xs = [float(p[0]) for p in outline_m]
    zs = [float(p[1]) for p in outline_m]
    x0, z0 = min(xs), min(zs)
    poly = [(float(p[0]) - x0, float(p[1]) - z0) for p in outline_m]
    return poly, max(xs) - x0, max(zs) - z0


def edge_geometry(poly: Sequence[Vec], centroid: Vec,
                  idx: int) -> Tuple[Vec, Vec, Vec, float]:
    """Edge start, unit direction, INWARD unit normal and length."""
    a = poly[idx % len(poly)]
    b = poly[(idx + 1) % len(poly)]
    ex, ez = b[0] - a[0], b[1] - a[1]
    length = math.hypot(ex, ez) or 1.0
    d = (ex / length, ez / length)
    n = (d[1], -d[0])
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    to_c = (centroid[0] - mid[0], centroid[1] - mid[1])
    if n[0] * to_c[0] + n[1] * to_c[1] < 0:
        n = (-n[0], -n[1])
    return a, d, n, length


def wall_edges(poly: Sequence[Vec], centroid: Vec, wall: str) -> List[int]:
    """Indices of the polygon edges whose OUTWARD normal points mostly in the
    wall's compass direction (the v1 rule, kept verbatim: dot > 0.5)."""
    want = COMPASS_VEC[wall]
    out: List[int] = []
    for i in range(len(poly)):
        _, _, inward, _ = edge_geometry(poly, centroid, i)
        if -inward[0] * want[0] - inward[1] * want[1] > 0.5:
            out.append(i)
    return out


def edge_wall_class(poly: Sequence[Vec], centroid: Vec, idx: int) -> str:
    """The compass class an edge belongs to — the direction its OUTWARD normal
    points at most. Deterministic tie order n, e, s, w."""
    _, _, inward, _ = edge_geometry(poly, centroid, idx)
    best, best_dot = "n", -2.0
    for wall in ("n", "e", "s", "w"):
        want = COMPASS_VEC[wall]
        dot = -inward[0] * want[0] - inward[1] * want[1]
        if dot > best_dot + 1e-6:
            best, best_dot = wall, dot
    return best


def centred_offsets(usable: float, step: float) -> List[float]:
    """0.5, then symmetric pairs outward — the deterministic slide order along
    a wall, expressed as fractions of the usable range."""
    if usable <= 0:
        return [0.5]
    ticks = max(1, int(usable / step))
    fracs = [0.5]
    for k in range(1, ticks + 1):
        f = k * step / usable / 2
        if 0.5 + f <= 1.0:
            fracs.append(0.5 + f)
        if 0.5 - f >= 0.0:
            fracs.append(0.5 - f)
    return fracs


def symmetric_ticks(half: float, step: float) -> List[float]:
    """Grid coordinates over ``[−half, +half]`` in ``step`` increments, ordered
    centre first then outward: 0, +step, −step, +2·step, … — the two-axis
    sibling of :func:`centred_offsets` used for surface rasters."""
    if half < 0:
        return []
    n = int(half / step + 1e-9)
    out = [0.0]
    for k in range(1, n + 1):
        out.append(k * step)
        out.append(-k * step)
    return out


class Zone:
    """Keep-out volume: a quad plus the height interval it blocks. A door strip
    blocks ``[0, opening height]`` (so a pendant lamp above it is fine); a
    window strip blocks ``[sill, sill + height]`` (so a shelf above it, or a
    chest below it, passes)."""

    __slots__ = ("corners", "y0", "y1", "opening")

    def __init__(self, corners: List[Vec], y0: float, y1: float,
                 opening: int) -> None:
        self.corners = corners
        self.y0 = y0
        self.y1 = y1
        self.opening = opening

    def blocks(self, corners: Sequence[Vec], y0: float, y1: float) -> bool:
        return (spans_overlap(y0, y1, self.y0, self.y1)
                and rects_overlap(corners, self.corners))


def strip_corners(p: Vec, direction: Vec, normal: Vec, half_width: float,
                  depth: float) -> List[Vec]:
    """The rectangle that starts on an edge at ``p``, reaches ``depth`` into the
    room along ``normal`` and is ``2·half_width`` wide along ``direction``."""
    a = (p[0] + direction[0] * half_width, p[1] + direction[1] * half_width)
    b = (p[0] - direction[0] * half_width, p[1] - direction[1] * half_width)
    return [a, (a[0] + normal[0] * depth, a[1] + normal[1] * depth),
            (b[0] + normal[0] * depth, b[1] + normal[1] * depth), b]


def opening_zones(poly: Sequence[Vec], centroid: Vec,
                  openings: Optional[Sequence[Dict[str, Any]]],
                  door_clear_m: float = 0.6,
                  window_clear_m: float = 0.6) -> List[Zone]:
    """Keep-out zones in front of the openings (B11, B16).

    Door/passage: depth ``max(0.6, width_m)`` for a door — the leaf swings
    almost its full width into the room — and a flat 0.6 for a passage; width
    ``width_m + 0.4``; interval ``[0, height_m]`` (default 2.1).
    Window: depth 0.6, width ``width_m + 0.4``, interval
    ``[sill_m, sill_m + height_m]``.
    """
    zones: List[Zone] = []
    for index, op in enumerate(openings or []):
        try:
            edge = int(op.get("edge") or 0)
            at = float(op.get("at") or 0.5)
            width = float(op.get("width_m") or 1.0)
        except (TypeError, ValueError):
            continue
        typ = str(op.get("type") or "door")
        a, d, n, length = edge_geometry(poly, centroid, edge)
        p = (a[0] + d[0] * at * length, a[1] + d[1] * at * length)
        hw = (width + 0.4) / 2
        if typ == "window":
            try:
                sill = float(op.get("sill_m") or 0.9)
                height = float(op.get("height_m") or 1.2)
            except (TypeError, ValueError):
                sill, height = 0.9, 1.2
            zones.append(Zone(strip_corners(p, d, n, hw, window_clear_m),
                              sill, sill + height, index))
            continue
        try:
            height = float(op.get("height_m") or 2.1)
        except (TypeError, ValueError):
            height = 2.1
        depth = max(door_clear_m, width) if typ == "door" else door_clear_m
        zones.append(Zone(strip_corners(p, d, n, hw, depth), 0.0, height, index))
    return zones


def opening_point(poly: Sequence[Vec], centroid: Vec,
                  op: Dict[str, Any]) -> Optional[Tuple[Vec, Vec, Vec, int]]:
    """Midpoint, edge direction and inward normal of one opening, plus its edge
    index — ``None`` when the opening does not name a usable edge."""
    try:
        edge = int(op.get("edge") or 0)
        at = float(op.get("at") or 0.5)
    except (TypeError, ValueError):
        return None
    if not poly:
        return None
    a, d, n, length = edge_geometry(poly, centroid, edge)
    p = (a[0] + d[0] * at * length, a[1] + d[1] * at * length)
    return p, d, n, edge % len(poly)
