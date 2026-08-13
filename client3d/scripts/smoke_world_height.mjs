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
 *      With two enclosing locations — a square of width 80 lifting 0.2 m and
 *      a hut of width 20 lifting 1.0 m — the answer is 1.25 + 1.0 = 2.25:
 *      the narrower footprint is the more specific one (finding F3). With no
 *      patch at all it is the world alone, 1.25.
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

const { sampleWorldHeight } = await loadModule(SRC, 'worldHeight');
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

const PATCHES = [{ width: 80, lift: 0.2 }, { width: 20, lift: 1 }];
check('the innermost scene relief wins',
  groundLift(sampleWorldHeight(FIELD, 2, 2), PATCHES), 2.25);
check('...and the widest alone would have said',
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

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
