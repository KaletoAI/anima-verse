#!/usr/bin/env node
/**
 * Ruling A212, the owner's procedure of 2026-11-20 and the objective of 2026-11-22: the TWO-KEY-FRAME Auto-align of
 * `packages/scene-render/src/pairAlign.ts` (solveAlign, alignByPasses, keyReport, keyLamp, keyReasons). Every expected
 * number is derived BY HAND below (§ B5a), never recorded from a run.
 *
 * THE OBJECTIVE (pairAlign THE RESIDUALS): at both key frames the shaft line's offset at the opening plane and the
 *   angle's lever L·(d − u) (L = 0.1 m); at the deep frame the DEPTH TARGET s_root* = min(−m, (depth − r_tip) − m −
 *   (s_tip − s_root)), m = 0.002. Every stroke below has its shaft 0.12 m long ALONG its direction and a channel of
 *   depth 0.15 with r_tip 0.015, so (depth − r_tip) − m − 0.12 = 0.135 − 0.002 − 0.12 = +0.013 > −0.002: the ROOT binds,
 *   s_root* = −0.002 (the root joint 2 mm in front of the opening, the tip 0.118 inside).
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
 *       −B·e) and the root angle A* (the shaft along u), tilt/roll 0 (the null direction: the ridge keeps them). ALONG
 *       the axis the depth target decides: the deep root sits at s = −0.02 and goes to −0.002, i.e. the figure moves
 *       0.018 along +u: x = −e + 0.018·(0, −sin 15°, cos 15°) = (−2, −2.8978 − 0.4659, −0.7765 + 1.7387) cm =
 *       (−2, −3.3637, 0.9622) cm (B·(0, −sin 15°, cos 15°) = u). Expect |x − that| < 1 mm, |root − A*| < 0.2°,
 *       |tilt|, |roll| < 0.2°; the report after (moveSample with the solution): root and tip off axis < 0.1 mm at both
 *       key frames, shaft 0° (< 0.05°), the deep root at −2 mm (±0.05) and the tip at 118 mm, lamp green, no hits.
 *       TWO RELATIONS on the same figure (a second, unrooted chain whose correct stroke lies on a second axis through
 *       O₂ = O + B·(0.08, 0.05, 0), measured with the same e and the same stroke depths; it sees the shift only): the
 *       same answer.
 *   [2] A CORRECT LINE, A SHALLOW STROKE (deep s_tip 0.10, s_root −0.02) goes to FULL DEPTH: measured at A* and e = 0
 *       the axis error is 0 at both frames; only the depth target costs, 0.018 along +u → x = 0.018·(0, −sin 15°,
 *       cos 15°) = (0, −0.46587, 1.73867) cm (±0.05 mm), root moved < 0.01°, tilt/roll < 0.01°; deep root −2 mm. (The
 *       objective of 2026-11-20 left such a stroke where it was — the diagnosis of 2026-11-21.)
 *   [3] ROOT INSIDE AT THE DEEP FRAME: the correct stroke moved 3 cm along +u (deep s_tip 0.13 ≤ 0.133, s_root +0.01 —
 *       inside). Laterally nothing is wrong, so only the hinge max(0, s_root + 0.002) costs: the solve moves the figure
 *       along −u by exactly 0.012 → x = −0.012·(0, −sin 15°, cos 15°) = (0, 0.31058, −1.15911) cm (±0.05 mm), deep
 *       s_root −2 mm (rootOutside), s_tip 0.118; lamp green.
 *   [4] CAPS: [1] with e = (5, 0, 0) cm: side needs −5 cm, the cap stops it at −3 cm → hits ∋ 'side', lamp red, the
 *       reasons name 'caps'. (Roll and root yaw then take what they can of the rest at the cost of the angle's lever;
 *       how much is not asserted.) A* = (12°, −35°) measured at (12°, 0°): the yaw needs −35°, beyond its range ±30° →
 *       hits ∋ 'yaw', red.
 *   [5] CONVERGENCE OF THE PASSES (alignByPasses): the "measured" chain carries only g = 0.85 of the root angle applied
 *       (a chain that follows its root turn only partly). The model turns the measured chain by q(new)·q(applied)⁻¹, so
 *       per pass the realised angle r obeys r_{k+1} = g·T + (1 − g)·r_k (T = A*): the error shrinks by 0.15 per pass —
 *       from 8° to 8·0.15⁴ ≈ 0.004° after four. Expect at most ALIGN_PASSES (5) passes, converged, the realised root
 *       angle g·A within 0.02° of A*, the increments shrinking (each pass's root step ≤ 0.2 × the one before, up to the
 *       ridge/Gauss–Newton tolerance), and the measured key frames green.
 *   [6] JOIN (end clips): [2]'s correct stroke, no tilt/roll axes (a group clip), the join Δ = B·(0.01, 0, 0), weight 1.
 *       Two key frames (N = 2). ALONG u the depth target (deep s_root −0.02 → −0.002, one frame, weight 1) and the join
 *       (which wants no shift there, weight N = 2) share: (a − 0.018)² + 2a² → a = 0.006, so the root joints stand at
 *       ρ_deep = 0.014 and ρ_shallow = 0.084 in front of the opening. ACROSS: a side shift y (B·side ⊥ u) moves the shaft
 *       line's crossing of the opening plane by y at both frames; a root yaw ψ turns the shaft about the body's up
 *       axis, up × u = cos 15°·side, so with ψ' = cos 15°·ψ (radians) the crossing moves by ρ_k·ψ' and the lever costs
 *       0.1·ψ' at both frames: cost Σ_k (y + ρ_k ψ')² + 2·(0.1ψ')² + 2(y − 0.01)². Least in ψ': ψ' = −y·Σρ/(Σρ² + 0.02)
 *       = −y·0.098/0.027252; left in y: Q·y² + 2(y − 0.01)² with Q = 2 − 0.098²/0.027252 = 1.647586 → y = 0.02/(Q + 2)
 *       = 0.0054831 (±2e-5; the small-angle steps are below 1e-6).
 *   [7] relativeOf / joinDelta: frame Ry(90°) row-major [0,0,1, 0,1,0, −1,0,0], anchor (1, 0, 2), hips (1, 0.1, 3):
 *       d = (0, 0.1, 1), frameᵀd = (−1, 0.1, 0); joinDelta of that rel from the same hips = (0, 0, 0); from hips
 *       (1, 0.1, 2.5) = (0, 0, 0.5).
 *   [8] THE RECEIVING FIGURE NEVER MOVES: hits {e 1, r 0}, {e 2, r 0}, {e 1, r 3} → alignMovers keys exactly {1, 2}.
 *   [9] keyFrames of tips s = 0.05, 0.02, 0.09, 0.02, 0.09 → deep 2 (first of the ties), shallow 1; alignCap(4) = side 3,
 *       up/forward 4 cm.
 *   [10] REAL-SHAPED: THE AXIS TURNS BETWEEN THE KEY FRAMES (the crouching-doggy capture of 2026-11-21: the receiving
 *       axis 8° apart at the deep and the shallow frame, the two axis lines crossing about 0.2 m in front of the
 *       opening, a 0.107 m part). Basis B = I (side x, up y, forward z), shift only (no root angle, no tilt/roll axes —
 *       the part's direction cannot turn), C = cos 4°, S = sin 4°. The crossing X = (0, 0.9, 0.2); the deep axis
 *       u_d = (0, S, C), the shallow u_s = (0, −S, C); the openings O_d = X + 0.2·u_d, O_s = X + 0.2·u_s; the part along
 *       m = (0, 0, 1): root X + t·m, tip X + (t + 0.107)·m, t = 0.127 at the deep frame and 0.057 at the shallow one.
 *       Measured: deep s_root = 0.127·C − 0.2 = −0.073309, s_tip = 0.234·C − 0.2 = +0.033430 (≈ the capture's +34 mm);
 *       shallow s_tip = 0.164·C − 0.2 = −0.036400. A shift (a, b, f) moves the line to X + (a, b, 0) + t·m: it crosses
 *       the deep opening plane off the axis by (a, (b − 0.2·S)/C) in magnitude (the in-plane part is (b − 0.2S)·(n − (S/C)·m)
 *       with n = (0, 1, 0), length |b − 0.2S|/C), the shallow one by (a, |b + 0.2S|/C); the lever is 0.1·2 sin 2° at
 *       both, whatever the shift. Least at a = 0, b = 0: each frame keeps 0.2·S/C = 0.2·tan 4° = 13.985 mm (no shift can
 *       put ONE line through two openings 2·0.2·S = 27.9 mm apart). Along m only the depth target counts: s_root =
 *       (0.127 + f)·C − 0.2 = −0.002 (bottom: 0.133 − 0.107·C = 0.02626 > −0.002, the root binds) → f = 0.198/C − 0.127 =
 *       0.0714835 m (< the 8 cm cap). Expect x = (0, 0, 0.07148) (±0.05 mm), deep root −2.000 mm, deep tip −2 + 107·C =
 *       104.739 mm, opening offset 13.985 mm at both key frames, lever 6.980 mm, tip inside, root outside, no hits;
 *       the reasons only 'off_axis' (13.985 > 10 → red).
 *       FAILS ON THE OLD CODE (commit 99a32b3f3a82b83faf8357d2c59058131bbb259e, root joint and tip off the LINE at both
 *       frames): the four points' line distances are |t_i|·S at their own frame (t_i along m from X), least where the
 *       points crowd X — 0.2 m in front of the opening — and only "tip inside" max(0, m − s_tip) holds the part back:
 *       it engages below s_tip = m = 2 mm and its weight (10 per metre) against a lateral slope of order S²·Σt_i
 *       (≈ 2e-3) leaves the tip at most a few hundredths of a millimetre under it: 1.9 < s_tip ≤ 2.0 mm.
 *   [11] THE RECEIVING ROLE MOVES (`mover` 'receiver'): [1]'s correct stroke moved 0.018 along +u (deep s_root =
 *       −0.002 = s*: nothing to deepen), unrooted (d = u), no root angle. The receiving figure is misplaced: its channel
 *       turned by θ = 6° about the side axis through its pivot Q = O + B·(0, 0.3, 0.2) and then shifted by
 *       e_r = (1, 2, 0.5) cm: o_m = Q + R_θ(O − Q) + B·e_r, u_m = R_θ·u, the sample's pivot Q + B·e_r (the receiving
 *       figure's own). Solved with the tilt axis = side: the fix about that pivot gives o' = R_φ(o_m − p) + p + B·x =
 *       Q + R_φR_θ(O − Q) + B·(e_r + x), u' = R_φR_θ·u; zero error needs u' = u → φ = −θ (u ⊥ side, so any other φ turns
 *       it), then o' = O + B(e_r + x) on the axis and at the depth target → x = −e_r. Expect x = (−1, −2, −0.5) cm
 *       (±0.05 mm), tilt −6° (±0.01°), and the part's samples unchanged by moveSample (only o and u move).
 *   [12] THE AXIS ERROR IS CONTINUOUS in the shaft angle (`axisError`): o = 0, u = +Z, the root joint at (0, 0, −0.05)
 *       (s_root = −0.05), the shaft d = (sin θ, 0, cos θ), c = cos θ, c_min = 0.2. Q = P'_0 + t·d with
 *       t = 0.05·c / max(c², 0.04), so the offset is t·sin θ along +X:
 *         c = 0.5:  t = 0.05/0.5 = 0.1,           sin θ = √0.75 = 0.8660254  → 0.0866025 m (the exact crossing, z = 0)
 *         c = 0.2:  t = 0.05·0.2/0.04 = 0.25,     sin θ = √0.96 = 0.9797959  → 0.2449490 m (both sides of c_min agree:
 *                   c = 0.2 + 1e-9 gives 0.05/c = 0.25 too, within 1e-7)
 *         c = 0.1:  t = 0.05·0.1/0.04 = 0.125,    sin θ = √0.99 = 0.9949874  → 0.1243734 m (the taper)
 *         c = 0:    t = 0 → 0 (the root joint, which lies on the axis); c = −0.3: t = 0 → 0.
 *       The lever is L·|d − u| = 0.1·√(2 − 2c): c = 0.5 → 0.1 m.
 */
