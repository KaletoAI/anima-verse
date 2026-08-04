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

# Terrain relief (contract v5.2 Nr. 14): the DEFAULT resolution of the height
# field over the reference square — 16 × 16 cells, i.e. 17 × 17 support
# points. This is what every location produced before the wave width existed,
# so it stays the fallback for anything that does not set one. The actual
# count travels WITH the grid (its row count) and with ``terrain.step``, so
# server, 3D client and admin preview address the very same points and can be
# diffed numerically.
TERRAIN_CELLS = 16

# Bounds of the height field's resolution. TWO is the coarsest field that is
# not flat: the border ring is pinned to zero so neighbouring tiles meet, and
# a single cell would be nothing but border.
#
# TWENTY-TWO is the finest field the renderers can actually DRAW, and that is
# the binding limit — not taste. ``drapeGeometry``
# (packages/scene-render/src/terrain.ts) subdivides a plate only while its
# longest edge exceeds one cell, and it stops after ``MAX_SPLITS = 5``
# halvings. A plate spanning the reference square starts at its diagonal,
# e·√2, so the finest edge it ever reaches is e·√2 / 2⁵ = e / 22.63 — a
# 22-cell field (cell e/22) is still resolved, a 23-cell one (cell e/23) is
# not. Past that the payload would keep getting finer while the drawn ground
# stopped following. Raising this therefore means raising ``MAX_SPLITS``
# first, which costs triangles in EVERY location — and the complaint that
# brought this parameter into existence was ground that is too FINE.
RELIEF_CELLS_MIN = 2
RELIEF_CELLS_MAX = 22

# Spatial-hash constants for the per-point seed. Two large odd primes (the
# classic Teschner spatial-hash triple) so that neighbouring (i, j) land far
# apart in the xorshift state: seeding with ``seed + i + j`` would produce a
# visibly striped field, because adjacent seeds share most of their bits.
TERRAIN_HASH_I = 73856093
TERRAIN_HASH_J = 19349663


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


def variant_mix(base_seed: int, variant: int) -> int:
    """Mix a clone's variant number into one of its stored seeds.

    A clone of a location stores almost nothing of its own — every field it
    does not carry is merged in from the template at read time, and that
    includes the scatter seeds of its props and the seed of its relief. Two
    copies of the same template therefore used to look identical down to the
    last blade of grass.

    A clone carries ONE variant number, drawn when it is placed on the map.
    Mixing it into every stored seed makes the whole copy differ while keeping
    it FIXED: the same pair always yields the same number, so a copy does not
    reshuffle on every load.

    ``variant == 0`` returns the stored seed unchanged — that is what every
    location predating this change carries, and it keeps its exact look.

    The mix is the same xorshift32 step the height field already uses
    (``XorShift32``), so a result can be re-derived by hand for verification.
    """
    v = int(variant) & 0xFFFFFFFF
    if not v:
        return int(base_seed) & 0xFFFFFFFF
    return XorShift32((int(base_seed) & 0xFFFFFFFF)
                      ^ (v * 0x9E3779B1 & 0xFFFFFFFF)).next()


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


def relief_cells(wave_m: Any, extent_m: Any) -> int:
    """How many grid cells a wave of ``wave_m`` metres needs over the square.

    The author sets a LENGTH — how wide one ground swell is — because a cell
    count means nothing at the drawing board. One cell is one swell's support
    spacing, so the count is simply the square divided by the wave, clamped.

    Both lengths must be in the SAME frame, and the caller owes REAL metres
    on both: the wave width is authored in real metres, so the reference
    square has to arrive as its real edge length (``extent_m / k``), not as
    its world extent.

    Anything unusable (zero, negative, no extent) falls back to
    ``TERRAIN_CELLS``, which over an 80 m square is a 5 m wave — exactly what
    every location produced before this parameter existed.

    Rounding is HALF-UP (``int(q + 0.5)``), not Python's banker's rounding:
    the admin caption tells the author how many swells the setting produces
    and computes it in JavaScript, whose ``Math.round`` is half-up. With
    ``round`` an exact .5 quotient promised one swell more than the server
    built.
    """
    try:
        wave = float(wave_m)
        extent = float(extent_m)
    except (TypeError, ValueError):
        return TERRAIN_CELLS
    if wave <= 0 or extent <= 0:
        return TERRAIN_CELLS
    return max(RELIEF_CELLS_MIN,
               min(RELIEF_CELLS_MAX, int(extent / wave + 0.5)))


