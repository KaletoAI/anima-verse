#!/usr/bin/env node
/**
 * Smoke check for the STATISTICS of the render bench (client3d/src/render/bench.ts
 * — the pure part; the camera drive and the DOM readout need a browser).
 *
 * Usage:  node client3d/scripts/smoke_bench_math.mjs
 *
 * Hand-derived expectations (§ B5a: numbers, no snapshots):
 * [1] percentile — linear interpolation between ranks (p50 of 1,2,3,4 = 2.5)
 * [2] summarize — 4 frames of 10/20/30/40 ms: 0.1 s total, 40 fps mean
 *     (frames / seconds, NOT the mean of per-frame rates), frame-ms median 25,
 *     P95 38.5, cpu/gpu/calls/tris medians as given, gpuMs null when never
 *     resolved
 * [3] empty input yields zeros and nulls, never NaN
 * [4] the drive: yaw runs 0..2π over the run, the distance goes r0->r1->r0 as
 *     a cosine — hand values at 0 %, 25 %, 50 %, 100 %
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d/src/render/bench.ts');
let fails = 0;
const check = (ok, msg) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${msg}`); if (!ok) fails++; };
const near = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps;

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

console.log('\n[1] percentile');
check(near(m.percentile([1, 2, 3, 4], 50), 2.5), 'p50 of 1,2,3,4 = 2.5 (interpolated)');
check(near(m.percentile([1, 2, 3, 4], 0), 1) && near(m.percentile([1, 2, 3, 4], 100), 4), 'p0 / p100 are min / max');
check(near(m.percentile([5], 95), 5), 'single sample answers itself');
check(near(m.percentile([10, 20, 30, 40], 95), 38.5), 'p95 of 10..40 = 38.5');
check(Number.isNaN(m.percentile([], 50)) === false && m.percentile([], 50) === 0, 'empty list -> 0, not NaN');

console.log('\n[2] summarize');
const S = [
  { dt: 0.01, cpuMs: 2, gpuMs: null, calls: 100, tris: 1000 },
  { dt: 0.02, cpuMs: 4, gpuMs: null, calls: 120, tris: 1200 },
  { dt: 0.03, cpuMs: 6, gpuMs: null, calls: 110, tris: 1100 },
  { dt: 0.04, cpuMs: 8, gpuMs: null, calls: 130, tris: 1300 },
];
const s = m.summarize(S);
check(s.frames === 4, 'frames 4');
check(near(s.seconds, 0.1), 'seconds 0.1');
check(near(s.fpsMean, 40), 'fpsMean = frames/seconds = 40');
check(near(s.frameMsMedian, 25), 'frameMsMedian 25');
check(near(s.frameMsP95, 38.5), 'frameMsP95 38.5');
check(near(s.cpuMsMedian, 5) && near(s.cpuMsP95, 7.7), 'cpuMs median 5 / p95 7.7');
check(s.gpuMsMedian === null, 'gpuMsMedian null when never resolved');
check(near(s.callsMedian, 115) && near(s.trisMedian, 1150), 'calls / tris medians');
const withGpu = m.summarize(S.map((x, i) => ({ ...x, gpuMs: i === 0 ? null : 3 + i })));
check(near(withGpu.gpuMsMedian, 5), 'gpuMsMedian ignores unresolved frames (median of 4,5,6 = 5)');

console.log('\n[3] empty');
const e = m.summarize([]);
check(e.frames === 0 && e.seconds === 0 && e.fpsMean === 0 && e.frameMsMedian === 0
      && e.gpuMsMedian === null && !Object.values(e).some((v) => Number.isNaN(v)), 'zeros/nulls, no NaN');

console.log('\n[4] the drive');
const d0 = m.driveAt(0, 40, 12), d25 = m.driveAt(0.25, 40, 12), d50 = m.driveAt(0.5, 40, 12), d1 = m.driveAt(1, 40, 12);
check(near(d0.yaw, 0) && near(d1.yaw, 2 * Math.PI), 'yaw 0 -> 2π');
check(near(d50.yaw, Math.PI), 'yaw π at half time');
check(near(d0.dist, 40) && near(d1.dist, 40), 'dist starts and ends at r0');
check(near(d50.dist, 12), 'dist reaches r1 at half time');
check(near(d25.dist, 26), 'dist at a quarter = midpoint (cosine)');

console.log(fails ? `\n${fails} FAILED` : '\nall ok');
process.exit(fails ? 1 : 0);
