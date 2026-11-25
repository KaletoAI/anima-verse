/**
 * PAIR HEIGHT (owner decision 2026-11-25: "build the vertical size compensation") — the VERTICAL half of the pair
 * scale (`pairScale.ts`, which scales only the horizontal root paths about the contact pivot C).
 *
 * THE GAP. A pair/group clip is aligned on figures of 1.70 m. In the game every figure stands on its own support and
 * its body (hips track included) scales with its own a = h / 1.70 about that support. A contact relation's target
 * point sits at the height h_c (metres above the stage floor, measured at 1.70 m at the relation's DEEPEST key frame
 * and stored in the clip's sidecar, `pair_contact_heights`). In the game the receiving figure's target is at
 * s_r + a_r·(h_c − s_r) and the attached part of the entering figure at s_p + a_p·(h_c − s_p) (s = the figure's
 * support height: 0 on the floor, the surface of a bed or seat otherwise). The vertical gap of the relation is
 *     Δ = (s_p + a_p·(h_c − s_p)) − (s_r + a_r·(h_c − s_r))                                     (`pairHeightGap`)
 * — for two figures on the floor (a_p − a_r)·h_c: 1.86 m on 1.70 m at h_c 0.852 m = (1.86/1.70 − 1)·0.852 = 80.2 mm.
 * Δ > 0: the part is ABOVE the target. It closes when the receiving figure rises by Δ or the entering one sinks by Δ:
 *     o_receiver − o_part = Δ                                                                      (one relation)
 * with o_i the constant vertical offset of figure i's hips for the clip (metres, + = up).
 *
 * WHO TAKES IT (`pairRoleRange`, from the role's legs at the deepest frame, stored beside h_c at 1.70 m and scaled by
 * the figure's a about its support):
 *   - a figure on FIXED-HEIGHT FURNITURE (support above FURNITURE_M), LYING or SITTING on its support (hips within
 *     HIPS_REST_M of it) or CARRIED (no leg planted) takes nothing: range [0, 0].
 *   - a leg is PLANTED when its ankle is within FOOT_PLANT_M or its knee within KNEE_PLANT_M of the support. The hips
 *     move straight up/down by δ and a two-bone leg IK (`twoBoneIk.ts`) keeps every planted ankle where the clip put it;
 *     a δ is allowed only when for every planted leg: the leg keeps a bend of MIN_BEND_DEG (never straight), it does not
 *     fold shut (FOLD_M), a planted KNEE moves at most KNEE_HOLD_M, and no knee goes below the support clearance
 *     (KNEE_FLOOR_M, or its own height when already lower) — never through the support. |δ| ≤ MAX_M.
 *   - STANDING (every planted leg bent less than STAND_BEND_DEG, no knee planted): lowering only — the figure bends
 *     its knees; it never rises on straight legs. A kneeling, crouching or squatting figure goes both ways.
 *   The range per direction is the largest |δ| the rule allows (bisection, BISECT_STEPS).
 * THE SOLVE (`pairHeightOffsets`): every figure's offset minimises Σ_relations (o_r − o_p − Δ)² inside its range —
 * a projected Gauss–Seidel: each figure in turn takes the mean of what its relations ask of it, clamped to its range.
 * The figures go in the order of the range they have in the direction their relations first ask (largest first, ties by
 * role), so for a PAIR the figure with the larger available range takes the whole gap and the other only what remains
 * (a split when one alone cannot cover it); for a GROUP the same sweeps are the least-squares solve over all relations.
 * What is still open per relation is its RESIDUAL Δ − (o_r − o_p): left to the attached part's chain bend
 * (`chainBend.ts`), as before.
 *
 * Equal heights (or no stored height): every Δ is exactly 0 and every offset exactly 0 — the consumers then apply
 * nothing, so the pose is bit-identical to today's. A clip without `pair_contact_heights` computes nothing.
 * One constant offset per figure and clip (the deepest frame decides it); the renderers apply it every frame after the
 * clip pose and before phase B (`pairHeightPose.ts`), weighted with the clip's own transition.
 *
 * Pure maths, no three.js. Native twin: native/Core/Figures/PairHeight.cs; vectors shared/test-vectors/pair_scale.json
 * (hand derivations: scripts/smoke_pair_height.mjs).
 */
