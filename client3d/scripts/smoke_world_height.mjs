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
 * [4] THE HEIGHT SOURCE IS ONE READING — the counter-probe of E5b
 * ============================================================================
 * `main.ts` `reliefLiftAt` used to ask TWO sources and add them: the WORLD
 * field (`sampleWorldHeight`, the bilinear reading — the server's own) plus the
 * scene relief of the INNERMOST enclosing location that had a field, composed
 * by `game/ground.groundLift`. "Ein Boden" E5b deletes the second term with the
 * field it read: a location has no 17 x 17 relief of its own any more (§ A19
 * no. 6, decision 1), local relief is authored through the map's HEIGHT AREAS,
 * and `reliefLiftAt` is one line. The walk verdict is unchanged
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

/** `client3d/src/scene/waterRaster.ts` with `@anima/scene-render` resolved to
 *  `worldHeight.ts` itself — the only thing it takes from the package is
 *  `tileKeyAt`, and pointing at the real barrel would drag `three` in. Same
 *  alarm as `loadModule`: an import of anything else fails loudly here. */
async function loadWaterRaster() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'waterraster-'));
  try {
    const ts = async (src, name, fix = (c) => c) => {
      const code = await readFile(src, 'utf8');
      await writeFile(join(dir, `${name}.mjs`),
        fix(esbuild.transformSync(code, { loader: 'ts', format: 'esm' }).code),
        'utf8');
    };
    await ts(SRC, 'worldHeight');
    await ts(join(ROOT, 'client3d/src/scene/waterRaster.ts'), 'waterRaster',
      (code) => code.replace(/from\s*["']@anima\/scene-render["']/g,
                             "from './worldHeight.mjs'"));
    return await import(`file://${join(dir, 'waterRaster.mjs')}`);
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
const groundMod = await loadModule(
  join(ROOT, 'client3d/src/game/ground.ts'), 'ground', ['polygon']);
const { standY } = groundMod;
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

console.log('[4] the height source is ONE reading — the counter-probe of E5b');
// The world's limits, the defaults of `game.max_step_height_m` / `max_slope_deg`.
const STEP = 0.4;
const SLOPE = 40;
// `groundLift(worldHeight, patches)` IS GONE ("Ein Boden" E5b): it added the
// innermost enclosing LOCATION's own 17 x 17 relief on top of the world field,
// and that field is deleted (§ A19 no. 6, decision 1 — local relief is
// authored through the map's height areas). What used to be
// `groundLift(sampleWorldHeight(...), patches)` is `sampleWorldHeight(...)`,
// full stop, and `main.reliefLiftAt` is one line because of it.
checkBool('`groundLift` no longer exists', groundMod.groundLift === undefined, true);
const hereH = sampleWorldHeight(FIELD, -2, 0);
const thereH = sampleWorldHeight(FIELD, -1, 0);
check('the flank at (-2, 0)', hereH, 2.5);
check('the flank at (-1, 0)', thereH, 3.75);
check('the rise over one metre', thereH - hereH, 1.25);
checkBool('atan(1.25/1) = 51.34 deg > 40 -> the step is refused',
  slopeBlocks(thereH - hereH, 1, STEP, SLOPE), true);
checkBool('RED COUNTER-PROBE: on flat ground the mirror sees nothing',
  slopeBlocks(0, 1, STEP, SLOPE), false);
// WHAT THE SECOND TERM USED TO DO, kept as a number so the deletion is
// readable: two enclosing footprints (a square of edge 80 = 6400 m², a hut of
// edge 20 = 400 m²) would have raised the point at (2, 2) — world height
// 1.25 — to 2.25 through the innermost of them, and to 1.45 through the
// outermost. Both readings are gone; the point is 1.25, the height the SERVER
// judges it by.
check('the point at (2, 2) is the world field and nothing added',
  sampleWorldHeight(FIELD, 2, 2), 1.25);
checkBool('RED: the old innermost-patch answer 2.25 is not reachable',
  sampleWorldHeight(FIELD, 2, 2) === 2.25, false);
checkBool('RED: nor the outermost-patch answer 1.45',
  sampleWorldHeight(FIELD, 2, 2) === 1.45, false);

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

// Sections [6] (plateLift) and [7] (the plate's flatness probe) were deleted
// with the footprint plate itself — see the header. Nothing takes their place:
// their subject no longer exists in the client.

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

// ============================================================================
// [W] THE WATER RASTER — `client3d/src/scene/waterRaster.ts` (K-A E1/E2)
// ============================================================================
// TWIN DISCIPLINE, and this time against a THIRD implementation: the tables
// below are what `app/core/heightfield.HeightModel.water_raster` really writes
// for the two fixtures of `scripts/smoke_height_bake.py` section [12], derived
// here from the same three rules the server derives them from:
//
//   level(p) = water_level_at(profile, p)   of the topmost water covering p
//   covered  = inside the outline, OR within 2 lattice steps (4 m) of it
//   flow(p)  = the axis tangent, blended through the knots, times the factor
//
// THE LAKE (server [12a]/[12b]): the square (20,20)-(60,60) with an authored
// level of 3.0 — one knot, so 3.0 everywhere and no flow at all.
//
// WINDOW A, its NORTH-WEST corner: origin (12,12), step 2, 7 x 7 points, so
// x and z run 12, 14, 16, 18, 20, 22, 24. A point west of the rim is
// `20 − x` from the outline, one north of it `20 − z`, and one north-WEST of
// the corner is `hypot(20−x, 20−z)` from the corner point (20,20):
//
//     (14, 20) -> 6.000  dry        (16, 20) -> 4.000  wet, the band exactly
//     (16, 16) -> 5.657  dry        (18, 18) -> 2.828  wet  (the DIAGONAL)
//     (16, 18) -> 4.472  dry        (18, 16) -> 4.472  dry
//
// so the mask is a staircase and it is the one the server prints:
const LAKE_NW = {
  origin_x: 12, origin_z: 12, step_m: 2, rows: 7, cols: 7,
  level: [
    [null, null, null, null, null, null, null],   // z = 12
    [null, null, null, null, null, null, null],   // z = 14
    [null, null, null, null, 3.0, 3.0, 3.0],      // z = 16
    [null, null, null, 3.0, 3.0, 3.0, 3.0],       // z = 18
    [null, null, 3.0, 3.0, 3.0, 3.0, 3.0],        // z = 20
    [null, null, 3.0, 3.0, 3.0, 3.0, 3.0],        // z = 22
    [null, null, 3.0, 3.0, 3.0, 3.0, 3.0],        // z = 24
  ],
};
// WINDOW B, its EAST rim: origin (56,30), step 2, 7 x 3 points, x = 56 … 68.
// Inside up to 60, then 62 (2 m out) and 64 (4 m out) are the dilation ring,
// and 66/68 are dry. This is the window the masked mix is FOR — see below.
const LAKE_E = {
  origin_x: 56, origin_z: 30, step_m: 2, rows: 3, cols: 7,
  level: [
    [3.0, 3.0, 3.0, 3.0, 3.0, null, null],
    [3.0, 3.0, 3.0, 3.0, 3.0, null, null],
    [3.0, 3.0, 3.0, 3.0, 3.0, null, null],
  ],
};
// THE CLIFF RIVER (server [8l]/[12c]): drawn (0,0) -> (100,0), 6 m wide, over a
// hard 3 m step at x = 41. Its axis is [(0,3), (40,3), (42,0), (100,0)], so the
// WHOLE drop sits between two lattice points and the raster carries it exactly.
// WINDOW: origin (36,-8), step 2, 6 x 5 points, x = 36 … 46, z = −8 … 0. The
// mask is z in [−3, 3], so z = −8 is 5 m out (dry) and −6 is 3 m out (wet).
const CLIFF_W = {
  origin_x: 36, origin_z: -8, step_m: 2, rows: 5, cols: 6,
  level: [
    [null, null, null, null, null, null],       // z = −8
    [3.0, 3.0, 3.0, 0.0, 0.0, 0.0],             // z = −6
    [3.0, 3.0, 3.0, 0.0, 0.0, 0.0],             // z = −4
    [3.0, 3.0, 3.0, 0.0, 0.0, 0.0],             // z = −2
    [3.0, 3.0, 3.0, 0.0, 0.0, 0.0],             // z =  0
  ],
  flow_x: [[0, 0, 0, 0, 0, 0], [1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1, 1],
           [1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 1, 1]],
  flow_z: [[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0],
           [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]],
};

const wr = await loadWaterRaster();
const { emptyWaterRaster, rasterFlowAt, rasterLevelAt, waterBilinear,
        waterTileFrom } = wr;

function rasterOf(tileM, entries) {
  const r = emptyWaterRaster();
  r.tileM = tileM;
  for (const [key, wire] of entries) {
    r.tiles.set(key, waterTileFrom(wire.origin_x, wire.origin_z, wire.step_m,
                                   wire));
  }
  return r;
}
function checkAbove(label, actual, floor) {
  const ok = typeof actual === 'number' && actual > floor;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (> ${floor})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected > ${floor}\n       actual   ${actual}`);
  }
}
function checkBelow(label, actual, ceiling) {
  const ok = typeof actual === 'number' && actual < ceiling;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (< ${ceiling})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected < ${ceiling}\n       actual   ${actual}`);
  }
}
function checkNaN(label, actual) {
  const ok = typeof actual === 'number' && Number.isNaN(actual);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = NaN (dry)`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected NaN\n       actual   ${actual}`);
  }
}

