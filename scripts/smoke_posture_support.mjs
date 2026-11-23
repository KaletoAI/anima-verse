#!/usr/bin/env node
/**
 * Ruling A150: the posture support of the pair solve (`packages/scene-render/src/postureSupport.ts`, the posture band of
 * `pairAlign.ts` THE RESIDUALS, solved by solveAlign with basis I and a cap of ±0.5 m / 20° that does not bind).
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
 *       axes, no bend, no channel inequalities. All frames are alike, so the deep and the shallow key frame are the same
 *       one frame. Rigid (no support): root and tip are both off by (0, −0.05) → Δ = (0, 0.05, 0). With the support
 *       above (base = its own height): the y residuals are (d − 0.05) for the root, (d − 0.05) for the tip and
 *       300·(d − 0.015) for d > 0.015; d/dd [2(d − 0.05)² + 90000 (d − 0.015)²] = 0 → d = (0.2 + 2700)/180004
 *       = 0.01500077776. The band edge is a kink (zero slope inside), which Gauss–Newton approaches from inside by
 *       line-search halvings: expect d − 0.5 mm ≤ Δy ≤ d + 1e-6 (never beyond the minimum, at most 0.5 mm short),
 *       Δx = Δz = 0 (±1e-9).
 *   [4] postureAngleCapDeg (tilt and roll; owner 2026-11-23 the lying role is held by THE SUPPORT, ABSOLUTE instead):
 *       stand 20 → 3, lie 20 → 20, seat 20 → 20, null 10 → 10.
 *   [5] postureReport of the frames moved by [3]: gapMm = Δy·1000 (±1e-6), sinkMm 0, heightMm = (0.05 + Δy)·1000 with
 *       surface 0, limited (Δy ≥ 14.5 mm ≥ 15 − 2).
 *   [6] Fixture [3] with tilt/roll axes X, Z and the place type 'stand' (angle cap postureAngleCapDeg('stand', 20) = 3):
 *       every turn ≤ 3° (+1e-9).
 *   [7] THE SUPPORT, ABSOLUTE: surfaceExcess 0.02 → 0.01, −0.008 → −0.003, 0.005 → 0 (band [−5, +10] mm).
 *       supportMode of [1]'s sample: only the two shins carry it and they stand upright (vertical 0.4 / 0.38 m
 *       capsules) → 'band' (on its feet). The shins laid flat (left_shin (0, 0.1, 0)–(0, 0.1, 0.4), right_shin
 *       (0.2, 0.12, 0)–(0.2, 0.12, 0.4), r 0.05; lowest point 0.05) on a surface at 0.05: surfaceGap 0 → 'surface'; on
 *       a surface at −0.01: gap 0.06 > carriedM 0.05 → 'band' (carried by someone else).
 *   [8] Fixture [3] with the flat shins and mode 'surface', surface 0.05: the gap is d (the vertical shift), root and tip want d = 0.05, the band allows d ≤ 0.01: minimise 2(d − 0.05)² + 300²(d − 0.01)²
 *       → d = (0.1 + 900)/90002 = 0.0100004444; the kink is approached from either side within 0.5 mm.
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
const I3 = [1, 0, 0, 0, 1, 0, 0, 0, 1], cap = { sideM: 0.5, upM: 0.5, forwardM: 0.5, angleDeg: 20 }
const solve = (samples, extra = {}) => SR.solveAlign({ relations: [{ samples }], basis: I3, cap, ...extra })
const rigid = solve(Array.from({ length: 6 }, () => frame(null))).fix
near(rigid.shift[1], 0.05, 1e-6, '[3] rigid Δy')
const S = Array.from({ length: 6 }, () => frame(sup))
const fix = solve(S).fix
const d = (0.2 + 2700) / 180004
assert.ok(fix.shift[1] >= d - 0.0005 && fix.shift[1] <= d + 1e-6, `[3] posture Δy ${fix.shift[1]} vs ${d}`); near(fix.shift[0], 0, 1e-9, '[3] Δx'); near(fix.shift[2], 0, 1e-9, '[3] Δz')
// [4]
assert.equal(SR.postureAngleCapDeg('stand', 20), 3); assert.equal(SR.postureAngleCapDeg('lie', 20), 20)
assert.equal(SR.postureAngleCapDeg('seat', 20), 20); assert.equal(SR.postureAngleCapDeg(null, 10), 10)
// [5]
const rep = SR.postureReport(S.map((x) => ({ support: x.support, pts: x.support.pts.map((p) => SR.fixPoint(fix, x.pivot, p)) })))
near(rep.gapMm, fix.shift[1] * 1000, 1e-6, '[5] gap'); assert.equal(rep.sinkMm, 0)
near(rep.heightMm, (0.05 + fix.shift[1]) * 1000, 1e-6, '[5] height'); assert.equal(rep.limited, true)
// [6]
const ax = [[1, 0, 0], [0, 0, 1]]
const tf = solve(S, { axes: ax, angleCapDeg: SR.postureAngleCapDeg('stand', cap.angleDeg) })
for (const a of tf.deg) assert.ok(Math.abs(a) <= 3 + 1e-9, `[6] turn ${a}`)
// [7]
near(SR.surfaceExcess(0.02), 0.01, 1e-12, '[7] float'); near(SR.surfaceExcess(-0.008), -0.003, 1e-12, '[7] sink')
assert.equal(SR.surfaceExcess(0.005), 0)
assert.equal(SR.supportMode(sup), 'band')
const flat = [
  { id: 'left_shin', now: { a: [0, 0.1, 0], b: [0, 0.1, 0.4], r: 0.05 } },
  { id: 'right_shin', now: { a: [0.2, 0.12, 0], b: [0.2, 0.12, 0.4], r: 0.05 } },
]
const fs0 = SR.supportSample(flat, { surface: 0.05 })
near(SR.surfaceGap(fs0), 0, 1e-12, '[7] flat gap'); assert.equal(SR.supportMode(fs0), 'surface')
assert.equal(SR.supportMode(SR.supportSample(flat, { surface: -0.01 })), 'band')
// [8]
const FS = Array.from({ length: 6 }, () => frame({ ...fs0, mode: 'surface' }))
const fx = solve(FS).fix
const d8 = (0.1 + 900) / 90002
assert.ok(Math.abs(fx.shift[1] - d8) <= 0.0005, `[8] surface Δy ${fx.shift[1]} vs ${d8}`)
console.log('smoke_posture_support OK')
