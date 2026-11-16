/**
 * CHAIN BEND (Ruling A145) — before a pair fit moves or turns the entering figure, its attached part BENDS toward the
 * contact target, within limits; only what the bend cannot reach is left to the shift/turn (`pairFit.ts`). One
 * geometry for both renderers: Auto-align, the pair check, the place preview's live fit and client3d's runtime fit call
 * the same functions on the same `FigureRuntime.inspect()` chain, and `FigureRuntime.bendChain` applies the result to
 * the bones the same way in both.
 *
 * THE CHAIN (world metres): the attached-part chain's points P_0 … P_n — P_i the joint of link i (`opChains` segment
 * a), P_n the last link's tip. The root joint P_0 sits on the body and never bends; the BEND JOINTS are the last
 * `BEND_JOINTS` joints before the tip among P_1 … P_{n−1} (`bendJoints`). A bend at joint j turns every point past it
 * rigidly about P_j.
 *
 * THE TARGET (a channel or a point target, opening/point O, unit axis u): every effector point E is pulled onto the
 * axis LINE at its own axial coordinate, G(E) = O + u · ((E − O)·u) — the bend removes the lateral, the axial part
 * (how far in) stays the shift's job. The effectors: the tip P_n always; for a CHANNEL, once the tip is near or past
 * the opening (s_n ≥ −`BEND_NEAR_M` on the chain as handed in), also the tip link's joint P_{n−1} and every joint past the bending joint that is inside
 * (s > 0) — so a chain whose tip is in the channel lies ALONG its axis (the bend comes from following the axis), not
 * just with its tip on it.
 *
 * THE SOLVE (`solveChainBend`): cyclic coordinate descent, `BEND_SWEEPS` sweeps, each from the tip-most bend joint to
 * the root-most. At joint j each effector k asks for the smallest turn r_k (axis (E_k − P_j) × (G_k − P_j), angle
 * between them); the step is their mean rotation vector. The step is then CLAMPED: the joint's accumulated bend
 * |D_j| ≤ `jointDeg` and the sum over the joints Σ|D_j| ≤ `totalDeg` — the largest share of the step for which both
 * hold (bisection, `BEND_BISECT` halvings). D_j is the joint's own turn RELATIVE to its parent link (a later turn of a parent
 * joint conjugates it, its angle is unchanged): what the bones get.
 *
 * THE LIMITS come from the chain's state: `raised` ∈ [0, 1] is the chain's straightening fraction (the extension
 * rig's raised state, `SecondaryMotion.opChains().raised`); the limit is the linear blend resting → raised
 * (`bendLimitAt`). Defaults `BEND_LIMITS_DEFAULT`: raised 15° per joint / 35° in all, resting 45° / 120°; a package
 * defaults its clip kinds (capability `clip_bend_limit_defaults`), a clip overrides in the Poses tab.
 *
 * THE ROOT (Ruling A150): before the chain bends, the part may PITCH at its root joint P_0 — the attachment, "from the
 * base" — about the body's side axis, and yaw a little about the body's up axis (`opts.frame`, the entering figure's
 * clip frame; without it the root stays put, the A145 solve). It is the FIRST lever: `ROOT_SWEEPS` steps at P_0 with
 * the tip (and, on a channel follow, the tip link's joint) as effectors, each step's mean rotation vector w split into
 * pitch α = s·(w·side) and yaw β = w·up (the twist about the part's own axis is dropped), the accumulated α clamped to
 * [−`rootDownDeg`, `rootUpDeg`] and β to ±`rootYawDeg`. Pitch UP (α > 0) is the turn that raises the tip along the
 * body's up axis: s = sign(((side × d)·up)) for the chain direction d = P_n − P_0 as handed in. The root has its own
 * limits per state (blended like the others) and does not count against `totalDeg`; its turn is joint 0 of `turns`.
 *
 * THE LAMP (`bendLamp`): yellow when the bend used reaches `BEND_AT_LIMIT` of the total (or every joint its own) —
 * the part is at its limit and the rest of the error is the shift's/turn's; green otherwise.
 */
import type { Vec3 } from './collision'

export interface BendLimit {
  jointDeg: number; totalDeg: number
  /** Ruling A150: the root joint's pitch up / pitch down / yaw either way (degrees; absent = 0, the root stays). */
  rootUpDeg?: number; rootDownDeg?: number; rootYawDeg?: number
}
export interface BendLimits { raised: BendLimit; resting: BendLimit }
export type Quat = [number, number, number, number]

