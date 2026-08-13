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
 * [2] `gridPlate` — the base plate on the field's own lines
 * ============================================================================
 * `gridPlate(-5, -5, 5, 5, step 4, origin (-4, -4))`, no relief box = cut all
 * over. The cut part is snapped OUTWARD onto the grid anchored at the origin:
 *   x0 = -4 + floor((-5+4)/4)·4 = -4 + (-1)·4 = -8
 *   x1 = -4 + ceil(( 5+4)/4)·4 = -4 +   3 ·4 =  8    (z likewise)
 * so 16 m per axis at 4 m = 4 × 4 cells, 5 × 5 = 25 support points (75 pos
 * numbers, 50 uv numbers) and 16 · 6 = 96 index entries. The REPORTED extent
 * stays the one that was asked for (-5…5) — that is what the UVs are
 * normalised over, and the snap only adds a metre of ground past the frame.
 *   - the first vertex is (-8, 0, -8) at uv ((-8+5)/10, (5+8)/10) =
 *     (-0.3, 1.3): u grows with x, v is 1 at the MINIMUM z edge (what
 *     `PlaneGeometry` did after `rotateX(-90°)`), and the snapped overhang
 *     runs just outside 0…1, which is what RepeatWrapping is for;
 *   - vertex (i 2, j 2) = index 12 is the world origin (0, 0) at uv (0.5, 0.5);
 *   - the first cell is [0, 5, 6, 0, 6, 1]: its split runs from the minimum
 *     corner (index 0) to the maximum one (index 6);
 *   - every y is 0 — lifting is the caller's step.
 * A step of 0 gives the single quad of the flat world, extent unsnapped.
 *
 * (b) THE BUDGET GOES WHERE THE RELIEF IS. `gridPlate(-100, -100, 100, 100,
 *     step 4, origin (0, 0), relief [0…8] × [0…8])`: only the field's own box
 *     is cut (2 × 2 cells, 9 support points, 24 index entries), the rest is
 *     four plain quads — north (-100…100) × (-100…0), south (-100…100) ×
 *     (8…100), west (-100…0) × (0…8), east (8…100) × (0…8). 9 + 16 = 25
 *     vertices, 24 + 24 = 48 index entries, and the areas
 *       20 000 + 18 400 + 800 + 736 + 64 = 40 000 m²
 *     are exactly the 200 × 200 m asked for — so the ring covers the plate
 *     without a gap AND without overlapping the cut part.
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
 *     which lies wholly inside it. Its two triangles must be the SAME two
 *     `gridPlate(0, 0, 8, 8, 4)` builds for that cell:
 *       (4,0), (4,4), (8,4)  and  (4,0), (8,4), (8,0)
 *     — same split, from the cell's minimum corner to its maximum one. That is
 *     what makes a meadow lie ON the plate over a hill instead of cutting
 *     through it.
 *
 * ============================================================================
 * [3b] THE CONTOUR CELL — why the ground is sampled TRIANGULATED
 * ============================================================================
 * The cell test above only covers vertices that land ON the grid. An area's
 * OUTLINE runs where it was painted, so its vertices sit anywhere INSIDE a
 * cell — and there the bilinear field and the drawn mesh are two different
 * surfaces. Measured case, from the regime the first version called safe:
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
 *     bilinear      = (0 + 0 + 0 + 4) / 4                        = 1.00 m
 *     drawn (tz ≤ tx) = h00 + 0.5·(h10 − h00) + 0.5·(h11 − h10)  = 2.00 m
 * A metre apart — an area vertex lifted by the field sinks A FULL METRE under
 * the plate it lies on, and the plate comes through the meadow. The error
 * scales with the cell's TWIST |h00 + h11 − h01 − h10| (here 4), not with the
 * falloff, which is why "falloff ≥ one cell" was never the bound.
 *
 * The checks: the drawn sampler agrees with the plate's own surface (measured
 * barycentrically on the lifted plate triangles) at the cell middle AND at a
 * handful of other points, while the bilinear one is 1.00 m off at the middle
 * — the red counter-check of the first version.
 *
 * ============================================================================
 * [4] `maxWorldHeightIn` — the height of a fog quad
 * ============================================================================
 * THE FIELD is the one `smoke_world_height.mjs` uses: origin (-4, -4), step 4,
 * a single 5 m peak at (0, 0), heights [[0,0,0],[0,5,0],[0,0,0]].
 *   (a) the whole field, (-4,-4)…(4,4): the grid line x = 0 / z = 0 is sampled
 *       and hits the peak                                              -> 5
 *   It reads the DRAWN ground, so the numbers are the triangulated ones:
 *   (b) (1,1)…(3,3), a rectangle with no grid line inside: the maximum sits at
 *       the CORNER nearest the peak, and that corner lies in the cell
 *       [0…4]² whose corners are h00 = 5 (the peak), h10 = h01 = h11 = 0.
 *       At (1,1): tx = tz = 0.25, tz <= tx, so
 *       5 + 0.25·(0−5) + 0.25·(0−0)                                -> 3.75
 *       (the other three corners give 1.25 each)
 *   (c) (-2,-2)…(2,2) — the peak is INSIDE the rectangle and on none of its
 *       corners. The grid lines x = 0 and z = 0 are sampled, so the answer is
 *       the peak                                                    -> 5
 *       (the nearest corner alone reads 0 + 0.5·(0−0) + 0.5·(5−0) = 2.5 —
 *        that is the discriminating half of this case)
 *   (d) no field at all                                               -> 0
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
const { gridPlate, gridStepFor, subdivideOnGrid } = grid;
const { maxWorldHeightIn, sampleGroundHeight, sampleWorldHeight } = height;
const { densifyPolyline, pointAtDistance } = travel;

