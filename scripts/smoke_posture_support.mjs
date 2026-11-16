#!/usr/bin/env node
/**
 * Ruling A150: the posture support of a pair fit (`packages/scene-render/src/postureSupport.ts`, `pairFit.ts` POSTURE).
 * Every expected number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_posture_support.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE (metres, +Y up). Capsules: left_shin (0, 0.1, 0)–(0, 0.5, 0) r 0.05 → lowest point 0.05; right_shin
 *   (0.2, 0.12, 0)–(0.2, 0.5, 0) r 0.05 → 0.07; hips (0.1, 0.9, 0)–(0.1, 1.1, 0) r 0.1 → 0.8; an unknown id `tail`
 *   (0, −1, 0)–(0, −1, 0) r 0 is not a support capsule.
 *   [1] supportSample: the lowest is 0.05; within POSTURE.bandM = 0.04 lies 0.07 too, 0.8 not → ids [left_shin,
 *       right_shin], height 0.05. With ids [hips] given → only hips, height 0.8.
 *   [2] postureExcess: 0.02 → 0.02 − 0.015 = 0.005; −0.015 → −0.015 + 0.01 = −0.005; 0.01 → 0.
 *   [3] THE SOLVE: 6 frames, tip T = (0, 0, 0.3), base (0, 0, 0.2), O = (0, 0.05, 0.3), u = +Z, pivot (0, 0.9, 0), no
 *       axes, no bend. Rigid (no support): the lateral (0, −0.05) is taken by Δ = (0, 0.05, 0) (entry s = 0 already).
 *       With the support above (base = its own height): per frame the y residuals are (d − 0.05) and
 *       300·(d − 0.015) for d > 0.015; d/dd [(d − 0.05)² + 90000 (d − 0.015)²] = 0 → d = (0.05 + 1350)/90001
 *       = 0.01500038888. The band edge is a kink (zero slope inside), which Gauss–Newton approaches from inside by
 *       line-search halvings: expect d − 0.5 mm ≤ Δy ≤ d + 1e-6 (never beyond the minimum, at most 0.5 mm short),
 *       Δx = Δz = 0 (±1e-9).
 *   [4] postureAngleCapDeg: stand 20 → 3, lie 20 → 5, seat 20 → 20, null 10 → 10.
 *   [5] postureReport of the frames moved by [3]: gapMm = Δy·1000 (±1e-6), sinkMm 0, heightMm = (0.05 + Δy)·1000 with
 *       surface 0, limited (Δy ≥ 14.5 mm ≥ 15 − 2).
 *   [6] Fixture [3] with tilt/roll axes X, Z and group 'lie': every turn ≤ 5° (+1e-9).
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-posture-'))
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
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg}: ${a} vs ${b}`)
const caps = [
  { id: 'left_shin', now: { a: [0, 0.1, 0], b: [0, 0.5, 0], r: 0.05 } },
  { id: 'right_shin', now: { a: [0.2, 0.12, 0], b: [0.2, 0.5, 0], r: 0.05 } },
  { id: 'hips', now: { a: [0.1, 0.9, 0], b: [0.1, 1.1, 0], r: 0.1 } },
  { id: 'tail', now: { a: [0, -1, 0], b: [0, -1, 0], r: 0 } },
]
// [1]
const sup = SR.supportSample(caps, { surface: 0 })
assert.deepEqual(sup.ids, ['left_shin', 'right_shin'])
near(SR.supportHeight(sup.pts, sup.r), 0.05, 1e-12, '[1] height')
const hs = SR.supportSample(caps, { ids: ['hips'] })
assert.deepEqual(hs.ids, ['hips']); near(SR.supportHeight(hs.pts, hs.r), 0.8, 1e-12, '[1] hips height')
// [2]
near(SR.postureExcess(0.02), 0.005, 1e-12, '[2] float'); near(SR.postureExcess(-0.015), -0.005, 1e-12, '[2] sink')
assert.equal(SR.postureExcess(0.01), 0)
// [3]
const frame = (support) => ({ tip: [0, 0, 0.3], base: [0, 0, 0.2], o: [0, 0.05, 0.3], u: [0, 0, 1], pivot: [0, 0.9, 0],
  ...(support ? { support } : {}) })
const rigid = SR.solvePairFix(Array.from({ length: 6 }, () => frame(null)), { axes: [], maxShiftM: 0.5, maxAngleDeg: 20 })
near(rigid.shift[1], 0.05, 1e-6, '[3] rigid Δy')
const S = Array.from({ length: 6 }, () => frame(sup))
const fix = SR.solvePairFix(S, { axes: [], maxShiftM: 0.5, maxAngleDeg: 20 })
const d = (0.05 + 1350) / 90001
assert.ok(fix.shift[1] >= d - 0.0005 && fix.shift[1] <= d + 1e-6, `[3] posture Δy ${fix.shift[1]} vs ${d}`); near(fix.shift[0], 0, 1e-9, '[3] Δx'); near(fix.shift[2], 0, 1e-9, '[3] Δz')
// [4]
assert.equal(SR.postureAngleCapDeg('stand', 20), 3); assert.equal(SR.postureAngleCapDeg('lie', 20), 5)
assert.equal(SR.postureAngleCapDeg('seat', 20), 20); assert.equal(SR.postureAngleCapDeg(null, 10), 10)
// [5]
const rep = SR.postureReport(S.map((x) => ({ support: x.support, pts: x.support.pts.map((p) => SR.fixPoint(fix, x.pivot, p)) })))
near(rep.gapMm, fix.shift[1] * 1000, 1e-6, '[5] gap'); assert.equal(rep.sinkMm, 0)
near(rep.heightMm, (0.05 + fix.shift[1]) * 1000, 1e-6, '[5] height'); assert.equal(rep.limited, true)
// [6]
const ax = [[1, 0, 0], [0, 0, 1]]
const tf = SR.solvePairFix(S, { axes: ax, maxShiftM: 0.5, maxAngleDeg: 20, group: 'lie' })
for (const a of SR.fixAnglesDeg(tf, ax)) assert.ok(Math.abs(a) <= 5 + 1e-9, `[6] turn ${a}`)
console.log('smoke_posture_support OK')
