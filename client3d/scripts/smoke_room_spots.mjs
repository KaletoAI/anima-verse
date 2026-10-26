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
 * floor was a stand. Storey 0 has no plate to ray any more (§ A16.9), so
 * the shape comes from `floor_plan` (§ A16.9) and the height from the one
 * height function at the point being asked about. The rules under test are the
 * pure half of that, `client3d/src/game/ground.ts` and
 * `client3d/src/game/roomSpots.ts`; the lookups around them live in
 * `scene/tiles.deriveRoomSpots` / `roomFloorAt` / `roomStandY`.
 *
 * SHARED VECTORS — `shared/test-vectors/room_spots.json` (plan Task 29). The
 * input -> value cases of [1], [2], [4], [6] and [7] run from that file, which
 * the native client's C# tests read too. Dispatch conventions:
 *   roomSpotConstants()   -> {SPOT_GRID, SPOT_SPREAD, SEAT_MIN_M, SEAT_MAX_M,
 *                             LIE_LENGTH_M, LIE_WIDTH_M} (only the expected
 *                             keys are compared)
 *   roomSpotGridHead(hull, cx, cz, w, d) -> {length, first, firstDist}: the
 *                             raster's size, its first (nearest) point and that
 *                             point's distance from (cx, cz)
 *   roomFloorLadder(datum, baked, declared, terrain): `declared` null = none
 *                             (undefined in TS); a non-finite terrain is
 *                             {"$number": "NaN"}
 *   roomStandLadder(floorY, centreY): `centreY` null = none (undefined in TS)
 *   roomSpotsOfValue(input): `roomSpotsOf` with `floorAt` / `baseFloorAt` as
 *                             [a, b, c] = a·lx + b·lz + c over TILE-LOCAL metres
 * WHAT STAYS HERE: the `pointInPolygon` cross-checks (inside / outside the
 * hull) and the `undefined` ring of [1] (JSON has none; `null` is the vector).
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
 * [2] `roomSpotGrid` — the fallback for a centre that lies outside its room
 * ============================================================================
 * `SPOT_GRID` = 6 rows and columns over `SPOT_SPREAD` = 0.78 of the room's
 * BOUNDING BOX, around its centre — the very raster of the ray version — with
 * the polygon test where the ray hit used to be. Ordered by distance from the
 * centre, nearest first.
 *
 * SINCE T4 IT HANDS OUT NO STANDS ANY MORE: where a figure without a place
 * marker stands in a room is the SERVER's word (§ A1.4, `scripts/smoke_room_stand.py`),
 * and the client draws `pos`. What is left of the raster is the ONE reader
 * `deriveRoomSpots` still has for it — the interior point a room needs when
 * its own area centroid falls outside the hull, which is case (b) below.
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
 * ============================================================================
 * [6] THE ROOM FLOOR AND THE STANDING HEIGHT — `roomFloorLadder`,
 *     `roomStandLadder` (the pure halves of `tiles.roomFloorAt` / `roomStandY`)
 * ============================================================================
 * roomFloorLadder(datum, baked, declared, terrain), WORLD metres, `declared`
 * tile-local over the datum:
 *   (2, 2.5, 0.3, 1)     -> 2.5   the room's own lattice answers first
 *   (2, null, 0.3, 1)    -> 2.3   else the declaration: 2 + 0.3
 *   (2, null, 0, 5)      -> 2     a declaration of 0 is a VALUE: 2 + 0, the
 *                                 terrain 5 is never asked
 *   (2, none, 1.7)       -> 1.7   no declaration: the terrain
 *   (2, none, −0.5)      -> −0.5  …even below the datum
 *   (2, none, NaN)       -> 2     a sampler with nothing to say: the datum
 * roomStandLadder(floorY, centreY): the floor + WALK_CLEARANCE_M 0.01, else
 * the room's stand centre (a corridor has no floor of its own), else null:
 *   (2.3, 9)   -> 2.31    (0, 1)   -> 0.01   a floor at 0 is a floor
 *   (none, 4.81) -> 4.81  (none, none) -> null
 *
 * ============================================================================
 * [7] THE STANDS OF ONE ROOM — `roomSpotsOf` (the core of `deriveRoomSpots`)
 * ============================================================================
 * (a) THE TURNED RECTANGLE: the room of [2](a), hull (−4,−4) (0,−4) (0,−1)
 *     (−4,−1), on a tile at (10, 1, 20) turned by yaw π/2 (cos 0, sin 1), so
 *       tileToWorld(lx, lz) = (10 + lz, ·, 20 − lx)
 *       worldToTile(x, z)   = (lx, lz) = (20 − z, x − 10)
 *     rect = bbox centre (−2, −2.5), 4 × 3. The area centroid (−2, −2.5) is
 *     inside, so it is the centre. floorAt = 0.1·lx + 0.2·lz + 1.5:
 *       floorY = −0.2 − 0.5 + 1.5 = 0.8
 *       centre = (10 − 2.5, 0.8 + 0.01, 20 + 2) = (7.5, 0.81, 22)
 *     Four placed props (world boxes), judged by `furnitureUse(0.8, top, w, d)`:
 *       chair  (7, ·, 21)…(7.5, 1.25, 21.5)   0.45 over, 0.5 × 0.5 -> sit
 *              at (7.25, 1.26, 21.25)
 *       bed    (8, ·, 22)…(10, 1.35, 23.4)    0.55 over, 2 × 1.4   -> lie
 *              at (9, 1.36, 22.7)
 *       table  (6, ·, 23)…(7.2, 1.55, 23.8)   0.75 over            -> nothing
 *       stool  (6, ·, 20)…(6.4, 1.4, 20.4)    0.60 over, 0.4 × 0.4 -> sit
 *              at (6.2, 1.41, 20.2)
 *     -> sit [chair, stool] in prop order, lie [bed].
 *     Four markers, baseFloorAt = 0.1·lx + 0.2·lz + 1.4:
 *       m1 slots (8, 21), (9, 21), drop 0.4, offsetY 0.45: mean (8.5, 21) ->
 *          tile-local (20 − 21, 8.5 − 10) = (−1, −1.5) -> floor
 *          −0.1 − 0.3 + 1.4 = 1.0 -> 1.0 − 0.4 + 0.45 = 1.05
 *       m2 fixed                       -> null (left alone)
 *       m3 no slots                    -> null
 *       m4 slot (10, 20), no drop/offset: local (0, 0) -> 1.4
 * (b) THE L-SHAPED ROOM of [1](b)/[2](b) on an unturned tile at the origin:
 *     the centroid (2.2, 2.2) is outside, so the raster's first point
 *     (1.596, 2.532) is the centre; floorAt 0.3 -> centre (1.596, 0.31,
 *     2.532), rect (3, 3, 6, 6); no props, no markers.
 * (c) A SLIVER (0,0) (0.2,0) (0.2,0.1) (0,0.1) at (5, 0, 5): the rectangle is
 *     at least 0.5 m a side -> (0.1, 0.05, 0.5, 0.5); the centroid (0.1, 0.05)
 *     is inside -> centre (5.1, 0 + 0.01, 5.05).
 * (d) An EMPTY hull has no rectangle: no stands at all (null).
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
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

