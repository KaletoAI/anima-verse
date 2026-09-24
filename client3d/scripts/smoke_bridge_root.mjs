#!/usr/bin/env node
/**
 * Smoke check for BRIDGE CLIPS WITH ROOT MOTION — `client3d/src/scene/bridgeTravel.ts`
 * and its consumer `figures.Figure` (§ B5a: numbers, never screenshots).
 *
 * Usage:  node client3d/scripts/smoke_bridge_root.mjs
 *         (bundles the client modules itself; part [B] needs the re-imported
 *          `get-up-chair` / `get-up-bed` in shared/models/clips — READ ONLY)
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Every clip used to play "in place": `adaptExternalClips` throws the hips'
 * horizontal track away, so a figure standing up out of a chair kept its hips
 * over the seat while the legs pushed it forward — the feet slid ~0.4 m over
 * the floor. The importer can now bake a FOOT-LOCKED travel into the hips
 * track (`root_motion.mode = foot_lock`), and the client carries the figure
 * along that travel while the bridge plays, then hands the offset to whoever
 * owns the figure's position (`Figure.takeTravel`).
 *
 * ---------------------------------------------------------------------------
 * [A] pure arithmetic and the Figure's bookkeeping (no clip files needed)
 * ---------------------------------------------------------------------------
 * [1] travelAt: path times [0, 1, 2], xz [0,0, 0,0.2, 0,0.4] (metres):
 *       t=0 → (0,0); t=0.5 → (0,0.1) (half way between the keys 0 and 0.2);
 *       t=2 → (0,0.4); t=5 (past the end) → (0,0.4) (clamped);
 *       t=-1 → (0,0) (clamped). The offset is RELATIVE to frame 0: a path
 *       starting at (0.1, 0.1) with the same steps gives the same answers.
 * [2] toWorld((0, 0.4), yaw 0) → (0, 0.4); yaw π/2 → (0.4, 0) (x' = 0·0 +
 *       0.4·1, z' = −0·1 + 0.4·0); yaw π → (0, −0.4);
 *       toWorld((0.1, 0), π/2) → (0, −0.1) (x' = 0.1·0 + 0, z' = −0.1·1).
 *       (Compass facing f is three.js rotation.y = f: forward (sin f, cos f);
 *       the figure's left at facing 0 is +x, at facing 90° it is −z.)
 * [3] Figure with a root-motion bridge (accel 0), on a real rig with a
 *       SYNTHETIC library whose numbers are chosen so
 *       the travel is known by hand (on `Soldier.glb`, whose origin is at
 *       its feet — `Test3_mia` is centred on its hips): every clip holds the hips at 100 source
 *       units (so the standing reference `sourceRest` = 100), and the bridge
 *       moves the hips from (0, 100, 0) to (10, 100, 40). The client scales a
 *       hips length by k = H_t / 100 (H_t = the rig's rest hips height in
 *       template units) and the instance by s = 1.70 / rawHeight, so the
 *       travel in world metres is
 *           (10, 40) · k · s = (0.1, 0.4) · H,   H = H_t · s,
 *       H being the figure's rest hips height in world metres (read off the
 *       template here, not out of the Figure). Facing yaw = 0.6 rad. After
 *       the clip ends: holdsTravel true, takeTravel() = toWorld((0.1H, 0.4H),
 *       0.6) to 1e-4; the instance is back on its base XZ; a second
 *       takeTravel() returns null.
 *       [3b] Rule 5: a SECOND bridge started while the first travel is still
 *       held warns once and folds the held offset into the new one — the
 *       final takeTravel() is twice the single travel.
 * [4] The same clip as a RAMPING bridge (accel 1): no offset during or after
 *       (holdsTravel false, instance XZ on its base) — the figure walks off
 *       by itself.
 *       (The reference-rig hips height handed to `adaptExternalClips` is 100
 *       source units too — the synthetic "rig" the clips were authored on.)
 * [8] No reference rig served (`donorHipsY` undefined or NaN): the travel
 *       cannot be scaled, so there is none — the bridge plays in place, no
 *       hold, the instance never leaves its base and never turns NaN, and one
 *       console.warn covers the session (two adaptations, one line).
 * [5] Bridge ended, nobody took the travel yet, three more update() frames
 *       (with the next clip asked for, as `npcs.tick` does): instance x/z
 *       unchanged (no snap back to the seat).
 *
 * ---------------------------------------------------------------------------
 * [B] the whole chain on REAL rigs, measured at the CONSUMER
 * ---------------------------------------------------------------------------
 * `Test3_mia.glb` (server mesh pipeline), `Soldier.glb` (Mixamo fallback
 * rig) and the reference rig itself (see THE SCALE), the real neutral clips (`idle` gives the standing reference, the
 * seat/bed clip is the state the bridge leaves), the reference rig's rest pose
 * for the bind-relative transplant (`restCorrections`, exactly what
 * `FigureLibrary` does when `/assets/animation-rig` is served), the real
 * `adaptExternalClips` and a real `Figure` inside an owner group that plays
 * the NPC root. What is measured is the WORLD XZ of the bones
 * `LeftFoot`/`LeftToeBase`/`RightFoot`/`RightToeBase` of the rendered
 * instance, frame by frame at 30 fps (the clips' own rate).
 *
 * WHICH POINT IS PLANTED, WHEN: the importer's OWN classification, not a
 * second opinion. `_root_motion.contact_weights` is re-run on the REFERENCE
 * rig with the RAW clip (travel included): height over the point's own
 * 5th-percentile ground (clamped to its rest height) within 2 cm and vertical
 * speed under 15 cm/s give full weight. Cross-check: the drift of those runs
 * on the reference rig must stay within the sidecar's `max_drift_cm`
 * (+0.05 cm) — measured 0.42 for the chair (sidecar 0.42) and 1.31 for the bed
 * (sidecar 1.44). A point the importer never verified (the chair's right foot
 * hovers 2–4.7 cm in every standing frame on the reference rig and slides
 * ~2.3 cm there) is therefore never counted; its wander over the window is
 * printed as info.
 *
 * Contact windows: the sidecar's `root_motion.contact_s`; figure frame i was
 * sampled at clip time (i+1)/30 = reference frame i+1. The first 0.30 s of
 * the bridge are left out: the bridge fades in over 0.25 s from the seat clip,
 * and those frames show the blend of two poses, not the clip. Drift = the
 * largest horizontal distance a verified point moves from where its run of
 * full-contact frame pairs began.
 *
 * THE SCALE, proven on the reference rig itself as a third figure (life-size,
 * its centimetres × 0.01, no proportions to adapt): whatever the client chain
 * adds to the importer's drift there is the chain's own error. The travel is
 * scaled by target rest hips / REFERENCE-RIG rest hips (113.03 units). The
 * bounce's own denominator, the idle clip's hips median (110.18), is 2.6 %
 * short of the rig and makes every travel 2.6 % too long.
 *
 * [6] foot_lock clips: planted-foot drift per contact run, bound PER CLIP
 *       (ruling 2026-09-25):
 *         get-up-chair, real rigs   <= 2.5 cm (1.5 cm importer limit + the
 *                                   rig's own proportions)
 *         get-up-bed, real rigs     <= 5.0 cm — the bed turns ~90° while it
 *                                   rises, and what is left on a real rig is
 *                                   that rig's proportions: the chain is exact
 *                                   on the reference rig (below), and a sweep
 *                                   of one global travel factor finds none
 *                                   that brings the bed under 2.5 cm on both
 *                                   rigs (best ~2.6 / ~3.2 cm, each at another
 *                                   factor, the chair worse there). Option B,
 *                                   a per-rig foot lock in the client, is the
 *                                   follow-up that would take it out.
 *         reference rig, both       <= 1.5 cm — the importer's own guarantee
 *       Measured 2026-09-25 (verified contacts, cm): chair Test3_mia 2.20,
 *       Soldier 1.09, reference 0.30; bed Test3_mia 4.76, Soldier 2.95,
 *       reference 1.31.
 *       RED COUNTER-PROBE: the same measurement with the offset switched off
 *       (the library adapted WITHOUT the root-motion flag — the pre-plan
 *       behaviour): get-up-chair >= 15 cm (its travel is 0.49 m on the
 *       reference rig, ~0.4 m on a 1.70 m figure, and the standing phase
 *       alone walks ~0.2 m of it; measured 20.3 / 23.8 cm); get-up-bed
 *       >= 25 cm (measured 37.2 / 44.7 cm on Test3_mia / Soldier).
 *       Reference rig only: the chain adds nothing on its own rig — drift
 *       <= the importer's own number there + 0.10 cm. RED COUNTER-PROBE: the
 *       idle-median scale overshoots that (chair 0.73 vs 0.42, bed 2.15 vs
 *       1.31 when this was written).
 * [7] End of bridge + takeTravel + owner root moved by it: the rendered foot
 *       positions of the last bridge frame and of the frame after the
 *       hand-over (no time advanced, so the only change is the hand-over)
 *       differ by <= 1 cm. RED COUNTER-PROBE: takeTravel WITHOUT moving the
 *       owner jumps the feet by the whole travel (>= 30 cm for the chair).
 *       The next real frame (next clip asked for, dt = 1/30) is printed.
 *   info  The largest horizontal travel of the LOWEST foot point over the
 *       WHOLE bridge (runs of frames in which the same point is the lowest),
 *       offset on and off — the partially planted phase the converter does
 *       not verify.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const CLIP_DIR = join(ROOT, 'shared/models/clips');
const RIG_FILE = join(ROOT, 'shared/models/rig/reference.fbx');
const MODELS = join(ROOT, 'client3d/public/models');
const RIGS = [join(MODELS, 'Test3_mia.glb'), join(MODELS, 'Soldier.glb')];
const FPS = 30;
/** The bridges part [B] walks: the clip, the state it leaves, the hard
 *  counter-probe floor (null = printed only). */
