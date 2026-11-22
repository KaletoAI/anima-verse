/**
 * KEY-FRAME AUTO-ALIGN (Ruling A212, the owner's procedure of 2026-11-20; objective of 2026-11-22) — Auto-align only
 * ADJUSTS a pair/group clip around the arrangement the user set, and it does so at TWO frames of the loop:
 *   1. the frame of MAXIMUM penetration (the largest axial coordinate s of the tip, `keyFrames` "deep"): there the
 *      attached part goes IN AS FAR AS IT CAN — its root joint just outside the opening, unless the channel's bottom
 *      stops the tip first (THE DEPTH TARGET);
 *   2. the frame of MINIMUM penetration ("shallow"): there the part is drawn STRAIGHT out along the axis.
 * At both the rigid shaft — the line from the part's root joint P_0 through its tip — must run along the channel's
 * axis and through its opening: then the render-time chain bend (`chainBend.ts`) has nothing left to do. One clip
 * has ONE stored offset per role and ONE root angle, so both frames are ONE least-squares problem. The other frames
 * of the loop are reported, not fitted.
 *
 * ONE RELATION, ONE MOVER (2026-11-22): a click aligns one contact relation (one part role against one receiving
 * role) by moving ONE of its two roles — the part's carrier (the default) or the receiving role. Moving the receiving
 * role moves ITS channel: the opening o and the axis u turn and shift about the receiving figure's own pivot, with its
 * own tilt/roll axes, while the part stays (`moveSample` with `AlignSample.mover` = 'receiver') — never the part
 * moved by the negated fix, which would turn about the wrong pivot. Every other role stays where it is.
 *
 * RIGID: the solve never bends the part. The bend is a render step after it; `keyRow` reports what it would still do
 * at a key frame (`bendSample`, with the state's limit).
 *
 * THE UNKNOWNS (increments z on top of the measured state, totals = start + z):
 *   x = (side, up, forward) — the moving role's offset in metres of its clip frame, relative to the base arrangement;
 *       world shift = B·x for the caller's row-major 3×3 `basis` (the vertical through the hips-drop gain);
 *   α_k — a pair only: tilt/roll in degrees about the caller's `axes`, relative to the base (yaw is never an unknown);
 *   (pitch, yaw) — the clip's ROOT ANGLE (Ruling A158, `chainBend.ts` THE ROOT ANGLE), absolute degrees, when `root`
 *       is given and a relation is `rooted` (its chain is the one the root angle turns, its samples carry `body`).
 *       The root angle re-poses the chain ANALYTICALLY on the sample (`moveSample`): the measured chain carries the
 *       root turn q(start); P_0 + q(new)·q(start)⁻¹·(P − P_0) is the chain under the new angle (`rootTurnQuat`, the
 *       sample's body axes), and the partner fix moves the result. What the simulated chain does beyond that rigid
 *       turn is caught by RE-MEASURING (`alignByPasses`).
 *
 * THE CAP (`alignCap`): totals, never per step — |x_forward|, |x_up| ≤ range (default `ALIGN_RANGE_CM_DEFAULT` = 8 cm,
 * per clip in the sidecar `align_range_cm`), |x_side| ≤ min(3 cm, range), |α_k| ≤ 10° (or the place type's posture
 * cap), |pitch| ≤ `ROOT_PITCH_MAX_DEG`, |yaw| ≤ `ROOT_YAW_MAX_DEG` (the slider ranges). Only the mover moves.
 * An unknown that ends on its bound is a HIT (`AlignBound`), named in the result; a hit makes the lamp red.
 *
 * THE RESIDUALS (`solveAlign`), per relation, at its deep and its shallow frame (one frame when they coincide). With
 * the rigid shaft's direction d = (T' − P'_0)/|T' − P'_0| (T' the tip, P'_0 the root joint, both after the trial):
 *   a channel (the declared channels and the mouth, `AlignSample.channel`) — THE AXIS ERROR (weight 1):
 *     P(Q − O)                                   the shaft line's OFFSET where it crosses the opening plane: Q = P'_0 +
 *                                                t·d, t = −s_root·c / max(c², c_min²), c = d·u, c_min =
 *                                                `ALIGN_CROSS_MIN` (P = I − uuᵀ). From c_min up, t = −s_root/c puts Q
 *                                                exactly on the opening plane; below it the travel shrinks linearly to
 *                                                the root joint itself at c = 0 (and stays there for c ≤ 0), so the
 *                                                offset is CONTINUOUS in the shaft angle — a hard switch at c_min
 *                                                jumped by 0.17 m on a clip whose shaft sat at 78.5° to the axis
 *     L·(d − u)                                  the shaft-to-axis ANGLE at a fixed lever L = `ALIGN_AXIS_LEVER_M`:
 *                                                |d − u| = 2 sin(θ/2) ≈ θ, so a degree costs L·π/180 metres
 *   a point target (hands, `isPointTarget`): P(P'_0 − O), P(T' − O) — the root joint and the tip off the target's line,
 *     as before (no opening plane, no depth).
 *   deep frame, a channel only — THE DEPTH TARGET (weight `ALIGN_DEPTH_WEIGHT`):
 *     s_root − s*,  s* = min(−m, (depth − r_tip) − m − (s_tip − s_root))
 *     the root joint just outside the opening (−m), or further out when the shaft would otherwise push the tip past
 *     the bottom (whichever binds first; without a known depth s* = −m). Plus the inequalities (only a VIOLATED one
 *     costs, `ALIGN_LIMIT_WEIGHT` per metre): max(0, m − s_tip) the tip not inside, max(0, s_tip − (depth − r_tip) + m)
 *     past the bottom, max(0, s_root + m) the root not outside; the margin m = `ALIGN_MARGIN_M`.
 *   Why (the diagnosis of 2026-11-21, crouching-doggy): the receiving axis turns between the key frames (8° there), so
 *   the two frames' axis LINES cross — 0.2 m outside the opening. The old residuals (root and tip off the line, at both
 *   frames) were least where both lines are close, i.e. near that crossing, outside; only the "tip inside" inequality
 *   held the part back, and it stopped at its margin: 2.0 mm deep. Measured at the opening plane plus the angle, the
 *   axis error no longer prefers any depth, and the depth is a target of its own.
 *   Plus, unchanged: the posture band of a key frame with a support (Ruling A150, `POSTURE.weight`, and
 *   `POSTURE.turnCostM`·√N per radian of turn), the JOIN of end clips (√(`JOIN_WEIGHT`·N)·(B·x − j), j the world shift
 *   that puts the moving role where the base clip's last frame left it).
 * THE NULL DIRECTIONS: a shift along the axis moves neither the opening-plane offset nor the angle — the depth target
 * alone decides it. A tilt/roll of the moving role turns it about its own hips at every frame, so to first order it
 * equals a shift plus a root-angle change — the two-frame problem does not decide them. A small ridge on the
 * increments (`ALIGN_RIDGE`: shift 1e-5 per metre, tilt/roll 1e-5 m per degree, root angle 1e-7 m per degree) holds a
 * null direction where it stands and makes the root angle the cheap lever: tilt/roll move only when the root angle's
 * range or the posture asks for it. Its bias on the decided directions is below 1e-4 of the answer (the smoke's
 * recovery checks hold it).
 *
 * THE SOLVE: Gauss–Newton with forward differences (step 1e-6), a line search and an active set — an unknown held on
 * its bound whose descent points outward is frozen and the rest re-solved (`solveBounded`). Several relations of one
 * figure are ONE problem (the figure moves once for all its contacts); the root angle is one per clip.
 *
 * THE PASSES (`alignByPasses`): measure → solve → apply → measure again, at most `ALIGN_PASSES` times, until the
 * increment is below 0.05 mm / 0.01°. The key frames are picked afresh from every measurement.
 *
 * THE LAMP (`keyLamp`, the reasons `keyReasons`): a channel is green when at both key frames the axis error — the
 * opening-plane offset and the angle's lever L·2 sin(θ/2) — is within `KEY_GREEN_MM` (3 mm) and the deep frame holds
 * step 1 (root outside, tip inside, not past the bottom); yellow within `KEY_YELLOW_MM` (10 mm) with step 1 holding;
 * red otherwise, when an unknown hit its cap/slider range, or when the deepest frame ended SHALLOWER than it started
 * (by more than `KEY_SHALLOWER_MM`; a start past the bottom is exempt — there going back out is the fix). A point
 * target reads the root joint and the tip off its line instead of the axis error.
 */
