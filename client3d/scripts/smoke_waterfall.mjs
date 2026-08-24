#!/usr/bin/env node
/**
 * Smoke check for the WATERFALL ("Ein Wasser-Gesetz" W5) — which segment of a
 * river's own flow axis is a fall, where it stands, and how wide it is.
 *
 * Usage:  node client3d/scripts/smoke_waterfall.mjs
 *         (transpiles `packages/scene-render/src/waterfall.ts`; needs esbuild)
 *
 * The profile the axis belongs to is checked next door
 * (`client3d/scripts/smoke_water_plane.mjs`, the polyline of W4a); this is the
 * ONE question W5 adds to it. Every expected value below is derived BY
 * HAND in this docstring (§ B5a) — nothing here records current output.
 *
 * ===========================================================================
 * [1] THE RULE, and why it is two conditions
 * ===========================================================================
 * Per consecutive pair of knots `a -> b` of `meta.water_profile.axis` (in flow
 * order, levels already made non-increasing by the bake):
 *
 *     drop = a.level − b.level        metres of water level lost
 *     run  = b.s − a.s                metres of axis spent
 *     fall <=> drop > 1.0  AND  drop/run > 0.5
 *
 * BOTH, and both STRICTLY. Alone, each is wrong in a way the other repairs:
 *
 *   - the DROP alone calls a valley a waterfall — a river losing 4 m over 200 m
 *     of its length passes it and is a slope one walks down beside;
 *   - the SLOPE alone calls a stone in the stream one — 0.2 m over 0.3 m of run
 *     is a 1-in-1.5 step and the ground already draws it as the short ramp it
 *     is.
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
 * [9] THE CLIFF BETWEEN TWO CLICKS — where the falls actually come from (W5b)
 * ===========================================================================
 * Every axis above is hand-written, which is what a unit check of a pure
 * function should be. THIS one is the payload the server really ships for the
 * case the user reported (`scripts/smoke_height_bake.py` [8l], same numbers):
 * a river drawn with TWO clicks, (0,0) -> (100,0), 6 m wide, across a plateau
 * that ends at x = 41 with a 3 m step.
 *
 * Until W5b the knots were the CLICKS, so that river's axis was
 *
 *     [[0,0,0,3], [100,0,100,0]]
 *
 * — two knots, one ramp, 3 m of drop spread over 100 m of run. NO FALL, and
 * for three independent reasons: fewer than three knots, a slope of 0.03, and
 * nothing anywhere near the edge to read. The cliff was invisible in the data.
 *
 * Since W5b the server samples the drawn line every 2 m, measures a level per
 * sample and simplifies the result back to where the level BENDS:
 *
 *     [[0,0,0,3], [40,0,40,3], [42,0,42,0], [100,0,100,0]]
 *
 *     0->40   drop 0.0  run 40   -> no
 *     40->42  drop 3.0  run  2   3.0 > 1.0 ✓  3.0/2 = 1.5 > 0.5 ✓  -> FALL
 *     42->100 drop 0.0  run 58   -> no
 *
 * ONE FALL, midpoint (41, 0), direction (1, 0), top 3, bottom 0, width 6.
 *
 * AND THE SIMPLIFICATION IS WHY IT IS ONE. The sampler alone would have cut
 * the drop into as many segments as it took steps over the edge, and each
 * shortened segment carries a SHORTER DROP — the slope test survives that (it
 * is a ratio) but `WATERFALL_MIN_DROP_M` does not, and a stack of curtains is
 * not a waterfall. Because a genuinely straight fall deviates from its own
 * chord by nothing, the simplification hands this rule ONE segment per bend of
 * the level, which is exactly the unit a curtain is hung on.
 *
 * ===========================================================================
 * [10] A CLICK INSIDE THE CLIFF — the drop belongs to the RUN (2026-08-24)
 * ===========================================================================
 * The knots are the bends of the LEVEL plus the author's own clicks, and a
 * click is never dropped (it is a bend of the LINE). So an author who clicked
 * halfway down a cliff hands this rule TWO segments where the ground has one
 * drop — and asking each of them for a full metre made the waterfall vanish
 * exactly where somebody had clicked in it.
 *
 * The fix is in the grouping, not in the thresholds: maximal runs of
 * consecutive STEEP segments (slope > 0.5) are joined FIRST, and the 1 m
 * minimum is asked of the joined run once.
 *
 *   (a) THE SPLIT DROP — 3.0 / 2.1 / 1.2 at s = 0 / 1.5 / 3.0
 *
 *       seg 1  drop 0.9  run 1.5  slope 0.6 > 0.5 ✓  steep, 0.9 > 1.0 ? NO
 *       seg 2  drop 0.9  run 1.5  slope 0.6 > 0.5 ✓  steep, 0.9 > 1.0 ? NO
 *
 *       Per segment: NO fall at all — the bug. Merged: one run, knots 0..2,
 *       drop 3.0 − 1.2 = 1.8 > 1.0 ✓ over a run of 3.0 (slope 0.6, still past
 *       the slope threshold, as a mean of slopes past it must be). ONE fall,
 *       top 3.0, bottom 1.2, arc midpoint s = 1.5 → the middle knot (1.5, 0),
 *       chord (3, 0) → direction (1, 0).
 *
 *   (b) THREE STEPS — 3.0 / 2.1 / 1.2 / 0.3 at s = 0 / 1.5 / 3.0 / 4.5
 *
 *       All three segments steep (0.6 each), none past 1 m alone. Merged drop
 *       2.7 over 4.5. The arc midpoint is s = 2.25, which lies INSIDE the
 *       second segment: (2.25 − 1.5) / 1.5 = 0.5 of the way from (1.5, 0) to
 *       (3, 0) → x = 2.25.
 *
 *   (c) A BENT FALL — (0,0) s 0 level 3.0, (1.5,0) s 1.5 level 2.1,
 *       (1.5,−1.5) s 3.0 level 1.2
 *
 *       Both segments steep, merged drop 1.8. The CHORD is (1.5, −1.5), length
 *       √4.5 = 2.1213203, so the direction is (0.7071068, −0.7071068) — and
 *       the position is the ARC midpoint (1.5, 0), the elbow, NOT the chord's
 *       middle (0.75, −0.75), which lies in the dry corner beside the water.
 *
 *   (d) A POOL BETWEEN TWO STAIRCASES — 6.0 / 5.1 / 4.2 / 4.1 / 3.2 / 2.3 at
 *       s = 0 / 1.5 / 3 / 23 / 24.5 / 26
 *
 *       seg 3 loses 0.1 over 20 m (slope 0.005) and is NOT steep, so it ends
 *       the first run and opens nothing. TWO falls, not one:
 *         knots 0..2  drop 1.8  top 6.0  bottom 4.2  arc mid s 1.5  → x 1.5
 *         knots 3..5  drop 1.8  top 4.1  bottom 2.3  arc mid s 24.5 → x 24.5
 *       Merging across the pool would have hung one 3.7 m curtain over 26 m of
 *       river, which is the failure mode this direction has to avoid.
 *
 *   (e) A RUN OF ONE SEGMENT IS THE OLD RULE. Every fixture of [2], [4], [6]
 *       and [9] is a single steep segment between two flat ones and keeps the
 *       numbers it always had; the plan's fixture is re-asserted here.
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
 * ===========================================================================
 * [9] THE CURTAIN MUST HANG IN FRONT OF ITS OWN WATERFALL (2026-08-24)
 * ===========================================================================
 * Under Wasser v2 K-A the mirror between lip and pool is not a mesh any more:
 * the terrain is lifted to `max(h, w_level)`, so the fall stands on the ground
 * as a steep, OPAQUE, wet face running the fall's own chord. On the plan's
 * fixture that face runs from knot B (20, 0) at y 9.8 to knot C (21.8, −2.4)
 * at y 4 — 3 m of ground for 5.8 m of drop.
 *
 * Write the run coordinate `r` of a point as its signed distance from the
 * fall's own point (20.9, −1.2) along `dir` = (0.6, −0.8), and the height as
 * `u = (y − 4) / 5.8` (0 at the pool, 1 at the lip). The FACE is then the
 * straight line
 *
 *     r_face(u) = (chord/2)·(1 − 2u) = 1.5·(1 − 2u)
 *
 * THE DEFECT. The curtain used to hang from the same midpoint over a run of
 * `WATERFALL_LEAN · h = 1.74 m`, i.e. `r_old(u) = 0.87·(1 − 2u)`. So
 *
 *     r_old − r_face = (0.87 − 1.5)·(1 − 2u) = −0.63·(1 − 2u)
 *
 * which is NEGATIVE — upstream, i.e. inside the hill — for every u below 0.5
 * and reaches −0.63 m at the pool. Exactly the lower HALF of the sheet stood
 * behind the water's own wall, and only the upper half was ever drawn: the
 * reported "the waterfall only has the waterfall texture at the top", and the
 * reason iso switch 22 ("water lift off") makes the whole curtain appear.
 *
 * THE FIX, and its numbers. The sheet is hung from the LIP and given the
 * face's own run plus the lean at its foot:
 *
 *     halfRun = chord/2 = 1.5      lean = 0.3 · 5.8 = 1.74
 *     top = (20.9, −1.2) − (0.6, −0.8)·1.5          = (20.0,   0.0)
 *     bot = (20.9, −1.2) + (0.6, −0.8)·(1.5 + 1.74) = (22.844, −3.792)
 *
 * The top corner IS knot B, the lip, to the metre. The foot sits
 * hypot(22.844 − 21.8, −3.792 + 2.4) = hypot(1.044, 1.392) = √3.0276 = 1.74 m
 * downstream of knot C, the face's foot — the lean, exactly. And in between
 *
 *     r_new(u) − r_face(u) = 1.74·(1 − u)
 *
 * so the sheet is in front of the face at every height, by 1.74 m at the pool,
 * 0.87 m halfway up, and 0 at the lip — where the curtain's own shader already
 * fades its last 6 % of v to nothing.
 *
 * THE TEXTURE WAS NEVER THE PROBLEM. The first suspicion was the wrap mode —
 * a fresh `THREE.CanvasTexture` clamps, and the curtain tiles its uv by
 * `width / 2.5` × `height / 2.5`, both well over 1. But the map is THE shared
 * one and `materials.makeWaveNormal` sets `wrapS = wrapT = RepeatWrapping` on
 * it before anybody sees it; the pin below is on that line.
 *
 * …and the arrangement: the curtain takes THE one wave normal map of the
 * process straight from `materials.surfaceWaveNormal` — the very texture the
 * terrain's own water pixels scroll (K-A E4), and no second one — rides the
 * shared surface clock (no per-frame work of its own), the foam is the shore's
 * own `WATER_FOAM_STRENGTH`, and no particle system was built. In `ground.ts`
 * the falls join `nextFalls` and their materials the area's disposal bag, which
 * is what makes them die with the areas they were derived from. Since K-A E5
 * they are the ONLY meshes a painted water still produces: the surface itself
 * is the terrain (`scene/waterShade.ts`).
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
check('and it carries the run\'s CHORD, |BC| = 3', fall.chordM, 3, 1e-12);
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

// ── [9] the cliff between two clicks ───────────────────────────────────────
console.log('\n[9] the payload the server really ships for a two-click river');
const CLIFF_AXIS = { axis: [[0, 0, 0, 3], [40, 0, 40, 3], [42, 0, 42, 0],
  [100, 0, 100, 0]] };
const CLIFF_META = { stroke: { points: [[0, 0], [100, 0]], width_m: 6 },
  water_profile: CLIFF_AXIS };
const cliffFalls = waterfallsFrom(CLIFF_AXIS, strokeWidthM(CLIFF_META));
check('exactly one fall, at the edge', cliffFalls.length, 1);
check('it stands at the middle of the 2 m segment that straddles the lip',
  cliffFalls[0]?.x, 41);
check('…on the drawn line', cliffFalls[0]?.z, 0);
check('it points downstream', cliffFalls[0]?.dirX, 1);
check('…and nowhere sideways', cliffFalls[0]?.dirZ, 0);
check('the water leaves at the plateau\'s level', cliffFalls[0]?.topY, 3);
check('…and arrives at the low ground\'s', cliffFalls[0]?.bottomY, 0);
// The drop and the slope are read out of the ANSWER and the axis it was read
// from — 3 − 0 = 3 metres lost over s 42 − 40 = 2 metres of run, i.e. 1.5,
// which is three times the threshold the rule applies.
const cliffDrop = (cliffFalls[0]?.topY ?? NaN) - (cliffFalls[0]?.bottomY ?? NaN);
const cliffRun = CLIFF_AXIS.axis[2][2] - CLIFF_AXIS.axis[1][2];
check('the drop is the plateau\'s own height', cliffDrop, 3);
check('…over a run of 2 m', cliffRun, 2);
check('…i.e. a slope of 1.5', cliffDrop / cliffRun, 1.5);
check('…which is three times WATERFALL_MIN_SLOPE',
  (cliffDrop / cliffRun) / WATERFALL_MIN_SLOPE, 3);
check('the curtain spans the drawn ribbon', cliffFalls[0]?.width, 6);
// RED: the very same river, as the CLICKS alone described it before W5b.
const CLICKS_ONLY = { axis: [[0, 0, 0, 3], [100, 0, 100, 0]] };
checkEq('RED: the two-knot axis of the same two clicks has NO fall at all',
  waterfallsFrom(CLICKS_ONLY, 6), []);
const clickDrop = CLICKS_ONLY.axis[0][3] - CLICKS_ONLY.axis[1][3];
const clickSlope = clickDrop / (CLICKS_ONLY.axis[1][2] - CLICKS_ONLY.axis[0][2]);
check('RED: …its drop is three times the drop threshold',
  clickDrop / WATERFALL_MIN_DROP_M, 3);
check('RED: …while its slope, 3 / 100', clickSlope, 0.03);
check('RED: …misses the slope threshold by a factor of 16⅔',
  WATERFALL_MIN_SLOPE / clickSlope, 16.6666667, 1e-7);
check('RED: …which is how a 3 m cliff stayed invisible',
  clickSlope > WATERFALL_MIN_SLOPE ? 1 : 0, 0);

// ── [10] a click inside the cliff: the drop belongs to the run ─────────────
console.log('\n[10] two sub-metre steps of one cliff are ONE fall');
const SPLIT = { axis: [[0, 0, 0, 3], [1.5, 0, 1.5, 2.1], [3, 0, 3, 1.2]] };
const split = waterfallsFrom(SPLIT, 6);
check('RED: each segment alone loses less than the metre a fall must lose',
  SPLIT.axis[0][3] - SPLIT.axis[1][3], 0.9);
check('RED: …and so does the second', SPLIT.axis[1][3] - SPLIT.axis[2][3], 0.9);
check('RED: …yet each is steeper than the slope threshold',
  (SPLIT.axis[0][3] - SPLIT.axis[1][3]) / (SPLIT.axis[1][2] - SPLIT.axis[0][2]),
  0.6, 1e-15);
check('so the run is one fall, not none', split.length, 1);
check('its drop is the run\'s, 3.0 − 1.2', split[0]?.topY - split[0]?.bottomY,
  1.8, 1e-15);
check('it leaves at the first knot\'s level', split[0]?.topY, 3);
check('…and arrives at the last one\'s', split[0]?.bottomY, 1.2);
check('it stands at the arc midpoint — the clicked knot itself', split[0]?.x,
  1.5);
check('…on the line', split[0]?.z, 0);
check('and points along the chord of the run', split[0]?.dirX, 1);
check('…which here is the drawn line', split[0]?.dirZ, 0);

console.log('\n[10b] three steps: the midpoint falls INSIDE a segment');
const THREE = { axis: [[0, 0, 0, 3], [1.5, 0, 1.5, 2.1], [3, 0, 3, 1.2],
  [4.5, 0, 4.5, 0.3]] };
const three = waterfallsFrom(THREE, 6);
check('still one fall', three.length, 1);
check('drop 3.0 − 0.3', three[0]?.topY - three[0]?.bottomY, 2.7, 1e-15);
check('arc midpoint s = 2.25, half way along the SECOND segment', three[0]?.x,
  2.25);

console.log('\n[10c] a bent fall hangs at its elbow, not beside the water');
const BENT = { axis: [[0, 0, 0, 3], [1.5, 0, 1.5, 2.1], [1.5, -1.5, 3, 1.2]] };
const bent = waterfallsFrom(BENT, 6);
check('one fall', bent.length, 1);
check('the arc midpoint is the elbow (x)', bent[0]?.x, 1.5);
check('…and (z)', bent[0]?.z, 0);
check('RED: the CHORD midpoint would sit in the dry corner (x)',
  (BENT.axis[0][0] + BENT.axis[2][0]) * 0.5, 0.75);
check('RED: …and (z)', (BENT.axis[0][1] + BENT.axis[2][1]) * 0.5, -0.75);
check('the direction IS the chord, √4.5 long (x)', bent[0]?.dirX, 0.7071068,
  1e-7);
check('…and (z)', bent[0]?.dirZ, -0.7071068, 1e-7);
check('it is a unit direction', Math.hypot(bent[0]?.dirX, bent[0]?.dirZ), 1,
  1e-15);

console.log('\n[10d] a pool between two staircases keeps them two falls');
const POOLED = { axis: [[0, 0, 0, 6], [1.5, 0, 1.5, 5.1], [3, 0, 3, 4.2],
  [23, 0, 23, 4.1], [24.5, 0, 24.5, 3.2], [26, 0, 26, 2.3]] };
const pooled = waterfallsFrom(POOLED, 6);
check('RED: the pool loses this little over 20 m',
  POOLED.axis[2][3] - POOLED.axis[3][3], 0.1, 1e-15);
check('RED: …i.e. a slope of 0.005, far short of the threshold',
  (POOLED.axis[2][3] - POOLED.axis[3][3])
  / (POOLED.axis[3][2] - POOLED.axis[2][2]), 0.005, 1e-15);
check('two falls, not one long curtain', pooled.length, 2);
check('the first from', pooled[0]?.topY, 6);
check('…down to', pooled[0]?.bottomY, 4.2);
check('…at its arc midpoint', pooled[0]?.x, 1.5);
check('the second from', pooled[1]?.topY, 4.1);
check('…down to', pooled[1]?.bottomY, 2.3);
check('…at its arc midpoint', pooled[1]?.x, 24.5);

console.log('\n[10e] a run of ONE segment is the rule it always was');
const planAgain = waterfallsFrom(PLAN_AXIS, strokeWidthM(PLAN_META));
check('the plan\'s fixture is still exactly one fall', planAgain.length, 1);
check('…at the same midpoint (x)', planAgain[0]?.x, 20.9);
check('…and (z)', planAgain[0]?.z, -1.2);
check('…from', planAgain[0]?.topY, 9.8);
check('…down to', planAgain[0]?.bottomY, 4);

// ── [8] the 3D half, structurally ──────────────────────────────────────────
console.log('\n[8] the curtain: the arrangement W5 decided on');
const fallSrc = await readFile(
  join(ROOT, 'client3d/src/scene/waterfall.ts'), 'utf8');
const groundSrc = await readFile(
  join(ROOT, 'client3d/src/scene/ground.ts'), 'utf8');
const lodSrc = await readFile(
  join(ROOT, 'client3d/src/scene/terrainLod.ts'), 'utf8');
const matSrc = await readFile(
  join(ROOT, 'packages/scene-render/src/materials.ts'), 'utf8');
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

// ── [9] the curtain hangs in FRONT of the wet face (2026-08-24) ─────────────
console.log('\n[9] the sheet clears the wet face the terrain draws behind it');
check('the sheet spans the fall\'s own chord, from the LIP',
  /const halfRun = Math\.max\(fall\.chordM, 0\) \* 0\.5;/.test(fallSrc)
  && /const topX = fall\.x - fall\.dirX \* halfRun;/.test(fallSrc) ? 1 : 0, 1);
check('…and its foot leans the full WATERFALL_LEAN · h past the face\'s foot',
  /const lean = WATERFALL_LEAN \* height;/.test(fallSrc)
  && /const botX = fall\.x \+ fall\.dirX \* \(halfRun \+ lean\);/.test(fallSrc)
    ? 1 : 0, 1);
check('RED: the old half-lean about the midpoint is gone',
  /WATERFALL_LEAN \* height \* 0\.5/.test(fallSrc) ? 1 : 0, 0);
// The four numbers of the docstring, on the plan's fixture.
const H9 = fall.topY - fall.bottomY;          // 5.8
const halfRun9 = fall.chordM * 0.5;           // 1.5
const lean9 = 0.3 * H9;                       // 1.74
check('the lean over a 5.8 m fall is', lean9, 1.74, 1e-12);
check('the top corner lands ON the lip knot B (x)',
  fall.x - fall.dirX * halfRun9, 20, 1e-12);
check('…and (z)', fall.z - fall.dirZ * halfRun9, 0, 1e-12);
check('the foot lands here (x)',
  fall.x + fall.dirX * (halfRun9 + lean9), 22.844, 1e-12);
check('…and (z)', fall.z + fall.dirZ * (halfRun9 + lean9), -3.792, 1e-12);
check('…i.e. exactly the lean downstream of the face\'s foot, knot C',
  Math.hypot(fall.x + fall.dirX * (halfRun9 + lean9) - 21.8,
             fall.z + fall.dirZ * (halfRun9 + lean9) + 2.4), 1.74, 1e-12);
// The clearance r_new(u) − r_face(u) = lean·(1 − u): never negative.
const rFace = (u) => halfRun9 * (1 - 2 * u);
const rNew = (u) => -halfRun9 * u + (halfRun9 + lean9) * (1 - u);
check('clearance at the pool (u = 0)', rNew(0) - rFace(0), 1.74, 1e-12);
check('…halfway up (u = 0.5)', rNew(0.5) - rFace(0.5), 0.87, 1e-12);
check('…and at the lip (u = 1), where the shader fades the sheet out anyway',
  rNew(1) - rFace(1), 0, 1e-12);
let behind = 0;
for (let i = 0; i <= 100; i += 1) if (rNew(i / 100) - rFace(i / 100) < 0) behind += 1;
check('RED: not one of 101 heights stands behind the face', behind, 0);
// …and the state that was measured: the old sheet, half of it inside the hill.
const rOld = (u) => 0.3 * H9 * 0.5 * (1 - 2 * u);
check('RED: the OLD foot stood this far INSIDE the wall',
  rOld(0) - rFace(0), -0.63, 1e-12);
let oldBehind = 0;
for (let i = 0; i <= 100; i += 1) if (rOld(i / 100) - rFace(i / 100) < 0) oldBehind += 1;
check('RED: …and exactly half its height was occluded', oldBehind, 50);
// The texture suspicion, refuted at the source: the ONE shared map repeats.
check('the shared wave map repeats — the curtain tiles it 2.4 x 2.32 times',
  /tex\.wrapS = tex\.wrapT = T\.RepeatWrapping/.test(matSrc) ? 1 : 0, 1);
check('…and the curtain really does tile it by width and height over 2.5 m',
  /fall\.width \/ WATERFALL_WAVE_M, height \/ WATERFALL_WAVE_M/.test(fallSrc)
    ? 1 : 0, 1);
check('the foam radius grows with the fall',
  /WATERFALL_FOAM_RADIUS_PER_M \* heightM/.test(fallSrc) ? 1 : 0, 1);
check('…and is never narrower than the stream itself',
  /Math\.max\(fall\.width \* 0\.5,/.test(fallSrc) ? 1 : 0, 1);
check('the foam is the SHORE\'s own white, not a second one',
  /WATER_FOAM_STRENGTH/.test(fallSrc) ? 1 : 0, 1);
check('the curtain takes THE wave normal map of the process, by name',
  /const map = surfaceWaveNormal\(THREE\)/.test(fallSrc) ? 1 : 0, 1);
check('…the same one the terrain\'s water pixels scroll (K-A E4)',
  /uWave\.value = surfaceWaveNormal\(THREE\)/.test(lodSrc) ? 1 : 0, 1);
check('RED: no second wave texture is built here',
  /makeWaveNormal|createCanvas|CanvasTexture/.test(fallSrc) ? 1 : 0, 0);
check('RED: …and it is not read off some other material any more',
  /normalMap|waterMat/.test(fallSrc) ? 1 : 0, 0);
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
console.log('\n[8b] and it lives exactly as long as its painted area does');
check('the falls are read off the very profile the water level comes from',
  /waterfallsFrom\(profile, strokeWidthM\(area\.meta\)\)/.test(groundSrc)
    ? 1 : 0, 1);
check('their meshes join the waterfall list, which `clearAreas` empties',
  /nextFalls\.push\(\.\.\.buildWaterfall\(fall, nextOwned\)\)/
    .test(groundSrc) ? 1 : 0, 1);
check('…and their materials the area\'s disposal bag',
  /sink\.push\(curtainMat\);/.test(fallSrc)
  && /sink\.push\(foamMat\);/.test(fallSrc) ? 1 : 0, 1);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
