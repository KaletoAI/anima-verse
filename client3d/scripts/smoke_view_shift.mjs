/**
 * Derivation moved to native/tests/Derivations/view_shift.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_view_shift.mjs
 *         (transforms the module with esbuild — a Vite dependency, already
 *          installed; no bundler, no GL context, no server)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d/src/scene/viewShift.ts');

/** The module, transformed and imported — it has no imports of its own, so a
 *  single-file transform is enough. esbuild resolves from client3d/, whose
 *  Vite dependency it is. */
async function loadShift() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'viewshift-smoke-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'viewShift.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const V = await loadShift();
const vectors = runVectors(loadVectors('view_shift'), { viewShiftFor: V.viewShiftFor });
let passed = vectors.passed;
let failed = vectors.failed;
function check(what, ok) {
  if (ok) { passed += 1; console.log(`  ok   ${what}`); }
  else { failed += 1; console.log(`  FAIL ${what}`); }
}

const W = 1920;
const H = 1080;
console.log('\n(inline) relations');
const def = V.viewShiftFor(W, H, { x: 12, y: 388, w: 840, h: 680 });
check('[1] the cap does not bind horizontally', Math.abs(def.dx) < 0.35 * W / 2);
check('[1] the cap does not bind vertically', Math.abs(def.dy) < 0.35 * H / 2);
const small = V.viewShiftFor(W, H, { x: 12, y: 808, w: 520, h: 260 });
check('[5] a smaller window shifts less than the default', small.dx < def.dx);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