console.log('\n[W1] the lake: the server\'s own table, read back');
// The two windows sit in tile "0,0" of a 256 m world; only one may be filed
// under that key at a time, so each gets its own raster.
const NW = rasterOf(256, [['0,0', LAKE_NW]]);
check('a support point inside the lake is the mirror', rasterLevelAt(NW, 22, 22), 3);
check('…so is the rim point (20, 20) itself', rasterLevelAt(NW, 20, 20), 3);
check('4 m outside the rim the DILATION still answers',
  rasterLevelAt(NW, 16, 20), 3);
check('…and halfway into the ring, between two written points',
  rasterLevelAt(NW, 17, 20), 3);
checkNaN('6 m out there is nothing to read', rasterLevelAt(NW, 14, 20));
checkNaN('…nor 5 m out, where the mix meets one dry corner',
  rasterLevelAt(NW, 15, 20));
checkNaN('…nor diagonally past the corner, 4.472 m away',
  rasterLevelAt(NW, 16, 18));
check('the DIAGONAL point (18, 18) is written — 2.828 m out, under the 4 m band',
  rasterLevelAt(NW, 18, 18), 3);
checkNaN('a point in a tile that has not arrived is dry',
  rasterLevelAt(NW, 900, 900));
checkNaN('…and so is every point of an empty raster',
  rasterLevelAt(emptyWaterRaster(), 22, 22));
