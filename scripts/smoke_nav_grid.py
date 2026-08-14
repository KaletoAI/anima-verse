#!/usr/bin/env python3
"""Smoke run for the nav grid: A* routing + string-pulling + segment costs
(Seamless World, E3 Task 1).

Runs against a THROWAWAY storage directory — never touches a real world.

Grid rules used to derive every number below by hand:
  NAV_CELL_M = 2.0; cell index i = floor(x / 2), its centre is 2*i + 1
  (same for z), its square is [2*i, 2*i+2]. A cell is blocked when a
  FOREIGN placed footprint OVERLAPS the cell square (footprints containing
  the start or the goal are exempt), or when the TERRAIN at its centre is
  not passable AND that centre lies OUT IN THE WILDERNESS — inside a
  placed footprint the ground is not asked for the BLOCK (decision
  2026-08-13, case [12]). For the PACE it is asked as far as the sky reaches
  (finding 3 + the reach decision of round 2, case [16]): costs are
  game-seconds at 1 m/s, metres / speed_factor, the terrain counts out in the
  wilderness and inside an AREA location, and a BUILDING footprint pays the
  neutral 1.0 — as does a factor-0 ground inside an area location. Shared
  catalog: grass 1.0 · forest 0.7 · sand 0.85 · path 1.2 · water SWIMMABLE at
  0.4 · deep_water impassable at 0.4 · rock impassable at 0.0. (Water became
  swimmable in round 2 — the barrier cases below use `deep_water`, which
  carries exactly the numbers `water` used to have, so their arithmetic is
  unchanged.)

Hand-derived expectations:

  [1] Empty world (no areas, no locations). route((0,0), (20,0)):
      A* walks the cell row, string-pulling then drops every intermediate
      centre because the straight line (0,0)->(20,0) is grass all the way
      -> exactly [(0,0), (20,0)]. segment_costs -> [20.0]
      (20 m / factor 1.0 = 20 game-seconds).
      route((4,4), (4,4)) collapses to ONE waypoint, costs []: (4,4) is
      NOT a cell centre (its cell (2,2) is centred on (5,5)), so the raw
      point list is start/centre/goal and must survive smoothing as a
      single point. Non-finite coordinates raise ValueError.

  [2] Deep-water barrier x in [8,12], z in [-6,6] between the same two
      points.
      Its blocked cells are the centres 9/11 (i=4,5) and -5..5 (j=-3..2),
      so the grid barrier spans x [8,12] x z [-6,6] and the route has to
      round a corner at |z| >= 7: roughly (0,0) -> (7,-7) -> (13,-7) ->
      (20,0), about 9.9 + 6 + 9.9 = 25.8 m. Checked: route exists, every
      waypoint is passable, the whole polyline sampled every 0.3 m never
      touches the water, and the length is > the 20 m airline (and < 40 m).
      Repeating the call gives the IDENTICAL polyline (determinism), with
      and without a rebuilt context.

  [3] Path corridor x in [0,20], z in [98,102] (speed_factor 1.2).
      segment_costs([(0,100), (20,100)]) samples the midpoints of ten 2 m
      sub-segments (n = ceil(20 / 2)), all inside the corridor
      -> 20 / 1.2 = 16.6667 s. route over the corridor is the straight
      2-point line with the same cost.

  [4] Deep lake x in [100,140], z in [-20,20]; goal (120,0) sits 18 m deep
      inside it — far beyond the 2-cell (<= ~4 m) rescue radius
      -> route((0,0), (120,0)) is None.

  [5] Barn at (60,0), plan_width_m 10, yaw 0 -> footprint x [55,65],
      z [-5,5]:
      a) route((40,0), (80,0)): the barn is FOREIGN to both endpoints, so
         the route rounds it — no waypoint inside the footprint, NO
         SEGMENT intersecting it (exact segment-vs-rectangle test, not
         sampling), length > the 40 m airline.
      b) route((40,0), (60,0)): the goal lies inside the barn, so that
         footprint is exempt -> straight [(40,0), (60,0)], cost [20.0].
      c) route((60,0), (80,0)): same for a start inside the barn.

  [6] Rescue: deep-water patch x in [198,202], z in [-2,2]. The start (200,0)
      lies in it and its own cell centre (201,1) is blocked; the nearest
      passable cell (201,3) is 1 cell away, inside the 2-cell rescue
      radius -> route((200,0), (220,0)) exists, keeps (200,0) as its first
      waypoint (the character really stands there) and every LATER
      waypoint is passable. Costs stay finite: an impassable ground is paid
      at its own factor, clamped up at MIN_SPEED_FACTOR (deep water 0.4 here,
      rock would be the clamped 0.1) — leaving the puddle is slow, never
      infinite.

  [7] Slow terrain must survive the smoothing. Forest x in [40,60],
      z in [190,210] (factor 0.7), route (0,200) -> (100,200):
      the straight line is 100 m, 20 m of it forest
      -> 80/1.0 + 20/0.7 = 80 + 28.571 = 108.571 s.
      Rounding the forest on grass costs roughly
      2*sqrt(40^2 + 11^2) + 20 = 2*41.48 + 20 = 102.96 s (the crossing
      has to happen at |z-200| >= 11, the first free cell row).
      A cost-blind string-pull would replace the detour by the straight
      line (shorter, but 5.6 s slower) — so: > 2 waypoints and a total
      cost below the 108.571 s of the straight line.

  [8] The two geometry helpers, hand-derived (see their docstrings):
      segment_hits_footprint over the unit-ish square at (0,0) w 2 yaw 0
      -> (-5,0)->(5,0) True (enters at t=0.4), (-5,2)->(5,2) False.
      footprint_hits_aabb for (0,0) w 2 yaw 45 (corners at ±sqrt(2) on the
      axes) -> cell [0,2]x[0,2] True, cell [1,3]x[1,3] False.
      placed_footprint refuses a non-finite position.

  [9] Rotated footprint (the corner-cutting repro): mill at (500,0),
      plan_width_m 14, yaw 45 -> a diamond with corners at
      (500 ± 9.90, 0) and (500, ±9.90) (7*sqrt(2) = 9.90). The straight
      line (480,0)->(520,0) runs through its centre, so the route must
      round it: no segment may intersect the footprint (exact test) and
      the length must exceed the 40 m airline.

 [10] Diagonal squeeze: rock at x [300,302] z [300,302] (cell centre
      (301,301)) and x [302,304] z [302,304] (centre (303,303)) touch at
      the corner (302,302). route((301,303), (303,301)) may NOT step
      through that corner: both diagonal orthogonals are blocked, so the
      2.83 m airline is impossible and the route has to walk around one of
      the blocks (> 4.5 m).

 [11] Cache: build_nav_context() returns the SAME object twice;
      invalidate_nav_cache() forces a rebuild; painting an area (terrain
      signature) and moving a placed location (placement hash) each
      invalidate it on their own.

 [12] FOOTPRINT WINS (decision 2026-08-13, the routing half of the walking
      rule in `POST /play/pos`): painted terrain judges the WILDERNESS, not
      the inside of a placed location. Hall at (700,0), plan_width_m 20 ->
      footprint x [690,710], z [-10,10], with ROCK painted x [691,709],
      z [-9,9] — strictly inside it, so the approach from the west stays
      grass.
      a) The goal cell is cell_of(700,0) = (350,0), centred on (701,1) —
         rock, and inside the hall. For the route's OWN search (the hall
         contains the goal, so its footprint is exempt) that cell is FREE;
         for a foreign search — start and goal both outside, e.g.
         (670,0) -> (670,60) — it stays blocked, by the footprint's SAT
         test, exactly as before. route((670,0), (700,0)) therefore
         EXISTS, starts on (670,0) and ends on (700,0), inside the rock.
         Under the old rule it was None: every cell within the 2-cell
         rescue radius of the goal (centres x 697..705, z -3..5) is rock
         as well, so nearest_free found nothing and an NPC could not be
         sent to a place its avatar walks around in freely.
      b) THE PACE OF A FACTOR-0 GROUND goes with it: rock is 0.0, and a 0 is
         not a pace but a "this was never meant to be walked" — under a
         footprint it pays the neutral 1.0 (finding 3 keeps exactly this
         half of the old rule). So the route is the STRAIGHT
         [(670,0), (700,0)] and its cost is 30 m / 1.0 = 30 s: 15 samples
         of 2 m, midpoints x = 671 … 699, the ten outside on grass (1.0),
         the five from 691 on inside the hall (1.0 instead of the rock's
         clamped 0.1). Before that half the same rock cost 10 s per metre,
         A* hugged the rim instead of walking straight and the last leg
         alone came to 90.55 s — while the avatar walked that hall at full
         speed, two movement models over one square metre.
      c) The wilderness half is untouched: rock x [730,770], z [-20,20]
         with NO location on it, goal (750,0) sits 20 m deep inside it,
         far beyond the rescue radius -> route((670,0), (750,0)) is None.

 [13] TOO STEEP TO STAND ON (E8 task 4). A cell dies of the GROUND under it
      when the slope at its centre passes `game.max_slope_deg` — the very rule
      `POST /play/pos` walks by, measured as the CENTRAL difference over the
      two opposite neighbours per axis (run = 2 · NAV_CELL_M = 4 m; one-sided,
      the flat shore at the foot of a cliff would inherit the cliff).

      THE HILL: height area (2000,0)-(2040,40), height 5, falloff 4. On the
      origin-anchored lattice (step 4) the support points sit at x = 1996 + 4i,
      z = -4 + 4j, and at z = 20 the row reads 0 (1996), 0 (2000, ON the
      outline), 5 (2004, 4 m in), 5 … 5 (2036), 0 (2040), 0 (2044).
        cell (1000, 10) — centre (2001, 21):
            h(2003, 21) = 0·0.25 + 5·0.75 = 3.75   (tx = 0.75, both z rows
                                                    read the same)
            h(1999, 21) = 0
            h(2001, 23) − h(2001, 19) = 0          (the flank runs in x only)
            rise = 3.75 over 4 m -> atan(0.9375) = 43.15° > 40 -> BLOCKED
        cell centred (2021, 21) sits on the plateau: 5 against 5 -> free
        cell centred (1981, 21) is out on the flat: 0 against 0 -> free
      A 5 m plateau reached over a 4 m ramp is a wall on EVERY side (that is
      the authoring limit § A16 names: tan(40°)·4 = 3.36 m), so a route from
      (1960,20) to (2060,20) does not cross it — it goes round the whole hill,
      which is more than the straight 100 m.
      RED COUNTER-PROBE: with the hill deleted the same route is the straight
      [(1960,20), (2060,20)], length 100.

 [14] THE CLIMB IS PAID FOR (E8 task 4), and it is a PENALTY only — the
      heuristic knows nothing about the relief, so a downhill discount would
      make it overestimate and A* would stop being optimal.
      `SLOPE_COST_S_PER_M` = 4 game-seconds per metre of rise, up or down.

      THE RIDGE: height area (3100,0)-(3112,12), height 5, falloff 12, out in
      untouched grass (the earlier sections paint their own ground and a slow
      area would swamp the cost this one measures). Nothing inside is further
      than 6 m from the outline, so the ridge tops out at 5·6/12 = 2.5 m.
      `height_at` reads the 2 m TILE (since 2026-08-14; the `height_field` the
      shape check below names is the 4 m OVERVIEW, which the rule no longer
      asks), and the 2 m lattice CARRIES the crest: (3106, 6) is a support
      point, so the ridge really tops out at its authored 2.5 rather than at
      the 1.667 the 4 m lattice could reach. The steepest probe pair anywhere
      on it is 1.4736 m over the 4 m run, atan(0.3684) = 20.2° — well inside
      the limit, so NOTHING here is blocked and what is measured is the cost
      alone.

      THE STRAIGHT WAY OVER, (3106,-6) -> (3106,18): 24 m in 12 parts of 2 m,
      grass factor 1.0 -> 24 s of walking. x = 3106 IS a support column of the
      2 m lattice, so the profile is the authored ramp itself, 5 · d/12 at the
      distance d to the nearest outline, stored at three decimals:
        z:   -6  -4  -2   0     2      4     6     8      10    12 … 18
        h:    0   0   0   0  0.833  1.667  2.5  1.667  0.833    0
      The climb sums to the honest full rise, 2.5 up plus 2.5 down = 5 m, so
      the segment costs 24 + 4 · 5 = 44 s. (At the old 4 m step it was 37.336:
      the coarse lattice never reached the crest, so the route was charged for
      a hill lower than the one it walked over — one of the two disagreements
      the tiles exist to end.)
      AROUND AN END the ground is 0 (everything outside the outline is): a way
      round like (3106,-6) -> (3099,6) -> (3106,18) is 2 · hypot(7,12) =
      27.78 m and climbs nothing — cheaper than the 44 over the top, so
      the route BENDS and the string-pulling does not straighten it back (the
      shortcut it weighs carries the hill now, `_smooth`'s cost guard). WHICH
      end it takes is the search's business (it hugs the east flank, the
      mirror image); what is derived by hand is that any way round is under
      30 s while over the top is 44.
      RED COUNTER-PROBE: with `SLOPE_COST_S_PER_M` at 0 the same route is the
      straight [(3106,-6), (3106,18)] at 24 s — the bend is the penalty and
      nothing else.

 [15] THE TWO EXEMPTIONS of the steepness rule (review finding I2). Both were
      untested: a mutant `openings=()` and a mutant `if False` on the
      footprint branch passed every case above. SINCE 2026-08-13 the footprint
      half is FLAG-CONDITIONAL: flattening is opt-in (`level_ground`), and the
      only justification the exemption ever had — "the field is levelled flat
      under a place anyway" — holds for the flagged places alone.

      a) AT AN OPENING (`OPENING_EXEMPT_M` = 1.5 m tolerance + one cell).
         WALL: height area (2200,0)-(2260,60), height 20, falloff 4 — twenty
         metres, so the plateau's rim is a wall by any measure. HOUSE at
         (2200,30), plan_width_m 8, one opening on the E edge at 0.5 -> world
         (2204, 30), and `level_ground` SET — without the flag there is no
         plateau and therefore no rim to be exempt from. The house's centre
         sits ON the area's west outline, so its plateau is 0 and the
         footprint plus one cell around it is pinned there.

         THE FLAG-OFF STATE FIRST, hand-derived on the same two objects: the
         grid is then the plain area raster, bounds (2200,0)-(2260,60) ->
         origin (2196,-4), ceil((2260+4-2196)/4)+1 = 18 columns and
         ceil((60+4+4)/4)+1 = 18 rows, i.e. 18 x 18 instead of 18 x 20, and
         h(2205,29) is the authored wall (5 m in from the west outline, ramp
         capped at falloff 4) = 20 rather than the pinned 0. Setting the flag
         has to hand out a NEW nav context (the placement hash carries it).
         Grid (the OVERVIEW, which is what the shape check names): bounds =
         area box ∪ footprint box grown by one overview step
         ([2192,2208]x[22,38]) = (2192,0)-(2260,60), so origin (2188,-4),
         20 x 18 points at 4 m.

         THE HEIGHTS BELOW ARE THE TILE's (2 m since 2026-08-14) — that is
         what `height_at` reads. Pinned to the plateau's 0 is everything within
         ONE 2 m cell of the footprint [2196,2204]x[26,34], i.e. the rounded
         rectangle out to x ∈ [2194,2206], z ∈ [24,36]; the ring is half as
         wide as it was, so the wall now starts one lattice point earlier.
         THE CELL centred (2207, 29), three metres outside the footprint and
         hypot(3,1) = 3.162 m from the opening — all four probes read between
         two lattice points (2207 and 29 are odd):
           h(2205,29) = 0     both corner columns 2204/2206 are pinned
           h(2209,29) = 20    columns 2208/2210 are 8 and 10 m into the area,
                              i.e. past the falloff 4 -> the full 20
           h(2207,27) = (0 + 20)/2 = 10    the west corners (2206,·) pinned,
                                           the east ones (2208,·) authored 20
           h(2207,31) = (0 + 20)/2 = 10    the same pair one cell north
         rise = hypot(h(2209,29) − h(2205,29), h(2207,31) − h(2207,27))
              = hypot(20, 0) = 20 over run 4 -> atan(5) = 78.6901°, far past
         40 -> the cell WOULD be blocked, and is exempt because the opening is
         within reach. The 4 m raster made the same statement more gently
         (hypot(5, 3.75) = 6.25 -> 57.4°): the narrower ramp ring is a steeper
         wall, which is the accepted consequence of the finer step.
         RED COUNTER-PROBE: the same context with `openings=()` blocks it.
         CONTROL: the next cell out, centred (2209,29), is hypot(5,1) = 5.1 m
         from the opening -> not exempt -> blocked. The exemption is local.

      b) INSIDE A LEVELLING FOOTPRINT (footprint wins). Not constructible
         through the store — after levelling no cell inside a footprint can be
         steep, the apron reaches one full cell past it and the probes only
         2 m — so this is measured on a HAND-BUILT context: a 5 x 5 field,
         step 4, origin (0,0), columns [0, 0, 20, 20, 20], i.e. a cliff
         between x = 4 and x = 8. The cell centred (7,7): h(5,7) =
         0·0.75 + 20·0.25 = 5, h(9,7) = 20 -> rise 15 over 4 -> 75.07° ->
         steep. THREE readings of that one cell, and each is the red probe of
         the next:
           * footprint of edge 8 at (7,7), `level_ground` SET, route STARTS in
             it (so it is exempt) -> free. The place levelled its ground, so
             there is nothing to measure.
           * the SAME footprint with the flag CLEARED -> steep again. The
             landscape runs through an unflagged place, and the router judges
             it exactly like the ground outside — the accepted consequence of
             the decision, and the case a `in_footprint` instead of
             `in_level_footprint` would silently wave through.
           * a route that neither starts nor ends there -> blocked either way
             (foreign footprint, the pre-existing guard).

         AND THE TWO RULES MEET IN ONE BRANCH. The PASSABILITY exemption is
         NOT flag-conditional; the steepness one is — so the case where BOTH
         speak has to be measured, or the steepness question in `blocked`'s
         impassable-ground branch is untested. Same hand-built cliff, plus the
         whole box (0,0)-(16,16) painted with an IMPASSABLE type
         (`{"rock": {"passable": False}}`), route starting inside the
         footprint, so the cell centre fails the terrain test and `blocked`
         takes exactly that branch:
           without a height field: 0 relief -> free in BOTH flag states
                                   (footprint wins, unchanged rule)
           with CLIFF_FIELD, UNFLAGGED: the branch still asks the steepness
                                   -> the same 75.07° -> BLOCKED
           with CLIFF_FIELD, FLAGGED:   `in_level_footprint` -> free
         RED COUNTER-PROBE (run by hand, 2026-08-13): with the
         `or self.too_steep(cell)` clause deleted from that branch the third
         line reads False and the check fails; the other three are unmoved by
         the mutant, which is why the pair is measured in both flag states.

      c) THE CACHE KEY (review finding I1). Authoring an opening changes no
         terrain area, no height area and no placement, and changing
         `game.max_slope_deg` changes nothing in the world at all — both must
         still hand out a NEW context, or the router judges by yesterday's
         doorway and yesterday's limit.

 [16] THE PACE OF THE TOPMOST TERRAIN REACHES AS FAR AS THE SKY (finding 3 of
      the E8 acceptance, 2026-08-13; the REACH decided by the user in round 2
      of the same acceptance). The passability half of "footprint wins" is
      unchanged ([12] proves it); what changed is that the ground's
      `speed_factor` is no longer neutralised in an OPEN place. Two rules:

      `terrain_query.ground_scope(place_is_area, room_is_outdoor)`, read
      most-specific-first (`None` = "no such thing over the point"):

          (None,  None)  -> "wilderness"   no footprint, no room
          (True,  None)  -> "open"         area location
          (False, None)  -> "built"        building footprint
          (True,  False) -> "built"        an interior room wins over it
          (False, True)  -> "open"         the terrace of a house

      `terrain_query.effective_speed_factor(factor, scope)`:

          scope "built"                 ->  1.0   (the place has a floor)
          scope "open" AND factor <= 0  ->  1.0   (a 0 is not a pace)
          otherwise                     ->  max(factor, MIN_SPEED_FACTOR)

      Hand table (MIN_SPEED_FACTOR = 0.1):
          (1.0,  wilderness) -> 1.0     (0.4, wilderness) -> 0.4
          (1.0,  open)       -> 1.0     (0.4, open)       -> 0.4  <- finding 3
          (0.0,  open)       -> 1.0     (0.0, wilderness) -> 0.1  (clamp)
          (0.05, open)       -> 0.1     (0.05, wilderness)-> 0.1  (clamp)
          (2.0,  open)       -> 2.0     (an impassable type's pace counts too)
          (0.4,  built)      -> 1.0     (2.0, built)      -> 1.0  <- round 2

      What makes a location OPEN is `world_geometry.is_area_location`: the
      AUTHORED `passable` or `map3d.area_model`, never a style/name guess —
      a location with `map3d.style: "water"` and `terrain: "lake"` is a
      building (red probe).

      a) A VILLAGE ON A LAKE. Area location at (900,0), plan_width_m 20 ->
         footprint x [890,910], z [-10,10], with WATER painted
         x [890.5,909], z [-9,9] — strictly inside it, so the approach from
         the west stays grass. The west edge sits at 890.5 and not on a whole
         metre so that NO cost midpoint lands exactly on the polygon
         boundary. Water is `speed_factor 0.4`; the footprint keeps the point
         ENTERABLE ([12]'s rule) and, the place being open ground, the 0.4
         applies inside it.
         segment_costs([(870,0), (900,0)]) = 30 m in 15 parts of 2 m,
         midpoints x = 871, 873, … 899. Ten of them (871…889) lie west of
         890.5 and are grass at 1.0 -> 20 m -> 20 s; five (891…899) lie inside
         the lake at 0.4 -> 2 / 0.4 = 5 s each -> 25 s. TOTAL 45 s, against the
         30 s the same walk costs when the place is not open ground.
         The route is still the straight line: every way to a goal 10 m deep
         in the lake crosses the same water, and going round the rim (out at
         z = 11, back down through 9 m of water) is both longer and wetter.
      b) TWO RED COUNTER-PROBES, both landing on 30 s:
         1. THE BUILDING (the round-2 decision, measured end to end): clear
            `map3d.area_model` on the very same location and rebuild the
            context. Nothing else moves, the scope at (900,0) turns "built",
            and all 15 parts pay 1.0 -> 30 s. Setting the flag again wades
            for 45 s.
         2. THE PRE-FINDING-3 RULE as a mutant (`scope != "wilderness" ->
            1.0`) monkeypatched into nav_grid pays the same segment 30 s —
            the same number from the other direction, and the defect finding
            3 named.
      c) THE WILDERNESS IS UNTOUCHED: the same 30 m of sand (0.85) with no
         location on it costs 30 / 0.85 = 35.294117… s, and a factor-0 ground
         out there still pays the MIN_SPEED_FACTOR clamp (10 s per metre),
         which is what makes [4] and [12c] unreachable rather than merely
         slow.
      d) THE HEURISTIC STAYS ADMISSIBLE (review finding F1). `best_factor` is
         the fastest pace A* divides its straight-line estimate by, so it must
         be the maximum over EVERY catalog entry — since (a), an impassable
         type's factor is paid inside footprints and clamped in the
         wilderness, so it is reachable pace. Authoring an impassable
         `speed_factor 2.0` type therefore lifts best_factor from the shared
         catalog's 1.2 (path) to 2.0; the old rule, maximising over passable
         entries only, would have kept 1.2 and let the heuristic overestimate
         a walk over that ground.

Usage:  ./.venv/bin/python scripts/smoke_nav_grid.py
"""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="nav-grid-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="nav-grid-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import config, nav_grid, terrain_query, terrain_types  # noqa: E402
from app.core.world_geometry import (  # noqa: E402
    footprint_hits_aabb, is_area_location, placed_footprint,
    point_in_footprint, segment_hits_footprint)
