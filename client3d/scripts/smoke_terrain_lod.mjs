#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/terrain_lod.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_terrain_lod.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { vectorCase, vectorArgs, vectorValue } from './e3VectorSupport.mjs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/**
 * A THREE.js stand-in, so a module that draws can still be checked as maths.
 *
 * `terrainLod.ts` allocates exactly two kinds of three object while it LOADS —
 * the neutral height texture and the level uniform array — and nothing else in
 * this file ever touches three. The stub therefore has to answer for those two
 * and no more; anything the module started using beyond them would fail here
 * loudly, which is the alarm this arrangement exists for.
 */
const THREE_STUB = `
export class DataTexture {
  constructor(data, w, h, format, type) {
    this.image = { data, width: w, height: h };
    this.format = format;
    this.type = type;
  }
  dispose() {}
}
export class Vector4 {
  constructor(x = 0, y = 0, z = 0, w = 0) { this.set(x, y, z, w); }
  set(x, y, z, w) { this.x = x; this.y = y; this.z = z; this.w = w; return this; }
}
export class CanvasTexture {
  constructor(image) { this.image = image; }
  dispose() {}
}
export const RedFormat = 1022;
export const FloatType = 1015;
export const NearestFilter = 1003;
export const ClampToEdgeWrapping = 1001;
`;

/**
 * The one piece of DOM the water variant touches: the shared wave normal map
 * is drawn onto a 256² canvas (`@anima/scene-render materials.makeWaveNormal`)
 * the first time a water program is compiled, and [16] compiles one. The stub
 * takes the pixels and throws them away — what is checked here is the SHADER,
 * never the map.
 */
if (typeof globalThis.document === 'undefined') {
  globalThis.document = {
    createElement: () => ({
      width: 0,
      height: 0,
      getContext: () => ({
        fillStyle: '',
        fillRect() {},
        putImageData() {},
        createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
      }),
    }),
  };
}

/**
 * Transpile a module and import it, with `three` and `@anima/scene-render`
 * resolved to local files.
 *
 * The package entry is a two-line BARREL over the two files `terrainLod.ts`
 * really takes something from — `worldHeight.ts` (the lattice sampler) and,
 * since K-A E4, `materials.ts` (the shared wave map, the shared sky and the
 * shared clock). Both are three-free at RUNTIME: materials.ts imports three
 * only as a TYPE, which esbuild erases, so no stub is needed and the constants
 * the water look falls back to are the REAL ones. Pointing at the real barrel
 * instead would drag three back in through the front door.
 *
 * `waterRaster.ts`, `waterPlaneMath.ts` and `waterShade.ts` come along as local
 * siblings: all three are pure arithmetic over the wire shape and over the
 * shore curves, so they load under exactly the same rules.
 *
 * `layerGround.ts` is STUBBED and not transpiled. `terrainLod.ts` takes exactly
 * one function from it (the borrowed id-mask uniforms, K-A E4) and that file
 * pulls in three, the texture library and the DOM — a wiring line, checked by
 * `npm run build -w client3d` and by nothing that could be derived by hand.
 */
