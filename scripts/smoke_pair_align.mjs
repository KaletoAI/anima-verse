#!/usr/bin/env node
/**
 * Ruling A212, the owner's procedure of 2026-11-20: the TWO-KEY-FRAME Auto-align of
 * `packages/scene-render/src/pairAlign.ts` (solveAlign, alignByPasses, keyReport, keyLamp). Every expected number is
 * derived BY HAND below (§ B5a), never recorded from a run.
 *
 * Usage: node scripts/smoke_pair_align.mjs   (no server, no world; bundles scene-render with esbuild)
 *
 * FIXTURE (metres, degrees). The moving figure's clip frame is turned 30° about +Y: basis B with the columns
 *   side = (cos 30°, 0, −sin 30°), up = (0, 1, 0), forward = (sin 30°, 0, cos 30°); the body axes (root angle) are
 *   side/up, the partner's tilt/roll axes side/forward. The channel: opening O = (0, 0.9, 0.4), axis
 *   u = B·(0, −sin 15°, cos 15°), depth 0.15, the tip's radius 0.015 → the bottom condition s_tip ≤ 0.135.
 *   The part: 4 links of 0.03 (L = 0.12), raised 1. Its RAW direction (root angle 0/0) is d₀ = q(A*)⁻¹·u for the
 *   CORRECT root angle A* = (pitch 12°, yaw −5°), q = rootTurnQuat(body, ·) — so the part rendered with A* points along u.
 *   8 frames φ = k/8: tip s(φ) = 0.03 + 0.035·(1 − cos 2πφ) (shallow φ = 0: s = 0.03, deep φ = ½: s = 0.10), the
 *   root P_0 = O + (s − L)·u (deep: s_root = −0.02, outside), the chain P_k = P_0 + 0.03·k·q(A)·d₀, the pivot (hips)
 *   P_0 + B·(0, 0.1, −0.1). A misplacement by a partner shift e is P ↦ P + B·e for every point and the pivot.
 *   Cap: alignCap() = side 3 cm, up/forward 8 cm, tilt/roll 10°; root ranges ±60° / ±30°.
 *   [1] RECOVERY: measured with the root angle A_m = (4°, 3°) (error −8° / +8°) and the partner shift
 *       e = (2, 3 cos 15°, 3 sin 15°) cm = (2, 2.8978, 0.7765) cm (B·e ⊥ u: a misplacement ACROSS the axis — along u
 *       no lateral residual can see it, and none should). The unique zero of the lateral residuals: x = −e (the root
 *       joint back on the axis line at both key frames needs the shift; its across-axis part is 2-dimensional and so is
 *       −B·e) and the root angle A* (the shaft along u), tilt/roll 0 (the null direction: the ridge keeps them).
 *       Expect |x − (−e)| < 1 mm, |root − A*| < 0.2°, |tilt|, |roll| < 0.2°; the report after (moveSample with the
 *       solution): root and tip off axis < 0.1 mm at both key frames, shaft 0° (< 0.05°), lamp green, no hits.
 *       TWO RELATIONS on the same figure (a second, unrooted chain whose correct stroke lies on a second axis through
 *       O₂ = O + B·(0.08, 0.05, 0), measured with the same e; it sees the shift only): the same answer.
 *   [2] A CORRECT STROKE THAT NEVER FULLY LEAVES (s_min = +3 cm) is NOT moved: measured at A* and e = 0 every residual
 *       is 0 and no inequality is violated (deep: s_tip 0.10 ∈ (0.002, 0.133), s_root −0.02 < −0.002) → |x| < 0.1 mm,
 *       root moved < 0.01°, tilt/roll < 0.01°. (The old ENTRY term pushed such a stroke 2.9 cm along the axis.)
 *   [3] ROOT INSIDE AT THE DEEP FRAME: the correct stroke moved 3 cm along +u (deep s_tip 0.13 ≤ 0.133, s_root +0.01 —
 *       inside). Laterally nothing is wrong, so only the hinge max(0, s_root + 0.002) costs: the solve moves the figure
 *       along −u by exactly 0.012 → x = −0.012·(0, −sin 15°, cos 15°) = (0, 0.31058, −1.15911) cm (±0.05 mm), deep
 *       s_root −2 mm (rootOutside), s_tip 0.118; lamp green.
 *   [4] CAPS: [1] with e = (5, 0, 0) cm: side needs −5 cm, the cap stops it at −3 cm → hits ∋ 'side', lamp red. (The
 *       roll then takes what it can: about the forward axis through the hips it moves the root joint, 0.1 m below and
 *       0.1 m in front of them, sideways by 0.1·ω — the missing 2 cm need ω = 0.2 rad = 11.5° > 10°, so 'roll' is hit
 *       too.) A* = (12°, −35°) measured at (12°, 0°): the yaw needs −35°, beyond its range ±30° → hits ∋ 'yaw', red.
 *   [5] CONVERGENCE OF THE PASSES (alignByPasses): the "measured" chain carries only g = 0.85 of the root angle applied
 *       (a chain that follows its root turn only partly). The model turns the measured chain by q(new)·q(applied)⁻¹, so
 *       per pass the realised angle r obeys r_{k+1} = g·T + (1 − g)·r_k (T = A*): the error shrinks by 0.15 per pass —
 *       from 8° to 8·0.15⁴ ≈ 0.004° after four. Expect at most ALIGN_PASSES (5) passes, converged, the realised root
 *       angle g·A within 0.02° of A*, the increments shrinking (each pass's root step ≤ 0.2 × the one before, up to the
 *       ridge/Gauss–Newton tolerance), and the measured key frames green.
 *   [6] JOIN (end clips): [2]'s correct stroke, no tilt/roll axes (a group clip), the join Δ = B·(0.01, 0, 0), weight 1.
 *       Two key frames (N = 2). A side shift y (B·side ⊥ u: purely across the axis) moves root and tip alike; the root
 *       yaw turns the tip back onto the axis at both frames for nothing (the shaft's direction is the same at both), so
 *       only the root joint pays: 2 frames · y², plus the join N·(y − 0.01)² = 2(y − 0.01)² → least at y = 0.005 (±2e-5).
 *   [7] relativeOf / joinDelta: frame Ry(90°) row-major [0,0,1, 0,1,0, −1,0,0], anchor (1, 0, 2), hips (1, 0.1, 3):
 *       d = (0, 0.1, 1), frameᵀd = (−1, 0.1, 0); joinDelta of that rel from the same hips = (0, 0, 0); from hips
 *       (1, 0.1, 2.5) = (0, 0, 0.5).
 *   [8] THE RECEIVING FIGURE NEVER MOVES: hits {e 1, r 0}, {e 2, r 0}, {e 1, r 3} → alignMovers keys exactly {1, 2}.
 *   [9] keyFrames of tips s = 0.05, 0.02, 0.09, 0.02, 0.09 → deep 2 (first of the ties), shallow 1; alignCap(4) = side 3,
 *       up/forward 4 cm.
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
let n = 0
const ok = (m) => { n++; console.log(`  PASS  ${m}`) }
const D2R = Math.PI / 180
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k]
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const yaw = 30 * D2R
const B = [Math.cos(yaw), 0, Math.sin(yaw), 0, 1, 0, -Math.sin(yaw), 0, Math.cos(yaw)]
const col = (j) => [B[j], B[3 + j], B[6 + j]]
const side = col(0), up = col(1), fwd = col(2)
const Bv = (v) => add(add(mul(side, v[0]), mul(up, v[1])), mul(fwd, v[2]))
const s15 = Math.sin(15 * D2R), c15 = Math.cos(15 * D2R)
const U = Bv([0, -s15, c15])
const O1 = [0, 0.9, 0.4], O2 = add(O1, Bv([0.08, 0.05, 0]))
const body = { side, up }
const cap = SR.alignCap()
const conj = (q) => [-q[0], -q[1], -q[2], q[3]]
const L = 0.12
const sOf = (ph) => 0.03 + 0.035 * (1 - Math.cos(2 * Math.PI * ph))
/** The stroke: correct root angle aStar, rendered with aShown (realised share g), misplaced by e, moved along u. */
const stroke = ({ O = O1, aStar = { pitchDeg: 12, yawDeg: -5 }, aShown = aStar, g = 1, e = [0, 0, 0], along = 0, rooted = true } = {}) => {
  const d0 = rooted ? SR.quatRotate(conj(SR.rootTurnQuat(body, aStar)), U) : U
  const shown = { pitchDeg: g * aShown.pitchDeg, yawDeg: g * aShown.yawDeg }
  const d = rooted ? SR.quatRotate(SR.rootTurnQuat(body, shown), d0) : U
  return Array.from({ length: 8 }, (_, k) => {
    const ph = k / 8, s = sOf(ph) + along
    const p0 = add(add(O, mul(U, s - L)), Bv(e))
    const chain = Array.from({ length: 5 }, (_, j) => add(p0, mul(d, 0.03 * j)))
    return { tip: chain[4], base: chain[0], chain, o: O, u: U, pivot: add(p0, Bv([0, 0.1, -0.1])), raised: 1, channel: true,
      body, depthM: 0.15, tipRadiusM: 0.015, phase: ph }
  })
}
const problem = (relations, root, extra = {}) => ({ relations, basis: B, axes: [side, fwd], cap, root, ...extra })
const after = (samples, sol, from) => samples.map((s) => SR.moveSample(s, sol.fix, from, sol.root))
const e1 = [0.02, 0.03 * c15, 0.03 * s15]
const AM = { pitchDeg: 4, yawDeg: 3 }