from app.models import terrain  # noqa: E402
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location,
    update_location_position)

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_true(label, cond, detail=""):
    global CHECKED
    CHECKED += 1
    ok = bool(cond)
    print(f"  {'✓' if ok else '✗'} {label}"
          + (f": {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def approx(label, actual, expected, tol=1e-6):
    global CHECKED
    CHECKED += 1
    ok = isinstance(actual, (int, float)) and abs(actual - expected) <= tol
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected ≈{expected!r}"))
    if not ok:
        FAILURES.append(label)


def raises_value_error(label, fn):
    global CHECKED
    CHECKED += 1
    try:
        fn()
    except ValueError as e:
        print(f"  ✓ {label}: ValueError({str(e)!r})")
        return
    except Exception as e:  # noqa: BLE001 — anything else is the defect
        print(f"  ✗ {label}: {type(e).__name__}({e}) — expected ValueError")
        FAILURES.append(label)
        return
    print(f"  ✗ {label}: no exception — expected ValueError")
    FAILURES.append(label)


def set_plan_width(location_id: str, width: float) -> None:
    """Scale anchor of a location (map3d.plan_width_m) — the footprint edge."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            map3d["plan_width_m"] = width
            loc["map3d"] = map3d
    _save_world_data(data)


def set_area_model(location_id: str, flag: bool) -> None:
    """Mark a location as OPEN GROUND (``map3d.area_model``) or take it back —
    the flag ``world_geometry.is_area_location`` reads."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            map3d = dict(loc.get("map3d") or {})
            if flag:
                map3d["area_model"] = True
            else:
                map3d.pop("area_model", None)
            loc["map3d"] = map3d
    _save_world_data(data)


def set_level_ground(location_id: str, flag: bool) -> None:
    """Flip the OPT-IN FLATTENING of a location (``level_ground``, decision
    2026-08-13) — the flag that decides whether the world grid is levelled
    under it and therefore whether the steepness rule steps back inside it."""
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc["level_ground"] = bool(flag)
    _save_world_data(data)


def set_yaw(location_id: str, yaw_deg: float) -> None:
    data = _load_world_data()
    for loc in data.get("locations", []):
        if loc.get("id") == location_id:
            loc["yaw_deg"] = yaw_deg
    _save_world_data(data)


def polyline_length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def polyline_samples(pts, step=0.3):
    """Every point along the polyline at `step` metres, endpoints included."""
    out = []
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        length = math.dist(pts[i], pts[i + 1])
        n = max(1, int(math.ceil(length / step)))
        for k in range(n + 1):
            t = k / n
            out.append((x0 + (x1 - x0) * t, z0 + (z1 - z0) * t))
    return out


def all_passable(pts):
    """(ok, first offending point) — independent terrain check per point."""
    for x, z in pts:
        if not terrain_query.passability_at(x, z)[0]:
            return False, (round(x, 2), round(z, 2))
    return True, None


def segments_hitting(pts, cx, cz, width, yaw):
    """Segments of the polyline that intersect a footprint — EXACT test."""
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)
            if segment_hits_footprint(pts[i][0], pts[i][1], pts[i + 1][0],
                                      pts[i + 1][1], cx, cz, width, yaw)]


