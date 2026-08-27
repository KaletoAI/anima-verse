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
  const ok = typeof expected === 'number'
    ? typeof actual === 'number' && Math.abs(actual - expected) <= eps
    : actual === expected;
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
  const { doorTargetAngle, easeAngle,
          DOOR_OPEN_RANGE, DOOR_OPEN_DEG, DOOR_SWING_RATE } = m;

  console.log('\n--- the constants (user decision 2026-08-27) ---');
  check('DOOR_OPEN_RANGE is 2.0 m', DOOR_OPEN_RANGE, 2.0);
  check('DOOR_OPEN_DEG is 85', DOOR_OPEN_DEG, 85);
  check('DOOR_SWING_RATE is 3.0 rad/s', DOOR_SWING_RATE, 3.0);

  // Written out here rather than imported, so the check has its OWN number.
  const OPEN = (85 * Math.PI) / 180;
  check('85° is 1.4835298641951802 rad', OPEN, 1.4835298641951802);

  console.log('\n--- doorTargetAngle ---');
  check('1.9 m, enterable, left hinge (+1) -> +85°',
    doorTargetAngle(1.9, true, 1), OPEN);
  check('2.1 m -> shut, the range ends at 2.0',
    doorTargetAngle(2.1, true, 1), 0);
  check('exactly 2.0 m still counts as standing in front of it',
    doorTargetAngle(2.0, true, 1), OPEN);
  check('1.9 m but LOCKED -> shut',
    doorTargetAngle(1.9, false, 1), 0);
  check('1.9 m, enterable, right hinge (-1) -> -85°',
    doorTargetAngle(1.9, true, -1), -OPEN);
  check('2.1 m AND locked -> shut',
    doorTargetAngle(2.1, false, -1), 0);
  check('0 m (standing in the doorway) -> open',
    doorTargetAngle(0, true, 1), OPEN);
  check('no avatar in the scene (Infinity) -> shut',
    doorTargetAngle(Infinity, true, 1), 0);
  check('NaN is not "near" either -> shut',
    doorTargetAngle(NaN, true, 1), 0);

  console.log('\n--- easeAngle: one frame at 60 fps, 3.0 rad/s = 0.05 rad ---');
  check('shut -> opening: 0 + 0.05',
    easeAngle(0, OPEN, 1 / 60, DOOR_SWING_RATE), 0.05);
  check('1.4 -> 1.45 (difference 0.0835 > one step)',
    easeAngle(1.4, OPEN, 1 / 60, DOOR_SWING_RATE), 1.45);
  check('1.45 -> the target itself (difference 0.0335 <= one step, no overshoot)',
    easeAngle(1.45, OPEN, 1 / 60, DOOR_SWING_RATE), OPEN);
  check('negative direction, first step: -0.05',
    easeAngle(0, -OPEN, 1 / 60, DOOR_SWING_RATE), -0.05);
  check('negative direction clamps at the target too',
    easeAngle(-1.45, -OPEN, 1 / 60, DOOR_SWING_RATE), -OPEN);
  check('shutting again: 1.2 -> 1.15',
    easeAngle(1.2, 0, 1 / 60, DOOR_SWING_RATE), 1.15);
  check('already there: nothing moves',
    easeAngle(OPEN, OPEN, 1 / 60, DOOR_SWING_RATE), OPEN);
  check('a frame of no time moves nothing',
    easeAngle(0.3, OPEN, 0, DOOR_SWING_RATE), 0.3);

  console.log('\n--- the whole swing, frame by frame (60 fps) ---');
  // 1.4835298641951802 / 0.05 = 29.67 → 30 frames to stand fully open, and
  // then it stays there: half a second, hand-counted.
  let a = 0;
  let frames = 0;
  while (a !== OPEN && frames < 100) {
    a = easeAngle(a, doorTargetAngle(1.0, true, 1), 1 / 60, DOOR_SWING_RATE);
    frames += 1;
  }
  check('30 frames from shut to fully open', frames, 30);
  check('...and it stops there', easeAngle(a, OPEN, 1 / 60, DOOR_SWING_RATE), OPEN);
  // Walking away shuts it in the same 30 frames.
  let b = OPEN;
  let shutFrames = 0;
  while (b !== 0 && shutFrames < 100) {
    b = easeAngle(b, doorTargetAngle(3.0, true, 1), 1 / 60, DOOR_SWING_RATE);
    shutFrames += 1;
  }
  check('and 30 frames back to shut when the avatar walks away', shutFrames, 30);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(`\nsmoke_door_swing: ${e?.message || e}`);
  process.exit(1);
});
