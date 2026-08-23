#!/usr/bin/env node
/**
 * Smoke check for the WATERFALL ("Ein Wasser-Gesetz" W5) — which segment of a
 * river's own flow axis is a fall, where it stands, and how wide it is.
 *
 * Usage:  node client3d/scripts/smoke_waterfall.mjs
 *         (transpiles `packages/scene-render/src/waterfall.ts`; needs esbuild)
 *
 * The mirror the axis belongs to is checked next door
 * (`client3d/scripts/smoke_water_plane.mjs`, the polyline profile of W4a); this
 * is the ONE question W5 adds to it. Every expected value below is derived BY
 * HAND in this docstring (§ B5a) — nothing here records current output.
 *
 * ===========================================================================
 * [1] THE RULE, and why it is two conditions
 * ===========================================================================
 * Per consecutive pair of knots `a -> b` of `meta.water_profile.axis` (in flow
 * order, levels already made non-increasing by the bake):
 *
 *     drop = a.level − b.level        metres of mirror lost
 *     run  = b.s − a.s                metres of axis spent
 *     fall <=> drop > 1.0  AND  drop/run > 0.5
 *
 * BOTH, and both STRICTLY. Alone, each is wrong in a way the other repairs:
 *
 *   - the DROP alone calls a valley a waterfall — a river losing 4 m over 200 m
 *     of its length passes it and is a slope one walks down beside;
 *   - the SLOPE alone calls a stone in the stream one — 0.2 m over 0.3 m of run
 *     is a 1-in-1.5 step and the mirror already draws it as the short ramp it is.
 *
 * 1.0 m is `swim_from_m`'s default (W4c): the least water this world already
 * treats as more than a step. 0.5 is 1-in-2, i.e. 26.6°, past where loose
 * material lies still at all — a bed that steep is scree and the water on it is
 * falling, not flowing.
 *
 * AT LEAST THREE KNOTS. A polygon river's axis is the two extremes of ONE
 * straight ramp (`heightfield._straight_profile`): its single segment is the
 * whole river, so a "fall" there would be a curtain across the entire length of
 * the water. A lake is one knot and has no segment at all.
 *
 * ===========================================================================
 * [2] THE PLAN'S FIXTURE — 10 / 9.8 / 4 / 3.9 over runs 20 / 3 / 20
 * ===========================================================================
 * Four knots, and the middle segment is the edge. Laid out so the fall does NOT
 * point the way the area does (see the red probe below): the first leg runs
 * 20 m east, the fall 3 m to the south-east, the last leg 20 m on:
 *
 *     A = (0, 0)        s = 0     level 10
 *     B = (20, 0)       s = 20    level 9.8      |AB| = 20            ✓
 *     C = (21.8, −2.4)  s = 23    level 4        |BC| = √(1.8²+2.4²)
 *                                                     = √9 = 3        ✓
 *     D = (33.8, −18.4) s = 43    level 3.9      |CD| = √(12²+16²)
 *                                                     = √400 = 20     ✓
 *
 * Segment by segment:
 *
 *     A->B  drop 0.2   run 20   0.2 > 1.0 ?  NO           -> no fall
 *     B->C  drop 5.8   run 3    5.8 > 1.0 ✓  5.8/3
 *                                            = 1.9333 > 0.5 ✓ -> FALL
 *     C->D  drop 0.1   run 20   0.1 > 1.0 ?  NO           -> no fall
 *
 * EXACTLY ONE FALL, and it is:
 *
 *     midpoint  ((20 + 21.8)/2, (0 + (−2.4))/2)  = (20.9, −1.2)
 *     direction (1.8, −2.4)/3                    = (0.6, −0.8)
 *     top / bottom                                = 9.8 / 4
 *     width     = the drawn ribbon's own `meta.stroke.width_m` = 6
 *
 * THE RED PROBE IS THE DIRECTION. The area-wide bearing of the nine numbers is
 * the CHORD A -> D = (33.8, −18.4), |chord| = √(33.8² + 18.4²) =
 * √(1142.44 + 338.56) = √1481 = 38.4837628, i.e. (0.8782925, −0.4781237).
 * Against the fall's own (0.6, −0.8):
 *
 *     cos = 0.6·0.8782925 + (−0.8)·(−0.4781237)
 *         = 0.5269755 + 0.3824990 = 0.9094745      -> 24.5672°
 *
 * A curtain hung on the AREA's bearing would stand a quarter-turn of a right
 * angle askew to the stream it is supposed to cross. The segment's own
 * direction is the whole reason the fall is read per segment.
 *
 * ===========================================================================
 * [3] THE FLAT RIVER — 10 down to 6 over 200 m
 * ===========================================================================
 *     A = (0, 0)    s = 0    level 10
 *     B = (100, 0)  s = 100  level 8
 *     C = (200, 0)  s = 200  level 6
 *
 *     A->B  drop 2.0  run 100  drop passes (2 > 1) but 2/100 = 0.02 > 0.5 ? NO
 *     B->C  the same
 *
 * NO FALL — and it is the DROP condition that lets it through and the SLOPE
 * that stops it, which is exactly why there are two.
 *
 * ===========================================================================
 * [4] THE TWO THRESHOLDS, from both sides
 * ===========================================================================
 * THE DROP, at run 1 m (slope 1.0, well past its own threshold, so only the
 * drop is under test):
 *
 *     10 -> 9      drop 1.0     1.0 > 1.0 ? NO (strict)      -> none
 *     10 -> 8.999  drop 1.001   1.001 > 1.0 ✓                -> ONE, top 10,
 *                                                               bottom 8.999
 *
 * THE SLOPE, at drop 2 m (twice its own threshold, so only the slope is under
 * test):
 *
 *     run 4.0   2/4   = 0.5      0.5 > 0.5 ? NO (strict)     -> none
 *     run 3.9   2/3.9 = 0.51282  > 0.5 ✓                     -> ONE, midpoint
 *                                                               x = 1.95
 *
 * Each fixture carries a third knot that is deliberately NOT a fall (a 1.0 m
 * and a 0.5 m step), so the axis has the three knots the rule needs and the
 * answer is about the segment under test alone.
 *
 * ===========================================================================
 * [5] THE POLYGON RIVER — steep and still no fall
 * ===========================================================================
 *     A = (0, 0)   s = 0   level 10
 *     B = (0, −3)  s = 3   level 4
 *
 *     drop 6.0  run 3  ->  6 > 1 ✓   6/3 = 2 > 0.5 ✓
 *
 * BOTH THRESHOLDS PASS AND THERE IS STILL NO FALL, because two knots are one
 * ramp and one ramp is the whole river. This is the red probe for the ≥ 3 rule:
 * without it, every steep polygon water in a world would grow a curtain across
 * its own length. (A lake — one knot — has no segment to test at all.)
 *
 * ===========================================================================
 * [6] TWO FALLS ON ONE RIVER, in flow order
 * ===========================================================================
 *     (0,0)  s 0   20      (2,0)  s 2   18     -> drop 2.0 / run 2 -> FALL
 *     (2,0)  s 2   18      (22,0) s 22  17.8   -> drop 0.2         -> no
 *     (22,0) s 22  17.8    (24,0) s 24  15     -> drop 2.8 / run 2 -> FALL
 *     (24,0) s 24  15      (44,0) s 44  14.8   -> drop 0.2         -> no
 *
 * Two falls, midpoints x = 1 and x = 23, tops 20 and 17.8. A staircase river is
 * a staircase, not one big fall.
 *
 * ===========================================================================
 * [7] THE WIDTH IS THE DRAWN RIBBON'S
 * ===========================================================================
 * `strokeWidthM(meta)` reads `meta.stroke.width_m`, which the server requires
 * of every stroke recipe (`models.terrain._sanitize_stroke`). No recipe, no
 * width — and no width, no fall: a curtain has to span the stream, and a stream
 * of unknown width has no curtain. In practice the two answers agree by
 * construction, because the axes with interior knots ARE the drawn ones.
 *
 * ===========================================================================
 * [8] THE 3D HALF, structurally
 * ===========================================================================
 * `client3d/src/scene/waterfall.ts` imports three and cannot be transpiled into
 * this process, so what is checked here is what makes it the ARRANGEMENT the
 * plan decided on, plus the two numbers it derives:
 *
 *     the mean speed of the falling water   √(g·h/2)
 *       h = 5.8  ->  √(9.81 · 5.8 / 2) = √28.449 = 5.3337604 m/s
 *       h = 2.0  ->  √(9.81 · 2.0 / 2) = √9.81   = 3.1320920 m/s
 *
 *     the lean, 0.3 m of downstream run per metre of fall — a jet leaving the
 *       lip at 1.5 m/s falls 5.8 m in √(2·5.8/9.81) = √1.1824679 = 1.0874129 s
 *       and travels 1.5 · 1.0874129 = 1.6311194 m while it does, i.e.
 *       1.6311194 / 5.8 = 0.2812275 of its own height.
 *
 * …and the arrangement: the curtain reuses the mirror's normal map (no second
 * texture), rides the shared surface clock (no per-frame work of its own), the
 * foam is the shore's own `WATER_FOAM_STRENGTH`, and no particle system was
 * built. In `ground.ts` the falls join `nextWater` and their materials the
 * area's disposal bag, which is what makes them die with the mirrors.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/** The file under test is import-free by design (its header says so), so a
 *  transpile is all it takes — the pattern of the other `.mjs` smokes. */
