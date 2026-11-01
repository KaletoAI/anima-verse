/** Task 89: execute the real shutdown closure and native-generated handoff scripts against fixture requests.
 * Usage: node client3d/scripts/smoke_resume.mjs [native user://task89-handoff.json]
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { mainFunction } from './mainFunction.mjs';

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
    posDirty: true, posInFlight: false, posSeq: 3, posSession: 'fixture-session',
    roomWalk: { candidate: 'guest' }, requestedRoom: null, roomRejectedUntil: new Map(),
    roomOf: new Map([['fixture-avatar', 'bath']]),
    positionDrain: { wait: async () => {} }, roomDrain: { wait: async () => {} },
    npcs: { positionOf: () => ({ x: 12.34, z: 56.78 }), inInteraction: () => false, hasOwnMotion: () => false },
    getGameState: () => ({ mode: 'embodied', movementLocked: false }),
    performance: { now: () => 340 }, AbortController,
    setTimeout: (f, ms) => { const id = setTimeout(f, ms); timeouts.add(id); return id; },
    clearTimeout: id => { clearTimeout(id); timeouts.delete(id); },
    fetch: async (url, init) => { sent.push({ url, ...init, body: JSON.parse(init.body) }); return { ok: true, json: async () => ({ ok: true }) }; },
    console: { info() {}, warn() {} }, ...overrides,
  }, ['exitFlushing']);
  return { fn, sent, close() { for (const id of timeouts) clearTimeout(id); } };
}
const earlyExit = await mainFunction('flushPlayerOnExit', { exitFlushing: false, exitReportsReady: false });
await earlyExit();
for (const unloading of [true, false]) {
  const f = await fixture();
  try {
    await f.fn(unloading);
    assert.deepEqual(f.sent.map(r => r.url), ['/play/pos', '/play/enter-room']);
    assert.deepEqual(f.sent[0].body, { x: 12.34, z: 56.78, seq: 4, t_ms: 340, session: 'fixture-session' });
    assert.deepEqual(f.sent[1].body, { room_id: 'guest' });
    assert(f.sent.every(r => r.keepalive && r.credentials === 'include'));
    await f.fn(unloading); assert.equal(f.sent.length, 2, 'pagehide after logout must not duplicate writes');
  } finally { f.close(); }
}
for (const overrides of [{ avatarSeated: true }, { ownedPropRun: () => ({}) }, { avatarDrive: { kind: 'SERVER' } }]) {
  const f = await fixture(overrides);
  try { await f.fn(true); assert.equal(f.sent.length, 0, 'server-owned avatars must stay seated/on their journey'); }
  finally { f.close(); }
}
{
  const f = await fixture({ posDirty: false });
  try { await f.fn(true); assert.deepEqual(f.sent.map(r => r.url), ['/play/enter-room'], 'room dirtiness is independent of position dirtiness'); }
  finally { f.close(); }
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
  npcs: { update(states) { update = states; }, faceTowards(...args) { facing = args; } },
});
await arrive();
assert.equal(tile.fade, 1);
assert.equal(update[0].snap, true, 'arrival never walks from an earlier fallback');
assert.deepEqual(update[0].pos, { x: 64, y: 7.03, z: 128 });
assert.deepEqual(facing, ['fixture-avatar', Math.sin(1.2), Math.cos(1.2), true], 'authoritative facing is set directly when supplied');
console.log('resume: PASS (handoff logout counts, final position/room, keepalive, ownership, direct upstairs arrival)');
