/** Task 89: execute the real shutdown closure and native-generated handoff scripts against fixture requests.
 * Usage: node client3d/scripts/smoke_resume.mjs [native user://task89-handoff.json]
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { mainFunction, mainFunctions } from './mainFunction.mjs';
import { buildSync, transformSync } from 'esbuild';
import ts from 'typescript';

// Execute the production serializer/accessor/figure methods without booting WebGL.
function sourceFunction(relative, name, dependencies = {}) {
  const source = ts.createSourceFile(relative, readFileSync(new URL(relative, import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true);
  let found;
  function visit(node) {
    if ((ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)) && node.name?.getText(source) === name) found = node;
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert(found, `missing production function ${name}`);
  const expression = ts.isMethodDeclaration(found) ? `({${found.getText(source)}}).${name}` : `(${found.getText(source).replace(/^export /, '')})`;
  return new Function(...Object.keys(dependencies), transformSync(`return ${expression}`, { loader: 'ts' }).code)(...Object.values(dependencies));
}

const echoSource = readFileSync(new URL('../src/game/posEcho.ts', import.meta.url), 'utf8');
const { positionYaw, positionYawChanged } = await import('data:text/javascript;base64,'
  + Buffer.from(transformSync(echoSource, { loader: 'ts', format: 'esm' }).code).toString('base64'));

if (process.argv[2]) {
  const scripts = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  for (const [kind, cookie, count, outcome] of [
    ['fresh', null, 0, 'no-session'], ['same', 'stored-token', 0, 'same-session'],
    ['recovery', 'old-token', 1, 'logged-out'],
  ]) {
    let held = cookie, logouts = 0, diagnostic;
    const document = {};
    Object.defineProperty(document, 'cookie', { set(value) { held = value.split(';')[0].split('=')[1]; } });
    const requests = [];
    await vm.runInNewContext(scripts[kind], {
      document, localStorage: { setItem() {} }, location: { replace() {} },
      window: { godotMethods: { hud_handoff(value) { diagnostic = value; } } },
      async fetch(path) {
        requests.push(path);
        if (path === '/auth/status') return { ok: true, json: async () => ({ authenticated: held !== null }) };
        assert.equal(path, '/auth/logout'); logouts++; held = null; return { ok: true };
      },
    });
    assert.equal(logouts, count, `${kind} logout count`);
    assert.equal(held, 'stored-token'); assert.equal(diagnostic, outcome);
    if (kind === 'fresh') assert.deepEqual(requests, ['/auth/status']);
  }
}

async function fixture(overrides = {}) {
  const sent = [], timeouts = new Set();
  const fn = await mainFunction('flushPlayerOnExit', {
    exitFlushing: false, exitReportsReady: true, avatarName: 'fixture-avatar', avatarDrive: { kind: 'PLAYER' }, avatarSeated: false,
    pendingSnap: null, correction: null, verticalRide: null,
    manualPropGate: { pending: false }, propMutationPending: false, propStateUncertain: false,
    propPreparation: { pending: false }, ownedPropRun: () => null, manualPropRelease: false,
    lastMap: { characters: [{ name: 'fixture-avatar' }] }, pendingReport: null,
    posDirty: true, posInFlight: false, posSeq: 3, posSession: 'fixture-session', reportedYaw: 0.8,
    roomWalk: { candidate: 'guest' }, requestedRoom: null, roomRejectedUntil: new Map(),
    roomOf: new Map([['fixture-avatar', 'bath']]),
    positionDrain: { wait: async () => {} }, roomDrain: { wait: async () => {} },
    npcs: { positionOf: () => ({ x: 12.34, z: 56.78 }), yawOf: () => 0.8, inInteraction: () => false, hasOwnMotion: () => false },
    getGameState: () => ({ mode: 'embodied', movementLocked: false }),
    performance: { now: () => 340 }, positionYaw, positionYawChanged, AbortController,
    setTimeout: (f, ms) => { const id = setTimeout(f, ms); timeouts.add(id); return id; },
    clearTimeout: id => { clearTimeout(id); timeouts.delete(id); },
    fetch: async (url, init) => { sent.push({ url, ...init, body: JSON.parse(init.body) }); return { ok: true, json: async () => ({ ok: true }) }; },
    console: { info() {}, warn() {} }, ...overrides,
  }, ['exitFlushing']);
  return { fn, sent, close() { for (const id of timeouts) clearTimeout(id); } };
}
// Execute the production lifecycle listeners. A browser reload replaces the frozen realm.
{
  const source = ts.createSourceFile('main.ts', readFileSync(new URL('../src/main.ts', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true);
  const listeners = [];
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.getText(source) === 'window.addEventListener'
      && (node.arguments[0]?.getText(source) === "'pageshow'"
        || (node.arguments[0]?.getText(source) === "'pagehide'" && node.getText(source).includes('flushPlayerOnExit'))))
      listeners.push(node.getText(source));
    ts.forEachChild(node, visit);
  }
  visit(source);
  const events = new Map(); let reloads = 0;
  const hidden = await fixture();
  try {
    new Function('window', 'location', 'flushPlayerOnExit', transformSync(listeners.join(';'), { loader: 'ts' }).code)(
      { addEventListener: (name, fn) => events.set(name, fn) }, { reload: () => reloads++ }, hidden.fn);
    events.get('pagehide')({ persisted: true });
    assert.equal(hidden.fn.snapshot().exitFlushing, true);
    events.get('pageshow')?.({ persisted: false }); assert.equal(reloads, 0);
    events.get('pageshow')?.({ persisted: true }); assert.equal(reloads, 1, 'bfcache restore must rebuild the HUD and position channel');
    const restored = await fixture();
    try { await restored.fn(true); assert.equal(restored.sent[0].url, '/play/pos', 'new realm reports again'); }
    finally { restored.close(); }
  } finally { hidden.close(); }
}
const earlyExit = await mainFunction('flushPlayerOnExit', { exitFlushing: false, exitReportsReady: false });
await earlyExit();
for (const unloading of [true, false]) {
  const f = await fixture();
  try {
    await f.fn(unloading);
    assert.deepEqual(f.sent.map(r => r.url), ['/play/pos', '/play/enter-room']);
    assert.deepEqual(f.sent[0].body, { x: 12.34, z: 56.78, yaw: 0.8, seq: 4, t_ms: 340, session: 'fixture-session' });
    assert.deepEqual(f.sent[1].body, { room_id: 'guest' });
    assert(f.sent.every(r => r.keepalive && r.credentials === 'include'));
    await f.fn(unloading); assert.equal(f.sent.length, 2, 'pagehide after logout must not duplicate writes');
  } finally { f.close(); }
}
for (const overrides of [{ avatarSeated: true }, { ownedPropRun: () => ({}) }, { avatarDrive: { kind: 'SERVER' } },
  { manualPropGate: { pending: true } }, { propPreparation: { pending: true } },
  { propMutationPending: true }, { propStateUncertain: true }, { verticalRide: {} },
  { npcs: { inInteraction: () => true } }, { npcs: { inInteraction: () => false, hasOwnMotion: () => true } }]) {
  const f = await fixture({ posDirty: false, reportedYaw: 0, ...overrides });
  try { await f.fn(true); assert.equal(f.sent.length, 0, 'server-owned avatars must stay seated/on their journey'); }
  finally { f.close(); }
}
{
  const f = await fixture({ posDirty: false });
  try { await f.fn(true); assert.deepEqual(f.sent.map(r => r.url), ['/play/enter-room'], 'room dirtiness is independent of position dirtiness'); }
  finally { f.close(); }
}
{
  const f = await fixture({ npcs: { positionOf: () => ({ x: 1, z: 2 }), yawOf: () => null,
    inInteraction: () => false, hasOwnMotion: () => false } });
  try { await f.fn(true); assert.equal(f.sent[0].body.yaw, null, 'quit without a rendered figure must preserve server facing'); }
  finally { f.close(); }
}
{
  const f = await fixture({ posDirty: false, reportedYaw: 0 });
  try {
    await f.fn(true);
    assert.equal(f.sent[0].url, '/play/pos', 'a yaw-only change must flush before the next frame');
    assert.equal(f.sent[0].body.yaw, 0.8);
  } finally { f.close(); }
}
{
  let release;
  const flight = new Promise(resolve => { release = resolve; });
  const f = await fixture({ posInFlight: true, positionDrain: { wait: () => flight } });
  try {
    const flushing = f.fn(false); assert.equal(f.sent.length, 0);
    release(); await flushing;
    assert.equal(f.sent[0].body.seq, 4, 'the final stamp outranks an earlier flight');
  } finally { f.close(); }
}
{
  const f = await fixture({ positionDrain: { wait: () => new Promise(() => {}) } });
  try {
    const started = Date.now(); await f.fn(false);
    assert(Date.now() - started < 1400, 'a lost HTTP flight cannot trap logout');
    assert.equal(f.sent.length, 0);
  } finally { f.close(); }
}
// The arrival placement must force a direct set even if the old hidden figure already had an NPC target.
const map = { characters: [{ name: 'fixture-avatar', location_id: 'house', yaw: 1.2 }] };
let update, facing;
const tile = { roomGroups: new Map(), fade: 0, levelFilter: 0 };
const arrive = await mainFunction('placeAvatarOnArrival', {
  awaitArrivalMount: async () => 'house', firstMap: map, lastMap: map, avatarName: 'fixture-avatar',
  residency: new Map([['house', { tile }]]), roomOf: new Map([['fixture-avatar', 'guest']]),
  followAvatarStorey: t => { t.levelFilter = 1; }, openable: () => true,
  applyTileFade: t => assert.equal(t.levelFilter, 1, 'show storey before revealing interior'),
  applyLevelDisplay() {}, applyRoomVisibility() {}, refreshOpenBadge() {}, openLocationId: 'house',
  computeNpcStates: () => [{ char: map.characters[0], pos: { x: 64, y: 7.03, z: 128 }, snap: false }],
  reportedYaw: null, positionYaw,
  npcs: { update(states) { update = states; }, faceTowards(...args) { facing = args; }, yawOf: () => 1.2 },
});
await arrive();
assert.equal(tile.fade, 1);
assert.equal(update[0].snap, true, 'arrival never walks from an earlier fallback');
assert.deepEqual(update[0].pos, { x: 64, y: 7.03, z: 128 });
assert.deepEqual(facing, ['fixture-avatar', Math.sin(1.2), Math.cos(1.2), true], 'authoritative facing is set directly when supplied');
facing = undefined;
map.characters[0].yaw = null;
await arrive();
assert.equal(facing, undefined, 'null yaw preserves default facing');

// Hand oracle: atan2(x,z) means +z=0, +x=pi/2; the 3-degree threshold wraps at pi.
for (const [before, after, dirty] of [[0, 2, false], [0, 4, true], [179, -179, false], [178, -178, true]])
  assert.equal(positionYawChanged(before * Math.PI / 180, after * Math.PI / 180), dirty);
const { facingYaw } = await import('data:text/javascript;base64,'
  + Buffer.from(buildSync({ entryPoints: [new URL('../src/game/npcWalk.ts', import.meta.url).pathname],
    bundle: true, format: 'esm', write: false }).outputFiles[0].text).toString('base64'));
const faceTowards = sourceFunction('../src/scene/figures.ts', 'faceTowards', { facingYaw });
const yawOf = sourceFunction('../src/scene/npcs.ts', 'yawOf');
assert.equal(positionYaw(yawOf.call({ npcs: new Map() }, 'missing')), null, 'missing figure must not invent zero yaw');
assert.equal(positionYaw(yawOf.call({ npcs: new Map([['pending', { root: { rotation: { y: 0 } } }]]) }, 'pending')), null,
  'a placeholder without a rendered figure must not supply facing');
for (const rendered of [0, Math.PI/2, -Math.PI/2, Math.PI, 7.2]) {
  const figure = { root: { rotation: { y: rendered } }, targetYaw: -2, holdsFacing: false };
  const yaw = positionYaw(yawOf.call({ npcs: new Map([['avatar', { figure }]]) }, 'avatar'));
  faceTowards.call(figure, { x: Math.sin(yaw), y: 0, z: Math.cos(yaw) }, true);
  assert(Math.abs(positionYaw(figure.root.rotation.y - rendered)) < .01, 'rendered facing round trips through real arrival method');
}
assert.equal(positionYaw(0), 0);
assert.equal(positionYaw(Math.PI/2), Math.PI/2);
let wireBody;
const postPos = sourceFunction('../src/api.ts', 'postPos', {
  fetch: async (url, options) => { assert.equal(url, '/play/pos'); wireBody = JSON.parse(options.body);
    return { status: 200, ok: true, json: async () => ({ ok: true }) }; },
});
await postPos(1, 2, undefined, 3, 330, 'fixture-session', .8);
assert.deepEqual(wireBody, { x: 1, z: 2, yaw: .8, seq: 3, t_ms: 330, session: 'fixture-session' });
await postPos(1, 2, undefined, 4, 660, 'fixture-session', null);
assert.equal(wireBody.yaw ?? null, null, 'no facing leaves stored server yaw unchanged');
const getWorldMap = sourceFunction('../src/api.ts', 'getWorldMap', {
  performance: { now: () => 0 }, worldMapMeta: new WeakMap(), json: r => r.json(),
  fetch: async () => ({ json: async () => ({ characters: [{ name: 'avatar', yaw: null }] }) }),
});
assert.equal((await getWorldMap()).characters[0].yaw, null, 'worldmap parser preserves null yaw');

let now = 330, renderedYaw = 0, delayedAnswer = null;
const reports = [];
const channel = await mainFunctions(['tickPosReport', 'markMoved', 'reserveReport', 'flushPendingReport', 'reportPosWithSeq'], {
  avatarName: 'fixture-avatar', npcs: { yawOf: () => renderedYaw }, positionYaw, positionYawChanged,
  pendingSnap: null, exitFlushing: false, avatarDrive: { kind: 'PLAYER' }, avatarSeated: false,
  manualPropGate: { pending: false }, propMutationPending: false, propStateUncertain: false,
  propPreparation: { pending: false }, ownedPropRun: () => null, manualPropRelease: false, lastMap: null,
  propPositionDrainActive: false, positionDrain: { begin: () => () => {} },
  posInFlight: false, posDirty: false, reportedYaw: 0, reportedPos: null,
  pendingReport: null, lastReportAt: 0, posSeq: 0, posSession: 'fixture-session',
  POS_REPORT_MS: 330, POS_TIMEOUT_MS: 8000, sentSeqs: [], answerFloor: 0,
  pushSeq() {}, answerApplies: () => true, adoptReport() {},
  performance: { now: () => now }, AbortController, setTimeout, clearTimeout,
  api: { async postPos(...args) { reports.push(args); return delayedAnswer ?? { ok: true }; } },
}, ['posDirty', 'reportedYaw']);
const tick = async () => { channel.tickPosReport({ x: 1, z: 2 }); await Promise.resolve(); };
await tick(); assert.equal(reports.length, 0, 'standing idle sends nothing');
renderedYaw = 2 * Math.PI / 180; await tick(); assert.equal(reports.length, 0);
renderedYaw = 4 * Math.PI / 180; await tick(); assert.equal(reports.length, 1, 'turn in place sends once');
assert.equal(reports[0][6], renderedYaw, 'normal report carries yaw through API');
now = 660; await tick(); now = 990; await tick(); assert.equal(reports.length, 1, 'no idle report stream');
now = 1000; renderedYaw = .8; await tick();
assert.equal(reports.length, 2);
now = 1100; renderedYaw = 1.2; await tick(); assert.equal(reports.length, 2, 'turn respects cadence');
now = 1330; await tick(); assert.equal(reports.length, 3); assert.equal(reports[2][6], 1.2);
let releaseAnswer;
delayedAnswer = new Promise(resolve => { releaseAnswer = resolve; });
now = 1660; renderedYaw = 1.6; await tick(); assert.equal(reports.length, 4);
now = 1990; await tick();
assert.equal(channel.snapshot().posDirty, false, 'unchanged facing during HTTP must not dirty a second report');
delayedAnswer = null; releaseAnswer({ ok: true }); await new Promise(resolve => setImmediate(resolve));
now = 2320; await tick(); assert.equal(reports.length, 4, 'slow HTTP still sends one report per turn');
now = 2400; renderedYaw = 2;
channel.markMoved({ x: 3, z: 2 }); channel.tickPosReport({ x: 3, z: 2 }); await Promise.resolve();
now = 2410; renderedYaw = 2.2;
channel.markMoved({ x: 3.25, z: 2 }); channel.tickPosReport({ x: 3.25, z: 2 }); await Promise.resolve();
assert.equal(reports.length, 5, 'last walking step remains under cadence');
now = 2730; renderedYaw = 2.3;
channel.tickPosReport({ x: 3.25, z: 2 }); await Promise.resolve();
assert.equal(reports.length, 6); assert.equal(reports[5][0], 3.25); assert.equal(reports[5][6], 2.3, 'final stop carries resting yaw');
now = 3060; channel.tickPosReport({ x: 3.25, z: 2 }); await Promise.resolve();
assert.equal(reports.length, 6, 'final stop reports only once');
now = 3390; renderedYaw = null;
channel.markMoved({ x: 4, z: 2 }); channel.tickPosReport({ x: 4, z: 2 }); await Promise.resolve();
assert.equal(reports.length, 7); assert.equal(reports[6][6], null, 'movement without a rendered figure must not send zero yaw');
console.log('resume: PASS (handoff, position/room/yaw flush, ownership, null arrival, facing round trip, turn threshold, cadence, slow flight, final stop)');
