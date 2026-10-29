/** HUD bridge: independent realms, both directions and protocol rejection. */
import assert from 'node:assert/strict';
import { loadHudRealm } from './load_hud_realm.mjs';
const scene = loadHudRealm();
const hud = loadHudRealm();
assert.notEqual(scene.gameActions, hud.gameActions);
scene.setGameState({ talkTarget: { name: 'initial snapshot', dist: 1 } });
hud.setGameState({ partyLeader: 'HUD initial' });
const [a, b] = scene.loopbackPair();
const hudMessages = [];
const hudTransport = { ...b, send: msg => { hudMessages.push(structuredClone(msg)); b.send(msg); } };
const stopHud = hud.connectHudSide(hudTransport);
const sceneMessages = [];
const sceneTransport = { ...a, send: msg => { sceneMessages.push(structuredClone(msg)); a.send(msg); } };
const stopScene = scene.connectSceneSide(sceneTransport);
assert.equal(hud.getGameState().talkTarget.name, 'initial snapshot');
assert.equal(scene.getGameState().partyLeader, 'HUD initial');
hud.setGameState({ groundRoomId: 'g1' });
assert.equal(scene.getGameState().groundRoomId, 'g1');
scene.setGameState({ mode: 'embodied' });
assert.equal(hud.getGameState().mode, 'embodied');
assert.equal(hud.getGameState().groundRoomId, 'g1');
hudMessages.length = 0;
sceneMessages.length = 0;
for (const name of ['one', 'two', 'three']) scene.setGameState({ talkTarget: { name, dist: 1 } });
assert.equal(hudMessages.filter(msg => msg.kind === 'hud').length, 0);
assert.deepEqual(sceneMessages.filter(msg => msg.kind === 'state').map(msg => Object.keys(msg.patch)), [['talkTarget'], ['talkTarget'], ['talkTarget']]);
hud.setHudUiState({ ...hud.getHudUiState() });
assert.equal(hudMessages.filter(msg => msg.kind === 'hud').length, 0);
hudMessages.length = 0;
hud.setGameState({ groundRoomId: 'g1' });
assert.equal(hudMessages.filter(msg => msg.kind === 'state').length, 0);
hud.setGameState({ groundRoomId: 'g2' });
assert.deepEqual(hudMessages.filter(msg => msg.kind === 'state'), [{ v: 4, kind: 'state', patch: { groundRoomId: 'g2' } }]);
const info = { id: 'loc1', name: 'Home', description: '', rooms: [], present: [], events: [], view: { openable: true, open: false } };
scene.setGameState({ info });
assert.deepEqual(hud.getGameState().info, info);
const infoCalls = [];
scene.gameActions.infoAction = (...args) => infoCalls.push(args);
hud.gameActions.infoAction('loc1', 'lookInside');
assert.deepEqual(infoCalls, [['loc1', 'lookInside']]);
let cleared = [];
scene.gameActions.clearSelection = (...args) => cleared.push(args);
hud.gameActions.clearSelection();
assert.deepEqual(cleared, [[]]);
hud.setHudUiState({ perfOn: true });
assert.equal(scene.getHudUiState().perfOn, true);
// Protocol v4 preserves unrelated graphics arguments across the clean cutover.
assert.equal(scene.HUD_BRIDGE_VERSION, 4);
const graphics = [];
scene.gameActions.applyGraphicsPrefs = (...args) => graphics.push(args);
hud.gameActions.applyGraphicsPrefs({ antiAliasing: '4x', shadows: false });
assert.deepEqual(graphics, [[{ antiAliasing: '4x', shadows: false }]]);
assert.deepEqual(hudMessages.at(-1), { v: 4, kind: 'action', name: 'applyGraphicsPrefs', args: [{ antiAliasing: '4x', shadows: false }] });
const exactTarget = { location_id: 'home', room_id: 'workshop', placement_id: 'coffee-2', variant_uid: 'ecfa003d-309a-4ce2-8c9b-29944ddae093' };
const semanticCalls = [];
for (const name of ['pickPropAction', 'respondPropAction', 'cancelPropAction', 'pickRoomPose', 'closePlaceMenu']) {
  scene.gameActions[name] = (...args) => semanticCalls.push({ name, args });
}
hud.gameActions.pickPropAction('share-coffee', exactTarget, 'revision-2', 'Ben');
hud.gameActions.respondPropAction('exact-question', false);
hud.gameActions.cancelPropAction('exact-owned-run');
hud.gameActions.pickRoomPose('room-marker', 'sitting');
hud.gameActions.closePlaceMenu();
assert.deepEqual(semanticCalls, [
  { name: 'pickPropAction', args: ['share-coffee', exactTarget, 'revision-2', 'Ben'] },
  { name: 'respondPropAction', args: ['exact-question', false] },
  { name: 'cancelPropAction', args: ['exact-owned-run'] },
  { name: 'pickRoomPose', args: ['room-marker', 'sitting'] },
  { name: 'closePlaceMenu', args: [] },
]);
assert.equal(hud.gameActions.pickPlacePose, undefined, 'removed furniture pose alias is not installed');
const sceneSemantic = scene.load('packages/player-ui/src/propActions.ts');
const hudSemantic = hud.load('packages/player-ui/src/propActions.ts');
let sceneInvalidations = 0;
let hudInvalidations = 0;
const offSceneInvalidation = sceneSemantic.onPropActionChanged(() => sceneInvalidations++);
const offHudInvalidation = hudSemantic.onPropActionChanged(() => hudInvalidations++);
hudSemantic.notifyPropActionChanged();
sceneSemantic.notifyPropActionChanged();
assert.equal(sceneInvalidations, 2, 'both local and remote mutations refresh the scene exactly once');
assert.equal(hudInvalidations, 2, 'both local and remote mutations refresh the HUD exactly once');
assert.equal(sceneMessages.filter(msg => msg.kind === 'prop-actions-changed').length, 1, 'scene notification does not echo');
assert.equal(hudMessages.filter(msg => msg.kind === 'prop-actions-changed').length, 1, 'HUD notification does not echo');
offSceneInvalidation();
offHudInvalidation();
// The shared panel's HTTP request must wait for the real host position drain.
let drainRelease;
let preparedId;
const drain = new Promise(resolve => { drainRelease = resolve; });
scene.gameActions.preparePropAction = async requestId => { preparedId = requestId; await drain; };
const originalFetch = globalThis.fetch;
const sentRequests = [];
globalThis.fetch = async (path, init) => {
  sentRequests.push({ path, body: JSON.parse(init.body) });
  return new Response(JSON.stringify({ execution_id: 'pending-run', status: 'awaiting_consent', reason: '' }), { status: 200 });
};
const finishedIds = [];
const offFinished = sceneSemantic.onPropActionChanged(id => finishedIds.push(id));
try {
  const mutation = hudSemantic.requestPropAction('share-coffee', exactTarget, 'revision-2', 'Ben');
  await Promise.resolve();
  assert.equal(typeof preparedId, 'string');
  assert.equal(sentRequests.length, 0, 'HTTP cannot overtake the host position write');
  sceneSemantic.notifyPropActionChanged();
  assert.equal(sentRequests.length, 0, 'an uncorrelated lifecycle change cannot bypass preparation');
  drainRelease();
  await mutation;
  assert.deepEqual(sentRequests, [{ path: '/play/prop-actions/request',
    body: { action_id: 'share-coffee', target: exactTarget, revision: 'revision-2', partner: 'Ben' } }]);
  assert.equal(finishedIds.at(-1), preparedId, 'settlement preserves the exact mutation barrier ID');
  assert.equal(sceneMessages.find(msg => msg.kind === 'prop-action-prepared').request_id, preparedId);
  scene.gameActions.preparePropAction = async () => { throw new Error('position write refused'); };
  await assert.rejects(hudSemantic.requestPropAction('share-coffee', exactTarget, 'revision-2', 'Ben'), /position write refused/);
  assert.equal(sentRequests.length, 1, 'failed host preparation never sends HTTP');
  assert.equal(finishedIds.at(-1), hudMessages.filter(msg => msg.kind === 'prop-action-prepare').at(-1).request_id,
    'failed preparation also releases only its correlated barrier');
} finally {
  offFinished();
  globalThis.fetch = originalFetch;
}
let received = [];
scene.gameActions.zoomTo = (...args) => received.push(args);
hud.gameActions.zoomTo('Kira');
assert.deepEqual(received, [['Kira']]);
hud.setHudUiState({ menuOpen: true });
assert.equal(scene.getHudUiState().menuOpen, true);
let opened = 0;
hud.uiActions.openChat = () => opened++;
scene.uiActions.openChat();
assert.equal(opened, 1);
scene.setBoot({ ...scene.getBoot(), state: { ...scene.getBoot().state, percent: 75 } });
assert.equal(hud.getBoot().state.percent, 75);
scene.setPerfStats(null);
assert.equal(hud.getPerfStats(), null);
scene.setMinimap(null);
assert.deepEqual(hud.getMinimap(), scene.getMinimap());
// v4: cache state is scene-owned, and clearing is an ordinary command.
assert.equal(hud.getGameState().clientCache, null);
let cacheClears = 0;
scene.gameActions.clearClientCache = () => cacheClears++;
scene.setGameState({ clientCache: { bytes: 12, limitBytes: 4294967296, entries: 2 } });
assert.deepEqual(hud.getGameState().clientCache, { bytes: 12, limitBytes: 4294967296, entries: 2 });
hud.gameActions.clearClientCache(); assert.equal(cacheClears, 1);
// A line stays pending until its exact acknowledgement, including failure/stop.
let finishSpeech;
scene.gameActions.speak = () => new Promise(resolve => { finishSpeech = resolve; });
let speechDone = false;
const speech = hud.gameActions.speak('voice.wav').then(() => { speechDone = true; });
await Promise.resolve(); assert.equal(speechDone, false);
const speechRequest = hudMessages.at(-1);
assert.equal(speechRequest.kind, 'speech'); assert.equal(speechRequest.url, 'voice.wav');
a.send({ v: 4, kind: 'speech-done', request_id: 'unrelated' });
await Promise.resolve(); assert.equal(speechDone, false);
finishSpeech(); await speech;
assert.equal(speechDone, true);
assert.deepEqual(sceneMessages.at(-1), { v: 4, kind: 'speech-done', request_id: speechRequest.request_id });
scene.gameActions.speak = () => { throw new Error('broken voice'); };
await hud.gameActions.speak('broken.wav');
scene.gameActions.speak = () => new Promise(resolve => { finishSpeech = resolve; });
scene.gameActions.stopSpeech = () => finishSpeech();
const stoppedSpeech = hud.gameActions.speak('stopped.wav'); hud.gameActions.stopSpeech(); await stoppedSpeech;
// A lost acknowledgement resolves after a bounded timeout; disconnect also releases the driver.
const realTimeout = globalThis.setTimeout;
let timeoutRelease;
globalThis.setTimeout = fn => { timeoutRelease = fn; return 123; };
const timedSpeech = hud.gameActions.speak('lost.wav');
globalThis.setTimeout = realTimeout;
timeoutRelease(); await timedSpeech;

