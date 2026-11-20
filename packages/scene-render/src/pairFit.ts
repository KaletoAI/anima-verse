/**
 * PAIR FIT (Ruling A129) — the geometry Auto-align (`pairAlign.ts`, Ruling A212) and both renderers share for a pair
 * clip: the library's place preview and client3d's pair interaction call the same functions on the same
 * `FigureRuntime.inspect()` numbers.
 *
 * A FIX moves the ENTERING figure rigidly about a PIVOT p (the caller's convention, the same at solve and at apply):
 *   X ↦ R(X − p) + p + Δ,  R = exp([θ]×) for the rotation vector θ (Rodrigues), Δ the shift (world metres).
 * Partner B's stored tilt/roll/yaw (`partnerTurnFix`) is such a fix, applied about its bind hips (`fixPivot`,
 * `fixRoot`); a solve turns only about the caller's AXES (Tilt = the clip frame's side axis, Roll = its forward axis).
 *
 * THE RESIDUALS (`fitResiduals`): what a fix leaves over the sampled loop — the least-squares problem the bounded
 * Auto-align solves (`pairAlign.ts` THE SOLVE, summed over every contact relation of one moving figure):
 *   r = [ P_t(T'_t − O_t)                     lateral of the tip, every frame t
 *         λ · P_t(d'_t)                       the shaft direction d' = (T' − B')/|T' − B'| off the axis, every frame
 *         √W · u_e·(T'_e − O_e) ]             the tip on the opening at the entry frame e (smallest s)
 * with P_t = I − u_t u_tᵀ, λ = `FIT_ANGLE_WEIGHT_M` (1 rad of shaft tilt costs like λ metres of lateral error) and
 * W = `CONTACT_ENTRY_WEIGHT` × the frame count — the A126 terms plus the angle term.
 *
 * RIGID (Ruling A145 as of 2026-11-20): the residuals read the samples as measured — the attached part never bends
 * inside the fit. The root bend (`chainBend.ts`) is a render step AFTER the fit: both renderers turn the part's root
 * every frame with the same `bendSample`, and Auto-align reports what that turn does on its aligned samples.
 *
 * POSTURE (Ruling A150, `postureSupport.ts`): a sample may carry the entering figure's SUPPORT; then every frame adds
 * the residual `POSTURE.weight` · (the support's change beyond the float/sink band), and the fix's turn costs
 * `POSTURE.turnCostM` · √N per radian — so the solve shifts along the surface first, turns only a little and only
 * about the support, and leaves what the posture cannot give as the residual. The caller caps the turn per place type
 * (`postureAngleCapDeg`). The clip's root angle (`chainBend.ts` THE ROOT ANGLE, Ruling A158) is already on the
 * rendered chain a sample is read from; the fit starts from it and never changes it.
 *
 * THE HONEST CHECK (`pairInterpenetration`): the deepest overlap of two different figures' capsules where ONLY the
 * pairs the channel allows are exempt — an attached-part capsule of the entering figure against one of the receiving
 * figure's `suppress` capsules. Everything else counts, attached part included. Lamp green ≤ `CLEAR_GREEN_MM`,
 * yellow ≤ `CLEAR_YELLOW_MM`.
 */
import type { Vec3 } from './collision'
import { CONTACT_ENTRY_WEIGHT, type ContactSample } from './channelContact'
import { isPointTarget, MOUTH_CHANNEL_ID, orientAlong, POINT_TARGET_OPS, type ContactTarget } from './contactTarget'
import { bendLimitAt, solveChainBend, type BendFrame, type BendLimits, type BendResult } from './chainBend'
import { POSTURE, postureExcess, supportHeight, supportSample, type SupportSample } from './postureSupport'

