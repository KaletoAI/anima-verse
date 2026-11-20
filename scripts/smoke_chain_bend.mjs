#!/usr/bin/env node
/**
 * Ruling A145, root-only (2026-11-20): the attached part turns at its ROOT toward its contact target once the tip is
 * near the opening; the shaft stays rigid (`packages/scene-render/src/chainBend.ts`, `pairFit.ts` bendSample). Auto-align
 * is rigid (`smoke_pair_align.mjs`). Every expected number is derived BY HAND below (§ B5a).
 *
 * Usage: node scripts/smoke_chain_bend.mjs   (no server, no world; bundles scene-render with esbuild, imports three)
 *
 * Chains below: S(n, a) = a straight chain P_k = a·k·(direction), k 0 … n, P_0 at the origin; L = n·a its length.
 * [1] bendLimitAt: raised 1 → 15° / 35°; raised 0 → 45° / 120°; raised 0.5 → 30° / 77.5° (linear). The ROOT limit is
 *     min(jointDeg, totalDeg): 15 (raised), 45 (resting), 30 (half); {jointDeg 50, totalDeg 20} → 20; negative → 0.
 * [2] bendGate(s) = clamp((s + 0.08) / 0.05, 0, 1): s −0.10 → 0, −0.08 → 0, −0.055 → 0.5, −0.03 → 1, 0 → 1, +0.02 → 1.
 * [3] THE HAND CASE: S(4, 0.03) along +x (L = 0.12), a POINT target (no joint effectors), axis u = +x, the line
 *     parallel at lateral offset d = 0.01 (o = (L, 0.01, 0), so s_tip = 0, gate 1). A root turn θ about P_0 puts the
 *     tip at (L cos θ, L sin θ, 0); on the line when L sin θ = d → θ = asin(d / L) = asin(1/12) = 4.78019°, tip
 *     (0.1195818, 0.01, 0). Every point turns rigidly: P_k = 0.03k (cos θ, sin θ, 0) — the angle between neighbouring
 *     links (the KINK) is 0 at every inner joint. turns = [{joint 0}] exactly; raised limit 15 → not at the limit,
 *     green.
 * [4] THE CLAMP: the same with d = 0.05 → wanted asin(0.05/0.12) = 24.6243°; raised limit 15° → the turn is exactly
 *     15° about the same axis (+z): tip (L cos 15°, L sin 15°, 0) = (0.1159111, 0.0310583, 0); at the limit → yellow.
 * [5] THE F1 CASES (Ruling A145 diagnosis): S(4, 0.03) along +z, a CHANNEL with u = +z, 1 cm off-axis (line at
 *     y = −0.01), the tip at s_tip = −0.30, −0.10, −0.04, 0 (o = (0, −0.01, L − s_tip)), raised 1 and 0.
 *     s_tip −0.30, −0.10: gate 0 → no turn at all (deg 0, chain unchanged). s_tip −0.04: gate 0.8, limit 12° / 36°.
 *     The joint weights w_k = clamp(1 + s_k / 0.03, 0, 1) with s_k = s_tip − 0.03(4 − k): at s_tip −0.04 and 0 every
 *     joint has s_k ≤ −0.03 → w 0, the tip alone → θ = asin(0.01/0.12) = 4.78019° (both states, under the limit).
 *     Kink at every inner joint 0 (the old solve kinked the tip joint by 15–18° here).
 * [6] CONTINUITY: S(4, 0.03) along +z, channel, line at y = −0.03, s_tip swept −0.10 … +0.02 in steps of 0.5 mm and of
 *     0.25 mm, raised 1 and 0. The gated limit has slope maxDeg / 0.05 m (resting 45/50 = 0.9°/mm, raised 0.3°/mm);
 *     the unclamped turn moves slower (each joint weight ramps over 30 mm). So no step between neighbouring samples
 *     exceeds 1.0°/mm × the spacing, and halving the spacing halves the largest step (ratio ≤ 0.6). (The old solve
 *     jumped 17° → 32° at s_tip = −0.03.)
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
 * [8] bendLimitsOf({raised: {joint_deg: 10}}) → raised 10 / 35 (total from the default), resting 45 / 120; junk →
 *     defaults. Limit 0 → no turn at all.
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
assert.deepEqual(SR.bendLimitAt(D, 1), { jointDeg: 15, totalDeg: 35 })
assert.deepEqual(SR.bendLimitAt(D, 0), { jointDeg: 45, totalDeg: 120 })
assert.deepEqual(SR.bendLimitAt(D, 0.5), { jointDeg: 30, totalDeg: 77.5 })
assert.equal(SR.rootBendLimitDeg(SR.bendLimitAt(D, 1)), 15); assert.equal(SR.rootBendLimitDeg(SR.bendLimitAt(D, 0)), 45)
assert.equal(SR.rootBendLimitDeg(SR.bendLimitAt(D, 0.5)), 30)
assert.equal(SR.rootBendLimitDeg({ jointDeg: 50, totalDeg: 20 }), 20); assert.equal(SR.rootBendLimitDeg({ jointDeg: -5, totalDeg: 20 }), 0)
ok('[1] limits and the root limit min(joint, total)')
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
  assert.equal(r.atLimit, false); assert.equal(SR.bendLamp(r), 'green')
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
    const want = s <= -0.08 ? 0 : 4.78019
    near(bend.deg, want, 1e-4, `[5] raised ${raised} s ${s}`)
    near(kink(sample.chain), 0, 1e-4, `[5] kink raised ${raised} s ${s}`)
    if (want === 0) assert.deepEqual(sample.chain, pts)
    rows.push(`${s * 100}cm:${bend.deg.toFixed(2)}°`)
  }
  ok(`[5] F1 cases, root turn ${rows.slice(0, 4).join(' ')} (both states), kink 0`)
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
      if (prev !== null) worst = Math.max(worst, Math.abs(b.deg - prev))
      prev = b.deg
    }
    return worst
  }
  for (const raised of [1, 0]) {
    const a = sweep(raised, 0.0005), b = sweep(raised, 0.00025)
    assert.ok(a <= 1.0 * 0.5, `[6] raised ${raised}: step ${a}° per 0.5 mm`)
    assert.ok(b <= 1.0 * 0.25, `[6] raised ${raised}: step ${b}° per 0.25 mm`)
    assert.ok(b / a <= 0.6, `[6] raised ${raised}: halving the spacing ${a} → ${b}`)
    ok(`[6] continuous, raised ${raised}: largest step ${a.toFixed(3)}° / 0.5 mm, ${b.toFixed(3)}° / 0.25 mm`)
  }
}
// [7]
{
  const u = [0, -Math.sin(10 * DEG), Math.cos(10 * DEG)], o = u.map((v) => 0.09 * v)
  const r = SR.solveChainBend(alongZ(4), o, u, { jointDeg: 45, totalDeg: 120 }, { channel: true })
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
  const r = SR.solveChainBend(alongZ(4), o, u, { jointDeg: 45, totalDeg: 120 }, { channel: true })
  near(r.deg, want, 0.01, '[7b] weighted fixed point'); near(kink(r.points), 0, 1e-4, '[7b] kink')
  assert.ok(r.deg > 4.79 && lat(r.points[4], o, u) > 1e-4, '[7b] a compromise, not the tip alone')
  ok(`[7b] the joints near/inside weigh in: ${r.deg.toFixed(4)}° (equation ${want.toFixed(4)}°)`)
}
// [8]
{
  const L8 = SR.bendLimitsOf({ raised: { joint_deg: 10 } })
  assert.deepEqual(L8, { raised: { jointDeg: 10, totalDeg: 35 }, resting: { jointDeg: 45, totalDeg: 120 } })
  assert.deepEqual(SR.bendLimitsOf('junk'), D)
  const r8 = SR.solveChainBend(alongX(4), [0.12, 0.05, 0], [1, 0, 0], { jointDeg: 0, totalDeg: 0 })
  assert.equal(r8.deg, 0); assert.deepEqual(r8.turns, []); assert.deepEqual(r8.points, alongX(4))
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
      bend = SR.solveChainBend(pointsOf(m), [0, 0.02, 0.2819078], [0, 0, 1], { jointDeg: 45, totalDeg: 120 })
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
console.log(`smoke_chain_bend OK (${passed} checks)`)
