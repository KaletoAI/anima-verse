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
 *   [13] ACTIVE SET (best fit with one unknown on its bound): fixture [10] (β = 15°, up and tilt correlated — both move
 *       the tips in y) with the tilt capped at 10°. The answer must be the least-squares optimum of (side, up, forward)
 *       WITH tilt held at 10°: a brute-force grid of up × forward (step 0.1 mm over ±8 cm, side 0 by the fixture's
 *       x-symmetry; refined to 0.01 mm around the best cell) gives that optimum's cost; the solver's cost must not
 *       exceed it by more than 1e-9 and its up/forward lie within 0.02 mm of the grid's.
 *   [14] RIGID RECOVERY (Ruling A145 root-only, finding F2: Auto-align never bends). A clip frame turned 30° about +Y,
 *       basis B with columns side = (cos 30°, 0, −sin 30°), up = (0, 1, 0), forward = (sin 30°, 0, cos 30°); axes tilt =
 *       side, roll = forward. The CORRECT stroke: a 4-link chain of 0.03 m lying ON the axis u = B·(0, −sin 15°, cos 15°)
 *       (opening O1 = (0, 0.9, 0.4)) with the tip at s = 0, 0.05, 0.10, 0.05, 0 over the five phases, the pivot 0.25 m
 *       behind O1 on the axis (moving with the stroke), `raised` 1, a channel — every residual is 0. MISPLACED by a known
 *       rigid fix about the pivot: X' = R(X − p) + p + B·e, p' = p + B·e, R = exp(side·4° + forward·(−3°)), e = (2, −3,
 *       2.5) cm. The fix that undoes it about p' is R⁻¹ = exp(−(side·4° + forward·(−3°))) and the shift −B·e, i.e.
 *       x = (−2, +3, −2.5) cm and (tilt, roll) = (−4°, +3°): all residuals 0 again, and the minimum is unique (the five
 *       phases' lateral fix side/up and the shaft's two angles, the entry term the forward). Both within the cap → the
 *       solve returns them to < 0.1 mm / 0.2° (bound asked: 1 mm), the free optimum the same (it is unique), lamp green,
 *       and the rigid tip lies on the axis afterwards (< 0.1 mm). TWO RELATIONS: a second chain on the SAME figure
 *       (opening O2 = O1 + B·(0.08, 0.05, 0), the same pivot), misplaced by the same fix → the same answer. Before
 *       (with the bend inside the fit) this case left the rigid tip 15–20 mm off the axis.
 *   [15] THE LAMP WHEN THE CAP CANNOT REACH: the [14] stroke misplaced by e = (5, 0, 0) cm (side cap 3) and tilt 14°
 *       (cap 10°): the free optimum is the unique inverse (−5 cm, −14°), so offCm = 2, offDeg = 4 → yellow (never
 *       green); the capped solve holds x_side at −3 cm and the tilt inside ±10° (where exactly is the least squares with
 *       side on its bound — shift and tilt both move the tip sideways, so it is not simply −10°). e = (0, 0, 20) cm
 *       (forward cap 8): offCm = 12 → red.
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
{ const b = 15 * Math.PI / 180, d = [0, Math.sin(b), Math.cos(b)], pv = d.map((v) => -0.3 * v)
  const s = [0, 0.03].map((c) => { const tip = d.map((v) => c * v); return { tip, base: tip.map((v, i) => v - 0.1 * d[i]), o: O, u: U, pivot: pv } })
  const r = SR.solveAlignAdjust({ relations: [{ samples: s }], basis: I, cap, axes: [[1, 0, 0]] })
  const a10 = 10 * Math.PI / 180
  const cost = (up, fw) => SR.fitResiduals(s, { shift: [0, up, fw], turn: [a10, 0, 0] }).reduce((a, v) => a + v * v, 0)
  let best = [Infinity, 0, 0]
  for (let i = -800; i <= 800; i++) for (let j = -800; j <= 800; j++) { const c = cost(i * 1e-4, j * 1e-4); if (c < best[0]) best = [c, i * 1e-4, j * 1e-4] }
  const [, u0, f0] = best
  for (let i = -10; i <= 10; i++) for (let j = -10; j <= 10; j++) { const c = cost(u0 + i * 1e-5, f0 + j * 1e-5); if (c < best[0]) best = [c, u0 + i * 1e-5, f0 + j * 1e-5] }
  near(r.deg[0], 10, 1e-9, '[13] tilt on its bound')
  const mine = cost(r.x[1], r.x[2])
  assert.ok(mine <= best[0] + 1e-9, `[13] cost ${mine} vs brute ${best[0]}`)
  near(r.x[1], best[1], 2e-5, '[13] up'); near(r.x[2], best[2], 2e-5, '[13] forward'); near(r.x[0], 0, 1e-9, '[13] side')
  ok(`[13] active set = brute force (up ${(r.x[1] * 1000).toFixed(2)} mm, fwd ${(r.x[2] * 1000).toFixed(2)} mm)`) }
{ // [14] / [15] rigid recovery
  const D2R = Math.PI / 180
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
  const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k]
  const yaw = 30 * D2R
  const B = [Math.cos(yaw), 0, Math.sin(yaw), 0, 1, 0, -Math.sin(yaw), 0, Math.cos(yaw)]
  const col = (j) => [B[j], B[3 + j], B[6 + j]]
  const side = col(0), up = col(1), fwd = col(2)
  const Bv = (v) => add(add(mul(side, v[0]), mul(up, v[1])), mul(fwd, v[2]))
  const u = Bv([0, -Math.sin(15 * D2R), Math.cos(15 * D2R)])
  const stroke = (O, pivot0) => [0, 0.05, 0.10, 0.05, 0].map((s, i) => {
    const tip = add(O, mul(u, s)), chain = Array.from({ length: 5 }, (_, k) => sub(tip, mul(u, 0.03 * (4 - k))))
    return { tip, base: chain[0], o: O, u, pivot: add(pivot0, mul(u, s)), chain, raised: 1, channel: true, phase: i / 4 }
  })
  const misplace = (smps, e, tilt, roll) => {
    const fix = { shift: Bv(e), turn: add(mul(side, tilt * D2R), mul(fwd, roll * D2R)) }
    return smps.map((s) => ({ ...SR.fixSample(s, fix), pivot: add(s.pivot, fix.shift) }))
  }
  const tipOff = (s) => { const v = sub(s.tip, s.o), a = v[0] * s.u[0] + v[1] * s.u[1] + v[2] * s.u[2]; return Math.hypot(...sub(v, mul(s.u, a))) }
  const O1 = [0, 0.9, 0.4], P1 = sub(O1, mul(u, 0.25))
  const C1 = stroke(O1, P1)
  const C2 = stroke(add(O1, Bv([0.08, 0.05, 0])), P1).map((s, i) => ({ ...s, pivot: C1[i].pivot }))
  const solve = (rels) => SR.solveAlignAdjust({ relations: rels.map((samples) => ({ samples })), basis: B, axes: [side, fwd], cap })
  const e = [0.02, -0.03, 0.025]
  for (const [label, rels] of [['one relation', [misplace(C1, e, 4, -3)]], ['two relations', [misplace(C1, e, 4, -3), misplace(C2, e, 4, -3)]]]) {
    const r = solve(rels)
    ;[-0.02, 0.03, -0.025].forEach((v, i) => near(r.x[i], v, 1e-4, `[14] ${label} x[${i}]`))
    near(r.deg[0], -4, 0.2, `[14] ${label} tilt`); near(r.deg[1], 3, 0.2, `[14] ${label} roll`)
    ;[-0.02, 0.03, -0.025].forEach((v, i) => near(r.freeX[i], v, 1e-4, `[14] ${label} free x[${i}]`))
    assert.equal(r.lamp, 'green')
    for (const sm of rels) for (const s of sm) assert.ok(tipOff(SR.fixSample(s, r.fix)) < 1e-4, `[14] ${label} rigid tip after`)
    ok(`[14] rigid recovery, ${label}: x ${r.x.map((v) => (v * 100).toFixed(3)).join('/')} cm, tilt ${r.deg[0].toFixed(3)}° roll ${r.deg[1].toFixed(3)}°`)
  }
  { const r = solve([misplace(C1, [0.05, 0, 0], 14, 0)])
    near(r.x[0], -0.03, 1e-6, '[15] side capped'); assert.ok(Math.abs(r.deg[0]) <= 10 + 1e-9, `[15] tilt within the cap ${r.deg[0]}`)
    near(r.freeX[0], -0.05, 1e-4, '[15] free side'); near(r.freeDeg[0], -14, 0.05, '[15] free tilt')
    near(r.offCm, 2, 0.01, '[15] offCm'); near(r.offDeg, 4, 0.05, '[15] offDeg'); assert.equal(r.lamp, 'yellow')
    const r2 = solve([misplace(C1, [0, 0, 0.20], 0, 0)])
    near(r2.offCm, 12, 0.01, '[15] offCm red'); assert.equal(r2.lamp, 'red')
    ok(`[15] the cap cannot reach: yellow (${r.offCm.toFixed(2)} cm, ${r.offDeg.toFixed(2)}° off), red (${r2.offCm.toFixed(2)} cm)`) }
}
console.log(`\n${n}/16 checks passed`)
