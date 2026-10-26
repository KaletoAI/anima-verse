#!/usr/bin/env node
/**
 * Smoke check for the height-tile LOADING POLICY —
 * `client3d/src/scene/heightTiles.ts` (§ A16.3).
 *
 * Usage:  node client3d/scripts/smoke_height_tiles.mjs
 *
 * Every number below is counted BY HAND from the tile raster, never recorded
 * from the current output. The question the file answers is "which indexed
 * tiles lie within 560 m of the anchor", and a want set that quietly loses the
 * rim of the radius is a ring of flat ground around the player that only shows
 * up as a step where the fine raster ends.
 *
 * ============================================================================
 * THE RASTER: tiles of 256 m, keys `"tx,tz"`, tile (tx, tz) covering
 * [tx·256, (tx+1)·256] × [tz·256, (tz+1)·256]. The test is box-to-point:
 * `dx` = how far the anchor is from the tile's x range (0 while inside it),
 * `dz` likewise, and the tile counts when dx² + dz² ≤ radius².
 * ============================================================================
 *
 * [1] THE ANCHOR AT THE ORIGIN, radius 560 (560² = 313 600)
 *
 *     Candidate columns for x = 0: tx runs floor(−560/256) = −3 … floor(560/256)
 *     = 2, and their distances are
 *         tx = −3 -> [−768, −512] -> dx = 512      512² = 262 144
 *         tx = −2 -> [−512, −256] -> dx = 256      256² =  65 536
 *         tx = −1 -> [−256,    0] -> dx =   0
 *         tx =  0 -> [   0,  256] -> dx =   0
 *         tx =  1 -> [ 256,  512] -> dx = 256
 *         tx =  2 -> [ 512,  768] -> dx = 512
 *     and the same six for z. Which pairs fit under 313 600:
 *         (0, 0)      0                  yes   2 × 2 = 4 tiles
 *         (0, 256)    65 536             yes   2 × 2 = 4   (and mirrored: 4)
 *         (256, 256)  131 072            yes   2 × 2 = 4
 *         (0, 512)    262 144            yes   2 × 2 = 4   (and mirrored: 4)
 *         (256, 512)  327 680            NO
 *         (512, 512)  524 288            NO
 *     -> 4 + 4 + 4 + 4 + 4 + 4 = 24 tiles.
 *
 *     NEAREST FIRST, ties by key: the four tiles the anchor stands in or on
 *     touch it (d = 0) and come first, in key order
 *     "-1,-1", "-1,0", "0,-1", "0,0"; the last one out is a d² = 262 144 tile.
 *
 * [2] RED COUNTER-PROBE — THE RIM IS THE PART THAT MATTERS. At radius 500
 *     (250 000) the 512-columns fall out: 262 144 > 250 000. That drops the
 *     (512, 0) group and the (0, 512) one, 8 tiles, leaving 16 — and "2,0",
 *     the tile due east across the last seam, is gone with them. A radius
 *     picked one tile too small looks exactly like this: everything near the
 *     player is fine and the world ends 500 m out, inside the fog's 520 m.
 *
 * [3] CROSSING A TILE BORDER CHANGES THE SET. The anchor at (300, 0) stands in
 *     tile (1, 0), one border east of the origin. Its columns:
 *         tx = −2 -> [−512, −256] -> dx = 556      309 136
 *         tx = −1 -> [−256,    0] -> dx = 300       90 000
 *         tx =  0 -> [   0,  256] -> dx =  44        1 936
 *         tx =  1 -> [ 256,  512] -> dx =   0
 *         tx =  2 -> [ 512,  768] -> dx = 212       44 944
 *         tx =  3 -> [ 768, 1024] -> dx = 468      219 024
 *     against the rows dz ∈ {512, 256, 0, 0, 256, 512} of z = 0 (tz = −3 … 2).
 *     Per column, how many of the six rows fit under 313 600:
 *         tx = −2: dz = 0 only            -> 2
 *         tx = −1: dz = 0, 256            -> 4      (90 000 + 262 144 > cap)
 *         tx =  0: all three              -> 6
 *         tx =  1: all three              -> 6
 *         tx =  2: all three              -> 6      (44 944 + 262 144 = 307 088)
 *         tx =  3: dz = 0, 256            -> 4      (219 024 + 262 144 > cap)
 *     -> 28 tiles, "3,0" now in and "-3,0" now out. THAT is why a border
 *     crossing has to recompute: the far half of the set is a different half.
 *
 * [4] THE INDEX CUTS THE SET. The want set is intersected with the tiles the
 *     world says it has a ground in, so an index of two keys can never produce
 *     more than those two — and never a request for a tile the server would
 *     answer with nothing.
 *
 * [5] BATCHES OF 64, in order. 130 keys are 64 + 64 + 2, and the first batch
 *     holds the nearest tiles because `wantedTiles` sorted them that way.
 *
 * [6] DEGENERATE INPUTS answer with nothing rather than with a guess: no tile
 *     size, an empty index, a non-finite anchor. Radius 0 is not degenerate —
 *     it is the anchor's own tile, and nothing else.

 *
 * Shared-vector companion hand derivations (also retained at their original sites):
 * Companion: smoke_world_height.mjs

 * Smoke check for the shared WORLD height sampler —
 * `packages/scene-render/src/worldHeight.ts` (§ A16).
 *
 * Usage:  node client3d/scripts/smoke_world_height.mjs
 *
 * TWIN DISCIPLINE. The same field and the same expected numbers are checked
 * against the Python side in `scripts/smoke_heightfield.py`, section [8]. One
 * bilinear rule, two implementations, ONE hand-derived table — because the
 * server refuses a walk report using its reading of this field while the
 * renderer drapes the ground with this one, and the two disagreeing is a
 * figure that gets snapped back on a hill the picture calls gentle.
 *
 * Every number below is derived by hand here and never recorded from the
 * current output.
 *
 * ============================================================================
 * THE FIELD: a single 5 m peak
 * ============================================================================
 * origin (−4, −4), step 4, 3 × 3 support points, so the points sit at
 * x, z ∈ {−4, 0, 4} and the middle one (0, 0) is 5 m high:
 *
 *     heights = [[0, 0, 0],
 *                [0, 5, 0],
 *                [0, 0, 0]]
 *
 * The rule: fx = clamp((x − origin_x)/step, 0, cols−1),
 *           i = min(floor(fx), cols−2), tx = fx − i   (fz/j/tz likewise),
 *           mix h[j][i], h[j][i+1], h[j+1][i], h[j+1][i+1] bilinearly.
 *
 * (1) (0, 0)      fx = 1, fz = 1 -> i = j = 1, tx = tz = 0
 *                 -> h[1][1] = 5                                    -> 5
 * (2) (2, 0)      fx = 1.5 -> i = 1, tx = 0.5; fz = 1 -> j = 1, tz = 0
 *                 north = 5·0.5 + 0·0.5 = 2.5, south = 0            -> 2.5
 * (3) (2, 2)      both fractions 0.5; only the h[1][1] corner carries a
 *                 height: 0.25 · 5                                  -> 1.25
 * (4) (0, −2)     fz = 0.5 -> j = 0, tz = 0.5; fx = 1 -> tx = 0
 *                 north = h[0][1] = 0, south = h[1][1] = 5
 *                 -> 0·0.5 + 5·0.5                                  -> 2.5
 * (5) (−4, −4)    the corner support point itself                   -> 0
 * (6) (100, 0)    far east: fx clamps to cols−1 = 2, i = min(2, 1) = 1,
 *                 tx = 1 -> north = h[1][2] = 0                     -> 0
 *                 (the server always rasters a 0 ring outside the authored
 *                  areas, so "clamp to the border" IS "the flat world")
 * (7) (−100, −100) far north-west: both clamp to 0 -> h[0][0]       -> 0
 * (8) HALF WAY UP THE FLANK, (−2, 0): fx = 0.5 -> i = 0, tx = 0.5;
 *                 fz = 1 -> j = 1, tz = 0
 *                 north = h[1][0]·0.5 + h[1][1]·0.5 = 2.5           -> 2.5
 * (9) DEGENERATE FIELDS carry no relief: a single row (rows < 2), a single
 *     column (cols < 2), step 0, and `null`/`undefined`               -> 0
 * (10) THE EMPTY WORLD as the endpoint sends it (rows/cols 0, heights [])
 *      -> 0, and not a crash: a world nobody has shaped is flat.
 * (11) A RAGGED FIELD — heights [[0, 10], [0]], origin (0, 0), step 4. The
 *      shape comes from the ARRAY, never from `rows`/`cols`, and a missing
 *      entry reads as 0: at (2, 2) north = 0·0.5 + 10·0.5 = 5, south = 0,
 *      both fractions 0.5 -> 2.5. Same number on the Python side (section [8]
 *      there). And `rows`/`cols` claiming 99 changes nothing: with
 *      [[0, 10], [0, 10]] the point (2, 2) is 5.
 *
 * ============================================================================
 * [4] THE HEIGHT SOURCE IS ONE READING — the counter-probe of E5b
 * ============================================================================
 * `main.ts` `reliefLiftAt` used to ask TWO sources and add them: the WORLD
 * field (`sampleWorldHeight`, the bilinear reading — the server's own) plus the
 * scene relief of the INNERMOST enclosing location that had a field, composed
 * by `game/ground.groundLift`. "Ein Boden" E5b deletes the second term with the
 * field it read: a location has no 17 x 17 relief of its own any more
 * (§ A16.1, decision 1), local relief is authored through the map's HEIGHT AREAS,
 * and `reliefLiftAt` became one line — then lost its last caller with the
 * room huddle (T4) and is gone with it. The walk verdict is unchanged
 * (`client3d/src/game/walk.slopeBlocks`), and both are checked against the
 * field above.
 *
 * (12) THE FLANK, walking east from (−2, 0) to (−1, 0):
 *        h(−2, 0) = 2.5                                  (case 8 above)
 *        h(−1, 0): fx = (−1+4)/4 = 0.75 -> i = 0, tx = 0.75; fz = 1 -> j = 1
 *                  north = 0·0.25 + 5·0.75 = 3.75        -> 3.75
 *      so dh = 1.25 over dist 1. dist is NOT below 1 m, so the step limit
 *      does not apply; atan(1.25 / 1) = 51.3402° > 40° -> BLOCKED.
 *      RED COUNTER-PROBE: on flat ground dh = 0 and nothing is refused — the
 *      shape of the rubber-band regression that the world term closed.
 * (13) THE SECOND TERM, AS THE NUMBER IT NO LONGER PRODUCES. At (2, 2) the
 *      world says 1.25. Two enclosing locations — a square of edge 80
 *      (6400 m²) lifting 0.2 m and a hut of edge 20 (400 m²) lifting 1.0 m —
 *      would have made that 2.25 through the innermost of them (the smaller
 *      area was the more specific answer, finding F3 / contract v6 Nr. 6) and
 *      1.45 through the outermost. Neither is reachable: the point is 1.25,
 *      which is exactly the height the server judges it by.
 * (14) THE PLATEAU IS FLAT, which is what makes a place walkable on a hill:
 *      the bake stamps the field flat under every BUILT footprint (§ G5), so
 *      BOTH ends of a step inside it read the same height (5 on the levelled
 *      field below), dh = 0 and `slopeBlocks` is inert — even over 0.15 m, the
 *      walking lead that would refuse a 0.5 m rise as a step.
 *
 * ============================================================================
 * [5] WHERE THE FIGURE STANDS INSIDE A FOOTPRINT — `game/ground.standY`
 * ============================================================================
 * Acceptance finding 4 (2026-08-13): `tileGroundY` measured everything from the
 * location's centre — plate, model skin, scene relief — so it knew ONE world
 * height for the whole footprint, while a traveller outside was already sampled
 * off the world field. The figure walked at plate height through a rising hill,
 * and at the border the height rule changed and it jumped. The user's rule is
 * THE HIGHER ONE WINS, and it is the whole of `standY(walkY, terrainY)`.
 *
 * (15) THE HILL RUNS THROUGH THE PLATE: the tile of a place at the foot of the
 *      5 m peak stands on its centre height, say 1.25 (the field at (2, 2)),
 *      while the world under a point further in reads 2.5 (the flank at
 *      (2, 0), case 3/2 above). standY(1.25, 2.5) = 2.5 — the figure walks up
 *      the hill instead of into it.
 *      RED COUNTER-PROBE: `min` instead of `max` gives 1.25, which IS the
 *      finding — the plate height while the ground rises through it.
 * (16) THE MODEL WINS WHERE IT IS HIGHER: a bridge or a raised shore rayed at
 *      3.0 over a world ground of 2.5 answers 3.0. Nothing about the rule
 *      prefers one source; it prefers the HIGHER one, in both directions.
 * (17) EQUAL SOURCES ANSWER THAT ONE NUMBER: standY(5, 5) = 5. This is the
 *      BUILT FOOTPRINT (`draws_built_floor`, § A16.4): the bake stamps the
 *      field to exactly the plateau the tile stands on, so the rule is inert
 *      there by construction — a no-op, not an exception.
 * (18) A SUNKEN PLACE IS UNDERCUT, and knowingly so: a lake bed at −0.8 under a
 *      world ground of 0 answers 0. That is the price of the rule, named in the
 *      spec (§ A16) — an area model that dips below the landscape is an
 *      authoring matter.
 * (19) NaN IS NOT A HEIGHT. A figure put at NaN never recovers, so a
 *      non-finite reading lets the other source answer alone:
 *      standY(NaN, 2.5) = 2.5, standY(1.25, NaN) = 1.25 (the state before the
 *      field has arrived — the client passes NaN then, deliberately, so a tile
 *      standing below zero is not lifted to zero by a missing field), and
 *      standY(NaN, NaN) = 0, the tile floor.
 *      Infinity is not a height either: standY(1.25, Infinity) = 1.25.
 * (20) NEGATIVE HEIGHTS COMPARE LIKE ANY OTHER: standY(−1, −4) = −1.
 *
 * ----------------------------------------------------------------------------
 * [6] and [7] ARE GONE ("Ein Boden" E3, plan-ein-boden.md § 3.1)
 * ----------------------------------------------------------------------------
 * Both sections measured the FOOTPRINT PLATE — the tile's own draped ground:
 * [6] pinned `game/ground.plateLift` (the clamped mirror of `standY` that
 * lifted a plate vertex onto the world field), [7] pinned which points the
 * plate's flatness probe reads (3 × 3 blind vs. the 2 m drape grid, review
 * finding I2). The tile draws no ground of its own any more — the terrain IS
 * the ground under a location — so `plateLift`, the drape lattice and the
 * flatness probe were deleted, and a check of deleted arithmetic proves
 * nothing. What survived them is `standY` in [5]: a figure still reconciles a
 * tile answer with the terrain under it, and case (15) is exactly that.
 *
 * The numbering below is deliberately NOT closed up — sections [8]… keep their
 * names so the file's cross-references and the twin `scripts/smoke_heightfield.py`
 * still point at the same content.
 *
 * ============================================================================
 * [8] THE TILED FIELD — `heightAt`, the ONE ladder over both rasters
 * ============================================================================
 * § A16.3. Since v2 the same landscape arrives as TWO rasters: a coarsenable
 * overview over everything, and 256 m tiles in the always-fine 4 m step. The
 * ladder is fine tile -> overview -> 0, and the two are NEVER mixed for one
 * point.
 *
 * The two fields below are built to DISAGREE on purpose — a precedence check
 * can prove nothing against two rasters that answer the same. Disagreement is
 * also the documented state as soon as the overview is coarsened (§ A16.3: the
 * resolution itself, plus a levelling ramp that is "one cell wide" in either
 * raster and therefore reaches further in the coarse one).
 *
 *   OVERVIEW  origin (0, 0), step 256, 3 x 3 support points at 0, 256, 512,
 *             heights[j][i] = i + 3j — i.e. the plane
 *                 ov(x, z) = x/256 + 3·z/256
 *             (bilinear over a plane IS that plane, so every reading inside
 *              [0, 512]^2 is the formula; outside it clamps to the border)
 *   TILES     tile (tx, tz) = the 65 x 65 window of the FINE ramp
 *                 fine(x, z) = x/128
 *             at origin (256·tx, 256·tz), step 4: heights[j][i] =
 *             (256·tx + 4i)/128. Loaded are (0,0) and (1,0). The fine ramp
 *             climbs TWICE as fast as the overview plane, so any reading says
 *             at once which raster answered it.
 *
 * (25) `tileKeyAt` IS THE ONE KEY MAPPING: (0, 0) -> "0,0"; (255.9, 10) ->
 *      "0,0"; (256, 0) -> "1,0", because a point on a seam belongs to the tile
 *      east/south of it; (-1, -300) -> "-1,-2", since floor(-1/256) = -1 and
 *      floor(-300/256) = floor(-1.171875) = -2 — negative tiles are ordinary.
 * (26) THE PRECEDENCE TABLE.
 *      (128, 8) lies in the loaded tile (0,0): fine = 128/128 = 1, while the
 *          overview would have said 128/256 + 3·8/256 = 0.5 + 0.09375 =
 *          0.59375. The fine tile wins, and the gap is the proof that it did.
 *      (384, 8) lies in the loaded tile (1,0): fine = 384/128 = 3, against an
 *          overview reading of 1.5 + 0.09375 = 1.59375.
 *      (100, 300) lies in tile "0,1", which is NOT loaded -> the overview:
 *          100/256 + 3·300/256 = 0.390625 + 3.515625 = 3.90625.
 *      OUTSIDE EVERYTHING -> 0, the flat world: the same point with no overview
 *          in the composite at all, an empty composite, and a null one.
 * (27) NEVER MIXED, and here is where that shows. A (synthetic) short tile at
 *      (0,0) carrying only 3 x 3 points at step 4, heights[j][i] = i, so its
 *      support points at x = 0, 4, 8 are 0, 1, 2. At (128, 8) it clamps to its
 *      own east border and answers 2 — it does NOT let the overview (0.59375)
 *      fill the part of the tile square it has no support point for. A loaded
 *      tile answers alone.
 * (28) THE SEAM IS CONTINUOUS, because both tiles carry the support points on
 *      x = 256: tile (0,0) as its column i = 64, (0 + 4·64)/128 = 2, and tile
 *      (1,0) as its column i = 0, (256 + 0)/128 = 2. Read out of either field
 *      the answer at (256, 12) is that same 2.
 *      Through the composite, (255.999, 12) is read out of tile (0,0) and — the
 *      ramp being linear, so bilinear reproduces it — is 255.999/128 =
 *      1.9999921875, while (256, 12) is read out of tile (1,0) and is 2. The
 *      difference across the seam is 7.8125e-6: the ramp's own rise over that
 *      millimetre, not a step.
 *      RED COUNTER-PROBE: corrupt tile (0,0)'s east column to 9. That field now
 *      answers 9 at (256, 12) — a seam gap of 7 m against its neighbour — and
 *      the composite reading just west of the seam becomes
 *      1.96875·0.00025 + 9·0.99975 = 8.9982421875 (the cell between
 *      h[3][63] = 252/128 = 1.96875 and the corrupted 9, at tx = 0.99975), so
 *      the walk across the seam drops 6.9982421875 m. The continuity check
 *      bites.
 * ============================================================================
 * [8e] THE DRAWN GROUND IS GONE — one sampler, and the numbers it replaced
 * ============================================================================
 * "Ein Boden" E2. Until this stage the client carried a SECOND height: the
 * surface its one big base plate really was, two triangles per cell of
 * `cellM` (a step DOUBLED until the plate fit a 40 000-cell budget — 64 m in
 * the live world; that helper is deleted with the drape it sized, E5b). Everything that touched the
 * ground was placed on THAT, because the ground the player saw was that mesh.
 * The mesh is gone: the terrain is a CDLOD patch whose vertices come out of
 * the lattice itself (`scene/terrainLod.ts`), so there is one answer and it is
 * the field.
 *
 * THIS SECTION KEEPS THE NUMBERS AS COUNTER-PROBES. The dead formula is
 * written out inside the file (`drawnTriangle`) because the package does not
 * carry it any more, and the checks pin (a) that the sampler answers the
 * bilinear reading, (b) how far the plate used to be from it, and (c) that no
 * export answers the plate's number for anybody.
 *
 * THE FIELD FOR THIS SECTION: a flat 3 x 3 overview at step 256 (so the
 * overview contributes nothing and every number comes from the tile), and one
 * loaded tile (0,0) of 65 x 65 zeroes with a single support point lifted —
 * ONE corner of a cell, which is what a twist is.
 *
 * (33) THE TWIST TILE has its 8 m on the support point i = j = 34, i.e. at
 *      (136, 136); everything else in the tile is 0. On a support point every
 *      reading agrees: (136, 136) -> 8.
 * (34) INSIDE THE CELL, at (134, 134). The 4 m cell is [132, 136]^2 with
 *      corners h00 = h10 = h01 = 0 and h11 = 8, tx = tz = 0.5:
 *        BILINEAR (the answer today) = 0.25 · 8                     = 2
 *        the 4 m triangle (tz <= tx) = 0 + 0.5·(0−0) + 0.5·(8−0)    = 4
 *        the 8 m cell [128, 136]^2, tx = tz = 0.75                  = 6
 *      i.e. the coarser the plate, the further from the field — 2 m and 4 m of
 *      error on a single 8 m spike, which is the shape of the 2.433 m measured
 *      on the live world's 64 m cells.
 * (35) SO THE CELL SIZE NO LONGER CHANGES THE ANSWER. The differences above
 *      are asserted as the gaps that USED to exist (−2 and −4); the sampler
 *      itself takes no cell size at all any more, and the module exports
 *      neither `sampleCompositeGroundHeight` nor `sampleGroundHeight`.
 * (36) AND IT CUT BOTH WAYS: what the plate did NOT have, it did not draw. A
 *      spike on the support point i = j = 33, i.e. at (132, 132), sits BETWEEN
 *      the corners of an 8 m grid, so that plate drew 0 over a 5 m hill — a
 *      figure walked straight through it. The sampler answers the hill.
 *
 * ============================================================================
 * [9] THE SERVER'S OWN FORMULA, ON BOTH STEP SIZES
 * ============================================================================
 * The bilinear reading has to be formula-identical to
 * `app/core/heightfield.sample_height` — the server refuses a walk by ITS
 * reading, so a client half a metre away shows a hill the player is refused on.
 * Since E1 the server's height is one pure function sampled on lattices that
 * are subsets of each other (addendum § 1), and the client draws BOTH: the
 * 2 m tiles under the play and the 4 m overview behind it. So the formula is
 * pinned on both.
 *
 * THE FIXTURE is a square pyramid, apex at the world origin, foot on the 8 m
 * ring: h(x, z) = 5 · max(0, 1 − max(|x|, |z|) / 8), rastered over
 * [-8, 8]^2 at 2 m (9 x 9 points) and at 4 m (5 x 5). The 4 m lattice is a
 * SUBSET of the 2 m one, which is the congruence § A16.3 guarantees.
 *
 * (37) The raster sizes, so a wrong fixture cannot pass silently.
 * (38) ON SUPPORT POINTS both rasters carry the function exactly: apex 5, the
 *      4 m point (4, 0) -> 5·(1 − 4/8) = 2.5 in BOTH, the foot (8, 8) -> 0.
 * (39) BETWEEN them, at (1, 0), the arithmetic is written out in the code and
 *      both rasters answer 4.375 — that line of the pyramid is linear and both
 *      carry its ends.
 * (40) At (1, 1) the twist bites: 2 m -> 4.0625, 4 m -> 3.90625, a gap of
 *      0.15625 m. That gap is the RESOLUTION difference, which is what the LOD
 *      morph is for; it is no longer a data change under the player's feet,
 *      because the two rasters are the same function.
 * (41) AND THE LADDER PICKS THE FINE ONE: with the 2 m raster loaded as tile
 *      "0,0" of a 16 m tile world, (1, 1) reads 4.0625 while (-1, -1) — in the
 *      unloaded tile "-1,-1" — reads the overview's 3.90625.
 *
 * WHAT IS NOT HERE ANY MORE: the rectangle helpers `maxCompositeHeightIn` /
 * `compositeHeightRangeIn` (contract v6 Nr. 8 switched the veil off) and, as
 * of E2, `maxWorldHeightIn` / `worldHeightRangeIn` with them — the last two
 * read the drawn ground and had no caller left once the fog was gone.

 *
 * [20] Additional lattice boundary cases: floor(256/256)=1 and
 * floor(0/256)=0 give key1,0; floor(-.1/256)=-1 and floor(-256/256)=-1
 * give -1,-1. The2x2 lattice[0,2;4,6], step2, averages four corners
 * at(1,1): (0+2+4+6)/4=3. Outside at(20,20) clamps to corner6.
 */
