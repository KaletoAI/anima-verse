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

**h_final IS A PURE PER-POINT FUNCTION** (plan-ein-boden.md § G1, E1). Every
step of the bake is evaluated at ONE (x, z) with parameters measured in
METRES; not a single one measures in "grid cells". :class:`HeightModel` holds
the whole authored world and answers :meth:`HeightModel.final` for any real
point, and every raster in this module is nothing but that function sampled on
a lattice::

    areas (strongest deflection)      the authored height polygons, |max| rule
      → micro-relief (ADDITIVE)       the painted kinds' own small hills
      → STAMPS: water carve           every water polygon sinks its bed
      → STAMPS: location plateaus     every BUILT location stamps its plot

That is the whole point of the rewrite. The old bake had two steps that
measured in cells — the micro-relief's edge rule asked about the four GRID
NEIGHBOURS, the plateau ramp was ONE GRID CELL wide — so the same world came
out 2 m-ramped on a tile and 32 m-ramped on a coarsened overview: the
documented "two landscapes" bug (measured max 1.104 m apart at the same world
point). With every parameter in metres, ANY lattice — the 2 m tile, the
overview, any mip level — evaluates the same function and the answers agree at
shared lattice points BY CONSTRUCTION, not by luck.

**THE STAMPS.** Two of them, in this order:

* **Water carve** (§ A16.3): a painted area of a WATER kind carries a mirror
  PROFILE (:class:`WaterProfile`), a ``water_depth_m`` and a ``shore_ramp_m``.
  Inside the polygon the ground is pushed down to at most
  ``water_level_at(x, z) − depth_profile(d)``, where the depth profile
  smoothsteps from 0 at the rim to the full depth ``shore_ramp_m`` inside.
  Since W1 the mirror is LOCAL, and since W4a its axis is a POLYLINE: a lake is
  one knot and one constant (the lake of every round before), a river drawn with
  the line tool one knot per drawn point, and the level interpolates along that
  line — through every bend, not across the chord of it. The invariant
  that buys — deeper than the shore ramp the ground is at least ``ε`` below the
  mirror AT THAT POINT, in EVERY raster — is what makes "distant terrain pokes
  through the water" impossible in the data instead of impossible in a shader.
* **Location plateaus** (§ G5): every location that draws a BUILT floor
  stamps its plot flat. Not a flag any more —
  ``models.heightfield.placed_footprints`` hands out every location with a
  drawn building outline or a closed room, and nothing else. The target height
  is the MEDIAN of the natural heights under the footprint (robust: one spike
  under a corner no longer decides where the house stands), and the ramp is a
  smoothstep of ``w = clamp(0.5·√(area/π), 2, 8)`` metres OUTSIDE the outline,
  widened where the rim step would otherwise be steeper than 35°.

**THE RULES READ TILES, THE DISTANCE READS THE OVERVIEW** (v2, decision
2026-08-14). One grid for the whole world cannot be both: the point budget
(:data:`MAX_POINTS`) coarsens it as soon as somebody paints far out, and at a
32 m step the ground a walker is judged against would be a landscape nobody
authored. So there are two rasters of the same landscape:

* the OVERVIEW — :func:`rasterize` / :func:`get_field`, one grid over
  everything, coarsened when it must be. It is a PICTURE for the distant view
  and nothing else reads it any more.
* the TILES — :func:`rasterize_tile`, a 256 m square of the world at the
  always-fine :data:`TILE_STEP_M`, computed on demand and cached per
  process. :func:`world_height`, i.e. every rule that asks what the ground
  does, samples THOSE.

Since E1 the two are the same function at two densities, and the overview is
no longer "a slightly different landscape": at any step the coarse grid is a
SUBSAMPLE of the fine one, so every shared point carries the identical number.
A tile is only rastered where there is something to raster: :func:`tile_index`
lists the tiles any authored box reaches into, and a point outside every one of
them is the flat world, answered without touching a grid.

**THE PYRAMID** (§ G2): a tile also knows its own ``min``/``max`` and, per mip
level (4/8/16/32/64 m), the largest vertical error a renderer makes by drawing
that level instead of the 2 m base (:func:`tile_stats`). Because the mip
lattices are SUBSETS of the base lattice — purity again — the error needs no
second evaluation of anything; it is arithmetic on the tile that already
exists.
"""

import math
from collections import OrderedDict
from typing import (Any, Dict, List, NamedTuple, Optional, Sequence, Tuple)

from app.core.log import get_logger

logger = get_logger("heightfield")

#: Code version of the bake, mixed into ``models.heightfield.height_sig`` as
#: ``code_version``. Bump whenever the code that derives this payload changes
#: its output for unchanged data — a changed carve, ramp or relief rule leaves
#: every authored area untouched, so without this the signature stands still
#: and every client and every stored raster keeps the ground of the old code.
#: It lives HERE, next to the bake it describes, and not next to the signature
#: it feeds: whoever changes ``h_final`` is reading this file.
HEIGHT_BAKE_VERSION = 1

#: Distance between two support points, in metres. Four metres is the scale of
#: the thing being described: a hill is tens of metres wide, and a walker
#: crosses one cell in a bit over a second. It travels WITH the dataset (the
#: ``world_heightfield`` row) so a stored grid always says what it is, rather
#: than being read back against whatever the constant happens to be later.
DEFAULT_STEP_M = 4.0

#: Distance between two support points INSIDE A TILE, in metres — HALF the
#: overview's step (decision 2026-08-14). The tiles are the ground every rule
#: reads (:func:`world_height`), so this, not :data:`DEFAULT_STEP_M`, is the
#: finest the world ever gets and the Nyquist limit an authored relief wave is
#: clamped against (``terrain_types.RELIEF_WAVE_MIN`` = 2 × this). Two metres
#: is what makes a 4 m wave authorable at all: at a 4 m step the editor had to
#: clamp anything below 8 m away, and a meadow whose swells are a walker's
#: stride wide could not be described.
#:
#: THE OVERVIEW STAYS AT :data:`DEFAULT_STEP_M`. It is a picture for the
#: distance and nothing reads it any more, so quartering its payload would buy
#: nobody anything. The two lattices stay congruent because 4 is a multiple of
#: 2 — every overview support point IS a tile support point — but they are no
#: longer the same raster: the one-cell ramp of a plateau and the neighbour
#: test of the relief edge rule both measure in the step of the grid they run
#: on, so the two answers part company exactly there (§ A16.3).
TILE_STEP_M = 2.0

#: Support points a grid may have in total. Past this the raster is built at a
#: COARSER step (doubled until it fits) instead of being cut off: a world twice
#: as wide should get a coarser relief, not a relief that stops halfway. The
#: cap is a payload budget as much as a compute one — every client fetches the
#: whole grid.
MAX_POINTS = 120_000

#: How far the micro-relief's EDGE RULE looks for flat ground, in metres
#: (E1, plan-ein-boden.md § G1). The rule itself is unchanged (2026-08-13,
#: § A16.2): a dip is cut off where the relief-carrying region ends, so a bumpy
#: meadow may run OUT over its border but must never pull the flat neighbour
#: down with it. What changed is the ruler. It used to ask about the four GRID
#: neighbours, which is 2 m on a tile and up to 32 m on a coarsened overview —
#: two different rules, hence two different landscapes at the same world point.
#: Now it asks at a fixed METRE offset and every raster gets the same answer.
#: The value is :data:`TILE_STEP_M`, so the tiles — the ground every rule reads
#: — keep exactly the heights they had.
RELIEF_EDGE_PROBE_M = 2.0

#: The plateau ramp of a built location, in metres (§ G5). Width is
#: :data:`PLATEAU_RAMP_FACTOR` · √(area/π) — half the radius of the circle of
#: the same area, i.e. a big plot gets a long ramp and a hut a short one —
#: clamped into [2, 8]. Below 2 m a ramp is not a ramp but the cliff the old
#: one-cell ring built; past 8 m it starts eating the landscape around the
#: place. It is measured OUTSIDE the outline, so the plot itself is exactly
#: flat right up to its own edge.
PLATEAU_RAMP_FACTOR = 0.5
PLATEAU_RAMP_MIN_M = 2.0
PLATEAU_RAMP_MAX_M = 8.0

#: Steepest a plateau ramp may be AT ITS STEEPEST METRE, in degrees. Where the
#: ramp would exceed it the width is WIDENED until it does not — a place on a
#: hillside gets a long ramp rather than a wall nobody can walk up.
#:
#: A smoothstep peaks at 1.5× its own mean gradient, so the widening carries
#: that factor (:data:`SMOOTHSTEP_PEAK`): ``w ≥ 1.5·Δ/tan(35°)``. Capping the
#: MEAN instead (the first cut of this wave) left a steepest metre of
#: atan(1.5·tan 35°) = 46.4° — above the walking gate's 40°, so the ramp of a
#: hillside plot was still unwalkable at its steepest point. With the peak
#: capped at 35° every plateau rim is walkable by construction
#: (measured in ``scripts/smoke_slope_gate.py``).
PLATEAU_MAX_SLOPE_DEG = 35.0

#: Peak-to-mean gradient ratio of the smoothstep ramp (max of 6t(1−t) is 1.5).
SMOOTHSTEP_PEAK = 1.5

#: The water stamp's defaults and clamps, in metres (§ G4). ``water_depth_m``
#: is how far the bed lies under the mirror once the shore ramp is done;
#: ``shore_ramp_m`` is how far inside the rim that full depth is reached (0 =
#: a step, legal for a basin). The lower depth clamp is what still reads as
#: water rather than as a wet floor; the upper one is a lake, not an ocean
#: trench.
WATER_DEPTH_DEFAULT_M = 2.0
WATER_DEPTH_MIN_M = 0.2
WATER_DEPTH_MAX_M = 20.0
WATER_SHORE_RAMP_DEFAULT_M = 3.0
WATER_SHORE_RAMP_MIN_M = 0.0
WATER_SHORE_RAMP_MAX_M = 20.0

#: The mip levels a tile reports an error bound for, in metres (§ G2). Each is
#: a multiple of :data:`TILE_STEP_M` AND divides the tile edge, so the coarse
#: lattice is a SUBSET of the base lattice and the pyramid needs no second
#: evaluation of the height function.
MIP_LEVELS_M = (4.0, 8.0, 16.0, 32.0, 64.0)


# ── Sampling ────────────────────────────────────────────────────────────

def sample_height(field: Optional[Dict[str, Any]], x: float, z: float) -> float:
    """Height of the world ground at (x, z) in metres — bilinear.

    ``field`` is the payload shape: ``origin_x``/``origin_z`` (world metres of
    ``heights[0][0]``), ``step_m``, ``rows``/``cols`` and ``heights[j][i]``,
    the height at ``(origin_x + i·step, origin_z + j·step)``.

    Grid fraction, then cell and mix — the very formula every renderer samples
    the ground with (``@anima/scene-render`` ``sampleWorldHeight``)::

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

