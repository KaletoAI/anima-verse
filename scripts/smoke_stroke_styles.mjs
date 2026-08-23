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
 * [1] WHERE THE DEFLECTIONS SIT (jagged: one point each)
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
 *   The corner-normal BLEND (see [5]) does not reach either of them: its
 *   window is half-open and both sit exactly spacing/2 = 5 from the corner.
 *   This case is therefore the same line it was before the blend existed —
 *   measured, not assumed, which is why it stays pinned point for point.
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
 * [4] THE POINT CAP (MAX_DECORATED_POINTS = 1024)
 * ---------------------------------------------------------------------------
 * The budget is the server's 2050-point polygon limit counted where it is
 * spent: a mitred ribbon is 2n points, so 1024 centre points make a 2048-point
 * outline and the two spare are what one bevelled join adds.
 *   [(0,0),(1000,0)], jagged, spacing 2: 500 deflections, 502 points, and the
 *   budget is not touched — `capped` false, `spacingM` still 2. (Under the old
 *   120-point budget this was the case that BIT.)
 *   [(0,0),(10000,0)], jagged, spacing 2: 5000 deflections would be 5002
 *   points. Room is 1024 − 2 = 1022, so the spacing becomes 10000/1022
 *   = 9.784735…, and the positions 4.89…, 14.68…, …, 9995.1… are exactly 1022
 *   (the next would be 10004.9 > 10000): 1024 points, `capped` true. Fed
 *   through `strokeToPolygon` at width 4 that is a 2048-point outline — inside
 *   the server's 2050, to the point.
 *   Spacing 20 on the 1000 m line asks for 50 deflections, which fits: 52
 *   points, `capped` false, `spacingM` still 20.
 *
 * ---------------------------------------------------------------------------
 * [5] WAVY IS A CURVE, NOT FOUR SAMPLES PER PERIOD
 * ---------------------------------------------------------------------------
 * The rule (`decorateStroke`), spelled out once more so this file derives the
 * numbers instead of recording them:
 *
 *   offset(d) = A(d) · sin(phase + 2π·d / (4·spacing))
 *
 * sampled every step = min(spacing/3, 3 m) of arc length. `A(d)` cosine-eases
 * (`(1−cos(πt))/2`) through the deflection heights m_i at spacing/2,
 * 3·spacing/2, … and is pinned to 0 at both clicked ends, so the curve leaves
 * and re-enters the line tangentially and the ends stay where they were
 * clicked. `phase` is `rnd()·2π`, the m_i are `A·(0.4 + 0.6·rnd())` in that
 * order — the same stream `jagged` reads, which is what lets the two styles
 * be compared at all.
 *
 *   [(0,0),(100,0)], spacing 10, A 2: step = min(3.33…, 3) = 3, so the arc
 *   positions are 0, 3, …, 99 (34 of them) plus the end at 100 -> 35 points.
 *   The normal is (0,−1) throughout, so x IS the arc position and the offset
 *   lands entirely in z: z(d) = −A(d)·sin(phase + π·d/20).
 *     · 35 points, x = [0, 3, …, 99, 100]
 *     · z(0) = z(100) = 0 exactly — A is 0 at both ends
 *     · |z| <= A = 2 everywhere, since |sin| <= 1 and A(d) <= A
 *     · the period is 4·spacing = 40 m and the step is 3 m, so a period
 *       carries 13.33 samples — the "at least 12" the rule promises, and
 *       three times what the old four-per-period sampling gave
 *     · every point equals the closed form above, to the 2 decimals the
 *       output is rounded to (the check re-derives it from `seededRandom`)
 *   SMOOTHNESS, hand-derived: |offset'| <= max|A'| + max|A|·2π/(4·spacing).
 *   The steepest cosine ease is an END RAMP (up to A = 2 over spacing/2 = 5 m,
 *   so (π/2)·2/5 = 0.62832) and the sine term is at most 2·π/20 = 0.31416,
 *   giving |offset'| <= 3πA/(2·spacing) = 0.94248. Each sample-to-sample
 *   direction is therefore within atan(0.94248) = 43.304° of the line, so the
 *   TURN at any sample is at most 86.61°; and |Δz| between two samples is at
 *   most 0.94248·3 = 2.8274 m. Between the first and last anchor, where the
 *   ease spans 10 m and at most A − 0.4A = 1.2, the same sum is
 *   0.18850 + 0.31416 = 0.50265 -> 26.687°, turn at most 53.38°, |Δz| at most
 *   1.5080 m.
 *   [(0,0),(1000,0)], spacing 10: room is 1022, so a sample every 1000/1022
 *   = 0.98 m would still fit and the asked-for 3 m stands — 0, 3, …, 999 plus
 *   the end = 335 points, `capped` false. Under the old 120-point budget the
 *   same line had to be sampled every 8.47 m: 4.7 samples per period, i.e. the
 *   zigzag again. Its outline at width 4 is 670 points — over the old 256
 *   limit, inside the new 2050.
 *   [(0,0),(5000,0)], spacing 10: 5000/1022 = 4.8924 > 3, so the step gives
 *   way and the spacing follows it up to 3·4.8924 = 14.6771 (never DOWN, so a
 *   wide spacing stays wide): `capped` true and at most 1024 points.
 *
 * ---------------------------------------------------------------------------
 * [6] A CORNER BENDS, IT DOES NOT SNAP
 * ---------------------------------------------------------------------------
 * Over ±half of arc length around a clicked corner — half = min(spacing/2,
 * and half of either adjoining segment) — the side normal is the cosine-eased
 * mix normalize((1−b)·n1 + b·n2) with b = ease((d−corner+half)/(2·half)).
 *   [(0,0),(10,0),(10,10)], WAVY, spacing 10: half = min(5,5,5) = 5, the
 *   arc positions are 0, 3, 6, 9, the corner at 10, then 12, 15, 18 and the
 *   end at 20 -> 9 points. At the corner b = ease(0.5) = 0.5, so the normal is
 *   normalize((0,−1)+(1,0)) = (0.7071068,−0.7071068) — a 45° push, exactly
 *   between the two segments. The point is therefore (10+0.7071068·o,
 *   −0.7071068·o) for one offset o, i.e. its x−10 and its −z are the SAME
 *   number. A snapping normal would put it on one of the two axes instead.
 *   [(0,0),(7,0),(7,7)], JAGGED, spacing 10: one deflection at 5, corner at 7,
 *   half = min(5, 3.5, 3.5) = 3.5, window [3.5, 10.5]. u = (5−7+3.5)/7
 *   = 0.2142857, b = ease(u) = 0.1090843, mix (0.1090843,−0.8909157) of
 *   length 0.8975691 -> normal (0.1215330,−0.9925874), so the deflection lands
 *   at (5 + 0.1215330·m0, −0.9925874·m0) instead of the unblended (5, −m0).
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'frontend/src/tabs/map/mapMath.ts');