# ── [1] empty world ─────────────────────────────────────────────────────
print("[1] empty world: the straight line survives string-pulling")
r = nav_grid.route((0, 0), (20, 0))
check("route((0,0),(20,0))", r, [(0.0, 0.0), (20.0, 0.0)])
costs = nav_grid.segment_costs(r, nav_grid.build_nav_context())
check("segment count", len(costs), 1)
approx("segment_costs[0]", costs[0], 20.0)

r0 = nav_grid.route((4, 4), (4, 4))
check("same-point route is ONE waypoint (off-centre point)", r0,
      [(4.0, 4.0)])
check("degenerate costs", nav_grid.segment_costs(r0), [])

raises_value_error("NaN start raises",
                   lambda: nav_grid.route((float("nan"), 0), (10, 0)))
raises_value_error("inf goal raises",
                   lambda: nav_grid.route((0, 0), (float("inf"), 0)))

# ── [2] water barrier ───────────────────────────────────────────────────
print("[2] a water barrier forces a detour")
terrain.save_area({"kind": "deep_water",
                   "polygon": [[8, -6], [12, -6], [12, 6], [8, 6]],
                   "z_order": 0})
r = nav_grid.route((0, 0), (20, 0))
check_true("route exists", r is not None, f"{r}")
if r:
    check_true("first waypoint is the start", r[0] == (0.0, 0.0), f"{r[0]}")
    check_true("last waypoint is the goal", r[-1] == (20.0, 0.0), f"{r[-1]}")
    ok, bad = all_passable(r)
    check_true("every waypoint is passable", ok, f"blocked at {bad}")
    ok, bad = all_passable(polyline_samples(r))
    check_true("polyline never enters the water (0.3 m samples)", ok,
               f"blocked at {bad}")
    length = polyline_length(r)
    check_true("longer than the 20 m airline", length > 20.0,
               f"{length:.2f} m")
    check_true("detour stays near the hand estimate (~25.8 m)",
               length < 40.0, f"{length:.2f} m")
    check("deterministic on repeat", nav_grid.route((0, 0), (20, 0)), r)
    nav_grid.invalidate_nav_cache()
    check("deterministic with a rebuilt context",
          nav_grid.route((0, 0), (20, 0)), r)

