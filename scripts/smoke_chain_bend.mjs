#!/usr/bin/env node
/**
 * Ruling A145 (owner decision 2026-11-20): ONE total limit per state; a raised part (r = 1) turns only at its ROOT, the
 * shaft rigid; a resting one (r = 0) bends at every joint, in between it blends (`packages/scene-render/src/chainBend.ts`
 * THE DISTRIBUTION, `pairFit.ts` bendSample). Auto-align is rigid (`smoke_pair_align.mjs`). Every expected number is
 * derived BY HAND below (§ B5a). The r = 1 cases [3], [4], [7], [7b], [11] are the root-only cases of 309b0d6fb unchanged.
 *
 * Usage: node scripts/smoke_chain_bend.mjs   (no server, no world; bundles scene-render with esbuild, imports three)
 *
 * Chains below: S(n, a) = a straight chain P_k = a·k·(direction), k 0 … n, P_0 at the origin; L = n·a its length.
 * [1] bendLimitAt (the TOTAL): raised 1 → 15°; raised 0 → 120°; raised 0.5 → 67.5° (linear); a negative total → 0.
 *     bendShares(n, r): inner joints (1 − r)/n each, the root 1 − (n − 1)(1 − r)/n: n 4, r 0 → [¼, ¼, ¼, ¼]; r 0.5 →
 *     [0.625, 0.125, 0.125, 0.125]; r 1 → [1, 0, 0, 0]; n 1 → [1] at any r. Every row sums to 1.
 * [2] bendGate(s) = clamp((s + 0.08) / 0.05, 0, 1): s −0.10 → 0, −0.08 → 0, −0.055 → 0.5, −0.03 → 1, 0 → 1, +0.02 → 1.
 * [3] THE HAND CASE: S(4, 0.03) along +x (L = 0.12), a POINT target (no joint effectors), axis u = +x, the line
 *     parallel at lateral offset d = 0.01 (o = (L, 0.01, 0), so s_tip = 0, gate 1). A root turn θ about P_0 puts the
 *     tip at (L cos θ, L sin θ, 0); on the line when L sin θ = d → θ = asin(d / L) = asin(1/12) = 4.78019° (raised, r = 1), tip
 *     (0.1195818, 0.01, 0). Every point turns rigidly: P_k = 0.03k (cos θ, sin θ, 0) — the angle between neighbouring
 *     links (the KINK) is 0 at every inner joint. turns = [{joint 0}] exactly; raised limit 15 → not at the limit,
 *     green.
 * [4] THE CLAMP: the same with d = 0.05 → wanted asin(0.05/0.12) = 24.6243°; raised limit 15° → the turn is exactly
 *     15° about the same axis (+z): tip (L cos 15°, L sin 15°, 0) = (0.1159111, 0.0310583, 0); at the limit → yellow.
 * [5] THE F1 CASES (Ruling A145 diagnosis): S(4, 0.03) along +z, a CHANNEL with u = +z, 1 cm off-axis (line at
 *     y = −0.01), the tip at s_tip = −0.30, −0.10, −0.04, 0 (o = (0, −0.01, L − s_tip)), raised 1 and 0.
 *     s_tip −0.30, −0.10: gate 0 → no turn at all (deg 0, chain unchanged). s_tip −0.04: gate 0.8, limit 12° (raised) /
 *     96° (resting). The joint weights w_k = clamp(1 + s_k / 0.03, 0, 1) with s_k = s_tip − 0.03(4 − k): at s_tip −0.04
 *     and 0 every joint has s_k ≤ −0.03 → w 0, the tip alone. Raised: θ = asin(0.01/0.12) = 4.78019°, kink 0 at every
 *     inner joint (the old CCD kinked the tip joint by 15–18° here). Resting: the uniform arc of [12] (the same chain
 *     geometry turned onto +z), total 4φ = 7.65365°, kink φ = 1.91341° at every inner joint — under the limit.
 * [6] CONTINUITY: S(4, 0.03) along +z, channel, line at y = −0.03, s_tip swept −0.10 … +0.02 in steps of 0.5 mm and of
 *     0.25 mm, raised 1 and 0. The gated limit has slope L / 0.05 m (resting 120/50 = 2.4°/mm, raised 15/50 = 0.3°/mm);
 *     the unclamped turn moves slower (each joint weight ramps over 30 mm). So no step between neighbouring samples
 *     exceeds L/50 °/mm × the spacing (+5 %), and halving the spacing halves the largest step (ratio ≤ 0.6). The total
 *     never exceeds the gated limit, the inner joints never (1 − r)·limit. (The old CCD jumped 17° → 32° at
 *     s_tip = −0.03.)
 * [7] ALONG THE AXIS: S(4, 0.03) along +z, the channel axis through P_0 itself, u = (0, −sin 10°, cos 10°), o = 0.09u.
 *     Every effector's line point lies on the ray P_0 + t·u, so every effector asks for the same turn: the shaft
 *     along u, θ = 10°, every point's lateral 0 (≤ 1e-6).
 * [7b] THE WEIGHTED FIXED POINT: S(4, 0.03) along +z, channel, line at lateral d = 0.01 (y = 0.01), s_tip = +0.05
 *     (o = (0, 0.01, 0.07)). Input s_k = 0.05 − 0.03(4 − k): P_3 0.02 → w 1, P_2 −0.01 → w 2/3, P_1 −0.04 → w 0; tip
 *     w 1. A point at r from P_0 turned by θ sits at (r sin θ, r cos θ) (lateral, axial); its line point (d, r cos θ);
 *     its own turn atan(d / (r cos θ)) − θ. The fixed point: Σ w_k (atan(d / (r_k cos θ)) − θ) = 0 over r = 0.12 (w 1),
 *     0.09 (w 1), 0.06 (w 2/3) — solved here by bisection (an independent equation, not the solver), within 0.01°.
 *     The tip then sits OFF the line (the shaft is a compromise along the axis): the joints nearer the root need a
 *     steeper turn to reach the line (atan(d / (r cos θ)) grows as r shrinks), so θ is MORE than the tip-only
 *     asin(d/L) = 4.78° and the tip crosses past the line.
 * [8] bendLimitsOf({raised: {total_deg: 10}}) → raised 10, resting 120 (from the default); a stale joint_deg key is
 *     not read ({raised: {joint_deg: 5}} → raised 15); junk → defaults. Limit 0 → no turn at all (r 1 and r 0).
 * [9] THE ROOT ANGLE (A158, `rootTurnOf`): a straight 2-link chain P_k = (0, 0, 0.1k), frame side +X, up +Y (a figure
 *     facing +Z = side × up, its left +X). Pitch +α is a turn of −α about +X (fixed sign):
 *     tip (0, 0, 0.2) → (0, 0.2 sin α, 0.2 cos α). Pitch +30 → (0, 0.1, 0.1732051); −30 → (0, −0.1, 0.1732051); 0 → no
 *     turn (null). Yaw +β is a turn of −β about +Y (fixed sign): tip → (−0.2 sin β, 0, 0.2 cos β) —
 *     toward −X, the figure's RIGHT. Yaw +15 → (−0.0517638, 0, 0.1931852); −15 → (+0.0517638, 0, 0.1931852). P_0 stays;
 *     the middle point turns with it (0, 0.05, 0.0866025) at pitch +30. Pitch 70 is clamped to 60: tip y = 0.2 sin 60.
 *     A HANGING chain P_k = (0, −0.1k, 0): pitch +30 swings it FORWARD: tip (0, −0.2 cos 30, 0.2 sin 30) = (0, −0.1732051, 0.1).
 *     bodyFrameOf(hips (0,1,0), spine (0,1.1,0.02), left hip (0.1,0.95,0), right hip (−0.1,0.95,0)): side (1,0,0), up
 *     (0, 0.1, 0.02)/|…| = (0, 0.9805807, 0.1961161).
 * [10] rootAngleOf({pitch_deg: 20, yaw_deg: -5}) → 20 / −5; junk → 0 / 0.
 * [11] COMPOSITION ON REAL BONES (`SecondaryMotion.bendChain`, what `FigureRuntime.applyRootAngle` and
 *     `FigureRuntime.bendChain` both call): a reader Hips → A1 → A2 → A3, A1 at the origin, each link 0.1 along +z (the
 *     chain P_k = (0, 0, 0.1k), L = 0.3), op `appendage_chain`, gain 0, gravity 0 (one update leaves the bind pose).
 *     (a) Root angle pitch +20 (frame side +X, up +Y) through bendChain(0, [{joint 0, q_r}]): the rendered chain is
 *     `rootTurnOf`'s points, tip (0, 0.3 sin 20°, 0.3 cos 20°) = (0, 0.1026060, 0.2819078). (b) Then the bend, solved
 *     on that rendered chain (point target, u = +z, line y = d = 0.02, o = (0, 0.02, 0.2819078) so s_tip = 0, limit
 *     45°): the tip must end on the line at distance L → net angle asin(d / L) = 3.82255° up, tip
 *     (0, 0.02, √(0.09 − 0.0004)) = (0, 0.02, 0.2993326); the bend's own turn 20° − 3.82255° = 16.17745°. The rendered
 *     bones after both: tip (0, 0.02, 0.2993326) — the root angle FIRST, then the bend (D_bend · R_root). Had the bend
 *     replaced the root angle (applied to the straight chain) the tip would sit at 3.82255° − 20° = −16.17745°:
 *     (0, −0.3 sin 16.17745°, 0.3 cos 16.17745°) = (0, −0.0835839, 0.2881210); had the root angle won, at (0, 0.1026060, 0.2819078). Every inner point lies on the
 *     straight line P_0 → tip (kink 0).
 * [12] THE HAND CASE OF THE DISTRIBUTION (r = 0): S(4, 0.03) along +x, a point target, the line parallel at d = 0.01
 *     (o = (0.12, 0.01, 0), s_tip = 0, gate 1, limit 120°). Shares ¼ each: every joint turns by φ about +z, link k
 *     (0 … 3) points at (k + 1)φ, so P_m = 0.03 Σ_{k=1..m} (cos kφ, sin kφ, 0). The tip alone is the effector: on the
 *     line when 0.03 Σ_{k=1..4} sin kφ = 0.01 — solved by bisection here (small angle 0.3φ = 0.01 → φ ≈ 1.91°):
 *     φ = 1.91341°, total 4φ = 7.65365°, root φ, inner 3φ = 5.74024° (≤ 120). turns = joints [0, 1, 2, 3], each of
 *     angle φ; the kink at every inner joint φ; every P_m as above within 1e-6.
 * [13] THE BUDGET SPLIT AT r = 0.5: shares [0.625, 0.125, 0.125, 0.125] (cumulative link angles 0.625, 0.75, 0.875,
 *     1 × Θ). (a) Unclamped, the same chain and line: 0.03 Σ_k sin(C_k Θ) = 0.01 by bisection → Θ = 5.88392°;
 *     inner 0.375Θ = 2.20647° ≤ ½·L(0.5) = 33.75. (b) Clamped: the line at d = 0.05, an explicit total of 4°: the
 *     wanted Θ exceeds 4 → total 4, root 2.5, inner 1.5 ≤ ½ · 4 = 2; each inner joint 0.5°; yellow. (c) r = 0, total
 *     4°, d = 0.05: every joint 1° exactly, inner 3 ≤ 4.
 * [14] CONTINUITY IN r: the chain of [6] (channel, line at y = −0.03) at s_tip = 0 and −0.06, r swept 0 … 1 in steps of
 *     0.01 and 0.005, limits D. The total moves from the arc's to the root's without a jump: no step larger than
 *     max(2 × |θ(0) − θ(1)|, gate × (120 − 15)) × Δr (+ 1e-6) — the second term is the gated limit's own slope in r
 *     (gate 1 at s_tip 0, 0.4 at −0.06, where the limit binds: 0.4 × 105 = 42°/unit r), halving the spacing halves the largest step (ratio ≤ 0.6), and at every r the
 *     total ≤ the gated limit, the inner joints ≤ (1 − r) × it. r = 1 − 1e-9 against r = 1 (the root-only code): within
 *     1e-4°.
 * [15] THE RIGID TAIL: a reader Hips → A1 … A4 (links 0.1 along +z), rigid_tail 1: `opChains` lists THREE segments (A4
 *     carried, no point of its own: P_3 = A4's head (0, 0, 0.3)); the r = 0 solve's turns name joints 0, 1, 2 only;
 *     applied with bendChain the bones' points equal the solve's points (1e-6), and A4's local rotation stays the
 *     identity (it rides on A3, no turn of its own).
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
const THREE = await import('three')
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg}: ${a} vs ${b}`)
const close = (p, q, eps, msg) => { for (let k = 0; k < 3; k++) near(p[k], q[k], eps, `${msg}[${k}]`) }
const D = SR.BEND_LIMITS_DEFAULT
const DEG = Math.PI / 180
const sub = (p, q) => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const dot = (p, q) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const lat = (p, o, u) => { const r = sub(p, o); const s = dot(r, u)
  return Math.hypot(r[0] - s * u[0], r[1] - s * u[1], r[2] - s * u[2]) }
/** The largest angle (degrees) between neighbouring links of a chain. */
const kink = (c) => { let m = 0
  for (let k = 1; k < c.length - 1; k++) { const a = sub(c[k], c[k - 1]), b = sub(c[k + 1], c[k])
    m = Math.max(m, Math.acos(Math.min(1, dot(a, b) / Math.hypot(...a) / Math.hypot(...b))) / DEG) }
  return m }