export const BEND_LIMITS_DEFAULT: BendLimits = Object.freeze({
  raised: Object.freeze({ jointDeg: 15, totalDeg: 35, rootUpDeg: 35, rootDownDeg: 45, rootYawDeg: 10 }),
  resting: Object.freeze({ jointDeg: 45, totalDeg: 120, rootUpDeg: 45, rootDownDeg: 80, rootYawDeg: 15 }),
}) as BendLimits
/** Ruling A150: steps of the root lever (module docstring THE ROOT). */
export const ROOT_SWEEPS = 6
/** How many joints before the tip bend (root → mid → tip of a 2–3 joint part). */
export const BEND_JOINTS = 3
export const BEND_SWEEPS = 8
/** The tip counts as at the opening from this far before it (metres; the channel follow starts there). */
export const BEND_NEAR_M = 0.03
/** Halvings of the clamp's bisection (share precision 2⁻¹⁶). */
export const BEND_BISECT = 16
/** Share of the limit from which the lamp says "at the limit". */
export const BEND_AT_LIMIT = 0.98

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

/** The limit at the chain's raised fraction (module docstring THE LIMITS). */
export function bendLimitAt(limits: BendLimits, raised: number): BendLimit {
  const r = Math.max(0, Math.min(1, Number.isFinite(raised) ? raised : 0))
  const mix = (k: keyof BendLimit) => (limits.resting[k] ?? 0) + ((limits.raised[k] ?? 0) - (limits.resting[k] ?? 0)) * r
  return { jointDeg: mix('jointDeg'), totalDeg: mix('totalDeg'), rootUpDeg: mix('rootUpDeg'),
    rootDownDeg: mix('rootDownDeg'), rootYawDeg: mix('rootYawDeg') }
}

/** The bend joints of a chain of n links (points P_0 … P_n): the last `BEND_JOINTS` of P_1 … P_{n−1}. */
export function bendJoints(n: number): number[] {
  const out: number[] = []
  for (let j = Math.max(1, n - BEND_JOINTS); j <= n - 1; j++) out.push(j)
  return out
}

export interface BendResult {
  /** The bent points P'_0 … P'_n. */
  points: Vec3[]
  /** Per bend joint (in `joints` order): its index and its turn D_j relative to its parent link (world axes of the
   *  BENT pose: apply root-most first, each about its own joint after its parents moved). */
  turns: { joint: number; q: Quat }[]
  jointDeg: number[]
  totalDeg: number
  limit: BendLimit
  atLimit: boolean
  /** Ruling A150: the root's pitch (+ up) and yaw used (degrees) and whether either reached its limit. */
  rootPitchDeg: number
  rootYawDeg: number
  rootAtLimit: boolean
}
/** Ruling A150: the entering figure's body axes (world unit vectors) the root lever turns about. */
export interface BendFrame { side: Vec3; up: Vec3 }

/** Bend `points` toward the axis line through `o` along unit `u` (module docstring THE SOLVE). `channel` adds the inside
 *  joints as effectors. A limit of 0 returns the chain unbent. */
