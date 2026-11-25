#!/usr/bin/env python3
"""Smoke run for the cheaper, budgeted nav-grid search (2026-11-25).

Runs against a THROWAWAY storage directory and HAND-BUILT nav contexts — it
never reads a world. Background: a wanderer route across the world
(4.6 km) ran 2076 s inside ``nav_grid._astar`` and a second one more than
13 minutes, starving the whole server process. Two fixes are checked here:

* the per-cell work got cheaper WITHOUT changing an answer
  (``terrain_query.AreaIndex`` instead of a ray cast over every painted area
  per point, box rejects before the placed-boundary ray casts, per-search
  memos of the cell height and pace);
* the search got a BUDGET (closed cells and wall time) and yields the GIL.

Rules every expectation below is derived from BY HAND:

  * ``kind_at``: the LAST painted area (paint order) whose polygon contains
    the point wins; an area with a malformed vertex or fewer than three
    vertices contains nothing; no hit -> the default kind.
  * Grid: NAV_CELL_M = 2, cell i covers [2i, 2i+2), centre 2i+1.
  * A* step cost = metres / factor (+ climb, flat here), heuristic = octile
    distance x 2 m / best factor. The open heap is ordered by (f, push
    counter).

Hand-derived expectations:

  [1] Kinds over the hand-painted areas (paint order A..H, default "meadow"):
        A grass  square (0,0)-(40,40)
        B deep_water square (10,10)-(30,30)            (over A)
        C rock L-shape (50,0)(70,0)(70,10)(60,10)(60,30)(50,30)
        D broken (a vertex "x")                        -> never contains
        E two vertices only                            -> never contains
        F path strip (0,100)-(300,104), five 64 m buckets wide
        G sand triangle (25,25)(45,25)(25,45)          (over A and B)
        H grass island (14,14)-(18,18)                 (over B)
      (5,5)     -> grass       inside A only
      (20,20)   -> deep_water  inside A and B, B painted later
      (16,16)   -> grass       H painted over B
      (27,27)   -> sand        inside G (x>=25, z>=25, x+z=54<=70), G over B
      (55,20)   -> rock        the L's tall arm x 50..60, z 0..30
      (65,20)   -> meadow      the L's notch (x 60..70, z 10..30) is outside
      (150,102) -> path        F, in the third bucket of the strip
      (-1,-1)   -> meadow      no area
      ...and over a 0.5 m lattice of x -5..305, z -5..110 (621 x 231 =
      143 451 points, every vertex and edge of the scene included) the index
      answers exactly what a plain "last containing area wins" loop answers:
      0 differences.

  [2] Routes over the same scene plus a hill and three placed boundaries
      (catalog grass 1.0, meadow 1.0, sand 0.85, path 1.2, deep_water and
      rock impassable). The reference is an A* written out in THIS file
      from the documented rules on the raw primitives (no index, no memo,
      no box reject): for each pair the cell chain of ``nav_grid._astar``
      equals the reference chain cell for cell, and ``route`` over the real
      context equals ``route`` over a context whose terrain lookup is the
      plain loop of [1]. The island goal (16,16) lies in grass ringed by
      4 m of deep water on every side: no route, both ways.

  [3] The budget, on an EMPTY flat world (no areas, factor 1.0 everywhere).
      Start (1,1) = cell (0,0), goal (21,1) = cell (10,0). A line cell (k,0)
      has g = 2k and h = 2(10-k), so f = 20.0 exactly; any off-line cell has
      f >= 2(k-1) + 2*sqrt2 + 2(10-k) + 2(sqrt2-1) = 21.657 > 20. The search
      therefore closes cells (0,0)..(9,0) — 10 expansions — and pops the goal
      as the 11th. So:
        max_expansions=10 -> the route [(1,1), (21,1)], 10 expansions;
        max_expansions=9  -> None, ONE warning naming "expansion budget 9".
      Goal (201,1) = cell (100,0) needs 100 expansions; with max_seconds=0
      the clock is first read at expansion NAV_YIELD_EVERY = 64 -> None after
      exactly 64 expansions, ONE warning naming "time budget". Without a
      budget that walk yields the GIL once per 64 expansions: 100 // 64 = 1
      sleep(0). The island goal of [2] with max_expansions=500 -> None after
      exactly 500 expansions (the reachable part of the box is larger).

  [4] The time budget measures the SEARCH'S OWN WORK (CPU time of its
      thread), not the wall clock: a search that waits for the GIL while
      another thread computes must not run out of time for that. Hand-built
      clock, same 100-expansion walk to (201,1) as in [3], max_seconds=1:
        * the wall clock jumps 1000 s per read, the thread clock stands at 0
          (a starved search): the clock is read at expansion 64 only (64 is
          the one multiple of 64 below 100), CPU time 0 <= 1 -> the route
          [(1,1), (201,1)] after 100 expansions, no warning;
        * the thread clock jumps 1000 s per read (a search that really
          works): first read at the start = 0, the read at expansion 64
          = 1000 > 1 -> None after exactly 64 expansions, ONE warning naming
          "time budget 1 s".

Usage:  ./.venv/bin/python scripts/smoke_nav_budget.py
"""
import heapq
import itertools
import logging
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="nav-budget-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="nav-budget-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)

