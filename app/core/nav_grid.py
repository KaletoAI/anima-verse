"""Nav grid: A* over the painted metre world + string-pulling (E3).

Turns two world points into a walkable METRE POLYLINE. The grid used to
find it is an INTERNAL implementation detail — it never appears in a
payload, in the 3D contract or on a character profile. Callers see
metres: ``route()`` hands back waypoints, ``segment_costs()`` hands back
game-seconds per segment at 1 m/s, and the travel engine bakes those into
a journey.

The model in one paragraph: the world is rastered into ``NAV_CELL_M``
squares anchored at the origin (cell ``i`` covers ``[i*c, (i+1)*c)``, its
centre is ``(i + 0.5) * c``). A cell is blocked when the terrain AT ITS
CENTRE is impassable or when that centre lies inside a placed location
footprint that is FOREIGN to this route — the footprints containing the
start or the goal are exempt, otherwise nobody could ever leave or enter a
building. A* walks the 8 neighbours (no corner-cutting: a diagonal needs
both orthogonals free), paying ``distance / speed_factor`` for every step,
and the resulting cell chain is pulled straight again by a line-of-sight
pass so the journey follows the terrain instead of the raster.

Performance discipline (E1 review lesson): the terrain areas, the type
catalog and the placed footprints are read ONCE into a :class:`NavContext`
and every cell sample runs against that prefetched data — never a DB or
config round trip per cell. The context is cached on the terrain
signature plus a placement hash, so it survives every route that does not
change the world; :func:`invalidate_nav_cache` drops it.
"""

import hashlib
import heapq
import itertools
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.core.world_geometry import (footprint_corners, footprint_hits_aabb,
                                     placed_footprint, point_in_footprint,
                                     segment_hits_footprint)

Point = Tuple[float, float]
Cell = Tuple[int, int]

# Raster resolution in metres. 2 m is a body width: fine enough to squeeze
# between two buildings, coarse enough that a kilometre of world is a few
# hundred cells per axis.
NAV_CELL_M = 2.0

# The search box is the data bounding box (see :func:`_route_bounds`) grown
# by this margin, so a detour may leave the painted world a little without
# the grid running to infinity.
BOUNDS_MARGIN_M = 10.0

# How far the start/goal cell may be rescued when it is blocked itself
# (Chebyshev cells). An arrival point in front of a door touches the wall;
# without this the journey would fail on its last metre.
RESCUE_RADIUS_CELLS = 2

# Sampling step of the line-of-sight test used by the string-pulling.
# Half a cell: fine enough that no blocked cell can hide between two
# samples of a straightened segment.
LOS_STEP_M = NAV_CELL_M / 2.0

# Cost sampling step (:func:`segment_costs`): one sample per cell length.
COST_STEP_M = NAV_CELL_M

# Lower clamp on the speed factor used for COSTS. A terrain type may be
# configured passable with factor 0, and a rescued start may sit on
# impassable ground — neither may produce an infinite travel time.
MIN_SPEED_FACTOR = 0.1

_SQRT2 = math.sqrt(2.0)
_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1),
               (1, 1), (1, -1), (-1, 1), (-1, -1))


# ── context ─────────────────────────────────────────────────────────────

@dataclass
class NavContext:
    """One prefetched snapshot of everything routing needs.

    ``footprints`` are ``(location_id, cx, cz, width_m, yaw_deg)`` of the
    PLACED locations, ``data_bounds`` the bounding box over all footprint
    corners and area vertices (None for a world without either).
    """

    areas: List[Dict[str, Any]]
    catalog: Dict[str, Dict[str, Any]]
    footprints: List[Tuple[str, float, float, float, float]]
    data_bounds: Optional[Tuple[float, float, float, float]]
    sig: Tuple[str, str]
    # The ground of every unpainted point, resolved ONCE — the hot loop must
    # not read the config per sample.
    default_kind: str = "grass"
    # Best speed factor of the catalog (>= 1.0) — the A* heuristic divides
    # by it so it stays admissible on fast terrain.
    best_factor: float = 1.0
    # Cell centre -> (passable, speed_factor), filled lazily. Terrain only;
    # footprints are per route (their exemption depends on the endpoints).
    _terrain_cache: Dict[Cell, Tuple[bool, float]] = field(
        default_factory=dict, repr=False)

    def terrain_at(self, x: float, z: float) -> Tuple[bool, float]:
        """(passable, speed_factor) of a POINT, from prefetched data."""
        from app.core.terrain_query import passability_at
        return passability_at(x, z, areas=self.areas, catalog=self.catalog,
                              default_kind=self.default_kind)

    def cell_terrain(self, cell: Cell) -> Tuple[bool, float]:
        """Terrain of a CELL, sampled once at its centre and memoized."""
        hit = self._terrain_cache.get(cell)
        if hit is None:
            hit = self.terrain_at(*cell_centre(cell))
            self._terrain_cache[cell] = hit
        return hit


