#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/bridge_lift.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_bridge_lift.mjs
 *         (bundles the client modules itself; part [V] reads the clips
 *          idle, walk, get-up-bed, get-up-chair, the pair half greeting-handshake__a
 *          and the two clips the bridges leave from shared/models/clips —
 *          READ ONLY)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { bridgeSourceClip } from './bridgeSources.mjs';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const CLIP_DIR = join(ROOT, 'shared/models/clips');
const RIG_FILE = join(ROOT, 'shared/models/rig/reference.fbx');
const MODELS = join(ROOT, 'client3d/public/models');
const FPS = 30;
const DT = 1 / FPS;
const FLOOR = 0.01;               // floor 0 + WALK_CLEARANCE_M: the root goal
const LIE_ROOT_DROP = 0.001;      // pose_catalog groups.lie.root_drop
const SEAT_ROOT_DROP = 0.234;     // pose_catalog groups.seat.root_drop
const BEDS = [0.46, 0.60];
const SEAT = 0.45;
const YAW = 0.7;
const LEAD = 0.3;
const WALK_SPEED = 3.4;
const V1_MIN = -0.05;
const V2_TOL = 0.015;
const V3_LO = -0.02;
const V3_HI = 0.03;
const V3_SPAN_S = 0.5;
const V4_AFTER_S = 1.0;
const V4_ROOT_TOL = 0.01;
const V4_FOOT_TOL = 0.02;
const RED_MAX = -0.25;
const PAIR_CLIP = 'greeting-handshake__a';  // tracked pair half (smoke_clip_pair)
const PAIR_AT_S = 0.8;            // bridge clip time the pair takes the figure
const PAIR_FADE_S = 0.25;         // playPair's crossfade
const PAIR_CHECK_S = 0.3;         // when [P2]/[P3] measure, after the takeover
const PAIR_END_S = 0.5;           // the interaction ends, [P4]
const P_SAME_TOL = 0.001;

globalThis.self = globalThis;
if (!globalThis.window) globalThis.window = globalThis;
if (!globalThis.document) {
  globalThis.document = {
    createElement: () => ({ style: {}, getContext: () => null, setAttribute() {} }),
  };
}
console.info = () => {};

