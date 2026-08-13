#!/usr/bin/env python3
"""Smoke run for the WORLD HEIGHTFIELD — authoring, rastering, sampling
(Seamless World, E8 task 2).

Throwaway storage, no server, no real world. Every number below is derived BY
HAND in this header from the rules, never recorded from the current output.

THE RULES BEING CHECKED
-----------------------
A height AREA is a polygon plus ``height_m`` (how high the ground stands
inside) and ``falloff_m`` (over how many metres it climbs there from the
outline). The server RASTERS the areas onto a grid of support points and
samples that grid bilinearly; nobody edits the grid.

    h_area(p) = height_m · min(1, distance_from_p_to_the_outline / falloff_m)
                for p INSIDE the outline, otherwise the area says nothing

Per support point the STRONGEST deflection from the flat world wins (largest
|value|), so two hills resolve to "the higher one" and a hollow is not beaten
by the 0 of the ground around it.

THE LATTICE IS ANCHORED AT THE WORLD ORIGIN (0, 0) — section [6] is the whole
reason this matters, and it is the finding this task was told to respect:
``world_bounds`` grows, and a grid derived from it would move every sample
point in the world whenever someone painted at the far edge.

  origin = floor(min / step) · step − step          (one ring OUTSIDE the data)
  points = ceil((max + step − origin) / step) + 1   (and one ring past it)

so the whole border of every raster is 0, which is what makes "clamp to the
border outside the grid" mean "the flat world".

THE SHAPES USED BELOW (step 4 m, the default, throughout)
--------------------------------------------------------
  HILL   square (0,0)-(40,40), height 5, falloff 4
  SOFT   the same square,      height 5, falloff 8
  BIG    square (20,20)-(60,60), height 9, falloff 4
  PIT    the same square as BIG, height −9, falloff 4
  VALLEY the HILL square with height −3, falloff 4

[1] RASTER GEOMETRY of HILL alone. bbox (0,0)-(40,40):
      origin = floor(0/4)·4 − 4 = −4 on both axes
      points = ceil((40 + 4 + 4)/4) + 1 = 12 + 1 = 13 per axis
    so heights[j][i] is the height at (−4 + 4i, −4 + 4j), 13 × 13.
      (−4,−4) i=0 j=0   outside the outline            -> 0
      ( 0, 0) i=1 j=1   ON the outline, distance 0     -> 5 · 0/4  = 0
      ( 4, 4) i=2 j=2   distance 4 to the nearest edge -> 5 · 4/4  = 5
      (20,20) i=6 j=6   distance 20                    -> 5 (capped by min)
      (40,20) i=11 j=6  ON the east edge, distance 0   -> 0
      (44,44) i=12 j=12 outside                        -> 0
[2] THE RAMP, with SOFT (falloff 8) on the same square:
      ( 4, 4) distance 4 -> 5 · 4/8 = 2.5
      ( 8, 8) distance 8 -> 5 · 8/8 = 5
      (20,20) distance 20, min caps the ramp at 1 -> 5
[3] OVERLAP. HILL + BIG together, bbox (0,0)-(60,60):
      origin −4, points = ceil((60+4+4)/4)+1 = 17+1 = 18 per axis.
      (32,32) HILL: distance min(32, 8, 32, 8) = 8 -> 5 · 1 = 5
              BIG:  distance min(12, 28, 12, 28) = 12 -> 9 · 1 = 9
              |9| > |5| -> 9          "the higher area wins"
      ( 4, 4) only HILL covers it -> 5
      (56,56) only BIG covers it, distance min(36,4,36,4) = 4 -> 9
    HILL + PIT (the same square as BIG, −9):
      (32,32) 5 against −9: |−9| > |5| -> −9
    VALLEY alone:
      (20,20) -> −3, and NOT 0: a hollow that lost against the flat world
                 would make every valley un-authorable.
[4] SANITIZER. height_m is CLAMPED (an authoring slip moves the ground to the
    limit, it does not lose the shape): 80 -> 50, −80 -> −50, junk/absent ->
    0.0. falloff_m is a width: −5 -> 0 (a wall, legal), 2000 -> 1000.
    The outline follows the terrain-area rules: 2 points, 257 points, a
    coordinate of 1e9, NaN and a dict vertex all raise ValueError. New ids are
    prefixed "ha_".
[5] SIGNATURE + STORE + ground_y. With HILL saved:
      ground_y(20,20) = 5.0                (a support point)
      ground_y( 2, 2) = 1.25               bilinear between (0,0)=0, (4,0)=0,
                                           (0,4)=0 and (4,4)=5, both fractions
                                           0.5 -> 0.25·5
      ground_y( 2,20) = 2.5                between (0,20)=0 and (4,20)=5,
                                           fraction 0.5, exactly on the z line
      ground_y(−100,−100) = 0.0            outside -> the 0 border
    The stored grid carries the signature it was built from (13 × 13 here),
    the signature changes on save, on edit and comes BACK to the empty one
    when the area is deleted (same areas, same signature), and ground_y is 0
    again afterwards — the write-through invalidation, without which the
    world would stay hilly after the hill was erased.
[6] THE ANCHORED LATTICE — and it has to be checked where it can FAIL.
    FAR = square (100,0)-(140,40), height 5, falloff 4.
    Rastered ALONE: origin_x = floor(100/4)·4 − 4 = 96.
    Rastered TOGETHER with WEST = square (−501,0)-(−461,40), a shape 600 m to
    the west whose corner is deliberately NOT on the 4 m lattice:
    origin_x = floor(−501/4)·4 − 4 = −126·4 − 4 = −508. Different origin,
    different index — and the SAME height at the same world point, because
    −508 is still a multiple of 4, so both grids sample the very same points.

    MEASURED ON THE FLANK, at (102, 20), and that is the whole point of the
    case. The support points either side are x = 100 (ON the outline, height 0)
    and x = 104 (4 m in, height 5·4/4 = 5), and 102 sits exactly between them:
      0·0.5 + 5·0.5 = 2.5, in BOTH rasters.
    RED COUNTER-PROBE (run by hand, 2026-08-13): with the naive origin
    `origin = min − step` the two answers come apart here — alone it is
    unchanged (100 is a multiple of 4, so the naive origin is also 96, 2.5),
    but with WEST the origin becomes −505, the neighbours of 102 are 99
    (outside, 0) and 103 (3 m in, 5·3/4 = 3.75) at fraction 0.75, giving
    0·0.25 + 3.75·0.75 = 2.8125 ≠ 2.5. A check on a lattice point (120) or in
    the PLATEAU (118, both neighbours already at full height) passes under that
    mutant — which is why neither is the measurement.
[7] COARSENING. A single square (0,0)-(8000,8000) would need
    ceil((8000+4+4)/4)+1 = 2003 points per axis = 4.0 M — past MAX_POINTS
    (120 000). The step doubles until it fits: 8 -> 1003² = 1.0 M, 16 -> 503²
    = 253 009, 32 -> ceil((8000+32+32)/32)+1 = 253 per axis = 64 009. So
    step_m 32 and 253 × 253. Doubling keeps the lattice anchored at the
    origin, so a coarser grid still samples a subset of the finer points.
[8] THE SHARED SAMPLER's table, hand-derived on a 3 × 3 field with a single
    5 m peak in the middle — the SAME field and the SAME expectations as
    ``client3d/scripts/smoke_world_height.mjs``. Twin discipline: one bilinear
    rule, two implementations, one table.
      field: origin (−4,−4), step 4, heights [[0,0,0],[0,5,0],[0,0,0]]
      ( 0, 0) the peak                                  -> 5
      ( 2, 0) fx 1.5 -> i 1, tx .5; fz 1 -> j 1, tz 0   -> 2.5
      ( 2, 2) both fractions .5, one corner carries 5   -> 1.25
      ( 0,−2) fz 0.5 between the 0 row and the peak row -> 2.5
      (−4,−4) the corner point itself                   -> 0
      (100,0) outside east: fx clamps to 2, i = 1, tx 1 -> 0 (border)
      (−100,−100) outside north-west: the corner        -> 0
      a field with a single row (rows < 2) carries no relief -> 0
      A RAGGED FIELD must not raise (a hand-edited or truncated row must cost
      a slightly wrong height, never a 500 on POST /play/pos): with
      heights [[0, 10], [0]] the point (2, 2) mixes north = 0·0.5 + 10·0.5 = 5
      against a south row whose missing entries read as 0 -> 5·0.5 = 2.5. The
      client sampler answers the same, from the same array shape.
[9] THE CACHE CONTRACT (review 2026-08-13, findings I1 + I4). Two properties,
    both of them about WHEN work happens rather than what it computes:
      * a warm ``get_field()`` returns THE SAME OBJECT — no signature, no DB
        read, no raster. That is the whole point: ``ground_y`` runs per walk
        report and (from task 4) per nav cell, and hashing every area per call
        measured 1.42 ms, i.e. ~14 s for a 10 000-cell route. After the fix the
        warm call is 0.0016 ms.
      * the raster is written BY THE WRITE, not by the next reader: right after
        ``save_height_area`` the stored grid already carries the current
        signature, without anyone having sampled anything. Rastering costs
        0.1–0.4 s, and lazily that bill lands on whoever asks next — on a live
        world the ``POST /play/pos`` of a walker.
    ``invalidate_cache()`` drops the object again (the next call rebuilds or
    reloads, so it is a DIFFERENT object with the same content).
    THE THIRD PROPERTY is ``current_sig()`` (E8 task 5), the signature the
    worldmap poll carries: warm it must equal ``height_sig()`` — a cached
    signature that outlived its world would send every client to refetch never
    or forever — and cold it must fall back WITHOUT building the field, i.e.
    ``cached_sig()`` is still None afterwards. A write in between is the
    discriminating case: the cache is dropped by the writer, so the poll may
    not answer out of it.
[10] ROUTES. POST assigns the id; PUT on an unknown id is 404 and creates
    NOTHING (the store is an upsert, so a repeated stale PUT would otherwise
    resurrect a deleted hill); PUT on a live id replaces it; DELETE twice is
    404 the second time. GET /play/heightfield returns exactly the field plus
    its signature.
[11] THE PLATEAU (E8 task 4) — AND IT IS OPT-IN (decision 2026-08-13). A place
    that ASKS FOR IT (``level_ground``) is put ON the world and the ground
    under it is levelled to carry it — the footprint pinned to the authored
    height at its own CENTRE, dilated by one cell so the ramp starts outside
    the place (the flat-hull pattern of the scene relief). A place that does NOT ask for
    it changes no height at all: the landscape runs through it, because "the
    landscape should not mind the place — one may even want a rise inside it".

    NO AREAS, NO GRID. A location on an unpainted world levels 0 onto 0: the
    raster stays empty (rows/cols 0), because a grid of zeros describes exactly
    what its absence describes.

    THE CASE: HILL again (square (0,0)-(40,40), height 5, falloff 4) and a
    location "Hut" at (2, 2) with plan_width_m 8, yaw 0 — footprint x, z in
    [-2, 6], deliberately on the FLANK, where levelling has something to do.
    The SAME hut is measured twice, once per flag state.

    0) FLAG OFF (the default). ``placed_footprints()`` does not list the hut at
       all, so the raster gets no footprint: the grid is the plain hill raster
       of [1] (13 × 13, origin (-4,-4)) and the field is byte-for-byte the pure
       area result. The authored landscape answers everywhere, hut or no hut:
         h( 4, 4) = 5      the support point 4 m inside the outline
         h( 6, 6) = 5      distance min(6, 34) = 6 > falloff 4, so full height
         h( 8, 4) = 5      the support point where the plateau's ramp would be
         h(-1, 5) = 0      outside the outline — all four corners of its cell
                           are 0 (x = -4 and x = 0 are outside/ON the outline)
       NOT MEASURED AT THE CENTRE: h(2,2) is 1.25 in BOTH states (a plateau is
       pinned to exactly the authored height at its centre), so the centre is
       the one point that cannot tell the two apart.
       RED COUNTER-PROBE, executed: with ``placed_footprints`` replaced by its
       pre-decision version (no flag filter) every one of those four points
       moves to the plateau's 1.25 and the grid grows to 15 × 15.

    0b) THE SIGNATURE FOLLOWS THE FLAG. Setting it changes ``height_sig``
       without the hut moving a centimetre (it enters the hashed list of
       places), and clearing it again returns EXACTLY the signature from before
       — the basis is the same data, so the hash has to be.

    a) THE GRID GROWS to hold the plateau and its ramp. The footprint box
       [-2,6]^2 widened by one step is [-6,10]^2, so the union with the hill's
       box is (-6,-6)-(40,40):
         origin = floor(-6/4)·4 - 4 = -12  (both axes)
         points = ceil((40 + 4 + 12)/4) + 1 = 14 + 1 = 15 per axis
       Support point (i, j) therefore sits at (-12 + 4i, -12 + 4j). Without the
       growth the plateau would be cut off at the border and meet the flat
       world outside the grid as a cliff.

    b) THE PLATEAU HEIGHT is the AREA raster sampled at the centre (2, 2), read
       BEFORE anything is levelled: the cell (0,0)-(4,4) has the corners
       (0,0)=0, (4,0)=0, (0,4)=0 (all ON the outline) and (4,4)=5 (4 m in), and
       both fractions are 0.5 -> 0.25 · 5 = 1.25 m. Same number as [5], on a
       differently anchored grid — the lattice is the same lattice.

    c) THE PINNED POINTS are those within one step of the footprint (the exact
       distance to the rectangle, not to its box): x in {-4, 0, 4, 8}
       (overshoots 2, 0, 0, 2) and the same in z, so i, j in {2, 3, 4, 5} —
       every combination, since the worst pair is hypot(2, 2) = 2.83 <= 4.
         (i,j) = (3,3) = (0,0)  authored 0 -> 1.25   the place raises the ground
         (i,j) = (4,4) = (4,4)  authored 5 -> 1.25   and cuts it down
         (i,j) = (2,2) = (-4,-4) authored 0 -> 1.25  the dilation ring, OUTSIDE
                                                     the footprint
       The border ring of the grid stays 0 (i or j 0 or 14) — the invariant the
       clamp outside the grid rests on.

    d) FLAT ACROSS THE WHOLE PLACE: sampled at the centre (2,2), at the corner
       (6,6) and at (-1,5) the field answers 1.25 everywhere, because every
       cell touching the footprint has four pinned corners.

    e) THE RAMP is the ONE cell between the ring and the landscape, and it is
       linear. East of the ring, on the row z = 4: h(8,4) = 1.25 (pinned),
       h(12,4) = 5 (authored: distance 4 to the nearest edge), so
         h(9,4)  = 1.25 + 3.75·0.25 = 2.1875
         h(10,4) = 3.125
         h(11,4) = 4.0625
       — monotone up. HONESTLY: 3.75 m over 4 m is atan(0.9375) = 43.2 deg,
       past the default max_slope_deg of 40 — this rim is a wall a walker
       cannot climb, and gets in through an opening (§ A15 no. 8 exempts them).
       That is the authoring limit the height tool warns about: a ramp of one
       cell carries tan(40 deg)·4 = 3.36 m.

    f) THE PLATEAU WANDERS WITH THE PLACE. Moving the hut to (20, 2) changes
       the signature (placements are part of it), frees (4,4) back to its
       authored 5 and levels the new footprint instead: the new centre reads
       h(20,0) = 0 (ON the outline) and h(20,4) = 5, i.e. 2.5 at z = 2, and
       (22,4) and (18,4) — both authored 5, both inside the new footprint — are
       cut to that same 2.5. Deleting the hut gives all of them back their 5.
[12] TWO PLACES ON ONE HILL (review finding I3). Everything in [11] has a
    single footprint, and two rules the docstrings call load-bearing are
    invisible with one: that every plateau height is sampled BEFORE any
    levelling, and that on overlap the SMALLEST footprint wins. Both need a
    nested pair.

    THE CASE, on the same HILL: SQUARE at (6, 6) with plan_width_m 24
    (footprint [-6, 18]²) and HUT at (2, 2) with plan_width_m 4 (footprint
    [0, 4]², entirely inside the square). BOTH FLAGGED ``level_ground`` — an
    unflagged place is not in the list at all, so nesting only has a question
    to answer between two levelling ones.

    THE GRID: the boxes grown by one step are [-10, 22]² and [-4, 8]², so the
    bounds are (-10,-10)-(40,40):
      origin = floor(-10/4)·4 - 4 = -16,  points = ceil((40+4+16)/4)+1 = 16
    Support point (i, j) sits at (-16 + 4i, -16 + 4j).

    THE TWO HEIGHTS, both read off the UNTOUCHED area raster:
      SQUARE at (6, 6): the cell (4,4)-(8,8) has all four corners at the full
                        5 (each 4 m or more inside the outline)      -> 5
      HUT    at (2, 2): corners (0,0), (4,0), (0,4) all ON the outline -> 0,
                        (4,4) -> 5, both fractions 0.5               -> 1.25
    The widest is levelled first, so the HUT writes last and wins where they
    overlap:
      ground_y(2, 2)   = 1.25     the hut's own plateau
      ground_y(14, 14) = 5        the square's, outside the hut's ring
      (i,j) = (4,4) = (0,0)   -> 1.25   pinned by the hut
      (i,j) = (7,5) = (12,4)  -> 5      the square's, past the hut's ring
      (i,j) = (3,3) = (-4,-4) -> 5      the hut's ring has ROUNDED corners
                                        (overshoot pair (4,4), hypot 5.66 > 4),
                                        so the square shows through there
      (i,j) = (6,6) = (8,8)   -> 5      the same corner on the far side

    TWO RED COUNTER-PROBES, and they are the point of the case:
      * LARGEST WINS (the sort key reversed): the hut is levelled first and
        the square overwrites it -> ground_y(2,2) = 5, not 1.25.
      * SAMPLED WHILE WRITING (h0 read inside the write loop instead of all of
        them up front): the square has already pinned (0,0)…(4,4) to 5 when
        the hut asks for its own height, so the hut levels to 5 as well ->
        ground_y(2,2) = 5. Which is the failure mode the "before" exists for:
        the answer would depend on the order the DB returned the two places.

[13] THE MICRO-RELIEF OF A TERRAIN KIND (decision 2026-08-13). A terrain type
    may carry ``relief_amplitude_m`` (0.05..2.0 m) and ``relief_wave_m``
    (8..200 m, absent = 32 m), and the world heightfield gets random small
    hills wherever that kind is painted. It is BAKED IN here so that server
    gate, client mirror and both renderers read the one ``heights`` array.

    THE FORMULA, value noise on a world-origin-anchored lattice of edge
    ``wave``:

      seed(kind) = FNV-1a 32 over the kind NAME (no seed field exists):
                   h = 2166136261; for each UTF-8 byte b:
                   h = ((h XOR b) · 16777619) mod 2**32
      rnd(u, v)  = XorShift32((seed + u·73856093 + v·19349663) mod 2**32)
                   .next01() · 2 − 1              (the old scene-relief hash)
      h_relief   = bilinear(rnd) over the four corners of
                   (u, v) = floor((x, z)/wave)    · amplitude

    and the PASS ORDER of the raster is
      areas (strongest |value|) → micro-relief (ADDITIVE) → plateaus (win).

    THE KIND AT A POINT is the topmost painted area containing it — the very
    ``terrain_query.kind_at`` rule (last hit wins), so a flat kind painted over
    a bumpy one flattens what it covers. A point NO area covers gets no relief:
    the unpainted world stays flat, which is also why the grid can be bounded
    at all (its base box is the height areas UNION the relief-carrying painted
    areas).

    THE FIXTURE: kind "g" with amplitude 1.0 and wave 16, kind "p" flat, and
    HILL (the square (0,0)-(40,40), height 5, falloff 4) from [1] — so the grid
    is the 13 × 13 raster of [1], origin (−4,−4), and every point 4 m or more
    inside the outline carries the full authored 5.

    a) THE SEED, by hand. "g" is the single byte 0x67 = 103:
         2166136261 XOR 103 = 2166136226
         2166136226 · 16777619 mod 2**32 = 3792446982       = seed("g")
    b) ONE SUPPORT POINT, by hand: (16, 16). With wave 16 it is the lattice
       corner (u, v) = (1, 1) exactly (both fractions 0), so the bilinear mix
       collapses to that one corner:
         state = 3792446982 + 73856093 + 19349663 = 3885652738
         xorshift32:  x ^= x<<13  -> 2902072066
                      x ^= x>>17  -> 2902084991
                      x ^= x<<5   -> 867426975
         next01 = 867426975 / 2**32 = 0.201963580912
         rnd    = 0.201963580912 · 2 − 1 = −0.596072838176
       Amplitude 1.0, so the relief at (16,16) is −0.596072838176 m and the
       support point reads 5 − 0.596072838176 = 4.403927161824 -> stored 4.404
       (the raster rounds to millimetres).
    c) BETWEEN CORNERS: (20, 16) is fx = 1.25, i.e. tx = 0.25 on the row v = 1:
         rnd(1,1) = −0.596072838176,  rnd(2,1) = −0.057022939436
         0.75·(−0.596072838176) + 0.25·(−0.057022939436) = −0.461310363491
    d) NEGATIVE LATTICE INDICES, and they are not an edge case but half the
       world. rnd(−1,−1) = −0.673446102068 (state 3699241226), so on a world
       painted ONLY with "g" over (−40,−40)-(40,40) — no height area at all,
       which is the case that proves a relief kind grows a grid of its own —
       the support point (−16,−16) reads exactly that. The arithmetic wraps
       properly: at u = −60 the state is 3792446982 − 60·73856093 =
       −638918598, which as an unsigned 32-bit number is 3656048698, and
       ``& 0xFFFFFFFF`` in Python IS that number (checked against ``% 2**32``).
    e) ADDITIVE, AND AFTER THE AREAS. (16,16) reads 4.404, not the bare 5.0.
       RED COUNTER-PROBE, EXECUTED: the same two passes in the wrong order —
       relief first, then the |max| rule of the area pass — give exactly 5.0 at
       that point, because 5 deflects more strongly than 4.404 and overwrites
       it. That mutant is built in this script from the module's own pieces
       (``_apply_micro_relief`` + ``area_height_at``).
    f) THE PLATEAU STILL WINS. A place at (20,20) with plan_width_m 16 and
       ``level_ground`` set is pinned to the ground at its centre READ FROM THE
       FINISHED, BUMPY landscape: relief(20,20) = −0.292580240552, so the
       plateau stands at 5 − 0.292580240552 = 4.707419759448 -> 4.707. The
       support point (16,16) from b) now reads 4.707 as well — the noise is not
       added on top of a levelled place.
    g) THE TOPMOST KIND DECIDES. A flat "p" area painted over (14,14)-(40,40)
       takes the relief away where it covers: (20,20) is back to the authored
       5.0 while (4,4) still carries 5 + 0.085719348543 = 5.086. Both points
       are cross-checked against ``terrain_query.kind_at``, which is the rule
       being mirrored.
    h) THE 0-RING IS UNTOUCHED (i or j 0 or 12) — the invariant "outside the
       grid the border value applies" rests on it, and it holds without a
       special case because the grid always reaches one full step past every
       painted box.
    i) DETERMINISM: rastering the same inputs twice yields the identical grid,
       and a world whose catalog carries NO relief rasters byte-for-byte like
       one with no terrain painted at all (the pass is a true no-op).
    j) THE SIGNATURE, and it is the whole write-path story:
         painting a flat kind          -> unchanged   (no re-raster is owed)
         painting "g" while it is flat -> unchanged
         giving "g" an amplitude       -> CHANGES
         changing that amplitude       -> CHANGES
         taking it away again          -> EXACTLY the signature from the start
       The last one is the strong form: the basis is the same data again, so
       the hash has to be the same number again.
    k) THE READER CLAMPS TOO. A catalog row that never met the sanitizer (a
       hand-edited DB row) is still read through the same limits:
       amplitude 99 -> 2.0, wave 2 -> 8.0 (NYQUIST: 2 × the 4 m step, a wave
       the grid could not carry), no wave -> 32.0, amplitude 0/junk -> no
       relief at all.

Usage:  ./.venv/bin/python scripts/smoke_heightfield.py
"""
import asyncio
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="heightfield-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="heightfield-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import heightfield as hf  # noqa: E402
from app.core.world_geometry import ground_y  # noqa: E402
from app.models import heightfield as store  # noqa: E402
from app.models.world import (_load_world_data, _save_world_data,  # noqa: E402
                              add_location, delete_location,
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


def near(label, actual, expected, tol=1e-9):
    global CHECKED
    CHECKED += 1
    ok = abs(float(actual) - float(expected)) <= tol
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_not(label, actual, forbidden):
    """The other half of a red counter-probe: the value a MUTANT would
    produce, asserted absent."""
    global CHECKED
    CHECKED += 1
    ok = actual != forbidden
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — this is the mutant's {forbidden!r}"))
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


def square(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


def at(field, i, j):
    """The stored support point (i, j) — the raster, not a sample."""
    return field["heights"][j][i]


HILL = {"id": "hill", "polygon": square(0, 0, 40, 40),
        "height_m": 5.0, "falloff_m": 4.0}
SOFT = {"id": "soft", "polygon": square(0, 0, 40, 40),
        "height_m": 5.0, "falloff_m": 8.0}
BIG = {"id": "big", "polygon": square(20, 20, 60, 60),
       "height_m": 9.0, "falloff_m": 4.0}
PIT = {"id": "pit", "polygon": square(20, 20, 60, 60),
       "height_m": -9.0, "falloff_m": 4.0}
VALLEY = {"id": "valley", "polygon": square(0, 0, 40, 40),
          "height_m": -3.0, "falloff_m": 4.0}

print("[1] raster geometry of one area")
f1 = hf.rasterize([HILL])
check("origin", (f1["origin_x"], f1["origin_z"]), (-4.0, -4.0))
check("step", f1["step_m"], 4.0)
check("shape", (f1["rows"], f1["cols"]), (13, 13))
near("(-4,-4) outside", at(f1, 0, 0), 0.0)
near("(0,0) on the outline", at(f1, 1, 1), 0.0)
near("(4,4) one falloff in", at(f1, 2, 2), 5.0)
near("(20,20) deep inside", at(f1, 6, 6), 5.0)
near("(40,20) on the east edge", at(f1, 11, 6), 0.0)
near("(44,44) the 0 ring", at(f1, 12, 12), 0.0)

print("[2] the ramp (falloff 8)")
f2 = hf.rasterize([SOFT])
near("(4,4) half way up", at(f2, 2, 2), 2.5)
near("(8,8) at the top", at(f2, 3, 3), 5.0)
near("(20,20) capped", at(f2, 6, 6), 5.0)

print("[3] overlap — the strongest deflection wins")
f3 = hf.rasterize([HILL, BIG])
check("shape", (f3["rows"], f3["cols"]), (18, 18))
near("(32,32) the higher area", at(f3, 9, 9), 9.0)
near("(4,4) only the hill", at(f3, 2, 2), 5.0)
near("(56,56) only the big one", at(f3, 15, 15), 9.0)
f3b = hf.rasterize([HILL, PIT])
near("(32,32) hill against pit", at(f3b, 9, 9), -9.0)
f3c = hf.rasterize([VALLEY])
near("(20,20) a hollow survives", at(f3c, 6, 6), -3.0)
# The order of the list must not decide anything (compared as a whole grid,
# reported as one word — 18 × 18 numbers in the log are not a check).
check("order does not matter",
      hf.rasterize([BIG, HILL])["heights"] == f3["heights"], True)

print("[4] the sanitizer")
check("id prefix", store.sanitize_height_area(
    {"polygon": square(0, 0, 1, 1)})["id"][:3], "ha_")
check("height clamped up", store.sanitize_height_area(
    {"polygon": square(0, 0, 1, 1), "height_m": 80})["height_m"], 50.0)
check("height clamped down", store.sanitize_height_area(
    {"polygon": square(0, 0, 1, 1), "height_m": -80})["height_m"], -50.0)
check("junk height is flat", store.sanitize_height_area(
    {"polygon": square(0, 0, 1, 1), "height_m": "abc"})["height_m"], 0.0)
check("absent height is flat", store.sanitize_height_area(
    {"polygon": square(0, 0, 1, 1)})["height_m"], 0.0)
check("NaN height is flat", store.sanitize_height_area(
    {"polygon": square(0, 0, 1, 1), "height_m": float("nan")})["height_m"], 0.0)
check("negative falloff is a wall", store.sanitize_height_area(
    {"polygon": square(0, 0, 1, 1), "falloff_m": -5})["falloff_m"], 0.0)
check("falloff clamped", store.sanitize_height_area(
    {"polygon": square(0, 0, 1, 1), "falloff_m": 2000})["falloff_m"], 1000.0)
raises_value_error("2 points", lambda: store.sanitize_height_area(
    {"polygon": [[0, 0], [1, 1]]}))
raises_value_error("257 points", lambda: store.sanitize_height_area(
    {"polygon": [[0, 0]] * 257}))
raises_value_error("coordinate 1e9", lambda: store.sanitize_height_area(
    {"polygon": square(0, 0, 1e9, 1)}))
raises_value_error("NaN coordinate", lambda: store.sanitize_height_area(
    {"polygon": [[0, 0], [1, 0], [float("nan"), 1]]}))
raises_value_error("dict vertex", lambda: store.sanitize_height_area(
    {"polygon": [[0, 0], [1, 0], {"x": 1, "z": 1}]}))
raises_value_error("not an object", lambda: store.sanitize_height_area("hill"))

print("[5] signature, store and ground_y")
sig_empty = store.height_sig()
check("signature length", len(sig_empty), 10)
saved = store.save_height_area({"polygon": square(0, 0, 40, 40),
                                "height_m": 5, "falloff_m": 4})
sig_one = store.height_sig()
check("saving changes the signature", sig_one != sig_empty, True)
near("ground_y at a support point", ground_y(20, 20), 5.0)
near("ground_y between four points", ground_y(2, 2), 1.25)
near("ground_y on a grid line", ground_y(2, 20), 2.5)
near("ground_y outside the grid", ground_y(-100, -100), 0.0)
grid = store.load_grid()
check("the stored grid carries its signature", grid["sig"], sig_one)
check("the stored shape", (grid["rows"], grid["cols"]), (13, 13))
store.save_height_area({"id": saved["id"], "polygon": square(0, 0, 40, 40),
                        "height_m": 9, "falloff_m": 4})
check("editing changes the signature", store.height_sig() != sig_one, True)
near("ground_y follows the edit", ground_y(20, 20), 9.0)
check("delete", store.delete_height_area(saved["id"]), True)
check("the signature comes back", store.height_sig(), sig_empty)
near("ground_y is flat again", ground_y(20, 20), 0.0)
check("deleting twice", store.delete_height_area(saved["id"]), False)

print("[6] the lattice is anchored at the world origin")
FAR = {"id": "far", "polygon": square(100, 0, 140, 40),
       "height_m": 5.0, "falloff_m": 4.0}
# Its west corner is NOT a multiple of the step, on purpose: an aligned shape
# would give the naive origin (min − step) the right answer by accident.
WEST = {"id": "west", "polygon": square(-501, 0, -461, 40),
        "height_m": 2.0, "falloff_m": 4.0}
alone = hf.rasterize([FAR])
grown = hf.rasterize([FAR, WEST])
check("origin alone", alone["origin_x"], 96.0)
check("origin after the world grew west", grown["origin_x"], -508.0)
check("and it is still on the lattice through (0,0)",
      grown["origin_x"] % hf.DEFAULT_STEP_M, 0.0)
# THE measurement: on the FLANK, where a shifted lattice changes the answer.
near("the flank, rastered alone", hf.sample_height(alone, 102, 20), 2.5)
near("the flank, after the world grew west",
     hf.sample_height(grown, 102, 20), 2.5)
near("and the ramp is really a ramp, not a plateau",
     hf.sample_height(alone, 104, 20), 5.0)

print("[7] coarsening past the point budget")
huge = hf.rasterize([{"id": "huge", "polygon": square(0, 0, 8000, 8000),
                      "height_m": 5.0, "falloff_m": 4.0}])
check("step doubled to", huge["step_m"], 32.0)
check("shape", (huge["rows"], huge["cols"]), (253, 253))

print("[8] the shared sampler's table")
FIELD = {"origin_x": -4.0, "origin_z": -4.0, "step_m": 4.0,
         "rows": 3, "cols": 3,
         "heights": [[0, 0, 0], [0, 5, 0], [0, 0, 0]]}
near("(0,0) the peak", hf.sample_height(FIELD, 0, 0), 5.0)
near("(2,0) half a cell east", hf.sample_height(FIELD, 2, 0), 2.5)
near("(2,2) diagonally between", hf.sample_height(FIELD, 2, 2), 1.25)
near("(0,-2) half a cell north", hf.sample_height(FIELD, 0, -2), 2.5)
near("(-2,0) half a cell west", hf.sample_height(FIELD, -2, 0), 2.5)
near("(-4,-4) the corner point", hf.sample_height(FIELD, -4, -4), 0.0)
near("(100,0) far east clamps to the border",
     hf.sample_height(FIELD, 100, 0), 0.0)
near("(-100,-100) far north-west", hf.sample_height(FIELD, -100, -100), 0.0)
near("a single row carries no relief",
     hf.sample_height({"origin_x": 0.0, "origin_z": 0.0, "step_m": 4.0,
                       "rows": 1, "cols": 3, "heights": [[1, 2, 3]]}, 4, 0), 0.0)
near("the empty world as the endpoint sends it",
     hf.sample_height({"origin_x": 0.0, "origin_z": 0.0, "step_m": 4.0,
                       "rows": 0, "cols": 0, "heights": []}, 0, 0), 0.0)
near("a ragged row is a height, not a crash",
     hf.sample_height({"origin_x": 0.0, "origin_z": 0.0, "step_m": 4.0,
                       "rows": 2, "cols": 2, "heights": [[0, 10], [0]]}, 2, 2), 2.5)
near("rows/cols lying about the array does not matter",
     hf.sample_height({"origin_x": 0.0, "origin_z": 0.0, "step_m": 4.0,
                       "rows": 99, "cols": 99,
                       "heights": [[0, 10], [0, 10]]}, 2, 2), 5.0)
near("no field at all", hf.sample_height(None, 0, 0), 0.0)

print("[9] the cache contract")
_cache_area = store.save_height_area({"polygon": square(200, 200, 240, 240),
                                      "height_m": 6, "falloff_m": 8})
# I4: the WRITE rastered and stored it — nobody has sampled anything yet.
_stored = store.load_grid()
check("the write left a stored raster", _stored is not None, True)
check("and it is the current one", _stored["sig"], store.height_sig())
# I1: a warm read is the same object, so it cost neither a hash nor a query.
check("a warm get_field is the same object",
      hf.get_field() is hf.get_field(), True)
_warm = hf.get_field()
hf.invalidate_cache()
check("invalidating drops it", hf.get_field() is not _warm, True)
check("and the content is the same", hf.get_field()["heights"] == _warm["heights"],
      True)
# The poll's signature: warm it comes out of the cache and is the real one.
hf.get_field()
check("a warm current_sig is the real signature",
      hf.current_sig(), store.height_sig())
# ...and a WRITE in between may not be answered out of the old cache.
_cache_area2 = store.save_height_area({"polygon": square(300, 300, 340, 340),
                                       "height_m": 3, "falloff_m": 4})
check("a write moves the polled signature too",
      hf.current_sig(), store.height_sig())
check("...and it really moved", hf.current_sig() != _stored["sig"], True)
store.delete_height_area(_cache_area2["id"])
# Cold: the same answer, and NOT by rastering — the poll never builds a field.
hf.invalidate_cache()
check("a cold current_sig is still the real signature",
      hf.current_sig(), store.height_sig())
check("...and it built no field to say so", hf.cached_sig(), None)
store.delete_height_area(_cache_area["id"])

print("[10] the routes")
from fastapi import HTTPException  # noqa: E402
from app.routes.world import (delete_height_area_route,  # noqa: E402
                              post_height_area_route, put_height_area_route)
from app.routes.play import get_heightfield_route  # noqa: E402


class _FakeRequest:
    """Minimal stand-in: the routes only ever await ``request.json()``."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


posted = asyncio.run(post_height_area_route(_FakeRequest(
    {"id": "ignored", "polygon": square(0, 0, 40, 40),
     "height_m": 5, "falloff_m": 4})))
new_id = posted["area"]["id"]
check("POST assigns its own id", new_id != "ignored" and new_id[:3] == "ha_",
      True)


def route_status(fn, *args):
    try:
        asyncio.run(fn(*args)) if asyncio.iscoroutinefunction(fn) else fn(*args)
    except HTTPException as e:
        return e.status_code
    return 200


check("PUT on an unknown id", route_status(
    put_height_area_route, "ha_nope",
    _FakeRequest({"polygon": square(0, 0, 4, 4)})), 404)
check("nothing was created", len(store.list_height_areas()), 1)
check("PUT on the live id", route_status(
    put_height_area_route, new_id,
    _FakeRequest({"polygon": square(0, 0, 40, 40), "height_m": 7,
                  "falloff_m": 4})), 200)
check("the edit landed", store.list_height_areas()[0]["height_m"], 7.0)

payload = get_heightfield_route(user={"role": "user"})
check("payload keys", sorted(payload.keys()),
      ["cols", "heights", "origin_x", "origin_z", "rows", "sig", "step_m"])
check("payload signature", payload["sig"], store.height_sig())
check("payload shape", (payload["rows"], payload["cols"]), (13, 13))
near("payload height at (20,20)",
     payload["heights"][6][6], 7.0)

check("DELETE", route_status(delete_height_area_route, new_id), 200)
check("DELETE again", route_status(delete_height_area_route, new_id), 404)

print("\n[11] the plateau under a footprint — and its opt-in flag")
for _a in store.list_height_areas():
    store.delete_height_area(_a["id"])


def set_level_ground(loc_id, on):
    """Flip the ``level_ground`` flag of a placed location — the ONE input of
    the opt-in flattening. Written through ``_save_world_data``, i.e. the same
    writer the PUT route uses, so the re-raster hook runs with it."""
    data = _load_world_data()
    for loc in data["locations"]:
        if loc.get("id") == loc_id:
            loc["level_ground"] = bool(on)
    _save_world_data(data)


def unfiltered_footprints():
    """THE MUTANT of the red counter-probe below: ``placed_footprints`` as it
    was before the decision — every placed location levels, flag or no flag."""
    from app.core.world_geometry import placed_footprint
    from app.models.world import list_locations
    out = []
    for loc in list_locations():
        fp = placed_footprint(loc)
        if fp is None:
            continue
        cx, cz, width, yaw = fp
        out.append((round(cx, 2), round(cz, 2), round(width, 2),
                    round(yaw, 1)))
    return out


HUT = add_location("Hut", "a place on the flank")["id"]
_world = _load_world_data()
for _loc in _world["locations"]:
    if _loc.get("id") == HUT:
        _loc["map3d"] = {"plan_width_m": 8}
_save_world_data(_world)
update_location_position(HUT, 2.0, 2.0, 0.0)

check("a placed location alone raises no grid", hf.get_field()["rows"], 0)
check("...and the ground stays flat", ground_y(2, 2), 0.0)

store.save_height_area(dict(HILL))
check("an UNFLAGGED place is no input of the raster",
      store.placed_footprints(), [])
field = hf.get_field()
check("so the grid is the plain hill raster",
      (field["rows"], field["cols"]), (13, 13))
check("...anchored at (-4,-4), not grown for a plateau",
      (field["origin_x"], field["origin_z"]), (-4.0, -4.0))
check("...and the field IS the pure area result",
      field["heights"] == hf.rasterize(store.list_height_areas())["heights"],
      True)
near("the landscape runs through the place: h(4,4)", ground_y(4, 4), 5.0)
near("...at the footprint corner (6,6)", ground_y(6, 6), 5.0)
near("...where the plateau's ramp would be, h(8,4)", ground_y(8, 4), 5.0)
near("...and outside the outline h(-1,5) is still 0", ground_y(-1, 5), 0.0)
near("the CENTRE cannot tell the two states apart", ground_y(2, 2), 1.25)

_real_footprints = store.placed_footprints
store.placed_footprints = unfiltered_footprints
hf.invalidate_cache()
_mutant = hf.get_field()
check("RED COUNTER-PROBE: without the flag filter the grid grows again",
      (_mutant["rows"], _mutant["cols"]), (15, 15))
near("...and the mutant levels (6,6) to the plateau", ground_y(6, 6), 1.25)
near("...and (4,4)", ground_y(4, 4), 1.25)
near("...and (8,4)", ground_y(8, 4), 1.25)
near("...and (-1,5)", ground_y(-1, 5), 1.25)
store.placed_footprints = _real_footprints
hf.invalidate_cache()
near("the real filter puts the landscape back", ground_y(6, 6), 5.0)

_sig_flat = store.height_sig()
set_level_ground(HUT, True)
check("flagging the place changes the signature — it never moved",
      store.height_sig() != _sig_flat, True)
field = hf.get_field()
check("the grid grew for the plateau + ramp",
      (field["rows"], field["cols"]), (15, 15))
check("...anchored one ring outside (-6, -6)",
      (field["origin_x"], field["origin_z"]), (-12.0, -12.0))
near("the plateau height = the authored ground at the centre",
     at(field, 3, 3), 1.25)
near("the levelling RAISES (0,0) from 0", at(field, 3, 3), 1.25)
near("...and CUTS (4,4) down from 5", at(field, 4, 4), 1.25)
near("the dilation ring outside the footprint, (-4,-4)", at(field, 2, 2), 1.25)
check("the border ring is still 0",
      [at(field, 0, 0), at(field, 14, 14), at(field, 0, 7), at(field, 7, 14)],
      [0.0, 0.0, 0.0, 0.0])
near("flat at the centre", ground_y(2, 2), 1.25)
near("flat at the footprint corner (6,6)", ground_y(6, 6), 1.25)
near("flat at (-1, 5)", ground_y(-1, 5), 1.25)
near("the ramp starts at the ring, h(8,4)", ground_y(8, 4), 1.25)
near("h(9,4)", ground_y(9, 4), 2.1875)
near("h(10,4)", ground_y(10, 4), 3.125)
near("h(11,4)", ground_y(11, 4), 4.0625)
near("h(12,4) — the authored landscape again", ground_y(12, 4), 5.0)
check("the ramp is monotone",
      [round(ground_y(8 + k, 4), 4) for k in range(5)]
      == sorted(round(ground_y(8 + k, 4), 4) for k in range(5)), True)
check("...and this rim is steeper than a walker climbs (43.2 deg)",
      round(math.degrees(math.atan2(5.0 - 1.25, 4.0)), 1), 43.2)

set_level_ground(HUT, False)
near("clearing the flag gives the landscape back at (6,6)",
     ground_y(6, 6), 5.0)
check("...the grid shrinks to the plain hill raster",
      (hf.get_field()["rows"], hf.get_field()["cols"]), (13, 13))
check("...and the signature is EXACTLY the one from before the flag",
      store.height_sig(), _sig_flat)
set_level_ground(HUT, True)
near("flagging it again levels (6,6) once more", ground_y(6, 6), 1.25)

_sig_before = store.height_sig()
update_location_position(HUT, 20.0, 2.0, 0.0)
check("moving the place changes the height signature",
      store.height_sig() != _sig_before, True)
near("the old plateau is gone — (4,4) is the hill again", ground_y(4, 4), 5.0)
near("the new plateau stands at the new centre", ground_y(20, 2), 2.5)
near("...and cut (22,4) down from 5", ground_y(22, 4), 2.5)
near("...and (18,4), inside it, likewise", ground_y(18, 4), 2.5)

delete_location(HUT)
near("deleting the place restores the hill at (18,4)", ground_y(18, 4), 5.0)
near("...and at (22,4)", ground_y(22, 4), 5.0)
check("...and the grid is the plain hill raster again",
      (hf.get_field()["rows"], hf.get_field()["cols"]), (13, 13))

print("\n[12] two places on one hill — sampled before, smallest wins")


def place_square(name, x, z, width):
    """A placed location with a scale anchor and the flattening flag — the
    three inputs the raster has of a place."""
    loc_id = add_location(name, "plateau smoke")["id"]
    data = _load_world_data()
    for loc in data["locations"]:
        if loc.get("id") == loc_id:
            loc["map3d"] = {"plan_width_m": width}
            loc["level_ground"] = True
    _save_world_data(data)
    update_location_position(loc_id, x, z)
    return loc_id


SQUARE = place_square("Square", 6.0, 6.0, 24.0)
HUT2 = place_square("Hut on the square", 2.0, 2.0, 4.0)
field = hf.get_field()
check("the grid holds both plateaus", (field["rows"], field["cols"]), (16, 16))
check("...anchored at (-16, -16)",
      (field["origin_x"], field["origin_z"]), (-16.0, -16.0))
_bare = hf.rasterize(store.list_height_areas())
near("the square's height, read off the UNTOUCHED raster",
     hf.sample_height(_bare, 6, 6), 5.0)
near("the hut's, likewise", hf.sample_height(_bare, 2, 2), 1.25)
near("the SMALLEST footprint wins: ground_y(2,2)", ground_y(2, 2), 1.25)
check_not("...and it is neither of the two mutants' 5.0", ground_y(2, 2), 5.0)
near("the square's plateau outside the hut's ring", ground_y(14, 14), 5.0)
near("(0,0) belongs to the hut", at(field, 4, 4), 1.25)
near("(12,4) to the square", at(field, 7, 5), 5.0)
near("(-4,-4): the hut's ring has rounded corners", at(field, 3, 3), 5.0)
near("(8,8): the same corner on the far side", at(field, 6, 6), 5.0)
delete_location(HUT2)
near("without the hut the square levels (2,2) to its own 5",
     ground_y(2, 2), 5.0)
delete_location(SQUARE)

print("\n[13] the micro-relief of a terrain kind")
from app.core import terrain_types  # noqa: E402
from app.core.terrain_query import kind_at  # noqa: E402
from app.models import terrain  # noqa: E402

for _a in store.list_height_areas():
    store.delete_height_area(_a["id"])

# The hand-derived constants of the header — written out here so a failure
# says WHICH number moved, and so the expectations never come from the module.
SEED_G = 3792446982
RND_11 = -0.596072838176            # rnd(1, 1)   — [13]b, xorshift by hand
RND_21 = -0.057022939436            # rnd(2, 1)
RND_M11 = -0.673446102068           # rnd(−1, −1) — [13]d
R_16_16 = RND_11                    # wave 16: (16,16) IS the corner (1,1)
R_20_16 = 0.75 * RND_11 + 0.25 * RND_21
R_20_20 = -0.292580240552           # [13]f, the plateau's ground
R_4_4 = 0.085719348543              # [13]g


def set_relief(kind, amplitude=None, wave=None):
    """Write one terrain kind, with or without a micro-relief."""
    meta = {}
    if amplitude is not None:
        meta["relief_amplitude_m"] = amplitude
    if wave is not None:
        meta["relief_wave_m"] = wave
    terrain_types.save_world_type({"kind": kind, "name": kind.upper(),
                                   "color": "#7ac74f", "passable": True,
                                   "speed_factor": 1.0, "meta": meta})


def raster_now():
    """Rasterize from the CURRENT world — the four inputs get_field() reads."""
    return hf.rasterize(store.list_height_areas(),
                        footprints=store.placed_footprints(),
                        terrain_areas=terrain.list_areas(),
                        terrain_catalog=terrain_types.effective_catalog())


set_relief("g", amplitude=1.0, wave=16.0)
set_relief("p")
GRASS = terrain.save_area({"kind": "g", "polygon": square(0, 0, 40, 40)})
store.save_height_area(dict(HILL))

check("the seed is a hash of the kind NAME", hf.relief_seed("g"), SEED_G)
check("...and another kind gets an unrelated one",
      hf.relief_seed("p") != SEED_G, True)
check("the catalog entry reads back as (seed, amplitude, wave)",
      hf.relief_params("g", terrain_types.get_type("g")),
      (SEED_G, 1.0, 16.0))
check("a kind without an amplitude carries no relief",
      hf.relief_params("p", terrain_types.get_type("p")), None)
near("rnd(1,1) — the corner derived by hand",
     hf.lattice_noise(SEED_G, 1, 1), RND_11, 1e-11)
near("the relief at (16,16), a lattice corner",
     hf.micro_relief_at((SEED_G, 1.0, 16.0), 16, 16), R_16_16, 1e-11)
near("...and at (20,16), a quarter cell east",
     hf.micro_relief_at((SEED_G, 1.0, 16.0), 20, 16), R_20_16, 1e-11)

f13 = raster_now()
check("the grid is the plain hill raster — relief grows nothing new here",
      (f13["rows"], f13["cols"], f13["origin_x"], f13["origin_z"]),
      (13, 13, -4.0, -4.0))
near("(16,16): the authored 5 PLUS the hand-derived relief", at(f13, 5, 5),
     4.404, 5e-4)
check_not("...and not the bare area result", at(f13, 5, 5), 5.0)
near("(4,4) likewise", at(f13, 2, 2), 5.086, 5e-4)
check("the 0-ring is untouched",
      [at(f13, 0, 0), at(f13, 12, 12), at(f13, 0, 6), at(f13, 6, 12)],
      [0.0, 0.0, 0.0, 0.0])
check("rastering twice is the same grid",
      raster_now()["heights"] == f13["heights"], True)

# RED COUNTER-PROBE, executed: relief BEFORE the areas — the |max| rule of the
# area pass then overwrites every point the hill covers.
_relief = hf.relief_inputs(terrain.list_areas(),
                           terrain_types.effective_catalog())
_mut = [[0.0] * f13["cols"] for _ in range(f13["rows"])]
hf._apply_micro_relief(f13["origin_x"], f13["origin_z"], f13["step_m"],
                       _mut, _relief)
for _j in range(f13["rows"]):
    _pz = f13["origin_z"] + _j * f13["step_m"]
    for _i in range(f13["cols"]):
        _v = hf.area_height_at(HILL, f13["origin_x"] + _i * f13["step_m"], _pz)
        if _v is None:
            continue
        _cur = _mut[_j][_i]
        if abs(_v) > abs(_cur) or (abs(_v) == abs(_cur) and _v > _cur):
            _mut[_j][_i] = _v
near("RED COUNTER-PROBE: with the passes swapped (16,16) collapses to the "
     "bare 5.0", _mut[5][5], 5.0)

print("  [13d] negative lattice indices")
near("rnd(−1,−1)", hf.lattice_noise(SEED_G, -1, -1), RND_M11, 1e-11)
check("...and it is NOT the mirror of rnd(1,1)",
      round(hf.lattice_noise(SEED_G, -1, -1), 9)
      != round(-RND_11, 9), True)
near("a state that wraps past 0 (u = −60) is the unsigned 32-bit one",
     hf.lattice_noise(SEED_G, -60, 0),
     hf.lattice_noise((SEED_G - 60 * 73856093) % 4294967296, 0, 0), 1e-15)
store.delete_height_area(store.list_height_areas()[0]["id"])
terrain.delete_area(GRASS["id"])
WIDE = terrain.save_area({"kind": "g", "polygon": square(-40, -40, 40, 40)})
f13d = raster_now()
check("a relief kind alone builds a grid (no height area at all)",
      (f13d["rows"], f13d["cols"], f13d["origin_x"]), (23, 23, -44.0))
near("(−16,−16) is the corner rnd(−1,−1)", at(f13d, 7, 7), RND_M11, 5e-4)
terrain.delete_area(WIDE["id"])
GRASS = terrain.save_area({"kind": "g", "polygon": square(0, 0, 40, 40)})
store.save_height_area(dict(HILL))

print("  [13f] the plateau still wins")
PLACE = add_location("Bump", "a levelled place on bumpy ground")["id"]
_w = _load_world_data()
for _loc in _w["locations"]:
    if _loc.get("id") == PLACE:
        _loc["map3d"] = {"plan_width_m": 16}
        _loc["level_ground"] = True
_save_world_data(_w)
update_location_position(PLACE, 20.0, 20.0, 0.0)
f13f = raster_now()
near("the plateau stands on the BUMPY ground at its centre",
     at(f13f, 6, 6), 4.707, 5e-4)
near("...and (16,16) is levelled to it, without the noise on top",
     at(f13f, 5, 5), 4.707, 5e-4)
check_not("...i.e. no longer its own 4.404", round(at(f13f, 5, 5), 3), 4.404)
near("the authored ground at the centre really is 5 + relief(20,20)",
     5.0 + R_20_20, 4.707419759448, 1e-11)
delete_location(PLACE)

print("  [13g] the topmost kind decides")
PATH = terrain.save_area({"kind": "p", "polygon": square(14, 14, 40, 40)})
_areas = terrain.list_areas()
check("kind_at agrees about (20,20)", kind_at(20, 20, areas=_areas), "p")
check("...and about (4,4)", kind_at(4, 4, areas=_areas), "g")
f13g = raster_now()
near("under the flat kind the ground is the authored 5 again",
     at(f13g, 6, 6), 5.0, 5e-4)
near("...while (4,4) keeps its hills", at(f13g, 2, 2), 5.086, 5e-4)
check("a flat area over a bumpy one IS an input of the pass",
      [a.get("kind") for a, _p, _b in hf.relief_inputs(
          _areas, terrain_types.effective_catalog())], ["g", "p"])
terrain.delete_area(PATH["id"])

print("  [13i] no relief in the catalog = the pass never happened")
set_relief("g")           # the same kind, amplitude gone
check("...so nothing is an input any more",
      hf.relief_inputs(terrain.list_areas(),
                       terrain_types.effective_catalog()), [])
check("and the grid is byte-for-byte the pure area raster",
      raster_now()["heights"]
      == hf.rasterize(store.list_height_areas())["heights"], True)

print("  [13j] the signature")
for _a in list(terrain.list_areas()):
    terrain.delete_area(_a["id"])
_sig0 = store.height_sig()
_flat_area = terrain.save_area({"kind": "p", "polygon": square(0, 0, 40, 40)})
check("painting a flat kind leaves the signature alone",
      store.height_sig(), _sig0)
_g_area = terrain.save_area({"kind": "g", "polygon": square(0, 0, 40, 40)})
check("...and so does painting a kind that carries no relief YET",
      store.height_sig(), _sig0)
set_relief("g", amplitude=1.0, wave=16.0)
_sig_relief = store.height_sig()
check("giving the kind an amplitude moves it", _sig_relief != _sig0, True)
set_relief("g", amplitude=0.5, wave=16.0)
check("changing the amplitude moves it again",
      store.height_sig() != _sig_relief, True)
set_relief("g", amplitude=0.5, wave=64.0)
check("...and so does the wave", store.height_sig() != _sig_relief, True)
# THE FLAT-OVER-RELIEF REFINEMENT, probed directly. Two lines of reasoning,
# no new number: [13g] already shows such an area IS an input of the pass (it
# erases the hills it covers), and the signature hashes exactly the input list
# (`relief_basis`) — so membership is provable by adding it and taking it away
# again. The basis carries kind/polygon/relief only, never an id, which is why
# the removal has to give the SAME string back and not merely a different one.
_sig_wave = store.height_sig()
_over = terrain.save_area({"kind": "p", "polygon": square(8, 8, 24, 24)})
check("a flat area painted OVER the active relief moves the signature",
      store.height_sig() != _sig_wave, True)
terrain.delete_area(_over["id"])
check("...and deleting it gives EXACTLY that signature back",
      store.height_sig(), _sig_wave)
set_relief("g")
check("taking the relief away gives EXACTLY the old signature back",
      store.height_sig(), _sig0)
terrain.delete_area(_g_area["id"])
terrain.delete_area(_flat_area["id"])

print("  [13k] the reader clamps a catalog row the sanitizer never saw")
check("amplitude 99 -> 2.0, wave 2 -> 8.0 (Nyquist)",
      hf.relief_params("g", {"meta": {"relief_amplitude_m": 99,
                                      "relief_wave_m": 2}}),
      (SEED_G, 2.0, 8.0))
check("no wave -> the 32 m default",
      hf.relief_params("g", {"meta": {"relief_amplitude_m": 0.4}}),
      (SEED_G, 0.4, 32.0))
check("amplitude 0 -> no relief",
      hf.relief_params("g", {"meta": {"relief_amplitude_m": 0}}), None)
check("junk amplitude -> no relief",
      hf.relief_params("g", {"meta": {"relief_amplitude_m": "much"}}), None)
check("NaN amplitude -> no relief",
      hf.relief_params("g", {"meta": {"relief_amplitude_m": float("nan")}}),
      None)
check("no meta at all -> no relief", hf.relief_params("g", {}), None)
near("a wave that is not carried by the grid is clamped, not aliased",
     hf.micro_relief_at(hf.relief_params("g", {"meta": {
         "relief_amplitude_m": 1.0, "relief_wave_m": 2}}), 8, 0),
     hf.micro_relief_at((SEED_G, 1.0, 8.0), 8, 0), 1e-15)

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
