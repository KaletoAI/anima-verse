#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/leg_pin.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_leg_pin.mjs
 *         (needs esbuild and three from the workspace)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
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
      `export { qrot, rotationBetween, twoBoneIk } from '${join(ROOT, 'packages/scene-render/src')}/twoBoneIk';`,
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

const sub = (a, b) => a.map((x, i) => x - b[i]);
const add = (a, b) => a.map((x, i) => x + b[i]);
const dist = (a, b) => Math.hypot(...sub(a, b));

async function main() {
  const THREE = await import('three');
  const lp = await loadClient();

  const vectors = await runBridgeVectors('leg_pin');
  passed += vectors.passed; failed += vectors.failed;

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
    check('[L1] report: liftCm ≥ 0.5013 − 1e-3', Number.isFinite(r?.liftCm) && r.liftCm >= 0.5013 - 1e-3,
      `${r?.liftCm}`);
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
    check('[L3] pinnedCm 0, liftCm 0', r?.pinnedCm === 0 && r?.liftCm === 0, `${r?.pinnedCm} ${r?.liftCm}`);
    const tracksAfter = clip.tracks.map((t) => [t.name, Array.from(t.values)]);
    check('[L3] no track changed or added', JSON.stringify(tracksAfter) === JSON.stringify(tracksBefore),
      `${tracksBefore.length} → ${tracksAfter.length} tracks`);
  }

  console.log('\n[L6] a foot rolling onto its side inside a planted stretch is not moved');
  {
    const rig = buildRig();
    const Z = new THREE.Vector3(0, 0, 1);
    const alphaDeg = (f) => ({ 11: 45, 12: 75, 13: 90, 14: 90, 15: 90, 16: 90, 17: 75, 18: 45 })[f] ?? 0;
    const raise = (f) => ({ 11: 0.25, 12: 0.5, 13: 1, 14: 1, 15: 1, 16: 1, 17: 0.5, 18: 0.25 })[f] ?? 0;
    const clip = new THREE.AnimationClip('bridge-roll', times[FRAMES - 1], [
      new THREE.VectorKeyframeTrack('mixamorigHips.position', times, times.flatMap(() => [0, 108, 0])),
      new THREE.QuaternionKeyframeTrack('mixamorigRightFoot.quaternion', times,
        quats(Z, (f) => (alphaDeg(f) * Math.PI) / 180)),
      new THREE.VectorKeyframeTrack('mixamorigRightFoot.position', times,
        times.flatMap((_, f) => [0, -50 + raise(f), -15])),
    ]);
    setClipRootPath(clip, { times: Float32Array.from(times), xz: new Float32Array(FRAMES * 2) });
    const pre = sampleClip(rig, clip, ['mixamorigRightFoot']);
    relockRootPaths([clip], rig, 1);
    const post = sampleClip(rig, clip, ['mixamorigRightFoot']);
    const y = (f) => post.mixamorigRightFoot[f].p[1];
    const rolled = [13, 14, 15, 16].map(y);
    check('[L6] rolled frames 13 … 16: the ankle stays at 9 (±1e-4)',
      rolled.every((h, i) => Math.abs(h - 9) <= 1e-4 && Math.abs(h - pre.mixamorigRightFoot[13 + i].p[1]) <= 1e-4),
      fmt(rolled));
    check('[L6] frame 11 (sole-down, fade 0.25): lowered to 8.1875 (±1e-4)', Math.abs(y(11) - 8.1875) <= 1e-4,
      y(11).toFixed(5));
    check('[L6] frame 5: stays at 8 (±1e-4)', Math.abs(y(5) - 8) <= 1e-4, y(5).toFixed(5));
  }

  console.log(`\n${passed + failed} checks, ${failed} failures`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
