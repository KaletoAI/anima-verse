#!/usr/bin/env node
/**
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
 * [4] THE COMBINED HEIGHT SOURCE — the client's mirror of the walk rule
 * ============================================================================
 * E8 task 4. `main.ts` `reliefLiftAt` asks TWO sources and adds them:
 * the WORLD field (`sampleWorldHeight`, the bilinear reading — the server's
 * own) and, on top, the scene relief of the INNERMOST enclosing location that
 * has a field. The composition rule is `client3d/src/game/ground.groundLift`,
 * the walk verdict is `client3d/src/game/walk.slopeBlocks`; both are pure and
 * checked here against the very field above.
 *
 * (12) THE FLANK, walking east from (−2, 0) to (−1, 0), no scene relief:
 *        h(−2, 0) = 2.5                                  (case 8 above)
 *        h(−1, 0): fx = (−1+4)/4 = 0.75 -> i = 0, tx = 0.75; fz = 1 -> j = 1
 *                  north = 0·0.25 + 5·0.75 = 3.75        -> 3.75
 *      so dh = 1.25 over dist 1. dist is NOT below 1 m, so the step limit
 *      does not apply; atan(1.25 / 1) = 51.3402° > 40° -> BLOCKED.
 *      RED COUNTER-PROBE, and it is the regression this task closes: with the
 *      world term LEFT OUT — the mirror as task 3 shipped it, scene relief
 *      only — both heights are 0, dh = 0 and the client walks on while the
 *      server refuses. That is the rubber band of the acceptance list.
 * (13) THE INNERMOST SCENE RELIEF WINS. At (2, 2) the world says 1.25.
 *      With two enclosing locations — a square of edge 80 (6400 m²) lifting
 *      0.2 m and a hut of edge 20 (400 m²) lifting 1.0 m — the answer is
 *      1.25 + 1.0 = 2.25: the SMALLER-AREA footprint is the more specific one
 *      (finding F3, and contract v6 Nr. 6 which replaced the smallest-width
 *      rule with it). With no patch at all it is the world alone, 1.25.
 * (14) THE PLATEAU IS FLAT, which is what makes a place walkable on a hill:
 *      the server levels the field under every footprint, so BOTH ends of a
 *      step inside it read the same height (5 on the levelled field below),
 *      dh = 0 and `slopeBlocks` is inert — even over 0.15 m, the walking lead
 *      that would refuse a 0.5 m rise as a step.
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
 *      LEVELLED FOOTPRINT (`level_ground`, § A16.1): the server flattens the
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
 * [6] AND WHAT THE PLATE DOES — `game/ground.plateLift` (review finding I1)
 * ----------------------------------------------------------------------------
 * The footprint plate is drawn where the figure walks, so it is derived from
 * `standY` and not written twice: `plateLift(worldY, tileY) = standY(tileY,
 * worldY) − tileY`. A tile standing on 2.0:
 *
 * (21) UPHILL, world 3.2: lift 1.2, and the figure stands on standY(2.0, 3.2)
 *      = 3.2 = tile floor + lift. Plate and figure on ONE surface.
 * (22) DOWNHILL, world 0.5: lift 0 — the plate stays the tile floor, and the
 *      figure stands on standY(2.0, 0.5) = 2.0. One surface again, with the
 *      landscape passing underneath.
 *      RED COUNTER-PROBE: the unclamped difference is −1.5, which would drop
 *      the plate a metre and a half away under a figure that stays at 2.0 —
 *      the finding mirrored, and what this clamp exists for.
 * (23) LEVEL / LEVELLED FOOTPRINT (world = tile = 2.0): lift 0, no cut.
 * (24) NO FIELD YET (world NaN): lift 0 — the plate is the flat square it was.
 *
 * ----------------------------------------------------------------------------
 * [7] WHERE THE FLATNESS PROBE LOOKS (review finding I2)
 * ----------------------------------------------------------------------------
 * The plate is cut only where the ground moves. WHICH points are asked decides
 * whether that is true, and a 3 × 3 probe (corners, edge midpoints, centre)
 * cannot see a hill between its samples. Hand-built field for exactly that:
 *
 *     origin (−4, −4), step 2, 5 × 5 support points at −4, −2, 0, 2, 4,
 *     all zero except h[3][3] = 5, i.e. the peak sits on (x, z) = (2, 2).
 *
 * A footprint of width 8 centred on (0, 0), tile floor 0:
 *   - the 3 × 3 probe asks (0, 0) and (±4, ±4)/(±4, 0)/(0, ±4). Every one of
 *     those is a support point of value 0 (the far ones clamp to the border,
 *     which is 0 as well) -> spread 0 -> ONE quad -> the hill cuts through the
 *     plate. THAT is the finding.
 *   - the DRAPE GRID at `DRAPE_STEP_M` = 2 m asks −4, −2, 0, 2, 4 on both
 *     axes, so (2, 2) is one of its 25 samples -> max lift 5 -> draped.
 * Both readings are taken on support points, so the bilinear reading used here
 * and the drawn sampler the client uses agree on them to the digit.
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
 * `cellM` (`gridStepFor`, which DOUBLED the field's step until the plate fit a
 * 40 000-cell budget — 64 m in the live world). Everything that touched the
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
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/worldHeight.ts');

/** Transpile a PURE module and import it. Every file loaded this way is
 *  free of runtime dependencies except the equally pure siblings named in
 *  `deps` (same directory, listed by file name): should someone add an import
 *  to `three`, the DOM or anything else, this fails loudly — that is the
 *  alarm, and it is the reason the list is explicit rather than resolved.
 *  `ground.ts` takes `polygon.ts` that way since it carries the recipe-floor
 *  rule (§ B1/B2 addendum 2026-08-20), exactly as `smoke_walk_math.mjs` loads
 *  the pair. */