import type { Vec3 } from './collision'
import { bendSample, fixPoint, solveLinear, supportDelta, turnMatrix, type FitSample, type PairFix } from './pairFit'
import { quatMul, quatRotate, rootTurnQuat, ROOT_PITCH_MAX_DEG, ROOT_YAW_MAX_DEG, type BendFrame, type BendLimits,
  type RootAngle } from './chainBend'
import { POSTURE, postureExcess } from './postureSupport'

export const ALIGN_RANGE_CM_DEFAULT = 8
export const ALIGN_SIDE_CM = 3
export const ALIGN_ANGLE_DEG = 10
export const JOIN_WEIGHT = 1
/** The inequality weight (per metre of violation) and the margin the inequalities keep (metres). */
export const ALIGN_LIMIT_WEIGHT = 10
export const ALIGN_MARGIN_M = 0.002
/** The fixed lever the shaft-to-axis angle is weighted by (metres per radian), and the depth target's weight. */
export const ALIGN_AXIS_LEVER_M = 0.1
export const ALIGN_DEPTH_WEIGHT = 1
/** Below this d·u the shaft runs too far across the axis for an exact opening-plane crossing: the travel along the
 *  shaft tapers off linearly to the root joint (`axisError`). */
export const ALIGN_CROSS_MIN = 0.2
/** The ridge on the increments (module docstring THE NULL DIRECTIONS). */
export const ALIGN_RIDGE = Object.freeze({ shiftPerM: 1e-5, turnMPerDeg: 1e-5, rootMPerDeg: 1e-7 })
/** At most this many measure → solve passes (module docstring THE PASSES). */
export const ALIGN_PASSES = 5
export const KEY_GREEN_MM = 3
export const KEY_YELLOW_MM = 10
/** A deepest frame this much shallower after the run than before turns the lamp red (THE LAMP). */
export const KEY_SHALLOWER_MM = 0.5