# ── [3] path corridor ───────────────────────────────────────────────────
print("[3] a faster corridor is worth 1/1.2 of the time")
terrain.save_area({"kind": "path",
                   "polygon": [[0, 98], [20, 98], [20, 102], [0, 102]],
                   "z_order": 1})
costs = nav_grid.segment_costs([(0, 100), (20, 100)])
check("segment count", len(costs), 1)
approx("20 m of path cost 20/1.2 s", costs[0], 20.0 / 1.2)
r = nav_grid.route((0, 100), (20, 100))
check("corridor route", r, [(0.0, 100.0), (20.0, 100.0)])
approx("corridor route cost", nav_grid.segment_costs(r)[0], 20.0 / 1.2)

# ── [4] goal inside a lake ──────────────────────────────────────────────
print("[4] a goal deep inside water is unreachable")
terrain.save_area({"kind": "deep_water",
                   "polygon": [[100, -20], [140, -20], [140, 20], [100, 20]],
                   "z_order": 0})
check("route into the lake", nav_grid.route((0, 0), (120, 0)), None)

# ── [5] footprints ──────────────────────────────────────────────────────
print("[5] a foreign footprint blocks, the endpoint's own does not")
barn = add_location(name="Smoke Barn", description="nav-grid smoke")
BARN_ID = barn["id"]
update_location_position(BARN_ID, 60.0, 0.0)
set_plan_width(BARN_ID, 10.0)