async function loadModule(path, name, deps = []) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'worldheight-'));
  const fixImports = (code) =>
    code.replace(/(from\s*["'])(\.\/[\w-]+)(["'])/g, '$1$2.mjs$3');
  try {
    for (const dep of deps) {
      const src = await readFile(join(path, '..', `${dep}.ts`), 'utf8');
      await writeFile(join(dir, `${dep}.mjs`),
        fixImports(esbuild.transformSync(src, { loader: 'ts', format: 'esm' }).code),
        'utf8');
    }
    const source = await readFile(path, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, `${name}.mjs`);
    await writeFile(file, fixImports(out.code), 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = typeof actual === 'number' && Math.abs(actual - expected) <= eps;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}

// The whole namespace, not just the names used: section [8e] asserts that the
// DEAD samplers are absent, and it can only do that by looking at what the
// module really exports.
const mod = await loadModule(SRC, 'worldHeight');
const { sampleWorldHeight, tileKeyAt, heightAt } = mod;
const { groundLift, plateLift, standY } = await loadModule(
  join(ROOT, 'client3d/src/game/ground.ts'), 'ground', ['polygon']);
const { slopeBlocks } = await loadModule(
  join(ROOT, 'client3d/src/game/walk.ts'), 'walk');

const FIELD = {
  origin_x: -4, origin_z: -4, step_m: 4, rows: 3, cols: 3,
  heights: [[0, 0, 0], [0, 5, 0], [0, 0, 0]],
};

console.log('[1] the peak and its flanks');
check('(0, 0) the peak', sampleWorldHeight(FIELD, 0, 0), 5);
check('(2, 0) half a cell east', sampleWorldHeight(FIELD, 2, 0), 2.5);
check('(2, 2) diagonally between', sampleWorldHeight(FIELD, 2, 2), 1.25);
check('(0, -2) half a cell north', sampleWorldHeight(FIELD, 0, -2), 2.5);
check('(-2, 0) half a cell west', sampleWorldHeight(FIELD, -2, 0), 2.5);
check('(-4, -4) the corner point', sampleWorldHeight(FIELD, -4, -4), 0);

console.log('[2] outside the grid: the border, which is the flat world');
check('(100, 0) far east', sampleWorldHeight(FIELD, 100, 0), 0);
check('(-100, -100) far north-west', sampleWorldHeight(FIELD, -100, -100), 0);
check('(0, 100) far south', sampleWorldHeight(FIELD, 0, 100), 0);

console.log('[3] degenerate fields carry no relief');
check('a single row', sampleWorldHeight(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 1, cols: 3, heights: [[1, 2, 3]] },
  4, 0), 0);
check('a single column', sampleWorldHeight(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 3, cols: 1, heights: [[1], [2], [3]] },
  0, 4), 0);
check('step 0', sampleWorldHeight(
  { origin_x: 0, origin_z: 0, step_m: 0, rows: 2, cols: 2, heights: [[1, 1], [1, 1]] },
  0, 0), 0);
check('the empty world', sampleWorldHeight(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 0, cols: 0, heights: [] }, 0, 0), 0);
check('a ragged row is a height, not a crash', sampleWorldHeight(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 2, cols: 2, heights: [[0, 10], [0]] },
  2, 2), 2.5);
