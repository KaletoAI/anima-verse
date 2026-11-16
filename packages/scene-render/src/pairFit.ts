/**
 * PAIR FIT (Ruling A129) — the follow-ups to Auto-align (A126, `channelContact.ts`). One geometry for both renderers:
 * the Library's place preview and client3d's pair interaction call the same functions on the same
 * `FigureRuntime.inspect()` numbers.
 *
 * A FIX moves the ENTERING figure rigidly about a PIVOT p (the caller's convention, the same at solve and at apply):
 *   X ↦ R(X − p) + p + Δ,  R = exp([θ]×) for the rotation vector θ (Rodrigues), Δ the shift (world metres).
 * Only rotations about the caller's AXES are solved (Tilt = the clip frame's side axis, Roll = its forward axis):
 * θ = Σ_k α_k a_k, every |α_k| ≤ the angle bound, |Δ_i| ≤ the shift bound.
 *
 * THE SOLVE (`solvePairFix`): least squares over the sampled loop, Gauss–Newton with a forward-difference Jacobian
 * (step 1e-6) and the bounds projected after every step (at most `iterations` steps, stop below 1e-7):
 *   r = [ P_t(T'_t − O_t)                     lateral of the tip, every frame t
 *         λ · P_t(d'_t)                       the shaft direction d' = (T' − B')/|T' − B'| off the axis, every frame
 *         √W · u_e·(T'_e − O_e) ]             the tip on the opening at the entry frame e (smallest s, re-chosen each step)
 * with P_t = I − u_t u_tᵀ, λ = `FIT_ANGLE_WEIGHT_M` (1 rad of shaft tilt costs like λ metres of lateral error) and
 * W = `CONTACT_ENTRY_WEIGHT` × the frame count — the A126 solve plus the angle term and the rotation unknowns. Without
 * axes it is the A126 shift solve (same minimum, different method).
 *
 * THE RUNTIME FIT (`PairFitState`): a pair interaction samples its own first loop (the tip measured with the current
 * fix applied, unapplied again before it is stored, so the samples are the raw clip), solves ONCE with the runtime
 * bounds (`RUNTIME_FIT`: ±5 cm, ±10°) — one whole loop, from the first wrap of the clip phase to the next, at least
 * `FIT_MIN_SAMPLES` samples — and keeps
 * that fix for the interaction. The stored clip offset stays the coarse one; every pair gets its own fine one.
 *
 * THE FOLLOW (`pairFitObserve`): per frame a small extra shift of the entering figure that keeps the tip on the
 * channel axis through the stroke — integral control on the measured lateral r = P(T − O):
 *   f ← clamp(f − g · r, `FOLLOW.maxM`) while the tip is near (s ≥ −`FOLLOW.nearM`), else f ← f · `FOLLOW.decay`.
 * Measured on the frame just rendered, applied on the next (one frame of lag, like any IK on last frame's pose).
 *
 * THE HONEST CHECK (`pairInterpenetration`): the deepest overlap of two different figures' capsules where ONLY the
 * pairs the channel allows are exempt — an attached-part capsule of the entering figure against one of the receiving
 * figure's `suppress` capsules. Everything else counts, attached part included. Lamp green ≤ `CLEAR_GREEN_MM`,
 * yellow ≤ `CLEAR_YELLOW_MM`.
 */
import type { Vec3 } from './collision'
import { CONTACT_ENTRY_WEIGHT, type ContactSample } from './channelContact'

export interface FitSample extends ContactSample { pivot: Vec3 }
export interface PairFix { shift: Vec3; turn: Vec3 }
export interface FitBounds { maxShiftM: number; maxAngleDeg: number }
export interface FitOptions extends FitBounds {
  /** Unit rotation axes (world) the fix may turn about; [] = shift only. */
  axes: readonly Vec3[]
  angleWeightM?: number
  entryWeight?: number
  iterations?: number
}

export const FIT_ANGLE_WEIGHT_M = 0.02
/** Auto-align (the Library, stored): partner B's tilt and roll at most ±20°, the shift effectively free. */
export const ALIGN_FIT: FitBounds = Object.freeze({ maxShiftM: 0.5, maxAngleDeg: 20 })
/** The runtime fine fit of one pair on top of the stored clip: ±5 cm, ±10°. */
export const RUNTIME_FIT: FitBounds = Object.freeze({ maxShiftM: 0.05, maxAngleDeg: 10 })
export const FIT_MIN_SAMPLES = 8
export const FOLLOW = Object.freeze({ maxM: 0.02, gain: 0.7, nearM: 0.03, decay: 0.9 })
export const CLEAR_GREEN_MM = 5
export const CLEAR_YELLOW_MM = 20
export const NO_FIX: PairFix = Object.freeze({ shift: [0, 0, 0] as Vec3, turn: [0, 0, 0] as Vec3 }) as PairFix

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const scale = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const len = (p: Vec3) => Math.hypot(p[0], p[1], p[2])
const lateral = (v: Vec3, u: Vec3): Vec3 => sub(v, scale(u, dot(v, u)))
const clamp = (v: number, m: number) => Math.max(-m, Math.min(m, v))