export interface AlignCap { sideM: number; upM: number; forwardM: number; angleDeg: number }
export type AlignLamp = 'green' | 'yellow' | 'red'
/** An unknown that ended on its cap or slider range. */
export type AlignBound = 'side' | 'up' | 'forward' | 'tilt' | 'roll' | 'pitch' | 'yaw'

/** The cap for a clip's alignment range (cm; null/invalid = the default). */
export function alignCap(rangeCm?: number | null): AlignCap {
  const r = typeof rangeCm === 'number' && Number.isFinite(rangeCm) && rangeCm > 0 ? rangeCm : ALIGN_RANGE_CM_DEFAULT
  return { sideM: Math.min(ALIGN_SIDE_CM, r) / 100, upM: r / 100, forwardM: r / 100, angleDeg: ALIGN_ANGLE_DEG }
}

/** One measured frame of a contact relation. */
export interface AlignSample extends FitSample {
  /** The moving figure's body axes (world) the root angle turns about (`FigureRuntime.bodyFrame`); absent = the root
   *  angle cannot be modelled on this sample. */
  body?: BendFrame
  /** The channel's depth and the tip's radius (metres): the bottom condition; absent/0 = no bottom known. */
  depthM?: number
  tipRadiusM?: number
  /** 0 … 1 of the loop (reported). */
  phase?: number
  /** Which role the trial moves (ONE RELATION, ONE MOVER): 'part' (absent) = the part's carrier — chain, tip, base,
   *  support and body axes move about `pivot`; 'receiver' = the receiving role — its opening `o` and axis `u` move
   *  about `pivot` (then the RECEIVING figure's pivot) and `support` is the receiving figure's. */
  mover?: 'part' | 'receiver'
}
/** A contact relation's samples over the loop; `rooted` = its chain is the one the clip's root angle turns. */
export interface AlignRelation { samples: readonly AlignSample[]; rooted?: boolean }
export interface AlignProblem {
  relations: readonly AlignRelation[]
  /** Row-major 3×3: world shift = basis · (side, up, forward). */
  basis: readonly number[]
  /** The trial already applied, relative to the base: offset (m) and angles (deg). */
  start?: Vec3
  startDeg?: readonly number[]
  /** Unit world axes the figure may turn about ([] / absent = shift only); index 0 = tilt, 1 = roll. */
  axes?: readonly Vec3[]
  cap: AlignCap
  /** A tighter angle cap (the place type's posture cap), degrees. */
  angleCapDeg?: number
  /** The root angle the samples were measured with; present = pitch/yaw are unknowns (a rooted relation needed). */
  root?: RootAngle | null
  posture?: boolean
  /** The world shift still missing to join the base clip's end (end clips), and its weight (× key-frame count). */
  join?: { deltaM: Vec3; weight?: number } | null
  iterations?: number
}
export interface AlignSolution {
  /** Total offset relative to the base (m, side/up/forward), total angles (deg) and the root angle (null = not solved). */
  x: Vec3; deg: number[]; root: RootAngle | null
  /** The increment's partner fix (world, about each sample's pivot) and the root angle it goes with. */
  fix: PairFix
  /** The unknowns that ended on their bound. */
  hits: AlignBound[]
  /** Per relation: the key frames' sample indices. */
  keys: ({ deep: number; shallow: number } | null)[]
}

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const scale = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const lateral = (v: Vec3, u: Vec3): Vec3 => sub(v, scale(u, dot(v, u)))
const mulM = (m: readonly number[], v: readonly number[]): Vec3 =>
  [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2], m[6] * v[0] + m[7] * v[1] + m[8] * v[2]]
