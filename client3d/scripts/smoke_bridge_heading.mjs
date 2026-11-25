#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/bridge_heading.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_bridge_heading.mjs
 *         (bundles the client modules itself; needs no clip files)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
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

async function main() {
  const THREE = await import('three');
  const c = await loadClient();

  const vectors = await runBridgeVectors('bridge_heading');
  passed += vectors.passed; failed += vectors.failed;

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
