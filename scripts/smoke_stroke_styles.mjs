/**
 * Smoke run for `decorateStroke` in `frontend/src/tabs/map/mapMath.ts` — the
 * line tool's jagged and wavy styles, the step BEFORE the ribbon is built.
 *
 * Usage:  node scripts/smoke_stroke_styles.mjs
 *         (bundles the module with esbuild — a Vite dependency, already
 *          installed; no jsdom, no server, no world DB. A bundle rather than
 *          the single-file transform `smoke_height_math.mjs` uses, because
 *          mapMath pulls `seededRandom` from @anima/scene-render.)
 *
 * Every number below is derived BY HAND from the rules in `decorateStroke`,
 * never recorded from the current output. `A` is the amplitude, `m_i` the
 * random height of the i-th deflection, which by rule lies in
 * [0.4·A, A] — the ONLY thing about the numbers the checks may assume, since
 * the heights come out of the PRNG.
 *
 * ---------------------------------------------------------------------------
 * [1] WHERE THE DEFLECTIONS SIT
 * ---------------------------------------------------------------------------
 * They sit at arc length spacing/2, 3·spacing/2, … — so a line of length L
 * carries the positions below L, i.e. ~L/spacing of them, and the clicked
 * points all survive in between.
 *   [(0,0),(100,0)], spacing 10: 5, 15, …, 95 -> 10 deflections, 12 points.
 *   The segment direction (1,0) has the side-A normal (0,−1), so x is exactly
 *   the arc position and the whole deflection lands in z:
 *     [(0,0),(5,−m0),(15,m1),(25,−m2),…,(95,m9),(100,0)]
 *   jagged alternates sides from there: sign(z) = −,+,−,+,…
 *   Length 100 at spacing 30: 1.66… -> positions 15, 45, 75 (105 > 100 is
 *   past the end) = 3 deflections, i.e. L/spacing rounded to the nearer whole
 *   number — the ±1 the spacing field promises.
 *   The corner case: [(0,0),(10,0),(10,10)], spacing 10, length 20 -> 5 and
 *   15. The first sits on segment 0 (normal (0,−1)), the second on segment 1
 *   (direction (0,1), normal (1,0)), and the CLICKED corner (10,0) stands
 *   between them:
 *     [(0,0),(5,−m0),(10,0),(10−m1,5),(10,10)]
 *
 * ---------------------------------------------------------------------------
 * [2] THE STRAIGHT LINE IS UNTOUCHED
 * ---------------------------------------------------------------------------
 * `straight` returns the array it was handed — the same object, not a copy of
 * it, so the tool that drew before this feature draws exactly as it did. The
 * same holds for everything that cannot be decorated: amplitude 0, spacing 0,
 * a NaN, one clicked point, a style this build does not know.
 *
 * ---------------------------------------------------------------------------
 * [3] DETERMINISM
 * ---------------------------------------------------------------------------
 * The seed is the clicked line itself (`strokeSeed`), so the same stroke gives
 * the same spikes twice, and an explicit seed overrides it. RED counter-probe:
 * a different seed must give MEASURABLY different deflections — same count,
 * same positions, other heights — or the whole seeding would be decoration in
 * name only. Moving one clicked point is such a different seed.
 *
 * ---------------------------------------------------------------------------
 * [4] THE POINT CAP (MAX_DECORATED_POINTS = 120)
 * ---------------------------------------------------------------------------
 * The budget is the server's 256-point polygon limit counted where it is
 * spent: a mitred ribbon is 2n points, so 120 centre points make a 240-point
 * outline.
 *   [(0,0),(1000,0)], spacing 2: 500 deflections would be 502 points. Room is
 *   120 − 2 = 118, so the spacing becomes 1000/118 = 8.474576…, and the
 *   positions 4.23…, 12.71…, …, 995.76… are exactly 118 (the next would be
 *   1004.2 > 1000): 120 points, `capped` true, `spacingM` the raised one.
 *   Fed through `strokeToPolygon` at width 4 that is a 240-point outline —
 *   the budget, to the point.
 *   Spacing 20 on the same line asks for 50 deflections, which fits: 52
 *   points, `capped` false, `spacingM` still 20.
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'frontend/src/tabs/map/mapMath.ts');

/** The module, bundled and imported — @anima/scene-render is a workspace
 *  package of TypeScript sources, so esbuild resolves and inlines it. */
