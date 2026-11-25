#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/undergrowth.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_undergrowth.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';

import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const LOD_SRC = join(ROOT, 'client3d/src/scene/scatterLod.ts');
const UG_SRC = join(ROOT, 'client3d/src/scene/undergrowth.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

/** `scatterLod.ts` has no import at all (see its header), so a transpile is
 *  all it takes. */
async function loadLod() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'undergrowth-'));
  try {
    const source = await readFile(LOD_SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/**
 * Bundle `undergrowth.ts` together with the wind patch it is handed and the
 * shared sampler it draws from, and import the lot. `external: ['three']`
 * keeps node's own three the only one in play, which is what lets sections
 * (F) and (G) inspect REAL materials and REAL instanced meshes.
 *
 * `mutate` rewrites the BUILT text before the import — that is how (B3), (D9)
 * and (F5) get a wrong module to compare against without a second copy of the
 * code lying around to rot.
 */
async function loadField(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-ug-'));
  try {
    const entry = `export * from '${UG_SRC}';\n`
      + `export { applySway } from '${GROUND_SRC}';\n`
      + "export { scatterInstances, scatterSeed } from '@anima/scene-render';\n";
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'undergrowth.mjs'), external: ['three', 'three/*'],
    });
    const text = built.outputFiles[0].text;
    const source = mutate ? mutate(text) : text;
    const file = join(dir, 'undergrowth.mjs');
    await writeFile(file, source, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section (B3)'s mutant: the seed forgets the CELL, so every cell of an area
 *  draws the same sequence of random numbers — one tuft pattern stamped out
 *  across the world every 64 m. */
function seedWithoutCell(text) {
  const anchor = /return `terrain:undergrowth:\$\{areaId\}:\$\{cx\},\$\{cz\}`;/;
  if (!anchor.test(text)) throw new Error('the cell seed is no longer where the probe looks');
  return text.replace(anchor, 'return `terrain:undergrowth:${areaId}`;');
}

/** Section (D9)'s mutant: every texel is opaque, so the blades stop being a
 *  silhouette and the alpha cut has nothing left to cut. */
function opaqueTexture(text) {
  const anchor = 'out[o + 3] = Math.round(255 * cov);';
  if (!text.includes(anchor)) throw new Error('the alpha write is no longer where the probe looks');
  return text.replace(anchor, 'out[o + 3] = 255;');
}

/** Section (F5)'s mutant: the material loses its alpha cut and draws every
 *  texel of all three quads — three solid boards per tuft. */
function noAlphaTest(text) {
  const anchor = 'alphaTest: UNDERGROWTH_ALPHA_TEST,';
  if (!text.includes(anchor)) throw new Error('the alpha cut is no longer where the probe looks');
  return text.replace(anchor, '');
}

/** Section (D12)'s mutant: the blade ramp is flattened to its middle, so every
 *  blade carries the tint (1, 1, 1) and the texture is greyscale again — the
 *  picture this round exists to replace. The headroom division stays (it hangs
 *  on `BLADE_BROWN`, not on the ramp), so the mutant differs from the real
 *  texture in the COLOUR CHANNELS ALONE. */
function flatBladeRamp(text) {
  const anchor = 'BLADE_RAMP = [5, 1, 6, 0, 8, 2, 7, 3, 4]';
  if (!text.includes(anchor)) throw new Error('the blade ramp is no longer where the probe looks');
  return text.replace(anchor, 'BLADE_RAMP = [4, 4, 4, 4, 4, 4, 4, 4, 4]');
}

/** Section (F1a)'s mutant: the star becomes fully symmetric, so a field of
 *  tufts repeats every third of a turn. */
function symmetricStar(text) {
  const anchor = 'UNDERGROWTH_STAR_DEG = [0, 55, 118]';
  if (!text.includes(anchor)) throw new Error('the star angles are no longer where the probe looks');
  return text.replace(anchor, 'UNDERGROWTH_STAR_DEG = [0, 60, 120]');
}

/** Section (F6c)'s mutant: the mix only ever runs from A to the middle, so
 *  the whole layer drifts towards the dark end of its own palette. */
function oneSidedTint(text) {
  const anchor = 'Number.isFinite(v) ? Math.min(Math.max(v, 0), 1) : 0.5;';
  if (!text.includes(anchor)) throw new Error('the tint mix is no longer where the probe looks');
  return text.replace(anchor,
    'Number.isFinite(v) ? Math.min(Math.max(v, 0), 1) * 0.5 : 0.5;');
}

/** Section (F6e)'s mutant: the binning compacts the matrices but leaves the
 *  colours in index order, so a drawn tuft wears its displaced neighbour's
 *  shade. */
function noColorCompaction(text) {
  const anchor = 'if (colBuf) copyColor(layer.srcColor, i, colBuf, n);';
  if (!text.includes(anchor)) throw new Error('the colour compaction is no longer where the probe looks');
  return text.replace(anchor, '');
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
    console.log(`  FAIL ${label}`);
    console.log(`       expected ${JSON.stringify(expected)}`);
    console.log(`       actual   ${JSON.stringify(actual)}`);
  }
}

function checkNot(label, actual, forbidden, eps = 1e-9) {
  const same = compare(actual, forbidden, eps);
  if (!same) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}`);
    console.log(`       must NOT equal ${JSON.stringify(forbidden)}`);
  }
}

function compare(a, b, eps) {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((v, i) => compare(v, b[i], eps));
  }
  if (typeof a === 'number' && typeof b === 'number') {
    return Number.isNaN(a) ? Number.isNaN(b) : Math.abs(a - b) <= eps;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

/** The in-cell offsets of a sampled point list — what makes "these two cells
 *  are the same pattern" a measurement rather than an impression. */
function offsets(points, cx, cz, cellM) {
  return points.map((p) => [p.x - cx * cellM, p.z - cz * cellM]);
}

async function main() {
  const lod = await loadLod();
  const field = await loadField();
  const pixels = field.undergrowthTexturePixels();
  const geometry = (h) => {
    const geo = field.undergrowthGeometry(h);
    try {
      const triples = (key) => {
        const a = geo.getAttribute(key);
        return Array.from({ length: a.count }, (_, i) => [a.getX(i), a.getY(i), a.getZ(i)]);
      };
      return { positions: triples('position'), normals: triples('normal'), indices: Array.from(geo.index.array) };
    } finally { geo.dispose(); }
  };
  const vectors = runVectors(loadVectors('undergrowth'), {
    ...lod, ...field, undergrowthGeometry: geometry,
    undergrowthTexel: (r, c, channel) => {
      const offset = (r * 64 + c) * 4;
      return channel === undefined ? Array.from(pixels.slice(offset, offset + 4)) : pixels[offset + channel];
    },
    undergrowthRowInk: (r) => {
      let ink = 0;
      for (let c = 0; c < 64; c++) ink += pixels[(r * 64 + c) * 4 + 3] / 255;
      return ink;
    },
  });
  passed += vectors.passed; failed += vectors.failed;
  const {
    UNDERGROWTH_CELL_M, UNDERGROWTH_CELL_RADIUS_M, UNDERGROWTH_CULL_M,
    UNDERGROWTH_DENSITY_PER_M2, UNDERGROWTH_FADE_M, UNDERGROWTH_H_MAX,
    UNDERGROWTH_H_MIN, UNDERGROWTH_MAX_PER_CELL, UNDERGROWTH_MIN_SHARE,
    SCATTER_MIN_SHARE, instanceHash, instanceShare, SCATTER_LOD_DEFAULTS,
    undergrowthCellCount, undergrowthDensityPer100m2, undergrowthHeight,
    undergrowthShare, undergrowthVisible,
  } = lod;
  const {
    createUndergrowthField, scatterInstances, scatterSeed,
    undergrowthCellKey, undergrowthCellSeed,
    undergrowthGeometry, undergrowthMaterial, undergrowthShade,
    undergrowthTexture, undergrowthTexturePixels, undergrowthTint,
    wantedUndergrowthCells, applySway,
    UNDERGROWTH_ALPHA_TEST, UNDERGROWTH_H_REF_M, UNDERGROWTH_TEX_SIZE,
    UNDERGROWTH_BLADES, UNDERGROWTH_BLADE_TINTS,
    UNDERGROWTH_TINT_A, UNDERGROWTH_TINT_B,
  } = field;
  const TAU = Math.PI * 2;

  console.log('(A) the cell raster — which cells the layer holds');
  check('A the raster is 64 m, the window 128 m',
    [UNDERGROWTH_CELL_M, UNDERGROWTH_CELL_RADIUS_M], [64, 128]);
  check('A the key is "cx,cz"', undergrowthCellKey(-2, 3), '-2,3');
  // A cell owns its LOWER edge (`Math.floor`), which a radius of 0 shows
  // directly: it answers with the anchor's own cell and nothing else.

  // (A1) the anchor in the middle of its cell
  const midCell = wantedUndergrowthCells(32, 32);
  check('A1 an anchor at a cell centre holds 21 cells — 25 less four corners',
    midCell.length, 21);
  check('A1 …and the nearest is its own', midCell[0], '0,0');
  check('A1 …the four corners are exactly the ones missing',
    ['-2,-2', '-2,2', '2,-2', '2,2'].filter((k) => midCell.includes(k)), []);
  check('A1 …while their neighbours along the axes are in',
    ['-2,-1', '-2,0', '2,1', '0,2'].every((k) => midCell.includes(k)), true);

  // (A2) the anchor on a corner — the asymmetric case
  const cornerCell = wantedUndergrowthCells(0, 0);
  check('A2 an anchor ON a cell corner holds 20', cornerCell.length, 20);
  check('A2 …and the tie between the four cells it touches goes by key',
    cornerCell[0], '-1,-1');
  check('A2 …the cell whose near edge is exactly 128 m away is still in',
    cornerCell.includes('2,0'), true);
  check('A2 …but its neighbour one row up is out',
    cornerCell.includes('2,1'), false);

  // (A3) the crossing
  const eastCell = wantedUndergrowthCells(96, 32);
  const dropped = midCell.filter((k) => !eastCell.includes(k));
  const added = eastCell.filter((k) => !midCell.includes(k));
  check('A3 one cell east is still 21 cells', eastCell.length, 21);
  check('A3 …five of them are new and five are gone',
    [dropped.length, added.length], [5, 5]);
  const nudged = wantedUndergrowthCells(63, 32);
  check('A3b a step INSIDE the cell still moves the window — it is the POINT '
    + 'the radius is measured from', nudged.length, 21);
  check('A3b …two out, two in',
    [midCell.filter((k) => !nudged.includes(k)).sort(),
      nudged.filter((k) => !midCell.includes(k)).sort()],
    [['-2,-1', '-2,1'], ['2,-2', '2,2']]);

  // (A4) junk
  for (const [x, z, name] of [[NaN, 0, 'a NaN anchor'],
    [0, Infinity, 'an infinite anchor']]) {
    check(`A4 ${name} holds no cells`, wantedUndergrowthCells(x, z), []);
  }

  console.log('\n(B) the seed — one per (area, cell)');

  check('B1 …and is not the authored scatter\'s',
    undergrowthCellSeed('ta_1', 0, 0) !== scatterSeed('ta_1', 0), true);

  // (B2) the cell keeps neighbours apart — measured on the in-cell offsets
  const CELL = UNDERGROWTH_CELL_M;
  const cellRing = (cx, cz) => [
    [cx * CELL, cz * CELL], [(cx + 1) * CELL, cz * CELL],
    [(cx + 1) * CELL, (cz + 1) * CELL], [cx * CELL, (cz + 1) * CELL],
  ];
  const sampleCell = (cx, cz, seed) => scatterInstances({
    ring: cellRing(cx, cz),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed,
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
  });
  const cell00 = sampleCell(0, 0, undergrowthCellSeed('ta_1', 0, 0));
  const cell10 = sampleCell(1, 0, undergrowthCellSeed('ta_1', 1, 0));
  check('B2 the same cell asked twice is the same tufts',
    sampleCell(0, 0, undergrowthCellSeed('ta_1', 0, 0)).slice(0, 5),
    cell00.slice(0, 5));
  checkNot('B2 …while the cell next door is a different pattern',
    offsets(cell10, 1, 0, CELL).slice(0, 5),
    offsets(cell00, 0, 0, CELL).slice(0, 5));

  // (B3) the red counter-check
  const noCell = await loadField(seedWithoutCell);
  const stamped00 = sampleCell(0, 0, noCell.undergrowthCellSeed('ta_1', 0, 0));
  const stamped10 = sampleCell(1, 0, noCell.undergrowthCellSeed('ta_1', 1, 0));
  check('B3 the "seed without the cell" mutant stamps ONE pattern everywhere',
    offsets(stamped10, 1, 0, CELL).slice(0, 5),
    offsets(stamped00, 0, 0, CELL).slice(0, 5));
  check('B3 …which the real seed measurably is not',
    compare(offsets(cell10, 1, 0, CELL).slice(0, 5),
      offsets(cell00, 0, 0, CELL).slice(0, 5), 1e-9), false);

  console.log('\n(C) how many — the density, per cell');
  check('C1 the base density is 0.80 tufts per square metre',
    UNDERGROWTH_DENSITY_PER_M2, 0.80);

  check('C2 …and the sampler really places 1966 of them',
    cell00.length, 1966);
  check('C3 the ceiling is 8000 per cell', UNDERGROWTH_MAX_PER_CELL, 8000);
  check('C3 …which full density does not come near',
    undergrowthCellCount(1) < UNDERGROWTH_MAX_PER_CELL, true);
  for (const [bad, name] of [[0, '0'], [-1, '-1'], [NaN, 'NaN'],
    ['thick', 'a string'], [null, 'null'], [undefined, 'undefined']]) {
    check(`C4 a value of ${name} grows nothing`,
      [undergrowthCellCount(bad), undergrowthDensityPer100m2(bad)], [0, 0]);
  }

  console.log('\n(D) the blade texture — a pure pixel function');
  const N = UNDERGROWTH_TEX_SIZE;
  const tex = undergrowthTexturePixels(N);
  const at = (r, c) => (r * N + c) * 4;
  check('D1 the texture is 64 x 64 and nine blades wide',
    [N, UNDERGROWTH_BLADES], [64, 9]);
  check('D1 …and comes back as RGBA bytes',
    [tex.length, tex instanceof Uint8ClampedArray], [64 * 64 * 4, true]);

  const rowInk = (r) => {
    let sum = 0;
    for (let c = 0; c < N; c += 1) sum += tex[at(r, c) + 3] / 255;
    return sum;
  };

  let topInk = 0;
  for (let r = 58; r < N; r += 1) topInk += rowInk(r);

  let footInk = 0;
  for (let r = 0; r < 10; r += 1) footInk += rowInk(r);
  check('D8 the ten lowest rows carry exactly 460.23 texels of ink',
    footInk, 460.234, 0.5);
  let ink = 0;
  let clear = 0;
  for (let r = 0; r < N; r += 1) {
    for (let c = 0; c < N; c += 1) {
      const a = tex[at(r, c) + 3];
      ink += a / 255;
      if (a === 0) clear += 1;
    }
  }
  check('D8 the whole texture stays under the 1202.7 texels the widths allow',
    ink < 1202.7, true);
  check('D8 …so at least 2059 of its 4096 texels are pure hole',
    clear >= 2059, true);

  // (D9) the red counter-check
  const solid = await loadField(opaqueTexture);
  const solidTex = solid.undergrowthTexturePixels(N);
  let solidClear = 0;
  let solidInk = 0;
  for (let i = 3; i < solidTex.length; i += 4) {
    solidInk += solidTex[i] / 255;
    if (solidTex[i] === 0) solidClear += 1;
  }
  check('D9 the "always opaque" mutant is a solid square, not a tuft',
    [solidInk, solidClear], [64 * 64, 0]);
  check('D9 …which is measurably not what the real function draws',
    [ink < solidInk / 3, clear >= 2059], [true, true]);

  // (D10) the two ends of the ramp, at the roots of the blades that carry them
  check('D10 there is one tint per blade', UNDERGROWTH_BLADE_TINTS.length,
    UNDERGROWTH_BLADES);
  check('D10 blade 3 is the brownest — BROWN times its own 1.05 of brightness',
    [...UNDERGROWTH_BLADE_TINTS[3]], [1.26, 0.903, 1.0185], 1e-12);
  check('D10 …and blade 4 the greenest — GREEN times 0.95',
    [...UNDERGROWTH_BLADE_TINTS[4]], [0.76, 1.083, 0.9785], 1e-12);
  // The two ends MIRROR in (1, 1, 1), read back out of the built table by
  // dividing each end by the brightness it carries. Same construction as
  // (F6a), one scale finer.
  check('D10 …so the two ends of the ramp sum to exactly (2, 2, 2)',
    [UNDERGROWTH_BLADE_TINTS[3][0] / 1.05 + UNDERGROWTH_BLADE_TINTS[4][0] / 0.95,
      UNDERGROWTH_BLADE_TINTS[3][1] / 1.05 + UNDERGROWTH_BLADE_TINTS[4][1] / 0.95,
      UNDERGROWTH_BLADE_TINTS[3][2] / 1.05 + UNDERGROWTH_BLADE_TINTS[4][2] / 0.95],
    [2, 2, 2], 1e-12);
  const rgb = (t, r, c) => [t[at(r, c)], t[at(r, c) + 1], t[at(r, c) + 2]];

  check('D10 …i.e. red 51 above green, on an opaque texel',
    [rgb(tex, 0, 24)[0] - rgb(tex, 0, 24)[1], tex[at(0, 24) + 3]], [51, 255]);

  check('D10 …i.e. green 46 above red, the other way round',
    [rgb(tex, 0, 31)[1] - rgb(tex, 0, 31)[0], tex[at(0, 31) + 3]], [46, 255]);

  // (D11) no drift on the texture itself — every blade pixel against the
  // neutral of its OWN row, read out of the texture at a texel of that row no
  // blade covers, and weighted by how much of the texel the blade covers.
  const channelMean = (t) => {
    const sum = [0, 0, 0];
    let weight = 0;
    for (let r = 0; r < N; r += 1) {
      let neutral = 0;
      for (let c = 0; c < N && !neutral; c += 1) {
        if (t[at(r, c) + 3] === 0) neutral = t[at(r, c)];
      }
      if (!neutral) continue;
      for (let c = 0; c < N; c += 1) {
        const a = t[at(r, c) + 3];
        if (!a) continue;
        weight += a / 255;
        for (let k = 0; k < 3; k += 1) sum[k] += (a / 255) * (t[at(r, c) + k] / neutral);
      }
    }
    return sum.map((v) => v / weight);
  };
  const texMean = channelMean(tex);
  check(`D11 the mean over the blade pixels is the neutral grey within 2 % `
    + `(got ${texMean.map((v) => v.toFixed(4)).join(', ')})`,
    texMean.every((v) => Math.abs(v - 1) <= 0.02), true);
  check('D11 …and it is the derived 1.0039 / 0.9973 / 0.9994, not merely inside '
    + 'the band', texMean, [1.0039, 0.9973, 0.9994], 0.004);

  // (D12) the red counter-check — the ramp flattened to its middle
  const flatRamp = await loadField(flatBladeRamp);
  const flatTex = flatRamp.undergrowthTexturePixels(N);
  check('D12 the "flat ramp" mutant gives every blade the neutral tint',
    [...flatRamp.UNDERGROWTH_BLADE_TINTS[3], ...flatRamp.UNDERGROWTH_BLADE_TINTS[4]],
    [1, 1, 1, 1, 1, 1], 1e-12);
  check('D12 …so the two blades of (D10) come out the row\'s plain grey, both '
    + 'of them the same 142', [rgb(flatTex, 0, 24), rgb(flatTex, 0, 31)],
    [[142, 142, 142], [142, 142, 142]]);
  check('D12 …i.e. the red-minus-green of (D10) collapses to nothing',
    [rgb(flatTex, 0, 24)[0] - rgb(flatTex, 0, 24)[1],
      rgb(flatTex, 0, 31)[1] - rgb(flatTex, 0, 31)[0]], [0, 0]);
  // …while everything that is NOT the ramp is untouched: same silhouette, same
  // neutral. That is what makes the difference above attributable to the ramp.
  let flatInk = 0;
  for (let i = 3; i < flatTex.length; i += 4) flatInk += flatTex[i] / 255;
  check('D12 …and its alpha and its neutral grey are the real ones, bit for bit',
    [flatInk, flatTex[at(0, 35)], flatTex[at(63, 0)]],
    [ink, tex[at(0, 35)], tex[at(63, 0)]], 1e-9);

  console.log('\n(E) the LOD ladder — its own numbers, beside the props\'');
  check('E the layer is drawn to 60 m and thinned from 30 m',
    [UNDERGROWTH_FADE_M, UNDERGROWTH_CULL_M], [30, 60]);
  check('E …and it fades to NOTHING, where the props keep a quarter',
    [UNDERGROWTH_MIN_SHARE, SCATTER_MIN_SHARE], [0, 0.25]);
  check('E a tuft is shin-high, 0.24 .. 0.42 m',
    [UNDERGROWTH_H_MIN, UNDERGROWTH_H_MAX], [0.24, 0.42]);
  check('E …which is exactly 60 % of the 0.4 .. 0.7 m of the round before',
    [UNDERGROWTH_H_MIN / 0.4, UNDERGROWTH_H_MAX / 0.7], [0.6, 0.6], 1e-12);

  for (const [bad, name] of [[NaN, 'NaN'], ['x', 'a string'],
    [undefined, 'undefined']]) {
    check(`E1 a yaw of ${name} is the shortest blade, never a NaN scale`,
      undergrowthHeight(bad), 0.24);
  }

  check('E2 a NaN distance draws nothing', undergrowthShare(NaN), 0);
  check('E2 at 45 m the props draw everything while the carpet is halved',
    [instanceShare(45, SCATTER_LOD_DEFAULTS), undergrowthShare(45)], [1, 0.5]);

  const grown = (d, n = 1000) => {
    const out = [];
    for (let i = 0; i < n; i += 1) if (undergrowthVisible(i, d)) out.push(i);
    return out;
  };
  check('E3 inside 30 m every tuft is drawn', grown(30).length, 1000);
  check('E3 at the cull distance none is — nothing can pop there',
    grown(60).length, 0);
  check('E3 the set at 45 m is the SAME set when asked again',
    grown(45), grown(45));
  const near375 = new Set(grown(37.5));
  check('E3 what is drawn at 52.5 m is still drawn at 37.5 m',
    grown(52.5).filter((i) => !near375.has(i)).length, 0);
  for (const [d, share] of [[37.5, 0.75], [45, 0.5], [52.5, 0.25]]) {
    const n = grown(d).length;
    check(`E3 ${d} m draws ${1000 * share} of 1000, within 5 % (got ${n})`,
      Math.abs(n - 1000 * share) <= 0.05 * 1000 * share, true);
  }

  console.log('\n(F) the look — a star of quads with an alpha cut');
  check('F the geometry stands at the middle of the height span',
    UNDERGROWTH_H_REF_M, 0.33);
  const geo = undergrowthGeometry(UNDERGROWTH_H_REF_M);
  const gp = geo.getAttribute('position');

  geo.computeBoundingBox();
  check('F1 the tuft STANDS on the ground (B16): y runs 0 .. 0.33',
    [geo.boundingBox.min.y, geo.boundingBox.max.y], [0, 0.33], 1e-6);
  // The angle of a card, read back OUT of its first vertex
  // (−halfW·cos, 0, halfW·sin) — so the assertion is about the built geometry
  // and not about the constant the builder read.
  const cardDeg = (g, q) => {
    const a = (Math.atan2(g.getZ(q * 4), -g.getX(q * 4)) * 180) / Math.PI;
    return Math.round(a * 1e6) / 1e6;
  };
  check('F1a the three planes stand at 0, 55 and 118 degrees',
    [cardDeg(gp, 0), cardDeg(gp, 1), cardDeg(gp, 2)], [0, 55, 118], 1e-4);
  check('F1a …so the gaps are UNEVEN — 55, 63, 62 and not three times 60',
    [cardDeg(gp, 1) - cardDeg(gp, 0), cardDeg(gp, 2) - cardDeg(gp, 1),
      180 - cardDeg(gp, 2)], [55, 63, 62], 1e-4);
  const gn = geo.getAttribute('normal');
  const upNormals = [];
  for (let i = 0; i < gn.count; i += 1) {
    upNormals.push([gn.getX(i), gn.getY(i), gn.getZ(i)]);
  }

  const idx = geo.getIndex();

  const tri = (n) => [idx.getX(n * 3), idx.getX(n * 3 + 1), idx.getX(n * 3 + 2)];
  const rev = (t) => [t[0], t[2], t[1]];
  check('F1c …the second eighteen being the first six triangles reversed',
    [tri(6), tri(7), tri(8), tri(9), tri(10), tri(11)],
    [rev(tri(0)), rev(tri(1)), rev(tri(2)), rev(tri(3)), rev(tri(4)),
      rev(tri(5))]);

  // (F1a) the red counter-check — the fully symmetric star
  const evenStar = await loadField(symmetricStar);
  const evenGeo = evenStar.undergrowthGeometry(UNDERGROWTH_H_REF_M);
  const evenPos = evenGeo.getAttribute('position');
  check('F1a the "0/60/120" mutant repeats every third of a turn',
    [cardDeg(evenPos, 0), cardDeg(evenPos, 1), cardDeg(evenPos, 2)],
    [0, 60, 120], 1e-4);
  check('F1a …and its third card starts 0.0063 m further out in x',
    evenPos.getX(8) - gp.getX(8), 0.103125 - 0.0968285, 1e-6);
  checkNot('F1a …neither of which the real star does',
    [cardDeg(gp, 0), cardDeg(gp, 1), cardDeg(gp, 2)], [0, 60, 120], 1e-4);

  const dataTex = undergrowthTexture();
  check('F the one shared texture is a 64 x 64 DataTexture',
    [dataTex.image.width, dataTex.image.height], [64, 64]);
  const mat = undergrowthMaterial(dataTex, '#6a994e', 0.06, applySway);
  check('F2 the material CUTS its alpha at 0.35',
    [mat.alphaTest, UNDERGROWTH_ALPHA_TEST], [0.35, 0.35]);
  check('F2 …and is NOT transparent — it stays in the opaque pass',
    mat.transparent, false);
  check('F2 …and it never draws a BACK face, so no normal is ever flipped',
    mat.side, THREE.FrontSide);
  check('F2 …through the blade texture', mat.map === dataTex, true);
  // 0.75 of albedo times the 1.26 of headroom the texture gave up for its
  // blade ramp — one number, and the second half of it is bookkeeping: the
  // texture's mean brightness fell by the same 1.26.
  const want = new THREE.Color('#6a994e').multiplyScalar(0.945);
  check('F3 the tint is the kind\'s colour times 0.75 · 1.26',
    [mat.color.r, mat.color.g, mat.color.b], [want.r, want.g, want.b], 1e-9);
  checkNot('F3 …and NOT the bare 0.75, which would darken the layer by a fifth',
    [mat.color.r, mat.color.g, mat.color.b],
    (() => { const c = new THREE.Color('#6a994e').multiplyScalar(0.75);
      return [c.r, c.g, c.b]; })(), 1e-9);
  check('F4 wind and camera corridor are BOTH on it, in that order',
    mat.customProgramCacheKey(), 'ground-sway@0.06+occlusion-corridor');

  // (F5) the red counter-check
  const cut = await loadField(noAlphaTest);
  const cutMat = cut.undergrowthMaterial(cut.undergrowthTexture(), '#6a994e',
                                         0.06, cut.applySway);
  check('F5 the "no alpha cut" mutant draws every texel of all three quads',
    cutMat.alphaTest, 0);
  checkNot('F5 …which the real material does not', mat.alphaTest, 0);

  console.log('\n(F6) the shade of one tuft — instanceColor, and no drift');
  check('F6a the dry end is 1.24 / 0.90 / 0.95 of the kind\'s colour',
    [...UNDERGROWTH_TINT_A], [1.24, 0.90, 0.95], 1e-12);
  check('F6a …and the fresh end 0.76 / 1.10 / 1.05',
    [...UNDERGROWTH_TINT_B], [0.76, 1.10, 1.05], 1e-12);
  // The swing is on RED AGAINST GREEN and not on brightness — the axis the
  // round before got wrong. Split each end into its luma and the colour that
  // is left over, and assert both halves side by side against the old pair, so
  // a spread that merely got wider could not pass for one that got re-aimed.
  const luma = (t) => 0.2126 * t[0] + 0.7152 * t[1] + 0.0722 * t[2];
  const chromaR = (t) => t[0] / luma(t);
  check('F6a …and only 2.4 % of it is brightness, where the old end had 12.8 %',
    [luma(UNDERGROWTH_TINT_A), luma([0.82, 0.88, 0.94])], [0.9759, 0.8716],
    5e-4);
  check('F6a …while the COLOUR on red is 27.1 % against the old 5.9 % — four '
    + 'and a half times as far',
    [chromaR(UNDERGROWTH_TINT_A), chromaR([0.82, 0.88, 0.94])],
    [1.2706, 0.9408], 5e-4);
  check('F6a …so the two of them sum to exactly (2, 2, 2)',
    [UNDERGROWTH_TINT_A[0] + UNDERGROWTH_TINT_B[0],
      UNDERGROWTH_TINT_A[1] + UNDERGROWTH_TINT_B[1],
      UNDERGROWTH_TINT_A[2] + UNDERGROWTH_TINT_B[2]], [2, 2, 2], 1e-12);

  for (const [bad, name] of [[NaN, 'NaN'], ['x', 'a string'],
    [undefined, 'undefined']]) {
    check(`F6b a shade of ${name} is the middle, never a NaN colour`,
      undergrowthTint(bad), [1, 1, 1], 1e-12);
  }

  // (F6c) no drift — measured over a grid of a thousand standing places
  const meanTint = (tintOf, shadeOf) => {
    const sum = [0, 0, 0];
    for (let i = 0; i < 1000; i += 1) {
      const t = tintOf(shadeOf((i % 40) - 20, Math.floor(i / 40) - 12));
      sum[0] += t[0]; sum[1] += t[1]; sum[2] += t[2];
    }
    return sum.map((v) => v / 1000);
  };
  const tintMean = meanTint(undergrowthTint, undergrowthShade);
  check(`F6c the mean tint over 1000 tufts is the kind's own colour within `
    + `2 % (got ${tintMean.map((v) => v.toFixed(4)).join(', ')})`,
    tintMean.every((v) => Math.abs(v - 1) <= 0.02), true);
  const oneSided = await loadField(oneSidedTint);
  const driftMean = meanTint(oneSided.undergrowthTint, oneSided.undergrowthShade);
  check('F6c the "one-sided mix" mutant drifts to the dry end of the palette',
    driftMean, [1.12, 0.95, 0.975], 0.02);
  check('F6c …i.e. measurably outside the band the real mix holds',
    Math.abs(driftMean[0] - 1) > 0.04, true);

  // (F6d) the position hash is not the LOD's index hash
  const survivors = [];
  for (let i = 0; i < 2000; i += 1) if (undergrowthVisible(i, 45)) survivors.push(i);
  const meanOf = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
  const byIndex = meanOf(survivors.map((i) => instanceHash(i)));
  const byPos = meanOf(survivors.map((i) => undergrowthShade((i % 50) * 1.3,
                                                             Math.floor(i / 50) * 1.3)));
  check(`F6d an index-keyed shade would lose its bright half at 45 m `
    + `(mean ${byIndex.toFixed(3)})`, Math.abs(byIndex - 0.25) <= 0.02, true);
  check(`F6d …while the POSITION-keyed one keeps the whole palette `
    + `(mean ${byPos.toFixed(3)})`, Math.abs(byPos - 0.5) <= 0.05, true);
  // …and the palette is really used from end to end, not clustered in the
  // middle: over a thousand places both ends are reached to within 1 %.
  let lowest = 1;
  let highest = 0;
  for (let i = 0; i < 1000; i += 1) {
    const h = undergrowthShade((i % 40) * 0.7 - 14, Math.floor(i / 40) * 0.7 - 8);
    if (h < lowest) lowest = h;
    if (h > highest) highest = h;
  }
  check(`F6d the whole palette is in use, both ends included `
    + `(${lowest.toFixed(3)} … ${highest.toFixed(3)})`,
    [lowest < 0.01, highest > 0.99], [true, true]);
  checkNot('F6d …while the tuft a metre away has its own shade',
    undergrowthShade(12.5, -7.25), undergrowthShade(13.5, -7.25));
  check('F6d a junk position is the middle of the palette, not a NaN',
    [undergrowthShade(NaN, 0), undergrowthShade(0, Infinity)], [0.5, 0.5]);

  console.log('\n(G) the field, end to end');
  const BIG = 2000;
  const area = {
    id: 'ta_wood',
    kind: 'forest',
    layer: 1,
    ring: [[-BIG, -BIG], [BIG, -BIG], [BIG, BIG], [-BIG, BIG]],
    bounds: [-BIG, -BIG, BIG, BIG],
    value: 0.6,
    color: '#6a994e',
    swayM: 0.06,
  };
  const grown3d = createUndergrowthField({ heightAt: () => 0, applySway, topLayerAt: () => 1 });
  grown3d.setAreas([area], []);
  check('G1 nothing is built before there is an anchor',
    grown3d.group.children.length, 0);
  grown3d.setAnchor(32, 32);
  check('G2 the anchor builds one mesh per wanted cell',
    grown3d.group.children.length, midCell.length);
  check('G2 …each with room for the cell\'s own 1966 tufts',
    grown3d.group.children.map((m) => m.instanceMatrix.count),
    midCell.map(() => 1966));
  check('G3 and nothing is DRAWN until the first tick',
    grown3d.group.children.some((m) => m.visible || m.count > 0), false);
  check('G3 …nor does any of it cast a shadow',
    grown3d.group.children.every((m) => m.castShadow === false), true);

  const cam = new THREE.Vector3(32, 0, 32);
  grown3d.tick(cam);
  let drawn = 0;
  let farthest = 0;
  const m4 = new THREE.Matrix4();
  const at3 = new THREE.Vector3();
  for (const mesh of grown3d.group.children) {
    drawn += mesh.count;
    for (let i = 0; i < mesh.count; i += 1) {
      m4.fromArray(mesh.instanceMatrix.array, i * 16);
      at3.setFromMatrixPosition(m4);
      const d = at3.distanceTo(cam);
      if (d > farthest) farthest = d;
    }
  }
  check('G4 the tick draws the 3167 tufts the thinning integral asks for',
    Math.abs(drawn - 3167) <= 0.08 * 3167, true);
  check(`G4 …and not one of them past the cull distance (${farthest.toFixed(1)} m)`,
    farthest <= UNDERGROWTH_CULL_M, true);

  // (F6e) the shade travels with the matrix — measured at the CONSUMER, i.e.
  // in the two buffers three actually uploads.
  const shadeMismatch = (mod, group) => {
    let slots = 0;
    let wrong = 0;
    const mm = new THREE.Matrix4();
    const pt = new THREE.Vector3();
    for (const mesh of group.children) {
      if (!mesh.instanceColor) return { slots: 0, wrong: -1 };
      for (let i = 0; i < mesh.count; i += 1) {
        mm.fromArray(mesh.instanceMatrix.array, i * 16);
        pt.setFromMatrixPosition(mm);
        const want = mod.undergrowthTint(mod.undergrowthShade(pt.x, pt.z));
        slots += 1;
        for (let k = 0; k < 3; k += 1) {
          if (Math.abs(mesh.instanceColor.array[i * 3 + k] - want[k]) > 1e-6) {
            wrong += 1;
            break;
          }
        }
      }
    }
    return { slots, wrong };
  };
  const shades = shadeMismatch(field, grown3d.group);
  check(`G4b every drawn slot wears the shade of the tuft standing there `
    + `(${shades.slots} slots)`, [shades.slots > 3000, shades.wrong], [true, 0]);
  // …and the red counter-check: the colour half of the compaction removed.
  const looseColor = await loadField(noColorCompaction);
  const loose3d = looseColor.createUndergrowthField({
    heightAt: () => 0, applySway: looseColor.applySway, topLayerAt: () => 1,
  });
  loose3d.setAreas([area], []);
  loose3d.setAnchor(32, 32);
  loose3d.tick(cam);
  const loose = shadeMismatch(looseColor, loose3d.group);
  check('G4b the "colours stay in index order" mutant misplaces hundreds of '
    + `them (${loose.wrong} of ${loose.slots})`, loose.wrong > 300, true);
  loose3d.dispose();

  const before = grown3d.group.children.slice();
  grown3d.setAnchor(63, 32);
  const nudgedMeshes = grown3d.group.children.slice();
  check('G5 a step inside the cell exchanges the two cells of (A3b)…',
    [nudgedMeshes.length,
      before.filter((m) => !nudgedMeshes.includes(m)).length],
    [21, 2]);
  check('G5 …and leaves the other nineteen as the very same meshes',
    before.filter((m) => nudgedMeshes.includes(m)).length, 19);
  grown3d.setAnchor(96, 32);
  check('G5 a border crossing moves the window, and it stays 21 cells',
    grown3d.group.children.length, eastCell.length);
  check('G5 …five of the meshes standing at the cell centre really went',
    before.filter((m) => !grown3d.group.children.includes(m)).length, 5);
  grown3d.dispose();
  check('G6 dispose empties the group', grown3d.group.children.length, 0);

  // (G7) the border, and the re-roll that must not happen there
  const path = {
    id: 'ta_path',
    kind: 'path',
    layer: 1,
    ring: [[0, -BIG], [BIG, -BIG], [BIG, BIG], [0, BIG]],
    bounds: [0, -BIG, BIG, BIG],
    value: 0,
    color: '#a0a0a0',
    swayM: 0,
  };
  const halved = createUndergrowthField({ heightAt: () => 0, applySway, topLayerAt: () => 1 });
  halved.setAreas([area, path], []);
  halved.setAnchor(-32, 32);
  // The anchor's own cell (-1, 0) runs x −64 … 0, so it lies wholly west of
  // the path and keeps everything — and it is built FIRST, the want set being
  // nearest-first.
  check('G7 a cell wholly west of the border still carries its 1966',
    halved.group.children[0].instanceMatrix.count, 1966);
  // The want set at (−32, 32) is (A1) shifted one column west, so the columns
  // east of the border (cx = 0 and 1) grow nothing at all: 21 cells less
  // cx = 0 (five rows) and cx = 1 (three, being a |cx| = 2 column) -> 13.
  check('G7 …and the thirteen cells west of it are the only ones with a layer',
    halved.group.children.length, 13);
  const straddling = scatterInstances({
    ring: cellRing(-1, 0),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed: undergrowthCellSeed('ta_wood', -1, 0),
    occluders: [[[-32, -BIG], [BIG, -BIG], [BIG, BIG], [-32, BIG]]],
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
    triesPerPoint: 1,
  });
  check('G7 half the cell covered keeps about half the tufts, not all of them',
    Math.abs(straddling.length - 983) <= 0.1 * 983, true);
  const topped = scatterInstances({
    ring: cellRing(-1, 0),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed: undergrowthCellSeed('ta_wood', -1, 0),
    occluders: [[[-32, -BIG], [BIG, -BIG], [BIG, BIG], [-32, BIG]]],
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
  });
  check('G7 …while the sampler\'s DEFAULT re-roll tops it back up to 1966 — '
    + 'double density against the border', topped.length, 1966);
  halved.dispose();

  // (G8) the footprint pre-filter, measured on a counting footprint
  const counting = (pts) => {
    const fp = { reads: 0 };
    // `footprintBox` (once per `setAreas`) and `pointInFootprint` (per
    // candidate) each read `points` EXACTLY once into a local before doing
    // anything else, so this counter is "how often was this outline walked".
    Object.defineProperty(fp, 'points', {
      get() { fp.reads += 1; return pts; },
      enumerable: true,
    });
    return fp;
  };
  const far = counting([[4995, 4995], [5005, 4995], [5005, 5005], [4995, 5005]]);
  const withFar = createUndergrowthField({ heightAt: () => 0, applySway, topLayerAt: () => 1 });
  withFar.setAreas([area], [far]);
  withFar.setAnchor(32, 32);
  check('G8 a place on the other side of the world is walked ONCE, when it is '
    + 'handed over — never again per cell and never per candidate',
    far.reads, 1);
  check('G8 …and it changes no tuft: the anchor cell still carries its 1966',
    withFar.group.children[0].instanceMatrix.count, 1966);
  withFar.dispose();
  // 22 … 42 on both axes: inside the anchor's own cell 0 … 64 and inside no
  // other, so exactly one cell asks it per candidate.
  const near = counting([[22, 22], [42, 22], [42, 42], [22, 42]]);
  const withNear = createUndergrowthField({ heightAt: () => 0, applySway, topLayerAt: () => 1 });
  withNear.setAreas([area], [near]);
  withNear.setAnchor(32, 32);
  check('G8 …while a place INSIDE the anchor cell — and inside no other — is '
    + 'asked once per candidate on top of that',
    near.reads, 1 + 1966);
  withNear.dispose();

  console.log('\n(H) the wiring, pinned by reading the source');
  const ugSrc = await readFile(UG_SRC, 'utf8');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  check('H the layer samples every cell under its own (area, cell) seed',
    ugSrc.includes('seed: undergrowthCellSeed(area.id, cx, cz),'), true);
  check('H …and hands the sampler its own per-cell ceiling',
    ugSrc.includes('maxPoints: UNDERGROWTH_MAX_PER_CELL,'), true);
  check('H the cell subtracts its rejections instead of re-rolling them',
    ugSrc.includes('triesPerPoint: 1,'), true);
  check('H the footprints are cut to the cell by their OWN bounding box',
    /\.filter\(\(f\) => meetsCell\(f\.bounds\)\)\.map\(\(f\) => f\.fp\)/.test(ugSrc),
    true);
  check('H …and that box is cut once per handover, not once per cell',
    ugSrc.includes('footprints = fps.map((fp) => ({ fp, bounds: footprintBox(fp) }));'),
    true);
  check('H …and it is the cut list the sampler gets',
    ugSrc.includes('footprints: nearFootprints,'), true);
  // The headroom is the one invariant that spans two constants: the texture
  // divides its grey by `BLADE_TINT_MAX` and the material multiplies it back.
  // Drop either half and the layer changes brightness by a fifth, which no
  // single-value check would notice — so both halves are pinned together.
  check('H the texture divides its grey by the tint headroom…',
    ugSrc.includes('BLADE_SHADE_SPAN * (py / n)) / BLADE_TINT_MAX'), true);
  check('H …and the material hands exactly that factor back',
    /multiplyScalar\(UNDERGROWTH_ALBEDO\s*\*\s*BLADE_TINT_MAX\)/.test(ugSrc),
    true);
  check('H the shade is written at build and compacted at every binning',
    ugSrc.includes('mesh.setColorAt(i, tint.setRGB(tr, tg, tb));')
      && ugSrc.includes('if (colBuf) copyColor(layer.srcColor, i, colBuf, n);'),
    true);
  check('H the chain is wind first, camera corridor after it',
    /applySway\(mat, swayM, UNDERGROWTH_H_REF_M\);\s*applyOcclusionFade\(mat\);/
      .test(ugSrc), true);
  check('H ground.ts no longer builds the layer itself',
    /buildUndergrowth|UNDERGROWTH_MAX_PER_AREA/.test(groundSrc), false);
  check('H …it hands over the shapes on every rebuild',
    groundSrc.includes('undergrowth.setAreas(undergrowthAreas, footprints);'),
    true);
  check('H …the height tiles\' own anchor',
    groundSrc.includes('undergrowth.setAnchor(x, z);'), true);
  check('H …and the LOD beat',
    groundSrc.includes('undergrowth.tick(cameraPos);'), true);
  // The authored tuft cones are untouched by this round, and the one place
  // that still patches a material of its own in ground.ts is theirs.
  const fadeCalls = groundSrc.match(/applyOcclusionFade\(mat\);/g);
  check('H the authored tuft keeps its own patched material, and only it',
    fadeCalls ? fadeCalls.length : 0, 1);
  // The authored rows keep a seed namespace of their own — since 2026-08-19
  // that is `scatterCellSeed` (they are sampled per 64 m cell too now, see
  // `smoke_scatter_math.mjs` section K), and it is still ONE call: two seed
  // families in one builder would be two answers to "what grows here".
  const seedCalls = groundSrc.match(/scatterCellSeed\(/g);
  check('H …and one cell-seed call, for the authored rows',
    seedCalls ? seedCalls.length : 0, 1);
  check('H …which is NOT the undergrowth\'s namespace',
    groundSrc.includes('undergrowthCellSeed('), false);

  // =========================================================================
  // [J] THE LAYER GATE — the mask decides, not the polygon (E3, decision 5.2)
  // =========================================================================
  // A tuft grows only where the TOPMOST ground at its own point really is the
  // kind that owns it, read off the very masks the picture is composited from
  // (`@anima/scene-render` `topLayerAt`, handed in as `topLayerAt`). The ring
  // and the occluders are the cheap first pass; this is the truth behind them.
  //
  // THE FIXTURE, derived by hand: one wood covering everything (layer 1), and a
  // gate that answers layer 2 — somebody else's ground — for every point with
  // x >= 0. The wood's ring still contains those points, so the ring filter
  // keeps them; only the gate can take them out.
  //
  // The anchor's own cell (0, 0) runs x 0…64, i.e. WHOLLY inside the half the
  // gate hands to layer 2, so that cell must come out with nothing at all —
  // and `buildCell` drops a layer with no kept points, so the mesh does not
  // exist rather than existing empty.
  console.log('\n[J] the layer gate');
  const gated = createUndergrowthField({
    heightAt: () => 0,
    applySway,
    topLayerAt: (x) => (x >= 0 ? 2 : 1),
  });
  gated.setAreas([area], []);
  gated.setAnchor(-32, 32);
  const gatedCells = gated.group.children.length;
  // West of the border the gate says 1 and the wood keeps its full cell — the
  // same 1966 tufts the ungated build produced for a cell of this density.
  check('J1 a cell west of the gate keeps its own 1966 tufts',
    gated.group.children[0].instanceMatrix.count, 1966);
  // …and the want set is the SAME 21 cells as always: what the gate removes is
  // the eight columns east of x = 0, which is exactly the thirteen of G7.
  check('J2 the gate leaves the same thirteen cells the polygon rule leaves',
    gatedCells, 13);
  gated.dispose();

  // The RED counter-probe: a gate that says "this is somebody else's ground"
  // everywhere must grow NOTHING, however full the ring is. Without the gate
  // the same fixture builds 21 cells.
  const blocked = createUndergrowthField({
    heightAt: () => 0, applySway, topLayerAt: () => 7,
  });
  blocked.setAreas([area], []);
  blocked.setAnchor(32, 32);
  check('J3 a gate that never matches grows nothing at all',
    blocked.group.children.length, 0);
  blocked.dispose();
  const open = createUndergrowthField({
    heightAt: () => 0, applySway, topLayerAt: () => 1,
  });
  open.setAreas([area], []);
  open.setAnchor(32, 32);
  check('J3 …while the identical fixture with a matching gate grows 21 cells',
    open.group.children.length, 21);
  open.dispose();

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