const clampTo = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
const sameAngle = (a: RootAngle | null | undefined, b: RootAngle | null | undefined) =>
  (a?.pitchDeg ?? 0) === (b?.pitchDeg ?? 0) && (a?.yawDeg ?? 0) === (b?.yawDeg ?? 0)

/** The axial coordinate s of a point (metres, + = inside). */
const axial = (s: { o: Vec3; u: Vec3 }, p: Vec3) => dot(sub(p, s.o), s.u)

/** The key frames of a relation's samples: deep = the largest s of the tip, shallow = the smallest (first on ties);
 *  null for no samples. */
export function keyFrames(samples: readonly { tip: Vec3; o: Vec3; u: Vec3 }[]): { deep: number; shallow: number } | null {
  if (!samples.length) return null
  let deep = 0, shallow = 0
  samples.forEach((s, i) => {
    const v = axial(s, s.tip)
    if (v > axial(samples[deep], samples[deep].tip)) deep = i
    if (v < axial(samples[shallow], samples[shallow].tip)) shallow = i
  })
  return { deep, shallow }
}

/** The sample under the mover's `fix` and, for a rooted sample with body axes, the root angle changed from `from` to
 *  `to` (module docstring THE UNKNOWNS). The root angle always re-poses the PART's chain (about its root joint, the
 *  part's body axes). Then the fix moves the mover about `pivot`: the part's carrier (default) — chain, tip, base,
 *  support and body axes, o and u unchanged; the receiving role (`mover` 'receiver') — o and u (u turned only) and
 *  its support, the part unchanged. The pivot itself stays. */
export function moveSample(s: AlignSample, fix: PairFix, from?: RootAngle | null, to?: RootAngle | null): AlignSample {
  let chain: Vec3[] = s.chain && s.chain.length >= 2 ? s.chain : [s.base, s.tip]
  if (s.body && to && !sameAngle(from, to)) {
    const q0 = rootTurnQuat(s.body, from ?? { pitchDeg: 0, yawDeg: 0 }), q1 = rootTurnQuat(s.body, to)
    const dq = quatMul(q1, [-q0[0], -q0[1], -q0[2], q0[3]])
    const p0 = chain[0]
    chain = chain.map((p, k) => (k === 0 ? p : add(p0, quatRotate(dq, sub(p, p0)))))
  }
  const R = turnMatrix(fix.turn)
  const support = s.support ? { support: { ...s.support, pts: s.support.pts.map((p) => fixPoint(fix, s.pivot, p)) } } : {}
  if (s.mover === 'receiver') {
    return { ...s, tip: chain[chain.length - 1], base: chain[0], ...(s.chain && s.chain.length >= 2 ? { chain } : {}),
      o: fixPoint(fix, s.pivot, s.o), u: mulM(R, s.u), ...support }
  }
  const moved = chain.map((p) => fixPoint(fix, s.pivot, p))
  return { ...s, tip: moved[moved.length - 1], base: moved[0], ...(s.chain && s.chain.length >= 2 ? { chain: moved } : {}),
    ...support, ...(s.body ? { body: { side: mulM(R, s.body.side), up: mulM(R, s.body.up) } } : {}) }
}

/** THE AXIS ERROR of a channel sample (module docstring THE RESIDUALS): the shaft line's offset where it crosses the
 *  opening plane (lateral to u) and the angle's lever L·(d − u). */
export function axisError(s: { o: Vec3; u: Vec3; tip: Vec3 }, root: Vec3): { offset: Vec3; lever: Vec3 } {
  const d0 = sub(s.tip, root), l = Math.hypot(d0[0], d0[1], d0[2])
  const d: Vec3 = l > 1e-12 ? scale(d0, 1 / l) : s.u
  const c = dot(d, s.u)
  const t = c > 0 ? -axial(s, root) * c / Math.max(c * c, ALIGN_CROSS_MIN * ALIGN_CROSS_MIN) : 0
  const q = add(root, scale(d, t))
  return { offset: lateral(sub(q, s.o), s.u), lever: scale(sub(d, s.u), ALIGN_AXIS_LEVER_M) }
}
/** THE DEPTH TARGET of a deep channel sample (metres along u): where the root joint should be. */
export function depthTarget(s: { o: Vec3; u: Vec3; tip: Vec3; depthM?: number; tipRadiusM?: number }, root: Vec3): number {
  const m = ALIGN_MARGIN_M
  if (!((s.depthM ?? 0) > 0)) return -m
  const bottom = (s.depthM ?? 0) - (s.tipRadiusM ?? 0)
  return Math.min(-m, bottom - m - (axial(s, s.tip) - axial(s, root)))
}

