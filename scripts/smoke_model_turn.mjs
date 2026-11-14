#!/usr/bin/env node
/**
 * Smoke: the model viewers' one mouse control, pure part (Ruling T-U4) — `frontend/src/lib/modelTurn.ts`.
 *
 * Usage:  node scripts/smoke_model_turn.mjs   (no server, no world; esbuild bundles the module)
 *
 * THE CASES, DERIVED BY HAND (0.5° per pixel, tilt limit 90°, reset 240°/s)
 * ------------------------------------------------------------------------
 * [1] dragPose from upright: (180, 0) px → yaw 90° = 1.5707963, pitch 0; (0, 100) px → pitch 50° = 0.8726646
 *     (dragging down tilts forward); (0, 400) px → 200°, clamped to 90° = 1.5707963; from pitch 1 rad, (0, −600) px
 *     → 1 − 300° = 1 − 5.2359878 rad, clamped to −90° = −1.5707963; the yaw is not clamped: (−720, 0) → −2π.
 * [2] wrapAngle: 3π/2 → −π/2 = −1.5707963; −π → π (the interval is (−π, π]); π → π; 0.5 → 0.5.
 * [3] resetPoseStep: (0.3, 0.4) rad, dt 0.25 s → the way is 0.5 rad, the step 60° = 1.0471976 rad ≥ 0.5 → (0, 0).
 *     (0.6, 0.8), dt 1/60 → the way 1.0, the step 4° = 0.0698132, both scaled by 1 − 0.06981317 = 0.93018683 →
 *     (0.5581121, 0.7441495): both axes arrive together. (3π/2, 0), dt 0.1 → the yaw the short way, −π/2; the step
 *     24° = 0.4188790 → yaw −π/2 · (1 − 0.4188790 / 1.5707963) = −π/2 · 0.7333333 = −1.1519173.
 * [4] poseMatrix (column-major, T(pivot + offset)·Ry·Rx·T(−pivot)), applied to points:
 *     pitch 90° about pivot (0, 1, 0): (0, 2, 0) — 1 m above the pivot — → Rx(90°)·(0, 1, 0) = (0, 0, 1) → (0, 1, 1)
 *     (the top goes forward, towards +z); the pivot stays at (0, 1, 0).
 *     yaw 90° about (0, 1, 0): the front point (0, 1, 1) → Ry(90°)·(0, 0, 1) = (1, 0, 0) → (1, 1, 0).
 *     yaw 90° AND pitch 90°: (0, 2, 0) → Rx first: (0, 0, 1), then Ry: (1, 0, 0) → (1, 1, 0).
 *     upright with offset (0.1, 0, 0): (0, 0, 0) → (0.1, 0, 0).
 * [5] isUpright: (2π, 0) → true (a whole turn); (0, 0.001) → false.
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'frontend/node_modules/esbuild'),
                      join(ROOT, 'client3d/node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'smoke-model-turn-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({ entryPoints: [src], outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const failures = [];
function check(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) failures.push(`${label}: got ${g}, want ${w}`);
  else console.log(`ok  ${label}`);
}
const r7 = (v) => Math.round(v * 1e7) / 1e7 + 0;   // + 0: no -0 in the comparison
const pose = (p) => [r7(p.yaw), r7(p.pitch)];
const apply = (m, p) => [0, 1, 2].map(i => r7(m[i] * p[0] + m[4 + i] * p[1] + m[8 + i] * p[2] + m[12 + i]));

const m = await loadBundled(join(ROOT, 'frontend/src/lib/modelTurn.ts'));
const UP = m.UPRIGHT;
const Q = Math.PI / 2;

check('[1] constants', [m.DRAG_TURN_DEG_PER_PX, m.PITCH_LIMIT_DEG, m.RESET_DEG_PER_S], [0.5, 90, 240]);
check('[1] drag 180 px right', pose(m.dragPose(UP, 180, 0)), [1.5707963, 0]);
check('[1] drag 100 px down tilts forward', pose(m.dragPose(UP, 0, 100)), [0, 0.8726646]);
check('[1] drag 400 px down: clamped to 90°', pose(m.dragPose(UP, 0, 400)), [0, 1.5707963]);
check('[1] drag 600 px up from 1 rad: clamped to −90°', pose(m.dragPose({ yaw: 0, pitch: 1 }, 0, -600)), [0, -1.5707963]);
check('[1] the yaw is not clamped', pose(m.dragPose(UP, -720, 0)), [r7(-2 * Math.PI), 0]);

check('[2] wrapAngle', [m.wrapAngle(3 * Q), m.wrapAngle(-Math.PI), m.wrapAngle(Math.PI), m.wrapAngle(0.5)].map(r7),
  [-1.5707963, 3.1415927, 3.1415927, 0.5]);

check('[3] within one step: upright', pose(m.resetPoseStep({ yaw: 0.3, pitch: 0.4 }, 0.25)), [0, 0]);
check('[3] both axes together', pose(m.resetPoseStep({ yaw: 0.6, pitch: 0.8 }, 1 / 60)), [0.5581121, 0.7441495]);
check('[3] the yaw the short way', pose(m.resetPoseStep({ yaw: 3 * Q, pitch: 0 }, 0.1)), [-1.1519173, 0]);

check('[4] pitch 90°: the top goes forward', apply(m.poseMatrix({ yaw: 0, pitch: Q }, [0, 1, 0]), [0, 2, 0]), [0, 1, 1]);
check('[4] pitch 90°: the pivot stays', apply(m.poseMatrix({ yaw: 0, pitch: Q }, [0, 1, 0]), [0, 1, 0]), [0, 1, 0]);
check('[4] yaw 90°: the front turns to +x', apply(m.poseMatrix({ yaw: Q, pitch: 0 }, [0, 1, 0]), [0, 1, 1]), [1, 1, 0]);
check('[4] yaw and pitch 90°', apply(m.poseMatrix({ yaw: Q, pitch: Q }, [0, 1, 0]), [0, 2, 0]), [1, 1, 0]);
check('[4] offset', apply(m.poseMatrix(UP, [0, 1, 0], [0.1, 0, 0]), [0, 0, 0]), [0.1, 0, 0]);

check('[5] isUpright', [m.isUpright({ yaw: 2 * Math.PI, pitch: 0 }), m.isUpright({ yaw: 0, pitch: 0.001 })], [true, false]);

if (failures.length) {
  for (const f of failures) console.error(`FAIL ${f}`);
  process.exit(1);
}
console.log('ALL OK');
