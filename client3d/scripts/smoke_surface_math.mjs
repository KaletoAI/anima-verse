#!/usr/bin/env node
/**
 * Smoke check for the baked-surface sampler — packages/scene-render/src/surface.ts.
 * Usage:  node client3d/scripts/smoke_surface_math.mjs
 * Every expected number is derived BY HAND (spec-surface-height § 6.2); the SAME
 * table drives scripts/smoke_model_surface.py part 2 — that equality is the proof
 * that client and server compute one height.
 *
 * S1: step 1, origin [-1,-1], cols 3, rows 3, box_min [-1,0,-1], box_max [1,1,1],
 *     extent_snapped [2,1,2], values (j rows of i):
 *       j=0: [0, 100, 200]   j=1: [0, 100, 200]   j=2: [null, 100, 200]
 *     -> height = 100*(mx+1) cm on the model's x, one null node at (i=0, j=2).
 * P1: anchor [4,-3], yaw_deg 90, bottom_y 0.5, max_m 4, measure 'xz'
 *     s = 4 / max(2,2) = 2;  c = (0, 0.5, 0)
 *     inverse of three's Ry(+90): lx = -qz, lz = qx   (q = world - anchor)
 *     model coords m = l / s + c.xz;  u = m.x + 1,  v = m.z + 1
 *   A  (4,-3)    q=(0,0)      l=(0,0)      m=(0,0)       u=1,    v=1   -> 100 -> 0.5 + 2*1.00 = 2.5
 *   B  (4,-5)    q=(0,-2)     l=(2,0)      m=(1,0)       u=2,    v=1   -> 200 -> 0.5 + 2*2.00 = 4.5
 *   C  (2,-2.5)  q=(-2,0.5)   l=(-0.5,-2)  m=(-0.25,-1)  u=0.75, v=0   ->  75 -> 0.5 + 2*0.75 = 2.0
 *   D  (5,-2)    q=(1,1)      l=(-1,1)     m=(-0.5,0.5)  u=0.5,  v=1.5 -> null neighbour (0,2) -> null
 *   E  (4,-6)    q=(0,-3)     l=(3,0)      m=(1.5,0)     u=2.5 > cols-1        -> null
 * P2: like P1 but measure 'xyz', extent_snapped [2,3,2], max_m 4 -> s = 4/3
 *   F  (4,-3)    as A                                                  -> 100 -> 0.5 + (4/3)*1.00 = 1.8333333
 * P3: like P1 but yaw_deg 0, so l = q
 *   G  (3.5,-5)  q=(-0.5,-2)  l=(-0.5,-2)  m=(-0.25,-1)  u=0.75, v=0   ->  75 -> 0.5 + 2*0.75 = 2.0
 *   H  (4,-3) on S1 with `values` truncated to four entries [0,100,200,0]: A's corner
 *      indices are 4, 5, 7, 8 — all past the end -> no node -> null. A corrupt sidecar
 *      reads as a hole (terrain takes over), in TS as in Python, never as an error.
 * Highest: [S1@P1, S1@P1 with bottom_y 1.0] at A -> max(2.5, 3.0) = 3.0
 *          [S1@P1, S1@P1 with bottom_y 1.0] at D -> both null -> null
 *          [S1@P1, S2] where S2 = S1 with values all null -> A -> 2.5
 * C and G sample v = 0 on purpose: a point at v = 1 sits in the cell spanning rows
 * j=1..2, which touches the null node (0,2) and is therefore null by design (D). The
 * bilinear reading is tested one row of nodes away from that hole, at the same u = 0.75.
 */
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// '../..' = the REPO root (this file lives in client3d/scripts/).
const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
let passed = 0, failed = 0;

function check(label, actual, expected, eps = 1e-6) {
  const ok = (actual === null && expected === null)
    || (typeof actual === 'number' && typeof expected === 'number' && Math.abs(actual - expected) <= eps);
  if (ok) { passed += 1; console.log(`  ok   ${label}`); }
  else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}\n       actual   ${JSON.stringify(actual)}`);
  }
}

/**
 * `surface.ts` is TypeScript and deliberately free of any runtime import (only
 * a type import, which vanishes on transpile), so a plain esbuild transform is
 * enough — no bundler. esbuild ships as a Vite dependency.
 */
async function load() {
  let esbuild;
  try { esbuild = await import('esbuild'); }
  catch { console.error('esbuild missing — run npm install (loud failure on purpose)'); process.exit(2); }
  const dir = await mkdtemp(join(tmpdir(), 'surface-'));
  const src = await readFile(join(ROOT, 'packages/scene-render/src/surface.ts'), 'utf8');
  const out = esbuild.transformSync(src, { loader: 'ts', format: 'esm' });
  const file = join(dir, 'surface.mjs');
  await writeFile(file, out.code, 'utf8');
  return import(`file://${file}`);
}

const { surfaceHeightAt: h, highestSurfaceAt } = await load();

const S1 = {
  step: 1, origin: [-1, -1], cols: 3, rows: 3, box_min: [-1, 0, -1], box_max: [1, 1, 1],
  extent_snapped: [2, 1, 2], values: [0, 100, 200, 0, 100, 200, null, 100, 200],
};
const P1 = { anchor: [4, -3], yaw_deg: 90, bottom_y: 0.5, max_m: 4, measure: 'xz' };

check('A anchor node', h(S1, P1, 4, -3), 2.5);
check('B node (2,1)', h(S1, P1, 4, -5), 4.5);
check('C bilinear 0.75', h(S1, P1, 2, -2.5), 2.0);
check('D null neighbour', h(S1, P1, 5, -2), null);
check('E outside', h(S1, P1, 4, -6), null);
check('F measure xyz', h({ ...S1, extent_snapped: [2, 3, 2] }, { ...P1, measure: 'xyz' }, 4, -3), 0.5 + 4 / 3);
check('G yaw 0', h(S1, { ...P1, yaw_deg: 0 }, 3.5, -5), 2.0);
check('H truncated values', h({ ...S1, values: [0, 100, 200, 0] }, P1, 4, -3), null);

const both = [{ id: 'a', spec: P1, surface: S1 }, { id: 'b', spec: { ...P1, bottom_y: 1.0 }, surface: S1 }];
check('highest at A', highestSurfaceAt(both, 4, -3), 3.0);
check('highest at D', highestSurfaceAt(both, 5, -2), null);
const blank = { ...S1, values: Array(9).fill(null) };
check('highest skips all-null',
  highestSurfaceAt([{ id: 'a', spec: P1, surface: S1 }, { id: 'c', spec: P1, surface: blank }], 4, -3), 2.5);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