import { vectorCase, vectorArgs, vectorValue } from './e3VectorSupport.mjs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/**
 * Bundle the module under test into ONE file inside the repo and import it.
 * Inside on purpose: `heightTiles.ts` imports `tileKeyAt` from
 * `@anima/scene-render` (there is ONE key mapping and this file does not own
 * it), which resolves through the workspace's `node_modules` — and the package
 * takes `three` as a parameter everywhere, so nothing of it survives into the
 * bundle.
 */
async function loadHeightTiles() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const entry = "export { wantedTiles, tileBatches, HEIGHT_TILE_RADIUS_M,"
      + " HEIGHT_TILE_BATCH_MAX, HEIGHT_TILE_CACHE_MAX }"
      + ` from '${join(ROOT, 'client3d/src/scene/heightTiles')}';`;
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'heightTiles.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'heightTiles.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function vector(label, fns) {
  const result = vectorCase("height_tiles", label, fns);
  passed += result.passed; failed += result.failed;
}

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}

const {
  wantedTiles, tileBatches, HEIGHT_TILE_RADIUS_M, HEIGHT_TILE_BATCH_MAX,
  HEIGHT_TILE_CACHE_MAX,
} = await loadHeightTiles();

const TILE_M = 256;
/** Everything from tile (−8, −8) to (8, 8) exists — a world with ground
 *  everywhere, so only the radius decides. */