/** Planted-foot drift bounds (see [6] in the docstring for the numbers).
 *  The chair: importer limit + rig proportions. The bed turns ~90° while it
 *  rises, and what it leaves on a real rig is that rig's proportions — a
 *  single travel scale cannot take it out (option B, a per-rig foot lock in
 *  the client, is the follow-up). The REFERENCE rig has no proportions to
 *  adapt: there the importer's own guarantee (1.5 cm) holds for both. */
const CHAIR_DRIFT_MAX_M = 0.025;
const BED_DRIFT_MAX_M = 0.05;
const REF_DRIFT_MAX_M = 0.015;
/** RED counter-probes, offset off: chair from the brief; bed derived from the
 *  measured 37.2 (Test3_mia) / 44.7 (Soldier) cm with room to spare. */
const CHAIR_RED_MIN_M = 0.15;
const BED_RED_MIN_M = 0.25;
const BRIDGES = [
  { kind: 'get-up-chair', from: 'sitting-in-chair', driftMax: CHAIR_DRIFT_MAX_M, redMin: CHAIR_RED_MIN_M },
  { kind: 'get-up-bed', from: 'sleeping-side', driftMax: BED_DRIFT_MAX_M, redMin: BED_RED_MIN_M },
];
const HANDOVER_MAX_M = 0.01;
const FADE_SKIP_S = 0.30;
/** `_root_motion.py` contact bands on the reference rig (cm, cm/s). */
const BAND_LO_CM = 2.0;
const BAND_HI_CM = 5.0;
const VY_LO_CM_S = 15.0;
const VY_HI_CM_S = 30.0;
const GROUND_PCT = 0.05;
const FULL = 0.999;

