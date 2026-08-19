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
 * [8] THE TILED FIELD — `sampleCompositeHeight` and the composite rectangles
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
 * [8e] THE DRAWN GROUND OF THE COMPOSITE — `sampleCompositeGroundHeight`
 * ============================================================================
 * Task 3 review, finding 1. A renderer does not draw the bilinear field, it
 * draws two triangles per cell of `cellM` (`gridStepFor`, which DOUBLES the
 * field's step until the plate fits its budget). Over such a cell the drawn
 * surface stands up to a quarter of the cell's twist above the field — so a
 * veil hung on the fine 4 m lattice alone would hang INSIDE the hill the
 * player sees, and a figure placed at the bilinear height would float or sink.
 *
 * THE FIELD FOR THIS SECTION: a flat 3 x 3 overview at step 256 (so the drawn
 * lattice is anchored at the origin and the overview contributes nothing), and
 * one loaded tile (0,0) of 65 x 65 zeroes with a single support point lifted —
 * ONE corner of a cell, which is what a twist is.
 *
 * (33) THE TWIST TILE has its 8 m on the support point i = j = 34, i.e. at
 *      (136, 136); everything else in the tile is 0. On a CELL CORNER the drawn
 *      ground IS the composite reading — both triangulations meet the field
 *      there: (136, 136) -> 8 and (128, 128) -> 0, at any cell size.
 * (34) INSIDE A 4 m CELL, at (134, 134): the cell is [132, 136]^2 with corners
 *      h00 = h10 = h01 = 0 and h11 = 8, tx = tz = 0.5. tz <= tx, so the drawn
 *      half is h00 + tx·(h10 − h00) + tz·(h11 − h10) = 0 + 0 + 0.5·8 = 4, while
 *      the BILINEAR reading of the same point is 0.25 · 8 = 2. The gap is 2 m —
 *      a quarter of the cell's twist |0 + 8 − 0 − 0| = 8, exactly as the header
 *      of `sampleGroundHeight` says.
 * (35) THE SAME POINT ON AN 8 m PLATE, (134, 134) with cellM = 8: the cell is
 *      [128, 136]^2, whose corners are (128,128) = (136,128) = (128,136) = 0 and
 *      (136,136) = 8; tx = tz = 6/8 = 0.75, tz <= tx -> 0 + 0.75·0 + 0.75·8 = 6.
 *      SO THE COARSER PLATE STANDS HIGHER STILL: 6 against the 4 of the 4 m
 *      cells and the 2 of the field. That is the finding in one number.
 * (36) AND IT CUTS BOTH WAYS: what the plate does NOT have is not drawn. A
 *      tile with its 5 m on the support point i = j = 33, i.e. at (132, 132),
 *      sits BETWEEN the corners of an 8 m grid. The field reads 5 there and the
 *      4 m plate has that point as a cell CORNER, so it reads 5 as well — but
 *      the 8 m cell [128, 136]^2 has four zero corners, and the ground drawn at
 *      (132, 132) is therefore 0. Whoever asks the field instead of the plate
 *      clears a hill nobody drew.
 *
 * WHAT IS NOT HERE ANY MORE: the rectangle helpers `maxCompositeHeightIn` /
 * `compositeHeightRangeIn`. They existed to hang the fog quads of § A12 and to
 * decide which of them was worth tiling; contract v6 Nr. 8 switched the veil
 * off, and they went with it rather than staying as dormant code. Their cases
 * (29)-(32) and (36)-(37) of the earlier revision went with them.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/worldHeight.ts');

/** Transpile one IMPORT-FREE module and import it. Every file loaded this way
 *  says in its own header that it has no runtime import; should someone add
 *  one, this fails loudly — that is the alarm. */
async function loadModule(path, name) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'worldheight-'));
  try {
    const source = await readFile(path, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, `${name}.mjs`);
    await writeFile(file, out.code, 'utf8');
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

const {
  sampleWorldHeight, tileKeyAt, sampleCompositeHeight,
  sampleCompositeGroundHeight,
} = await loadModule(SRC, 'worldHeight');
const { groundLift, plateLift, standY } = await loadModule(
  join(ROOT, 'client3d/src/game/ground.ts'), 'ground');
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
  sampleCompositeHeight(COMPOSITE, 128, 8), 1);
check('...where the overview would have said something else',
  sampleWorldHeight(OVERVIEW, 128, 8), 0.59375);
check('the eastern tile answers for its own square',
  sampleCompositeHeight(COMPOSITE, 384, 8), 3);
check('...against an overview reading of', sampleWorldHeight(OVERVIEW, 384, 8),
  1.59375);
check('an indexed but unloaded tile falls to the overview',
  sampleCompositeHeight(COMPOSITE, 100, 300), 3.90625);