/** Row-major 3×3 of the rotation vector θ (Rodrigues). */
export function turnMatrix(w: Vec3): number[] {
  const a = len(w)
  if (a < 1e-12) return [1, 0, 0, 0, 1, 0, 0, 0, 1]
  const [x, y, z] = scale(w, 1 / a)
  const c = Math.cos(a), s = Math.sin(a), k = 1 - c
  return [c + x * x * k, x * y * k - z * s, x * z * k + y * s,
    y * x * k + z * s, c + y * y * k, y * z * k - x * s,
    z * x * k - y * s, z * y * k + x * s, c + z * z * k]
}
const mul = (m: number[], v: Vec3): Vec3 =>
  [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2], m[6] * v[0] + m[7] * v[1] + m[8] * v[2]]
const mulT = (m: number[], v: Vec3): Vec3 =>
  [m[0] * v[0] + m[3] * v[1] + m[6] * v[2], m[1] * v[0] + m[4] * v[1] + m[7] * v[2], m[2] * v[0] + m[5] * v[1] + m[8] * v[2]]

/** X ↦ R(X − p) + p + Δ. */
export function fixPoint(fix: PairFix, pivot: Vec3, x: Vec3): Vec3 {
  return add(add(mul(turnMatrix(fix.turn), sub(x, pivot)), pivot), fix.shift)
}
/** The inverse: X ↦ Rᵀ(X − p − Δ) + p. */
export function unfixPoint(fix: PairFix, pivot: Vec3, x: Vec3): Vec3 {
  return add(mulT(turnMatrix(fix.turn), sub(sub(x, pivot), fix.shift)), pivot)
}
/** A sample with the entering figure's points (tip, base) moved by `fix`. */
export function fixSample(s: FitSample, fix: PairFix): FitSample {
  return { ...s, tip: fixPoint(fix, s.pivot, s.tip), base: fixPoint(fix, s.pivot, s.base) }
}
/** Two fixes about the same pivot: first `a`, then `b`. */
export function composeFix(a: PairFix, b: PairFix): PairFix {
  // b∘a: X ↦ Rb(Ra(X−p) + Δa) + p + Δb  →  turn ≈ combined rotation, shift = Rb Δa + Δb (exact for the shift).
  const Ra = turnMatrix(a.turn), Rb = turnMatrix(b.turn)
  const R = [0, 0, 0, 0, 0, 0, 0, 0, 0]
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) R[i * 3 + j] += Rb[i * 3 + k] * Ra[k * 3 + j]
  return { shift: add(mul(Rb, a.shift), b.shift), turn: matrixTurn(R) }
}
/** The rotation vector of a row-major rotation matrix. */
export function matrixTurn(m: number[]): Vec3 {
  const c = Math.max(-1, Math.min(1, (m[0] + m[4] + m[8] - 1) / 2))
  const a = Math.acos(c)
  if (a < 1e-9) return [0, 0, 0]
  const v: Vec3 = [m[7] - m[5], m[2] - m[6], m[3] - m[1]]
  const s = len(v)
  return s < 1e-12 ? [0, 0, 0] : scale(v, a / s)
}
/** World pose of a root at `position` (identity-free: the caller premultiplies) moved by `fix` about `pivot`:
 *  the new position and the rotation to premultiply, as a quaternion [x, y, z, w]. */
export function fixRoot(fix: PairFix, pivot: Vec3, position: Vec3): { position: Vec3; quaternion: [number, number, number, number] } {
  const a = len(fix.turn)
  const h = a / 2, s = a > 1e-12 ? Math.sin(h) / a : 0.5
  return { position: fixPoint(fix, pivot, position), quaternion: [fix.turn[0] * s, fix.turn[1] * s, fix.turn[2] * s, Math.cos(h)] }
}

function residuals(samples: readonly FitSample[], fix: PairFix, lambda: number, W: number): number[] {
  const out: number[] = []
  let e = -1, min = Infinity
  const moved = samples.map((x) => fixSample(x, fix))
  moved.forEach((x, i) => { const s = dot(sub(x.tip, x.o), x.u); if (s < min) { min = s; e = i } })
  for (const x of moved) {
    const lat = lateral(sub(x.tip, x.o), x.u)
    out.push(lat[0], lat[1], lat[2])
    const d = sub(x.tip, x.base), l = len(d)
    const pd = l > 0 ? lateral(scale(d, 1 / l), x.u) : [0, 0, 0] as Vec3
    out.push(lambda * pd[0], lambda * pd[1], lambda * pd[2])
  }
  if (e >= 0) out.push(Math.sqrt(W) * min)
  return out
}

