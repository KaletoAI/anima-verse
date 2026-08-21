#!/usr/bin/env node
/**
 * Smoke check for the pure maths of the ONE GROUND (§ A16): the field reading
 * every consumer shares (`packages/scene-render/src/worldHeight.ts`) and the
 * two travel-line derivations in `client3d/src/scene/travelPath.ts`.
 *
 * It used to cover the grid geometry both renderers cut their DRAPED ground on
 * as well; that machinery is deleted (see [1]-[3] below).
 *
 * Usage:  node client3d/scripts/smoke_relief_math.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots).
 *
 * ============================================================================
 * [1]–[3] THE GRID MESH — GONE with "Ein Boden" E5b
 * ============================================================================
 * `gridStepFor` (how fine a draped ground may be cut), `gridPlate` (the one big
 * base plate the world was draped on, already deleted in E3) and
 * `subdivideOnGrid` (a painted area cut on the same lines) were the machinery
 * of DRAPING: a mesh sliced along the height lattice so it could follow the
 * relief. E2 took the terrain's own vertices into the vertex shader, E3 turned
 * every painted ground into a CUT in that one surface, E4 made the last drape —
 * the water — a FLAT mirror, and E5b deleted the scene's own 17 x 17 relief
 * (§ A19 no. 6). Nothing drapes anything any more, so
 * `packages/scene-render/src/gridMesh.ts` and `terrain.ts` are deleted and
 * there is nothing left here to derive by hand.
 *
 * The sections are kept as a HEADING and not silently renumbered, so a reader
 * who remembers the old numbers finds out what happened to them.
 *
 * ============================================================================
 * [3b] THE CONTOUR CELL — the RED counter-probe of "Ein Boden" E2
 * ============================================================================
 * THIS SECTION USED TO BE THE OPPOSITE CLAIM. Until E2 the client sampled a
 * "drawn" ground: it re-read the field along the two triangles its base plate
 * had cut a cell into, because vertices, props and figures had to sit on the
 * MESH rather than on the field. That mesh is gone — the terrain is a CDLOD
 * patch whose vertices come out of the lattice itself — and with it the second
 * height. What stays is the NUMBER, kept here as a counter-probe: this is how
 * far the two used to be apart, and it must not come back.
 *
 * A height area with `height_m` 5 and `falloff_m` 10, its corner at the world
 * origin (the quadrant x ≥ 0, z ≥ 0), on the 8 m grid a big world gets:
 *     h(x, z) = 5 · min(1, min(x, z) / 10)   inside, 0 outside
 * Support points at 0, 8, 16, 24 therefore read
 *     h(0, ·) = h(·, 0) = 0,  h(8, 8) = h(16, 8) = h(8, 16) = 4,
 *     h(16, 16) = h(24, ·≥8) = h(·≥8, 24) = 5.
 * Take the first cell, [0…8] × [0…8]:
 *     h00 = 0 (0,0)   h10 = 0 (8,0)   h01 = 0 (0,8)   h11 = 4 (8,8)
 * and its middle, (4, 4), tx = tz = 0.5:
 *     bilinear        = (0 + 0 + 0 + 4) / 4                      = 1.00 m
 *     drawn (tz ≤ tx) = h00 + 0.5·(h10 − h00) + 0.5·(h11 − h10)  = 2.00 m
 * A metre apart, and the error scales with the cell's TWIST
 * |h00 + h11 − h01 − h10| (here 4) rather than with the falloff — which is why
 * "falloff ≥ one cell" was never the bound, and why the fix had to be one
 * sampler rather than a finer plate.
 *
 * The checks: `sampleWorldHeight` answers the bilinear 1.00 m; the drawn
 * formula — written out HERE, in this file, because the package no longer
 * carries it — answers 2.00 m; and the package exports no sampler that would
 * answer the second number for anybody.
 *
 * ============================================================================
 * [5] A TRAVELLER'S HEIGHT AT ITS PROGRESS
 * ============================================================================
 * The journey (-4, 0) -> (4, 0) runs straight over the peak; it is 8 m long.
 * `pointAtDistance` gives the point, `sampleWorldHeight` the ground under it:
 *   progress 0 m -> (-4, 0) -> 0      (the field's border)
 *   progress 2 m -> (-2, 0) -> 2.5    (half way up the flank)
 *   progress 4 m -> ( 0, 0) -> 5      (the peak)
 *   progress 6 m -> ( 2, 0) -> 2.5
 *   progress 8 m -> ( 4, 0) -> 0
 *
 * ============================================================================
 * [6] `densifyPolyline` — a drawn line that follows the ground
 * ============================================================================
 * (a) The journey above with spacing 4: the single 8 m segment is cut into
 *     ceil(8/4) = 2 pieces -> 3 points (-4, 0), (0, 0), (4, 0), and their
 *     heights are 0, 5, 0 — the line goes OVER the peak instead of through it.
 * (b) Spacing 2 -> 4 pieces -> 5 points at x = -4, -2, 0, 2, 4.
 * (c) CORNERS SURVIVE. (0,0) -> (10,0) -> (10,10) at spacing 4: each 10 m leg
 *     becomes ceil(10/4) = 3 pieces, so the inserted points sit at 10/3 and
 *     20/3 along it and both original corners are still in the list:
 *     1 + 3 + 3 = 7 points, the 4th of them the corner (10, 0).
 * (d) THE CAP DECIDES FIRST. (0,0) -> (100,0) with spacing 1 but at most 11
 *     points: the spacing is stretched to 100/(11-1) = 10, giving 11 points
 *     ten metres apart.
 * (e) A line of fewer than two points, and a spacing of 0, are handed back
 *     unchanged.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/** Every module under test is import-free by design (their headers say so), so
 *  a transpile is all it takes. Should someone add a runtime import, this
 *  fails loudly — that is the alarm, not a nuisance. */