async function loadPure(...relPaths) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'waterfall-'));
  try {
    const mods = [];
    for (const [i, rel] of relPaths.entries()) {
      const source = await readFile(join(ROOT, rel), 'utf8');
      const code = esbuild.transformSync(source, { loader: 'ts', format: 'esm' }).code;
      const file = join(dir, `m${i}.mjs`);
      await writeFile(file, code, 'utf8');
      mods.push(await import(`file://${file}`));
    }
    return mods;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-12) {
  const ok = typeof actual === 'number' && Math.abs(actual - expected) <= eps;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}
function checkEq(label, actual, expected) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a === b) {
    passed += 1;
    console.log(`  ok   ${label} = ${a}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${b}\n       actual   ${a}`);
  }
}

const [W] = await loadPure('packages/scene-render/src/waterfall.ts');
const { strokeWidthM, waterfallsFrom, WATERFALL_MIN_DROP_M,
  WATERFALL_MIN_SLOPE } = W;

/** The plan's fixture, docstring [2] — one fall on the middle segment. */
const PLAN_AXIS = { axis: [[0, 0, 0, 10], [20, 0, 20, 9.8],
  [21.8, -2.4, 23, 4], [33.8, -18.4, 43, 3.9]] };
/** …as the payload carries it: a river drawn with the line tool, 6 m wide. */
const PLAN_META = { stroke: { points: [[0, 0], [20, 0], [21.8, -2.4],
  [33.8, -18.4]], width_m: 6 }, water_profile: PLAN_AXIS };