_CACHE: Optional[Tuple[Tuple[str, str], NavContext]] = None


def invalidate_nav_cache() -> None:
    """Drop the cached context (tests + world mutations)."""
    global _CACHE
    _CACHE = None


def _placement_sig(footprints: Sequence[Tuple[str, float, float, float,
                                              float]]) -> str:
    basis = json.dumps(sorted(footprints), sort_keys=True)
    return hashlib.md5(basis.encode()).hexdigest()[:10]


def build_nav_context() -> NavContext:
    """The current nav context — cached until the world changes.

    The cache key is ``(terrain.terrain_sig(), placement hash)``: the first
    covers painted areas + world terrain types, the second every placed
    footprint (position, size, yaw). Checking it costs one areas read and
    one world read; building it adds the catalog on top.
    """
    global _CACHE
    from app.models.terrain import list_areas, terrain_sig
    from app.models.world import list_locations

    footprints: List[Tuple[str, float, float, float, float]] = []
    for loc in list_locations():
        fp = placed_footprint(loc)
        if fp is None:
            continue
        cx, cz, width, yaw = fp
        footprints.append((str(loc.get("id") or ""), cx, cz, width, yaw))

    key = (terrain_sig(), _placement_sig(footprints))
    cached = _CACHE
    if cached is not None and cached[0] == key:
        return cached[1]

    from app.core.terrain_query import default_kind
    from app.core.terrain_types import effective_catalog
    areas = list_areas()
    catalog = effective_catalog()

    best = 1.0
    for entry in catalog.values():
        if entry.get("passable", True):
            best = max(best, float(entry.get("speed_factor", 1.0) or 1.0))

    ctx = NavContext(areas=areas, catalog=catalog, footprints=footprints,
                     data_bounds=_data_bounds(areas, footprints), sig=key,
                     default_kind=default_kind(), best_factor=best)
    _CACHE = (key, ctx)
    return ctx


def _data_bounds(areas: List[Dict[str, Any]],
                 footprints: Sequence[Tuple[str, float, float, float, float]]
                 ) -> Optional[Tuple[float, float, float, float]]:
    """Bounding box over all area vertices and footprint corners."""
    xs: List[float] = []
    zs: List[float] = []
    for area in areas:
        for pt in (area.get("polygon") or []):
            try:
                xs.append(float(pt[0]))
                zs.append(float(pt[1]))
            except (TypeError, ValueError, IndexError):
                continue
    for _lid, cx, cz, width, yaw in footprints:
        for x, z in footprint_corners(cx, cz, width, yaw):
            xs.append(x)
            zs.append(z)
    if not xs:
        return None
    return (min(xs), min(zs), max(xs), max(zs))


# ── grid math ───────────────────────────────────────────────────────────

def cell_of(x: float, z: float) -> Cell:
    """The cell a world point falls into (grid anchored at the origin)."""
    return (int(math.floor(x / NAV_CELL_M)), int(math.floor(z / NAV_CELL_M)))


def cell_centre(cell: Cell) -> Point:
    """World centre of a cell in metres."""
    return ((cell[0] + 0.5) * NAV_CELL_M, (cell[1] + 0.5) * NAV_CELL_M)


