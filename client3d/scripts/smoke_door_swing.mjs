#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/door_swing.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_door_swing.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
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
