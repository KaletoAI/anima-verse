#!/usr/bin/env node
/**
 * Review 13-contact#1/#4: the 3D client's runtime pair fit (`packages/scene-render/src/pairFit.ts`, THE SLICED SOLVE)
 * never stalls a frame, and records no evidence. Before the fix `pairFitObserve` ran the whole Gauss–Newton solve over
 * every sample of one loop inside the wrap frame: ≈ 1 s at 120 samples, ≈ 4 s at 600 (the client froze once per pair
 * interaction), and appended up to three numbers per frame to arrays nothing in the client reads.
 *
 * Usage: node scripts/smoke_pair_fit_budget.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * THE BUDGET. A frame at 60 Hz has 16.7 ms and rendering needs most of it. `CLIENT_PAIR_FIT.sliceMs` = 3 ms of solve
 * work per frame; the solve yields after every sample's bend (one `bendSample` ≈ 0.07 ms on this machine: 8 sweeps ×
 * ≤ 3 joints × 16 bisection steps), so the slice overruns by about one sample. Outside the solve a frame does at most
 * one more bend (the follow) and O(samples) bookkeeping. On top comes what ANY frame of this allocation-heavy code can
 * hit: a young-generation GC pause or a JIT tier-up (measured up to ≈ 3.5 ms here, also in frames after the fit that
 * solve nothing). So FRAME_BUDGET_MS = 3 ms slice + 5 ms for one such pause = 8 ms, half a frame — the stated budget.
 * A single GC pause is noise, not a regression: each run is repeated up to three times and the BEST run's worst call
 * must stay under the budget (a systematic overrun — the old 1 s wrap frame — shows in every repetition).
 *
 * FIXTURE (the review's benchmark loop, scratchpad bench13/bench.mjs): a 6-point chain stroking ±3 cm along the
 * channel, a support of two shins, bend limits raised 15°/35°, resting 45°/120°, axes side (1,0,0) / forward (0,0,1),
 * RUNTIME_FIT bounds. One loop of N frames (N = 120, 300, 600 — 2 s at 60/150/300 fps) at phase k/N · 2 s.
 *   [1] Loop 1 arms, loop 2 is sampled (N samples), the wrap into loop 3 (frame 2N) starts the solve: the samples
 *       handed to it are the 32 at indices floor(i · N / 32), i = 0..31 (CLIENT_PAIR_FIT.maxSamples; 32 > FOLLOW.bins
 *       = 24, the resolution the follow corrects with).
 *   [2] Every pairFitObserve call of the run (collect, solve, two loops after the fit) takes < FRAME_BUDGET_MS.
 *   [3] The sliced solve gives EXACTLY (deepEqual) solvePairFix on those 32 samples with the same options — slicing
 *       changes when the fix lands, never the fix.
 *   [4] It lands, and not in the wrap frame: a 32-sample solve is ≈ 4300 steps ≈ 300 ms of work, ≈ 100 frames at
 *       3 ms; the run allows 3000 frames (9 s of slices) before calling it stuck.
 *   [5] The client records no evidence: lateralMm / bendDeg / supportMm stay empty after two fitted loops; the default
 *       (the Library preview) still records them.
 *   [6] The old path (the default runtime = the whole solve over all samples in the wrap frame) on N = 120 takes
 *       longer than FRAME_BUDGET_MS in that one call — check [2] fails on it.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pair-fit-budget-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const built = await esbuild.build({
      stdin: { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'sr.mjs'), external: ['three', 'three/*'], logLevel: 'error',
    })
    const file = join(dir, 'sr.mjs')
    await writeFile(file, built.outputFiles[0].text, 'utf8')
    return await import(`file://${file}`)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}
const SR = await loadSR()
const FRAME_BUDGET_MS = 8
const PERIOD = 2
const STUCK_FRAMES = 3000
const AXES = [[1, 0, 0], [0, 0, 1]]
const BEND = { raised: { jointDeg: 15, totalDeg: 35 }, resting: { jointDeg: 45, totalDeg: 120 } }
const OPTS = { ...SR.RUNTIME_FIT, axes: AXES, bend: BEND, group: null }

function frame(k, N) {
  const ph = k / N * Math.PI * 2
  const s = 0.03 * Math.sin(ph)
  const o = [0.02 * Math.sin(ph * 2), 1.0 + 0.01 * Math.cos(ph), 0.5]
  const u0 = [0.05, -0.1, 1], l = Math.hypot(...u0), u = u0.map((v) => v / l)
  const base = [0.03, 0.98, 0.5 - 0.16 + s]
  const chain = [0, 1, 2, 3, 4, 5].map((j) => [base[0] + 0.004 * j, base[1] + 0.006 * j * Math.cos(ph), base[2] + 0.03 * j])
  const support = { ids: ['left_shin', 'right_shin'], pts: [[0.1, 0.05, 0], [0.1, 0.06, 0.4], [-0.1, 0.05, 0], [-0.1, 0.06, 0.4]],
    r: [0.05, 0.05, 0.05, 0.05] }
  return { tip: chain[5], base: chain[0], o, u, pivot: [0, 0.95, 0.3], chain, raised: 0.8, channel: true, support }
}

/** Feed frames as the renderer would (the sample measured WITH the current total): two loops, then on until fitted
 *  (at most STUCK_FRAMES), then two more loops. Per-call times, the frames the solve started and landed at. */
