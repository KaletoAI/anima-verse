/** HUD bridge: independent realms, both directions and protocol rejection. */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
async function realm(id) {
  const result = await build({ stdin: { contents: "export * from './bus'; export * from './bridge';", resolveDir: 'client3d/src/hud' }, bundle: true, write: false, format: 'esm', platform: 'browser' });
  return import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text + `\n// ${id}`).toString('base64'));
}
const scene = await realm('scene');
const hud = await realm('hud');
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
assert.deepEqual(hudMessages.filter(msg => msg.kind === 'state'), [{ v: 1, kind: 'state', patch: { groundRoomId: 'g2' } }]);
let cleared = [];
scene.gameActions.clearSelection = (...args) => cleared.push(args);
hud.gameActions.clearSelection();
assert.deepEqual(cleared, [[]]);
hud.setHudUiState({ perfOn: true });
assert.equal(scene.getHudUiState().perfOn, true);
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
scene.gameActions.speak = () => Promise.resolve();
assert.equal(hud.gameActions.speak('voice.wav'), undefined);
const warnings = [];
const warn = console.warn;
console.warn = (...args) => warnings.push(args);
try {
  b.send({ v: 2, kind: 'action', name: 'zoomTo', args: ['wrong'] });
  b.send({ v: 1, kind: 'action', name: 'nope', args: [] });
  b.send({ v: 1, kind: 'action', name: 'toString', args: [] });
  a.send({ v: 1, kind: 'unknown' });
  a.send({ v: 1, kind: 'state', patch: { groundRoomId: 'x', partyLeader: 'wrong', movementLocked: true, elevatorOpen: true } });
  b.send({ v: 1, kind: 'state', patch: { mode: 'overview', selected: null, lockedLoc: 'valid HUD field' } });
} finally { console.warn = warn; }
assert.equal(warnings.length, 6);
assert.equal(hud.getGameState().groundRoomId, 'g2');
assert.equal(scene.getGameState().mode, 'embodied');
assert.equal(hud.getGameState().elevatorOpen, true);
assert.equal(hud.getGameState().movementLocked, false);
assert.equal(scene.getGameState().lockedLoc, 'valid HUD field');
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
const message = { v: 1, kind: 'hud', patch: {} };
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
stopScene(); stopHud();
assert.equal(hud.gameActions.zoomTo, undefined);
assert.equal(scene.uiActions.openChat, undefined);
scene.setGameState({ mode: 'overview' });
assert.equal(hud.getGameState().mode, 'embodied');
console.log('hud bridge: PASS (independent realms, owned-field deltas, ownership rejection, clearSelection, perfOn, UI message counts, transport, cleanup)');