import type { Vec3 } from './collision'

/** The thresholds and clamps of the rule (metres / degrees). */
export const PAIR_HEIGHT = Object.freeze({
  /** A support above this height is furniture: its figure takes nothing. */
  FURNITURE_M: 0.05,
  /** Hips this close to the support: the figure lies or sits on it and takes nothing. */
  HIPS_REST_M: 0.22,
  /** An ankle this close to the support plants its leg. */
  FOOT_PLANT_M: 0.16,
  /** A knee this close to the support plants its leg (and is held). */
  KNEE_PLANT_M: 0.13,
  /** How far a planted knee may move. */
  KNEE_HOLD_M: 0.02,
  /** No knee joint below this height over the support (unless it already is lower). */
  KNEE_FLOOR_M: 0.06,
  /** The smallest bend a leg keeps (degrees from straight). */
  MIN_BEND_DEG: 12,
  /** A planted leg bent less than this is a standing leg (degrees). */
  STAND_BEND_DEG: 35,
  /** How close a leg may fold (hip–ankle distance over |thigh − shin|). */
  FOLD_M: 0.02,
  /** The sane maximum of one figure's offset. */
  MAX_M: 0.15,
  /** The smallest step the range probes before bisecting. */
  MIN_STEP_M: 1e-4,
  /** Bisection steps of a range. */
  BISECT_STEPS: 40,
  /** Gauss–Seidel sweeps of the solve (it stops early when nothing changes). */
  SWEEPS: 64,
})

/** One leg at the deepest frame: hip, knee and ankle joints (metres; x/z relative to the role's hips). */
export interface PairLeg { hip: Vec3; knee: Vec3; ankle: Vec3 }
/** A role's pose at a relation's deepest frame, at 1.70 m: its support height, its hips height, its legs [left, right]. */
export interface PairRolePose { supportM: number; hipsM: number; legs: PairLeg[] }
/** One contact relation's stored height (`pair_contact_heights[key]`). */
export interface PairContactHeight {
  /** `<part role>><receiving role>:<target>` — the key of `align_status`. */
  key: string; part: string; receiver: string
  /** The target point's height above the stage floor at the deepest frame (metres, 1.70 m). */
  heightM: number
  roles: Record<string, PairRolePose>
}
export type PairStance = 'fixed' | 'resting' | 'free' | 'standing' | 'bent'
export interface PairHeightRange {
  /** The lowest offset (≤ 0) and the highest (≥ 0), metres. */
  down: number; up: number
  stance: PairStance
  /** Per leg [left, right]: planted (the IK holds its ankle). */
  planted: boolean[]
}
export interface PairHeightSolve {
  /** Per role: the hips offset (metres, + = up); 0 = nothing to apply. */
  offsets: Record<string, number>
  /** Per role: which legs the IK holds. */
  planted: Record<string, boolean[]>
  ranges: Record<string, PairHeightRange>
  /** Per relation key: the gap Δ and what is left of it (metres). */
  gaps: Record<string, number>
  residuals: Record<string, number>
}

const BOUND_CM = 300
const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const mul = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k]
const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const len = (a: Vec3): number => Math.sqrt(dot(a, a))
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const DEG = Math.PI / 180

/** The vertical gap Δ of one relation (module docstring): part height minus target height, metres. */
export function pairHeightGap(heightM: number, partSupportM: number, aPart: number, recvSupportM: number, aRecv: number): number {
  return (aPart - aRecv) * heightM + partSupportM * (1 - aPart) - recvSupportM * (1 - aRecv)
}

