#!/usr/bin/env node
/**
 * Smoke check for the shared HILLSHADE layer —
 * `packages/scene-render/src/hillshade.ts`.
 *
 * Usage:  node client3d/scripts/smoke_hillshade.mjs
 *
 * Every number below is derived BY HAND from the formulas in that file's
 * header and never recorded from its output. A check that only writes down what
 * the code currently answers proves nothing about a shading whose only failure
 * mode is looking subtly wrong.
 *
 * ============================================================================
 * THE LAMP
 * ============================================================================
 * World axes (§ A1.8): x runs EAST, z runs SOUTH, y is up — so north is −z and
 * west is −x. The cartographic azimuth runs FROM NORTH, CLOCKWISE (N = 0,
 * E = 90, S = 180, W = 270), the horizontal unit vector towards A is
 * (sin A, −cos A), and the vector from the ground towards the lamp is
 *
 *     L = (cos alt · sin A,  sin alt,  −cos alt · cos A)
 *
 * At the defaults A = 315, alt = 45 (cos 45 = sin 45 = √2⁄2 = 0.70710678):
 *
 *     L = (0.70710678 · (−0.70710678), 0.70710678, −0.70710678 · 0.70710678)
 *       = (−0.5, 0.70710678, −0.5)
 *
 * i.e. towards WEST and NORTH — the north-west, as the azimuth says. Everything
 * below follows from that vector; nothing was tried out.
 *
 * The surface normal is N = (−hx, 1, −hz)/√(hx² + hz² + 1), the gradient a
 * central difference inside the field and one-sided at its borders, and
 *
 *     grey  = round(255 · min(½ · max(N·L, 0) / sin alt, 1))
 *     alpha = round(255 · maxAlpha · √(hx² + hz²) / √(hx² + hz² + 1))
 *
 * with maxAlpha = 0.35. Level ground: N·L = sin alt, so grey = round(127.5) =
 * 128 and alpha = 0 — the neutral pixel, at EVERY altitude.
 *
 * ============================================================================
 * [3] THE TWO RAMPS — the case the whole layer stands or falls on
 * ============================================================================
 * RAMP A, falling towards the north-west: origin (0, 0), step 2, 3 × 3 with
 * heights[j][i] = i + j, i.e. h(x, z) = (x + z)/2 and hx = hz = 0.5.
 * A PLANE IS REPRODUCED BY BOTH DIFFERENCES — central inside ((3−1)/4 = 0.5),
 * one-sided at the border ((1−0)/2 = 0.5) — so all nine pixels are identical,
 * which is itself the border-rule check.
 *
 *   √(0.25 + 0.25 + 1) = √1.5 = 1.22474487
 *   N·L = (−0.5·(−0.5) + 1·0.70710678 + (−0.5)·(−0.5)) / 1.22474487
 *       = 1.20710678 / 1.22474487 = 0.98559856
 *   grey  = round(255 · 0.5 · 0.98559856 / 0.70710678)
 *         = round(255 · 0.69692342) = round(177.71547) = 178
 *   grad = √0.5 = 0.70710678, grad/len = 0.70710678/1.22474487 = 0.57735027
 *   alpha = round(255 · 0.35 · 0.57735027) = round(51.52851) = 52
 *
 * RAMP B, the mirror, falling towards the south-east: heights[j][i] = −(i + j),
 * so hx = hz = −0.5 and only the two signs in the dot product turn:
 *
 *   N·L = (−0.25 + 0.70710678 − 0.25) / 1.22474487 = 0.16910198
 *   grey  = round(255 · 0.11957315) = round(30.49115) = 30
 *   alpha = 52, unchanged — the slope is the same steepness, only its ASPECT
 *           turned, and the alpha carries steepness alone.
 *
 * 178 against 30 IS "the north-west flank is brighter", and it comes out of L
 * pointing north-west, not out of trying both.
 *
 * ============================================================================
 * [4] THE LAMP'S OWN SLOPE
 * ============================================================================
 * The brightest ground there is, and the cleanest arithmetic in the file: a
 * ramp with hx = hz = 1/√2 (step 2, heights[j][i] = (i + j)·√2) has
 *
 *   N = (−1/√2, 1, −1/√2)/√2 = (−0.5, 0.70710678, −0.5) = L exactly
 *
 * so N·L = 1 (a unit vector on itself), grey = round(255 · 0.5/0.70710678) =
 * round(180.31223) = 180 and, with grad = 1 and len = √2,
 * alpha = round(255 · 0.35 · 0.70710678) = round(63.09) = 63.
 *
 * AND A STEEPER SLOPE IS DARKER AGAIN, which is Lambert and not a bug: at
 * hx = hz = 5 the face has tipped atan(√50) = 82° over and swung most of the
 * way past the lamp, so with √51 = 7.14142843
 *
 *   N·L = (2.5 + 0.70710678 + 2.5)/7.14142843 = 5.70710678/7.14142843
 *       = 0.79914722
 *   grey  = round(255 · 0.56508537) = round(144.09677) = 144
 *   alpha = round(255 · 0.35 · √50/7.14142843) = round(88.37067) = 88
 *
 * — 144 is BELOW the 178 of the gentle ramp A, while the opacity has risen from
 * 52 to 88. The brightest slope is the one FACING the lamp, never the steepest;
 * only the alpha grows with steepness.
 *
 * ============================================================================
 * [5] A PEAK — where the four flanks land
 * ============================================================================
 * origin (0, 0), step 2, heights [[0,0,0],[0,1,0],[0,0,0]] — one metre on the
 * middle support point (2, 2).
 *
 *   SUMMIT (i = 1, j = 1): both central differences run between two zeros
 *       ((0−0)/4), so the gradient is 0 → 128 / 0. A summit is LEVEL, and a
 *       level pixel is invisible whatever stands under it.
 *   NORTH FLANK (1, 0): hx = (0−0)/4 = 0; hz one-sided = (1−0)/2 = 0.5, so the
 *       ground rises towards the south and the face looks NORTH — at the lamp.
 *       √(0.25 + 1) = 1.11803399
 *       N·L = (0.70710678 + (−0.5)·(−0.5)) / 1.11803399
 *           = 0.95710678 / 1.11803399 = 0.85606233
 *       grey  = round(255 · 0.60532747) = round(154.35851) = 154
 *       alpha = round(255 · 0.35 · 0.5/1.11803399) = round(39.91381) = 40
 *   SOUTH FLANK (1, 2): hz = (0−1)/2 = −0.5, the face turned away:
 *       N·L = (0.70710678 − 0.25)/1.11803399 = 0.40884873
 *       grey  = round(255 · 0.28909972) = round(73.72043) = 74, alpha 40
 *   WEST FLANK (0, 1): hx one-sided = (1−0)/2 = 0.5, hz central = (0−0)/4 = 0 —
 *       and its N·L is the NORTH flank's number to the digit, because the lamp
 *       stands on the north-west diagonal and a west face is exactly as tilted
 *       towards it as a north face. 154 / 40, by symmetry rather than by luck.
 *   EAST FLANK (2, 1): the same mirror the other way — 74 / 40.
 *   CORNERS: every neighbour is 0 → 128 / 0.
 *
 * ============================================================================
 * [6] RED COUNTER-PROBE — the lamp moved to the south-east
 * ============================================================================
 * A = 135: L = (0.70710678·0.70710678, 0.70710678, −0.70710678·(−0.70710678))
 * = (0.5, 0.70710678, 0.5), towards east and south. Ramp A's dot product
 * becomes (−0.25 + 0.70710678 − 0.25)/1.22474487 = 0.16910198 — EXACTLY ramp
 * B's value under the north-west lamp, and the other way round. The two greys
 * trade places, 178 ↔ 30, while both alphas stay 52: moving the lamp changes
 * which flank is lit, never how steep it is. A hillshade whose brightness did
 * NOT swap here is not reading the azimuth at all.
 *
 * ============================================================================
 * [7] RED COUNTER-PROBE — the gradient's sign, i.e. hill against hollow
 * ============================================================================
 * Negate the peak field and the same ground is a pit. Every gradient flips, so
 * the north flank falls to 74 and the south flank rises to 154: the measured
 * difference north − south goes from +80 to −80. THAT SIGN is the entire
 * convention. Flip the gradient (or the normal, or the lamp) once and every
 * hill on the map reads as a hollow — the one hillshade defect a reader cannot
 * un-see, and the reason this is a signed check and not a "looks about right".
 *
 * ============================================================================
 * [8] THE OPTIONS, AND [9] WHAT A BROKEN PAYLOAD DOES
 * ============================================================================
 * maxAlpha scales the alpha and nothing else (0 → the layer is invisible but
 * still grey; 1 → round(255 · 0.57735027) = round(147.22432) = 147 on ramp A).
 * The azimuth wraps: −45 and 675 are 315. The altitude is clamped above the
 * horizon, and a flat cell answers 128 at any of them.
 *
 * A field with fewer than 2 × 2 support points, a non-positive step, the empty
 * world, `null` and `undefined` all answer `null` — the consumers then draw
 * NOTHING, not a transparent rectangle. A ragged row reads its gaps as 0 (the
 * reading `sampleWorldHeight` gives them), and `rows`/`cols` lying about the
 * array changes nothing: the shape comes from the data.
 *
 *   RAGGED heights [[0, 10], [0]], origin (0, 0), step 4, pixel (0, 0):
 *     hx = (10 − 0)/4 = 2.5, hz = (0 − 0)/4 = 0, len = √7.25 = 2.69258240
 *     N·L = (2.5·0.5 + 0.70710678)/2.69258240 = 1.95710678/2.69258240
 *         = 0.72685773
 *     grey  = round(255 · 0.51396634) = round(131.06016) = 131
 *     alpha = round(255 · 0.35 · 2.5/2.69258240) = round(82.86654) = 83
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/hillshade.ts');

/** Transpile one module without a RUNTIME import and load it. `hillshade.ts`
 *  carries a type-only import of `WorldHeightField`, which esbuild erases —
 *  add a real one and this fails loudly, which is the alarm. */
