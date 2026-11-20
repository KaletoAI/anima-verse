/**
 * CHAIN BEND (Ruling A145; owner decision 2026-11-20) — the attached part bends toward the contact target, within ONE
 * limit per state (the TOTAL turn), once its tip is near the opening. WHERE it bends depends on the state: a stiff
 * (raised) part bends only at its ROOT, the shaft rigid; a part that is not stiff (resting) may bend at every joint;
 * in between it blends continuously by the chain's raised fraction r. It is a RENDER step, not a lever of Auto-align: Auto-align (`pairAlign.ts`) is rigid and
 * only reports what this bend does afterwards. One geometry for both renderers: the place preview's per-frame bend and
 * client3d's per-frame bend call `bendSample` (`pairFit.ts`) → `solveChainBend` on the same `FigureRuntime.inspect()`
 * chain, and `FigureRuntime.bendChain` applies the result to the bones the same way in both.
 *
 * THE CHAIN (world metres): the attached-part chain's points P_0 … P_n — P_i the joint of link i (`opChains` segment
 * a; one per SIMULATED link: a group's `rigid_tail` links are no particles, so they have no point and no joint of
 * their own and ride on the last link), P_n the last link's tip. The bend joints are P_0 … P_{n−1}; joint j turns the
 * points past it about P_j (applied root-most first, each after its parents moved — `SecondaryMotion.bendChain`).
 *
 * THE TARGET (a channel or a point target, opening/point O, unit axis u, s(E) = (E − O)·u the axial coordinate):
 * every effector point E is pulled onto the axis LINE at its own axial coordinate, G(E) = O + u · s(E) — the turn
 * removes the lateral, the axial part (how far in) is the clip's. The effectors, with weights fixed on the chain as
 * handed in: the tip P_n, weight 1; for a CHANNEL also every joint P_k (1 ≤ k &lt; n) with the weight
 * w_k = clamp(1 + s(P_k)/`BEND_NEAR_M`, 0, 1) — nothing from `BEND_NEAR_M` before the opening, full at the opening
 * and inside. On a rigid shaft that lays the part ALONG the axis the deeper it is in (not only its tip on the line),
 * and since every weight is continuous in the geometry there is no follow switch that could jump.
 *
 * THE DISTRIBUTION (by state, `bendShares`): the chain's turn is ONE rotation vector ω (the TOTAL turn |ω|), handed to
 * the joints in fixed shares c_j that sum to 1 — joint j turns by c_j·ω, so the per-joint angles add up to |ω|:
 *   inner joints (1 ≤ j ≤ n−1): c_j = (1 − r) / n each;   the root: c_0 = 1 − (n − 1)(1 − r) / n.
 * r = 1 (raised): c_0 = 1, the root alone — the rigid shaft, solved by exactly the root-only code of before (bit for
 * bit). r = 0 (resting): every joint 1/n — a uniform arc, the root included, no inner joint taking more than another.
 * In between linear in r, without a jump. The joints past the root together use (n − 1)(1 − r)/n · |ω| ≤ (1 − r)·L;
 * the root the rest, |ω| minus what they use.
 *
 * THE SOLVE (`solveChainBend`): a fixed point on ω, `BEND_SWEEPS` steps: each effector k asks for the smallest turn
 * r_k about P_0 (axis (E_k − P_0) × (G_k − P_0), the angle between them); the step is the weighted mean
 * Σ w_k r_k / Σ w_k, composed onto ω. With the root alone (r = 1) a turn of ω IS that rigid turn; with shares the
 * effector moves less per unit of ω (an arc's chord turns slower than its links), so the step is divided by the
 * weighted chord GAIN ḡ = Σ w_k g_k / Σ w_k, g_k = Σ_{j<k} c_j |P_k − P_j| / |P_k − P_0| on the chain as handed in (1
 * for the root alone; exact for small turns of a straight chain). Then the LIMIT: ω is scaled down to the limit about
 * its own axis when it is longer (a projection). Weights, gains, step and projection are continuous in the input and
 * in r, so the bend is too.
 *
 * THE LIMIT: one TOTAL per state (`BendLimits` {raised, resting} × {totalDeg}, sidecar key `total_deg`). At the
 * chain's raised fraction (`bendLimitAt`: `raised` ∈ [0, 1] is the chain's straightening fraction,
 * `SecondaryMotion.opChains().raised`, linear blend resting → raised) it is L(r), the most the whole chain turns — Σ of
 * every joint's angle. Defaults `BEND_LIMITS_DEFAULT`: raised 15°, resting 120°; a package defaults its clip kinds
 * (capability `clip_bend_limit_defaults`), a clip overrides in the Poses tab. (Before 2026-11-20 each state also had
 * a per-joint value; the stored sidecars were migrated once: raised total = min(old joint, old total) — what the
 * root-only bend used — and resting total = the old total, `animation_clips.migrate_bend_limits_total`.)
 *
 * THE DISTANCE GATE: the limit is scaled by gate(s_tip) = clamp((s_tip + `BEND_REACH_M`) / (`BEND_REACH_M` −
 * `BEND_NEAR_M`), 0, 1) on the chain as handed in — no turn at all while the tip is `BEND_REACH_M` (8 cm) or more in
 * front of the opening, the full limit from `BEND_NEAR_M` (3 cm) before it on, linear in between. Every piece (gate,
 * weights, fixed point, projection) is continuous in the input, so the turn is continuous in s_tip.
 *
 * THE ROOT ANGLE (Ruling A158, replacing A150's root lever): a pair clip sets the attached part's root turn DIRECTLY,
 * per clip — pitch (+ up toward the belly, − down) about the body's side axis and turn (+ the figure's right, − its
 * left) about the body's up axis, both at the root joint P_0 (`rootTurnOf`). It is applied to the rendered chain
 * BEFORE anything reads it (`FigureRuntime.setRootAngle`), always, with or without a partner. The bend above then
 * starts from that turned chain and its own turn COMPOSES with it at the same joint: both go through
 * `SecondaryMotion.bendChain`, which premultiplies the bone's CURRENT world matrix about P_0 — the rendered root is
 * D_bend · R_root (root angle first, then the bend), never one in place of the other. The body axes are the
 * skeleton's own (`bodyFrameOf`: hip joints, hips → spine), since a pair clip turns each half's body inside the clip
 * frame. The figure faces +forward = side × up, side is its LEFT. Pitch +α is a turn of −α about side: a
 * forward-pointing part rises toward the belly, a hanging one swings forward. Yaw +β is a turn of −β about up: a
 * forward-pointing part swings to the figure's RIGHT. Fixed signs, so the slider means the same whatever the part's
 * direction.
 *
 * THE LAMP (`bendLamp`): yellow when the solve wanted more than the (gated) limit — the projection cut the turn, the
 * rest of the error stays visible; green otherwise.
 *
 * THE HAND CASE (`scripts/smoke_chain_bend.mjs` [12]): a straight chain of 4 links of 3 cm along +x, a point target
 * whose axis line runs parallel at 1 cm (tip on the opening), r = 0: every joint turns by φ about +z, link k points at
 * (k+1)φ, and the tip lands on the line when 0.03·Σ_{k=1..4} sin kφ = 0.01 — φ ≈ 1.910° (small angle: 0.3φ = 0.01), a
 * total of 4φ ≈ 7.64° against the root alone's asin(1/12) = 4.78°.
 */
