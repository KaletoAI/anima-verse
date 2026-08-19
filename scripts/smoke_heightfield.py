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
[7b] THE STEP THE EDITOR IS TOLD ABOUT (finding 14, 2026-08-13). The
    coarsening above is invisible in the editor, and the case it was reported
    on is the LIVE north area: a union box of 16 160 × 5 876 m. By hand, with
    `points = ceil((max + step − origin) / step) + 1` and
    `origin = floor(min/step)·step − step`, i.e. for a box starting at 0
    `points = ceil((max + 2·step) / step) + 1`:
        step  4: cols ceil(16168/4)+1 = 4043, rows ceil(5884/4)+1 = 1472
                 -> 5 951 296 points, far past MAX_POINTS (120 000)
        step  8: cols ceil(16176/8)+1 = 2023, rows ceil(5892/8)+1 =  738
                 -> 1 492 974
        step 16: cols ceil(16192/16)+1 = 1013, rows ceil(5908/16)+1 = 371
                 ->   375 823, still past it
        step 32: cols ceil(16224/32)+1 =  508, rows ceil(5940/32)+1 = 187
                 ->    94 996  <= 120 000, so the step is 32 m
    and 32 m is where the forest's micro-relief dies: its swells are 8…12 m
    wide (§ A16.2) and the raster carries nothing under 2 × step = 64 m.
    `heightfield.current_step_m()` is the ONE place the editor's routes read
    that number from — checked here against the same box in the store, so the
    warning cannot name a step the world does not have.
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
       NOT MEASURED AT THE CENTRE: h(2,2) is the same number in BOTH states (a
       plateau is pinned to exactly the authored height at its centre), so the
       centre is the one point that cannot tell the two apart.
       RED COUNTER-PROBE, executed: with ``placed_footprints`` replaced by its
       pre-decision version (no flag filter) every one of those four points
       moves to the plateau height and the grid grows to 15 × 15.

       ``ground_y`` READS THE TILE, the field checks read the OVERVIEW, and
       since 2026-08-14 those are two different steps (2 m and 4 m). Every
       ``h(...)`` above is unaffected — it is the authored landscape at a point
       both lattices carry — but the plateau height is not, see b).

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

    b) THE PLATEAU HEIGHT is the authored landscape at the centre (2, 2), read
       BEFORE anything is levelled — and it is a property of the LATTICE one
       reads it on, which is why there are two numbers since the tiles went to
       2 m (2026-08-14):
         OVERVIEW, step 4: the cell (0,0)-(4,4) has the corners (0,0)=0,
           (4,0)=0, (0,4)=0 (all ON the outline) and (4,4)=5 (4 m in), both
           fractions 0.5 -> 0.25 · 5 = 1.25 m. That is what the grid checks
           below see.
         TILE, step 2: (2,2) IS a support point, so no mixing happens at all
           and the plateau stands at the authored ramp itself,
           5 · min(1, 2/4) = 2.5 m. That is what ``ground_y`` answers.
       The finer number is the truer one — 2.5 is the ramp's exact height at
       (2,2) — and the gap is the honest cost of two rasters: the distant
       picture pins this place a metre and a quarter lower than the ground
       every rule walks on.

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
       (6,6) and at (-1,5) ``ground_y`` answers 2.5 everywhere, because every
       cell touching the footprint has four pinned corners.

    e) THE RAMP is the ONE cell between the ring and the landscape, and a cell
       is 2 m on the tile the rule reads. East of the ring, on the row z = 4:
       the pinned ring reaches x = 8 (the footprint ends at 6, one cell is 2),
       so h(8,4) = 2.5, and h(10,4) = 5 (authored: distance min(10,30,4,36) = 4
       = the falloff, so the full height), hence
         h( 9,4) = 2.5 + 2.5·0.5 = 3.75
         h(10,4) = 5.0
         h(11,4) = 5.0            (both its corners, 10 and 12, are authored 5)
       — monotone up. HONESTLY: 2.5 m over 2 m is atan(1.25) = 51.3 deg, past
       the default max_slope_deg of 40 — this rim is a wall a walker cannot
       climb, and gets in through an opening (§ A15 no. 8 exempts them). That
       is the authoring limit the height tool warns about, and it HALVED with
       the cell: a ramp of one cell now carries tan(40 deg)·2 = 1.68 m where it
       carried 3.36 m at the 4 m step. The editor computes it from the
       ``tile_step_m`` the server sends, so the sentence moved with the world.

    f) THE PLATEAU WANDERS WITH THE PLACE. Moving the hut to (20, 2) changes
       the signature (placements are part of it), frees (4,4) back to its
       authored 5 and levels the new footprint instead: the new centre reads
       h(20,2) = 5 · min(1, 2/4) = 2.5 — the 2 m lattice carries that point, so
       it is the authored ramp itself — and (22,4) and (18,4), both authored 5
       and both inside the new footprint, are cut to that same 2.5. Deleting
       the hut gives all of them back their 5.
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

    THE TWO HEIGHTS, both read off the UNTOUCHED area raster AT THE TILE STEP
    (that is the raster ``ground_y`` levels on):
      SQUARE at (6, 6): a support point, distance min(6, 34) = 6 >= the
                        falloff 4                                    -> 5
      HUT    at (2, 2): a support point too, distance 2 of a 4 m ramp -> 2.5
    The widest is levelled first, so the HUT writes last and wins where they
    overlap:
      ground_y(2, 2)   = 2.5      the hut's own plateau
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
       amplitude 99 -> 2.0, wave 2 -> 4.0 (NYQUIST: 2 × the 2 m TILE step,
       a wave the grid could not carry — the floor halved with the step on
       2026-08-14, which is what made a 4 m swell authorable), no wave -> 32.0,
       amplitude 0/junk -> no relief at all.
    l) THE EDGE RULE — the relief may LIFT its neighbour, never sink it (user
       decision 2026-08-13). At a support point one of whose four grid
       neighbours carries no relief (a flat topmost kind or unpainted ground)
       the noise is clamped to max(0, noise); inner points keep theirs.

       THE FIXTURE: "g" (amplitude 1.0, wave 16) painted over (0,0)-(40,40)
       with a FLAT "w" (water) over (40,0)-(80,40) east of it, and no height
       area at all — so every support point reads its bare relief. The grid is
       the one of the grass box alone (the flat kind does not grow it): 13 × 13
       from origin (−4,−4), step 4. The ray-cast contains the LOWER edges only
       (`world_geometry.point_in_polygon`, `x < cross_x`), so the grass points
       are i, j = 1..10 (x, z = 0..36) and the water starts at i = 11 (x = 40)
       — the seam runs between them.

       THE FOUR POINTS, all by hand from rnd(u, v) of b):
         rnd(2,1) = −0.057022939436   rnd(3,1) =  0.968026378658
         rnd(2,2) = −0.201629256364   rnd(3,2) = −0.737533572596
         rnd(0,1) = −0.100840141065   rnd(0,0) =  0.494826480746
       (the last two by the same three lines as b): state(0,1) = 3792446982 +
       19349663 = 3811796645 -> 2414331557 -> 2414313814 -> 1930931094, and
       1930931094/2**32·2−1 = −0.100840141065.)

         (36,32) i=10 j=9  BORDER (i+1 is water), fx = 2.25 -> tx = 0.25,
                           fz = 2.0 -> tz = 0:
                           0.75·(−0.201629256364) + 0.25·(−0.737533572596)
                           = −0.335605335422   -> CLAMPED to 0.0
         (36,16) i=10 j=5  the same border column, tz = 0 on v = 1:
                           0.75·(−0.057022939436) + 0.25·(0.968026378658)
                           = +0.199239390088   -> KEPT, the shore lifts
         (32,16) i=9  j=5  INNER (all four neighbours are grass), fx = 2.0:
                           rnd(2,1) = −0.057022939436  -> KEPT, still a dip
         (0,16)  i=1  j=5  BORDER to UNPAINTED ground, fx = 0, fz = 1:
                           rnd(0,1) = −0.100840141065  -> CLAMPED to 0.0
         (0,0)   i=1  j=1  the same border, positive:
                           rnd(0,0) = +0.494826480746  -> KEPT
       and the seam itself is level: (36,32) and the water point (40,32) both
       read 0.0, which is the finding — the lake no longer sinks with the
       meadow beside it.

       RED COUNTER-PROBE, EXECUTED: the same pass without the clamp, rebuilt
       in this script from the module's own pieces (`relief_inputs` +
       `micro_relief_at` + `point_in_polygon`, i.e. the topmost-kind rule and
       the noise, without the mask). It puts −0.335605335422 back at (36,32)
       and −0.100840141065 at (0,16) — the values the finding was about — and
       agrees with the shipped pass at every point that is NOT a clamped one.

