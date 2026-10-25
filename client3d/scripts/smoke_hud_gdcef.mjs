/**
 * HUD bridge over gdCEF's JS binding (`gdcefTransport`, native client spike S4).
 *
 * Usage (repo root): node client3d/scripts/smoke_hud_gdcef.mjs
 *
 * A fake gdCEF host stands in for the native client's Chromium:
 * `godotMethods.hud_bridge(data)` is what a page calls to reach Godot,
 * `godotEvents.on/emit` is how Godot's `js_emit` reaches the page (gdCEF has
 * no `off`). Behind the fake host sits a SECOND realm running the browser's own
 * `connectSceneSide`, so every message crosses as a JSON string in both
 * directions, exactly like the gdCEF wire (a string survives its Variant/V8
 * conversion, an object would not). Expected values are the ones written into
 * the messages below — nothing is recorded from a previous run.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
async function realm(id) {
  const result = await build({ stdin: { contents: "export * from './bus'; export * from './bridge';", resolveDir: 'client3d/src/hud' }, bundle: true, write: false, format: 'esm', platform: 'browser' });
  return import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text + `\n// ${id}`).toString('base64'));
}
const scene = await realm('scene');
const hud = await realm('hud');

// --- the fake gdCEF host ------------------------------------------------------
const toGodot = [];          // raw arguments of godotMethods.hud_bridge
const fromGodot = [];        // raw payloads of godotEvents.emit
const eventListeners = new Map();
let nativeInbox = null;      // the scene realm's receive function
const host = {
  // gdCEF's Proxy answers every property with a function; one name is enough here.
  godotMethods: { hud_bridge: data => { toGodot.push(data); nativeInbox?.(JSON.parse(data)); return true; } },
  godotEvents: {
    on(event, fn) { if (!eventListeners.has(event)) eventListeners.set(event, new Set()); eventListeners.get(event).add(fn); },
    emit(event, data) { fromGodot.push(data); for (const fn of eventListeners.get(event) ?? []) fn(data); },
  },
};
// The Godot side: strings out (js_emit of a JSON string), strings in.
const nativeTransport = {
  send: msg => host.godotEvents.emit('hud_bridge', JSON.stringify(msg)),
  onMessage: fn => { nativeInbox = fn; return () => { nativeInbox = null; }; },
};

const stopScene = scene.connectSceneSide(nativeTransport);
const transport = hud.gdcefTransport(host);
const stopHud = hud.connectHudSide(transport);
assert.equal(eventListeners.get('hud_bridge')?.size, 1, 'one gdCEF listener on the hud_bridge channel');
assert.ok(toGodot.length > 0 && toGodot.every(d => typeof d === 'string'), 'HUD -> Godot payloads are JSON strings');
assert.ok(fromGodot.every(d => typeof d === 'string'), 'Godot -> HUD payloads are JSON strings');

// scene -> HUD: a scene-owned field (clock) and the boot snapshot
scene.setGameState({ clock: 'Day 3, 14:05' });
assert.equal(hud.getGameState().clock, 'Day 3, 14:05');
scene.setBoot({ state: { percent: 100, label: 'ready', note: null, stages: ['visible'] }, report: null });
assert.equal(hud.getBoot().state.percent, 100);
// scene -> HUD: ui action (the native client's Enter/F key)
let opened = 0;
hud.uiActions.openChat = () => opened++;
scene.uiActions.openChat();
assert.equal(opened, 1);
// HUD -> scene: ui state with hit rectangles, typing and menu flags
hud.setHudUiState({ typing: true, menuOpen: true, hitRects: [{ x: 10, y: 20, w: 300, h: 200 }] });
assert.deepEqual(scene.getHudUiState().hitRects, [{ x: 10, y: 20, w: 300, h: 200 }]);
assert.equal(scene.getHudUiState().typing, true);
assert.equal(scene.getHudUiState().menuOpen, true);
// HUD -> scene: a game action with arguments
const zoomed = [];
scene.gameActions.zoomTo = (...args) => zoomed.push(args);
hud.gameActions.zoomTo('Kira');
assert.deepEqual(zoomed, [['Kira']]);
// HUD -> scene: a HUD-owned field
hud.setGameState({ partyLeader: 'Ari "the bold" Ünal' });
assert.equal(scene.getGameState().partyLeader, 'Ari "the bold" Ünal', 'quotes and non-ASCII survive the string wire');
// The last HUD -> Godot payload is exactly the JSON of a protocol v1 message.
const last = JSON.parse(toGodot.at(-1));
assert.deepEqual(last, { v: 1, kind: 'state', patch: { partyLeader: 'Ari "the bold" Ünal' } });

// Rejection on the HUD side: invalid JSON, wrong version, unknown kind — 3 warnings, no state change.
const warnings = [];
const warn = console.warn;
console.warn = (...args) => warnings.push(args);
try {
  host.godotEvents.emit('hud_bridge', '{not json');
  host.godotEvents.emit('hud_bridge', JSON.stringify({ v: 2, kind: 'state', patch: { clock: 'wrong' } }));
  host.godotEvents.emit('hud_bridge', JSON.stringify({ v: 1, kind: 'bogus' }));
} finally { console.warn = warn; }
assert.equal(warnings.length, 3);
assert.equal(hud.getGameState().clock, 'Day 3, 14:05');
// An already-parsed object (a host that emitted a Dictionary) is accepted as it is.
host.godotEvents.emit('hud_bridge', { v: 1, kind: 'state', patch: { clock: 'Day 3, 14:06' } });
assert.equal(hud.getGameState().clock, 'Day 3, 14:06');

// Without the binding (page opened in a normal browser with ?bridge=gdcef): one warning, no throw.
const bare = hud.gdcefTransport({});
const bareWarnings = [];
console.warn = (...args) => bareWarnings.push(args);
try {
  bare.send({ v: 1, kind: 'hud', patch: {} });
  bare.send({ v: 1, kind: 'hud', patch: {} });
  const off = bare.onMessage(() => {});
  off();
} finally { console.warn = warn; }
assert.equal(bareWarnings.length, 1, 'one warning for a missing binding, not one per message');

// A binding that appears only after the page script subscribed (gdCEF installs it in
// OnContextCreated; this guards the ordering): the transport keeps looking (50 ms steps)
// and receives what is emitted once it is there.
const lateHost = {};
const lateGot = [];
const lateTransport = hud.gdcefTransport(lateHost);
const offLate = lateTransport.onMessage(msg => lateGot.push(msg));
await new Promise(resolve => setTimeout(resolve, 30));
const lateListeners = new Set();
lateHost.godotEvents = { on: (event, fn) => { assert.equal(event, 'hud_bridge'); lateListeners.add(fn); } };
await new Promise(resolve => setTimeout(resolve, 120));
assert.equal(lateListeners.size, 1, 'late binding found by the retry');
for (const fn of lateListeners) fn(JSON.stringify({ v: 1, kind: 'ui', name: 'toast', args: ['late'] }));
assert.deepEqual(lateGot, [{ v: 1, kind: 'ui', name: 'toast', args: ['late'] }]);
offLate();

// Cleanup: after disconnect the HUD no longer reacts, even though gdCEF keeps its listener.
stopHud();
const before = hud.getGameState().clock;
host.godotEvents.emit('hud_bridge', JSON.stringify({ v: 1, kind: 'state', patch: { clock: 'after disconnect' } }));
assert.equal(hud.getGameState().clock, before);
assert.equal(hud.gameActions.zoomTo, undefined);
stopScene();
console.log('hud gdcef: PASS (string wire both ways, state/boot/ui/hud/action round trips, rejection, missing binding, late binding, cleanup)');