import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
/** The scene-render bundle, or — `oldAt` = a commit — that commit's pairAlign.ts against today's modules (the [10] proof). */
async function loadSR(oldAt = null) {
  const dir = await mkdtemp(join(ROOT, 'scripts/.smoke-pair-align-'))
  try {
    const esbuild = await import(join(ROOT, 'node_modules/esbuild/lib/main.js'))
    const stdin = oldAt
      ? { contents: execFileSync('git', ['show', `${oldAt}:packages/scene-render/src/pairAlign.ts`], { cwd: ROOT, encoding: 'utf8' }),
        resolveDir: join(ROOT, 'packages/scene-render/src'), loader: 'ts' }
      : { contents: "export * from '@anima/scene-render';", resolveDir: join(ROOT, 'client3d'), loader: 'ts' }
    const built = await esbuild.build({
      stdin,
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
  const want1 = add(mul(e1, -1), mul([0, -s15, c15], 0.018))
  const dx = Math.hypot(...sub(sol.x, want1))
  assert.ok(dx < 1e-3, `[1] x off by ${dx}`)
  near(sol.root.pitchDeg, 12, 0.2, '[1] pitch'); near(sol.root.yawDeg, -5, 0.2, '[1] yaw')
  near(sol.deg[0], 0, 0.2, '[1] tilt'); near(sol.deg[1], 0, 0.2, '[1] roll')
  assert.deepEqual(sol.hits, [])
  const rep = SR.keyReport(after(meas, sol, AM))
  for (const r of [rep.deep, rep.shallow]) {
    assert.ok(r.rootOffMm < 0.1 && r.tipOffMm < 0.1, `[1] off axis ${r.rootOffMm} / ${r.tipOffMm}`)
    assert.ok(r.shaftDeg < 0.05, `[1] shaft ${r.shaftDeg}`)
  }
  near(rep.deep.rootDepthMm, -2, 0.05, '[1] deep root'); near(rep.deep.depthMm, 118, 0.05, '[1] deep tip')
  assert.equal(rep.deep.index, 4); assert.equal(rep.shallow.index, 0)
  assert.equal(SR.keyLamp(rep, sol.hits, true), 'green')
  ok(`[1] recovery: x error ${(dx * 1000).toFixed(4)} mm, root ${sol.root.pitchDeg.toFixed(4)}° / ${sol.root.yawDeg.toFixed(4)}°, tilt/roll ${sol.deg.map((v) => v.toFixed(4)).join(' / ')}°`)
  const meas2 = stroke({ O: O2, e: e1, rooted: false })
  const two = SR.solveAlign(problem([{ samples: meas, rooted: true }, { samples: meas2 }], AM))
  const dx2 = Math.hypot(...sub(two.x, want1))
  assert.ok(dx2 < 1e-3, `[1] two relations x off by ${dx2}`)
  near(two.root.pitchDeg, 12, 0.2, '[1] two pitch'); near(two.root.yawDeg, -5, 0.2, '[1] two yaw')
  ok(`[1] two relations: x error ${(dx2 * 1000).toFixed(4)} mm, root ${two.root.pitchDeg.toFixed(4)}° / ${two.root.yawDeg.toFixed(4)}°`)
}
{ // [2]
  const A = { pitchDeg: 12, yawDeg: -5 }
  const meas = stroke()
  const sol = SR.solveAlign(problem([{ samples: meas, rooted: true }], A))
  ;[0, -0.018 * s15, 0.018 * c15].forEach((v, i) => near(sol.x[i], v, 5e-5, `[2] x[${i}]`))
  assert.ok(Math.abs(sol.root.pitchDeg - 12) < 0.01 && Math.abs(sol.root.yawDeg + 5) < 0.01, '[2] root')
  assert.ok(sol.deg.every((v) => Math.abs(v) < 0.01), '[2] tilt/roll')
  near(SR.keyReport(after(meas, sol, A)).deep.rootDepthMm, -2, 0.05, '[2] deep root')
  ok(`[2] a correct line, shallow stroke goes to full depth: x = ${sol.x.map((v) => (v * 100).toFixed(4)).join(' / ')} cm`)
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
  assert.ok(sol.hits.includes('side'), `[4] hits ${sol.hits}`); near(sol.x[0], -0.03, 1e-9, '[4] side on its cap')
  assert.equal(SR.keyLamp(SR.keyReport(after(meas, sol, AM)), sol.hits, true), 'red')
  assert.ok(SR.keyReasons(SR.keyReport(after(meas, sol, AM)), sol.hits, true).includes('caps'), '[4] reason caps')
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
  near(sol.x[0], 0.0054831, 2e-5, '[6] join side')
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
{ // [10]
  const C = Math.cos(4 * D2R), S = Math.sin(4 * D2R)
  const X = [0, 0.9, 0.2], m = [0, 0, 1]
  const I = [1, 0, 0, 0, 1, 0, 0, 0, 1]
  const frame = (u, t, phase) => {
    const o = add(X, mul(u, 0.2)), root = add(X, mul(m, t)), tip = add(X, mul(m, t + 0.107))
    const chain = Array.from({ length: 5 }, (_, j) => add(root, mul(m, 0.107 * j / 4)))
    return { tip, base: root, chain, o, u, pivot: add(root, [0, 0.1, -0.1]), raised: 1, channel: true,
      depthM: 0.15, tipRadiusM: 0.015, phase }
  }
  const samples = [frame([0, S, C], 0.127, 0.5), frame([0, -S, C], 0.057, 0)]
  const prob = { relations: [{ samples }], basis: I, axes: [], cap, root: null }
  const before = SR.keyReport(samples)
  near(before.deep.depthMm, 33.430, 0.01, '[10] measured deep tip'); near(before.deep.rootDepthMm, -73.309, 0.01, '[10] measured deep root')
  const sol = SR.solveAlign(prob)
  ;[0, 0, 0.198 / C - 0.127].forEach((v, i) => near(sol.x[i], v, 5e-5, `[10] x[${i}]`))
  assert.deepEqual(sol.hits, [])
  const rep = SR.keyReport(samples.map((s) => SR.moveSample(s, sol.fix)))
  near(rep.deep.rootDepthMm, -2, 0.05, '[10] deep root'); near(rep.deep.depthMm, -2 + 107 * C, 0.05, '[10] deep tip')
  for (const r of [rep.deep, rep.shallow]) {
    near(r.openOffMm, 200 * S / C, 0.01, '[10] opening offset'); near(r.leverMm, 200 * Math.sin(2 * D2R), 0.01, '[10] lever')
  }
  assert.ok(rep.deep.tipInside && rep.deep.rootOutside && !rep.deep.pastBottom, '[10] step 1')
  assert.deepEqual(SR.keyReasons(rep, sol.hits, true, before), ['off_axis'])
  assert.equal(SR.keyLamp(rep, sol.hits, true, before), 'red')
  ok(`[10] axes 8° apart: full depth, tip ${rep.deep.depthMm.toFixed(3)} mm, root ${rep.deep.rootDepthMm.toFixed(3)} mm, opening offset ${rep.deep.openOffMm.toFixed(3)} mm`)
  const OLD = await loadSR('99a32b3f3a82b83faf8357d2c59058131bbb259e')
  const old = OLD.solveAlign(prob)
  const oldTip = OLD.keyReport(samples.map((s) => OLD.moveSample(s, old.fix))).deep.depthMm
  assert.ok(oldTip > 1.9 && oldTip <= 2.0, `[10] old deep tip ${oldTip}`)
  ok(`[10] fails on 99a32b3f: the old solve leaves the deep tip at ${oldTip.toFixed(3)} mm`)
}
{ // [11]
  const th = 6 * D2R
  const R6 = SR.turnMatrix(mul(side, th))
  const mv = (M, v) => [M[0] * v[0] + M[1] * v[1] + M[2] * v[2], M[3] * v[0] + M[4] * v[1] + M[5] * v[2], M[6] * v[0] + M[7] * v[1] + M[8] * v[2]]
  const Q = add(O1, Bv([0, 0.3, 0.2])), er = [0.01, 0.02, 0.005]
  const meas = stroke({ along: 0.018, rooted: false }).map((s) => ({ ...s, mover: 'receiver',
    o: add(add(Q, mv(R6, sub(s.o, Q))), Bv(er)), u: mv(R6, s.u), pivot: add(Q, Bv(er)) }))
  const sol = SR.solveAlign({ relations: [{ samples: meas }], basis: B, axes: [side], cap, root: null })
  er.forEach((v, i) => near(sol.x[i], -v, 5e-5, `[11] x[${i}]`))
  near(sol.deg[0], -6, 0.01, '[11] tilt')
  const moved = SR.moveSample(meas[3], sol.fix)
  assert.deepEqual(moved.chain, meas[3].chain); assert.deepEqual(moved.tip, meas[3].tip)
  near(Math.hypot(...sub(moved.o, O1)), 0, 1e-4, '[11] opening back'); near(dot(moved.u, U), 1, 1e-8, '[11] axis back')
  ok(`[11] the receiving role moves: x = ${sol.x.map((v) => (v * 100).toFixed(4)).join(' / ')} cm, tilt ${sol.deg[0].toFixed(4)}°`)
}
{ // [12]
  const at = (c) => { const sn = Math.sqrt(1 - c * c); return SR.axisError({ o: [0, 0, 0], u: [0, 0, 1], tip: [0.12 * sn, 0, -0.05 + 0.12 * c] }, [0, 0, -0.05]) }
  const cases = [[0.5, 0.0866025], [0.2, 0.2449490], [0.2 + 1e-9, 0.2449490], [0.1, 0.1243734], [0, 0], [-0.3, 0]]
  for (const [c, want] of cases) {
    const e = at(c)
    near(e.offset[0], want, 2e-7, `[12] offset at c = ${c}`); near(e.offset[1], 0, 1e-12, '[12] y'); near(e.offset[2], 0, 1e-12, '[12] z')
  }
  near(Math.hypot(...at(0.5).lever), 0.1, 1e-9, '[12] lever')
  ok('[12] the opening-plane offset is continuous: 86.603 / 244.949 / 244.949 / 124.373 / 0 / 0 mm')
}
console.log(`\n${n}/14 checks passed`)