/** The active-set Gauss–Newton of the module docstring THE SOLVE: the increment z with (start + z) within ±half that
 *  minimises |res(z)|². */
function solveBounded(res: (z: number[]) => number[], start: readonly number[], half: readonly number[], iterations: number): number[] {
  const n = start.length
  const lo = (i: number) => -half[i] - start[i], hi = (i: number) => half[i] - start[i]
  const project = (z: number[]) => z.map((v, i) => clampTo(v, lo(i), hi(i)))
  let z = project(new Array(n).fill(0))
  let r = res(z)
  let c = r.reduce((a, v) => a + v * v, 0)
  if (!r.length) return z
  for (let it = 0; it < iterations; it++) {
    const J: number[][] = []
    for (let k = 0; k < n; k++) {
      const zp = z.slice(); zp[k] += 1e-6
      const rp = res(zp)
      J.push(rp.map((v, i) => (v - r[i]) / 1e-6))
    }
    const A = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => {
      let s = 0
      for (let m = 0; m < r.length; m++) s += J[i][m] * J[j][m]
      return s + (i === j ? 1e-12 : 0)
    }))
    const g = Array.from({ length: n }, (_, i) => { let s = 0; for (let m = 0; m < r.length; m++) s -= J[i][m] * r[m]; return s })
    const atLo = (i: number) => z[i] <= lo(i) + 1e-12, atHi = (i: number) => z[i] >= hi(i) - 1e-12
    const frozen = new Set<number>()
    for (let i = 0; i < n; i++) if ((atLo(i) && g[i] < 0) || (atHi(i) && g[i] > 0)) frozen.add(i)
    let step: number[] | null = null
    for (let pass = 0; pass <= n; pass++) {
      const free = Array.from({ length: n }, (_, i) => i).filter((i) => !frozen.has(i))
      if (!free.length) { step = new Array(n).fill(0); break }
      const sub = solveLinear(free.map((i) => free.map((j) => A[i][j])), free.map((i) => g[i]))
      if (!sub) { step = null; break }
      step = new Array(n).fill(0)
      free.forEach((i, k) => { step![i] = sub[k] })
      const out = free.filter((i) => (atLo(i) && step![i] < 0) || (atHi(i) && step![i] > 0))
      if (!out.length) break
      out.forEach((i) => frozen.add(i))
    }
    if (!step || step.every((v) => v === 0)) break
    let t = 1, accepted = false
    for (let ls = 0; ls < 12; ls++) {
      const zn = project(z.map((v, i) => v + t * step[i]))
      const rn = res(zn)
      const cn = rn.reduce((a, v) => a + v * v, 0)
      if (cn < c) {
        const moved = Math.max(...zn.map((v, i) => Math.abs(v - z[i])))
        z = zn; r = rn; c = cn; accepted = moved > 1e-9
        break
      }
      t /= 2
    }
    if (!accepted) break
  }
  return z
}