// --- [1] the cell size ------------------------------------------------------
console.log('[1] gridStepFor doubles until the mesh fits the budget');
check('400 m at step 4', gridStepFor(0, 0, 400, 400, 4), 4);
check('1 000 m at step 4', gridStepFor(0, 0, 1000, 1000, 4), 8);
check('1 500 m at step 4 (the largest world of § A16)',
  gridStepFor(-750, -750, 750, 750, 4), 8);
check('no relief (step 0) is handed back', gridStepFor(0, 0, 400, 400, 0), 0);

// --- [2] the base plate -----------------------------------------------------
console.log('[2] gridPlate snaps onto the grid and splits every cell alike');
const plate = gridPlate(-5, -5, 5, 5, 4, -4, -4);
checkEq('the reported extent is the one asked for',
  [plate.minX, plate.minZ, plate.maxX, plate.maxZ], [-5, -5, 5, 5]);
checkEq('support points per axis', [plate.cols, plate.rows], [5, 5]);
check('position numbers', plate.pos.length, 75);
check('uv numbers', plate.uv.length, 50);
check('index entries', plate.index.length, 96);
checkEq('first vertex', plate.pos.slice(0, 3), [-8, 0, -8]);
checkEq('first uv (the snapped overhang runs outside 0…1)',
  plate.uv.slice(0, 2), [-0.3, 1.3]);
checkEq('the world origin is vertex 12', plate.pos.slice(36, 39), [0, 0, 0]);
checkEq('…at uv (0.5, 0.5)', plate.uv.slice(24, 26), [0.5, 0.5]);
checkEq('the first cell splits minimum -> maximum corner',
  plate.index.slice(0, 6), [0, 5, 6, 0, 6, 1]);
check('every vertex lies at y = 0',
  plate.pos.filter((_, i) => i % 3 === 1).reduce((a, b) => a + Math.abs(b), 0), 0);
const ringed = gridPlate(-100, -100, 100, 100, 4, 0, 0,
  { x0: 0, z0: 0, x1: 8, z1: 8 });
check('a relief box cuts only itself: vertices', ringed.pos.length / 3, 25);
check('…index entries', ringed.index.length, 48);
const plateArea = (g) => {
  let sum = 0;
  for (let t = 0; t + 2 < g.index.length; t += 3) {
    const v = [0, 1, 2].map((n) => g.index[t + n] * 3);
    const [ax, az] = [g.pos[v[0]], g.pos[v[0] + 2]];
    const [bx, bz] = [g.pos[v[1]], g.pos[v[1] + 2]];
    const [cx, cz] = [g.pos[v[2]], g.pos[v[2] + 2]];
    sum += Math.abs((bx - ax) * (cz - az) - (cx - ax) * (bz - az)) / 2;
  }
  return sum;
};
check('…and the ring covers the plate exactly, without overlap',
  plateArea(ringed), 40000);