const FULL = new Set();
for (let tz = -8; tz <= 8; tz += 1) {
  for (let tx = -8; tx <= 8; tx += 1) FULL.add(`${tx},${tz}`);
}

console.log('[0] the constants the policy is written in');
check('the load radius clears the fog end of 520 m', HEIGHT_TILE_RADIUS_M, 560);
check('the batch cap is the server\'s', HEIGHT_TILE_BATCH_MAX, 64);
check('the LRU cap', HEIGHT_TILE_CACHE_MAX, 96);

console.log('[1] the anchor at the origin — 24 tiles, counted by hand');
const atOrigin = wantedTiles(FULL, TILE_M, 0, 0, 560);
vector("[1] height_tiles: tiles within 560 m of (0, 0)", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
check('the four tiles touching the anchor come first',
  atOrigin.slice(0, 4).join(' '), '-1,-1 -1,0 0,-1 0,0');
check('the tile due east across one seam is in', atOrigin.includes('2,0'), true);
check('the diagonal at (256, 512) is out', atOrigin.includes('1,2'), false);
check('...and so is the far diagonal', atOrigin.includes('2,2'), false);
check('the last one out is a rim tile', atOrigin[atOrigin.length - 1], '2,0');

console.log('[2] RED COUNTER-PROBE: one tile less radius loses the rim');
const tooSmall = wantedTiles(FULL, TILE_M, 0, 0, 500);
vector("[2] height_tiles: at 500 m the rim columns fall out", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
check('...and "2,0" with them', tooSmall.includes('2,0'), false);
check('the ring that is lost', atOrigin.length - tooSmall.length, 8);

console.log('[3] crossing a tile border changes the set');
const eastward = wantedTiles(FULL, TILE_M, 300, 0, 560);
vector("[3] height_tiles: tiles within 560 m of (300, 0)", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
check('a tile appears in the east', eastward.includes('3,0'), true);
check('...and one drops off in the west', eastward.includes('-3,0'), false);
check('the west tile WAS in the origin set', atOrigin.includes('-3,0'), true);
check('the two tiles the anchor now touches come first',
  eastward.slice(0, 2).join(' '), '1,-1 1,0');
check('the same anchor answers the same set twice',
  wantedTiles(FULL, TILE_M, 300, 0, 560).join(' ') === eastward.join(' '), true);

console.log('[4] the index cuts the set');
const SPARSE = new Set(['0,0', '5,5']);
check('only what the world has a ground in',
  wantedTiles(SPARSE, TILE_M, 0, 0, 560).join(' '), '0,0');
vector("[4] height_tiles: an index that knows nothing here", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });

console.log('[5] batches of 64, nearest first');
const many = [];
for (let i = 0; i < 130; i += 1) many.push(`k${i}`);
const batches = tileBatches(many);
vector("[5] height_tiles: 130 keys are three requests", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: the first is full", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: the second too", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: the tail is the rest", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: and the order survives", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: ...through the split", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
check('one batch is enough for a full want set',
  tileBatches(atOrigin).length, 1);
vector("[5] height_tiles: nothing wanted is no request", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: a nonsense batch size still terminates", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });

console.log('[6] degenerate inputs answer with nothing');
vector("[6] height_tiles: no tile size", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
vector("[6] height_tiles: a negative tile size", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
vector("[6] height_tiles: an empty index", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
check('a NaN anchor', wantedTiles(FULL, TILE_M, NaN, 0, 560).length, 0);
check('an infinite radius', wantedTiles(FULL, TILE_M, 0, 0, Infinity).length, 0);
check('radius 0 is the anchor\'s own tile and nothing else',
  wantedTiles(FULL, TILE_M, 300, 300, 0).join(' '), '1,1');

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
