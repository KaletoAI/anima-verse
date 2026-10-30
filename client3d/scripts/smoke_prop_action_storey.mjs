/** Task 77: real main.ts route projection and NpcManager playback on an upper floor. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { mainFunction } from './mainFunction.mjs';
const bundled = await build({ stdin: { contents: `export { NpcManager } from './client3d/src/scene/npcs';
  export { Figure, setClipRootPath } from './client3d/src/scene/figures';
  export { setClipBridgeLift } from './client3d/src/scene/bridgeLift';
  export * as motion from './client3d/src/game/propActionMotion';
  export * as walk from './client3d/src/game/walk';
  export * as echo from './client3d/src/game/posEcho';
  export * as path from './client3d/src/scene/travelPath'; export * as THREE from 'three';`,
  resolveDir: fileURLToPath(new URL('../..', import.meta.url)), loader: 'ts' },
  bundle: true, loader: { '.css': 'empty' }, write: false, platform: 'node', format: 'esm' });
const { NpcManager, Figure, setClipRootPath, setClipBridgeLift, THREE, path, motion, walk, echo } = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`);
const read = name => JSON.parse(readFileSync(new URL(`../../native/fixtures/propactions/${name}`, import.meta.url)));
const map = read('worldmap_approach.json');
const char = map.characters[0];
let motionStatus = 'approaching';
const routeFor = await mainFunction('travellerState', {
  avatarName: char.name, manualPropGate: { withdrawn: () => false },
  ownedPropRun: () => motionStatus ? ({ status: motionStatus }) : null,
  preparedPropJourney: null, propMutationPending: true, propStateUncertain: true, propPreparation: { pending: true }, api: { mapMetaOf: () => ({ parsedAt: performance.now() }) },
  ...path, poseClip: walk.poseClip, ageAtReceiptS: () => 0, THREE,
  groundY: () => 0, terrainGround: { heightAt: () => 0 },
  residency: new Map(), roomOf: new Map([[char.name, 'r-props']]),
  tileAt: () => ({}), worldToTile: (_tile, x, z) => ({ x, z }), roomStandY: () => 9.4, WALK_CLEARANCE_M: 0.01,
});
for (const floor of [9.4, undefined, 0]) {
  char.travel.floor_y = floor;
  const state = routeFor(char, 1, map);
  assert.equal(state.pos.y, floor === undefined ? 9.4 : floor + 0.01, 'initial placement uses journey floor (+ walking clearance) or room floor');
  assert.equal(state.route.floorY, floor === undefined ? 9.4 : floor + 0.01, 'route carries floor to frame ticks');
  // This loop also preserves exact public/NPC receipt-clock playback.
  state.route.ownedApproach = false;
  const mgr = new NpcManager(null, { syncCounters: {}, errWindow: { t: [], e: [] } });
  const root = new THREE.Group();
  const npc = { name: char.name, root, target: new THREE.Vector3(), figure: null,
    sprite: null, label: {}, labelName: {}, labelActivity: {}, waypoints: [],
    interaction: null, entry: null, bubbleUntil: 0, route: null, travelLine: null, travelKey: '' };
  mgr.npcs.set(char.name, npc); mgr.update([state]);
  npc.route.receivedAt = performance.now() - 5000;
  mgr.setGroundHeight(() => 0); mgr.setRoomStandAt(() => 9.4);
  mgr.tick(0, 10);
  assert.equal(root.position.y, floor === undefined ? 9.4 : floor + 0.01, 'exact route never falls to terrain');
  assert.ok(root.position.x > .9 && root.position.x < 1.1, 'walk advances on the polyline');
}
// Task 80: a future start holds even when the reported progress is ahead.
{
  const fresh = structuredClone(char);
  fresh.travel.starts_in_s = .75; fresh.travel.progress_m = 1;
  const mgr = new NpcManager(null, { syncCounters: {}, errWindow: { t: [], e: [] } });
  const root = new THREE.Group(); root.position.set(-3, 9.41, -2);
  const figure = new Figure({ name: 'fresh', template: new THREE.Group(), scale: 1, height: 1.7,
    clips: ['walking', 'standing', 'fixture-start-walk'].map(name => new THREE.AnimationClip(name, .2, [])),
    tier: 'full', noClips: false, libraryFits: true });
  root.add(figure.root);
  const npc = { name: char.name, root, figure, target: root.position.clone(), waypoints: [],
    entry: null, interaction: null, route: null, travelLine: null, travelKey: '',
    label: {}, labelName: {}, labelActivity: {}, bubbleUntil: 0 };
  mgr.npcs.set(char.name, npc); mgr.setPlayerDriven(char.name); mgr.setServerDriven(char.name, true);
  mgr.update([routeFor(fresh, 7, map)]);
  assert.equal(npc.route.catchUpRate, 0, 'future approach never catches up');
  mgr.tick(.1, 10);
  assert.equal(root.position.x, -3, 'future approach holds rendered start');
  assert.equal(figure.current.getClip().name, 'standing', 'fresh approach stands until departure');
  walk.setClipTransitions([{ from: walk.poseClip('standing'), to: walk.poseClip('walking'), kind: 'fixture-start-walk', accel: 0 }]);
  npc.route.receivedAt = performance.now() - 800;
  mgr.tick(1 / 60, 10);
  assert.equal(figure.current.getClip().name, 'fixture-start-walk', 'departure opens the holding stand-to-walk bridge');
  assert.equal(root.position.x, -3, 'holding bridge prevents the first walking step');
  mgr.tick(.25, 10); mgr.tick(1 / 60, 10);
  assert.ok(root.position.x > -3, 'walk begins after countdown and bridge');
  walk.setClipTransitions([]);
  root.position.set(-3, 9.41, -2); npc.route = null;
  const aged = routeFor(fresh, 8, map); aged.route.ageAtParsedS = .5;
  mgr.update([aged]);
  assert.equal(npc.route.catchUpRate, 0, 'aged but future adoption has no catch-up');
  assert.ok(performance.now() - npc.route.receivedAt >= 500, 'route retains poll age for departure clock');
  mgr.tick(0, 10); assert.equal(root.position.x, -3, 'remaining countdown still holds');
}

// The zero-time seat leg is rendered by the exit clip, then handed to the root once.
{
  const realPerformance = globalThis.performance;
  let now = 10000;
  globalThis.performance = { now: () => now };
  try {
    const mgr = new NpcManager(null, { syncCounters: {}, errWindow: { t: [], e: [] } });
    const root = new THREE.Group(); root.position.set(2, .129, 0);
    const exit = new THREE.AnimationClip('fixture-get-up', .5, []);
    setClipRootPath(exit, { times: new Float32Array([0, .5]), xz: new Float32Array([0, 0, 0, -.5]) });
    setClipBridgeLift(exit, { endLift: 0, firstContactS: .5 });
    const figure = new Figure({ name: 'switch', template: new THREE.Group(), scale: 1, height: 1.7,
      clips: [exit, ...['walking', 'standing', 'sitting'].map(name => new THREE.AnimationClip(name, 1, []))],
      tier: 'full', noClips: false, libraryFits: true });
    root.add(figure.root); figure.setYaw(0); figure.play('sitting');
    const npc = { name: char.name, root, figure, target: root.position.clone(), waypoints: [],
      entry: null, interaction: null, route: null, travelLine: null, travelKey: '',
      label: {}, labelName: {}, labelActivity: {}, bubbleUntil: 0 };
    mgr.npcs.set(char.name, npc); mgr.setPlayerDriven(char.name); mgr.setServerDriven(char.name, true);
    const release = await mainFunction('releaseSwitchedPropSeat', {
      preparedPropSeatExecution: 'old', ownedPropRun: () => ({ execution_id: 'new', status: 'approaching' }),
      avatarName: char.name, avatarSeated: true, seatedKey: 'bench#0', ownSeatChangeAt: 0,
      releasedPropExecutions: new Set(), npcs: mgr,
    }, ['avatarSeated']);
    release();
    assert.equal(release.snapshot().avatarSeated, false);
    assert.equal(figure.current.getClip().name, 'sitting', 'local release preserves seated clip until exit');
    const fresh = structuredClone(char);
    fresh.travel = { ...fresh.travel, waypoints: [[2, 0], [2, -.5], [4, -.5]],
      starts_in_s: .75, progress_m: 0, paces_m_s_real: null, floor_y: 0 };
    fresh.activity_animation = 'fixture-get-up';
    const adopted = routeFor(fresh, 30, map);
    mgr.update([adopted]); mgr.tick(0, 10);
    assert.equal(figure.current.getClip().name, 'fixture-get-up');
    assert.equal(figure.bridging, true);
    assert.equal(root.position.z, 0, 'root stays at seat during exit');
    const bodyPoint = () => { root.updateMatrixWorld(true); return figure.root.children[0].getWorldPosition(new THREE.Vector3()); };
    let previous = bodyPoint();
    for (let i = 0; i < 44; i++) {
      now += 1000 / 60; mgr.tick(1 / 60, 10);
      const point = bodyPoint();
      assert.ok(point.distanceTo(previous) <= .25001, 'rendered exit and handoff stay continuous');
      previous = point;
      if (i === 5) {
        const state = routeFor(fresh, 31, map);
        state.route.startsInS = .65; // A later countdown must not restart the exit.
        mgr.update([state]);
      }
      assert.notEqual(figure.current.getClip().name, 'walking', 'no walking before departure');
    }
    assert.ok(Math.abs(root.position.z + .5) < 1e-6, 'exit travel reaches stand point before walk');
    assert.equal(root.position.x, 2, 'countdown cannot move beyond stand point');
    fresh.travel.starts_in_s = null; fresh.travel.progress_m = .5;
    fresh.travel.paces_m_s_real = [null, 1]; fresh.activity_animation = '';
    mgr.update([routeFor(fresh, 32, map)]);
    for (let i = 0; i < 20; i++) {
      now += 1000 / 60; mgr.tick(1 / 60, 10);
      const point = bodyPoint(); assert.ok(point.distanceTo(previous) <= .25001); previous = point;
    }
    assert.ok(root.position.x > 2 && root.position.z === -.5, 'walk follows second leg after departure');
    assert.equal(figure.current.getClip().name, 'walking');
  } finally { globalThis.performance = realPerformance; }
}

// Task 81: no exit clip holds the seat through the short lead, then releases at waypoint 2.
{
  const realPerformance = globalThis.performance;
  let now = 10000;
  globalThis.performance = { now: () => now };
  try {
    const mgr = new NpcManager(null, { syncCounters: {}, errWindow: { t: [], e: [] } });
    const root = new THREE.Group(); root.position.set(2, .129, 0);
    const figure = new Figure({ name: 'no-exit', template: new THREE.Group(), scale: 1, height: 1.7,
      clips: ['walking', 'standing', 'sitting'].map(name => new THREE.AnimationClip(name, 1, [])),
      tier: 'full', noClips: false, libraryFits: true });
    root.add(figure.root); figure.play('sitting');
    // Imported asset names may differ from the semantic action key.
    figure.current.getClip().name = 'SittingIdle';
    const npc = { name: char.name, root, figure, target: root.position.clone(), waypoints: [],
      entry: null, interaction: null, route: null, travelLine: null, travelKey: '',
      label: {}, labelName: {}, labelActivity: {}, bubbleUntil: 0 };
    mgr.npcs.set(char.name, npc); mgr.setPlayerDriven(char.name); mgr.setServerDriven(char.name, true);
    mgr.preparePropDeparture(char.name);
    const fresh = structuredClone(char);
    fresh.travel = { ...fresh.travel, waypoints: [[2, 0], [2, -.5], [4, -.5]],
      starts_in_s: .3, progress_m: 0, paces_m_s_real: [null, 1], floor_y: 0 };
    fresh.activity_animation = 'sitting';
    mgr.update([routeFor(fresh, 81, map)]);
    for (let i = 0; i < 3; i++) {
      mgr.tick(.1, 10);
      assert.equal(figure.current.getClip().name, 'SittingIdle', 'no-exit lead retains aliased seat pose');
      assert.equal(root.position.z, 0, 'no-exit lead retains seat point');
      assert.equal(figure.bridging, false, 'seat pose never becomes a departure bridge');
      now += 100;
    }
    mgr.tick(0, 10);
    assert.equal(root.position.z, -.5, 'at start, stand up at SECOND waypoint');
    assert.equal(root.position.y, .01, 'at start, stand on the bare floor plus clearance');
    assert.equal(figure.current.getClip().name, 'standing', 'at start, release directly to upright pose');
    let previous = root.position.clone();
    for (let i = 0; i < 30; i++) {
      now += 1000 / 60; mgr.tick(1 / 60, 10);
      assert.ok(root.position.distanceTo(previous) <= .25001, 'walk after defined stand-up remains continuous');
      previous.copy(root.position);
    }
    assert.ok(root.position.x > 2 && root.position.z === -.5, 'null seat pace cannot trap the walk');
    assert.equal(figure.current.getClip().name, 'walking');
    npc.propCommitKey = 'old-seat';
    mgr.clearPropEntry(char.name);
    assert.equal(npc.propCommitKey, '', 'release clears held-pose commit identity');
    assert.equal(npc.route, null, 'release clears a route even without an entry');
    assert.equal(figure.current.getClip().name, 'standing', 'release clears animation even without an entry');
  } finally { globalThis.performance = realPerformance; }
}

// A late first owned poll must walk the remaining visual route, including corners.
{
  const late = structuredClone(char);
  late.travel.progress_m = 5.4; late.travel.floor_y = 9.4;
  const mgr = new NpcManager(null, { syncCounters: {}, errWindow: { t: [], e: [] } });
  const root = new THREE.Group(); root.position.set(-3, 9.41, -2);
  const figure = new Figure({ name: 'late', template: new THREE.Group(), scale: 1, height: 1.7,
    clips: ['walking', 'standing', 'sitting'].map(name => new THREE.AnimationClip(name, 1, [])),
    tier: 'full', noClips: false, libraryFits: true });
  root.add(figure.root);
  const npc = { name: char.name, root, figure, target: root.position.clone(), waypoints: [],
    entry: null, interaction: null, route: null, travelLine: null, travelKey: '',
    label: {}, labelName: {}, labelActivity: {}, bubbleUntil: 0 };
  mgr.npcs.set(char.name, npc);
  mgr.setPlayerDriven(char.name); mgr.setServerDriven(char.name, true);
  motionStatus = null;
  const pendingOwnership = routeFor(late, 8, map);
  assert.equal(pendingOwnership.route.ownedApproach, true, 'new prepared journey is continuous before private state arrives');
  mgr.update([pendingOwnership]); mgr.tick(1 / 60, 10);
  assert.ok(root.position.x > -3 && root.position.x < -2.7 && root.position.z === -2, 'pre-private frame follows first route leg');
  root.position.set(-3, 9.41, -2); npc.route = null;
  motionStatus = 'approaching';
  const beforeOwnership = routeFor(late, 9, map);
  beforeOwnership.route.exact = false; beforeOwnership.route.ownedApproach = false;
  mgr.update([beforeOwnership]);
  mgr.update([routeFor(late, 10, map)]);
  assert.equal(root.position.x, -3, 'late adoption retains current rendered point');
  assert.equal(npc.route.shownM, 0, 'owned route starts at current projection, not 90%');
  mgr.tick(0, 10);
  assert.equal(root.position.x, -3, 'first zero-time frame never jumps');
  for (let i = 0; i < 50; i++) {
    const before = root.position.clone();
    if (i === 5) {
      late.travel.progress_m = 6;
      mgr.update([routeFor(late, 11, map)]);
      assert.ok(root.position.distanceTo(before) < 1e-6, 'new poll cannot snap forward');
    }
    mgr.tick(1 / 60, 10);
    assert.ok(root.position.distanceTo(before) <= .25001, 'no frame jumps more than .25m');
    assert.ok((root.position.z === -2 && root.position.x <= 0)
      || (Math.abs(root.position.x) < 1e-5 && root.position.z <= -1)
      || (root.position.z === -1 && root.position.x >= 0), 'catch-up follows exact corners');
  }
  assert.ok(root.position.distanceTo(new THREE.Vector3(2, 9.41, -1)) < 1e-5, 'reaches access within catch-up window');
  assert.equal(figure.current.getClip().name, 'standing', 'waiting for server settlement stands at access');
  root.position.set(-3, 9.41, -2); npc.route = null;
  mgr.update([routeFor(late, 19, map)]);
  const paired = { ...read('worldmap_active.json').characters[0], place: null,
    interaction: { id: 'pair', kind: 'greeting-handshake', role: 'a', partner: 'npc',
      anchor: { x: 2, z: -1, yaw: 0, place_id: null }, elapsed_s: 0, clip_duration_s: 2, loop: false, rate: 1 } };
  mgr.update([{ char: paired, interaction: paired.interaction, pos: new THREE.Vector3(2, 9.41, -1), stamp: 19 }]);
  assert.equal(root.position.x, -3, 'interaction-only arrival cannot skip approach');
  assert.equal(npc.route.ownedApproach, true, 'pair arrival retains owned route');
  assert.equal(npc.interaction, null, 'pair clip waits for visual access');
  root.position.set(-3, 9.41, -2); npc.route = null;
  mgr.update([routeFor(late, 20, map)]);
  const seatedState = { char: read('worldmap_active.json').characters[0],
    pos: new THREE.Vector3(2, 9.529, 0), committedPropKey: 'bench#0#sitting', stamp: 21 };
  const held = {};
  const reconcileSeat = await mainFunction('reconcileAvatarPlace', {
    pollIsStale: () => false, ownSeatChangeAt: 0, avatarName: char.name,
    manualPropGate: { pending: false }, npcs: mgr, avatarSeated: false, seatedKey: '',
    getGameState: () => ({ mode: 'embodied' }),
    residency: new Map([[seatedState.char.location_id, { ring: 'near', tile: {
      roomMarkers: new Map([[seatedState.char.place.room_id, new Map([[seatedState.char.place.id, held]])]]),
    } }]]),
    slotFor: () => seatedState.pos.clone(), cancelRoute() {}, walkIn: null, correction: null, THREE,
  });
  const driver = await mainFunction('applyDriver', {
  reconcilePropWorld() {},
    pollIsStale: () => false, ownCorrectionAt: 0, ownSeatChangeAt: 0, avatarName: char.name,
    manualPropGate: { pending: false, withdrawn: () => false }, ownedPropRun: () => null,
    ownedPropJourney: late.travel.journey_id, avatarDrive: { kind: 'SERVER', j: late.travel.journey_id },
    avatarCancelled: echo.NO_CANCEL, avatarDriver: echo.avatarDriver, posSession: 'late', THREE,
    npcs: mgr, enterServerDrive: () => mgr.setServerDriven(char.name, true),
    tileAt: () => null, roomFloorY: () => 9.41, groundY: () => 0,
  });
  driver({ characters: [seatedState.char] }, 21);
  reconcileSeat({ characters: [seatedState.char] }, 21);
  mgr.update([seatedState]);
  assert.equal(root.position.x, -3, 'early seat cannot skip rendered approach');
  for (let i = 0; i < 50; i++) {
    const before = root.position.clone(); mgr.tick(1 / 60, 10);
    assert.ok(root.position.distanceTo(before) <= .25001, 'early settlement still walks continuously');
  }
  reconcileSeat({ characters: [seatedState.char] }, 21);
  mgr.update([seatedState]);
  assert.equal(figure.current.getClip().name, 'sitting', 'seat follows completed visible approach');

}
motionStatus = 'active'; char.travel.floor_y = 9.4;
assert.equal(routeFor(char, 2, map).route.exact, true, 'active private state cannot turn the older owned approach into an overland journey');
assert.equal(routeFor(char, 2, map).pos.y, 9.4 + 0.01);
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
  reconcilePropWorld() {},
  pollIsStale: () => false, ownCorrectionAt: 0, ownSeatChangeAt: 0,
  manualPropGate: { pending: false, withdrawn: () => false }, avatarName: char.name,
  ownedPropRun: () => ownedRun, ownedPropJourney: 'upper',
  avatarDriver: echo.avatarDriver, avatarCancelled: echo.NO_CANCEL, posSession: 'upper',
  THREE, groundY: () => 0, roomFloorY: () => 9.41, tileAt: () => ({}),
  npcs: { propEntryUnavailable: name => mgr.propEntryUnavailable(name),
    setServerDriven: (_name, _on, how) => { terminalPoint = how.arriveAt; } },
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
const localRelease = await mainFunction('releaseLocalProp', {
  manualPropGate: manualGate, manualPropRelease: false, ownSeatChangeAt: 0, answerFloor: 0, posSeq: 1, pendingReport: {},
  avatarName: char.name, avatarCancelled: null, avatarDrive: { kind: 'SERVER', j: 'upper-journey' }, npcs: mgr,
  avatarSeated: true, seatedKey: 'bench#0', preparedPropJourney: null, preparedPropSeatExecution: 'upper',
}, ['avatarDrive', 'avatarSeated', 'manualPropRelease']);
const release = await mainFunction('releaseOwnedProp', {
  releaseLocalProp: localRelease, trackedPropRun: null, requestedPropRun: null, adoptedPropJourney: null,
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
assert.deepEqual(localRelease.snapshot(), { avatarDrive: { kind: 'PLAYER' }, avatarSeated: false, manualPropRelease: true });
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
