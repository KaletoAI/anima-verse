#!/usr/bin/env node
/**
 * Smoke check for the ROOM SPOTS of "Ein Boden" E5b — the centres, stands and
 * seats that used to be measured against meshes and are read off data now.
 *
 * Usage:  node client3d/scripts/smoke_room_spots.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots).
 *
 * WHAT REPLACED WHAT. Until E5b a room's centre, its NPC stands and its
 * sit/lie targets came out of 36 rays shot down at the room's PLATE mesh: the
 * dominant 7 cm height bin was the floor, a reference ray at the door repaired
 * it where a generated mesh had holes, and everything within 12 cm of that
 * floor was a stand. Storey 0 has no plate to ray any more (§ A19 no. 1), so
 * the shape comes from `floor_plan` (§ A19 no. 3) and the height from the one
 * height function at the point being asked about. The rules under test are the
 * pure half of that, `client3d/src/game/ground.ts`; the lookups around them
 * live in `scene/tiles.deriveRoomSpots`.
 *
 * ============================================================================
 * [1] `polygonCentroid` — the centre of a drawn room
 * ============================================================================
 * The shoelace centroid, i.e. the centre of MASS of the surface, not the
 * average of the corners: a wall drawn with ten points and the opposite one
 * with two would pull a corner average against the ten-point wall.
 *
 * (a) The square (−1,−1) (1,−1) (1,1) (−1,1) is its own centre, (0, 0).
 * (b) THE L-SHAPED ROOM, which is the whole reason this file exists:
 *       (0,0) (6,0) (6,2) (2,2) (2,6) (0,6)
 *     is a 6 × 2 bar plus a 2 × 4 column on top of its left end.
 *       bar:    area 12, centre (3, 1)
 *       column: area  8, centre (1, 4)
 *       total  area 20
 *       cx = (12·3 + 8·1) / 20 = 44/20 = 2.2
 *       cz = (12·1 + 8·4) / 20 = 44/20 = 2.2
 *     and (2.2, 2.2) lies in the CUT-OUT quadrant (x > 2 and z > 2): the area
 *     centroid of this room is OUTSIDE the room. That is the case the fallback
 *     in `deriveRoomSpots` exists for.
 * (c) Winding does not matter: the reversed ring gives the same point (the
 *     signed area flips with the numerator).
 * (d) A ring of two points, and a ring whose three points are collinear,
 *     enclose nothing and have no centre — `null`, never 0/0.
 *
 * ============================================================================
 * [2] `roomSpotGrid` — the stands, on the raster the rays were shot on
 * ============================================================================
 * `SPOT_GRID` = 6 rows and columns over `SPOT_SPREAD` = 0.78 of the room's
 * BOUNDING BOX, around its centre — the very raster of the ray version — with
 * the polygon test where the ray hit used to be. Ordered by distance from the
 * centre, nearest first, which is why a lone character stands in the middle of
 * its room.
 *
 * (a) THE RECTANGULAR ROOM (−4,−4) (0,−4) (0,−1) (−4,−1) — 4 m × 3 m, the
 *     "Haus von Kai" room hull the walk smoke uses:
 *       bbox centre (−2, −2.5), w = 4, d = 3
 *       x_i = −2 + (i/5 − 0.5)·4·0.78 = −2 + (i/5 − 0.5)·3.12
 *             i = 0…5 -> −3.56, −2.936, −2.312, −1.688, −1.064, −0.44
 *       z_j = −2.5 + (j/5 − 0.5)·3·0.78 = −2.5 + (j/5 − 0.5)·2.34
 *             j = 0…5 -> −3.67, −3.202, −2.734, −2.266, −1.798, −1.33
 *     The spread is 0.78 < 1, so all 36 points lie inside the rectangle.
 *     The nearest four are the (i, j) ∈ {2,3}² corners at
 *       d² = 0.312² + 0.234² = 0.097344 + 0.054756 = 0.1521  (d = 0.39 m)
 *     and the sort is stable, so the FIRST of them in build order (i outer,
 *     j inner) wins: (−2.312, −2.734).
 * (b) THE L-SHAPED ROOM: bbox 0…6 × 0…6, centre (3, 3), w = d = 6.
 *       x_i = z_i = 3 + (i/5 − 0.5)·6·0.78 = 3 + (i/5 − 0.5)·4.68
 *             -> 0.66, 1.596, 2.532, 3.468, 4.404, 5.34
 *     A point is in the L iff z ≤ 2 (the bar) or x ≤ 2 (the column):
 *       x = 0.66  -> all 6      x = 2.532 -> z ∈ {0.66, 1.596}   = 2
 *       x = 1.596 -> all 6      x = 3.468 / 4.404 / 5.34         = 2 each
 *     so 6 + 6 + 2 + 2 + 2 + 2 = 20 stands, and 16 of the 36 raster points
 *     fall into the cut-out quadrant and are dropped.
 *     The nearest to (3, 3) is a four-way tie at
 *       d² = 1.404² + 0.468² = 1.971216 + 0.219024 = 2.19024   (d = 1.48 m)
 *     between (2.532, 1.596), (3.468, 1.596), (1.596, 2.532) and
 *     (1.596, 3.468); build order makes it (1.596, 2.532) — which is INSIDE
 *     the room, and that is exactly what makes it a usable centre for a room
 *     whose own centroid is not.
 * (c) Without a hull nothing is dropped: 36 points.
 * (d) A degenerate hull (fewer than three points) is not a filter either — it
 *     contains nothing, and a room that dropped every stand would be a room
 *     nobody could be placed in.
 *
 * ============================================================================
 * [3] `SPOT_FLAT_M` — the 12 cm, now measured against the HEIGHT DATA
 * ============================================================================
 * The ray version kept a hit whose y was within 0.12 m of the dominant height
 * bin. The same tolerance survives, applied to the SAMPLER: a stand whose
 * ground runs further than that from the room's own floor is the hillside an
 * open zone happens to climb, not part of that floor.
 *
 * Under a BUILT room it is inert by construction — § G5 stamps the plot flat,
 * so every stand reads the room's floor to the millimetre. Derived on a plane
 * that rises 0.05 m/m (a 2.9° slope) through a 4 m room: over the raster's
 * half-width 1.56 m the ground moves ±0.078 m, so nothing is dropped; at
 * 0.10 m/m (5.7°) it moves ±0.156 m and the outer columns go.
 *
 * ============================================================================
 * [4] `furnitureUse` — a seat is measured on the OBJECT, over the DATA floor
 * ============================================================================
 * The floor reference is the room's data height; what is measured against it
 * is the prop's own bounding box. The windows are re-derived for a 1.70 m
 * figure (the pre-E5b 0.08…0.32 m was a real-metre window from the era when a
 * room figure was 0.60 m tall — `k` was a scale then and has been 1 since § B
 * E4, so it caught nothing at all):
 *   SEAT_MIN_M 0.25   a footstool
 *   SEAT_MAX_M 0.70   a bar stool; a table at 0.72 m and up is NOT a seat
 *   LIE_LENGTH_M 1.6 / LIE_WIDTH_M 0.7   a body needs both
 *
 *   chair   0.45 high, 0.5 × 0.5   -> sit   (long 0.5 < 1.6)
 *   bench   0.45 high, 1.8 × 0.5   -> sit   (short 0.5 < 0.7)
 *   bed     0.55 high, 2.0 × 1.4   -> lie
 *   table   0.75 high, 1.2 × 0.8   -> null  (over the seat window)
 *   rug     0.02 high              -> null  (under it)
 *   the windows are INCLUSIVE at both ends: 0.25 and 0.70 are seats, 0.24 and
 *   0.71 are not; 1.6 × 0.7 exactly is a bed.
 *   AND THE FLOOR MOVES WITH THE ROOM: the same chair in a first-storey room
 *   (floor 2.90) has its surface at 3.35 and is still a seat — which is the
 *   whole point of measuring over the data floor instead of over zero.
 *
 * THERE IS NO [5] ANY MORE. It checked `zoneWaterMirrors`: the mirrors of the
 * rooms whose floor kind was a water surface, out of the layer index's `waters`
 * list. "Ein Wasser-Gesetz" W1 deleted that bake stage, that list and the room
 * water fields — water is an ART on the MAP now, and a room that lies in a
 * painted one merely says so in its floor plan (`map_water`, a derived
 * reference). The mirror arithmetic that replaced it is
 * `client3d/scripts/smoke_water_plane.mjs`; what is left here is room GEOMETRY,
 * which W1 did not touch.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/** The modules under test are import-free apart from each other, so a plain
 *  transpile is enough — the pattern of `smoke_walk_math.mjs`. */