function solveLinear(A: number[][], b: number[]): number[] | null {
  const n = b.length
  const M = A.map((row, i) => [...row, b[i]])
  for (let c = 0; c < n; c++) {
    let p = c
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r
    if (Math.abs(M[p][c]) < 1e-15) return null
    ;[M[c], M[p]] = [M[p], M[c]]
    for (let r = 0; r < n; r++) {
      if (r === c) continue
      const f = M[r][c] / M[c][c]
      for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]
    }
  }
  return M.map((row, i) => row[n] / row[i])
}

/** The fix for the entering figure (module docstring THE SOLVE); NO_FIX without samples. */
export function solvePairFix(samples: readonly FitSample[], opts: FitOptions): PairFix {
  if (!samples.length) return NO_FIX
  const lambda = opts.angleWeightM ?? FIT_ANGLE_WEIGHT_M
  const W = (opts.entryWeight ?? CONTACT_ENTRY_WEIGHT) * samples.length
  const axes = opts.axes
  const n = 3 + axes.length
  const maxA = opts.maxAngleDeg * Math.PI / 180
  const toFix = (x: number[]): PairFix => {
    const turn: Vec3 = [0, 0, 0]
    axes.forEach((a, k) => { turn[0] += a[0] * x[3 + k]; turn[1] += a[1] * x[3 + k]; turn[2] += a[2] * x[3 + k] })
    return { shift: [x[0], x[1], x[2]], turn }
  }
  const project = (x: number[]) => x.map((v, i) => clamp(v, i < 3 ? opts.maxShiftM : maxA))
  let x = new Array(n).fill(0)
  const cost = (r: number[]) => r.reduce((a, v) => a + v * v, 0)
  let r = residuals(samples, toFix(x), lambda, W)
  let c = cost(r)
  const iterations = opts.iterations ?? 20
  for (let it = 0; it < iterations; it++) {
    const J: number[][] = []
    for (let k = 0; k < n; k++) {
      const xp = x.slice(); xp[k] += 1e-6
      const rp = residuals(samples, toFix(xp), lambda, W)
      J.push(rp.map((v, i) => (v - r[i]) / 1e-6))
    }
    const A = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => {
      let s = 0
      for (let m = 0; m < r.length; m++) s += J[i][m] * J[j][m]
      return s + (i === j ? 1e-9 : 0)
    }))
    const g = Array.from({ length: n }, (_, i) => { let s = 0; for (let m = 0; m < r.length; m++) s -= J[i][m] * r[m]; return s })
    const step = solveLinear(A, g)
    if (!step) break
    let t = 1, accepted = false
    for (let ls = 0; ls < 8; ls++) {
      const xn = project(x.map((v, i) => v + t * step[i]))
      const rn = residuals(samples, toFix(xn), lambda, W)
      const cn = cost(rn)
      if (cn < c) { const moved = Math.max(...xn.map((v, i) => Math.abs(v - x[i]))); x = xn; r = rn; c = cn; accepted = moved > 1e-7; break }
      t /= 2
    }
    if (!accepted) break
  }
  return toFix(x)
}

/** The fix's angles about `axes` (degrees, in axis order) — the inverse of `solvePairFix`'s θ = Σ α_k a_k for
 *  orthogonal axes. */
export function fixAnglesDeg(fix: PairFix, axes: readonly Vec3[]): number[] {
  return axes.map((a) => dot(fix.turn, a) * 180 / Math.PI)
}

/** The clip frame's tilt and roll axes (world) of a figure whose root frame is the row-major `frame`
 *  (`ClipCalibration.frame`): its side axis (+X) and its forward axis (+Z). */
export function turnAxes(frame: readonly number[]): [Vec3, Vec3] {
  return [[frame[0], frame[3], frame[6]], [frame[2], frame[5], frame[8]]]
}
/** Partner B's stored/drafted turn (Ruling A129) as a fix: tilt about the side axis, roll about the forward axis. */
export function partnerTurnFix(tiltDeg: number, rollDeg: number, frame: readonly number[]): PairFix {
  const [side, fwd] = turnAxes(frame)
  const a = tiltDeg * Math.PI / 180, b = rollDeg * Math.PI / 180
  return { shift: [0, 0, 0], turn: [side[0] * a + fwd[0] * b, side[1] * a + fwd[1] * b, side[2] * a + fwd[2] * b] }
}
/** THE PIVOT both renderers turn the entering figure about: its root (before any fix) plus its hips bind turned by
 *  the root frame — the bind hips point, the same at solve and at apply. */