r = nav_grid.route((40, 0), (80, 0))
check_true("route around the barn exists", r is not None, f"{r}")
if r:
    inside = [p for p in r if point_in_footprint(p[0], p[1], 60, 0, 10, 0)]
    check("no waypoint inside the foreign footprint", inside, [])
    check("no SEGMENT intersects the footprint (exact test)",
          segments_hitting(r, 60, 0, 10, 0), [])
    length = polyline_length(r)
    check_true("longer than the 40 m airline", length > 40.0,
               f"{length:.2f} m")

r = nav_grid.route((40, 0), (60, 0))
check("goal footprint is exempt", r, [(40.0, 0.0), (60.0, 0.0)])
approx("straight cost", nav_grid.segment_costs(r)[0], 20.0)
r = nav_grid.route((60, 0), (80, 0))
check("start footprint is exempt", r, [(60.0, 0.0), (80.0, 0.0)])

# ── [6] blocked start cell ──────────────────────────────────────────────
print("[6] a start on a blocked cell is rescued to the nearest passable one")
terrain.save_area({"kind": "deep_water",
                   "polygon": [[198, -2], [202, -2], [202, 2], [198, 2]],
                   "z_order": 0})
check("the start really stands in water",
      terrain_query.passability_at(200, 0)[0], False)
r = nav_grid.route((200, 0), (220, 0))
check_true("route out of the puddle exists", r is not None, f"{r}")
if r:
    check("first waypoint stays the real start", r[0], (200.0, 0.0))
    check("last waypoint is the goal", r[-1], (220.0, 0.0))
    ok, bad = all_passable(r[1:])
    check_true("every waypoint after the start is passable", ok,
               f"blocked at {bad}")
    costs = nav_grid.segment_costs(r)
    check_true("costs are finite and positive",
               costs and all(math.isfinite(c) and c > 0 for c in costs),
               f"{[round(c, 2) for c in costs]}")

# ── [7] cost-aware smoothing ────────────────────────────────────────────
print("[7] the detour around slow terrain survives the string-pulling")
terrain.save_area({"kind": "forest",
                   "polygon": [[40, 190], [60, 190], [60, 210], [40, 210]],
                   "z_order": 0})
straight = nav_grid.segment_costs([(0, 200), (100, 200)])[0]
approx("straight line through the forest costs 80 + 20/0.7",
       straight, 80.0 + 20.0 / 0.7, tol=1e-6)
r = nav_grid.route((0, 200), (100, 200))
check_true("route exists", r is not None, f"{r}")
if r:
    total = sum(nav_grid.segment_costs(r))
    check_true("the route is NOT the straight line", len(r) > 2,
               f"{len(r)} waypoints: {r}")
    check_true("and it is cheaper than crossing the forest",
               total < straight - 1.0,
               f"{total:.2f} s vs {straight:.2f} s "
               f"(hand estimate for rounding it: ~102.96 s)")
    length = polyline_length(r)
    check_true("longer in METRES than the 100 m airline", length > 100.0,
               f"{length:.2f} m")

# ── [8] geometry helpers ────────────────────────────────────────────────
print("[8] the exact geometry helpers, hand-derived")
check("segment through the footprint",
      segment_hits_footprint(-5, 0, 5, 0, 0, 0, 2, 0), True)
check("segment passing 2 m beside it",
      segment_hits_footprint(-5, 2, 5, 2, 0, 0, 2, 0), False)
check("segment ending before it",
      segment_hits_footprint(-5, 0, -2, 0, 0, 0, 2, 0), False)
check("cell [0,2]x[0,2] overlaps the yaw-45 square",
      footprint_hits_aabb(0, 0, 2, 45, 0, 0, 2, 2), True)
check("cell [1,3]x[1,3] does not",
      footprint_hits_aabb(0, 0, 2, 45, 1, 1, 3, 3), False)
check("a non-finite position has no footprint",
      placed_footprint({"pos_x": float("nan"), "pos_z": 0.0,
                        "map3d": {"plan_width_m": 10}}), None)
check("a sane position still has one",
      placed_footprint({"pos_x": 5.0, "pos_z": 6.0,
                        "map3d": {"plan_width_m": 10}}), (5.0, 6.0, 10.0, 0.0))

# ── [9] rotated footprint ───────────────────────────────────────────────
print("[9] a rotated footprint is rounded, not clipped")
mill = add_location(name="Smoke Mill", description="nav-grid smoke")
MILL_ID = mill["id"]
update_location_position(MILL_ID, 500.0, 0.0)
set_plan_width(MILL_ID, 14.0)
set_yaw(MILL_ID, 45.0)
check_true("the airline really crosses the mill",
           segment_hits_footprint(480, 0, 520, 0, 500, 0, 14, 45), "")
r = nav_grid.route((480, 0), (520, 0))
check_true("route around the mill exists", r is not None, f"{r}")
if r:
    check("no SEGMENT intersects the rotated footprint",
          segments_hitting(r, 500, 0, 14, 45), [])
    inside = [p for p in r if point_in_footprint(p[0], p[1], 500, 0, 14, 45)]
    check("no waypoint inside it", inside, [])
    length = polyline_length(r)
    check_true("longer than the 40 m airline", length > 40.0,
               f"{length:.2f} m")

# ── [10] diagonal squeeze ───────────────────────────────────────────────
print("[10] no squeezing diagonally between two corner-touching blocks")
terrain.save_area({"kind": "rock",
                   "polygon": [[300, 300], [302, 300], [302, 302], [300, 302]],
                   "z_order": 0})
terrain.save_area({"kind": "rock",
                   "polygon": [[302, 302], [304, 302], [304, 304], [302, 304]],
                   "z_order": 0})
check("cell centre (301,301) is blocked",
      terrain_query.passability_at(301, 301)[0], False)
check("cell centre (303,303) is blocked",
      terrain_query.passability_at(303, 303)[0], False)
r = nav_grid.route((301, 303), (303, 301))
check_true("route exists", r is not None, f"{r}")
if r:
    length = polyline_length(r)
    check_true("it walks around instead of through the corner "
               "(airline is 2.83 m)", length > 4.5, f"{length:.2f} m")
    inside = [p for p in r if not terrain_query.passability_at(*p)[0]]
    check("no waypoint on rock", inside, [])

# ── [11] cache ──────────────────────────────────────────────────────────
print("[11] the context is cached on terrain + placement signature")
ctx_a = nav_grid.build_nav_context()
check_true("second build hits the cache",
           nav_grid.build_nav_context() is ctx_a, "")
nav_grid.invalidate_nav_cache()
ctx_b = nav_grid.build_nav_context()
check_true("invalidate_nav_cache() forces a rebuild", ctx_b is not ctx_a, "")
check("the default ground is resolved once into the context",
      ctx_b.default_kind, terrain_query.default_kind())
area = terrain.save_area({"kind": "sand",
                          "polygon": [[400, 400], [410, 400], [410, 410],
                                      [400, 410]],
                          "z_order": 0})
ctx_c = nav_grid.build_nav_context()
check_true("painting an area invalidates the cache", ctx_c is not ctx_b, "")
terrain.delete_area(area["id"])
nav_grid.build_nav_context()
update_location_position(BARN_ID, 61.0, 0.0)
ctx_d = nav_grid.build_nav_context()
check_true("moving a placed location invalidates the cache",
           ctx_d is not ctx_c, "")

