#!/usr/bin/env node
/**
 * Smoke check: a figure that SAT DOWN through a measured prop entry and is
 * then taken over by a pair/group interaction stays on its seat (§ A8a, the
 * pair blend of `game/pairBlend.ts`; § B5a: numbers, never screenshots).
 *
 * Usage:  node client3d/scripts/smoke_pair_after_entry.mjs
 *         (bundles client3d/src/scene/npcs.ts with esbuild; no WebGL, no server)
 *
 * WHY THIS FILE EXISTS (2026-11-08): a group furniture action (avatar + two
 * NPCs on one seat) — both NPCs dropped to the floor when the group clip
 * started and came back up a moment later; the avatar did not. A figure in a
 * measured entry keeps its ROOT on the ACCESS point on the floor
 * (`tickPropEntry`: root = access, the entry clip's travel and the support
 * lift `entrySupportLift = anchor.y − access.y` carry the BODY onto the seat).
 * The server ends the entry and starts the interaction in ONE commit
 * (`interaction_engine.start_interaction_at`: `prop_action_entry=None` beside
 * `interaction`), so the poll that ends the entry is the poll that starts the
 * pair, and `update()` adopts the interaction FIRST: the blend's origin was
 * taken from the root — the access point on the floor — and `playPair` drops
 * the lift. The avatar's own motion holds its root on the anchor once
 * arrived (`sampleMotion` 'arrived' → anchor), so its blend starts on the seat.
 *
 * THE RULE: the origin of a pair blend is where the figure is SHOWN. For a
 * figure whose entry is being handed over that is the entry's ANCHOR (the
 * entry is finished at phase 1 in that same update — `adoptPropEntry`), in
 * the payload's units: `y` is the body root, yaw compass degrees →
 * radians (`figure.root.rotation.y = degToRad(deg)`, as `adoptPropEntry`'s
 * `setYaw` does). Otherwise it is the root, as before.
 *
 * HAND-DERIVED NUMBERS — seat 'bench' (slot y 0.42 = body root on the seat),
 *   access {x 2, y 0, z 3, yaw 180}, entry anchor {x 2, y 0.42, z 2.5, yaw 180},
 *   group anchor {x 2, z 2.5, yaw π}, this member's clip root (0, 0)
 *   → target = anchor + R(π)·(0,0) = (2, 0.42, 2.5), yaw π.
 *   Blend weight w(u) = u²(3 − 2u), u = age / 0.4 s.
 *   NEW: origin = entry anchor = (2, 0.42, 2.5), yaw π = target, so every
 *        frame shows (2, 0.42, 2.5), yaw π — at age 0, 0.1 s and 0.4 s.
 *   OLD (origin = root at access (2, 0, 3)): age 0 → y 0 (0.42 m under the
 *        seat, on the floor), z 3; age 0.1 s → w = 0.15625 → y = 0.065625,
 *        z = 3 − 0.5·0.15625 = 2.921875; age 0.4 s → back on (2, 0.42, 2.5).
 *   CONTROL: a figure WITHOUT an entry, root (5, 0, 5), yaw 0, still blends
 *        from its root — pairBlendOrigin returns (5, 0, 5), yaw 0 — and an entry
 *        anchor with yaw 90° gives π/2.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const bundle = await build({
  stdin: { contents: `export {NpcManager} from './client3d/src/scene/npcs'; export {pairBlendOrigin} from './client3d/src/game/pairBlend'; export * as THREE from 'three';`,
           resolveDir: fileURLToPath(new URL('../..', import.meta.url)), loader: 'ts' },
  bundle: true, loader: { '.css': 'empty' }, write: false, platform: 'node', format: 'esm', logLevel: 'error',
});
const { NpcManager, pairBlendOrigin, THREE } =
  await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);

const close = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg}: ${a} != ${b}`);

// [1] the pure origin
{
  const free = pairBlendOrigin({ x: 5, y: 0, z: 5 }, 0, null);
  assert.deepEqual(free, { x: 5, y: 0, z: 5, yaw: 0 }, 'no entry: the root is the origin');
  const seated = pairBlendOrigin({ x: 2, y: 0, z: 3 }, 0,
    { anchor: { x: 2, y: 0.42, z: 2.5, yaw: 90 } });
  close(seated.x, 2, 'entry origin x'); close(seated.y, 0.42, 'entry origin y');
  close(seated.z, 2.5, 'entry origin z'); close(seated.yaw, Math.PI / 2, 'entry origin yaw 90° → π/2');
  console.log('[1] pairBlendOrigin: root without entry, entry anchor with one — PASS');
}

// [2] the manager path, through the real update() order
const saved = globalThis.performance; let now = 10000;
globalThis.performance = { now: () => now };
try {
  const mgr = new NpcManager({ pairRootAt: () => ({ x: 0, z: 0 }) },
    { syncCounters: {}, errWindow: { t: [], e: [] } });
  mgr.setPlaceAt((_n, id) => (id === 'bench' ? { slots: [{ y: 0.42 }], group: 'seat' } : undefined));
  mgr.setGroundHeight(() => 0);
  const root = new THREE.Group();
  const figure = {
    root: new THREE.Group(), holdsTravel: false,
    playPropEntry: () => true, finishPropEntry() {}, playPair: () => true,
    setYaw(y) { this.root.rotation.y = y; }, setLean() {}, update() {}, resetSecondaryMotion() {}, setFirstPerson() {},
    faceTowards(dir) { this.root.rotation.y = Math.atan2(dir.x, dir.z); },
  };
  const el = () => ({ textContent: '' });
  const npc = { name: 'Npc B', root, figure, target: new THREE.Vector3(), waypoints: [], route: null, ride: null,
    entry: null, entryBlocked: false, propCommitKey: '', interaction: null, finale: null, finaleSeen: '',
    settle: null, label: { visible: true }, labelName: el(), labelActivity: el(), labelBadges: el(), badgeKey: '',
    labelBubble: { hidden: true }, bubbleUntil: 0, travelLine: null, travelKey: '', reckon: null };
  mgr.npcs.set('Npc B', npc);

  const access = { x: 2, y: 0, z: 3, yaw: 180 };
  const anchor = { x: 2, y: 0.42, z: 2.5, yaw: 180 };
  const entry = { kind: 'sit-down', pose_key: 'group-sit', access, anchor, root_offset: 0.08,
    duration_s: 2, elapsed_s: 0, clock_rate: 1, height_cm: 170, role: 'b', started_s: 7 };
  // poll 1: the entry plays — root on the ACCESS point on the floor
  mgr.update([{ char: { name: 'Npc B', activity_animation: 'walking', prop_action_entry: entry },
    pos: new THREE.Vector3(2, 0, 3), stamp: 1 }]);
  now += 2000; mgr.tick(2, 10);
  assert.deepEqual(root.position.toArray(), [2, 0, 3], 'during the entry the root stands on the access point');

  // poll 2: ONE commit ends the entry and starts the group interaction
  const interaction = { id: 'g1', kind: 'group-sit', role: 'b', alt: '', elapsed_s: 0, rate: 1, loop: true,
    clip_duration_s: 2, anchor: { x: 2, z: 2.5, yaw: Math.PI, place_id: 'bench' } };
  const st = { char: { name: 'Npc B', activity_animation: 'sitting', prop_action_entry: null,
    place: { id: 'bench', slot: 0, room_id: 'room' }, interaction },
    pos: new THREE.Vector3(2, 0, 2.5), interaction, stamp: 2 };
  mgr.update([st]);
  assert.ok(npc.interaction && !npc.entry, 'the interaction is adopted and the entry handed over');

  const frames = [];
  for (const step of [0, 100, 300]) {   // ages 0, 0.1 s, 0.4 s
    now += step;
    mgr.tick(step / 1000, 10);
    frames.push([root.position.x, root.position.y, root.position.z, figure.root.rotation.y]);
  }
  for (const [i, [x, y, z, yaw]] of frames.entries()) {
    const age = [0, 0.1, 0.4][i];
    close(x, 2, `age ${age}s x`);
    close(y, 0.42, `age ${age}s y — on the seat, never the floor (old code: ${[0, 0.065625, 0.42][i]})`);
    close(z, 2.5, `age ${age}s z (old code: ${[3, 2.921875, 2.5][i]})`);
    close(Math.cos(yaw), -1, `age ${age}s yaw π`);
  }
  console.log('[2] entry → group interaction: (2, 0.42, 2.5) yaw π at 0 / 0.1 / 0.4 s — PASS');

  // [3] control: a NEW interaction for a figure standing free still blends from its root
  const free = { ...npc, name: 'Npc C', root: new THREE.Group(), entry: null, interaction: null,
    figure: { ...figure, root: new THREE.Group() } };
  free.root.position.set(5, 0, 5);
  mgr.npcs.set('Npc C', free);
  const it2 = { ...interaction, id: 'g2' };
  mgr.update([st, { char: { name: 'Npc C', activity_animation: 'standing', place: { id: 'bench', slot: 0, room_id: 'room' },
    interaction: it2 }, pos: new THREE.Vector3(5, 0, 5), interaction: it2, stamp: 3 }]);
  now += 100; mgr.tick(0.1, 10);
  // from (5,0,5) to (2,0.42,2.5), w = 0.15625: x = 5 − 3·w = 4.53125, y = 0.065625, z = 5 − 2.5·w = 4.609375
  close(free.root.position.x, 4.53125, 'free figure x'); close(free.root.position.y, 0.065625, 'free figure y');
  close(free.root.position.z, 4.609375, 'free figure z');
  console.log('[3] control: a figure without an entry blends from its root — PASS');
} finally {
  globalThis.performance = saved;
}
console.log('pair after entry: all checks passed');