let failed = 0;
let passed = 0;
function check(label, ok, detail) {
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
const cm = (m) => `${(m * 100).toFixed(2)} cm`;

/** Bundle the client modules into ONE file next to this script (three stays
 *  external so the bundle and this script share one three). */
async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src');
    const entry = [
      `export { BRIDGE_FADE_IN_S, LIFT_RAMP_S, fadeCarry, liftAt, liftRamp, clipBridgeLift,`
        + ` setClipBridgeLift } from '${src}/scene/bridgeLift';`,
      `export { rootPathAt, toWorld } from '${src}/scene/bridgeTravel';`,
      `export { adaptExternalClips, extractRootPath, Figure, setClipRootMotion } from '${src}/scene/figures';`,
      `export { relockRootPaths } from '${src}/scene/footLockMeasure';`,
      `export { measureGroundOffsets } from '${src}/scene/clipGround';`,
      `export { NpcManager } from '${src}/scene/npcs';`,
      `export { STAND_ADOPT_M } from '${src}/scene/standSettle';`,
      `export { moveClip, setClipTransitions } from '${src}/game/walk';`,
      `export { getAnimationClips } from '${join(ROOT, 'hud/src')}/api';`,
      `export { restCorrections, restPoseOf, rigHipsHeight } from '@anima/scene-render';`,
    ].join('\n');
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'client.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'client.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const arrayBufferOf = (buf) => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const keyOf = (name) => name.replace(/^mixamorig:?/i, '').replace(/[^a-z0-9]/gi, '').toLowerCase();
const FOOT_KEYS = ['leftfoot', 'lefttoebase', 'rightfoot', 'righttoebase', 'lefttoeend', 'righttoeend'];
const TORSO_RE = /^(hips|spine\d*|neck|head|leftshoulder|rightshoulder)$/;

async function main() {
  const THREE = await import('three');
  const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
  const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
  const C = await loadClient();

  // Task 7, spec §7: dt=.1, walk=3.4 m/s => .34 m (an NPC's step does not
  // read the terrain's speed_factor; `npc.pace` is 1 for everybody but the
  // avatar); only walk_run boosts by 1.8 => .612 m. A waypoint adds 10 m to
  // dist, so it must never enable running for walk/swim/crawl. No rig needed.
  console.log('[M] terrain movement controls clips and pace');
  for (const [movement, clip, step] of [
    ['walk_run', 'run', .612], ['walk', 'walk', .34],
    ['swim', 'breast-stroke', .34], ['crawl', 'crawl', .34],
  ]) {
    const mgr = new C.NpcManager({}, {});
    const root = new THREE.Group();
    const npc = {name: 'movement-test', root, figure: null, sprite: null,
      label: {visible: false}, bubbleUntil: 0, target: new THREE.Vector3(20, 0, 0),
      waypoints: [new THREE.Vector3(20, 0, 0)], pace: 1, face: null,
      ride: null, route: null, travelling: false, interaction: null, settle: null};
    mgr.npcs.set(npc.name, npc);
    mgr.setTerrainMove(() => ({movement, scope: 'wilderness', speed: .5,
      sink: {move: 0, idle: 0}, water: null, swimFrom: 1}));
    check(`[M] ${movement} distant clip`, C.moveClip(movement, true) === clip);
    mgr.tick(.1, 10);
    near(`[M] ${movement} waypoint step`, root.position.x, step, 1e-9);
  }
  // Deliberately contradictory pose-keyed admin rules: the player must read
  // transition_clips, preserving its accel, and never use transitions.
  const originalFetch = globalThis.fetch;
  const payload = {clips: [], movement_poses: {walking: {kind: 'local-walk', public_kind: 'walk'}},
    transitions: [{from: 'lying', to: 'walking', kind: 'wrong-admin-rule'}],
    transition_clips: [{from: 'laying', to: 'local-walk', kind: 'get-up-bed', accel: .5}]};
  try {
    globalThis.fetch = async () => ({ok: true, json: async () => payload});
    const library = await C.getAnimationClips();
    check('[M] API movement poses', library.movement_poses.walking.kind === 'local-walk');
    check('[M] API uses clip transitions including accel',
      JSON.stringify(library.transition_clips) === JSON.stringify(payload.transition_clips));
  } finally { globalThis.fetch = originalFetch; }

  const vectors = await runBridgeVectors('bridge_lift');
  passed += vectors.passed; failed += vectors.failed;

  // ------------------------------------------------------------------ [V]
  const fbx = new FBXLoader();
  const loadClip = async (kind) => {
    const obj = fbx.parse(arrayBufferOf(await readFile(join(CLIP_DIR, `${kind}.fbx`))), '');
    const c = obj.animations[0].clone();
    c.name = kind;
    return c;
  };
  // The clips the bridges leave: named by the live table, tracked, or the
  // tracked fallback (`bridgeSources.mjs`); null = that part is skipped.
  const bedFrom = bridgeSourceClip(ROOT, 'get-up-bed', 'laying');
  const chairFrom = bridgeSourceClip(ROOT, 'get-up-chair', 'recovering');
  const FROM = { 'get-up-bed': bedFrom?.kind, 'get-up-chair': chairFrom?.kind };
  for (const [kind, src] of [['get-up-bed', bedFrom], ['get-up-chair', chairFrom]]) {
    console.log(src ? `\n[V] ${kind} leaves ${src.kind} — ${src.note}` : `\n[V] ${kind}: SKIPPED (see above)`);
  }
  const KINDS = ['idle', 'walk', 'get-up-bed', 'get-up-chair', PAIR_CLIP,
    ...[bedFrom, chairFrom].filter(Boolean).map((x) => x.kind)];
  const side = {};
  const raw = {};
  for (const k of KINDS) {
    try {
      side[k] = JSON.parse(await readFile(join(CLIP_DIR, `${k}.json`), 'utf8'));
    } catch {
      side[k] = {};   // a clip without a sidecar carries no root motion
    }
    raw[k] = await loadClip(k);
  }
  // The pair clip's root path, kept aside BEFORE the adaptation strips the
  // hips' XZ — exactly what `FigureLibrary` does (`pairRoots`). The stand-in
  // library below answers the one question `tickInteraction` asks of it.
  const pairPath = C.extractRootPath(raw[PAIR_CLIP]);
  // Like the library it also names the clip's contact pivot (the sidecar's `pair_pivot_cm`, absent = the origin).
  const pv = side[PAIR_CLIP]?.pair_pivot_cm;
  const pairPivot = Array.isArray(pv) ? { x: pv[0] / 100, z: pv[1] / 100 } : { x: 0, z: 0 };
  const pairLib = { pairRootAt: (clip, t) => (clip === PAIR_CLIP ? { ...C.rootPathAt(pairPath, t), pivot: pairPivot } : null) };
  const refRig = fbx.parse(arrayBufferOf(await readFile(RIG_FILE)), '');
  const donorRest = C.restPoseOf(THREE, refRig);
  const donorHipsY = C.rigHipsHeight(THREE, refRig);
  C.setClipTransitions([bedFrom, chairFrom].map((src, i) => src && {
    from: src.kind, to: '*', kind: i === 0 ? 'get-up-bed' : 'get-up-chair', accel: 0 }).filter(Boolean));
  const loadGlb = async (file) => {
    const bytes = arrayBufferOf(await readFile(file));
    const gltf = await new Promise((res, rej) => new GLTFLoader().parse(bytes, '', res, rej));
    gltf.scene.updateMatrixWorld(true);
    return gltf.scene;
  };
  const RIGS = [
    { label: 'Test3_mia', load: () => loadGlb(join(MODELS, 'Test3_mia.glb')), height: 1.70 },
    { label: 'Soldier', load: () => loadGlb(join(MODELS, 'Soldier.glb')), height: 1.70 },
    { label: 'reference', load: async () => fbx.parse(arrayBufferOf(await readFile(RIG_FILE)), ''),
      scale: 0.01, height: side['get-up-bed'].geometry.root_motion.ref_height_m },
  ];
  const v = new THREE.Vector3();

  const redNpc = [];
  for (const rig of RIGS) {
    const template = await rig.load();
    template.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(template);
    const scale = rig.scale ?? 1.70 / (box.max.y - box.min.y);
    const H = rig.height;
    const corr = C.restCorrections(THREE, donorRest, template);
    const lib = C.adaptExternalClips(KINDS.map((k) => {
      const c = raw[k].clone();
      c.name = k;
      const mode = side[k]?.geometry?.root_motion?.mode;
      if (mode === 'keep' || mode === 'foot_lock') C.setClipRootMotion(c, true);
      return c;
    }), template, corr, donorHipsY);
    C.relockRootPaths(lib, template, 1 / (100 * scale));
    C.measureGroundOffsets(lib, template);
    const clipOf = (k) => lib.find((c) => c.name === k);
    const lifts = {};
    for (const k of ['get-up-bed', 'get-up-chair']) {
      lifts[k] = C.clipBridgeLift(clipOf(k));
      console.log(`\n[V] ${rig.label}: ${k} endLift ${lifts[k] ? cm(lifts[k].endLift * scale) : 'NONE'}`
        + `, firstContactS ${lifts[k]?.firstContactS?.toFixed(3) ?? '—'} s (clip ${clipOf(k).duration.toFixed(3)} s)`);
    }
    check(`[V] ${rig.label}: both bridges carry a measured lift`, !!lifts['get-up-bed'] && !!lifts['get-up-chair']);

    /** [V3b] reference: the lowest foot over the root plane through a plain
     *  idle → walk crossfade (2 s of idle, then 15 frames of walk). */
    const plainDip = () => {
      const figure = new C.Figure({ name: rig.label, template, clips: lib, scale, height: H,
        assignOnly: true, noClips: false, tier: 'full', libraryFits: true });
      const owner = new THREE.Group();
      owner.add(figure.root);
      const feet = [];
      figure.root.children[0].traverse((o) => { if (o.isBone && FOOT_KEYS.includes(keyOf(o.name))) feet.push(o); });
      for (let i = 0; i < 2 * FPS; i++) { figure.play('idle', false, 0); figure.update(DT); }
      let dip = Infinity;
      for (let i = 0; i < 15; i++) {
        figure.play('walk', true, 0);
        figure.update(DT);
        owner.updateMatrixWorld(true);
        for (const b of feet) dip = Math.min(dip, b.getWorldPosition(v).y);
      }
      figure.dispose();
      return dip;
    };
    const walkDip = plainDip();
    console.log(`  info [V3b] ${rig.label}: plain idle → walk crossfade, lowest foot over the root ${cm(walkDip)}`);

    /** One figure lying / sitting on its slot, the stand-up, and every frame
     *  measured until `afterS` past the bridge. */
    const run = (scenario, bridgeKind, S, { liftOff = false, lateFloorS = 0, pairAtS = 0 } = {}) => {
      const fromKind = FROM[bridgeKind];
      const drop = (bridgeKind === 'get-up-bed' ? LIE_ROOT_DROP : SEAT_ROOT_DROP) * H;
      const saved = clipOf(bridgeKind) && C.clipBridgeLift(clipOf(bridgeKind));
      if (liftOff) C.setClipBridgeLift(clipOf(bridgeKind), null);
      const figure = new C.Figure({ name: rig.label, template, clips: lib, scale, height: H,
        assignOnly: true, noClips: false, tier: 'full', libraryFits: true });
      const owner = new THREE.Group();
      owner.add(figure.root);
      const inst = figure.root.children[0];
      const groundY = inst.position.y;
      const feet = [];
      const torso = [];
      inst.traverse((o) => {
        if (!o.isBone) return;
        const k = keyOf(o.name);
        if (FOOT_KEYS.includes(k)) feet.push(o);
        if (TORSO_RE.test(k)) torso.push(o);
      });
      const name = `${rig.label}-${scenario}`;
      const npc = {
        name, animation: fromKind, root: owner, figure, ring: null, sprite: null,
        label: { visible: false }, labelName: { textContent: '' }, labelActivity: { textContent: '' }, labelBadges: { textContent: '' },
        labelBubble: null, bubbleUntil: 0, target: new THREE.Vector3(), pace: 1, face: null,
        waypoints: [], ride: null, route: null, travelling: false, reckon: null,
        interaction: null, activity: '', travelLine: null, travelKey: '', bobPhase: 0,
        settle: null,
      };
      const mgr = new C.NpcManager(pairLib, {
        syncCounters: { posCorr: 0, pos409: 0, travBack: 0, travFwd: 0, travErrMaxM: 0, arrive: 0, place: 0 },
        errWindow: { t: [], e: [] },
      });
      mgr.npcs.set(name, npc);
      const seat = new THREE.Vector3(0, S - drop, 0);
      const avatar = scenario !== 'npc';
      if (avatar) {
        mgr.setPlayerDriven(name);
        mgr.snapPlayerTo(name, seat);
        mgr.setPlayerAnimation(name, fromKind);
      } else {
        owner.position.copy(seat);
        npc.target.copy(seat);
      }
      figure.faceTowards(new THREE.Vector3(Math.sin(YAW), 0, Math.cos(YAW)), true);
      for (let i = 0; i < 20; i++) mgr.tick(0.05, 10);
      // The server's stand point: the slot + the clip's travel at this height.
      const rm = side[bridgeKind].geometry.root_motion;
      const k = H / rm.ref_height_m;
      const sp = C.toWorld({ x: rm.travel_m[0] * k, z: rm.travel_m[1] * k }, YAW);
      const standPoint = new THREE.Vector3(sp.x, FLOOR, sp.z);
      /** The poll that carries the stand point — the REAL `update()`, since
       *  Task C4 decides the goal there (the point, or the spot the bridge
       *  left the figure on). */
      /** [P]: the pair interaction the server hands this NPC (null = none) —
       *  every poll carries it while it runs, as the worldmap does. */
      let pair = null;
      const poll = () => mgr.update([{ char: { name, activity: '', activity_animation: 'idle' },
        pos: standPoint.clone(), interaction: pair }]);
      const keyHeld = scenario === 'avatar_key';
      if (avatar) {
        mgr.setPlayerAnimation(name, keyHeld ? 'walk' : null);
        // `groundAvatarGoal` (main.ts); the counter-probe is the code before it.
        if (!liftOff) mgr.setPlayerTarget(name, new THREE.Vector3(owner.position.x, FLOOR, owner.position.z));
      } else {
        npc.animation = 'idle';
        // [V6]: the poll that brought the standing clip still carried the seat.
        if (!lateFloorS) poll();
      }
      const measure = () => {
        owner.updateMatrixWorld(true);
        let foot = Infinity;
        for (const b of feet) foot = Math.min(foot, b.getWorldPosition(v).y);
        let trunk = Infinity;
        for (const b of torso) trunk = Math.min(trunk, b.getWorldPosition(v).y);
        return { root: owner.position.y, drawn: owner.position.y + inst.position.y - groundY, foot, trunk };
      };
      const before = measure();
      const rows = [];
      let sinceUpdate = 0;
      let seen = false;
      let after = -1;
      let bridgeFrame = -1;
      /** the NPC kept the spot its bridge left it on (Task C4): it goes into
       *  idle, not walk */
      let settled = false;
      /** [P]: the frame index the pair took the figure, and the rows after it */
      let pairFrame = -1;
      const pairRows = [];
      for (let f = 0; f < FPS * 15; f++) {
        if (pairAtS && pairFrame < 0 && bridgeFrame >= 0 && (bridgeFrame + 1) * DT >= pairAtS - 1e-9) {
          pair = { id: 'p1', kind: PAIR_CLIP.split('__')[0], role: 'a', members: { a: name, b: 'nobody' },
            anchor: { x: standPoint.x, z: standPoint.z, yaw: YAW + Math.PI, place_id: null },
            started_at_game: 'Y0001-D001T00:00:00', elapsed_s: 0, rate: 1,
            clip_duration_s: raw[PAIR_CLIP].duration, loop: false };
          poll();
          sinceUpdate = 0;
          pairFrame = f;
        }
        if (pairFrame >= 0 && pair && (f - pairFrame) * DT >= PAIR_END_S - 1e-9) {
          pair = null;
          poll();
          sinceUpdate = 0;
        }
        const late = lateFloorS && f * DT < lateFloorS - 1e-9;
        if (!avatar && !late && (sinceUpdate >= 1.0 || (lateFloorS && Math.abs(f * DT - lateFloorS) < DT / 2))) {
          poll();
          sinceUpdate = 0;
        }
        if (avatar) {
          mgr.takePlayerTravel(name);
          if (keyHeld) {
            mgr.setPlayerAnimation(name, 'walk');
            if (mgr.paceLimitFor(name, 'walk') > 0) {
              mgr.setPlayerTarget(name, new THREE.Vector3(owner.position.x + Math.sin(YAW) * LEAD,
                FLOOR, owner.position.z + Math.cos(YAW) * LEAD));
            }
          }
        }
        mgr.tick(DT, 10);
        sinceUpdate += DT;
        if (pairFrame >= 0) {
          // read BEFORE `bridging` below, which could end a timed-out bridge
          const m = measure();
          pairRows.push({ ...m, s: (f - pairFrame + 1) * DT, lift: inst.position.y - groundY,
            bridging: figure.bridging, holdsHeight: figure.holdsHeight, holdsFacing: figure.holdsFacing,
            pace: figure.paceLimit, clipKind: figure.root.userData.clipKind });
          if ((f - pairFrame + 1) * DT > PAIR_END_S + 0.2) break;
          continue;
        }
        const bridging = figure.bridging;
        if (bridging) { seen = true; bridgeFrame += 1; }
        const m = measure();
        rows.push({ ...m, phase: bridging ? 'bridge' : seen ? 'after' : 'pre',
          clipT: bridging ? (bridgeFrame + 1) * DT : NaN });
        if (seen && !bridging) {
          // The hand-over runs in the first tick AFTER the one the bridge
          // ended in, so the spot is asked for on every frame after it.
          if (!avatar && npc.settle) settled = true;
          if (after < 0) after = 0;
          after += DT;
          if (after > V4_AFTER_S + 1e-9) break;
        }
      }
      figure.dispose();
      if (liftOff) C.setClipBridgeLift(clipOf(bridgeKind), saved);
      const br = rows.filter((r) => r.phase === 'bridge');
      const af = rows.filter((r) => r.phase === 'after');
      const startLift = (S - drop) - FLOOR;
      const spec = lifts[bridgeKind];
      // [V5]: the smoothstep's steepest frame, 1.5 · |Δ| / D · dt.
      const ramp = C.liftRamp(spec.firstContactS);
      const stepBound = 1.5 * Math.abs(spec.endLift * scale - startLift) / (ramp.to - ramp.from) * DT;
      let maxStep = 0;
      let prev = before.drawn;
      for (const x of rows.filter((x) => x.phase === 'bridge')) {
        maxStep = Math.max(maxStep, Math.abs(x.drawn - prev));
        prev = x.drawn;
      }
      return { before, rows, br, af, last: br[br.length - 1], startLift, lift: spec, ramp, stepBound, maxStep,
        settled, handOverM: settled ? Math.hypot(npc.settle.offset.x, npc.settle.offset.z) : NaN, pairRows };
    };
    const stepCheck = (label, r) => check(`${label}: no bridge frame moves the drawn root more than`
      + ` 1.5·|Δ|/D·dt = ${cm(r.stepBound)} (D ${(r.ramp.to - r.ramp.from).toFixed(3)} s)`,
    r.maxStep <= r.stepBound + 1e-4, cm(r.maxStep));

    for (const S of bedFrom ? BEDS : []) {
      for (const scenario of ['npc', 'avatar_key', 'avatar_idle']) {
        const r = run(scenario, 'get-up-bed', S);
        const tag = `${rig.label} bed ${S.toFixed(2)} ${scenario}`;
        if (!r.last) { check(`[V] ${tag}: the bridge ran`, false); continue; }
        const onBed = r.br.filter((x) => x.clipT < r.ramp.from);
        const trunkMin = Math.min(...onBed.map((x) => x.trunk - S));
        if (scenario === 'npc') {
          const lay = r.before.trunk - S;
          const bound = Math.min(0, lay) + V1_MIN;
          console.log(`  info [V1] ${tag}: lying (before the bridge) trunk − S ${cm(lay)}`);
          check(`[V1] ${tag}: trunk − S >= ${cm(bound)} until the ramp (${onBed.length} frames)`,
            trunkMin >= bound, cm(trunkMin));
        }
        const footEnd = r.last.foot - FLOOR;
        check(`[V2] ${tag}: last bridge frame, lowest foot − floor within ±1.5 cm`,
          Math.abs(footEnd) <= V2_TOL, cm(footEnd));
        stepCheck(`[V5b] ${tag}`, r);
        const span = [r.last, ...r.af.filter((_, i) => (i + 1) * DT <= V3_SPAN_S + 1e-9)]
          .map((x) => x.foot - FLOOR);
        const lo = Math.min(...span);
        const hi = Math.max(...span);
        if (scenario === 'npc') {
          // Which of [V3a]/[V3b] applies is picked by `r.settled` below, so a
          // broken settle would only switch the NPC to the walk bounds. This
          // check makes it fail instead: every rig settles (see [V3a]).
          check(`[V3a] ${tag}: the NPC keeps its spot, within STAND_ADOPT_M ${cm(C.STAND_ADOPT_M)} of the stand point`,
            r.settled && r.handOverM <= C.STAND_ADOPT_M,
            r.settled ? `${cm(r.handOverM)} off → into idle` : 'no settle → walks on to the stand point');
        }
        if (scenario === 'avatar_idle' || r.settled) {
          check(`[V3a] ${tag}: into idle, lowest foot − floor in −2 … +3 cm through 0.5 s after`,
            lo >= V3_LO && hi <= V3_HI, `${cm(lo)} … ${cm(hi)}`);
        } else {
          const floorBound = walkDip - V2_TOL;
          check(`[V3b] ${tag}: into walk, lowest foot − floor in ${cm(floorBound)} … +3 cm through 0.5 s after`,
            lo >= floorBound && hi <= V3_HI, `${cm(lo)} … ${cm(hi)}`);
        }
        if (scenario === 'avatar_idle') {
          const end = r.af[r.af.length - 1];
          check(`[V4] ${tag}: 1 s after, root on the floor (±1 cm)`,
            Math.abs(end.root - FLOOR) <= V4_ROOT_TOL, cm(end.root - FLOOR));
          check(`[V4] ${tag}: 1 s after, idle feet within ±2 cm of the floor`,
            Math.abs(end.foot - FLOOR) <= V4_FOOT_TOL, cm(end.foot - FLOOR));
        }
      }
      // COUNTER-PROBE: the lift removed from the clip (today's chain).
      for (const scenario of ['npc', 'avatar_idle']) {
        const r = run(scenario, 'get-up-bed', S, { liftOff: true });
        const footEnd = r.last.foot - FLOOR;
        if (scenario === 'npc') {
          redNpc.push(footEnd);
          check(`[V2] COUNTER-PROBE ${rig.label} bed ${S.toFixed(2)} npc, lift off: feet <= −25 cm`,
            footEnd <= RED_MAX, cm(footEnd));
        } else {
          const end = r.af[r.af.length - 1];
          console.log(`  info [V2/V4] COUNTER-PROBE ${rig.label} bed ${S.toFixed(2)} avatar without input,`
            + ` lift off: last bridge frame ${cm(footEnd)}, 1 s after root ${cm(end.root - FLOOR)} / feet ${cm(end.foot - FLOOR)}`);
        }
      }
    }

    // [V6] the floor arrives 0.5 s after the bridge opened on the seat.
    if (bedFrom) {
      const S = BEDS[0];
      const r = run('npc', 'get-up-bed', S, { lateFloorS: 0.5 });
      const tag = `${rig.label} bed ${S.toFixed(2)} npc, floor 0.5 s late`;
      if (!r.last) check(`[V6] ${tag}: the bridge ran`, false);
      else {
        console.log(`  info [V6] ${tag}: ramp from ${r.ramp.from.toFixed(3)} s (after the late floor)`);
        const footEnd = r.last.foot - FLOOR;
        check(`[V6] ${tag}: last bridge frame, lowest foot − floor within ±1.5 cm`,
          Math.abs(footEnd) <= V2_TOL, cm(footEnd));
        stepCheck(`[V6] ${tag}`, r);
      }
    }

    // [P] a pair clip takes the NPC over PAIR_AT_S into get-up-bed.
    if (bedFrom) {
      /** Control: the same pair half on a figure that stood (idle, no
       *  bridge), measured the same PAIR_CHECK_S after the interaction came. */
      const pairControl = () => {
        const figure = new C.Figure({ name: rig.label, template, clips: lib, scale, height: H,
          assignOnly: true, noClips: false, tier: 'full', libraryFits: true });
        const owner = new THREE.Group();
        owner.add(figure.root);
        const feet = [];
        figure.root.children[0].traverse((o) => { if (o.isBone && FOOT_KEYS.includes(keyOf(o.name))) feet.push(o); });
        const name = `${rig.label}-pair-control`;
        const npc = {
          name, animation: 'idle', root: owner, figure, ring: null, sprite: null,
          label: { visible: false }, labelName: { textContent: '' }, labelActivity: { textContent: '' }, labelBadges: { textContent: '' },
          labelBubble: null, bubbleUntil: 0, target: new THREE.Vector3(0, FLOOR, 0), pace: 1, face: null,
          waypoints: [], ride: null, route: null, travelling: false, reckon: null,
          interaction: null, activity: '', travelLine: null, travelKey: '', bobPhase: 0, settle: null,
        };
        const mgr = new C.NpcManager(pairLib, {
          syncCounters: { posCorr: 0, pos409: 0, travBack: 0, travFwd: 0, travErrMaxM: 0, arrive: 0, place: 0 },
          errWindow: { t: [], e: [] },
        });
        mgr.npcs.set(name, npc);
        owner.position.set(0, FLOOR, 0);
        for (let i = 0; i < 2 * FPS; i++) mgr.tick(DT, 10);
        mgr.update([{ char: { name, activity: '', activity_animation: 'idle' }, pos: new THREE.Vector3(0, FLOOR, 0),
          interaction: { id: 'c1', kind: PAIR_CLIP.split('__')[0], role: 'a', members: { a: name, b: 'nobody' },
            anchor: { x: 0, z: 0, yaw: YAW + Math.PI, place_id: null }, started_at_game: 'Y0001-D001T00:00:00',
            elapsed_s: 0, rate: 1, clip_duration_s: raw[PAIR_CLIP].duration, loop: false } }]);
        let foot = Infinity;
        for (let i = 0; i < Math.round(PAIR_CHECK_S / DT); i++) mgr.tick(DT, 10);
        owner.updateMatrixWorld(true);
        for (const b of feet) foot = Math.min(foot, b.getWorldPosition(v).y);
        const out = { foot, root: owner.position.y };
        figure.dispose();
        return out;
      };
      const S = BEDS[0];
      const tag = `${rig.label} bed ${S.toFixed(2)} npc, pair ${PAIR_CLIP} at ${PAIR_AT_S} s`;
      const r = run('npc', 'get-up-bed', S, { pairAtS: PAIR_AT_S });
      const rows = r.pairRows;
      const ctl = pairControl();
      if (!rows.length) check(`[P] ${tag}: the pair took the figure`, false);
      else {
        const first = rows[0];
        const at = rows.find((x) => Math.abs(x.s - PAIR_CHECK_S) < DT / 2);
        const endRows = rows.filter((x) => x.s >= PAIR_END_S + 2 * DT - 1e-9);
        const floor = at.root;   // the anchor's floor: tickInteraction puts the root on it
        console.log(`  info [P] ${tag}: lift at the takeover frame ${cm(first.lift)}, the anchor floor y ${cm(floor)},`
          + ` control (stood, no bridge) lowest foot ${cm(ctl.foot - ctl.root)} over its root`);
        check(`[P1] ${tag}: the takeover frame releases the bridge (bridging, holdsHeight, holdsFacing false; pace 1)`,
          !first.bridging && !first.holdsHeight && !first.holdsFacing && first.pace === 1,
          `bridging ${first.bridging}, holdsHeight ${first.holdsHeight}, holdsFacing ${first.holdsFacing}, pace ${first.pace}`);
        check(`[P2] ${tag}: ${PAIR_CHECK_S} s after, the lift is 0 (the ${PAIR_FADE_S} s fade is over)`,
          at && Math.abs(at.lift) <= 1e-6, at ? cm(at.lift) : 'no row');
        check(`[P2] ${tag}: ${PAIR_CHECK_S} s after, lowest foot = the control's (±1 mm)`,
          at && Math.abs((at.foot - floor) - (ctl.foot - ctl.root)) <= P_SAME_TOL,
          at ? `${cm(at.foot - floor)} vs ${cm(ctl.foot - ctl.root)}` : 'no row');
        check(`[P4] ${tag}: the interaction ends at ${PAIR_END_S} s → the next play() is not blocked`,
          endRows.length > 0 && endRows.every((x) => x.clipKind !== PAIR_CLIP && !x.bridging),
          endRows.map((x) => x.clipKind).join(',') || 'no row');
      }
    }

    for (const scenario of chairFrom ? ['npc', 'avatar_idle'] : []) {
      const r = run(scenario, 'get-up-chair', SEAT);
      const tag = `${rig.label} chair ${SEAT.toFixed(2)} ${scenario}`;
      if (!r.last) { check(`[V5] ${tag}: the bridge ran`, false); continue; }
      const footEnd = r.last.foot - FLOOR;
      check(`[V5] ${tag}: last bridge frame, lowest foot − floor within ±1.5 cm`,
        Math.abs(footEnd) <= V2_TOL, cm(footEnd));
      stepCheck(`[V5] ${tag}`, r);
      const span = [r.last, ...r.af.filter((_, i) => (i + 1) * DT <= V3_SPAN_S + 1e-9)]
        .map((x) => x.foot - FLOOR);
      console.log(`  info [V5] ${tag}: 0.5 s after the bridge lowest foot − floor ${cm(Math.min(...span))} … ${cm(Math.max(...span))}`);
    }
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