import type { Vec3 } from './collision'

/** One state's limit: the most the whole chain turns, Σ of every joint's angle (degrees). */
export interface BendLimit { totalDeg: number }
/** Ruling A158: a clip's direct root angle (degrees): pitch + up toward the belly, yaw + the figure's right. */
export interface RootAngle { pitchDeg: number; yawDeg: number }
export interface BendLimits { raised: BendLimit; resting: BendLimit }
export type Quat = [number, number, number, number]

export const BEND_LIMITS_DEFAULT: BendLimits = Object.freeze({
  raised: Object.freeze({ totalDeg: 15 }),
  resting: Object.freeze({ totalDeg: 120 }),
}) as BendLimits
/** Ruling A158: the slider ranges of the root angle (degrees, either way). */
export const ROOT_PITCH_MAX_DEG = 60
export const ROOT_YAW_MAX_DEG = 30
/** Steps of the fixed point (module docstring THE SOLVE). */
export const BEND_SWEEPS = 24
/** The full limit applies from this far before the opening on (metres; also the channel joints' weight ramp). */
export const BEND_NEAR_M = 0.03
/** No bend while the tip is this far or farther before the opening (metres; module docstring THE DISTANCE GATE). */
export const BEND_REACH_M = 0.08

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const mul = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const cross = (p: Vec3, q: Vec3): Vec3 => [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]]
const len = (p: Vec3) => Math.hypot(p[0], p[1], p[2])
const DEG = Math.PI / 180

