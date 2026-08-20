/**
 * Smoke run for the MAP's "Rooms" view — the pure math behind
 * `frontend/src/tabs/map/roomShapes.ts`, which puts the floor plan's room
 * hulls onto the world map so a place can be lined up with the painted ground.
 *
 * Usage:  node scripts/smoke_map_room_shapes.mjs
 *         (bundles the modules with esbuild — a Vite dependency, already
 *          installed; no bundler config, no jsdom, no server)
 *
 * Sibling of `smoke_plan_boundary_edit.mjs` and written to the same rule: every
 * expected number below is derived BY HAND from the two contracts, never
 * recorded from the current output. What is deliberately NOT covered is the
 * drawing — the SVG clip against the boundary, the fill opacities and the
 * label threshold are visual questions this file could only photograph.
 *
 * ===========================================================================
 * [1] THE TWO TURNS, IN ORDER
 * ===========================================================================
 * A room hull travels through TWO rotations about TWO different centres, and
 * getting the order or a centre wrong still produces a plausible-looking
 * rectangle somewhere else on the map — which is why it is pinned by hand.
 *
 *   1. the ROOM's own `rotation` about its RECT CENTRE (contract v6 addendum,
 *      `planGeometry.roomToLocal`): room-local metres -> LOCATION-local metres
 *   2. the LOCATION's `yaw_deg` about the PIN (§ A1.1, `mapMath.localToWorld`):
 *      location-local metres -> WORLD metres
 *
 * Both use the ONE sense of § A1.1 (`world_geometry.local_to_world`,
 * three.js `rotation.y = +rad θ`):
 *
 *      x' = cx + lx·cos θ + lz·sin θ
 *      z' = cz − lx·sin θ + lz·cos θ
 *
 * THE HAND CASE (the one the module docstring carries): a 4 × 2 m room whose
 * min corner is (1, 1), `rotation` 90, in a location pinned at (100, 50) with
 * `yaw_deg` 90.
 *
 *   room-local hull (the implicit rectangle, clockwise, edges 0=N 1=E 2=S 3=W)
 *       [[0,0], [4,0], [4,2], [0,2]]
 *   translated by the min corner (1,1):
 *       [[1,1], [5,1], [5,3], [1,3]]
 *   rect centre: (1 + 4/2, 1 + 2/2) = (3, 2)
 *
 *   step 1 — rotateAbout(·, (3,2), 90).  cos 90 = 0, sin 90 = 1, so
 *       x' = 3 + lz        z' = 2 − lx        (lx, lz relative to the centre)
 *     (1,1): lx=−2, lz=−1  ->  x' = 3 + (−1) = 2,  z' = 2 − (−2) = 4  -> (2,4)
 *     (5,1): lx=+2, lz=−1  ->  x' = 3 + (−1) = 2,  z' = 2 − (+2) = 0  -> (2,0)
 *     (5,3): lx=+2, lz=+1  ->  x' = 3 + (+1) = 4,  z' = 2 − (+2) = 0  -> (4,0)
 *     (1,3): lx=−2, lz=+1  ->  x' = 3 + (+1) = 4,  z' = 2 − (−2) = 4  -> (4,4)
 *   location-local hull:  [[2,4], [2,0], [4,0], [4,4]]
 *   SANITY, without arithmetic: the room was 4 m wide (x) and 2 m deep (z);
 *   after a quarter turn it must be 2 m wide and 4 m deep — x spans 2…4, z
 *   spans 0…4.  ✔  And its centre is unmoved: ((2+4)/2, (0+4)/2) = (3, 2).  ✔
 *
 *   step 2 — localToWorld(100, 50, 90, ·).  cos 90 = 0, sin 90 = 1, so
 *       x = 100 + lz       z = 50 − lx
 *     (2,4) -> x = 104, z = 48
 *     (2,0) -> x = 100, z = 48
 *     (4,0) -> x = 100, z = 46
 *     (4,4) -> x = 104, z = 46
 *   WORLD hull:  [[104,48], [100,48], [100,46], [104,46]]
 *   SANITY: the pin turns it back a quarter, so it must be 4 m in x and 2 m in
 *   z again — x spans 100…104, z spans 46…48.  ✔  The two turns are 90 + 90 =
 *   half a turn in total, and a rectangle turned 180° covers the same ground
 *   as the unturned one; that is exactly what the next case shows.
 *
 * THE SAME ROOM WITHOUT ITS OWN TURN, same location:
 *   location-local hull is just the translation:  [[1,1], [5,1], [5,3], [1,3]]
 *   localToWorld(100, 50, 90, ·):
 *     (1,1) -> (101, 49)   (5,1) -> (101, 45)
 *     (5,3) -> (103, 45)   (1,3) -> (103, 49)
 *   -> [[101,49], [101,45], [103,45], [103,49]] — 2 m in x, 4 m in z, i.e.
 *   turned ONCE. Against the case above (4 m in x, 2 m in z) that is the proof
 *   the room's own rotation is applied and is applied about the ROOM's centre:
 *   both hulls share the location, the pin and the yaw and differ only in it.
 *
 * THE PIN IS AN ARGUMENT, NOT A FIELD — while a footprint is dragged the
 * outline follows the cursor and the rooms have to follow it in the same
 * frame. Moving the pin by (+7, −3) must move every world point by exactly
 * that, whatever the yaw:  [[111,45], [107,45], [107,43], [111,43]]  for the
 * first case, which is the previous list + (7, −3) per point.
 *
 * ===========================================================================
 * [2] WHAT IS NOT A SHAPE ON THIS MAP
 * ===========================================================================
 *   * THE YARD (§ A13a) carries no rectangle at all — its surface IS the
 *     location boundary — so `hasRect` is false and it has no hull to draw.
 *   * ANOTHER STOREY. The map is a top-down view of the GROUND; drawing a
 *     first floor over it would say two things about one square metre.
 *     `level` absent means 0 (the ground floor), so a room without one is
 *     drawn and a `level: 1` room is not.
 *   * A room with a DRAWN `outline` is a shape and uses it instead of the
 *     implicit rectangle (`outlineOf`) — the outline is room-local metres
 *     spanning 0…w / 0…d, so it rides the same two turns.
 *
 * ===========================================================================
 * [3] THE FLOOR COLOUR
 * ===========================================================================
 * A room floor is a kind of the SURFACE-TEXTURE library (`surfaces.floor`),
 * and so is the material a terrain type wears (`TerrainType.surface`, said out
 * loud since 2026-08-16). The catalog therefore answers first: a room of
 * painted-water floor comes out in the exact colour the painted water beside
 * it has, and a misplaced shore reads as two COLOURS instead of two shades.
 *   * catalog hit          -> the catalog's colour
 *   * no type wears it     -> the small built-floor table (`FLOOR_KIND_COLORS`)
 *   * nobody knows it, or the room names no floor at all -> the fallback grey
 * A type without a `surface` wears the renderers' default ground and names no
 * material, so it contributes nothing to the fold; two types wearing the same
 * material is legal and the first one wins, because a material has ONE colour.
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));

async function loadModules() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'roomshapes-smoke-'));
  try {
    const file = join(dir, 'entry.mjs');
    await esbuild.build({
      stdin: {
        contents: [
          "export { FLOOR_FALLBACK_COLOR, FLOOR_KIND_COLORS, floorColor,"
          + " polyBBox, roomShapesWorld, surfaceColorMap } from"
          + " './frontend/src/tabs/map/roomShapes'",
        ].join('\n'),
        resolveDir: ROOT,
        loader: 'ts',
      },
      outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
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

const {
  FLOOR_FALLBACK_COLOR, FLOOR_KIND_COLORS, floorColor, polyBBox,
  roomShapesWorld, surfaceColorMap,
} = await loadModules();

/** The room of the hand case: 4 × 2 m at min corner (1,1). */
const room = (extra = {}) => ({
  id: 'hall', name: 'Hall',
  layout: { x: 1, y: 1, w: 4, d: 2, ...extra },
});
const polyOf = (shapes) => shapes.map((s) => s.poly);

