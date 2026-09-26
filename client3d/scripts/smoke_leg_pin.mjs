#!/usr/bin/env node
/**
 * Smoke check for the PER-RIG LEG PIN of the 3D client
 * (`client3d/src/scene/legPin.ts`, used by `footLockMeasure.relockRootPaths`):
 * a bridge clip's planted feet are nailed to their spot on each model's OWN
 * skeleton by a two-bone leg IK, baked into the adapted clip — the client's
 * counterpart of the importer's foot plant (`app/blender/scripts/_foot_plant.py`,
 * `cmu_clip._plant_feet` / `_pin_feet`). Numbers only (§ B5a); a SYNTHETIC
 * skeleton, no clip files, no server.
 *
 * Usage:  node client3d/scripts/smoke_leg_pin.mjs
 *         (needs esbuild and three from the workspace)
 *
 * ===========================================================================
 * THE PURE MATHS — the importer's parity cases (scripts/smoke_foot_plant_math.py)
 * ===========================================================================
 * [P2] twoBoneIk, a REACHABLE pull-down, verbatim: hip H (0,100,0), knee
 *      K (0,50,15), ankle A (0,0,0), target T (0,−2,0), pole = K.
 *      l1 = |H−K| = √(50² + 15²) = √2725 = 52.2015 = l2 = |K−A|;
 *      d = |H−T| = 102 < l1 + l2 = 104.4031. Equal segments → the new knee
 *      sits above the midpoint of H–T: y = 100 − d/2 = 49, off the line by
 *      √(l1² − (d/2)²) = √(2725 − 2601) = √124 = 11.1355, on the pole's side
 *      (+z) → knee (0, 49, 11.1355). Applying upper to K−H about H and
 *      lower·upper to A−K about the new knee: the ankle reaches (0,−2,0),
 *      the knee stays in the plane x = 0, both lengths stay 52.2015 (±1e-6).
 * [P3] out of reach: K (0,50,5), target (0,−5,0): hip→target 105 >
 *      2·√2525 = 100.4988 → stretched along hip→target: ankle at
 *      (0, 100 − 100.4988, 0) = (0, −0.4988, 0), knee at (0, 49.7506, 0)
 *      (±1e-6) — and every number finite (no NaN).
 * [P1] pinRuns, the run rule and fade, 30 fps (F = round(0.1·30) = 3):
 *      weights [1]*9 + [0]*14: the run [0, 8] = 9 frames = 0.3 s ≥ 0.2 s,
 *      it starts at the take's first frame → no fade-in, fade-out
 *      min(1, (8 − f + 1)/4) → [1, 1, 1, 1, 1, 1, 0.75, 0.5, 0.25] + [0]*14.
 *      [P1b] a run inside the take fades on both sides: [0]*4 + [1]*7 +
 *      [0]*4, run [4, 10] = 0.233 s → (f − 3)/4 rising, (11 − f)/4 falling →
 *      [0, 0, 0, 0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25, 0, 0, 0, 0].
 *      [P1c] too short: [0]*3 + [1]*5 + [0]*3 (5 frames = 0.167 s < 0.2) →
 *      all 0. [P1d] the ramps do not count as full: [0.9]*20 → all 0.
 *      [P1e] a run touching the LAST frame keeps its end: [0]*4 + [1]*8 →
 *      [0]*4 + [0.25, 0.5, 0.75] + [1]*5.
 *
 * ===========================================================================
 * THE SYNTHETIC SKELETON (template units = cm, unitsPerCm 1)
 * ===========================================================================
 *   rig (Group, identity)
 *   └ mixamorigHips            local (0, 108, 0)   (held there: the hips are fixed)
 *     ├ mixamorigLeftUpLeg     local (10, 0, 0)     → world (10, 108, 0)   hip
 *     │ └ mixamorigLeftLeg     local (0, −50, 15)   → world (10, 58, 15)   knee
 *     │   └ mixamorigLeftFoot  local (0, −50, −15)  → world (10, 8, 0)     ankle
 *     │     └ mixamorigLeftToeBase local (0, −5, 12) → world (10, 3, 12)
 *     │       └ mixamorigLeftToe_End local (0, −3, 6) → world (10, 0, 18)
 *     └ the same on the right with x = −10 (never animated)
 * Both segments are √2725 = 52.2015 long, the hip→ankle line 100 < 104.40:
 * a bent knee, so the IK has its own bending plane (x = ±10).
 * Rest heights over the toe ends: ankle 8, ball 3.
 *
 * THE CLIP, 30 keys f = 0 … 29 at 30 fps: the hips POSITION track holds
 * (0, 108, 0) (it gives the sample times); `mixamorigLeftUpLeg.quaternion`
 * turns the whole left leg about X by θ_f and `mixamorigLeftFoot.quaternion`
 * turns the foot back by −θ_f, so the left foot stays LEVEL (world rotation
 * identity, its ball always (0, −5, 12) off the ankle). Turning (0, −100, 0)
 * about X by θ gives (0, −100 cos θ, −100 sin θ), so with
 *   f = 0 … 14:  sin θ_f = (2f − 10)/100  → ankle z = 10 − 2f: the foot
 *                SLIDES 2 cm a frame backwards while standing (its height
 *                108 − 100 cos θ_f stays within 8 … 9.63 cm);
 *   f = 15 … 29: θ = −60° → ankle (10, 58, 86.6): the foot is up.
 * The right ankle stands still at (−10, 8, 0) the whole clip, while
 * `mixamorigRightFoot.quaternion` turns the right foot about Y (its yaw) by
 * φ_f = −5° + 10°·f/29: a planted foot that pivots, as the actors' feet do
 * while they rise.
 * The imported root path is preset to ZERO.
 *
 * CONTACTS (`footLock.contactWeights`, the client's rule): left ankle ground
 * = min(5th percentile = 2nd lowest of 30 = 8.02 (f = 4, 6), rest 8) = 8;
 * heights ≤ 9.63 → over ground < 2 → band 1; vertical speed on 0 … 13 ≤
 * (9.633 − 8.985)·15 = 9.7 cm/s < 15 → 1; frame 14's central difference
 * reaches the lifted frame 15 → 0; frames 15 … 29 are 48 cm up → 0. The left
 * ball stands 5 cm under its ankle (ground min(3.02, rest 3) = 3, the same
 * heights over it) → the same weights. Right ankle and ball: constant heights
 * 8 and 3 (a yaw does not lift) → 1 everywhere.
 * DOWN (pinRuns of the sampled contacts): left run [0, 13] (14 frames =
 * 0.47 s) from the take's first frame → no fade-in, fade-out F = 3:
 * (13 − f + 1)/4 → [1]*11 + [0.75, 0.5, 0.25] + [0]*16. The LIFT = the least
 * of ankle − 8 and ball − 3 = the ankle's own height over 8 (equal), so the
 * lowered left heights are 8 + (1 − down_f)·(h_f − 8): 8 on f 0 … 10, then
 * 8.1807, 8.4924, 8.9662 on f 11 … 13 (h = 8.7226, 8.9848, 9.2883), f 14
 * unlowered 9.6333. Right: lift 0.
 * HOLD (pinRuns of the contacts of the LOWERED foot): frame 13's vertical
 * speed is now (9.6333 − 8.4924)·15 = 17.114 cm/s → weight (30 − 17.114)/15
 * = 0.8591 (frame 12: (8.9662 − 8.1807)·15 = 11.78 → 1) → the same run,
 * its fade-out × that weight:
 *   left hold  = [1]*11 + [0.75, 0.5, 0.25 · 0.8591 = 0.2148] + [0]*16,
 *   right hold = [1]*30 (a run over the whole take: no fade at all).
 * THE HELD POINT per run: ankle + s·(ball − ankle), s = the ball's share of
 * the two points' contact weights over the run's full frames = 1/(1 + 1) =
 * 0.5 on both feet — the middle of a flat foot.
 *
 * [L1] After relockRootPaths, with u_f = the left ankle's WORLD XZ before the
 *      pin (the probe's in-place position + the stored path, whatever path
 *      the re-lock chose) and A = mean of u_f over the full-hold frames (the
 *      left foot is level, its held middle point sits a constant (0, 6) off
 *      the ankle, so holding it holds the ankle):
 *        left ankle world XZ on f = 0 … 10 equals A (≤ 1 mm) — the foot is
 *        nailed; on the fade frames 11 … 13 it is A + (1 − w_f)(u_f − A)
 *        (w = 0.75, 0.5, 0.2148; ≤ 1 mm) — the importer's blend
 *        `old + w·(anchor − path − old)`;
 *        the left Foot's WORLD rotation is unchanged on every frame
 *        (|Δ| ≤ 1e-6 per component, sign-aligned) — the toes stay flat;
 *        frames 14 … 29 of the left leg are UNCHANGED: ankle and knee world
 *        position (≤ 1e-6) and the three local quaternions (≤ 1e-6);
 *        the LIFT: frame 5 (θ = 0) — ankle 8 over ground 8 → lift 0 → its
 *        height stays 8 (±1e-3); frame 0 (sin θ = −0.1, cos θ = 0.994987) —
 *        ankle 108 − 99.4987 = 8.5013, lift 0.5013, down 1 → 8 (±1e-3);
 *        the report says pinnedCm > 0 (finite), no pinReason, and driftCm
 *        (re-measured AFTER the pin) is below importedDriftCm.
 * [L5] THE PIVOTING RIGHT FOOT: its ball is v = (0, 12) off the ankle in XZ,
 *      turned by φ. Held at the middle point, ankle = M − v(φ)/2 and ball =
 *      M + v(φ)/2 with M fixed (≤ 1 mm), so each moves |v(φ_f) − v(φ_0)|/2 =
 *      6 · 2 sin(|φ_f − φ_0|/2) from where the run began — at most (f = 29,
 *      10°) 12 · sin 5° = 1.0459 cm for BOTH points (±1e-3). Holding the ankle
 *      (the importer's anchor) would leave the ankle at 0 and swing the ball
 *      by the whole 2 · 1.0459 = 2.0917 cm.
 * [L2] The template is untouched: every bone's local position and quaternion
 *      equal (exactly) their values before the call.
 * [L3] The same rig with the left KNEE bone renamed (`mixamorigLeftKnee` — no
 *      `LeftLeg`): the contact points are all there, so the path is still
 *      rebuilt, but there is no leg chain to bend: pinReason 'no leg bones',
 *      pinnedCm 0, and no quaternion track of the clip changed (the values
 *      identical, no track added).
 * [L4] RED COUNTER-PROBE, same run: the left ankle's world XZ over f = 0 … 10
 *      WITHOUT the pin (u_f) moves ≥ 9.5 cm — the path alone cannot hold a
 *      foot that slides against the other one: each step moves the root by
 *      the mean slide of the fully planted points — left ankle and ball −2
 *      each, right ankle 0, right ball at most 12 · (10°/29 in rad) = 0.072 —
 *      so at most (2 + 2 + 0.072)/4 = 1.018 cm a frame, and the left ankle's
 *      world z still moves ≥ (2 − 1.018)·10 = 9.82 cm over f = 0 … 10.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const FPS = 30;
const FRAMES = 30;
const TOL = 1e-6;

let failed = 0;
let passed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`); }
  else { failed += 1; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`); }
}
const close = (a, b, tol = TOL) => a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) <= tol);
const fmt = (a) => `[${a.map((x) => Number(x).toFixed(4)).join(', ')}]`;

async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const entry = [
      `export * from '${src}/legPin';`,
      `export { relockRootPaths } from '${src}/footLockMeasure';`,
      `export { clipRootPath, setClipRootPath } from '${src}/bridgeTravel';`,
    ].join('\n');
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'legpin.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'legpin.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

// (w, x, y, z) quaternion maths of the smoke's own, as in smoke_foot_plant_math.py
function qmat([w, x, y, z]) {
  return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]];
}
const rot = (q, v) => qmat(q).map((r) => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]);
const sub = (a, b) => a.map((x, i) => x - b[i]);
const add = (a, b) => a.map((x, i) => x + b[i]);
const dist = (a, b) => Math.hypot(...sub(a, b));

async function main() {
  const THREE = await import('three');
  const lp = await loadClient();

  console.log('[P2] twoBoneIk: a reachable pull-down');
  {
    const hip = [0, 100, 0]; const knee = [0, 50, 15]; const ankle = [0, 0, 0]; const target = [0, -2, 0];
    const { upper, lower } = lp.twoBoneIk(hip, knee, ankle, target, knee);
    const k2 = add(hip, rot(upper, sub(knee, hip)));
    const a2 = add(k2, rot(lower, rot(upper, sub(ankle, knee))));
    check('ankle reaches the target', close(a2, target), fmt(a2));
    check('knee at (0, 49, 11.1355)', close(k2, [0, 49, Math.sqrt(124)]), fmt(k2));
    check('knee in the plane x = 0', Math.abs(k2[0]) <= TOL, fmt(k2));
    const l = Math.sqrt(2725);
    check('|hip − knee| = 52.2015', Math.abs(dist(hip, k2) - l) <= TOL, String(dist(hip, k2)));
    check('|knee − ankle| = 52.2015', Math.abs(dist(k2, a2) - l) <= TOL, String(dist(k2, a2)));
  }

  console.log('\n[P3] twoBoneIk: out of reach → stretched along hip→target');
  {
    const hip = [0, 100, 0]; const knee = [0, 50, 5]; const ankle = [0, 0, 0]; const target = [0, -5, 0];
    const { upper, lower } = lp.twoBoneIk(hip, knee, ankle, target, knee);
    const k2 = add(hip, rot(upper, sub(knee, hip)));
    const a2 = add(k2, rot(lower, rot(upper, sub(ankle, knee))));
    const l = Math.sqrt(2525);
    check('every number finite', [...upper, ...lower, ...k2, ...a2].every(Number.isFinite));
    check('ankle at (0, −0.4988, 0)', close(a2, [0, 100 - 2 * l, 0]), fmt(a2));
    check('knee at (0, 49.7506, 0)', close(k2, [0, 100 - l, 0]), fmt(k2));
  }

  console.log('\n[P1] pinRuns: run rule and fade');
  {
    check('constants PIN_MIN_S 0.2, PIN_FADE_S 0.1', lp.PIN_MIN_S === 0.2 && lp.PIN_FADE_S === 0.1);
    const cases = [
      ['[P1] no fade-in at the take\'s start', [...Array(9).fill(1), ...Array(14).fill(0)],
        [1, 1, 1, 1, 1, 1, 0.75, 0.5, 0.25, ...Array(14).fill(0)]],
      ['[P1b] a run inside the take fades on both sides', [...Array(4).fill(0), ...Array(7).fill(1), ...Array(4).fill(0)],
        [0, 0, 0, 0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25, 0, 0, 0, 0]],
      ['[P1c] 5 full frames (0.167 s) are a step, not a stand', [0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0],
        Array(11).fill(0)],
      ['[P1d] the ramps alone never count as full', Array(20).fill(0.9), Array(20).fill(0)],
      ['[P1e] a run touching the last frame keeps its end', [...Array(4).fill(0), ...Array(8).fill(1)],
        [0, 0, 0, 0, 0.25, 0.5, 0.75, 1, 1, 1, 1, 1]],
    ];
    for (const [label, w, want] of cases) {
      const got = lp.pinRuns(w, FPS);
      check(label, close(got, want), fmt(got));
    }
  }

  // ------------------------------------------------------------ the rig
  const { relockRootPaths, clipRootPath, setClipRootPath } = lp;
  const bone = (name, x, y, z, parent) => {
    const b = new THREE.Bone();
    b.name = name;
    b.position.set(x, y, z);
    if (parent) parent.add(b);
    return b;
  };
  const buildRig = ({ leftKneeName = 'mixamorigLeftLeg' } = {}) => {
    const rig = new THREE.Group();
    const hips = bone('mixamorigHips', 0, 108, 0, rig);
    for (const [side, x] of [['Left', 10], ['Right', -10]]) {
      const up = bone(`mixamorig${side}UpLeg`, x, 0, 0, hips);
      const knee = bone(side === 'Left' ? leftKneeName : 'mixamorigRightLeg', 0, -50, 15, up);
      const foot = bone(`mixamorig${side}Foot`, 0, -50, -15, knee);
      const ball = bone(`mixamorig${side}ToeBase`, 0, -5, 12, foot);
      bone(`mixamorig${side}Toe_End`, 0, -3, 6, ball);
    }
    rig.updateMatrixWorld(true);
    return rig;
  };
  const times = Array.from({ length: FRAMES }, (_, f) => f / FPS);
  const thetaOf = (f) => (f <= 14 ? Math.asin((2 * f - 10) / 100) : -Math.PI / 3);
  const phiOf = (f) => ((-5 + (10 * f) / 29) * Math.PI) / 180;
  const X = new THREE.Vector3(1, 0, 0);
  const Y = new THREE.Vector3(0, 1, 0);
  const quats = (axis, angleOf) => times.flatMap((_, f) => new THREE.Quaternion()
    .setFromAxisAngle(axis, angleOf(f)).toArray());
  const buildClip = (name) => {
    const hipsVals = times.flatMap(() => [0, 108, 0]);
    const clip = new THREE.AnimationClip(name, times[FRAMES - 1], [
      new THREE.VectorKeyframeTrack('mixamorigHips.position', times, hipsVals),
      new THREE.QuaternionKeyframeTrack('mixamorigLeftUpLeg.quaternion', times, quats(X, thetaOf)),
      new THREE.QuaternionKeyframeTrack('mixamorigLeftFoot.quaternion', times, quats(X, (f) => -thetaOf(f))),
      new THREE.QuaternionKeyframeTrack('mixamorigRightFoot.quaternion', times, quats(Y, phiOf)),
    ]);
    setClipRootPath(clip, { times: Float32Array.from(times), xz: new Float32Array(FRAMES * 2) });
    return clip;
  };
  /** Play `clip` on a fresh clone of `rig` and read, per frame, world data of
   *  the named bones: position (cm), world quaternion, local quaternion. */
  const sampleClip = (rig, clip, names) => {
    const view = rig.clone(true);
    view.updateMatrixWorld(true);
    const byName = {};
    view.traverse((o) => { if (o.isBone) byName[o.name] = o; });
    const mixer = new THREE.AnimationMixer(view);
    const action = mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    action.play();
    const out = Object.fromEntries(names.map((n) => [n, []]));
    for (const t of times) {
      action.paused = false;
      mixer.setTime(t);
      view.updateMatrixWorld(true);
      for (const n of names) {
        const b = byName[n];
        out[n].push({
          p: b.getWorldPosition(new THREE.Vector3()).toArray(),
          qw: b.getWorldQuaternion(new THREE.Quaternion()).toArray(),
          ql: b.quaternion.toArray(),
        });
      }
    }
    action.stop();
    mixer.uncacheClip(clip);
    return out;
  };
  const snapshot = (rig) => {
    const s = [];
    rig.traverse((o) => s.push([o.name, ...o.position.toArray(), ...o.quaternion.toArray()]));
    return JSON.stringify(s);
  };
  const LEFT = ['mixamorigLeftUpLeg', 'mixamorigLeftLeg', 'mixamorigLeftFoot'];
  const NAMES = [...LEFT, 'mixamorigRightFoot', 'mixamorigRightToeBase'];
  const expectLeftHold = [...Array(11).fill(1), 0.75, 0.5, 0.25 * ((30 - 17.114) / 15), ...Array(16).fill(0)];

  console.log('\n[L1]–[L5] a sliding and a pivoting foot on a synthetic skeleton (hips fixed)');
  {
    const rig = buildRig();
    const before = snapshot(rig);
    const clip = buildClip('bridge-slide');
    const pre = sampleClip(rig, clip, NAMES);
    const reports = relockRootPaths([clip], rig, 1);
    const r = reports[0];
    console.log(`      report: used ${r?.used}${r?.reason ? ` (${r.reason})` : ''}, drift ${r?.driftCm?.toFixed(3)} cm`
      + ` (imported ${r?.importedDriftCm?.toFixed(3)}), pinned ${r?.pinnedCm?.toFixed(3)} cm`
      + `${r?.pinReason ? `, ${r.pinReason}` : ''}`);
    const post = sampleClip(rig, clip, NAMES);
    const path = clipRootPath(clip);
    const off = (f) => [path.xz[f * 2], path.xz[f * 2 + 1]];
    const worldXZ = (samples, f) => [samples[f].p[0] + off(f)[0], samples[f].p[2] + off(f)[1]];

    // the anchor per foot: the mean world XZ BEFORE the pin over its full frames
    const anchor = (samples, pin) => {
      const full = pin.map((w, f) => (w >= 0.999 ? f : -1)).filter((f) => f >= 0);
      const s = full.reduce((a, f) => add(a, worldXZ(samples, f)), [0, 0]);
      return s.map((x) => x / full.length);
    };
    const la = anchor(pre.mixamorigLeftFoot, expectLeftHold);
    console.log(`      left anchor (${fmt(la)}) cm`);
    let worstNail = 0;
    let worstFade = 0;
    for (let f = 0; f < 14; f++) {
      const w = expectLeftHold[f];
      const u = worldXZ(pre.mixamorigLeftFoot, f);
      const want = add(la, u.map((x, i) => (1 - w) * (x - la[i])));
      const got = worldXZ(post.mixamorigLeftFoot, f);
      const d = Math.hypot(got[0] - want[0], got[1] - want[1]);
      if (w >= 0.999) worstNail = Math.max(worstNail, d);
      else worstFade = Math.max(worstFade, d);
    }
    check('[L1] left ankle nailed to its anchor on f 0 … 10 (≤ 1 mm)', worstNail <= 0.1, `${worstNail.toFixed(6)} cm`);
    check('[L1] fade frames 11 … 13 at A + (1 − w)(u − A) (≤ 1 mm)', worstFade <= 0.1, `${worstFade.toFixed(6)} cm`);
    // [L5] the pivoting right foot: held at its middle
    const mid = (f) => worldXZ(post.mixamorigRightFoot, f).map((x, i) =>
      (x + worldXZ(post.mixamorigRightToeBase, f)[i]) / 2);
    let midMove = 0;
    let ankleDrift = 0;
    let ballDrift = 0;
    for (let f = 0; f < FRAMES; f++) {
      midMove = Math.max(midMove, Math.hypot(...sub(mid(f), mid(0))));
      ankleDrift = Math.max(ankleDrift, Math.hypot(...sub(worldXZ(post.mixamorigRightFoot, f),
        worldXZ(post.mixamorigRightFoot, 0))));
      ballDrift = Math.max(ballDrift, Math.hypot(...sub(worldXZ(post.mixamorigRightToeBase, f),
        worldXZ(post.mixamorigRightToeBase, 0))));
    }
    const half = 12 * Math.sin((5 * Math.PI) / 180);
    check('[L5] the pivoting right foot is held at its middle (≤ 1 mm)', midMove <= 0.1, `${midMove.toFixed(6)} cm`);
    check('[L5] right ankle drifts 12·sin 5° = 1.0459 cm (±1e-3)', Math.abs(ankleDrift - half) <= 1e-3,
      `${ankleDrift.toFixed(5)} cm`);
    check('[L5] right ball drifts 12·sin 5° = 1.0459 cm (±1e-3)', Math.abs(ballDrift - half) <= 1e-3,
      `${ballDrift.toFixed(5)} cm`);
    let worstRotation = 0;
    for (let f = 0; f < FRAMES; f++) {
      const a = pre.mixamorigLeftFoot[f].qw;
      const b = post.mixamorigLeftFoot[f].qw;
      const sgn = a.reduce((s, x, i) => s + x * b[i], 0) < 0 ? -1 : 1;
      worstRotation = Math.max(worstRotation, ...a.map((x, i) => Math.abs(x - sgn * b[i])));
    }
    check('[L1] the left Foot keeps its world rotation on every frame (≤ 1e-6)', worstRotation <= TOL,
      worstRotation.toExponential(2));
    let worstOutside = 0;
    for (let f = 14; f < FRAMES; f++) {
      for (const n of LEFT) {
        const a = pre[n][f];
        const b = post[n][f];
        worstOutside = Math.max(worstOutside, ...a.ql.map((x, i) => Math.abs(x - b.ql[i])));
      }
      for (const n of ['mixamorigLeftLeg', 'mixamorigLeftFoot']) {
        worstOutside = Math.max(worstOutside, dist(pre[n][f].p, post[n][f].p));
      }
    }
    check('[L1] frames 14 … 29 of the left leg unchanged (≤ 1e-6)', worstOutside <= TOL,
      worstOutside.toExponential(2));
    const y5 = post.mixamorigLeftFoot[5].p[1];
    const y0 = post.mixamorigLeftFoot[0].p[1];
    check('[L1] lift: frame 5 ankle height stays 8 (±1e-3)', Math.abs(y5 - 8) <= 1e-3, y5.toFixed(5));
    check('[L1] lift: frame 0 ankle comes down from 8.5013 to 8 (±1e-3)',
      Math.abs(pre.mixamorigLeftFoot[0].p[1] - 8.5013) <= 1e-3 && Math.abs(y0 - 8) <= 1e-3,
      `${pre.mixamorigLeftFoot[0].p[1].toFixed(5)} → ${y0.toFixed(5)}`);
    check('[L1] report: pinnedCm > 0 and finite, no pinReason',
      Number.isFinite(r?.pinnedCm) && r.pinnedCm > 0 && !r.pinReason, `${r?.pinnedCm} ${r?.pinReason ?? ''}`);
    check('[L1] report: driftCm (after the pin) below importedDriftCm',
      Number.isFinite(r?.driftCm) && r.driftCm < r.importedDriftCm,
      `${r?.driftCm?.toFixed(3)} < ${r?.importedDriftCm?.toFixed(3)}`);
    let redMove = 0;
    const u0 = worldXZ(pre.mixamorigLeftFoot, 0);
    for (let f = 0; f <= 10; f++) {
      const u = worldXZ(pre.mixamorigLeftFoot, f);
      redMove = Math.max(redMove, Math.hypot(u[0] - u0[0], u[1] - u0[1]));
    }
    check('[L4] RED COUNTER-PROBE — without the pin the left ankle moves ≥ 9.5 cm', redMove >= 9.5,
      `${redMove.toFixed(3)} cm`);
    check('[L2] the template is untouched', snapshot(rig) === before);
  }

  console.log('\n[L3] no LeftLeg bone: nothing is pinned');
  {
    const rig = buildRig({ leftKneeName: 'mixamorigLeftKnee' });
    const clip = buildClip('bridge-noleg');
    const tracksBefore = clip.tracks.map((t) => [t.name, Array.from(t.values)]);
    const r = relockRootPaths([clip], rig, 1)[0];
    check("[L3] pinReason 'no leg bones'", r?.pinReason === 'no leg bones', `${r?.pinReason}`);
    check('[L3] pinnedCm 0', r?.pinnedCm === 0, `${r?.pinnedCm}`);
    const tracksAfter = clip.tracks.map((t) => [t.name, Array.from(t.values)]);
    check('[L3] no track changed or added', JSON.stringify(tracksAfter) === JSON.stringify(tracksBefore),
      `${tracksBefore.length} → ${tracksAfter.length} tracks`);
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
