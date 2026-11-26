/**
 * PAIR HEIGHT (owner decision 2026-11-25, reworked 2026-11-26 on the measured causes) — the VERTICAL half of a pair
 * clip on figures of real heights (`pairScale.ts` scales only the horizontal root paths about the contact pivot).
 *
 * WHAT IS MEASURED. Nothing is stored. When a pair interaction starts, its renderer SAMPLES one loop of the clip as the
 * figures really stand — every figure on its own ground point, at its own scale, with its own body, WITHOUT the
 * compensation — at N phases (`PAIR_HEIGHT_SAMPLES`), without rendering. Per sampled phase and role: its ground
 * height, its hips and its legs (`PairHeightRoleFrame`, world metres). Per phase and contact RELATION (part role →
 * receiving role): the part's STRAIGHT AXIS — the attached part's chain at rest on the posed body (no bend; the clip's
 * root angle included), root point P, unit direction u, length L — and the receiving figure's OPENING O (its channel,
 * mouth or hand as that renderer resolves them; a renderer without built channels uses the declared anchors on the
 * skeleton). Terrain, the figure scale and where the opening sits on THIS body are therefore in the numbers already.
 *
 * THE CONTACT PHASE of a relation (`pairContactFrame`): the sampled phase where O is closest to the straight segment
 * P … P + L·u.
 * THE GAP there (`pairAxisGap`): the height of the axis LINE where it is horizontally nearest to O, minus O's height:
 *     λ = ⟨(O − P)_xz, u_xz⟩ / |u_xz|²   (λ ≥ 0; an axis with |u_xz|² < 1e-6 takes λ = ⟨O − P, u⟩)
 *     Δ = P_y + λ·u_y − O_y
 * Δ > 0: the axis passes ABOVE the opening. Moving the part figure's hips by o_p moves P by o_p (the chain rides the
 * hips rigidly), moving the receiver's by o_r moves O by o_r, so the axis points at the opening (vertically) when
 *     o_receiver − o_part = Δ                                                                       (one relation)
 * A |Δ| below `DEADBAND_M` counts as 0 (a clip aligned on its own needs nothing). What is left is the chain bend's.
 *
 * WHO TAKES IT (`pairRoleClass`, `pairRoleRange`), from the role's sampled frames — the WHOLE loop, never one frame:
 *   - FIXED: the renderer says the figure sits on a place (furniture) — takes nothing.
 *   - per frame the figure's LOWEST joint (ankles and knees); a joint is DOWN in that frame when it is within
 *     `DOWN_FRAC`·leg length above that lowest joint, UP above `UP_FRAC`·leg length, in between undecided (the
 *     hysteresis band: a joint there counts neither way). A leg is PLANTED when its ankle or knee is down in more frames
 *     than up; its KNEE is held when the knee is. Both thresholds are fractions of the leg's own length, so a figure's
 *     scale cannot flip a leg, and a leg lifted for most of the loop is never planted.
 *   - CARRIED ('free': the median lowest joint more than `CARRIED_M` above the ground), no planted leg, or RESTING (the
 *     median hips less than `HIPS_REST_M` above the lowest joint: lying, sitting) — takes nothing.
 *   - STANDING (every planted leg bent less than `STAND_BEND_DEG` in most frames, no knee held): lowering only.
 *     Kneeling, crouching, squatting: both ways.
 *   The range per direction is the smallest that EVERY sampled frame allows (`pairOffsetAllowed` per frame: the hips
 *   move straight by δ, a two-bone IK keeps each planted ankle, the leg keeps MIN_BEND_DEG, does not fold shut, a held
 *   knee moves at most KNEE_HOLD_M, no knee below the ground clearance; |δ| ≤ MAX_M; bisection).
 * THE SOLVE (`pairHeightOffsets`): every figure's offset minimises Σ_relations (o_r − o_p − Δ)² inside its range — a
 * projected Gauss–Seidel, the figure with the larger range in the asked direction first (a pair: it takes the whole gap,
 * the other only what remains). RESIDUAL = Δ − (o_r − o_p).
 *
 * One constant offset per figure and clip; the renderers apply it every frame after the clip pose and before phase B
 * (`pairHeightPose.ts`), weighted with the clip's own transition. Pure maths, no three.js. Native twin:
 * native/Core/Figures/PairHeight.cs; vectors shared/test-vectors/pair_scale.json (hand derivations:
 * scripts/smoke_pair_height.mjs).
 */
