/**
 * Smoke run for `client3d/src/scene/cameraFraming.ts` — what the 3D client's
 * camera puts in the picture, and in particular what the EMBODIED camera
 * frames when the player zooms in.
 *
 * Usage:  node scripts/smoke_embodied_camera.mjs
 *         (transforms the module with esbuild — a Vite dependency, already
 *          installed; no bundler, no GL context, no server)
 *
 * Every number below is derived BY HAND from the rules, never recorded from
 * the current output.
 *
 * ---------------------------------------------------------------------------
 * THE RULES
 * ---------------------------------------------------------------------------
 * The camera is an orbit camera with a 45° VERTICAL field of view, so the
 * picture reaches 22.5° above and below its axis — call that the HALF-FRAME.
 * It sits at distance d from its aim point, looking down at
 *
 *     pitch(d, near) = near + (62 − near) · sqrt((d − 0.8) / 149.2)
 *
 * (`basePitchDeg`; 0.8 = MIN_DIST, 150 = MAX_DIST, 62 = FAR_PITCH_DEG, and the
 * divisor is 150 − 0.8 = 149.2). That places it at
 *
 *     camY  = aimY + d · sin(pitch)          horiz = d · cos(pitch)
 *
 * and a point at height y on the figure's vertical axis appears
 *
 *     off(y) = atan2(camY − y, horiz) − pitch     degrees BELOW the centre
 *
 * of the picture (negative = above it). The horizon — every point infinitely
 * far away at eye level — sits at −pitch, i.e. exactly `pitch` above centre.
 *
 * ---------------------------------------------------------------------------
 * [1] THE AIM POINT (the bug of 2026-09-02)
 * ---------------------------------------------------------------------------
 * The embodied camera followed the figure's ROOT, and a root is at the feet:
 * aimY = 0. The feet were therefore the centre of the picture at EVERY
 * distance, and the pitch curve pushed the camera down towards them as it came
 * closer. With the old overview near end (18°) that gives, for a 1.70 m figure:
 *
 *     d = 7 m:  pitch = 18 + 44·sqrt(6.2/149.2) = 18 + 44·0.2038503 = 26.97°
 *               camY = 7·sin 26.97° = 3.1746 m
 *               head at off(1.70) = atan2(1.4746, 6.2394) − 26.97 = −13.67°
 *               → the whole figure crammed into the upper half of the frame
 *     d = 3 m:  pitch = 18 + 44·sqrt(2.2/149.2) = 23.3429°
 *               camY = 1.1887 m, head at −33.86° — BEYOND the 22.5° half-frame,
 *               so below ~3 m the head is out of the picture and the zoom runs
 *               into the feet. That is what the bug report described.
 *
 * The aim point is now the EYES: `eyeHeight(h) = 0.94 · h`, so
 *     eyeHeight(1.70) = 1.598 m   and   eyeHeight(2.00) = 1.880 m.
 *
 * ---------------------------------------------------------------------------
 * [2] THE EMBODIED NEAR END
 * ---------------------------------------------------------------------------
 * Two numbers go with it: the camera may not come closer than
 * EMBODY_MIN_DIST = 2 m (0.8 m from the eyes is inside the head), and the near
 * end of the pitch curve flattens to EMBODY_NEAR_PITCH_DEG = 8°, so
 *
 *     pitch(2, 8)  = 8 + 54·sqrt(1.2/149.2) = 8 + 54·0.0896822 = 12.8428°
 *     pitch(7, 8)  = 8 + 54·0.2038503                          = 19.0079°
 *     pitch(34, 8) = 8 + 54·sqrt(33.2/149.2) = 8 + 54·0.4717...= 33.4729°
 *
 * and, with aimY = 1.598 (a 1.70 m figure), the picture at the zoom floor is
 *
 *     camY = 1.598 + 2·sin 12.8428° = 1.598 + 0.4446 = 2.0426 m
 *     head   off(1.70)  = −2.88°   (just above the centre)
 *     feet   off(0)     = +33.49°  (outside the half-frame: a close
 *                                   over-the-shoulder shot shows no feet)
 *     horizon           = −12.84°  (INSIDE the 22.5° half-frame — the world
 *                                   ahead of the avatar is in shot, which is
 *                                   the whole point of the change)
 *
 * At the entry distance of 7 m the whole figure is back in the frame:
 *     camY = 1.598 + 7·sin 19.0079° = 3.8779 m
 *     feet +11.36°, head −0.79°, horizon −19.01° — all inside 22.5°.
 *
 * ---------------------------------------------------------------------------
 * [3] THE OVERVIEW IS UNTOUCHED
 * ---------------------------------------------------------------------------
 * `basePitchDeg` without a near end is the overview curve, and it must still
 * answer exactly what it always did: 18° at MIN_DIST (zoomK = 0), 62° at
 * MAX_DIST (zoomK = 1), 26.9694° at 7 m.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = new URL('..', import.meta.url);
const SRC = join(fileURLToPath(ROOT), 'client3d/src/scene/cameraFraming.ts');

/** esbuild comes with Vite and npm does NOT hoist it to the root of the
 *  workspace, so a bare `import('esbuild')` from `scripts/` finds nothing.
 *  Ask the workspaces that own it, in the order that puts the client — whose
 *  file this check transforms — first. */
function esbuildEntry() {
  for (const ws of ['client3d', 'frontend']) {
    try {
      return createRequire(new URL(`${ws}/package.json`, ROOT)).resolve('esbuild');
    } catch { /* that workspace has no node_modules yet */ }
  }
  throw new Error('esbuild not found — run `npm install` in the repo root');
}

