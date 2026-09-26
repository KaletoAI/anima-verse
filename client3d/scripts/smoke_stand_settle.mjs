#!/usr/bin/env node
/**
 * Smoke check: an NPC keeps the spot its bridge clip left it on (plan
 * bruecken-feinschliff, Task C4) — `settleOffset` in
 * `client3d/src/scene/standSettle.ts` and its two call sites in
 * `client3d/src/scene/npcs.ts` (the bridge hand-over in `tick`, the goal write
 * in `update`).
 *
 * Usage:  node client3d/scripts/smoke_stand_settle.mjs
 *
 * Every expected number below is derived BY HAND from the rule written out
 * here, never recorded from the current output.
 *
 * ===========================================================================
 * THE RULE
 * ===========================================================================
 * A bridge clip with root motion (getting up out of a chair or a bed) carries
 * the body off the seat; when it ends the NPC's root takes that travel over
 * (`Figure.takeTravel`). The server already put the character's position on
 * the point the same clip sets it down (`room_stand.bridge_stand_point` = seat
 * + the clip's travel, then `pick_stand`), so the goal the NPC walks to IS that
 * stand point — the hand-over moves the ROOT only. Before this task it moved
 * the goal by the travel as well: the figure walked on to a point one travel
 * past the stand point, and back once the next poll re-wrote the goal (C0
 * § 5.2: goal 49 → 85 cm from the seat).
 *
 * Client and server measure the travel differently (the client per rig, with
 * the bridge's turn in the root; the server from the sidecar's `travel_m`), so
 * the body lands a few centimetres off the server's point. Within
 * STAND_ADOPT_M = 0.25 m — the raster step of `room_stand.pick_stand`
 * (`STAND_GRID_M = 0.25`, app/core/room_stand.py:51), i.e. closer than the
 * server could have placed the figure anyway — the NPC keeps where it stands:
 *
 *     settle = figure − server              (X/Z; |settle| <= 0.25)
 *     goal   = server + settle              (= the figure: nothing to walk)
 *
 * as long as the server sends the SAME position (within SAME_STAND_M = 1 mm;
 * the server writes centimetre-rounded points, so a real move is >= 1 cm).
 * A different position voids it — the figure walks from where it stands. The
 * height is the server's either way (only X/Z are settled).
 *
 * ===========================================================================
 * [P] THE PURE DECISION — settleOffset(figure, server, lastServer, tol)
 * ===========================================================================
 * [P1] figure (2.12, 3.00), server = last = (2.00, 3.00):
 *      off = (0.12, 0), |off| = 0.12 <= 0.25            → (0.12, 0)
 * [P2] figure (2.40, 3.00):  |off| = 0.40 > 0.25          → null
 * [P3] diagonal, figure (2.09, 2.88): off = (0.09, −0.12),
 *      |off| = sqrt(0.0081 + 0.0144) = sqrt(0.0225) = 0.15 → (0.09, −0.12)
 * [P4] exactly on the raster step: figure (2.00, 3.25), |off| = 0.25 → kept
 *      ((0, 0.25), the bound is inclusive); figure (2.00, 3.2501) → null
 * [P5] the server moved: server (2.01, 3.00), last (2.00, 3.00) — 1 cm, a
 *      real move → null; server (2.0004, 3.00) — 0.4 mm, float noise → the
 *      offset from the NEW server point, (2.12 − 2.0004, 0) = (0.1196, 0)
 * [P6] STAND_ADOPT_M is 0.25 (the raster step quoted above).
 *
 * ===========================================================================
 * [S] THE MANAGER — the real `NpcManager.update` + `tick`
 * ===========================================================================
 * One injected NPC (the shape `createNpc` builds; `update` never creates it,
 * so no DOM is needed), with a STUB figure whose bridge has just ended and
 * holds a travel (`holdsTravel`, `takeTravel` hands it over once) — the
 * bridge itself is `smoke_bridge_root.mjs` [Y3]'s business, here only what
 * the manager does with the travel. Seat at (1.60, 0, 3.00), server stand
 * point P = (2.00, 0, 3.00) delivered by `update`, dt = 1/30 s. Walking pace:
 * step = min(dist, WALK_SPEED 3.4 · dt) = min(dist, 0.113333) (dist < 6 m
 * RUN_DISTANCE: no boost), and nothing moves under MOVE_EPS_M = 0.05.
 *
 * [S1] travel (0.52, 0): after the hand-over tick the root is at (2.12, 3.00)
 *      — 0.12 m off P → settle (0.12, 0), goal = (2.12, 0, 3.00) = the figure.
 *      The root does not move in that tick nor in 30 more (<= 1e-6), and after
 *      the next `update` (same P) the distance root → goal is < 1e-6.
 *      OLD CODE: the goal moved by the travel to (2.52, 3.00), 0.40 m ahead,
 *      and the hand-over tick already stepped 0.113333 towards it.
 * [S4] `update` with the SAME P again (a poll): settle kept, goal (2.12, 3.00).
 * [S3] `update` with a NEW P' = (3.00, 3.00) — 1 m away: settle cleared, goal
 *      = P' exactly; one tick later the root has walked 0.113333 towards it
 *      (dist 0.88 > 0.113333), x = 2.12 + 0.113333 = 2.233333.
 * [S2] travel (0.80, 0) on a fresh NPC: root (2.40, 3.00), 0.40 m off P → no
 *      settle, goal = P; the hand-over tick walks back 0.113333 towards it:
 *      x = 2.40 − 0.113333 = 2.286667.
 *      OLD CODE: goal (2.80, 3.00), the tick walks away: x = 2.513333.
 * [S5] THE AVATAR IS NOT AFFECTED: the player-driven figure takes its travel
 *      through `takePlayerTravel`, which still moves root AND goal (main.ts
 *      reports the new point itself): root (1.60, 3.00) + (0.52, 0) → both at
 *      (2.12, 3.00), and it keeps no settle.
 * [S6] a SNAP (`st.snap`, a view change) with the same P puts the root on the
 *      settled spot (2.12, 3.00), not back on P.
 */
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

  // ------------------------------------------------------------------ [P]
  console.log('[P] settleOffset — the pure decision (hand cases)');
  let pure = null;
  try {
    pure = await bundle(`export { settleOffset, STAND_ADOPT_M } from '${src}/scene/standSettle';`);
  } catch (e) {
    check('[P] standSettle.ts bundles', false, String(e.message ?? e).split('\n')[0]);
  }
  if (pure) {
    const { settleOffset, STAND_ADOPT_M } = pure;
    const P = { x: 2.0, z: 3.0 };
    const same = (o, x, z) => !!o && Math.abs(o.x - x) < 1e-9 && Math.abs(o.z - z) < 1e-9;
    const show = (o) => (o ? `(${o.x.toFixed(4)}, ${o.z.toFixed(4)})` : 'null');
    let o = settleOffset({ x: 2.12, z: 3.0 }, P, P);
    check('[P1] 0.12 m off → (0.12, 0)', same(o, 0.12, 0), show(o));
    o = settleOffset({ x: 2.40, z: 3.0 }, P, P);
    check('[P2] 0.40 m off → null', o === null, show(o));
    o = settleOffset({ x: 2.09, z: 2.88 }, P, P);
    check('[P3] diagonal 0.15 m off → (0.09, −0.12)', same(o, 0.09, -0.12), show(o));
    o = settleOffset({ x: 2.0, z: 3.25 }, P, P);
    check('[P4] exactly 0.25 m off → kept (inclusive bound)', same(o, 0, 0.25), show(o));
    o = settleOffset({ x: 2.0, z: 3.2501 }, P, P);
    check('[P4] 0.2501 m off → null', o === null, show(o));
    o = settleOffset({ x: 2.12, z: 3.0 }, { x: 2.01, z: 3.0 }, P);
    check('[P5] the server moved 1 cm → null', o === null, show(o));
    o = settleOffset({ x: 2.12, z: 3.0 }, { x: 2.0004, z: 3.0 }, P);
    check('[P5] 0.4 mm float noise → the offset from the new point (0.1196, 0)', same(o, 0.1196, 0), show(o));
    check('[P6] STAND_ADOPT_M = the pick_stand raster step 0.25', STAND_ADOPT_M === 0.25, String(STAND_ADOPT_M));
  }

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
    beginBridgeLift: () => false, shiftBridgeLift: () => false, dispose() {},
  });
  const SEAT = new THREE.Vector3(1.6, 0, 3.0);
  const P = new THREE.Vector3(2.0, 0, 3.0);
  const npcOn = (name, travel, player = false) => {
    const mgr = new NpcManager(null);
    const root = new THREE.Group();
    root.position.copy(SEAT);
    const npc = {
      name, animation: 'idle', root, figure: stubFigure(travel), ring: null, sprite: null,
      label: { visible: false }, labelName: { textContent: '' }, labelActivity: { textContent: '' },
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