/** The bounded two-key-frame solve (module docstring THE RESIDUALS, THE NULL DIRECTIONS, THE SOLVE). */
export function solveAlign(p: AlignProblem): AlignSolution {
  const axes = p.axes ?? []
  const keys = p.relations.map((r) => keyFrames(r.samples))
  const picks: { s: AlignSample; deep: boolean; rooted: boolean }[] = []
  p.relations.forEach((r, i) => {
    const k = keys[i]
    if (!k) return
    picks.push({ s: r.samples[k.deep], deep: true, rooted: !!r.rooted })
    if (k.shallow !== k.deep) picks.push({ s: r.samples[k.shallow], deep: false, rooted: !!r.rooted })
  })
  const rooted = !!p.root && picks.some((x) => x.rooted && !!x.s.body && (x.s.chain?.length ?? 0) >= 2)
  const nA = axes.length
  const ang = Math.min(p.cap.angleDeg, p.angleCapDeg ?? Infinity)
  const half = [p.cap.sideM, p.cap.upM, p.cap.forwardM, ...axes.map(() => ang),
    ...(rooted ? [ROOT_PITCH_MAX_DEG, ROOT_YAW_MAX_DEG] : [])]
  const root0: RootAngle = { pitchDeg: p.root?.pitchDeg ?? 0, yawDeg: p.root?.yawDeg ?? 0 }
  const start = [...(p.start ?? [0, 0, 0]), ...axes.map((_, k) => p.startDeg?.[k] ?? 0),
    ...(rooted ? [root0.pitchDeg, root0.yawDeg] : [])]
  const toFix = (z: number[]): PairFix => {
    const turn: Vec3 = [0, 0, 0]
    axes.forEach((a, k) => {
      const r = z[3 + k] * Math.PI / 180
      turn[0] += a[0] * r; turn[1] += a[1] * r; turn[2] += a[2] * r
    })
    return { shift: mulM(p.basis, z), turn }
  }
  const rootOf = (z: number[]): RootAngle => ({ pitchDeg: root0.pitchDeg + z[3 + nA], yawDeg: root0.yawDeg + z[4 + nA] })
  const N = Math.max(1, picks.length)
  const jw = p.join ? Math.sqrt((p.join.weight ?? JOIN_WEIGHT) * N) : 0
  const posture = p.posture !== false && picks.some((x) => !!x.s.support)
  const W = ALIGN_LIMIT_WEIGHT, m = ALIGN_MARGIN_M
  const res = (z: number[]): number[] => {
    const fix = toFix(z)
    const to = rooted ? rootOf(z) : null
    const out: number[] = []
    for (const k of picks) {
      const s = moveSample(k.s, fix, k.rooted ? root0 : null, k.rooted ? to : null)
      const r0 = s.chain?.[0] ?? s.base
      if (k.s.channel) {
        const e = axisError(s, r0)
        out.push(e.offset[0], e.offset[1], e.offset[2], e.lever[0], e.lever[1], e.lever[2])
      } else {
        const lr = lateral(sub(r0, s.o), s.u), lt = lateral(sub(s.tip, s.o), s.u)
        out.push(lr[0], lr[1], lr[2], lt[0], lt[1], lt[2])
      }
      if (k.deep && k.s.channel) {
        const st = axial(s, s.tip), sr = axial(s, r0)
        out.push(ALIGN_DEPTH_WEIGHT * (sr - depthTarget(s, r0)))
        out.push(W * Math.max(0, m - st), W * Math.max(0, sr + m))
        const bottom = (k.s.depthM ?? 0) - (k.s.tipRadiusM ?? 0)
        if ((k.s.depthM ?? 0) > 0) out.push(W * Math.max(0, st - bottom + m))
      }
      if (posture) {
        const d = supportDelta(k.s, fix)   // the mover's support about the mover's pivot
        if (d !== null) out.push(POSTURE.weight * postureExcess(d))
      }
    }
    if (posture) {
      const kt = POSTURE.turnCostM * Math.sqrt(N)
      out.push(kt * fix.turn[0], kt * fix.turn[1], kt * fix.turn[2])
    }
    if (p.join) {
      const sh = fix.shift, d = p.join.deltaM
      out.push(jw * (sh[0] - d[0]), jw * (sh[1] - d[1]), jw * (sh[2] - d[2]))
    }
    z.forEach((v, i) => out.push(v * (i < 3 ? ALIGN_RIDGE.shiftPerM : i < 3 + nA ? ALIGN_RIDGE.turnMPerDeg : ALIGN_RIDGE.rootMPerDeg)))
    return out
  }
  const z = picks.length ? solveBounded(res, start, half, p.iterations ?? 30) : new Array(start.length).fill(0)
  const tot = z.map((v, i) => v + start[i])
  const names: AlignBound[] = ['side', 'up', 'forward', ...axes.map((_, k): AlignBound => (k === 0 ? 'tilt' : 'roll')),
    ...(rooted ? ['pitch', 'yaw'] as AlignBound[] : [])]
  const hits = names.filter((_, i) => Math.abs(tot[i]) >= half[i] - 1e-9 && half[i] > 0)
  return { x: [tot[0], tot[1], tot[2]], deg: tot.slice(3, 3 + nA),
    root: rooted ? { pitchDeg: tot[3 + nA], yawDeg: tot[4 + nA] } : null, fix: toFix(z), hits, keys }
}

/** One key frame's numbers (rigid): the tip's depth along the axis (+ = inside), the root joint's, whether the root is
 *  outside / the tip inside / past the bottom, the root and the tip off the axis line, the rigid shaft (root → tip)
 *  against the axis, and what the render-time chain bend still does there with the state's limit (`bendSample`). */
