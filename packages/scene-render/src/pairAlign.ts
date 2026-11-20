/**
 * BOUNDED AUTO-ALIGN (Ruling A212) — Auto-align only ADJUSTS a pair/group clip around the arrangement the user set.
 * One geometry for the Library's place preview (and any other caller): `fitResiduals` (`pairFit.ts`), summed over
 * every contact relation of ONE moving figure.
 *
 * RIGID (2026-11-20): Auto-align moves and turns the figure as one rigid body and NEVER bends the attached part —
 * neither in the bounded solve nor in the lamp's free solve. The part's bend (`chainBend.ts`) is a render step
 * after it; a caller may report what that bend does on the aligned samples (`bendSample`), but every number of the
 * solve and of `phaseRow` is the rigid one.
 *
 * THE UNKNOWNS: the moving figure's offset x = (side, up, forward) in metres of its clip frame, relative to the base
 * arrangement (the dials when Auto-align was clicked), and — a pair only — its tilt/roll α_k in degrees about the
 * caller's axes, also relative to the base. World shift = B·x for the caller's row-major 3×3 `basis` (the clip frame
 * columns, the vertical through the hips-drop gain). Yaw is never an unknown.
 *
 * THE CAP (`alignCap`): the TOTAL over every iteration, never per step — |x_forward|, |x_up| ≤ range (default
 * `ALIGN_RANGE_CM_DEFAULT` = 8 cm, per clip in the sidecar `align_range_cm`), |x_side| ≤ min(3 cm, range),
 * |α_k| ≤ 10°. The receiving figure never moves: only the role that carries the attached part has unknowns.
 *
 * THE SOLVE (`solveAlignAdjust`): the samples were measured with the trial `start` (x₀, α₀) already applied; the solve
 * finds the increment (y, β) minimising  Σ_relations |fitResiduals(samples_r, fix(y, β))|²  +  J·|B·y − j|²  with
 * (x₀ + y, α₀ + β) projected into the cap box after every Gauss–Newton step (forward-difference Jacobian, step 1e-6,
 * at most `iterations` steps; an unknown held on its bound is frozen and the rest re-solved — an active set). Several relations of one figure are ONE least-squares problem — the figure moves once
 * for all its contacts, not relation after relation. j is the optional JOIN (end clips): the world shift that puts the
 * moving figure where the base clip's last frame left it, relative to the anchor role; J = `JOIN_WEIGHT` × the sample
 * count.
 *
 * THE LAMP: the same problem is solved once more inside a wide box (`FREE_BOX`); what that free optimum lies beyond
 * the cap (per axis, max(0, |free| − cap)) is how far the base arrangement is off. offCm = |excess| (cm), offDeg = the
 * largest angle excess. green = offCm ≤ `CAP_SLACK_CM` and offDeg ≤ 1°; yellow = offCm ≤ the range and offDeg ≤ the
 * angle cap; red beyond. Not green = the caller says "move it closer by hand" instead of pushing further.
 *
 * THE PHASES (`ALIGN_PHASES`): the stroke is fitted over five phases of the loop together — start, ¼, ½, ¾ and the
 * end (the loop's last frame; a loop ends where it starts) — `pickPhases` takes the sample nearest each, `phaseRow`
 * reports a sample's tip off the axis, its depth along the axis (+ = inside) and the shaft against the axis.
 */
import type { Vec3 } from './collision'
import { fitResiduals, solveLinear, type FitSample, type PairFix } from './pairFit'

export const ALIGN_RANGE_CM_DEFAULT = 8
export const ALIGN_SIDE_CM = 3
export const ALIGN_ANGLE_DEG = 10
export const ALIGN_PHASES: readonly number[] = Object.freeze([0, 0.25, 0.5, 0.75, 1])
export const JOIN_WEIGHT = 1
export const CAP_SLACK_CM = 0.5
/** The box of the free solve that measures how far the base is off (metres, degrees). */
export const FREE_BOX = Object.freeze({ shiftM: 1, angleDeg: 45 })

export interface AlignCap { sideM: number; upM: number; forwardM: number; angleDeg: number }
export type AlignLamp = 'green' | 'yellow' | 'red'

/** The cap for a clip's alignment range (cm; null/invalid = the default). */
export function alignCap(rangeCm?: number | null): AlignCap {
  const r = typeof rangeCm === 'number' && Number.isFinite(rangeCm) && rangeCm > 0 ? rangeCm : ALIGN_RANGE_CM_DEFAULT
  return { sideM: Math.min(ALIGN_SIDE_CM, r) / 100, upM: r / 100, forwardM: r / 100, angleDeg: ALIGN_ANGLE_DEG }
}

