#!/usr/bin/env node
/**
 * Smoke check for the DOOR SWING maths of the 3D client (v5 door props,
 * user decision 2026-08-27) — `client3d/src/game/doorSwing.ts`.
 *
 * Usage:  node client3d/scripts/smoke_door_swing.mjs
 *
 * Like every other check here, each expected number below is derived BY HAND
 * from the contract (§ B5a: numbers, never a screenshot, and never a value
 * recorded from the current output).
 *
 * WHAT THE MODULE IS. A door prop is a `models[]` entry with `measure: "fit"`
 * whose placed group has its ORIGIN ON THE HINGE (spec addendum "Tür-Props +
 * Slots (v5)"), so "the door opens" is a rotation of that group about its own
 * y axis. WHEN it opens and HOW FAR is view state and lives per app; these two
 * pure functions are that rule, and `main.ts` does nothing but feed them the
 * distance and hang the result on `group.rotation.y`.
 *
 * THE CONSTANTS (user decision 2026-08-27):
 *   DOOR_OPEN_RANGE = 2.0 m   — "the avatar stands in front of it"
 *   DOOR_OPEN_DEG   = 85°     — how far a door swings open
 *   DOOR_SWING_RATE = 3.0 rad/s — how fast it gets there
 *
 * --- doorTargetAngle(distM, enterable, swing) -----------------------------
 * The open angle in RADIANS, signed by `swing` (+1 left hinge, −1 right):
 *
 *   open = 85 · π / 180 = 1.4835298641951802 rad
 *
 *   (1.9, true,  +1) ->  +1.4835298641951802   inside the range, open
 *   (2.1, true,  +1) ->   0                    outside it, shut
 *   (2.0, true,  +1) ->  +1.4835298641951802   the range is inclusive
 *   (1.9, false, +1) ->   0                    LOCKED stays shut, however
 *                                              close one stands (§ 3
 *                                              decision 2: a ban is visible)
 *   (1.9, true,  -1) ->  -1.4835298641951802   right hinge, other way round
 *   (2.1, false, -1) ->   0                    both reasons at once
 *
 * A non-finite distance (no avatar in the scene) is not "near": `NaN <= 2.0`
 * and `Infinity <= 2.0` are both false, so the door shuts.
 *
 * --- doorDistance(doorLevel, avatarLevel, distM) --------------------------
 * DOORS STACK. A front door and the balcony door above it share their (x, z)
 * to the millimetre, so a plain 2D distance opens both at once. The gate is
 * the storey the AVATAR is on (the storey of its room), never the displayed
 * one: `levelFilter` is the in-world storey BUTTON, and "avatar on storey 0,
 * view on storey 1" is an everyday state — gating on the camera would open
 * the door directly overhead with nobody in front of it.
 *
 *   (0, 0, 1.9) -> 1.9        same storey, the distance stands
 *   (1, 0, 0.1) -> Infinity   the door overhead, however close in plan
 *   (0, 1, 0.1) -> Infinity   ...and the one under one's feet
 *   (-1,-1, 0.4) -> 0.4       a basement door seen from the basement
 *
 * Fed onward, `Infinity` is exactly "nobody is in front of it", so
 *   doorTargetAngle(doorDistance(1, 0, 0.1), true, 1) = 0
 * while the same door on the avatar's own storey stands open. `Infinity`
 * rather than skipping the door: one left open on the floor one has just
 * ridden away from must ease SHUT, not freeze.
 *
 * --- easeAngle(current, target, dt, rate) ---------------------------------
 * One frame of the swing: at most `rate · dt` radians towards the target, and
 * never past it. At 60 fps and 3.0 rad/s one step is
 *
 *   3.0 / 60 = 0.05 rad
 *
 *   (0,     1.4835298641951802, 1/60, 3.0) -> 0.05
 *        the difference is 1.4835 > 0.05, so a full step: 0 + 0.05
 *   (1.4,   1.4835298641951802, 1/60, 3.0) -> 1.45
 *        difference 0.0835298641951802 > 0.05, another full step
 *   (1.45,  1.4835298641951802, 1/60, 3.0) -> 1.4835298641951802
 *        difference 0.0335298641951802 <= 0.05, so it CLAMPS at the target —
 *        no overshoot, and the door does not jitter around its end stop
 *   (0,    -1.4835298641951802, 1/60, 3.0) -> -0.05      symmetric
 *   (-1.45,-1.4835298641951802, 1/60, 3.0) -> -1.4835298641951802
 *   (1.2,   0,                  1/60, 3.0) -> 1.15       shutting again
 *   (x, x, …) -> x                                        already there
 *   (0.3,   1.4835298641951802, 0,    3.0) -> 0.3        a frame of no time
 *                                                        moves nothing
 *
 *   (0,    1, 1/60) -> 0.05     the rate defaults to DOOR_SWING_RATE 3.0
 *
 * --- the whole swing, frame by frame (60 fps) -----------------------------
 *   1.4835298641951802 / 0.05 = 29.67 → 30 frames from shut to fully open
 *   (standing 1.0 m away), and 30 frames back to shut from fully open when
 *   the avatar stands 3.0 m away.
 *
 * VECTORS: the cases above are in shared/test-vectors/door_swing.json (shared
 * with the native client's C# tests). JSON wrappers: a `null` distance
 * argument is Infinity and a returned Infinity is `null`;
 * `doorConstants()` = {range, openDeg, rate}; `doorSwingFrames(from, distM)`
 * counts 60-fps frames of easeAngle towards doorTargetAngle(distM, true, +1)
 * until the angle stands exactly on it (at most 100). NaN has no JSON
 * spelling, so that case stays inline below, as does the stacked-door chain.
 *
 * The LEAF PIVOT (where the leaf node turns, ruling R13) is NOT here: it is
 * `leafPivot` of @anima/scene-render, checked by scripts/smoke_leaf_pivot.mjs.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// '../..' = the REPO root (this file lives in client3d/scripts/) — the same
// anchor smoke_walk_math.mjs uses.
const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'client3d/src/game/doorSwing.ts');

/**
 * `doorSwing.ts` is TypeScript and deliberately import-free (that is the point
 * of "pure" in its docstring), so a plain esbuild transpile is enough — no
 * bundler, and nothing to resolve. esbuild is a Vite dependency and lives in
 * `client3d/node_modules`, which a specifier from THIS directory finds.
 */