def edge_distance(px: float, pz: float,
                  ring: Sequence[Sequence[float]]) -> float:
    """Shortest distance from (x, z) to the OUTLINE of a polygon, metres.

    The outline, not the interior: a point deep inside a large area is far from
    every edge, which is exactly what the ramp needs to know. Auto-closed, like
    every polygon in this world.
    """
    parsed = _ring(ring)
    if parsed is None:
        return 0.0
    return _ring_edge_distance(px, pz, parsed)


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
    ring = _ring(area.get("polygon"))
    if ring is None:
        return None
    return _area_value(ring, float(area.get("height_m") or 0.0),
                       float(area.get("falloff_m") or 0.0), x, z)


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
    Nyquist limit of the raster the RULES read (2 × :data:`TILE_STEP_M`), and a
    field that cannot carry its own wave would alias differently at every step
    size.
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

    THE FORMULA OF THE OLD SCENE RELIEF, deliberately unchanged (its two
    spatial-hash primes are imported from ``scatter_curves`` rather than
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
    on the tile grid the amplitude clamp therefore allows atan(2·2.0/2.0) = 63°
    where it allowed 45° at the old 4 m step (2026-08-14). It is a theoretical
    worst case: it needs two adjacent noise corners at the full ±1, which the
    lattice hands out for one pair of corners in a very long while.
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


#: A levelling footprint as the raster receives it (contract v6 no. 7):
#: the anchor pin, its yaw, and the boundary polygon in LOCAL metres —
#: exactly what ``models.heightfield.placed_footprints`` hands out.
Footprint = Tuple[float, float, float, List[Tuple[float, float]]]


def _footprint_box(fp: Footprint
                   ) -> Optional[Tuple[float, float, float, float]]:
    """Axis-aligned WORLD box around a polygon footprint, or None for junk.

    The v6 successor of the half-diagonal box around a rotated square: the
    outline goes through the ONE § A1.1 transform and the bounds are taken of
    the world points. None means "this footprint describes no surface" — fewer
    than three readable points — and every caller drops it, so a malformed
    outline can neither grow a grid nor index a tile.
    """
    from app.core.world_geometry import polygon_bounds, polygon_local_to_world
    try:
        cx, cz, yaw, points = fp
    except (TypeError, ValueError):
        return None
    world = polygon_local_to_world(points, float(cx), float(cz), float(yaw))
    if world is None:
        return None
    return polygon_bounds(world)


def _boxed_footprints(footprints: Sequence[Footprint]
                      ) -> List[Tuple[Footprint,
                                      Tuple[float, float, float, float]]]:
    """The footprints that describe a surface, each with its world box.

    ONE place decides what "usable" means, so the grid growth, the tile index
    and the plateau pass cannot disagree about which places level.
    """
    out: List[Tuple[Footprint, Tuple[float, float, float, float]]] = []
    for fp in (footprints or ()):
        if not fp:
            continue
        box = _footprint_box(fp)
        if box is not None:
            out.append((fp, box))
    return out


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


# ── The authored inputs ─────────────────────────────────────────────────

#: A height area together with its bounding box, the form every pass wants.
AreaBox = Tuple[Dict[str, Any], Tuple[float, float, float, float]]

#: One entry of the micro-relief input list: the painted area, its kind's
#: ``(seed, amplitude, wave)`` — or None for a FLAT kind lying over a bumpy one
#: — and its bounding box.
ReliefEntry = Tuple[Dict[str, Any], Optional[Tuple[int, float, float]],
                    Tuple[float, float, float, float]]


def area_boxes(areas: Sequence[Dict[str, Any]]) -> List[AreaBox]:
    """The usable height areas with their boxes, in the order given.

    A polygon of fewer than three points describes no surface and an outline
    whose vertices are all unreadable has no box — both are dropped HERE, once,
    so every consumer downstream (the model, the tile index) works off the same
    list and cannot disagree about what is authored.
    """
    from app.models.heightfield import polygon_bounds
    out: List[AreaBox] = []
    for area in (areas or []):
        if len(area.get("polygon") or []) < 3:
            continue
        box = polygon_bounds(area.get("polygon"))
        if box is not None:
            out.append((area, box))
    return out


# ── The pure height function ────────────────────────────────────────────

def smoothstep(t: float) -> float:
    """The classic ``t²·(3 − 2t)`` on [0, 1], clamped outside it.

    THE ONE RAMP SHAPE of this module (§ G1): both stamps blend with it, so a
    shore and a plot rim are the same curve at two widths. It is flat at both
    ends (its derivative is 0 at 0 and at 1), which is what makes a ramp meet
    the landscape without a crease — a linear ramp leaves a visible kink at
    each end, and the kink is exactly where a walking gate measures.
    """
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


#: The one empty list :meth:`_BoxIndex.at` hands out — allocating a fresh one
#: per point is measurable on a 129² tile.
_EMPTY: List[int] = []


class _BoxIndex:
    """Which items of a list can possibly cover a point — a bucket grid.

    THE PER-POINT COST IS THE WHOLE REASON IT EXISTS. The old bake walked each
    area over its OWN index window, which is cheap but only possible for a
    raster; a pure per-point function has to turn the loop around and ask "who
    covers this point", and doing that against every area would be
    ``points × areas`` — seconds for a full-budget overview.

    Items are bucketed by their bounding box on a fixed 64 m lattice anchored
    at the world origin. An item whose box covers absurdly many buckets (a
    single area painted across the whole world) is not bucketed at all but kept
    in :attr:`_everywhere`, which is answered for every query — a bucket list
    the size of the world would cost more to build than it saves.

    :meth:`at` answers INDICES IN THE ORIGINAL ORDER, always: every rule that
    reads this list (the |max| tie-break, "the last painted kind wins", the
    plateau overlap order) is order-dependent, and an index that arrives in
    bucket order would decide those differently from one query to the next.
    """

    CELL_M = 64.0
    MAX_CELLS = 4096

    def __init__(self, boxes: Sequence[Tuple[float, float, float, float]]):
        self._cells: Dict[Tuple[int, int], List[int]] = {}
        self._everywhere: List[int] = []
        cell = self.CELL_M
        for idx, box in enumerate(boxes):
            i0 = int(math.floor(box[0] / cell))
            i1 = int(math.floor(box[2] / cell))
            j0 = int(math.floor(box[1] / cell))
            j1 = int(math.floor(box[3] / cell))
            if (i1 - i0 + 1) * (j1 - j0 + 1) > self.MAX_CELLS:
                self._everywhere.append(idx)
                continue
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    self._cells.setdefault((i, j), []).append(idx)
        # Two shapes answer without a lookup at all: an empty index, and one
        # whose every item is "everywhere". Both are common (a world without
        # water, a single painted meadow over the whole map) and both sit on
        # the per-point path.
        self._trivial: Optional[List[int]] = (
            self._everywhere if not self._cells else None)

    def at(self, x: float, z: float) -> List[int]:
        if self._trivial is not None:
            return self._trivial
        cell = self.CELL_M
        hit = self._cells.get((int(x // cell), int(z // cell)))
        if not self._everywhere:
            return hit or _EMPTY
        if not hit:
            return self._everywhere
        return sorted(hit + self._everywhere)


def _rim_samples(ring: Sequence[Sequence[float]], spacing: float = 2.0,
                 cap: int = 512) -> List[Tuple[float, float]]:
    """Points ALONG a polygon outline, at most ``spacing`` metres apart.

    Both stamps need to know what the landscape does at the RIM of a shape —
    the water level defaults to the median height there, the plateau ramp is
    widened by the biggest step there. Sampling the outline rather than the
    vertices matters for exactly the shapes that hurt: a lake drawn with four
    corners has its interesting heights in the middle of its edges.

    The cap keeps an outline around a kilometre-wide area from turning into a
    hundred thousand height evaluations; past it the spacing simply grows. It
    is a cap on the SPACING, not on the count: every edge contributes at least
    one sample, so a ring with more vertices than the cap answers one per
    vertex — which is the ceiling the sanitizer sets (2050, and 670 for the
    kilometre of `wavy` river that made it that high). Degenerate rings (fewer
    than three points) answer empty.
    """
    pts: List[Tuple[float, float]] = []
    n = len(ring)
    if n < 3 or spacing <= 0:
        return pts
    perimeter = 0.0
    for k in range(n):
        ax, az = float(ring[k][0]), float(ring[k][1])
        bx, bz = float(ring[(k + 1) % n][0]), float(ring[(k + 1) % n][1])
        perimeter += math.hypot(bx - ax, bz - az)
    if perimeter > 0 and perimeter / spacing > cap:
        spacing = perimeter / cap
    for k in range(n):
        ax, az = float(ring[k][0]), float(ring[k][1])
        bx, bz = float(ring[(k + 1) % n][0]), float(ring[(k + 1) % n][1])
        length = math.hypot(bx - ax, bz - az)
        steps = max(1, int(math.ceil(length / spacing)))
        for s in range(steps):
            t = s / steps
            pts.append((ax + (bx - ax) * t, az + (bz - az) * t))
    return pts


def _median(values: Sequence[float]) -> float:
    """The middle value; the mean of the two middle ones for an even count.

    THE ROBUST ANSWER, which is why both stamps use it and neither uses a mean
    or a single probe (§ G5): one spike of micro-relief under a corner of a
    house must not decide where the house stands, and with a median it cannot —
    it would have to move half the ground under the plot to move the plateau by
    a centimetre.
    """
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) * 0.5


#: One knot of a flow axis: ``(x, z, s, level)`` — the world position, the arc
#: coordinate measured from the FIRST knot and the mirror height there.
WaterKnot = Tuple[float, float, float, float]


class WaterProfile(NamedTuple):
    """THE MIRROR OF ONE WATER AREA AS A FUNCTION OF THE PLACE (W1/W4a, § A16.3).

    A lake is one number; a river is a surface that follows its own drawn line.
    Both are this: a POLYLINE OF KNOTS, each carrying a level, interpolated
    along the line. A lake is that polyline with ONE knot, a straight river the
    one with two — the old laws are degenerate cases of the new one, not
    branches beside it.

    * ``axis`` — the knots ``(x, z, s, level)`` in FLOW order (§ A16.3, W4a):
      ``s`` is the arc length from the first knot, ``level`` the world y there.
      ONE knot means still water and ``s`` is 0; two or more mean the water
      flows from ``axis[0]`` toward ``axis[-1]``. It is never empty, which is
      what lets :func:`water_level_at` be one straight-line expression.

    The nine numbers below are the same mirror as ONE TILTED PLANE — what a
    reader that never heard of the polyline gets, and for a two-knot axis the
    whole truth:

    * ``level_up`` / ``level_down`` — the levels of the FIRST and the LAST knot.
    * ``flow_dir_deg`` — the downstream bearing, ``None`` for still water: the
      authored one for polygon water, and for a drawn line the bearing of the
      chord FIRST → LAST knot (the best single plane through a meander). It is
      spelled like every other yaw in this contract (§ A1.1):
      ``dir = (sin θ, cos θ)``, so 0° flows toward +z, 90° toward +x.
    * ``axis_x`` / ``axis_z`` — the point that plane's axis runs through: the
      polygon's area centroid for polygon water, the first knot for a line.
    * ``dir_x`` / ``dir_z`` — that unit direction, (0, 0) for still water.
    * ``s_min`` / ``s_max`` — the axis coordinates of the upstream and the
      downstream extreme along it.

    IT IS THE WHOLE PAYLOAD TOO. ``GET /world/terrain-areas`` and
    ``GET /play/terrain`` ship the nine numbers AND the knots as
    ``meta.water_profile``, so a client evaluates :func:`water_level_at` itself
    and the server never has to rasterise a mirror.
    """
    level_up: float
    level_down: float
    flow_dir_deg: Optional[float]
    axis_x: float
    axis_z: float
    dir_x: float
    dir_z: float
    s_min: float
    s_max: float
    axis: Tuple[WaterKnot, ...]


def _axis_s_at(axis: Tuple[WaterKnot, ...], x: float, z: float) -> float:
    """The arc coordinate of the point on ``axis`` NEAREST to ``(x, z)``.

    Every segment is projected onto with a clamp to its own ends, and the
    shortest distance wins; the answer is that segment's ``s`` interpolated by
    the projection. The candidate the loop starts from is the FIRST KNOT, which
    is the whole answer for a one-knot (still) axis and is dominated by the
    first segment for every longer one.
    """
    best_x, best_z, best_s, _ = axis[0]
    best_d2 = (x - best_x) * (x - best_x) + (z - best_z) * (z - best_z)
    i = 1
    while i < len(axis):
        ax, az, a_s, _ = axis[i - 1]
        bx, bz, b_s, _ = axis[i]
        dx, dz = bx - ax, bz - az
        seg = dx * dx + dz * dz
        u = 0.0 if seg <= 1e-18 else ((x - ax) * dx + (z - az) * dz) / seg
        u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
        px, pz = ax + dx * u, az + dz * u
        d2 = (x - px) * (x - px) + (z - pz) * (z - pz)
        if d2 < best_d2:
            best_d2 = d2
            best_s = a_s + (b_s - a_s) * u
        i += 1
    return best_s


def _axis_level_at(axis: Tuple[WaterKnot, ...], s: float) -> float:
    """The level of ``axis`` at arc coordinate ``s``, linear between the knots.

    CLAMPED AT BOTH ENDS, and that matters: the knots sit where the levels were
    measured, and a point past the last one must not read past the level that
    measurement stands for. A one-knot axis answers its own level here, because
    its ``s`` is both the first and the last.
    """
    if s <= axis[0][2]:
        return axis[0][3]
    if s >= axis[-1][2]:
        return axis[-1][3]
    i = 1
    while i < len(axis):
        a_s, a_level = axis[i - 1][2], axis[i - 1][3]
        b_s, b_level = axis[i][2], axis[i][3]
        if s <= b_s:
            span = b_s - a_s
            if span <= 1e-12:
                return b_level
            return a_level + (b_level - a_level) * ((s - a_s) / span)
        i += 1
    return axis[-1][3]


def water_level_at(profile: WaterProfile, x: float, z: float) -> float:
    """The mirror of ``profile`` AT ONE POINT — a pure function, no state.

    THE AXIS IS A POLYLINE (W4a), and the rule is the same three lines it was
    when it was a straight one::

        s     = arc coordinate of the NEAREST point on the polyline
                (each segment projected with a clamp, shortest distance wins)
        level = linear between the two knots s falls between, clamped at
                both ends of the line

    A MEANDER IS THE REASON: projecting a 180° loop onto one straight axis puts
    its two ends at the same axis point, so the mirror of a bend could not fall
    at all. Along its OWN line it always can.

    BOTH OLD LAWS FALL OUT OF IT, no branch beside them: still water is ONE
    knot, so the nearest point is that knot and the clamp answers its level
    everywhere; a straight river is TWO knots at the axis extremes, so the
    projection onto the single segment is exactly the ``(s − s_min)/span`` of
    W1, clamp included.
    """
    return _axis_level_at(profile.axis, _axis_s_at(profile.axis, x, z))


def flow_direction(flow_dir_deg: Optional[float]) -> Tuple[float, float]:
    """The DOWNSTREAM unit vector of a flow bearing — ``(sin θ, cos θ)``.

    THE SAME MAPPING EVERY OTHER YAW IN THIS CONTRACT USES: it is
    ``world_geometry.local_to_world(0, 1, 0, 0, θ)``, i.e. the local +z axis
    turned by θ, which is what a marker's ``facing`` and a prop's ``yaw`` mean.
    A river with ``flow_dir_deg`` 90 flows toward +x, and the client that
    scrolls its ripples along the same bearing gets the same arrow.

    The components are rounded to twelve decimals so the cardinal directions are
    EXACTLY (0, ±1) / (±1, 0): ``cos(270°)`` is −1.8e−16 in binary floating
    point, and a mirror that tilted by a femtometre across a river's width would
    make two lattices disagree in the last bit for no reason at all.
    """
    if flow_dir_deg is None:
        return (0.0, 0.0)
    rad = math.radians(float(flow_dir_deg))
    # ``0.0 if v == 0`` and not ``+ 0.0``: rounding ``cos(270°)`` gives NEGATIVE
    # zero, which is equal to zero everywhere except in the JSON it would be
    # written as.
    return tuple(0.0 if v == 0 else v                     # type: ignore[return-value]
                 for v in (round(math.sin(rad), 12), round(math.cos(rad), 12)))


def sanitize_flow_dir(raw: Any) -> Optional[float]:
    """One authored flow bearing, 0…360 — or None for "still".

    WRAPPED, NOT CLAMPED: a bearing is an angle, so 370° is 10° and −90° is
    270°; clamping would turn a slip of the wrist into a river flowing the wrong
    way along the axis. Junk, an empty string and a non-finite number all answer
    None, which is the shape of "no flow" everywhere: no key, no tilt, one
    level.
    """
    if raw is None or f"{raw}".strip() == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return round(value % 360.0, 3)


#: One water stamp: the polygon in WORLD metres, its box, the mirror PROFILE,
#: the depth under it and the width of the shore ramp — all in metres.
WaterStamp = Tuple[List[List[float]], Tuple[float, float, float, float],
                   WaterProfile, float, float]

#: One plateau stamp: pin x/z, yaw, the outline in LOCAL metres, its world box,
#: the target height and the ramp width in metres.
PlateauStamp = Tuple[float, float, float, List[Tuple[float, float]],
                     Tuple[float, float, float, float], float, float]


#: The two directions a drawn line may be flowed along — and ``None``, which is
#: "still". ``forward`` is the drawing order of ``meta.stroke.points``.
FLOW_ALONG_VALUES = ("forward", "reverse")

#: How many probes one cross-section of a drawn river takes for its knot level
#: (§ A16.3, W4a). ODD, so the median is a probe and not a mean of two, and
#: small: the section is a handful of metres wide and the median only has to
#: outvote the micro-relief.
WATER_AXIS_CROSS_SAMPLES = 9


class WaterMeta(NamedTuple):
    """Everything ONE painted water area authors about its own water.

    The reader's half of ``models.terrain._sanitize_water``. The MIRROR fields
    are optional — absent means "derive it from the rim" — while the two shape
    widths always answer a number, because the KIND answers when the area does
    not (``terrain_types.water_kind_defaults``).

    ``flow_along`` and the two ``stroke_*`` fields are the DRAWN LINE (W4a):
    the centre line the line tool already stores in ``meta.stroke`` becomes the
    flow axis when the author flows the area along it. They are read here, and
    not from the polygon, because the polygon is the ribbon AROUND the line and
    has no direction of its own.
    """
    level: Optional[float]
    level_up: Optional[float]
    level_down: Optional[float]
    depth_m: float
    shore_ramp_m: float
    flow_dir_deg: Optional[float]
    bed_kind: str
    flow_along: Optional[str]
    stroke_points: Tuple[Tuple[float, float], ...]
    stroke_width_m: float


def is_flowing(meta: WaterMeta) -> bool:
    """Does this area's mirror TILT at all? — the one predicate, once (W4a).

    A drawn line wins over a bearing: an area that carries both is a river
    somebody drew, and ``flow_dir_deg`` would be the straight axis its own line
    replaced. Without a usable line the bearing still answers, which is polygon
    water and every river painted before W4a.
    """
    if meta.flow_along in FLOW_ALONG_VALUES and len(meta.stroke_points) >= 2:
        return True
    return meta.flow_dir_deg is not None


def water_meta(area: Dict[str, Any],
               defaults: Optional[Tuple[float, float]] = None) -> WaterMeta:
    """What one painted water area says about its water (§ A16.3, W1).

    THE MIRROR IS THE AREA'S ALONE — two lakes in one world stand at two
    heights, and no kind can answer that. THE TWO WIDTHS ARE THE KIND'S UNLESS
    THE AREA OVERRIDES THEM: ``defaults`` is ``(depth_m, shore_ramp_m)`` out of
    ``terrain_types.water_kind_defaults``, and a key present on the area wins
    over it. Without ``defaults`` the module constants stand in, which is what
    every caller got before the kind had an opinion.

    ``water_level`` sets BOTH ends of the profile (a still lake); the two end
    fields override their own end, so a river may be authored at one end and
    derived at the other. A missing or unreadable number answers None and the
    model derives it (the rim median of § A16.3, per third along the axis where
    there is a flow direction).
    """
    meta = area.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    default_depth, default_ramp = (defaults if defaults is not None
                                   else (WATER_DEPTH_DEFAULT_M,
                                         WATER_SHORE_RAMP_DEFAULT_M))

    def _level(key: str) -> Optional[float]:
        try:
            value = float(meta[key])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        return value if math.isfinite(value) else None

    def _width(key: str, fallback: float, low: float, high: float) -> float:
        if key not in meta:
            return min(max(fallback, low), high)
        try:
            value = float(meta[key])
        except (TypeError, ValueError, OverflowError):
            value = fallback
        if not math.isfinite(value):
            value = fallback
        return min(max(value, low), high)

    along = str(meta.get("flow_along") or "").strip().lower()
    points, width = _stroke_line(meta.get("stroke"))
    return WaterMeta(
        level=_level("water_level"),
        level_up=_level("water_level_up"),
        level_down=_level("water_level_down"),
        depth_m=_width("water_depth_m", default_depth,
                       WATER_DEPTH_MIN_M, WATER_DEPTH_MAX_M),
        shore_ramp_m=_width("shore_ramp_m", default_ramp,
                            WATER_SHORE_RAMP_MIN_M, WATER_SHORE_RAMP_MAX_M),
        flow_dir_deg=sanitize_flow_dir(meta.get("flow_dir_deg")),
        bed_kind=str(meta.get("bed_kind") or "").strip(),
        flow_along=along if along in FLOW_ALONG_VALUES else None,
        stroke_points=points,
        stroke_width_m=width,
    )


def _stroke_line(raw: Any) -> Tuple[Tuple[Tuple[float, float], ...], float]:
    """The centre line of ``meta.stroke`` — points and ribbon width, or empty.

    The recipe is whitelisted on the way in (``models.terrain._sanitize_stroke``),
    so this only has to survive a hand-written fixture and an area drawn as a
    polygon: anything that is not a readable line answers ``((), 0.0)`` and the
    area is polygon water.
    """
    if not isinstance(raw, dict):
        return ((), 0.0)
    points: List[Tuple[float, float]] = []
    for point in (raw.get("points") or []):
        try:
            px, pz = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            return ((), 0.0)
        if not (math.isfinite(px) and math.isfinite(pz)):
            return ((), 0.0)
        points.append((px, pz))
    try:
        width = float(raw.get("width_m"))
    except (TypeError, ValueError, OverflowError):
        width = 0.0
    if not math.isfinite(width) or width < 0.0:
        width = 0.0
    return (tuple(points), width)


def _stroke_knots(meta: WaterMeta) -> List[Tuple[float, float, float]]:
    """The drawn line as ``(x, z, s)`` knots IN FLOW ORDER (W4a).

    ``forward`` is the order the author clicked the points in, ``reverse`` the
    other way round; ``s`` is the arc length from the first knot of that order.
    Repeated points are dropped: a double click leaves a zero-length segment,
    which has no tangent and no share of the arc, and every rule downstream
    would have to ask about it.
    """
    points = list(meta.stroke_points)
    if meta.flow_along == "reverse":
        points.reverse()
    knots: List[Tuple[float, float, float]] = []
    total = 0.0
    for px, pz in points:
        if knots:
            step = math.hypot(px - knots[-1][0], pz - knots[-1][1])
            if step <= 1e-9:
                continue
            total += step
        knots.append((px, pz, total))
    return knots


def _knot_tangent(knots: List[Tuple[float, float, float]],
                  i: int) -> Tuple[float, float]:
    """The unit flow direction AT one knot — the local tangent of the line.

    An inner knot uses the chord of its two NEIGHBOURS, so the cross section of
    a bend is cut across the bend and not across one of its two legs; the ends
    use their own single segment. A knot whose neighbours coincide (a hairpin
    that turns back on itself) has no chord and falls back to the segment
    leading INTO it, which is the direction the water arrives from.
    """
    last = len(knots) - 1
    if i <= 0:
        pairs = ((0, 1),)
    elif i >= last:
        pairs = ((last - 1, last),)
    else:
        pairs = ((i - 1, i + 1), (i - 1, i), (i, i + 1))
    for a, b in pairs:
        dx = knots[b][0] - knots[a][0]
        dz = knots[b][1] - knots[a][1]
        length = math.hypot(dx, dz)
        if length > 1e-9:
            return (dx / length, dz / length)
    return (0.0, 1.0)


def _authored_axis_levels(levels: List[float], arc: List[float],
                          meta: WaterMeta) -> List[float]:
    """The derived knot levels with the AUTHORED ends imposed (W4a).

    ``water_level`` flattens the whole line to one number. Otherwise each end
    the author named replaces its knot and the rest is remapped affinely into
    the resulting span — same shape, authored ends. A derived shape that is
    already flat has nothing to keep, so it becomes a straight ramp along the
    arc length instead of a division by zero.
    """
    if meta.level is not None:
        return [float(meta.level)] * len(levels)
    if meta.level_up is None and meta.level_down is None:
        return levels
    first, last = levels[0], levels[-1]
    up = float(meta.level_up) if meta.level_up is not None else first
    down = float(meta.level_down) if meta.level_down is not None else last
    span = first - last
    if abs(span) > 1e-9:
        scale = (up - down) / span
        return [down + (value - last) * scale for value in levels]
    total = arc[-1] - arc[0]
    if total <= 1e-9:
        return [up] * len(levels)
    return [up + (down - up) * ((s - arc[0]) / total) for s in arc]


def water_areas(terrain_areas: Sequence[Dict[str, Any]],
                catalog: Optional[Dict[str, Dict[str, Any]]]
                ) -> List[Tuple[Dict[str, Any],
                                Tuple[float, float, float, float]]]:
    """The painted areas that CARVE — every usable polygon of a water kind.

    "Water kind" is a property of the CATALOG, never of the name (§ G4):
    ``terrain_types.is_water_kind`` reads the entry's own ``meta.water`` flag,
    so a world may call its lakes whatever it likes and a world that carves
    nothing simply flags nothing. An unknown kind is not water.
    """
    from app.core.terrain_types import is_water_kind
    from app.models.heightfield import polygon_bounds
    catalog = catalog or {}
    out: List[Tuple[Dict[str, Any],
                    Tuple[float, float, float, float]]] = []
    for area in (terrain_areas or []):
        if len(area.get("polygon") or []) < 3:
            continue
        if not is_water_kind(str(area.get("kind") or ""), catalog):
            continue
        box = polygon_bounds(area.get("polygon"))
        if box is not None:
            out.append((area, box))
    return out


def _ring(points: Any) -> Optional[List[Tuple[float, float]]]:
    """A polygon parsed ONCE into float pairs, or None when it is not one.

    The whole per-point cost of the bake used to sit in the fact that
    ``world_geometry.point_in_polygon`` and ``polygon_distance`` re-parse their
    outline on EVERY call — which a raster does hundreds of thousands of times
    per tile. The model parses each ring once at construction and the two
    primitives below work on the result. They are the same rules, spelled the
    same way; the smoke runs measure them against the shared functions.
    """
    out: List[Tuple[float, float]] = []
    for pt in (points or []):
        try:
            out.append((float(pt[0]), float(pt[1])))
        except (TypeError, ValueError, IndexError):
            return None
    return out if len(out) >= 3 else None


def _area_value(ring: List[Tuple[float, float]], height: float,
                falloff: float, x: float, z: float) -> Optional[float]:
    """THE height-area rule, expressed ONCE, on a parsed ring.

    ``None`` when the point is not inside the outline. Both readers go through
    here — :func:`area_height_at` (the documented single-area primitive, used
    by the smoke runs) and :meth:`HeightModel.natural` (which pre-parses its
    rings at construction) — so there is no second opinion about what one
    painted height does to a point.
    """
    if not _inside_ring(x, z, ring):
        return None
    if falloff <= 0:
        return height
    return height * min(1.0, _ring_edge_distance(x, z, ring) / falloff)


def _inside_ring(x: float, z: float, ring: List[Tuple[float, float]]) -> bool:
    """``world_geometry.point_in_polygon`` on a PARSED ring — ray casting."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, zi = ring[i]
        xj, zj = ring[j]
        if (zi > z) != (zj > z):
            if x < (xj - xi) * (z - zi) / (zj - zi) + xi:
                inside = not inside
        j = i
    return inside


def _ring_edge_distance(x: float, z: float,
                        ring: List[Tuple[float, float]]) -> float:
    """:func:`edge_distance` on a PARSED ring — distance to the OUTLINE."""
    best = math.inf
    j = len(ring) - 1
    for i in range(len(ring)):
        ax, az = ring[j]
        bx, bz = ring[i]
        dx, dz = bx - ax, bz - az
        len2 = dx * dx + dz * dz
        if len2 < 1e-18:
            d = math.hypot(x - ax, z - az)
        else:
            t = ((x - ax) * dx + (z - az) * dz) / len2
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            d = math.hypot(x - (ax + t * dx), z - (az + t * dz))
        if d < best:
            best = d
        j = i
    return best


def _ring_centroid(ring: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """The AREA centroid of a parsed ring — the point a flow axis runs through.

    The signed-area formula, not the mean of the vertices: a river drawn with
    twenty points along one bank and two along the other would otherwise have
    its axis dragged onto the detailed bank. A degenerate ring (zero area, all
    points on a line) has no area centroid, so there the vertex mean is the
    honest answer — and it only ever decides where the axis is ANCHORED, never
    how steeply the mirror tilts (that is ``s_min``/``s_max``, which are
    measured from the anchor and cancel it out).
    """
    if not ring:
        return (0.0, 0.0)
    twice_area = 0.0
    cx = 0.0
    cz = 0.0
    n = len(ring)
    for i in range(n):
        ax, az = ring[i]
        bx, bz = ring[(i + 1) % n]
        cross = ax * bz - bx * az
        twice_area += cross
        cx += (ax + bx) * cross
        cz += (az + bz) * cross
    if abs(twice_area) < 1e-12:
        return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    return (cx / (3.0 * twice_area), cz / (3.0 * twice_area))


def _ring_distance(x: float, z: float,
                   ring: List[Tuple[float, float]]) -> float:
    """``world_geometry.polygon_distance`` on a PARSED ring — 0 inside."""
    if _inside_ring(x, z, ring):
        return 0.0
    return _ring_edge_distance(x, z, ring)


class HeightModel:
    """The whole authored world as ONE pure function of (x, z) — ``h_final``.

    Build it from the four raster inputs plus the placed footprints and ask
    :meth:`final`. Everything in this module that produces a grid — the
    overview, a tile, a mip level — is this function sampled on a lattice, and
    that identity is the contract E1 exists to establish (§ G1): two lattices
    over the same model carry the same number at every shared point, by
    construction rather than by agreement.

    CONSTRUCTION IS IN THREE STAGES, and the order is the pipeline order:

    1. the areas and the micro-relief, which are pure inputs;
    2. the WATER stamps, whose default mirror height is the median of
       :meth:`natural` along the rim — read from the landscape BEFORE any
       stamp, so a lake does not sink itself;
    3. the PLATEAU stamps, whose target height is the median of
       :meth:`natural` under the footprint and whose ramp width is widened
       against the rim step — again read from the landscape before any stamp,
       so two neighbouring places cannot answer differently depending on which
       order the DB returned them in.

    THERE IS NO FIFTH STAGE ANY MORE (W1, 2026-08-21). The zone-water carve —
    a room whose floor kind was water — is deleted without a fallback reader:
    water left the room plan entirely and lives on the MAP, where one polygon
    carries its own mirror, its own bed and its own flow. A room that lies on
    painted water now shows a REFERENCE in its floor plan
    (``scene_recipe._floor_plan`` → ``map_water``) and shapes nothing.

    Both stamp geometries are computed ONCE here, never per point: they are
    properties of the WORLD, not of whatever window somebody is rastering.
    That is what lets a tile stamp a plateau whose centre lies in the tile next
    door and still get the same height.

    **The model is immutable once built.** It caches noise corners and topmost
    kinds, and both caches are pure memoisation of a fixed world.
    """

    def __init__(self, areas: Sequence[Dict[str, Any]] = (),
                 terrain_areas: Sequence[Dict[str, Any]] = (),
                 terrain_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
                 footprints: Sequence["Footprint"] = ()):
        self.boxes: List[AreaBox] = area_boxes(areas)
        self._area_index = _BoxIndex([b for _a, b in self.boxes])
        # (ring, height_m, falloff_m) per height area, parsed ONCE.
        self._area_fast: List[Tuple[List[Tuple[float, float]], float,
                                    float]] = []
        for _area, _box in self.boxes:
            _r = _ring(_area.get("polygon"))
            self._area_fast.append(
                ([] if _r is None else _r,
                 float(_area.get("height_m") or 0.0),
                 float(_area.get("falloff_m") or 0.0)))
        self.relief: List[ReliefEntry] = relief_inputs(terrain_areas,
                                                       terrain_catalog)
        self._relief_index = _BoxIndex([e[2] for e in self.relief])
        self._relief_fast: List[Tuple[List[Tuple[float, float]],
                                      Optional[Tuple[int, float, float]]]] = [
            (_ring(e[0].get("polygon")) or [], e[1]) for e in self.relief]
        self._corners: Dict[Tuple[int, int, int], float] = {}
        self._kind_cache: Dict[Tuple[float, float],
                               Optional[Tuple[int, float, float]]] = {}
        #: area id -> the mirror PROFILE the carve used, authored or derived.
        self.water_profile_by_area: Dict[str, WaterProfile] = {}
        #: area id -> the bed DEPTH the carve used, in metres: the kind's
        #: default with the area's own override applied and clamped
        #: (:func:`water_meta`). Output like the profile beside it, and shipped
        #: as ``meta.water_depth_effective`` so a renderer never has to repeat
        #: that resolution to know how deep this water is.
        self.water_depth_by_area: Dict[str, float] = {}
        self.water: List[WaterStamp] = self._build_water(terrain_areas,
                                                         terrain_catalog)
        self._water_index = _BoxIndex([w[1] for w in self.water])
        self._water_fast = [(_ring(w[0]) or [], w[2], w[3], w[4])
                            for w in self.water]
        self.plateaus: List[PlateauStamp] = self._build_plateaus(footprints)
        # THE INDEX IS OVER THE RAMP BOX, not over the outline's: a stamp
        # writes as far as its ramp reaches, and an index that only knew the
        # outline would drop the ramp of every plot whose rim lies in another
        # bucket — a bug that hides wherever the bucket happens to be large.
        self._plateau_index = _BoxIndex(
            [self.plateau_ramp_box(i) for i in range(len(self.plateaus))])
        # (cx, cz, cos yaw, sin yaw, local ring, target, ramp width) — the
        # inverse pin transform spelled out so no point pays a
        # ``math.radians``/``math.cos`` per stamp.
        self._plateau_fast = []
        for cx, cz, yaw, points, _box, h0, width in self.plateaus:
            rad = math.radians(yaw or 0.0)
            self._plateau_fast.append((cx, cz, math.cos(rad), math.sin(rad),
                                       _ring(points) or [], h0, width))

    # ── the authored landscape ──────────────────────────────────────────

    def natural(self, x: float, z: float) -> float:
        """``h_natural`` at one point: the areas, plus the micro-relief.

        The |max| rule of the height areas — the STRONGEST deflection from the
        flat world wins, at equal strength the greater value, a true tie keeps
        what is there — and then the painted kind's own hills ADDED on top.
        Additive and after, because the relief is a variation OF the authored
        landscape and not a competitor of it.
        """
        h = 0.0
        fast = self._area_fast
        for idx in self._area_index.at(x, z):
            ring, height, falloff = fast[idx]
            if not ring:
                continue
            value = _area_value(ring, height, falloff, x, z)
            if value is None:
                continue
            if abs(value) > abs(h) or (abs(value) == abs(h) and value > h):
                h = value
        if self.relief:
            h += self._micro(x, z)
        return h

    def _kind_at(self, x: float, z: float
                 ) -> Optional[Tuple[int, float, float]]:
        """The relief parameters of the TOPMOST painted kind at a point.

        ``terrain_query.kind_at``'s rule — the LAST painted area containing the
        point wins — which is why the list is walked backwards and the first
        hit answers. A flat kind painted over a bumpy one therefore answers
        None: it ERASES the hills it covers, which is the whole reason
        :func:`relief_inputs` carries those flat areas at all.
        """
        fast = self._relief_fast
        for idx in reversed(self._relief_index.at(x, z)):
            ring, params = fast[idx]
            if ring and _inside_ring(x, z, ring):
                return params
        return None

    def _kind_memo(self, x: float, z: float
                   ) -> Optional[Tuple[int, float, float]]:
        """:meth:`_kind_at`, memoised on the rounded point.

        The edge rule asks about four NEIGHBOURS per evaluated point, and on a
        raster whose step is :data:`RELIEF_EDGE_PROBE_M` the neighbour of one
        support point IS the next support point — so five lookups per point
        collapse to one plus four cache hits. The key is rounded to the
        millimetre because the probe offsets are exact metre arithmetic; a
        world coordinate that differs by less than that is the same point for
        the purpose of "is there relief here".
        """
        key = (x, z)
        cache = self._kind_cache
        if key in cache:
            return cache[key]
        value = self._kind_at(x, z)
        if len(cache) > 400_000:
            cache.clear()
        cache[key] = value
        return value

    def _micro(self, x: float, z: float) -> float:
        """The micro-relief at one point, edge rule included.

        THE EDGE RULE (2026-08-13, § A16.2, METRE-BASED since E1): a DIP is cut
        off where one of the four points at :data:`RELIEF_EDGE_PROBE_M` carries
        no relief. A bumpy meadow may run OUT over its border — a shore rising
        softly is what one wants — but it must never pull the flat neighbour
        DOWN, which was the acceptance finding the rule was written for: the
        seam of a lake sank with the grass beside it.
        """
        kind_at = self._kind_memo
        params = kind_at(x, z)
        if params is None:
            return 0.0
        seed, amp, wave = params
        fx = x / wave
        fz = z / wave
        u = math.floor(fx)
        v = math.floor(fz)
        tx = fx - u
        tz = fz - v
        corners = self._corners
        n00 = _corner(corners, seed, u, v)
        n10 = _corner(corners, seed, u + 1, v)
        n01 = _corner(corners, seed, u, v + 1)
        n11 = _corner(corners, seed, u + 1, v + 1)
        north = n00 * (1.0 - tx) + n10 * tx
        south = n01 * (1.0 - tx) + n11 * tx
        noise = (north * (1.0 - tz) + south * tz) * amp
        if noise < 0.0:
            p = RELIEF_EDGE_PROBE_M
            if (kind_at(x - p, z) is None or kind_at(x + p, z) is None
                    or kind_at(x, z - p) is None
                    or kind_at(x, z + p) is None):
                return 0.0
        return noise

    # ── the stamps ──────────────────────────────────────────────────────

    def _build_water(self, terrain_areas: Sequence[Dict[str, Any]],
                     catalog: Optional[Dict[str, Dict[str, Any]]]
                     ) -> List[WaterStamp]:
        """Every water polygon with its mirror PROFILE settled (§ A16.3, W1).

        THE DEFAULT MIRROR IS A MEDIAN OF THE NATURAL HEIGHTS ALONG THE RIM,
        computed here from :meth:`natural` — i.e. from the landscape before any
        stamp, water's own included. A lake whose level was read from the
        carved ground would sink a little further every time the world was
        re-baked. An AUTHORED level always wins; the default only exists so a
        freshly painted water has a mirror at all, and
        ``models.terrain.save_area`` persists it so it stops depending on the
        landscape around it.

        WITHOUT A FLOW DIRECTION that is ONE median over the WHOLE rim and both
        ends of the profile carry it — the still lake of every round before
        this one. WITH one, the rim is split along the flow axis and each end
        gets the median of ITS OWN THIRD:

        * project every rim sample onto the axis, giving ``s`` per sample and
          the span ``[s_min, s_max]`` the polygon occupies along it;
        * ``level_up`` = median over the samples with ``s ≤ s_min + span/3``,
          ``level_down`` = median over those with ``s ≥ s_max − span/3``.

        A THIRD, not "the two extreme points": a river drawn with four corners
        has one sample at each end and would take its levels from two arbitrary
        pixels of the landscape. A third of the span is enough rim to be a
        median and short enough that the middle of the river never votes on
        either end.

        AN AREA FLOWED ALONG ITS DRAWN LINE (``meta.flow_along``, W4a) does not
        come through here at all: its axis is the line, its levels are one
        median per KNOT, and the rule is in :meth:`_stroke_profile`.
        """
        from app.core.terrain_types import water_kind_defaults
        out: List[WaterStamp] = []
        for area, box in water_areas(terrain_areas, catalog):
            polygon = area.get("polygon")
            kind = str(area.get("kind") or "")
            meta = water_meta(area, water_kind_defaults(kind, catalog or {}))
            profile = self.water_profile_for(polygon, meta)
            out.append((polygon, box, profile, meta.depth_m,
                        meta.shore_ramp_m))
            # THE EFFECTIVE PROFILE, keyed by area id (E1b): the admin panel
            # offers "auto (rim)" and still wants to show the numbers the carve
            # actually used. It is server-computed OUTPUT — it is never written
            # back into the authored fields, which stay the author's.
            area_id = str(area.get("id") or "")
            if area_id:
                self.water_profile_by_area[area_id] = profile
                self.water_depth_by_area[area_id] = meta.depth_m
        return out

    def water_profile_for(self, polygon: Any,
                          meta: WaterMeta) -> WaterProfile:
        """The mirror profile of ONE water polygon — the whole rule, once.

        THREE CASES, ONE FUNCTION AT THE END (W4a). An area flowed along its
        DRAWN LINE takes that line as its axis (:meth:`_stroke_profile`); one
        with a ``flow_dir_deg`` takes the straight axis of W1, written down as
        the two-knot degenerate case; one with neither is a lake and is the
        one-knot case. Whatever comes out, ``water_level_at`` reads it the same
        way.

        Authoring beats derivation at EACH END separately: ``water_level_up`` /
        ``water_level_down`` win for their own end, a plain ``water_level`` wins
        for both (that IS the still lake), and what neither names is the rim
        median described in :meth:`_build_water`.
        """
        if (meta.flow_along in FLOW_ALONG_VALUES
                and len(meta.stroke_points) >= 2):
            knots = _stroke_knots(meta)
            if len(knots) >= 2:
                return self._stroke_profile(knots, meta)
        ring = _ring(polygon) or []
        dir_x, dir_z = flow_direction(meta.flow_dir_deg)
        axis_x, axis_z = _ring_centroid(ring)
        rim = _rim_samples(polygon)
        if meta.flow_dir_deg is None or not rim:
            # STILL WATER: no direction, one median, ONE knot. The nearest
            # point on a one-knot polyline is that knot, so ``water_level_at``
            # answers its level everywhere without ever dividing by a span.
            level = meta.level_up if meta.level_up is not None else meta.level
            if level is None:
                level = meta.level_down
            if level is None:
                level = (_median([self.natural(px, pz) for px, pz in rim])
                         if rim else 0.0)
            return WaterProfile(level_up=float(level), level_down=float(level),
                                flow_dir_deg=None, axis_x=axis_x,
                                axis_z=axis_z, dir_x=0.0, dir_z=0.0,
                                s_min=0.0, s_max=0.0,
                                axis=((axis_x, axis_z, 0.0, float(level)),))
        projected = [(((px - axis_x) * dir_x + (pz - axis_z) * dir_z), px, pz)
                     for px, pz in rim]
        s_min = min(entry[0] for entry in projected)
        s_max = max(entry[0] for entry in projected)
        third = (s_max - s_min) / 3.0
        up_cut = s_min + third
        down_cut = s_max - third
        level_up = meta.level_up if meta.level_up is not None else meta.level
        level_down = (meta.level_down if meta.level_down is not None
                      else meta.level)
        if level_up is None:
            level_up = _median([self.natural(px, pz)
                                for s, px, pz in projected if s <= up_cut])
        if level_down is None:
            level_down = _median([self.natural(px, pz)
                                  for s, px, pz in projected if s >= down_cut])
        # THE STRAIGHT AXIS AS TWO KNOTS: the upstream and the downstream
        # extreme of the polygon, ON the axis, carrying their own end level.
        # The projection onto that single segment IS the ``(s − s_min)/span``
        # of W1 — same arithmetic, one reader.
        return WaterProfile(level_up=float(level_up),
                            level_down=float(level_down),
                            flow_dir_deg=float(meta.flow_dir_deg),
                            axis_x=axis_x, axis_z=axis_z,
                            dir_x=dir_x, dir_z=dir_z,
                            s_min=s_min, s_max=s_max,
                            axis=((axis_x + dir_x * s_min,
                                   axis_z + dir_z * s_min,
                                   s_min, float(level_up)),
                                  (axis_x + dir_x * s_max,
                                   axis_z + dir_z * s_max,
                                   s_max, float(level_down))))

    def _stroke_profile(self, knots: List[Tuple[float, float, float]],
                        meta: WaterMeta) -> WaterProfile:
        """The mirror of a river that follows its DRAWN LINE (W4a, § A16.3).

        THE LEVEL OF ONE KNOT is the median of :meth:`natural` over a CROSS
        SECTION at that knot: :data:`WATER_AXIS_CROSS_SAMPLES` probes
        perpendicular to the local tangent, spread over the ribbon's own width
        plus the shore ramp on both sides. It is the rim median of § A16.3 taken
        LOCALLY — a river is only ever a few metres wide, and a median across
        it is decided by the valley it lies in, not by the one square metre the
        line happens to pass over.

        THEN DOWNSTREAM IS MONOTONE: a running minimum along the flow. Water
        never runs uphill, and a drawn line that crosses a rise would otherwise
        put a step in the mirror there.

        THEN THE AUTHOR WINS. ``water_level`` makes every knot that number (a
        drawn but standing water). ``water_level_up`` / ``water_level_down``
        replace the first / last knot, and the inner knots are remapped AFFINELY
        into the new span: their shape — where the river falls fast and where it
        pools — is the landscape's answer and survives, only its two ends become
        the authored ones. Where the derived shape is FLAT there is no shape to
        keep and the knots ramp linearly along ``s``.
        """
        levels = [self._cross_median(knots, i, meta)
                  for i in range(len(knots))]
        i = 1
        while i < len(levels):
            if levels[i] > levels[i - 1]:
                levels[i] = levels[i - 1]
            i += 1
        levels = _authored_axis_levels(levels, [k[2] for k in knots], meta)
        axis = tuple((kx, kz, ks, lv)
                     for (kx, kz, ks), lv in zip(knots, levels))
        # THE NINE NUMBERS for a reader that only knows the tilted plane: the
        # chord FIRST → LAST knot is the best single axis through a meander,
        # and the two end levels are the ones the plane must hit.
        first, last = axis[0], axis[-1]
        dx, dz = last[0] - first[0], last[1] - first[1]
        if math.hypot(dx, dz) <= 1e-9:
            # A LINE THAT RETURNS TO ITS START (a full loop) has no chord; the
            # first segment is the only honest bearing left, and the span
            # collapses to zero, so the nine-number reader sees one flat plane.
            dx, dz = axis[1][0] - first[0], axis[1][1] - first[1]
        bearing = round(math.degrees(math.atan2(dx, dz)) % 360.0, 3)
        dir_x, dir_z = flow_direction(bearing)
        s_max = ((last[0] - first[0]) * dir_x + (last[1] - first[1]) * dir_z)
        return WaterProfile(level_up=axis[0][3], level_down=axis[-1][3],
                            flow_dir_deg=bearing,
                            axis_x=first[0], axis_z=first[1],
                            dir_x=dir_x, dir_z=dir_z,
                            s_min=0.0, s_max=s_max, axis=axis)

    def _cross_median(self, knots: List[Tuple[float, float, float]], i: int,
                      meta: WaterMeta) -> float:
        """The natural height ACROSS the river at knot ``i`` — its median."""
        tx, tz = _knot_tangent(knots, i)
        px, pz = knots[i][0], knots[i][1]
        half = meta.stroke_width_m * 0.5 + meta.shore_ramp_m
        n = WATER_AXIS_CROSS_SAMPLES
        step = (2.0 * half) / (n - 1)
        # The perpendicular of (tx, tz) is (−tz, tx); the offsets run from one
        # bank to the other and include the centre exactly once (n is odd).
        return _median([self.natural(px - tz * (step * k - half),
                                     pz + tx * (step * k - half))
                        for k in range(n)])

    def _build_plateaus(self, footprints: Sequence["Footprint"]
                        ) -> List[PlateauStamp]:
        """Every built location's plot, with its target height and ramp (§ G5).

        LARGEST AREA FIRST, so the SMALLEST writes last and has the final say —
        the hut on the village square is the more specific answer about the
        square metre it stands on, the rule ``location_at_point`` already
        resolves nesting by — and the same rule ``terrain_layers.world_floors``
        orders the LAYERS of the ground by. ``sorted`` is stable, so equal
        areas keep the caller's order.

        TARGET = the MEDIAN of :meth:`natural` over the footprint, sampled on
        the 2 m world lattice inside the outline (the guaranteed interior point
        alone where the outline is too small to catch one). It replaced the
        single interior probe of the old pass: a probe is decided by whatever
        the micro-relief happens to do at one square metre, a median has to be
        outvoted by half the plot.

        RAMP = :data:`PLATEAU_RAMP_FACTOR` · √(area/π), clamped into
        [:data:`PLATEAU_RAMP_MIN_M`, :data:`PLATEAU_RAMP_MAX_M`] — and then
        WIDENED where the rim step demands it: with ``Δ`` the largest
        |target − natural| along the outline, the width is at least
        ``Δ / tan(35°)``, so the ramp of a place on a hillside gets long
        instead of vertical.
        """
        from app.core.world_geometry import (polygon_area, polygon_distance,
                                             polygon_interior_point,
                                             world_to_local)
        usable: List[Tuple[float, float, float, float,
                           List[Tuple[float, float]],
                           Tuple[float, float, float, float]]] = []
        for fp, box in _boxed_footprints(footprints):
            cx, cz, yaw, points = float(fp[0]), float(fp[1]), float(fp[2]), \
                fp[3]
            if polygon_interior_point(points) is None:
                # A degenerate outline (all points on one line) encloses
                # nothing: no square metre to stand on, nothing to level.
                continue
            usable.append((polygon_area(points), cx, cz, yaw, points, box))
        ordered = sorted(usable, key=lambda entry: -entry[0])
        out: List[PlateauStamp] = []
        tan_max = math.tan(math.radians(PLATEAU_MAX_SLOPE_DEG))
        for area, cx, cz, yaw, points, box in ordered:
            samples: List[float] = []
            step = TILE_STEP_M
            i0 = int(math.floor(box[0] / step))
            i1 = int(math.ceil(box[2] / step))
            j0 = int(math.floor(box[1] / step))
            j1 = int(math.ceil(box[3] / step))
            # A very large plot is sampled on a coarser lattice rather than on
            # every one of its (possibly millions of) 2 m points — the median
            # of a plane does not get better for being asked more often.
            stride = max(1, int(math.ceil(
                math.sqrt(max(1.0, (i1 - i0 + 1) * (j1 - j0 + 1) / 4096.0)))))
            for j in range(j0, j1 + 1, stride):
                pz = j * step
                for i in range(i0, i1 + 1, stride):
                    px = i * step
                    lx, lz = world_to_local(px, pz, cx, cz, yaw)
                    if polygon_distance(lx, lz, points) <= 0.0:
                        samples.append(self.natural(px, pz))
            if not samples:
                inner = polygon_interior_point(points)
                from app.core.world_geometry import local_to_world
                wx, wz = local_to_world(inner[0], inner[1], cx, cz, yaw)
                samples.append(self.natural(wx, wz))
            h0 = _median(samples)
            width = min(max(PLATEAU_RAMP_FACTOR * math.sqrt(area / math.pi),
                            PLATEAU_RAMP_MIN_M), PLATEAU_RAMP_MAX_M)
            from app.core.world_geometry import polygon_local_to_world
            world_ring = polygon_local_to_world(points, cx, cz, yaw) or []
            drop = 0.0
            for px, pz in _rim_samples(world_ring):
                drop = max(drop, abs(h0 - self.natural(px, pz)))
            if tan_max > 0 and SMOOTHSTEP_PEAK * drop > tan_max * width:
                width = SMOOTHSTEP_PEAK * drop / tan_max
            out.append((cx, cz, yaw, points, box, h0, width))
        return out

    def plateau_ramp_box(self, index: int
                         ) -> Tuple[float, float, float, float]:
        """The world box a plateau stamp can write into — its outline PLUS its
        ramp. What the grid has to cover, and what the index has to list."""
        _cx, _cz, _yaw, _pts, box, _h0, width = self.plateaus[index]
        return _grown(box, width)

    # ── h_final ─────────────────────────────────────────────────────────

    def final(self, x: float, z: float) -> float:
        """``h_final`` at one point — the whole pipeline, in order.

        areas → micro-relief → water carve → plateaus. Every step is metre
        parametrised, so this answer does not know and cannot know which lattice
        (if any) it is being sampled on.
        """
        h = self.natural(x, z)
        h = self._carve(h, x, z)
        return self._stamp(h, x, z)

    def _carve(self, h: float, x: float, z: float) -> float:
        """The water stamp: ``h = min(h, level_at(x,z) − depth_profile(d))``.

        ``d`` is the distance from the point to the polygon OUTLINE, so the
        profile is 0 at the rim and smoothsteps to the full depth
        ``shore_ramp_m`` metres inside. MIN, never assignment: a rock rising
        out of a lake stays where it is only if it is already below the
        mirror — anything above is cut, which is precisely the invariant.

        THE LEVEL IS LOCAL (W1). It is ``water_level_at`` of this area's
        profile, so a river's bed follows its own tilted mirror down the valley
        instead of hanging from one plane; for still water the profile answers
        the same number everywhere and this is literally the old expression. The
        invariant grows with it: past the shore ramp the second argument of the
        ``min`` is ``level_at(x,z) − depth``, so ``h ≤ level_at(x,z) − ε`` holds
        POINTWISE, not against an average.
        """
        if not self.water:
            return h
        fast = self._water_fast
        for idx in self._water_index.at(x, z):
            ring, water_profile, depth, ramp = fast[idx]
            if not ring or not _inside_ring(x, z, ring):
                continue
            if ramp <= 0.0:
                profile = depth
            else:
                profile = depth * smoothstep(
                    _ring_edge_distance(x, z, ring) / ramp)
            bed = water_level_at(water_profile, x, z) - profile
            if bed < h:
                h = bed
        return h

    def _stamp(self, h: float, x: float, z: float) -> float:
        """The plateau stamps, in their order (largest area first).

        Inside the outline the answer IS the target height. Outside it the
        ramp blends back over ``width`` metres — and it blends against the
        height the pipeline holds SO FAR, not against the untouched landscape,
        so a hut inside a village square walks down onto the square's plateau
        instead of down to the hillside underneath both.
        """
        if not self.plateaus:
            return h
        fast = self._plateau_fast
        for idx in self._plateau_index.at(x, z):
            cx, cz, cos_y, sin_y, ring, h0, width = fast[idx]
            dx, dz = x - cx, z - cz
            lx = dx * cos_y - dz * sin_y
            lz = dx * sin_y + dz * cos_y
            if not ring:
                continue
            if _inside_ring(lx, lz, ring):
                h = h0
                continue
            d = _ring_edge_distance(lx, lz, ring)
            if d < width:
                h = h0 + (h - h0) * smoothstep(d / width)
        return h

    # ── what the model REACHES ──────────────────────────────────────────

    def shaped_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        """The union box of everything that can move a height away from 0 —
        or None for a world that shapes nothing.

        Height areas, relief-CARRYING painted areas, water polygons and every
        plateau's outline plus its ramp. It is a SUPERSET of
        "where the ground is not flat", which is the property the tile index and
        the grid growth both hang on: outside it the world is answered 0 without
        rastering anything.
        """
        boxes = self.shaped_boxes()
        return _union(boxes) if boxes else None

    def shaped_boxes(self) -> List[Tuple[float, float, float, float]]:
        """Every box of :meth:`shaped_bounds`, unmerged — the tile index reads
        these one by one so a hut 1.6 km away indexes its own tile and not the
        whole rectangle between."""
        boxes = [b for _a, b in self.boxes]
        boxes += [e[2] for e in self.relief if e[1] is not None]
        boxes += [w[1] for w in self.water]
        boxes += [self.plateau_ramp_box(i) for i in range(len(self.plateaus))]
        return boxes

    def grid(self, origin_x: float, origin_z: float, step: float,
             cols: int, rows: int) -> List[List[float]]:
        """:meth:`final` over one window of a lattice — the ONE way a grid is
        made in this module.

        A WINDOW IS ITS ORIGIN, ITS STEP AND ITS SIZE, nothing else. It may lie
        anywhere and may be smaller than an area; what a point outside it does
        is not this function's business, because there is no window state to
        get wrong any more.
        """
        if cols < 1 or rows < 1 or step <= 0:
            return [[0.0] * max(cols, 0) for _ in range(max(rows, 0))]
        final = self.final
        out: List[List[float]] = []
        for j in range(rows):
            pz = origin_z + j * step
            out.append([final(origin_x + i * step, pz)
                        for i in range(cols)])
        return out


def build_model(areas: Sequence[Dict[str, Any]] = (),
                footprints: Sequence["Footprint"] = (),
                terrain_areas: Sequence[Dict[str, Any]] = (),
                terrain_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
                ) -> HeightModel:
    """A :class:`HeightModel` from the four raster inputs — pure, no DB.

    The argument order of :func:`rasterize`, so a smoke run can build a world
    out of literals and ask it anything.
    """
    return HeightModel(areas=areas, terrain_areas=terrain_areas,
                       terrain_catalog=terrain_catalog, footprints=footprints)


def rasterize(areas: Sequence[Dict[str, Any]],
              step_m: float = 0.0,
              footprints: Sequence[Footprint] = (),
              terrain_areas: Sequence[Dict[str, Any]] = (),
              terrain_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
              model: Optional[HeightModel] = None,
              ) -> Dict[str, Any]:
    """The whole world as ONE grid — pure, deterministic, no DB.

    THE OVERVIEW (v2, decision 2026-08-14), and only the distant view reads it:
    it is the one raster that may be COARSENED, and a rule asked at 32 m would
    judge a landscape nobody authored. Since E1 the coarsening no longer
    changes the landscape, only how finely it is sampled — every support point
    it keeps carries the number a tile carries there, because both are
    :meth:`HeightModel.final` (§ G1).

    ``footprints`` are the BUILT locations, each a :data:`Footprint`
    ``(cx, cz, yaw_deg, boundary points in local metres)`` out of
    ``models.heightfield.placed_footprints``. Since E1 there is no flag to
    set: a location that draws a built floor stamps its plot, one that does not
    leaves the landscape running through it (§ G5).

    ``terrain_areas`` + ``terrain_catalog`` are the painted ground and its type
    catalog, and they carry two things: the MICRO-RELIEF of a kind with hills
    and the WATER polygons that carve their own bed (§ G4). They are handed IN
    rather than read, because this function stays pure — the caller
    (:func:`get_field`) does the one DB read.

    THE GRID COVERS WHAT SHAPES THE GROUND and one ring beyond
    (:func:`_axis_origin`), so the whole border is 0 and "clamp outside the
    grid" means "the flat world". A world that shapes nothing at all answers an
    empty grid: a hundred places on an unpainted world stamp plateaus of 0 onto
    ground that is already 0, and a grid of zeros is a payload nobody needs.

    ``model`` lets a caller hand in a model it has already built (the payload
    path builds one per generation); without it one is built here.
    """
    if model is None:
        model = build_model(areas, footprints, terrain_areas, terrain_catalog)
    # What the LANDSCAPE reaches — the height areas, the relief-carrying
    # painted areas and the water polygons. The plateaus are handled apart
    # because a place far outside all of that stamps 0 onto 0 and must not
    # stretch the grid across the world to do it.
    world_boxes = ([b for _a, b in model.boxes]
                   + [e[2] for e in model.relief if e[1] is not None]
                   + [w[1] for w in model.water])
    if not world_boxes:
        return {"origin_x": 0.0, "origin_z": 0.0,
                "step_m": step_m or DEFAULT_STEP_M,
                "rows": 0, "cols": 0, "heights": []}
    area_bounds = _union(world_boxes)
    ramp_boxes = [model.plateau_ramp_box(i)
                  for i in range(len(model.plateaus))]
    bounds = _union([area_bounds]
                    + [b for b in ramp_boxes if _overlaps(b, area_bounds)])
    step = float(step_m) if step_m and step_m > 0 else _step_for(bounds)
    min_x, min_z, max_x, max_z = bounds
    origin_x = _axis_origin(min_x, step)
    origin_z = _axis_origin(min_z, step)
    cols = _axis_points(min_x, max_x, step)
    rows = _axis_points(min_z, max_z, step)
    heights = model.grid(origin_x, origin_z, step, cols, rows)
    return {"origin_x": round(origin_x, 3), "origin_z": round(origin_z, 3),
            "step_m": step, "rows": rows, "cols": cols,
            "heights": [[round(v, 3) for v in row] for row in heights]}


# ── Tiles: the fine ground the RULES read ───────────────────────────────

#: Edge of one height tile, in metres. 256 is a multiple of
#: :data:`TILE_STEP_M`, which is the whole requirement: a tile's support
#: points are then global lattice points and a tile is a WINDOW of the one
#: world grid rather than a grid of its own. It is also a sensible parcel —
#: 129 × 129 points, a few milliseconds to raster, about a hundred kilobytes
#: to ship.
TILE_M = 256.0

#: Support points per tile axis — the edges INCLUDED, so tile (tx, tz) covers
#: ``[tx·256, (tx+1)·256]`` closed and the point on a seam exists in both
#: neighbours. That duplication is deliberate: bilinear sampling inside a tile
#: never needs a point from the tile next door (so a client may hold any subset
#: it likes), and the shared points guarantee the ground is continuous across
#: the seam instead of merely nearly so.
TILE_POINTS = int(TILE_M / TILE_STEP_M) + 1


def tile_key(x: float, z: float) -> Tuple[int, int]:
    """The tile a world point belongs to — ``floor((x, z) / TILE_M)``.

    A point ON a seam belongs to the tile EAST/SOUTH of it, which is the same
    half-open rule the nav grid uses for its cells. Both tiles carry that point
    with the same height, so nothing depends on the choice.
    """
    return (int(math.floor(float(x) / TILE_M)),
            int(math.floor(float(z) / TILE_M)))


def tiles_of_box(box: Tuple[float, float, float, float]
                 ) -> List[Tuple[int, int]]:
    """Every tile an axis-aligned box reaches into, seams included."""
    tx0, tz0 = tile_key(box[0], box[1])
    tx1, tz1 = tile_key(box[2], box[3])
    return [(tx, tz) for tx in range(tx0, tx1 + 1)
            for tz in range(tz0, tz1 + 1)]


def tile_index_from(areas: Sequence[Dict[str, Any]] = (),
                    footprints: Sequence[Footprint] = (),
                    terrain_areas: Sequence[Dict[str, Any]] = (),
                    terrain_catalog: Optional[Dict[str, Dict[str, Any]]]
                    = None,
                    model: Optional[HeightModel] = None,
                    ) -> frozenset:
    """Which tiles the world has a ground in — pure, no DB (v2, 2026-08-14).

    PURE BOX COVERAGE, and nothing finer: a tile is indexed when a height
    area's box, a relief-carrying terrain area's box, a WATER polygon's box or
    a plateau's outline PLUS ITS RAMP reaches into it. A polygon that only
    clips the corner of a tile still indexes the whole tile — the answer is
    "there may be ground here", and the raster then says what it is.

    OUTSIDE THE INDEX THE WORLD IS FLAT, which is the property everything else
    hangs on (:func:`world_height` answers 0.0 there without rastering
    anything), so the list has to be a SUPERSET of everywhere a height can be
    non-zero. It is: every one of the four writes only inside its own box, and
    the plateau box already carries the ramp — which since E1 is a METRE width
    off the stamp itself (§ G5) and not "one cell of whatever grid".

    A PLATEAU OUT IN THE FLAT WORLD IS DROPPED. Its target height is the median
    of the natural ground under it, i.e. 0 out there, and its ramp then blends
    0 into 0 — it writes nothing anywhere and needs no tile. The test is
    against the box of everything that shapes the LANDSCAPE, so a hut 1.6 km
    from the nearest painted thing costs no tile at all.

    THE ARGUMENTS ARE :func:`rasterize`'s, deliberately — the index and the
    grid have to be built from the same four inputs or they will disagree
    about where the ground is. Handing in a ``model`` skips the rebuild.
    """
    if model is None:
        model = build_model(areas, footprints, terrain_areas, terrain_catalog)
    world_boxes = ([b for _a, b in model.boxes]
                   + [e[2] for e in model.relief if e[1] is not None]
                   + [w[1] for w in model.water])
    if not world_boxes:
        # Nothing shapes the ground: no tile, exactly as the overview returns
        # an empty grid.
        return frozenset()
    area_bounds = _union(world_boxes)
    boxes = list(world_boxes)
    boxes += [b for b in (model.plateau_ramp_box(i)
                          for i in range(len(model.plateaus)))
              if _overlaps(b, area_bounds)]
    keys: List[Tuple[int, int]] = []
    for box in boxes:
        keys.extend(tiles_of_box(box))
    return frozenset(keys)


def rasterize_tile(
        tx: int, tz: int,
        areas: Sequence[Dict[str, Any]],
        footprints: Sequence[Footprint] = (),
        terrain_areas: Sequence[Dict[str, Any]] = (),
        terrain_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
        model: Optional[HeightModel] = None,
) -> Dict[str, Any]:
    """ONE 256 m tile of the world ground as a grid — pure, no DB.

    The same payload shape :func:`sample_height` reads and the same shape the
    overview has, only with a fixed window: origin ``(tx·256, tz·256)``, step
    :data:`TILE_STEP_M`, 129 × 129 points. It takes the very inputs
    :func:`rasterize` takes, for the same reason: purity, so a smoke run can
    build a world out of literals.

    IT IS A WINDOW OF THE ONE FUNCTION, NOT A SECOND OPINION. Both go through
    :meth:`HeightModel.grid` over the world-anchored lattice, so the two carry
    the same number at every shared point — seams, plateau ramps and shore
    ramps included, and at ANY step, because since E1 nothing in the bake
    measures in grid cells (§ G1).

    NO FOOTPRINT IS FILTERED OUT HERE. A stamp whose centre lies in the tile
    next door still ramps into this one, and the ORDER of the stamps decides on
    overlap — dropping a member of that chain would let a wide plateau show
    through where a narrow one flattened it.
    """
    if model is None:
        model = build_model(areas, footprints, terrain_areas, terrain_catalog)
    origin_x = tx * TILE_M
    origin_z = tz * TILE_M
    heights = model.grid(origin_x, origin_z, TILE_STEP_M,
                         TILE_POINTS, TILE_POINTS)
    return {"origin_x": origin_x, "origin_z": origin_z,
            "step_m": TILE_STEP_M,
            "rows": TILE_POINTS, "cols": TILE_POINTS,
            "heights": [[round(v, 3) for v in row] for row in heights]}


# ── The pyramid: what a coarser lattice costs (§ G2) ────────────────────

def mip_error(heights: Sequence[Sequence[float]], step_m: float,
              level_m: float) -> float:
    """Largest vertical error, in metres, of drawing ``level_m`` instead of the
    base lattice this array stands on.

    THE MIP LATTICE IS A SUBSET OF THE BASE LATTICE — ``level_m`` is a multiple
    of ``step_m`` and divides the array — so the coarse level needs no second
    evaluation of anything: it IS these values, every ``stride``-th one. That
    is purity paying for itself (§ G1); with the old raster-dependent bake a
    coarser grid was a different landscape and the difference could not be
    called an error at all.

    THE NUMBER IS AN EXACT BOUND, not a sample. Both fields are bilinear
    inside one base cell — the coarse one because a bilinear function stays
    bilinear on a sub-rectangle — so their difference is bilinear there too,
    and a bilinear function on a rectangle takes its extremes AT THE CORNERS.
    The maximum over the base support points is therefore the maximum over the
    whole tile, continuum included.

    An array too small for the level, or a level that is not a whole number of
    steps, answers 0.0: there is no coarser lattice to compare against.
    """
    rows = len(heights)
    cols = len(heights[0]) if rows and isinstance(heights[0], list) else 0
    if rows < 2 or cols < 2 or step_m <= 0 or level_m <= 0:
        return 0.0
    stride = int(round(level_m / step_m))
    if stride < 1 or abs(stride * step_m - level_m) > 1e-9:
        return 0.0
    if stride == 1:
        return 0.0
    if (rows - 1) % stride or (cols - 1) % stride:
        return 0.0
    worst = 0.0
    for j in range(rows):
        jc = min(j // stride, (rows - 1) // stride - 1)
        tz = (j - jc * stride) / stride
        row_n = heights[jc * stride]
        row_s = heights[(jc + 1) * stride]
        base = heights[j]
        for i in range(cols):
            ic = min(i // stride, (cols - 1) // stride - 1)
            tx = (i - ic * stride) / stride
            a = row_n[ic * stride]
            b = row_n[(ic + 1) * stride]
            c = row_s[ic * stride]
            d = row_s[(ic + 1) * stride]
            north = a + (b - a) * tx
            south = c + (d - c) * tx
            err = abs(north + (south - north) * tz - base[i])
            if err > worst:
                worst = err
    return worst


def tile_stats_from(tile: Dict[str, Any]) -> Dict[str, Any]:
    """``{"min", "max", "err"}`` of one rastered tile (§ G2).

    ``err`` is one number per entry of :data:`MIP_LEVELS_M`, in that order:
    the largest vertical distance between the tile drawn at that level and the
    tile drawn at the 2 m base. A CDLOD renderer picks its level from exactly
    this — "at this camera distance, how many metres of error may I buy" — and
    the water invariant of § G4 is stated against the coarsest one, so the two
    consumers of the pyramid read the same numbers.

    ``min``/``max`` are the tile's own extent, the other half a quadtree node
    needs (frustum and occlusion boxes).
    """
    heights = tile.get("heights") or []
    step = float(tile.get("step_m") or TILE_STEP_M)
    flat = [v for row in heights for v in row]
    return {
        "min": round(min(flat), 3) if flat else 0.0,
        "max": round(max(flat), 3) if flat else 0.0,
        "err": [round(mip_error(heights, step, level), 4)
                for level in MIP_LEVELS_M],
    }


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

#: (generation, inputs) — the four raster inputs, read once per generation.
#: The tiles are built lazily, so without this a tile miss would be a DB read,
#: and a route crossing five tiles would pay five of them mid-A*.
_TILE_INPUTS: Optional[Tuple[int, Tuple[List[Dict[str, Any]],
                                        List[Tuple[float, float, float,
                                                   float]],
                                        List[Dict[str, Any]],
                                        Dict[str, Dict[str, Any]]]]] = None

#: (generation, keys) of the tile index.
_TILE_INDEX: Optional[Tuple[int, frozenset]] = None

#: (generation, model) — THE world's height function for this generation
#: (§ G1). Built once, read by the overview, by every tile and by every mip
#: statistic, which is what makes "the same function at every density" a fact
#: of the process and not a hope: two models built from the same DB rows would
#: agree anyway (they are pure), but they would each pay for their own stamp
#: geometry — a plateau median is a few thousand height evaluations.
_MODEL: Optional[Tuple[int, "HeightModel"]] = None

#: (generation, {(tx, tz): stats}) — the pyramid statistics per tile (§ G2).
#: Kept apart from :data:`_TILES` because they outlive the tile they describe:
#: the LRU may evict a 129² array long before a client stops asking what its
#: mip error was.
_TILE_STATS: Optional[Tuple[int, Dict[Tuple[int, int], Dict[str, Any]]]] = None

#: The tiles this process holds, keyed ``(generation, tx, tz)`` and ordered
#: least-recently-used FIRST. A plain OrderedDict rather than
#: ``functools.lru_cache``: the generation has to be able to drop the whole
#: cache at once, and a decorator that only knows its own arguments cannot.
_TILES: "OrderedDict[Tuple[int, int, int], Dict[str, Any]]" = OrderedDict()

#: How many tiles stay in the process. 128 tiles are 128 × 129² floats
#: ≈ 68 MB — the same footprint as the old 512 tiles at the 4 m step, and
#: the client's want-set (~28 tiles) stays well under the limit.
TILE_CACHE_MAX = 128


def invalidate_cache() -> None:
    """Drop the cached field AND every cached tile (tests + authoring writes).

    THE ONE WAY the cache learns about a change. A writer that goes round
    ``app/models/heightfield`` — raw SQL against ``height_areas`` — leaves this
    process on a stale grid until it is called; that is the price of not
    hashing on the read path, and there is no such writer in the app.

    The tiles hang off the same generation counter as the overview, because
    they describe the same authored world: a hill painted into it moves both,
    and a tile that outlived its world would let a walker walk on a ground the
    picture no longer shows. Bumping the counter alone would already do it (it
    is part of every tile key); the caches are emptied as well so a long-lived
    process does not carry a dead generation around.
    """
    global _GENERATION, _CACHE, _TILE_INDEX, _TILE_INPUTS, _MODEL, _TILE_STATS
    _GENERATION += 1
    _CACHE = None
    _TILE_INDEX = None
    _TILE_INPUTS = None
    _MODEL = None
    _TILE_STATS = None
    _TILES.clear()


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
    field = rasterize((), model=world_model())
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


def _tile_inputs() -> Tuple[List[Dict[str, Any]],
                            List[Tuple[float, float, float, float]],
                            List[Dict[str, Any]],
                            Dict[str, Dict[str, Any]]]:
    """The four raster inputs, read ONCE per generation.

    The same four :func:`get_field` reads and ``height_sig`` hashes — height
    areas, levelling placements, painted terrain and the type catalog — kept
    here because the tiles are built ON DEMAND: without it a tile miss would be
    four DB reads, and those misses happen in the middle of a route, of a walk
    report, of an A* expansion. With it a miss is arithmetic.
    """
    global _TILE_INPUTS
    cached = _TILE_INPUTS
    if cached is not None and cached[0] == _GENERATION:
        return cached[1]
    generation = _GENERATION
    from app.core.terrain_types import effective_catalog
    from app.models import heightfield as store
    from app.models.terrain import list_areas
    data = (store.list_height_areas(), store.placed_footprints(),
            list_areas(), effective_catalog())
    _TILE_INPUTS = (generation, data)
    return data


def world_model() -> HeightModel:
    """THE height function of this world, built once per generation (§ G1).

    Everything that produces a height goes through it — the overview, every
    tile, every mip statistic, ``ground_y``. Building it costs the stamp
    geometry (a median under every plot, a rim median under every lake), which
    is why it is cached and why the cache is dropped by the same
    :func:`invalidate_cache` every other derived thing hangs on.
    """
    global _MODEL
    cached = _MODEL
    if cached is not None and cached[0] == _GENERATION:
        return cached[1]
    generation = _GENERATION
    areas, footprints, terrain_areas, catalog = _tile_inputs()
    model = build_model(areas, footprints, terrain_areas, catalog)
    _MODEL = (generation, model)
    return model


def tile_index() -> frozenset:
    """The keys of every tile the world has a ground in, cached per generation.

    The reading half of :func:`tile_index_from` — same list of tiles, read out
    of the DB instead of handed in. It is asked on EVERY :func:`world_height`,
    so it must be a set lookup and nothing more; that is what the per-
    generation cache buys.
    """
    global _TILE_INDEX
    cached = _TILE_INDEX
    if cached is not None and cached[0] == _GENERATION:
        return cached[1]
    generation = _GENERATION
    keys = tile_index_from(model=world_model())
    _TILE_INDEX = (generation, keys)
    return keys


def get_tile(tx: int, tz: int) -> Dict[str, Any]:
    """One tile of the world ground, rastered on demand and kept (LRU).

    NOTHING IS STORED IN THE DB, deliberately: a tile is arithmetic (about
    80 ms for 129² points over a world with relief, water and twenty plots —
    measured 2026-08-21, up from a couple of milliseconds before E1, which is
    the price of a per-point function instead of a per-area raster sweep),
    while a stored one would need its own validity token, its own migration
    and its own way of going stale.

    **The returned dict is SHARED — treat it as read-only**, exactly like
    :func:`get_field`'s.
    """
    key = (_GENERATION, int(tx), int(tz))
    tile = _TILES.get(key)
    if tile is not None:
        try:
            _TILES.move_to_end(key)
        except KeyError:
            # Another thread evicted the entry between the lookup and this
            # line — two batch requests can each push 64 tiles through the
            # LRU at once. We already hold the tile, so the ANSWER is right;
            # only its place in the order is lost, which costs a re-raster
            # later. A lock around the whole cache would buy nothing else and
            # would sit on the walk-report path.
            pass
        return tile
    tile = rasterize_tile(int(tx), int(tz), (), model=world_model())
    _TILES[key] = tile
    while len(_TILES) > TILE_CACHE_MAX:
        _TILES.popitem(last=False)
    return tile


def tile_stats(tx: int, tz: int) -> Dict[str, Any]:
    """The pyramid statistics of one tile, cached per generation (§ G2).

    ``{"min", "max", "err": [one per MIP level]}`` — see
    :func:`tile_stats_from`. A tile outside the index answers a flat zero
    record without rastering anything, exactly as :func:`world_height` answers
    0 there.
    """
    global _TILE_STATS
    cached = _TILE_STATS
    if cached is None or cached[0] != _GENERATION:
        cached = (_GENERATION, {})
        _TILE_STATS = cached
    key = (int(tx), int(tz))
    stats = cached[1].get(key)
    if stats is None:
        if key not in tile_index():
            stats = {"min": 0.0, "max": 0.0,
                     "err": [0.0] * len(MIP_LEVELS_M)}
        else:
            stats = tile_stats_from(get_tile(key[0], key[1]))
        cached[1][key] = stats
    return stats


def world_height(x: float, z: float) -> float:
    """Height of the world ground at (x, z) — what ``ground_y`` answers.

    THE RULES READ TILES (v2, 2026-08-14), never the overview: this is the one
    function the walking gate, the router and every skill go through, and the
    overview may stand at a 32 m step, where a hill is a slope nobody authored
    and a 22 m patch of relief does not exist at all.

    Three lines, and the first one is the cheap answer: a point in no indexed
    tile is the flat world, which is most of the world (:func:`tile_index`).
    Otherwise the tile is fetched — a dict lookup, or a few milliseconds of
    rastering once — and read bilinearly, the very rule the overview is read
    with. The tile covers its whole square INCLUDING the seams, so the clamp in
    :func:`sample_height` never fires for a point inside it.
    """
    key = tile_key(x, z)
    if key not in tile_index():
        return 0.0
    return sample_height(get_tile(*key), x, z)


# ── The payload: the index list and the tile batch ──────────────────────

#: Tiles one batch request may ask for. 64 tiles are 4 km² of fine ground —
#: more than the client's own load radius ever wants at once — and they cost a
#: few hundred milliseconds to raster from cold. The cap is what keeps a
#: hand-written query from turning one request into a full-world raster; a
#: client that needs more asks twice.
TILE_BATCH_MAX = 64


def format_tile_key(tx: int, tz: int) -> str:
    """A tile key as it appears IN A PAYLOAD: ``"tx,tz"``.

    Deliberately not the form the QUERY uses (``tx:tz``, see
    :func:`parse_tile_keys`) — a comma separates the keys from each other
    there, so a comma inside one would need escaping. Both forms are written
    down in § A16.3.
    """
    return f"{tx},{tz}"


def _parse_tile_token(token: str) -> Optional[Tuple[int, int]]:
    """One ``"tx:tz"`` token, or None when it is not one.

    The whole rule of the query format in one place, so the parser and the
    junk-token list of the route cannot disagree about what is readable.
    Exactly one colon, an integer on each side — a float, a name, a missing
    half and a second colon are all "not a tile key".
    """
    parts = token.split(":")
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def parse_tile_keys(raw: str, cap: int = TILE_BATCH_MAX
                    ) -> List[Tuple[int, int]]:
    """The ``keys=tx:tz,tx:tz`` query of the tile batch — pure, no DB.

    FORGIVING BY DESIGN, like every reader of a free-text field here: an
    unreadable token is SKIPPED rather than failing the request, because the
    tiles a client did name are still the ground it is missing, and a batch
    that answers nothing turns one typo into a flat world. What is dropped is
    said once, by the route (§ A16.3, the ``backdrop.py`` pattern).

    Duplicates collapse to their FIRST position — a client that asks for the
    same tile twice gets it once, and the order it asked in survives, which is
    the order the cap then cuts at: :data:`TILE_BATCH_MAX` keys AFTER the
    dedupe, so a repeated key cannot push a distinct one out of the batch.
    A ``cap`` of 0 does not cut at all — that is how :func:`overflow_tile_keys`
    asks what the cap threw away.
    """
    out: List[Tuple[int, int]] = []
    seen = set()
    for token in str(raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        key = _parse_tile_token(token)
        if key is None or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if 0 < cap <= len(out):
            break
    return out


def unusable_tile_tokens(raw: str) -> List[str]:
    """The tokens of a ``keys=`` query that are NOT tile keys.

    The other half of :func:`parse_tile_keys`, and it exists because the parser
    stays silent: a client asking with the wrong separator gets an empty batch
    and a flat world, which looks exactly like "there is no ground there". The
    route says so once. An EMPTY token is not listed — a trailing comma is a
    typo without consequence, not a misunderstanding of the format.
    """
    return [token for token in
            (t.strip() for t in str(raw or "").split(","))
            if token and _parse_tile_token(token) is None]


def overflow_tile_keys(raw: str, cap: int = TILE_BATCH_MAX
                       ) -> List[Tuple[int, int]]:
    """The distinct keys of a query that the CAP cut off, in order.

    The third reader of the same parse (:func:`parse_tile_keys` with the cap
    switched off, ``cap`` 0 = do not cut), and it exists for the same reason
    :func:`unusable_tile_tokens` does: what the batch silently does not answer
    is what a client then draws as flat ground. 100 keys in, 64 out, and the
    36 missing tiles look exactly like a world without a hill in it — so the
    route says once that they were dropped, and the client's own load policy
    is the fix (ask twice), not a bigger cap.
    """
    return parse_tile_keys(raw, cap=0)[cap:] if cap > 0 else []


def tile_index_keys() -> List[str]:
    """The indexed tiles as payload keys, sorted by ``tx``, then ``tz``.

    THE INDEX IS THE CLIENT'S MAP OF THE GROUND: it names every tile that can
    carry a height, so a client only ever asks for tiles that exist and treats
    everything else as the flat world without a round trip. Sorted because a
    payload that reorders itself between two identical worlds is a diff nobody
    can read.
    """
    return [format_tile_key(tx, tz) for tx, tz in sorted(tile_index())]


def tiles_payload(keys: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    """The batch payload of ``GET /play/heightfield/tiles`` (§ A16.3).

    ONLY INDEXED TILES COME BACK. A key outside :func:`tile_index` is left out
    — not an error, not an empty grid: the index already told the client that
    everything else is flat, so a missing entry is that same statement and
    costs neither a raster nor a kilobyte. That also makes the endpoint safe to
    ask with a stale index; the answer is simply smaller than the question.

    THE SIGNATURE IS READ FIRST, before a single tile is rastered, and that
    order matters: an authoring write landing mid-request then makes the client
    hold tiles NEWER than the signature they arrived with, which the next poll
    corrects. The other way round it would hold stale tiles labelled current.
    """
    sig = current_sig()
    index = tile_index()
    tiles: Dict[str, Any] = {}
    for tx, tz in keys:
        if (tx, tz) not in index:
            continue
        tile = get_tile(tx, tz)
        # The tile's own fields, minus its ``step_m``: every tile in a batch
        # has the same one and it stands at the top level.
        tiles[format_tile_key(tx, tz)] = {
            "origin_x": tile["origin_x"], "origin_z": tile["origin_z"],
            "rows": tile["rows"], "cols": tile["cols"],
            "heights": tile["heights"],
            # …and what a CDLOD renderer needs to pick a level for it (§ G2).
            # It rides HERE because the tile is already rastered: asking for
            # the statistics of a tile nobody loaded is what costs.
            "stats": tile_stats(tx, tz),
        }
    return {"sig": sig, "tile_m": TILE_M, "step_m": TILE_STEP_M,
            "mip_levels_m": list(MIP_LEVELS_M), "tiles": tiles}


def stats_payload(keys: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    """The STATISTICS of the named tiles, without their grids (§ G2).

    The other half of :data:`TILE_STATS_MAX`. The overview ships the first
    64 tiles' statistics and says so (``tile_stats_complete``); everything past
    that used to arrive only with the tile itself, so a client that draws the
    whole world from a quadtree — where the worst error per LEVEL is taken over
    every tile it knows a statistic for — underestimated that maximum on any
    world with more than 64 tiles and drew the distant ground too coarse until
    those tiles happened to be loaded. This endpoint lets it ask for the rest.

    Same rules as :func:`tiles_payload`, for the same reasons: only indexed
    tiles come back (an unindexed one IS the flat world and needs no answer),
    and THE SIGNATURE IS READ FIRST, before a single tile is rastered, so a
    client can never hold statistics labelled newer than the raster they were
    read off.

    A tile whose statistic is not cached yet costs a raster (~90 ms), which is
    why the route caps the batch — but the raster lands in the process LRU, so
    the tile's own request afterwards is a cache hit and the bill is paid once.
    """
    sig = current_sig()
    index = tile_index()
    return {"sig": sig,
            "tile_stats": {format_tile_key(tx, tz): tile_stats(tx, tz)
                           for tx, tz in keys if (tx, tz) in index}}


#: How many tiles the OVERVIEW payload carries statistics for. Every one of
#: them has to be rastered (the numbers are read off the finished 129² array),
#: so this is a WORK budget for one request and not a payload one — the whole
#: block is about 5 kB.
#:
#: 64 tiles are 4 km² of fine ground and cost about six seconds from cold
#: (measured 2026-08-21, ~90 ms per tile). That work is not extra: the tiles
#: land in the process LRU, so every ``/play/heightfield/tiles`` batch after it
#: is a cache hit — it is the same bill, paid on the one request that is
#: already only made when the height signature changes. Half of
#: :data:`TILE_CACHE_MAX`, so filling it cannot evict what it just built. Past
#: the cap a client gets the rest with the tiles it actually asks for
#: (:func:`tiles_payload`), and ``tile_stats_complete`` says so.
TILE_STATS_MAX = 64


def water_profile_payload(profile: WaterProfile) -> Dict[str, Any]:
    """One :class:`WaterProfile` as the numbers a client reads (W1, W4a).

    Everything ``water_level_at`` needs and nothing else, so a renderer builds
    the same mirror the bake carved against — per vertex, without asking the
    server for a raster. ``flow_dir_deg`` is ``None`` for still water, and then
    ``s_min == s_max`` and both levels are equal: the reader's own clamp
    answers ``level_up`` everywhere without a special case.

    ``axis`` is the TRUTH since W4a: the knots ``[x, z, s, level]`` in flow
    order, one for still water and two for a straight river. The nine numbers
    beside it stay what they were — the best single tilted plane — for a reader
    that has not learned the polyline yet.
    """
    return {"level_up": round(profile.level_up, 3),
            "level_down": round(profile.level_down, 3),
            "flow_dir_deg": (None if profile.flow_dir_deg is None
                             else round(profile.flow_dir_deg, 3)),
            "axis_x": round(profile.axis_x, 3),
            "axis_z": round(profile.axis_z, 3),
            "dir_x": round(profile.dir_x, 6),
            "dir_z": round(profile.dir_z, 6),
            "s_min": round(profile.s_min, 3),
            "s_max": round(profile.s_max, 3),
            "axis": [[round(kx, 3), round(kz, 3), round(ks, 3),
                      round(level, 3)]
                     for kx, kz, ks, level in profile.axis]}


def with_effective_water_level(areas: Sequence[Dict[str, Any]]
                               ) -> List[Dict[str, Any]]:
    """Copies of the painted areas carrying the bake's water OUTPUT —
    ``meta.water_level_effective``, ``meta.water_depth_effective`` and
    ``meta.water_profile``.

    THE EFFECTIVE LEVEL IS OUTPUT, not authoring (E1b). ``meta.water_level`` is
    the author's field and may be unset ("auto (rim)"); this is the number the
    bake actually carved with, so the editor can show it without guessing and
    without a second implementation of the rim median. Where the author DID set
    a level the two are equal, which is the point — one field to read, whatever
    the author chose.

    SINCE W1 IT IS THE MID LEVEL OF THE PROFILE, i.e. the mean of the two ends —
    which for still water is still exactly the mirror it always was, and for a
    river is the level at the middle of its own axis. That choice is deliberate:
    the field is what a FLAT-mirror consumer draws one plane at, and the middle
    is the plane that misses a tilted river by the least on both ends. A
    consumer that wants the truth reads ``water_profile`` beside it and
    evaluates :func:`water_level_at`.

    ``water_depth_effective`` IS THE SAME KIND OF ANSWER FOR THE BED (W4b): the
    depth the carve really used, i.e. the kind's default with this area's own
    override applied and clamped. The renderer needs it because how opaque a
    water is drawn is ¾ of its depth — a shallow river and a deep lake do not
    fade in over the same metres — and resolving kind-versus-area a second time
    in a client is exactly the double bookkeeping ``water_level_effective``
    exists to prevent.

    Only water areas gain the keys; every other area is passed through as it is.
    Nothing is written back to the DB, and the input list is not mutated.
    """
    model = world_model()
    profiles = model.water_profile_by_area
    if not profiles:
        return list(areas or [])
    depths = model.water_depth_by_area
    out: List[Dict[str, Any]] = []
    for area in (areas or []):
        area_id = str(area.get("id") or "")
        profile = profiles.get(area_id)
        if profile is None:
            out.append(area)
            continue
        meta = dict(area.get("meta") or {})
        meta["water_level_effective"] = round(
            (profile.level_up + profile.level_down) * 0.5, 3)
        depth = depths.get(area_id)
        if depth is not None:
            meta["water_depth_effective"] = round(depth, 3)
        meta["water_profile"] = water_profile_payload(profile)
        out.append({**area, "meta": meta})
    return out


def index_stats_payload() -> Dict[str, Any]:
    """The pyramid block of ``GET /play/heightfield`` (§ G2).

    ``mip_levels_m`` names the levels, ``tile_stats`` carries ``min``/``max``
    and one error per level for the indexed tiles, in the sorted order of the
    index, and ``tile_stats_complete`` says whether that is all of them.

    IT IS ADDITIVE. A client that only reads the overview grid (everything
    before E2) sees the same fields it always saw; a CDLOD client reads this
    and knows, per tile and per level, how many metres it buys by drawing
    coarser — which is the one number the water invariant of § G4 is stated
    against.
    """
    keys = sorted(tile_index())
    capped = keys[:TILE_STATS_MAX]
    return {
        "mip_levels_m": list(MIP_LEVELS_M),
        "tile_stats": {format_tile_key(tx, tz): tile_stats(tx, tz)
                       for tx, tz in capped},
        "tile_stats_complete": len(capped) == len(keys),
    }