async function loadLod() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'terrainlod-'));
  try {
    const ts = async (src, name) => {
      const code = await readFile(src, 'utf8');
      await writeFile(join(dir, `${name}.mjs`),
        esbuild.transformSync(code, { loader: 'ts', format: 'esm' }).code
          .replace(/from\s*["']@anima\/scene-render["']/g, "from './sceneRender.mjs'")
          .replace(/from\s*["']\.\/([A-Za-z]+)["']/g, "from './$1.mjs'"),
        'utf8');
    };
    await writeFile(join(dir, 'three.mjs'), THREE_STUB, 'utf8');
    await writeFile(join(dir, 'sceneRender.mjs'),
      "export * from './worldHeight.mjs';\nexport * from './materials.mjs';\nexport * from './waterExtras.mjs';\n", 'utf8');
    await ts(join(ROOT, 'packages/scene-render/src/worldHeight.ts'), 'worldHeight');
    await ts(join(ROOT, 'packages/scene-render/src/materials.ts'), 'materials');
    await ts(join(ROOT, 'packages/scene-render/src/waterExtras.ts'), 'waterExtras');
    await ts(join(ROOT, 'client3d/src/scene/waterRaster.ts'), 'waterRaster');
    await ts(join(ROOT, 'client3d/src/scene/waterPlaneMath.ts'), 'waterPlaneMath');
    await ts(join(ROOT, 'client3d/src/scene/waterShade.ts'), 'waterShade');
    const src = await readFile(join(ROOT, 'client3d/src/scene/terrainLod.ts'), 'utf8');
    const out = esbuild.transformSync(src, { loader: 'ts', format: 'esm' }).code
      .replace(/from\s*["']three["']/g, "from './three.mjs'")
      // NO `layerGround` STUB ANY MORE (bake v10): the terrain's water variant
      // stopped borrowing the ground compositor's id mask when the water raster
      // started naming its own kind per texel, so this module has no import of
      // it left to satisfy.
      .replace(/from\s*["']\.\/(waterRaster|waterShade)["']/g,
               "from './$1.mjs'")
      .replace(/from\s*["']@anima\/scene-render["']/g, "from './sceneRender.mjs'");
    await writeFile(join(dir, 'terrainLod.mjs'), out, 'utf8');
    return {
      lod: await import(`file://${join(dir, 'terrainLod.mjs')}`),
      height: await import(`file://${join(dir, 'worldHeight.mjs')}`),
      water: await import(`file://${join(dir, 'waterRaster.mjs')}`),
      shade: await import(`file://${join(dir, 'waterShade.mjs')}`),
      mats: await import(`file://${join(dir, 'materials.mjs')}`),
      extras: await import(`file://${join(dir, 'waterExtras.mjs')}`),
    };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function vector(label, fns) {
  const result = vectorCase("terrain_lod", label, fns);
  passed += result.passed; failed += result.failed;
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
function checkBelow(label, actual, ceiling) {
  const ok = typeof actual === 'number' && actual >= 0 && actual < ceiling;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (< ${ceiling})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected < ${ceiling}\n       actual   ${actual}`);
  }
}
function checkAbove(label, actual, floor) {
  const ok = typeof actual === 'number' && actual > floor;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (> ${floor})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected > ${floor}\n       actual   ${actual}`);
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

const { lod, height, water, shade, mats, extras } = await loadLod();
const { PATCH_N, MAX_LOD_LEVELS, MIN_LOD_DISTANCE_M, MAX_NODES, MORPH_START, MAX_PIXEL_ERROR,
  MAX_RANGE_WIDENING,
  buildPyramid, pyramidHeight, pyramidLevelFor, lodRanges, selectLodNodes,
  morphedVertex, lodLambda, lodVertex, nodeBounds, terrainLodGlsl, selectLodFitted,
  levelErrorsFrom,
  terrainLodNormalGlsl, fragmentNormal, gpuHeightAt,
  buildWaterPyramid, wlevelAt, bindTerrainLodUniforms,
  terrainLodWaterGlsl, nodeHasWater, liftedHeight, liftedDepth, gpuWaterAt,
  gpuWaterSdAt, gpuWaterFlowAt,
  patchTerrainLod, LOD_CAP_NONE, waterTileCaps, buildLodCapGrid, lodCapAt,
  lodCapOverSquare,
  TERRAIN_LOD_CACHE_KEY, TERRAIN_LOD_WATER_CACHE_KEY } = lod;
const { heightAt, rayGroundHit, sampleWorldHeight } = height;
const { emptyWaterRaster, rasterLevelAt, rasterSdAt, waterTileFrom,
        WATER_SD_DRY } = water;
// The GATE (finding G1) is one shared GLSL text and one shared curve, so the
// checks below read it from `waterShade` and never re-spell it here.
const { waterGateGlsl, terrainWaterFragmentGlsl, WATER_SD_BAND_M } = shade;

/** An `SdField` over a lattice, from a per-x function — the shape `buildSd`
 *  produces in the renderer, built here by hand so the twin is fed the very
 *  numbers the shader fetches. */
function sdFieldFrom(at, originX, originZ, step, cols, rows) {
  const data = new Float32Array(cols * rows);
  for (let j = 0; j < rows; j += 1) {
    for (let i = 0; i < cols; i += 1) {
      data[j * cols + i] = at(originX + i * step, originZ + j * step);
    }
  }
  return { originX, originZ, step, cols, rows, data };
}

// ── [1] the constants ───────────────────────────────────────────────────────
console.log('[1] the constants are derived from the server\'s own pyramid');
const BASE = 2;
check('cells per patch axis', PATCH_N, 32);
check('levels', MAX_LOD_LEVELS, 6);
check('lodRange[0]', MIN_LOD_DISTANCE_M, 128);
check('the morph starts at half a range', MORPH_START, 0.5);
check('the pixel budget', MAX_PIXEL_ERROR, 2);
const stepsPerLevel = [];
for (let i = 0; i < MAX_LOD_LEVELS; i += 1) stepsPerLevel.push(BASE * (1 << i));
checkEq('(a) the node grid steps at a 2 m base', stepsPerLevel, [2, 4, 8, 16, 32, 64]);
// The server's own list, read out of the Python so the two cannot drift.
const heightfieldPy = await readFile(join(ROOT, 'app/core/heightfield.py'), 'utf8');
const mipLine = /MIP_LEVELS_M = \(([^)]*)\)/.exec(heightfieldPy);
const serverMips = mipLine[1].split(',').map((s) => Number(s.trim())).filter((n) => n > 0);
checkEq('(b) levels 1..5 ARE the server\'s MIP_LEVELS_M', stepsPerLevel.slice(1), serverMips);
check('the leaf node edge', PATCH_N * BASE, 64);
check('the root node edge', PATCH_N * BASE * (1 << (MAX_LOD_LEVELS - 1)), 2048);
check('(c) vertices per patch', (PATCH_N + 1) ** 2, 1089);
check('…index entries', PATCH_N * PATCH_N * 6, 6144);
// The shader fetches, it does not filter: R32F is not filterable in core
// WebGL2, and a driver that DID filter it would round the weights its own way.
const glsl = terrainLodGlsl();
// EIGHT since F1: the height's four, and the four corners of the water's mip
// cap that the morph clamps λ against (`tlodCapAt`, [18]). Both are hand mixes
// for the same reason.
check('the shader fetches texels', glsl.split('texelFetch(').length - 1, 8);
checkEq('…and never asks a sampler to filter', glsl.includes('texture2D('), false);
checkEq('…nor the GLSL3 spelling of it', /\btexture\s*\(/.test(glsl), false);

// ── [2] the pyramid ─────────────────────────────────────────────────────────
console.log('\n[2] the pyramid is decimation — the SAME function, coarser');
const ARB = (x, z) => (((7 * (x / 2) + 13 * (z / 2)) % 11) - 5);
const arb = buildPyramid(ARB, 0, 0, 2, 5, 5, MAX_LOD_LEVELS);
check('levels', arb.levels.length, 3);
check('texture width', arb.texW, 5);
check('texture height', arb.texH, 10);
checkEq('the level shapes', arb.levels.map((l) => [l.cols, l.rows, l.step, l.row0]),
  [[5, 5, 2, 0], [3, 3, 4, 5], [2, 2, 8, 8]]);
check('texels held', arb.data.length, 50);
// (d) every coarse support point reads what level 0 reads there
let worst = 0;
for (let k = 1; k < arb.levels.length; k += 1) {
  const lv = arb.levels[k];
  for (let j = 0; j < lv.rows; j += 1) {
    for (let i = 0; i < lv.cols; i += 1) {
      const x = i * lv.step;
      const z = j * lv.step;
      worst = Math.max(worst, Math.abs(pyramidHeight(arb, x, z, k)
        - pyramidHeight(arb, x, z, 0)));
    }
  }
}
check('(d) coarse support points == fine support points', worst, 0);
// (e) a linear field survives every level, between the points as well
const lin = buildPyramid((x, z) => x / 2 + z, 0, 0, 2, 5, 5, MAX_LOD_LEVELS);
for (const [x, z, want] of [[1, 1, 1.5], [7.5, 2.5, 6.25], [3, 5, 6.5]]) {
  for (let k = 0; k < lin.levels.length; k += 1) {
    check(`(e) the plane at (${x}, ${z}), level ${k}`, pyramidHeight(lin, x, z, k),
      want, 1e-6);
  }
}
// (f) a spike on an ODD lattice index is gone one level up — that IS the error
const spike = buildPyramid((x, z) => (x === 2 && z === 2 ? 8 : 0), 0, 0, 2, 5, 5,
                           MAX_LOD_LEVELS);
check('(f) level 0 has the spike', pyramidHeight(spike, 2, 2, 0), 8);
check('…level 1 does not', pyramidHeight(spike, 2, 2, 1), 0);
check('…so drawing that tile one level up costs', pyramidHeight(spike, 2, 2, 0)
  - pyramidHeight(spike, 2, 2, 1), 8);
checkEq('the level for a node step, base 2', [2, 4, 8, 16, 32, 64]
  .map((s) => pyramidLevelFor(arb, s)), [0, 1, 2, 2, 2, 2]);

// ── [3] the GPU formula ─────────────────────────────────────────────────────
console.log('\n[3] the shader formula IS the sampler — reimplemented, not read');
/** `tlodGrid` of the vertex shader, written out from the arithmetic. */
function glslGrid(pyr, k, x, z) {
  const lv = pyr.levels[k];
  const { cols, rows, step, row0 } = lv;
  if (cols < 2 || rows < 2 || step <= 0) return 0;
  const fx = Math.min(Math.max((x - pyr.originX) / step, 0), cols - 1);
  const fz = Math.min(Math.max((z - pyr.originZ) / step, 0), rows - 1);
  const fi = Math.min(Math.floor(fx), cols - 2);
  const fj = Math.min(Math.floor(fz), rows - 2);
  const tx = fx - fi;
  const tz = fz - fj;
  const at = (i, j) => pyr.data[(j + row0) * pyr.texW + i];
  const north = at(fi, fj) * (1 - tx) + at(fi + 1, fj) * tx;
  const south = at(fi, fj + 1) * (1 - tx) + at(fi + 1, fj + 1) * tx;
  return north * (1 - tz) + south * tz;
}
/**
 * ONE height function, two rasters — which is what E1 made true of the server
 * (addendum § 1) and what the fixture has to honour, or it would be testing a
 * world that cannot exist. `H` is defined on the 2 m lattice; the tiles take
 * every point of it, the overview every second one, so the two carry the SAME
 * number wherever they share a support point.
 */
const H = (x, z) => ((((7 * (x / 2) + 13 * (z / 2)) % 11) + 11) % 11) - 5;
const TILE_N = 9;                 // 9 points at 2 m = one 16 m tile
function tileOf(tx) {
  return {
    origin_x: tx * 16, origin_z: 0, step_m: 2, rows: TILE_N, cols: TILE_N,
    heights: Array.from({ length: TILE_N }, (_, j) =>
      Array.from({ length: TILE_N }, (_, i) => H(tx * 16 + 2 * i, 2 * j))),
  };
}
const OV_N = 17;                  // 17 points at 4 m over [-16, 48]
const OVERVIEW = {
  origin_x: -16, origin_z: -16, step_m: 4, rows: OV_N, cols: OV_N,
  heights: Array.from({ length: OV_N }, (_, j) =>
    Array.from({ length: OV_N }, (_, i) => H(-16 + 4 * i, -16 + 4 * j))),
};
// TWO loaded tiles, so the fixture has an INTERIOR seam. The rim of the loaded
// set is a real discontinuity in `heightAt` itself (a tile answers alone,
// § A16.3) and no renderer can smooth it; in the client it sits at 560 m,
// behind the haze. The interior seam is the one that must be invisible.
const COMPOSITE = {
  tileM: 16, overview: OVERVIEW,
  tiles: new Map([['0,0', tileOf(0)], ['1,0', tileOf(1)]]),
};
check('the two tiles share the column at x = 16',
  heightAt(COMPOSITE, 16, 6) - H(16, 6), 0);
// The near window: the loaded tiles grown by 8 m, on the 2 m lattice.
const NEAR_X0 = -8;
const NEAR_Z0 = -8;
const NEAR_COLS = 25;   // -8 … 40 at 2 m
const NEAR_ROWS = 17;   // -8 … 24
const near = buildPyramid((x, z) => heightAt(COMPOSITE, x, z),
                          NEAR_X0, NEAR_Z0, 2, NEAR_COLS, NEAR_ROWS, MAX_LOD_LEVELS);
check('the near window reaches', NEAR_X0 + (NEAR_COLS - 1) * 2, 40);
// (g) inside the loaded set, ACROSS the interior seam at x = 16
let gpuWorst = 0;
let samples = 0;
for (let z = 0; z <= 14; z += 0.5) {
  for (let x = 0; x <= 30; x += 0.5) {
    gpuWorst = Math.max(gpuWorst,
      Math.abs(glslGrid(near, 0, x, z) - heightAt(COMPOSITE, x, z)));
    samples += 1;
  }
}
check('samples taken', samples, 61 * 29);
check('(g) |h_gpu - h_cpu| stays under 1e-4', gpuWorst < 1e-4 ? 0 : gpuWorst, 0);
check('…and on THIS fixture it is exactly 0 (small halves survive R32F)',
  gpuWorst, 0);
// What the 1e-4 of the contract is really for: a height that is not a binary
// fraction loses about 6e-6 m to the 24-bit mantissa at the scale a world is
// shaped in. Sampled here so the bound is a measured number and not a hope.
const ROUGH = buildPyramid((x, z) => 0.1 * x + 0.03 * z, 0, 0, 2, 9, 9, 1);
let f32Worst = 0;
for (let z = 0; z <= 16; z += 0.5) {
  for (let x = 0; x <= 16; x += 0.5) {
    f32Worst = Math.max(f32Worst, Math.abs(glslGrid(ROUGH, 0, x, z) - (0.1 * x + 0.03 * z)));
  }
}
check('R32F rounding on a non-representable field is under 1e-5',
  f32Worst > 0 && f32Worst < 1e-5 ? 1 : 0, 1);
checkEq('a few of them by name', [[0, 0], [1, 1], [7, 3], [15.5, 9.5], [16, 6], [17, 7]]
  .map(([x, z]) => Math.abs(glslGrid(near, 0, x, z) - heightAt(COMPOSITE, x, z)) < 1e-4),
  [true, true, true, true, true, true]);
// (h) the margin, where the switch between the pyramids happens
const far = buildPyramid((x, z) => sampleWorldHeight(OVERVIEW, x, z),
                         OVERVIEW.origin_x, OVERVIEW.origin_z, 4, OV_N, OV_N,
                         MAX_LOD_LEVELS);
// The strip runs to z = −2 and no further: the 2 m cell [−2, 0] has its south
// row ON the loaded set, so it is the rim cell itself. That is why the near
// window is grown by TWO overview cells (`NEAR_MARGIN_CELLS`) — the rectangle
// the shader switches on must lie strictly outside the rim.
let rimWorst = 0;
for (let z = -8; z <= -2; z += 0.5) {
  for (let x = -8; x <= 40; x += 0.5) {
    rimWorst = Math.max(rimWorst, Math.abs(glslGrid(near, 0, x, z) - glslGrid(far, 0, x, z)));
  }
}
check('(h) near == far in the margin strip', rimWorst < 1e-4 ? 0 : rimWorst, 0);
check('…and there too it is exact, not merely close', rimWorst, 0);
// (i) the red counter-probe: one level up is a different surface
let mipWorst = 0;
for (let z = 0; z <= 14; z += 0.5) {
  for (let x = 0; x <= 30; x += 0.5) {
    mipWorst = Math.max(mipWorst,
      Math.abs(glslGrid(near, 1, x, z) - heightAt(COMPOSITE, x, z)));
  }
}
check('(i) RED: level 1 is NOT the sampler, and misses by more than a metre',
  mipWorst > 1 ? 1 : 0, 1);

// ── [4] the ranges ──────────────────────────────────────────────────────────
console.log('\n[4] the LOD ranges — geometry, widened by the error bound, capped at one doubling');
vector("[4] terrain_lod: (j) without an error list", { lodRanges: (...args) => lodRanges(...vectorArgs(args)) });
const ERR = [0, 0.5862, 0.85, 1.0, 1.1636, 3.3132];
check('the error rule may widen a ring by one doubling', MAX_RANGE_WIDENING, 2);
checkEq('(k) with the contract\'s own example errors at 2 000 px/m/m',
  lodRanges(128, 6, ERR, 2000).map((v) => Math.round(v * 1e4) / 1e4),
  [256, 512, 1000, 1163.6, 3313.2, 4096]);
// …and the two the cap holds are exactly the two the rule asked too much for:
// 586.2 / 128 = 4.6 doublings' worth and 850 / 256 = 3.3.
checkEq('…the levels the cap held, and what they had asked for',
  [0, 1].map((i) => [Math.round((ERR[i + 1] * 2000) / MAX_PIXEL_ERROR * 10) / 10,
                     128 * (1 << i) * MAX_RANGE_WIDENING]),
  [[586.2, 256], [850, 512]]);
/**
 * (l) THE LADDER IS MONOTONE BY CONSTRUCTION UNDER THE CAP — derived in the
 * docstring, measured here on the shape that used to invert it: a huge error at
 * level 1 beside a small one at level 2. The error term is err · 200 / 2 =
 * err · 100, so [1000, 300] against geometric rings of [128, 256] and caps of
 * [256, 512].
 */
const HOSTILE = [0, 10, 3];
vector("[4] terrain_lod: (l) the hostile error list, capped", { lodRanges: (...args) => lodRanges(...vectorArgs(args)) });
/**
 * THE LADDER AS IT WAS BEFORE THE CAP, written out from its own arithmetic
 * rather than by calling the shipped function — `MAX_RANGE_WIDENING` cannot be
 * turned off from outside, and a red probe that asked the shipped code to
 * misbehave would prove nothing anyway.
 *
 * `monotone` is the repair line the old `lodRanges` ran afterwards: off here in
 * (l), where the point is that the raw terms really do invert, and ON in [14],
 * which reproduces the world that overran `MAX_NODES` and therefore needs the
 * old function's answer to the digit.
 */
const uncappedLadder = (min, levels, err, scale, monotone = false) => {
  const out = [];
  for (let i = 0; i < levels; i += 1) {
    let r = min * (1 << i);
    const e = err?.[i + 1] ?? 0;
    if (min > 0 && scale > 0 && e > 0) r = Math.max(r, (e * scale) / MAX_PIXEL_ERROR);
    if (monotone && i > 0 && r < out[i - 1]) r = out[i - 1];
    out.push(r);
  }
  return out;
};
// RED: level 1's ring starts INSIDE level 0's as soon as the cap is gone.
const hostileRaw = uncappedLadder(128, 3, HOSTILE, 200);
checkEq('…RED: uncapped, the same list inverts the ladder', hostileRaw,
  [1000, 300, 512]);
check('…RED: by this many metres, level 1 starting inside level 0',
  hostileRaw[0] - hostileRaw[1], 700);
// …and the capped ladder cannot: range[i] ≤ 2·g_i = g_(i+1) ≤ range[i+1].
const capMono = (err, scale) => {
  const r = lodRanges(128, 6, err, scale);
  return r.every((v, i) => (i === 0 || v >= r[i - 1])
    && v <= 128 * (1 << i) * MAX_RANGE_WIDENING + 1e-9);
};
checkEq('…while every capped ladder is monotone and inside one doubling',
  [capMono(ERR, 2000), capMono(HOSTILE, 200), capMono([0, 9, 9, 9, 9, 9], 5000)],
  [true, true, true]);
vector("[4] terrain_lod: (m) a flat world has no ranges", { lodRanges: (...args) => lodRanges(...vectorArgs(args)) });

/**
 * (m2) THE ERROR LIST IS TAKEN OVER *ALL* TILES — `levelErrorsFrom`, and what
 *     an incomplete `tile_stats` costs.
 *
 * `GET /play/heightfield` ships at most `TILE_STATS_MAX` = 64 tile statistics
 * and says so through `tile_stats_complete`; the rest is fetched from
 * `GET /play/heightfield/stats`. The rule below takes a MAXIMUM per level, so
 * a missing tile is not a small contribution but no contribution at all: the
 * ladder above is then built from the roughness of the first 64 tiles alone.
 *
 * THE FIXTURE — 100 tiles keyed `"i,0"`, i = 0…99, in the server's own order
 * (`sorted(tile_index())` is by tx, then tz), each with the five mip errors
 *     err(i) = [ i/128, 2i/128, 3i/128, 4i/128, 5i/128 ]  metres
 * — dyadic, so every number here is exact in binary. The roughest tiles are
 * the LAST ones, which is the case that matters: the cap keeps the first 64.
 *
 * The node level L draws its vertices `2 · 2^L` m apart, so L = 1…5 are the
 * server's `mip_levels_m` [4, 8, 16, 32, 64] and L = 0 is the base lattice
 * with no error at all. Hence, per level, the maximum of column k over the
 * tiles held:
 *     all 100 tiles   -> i = 99: [0, 99/128, 198/128, 297/128, 396/128, 495/128]
 *                              = [0, 0.7734375, 1.546875, 2.3203125,
 *                                 3.09375, 3.8671875]
 *     first 64 only   -> i = 63: [0, 63/128, 126/128, 189/128, 252/128, 315/128]
 *                              = [0, 0.4921875, 0.984375, 1.4765625,
 *                                 1.96875, 2.4609375]
 * — 99/63 = 1.5714… times too small on EVERY level.
 *
 * WHAT THAT COSTS, through `lodRanges(128, 6, err, 500)`. The error term is
 * `err · 500 / MAX_PIXEL_ERROR` = `err · 250`, the geometric ring is
 * `128 · 2^i`, and the widening is capped at twice that:
 *     complete: 250 · [0.7734375, 1.546875, 2.3203125, 3.09375, 3.8671875]
 *             = [193.359375, 386.71875, 580.078125, 773.4375, 966.796875]
 *       i = 0: max(128,  min(193.359375, 256))  = 193.359375
 *       i = 1: max(256,  min(386.71875,  512))  = 386.71875
 *       i = 2: max(512,  min(580.078125, 1024)) = 580.078125
 *       i = 3: max(1024, min(773.4375,   2048)) = 1024      (geometry wins)
 *       i = 4: max(2048, min(966.796875, 4096)) = 2048      (geometry wins)
 *       i = 5: no err[6]                        = 4096
 *     capped:   250 · [0.4921875, 0.984375, 1.4765625, 1.96875, 2.4609375]
 *             = [123.046875, 246.09375, 369.140625, 492.1875, 615.234375]
 *       every one of them is BELOW its geometric ring, so the ladder collapses
 *       to the purely geometric [128, 256, 512, 1024, 2048, 4096].
 *
 * That is the defect in one number: with two thirds of the statistics missing
 * the finest ring reaches 128 m instead of 193.359375 m — the ground between
 * them is drawn one level coarser than the two-pixel budget allows, and
 * nothing in the picture says so.
 */
const statsFor = (n, from = 0) => {
  const m = new Map();
  for (let i = from; i < n; i += 1) {
    m.set(`${i},0`, { err: [1, 2, 3, 4, 5].map((f) => (i * f) / 128) });
  }
  return m;
};
const MIPS = [4, 8, 16, 32, 64];
const allStats = statsFor(100);
const cappedStats = statsFor(64);
check('(m2) the fixture has one statistic per tile', allStats.size, 100);
checkEq('…the level errors over ALL 100 tiles',
  levelErrorsFrom(allStats, MIPS, BASE, MAX_LOD_LEVELS),
  [0, 0.7734375, 1.546875, 2.3203125, 3.09375, 3.8671875]);
checkEq('…RED: over the first 64 alone, too small on every level',
  levelErrorsFrom(cappedStats, MIPS, BASE, MAX_LOD_LEVELS),
  [0, 0.4921875, 0.984375, 1.4765625, 1.96875, 2.4609375]);
checkEq('…and the ladder the complete list buys',
  lodRanges(128, MAX_LOD_LEVELS,
            levelErrorsFrom(allStats, MIPS, BASE, MAX_LOD_LEVELS), 500),
  [193.359375, 386.71875, 580.078125, 1024, 2048, 4096]);
checkEq('…RED: the capped list falls back to the purely geometric rings',
  lodRanges(128, MAX_LOD_LEVELS,
            levelErrorsFrom(cappedStats, MIPS, BASE, MAX_LOD_LEVELS), 500),
  [128, 256, 512, 1024, 2048, 4096]);
// The order the statistics arrive in cannot matter — it is a maximum. The
// 36 tiles the cap dropped are merged in the other way round and answer the
// same list, which is what `fillMissingStats` does per batch.
const merged = new Map([...statsFor(100, 64), ...cappedStats]);
checkEq('…merging the missing 36 in afterwards restores it, order-free',
  levelErrorsFrom(merged, MIPS, BASE, MAX_LOD_LEVELS),
  [0, 0.7734375, 1.546875, 2.3203125, 3.09375, 3.8671875]);
// The degenerate inputs of the rule: no statistics at all, and a base step
// whose doublings (6, 12, 24, 48, 96 m) are no declared mip level.
checkEq('…no statistics at all -> no error anywhere',
  levelErrorsFrom(new Map(), MIPS, BASE, MAX_LOD_LEVELS), [0, 0, 0, 0, 0, 0]);
checkEq('…a base step the server declares no level for -> the same',
  levelErrorsFrom(allStats, MIPS, 3, MAX_LOD_LEVELS), [0, 0, 0, 0, 0, 0]);

// ── [5] the selection ───────────────────────────────────────────────────────
console.log('\n[5] the quadtree — camera on the world corner');
const FLAT_BOUNDS = () => ({ min: 0, max: 0 });
const picked = selectLodNodes({
  x0: 0, z0: 0, x1: 2048, z1: 2048,
  leafM: 64, levels: 6, minLodDistance: 128,
  camX: 0, camY: 0, camZ: 0,
  boundsOf: FLAT_BOUNDS,
});
check('(n) nodes selected', picked.length, 16);
const perLevel = [0, 0, 0, 0, 0, 0];
for (const n of picked) perLevel[n.level] += 1;
checkEq('…per level', perLevel, [4, 3, 3, 3, 3, 0]);
const key = (n) => `${n.level}:${n.x},${n.z}`;
checkEq('the level-0 nodes', picked.filter((n) => n.level === 0).map(key).sort(),
  ['0:0,0', '0:0,64', '0:64,0', '0:64,64']);
checkEq('the level-4 nodes', picked.filter((n) => n.level === 4).map(key).sort(),
  ['4:0,1024', '4:1024,0', '4:1024,1024']);
checkEq('…and every one of them draws the whole patch',
  picked.every((n) => n.cells === PATCH_N), true);
for (const level of [0, 1, 2, 3, 4]) {
  const size = 64 * (1 << level);
  const corner = picked.find((n) => n.level === level && n.x === 0 && n.z === 0);
  const axis = picked.find((n) => n.level === level && n.x === size && n.z === 0);
  const diag = picked.find((n) => n.level === level && n.x === size && n.z === size);
  if (level === 0) check(`(o) level 0, the corner node (d = 0)`, corner.morph, 0);
  check(`(o) level ${level}, the axis node (d = size)`, axis.morph, 0);
  // The ramp of level L runs over the LAST HALF OF ITS OWN RING. Level 0's ring
  // starts at 0, so its ramp begins at 0.5·range[0] = size and the diagonal node
  // at d = size·√2 is (√2 − 1) of the way through it. Every level above has its
  // ring start at range[L−1] = size, so its ramp begins at 1.5·size — past the
  // 1.414·size the diagonal stands at, and the node has not begun to morph.
  check(`…the diagonal one (d = size·√2 = 1.414·size)`, diag.morph,
    level === 0 ? Math.SQRT2 - 1 : 0, 1e-12);
}
// (o2) AND THE RAMP ITSELF, on one node with nothing else in the world. The
// node [0, 128]² at level 1 owns the ring [128, 256] and its morph runs over
// the LAST HALF of that ring, [192, 256]. A camera on the x axis at 128 + d is
// exactly d from its east face:
//   d = 192 -> the ramp has not started        -> 0
//   d = 224 -> (224 − 192) / 64                -> 0.5
//   d = 256 -> the ring ends                   -> 1
for (const [camX, want] of [[320, 0], [352, 0.5], [384, 1]]) {
  const one = selectLodNodes({
    x0: 0, z0: 0, x1: 128, z1: 128, leafM: 64, levels: 2, minLodDistance: 128,
    camX, camY: 0, camZ: 0, boundsOf: FLAT_BOUNDS,
  });
  check(`(o2) the level-1 ramp at d = ${camX - 128} m`, one[0].morph, want, 1e-12);
}
// The ring boundary belongs to the COARSER level: at exactly `ranges[L-1]` the
// node is selected, not split. One metre nearer and it splits.
// The node is [0, 128]², so a camera at x = 256 is 128 m from its east face —
// exactly lodRange[0]. (A camera AT 128 would be touching the box and read 0.)
const onRing = selectLodNodes({
  x0: 0, z0: 0, x1: 128, z1: 128, leafM: 64, levels: 2, minLodDistance: 128,
  camX: 256, camY: 0, camZ: 0, boundsOf: FLAT_BOUNDS,
});
checkEq('a node at exactly lodRange[0] stays whole', onRing.map(key), ['1:0,0']);
check('…and it has not begun to morph', onRing[0].morph, 0);
const inside = selectLodNodes({
  x0: 0, z0: 0, x1: 128, z1: 128, leafM: 64, levels: 2, minLodDistance: 128,
  camX: 255.9, camY: 0, camZ: 0, boundsOf: FLAT_BOUNDS,
});
check('…and a decimetre nearer it splits into four', inside.length, 4);

// ── [6] crack-freeness ──────────────────────────────────────────────────────
console.log('\n[6] a fully morphed node IS its parent — no skirt, no crack');
// A field with a spike on every odd lattice point of level 1, so the two
// levels genuinely disagree between the parent's support points.
const CRACK = buildPyramid((x, z) => (((x / 8) % 2 === 1) ? 6 : 0),
                           0, 0, 8, 33, 33, MAX_LOD_LEVELS);
const RECT = null;
const childFull = { x: 0, z: 0, size: 256, level: 1, cells: PATCH_N, morph: 1 };
const childOwn = { x: 0, z: 0, size: 256, level: 1, cells: PATCH_N, morph: 0 };
const parent = { x: 0, z: 0, size: 512, level: 2, cells: PATCH_N, morph: 0 };
let edgeWorst = 0;
let ownWorst = 0;
for (let g = 0; g <= PATCH_N; g += 1) {
  const a = morphedVertex(childFull, g, 0, null, RECT, CRACK);
  // The parent's vertex at the SAME world x — the child's fully morphed
  // vertices land on even indices of its own grid, i.e. on the parent's every
  // other point, which is the parent's vertex g/2 rounded down.
  const b = morphedVertex(parent, Math.floor(g / 2), 0, null, RECT, CRACK);
  edgeWorst = Math.max(edgeWorst, Math.abs(a.x - b.x), Math.abs(a.y - b.y));
  const c = morphedVertex(childOwn, g, 0, null, RECT, CRACK);
  ownWorst = Math.max(ownWorst, Math.abs(c.y - b.y));
}
check('(p) the morphed edge lands exactly on the parent\'s', edgeWorst, 0);
check('(q) RED: unmorphed, the same edge stands off it by', ownWorst, 6);
// THE WORLD FRAME. A quadtree node is a power-of-two square and the frame is
// not, so the outermost nodes reach past it and the shader clamps their
// vertices onto it. Two things have to hold: nothing is drawn outside, and the
// clamp does not open a crack — a node and its parent clamp against the SAME
// rectangle, so they still meet.
const EXTENT = [0, 0, 200, 200];
let outside = 0;
let frameWorst = 0;
for (let g = 0; g <= PATCH_N; g += 1) {
  const a = morphedVertex(childFull, g, 0, null, RECT, CRACK, EXTENT);
  const b = morphedVertex(parent, Math.floor(g / 2), 0, null, RECT, CRACK, EXTENT);
  if (a.x < EXTENT[0] - 1e-9 || a.x > EXTENT[2] + 1e-9) outside += 1;
  frameWorst = Math.max(frameWorst, Math.abs(a.x - b.x), Math.abs(a.y - b.y));
}
check('no vertex is drawn outside the world frame', outside, 0);
check('…and the clamp opens no crack against the parent', frameWorst, 0);
check('the last vertex of a 256 m node sits on the 200 m frame',
  morphedVertex(childFull, PATCH_N, 0, null, RECT, CRACK, EXTENT).x, 200);

// ── [8] the morph belongs to the vertex ─────────────────────────────────────
console.log('\n[8] two neighbours describe ONE polyline — the morph is per vertex');
const RANGES = lodRanges(128, 6);
vector("[8] terrain_lod: (w) λ(0)", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
vector("[8] terrain_lod: (w) λ(64)", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
vector("[8] terrain_lod: (w) λ(96)", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
vector("[8] terrain_lod: (w) λ(128) = one whole level", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
vector("[8] terrain_lod: (w) λ(192) — level 1's ramp only STARTS here", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
vector("[8] terrain_lod: (w) λ(224)", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
vector("[8] terrain_lod: (w) λ(256)", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
vector("[8] terrain_lod: (w) λ(400)", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
vector("[8] terrain_lod: (w) λ(512)", { lodLambda: (...args) => lodLambda(...vectorArgs(args)) });
// A 6 m step every other 4 m of z — see the docstring: the 2 m, 4 m and 8 m
// mips all read it differently, at the very points the two nodes meet on.
const SEAM = buildPyramid((x, z) => ((Math.floor(z / 4) % 2 === 1) ? 6 : 0),
                          0, 0, 2, 129, 129, MAX_LOD_LEVELS);
check('the 2 m mip reads the step at z = 4', pyramidHeight(SEAM, 128, 4, 0), 6);
check('…the 4 m mip too', pyramidHeight(SEAM, 128, 4, 1), 6);
check('…and the 8 m mip is flat there', pyramidHeight(SEAM, 128, 4, 2), 0);
const SEAM_CAM = { x: 0, y: 0, z: 0 };
const seamNodes = selectLodNodes({
  x0: 0, z0: 0, x1: 2048, z1: 2048,
  leafM: 64, levels: 6, minLodDistance: 128,
  camX: SEAM_CAM.x, camY: SEAM_CAM.y, camZ: SEAM_CAM.z,
  // An HONEST box: the field really reaches 6 m, and the guarantee "a vertex is
  // never nearer than its node's box" is what puts λ ≥ level on every vertex.
  boundsOf: () => ({ min: 0, max: 6 }),
});
const fine = seamNodes.find((n) => n.level === 0 && n.x === 64 && n.z === 0);
const coarse = seamNodes.find((n) => n.level === 1 && n.x === 128 && n.z === 0);
check('the fine node is a leaf at (64, 0)', fine ? fine.size : -1, 64);
check('…its neighbour at (128, 0) is one level up', coarse ? coarse.size : -1, 128);
check('both stand at morph 0 under the old per-node rule', fine.morph + coarse.morph, 0);
/** The height of a node's WEST edge polyline at world z — the line a neighbour
 *  really has to meet, not merely its vertices. */
function edgeYAt(node, vertexFn, z) {
  let prev = vertexFn(node, 0, 0);
  for (let j = 1; j <= PATCH_N; j += 1) {
    const cur = vertexFn(node, 0, j);
    if (cur.z > prev.z && z >= prev.z - 1e-9 && z <= cur.z + 1e-9) {
      const f = (z - prev.z) / (cur.z - prev.z);
      return prev.y * (1 - f) + cur.y * f;
    }
    prev = cur;
  }
  return null;
}
const newFine = (n, gx, gz) => lodVertex(n, gx, gz, SEAM, null, SEAM, null,
                                         SEAM_CAM, RANGES);
const oldFine = (n, gx, gz) => morphedVertex(n, gx, gz, SEAM, null, SEAM);
let sharedWorst = 0;
let seamWorst = 0;
let seamRed = 0;
for (let g = 0; g <= PATCH_N; g += 1) {
  const a = newFine(fine, PATCH_N, g);
  const onB = edgeYAt(coarse, (n, gx, gz) => newFine(n, gx, gz), a.z);
  if (onB !== null) seamWorst = Math.max(seamWorst, Math.abs(a.y - onB));
  if (g % 2 === 0) {
    // The vertices the two really SHARE: the fine node's every second one is
    // the coarse node's own. Same raw point, same finest height, same λ.
    const b = newFine(coarse, 0, g / 2);
    sharedWorst = Math.max(sharedWorst, Math.abs(a.x - b.x), Math.abs(a.z - b.z),
                           Math.abs(a.y - b.y));
  }
  const ra = oldFine(fine, PATCH_N, g);
  const onRb = edgeYAt(coarse, (n, gx, gz) => oldFine(n, gx, gz), ra.z);
  if (onRb !== null) seamRed = Math.max(seamRed, Math.abs(ra.y - onRb));
}
check('(x) every vertex the two SHARE agrees exactly', sharedWorst, 0, 1e-12);
check('…and the whole fine edge lies ON the coarse one', seamWorst, 0, 1e-9);
check('(y) RED: with one morph per node the same edge stood off by',
  seamRed, 3, 1e-12);

// ── [9] coverage over the whole compass ─────────────────────────────────────
console.log('\n[9] the selected nodes tile every visible piece of ground');

// (z1) the negative side of the tile lattice, by hand
const TILE_M = 256;
const bx = (x, size) => [Math.floor(x / TILE_M), Math.floor((x + size - 1e-6) / TILE_M)];
checkEq('(z1) the reported spot (-1550, -760) is tile (-7, -3)',
  [Math.floor(-1550 / TILE_M), Math.floor(-760 / TILE_M)], [-7, -3]);
checkEq('…and that tile spans x [-1792, -1536), z [-768, -512)',
  [-7 * TILE_M, -6 * TILE_M, -3 * TILE_M, -2 * TILE_M], [-1792, -1536, -768, -512]);
checkEq('…while Math.trunc would name the tile east AND south of it',
  [Math.trunc(-1550 / TILE_M), Math.trunc(-760 / TILE_M)], [-6, -2]);
checkEq('a 64 m node at (64, -128) covers tile (0, -1) alone',
  [bx(64, 64), bx(-128, 64)], [[0, 0], [-1, -1]]);
checkEq('a 256 m node at (-128, -128) covers the four tiles around the origin',
  [bx(-128, 256), bx(-128, 256)], [[-1, 0], [-1, 0]]);
checkEq('a 256 m node at (-256, -512) stops at its own tile',
  [bx(-256, 256), bx(-512, 256)], [[-1, -1], [-2, -2]]);

// The compass world — see the docstring. Negative-heavy on purpose.
const CX0 = -2560;
const CZ0 = -2560;
const CX1 = 2560;
const CZ1 = 2560;
const LEAF_M = PATCH_N * BASE;                  // 64
/** A rolling relief with two hills, deliberately NOT symmetric in x and z, so
 *  a direction-blind bug cannot hide behind a symmetric field. */
const CH = (x, z) => 9 * Math.sin(x / 197) * Math.cos(z / 151)
  + 14 * Math.exp(-(((x + 900) ** 2 + (z + 200) ** 2) / (2 * 320 ** 2)))
  + 22 * Math.exp(-(((x - 400) ** 2 + (z + 1400) ** 2) / (2 * 260 ** 2)));
/** Honest per-tile statistics: the extremes of the tile's OWN 2 m lattice,
 *  which is what the server ships and what the drawn surface stays inside. */
const cStats = new Map();
let gMin = 0;
let gMax = 0;
for (let tz = CZ0 / TILE_M; tz < CZ1 / TILE_M; tz += 1) {
  for (let tx = CX0 / TILE_M; tx < CX1 / TILE_M; tx += 1) {
    let mn = Infinity;
    let mx = -Infinity;
    for (let j = 0; j <= TILE_M / BASE; j += 1) {
      for (let i = 0; i <= TILE_M / BASE; i += 1) {
        const v = CH(tx * TILE_M + i * BASE, tz * TILE_M + j * BASE);
        if (v < mn) mn = v;
        if (v > mx) mx = v;
      }
    }
    cStats.set(`${tx},${tz}`, { min: mn, max: mx });
    gMin = Math.min(gMin, mn);
    gMax = Math.max(gMax, mx);
  }
}
const cGlobal = { min: gMin, max: gMax };
check('the compass world holds tiles', cStats.size, 20 * 20);

// The frustum, written out — three's own `setFromProjectionMatrix` (Gribb &
// Hartmann: the rows of the view-projection added to and subtracted from the
// w row) and its `intersectsBox` (the box corner FARTHEST along each plane
// normal). Reimplemented here for the same reason `tlodGrid` is: a check that
// imported the renderer's matrices could only prove them equal to themselves.
const FOV_DEG = 45;
const ASPECT = 16 / 9;
const NEAR_M = 0.2;
const FAR_M = 800;
const HAZE_M = 520;
const PIXELS = 1080;
const camPixelScale = PIXELS / (2 * Math.tan((FOV_DEG * Math.PI) / 360));
/** The server's own example error bounds (§ 4 of the E1 addendum), so the
 *  ranges the sweep runs against are the widened ones a real world produces. */
const CERR = [0, 0.5862, 0.85, 1.0, 1.1636, 3.3132];
const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                          a[0] * b[1] - a[1] * b[0]];
const unit = (a) => { const l = Math.hypot(a[0], a[1], a[2]); return [a[0] / l, a[1] / l, a[2] / l]; };
function mul4(a, b) {
  const o = new Array(16).fill(0);
  for (let r = 0; r < 4; r += 1) {
    for (let c = 0; c < 4; c += 1) {
      let s = 0;
      for (let k = 0; k < 4; k += 1) s += a[r * 4 + k] * b[k * 4 + c];
      o[r * 4 + c] = s;
    }
  }
  return o;
}
function frustumPlanes(eye, fwd) {
  const zA = [-fwd[0], -fwd[1], -fwd[2]];
  const xA = unit(cross3([0, 1, 0], zA));
  const yA = cross3(zA, xA);
  const view = [xA[0], xA[1], xA[2], -dot3(xA, eye),
                yA[0], yA[1], yA[2], -dot3(yA, eye),
                zA[0], zA[1], zA[2], -dot3(zA, eye),
                0, 0, 0, 1];
  const f = 1 / Math.tan((FOV_DEG * Math.PI) / 360);
  const proj = [f / ASPECT, 0, 0, 0,
                0, f, 0, 0,
                0, 0, (FAR_M + NEAR_M) / (NEAR_M - FAR_M), (2 * FAR_M * NEAR_M) / (NEAR_M - FAR_M),
                0, 0, -1, 0];
  const m = mul4(proj, view);
  const row = (r) => [m[r * 4], m[r * 4 + 1], m[r * 4 + 2], m[r * 4 + 3]];
  const [m0, m1, m2, m3] = [row(0), row(1), row(2), row(3)];
  const add = (a, b, s) => [a[0] + s * b[0], a[1] + s * b[1], a[2] + s * b[2], a[3] + s * b[3]];
  return [add(m3, m0, 1), add(m3, m0, -1), add(m3, m1, 1), add(m3, m1, -1),
          add(m3, m2, 1), add(m3, m2, -1)]
    .map((p) => { const l = Math.hypot(p[0], p[1], p[2]);
                  return [p[0] / l, p[1] / l, p[2] / l, p[3] / l]; });
}
const boxSeen = (ps, x0, y0, z0, x1, y1, z1) => ps.every((p) =>
  p[0] * (p[0] > 0 ? x1 : x0) + p[1] * (p[1] > 0 ? y1 : y0)
  + p[2] * (p[2] > 0 ? z1 : z0) + p[3] >= 0);
const pointSeen = (ps, x, y, z) => ps.every((p) => p[0] * x + p[1] * y + p[2] * z + p[3] >= 0);

/** Where the eye stands for a heading: the orbit camera sits `dist` behind and
 *  above the point it looks at, exactly the arrangement `engine.ts` builds. */
function eyeFor(atX, atZ, yawDeg, pitchDeg, dist) {
  const a = (yawDeg * Math.PI) / 180;
  const pr = (pitchDeg * Math.PI) / 180;
  const fwd = [Math.sin(a) * Math.cos(pr), Math.sin(pr), Math.cos(a) * Math.cos(pr)];
  const ty = CH(atX, atZ) + 1.6;
  return { fwd, eye: [atX - fwd[0] * dist, ty - fwd[1] * dist, atZ - fwd[2] * dist] };
}
/**
 * One heading: select, then walk a polar fan of ground points and count the
 * VISIBLE ones no selected square owns.
 *
 * The fan is ±40° about the view axis (the horizontal half-angle of a 45°/16:9
 * frustum is atan(tan 22.5° · 16/9) = 36.4°, so it reaches past both edges)
 * and its rings grow geometrically, which puts samples where the nodes are
 * small as well as where they are large.
 */
function coverageAt(boundsFn, atX, atZ, yawDeg, pitchDeg, dist, drawn = null) {
  const { fwd, eye } = eyeFor(atX, atZ, yawDeg, pitchDeg, dist);
  const ps = frustumPlanes(eye, fwd);
  const select = (e) => selectLodNodes({
    x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: e[0], camY: e[1], camZ: e[2],
    boundsOf: boundsFn, levelErrorM: CERR, pixelScale: camPixelScale,
  });
  // The SHIPPED renderer draws the whole selection — there is no frustum test
  // in it since 2026-08-22. `drawn` is how a RED probe puts one back, or hands
  // the frame a list that was selected for a different camera.
  const picked = drawn ? drawn({ eye, fwd, ps, select, boundsFn }) : select(eye);
  const a = (yawDeg * Math.PI) / 180;
  const flat = Math.cos((pitchDeg * Math.PI) / 180);
  let miss = 0;
  let tested = 0;
  for (let r = 4; r <= HAZE_M; r *= 1.06) {
    for (let da = -40; da <= 40; da += 1) {
      const b = a + (da * Math.PI) / 180;
      const px = eye[0] + Math.sin(b) * r * flat;
      const pz = eye[2] + Math.cos(b) * r * flat;
      if (px < CX0 || px > CX1 || pz < CZ0 || pz > CZ1) continue;
      const py = CH(px, pz);
      if (!pointSeen(ps, px, py, pz)) continue;
      tested += 1;
      let owned = false;
      for (const n of picked) {
        if (px >= n.x && px <= n.x + n.size && pz >= n.z && pz <= n.z + n.size) {
          owned = true;
          break;
        }
      }
      if (!owned) miss += 1;
    }
  }
  return { miss, tested, nodes: picked.length };
}
/** The whole compass for one orbit setting: total misses, total samples, and
 *  the headings that failed, as ranges. */
function sweepCompass(boundsFn, atX, atZ, pitchDeg, dist, drawn = null) {
  let miss = 0;
  let tested = 0;
  let maxNodes = 0;
  const bad = [];
  for (let yaw = 0; yaw < 360; yaw += 1) {
    const r = coverageAt(boundsFn, atX, atZ, yaw, pitchDeg, dist, drawn);
    miss += r.miss;
    tested += r.tested;
    if (r.nodes > maxNodes) maxNodes = r.nodes;
    if (r.miss) bad.push(yaw);
  }
  const ranges = [];
  for (const y of bad) {
    const last = ranges[ranges.length - 1];
    if (last && y === last[1] + 1) last[1] = y;
    else ranges.push([y, y]);
  }
  return { miss, tested, headings: bad.length, maxNodes,
           ranges: ranges.map((r) => (r[0] === r[1] ? `${r[0]}` : `${r[0]}-${r[1]}`)).join(', ') };
}
const REPORTED_X = -1550;
const REPORTED_Z = -760;
const ORBITS = [[8, -15], [25, -25], [60, -35]];
const honest = (x, z, size) => nodeBounds(cStats, TILE_M, cGlobal, x, z, size);
let sweptSamples = 0;
let maxSweepNodes = 0;
for (const [dist, pitch] of ORBITS) {
  const r = sweepCompass(honest, REPORTED_X, REPORTED_Z, pitch, dist);
  sweptSamples += r.tested;
  maxSweepNodes = Math.max(maxSweepNodes, r.maxNodes);
  check(`(z2) 360 headings at ${dist} m / ${pitch}°: visible ground with no node`
    + ` (of ${r.tested} samples)`, r.miss, 0);
  check('…failing headings', r.headings, 0);
}
checkAbove('(z2) ground points sampled over the whole compass', sweptSamples, 2.5e6);
checkBelow('…and the largest selection any of those frames drew', maxSweepNodes, MAX_NODES);
console.log(`       (at most ${maxSweepNodes} pieces per frame, cap ${MAX_NODES})`);

// (z3) RED A — THE ONE-FRAME-LATE INSTANCE BUFFER, the defect that was measured
// on 2026-08-22. three.js uploads an InstancedBufferGeometry's dirty attributes
// in `projectObject` (`WebGLObjects.update`, "Update once per frame"), which
// runs over the whole scene BEFORE the first `object.onBeforeRender`. The
// selection used to be written in that hook, so the rows the card read were the
// PREVIOUS frame's while `instanceCount` was this frame's. Here the frame is
// drawn with the list selected one degree of yaw earlier — and because the old
// code also culled per piece, that list was a different set every frame.
const cullAll = (list, planes, boundsFn) => list.filter((n) => {
  const b = boundsFn(n.x, n.z, n.size);
  return boxSeen(planes, n.x, b.min, n.z, n.x + n.size, b.max, n.z + n.size);
});
const oneFrameLate = (deg, pitchDeg, dist) => ({ eye, fwd, ps, select, boundsFn }) => {
  const yawNow = (Math.atan2(fwd[0], fwd[2]) * 180) / Math.PI;
  const prev = eyeFor(REPORTED_X, REPORTED_Z, yawNow - deg, pitchDeg, dist);
  // What the card really had: the ROWS of the previous frame (selected and
  // culled against the previous camera), cut off at THIS frame's instance
  // count. Both halves are the shipped code of 2026-08-21 — the write in
  // `onBeforeRender`, the count read at draw time.
  const rows = cullAll(select(prev.eye), frustumPlanes(prev.eye, prev.fwd), boundsFn);
  const count = cullAll(select(eye), ps, boundsFn).length;
  return rows.slice(0, count);
};
const redLate = sweepCompass(honest, REPORTED_X, REPORTED_Z, -15, 8,
                             oneFrameLate(1, -15, 8));
// The floor is a dozen headings and five figures of ground, not the exact count:
// how many headings the staleness bites at is a property of the fixture's rings
// (25 under the capped ladder, 40 under the uncapped one — see the docstring).
checkAbove('(z3) RED A: the previous frame\'s rows under this frame\'s count'
  + ' lose ground at headings', redLate.headings, 12);
checkAbove('…and lose this many sampled points', redLate.miss, 1e4);
console.log(`       (RED A fails at headings ${redLate.ranges})`);
// …and the same staleness against the SHIPPED renderer, which culls nothing:
// the selection then depends on the camera POSITION alone, so a heading that is
// one frame old changes nothing at all and the count matches the rows.
const lateNoCull = (deg, pitchDeg, dist) => ({ fwd, select }) => {
  const yawNow = (Math.atan2(fwd[0], fwd[2]) * 180) / Math.PI;
  return select(eyeFor(REPORTED_X, REPORTED_Z, yawNow - deg, pitchDeg, dist).eye);
};
const lateNow = sweepCompass(honest, REPORTED_X, REPORTED_Z, -15, 8,
                             lateNoCull(1, -15, 8));
check('…while without the cull the very same staleness loses nothing',
  lateNow.miss, 0);

// (z4) RED B — THE CULL'S OWN BOX, where the server's per-tile statistics do not
// reach. `tile_stats` is capped (`TILE_STATS_MAX`), and `nodeBounds` folds a
// ZERO into the box for every tile it has no statistic for — the flat world an
// unindexed tile stands for. A tile that exists and carries hills but whose
// statistic was capped away therefore gets a box that does not contain its own
// ground, and the frustum test rejects it while it is on screen. That is the
// second reason the per-piece cull is gone rather than repaired.
const capped = new Map();
let kept = 0;
for (const [key, v] of cStats) {
  // Every fourth tile keeps its statistic — a cap that bites, in the pattern a
  // server-side cap really produces (the first N of an ordered scan).
  if (kept % 4 === 0) capped.set(key, v);
  kept += 1;
}
const cappedBounds = (x, z, size) => nodeBounds(capped, TILE_M, { min: 0, max: 0 },
                                                x, z, size);
const cullWithBox = ({ eye, ps, select }) => select(eye)
  .filter((n) => {
    const b = cappedBounds(n.x, n.z, n.size);
    return boxSeen(ps, n.x, b.min, n.z, n.x + n.size, b.max, n.z + n.size);
  });
const redBox = sweepCompass(honest, REPORTED_X, REPORTED_Z, -25, 25, cullWithBox);
checkAbove('(z4) RED B: the cull with a box the capped statistics do not cover'
  + ' loses ground at headings', redBox.headings, 20);
checkAbove('…and loses this many sampled points', redBox.miss, 1e3);
console.log(`       (RED B fails at headings ${redBox.ranges})`);

// (z5) stability — the other half of a flicker
for (const [dist, pitch] of [[8, -15], [25, -25]]) {
  let worst = 0;
  let prev = null;
  for (let yaw = 0; yaw < 360; yaw += 0.05) {
    const { eye } = eyeFor(REPORTED_X, REPORTED_Z, yaw, pitch, dist);
    const picked = selectLodNodes({
      x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
      leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
      camX: eye[0], camY: eye[1], camZ: eye[2],
      boundsOf: honest, levelErrorM: CERR, pixelScale: camPixelScale,
    });
    const set = new Set(picked.map((n) => `${n.level}:${n.x},${n.z}`));
    if (prev) {
      let diff = 0;
      for (const k of set) if (!prev.has(k)) diff += 1;
      for (const k of prev) if (!set.has(k)) diff += 1;
      if (diff > worst) worst = diff;
    }
    prev = set;
  }
  // Three simultaneous split/merge events, 5 entries each — the derivation of
  // the two centimetres the eye moves per step is in the docstring.
  checkBelow(`(z5) worst node churn per 0.05° of yaw at ${dist} m / ${pitch}°`,
    worst, 16);
}

// (z6) the selection knows no quadrant
const MIRROR_EXTENT = [-2048, -2048, 2048, 2048];
const flatBounds = () => ({ min: 0, max: 6 });
function selectAt(cx, cz) {
  return selectLodNodes({
    x0: MIRROR_EXTENT[0], z0: MIRROR_EXTENT[1], x1: MIRROR_EXTENT[2], z1: MIRROR_EXTENT[3],
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: cx, camY: 12, camZ: cz, boundsOf: flatBounds,
  });
}
const eastNorth = selectAt(777, -333);
const westSouth = selectAt(-777, 333);
checkAbove('(z6) the mirrored selections have nodes', eastNorth.length, 20);
const mirrored = eastNorth.map((n) => `${n.level}:${-n.x - n.size},${-n.z - n.size}`).sort().join('|');
checkEq('…and are the same tree through (x, z) -> (-x - size, -z - size)',
  mirrored === westSouth.map((n) => `${n.level}:${n.x},${n.z}`).sort().join('|'), true);

// (z7) the near window on its negative side — the pyramid switch is invisible
// on all four margin strips, not only the one [3](h) walks.
const NEG_TILE_N = 129;                 // 129 points at 2 m = one 256 m tile
const NEG_TILE = {
  origin_x: -1792, origin_z: -768, step_m: BASE, rows: NEG_TILE_N, cols: NEG_TILE_N,
  heights: Array.from({ length: NEG_TILE_N }, (_, j) =>
    Array.from({ length: NEG_TILE_N }, (_, i) => CH(-1792 + BASE * i, -768 + BASE * j))),
};
const NEG_OV_N = 81;                    // 81 points at 64 m over [-2560, 2560]
const NEG_OVERVIEW = {
  origin_x: CX0, origin_z: CZ0, step_m: 64, rows: NEG_OV_N, cols: NEG_OV_N,
  heights: Array.from({ length: NEG_OV_N }, (_, j) =>
    Array.from({ length: NEG_OV_N }, (_, i) => CH(CX0 + 64 * i, CZ0 + 64 * j))),
};
const NEG_COMPOSITE = { tileM: TILE_M, overview: NEG_OVERVIEW,
                        tiles: new Map([['-7,-3', NEG_TILE]]) };
check('the loaded tile really answers inside itself',
  heightAt(NEG_COMPOSITE, -1700, -700) - sampleWorldHeight(NEG_TILE, -1700, -700), 0);
// The window: the tile grown by max(16, 2 · 64) = 128 m, on the 2 m lattice.
const NEG_X0 = -1792 - 128;
const NEG_Z0 = -768 - 128;
const NEG_COLS = Math.floor((-1536 + 128 - NEG_X0) / BASE) + 1;
const NEG_ROWS = Math.floor((-512 + 128 - NEG_Z0) / BASE) + 1;
checkEq('the near window around tile (-7, -3)',
  [NEG_X0, NEG_Z0, NEG_COLS, NEG_ROWS], [-1920, -896, 257, 257]);
checkEq('…so its rectangle is',
  [NEG_X0, NEG_Z0, NEG_X0 + (NEG_COLS - 1) * BASE, NEG_Z0 + (NEG_ROWS - 1) * BASE],
  [-1920, -896, -1408, -384]);
const negNear = buildPyramid((x, z) => heightAt(NEG_COMPOSITE, x, z),
                             NEG_X0, NEG_Z0, BASE, NEG_COLS, NEG_ROWS, MAX_LOD_LEVELS);
const negFar = buildPyramid((x, z) => sampleWorldHeight(NEG_OVERVIEW, x, z),
                            CX0, CZ0, 64, NEG_OV_N, NEG_OV_N, MAX_LOD_LEVELS);
const STRIPS = [
  ['west', [-1920, -1794], [-896, -384]],
  ['east', [-1534, -1408], [-896, -384]],
  ['north', [-1920, -1408], [-896, -770]],
  ['south', [-1920, -1408], [-510, -384]],
];
for (const [name, [sx0, sx1], [sz0, sz1]] of STRIPS) {
  let worstStrip = 0;
  let n = 0;
  for (let z = sz0; z <= sz1; z += 2) {
    for (let x = sx0; x <= sx1; x += 2) {
      worstStrip = Math.max(worstStrip,
        Math.abs(pyramidHeight(negNear, x, z, 0) - pyramidHeight(negFar, x, z, 0)));
      n += 1;
    }
  }
  check(`(z7) near == far in the ${name} margin strip (${n} samples)`, worstStrip, 0, 1e-4);
}

// ── [7] the analytic click ──────────────────────────────────────────────────
console.log('\n[7] the click is solved against the field, not raycast');
const zeros = (n) => Array.from({ length: n }, () => new Array(n).fill(0));
const FLAT = {
  tileM: 16, overview: null,
  tiles: new Map([['0,0', { origin_x: 0, origin_z: 0, step_m: 2, rows: 9, cols: 9,
    heights: zeros(9) }]]),
};
const down = rayGroundHit(FLAT, 4, 10, 4, 0, -1, 0, { minY: 0, maxY: 0 });
check('(r) straight down onto flat ground: x', down.x, 4, 1e-9);
check('…y', down.y, 0, 1e-9);
check('…z', down.z, 4, 1e-9);
const RAMP = {
  tileM: 16, overview: null,
  tiles: new Map([['0,0', { origin_x: 0, origin_z: 0, step_m: 2, rows: 9, cols: 9,
    heights: Array.from({ length: 9 }, () =>
      Array.from({ length: 9 }, (_, i) => (i * 2) / 2)) }]]),
};
check('the ramp reads x/2 at (7, 0)', heightAt(RAMP, 7, 0), 3.5);
const slope = rayGroundHit(RAMP, 0, 10, 0, 1, -1, 0, { minY: 0, maxY: 8 });
check('(s) down the ramp: x', slope.x, 20 / 3, 1e-6);
check('…y', slope.y, 10 / 3, 1e-6);
check('…and the hit really lies ON the ground',
  slope.y - heightAt(RAMP, slope.x, slope.z), 0, 1e-6);
checkEq('(t) a ray into the sky misses',
  rayGroundHit(RAMP, 0, 10, 0, 0, 1, 0, { minY: 0, maxY: 8 }), null);
checkEq('…and one running flat above the whole world too',
  rayGroundHit(RAMP, 0, 10, 0, 1, 0, 0, { minY: 0, maxY: 8 }), null);
const under = rayGroundHit(RAMP, 4, 1, 0, 0, -1, 0, { minY: 0, maxY: 8 });
check('(u) a ray starting under the ground hits at its own origin, y', under.y, 1, 1e-9);
check('…at x', under.x, 4, 1e-9);
checkEq('(v) no field at all is a miss',
  rayGroundHit(null, 0, 10, 0, 0, -1, 0, { minY: 0, maxY: 0 }), null);

// ── [10] the shading normal ─────────────────────────────────────────────────
console.log('\n[10] the shading normal is a function of the ground, not of the camera');
/** One axis of the fixture: period 8, 1 m tall, flat over the two lattice
 *  points on each side of its crest — see the docstring. */
const rung = (u) => {
  const i = Math.round(u / 2);
  return ((i % 4) + 4) % 4 >= 2 ? 1 : 0;
};
const RELIEF = (x, z) => rung(x) + rung(z);
const relPyr = buildPyramid(RELIEF, 0, 0, 2, 65, 65, MAX_LOD_LEVELS);
const relRect = [0, 0, 128, 128];
const SPAN = 2;
// (aa) the fixture is what the derivation says it is
checkEq('(aa) the lattice column reads 0,0,1,1,0,0,1,1',
  [0, 1, 2, 3, 4, 5, 6, 7].map((i) => rung(i * 2)), [0, 0, 1, 1, 0, 0, 1, 1]);
checkEq('…the level steps', relPyr.levels.map((l) => l.step), [2, 4, 8, 16, 32, 64]);
check('…level 1 is a triangle wave of period 8: h(36) − h(28)',
  pyramidHeight(relPyr, 36, 32, 1) - pyramidHeight(relPyr, 28, 32, 1), 0, 0);
let flatL2 = 0;
for (let x = 24; x <= 48; x += 1) flatL2 = Math.max(flatL2,
  Math.abs(pyramidHeight(relPyr, x, 32, 2) - pyramidHeight(relPyr, 24, 32, 2)));
check('…and level 2 is dead flat', flatL2, 0, 0);
// (bb) the normal at the crest flank, by hand
const nCrest = fragmentNormal(relPyr, relRect, null, 35, 35, SPAN);
const S18 = Math.sqrt(18);
check('(bb) n.x at (35, 35)', nCrest.x, -1 / S18, 1e-12);
check('…n.y', nCrest.y, 4 / S18, 1e-12);
check('…n.z', nCrest.z, -1 / S18, 1e-12);
const degOff = (n) => (Math.acos(Math.min(Math.max(n.y, -1), 1)) * 180) / Math.PI;
check('…the tilt from the vertical, degrees', degOff(nCrest), 19.4712206344, 1e-9);

/** The 200 cameras: 8 azimuths × 25 distances from 8 m to 1 000 m, as offsets
 *  from the ground point. Only their DISTANCE can reach the old law, so the
 *  sweep is written as one. */
const CAMS = [];
for (let a = 0; a < 8; a += 1) {
  for (let k = 0; k < 25; k += 1) {
    const d = 8 * (1000 / 8) ** (k / 24);
    const phi = (a * Math.PI) / 4;
    const pitch = 0.3 + 0.05 * a;
    CAMS.push([Math.cos(phi) * Math.cos(pitch) * d, Math.sin(pitch) * d,
               Math.sin(phi) * Math.cos(pitch) * d]);
  }
}
const NRANGES = lodRanges(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS);
check('the sweep crosses the morph ramps of levels 0…3, λ(1000)',
  lodLambda(1000, NRANGES), 3 + (1000 - 768) / 256, 1e-12);

/** THE OLD LAW, rebuilt from its own arithmetic: the vertex's morph pair,
 *  differenced at each span on the mip level that span names, blended by
 *  `f = λ − ⌊λ⌋`. `d` is the vertex's distance to the CAMERA — the whole
 *  defect in one argument. */
function oldNormal(x, z, d) {
  const lam = lodLambda(d, NRANGES);
  const level = Math.max(0, Math.min(Math.floor(lam), MAX_LOD_LEVELS - 1));
  const t = lam - level;
  const k = Math.min(Math.floor(t), MAX_LOD_LEVELS - 1);
  const f = t - k;
  const e1 = SPAN * 2 ** level * 2 ** k;
  const e2 = e1 * 2;
  const at = (px, pz, e) => gpuHeightAt(relPyr, relRect, null, px, pz, e);
  const one = (e) => {
    const hx = at(x + e, z, e) - at(x - e, z, e);
    const hz = at(x, z + e, e) - at(x, z - e, e);
    const len = Math.hypot(hx, 2 * e, hz);
    return [-hx / len, (2 * e) / len, -hz / len];
  };
  const [ax, ay, az] = one(e1);
  const [bx, by, bz] = one(e2);
  const mx = ax + (bx - ax) * f;
  const my = ay + (by - ay) * f;
  const mz = az + (bz - az) * f;
  const len = Math.hypot(mx, my, mz);
  return { x: mx / len, y: my / len, z: mz / len };
}

// The sun of `engine.ts` at 18:00 — the numbers, not a stand-in.
const SUN = [Math.cos(Math.PI) * 60, Math.max(0.08, Math.sin(Math.PI)) * 80, 25];
const SUN_LEN = Math.hypot(...SUN);
check('the 18:00 sun stands at |(−60, 6.4, 25)|', SUN_LEN, Math.sqrt(4265.96), 1e-9);
check('…which is an elevation of', (Math.asin(SUN[1] / SUN_LEN) * 180) / Math.PI,
  5.6233, 1e-3);
const dotSun = (n) => (n.x * SUN[0] + n.y * SUN[1] + n.z * SUN[2]) / SUN_LEN;

let worstNew = 0;
let swingOld = 0;
let crossNew = 0;
let crossOld = 0;
let unlitNew = 0;
for (let j = 0; j < 8; j += 1) {
  for (let i = 0; i < 8; i += 1) {
    const px = 32 + i;
    const pz = 32 + j;
    const ref = fragmentNormal(relPyr, relRect, null, px, pz, SPAN);
    let litNewSeen = false;
    let darkNewSeen = false;
    let litOldSeen = false;
    let darkOldSeen = false;
    let minOldY = 1;
    let maxOldY = -1;
    for (const [ox, oy, oz] of CAMS) {
      const d = Math.hypot(ox, oy, oz);
      // (cc) the same ground point, asked from every camera in the sweep
      const n = fragmentNormal(relPyr, relRect, null, px, pz, SPAN);
      worstNew = Math.max(worstNew, Math.abs(n.x - ref.x), Math.abs(n.y - ref.y),
                          Math.abs(n.z - ref.z));
      if (dotSun(n) > 0) litNewSeen = true; else darkNewSeen = true;
      // (dd) and the same point under the old law, from the same camera
      const o = oldNormal(px, pz, d);
      minOldY = Math.min(minOldY, o.y);
      maxOldY = Math.max(maxOldY, o.y);
      if (dotSun(o) > 0) litOldSeen = true; else darkOldSeen = true;
    }
    swingOld = Math.max(swingOld,
      Math.abs(degOff({ y: minOldY }) - degOff({ y: maxOldY })));
    if (litNewSeen && darkNewSeen) crossNew += 1;
    if (litOldSeen && darkOldSeen) crossOld += 1;
    if (dotSun(ref) <= 0) unlitNew += 1;
  }
}
check(`(cc) the normal over ${CAMS.length} cameras × 64 probes — worst deviation`,
  worstNew, 0, 0);
check('(dd) RED: the old law swings, degrees', swingOld, 19.4712206344, 1e-9);
checkAbove('…which is the 16° class the live world was measured at', swingOld, 16);
check('(ee) probes standing in their own shadow at a 5.62° sun', unlitNew, 24);
check('…terminator crossings over the whole sweep, NEW law', crossNew, 0, 0);
check('…RED: the same count under the OLD law', crossOld, 24);
check('…i.e. this share of the ground flipped with the camera, %',
  (crossOld / 64) * 100, 37.5, 1e-9);

// (ff) the shipped chunks, read as strings — the same kind of pin as [1]
const nglsl = terrainLodNormalGlsl();
checkEq('(ff) the fragment normal names no camera', /cameraPosition/.test(nglsl), false);
checkEq('…no node attribute', /iNode/.test(nglsl), false);
checkEq('…no LOD range', /uTlodRange/.test(nglsl), false);
checkEq('…and no pixel footprint (none was needed)', /fwidth|dFdx|dFdy/.test(nglsl), false);
checkEq('…while the vertex chunk computes no normal any more',
  /tlodNormal\b/.test(glsl), false);
// (gg) the cost, counted
check('(gg) height taps of the fragment normal', nglsl.split('tlodHeight(').length - 1, 4);
check('…texel reads per ground fragment, 4 taps × the bilinear\'s 4',
  (nglsl.split('tlodHeight(').length - 1) * 4, 16);
// The VERTEX cost, after the T-junction fix of 2026-08-22. `tlodCompute` taps
// the height twice for the blend and asks `tlodMorphAt` — one tap each — once
// for the vertex itself and once per step of the block descent, which runs at
// most MAX_LOD_LEVELS − 1 = 5 times. Worst case 2 + 1 + 5 = 8 taps per vertex,
// still fewer than the 11 the shader carried before the shading normal moved to
// the fragment stage.
const compute = glsl.slice(glsl.indexOf('void tlodCompute'));
check('…height taps in tlodCompute itself', compute.split('tlodHeight(').length - 1, 2);
check('…and morph reads, one before the descent and one inside it',
  compute.split('tlodMorphAt(').length - 1, 2);
check('…one tap each, so the worst case per vertex is',
  2 + 1 + (MAX_LOD_LEVELS - 1), 8);
checkBelow('…which is still under what the vertex stage cost before', 8, 11);

// ── [11] the transition probe ───────────────────────────────────────────────
console.log('\n[11] a split does not move the ground — the transition probe');

/**
 * A relief with structure AT the 2 m lattice.
 *
 * The compass world `CH` of [9] is three smooth waves whose shortest period is
 * 151 m, so its 2 m lattice and its 4 m decimation answer almost the same
 * number and the morph has nothing to carry — (hh) measures that, and it is
 * why this section brings its own field instead of borrowing that one: a
 * transition probe run on `CH` reports a pop of 4e-3 m and would pass on a
 * renderer with no morph at all.
 */
const TR = (x, z) => 9 * Math.sin(x / 197) * Math.cos(z / 151)
  + 0.9 * Math.sin(x / 1.3) * Math.cos(z / 1.1)
  + 0.6 * Math.sin(x / 2.9 + z / 3.7)
  + 1.4 * Math.sin(x / 7.3) * Math.sin(z / 6.1);
const TR_X0 = -2048;
const TR_Z0 = -1280;
const TR_N = 513;                             // 1 024 m at 2 m
const trPyr = buildPyramid(TR, TR_X0, TR_Z0, BASE, TR_N, TR_N, MAX_LOD_LEVELS);
const TR_RECT = [TR_X0, TR_Z0, TR_X0 + (TR_N - 1) * BASE, TR_Z0 + (TR_N - 1) * BASE];
const TR_EXT = [-2560, -2560, 2560, 2560];
let mipGap = 0;
let chGap = 0;
for (let z = -1000; z <= -900; z += 2) {
  for (let x = -1700; x <= -1600; x += 2) {
    mipGap = Math.max(mipGap, Math.abs(pyramidHeight(trPyr, x, z, 0)
      - pyramidHeight(trPyr, x, z, 1)));
    chGap = Math.max(chGap, Math.abs(CH(x, z) - (CH(x - 2, z) + CH(x + 2, z)) / 2));
  }
}
checkAbove('(hh) the fixture: the 2 m and the 4 m mip really disagree, metres',
  mipGap, 0.5);
checkBelow('…RED: the compass world of [9] does not, so it cannot probe a morph',
  chGap, 0.01);

// Honest per-tile boxes over the stretch the path can see; everything else
// falls back to a range that contains the whole field, which culls nothing.
const trStats = new Map();
for (let tz = -6; tz <= -1; tz += 1) {
  for (let tx = -9; tx <= -4; tx += 1) {
    let mn = Infinity;
    let mx = -Infinity;
    for (let j = 0; j <= TILE_M / BASE; j += 1) {
      for (let i = 0; i <= TILE_M / BASE; i += 1) {
        const v = TR(tx * TILE_M + i * BASE, tz * TILE_M + j * BASE);
        if (v < mn) mn = v;
        if (v > mx) mx = v;
      }
    }
    trStats.set(`${tx},${tz}`, { min: mn, max: mx });
  }
}
// The amplitudes sum to 9 + 0.9 + 0.6 + 1.4 = 11.9, so ±12 contains the field
// everywhere — a bound, which is all `nodeBounds` may ever be.
const TR_GLOBAL = { min: -12, max: 12 };
const trBounds = (x, z, size) => nodeBounds(trStats, TILE_M, TR_GLOBAL, x, z, size);
/**
 * THE RINGS THIS SECTION AND [12] MEASURE AGAINST, derived by hand from the
 * error list `CERR` and the 1 080 px pixel scale
 * 1080 / (2 · tan 22.5°) = 1080 / 0.8284271 = 1303.6753, so the error term is
 * `err · 1303.6753 / 2 = err · 651.8377` and the cap is twice the geometric
 * ring:
 *   i=0: max(128,  min(0.5862 · 651.84 =  382.1, 256))  =  256   <- at the cap
 *   i=1: max(256,  min(0.85   · 651.84 =  554.1, 512))  =  512   <- at the cap
 *   i=2: max(512,  min(1.0    · 651.84 =  651.8, 1024)) =  651.8 <- the rule
 *   i=3: max(1024, min(1.1636 · 651.84 =  758.5, 2048)) = 1024
 *   i=4: max(2048, min(3.3132 · 651.84 = 2159.7, 4096)) = 2159.7 <- the rule
 *   i=5: max(4096, 0)                                   = 4096
 * Two rings still stand OUT of the doubling (652 and 2160), which is what makes
 * this fixture a fair test of `lodLambda`'s ring-anchored ramp: level 3 owns
 * [652, 1024] and must not begin morphing at 0.5 · 1024 = 512.
 */
const TR_RANGES = lodRanges(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, CERR, camPixelScale);
checkEq('the rings this section measures against',
  TR_RANGES.map((r) => Math.round(r * 10) / 10), [256, 512, 651.8, 1024, 2159.7, 4096]);
checkEq('…two of them still out of the doubling, the rest held at the cap',
  TR_RANGES.map((r, i) => Math.round((r / (MIN_LOD_DISTANCE_M * (1 << i))) * 100) / 100),
  [2, 2, 1.27, 1, 1.05, 1]);

function trSelect(cam) {
  return selectLodNodes({
    x0: TR_EXT[0], z0: TR_EXT[1], x1: TR_EXT[2], z1: TR_EXT[3],
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: cam.x, camY: cam.y, camZ: cam.z,
    boundsOf: trBounds, levelErrorM: CERR, pixelScale: camPixelScale,
  });
}
/** One vertex of a node — the whole of `tlodCompute`, position and height. */
function trVertex(node, gx, gz, cam) {
  return lodVertex(node, gx, gz, trPyr, TR_RECT, trPyr, TR_EXT, cam, TR_RANGES);
}
/**
 * THE OLD λ, rebuilt from its own arithmetic: every level's ramp anchored at
 * the ORIGIN (`MORPH_START · range[i]`) instead of inside the level's own ring.
 * The two agree while the ranges double exactly and part company as soon as the
 * screen-space error rule widens one — which is why [12] uses it as a red probe.
 */
function redLambda(d, ranges) {
  let lam = 0;
  for (const r of ranges) {
    if (!(r > 0)) continue;
    const t = (d - MORPH_START * r) / ((1 - MORPH_START) * r);
    lam += t <= 0 ? 0 : t >= 1 ? 1 : t;
  }
  return lam;
}
/**
 * THE OLD `tlodCompute`, rebuilt: the morph coordinate read at the VERTEX
 * itself rather than at the block it snaps into, and the old λ. `morphedVertex`
 * is the shipped one — it takes t as an argument, so what this reimplements is
 * precisely the half that changed.
 */
function redVertex(node, gx, gz, pyr, rect, ext, cam, ranges) {
  const step = node.size / node.cells;
  let x0 = node.x + Math.min(gx, node.cells) * step;
  let z0 = node.z + Math.min(gz, node.cells) * step;
  if (ext) {
    x0 = Math.min(Math.max(x0, ext[0]), ext[2]);
    z0 = Math.min(Math.max(z0, ext[1]), ext[3]);
  }
  const y0 = gpuHeightAt(pyr, rect, pyr, x0, z0, 0);
  const d = Math.hypot(x0 - cam.x, y0 - cam.y, z0 - cam.z);
  const t = Math.max(0, ranges === null ? 0 : redLambda(d, ranges) - node.level);
  return { ...morphedVertex(node, gx, gz, pyr, rect, pyr, ext, t), t };
}

// (ii)/(jj) ONE parent, ONE child, ONE camera — where exactly do they differ?
// The two are built by hand: after the out-of-range rule of § A16.6 a rendered
// parent and a rendered child of it cannot both occur, and what is asked here is
// the VERTEX ARITHMETIC, which has to hold for any pair of levels that meet.
const trCam = { x: -1669.6, y: TR(-1669.6, -630.4) + 12, z: -630.4 };
const trParent = { x: -1280, z: -1152, size: 256, level: 2, cells: PATCH_N, morph: 0 };
const trChild = { x: -1280, z: -1152, size: 128, level: 1, cells: PATCH_N, morph: 0 };
let sharedWorstV = 0;
let oddOffset = 0;
let oddHeight = 0;
let redOffset = 0;
let redHeight = 0;
let deepest = 0;
for (let gz = 0; gz <= PATCH_N; gz += 1) {
  for (let gx = 0; gx <= PATCH_N; gx += 1) {
    const c = trVertex(trChild, gx, gz, trCam);
    deepest = Math.max(deepest, Math.floor(c.t));
    if (gx % 2 === 0 && gz % 2 === 0) {
      const p = trVertex(trParent, gx / 2, gz / 2, trCam);
      sharedWorstV = Math.max(sharedWorstV, Math.abs(c.x - p.x), Math.abs(c.z - p.z),
                              Math.abs(c.y - p.y));
      continue;
    }
    // The vertices the child ADDS are supposed to COLLAPSE onto their even twin
    // wherever the child is drawing on a lattice coarser than its own (k ≥ 1) —
    // that is what `mix(gi − gi mod m1, gi − gi mod m2, f)` does, and it does it
    // only if both use the SAME f.
    const e = trVertex(trChild, gx - (gx % 2), gz - (gz % 2), trCam);
    if (Math.floor(c.t) >= 1) {
      oddOffset = Math.max(oddOffset, Math.hypot(c.x - e.x, c.z - e.z));
      oddHeight = Math.max(oddHeight, Math.abs(c.y - e.y));
    }
    const rc = redVertex(trChild, gx, gz, trPyr, TR_RECT, TR_EXT, trCam, TR_RANGES);
    const re = redVertex(trChild, gx - (gx % 2), gz - (gz % 2), trPyr, TR_RECT,
                         TR_EXT, trCam, TR_RANGES);
    if (Math.floor(rc.t) >= 1) {
      redOffset = Math.max(redOffset, Math.hypot(rc.x - re.x, rc.z - re.z));
      redHeight = Math.max(redHeight, Math.abs(rc.y - re.y));
    }
  }
}
check('(ii) every vertex the parent and the child SHARE agrees', sharedWorstV, 0, 0);
checkAbove('…and the child really is drawing coarser than its own level here, k',
  deepest, 0);
// (jj) THE VERTICES THE CHILD ADDS. Reading the morph at the vertex's BLOCK
// instead of at the vertex (§ A16.6, `lodVertex`) makes every one of them land
// exactly on the twin it is meant to disappear into.
check('(jj) a vertex the child adds misses its own twin by, metres', oddOffset, 0, 0);
check('…and stands off the parent\'s surface by, metres', oddHeight, 0, 0);
checkAbove('…RED: with the morph read per VERTEX it missed by, metres',
  redOffset, 0.3);
checkAbove('…and hung this far off the parent\'s surface, metres', redHeight, 0.05);

// (kk) THE SWEEP: the surface before and after every transition, same camera.
/** The drawn mesh of one node — `tlodCompute` at all 1 089 vertices. */
function trMesh(node, cam) {
  const V = [];
  for (let gz = 0; gz <= PATCH_N; gz += 1) {
    const row = [];
    for (let gx = 0; gx <= PATCH_N; gx += 1) row.push(trVertex(node, gx, gz, cam));
    V.push(row);
  }
  return V;
}
function triY(a, b, c, x, z) {
  const den = (b.z - c.z) * (a.x - c.x) + (c.x - b.x) * (a.z - c.z);
  if (Math.abs(den) < 1e-12) return null;
  const l1 = ((b.z - c.z) * (x - c.x) + (c.x - b.x) * (z - c.z)) / den;
  const l2 = ((c.z - a.z) * (x - c.x) + (a.x - c.x) * (z - c.z)) / den;
  const l3 = 1 - l1 - l2;
  if (l1 < -1e-9 || l2 < -1e-9 || l3 < -1e-9) return null;
  return l1 * a.y + l2 * b.y + l3 * c.y;
}
/** The height a node's TRIANGLES answer at (x, z) — the surface, not the
 *  vertices. The morph slides a vertex up to `m2` cells towards the node's own
 *  corner, so the cell holding the point is looked for in a window that wide. */
function meshY(node, V, x, z) {
  const step = node.size / PATCH_N;
  const gi = Math.floor((x - node.x) / step);
  const gj = Math.floor((z - node.z) / step);
  for (let dj = -16; dj <= 16; dj += 1) {
    for (let di = -16; di <= 16; di += 1) {
      const i = gi + di;
      const j = gj + dj;
      if (i < 0 || j < 0 || i >= PATCH_N || j >= PATCH_N) continue;
      const t1 = triY(V[j][i], V[j + 1][i], V[j + 1][i + 1], x, z);
      if (t1 !== null) return t1;
      const t2 = triY(V[j][i], V[j + 1][i + 1], V[j][i + 1], x, z);
      if (t2 !== null) return t2;
    }
  }
  return null;
}
function trSurface(nodes, cam) {
  const cache = new Map();
  return (x, z) => {
    for (let i = 0; i < nodes.length; i += 1) {
      const n = nodes[i];
      if (x < n.x || x > n.x + n.size || z < n.z || z > n.z + n.size) continue;
      let V = cache.get(i);
      if (!V) { V = trMesh(n, cam); cache.set(i, V); }
      const y = meshY(n, V, x, z);
      if (y !== null) return y;
    }
    return null;
  };
}
const nkey = (n) => `${n.level}:${n.x},${n.z}`;
/** One walk: every frame where the node set changes, the OLD set's surface and
 *  the NEW set's surface are read at the same points from the same camera. The
 *  pop is reported in PIXELS as well as in metres, because a metre at 700 m is
 *  not the same defect as a metre at 30 m. */
function sweepTransitions(yawDeg, stepM, steps) {
  const ang = (yawDeg * Math.PI) / 180;
  const dx = Math.sin(ang);
  const dz = Math.cos(ang);
  let prevSet = null;
  let prevNodes = null;
  let transitions = 0;
  let worstM = 0;
  let worstPx = 0;
  let sumPx = 0;
  let samples = 0;
  for (let s = 0; s < steps; s += 1) {
    const cx = -1700 + dx * stepM * s;
    const cz = -600 + dz * stepM * s;
    const cam = { x: cx, y: TR(cx, cz) + 12, z: cz };
    const nodes = trSelect(cam);
    const set = new Set(nodes.map(nkey));
    if (prevSet) {
      const appeared = nodes.filter((n) => !prevSet.has(nkey(n)));
      if (appeared.length) {
        transitions += 1;
        const oldS = trSurface(prevNodes, cam);
        const newS = trSurface(nodes, cam);
        for (const n of appeared) {
          const q = n.size / 16;
          for (let j = 0; j <= 16; j += 1) {
            for (let i = 0; i <= 16; i += 1) {
              const x = n.x + i * q + 0.137;
              const z = n.z + j * q + 0.211;
              const oy = oldS(x, z);
              const ny = newS(x, z);
              if (oy === null || ny === null) continue;
              const d = Math.abs(ny - oy);
              const dist = Math.hypot(x - cam.x, cam.y - ny, z - cam.z);
              const px = (d * camPixelScale) / dist;
              worstM = Math.max(worstM, d);
              worstPx = Math.max(worstPx, px);
              sumPx += px;
              samples += 1;
            }
          }
        }
      }
    }
    prevSet = set;
    prevNodes = nodes;
  }
  return { transitions, worstM, worstPx, meanPx: sumPx / Math.max(samples, 1), samples };
}
// Heading 135° is east–north, the sector the shimmer was reported in.
const swept = sweepTransitions(135, 0.5, 120);
checkAbove('(kk) transitions over 60 m heading east–north', swept.transitions, 5);
checkAbove('…ground points compared across them', swept.samples, 1e4);
console.log(`       (worst pop ${swept.worstM.toFixed(4)} m, `
  + `mean ${swept.meanPx.toExponential(2)} px)`);
/**
 * THE BOUND, re-derived after § A16.6 (2026-08-22). It used to be a fraction of
 * `MAX_PIXEL_ERROR`: a split cost 0.101 m, a quarter of a pixel, and the check
 * asked for no more than that. It now costs NOTHING, and the reason is
 * structural rather than lucky — the drawn surface is a function of the world
 * point and the block it lies in, and neither of those knows which piece drew
 * it, so exchanging one piece for four cannot move the ground at all.
 *
 * SO THE BOUND IS THE PROBE'S OWN ARITHMETIC, and it is worth writing down what
 * that is, because it is not the double epsilon. `meshY` reads the surface by
 * BARYCENTRIC interpolation, dividing by the triangle's determinant `den`, and
 * a morphed patch is full of triangles the morph has collapsed: three vertices
 * on one line, `den` a rounding residue of products of world coordinates around
 * 1.7e3 m, i.e. (1.7e3)² · 2.2e−16 ≈ 6e−10 — just past the 1e−12 the probe
 * rejects a triangle at. Such a sliver returns weights whose noise is amplified
 * by the same tiny divisor, so the floor of the METHOD is nanometres and moves
 * with the fixture's rings, while the floor of the LAW is the 2.2e−13 that [12]
 * measures on vertices, where no division happens. The threshold is therefore
 * the micrometre [12](mm) calls "on the chain" — six orders under the 0.101 m
 * the old rule cost, and nine under the ground's own relief.
 */
check('…the worst of them, metres', swept.worstM, 0, 1e-6);
// 1 µm at the 10 m the nearest sample can stand from the eye is
// 1e-6 · 1303.7 / 10 = 1.3e-4 px, so a thousandth of a pixel is the matching
// ceiling on the other axis.
check('…and in PIXELS of a 45° / 1 080 px view', swept.worstPx, 0, 1e-3);

// (ll) NO COMPASS DIRECTION. Hypothesis (B) was a corner bias in the box
// distance — nodes east and north of the camera splitting earlier than their
// mirror images. Mirror the WORLD through the origin (every tile (tx, tz)
// becomes (−tx−1, −tz−1), because tile tx spans [tx·T, (tx+1)·T)) and walk the
// opposite heading: the selection must answer the mirrored tree at every step.
const mirStats = new Map();
for (const [k, v] of trStats) {
  const [tx, tz] = k.split(',').map(Number);
  mirStats.set(`${-tx - 1},${-tz - 1}`, v);
}
const mirBounds = (x, z, size) => nodeBounds(mirStats, TILE_M, TR_GLOBAL, x, z, size);
let mirrorWorst = 0;
let mirrorFrames = 0;
for (let s = 0; s < 120; s += 1) {
  const cx = -1700 + Math.sin((135 * Math.PI) / 180) * 0.5 * s;
  const cz = -600 + Math.cos((135 * Math.PI) / 180) * 0.5 * s;
  const cy = TR(cx, cz) + 12;
  const here = selectLodNodes({
    x0: TR_EXT[0], z0: TR_EXT[1], x1: TR_EXT[2], z1: TR_EXT[3],
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: cx, camY: cy, camZ: cz, boundsOf: trBounds,
    levelErrorM: CERR, pixelScale: camPixelScale,
  });
  const there = selectLodNodes({
    x0: TR_EXT[0], z0: TR_EXT[1], x1: TR_EXT[2], z1: TR_EXT[3],
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: -cx, camY: cy, camZ: -cz, boundsOf: mirBounds,
    levelErrorM: CERR, pixelScale: camPixelScale,
  });
  const a = here.map((n) => `${n.level}:${-n.x - n.size},${-n.z - n.size}`).sort().join('|');
  const b = there.map(nkey).sort().join('|');
  if (a !== b) mirrorWorst += 1;
  mirrorFrames += 1;
}
check('(ll) frames whose mirror image is a different tree', mirrorWorst, 0);
checkAbove('…frames walked east–north and its mirror', mirrorFrames, 100);

// ── [12] the T-junction probe ───────────────────────────────────────────────
console.log('\n[12] no vertex hangs beside a neighbour\'s edge — the T-junction probe');

/** Distance from a point to an axis-aligned box, the shipped `boxDistance`
 *  rewritten for the red selection below. */
function redBoxDist(px, py, pz, x0, y0, z0, x1, y1, z1) {
  const dx = Math.max(x0 - px, 0, px - x1);
  const dy = Math.max(y0 - py, 0, py - y1);
  const dz = Math.max(z0 - pz, 0, pz - z1);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}
/**
 * THE OLD SELECTION, rebuilt: split on the node's own distance and hand every
 * one of the four children the finer level, whether that child's own distance
 * is still inside the ring or not. `cells` is `PATCH_N` for all of them, since
 * a parent quadrant is exactly what this rule cannot express.
 */
function redSelect(o) {
  const out = [];
  const top = o.levels - 1;
  const ranges = lodRanges(o.minLodDistance, o.levels, o.levelErrorM, o.pixelScale);
  const visit = (x, z, level) => {
    const size = o.leafM * (1 << level);
    if (x >= o.x1 || z >= o.z1 || x + size <= o.x0 || z + size <= o.z0) return;
    const b = o.boundsOf(x, z, size);
    const d = redBoxDist(o.camX, o.camY, o.camZ,
                         x, b.min, z, x + size, b.max, z + size);
    if (level > 0 && ranges[level - 1] > 0 && d < ranges[level - 1]) {
      const half = size / 2;
      visit(x, z, level - 1);
      visit(x + half, z, level - 1);
      visit(x, z + half, level - 1);
      visit(x + half, z + half, level - 1);
      return;
    }
    out.push({ x, z, size, level, cells: PATCH_N,
               morph: Math.max(0, redLambda(d, ranges) - level) });
  };
  const rootSize = o.leafM * (1 << top);
  for (let rz = Math.floor(o.z0 / rootSize); rz <= Math.floor((o.z1 - 1e-6) / rootSize); rz += 1) {
    for (let rx = Math.floor(o.x0 / rootSize); rx <= Math.floor((o.x1 - 1e-6) / rootSize); rx += 1) {
      visit(rx * rootSize, rz * rootSize, top);
    }
  }
  return out;
}

/**
 * The four DRAWN edges of a piece, each as a chain of (along-axis, height)
 * points. The morph slides a vertex along the edge as well as across it, so the
 * chain is not a graph over the axis and the comparison below has to be a
 * distance to the chain rather than an evaluation at a coordinate — that is not
 * pedantry: measured with an evaluation, two IDENTICAL chains report 0.1 m
 * wherever the old rule folded one back on itself.
 */
function edgesOf(node, vertexFn, cam) {
  const c = node.cells;
  const line = (fn) => {
    const pts = [];
    for (let g = 0; g <= c; g += 1) pts.push(fn(g));
    return pts;
  };
  return {
    west: line((g) => { const v = vertexFn(node, 0, g, cam); return { a: v.z, y: v.y }; }),
    east: line((g) => { const v = vertexFn(node, c, g, cam); return { a: v.z, y: v.y }; }),
    north: line((g) => { const v = vertexFn(node, g, 0, cam); return { a: v.x, y: v.y }; }),
    south: line((g) => { const v = vertexFn(node, g, c, cam); return { a: v.x, y: v.y }; }),
  };
}
/** Distance from a point to a polygonal chain, in the (along, height) plane. */
function distToChain(pts, a, y) {
  let best = Infinity;
  for (let i = 0; i + 1 < pts.length; i += 1) {
    const dx = pts[i + 1].a - pts[i].a;
    const dy = pts[i + 1].y - pts[i].y;
    const len2 = dx * dx + dy * dy;
    let u = len2 > 0 ? ((a - pts[i].a) * dx + (y - pts[i].y) * dy) / len2 : 0;
    u = u < 0 ? 0 : u > 1 ? 1 : u;
    const d = Math.hypot(pts[i].a + u * dx - a, pts[i].y + u * dy - y);
    if (d < best) best = d;
  }
  return best;
}
/**
 * One camera: select, then walk every pair of pieces that share a stretch of
 * edge and ask how far each side's vertices stand off the other side's chain.
 * `triangles` counts the NON-DEGENERATE ones, `beyond` the pieces whose own
 * nearest point has already left their level's ring.
 */
function tjunctionAt(cam, selectFn, vertexFn, acc) {
  const nodes = selectFn(cam);
  const E = nodes.map((n) => edgesOf(n, vertexFn, cam));
  for (const n of nodes) {
    acc.triangles += n.cells * n.cells * 2;
    if (n.level < MAX_LOD_LEVELS - 1 && n.morph > 1 + 1e-12) acc.beyond += 1;
    if (n.morph < 0) acc.negative += 1;
  }
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = 0; j < nodes.length; j += 1) {
      if (i === j) continue;
      const A = nodes[i];
      const B = nodes[j];
      let pair = null;
      if (Math.abs(A.x + A.size - B.x) < 1e-9) {
        const lo = Math.max(A.z, B.z);
        const hi = Math.min(A.z + A.size, B.z + B.size);
        if (hi - lo > 1e-9) pair = [E[i].east, E[j].west, lo, hi];
      } else if (Math.abs(A.z + A.size - B.z) < 1e-9) {
        const lo = Math.max(A.x, B.x);
        const hi = Math.min(A.x + A.size, B.x + B.size);
        if (hi - lo > 1e-9) pair = [E[i].south, E[j].north, lo, hi];
      }
      if (!pair) continue;
      const [pa, pb, lo, hi] = pair;
      for (const [from, onto] of [[pa, pb], [pb, pa]]) {
        for (const p of from) {
          if (p.a < lo - 1e-9 || p.a > hi + 1e-9) continue;
          const d = distToChain(onto, p.a, p.y);
          if (d > acc.worst) acc.worst = d;
          if (d > 1e-6) acc.bad += 1;
          acc.tested += 1;
        }
      }
    }
  }
  acc.nodes += nodes.length;
  acc.frames += 1;
}
/** The whole sweep: the 60 m NE walk of (kk) plus all 24 headings of a
 *  15°-compass at its start, which is where the finding was reported. */
function tjunctionSweep(selectFn, vertexFn) {
  const acc = { worst: 0, bad: 0, tested: 0, nodes: 0, frames: 0,
                triangles: 0, beyond: 0, negative: 0 };
  for (let s = 0; s < 120; s += 1) {
    const cx = -1700 + Math.sin((135 * Math.PI) / 180) * 0.5 * s;
    const cz = -600 + Math.cos((135 * Math.PI) / 180) * 0.5 * s;
    tjunctionAt({ x: cx, y: TR(cx, cz) + 12, z: cz }, selectFn, vertexFn, acc);
  }
  for (let h = 0; h < 24; h += 1) {
    const a = (h * 15 * Math.PI) / 180;
    const cx = -1700 + Math.sin(a) * 30;
    const cz = -600 + Math.cos(a) * 30;
    tjunctionAt({ x: cx, y: TR(cx, cz) + 12, z: cz }, selectFn, vertexFn, acc);
  }
  return acc;
}
const redTrSelect = (cam) => redSelect({
  x0: TR_EXT[0], z0: TR_EXT[1], x1: TR_EXT[2], z1: TR_EXT[3],
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
  camX: cam.x, camY: cam.y, camZ: cam.z,
  boundsOf: trBounds, levelErrorM: CERR, pixelScale: camPixelScale,
});
const now = tjunctionSweep(trSelect, (n, gx, gz, cam) => trVertex(n, gx, gz, cam));
const before = tjunctionSweep(redTrSelect,
  (n, gx, gz, cam) => redVertex(n, gx, gz, trPyr, TR_RECT, TR_EXT, cam, TR_RANGES));
checkAbove('(mm) camera settings walked (120 m of path + 24 headings)', now.frames, 140);
checkAbove('…edge vertices measured against the neighbour\'s chain', now.tested, 3e6);
check('(mm) vertices standing off the neighbour\'s edge by more than 1 µm',
  now.bad, 0);
check('…and the worst of them, metres', now.worst, 0, 1e-9);
console.log(`       (worst ${now.worst.toExponential(2)} m over ${now.tested} tests)`);
checkAbove('(nn) RED: the old rule leaves this many hanging vertices',
  before.bad, 1e4);
checkAbove('…and the worst of them stands off by, metres', before.worst, 0.05);
console.log(`       (RED worst ${before.worst.toFixed(4)} m, `
  + `${before.bad} of ${before.tested} tests)`);
// (oo) THE OUT-OF-RANGE RULE ITSELF: `morph` is λ at the piece's nearest point
// minus its level, so `morph ≤ 1` says the piece lies inside its own ring.
check('(oo) pieces drawn at a level whose ring they have left', now.beyond, 0);
check('…and none with a negative morph either', now.negative, 0);
checkAbove('…RED: under the old rule this many were', before.beyond, 1e3);
// (pp) WHAT IT COSTS. The out-of-range quadrants draw a child-sized square at
// the parent's spacing — a quarter of the triangles the old rule spent on the
// same ground — so the far half of the ground gets cheaper, not dearer.
const triNow = Math.round(now.triangles / now.frames);
const triRed = Math.round(before.triangles / before.frames);
console.log(`       (${Math.round(now.nodes / now.frames)} pieces / `
  + `${triNow} triangles per frame, was `
  + `${Math.round(before.nodes / before.frames)} / ${triRed})`);
checkBelow('(pp) real triangles per frame, as a share of the old rule\'s',
  triNow / triRed, 1);

// ── [13] the flat world gets the rings too ──────────────────────────────────
console.log('\n[13] a level world is drawn by the rings, not by its roots');

/**
 * THE 3D-TEST WORLD, as the readout described it: a world frame of about 7 km,
 * no height areas, the location at (-10, 10). Its overview is level, so the
 * shortcut that was deleted on 2026-08-22 gave it `minLodDistance` 0 — every
 * range 0, nothing ever split, the whole world drawn from its roots.
 *
 * THE CALIBRATION IS HAND-DERIVED AND MATCHES THE PANEL. A leaf is
 * `PATCH_N · baseStep` = 32 · 2 = 64 m and the tree has 6 levels, so a root is
 * 64 · 2^5 = 2 048 m. The frame [-3500, 3500] reaches roots
 * floor(-3500/2048) = -2 up to floor(3499.999/2048) = 1, i.e. 4 per axis and
 * 16 in all — which is exactly the "16" the isolation panel read with the
 * frustum test switched off, and the 3 to 4 it read with it on were those of
 * the 16 that a 800 m / 45° frustum kept.
 */
const FLAT_EXT = [-3500, -3500, 3500, 3500];
const FLAT_AT = [-10, 10];
const flatLevel = () => ({ min: 0, max: 0 });
const flatSelect = (eye, minLod) => selectLodNodes({
  x0: FLAT_EXT[0], z0: FLAT_EXT[1], x1: FLAT_EXT[2], z1: FLAT_EXT[3],
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: minLod,
  camX: eye[0], camY: eye[1], camZ: eye[2],
  boundsOf: flatLevel, pixelScale: camPixelScale,
});
// The engine's own camera law (`scene/engine.ts`): pitch 18° at MIN_DIST 0.8 m,
// 62° at MAX_DIST 150 m, the eye `dist` behind and above the point it looks at.
const flatEye = (yawDeg, dist) => {
  const zoomK = Math.min(Math.max((dist - 0.8) / (150 - 0.8), 0), 1);
  const pitch = 18 + (62 - 18) * Math.sqrt(zoomK);
  const a = (yawDeg * Math.PI) / 180;
  const pr = (pitch * Math.PI) / 180;
  const fwd = [Math.sin(a) * Math.cos(pr), -Math.sin(pr), Math.cos(a) * Math.cos(pr)];
  return [FLAT_AT[0] - fwd[0] * dist, -fwd[1] * dist, FLAT_AT[1] - fwd[2] * dist];
};
const flatCam = flatEye(45, 12);
// (qq) the model IS the world the panel measured — before anything is asserted
// about the new rule.
const wasRoots = flatSelect(flatCam, 0);
check('(qq) the deleted shortcut drew the 7 km world as this many pieces',
  wasRoots.length, 16);
checkEq('…every one of them a 2 048 m root',
  [...new Set(wasRoots.map((n) => n.size))], [64 * 2 ** (MAX_LOD_LEVELS - 1)]);
// (rr) …and what the rings make of the same camera.
const nowRings = flatSelect(flatCam, MIN_LOD_DISTANCE_M);
checkAbove('(rr) the same camera with the rings, pieces', nowRings.length, 100);
checkBelow('…and still a three-digit count', nowRings.length, 1000);
console.log(`       (${wasRoots.length} pieces of 2048 m -> ${nowRings.length} pieces, `
  + `${[...new Set(nowRings.map((n) => n.size))].sort((a, b) => a - b).join('/')} m)`);
/**
 * (ss) NO PIECE IS WIDER THAN ITS OWN DISTANCE, and that is the ring structure
 * written as one number. `lodRange[i] = 128 · 2^i` and a leaf is 64 m, so a
 * whole node at level L has `size = 64 · 2^L` and is only emitted once its box
 * distance has reached `lodRange[L-1] = 128 · 2^(L-1) = 64 · 2^L` — the same
 * number. A level-0 leaf has no inner ring and is capped by the leaf size
 * instead. Under the deleted shortcut a piece 2 048 m wide stood at distance 0,
 * i.e. 32 leaves wide where the rule allows one.
 */
const ringBreaches = (picked, eye) => {
  let bad = 0;
  let worst = 0;
  for (const n of picked) {
    const d = Math.hypot(Math.max(n.x - eye[0], 0, eye[0] - (n.x + n.size)),
                         eye[1],
                         Math.max(n.z - eye[2], 0, eye[2] - (n.z + n.size)));
    if (d > HAZE_M) continue;
    const allowed = Math.max(LEAF_M, d);
    if (n.size > allowed + 1e-9) { bad += 1; worst = Math.max(worst, n.size / allowed); }
  }
  return { bad, worst };
};
check('(ss) pieces inside the haze wider than their own distance', 
  ringBreaches(nowRings, flatCam).bad, 0);
checkAbove('…RED: under the deleted shortcut, this many were',
  ringBreaches(wasRoots, flatCam).bad, 3);
console.log(`       (RED: the worst stood ${ringBreaches(wasRoots, flatCam).worst.toFixed(0)}x `
  + 'wider than the ring allows)');
// (tt) …and the SHAPED worlds keep the property, so it is the rule and not an
// accident of a level field.
for (const [name, picked, eye] of [
  ['the compass world', selectLodNodes({
    x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: REPORTED_X, camY: CH(REPORTED_X, REPORTED_Z) + 14, camZ: REPORTED_Z,
    boundsOf: honest, levelErrorM: CERR, pixelScale: camPixelScale,
  }), [REPORTED_X, CH(REPORTED_X, REPORTED_Z) + 14, REPORTED_Z]],
]) {
  check(`(tt) ${name}: pieces inside the haze wider than their distance`,
    ringBreaches(picked, eye).bad, 0);
}
// (uu) THE CEILING. Nothing is culled any more, so the whole frame is selected
// every frame — the number the instance buffer is allocated for has to hold it
// over every camera, not over the lucky one.
let flatMax = 0;
let flatFrames = 0;
for (const dist of [0.8, 3, 12, 40, 90, 150]) {
  for (let yaw = 0; yaw < 360; yaw += 5) {
    flatMax = Math.max(flatMax, flatSelect(flatEye(yaw, dist), MIN_LOD_DISTANCE_M).length);
    flatFrames += 1;
  }
}
checkAbove('(uu) camera settings swept over the flat 7 km world', flatFrames, 400);
checkBelow('…and the largest selection any of them produced', flatMax, MAX_NODES);
console.log(`       (flat world at most ${flatMax} pieces, compass world at most `
  + `${maxSweepNodes}, buffer ${MAX_NODES})`);

// ── [14] the ceiling coarsens, it does not truncate ─────────────────────────
console.log('\n[14] the widening is capped at one doubling, and the ceiling coarsens '
  + 'instead of dropping the tail');

/**
 * THE LIVE WORLD, by its numbers. `world_bounds` comes from
 * `core/world_ops.py` (every placed location's outline and every painted
 * polygon), the ground plate grows it by `ground.BASE_MARGIN_M` = 60 m, and
 * the error list is the per-level MAXIMUM of `heightfield.tile_stats` over the
 * tiles the client really holds — the 64-tile world-wide `index_stats_payload`
 * block plus the 25 tiles inside the 560 m load radius. Baked off a COPY of
 * `worlds/Anima Divide/world.db` through `heightfield.rasterize_tile` /
 * `tile_stats`, i.e. the server's own arithmetic and not a fetch.
 *
 * The boxes are FLAT here on purpose: that world's whole relief spans 5.4 m
 * (-2.0 … 3.4), which against a 1 538 m ring is a rounding error — so the
 * count below is a property of the RINGS and cannot be blamed on a hill.
 */
const LIVE_BOUNDS = { min_x: -7907.36, min_z: -6505.66, max_x: 8544.28, max_z: 7726.95 };
const LIVE_MARGIN_M = 60;                       // ground.BASE_MARGIN_M
const LIVE_EXT = [LIVE_BOUNDS.min_x - LIVE_MARGIN_M, LIVE_BOUNDS.min_z - LIVE_MARGIN_M,
                  LIVE_BOUNDS.max_x + LIVE_MARGIN_M, LIVE_BOUNDS.max_z + LIVE_MARGIN_M];
const LIVE_ERR = [0, 1.9913, 2.945, 3.7229, 3.5949, 4.3741];
const liveFlat = () => ({ min: 0, max: 0 });
/** `ranges` is how the red probes put the UNCAPPED ladder back: the shipped
 *  `lodRanges` can no longer produce it, and `LodSelectOpts.ranges` is the one
 *  door the selection has for rings it did not compute itself. */
const liveOpts = (eye, px, ranges) => ({
  x0: LIVE_EXT[0], z0: LIVE_EXT[1], x1: LIVE_EXT[2], z1: LIVE_EXT[3],
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
  camX: eye[0], camY: eye[1], camZ: eye[2], boundsOf: liveFlat,
  levelErrorM: LIVE_ERR, pixelScale: px / (2 * Math.tan((FOV_DEG * Math.PI) / 360)),
  ...(ranges ? { ranges } : {}),
});
/** The engine's camera law again, about an arbitrary point of the live frame. */
const liveEye = (yawDeg, dist, tx, tz) => {
  const zoomK = Math.min(Math.max((dist - 0.8) / (150 - 0.8), 0), 1);
  const pitch = (18 + (62 - 18) * Math.sqrt(zoomK)) * Math.PI / 180;
  const a = (yawDeg * Math.PI) / 180;
  return [tx + Math.sin(a) * Math.cos(pitch) * dist, Math.sin(pitch) * dist,
          tz + Math.cos(a) * Math.cos(pitch) * dist];
};
/**
 * Ground the selection does not own — a 256 m lattice over the WHOLE frame,
 * because the shipped rule culls nothing and therefore owes every square of
 * it. The haze half is reported apart: an uncovered sample nearer than 520 m
 * is not a coarser picture, it is sky.
 */
function uncovered(picked, eye) {
  let miss = 0;
  let tested = 0;
  let nearMiss = 0;
  let nearTested = 0;
  let nearest = Infinity;
  for (let z = LIVE_EXT[1] + 64; z < LIVE_EXT[3]; z += 256) {
    for (let x = LIVE_EXT[0] + 64; x < LIVE_EXT[2]; x += 256) {
      tested += 1;
      let owned = false;
      for (const n of picked) {
        if (x >= n.x && x <= n.x + n.size && z >= n.z && z <= n.z + n.size) {
          owned = true;
          break;
        }
      }
      const d = Math.hypot(x - eye[0], z - eye[2]);
      if (d <= HAZE_M) {
        nearTested += 1;
        if (!owned) { nearMiss += 1; nearest = Math.min(nearest, d); }
      }
      if (!owned) miss += 1;
    }
  }
  return { miss, tested, nearMiss, nearTested, nearest };
}

// (vv) THE CAPPED LADDER, at both viewports — the derivation is in the
// docstring, and the number the cap exists to refuse is asserted beside it.
const livePx = (px) => px / (2 * Math.tan((FOV_DEG * Math.PI) / 360));
const liveCam = liveEye(45, 12, REPORTED_X, REPORTED_Z);
const liveRanges = lodRanges(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, LIVE_ERR, livePx(1280));
const liveRanges2160 = lodRanges(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, LIVE_ERR,
                                 livePx(2160));
check('the pixel scale of a 1 280 px buffer at 45°', livePx(1280), 1545.0967, 1e-4);
check('(vv) what level 0 asked for, metres',
  Math.round(((LIVE_ERR[1] * livePx(1280)) / MAX_PIXEL_ERROR) * 10) / 10, 1538.4);
check('…and what the cap gives it', liveRanges[0], MIN_LOD_DISTANCE_M * MAX_RANGE_WIDENING);
checkEq('(vv) the capped ladder at 1 280 px',
  liveRanges.map((r) => Math.round(r * 10) / 10), [256, 512, 1024, 2048, 3379.2, 4096]);
checkEq('…and at 2 160 px, where level 4 reaches its cap too',
  liveRanges2160.map((r) => Math.round(r * 10) / 10), [256, 512, 1024, 2048, 4096, 4096]);
checkEq('…so the four inner rings do not depend on the buffer height at all',
  liveRanges.slice(0, 4), liveRanges2160.slice(0, 4));
checkEq('…and no ring stands more than one doubling out of the ladder',
  liveRanges.every((r, i) => r <= MIN_LOD_DISTANCE_M * (1 << i) * MAX_RANGE_WIDENING + 1e-9)
  && liveRanges2160.every((r, i) =>
    r <= MIN_LOD_DISTANCE_M * (1 << i) * MAX_RANGE_WIDENING + 1e-9), true);
// RED: the uncapped ladder is a different world — a 1 538 m innermost ring.
const liveUncapped = uncappedLadder(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, LIVE_ERR,
                                    livePx(1280), true);
check('…RED: uncapped, lodRange[0] was, metres',
  Math.round(liveUncapped[0] * 10) / 10, 1538.4);
checkAbove('…RED: which is this many times the geometric 128 m',
  Math.round(liveUncapped[0] / MIN_LOD_DISTANCE_M), 11);

// (vv2) the pieces that follow from the capped ladder.
const live1280 = selectLodFitted(liveOpts(liveCam, 1280));
const live2160 = selectLodFitted(liveOpts(liveCam, 2160));
const perLv = (sel) => {
  const c = [0, 0, 0, 0, 0, 0];
  for (const n of sel.nodes) c[n.level] += 1;
  return c;
};
check('(vv2) pieces at the reported camera, 1 280 px', live1280.nodes.length, 372);
check('…and at 2 160 px', live2160.nodes.length, 390);
check('…the rings did not have to be coarsened for either',
  live1280.coarsenings + live2160.coarsenings, 0);
checkEq('…and levels 0…3 are the same count at both, ring for ring',
  perLv(live1280).slice(0, 4), perLv(live2160).slice(0, 4));
checkEq('…the whole per-level split at 1 280 px', perLv(live1280),
  [67, 58, 59, 65, 49, 74]);
checkEq('…and at 2 160 px, where only levels 4 and 5 move',
  perLv(live2160), [67, 58, 59, 65, 70, 71]);
check('…half-sized quadrants among the 372',
  live1280.nodes.filter((n) => n.cells === PATCH_N / 2).length, 92);
// RED: what the SAME camera drew before the cap — the uncapped rings handed in.
const liveRed1280 = selectLodNodes(liveOpts(liveCam, 1280, liveUncapped));
check('…RED: the uncapped ladder drew this many pieces there', liveRed1280.length, 2952);
check('…RED: of which finest-level (64 m) ones',
  liveRed1280.filter((n) => n.level === 0).length, 1914);

// (ww) RED — the uncapped world at a 2 160 px drawing buffer, WITHOUT the guard.
// The rings are handed in rather than asked for: `MAX_RANGE_WIDENING` is not a
// switch, and a probe that made the shipped function misbehave would measure the
// probe. The ceiling itself is a property of the SELECTION and has to stay
// proven for any ring ladder, capped or not.
const redRanges = uncappedLadder(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, LIVE_ERR,
                                 livePx(2160), true);
checkEq('(ww) the uncapped ladder the red probe selects against',
  redRanges.map((r) => Math.round(r * 10) / 10),
  [2596, 3839.3, 4853.5, 4853.5, 5702.4, 5702.4]);
check('…where the raw level-3 term fell below level 2\'s and was raised',
  Math.round(((LIVE_ERR[4] * livePx(2160)) / MAX_PIXEL_ERROR) * 10) / 10, 4686.6);
const redCam = liveEye(45, 12, 3000, 3000);
const redRaw = selectLodNodes(liveOpts(redCam, 2160, redRanges));
const redCover = uncovered(redRaw, redCam);
check('(ww) RED: selectLodNodes alone stops at exactly the ceiling',
  redRaw.length, MAX_NODES);
checkAbove('…RED: frame samples it left with no ground at all',
  redCover.miss, 1000);
check(`…RED: of ${redCover.nearTested} samples inside the haze, uncovered`,
  redCover.nearMiss, 6);
checkBelow('…RED: and the nearest of those stood this far from the camera, m',
  Math.round(redCover.nearest), HAZE_M);

// (xx) the guard on the very same camera and the very same rings.
const redFit = selectLodFitted(liveOpts(redCam, 2160, redRanges));
checkBelow('(xx) selectLodFitted stays under the ceiling', redFit.nodes.length, MAX_NODES);
check('…by halving the rings this many times', redFit.coarsenings, 1);
const fitCover = uncovered(redFit.nodes, redCam);
check(`…and of the ${fitCover.tested} frame samples, uncovered`, fitCover.miss, 0);
check('…inside the haze, uncovered', fitCover.nearMiss, 0);
/**
 * HALVING IS A PURE RESCALING OF λ, which is what makes it safe for the seam.
 * `lodLambda` anchors each ramp inside its own ring — `s_i = range[i−1] +
 * MORPH_START · (range[i] − range[i−1])` — so halving every range halves every
 * `s_i` with it and `(d − s/2)/((r − s)/2) = (2d − s)/(r − s)`: the coarsened
 * λ at d is the honest λ at 2d, EXACTLY. Nothing about the morph's shape
 * changes, only how far out it happens, so the arguments of [8] and [12] carry
 * over unchanged. (The identity λ(range[i]) = i + 1 is NOT asserted here: this
 * world's error list collapses two rings to zero width — range[2] = range[3]
 * and range[4] = range[5] — and `lodLambda` steps over such a ring by design,
 * so λ skips a level there. Nothing is ever emitted at a zero-width level.)
 */
checkEq('…the coarsened rings are still monotone',
  redFit.ranges.every((r, i) => i === 0 || r >= redFit.ranges[i - 1]), true);
checkEq('…and are exactly the rings it started from, halved',
  redFit.ranges.every((r, i) => Math.abs(r - redRanges[i] / 2) < 1e-9), true);
let lamOff = 0;
for (let d = 0; d <= 4000; d += 7) {
  const a = lodLambda(d, redFit.ranges);
  const b = lodLambda(2 * d, redRanges);
  lamOff = Math.max(lamOff, Math.abs(a - b));
}
check('…so the coarsened λ(d) IS the honest λ(2d), worst deviation', lamOff, 0, 1e-12);
console.log(`       (${redRaw.length} truncated pieces, ${redCover.miss}/${redCover.tested} `
  + `frame samples with no ground -> ${redFit.nodes.length} coarsened pieces, 0 uncovered)`);

// (yy) …and it is a no-op wherever the honest rings already fit — the live
// world under the SHIPPED (capped) rings first, which is the case that used to
// need the guard and no longer does.
check('(yy) the live world, capped rings: coarsenings', live1280.coarsenings, 0);
check('…and the very list selectLodNodes returns',
  live1280.nodes.length, selectLodNodes(liveOpts(liveCam, 1280)).length);
const flatFit = selectLodFitted({
  x0: FLAT_EXT[0], z0: FLAT_EXT[1], x1: FLAT_EXT[2], z1: FLAT_EXT[3],
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
  camX: flatCam[0], camY: flatCam[1], camZ: flatCam[2],
  boundsOf: flatLevel, pixelScale: camPixelScale,
});
check('(yy) the level world: coarsenings', flatFit.coarsenings, 0);
check('…and its list too', flatFit.nodes.length, nowRings.length);
const compassOpts = {
  x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
  camX: REPORTED_X, camY: CH(REPORTED_X, REPORTED_Z) + 14, camZ: REPORTED_Z,
  boundsOf: honest, levelErrorM: CERR, pixelScale: camPixelScale,
};
const compassFit = selectLodFitted(compassOpts);
check('…the compass world: coarsenings', compassFit.coarsenings, 0);
check('…and its list too', compassFit.nodes.length, selectLodNodes(compassOpts).length);

// ── [15] THE WATER PYRAMID (Wasser v2, K-A E2) ──────────────────────────────
//
// The second field of the tiles gets a pyramid of its own, beside the height
// ones and over the SAME near window. This section pins the two decisions of
// that pyramid — the decimation rule and what happens to the dry sentinel —
// and the CPU twin `wlevelAt` the shader of K-A E3 will mirror.
//
// THE FIXTURE, a ramp with a dry tail, so every number is readable at a glance:
// one tile, origin (0,0), step 2, 9 x 9 support points at x, z in {0…16}, and
//
//     level[j][i] = i        for i <= 7      (i.e. the mirror is x/2)
//     level[j][8] = null                     (x = 16 carries no water)
//
// A LINEAR mirror is not a convenience here, it is the case the rule is chosen
// for: `water_level_at` interpolates LINEARLY between two knots, so a coarse
// lattice that is a SUBSET of the fine one carries the same surface — and that
// is exactly what the checks below measure.
console.log('\n[15] the water pyramid — decimation, the sentinel, and wlevelAt');
const WROW = [0, 1, 2, 3, 4, 5, 6, 7, null];
const WRASTER = emptyWaterRaster();
WRASTER.tileM = 256;
WRASTER.tiles.set('0,0', waterTileFrom(0, 0, 2, {
  level: Array.from({ length: 9 }, () => WROW.slice()),
}));
const WPYR = buildWaterPyramid((x, z) => rasterLevelAt(WRASTER, x, z),
  0, 0, 2, 9, 9, MAX_LOD_LEVELS);
// The chain: 9 -> 5 -> 3 -> 2 -> (1, too small to carry a surface), so FOUR
// levels at steps 2, 4, 8, 16 — the same `floor((n−1)/2)+1` the height pyramid
// walks, because it IS `buildPyramid`.
check('the chain ends where a level has under two points per axis',
  WPYR.levels.length, 4);
check('level 0 is the raster itself', WPYR.levels[0].step, 2);
check('…level 1 is twice as coarse', WPYR.levels[1].step, 4);
check('…level 3 is eight times', WPYR.levels[3].step, 16);
check('level 1 has 5 points per axis', WPYR.levels[1].cols, 5);
check('…level 2 has 3', WPYR.levels[2].cols, 3);
check('…level 3 has 2', WPYR.levels[3].cols, 2);
// DECIMATION IS A SUBSET. Level 1 keeps the base points 0, 2, 4, 6, 8, so its
// row is [0, 2, 4, 6, NaN] — every value is a base value, none is an average.
const wrow = (k) => {
  const lv = WPYR.levels[k];
  return Array.from({ length: lv.cols },
    (_, i) => WPYR.data[lv.row0 * WPYR.texW + i]);
};
check('level 1 keeps every SECOND base value, at index 1', wrow(1)[1], 2);
check('…at index 2', wrow(1)[2], 4);
check('…at index 3', wrow(1)[3], 6);
check('level 2 keeps every fourth', wrow(2)[1], 4);
// RED COUNTER-PROBE: a MEAN (box) filter would answer 6.5 at that same level-1
// texel — the average of the base pair (6, 7) — a mirror no profile describes
// and half a metre of invented water at the shore.
check('RED: a box filter would have put 6.5 there', (6 + 7) / 2, 6.5);
checkEq('…and the pyramid does not carry it', wrow(1)[3] === 6.5, false);
// THE SUBSET IS EXACT FOR A LINEAR MIRROR, which is the justification: level 1
// and level 2 answer the SAME number as level 0 between the support points.
check('level 0 at (6, 0)', wlevelAt(WPYR, 6, 0, 0), 3);
check('…level 1 answers the same', wlevelAt(WPYR, 6, 0, 1), 3);
check('…and level 2 as well', wlevelAt(WPYR, 6, 0, 2), 3);
check('…between two base points too, at (7, 0)', wlevelAt(WPYR, 7, 0, 0), 3.5);
// THE SENTINEL DECIMATES WITH THE LEVEL: a coarse texel is water exactly when
// its own base texel is. Base index 8 is dry, so level 1's index 4 is, and so
// on up the chain — one number, one book about where the water is.
checkEq('the dry base point is NaN', Number.isNaN(wrow(0)[8]), true);
checkEq('…and so is the level-1 texel that IS it', Number.isNaN(wrow(1)[4]), true);
checkEq('…and the level-2 one', Number.isNaN(wrow(2)[2]), true);
checkEq('a read on the dry point answers NaN',
  Number.isNaN(wlevelAt(WPYR, 16, 0, 0)), true);
checkEq('…on every level', Number.isNaN(wlevelAt(WPYR, 16, 0, 1)), true);
// THE MASKED MIX, at the pyramid this time. (14, 0) is the OUTERMOST written
// point; its eastern neighbour is dry and carries weight 0 there. Plain
// bilinear would answer NaN and the ring would lose its outer texel — which is
// the erosion finding of `waterRaster.waterBilinear`.
check('the outermost written point keeps its value', wlevelAt(WPYR, 14, 0, 0), 7);
checkEq('RED: the same mix without the mask is NaN',
  Number.isNaN(7 * 1 + NaN * 0), true);
checkEq('…and a WEIGHTED dry corner still answers NaN',
  Number.isNaN(wlevelAt(WPYR, 15, 0, 0)), true);
// THE PRICE, stated as the number it is: the ring loses half its texels per
// level, because the decimation keeps every second one. The outermost WRITTEN
// support point walks inward 14 -> 12 -> 8 -> 0 as the level coarsens, which is
// why the server's dilation guarantee (`WATER_RASTER_DILATION_STEPS`) is
// claimed for the BASE lattice and deliberately not above it.
const lastWritten = (k) => {
  const lv = WPYR.levels[k];
  let last = -1;
  for (let i = 0; i < lv.cols; i += 1) {
    if (!Number.isNaN(wrow(k)[i])) last = i * lv.step;
  }
  return last;
};
check('the outermost written x at level 0', lastWritten(0), 14);
check('…at level 1', lastWritten(1), 12);
check('…at level 2', lastWritten(2), 8);
check('…at level 3', lastWritten(3), 0);
// AND THE UPLOAD IS WIRED: the three water uniforms are bound beside the height
// ones, by the same one function every patched material goes through — and
// since E3 the WATER VARIANT of the program is what reads them (section [16]).
const bound = {};
bindTerrainLodUniforms(bound);
checkEq('the water TEXTURE is bound', bound.uTlodWater !== undefined, true);
checkEq('…its geometry', bound.uTlodWaterGeom !== undefined, true);
checkEq('…and its per-level lattice', bound.uTlodWaterLevel !== undefined, true);
checkEq('…and the height ones are still there',
  bound.uTlodNear !== undefined && bound.uTlodFar !== undefined, true);
// NO FAR TWIN, and there will not be one: the overview grid carries no water at
// all (§ A16.5), so a point outside the near window is "no water known here"
// rather than a mirror invented from a coarse raster.
checkEq('there is no far water pyramid', bound.uTlodWaterFar === undefined, true);

// ── [16] THE VERTEX LIFT (Wasser v2, K-A E3) ────────────────────────────────
//
// THE FIXTURE — one shore, hand-built from the shape the server's bake really
// leaves behind, on one 9 x 9 window at the 2 m base step (x = 0 … 16, and
// everything is constant in z so the row IS the world).
//
// The authored water is a lake whose OUTLINE runs at x = 10, level 1.0 (one
// knot, so the mirror is 1.0 everywhere), depth 2.0 m, shore ramp 4.0 m.
//
// EVERY NUMBER BELOW IS EXACT IN BINARY32, on purpose: the pyramids are
// Float32Arrays, so a fixture built out of tenths would be checked against
// values the arithmetic never produces (1.4 comes back as 1.3999999762) and
// the tolerances would hide the very drift they are there to catch.
//
//   THE MIRROR ROW, i.e. what `HeightModel.water_raster` writes. The raster is
//   dilated `WATER_RASTER_DILATION_STEPS` = 2 steps = 4 m past the outline
//   (`heightfield.py`), so it is written out to x = 14 and x = 16 is the dry
//   sentinel:
//
//       x     0    2    4    6    8   10   12   14   16
//       w   1.0  1.0  1.0  1.0  1.0  1.0  1.0  1.0  null
//
//   THE GROUND ROW, `h_final`, one number per bake stage:
//
//       x = 0 … 6   the CARVE at full depth:  level − depth = 1 − 2 = −1
//       x = 8       the shore ramp on its way up out of the bed:       0.0
//       x = 10      the outline, where the ramp has reached the mirror: 1.0
//       x = 12      2 m outside the outline: authored meadow standing 0.5 m
//                   OVER its own mirror — a bank, and nothing in the bake
//                   touches it (the shore guards are gone since v8, K-A E6,
//                   and while they existed this was the clamp's band):  1.5
//       x = 14      4 m outside: authored meadow lying UNDER the mirror,
//                   which is the normal legal case since v8 — the bake leaves
//                   it and the LIFT below is what covers it:            0.75
//       x = 16      dry land:                                          3.0
//
//       x     0    2    4    6    8   10   12   14   16
//       h  −1.0 −1.0 −1.0 −1.0  0.0  1.0  1.5 0.75  3.0
//
// THE TWO PYRAMIDS DECIMATE AS SUBSETS (section [15]), so level 1 keeps the
// base points 0, 4, 8, 12, 16:
//
//       level 1   x:    0     4     8    12    16
//                 w:  1.0   1.0   1.0   1.0   null
//                 h: −1.0  −1.0   0.0   1.5   3.0
//
// (a) THE LIFT ITSELF: y = max(h, w), with the DRY SENTINEL falling through to
//     the ground. Derived from the rows above:
//
//       x = 4    h = −1.0, w = 1.0    → 1.0   (the bed lifts by 2 m)
//       x = 9    h = mix(0.0, 1.0, ½) = 0.5, w = 1.0 → 1.0
//       x = 10   h = 1.0, w = 1.0     → 1.0   (AT THE OUTLINE THE TWO HALVES
//                                              OF THE MAX MEET: the ramp has
//                                              arrived, so it does not matter
//                                              which branch wins)
//       x = 12   h = 1.5, w = 1.0     → 1.5   THE RING PROBE — the dilation
//                                              ring HAS a level here and the
//                                              terrain does NOT lift, because
//                                              the authored ground already
//                                              stands 0.5 m over its mirror
//       x = 14   h = 0.75, w = 1.0    → 1.0   …and here it DOES, by 0.25 m
//       x = 15   h = mix(0.75, 3.0, ½) = 1.875, w = mix(1.0, null, ½) = dry
//                                     → 1.875 (a WEIGHTED dry corner is dry)
//       x = 16   h = 3.0, w = dry     → 3.0
//
//     THE RING RULE, and it is the point of the whole stage. A vertex in the
//     dilation ring lifts wherever the mirror stands over the ground, and
//     since v8 (K-A E6) the bake no longer holds that ground up: the bank
//     clamp and the 16 m relief fade are deleted, precisely because THIS is
//     the answer to land lying under the mirror beside its own water (failure
//     class F1, `recherche-wasser-v2.md` § 2) — K-A raises the land instead of
//     floating the water. The lift is bounded twice over: by `level − h` in
//     height and by the 4 m dilation in width, which is why x = 15 (a weighted
//     dry corner) is already dry again and the lake cannot creep into the
//     meadow past the ring.
//
// (b) THE MIP IS THE HEIGHT'S MIP, AND THE MAX IS TAKEN PER LEVEL. At x = 14
//     the level-1 lattice has already lost the ring (its next support point,
//     x = 16, is the dry sentinel), so:
//
//       level 0:  h = 0.75,                    w = 1.0  → max = 1.0
//       level 1:  h = mix(1.5, 3.0, ½) = 2.25, w = dry  → max = 2.25
//
//     The shipped shape blends those two: y(f) = mix(1.0, 2.25, f), continuous,
//     y(0) = 1.0, y(0.001) = 1.00125. The OTHER order — blend the mirrors
//     first, then take one max — answers max(mix(0.75, 2.25, f),
//     maskedMix(1.0, dry, f)), and `maskedMix(1.0, dry, f)` is 1.0 at f = 0 and
//     dry for every f > 0, so it drops to 0.75 + 1.5·f the instant f leaves 0
//     (0.7515 at f = 0.001): a step of
//         1.0 − 0.75 = 0.25 m
//     in the drawn ground, AT the morph front, i.e. a shoreline that swims
//     against its own bed as the camera moves. That is the number this section
//     pins, and the reason for the order.
//
// (c) THE GATE. `nodeHasWater` decides which pieces get the lifting program.
//     Over a world of 256 m tiles with water in tile "1,0" alone:
//       - a 64 m piece at x = 0 touches tile 0 only              → dry
//       - a 64 m piece at x = 256 touches tile 1                 → wet
//       - a 64 m piece at x = 192 REACHES x = 256, and the vertex it puts
//         there is filed under tile 1 by `tileKeyAt`             → wet
//     The third is the whole crack argument: the closed rectangle
//     (`floor((x + size) / tileM)`, no epsilon) is what makes a vertex shared
//     by two pieces belong to BOTH of their tile spans, so both pieces run the
//     same program and cannot disagree about where it sits. The RED probe
//     below re-derives the same span with `nodeBounds`' `− 1e-6` and shows it
//     answering "one tile" for the piece at 192 — the crack the epsilon opens.
console.log('\n[16] the vertex lift — max(h, w_level), and who pays for it');

const SHORE_H = [-1, -1, -1, -1, 0, 1, 1.5, 0.75, 3];
const SHORE_W = [1, 1, 1, 1, 1, 1, 1, 1, null];
const shoreH = (x) => SHORE_H[Math.max(0, Math.min(8, Math.round(x / 2)))];
const shoreNear = buildPyramid((x) => shoreH(x), 0, 0, 2, 9, 9, MAX_LOD_LEVELS);
const shoreRaster = emptyWaterRaster();
shoreRaster.tileM = 256;
shoreRaster.tiles.set('0,0', waterTileFrom(0, 0, 2, {
  level: Array.from({ length: 9 }, () => SHORE_W.slice()),
}));
const shoreWater = buildWaterPyramid((x, z) => rasterLevelAt(shoreRaster, x, z),
  0, 0, 2, 9, 9, MAX_LOD_LEVELS);
const SHORE_RECT = [0, 0, 16, 16];
// THE OUTLINE IS AT x = 10, and the raster's two dilation steps are what put a
// level at x = 12 and x = 14 (`WATER_RASTER_DILATION_STEPS` = 2). The sd field
// says so: +(10 − x) inside, −(x − 10) in the ring, dry past it — exactly what
// the server bakes (bake v9) and what `buildSd` uploads.
const SHORE_SD = sdFieldFrom((x) => (x <= 15 ? 10 - x : WATER_SD_DRY),
  0, 0, 2, 9, 9);
/** The drawn height of ONE tap: the three shipped twins composed exactly as
 *  `tlodCompute` composes them for one member of the morph pair. `sd` is taken
 *  ONCE per vertex there, so it is a parameter here and not a third lookup. */
const liftAt = (x, nodeStep, sd = gpuWaterSdAt(SHORE_SD, x, 0)) => liftedHeight(
  gpuHeightAt(shoreNear, SHORE_RECT, null, x, 0, nodeStep),
  gpuWaterAt(shoreWater, SHORE_RECT, x, 0, nodeStep), sd);
/** The same tap with NO gate — what the renderer drew until finding F-B, kept
 *  as the red probe every ring check below is measured against.
 *
 *  THE "NO GATE" DISTANCE IS `WATER_SD_BAND_M` AND NO LONGER 0 (finding G1):
 *  the gate is a RAMP that starts at 0 ON the outline and reaches 1 half a metre
 *  in, so the distance that means "lift it all" is past the band's far end. 0
 *  now means the outline itself, which is where the ramp lifts nothing. */
const UNGATED = WATER_SD_BAND_M;
const liftUngated = (x, nodeStep) => liftedHeight(
  gpuHeightAt(shoreNear, SHORE_RECT, null, x, 0, nodeStep),
  gpuWaterAt(shoreWater, SHORE_RECT, x, 0, nodeStep), UNGATED);
const wrow16 = (pyr, k, n) => {
  const lv = pyr.levels[k];
  return Array.from({ length: n }, (_, i) => pyr.data[lv.row0 * pyr.texW + i]);
};

// The fixture is what the docstring says it is, before anything is read off it.
checkEq('(a) the level-1 mirror keeps every second base value',
  wrow16(shoreWater, 1, 5).map((v) => (Number.isNaN(v) ? 'dry' : v)),
  [1, 1, 1, 1, 'dry']);
checkEq('…and the level-1 ground does too', wrow16(shoreNear, 1, 5),
  [-1, -1, 0, 1.5, 3]);

// (a) the lift, probe by probe
check('the bed at x = 4 (−1) lifts onto its mirror', liftAt(4, 2), 1);
check('…and so does the shore ramp at x = 9 (0.5)', liftAt(9, 2), 1);
check('AT THE OUTLINE x = 10 the two halves meet — 1.0 either way',
  liftAt(10, 2), 1);
check('THE RING PROBE x = 12: the level is there, the bank is over it',
  liftAt(12, 2), 1.5);
check('…and its sd is negative too', gpuWaterSdAt(SHORE_SD, 12, 0), -2);
checkEq('…so what is drawn is the GROUND and not the mirror',
  liftAt(12, 2) === shoreH(12), true);
// THE RING NO LONGER LIFTS (finding F-B). x = 14 is 4 m outside the authored
// outline; the raster has a level there (the dilation), the bank under it is
// 0.75, and until this round the vertex rose the 0.25 m onto the mirror — a
// lifted band all round every shore whose outer edge is a LATTICE STAIRCASE,
// drawn as ground, with the real ground a quarter of a metre UNDER it.
check('RED: ungated, the outer ring x = 14 lifts onto the mirror',
  liftUngated(14, 2), 1);
check('RED: …by exactly level − h', liftUngated(14, 2) - shoreH(14), 0.25);
check('the sd at x = 14 is −4 — the dilation\'s own width, negative',
  gpuWaterSdAt(SHORE_SD, 14, 0), -4);
check('…so the GATED tap draws the bank, not the mirror', liftAt(14, 2),
  shoreH(14));
check('…and the lift there is exactly 0', liftAt(14, 2) - shoreH(14), 0);
check('a WEIGHTED dry corner is dry — x = 15 draws the ground', liftAt(15, 2), 1.875);
check('…and so does the dry probe x = 16', liftAt(16, 2), 3);
// RED: `Math.max` is not the rule, and this is why `liftedHeight` exists.
checkEq('RED: Math.max(h, NaN) would answer NaN at the dry probe',
  Number.isNaN(Math.max(3, gpuWaterAt(shoreWater, SHORE_RECT, 16, 0, 2))), true);
check('…while the shipped rule answers the ground', liftedHeight(3, NaN, UNGATED), 3);
// The near rectangle is the gate: outside it the height is the OVERVIEW's and
// the overview carries no water, so the mirror is not known there either.
checkEq('past the near window there is no mirror to read',
  Number.isNaN(gpuWaterAt(shoreWater, SHORE_RECT, 20, 0, 2)), true);
checkEq('…and no pyramid at all is dry as well',
  Number.isNaN(gpuWaterAt(null, SHORE_RECT, 4, 0, 2)), true);

// ── THE FIGURE BESIDE THE WATER (finding F-B) ──────────────────────────────
// The shore fixture's own bank happens to stand ABOVE the mirror in most of the
// ring, which hides the symptom. This one does not: flat ground at 0, a mirror
// at 1.0 over a wet mask that reaches 4 m past an outline at x = 10. Ungated,
// every vertex of that 4 m band rises a WHOLE METRE onto the mirror, so the
// drawn ground beside the lake hangs 1 m over the real ground a figure stands
// on (`waterPlaneMath.waterLevelAt` is what a figure reads, and it never knew
// about the dilation) — "the avatar is standing in the ground". The band's
// outer edge is a lattice staircase, and the band itself is drawn as ground:
// the grey rim patch and the step silhouette, both.
const FLAT_H = buildPyramid(() => 0, 0, 0, 2, 11, 3, MAX_LOD_LEVELS);
const FLAT_W = buildWaterPyramid((x) => (x <= 15 ? 1 : NaN), 0, 0, 2, 11, 3,
  MAX_LOD_LEVELS);
const FLAT_SD = sdFieldFrom((x) => (x <= 15 ? 10 - x : WATER_SD_DRY),
  0, 0, 2, 11, 3);
const FLAT_RECT = [0, 0, 20, 4];
const flatAt = (x, sd) => liftedHeight(
  gpuHeightAt(FLAT_H, FLAT_RECT, null, x, 0, 2),
  gpuWaterAt(FLAT_W, FLAT_RECT, x, 0, 2), sd);
check('inside the lake the ground IS the mirror', flatAt(8, gpuWaterSdAt(FLAT_SD, 8, 0)), 1);
check('RED: ungated, a probe 1 m OUTSIDE the outline rises a whole metre',
  flatAt(11, UNGATED), 1);
check('RED: …and 2 m outside just as much', flatAt(12, UNGATED), 1);
check('the sd 1 m out is −1', gpuWaterSdAt(FLAT_SD, 11, 0), -1);
check('…so the gated vertex draws the TRUE ground there', flatAt(11, gpuWaterSdAt(FLAT_SD, 11, 0)), 0);
check('…which is exactly the h a figure stands on', flatAt(11, gpuWaterSdAt(FLAT_SD, 11, 0)),
  gpuHeightAt(FLAT_H, FLAT_RECT, null, 11, 0, 2));
check('…and the phantom lift the figure sank into was', flatAt(11, UNGATED)
  - flatAt(11, gpuWaterSdAt(FLAT_SD, 11, 0)), 1);
// ── AND THE SAME SINKING, HALF A METRE FURTHER IN (finding G1) ─────────────
// The gate closed the RING. Inside the outline the lift was still binary while
// the fragment faded the water look in over half a metre, so the first half
// metre of real water stood the WHOLE metre up and was shaded as ground — a
// figure at h was drawn a metre under a surface that still looked like bank.
// The ramp is the fix, and these are its metres on this fixture (mirror 1.0 m
// over a flat bed):
//     sd = 0     (x = 10, the outline)   -> 1.0 · 0       = 0
//     sd = 0.05  (x =  9.95)             -> 1.0 · 0.028   = 0.028 m
//     sd = 0.1   (x =  9.9)              -> 1.0 · 0.104   = 0.104 m
//     sd = 0.25  (x =  9.75)             -> 1.0 · 0.5     = 0.5 m
//     sd = 0.5   (x =  9.5)              -> 1.0 · 1       = 1.0 m
check('ON the outline the ramp lifts nothing — ground, and shaded as ground',
  flatAt(10, gpuWaterSdAt(FLAT_SD, 10, 0)), 0);
check('RED: it used to stand the WHOLE metre up there', flatAt(10, UNGATED), 1);
check('5 cm inside the outline the surface has risen', flatAt(10, 0.05), 0.028);
check('…10 cm in', flatAt(10, 0.1), 0.104);
check('…a quarter metre in, half way', flatAt(10, 0.25), 0.5);
check('…and half a metre in it is the full mirror', flatAt(10, 0.5), 1);
check('…and stays there', flatAt(10, 4), 1);
// RED: the old rule, `sd >= 0 ? w : h`, spelled out — all five stood at 1.
const oldRule = (h, w, sd) => (sd >= 0 && w > h ? w : h);
checkEq('RED: every one of those five stood at the full metre before the ramp',
  [0, 0.05, 0.1, 0.25, 0.5].map((sd) => oldRule(0, 1, sd)), [1, 1, 1, 1, 1]);
// THE FIGURE PROBE the finding names: "just inside the edge, the drawn surface
// within ~1 cm of the height the figure stands on". At sd = 0.05 the gap is
// 2.8 cm for a 1.0 m lift and 1.12 cm for the 0.40 m one a shore usually has;
// it falls under a centimetre for every lift under 0.357 m.
check('the drawn surface 5 cm in is this far over the figure\'s ground',
  flatAt(10, 0.05) - 0, 0.028);
vector("[16] terrain_lod: …and for the 0.40 m lift a real shore has, this far", { liftedHeight: (...args) => liftedHeight(...vectorArgs(args)) });
checkEq('RED: before the ramp that gap was the whole lift',
  [flatAt(10, UNGATED) - 0, oldRule(0, 0.4, 0.05)], [1, 0.4]);
// x = 15 is left out on purpose: its cell already meets the dry texel at 16, so
// the masked mix answers NaN there and the ring ends of its own accord.
checkEq('…and the whole 4 m ring is back on the ground, texel by texel',
  [11, 12, 13, 14].map((x) => flatAt(x, gpuWaterSdAt(FLAT_SD, x, 0))),
  [0, 0, 0, 0]);
checkEq('RED: …every one of which used to hang a metre up',
  [11, 12, 13, 14].map((x) => flatAt(x, UNGATED)), [1, 1, 1, 1]);

// (b) the morph reads BOTH taps at their own footprint
// Measured on the UNGATED taps, because the argument is about the ORDER of the
// max and the mix and not about the gate — and x = 14 is the only probe of this
// fixture whose two taps disagree. With the gate both taps are the ground and
// the blend is trivially continuous, which is checked right after.
check('at x = 14 the level-0 tap lifts to the mirror', liftUngated(14, 2), 1);
check('…while the level-1 tap has lost the ring and stays ground',
  liftUngated(14, 4), 2.25);
const blend16 = (f) => liftUngated(14, 2) * (1 - f) + liftUngated(14, 4) * f;
check('the shipped order is continuous at f = 0', blend16(0), 1);
check('…and one thousandth in it has moved one thousandth of the way',
  blend16(0.001), 1.00125, 1e-12);
// …and the GATE is taken once for both taps, so the pair is continuous in f at
// the outline for the same reason: one number, both terms.
const gated16 = (f) => liftAt(14, 2) * (1 - f) + liftAt(14, 4) * f;
const ground16 = (f) => gpuHeightAt(shoreNear, SHORE_RECT, null, 14, 0, 2) * (1 - f)
  + gpuHeightAt(shoreNear, SHORE_RECT, null, 14, 0, 4) * f;
check('gated, BOTH taps are the bare ground — no mirror enters at all',
  gated16(0) - ground16(0), 0);
check('…at the other end of the morph too', gated16(1) - ground16(1), 0);
check('…and in the middle, so the whole pair is the dry surface',
  gated16(0.5) - ground16(0.5), 0);
// RED COUNTER-PROBE: mirrors blended first, then one max. A masked mix of a wet
// and a dry corner is dry for every weight above 0, so the lift vanishes the
// moment f leaves 0.
const wrongOrder = (f) => {
  const h = gpuHeightAt(shoreNear, SHORE_RECT, null, 14, 0, 2) * (1 - f)
    + gpuHeightAt(shoreNear, SHORE_RECT, null, 14, 0, 4) * f;
  const w = f === 0 ? gpuWaterAt(shoreWater, SHORE_RECT, 14, 0, 2) : NaN;
  return liftedHeight(h, w, UNGATED);
};
check('RED: the wrong order stands at 1.0 while f is exactly 0', wrongOrder(0), 1);
check('…and drops to the bed one thousandth later', wrongOrder(0.001), 0.7515, 1e-12);
check('…a step in the drawn ground of', wrongOrder(0) - wrongOrder(0.001),
  0.2485, 1e-12);

// …and the SHIPPED vertex function does it, not just the arithmetic above.
const SHORE_NODE = { x: 0, z: 0, size: 64, level: 0, cells: 32, morph: 0 };
check('morphedVertex at x = 14, ungated, lifts to the mirror',
  morphedVertex(SHORE_NODE, 7, 0, shoreNear, SHORE_RECT, null, null, 0,
    shoreWater).y, 1);
check('…and with the sd field it stays on the bank',
  morphedVertex(SHORE_NODE, 7, 0, shoreNear, SHORE_RECT, null, null, 0,
    shoreWater, SHORE_SD).y, 0.75);
check('…and without a water pyramid it is the bed, unchanged',
  morphedVertex(SHORE_NODE, 7, 0, shoreNear, SHORE_RECT, null, null, 0,
    null).y, 0.75);
// x = 12 is a support point of levels 0, 1 AND 2, so the decimation gives every
// tap the same lifted height and the morph moves NOTHING — the mirror cannot
// swim at a point every lattice agrees on.
for (const t of [0, 0.5, 1]) {
  check(`…and at x = 12 the morph t = ${t} draws the same 1.5`,
    morphedVertex(SHORE_NODE, 6, 0, shoreNear, SHORE_RECT, null, null, t,
      shoreWater, SHORE_SD).y, 1.5);
}

// (c) the gate
console.log('\n…and the gate: which pieces get the lifting program at all');
const WET_TILES = new Set(['1,0']);
checkEq('a piece west of the water is dry',
  nodeHasWater(WET_TILES, 256, 0, 0, 64), false);
checkEq('…a piece inside the wet tile is wet',
  nodeHasWater(WET_TILES, 256, 256, 0, 64), true);
checkEq('THE SEAM: a piece whose EAST EDGE is the tile border is wet too',
  nodeHasWater(WET_TILES, 256, 192, 0, 64), true);
// RED: the same span with `nodeBounds`' epsilon drops the tile the shared
// vertex reads its water out of — the piece at 192 would run the dry program
// while its neighbour at 256 lifts, and the edge they share would tear.
const epsSpan = (x, size, tileM) =>
  Math.floor((x + size - 1e-6) / tileM) - Math.floor(x / tileM) + 1;
check('RED: with the −1e-6 span that piece covers only', epsSpan(192, 64, 256), 1);
check('…while the closed rectangle covers',
  Math.floor((192 + 64) / 256) - Math.floor(192 / 256) + 1, 2);
checkEq('…and the tile the epsilon keeps holds no water',
  WET_TILES.has('0,0'), false);
checkEq('an empty raster leaves every piece on the dry program',
  nodeHasWater(new Set(), 256, 0, 0, 64), false);
checkEq('…and so does a raster with no tile size',
  nodeHasWater(WET_TILES, 0, 0, 0, 64), false);
// The scan cap: a 2 048 m root over 256 m tiles spans 9 x 9 = 81 closed, which
// is the cap itself, so the real quadtree is always scanned. Smaller tiles blow
// past it and the answer is the SAFE one — wet, i.e. it pays four texelFetch
// per vertex and draws the identical ground.
check('a root over 256 m tiles spans exactly the cap', (2048 / 256 + 1) ** 2, 81);
checkEq('…and is really scanned: no water near it, no lifting program',
  nodeHasWater(WET_TILES, 256, -4096, 0, 2048), false);
check('…while over 128 m tiles the same root spans', (2048 / 128 + 1) ** 2, 289);
checkEq('…which is past the cap, so it is marked wet without looking',
  nodeHasWater(new Set(['99,99']), 128, -4096, 0, 2048), true);

// ── [17] THE SECOND MATERIAL VARIANT — and what the dry one pays ────────────
//
// THE BINDING RISK RULE of `recherche-wasser-v2.md` § 4 K-A: the water branch
// exists only for nodes that carry water, so dry ground must keep the program
// it had before this stage — the same GLSL statements and, since three caches
// programs by `customProgramCacheKey`, literally the same `WebGLProgram`.
//
// String pins, hand-derived from what the lift has to be:
//   - the dry variant declares NO uTlodWater*, calls NO tlodLift, and keeps
//     its four texelFetch (the height's bilinear corners);
//   - the water variant has EIGHT — four for the ground, four for the mirror;
//   - the lift is `( w > h ) ? w : h` and NOT `max( h, w )`: the dry sentinel
//     is a NaN out of the texture, IEEE says every comparison against it is
//     false so `>` falls through to the ground, while GLSL leaves it open
//     which operand `max` returns for a NaN;
//   - each tap passes the SAME `nodeStep * m1` (and `* m2`) to the height and
//     to the lift. That one repeated expression IS the "same footprint, same
//     mip" property of section [16](b), written where it cannot drift.
console.log('\n[17] the water variant, and the dry program that is untouched');
const dryGlsl = terrainLodGlsl();
const wetGlsl = terrainLodGlsl(true);
checkEq('the dry variant knows no water uniform', dryGlsl.includes('uTlodWater'), false);
checkEq('…nor the lift', dryGlsl.includes('tlodLift'), false);
check('…and still fetches exactly the height\'s four texels, plus the cap\'s four',
  dryGlsl.split('texelFetch(').length - 1, 8);
checkEq('…its height line is the one it always had',
  dryGlsl.includes(
    'float h = mix( tlodHeight( p, nodeStep * m1 ), tlodHeight( p, nodeStep * m2 ), f );'),
  true);
checkEq('the water variant declares the sampler',
  wetGlsl.includes('uniform sampler2D uTlodWater;'), true);
checkEq('…and the isolation uniform',
  wetGlsl.includes('uniform float uTlodNoWater;'), true);
// SIXTEEN since Task 7 (2026-08-27), not twenty: four ground, four mirror, four
// mip cap and four SD. The FLOW's four left this stage with the varying —
// they are now spent per water PIXEL instead (`waterShade.waterFlowGlsl`),
// which is what makes the drift independent of the vertex spacing.
check('…and fetches sixteen: four ground, mirror, mip cap and SD',
  wetGlsl.split('texelFetch(').length - 1, 16);
checkEq('THE LIFT IS A COMPARISON',
  wetGlsl.includes('return ( w > h ) ? h + ( w - h ) * g : h;'), true);
checkEq('RED: and never max(), which GLSL does not pin down for a NaN',
  /max\(\s*h,\s*w\s*\)/.test(wetGlsl), false);
checkEq('EACH TAP IS LIFTED AT ITS OWN FOOTPRINT — the m1 half',
  wetGlsl.includes('float l1 = tlodLift( h1, p, nodeStep * m1, sdw );'), true);
checkEq('…and the m2 half',
  wetGlsl.includes('float l2 = tlodLift( h2, p, nodeStep * m2, sdw );'), true);
// …AND THE GATE IS TAKEN ONCE, before either tap: it is a function of the
// position alone, so both taps carry the same number and the pair stays
// continuous in f at the outline (finding F-B).
checkEq('the sd is read ONCE per vertex, before the taps',
  wetGlsl.includes('float sdw = twSdAt( p );'), true);
check('…exactly once', wetGlsl.split('twSdAt( p )').length - 1, 1);
// THE GATE IS THE FRAGMENT'S OWN CURVE (finding G1) — one GLSL text, included
// by the vertex stage here and by `waterShade.terrainWaterFragmentGlsl` there,
// so the drawn surface and the drawn look ride the same shore ramp.
checkEq('THE GATE IS THE SHARED CURVE, not a sign test',
  wetGlsl.includes('float g = twInside( sd );')
  && wetGlsl.includes('if ( g <= 0.0 ) return h;'), true);
checkEq('RED: …and the old binary sign test is gone',
  wetGlsl.includes('sd < 0.0'), false);
checkEq('…the curve comes from the one shared text',
  wetGlsl.includes(waterGateGlsl().trim()), true);
checkEq('…which the FRAGMENT program includes as well',
  terrainWaterFragmentGlsl().includes(waterGateGlsl().trim()), true);
checkEq('…and the vertex program declares twInside exactly once',
  wetGlsl.split('float twInside(').length - 1, 1);
checkEq('…so the max is taken per LEVEL and one mix wraps both',
  wetGlsl.includes('float h = mix( l1, l2, f );'), true);
// ── K-A E4: the DEPTH the fragment shades from is a varying, not a lookup ──
// The drawn surface is mix(l1, l2, f) and the drawn bed is mix(h1, h2, f), so
// their difference is mix(l1 − h1, l2 − h2, f): exact for the triangle that is
// really drawn, ≥ 0 term by term, and 0 wherever nothing was lifted. That is
// what buys the fragment its shoreline WITHOUT the mirror's four texelFetch
// per pixel.
checkEq('THE LIFTED DEPTH RIDES ALONG as a varying',
  wetGlsl.includes('vTlodWet = mix( l1 - h1, l2 - h2, f );'), true);
checkEq('…declared in the water variant', wetGlsl.includes('varying float vTlodWet;'), true);
checkEq('…and in NO dry program', dryGlsl.includes('vTlodWet'), false);
// THE FLOW DOES NOT RIDE ALONG ANY MORE (Task 7, 2026-08-27). It was
// `vTlodFlow`, sampled once per vertex, and a level-3 piece's 16 m spacing
// straddles a 14 m river band whole — all four corners dry, the varying exactly
// (0, 0), the fragment's STILL branch, a river drawn as standing water while the
// field under it carried 2 m/s. The tap is the FRAGMENT's own now.
// (The chunk still CARRIES a comment naming the retired path — that is the
// record of why it is gone. The pins are on code: no varying, no function, no
// fetch.)
checkEq('RED: the vertex program declares no flow varying, function or fetch',
  /varying vec2 vTlodFlow|vec2 tlodFlowAt\(|texelFetch\( uTlodFlow|uniform sampler2D uTlodFlow/
    .test(wetGlsl), false);
checkEq('RED: …and it assigns nothing to one either',
  /vTlodFlow\s*=/.test(wetGlsl), false);
checkEq('RED: …nor does the dry one',
  /vTlodFlow|tlodFlowAt|uTlodFlow/.test(dryGlsl), false);
checkEq('…and the FRAGMENT declares the sampler and taps it at the pixel\'s XZ',
  terrainWaterFragmentGlsl().includes('uniform sampler2D uTlodFlow;')
  && terrainWaterFragmentGlsl().includes('vec2 twFlowAt( vec2 p ) {')
  && terrainWaterFragmentGlsl().includes('vec2 flow = twFlowAt( p );'), true);
// The TS twin of `l - h`, and the identity that makes it one statement.
check('liftedDepth: a mirror 1.2 m over the bed, well inside the outline',
  liftedDepth(3, 4.2, UNGATED), 1.2);
check('…a mirror UNDER the bed is dry', liftedDepth(5, 4.2, UNGATED), 0);
check('…and the dry sentinel is dry', liftedDepth(5, NaN, UNGATED), 0);
vector("[17] terrain_lod: …and so is a mirror OUTSIDE the outline, however deep", { liftedDepth: (...args) => liftedDepth(...vectorArgs(args)) });
vector("[17] terrain_lod: …and ON the outline, where the ramp starts", { liftedDepth: (...args) => liftedDepth(...vectorArgs(args)) });
// THE RAMP, on the shipped function: 1.2 m of water times the gate's curve.
checkEq('the shipped depth follows the gate metre for metre',
  [0, 0.05, 0.1, 0.125, 0.25, 0.375, 0.5, 1]
    .map((sd) => Number((liftedDepth(3, 4.2, sd)).toFixed(9))),
  [0, 0.0336, 0.1248, 0.1875, 0.6, 1.0125, 1.2, 1.2]);
checkEq('RED: every one of those was the full 1.2 m before the ramp',
  [0, 0.05, 0.1, 0.125, 0.25, 0.375, 0.5, 1]
    .map((sd) => (sd >= 0 ? 1.2 : 0)),
  [1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2]);
// AND IT NEVER GOES NEGATIVE — the fragment's every branch keys on `> 0`.
let worstDepth = 0;
for (let sd = -1; sd <= 2.0001; sd += 0.001) {
  for (const w of [NaN, -3, 3, 4.2, 9]) {
    const d = liftedDepth(3, w, sd);
    if (d < worstDepth) worstDepth = d;
  }
}
check('the depth stays >= 0 over 3001 x 5 probes', worstDepth, 0);
// `liftedDepth` IS `liftedHeight − h`, at every distance. The last probe adds a
// float's worth of slack and nothing more: `h + x − h` is not bit-exact for
// h = 3, x = 0.1248 (it comes back 0.12479999999999997), and the identity is
// about the RULE, not about IEEE rounding.
checkEq('RED: depth 0 is exactly where the lift did nothing',
  [liftedHeight(5, NaN, UNGATED) - 5, liftedDepth(5, NaN, UNGATED),
   liftedHeight(3, 4.2, UNGATED) - 3 - liftedDepth(3, 4.2, UNGATED),
   liftedHeight(3, 4.2, -1) - 3 - liftedDepth(3, 4.2, -1)], [0, 0, 0, 0]);
check('…and the identity holds on the ramp too, to a float',
  liftedHeight(3, 4.2, 0.1) - 3 - liftedDepth(3, 4.2, 0.1), 0, 1e-15);
// The masked mix, in GLSL this time: four corners, four weight guards.
check('the mirror\'s bilinear guards every one of its four corners',
  terrainLodWaterGlsl().split('!= 0.0').length - 1, 4);
checkEq('…and it is read in the NEAR window alone, where the height is',
  terrainLodWaterGlsl().includes('p.x < uTlodNearRect.x'), true);
// λ IS NEVER LIFTED: both variants measure the morph distance against the
// unlifted ground, so a dry piece and the wet piece beside it place the vertex
// they share at the same point.
checkEq('the morph distance is the UNLIFTED ground, in both variants',
  dryGlsl.includes('tlodHeight( p, 0.0 )') && wetGlsl.includes('tlodHeight( p, 0.0 )'),
  true);
checkEq('RED: nothing lifts inside tlodMorphAt',
  /float tlodMorphAt[\s\S]*?\n}/.exec(wetGlsl)[0].includes('tlodLift'), false);

// The cache key, on a stand-in material: the dry one is the string it was, the
// water one appends and never replaces.
const fakeMat = (prevKey) => {
  const m = { onBeforeCompile: () => {} };
  if (prevKey) m.customProgramCacheKey = () => prevKey;
  return m;
};
const dryMat = fakeMat('');
patchTerrainLod(dryMat);
const wetMat = fakeMat('');
patchTerrainLod(wetMat, true);
checkEq('the dry cache key', dryMat.customProgramCacheKey(), TERRAIN_LOD_CACHE_KEY);
checkEq('…is the string it always was', TERRAIN_LOD_CACHE_KEY, 'terrain-lod');
checkEq('the water cache key appends', wetMat.customProgramCacheKey(),
  `${TERRAIN_LOD_CACHE_KEY}+${TERRAIN_LOD_WATER_CACHE_KEY}`);
const chainedDry = fakeMat('ground+layers');
patchTerrainLod(chainedDry);
const chainedWet = fakeMat('ground+layers');
patchTerrainLod(chainedWet, true);
checkEq('…and both still chain onto what the owner built',
  [chainedDry.customProgramCacheKey(), chainedWet.customProgramCacheKey()],
  ['ground+layers+terrain-lod', 'ground+layers+terrain-lod+water']);
// …and the uniform that only the water variant may carry.
const compile = (mat) => {
  const shader = {
    uniforms: {},
    vertexShader: '#include <uv_vertex>\n#include <beginnormal_vertex>\n'
      + '#include <begin_vertex>',
    // The four chunks the two variants insert at, in three's own order.
    fragmentShader: '#include <metalnessmap_fragment>\n'
      + '#include <normal_fragment_begin>\n#include <opaque_fragment>',
  };
  mat.onBeforeCompile(shader, null);
  return shader;
};
const dryShader = compile(dryMat);
const wetShader = compile(wetMat);
checkEq('the dry program is handed no uTlodNoWater',
  dryShader.uniforms.uTlodNoWater === undefined, true);
checkEq('…the water program is', wetShader.uniforms.uTlodNoWater !== undefined, true);
checkEq('…both get the water TEXTURE bound (an unread uniform has no location)',
  dryShader.uniforms.uTlodWater !== undefined
  && wetShader.uniforms.uTlodWater !== undefined, true);
checkEq('the dry vertex shader carries no lift',
  dryShader.vertexShader.includes('tlodLift'), false);
checkEq('…the water one does', wetShader.vertexShader.includes('tlodLift'), true);

// ── [18] K-A E4: THE WATER SHADING IS THE WATER PROGRAM'S ALONE ─────────────
// The dry fragment must be, statement for statement, what it was before the
// stage — one replacement at `normal_fragment_begin` and nothing else. The
// arithmetic the shading itself runs on is checked, against hand tables, in
// `client3d/scripts/smoke_water_shade.mjs`; what belongs HERE is only that the
// two programs stay two programs.
console.log('\n[18] the water shading lives in the water program only (K-A E4)');
checkEq('THE DRY FRAGMENT IS THE ONE IT ALWAYS WAS',
  dryShader.fragmentShader.includes(`#include <normal_fragment_begin>
\tnormal = normalize( ( viewMatrix * vec4( tlodNormalAt( vTlodXZ ), 0.0 ) ).xyz );
\tnonPerturbedNormal = normal;`), true);
checkEq('…and gains nothing at metalnessmap or opaque_fragment',
  /#include <metalnessmap_fragment>\n#include <normal/.test(dryShader.fragmentShader)
  && /nonPerturbedNormal = normal;\n#include <opaque_fragment>/
    .test(dryShader.fragmentShader), true);
checkEq('RED: no water word reaches the dry fragment',
  /tlodWater|vTlodWet|uTlodWave|twA/.test(dryShader.fragmentShader), false);
// …and the water one composes in exactly three places, in shader order.
const wetFrag = wetShader.fragmentShader;
checkEq('the ALBEDO stage sits after the metalness chunk',
  wetFrag.includes('#include <metalnessmap_fragment>\n'
    + '\ttlodWaterSurface( diffuseColor, roughnessFactor, metalnessFactor );'), true);
checkEq('…the NORMAL stage replaces the dry expression',
  wetFrag.includes('\tnormal = tlodWaterNormal();'), true);
checkEq('…and the LIGHT stage runs before opaque_fragment',
  wetFrag.includes('\ttlodWaterOut( outgoingLight, normal, vViewPosition );\n'
    + '#include <opaque_fragment>'), true);
check('the composition order is albedo -> normal -> light',
  [wetFrag.indexOf('tlodWaterSurface( diffuseColor'),
   wetFrag.indexOf('normal = tlodWaterNormal();'),
   wetFrag.indexOf('tlodWaterOut( outgoingLight')]
    .every((v, i, a) => v > 0 && (i === 0 || v > a[i - 1])) ? 1 : 0, 1);
checkEq('the water program is handed the look table, the wave map, the flow, '
  + 'the distance and the KIND field',
  ['uTlodWaterLook', 'uTlodWave', 'uTlodFlow', 'uTlodTime', 'uTlodSky',
   'uTlodWaterSd', 'uTlodWaterKind']
    .every((k) => wetShader.uniforms[k] !== undefined), true);
// RED: NOTHING of the ground compositor is borrowed any more (finding F-A, both
// halves). Its signed distance went first — a lake with a painted bed answers
// (sand, sand) on the material mask — and its id PAIR went with bake v10, when
// the water raster started naming its own kind per texel. A river under a
// forest area read (forest, forest) and drew as the world's primary water.
checkEq('RED: the compositor\'s sd window and byte code are gone',
  ['uTlodWaterSdGeom', 'uTlodWaterSdCode']
    .some((k) => wetShader.uniforms[k] !== undefined), false);
checkEq('RED: …and so are its id mask and that mask\'s window',
  ['uTlodWaterMask', 'uTlodWaterMaskGeom']
    .some((k) => wetShader.uniforms[k] !== undefined), false);
checkEq('RED: …and no water word reaches the dry program either',
  ['uTlodWaterLook', 'uTlodWave', 'uTlodFlow', 'uTlodWaterKind', 'uTlodWaterSd']
    .some((k) => dryShader.uniforms[k] !== undefined), false);
// The absorption a fragment reads is the mirror's own shore curve — the twin
// is checked against hand tables in `smoke_water_shade.mjs`; here only that
// BOTH sides spell the same easing.
checkEq('the GLSL easing is the TS easing',
  shade.terrainWaterFragmentGlsl()
    .includes('return c * c * ( 3.0 - 2.0 * c );'), true);

// ============================================================================
// [18] THE WATER'S MIP RESOLUTION LIMIT — F1
// ============================================================================
// THE DEFECT (`docs/schnittstellen-3d.md` § "Offen und NICHT gefixt"): a 6 m
// river bed carved into the ground has no support point of its own left on an
// 8 m lattice, so `h_k ≥ w_k` there, the lift does not fire and the river falls
// apart into lens-shaped puddles at level 2 and is gone at level 3.
//
// TWO FIXTURES, both on the 2 m base lattice over [0, 256] × [0, 64], a bed
// 6 m wide (|z − zc| ≤ 3) carved 3 m deep, a mirror at −0.5 m and a dilated
// wet mask 22 m wide, so that the mask never limits anything and what is
// measured is the LIFT alone:
//   R: a straight reach, zc = 4 — every number below is derived by hand from
//      "which multiples of 2·2^k lie inside the bed [1, 7]";
//   M: a meander, zc = 8 + 4·sin(2πx/128) — bed inside [1, 15] everywhere.
//
// (a) THE TABLE ON R, along its axis at (x, 4) for x = 0, 2 … 244 (123 points).
//     level 0, step 2: rows 2, 4, 6 lie in [1, 7]; the axis sits ON row 4, so
//                      tz = 0 and h = −3 < −0.5 -> lifted, 123/123.
//     level 1, step 4: rows 0, 4, 8 — row 4 is in the bed and again carries the
//                      whole weight -> 123/123.
//     level 2, step 8: rows 0 and 8, NEITHER in [1, 7]; the axis sits halfway
//                      between them, h = 0 > −0.5 -> 0/123.
//     level 3, step 16: rows 0 and 16, same -> 0/123.
// (b) THE CAP THAT FOLLOWS. `waterTileCaps` never looks at the axis: a level k
//     survives at a texel while a FULLY lifting block of (2^k + 1)² texels sits
//     around it, because 2^k + 1 consecutive indices always contain a multiple
//     of 2^k. R's bed is 3 texels wide (rows 2, 4, 6), so 2^k + 1 ≤ 3 -> k ≤ 1:
//     cap 1, which is exactly where the table above stops. A LAKE 31 texels
//     across (|z − 32| ≤ 30, rows 1…31) gives 2^k + 1 ≤ 31 -> k ≤ 4: cap 4, and
//     nothing is refined for it.
// (c) THE TABLE ON M is 123/123 and 123/123 at levels 0 and 1 for a reason that
//     no longer mentions the fixture: with a step s ≤ 6 one of the two rows
//     bracketing the axis is always inside a 6 m bed and carries at least half
//     the weight, so h ≤ −1.5 < −0.5. At level 3 it is 0/123 because the bed
//     never leaves [1, 15] and the only multiples of 16 in reach are 0 and 16.
//     Level 2 is the interesting one — PARTIAL, the puddles — and its exact
//     count depends on the mix in x, so what is pinned is the subset where
//     there is none: at the 16 aligned points x = 0, 16 … 240 the axis reads
//     |4·sin| ≤ 3 at 12 of them (sin ≠ ±1) and > 3 at 4 (x = 32, 96, 160, 224),
//     and level 2 lifts at exactly those 12 and none of the 4.
// (d) RED — "ONE SURVIVING TEXEL" IS NOT A RIVER. The obvious rule (the
//     coarsest level whose own lattice still holds a lifting texel of the tile,
//     `max min(ctz i, ctz j)`) answers 2 for M, and the table says level 2 has
//     already lost a third of the axis. The cap is a WIDTH, not a count.
console.log('\n[18] the water\'s mip limit — the cap is a width');
const F1_BASE = 2;
const F1_COLS = 129;
const F1_ROWS = 33;
function f1Field(zcOf, half = 3) {
  const h = (x, z) => (Math.abs(z - zcOf(x)) <= half ? -3 : 0);
  // The wet mask is the bed plus the server's dilation ring, so it never limits
  // anything: what is measured here is the LIFT (`w > h`) and nothing else.
  const w = (x, z) => (Math.abs(z - zcOf(x)) <= half + 8 ? -0.5 : NaN);
  return {
    hp: buildPyramid(h, 0, 0, F1_BASE, F1_COLS, F1_ROWS, MAX_LOD_LEVELS),
    wp: buildWaterPyramid(w, 0, 0, F1_BASE, F1_COLS, F1_ROWS, MAX_LOD_LEVELS),
  };
}
/** How many of the axis points are LIFTED when the ground is drawn at level k
 *  — the lift is `w > h` on the interpolated pair, `tlodLift` itself. */
function f1Lifted(field, pts, k) {
  let n = 0;
  for (const [x, z] of pts) {
    if (wlevelAt(field.wp, x, z, k) > pyramidHeight(field.hp, x, z, k)) n += 1;
  }
  return n;
}
const RIVER_ZC = () => 4;
const MEANDER_ZC = (x) => 8 + 4 * Math.sin((2 * Math.PI * x) / 128);
const axis = (zc) => Array.from({ length: 123 }, (_, m) => [2 * m, zc(2 * m)]);
const R = f1Field(RIVER_ZC);
const M = f1Field(MEANDER_ZC);
const R_AXIS = axis(RIVER_ZC);
const M_AXIS = axis(MEANDER_ZC);
checkEq('(a) the straight reach, lifted points per level',
  [0, 1, 2, 3].map((k) => f1Lifted(R, R_AXIS, k)), [123, 123, 0, 0]);
// The cap the renderer derives from the MASK alone — 64 m tiles over the
// fixture, so tiles 0…3 hold the reach and tile 4 is the one column at the
// window's edge, where a block cannot close and the cap honestly reads 0.
const R_CAPS = waterTileCaps(R.wp, R.hp, 64, null, MAX_LOD_LEVELS);
checkEq('(b) …and the cap the mask gives those tiles',
  [0, 1, 2, 3].map((t) => R_CAPS.get(`${t},0`)), [1, 1, 1, 1]);
const LAKE = f1Field(() => 32, 30);
const LAKE_CAPS = waterTileCaps(LAKE.wp, LAKE.hp, 64, null, MAX_LOD_LEVELS);
checkEq('…a lake 31 texels across keeps level 4',
  [0, 1, 2, 3].map((t) => LAKE_CAPS.get(`${t},0`)), [4, 4, 4, 4]);
checkEq('(c) the meander is whole at levels 0 and 1…',
  [0, 1].map((k) => f1Lifted(M, M_AXIS, k)), [123, 123]);
check('…gone at level 3', f1Lifted(M, M_AXIS, 3), 0);
const M2 = f1Lifted(M, M_AXIS, 2);
checkAbove('…and BROKEN at level 2 — some of it survives', M2, 0);
checkBelow('…but not all of it: the lens-shaped puddles', M2, 123);
const M_ALIGNED = M_AXIS.filter(([x]) => x % 16 === 0);
const M_IN = M_ALIGNED.filter(([x]) => Math.abs(MEANDER_ZC(x) - 8) <= 3);
const M_OUT = M_ALIGNED.filter(([x]) => Math.abs(MEANDER_ZC(x) - 8) > 3);
checkEq('…the aligned points split 12 in-band / 4 out',
  [M_IN.length, M_OUT.length], [12, 4]);
checkEq('…and level 2 lifts exactly the in-band twelve',
  [f1Lifted(M, M_IN, 2), f1Lifted(M, M_OUT, 2)], [12, 0]);
const M_CAPS = waterTileCaps(M.wp, M.hp, 64, null, MAX_LOD_LEVELS);
// (e) THE CAP MEASURES THE GATED LIFT (finding F-B). The fixtures above carve
//     their bank ABOVE the mirror, so `w > h` alone already stops at the bed's
//     own 3 texels. A bank that lies BELOW the mirror is the ordinary case, and
//     there the raster's 4 m dilation ring lifts too. The wet mask |z − 4| ≤ 11
//     covers rows j = 0…7 of this window (z = 0…14; the ring below z = 0 falls
//     outside it), so a block of radius r = 1 << (k − 1) closes for k = 2
//     (r = 2, rows 2…5) and not for k = 3 (r = 4, nine rows needed): cap 2, for
//     a river whose own body has already broken up at level 2. With the sd gate
//     the lifting band is the authored 6 m again — rows 1, 2, 3 — and only
//     r = 1 closes: cap 1, exactly the number the width rule gives the body.
const F1_SUNK = {
  hp: buildPyramid((x, z) => (Math.abs(z - 4) <= 3 ? -3 : -1),
    0, 0, F1_BASE, F1_COLS, F1_ROWS, MAX_LOD_LEVELS),
  wp: buildWaterPyramid((x, z) => (Math.abs(z - 4) <= 11 ? -0.5 : NaN),
    0, 0, F1_BASE, F1_COLS, F1_ROWS, MAX_LOD_LEVELS),
};
const F1_SD = sdFieldFrom((x, z) => 3 - Math.abs(z - 4),
  0, 0, F1_BASE, F1_COLS, F1_ROWS);
const SUNK_OPEN = waterTileCaps(F1_SUNK.wp, F1_SUNK.hp, 64, null, MAX_LOD_LEVELS);
const SUNK_GATED = waterTileCaps(F1_SUNK.wp, F1_SUNK.hp, 64, F1_SD, MAX_LOD_LEVELS);
checkEq('RED: ungated, the flooded ring makes a 6 m river carry level 2',
  [0, 1, 2, 3].map((t) => SUNK_OPEN.get(`${t},0`)), [2, 2, 2, 2]);
checkEq('…and the sd gate hands back the authored width\'s cap',
  [0, 1, 2, 3].map((t) => SUNK_GATED.get(`${t},0`)), [1, 1, 1, 1]);
check('…the ring really is 4 m of it: sd at |z − 4| = 5 is', 
  gpuWaterSdAt(F1_SD, 0, 9), -2);
check('…and 0 exactly on the outline', gpuWaterSdAt(F1_SD, 0, 7), 0);

checkEq('…so the meander caps at 1 too, and its whole axis comes back',
  [0, 1, 2, 3].map((t) => M_CAPS.get(`${t},0`)), [1, 1, 1, 1]);
// (d) the rejected rule, rebuilt from its own arithmetic.
function ctzCap(field, tileM) {
  const wl = field.wp.levels[0];
  const top = MAX_LOD_LEVELS - 1;
  const ctz = (v) => { if (v === 0) return top;
    let k = 0; while (k < top && (v & (1 << k)) === 0) k += 1; return k; };
  const out = new Map();
  for (let j = 0; j < wl.rows; j += 1) {
    for (let i = 0; i < wl.cols; i += 1) {
      const w = field.wp.data[(wl.row0 + j) * field.wp.texW + i];
      const h = field.hp.data[(field.hp.levels[0].row0 + j) * field.hp.texW + i];
      if (!(w > h)) continue;
      const key = `${Math.floor((i * F1_BASE) / tileM)},${Math.floor((j * F1_BASE) / tileM)}`;
      out.set(key, Math.max(out.get(key) ?? -1, Math.min(ctz(i), ctz(j))));
    }
  }
  return out;
}
check('(d) RED: the "one surviving texel" rule answers 2 for the meander',
  ctzCap(M, 64).get('1,0'), 2);
checkAbove('…at a level whose axis has already lost points', 123 - M2, 0);

// ============================================================================
// [19] THE CAP AS A FIELD — continuous, an upper bound inside, none outside
// ============================================================================
// The cap enters λ (`tlodMorphAt`), and the whole crack-freeness of this
// renderer is that the drawn surface is a function of the WORLD POINT alone. A
// per-tile step function is such a function but a discontinuous one, and a
// discontinuous λ stops the fine side's extra vertices collapsing onto the
// coarse side's edge — a T-junction at every tile border. So the caps are
// sampled at the tile CORNERS, each corner taking the MINIMUM of the four tiles
// that meet there, and mixed bilinearly.
//
// THE FIXTURE is one row of 64 m tiles, tx = 0…31 at tz = 0, all capped at 1.
// Corner b sits between tiles (tz0 − 2 + b) and (tz0 − 1 + b), so with tz0 = 0
// the grid runs z = −64, 0, 64, 128 — four rows — and its outer two touch no
// wet tile and read LOD_CAP_NONE = 6.
// (e) the corner values are 6, 1, 1, 6 and the field between them is the ramp.
// (f) INSIDE a wet tile the field never exceeds that tile's own cap, which is
//     what makes the cap a promise: every corner of the tile is a minimum over
//     four tiles including this one.
// (g) OUTSIDE the grid it is LOD_CAP_NONE, so a world with a pond in one corner
//     pays nothing anywhere else — and a world with no water has NO GRID AT
//     ALL: `buildLodCapGrid` answers null and no texture is ever allocated.
console.log('\n[19] the cap is a continuous field over the tile corners');
const CAP_TILE = 64;
const CAP_ROW = new Map();
for (let tx = 0; tx < 32; tx += 1) CAP_ROW.set(`${tx},0`, 1);
const GRID = buildLodCapGrid(CAP_ROW, CAP_TILE);
checkEq('(e) the grid spans the wet box grown by one tile',
  [GRID.x0, GRID.z0, GRID.step, GRID.cols, GRID.rows], [-64, -64, 64, 35, 4]);
checkEq('…and its corner column reads 6, 1, 1, 6',
  [0, 1, 2, 3].map((b) => GRID.caps[b * GRID.cols + 4]),
  [LOD_CAP_NONE, 1, 1, LOD_CAP_NONE]);
check('(f) inside the wet tile the field is the tile\'s own cap',
  lodCapAt(GRID, 1000, 32), 1);
check('…and at its far corner line still 1', lodCapAt(GRID, 1000, 64), 1);
check('…while a tile out it has ramped half way to "no cap"',
  lodCapAt(GRID, 1000, 96), (1 + LOD_CAP_NONE) / 2);
check('…the ramp is CONTINUOUS, not a step (a quarter of the way)',
  lodCapAt(GRID, 1000, 80), 1 + (LOD_CAP_NONE - 1) / 4);
check('(g) past the grid there is no cap', lodCapAt(GRID, 1000, 200), LOD_CAP_NONE);
check('…nor before it', lodCapAt(GRID, 1000, -100), LOD_CAP_NONE);
check('…nor without a grid at all', lodCapAt(null, 0, 0), LOD_CAP_NONE);
vector("[19] terrain_lod: …and a world without a drop has no grid to allocate", { buildLodCapGrid: (...args) => buildLodCapGrid(...vectorArgs(args)) });
// The selection reads the same field through a square, and must never answer
// ABOVE it — a node coarser than the cap the shader applies inside it would be
// a node without the vertices λ_eff places.
let capBoundOk = 1;
for (let z = -80; z <= 200; z += 7) {
  const square = lodCapOverSquare(GRID, 500, z, 128);
  for (let s = 0; s <= 128; s += 4) {
    if (lodCapAt(GRID, 500 + s, z + s) < square - 1e-9) capBoundOk = 0;
  }
}
check('the square answer never exceeds the field inside it', capBoundOk, 1);

// ============================================================================
// [20] THE SELECTION SPLITS TO THE CAP — and the budget takes it back
// ============================================================================
// The same [5] world — extent [0, 2048]², leaf 64 m, six levels,
// `minLodDistance` 128 — with the camera in the MIDDLE (1024, 200, 1024) so the
// tile row along the south edge is far enough to be drawn coarse, and the cap
// row of [19] under it.
// (h) a node is never emitted above the cap of the square it covers;
// (i) the price is 36 extra pieces, and every one of them stands over the
//     water's own tile row — the cost lands on the water, which is the whole
//     decision;
// (j) RELAXING THE CAP PAST `LOD_CAP_NONE` REPRODUCES THE OLD SELECTION
//     EXACTLY, piece for piece. That is one statement doing two jobs: the
//     budget ladder of `selectLodFitted` (eight halvings, +8 on the cap) ends
//     at the picture this renderer drew before F1 — the river breaks up again,
//     which is a loss and never a crash — and the isolation panel's toggle 22
//     ("Water lift off") is the same addition, which is why it needs no switch
//     of its own.
console.log('\n[20] the selection splits down to the cap, and can be forced back');
const F1_OPTS = {
  x0: 0, z0: 0, x1: 2048, z1: 2048, leafM: 64, levels: MAX_LOD_LEVELS,
  minLodDistance: 128, camX: 1024, camY: 200, camZ: 1024,
  boundsOf: () => ({ min: 0, max: 0 }),
};
const capOfSquare = (x, z, s) => lodCapOverSquare(GRID, x, z, s);
const PLAIN = selectLodNodes(F1_OPTS);
const CAPPED = selectLodNodes({ ...F1_OPTS, lodCapOf: capOfSquare });
const byLevel = (ns) => {
  const c = new Array(MAX_LOD_LEVELS).fill(0);
  ns.forEach((n) => { c[n.level] += 1; });
  return c;
};
checkEq('(h) no piece is coarser than the cap over its own square',
  CAPPED.filter((n) => n.level > capOfSquare(n.x, n.z, n.size) + 1e-9).length, 0);
checkEq('(i) the uncapped selection, by level', byLevel(PLAIN), [0, 12, 16, 12, 0, 0]);
checkEq('…and the capped one — 36 pieces more, all of them over the water',
  byLevel(CAPPED), [0, 28, 32, 16, 0, 0]);
check('…which is the whole extra cost', CAPPED.length - PLAIN.length, 36);
// …and it is CONFINED. The capped band is the grid, z ∈ [−64, 128]; the
// coarsest square that meets it is a 512 m node at z = 0, so nothing the cap
// touches can reach past z + size = 512 — a quarter of the world's depth, and
// the other three quarters are selected exactly as before.
const ADDED = CAPPED.filter((n) => !PLAIN.some((p) => p.x === n.x && p.z === n.z
  && p.size === n.size && p.level === n.level));
checkEq('…and every added piece stands over the water\'s own row of nodes',
  [ADDED.length, ADDED.filter((n) => n.z + n.size > 512).length], [40, 0]);
const RELAXED = selectLodNodes({ ...F1_OPTS,
  lodCapOf: (x, z, s) => capOfSquare(x, z, s) + LOD_CAP_NONE });
checkEq('(j) the cap relaxed past LOD_CAP_NONE is the old selection, piece for piece',
  RELAXED.length === PLAIN.length && RELAXED.every((n, i) => n.x === PLAIN[i].x
    && n.z === PLAIN[i].z && n.size === PLAIN[i].size && n.level === PLAIN[i].level
    && Math.abs(n.morph - PLAIN[i].morph) < 1e-12), true);
const FIT = selectLodFitted({ ...F1_OPTS, lodCapOf: capOfSquare });
checkEq('…and the fitted selection reports the ladder both halves climb',
  [FIT.nodes.length, FIT.coarsenings, FIT.capRelax], [76, 0, 0]);
checkEq('a selection without a cap is what it always was',
  selectLodNodes(F1_OPTS).length, PLAIN.length);

// ============================================================================
// [21] THE CAP DOES NOT CRACK THE GROUND — shared vertices, bit for bit
// ============================================================================
// THE FINDING THAT MADE THE CAP NECESSARY, first. The drawn surface is a
// function of λ and the world point: a vertex snaps onto the world lattice of
// `baseStep · 2^⌊λ⌋` and reads the mip pair (⌊λ⌋, ⌊λ⌋+1), and the piece's own
// level cancels out of both (`morphedVertex`). So SPLITTING A NODE DOWN CHANGES
// NOTHING: the vertices it adds collapse onto the ones the coarse piece already
// had. (kk) measures that on the rugged fixture — which is why the cap had to
// go into λ and not into the node level.
//
// And because it goes into λ, the same probe is what proves it safe: two pieces
// of DIFFERENT levels must still answer the same point and the same height at a
// vertex they share, with the cap on, and on the cap grid's own corner line
// where the field's derivative jumps.
console.log('\n[21] the cap enters λ — and two pieces still meet exactly');
const RUG = (x, z) => Math.sin(x * 0.37) * 3 + Math.cos(z * 0.53) * 2
  + ((x / 2 + z / 2) % 7);
const RUG_N = 513;
const RUG_PYR = buildPyramid(RUG, 0, 0, 2, RUG_N, RUG_N, MAX_LOD_LEVELS);
const RUG_RECT = [0, 0, (RUG_N - 1) * 2, (RUG_N - 1) * 2];
const RUG_RANGES = lodRanges(128, MAX_LOD_LEVELS);
const RUG_CAM = { x: -600, y: 200, z: 512 };
const capField = (x, z) => lodCapAt(GRID, x, z);
// (kk) the same world point, from a level-3 piece and from a level-1 piece.
const P3 = { x: 256, z: 256, size: 512, level: 3, cells: PATCH_N, morph: 0 };
const P1 = { x: 448, z: 448, size: 128, level: 1, cells: PATCH_N, morph: 0 };
const V3 = lodVertex(P3, 16, 16, RUG_PYR, RUG_RECT, null, RUG_RECT, RUG_CAM,
                     RUG_RANGES, null, null);
const V1 = lodVertex(P1, 16, 16, RUG_PYR, RUG_RECT, null, RUG_RECT, RUG_CAM,
                     RUG_RANGES, null, null);
checkEq('(kk) a level-1 piece answers the level-3 piece\'s point and height',
  [V1.x === V3.x, V1.z === V3.z, V1.y === V3.y], [true, true, true]);
const V1B = lodVertex(P1, 17, 16, RUG_PYR, RUG_RECT, null, RUG_RECT, RUG_CAM,
                      RUG_RANGES, null, null);
checkEq('…and the vertex it ADDS collapses onto that same point — the split is inert',
  [V1B.x === V3.x, V1B.z === V3.z, V1B.y === V3.y], [true, true, true]);
// (ll) with the cap on, over its own band, the two still meet.
const C3 = { x: 256, z: -256, size: 512, level: 3, cells: PATCH_N, morph: 0 };
const C1 = { x: 448, z: 0, size: 128, level: 1, cells: PATCH_N, morph: 0 };
const W3 = lodVertex(C3, 16, 20, RUG_PYR, RUG_RECT, null, RUG_RECT, RUG_CAM,
                     RUG_RANGES, null, capField);
const W1 = lodVertex(C1, 16, 16, RUG_PYR, RUG_RECT, null, RUG_RECT, RUG_CAM,
                     RUG_RANGES, null, capField);
checkEq('(ll) ON the cap grid\'s corner line z = 64 the two pieces agree bit for bit',
  [W1.x === W3.x, W1.z === W3.z, W1.y === W3.y], [true, true, true]);
// (mm) and the cap really bites: a far camera, a vertex inside the band.
const FAR_CAM = { x: -1400, y: 300, z: 32 };
const IN = lodVertex(C1, 16, 8, RUG_PYR, RUG_RECT, null, RUG_RECT, FAR_CAM,
                     RUG_RANGES, null, capField);
const OUT = lodVertex(C1, 16, 8, RUG_PYR, RUG_RECT, null, RUG_RECT, FAR_CAM,
                      RUG_RANGES, null, null);
checkEq('(mm) capped, the vertex stays on its own 4 m lattice at (512, 32)',
  [IN.x, IN.z, IN.t], [512, 32, 0]);
checkAbove('…uncapped it is dragged off it by metres', Math.abs(OUT.z - 32), 20);
checkAbove('…because λ had climbed past 3 there', OUT.t, 3);
check('…and the cap at that point is 1', lodCapAt(GRID, 512, 32), 1);
// (nn) a dry world is untouched: no grid, no cap, the same vertex as before F1.
const DRY = lodVertex(P3, 16, 16, RUG_PYR, RUG_RECT, null, RUG_RECT, RUG_CAM,
                      RUG_RANGES, null, () => LOD_CAP_NONE);
checkEq('(nn) "no cap" is the identity on λ — the dry world keeps its surface',
  [DRY.x === V3.x, DRY.z === V3.z, DRY.y === V3.y, DRY.t === V3.t],
  [true, true, true, true]);

// ============================================================================
// [22] THE GLSL SIDE OF THE CAP
// ============================================================================
// BOTH programs declare it, and that is the point: a dry piece and the wet
// piece beside it share vertices, so a cap only one of them knew would open the
// seam the partition exists to keep shut.
console.log('\n[22] the cap in the shader — both programs, one early-out');
for (const [name, src] of [['dry', dryGlsl], ['wet', wetGlsl]]) {
  checkEq(`the ${name} program declares the cap sampler`,
    src.includes('uniform sampler2D uTlodCap;'), true);
  checkEq(`…and clamps λ with it`,
    src.includes('return max( min( tlodLambda( d ), tlodCapAt( p ) ) - iNode.w, 0.0 );'),
    true);
  checkEq(`…and leaves on the first compare without a grid`,
    src.includes(`if ( cols < 2.0 || rows < 2.0 || step <= 0.0 ) return ${LOD_CAP_NONE}.0;`),
    true);
  checkEq(`…and on the rectangle test outside it`,
    src.includes('if ( fx <= 0.0 || fz <= 0.0 || fx >= cols - 1.0 || fz >= rows - 1.0 )'),
    true);
}
checkEq('the cap is bound on the dry program too',
  ['uTlodCap', 'uTlodCapGeom', 'uTlodCapFit']
    .every((k) => dryShader.uniforms[k] !== undefined), true);
checkEq('…and on the wet one',
  ['uTlodCap', 'uTlodCapGeom', 'uTlodCapFit']
    .every((k) => wetShader.uniforms[k] !== undefined), true);
checkEq('RED: and no cap word reaches the dry FRAGMENT shader',
  /tlodCap|uTlodCapFit/.test(dryShader.fragmentShader), false);

// ============================================================================
// [23] THE FLOW A FRAGMENT REALLY READS — H1's parked suspect, measured
// ============================================================================
// THE SUSPICION, parked by the H1 report and taken up here: `vTlodFlow` is
// sampled ONCE PER VERTEX (`tlodFlowAt`) and INTERPOLATED across the triangle,
// so a fragment in the middle of a river reads an affine blend of three vertex
// samples and not the field. If that blend collapses — below the shader's own
// still threshold (`|flow| < 1e-4`, at which the ripple counter-scrolls at the
// kind's STILL speed and can never drift downstream) or merely below about a
// half, at which the crest speed `flowSpeed · |flow|` is halved — then the flow
// is invisible because the varying ate it, and the fix would be to sample the
// flow in the FRAGMENT like the sd and the kind.
//
// ── AND THAT IS WHAT HAPPENED, AND WHAT THE FIX WAS (Task 7, 2026-08-27) ────
// This section only ever measured levels 0 and 1, because the F1 cap held a
// 6 m river there — and inside that cap the varying was fine, which is what
// these numbers still say. It is OUTSIDE the cap that the varying dies: the
// budget fit relaxes the cap by a level per halving step (`selectLodFitted`),
// and at a 16 m vertex spacing a 14 m river band fits BETWEEN two vertices, so
// the blend is exactly (0, 0). The tap therefore moved into the fragment
// (`waterShade.waterFlowGlsl`), and `client3d/scripts/smoke_flow_lod.mjs` pins
// that the flow a pixel drifts at no longer depends on the level at all.
// `drawnFlow` below is the RETIRED path, kept as the baseline it fails against.
//
// ── THE FIELD, BUILT AS THE SERVER BUILDS IT ────────────────────────────────
// `HeightModel.water_raster` writes the unit axis tangent (times the area's
// speed factor, 1 here) at every lattice point of the polygon GROWN by
// `WATER_RASTER_DILATION_M` = 4 m, (0, 0) everywhere else, and then runs the
// two components through a separable box of `WATER_FLOW_BLUR_M` = 4 m radius —
// two texels on the 2 m lattice, i.e. a 5 × 5 box (`_box_blur`, over a padded
// window so no index is clamped).
//
// ── THE HAND TABLE, on the straight 6 m reach of [18] (bed |z − 4| ≤ 3) ─────
// The tangent is (1, 0) everywhere it is written, so the x pass is the
// identity and the z pass alone decides the LENGTH. The written rows are
// |z − 4| ≤ 7, i.e. z = −2, 0, 2, 4, 6, 8, 10; the box at a row z averages the
// five rows z − 4 … z + 4, so |flow| is (how many of those five are written)/5:
//
//     z =  0 -> rows −4… 4 : 4 of 5  -> 0.8
//     z =  2 -> rows −2… 6 : 5 of 5  -> 1
//     z =  4 -> rows  0… 8 : 5 of 5  -> 1
//     z =  6 -> rows  2…10 : 5 of 5  -> 1
//     z =  8 -> rows  4…12 : 4 of 5  -> 0.8
//     z = 10 -> rows  6…14 : 3 of 5  -> 0.6
//     z = 12 -> rows  8…16 : 2 of 5  -> 0.4   (outside, the blur still reaches)
//     z = 14 -> rows 10…18 : 1 of 5  -> 0.2
//
// — symmetric about the axis at z = 4 (z = −2 would read 0.6 and z = −4 0.4,
// off the bottom of this window, which starts at z = 0).
//
// ── WHAT THE TRIANGLE THEN DELIVERS ─────────────────────────────────────────
// The field is constant in x, and barycentric interpolation of three vertices
// is affine, so the drawn value at a point is the LINEAR interpolation in z
// between the two vertex ROWS bracketing it — the triangulation drops out. The
// vertex rows are multiples of `baseStep · 2^level` = 2 m (level 0) and 4 m
// (level 1); those are the only two levels a 6 m river is ever drawn at, because
// the F1 cap is a WIDTH and answers 1 for it ([18](b)).
//
//   level 0, rows 0 (0.8), 2 (1), 4 (1), 6 (1), 8 (0.8):
//       the drawn band is z in (1, 7) — `twInside(sd)` is 0 ON the outline —
//       and the interpolant is 0.9 at z = 1, 1 from z = 2 to 6, 0.9 at z = 7.
//       MINIMUM over the band: 0.9.
//   level 1, rows 0 (0.8), 4 (1), 8 (0.8):
//       z = 1 -> 0.8 + 0.2·(1/4) = 0.85 ;  z = 7 -> 1 − 0.2·(3/4) = 0.85.
//       MINIMUM over the band: 0.85.
//
// ── THE VERDICT ─────────────────────────────────────────────────────────────
// 0.85 is 8 500 times the still threshold and well above the half the crest
// speed would need to be visibly slowed. THE SUSPECT IS ACQUITTED: the
// interpolation of the flow varying is not why the water does not appear to
// flow, and nothing is moved into the fragment for it.
//
// ── AND THE CHECK IS NOT VACUOUS ────────────────────────────────────────────
// The reason the blend survives is the server's DILATION: the box of radius 4 m
// around a point inside the outline still lies inside the written footprint, so
// the vectors it averages are all the same water's (`WATER_FLOW_BLUR_M`'s own
// argument). Build the same field WITHOUT the ring and the same measurement
// convicts at once — rows 2, 4, 6 written, so z = 4 averages 3 of 5 = 0.6,
// z = 0 and z = 8 average 2 of 5 = 0.4, and level 1 reads
// 0.4 + 0.2·(1/4) = 0.45 at z = 1, under the half. That is the RED probe below:
// the threshold is one this fixture can really fail.
console.log('\n[23] the flow varying survives the triangle (H1, acquitted)');
const FLOW_DIL = 4;            // WATER_RASTER_DILATION_M
const FLOW_BLUR = 2;           // WATER_FLOW_BLUR_M / TILE_STEP_M, in texels

/** The server's flow raster over the [18] window: the unit axis tangent inside
 *  the grown outline, (0, 0) outside, then a separable 5 × 5 box over a padded
 *  sample — `heightfield._box_blur`, line for line, margin included. */
function flowFieldOf(zcOf, dzOf, half, ring = FLOW_DIL) {
  const pad = FLOW_BLUR;
  const pc = F1_COLS + 2 * pad;
  const pr = F1_ROWS + 2 * pad;
  const raw = [];
  for (let j = 0; j < pr; j += 1) {
    const z = (j - pad) * F1_BASE;
    const row = [];
    for (let i = 0; i < pc; i += 1) {
      const x = (i - pad) * F1_BASE;
      // The nearest point of the axis, by scan — the twin of `_axis_nearest`
      // on a curve rather than on its polyline, which is the same answer for a
      // line sampled every 2 m and a curvature radius of 100 m.
      let bestD2 = Infinity;
      let bestX = x;
      for (let t = x - 40; t <= x + 40; t += 0.05) {
        const d2 = (x - t) ** 2 + (z - zcOf(t)) ** 2;
        if (d2 < bestD2) { bestD2 = d2; bestX = t; }
      }
      if (Math.sqrt(bestD2) > half + ring) { row.push(0, 0); continue; }
      const m = dzOf(bestX);
      const len = Math.hypot(1, m);
      row.push(1 / len, m / len);
    }
    raw.push(row);
  }
  const n = 2 * FLOW_BLUR + 1;
  const data = new Float32Array(F1_COLS * F1_ROWS * 2);
  for (let c = 0; c < 2; c += 1) {
    // x pass over EVERY padded row, cropped to the window's columns…
    const xp = raw.map((row) => {
      const out = [];
      for (let i = pad; i < pad + F1_COLS; i += 1) {
        let acc = 0;
        for (let k = i - FLOW_BLUR; k <= i + FLOW_BLUR; k += 1) acc += row[k * 2 + c];
        out.push(acc / n);
      }
      return out;
    });
    // …then the z pass over the window's rows.
    for (let j = pad; j < pad + F1_ROWS; j += 1) {
      for (let i = 0; i < F1_COLS; i += 1) {
        let acc = 0;
        for (let k = j - FLOW_BLUR; k <= j + FLOW_BLUR; k += 1) acc += xp[k][i];
        data[(((j - pad) * F1_COLS) + i) * 2 + c] = acc / n;
      }
    }
  }
  return { originX: 0, originZ: 0, step: F1_BASE,
           cols: F1_COLS, rows: F1_ROWS, data };
}

/** |flow| as the RASTERIZER delivers it at (x, z) when the ground is drawn at
 *  `level`: the vertex sampler at the three corners of the triangle the point
 *  falls in (`patchGeometry`'s split: (i,j),(i,j+1),(i+1,j+1) and
 *  (i,j),(i+1,j+1),(i+1,j)), blended barycentrically. */
function drawnFlow(field, x, z, level) {
  const e = F1_BASE * (1 << level);
  const i = Math.floor(x / e);
  const j = Math.floor(z / e);
  const u = x / e - i;
  const v = z / e - j;
  const P = (a, b) => gpuWaterFlowAt(field, (i + a) * e, (j + b) * e);
  const [A, B, C, wb, wc] = u <= v
    ? [P(0, 0), P(0, 1), P(1, 1), v - u, u]
    : [P(0, 0), P(1, 1), P(1, 0), v, u - v];
  const wa = 1 - wb - wc;
  return Math.hypot(A[0] * wa + B[0] * wb + C[0] * wc,
                    A[1] * wa + B[1] * wb + C[1] * wc);
}

/** The smallest |flow| anywhere the water DRAWS — inside the authored outline,
 *  where `twInside(sd) > 0` — sampled every 25 cm along and across. */
function drawnFlowMin(field, zcOf, half, level, x0 = 20, x1 = 240) {
  let min = Infinity;
  for (let x = x0; x <= x1; x += 0.25) {
    for (let d = -half; d <= half; d += 0.25) {
      const z = zcOf(x) + d;
      if (z < 0 || z > (F1_ROWS - 1) * F1_BASE) continue;
      min = Math.min(min, drawnFlow(field, x, z, level));
    }
  }
  return min;
}

const R_FLOW = flowFieldOf(RIVER_ZC, () => 0, 3);
// (a) the blurred lattice profile — the eight numbers of the hand table.
checkEq('(a) the blurred |flow| on the lattice rows of the straight reach',
  [0, 2, 4, 6, 8, 10, 12, 14].map((z) => Math.round(
    Math.hypot(...gpuWaterFlowAt(R_FLOW, 100, z)) * 1e6) / 1e6),
  [0.8, 1, 1, 1, 0.8, 0.6, 0.4, 0.2]);
// (b) what the drawn triangle hands the fragment, at both capped levels.
check('(b) level 0: the bank of the drawn band reads',
  drawnFlow(R_FLOW, 100, 1, 0), 0.9, 1e-6);
check('…and its middle reads the unit tangent', drawnFlow(R_FLOW, 100, 4, 0), 1,
  1e-6);
check('…the far bank, symmetrically', drawnFlow(R_FLOW, 100, 7, 0), 0.9, 1e-6);
check('level 1 (the F1 cap): the bank reads', drawnFlow(R_FLOW, 100, 1, 1),
  0.85, 1e-6);
check('…and the middle still the unit tangent',
  drawnFlow(R_FLOW, 100, 4, 1), 1, 1e-6);
check('…the far bank', drawnFlow(R_FLOW, 100, 7, 1), 0.85, 1e-6);
checkAbove('…so nothing the reach draws is below a half at level 0',
  drawnFlowMin(R_FLOW, RIVER_ZC, 3, 0), 0.5);
checkAbove('…nor at level 1', drawnFlowMin(R_FLOW, RIVER_ZC, 3, 1), 0.5);
// (c) THE MEANDER of [18], where the tangent really turns and the medial axis
//     of a bend is the thing the bake's blur exists for.
const M_FLOW = flowFieldOf(MEANDER_ZC,
  (x) => 4 * ((2 * Math.PI) / 128) * Math.cos((2 * Math.PI * x) / 128), 3);
const M_MIN0 = drawnFlowMin(M_FLOW, MEANDER_ZC, 3, 0);
const M_MIN1 = drawnFlowMin(M_FLOW, MEANDER_ZC, 3, 1);
checkAbove('(c) the meander at level 0 never falls below a half', M_MIN0, 0.5);
checkAbove('…nor at level 1', M_MIN1, 0.5);
checkAbove('…and both are four orders above the shader\'s still threshold',
  Math.min(M_MIN0, M_MIN1) / 1e-4, 1000);
checkAbove('…the reach\'s minimum too', drawnFlowMin(R_FLOW, RIVER_ZC, 3, 1) / 1e-4,
  1000);
// (d) RED — the same measurement WITHOUT the server's dilation ring, which is
//     what a convicting field would look like. Rows 2, 4, 6 written only.
const NAKED = flowFieldOf(RIVER_ZC, () => 0, 3, 0);
checkEq('(d) RED: with no dilation ring the lattice profile collapses',
  [0, 2, 4, 6, 8].map((z) => Math.round(
    Math.hypot(...gpuWaterFlowAt(NAKED, 100, z)) * 1e6) / 1e6),
  [0.4, 0.6, 0.6, 0.6, 0.4]);
checkBelow('RED: …and the drawn bank falls under the half at level 1',
  drawnFlow(NAKED, 100, 1, 1), 0.5);
checkBelow('RED: …i.e. the threshold IS one this fixture can fail',
  drawnFlowMin(NAKED, RIVER_ZC, 3, 1), 0.5);

// ============================================================================
// [24] THE DRIFT REACHES THE COMPILED FRAGMENT — the chain, end to end
// ============================================================================
// The numeric twins of `smoke_water_shade.mjs` [9] prove the drift arithmetic
// carries a crest downstream. What no twin can see is a break in the CHAIN
// between that arithmetic and the program the card runs: a `textureGrad` fed
// some other coordinate, a `uTlodTime` bound to a second clock, an insertion
// that stopped matching three's chunk name. So the whole path is pinned here as
// TEXT, on `wetShader.fragmentShader` — the source three would compile — and
// not on the generator's return value.
console.log('\n[110] the graphics switch reaches existing wet programs');
checkEq('wet shader holds the shared extras uniform', wetShader.uniforms.uWaterExtras === extras.waterExtrasUniform, true);
extras.setWaterExtrasEnabled(false);
checkEq('off changes the existing program without replacing the water material', wetShader.uniforms.uWaterExtras.value, 0);
extras.setWaterExtrasEnabled(true);
checkEq('on restores the existing program', wetShader.uniforms.uWaterExtras.value, 1);
checkEq('foam and normal-map reads are inside the extras branch',
  /if \( uWaterExtras > 0\.5 \) \{[\s\S]*float rawFoam[\s\S]*twN = twRipple/.test(wetFrag), true);
console.log('\n[24] the drift chain reaches the compiled fragment');
checkEq('the wet fragment declares the shared clock',
  wetFrag.includes('uniform float uTlodTime;'), true);
checkEq('…and it is bound to the ONE object the engine advances per frame',
  wetShader.uniforms.uTlodTime === mats.surfaceTimeUniform, true);
checkEq('the flowing branch takes sgn = −1 (downstream) and the still one +1',
  wetFrag.includes('float sgn = still ? 1.0 : -1.0;'), true);
checkEq('…and its speed is the kind\'s flow dial times the raster\'s factor',
  wetFrag.includes('float sp = still ? speed : flowSpeed * len;'), true);
checkEq('sheet A\'s sample coordinate carries the uTlodTime drift',
  wetFrag.includes('vec2 uvA = twFrame( p / lamA + dirA * ( uTlodTime * sp '
    + '* sgn / lamA ), ax, ay, aniso );'), true);
checkEq('…sheet B\'s',
  wetFrag.includes('vec2 uvB = twFrame( p / lamB + dirB * ( uTlodTime * sp '
    + '* sgn / lamB ), ax, ay, aniso );'), true);
checkEq('…and the streak ribbon\'s',
  wetFrag.includes('vec2 uvC = twFrame( ( p + ax * ( uTlodTime * sp * sgn ) ) '
    + '/ lamC, ax, ay, 8.0 );'), true);
// …AND THOSE VERY COORDINATES ARE WHAT IS SAMPLED. A drift computed into a
// variable nothing reads would pass every check above.
checkEq('the wave map is fetched AT uvA, uvB and uvC',
  wetFrag.includes('vec3 nA = textureGrad( uTlodWave, uvA,')
  && wetFrag.includes('vec3 nB = textureGrad( uTlodWave, uvB,')
  && wetFrag.includes('vec3 nC = textureGrad( uTlodWave, uvC,'), true);
checkEq('…the three sheets become the ripple normal',
  wetFrag.includes('vec3 n = normalize( nA + nB + nC * ( still ? 0.0 : 0.35 ) );'),
  true);
checkEq('…which the measurement stage stores in twN',
  wetFrag.includes('twN = twRipple( vTlodXZ, gx, gy, max( look1.x, 0.05 ), '
    + 'look1.y, look1.z );'), true);
checkEq('…and the shading normal really carries twN into the lighting',
  wetFrag.includes('vec3 nw = normalize( macro + ( twN - up ) * twS );')
  && wetFrag.includes('normal = tlodWaterNormal();'), true);
// The still branch is what a flow of (0, 0) falls into — the one state in which
// nothing can drift downstream however fast the kind's dial is set. Pinned so a
// report that reads STILL off the debug line knows what it is naming.
checkEq('the still test is the 1e-4 the WATER line reports against',
  wetFrag.includes('bool still = len < 1e-4;')
  && wetFrag.includes('float len = length( flow );'), true);
checkEq('…and it is decided on THIS PIXEL\'s tap, never on a varying',
  wetFrag.includes('vec2 flow = twFlowAt( p );')
  && !wetFrag.includes('vTlodFlow'), true);
checkEq('RED: and none of it reaches the dry program',
  /uvA|twRipple|uTlodTime/.test(dryShader.fragmentShader), false);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