export function solveChainBend(points: readonly Vec3[], o: Vec3, u: Vec3, limit: BendLimit,
  opts: { channel?: boolean; joints?: readonly number[]; sweeps?: number; frame?: BendFrame | null } = {}): BendResult {
  const P = points.map((p) => [p[0], p[1], p[2]] as Vec3)
  const n = P.length - 1
  const joints = opts.joints ?? bendJoints(n)
  const D: Quat[] = joints.map(() => [0, 0, 0, 1])
  const maxJ = Math.max(0, limit.jointDeg) * DEG, maxT = Math.max(0, limit.totalDeg) * DEG
  const total = () => D.reduce((a, q) => a + quatAngle(q), 0)
  const onAxis = (e: Vec3): Vec3 => add(o, mul(u, dot(sub(e, o), u)))
  // Channel follow: decided once, on the chain as handed in (no flip mid-solve).
  const follow = !!opts.channel && n >= 1 && dot(sub(P[n], o), u) >= -BEND_NEAR_M
  // Ruling A150 THE ROOT: pitch (+ a little yaw) at P_0 first.
  let alpha = 0, beta = 0, Qr: Quat = [0, 0, 0, 1]
  const upR = Math.max(0, limit.rootUpDeg ?? 0) * DEG, downR = Math.max(0, limit.rootDownDeg ?? 0) * DEG
  const yawR = Math.max(0, limit.rootYawDeg ?? 0) * DEG
  const fr = opts.frame
  if (fr && n >= 1 && (upR > 0 || downR > 0 || yawR > 0)) {
    const s = Math.sign(dot(cross(fr.side, sub(P[n], P[0])), fr.up)) || 1
    const p0 = P[0]
    for (let it = 0; it < ROOT_SWEEPS; it++) {
      const eff = follow && n >= 2 ? [n, n - 1] : [n]
      let w: Vec3 = [0, 0, 0]
      for (const k of eff) {
        const a = sub(P[k], p0), b = sub(onAxis(P[k]), p0)
        const la = len(a), lb = len(b)
        if (la < 1e-9 || lb < 1e-9) continue
        const c = cross(a, b), lc = len(c)
        if (lc < 1e-12) continue
        w = add(w, mul(c, Math.atan2(lc, dot(a, b)) / lc / eff.length))
      }
      const na = Math.max(-downR, Math.min(upR, alpha + s * dot(w, fr.side)))
      const nb = Math.max(-yawR, Math.min(yawR, beta + dot(w, fr.up)))
      const da = na - alpha, db = nb - beta
      if (Math.abs(da) + Math.abs(db) < 1e-9) break
      alpha = na; beta = nb
      const st = quatOf(add(mul(fr.side, s * da), mul(fr.up, db)))
      for (let k = 1; k <= n; k++) P[k] = add(p0, quatRotate(st, sub(P[k], p0)))
      Qr = quatMul(st, Qr)
    }
  }
  if (n >= 1 && maxJ > 0 && maxT > 0) {
    for (let sweep = 0; sweep < (opts.sweeps ?? BEND_SWEEPS); sweep++) {
      for (let ji = joints.length - 1; ji >= 0; ji--) {
        const j = joints[ji]
        const pj = P[j]
        const eff = [n]
        if (follow) {
          for (let k = j + 1; k < n; k++) if (k === n - 1 || dot(sub(P[k], o), u) > 0) eff.push(k)
        }
        let w: Vec3 = [0, 0, 0]
        for (const k of eff) {
          const a = sub(P[k], pj), b = sub(onAxis(P[k]), pj)
          const la = len(a), lb = len(b)
          if (la < 1e-9 || lb < 1e-9) continue
          const c = cross(a, b), lc = len(c)
          if (lc < 1e-12) continue
          const ang = Math.atan2(lc, dot(a, b))
          w = add(w, mul(c, ang / lc / eff.length))
        }
        const ang = len(w)
        if (ang < 1e-9) continue
        const others = total() - quatAngle(D[ji])
        const fits = (f: number) => {
          const st = quatOf(mul(w, f))
          const a = quatAngle(quatMul(st, D[ji]))
          return a <= maxJ + 1e-9 && others + a <= maxT + 1e-9 ? st : null
        }
        let step = fits(1)
        if (!step) {
          // The largest share of the step within both limits (bisection, `BEND_BISECT` halvings).
          let lo = 0, hi = 1
          for (let h = 0; h < BEND_BISECT; h++) { const mid = (lo + hi) / 2; if (fits(mid)) lo = mid; else hi = mid }
          step = lo > 0 ? fits(lo) : null
        }
        if (!step) continue
        // Turn the points past j about P_j; the joint's own turn grows, the children's (relative) turns are conjugated.
        for (let k = j + 1; k <= n; k++) P[k] = add(pj, quatRotate(step, sub(P[k], pj)))
        D[ji] = quatMul(step, D[ji])
        for (let ci = ji + 1; ci < joints.length; ci++) D[ci] = quatMul(quatMul(step, D[ci]), conj(step))
      }
    }
  }
  const jointDeg = D.map((q) => quatAngle(q) / DEG)
  const totalDeg = jointDeg.reduce((a, v) => a + v, 0)
  const atLimit = (limit.totalDeg > 0 && totalDeg >= BEND_AT_LIMIT * limit.totalDeg)
    || (jointDeg.length > 0 && jointDeg.every((v) => v >= BEND_AT_LIMIT * limit.jointDeg))
  const turns = joints.map((joint, i) => ({ joint, q: D[i] }))
  if (quatAngle(Qr) > 1e-9) turns.unshift({ joint: 0, q: Qr })
  const rootAtLimit = (alpha > 0 && upR > 0 && alpha >= BEND_AT_LIMIT * upR) || (alpha < 0 && downR > 0 && -alpha >= BEND_AT_LIMIT * downR)
    || (yawR > 0 && Math.abs(beta) >= BEND_AT_LIMIT * yawR)
  return { points: P, turns, jointDeg, totalDeg, limit, atLimit, rootPitchDeg: alpha / DEG, rootYawDeg: beta / DEG,
    rootAtLimit }
}

/** Yellow at the limit (module docstring THE LAMP: the total, or every joint at its own), green below. */
export function bendLamp(r: { atLimit: boolean }): 'green' | 'yellow' {
  return r.atLimit ? 'yellow' : 'green'
}

/** Read a stored/declared limits object ({raised: {joint_deg, total_deg}, resting: …}, degrees) over the defaults. */
export function bendLimitsOf(v: unknown, fallback: BendLimits = BEND_LIMITS_DEFAULT): BendLimits {
  const one = (x: unknown, d: BendLimit): BendLimit => {
    const o = (x && typeof x === 'object' ? x : {}) as Record<string, unknown>
    const num = (k: string, dv: number) => (typeof o[k] === 'number' && Number.isFinite(o[k] as number) ? o[k] as number : dv)
    return { jointDeg: num('joint_deg', d.jointDeg), totalDeg: num('total_deg', d.totalDeg),
      rootUpDeg: num('root_up_deg', d.rootUpDeg ?? 0), rootDownDeg: num('root_down_deg', d.rootDownDeg ?? 0),
      rootYawDeg: num('root_yaw_deg', d.rootYawDeg ?? 0) }
  }
  const o = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>
  return { raised: one(o.raised, fallback.raised), resting: one(o.resting, fallback.resting) }
}
