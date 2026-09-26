#!/usr/bin/env node
/**
 * Smoke check for THE HEIGHT OF A HOLDING BRIDGE — `client3d/src/scene/bridgeLift.ts`,
 * its measurement in `footLockMeasure.relockRootPaths` and its consumers
 * `figures.Figure` (`beginBridgeLift`, `holdsHeight`) and `npcs.NpcManager.tick`
 * (§ B5a: numbers, never screenshots). Task C5 of plan-bruecken-feinschliff.
 *
 * Usage:  node client3d/scripts/smoke_bridge_lift.mjs
 *         (bundles the client modules itself; part [V] reads the clips
 *          idle, walk, get-up-bed, get-up-chair and the two clips they leave
 *          from shared/models/clips — READ ONLY)
 *
 * WHICH CLIPS ARE LEFT (`bridgeSources.mjs`): the lying clip is the first
 * `from` the live transition table (`shared/config/clip_transitions.json`,
 * read at run time) names for get-up-bed whose .fbx exists AND is tracked by
 * git; otherwise the tracked `laying`. The sitting clip likewise for
 * get-up-chair, fallback `sitting-in-chair`. No tracked clip → the bed or
 * chair part is SKIPPED with a message. The run prints which it used.
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Task C0 measured an NPC getting out of bed: the server's stand point is the
 * FLOOR (+ WALK_CLEARANCE_M = 0.01), it arrives in the same poll as the
 * standing clip, and `npcs.tick` eased the root down to it with 4·dt from the
 * first bridge frame on — the lying body sank up to 35 cm (bed 0.46 m) / 46 cm
 * (0.60 m) into the mattress, the feet ended 31–43 cm UNDER the floor and the
 * figure hopped 36 cm up when the next clip faded in. The avatar kept its
 * root on the bed: feet 13.5 / 27.5 cm over the floor at the end, and without
 * input afterwards the idle feet hung 49 / 63 cm beside the bed for good.
 * Re-measured on this tree before the fix (Test3_mia / Soldier / reference
 * rig, lowest foot bone over y = 0, last bridge frame): NPC −32.0 / −37.0 /
 * −45.0 cm (both beds); avatar bed 0.46 +12.5 / +7.5 / −0.6, bed 0.60
 * +26.5 / +21.5 / +13.4; avatar without input, 0.5 s after: +47.0 / +47.3 /
 * +45.6 (bed 0.46).
 *
 * THE RULE NOW: during a holding bridge the owner keeps the root in X/Z only;
 * it puts the root ONCE, at the bridge start, onto the new floor and hands the
 * difference to the figure as `startLift`. The figure draws the body at
 * `root + startLift` (on the bed) until `LIFT_RAMP_S` before the feet's first
 * full contact, then smoothsteps onto `endLift` — measured per rig so that the
 * lowest foot point of the clip's LAST frame stands on the rig's REST floor.
 *
 * THE FLOOR every check below measures against is the plane the figure stands
 * on: its root goal, floor 0 + WALK_CLEARANCE_M = 0.01 m (the NPC's stand
 * point, `main.ts` server stand point; the avatar's `groundAvatarGoal` /
 * walking goal, `roomFloorY`). A foot "on the floor" is a foot BONE point
 * (Foot, ToeBase, Toe_End of both sides — the points of the rest floor) at
 * that plane plus the rig's own rest height of it over the bind soles, r:
 * Test3_mia 0.33 cm, Soldier 1.34 cm, the reference rig 0 (its bind box IS
 * its bones) — measured on the rigs (lowest foot bone over the bind box
 * floor at the nominal scale).
 *
 * ---------------------------------------------------------------------------
 * [L] liftAt — pure, by hand (smoothstep s(x) = x²(3 − 2x))
 * ---------------------------------------------------------------------------
 * [L1] startLift 0.46, endLift 0.358, firstContactS 2.4 → ramp from
 *      2.4 − 0.6 = 1.8 s: t=0 → 0.46; t=1.8 → 0.46; t=2.1 (x = 0.5,
 *      s = 0.25·2 = 0.5) → 0.46 − 0.102·0.5 = 0.409; t=2.4 → 0.358;
 *      t=4 → 0.358.
 * [L2] firstContactS 0.03 (a chair whose feet stand from the start): the ramp
 *      never ends before the bridge's start crossfade BRIDGE_FADE_IN_S = 0.25
 *      → window [max(0, 0.25 − 0.6) = 0, max(0.03, 0.25) = 0.25]:
 *      t=0 → startLift (0.042); t=0.125 (x = 0.5, s = 0.5) → 0.021;
 *      t=0.0625 (x = 0.25, s = 0.0625·2.5 = 0.15625) → 0.042 − 0.042·0.15625
 *      = 0.0354375; t=0.25 → endLift (0.0); t=0.03 (x = 0.12, s = 0.0144·2.76
 *      = 0.039744) → 0.042·(1 − 0.039744) = 0.040330752 — NOT endLift any
 *      more (before: a drop of the whole 4.2 cm within 0.03 s).
 *      liftRamp(0.03) = {0, 0.25}; liftRamp(2.4) = {1.8, 2.4};
 *      liftRamp(0.4) = {0, 0.4}.
 * [L3] startLift == endLift (0.2) → 0.2 for t = 0, 1.9, 2.1, 2.4, 9.
 * [L4] non-finite t / endLift / firstContactS → startLift (0.46); a NaN
 *      startLift counts as 0 — never NaN.
 * [L5] fadeCarry(0.1, e): e=0 → 0.1; e=0.3 (x = 0.5) → 0.05; e=0.15
 *      (x = 0.25, s = 0.15625) → 0.084375; e=0.6 → 0; e=2 → 0; NaN → 0.
 *
 * ---------------------------------------------------------------------------
 * [V] the whole chain on REAL rigs, measured at the CONSUMER
 * ---------------------------------------------------------------------------
 * Test3_mia.glb, Soldier.glb (1.70 m, nominal scale 1.70 / mesh height) and the
 * reference rig (its centimetres × 0.01, 2.011 m); the real clips through
 * `adaptExternalClips` → `relockRootPaths` (which now also measures the
 * lift) → `measureGroundOffsets` → `Figure`, the order of `fitLibrary`.
 * Rules: <lying clip> → * via get-up-bed, <sitting clip> → * via
 * get-up-chair, both accel 0 (they hold). 30 fps (the clips' own rate).
 *
 * The bed: lying place at S = 0.46 and 0.60 m, `lie` root_drop 0.001 · H
 * (pose_catalog groups; H = 1.70, the reference rig 2.011) → root at S −
 * 0.0017 (S − 0.0020). Yaw 0.7 (heights do not depend on it).
 * The chair: seat S = 0.45 m, `seat` root_drop 0.234 · H → root at
 * 0.45 − 0.3978 = 0.0522 m (reference rig 0.45 − 0.4706 = −0.0206 m), so the
 * chair's startLift = root − 0.01 = 0.0422 m (−0.0306 m).
 *
 * NPC = the REAL `NpcManager.tick` with one injected NPC (the pattern of
 * smoke_bridge_root [Y3]): it lies/sits on its slot (goal = its root), then
 * the server stands it up — `animation` idle and goal = the server's stand
 * point (slot + the clip's travel_m × H / ref_height_m turned by the yaw,
 * y = 0.01), delivered once a second through the real `update()` (which
 * since Task C4 keeps the spot the bridge left the figure on when it is
 * within 0.25 m of that point).
 * AVATAR = the same manager with the figure player-driven: seated by
 * `snapPlayerTo`, then the release `main.ts` does now — clip cleared (key:
 * walk while held) and `groundAvatarGoal` (goal = seat X/Z at the floor
 * height 0.01) — and per frame the steering hook's part that matters here:
 * `takePlayerTravel`, and with the key held, once `paceLimitFor(walk)` lets
 * go, a walking goal 0.3 m ahead at y = 0.01.
 *
 * [V1] NPC, bed: from the first bridge frame while the clip time is before
 *      the ramp (`liftRamp(firstContactS).from`), the lowest trunk bone (hips,
 *      spines, neck, head, shoulders) − S >= min(0, the same measure while it
 *      still LAY) − 5 cm. The body is drawn where it lay (root + startLift =
 *      the old root), so the lift adds nothing; what is left is the 0.25 s
 *      crossfade from the lying clip into the first pose of get-up-bed
 *      (sleeping-side: −4.3 cm on Test3_mia, C0's avatar column, where the
 *      root never left the bed). A lying clip whose own pose already reaches
 *      under S (the tracked `laying` on Test3_mia: −10.3 cm, the clip and the
 *      `lie` root_drop, not the bridge — INFO line) is judged from there.
 *      Before: −35.8 / −46.9 cm (Test3_mia, sleeping-side, S = 0.46 / 0.60).
 * [V2] last bridge frame: lowest foot − floor within ±1.5 cm, both S, three
 *      rigs, NPC and avatar (key held / no input). By construction the lift is
 *      `endLift` there, which puts the lowest foot point of the clip's last
 *      frame on the rest floor, r over the root plane: 0.33 / 1.34 / 0 cm
 *      (the last bridge frame is up to one frame before the clip's end).
 *      COUNTER-PROBE in the same run, the lift removed from the clip (and the
 *      avatar's goal not written, as before): NPC <= −25 cm (today −32 / −37 /
 *      −45 over y = 0).
 * [V3] from the last bridge frame through 0.5 s after it, no 36 cm hop: the
 *      fade-out lift (lift × the bridge's weight) carries the body across the
 *      crossfade into the next clip.
 *      [V3a] into IDLE (the avatar without input, and since Task C4 the NPC
 *      that keeps the spot its bridge left it on — within STAND_ADOPT_M
 *      = 0.25 m of the server's stand point): lowest foot − floor
 *      within −2 … +3 cm — idle's own foot lift over the root is +1.5
 *      (Test3_mia) / +1.8 (Soldier) / +0.2 cm (reference; the A1 measure).
 *      The NPC SETTLES on every rig, and that is checked, not only observed:
 *      its hand-over lands 14.58 (Test3_mia) / 3.80 (Soldier) / 0.01 cm
 *      (reference) off the stand point (measured), all under STAND_ADOPT_M
 *      = 25 cm — a broken settle fails there instead of quietly moving the
 *      NPC to the [V3b] bounds.
 *      [V3b] into WALK (the NPC walking on to its stand point from further
 *      off, the avatar with the key held): upper bound +3 cm as above; the lower bound is
 *      NOT −2 cm. A crossfade between two stances blends the leg joints'
 *      rotations, and a blended leg reaches further down than the average of
 *      the two (the vertical reach goes with the cosine of the joint angles,
 *      which is concave): every plain idle → walk crossfade on flat ground,
 *      no bridge and no lift involved, dips the lowest foot under the root
 *      plane — measured in this run per rig as the reference (INFO; at the
 *      time of writing Test3_mia −3.67, Soldier −2.45, reference −3.38 cm).
 *      The hand-over into walk may dip no deeper than that plain crossfade
 *      minus the [V2] tolerance, 1.5 cm — DERIVED, not measured: the blended
 *      foot height is the weighted mix of the two poses' foot heights plus
 *      the blend's own concave term. The plain crossfade starts from idle's
 *      feet; the hand-over starts from the bridge's last frame, whose feet
 *      [V2] puts within ±1.5 cm of the floor. The concave term is the same
 *      kind of dip, so the hand-over's mix differs from the control's by at
 *      most the weight × that start offset, i.e. at most 1.5 cm. Before: the
 *      feet rose from −32 to +2.6 cm in eight frames (NPC) — the hop.
 * [V4] avatar, no input after the bridge: 1 s after its end the root stands
 *      on the floor plane (±1 cm; it was put there at the bridge start and
 *      nothing lifts it — before: 45.5 / 59.5 cm) and the lowest idle foot is
 *      within ±2 cm of it (the idle lift above; before +47 / +61 cm).
 * [V5] get-up-chair, seat 0.45, NPC and avatar without input: last bridge
 *      frame lowest foot − floor within ±1.5 cm (same construction as [V2]);
 *      and no frame of the bridge moves the drawn root (owner y + lift) by
 *      more than the smoothstep's steepest frame (+0.1 mm): the drawn root is
 *      continuous at the bridge start (root + startLift = the old root) and
 *      then follows start + Δ·s(x), Δ = endLift − startLift, x over the ramp
 *      of length D = liftRamp(fc).to − liftRamp(fc).from. s'(x) = 6x(1 − x)
 *      peaks at 1.5, so no frame of dt = 1/30 s moves it more than
 *      1.5 · |Δ| / D · dt (mean value theorem). For a chair whose feet stand
 *      from the first frame D = 0.25 s (the fade-in floor): Soldier |Δ| =
 *      4.22 + 0.34 = 4.56 cm → 1.5·4.56/0.25/30 = 0.912 cm (before this
 *      floor: the whole 4.56 cm in one frame). The same bound is checked on
 *      every bed run ([V5b], D = 0.6 s).
 * [V6] THE FLOOR ARRIVES LATE (C0 § 6), NPC, bed 0.46, three rigs: the bridge
 *      opens while the goal is still the SEAT (the poll carried the standing
 *      clip but still the seat's point), so it opens with startLift 0; 0.5 s
 *      later the server's stand point arrives at the floor. The owner puts the
 *      root on it and hands the difference over (`shiftBridgeLift`); 0.5 s is
 *      before every rig's ramp (firstContactS − 0.6 >= 1.4 s, INFO), so the
 *      carry is 0 and the run from there on is the normal one: [V2] holds
 *      (last bridge frame, lowest foot − floor within ±1.5 cm) and no frame
 *      moves the drawn root more than the [V5] bound of the normal bed run
 *      (the same Δ and D).
 * INFO: per rig the measured endLift (world cm) and firstContactS.
 */
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
      `export { toWorld } from '${src}/scene/bridgeTravel';`,
      `export { adaptExternalClips, Figure, setClipRootMotion } from '${src}/scene/figures';`,
      `export { relockRootPaths } from '${src}/scene/footLockMeasure';`,
      `export { measureGroundOffsets } from '${src}/scene/clipGround';`,
      `export { NpcManager } from '${src}/scene/npcs';`,
      `export { STAND_ADOPT_M } from '${src}/scene/standSettle';`,
      `export { setClipTransitions } from '${src}/game/walk';`,
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

  // ------------------------------------------------------------------ [L]
  console.log('[L] liftAt — hand cases');
  const L = C.liftAt;
  for (const [t, ex] of [[0, 0.46], [1.8, 0.46], [2.1, 0.409], [2.4, 0.358], [4, 0.358]]) {
    near(`[L1] t=${t} → ${ex}`, L(t, 0.46, 0.358, 2.4), ex, 1e-9);
  }
  near('[L1] LIFT_RAMP_S = 0.6', C.LIFT_RAMP_S, 0.6, 0);
  near('[L2] BRIDGE_FADE_IN_S = 0.25', C.BRIDGE_FADE_IN_S, 0.25, 0);
  for (const [t, ex] of [[0, 0.042], [0.0625, 0.0354375], [0.125, 0.021], [0.03, 0.040330752], [0.25, 0], [1, 0]]) {
    near(`[L2] chair, firstContactS 0.03: t=${t} → ${ex}`, L(t, 0.042, 0, 0.03), ex, 1e-9);
  }
  for (const [fc, from, to] of [[0.03, 0, 0.25], [2.4, 1.8, 2.4], [0.4, 0, 0.4]]) {
    const r = C.liftRamp(fc);
    check(`[L2] liftRamp(${fc}) = {${from}, ${to}}`, Math.abs(r.from - from) < 1e-9 && Math.abs(r.to - to) < 1e-9,
      `{${r.from}, ${r.to}}`);
  }
  for (const t of [0, 1.9, 2.1, 2.4, 9]) near(`[L3] start == end: t=${t} → 0.2`, L(t, 0.2, 0.2, 2.4), 0.2, 1e-12);
  near('[L4] t NaN → startLift', L(NaN, 0.46, 0.358, 2.4), 0.46, 0);
  near('[L4] endLift Infinity → startLift', L(3, 0.46, Infinity, 2.4), 0.46, 0);
  near('[L4] firstContactS NaN → startLift', L(3, 0.46, 0.358, NaN), 0.46, 0);
  near('[L4] startLift NaN → counts as 0 (before the ramp)', L(0, NaN, 0.358, 2.4), 0, 0);
  check('[L4] startLift NaN → never NaN inside the ramp', Number.isFinite(L(2.1, NaN, 0.358, 2.4)),
    String(L(2.1, NaN, 0.358, 2.4)));
  for (const [e, ex] of [[0, 0.1], [0.15, 0.084375], [0.3, 0.05], [0.6, 0], [2, 0], [NaN, 0]]) {
    near(`[L5] fadeCarry(0.1, ${e}) → ${ex}`, C.fadeCarry(0.1, e), ex, 1e-12);
  }

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
  const chairFrom = bridgeSourceClip(ROOT, 'get-up-chair', 'sitting-in-chair');
  const FROM = { 'get-up-bed': bedFrom?.kind, 'get-up-chair': chairFrom?.kind };
  for (const [kind, src] of [['get-up-bed', bedFrom], ['get-up-chair', chairFrom]]) {
    console.log(src ? `\n[V] ${kind} leaves ${src.kind} — ${src.note}` : `\n[V] ${kind}: SKIPPED (see above)`);
  }
  const KINDS = ['idle', 'walk', 'get-up-bed', 'get-up-chair', ...[bedFrom, chairFrom].filter(Boolean).map((x) => x.kind)];
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
    const run = (scenario, bridgeKind, S, { liftOff = false, lateFloorS = 0 } = {}) => {
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
        label: { visible: false }, labelName: { textContent: '' }, labelActivity: { textContent: '' },
        labelBubble: null, bubbleUntil: 0, target: new THREE.Vector3(), pace: 1, face: null,
        waypoints: [], ride: null, route: null, travelling: false, reckon: null,
        interaction: null, activity: '', travelLine: null, travelKey: '', bobPhase: 0,
        settle: null,
      };
      const mgr = new C.NpcManager(null);
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
      const poll = () => mgr.update([{ char: { name, activity: '', activity_animation: 'idle' },
        pos: standPoint.clone() }]);
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
      for (let f = 0; f < FPS * 15; f++) {
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
        settled, handOverM: settled ? Math.hypot(npc.settle.offset.x, npc.settle.offset.z) : NaN };
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