// ── [1] the two constants ──────────────────────────────────────────────────
console.log('[1] the thresholds, and they are the plan\'s');
check('a fall drops more than a metre', WATERFALL_MIN_DROP_M, 1.0);
check('…faster than one metre down per two along', WATERFALL_MIN_SLOPE, 0.5);

// ── [2] the plan's fixture ─────────────────────────────────────────────────
console.log('\n[2] 10 / 9.8 / 4 / 3.9 over runs 20 / 3 / 20 -> exactly ONE');
const planFalls = waterfallsFrom(PLAN_AXIS, strokeWidthM(PLAN_META));
check('one fall, not three and not none', planFalls.length, 1);
const fall = planFalls[0] || {};
check('it stands at the middle of the steep segment (x)', fall.x, 20.9);
check('…and (z)', fall.z, -1.2);
check('it points downstream ALONG THAT SEGMENT (x)', fall.dirX, 0.6, 1e-15);
check('…and (z)', fall.dirZ, -0.8, 1e-15);
check('it is a unit direction', Math.hypot(fall.dirX, fall.dirZ), 1, 1e-15);
check('the water leaves at the upstream knot\'s level', fall.topY, 9.8);
check('…and arrives at the downstream one\'s', fall.bottomY, 4);
check('the drop is the plan\'s 5.8 m', fall.topY - fall.bottomY, 5.8, 1e-12);
check('it is as wide as the drawn ribbon', fall.width, 6);
// RED: the AREA's own bearing is not the fall's — see docstring [2].
const chord = Math.hypot(33.8, 18.4);
check('RED: the area-wide chord is this long', chord, 38.4837628, 1e-7);
check('RED: …its bearing (x)', 33.8 / chord, 0.8782925, 1e-7);
check('RED: …and (z)', -18.4 / chord, -0.4781237, 1e-7);
check('RED: …which is this many degrees off the fall\'s own direction',
  (Math.acos(fall.dirX * (33.8 / chord) + fall.dirZ * (-18.4 / chord))
   * 180) / Math.PI, 24.5672, 1e-4);

// ── [3] the flat river ─────────────────────────────────────────────────────
console.log('\n[3] a river losing 4 m over 200 m is a valley, not a fall');
const FLAT = { axis: [[0, 0, 0, 10], [100, 0, 100, 8], [200, 0, 200, 6]] };
checkEq('no fall anywhere on it', waterfallsFrom(FLAT, 6), []);
check('RED: its drop DOES pass the drop threshold', 10 - 8, 2);
check('RED: …and its slope misses the slope one by two orders',
  2 / 100, 0.02);