async function loadModule() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'doorswing-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'doorSwing.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-12) {
  // Exact first, so `Infinity` (a legitimate answer here — "nobody is in
  // front of this door") compares as itself: `Infinity − Infinity` is NaN and
  // every tolerance test on it is false.
  const ok = actual === expected
    || (typeof expected === 'number' && typeof actual === 'number'
        && Math.abs(actual - expected) <= eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

async function main() {
  const m = await loadModule();
  const { doorDistance, doorTargetAngle, easeAngle,
          DOOR_OPEN_RANGE, DOOR_OPEN_DEG, DOOR_SWING_RATE } = m;

  console.log('\n--- the constants (user decision 2026-08-27) ---');
  check('DOOR_OPEN_RANGE is 2.0 m', DOOR_OPEN_RANGE, 2.0);
  check('DOOR_OPEN_DEG is 85', DOOR_OPEN_DEG, 85);
  check('DOOR_SWING_RATE is 3.0 rad/s', DOOR_SWING_RATE, 3.0);

  // Written out here rather than imported, so the check has its OWN number.
  const OPEN = (85 * Math.PI) / 180;
  check('85° is 1.4835298641951802 rad', OPEN, 1.4835298641951802);

  console.log('\n--- the shared vectors (shared/test-vectors/door_swing.json) ---');
  const { loadVectors, runVectors } = await import('../../shared/test-vectors/vectors.mjs');
  const inf = (d) => (d === null ? Infinity : d);
  const fin = (v) => (v === Infinity ? null : v);
  const vectors = runVectors(loadVectors('door_swing'), {
    doorConstants: () => ({ range: DOOR_OPEN_RANGE, openDeg: DOOR_OPEN_DEG, rate: DOOR_SWING_RATE }),
    doorTargetAngle: (d, enterable, swing) => doorTargetAngle(inf(d), enterable, swing),
    doorDistance: (dl, al, d) => fin(doorDistance(dl, al, inf(d))),
    easeAngle,
    doorSwingFrames: (from, distM) => {
      const target = doorTargetAngle(distM, true, 1);
      let a = from;
      let frames = 0;
      while (a !== target && frames < 100) {
        a = easeAngle(a, target, 1 / 60, DOOR_SWING_RATE);
        frames += 1;
      }
      return frames;
    },
  });
  passed += vectors.passed;
  failed += vectors.failed;

  console.log('\n--- inline: NaN and the stacked-door chain ---');
  check('NaN is not "near" either -> shut',
    doorTargetAngle(NaN, true, 1), 0);
  check('RED: a stacked door 0.1 m away in plan stays SHUT',
    doorTargetAngle(doorDistance(1, 0, 0.1), true, 1), 0);
  check('...while the very same door on the avatar\'s own storey stands open',
    doorTargetAngle(doorDistance(1, 1, 0.1), true, 1), OPEN);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(`\nsmoke_door_swing: ${e?.message || e}`);
  process.exit(1);
});