async function loadModule(path, name) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'hillshade-'));
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
function check(label, actual, expected) {
  const ok = actual === expected;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}

/** One pixel of the image as `[r, g, b, a]`. The row is the field's row, so
 *  (i, j) is the support point (origin_x + i·step, origin_z + j·step). */
function pixel(img, i, j) {
  const p = (j * img.cols + i) * 4;
  return [img.data[p], img.data[p + 1], img.data[p + 2], img.data[p + 3]];
}

/** A pixel against its hand-derived grey and alpha. The three colour channels
 *  must be the SAME number — the layer is a neutral grey, never a tint. */
function checkPixel(label, img, i, j, grey, alpha) {
  const [r, g, b, a] = pixel(img, i, j);
  const ok = r === grey && g === grey && b === grey && a === alpha;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = grey ${grey}, alpha ${alpha}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected grey ${grey}, alpha ${alpha}`
      + `\n       actual   [${r}, ${g}, ${b}, ${a}]`);
  }
}

const { hillshadeImage } = await loadModule(SRC, 'hillshade');

/** A 3 × 3 field at origin (0, 0) with step 2 — the geometry of every field in
 *  sections [2] to [7]; only the heights differ. */
function field3(fn) {
  const heights = [];
  for (let j = 0; j < 3; j += 1) {
    const row = [];
    for (let i = 0; i < 3; i += 1) row.push(fn(i, j));
    heights.push(row);
  }
  return { origin_x: 0, origin_z: 0, step_m: 2, rows: 3, cols: 3, heights };
}

console.log('[1] the shape of the answer');
const FLAT = field3(() => 0);
const flatImg = hillshadeImage(FLAT);
check('columns', flatImg.cols, 3);
check('rows', flatImg.rows, 3);
check('four bytes per support point', flatImg.data.length, 3 * 3 * 4);
check('and they are clamped bytes', flatImg.data instanceof Uint8ClampedArray, true);

console.log('[2] the flat world is left exactly as it is drawn today');
for (let j = 0; j < 3; j += 1) {
  for (let i = 0; i < 3; i += 1) {
    checkPixel(`flat (${i}, ${j})`, flatImg, i, j, 128, 0);
  }
}

console.log('[3] the two ramps — north-west bright, south-east dark');
const RAMP_NW = field3((i, j) => i + j);
const RAMP_SE = field3((i, j) => -(i + j));
const nwImg = hillshadeImage(RAMP_NW);
const seImg = hillshadeImage(RAMP_SE);
// A plane comes out uniform, borders included: that IS the one-sided rule.
for (let j = 0; j < 3; j += 1) {
  for (let i = 0; i < 3; i += 1) {
    checkPixel(`the NW-facing plane at (${i}, ${j})`, nwImg, i, j, 178, 52);
  }
}
checkPixel('the SE-facing plane (centre)', seImg, 1, 1, 30, 52);
checkPixel('...and at a border, where the difference is one-sided',
  seImg, 0, 0, 30, 52);
check('the north-west flank is the brighter one',
  pixel(nwImg, 1, 1)[0] > pixel(seImg, 1, 1)[0], true);
check('...and both carry the same opacity, the slope being the same',
  pixel(nwImg, 1, 1)[3] === pixel(seImg, 1, 1)[3], true);

console.log("[4] the lamp's own slope, and the one steeper than it");
const FACING = field3((i, j) => (i + j) * Math.SQRT2);
checkPixel('a face whose normal IS the light vector', hillshadeImage(FACING), 1, 1,
  180, 63);
const STEEP = field3((i, j) => (i + j) * 10);
checkPixel('ten times as steep, and darker again — that is Lambert',
  hillshadeImage(STEEP), 1, 1, 144, 88);
check('...darker than the gentle ramp facing the same way',
  pixel(hillshadeImage(STEEP), 1, 1)[0] < pixel(nwImg, 1, 1)[0], true);
check('...while its opacity did rise with the steepness',
  pixel(hillshadeImage(STEEP), 1, 1)[3] > pixel(nwImg, 1, 1)[3], true);

console.log('[5] a peak — the four flanks and the level summit');
const PEAK = field3((i, j) => (i === 1 && j === 1 ? 1 : 0));
const peakImg = hillshadeImage(PEAK);
checkPixel('the summit is level, so nothing is painted', peakImg, 1, 1, 128, 0);
checkPixel('the north flank looks at the lamp', peakImg, 1, 0, 154, 40);
checkPixel('the west flank catches exactly as much', peakImg, 0, 1, 154, 40);
checkPixel('the south flank is turned away', peakImg, 1, 2, 74, 40);
checkPixel('and so is the east flank', peakImg, 2, 1, 74, 40);
checkPixel('the north-west corner has no neighbour that moves', peakImg, 0, 0, 128, 0);
checkPixel('nor the south-east one', peakImg, 2, 2, 128, 0);

console.log('[6] RED COUNTER-PROBE: the lamp moved to the south-east');
const SE_LAMP = { azimuthDeg: 135 };
checkPixel('the NW-facing plane is now the dark one',
  hillshadeImage(RAMP_NW, SE_LAMP), 1, 1, 30, 52);
checkPixel('...and the SE-facing plane the bright one',
  hillshadeImage(RAMP_SE, SE_LAMP), 1, 1, 178, 52);
check('the two greys traded places exactly',
  pixel(hillshadeImage(RAMP_NW, SE_LAMP), 1, 1)[0] === pixel(seImg, 1, 1)[0], true);

console.log('[7] RED COUNTER-PROBE: the sign of the gradient — hill or hollow');
const HOLLOW = field3((i, j) => (i === 1 && j === 1 ? -1 : 0));
const hollowImg = hillshadeImage(HOLLOW);
checkPixel('the pit\'s northern wall is the dark one', hollowImg, 1, 0, 74, 40);
checkPixel('...and its southern wall the lit one', hollowImg, 1, 2, 154, 40);
check('the hill reads north minus south as',
  pixel(peakImg, 1, 0)[0] - pixel(peakImg, 1, 2)[0], 80);
check('...and the hollow as the very same number, negated',
  pixel(hollowImg, 1, 0)[0] - pixel(hollowImg, 1, 2)[0], -80);

console.log('[8] the options');
checkPixel('maxAlpha 0 hides the layer without touching its greys',
  hillshadeImage(RAMP_NW, { maxAlpha: 0 }), 1, 1, 178, 0);
checkPixel('maxAlpha 1 is the same shading at full strength',
  hillshadeImage(RAMP_NW, { maxAlpha: 1 }), 1, 1, 178, 147);
checkPixel('a negative maxAlpha is clamped to 0',
  hillshadeImage(RAMP_NW, { maxAlpha: -3 }), 1, 1, 178, 0);
checkPixel('the azimuth wraps below zero', hillshadeImage(RAMP_NW, { azimuthDeg: -45 }),
  1, 1, 178, 52);
checkPixel('...and above a full turn', hillshadeImage(RAMP_NW, { azimuthDeg: 675 }),
  1, 1, 178, 52);
checkPixel('a lamp on the horizon is clamped above it, and level ground stays neutral',
  hillshadeImage(FLAT, { altitudeDeg: 0 }), 1, 1, 128, 0);
checkPixel('a lamp straight overhead: level ground is still the neutral grey',
  hillshadeImage(FLAT, { altitudeDeg: 90 }), 1, 1, 128, 0);
checkPixel('rubbish falls back to the default lamp',
  hillshadeImage(RAMP_NW, { azimuthDeg: NaN, altitudeDeg: undefined, maxAlpha: NaN }),
  1, 1, 178, 52);

console.log('[9] fields that carry no relief answer null');
check('no field at all', hillshadeImage(null), null);
check('undefined', hillshadeImage(undefined), null);
check('the empty world as the endpoint sends it', hillshadeImage(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 0, cols: 0, heights: [] }), null);
check('a single row has no gradient across it', hillshadeImage(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 1, cols: 3, heights: [[1, 2, 3]] }), null);
check('a single column neither', hillshadeImage(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 3, cols: 1, heights: [[1], [2], [3]] }),
  null);
check('step 0 is no grid', hillshadeImage(
  { origin_x: 0, origin_z: 0, step_m: 0, rows: 2, cols: 2, heights: [[1, 1], [1, 1]] }),
  null);

console.log('[9a] a ragged field is a shading, not a crash');
const RAGGED = hillshadeImage(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 2, cols: 2, heights: [[0, 10], [0]] });
check('the shape comes from the array', `${RAGGED.cols}x${RAGGED.rows}`, '2x2');
checkPixel('the gap reads as 0, like every other reader of this field',
  RAGGED, 0, 0, 131, 83);
const LYING = hillshadeImage(
  { origin_x: 0, origin_z: 0, step_m: 4, rows: 99, cols: 99, heights: [[0, 10], [0]] });
check('rows/cols lying about the array change nothing',
  `${LYING.cols}x${LYING.rows}`, '2x2');
checkPixel('...not one pixel of it', LYING, 0, 0, 131, 83);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