// ── [4] both thresholds, from both sides ───────────────────────────────────
console.log('\n[4] the thresholds are strict, and each is tested alone');
const DROP_AT = { axis: [[0, 0, 0, 10], [1, 0, 1, 9], [2, 0, 2, 8.5]] };
const DROP_OVER = { axis: [[0, 0, 0, 10], [1, 0, 1, 8.999], [2, 0, 2, 8.5]] };
checkEq('a drop of EXACTLY 1.0 m is not past 1.0 m',
  waterfallsFrom(DROP_AT, 6), []);
check('one millimetre more is', waterfallsFrom(DROP_OVER, 6).length, 1);
check('…and it is that segment', waterfallsFrom(DROP_OVER, 6)[0].topY, 10);
check('…down to', waterfallsFrom(DROP_OVER, 6)[0].bottomY, 8.999);
const SLOPE_AT = { axis: [[0, 0, 0, 10], [4, 0, 4, 8], [8, 0, 8, 7]] };
const SLOPE_OVER = { axis: [[0, 0, 0, 10], [3.9, 0, 3.9, 8], [8, 0, 8, 7]] };
checkEq('a slope of EXACTLY 0.5 is not past 0.5',
  waterfallsFrom(SLOPE_AT, 6), []);
check('RED: …though its drop is twice the drop threshold', 10 - 8, 2);
check('ten centimetres less run and it is a fall',
  waterfallsFrom(SLOPE_OVER, 6).length, 1);
check('…at the middle of that segment',
  waterfallsFrom(SLOPE_OVER, 6)[0].x, 1.95);
check('…whose slope is', 2 / 3.9, 0.5128205128205128, 1e-15);

// ── [5] the two-knot polygon river ─────────────────────────────────────────
console.log('\n[5] a polygon river is ONE ramp — steep is not enough');
const POLY = { axis: [[0, 0, 0, 10], [0, -3, 3, 4]] };
checkEq('no fall, though both thresholds pass', waterfallsFrom(POLY, 6), []);
check('RED: its drop', 10 - 4, 6);
check('RED: …and its slope, both well past', 6 / 3, 2);
checkEq('a lake — one knot — has no segment at all',
  waterfallsFrom({ axis: [[12, -4, 0, 3.25]] }, 6), []);
checkEq('and neither has an empty axis', waterfallsFrom({ axis: [] }, 6), []);
checkEq('nor a missing profile', waterfallsFrom(null, 6), []);
checkEq('nor junk in the axis slot',
  waterfallsFrom({ axis: 'downhill' }, 6), []);
checkEq('a knot carrying a NaN is a broken axis, and draws nothing',
  waterfallsFrom({ axis: [[0, 0, 0, 10], [0, -3, 3, NaN], [0, -6, 6, 1]] }, 6),
  []);

// ── [6] two falls, in flow order ───────────────────────────────────────────
console.log('\n[6] a staircase river is a staircase');
const STAIRS = { axis: [[0, 0, 0, 20], [2, 0, 2, 18], [22, 0, 22, 17.8],
  [24, 0, 24, 15], [44, 0, 44, 14.8]] };
const stairs = waterfallsFrom(STAIRS, 6);
check('two falls', stairs.length, 2);
check('the first one\'s midpoint', stairs[0]?.x, 1);
check('…from', stairs[0]?.topY, 20);
check('…down to', stairs[0]?.bottomY, 18);
check('the second one\'s midpoint', stairs[1]?.x, 23);
check('…from', stairs[1]?.topY, 17.8);
check('…down to', stairs[1]?.bottomY, 15);
console.log('\n[6b] and water never falls upward');
checkEq('a RISING segment is no fall',
  waterfallsFrom({ axis: [[0, 0, 0, 4], [0, -3, 3, 10], [0, -6, 6, 9]] }, 6),
  []);
checkEq('a segment of no length names no direction either',
  waterfallsFrom({ axis: [[0, 0, 0, 10], [0, 0, 0, 4], [0, -6, 6, 3.9]] }, 6),
  []);

// ── [7] the width ──────────────────────────────────────────────────────────
console.log('\n[7] the width is the drawn ribbon\'s, or there is no curtain');
check('the recipe\'s own width', strokeWidthM(PLAN_META), 6);
check('a numeric STRING is a number — the payload is JSON either way',
  strokeWidthM({ stroke: { width_m: '6' } }), 6);