/** The modules under test, bundled: `roomSpots.ts` reads the tile frame from
 *  `scene/sceneView.ts` and `@anima/scene-render` — no `three`, no DOM. */
const entry = `
export * from './client3d/src/game/ground.ts';
export { pointInPolygon } from './client3d/src/game/polygon.ts';
export { roomSpotsOf } from './client3d/src/game/roomSpots.ts';
`;
const built = await build({
  stdin: { contents: entry, resolveDir: fileURLToPath(new URL('../..', import.meta.url)), loader: 'ts' },
  bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'error',
});
const ground = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  if (actual === expected) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

const { polygonCentroid, roomSpotGrid, pointInPolygon } = ground;
const num = (v) => (v !== null && typeof v === 'object' && '$number' in v ? Number(v.$number) : v);
const plane = (abc) => (u, v) => abc[0] * u + abc[1] * v + abc[2];

console.log('(vectors) shared/test-vectors/room_spots.json');
const vectors = runVectors(loadVectors('room_spots'), {
  polygonCentroid,
  roomSpotConstants: () => ({
    SPOT_GRID: ground.SPOT_GRID, SPOT_SPREAD: ground.SPOT_SPREAD,
    SEAT_MIN_M: ground.SEAT_MIN_M, SEAT_MAX_M: ground.SEAT_MAX_M,
    LIE_LENGTH_M: ground.LIE_LENGTH_M, LIE_WIDTH_M: ground.LIE_WIDTH_M,
  }),
  roomSpotGridHead: (hull, cx, cz, w, d) => {
    const grid = roomSpotGrid(hull, cx, cz, w, d);
    return { length: grid.length, first: grid[0] ?? null,
             firstDist: grid[0] ? Math.hypot(grid[0].x - cx, grid[0].z - cz) : null };
  },
  furnitureUse: ground.furnitureUse,
  roomFloorLadder: (datum, baked, declared, terrain) =>
    ground.roomFloorLadder(datum, baked, declared ?? undefined, num(terrain)),
  roomStandLadder: (floorY, centreY) => ground.roomStandLadder(floorY, centreY ?? undefined),
  roomSpotsOfValue: (input) => ground.roomSpotsOf({
    ...input, floorAt: plane(input.floorAt), baseFloorAt: plane(input.baseFloorAt),
  }),
});
passed += vectors.passed;
failed += vectors.failed;

// --- what JSON cannot carry, or a cross-check against another rule ----------
console.log('\n[1] polygonCentroid — the local cross-checks');
const L_ROOM = [[0, 0], [6, 0], [6, 2], [2, 2], [2, 6], [0, 6]];
check('…and the L room\'s centroid (2.2, 2.2) is OUTSIDE the room',
  pointInPolygon(2.2, 2.2, L_ROOM), false);
check('…nor an absent (undefined) ring', polygonCentroid(undefined), null);

console.log('\n[2] roomSpotGrid — every stand lies inside its hull');
const RECT = [[-4, -4], [0, -4], [0, -1], [-4, -1]];
check('…every one of the rectangle\'s 36 is inside the room',
  roomSpotGrid(RECT, -2, -2.5, 4, 3).every((p) => pointInPolygon(p.x, p.z, RECT)), true);
const lshape = roomSpotGrid(L_ROOM, 3, 3, 6, 6);
check('…the L room\'s nearest stand IS inside the room, unlike its centroid',
  pointInPolygon(lshape[0].x, lshape[0].z, L_ROOM), true);
check('…and every L stand is inside',
  lshape.every((p) => pointInPolygon(p.x, p.z, L_ROOM)), true);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
