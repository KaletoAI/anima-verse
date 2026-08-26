#!/usr/bin/env node
/**
 * Smoke check for THE FLOW A WATER PIXEL REALLY DRIFTS AT — the fragment tap
 * that replaced the per-vertex varying (Task 7, 2026-08-27).
 *
 * Usage:  node client3d/scripts/smoke_flow_lod.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots).
 *
 * ============================================================================
 * WHY THIS FILE EXISTS
 * ============================================================================
 * The user walked from the inn to the river and the water stood still, while
 * the debug readout at the same spot said `flow -1.6723,1.0902 |1.9963|
 * sp 0.998 m/s` — a healthy current. Both were true. The readout taps the flow
 * FIELD at a point; the shader used to tap it once per VERTEX
 * (`terrainLod.tlodFlowAt` -> the varying `vTlodFlow`) and let the rasterizer
 * interpolate. The vertices of a terrain piece are `baseStep · 2^level` metres
 * apart — 2 m at level 0, 16 m at level 3, 64 m at level 5 — and the flow
 * raster is written only inside the water plus the bake's 4 m dilation. A
 * narrow river therefore fits BETWEEN two vertices, all four corners of the
 * cell read (0, 0), the varying is exactly (0, 0), and `twRipple` takes its
 * STILL branch: a river drawn as standing water.
 *
 * The tap now lives in the fragment (`waterShade.waterFlowGlsl`, `twFlowAt`),
 * whose TS twin is `terrainLod.gpuWaterFlowAt`. This file pins the two halves
 * of that: the RETIRED path really does collapse (the RED baseline), and the
 * shipped one cannot, because the level does not enter it at all.
 *
 * ============================================================================
 * THE FIXTURE, and every number that follows from it
 * ============================================================================
 * A flow field as `terrainLod.buildFlow` produces one: the water pyramid's base
 * lattice, `step` 2 m, origin (−64, −64), 129 × 97 support points (the window
 * of two 64 m tiles plus the near margin, i.e. x = −64 … 192, z = −64 … 128).
 *
 * A straight river runs north along x = 96, SIX METRES wide (bed |x − 96| ≤ 3,
 * i.e. 93 … 99). The server writes the flow over the bed GROWN by
 * `WATER_RASTER_DILATION_M` = 4 m, so the written band is 89 … 103; on the 2 m
 * lattice (whose columns are the even metres) the written COLUMNS are therefore
 *
 *     x = 90, 92, 94, 96, 98, 100, 102        — seven columns, all (0, 2)
 *
 * and every other column is (0, 0). The vector is (0, 2): tangent (0, 1) north
 * times an area speed factor of 2, so `|flow|` is 2 and no component is an axis
 * accident of the other.
 *
 * ── (1) THE FIELD ITSELF, read as the fragment reads it ─────────────────────
 * `gpuWaterFlowAt` is a plain bilinear over the lattice, so on this field it is
 * a 1-D linear ramp in x, constant in z:
 *
 *     x = 96  (a written column, mid-river)        -> (0, 2)      |flow| 2
 *     x = 93  (between 92 and 94, both written)    -> (0, 2)      |flow| 2
 *     x = 99  (between 98 and 100, both written)   -> (0, 2)      |flow| 2
 *     x = 103 (between 102 written and 104 dry)    -> (0, 1)      |flow| 1
 *     x = 104 (a dry column)                       -> (0, 0)      |flow| 0
 *     x = 89  (between 88 dry and 90 written)      -> (0, 1)      |flow| 1
 *
 * So the field's support is the OPEN interval (88, 104) — 16 m wide — and it
 * carries the full 2 everywhere on [90, 102].
 *
 * ── (2) WHEN THE RETIRED VARYING DIES ───────────────────────────────────────
 * A vertex sample is a point tap at a vertex column; the varying at a pixel is
 * a convex blend of the two columns bracketing it (the field is constant in z,
 * so the triangulation drops out and the blend is the 1-D interpolation). A
 * convex blend of two vectors that both point north is (0, 0) IF AND ONLY IF
 * both are (0, 0), i.e. both bracketing columns lie outside (88, 104).
 *
 * With a vertex pitch p and a lattice anchored at `a`, the bracketing columns
 * are g and g + p with g ≤ x < g + p. Both outside needs
 *
 *     g ≤ 88   AND   g + p ≥ 104   =>   p ≥ 104 − 88 = 16.
 *
 * Hence, for every pixel inside the river:
 *
 *     level 0 (p =  2) -> impossible, the varying is never still
 *     level 1 (p =  4) -> impossible
 *     level 2 (p =  8) -> impossible  (8 < 16)
 *     level 3 (p = 16) -> possible for EXACTLY ONE alignment: g = 88, i.e.
 *                         a ≡ 88 (mod 16) = 8. Columns 88 and 104, both dry.
 *     level 4 (p = 32) -> possible whenever 72 ≤ g ≤ 88
 *     level 5 (p = 64) -> possible whenever 40 ≤ g ≤ 88, e.g. a = 40:
 *                         columns 40 and 104, both dry.
 *
 * Swept over every alignment (a = 0, 2, … p − 2) and every written column of
 * the river (x = 90 … 102, seven probes) the STILL counts are
 *
 *     level 0:   0 / 7      level 3:   7 / 56     (1 alignment × 7 probes)
 *     level 1:   0 / 14     level 4:  63 / 112    (9 of 16 alignments)
 *     level 2:   0 / 28     level 5: 175 / 224    (25 of 32 alignments)
 *
 * The level-3 and level-5 counts are derived above; the level-4 count follows
 * from the same inequality (a = 0 … 30 even; g = the multiple of 32 plus a that
 * brackets the probe) and is asserted as ">= 1 alignment" rather than as its
 * exact 63, so the check states the FAILURE and not an arithmetic accident.
 *
 * ── (3) WHAT THE FIX BUYS ───────────────────────────────────────────────────
 * `gpuWaterFlowAt(field, x, z)` has no level argument, so the shipped answer at
 * a pixel is the same number at every level — and inside the painted river it is
 * the full (0, 2). That is the whole statement, and it is why the LOD ring fit,
 * the F1 cap relaxation and the camera zoom can no longer turn a river into a
 * lake.
 *
 * ── (4) THE WINDOW IS A TEST AND NOT A CLAMP ────────────────────────────────
 * Outside the field the tap answers (0, 0) rather than the nearest edge texel —
 * the sd sampler's rule (`twSdAt`), for its reason: a clamped edge would drag
 * one water's current along the whole rim of the near window.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

/**
 * A THREE.js stand-in — `terrainLod.ts` allocates exactly two kinds of three
 * object while it LOADS (the neutral data textures and the level uniform
 * array), and this check touches nothing that draws. Anything the module
 * started using beyond these would fail here loudly, which is the alarm the
 * arrangement exists for. Same stub as `smoke_terrain_lod.mjs`.
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
export const RGFormat = 1030;
export const RGBAFormat = 1023;
export const FloatType = 1015;
export const NearestFilter = 1003;
export const ClampToEdgeWrapping = 1001;
`;

/** Transpile `terrainLod.ts` and its pure siblings and import them, with
 *  `three` and `@anima/scene-render` resolved to local files. */