checkNaN('…and of none at all', rasterLevelAt(null, 22, 22));
check('a still water has no flow — the wire omits both arrays',
  rasterFlowAt(NW, 22, 22)[0], 0);
check('…in both components', rasterFlowAt(NW, 22, 22)[1], 0);
checkBool('no raster at all is still water too, not a crash',
  rasterFlowAt(null, 22, 22).join() === '0,0', true);
checkBool('…and an empty one',
  rasterFlowAt(emptyWaterRaster(), 22, 22).join() === '0,0', true);

console.log('\n[W2] THE MASKED MIX — a corner with weight 0 is not read');
// (64, 32) is the OUTERMOST written point of the east ring: its own weight is
// 1 and its eastern neighbour (66, 32) is dry with weight 0. Plain bilinear
// would answer NaN there (`NaN · 0 = NaN`), and that is not cosmetic: the near
// pyramid is filled AT the lattice points, so the ring would lose its outer
// texel — 2 steps of dilation would become 1, which is under the sqrt(2) a
// bilinear read of an interior point needs, and a water would show holes.
const EAST = rasterOf(256, [['0,0', LAKE_E]]);
check('the outermost ring point keeps its value', rasterLevelAt(EAST, 64, 32), 3);
check('RED COUNTER-PROBE: the same four corners mixed WITHOUT the mask',
  Number.isNaN(3 * 1 + NaN * 0 + 3 * 0 + NaN * 0) ? 1 : 0, 1);
check('…while the masked mix answers the wet corner',
  waterBilinear(3, NaN, 3, NaN, 0, 0), 3);
check('…and it still answers NaN when a WEIGHTED corner is dry',
  Number.isNaN(waterBilinear(3, NaN, 3, NaN, 0.5, 0)) ? 1 : 0, 1);
