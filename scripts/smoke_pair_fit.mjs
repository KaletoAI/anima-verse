#!/usr/bin/env node
/**
 * Ruling A129: the pair fit of `packages/scene-render/src/pairFit.ts` — shift AND partner B's tilt/roll. Every
 * expected number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_pair_fit.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE A (metres). Channel O = (0, 0, 0), u = (0, 0, 1). The shaft runs along d = (0, sin 10°, cos 10°)
 *   = (0, 0.17364818, 0.98480775): tips T_c = c·d for c = 0 and 0.03, base = T − 0.1·d, pivot p = −0.3·d
 *   = (0, −0.05209445, −0.29544233) (on the shaft's line). Axes: tilt (1, 0, 0), roll (0, 1, 0).
 *   [1] ROTATION about +X by α maps (0, sin β, cos β) to (0, sin(β − α), cos(β − α)); α = 10° lays d on u.
 *       Then R(T_c − p) + p = p + (0.3 + c)·u = (0, −0.05209445, 0.00455767 + c), so Δ = (0, 0.05209445,
 *       −0.00455767) puts every tip on the axis with the entry tip at s = 0: every residual 0 — the unique minimum.
 *       Expect tilt 10° (±0.01°), roll 0° (±0.01°), Δ as above (±1e-5 m).
 *   [2] fixSample of that fix: tips (0, 0, 0) and (0, 0, 0.03) (±1e-5), shaft against the axis 0° (contactReport
 *       axisDeg < 0.05°). Before the fix the angle is 10° (acos(d·u)).
 *   [3] BOUND: maxAngleDeg 5 → tilt exactly 5° (projected), |Δ_i| ≤ 0.5.
 *   [4] fixPoint ∘ unfixPoint = identity on (0.1, −0.2, 0.3) (±1e-12).
 * FIXTURE B = A126's fixture 1 (smoke_channel_contact.mjs): no axes → the shift-only solve; its minimum is
 *   Δ = (−0.01, 0.02, 0.05) (the angle term is constant there: the shaft lies on the axis direction).
 *   [5] solvePairFix(no axes) = (−0.01, 0.02, 0.05) ± 1e-6.
 * [6] partnerTurnFix(10, −5, identity frame) = turn (10°, 0, −5°) in radians: (0.17453293, 0, −0.08726646).
 * [7] fixPivot((1, 0, 2), Ry(90°) row-major [0,0,1, 0,1,0, −1,0,0], hips (0, 0.9, 0.1)) = (1 + 0.1, 0.9, 2 − 0) =
 *     (1.1, 0.9, 2).
 * FIXTURE C — THE RUNTIME FIT (A129.3). Same channel; ten frames per loop at phase k/10, tip T = (0.01, 0, −0.02 +
 *   0.05·phase), base = T − 0.1·u, pivot (0, 0, −0.3), no axes. Fed as the renderer would: the sample measured WITH
 *   `pairFitTotal` applied.
 *   [8] Loop 1 is not sampled (it may have started mid-loop); the wrap into loop 2 arms, loop 2 is sampled (10
 *       samples), the wrap into loop 3 solves: phase 'fitted' after 2 loops + 1 frame, not one frame earlier.
 *   [9] The fix: lateral x + 0.01 → Δx = −0.01, Δy = 0; entry frame = phase 0 (s = −0.02) → Δz = +0.02 (±1e-6).
 *   [10] Bound: the same with x = 0.08 → Δx clamped to −0.05 (RUNTIME_FIT.maxShiftM).
 *   [11] After the fit every measured frame lies on the axis: lateralMm all 0 (±1e-3 mm). Loop 3 adds 9 rows: its
 *        frame 0 is the solving frame, rendered BEFORE the fit (s = −0.02 < 0, not inside).
 * THE FOLLOW (A129.4), fixture C with the fit bounded to nothing (maxShiftM 0, maxAngleDeg 0) so only the follow acts.
 *   Fitted after 2 loops + 1 frame ([8]); the period seen is 0.9 s, so 24 bins of 0.0375 s: phase k/10 lies in bin
 *   floor(k/10 / 0.9 · 24) — k = 0..9 → bins 0, 2, 5, 8, 10, 13, 16, 18, 21, 23 (one frame per bin). Each bin learns
 *   f ← f − 0.8·r from the frame rendered with it: r_n = 0.01 + f_n → f_n = −0.01 (1 − 0.2^n) per loop.
 *   [12] after loops 3, 4, 5 (frames 1..9 of loop 3 learn; frame 0 was the solving frame, rendered before the fit):
 *        bin 0 has learnt twice (loops 4, 5) → −0.01 · (1 − 0.04) = −0.0096; bin 2 thrice → −0.01 · 0.992 = −0.00992.
 *   [13] lateral offset 0.05: the fixed point −0.05 lies beyond FOLLOW.maxM → every bin at −0.02 after 4 loops.
 *   [14] the tip far outside (s = −0.2 < −0.03) for one more loop: bin 2 decays by 0.9 → −0.008928.
 *   [15] pairFitTotal at phase 0.1 (bin 2) carries that bin's shift; without a phase it carries none.
 * THE HONEST CHECK (A129.5): entering E with part capsule `part`, receiving R whose channel allows `pelvis`.
 *   Contacts: E|part–R|pelvis 0.03 (exempt), R|pelvis–E|part 0.04 (exempt, reversed order), E|part–R|thigh 0.01
 *   (counts: the part may only pass the allowed capsule), E|thigh–R|pelvis 0.02 (counts: not the part).
 *   [16] depth 0.02 at E thigh ↔ R pelvis. Without the exemption the deepest would be 0.04.
 *   [17] lamps: 5 mm green, 5.1 yellow, 20 yellow, 20.1 red.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pair-fit-'))
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
const s10 = Math.sin(10 * Math.PI / 180), c10 = Math.cos(10 * Math.PI / 180)
const d = [0, s10, c10], U = [0, 0, 1], O = [0, 0, 0]
const pivot = d.map((v) => -0.3 * v)
const A = [0, 0.03].map((c) => ({ tip: d.map((v) => c * v), base: d.map((v) => (c - 0.1) * v), o: O, u: U, pivot }))
const AXES = [[1, 0, 0], [0, 1, 0]]

const fix = SR.solvePairFix(A, { axes: AXES, maxShiftM: 0.5, maxAngleDeg: 20 })            // [1]
const [tilt, roll] = SR.fixAnglesDeg(fix, AXES)
near(tilt, 10, 0.01, 'tilt'); near(roll, 0, 0.01, 'roll')
near(fix.shift[0], 0, 1e-5, 'dx'); near(fix.shift[1], 0.05209445, 1e-5, 'dy'); near(fix.shift[2], -0.00455767, 1e-5, 'dz')
const moved = A.map((x) => SR.fixSample(x, fix))                                             // [2]
near(moved[0].tip[1], 0, 1e-5, 'tip0 y'); near(moved[0].tip[2], 0, 1e-5, 'tip0 z'); near(moved[1].tip[2], 0.03, 1e-5, 'tip1 z')
near(SR.contactReport(A).axisDeg, 10, 1e-6, 'angle before')
assert.ok(SR.contactReport(moved).axisDeg < 0.05, 'angle after')
const lim = SR.solvePairFix(A, { axes: AXES, maxShiftM: 0.5, maxAngleDeg: 5 })               // [3]
near(SR.fixAnglesDeg(lim, AXES)[0], 5, 1e-9, 'bounded tilt')
assert.ok(lim.shift.every((v) => Math.abs(v) <= 0.5))
const P = [0.1, -0.2, 0.3], back = SR.unfixPoint(fix, pivot, SR.fixPoint(fix, pivot, P))     // [4]
P.forEach((v, i) => near(back[i], v, 1e-12, 'inverse'))
const B = [-0.05, 0, 0.03].map((z) => ({ tip: [0.01, -0.02, z], base: [0.01, -0.02, z - 0.1], o: O, u: U, pivot: [0, 0, 0] }))
const fb = SR.solvePairFix(B, { axes: [], maxShiftM: 0.5, maxAngleDeg: 20 })                 // [5]
;[-0.01, 0.02, 0.05].forEach((v, i) => near(fb.shift[i], v, 1e-6, 'shift-only'))
const pt = SR.partnerTurnFix(10, -5, [1, 0, 0, 0, 1, 0, 0, 0, 1])                            // [6]
near(pt.turn[0], 0.17453293, 1e-8, 'turn x'); near(pt.turn[1], 0, 1e-12, 'turn y'); near(pt.turn[2], -0.08726646, 1e-8, 'turn z')
const pv = SR.fixPivot([1, 0, 2], [0, 0, 1, 0, 1, 0, -1, 0, 0], [0, 0.9, 0.1])               // [7]
;[1.1, 0.9, 2].forEach((v, i) => near(pv[i], v, 1e-12, 'pivot'))
const runLoops = (x0, loops) => {
  const st = SR.createPairFit()
  const log = []
  for (let L = 0; L < loops; L++) for (let k = 0; k < 10; k++) {
    const ph = k / 10, tip = [x0, 0, -0.02 + 0.05 * ph]
    const raw = { tip, base: [tip[0], tip[1], tip[2] - 0.1], o: O, u: U, pivot: [0, 0, -0.3] }
    SR.pairFitObserve(st, SR.fixSample(raw, SR.pairFitTotal(st)), ph, [], SR.RUNTIME_FIT, false)
    log.push(st.phase)
  }
  return { st, log }
}
const c1 = runLoops(0.01, 3)                                                                // [8]
assert.equal(c1.log[19], 'collect'); assert.equal(c1.log[20], 'fitted')
const cf = c1.st.fix.shift                                                                  // [9]
near(cf[0], -0.01, 1e-6, 'fit x'); near(cf[1], 0, 1e-6, 'fit y'); near(cf[2], 0.02, 1e-6, 'fit z')
near(runLoops(0.08, 3).st.fix.shift[0], -0.05, 1e-12, 'fit bound')                          // [10]
assert.equal(c1.st.lateralMm.length, 9)                                                    // [11]
assert.ok(c1.st.lateralMm.every((v) => Math.abs(v) < 1e-3), 'lateral after the fit')
const NOFIT = { maxShiftM: 0, maxAngleDeg: 0 }
const followLoops = (x0, loops, z = 0.01, st = SR.createPairFit()) => {
  for (let L = 0; L < loops; L++) for (let k = 0; k < 10; k++) {
    const ph = k / 10, tip = [x0, 0, z]
    const raw = { tip, base: [x0, 0, z - 0.1], o: O, u: U, pivot: [0, 0, -0.3] }
    SR.pairFitObserve(st, SR.fixSample(raw, SR.pairFitTotal(st, ph)), ph, [], NOFIT, true)
  }
  return st
}
const f5 = followLoops(0.01, 5)                                                             // [12]
near(f5.period, 0.9, 1e-12, 'period')
near(f5.followTable[0][0], -0.0096, 1e-9, 'bin 0'); near(f5.followTable[2][0], -0.00992, 1e-9, 'bin 2')
near(f5.followTable[2][1], 0, 1e-12, 'bin 2 y')
assert.ok(followLoops(0.05, 6).followTable.filter((_, b) => [0, 2, 5, 8, 10, 13, 16, 18, 21, 23].includes(b))
  .every((c) => Math.abs(c[0] + 0.02) < 1e-12), 'follow clamp')                             // [13]
near(followLoops(0.01, 1, -0.2, f5).followTable[2][0], -0.008928, 1e-9, 'follow decay')   // [14]
near(SR.pairFitTotal(f5, 0.1).shift[0], f5.followTable[2][0], 1e-12, 'total with phase')   // [15]
near(SR.pairFitTotal(f5).shift[0], 0, 1e-12, 'total without phase')
const contacts = [{ a: 'E', capA: 'part', b: 'R', capB: 'pelvis', depth: 0.03 },
  { a: 'R', capA: 'pelvis', b: 'E', capB: 'part', depth: 0.04 }, { a: 'E', capA: 'part', b: 'R', capB: 'thigh', depth: 0.01 },
  { a: 'E', capA: 'thigh', b: 'R', capB: 'pelvis', depth: 0.02 }]
const hon = SR.pairInterpenetration(contacts, { entering: 'E', parts: new Set(['part']), receiving: 'R', allowed: new Set(['pelvis']) })
near(hon.depth, 0.02, 1e-12, 'honest depth'); assert.deepEqual(hon.worst, { a: 'E', capA: 'thigh', b: 'R', capB: 'pelvis' })  // [16]
near(SR.pairInterpenetration(contacts, { entering: 'E', parts: new Set(), receiving: 'R', allowed: new Set() }).depth, 0.04, 1e-12, 'no exemption')
assert.deepEqual([5, 5.1, 20, 20.1].map(SR.clearLamp), ['green', 'yellow', 'yellow', 'red'])                                       // [17]
console.log('smoke_pair_fit: OK')
