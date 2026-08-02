"""Curve tessellation + deterministic prop scatter (plan-area-detail-scenes.md).

Pure geometry, no I/O, no wall clock, no library randomness — identical
input yields identical output. The scene payload stays plain polygons:
curves exist only as editor data (``layout.outline_curves``) and are
tessellated HERE before anything downstream sees them. The PRNG is three
lines of integer arithmetic on purpose: § B5a verification re-implements it
independently in the smoke script and diffs exact positions.

Coordinate frames are the caller's business — both functions are
frame-agnostic (the sanitizer feeds bbox-local fractions, the recipe feeds
real metres). Only ``spacing`` and the footprints must share the frame of
``outline``.
"""

from typing import Any, Dict, List, Sequence, Tuple

# Segments a curved edge is split into (t = k/8). Fixed, not configurable:
# the number is part of the geometry contract — both the sanitizer's bbox
# fold and the recipe must agree on the exact points.
TESS_N = 8

# Attempts the scatter spends per requested prop before giving up. A short
# placement (dense room, many keep-outs) is fine — forests are not exact.
ATTEMPTS_PER_PROP = 30


def curve_map(curves: Any, edge_count: int) -> Dict[int, Tuple[float, float]]:
    """``outline_curves`` entries as {edge index: control point}. Invalid or
    out-of-range entries are dropped, later duplicates lose."""
    out: Dict[int, Tuple[float, float]] = {}
    for cur in curves if isinstance(curves, (list, tuple)) else []:
        if not isinstance(cur, dict):
            continue
        c = cur.get("c")
        if not isinstance(c, (list, tuple)) or len(c) != 2:
            continue
        try:
            edge = int(cur.get("edge"))
            pt = (float(c[0]), float(c[1]))
        except (TypeError, ValueError):
            continue
        if 0 <= edge < edge_count and edge not in out:
            out[edge] = pt
    return out


def tessellate(outline: Sequence[Sequence[float]], curves: Any,
               n: int = TESS_N) -> Tuple[List[List[float]], List[int]]:
    """Replace each curved edge by ``n`` straight segments.

    ``curves`` is the raw ``outline_curves`` list ({"edge": i, "c": [u, v]});
    edge i runs from vertex i to vertex i+1 (closed polygon). The inserted
    points are the quadratic bezier B(t) = (1-t)²·P0 + 2t(1-t)·C + t²·P1 at
    t = k/n for k = 1..n-1 — the original vertices stay, so straight edges
    are untouched.

    Returns ``(points, edge_map)`` where ``edge_map[i]`` is the index of the
    FIRST output edge belonging to original edge i (output edge j starts at
    ``points[j]``). Straight edges map onto exactly one output edge, so an
    opening on original edge i lives on output edge ``edge_map[i]`` with the
    same ``at``.
    """
    ctrl = curve_map(curves, len(outline))
    pts: List[List[float]] = []
    edge_map: List[int] = []
    m = len(outline)
    for i in range(m):
        p = outline[i]
        edge_map.append(len(pts))
        pts.append([float(p[0]), float(p[1])])
        c = ctrl.get(i)
        if c is None:
            continue
        q = outline[(i + 1) % m]
        for k in range(1, n):
            t = k / n
            s = 1.0 - t
            pts.append([s * s * float(p[0]) + 2 * t * s * c[0] + t * t * float(q[0]),
                        s * s * float(p[1]) + 2 * t * s * c[1] + t * t * float(q[1])])
    return pts, edge_map


class XorShift32:
    """xorshift32 — the whole algorithm, verbatim in the contract doc:
    ``x ^= x << 13; x ^= x >> 17; x ^= x << 5`` (uint32). Seed 0 is mapped
    to 1 (the all-zero state never leaves itself)."""

    def __init__(self, seed: int):
        self.x = int(seed) & 0xFFFFFFFF or 1

    def next(self) -> int:
        x = self.x
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.x = x
        return x

    def next01(self) -> float:
        """Uniform in [0, 1): next() / 2**32."""
        return self.next() / 4294967296.0


def point_in_poly(pt: Sequence[float], poly: Sequence[Sequence[float]]) -> bool:
    """Parity test — same routine as ``furnish_solver._point_in_poly``."""
    x, y = float(pt[0]), float(pt[1])
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = float(poly[i][0]), float(poly[i][1])
        x2, y2 = float(poly[(i + 1) % n][0]), float(poly[(i + 1) % n][1])
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xi:
                inside = not inside
    return inside


def scatter(seed: int,
            count: int,
            outline: Sequence[Sequence[float]],
            keepouts: Sequence[Sequence[Sequence[float]]] = (),
            spacing: float = 0.0) -> List[Dict[str, Any]]:
    """Deterministic rejection sampling over a room hull — ONE kind per call
    (scatter is a placement property; each scattering placement brings its
    own seed).

    ``keepouts`` = polygons in the outline's frame (a rect is a 4-point
    polygon). Per attempt EXACTLY three draws are consumed — u, v, yaw —
    whether the candidate is accepted or not, so the whole run is a fixed
    function of the seed. A candidate is accepted iff its centre lies inside
    the hull, outside every keep-out, and at least ``spacing`` away from
    every copy already placed IN THIS CALL. ``spacing`` is the whole
    density rule: 0 means copies may overlap — a forest's crowns do (the
    former footprint-based minimum kept every tree a crown apart, user
    finding 2026-08-02). Returns [{"at": [x, y], "yaw"}] in placement order.
    """
    rng = XorShift32(seed)
    xs = [float(p[0]) for p in outline]
    ys = [float(p[1]) for p in outline]
    if not xs or not ys or count <= 0:
        return []
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    placed: List[Dict[str, Any]] = []
    budget = int(count) * ATTEMPTS_PER_PROP
    while len(placed) < count and budget > 0:
        budget -= 1
        u = rng.next01()
        v = rng.next01()
        yaw = rng.next01()
        x = x0 + u * (x1 - x0)
        y = y0 + v * (y1 - y0)
        if not point_in_poly((x, y), outline):
            continue
        if any(point_in_poly((x, y), ko) for ko in keepouts):
            continue
        if spacing > 0:
            sp2 = float(spacing) * float(spacing)
            if any((x - o["at"][0]) ** 2 + (y - o["at"][1]) ** 2 < sp2
                   for o in placed):
                continue
        placed.append({"at": [x, y], "yaw": round(yaw * 360.0, 1)})
    return placed