def cell_box(cell: Cell) -> Tuple[float, float, float, float]:
    """(min_x, min_z, max_x, max_z) of a cell square in metres."""
    return (cell[0] * NAV_CELL_M, cell[1] * NAV_CELL_M,
            (cell[0] + 1) * NAV_CELL_M, (cell[1] + 1) * NAV_CELL_M)


def _finite_point(raw: Any, label: str) -> Point:
    try:
        x, z = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError, KeyError, OverflowError):
        raise ValueError(f"{label} must be an (x, z) pair of numbers")
    if not (math.isfinite(x) and math.isfinite(z)):
        raise ValueError(f"{label} must be finite")
    return (x, z)


def _route_bounds(ctx: NavContext, start: Point,
                  goal: Point) -> Tuple[float, float, float, float]:
    """Search box: data bounds ∪ both endpoints, grown by the margin.

    A detour that would only exist further outside than the margin is not
    found — deliberate, the alternative is an unbounded grid.
    """
    xs = [start[0], goal[0]]
    zs = [start[1], goal[1]]
    if ctx.data_bounds is not None:
        min_x, min_z, max_x, max_z = ctx.data_bounds
        xs += [min_x, max_x]
        zs += [min_z, max_z]
    return (min(xs) - BOUNDS_MARGIN_M, min(zs) - BOUNDS_MARGIN_M,
            max(xs) + BOUNDS_MARGIN_M, max(zs) + BOUNDS_MARGIN_M)


class _Search:
    """Per-route view of the grid: bounds, exempt footprints, blocking."""

    def __init__(self, ctx: NavContext, start: Point, goal: Point):
        self.ctx = ctx
        # A footprint containing the start or the goal is exempt for THIS
        # route — a character standing in a house has to be able to walk
        # out of it, and arriving means walking in.
        self.exempt: Set[str] = set()
        for lid, cx, cz, width, yaw in ctx.footprints:
            if (point_in_footprint(start[0], start[1], cx, cz, width, yaw)
                    or point_in_footprint(goal[0], goal[1], cx, cz, width,
                                          yaw)):
                self.exempt.add(lid)
        self.blocking = [fp for fp in ctx.footprints
                         if fp[0] not in self.exempt]
        min_x, min_z, max_x, max_z = _route_bounds(ctx, start, goal)
        self.min_i, self.min_j = cell_of(min_x, min_z)
        self.max_i, self.max_j = cell_of(max_x, max_z)
        self._blocked: Dict[Cell, bool] = {}

    def in_bounds(self, cell: Cell) -> bool:
        return (self.min_i <= cell[0] <= self.max_i
                and self.min_j <= cell[1] <= self.max_j)

    def blocked(self, cell: Cell) -> bool:
        """A CELL is blocked by impassable terrain at its centre or by a
        foreign footprint OVERLAPPING it — cells outside the search box
        count as blocked so A* cannot wander off.

        Footprints are tested against the whole cell square, not against
        its centre: a building may cover most of a cell without touching
        the centre, and a step between two such cells would walk through
        the wall.
        """
        hit = self._blocked.get(cell)
        if hit is None:
            if not self.in_bounds(cell):
                hit = True
            else:
                box = cell_box(cell)
                hit = (not self.ctx.cell_terrain(cell)[0]
                       or any(footprint_hits_aabb(fcx, fcz, w, yaw, *box)
                              for _lid, fcx, fcz, w, yaw in self.blocking))
            self._blocked[cell] = hit
        return hit

    def factor(self, cell: Cell) -> float:
        return max(self.ctx.cell_terrain(cell)[1], MIN_SPEED_FACTOR)

    def nearest_free(self, cell: Cell) -> Optional[Cell]:
        """The cell itself, or the closest passable cell within
        ``RESCUE_RADIUS_CELLS`` (Chebyshev), or None."""
        if not self.blocked(cell):
            return cell
        best: Optional[Cell] = None
        best_d = 0.0
        for di in range(-RESCUE_RADIUS_CELLS, RESCUE_RADIUS_CELLS + 1):
            for dj in range(-RESCUE_RADIUS_CELLS, RESCUE_RADIUS_CELLS + 1):
                cand = (cell[0] + di, cell[1] + dj)
                if self.blocked(cand):
                    continue
                dist = math.hypot(di, dj)
                if best is None or dist < best_d:
                    best, best_d = cand, dist
        return best

    def line_clear(self, a: Point, b: Point) -> bool:
        """Whether the straight segment a→b is walkable.

        Foreign footprints are tested EXACTLY (segment vs. rotated
        rectangle) — sampling misses the sub-metre corner clip that a
        straightened segment produces. Terrain is sampled every
        ``LOS_STEP_M`` metres (both endpoints included), the same
        resolution the raster itself works at.
        """
        for _lid, cx, cz, width, yaw in self.blocking:
            if segment_hits_footprint(a[0], a[1], b[0], b[1], cx, cz, width,
                                      yaw):
                return False
        length = math.dist(a, b)
        steps = max(1, int(math.ceil(length / LOS_STEP_M)))
        for k in range(steps + 1):
            t = k / steps
            if not self.ctx.terrain_at(a[0] + (b[0] - a[0]) * t,
                                       a[1] + (b[1] - a[1]) * t)[0]:
                return False
        return True