globalThis.self = globalThis;
if (!globalThis.window) globalThis.window = globalThis;
if (!globalThis.document) {
  globalThis.document = {
    createElement: () => ({ style: {}, getContext: () => null, setAttribute() {} }),
  };
}

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
    `${Number(actual).toFixed(5)} (expected ${expected} ±${eps})`);
const cm = (m) => `${(m * 100).toFixed(2)} cm`;

/** Bundle the client modules into ONE file next to this script (three stays
 *  external so the bundle and this script share one three). */
async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src');
    const entry = [
      `export { travelAt, toWorld, rootPathAt } from '${src}/scene/bridgeTravel';`,
      `export { adaptExternalClips, Figure, rigHipsHeight, setClipRootMotion } from '${src}/scene/figures';`,
      `export { setClipTransitions } from '${src}/game/walk';`,
      `export { restCorrections, restPoseOf } from '@anima/scene-render';`,
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

function arrayBufferOf(buf) {
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

const FOOT_KEYS = ['leftfoot', 'lefttoebase', 'rightfoot', 'righttoebase'];
const keyOf = (name) => name.replace(/^mixamorig:?/i, '').replace(/[^a-z0-9]/gi, '').toLowerCase();

async function main() {
  const THREE = await import('three');
  const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
  const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
  const client = await loadClient();
  const { travelAt, toWorld, adaptExternalClips, Figure, rigHipsHeight, setClipRootMotion,
          setClipTransitions, restCorrections, restPoseOf } = client;

  const loadRig = async (file) => {
    const bytes = arrayBufferOf(await readFile(file));
    const gltf = await new Promise((res, rej) =>
      new GLTFLoader().parse(bytes, '', res, rej));
    const template = gltf.scene;
    template.updateMatrixWorld(true);
    return template;
  };
  const hipsOf = (obj) => {
    let hips = null;
    obj.traverse((o) => { if (o.isBone && /hips$/i.test(o.name) && !hips) hips = o; });
    return hips;
  };
  /** `scale` given = the instance scale as is (the reference rig has no mesh
   *  to measure, and its centimetres ARE the importer's); otherwise the
   *  figure is normalised to 1.70 m as `FigureLibrary` does. */
  const makeFigure = (label, template, clips, fixedScale) => {
    const bbox = new THREE.Box3().setFromObject(template);
    const rawHeight = bbox.max.y - bbox.min.y;
    const scale = fixedScale ?? 1.70 / rawHeight;
    const figure = new Figure({
      name: label, template, clips, scale, height: 1.70, assignOnly: true,
      noClips: false, tier: 'full', libraryFits: true,
    });
    const owner = new THREE.Group();
    owner.add(figure.root);
    return { figure, owner, scale, inst: figure.root.children[0] };
  };

  // ------------------------------------------------------------------ [A]
  console.log('[1] travelAt — relative to frame 0, clamped (hand cases)');
  const toy = { times: new Float32Array([0, 1, 2]), xz: new Float32Array([0, 0, 0, 0.2, 0, 0.4]) };
  const moved = { times: new Float32Array([0, 1, 2]), xz: new Float32Array([0.1, 0.1, 0.1, 0.3, 0.1, 0.5]) };
  for (const [name, path] of [['origin path', toy], ['path from (0.1,0.1)', moved]]) {
    for (const [t, ex, ez] of [[0, 0, 0], [0.5, 0, 0.1], [2, 0, 0.4], [5, 0, 0.4], [-1, 0, 0]]) {
      const p = travelAt(path, t);
      check(`${name}: t=${t} → (${ex}, ${ez})`,
        Math.abs(p.x - ex) < 1e-6 && Math.abs(p.z - ez) < 1e-6,
        `(${p.x.toFixed(6)}, ${p.z.toFixed(6)})`);
    }
  }

  console.log('\n[2] toWorld — the rotation of npcs.tickInteraction (hand cases)');
  for (const [lx, lz, yaw, ex, ez, what] of [
    [0, 0.4, 0, 0, 0.4, 'yaw 0'], [0, 0.4, Math.PI / 2, 0.4, 0, 'yaw π/2'],
    [0, 0.4, Math.PI, 0, -0.4, 'yaw π'], [0.1, 0, Math.PI / 2, 0, -0.1, 'left at 90° is −z'],
  ]) {
    const p = toWorld({ x: lx, z: lz }, yaw);
    check(`toWorld((${lx}, ${lz}), ${what}) → (${ex}, ${ez})`,
      Math.abs(p.x - ex) < 1e-9 && Math.abs(p.z - ez) < 1e-9,
      `(${p.x.toFixed(9)}, ${p.z.toFixed(9)})`);
  }

  console.log('\n[3]–[5] the Figure with a synthetic root-motion bridge (Soldier)');
  // Soldier and not Test3_mia: the hand derivation needs the rig's rest hips
  // height, and Soldier stands with its feet on its origin (hips at 1.061
  // template units), while Test3_mia is centred on its hips (y ≈ 0) and takes
  // the client's fallback factor instead.
  const synthRig = await loadRig(RIGS[1]);
  const synthBones = [];
  synthRig.traverse((o) => { if (o.isBone) synthBones.push(o); });
  const synthHips = hipsOf(synthRig);
  /** A synthetic clip: every bone held at its rest rotation, the hips at
   *  `from` → `to` (source units) over one second. */
  const synthClip = (name, from, to) => {
    const tracks = synthBones.map((b) => new THREE.QuaternionKeyframeTrack(
      `${b.name}.quaternion`, [0, 1], [...b.quaternion.toArray(), ...b.quaternion.toArray()]));
    tracks.push(new THREE.VectorKeyframeTrack(`${synthHips.name}.position`, [0, 1], [...from, ...to]));
    return new THREE.AnimationClip(name, 1, tracks);
  };
  /** `rigHeight`: the reference-rig hips height handed in — an explicit
   *  `undefined` is kept (a default parameter would swallow it). */
  const synthLibrary = ({ rigHeight } = { rigHeight: 100 }) => {
    const lib = [
      synthClip('idle', [0, 100, 0], [0, 100, 0]),
      synthClip('sit-synth', [0, 100, 0], [0, 100, 0]),
      synthClip('bridge-synth', [0, 100, 0], [10, 100, 40]),
    ];
    setClipRootMotion(lib[2], true);
    return adaptExternalClips(lib, synthRig, undefined, rigHeight);
  };
  const synthBbox = new THREE.Box3().setFromObject(synthRig);
  const H = synthHips.getWorldPosition(new THREE.Vector3()).y * (1.70 / (synthBbox.max.y - synthBbox.min.y));
  const YAW = 0.6;
  const expectLocal = { x: 0.1 * H, z: 0.4 * H };
  const expectWorld = toWorld(expectLocal, YAW);
  console.log(`      rest hips height H = ${H.toFixed(4)} m → expected travel`
    + ` local (${expectLocal.x.toFixed(4)}, ${expectLocal.z.toFixed(4)}),`
    + ` world at yaw ${YAW} (${expectWorld.x.toFixed(4)}, ${expectWorld.z.toFixed(4)})`);

  /** Seat the figure, turn it, open the bridge, run it to its end. Returns
   *  the instance XZ seen on every bridge frame and the frame count. */
  const runSynthBridge = (fig) => {
    fig.figure.faceTowards(new THREE.Vector3(Math.sin(YAW), 0, Math.cos(YAW)), true);
    fig.figure.play('sit-synth');
    for (let i = 0; i < 10; i++) fig.figure.update(0.05);
    fig.figure.play('idle');
    const bridged = fig.figure.bridging;
    const seen = [];
    let frames = 0;
    while (fig.figure.bridging && frames < 200) {
      fig.figure.update(1 / FPS);
      seen.push({ x: fig.inst.position.x, z: fig.inst.position.z, holds: fig.figure.holdsTravel });
      frames += 1;
    }
    return { bridged, seen, frames };
  };

  setClipTransitions([{ from: 'sit-synth', to: '*', kind: 'bridge-synth', accel: 0 }]);
  {
    const fig = makeFigure('synth', synthRig, synthLibrary());
    const base = { x: fig.inst.position.x, z: fig.inst.position.z };
    const run = runSynthBridge(fig);
    check('[3] the bridge opens', run.bridged, `${run.frames} frames`);
    const mid = run.seen[Math.floor(run.seen.length / 2)];
    check('[3] during the bridge the instance travels', !!mid
      && Math.hypot(mid.x - base.x, mid.z - base.z) > 0.05,
      mid ? cm(Math.hypot(mid.x - base.x, mid.z - base.z)) : 'no frame');
    check('[3] after the clip: holdsTravel', fig.figure.holdsTravel === true);
    const held = { x: fig.inst.position.x - base.x, z: fig.inst.position.z - base.z };
    near('[3] held offset (root frame) x = 0.1·H', held.x, expectLocal.x, 1e-4);
    near('[3] held offset (root frame) z = 0.4·H', held.z, expectLocal.z, 1e-4);
    // [5] three more frames, the next clip asked for as npcs.tick does
    for (let i = 0; i < 3; i++) {
      fig.figure.play('idle');
      fig.figure.update(1 / FPS);
    }
    near('[5] three frames later: instance x unchanged', fig.inst.position.x, base.x + held.x, 1e-9);
    near('[5] three frames later: instance z unchanged', fig.inst.position.z, base.z + held.z, 1e-9);
    const took = fig.figure.takeTravel();
    check('[3] takeTravel returns an offset', !!took);
    near('[3] takeTravel x = toWorld(travel, yaw).x', took?.x ?? NaN, expectWorld.x, 1e-4);
    near('[3] takeTravel z = toWorld(travel, yaw).z', took?.z ?? NaN, expectWorld.z, 1e-4);
    check('[3] …and holds nothing any more', fig.figure.holdsTravel === false);
    near('[3] the instance is back on its base x', fig.inst.position.x, base.x, 1e-9);
    near('[3] the instance is back on its base z', fig.inst.position.z, base.z, 1e-9);
    check('[3] a second takeTravel returns null', fig.figure.takeTravel() === null);

    // [3b] rule 5: a second bridge while the first travel is still held
    const warned = [];
    const warn = console.warn;
    console.warn = (...a) => warned.push(a.join(' '));
    try {
      runSynthBridge(fig);     // first travel, not taken
      runSynthBridge(fig);     // second bridge on top of it
    } finally {
      console.warn = warn;
    }
    check('[3b] a bridge over a held travel warns', warned.some((w) => /travel/i.test(w)),
      `${warned.length} warning(s)`);
    const twice = fig.figure.takeTravel();
    near('[3b] …and folds it in: takeTravel x = 2 × travel', twice?.x ?? NaN, 2 * expectWorld.x, 2e-4);
    near('[3b] …and folds it in: takeTravel z = 2 × travel', twice?.z ?? NaN, 2 * expectWorld.z, 2e-4);
    fig.figure.dispose();
  }

  setClipTransitions([{ from: 'sit-synth', to: '*', kind: 'bridge-synth', accel: 1 }]);
  {
    const fig = makeFigure('synth-ramp', synthRig, synthLibrary());
    const base = { x: fig.inst.position.x, z: fig.inst.position.z };
    const run = runSynthBridge(fig);
    check('[4] the ramping bridge opens', run.bridged, `${run.frames} frames`);
    const maxOff = Math.max(0, ...run.seen.map((s) => Math.hypot(s.x - base.x, s.z - base.z)));
    near('[4] no offset DURING a ramping bridge', maxOff, 0, 1e-9);
    check('[4] no hold during it', run.seen.every((s) => !s.holds));
    check('[4] no hold after it', fig.figure.holdsTravel === false);
    check('[4] takeTravel returns null', fig.figure.takeTravel() === null);
    fig.figure.dispose();
  }

  // [8] no reference rig served: the travel cannot be scaled, so there is
  // none — the clip plays in place, one warning for the whole session, and no
  // NaN reaches the instance (undefined and NaN both count as "no rig").
  setClipTransitions([{ from: 'sit-synth', to: '*', kind: 'bridge-synth', accel: 0 }]);
  {
    const warned = [];
    const warn = console.warn;
    console.warn = (...a) => warned.push(a.join(' '));
    let fig;
    let run;
    let base;
    try {
      synthLibrary({ rigHeight: NaN });
      fig = makeFigure('synth-norig', synthRig, synthLibrary({ rigHeight: undefined }));
      base = { x: fig.inst.position.x, z: fig.inst.position.z };
      run = runSynthBridge(fig);
    } finally {
      console.warn = warn;
    }
    const rigWarnings = warned.filter((w) => /reference rig/.test(w));
    check('[8] no rig: exactly one warning over two adaptations', rigWarnings.length === 1,
      `${rigWarnings.length}: ${rigWarnings[0] ?? '-'}`);
    check('[8] no rig: the bridge still plays', run.bridged, `${run.frames} frames`);
    check('[8] no rig: no hold during or after it',
      run.seen.every((f) => !f.holds) && fig.figure.holdsTravel === false);
    check('[8] no rig: the instance never leaves its base, never NaN',
      run.seen.every((f) => Number.isFinite(f.x) && Number.isFinite(f.z)
        && Math.abs(f.x - base.x) < 1e-9 && Math.abs(f.z - base.z) < 1e-9));
    check('[8] no rig: takeTravel returns null', fig.figure.takeTravel() === null);
    fig.figure.dispose();
  }

  // ------------------------------------------------------------------ [B]
  console.log('\n[B] foot_lock bridges on real rigs (consumer measurement)');
  const sidecars = {};
  const missing = [];
  for (const b of BRIDGES) {
    const fbx = join(CLIP_DIR, `${b.kind}.fbx`);
    const json = join(CLIP_DIR, `${b.kind}.json`);
    let rm = null;
    if (existsSync(fbx) && existsSync(json)) {
      try { rm = JSON.parse(await readFile(json, 'utf8'))?.geometry?.root_motion ?? null; } catch { rm = null; }
    }
    if (!rm || rm.mode !== 'foot_lock' || !Array.isArray(rm.contact_s)) missing.push(b.kind);
    else sidecars[b.kind] = rm;
  }
  if (missing.length) {
    console.log(`  skip — ${missing.join(', ')} missing or without a foot_lock travel`
      + ` in ${CLIP_DIR} (run Task 8 first)`);
    console.log(`\n${passed + failed} checks, ${failed} failures`);
    process.exit(failed ? 1 : 0);
  }
  const fbxLoader = new FBXLoader();
  const loadClip = async (kind) => {
    const obj = fbxLoader.parse(arrayBufferOf(await readFile(join(CLIP_DIR, `${kind}.fbx`))), '');
    const c = obj.animations[0].clone();
    c.name = kind;
    return c;
  };
  const rawClips = {};
  for (const k of ['idle', ...BRIDGES.flatMap((b) => [b.kind, b.from])]) rawClips[k] = await loadClip(k);
  const refRig = fbxLoader.parse(arrayBufferOf(await readFile(RIG_FILE)), '');
  const donorRest = restPoseOf(THREE, refRig);
  const donorHipsY = rigHipsHeight(refRig);
  console.log(`      reference rig rest hips height ${donorHipsY.toFixed(2)} units`);
  setClipTransitions(BRIDGES.map((b) => ({ from: b.from, to: '*', kind: b.kind, accel: 0 })));

  // WHICH POINT IS A VERIFIED CONTACT, WHEN: the importer's own rule
  // (`_root_motion.contact_weights`), re-run on the REFERENCE rig with the RAW
  // clip — travel included, so the planted points stand still in its world and
  // the drift measured there must come back as the sidecar's `max_drift_cm`.
  // That cross-check is what makes this the importer's classification and not
  // a second opinion. Units: the reference rig's world is centimetres.
  refRig.updateMatrixWorld(true);
  const refPoints = {};
  const refRestY = {};
  refRig.traverse((o) => {
    if (!o.isBone) return;
    const k = keyOf(o.name);
    if (FOOT_KEYS.includes(k)) refPoints[k] = o;
    if (FOOT_KEYS.includes(k) || k === 'lefttoeend' || k === 'righttoeend') {
      refRestY[k] = o.getWorldPosition(new THREE.Vector3()).y;
    }
  });
  const refFloor = Math.min(...Object.values(refRestY));
  const verified = {};   // kind -> { weights[point][frame], drift }
  {
    const ramp = (x, lo, hi) => (!Number.isFinite(x) ? 0 : x <= lo ? 1 : x >= hi ? 0 : (hi - x) / (hi - lo));
    const mixer = new THREE.AnimationMixer(refRig);
    for (const b of BRIDGES) {
      const clip = rawClips[b.kind];
      const action = mixer.clipAction(clip);
      action.play();
      const n = Math.round(clip.duration * FPS) + 1;
      const tracks = FOOT_KEYS.map(() => []);
      for (let f = 0; f < n; f++) {
        mixer.setTime(Math.min(f / FPS, clip.duration));
        refRig.updateMatrixWorld(true);
        FOOT_KEYS.forEach((k, j) => {
          const p = refPoints[k].getWorldPosition(new THREE.Vector3());
          tracks[j].push({ x: p.x, y: p.y, z: p.z });
        });
      }
      action.stop();
      mixer.uncacheClip(clip);
      const weights = tracks.map((pts, j) => {
        const ys = pts.map((p) => p.y).sort((a, c) => a - c);
        const pct = ys[Math.min(ys.length - 1, Math.floor(GROUND_PCT * (ys.length - 1)))];
        const g = Math.min(pct, refRestY[FOOT_KEYS[j]] - refFloor);
        return pts.map((p, f) => {
          const a = Math.max(f - 1, 0);
          const c = Math.min(f + 1, pts.length - 1);
          const vy = c > a ? (pts[c].y - pts[a].y) / ((c - a) / FPS) : 0;
          return ramp(p.y - g, BAND_LO_CM, BAND_HI_CM) * ramp(Math.abs(vy), VY_LO_CM_S, VY_HI_CM_S);
        });
      });
      let drift = 0;
      tracks.forEach((pts, j) => {
        let start = null;
        for (let f = 0; f < pts.length; f++) {
          if (weights[j][f] >= FULL) {
            if (!start) start = pts[f];
            drift = Math.max(drift, Math.hypot(pts[f].x - start.x, pts[f].z - start.z));
          } else start = null;
        }
      });
      verified[b.kind] = { weights, drift };
      const planted = FOOT_KEYS.map((k, j) => `${k} ${weights[j].filter((w) => w >= FULL).length}`).join(', ');
      check(`reference rig, ${b.kind}: the importer's classification holds its bound`
        + ` (<= sidecar ${sidecars[b.kind].max_drift_cm} cm)`,
        drift <= sidecars[b.kind].max_drift_cm + 0.05, `${drift.toFixed(2)} cm`);
      console.log(`      full-contact frames per point: ${planted}`);
    }
  }

  const v = new THREE.Vector3();
  // The two real character rigs, and the REFERENCE rig itself as a third
  // figure (a fresh parse, life-size: its centimetres × 0.01). On its own rig
  // the chain has no proportions to adapt, so whatever it adds to the
  // importer's drift is the chain's own error — the proof of the scale.
  const targets = [
    ...RIGS.map((f) => ({ label: f.split('/').pop(), load: () => loadRig(f), scale: undefined })),
    { label: 'reference.fbx', ref: true, scale: 0.01,
      load: async () => fbxLoader.parse(arrayBufferOf(await readFile(RIG_FILE)), '') },
  ];
  for (const target of targets) {
    const { label } = target;
    console.log(`  --- ${label}`);
    const template = await target.load();
    template.updateMatrixWorld(true);
    const corrections = restCorrections(THREE, donorRest, template);
    /** The library adapted WITH the listing's flag (on) or without (off);
     *  `useRig` false = the travel scaled by the idle median, the bounce's
     *  own denominator (the RED counter-probe of the scale). */
    const adapt = (flagged, useRig = true) => {
      const lib = Object.values(rawClips).map((c) => {
        const cc = c.clone();
        cc.name = c.name;
        if (flagged && sidecars[c.name]) setClipRootMotion(cc, true);
        return cc;
      });
      return adaptExternalClips(lib, template, corrections, useRig ? donorHipsY : undefined);
    };

    for (const b of BRIDGES) {
      const rm = sidecars[b.kind];
      const results = {};
      for (const mode of target.ref ? ['on', 'off', 'median'] : ['on', 'off']) {
        const flagged = mode !== 'off';
        const fig = makeFigure(label, template,
          adapt(flagged, mode !== 'median'), target.scale);
        const feet = [];
        fig.inst.traverse((o) => { if (o.isBone && FOOT_KEYS.includes(keyOf(o.name))) feet.push(o); });
        feet.sort((a, c) => FOOT_KEYS.indexOf(keyOf(a.name)) - FOOT_KEYS.indexOf(keyOf(c.name)));
        const hipsY = hipsOf(fig.inst).getWorldPosition(v).y;   // bind pose, world metres
        const sample = () => {
          fig.owner.updateMatrixWorld(true);
          return feet.map((f) => { f.getWorldPosition(v); return { x: v.x, y: v.y, z: v.z }; });
        };
        fig.owner.position.set(3, 0, -2);
        fig.figure.faceTowards(new THREE.Vector3(Math.sin(YAW), 0, Math.cos(YAW)), true);
        fig.figure.play(b.from);
        for (let i = 0; i < 20; i++) fig.figure.update(0.05);
        fig.figure.play('idle');
        const frames = [];   // frames[i] = feet at clip time (i+1)/FPS
        let guard = 0;
        while (fig.figure.bridging && guard++ < 1000) {
          fig.figure.update(1 / FPS);
          frames.push(sample());
        }
        const last = frames[frames.length - 1];
        const r = { frames, hipsY, feet: feet.map((f) => keyOf(f.name)), held: fig.figure.holdsTravel };
        if (mode === 'on') {
          // [7] the hand-over: owner += takeTravel, no time advanced
          const took = fig.figure.takeTravel();
          if (took) fig.owner.position.add(new THREE.Vector3(took.x, 0, took.z));
          fig.figure.update(0);
          const after = sample();
          r.took = took;
          r.jump = Math.max(...after.map((p, i) => Math.hypot(p.x - last[i].x, p.z - last[i].z)));
          fig.figure.play('idle');
          fig.figure.update(1 / FPS);
          const next = sample();
          r.nextJump = Math.max(...next.map((p, i) => Math.hypot(p.x - last[i].x, p.z - last[i].z)));
          // RED counter-probe on a second run: take the travel, do not move the owner
          const fig2 = makeFigure(label, template, adapt(true), target.scale);
          fig2.owner.position.set(3, 0, -2);
          const feet2 = [];
          fig2.inst.traverse((o) => { if (o.isBone && FOOT_KEYS.includes(keyOf(o.name))) feet2.push(o); });
          feet2.sort((a, c) => FOOT_KEYS.indexOf(keyOf(a.name)) - FOOT_KEYS.indexOf(keyOf(c.name)));
          const sample2 = () => {
            fig2.owner.updateMatrixWorld(true);
            return feet2.map((f) => { f.getWorldPosition(v); return { x: v.x, z: v.z }; });
          };
          fig2.figure.faceTowards(new THREE.Vector3(Math.sin(YAW), 0, Math.cos(YAW)), true);
          fig2.figure.play(b.from);
          for (let i = 0; i < 20; i++) fig2.figure.update(0.05);
          fig2.figure.play('idle');
          guard = 0;
          while (fig2.figure.bridging && guard++ < 1000) fig2.figure.update(1 / FPS);
          const before2 = sample2();
          fig2.figure.takeTravel();
          fig2.figure.update(0);
          const after2 = sample2();
          r.redJump = Math.max(...after2.map((p, i) => Math.hypot(p.x - before2[i].x, p.z - before2[i].z)));
          fig2.figure.dispose();
        }
        fig.figure.dispose();
        results[mode] = r;
      }

      // --- drift of the VERIFIED contacts on this rig ---------------------
      // frames[i] was sampled at clip time (i+1)/FPS — reference frame i+1.
      const on = results.on;
      const nF = on.frames.length;
      const tOf = (i) => (i + 1) / FPS;
      const refW = verified[b.kind].weights;
      const wOf = (j, i) => refW[j][Math.min(i + 1, refW[j].length - 1)];
      const inWindow = (i) => rm.contact_s.findIndex(([s0, e0]) => tOf(i) >= s0 && tOf(i) <= e0
        && tOf(i) >= FADE_SKIP_S);
      /** Per window × point: the largest drift of any verified full-contact
       *  run (both frames of a pair in the window, both at full weight). */
      const driftOf = (frames) => {
        const out = [];
        for (let w = 0; w < rm.contact_s.length; w++) {
          for (let j = 0; j < FOOT_KEYS.length; j++) {
            let start = null;
            let worst = 0;
            let planted = 0;
            for (let i = 0; i + 1 < nF; i++) {
              const full = inWindow(i) === w && inWindow(i + 1) === w
                && Math.min(wOf(j, i), wOf(j, i + 1)) >= FULL;
              if (full) {
                planted += 1;
                for (const k of [i, i + 1]) {
                  const p = frames[k][j];
                  if (!start) start = p;
                  worst = Math.max(worst, Math.hypot(p.x - start.x, p.z - start.z));
                }
              } else {
                start = null;
              }
            }
            out.push({ w, point: FOOT_KEYS[j], planted, drift: worst });
          }
        }
        return out;
      };
      /** The same point's largest wander over the whole window, verified or
       *  not — printed for the points the importer never verified. */
      const wanderOf = (frames, w, j) => {
        let start = null;
        let worst = 0;
        for (let i = 0; i < nF; i++) {
          if (inWindow(i) !== w) continue;
          const p = frames[i][j];
          if (!start) start = p;
          worst = Math.max(worst, Math.hypot(p.x - start.x, p.z - start.z));
        }
        return worst;
      };
      const dOn = driftOf(on.frames);
      const dOff = driftOf(results.off.frames);
      console.log(`      ${b.kind}: ${nF} bridge frames, figure hips ${on.hipsY.toFixed(3)} m,`
        + ` windows ${JSON.stringify(rm.contact_s)}`);
      let worstOn = 0;
      let worstOff = 0;
      for (let k = 0; k < dOn.length; k++) {
        const a = dOn[k];
        const o = dOff[k];
        if (!a.planted) {
          const j = FOOT_KEYS.indexOf(a.point);
          console.log(`        window ${a.w} ${a.point.padEnd(12)} not a verified contact —`
            + ` info: wanders ${cm(wanderOf(on.frames, a.w, j))} over the window`
            + ` (off ${cm(wanderOf(results.off.frames, a.w, j))})`);
          continue;
        }
        console.log(`        window ${a.w} ${a.point.padEnd(12)} ${String(a.planted).padStart(3)} frame pairs`
          + `  drift on ${cm(a.drift)}   off ${cm(o.drift)}`);
        worstOn = Math.max(worstOn, a.drift);
        worstOff = Math.max(worstOff, o.drift);
      }
      const plantedCount = dOn.filter((d) => d.planted).length;
      check(`${label} ${b.kind}: some point is a verified contact in the windows`, plantedCount > 0,
        `${plantedCount} point×window runs`);
      const bound = target.ref ? REF_DRIFT_MAX_M : b.driftMax;
      check(`[6] ${label} ${b.kind}: planted-foot drift <= ${cm(bound)}`,
        worstOn <= bound, cm(worstOn));
      check(`[6] ${label} ${b.kind}: RED COUNTER-PROBE — offset off slides >= ${cm(b.redMin)}`,
        worstOff >= b.redMin, cm(worstOff));
      if (target.ref) {
        // The chain on its own rig: nothing to add to the importer's drift.
        const own = verified[b.kind].drift / 100;
        check(`[6] ${label} ${b.kind}: the chain adds nothing on its own rig`
          + ` (<= importer ${cm(own)} + 0.10 cm)`, worstOn <= own + 0.001, cm(worstOn));
        const dMed = driftOf(results.median.frames).reduce((m, d) => (d.planted ? Math.max(m, d.drift) : m), 0);
        check(`[6] ${label} ${b.kind}: RED COUNTER-PROBE — the idle-median scale overshoots`
          + ` (> importer + 0.10 cm)`, dMed > own + 0.001, cm(dMed));
      }
      check(`[7] ${label} ${b.kind}: the travel was held at the end`, on.held && !!on.took);
      check(`[7] ${label} ${b.kind}: hand-over jump <= ${cm(HANDOVER_MAX_M)}`,
        on.jump <= HANDOVER_MAX_M, cm(on.jump));
      const tookLen = on.took ? Math.hypot(on.took.x, on.took.z) : 0;
      check(`[7] ${label} ${b.kind}: RED COUNTER-PROBE — owner not moved jumps by the travel`,
        Math.abs(on.redJump - tookLen) <= 0.05 && on.redJump >= (b.kind === 'get-up-chair' ? 0.30 : 0.1),
        `${cm(on.redJump)} vs travel ${cm(tookLen)}`);
      console.log(`      [7] ${label} ${b.kind}: travel handed over ${cm(tookLen)}`
        + ` (${on.took ? `${on.took.x.toFixed(3)}, ${on.took.z.toFixed(3)}` : '-'});`
        + ` next real frame (idle crossfade, 1/30 s) moves the feet ${cm(on.nextJump)}`);

      // info: the LOWEST foot point over the whole bridge
      const lowestRuns = (frames) => {
        let worst = { d: 0, point: '', t: 0 };
        let cur = -1;
        let start = null;
        for (let i = 0; i < frames.length; i++) {
          if (tOf(i) < FADE_SKIP_S) continue;
          let j = 0;
          for (let q = 1; q < frames[i].length; q++) if (frames[i][q].y < frames[i][j].y) j = q;
          if (j !== cur) { cur = j; start = frames[i][j]; }
          const d = Math.hypot(frames[i][j].x - start.x, frames[i][j].z - start.z);
          if (d > worst.d) worst = { d, point: FOOT_KEYS[j], t: tOf(i) };
        }
        return worst;
      };
      const lo = lowestRuns(on.frames);
      const loOff = lowestRuns(results.off.frames);
      console.log(`      info ${label} ${b.kind}: lowest foot point, whole bridge —`
        + ` on ${cm(lo.d)} (${lo.point} @ ${lo.t.toFixed(2)} s),`
        + ` off ${cm(loOff.d)} (${loOff.point} @ ${loOff.t.toFixed(2)} s)`);
    }
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