export function fixPivot(rootPosition: Vec3, frame: readonly number[], hipsBind: Vec3): Vec3 {
  return [rootPosition[0] + frame[0] * hipsBind[0] + frame[1] * hipsBind[1] + frame[2] * hipsBind[2],
    rootPosition[1] + frame[3] * hipsBind[0] + frame[4] * hipsBind[1] + frame[5] * hipsBind[2],
    rootPosition[2] + frame[6] * hipsBind[0] + frame[7] * hipsBind[1] + frame[8] * hipsBind[2]]
}

// ── the runtime fit + the follow ──

export interface PairFitState {
  phase: 'collect' | 'fitted'
  samples: FitSample[]
  fix: PairFix
  follow: Vec3
  lastPhase: number
  /** The first wrap of the clip was seen: from here one WHOLE loop is sampled. */
  armed: boolean
  /** Lateral of the tip (mm) at each frame the tip was in or at the channel since the fit (the follow's evidence). */
  lateralMm: number[]
}

export function createPairFit(): PairFitState {
  return { phase: 'collect', samples: [], fix: NO_FIX, follow: [0, 0, 0], lastPhase: -1, armed: false, lateralMm: [] }
}

/** The fix the entering figure carries this frame: the solved one plus the follow shift. */
export function pairFitTotal(st: PairFitState): PairFix {
  return { shift: add(st.fix.shift, st.follow), turn: st.fix.turn }
}

/** One rendered frame of the pair (module docstring THE RUNTIME FIT / THE FOLLOW). `measured` = the sample as
 *  rendered, i.e. WITH `pairFitTotal(st)` applied about `measured.pivot`; `phase` = the clip time (s). `axes` =
 *  the tilt/roll axes (world) of this frame. `follow` false switches the follow off (the fit still runs). */
export function pairFitObserve(st: PairFitState, measured: FitSample, phase: number, axes: readonly Vec3[],
  bounds: FitBounds = RUNTIME_FIT, follow = true): void {
  const total = pairFitTotal(st)
  if (st.phase === 'collect') {
    const raw: FitSample = { ...measured, tip: unfixPoint(total, measured.pivot, measured.tip),
      base: unfixPoint(total, measured.pivot, measured.base) }
    const wrapped = st.lastPhase >= 0 && phase < st.lastPhase
    if (wrapped && st.armed && st.samples.length >= FIT_MIN_SAMPLES) {
      st.fix = solvePairFix(st.samples, { ...bounds, axes })
      st.phase = 'fitted'
    } else {
      if (wrapped) st.armed = true
      if (st.armed) st.samples.push(raw)
    }
  }
  st.lastPhase = phase
  // What was rendered: the evidence (lateral through the stroke, once fitted).
  const rel = sub(measured.tip, measured.o)
  const s = dot(rel, measured.u)
  const lat = lateral(rel, measured.u)
  if (st.phase === 'fitted' && s >= 0) st.lateralMm.push(len(lat) * 1000)
  if (!follow) { st.follow = [0, 0, 0]; return }
  if (s >= -FOLLOW.nearM) {
    st.follow = [0, 1, 2].map((i) => clamp(st.follow[i] - FOLLOW.gain * lat[i], FOLLOW.maxM)) as Vec3
  } else st.follow = scale(st.follow, FOLLOW.decay)
}

// ── finding the contact in two inspections ──

interface InspectionLike {
  chains: readonly { op: string; segments: readonly { a: readonly number[]; b: readonly number[] }[] }[]
  channels: readonly { id: string; o: readonly number[]; u: readonly number[]; accepts: readonly string[] }[]
}
/** The first chain of `entering` whose op one of `receiving`'s channels accepts: chain index + channel id. */
export function findContact(entering: InspectionLike, receiving: InspectionLike): { chain: number; channel: string } | null {
  for (let ci = 0; ci < entering.chains.length; ci++) {
    const ch = receiving.channels.find((x) => x.accepts.includes(entering.chains[ci].op))
    if (ch && entering.chains[ci].segments.length) return { chain: ci, channel: ch.id }
  }
  return null
}
/** The contact sample of this frame (world), or null when the chain or channel is missing. */
export function contactSampleOf(entering: InspectionLike, receiving: InspectionLike, hit: { chain: number; channel: string },
  pivot: Vec3): FitSample | null {
  const chain = entering.chains[hit.chain]
  const ch = receiving.channels.find((x) => x.id === hit.channel)
  if (!chain?.segments.length || !ch) return null
  const v = (p: readonly number[]): Vec3 => [p[0], p[1], p[2]]
  const u = v(ch.u), l = len(u) || 1
  return { tip: v(chain.segments[chain.segments.length - 1].b), base: v(chain.segments[0].a), o: v(ch.o),
    u: scale(u, 1 / l), pivot }
}