async function loadPure(...relPaths) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'relief-'));
  try {
    const out = [];
    for (const rel of relPaths) {
      const source = await readFile(join(ROOT, rel), 'utf8');
      const code = esbuild.transformSync(source, { loader: 'ts', format: 'esm' }).code;
      const file = join(dir, `${out.length}-${rel.split('/').pop().replace(/\.ts$/, '.mjs')}`);
      await writeFile(file, code, 'utf8');
      out.push(await import(`file://${file}`));
    }
    return out;
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

const [height, travel] = await loadPure(
  'packages/scene-render/src/worldHeight.ts',
  'client3d/src/scene/travelPath.ts');
const { sampleWorldHeight } = height;
const { densifyPolyline, pointAtDistance } = travel;

// --- [1]-[3] the grid mesh — GONE (see the header) ---------------------------
// `gridStepFor`, `gridPlate` and `subdivideOnGrid` are deleted together with
// the two package files that held them. Nothing is asserted here because there
// is nothing to assert: the RED probe for their absence is the module list two
// lines up, which no longer loads `packages/scene-render/src/gridMesh.ts` and
// would fail to resolve it if somebody brought it back by accident.

// --- [3b] the contour cell --------------------------------------------------
console.log('[3b] the drawn-triangle reading is GONE — one sampler, the field');
/** The field of the derivation: a 5 m area with a 10 m falloff whose corner is
 *  the world origin, rastered on an 8 m grid. */
const CORNER_FIELD = (() => {
  const at = (x, z) => (x >= 0 && z >= 0 ? 5 * Math.min(1, Math.min(x, z) / 10) : 0);
  const heights = [];
  for (let j = 0; j < 4; j += 1) {
    const row = [];
    for (let i = 0; i < 4; i += 1) row.push(at(i * 8, j * 8));
    heights.push(row);
  }
  return { origin_x: 0, origin_z: 0, step_m: 8, rows: 4, cols: 4, heights };
})();
checkEq('the rastered field', CORNER_FIELD.heights,
  [[0, 0, 0, 0], [0, 4, 4, 4], [0, 4, 5, 5], [0, 4, 5, 5]]);
check('bilinear in the middle of the contour cell',
  sampleWorldHeight(CORNER_FIELD, 4, 4), 1);

/** The DEAD reading, written out here because the package no longer carries
 *  it: the cell of `cellM` is split from its minimum corner to its maximum
 *  one, so inside it the surface is one of two PLANES. This is what every
 *  figure, prop and area vertex used to be placed by. */
function drawnTriangle(field, x, z, cellM) {
  const i = Math.floor((x - field.origin_x) / cellM);
  const j = Math.floor((z - field.origin_z) / cellM);
  const x0 = field.origin_x + i * cellM;
  const z0 = field.origin_z + j * cellM;
  const tx = (x - x0) / cellM;
  const tz = (z - z0) / cellM;
  const h00 = sampleWorldHeight(field, x0, z0);
  const h10 = sampleWorldHeight(field, x0 + cellM, z0);
  const h01 = sampleWorldHeight(field, x0, z0 + cellM);
  const h11 = sampleWorldHeight(field, x0 + cellM, z0 + cellM);
  return tz <= tx
    ? h00 + tx * (h10 - h00) + tz * (h11 - h10)
    : h00 + tz * (h01 - h00) + tx * (h11 - h01);
}
check('what the drawn triangle used to answer there',
  drawnTriangle(CORNER_FIELD, 4, 4, 8), 2);
check('…the gap that is now gone', drawnTriangle(CORNER_FIELD, 4, 4, 8)
  - sampleWorldHeight(CORNER_FIELD, 4, 4), 1);
checkEq('and the package exports no sampler that answers the second number',
  ['sampleGroundHeight', 'sampleCompositeGroundHeight', 'maxWorldHeightIn',
    'worldHeightRangeIn'].filter((n) => n in height), []);

// --- [5] the traveller on the slope ----------------------------------------
const FIELD = {
  origin_x: -4, origin_z: -4, step_m: 4, rows: 3, cols: 3,
  heights: [[0, 0, 0], [0, 5, 0], [0, 0, 0]],
};
console.log('[5] a traveller stands on the ground under its progress');
const ROUTE = [[-4, 0], [4, 0]];
for (const [progress, expected] of [[0, 0], [2, 2.5], [4, 5], [6, 2.5], [8, 0]]) {
  const at = pointAtDistance(ROUTE, progress);
  check(`progress ${progress} m -> (${at[0]}, ${at[1]})`,
    sampleWorldHeight(FIELD, at[0], at[1]), expected);
}

// --- [6] the drawn line ----------------------------------------------------
console.log('[6] densifyPolyline gives the line a point per ground sample');
checkEq('spacing 4 over the peak', densifyPolyline(ROUTE, 4),
  [[-4, 0], [0, 0], [4, 0]]);
checkEq('…their heights', densifyPolyline(ROUTE, 4).map(
  ([x, z]) => sampleWorldHeight(FIELD, x, z)), [0, 5, 0]);
checkEq('spacing 2', densifyPolyline(ROUTE, 2).map(([x]) => x), [-4, -2, 0, 2, 4]);
const corner = densifyPolyline([[0, 0], [10, 0], [10, 10]], 4);
check('a corner route keeps its corners: point count', corner.length, 7);
checkEq('…the corner itself is point 4', corner[3], [10, 0]);
const capped = densifyPolyline([[0, 0], [100, 0]], 1, 11);
check('the cap stretches the spacing: point count', capped.length, 11);
checkEq('…ten metres apart', capped[1], [10, 0]);
checkEq('a one-point line is handed back', densifyPolyline([[1, 2]], 4), [[1, 2]]);
checkEq('spacing 0 densifies nothing', densifyPolyline(ROUTE, 0), ROUTE);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
