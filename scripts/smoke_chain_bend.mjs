#!/usr/bin/env node
/**
 * Ruling A145: the attached part bends toward its contact target before the pair fit moves the partner
 * (`packages/scene-render/src/chainBend.ts`, `pairFit.ts` bendSample / solvePairFix with `bend`). Every expected number
 * is derived BY HAND below (§ B5a).
 *
 * Usage: node scripts/smoke_chain_bend.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * [1] bendLimitAt: raised 1 → 15° / 35°; raised 0 → 45° / 120°; raised 0.5 → 30° / 77.5° (linear).
 * [2] bendJoints(n): the last 3 of P_1 … P_{n−1}: n 5 → [2, 3, 4]; n 4 → [1, 2, 3]; n 2 → [1]; n 1 → [].
 * [3] One joint, unclamped: P (0,0,0), (0,0,0.1), (0,0,0.2), joint [1]; axis u (0,0,1) through o (0,−h,0) with
 *     h = 0.1·sin 10° = 0.0173648. The tip turned by θ about P_1 is (0, −0.1 sin θ, 0.1 + 0.1 cos θ); on the line when
 *     0.1 sin θ = h → θ = 10°, tip (0, −0.0173648, 0.1984808).
 * [4] The same with h = 0.05 (θ would be 30°) under 15° / 35°: the joint stops at 15°, tip y = −0.1 sin 15° =
 *     −0.0258819; at the limit (every joint at its own) → lamp yellow.
 * [5] Three joints, a straight chain P_k = (0,0,0.1k), k 0…4, joints [1,2,3]; the line far below (o (0,−1,0), u +z):
 *     every joint wants down; per joint ≤ 15° and in all ≤ 35° → total 35°, each ≤ 15°, tip y < 0, lamp yellow.
 * [6] Channel follow: P_k = (0,0,0.1k), k 0…3, joints [1,2] (resting limits 45/120: not binding); channel axis
 *     through o (0,0,0.15), u = (0, −sin 20°, cos 20°). The tip is inside, so the tip link's joint P_2 is an
 *     effector too, and the solve lays P_2 and P_3
 *     ON the axis: link 2 along u (bend 20° in all) and P_2 = P_1 + 0.1(0, −sin α, cos α) on the line
 *     y = −(z − 0.15) tan 20°: 0.1 sin α = (0.1 cos α − 0.05) tan 20° → α = 10.1534° (joint 1), 20° − α = 9.8466°
 *     (joint 2). P_2, P_3 lateral ≈ 0.
 * [7] Rigid (A129) vs bend first: 6 frames, chain P_k = (0, 0.01, 0.1k + 0.01i), k 0…3, frame i 0…5, axis u +z
 *     through o (0,0,0.3) — a parallel offset of 1 cm, the tip at or past the opening (s 0 … 0.05). Rigid shift-only solve: the lateral rows
 *     want Δy = −0.01 exactly (the entry row only touches z, the base→tip direction is along u whatever the shift).
 *     Bend first (resting limits): with the tip at/inside the opening the tip link's joint is an effector too, the
 *     joints lay P_2, P_3 on the axis (a few degrees ≪ the limit), the last link
 *     runs along u, so nothing but the stay term is left in y: |Δy| < 0.3 · 0.01, and the bent tip's lateral < 1 mm.
 *     The bend: P_2 down onto the axis from the offset left after the shift, e = 0.01 + Δy, over the 0.1 m link →
 *     asin(e / 0.1) at joint 1, the same back at joint 2 → 2 asin(e / 0.1) in all (11.48° at Δy = 0).
 * [8] bendLimitsOf({raised: {joint_deg: 10}}) → raised 10 / 35 (total from the default), resting 45 / 120; junk →
 *     defaults. Limit 0 → no bend at all.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')

async function loadSR() {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-chain-bend-'))
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
const D = SR.BEND_LIMITS_DEFAULT
const lat = (p, o, u) => { const r = [p[0] - o[0], p[1] - o[1], p[2] - o[2]]; const s = r[0] * u[0] + r[1] * u[1] + r[2] * u[2]
  return Math.hypot(r[0] - s * u[0], r[1] - s * u[1], r[2] - s * u[2]) }

// [1]
assert.deepEqual(SR.bendLimitAt(D, 1), { jointDeg: 15, totalDeg: 35 })
assert.deepEqual(SR.bendLimitAt(D, 0), { jointDeg: 45, totalDeg: 120 })
assert.deepEqual(SR.bendLimitAt(D, 0.5), { jointDeg: 30, totalDeg: 77.5 })
// [2]
assert.deepEqual(SR.bendJoints(5), [2, 3, 4]); assert.deepEqual(SR.bendJoints(4), [1, 2, 3])
assert.deepEqual(SR.bendJoints(2), [1]); assert.deepEqual(SR.bendJoints(1), [])
// [3]
const straight = (n, y = 0) => Array.from({ length: n + 1 }, (_, k) => [0, y, 0.1 * k])
const h = 0.1 * Math.sin(10 * Math.PI / 180)
const r3 = SR.solveChainBend(straight(2), [0, -h, 0], [0, 0, 1], { jointDeg: 45, totalDeg: 120 }, { joints: [1] })
near(r3.jointDeg[0], 10, 0.01, '[3] angle'); near(r3.points[2][1], -0.0173648, 1e-5, '[3] tip y'); near(r3.points[2][2], 0.1984808, 1e-5, '[3] tip z')
assert.equal(r3.atLimit, false); assert.equal(SR.bendLamp(r3), 'green')
// [4]
const r4 = SR.solveChainBend(straight(2), [0, -0.05, 0], [0, 0, 1], { jointDeg: 15, totalDeg: 35 }, { joints: [1] })
near(r4.jointDeg[0], 15, 0.01, '[4] clamped'); near(r4.points[2][1], -0.0258819, 2e-5, '[4] tip y')
assert.equal(r4.atLimit, true); assert.equal(SR.bendLamp(r4), 'yellow')
// [5]
const r5 = SR.solveChainBend(straight(4), [0, -1, 0], [0, 0, 1], { jointDeg: 15, totalDeg: 35 })
near(r5.totalDeg, 35, 0.01, '[5] total'); r5.jointDeg.forEach((a, i) => assert.ok(a <= 15 + 1e-6, `[5] joint ${i} ${a}`))
assert.ok(r5.points[4][1] < 0, '[5] tip down'); assert.equal(SR.bendLamp(r5), 'yellow')
// [6]
const a20 = 20 * Math.PI / 180, u6 = [0, -Math.sin(a20), Math.cos(a20)], o6 = [0, 0, 0.15]
const r6 = SR.solveChainBend(straight(3), o6, u6, { jointDeg: 45, totalDeg: 120 }, { channel: true, joints: [1, 2], sweeps: 40 })
near(r6.jointDeg[0], 10.1534, 0.05, '[6] joint 1'); near(r6.jointDeg[1], 9.8466, 0.05, '[6] joint 2')
assert.ok(lat(r6.points[2], o6, u6) < 1e-4 && lat(r6.points[3], o6, u6) < 1e-4, '[6] on the axis')
// the same without the channel rule only puts the TIP on the line (P_2 stays off it)
const r6b = SR.solveChainBend(straight(3), o6, u6, { jointDeg: 45, totalDeg: 120 }, { joints: [1, 2], sweeps: 40 })
assert.ok(lat(r6b.points[3], o6, u6) < 1e-4, '[6b] tip on the line')
// [7]
const o7 = [0, 0, 0.3], u7 = [0, 0, 1]
const frames = Array.from({ length: 6 }, (_, i) => {
  const dz = 0.01 * i
  const chain = straight(3, 0.01).map((p) => [p[0], p[1], p[2] + dz])
  return { tip: chain[3], base: chain[0], o: o7, u: u7, pivot: [0, 0, 0], chain, raised: 0, channel: true }
})
const rigid = SR.solvePairFix(frames, { maxShiftM: 0.5, maxAngleDeg: 20, axes: [] })
near(rigid.shift[1], -0.01, 1e-5, '[7] rigid Δy')
const bent = SR.solvePairFix(frames, { maxShiftM: 0.5, maxAngleDeg: 20, axes: [], bend: D })
assert.ok(Math.abs(bent.shift[1]) < 0.3 * 0.01, `[7] bend first Δy ${bent.shift[1]}`)
for (const f of frames) {
  const b = SR.bendSample(SR.fixSample(f, bent), D)
  assert.ok(lat(b.sample.tip, o7, u7) < 0.001, `[7] bent lateral ${lat(b.sample.tip, o7, u7)}`)
  const left = 0.01 + bent.shift[1]   // the offset the bend still has to take after the (small) shift
  near(b.bend.totalDeg, 2 * Math.asin(left / 0.1) * 180 / Math.PI, 0.2, '[7] bend (8 sweeps converge within 0.2°) = 2 · asin(offset / 0.1)')
}
// [8]
const L = SR.bendLimitsOf({ raised: { joint_deg: 10 } })
assert.deepEqual(L, { raised: { jointDeg: 10, totalDeg: 35 }, resting: { jointDeg: 45, totalDeg: 120 } })
assert.deepEqual(SR.bendLimitsOf('junk'), { raised: { jointDeg: 15, totalDeg: 35 }, resting: { jointDeg: 45, totalDeg: 120 } })
const r8 = SR.solveChainBend(straight(2), [0, -0.05, 0], [0, 0, 1], { jointDeg: 0, totalDeg: 0 })
assert.equal(r8.totalDeg, 0)
console.log('smoke_chain_bend OK')
