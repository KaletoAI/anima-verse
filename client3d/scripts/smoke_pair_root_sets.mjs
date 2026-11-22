#!/usr/bin/env node
/**
 * Two halves of the pair-placement fix of 2026-11-20, checked by hand (no server, no models):
 *
 * A) THE ROOT CACHE KEEPS SETS APART. Clips are indexed per kind AND set (`commitInListOrder`, first file per
 *    (kind, set) wins); the pair roots used to be cached per kind only, so the LAST set listed supplied the root path of
 *    every set. Listing: hug__a in set "female" (file f1), hug__a in "male" (m1), hug__a in "male" again (m2, loses:
 *    first wins), hug__b in "" (n1). `pairRootsOf` over the committed index, pairRoot = "root:" + id:
 *    [A1] hug__a / female = root:f1, hug__a / male = root:m1 (not m2, not each other's).
 *    [A2] `pairRootFor` along a set chain (the character's sets, then ""): ["male", ""] → root:m1, ["female", ""] →
 *         root:f1, ["elf", ""] → undefined (no neutral hug__a), hug__b with ["male", ""] → root:n1 (the neutral file).
 *    [A3] a solo kind (walk) gets no root entry.
 * B) THE GAME PLACES EACH FIGURE BY ITS OWN SIZE (`npcs.ts` tickInteraction through scene-render `scalePairRoot`).
 *    The library answers root p = (0.3, 0.1) and pivot C = (0.12, 0.30) for the half; anchor (10, 22), yaw 90°
 *    (x = ax + rx·cos + rz·sin = 10 + rz, z = az − rx·sin + rz·cos = 22 − rx).
 *    [B1] no figure height (an old figure stand-in) and height 1.70: p unchanged → x = 10.1, z = 21.7, and the two are
 *         bit-identical.
 *    [B2] height 1.85, a = 37/34: p' = C + a·(p − C) = (0.12 + a·0.18, 0.30 − a·0.20) = (0.31588235, 0.08235294)
 *         → x = 10.08235294, z = 21.68411765 (±1e-8).
 *    [B3] height 1.60, a = 16/17: p' = (0.12 + 0.16941176, 0.30 − 0.18823529) = (0.28941176, 0.11176471)
 *         → x = 10.11176471, z = 21.71058824 (±1e-8).
 *
 * Usage: node client3d/scripts/smoke_pair_root_sets.mjs
 */
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { build } from 'esbuild';
import * as THREE from 'three';

const root = fileURLToPath(new URL('../../', import.meta.url));
const dir = await mkdtemp(join(root, 'client3d/scripts/.smoke-'));
let m;
try {
  const entry = `export {commitInListOrder, pairRootsOf, pairRootFor} from '${root}client3d/src/game/clipCommit.ts';
export {NpcManager} from '${root}client3d/src/scene/npcs.ts';`;
  const built = await build({stdin: {contents: entry, resolveDir: root, loader: 'ts'},
    bundle: true, platform: 'node', format: 'esm', write: false,
    outfile: join(dir, 'm.mjs'), external: ['three', 'three/*'], logLevel: 'error'});
  const file = join(dir, 'm.mjs');
  await writeFile(file, built.outputFiles[0].text);
  m = await import(`file://${file}`);
} finally { await rm(dir, {recursive: true, force: true}); }

let n = 0;
const ok = (label) => { n++; console.log('  ok', label); };