// The actual HUD driver renders the next line only after playback completes.
const { createVoiceover } = hud.load('client3d/src/game/voiceover.ts');
const rendered = [], played = [];
const releases = [];
scene.gameActions.speak = url => { played.push(url); return new Promise(resolve => releases.push(resolve)); };
scene.gameActions.stopSpeech = () => { for (const resolve of releases.splice(0)) resolve(); };
const voice = createVoiceover({
  synth: async line => { rendered.push(line.text); return line.text; },
  play: async url => { await hud.gameActions.speak(url); },
  stop: () => hud.gameActions.stopSpeech(),
});
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
voice.push([{ speaker: 'A', text: 'one' }, { speaker: 'B', text: 'two' }, { speaker: 'C', text: 'three' }]);
await flush(); assert.deepEqual(rendered, ['one']); assert.deepEqual(played, ['one']);
releases.shift()(); await flush(); assert.deepEqual(rendered, ['one', 'two']);
releases.shift()(); await flush(); assert.deepEqual(played, ['one', 'two', 'three']);
voice.clear(); await flush(); assert.equal(voice.pending.length, 0);
voice.push([{ speaker: 'A', text: 'fresh' }]); await flush();
assert.equal(played.at(-1), 'fresh'); voice.clear(); await flush();
const warnings = [];
const warn = console.warn;
console.warn = (...args) => warnings.push(args);
try {
  b.send({ v: 3, kind: 'action', name: 'zoomTo', args: ['wrong'] });   // the replaced v3 peer is refused
  b.send({ v: 4, kind: 'action', name: 'nope', args: [] });
  b.send({ v: 4, kind: 'action', name: 'toString', args: [] });
  a.send({ v: 4, kind: 'unknown' });
  a.send({ v: 4, kind: 'state', patch: { groundRoomId: 'x', partyLeader: 'wrong', movementLocked: true, elevatorOpen: true } });
  b.send({ v: 4, kind: 'state', patch: { mode: 'overview', selected: null, clientCache: null, lockedLoc: 'valid HUD field' } });
} finally { console.warn = warn; }
assert.equal(warnings.length, 6);
assert.equal(hud.getGameState().groundRoomId, 'g2');
assert.equal(scene.getGameState().mode, 'embodied');
assert.equal(hud.getGameState().elevatorOpen, true);
assert.equal(hud.getGameState().movementLocked, false);
assert.equal(scene.getGameState().lockedLoc, 'valid HUD field');
assert.equal(scene.getGameState().clientCache.bytes, 12, 'HUD cannot overwrite the cache readout');
assert.deepEqual(received, [['Kira']]);
const rects = [{ x: 0, y: 0, w: 10, h: 10 }, { x: 5, y: 5, w: 10, h: 10 }];
assert.deepEqual(scene.mergeRects(rects), rects);
assert.equal(scene.pointInRects(rects, 12, 12), true);
assert.equal(scene.pointInRects(rects, 20, 1), false);
// A Window-like host proves both source and origin checks, and listener cleanup.
const handlers = new Set();
globalThis.window = {
  addEventListener: (name, fn) => handlers.add(fn),
  removeEventListener: (name, fn) => handlers.delete(fn),
};
const sent = [];
const target = { postMessage: (...args) => sent.push(args) };
const transport = scene.postMessageTransport(target, 'https://hud.test');
let deliveries = 0;
const off = transport.onMessage(() => deliveries++);
const message = { v: 4, kind: 'hud', patch: {} };
transport.send(message);
assert.deepEqual(sent, [[message, 'https://hud.test']]);
for (const fn of handlers) {
  fn({ source: {}, origin: 'https://hud.test', data: message });
  fn({ source: target, origin: 'https://other.test', data: message });
  fn({ source: target, origin: 'https://hud.test', data: message });
}
assert.equal(deliveries, 1);
off(); assert.equal(handlers.size, 0);
delete globalThis.window;
const disconnectedSpeech = hud.gameActions.speak('disconnect.wav');
stopScene(); stopHud(); await disconnectedSpeech;
assert.equal(hud.gameActions.zoomTo, undefined);
assert.equal(scene.uiActions.openChat, undefined);
scene.setGameState({ mode: 'overview' });
assert.equal(hud.getGameState().mode, 'embodied');
console.log('hud bridge: PASS (independent realms, owned-field deltas, exact semantic target/revision/partner, consent/stop, room markers, transport, cleanup)');
