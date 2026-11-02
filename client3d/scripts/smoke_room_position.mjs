/** Task 98: the same rotated two-room fixture as Core and Godot placement.
 * Hand derivations and literal expectations: native/fixtures/placement/stale_positions.json.
 * Usage: node client3d/scripts/smoke_room_position.mjs
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { build } from 'esbuild';
import { mainFunctions } from './mainFunction.mjs';

const fixture = JSON.parse(readFileSync(new URL('../../native/fixtures/placement/stale_positions.json', import.meta.url)));
const built = await build({ stdin: { contents: `export * from './client3d/src/game/npcPlacement';
export * from './client3d/src/game/placement'; export * from './client3d/src/scene/sceneView';
export { avatarWaitsForPlace } from './client3d/src/game/readiness';
export { worldToLocalXZ } from '@anima/scene-render'; export * as THREE from 'three';`,
  resolveDir: process.cwd(), loader: 'ts' }, bundle: true, platform: 'node', format: 'esm', write: false });
const m = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
const tile = {
  center: fixture.center, yaw: fixture.yaw, width: 12, isBuilding: true, fade: 1, levelFilter: 0,
  alwaysVisibleRooms: new Set(), roomCenters: new Map(Object.entries(fixture.roomCenters)),
  roomLevels: new Map([['r-hall', 0], ['r-bed', 0]]),
  roomFloors: new Map(Object.entries(fixture.hulls).map(([id, hull]) => [id, { hull }])),
  roomMarkers: new Map(), roomSitSpots: new Map(), roomLieSpots: new Map(), corridors: [],
};
const roomStandY = (_room, lx, lz) => (64 + lz) / 32 + (128 - lx) / 64 + .01;
const ctx = { locId: 'loc-inn', near: true, roomOf: () => fixture.room, shownOf: () => undefined,
  seatOf: () => undefined, roomStandY, groundY: () => 4, targetCentre: () => undefined };
const near = (got, want) => {
  for (const key of ['x', 'y', 'z']) assert(Math.abs(got[key] - want[key]) < 1e-8, `${key}: ${got[key]} != ${want[key]}`);
};
for (const c of fixture.cases) {
  const lines = [];
  const diagnostics = new m.RoomPositionDiagnostics(line => lines.push(line));
  const row = { name: 'demo', room_id: fixture.room, location_id: 'loc-inn', pos: c.pos };
  for (let poll = 0; poll < 4; poll++) {
    const [placed] = m.placeAtLocation([row], tile, { ...ctx,
      stalePos: (name, room, point) => diagnostics.report('loc-inn', name, room, point) });
    assert.equal(placed.branch, c.branch, c.label);
    near(placed.pos, c.expected);
    assert.equal(placed.inRoom, fixture.room);
  }
  assert.equal(lines.length, c.logs, c.label);

  // Run the production boot arrival and cooperating placement closures. Only rendering/model IO is substituted.
  tile.fade = 0;
  tile.roomGroups = new Map();
  const map = { avatar: 'demo', characters: [row] };
  const npcLines = [], arrivalDiagnostics = new m.RoomPositionDiagnostics(line => npcLines.push(line));
  let rendered;
  const npcs = { hasOwnMotion: () => false, update: states => { rendered = states[0]; },
    yawOf: () => 0, faceTowards() {} };
  const run = await mainFunctions(['computeNpcPlacements', 'computeNpcStates', 'placeAvatarOnArrival'], {
    ...m, avatarName: 'demo', lastMap: map, firstMap: map, mapStamp: 0,
    residency: new Map([['loc-inn', { tile, ring: 'near', ready: true }]]),
    hiddenChars: new Set(), shownPlacement: new Map(), roomOf: new Map([['demo', fixture.room]]),
    npcs, roomPositionDiagnostics: arrivalDiagnostics, places: new Map(), api: { mapMetaOf: () => undefined },
    manualPropRelease: false, travellerState: () => null, slotFor: () => undefined,
    roomStandY: (_tile, ...args) => roomStandY(...args),
    awaitArrivalMount: async () => 'loc-inn', openLocationId: 'loc-inn',
    followAvatarStorey: (t, room) => { assert.equal(room, fixture.room); t.levelFilter = 0; },
    openable: () => true, applyTileFade() {}, applyLevelDisplay() {}, applyRoomVisibility() {}, refreshOpenBadge() {},
    reportedYaw: 0, positionYaw: value => value,
  });
  await run.placeAvatarOnArrival();
  near(rendered.pos, c.expected);
  assert.equal(rendered.snap, true);
  assert.equal(tile.fade, 1);
  for (let poll = 0; poll < 3; poll++) run.computeNpcStates(map);
  assert.equal(npcLines.length, c.logs, `arrival and later polls: ${c.label}`);
  assert.equal(row.room_id, fixture.room);
}
const concave = { ...tile, center: { x: 0, y: 0, z: 0 }, yaw: 0, levelFilter: 1,
  roomCenters: new Map([['upstairs', { x: 1, y: 7, z: 1 }]]), roomLevels: new Map([['upstairs', 1]]),
  roomFloors: new Map([['upstairs', { hull: [[0,0],[4,0],[4,2],[2,2],[2,4],[0,4]] }]]) };
const [notch] = m.placeAtLocation([{ name: 'demo', pos: { x: 3, z: 3 } }], concave,
  { ...ctx, roomOf: () => 'upstairs', roomStandY: () => 7 });
assert.equal(notch.branch, 'centre');
near(notch.pos, { x: 1, y: 7, z: 1 });
assert.equal(notch.hidden, false);
console.log('room position: geometry, once-only logs, production arrival/polls and concave upstairs room passed');