function run(st, N) {
  const times = []
  let fittedAt = -1, sampledN = -1, solveStart = -1, after = -1
  for (let i = 0; after < 0 || i < after; i++) {
    if (fittedAt < 0 && i > 2 * N + STUCK_FRAMES) break
    const k = i % N
    const ph = k / N * PERIOD
    const measured = SR.fixSample(frame(k, N), SR.pairFitTotal(st, st.phase === 'fitted' ? ph : undefined))
    const before = st.samples.length, solving = !!st.solver
    const t0 = performance.now()
    SR.pairFitObserve(st, measured, ph, AXES, SR.RUNTIME_FIT, true)
    times.push(performance.now() - t0)
    if (solveStart < 0 && !solving && (st.solver || st.phase === 'fitted')) { solveStart = i; sampledN = before }
    if (fittedAt < 0 && st.phase === 'fitted') { fittedAt = i; after = i + 2 * N }
  }
  return { times, fittedAt, sampledN, solveStart }
}

// Warm the JIT on a small solve first so the measured run is not the compile.
SR.solvePairFix(Array.from({ length: 8 }, (_, k) => frame(k, 8)), OPTS)

for (const N of [120, 300, 600]) {
  let best = null
  for (let rep = 0; rep < 3 && !(best && best.worst < FRAME_BUDGET_MS); rep++) {
    const st = SR.createPairFit(BEND, null, SR.CLIENT_PAIR_FIT)
    const r = run(st, N)
    assert.equal(r.sampledN, N, `[1] N=${N}: one whole loop sampled`)
    assert.equal(r.solveStart, 2 * N, `[1] N=${N}: the solve starts in the wrap into loop 3`)
    assert.equal(st.samples.length, 32, `[1] N=${N}: 32 samples`)
    Array.from({ length: 32 }, (_, i) => Math.floor(i * N / 32)).forEach((j, i) =>
      assert.deepEqual(st.samples[i].tip, frame(j, N).tip, `[1] N=${N}: sample ${i} = frame ${j}`))
    assert.deepEqual(st.fix, SR.solvePairFix(st.samples, OPTS), `[3] N=${N}: sliced fix = whole solve`)
    assert.ok(r.fittedAt > r.solveStart, `[4] N=${N}: the fix never landed (or landed in the wrap frame)`)
    assert.equal(st.lateralMm.length + st.bendDeg.length + st.supportMm.length, 0, `[5] N=${N}: no evidence`)
    const worst = Math.max(...r.times)
    if (!best || worst < best.worst) best = { worst, frames: r.fittedAt - r.solveStart + 1, rep }
  }
  assert.ok(best.worst < FRAME_BUDGET_MS, `[2] N=${N}: worst call ${best.worst.toFixed(2)} ms ≥ ${FRAME_BUDGET_MS} ms`)
  console.log(`  N=${N}: worst call ${best.worst.toFixed(2)} ms (run ${best.rep + 1}), solve over ${best.frames} frames`)
}

{ // [5] the preview default keeps its evidence; [6] the old path stalls the wrap frame
  const st = SR.createPairFit(BEND, null)
  const r = run(st, 120)
  const wrap = r.times[r.solveStart]
  assert.equal(r.fittedAt, r.solveStart, '[6] the default fits in the wrap frame')
  assert.equal(st.samples.length, 120, '[6] the default solves over every sample')
  assert.ok(st.lateralMm.length + st.bendDeg.length > 0 && st.supportMm.length > 0, '[5] the preview records its evidence')
  assert.ok(wrap > FRAME_BUDGET_MS, `[6] the unsliced wrap frame took only ${wrap.toFixed(1)} ms`)
  console.log(`  old path (unsliced, 120 samples): wrap frame ${wrap.toFixed(0)} ms`)
}
console.log('smoke_pair_fit_budget: OK')