/** A role's pose scaled by a about its support: x, z → a·x, a·z (relative to its hips), y → s + a·(y − s). */
export function scaleRolePose(pose: PairRolePose, a: number): PairRolePose {
  if (a === 1) return pose
  const s = pose.supportM
  const p = (v: Vec3): Vec3 => [a * v[0], s + a * (v[1] - s), a * v[2]]
  return { supportM: s, hipsM: s + a * (pose.hipsM - s), legs: pose.legs.map((l) => ({ hip: p(l.hip), knee: p(l.knee), ankle: p(l.ankle) })) }
}

/** The knee a two-bone IK (`twoBoneIk`) puts the leg's knee at when the hip is at `hip` and the ankle reaches `target`,
 *  the pole = the current knee — the same construction, without the rotations. */
export function ikKnee(hip: Vec3, knee: Vec3, ankle: Vec3, target: Vec3): Vec3 {
  const l1 = len(sub(knee, hip)), l2 = len(sub(ankle, knee))
  const toT = sub(target, hip)
  let d = len(toT)
  if (l1 < 1e-9 || l2 < 1e-9 || d < 1e-9) return knee
  const t = mul(toT, 1 / d)
  d = Math.min(Math.max(d, Math.abs(l1 - l2) + 1e-9), l1 + l2)
  const p = sub(knee, hip)
  let u = sub(p, mul(t, dot(p, t)))
  if (len(u) < 1e-9) {
    u = cross(t, [1, 0, 0])
    if (len(u) < 1e-6) u = cross(t, [0, 0, 1])
  }
  u = mul(u, 1 / len(u))
  const cosA = Math.max(-1, Math.min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
  const sinA = Math.sqrt(Math.max(0, 1 - cosA * cosA))
  return add(hip, add(mul(t, l1 * cosA), mul(u, l1 * sinA)))
}

/** The leg's bend, degrees from straight (0 = straight, 180 = folded shut). */
export function legBendDeg(leg: PairLeg): number {
  const a = sub(leg.knee, leg.hip), b = sub(leg.ankle, leg.knee)
  const la = len(a), lb = len(b)
  if (la < 1e-9 || lb < 1e-9) return 0
  return Math.acos(Math.max(-1, Math.min(1, dot(a, b) / (la * lb)))) / DEG
}

function legPlanted(leg: PairLeg, s: number): boolean {
  return leg.ankle[1] - s <= PAIR_HEIGHT.FOOT_PLANT_M || leg.knee[1] - s <= PAIR_HEIGHT.KNEE_PLANT_M
}

/** Whether the hips may move by δ (metres) with every planted ankle held (module docstring WHO TAKES IT). */
export function pairOffsetAllowed(pose: PairRolePose, planted: readonly boolean[], delta: number): boolean {
  if (Math.abs(delta) > PAIR_HEIGHT.MAX_M + 1e-12) return false
  const s = pose.supportM
  const cosMin = Math.cos(PAIR_HEIGHT.MIN_BEND_DEG * DEG)
  for (let i = 0; i < pose.legs.length; i++) {
    if (!planted[i]) continue
    const leg = pose.legs[i]
    const l1 = len(sub(leg.knee, leg.hip)), l2 = len(sub(leg.ankle, leg.knee))
    const up: Vec3 = [0, delta, 0]
    const hip = add(leg.hip, up)
    const d = len(sub(hip, leg.ankle))
    if (d > Math.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * cosMin) + 1e-12) return false
    if (d < Math.abs(l1 - l2) + PAIR_HEIGHT.FOLD_M) return false
    const knee = ikKnee(hip, add(leg.knee, up), add(leg.ankle, up), leg.ankle)
    if (leg.knee[1] - s <= PAIR_HEIGHT.KNEE_PLANT_M && len(sub(knee, leg.knee)) > PAIR_HEIGHT.KNEE_HOLD_M + 1e-12) return false
    if (knee[1] < s + Math.min(leg.knee[1] - s, PAIR_HEIGHT.KNEE_FLOOR_M) - 1e-12) return false
  }
  return true
}