/** Quaternion of the rotation vector w (axis · angle). */
export function quatOf(w: Vec3): Quat {
  const a = len(w)
  if (a < 1e-12) return [0, 0, 0, 1]
  const s = Math.sin(a / 2) / a
  return [w[0] * s, w[1] * s, w[2] * s, Math.cos(a / 2)]
}
export function quatMul(a: Quat, b: Quat): Quat {
  return [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
    a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
    a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]]
}
const conj = (q: Quat): Quat => [-q[0], -q[1], -q[2], q[3]]
export function quatRotate(q: Quat, v: Vec3): Vec3 {
  const r = quatMul(quatMul(q, [v[0], v[1], v[2], 0]), conj(q))
  return [r[0], r[1], r[2]]
}
/** The rotation angle of q (radians, 0 … π). */
export function quatAngle(q: Quat): number {
  return 2 * Math.acos(Math.min(1, Math.abs(q[3])))
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0))

/** The total limit (degrees, ≥ 0) at the chain's raised fraction (module docstring THE LIMIT). */
export function bendLimitAt(limits: BendLimits, raised: number): number {
  const r = clamp01(raised)
  const lo = limits.resting.totalDeg ?? 0, hi = limits.raised.totalDeg ?? 0
  return Math.max(0, lo + (hi - lo) * r)
}

/** The shares c_0 … c_{n−1} of the total turn per joint for a chain of n links at raised fraction r (module docstring
 *  THE DISTRIBUTION): inner joints (1 − r)/n each, the root the rest; they sum to 1. */
export function bendShares(n: number, raised: number): number[] {
  if (n < 1) return []
  const inner = (1 - clamp01(raised)) / n
  return [1 - (n - 1) * inner, ...Array.from({ length: n - 1 }, () => inner)]
}
/** The distance gate at the tip's axial coordinate s_tip (metres, − = before the opening): 0 … 1 (module docstring). */
export function bendGate(sTip: number): number {
  if (!Number.isFinite(sTip)) return 0
  return Math.max(0, Math.min(1, (sTip + BEND_REACH_M) / (BEND_REACH_M - BEND_NEAR_M)))
}

export interface BendResult {
  /** The bent points P'_0 … P'_n (P'_0 = P_0). */
  points: Vec3[]
  /** Every joint that turns, root first: {joint j, q} — its turn relative to its parent link, world axes, applied about
   *  P_j after its parents moved. Only the root at r = 1; empty when nothing turns. */
  turns: { joint: number; q: Quat }[]
  /** The total turn applied (Σ of every joint's angle), the turn the solve wanted, the gated total limit and the full
   *  (ungated) total limit (degrees). */
  deg: number
  wantDeg: number
  limitDeg: number
  maxDeg: number
  /** The distance gate 0 … 1 the limit was scaled by. */
  gate: number
  /** Of `deg`: the root's own turn and what the joints past it use together (degrees). */
  rootDeg: number
  innerDeg: number
  /** The projection cut the turn (the solve wanted more than the gated limit). */
  atLimit: boolean
}
/** The entering figure's body axes (world unit vectors) the root angle turns about. */
export interface BendFrame { side: Vec3; up: Vec3 }

/** The rotation vector (axis · angle, angle ≤ π) of a unit quaternion. */
function rotVecOf(q: Quat): Vec3 {
  const sh = Math.sqrt(Math.max(0, 1 - q[3] * q[3]))
  if (sh < 1e-12) return [0, 0, 0]
  return mul([q[0], q[1], q[2]], ((q[3] < 0 ? -1 : 1) * quatAngle(q)) / sh)
}

/** Bend `points` toward the axis line through `o` along unit `u` (module docstring THE DISTRIBUTION, THE SOLVE) within
 *  the total limit `limitDeg` (degrees, before the gate). `channel` adds the joints as weighted effectors; `raised`
 *  (0 … 1, default 1 = the root alone) is the chain's raised fraction r. A limit of 0, or a tip at or beyond
 *  `BEND_REACH_M` before the opening, returns the chain unbent. */
