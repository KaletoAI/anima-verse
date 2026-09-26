#!/usr/bin/env node
/**
 * Smoke check for THE TURN OF A BRIDGE CLIP — `client3d/src/scene/bridgeHeading.ts`
 * (the heading of the pelvis per frame), `bridgeTravel.turnAt` (its
 * interpolation) and the bake in `footLockMeasure.relockRootPaths` (the turn
 * moved out of the hips track), Task C2 of plan-bruecken-feinschliff.
 * § B5a: numbers, never screenshots. The whole chain on real rigs is
 * `smoke_bridge_root.mjs` [B12]–[B15].
 *
 * Usage:  node client3d/scripts/smoke_bridge_heading.mjs
 *         (bundles the client modules itself; needs no clip files)
 *
 * Convention (clip frame, +Z forward, +X the figure's LEFT; yaw f means
 * forward (sin f, cos f), as in `bridgeTravel.toWorld` and three.js
 * `rotation.y`): L = leftUpLeg − rightUpLeg, heading = atan2(L.x, L.z) − π/2.
 *
 * [H1] Straight pelvis: left (10,100,0), right (−10,100,0) → L = (20,0,0),
 *      atan2(20, 0) − π/2 = 0.
 *      Turned 90° to the figure's RIGHT (forward now −X): left (0,100,10),
 *      right (0,100,−10) → L = (0,0,20), atan2(0, 20) − π/2 = −π/2.
 *      A two-frame take [straight, turned] → track [0, −π/2].
 * [H2] Unwrap: headings −170°, 175°, 160° (absolute) → relative track
 *      0, −15°, −30° (not +345°). A heading h is built as L = (cos h, 0,
 *      −sin h) · 20 (then atan2(cos h, −sin h) − π/2 = h), left = right + L.
 * [H3] A frame whose L vector is (0.1, 1, 0) (horizontal share
 *      0.1/|L| = 0.0995 < HEADING_MIN_HORIZONTAL 0.5) keeps the previous
 *      value: headings 0°, −20°, rolled, −40° → 0, −20°, −20°, −40°.
 *      A take that STARTS rolled takes the first valid value for its leading
 *      frames: rolled, rolled, 30°, 10° → relative to the first valid (30°):
 *      0, 0, 0, −20°.
 * [H5] turnAt: times [0,1,2], yaw [0, −0.5, −1.9] → t = 0.5 → −0.25
 *      (half way between 0 and −0.5), t = 5 → −1.9 (clamped), t = −1 → 0
 *      (clamped), NaN → 0 (the first key).
 *
 * THE SYNTHETIC SKELETON (template units = cm, unitsPerCm 1), the one of
 * `smoke_leg_pin.mjs`:
 *   rig (Group, identity)
 *   └ mixamorigHips            local (0, 108, 0)
 *     ├ mixamorig<Side>UpLeg   local (±10, 0, 0)     → world (±10, 108, 0)
 *     │ └ mixamorig<Side>Knee  local (0, −50, 15)    (a KNEE, not a `Leg`:
 *     │   │                     no leg chain, so the leg pin stays out and
 *     │   │                     only the turn is under test)
 *     │   └ mixamorig<Side>Foot local (0, −50, −15)  → world (±10, 8, 0)
 *     │     └ mixamorig<Side>ToeBase (0, −5, 12) └ mixamorig<Side>Toe_End (0, −3, 6)
 * THE CLIP, 30 keys f = 0 … 29 at 30 fps: the hips POSITION track holds
 * (0, 108, 0) (it gives the sample times), the hips QUATERNION turns about
 * +Y by α_f = −90° · f/29 (to the figure's right). The imported path is
 * preset to ZERO (`setClipRootPath`), so the clip counts as a travelling
 * bridge.
 *
 * [H6] The turn measured on it: the UpLegs sit at Ry(α)(±10, 0, 0) off the
 *      hips, so L = Ry(α)(20, 0, 0) = (20 cos α, 0, −20 sin α) and the
 *      heading is atan2(cos α, −sin α) − π/2 = α (α ∈ [−90°, 0]). Expected:
 *      `clipRootTurn(clip).yaw[f]` = −(π/2)·f/29 (±1e-5), its times the hips
 *      keys f/30, its pivot the hips' rest point in template-local
 *      coordinates (0, 108, 0) (±1e-6); the report's turnDeg = −90 (±1e-3).
 *      THE BAKE: the hips turned back about the vertical through the pivot
 *      by −α_f: world quaternion Ry(−α)·Ry(α) = identity on every key
 *      (|component − (0,0,0,1)| ≤ 1e-6, sign-aligned), position (0, 108, 0)
 *      unchanged (the pivot is on the hips' own vertical) (±1e-6).
 *      INVARIANCE (the rule `Figure` relies on): every bone's world position
 *      of the baked clip, turned by Ry(+ψ_f) about the pivot's vertical,
 *      equals the same bone of the SAME clip re-locked without the bake
 *      (`relockRootPaths(…, { turn: false })`) within 1e-3 cm on every key.
 *      A second call with `{ turn: false }` stores no turn.
 * [H7] A pelvis that never turns: the same rig and clip with α_f = 0 on
 *      every key → ψ ≡ 0 (below TURN_NONE_RAD 1e-6 everywhere): nothing to
 *      hand over — no turn stored, the hips tracks untouched (values
 *      identical), turnDeg 0, and the log line carries no turn part (like
 *      the pin part when it moved nothing).
 * [H4] Missing bones: the same rig with the UpLegs named `…Thigh` (no
 *      `LeftUpLeg`/`RightUpLeg`): no turn is stored (`clipRootTurn`
 *      undefined), the hips quaternion track is the one of the clip
 *      (values identical), the report's turnDeg is null with turnReason
 *      'no hip bones', and the log line says `turn: none (no hip bones)`.
 *      The figure then keeps its yaw — `Figure` reads no turn.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const FPS = 30;
const FRAMES = 30;
const D = Math.PI / 180;

let failed = 0;
let passed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`); }
  else { failed += 1; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`); }
}
const close = (a, b, tol) => a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) <= tol);
const fmt = (a) => `[${Array.from(a).map((x) => Number(x).toFixed(5)).join(', ')}]`;

async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const entry = [
      `export { headingTrack, HEADING_MIN_HORIZONTAL } from '${src}/bridgeHeading';`,
      `export { turnAt, clipRootTurn, setClipRootPath } from '${src}/bridgeTravel';`,
      `export { relockRootPaths } from '${src}/footLockMeasure';`,
    ].join('\n');
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'heading.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'heading.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Left and right UpLeg for an absolute heading h (degrees), right at the
 *  origin's side (−10, 100, 0) — docstring [H2]. */