const alongZ = (n, a = 0.03) => Array.from({ length: n + 1 }, (_, k) => [0, 0, a * k])
const alongX = (n, a = 0.03) => Array.from({ length: n + 1 }, (_, k) => [a * k, 0, 0])
let passed = 0
const ok = (m) => { passed++; console.log(`  PASS  ${m}`) }

// [1]
assert.equal(SR.bendLimitAt(D, 1), 15); assert.equal(SR.bendLimitAt(D, 0), 120); assert.equal(SR.bendLimitAt(D, 0.5), 67.5)
assert.equal(SR.bendLimitAt({ raised: { totalDeg: -5 }, resting: { totalDeg: -5 } }, 0.3), 0)
assert.deepEqual(SR.bendShares(4, 0), [0.25, 0.25, 0.25, 0.25]); assert.deepEqual(SR.bendShares(4, 0.5), [0.625, 0.125, 0.125, 0.125])
assert.deepEqual(SR.bendShares(4, 1), [1, 0, 0, 0]); assert.deepEqual(SR.bendShares(1, 0), [1])
for (const r of [0, 0.3, 0.5, 1]) near(SR.bendShares(4, r).reduce((a, v) => a + v, 0), 1, 1e-12, `[1] shares sum r ${r}`)
ok('[1] the total limit and the shares')
// [2]
;[[-0.10, 0], [-0.08, 0], [-0.055, 0.5], [-0.03, 1], [0, 1], [0.02, 1]].forEach(([s, g]) => near(SR.bendGate(s), g, 1e-12, `[2] gate ${s}`))
ok('[2] the distance gate')
// [3]
{
  const L = 0.12, d = 0.01, th = Math.asin(d / L)
  const r = SR.solveChainBend(alongX(4), [L, d, 0], [1, 0, 0], SR.bendLimitAt(D, 1))
  near(r.deg, 4.78019, 1e-4, '[3] root turn = asin(d/L)'); near(th / DEG, 4.78019, 1e-4, '[3] the hand value')
  close(r.points[4], [0.1195818, 0.01, 0], 1e-6, '[3] tip on the line')
  for (let k = 1; k <= 4; k++) close(r.points[k], [0.03 * k * Math.cos(th), 0.03 * k * Math.sin(th), 0], 1e-6, `[3] P_${k} rigid`)
  near(kink(r.points), 0, 1e-4, '[3] kink'); assert.deepEqual(r.turns.map((x) => x.joint), [0])
  assert.equal(r.atLimit, false); assert.equal(SR.bendLamp(r), 'green'); near(r.innerDeg, 0, 0, '[3] inner')
  ok(`[3] one root turn ${r.deg.toFixed(5)}° = asin(1/12), the shaft rigid`)
}
// [4]
{
  const r = SR.solveChainBend(alongX(4), [0.12, 0.05, 0], [1, 0, 0], SR.bendLimitAt(D, 1))
  near(r.deg, 15, 1e-9, '[4] clamped'); near(r.wantDeg, 24.6243, 1e-3, '[4] wanted')
  close(r.points[4], [0.1159111, 0.0310583, 0], 1e-6, '[4] tip'); near(kink(r.points), 0, 1e-4, '[4] kink')
  assert.equal(r.atLimit, true); assert.equal(SR.bendLamp(r), 'yellow')
  ok('[4] the projection to the 15° limit about the same axis, yellow')
}
// [5]
{
  const rows = []
  for (const raised of [1, 0]) for (const s of [-0.30, -0.10, -0.04, 0]) {
    const pts = alongZ(4)
    const smp = { tip: pts[4], base: pts[0], o: [0, -0.01, 0.12 - s], u: [0, 0, 1], pivot: [0, 0, 0], chain: pts, raised, channel: true }
    const { bend, sample } = SR.bendSample(smp, D)
    const want = s <= -0.08 ? 0 : raised ? 4.78019 : 7.65365
    near(bend.deg, want, 1e-4, `[5] raised ${raised} s ${s}`)
    near(kink(sample.chain), want === 0 || raised ? 0 : 1.91341, 1e-4, `[5] kink raised ${raised} s ${s}`)
    if (want === 0) assert.deepEqual(sample.chain, pts)
    rows.push(`${s * 100}cm:${bend.deg.toFixed(2)}°`)
  }
  ok(`[5] F1 cases, raised ${rows.slice(0, 4).join(' ')} kink 0; resting ${rows.slice(4).join(' ')} kink 1.91°`)
}
// [6]
{
  const sweep = (raised, ds) => {
    let prev = null, worst = 0
    for (let i = 0; ; i++) {
      const s = -0.10 + i * ds
      if (s > 0.02 + 1e-12) break
      const pts = alongZ(4)
      const b = SR.bendSample({ tip: pts[4], base: pts[0], o: [0, -0.03, 0.12 - s], u: [0, 0, 1], pivot: [0, 0, 0], chain: pts,
        raised, channel: true }, D).bend
      assert.ok(b.deg <= b.limitDeg + 1e-9 && b.innerDeg <= (1 - raised) * b.limitDeg + 1e-9, `[6] budget at s ${s}`)
      if (prev !== null) worst = Math.max(worst, Math.abs(b.deg - prev))
      prev = b.deg
    }
    return worst
  }
  for (const raised of [1, 0]) {
    const a = sweep(raised, 0.0005), b = sweep(raised, 0.00025)
    const slope = SR.bendLimitAt(D, raised) / 50 * 1.05
    assert.ok(a <= slope * 0.5, `[6] raised ${raised}: step ${a}° per 0.5 mm`)
    assert.ok(b <= slope * 0.25, `[6] raised ${raised}: step ${b}° per 0.25 mm`)
    assert.ok(b / a <= 0.6, `[6] raised ${raised}: halving the spacing ${a} → ${b}`)
    ok(`[6] continuous, raised ${raised}: largest step ${a.toFixed(3)}° / 0.5 mm, ${b.toFixed(3)}° / 0.25 mm`)
  }
}
// [7]
{
  const u = [0, -Math.sin(10 * DEG), Math.cos(10 * DEG)], o = u.map((v) => 0.09 * v)
  const r = SR.solveChainBend(alongZ(4), o, u, 45, { channel: true })
  near(r.deg, 10, 1e-4, '[7] along the axis'); r.points.forEach((p, k) => assert.ok(lat(p, o, u) < 1e-6, `[7] P_${k} lateral`))
  ok('[7] a channel through the root: the rigid shaft lies along the axis (10°)')
}
// [7b]
{
  const d = 0.01, o = [0, 0.01, 0.07], u = [0, 0, 1]
  const eff = [[0.12, 1], [0.09, 1], [0.06, 2 / 3]]
  const f = (th) => eff.reduce((a, [r, w]) => a + w * (Math.atan(d / (r * Math.cos(th))) - th), 0)
  let lo = 0, hi = 20 * DEG
  for (let i = 0; i < 80; i++) { const m = (lo + hi) / 2; if (f(m) > 0) lo = m; else hi = m }
  const want = lo / DEG
  const r = SR.solveChainBend(alongZ(4), o, u, 45, { channel: true })
  near(r.deg, want, 0.01, '[7b] weighted fixed point'); near(kink(r.points), 0, 1e-4, '[7b] kink')
  assert.ok(r.deg > 4.79 && lat(r.points[4], o, u) > 1e-4, '[7b] a compromise, not the tip alone')
  ok(`[7b] the joints near/inside weigh in: ${r.deg.toFixed(4)}° (equation ${want.toFixed(4)}°)`)
}
// [8]
{
  assert.deepEqual(SR.bendLimitsOf({ raised: { total_deg: 10 } }), { raised: { totalDeg: 10 }, resting: { totalDeg: 120 } })
  assert.deepEqual(SR.bendLimitsOf({ raised: { joint_deg: 5 } }), D)
  assert.deepEqual(SR.bendLimitsOf('junk'), D)
  for (const raised of [1, 0]) {
    const r8 = SR.solveChainBend(alongX(4), [0.12, 0.05, 0], [1, 0, 0], 0, { raised })
    assert.equal(r8.deg, 0); assert.deepEqual(r8.turns, []); assert.deepEqual(r8.points, alongX(4))
  }
  ok('[8] bendLimitsOf, and limit 0 = no turn')
}
// [9]–[10] THE ROOT ANGLE (A158)
{
  const F = { side: [1, 0, 0], up: [0, 1, 0] }
  const sin = (d) => Math.sin(d * DEG), cos = (d) => Math.cos(d * DEG)
  const two = alongZ(2, 0.1)
  const tip = (a) => SR.rootTurnOf(two, F, a).points[2]
  close(tip({ pitchDeg: 30, yawDeg: 0 }), [0, 0.1, 0.2 * cos(30)], 1e-9, '[9] pitch +30 up')
  close(tip({ pitchDeg: -30, yawDeg: 0 }), [0, -0.1, 0.2 * cos(30)], 1e-9, '[9] pitch -30 down')
  close(tip({ pitchDeg: 0, yawDeg: 15 }), [-0.2 * sin(15), 0, 0.2 * cos(15)], 1e-9, '[9] yaw +15 right')
  close(tip({ pitchDeg: 0, yawDeg: -15 }), [0.2 * sin(15), 0, 0.2 * cos(15)], 1e-9, '[9] yaw -15 left')
  close(SR.rootTurnOf(two, F, { pitchDeg: 30, yawDeg: 0 }).points[1], [0, 0.05, 0.1 * cos(30)], 1e-9, '[9] middle')
  close(SR.rootTurnOf(two, F, { pitchDeg: 30, yawDeg: 0 }).points[0], [0, 0, 0], 1e-9, '[9] P_0 stays')
  near(tip({ pitchDeg: 70, yawDeg: 0 })[1], 0.2 * sin(60), 1e-9, '[9] clamped at 60')
  assert.equal(SR.rootTurnOf(two, F, { pitchDeg: 0, yawDeg: 0 }), null)
  const hang = [[0, 0, 0], [0, -0.1, 0], [0, -0.2, 0]]
  close(SR.rootTurnOf(hang, F, { pitchDeg: 30, yawDeg: 0 }).points[2], [0, -0.2 * cos(30), 0.1], 1e-9, '[9] hanging swings forward')
  const bf = SR.bodyFrameOf([0, 1, 0], [0, 1.1, 0.02], [0.1, 0.95, 0], [-0.1, 0.95, 0])
  close(bf.side, [1, 0, 0], 1e-9, '[9] body side'); close(bf.up, [0, 0.1 / Math.hypot(0.1, 0.02), 0.02 / Math.hypot(0.1, 0.02)], 1e-9, '[9] body up')
  assert.deepEqual(SR.rootAngleOf({ pitch_deg: 20, yaw_deg: -5 }), { pitchDeg: 20, yawDeg: -5 })   // [10]
  assert.deepEqual(SR.rootAngleOf('junk'), { pitchDeg: 0, yawDeg: 0 })
  ok('[9]–[10] the root angle')
}
// [11] composition on real bones
{
  const defaults = { freq_hz: 2, zeta: 1, gravity: 0, gravity_scale: 1, gain: 0,
    max_deg: 25, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
    flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
    squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90, straighten_deg: 0, freetext_clothing_gain: 1 }
  const reader = () => {
    const root = new THREE.Group()
    const bones = []
    const bone = (name, parent, at) => { const b = new THREE.Bone(); b.name = `mixamorig:${name}`; b.position.set(...at)
      ;(parent ?? root).add(b); bones.push(b); return b }
    const hips = bone('Hips', null, [0, 0, 0])
    const chain = []
    let parent = hips
    for (let j = 0; j < 3; j++) { parent = bone(`A${j + 1}`, parent, j ? [0, 0, 0.1] : [0, 0, 0]); chain.push(parent) }
    const positions = [], skinIndex = [], skinWeight = []
    chain.forEach((b, j) => { for (const dz of [0, 0.1]) { positions.push(0, 0, 0.1 * j + dz); skinIndex.push(bones.indexOf(b), 0, 0, 0); skinWeight.push(1, 0, 0, 0) } })
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(skinIndex, 4))
    geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(skinWeight, 4))
    const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
    root.add(mesh); root.updateMatrixWorld(true)
    mesh.bind(new THREE.Skeleton(bones))
    const motion = SR.createSecondaryMotion(THREE, root, { rev: 'g', groups: { g: { ...defaults,
      bones: chain.map((b) => b.name.replace('mixamorig:', '')), op: 'appendage_chain' } } })
    motion.update(1 / 60, {})
    return motion
  }
  const pointsOf = (m) => { const segs = m.opChains()[0].segments; return [...segs.map((s) => s.a), segs[segs.length - 1].b] }
  const run = (withRoot, withBend) => {
    const m = reader()
    const P = pointsOf(m)
    close(P[3], [0, 0, 0.3], 1e-6, '[11] bind tip')
    let bend = null
    if (withRoot) {
      const got = SR.rootTurnOf(P, { side: [1, 0, 0], up: [0, 1, 0] }, { pitchDeg: 20, yawDeg: 0 })
      m.bendChain(0, [{ joint: 0, q: got.q }])
      pointsOf(m).forEach((p, k) => close(p, got.points[k], 1e-6, `[11a] P_${k} = rootTurnOf`))
    }
    if (withBend) {
      bend = SR.solveChainBend(pointsOf(m), [0, 0.02, 0.2819078], [0, 0, 1], 45)
      m.bendChain(0, bend.turns)
    }
    return { pts: pointsOf(m), bend }
  }
  const root = run(true, false).pts
  close(root[3], [0, 0.1026060, 0.2819078], 1e-6, '[11a] root angle tip')
  const both = run(true, true)
  near(both.bend.deg, 16.17745, 1e-3, '[11b] the bend turn')
  close(both.pts[3], [0, 0.02, 0.2993326], 1e-6, '[11b] composed tip')
  both.pts.forEach((p, k) => close(p, both.bend.points[k], 1e-6, `[11b] bones = solve P_${k}`))
  near(kink(both.pts), 0, 1e-3, '[11b] kink')
  // the bend's own turn on the STRAIGHT chain (what "replacing" the root angle would render)
  const q = both.bend.turns[0].q
  const repl = SR.quatRotate(q, [0, 0, 0.3])
  close(repl, [0, -0.0835839, 0.2881210], 1e-6, '[11] the replacing alternative')
  assert.ok(Math.hypot(...sub(both.pts[3], repl)) > 0.05 && Math.hypot(...sub(both.pts[3], root[3])) > 0.05, '[11] neither one wins')
  ok(`[11] root angle 20° then bend ${both.bend.deg.toFixed(3)}° compose on the bones: tip (0, 0.0200, 0.2993)`)
}
// [12] the hand case of the distribution (r = 0)
{
  const f = (ph) => 0.03 * [1, 2, 3, 4].reduce((a, k) => a + Math.sin(k * ph), 0) - 0.01
  let lo = 0, hi = 0.2
  for (let i = 0; i < 80; i++) { const m = (lo + hi) / 2; if (f(m) < 0) lo = m; else hi = m }
  const ph = lo
  near(ph / DEG, 1.91341, 1e-4, '[12] the hand value φ')
  const r = SR.solveChainBend(alongX(4), [0.12, 0.01, 0], [1, 0, 0], 120, { raised: 0 })
  near(r.deg, 4 * ph / DEG, 1e-5, '[12] total 4φ'); near(r.rootDeg, ph / DEG, 1e-5, '[12] root φ'); near(r.innerDeg, 3 * ph / DEG, 1e-5, '[12] inner 3φ')
  assert.deepEqual(r.turns.map((x) => x.joint), [0, 1, 2, 3])
  r.turns.forEach((x) => near(SR.quatAngle(x.q) / DEG, ph / DEG, 1e-5, `[12] joint ${x.joint} angle`))
  for (let m = 1; m <= 4; m++) {
    let x = 0, y = 0
    for (let k = 1; k <= m; k++) { x += 0.03 * Math.cos(k * ph); y += 0.03 * Math.sin(k * ph) }
    close(r.points[m], [x, y, 0], 1e-6, `[12] P_${m}`)
  }
  near(r.points[4][1], 0.01, 1e-7, '[12] tip on the line'); near(kink(r.points), ph / DEG, 1e-4, '[12] kink φ')
  assert.equal(r.atLimit, false)
  ok(`[12] resting: every joint ${(ph / DEG).toFixed(5)}°, total ${r.deg.toFixed(5)}° (root alone 4.78019°)`)
}
// [13] the budget split at r = 0.5, and the clamp at r = 0
{
  const C = [0.625, 0.75, 0.875, 1]
  const f = (th) => 0.03 * C.reduce((a, c) => a + Math.sin(c * th), 0) - 0.01
  let lo = 0, hi = 0.3
  for (let i = 0; i < 80; i++) { const m = (lo + hi) / 2; if (f(m) < 0) lo = m; else hi = m }
  near(lo / DEG, 5.88392, 1e-4, '[13a] the hand value Θ')
  const a = SR.solveChainBend(alongX(4), [0.12, 0.01, 0], [1, 0, 0], SR.bendLimitAt(D, 0.5), { raised: 0.5 })
  near(a.deg, lo / DEG, 1e-5, '[13a] total Θ'); near(a.innerDeg, 0.375 * lo / DEG, 1e-5, '[13a] inner 0.375Θ')
  assert.ok(a.innerDeg <= 0.5 * a.limitDeg, '[13a] inner ≤ ½ L'); near(a.limitDeg, 67.5, 1e-12, '[13a] L(0.5)')
  const b = SR.solveChainBend(alongX(4), [0.12, 0.05, 0], [1, 0, 0], 4, { raised: 0.5 })
  near(b.deg, 4, 1e-9, '[13b] total'); near(b.rootDeg, 2.5, 1e-9, '[13b] root'); near(b.innerDeg, 1.5, 1e-9, '[13b] inner')
  b.turns.slice(1).forEach((x) => near(SR.quatAngle(x.q) / DEG, 0.5, 1e-9, '[13b] inner joint'))
  assert.ok(b.innerDeg <= 2 && b.atLimit && SR.bendLamp(b) === 'yellow', '[13b] ≤ ½ L, yellow')
  const c = SR.solveChainBend(alongX(4), [0.12, 0.05, 0], [1, 0, 0], 4, { raised: 0 })
  c.turns.forEach((x) => near(SR.quatAngle(x.q) / DEG, 1, 1e-9, '[13c] every joint 1°'))
  near(c.innerDeg, 3, 1e-9, '[13c] inner 3')
  ok(`[13] r 0.5: Θ ${a.deg.toFixed(5)}°, inner ${a.innerDeg.toFixed(5)}°; clamped 4° → root 2.5 + inner 1.5; r 0 → 1° each`)
}
// [14] continuity in r
{
  const at = (s, raised) => {
    const pts = alongZ(4)
    return SR.bendSample({ tip: pts[4], base: pts[0], o: [0, -0.03, 0.12 - s], u: [0, 0, 1], pivot: [0, 0, 0], chain: pts,
      raised, channel: true }, D).bend
  }
  for (const s of [0, -0.06]) {
    const span = Math.abs(at(s, 0).deg - at(s, 1).deg)
    const slope = Math.max(2 * span, SR.bendGate(s) * (120 - 15))
    const sweep = (dr) => {
      let prev = null, worst = 0
      for (let i = 0; i * dr <= 1 + 1e-12; i++) {
        const raised = Math.min(1, i * dr), b = at(s, raised)
        assert.ok(b.deg <= b.limitDeg + 1e-9 && b.innerDeg <= (1 - raised) * b.limitDeg + 1e-9, `[14] budget r ${raised}`)
        if (prev !== null) worst = Math.max(worst, Math.abs(b.deg - prev))
        prev = b.deg
      }
      return worst
    }
    const a = sweep(0.01), b = sweep(0.005)
    assert.ok(a <= slope * 0.01 + 1e-6 && b <= slope * 0.005 + 1e-6, `[14] s ${s}: steps ${a} / ${b} (span ${span})`)
    assert.ok(b / a <= 0.6, `[14] s ${s}: halving ${a} → ${b}`)
    near(at(s, 1 - 1e-9).deg, at(s, 1).deg, 1e-4, `[14] s ${s}: r → 1 meets the root-only code`)
    ok(`[14] continuous in r at s_tip ${s}: span ${span.toFixed(3)}°, largest step ${a.toFixed(4)}° / 0.01, ${b.toFixed(4)}° / 0.005`)
  }
}
// [15] the rigid tail has no joint of its own
{
  const defaults = { freq_hz: 2, zeta: 1, gravity: 0, gravity_scale: 1, gain: 0,
    max_deg: 25, sag_max_deg: 0, spill_max_deg: 0, head_sag: 1, axis_gain: [1, 1, 1],
    flatten: 0, stretch: 0, spread: 0, flatten_floor: 1, spill: 0, translate: 0,
    squash: [1, 1], length: 1, girth: 1, rest_deg: 0, rest_max_deg: 90, straighten_deg: 0, freetext_clothing_gain: 1 }
  const root = new THREE.Group()
  const bones = []
  const bone = (name, parent, at) => { const b = new THREE.Bone(); b.name = `mixamorig:${name}`; b.position.set(...at)
    ;(parent ?? root).add(b); bones.push(b); return b }
  const hips = bone('Hips', null, [0, 0, 0])
  const chain = []
  let parent = hips
  for (let j = 0; j < 4; j++) { parent = bone(`A${j + 1}`, parent, j ? [0, 0, 0.1] : [0, 0, 0]); chain.push(parent) }
  const positions = [], skinIndex = [], skinWeight = []
  chain.forEach((b, j) => { for (const dz of [0, 0.1]) { positions.push(0, 0, 0.1 * j + dz); skinIndex.push(bones.indexOf(b), 0, 0, 0); skinWeight.push(1, 0, 0, 0) } })
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(skinIndex, 4))
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(skinWeight, 4))
  const mesh = new THREE.SkinnedMesh(geo, new THREE.MeshBasicMaterial())
  root.add(mesh); root.updateMatrixWorld(true)
  mesh.bind(new THREE.Skeleton(bones))
  const m = SR.createSecondaryMotion(THREE, root, { rev: 'g', groups: { g: { ...defaults, rigid_tail: 1,
    bones: chain.map((b) => b.name.replace('mixamorig:', '')), op: 'appendage_chain' } } })
  m.update(1 / 60, {})
  const pointsOf = () => { const segs = m.opChains()[0].segments; return [...segs.map((x) => x.a), segs[segs.length - 1].b] }
  const P = pointsOf()
  assert.equal(P.length, 4, '[15] three segments'); close(P[3], [0, 0, 0.3], 1e-6, '[15] P_3 = A4 head')
  const bend = SR.solveChainBend(P, [0, 0.02, 0.3], [0, 0, 1], 120, { raised: 0 })
  assert.deepEqual(bend.turns.map((x) => x.joint), [0, 1, 2])
  const q4 = chain[3].quaternion.clone()
  m.bendChain(0, bend.turns)
  pointsOf().forEach((p, k) => close(p, bend.points[k], 1e-6, `[15] bones = solve P_${k}`))
  near(chain[3].quaternion.angleTo(q4), 0, 1e-9, '[15] A4 keeps its local rotation')
  ok(`[15] rigid tail: joints [0, 1, 2] turn (${bend.deg.toFixed(3)}° in all), the tail link rides on A3`)
}
console.log(`smoke_chain_bend OK (${passed} checks)`)