async function loadLod() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'flowlod-'));
  try {
    const ts = async (src, name) => {
      const code = await readFile(src, 'utf8');
      await writeFile(join(dir, `${name}.mjs`),
        esbuild.transformSync(code, { loader: 'ts', format: 'esm' }).code
          .replace(/from\s*["']@anima\/scene-render["']/g, "from './sceneRender.mjs'")
          .replace(/from\s*["']\.\/([A-Za-z]+)["']/g, "from './$1.mjs'")
          .replace(/from\s*["']three["']/g, "from './three.mjs'"),
        'utf8');
    };
    await writeFile(join(dir, 'three.mjs'), THREE_STUB, 'utf8');
    await writeFile(join(dir, 'sceneRender.mjs'),
      "export * from './worldHeight.mjs';\nexport * from './materials.mjs';\n", 'utf8');
    await ts(join(ROOT, 'packages/scene-render/src/worldHeight.ts'), 'worldHeight');
    await ts(join(ROOT, 'packages/scene-render/src/materials.ts'), 'materials');
    await ts(join(ROOT, 'client3d/src/scene/waterRaster.ts'), 'waterRaster');
    await ts(join(ROOT, 'client3d/src/scene/waterPlaneMath.ts'), 'waterPlaneMath');
    await ts(join(ROOT, 'client3d/src/scene/waterShade.ts'), 'waterShade');
    await ts(join(ROOT, 'client3d/src/scene/terrainLod.ts'), 'terrainLod');
    return import(`file://${join(dir, 'terrainLod.mjs')}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
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
function checkEq(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${JSON.stringify(actual)}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

const { gpuWaterFlowAt } = await loadLod();

// ── THE FIXTURE ─────────────────────────────────────────────────────────────
const STEP = 2;
const COLS = 129;
const ROWS = 97;
const OX = -64;
const OZ = -64;
/** The river: 6 m of water at x = 96, the bake's 4 m dilation on each bank. */
const RIVER_X = 96;
const HALF_W = 3;
const DILATION = 4;
const WET_LO = RIVER_X - HALF_W - DILATION;   //  89
const WET_HI = RIVER_X + HALF_W + DILATION;   // 103
/** The area's speed factor rides in the vector's LENGTH. */
const FLOW = 2;

const data = new Float32Array(COLS * ROWS * 2);
for (let j = 0; j < ROWS; j += 1) {
  for (let i = 0; i < COLS; i += 1) {
    const x = OX + i * STEP;
    const at = (j * COLS + i) * 2;
    data[at] = 0;
    data[at + 1] = x >= WET_LO && x <= WET_HI ? FLOW : 0;
  }
}
const FIELD = { originX: OX, originZ: OZ, step: STEP, cols: COLS, rows: ROWS, data };
const Z = 32;
const len = (v) => Math.hypot(v[0], v[1]);
/** The tap the FRAGMENT makes — the shipped path (`waterShade.twFlowAt`). */
const tap = (x) => gpuWaterFlowAt(FIELD, x, Z);
/**
 * The RETIRED per-vertex path: the two vertex columns of pitch `p` (anchored at
 * `a`) bracketing x, blended. The field is constant in z, so this IS what the
 * rasterizer delivered for the varying `vTlodFlow`.
 */
function varying(x, p, a) {
  const g = a + Math.floor((x - a) / p) * p;
  const t = (x - g) / p;
  const lo = tap(g);
  const hi = tap(g + p);
  return [lo[0] * (1 - t) + hi[0] * t, lo[1] * (1 - t) + hi[1] * t];
}
/** The shader's own branch (`bool still = len < 1e-4;`). */
const STILL = 1e-4;
/** The written columns of the river — the seven probes of the sweep. */
const PROBES = [90, 92, 94, 96, 98, 100, 102];

// ============================================================================
console.log('\n[1] the field, read as the fragment reads it');
// ============================================================================
checkEq('mid-river carries the full vector', tap(96), [0, 2]);
checkEq('…and so does every point between two written columns', tap(93), [0, 2]);
checkEq('…on the far bank of the bed too', tap(99), [0, 2]);
checkEq('the outer edge of the dilation ring is half way down', tap(103), [0, 1]);
checkEq('…and its mirror image on the near bank', tap(89), [0, 1]);
checkEq('a dry column is (0, 0) exactly', tap(104), [0, 0]);
checkEq('…and so is the far side of the world', tap(160), [0, 0]);
check('the support is 16 m wide: (88, 104)', 104 - 88, 16);

// ============================================================================
console.log('\n[2] RED — the retired per-vertex varying, and where it dies');
// ============================================================================
// A convex blend of two north-pointing vectors is (0, 0) only if BOTH are, so
// the varying dies exactly when a cell of pitch p straddles the whole 16 m
// support: p >= 16.
for (const level of [0, 1, 2]) {
  const p = STEP * 2 ** level;
  let still = 0;
  let tot = 0;
  let worst = Infinity;
  for (let a = 0; a < p; a += STEP) {
    for (const x of PROBES) {
      const v = len(varying(x, p, a));
      tot += 1;
      if (v < STILL) still += 1;
      if (v < worst) worst = v;
    }
  }
  check(`level ${level} (${p} m/vertex): still in n of ${tot} alignments`, still, 0);
  check(`…and its worst reading is a real current`, worst, level === 0 ? 2
    : level === 1 ? 1 : 0.5);
}
// level 3: the ONE alignment that puts vertices on 88 and 104, both dry.
// g = 8 + floor((96 − 8) / 16) · 16 = 8 + 5 · 16 = 88, so the cell is [88, 104]
// — the two columns that bracket the whole 16 m support without touching it.
const g3 = 8 + Math.floor((96 - 8) / 16) * 16;
checkEq('level 3 (16 m/vertex), anchor 8: the columns are 88 and 104',
  [g3, g3 + 16], [88, 104]);
checkEq('…and both of them are dry', [tap(g3), tap(g3 + 16)], [[0, 0], [0, 0]]);
check('RED: …so mid-river the varying is EXACTLY still',
  len(varying(96, 16, 8)), 0);
check('RED: …and so is every other point of the river',
  PROBES.map((x) => len(varying(x, 16, 8))).reduce((a, b) => a + b, 0), 0);
// level 5: a 64 m cell from 40 to 104 swallows the river whole.
check('RED: level 5 (64 m/vertex), anchor 40: still mid-river',
  len(varying(96, 64, 40)), 0);
// The sweep counts of the docstring — stated as "it can happen", which is the
// failure, rather than as an exact count that would pin an alignment accident.
for (const level of [3, 4, 5]) {
  const p = STEP * 2 ** level;
  let still = 0;
  let tot = 0;
  for (let a = 0; a < p; a += STEP) {
    for (const x of PROBES) {
      tot += 1;
      if (len(varying(x, p, a)) < STILL) still += 1;
    }
  }
  const ok = still > 0;
  if (ok) {
    passed += 1;
    console.log(`  ok   RED: level ${level} (${p} m/vertex) draws a still river `
      + `in ${still} of ${tot} alignment/probe pairs`);
  } else {
    failed += 1;
    console.log(`  FAIL RED: level ${level} was expected to be able to go still`);
  }
}
check('level 3 goes still in exactly the one alignment derived by hand',
  (() => {
    let n = 0;
    for (let a = 0; a < 16; a += STEP) {
      if (PROBES.every((x) => len(varying(x, 16, a)) < STILL)) n += 1;
    }
    return n;
  })(), 1);

// ============================================================================
console.log('\n[3] THE FIX — the fragment tap does not know what a level is');
// ============================================================================
// Every pixel of the painted river reads the full current, and reads the SAME
// current whatever the piece under it is drawn at: the level is not an argument
// of `gpuWaterFlowAt` / `twFlowAt` at all, which is the whole point.
for (const x of PROBES) {
  check(`the fragment tap at x = ${x} is the full current`, len(tap(x)), FLOW);
}
checkEq('…and it is the same vector at every level 0…5',
  [0, 1, 2, 3, 4, 5].map(() => tap(96)),
  [[0, 2], [0, 2], [0, 2], [0, 2], [0, 2], [0, 2]]);
// The bed itself — the water a player sees — never drops below the full factor.
check('nothing inside the 6 m bed is below the full factor',
  Math.min(...[93, 94, 95, 96, 97, 98, 99].map((x) => len(tap(x)))), FLOW);
check('…and nothing anywhere in the river is anywhere near still',
  Math.min(...PROBES.map((x) => len(tap(x)))) / STILL >= 1000 ? 1 : 0, 1);

// ============================================================================
console.log('\n[4] the window is a test, not a clamp');
// ============================================================================
checkEq('one step past the western rim', tap(OX - STEP), [0, 0]);
checkEq('…and past the eastern one', tap(OX + (COLS - 1) * STEP + STEP), [0, 0]);
checkEq('…on the rim itself the field still answers', tap(OX), [0, 0]);
checkEq('a null field is still water', gpuWaterFlowAt(null, 96, Z), [0, 0]);
checkEq('…and so is a degenerate one',
  gpuWaterFlowAt({ ...FIELD, cols: 1 }, 96, Z), [0, 0]);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