# ── routing ─────────────────────────────────────────────────────────────

def _astar(search: _Search, start_cell: Cell,
           goal_cell: Cell) -> Optional[List[Cell]]:
    """8-neighbour A*; cost per step = metres / speed_factor of the entered
    cell, heuristic = octile distance / best catalog factor (admissible)."""
    if start_cell == goal_cell:
        return [start_cell]
    inv_best = 1.0 / max(search.ctx.best_factor, MIN_SPEED_FACTOR)

    def heuristic(cell: Cell) -> float:
        dx = abs(cell[0] - goal_cell[0])
        dz = abs(cell[1] - goal_cell[1])
        octile = NAV_CELL_M * (max(dx, dz) + (_SQRT2 - 1.0) * min(dx, dz))
        return octile * inv_best

    counter = itertools.count()
    open_heap = [(heuristic(start_cell), next(counter), start_cell)]
    came: Dict[Cell, Cell] = {}
    g_score: Dict[Cell, float] = {start_cell: 0.0}
    closed: Set[Cell] = set()

    while open_heap:
        _f, _n, cell = heapq.heappop(open_heap)
        if cell in closed:
            continue
        if cell == goal_cell:
            path = [cell]
            while cell in came:
                cell = came[cell]
                path.append(cell)
            path.reverse()
            return path
        closed.add(cell)
        base_g = g_score[cell]
        for di, dj in _NEIGHBOURS:
            nxt = (cell[0] + di, cell[1] + dj)
            if nxt in closed or search.blocked(nxt):
                continue
            if di and dj:
                # No corner-cutting: squeezing diagonally between two
                # blocked cells would walk through a wall.
                if (search.blocked((cell[0] + di, cell[1]))
                        or search.blocked((cell[0], cell[1] + dj))):
                    continue
                step = NAV_CELL_M * _SQRT2
            else:
                step = NAV_CELL_M
            tentative = base_g + step / search.factor(nxt)
            if tentative < g_score.get(nxt, math.inf):
                g_score[nxt] = tentative
                came[nxt] = cell
                heapq.heappush(open_heap,
                               (tentative + heuristic(nxt), next(counter),
                                nxt))
    return None


def _segment_cost(ctx: NavContext, a: Point, b: Point) -> float:
    """Game-seconds for one straight segment at 1 m/s — the sampling rule
    documented on :func:`segment_costs` (midpoints of ``n`` equal parts)."""
    length = math.dist(a, b)
    if length <= 0.0:
        return 0.0
    n = max(1, int(math.ceil(length / COST_STEP_M)))
    part = length / n
    total = 0.0
    for k in range(n):
        t = (k + 0.5) / n
        factor = max(ctx.terrain_at(a[0] + (b[0] - a[0]) * t,
                                    a[1] + (b[1] - a[1]) * t)[1],
                     MIN_SPEED_FACTOR)
        total += part / factor
    return total


def _dedupe(points: List[Point]) -> List[Point]:
    out: List[Point] = []
    for pt in points:
        if not out or math.dist(out[-1], pt) > 1e-9:
            out.append(pt)
    return out