checkNaN('…which is what a point past the ring reads', rasterLevelAt(EAST, 65, 32));
check('inside the lake nothing changes', rasterLevelAt(EAST, 59, 32), 3);

console.log('\n[W3] the cliff river: the drop, and the flow');
// The window straddles z = 0, i.e. the seam between tiles "0,-1" and "0,0",
// and the server ships those support points in BOTH of them — a tile carries
// its own borders (§ A16.5). So the same hand table is filed under both keys,
// which is what the two real tiles would agree on there.
const CLIFF_R = rasterOf(256, [['0,-1', CLIFF_W], ['0,0', CLIFF_W]]);
check('upstream of the lip the mirror is the plateau\'s 3.0',
  rasterLevelAt(CLIFF_R, 38, 0), 3);
check('downstream of it, the low ground\'s 0.0', rasterLevelAt(CLIFF_R, 44, 0), 0);
// x = 41 is the middle of the ONE cell the drop sits in: (3 + 0)/2. The server
// says 1.5 there too (`smoke_height_bake.py` [8l]) — the raster reproduces the
// step exactly because the axis knots at 40 and 42 ARE lattice points.
check('…and halfway between them the mirror is halfway down, 1.5',
  rasterLevelAt(CLIFF_R, 41, 0), 1.5);
check('…a quarter of the way, a quarter down', rasterLevelAt(CLIFF_R, 40.5, 0), 2.25);
check('the flow is the unit tangent of a river running east, x',
  rasterFlowAt(CLIFF_R, 41, 0)[0], 1);
check('…and z', rasterFlowAt(CLIFF_R, 41, 0)[1], 0);
check('…and it is a unit vector', Math.hypot(...rasterFlowAt(CLIFF_R, 41, 0)), 1);
checkNaN('5 m off the bank there is no water', rasterLevelAt(CLIFF_R, 41, -8));
check('the rim of the mask reads the mirror, not a fade',
  rasterLevelAt(CLIFF_R, 38, -3), 3);

console.log('\n[W4] the wire shape — the sentinel is converted once, at the edge');
check('a tile without a level array is no water field',
  waterTileFrom(0, 0, 2, { }) === null ? 1 : 0, 1);
check('…nor is a missing one', waterTileFrom(0, 0, 2, null) === null ? 1 : 0, 1);
check('…nor one row (a lattice under 2 x 2 carries no surface)',
  waterTileFrom(0, 0, 2, { level: [[1, 2]] }) === null ? 1 : 0, 1);
check('…nor a field without a step', waterTileFrom(0, 0, 0,
  { level: [[1, 2], [3, 4]] }) === null ? 1 : 0, 1);
const CONV = waterTileFrom(0, 0, 2, { level: [[1, null], [null, 4]] });
check('null becomes NaN', Number.isNaN(CONV.level[0][1]) ? 1 : 0, 1);
check('…and a number stays itself', CONV.level[1][1], 4);
check('a tile without flow arrays holds null, not zeros',
  CONV.flowX === null && CONV.flowZ === null ? 1 : 0, 1);

