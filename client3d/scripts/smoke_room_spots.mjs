#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/room_spots.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_room_spots.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
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