console.log('[1] the two turns, in order');
check('room rotation 90 + location (100,50) yaw 90',
  polyOf(roomShapesWorld([room({ rotation: 90 })], 100, 50, 90)),
  [[[104, 48], [100, 48], [100, 46], [104, 46]]]);
check('the same room WITHOUT its own turn is turned once, not twice',
  polyOf(roomShapesWorld([room()], 100, 50, 90)),
  [[[101, 49], [101, 45], [103, 45], [103, 49]]]);
check('at pin (0,0) yaw 0 the hull is the plain translation',
  polyOf(roomShapesWorld([room()], 0, 0, 0)),
  [[[1, 1], [5, 1], [5, 3], [1, 3]]]);
check("the room's turn alone (yaw 0) turns it about the ROOM centre (3,2)",
  polyOf(roomShapesWorld([room({ rotation: 90 })], 0, 0, 0)),
  [[[2, 4], [2, 0], [4, 0], [4, 4]]]);
check('the pin is an argument: +7/−3 moves every world point by +7/−3',
  polyOf(roomShapesWorld([room({ rotation: 90 })], 107, 47, 90)),
  [[[111, 45], [107, 45], [107, 43], [111, 43]]]);
check('a quarter turn swaps the bounding box sides (4×2 -> 2×4)',
  (() => {
    const bb = polyBBox(roomShapesWorld([room({ rotation: 90 })], 0, 0, 0)[0].poly);
    return [bb.maxX - bb.minX, bb.maxZ - bb.minZ];
  })(), [2, 4]);