/** The range one direction allows (sign = +1 up, −1 down): the whole MAX_M, nothing, or the bisected limit. */
function reach(pose: PairRolePose, planted: readonly boolean[], sign: number): number {
  if (pairOffsetAllowed(pose, planted, sign * PAIR_HEIGHT.MAX_M)) return sign * PAIR_HEIGHT.MAX_M
  if (!pairOffsetAllowed(pose, planted, sign * PAIR_HEIGHT.MIN_STEP_M)) return 0
  let lo: number = PAIR_HEIGHT.MIN_STEP_M, hi: number = PAIR_HEIGHT.MAX_M
  for (let k = 0; k < PAIR_HEIGHT.BISECT_STEPS; k++) {
    const mid = (lo + hi) / 2
    if (pairOffsetAllowed(pose, planted, sign * mid)) lo = mid; else hi = mid
  }
  return sign * lo
}

/** The offsets a role may take for a figure of scale `a` (its stored pose scaled about its support). */
export function pairRoleRange(pose: PairRolePose, a: number): PairHeightRange {
  const p = scaleRolePose(pose, a)
  const s = p.supportM
  const none = (stance: PairStance, planted: boolean[]): PairHeightRange => ({ down: 0, up: 0, stance, planted })
  const planted = p.legs.map((l) => legPlanted(l, s))
  if (s > PAIR_HEIGHT.FURNITURE_M) return none('fixed', planted.map(() => false))
  if (p.hipsM - s < PAIR_HEIGHT.HIPS_REST_M) return none('resting', planted.map(() => false))
  if (!planted.some(Boolean)) return none('free', planted)
  const standing = p.legs.every((l, i) => !planted[i]
    || (legBendDeg(l) < PAIR_HEIGHT.STAND_BEND_DEG && l.knee[1] - s > PAIR_HEIGHT.KNEE_PLANT_M))
  return { down: reach(p, planted, -1), up: standing ? 0 : reach(p, planted, 1), stance: standing ? 'standing' : 'bent', planted }
}

/** The offsets of every role of a clip for the figures' scales (module docstring THE SOLVE). `scaleOf(role)` = h / 1.70. */
export function pairHeightOffsets(relations: readonly PairContactHeight[], scaleOf: (role: string) => number): PairHeightSolve {
  const out: PairHeightSolve = { offsets: {}, planted: {}, ranges: {}, gaps: {}, residuals: {} }
  const poses = new Map<string, PairRolePose>()
  for (const r of relations) for (const role of [r.part, r.receiver]) {
    const pose = r.roles[role]
    if (pose && !poses.has(role)) poses.set(role, pose)
  }
  const usable = relations.filter((r) => poses.has(r.part) && poses.has(r.receiver) && r.part !== r.receiver)
  for (const r of usable) {
    out.gaps[r.key] = pairHeightGap(r.heightM, poses.get(r.part)!.supportM, scaleOf(r.part),
      poses.get(r.receiver)!.supportM, scaleOf(r.receiver))
  }
  const roles = [...poses.keys()].sort()
  for (const role of roles) out.offsets[role] = 0
  if (usable.every((r) => out.gaps[r.key] === 0)) {
    for (const r of usable) out.residuals[r.key] = 0
    return out
  }
  for (const role of roles) {
    out.ranges[role] = pairRoleRange(poses.get(role)!, scaleOf(role))
    out.planted[role] = out.ranges[role].planted
  }
  const o = out.offsets
  /** What a role's relations ask of it with the others where they are: the mean (the least-squares optimum). */
  const want = (role: string): number | null => {
    let sum = 0, n = 0
    for (const r of usable) {
      if (r.receiver === role) { sum += o[r.part] + out.gaps[r.key]; n++ }
      if (r.part === role) { sum += o[r.receiver] - out.gaps[r.key]; n++ }
    }
    return n ? sum / n : null
  }
  const first = new Map(roles.map((role) => {
    const w = want(role) ?? 0
    const rg = out.ranges[role]
    return [role, w > 0 ? rg.up : w < 0 ? -rg.down : 0] as const
  }))
  const order = [...roles].sort((x, y) => (first.get(y)! - first.get(x)!) || (x < y ? -1 : x > y ? 1 : 0))
  for (let sweep = 0; sweep < PAIR_HEIGHT.SWEEPS; sweep++) {
    let change = 0
    for (const role of order) {
      const w = want(role)
      if (w === null) continue
      const rg = out.ranges[role]
      const v = Math.max(rg.down, Math.min(rg.up, w))
      change = Math.max(change, Math.abs(v - o[role]))
      o[role] = v
    }
    if (change < 1e-12) break
  }
  for (const r of usable) out.residuals[r.key] = out.gaps[r.key] - (o[r.receiver] - o[r.part])
  return out
}

