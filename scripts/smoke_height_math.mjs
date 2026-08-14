/**
 * Smoke run for `frontend/src/tabs/map/heightMath.ts` — the authoring
 * arithmetic of the world relief, as the map editor states it.
 *
 * Usage:  node scripts/smoke_height_math.mjs
 *         (transforms the module with esbuild — a Vite dependency, already
 *          installed; no bundler, no jsdom, no server)
 *
 * Every number below is derived BY HAND from the rules, never recorded from
 * the current output.
 *
 * ---------------------------------------------------------------------------
 * [1] THE STEEPNESS WARNING (§ A15 Nr. 8, `app/core/relief.slope_blocks`)
 * ---------------------------------------------------------------------------
 * A height area's ramp climbs its full height over exactly `falloff_m` metres,
 * so its gradient is constant and both server limits collapse into one number:
 *
 *     gradient = |height_m| / falloff_m
 *     walkable while gradient <= min(tan(max_slope_deg), max_step_m / 1 m)
 *
 * At the world defaults (40°, 0.4 m):
 *     tan 40°   = 0.8390996…      the SLOPE limit
 *     0.4 / 1 m = 0.4             the STEP limit — the binding one, and
 *                                 leaving it out was the hole of the review
 *     maxGradient = 0.4
 *     minFalloffFor(5 m)  = 5 / 0.4  = 12.5 m
 *     minFalloffFor(−5 m) = the same: a hollow is as steep as a hill
 *     tooSteep(5 m over 8 m)    -> true   (12.5 > 8: the editor called this
 *                                 walkable before the step limit was added)
 *     tooSteep(5 m over 12.5 m) -> false  (exactly at the limit is walkable)
 * With the slope limit alone binding (60°, 10 m): tan 60° = 1.7320508…,
 * step 10/1 = 10, so maxGradient = 1.7320508…, and
 *     minFalloffFor(5 m) = 5 / 1.7320508… = 2.886751… -> 2.89 (2 decimals)
 * Nothing usable to judge by (0°, 0 m) means maxGradient 0, and then NOTHING
 * is warned about: `minFalloffFor` 0 and `tooSteep` false — a warning without
 * a limit would be a guess.
 *
 * ---------------------------------------------------------------------------
 * [2] THE GRID-STEP NOTICE (finding 14, 2026-08-13)
 * ---------------------------------------------------------------------------
 * `step_m` is nothing anybody sets: the server doubles it until the grid over
 * the world's whole painted extent fits inside its point budget
 * (`app/core/heightfield._step_for`). The live case behind the finding is a
 * 16 160 × 5 876 m union box, which forces 4 m -> 32 m (hand-derived in
 * `scripts/smoke_heightfield.py` section [7b]).
 *
 * BOTH NUMBERS COME FROM THE SERVER — `GET /world/height-areas` carries
 * `step_m` + `default_step_m`, the save answers carry `step_m`. This module
 * does NOT redo the doubling; it does the one piece of arithmetic the sentence
 * needs, and that is Nyquist:
 *
 *     nothing narrower than 2 × step survives the raster
 *
 * (the same limit that clamps `relief_wave_m` at 2 × the default step).
 *     reliefStepNotice(32, 4) -> {stepM: 32, lostUnderM: 64}   the live case
 *     reliefStepNotice( 8, 4) -> {stepM:  8, lostUnderM: 16}   one doubling
 *     reliefStepNotice( 4, 4) -> null   the finest grid says nothing
 *     reliefStepNotice( 2, 4) -> null   finer than the finest cannot happen,
 *                                       and would still be nothing to warn of
 *     reliefStepNotice(0 / −1 / NaN, 4) -> null    no answer yet, no sentence
 *     reliefStepNotice(32, 0 / NaN)     -> null    without "the finest" there
 *                                       is no "coarser than normal"
 *
 * ---------------------------------------------------------------------------
 * [3] THE MICRO-RELIEF WARNING of the terrain-type dialog (§ A16.2)
 * ---------------------------------------------------------------------------
 * The relief noise is bilinear between grid corners, so the steepest flank two
 * NEIGHBOURING support points can build is the full swing of the amplitude
 * over one tile step — `atan(2·amp / tile_step_m)`. It outgrows the walk gate
 * from
 *
 *     amp > tile_step_m · tan(max_slope_deg) / 2
 *
 * on, and THAT is what the field warns at (the clamp stays 2.0 m, user
 * decision 2026-08-14). It is the SLOPE limit alone: `max_step_height_m`
 * judges reports below one metre of travel, a different question.
 *   tan 40° = 0.8390996…
 *     reliefWarnAmpM(40, 2) = 2 · 0.8390996… / 2 = 0.8390996… -> 0.84
 *     reliefWarnAmpM(40, 4) = 4 · 0.8390996… / 2 = 1.6781992… -> 1.68
 *                             (the 4 m tile step before 2026-08-14)
 *   tan 60° = 1.7320508…
 *     reliefWarnAmpM(60, 2) = 2 · 1.7320508… / 2 = 1.7320508… -> 1.73
 * Cross-check against the rule it comes from: the worst-case flank AT the
 * threshold is the limit itself, atan(2 · 0.84 / 2) = 40.03° — 40° up to the
 * two decimals the number is rounded to.
 * Nothing to say is `null`: no tile step answered yet (0), and an angle that
 * judges nothing (0°, 90°, NaN) — a threshold without a gate would be a guess.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = join(fileURLToPath(new URL('..', import.meta.url)),
  'frontend/src/tabs/map/heightMath.ts');

/** The module, transformed and imported — it has no imports of its own, so a
 *  single-file transform is enough (the `smoke_walk_math.mjs` recipe). */
