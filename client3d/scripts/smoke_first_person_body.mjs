#!/usr/bin/env node
/**
 * Usage: node client3d/scripts/smoke_first_person_body.mjs
 *
 * First person WITH the own body (`cameraFraming.restEyePoint`,
 * `bodyYawForView`, `viewHeading`; `Figure.setFirstPerson`/`firstPersonEye`).
 * Every expected number is derived by hand below from the constants of
 * `cameraFraming.ts` (EYE_HEAD_FRACTION 0.45, EYE_FORWARD_FRACTION 0.055,
 * BODY_TURN_DEG 60) — not recorded from a run.
 *
 * [1] restEyePoint: head joint (0, 1.52, 0.02), crown end (0, 1.72, 0.03),
 *     1.70 m → y = 1.52 + 0.20·0.45 = 1.61, z = 0.02 + 1.70·0.055 = 0.1135.
 *     Without a crown bone the standing eye 1.70·0.94 = 1.598.
 * [2] viewHeading: orbit yaw 0 puts the camera on +Z looking at −Z → facing
 *     yaw ±π; orbit yaw π/2 puts it on +X looking at −X → −π/2.
 * [3] bodyYawForView: 57.3° (1.0 rad) off stays, 63.0° (1.1 rad) turns to
 *     the view; body 3.0 vs view −3.0 is 0.283 rad (16.2°) across the seam,
 *     not 6 rad, and stays; an unwrapped body 4π + 0 vs view 1.1 turns.
 * [4] A synthetic rig (a 1.70 m box, hips → head → crown end, no skin; one
 *     identity `idle` clip so the figure is not the procedural-gait static):
 *     the head joint stands at (0, 1.52, 0.02), the crown end at
 *     (0, 1.72, 0.03), the instance scale is 1 (box height 1.70).
 *     - rest lens = [1] = (0, 1.61, 0.1135);
 *     - root at (5, 0, −3) facing +X (yaw π/2, Ry maps (x, z) → (z, −x)):
 *       (0, 1.61, 0.1135) → (0.1135, 1.61, 0) + root = (5.1135, 1.61, −3);
 *     - back at yaw 0, head pitched +90° about X (+Y → +Z, +Z → −Y): the
 *       offset (0, 0.09, 0.0935) becomes (0, −0.0935, 0.09), so the lens is
 *       head + it = (5, 1.4265, −2.89) — the lens follows the head's pose;
 *     - first person on + update: head scale 1e-3, the crown end collapses
 *       onto the head joint (0.20 m · 1e-3 = 0.2 mm), the lens is unchanged;
 *     - first person off: head scale back to 1 at once, without an update.
 *     Tolerance 1e-6 m: the box geometry is Float32, its 0.85 lands as
 *     0.8499999762, which shifts every point by 2.4e-8 m.
 *     A rig without a head bone reports `hasHead` false and no lens.
 */
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { embodyDispatch } from './embodyVectorDispatch.mjs';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src');
    const entry = [
      `export { bodyYawForView, restEyePoint, viewHeading } from '${src}/scene/cameraFraming';`,
      `export { Figure } from '${src}/scene/figures';`,
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

const near = (actual, expected, eps, what) =>
  assert.ok(Number.isFinite(actual) && Math.abs(actual - expected) <= eps,
    `${what}: ${actual} (expected ${expected} ±${eps})`);
const nearV = (v, [x, y, z], eps, what) => {
  near(v.x, x, eps, `${what} x`); near(v.y, y, eps, `${what} y`); near(v.z, z, eps, `${what} z`);
};

const THREE = await import('three');
const { bodyYawForView, restEyePoint, viewHeading, Figure } = await loadClient();

const framingVectors = loadVectors('camera');
const result = runVectors({ ...framingVectors, cases: framingVectors.cases.filter(c =>
  ['restEyePoint', 'eyeHeight', 'viewHeading', 'bodyYawForView'].includes(c.fn)) }, embodyDispatch);
assert.equal(result.failed, 0, 'shared first-person body arithmetic');

// [4]
function rig(withHead) {
  const template = new THREE.Group();
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.4, 1.70, 0.3), new THREE.MeshBasicMaterial());
  box.position.y = 0.85;
  template.add(box);
  const hips = new THREE.Bone();
  hips.name = 'Hips';
  hips.position.set(0, 0.95, 0);
  template.add(hips);
  if (withHead) {
    const head = new THREE.Bone();
    head.name = 'mixamorig:Head';
    head.position.set(0, 0.57, 0.02);
    hips.add(head);
    const crown = new THREE.Bone();
    crown.name = 'mixamorig:HeadTop_End';
    crown.position.set(0, 0.20, 0.01);
    head.add(crown);
  }
  template.updateMatrixWorld(true);
  const idle = new THREE.AnimationClip('idle', 1, [
    new THREE.QuaternionKeyframeTrack('Hips.quaternion', [0, 1], [0, 0, 0, 1, 0, 0, 0, 1]),
  ]);
  const figure = new Figure({
    name: 'demo', template, clips: [idle], scale: 1, height: 1.70, assignOnly: true,
    noClips: false, tier: 'full', libraryFits: true,
  });
  const owner = new THREE.Group();
  owner.add(figure.root);
  const bone = (n) => {
    let found = null;
    figure.root.traverse((o) => { if (o.isBone && o.name === n && !found) found = o; });
    return found;
  };
  return { figure, head: bone('mixamorig:Head'), crown: bone('mixamorig:HeadTop_End') };
}

const { figure, head, crown } = rig(true);
assert.ok(figure.hasHead, '[4] head bone found');
nearV(head.getWorldPosition(new THREE.Vector3()), [0, 1.52, 0.02], 1e-6, '[4] head joint');
nearV(figure.firstPersonEye(new THREE.Vector3()), [0, 1.61, 0.1135], 1e-6, '[4] rest lens');

figure.root.position.set(5, 0, -3);
figure.faceTowards(new THREE.Vector3(1, 0, 0), true);
figure.update(1 / 60);
nearV(figure.firstPersonEye(new THREE.Vector3()), [5.1135, 1.61, -3], 1e-6, '[4] turned lens');

figure.faceTowards(new THREE.Vector3(0, 0, 1), true);
head.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2);
figure.update(1 / 60);
nearV(figure.firstPersonEye(new THREE.Vector3()), [5, 1.4265, -2.89], 1e-6, '[4] pitched head lens');
head.quaternion.identity();

figure.setFirstPerson(true);
figure.update(1 / 60);
near(head.scale.x, 1e-3, 1e-15, '[4] head shrunk');
const hw = head.getWorldPosition(new THREE.Vector3());
assert.ok(crown.getWorldPosition(new THREE.Vector3()).distanceTo(hw) < 2.1e-4,
  '[4] crown collapses onto the head joint');
nearV(figure.firstPersonEye(new THREE.Vector3()), [5, 1.61, -2.8865], 1e-6, '[4] lens ignores the shrink');
figure.update(1 / 60);
near(head.scale.x, 1e-3, 1e-15, '[4] still shrunk on the next frame');

figure.setFirstPerson(false);
near(head.scale.x, 1, 1e-15, '[4] head back at once');

const headless = rig(false).figure;
assert.equal(headless.hasHead, false, '[4] no head bone');
assert.equal(headless.firstPersonEye(new THREE.Vector3()), null, '[4] no lens without a head');

console.log('PASS: first-person body — rest eye, view heading, body turn, head shrink and lens');