from app.core import nav_grid, terrain_query  # noqa: E402
from app.core.relief import slope_blocks  # noqa: E402
from app.core.world_geometry import point_in_polygon, polygon_hits_aabb  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    if actual == expected:
        print(f"  ✓ {label}: {actual!r}")
    else:
        FAILURES.append(label)
        print(f"  ✗ {label}: got {actual!r}, expected {expected!r}")


# ── [1] kinds ────────────────────────────────────────────────────────────

def sq(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


AREAS = [
    {"kind": "grass", "polygon": sq(0, 0, 40, 40)},
    {"kind": "deep_water", "polygon": sq(10, 10, 30, 30)},
    {"kind": "rock", "polygon": [[50, 0], [70, 0], [70, 10], [60, 10],
                                 [60, 30], [50, 30]]},
    {"kind": "rock", "polygon": [[0, 60], ["x", 60], [10, 70]]},
    {"kind": "rock", "polygon": [[0, 80], [10, 80]]},
    {"kind": "path", "polygon": sq(0, 100, 300, 104)},
    {"kind": "sand", "polygon": [[25, 25], [45, 25], [25, 45]]},
    {"kind": "grass", "polygon": sq(14, 14, 18, 18)},
]
DEFAULT = "meadow"


def ref_ray(x, z, pts):
    """Ray casting written out once more, on its own."""
    inside = False
    n = len(pts)
    for i in range(n):
        xi, zi = pts[i]
        xj, zj = pts[i - 1]
        if (zi > z) != (zj > z):
            if x < (xj - xi) * (z - zi) / (zj - zi) + xi:
                inside = not inside
    return inside


def ref_kind(x, z):
    hit = ""
    for area in AREAS:
        try:
            pts = [(float(p[0]), float(p[1])) for p in area["polygon"]]
        except (TypeError, ValueError):
            continue
        if len(pts) >= 3 and ref_ray(x, z, pts):
            hit = area["kind"]
    return hit or DEFAULT


print("[1] kinds through the prepared index")
INDEX = terrain_query.AreaIndex(AREAS)
for pt, want in [((5, 5), "grass"), ((20, 20), "deep_water"),
                 ((16, 16), "grass"), ((27, 27), "sand"),
                 ((55, 20), "rock"), ((65, 20), "meadow"),
                 ((150, 102), "path"), ((-1, -1), "meadow")]:
    check(f"kind at {pt}", terrain_query.kind_at(*pt, default_kind=DEFAULT,
                                                 index=INDEX), want)
points = 0
diffs = []
for ix in range(-10, 611):
    for iz in range(-10, 221):
        x, z = ix * 0.5, iz * 0.5
        points += 1
        got = terrain_query.kind_at(x, z, default_kind=DEFAULT, index=INDEX)
        if got != ref_kind(x, z):
            diffs.append((x, z))
check("lattice points compared", points, 143451)
check("lattice differences index vs plain loop", diffs[:5], [])


# ── [2] routes ───────────────────────────────────────────────────────────

CATALOG = {
    "grass": {"passable": True, "speed_factor": 1.0},
    "meadow": {"passable": True, "speed_factor": 1.0},
    "sand": {"passable": True, "speed_factor": 0.85},
    "path": {"passable": True, "speed_factor": 1.2},
    "deep_water": {"passable": False, "speed_factor": 0.4},
    "rock": {"passable": False, "speed_factor": 0.0},
}
# A hill around (100, 30): 1.5 m of rise per metre near the top — steeper
# than the 40 degree limit, so the top is sealed and the flanks are not.
STEP = 4.0
COLS, ROWS = 46, 20
HEIGHTS = [[max(0.0, 24.0 - 1.5 * math.hypot(i * STEP - 100.0, j * STEP - 30.0))
            for i in range(COLS)] for j in range(ROWS)]
FIELD = {"origin_x": 0.0, "origin_z": 0.0, "step_m": STEP, "rows": ROWS,
         "cols": COLS, "heights": HEIGHTS}


def region(lid, pts, is_area, built):
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    area = (max(xs) - min(xs)) * (max(zs) - min(zs))
    return nav_grid.Region(lid=lid, points=tuple(pts),
                           bounds=(min(xs), min(zs), max(xs), max(zs)),
                           area_m2=area, is_area=is_area, built_floor=built)


REGIONS = [
    region("house", ((80.0, 40.0), (90.0, 40.0), (90.0, 50.0), (80.0, 50.0)),
           False, True),
    region("village", ((120.0, 0.0), (140.0, 0.0), (140.0, 20.0),
                       (120.0, 20.0)), True, False),
    region("hall", ((150.0, 40.0), (160.0, 40.0), (160.0, 50.0),
                    (150.0, 50.0)), False, True),
]


def make_ctx(cls=nav_grid.NavContext):
    return cls(areas=AREAS, catalog=CATALOG, regions=REGIONS,
               data_bounds=nav_grid._data_bounds(AREAS, REGIONS),
               sig=("hand", "hand"), default_kind=DEFAULT, best_factor=1.2,
               height_field=FIELD, openings=(), max_step_m=0.4,
               max_slope_deg=40.0)


class PlainLoopCtx(nav_grid.NavContext):
    """The terrain lookup as the plain loop of [1] — no index."""

    def terrain_at(self, x, z):
        entry = CATALOG[ref_kind(x, z)]
        return bool(entry["passable"]), float(entry["speed_factor"])


def ref_astar(ctx, start, goal, s_cell, g_cell):
    """A* from the documented rules, on raw primitives only."""
    c = nav_grid.NAV_CELL_M
    exempt = [r for r in REGIONS
              if point_in_polygon(start[0], start[1], r.points)
              or point_in_polygon(goal[0], goal[1], r.points)]
    blocking = [r for r in REGIONS if r not in exempt]
    min_x, min_z, max_x, max_z = nav_grid._route_bounds(ctx, start, goal)
    lo = nav_grid.cell_of(min_x, min_z)
    hi = nav_grid.cell_of(max_x, max_z)

    def centre(cell):
        return ((cell[0] + 0.5) * c, (cell[1] + 0.5) * c)

    def h(cell):
        return ctx.height_at(*centre(cell))

    def in_any(x, z, regs):
        return any(point_in_polygon(x, z, r.points) for r in regs)

    def steep(cell):
        cx, cz = centre(cell)
        if in_any(cx, cz, [r for r in exempt if r.built_floor]):
            return False
        dx = ctx.height_at(cx + c, cz) - ctx.height_at(cx - c, cz)
        dz = ctx.height_at(cx, cz + c) - ctx.height_at(cx, cz - c)
        return slope_blocks(math.hypot(dx, dz), 2 * c, 0.4, 40.0)

    def blocked(cell):
        if not (lo[0] <= cell[0] <= hi[0] and lo[1] <= cell[1] <= hi[1]):
            return True
        box = (cell[0] * c, cell[1] * c, (cell[0] + 1) * c, (cell[1] + 1) * c)
        if any(polygon_hits_aabb(r.points, *box) for r in blocking):
            return True
        cx, cz = centre(cell)
        if CATALOG[ref_kind(cx, cz)]["passable"]:
            return steep(cell)
        return not in_any(cx, cz, exempt) or steep(cell)

    def factor(cell):
        cx, cz = centre(cell)
        best = None
        for r in exempt:
            if point_in_polygon(cx, cz, r.points) and (
                    best is None or r.area_m2 < best.area_m2):
                best = r
        scope = terrain_query.ground_scope(
            None if best is None else best.is_area, None)
        return terrain_query.effective_speed_factor(
            float(CATALOG[ref_kind(cx, cz)]["speed_factor"]), scope)

    def heur(cell):
        dx = abs(cell[0] - g_cell[0])
        dz = abs(cell[1] - g_cell[1])
        return c * (max(dx, dz) + (math.sqrt(2.0) - 1.0) * min(dx, dz)) / 1.2

    counter = itertools.count()
    heap = [(heur(s_cell), next(counter), s_cell)]
    came, g, closed = {}, {s_cell: 0.0}, set()
    while heap:
        _f, _n, cell = heapq.heappop(heap)
        if cell in closed:
            continue
        if cell == g_cell:
            path = [cell]
            while cell in came:
                cell = came[cell]
                path.append(cell)
            return path[::-1]
        closed.add(cell)
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nxt = (cell[0] + di, cell[1] + dj)
            if nxt in closed or blocked(nxt):
                continue
            if di and dj:
                if blocked((cell[0] + di, cell[1])) or \
                        blocked((cell[0], cell[1] + dj)):
                    continue
                step = c * math.sqrt(2.0)
            else:
                step = c
            cost = g[cell] + step / factor(nxt) + 4.0 * abs(h(nxt) - h(cell))
            if cost < g.get(nxt, math.inf):
                g[nxt] = cost
                came[nxt] = cell
                heapq.heappush(heap, (cost + heur(nxt), next(counter), nxt))
    return None


print("[2] routes: the cheaper search against the plain reference")
CTX = make_ctx()
PLAIN = make_ctx(PlainLoopCtx)
PAIRS = [((2.0, 2.0), (38.0, 38.0)),       # around the lake, over the sand
         ((60.0, 50.0), (110.0, 30.0)),    # onto the hill flank
         ((125.0, 10.0), (155.0, 45.0)),   # village (open) -> hall (built)
         ((40.0, 70.0), (95.0, 45.0)),     # past the house
         ((5.0, 102.0), (295.0, 102.0)),   # along the path strip
         ((2.0, 2.0), (16.0, 16.0))]       # the island: unreachable
for start, goal in PAIRS:
    search = nav_grid._Search(CTX, start, goal)
    s_cell = search.nearest_free(nav_grid.cell_of(*start))
    g_cell = search.nearest_free(nav_grid.cell_of(*goal))
    got = nav_grid._astar(search, s_cell, g_cell)
    want = ref_astar(CTX, start, goal, s_cell, g_cell)
    check(f"{start}->{goal}: cell chain equals the reference "
          f"({'none' if want is None else len(want)} cells)", got == want, True)
    check(f"{start}->{goal}: route equals the plain-loop route",
          nav_grid.route(start, goal, CTX) == nav_grid.route(start, goal, PLAIN),
          True)
check("the island stays unreachable", nav_grid.route((2.0, 2.0), (16.0, 16.0),
                                                     CTX), None)


# ── [3] budget ───────────────────────────────────────────────────────────

class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


CAP = Capture()
nav_grid.logger.addHandler(CAP)

FLAT = nav_grid.NavContext(areas=[], catalog=CATALOG, regions=[],
                           data_bounds=None, sig=("flat", "flat"),
                           default_kind="grass", best_factor=1.0)


def budget_run(goal, **kw):
    """route() plus the expansions its one search reported."""
    CAP.lines.clear()
    seen = {}
    real = nav_grid._astar

    def spy(search, s, g, **inner):
        out = real(search, s, g, **inner)
        seen["n"] = search.expansions
        return out

    nav_grid._astar = spy
    try:
        out = nav_grid.route((1.0, 1.0), goal, FLAT, **kw)
    finally:
        nav_grid._astar = real
    return out, seen.get("n"), list(CAP.lines)


print("[3] the search budget")
out, n, lines = budget_run((21.0, 1.0), max_expansions=10)
check("budget 10: the straight route", out, [(1.0, 1.0), (21.0, 1.0)])
check("budget 10: expansions", n, 10)
check("budget 10: no warning", lines, [])
out, n, lines = budget_run((21.0, 1.0), max_expansions=9)
check("budget 9: no route", out, None)
check("budget 9: expansions", n, 9)
check("budget 9: one warning", len(lines), 1)
check("budget 9: it names the budget",
      "expansion budget 9" in (lines or [""])[0], True)
out, n, lines = budget_run((201.0, 1.0), max_seconds=0.0)
check("time budget 0 s: no route", out, None)
check("time budget 0 s: expansions", n, nav_grid.NAV_YIELD_EVERY)
check("time budget 0 s: one warning naming it",
      [("time budget" in s) for s in lines], [True])


class SleepSpy:
    calls = []

    @staticmethod
    def monotonic():
        return 0.0

    @staticmethod
    def thread_time():
        return 0.0

    @staticmethod
    def sleep(s):
        SleepSpy.calls.append(s)


real_time = nav_grid.time
nav_grid.time = SleepSpy
try:
    out, n, lines = budget_run((201.0, 1.0))
finally:
    nav_grid.time = real_time
check("100 expansions: the route", (out, n), ([(1.0, 1.0), (201.0, 1.0)], 100))
check("100 expansions: the GIL is yielded once", SleepSpy.calls, [0])

CAP.lines.clear()
island = nav_grid._Search(CTX, (2.0, 2.0), (16.0, 16.0))
none = nav_grid._astar(island, nav_grid.cell_of(2.0, 2.0),
                       nav_grid.cell_of(16.0, 16.0), max_expansions=500)
check("island with budget 500: no route", none, None)
check("island with budget 500: expansions", island.expansions, 500)
check("island with budget 500: one warning", len(CAP.lines), 1)


print("[4] the time budget counts the search's own CPU time")


class Clock:
    """Wall and thread clocks that each advance a fixed step per read."""

    def __init__(self, wall_step, cpu_step):
        self.wall = 0.0
        self.cpu = 0.0
        self.wall_step = wall_step
        self.cpu_step = cpu_step

    def monotonic(self):
        now = self.wall
        self.wall += self.wall_step
        return now

    def thread_time(self):
        now = self.cpu
        self.cpu += self.cpu_step
        return now

    @staticmethod
    def sleep(_s):
        pass


for label, clock, want_out, want_n, want_warn in [
        ("starved (wall runs, CPU stands)", Clock(1000.0, 0.0),
         [(1.0, 1.0), (201.0, 1.0)], 100, []),
        ("busy (CPU runs)", Clock(0.0, 1000.0), None, 64,
         ["time budget 1 s"])]:
    nav_grid.time = clock
    try:
        out, n, lines = budget_run((201.0, 1.0), max_seconds=1.0)
    finally:
        nav_grid.time = real_time
    check(f"{label}: result", out, want_out)
    check(f"{label}: expansions", n, want_n)
    check(f"{label}: warnings", [w for w in want_warn
                                 if any(w in s for s in lines)]
          if lines else [], want_warn)
    check(f"{label}: warning count", len(lines), len(want_warn))

print()
if FAILURES:
    print(f"FAILED — {len(FAILURES)} of {CHECKED} checks:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