// ── the sidecar wire (`pair_contact_heights`, cm) ──

const num = (v: unknown, lo = -BOUND_CM, hi = BOUND_CM): v is number =>
  typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi
const vec = (v: unknown): v is [number, number, number] => Array.isArray(v) && v.length === 3 && v.every((x) => num(x))
const KEY = /^([a-e])>([a-e]):([a-z_]{1,40})$/

/** One role of the wire → metres; null when malformed. */
function roleOf(w: unknown): PairRolePose | null {
  if (!w || typeof w !== 'object') return null
  const r = w as { support_cm?: unknown; hips_cm?: unknown; legs?: unknown }
  if (!num(r.support_cm, -50) || !num(r.hips_cm) || !Array.isArray(r.legs) || r.legs.length > 2) return null
  const legs: PairLeg[] = []
  for (const l of r.legs) {
    if (!Array.isArray(l) || l.length !== 3 || !l.every(vec)) return null
    const m = (v: number[]): Vec3 => [v[0] / 100, v[1] / 100, v[2] / 100]
    legs.push({ hip: m(l[0]), knee: m(l[1]), ankle: m(l[2]) })
  }
  return { supportM: r.support_cm / 100, hipsM: r.hips_cm / 100, legs }
}

/** The clip's stored contact heights (the listing's `pair_contact_heights`), sorted by key; [] for none or malformed
 *  (a malformed relation is skipped, the others stay). */
export function pairContactHeightsOf(wire: unknown): PairContactHeight[] {
  if (!wire || typeof wire !== 'object' || Array.isArray(wire)) return []
  const out: PairContactHeight[] = []
  for (const key of Object.keys(wire).sort()) {
    const m = KEY.exec(key)
    const e = (wire as Record<string, unknown>)[key] as { height_cm?: unknown; roles?: unknown } | null
    if (!m || m[1] === m[2] || !e || typeof e !== 'object' || !num(e.height_cm, 0)) continue
    if (!e.roles || typeof e.roles !== 'object') continue
    const roles: Record<string, PairRolePose> = {}
    let bad = false
    for (const [role, rw] of Object.entries(e.roles as Record<string, unknown>)) {
      const pose = /^[a-e]$/.test(role) ? roleOf(rw) : null
      if (!pose) { bad = true; break }
      roles[role] = pose
    }
    if (bad || !roles[m[1]] || !roles[m[2]]) continue
    out.push({ key, part: m[1], receiver: m[2], heightM: e.height_cm / 100, roles })
  }
  return out
}

/** One role's wire entry (cm, 0.1 cm) from its joints at the deepest frame: `hips` and every leg's joints in stage
 *  metres; x/z are stored relative to the hips. */
export function pairRolePoseCm(hips: Vec3, legs: readonly PairLeg[], supportM: number):
  { support_cm: number; hips_cm: number; legs: [number, number, number][][] } {
  const r = (v: number) => Math.max(-BOUND_CM, Math.min(BOUND_CM, Math.round(v * 1000) / 10 || 0))
  const rel = (p: Vec3): [number, number, number] => [r(p[0] - hips[0]), r(p[1]), r(p[2] - hips[2])]
  return { support_cm: r(supportM), hips_cm: r(hips[1]), legs: legs.map((l) => [rel(l.hip), rel(l.knee), rel(l.ankle)]) }
}