# ── [12] footprint wins over painted ground ─────────────────────────────
print("[12] a location on rock is reachable — the footprint wins")
hall = add_location(name="Smoke Bluff Hall", description="nav-grid smoke")
HALL_ID = hall["id"]
update_location_position(HALL_ID, 700.0, 0.0)
set_plan_width(HALL_ID, 20.0)
terrain.save_area({"kind": "rock",
                   "polygon": [[691, -9], [709, -9], [709, 9], [691, 9]],
                   "z_order": 0})
check("the goal really stands on impassable ground",
      terrain_query.passability_at(700, 0)[0], False)
check("...and the approach does not",
      terrain_query.passability_at(670, 0)[0], True)
check_true("the goal lies inside the footprint",
           point_in_footprint(700, 0, 700, 0, 20, 0), "")
ctx = nav_grid.build_nav_context()
check("the goal cell is (350, 0)", nav_grid.cell_of(700, 0), (350, 0))
check("...centred on (701, 1)", nav_grid.cell_centre((350, 0)), (701.0, 1.0))
own = nav_grid._Search(ctx, (670.0, 0.0), (700.0, 0.0))
check("its own route does not lose the goal cell to the rock under it",
      own.blocked((350, 0)), False)
foreign = nav_grid._Search(ctx, (670.0, 0.0), (670.0, 60.0))
check("a FOREIGN route still finds it blocked — by the footprint",
      foreign.blocked((350, 0)), True)
r = nav_grid.route((670, 0), (700, 0))
check("the straight line into the hall (old rule: None)", r,
      [(670.0, 0.0), (700.0, 0.0)])
check_true("its end really lies in the footprint",
           point_in_footprint(700, 0, 700, 0, 20, 0), "")
# The PACE side of the decision: 30 m, 15 samples of 2 m, midpoints at
# x = 671, 673, … 699. The ten outside are grass (1.0), the five from 691 on
# lie in the footprint of a BUILDING and are paid at the neutral 1.0 instead
# of the rock's clamped 0.1 -> 30 / 1.0 = 30 s exactly. Two rules land on the
# same number here: a built place replaces the ground outright (round 2), and
# a factor-0 ground is neutral in an open place too (see [16]). With the old
# factor the same five would have cost 10 s per metre and A* would not even
# have walked straight: it hugged the rim and the last leg alone cost 90.55 s.
approx("its cost is the plain 30 m at factor 1.0",
       nav_grid.segment_costs(r)[0], 30.0)
check("a built place pays the neutral 1.0 whatever the ground holds",
      terrain_query.effective_speed_factor(0.0, "built"), 1.0)
check("...and a factor-0 ground in an OPEN place is neutral as well",
      terrain_query.effective_speed_factor(0.0, "open"), 1.0)
# The wilderness half is unchanged: the same rock without a location on it.
terrain.save_area({"kind": "rock",
                   "polygon": [[730, -20], [770, -20], [770, 20], [730, 20]],
                   "z_order": 0})
check("a goal 20 m deep in wilderness rock stays unreachable",
      nav_grid.route((670, 0), (750, 0)), None)

print("[13] a cell too steep to stand on is blocked")
from app.models import heightfield as height_store  # noqa: E402

height_store.save_height_area(
    {"id": "steep", "height_m": 5.0, "falloff_m": 4.0,
     "polygon": [[2000, 0], [2040, 0], [2040, 40], [2000, 40]]})
ctx = nav_grid.build_nav_context()
approx("the west flank at (2003, 21)", ctx.height_at(2003, 21), 3.75)
approx("...against (1999, 21)", ctx.height_at(1999, 21), 0.0)
approx("the angle of that rise over 4 m",
       math.degrees(math.atan2(3.75, 4.0)), 43.1524, 1e-4)
search = nav_grid._Search(ctx, (1960.0, 20.0), (2060.0, 20.0))
check("the flank cell", nav_grid.cell_of(2001, 21), (1000, 10))
check("...is too steep to stand on", search.too_steep((1000, 10)), True)
check("...and therefore blocked", search.blocked((1000, 10)), True)
check("the plateau itself is flat and free",
      search.too_steep(nav_grid.cell_of(2021, 21)), False)
check("...and so is the flat world beside the hill",
      search.too_steep(nav_grid.cell_of(1981, 21)), False)
steep_route = nav_grid.route((1960, 20), (2060, 20))
check_true("a route past the hill exists", steep_route is not None,
           f"{steep_route}")
check_true("...and it does not cross it",
           steep_route is not None
           and all(not search.too_steep(nav_grid.cell_of(x, z))
                   for x, z in polyline_samples(steep_route, 1.0)),
           "")
check_true("...so it is longer than the straight 100 m",
           steep_route is not None and polyline_length(steep_route) > 100.0,
           f"{round(polyline_length(steep_route), 2) if steep_route else None}")
height_store.delete_height_area("steep")
check("RED COUNTER-PROBE: without the hill the route is straight",
      nav_grid.route((1960, 20), (2060, 20)), [(1960.0, 20.0), (2060.0, 20.0)])

print("\n[14] the climb is paid for — a penalty, never a bonus")
height_store.save_height_area(
    {"id": "ridge", "height_m": 5.0, "falloff_m": 12.0,
     "polygon": [[3100, 0], [3112, 0], [3112, 12], [3100, 12]]})
ctx = nav_grid.build_nav_context()
check("the ridge raster is 6 × 6",
      (ctx.height_field["rows"], ctx.height_field["cols"]), (6, 6))
check("the ground around it is plain grass at factor 1.0",
      ctx.terrain_at(3106, -6), (True, 1.0))
approx("its spine tops out at the authored 5 · 6/12 on the 2 m tile",
       ctx.height_at(3106, 6), 2.5, 1e-9)
approx("the profile at z = 2", ctx.height_at(3106, 2), 0.833, 1e-9)
ridge_search = nav_grid._Search(ctx, (3106.0, -6.0), (3106.0, 18.0))
check("nothing on the ridge is blocked",
      any(ridge_search.too_steep(nav_grid.cell_of(3106, z))
          for z in range(-6, 19)), False)
approx("the straight way over costs 24 m + 4 · 5 m of climb (2.5 up, 2.5 "
       "down)",
       nav_grid._segment_cost(ctx, (3106.0, -6.0), (3106.0, 18.0)), 44.0,
       1e-9)
ridge_route = nav_grid.route((3106, -6), (3106, 18))
check_true("the route BENDS around the ridge instead of going over it",
           ridge_route is not None and len(ridge_route) > 2, f"{ridge_route}")
check_true("...and costs less than the straight way",
           ridge_route is not None
           and sum(nav_grid.segment_costs(ridge_route)) < 44.0,
           f"{round(sum(nav_grid.segment_costs(ridge_route)), 3)}")
_penalty = nav_grid.SLOPE_COST_S_PER_M
nav_grid.SLOPE_COST_S_PER_M = 0.0
nav_grid.invalidate_nav_cache()
check("RED COUNTER-PROBE: without the penalty it goes straight over",
      nav_grid.route((3106, -6), (3106, 18)),
      [(3106.0, -6.0), (3106.0, 18.0)])
approx("...at the plain 24 m",
       nav_grid._segment_cost(nav_grid.build_nav_context(),
                              (3106.0, -6.0), (3106.0, 18.0)), 24.0)
nav_grid.SLOPE_COST_S_PER_M = _penalty
height_store.delete_height_area("ridge")

print("\n[15] the two exemptions of the steepness rule")
from dataclasses import replace as _replace  # noqa: E402

height_store.save_height_area(
    {"id": "wall", "height_m": 20.0, "falloff_m": 4.0,
     "polygon": [[2200, 0], [2260, 0], [2260, 60], [2200, 60]]})