export interface FitSample extends ContactSample {
  pivot: Vec3
  /** Ruling A145: the attached-part chain's points (root joint … tip), its raised fraction and whether the target is a
   *  channel (the joints near/inside follow its axis) — what `bendSample` turns at the root. Absent = no bend. */
  chain?: Vec3[]
  raised?: number
  channel?: boolean
  /** Ruling A150: the entering figure's support this frame (absent = no posture term). */
  support?: SupportSample | null
}
export interface PairFix { shift: Vec3; turn: Vec3 }
export interface FitOptions {
  angleWeightM?: number
  entryWeight?: number
  /** Ruling A150: the posture term for samples with a support (default on). */
  posture?: boolean
}
export const FIT_ANGLE_WEIGHT_M = 0.02
export const CLEAR_GREEN_MM = 5
export const CLEAR_YELLOW_MM = 20

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const scale = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const len = (p: Vec3) => Math.hypot(p[0], p[1], p[2])
const lateral = (v: Vec3, u: Vec3): Vec3 => sub(v, scale(u, dot(v, u)))

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

/** X ↦ R(X − p) + p + Δ. */
export function fixPoint(fix: PairFix, pivot: Vec3, x: Vec3): Vec3 {
  return add(add(mul(turnMatrix(fix.turn), sub(x, pivot)), pivot), fix.shift)
}
/** A sample with the entering figure's points (tip, base) moved by `fix`. */
export function fixSample(s: FitSample, fix: PairFix): FitSample {
  return { ...s, tip: fixPoint(fix, s.pivot, s.tip), base: fixPoint(fix, s.pivot, s.base),
    ...(s.chain ? { chain: s.chain.map((p) => fixPoint(fix, s.pivot, p)) } : {}),
    ...(s.support ? { support: { ...s.support, pts: s.support.pts.map((p) => fixPoint(fix, s.pivot, p)),
      base: s.support.base ?? supportHeight(s.support.pts, s.support.r) } } : {}) }
}
/** Ruling A150: the support's change (metres) of sample `s` under `fix` against its baseline. */
export function supportDelta(s: FitSample, fix: PairFix): number | null {
  if (!s.support) return null
  const base = s.support.base ?? supportHeight(s.support.pts, s.support.r)
  return supportHeight(s.support.pts.map((p) => fixPoint(fix, s.pivot, p)), s.support.r) - base
}
/** Ruling A145: the sample with its chain turned at the root toward its target within `limits` at its raised fraction
 *  (`chainBend.ts`) — tip and base from the turned chain — and the bend; the sample unchanged (bend null) without a
 *  chain. What both renderers apply every frame; never part of the fit. */