async function loadHeightMath() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'heightmath-smoke-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'heightMath.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = compare(actual, expected, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}
function compare(a, b, eps) {
  if (a === null || b === null) return a === b;
  if (typeof b === 'number') return typeof a === 'number' && Math.abs(a - b) <= eps;
  if (typeof b === 'object') {
    const keys = Object.keys(b);
    if (typeof a !== 'object' || a === null) return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

const { maxGradient, minFalloffFor, tooSteep, reliefStepNotice,
  reliefWarnAmpM, STEP_DISTANCE_M } = await loadHeightMath();

console.log('[1] the steepness warning');
check('a step counts as a step below one metre of travel', STEP_DISTANCE_M, 1);
check('at the defaults the STEP limit binds, not the slope',
  maxGradient(40, 0.4), 0.4);
check('...and the slope one where the step is generous',
  maxGradient(60, 10), Math.tan(Math.PI / 3));
check('nothing usable to judge by is no limit at all', maxGradient(0, 0), 0);
check('a 5 m rise needs 12.5 m of ramp', minFalloffFor(5, 40, 0.4), 12.5);
check('...a hollow of the same depth just as much',
  minFalloffFor(-5, 40, 0.4), 12.5);
check('...and 2.89 m where only the slope binds',
  minFalloffFor(5, 60, 10), 2.89);
check('flat ground needs no ramp', minFalloffFor(0, 40, 0.4), 0);
check('without limits nothing can be demanded', minFalloffFor(5, 0, 0), 0);
check('THE REVIEW CASE: 5 m over 8 m is too steep',
  tooSteep(5, 8, 40, 0.4), true);
check('...exactly at the limit it is walkable',
  tooSteep(5, 12.5, 40, 0.4), false);
check('...and past it, comfortably so', tooSteep(5, 20, 40, 0.4), false);
check('a wall at the edge of a real height is too steep',
  tooSteep(5, 0, 40, 0.4), true);
check('flat ground is never too steep', tooSteep(0, 0, 40, 0.4), false);
check('without limits nothing is warned about', tooSteep(5, 0, 0, 0), false);
// RED COUNTER-PROBE, executed: the rule WITHOUT the step limit — the state of
// the hole the review found. It calls the 5 m over 8 m ramp walkable, which is
// exactly the figure snapping back on a ramp the editor blessed.
const slopeOnly = (h, f, deg) => !(f >= Math.abs(h) / Math.tan(deg * Math.PI / 180));
check('RED: judged by the slope alone, 5 m over 8 m passes',
  slopeOnly(5, 8, 40), false);
check('...while the rule in force refuses it', tooSteep(5, 8, 40, 0.4), true);

console.log('[2] the grid-step notice');
check('THE LIVE CASE: a 32 m step eats everything under 64 m',
  reliefStepNotice(32, 4), { stepM: 32, lostUnderM: 64 });
check('one doubling is already worth saying',
  reliefStepNotice(8, 4), { stepM: 8, lostUnderM: 16 });
check('the finest grid says nothing', reliefStepNotice(4, 4), null);
check('...and neither does a finer one', reliefStepNotice(2, 4), null);
check('no answer yet is no sentence', reliefStepNotice(0, 4), null);
check('...nor is a negative step', reliefStepNotice(-1, 4), null);
check('...nor a NaN one', reliefStepNotice(NaN, 4), null);
check('without "the finest" there is no "coarser than normal"',
  reliefStepNotice(32, 0), null);
check('...and a NaN one is just as silent', reliefStepNotice(32, NaN), null);

console.log('[3] the micro-relief warning');
check('THE CASE IN FORCE: 40° over the 2 m tile step warns from 0.84 m',
  reliefWarnAmpM(40, 2), 0.84);
check('...over the old 4 m step it was 1.68 m', reliefWarnAmpM(40, 4), 1.68);
check('...and a 60° gate carries 1.73 m of hills',
  reliefWarnAmpM(60, 2), 1.73);
// The threshold IS the rule: at that amplitude the worst-case flank of the
// noise is the gate angle itself, up to the two decimals it is rounded to.
check('the worst-case flank at the threshold is the gate angle',
  Math.atan(2 * reliefWarnAmpM(40, 2) / 2) * 180 / Math.PI, 40, 0.05);
check('no tile step answered yet, no threshold', reliefWarnAmpM(40, 0), null);
check('...nor a NaN one', reliefWarnAmpM(40, NaN), null);
check('an angle that gates nothing is no threshold', reliefWarnAmpM(0, 2), null);
check('...and neither is a vertical one', reliefWarnAmpM(90, 2), null);
check('...nor a NaN one', reliefWarnAmpM(NaN, 2), null);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
