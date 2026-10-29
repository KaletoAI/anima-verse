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
 * [7a] THE VERTICAL EXAGGERATION — the number both 2D maps shade with
 * ============================================================================
 * `zFactor` multiplies BOTH gradient components before anything else, so it
 * tilts the surface rather than gaining the output. The 2D maps read the
 * OVERVIEW grid, which coarsens to as much as 32 m per cell, and a 5 m hill on
 * such a cell contributes about one of 255 steps to the finished picture —
 * hence `MAP_RELIEF_Z_FACTOR` = 3 in both consumers.
 *
 * RAMP A AT zFactor 3: hx = hz = 3 · 0.5 = 1.5.
 *   len = √(2.25 + 2.25 + 1) = √5.5 = 2.34520788
 *   N·L = (−1.5·(−0.5) + 0.70710678 + (−1.5)·(−0.5)) / 2.34520788
 *       = 2.20710678 / 2.34520788 = 0.94111349
 *   grey  = round(255 · 0.5 · 0.94111349/0.70710678)
 *         = round(255 · 0.66546773) = round(169.69427) = 170
 *   grad = √4.5 = 2.12132034, grad/len = √(4.5/5.5) = 0.90453403
 *   alpha = round(255 · 0.35 · 0.90453403) = round(80.72967) = 81
 *
 * The GREY FELL (178 → 170) and that is not a defect: at hx = hz = 1.5 the ramp
 * has tipped PAST the lamp's own slope (section [4]: the brightest face is the
 * one at 0.70710678), so Lambert brings it down again. The alpha is where the
 * exaggeration pays — 52 → 81 — and on the case a map is actually about, a
 * hill against its own back side, both do:
 *
 * THE PEAK AT zFactor 3 (heights [[0,0,0],[0,1,0],[0,0,0]], step 2):
 *   NORTH FLANK (1, 0): hx = 0, hz = 3 · 0.5 = 1.5, len = √3.25 = 1.80277564
 *       N·L = (0.70710678 + 0.75)/1.80277564 = 1.45710678/1.80277564
 *           = 0.80825740
 *       grey  = round(255 · 0.57152429) = round(145.73869) = 146
 *       alpha = round(255 · 0.35 · 1.5/1.80277564) = round(89.25 · 0.83205029)
 *             = round(74.26049) = 74
 *   SOUTH FLANK (1, 2): hz = −1.5, so N·L = (0.70710678 − 0.75)/1.80277564
 *       = −0.02379 — NEGATIVE. The face has turned more than 45° away from a
 *       lamp standing 45° up, so it lies in its own shadow: lit = 0, grey 0,
 *       alpha 74 unchanged (steepness, not aspect).
 *   The measured contrast north − south therefore goes from 154 − 74 = 80 to
 *   146 − 0 = 146, at nearly twice the opacity. THAT is what the factor buys.
 *
 * COUNTER-PROBE, and the one that keeps this an addition rather than a change:
 * `zFactor` 1 must be the value the file already answered — 178/52 on ramp A,
 * 154/40 on the peak's north flank. `zFactor` 0 flattens the world (128/0
 * everywhere, exactly the flat field of section [2]), and a NEGATIVE factor is
 * clamped to 0 instead of mirroring the ground: −3 would read every hill as a
 * hollow, which is the very defect section [7] exists to catch.
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

// Task 55 / E7-T10: the hand derivations above feed ONE shared expectation file.
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const { hillshadeImage } = await loadModule(SRC, 'hillshade');
const result = runVectors(loadVectors('hillshade'), {
  hillshadeImage(field, opts) {
    const image = hillshadeImage(field, opts);
    return image ? { ...image, data: Array.from(image.data) } : null;
  },
  hillshadePixel(field, opts, i, j) {
    const image = hillshadeImage(field, opts);
    return Array.from(image.data.slice((j * image.cols + i) * 4, (j * image.cols + i) * 4 + 4));
  },
});
console.log(`\n${result.passed + result.failed} shared vectors, ${result.failed} failures`);
process.exit(result.failed ? 1 : 0);