export interface AlignProblem {
  /** One entry per contact relation of the moving figure: its samples measured with `start` applied. */
  relations: readonly { samples: readonly FitSample[] }[]
  /** Row-major 3×3: world shift = basis · (side, up, forward). */
  basis: readonly number[]
  /** The trial already applied, relative to the base: offset (m) and angles (deg). */
  start?: Vec3
  startDeg?: readonly number[]
  /** Unit world axes the figure may turn about ([] / absent = shift only). */
  axes?: readonly Vec3[]
  cap: AlignCap
  /** A tighter angle cap (the place type's posture cap), degrees. */
  angleCapDeg?: number
  posture?: boolean
  /** The world shift still missing to join the base clip's end (end clips), and its weight (× sample count). */
  join?: { deltaM: Vec3; weight?: number } | null
  iterations?: number
}
export interface AlignSolution {
  /** Total offset relative to the base (m, side/up/forward) and total angles (deg), inside the cap. */
  x: Vec3; deg: number[]
  /** The increment to apply on top of the measured state (world, about each sample's pivot). */
  fix: PairFix
  /** The free optimum's totals and how far it lies beyond the cap. */
  freeX: Vec3; freeDeg: number[]; offCm: number; offDeg: number
  capped: boolean; lamp: AlignLamp
}

const mulB = (b: readonly number[], v: readonly number[]): Vec3 =>
  [b[0] * v[0] + b[1] * v[1] + b[2] * v[2], b[3] * v[0] + b[4] * v[1] + b[5] * v[2], b[6] * v[0] + b[7] * v[1] + b[8] * v[2]]
const clampTo = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

function solveBox(p: AlignProblem, half: number[]): number[] {
  const axes = p.axes ?? []
  const n = 3 + axes.length
  const start = [...(p.start ?? [0, 0, 0]), ...axes.map((_, k) => p.startDeg?.[k] ?? 0)]
  const toFix = (z: number[]): PairFix => {
    const turn: Vec3 = [0, 0, 0]
    axes.forEach((a, k) => {
      const r = z[3 + k] * Math.PI / 180
      turn[0] += a[0] * r; turn[1] += a[1] * r; turn[2] += a[2] * r
    })
    return { shift: mulB(p.basis, z), turn }
  }
  const count = p.relations.reduce((a, r) => a + r.samples.length, 0)
  const jw = p.join ? Math.sqrt((p.join.weight ?? JOIN_WEIGHT) * Math.max(1, count)) : 0
  const res = (z: number[]) => {
    const fix = toFix(z)
    const out: number[] = []
    for (const r of p.relations) out.push(...fitResiduals(r.samples, fix, { posture: p.posture }))
    if (p.join) {
      const s = fix.shift, d = p.join.deltaM
      out.push(jw * (s[0] - d[0]), jw * (s[1] - d[1]), jw * (s[2] - d[2]))
    }
    return out
  }
  // the increment's box: (start + z) within ±half
  const project = (z: number[]) => z.map((v, i) => clampTo(v, -half[i] - start[i], half[i] - start[i]))
  let z = project(new Array(n).fill(0))
  let r = res(z)
  let c = r.reduce((a, v) => a + v * v, 0)
  if (!r.length) return z
  for (let it = 0; it < (p.iterations ?? 20); it++) {
    const J: number[][] = []
    for (let k = 0; k < n; k++) {
      const zp = z.slice(); zp[k] += 1e-6
      const rp = res(zp)
      J.push(rp.map((v, i) => (v - r[i]) / 1e-6))
    }
    const A = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => {
      let s = 0
      for (let m = 0; m < r.length; m++) s += J[i][m] * J[j][m]
      return s + (i === j ? 1e-9 : 0)
    }))
    const g = Array.from({ length: n }, (_, i) => { let s = 0; for (let m = 0; m < r.length; m++) s -= J[i][m] * r[m]; return s })
    // Active set: an unknown on its bound whose descent direction points outward is frozen and the reduced system
    // is solved again, so the free unknowns take their best fit WITH the bound one held (not a clamped full step).
    const lo = (i: number) => -half[i] - start[i], hi = (i: number) => half[i] - start[i]
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
    for (let ls = 0; ls < 10; ls++) {
      const zn = project(z.map((v, i) => v + t * step[i]))
      const rn = res(zn)
      const cn = rn.reduce((a, v) => a + v * v, 0)
      if (cn < c) {
        const moved = Math.max(...zn.map((v, i) => Math.abs(v - z[i])))
        z = zn; r = rn; c = cn; accepted = moved > 1e-7
        break
      }
      t /= 2
    }
    if (!accepted) break
  }
  return z
}

