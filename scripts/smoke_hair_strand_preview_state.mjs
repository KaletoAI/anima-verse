#!/usr/bin/env node
/**
 * Smoke: the Hairstyles preview's per-strand motion, pure part (strand-hair plan 2026-11-13 Task 10, spec § 6.2.5,
 * coordinator ruling H-R2) — `frontend/src/tabs/characters/hairstylesModel.ts`.
 *
 * Usage:  node scripts/smoke_hair_strand_preview_state.mjs   (no server, no world; esbuild bundles the module)
 *
 * THE CASES, DERIVED BY HAND
 * --------------------------
 * [1] strandPreviewState({preview_strands_url: '/x'}, true) = 'swings'; (…, false) = 'swing_off';
 *     ({preview_strands_url: null}, true) = 'no_preview'; a missing url = 'no_preview' too.
 * [2] The Motion group's hint texts, verbatim from the brief:
 *       swings    "Drag the figure above to turn and tilt it — every strand swings."
 *       swing_off "Swing is off — the hair stays still."
 *       no_preview "No fitted hair yet — nothing to preview."
 * [3] Drag turn (H-R2: dragging turns the figure about the vertical axis): 0.5° per pixel, so 180 px = 90° =
 *     π/2 = 1.5707963 rad and −360 px = −180° = −π; dragTurnDeg(180) = 90.
 * [4] The motions, ported from the spike viewer (`~/claude-out/haar-spike2/viewer/src/sim.js` `rootMotion`):
 *       sway t = 0.5 s, amp 1: yaw = 15°·sin(2π·0.5·0.5) = 15° = 0.2617994 rad, pitch = 5°·sin(π/2 + π/2) = 0;
 *         t = 1.0 s: yaw = 15°·sin(π) = 0, pitch = 5°·sin(π + π/2) = −5° = −0.0872665 rad.
 *       walk t = 0.5 s, amp 1: z = 0.25·sin(π/2) = 0.25 m, y = 0.015·(1 − cos(2π·0.5)) = 0.03 m;
 *         amp 0.5 halves both: z 0.125, y 0.015.
 *       turn (a 180° turn and back, cosine ease: 2.5 s out, 1 s held, 2.5 s back, 6 s in all):
 *         t 0 → 0; t 1.25 → π/2·(1 − cos(π/2)) = π/2; t 2.5 and 3.0 → π; t 4.75 → π/2·(1 + cos(π/2)) = π/2;
 *         t 6 and 7 → 0. Its peak angular acceleration (π/2)·(π/2.5)² = 1.5707963·1.5791367 = 2.4805021 rad/s² stays under the strands'
 *         felt limit `STRAND_ROOT_LIMITS.angAccel` = 15°·π² = 0.2617994·9.8696044 = 2.5838564 rad/s², so the
 *         whole turn is felt (none of it is carried rigidly).
 *       Every motion at amp 0 is the rest pose (yaw 0, pitch 0, offset 0) — what Stop eases back to.
 * [5] The amplitude ramp (the spike's `amp += (target − amp)·min(1, dt/0.5)`): previewMotionAmp(0, 1, 0.25) = 0.5,
 *     (0.5, 1, 0.25) = 0.75, (1, 0, 1) = 0 (a long frame lands on the target, never beyond).
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
  const dir = await mkdtemp(join(tmpdir(), 'smoke-strand-preview-'));
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
const pose7 = (p) => [r7(p.yaw), r7(p.pitch), p.offset.map(r7)];

const m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/hairstylesModel.ts'));
const sr = await loadBundled(join(ROOT, 'packages/scene-render/src/hairSimMath.ts'));

// [1]
check('[1] states', [
  m.strandPreviewState({ preview_strands_url: '/x' }, true),
  m.strandPreviewState({ preview_strands_url: '/x' }, false),
  m.strandPreviewState({ preview_strands_url: null }, true),
  m.strandPreviewState({}, true),
], ['swings', 'swing_off', 'no_preview', 'no_preview']);

// [2]
check('[2] hints', m.STRAND_PREVIEW_HINTS, {
  swings: 'Drag the figure above to turn and tilt it — every strand swings.',
  swing_off: 'Swing is off — the hair stays still.',
  no_preview: 'No fitted hair yet — nothing to preview.',
});

// [3]
check('[3] drag turn', [m.DRAG_TURN_DEG_PER_PX, r7(m.dragTurnRad(180)), r7(m.dragTurnRad(-360)), m.dragTurnDeg(180)],
  [0.5, 1.5707963, -3.1415927, 90]);

// [4]
check('[4] sway 0.5 s', pose7(m.previewRootPose('sway', 0.5, 1)), [0.2617994, 0, [0, 0, 0]]);
check('[4] sway 1.0 s', pose7(m.previewRootPose('sway', 1.0, 1)), [0, -0.0872665, [0, 0, 0]]);
check('[4] walk 0.5 s', pose7(m.previewRootPose('walk', 0.5, 1)), [0, 0, [0, 0.03, 0.25]]);
check('[4] walk 0.5 s, amp 0.5', pose7(m.previewRootPose('walk', 0.5, 0.5)), [0, 0, [0, 0.015, 0.125]]);
check('[4] turn', [0, 1.25, 2.5, 3.0, 4.75, 6, 7].map((t) => r7(m.previewRootPose('turn', t, 1).yaw)),
  [0, 1.5707963, 3.1415927, 3.1415927, 1.5707963, 0, 0]);
check('[4] turn length', [m.TURN_S], [6]);
const turnPeak = (Math.PI / 2) * (Math.PI / 2.5) ** 2;
check('[4] turn felt whole', [r7(turnPeak), r7(sr.STRAND_ROOT_LIMITS.angAccel), turnPeak <= sr.STRAND_ROOT_LIMITS.angAccel],
  [2.4805021, 2.5838564, true]);
check('[4] amp 0 = rest', ['sway', 'walk', 'turn'].map((k) => pose7(m.previewRootPose(k, 0.7, 0))),
  [[0, 0, [0, 0, 0]], [0, 0, [0, 0, 0]], [0, 0, [0, 0, 0]]]);

// [5]
check('[5] ramp', [m.previewMotionAmp(0, 1, 0.25), m.previewMotionAmp(0.5, 1, 0.25), m.previewMotionAmp(1, 0, 1)],
  [0.5, 0.75, 0]);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