check('rows/cols lying about the array', sampleWorldHeight(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 99, cols: 99, heights: [[0, 10], [0, 10]] },
  2, 2), 5);
check('no field at all', sampleWorldHeight(null, 0, 0), 0);
check('undefined', sampleWorldHeight(undefined, 12, 34), 0);

function checkBool(label, actual, expected) {
  const ok = actual === expected;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}

console.log('[4] the combined height source — world field + scene relief');
// The world's limits, the defaults of `game.max_step_height_m` / `max_slope_deg`.
const STEP = 0.4;
const SLOPE = 40;
const hereH = groundLift(sampleWorldHeight(FIELD, -2, 0), []);
const thereH = groundLift(sampleWorldHeight(FIELD, -1, 0), []);
check('the flank at (-2, 0)', hereH, 2.5);
check('the flank at (-1, 0)', thereH, 3.75);
check('the rise over one metre', thereH - hereH, 1.25);
checkBool('atan(1.25/1) = 51.34 deg > 40 -> the step is refused',
  slopeBlocks(thereH - hereH, 1, STEP, SLOPE), true);
checkBool('RED COUNTER-PROBE: without the world term the mirror sees nothing',
  slopeBlocks(groundLift(0, []) - groundLift(0, []), 1, STEP, SLOPE), false);

// Two enclosing footprints as AREAS in m² (contract v6 Nr. 6): a square of
// edge 80 is 6400 m², a hut of edge 20 is 400 m². The smallest area is the
// most specific answer — the same order the old smallest-width rule gave.
const PATCHES = [{ area: 6400, lift: 0.2 }, { area: 400, lift: 1 }];
check('the innermost scene relief wins',
  groundLift(sampleWorldHeight(FIELD, 2, 2), PATCHES), 2.25);
check('...and the largest alone would have said',
  groundLift(sampleWorldHeight(FIELD, 2, 2), [PATCHES[0]]), 1.45);
check('no scene relief: the world alone',
  groundLift(sampleWorldHeight(FIELD, 2, 2), []), 1.25);

// The levelled plateau under a footprint: the server pins these points, so
// both ends of any step inside it read the same height.
const PLATEAU = {
  origin_x: -4, origin_z: -4, step_m: 4, rows: 3, cols: 3,
  heights: [[5, 5, 5], [5, 5, 5], [5, 5, 5]],
};
check('the plateau at its centre', sampleWorldHeight(PLATEAU, 0, 0), 5);
check('...and a metre away', sampleWorldHeight(PLATEAU, 1, 1), 5);
checkBool('a step on the plateau is never refused',
  slopeBlocks(sampleWorldHeight(PLATEAU, 1, 1) - sampleWorldHeight(PLATEAU, 0, 0),
    0.15, STEP, SLOPE), false);

console.log('\n[5] standY — where the figure stands inside a footprint');
// The two numbers of case (15) come off the very field above: the tile centre
// height at (2, 2) and the world ground at (2, 0).
const tileY = sampleWorldHeight(FIELD, 2, 2);
const worldY = sampleWorldHeight(FIELD, 2, 0);
check('the tile centre height', tileY, 1.25);
check('the world ground further in', worldY, 2.5);
check('the hill runs through the plate -> the hill wins',
  standY(tileY, worldY), 2.5);
check('RED COUNTER-PROBE: min instead of max is the finding itself',
  Math.min(tileY, worldY), 1.25);
check('a bridge over the landscape keeps its own height',
  standY(3, worldY), 3);
check('a levelled footprint is a no-op (both sources agree)',
  standY(5, 5), 5);