// ============================================================================
// [W5] THE MIP LIMIT IS A PROPERTY OF THE FIELD, not of a renderer (F1)
// ============================================================================
// The 3D client draws the ground from a pyramid whose coarse levels are the
// base lattice at STRIDE 2^k (decimation, not filtering — § G2), and lifts a
// vertex onto the mirror wherever the water level of the same support point
// stands above the ground there. Everything that costs is therefore decided
// HERE, in the raster: a support point that is not inside the bed cannot lift,
// and a stride that steps over a narrow bed has no support point inside it.
//
// THE FIXTURE is the meander of `docs/schnittstellen-3d.md` § "Offen und NICHT
// gefixt", rebuilt on one 256 m tile at the server's 2 m step: a bed 6 m wide
// (|z − zc| ≤ 3) carved 3 m into a flat ground, a mirror at −0.5 m, the wet
// mask dilated to 11 m so that it never limits anything, and
// zc(x) = 8 + 4·sin(2πx/128) — so the bed stays inside z ∈ [1, 15] everywhere.
// The axis is sampled at (x, zc(x)) for x = 0, 2 … 244: 123 points.
//
// THE COUNT is "does the stride-s lattice hold a lifting support point inside
// the bed at this x" — the same question the pyramid asks, reimplemented here
// out of the raster's own arrays and the stride rule, so that it is a statement
// about the DATA and not about `terrainLod.ts`.
//   s = 2 m: the bed spans 3 lattice rows at every x -> 123/123.
//   s = 4 m: any interval 6 m long contains a multiple of 4 -> 123/123.
//   s = 8 m: the only multiple of 8 the bed can reach is z = 8, and it lies
//            inside only while |zc − 8| ≤ 3, i.e. |4·sin| ≤ 3 -> PARTIAL.
//   s = 16 m: the multiples in reach are 0 and 16, and the bed never leaves
//            [1, 15] -> 0/123.
// A body N metres wide therefore carries the strides up to N, which is where
// the client's per-tile cap comes from — 6 m of river = 4 m of lattice = the
// level-1 cap, and nothing coarser.
console.log('\n[W5] the mip limit of a 6 m river, out of the raster itself');
const MEANDER_ZC = (x) => 8 + 4 * Math.sin((2 * Math.PI * x) / 128);
const MEANDER_STEP = 2;
const MEANDER_N = 129;                       // [0, 256] at 2 m
const MEANDER_ROWS = 17;                     // [0, 32] at 2 m
const MEANDER_W = {
  origin_x: 0,
  origin_z: 0,
  step_m: MEANDER_STEP,
  level: Array.from({ length: MEANDER_ROWS }, (_, j) =>
    Array.from({ length: MEANDER_N }, (_, i) =>
      (Math.abs(j * MEANDER_STEP - MEANDER_ZC(i * MEANDER_STEP)) <= 11
        ? -0.5 : null))),
};
const MEANDER_R = rasterOf(256, [['0,0', MEANDER_W]]);
/** The ground of the same lattice: the bed, 3 m deep and 6 m wide. */
const bedAt = (x, z) => (Math.abs(z - MEANDER_ZC(x)) <= 3 ? -3 : 0);
/** Does the stride-`s` lattice hold a support point that LIFTS, in the bed
 *  under this x? The stride rule is written out here — index i survives to a
 *  lattice of stride s while `i mod (s / step) == 0` — so the check does not
 *  borrow the pyramid's own arithmetic. */
function liftsAt(x, s) {
  const stride = s / MEANDER_STEP;
  const col = Math.round(x / MEANDER_STEP);
  if (col % stride !== 0) return false;       // the axis point's own column is
  for (let j = 0; j < MEANDER_ROWS; j += 1) { // gone from this lattice entirely
    if (j % stride !== 0) continue;
    const z = j * MEANDER_STEP;
    if (Math.abs(z - MEANDER_ZC(x)) > 3) continue;
    if (rasterLevelAt(MEANDER_R, x, z) > bedAt(x, z)) return true;
  }
  return false;
}
/** …asked at every axis point, but only where the point's own column is on the
 *  lattice: between two columns the drawn ground is a mix of the two, and this
 *  section is about the DATA. The columns that survive stride s are every
 *  (s/2)-th of the 123, so the counts below are out of 123, 62, 31 and 16. */
const AXIS = Array.from({ length: 123 }, (_, m) => m * 2);
function liftedCount(s) {
  return AXIS.filter((x) => (x % s === 0) && liftsAt(x, s)).length;
}
function onLattice(s) { return AXIS.filter((x) => x % s === 0).length; }
check('every 2 m column of the axis carries the bed', liftedCount(2), onLattice(2));
check('…123 of them', onLattice(2), 123);
check('every 4 m column does too — a 6 m bed always spans a multiple of 4',
  liftedCount(4), onLattice(4));
check('…62 of them', onLattice(4), 62);
const S8 = liftedCount(8);
const N8 = onLattice(8);
check('…31 columns survive the 8 m lattice', N8, 31);
checkAbove('…and only SOME of them still reach the bed', S8, 0);
checkBelow('…never all: the lens-shaped puddles', S8, N8);
check('…exactly the columns whose axis runs within 3 m of z = 8',
  AXIS.filter((x) => x % 8 === 0 && Math.abs(MEANDER_ZC(x) - 8) <= 3).length, S8);
check('the 16 m lattice reaches the bed nowhere — 0 and 16 are outside [1, 15]',
  liftedCount(16), 0);
check('…though 16 of its columns are still there', onLattice(16), 16);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
