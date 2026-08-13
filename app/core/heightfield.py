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

**THE PLATEAU PASS RUNS AFTER THE AREAS** (E8 task 4, :func:`level_plateaus`).
The authored areas are rastered first, purely; then the footprint of every
location THAT ASKED FOR IT is pinned flat to the ground under its own centre.
That order is the whole trick — the plateau's height is read from the authored
landscape BEFORE any of it is levelled, so a hill keeps carrying the place
standing on it.

**FLATTENING IS OPT-IN** (decision 2026-08-13, default OFF): the pass only ever
sees the locations whose ``level_ground`` flag is set, because
``models.heightfield.placed_footprints`` hands out no others. The landscape is
authored and does not mind the places on it — a rise INSIDE a location is a
thing one may want. Nothing in this module decides that; it only ever levels
what it is given.

**THE MICRO-RELIEF SITS BETWEEN THE TWO** (decision 2026-08-13, § A16.2). A
terrain KIND may carry random small hills (``relief_amplitude_m`` /
``relief_wave_m`` in the type catalog), and they are BAKED IN HERE rather than
rendered anywhere: the server's walking gate, the client's mirror and both
renderers read the one ``heights`` array, so a bumpy meadow cannot mean two
different grounds. The whole pass order is

    areas (strongest deflection) → micro-relief (ADDITIVE) → plateaus (win)

and each step is what it is because of the one before it: the relief is a
variation OF the authored landscape, not a competitor of it (hence additive,
after the |max| rule), and a levelled place stands on flat ground, not on flat
ground plus noise (hence the plateaus last).
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


# ── The micro-relief of a terrain kind ──────────────────────────────────

def relief_seed(kind: str) -> int:
    """The noise seed of a terrain kind — a stable hash OF ITS NAME.

    THERE IS NO SEED FIELD, on purpose (decision 2026-08-13): a seed is a
    number nobody can author meaningfully, and a stored one would have to be
    carried through every catalog edit, every export and every world clone to
    keep the ground still. The name already identifies the kind, so the hills
    of "grass" are the hills of "grass" in every world, and renaming a kind is
    honestly a different ground.

    The formula is FNV-1a, 32 bit — three lines of integer arithmetic so a
    smoke run can re-derive any support point by hand (§ B5a)::

        h = 2166136261
        for each byte b of kind, UTF-8:
            h = ((h XOR b) · 16777619) mod 2**32

    Different kinds therefore get unrelated hill patterns, and two areas of the
    SAME kind continue each other seamlessly — the lattice is one world-wide
    field per kind, not a per-area one.
    """
    h = 2166136261
    for byte in (kind or "").encode("utf-8"):
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return h


