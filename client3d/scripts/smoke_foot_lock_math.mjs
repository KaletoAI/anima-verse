#!/usr/bin/env node
/**
 * Smoke check for the FOOT-LOCK maths of the 3D client
 * (`client3d/src/scene/footLock.ts`) — the TypeScript twin of the importer's
 * `app/blender/scripts/_root_motion.py`. Pure numbers (§ B5a), no three, no
 * clips, no server.
 *
 * Usage:  node client3d/scripts/smoke_foot_lock_math.mjs
 *         (needs esbuild; reads scripts/fixtures/root_motion_cases.json)
 *
 * Hand-derived expectations
 * -------------------------
 * The expectations are NOT derived here a second time: they live in the
 * shared fixture `scripts/fixtures/root_motion_cases.json`, which holds the
 * cases [2], [4], [5], [6], [10] and [11] of `scripts/smoke_root_motion_math.py`
 * with the paths and drifts derived by hand in that smoke's docstring (each
 * case names its origin in `"from"`). The Python smoke checks the same file in
 * its section [F], so one file is the contract both copies answer to.
 *
 *   [C] constants: BAND_LO_CM 2, BAND_HI_CM 5, VY_LO_CM_S 15, VY_HI_CM_S 30,
 *       GROUND_PCT 0.05, MIN_WEIGHT 1e-3, FULL 0.999 and CONTACT_POINTS
 *       (LeftFoot, LeftToeBase, RightFoot, RightToeBase) equal the fixture's.
 *
 *   [F] every fixture case through groundHeights → contactWeights →
 *       footLockPath: the path within 1e-6 of the fixture's, and
 *       maxPlantedDrift with the case's own path (`drift_path`) and with an
 *       all-zero path (`drift_zero_path`, the strip file) where given.
 *       Example, case [2]: one foot at its rest height 8 sliding back 2 cm a
 *       frame → path z = 2f, drift 0 with that path, 20 with a zero path.
 *
 *   [D] degenerate inputs, from the Python smoke's [1]/[7]:
 *       ramp(NaN, 2, 5) = 0; ramp(3.5, 2, 5) = (5 − 3.5)/3 = 0.5;
 *       footLockPath({}, {}) = [] (empty tracks → empty path).
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const FIXTURE = join(ROOT, 'scripts/fixtures/root_motion_cases.json');
const EPS = 1e-6;

let failed = 0;
let passed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`); }
  else { failed += 1; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`); }
}
const near = (label, actual, expected, eps = EPS) =>
  check(label, Number.isFinite(actual) && Math.abs(actual - expected) <= eps,
    `got ${actual}, expected ${expected} ±${eps}`);
const nearPath = (label, path, expected, eps = EPS) =>
  check(label, Array.isArray(path) && path.length === expected.length
    && path.every((p, i) => Math.abs(p[0] - expected[i][0]) <= eps
      && Math.abs(p[1] - expected[i][1]) <= eps),
  `got ${JSON.stringify(path)}, expected ${JSON.stringify(expected)}`);

async function loadFootLock() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const entry = `export * from '${join(ROOT, 'client3d/src/scene')}/footLock';`;
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'footLock.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'footLock.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function main() {
  const fl = await loadFootLock();
  const fixture = JSON.parse(await readFile(FIXTURE, 'utf8'));

  console.log('[C] constants equal the fixture');
  for (const [key, want] of Object.entries(fixture.constants)) {
    const got = fl[key];
    if (Array.isArray(want)) {
      check(`constant ${key}`, JSON.stringify([...(got ?? [])]) === JSON.stringify(want),
        `${JSON.stringify(got)} vs ${JSON.stringify(want)}`);
    } else {
      near(`constant ${key}`, got, want, 0);
    }
  }

  console.log('[F] shared fixture cases');
  for (const c of fixture.cases) {
    const ground = fl.groundHeights(c.tracks, c.rest);
    const weights = fl.contactWeights(c.tracks, ground, c.fps);
    const path = fl.footLockPath(c.tracks, weights);
    nearPath(`${c.from} path`, path, c.expect.path);
    if ('drift_path' in c.expect) {
      near(`${c.from} drift with its path`, fl.maxPlantedDrift(c.tracks, weights, path),
        c.expect.drift_path);
    }
    if ('drift_zero_path' in c.expect) {
      const zero = path.map(() => [0, 0]);
      near(`${c.from} drift with a zero path`, fl.maxPlantedDrift(c.tracks, weights, zero),
        c.expect.drift_zero_path);
    }
  }

  console.log('[D] degenerate inputs');
  near('ramp(NaN, 2, 5) = 0', fl.ramp(Number.NaN, 2, 5), 0);
  near('ramp(3.5, 2, 5) = 0.5', fl.ramp(3.5, 2, 5), 0.5);
  const empty = fl.footLockPath({}, {});
  check('empty tracks → empty path', Array.isArray(empty) && empty.length === 0,
    JSON.stringify(empty));

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((err) => {
  console.error(`FAIL ${err?.message ?? err}`);
  process.exit(1);
});
