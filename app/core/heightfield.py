"""The world heightfield — rastering the authored areas and sampling them.

THE GROUND OF THE OPEN WORLD (E8 task 2). Task 1 gave the rules a height to
ask about, but only inside a detail scene: outside every footprint the world
was still the flat v1 plate. This module is what makes ``ground_y(x, z)``
answer something, and it is the ONLY place a world height is computed.

Three steps, deliberately separate:

1. **Authoring** lives next door (``app/models/heightfield.py``): polygons
   with a ``height_m`` and a ``falloff_m``. Nobody edits a grid.
2. **Rastering** (:func:`rasterize`) turns those areas into a regular grid of
   support points. It is a pure function of the areas and the step — same
   areas, same grid, every time and on every machine.
3. **Sampling** (:func:`sample_height`) reads a height between the support
   points, BILINEARLY. It is the twin of the shared client sampler
   ``packages/scene-render/src/worldHeight.ts`` (``sampleWorldHeight``), and
   the two are checked against the same hand-derived table
   (``scripts/smoke_heightfield.py`` / ``client3d/scripts/smoke_world_height.mjs``).

**THE LATTICE IS ANCHORED AT THE WORLD ORIGIN**, never at ``world_bounds``.
Every grid point sits on a multiple of ``step_m`` counted from (0, 0), so
painting a new area at the far edge of the world grows the grid without moving
a single existing sample point. A grid derived from the current extent would
shift every height in the world whenever someone painted at its border — the
one failure mode that cannot be seen in a screenshot and ruins every stored
comparison (inventory finding 5).

**NO PLATEAU PASS HERE.** Flattening the ground under a location's footprint
is E8 task 4; this module rasters exactly what was authored and nothing else.
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger("heightfield")

#: Distance between two support points, in metres. Four metres is the scale of
#: the thing being described: a hill is tens of metres wide, and a walker
#: crosses one cell in a bit over a second. It travels WITH the dataset (the
#: ``world_heightfield`` row) so a stored grid always says what it is, rather
#: than being read back against whatever the constant happens to be later.
DEFAULT_STEP_M = 4.0

#: Support points a grid may have in total. Past this the raster is built at a
#: COARSER step (doubled until it fits) instead of being cut off: a world twice
#: as wide should get a coarser relief, not a relief that stops halfway. The
#: cap is a payload budget as much as a compute one — every client fetches the
#: whole grid.
MAX_POINTS = 120_000


# ── Sampling ────────────────────────────────────────────────────────────

def sample_height(field: Optional[Dict[str, Any]], x: float, z: float) -> float:
    """Height of the world ground at (x, z) in metres — bilinear.

    ``field`` is the payload shape: ``origin_x``/``origin_z`` (world metres of
    ``heights[0][0]``), ``step_m``, ``rows``/``cols`` and ``heights[j][i]``,
    the height at ``(origin_x + i·step, origin_z + j·step)``.

    Grid fraction, then cell and mix — the very formula the scene sampler uses
    (``scatter_curves.terrain_height`` / ``sampleTerrain``), only with a world
    origin instead of a plan fraction::

        fx = clamp((x − origin_x) / step, 0, cols − 1)
        i  = min(floor(fx), cols − 2),   tx = fx − i        (fz/j/tz likewise)
        north = h[j][i]·(1−tx) + h[j][i+1]·tx
        south = h[j+1][i]·(1−tx) + h[j+1][i+1]·tx
        h     = north·(1−tz) + south·tz

    OUTSIDE THE GRID the border value applies (the fraction is clamped), and
    that is not an approximation: :func:`rasterize` always lays a ring of
    points OUTSIDE every authored area, so the whole border is 0 and clamping
    means "the flat world". A field without at least 2 × 2 points carries no
    relief at all and answers 0.0.

    THE SHAPE IS TAKEN FROM THE ARRAY, not from ``rows``/``cols`` — those two
    are a description of the data and this function is on the walk-report path.
    A row shorter than the rest (a hand-edited row, a truncated write) must
    make a walker sample a slightly wrong height, never turn ``POST /play/pos``
    into a 500. The client sampler reads the array the same way.
    """
    if not field:
        return 0.0
    heights = field.get("heights") or []
    rows = len(heights)
    cols = len(heights[0]) if rows and isinstance(heights[0], list) else 0
    try:
        step = float(field.get("step_m") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if rows < 2 or cols < 2 or step <= 0:
        return 0.0
    fx = (float(x) - float(field.get("origin_x") or 0.0)) / step
    fz = (float(z) - float(field.get("origin_z") or 0.0)) / step
    fx = min(max(fx, 0.0), cols - 1.0)
    fz = min(max(fz, 0.0), rows - 1.0)
    i = min(int(math.floor(fx)), cols - 2)
    j = min(int(math.floor(fz)), rows - 2)
    tx = fx - i
    tz = fz - j

    def _at(row: Any, k: int) -> float:
        try:
            return float(row[k])
        except (TypeError, ValueError, IndexError, KeyError):
            return 0.0

    row_n = heights[j]
    row_s = heights[j + 1]
    north = _at(row_n, i) * (1.0 - tx) + _at(row_n, i + 1) * tx
    south = _at(row_s, i) * (1.0 - tx) + _at(row_s, i + 1) * tx
    return north * (1.0 - tz) + south * tz


# ── Rastering ───────────────────────────────────────────────────────────

def _seg_distance(px: float, pz: float, ax: float, az: float,
                  bx: float, bz: float) -> float:
    """Distance from a point to the segment a→b (metres)."""
    dx, dz = bx - ax, bz - az
    len2 = dx * dx + dz * dz
    if len2 <= 0:
        return math.hypot(px - ax, pz - az)
    t = ((px - ax) * dx + (pz - az) * dz) / len2
    t = min(max(t, 0.0), 1.0)
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def edge_distance(px: float, pz: float,
                  ring: Sequence[Sequence[float]]) -> float:
    """Shortest distance from (x, z) to the OUTLINE of a polygon, metres.

    The outline, not the interior: a point deep inside a large area is far from
    every edge, which is exactly what the ramp needs to know. Auto-closed, like
    every polygon in this world.
    """
    best = math.inf
    n = len(ring)
    for k in range(n):
        ax, az = float(ring[k][0]), float(ring[k][1])
        bx, bz = float(ring[(k + 1) % n][0]), float(ring[(k + 1) % n][1])
        d = _seg_distance(px, pz, ax, az, bx, bz)
        if d < best:
            best = d
    return best if best < math.inf else 0.0


def area_height_at(area: Dict[str, Any], x: float, z: float) -> Optional[float]:
    """What ONE height area makes of the point, or None when it does not cover
    it.

    Inside the outline the ground stands at ``height_m``, ramping there
    linearly over the last ``falloff_m`` metres::

        h = height_m · min(1, distance_to_outline / falloff_m)

    so the area meets the world at 0 exactly ON its outline and needs no
    matching neighbour to look continuous. ``falloff_m`` 0 means no ramp: the
    full height right up to the edge, a wall — legal, and what the editor
    warns about when it is steeper than a walker can climb.
    """
    ring = area.get("polygon") or []
    if len(ring) < 3:
        return None
    from app.core.world_geometry import point_in_polygon
    if not point_in_polygon(x, z, ring):
        return None
    height = float(area.get("height_m") or 0.0)
    falloff = float(area.get("falloff_m") or 0.0)
    if falloff <= 0:
        return height
    return height * min(1.0, edge_distance(x, z, ring) / falloff)


def _step_for(bounds: Tuple[float, float, float, float]) -> float:
    """The step this extent gets: the default, doubled until the grid fits
    inside :data:`MAX_POINTS`. Doubling keeps the lattice anchored at the world
    origin, so a coarser grid still samples a subset of the finer one's
    points."""
    min_x, min_z, max_x, max_z = bounds
    step = DEFAULT_STEP_M
    while True:
        cols = _axis_points(min_x, max_x, step)
        rows = _axis_points(min_z, max_z, step)
        if rows * cols <= MAX_POINTS or step >= 1024:
            if step > DEFAULT_STEP_M:
                # Said out loud: the resolution drops silently otherwise, and
                # it hangs on the UNION box of all height areas — ONE hill
                # painted far out coarsens the relief of the whole world.
                logger.info(
                    "Heightfield coarsened to a %s m step (%d x %d points): "
                    "the authored areas span %.0f x %.0f m, which is past the "
                    "%d-point budget at %s m",
                    step, rows, cols, max_x - min_x, max_z - min_z,
                    MAX_POINTS, DEFAULT_STEP_M)
            return step
        step *= 2.0


def _axis_origin(low: float, step: float) -> float:
    """First support point on one axis: the lattice point at or below ``low``,
    ONE step further out — the ring that pins the border to 0."""
    return math.floor(low / step) * step - step


def _axis_points(low: float, high: float, step: float) -> int:
    """Support points needed on one axis so the grid reaches one full step
    PAST ``high`` (the closing half of the 0-ring)."""
    origin = _axis_origin(low, step)
    return int(math.ceil((high + step - origin) / step)) + 1


def rasterize(areas: Sequence[Dict[str, Any]],
              step_m: float = 0.0) -> Dict[str, Any]:
    """The authored areas as a grid — pure, deterministic, no DB.

    Per support point the areas that COVER it are compared and the STRONGEST
    deflection from the flat world wins: the largest ``|value|``; at equal
    strength the greater value (a hill over a hollow of the same depth), and a
    true tie keeps what is already there. ``areas`` arrives in a stable order
    (insert order), so a tie is decided reproducibly rather than by whatever
    the DB returned first. For two hills the rule is exactly "the higher one
    wins"; it is written as a deflection so that a hollow (negative
    ``height_m``) is not silently beaten by the 0 of the flat world around it.

    A point no area covers is 0.0 — the unpainted world is flat, and there is
    no "default height" to configure.
    """
    from app.models.heightfield import polygon_bounds
    usable = [a for a in (areas or []) if len(a.get("polygon") or []) >= 3]
    boxes: List[Tuple[Dict[str, Any], Tuple[float, float, float, float]]] = []
    for area in usable:
        box = polygon_bounds(area.get("polygon"))
        if box is not None:
            boxes.append((area, box))
    if not boxes:
        return {"origin_x": 0.0, "origin_z": 0.0,
                "step_m": step_m or DEFAULT_STEP_M,
                "rows": 0, "cols": 0, "heights": []}

    min_x = min(b[1][0] for b in boxes)
    min_z = min(b[1][1] for b in boxes)
    max_x = max(b[1][2] for b in boxes)
    max_z = max(b[1][3] for b in boxes)
    bounds = (min_x, min_z, max_x, max_z)
    step = float(step_m) if step_m and step_m > 0 else _step_for(bounds)
    origin_x = _axis_origin(min_x, step)
    origin_z = _axis_origin(min_z, step)
    cols = _axis_points(min_x, max_x, step)
    rows = _axis_points(min_z, max_z, step)

    heights = [[0.0] * cols for _ in range(rows)]
    # Per area only the index window its own box covers — a world of small
    # hills must not cost "every area × every point".
    for area, (ax0, az0, ax1, az1) in boxes:
        i0 = max(0, int(math.floor((ax0 - origin_x) / step)))
        i1 = min(cols - 1, int(math.ceil((ax1 - origin_x) / step)))
        j0 = max(0, int(math.floor((az0 - origin_z) / step)))
        j1 = min(rows - 1, int(math.ceil((az1 - origin_z) / step)))
        for j in range(j0, j1 + 1):
            pz = origin_z + j * step
            row = heights[j]
            for i in range(i0, i1 + 1):
                value = area_height_at(area, origin_x + i * step, pz)
                if value is None:
                    continue
                current = row[i]
                # Stronger deflection wins; at equal strength the higher
                # value does (a hill over a hollow of the same depth), and a
                # true tie keeps what is there. `areas` arrives in a stable
                # order (insert order), so the result never depends on which
                # row the DB happened to return first.
                if abs(value) > abs(current) or (
                        abs(value) == abs(current) and value > current):
                    row[i] = value
    return {"origin_x": round(origin_x, 3), "origin_z": round(origin_z, 3),
            "step_m": step, "rows": rows, "cols": cols,
            "heights": [[round(v, 3) for v in row] for row in heights]}


# ── The cached world field ──────────────────────────────────────────────

#: Bumped by :func:`invalidate_cache`, i.e. by every authoring write. It is
#: what a cache hit is checked against, and checking it costs an integer
#: comparison — deliberately NOT the signature, which is a full read of every
#: area plus an md5 (1.4 ms, measured). ``ground_y`` runs on every walk report
#: and, from task 4 on, per nav CELL: a signature per call would be seconds per
#: route. The signature still decides whether the STORED raster may be used —
#: on a miss, where it costs nothing that matters.
_GENERATION = 0

#: (generation, field) of the field this process last built or loaded.
_CACHE: Optional[Tuple[int, Dict[str, Any]]] = None


def invalidate_cache() -> None:
    """Drop the cached field (tests + every authoring write).

    THE ONE WAY the cache learns about a change. A writer that goes round
    ``app/models/heightfield`` — raw SQL against ``height_areas`` — leaves this
    process on a stale grid until it is called; that is the price of not
    hashing on the read path, and there is no such writer in the app.
    """
    global _GENERATION, _CACHE
    _GENERATION += 1
    _CACHE = None


def get_field() -> Dict[str, Any]:
    """The current world heightfield, cached, with its ``sig``.

    Three levels, cheapest first: the process cache (an integer comparison),
    the raster stored in ``world_heightfield`` (a restart costs no rastering),
    and finally the raster itself, which is then stored. The stored row is only
    used when its signature still matches the areas — a grid that no longer
    describes what is authored is not a cache, it is a lie.

    **The returned dict is SHARED — treat it as read-only.** Every caller gets
    the very object the cache holds, so mutating it (a plateau pass writing
    into ``heights``, task 4) would rewrite the world for everyone else and
    survive until the next authoring write. Build a new grid instead; the
    payload route only reads.
    """
    global _CACHE
    from app.models import heightfield as store
    cached = _CACHE
    if cached is not None and cached[0] == _GENERATION:
        return cached[1]
    generation = _GENERATION
    sig = store.height_sig()
    stored = store.load_grid()
    if stored is not None and stored.get("sig") == sig:
        _CACHE = (generation, stored)
        return stored
    field = rasterize(store.list_height_areas())
    field["sig"] = sig
    try:
        store.store_grid(field)
    except Exception as exc:   # a cache that cannot be written is not fatal
        logger.warning("Could not store the rastered heightfield: %s", exc)
    _CACHE = (generation, field)
    return field


def world_height(x: float, z: float) -> float:
    """Height of the world ground at (x, z) — what ``ground_y`` answers."""
    return sample_height(get_field(), x, z)