[14] THE TILES THE RULES READ (v2, 2026-08-14). The world grid above is ONE
    raster over everything, so the point budget coarsens it as soon as somebody
    paints far out ([7b]: a 16 km box forces 32 m) — and at 32 m the ground a
    walker is judged against is not the ground anybody authored. So the rules
    read TILES: 256 m squares at the fixed 2 m step, rastered on demand.

    THE STEP IS 2 m SINCE THE NACHWELLE (user decision 2026-08-14), and the
    overview keeps its own 4 m: a relief wave is clamped at 2 × the TILE step
    ([13k], Nyquist), so 2 m is what makes a 4 m swell authorable at all. The
    two lattices stay congruent — 4 is a multiple of 2, so every overview
    support point is a tile support point — but they are no longer the same
    raster, because two rules measure in cells: the plateau's ramp ring is ONE
    CELL wide, and the relief's edge rule asks about the four NEIGHBOURS. Both
    therefore reach 4 m on the overview and 2 m on a tile. Hence the forced
    step below.

    THE CLAIM BEING CHECKED IS EQUALITY, not "the tiles look plausible": tile
    and overview come out of the ONE evaluation kernel over the ONE lattice
    anchored at the world origin, so with the overview rastered at the TILE
    step the two must carry the SAME number at every shared point. Every
    expectation below is derived from the shapes, never read off the output.

    THE FIXTURE (all of it synthetic, the pure functions only):
      A1     square (258,100)-(360,260), height  6, falloff 8
      A2     square (300,200)-(420,300), height −9, falloff 0 (a wall)
      GRASS  terrain kind "g", amplitude 1.0, wave 16, painted as a BAND over
             (264,240)-(396,264) — deliberately ACROSS the z = 256 seam
      FP_BIG   (340,140) width 40   level_ground
      FP_SMALL (356,152) width  8   level_ground, inside FP_BIG
      FP_WEST  (260,220) width  8   level_ground, at A1's west edge
      FP_FAR  (2000,2000) width 20  level_ground, 1.6 km away

    a) THE OVERVIEW, at the forced step 2 — the TILE step, so the comparison
       is about the tiles and not about two resolutions. The GRASS band lies
       inside the two height boxes, so the union is
       A1 ∪ A2 = (258,100)-(420,300); the levelling footprints grow it by
       their own box PLUS one step where they are relevant, i.e. where that
       grown box still touches the authored one:
         FP_BIG   box (320,120)-(360,160) -> grown (318,118)-(362,162)  yes
         FP_SMALL box (352,148)-(360,156) -> grown (350,146)-(362,158)  yes
         FP_WEST  box (256,216)-(264,224) -> grown (254,214)-(266,226)  yes
         FP_FAR   box (1990,1990)-(2010,2010) -> grown (1988,…)-(2012,…) NO
       so bounds = (254,100)-(420,300) and
         origin = (floor(254/2)·2 − 2, floor(100/2)·2 − 2) = (252, 98)
         cols   = ceil((420 + 2 − 252)/2) + 1 = 86
         rows   = ceil((300 + 2 −  98)/2) + 1 = 103     -> 8858 points
    b) THE TILE INDEX is pure box coverage, tile (tx, tz) = floor(p/256):
         A1     (258,100)-(360,260) -> tx 1, tz 0..1  -> (1,0) (1,1)
         A2     (300,200)-(420,300) -> tx 1, tz 0..1  -> (1,0) (1,1)
         GRASS  (264,240)-(396,264) -> tx 1, tz 0..1  -> (1,0) (1,1)
         FP_BIG/FP_SMALL grown      -> tx 1, tz 0     -> (1,0)
         FP_WEST grown (254,…)-(266,…) -> tx 0..1, tz 0 -> (0,0) (1,0)
         FP_FAR irrelevant          -> nothing
       = {(0,0), (1,0), (1,1)}, three tiles — the same three the 4 m ring gave,
       and it is worth saying why the narrower ring did not lose (0,0): the
       ring is measured from the footprint's BOX (256…264), so 2 m still reach
       across the seam at x = 256. TWO OF THE THREE INDEX CASES ARE IN THAT
       LIST: (0,0) exists ONLY because a footprint's ramp ring crosses that
       seam, and the far hut adds no tile at all — it would level 0 onto 0,
       which is why the relevance rule may drop it. (0,1) is absent, and so the
       whole strip x < 256, z >= 256 is answered 0 without a raster — which the
       equality run measures against the overview, whose support points there
       are all outside every polygon.
    c) HAND VALUES on the lattice (all outside GRASS, so no noise is involved):
       (260,104) A1 only, distance to the outline 2      -> 6 · 2/8 = 1.5
       (348,232) A1 gives 6, A2 gives −9, |−9| wins      -> −9
       (416,296) A2 only                                 -> −9
       and the three plateau heights, each read from the landscape at the
       footprint's own centre BEFORE any levelling:
       FP_BIG   (340,140) distance min(82,20,40,120) = 20 >= 8   -> 6.0
       FP_SMALL (356,152) distance min(98, 4,52,108) =  4        -> 3.0
       FP_WEST  (260,220) distance min( 2,100,120,40) = 2        -> 1.5
       so (356,152) is pinned by BOTH squares and reads the NARROWER one's 3.0,
       while (344,152) — 8 m from FP_SMALL's square, i.e. past its one-cell
       ring — keeps FP_BIG's 6.0. (254,220) is FP_WEST's ring, 2 m west of its
       square and IN THE NEIGHBOUR TILE: 1.5. THE RING IS EXACTLY ONE CELL, so
       the 2 m step moved it: (252,220), which the 4 m raster still pinned, is
       now 4 m out and therefore the flat world, 0.0 — the honest price of the
       finer step, and the number the editor warning now has to name
       (tan(40°)·2 = 1.68 m instead of 3.36 m).
       (254,220) GUARDS THE PURE PLATEAU HEIGHT. FP_WEST's centre (260,220)
       lies OUTSIDE tile (0,0), which still has to level the ring reaching into
       it. Read from the window's own array — the way the overview did while it
       was the only raster — the corner would clamp to the tile border and the
       place would stand at the ground of (256,220), i.e. at 0.0 in one tile
       and 1.5 in the other. It is 1.5 in both.
    d) THE SEAM. A tile carries its edges (129 × 129 points for 256 m at 2 m,
       (256/2) + 1 per axis), so
       the last row of tile (1,0) IS the first row of tile (1,1) — checked
       value by value, because "the ground is continuous across the seam" is
       exactly what a client stitching two tiles depends on. The bilinear
       samples of the equality run include points sitting ON both seams.
    e) RED COUNTER-PROBES, all three built in this script from the module's own
       pieces:
       * NO APRON: the micro-relief's edge clamp asks the four NEIGHBOURS of a
         point, so a tile must evaluate a one-point ring outside its own
         window. With the pre-v2 rule ("a point on the window border borders
         flat ground") the clamp fires along the whole seam row z = 256, which
         runs through the middle of the painted band. The row's ELEVEN INNER
         dips — x = 350, 352, 354, 378, 380, 382, 384, 386, 388, 390, 392, the
         points whose four neighbours (2 m away now) are painted too and whose
         noise points down — are the discriminating ones: the world keeps them,
         the mutant cuts every one to 0. The list is longer than the four the
         4 m step had, and it is longer for both reasons at once: the row has
         twice the points, and a neighbour 2 m away is more often still inside
         the band than one 4 m away (x = 392 used to be excluded because its
         eastern neighbour 396 lay on the band's own edge; at 2 m that
         neighbour is 394, well inside). It is predicted here from the module's
         noise formula and the ray-cast alone — never from a raster.
       * PLATEAU ORDER REVERSED (narrowest first): (356,152) reads FP_BIG's
         6.0 instead of FP_SMALL's 3.0.
       * A TILE STRICKEN FROM THE INDEX: without (0,0) the point (254,220)
         answers 0.0 instead of FP_WEST's ramp — the index is not a hint, it is
         the statement "everywhere else is flat".

[15] THE TILE-KEY QUERY of the batch endpoint (§ A16.3). ``keys=tx:tz,tx:tz``
    — colon INSIDE a key, comma BETWEEN them — parsed purely, and every rule
    of it derived here:
      "1:0,2:3"        -> [(1, 0), (2, 3)]        the plain case
      "1:0,x,2:3:4,,7" -> [(1, 0)]                a name, two colons, an empty
                                                  token and a missing half are
                                                  all "not a tile key"
      "-1:-2"          -> [(-1, -2)]              west/north of the origin is
                                                  an ordinary tile
      "2:3,1:0,2:3"    -> [(2, 3), (1, 0)]        a duplicate collapses to its
                                                  FIRST position — the order
                                                  the cap then cuts at
      ""               -> []                      an empty query asks nothing
    THE CAP IS 64 AND IT BITES AFTER THE DEDUPE: "0:0,0:1,…,0:64" is 65
    distinct keys, so 64 come back and the 65th, (0, 64), is not among them;
    a query of 64 distinct keys with every one of them repeated still returns
    all 64, because the repeats never occupied a slot.
    THE PAYLOAD is built over the [14] world: the index is {(0,0), (1,0),
    (1,1)}, so ``tiles`` answers "1,0" (comma in the payload, colon in the
    query) and simply omits the unindexed (9, 9) — the client reads a missing
    tile as flat ground.
    THE INDEX IS SORTED NUMERICALLY, which only a two-digit index can show:
    two more patches at x = 520…530 and x = 2570…2580 are the tiles
    floor(520/256) = 2 and floor(2570/256) = 10, so the index reads
    ["0,0", "1,0", "1,1", "2,0", "10,0"] — sorting the strings would put
    "10,0" in front of "2,0".

[16] A 4 m RELIEF WAVE — what the 2 m tile step actually bought (Nachwelle,
    2026-08-14). The wave a terrain kind may ask for is clamped at
    2 × the TILE step (`terrain_types.RELIEF_WAVE_MIN`, Nyquist), so halving
    that step halved the floor: 8 m -> 4 m. THAT is the user-facing change, and
    it is what this section measures.

    THE FIXTURE, purely functional (no DB, no world): kind "w" with amplitude
    0.5 and wave 4.0, painted over the square (600,600)-(700,700). It sits
    inside tile (2,2), which covers [512, 768] on both axes, so the tile alone
    answers for it. The noise lattice of a 4 m wave has its corners at the
    multiples of 4; the two points measured are

      (640,640)  u,v = 160,160, both fractions 0     -> 0.5 · rnd(160,160)
      (642,642)  u,v = 160,160, both fractions 0.5   -> 0.5 · the MEAN of the
                                                        four corners
                                                        = −0.111142964044

    and the second one is the whole point: at a 2 m step the raster HAS a
    support point in the middle of every wave cell (index 65 of 129), at a 4 m
    step it has none — one support point per wave instead of two.

    RED COUNTER-PROBE (a), THE OLD FLOOR: read with `RELIEF_WAVE_MIN` at 8 the
    very same catalog row becomes an 8 m wave, i.e. a DIFFERENT ground — at
    (642,642) it stands at +0.260513117624 where the wave the author asked for
    dips to −0.111142964044. That was the silent substitution before the
    Nachwelle: one typed 4 and the world built 8.

    RED COUNTER-PROBE (b), NYQUIST ITSELF: rastered at 8 m — below two points
    per wave — the field no longer describes that wave. The 8 m grid holds only
    every SECOND corner, so its bilinear reading at the corner (644,644) is the
    mean of the corners (160,160), (162,160), (160,162), (162,162) = +0.190706,
    while the wave itself is 0.5 · rnd(161,161) = −0.203251 there: opposite
    sign, an aliased pattern rather than a coarser one. Grid geometry of that
    raster, by hand: relief box (600,600)-(700,700), so
      origin = floor(600/8)·8 − 8 = 592,  points = ceil((700 + 8 − 592)/8) + 1
             = 15 + 1 = 16 per axis.

    AND THE HONEST HALF: a 4 m raster still reproduces a 4 m wave EXACTLY —
    value noise is bilinear between its corners and a 4 m grid holds every one
    of them, so sampling it at (642,642) gives the tile's own number back. What
    the 4 m step could not do was let anybody ASK for that wave. The gain is
    the authoring range, not a sharper picture of a wave one could already
    have; the sharper picture is what the extra support point gives every
    LONGER wave, and the walking gate reads it.

Usage:  ./.venv/bin/python scripts/smoke_heightfield.py
"""
import asyncio
import math
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="heightfield-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="heightfield-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import heightfield as hf  # noqa: E402
from app.core.world_geometry import ground_y, point_in_polygon  # noqa: E402
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


def fp_square(cx, cz, width, yaw=0.0):
    """A LEVELLING footprint in the v6 shape: pin, yaw, outline in LOCAL
    metres. Exactly what ``effective_boundary`` synthesizes for a location
    that still carries only the legacy ``plan_width_m`` dial, written out so
    the square fixtures below stay the squares they always were."""
    half = width / 2.0
    return (float(cx), float(cz), float(yaw),
            [(-half, -half), (half, -half), (half, half), (-half, half)])


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
# (2,2) IS a support point of the 2 m tile lattice, so the rule reads the
# authored ramp itself: 5 · min(1, 2/4) = 2.5. The 4 m overview still mixes
# its four corners to 1.25 there — the two rasters part company at exactly
# this kind of point since the tiles went to 2 m.
near("ground_y ON a tile support point the overview interpolates",
     ground_y(2, 2), 2.5)
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

print("[7b] the step the editor is told about (the live box of finding 14)")
LIVE = {"id": "live", "polygon": square(0, 0, 16160, 5876),
        "height_m": 5.0, "falloff_m": 4.0}
live = hf.rasterize([LIVE])
check("the live north box coarsens the world to", live["step_m"], 32.0)
check("...at this shape", (live["rows"], live["cols"]), (187, 508))
check("...which is inside the point budget",
      live["rows"] * live["cols"] <= hf.MAX_POINTS, True)
# ...and one step finer would not be: the doubling stops at the FIRST step
# that fits, so 16 m has to be over the budget or 32 is the wrong answer.
check("...while one step finer is not", (hf._axis_points(0, 5876, 16.0)
                                         * hf._axis_points(0, 16160, 16.0)
                                         > hf.MAX_POINTS), True)
# THE EDITOR'S SOURCE, asked the way the routes ask it: through the store.
for _a in store.list_height_areas():
    store.delete_height_area(_a["id"])
check("an empty world stands at the finest step",
      hf.current_step_m(), hf.DEFAULT_STEP_M)
store.save_height_area(LIVE)
check("...and reports the coarsened one once the area is stored",
      hf.current_step_m(), 32.0)
check("which is exactly what the raster says",
      hf.current_step_m(), hf.get_field()["step_m"])
store.delete_height_area("live")
check("deleting it gives the fine grid back", hf.current_step_m(),
      hf.DEFAULT_STEP_M)

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
from app.core import relief  # noqa: E402
from app.routes.world import (delete_height_area_route,  # noqa: E402
                              get_height_areas_route, post_height_area_route,
                              put_height_area_route)
from app.routes.play import (get_heightfield_route,  # noqa: E402
                             get_heightfield_tiles_route)


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

# The AREA list answers the two walk limits alongside the steps (2026-08-16),
# so the terrain editor turns an amplitude into "this becomes unwalkable" out
# of one fetch instead of pulling the whole worldmap for one float. Pinned by
# KEY, not by value: the numbers are admin dials.
areas_payload = get_height_areas_route()
check("area-list keys", sorted(areas_payload.keys()),
      ["areas", "default_step_m", "max_slope_deg", "max_step_height_m", "sig",
       "step_m", "tile_step_m"])
check("...and the limits are the same ones the walk gate reads",
     (areas_payload["max_slope_deg"], areas_payload["max_step_height_m"]),
     (relief.get_max_slope_deg(), relief.get_max_step_height_m()))

payload = get_heightfield_route(user={"role": "user"})
check("payload keys", sorted(payload.keys()),
      ["cols", "heights", "origin_x", "origin_z", "rows", "sig", "step_m",
       "tile_m", "tile_step_m", "tiles"])
check("payload signature", payload["sig"], store.height_sig())
check("payload shape", (payload["rows"], payload["cols"]), (13, 13))
# The overview carries the TILE INDEX with it (§ A16.3): the one area here is
# the square (0,0)-(40,40), which lies inside tile (0, 0) alone.
check("the overview carries the tile index", payload["tiles"], ["0,0"])
check("...with the tile edge", payload["tile_m"], 256.0)
check("...and the fine step the tiles are rastered at",
      payload["tile_step_m"], 2.0)
near("payload height at (20,20)",
     payload["heights"][6][6], 7.0)

# …and the batch endpoint on the same world: (0,0) is the only indexed tile,
# (5,5) is 1.3 km away and simply missing, the junk token is skipped.
batch = get_heightfield_tiles_route(keys="0:0,5:5,nonsense",
                                    user={"role": "user"})
check("batch keys", sorted(batch.keys()),
      ["sig", "step_m", "tile_m", "tiles"])
check("the batch answers the indexed tile and nothing else",
      sorted(batch["tiles"].keys()), ["0,0"])
near("...and it is the fine ground under the hill's centre",
     hf.sample_height({**batch["tiles"]["0,0"], "step_m": batch["step_m"]},
                      20, 20), 7.0)

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
    from app.core.world_geometry import effective_boundary
    from app.models.world import list_locations
    out = []
    for loc in list_locations():
        eff = effective_boundary(loc)
        if eff is None:
            continue
        cx, cz, yaw, points = eff
        out.append((round(cx, 2), round(cz, 2), round(yaw, 1),
                    [(round(lx, 2), round(lz, 2)) for lx, lz in points]))
    return out



def _square_map3d(width):
    """The DRAWN centred square of that edge, plus the width the sanitizer
    derives from its bounding box. Since 2026-08-19 a width alone is no shape
    at all — a location without an outline has no area, so nothing to level —
    and these are the very corners the deleted synthesis produced, so every
    hand-derived number in this file stays put."""
    h = round(float(width) / 2.0, 2)
    return {"plan_width_m": width,
            "boundary": [[-h, -h], [h, -h], [h, h], [-h, h]]}

HUT = add_location("Hut", "a place on the flank")["id"]
_world = _load_world_data()
for _loc in _world["locations"]:
    if _loc.get("id") == HUT:
        _loc["map3d"] = _square_map3d(8)
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
near("the CENTRE cannot tell the two states apart", ground_y(2, 2), 2.5)

_real_footprints = store.placed_footprints
store.placed_footprints = unfiltered_footprints
hf.invalidate_cache()
_mutant = hf.get_field()
check("RED COUNTER-PROBE: without the flag filter the grid grows again",
      (_mutant["rows"], _mutant["cols"]), (15, 15))
near("...and the mutant levels (6,6) to the plateau", ground_y(6, 6), 2.5)
near("...and (4,4)", ground_y(4, 4), 2.5)
near("...and (8,4)", ground_y(8, 4), 2.5)
near("...and (-1,5)", ground_y(-1, 5), 2.5)
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
near("flat at the centre", ground_y(2, 2), 2.5)
near("flat at the footprint corner (6,6)", ground_y(6, 6), 2.5)
near("flat at (-1, 5)", ground_y(-1, 5), 2.5)
near("the ramp starts at the ring, h(8,4)", ground_y(8, 4), 2.5)
near("h(9,4)", ground_y(9, 4), 3.75)
near("h(10,4) — the authored landscape again", ground_y(10, 4), 5.0)
near("h(11,4) — and it stays there", ground_y(11, 4), 5.0)
near("h(12,4)", ground_y(12, 4), 5.0)
check("the ramp is monotone",
      [round(ground_y(8 + k, 4), 4) for k in range(5)]
      == sorted(round(ground_y(8 + k, 4), 4) for k in range(5)), True)
check("...and this rim is steeper than a walker climbs (51.3 deg)",
      round(math.degrees(math.atan2(5.0 - 2.5, hf.TILE_STEP_M)), 1), 51.3)
check("...which is exactly what one cell of ramp carries: tan(40 deg)·2",
      round(math.tan(math.radians(40.0)) * hf.TILE_STEP_M, 2), 1.68)

set_level_ground(HUT, False)
near("clearing the flag gives the landscape back at (6,6)",
     ground_y(6, 6), 5.0)
check("...the grid shrinks to the plain hill raster",
      (hf.get_field()["rows"], hf.get_field()["cols"]), (13, 13))
check("...and the signature is EXACTLY the one from before the flag",
      store.height_sig(), _sig_flat)
set_level_ground(HUT, True)
near("flagging it again levels (6,6) once more", ground_y(6, 6), 2.5)

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
            loc["map3d"] = _square_map3d(width)
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
# At the TILE step, because that is the raster ``ground_y`` levels on.
_bare = hf.rasterize(store.list_height_areas(), step_m=hf.TILE_STEP_M)
near("the square's height, read off the UNTOUCHED raster",
     hf.sample_height(_bare, 6, 6), 5.0)
near("the hut's, likewise", hf.sample_height(_bare, 2, 2), 2.5)
near("the SMALLEST footprint wins: ground_y(2,2)", ground_y(2, 2), 2.5)
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
RND_00 = 0.494826480746             # rnd(0, 0)   — [13]l
RND_01 = -0.100840141065            # rnd(0, 1)
RND_22 = -0.201629256364            # rnd(2, 2)
RND_31 = 0.968026378658             # rnd(3, 1)
RND_32 = -0.737533572596            # rnd(3, 2)
R_32_16 = RND_21                    # wave 16: (32,16) IS the corner (2,1)
R_36_16 = 0.75 * RND_21 + 0.25 * RND_31     # +0.199239390088, a border HILL
R_36_32 = 0.75 * RND_22 + 0.25 * RND_32     # −0.335605335422, a border DIP


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
        _loc["map3d"] = _square_map3d(16)
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
check("amplitude 99 -> 2.0, wave 2 -> 4.0 (Nyquist, 2 x the 2 m tile step)",
      hf.relief_params("g", {"meta": {"relief_amplitude_m": 99,
                                      "relief_wave_m": 2}}),
      (SEED_G, 2.0, 4.0))
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
     hf.micro_relief_at((SEED_G, 1.0, 4.0), 8, 0), 1e-15)

print("  [13l] the edge rule — the relief lifts its neighbour, never sinks it")
for _a in store.list_height_areas():
    store.delete_height_area(_a["id"])
for _a in list(terrain.list_areas()):
    terrain.delete_area(_a["id"])
set_relief("g", amplitude=1.0, wave=16.0)
set_relief("w")                     # the flat neighbour: water
terrain.save_area({"kind": "g", "polygon": square(0, 0, 40, 40)})
terrain.save_area({"kind": "w", "polygon": square(40, 0, 80, 40)})
f13l = raster_now()
_areas_l = terrain.list_areas()
check("the flat neighbour does not grow the grid",
      (f13l["rows"], f13l["cols"], f13l["origin_x"], f13l["origin_z"]),
      (13, 13, -4.0, -4.0))
check("kind_at agrees where the seam runs",
      [kind_at(36, 32, areas=_areas_l), kind_at(40, 32, areas=_areas_l)],
      ["g", "w"])
near("an INNER dip is still a dip", at(f13l, 9, 5), R_32_16, 5e-4)
near("THE FINDING: a border dip toward the water is pulled up to 0",
     at(f13l, 10, 9), 0.0)
near("...while a border hill runs out into it", at(f13l, 10, 5), R_36_16, 5e-4)
near("...and the water itself is where it always was", at(f13l, 11, 9), 0.0)
near("the same at the border to UNPAINTED ground: the dip is pulled up",
     at(f13l, 1, 5), 0.0)
near("...and the hill is kept", at(f13l, 1, 1), RND_00, 5e-4)

# RED COUNTER-PROBE, executed: the pass WITHOUT the mask, rebuilt from the
# module's own pieces — the topmost-kind rule (`relief_inputs` + the ray-cast)
# and the noise, and nothing else. It is the state the finding was reported on.
_relief_l = hf.relief_inputs(_areas_l, terrain_types.effective_catalog())
_unclamped = [[0.0] * f13l["cols"] for _ in range(f13l["rows"])]
for _j in range(f13l["rows"]):
    _pz = f13l["origin_z"] + _j * f13l["step_m"]
    for _i in range(f13l["cols"]):
        _px = f13l["origin_x"] + _i * f13l["step_m"]
        _params = None
        for _area, _p, _b in _relief_l:
            if point_in_polygon(_px, _pz, _area.get("polygon")):
                _params = _p
        _unclamped[_j][_i] = round(hf.micro_relief_at(_params, _px, _pz), 3)
near("RED COUNTER-PROBE: without the clamp the border dip is back",
     _unclamped[9][10], R_36_32, 5e-4)
near("...and so is the one toward unpainted ground",
     _unclamped[5][1], RND_01, 5e-4)
_moved = [(i, j) for j in range(f13l["rows"]) for i in range(f13l["cols"])
          if _unclamped[j][i] != at(f13l, i, j)]
check("the clamp moves ONLY border points, and only downward-pointing ones",
      all(_unclamped[j][i] < 0 and at(f13l, i, j) == 0.0
          for i, j in _moved) and len(_moved) > 0, True)

print("\n[14] the tiles the rules read — the same ground, twice")

T14_A1 = {"id": "t14_a1", "polygon": square(258, 100, 360, 260),
          "height_m": 6.0, "falloff_m": 8.0}
T14_A2 = {"id": "t14_a2", "polygon": square(300, 200, 420, 300),
          "height_m": -9.0, "falloff_m": 0.0}
T14_AREAS = [T14_A1, T14_A2]
T14_TERRAIN = [{"kind": "g", "polygon": square(264, 240, 396, 264),
                "z_order": 0}]
T14_CATALOG = {"g": {"passable": True, "speed_factor": 1.0,
                     "meta": {"relief_amplitude_m": 1.0,
                              "relief_wave_m": 16.0}}}
T14_BIG = fp_square(340.0, 140.0, 40.0)
T14_SMALL = fp_square(356.0, 152.0, 8.0)
T14_WEST = fp_square(260.0, 220.0, 8.0)
T14_FAR = fp_square(2000.0, 2000.0, 20.0)
T14_FPS = [T14_BIG, T14_SMALL, T14_WEST, T14_FAR]
T14_RELIEF = hf.relief_inputs(T14_TERRAIN, T14_CATALOG)

# THE STEP IS FORCED to the TILE step: the comparison is about the tiles, and
# both a coarsened overview and the overview's own 4 m default would make it
# fail (or pass) for reasons of resolution rather than of the kernel.
T14_S = hf.TILE_STEP_M
F14 = hf.rasterize(T14_AREAS, step_m=T14_S, footprints=T14_FPS,
                   terrain_areas=T14_TERRAIN, terrain_catalog=T14_CATALOG)
check("the overview is anchored at (252, 98)",
      (F14["origin_x"], F14["origin_z"]), (252.0, 98.0))
check("...86 × 103 points at the 2 m tile step",
      (F14["cols"], F14["rows"], F14["step_m"]), (86, 103, 2.0))
near("(260,104) — A1's ramp, 2 m in", at(F14, 4, 3), 1.5)
near("(348,232) — the hollow beats the ridge", at(F14, 48, 67), -9.0)
near("(416,296) — the hollow alone", at(F14, 82, 99), -9.0)
near("(340,140) — FP_BIG's plateau", at(F14, 44, 21), 6.0)
near("(356,152) — the NARROWER place wins", at(F14, 52, 27), 3.0)
near("(344,152) — past its ring, FP_BIG again", at(F14, 46, 27), 6.0)
near("(254,220) — FP_WEST's ring, outside every area", at(F14, 1, 61), 1.5)
near("(252,220) — one cell further out, and one cell is 2 m now: flat",
     at(F14, 0, 61), 0.0)

T14_INDEX = hf.tile_index_from(T14_AREAS, T14_RELIEF, T14_FPS)
check("the tile index is the three hand-derived keys",
      sorted(T14_INDEX), [(0, 0), (1, 0), (1, 1)])

_t14_cache = {}


def t14_tile(key):
    """One rastered tile of the fixture, kept so the equality run below does
    not raster the same square 2385 times."""
    tile = _t14_cache.get(key)
    if tile is None:
        tile = hf.rasterize_tile(key[0], key[1], T14_AREAS,
                                 footprints=T14_FPS,
                                 terrain_areas=T14_TERRAIN,
                                 terrain_catalog=T14_CATALOG)
        _t14_cache[key] = tile
    return tile


def t14_sample(x, z, index=None):
    """``world_height``'s rule, purely: the tile that holds the point, or the
    flat world where no tile is indexed."""
    key = hf.tile_key(x, z)
    if key not in (T14_INDEX if index is None else index):
        return 0.0
    return hf.sample_height(t14_tile(key), x, z)


T14_T10 = t14_tile((1, 0))
T14_T11 = t14_tile((1, 1))
T14_T00 = t14_tile((0, 0))
check("a tile is 129 × 129 points at the fixed 2 m step",
      (T14_T10["rows"], T14_T10["cols"], T14_T10["step_m"]), (129, 129, 2.0))
check("...anchored at its own corner",
      (T14_T10["origin_x"], T14_T10["origin_z"]), (256.0, 0.0))

# THE EQUALITY, point by point over the whole overview.
_t14_off = []
for _j in range(F14["rows"]):
    _z = F14["origin_z"] + _j * T14_S
    for _i in range(F14["cols"]):
        _x = F14["origin_x"] + _i * T14_S
        _tiled = round(t14_sample(_x, _z), 3)
        if at(F14, _i, _j) != _tiled:
            _t14_off.append((_x, _z, at(F14, _i, _j), _tiled))
check(f"all {F14['rows'] * F14['cols']} support points of the overview carry "
      "the tiles' number", (len(_t14_off), _t14_off[:2]), (0, []))

# …and BETWEEN them, where the bilinear rule does the talking. Two of the
# seven sit exactly on a seam (z = 256 and x = 256).
for _p in [(290.0, 256.0), (256.0, 220.0), (302.0, 178.0), (270.5, 130.25),
           (410.0, 290.0), (250.0, 218.0), (259.0, 257.5)]:
    near(f"between the support points at {_p}", t14_sample(*_p),
         hf.sample_height(F14, *_p), 1e-12)

T14_LAST = hf.TILE_POINTS - 1
check("the seam is SHARED: the last row of (1,0) is the first of (1,1)",
      T14_T10["heights"][T14_LAST] == T14_T11["heights"][0], True)
check("...and the east column of (0,0) is the west column of (1,0)",
      [row[T14_LAST] for row in T14_T00["heights"]]
      == [row[0] for row in T14_T10["heights"]], True)

print("  [14a] what the index does and does not contain")
check("the hut 1.6 km away indexes no tile",
      hf.tile_key(2000, 2000) in T14_INDEX, False)
check("RED COUNTER-PROBE: without the relevance rule its ring would be one",
      hf.tile_key(2000, 2000) in frozenset(
          key for fp in T14_FPS
          for key in hf.tiles_of_box(hf._grown(hf._footprint_box(fp), T14_S))),
      True)
near("...so the ground under it is the flat world",
     t14_sample(2000, 2000), 0.0)
near("...which is what the overview says there too",
     hf.sample_height(F14, 2000, 2000), 0.0)
check("the ramp ring at A1's west edge DOES index the neighbour tile",
      (0, 0) in T14_INDEX, True)
near("...and the ramp is really in it, 2 m west of the square",
     t14_sample(254, 220), 1.5)
near("...while 4 m west of it — the old ring width — the world is flat",
     t14_sample(252, 220), 0.0)
check("the strip west of the seam and south of it has no tile",
      (0, 1) in T14_INDEX, False)
near("...so a point there is 0 without a raster", t14_sample(100, 300), 0.0)
near("a point east of everything likewise", t14_sample(600, 150), 0.0)


def t14_tile_no_apron(tx, tz):
    """RED COUNTER-PROBE (a): the tile with the PRE-v2 window rule — the relief
    mask is the window itself and a point on its border counts as bordering
    flat ground. Rebuilt from the module's own pieces (`_window_grid` for the
    areas, `relief_inputs` + `micro_relief_at` + the ray-cast for the
    noise)."""
    ox, oz = tx * hf.TILE_M, tz * hf.TILE_M
    n = hf.TILE_POINTS
    s = T14_S
    boxes = hf.area_boxes(T14_AREAS)
    heights = hf._window_grid(ox, oz, s, n, n, boxes, ())
    mask = [[None] * n for _ in range(n)]
    for _area, _params, _box in T14_RELIEF:
        for j in range(n):
            for i in range(n):
                if point_in_polygon(ox + s * i, oz + s * j,
                                    _area.get("polygon")):
                    mask[j][i] = _params
    for j in range(n):
        for i in range(n):
            params = mask[j][i]
            if params is None:
                continue
            noise = hf.micro_relief_at(params, ox + s * i, oz + s * j)
            flat = (i == 0 or j == 0 or i == n - 1 or j == n - 1
                    or mask[j - 1][i] is None or mask[j + 1][i] is None
                    or mask[j][i - 1] is None or mask[j][i + 1] is None)
            if noise < 0.0 and flat:
                noise = 0.0
            heights[j][i] += noise
    window = (ox, oz, ox + hf.TILE_M, oz + hf.TILE_M)
    near_fps = [fp for fp in T14_FPS
                if hf._overlaps(hf._grown(hf._footprint_box(fp), s), window)]
    hf.level_plateaus(ox, oz, s, heights, near_fps, boxes, T14_RELIEF)
    return [[round(v, 3) for v in row] for row in heights]


print("  [14b] the red counter-probes")
_mut_apron = t14_tile_no_apron(1, 0)
# The seam row z = 256 is the tile's last row (j = 128) and the overview's row
# j = (256 − 98)/2 = 79; column i of the tile is x = 256 + 2i, i.e. the
# overview's i + 2 — (256 + 2i − 252)/2 = i + 2.
_T14_SEAM_ROW = (256 - int(F14["origin_z"])) // int(T14_S)
_T14_SEAM_COL = (256 - int(F14["origin_x"])) // int(T14_S)
check("the seam row z = 256 is the overview's row 79, its column 256 is 2",
      (_T14_SEAM_ROW, _T14_SEAM_COL), (79, 2))
_apron_off = [i for i in range(hf.TILE_POINTS)
              if _mut_apron[T14_LAST][i] != T14_T10["heights"][T14_LAST][i]]
# The points that row MUST lose: the ones INSIDE the painted band, all four
# neighbours painted too, whose noise points DOWN. Asked of the module's own
# noise and the ray-cast, never of the raster. At the 2 m step there are
# eleven of them where the 4 m step had four — twice the points on the row,
# and a neighbour 2 m out falls inside the band where a 4 m one did not
# (x = 392 is in the list now: its eastern neighbour is 394, not 396).
_t14_band = T14_TERRAIN[0]["polygon"]
_seam_dips = [i for i in range(hf.TILE_POINTS)
              if all(point_in_polygon(256.0 + T14_S * i + dx, 256.0 + dz,
                                      _t14_band)
                     for dx, dz in ((0, 0), (T14_S, 0), (-T14_S, 0),
                                    (0, T14_S), (0, -T14_S)))
              and hf.micro_relief_at(T14_RELIEF[0][1], 256.0 + T14_S * i,
                                     256.0) < 0.0]
check("the seam row has eleven inner dips, from x = 350 to x = 392",
      [256 + T14_S * i for i in _seam_dips],
      [350.0, 352.0, 354.0, 378.0, 380.0, 382.0, 384.0, 386.0, 388.0,
       390.0, 392.0])
check("RED COUNTER-PROBE: without the apron the seam row loses exactly those",
      _apron_off, _seam_dips)
check("...every one of them a dip the world keeps and the mutant cuts to 0",
      all(T14_T10["heights"][T14_LAST][i] < _mut_apron[T14_LAST][i]
          for i in _apron_off), True)
check("...the shipped tile matches the overview at each of those points",
      all(T14_T10["heights"][T14_LAST][i]
          == at(F14, i + _T14_SEAM_COL, _T14_SEAM_ROW)
          for i in _apron_off), True)
check("...and the mutant matches it at none of them",
      all(_mut_apron[T14_LAST][i] != at(F14, i + _T14_SEAM_COL, _T14_SEAM_ROW)
          for i in _apron_off), True)


def t14_tile_widest_last(tx, tz):
    """RED COUNTER-PROBE (b): the plateau pass with the sort key REVERSED —
    smallest area first, so the largest writes last and wins where they
    overlap."""
    from app.core.world_geometry import (local_to_world, polygon_area,
                                         polygon_distance,
                                         polygon_interior_point,
                                         world_to_local)
    ox, oz = tx * hf.TILE_M, tz * hf.TILE_M
    n = hf.TILE_POINTS
    s = T14_S
    boxes = hf.area_boxes(T14_AREAS)
    heights = hf._window_grid(ox, oz, s, n, n, boxes, T14_RELIEF)
    for cx, cz, yaw, points in sorted(T14_FPS,
                                      key=lambda fp: polygon_area(fp[3])):
        inner = polygon_interior_point(points)
        wx, wz = local_to_world(inner[0], inner[1], cx, cz, yaw)
        h0 = hf.plateau_height(wx, wz, s, boxes, T14_RELIEF)
        for j in range(n):
            pz = oz + s * j
            for i in range(n):
                lx, lz = world_to_local(ox + s * i, pz, cx, cz, yaw)
                if polygon_distance(lx, lz, points) <= s + 1e-9:
                    heights[j][i] = h0
    return [[round(v, 3) for v in row] for row in heights]


# (356,152) inside tile (1,0): i = (356 − 256)/2 = 50, j = 152/2 = 76.
_mut_order = t14_tile_widest_last(1, 0)
near("RED COUNTER-PROBE: widest last puts FP_BIG's 6.0 on (356,152)",
     _mut_order[76][50], 6.0)
near("...where the shipped tile has the narrower place's 3.0",
     T14_T10["heights"][76][50], 3.0)
near("RED COUNTER-PROBE: with the ring tile struck from the index the ramp "
     "at (254,220) is gone", t14_sample(254, 220, index=T14_INDEX - {(0, 0)}),
     0.0)

print("  [14c] the same ground through the world — index, cache, world_height")
for _a in store.list_height_areas():
    store.delete_height_area(_a["id"])
for _a in list(terrain.list_areas()):
    terrain.delete_area(_a["id"])
set_relief("g", amplitude=1.0, wave=16.0)
store.save_height_area(T14_A1)
store.save_height_area(T14_A2)
terrain.save_area({"kind": "g", "polygon": square(264, 240, 396, 264)})
for _name, _fp in [("T14 Big", T14_BIG), ("T14 Small", T14_SMALL),
                   ("T14 West", T14_WEST), ("T14 Far", T14_FAR)]:
    # The outline's own edge, so the placed location and the literal above
    # describe the same square: local x runs from -half to +half.
    place_square(_name, _fp[0], _fp[1], _fp[3][1][0] - _fp[3][0][0])
# ``list_locations`` hands them out by NAME, so the DB order is Big, Far,
# Small, West rather than the fixture's. It changes nothing: the pass sorts by
# AREA (1600, 400, 64, 64 m²) and the only pair of equal area — Small and West
# — does not overlap, so no point is written by both. Tiles compared below.
check("the world hands the raster exactly the four footprints",
      store.placed_footprints(), [T14_BIG, T14_FAR, T14_SMALL, T14_WEST])
check("tile_index() is the hand-derived set", sorted(hf.tile_index()),
      [(0, 0), (1, 0), (1, 1)])
near("world_height on a support point", hf.world_height(348, 232), -9.0)
near("...on the plateau two places share", hf.world_height(356, 152), 3.0)
near("...on the ramp in the neighbour tile", hf.world_height(254, 220), 1.5)
near("...between the support points, right on the seam",
     hf.world_height(290, 256), t14_sample(290, 256), 1e-12)
near("...0 where no tile is indexed", hf.world_height(100, 300), 0.0)
near("...and 0 under the far hut", hf.world_height(2000, 2000), 0.0)
check("ground_y goes the same way", ground_y(356, 152),
      hf.world_height(356, 152))
check("a warm tile is the SAME object", hf.get_tile(1, 0) is hf.get_tile(1, 0),
      True)
_warm_tile = hf.get_tile(1, 0)
hf.invalidate_cache()
check("invalidating drops the tiles with the field",
      hf.get_tile(1, 0) is not _warm_tile, True)
check("...and the rebuilt tile carries the same numbers",
      hf.get_tile(1, 0)["heights"] == _warm_tile["heights"], True)
check("the world's tile IS the pure one",
      hf.get_tile(1, 0)["heights"] == T14_T10["heights"], True)

print("  [14d] what one tile costs (reported, not asserted)")
_giant_area = [{"id": "t14_giant", "polygon": square(0, 0, 8000, 8000),
                "height_m": 12.0, "falloff_m": 40.0}]
_giant_terrain = [{"kind": "g", "polygon": square(0, 0, 8000, 8000)}]
_t0 = time.perf_counter()
_giant_tile = hf.rasterize_tile(3, 3, _giant_area, footprints=(),
                                terrain_areas=_giant_terrain,
                                terrain_catalog=T14_CATALOG)
_giant_ms = (time.perf_counter() - _t0) * 1000.0
print(f"    a full tile over an 8 km area with relief: {_giant_ms:.1f} ms "
      f"({hf.TILE_POINTS}² points)")
check("...and it is a whole tile of ground",
      (_giant_tile["rows"], _giant_tile["cols"]), (129, 129))
# …and THE REASON THE TILES EXIST, on the very shape of [7]: the overview of
# an 8 km world is rastered at 32 m, where a 16 m wave cannot survive
# (Nyquist, [13k]) — the tile of the same world is still 2 m.
check("the overview over an 8 km area coarsens to a 32 m step",
      hf.rasterize(_giant_area)["step_m"], 32.0)
check("...while its tiles stay at the fine step, relief and all",
      _giant_tile["step_m"], hf.TILE_STEP_M)
# The tile's own centre: index 64 of 129 is x = 3·256 + 64·2 = 896, the same
# world point index 32 of 65 named at the 4 m step.
near("...deep inside the area, at the full height plus its noise",
     _giant_tile["heights"][64][64] - 12.0,
     hf.micro_relief_at(hf.relief_params("g", T14_CATALOG["g"]), 896.0, 896.0),
     5e-4)

print("[15] the tile-key query and the batch payload")
check("the plain case", hf.parse_tile_keys("1:0,2:3"), [(1, 0), (2, 3)])
check("junk tokens are skipped, the readable ones survive",
      hf.parse_tile_keys("1:0,x,2:3:4,,7"), [(1, 0)])
check("...and exactly those tokens are the ones the route says out loud",
      hf.unusable_tile_tokens("1:0,x,2:3:4,,7"), ["x", "2:3:4", "7"])
check("an empty token is no complaint", hf.unusable_tile_tokens("1:0,,"), [])
check("negative tile indices are ordinary tiles",
      hf.parse_tile_keys("-1:-2"), [(-1, -2)])
check("a duplicate collapses to its FIRST position",
      hf.parse_tile_keys("2:3,1:0,2:3"), [(2, 3), (1, 0)])
check("an empty query asks for nothing", hf.parse_tile_keys(""), [])
# The cap bites AFTER the dedupe: 65 distinct keys in, 64 out.
_65 = ",".join(f"0:{n}" for n in range(65))
check("65 distinct keys are cut to the cap",
      len(hf.parse_tile_keys(_65)), 64)
check("...and it is the 65th that is missing",
      (0, 64) in hf.parse_tile_keys(_65), False)
check("...while repeats never occupy a slot",
      len(hf.parse_tile_keys(",".join(f"0:{n},0:{n}" for n in range(64)))), 64)

# The payload, over the world [14c] left standing (index {(0,0),(1,0),(1,1)}).
check("the index travels as sorted payload keys — tx first, then tz",
      hf.tile_index_keys(), ["0,0", "1,0", "1,1"])
_batch = hf.tiles_payload(hf.parse_tile_keys("1:0,9:9"))
check("the batch names the tile with a COMMA, the query used a colon",
      sorted(_batch["tiles"].keys()), ["1,0"])
check("an unindexed tile is simply left out — no error, no empty grid",
      "9,9" in _batch["tiles"], False)
check("the batch carries THE one signature", _batch["sig"], store.height_sig())
check("...the tile edge", _batch["tile_m"], 256.0)
check("...and the always-fine step", _batch["step_m"], 2.0)
check("a tile entry is the grid without its own step",
      sorted(_batch["tiles"]["1,0"].keys()),
      ["cols", "heights", "origin_x", "origin_z", "rows"])
check("...and it IS the tile the rules read",
      _batch["tiles"]["1,0"]["heights"] == hf.get_tile(1, 0)["heights"], True)
check("...at the tile's own origin",
      (_batch["tiles"]["1,0"]["origin_x"], _batch["tiles"]["1,0"]["origin_z"]),
      (256.0, 0.0))

# THE SORT IS NUMERIC, and only a two-digit index can show it: a patch at
# x = 520…530 is tile floor(520/256) = 2, one at x = 2570…2580 is tile 10.
# Numerically 2 comes before 10; sorting the STRINGS would put "10,0" first.
store.save_height_area({"id": "t15_tx2", "polygon": square(520, 10, 530, 20),
                        "height_m": 2.0, "falloff_m": 2.0})
store.save_height_area({"id": "t15_tx10",
                        "polygon": square(2570, 10, 2580, 20),
                        "height_m": 2.0, "falloff_m": 2.0})
check("two-digit tile indices sort numerically, not lexicographically",
      hf.tile_index_keys(), ["0,0", "1,0", "1,1", "2,0", "10,0"])

print("\n[16] a 4 m relief wave — what the 2 m tile step bought")

T16_CATALOG = {"w": {"passable": True, "speed_factor": 1.0,
                     "meta": {"relief_amplitude_m": 0.5,
                              "relief_wave_m": 4.0}}}
T16_TERRAIN = [{"kind": "w", "polygon": square(600, 600, 700, 700)}]
T16_SEED = hf.relief_seed("w")
# The four corners of the wave cell (640,640)-(644,644), from the primitive
# [13]b derives by hand (xorshift32 step by step).
T16_N00 = hf.lattice_noise(T16_SEED, 160, 160)
T16_N10 = hf.lattice_noise(T16_SEED, 161, 160)
T16_N01 = hf.lattice_noise(T16_SEED, 160, 161)
T16_N11 = hf.lattice_noise(T16_SEED, 161, 161)
T16_MID = 0.5 * (T16_N00 + T16_N10 + T16_N01 + T16_N11) / 4.0

check("the 4 m wave survives the reader's clamp — the floor is 2 x 2 m now",
      hf.relief_params("w", T16_CATALOG["w"]), (T16_SEED, 0.5, 4.0))
near("the mid-cell value, mixed by hand from the four corners",
     T16_MID, -0.111142964044, 1e-11)
near("RED COUNTER-PROBE: at the old 8 m floor the same row built another "
     "ground — at (642,642) it RISES where the authored wave dips",
     hf.micro_relief_at((T16_SEED, 0.5, 8.0), 642, 642), 0.260513117624, 1e-11)

T16_TILE = hf.rasterize_tile(2, 2, [], footprints=(),
                             terrain_areas=T16_TERRAIN,
                             terrain_catalog=T16_CATALOG)
check("the patch's tile is anchored at (512, 512)",
      (T16_TILE["origin_x"], T16_TILE["origin_z"]), (512.0, 512.0))
near("(640,640) is a lattice CORNER: index 64 carries 0.5 · rnd(160,160)",
     T16_TILE["heights"][64][64], round(0.5 * T16_N00, 3), 1e-9)
near("(642,642) is the MID-cell point only a 2 m step has: index 65",
     T16_TILE["heights"][65][65], round(T16_MID, 3), 1e-9)
# Two support points per wave at 2 m, one at 4 m — the Nyquist limit, counted.
T16_AXIS = [512.0 + hf.TILE_STEP_M * i for i in range(hf.TILE_POINTS)]
check("one wave cell holds TWO tile support points, and only ONE at 4 m",
      ([x for x in T16_AXIS if 640.0 <= x < 644.0],
       [x for x in T16_AXIS if 640.0 <= x < 644.0 and x % 4.0 == 0.0]),
      ([640.0, 642.0], [640.0]))

F16_8 = hf.rasterize([], step_m=8.0, terrain_areas=T16_TERRAIN,
                     terrain_catalog=T16_CATALOG)
check("the 8 m raster of the same patch is 16 x 16 from (592, 592)",
      (F16_8["origin_x"], F16_8["origin_z"], F16_8["cols"], F16_8["rows"]),
      (592.0, 592.0, 16, 16))
near("RED COUNTER-PROBE: below two points per wave the field ALIASES — the "
     "8 m raster reads (644,644) as the mean of the corners it does hold",
     hf.sample_height(F16_8, 644, 644),
     0.5 * (T16_N00 + hf.lattice_noise(T16_SEED, 162, 160)
            + hf.lattice_noise(T16_SEED, 160, 162)
            + hf.lattice_noise(T16_SEED, 162, 162)) / 4.0, 5e-4)
near("...while the wave itself points the other way there: 0.5 · rnd(161,161)",
     hf.micro_relief_at((T16_SEED, 0.5, 4.0), 644, 644), 0.5 * T16_N11, 1e-12)

F16_4 = hf.rasterize([], step_m=4.0, terrain_areas=T16_TERRAIN,
                     terrain_catalog=T16_CATALOG)
near("HONESTLY: a 4 m raster reproduces a 4 m wave exactly — it holds every "
     "corner. What it did not do was let anybody ASK for one",
     hf.sample_height(F16_4, 642, 642), T16_TILE["heights"][65][65], 1e-9)

print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