async function loadMapMath() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'strokestyles-smoke-'));
  try {
    const file = join(dir, 'mapMath.mjs');
    await esbuild.build({
      entryPoints: [SRC], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
    });
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
/** A red counter-probe: the two answers must NOT agree. */
function differs(label, a, b) {
  const ok = JSON.stringify(a) !== JSON.stringify(b);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       both are ${JSON.stringify(a)}`
      + ' — the check proves nothing');
  }
}
function compare(a, b, eps) {
  if (a === null || b === null) return a === b;
  if (typeof b === 'number') return typeof a === 'number' && Math.abs(a - b) <= eps;
  if (Array.isArray(b)) {
    return Array.isArray(a) && a.length === b.length
      && b.every((v, i) => compare(a[i], v, eps));
  }
  if (typeof b === 'object') {
    const keys = Object.keys(b);
    if (typeof a !== 'object' || a === null) return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

const { decorateStroke, strokeSeed, strokeToPolygon, MAX_DECORATED_POINTS,
  STROKE_STYLES, isStrokeStyle } = await loadMapMath();

const LINE_100 = [[0, 0], [100, 0]];
const CORNER = [[0, 0], [10, 0], [10, 10]];
const A = 2;
/** The height band the rule allows: [0.4·A, A]. */
const inBand = (v) => Math.abs(v) >= 0.4 * A - 1e-9 && Math.abs(v) <= A + 1e-9;

console.log('[1] where the deflections sit');
const jag = decorateStroke(LINE_100, 'jagged', 10, A);
check('a 100 m line at 10 m spacing carries 10 deflections',
  jag.points.length, 12);
check('...the spacing is the one asked for', jag.spacingM, 10);
check('...and nothing was thinned out', jag.capped, false);
check('the clicked ends stand where they were clicked',
  [jag.points[0], jag.points[11]], [[0, 0], [100, 0]]);
check('the deflections sit at 5, 15, … 95 (x is the arc position)',
  jag.points.slice(1, 11).map((p) => p[0]),
  [5, 15, 25, 35, 45, 55, 65, 75, 85, 95]);
check('...every height inside [0.4·A, A]',
  jag.points.slice(1, 11).every((p) => inBand(p[1])), true);
check('...and jagged alternates the sides, starting on side A (−z)',
  jag.points.slice(1, 11).map((p) => Math.sign(p[1])),
  [-1, 1, -1, 1, -1, 1, -1, 1, -1, 1]);
// Not a multiple of the spacing: 100/30 = 3.33… -> 3, the "±1" the field means.
check('a 30 m spacing on the same line carries 3',
  decorateStroke(LINE_100, 'jagged', 30, A).points.map((p) => p[0]),
  [0, 15, 45, 75, 100]);
const corner = decorateStroke(CORNER, 'jagged', 10, A);
check('the clicked corner survives between the two deflections',
  [corner.points.length, corner.points[0], corner.points[2], corner.points[4]],
  [5, [0, 0], [10, 0], [10, 10]]);
check('...the first is pushed sideways on segment 0 (x = 5, z = −m0)',
  [corner.points[1][0], Math.sign(corner.points[1][1]),
    inBand(corner.points[1][1])], [5, -1, true]);
check('...the second on segment 1, whose normal is (1,0) (z = 5, x = 10−m1)',
  [corner.points[3][1], Math.sign(corner.points[3][0] - 10),
    inBand(corner.points[3][0] - 10)], [5, -1, true]);
const wav = decorateStroke(LINE_100, 'wavy', 10, A);
check('wavy uses the same 10 positions',
  wav.points.map((p) => p[0]), jag.points.map((p) => p[0]));
check('...and stays inside the amplitude',
  wav.points.slice(1, 11).every((p) => Math.abs(p[1]) <= A + 1e-9), true);
differs('...but is NOT the jagged zigzag', wav.points, jag.points);

console.log('[2] the straight line is untouched');
check('straight hands the very array back',
  decorateStroke(LINE_100, 'straight', 10, A).points === LINE_100, true);
check('...and reports the spacing it was given, uncapped',
  { s: decorateStroke(LINE_100, 'straight', 10, A).spacingM,
    c: decorateStroke(LINE_100, 'straight', 10, A).capped }, { s: 10, c: false });
for (const [label, args] of [
  ['an amplitude of 0', ['jagged', 10, 0]],
  ['a negative amplitude', ['jagged', 10, -3]],
  ['a NaN amplitude', ['jagged', 10, NaN]],
  ['a spacing of 0', ['jagged', 0, A]],
  ['a NaN spacing', ['jagged', NaN, A]],
  ['a style this build does not know', ['dotted', 10, A]],
]) {
  check(`${label} decorates nothing`,
    decorateStroke(LINE_100, ...args).points === LINE_100, true);
}
check('one clicked point is no line',
  decorateStroke([[5, 5]], 'jagged', 10, A).points.length, 1);
check('a line of zero length is no line either',
  decorateStroke([[5, 5], [5, 5]], 'jagged', 10, A).points.length, 2);
check('a non-finite coordinate decorates nothing',
  decorateStroke([[0, 0], [NaN, 0]], 'jagged', 10, A).points.length, 2);
check('the three styles are the three the toolbar offers',
  [...STROKE_STYLES], ['straight', 'jagged', 'wavy']);
check('...and only those are read as a style',
  [isStrokeStyle('wavy'), isStrokeStyle('dotted'), isStrokeStyle(7),
    isStrokeStyle(null)], [true, false, false, false]);

console.log('[3] determinism');
check('the same line twice gives the same points',
  decorateStroke(LINE_100, 'jagged', 10, A).points,
  decorateStroke(LINE_100, 'jagged', 10, A).points);
check('the seed IS the clicked line',
  decorateStroke(LINE_100, 'jagged', 10, A, strokeSeed(LINE_100)).points,
  jag.points);
// RED counter-probe: another seed must move the heights, not just claim to.
const other = decorateStroke(LINE_100, 'jagged', 10, A, 'terrain:stroke:other');
check('RED: another seed keeps the positions',
  other.points.map((p) => p[0]), jag.points.map((p) => p[0]));
differs('RED: …and moves the heights', other.points.map((p) => p[1]),
  jag.points.map((p) => p[1]));
// A dragged clicked point is such a different seed — same reason, real cause.
differs('RED: a moved clicked point redraws the pattern',
  decorateStroke([[0, 0], [100, 0.5]], 'jagged', 10, A).points.map((p) => p[1]),
  jag.points.map((p) => p[1]));
// …and the two styles must not agree either, or the phase would be dead.
differs('RED: wavy and jagged are two shapes, not one',
  wav.points.map((p) => p[1]), jag.points.map((p) => p[1]));

console.log('[4] the point cap');
check('the budget is 120 centre points', MAX_DECORATED_POINTS, 120);
const dense = decorateStroke([[0, 0], [1000, 0]], 'jagged', 2, A);
check('2 m spacing over 1000 m is thinned to the budget',
  dense.points.length, 120);
check('...and says so', dense.capped, true);
check('...at the raised spacing 1000/118', dense.spacingM, 1000 / 118, 1e-9);
check('...the first deflection sits half a raised spacing in',
  dense.points[1][0], Math.round((1000 / 118 / 2) * 100) / 100, 1e-9);
check('...the outline it generates is exactly the 240-point budget',
  strokeToPolygon(dense.points, 4).length, 240);
const loose = decorateStroke([[0, 0], [1000, 0]], 'jagged', 20, A);
check('a spacing that fits is left alone',
  [loose.points.length, loose.capped, loose.spacingM], [52, false, 20]);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