checkEq('a polygon area has no recipe', strokeWidthM({}), null);
checkEq('no meta at all', strokeWidthM(undefined), null);
checkEq('junk in the slot is no recipe', strokeWidthM({ stroke: 'wide' }), null);
checkEq('a width of zero is no width', strokeWidthM({ stroke: { width_m: 0 } }),
  null);
checkEq('…and neither is a NaN',
  strokeWidthM({ stroke: { width_m: NaN } }), null);
checkEq('without a width the steep segment draws nothing',
  waterfallsFrom(PLAN_AXIS, null), []);
checkEq('…and a zero width draws nothing either',
  waterfallsFrom(PLAN_AXIS, 0), []);
check('a width that arrives as a string still spans the stream',
  waterfallsFrom(PLAN_AXIS, '6')[0]?.width, 6);

// ── [8] the 3D half, structurally ──────────────────────────────────────────
console.log('\n[8] the curtain: the arrangement W5 decided on');
const fallSrc = await readFile(
  join(ROOT, 'client3d/src/scene/waterfall.ts'), 'utf8');
const groundSrc = await readFile(
  join(ROOT, 'client3d/src/scene/ground.ts'), 'utf8');
check('the sheet drifts at the MEAN speed of falling water, √(g·h/2)',
  /Math\.sqrt\(WATERFALL_G \* Math\.max\(heightM, 0\) \* 0\.5\)/.test(fallSrc)
    ? 1 : 0, 1);
check('…with g at', /const WATERFALL_G = 9\.81;/.test(fallSrc) ? 1 : 0, 1);
check('a 5.8 m fall therefore scrolls at', Math.sqrt((9.81 * 5.8) / 2),
  5.3337604, 1e-7);
check('…and a 2 m one at', Math.sqrt((9.81 * 2) / 2), 3.1320920, 1e-7);
check('the sheet leans downstream, 0.3 m per metre of fall',
  /const WATERFALL_LEAN = 0\.3;/.test(fallSrc) ? 1 : 0, 1);
check('RED: which is about the chord of a 1.5 m/s jet over that same 5.8 m',
  (1.5 * Math.sqrt((2 * 5.8) / 9.81)) / 5.8, 0.2812275, 1e-7);
check('the foam radius grows with the fall',
  /WATERFALL_FOAM_RADIUS_PER_M \* heightM/.test(fallSrc) ? 1 : 0, 1);
check('…and is never narrower than the stream itself',
  /Math\.max\(fall\.width \* 0\.5,/.test(fallSrc) ? 1 : 0, 1);
check('the foam is the SHORE\'s own white, not a second one',
  /WATER_FOAM_STRENGTH/.test(fallSrc) ? 1 : 0, 1);
check('the curtain reuses the MIRROR\'s normal map',
  /std\.normalMap \?\? null/.test(fallSrc) ? 1 : 0, 1);
check('RED: no second wave texture is built here',
  /makeWaveNormal|createCanvas|CanvasTexture/.test(fallSrc) ? 1 : 0, 0);
check('it rides the shared surface clock',
  /shader\.uniforms\.uTime = surfaceTimeUniform;/.test(fallSrc) ? 1 : 0, 1);
check('RED: …so it has no per-frame work and no loop of its own',
  /requestAnimationFrame|setInterval|onBeforeRender/.test(fallSrc) ? 1 : 0, 0);
check('RED: and no particle system was built (W5 parks them)',
  /new THREE\.(Points|Sprite|InstancedMesh)\b/.test(fallSrc) ? 1 : 0, 0);
check('the sheet writes no depth — the cliff behind it stays visible',
  /depthWrite: false/.test(fallSrc) ? 1 : 0, 1);
check('…and is drawn from both banks',
  /side: THREE\.DoubleSide/.test(fallSrc) ? 1 : 0, 1);
check('the drift is ADDED to the sample coordinate, which carries the crests '
  + 'DOWN', /wfUv \+ vec2\( 0\.0, wfT \)/.test(fallSrc) ? 1 : 0, 1);
console.log('\n[8b] and it lives exactly as long as the mirror does');
check('the falls are read off the very profile the mirror is built on',
  /waterfallsFrom\(profile, strokeWidthM\(meta\)\)/.test(groundSrc) ? 1 : 0, 1);
check('their meshes join the water list, which `clearAreas` empties',
  /nextWater\.push\(\.\.\.buildWaterfall\(fall, mat, nextOwned\)\)/
    .test(groundSrc) ? 1 : 0, 1);
check('…and their materials the area\'s disposal bag',
  /sink\.push\(curtainMat\);/.test(fallSrc)
  && /sink\.push\(foamMat\);/.test(fallSrc) ? 1 : 0, 1);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