check('a sunken lake bed is undercut — the named price',
  standY(-0.8, 0), 0);
check('NaN tile answer: the world alone', standY(NaN, 2.5), 2.5);
check('NaN world answer (no field yet): the tile alone', standY(1.25, NaN), 1.25);
check('both gone: the tile floor, never NaN', standY(NaN, NaN), 0);
check('Infinity is not a height either', standY(1.25, Infinity), 1.25);
check('negative heights compare like any other', standY(-1, -4), -1);

console.log('\n[6] plateLift — the plate is drawn where the figure walks');
const TILE_Y = 2;
check('uphill: the plate rises with the world', plateLift(3.2, TILE_Y), 1.2, 1e-9);
check('...and the figure stands on the same surface',
  standY(TILE_Y, 3.2) - TILE_Y, 1.2, 1e-9);
check('downhill: the plate stays the tile floor', plateLift(0.5, TILE_Y), 0);
check('...and so does the figure', standY(TILE_Y, 0.5), TILE_Y);
check('RED COUNTER-PROBE: unclamped, the plate would sink away',
  0.5 - TILE_Y, -1.5, 1e-9);
check('level ground / levelled footprint: no lift', plateLift(TILE_Y, TILE_Y), 0);
check('no field yet: no lift', plateLift(NaN, TILE_Y), 0);

console.log('[7] the flatness probe reads the drape grid, not nine points');
// One peak on (2, 2) of a 2 m lattice — see the header for the derivation.
const PEAK22 = {
  origin_x: -4, origin_z: -4, step_m: 2, rows: 5, cols: 5,
  heights: [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0],
            [0, 0, 0, 5, 0], [0, 0, 0, 0, 0]],
};
check('the peak is where the derivation puts it',
  sampleWorldHeight(PEAK22, 2, 2), 5);
const maxLift = (points) => Math.max(...points.map(([x, z]) =>
  plateLift(sampleWorldHeight(PEAK22, x, z), 0)));
const axis3 = [-4, 0, 4];
const grid = [-4, -2, 0, 2, 4];
const cross = (vals) => vals.flatMap((x) => vals.map((z) => [x, z]));
check('the 3x3 probe sees nothing — the finding', maxLift(cross(axis3)), 0);
check('the drape grid (2 m) finds the hill', maxLift(cross(grid)), 5);

function checkText(label, actual, expected) {
  if (actual === expected) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}

console.log('\n[8] the tiled field — fine tile > overview > 0');
const TILE_M = 256;
// A SYNTHETIC tile grid of this file's own, not the server's contract: the
// sampler takes every step out of the payload it is handed, so the numbers
// here only have to be consistent with each other. (The server ships 2 m /
// 129 points since 2026-08-14; nothing below depends on that.)
const TILE_STEP = 4;
const TILE_N = 65;

// The overview: the plane ov(x, z) = x/256 + 3·z/256 on a coarsened 256 m
// lattice — heights[j][i] = i + 3j at x, z in {0, 256, 512}.
const OVERVIEW = {
  origin_x: 0, origin_z: 0, step_m: 256, rows: 3, cols: 3,
  heights: [[0, 1, 2], [3, 4, 5], [6, 7, 8]],
};

/** One tile of the fine ramp fine(x, z) = x/128 — the header's formula written
 *  out over the 65 x 65 window of tile (tx, tz), nothing recorded. */
function rampTile(tx, tz) {
  const originX = tx * TILE_M;
  const originZ = tz * TILE_M;
  const heights = [];
  for (let j = 0; j < TILE_N; j += 1) {
    const row = [];
    for (let i = 0; i < TILE_N; i += 1) row.push((originX + i * TILE_STEP) / 128);
    heights.push(row);
  }
  return {
    origin_x: originX, origin_z: originZ, step_m: TILE_STEP,
    rows: TILE_N, cols: TILE_N, heights,
  };
}
const TILE_00 = rampTile(0, 0);
const TILE_10 = rampTile(1, 0);
const COMPOSITE = {
  tileM: TILE_M,
  overview: OVERVIEW,
  tiles: new Map([['0,0', TILE_00], ['1,0', TILE_10]]),
};

check('the generated tile carries the ramp at its west edge',
  TILE_00.heights[0][0], 0);
