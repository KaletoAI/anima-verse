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
 * THE FOLLOW (A129.4), fixture C with the fit bounded to nothing (maxShiftM 0, maxAngleDeg 0) so only the follow acts;
 *   every frame inside (s ≥ −0.03). Integral control f ← f − 0.7·r on the lateral r of the frame just rendered:
 *   r_n = 0.01 + f_n  →  f_{n+1} = f_n − 0.7(0.01 + f_n) = 0.3 f_n − 0.007  →  f_n = −0.01 (1 − 0.3^n).
 *   [12] after 3 observed frames f_x = −0.01 · (1 − 0.027) = −0.00973 (±1e-9); f_y = f_z = 0.
 *   [13] lateral offset 0.05: the fixed point −0.05 lies beyond FOLLOW.maxM → f_x clamps at −0.02 after enough frames.
 *   [14] a tip far outside (s = −0.2 < −0.03): the follow decays by 0.9 per frame (−0.00973 → −0.008757).
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
const follow = (x0, frames, z = 0.01, st = SR.createPairFit()) => {
  for (let k = 0; k < frames; k++) {
    const tip = [x0, 0, z]
    const raw = { tip, base: [x0, 0, z - 0.1], o: O, u: U, pivot: [0, 0, -0.3] }
    SR.pairFitObserve(st, SR.fixSample(raw, SR.pairFitTotal(st)), 0.05 * k, [], NOFIT, true)
  }
  return st
}
const f3 = follow(0.01, 3)                                                                   // [12]
near(f3.follow[0], -0.00973, 1e-9, 'follow x'); near(f3.follow[1], 0, 1e-12, 'follow y'); near(f3.follow[2], 0, 1e-12, 'follow z')
near(follow(0.05, 30).follow[0], -0.02, 1e-12, 'follow clamp')                              // [13]
near(follow(0.01, 1, -0.2, f3).follow[0], -0.008757, 1e-9, 'follow decay')                  // [14]
console.log('smoke_pair_fit: OK')
