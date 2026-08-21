#!/usr/bin/env node
/**
 * Smoke check for the pure maths of the DRAPED GROUND (E8 task 3, § A16):
 * the grid geometry both renderers cut their ground on
 * (`packages/scene-render/src/gridMesh.ts`), the field query the fog hangs on
 * (`maxWorldHeightIn`, worldHeight.ts) and the two travel-line derivations in
 * `client3d/src/scene/travelPath.ts`.
 *
 * Usage:  node client3d/scripts/smoke_relief_math.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots).
 *
 * ============================================================================
 * [1] `gridStepFor` — how fine the ground may be cut
 * ============================================================================
 * The rule: the field's own `step`, DOUBLED until `ceil(w/step)·ceil(d/step)`
 * stays under the cell budget (40 000, derived in gridMesh.ts from the § A16
 * point budget).
 *   (a) 400 × 400 m at step 4  -> 100 × 100 = 10 000 cells                -> 4
 *   (b) 1 000 × 1 000 m at 4   -> 250 × 250 = 62 500 > 40 000; at 8 ->
 *       125 × 125 = 15 625                                                -> 8
 *   (c) 1 500 × 1 500 m at 4 (the largest world § A16 can describe, plus the
 *       2 × 60 m ground margin) -> 375² = 140 625 > 40 000; at 8 -> 188² =
 *       35 344                                                            -> 8
 *   (d) step 0 (no relief) is handed back unchanged                       -> 0
 *
 * ============================================================================
 * [2] `gridPlate` — GONE with "Ein Boden" E3
 * ============================================================================
 * The base plate was ONE mesh over the whole world frame, cut on the field's
 * own lines, with every painted area draped on top of it. Both halves are gone:
 * since E2 the terrain places its own vertices out of the height lattice in the
 * vertex shader (`scene/terrainLod.ts`), and since E3 the painted grounds are a
 * CUT in that one surface rather than meshes lying on it
 * (`@anima/scene-render/layerCut.ts`). Nothing calls `gridPlate`, so it was
 * deleted and there is nothing left here to derive by hand.
 *
 * The section is kept as a HEADING and not silently renumbered, so a reader who
 * remembers the old numbers finds out what happened to them.
 *
 * ============================================================================
 * [3] `subdivideOnGrid` — a painted area cut on the same lines
 * ============================================================================
 * (a) ONE CELL, ONE TRIANGLE. The triangle (0,0), (4,0), (4,4) with step 4 at
 *     origin (0, 0) lies inside a single cell: no grid line runs strictly
 *     between its bounds, so it comes back as itself — 1 triangle, area 8.
 *
 * (b) ACROSS A COLUMN BORDER. The triangle A(0,0), B(8,0), C(0,4), step 4:
 *     x = 4 cuts it, z has no interior line. On the hypotenuse B->C the cut
 *     sits at half the segment, i.e. (4, 2).
 *       low  (x <= 4): (0,0), (4,0), (4,2), (0,4)   shoelace 24/2 = 12 m²
 *       high (x >= 4): (4,0), (8,0), (4,2)          shoelace  8/2 =  4 m²
 *     Fanned from their minimum corners that is 2 + 1 = 3 triangles, and
 *     12 + 4 = 16 m² is exactly the original 8·4/2.
 *
 * (c) UVs STAY WORLD METRES. `buildAreaGeometry` hands out uv = (x, -z) (the
 *     shape plane of `groundAreas.ts`). The cut interpolates linearly and the
 *     UV is affine in the position, so EVERY output vertex — the ones on the
 *     grid lines included — still has u = x and v = -z.
 *
 * (d) THE CRACK TEST, the one this whole file exists for. Cut the triangle
 *     (0,0), (8,0), (8,8) on the same grid and take the cell [4…8] × [0…4],
 *     which lies wholly inside it. Its two triangles must be the two the RULE
 *     states — the split from the cell's MINIMUM corner to its MAXIMUM one:
 *       (4,0), (4,4), (8,4)  and  (4,0), (8,4), (8,0)
 *     That used to be checked against `gridPlate`'s own cell; with the plate
 *     gone the diagonal is derived by hand instead, which is the same statement
 *     without a second mesh to compare against. It is what makes the water
 *     drape lie ON the terrain over a hill instead of cutting through it.
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

const [grid, height, travel] = await loadPure(
  'packages/scene-render/src/gridMesh.ts',
  'packages/scene-render/src/worldHeight.ts',
  'client3d/src/scene/travelPath.ts');
const { gridStepFor, subdivideOnGrid } = grid;
const { sampleWorldHeight } = height;
const { densifyPolyline, pointAtDistance } = travel;

// --- [1] the cell size ------------------------------------------------------
console.log('[1] gridStepFor doubles until the mesh fits the budget');
check('400 m at step 4', gridStepFor(0, 0, 400, 400, 4), 4);
check('1 000 m at step 4', gridStepFor(0, 0, 1000, 1000, 4), 8);
check('1 500 m at step 4 (the largest world of § A16)',
  gridStepFor(-750, -750, 750, 750, 4), 8);
check('no relief (step 0) is handed back', gridStepFor(0, 0, 400, 400, 0), 0);

// --- [2] the base plate — GONE with E3 --------------------------------------
// `gridPlate` built ONE big mesh over the whole world frame, cut on the field's
// own lines, and every painted area was draped on top of it. Both halves of
// that arrangement are gone: since E2 the terrain places its own vertices out
// of the height lattice in the vertex shader (`scene/terrainLod.ts`), and since
// E3 the painted grounds are a CUT in that one surface rather than meshes on it
// (`@anima/scene-render/layerCut.ts`). Nothing calls the plate, so there is
// nothing here to derive by hand any more. What survived the removal —
// `gridStepFor` above and `subdivideOnGrid` below — is checked exactly as
// before; the ONE mesh still cut on the field's lines is the water drape, until
// E4 gives it a level mirror.
//
// The crack test of [3] used to measure the area's cell against the PLATE's
// cell. It now measures it against the diagonal the rule itself states (minimum
// corner to maximum corner), which is the same statement without a second mesh
// to compare against.

// --- [3] the painted areas --------------------------------------------------
console.log('[3] subdivideOnGrid cuts on the same lines');

/** Triangles of a flat position list as `[[x, z], …]` triples. */
function triangles(pos) {
  const out = [];
  for (let t = 0; t + 8 < pos.length; t += 9) {
    out.push([[pos[t], pos[t + 2]], [pos[t + 3], pos[t + 5]], [pos[t + 6], pos[t + 8]]]);
  }
  return out;
}
function triArea([a, b, c]) {
  return Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2;
}
const totalArea = (pos) => triangles(pos).reduce((s, t) => s + triArea(t), 0);