check('...and at its east edge, 64 steps of 4 m later',
  TILE_00.heights[0][64], 2);
check('the eastern tile starts where the western one ended',
  TILE_10.heights[0][0], 2);

checkText('the key of the origin', tileKeyAt(TILE_M, 0, 0), '0,0');
checkText('a point just short of the seam', tileKeyAt(TILE_M, 255.9, 10), '0,0');
checkText('the seam belongs to the tile east of it',
  tileKeyAt(TILE_M, 256, 0), '1,0');
checkText('negative tiles are ordinary tiles',
  tileKeyAt(TILE_M, -1, -300), '-1,-2');

console.log('[8a] the precedence table');
check('a point in a loaded tile reads the fine ramp',
  heightAt(COMPOSITE, 128, 8), 1);
check('...where the overview would have said something else',
  sampleWorldHeight(OVERVIEW, 128, 8), 0.59375);
check('the eastern tile answers for its own square',
  heightAt(COMPOSITE, 384, 8), 3);
check('...against an overview reading of', sampleWorldHeight(OVERVIEW, 384, 8),
  1.59375);
check('an indexed but unloaded tile falls to the overview',
  heightAt(COMPOSITE, 100, 300), 3.90625);
check('no overview under an unloaded tile: the flat world',
  heightAt(
    { tileM: TILE_M, overview: null, tiles: new Map([['0,0', TILE_00]]) },
    100, 300), 0);
check('an empty composite is flat', heightAt(
  { tileM: TILE_M, overview: null, tiles: new Map() }, 0, 0), 0);
check('no composite at all is flat', heightAt(null, 128, 8), 0);

console.log('[8b] the two rasters are never mixed for one point');
const SHORT_TILE = {
  origin_x: 0, origin_z: 0, step_m: 4, rows: 3, cols: 3,
  heights: [[0, 1, 2], [0, 1, 2], [0, 1, 2]],
};
check('a loaded tile answers alone, even where it has no support point',
  heightAt(
    { tileM: TILE_M, overview: OVERVIEW, tiles: new Map([['0,0', SHORT_TILE]]) },
    128, 8), 2);
check('...and that is NOT the overview it refused to mix in',
  sampleWorldHeight(OVERVIEW, 128, 8), 0.59375);

console.log('[8c] the seam is continuous, because both sides carry the point');
check('the western tile carries the seam column',
  sampleWorldHeight(TILE_00, 256, 12), 2);
check('the eastern tile carries the very same point',
  sampleWorldHeight(TILE_10, 256, 12), 2);
const westOfSeam = heightAt(COMPOSITE, 255.999, 12);
const onSeam = heightAt(COMPOSITE, 256, 12);
check('a millimetre west of the seam', westOfSeam, 1.9999921875);
check('on the seam itself', onSeam, 2);
check('the walk across it is the ramp over that millimetre',
  onSeam - westOfSeam, 7.8125e-6);

const CORRUPT_00 = {
  ...TILE_00,
  heights: TILE_00.heights.map((row) => {
    const copy = row.slice();
    copy[64] = 9;
    return copy;
  }),
};
const CORRUPT = {
  tileM: TILE_M,
  overview: OVERVIEW,
  tiles: new Map([['0,0', CORRUPT_00], ['1,0', TILE_10]]),
};
check('RED COUNTER-PROBE: a corrupted border column breaks the shared point',
  sampleWorldHeight(CORRUPT_00, 256, 12) - sampleWorldHeight(TILE_10, 256, 12), 7);
check('...and the composite drops seven metres across the seam',
  heightAt(CORRUPT, 255.999, 12)
    - heightAt(CORRUPT, 256, 12), 6.9982421875);