def _smooth(search: _Search, points: List[Point]) -> List[Point]:
    """String-pulling: drop a waypoint when the straight line from its
    predecessor to its successor is walkable AND not more expensive than
    the two segments it replaces. Repeated until stable, so a corridor of
    cell centres collapses to the few real corners.

    The cost guard is what keeps A*'s terrain work: a shortcut is always
    SHORTER, but a shortcut through a swamp can still cost more time than
    the detour around it — a purely geometric string-pull would silently
    undo every detour the search made for a slow-but-passable area.
    """
    ctx = search.ctx
    out = list(points)
    changed = True
    while changed and len(out) > 2:
        changed = False
        i = 0
        while i + 2 < len(out):
            # line_clear first: it exits at the first blocked sample, while
            # the cost guard always samples the whole segment. In a maze
            # most candidates are blocked, so the order is worth an order
            # of magnitude.
            if search.line_clear(out[i], out[i + 2]):
                detour = (_segment_cost(ctx, out[i], out[i + 1])
                          + _segment_cost(ctx, out[i + 1], out[i + 2]))
                shortcut = _segment_cost(ctx, out[i], out[i + 2])
                # Relative epsilon: collinear points must still collapse
                # despite float noise in the sampling sums.
                if shortcut <= detour * (1.0 + 1e-9) + 1e-9:
                    del out[i + 1]
                    changed = True
                    continue
            i += 1
    return out


def route(start_xz: Any, goal_xz: Any,
          ctx: Optional[NavContext] = None) -> Optional[List[Point]]:
    """Walkable polyline from start to goal in world metres, or None.

    The first waypoint is always the real start point and the last the real
    goal point (a rescued endpoint keeps its true position — the character
    stands where it stands). Everything in between are the corners left
    after the line-of-sight smoothing. ``None`` means unreachable: no
    passable cell near an endpoint, or no route inside the search box.

    Resolution caveat: TERRAIN is judged at cell centres (and at 1 m
    samples along a smoothed segment), so a painted obstacle thinner than
    roughly a cell can slip between the samples — building footprints do
    not, they are tested exactly against the cell square and the segment.
    Sub-cell terrain detail is below what a 2 m raster can represent.
    """
    start = _finite_point(start_xz, "start")
    goal = _finite_point(goal_xz, "goal")
    if ctx is None:
        ctx = build_nav_context()
    search = _Search(ctx, start, goal)

    start_cell = search.nearest_free(cell_of(*start))
    goal_cell = search.nearest_free(cell_of(*goal))
    if start_cell is None or goal_cell is None:
        return None

    cells = _astar(search, start_cell, goal_cell)
    if cells is None:
        return None

    # Real endpoints + every cell centre; the smoothing throws away what the
    # straight line covers anyway (in an empty world: everything).
    points = _dedupe([start] + [cell_centre(c) for c in cells] + [goal])
    # Dedupe again: smoothing a start==goal route collapses to two identical
    # points, and "already there" must be ONE waypoint, not a zero-length
    # segment the journey engine would have to special-case.
    points = _dedupe(_smooth(search, points))
    return [(round(x, 2), round(z, 2)) for x, z in points]


def segment_costs(waypoints: Sequence[Point],
                  ctx: Optional[NavContext] = None) -> List[float]:
    """Game-seconds per segment at 1 m/s (Task 2 divides by the world speed).

    Sampling rule: a segment of length L is split into
    ``n = max(1, ceil(L / NAV_CELL_M))`` equal parts and the terrain factor
    is read at the MIDPOINT of each part (midpoints, not endpoints — a
    waypoint typically sits exactly on a terrain border, where the reading
    is a coin flip). The cost is the sum of ``(L / n) / factor``, i.e. the
    length divided by the harmonic mean of the sampled factors. Footprints
    do not matter here: a building has no speed, only ground does.
    """
    if ctx is None:
        ctx = build_nav_context()
    costs: List[float] = []
    for i in range(len(waypoints) - 1):
        a = _finite_point(waypoints[i], "waypoint")
        b = _finite_point(waypoints[i + 1], "waypoint")
        costs.append(_segment_cost(ctx, a, b))
    return costs
