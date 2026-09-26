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
 *       console.warn covers the session (two adaptations, one line) — plus,
 *       separately, the one line saying the STANDING reference fell back to
 *       the idle clip (`standingHipsRef`, smoke_rig_stand_ref.mjs).
 * [5] Bridge ended, nobody took the travel yet, three more update() frames
 *       (with the next clip asked for, as `npcs.tick` does): instance x/z
 *       unchanged (no snap back to the seat).
 *
 * ---------------------------------------------------------------------------
 * [B] the whole chain on REAL rigs, measured at the CONSUMER
 * ---------------------------------------------------------------------------
 * `Test3_mia.glb` (server mesh pipeline), `Soldier.glb` (Mixamo fallback
 * rig) and the reference rig itself (life-size, its centimetres × 0.01), the
 * real neutral clips (`idle` gives the standing reference, the seat/bed clip
 * is the state the bridge leaves), the reference rig's rest pose for the
 * bind-relative transplant (`restCorrections`, exactly what `FigureLibrary`
 * does when `/assets/animation-rig` is served), the real
 * `adaptExternalClips`, and then — as `FigureLibrary.fitLibrary` does right
 * after it — `relockRootPaths(clips, template, 1 / (100 · scale))`, ONE call
 * per model over its library at the model's nominal scale (1.70 m ÷ mesh
 * height; 0.01 for the reference rig), which rebuilds the travel AND pins the
 * planted feet by leg IK (`legPin.ts`, `smoke_leg_pin.mjs`). A real `Figure` inside an owner group
 * plays the NPC root. What is measured is the WORLD position of the bones
 * `LeftFoot`/`LeftToeBase`/`RightFoot`/`RightToeBase` of the rendered
 * instance, frame by frame at 30 fps (the clips' own rate); figure frame i is
 * clip time (i+1)/30. The first 0.30 s are left out everywhere: the bridge
 * fades in over 0.25 s from the seat clip, those frames are a blend.
 *
 * WHICH POINT IS PLANTED, WHEN — the smoke's OWN contact detection on the
 * RENDERED rig (its own code here, not `footLock.ts`): "planted" is a
 * property of the rig the feet belong to. The importer's constants: a
 * point's ground is the 5th percentile of its heights (over the frames
 * after the fade), capped at its bind-pose rest height (the importer's rule
 * and the client's: no lift tolerance — with the rig's rest hips height as
 * the standing reference an adapted clip no longer stands lifted over the
 * rest, `smoke_foot_lock_measure.mjs` [C8]); rest heights come
 * from THAT rig's bind pose, each point over the lowest of the four points
 * and the toe ends. Weight = ramp(height − ground, 2, 5 cm) ×
 * ramp(|vertical speed|, 15, 30 cm/s) (central difference); a frame at
 * ≥ 0.999 is FULL. Drift = the largest horizontal distance a point moves
 * from where its run of FULL frames began. Each run is judged on its OWN
 * contacts: the leg pin lowers planted feet in the re-locked library, so its
 * heights are not those of the imported / offset-off runs (which share
 * theirs — the travel is XZ only).
 *
 * INFO only, the measurement [6] bounded before this plan: the importer's
 * classification (`_root_motion.contact_weights` re-run on the REFERENCE rig
 * with the RAW clip) inside the sidecar's `contact_s` windows. Cross-check:
 * on the reference rig that classification gives the sidecar's
 * `max_drift_cm` back (+0.05 cm). On another rig it transplants the
 * reference rig's contacts onto feet that are not planted there (Test3_mia
 * bed: 3.13 cm re-locked, although its own feet hold 2.27 cm).
 *
 * [6] foot_lock clips: planted-foot drift, own contacts, per clip, on ALL
 *       THREE rigs: <= 1.5 cm for get-up-chair AND get-up-bed — the
 *       importer's guarantee, now per rig. The bed turns ~90° while both
 *       feet are planted, which a translation-only path could not hold (it
 *       had 2.5 cm, the rule's residual 2.27 cm on Test3_mia); the leg pin
 *       holds each foot in place of the path, so the bed takes the chair's
 *       bound (Task C6).
 *       HISTORY (imported path only, sidecar spans, 2026-09-25): chair
 *       Test3_mia 2.20, Soldier 1.09, reference 0.30; bed 4.76, 2.95, 1.31 —
 *       bounded then by 2.5 / 5.0 cm.
 *       BEFORE Task C6 (path re-locked, NO leg pin; own contacts, re-locked /
 *       imported, cm) — the old get-up-chair (63e48659) and, in brackets, the
 *       re-import with both feet planted through the rise (B1/B2), which the
 *       path alone could no longer hold:
 *         chair  Test3_mia 1.41 / 2.20 [3.86 / 5.03]   Soldier 0.68 / 1.44 [1.59 / 4.89]
 *                reference 0.42 / 0.42 [1.04 / 1.04]
 *         bed    Test3_mia 2.27 / 2.83   Soldier 1.66 / 3.07   reference 1.43 / 1.43
 *       AFTER (the re-imported chair, leg pin on; re-locked + pinned /
 *       imported, cm):
 *         chair  Test3_mia 0.58 / 5.03   Soldier 1.02 / 4.89   reference 0.64 / 1.04
 *         bed    Test3_mia 0.70 / 2.83   Soldier 1.30 / 3.07   reference 1.11 / 1.43
 *       The re-lock's own report (`relockRootPaths`, its contacts on the
 *       probe clone, the bridge's fade-in included; drift rebuilt / imported
 *       before the pin, the largest horizontal hold / vertical lift of an
 *       ankle, the drift after it):
 *       Test3_mia chair 3.86 / 5.03, held 2.66 / lifted 2.08 → 0.45; bed
 *       2.27 / 3.00, 2.15 / 2.08 → 0.55; Soldier chair 1.63 / 4.91, 0.59 /
 *       1.63 → 1.03; bed 1.66 / 3.14, 1.41 / 2.08 → 1.00; the reference rig
 *       keeps its IMPORTED path for BOTH clips — chair imported 1.05 (rebuilt
 *       1.05), bed imported 1.43 (rebuilt 1.44): the rebuild gains less than
 *       `RELOCK_MIN_GAIN_CM` = 0.1 cm there — and is pinned on it: chair
 *       0.26 / 0.66 → 0.64, bed 1.81 / 2.08 → 0.44 (the bed is an import
 *       from before the importer's foot plant). The 2.08 is the most the
 *       lift can move: a foot h cm over its ground weighs (5 − h)/3 in the
 *       contact band and comes down by that × h, at most 2.5 · 2.5/3 =
 *       2.083 cm (h = 2.5). CHECKED:
 *       every report on the reference rig says used 'imported'; own contacts
 *       hold <= 1.5 cm for BOTH clips there (checked).
 *       COUNTER-PROBE in the same run, the IMPORTED path (no re-lock, no pin)
 *       measured the same way: never lower than the re-locked one (clip ×
 *       rig), and on Test3_mia / get-up-chair the re-lock gains >= 0.5 cm —
 *       Task 2 measured 2.20 → 1.23 cm (sidecar spans), a gain of 0.97; the
 *       path alone on the re-imported chair gains 5.03 → 3.86 = 1.17, with
 *       the pin 5.03 → 0.58 = 4.45; the checked floor of 0.5 cm stays well
 *       under all of them.
 *       RED COUNTER-PROBE: offset switched off (the library adapted WITHOUT
 *       the root-motion flag): chair >= 15 cm, bed >= 25 cm (measured, chair
 *       / bed: Test3_mia 35.9 / 32.2, Soldier 58.2 / 45.5, reference 70.0 /
 *       53.2 cm).
 *       RED COUNTER-PROBE of the scale (reference rig, sidecar spans): the
 *       idle-median scale overshoots the importer's own number by > 0.10 cm.
 * [7] End of bridge + takeTravel + owner root moved by it (re-locked
 *       library): the rendered foot positions of the last bridge frame and of
 *       the frame after the hand-over (no time advanced) differ by <= 1 cm.
 *       RED COUNTER-PROBE: takeTravel WITHOUT moving the owner jumps the feet
 *       by the whole travel (>= 30 cm for the chair).
 * [B9] LINEARITY PROOF, per clip × rig: the same figure drawn with
 *       baseScale × 1.15 (a 1.955 m body) on the path re-locked at the
 *       nominal scale; contacts judged at the nominal scale (heights ÷ 1.15 —
 *       the thresholds are written for it), drift in WORLD cm. Expected:
 *       drift(×1.15) = 1.15 × drift(×1) within 1 %. In the client the re-lock
 *       scale IS the figure's baseScale (`fitLibrary(…, model.scale)` and
 *       `Figure.baseScale = model.scale`), so no figure is ever drawn at
 *       another scale than its path was built for — what this check proves
 *       is that the path scales with the body (instance and travel both ×
 *       baseScale), not an extra tolerance on the [6] bounds. The leg pin
 *       bakes ROTATIONS, which do not care for the scale. Measured (chair /
 *       bed): Test3_mia 0.67 / 0.80 cm (= 1.15 × 0.58 / 0.70), Soldier
 *       1.17 / 1.49, reference 0.73 / 1.28.
 * [B10] INFO: distance of the handed-over end point from the server's stand
 *       point (`travel_m × height / ref_height_m`, turned by the same yaw;
 *       height 1.70 m, the reference rig = ratio 1), per rig, cm. Measured
 *       re-locked / imported: Test3_mia chair 9.6 / 5.2, bed 14.9 / 5.4;
 *       Soldier 2.0 / 1.4, 3.5 / 1.5; reference 0.0 / 0.0 (the pin moves
 *       feet, not the travel: the chair's numbers changed with its
 *       re-import, B2).
 * [B11] relockRootPaths per model (one call, both bridges, the leg pin
 *       included) <= 100 ms, printed (measured 4–5 ms before the pin,
 *       9.6–14.3 ms with it).
 * [B17] THE CHAIR'S END, BOTH FEET ON THE FLOOR: from t >= 3.5 s (40
 *       frames), per side the lowest of the foot's bones (Foot, ToeBase,
 *       Toe_End) over the rig's rest floor, MEDIAN over those frames — the
 *       measure Task B2 used, so the numbers compare; single frames reach
 *       further (printed as the range) — within ±1.0 cm on every rig. Task B2 measured it on the re-imported chair
 *       without the pin (right / left, cm): Test3_mia −0.53 / 0.82, Soldier
 *       1.30 / 1.15, reference 0.01 / 0.00 — Soldier's feet stood 1.2–1.3 cm
 *       up (old chair: right foot 3.84 there). With the pin: Test3_mia
 *       −0.93 / 0.33, Soldier −0.25 / −0.55, reference 0.01 / −0.16 (the
 *       pin brings a foot to the ground of its points, `groundHeights` —
 *       the low 5th percentile of the adapted clip itself, which on
 *       Test3_mia lies 1.01 cm under the rest floor for the right ball, in
 *       the same frame as the rest heights — the tightest case).
 *   info  The re-lock's own report per clip, the per-point numbers (FULL
 *       frames, runs, worst run and its span, drift re-locked / imported /
 *       off / × 1.15) and the final drift table.
 *
 * ---------------------------------------------------------------------------
 * [Y] NOTHING TURNS OR STEPS A FIGURE A BRIDGE HOLDS
 * ---------------------------------------------------------------------------
 * A bridge with `accel` 0 (getting up out of bed) owns the whole body: its
 * yaw as much as its place. [Y1]/[Y2] run in part [A] (the synthetic Soldier
 * bridge, 1 s, accel 0 — no clip files needed), [Y3] after part [B] (the
 * real clips).
 * [Y1] The figure faces yaw 0.6, the bridge opens, and on EVERY bridge frame
 *       `faceTowards(+x, snap)` (yaw atan2(1, 0) = π/2) and then
 *       `setYaw(1.0)` are asked for. `root.rotation.y` stays 0.6 ± 1e-6 for
 *       the whole bridge. (Task C2 will hand the bridge's OWN turn over at its
 *       end; until then there is none.) Before this task the snap turned
 *       the root to π/2 at once: |π/2 − 0.6| = 0.9708 rad.
 *       [Y1r] COUNTER-PROBE, same asks on a RAMPING bridge (accel 1): it
 *       keeps its turn — the figure is about to walk off — so rotation.y
 *       leaves 0.6 by more than 0.1 rad.
 * [Y2] After the bridge nobody asks again, the frames go on (the next clip
 *       asked for as `npcs.tick` does): the figure eases towards the LAST
 *       direction asked for, 1.0. After 2 s = 60 frames the rest is
 *       0.4 · (2/3)^60 ≈ 1e-11 rad, so |rotation.y − 1.0| < 0.05.
 * [Y3] The REAL `NpcManager.tick` (one injected NPC) over the real chain on
 *       Test3_mia (`adaptExternalClips` → `relockRootPaths` →
 *       `measureGroundOffsets` → `Figure`, the order of `fitLibrary`; clips idle, walk, sleeping-side,
 *       get-up-bed; rule sleeping-side → * via get-up-bed, accel 0). The NPC
 *       lies (`animation` sleeping-side, goal = its root), then the server
 *       stands it up: `animation` idle, goal 0.5 m away (< RUN_DISTANCE 6 m:
 *       walk). In the ONE tick that starts the bridge (checked: bridging
 *       after it) the root moves <= 1 mm in X/Z. Before this task the step
 *       read `paceLimit` before the clip was asked for: min(0.5, 3.4 m/s ·
 *       1/30 s) = 11.33 cm (C0 § 5.1).
 *       [Y3c] COUNTER-PROBE, same run: an NPC standing on idle (idle → walk
 *       has no rule) with the same goal steps the full 3.4/30 = 0.11333 m ±
 *       1e-4 in its first tick — the gate holds a bridge, nobody else.
 *       [Y3b] The NPC lies again, stands up with its goal ON its root (not
 *       moving — the standing branch) and a marker facing +x: rotation.y is
 *       the same ± 1e-6 on every bridge frame. Before this task it eased to
 *       the marker's π/2: 0.9708 rad off.
 *       [Y3d] After the bridge the gate opens: the first tick after it hands
 *       the bridge travel over (root and goal move by it, `applyBridgeTravel`),
 *       and within the 1 s after THAT tick the root walks >= 5 cm (the goal
 *       is still ~0.5 m away; 1 s of walking is up to 3.4 m).
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
/** Planted-foot drift bounds, own contacts on every rig ([6], docstring):
 *  the importer's 1.5 cm guarantee for both bridges — the bed's ~90° turn
 *  with both feet planted is held by the leg pin, not by the path. */