check('no overview under an unloaded tile: the flat world',
  sampleCompositeHeight(
    { tileM: TILE_M, overview: null, tiles: new Map([['0,0', TILE_00]]) },
    100, 300), 0);
check('an empty composite is flat', sampleCompositeHeight(
  { tileM: TILE_M, overview: null, tiles: new Map() }, 0, 0), 0);
check('no composite at all is flat', sampleCompositeHeight(null, 128, 8), 0);

console.log('[8b] the two rasters are never mixed for one point');
const SHORT_TILE = {
  origin_x: 0, origin_z: 0, step_m: 4, rows: 3, cols: 3,
  heights: [[0, 1, 2], [0, 1, 2], [0, 1, 2]],
};
check('a loaded tile answers alone, even where it has no support point',
  sampleCompositeHeight(
    { tileM: TILE_M, overview: OVERVIEW, tiles: new Map([['0,0', SHORT_TILE]]) },
    128, 8), 2);
check('...and that is NOT the overview it refused to mix in',
  sampleWorldHeight(OVERVIEW, 128, 8), 0.59375);

console.log('[8c] the seam is continuous, because both sides carry the point');
check('the western tile carries the seam column',
  sampleWorldHeight(TILE_00, 256, 12), 2);
check('the eastern tile carries the very same point',
  sampleWorldHeight(TILE_10, 256, 12), 2);
const westOfSeam = sampleCompositeHeight(COMPOSITE, 255.999, 12);
const onSeam = sampleCompositeHeight(COMPOSITE, 256, 12);
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
  sampleCompositeHeight(CORRUPT, 255.999, 12)
    - sampleCompositeHeight(CORRUPT, 256, 12), 6.9982421875);

console.log('[8e] the DRAWN ground of the composite — cells, not the field');
// A flat overview: the drawn lattice is anchored on its origin (0, 0) and the
// overview itself adds nothing, so every number below comes from the tile.
const OV_FLAT = {
  origin_x: 0, origin_z: 0, step_m: 256, rows: 3, cols: 3,
  heights: [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
};
/** A 65 x 65 tile of zeroes with ONE support point lifted — the twist of the
 *  cell that corner belongs to. `i`/`j` are the support point's indices, so the
 *  point sits at (4i, 4j) metres. */
function spikeTile(i0, j0, h) {
  const heights = [];
  for (let j = 0; j < TILE_N; j += 1) {
    const row = [];
    for (let i = 0; i < TILE_N; i += 1) row.push(i === i0 && j === j0 ? h : 0);
    heights.push(row);
  }
  return { origin_x: 0, origin_z: 0, step_m: TILE_STEP, rows: TILE_N, cols: TILE_N, heights };
}
// (33) 8 m on the support point (136, 136) — a corner of the 4 m AND of the
// 8 m grid, which is what makes the two plates disagree between the corners.
const TWIST = {
  tileM: TILE_M, overview: OV_FLAT, tiles: new Map([['0,0', spikeTile(34, 34, 8)]]),
};
check('the lifted support point sits at (136, 136)',
  sampleCompositeHeight(TWIST, 136, 136), 8);
check('a cell corner is the composite reading itself, at 4 m cells',
  sampleCompositeGroundHeight(TWIST, 136, 136, 4), 8);
check('...and at 8 m cells', sampleCompositeGroundHeight(TWIST, 136, 136, 8), 8);
check('the low corner is 0 either way',
  sampleCompositeGroundHeight(TWIST, 128, 128, 8), 0);
check('(34) inside the 4 m cell the drawn ground is the triangle plane',
  sampleCompositeGroundHeight(TWIST, 134, 134, 4), 4);
check('...where the FIELD says half of that',
  sampleCompositeHeight(TWIST, 134, 134), 2);
check('...the gap being a quarter of the cell twist 8',
  sampleCompositeGroundHeight(TWIST, 134, 134, 4) - sampleCompositeHeight(TWIST, 134, 134),
  2);
check('(35) the same point on an 8 m plate stands higher still',
  sampleCompositeGroundHeight(TWIST, 134, 134, 8), 6);
// (36) The other direction: a spike BETWEEN the corners of the 8 m grid is not
// on that plate at all, and nothing may clear a hill nobody drew.
const BETWEEN = {
  tileM: TILE_M, overview: OV_FLAT, tiles: new Map([['0,0', spikeTile(33, 33, 5)]]),
};
check('(36) the spike sits at (132, 132), between the 8 m corners',
  sampleCompositeHeight(BETWEEN, 132, 132), 5);
check('...the 4 m plate has it as a cell CORNER and draws it',
  sampleCompositeGroundHeight(BETWEEN, 132, 132, 4), 5);
check('...while the 8 m cell has four zero corners, so the ground drawn is 0',
  sampleCompositeGroundHeight(BETWEEN, 132, 132, 8), 0);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
