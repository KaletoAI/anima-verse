#!/usr/bin/env node
/**
 * Smoke check for the STATISTICS of the render bench (client3d/src/bench/benchStats.ts
 * — the pure part; the camera drive and the DOM readout need a browser).
 *
 * Usage:  node client3d/scripts/smoke_bench_math.mjs
 *
 * Hand-derived expectations (§ B5a: numbers, no snapshots):
 * [1] percentile — linear interpolation between ranks (p50 of 1,2,3,4 = 2.5)
 * [2] summarize — 4 frames of 10/20/30/40 ms: 0.1 s total, 40 fps mean
 *     (frames / seconds, NOT the mean of per-frame rates), frame-ms median 25,
 *     P95 38.5, cpu/gpu/calls/tris medians as given, gpuMs null when never
 *     resolved. Worked: p95 rank = 0.95 * (4 - 1) = 2.85, so frame ms
 *     30 + 0.85 * 10 = 38.5 and cpu (2,4,6,8) 6 + 0.85 * 2 = 7.7, cpu median 5;
 *     calls sorted 100,110,120,130 -> median 115, tris -> 1150; with gpuMs
 *     null,4,5,6 only 4,5,6 count -> median 5
 * [3] empty input yields zeros and nulls, never NaN
 *
 * The cases (inputs + expectations) live in shared/test-vectors/bench_math.json, shared with
 * the native client's C# tests; each case label starts with the [n] of its derivation above.
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