{ // [1]
  const meas = stroke({ aShown: AM, e: e1 })
  const sol = SR.solveAlign(problem([{ samples: meas, rooted: true }], AM))
  const dx = Math.hypot(...sub(sol.x, mul(e1, -1)))
  assert.ok(dx < 1e-3, `[1] x off by ${dx}`)
  near(sol.root.pitchDeg, 12, 0.2, '[1] pitch'); near(sol.root.yawDeg, -5, 0.2, '[1] yaw')
  near(sol.deg[0], 0, 0.2, '[1] tilt'); near(sol.deg[1], 0, 0.2, '[1] roll')
  assert.deepEqual(sol.hits, [])
  const rep = SR.keyReport(after(meas, sol, AM))
  for (const r of [rep.deep, rep.shallow]) {
    assert.ok(r.rootOffMm < 0.1 && r.tipOffMm < 0.1, `[1] off axis ${r.rootOffMm} / ${r.tipOffMm}`)
    assert.ok(r.shaftDeg < 0.05, `[1] shaft ${r.shaftDeg}`)
  }
  assert.equal(rep.deep.index, 4); assert.equal(rep.shallow.index, 0)
  assert.equal(SR.keyLamp(rep, sol.hits, true), 'green')
  ok(`[1] recovery: x error ${(dx * 1000).toFixed(4)} mm, root ${sol.root.pitchDeg.toFixed(4)}° / ${sol.root.yawDeg.toFixed(4)}°, tilt/roll ${sol.deg.map((v) => v.toFixed(4)).join(' / ')}°`)
  const meas2 = stroke({ O: O2, e: e1, rooted: false })
  const two = SR.solveAlign(problem([{ samples: meas, rooted: true }, { samples: meas2 }], AM))
  const dx2 = Math.hypot(...sub(two.x, mul(e1, -1)))
  assert.ok(dx2 < 1e-3, `[1] two relations x off by ${dx2}`)
  near(two.root.pitchDeg, 12, 0.2, '[1] two pitch'); near(two.root.yawDeg, -5, 0.2, '[1] two yaw')
  ok(`[1] two relations: x error ${(dx2 * 1000).toFixed(4)} mm, root ${two.root.pitchDeg.toFixed(4)}° / ${two.root.yawDeg.toFixed(4)}°`)
}
{ // [2]
  const A = { pitchDeg: 12, yawDeg: -5 }
  const sol = SR.solveAlign(problem([{ samples: stroke(), rooted: true }], A))
  assert.ok(Math.hypot(...sol.x) < 1e-4, `[2] moved ${sol.x}`)
  assert.ok(Math.abs(sol.root.pitchDeg - 12) < 0.01 && Math.abs(sol.root.yawDeg + 5) < 0.01, '[2] root')
  assert.ok(sol.deg.every((v) => Math.abs(v) < 0.01), '[2] tilt/roll')
  ok(`[2] a correct stroke (s_min +3 cm) stays: |x| = ${(Math.hypot(...sol.x) * 1000).toExponential(2)} mm`)
}
{ // [3]
  const A = { pitchDeg: 12, yawDeg: -5 }
  const meas = stroke({ along: 0.03 })
  const before = SR.keyReport(meas)
  assert.equal(before.deep.rootOutside, false)
  const sol = SR.solveAlign(problem([{ samples: meas, rooted: true }], A))
  ;[0, 0.012 * s15, -0.012 * c15].forEach((v, i) => near(sol.x[i], v, 5e-5, `[3] x[${i}]`))
  const rep = SR.keyReport(after(meas, sol, A))
  near(rep.deep.rootDepthMm, -2, 0.05, '[3] root depth'); near(rep.deep.depthMm, 118, 0.05, '[3] tip depth')
  assert.equal(rep.deep.rootOutside, true)
  assert.equal(SR.keyLamp(rep, sol.hits, true), 'green')
  ok(`[3] root inside pushed out: x = ${sol.x.map((v) => (v * 100).toFixed(4)).join(' / ')} cm, root at ${rep.deep.rootDepthMm.toFixed(3)} mm`)
}
{ // [4]
  const meas = stroke({ aShown: AM, e: [0.05, 0, 0] })
  const sol = SR.solveAlign(problem([{ samples: meas, rooted: true }], AM))
  assert.ok(sol.hits.includes('side') && sol.hits.includes('roll'), `[4] hits ${sol.hits}`); near(sol.x[0], -0.03, 1e-9, '[4] side on its cap')
  assert.equal(SR.keyLamp(SR.keyReport(after(meas, sol, AM)), sol.hits, true), 'red')
  const aStar = { pitchDeg: 12, yawDeg: -35 }, a0 = { pitchDeg: 12, yawDeg: 0 }
  const m2 = stroke({ aStar, aShown: a0 })
  const s2 = SR.solveAlign(problem([{ samples: m2, rooted: true }], a0))
  assert.ok(s2.hits.includes('yaw'), `[4] hits ${s2.hits}`); near(s2.root.yawDeg, -30, 1e-9, '[4] yaw on its range')
  assert.equal(SR.keyLamp(SR.keyReport(after(m2, s2, a0)), s2.hits, true), 'red')
  ok(`[4] caps hit → red and named: [${sol.hits}] and [${s2.hits}]`)
}
{ // [5]
  const g = 0.85, aStar = { pitchDeg: 12, yawDeg: -5 }
  const measure = (st) => ({ relations: [{ samples: stroke({ aStar, aShown: st.root, g, e: mul(e1, 1).map((v, i) => v + st.x[i]) }), rooted: true }], basis: B })
  const run = SR.alignByPasses(measure, { axes: [side, fwd], cap }, { x: [0, 0, 0], deg: [0, 0], root: AM })
  assert.ok(run.converged, 'converged'); assert.ok(run.trace.length <= SR.ALIGN_PASSES, 'passes')
  near(g * run.state.root.pitchDeg, 12, 0.02, '[5] realised pitch'); near(g * run.state.root.yawDeg, -5, 0.02, '[5] realised yaw')
  for (let k = 2; k < run.trace.length; k++) assert.ok(run.trace[k].rootDeg <= 0.2 * run.trace[k - 1].rootDeg + 2e-3, `[5] shrink ${k}`)
  const rep = SR.keyReport(run.last.relations[0].samples)
  assert.equal(SR.keyLamp(rep, run.sol.hits, true), 'green')
  ok(`[5] passes converge: root steps ${run.trace.map((t) => t.rootDeg.toFixed(4)).join(' → ')}°, shift steps ${run.trace.map((t) => t.shiftMm.toFixed(3)).join(' → ')} mm`)
}
{ // [6]
  const A = { pitchDeg: 12, yawDeg: -5 }
  const sol = SR.solveAlign(problem([{ samples: stroke(), rooted: true }], A, { axes: [], join: { deltaM: Bv([0.01, 0, 0]) } }))
  near(sol.x[0], 0.005, 2e-5, '[6] join side')
  ok(`[6] the join to the base end pose: side ${(sol.x[0] * 1000).toFixed(4)} mm`)
}
{ // [7]
  const F = [0, 0, 1, 0, 1, 0, -1, 0, 0]
  const rv = SR.relativeOf(F, [1, 0.1, 3], [1, 0, 2])
  ;[-1, 0.1, 0].forEach((v, i) => near(rv[i], v, 1e-12, '[7] rel'))
  SR.joinDelta(F, rv, [1, 0.1, 3], [1, 0, 2]).forEach((v) => near(v, 0, 1e-12, '[7] join 0'))
  const j = SR.joinDelta(F, rv, [1, 0.1, 2.5], [1, 0, 2]); [0, 0, 0.5].forEach((v, i) => near(j[i], v, 1e-12, '[7] join'))
  ok('[7] relativeOf / joinDelta')
}
{ // [8]
  const m = SR.alignMovers([{ e: 1, r: 0 }, { e: 2, r: 0 }, { e: 1, r: 3 }])
  assert.deepEqual([...m.keys()].sort(), [1, 2]); assert.equal(m.get(1).length, 2)
  ok('[8] only the figures with the attached part move')
}
{ // [9]
  const k = SR.keyFrames([0.05, 0.02, 0.09, 0.02, 0.09].map((s) => ({ tip: [0, 0, s], o: [0, 0, 0], u: [0, 0, 1] })))
  assert.deepEqual(k, { deep: 2, shallow: 1 })
  const c4 = SR.alignCap(4)
  near(c4.sideM, 0.03, 1e-12, '[9] side'); near(c4.upM, 0.04, 1e-12, '[9] up'); near(c4.forwardM, 0.04, 1e-12, '[9] fwd')
  ok('[9] key frames and the cap of a 4 cm range')
}
console.log(`\n${n}/10 checks passed`)