check('and the pin turns it back (2×4 -> 4×2)',
  (() => {
    const bb = polyBBox(roomShapesWorld([room({ rotation: 90 })], 100, 50, 90)[0].poly);
    return [bb.maxX - bb.minX, bb.maxZ - bb.minZ];
  })(), [4, 2]);

console.log('[2] what is not a shape on this map');
check('the yard has no rectangle and therefore no hull',
  roomShapesWorld([{ id: 'yard', layout: { props: [] } }], 0, 0, 0), []);
check('a first-floor room is not drawn on the ground map',
  roomShapesWorld([room({ level: 1 })], 0, 0, 0), []);
check('an absent level IS the ground floor',
  polyOf(roomShapesWorld([room()], 0, 0, 0)),
  [[[1, 1], [5, 1], [5, 3], [1, 3]]]);
check('level 1 is drawn when level 1 is asked for',
  polyOf(roomShapesWorld([room({ level: 1 })], 0, 0, 0, 1)),
  [[[1, 1], [5, 1], [5, 3], [1, 3]]]);
check('a drawn outline replaces the implicit rectangle and rides both turns',
  // A triangle in room-local metres; at pin (100,50) yaw 90 the § A1.1 map is
  // x = 100 + lz, z = 50 − lx, applied to (1,1), (5,1), (1,3).
  polyOf(roomShapesWorld([room({ outline: [[0, 0], [4, 0], [0, 2]] })],
    100, 50, 90)),
  [[[101, 49], [101, 45], [103, 49]]]);
check('no rooms at all is no shapes, not a crash',
  [roomShapesWorld(undefined, 0, 0, 0), roomShapesWorld(null, 0, 0, 0),
    roomShapesWorld([], 0, 0, 0)], [[], [], []]);
check('the two flags travel with the shape',
  roomShapesWorld([{ id: 'shore', name: 'Shore',
    layout: { x: 0, y: 0, w: 2, d: 2, always_visible: true,
      surfaces: { floor: ' water ' } } }], 0, 0, 0)
    .map((s) => [s.id, s.name, s.floor, s.open]),
  [['shore', 'Shore', 'water', true]]);
check('a room without a name falls back to its id, and a closed room is closed',
  roomShapesWorld([{ id: 'r1', layout: { x: 0, y: 0, w: 1, d: 1 } }], 0, 0, 0)
    .map((s) => [s.name, s.floor, s.open]),
  [['r1', '', false]]);

console.log('[3] the floor colour');
const catalog = [
  { kind: 'water', color: '#4a90d9', surface: 'water' },
  { kind: 'lake', color: '#123456', surface: 'water' },
  { kind: 'path', color: '#b08968' },
  { kind: 'moss', color: '#0abc12', surface: 'deep_forest' },
];
const colors = surfaceColorMap(catalog);
check('a type without a surface names no material',
  colors, { water: '#4a90d9', deep_forest: '#0abc12' });
check('the catalog wins — the room is the colour of the painted ground',
  floorColor('water', colors), '#4a90d9');
check('a material no type wears comes from the built-floor table',
  floorColor('wooden_floor', colors), FLOOR_KIND_COLORS.wooden_floor);
check('an unknown kind is grey, not a guess',
  floorColor('linoleum_1787', colors), FLOOR_FALLBACK_COLOR);
check('a room that names no floor at all is grey too',
  [floorColor('', colors), floorColor('   ', colors)],
  [FLOOR_FALLBACK_COLOR, FLOOR_FALLBACK_COLOR]);
check('without a catalog the table still answers',
  [floorColor('water'), floorColor('grass')], ['#4a90d9', '#6a994e']);
check('an empty catalog folds to nothing', surfaceColorMap([]), {});

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
