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
 *
 * ---------------------------------------------------------------------------
 * [4] WHERE THE RAMP ENDS — `rampCrestRing` (§ A16)
 * ---------------------------------------------------------------------------
 * THE SERVER RAMPS INWARD. `app/core/heightfield._area_value`, lines 1252–1266
 * (documented on `area_height_at`, lines 294–313):
 *
 *     if not _inside_ring(x, z, ring): return None
 *     if falloff <= 0:                 return height
 *     return height * min(1.0, _ring_edge_distance(x, z, ring) / falloff)
 *
 * — nothing outside the outline, exactly 0 ON it, full `height_m` at
 * `falloff_m` metres inside. So the OUTLINE is the foot line (the relief has
 * blended into the surrounding ground there) and the line the map lacked is
 * the CREST, `falloff_m` INSIDE. Since the rule divides by a plain distance to
 * the outline, the crest is a true buffer — the polygon eroded by a disc:
 *
 *     crest = { p inside : distance(p, outline) = falloff_m }
 *
 * which is why EVERY point of every ring below sits at exactly `falloff_m`
 * from the outline. That single invariant is checked on all of them.
 *
 * [4a] THE SQUARE. (0,0)-(10,10), ramp 3. Each edge moves 3 m in: x=3, x=7,
 * z=3, z=7, and at a CONVEX corner the two inset lines simply meet (a miter —
 * exact, no arc). Crest = (3,3),(7,3),(7,7),(3,7): a 4 × 4 box, its corner
 * 3·√2 = 4.2426 m in from the authored corner along the diagonal. Starting
 * vertex and direction follow the input ring, so the reversed (clockwise)
 * square gives the same box in the other order.
 *   RED, and the reason this is the inward line: the OUTWARD reading of the
 *   same 10 × 10 square would draw a 16 × 16 box — its corner (13,13) is not
 *   even inside the area, and `_area_value` returns None out there. The bake
 *   has no reach outside the outline at all, so an outward line would be a
 *   picture of a ramp nobody baked.
 *   Ramp 4 still leaves a 2 × 2 plateau; ramp 5 leaves exactly one point and
 *   ramp 6 nothing — both `null`, because a line around no plateau is a lie.
 *
 * [4b] THE TRIANGLE (0,0),(12,0),(0,12), ramp 2. Legs inset to x=2 and z=2;
 * the hypotenuse x + z = 12 moves in by 2 to x + z = 12 − 2·√2 = 9.171573.
 * Crest = (2,2),(7.171573,2),(2,7.171573). The triangle's incircle radius is
 * area/s = 72 / ((12 + 12 + 12·√2)/2) = 72 / 20.485281 = 3.514719, so a 4 m
 * ramp swallows it: `null`.
 *
 * [4c] THE REFLEX CORNER — an L, (0,0),(20,0),(20,20),(10,20),(10,10),(0,10),
 * ramp 3. Five convex corners miter as above: (3,3),(17,3),(17,17),(13,17) and
 * (3,7). At the reflex vertex (10,10) the nearest outline point IS the vertex,
 * so the crest runs around it on a circle of radius 3, from (13,10) to (10,7)
 * — a 90° sweep, drawn at 10° per segment (`RAMP_ARC_STEP_DEG`) = 9 segments,
 * 10 points. 5 + 10 = 15 points in all.
 *   THE ERROR BOUND of that arc, the only approximation in the whole ring: the
 *   sagitta of one 10° chord, r·(1 − cos 5°) = 3 · 0.0038053 = 0.011416 m. It
 *   is checked as the distance of a chord's MIDPOINT from the vertex,
 *   3 · cos 5° = 2.988584 — inside the true arc, never outside it, so the line
 *   never claims more plateau than the bake makes.
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
  reliefWarnAmpM, STEP_DISTANCE_M, rampCrestRing, outlineDistance,
  RAMP_ARC_STEP_DEG } = await loadHeightMath();

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

console.log('[4] where the ramp ends');
/** The box a ring occupies: [minX, minZ, maxX, maxZ]. */
function bbox(ring) {
  return [Math.min(...ring.map((p) => p[0])), Math.min(...ring.map((p) => p[1])),
    Math.max(...ring.map((p) => p[0])), Math.max(...ring.map((p) => p[1]))];
}
/** THE INVARIANT of the whole section: the bake's rule is a distance rule, so
 *  every point of a crest ring stands exactly `ramp` metres from the outline —
 *  the first metre at which the ground is at its full height. */
function everyPointAtRamp(ring, poly, ramp, eps = 1e-9) {
  return ring.every((p) => Math.abs(outlineDistance(p[0], p[1], poly) - ramp)
    <= eps);
}
const SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]];
const sq3 = rampCrestRing(SQUARE, 3);
check('the 10 m square with a 3 m ramp keeps a 4 x 4 plateau',
  bbox(sq3), [3, 3, 7, 7], 1e-9);