/** The module, transformed and imported — it has no imports of its own, so a
 *  single-file transform is enough (the `smoke_height_math.mjs` recipe). */
async function loadFraming() {
  const esbuild = await import(pathToFileURL(esbuildEntry()).href);
  const dir = await mkdtemp(join(tmpdir(), 'camframing-smoke-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'cameraFraming.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-4) {
  const ok = typeof expected === 'number'
    ? typeof actual === 'number' && Math.abs(actual - expected) <= eps
    : actual === expected;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}

/** The picture, as the rules in the header state it: where the camera ends up
 *  and how far above/below the centre the interesting heights land. */
function shot(F, dist, nearPitchDeg, figureHeightM) {
  const pitch = F.basePitchDeg(dist, nearPitchDeg);
  const rad = (pitch * Math.PI) / 180;
  const aimY = F.eyeHeight(figureHeightM);
  const camY = aimY + dist * Math.sin(rad);
  const horiz = dist * Math.cos(rad);
  const off = (y) => (Math.atan2(camY - y, horiz) * 180) / Math.PI - pitch;
  return { pitch, camY, feet: off(0), head: off(figureHeightM), horizon: -pitch };
}

const F = await loadFraming();
const HALF_FRAME = 22.5;

console.log('[1] the aim point');
check('eyeHeight(1.70)', F.eyeHeight(1.70), 1.598);
check('eyeHeight(2.00)', F.eyeHeight(2.00), 1.880);
// The old framing, reconstructed from the same formula: aim at the feet with
// the overview near end. Both numbers are the bug, and they are checked so a
// future change to the curve cannot quietly bring them back.
for (const [dist, pitch, camY, head] of [[7, 26.9694, 3.1746, -13.67],
                                         [3, 23.3429, 1.1887, -33.86]]) {
  const p = F.basePitchDeg(dist, 18);
  const cy = dist * Math.sin((p * Math.PI) / 180);
  const hd = (Math.atan2(cy - 1.70, dist * Math.cos((p * Math.PI) / 180)) * 180) / Math.PI - p;
  check(`old aim-at-feet, ${dist} m: pitch`, p, pitch, 1e-3);
  check(`old aim-at-feet, ${dist} m: camY`, cy, camY, 1e-3);
  check(`old aim-at-feet, ${dist} m: head off centre`, hd, head, 5e-3);
}
check('old aim-at-feet, 3 m: head outside the half-frame',
  Math.abs(-33.86) > HALF_FRAME, true);

console.log('[2] the embodied near end');
check('EMBODY_MIN_DIST', F.EMBODY_MIN_DIST, 2.0);
check('EMBODY_NEAR_PITCH_DEG', F.EMBODY_NEAR_PITCH_DEG, 8);
check('pitch(2, 8)', F.basePitchDeg(2, F.EMBODY_NEAR_PITCH_DEG), 12.8428, 1e-3);
check('pitch(7, 8)', F.basePitchDeg(7, F.EMBODY_NEAR_PITCH_DEG), 19.0079, 1e-3);
check('pitch(34, 8)', F.basePitchDeg(34, F.EMBODY_NEAR_PITCH_DEG), 33.4729, 1e-3);

const floor = shot(F, F.EMBODY_MIN_DIST, F.EMBODY_NEAR_PITCH_DEG, 1.70);
check('zoom floor: camY', floor.camY, 2.0426, 1e-3);
check('zoom floor: head off centre', floor.head, -2.88, 5e-3);
check('zoom floor: feet off centre', floor.feet, 33.49, 5e-3);
check('zoom floor: horizon off centre', floor.horizon, -12.8428, 1e-3);
check('zoom floor: head inside the half-frame',
  Math.abs(floor.head) < HALF_FRAME, true);
check('zoom floor: horizon inside the half-frame',
  Math.abs(floor.horizon) < HALF_FRAME, true);
// The camera must not stand in the head: 2 m at 12.84° leaves 1.95 m of
// horizontal air behind a figure whose crown is 1.70 m up, and 0.34 m above it.
check('zoom floor: horizontal distance behind the figure',
  F.EMBODY_MIN_DIST * Math.cos((floor.pitch * Math.PI) / 180), 1.9500, 1e-3);
check('zoom floor: camera above the crown', floor.camY - 1.70, 0.3426, 1e-3);

const entry = shot(F, 7, F.EMBODY_NEAR_PITCH_DEG, 1.70);
check('entry 7 m: camY', entry.camY, 3.8779, 1e-3);
check('entry 7 m: feet off centre', entry.feet, 11.36, 5e-3);
check('entry 7 m: head off centre', entry.head, -0.79, 5e-3);
check('entry 7 m: whole figure inside the half-frame',
  Math.abs(entry.feet) < HALF_FRAME && Math.abs(entry.head) < HALF_FRAME, true);
check('entry 7 m: horizon inside the half-frame',
  Math.abs(entry.horizon) < HALF_FRAME, true);

console.log('[3] the overview is untouched');
check('MIN_DIST', F.MIN_DIST, 0.8);
check('MAX_DIST', F.MAX_DIST, 150);
check('OVERVIEW_NEAR_PITCH_DEG', F.OVERVIEW_NEAR_PITCH_DEG, 18);
check('pitch at MIN_DIST', F.basePitchDeg(F.MIN_DIST), 18);
check('pitch at MAX_DIST', F.basePitchDeg(F.MAX_DIST), 62);
check('pitch beyond MAX_DIST is clamped', F.basePitchDeg(400), 62);
check('pitch below MIN_DIST is clamped', F.basePitchDeg(0.1), 18);
check('pitch(7) overview', F.basePitchDeg(7), 26.9694, 1e-3);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