HOUSE = add_location(name="Smoke House", description="nav smoke")["id"]
update_location_position(HOUSE, 2200.0, 30.0)
set_plan_width(HOUSE, 8.0)
# THE FLAG-OFF STATE FIRST: an unflagged place levels nothing, so there is no
# plateau, no rim and no grid growth — the authored wall runs straight through
# the house.
flat_ctx = nav_grid.build_nav_context()
check("an unflagged house does not grow the grid",
      (flat_ctx.height_field["rows"], flat_ctx.height_field["cols"]), (18, 18))
check("...which is anchored at the area's own box",
      (flat_ctx.height_field["origin_x"], flat_ctx.height_field["origin_z"]),
      (2196.0, -4.0))
approx("...and h(2205,29) is the authored wall, not a pinned apron",
       flat_ctx.height_at(2205, 29), 20.0)
set_level_ground(HOUSE, True)
ctx_before = nav_grid.build_nav_context()
check_true("setting level_ground hands out a NEW context (placement hash)",
           ctx_before is not flat_ctx, f"{flat_ctx.sig} -> {ctx_before.sig}")
_house = _load_world_data()
for _loc in _house["locations"]:
    if _loc.get("id") == HOUSE:
        _map3d = dict(_loc.get("map3d") or {})
        _map3d["boundary_openings"] = [{"edge": "E", "at": 0.5,
                                        "width_m": 2.0, "type": "passage",
                                        "room": ""}]
        _loc["map3d"] = _map3d
_save_world_data(_house)
ctx = nav_grid.build_nav_context()
check_true("[I1] authoring an opening hands out a NEW context",
           ctx is not ctx_before, f"{ctx_before.sig} -> {ctx.sig}")
check("the opening sits on the E edge", ctx.openings, ((2204.0, 30.0),))
check("the grid grew for the house's plateau",
      (ctx.height_field["rows"], ctx.height_field["cols"]), (18, 20))
approx("h(2205,29) — the pinned apron", ctx.height_at(2205, 29), 0.0)
approx("h(2209,29) — past the falloff, the full wall",
       ctx.height_at(2209, 29), 20.0)
approx("h(2207,27) — pinned west, authored east", ctx.height_at(2207, 27),
       10.0)
approx("h(2207,31) — the same pair one cell north",
       ctx.height_at(2207, 31), 10.0)
approx("so the rise is hypot(20, 0)", math.hypot(20.0, 0.0), 20.0)
approx("its angle over 4 m", math.degrees(math.atan2(20.0, 4.0)), 78.6901,
       1e-4)
near_cell = nav_grid.cell_of(2207, 29)
far_cell = nav_grid.cell_of(2209, 29)
check("the exempt cell is centred (2207, 29)", nav_grid.cell_centre(near_cell),
      (2207.0, 29.0))
approx("...and lies 3.162 m from the opening",
       math.hypot(2207 - 2204, 29 - 30), 3.1622777, 1e-6)
search = nav_grid._Search(ctx, (2260.0, 58.0), (2258.0, 56.0))
check("the cell at the opening is NOT blocked for its height",
      search.too_steep(near_cell), False)
blind = nav_grid._Search(_replace(ctx, openings=()),
                         (2260.0, 58.0), (2258.0, 56.0))
check("RED COUNTER-PROBE: without the openings it is too steep",
      blind.too_steep(near_cell), True)
approx("the control cell lies 5.1 m from the opening",
       math.hypot(2209 - 2204, 29 - 30), 5.0990195, 1e-6)
check("...so it stays blocked — the exemption is local",
      search.too_steep(far_cell), True)

# The footprint half, on a hand-built context: after levelling no cell INSIDE
# a footprint can be steep, so the guard is measured where a cliff and a
# footprint really do overlap.
CLIFF_FIELD = {"origin_x": 0.0, "origin_z": 0.0, "step_m": 4.0,
               "rows": 5, "cols": 5,
               "heights": [[0.0, 0.0, 20.0, 20.0, 20.0] for _ in range(5)]}


def cliff_ctx(level_ground):
    """The hand-built cliff with ONE footprint over it, flagged or not."""
    return nav_grid.NavContext(
        areas=[], catalog={},
        footprints=[("fp", 7.0, 7.0, 8.0, 0.0, False, level_ground)],
        data_bounds=(0.0, 0.0, 16.0, 16.0), sig=("hand", "hand"),
        height_field=CLIFF_FIELD, openings=(), max_step_m=0.4,
        max_slope_deg=40.0)


hand = cliff_ctx(True)
approx("the hand-built cliff: h(5,7)", hand.height_at(5, 7), 5.0)
approx("...against h(9,7)", hand.height_at(9, 7), 20.0)
approx("...15 m over 4 m", math.degrees(math.atan2(15.0, 4.0)), 75.0686, 1e-4)
inside = nav_grid._Search(hand, (7.0, 7.0), (7.0, 7.0))
check("a route that starts in a LEVELLING place walks its own ground",
      inside.too_steep(nav_grid.cell_of(7, 7)), False)
unflagged = nav_grid._Search(cliff_ctx(False), (7.0, 7.0), (7.0, 7.0))
check("RED COUNTER-PROBE: without level_ground the same cell measures for "
      "real", unflagged.too_steep(nav_grid.cell_of(7, 7)), True)
check("...and is therefore blocked, out of its own place",
      unflagged.blocked(nav_grid.cell_of(7, 7)), True)
check("...while the levelling one stays free",
      inside.blocked(nav_grid.cell_of(7, 7)), False)
outside = nav_grid._Search(hand, (100.0, 100.0), (101.0, 101.0))
check("RED COUNTER-PROBE: for a foreign route the same cell is too steep",
      outside.too_steep(nav_grid.cell_of(7, 7)), True)
ROCK_AREAS = [{"kind": "rock", "z_order": 0,
               "polygon": [[0, 0], [16, 0], [16, 16], [0, 16]]}]
ROCK_CATALOG = {"rock": {"passable": False, "speed_factor": 1.0}}


def rock_search(level_ground, with_relief):
    """A route starting INSIDE the footprint on painted rock — the cell centre
    fails the terrain test, so ``blocked`` reaches its impassable-ground
    branch, which is the one both rules meet in."""
    ctx = _replace(cliff_ctx(level_ground), areas=ROCK_AREAS,
                   catalog=ROCK_CATALOG,
                   height_field=CLIFF_FIELD if with_relief else None)
    return nav_grid._Search(ctx, (7.0, 7.0), (7.0, 7.0))


check("the cell centre really is impassable rock",
      terrain_query.passability_at(7, 7, areas=ROCK_AREAS,
                                   catalog=ROCK_CATALOG), (False, 1.0))
check("the PASSABILITY exemption does NOT ask the flag — an unflagged place "
      "on impassable ground still wins",
      rock_search(False, False).blocked(nav_grid.cell_of(7, 7)), False)
check("...nor does it for a levelling one",
      rock_search(True, False).blocked(nav_grid.cell_of(7, 7)), False)
check("...but on the CLIFF the unflagged place is blocked all the same — by "
      "its STEEPNESS, in the very branch the terrain just waved through",
      rock_search(False, True).blocked(nav_grid.cell_of(7, 7)), True)
check("RED COUNTER-PROBE: its levelling twin, same rock, same cliff, is free",
      rock_search(True, True).blocked(nav_grid.cell_of(7, 7)), False)

# [I1] the second half: an admin dial nobody else notices.
ctx_limits = nav_grid.build_nav_context()
config._CONFIG.setdefault("game", {})["max_slope_deg"] = 80.0
check_true("[I1] changing max_slope_deg hands out a NEW context",
           nav_grid.build_nav_context() is not ctx_limits, "")