/** The bounded increment and the lamp (module docstring THE SOLVE, THE LAMP). */
export function solveAlignAdjust(p: AlignProblem): AlignSolution {
  const axes = p.axes ?? []
  const ang = Math.min(p.cap.angleDeg, p.angleCapDeg ?? Infinity)
  const capHalf = [p.cap.sideM, p.cap.upM, p.cap.forwardM, ...axes.map(() => ang)]
  const freeHalf = [FREE_BOX.shiftM, FREE_BOX.shiftM, FREE_BOX.shiftM, ...axes.map(() => FREE_BOX.angleDeg)]
  const start = [...(p.start ?? [0, 0, 0]), ...axes.map((_, k) => p.startDeg?.[k] ?? 0)]
  const z = solveBox(p, capHalf)
  const zf = solveBox(p, freeHalf)
  const tot = z.map((v, i) => v + start[i]), free = zf.map((v, i) => v + start[i])
  const ex = free.map((v, i) => Math.max(0, Math.abs(v) - capHalf[i]))
  const offCm = Math.hypot(ex[0], ex[1], ex[2]) * 100
  const offDeg = ex.length > 3 ? Math.max(...ex.slice(3)) : 0
  const capped = offCm > CAP_SLACK_CM || offDeg > 1
  const lamp: AlignLamp = !capped ? 'green' : offCm <= p.cap.forwardM * 100 && offDeg <= ang ? 'yellow' : 'red'
  const turn: Vec3 = [0, 0, 0]
  axes.forEach((a, k) => { const r = z[3 + k] * Math.PI / 180; turn[0] += a[0] * r; turn[1] += a[1] * r; turn[2] += a[2] * r })
  return { x: [tot[0], tot[1], tot[2]], deg: tot.slice(3), fix: { shift: mulB(p.basis, z), turn },
    freeX: [free[0], free[1], free[2]], freeDeg: free.slice(3), offCm, offDeg, capped, lamp }
}

/** The sample nearest each phase (0 … 1 of the loop); phase 1 = the loop's last sample. null = no samples. */
export function pickPhases<T extends { phase: number }>(samples: readonly T[], phases: readonly number[] = ALIGN_PHASES): (T | null)[] {
  if (!samples.length) return phases.map(() => null)
  return phases.map((ph) => {
    if (ph >= 1) return samples.reduce((a, x) => (x.phase > a.phase ? x : a), samples[0])
    return samples.reduce((a, x) => (Math.abs(x.phase - ph) < Math.abs(a.phase - ph) ? x : a), samples[0])
  })
}

export interface PhaseRow { phase: number; tipMm: number; depthMm: number; axisDeg: number }
/** One sample's numbers: the tip off the axis (mm), its depth along the axis (mm, + = inside) and the shaft — the
 *  chain's last link when it has one — against the axis (degrees). */
export function phaseRow(s: FitSample, phase: number): PhaseRow {
  const v: Vec3 = [s.tip[0] - s.o[0], s.tip[1] - s.o[1], s.tip[2] - s.o[2]]
  const along = v[0] * s.u[0] + v[1] * s.u[1] + v[2] * s.u[2]
  const lat = Math.hypot(v[0] - along * s.u[0], v[1] - along * s.u[1], v[2] - along * s.u[2])
  const c = s.chain && s.chain.length >= 2 ? s.chain : null
  const a = c ? c[c.length - 2] : s.base, b = c ? c[c.length - 1] : s.tip
  const d: Vec3 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]]
  const l = Math.hypot(d[0], d[1], d[2])
  const cos = l > 0 ? (d[0] * s.u[0] + d[1] * s.u[1] + d[2] * s.u[2]) / l : 1
  return { phase, tipMm: lat * 1000, depthMm: along * 1000, axisDeg: Math.acos(clampTo(cos, -1, 1)) * 180 / Math.PI }
}

/** The moving figure's hips relative to the anchor's, in the anchor's clip frame (row-major `frame`): frameᵀ(h − a). */
export function relativeOf(frame: readonly number[], hips: Vec3, anchor: Vec3): Vec3 {
  const d = [hips[0] - anchor[0], hips[1] - anchor[1], hips[2] - anchor[2]]
  return [frame[0] * d[0] + frame[3] * d[1] + frame[6] * d[2], frame[1] * d[0] + frame[4] * d[1] + frame[7] * d[2],
    frame[2] * d[0] + frame[5] * d[1] + frame[8] * d[2]]
}
/** The world shift that brings `hips` to `rel` (anchor clip frame) from `anchor`: frame·rel − (h − a). */
export function joinDelta(frame: readonly number[], rel: Vec3, hips: Vec3, anchor: Vec3): Vec3 {
  const w = mulB(frame, rel)
  return [w[0] - (hips[0] - anchor[0]), w[1] - (hips[1] - anchor[1]), w[2] - (hips[2] - anchor[2])]
}

/** THE MOVERS: the contact hits grouped by the figure that carries the attached part (`e`) — one bounded solve per
 *  group, all its relations at once. A receiving figure (`r`) is never a key unless it carries a part itself. */
export function alignMovers<T extends { e: number; r: number }>(hits: readonly T[]): Map<number, T[]> {
  const out = new Map<number, T[]>()
  for (const h of hits) out.set(h.e, [...(out.get(h.e) ?? []), h])
  return out
}
