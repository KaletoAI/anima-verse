#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/stand_settle.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_stand_settle.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const DT = 1 / 30;
const STEP = 3.4 * DT;   // 0.113333…

let passed = 0;
let failed = 0;
function check(label, ok, detail = '') {
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}
const near = (label, actual, expected, eps) =>
  check(label, Number.isFinite(actual) && Math.abs(actual - expected) <= eps,
    `${Number(actual).toFixed(6)} (expected ${expected} ±${eps})`);

/** Bundle one entry (three external, so bundle and script share one three). */
async function bundle(entry) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'out.mjs'), external: ['three', 'three/*'], logLevel: 'silent',
    });
    const file = join(dir, 'out.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function main() {
  const THREE = await import('three');
  const src = join(ROOT, 'client3d/src');

  const vectors = await runBridgeVectors('stand_settle');
  passed += vectors.passed; failed += vectors.failed;

  // ------------------------------------------------------------------ [S]
  console.log('\n[S] the manager: hand-over in tick, goal in update (stub figure)');
  const { NpcManager } = await bundle(`export { NpcManager } from '${src}/scene/npcs';`);
  /** A figure whose bridge has just ENDED and still holds `travel`. */
  const stubFigure = (travel) => ({
    bridging: false, holdsTravel: !!travel, holdsFacing: false, holdsHeight: false,
    paceLimit: 1, bridgePace: 0, height: 1.7, root: new THREE.Group(),
    paceLimitFor: () => 1,
    takeTravel() {
      if (!this.holdsTravel) return null;
      this.holdsTravel = false;
      return { x: travel.x, z: travel.z };
    },
    play() {}, update() {}, faceTowards() {}, setSubmerged() {}, setLean() {},
    setFirstPerson() {}, resetSecondaryMotion() {}, hasHead: true,
    beginBridgeLift: () => false, shiftBridgeLift: () => false, dispose() {},
  });
  const SEAT = new THREE.Vector3(1.6, 0, 3.0);
  const P = new THREE.Vector3(2.0, 0, 3.0);
  const npcOn = (name, travel, player = false) => {
    const mgr = new NpcManager(null, {
      syncCounters: { posCorr: 0, pos409: 0, travBack: 0, travFwd: 0, travErrMaxM: 0, arrive: 0, place: 0 },
      errWindow: { t: [], e: [] },
    });
    const root = new THREE.Group();
    root.position.copy(SEAT);
    const npc = {
      name, animation: 'idle', root, figure: stubFigure(travel), ring: null, sprite: null,
      label: { visible: false }, labelName: { textContent: '' }, labelActivity: { textContent: '' }, labelBadges: { textContent: '' },
      labelBubble: null, bubbleUntil: 0, target: SEAT.clone(), pace: 1, face: null,
      waypoints: [], ride: null, route: null, travelling: false, reckon: null,
      interaction: null, activity: '', travelLine: null, travelKey: '', bobPhase: 0,
      settle: null,
    };
    mgr.npcs.set(name, npc);
    if (player) mgr.setPlayerDriven(name);
    return { mgr, npc };
  };
  const stateAt = (name, pos, extra = {}) => ({
    char: { name, activity: '', activity_animation: 'idle' }, pos: pos.clone(), ...extra,
  });
  const at = (v) => `(${v.x.toFixed(6)}, ${v.z.toFixed(6)})`;
  const dist = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);

  // [S1] + [S4] + [S3]
  {
    const { mgr, npc } = npcOn('s1', { x: 0.52, z: 0 });
    mgr.update([stateAt('s1', P)]);
    mgr.tick(DT, 10);   // the hand-over tick
    const handed = npc.root.position.clone();
    near('[S1] the hand-over tick: root x = 1.60 + 0.52 = 2.12 (no step)', handed.x, 2.12, 1e-6);
    check('[S1] settle = (0.12, 0)', !!npc.settle
      && Math.abs(npc.settle.offset.x - 0.12) < 1e-9 && Math.abs(npc.settle.offset.z) < 1e-9,
      npc.settle ? `(${npc.settle.offset.x.toFixed(6)}, ${npc.settle.offset.z.toFixed(6)})` : 'none');
    check('[S1] goal = the figure (2.12, 3.00)', dist(npc.target, handed) < 1e-6, at(npc.target));
    for (let i = 0; i < 30; i++) mgr.tick(DT, 10);
    check('[S1] 30 more ticks: the root does not move (<= 1e-6)',
      dist(npc.root.position, handed) <= 1e-6, `${dist(npc.root.position, handed).toExponential(2)} m`);
    mgr.update([stateAt('s1', P)]);
    check('[S1] after the next update (same P): distance root → goal < 1e-6',
      dist(npc.root.position, npc.target) < 1e-6, `${dist(npc.root.position, npc.target).toExponential(2)} m`);
    mgr.update([stateAt('s1', P)]);
    mgr.tick(DT, 10);
    check('[S4] a poll with the same P keeps the settle, goal (2.12, 3.00)',
      !!npc.settle && Math.abs(npc.target.x - 2.12) < 1e-6 && Math.abs(npc.target.z - 3.0) < 1e-6,
      at(npc.target));
    check('[S4] …and the root still does not move', dist(npc.root.position, handed) <= 1e-6,
      `${dist(npc.root.position, handed).toExponential(2)} m`);
    const P2 = new THREE.Vector3(3.0, 0, 3.0);
    mgr.update([stateAt('s1', P2)]);
    check('[S3] a new P\' (1 m away) clears the settle', !npc.settle, String(!!npc.settle));
    check('[S3] goal = P\' exactly', npc.target.equals(P2), at(npc.target));
    mgr.tick(DT, 10);
    near('[S3] one tick later the root walked 0.113333 towards it: x = 2.233333',
      npc.root.position.x, 2.12 + STEP, 1e-6);
  }
  // [S2]
  {
    const { mgr, npc } = npcOn('s2', { x: 0.80, z: 0 });
    mgr.update([stateAt('s2', P)]);
    mgr.tick(DT, 10);
    check('[S2] 0.40 m off: no settle', !npc.settle, String(!!npc.settle));
    check('[S2] goal = P', npc.target.equals(P), at(npc.target));
    near('[S2] the hand-over tick walks back towards P: x = 2.40 − 0.113333 = 2.286667',
      npc.root.position.x, 2.4 - STEP, 1e-6);
  }
  // [S5]
  {
    const { mgr, npc } = npcOn('s5', { x: 0.52, z: 0 }, true);
    const out = mgr.takePlayerTravel('s5');
    check('[S5] the avatar\'s hand-over returns its new point (2.12, 3.00)',
      !!out && Math.abs(out.x - 2.12) < 1e-9 && Math.abs(out.z - 3.0) < 1e-9,
      out ? `(${out.x.toFixed(6)}, ${out.z.toFixed(6)})` : 'null');
    check('[S5] root AND goal moved by the travel', Math.abs(npc.root.position.x - 2.12) < 1e-9
      && Math.abs(npc.target.x - 2.12) < 1e-9, `root ${at(npc.root.position)}, goal ${at(npc.target)}`);
    check('[S5] no settle on the avatar', !npc.settle, String(!!npc.settle));
  }
  // [S6]
  {
    const { mgr, npc } = npcOn('s6', { x: 0.52, z: 0 });
    mgr.update([stateAt('s6', P)]);
    mgr.tick(DT, 10);
    mgr.update([stateAt('s6', P, { snap: true })]);
    check('[S6] a snap with the same P puts the root on the settled spot (2.12, 3.00)',
      Math.abs(npc.root.position.x - 2.12) < 1e-6 && Math.abs(npc.root.position.z - 3.0) < 1e-6,
      at(npc.root.position));
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
