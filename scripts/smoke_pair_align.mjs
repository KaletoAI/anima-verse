#!/usr/bin/env node
/**
 * Ruling A212: the bounded Auto-align of `packages/scene-render/src/pairAlign.ts`. Every expected number is derived BY
 * HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_pair_align.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE (metres). Channel O = (0, 0, 0), u = (0, 0, 1); basis = identity, so x = (side, up, forward) = world x, y, z.
 *   A sample at phase φ has tip T = (lx(φ), ly, −0.02 + 0.05·φ), base T − 0.1·u (the shaft lies along u: the angle
 *   term is 0 for every shift), pivot (0, 0, −0.3). No bend, no posture, no axes unless named. Then the residual is
 *   separable per axis: side/up only see the tip's lateral (lx + y_side, ly + y_up), forward only sees the entry term
 *   √(10·N)·(s_min + y_fwd) with s_min = −0.02 (phase 0). Cap of the default range 8 cm: side 3 cm, up 8, forward 8.
 *   [1] lx = 0.01, ly = −0.02 at all five phases: the unique minimum y = (−0.01, 0.02, 0.02), inside the cap →
 *       x = (−0.01, 0.02, 0.02) (±1e-6), lamp green, offCm 0.
 *   [2] lx = 0.05: side free optimum −0.05, cap 0.03 → x_side = −0.03 exactly; excess 2 cm → offCm = 2 (±0.01), lamp
 *       yellow (≤ 8 cm); up/forward unchanged (0.02, 0.02).
 *   [3] lx = 0.15: excess 12 cm > 8 → red; x_side still −0.03.
 *   [4] TWO RELATIONS solved together: relation 1 lx = 0.02, relation 2 lx = 0 (same N = 5): Σ (0.02 + y)² + y² is
 *       least at y = −0.01. (One after the other the second would end at 0: the last relation wins.)
 *   [5] THE CAP IS THE TOTAL: start = (−0.02, 0, 0) already applied, the measured lx = 0.02 still wants −0.02 more
 *       (free total −0.04) → the total stops at −0.03, the increment (fix.shift x) is −0.01; offCm = 1.
 *   [6] range 4 cm: alignCap(4) = side 0.03, up 0.04, forward 0.04; ly = −0.06 → x_up = 0.04, offCm 2.
 *   [7] PHASES: samples at φ = k/10 (k = 0..9): pickPhases → 0, 0.2 (0.25 is a tie of 0.2/0.3: the first wins), 0.5,
 *       0.7 (tie 0.7/0.8), end = 0.9. phaseRow of T = (0.01, 0, 0.03), base T − 0.1u: tip 10 mm, depth 30 mm, axis 0°.
 *   [8] THE STROKE OVER ALL PHASES: lx = 0.01 at φ = 0, 0.5, 1 and 0.03 at 0.25, 0.75 → mean 0.018 → x_side = −0.018
 *       (an out/in pair φ = 0, 0.5 alone would give −0.01).
 *   [9] JOIN: lx = ly = 0, s_min = 0 (T_z = 0.05·φ), join Δ = (0, 0, 0.05), weight 1: forward cost 10N·y² + N(y − 0.05)²
 *       → 20y + 2(y − 0.05) = 0 → y = 0.1/22 = 0.0045454 (±1e-5).
 *   [10] TILT CAP: pairFit fixture A with the shaft tilted β = 15° (d = (0, sin β, cos β), tips c·d for c = 0, 0.03,
 *       base T − 0.1d, pivot −0.3d), axes tilt (1, 0, 0): the free optimum turns α = +15° (rotation about +X maps β to
 *       β − α) with shift up 0.3 sin 15° = 0.07765 (inside 8 cm) → deg = 10 (the cap), offDeg = 5 (±0.05), offCm 0,
 *       lamp yellow.
 *   [11] relativeOf / joinDelta: frame Ry(90°) row-major [0,0,1, 0,1,0, −1,0,0], anchor (1, 0, 2), hips (1, 0.1, 3):
 *       d = (0, 0.1, 1), frameᵀd = (−1, 0.1, 0); joinDelta of that rel from the same hips = (0, 0, 0); from hips
 *       (1, 0.1, 2.5) = (0, 0, 0.5).
 *   [12] THE RECEIVING FIGURE NEVER MOVES: hits {e 1, r 0}, {e 2, r 0}, {e 1, r 3} → alignMovers keys exactly {1, 2}
 *       (1 with two relations, solved together); 0 and 3 only receive and are no key.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pair-align-'))
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
const U = [0, 0, 1], O = [0, 0, 0], I = [1, 0, 0, 0, 1, 0, 0, 0, 1]
const PH = [0, 0.25, 0.5, 0.75, 1]
const smp = (lx, ly, ph, z0 = -0.02) => {
  const tip = [lx, ly, z0 + 0.05 * ph]
  return { tip, base: [tip[0], tip[1], tip[2] - 0.1], o: O, u: U, pivot: [0, 0, -0.3] }
}
const rel = (f) => ({ samples: PH.map((ph) => f(ph)) })
const cap = SR.alignCap()
let n = 0
const ok = (m) => { n++; console.log(`  PASS  ${m}`) }

{ const r = SR.solveAlignAdjust({ relations: [rel((ph) => smp(0.01, -0.02, ph))], basis: I, cap })
  near(r.x[0], -0.01, 1e-6, '[1] side'); near(r.x[1], 0.02, 1e-6, '[1] up'); near(r.x[2], 0.02, 1e-6, '[1] fwd')
  assert.equal(r.lamp, 'green'); near(r.offCm, 0, 1e-3, '[1] off'); ok('[1] inside the cap: the exact minimum, green') }
{ const r = SR.solveAlignAdjust({ relations: [rel((ph) => smp(0.05, -0.02, ph))], basis: I, cap })
  near(r.x[0], -0.03, 1e-9, '[2] side capped'); near(r.x[1], 0.02, 1e-6, '[2] up'); near(r.x[2], 0.02, 1e-6, '[2] fwd')
  near(r.offCm, 2, 0.01, '[2] off'); assert.equal(r.lamp, 'yellow'); ok('[2] side capped at 3 cm, 2 cm off, yellow') }
{ const r = SR.solveAlignAdjust({ relations: [rel((ph) => smp(0.15, 0, ph))], basis: I, cap })
  near(r.x[0], -0.03, 1e-9, '[3] side'); assert.equal(r.lamp, 'red'); near(r.offCm, 12, 0.01, '[3] off'); ok('[3] 12 cm off → red') }
{ const r = SR.solveAlignAdjust({ relations: [rel((ph) => smp(0.02, 0, ph)), rel((ph) => smp(0, 0, ph))], basis: I, cap })
  near(r.x[0], -0.01, 1e-6, '[4] joint'); ok('[4] two relations solved together: −0.01') }
{ const r = SR.solveAlignAdjust({ relations: [rel((ph) => smp(0.02, 0, ph))], basis: I, cap, start: [-0.02, 0, 0] })
  near(r.x[0], -0.03, 1e-9, '[5] total'); near(r.fix.shift[0], -0.01, 1e-9, '[5] increment'); near(r.offCm, 1, 0.01, '[5] off')
  ok('[5] the cap holds the TOTAL over iterations') }
{ const c4 = SR.alignCap(4)
  near(c4.sideM, 0.03, 1e-12, '[6] side'); near(c4.upM, 0.04, 1e-12, '[6] up'); near(c4.forwardM, 0.04, 1e-12, '[6] fwd')
  const r = SR.solveAlignAdjust({ relations: [rel((ph) => smp(0, -0.06, ph))], basis: I, cap: c4 })
  near(r.x[1], 0.04, 1e-9, '[6] up capped'); near(r.offCm, 2, 0.01, '[6] off'); ok('[6] a clip range of 4 cm') }
{ const s = Array.from({ length: 10 }, (_, k) => ({ phase: k / 10 }))
  assert.deepEqual(SR.pickPhases(s).map((x) => x.phase), [0, 0.2, 0.5, 0.7, 0.9])
  const row = SR.phaseRow({ tip: [0.01, 0, 0.03], base: [0.01, 0, -0.07], o: O, u: U, pivot: O }, 0.5)
  near(row.tipMm, 10, 1e-9, '[7] tip'); near(row.depthMm, 30, 1e-9, '[7] depth'); near(row.axisDeg, 0, 1e-6, '[7] axis')
  ok('[7] the five phases and a phase row') }
{ const lx = (ph) => (ph === 0.25 || ph === 0.75 ? 0.03 : 0.01)
  const r = SR.solveAlignAdjust({ relations: [rel((ph) => smp(lx(ph), 0, ph))], basis: I, cap })
  near(r.x[0], -0.018, 1e-6, '[8] stroke'); ok('[8] the stroke fitted over all five phases: −0.018') }
{ const r = SR.solveAlignAdjust({ relations: [rel((ph) => smp(0, 0, ph, 0))], basis: I, cap, join: { deltaM: [0, 0, 0.05] } })
  near(r.x[2], 0.1 / 22, 1e-5, '[9] join'); ok('[9] the join to the base end pose: 0.004545') }
{ const b = 15 * Math.PI / 180, d = [0, Math.sin(b), Math.cos(b)], pv = d.map((v) => -0.3 * v)
  const s = [0, 0.03].map((c) => { const tip = d.map((v) => c * v); return { tip, base: tip.map((v, i) => v - 0.1 * d[i]), o: O, u: U, pivot: pv } })
  const r = SR.solveAlignAdjust({ relations: [{ samples: s }], basis: I, cap, axes: [[1, 0, 0]] })
  near(r.deg[0], 10, 1e-6, '[10] tilt capped'); near(r.freeDeg[0], 15, 0.05, '[10] free'); near(r.offDeg, 5, 0.05, '[10] offDeg')
  near(r.offCm, 0, 0.01, '[10] offCm'); assert.equal(r.lamp, 'yellow'); ok('[10] tilt capped at 10°, 5° off, yellow') }
{ const F = [0, 0, 1, 0, 1, 0, -1, 0, 0]
  const rv = SR.relativeOf(F, [1, 0.1, 3], [1, 0, 2])
  ;[-1, 0.1, 0].forEach((v, i) => near(rv[i], v, 1e-12, '[11] rel'))
  SR.joinDelta(F, rv, [1, 0.1, 3], [1, 0, 2]).forEach((v) => near(v, 0, 1e-12, '[11] join 0'))
  const j = SR.joinDelta(F, rv, [1, 0.1, 2.5], [1, 0, 2]); [0, 0, 0.5].forEach((v, i) => near(j[i], v, 1e-12, '[11] join'))
  ok('[11] relativeOf / joinDelta') }
{ const m = SR.alignMovers([{ e: 1, r: 0 }, { e: 2, r: 0 }, { e: 1, r: 3 }])
  assert.deepEqual([...m.keys()].sort(), [1, 2]); assert.equal(m.get(1).length, 2)
  ok('[12] only the figures with the attached part move; the receiving ones are no key') }
console.log(`\n${n}/12 checks passed`)