/** The module, bundled and imported — @anima/scene-render is a workspace
 *  package of TypeScript sources, so esbuild resolves and inlines it.
 *
 *  `seededRandom` comes along because the wavy curve is a closed form OVER A
 *  RANDOM STREAM: phase and deflection heights cannot be written down as
 *  literals, so the only way to check the values instead of the shape is to
 *  re-derive them from the same PRNG — which is what [5] does. */
async function loadMapMath() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'strokestyles-smoke-'));
  try {
    const file = join(dir, 'mapMath.mjs');
    await esbuild.build({
      stdin: {
        contents: `export * from ${JSON.stringify(SRC)};\n`
          + "export { seededRandom } from '@anima/scene-render';\n",
        resolveDir: ROOT, sourcefile: 'smoke-entry.mjs', loader: 'js',
      },
      outfile: file, bundle: true, format: 'esm',
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
  STROKE_STYLES, isStrokeStyle, seededRandom } = await loadMapMath();

/** The rule's own rounding — `Math.round(v·100)/100`, `+0` to kill −0. */
const r2 = (v) => Math.round(v * 100) / 100 + 0;
/** The cosine ease of the rule: 0 at 0, 1 at 1, flat at both ends. */
const ez = (t) => (1 - Math.cos(Math.PI * t)) / 2;

/**
 * The WAVY curve of a STRAIGHT west→east line, written out from the rule in
 * [5] and from nothing else — a second, independent statement of the same
 * arithmetic, which is the only kind of check a PRNG-driven curve admits.
 * Returns `{ x, z }` arrays.
 */
function wavyByHand(len, spacing, amp, seed) {
  const rnd = seededRandom(seed);
  const phase = rnd() * Math.PI * 2;
  const aD = [0];
  const aH = [0];
  for (let d = spacing / 2; d < len - 1e-9; d += spacing) {
    aD.push(d);
    aH.push(amp * (0.4 + 0.6 * rnd()));
  }
  aD.push(len);
  aH.push(0);
  const env = (d) => {
    let i = 0;
    while (i + 2 < aD.length && aD[i + 1] < d) i += 1;
    const span = aD[i + 1] - aD[i];
    if (!(span > 0)) return aH[i + 1];
    return aH[i] + (aH[i + 1] - aH[i]) * ez((d - aD[i]) / span);
  };
  const step = Math.min(spacing / 3, 3);
  const x = [];
  const z = [];
  for (let k = 0; k * step < len - 1e-9; k += 1) {
    const d = k * step;
    // The normal of a west→east segment is (0,−1): x keeps the arc position
    // and the whole offset lands in z, with the sign the normal gives it.
    x.push(r2(d));
    z.push(k === 0 ? 0
      : r2(-env(d) * Math.sin(phase + (2 * Math.PI * d) / (4 * spacing))));
  }
  x.push(len);
  z.push(0);
  return { x, z };
}

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
// The blend does NOT reach these two deflections (see [6]) — both sit exactly
// spacing/2 = 5 from the corner and the window is half-open — so the arc
// positions above survive untouched and the case is the line it always was.
check('...and the corner blend reaches neither of them',
  [corner.points[1][0], corner.points[3][1]], [5, 5]);

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

console.log('[4] the point cap');
check('the budget is 1024 centre points', MAX_DECORATED_POINTS, 1024);
const km = decorateStroke([[0, 0], [1000, 0]], 'jagged', 2, A);
check('2 m spacing over 1000 m now fits — 500 deflections, 502 points',
  [km.points.length, km.capped, km.spacingM], [502, false, 2]);
const dense = decorateStroke([[0, 0], [10000, 0]], 'jagged', 2, A);
check('...ten times that line IS thinned to the budget',
  dense.points.length, 1024);
check('...and says so', dense.capped, true);
check('...at the raised spacing 10000/1022', dense.spacingM, 10000 / 1022, 1e-9);
check('...the first deflection sits half a raised spacing in',
  dense.points[1][0], Math.round((10000 / 1022 / 2) * 100) / 100, 1e-9);
check('...the outline it generates is the 2048-point mitred budget',
  strokeToPolygon(dense.points, 4).length, 2048);
const loose = decorateStroke([[0, 0], [1000, 0]], 'jagged', 20, A);
check('a spacing that fits is left alone',
  [loose.points.length, loose.capped, loose.spacingM], [52, false, 20]);

console.log('[5] wavy is a curve, not four samples per period');
const wav = decorateStroke(LINE_100, 'wavy', 10, A);
const want = wavyByHand(100, 10, A, strokeSeed(LINE_100));
check('a 100 m line at spacing 10 is sampled every 3 m: 34 + the end',
  [wav.points.length, wav.spacingM, wav.capped], [35, 10, false]);
check('...the arc positions are 0, 3, …, 99, 100', wav.points.map((p) => p[0]),
  want.x);
check('...and every offset is A(d)·sin(phase + π·d/20), to the 2 decimals',
  wav.points.map((p) => p[1]), want.z, 1e-9);
check('...both ends stay exactly where they were clicked',
  [wav.points[0], wav.points[34]], [[0, 0], [100, 0]]);
check('...nothing leaves the amplitude',
  wav.points.every((p) => Math.abs(p[1]) <= A + 1e-9), true);
check('...a period (4·spacing = 40 m) carries 13.33 samples, not 4',
  (4 * wav.spacingM) / 3, 40 / 3, 1e-9);
// The turn bound of [5], from |offset'| <= 3πA/(2·spacing) = 0.94248.
const dirs = [];
for (let i = 1; i < wav.points.length; i++) {
  dirs.push(Math.atan2(wav.points[i][1] - wav.points[i - 1][1],
    wav.points[i][0] - wav.points[i - 1][0]));
}
const maxTurn = Math.max(...dirs.slice(1).map((d, i) => Math.abs(d - dirs[i])));
const maxDir = Math.max(...dirs.map(Math.abs));
check('...no sample-to-sample direction leaves ±atan(0.94248) = 43.304°',
  maxDir <= Math.atan(0.94248) + 1e-9, true);
check('...so no turn reaches the 86.61° that bound allows',
  maxTurn <= 2 * Math.atan(0.94248) + 1e-9, true);
// RED: the OLD rule sampled four times per period, i.e. 12 points on this
// line. A check that only bounds the turn would pass for that zigzag too.
check('RED: the old four-per-period sampling would have been 12 points',
  wav.points.length > 30, true);
const kmWav = decorateStroke([[0, 0], [1000, 0]], 'wavy', 10, A);
check('a KILOMETRE of river is 335 points at the asked-for 3 m',
  [kmWav.points.length, kmWav.capped, kmWav.spacingM], [335, false, 10]);
check('...and its outline is 670 points — over the old 256, inside 2050',
  strokeToPolygon(kmWav.points, 4).length, 670);
const wide = decorateStroke([[0, 0], [5000, 0]], 'wavy', 10, A);
check('five kilometres is where the step has to give way',
  [wide.capped, wide.points.length <= MAX_DECORATED_POINTS], [true, true]);
check('...and the spacing follows it UP to 3·5000/1022',
  wide.spacingM, 3 * (5000 / 1022), 1e-9);
check('...never down: a 100 m spacing on the same line stays 100',
  decorateStroke([[0, 0], [5000, 0]], 'wavy', 100, A).spacingM, 100);

console.log('[6] a corner bends, it does not snap');
const wavCorner = decorateStroke(CORNER, 'wavy', 10, A);
check('the 90° corner is sampled at 0, 3, 6, 9, 10, 12, 15, 18, 20',
  [wavCorner.points.length, wavCorner.points.map((p) => p[0])[0]], [9, 0]);
// The corner point, derived from the rule alone: base (10,0), amplitude the
// cosine ease halfway between the anchors at 5 and 15 (= their mean), sine
// argument phase + 2π·10/40 = phase + π/2, normal normalize((0,−1)+(1,0)).
const rndC = seededRandom(strokeSeed(CORNER));
const phC = rndC() * Math.PI * 2;
const mC0 = A * (0.4 + 0.6 * rndC());
const mC1 = A * (0.4 + 0.6 * rndC());
const offC = ((mC0 + mC1) / 2) * Math.sin(phC + Math.PI / 2);
check('...and its point is (10,0) pushed along (0.7071068,−0.7071068)',
  wavCorner.points[4],
  [r2(10 + offC * Math.SQRT1_2), r2(-offC * Math.SQRT1_2)], 1e-9);
// …and the blend really is the eased mix, not a straight average: the jagged
// case of [6], whose one deflection sits inside the window.
const bent = decorateStroke([[0, 0], [7, 0], [7, 7]], 'jagged', 10, A);
const b7 = ez((5 - 7 + 3.5) / 7);
const n7 = [b7 / Math.hypot(b7, 1 - b7), -(1 - b7) / Math.hypot(b7, 1 - b7)];
check('the blended normal is (0.1215330, −0.9925874), not (0,−1)',
  n7, [0.1215330, -0.9925874], 1e-6);
const m7 = bent.points[1][1] / n7[1];    // the height that normal implies
check('...and the deflection inside the window rides it',
  [bent.points.length, bent.points[1][0], inBand(bent.points[1][1])],
  [4, 5 + m7 * n7[0], true], 0.011);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
