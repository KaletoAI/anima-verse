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
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/worldHeight.ts');

/** The module has no runtime import (see its header), so a transpile is all it
 *  takes. Should someone add one, this fails loudly — that is the alarm. */
async function loadSampler() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'worldheight-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'worldHeight.mjs');
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

const { sampleWorldHeight } = await loadSampler();

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

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