def terrain_grid(seed: int,
                 amplitude_world: float,
                 flat_hulls: Sequence[Sequence[Sequence[float]]] = (),
                 cells: int = TERRAIN_CELLS,
                 ) -> List[List[float]]:
    """The location's height field as ``grid[j][i]`` support points.

    ``cells`` is the resolution: the grid spans the reference square as
    ``n × n`` cells, i.e. ``n + 1`` support points per side, clamped to
    [``RELIEF_CELLS_MIN``, ``RELIEF_CELLS_MAX``]. It comes from the authored
    wave width via :func:`relief_cells` — fewer cells mean wider, gentler
    swells, more cells mean a choppier field at the same amplitude. The
    default reproduces the fixed 16 × 16 field every location had before the
    wave width existed.

    ``i`` runs west→east, ``j`` north→south; point (i, j) sits at plan
    fraction (i/n, j/n) of the reference square. Values are WORLD metres —
    the caller has already multiplied the real-metre amplitude by k, because
    everything downstream (prop lift, plate drape) is world metres too.

    Two kinds of point are pinned to zero, and both are structural rather
    than cosmetic:

    * **The border** (i or j at 0 or n). Neighbouring map tiles compute
      their own field from their own seed and would otherwise meet at a
      cliff; a zero rim makes every tile edge match every other one.
    * **Flat hulls** — the tessellated outlines of rooms that must stay
      even (every indoor room, plus outdoor rooms flagged ``relief_flat``:
      a road, a paved square), DILATED by one grid cell: a point is pinned
      when it lies inside a hull or within one cell (1/n plan fraction)
      of its boundary. Without the margin only the points INSIDE were
      zero, and the boundary cells interpolated the neighbours' heights
      back INTO the room — the draped ground pierced the flat road plate
      and chopped it up (user finding 2026-08-02). With it, every cell
      that touches the hull has all-zero corners, so the field is exactly
      0 across the whole flat room and the ramp starts one cell outside.

    Every other point draws ONE number from a xorshift32 seeded with the
    spatial hash of (seed, i, j) — position-independent, so a point keeps
    its height no matter which order or how often it is computed, and the
    field can be re-derived by hand for § B5a verification. The draw is
    mapped from [0, 1) to [−1, 1) and scaled by the amplitude.

    ``flat_hulls`` are polygons in ABSOLUTE plan fractions and must arrive
    already tessellated (curved room edges) — this function does not know
    about curves.
    """
    n = max(RELIEF_CELLS_MIN, min(RELIEF_CELLS_MAX, int(cells)))
    amp = float(amplitude_world)
    hulls = [h for h in flat_hulls if len(h) >= 3]
    margin = 1.0 / n

    def _flat(u: float, v: float) -> bool:
        for hull in hulls:
            if point_in_poly((u, v), hull):
                return True
            m = len(hull)
            for a in range(m):
                ax, ay = float(hull[a][0]), float(hull[a][1])
                bx, by = float(hull[(a + 1) % m][0]), float(hull[(a + 1) % m][1])
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                t = 0.0 if l2 <= 0 else max(0.0, min(1.0, ((u - ax) * dx
                                                           + (v - ay) * dy) / l2))
                qx, qy = ax + t * dx, ay + t * dy
                if (u - qx) ** 2 + (v - qy) ** 2 <= margin * margin:
                    return True
        return False

    grid: List[List[float]] = []
    for j in range(n + 1):
        row: List[float] = []
        for i in range(n + 1):
            if i == 0 or j == 0 or i == n or j == n:
                row.append(0.0)
                continue
            if _flat(i / n, j / n):
                row.append(0.0)
                continue
            rng = XorShift32((int(seed) + i * TERRAIN_HASH_I
                              + j * TERRAIN_HASH_J) & 0xFFFFFFFF)
            value = round((rng.next01() * 2.0 - 1.0) * amp, 4)
            row.append(value if value else 0.0)  # never −0.0 in payloads
        grid.append(row)
    return grid


def terrain_height(grid: Sequence[Sequence[float]], u: float,
                   v: float) -> float:
    """Bilinear sample of the height field at plan fraction (u, v).

    The grid is a coarse lattice (17 × 17 points at the default resolution)
    but every object in the scene stands somewhere between its points, so the
    field has to be continuous — and it has to be continuous the SAME way in
    Python and in the renderers, or a prop the server lifted by 0.3 m would
    sit on ground the client drapes to 0.28 m. Bilinear over the four
    surrounding points is the cheapest such rule and the one both sides
    implement.

    (u, v) is clamped to [0, 1]²; a sample exactly on the far edge falls back
    into the last cell (fraction 1.0), so u = 1 reads the border point.
    """
    if not grid or not grid[0]:
        return 0.0
    n = len(grid) - 1
    fx = min(max(float(u), 0.0), 1.0) * n
    fy = min(max(float(v), 0.0), 1.0) * n
    i = min(int(fx), n - 1)
    j = min(int(fy), n - 1)
    tx = fx - i
    ty = fy - j
    north = grid[j][i] * (1.0 - tx) + grid[j][i + 1] * tx
    south = grid[j + 1][i] * (1.0 - tx) + grid[j + 1][i + 1] * tx
    return north * (1.0 - ty) + south * ty
