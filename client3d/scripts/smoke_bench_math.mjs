#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/bench_math.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_bench_math.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d/src/bench/benchStats.ts');

async function load() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      stdin: { contents: `export * from '${SRC}';`, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'bench.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'bench.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally { await rm(dir, { recursive: true, force: true }); }
}

const m = await load();
const { passed, failed } = runVectors(loadVectors('bench_math'), {
  percentile: m.percentile,
  summarize: m.summarize,
});
console.log(failed ? `\n${failed} FAILED, ${passed} ok` : `\nall ok (${passed})`);
process.exit(failed ? 1 : 0);