const legsAt = (hDeg) => {
  const h = hDeg * D;
  const right = [-10, 100, 0];
  return { left: [right[0] + 20 * Math.cos(h), 100, right[2] - 20 * Math.sin(h)], right };
};
const ROLLED = { left: [-9.9, 101, 0], right: [-10, 100, 0] };   // L = (0.1, 1, 0)

async function main() {
  const THREE = await import('three');
  const c = await loadClient();

  console.log('[H1] heading from the hips cross vector');
  check('HEADING_MIN_HORIZONTAL = 0.5', c.HEADING_MIN_HORIZONTAL === 0.5);
  {
    const got = c.headingTrack([[10, 100, 0], [0, 100, 10]], [[-10, 100, 0], [0, 100, -10]]);
    check('[straight, turned right 90°] → [0, −π/2]', close(got, [0, -Math.PI / 2], 1e-6), fmt(got));
  }

  console.log('\n[H2] unwrapped, relative to frame 0');
  {
    const takes = [-170, 175, 160].map(legsAt);
    const got = c.headingTrack(takes.map((t) => t.left), takes.map((t) => t.right));
    check('−170°, 175°, 160° → 0, −15°, −30°', close(got, [0, -15 * D, -30 * D], 1e-6), fmt(got));
  }

  console.log('\n[H3] a rolled pelvis keeps the last valid heading');
  {
    const takes = [legsAt(0), legsAt(-20), ROLLED, legsAt(-40)];
    const got = c.headingTrack(takes.map((t) => t.left), takes.map((t) => t.right));
    check('0°, −20°, rolled, −40° → 0, −20°, −20°, −40°',
      close(got, [0, -20 * D, -20 * D, -40 * D], 1e-6), fmt(got));
    const lead = [ROLLED, ROLLED, legsAt(30), legsAt(10)];
    const got2 = c.headingTrack(lead.map((t) => t.left), lead.map((t) => t.right));
    check('rolled, rolled, 30°, 10° → 0, 0, 0, −20°', close(got2, [0, 0, 0, -20 * D], 1e-6), fmt(got2));
  }

  console.log('\n[H5] turnAt — linear, clamped');
  {
    const turn = { times: new Float32Array([0, 1, 2]), yaw: new Float32Array([0, -0.5, -1.9]),
      pivot: [0, 0, 0] };
    for (const [t, want] of [[0.5, -0.25], [5, -1.9], [-1, 0], [NaN, 0], [1, -0.5]]) {
      const got = c.turnAt(turn, t);
      check(`t = ${t} → ${want}`, Math.abs(got - want) <= 1e-6, got.toFixed(6));
    }
  }

  // ------------------------------------------------ the synthetic rig
  const bone = (name, x, y, z, parent) => {
    const b = new THREE.Bone();
    b.name = name;
    b.position.set(x, y, z);
    parent.add(b);
    return b;
  };
  const buildRig = (upLeg = 'UpLeg') => {
    const rig = new THREE.Group();
    const hips = bone('mixamorigHips', 0, 108, 0, rig);
    for (const [side, x] of [['Left', 10], ['Right', -10]]) {
      const up = bone(`mixamorig${side}${upLeg}`, x, 0, 0, hips);
      const knee = bone(`mixamorig${side}Knee`, 0, -50, 15, up);
      const foot = bone(`mixamorig${side}Foot`, 0, -50, -15, knee);
      const ball = bone(`mixamorig${side}ToeBase`, 0, -5, 12, foot);
      bone(`mixamorig${side}Toe_End`, 0, -3, 6, ball);
    }
    rig.updateMatrixWorld(true);
    return rig;
  };
  let alpha = (f) => (-90 * D * f) / (FRAMES - 1);
  const buildClip = () => {
    const times = Array.from({ length: FRAMES }, (_, f) => f / FPS);
    const pos = times.flatMap(() => [0, 108, 0]);
    const quat = times.flatMap((_, f) =>
      new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), alpha(f)).toArray());
    const clip = new THREE.AnimationClip('turn-synth', times[FRAMES - 1], [
      new THREE.VectorKeyframeTrack('mixamorigHips.position', times, pos),
      new THREE.QuaternionKeyframeTrack('mixamorigHips.quaternion', times, quat),
    ]);
    c.setClipRootPath(clip, { times: Float32Array.from(times), xz: new Float32Array(FRAMES * 2) });
    return clip;
  };
  const hipsTrack = (clip, prop) => clip.tracks.find((t) => t.name === `mixamorigHips.${prop}`);
  /** World position of every bone of `rig` at every key of `clip` (a clone
   *  of the rig is posed; the rig itself is not). */
  const sampleBones = (rig, clip) => {
    const probe = rig.clone(true);
    const bones = [];
    probe.traverse((o) => { if (o.isBone) bones.push(o); });
    const mixer = new THREE.AnimationMixer(probe);
    const action = mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    action.play();
    const out = [];
    for (let f = 0; f < FRAMES; f++) {
      action.paused = false;
      mixer.setTime(f / FPS);
      probe.updateMatrixWorld(true);
      out.push({
        pos: bones.map((b) => b.getWorldPosition(new THREE.Vector3())),
        hipsQ: bones[0].getWorldQuaternion(new THREE.Quaternion()),
        hipsP: bones[0].getWorldPosition(new THREE.Vector3()),
      });
    }
    return out;
  };

  console.log('\n[H6] the turn measured on a synthetic rig and baked out of the hips');
  {
    const rig = buildRig();
    const clip = buildClip();
    const plain = buildClip();
    const lines = [];
    const [rep] = c.relockRootPaths([clip], rig, 1, (m) => lines.push(m));
    c.relockRootPaths([plain], rig, 1, undefined, { turn: false });
    const turn = c.clipRootTurn(clip);
    check('a turn is stored', !!turn);
    if (turn) {
      const want = Array.from({ length: FRAMES }, (_, f) => alpha(f));
      check('yaw[f] = −(π/2)·f/29', close(turn.yaw, want, 1e-5),
        `${fmt(turn.yaw.slice(0, 3))} … ${turn.yaw[FRAMES - 1].toFixed(6)}`);
      check('times = the hips keys f/30', close(turn.times, want.map((_, f) => f / FPS), 1e-6));
      check('pivot = the hips rest (0, 108, 0)', close(turn.pivot, [0, 108, 0], 1e-6), fmt(turn.pivot));
    }
    check('report turnDeg = −90', Math.abs((rep?.turnDeg ?? NaN) + 90) <= 1e-3, String(rep?.turnDeg));
    check('the log line names the turn', lines.some((l) => /turn -90\.0°/.test(l)), lines.join(' | '));
    check('{ turn: false } stores no turn', c.clipRootTurn(plain) === undefined);
    const baked = sampleBones(rig, clip);
    const ref = sampleBones(rig, plain);
    let qErr = 0;
    let pErr = 0;
    let inv = 0;
    const pivot = new THREE.Vector3(0, 108, 0);
    baked.forEach((fr, f) => {
      const q = fr.hipsQ.clone();
      if (q.w < 0) q.set(-q.x, -q.y, -q.z, -q.w);
      qErr = Math.max(qErr, Math.abs(q.x), Math.abs(q.y), Math.abs(q.z), Math.abs(q.w - 1));
      pErr = Math.max(pErr, fr.hipsP.distanceTo(pivot));
      const back = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), alpha(f));
      fr.pos.forEach((p, i) => {
        const w = p.clone().sub(pivot).applyQuaternion(back).add(pivot);
        inv = Math.max(inv, w.distanceTo(ref[f].pos[i]));
      });
    });
    check('baked hips world quaternion = identity on every key', qErr <= 1e-6, qErr.toExponential(2));
    check('baked hips position unchanged (0, 108, 0)', pErr <= 1e-6, pErr.toExponential(2));
    check('INVARIANCE: baked bones turned back by ψ = the unbaked clip (≤ 1e-3 cm)', inv <= 1e-3,
      inv.toExponential(2));
  }

  console.log('\n[H7] a pelvis that never turns → nothing handed over');
  {
    const turning = alpha;
    alpha = () => 0;
    const rig = buildRig();
    const clip = buildClip();
    const before = ['position', 'quaternion'].map((p) => Array.from(hipsTrack(clip, p).values));
    const lines = [];
    const [rep] = c.relockRootPaths([clip], rig, 1, (m) => lines.push(m));
    check('no turn stored', c.clipRootTurn(clip) === undefined);
    check('the hips tracks are untouched', ['position', 'quaternion'].every((p, k) => {
      const t = hipsTrack(clip, p);
      return !!t && t.values.length === before[k].length && t.values.every((x, i) => x === before[k][i]);
    }));
    check('report turnDeg 0', rep?.turnDeg === 0, String(rep?.turnDeg));
    check('the log line has no turn part', lines.length === 1 && !/, turn[ :]/.test(lines[0]), lines.join(' | '));
    alpha = turning;
  }

  console.log('\n[H4] no UpLeg bones → no turn');
  {
    const rig = buildRig('Thigh');
    const clip = buildClip();
    const before = Array.from(hipsTrack(clip, 'quaternion').values);
    const lines = [];
    const [rep] = c.relockRootPaths([clip], rig, 1, (m) => lines.push(m));
    check('no turn stored', c.clipRootTurn(clip) === undefined);
    const after = hipsTrack(clip, 'quaternion');
    check('the hips quaternion track is the clip\'s own', !!after
      && after.values.length === before.length && after.values.every((x, i) => x === before[i]));
    check('report: turnDeg null, turnReason "no hip bones"',
      rep?.turnDeg === null && rep?.turnReason === 'no hip bones',
      `${rep?.turnDeg} / ${rep?.turnReason}`);
    check('the log line says "turn: none (no hip bones)"',
      lines.some((l) => l.includes('turn: none (no hip bones)')), lines.join(' | '));
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