const flatPlate = gridPlate(-100, -100, 100, 100, 0);
checkEq('a flat world is one quad, unsnapped',
  [flatPlate.pos.length, flatPlate.index.length, flatPlate.minX, flatPlate.maxX],
  [12, 6, -100, 100]);

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
const platePlain = gridPlate(0, 0, 8, 8, 4, 0, 0);
const plateTris = [];
for (let i = 0; i + 2 < platePlain.index.length; i += 3) {
  plateTris.push([0, 1, 2].map((n) => {
    const v = platePlain.index[i + n] * 3;
    return [platePlain.pos[v], platePlain.pos[v + 2]];
  }));
}
check('the cell [4…8]×[0…4] of the area is two triangles', areaCell.length, 2);
checkEq('…and they are the plate\'s own two',
  asKey(areaCell), asKey(plateTris.filter(inCell)));
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
    if (asKey(tris) === asKey(plateTris.filter(inCell))) sameCell += 1;
  }
}
check('every winding and rotation gives that same cell', sameCell, 6);

// --- [3b] the contour cell --------------------------------------------------
console.log('[3b] inside a cell the DRAWN ground is the triangulated one');
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
check('the DRAWN ground there', sampleGroundHeight(CORNER_FIELD, 4, 4, 8), 2);

/** The plate's own surface at (x, z): lift its vertices, find the triangle the
 *  point falls in and interpolate barycentrically. This is the mesh, measured
 *  — not a second formula. */
function plateSurfaceAt(plate, lift, x, z) {
  const pos = [...plate.pos];
  for (let i = 0; i < pos.length; i += 3) pos[i + 1] += lift(pos[i], pos[i + 2]);
  for (let t = 0; t + 2 < plate.index.length; t += 3) {
    const v = [0, 1, 2].map((n) => plate.index[t + n] * 3);
    const [ax, az] = [pos[v[0]], pos[v[0] + 2]];
    const [bx, bz] = [pos[v[1]], pos[v[1] + 2]];
    const [cx, cz] = [pos[v[2]], pos[v[2] + 2]];
    const den = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz);
    if (Math.abs(den) < 1e-12) continue;
    const wa = ((bz - cz) * (x - cx) + (cx - bx) * (z - cz)) / den;
    const wb = ((cz - az) * (x - cx) + (ax - cx) * (z - cz)) / den;
    const wc = 1 - wa - wb;
    if (wa < -1e-9 || wb < -1e-9 || wc < -1e-9) continue;
    return wa * pos[v[0] + 1] + wb * pos[v[1] + 1] + wc * pos[v[2] + 1];
  }
  return NaN;
}
const CORNER_PLATE = gridPlate(0, 0, 24, 24, 8, 0, 0);
const drawn = (x, z) => sampleGroundHeight(CORNER_FIELD, x, z, 8);
for (const [x, z] of [[4, 4], [2, 6], [6, 2], [10, 3], [13, 17], [8, 8]]) {
  check(`the plate's surface at (${x}, ${z}) IS the drawn sampler`,
    plateSurfaceAt(CORNER_PLATE, drawn, x, z), drawn(x, z), 1e-9);
}
check('a bilinearly lifted vertex sinks under it by',
  drawn(4, 4) - sampleWorldHeight(CORNER_FIELD, 4, 4), 1);

// --- [4] the fog height -----------------------------------------------------
console.log('[4] maxWorldHeightIn — what a fog quad has to clear');
const FIELD = {
  origin_x: -4, origin_z: -4, step_m: 4, rows: 3, cols: 3,
  heights: [[0, 0, 0], [0, 5, 0], [0, 0, 0]],
};
check('the whole field', maxWorldHeightIn(FIELD, -4, -4, 4, 4), 5);
check('a rectangle beside the peak', maxWorldHeightIn(FIELD, 1, 1, 3, 3), 3.75);
check('a rectangle AROUND the peak (no corner sees it)',
  maxWorldHeightIn(FIELD, -2, -2, 2, 2), 5);
check('…its corners alone would say', sampleGroundHeight(FIELD, -2, -2), 2.5);
check('no field at all', maxWorldHeightIn(null, -4, -4, 4, 4), 0);

// --- [5] the traveller on the slope ----------------------------------------
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