check('...one miter point per corner, no arcs', sq3.length, 4);
check('...and the corner sits 3·√2 in from the authored one',
  Math.hypot(sq3[0][0] - 0, sq3[0][1] - 0), 3 * Math.SQRT2, 1e-9);
check('...every point of it exactly 3 m from the outline',
  everyPointAtRamp(sq3, SQUARE, 3), true);
// RED counter-probe: the OUTWARD reading of the same area. `_area_value`
// returns None outside the outline, so a 16 x 16 ring would draw a reach the
// bake does not have — the line goes inwards, and this is the number that says
// so out loud.
check('RED: the outward reading would be 16 m across, the bake 4 m',
  bbox(sq3)[2] - bbox(sq3)[0], 4);
check('a 4 m ramp still leaves a 2 x 2 plateau',
  bbox(rampCrestRing(SQUARE, 4)), [4, 4, 6, 6], 1e-9);
check('a 5 m ramp leaves a point, which is no plateau',
  rampCrestRing(SQUARE, 5), null);
check('...and a 6 m ramp eats the area whole', rampCrestRing(SQUARE, 6), null);
check('a wall (ramp 0) has no second line', rampCrestRing(SQUARE, 0), null);
check('...nor has a negative or NaN one', rampCrestRing(SQUARE, -3), null);
check('...nor a NaN one', rampCrestRing(SQUARE, NaN), null);
check('two points are no polygon', rampCrestRing([[0, 0], [10, 0]], 3), null);
// The ring the author drew is used as it comes: a repeated closing vertex is
// dropped, and the reversed winding gives the same plateau the other way round.
check('a closed ring is the same ring',
  bbox(rampCrestRing([...SQUARE, [0, 0]], 3)), [3, 3, 7, 7], 1e-9);
const sqCw = rampCrestRing([[0, 0], [0, 10], [10, 10], [10, 0]], 3);
check('...and so is the same square drawn the other way round',
  bbox(sqCw), [3, 3, 7, 7], 1e-9);
check('...still exactly 3 m in', everyPointAtRamp(sqCw, SQUARE, 3), true);

const TRI = [[0, 0], [12, 0], [0, 12]];
const tri2 = rampCrestRing(TRI, 2);
check('the right triangle keeps a triangle', tri2.length, 3);
check('...its right-angle corner at (2,2)', tri2[0], [2, 2], 1e-9);
check('...the hypotenuse moved in to x + z = 12 − 2·√2',
  tri2[1], [12 - 2 * Math.SQRT2 - 2, 2], 1e-9);
check('...symmetrically on the other leg',
  tri2[2], [2, 12 - 2 * Math.SQRT2 - 2], 1e-9);
check('...every point exactly 2 m from the outline',
  everyPointAtRamp(tri2, TRI, 2), true);
check('a ramp wider than its incircle (3.514719 m) leaves nothing',
  rampCrestRing(TRI, 4), null);
check('...just inside it, something', rampCrestRing(TRI, 3.5) !== null, true);

const ELL = [[0, 0], [20, 0], [20, 20], [10, 20], [10, 10], [0, 10]];
const ell3 = rampCrestRing(ELL, 3);
check('the L: 5 mitered corners + a 10-point arc', ell3.length, 15);
check('...arcs at 10° per segment, so 9 of them for a 90° reflex corner',
  Math.ceil(90 / RAMP_ARC_STEP_DEG), 9);
check('...the arc starts where the inset edges leave off', ell3[4], [13, 10],
  1e-9);
check('...and ends on the other one', ell3[13], [10, 7], 1e-9);
check('...every arc point 3 m around the reflex vertex (10,10)',
  ell3.slice(4, 14).every((p) => Math.abs(Math.hypot(p[0] - 10, p[1] - 10) - 3)
    <= 1e-9), true);
check('...every point of the whole ring exactly 3 m from the outline',
  everyPointAtRamp(ell3, ELL, 3), true);
// THE ERROR BOUND, measured: one chord's midpoint lies r·(1 − cos 5°) inside
// the true arc — 11.4 mm on this 3 m ramp, and inside, never outside.
const mid = [(ell3[4][0] + ell3[5][0]) / 2, (ell3[4][1] + ell3[5][1]) / 2];
check('the arc chord sags 3·(1 − cos 5°) = 0.011416 m inside the true arc',
  3 - Math.hypot(mid[0] - 10, mid[1] - 10), 3 * (1 - Math.cos(Math.PI / 36)),
  1e-9);
check('...which is 11.4 mm', 3 - Math.hypot(mid[0] - 10, mid[1] - 10), 0.0114,
  5e-5);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