check("...and the router judges by the new limit",
      nav_grid.build_nav_context().max_slope_deg, 80.0)
check("the steep cell is walkable at 80°",
      nav_grid._Search(nav_grid.build_nav_context(),
                       (2260.0, 58.0), (2258.0, 56.0)).too_steep(far_cell),
      False)
config._CONFIG.setdefault("game", {}).pop("max_slope_deg", None)
height_store.delete_height_area("wall")

print("\n[16] the pace of the topmost terrain reaches as far as the sky")
# How far it reaches — the hand table of the docstring.
check("nothing over the point is the wilderness",
      terrain_query.ground_scope(None, None), "wilderness")
check("an area location is open ground",
      terrain_query.ground_scope(True, None), "open")
check("a building footprint is built",
      terrain_query.ground_scope(False, None), "built")
check("an interior room beats the area location it stands in",
      terrain_query.ground_scope(True, False), "built")
check("an outdoor room beats the building it belongs to",
      terrain_query.ground_scope(False, True), "open")
# The pace itself, straight off the second hand table.
check("wilderness grass", terrain_query.effective_speed_factor(1.0, "wilderness"),
      1.0)
check("open-place grass", terrain_query.effective_speed_factor(1.0, "open"), 1.0)
check("wilderness water 0.4",
      terrain_query.effective_speed_factor(0.4, "wilderness"), 0.4)
check("water 0.4 in an OPEN place stays 0.4 (the finding)",
      terrain_query.effective_speed_factor(0.4, "open"), 0.4)
check("...and in a BUILT one the floor replaces it (round 2)",
      terrain_query.effective_speed_factor(0.4, "built"), 1.0)
check("a factor-0 ground in the wilderness is clamped, not neutralised",
      terrain_query.effective_speed_factor(0.0, "wilderness"), 0.1)
check("...and in an open place it is neutral",
      terrain_query.effective_speed_factor(0.0, "open"), 1.0)
check("a crawling 0.05 is clamped out here",
      terrain_query.effective_speed_factor(0.05, "wilderness"), 0.1)
check("...and in an open place too (only the 0 is special)",
      terrain_query.effective_speed_factor(0.05, "open"), 0.1)
check("a fast 2.0 keeps its pace in an open place",
      terrain_query.effective_speed_factor(2.0, "open"), 2.0)
check("...and loses it under a roof",
      terrain_query.effective_speed_factor(2.0, "built"), 1.0)
# What makes a location OPEN: two authored flags, never a style guess.
check("a plain location is not an area", is_area_location({"name": "Hall"}),
      False)
check("a transit location is", is_area_location({"passable": True}), True)
check("...and so is one whose model IS the ground",
      is_area_location({"map3d": {"area_model": True}}), True)
check("RED: a lake-STYLE building is still a building",
      is_area_location({"map3d": {"style": "water"}, "terrain": "lake"}), False)

lake_hall = add_location(name="Smoke Lake Village", description="nav-grid smoke")
LAKE_ID = lake_hall["id"]
update_location_position(LAKE_ID, 900.0, 0.0)
set_plan_width(LAKE_ID, 20.0)
set_area_model(LAKE_ID, True)
terrain.save_area({"kind": "water",
                   "polygon": [[890.5, -9], [909, -9], [909, 9], [890.5, 9]],
                   "z_order": 0})
check("the goal stands on water — swimmable since round 2",
      terrain_query.passability_at(900, 0), (True, 0.4))
check("...and the approach on grass", terrain_query.passability_at(870, 0),
      (True, 1.0))
lake_ctx = nav_grid.build_nav_context()
check("the village really counts as open ground",
      nav_grid._footprint_scope(900.0, 0.0, lake_ctx.footprints), "open")
# 15 samples of 2 m, midpoints x = 871 … 899: ten west of the 890.5 shore on
# grass (10 * 2 / 1.0 = 20 s) and five in the lake inside the footprint
# (5 * 2 / 0.4 = 25 s) -> 45 s. No midpoint sits on the polygon edge.
approx("30 m into the village cost 20 s of grass + 25 s of wading",
       nav_grid._segment_cost(lake_ctx, (870.0, 0.0), (900.0, 0.0)), 45.0)
r = nav_grid.route((870, 0), (900, 0))
check("the route is still the straight line into the village", r,
      [(870.0, 0.0), (900.0, 0.0)])
approx("...and the journey pays the water for it",
       sum(nav_grid.segment_costs(r)), 45.0)
# RED COUNTER-PROBE 1 (round 2): the SAME lake under a BUILDING. Nothing
# changes but the area flag, and the five wet midpoints go back to the
# neutral 1.0 -> 15 parts of 2 m at 1.0 = 30 s. That is the reach decision,
# measured end to end instead of monkeypatched.
set_area_model(LAKE_ID, False)
built_ctx = nav_grid.build_nav_context()
check_true("flipping the flag really hands out a new context",
           built_ctx is not lake_ctx, "")
check("the same point is BUILT now",
      nav_grid._footprint_scope(900.0, 0.0, built_ctx.footprints), "built")
approx("RED COUNTER-PROBE: a HALL on the same lake is walked dry in 30 s",
       nav_grid._segment_cost(built_ctx, (870.0, 0.0), (900.0, 0.0)), 30.0)
set_area_model(LAKE_ID, True)
lake_ctx = nav_grid.build_nav_context()
approx("...and the village wades again",
       nav_grid._segment_cost(lake_ctx, (870.0, 0.0), (900.0, 0.0)), 45.0)
# RED COUNTER-PROBE 2: the rule BEFORE finding 3, where every footprint
# neutralised its ground — the same 30 s, from the other direction.
_rule = nav_grid.effective_speed_factor
nav_grid.effective_speed_factor = (
    lambda factor, scope: 1.0 if scope != "wilderness"
    else max(factor, terrain_query.MIN_SPEED_FACTOR))
approx("RED COUNTER-PROBE: the old footprint-neutral rule walks it dry in 30 s",
       nav_grid._segment_cost(lake_ctx, (870.0, 0.0), (900.0, 0.0)), 30.0)
nav_grid.effective_speed_factor = _rule
approx("...and the real rule is back",
       nav_grid._segment_cost(lake_ctx, (870.0, 0.0), (900.0, 0.0)), 45.0)
# The wilderness half: sand out in the open, no footprint anywhere near it.
terrain.save_area({"kind": "sand",
                   "polygon": [[1200, -20], [1240, -20], [1240, 20],
                               [1200, 20]],
                   "z_order": 0})
sand_ctx = nav_grid.build_nav_context()
approx("30 m of wilderness sand cost 30 / 0.85",
       nav_grid._segment_cost(sand_ctx, (1205.0, 0.0), (1235.0, 0.0)),
       30.0 / 0.85)
# [16d] the heuristic's divisor knows the impassable types too.
approx("the shared catalog's fastest pace is the path's 1.2",
       nav_grid.build_nav_context().best_factor, 1.2)
terrain_types.save_world_type({"kind": "rapids", "color": "#3366aa",
                               "passable": False, "speed_factor": 2.0})
approx("an impassable 2.0 type lifts best_factor to 2.0",
       nav_grid.build_nav_context().best_factor, 2.0)
# RED COUNTER-PROBE: the old rule looked at passable entries only.
_old_best = max([1.0] + [float(e.get("speed_factor", 1.0) or 1.0)
                         for e in terrain_types.effective_catalog().values()
                         if e.get("passable", True)])
approx("RED COUNTER-PROBE: passable-only would have kept 1.2 (inadmissible)",
       _old_best, 1.2)
terrain_types.delete_world_type("rapids")
approx("...and removing the type puts the divisor back",
       nav_grid.build_nav_context().best_factor, 1.2)

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)}/{CHECKED}: {FAILURES}")
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