async function loadModules(specs) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'roomspots-'));
  try {
    for (const [rel, name] of specs) {
      const source = await readFile(join(ROOT, rel), 'utf8');
      const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
      await writeFile(join(dir, `${name}.mjs`),
        out.code.replace(/(from\s*["'])(\.\/[\w-]+)(["'])/g, '$1$2.mjs$3'), 'utf8');
    }
    const loaded = {};
    for (const [, name] of specs) {
      loaded[name] = await import(`file://${join(dir, `${name}.mjs`)}`);
    }
    return loaded;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
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
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}
function compare(a, b, eps) {
  if (a === null || b === null) return a === b;
  if (typeof b === 'number') return typeof a === 'number' && Math.abs(a - b) <= eps;
  if (Array.isArray(b)) {
    return Array.isArray(a) && a.length === b.length
      && b.every((v, i) => compare(a[i], v, eps));
  }
  if (typeof b === 'object') {
    const keys = Object.keys(b);
    if (typeof a !== 'object' || a === null) return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

const { ground } = await loadModules([
  ['client3d/src/game/polygon.ts', 'polygon'],
  ['client3d/src/game/ground.ts', 'ground'],
]);
const { polygonCentroid, roomSpotGrid, furnitureUse,
  SPOT_GRID, SPOT_SPREAD, SPOT_FLAT_M,
  SEAT_MIN_M, SEAT_MAX_M, LIE_LENGTH_M, LIE_WIDTH_M } = ground;
const { pointInPolygon } = (await loadModules(
  [['client3d/src/game/polygon.ts', 'polygon']])).polygon;

// --- [1] the centre of a drawn room -----------------------------------------
console.log('[1] polygonCentroid — the centre of MASS of the drawn hull');
const SQUARE = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
check('the square is its own centre', polygonCentroid(SQUARE), { x: 0, z: 0 });
const L_ROOM = [[0, 0], [6, 0], [6, 2], [2, 2], [2, 6], [0, 6]];
check('the L-shaped room: (44/20, 44/20)', polygonCentroid(L_ROOM),
  { x: 2.2, z: 2.2 });
check('…and that point is OUTSIDE the room it is the centroid of',
  pointInPolygon(2.2, 2.2, L_ROOM), false);
check('winding does not matter', polygonCentroid([...L_ROOM].reverse()),
  { x: 2.2, z: 2.2 });
check('a two-point ring has no centre', polygonCentroid([[0, 0], [1, 1]]), null);
check('…and neither does a collinear one',
  polygonCentroid([[0, 0], [1, 1], [2, 2]]), null);
check('…nor an absent one', polygonCentroid(undefined), null);

// --- [2] the stands ----------------------------------------------------------
console.log('\n[2] roomSpotGrid — the raster the rays were shot on');
check('the raster is 6 x 6', SPOT_GRID, 6);
check('…over 0.78 of the bounding box', SPOT_SPREAD, 0.78);
const RECT = [[-4, -4], [0, -4], [0, -1], [-4, -1]];
const rect = roomSpotGrid(RECT, -2, -2.5, 4, 3);
check('the rectangular room keeps all 36 stands', rect.length, 36);
check('…and the nearest one is (−2.312, −2.734)', rect[0],
  { x: -2.312, z: -2.734 });
check('…at 0.39 m from the centre',
  Math.hypot(rect[0].x + 2, rect[0].z + 2.5), 0.39);
check('…and every one of them is inside the room',
  rect.every((p) => pointInPolygon(p.x, p.z, RECT)), true);
const lshape = roomSpotGrid(L_ROOM, 3, 3, 6, 6);
check('the L-shaped room drops the 16 points of its cut-out quadrant',
  lshape.length, 20);
check('…so the nearest stand is (1.596, 2.532)', lshape[0],
  { x: 1.596, z: 2.532 });
check('…which IS inside the room, unlike its centroid',
  pointInPolygon(lshape[0].x, lshape[0].z, L_ROOM), true);
check('…at 1.48 m from the bbox centre',
  Math.hypot(lshape[0].x - 3, lshape[0].z - 3), Math.sqrt(2.19024));
check('…and every stand is inside',
  lshape.every((p) => pointInPolygon(p.x, p.z, L_ROOM)), true);
check('without a hull nothing is filtered', roomSpotGrid(null, 0, 0, 6, 6).length, 36);
check('…and a degenerate hull is not a filter either',
  roomSpotGrid([[0, 0], [1, 1]], 0, 0, 6, 6).length, 36);

// --- [3] the flatness gate ---------------------------------------------------
console.log('\n[3] SPOT_FLAT_M — the 12 cm, measured against the height data');
check('the tolerance is the ray version\'s 0.12 m', SPOT_FLAT_M, 0.12);
const HALF_W = 0.5 * 4 * SPOT_SPREAD;          // 1.56 m, the raster half-width
check('the raster half-width of a 4 m room is 1.56 m', HALF_W, 1.56);
/** A plane rising `slope` metres per metre in x, read at a stand. */
const rise = (slope, p) => slope * p.x;
const keptAt = (slope) => rect.filter(
  (p) => Math.abs(rise(slope, p) - rise(slope, { x: -2 })) <= SPOT_FLAT_M).length;
check('a flat plot keeps every stand (the built case, § G5)', keptAt(0), 36);
check('a 0.05 m/m slope (2.9°) still keeps them all: 1.56 · 0.05 = 0.078',
  keptAt(0.05), 36);
check('a 0.10 m/m slope (5.7°) drops the two outer columns: 1.56 · 0.10 = 0.156',
  keptAt(0.10), 24);

// --- [4] the furniture -------------------------------------------------------
console.log('\n[4] furnitureUse — the OBJECT is measured, the floor is data');
check('the seat window is 0.25 … 0.70 m over the floor',
  [SEAT_MIN_M, SEAT_MAX_M], [0.25, 0.70]);
check('a body needs 1.6 m by 0.7 m', [LIE_LENGTH_M, LIE_WIDTH_M], [1.6, 0.7]);
check('a chair (0.45, 0.5 x 0.5) is a seat', furnitureUse(0, 0.45, 0.5, 0.5), 'sit');
check('a bench (0.45, 1.8 x 0.5) is a seat — too narrow to lie on',
  furnitureUse(0, 0.45, 1.8, 0.5), 'sit');
check('a bed (0.55, 2.0 x 1.4) is a place to lie',
  furnitureUse(0, 0.55, 2.0, 1.4), 'lie');
check('…whichever way round its sides are given',
  furnitureUse(0, 0.55, 1.4, 2.0), 'lie');
check('a table (0.75) is neither', furnitureUse(0, 0.75, 1.2, 0.8), null);
check('a rug (0.02) is neither', furnitureUse(0, 0.02, 2.0, 1.4), null);
check('the seat window is inclusive at the bottom',
  furnitureUse(0, 0.25, 0.5, 0.5), 'sit');
check('…and at the top', furnitureUse(0, 0.70, 0.5, 0.5), 'sit');
check('0.24 is under it', furnitureUse(0, 0.24, 0.5, 0.5), null);
check('0.71 is over it', furnitureUse(0, 0.71, 0.5, 0.5), null);
check('exactly 1.6 x 0.7 is a bed', furnitureUse(0, 0.5, 1.6, 0.7), 'lie');
check('1.59 long is a seat', furnitureUse(0, 0.5, 1.59, 0.7), 'sit');
check('THE FLOOR MOVES WITH THE ROOM: the same chair on storey 1 (floor 2.90)',
  furnitureUse(2.90, 3.35, 0.5, 0.5), 'sit');
check('…and measured against zero it would be nothing at all',
  furnitureUse(0, 3.35, 0.5, 0.5), null);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