import type { Vec3 } from './collision'

/** The thresholds and clamps of the rule (metres / degrees / fractions). */
export const PAIR_HEIGHT = Object.freeze({
  /** A gap below this counts as none. */
  DEADBAND_M: 0.005,
  /** The median hips this close above the lowest joint: lying or sitting — takes nothing. */
  HIPS_REST_M: 0.22,
  /** The median lowest joint this far above the ground: carried — takes nothing. */
  CARRIED_M: 0.35,
  /** A joint within this fraction of its leg's length above the frame's lowest joint is DOWN. */
  DOWN_FRAC: 0.12,
  /** A joint more than this fraction above it is UP (between the two: undecided). */
  UP_FRAC: 0.22,
  /** How far a held knee may move. */
  KNEE_HOLD_M: 0.02,
  /** No knee joint below this height over the ground (unless it already is lower). */
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
/** How many phases of one loop a renderer samples. */
export const PAIR_HEIGHT_SAMPLES = 24

/** One leg: hip, knee and ankle joints (world metres). */
export interface PairLeg { hip: Vec3; knee: Vec3; ankle: Vec3 }
/** One role at one sampled phase (world metres): the ground under it, its hips height, its legs [left, right]. */
export interface PairHeightRoleFrame { groundM: number; hipsM: number; legs: PairLeg[] }
export interface PairHeightRole { frames: PairHeightRoleFrame[]; fixed?: boolean }
/** One relation at one sampled phase: the part's straight axis (root, unit direction, length) and the opening. */
export interface PairHeightRelationFrame { root: Vec3; axis: Vec3; lengthM: number; opening: Vec3 }
export interface PairHeightRelation {
  /** `<part role>><receiving role>:<target>`. */
  key: string; part: string; receiver: string
  /** Per sampled phase (the roles' frame index); null where the part or the opening could not be resolved. */
  frames: (PairHeightRelationFrame | null)[]
}
export interface PairHeightInput { roles: Record<string, PairHeightRole>; relations: PairHeightRelation[] }
export type PairStance = 'fixed' | 'resting' | 'free' | 'standing' | 'bent'
export interface PairRoleClass {
  stance: PairStance
  /** Per leg [left, right]: planted (the IK holds its ankle) / its knee held. */
  planted: boolean[]; kneeHeld: boolean[]
}
export interface PairHeightRange extends PairRoleClass {
  /** The lowest offset (≤ 0) and the highest (≥ 0), metres. */
  down: number; up: number
}
export interface PairHeightSolve {
  /** Per role: the hips offset (metres, + = up); 0 = nothing to apply. */
  offsets: Record<string, number>
  /** Per role: which legs the IK holds. */
  planted: Record<string, boolean[]>
  ranges: Record<string, PairHeightRange>
  /** Per relation key: its contact phase (frame index), the gap Δ there and what is left of it (metres). */
  contactFrames: Record<string, number>
  gaps: Record<string, number>
  residuals: Record<string, number>
}

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const mul = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k]
const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const len = (a: Vec3): number => Math.sqrt(dot(a, a))
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const DEG = Math.PI / 180
const median = (xs: number[]): number => {
  const s = [...xs].sort((a, b) => a - b)
  return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : 0
}

/** A relation frame from the part chain's points (root first, tip last) and the opening; null when degenerate. */
export function pairRelationFrame(chain: readonly Vec3[], opening: Vec3): PairHeightRelationFrame | null {
  if (chain.length < 2) return null
  const root = chain[0], d = sub(chain[chain.length - 1], root), l = len(d)
  if (!(l > 1e-6)) return null
  return { root, axis: mul(d, 1 / l), lengthM: l, opening }
}

/** The distance of the opening from the straight segment P … P + L·u. */
export function pairAxisDistance(f: PairHeightRelationFrame): number {
  const t = Math.max(0, Math.min(f.lengthM, dot(sub(f.opening, f.root), f.axis)))
  return len(sub(f.opening, add(f.root, mul(f.axis, t))))
}

/** The relation's contact phase: the frame index of the smallest `pairAxisDistance`; −1 when no frame resolved. */
export function pairContactFrame(frames: readonly (PairHeightRelationFrame | null)[]): number {
  let best = -1, d = Infinity
  frames.forEach((f, i) => { if (!f) return; const x = pairAxisDistance(f); if (x < d) { d = x; best = i } })
  return best
}

/** The vertical gap of one frame (module docstring THE GAP): the axis line's height where it is horizontally nearest
 *  to the opening, minus the opening's height. */
export function pairAxisGap(f: PairHeightRelationFrame): number {
  const u = f.axis, o = sub(f.opening, f.root)
  const h2 = u[0] * u[0] + u[2] * u[2]
  const lambda = Math.max(0, h2 > 1e-6 ? (o[0] * u[0] + o[2] * u[2]) / h2 : dot(o, u))
  return f.root[1] + lambda * u[1] - f.opening[1]
}

/** The angle (degrees) between the straight axis and the direction from its root to the opening, with the part
 *  figure moved by `oPart` and the receiver by `oRecv` — the bend the chain still needs. */
export function pairNeededBendDeg(f: PairHeightRelationFrame, oPart = 0, oRecv = 0): number {
  const to = sub(add(f.opening, [0, oRecv, 0]), add(f.root, [0, oPart, 0]))
  const l = len(to)
  return l > 1e-9 ? Math.acos(Math.max(-1, Math.min(1, dot(f.axis, to) / l))) / DEG : 0
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

const legLength = (l: PairLeg): number => len(sub(l.knee, l.hip)) + len(sub(l.ankle, l.knee))

/** The class of one role over its sampled frames (module docstring WHO TAKES IT). */
export function pairRoleClass(role: PairHeightRole): PairRoleClass {
  const frames = role.frames
  const nLegs = frames.reduce((n, f) => Math.max(n, f.legs.length), 0)
  const none = (stance: PairStance): PairRoleClass =>
    ({ stance, planted: Array(nLegs).fill(false), kneeHeld: Array(nLegs).fill(false) })
  if (role.fixed) return none('fixed')
  if (!frames.length || !nLegs) return none('free')
  const lowest = frames.map((f) => Math.min(...f.legs.flatMap((l) => [l.ankle[1], l.knee[1]])))
  if (median(frames.map((f, i) => f.hipsM - lowest[i])) < PAIR_HEIGHT.HIPS_REST_M) return none('resting')
  if (median(frames.map((f, i) => lowest[i] - f.groundM)) > PAIR_HEIGHT.CARRIED_M) return none('free')
  const planted: boolean[] = [], kneeHeld: boolean[] = []
  for (let i = 0; i < nLegs; i++) {
    let legDown = 0, legUp = 0, kneeDown = 0, kneeUp = 0
    frames.forEach((f, k) => {
      const l = f.legs[i]
      if (!l) return
      const ll = legLength(l)
      const state = (y: number) => (y - lowest[k] <= PAIR_HEIGHT.DOWN_FRAC * ll ? 1 : y - lowest[k] > PAIR_HEIGHT.UP_FRAC * ll ? -1 : 0)
      const a = state(l.ankle[1]), kn = state(l.knee[1])
      const leg = Math.max(a, kn)
      if (leg > 0) legDown++; else if (leg < 0) legUp++
      if (kn > 0) kneeDown++; else if (kn < 0) kneeUp++
    })
    planted.push(legDown > legUp)
    kneeHeld.push(planted[i] && kneeDown > kneeUp)
  }
  if (!planted.some(Boolean)) return { stance: 'free', planted, kneeHeld }
  const standing = !kneeHeld.some(Boolean) && planted.every((p, i) => !p ||
    frames.filter((f) => f.legs[i] && legBendDeg(f.legs[i]) < PAIR_HEIGHT.STAND_BEND_DEG).length * 2 > frames.length)
  return { stance: standing ? 'standing' : 'bent', planted, kneeHeld }
}

/** Whether the hips of one frame may move by δ (metres) with every planted ankle held (module docstring). */
export function pairOffsetAllowed(frame: PairHeightRoleFrame, cls: Pick<PairRoleClass, 'planted' | 'kneeHeld'>, delta: number): boolean {
  if (Math.abs(delta) > PAIR_HEIGHT.MAX_M + 1e-12) return false
  const s = frame.groundM
  const cosMin = Math.cos(PAIR_HEIGHT.MIN_BEND_DEG * DEG)
  for (let i = 0; i < frame.legs.length; i++) {
    if (!cls.planted[i]) continue
    const leg = frame.legs[i]
    const l1 = len(sub(leg.knee, leg.hip)), l2 = len(sub(leg.ankle, leg.knee))
    const up: Vec3 = [0, delta, 0]
    const hip = add(leg.hip, up)
    const d = len(sub(hip, leg.ankle))
    if (d > Math.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * cosMin) + 1e-12) return false
    if (d < Math.abs(l1 - l2) + PAIR_HEIGHT.FOLD_M) return false
    const knee = ikKnee(hip, add(leg.knee, up), add(leg.ankle, up), leg.ankle)
    if (cls.kneeHeld[i] && len(sub(knee, leg.knee)) > PAIR_HEIGHT.KNEE_HOLD_M + 1e-12) return false
    if (knee[1] < s + Math.min(leg.knee[1] - s, PAIR_HEIGHT.KNEE_FLOOR_M) - 1e-12) return false
  }
  return true
}

/** The range one direction allows in EVERY frame (sign = +1 up, −1 down): the whole MAX_M, nothing, or the bisected
 *  limit. */
function reach(frames: readonly PairHeightRoleFrame[], cls: PairRoleClass, sign: number): number {
  const ok = (m: number) => frames.every((f) => pairOffsetAllowed(f, cls, sign * m))
  if (ok(PAIR_HEIGHT.MAX_M)) return sign * PAIR_HEIGHT.MAX_M
  if (!ok(PAIR_HEIGHT.MIN_STEP_M)) return 0
  let lo: number = PAIR_HEIGHT.MIN_STEP_M, hi: number = PAIR_HEIGHT.MAX_M
  for (let k = 0; k < PAIR_HEIGHT.BISECT_STEPS; k++) {
    const mid = (lo + hi) / 2
    if (ok(mid)) lo = mid; else hi = mid
  }
  return sign * lo
}

/** The offsets a role may take over its sampled frames. */
export function pairRoleRange(role: PairHeightRole): PairHeightRange {
  const cls = pairRoleClass(role)
  if (cls.stance === 'fixed' || cls.stance === 'resting' || cls.stance === 'free') return { ...cls, down: 0, up: 0 }
  return { ...cls, down: reach(role.frames, cls, -1), up: cls.stance === 'standing' ? 0 : reach(role.frames, cls, 1) }
}

/** The offsets of every role of an interaction from its sampled loop (module docstring THE SOLVE). */
export function pairHeightOffsets(input: PairHeightInput): PairHeightSolve {
  const out: PairHeightSolve = { offsets: {}, planted: {}, ranges: {}, contactFrames: {}, gaps: {}, residuals: {} }
  const roles = Object.keys(input.roles).sort()
  for (const role of roles) out.offsets[role] = 0
  const usable: PairHeightRelation[] = []
  for (const r of input.relations) {
    if (r.part === r.receiver || !input.roles[r.part] || !input.roles[r.receiver]) continue
    const k = pairContactFrame(r.frames)
    if (k < 0) continue
    const gap = pairAxisGap(r.frames[k]!)
    out.contactFrames[r.key] = k
    out.gaps[r.key] = Math.abs(gap) < PAIR_HEIGHT.DEADBAND_M ? 0 : gap
    usable.push(r)
  }
  if (usable.every((r) => out.gaps[r.key] === 0)) {
    for (const r of usable) out.residuals[r.key] = 0
    return out
  }
  for (const role of roles) {
    out.ranges[role] = pairRoleRange(input.roles[role])
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