const CHAIR_DRIFT_MAX_M = 0.015;
const BED_DRIFT_MAX_M = 0.015;
/** [6] counter-probe: the re-lock's least gain on Test3_mia / get-up-chair. */
const RELOCK_GAIN_MIN_M = 0.005;
/** RED counter-probes, offset off: chair from the brief; bed derived from the
 *  measured 37.2 (Test3_mia) / 44.7 (Soldier) cm with room to spare. */
const CHAIR_RED_MIN_M = 0.15;
const BED_RED_MIN_M = 0.25;
/** [B9]: the figure drawn this much larger than the scale it was re-locked
 *  at, and how closely its drift must follow the scale (relative). */
const SCALE_UP = 1.15;
const LINEAR_TOL = 0.01;
/** [B11]: the re-lock of one model's library, ms. */
const RELOCK_MAX_MS = 100;
/** The bridges part [B] walks: the clip, the state it leaves, the bounds. */
const BRIDGES = [
  { kind: 'get-up-chair', from: 'sitting-in-chair', driftMax: CHAIR_DRIFT_MAX_M, redMin: CHAIR_RED_MIN_M },
  { kind: 'get-up-bed', from: 'sleeping-side', driftMax: BED_DRIFT_MAX_M, redMin: BED_RED_MIN_M },
];
const HANDOVER_MAX_M = 0.01;
/** [B17]: the chair's end part, and how far its feet may stand off the floor. */
const B17_FROM_S = 3.5;
const B17_MAX_CM = 1.0;
const FADE_SKIP_S = 0.30;
/** `_root_motion.py` contact bands (cm, cm/s) — the smoke's own copy. */
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
      `export { adaptExternalClips, Figure, setClipRootMotion } from '${src}/scene/figures';`,
      `export { relockRootPaths } from '${src}/scene/footLockMeasure';`,
      `export { measureGroundOffsets } from '${src}/scene/clipGround';`,
      `export { NpcManager } from '${src}/scene/npcs';`,
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
          setClipTransitions, restCorrections, restPoseOf, relockRootPaths,
          measureGroundOffsets, NpcManager } = client;

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
  const nominalScale = (template) => {
    const bbox = new THREE.Box3().setFromObject(template);
    return 1.70 / (bbox.max.y - bbox.min.y);
  };
  const makeFigure = (label, template, clips, fixedScale) => {
    const scale = fixedScale ?? nominalScale(template);
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
    const rigWarnings = warned.filter((w) => /root motion/.test(w) && /reference rig/.test(w));
    check('[8] no rig: exactly one travel warning over two adaptations', rigWarnings.length === 1,
      `${rigWarnings.length}: ${rigWarnings[0] ?? '-'}`);
    const standWarnings = warned.filter((w) => /standing height falls back/.test(w));
    check('[8] no rig: exactly one standing-reference warning over two adaptations',
      standWarnings.length === 1, `${standWarnings.length}: ${standWarnings[0] ?? '-'}`);
    check('[8] no rig: the bridge still plays', run.bridged, `${run.frames} frames`);
    check('[8] no rig: no hold during or after it',
      run.seen.every((f) => !f.holds) && fig.figure.holdsTravel === false);
    check('[8] no rig: the instance never leaves its base, never NaN',
      run.seen.every((f) => Number.isFinite(f.x) && Number.isFinite(f.z)
        && Math.abs(f.x - base.x) < 1e-9 && Math.abs(f.z - base.z) < 1e-9));
    check('[8] no rig: takeTravel returns null', fig.figure.takeTravel() === null);
    fig.figure.dispose();
  }

  // [Y1]/[Y2] a holding bridge owns the facing (docstring [Y]).
  console.log('\n[Y1]/[Y2] nothing turns a figure a bridge holds (synthetic, Soldier)');
  const PLUS_X = new THREE.Vector3(1, 0, 0);
  /** Seat the figure at yaw YAW, open the bridge and ask for a turn on every
   *  bridge frame; returns the largest |rotation.y − YAW| seen and the frame
   *  count. */
  const turnDuringBridge = (fig) => {
    fig.figure.faceTowards(new THREE.Vector3(Math.sin(YAW), 0, Math.cos(YAW)), true);
    fig.figure.play('sit-synth');
    for (let i = 0; i < 10; i++) fig.figure.update(0.05);
    fig.figure.play('idle');
    const bridged = fig.figure.bridging;
    let maxTurn = 0;
    let frames = 0;
    while (fig.figure.bridging && frames < 200) {
      fig.figure.faceTowards(PLUS_X, true);
      fig.figure.setYaw(1.0);
      maxTurn = Math.max(maxTurn, Math.abs(fig.figure.root.rotation.y - YAW));
      fig.figure.update(1 / FPS);
      if (fig.figure.bridging) maxTurn = Math.max(maxTurn, Math.abs(fig.figure.root.rotation.y - YAW));
      frames += 1;
    }
    return { bridged, maxTurn, frames };
  };
  setClipTransitions([{ from: 'sit-synth', to: '*', kind: 'bridge-synth', accel: 0 }]);
  {
    const fig = makeFigure('synth-yaw', synthRig, synthLibrary());
    const run = turnDuringBridge(fig);
    check('[Y1] the holding bridge opens', run.bridged, `${run.frames} frames`);
    near('[Y1] faceTowards(+x, snap) + setYaw(1.0) on every bridge frame: rotation.y stays',
      run.maxTurn, 0, 1e-6);
    for (let i = 0; i < 2 * FPS; i++) {
      fig.figure.play('idle');
      fig.figure.update(1 / FPS);
    }
    near('[Y2] 2 s after the bridge: rotation.y reached the last ask (1.0)',
      fig.figure.root.rotation.y, 1.0, 0.05);
    fig.figure.dispose();
  }
  setClipTransitions([{ from: 'sit-synth', to: '*', kind: 'bridge-synth', accel: 1 }]);
  {
    const fig = makeFigure('synth-yaw-ramp', synthRig, synthLibrary());
    const run = turnDuringBridge(fig);
    check('[Y1r] COUNTER-PROBE — a ramping bridge keeps its turn (> 0.1 rad)',
      run.bridged && run.maxTurn > 0.1, `${run.maxTurn.toFixed(4)} rad over ${run.frames} frames`);
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
  const donorHipsY = rigHipsHeight(THREE, refRig);
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

  /** The smoke's OWN contact detection on a RENDERED rig — its own code, the
   *  importer's constants. `frames[i][j]` = world position (metres) of point
   *  j at clip time (i+1)/FPS; `rest[j]` = the point's bind-pose height over
   *  that rig's rest floor (cm); `floorY` = the rest floor's world height
   *  (metres); `size` = rendered scale ÷ nominal scale (heights are judged
   *  at the nominal scale the thresholds are written for). Frames inside the
   *  bridge's fade-in are left out entirely. Returns per point the weight of
   *  every frame (null = left out). */
  const ownWeights = (frames, rest, floorY, size) => {
    const ramp = (x, lo, hi) => (!Number.isFinite(x) ? 0 : x <= lo ? 1 : x >= hi ? 0 : (hi - x) / (hi - lo));
    const first = Math.ceil(FADE_SKIP_S * FPS - 1 - 1e-9);   // (i+1)/FPS >= FADE_SKIP_S
    return FOOT_KEYS.map((_, j) => {
      const h = frames.map((f) => ((f[j].y - floorY) * 100) / size);
      const used = h.slice(first).sort((a, c) => a - c);
      const pct = used[Math.min(used.length - 1, Math.floor(GROUND_PCT * (used.length - 1)))];
      const g = Math.min(pct, rest[j]);
      return h.map((y, i) => {
        if (i < first) return null;
        const a = Math.max(i - 1, first);
        const c = Math.min(i + 1, h.length - 1);
        const vy = c > a ? (h[c] - h[a]) / ((c - a) / FPS) : 0;
        return ramp(y - g, BAND_LO_CM, BAND_HI_CM) * ramp(Math.abs(vy), VY_LO_CM_S, VY_HI_CM_S);
      });
    });
  };
  /** Per point: the largest horizontal distance (world metres) a point moves
   *  from where its run of FULL-weight frames began, the run's span, and how
   *  many frames were full. */
  const ownDrift = (frames, weights) => FOOT_KEYS.map((point, j) => {
    let start = null;
    let t0 = 0;
    const worst = { drift: 0, from: 0, to: 0 };
    let full = 0;
    let runs = 0;
    for (let i = 0; i < frames.length; i++) {
      if ((weights[j][i] ?? 0) >= FULL) {
        full += 1;
        const p = frames[i][j];
        if (!start) { start = p; t0 = (i + 1) / FPS; runs += 1; }
        const d = Math.hypot(p.x - start.x, p.z - start.z);
        if (d > worst.drift) Object.assign(worst, { drift: d, from: t0, to: (i + 1) / FPS });
      } else {
        start = null;
      }
    }
    return { point, full, runs, ...worst };
  });
  const worstOf = (per) => Math.max(0, ...per.map((d) => d.drift));

  // The two real character rigs, and the REFERENCE rig itself as a third
  // figure (a fresh parse, life-size: its centimetres × 0.01).
  const targets = [
    ...RIGS.map((f) => ({ label: f.split('/').pop(), load: () => loadRig(f), scale: undefined })),
    { label: 'reference.fbx', ref: true, scale: 0.01,
      load: async () => fbxLoader.parse(arrayBufferOf(await readFile(RIG_FILE)), '') },
  ];
  const table = [];   // the drift table printed at the end
  for (const target of targets) {
    const { label } = target;
    console.log(`  --- ${label}`);
    const template = await target.load();
    template.updateMatrixWorld(true);
    const scale = target.scale ?? nominalScale(template);
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
    // Rest heights of this rig's contact points, from ITS bind pose, in cm
    // at the nominal scale: over the lowest of the four points and the toe
    // ends (the importer's `_rest_heights`). The template is never posed.
    const restWorld = {};
    template.traverse((o) => {
      if (!o.isBone) return;
      const k = keyOf(o.name);
      if ((FOOT_KEYS.includes(k) || k === 'lefttoeend' || k === 'righttoeend') && !(k in restWorld)) {
        restWorld[k] = o.getWorldPosition(new THREE.Vector3()).y;
      }
    });
    const restFloor = Math.min(...Object.values(restWorld));
    const rest = FOOT_KEYS.map((k) => (restWorld[k] - restFloor) * scale * 100);
    console.log(`      rest heights (cm, own bind pose): ${FOOT_KEYS.map((k, j) => `${k} ${rest[j].toFixed(2)}`).join(', ')}`);

    // [B11] the per-rig re-lock, timed — ONE call per model over its library,
    // exactly as `FigureLibrary.fitLibrary` makes it.
    const relockLib = adapt(true);
    const t0 = performance.now();
    const reports = relockRootPaths(relockLib, template, 1 / (100 * scale));
    const relockMs = performance.now() - t0;
    check(`[B11] ${label}: relockRootPaths per model <= ${RELOCK_MAX_MS} ms`,
      relockMs <= RELOCK_MAX_MS, `${relockMs.toFixed(1)} ms`);
    for (const r of reports) {
      console.log(`      relock ${r.clip}: used ${r.used}${r.reason ? ` (${r.reason})` : ''},`
        + ` its own drift rebuilt ${r.rebuiltDriftCm.toFixed(2)} / imported ${r.importedDriftCm.toFixed(2)} cm,`
        + ` held ${r.pinnedCm.toFixed(2)} / lifted ${r.liftCm.toFixed(2)} cm${r.pinReason ? ` (${r.pinReason})` : ''}`
        + ` → ${r.driftCm.toFixed(2)} cm,`
        + ` travel (${r.travel[0].toFixed(1)}, ${r.travel[1].toFixed(1)}) cm`);
    }
    if (target.ref) {
      // The rig the import was measured on keeps the import's own path.
      for (const b of BRIDGES) {
        const r = reports.find((x) => x.clip === b.kind);
        check(`[6] ${label} ${b.kind}: the reference rig keeps the imported path`,
          r?.used === 'imported', r ? `${r.used}${r.reason ? ` (${r.reason})` : ''}` : 'no report');
      }
    }
    const libs = { relock: relockLib, imported: adapt(true), off: adapt(false) };
    if (target.ref) libs.median = adapt(true, false);

    for (const b of BRIDGES) {
      const rm = sidecars[b.kind];
      /** One bridge on a fresh figure of `lib`; `size` = the scale factor
       *  over the nominal one ([B9]). */
      const runBridge = (lib, size = 1, handOver = false) => {
        const fig = makeFigure(label, template, lib, scale * size);
        const feet = [];
        fig.inst.traverse((o) => { if (o.isBone && FOOT_KEYS.includes(keyOf(o.name))) feet.push(o); });
        feet.sort((a, c) => FOOT_KEYS.indexOf(keyOf(a.name)) - FOOT_KEYS.indexOf(keyOf(c.name)));
        // [B17] per side the foot's bones: Foot, ToeBase, Toe_End.
        const sideBones = { left: [], right: [] };
        fig.inst.traverse((o) => {
          const k = o.isBone ? keyOf(o.name) : '';
          if (/^(left|right)(foot|toebase|toeend)$/.test(k)) sideBones[k.startsWith('left') ? 'left' : 'right'].push(o);
        });
        const lows = [];   // lows[i] = [left, right] lowest foot bone y at clip time (i+1)/FPS
        const sample = () => {
          fig.owner.updateMatrixWorld(true);
          lows.push(['left', 'right'].map((side) =>
            Math.min(...sideBones[side].map((b) => b.getWorldPosition(v).y))));
          return feet.map((f) => { f.getWorldPosition(v); return { x: v.x, y: v.y, z: v.z }; });
        };
        fig.owner.position.set(3, 0, -2);
        // The rest floor in the world, read off the unposed instance.
        fig.owner.updateMatrixWorld(true);
        let floorY = Infinity;
        fig.inst.traverse((o) => {
          const k = o.isBone ? keyOf(o.name) : '';
          if (FOOT_KEYS.includes(k) || k === 'lefttoeend' || k === 'righttoeend') {
            floorY = Math.min(floorY, o.getWorldPosition(v).y);
          }
        });
        const hipsY = hipsOf(fig.inst).getWorldPosition(v).y;   // bind pose, world metres
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
        const r = { frames, floorY, hipsY, held: fig.figure.holdsTravel, lows: lows.slice(0, frames.length) };
        if (handOver) {
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
        } else {
          r.took = fig.figure.takeTravel();
        }
        fig.figure.dispose();
        return r;
      };
      const runs = {};
      for (const mode of Object.keys(libs)) runs[mode] = runBridge(libs[mode], 1, mode === 'relock');
      runs.scaled = runBridge(libs.relock, SCALE_UP);
      const on = runs.relock;
      const nF = on.frames.length;
      console.log(`      ${b.kind}: ${nF} bridge frames, figure hips ${on.hipsY.toFixed(3)} m`);

      // --- [6] drift with the smoke's OWN contacts on this rig -------------
      // Planted is a property of the feet as they are drawn: the weights come
      // from THIS rig's rendered frames, per run — the leg pin lowers planted
      // feet in the re-locked library, so its heights are not the others'.
      const per = {};
      for (const mode of ['relock', 'imported', 'off']) {
        per[mode] = ownDrift(runs[mode].frames, ownWeights(runs[mode].frames, rest, runs[mode].floorY, 1));
      }
      // [B9] the same figure 15 % larger: contacts judged at the nominal scale.
      const wScaled = ownWeights(runs.scaled.frames, rest, runs.scaled.floorY, SCALE_UP);
      per.scaled = ownDrift(runs.scaled.frames, wScaled);
      for (let j = 0; j < FOOT_KEYS.length; j++) {
        const a = per.relock[j];
        const i0 = per.imported[j];
        console.log(`        ${a.point.padEnd(12)} full ${String(a.full).padStart(3)}/${nF} in ${a.runs} run(s)`
          + `  re-locked ${cm(a.drift)} (${a.from.toFixed(2)}–${a.to.toFixed(2)} s)`
          + `  imported ${cm(i0.drift)}  off ${cm(per.off[j].drift)}  ×${SCALE_UP} ${cm(per.scaled[j].drift)}`);
      }
      const dRe = worstOf(per.relock);
      const dIm = worstOf(per.imported);
      const dOff = worstOf(per.off);
      const dUp = worstOf(per.scaled);
      table.push({ label, kind: b.kind, dRe, dIm, dUp });
      check(`${label} ${b.kind}: some point is fully planted on this rig`,
        per.relock.some((d) => d.full > 1), `${per.relock.map((d) => d.full).join('/')} full frames`);
      check(`[6] ${label} ${b.kind}: planted-foot drift (own contacts) <= ${cm(b.driftMax)}`,
        dRe <= b.driftMax, cm(dRe));
      if (target.ref) {
        check(`[6] ${label} ${b.kind}: on its own rig the import's guarantee holds`
          + ` (own contacts <= ${cm(CHAIR_DRIFT_MAX_M)})`, dRe <= CHAIR_DRIFT_MAX_M, cm(dRe));
      }
      check(`[6] ${label} ${b.kind}: COUNTER-PROBE — the imported path is never lower`
        + ' than the re-locked one', dIm >= dRe - 1e-6, `imported ${cm(dIm)} vs re-locked ${cm(dRe)}`);
      if (b.kind === 'get-up-chair' && label === 'Test3_mia.glb') {
        check(`[6] ${label} ${b.kind}: COUNTER-PROBE — the re-lock gains >= ${cm(RELOCK_GAIN_MIN_M)}`,
          dIm - dRe >= RELOCK_GAIN_MIN_M, `${cm(dIm - dRe)} (imported ${cm(dIm)} − re-locked ${cm(dRe)})`);
      }
      check(`[6] ${label} ${b.kind}: RED COUNTER-PROBE — offset off slides >= ${cm(b.redMin)}`,
        dOff >= b.redMin, cm(dOff));
      const expectUp = SCALE_UP * dRe;
      check(`[B9] ${label} ${b.kind}: baseScale × ${SCALE_UP} drifts ${SCALE_UP} × the nominal drift`
        + ` (±${(LINEAR_TOL * 100).toFixed(0)} %)`,
        Math.abs(dUp - expectUp) <= Math.max(LINEAR_TOL * expectUp, 1e-6),
        `${cm(dUp)} vs ${SCALE_UP} × ${cm(dRe)} = ${cm(expectUp)}`
        + ` (${expectUp > 0 ? (((dUp / expectUp) - 1) * 100).toFixed(2) : '0'} %)`);

      // --- INFO: the old measurement, the sidecar's reference-rig spans -----
      // The importer's classification (the reference rig, the RAW clip) in the
      // sidecar's contact windows — what [6] bounded before the per-rig re-lock.
      const tOf = (i) => (i + 1) / FPS;
      const refW = verified[b.kind].weights;
      const wOf = (j, i) => refW[j][Math.min(i + 1, refW[j].length - 1)];
      const inWindow = (i) => rm.contact_s.findIndex(([s0, e0]) => tOf(i) >= s0 && tOf(i) <= e0
        && tOf(i) >= FADE_SKIP_S);
      const spanDrift = (frames) => {
        let out = 0;
        for (let wi = 0; wi < rm.contact_s.length; wi++) {
          for (let j = 0; j < FOOT_KEYS.length; j++) {
            let start = null;
            for (let i = 0; i + 1 < nF; i++) {
              const full = inWindow(i) === wi && inWindow(i + 1) === wi
                && Math.min(wOf(j, i), wOf(j, i + 1)) >= FULL;
              if (!full) { start = null; continue; }
              for (const k of [i, i + 1]) {
                const p = frames[k][j];
                if (!start) start = p;
                out = Math.max(out, Math.hypot(p.x - start.x, p.z - start.z));
              }
            }
          }
        }
        return out;
      };
      const sRe = spanDrift(on.frames);
      const sIm = spanDrift(runs.imported.frames);
      console.log(`      info ${label} ${b.kind}: sidecar spans (reference-rig contacts) —`
        + ` re-locked ${cm(sRe)}, imported ${cm(sIm)}, off ${cm(spanDrift(runs.off.frames))}`);
      if (target.ref) {
        // The scale of the imported travel: on its own rig the importer's
        // number comes back; the idle-median scale overshoots it.
        const own = verified[b.kind].drift / 100;
        const sMed = spanDrift(runs.median.frames);
        check(`[6] ${label} ${b.kind}: RED COUNTER-PROBE — the idle-median scale overshoots`
          + ` the importer (> ${cm(own)} + 0.10 cm; rig scale ${cm(sIm)})`, sMed > own + 0.001, cm(sMed));
      }

      // --- [B17] the chair's end: both feet ON the floor ------------------
      if (b.kind === 'get-up-chair') {
        const end = on.lows.filter((_, i) => (i + 1) / FPS >= B17_FROM_S);
        const median = (a) => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)];
        ['left', 'right'].forEach((side, k) => {
          const hs = end.map((l) => (l[k] - on.floorY) * 100);
          const med = median(hs);
          table[table.length - 1][`b17${side}`] = med;
          check(`[B17] ${label} ${b.kind}: ${side} foot's lowest bone over the floor from`
            + ` ${B17_FROM_S} s (median of ${hs.length}) within ±${B17_MAX_CM} cm`,
            Math.abs(med) <= B17_MAX_CM,
            `${med.toFixed(2)} cm (range ${Math.min(...hs).toFixed(2)} … ${Math.max(...hs).toFixed(2)})`);
        });
      }

      // --- [7] the hand-over ---------------------------------------------
      check(`[7] ${label} ${b.kind}: the travel was held at the end`, on.held && !!on.took);
      check(`[7] ${label} ${b.kind}: hand-over jump <= ${cm(HANDOVER_MAX_M)}`,
        on.jump <= HANDOVER_MAX_M, cm(on.jump));
      const tookLen = on.took ? Math.hypot(on.took.x, on.took.z) : 0;
      {
        // RED counter-probe on a second run: take the travel, do not move the owner.
        const fig2 = makeFigure(label, template, libs.relock, scale);
        fig2.owner.position.set(3, 0, -2);
        const feet2 = [];
        fig2.inst.traverse((o) => { if (o.isBone && FOOT_KEYS.includes(keyOf(o.name))) feet2.push(o); });
        const sample2 = () => {
          fig2.owner.updateMatrixWorld(true);
          return feet2.map((f) => { f.getWorldPosition(v); return { x: v.x, z: v.z }; });
        };
        fig2.figure.faceTowards(new THREE.Vector3(Math.sin(YAW), 0, Math.cos(YAW)), true);
        fig2.figure.play(b.from);
        for (let i = 0; i < 20; i++) fig2.figure.update(0.05);
        fig2.figure.play('idle');
        let guard = 0;
        while (fig2.figure.bridging && guard++ < 1000) fig2.figure.update(1 / FPS);
        const before2 = sample2();
        fig2.figure.takeTravel();
        fig2.figure.update(0);
        const after2 = sample2();
        const redJump = Math.max(...after2.map((p, i) => Math.hypot(p.x - before2[i].x, p.z - before2[i].z)));
        fig2.figure.dispose();
        check(`[7] ${label} ${b.kind}: RED COUNTER-PROBE — owner not moved jumps by the travel`,
          Math.abs(redJump - tookLen) <= 0.05 && redJump >= (b.kind === 'get-up-chair' ? 0.30 : 0.1),
          `${cm(redJump)} vs travel ${cm(tookLen)}`);
      }
      console.log(`      [7] ${label} ${b.kind}: travel handed over ${cm(tookLen)}`
        + ` (${on.took ? `${on.took.x.toFixed(3)}, ${on.took.z.toFixed(3)}` : '-'});`
        + ` next real frame (idle crossfade, 1/30 s) moves the feet ${cm(on.nextJump)}`);

      // --- [B10] INFO: the end point against the server's stand point -------
      // The server carries the figure by travel_m × height / ref_height_m
      // (`room_stand.bridge_offset`), turned by the same facing. Height = the
      // figure's (1.70 m; × SCALE_UP for the larger one); the reference rig
      // IS the reference height (ratio 1).
      const server = (size) => {
        const k = target.ref ? size : (1.70 * size) / rm.ref_height_m;
        return toWorld({ x: rm.travel_m[0] * k, z: rm.travel_m[1] * k }, YAW);
      };
      const off = (took, size) => (took ? Math.hypot(took.x - server(size).x, took.z - server(size).z) : NaN);
      const b10 = { relock: off(on.took, 1), imported: off(runs.imported.took, 1), scaled: off(runs.scaled.took, SCALE_UP) };
      table[table.length - 1].b10 = b10;
      console.log(`      [B10] ${label} ${b.kind}: end point vs the server's stand point —`
        + ` re-locked ${cm(b10.relock)}, imported ${cm(b10.imported)}, ×${SCALE_UP} re-locked ${cm(b10.scaled)}`);
    }
  }

  // ------------------------------------------------------------------ [Y3]
  // The REAL NpcManager.tick over the real client chain (docstring [Y]).
  console.log('\n[Y3] the NPC chain: no step, no turn in a bridge that holds (Test3_mia)');
  {
    const template = await loadRig(RIGS[0]);
    const scale = nominalScale(template);
    const corrections = restCorrections(THREE, donorRest, template);
    const raw = { idle: rawClips.idle, walk: await loadClip('walk'),
      'sleeping-side': rawClips['sleeping-side'], 'get-up-bed': rawClips['get-up-bed'] };
    const lib = adaptExternalClips(Object.entries(raw).map(([name, c]) => {
      const cc = c.clone();
      cc.name = name;
      if (sidecars[name]) setClipRootMotion(cc, true);
      return cc;
    }), template, corrections, donorHipsY);
    relockRootPaths(lib, template, 1 / (100 * scale));
    measureGroundOffsets(lib, template);
    setClipTransitions([{ from: 'sleeping-side', to: '*', kind: 'get-up-bed', accel: 0 }]);
    const DT = 1 / FPS;
    const GOAL_M = 0.5;
    /** One NPC as `NpcManager.update` would build it, injected into a manager
     *  of its own — `tick` is the code under test, not the poll. */
    const npcOn = (name, animation) => {
      const fig = makeFigure(name, template, lib, scale);
      const npc = {
        name, animation, root: fig.owner, figure: fig.figure, ring: null, sprite: null,
        label: { visible: false }, labelName: null, labelActivity: null, labelBubble: null,
        bubbleUntil: 0, target: fig.owner.position.clone(), pace: 1, face: null,
        waypoints: [], ride: null, route: null, travelling: false, reckon: null,
        interaction: null, activity: '', travelLine: null, travelKey: '', bobPhase: 0,
      };
      const mgr = new NpcManager(null);
      mgr.npcs.set(name, npc);
      fig.figure.faceTowards(new THREE.Vector3(Math.sin(YAW), 0, Math.cos(YAW)), true);
      for (let i = 0; i < 20; i++) mgr.tick(0.05, 10);
      return { npc, mgr, fig };
    };
    const xz = (p) => ({ x: p.x, z: p.z });
    const moved = (a, b) => Math.hypot(b.x - a.x, b.z - a.z);
    const goalAhead = (npc) => npc.target.set(npc.root.position.x + Math.sin(YAW) * GOAL_M,
      npc.root.position.y, npc.root.position.z + Math.cos(YAW) * GOAL_M);

    const bed = npcOn('y3-bed', 'sleeping-side');
    check('[Y3] the NPC lies (sleeping-side, no bridge)',
      bed.fig.figure.root.userData.clipKind === 'sleeping-side' && !bed.fig.figure.bridging,
      String(bed.fig.figure.root.userData.clipKind));
    bed.npc.animation = 'idle';
    goalAhead(bed.npc);
    const before = xz(bed.npc.root.position);
    bed.mgr.tick(DT, 10);
    check('[Y3] the tick that stands it up opens the bridge', bed.fig.figure.bridging,
      String(bed.fig.figure.root.userData.clipKind));
    const firstStep = moved(before, bed.npc.root.position);
    check('[Y3] the frame the bridge starts: root X/Z moves <= 1 mm', firstStep <= 0.001, cm(firstStep));
    let guard = 0;
    while (bed.fig.figure.bridging && guard++ < 1000) bed.mgr.tick(DT, 10);
    bed.mgr.tick(DT, 10);   // the hand-over tick: root and goal move by the travel
    const atEnd = xz(bed.npc.root.position);
    for (let i = 0; i < FPS; i++) bed.mgr.tick(DT, 10);
    const walkedOn = moved(atEnd, bed.npc.root.position);
    check('[Y3d] after the bridge and its hand-over the NPC walks on (>= 5 cm within 1 s)', walkedOn >= 0.05, cm(walkedOn));
    bed.fig.figure.dispose();

    const stand = npcOn('y3-stand', 'idle');
    goalAhead(stand.npc);
    const before2 = xz(stand.npc.root.position);
    stand.mgr.tick(DT, 10);
    near('[Y3c] COUNTER-PROBE — without a rule the first tick steps 3.4/30 m',
      moved(before2, stand.npc.root.position), 3.4 / 30, 1e-4);
    stand.fig.figure.dispose();

    const lie = npcOn('y3-face', 'sleeping-side');
    lie.npc.animation = 'idle';
    lie.npc.face = new THREE.Vector3(1, 0, 0);
    const yaw0 = lie.fig.figure.root.rotation.y;
    let maxTurn = 0;
    let frames = 0;
    lie.mgr.tick(DT, 10);
    const opened = lie.fig.figure.bridging;
    while (lie.fig.figure.bridging && frames++ < 1000) {
      maxTurn = Math.max(maxTurn, Math.abs(lie.fig.figure.root.rotation.y - yaw0));
      lie.mgr.tick(DT, 10);
    }
    check('[Y3b] standing up in place opens the bridge', opened, `${frames} frames`);
    near('[Y3b] marker facing +x while the bridge holds: rotation.y stays', maxTurn, 0, 1e-6);
    lie.fig.figure.dispose();
  }

  console.log('\n      drift table (own contacts, cm): clip × rig — re-locked / imported / ×1.15 re-locked; [B10] re-locked / imported');
  for (const r of table) {
    console.log(`        ${r.kind.padEnd(13)} ${r.label.padEnd(14)} ${(r.dRe * 100).toFixed(2)} / ${(r.dIm * 100).toFixed(2)}`
      + ` / ${(r.dUp * 100).toFixed(2)};  B10 ${(r.b10.relock * 100).toFixed(1)} / ${(r.b10.imported * 100).toFixed(1)}`);
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