export function solveChainBend(points: readonly Vec3[], o: Vec3, u: Vec3, limitDeg: number,
  opts: { channel?: boolean; raised?: number; sweeps?: number } = {}): BendResult {
  const P = points.map((p) => [p[0], p[1], p[2]] as Vec3)
  const n = P.length - 1
  const maxDeg = Math.max(0, Number.isFinite(limitDeg) ? limitDeg : 0)
  const s = (e: Vec3) => dot(sub(e, o), u)
  const gate = n >= 1 ? bendGate(s(P[n])) : 0
  const limDeg = maxDeg * gate
  const none: BendResult = { points: P, turns: [], deg: 0, wantDeg: 0, limitDeg: limDeg, maxDeg, gate, atLimit: false,
    rootDeg: 0, innerDeg: 0 }
  if (n < 1 || !(limDeg > 0)) return none
  const p0 = P[0]
  // The effectors and their weights, fixed on the chain as handed in.
  const eff: { k: number; w: number }[] = [{ k: n, w: 1 }]
  if (opts.channel) {
    for (let k = 1; k < n; k++) {
      const w = Math.max(0, Math.min(1, 1 + s(P[k]) / BEND_NEAR_M))
      if (w > 0) eff.push({ k, w })
    }
  }
  const wsum = eff.reduce((a, e) => a + e.w, 0)
  const onAxis = (e: Vec3): Vec3 => add(o, mul(u, s(e)))
  /** The weighted mean of the effectors' smallest turns about P_0 on the posed chain Q (module docstring THE SOLVE). */
  const stepOf = (Q: readonly Vec3[]): Vec3 => {
    let w: Vec3 = [0, 0, 0]
    for (const { k, w: wk } of eff) {
      const a = sub(Q[k], p0), b = sub(onAxis(Q[k]), p0)
      const la = len(a), lb = len(b)
      if (la < 1e-9 || lb < 1e-9) continue
      const c = cross(a, b), lc = len(c)
      if (lc < 1e-12) continue
      const ang = Math.atan2(lc, dot(a, b))
      w = add(w, mul(c, (ang / lc) * (wk / wsum)))
    }
    return w
  }
  const sweeps = opts.sweeps ?? BEND_SWEEPS
  const lim = limDeg * DEG
  const r = opts.raised === undefined ? 1 : clamp01(opts.raised)
  if (r >= 1 || n < 2) {
    // THE ROOT ALONE (r = 1, or a single link): one rigid turn D about P_0.
    const turned = (q: Quat) => P.map((p, k) => (k === 0 ? p : add(p0, quatRotate(q, sub(p, p0)))))
    let D: Quat = [0, 0, 0, 1]
    let Q = P
    for (let it = 0; it < sweeps; it++) {
      const w = stepOf(Q)
      if (len(w) < 1e-12) break
      D = quatMul(quatOf(w), D)
      Q = turned(D)
    }
    // The limit: the rotation vector of D scaled down to the gated limit about its own axis.
    const want = quatAngle(D)
    if (!(want > 1e-12)) return { ...none, wantDeg: 0 }
    if (want > lim) {
      const sh = Math.sqrt(Math.max(0, 1 - D[3] * D[3]))
      const axis: Vec3 = sh > 1e-12 ? mul([D[0], D[1], D[2]], (D[3] < 0 ? -1 : 1) / sh) : [0, 0, 0]
      D = quatOf(mul(axis, lim))
      Q = turned(D)
    }
    const deg = quatAngle(D) / DEG
    return { points: Q, turns: [{ joint: 0, q: D }], deg, wantDeg: want / DEG, limitDeg: limDeg, maxDeg, gate,
      atLimit: want > lim + 1e-9, rootDeg: deg, innerDeg: 0 }
  }
  // SHARES (r < 1): joint j turns by c_j·ω, root-most first, each about its joint as its parents left it.
  const c = bendShares(n, r)
  const pose = (om: Vec3): Vec3[] => {
    const Q = P.map((p) => [p[0], p[1], p[2]] as Vec3)
    for (let j = 0; j < n; j++) {
      const q = quatOf(mul(om, c[j]))
      for (let k = j + 1; k <= n; k++) Q[k] = add(Q[j], quatRotate(q, sub(Q[k], Q[j])))
    }
    return Q
  }
  // The weighted chord gain (module docstring THE SOLVE), on the chain as handed in.
  let gain = 0
  for (const { k, w } of eff) {
    const rk = len(sub(P[k], p0))
    if (rk < 1e-9) continue
    let g = 0
    for (let j = 0; j < k; j++) g += c[j] * len(sub(P[k], P[j]))
    gain += (w / wsum) * (g / rk)
  }
  if (!(gain > 1e-6)) gain = 1
  let om: Vec3 = [0, 0, 0]
  let Q = P
  for (let it = 0; it < sweeps; it++) {
    const w = stepOf(Q)
    if (len(w) < 1e-12) break
    om = rotVecOf(quatMul(quatOf(mul(w, 1 / gain)), quatOf(om)))
    Q = pose(om)
  }
  const want = len(om)
  if (!(want > 1e-12)) return { ...none, wantDeg: 0 }
  if (want > lim) {
    om = mul(om, lim / want)
    Q = pose(om)
  }
  const total = len(om)
  const turns = c.map((cj, joint) => ({ joint, q: quatOf(mul(om, cj)) })).filter((_, j) => c[j] > 0)
  return { points: Q, turns, deg: total / DEG, wantDeg: want / DEG, limitDeg: limDeg, maxDeg, gate,
    atLimit: want > lim + 1e-9, rootDeg: (c[0] * total) / DEG, innerDeg: ((1 - c[0]) * total) / DEG }
}

