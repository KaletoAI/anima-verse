/** Task 77: real main.ts route projection and NpcManager playback on an upper floor. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { mainFunction } from './mainFunction.mjs';
const bundled = await build({ stdin: { contents: `export { NpcManager } from './client3d/src/scene/npcs';
  export { Figure, setClipRootPath } from './client3d/src/scene/figures';
  export * as motion from './client3d/src/game/propActionMotion';
  export * as walk from './client3d/src/game/walk';
  export * as echo from './client3d/src/game/posEcho';
  export * as path from './client3d/src/scene/travelPath'; export * as THREE from 'three';`,
  resolveDir: fileURLToPath(new URL('../..', import.meta.url)), loader: 'ts' },
  bundle: true, loader: { '.css': 'empty' }, write: false, platform: 'node', format: 'esm' });
const { NpcManager, Figure, setClipRootPath, THREE, path, motion, walk, echo } = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);
const read = name => JSON.parse(readFileSync(new URL(`../../native/fixtures/propactions/${name}`, import.meta.url)));
const map = read('worldmap_approach.json');
const char = map.characters[0];
let motionStatus = 'approaching';
const routeFor = await mainFunction('travellerState', {
  avatarName: char.name, manualPropGate: { withdrawn: () => false },
  ownedPropRun: () => ({ status: motionStatus }), api: { mapMetaOf: () => ({ parsedAt: performance.now() }) },
  ...path, ageAtReceiptS: () => 0, THREE,
  groundY: () => 0, terrainGround: { heightAt: () => 0 },
  residency: new Map(), roomOf: new Map([[char.name, 'r-props']]),
  tileAt: () => ({}), worldToTile: (_tile, x, z) => ({ x, z }), roomStandY: () => 9.4,
});
for (const floor of [9.4, undefined, 0]) {
  char.travel.floor_y = floor;
  const state = routeFor(char, 1, map);
  assert.equal(state.pos.y, floor ?? 9.4, 'initial placement uses journey floor or room floor');
  assert.equal(state.route.floorY, floor ?? 9.4, 'route carries floor to frame ticks');
  const mgr = new NpcManager(null, { syncCounters: {}, errWindow: { t: [], e: [] } });
  const root = new THREE.Group();
  const npc = { name: char.name, root, target: new THREE.Vector3(), figure: null,
    sprite: null, label: {}, labelName: {}, labelActivity: {}, waypoints: [],
    interaction: null, entry: null, bubbleUntil: 0, route: null, travelLine: null, travelKey: '' };
  mgr.npcs.set(char.name, npc); mgr.update([state]);
  npc.route.receivedAt = performance.now() - 5000;
  mgr.setGroundHeight(() => 0); mgr.setRoomStandAt(() => 9.4);
  mgr.tick(0, 10);
  assert.equal(root.position.y, floor ?? 9.4, 'exact route never falls to terrain');
  assert.ok(root.position.x > .9 && root.position.x < 1.1, 'walk advances on the polyline');
}
motionStatus = 'active'; char.travel.floor_y = 9.4;
assert.equal(routeFor(char, 2, map).route.exact, true, 'active private state cannot turn the older owned approach into an overland journey');
assert.equal(routeFor(char, 2, map).pos.y, 9.4);
// Arrival bypasses any ordinary walk-to-sit bridge. A failed live entry also
// yields to authoritative place state rather than permanently hiding the avatar.
const mgr = new NpcManager(null, { syncCounters: {}, errWindow: { t: [], e: [] } });
const root = new THREE.Group();
const template = new THREE.Group(), hips = new THREE.Bone(); hips.name = 'Hips'; template.add(hips);
const bridgeClip = new THREE.AnimationClip('fixture-sit-down', 2, [
  new THREE.VectorKeyframeTrack('Hips.position', [0, 2], [0, 1, 0, 0, .5, 0]),
]);
setClipRootPath(bridgeClip, { times: new Float32Array([0, 2]), xz: new Float32Array([0, 0, 0, -1]) });
const figure = new Figure({ name: 'upper', template, scale: 1, height: 1.7,
  clips: [bridgeClip, ...['walking', 'sitting'].map(name => new THREE.AnimationClip(name, 1, []))],
  tier: 'full', noClips: false, libraryFits: true });
root.add(figure.root);
const npc = { name: char.name, root, figure, target: new THREE.Vector3(), waypoints: [], route: null,
  entry: null, entryBlocked: false, propCommitKey: '', activity: '', labelActivity: {}, labelName: {},
  settle: null, travelling: false, interaction: null, travelLine: null, travelKey: '', label: {} };
mgr.npcs.set(char.name, npc);
const active = read('worldmap_active.json').characters[0];
const state = { char: active, pos: new THREE.Vector3(2, 9.529, 0), snap: true, hidden: false,
  committedPropKey: 'bench#0#sitting', stamp: 2 };
for (const failedEntry of [false, true]) {
  npc.propCommitKey = ''; npc.entryBlocked = false;
  npc.entry = failedEntry ? { spec: read('worldmap_entry.json').characters[0].prop_action_entry,
    played: false, failed: true } : null;
  figure.play('walking');
  mgr.update([state]);
  assert.equal(npc.entry, null, 'authoritative held place ends entry');
  assert.equal(npc.entryBlocked, false, 'held place releases failed entry gate');
  assert.equal(root.visible, true);
  assert.equal(root.position.y, 9.529);
  assert.equal(figure.current.getClip().name, 'sitting');
  assert.equal(figure.bridging, false);
}
const entryChar = read('worldmap_entry.json').characters[0];
entryChar.prop_action_entry.access.y = 9.4; entryChar.prop_action_entry.anchor.y = 9.529;
mgr.update([{ char: entryChar, pos: new THREE.Vector3(2, 9.4, -1), stamp: 3, entryAt: performance.now() }]);
mgr.tick(0, 10);
assert.equal(root.position.y, 9.4, 'upper bridge keeps its floor access');
assert.equal(npc.entry.played, true, 'measured sit-down actually plays');
assert.ok(Math.abs(figure.current.time - 1) < .02, 'measured clip reaches halfway');
mgr.update([{ ...state, stamp: 4 }]);
assert.equal(root.position.y, 9.529, 'bridge completion takes held anchor');
assert.equal(figure.bridging, false);
assert.equal(figure.current.getClip().name, 'sitting');

let serverDrive = 0, terminalPoint = null, ownedRun = { status: 'active' };
const applyDriver = await mainFunction('applyDriver', {
  pollIsStale: () => false, ownCorrectionAt: 0, ownSeatChangeAt: 0,
  manualPropGate: { pending: false, withdrawn: () => false }, avatarName: char.name,
  ownedPropRun: () => ownedRun, ownedPropJourney: 'upper',
  avatarDriver: echo.avatarDriver, avatarCancelled: echo.NO_CANCEL, posSession: 'upper',
  THREE, groundY: () => 0, roomFloorY: () => 9.41, tileAt: () => ({}),
  npcs: { setServerDriven: (_name, _on, how) => { terminalPoint = how.arriveAt; } },
  avatarDrive: { kind: 'PLAYER' }, enterServerDrive: () => serverDrive++,
}, ['avatarDrive']);
applyDriver({ characters: [active] }, 1);
assert.equal(serverDrive, 1, 'active held action keeps server rendering until release');
assert.equal(applyDriver.snapshot().avatarDrive.kind, 'SERVER', 'driver remembers ownership so terminal state can hand back control');
ownedRun = null;
applyDriver({ characters: [active] }, 2);
assert.equal(applyDriver.snapshot().avatarDrive.kind, 'PLAYER');
assert.equal(terminalPoint.y, 9.41, 'terminal handoff retains the indoor floor');

const manualGate = motion.createManualPropGate();
let finishCancel, requests = 0;
const released = new Set();
const release = await mainFunction('releaseOwnedProp', {
  avatarName: char.name, ownedPropRun: () => ({ execution_id: 'upper' }),
  manualPropGate: manualGate, lastMap: { characters: [active] }, ownedPropJourney: 'upper-journey',
  api: { cancelPropAction: () => { requests++; return new Promise(resolve => { finishCancel = resolve; }); } },
  releasedPropExecutions: released, manualPropRelease: false, ownSeatChangeAt: 0,
  avatarCancelled: null, avatarDrive: { kind: 'SERVER', j: 'upper-journey' }, npcs: mgr,
  avatarSeated: true, seatedKey: 'bench#0', refreshPropMotion: async () => {},
  uiActions: { toast: message => { throw new Error(message); } },
}, ['avatarDrive', 'avatarSeated', 'manualPropRelease']);
let releasing;
const steer = await mainFunction('engine.addFrameHook:manualInput', {
  getGameState: () => ({ mode: 'embodied' }), pendingSnap: false,
  walkDir: walk.walkDir, engine: { keysDown: () => new Set(['w']), yaw: 0 }, route: null,
  manualPropGate: manualGate, propMutationPending: false, propStateUncertain: false,
  propPreparation: { pending: false }, ownedPropRun: () => ({ status: 'active' }),
  releaseOwnedProp: () => { releasing = release(); return releasing; },
});
steer(.016); steer(.016);
assert.equal(manualGate.pending, true);
assert.equal(released.size, 0, 'unanswered cancellation keeps ownership');
finishCancel({ status: 'cancelled' }); await releasing;
assert.equal(requests, 1);
assert.equal(manualGate.pending, false);
assert.equal(manualGate.withdrawn('upper-journey'), true);
assert.deepEqual(release.snapshot(), { avatarDrive: { kind: 'PLAYER' }, avatarSeated: false, manualPropRelease: true });
assert.equal(mgr.propEntryUnavailable(char.name), false);


const correct = await mainFunction('correctTo', {
  avatarName: char.name, npcs: mgr, THREE, ownCorrectionAt: 0,
  clearApproach: () => {}, readinessDeps: {}, readinessState: {},
  tileAt: () => ({}), roomFloorY: () => 9.41, groundY: () => 0,
  CORRECT_WALK_M: 8, CORRECT_MS: 3000, correction: null,
  cancelRoute: () => {}, walkIn: null, reportedPos: null, posDirty: false,
});
correct({ x: 0, z: -1 });
assert.equal(npc.target.y, 9.41, 'post-release correction stays on the room floor');

console.log('prop action storey: PASS (upper approach/bridge/direct seat, failed-entry recovery, ownership and awaited release)');