def relief_params(kind: str, entry: Any
                  ) -> Optional[Tuple[int, float, float]]:
    """``(seed, amplitude_m, wave_m)`` of a catalog entry, or None.

    None means "this ground is flat", and that is the answer for a missing
    key, a junk value, a non-finite one and an amplitude of 0 alike — the
    sanitizer already drops those keys on write
    (``terrain_types.sanitize_type``), so this is the reader's half of the
    same rule and covers a catalog row that never went through it.

    BOTH NUMBERS ARE CLAMPED HERE TOO, and the wave one matters: it is the
    Nyquist limit of the raster (2 × :data:`DEFAULT_STEP_M`), and a field that
    cannot carry its own wave would alias differently at every step size.
    """
    from app.core.terrain_types import (DEFAULT_RELIEF_WAVE_M,
                                        RELIEF_AMPLITUDE_MAX,
                                        RELIEF_AMPLITUDE_MIN, RELIEF_WAVE_MAX,
                                        RELIEF_WAVE_MIN)
    meta = entry.get("meta") if isinstance(entry, dict) else None
    if not isinstance(meta, dict):
        return None
    try:
        amp = float(meta.get("relief_amplitude_m") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(amp) or amp <= 0.0:
        return None
    amp = min(max(amp, RELIEF_AMPLITUDE_MIN), RELIEF_AMPLITUDE_MAX)
    try:
        wave = float(meta.get("relief_wave_m") or DEFAULT_RELIEF_WAVE_M)
    except (TypeError, ValueError, OverflowError):
        wave = DEFAULT_RELIEF_WAVE_M
    if not math.isfinite(wave) or wave <= 0.0:
        wave = DEFAULT_RELIEF_WAVE_M
    wave = min(max(wave, RELIEF_WAVE_MIN), RELIEF_WAVE_MAX)
    return (relief_seed(kind), round(amp, 2), round(wave, 2))


def lattice_noise(seed: int, u: int, v: int) -> float:
    """One lattice corner of the noise field, in [−1, 1).

    THE FORMULA OF THE OLD SCENE RELIEF, deliberately unchanged
    (``scatter_curves.terrain_grid``, whose constants are imported rather than
    copied): one xorshift32 draw seeded with the spatial hash of the corner::

        rnd(u, v) = XorShift32((seed + u·73856093 + v·19349663) mod 2**32)
                    .next01() · 2 − 1

    Position-independent, so a corner keeps its height no matter in which
    order, how often or on which machine it is computed — that is what makes
    the whole world heightfield reproducible.

    NEGATIVE CORNERS ARE WELL DEFINED: ``& 0xFFFFFFFF`` reads Python's
    unbounded negative integer as its two's complement, so the corner west of
    the world origin is a corner like any other and not a mirror of the one
    east of it.
    """
    from app.core.scatter_curves import (TERRAIN_HASH_I, TERRAIN_HASH_J,
                                         XorShift32)
    state = (int(seed) + int(u) * TERRAIN_HASH_I
             + int(v) * TERRAIN_HASH_J) & 0xFFFFFFFF
    return XorShift32(state).next01() * 2.0 - 1.0


def micro_relief_at(params: Optional[Tuple[int, float, float]],
                    x: float, z: float) -> float:
    """The micro-relief a terrain kind adds at (x, z), in metres.

    Value noise on a lattice of edge ``wave_m`` that is ANCHORED AT THE WORLD
    ORIGIN, exactly like the height grid itself: the corner indices are
    ``floor((x, z) / wave)``, and the value between four corners is bilinear —
    the same mixing rule :func:`sample_height` uses, so the field stays smooth
    where the raster samples it::

        u, v   = floor(x/wave), floor(z/wave);  tx, tz = the fractions
        north  = rnd(u, v)·(1−tx)   + rnd(u+1, v)·tx
        south  = rnd(u, v+1)·(1−tx) + rnd(u+1, v+1)·tx
        h      = (north·(1−tz) + south·tz) · amplitude

    There is NO fade at the painted contour, and that is a decision
    (2026-08-13): the field's own bilinear interpolation carries the transition
    over one grid step, and the worst case it can build is atan(2·amp/step) —
    45° at the maximum amplitude, which is why the amplitude is clamped.
    """
    if not params:
        return 0.0
    seed, amp, wave = params
    fx = float(x) / wave
    fz = float(z) / wave
    u = math.floor(fx)
    v = math.floor(fz)
    tx = fx - u
    tz = fz - v
    north = (lattice_noise(seed, u, v) * (1.0 - tx)
             + lattice_noise(seed, u + 1, v) * tx)
    south = (lattice_noise(seed, u, v + 1) * (1.0 - tx)
             + lattice_noise(seed, u + 1, v + 1) * tx)
    return (north * (1.0 - tz) + south * tz) * amp


def relief_inputs(terrain_areas: Sequence[Dict[str, Any]],
                  catalog: Optional[Dict[str, Dict[str, Any]]]
                  ) -> List[Tuple[Dict[str, Any],
                                  Optional[Tuple[int, float, float]],
                                  Tuple[float, float, float, float]]]:
    """The painted terrain the relief pass READS — ``(area, params, box)``.

    THE ONE PLACE THAT DECIDES WHAT THE FIELD DEPENDS ON, and it has two
    readers on purpose: :func:`rasterize` builds the ground from it, and
    ``models.heightfield.height_sig`` hashes it. A signature over a different
    list than the raster consumes is how a stale grid survives an edit.

    Two kinds of entry come back, in the areas' own bottom-to-top order:

    * an area whose KIND carries relief — ``params`` is its
      ``(seed, amplitude, wave)``;
    * an area whose kind does NOT, but which lies OVER one that does —
      ``params`` is None. It still matters, because the topmost kind at a
      point decides (``terrain_query.kind_at``): a paved square painted on a
      bumpy meadow flattens the ground it covers.

    Everything else is dropped, and that is the point of the filter: painting
    on a world whose catalog carries no relief at all changes NOTHING about
    the heightfield, so it must not change the signature and must not cost a
    re-raster. An empty list means the whole pass is a no-op.
    """
    catalog = catalog or {}
    params_by_kind: Dict[str, Tuple[int, float, float]] = {}
    for kind, entry in catalog.items():
        params = relief_params(kind, entry)
        if params is not None:
            params_by_kind[kind] = params
    if not params_by_kind:
        return []
    from app.models.heightfield import polygon_bounds
    out: List[Tuple[Dict[str, Any], Optional[Tuple[int, float, float]],
                    Tuple[float, float, float, float]]] = []
    active: List[Tuple[float, float, float, float]] = []
    for area in (terrain_areas or []):
        polygon = area.get("polygon") or []
        if len(polygon) < 3:
            continue
        box = polygon_bounds(polygon)
        if box is None:
            continue
        params = params_by_kind.get(str(area.get("kind") or ""))
        if params is None:
            # A flat kind is only an input where it can ERASE something: over
            # an area with relief that was painted BEFORE it. Anywhere else it
            # writes the 0 that is already there.
            # The test is the bounding BOXES, i.e. a superset of the true
            # polygon overlap: a flat area whose box merely touches a bumpy
            # one's box comes along as an input that erases nothing. That
            # costs one no-op entry in the list (and in the signature), never
            # a wrong height — the pass itself asks `kind_at` per cell.
            if not any(_overlaps(box, earlier) for earlier in active):
                continue
        else:
            active.append(box)
        out.append((area, params, box))
    return out


def _apply_micro_relief(origin_x: float, origin_z: float, step: float,
                        heights: List[List[float]],
                        relief: Sequence[Tuple[Dict[str, Any],
                                               Optional[Tuple[int, float,
                                                              float]],
                                               Tuple[float, float, float,
                                                     float]]]) -> None:
    """Add every kind's micro-relief onto the rastered areas — IN PLACE.

    TWO SWEEPS, and the first one is only there for the cost. Which kind is
    on top at a point is ``terrain_query.kind_at``'s rule — the LAST painted
    area containing it — and asking that per support point would walk every
    area for every one of up to 120 000 points. So the same rule is turned
    inside out: each area writes its own parameters into its own index window,
    in the areas' bottom-to-top order, and the last writer wins. Identical
    answer, "painted area × its own points" instead of "point × every area".

    The second sweep adds the noise where a kind was found. The lattice
    corners are memoised for the whole grid: at the default 32 m wave over a
    4 m step, sixty-four support points share the same four corners.

    THE EDGE RULE (user decision 2026-08-13, § A16.2): at a support point one
    of whose four grid neighbours carries NO relief, the noise is clamped to
    ``max(0, noise)``. A bumpy meadow may run OUT over its border — the
    bilinear interpolation carries a hill a little way into the water next to
    it, and a shore rising softly is what one wants — but it must never pull
    the flat neighbour DOWN, which is the acceptance finding: the seam of a
    lake sank with the grass beside it. The first sweep's buffer IS the mask,
    which is why this costs no second area scan: a neighbour without relief
    parameters is a flat topmost kind or unpainted ground, and both are ground
    this field has no business moving.

    THE 0-RING IS NOT TOUCHED and needs no special case: the grid always
    reaches one full step PAST the union box of everything that shaped it
    (:func:`_axis_origin`), so no painted polygon can contain a border point.
    """
    rows = len(heights)
    cols = len(heights[0]) if rows else 0
    if rows < 2 or cols < 2 or step <= 0 or not relief:
        return
    from app.core.world_geometry import point_in_polygon
    at_point: List[List[Optional[Tuple[int, float, float]]]] = [
        [None] * cols for _ in range(rows)]
    for area, params, (ax0, az0, ax1, az1) in relief:
        polygon = area.get("polygon")
        i0 = max(0, int(math.floor((ax0 - origin_x) / step)))
        i1 = min(cols - 1, int(math.ceil((ax1 - origin_x) / step)))
        j0 = max(0, int(math.floor((az0 - origin_z) / step)))
        j1 = min(rows - 1, int(math.ceil((az1 - origin_z) / step)))
        for j in range(j0, j1 + 1):
            pz = origin_z + j * step
            row = at_point[j]
            for i in range(i0, i1 + 1):
                if point_in_polygon(origin_x + i * step, pz, polygon):
                    row[i] = params
    corners: Dict[Tuple[int, int, int], float] = {}
    for j in range(rows):
        pz = origin_z + j * step
        krow = at_point[j]
        hrow = heights[j]
        for i in range(cols):
            params = krow[i]
            if params is None:
                continue
            seed, amp, wave = params
            fx = (origin_x + i * step) / wave
            fz = pz / wave
            u = math.floor(fx)
            v = math.floor(fz)
            tx = fx - u
            tz = fz - v
            n00 = _corner(corners, seed, u, v)
            n10 = _corner(corners, seed, u + 1, v)
            n01 = _corner(corners, seed, u, v + 1)
            n11 = _corner(corners, seed, u + 1, v + 1)
            north = n00 * (1.0 - tx) + n10 * tx
            south = n01 * (1.0 - tx) + n11 * tx
            noise = (north * (1.0 - tz) + south * tz) * amp
            # The edge rule: only a DIP is cut off, and only at the border of
            # the relief-carrying region (see the docstring). Asking for the
            # neighbours costs nothing where the noise lifts anyway.
            if noise < 0.0 and _flat_neighbour(at_point, i, j, rows, cols):
                noise = 0.0
            hrow[i] += noise


def _flat_neighbour(at_point: List[List[Optional[Tuple[int, float, float]]]],
                    i: int, j: int, rows: int, cols: int) -> bool:
    """Does one of the four grid neighbours of (i, j) carry no relief?

    The mask of the edge rule, read straight off the first sweep's buffer.
    A point ON the grid border counts as bordering flat ground: outside the
    grid the border value applies, and that ground is nobody's relief.
    """
    if i == 0 or j == 0 or i == cols - 1 or j == rows - 1:
        return True
    return (at_point[j - 1][i] is None or at_point[j + 1][i] is None
            or at_point[j][i - 1] is None or at_point[j][i + 1] is None)


def _corner(cache: Dict[Tuple[int, int, int], float],
            seed: int, u: int, v: int) -> float:
    """:func:`lattice_noise`, memoised per raster run. A cached 0.0 is a value
    like any other — hence the ``is None`` test and not a truth test."""
    key = (seed, u, v)
    value = cache.get(key)
    if value is None:
        value = lattice_noise(seed, u, v)
        cache[key] = value
    return value


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


def _footprint_box(fp: Tuple[float, float, float, float]
                   ) -> Tuple[float, float, float, float]:
    """Axis-aligned box around a rotated footprint square (cx, cz, w, yaw)."""
    from app.core.world_geometry import footprint_corners
    cx, cz, width, yaw = fp
    corners = footprint_corners(cx, cz, width, yaw)
    xs = [p[0] for p in corners]
    zs = [p[1] for p in corners]
    return (min(xs), min(zs), max(xs), max(zs))


def _union(boxes: Sequence[Tuple[float, float, float, float]]
           ) -> Tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _overlaps(a: Tuple[float, float, float, float],
              b: Tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _grown(box: Tuple[float, float, float, float],
           margin: float) -> Tuple[float, float, float, float]:
    return (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)


def level_plateaus(origin_x: float, origin_z: float, step: float,
                   heights: List[List[float]],
                   footprints: Sequence[Tuple[float, float, float, float]]
                   ) -> None:
    """Flatten the ground under every footprint GIVEN — IN PLACE (E8 task 4).

    ``footprints`` are the places that OPTED IN (``level_ground``, decision
    2026-08-13) — the caller filters, this pass levels. Such a location is a
    building site, not a tent: it is put ON the world, and the ground under it
    is levelled to carry it. Without the pass a place standing on a slope has
    its own floor cutting through the hill on one side and hovering over it on
    the other, and the walking rule (§ A15 no. 8) refuses every step across the
    seam. A location that did NOT ask for it accepts exactly that — the
    landscape runs through it, and keeping the place usable is an authoring
    matter.

    THE HEIGHT OF THE PLATEAU is the authored ground at the footprint's CENTRE,
    ``ground_y(pos_x, pos_z)`` — read from the raster BEFORE anything is
    levelled, which is why every ``h0`` below is sampled first and only then
    written. Sampling as we go would let the first plateau raise the ground the
    second one then reads, so two neighbouring places would answer differently
    depending on the order the DB returned them.

    THE PINNED REGION IS THE FOOTPRINT DILATED BY ONE CELL — the flat-hull
    pattern of the scene relief (``scatter_curves.terrain_grid``), for the same
    reason it exists there: with only the points INSIDE pinned, every border
    cell still interpolates the outside heights back IN, and the ground would
    rise through the floor of the place at its own edge. With the ring, every
    cell that touches the footprint has four pinned corners, the plateau is
    exactly flat across the whole place, and THE RAMP is the one cell between
    the ring and the untouched landscape.

    A ramp of one cell is what makes the plateau reachable at all: over 4 m a
    walker climbs ``tan(40°)·4 = 3.36 m`` at the default limit. A place whose
    centre sits more than that below or above the ground at its rim keeps a
    rim nobody can cross — legal and sometimes intended (a plateau entered
    through an opening, which the gate exempts), and the authoring warning in
    the height tool is about exactly this number. IT IS AN OPT-IN RIM: a
    location without ``level_ground`` builds no ramp at all, because it changes
    no height — there the authored slope simply continues under the place.

    OVERLAPS: THE SMALLEST FOOTPRINT WINS, the rule ``location_at_point`` and
    ``relief.ground_lift_at`` already resolve nesting by — the hut on the
    village square is the more specific answer about the square metre it
    stands on. It is implemented by levelling the widest first, so the
    narrowest writes last; equal widths keep the caller's (stable) order,
    where the later one wins.
    """
    rows = len(heights)
    cols = len(heights[0]) if rows else 0
    if rows < 2 or cols < 2 or step <= 0 or not footprints:
        return
    from app.core.world_geometry import footprint_distance
    field = {"origin_x": origin_x, "origin_z": origin_z, "step_m": step,
             "rows": rows, "cols": cols, "heights": heights}
    # Widest first — see the docstring: the last write wins, so the smallest
    # footprint has the final say. ``sorted`` is stable, so equal widths keep
    # the order they arrived in.
    ordered = sorted(footprints, key=lambda fp: -float(fp[2]))
    # EVERY plateau height first, from the untouched raster.
    levels = [sample_height(field, fp[0], fp[1]) for fp in ordered]
    for (cx, cz, width, yaw), h0 in zip(ordered, levels):
        # Index window: the whole rotated square (half-diagonal) plus the
        # dilation ring, so no pinned point is missed and none of the world
        # outside it is visited.
        reach = width * 0.7071067811865476 + step
        i0 = max(0, int(math.floor((cx - reach - origin_x) / step)))
        i1 = min(cols - 1, int(math.ceil((cx + reach - origin_x) / step)))
        j0 = max(0, int(math.floor((cz - reach - origin_z) / step)))
        j1 = min(rows - 1, int(math.ceil((cz + reach - origin_z) / step)))
        for j in range(j0, j1 + 1):
            pz = origin_z + j * step
            row = heights[j]
            for i in range(i0, i1 + 1):
                # ``footprint_distance`` is 0 anywhere INSIDE the square, so
                # this one test is "inside or within one cell of it" — the
                # exact distance to the rotated rectangle, not a bounding box.
                if footprint_distance(origin_x + i * step, pz,
                                      cx, cz, width, yaw) <= step + 1e-9:
                    row[i] = h0


def rasterize(areas: Sequence[Dict[str, Any]],
              step_m: float = 0.0,
              footprints: Sequence[Tuple[float, float, float, float]] = (),
              terrain_areas: Sequence[Dict[str, Any]] = (),
              terrain_catalog: Optional[Dict[str, Dict[str, Any]]] = None
              ) -> Dict[str, Any]:
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

    ``footprints`` are the LEVELLING locations ``(cx, cz, width_m, yaw_deg)`` —
    the ones whose ``level_ground`` flag is set, filtered by the caller
    (``models.heightfield.placed_footprints``); the PLATEAU PASS
    (:func:`level_plateaus`) runs over the finished area raster. An unflagged
    place is not in the list and therefore neither grows this grid nor changes
    a height in it: the landscape runs through it (decision 2026-08-13).
    A world without a single height area stays empty even with a hundred
    places on it: every plateau there would be levelled to 0 on ground that is
    already 0, and a grid of zeros is a payload nobody needs.

    ``terrain_areas`` + ``terrain_catalog`` are the painted ground and its type
    catalog, and they are here for the MICRO-RELIEF (decision 2026-08-13): a
    kind carrying ``relief_amplitude_m`` puts random small hills on every area
    painted with it (:func:`relief_inputs`, :func:`_apply_micro_relief`). They
    are handed IN rather than read, because this function stays pure — the
    caller (``get_field``) does the one DB read.

    A RELIEF KIND GROWS THE GRID like a height area does: the base box is the
    height areas UNION the areas whose kind carries relief. A world without a
    single height area but with bumpy grass painted on it gets its first grid
    that way, and the point budget behaves exactly as before.
    """
    from app.models.heightfield import polygon_bounds
    usable = [a for a in (areas or []) if len(a.get("polygon") or []) >= 3]
    boxes: List[Tuple[Dict[str, Any], Tuple[float, float, float, float]]] = []
    for area in usable:
        box = polygon_bounds(area.get("polygon"))
        if box is not None:
            boxes.append((area, box))
    relief = relief_inputs(terrain_areas, terrain_catalog)
    relief_boxes = [box for _a, params, box in relief if params is not None]
    if not boxes and not relief_boxes:
        return {"origin_x": 0.0, "origin_z": 0.0,
                "step_m": step_m or DEFAULT_STEP_M,
                "rows": 0, "cols": 0, "heights": []}

    area_bounds = _union([b[1] for b in boxes] + relief_boxes)
    # THE GRID HAS TO COVER WHAT IT DESCRIBES. A LEVELLING footprint reaching
    # out of the painted box is levelled too, so the grid grows to hold it
    # plus its ramp ring — otherwise the plateau would be cut off at the
    # border and the clamp outside the grid ("the flat world") would meet it
    # as a cliff.
    # Footprints that cannot touch any authored height are left out: outside
    # every polygon the ground is 0, levelling 0 onto 0 changes nothing, and a
    # single far-away hut must not stretch the grid across the world.
    fp_boxes = [_footprint_box(fp) for fp in (footprints or ())
                if fp and float(fp[2]) > 0]
    step = float(step_m) if step_m and step_m > 0 else _step_for(area_bounds)
    bounds = area_bounds
    # The ring margin depends on the step and the step on the bounds, so the
    # two are settled by iteration. The step only ever DOUBLES (`_step_for`)
    # and is capped, so this reaches a fixed point in a couple of rounds.
    for _round in range(6):
        relevant = [box for box in fp_boxes
                    if _overlaps(_grown(box, step), area_bounds)]
        bounds = _union([area_bounds] + [_grown(b, step) for b in relevant])
        nxt = float(step_m) if step_m and step_m > 0 else _step_for(bounds)
        if nxt == step:
            break
        step = nxt
    min_x, min_z, max_x, max_z = bounds
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
    # THEN the terrain's own small hills, ADDED onto that landscape — a
    # variation of it, not a competitor: run before the |max| rule they would
    # simply be overwritten by every authored area (which is exactly the red
    # counter-probe in the smoke).
    _apply_micro_relief(origin_x, origin_z, step, heights, relief)
    # …and only now the places standing on that landscape (E8 task 4).
    level_plateaus(origin_x, origin_z, step, heights,
                   [fp for fp in (footprints or ()) if fp and float(fp[2]) > 0])
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

    THE RASTER'S INPUTS ARE READ HERE, all four of them: the height areas, the
    levelling placements, and (since 2026-08-13) the painted terrain plus its
    type catalog, which carry the micro-relief. ``height_sig`` hashes exactly
    the same four, so "the world changed" and "this grid is stale" stay one
    question.

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
    from app.core.terrain_types import effective_catalog
    from app.models.terrain import list_areas
    field = rasterize(store.list_height_areas(),
                      footprints=store.placed_footprints(),
                      terrain_areas=list_areas(),
                      terrain_catalog=effective_catalog())
    field["sig"] = sig
    try:
        store.store_grid(field)
    except Exception as exc:   # a cache that cannot be written is not fatal
        logger.warning("Could not store the rastered heightfield: %s", exc)
    _CACHE = (generation, field)
    return field


def current_step_m() -> float:
    """The grid step the world's relief is rastered at right now, in metres.

    THE ONE SOURCE OF THAT NUMBER FOR THE EDITOR (finding 14, 2026-08-13). The
    step is not a setting: it is :func:`_step_for`'s answer to the UNION BOX of
    everything that shapes the ground, doubled until the grid fits inside
    :data:`MAX_POINTS`. So one hill painted 16 km out coarsens the relief of the
    whole world — a measured case forced 4 m to 32 m — and the micro-relief of
    a 22 m patch, whose swells are 8…12 m wide, loses every support point it
    had and simply disappears. Nothing on screen said so.

    The editor shows it and warns when a save moves it, and it asks HERE rather
    than reimplementing the doubling: a second opinion about the raster is how
    the warning starts naming a step the world does not have.

    It costs what :func:`get_field` costs — a dict lookup on a warm cache, the
    stored raster on a cold one. That is why it is asked on the editor's
    routes, which are already waiting for a round trip, and nowhere near a
    poll.
    """
    step = get_field().get("step_m")
    return float(step) if step else DEFAULT_STEP_M


def cached_sig() -> Optional[str]:
    """Signature of the field this process holds, or None when it holds none.

    The ONE cheap way to ask "is what I have still the world?": it costs a
    dict lookup, while the answer it is compared against (``height_sig``) costs
    a full read of the areas and the placed locations. That asymmetry is the
    point — the check runs on WRITE paths (a location moved, and a location
    write happens for every rename and every room edit too), where paying for
    the question once is cheap and re-rastering blindly is not.
    """
    cached = _CACHE
    if cached is None or cached[0] != _GENERATION:
        return None
    return cached[1].get("sig")


def current_sig() -> str:
    """The world relief's signature — out of the WARM CACHE where there is one.

    The same answer as ``models.heightfield.height_sig``, and that identity is
    the point: whenever this process holds the current field, the signature it
    was built from IS the current one — every writer of a height area and every
    writer of a placement drops the cache first (:func:`invalidate_cache` via
    ``_invalidate`` / ``note_world_write``), so a warm cache cannot hold a
    signature the world has moved past.

    THE READ PATH IS WHY IT EXISTS. ``build_worldmap_payload`` carries the
    signature on a 3-second poll, per client — and ``height_sig`` costs a full
    read of every area PLUS a full ``list_locations()`` PLUS an md5 (1.4 ms
    measured on the areas alone), for an answer that only changes when somebody
    edits the world. Here it is a dict lookup.

    A COLD cache falls back to the full computation and deliberately does NOT
    build the field: a poll is not the place to pay for a raster (0.39 s for a
    full-budget square, measured). Then it costs exactly what it always did.
    """
    cached = cached_sig()
    if cached is not None:
        return cached
    from app.models import heightfield as store
    return store.height_sig()


def world_height(x: float, z: float) -> float:
    """Height of the world ground at (x, z) — what ``ground_y`` answers."""
    return sample_height(get_field(), x, z)