console.log('[8e] the drawn ground is GONE — the counter-probes of E2');
// A flat overview: every number below therefore comes from the tile, and any
// answer that is not the tile's is the overview leaking in.
const OV_FLAT = {
  origin_x: 0, origin_z: 0, step_m: 256, rows: 3, cols: 3,
  heights: [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
};
/** A tile of zeroes with ONE support point lifted — the twist of the cell that
 *  corner belongs to. `i`/`j` are the support point's indices, so the point
 *  sits at (step·i, step·j) metres. */
function spikeTile(i0, j0, h, step = TILE_STEP, n = TILE_N) {
  const heights = [];
  for (let j = 0; j < n; j += 1) {
    const row = [];
    for (let i = 0; i < n; i += 1) row.push(i === i0 && j === j0 ? h : 0);
    heights.push(row);
  }
  return { origin_x: 0, origin_z: 0, step_m: step, rows: n, cols: n, heights };
}

/** THE DEAD READING, written out here and nowhere else: the two planes a cell
 *  of `cellM` used to be split into. Nothing in the package answers this any
 *  more, which is the point of the section. */
function drawnTriangle(c, x, z, cellM) {
  const i = Math.floor(x / cellM);
  const j = Math.floor(z / cellM);
  const x0 = i * cellM;
  const z0 = j * cellM;
  const tx = (x - x0) / cellM;
  const tz = (z - z0) / cellM;
  const h00 = heightAt(c, x0, z0);
  const h10 = heightAt(c, x0 + cellM, z0);
  const h01 = heightAt(c, x0, z0 + cellM);
  const h11 = heightAt(c, x0 + cellM, z0 + cellM);
  return tz <= tx
    ? h00 + tx * (h10 - h00) + tz * (h11 - h10)
    : h00 + tz * (h01 - h00) + tx * (h11 - h01);
}

// (33) 8 m on the support point (136, 136) — a corner of the 4 m AND of the
// 8 m grid, which is what made the two plates disagree between the corners.
const TWIST = {
  tileM: TILE_M, overview: OV_FLAT, tiles: new Map([['0,0', spikeTile(34, 34, 8)]]),
};
check('the lifted support point sits at (136, 136)',
  heightAt(TWIST, 136, 136), 8);
check('(34) inside the cell the ONE sampler answers the bilinear reading',
  heightAt(TWIST, 134, 134), 2);
check('...the 4 m triangle would have said', drawnTriangle(TWIST, 134, 134, 4), 4);
check('...and the 64 m cells of the live world, here at 8 m, more still',
  drawnTriangle(TWIST, 134, 134, 8), 6);
check('(35) EVERY cell size answers the same number now: 4 m',
  heightAt(TWIST, 134, 134) - drawnTriangle(TWIST, 134, 134, 4), -2);
check('...8 m — the same field, a different plate, and the field wins',
  heightAt(TWIST, 134, 134) - drawnTriangle(TWIST, 134, 134, 8), -4);
checkText('and no exported sampler answers a plate reading',
  ['sampleCompositeGroundHeight', 'sampleGroundHeight'].filter((n) => n in mod).join(','),
  '');

// (36) THE OTHER DIRECTION, and this is the case the plate could not draw at
// all: a spike BETWEEN the corners of the coarse grid. The field has it, the
// plate had four zero corners — a hill nobody drew, and a figure that walked
// through it. Now there is one answer and it is the hill.
const BETWEEN = {
  tileM: TILE_M, overview: OV_FLAT, tiles: new Map([['0,0', spikeTile(33, 33, 5)]]),
};
check('(36) the spike sits at (132, 132), between the 8 m corners',
  heightAt(BETWEEN, 132, 132), 5);
check('...the 8 m plate drew 0 there', drawnTriangle(BETWEEN, 132, 132, 8), 0);
check('...the sampler answers the hill, whatever anyone draws',
  heightAt(BETWEEN, 132, 132), 5);

// ============================================================================
console.log('\n[9] the SERVER formula, on both step sizes');
// (37) The very peak of section [1], rastered at 2 m and at 4 m over the same
// 16 x 16 m window: h(x, z) = 5 · max(0, 1 − max(|x|, |z|) / 8), a square
// pyramid whose apex is the world origin and whose foot is the 8 m ring.
function pyramidField(step) {
  const n = 16 / step + 1;
  const heights = [];
  for (let j = 0; j < n; j += 1) {
    const row = [];
    for (let i = 0; i < n; i += 1) {
      const x = -8 + i * step;
      const z = -8 + j * step;
      row.push(5 * Math.max(0, 1 - Math.max(Math.abs(x), Math.abs(z)) / 8));
    }
    heights.push(row);
  }
  return { origin_x: -8, origin_z: -8, step_m: step, rows: n, cols: n, heights };
}
const P2 = pyramidField(2);
const P4 = pyramidField(4);
check('the 2 m raster is 9 x 9 support points', P2.cols * P2.rows, 81);
check('the 4 m raster is 5 x 5', P4.cols * P4.rows, 25);
// SUPPORT POINTS: both rasters carry the function exactly where they have a
// point, and the 4 m lattice is a SUBSET of the 2 m one (§ A16.3 congruence).
check('(38) the apex, 2 m', sampleWorldHeight(P2, 0, 0), 5);
check('...4 m', sampleWorldHeight(P4, 0, 0), 5);
check('the 4 m support point (4, 0): 5·(1 − 4/8)', sampleWorldHeight(P4, 4, 0), 2.5);
check('...and the 2 m raster has that point too', sampleWorldHeight(P2, 4, 0), 2.5);
check('the foot ring (8, 8)', sampleWorldHeight(P2, 8, 8), 0);
// BETWEEN the points the two rasters part company, and the arithmetic says by
// how much — this is the bilinear formula, hand-derived, on each step.
// (39) At (1, 0):
//   2 m — fx = (1+8)/2 = 4.5 -> i = 4, tx = 0.5; fz = (0+8)/2 = 4 -> j = 4,
//         tz = 0, so the cell is [0, 2] x [0, 2] and only its north edge
//         counts: h(0,0) = 5, h(2,0) = 3.75 -> 5·0.5 + 3.75·0.5   = 4.375
//   4 m — fx = 9/4 = 2.25 -> i = 2, tx = 0.25; fz = 2 -> j = 2, tz = 0:
//         h(0,0) = 5, h(4,0) = 2.5 -> 5·0.75 + 2.5·0.25           = 4.375
//   The two agree here because this line of the pyramid is linear and both
//   rasters carry its ends.
check('(39) (1, 0) at 2 m', sampleWorldHeight(P2, 1, 0), 4.375);
check('...and at 4 m — the same, this line of the pyramid being linear',
  sampleWorldHeight(P4, 1, 0), 4.375);
// (40) At (1, 1) the twist bites and the two rasters differ:
//   2 m — cell [0, 2]^2, corners h(0,0) = 5, h(2,0) = 3.75, h(0,2) = 3.75,
//         h(2,2) = 3.75; tx = tz = 0.5
//         north = 4.375, south = 3.75
//         -> 4.375·0.5 + 3.75·0.5                                 = 4.0625
//   4 m — cell [0, 4]^2, corners 5, 2.5, 2.5, 2.5; tx = tz = 0.25
//         north = 5·0.75 + 2.5·0.25 = 4.375, south = 2.5
//         -> 4.375·0.75 + 2.5·0.25                                = 3.90625
check('(40) (1, 1) at 2 m', sampleWorldHeight(P2, 1, 1), 4.0625);
check('...at 4 m', sampleWorldHeight(P4, 1, 1), 3.90625);
check('...the coarser raster is lower by', sampleWorldHeight(P2, 1, 1)
  - sampleWorldHeight(P4, 1, 1), 0.15625);
// (41) THE LADDER PICKS THE FINE ONE, and both rasters cover the SAME window
// here, so the only thing that decides is the precedence. Tile "0,0" of a 16 m
// tile world is the 2 m pyramid; everything outside it falls to the 4 m
// overview.
//   (1, 1) lies in tile "0,0" -> the 2 m reading, 4.0625 (case 40).
//   (-1, -1) lies in tile "-1,-1", which is NOT loaded -> the overview:
//       cell [-4, 0]^2, corners h(-4,-4) = h(0,-4) = h(-4,0) = 2.5,
//       h(0,0) = 5; tx = tz = 0.75
//       north = 2.5, south = 2.5·0.25 + 5·0.75 = 4.375
//       -> 2.5·0.25 + 4.375·0.75 = 0.625 + 3.28125 = 3.90625
const FINE = { tileM: 16, overview: P4, tiles: new Map([['0,0', P2]]) };
check('(41) inside the loaded tile the FINE raster answers',
  heightAt(FINE, 1, 1), 4.0625);
check('...while a point in an unloaded tile takes the overview',
  heightAt(FINE, -1, -1), 3.90625);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