// ── A) the root cache ──
{
  const sources = [
    {kind: 'hug__a', set: 'female', url: 'f1'}, {kind: 'hug__a', set: 'male', url: 'm1'},
    {kind: 'hug__a', set: 'male', url: 'm2'}, {kind: 'hug__b', set: '', url: 'n1'}, {kind: 'walk', set: '', url: 'w1'},
  ];
  const results = ['f1', 'm1', 'm2', 'n1', 'w1'].map((id) => ({clip: {id}}));
  const isPair = (k) => /__[a-e]$/.test(k);
  const out = m.commitInListOrder(sources, results, {setFlags: () => {}, isPair, pairRoot: () => null,
    rename: (c, name) => ({...c, name})});
  const roots = m.pairRootsOf(out.index, isPair, (c) => 'root:' + c.id);
  assert.equal(roots.get('hug__a').get('female'), 'root:f1');
  assert.equal(roots.get('hug__a').get('male'), 'root:m1');
  ok('[A1] hug__a keeps female = f1 and male = m1 apart (first file per set, like the clip index)');
  assert.equal(m.pairRootFor(roots, 'hug__a', ['male', '']), 'root:m1');
  assert.equal(m.pairRootFor(roots, 'hug__a', ['female', '']), 'root:f1');
  assert.equal(m.pairRootFor(roots, 'hug__a', ['elf', '']), undefined);
  assert.equal(m.pairRootFor(roots, 'hug__b', ['male', '']), 'root:n1');
  ok('[A2] the set chain picks the root of the very file the character plays');
  assert.equal(roots.has('walk'), false);
  ok('[A3] a solo kind has no root entry');
}

// ── B) the game placement by figure size ──
function place(height) {
  const lib = {pairRootAt: () => ({x: 0.3, z: 0.1, pivot: {x: 0.12, z: 0.30}})};
  const figure = {
    playPair: () => true, holdsTravel: false, takeTravel: () => {},
    faceTowards: () => {}, setYaw: () => {}, update: () => {}, setFirstPerson: () => {}, hasHead: false,
    pairHipsBind: [0, 0.9, 0], pairTurnDeg: [0, 0, 0],
    ...(height === undefined ? {} : {height}),
  };
  const mgr = new m.NpcManager(lib, {
    syncCounters: {posCorr: 0, pos409: 0, travBack: 0, travFwd: 0, travErrMaxM: 0, arrive: 0, place: 0},
    errWindow: {t: [], e: []},
  });
  mgr.setGroundHeight(() => 0.5);
  mgr.setPlaceAt(() => undefined);
  mgr.setRoomStandAt(() => null);
  const r = new THREE.Group();
  const npc = {
    name: 'A', animation: 'idle', root: r, figure, ring: null, sprite: null,
    label: {visible: false}, labelName: {textContent: ''}, labelActivity: {textContent: ''}, labelBadges: {textContent: ''},
    labelBubble: null, bubbleUntil: 0, target: new THREE.Vector3(), pace: 1, face: null,
    waypoints: [], ride: null, route: null, travelling: false, reckon: null,
    interaction: {id: 'p1', clip: 'handshake__a', base: 'handshake__a', anchor: {x: 10, z: 22, yaw: Math.PI / 2, placeId: null},
      elapsed: 0, clipT: 0, clipDuration: 2, loop: true, rate: 1, tempo: 1, stamp: 0},
    activity: '', travelLine: null, travelKey: '', bobPhase: 0, settle: null,
  };
  mgr.npcs.set('A', npc);
  // the interaction step alone (the full tick also runs phase B, which this stand-in figure does not have)
  assert.equal(mgr.tickInteraction(npc, 1 / 30, false, false), true);
  return r.position;
}
{
  const none = place(undefined), base = place(1.70);
  assert.ok(Math.abs(none.x - 10.1) < 1e-12 && Math.abs(none.z - 21.7) < 1e-12, `${none.x} ${none.z}`);
  assert.ok(Object.is(none.x, base.x) && Object.is(none.z, base.z));
  ok('[B1] no height and 1.70 m: (10.1, 21.7), bit-identical');
  const tall = place(1.85);
  assert.ok(Math.abs(tall.x - 10.08235294) < 1e-8 && Math.abs(tall.z - 21.68411765) < 1e-8, `${tall.x} ${tall.z}`);
  ok('[B2] 1.85 m: (10.08235294, 21.68411765)');
  const short = place(1.60);
  assert.ok(Math.abs(short.x - 10.11176471) < 1e-8 && Math.abs(short.z - 21.71058824) < 1e-8, `${short.x} ${short.z}`);
  ok('[B3] 1.60 m: (10.11176471, 21.71058824)');
}
console.log(`smoke_pair_root_sets: ${n} ok`);