export interface KeyRow {
  index: number; phase: number
  depthMm: number; rootDepthMm: number
  rootOutside: boolean; tipInside: boolean; pastBottom: boolean
  tipOffMm: number; rootOffMm: number; shaftDeg: number
  /** THE AXIS ERROR: the shaft line's offset at the opening plane and the angle's lever L·2 sin(θ/2) (mm); the depth
   *  target of the root joint (mm along the axis, + = inside). */
  openOffMm: number; leverMm: number; rootTargetMm: number
  /** The bend at this frame (degrees; null = no limits or no chain), the turn it wanted and whether the limit cut it. */
  bendDeg: number | null; bendWantDeg: number | null; bendAtLimit: boolean
}
export interface KeyReport { deep: KeyRow; shallow: KeyRow }

export function keyRow(s: AlignSample, index: number, limits?: BendLimits | null): KeyRow {
  const r0 = s.chain && s.chain.length >= 2 ? s.chain[0] : s.base
  const st = axial(s, s.tip), sr = axial(s, r0)
  const d = sub(s.tip, r0), l = Math.hypot(d[0], d[1], d[2])
  const cos = l > 0 ? dot(d, s.u) / l : 1
  const bend = limits ? bendSample(s, limits).bend : null
  const bottom = (s.depthM ?? 0) > 0 ? (s.depthM ?? 0) - (s.tipRadiusM ?? 0) : Infinity
  const off = (p: Vec3) => { const v = lateral(sub(p, s.o), s.u); return Math.hypot(v[0], v[1], v[2]) * 1000 }
  const ax = axisError(s, r0), mm = (v: Vec3) => Math.hypot(v[0], v[1], v[2]) * 1000
  return { index, phase: s.phase ?? 0, depthMm: st * 1000, rootDepthMm: sr * 1000, rootOutside: sr < 0, tipInside: st > 0,
    pastBottom: st > bottom, tipOffMm: off(s.tip), rootOffMm: off(r0), shaftDeg: Math.acos(clampTo(cos, -1, 1)) * 180 / Math.PI,
    openOffMm: mm(ax.offset), leverMm: mm(ax.lever), rootTargetMm: depthTarget(s, r0) * 1000,
    bendDeg: bend ? bend.deg : null, bendWantDeg: bend ? bend.wantDeg : null, bendAtLimit: !!bend?.atLimit }
}
/** The deep and the shallow frame of measured samples (`keyFrames`), null for none. */
export function keyReport(samples: readonly AlignSample[], limits?: BendLimits | null): KeyReport | null {
  const k = keyFrames(samples)
  return k ? { deep: keyRow(samples[k.deep], k.deep, limits), shallow: keyRow(samples[k.shallow], k.shallow, limits) } : null
}
/** The worst axis error of a key report (mm): a channel's opening-plane offset and lever, a point target's root joint
 *  and tip off its line. */
export function keyWorstMm(rep: KeyReport, inside: boolean): number {
  const rows = [rep.deep, rep.shallow]
  return Math.max(...rows.map((r) => (inside ? Math.max(r.openOffMm, r.leverMm) : Math.max(r.tipOffMm, r.rootOffMm))))
}
/** Why a key report's lamp is not green (module docstring THE LAMP), in a fixed order: the caps hit, 'shallower' (the
 *  deepest frame ended shallower than `before`), 'root_inside', 'tip_outside', 'past_bottom', 'off_axis' (beyond the
 *  green limit). Empty = green. */
export type KeyReason = 'caps' | 'shallower' | 'root_inside' | 'tip_outside' | 'past_bottom' | 'off_axis'
export function keyReasons(rep: KeyReport | null, hits: readonly AlignBound[], inside: boolean,
  before?: KeyReport | null): KeyReason[] {
  if (!rep) return ['off_axis']
  const out: KeyReason[] = []
  if (hits.length) out.push('caps')
  if (inside && before && !before.deep.pastBottom && rep.deep.depthMm < before.deep.depthMm - KEY_SHALLOWER_MM) out.push('shallower')
  if (inside && !rep.deep.rootOutside) out.push('root_inside')
  if (inside && !rep.deep.tipInside) out.push('tip_outside')
  if (inside && rep.deep.pastBottom) out.push('past_bottom')
  if (keyWorstMm(rep, inside) > KEY_GREEN_MM) out.push('off_axis')
  return out
}
/** The lamp of a key report (module docstring THE LAMP); `inside` = a channel (step 1 applies); `before` = the report
 *  before the run (a shallower deepest frame is red). */