const oneCell = subdivideOnGrid([0, 0, 0, 4, 0, 0, 4, 0, 4], null, 4, 0, 0);
check('a triangle inside one cell stays one triangle',
  triangles(oneCell.pos).length, 1);
check('…with its own area', totalArea(oneCell.pos), 8);

const cut = subdivideOnGrid([0, 0, 0, 8, 0, 0, 0, 0, 4], null, 4, 0, 0);
check('a triangle across a column border becomes three',
  triangles(cut.pos).length, 3);
check('…and keeps its area', totalArea(cut.pos), 16, 1e-9);
check('…none of it beyond the original outline',
  triangles(cut.pos).every(([a, b, c]) => [a, b, c].every(
    ([x, z]) => x >= -1e-9 && z >= -1e-9 && x <= 8 + 1e-9 && z <= 4 + 1e-9)) ? 1 : 0, 1);

// uv = (x, -z), the convention of `buildAreaGeometry`
const uvCut = subdivideOnGrid([0, 0, 0, 8, 0, 0, 0, 0, 4],
  [0, 0, 8, 0, 0, -4], 4, 0, 0);
let uvDrift = 0;
for (let i = 0, k = 0; i + 2 < uvCut.pos.length; i += 3, k += 2) {
  uvDrift += Math.abs(uvCut.uv[k] - uvCut.pos[i]);
  uvDrift += Math.abs(uvCut.uv[k + 1] + uvCut.pos[i + 2]);
}
check('UVs stay world metres through every cut', uvDrift, 0, 1e-12);

// THE CRACK TEST: a full cell of an area is the plate's own cell.
const big = subdivideOnGrid([0, 0, 0, 8, 0, 0, 8, 0, 8], null, 4, 0, 0);
const inCell = (t) => t.every(([x, z]) => x >= 4 - 1e-9 && x <= 8 + 1e-9
  && z >= -1e-9 && z <= 4 + 1e-9);
const asKey = (tris) => tris.map((t) => t.map(([x, z]) => `${x},${z}`).sort().join('|'))
  .sort().join(' / ');
const areaCell = triangles(big.pos).filter(inCell);
// THE RULE, DERIVED BY HAND: a full grid cell is split from its MINIMUM corner
// (4, 0) to its MAXIMUM one (8, 4), so the cell [4…8]×[0…4] is exactly
//   (4,0) (4,4) (8,4)   and   (4,0) (8,4) (8,0)
// — the two triangles every consumer of this grid has to produce, whichever way
// it arrived at the cell.
const CELL_TRIS = [
  [[4, 0], [4, 4], [8, 4]],
  [[4, 0], [8, 4], [8, 0]],
];
check('the cell [4…8]×[0…4] of the area is two triangles', areaCell.length, 2);
checkEq('…and they are the minimum-to-maximum diagonal of the rule',
  asKey(areaCell), asKey(CELL_TRIS));
// …and that must not depend on how the triangle happened to be wound or
// where earcut started it: the cell polygon comes out of the clipping in a
// different order for each of these six, and the fan from the MINIMUM corner
// is what makes them all describe the same surface.
const CORNERS = [[0, 0], [8, 0], [8, 8]];
let sameCell = 0;
for (const winding of [CORNERS, [...CORNERS].reverse()]) {
  for (let r = 0; r < 3; r += 1) {
    const rot = [winding[r % 3], winding[(r + 1) % 3], winding[(r + 2) % 3]];
    const flat = rot.flatMap(([x, z]) => [x, 0, z]);
    const tris = triangles(subdivideOnGrid(flat, null, 4, 0, 0).pos).filter(inCell);
    if (asKey(tris) === asKey(CELL_TRIS)) sameCell += 1;
  }
}
check('every winding and rotation gives that same cell', sameCell, 6);

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