/** Ruling A158 (module docstring THE ROOT ANGLE): the root turn of `angle` for the chain `points` (P_0 … P_n, world)
 *  in the body frame `frame` — the quaternion to apply at joint 0 and the turned points; null for a zero angle or a
 *  chain without a link. Angles are clamped to the slider ranges. */
export function rootTurnOf(points: readonly Vec3[], frame: BendFrame, angle: RootAngle | null | undefined):
  { q: Quat; points: Vec3[] } | null {
  const n = points.length - 1
  if (!angle || n < 1) return null
  const clamp = (v: number, m: number) => (Number.isFinite(v) ? Math.max(-m, Math.min(m, v)) : 0)
  const a = clamp(angle.pitchDeg, ROOT_PITCH_MAX_DEG) * DEG, b = clamp(angle.yawDeg, ROOT_YAW_MAX_DEG) * DEG
  if (Math.abs(a) + Math.abs(b) < 1e-12) return null
  const p0 = points[0]
  // Pitch about the body's side axis, then the turn about its up axis (world axes, both at P_0).
  const q = quatMul(quatOf(mul(frame.up, -b)), quatOf(mul(frame.side, -a)))
  return { q, points: points.map((p, k) => (k === 0 ? [p[0], p[1], p[2]] as Vec3 : add(p0, quatRotate(q, sub(p, p0))))) }
}

/** Ruling A158: the BODY's own axes from its skeleton (world points): side = left hip joint − right hip joint (the
 *  figure's left), up = hips → spine with its side share removed. Not the placement root's axes — a pair clip turns
 *  each half's body inside the clip frame (partner B faces A). Null when the points are degenerate. */
export function bodyFrameOf(hips: Vec3, spine: Vec3, leftUpLeg: Vec3, rightUpLeg: Vec3): BendFrame | null {
  const sd = sub(leftUpLeg, rightUpLeg), ls = len(sd)
  if (ls < 1e-6) return null
  const side = mul(sd, 1 / ls)
  const ur = sub(spine, hips)
  const uo = sub(ur, mul(side, dot(ur, side))), lu = len(uo)
  if (lu < 1e-6) return null
  return { side, up: mul(uo, 1 / lu) }
}

/** Ruling A158: a stored root angle ({pitch_deg, yaw_deg}, degrees) — 0/0 for anything else. */
export function rootAngleOf(v: unknown): RootAngle {
  const o = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>
  const num = (k: string) => (typeof o[k] === 'number' && Number.isFinite(o[k] as number) ? o[k] as number : 0)
  return { pitchDeg: num('pitch_deg'), yawDeg: num('yaw_deg') }
}

/** Yellow when the limit cut the turn (module docstring THE LAMP), green otherwise. */
export function bendLamp(r: { atLimit: boolean }): 'green' | 'yellow' {
  return r.atLimit ? 'yellow' : 'green'
}

/** Read a stored/declared limits object ({raised: {total_deg}, resting: {total_deg}}, degrees) over the defaults. */
export function bendLimitsOf(v: unknown, fallback: BendLimits = BEND_LIMITS_DEFAULT): BendLimits {
  const one = (x: unknown, d: BendLimit): BendLimit => {
    const o = (x && typeof x === 'object' ? x : {}) as Record<string, unknown>
    const t = o.total_deg
    return { totalDeg: typeof t === 'number' && Number.isFinite(t) ? t : d.totalDeg }
  }
  const o = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>
  return { raised: one(o.raised, fallback.raised), resting: one(o.resting, fallback.resting) }
}
