#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/camera_math.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_camera_math.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { embodyDispatch } from './embodyVectorDispatch.mjs';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d/src/scene/cameraMath.ts');
const FRAMING = join(ROOT, 'client3d/src/scene/cameraFraming.ts');

async function load() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      stdin: { contents: `export * from '${SRC}'; export { basePitchDeg } from '${FRAMING}';`,
        resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'camera.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'camera.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally { await rm(dir, { recursive: true, force: true }); }
}

const m = await load();
const { passed: vPassed, failed: vFailed } = runVectors(loadVectors('camera'), {
  ...embodyDispatch,
  fitDistance: m.fitDistance,
  worldCentreXZ: m.worldCentreXZ,
  basePitchDeg: m.basePitchDeg,
  clampPitchDeg: m.clampPitchDeg,
  wheelZoom: m.wheelZoom,
  zoomTowardCursor: m.zoomTowardCursor,
  damp: m.damp,
  flyAdvance: m.flyAdvance,
  flyEase: m.flyEase,
  orbitStep: m.orbitStep,
  cameraPose: m.cameraPose,
});

let passed = vPassed;
let failed = vFailed;
function check(label, ok) {
  if (ok) { passed += 1; console.log(`  ok   ${label}`); }
  else { failed += 1; console.log(`  FAIL ${label}`); }
}
const close = (a, b, eps = 1e-12) => Math.abs(a - b) <= eps;

console.log('\n(inline) constants, properties, source pins');
check('constants: wheel 0.0012, fly 1.6, frame dt 0.1, margin 1.15, empty 70',
  m.WHEEL_ZOOM_RATE === 0.0012 && m.FLY_RATE === 1.6 && m.MAX_FRAME_DT === 0.1
  && m.CAMERA_FIT_MARGIN === 1.15 && m.CAMERA_FIT_EMPTY === 70);
check('constants: orbit 0.005 rad/px, 0.25 deg/px, offset limits 35 / 85',
  m.ORBIT_YAW_PER_PX === 0.005 && m.ORBIT_PITCH_DEG_PER_PX === 0.25
  && m.PITCH_OFFSET_LIMIT_DEG === 35 && m.FIRST_PERSON_PITCH_OFFSET_LIMIT_DEG === 85);
// Two frames of dt/2 close the same share as one frame of dt:
// 1 − (1 − damp(dt/2))² = 1 − e^(−8·dt) = damp(dt) while dt <= 0.1.
check('damp is frame-rate independent (two half frames = one frame)',
  close(1 - (1 - m.damp(0.03)) ** 2, m.damp(0.06)));
const off = m.orbitOffset(0.7, 33);
check('orbitOffset is a unit vector', close(Math.hypot(off[0], off[1], off[2]), 1));
const out = [9, 9, 9];
check('orbitOffset writes into the given tuple and returns it', m.orbitOffset(0, 0, out) === out
  && close(out[2], 1));
const target = [10, 0, 10];
m.zoomTowardCursor(target, [20, 30], 100, 80);
check('zoomTowardCursor leaves the input target untouched',
  target[0] === 10 && target[1] === 0 && target[2] === 10);

const engine = await readFile(join(ROOT, 'client3d/src/scene/engine.ts'), 'utf8');
const main = await readFile(join(ROOT, 'client3d/src/main.ts'), 'utf8');
check('engine.ts imports the camera arithmetic from ./cameraMath',
  /from '\.\/cameraMath'/.test(engine));
for (const [what, re] of [
  ['the wheel factor', /Math\.exp\(e\.deltaY/],
  ['the exp easing', /Math\.exp\(-8 \* dt\)/],
  ['the fly rate', /dt \* 1\.6/],
  ['the orbit yaw step', /dx \* 0\.005/],
  ['the pitch-offset step', /dy \* 0\.25/],
]) check(`engine.ts holds no inline copy of ${what}`, !re.test(engine));
check('main.ts frames the world through cameraMath, no own fitDistance',
  /from '\.\/scene\/cameraMath'/.test(main) && !/function fitDistance/.test(main));

console.log(failed ? `\n${failed} FAILED, ${passed} ok` : `\nall ok (${passed})`);
process.exit(failed ? 1 : 0);