export function keyLamp(rep: KeyReport | null, hits: readonly AlignBound[], inside: boolean, before?: KeyReport | null): AlignLamp {
  if (!rep) return 'red'
  const why = keyReasons(rep, hits, inside, before)
  if (why.some((r) => r !== 'off_axis')) return 'red'
  return keyWorstMm(rep, inside) <= KEY_GREEN_MM ? 'green' : keyWorstMm(rep, inside) <= KEY_YELLOW_MM ? 'yellow' : 'red'
}

/** What a pass applies: the totals of the unknowns (offset relative to the base, tilt/roll, the root angle). */
export interface AlignState { x: Vec3; deg: number[]; root: RootAngle | null }
/** What one measurement hands the solve. */
export interface AlignMeasure { relations: readonly AlignRelation[]; basis: readonly number[]; join?: AlignProblem['join'] }
/** One pass: the increment it proposed (mm, largest tilt/roll degree, largest root-angle degree). */
export interface AlignPass { shiftMm: number; turnDeg: number; rootDeg: number }

/** THE PASSES: measure with `start`, solve, apply, measure again — at most `passes` times, until the increment is below
 *  0.05 mm / 0.01°. `fixed` = the problem's parts that do not change between passes (cap, axes, …); a null
 *  `start.root` leaves the root angle out of the unknowns. */
export function alignByPasses<M extends AlignMeasure>(measure: (s: AlignState) => M,
  fixed: Omit<AlignProblem, 'relations' | 'basis' | 'join' | 'start' | 'startDeg' | 'root'>, start: AlignState,
  passes = ALIGN_PASSES): { state: AlignState; sol: AlignSolution | null; first: M; last: M; trace: AlignPass[]; converged: boolean } {
  let st = start
  const first = measure(st)
  let cur = first
  let sol: AlignSolution | null = null
  const trace: AlignPass[] = []
  let converged = false
  for (let i = 0; i < passes; i++) {
    sol = solveAlign({ ...fixed, relations: cur.relations, basis: cur.basis, join: cur.join, start: st.x, startDeg: st.deg,
      root: st.root })
    const step: AlignPass = {
      shiftMm: Math.hypot(sol.x[0] - st.x[0], sol.x[1] - st.x[1], sol.x[2] - st.x[2]) * 1000,
      turnDeg: Math.max(0, ...sol.deg.map((v, k) => Math.abs(v - (st.deg[k] ?? 0)))),
      rootDeg: sol.root && st.root ? Math.max(Math.abs(sol.root.pitchDeg - st.root.pitchDeg), Math.abs(sol.root.yawDeg - st.root.yawDeg)) : 0,
    }
    trace.push(step)
    st = { x: sol.x, deg: sol.deg, root: sol.root ?? st.root }
    cur = measure(st)
    if (step.shiftMm < 0.05 && step.turnDeg < 0.01 && step.rootDeg < 0.01) { converged = true; break }
  }
  return { state: st, sol, first, last: cur, trace, converged }
}

/** The moving figure's hips relative to the anchor's, in the anchor's clip frame (row-major `frame`): frameᵀ(h − a). */
export function relativeOf(frame: readonly number[], hips: Vec3, anchor: Vec3): Vec3 {
  const d = [hips[0] - anchor[0], hips[1] - anchor[1], hips[2] - anchor[2]]
  return [frame[0] * d[0] + frame[3] * d[1] + frame[6] * d[2], frame[1] * d[0] + frame[4] * d[1] + frame[7] * d[2],
    frame[2] * d[0] + frame[5] * d[1] + frame[8] * d[2]]
}
/** The world shift that brings `hips` to `rel` (anchor clip frame) from `anchor`: frame·rel − (h − a). */
export function joinDelta(frame: readonly number[], rel: Vec3, hips: Vec3, anchor: Vec3): Vec3 {
  const w = mulM(frame, rel)
  return [w[0] - (hips[0] - anchor[0]), w[1] - (hips[1] - anchor[1]), w[2] - (hips[2] - anchor[2])]
}

/** THE MOVERS of a run over ALL relations ("Align all", end clips): the contact hits grouped by the figure that
 *  carries the attached part (`e`) — one bounded solve per group, all its relations at once. A receiving figure (`r`)
 *  is never a key unless it carries a part itself. (A single click aligns one relation with the mover it names.) */
export function alignMovers<T extends { e: number; r: number }>(hits: readonly T[]): Map<number, T[]> {
  const out = new Map<number, T[]>()
  for (const h of hits) out.set(h.e, [...(out.get(h.e) ?? []), h])
  return out
}