export function bendSample(s: FitSample, limits: BendLimits): { sample: FitSample; bend: BendResult | null } {
  if (!s.chain || s.chain.length < 2) return { sample: s, bend: null }
  const bend = solveChainBend(s.chain, s.o, s.u, bendLimitAt(limits, s.raised ?? 0), { channel: !!s.channel })
  const pts = bend.points
  return { sample: { ...s, chain: pts, tip: pts[pts.length - 1], base: pts[0] }, bend }
}
/** Two fixes about the same pivot: first `a`, then `b`. */
function composeFix(a: PairFix, b: PairFix): PairFix {
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

/** The residual vector of `fix` (module docstring THE RESIDUALS). */
function residuals(samples: readonly FitSample[], fix: PairFix, lambda: number, W: number, posture = false): number[] {
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
  if (posture) {
    // A150: the support stays in its band; a turn pays for itself.
    for (const x of samples) {
      const d = supportDelta(x, fix)
      if (d !== null) out.push(POSTURE.weight * postureExcess(d))
    }
    const k = POSTURE.turnCostM * Math.sqrt(samples.length)
    out.push(k * fix.turn[0], k * fix.turn[1], k * fix.turn[2])
  }
  return out
}

/** The residual vector of `fix` over `samples` (module docstring THE RESIDUALS) — what the bounded Auto-align
 *  (`pairAlign.ts`) adds up over several contact relations of one moving figure. */
export function fitResiduals(samples: readonly FitSample[], fix: PairFix, opts: FitOptions = {}): number[] {
  if (!samples.length) return []
  const lambda = opts.angleWeightM ?? FIT_ANGLE_WEIGHT_M
  const W = (opts.entryWeight ?? CONTACT_ENTRY_WEIGHT) * samples.length
  const posture = opts.posture !== false && samples.some((x) => !!x.support)
  return residuals(samples, fix, lambda, W, posture)
}

export function solveLinear(A: number[][], b: number[]): number[] | null {
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

/** The clip frame's tilt and roll axes (world) of a figure whose root frame is the row-major `frame`
 *  (`ClipCalibration.frame`): its side axis (+X) and its forward axis (+Z). */
export function turnAxes(frame: readonly number[]): [Vec3, Vec3] {
  return [[frame[0], frame[3], frame[6]], [frame[2], frame[5], frame[8]]]
}
/** The body axes of a row-major root frame — side (+X) and up (+Y); what the root angle turns about (Ruling A158). */
export function bendFrameOf(frame: readonly number[]): BendFrame {
  return { side: [frame[0], frame[3], frame[6]], up: [frame[1], frame[4], frame[7]] }
}
/** Partner B's stored/drafted turn (Ruling A129) as a fix: tilt about the side axis, roll about the forward axis.
 *  Ruling A165: `yawDeg` turns B about its OWN vertical axis — the root frame's up through the fix pivot (B's bind
 *  hips) — FIRST; the tilt/roll follows. Yaw 0 is the A129 fix unchanged. */
export function partnerTurnFix(tiltDeg: number, rollDeg: number, frame: readonly number[], yawDeg = 0): PairFix {
  const [side, fwd] = turnAxes(frame)
  const a = tiltDeg * Math.PI / 180, b = rollDeg * Math.PI / 180
  const tr: PairFix = { shift: [0, 0, 0],
    turn: [side[0] * a + fwd[0] * b, side[1] * a + fwd[1] * b, side[2] * a + fwd[2] * b] }
  return yawDeg ? composeFix(partnerYawFix(yawDeg, frame), tr) : tr
}
/** Ruling A165: partner B's yaw about its own vertical axis (the root frame's up, +Y) as a fix — a positive yaw turns
 *  B's forward (+Z) towards its left (+X), like the clip's own turn dial. */
export function partnerYawFix(yawDeg: number, frame: readonly number[]): PairFix {
  const c = yawDeg * Math.PI / 180
  return { shift: [0, 0, 0], turn: [frame[1] * c, frame[4] * c, frame[7] * c] }
}
/** THE PIVOT both renderers turn the entering figure about: its root (before any fix) plus its hips bind turned by
 *  the root frame — the bind hips point, the same at solve and at apply. */
export function fixPivot(rootPosition: Vec3, frame: readonly number[], hipsBind: Vec3): Vec3 {
  return [rootPosition[0] + frame[0] * hipsBind[0] + frame[1] * hipsBind[1] + frame[2] * hipsBind[2],
    rootPosition[1] + frame[3] * hipsBind[0] + frame[4] * hipsBind[1] + frame[5] * hipsBind[2],
    rootPosition[2] + frame[6] * hipsBind[0] + frame[7] * hipsBind[1] + frame[8] * hipsBind[2]]
}

// ── finding the contact in two inspections ──

interface InspectionLike {
  chains: readonly { op: string; segments: readonly { a: readonly number[]; b: readonly number[] }[]
    /** Ruling A145: the chain's raised (straightening) fraction, 0 … 1. */
    raised?: number }[]
  channels: readonly { id: string; o: readonly number[]; u: readonly number[]; accepts: readonly string[] }[]
  /** Ruling A139: the point targets the figure's bones resolve (`contactTarget.ts`). */
  targets?: readonly { id: string; o: readonly number[]; u: readonly number[] }[]
  /** Ruling A150: the body capsules (world) the posture support is read from. */
  capsules?: readonly { id: string; now: { a: readonly number[]; b: readonly number[]; r: number } }[]
}
/** The contact of `entering` in `receiving` for the clip's CONTACT TARGET (Ruling A139, `contactTarget.ts`):
 *  `channel` = the first chain whose op one of `receiving`'s DECLARED channels accepts (A126); `mouth` = the same
 *  against the mouth channel only (A159); a point target = the first chain
 *  with an op of `POINT_TARGET_OPS` against that target of `receiving` (`channel` then holds the target id); `none` = no contact. */
export function findContact(entering: InspectionLike, receiving: InspectionLike, target: ContactTarget = 'channel'):
  { chain: number; channel: string } | null {
  if (target === 'none') return null
  if (isPointTarget(target)) {
    if (!receiving.targets?.some((x) => x.id === target)) return null
    const ci = entering.chains.findIndex((c) => c.segments.length > 0 && POINT_TARGET_OPS.includes(c.op))
    return ci >= 0 ? { chain: ci, channel: target } : null
  }
  // A159: `mouth` = only the mouth channel; `channel` = a declared one, never the mouth.
  const wanted = (id: string) => target === 'mouth' ? id === MOUTH_CHANNEL_ID : id !== MOUTH_CHANNEL_ID
  for (let ci = 0; ci < entering.chains.length; ci++) {
    const ch = receiving.channels.find((x) => wanted(x.id) && x.accepts.includes(entering.chains[ci].op))
    if (ch && entering.chains[ci].segments.length) return { chain: ci, channel: ch.id }
  }
  return null
}
/** The contact sample of this frame (world), or null when the chain or the channel / point target is missing. */
export function contactSampleOf(entering: InspectionLike, receiving: InspectionLike, hit: { chain: number; channel: string },
  pivot: Vec3): FitSample | null {
  const chain = entering.chains[hit.chain]
  const ch = isPointTarget(hit.channel) ? receiving.targets?.find((x) => x.id === hit.channel)
    : receiving.channels.find((x) => x.id === hit.channel)
  if (!chain?.segments.length || !ch) return null
  const v = (p: readonly number[]): Vec3 => [p[0], p[1], p[2]]
  const u = v(ch.u), l = len(u) || 1
  const tip = v(chain.segments[chain.segments.length - 1].b), base = v(chain.segments[0].a)
  // Ruling A145: the chain's points (joints, then the tip) so the renderers can turn it at the root.
  const pts = [...chain.segments.map((x) => v(x.a)), tip]
  const support = entering.capsules ? supportSample(entering.capsules) : null
  return { tip, base, o: v(ch.o), u: orientAlong(hit.channel, scale(u, 1 / l), tip, base), pivot, chain: pts,
    raised: chain.raised ?? 0, channel: !isPointTarget(hit.channel), ...(support ? { support } : {}) }
}

// ── the honest interpenetration check ──

export type ClearLamp = 'green' | 'yellow' | 'red'
/** The deepest overlap between two different figures' capsules (metres, ≥ 0) where only `entering|part` against
 *  `receiving|allowed` is exempt (module docstring THE HONEST CHECK), and the pair it is. */
export function pairInterpenetration(
  contacts: readonly { a: string; capA: string; b: string; capB: string; depth: number }[],
  allow: { entering: string; parts: ReadonlySet<string>; receiving: string; allowed: ReadonlySet<string> },
): { depth: number; worst: { a: string; capA: string; b: string; capB: string } | null } {
  let depth = 0
  let worst: { a: string; capA: string; b: string; capB: string } | null = null
  const exempt = (fa: string, ca: string, fb: string, cb: string) =>
    fa === allow.entering && allow.parts.has(ca) && fb === allow.receiving && allow.allowed.has(cb)
  for (const c of contacts) {
    if (exempt(c.a, c.capA, c.b, c.capB) || exempt(c.b, c.capB, c.a, c.capA)) continue
    if (c.depth > depth) { depth = c.depth; worst = { a: c.a, capA: c.capA, b: c.b, capB: c.capB } }
  }
  return { depth, worst }
}
/** The capsule regions of the entering figure that ARE the attached part (only these may enter the channel). */
export const PART_REGIONS: readonly string[] = ['attached_part', 'appendage']
/** The lamp of the honest check (mm): green ≤ `CLEAR_GREEN_MM`, yellow ≤ `CLEAR_YELLOW_MM`, red beyond. */
export function clearLamp(depthMm: number): ClearLamp {
  return depthMm <= CLEAR_GREEN_MM ? 'green' : depthMm <= CLEAR_YELLOW_MM ? 'yellow' : 'red'
}
