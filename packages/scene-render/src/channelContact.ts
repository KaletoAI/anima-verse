/**
 * AUTO CONTACT of a pair clip with a channel (Ruling A126): where partner B has to stand so that the attached part
 * of one figure meets the channel of the other. Pure maths over sampled frames; the caller (the Library's place
 * preview) plays the clip with both figures, reads every frame's attached-part chain (`FigureInspection.chains`) and
 * the receiving channel (`FigureInspection.channels`) and hands them in as samples. One geometry for both renderers:
 * the samples are the same `FigureRuntime.inspect()` numbers client3d's figures produce.
 *
 * - A SAMPLE (one frame, world metres): the chain's tip T (the last link's tip), its base B (the first link's joint),
 *   the channel's opening O and unit axis u into the body.
 * - THE SHIFT Δ moves the ENTERING figure rigidly (a role shift moves the whole half; the receiving channel does
 *   not depend on the other figure), so in frame t the tip is T_t + Δ, with s_t = (T_t + Δ − O_t)·u_t and
 *   ρ_t = |P_t (T_t + Δ − O_t)|, P_t = I − u_t u_tᵀ (`channelCoords`).
 * - THE ENTRY FRAME e = the frame with the SMALLEST s_t (the outermost tip of the stroke; independent of Δ while the
 *   axis keeps its direction). The rule: at e the tip sits on the opening (s_e = 0, ρ_e = 0), and over the whole
 *   loop the tip runs along the axis (every ρ_t small).
 * - THE SOLVE (`solveContactShift`): least squares over  Σ_t |P_t(T_t + Δ − O_t)|²  +  W · (u_e·(T_e + Δ − O_e))²
 *   with W = `CONTACT_ENTRY_WEIGHT` × the frame count, so the entry condition dominates the lateral fit. Normal
 *   equations  M Δ = −g,  M = Σ P_t + W u_e u_eᵀ,  g = Σ P_t (T_t − O_t) + W u_e (u_e·(T_e − O_e)); 3×3, Cramer. M is
 *   singular only when there are no frames.
 * - THE REPORT (`contactReport`): entry distance |T_e + Δ − O_e| (mm), the DEEPEST frame d = argmax s_t: its depth
 *   s_d (mm, > 0 = inside) and lateral error ρ_d (mm), the largest ρ over the frames with s ≥ 0, and the shaft angle at
 *   the entry frame between T_e − B_e and u_e (degrees).
 * - THE LAMP (`contactLamp`): green = entry ≤ `CONTACT_ENTRY_GREEN_MM`, s_d > 0 and ρ_d ≤ R (the tip in the channel's
 *   cylinder at the deepest frame) and the shift deepened the bodies' overlap elsewhere by at most `CONTACT_CLEAR_MM`
 *   (the growth, after − before: capsules are coarse, so a pair clip that presses the thighs together already overlaps
 *   tens of mm before any shift); yellow = s_d > 0 and ρ_d ≤ R + the
 *   funnel's widening at the opening (R + F·tan α) — inside, but not on the axis; red = not inside at the deepest
 *   frame.
 * - CLEARANCE (`bodyOverlap`): the deepest overlap of two DIFFERENT figures' contact capsules (`inspectFrame`
 *   contacts), skipping the receiving body's `suppress` capsules (the channel lets the part pass there) and the
 *   entering chain's own capsules; metres, 0 = none.
 *
 * Per-character sizes: the solve runs on the figures the preview shows (their own anchors), and Save stores the
 * result as the clip's partner shift — the numbers are the shown pair's. Another pair re-runs it.
 */
import type { Vec3 } from './collision'

/** W per frame of the entry condition against the lateral fit. */
export const CONTACT_ENTRY_WEIGHT = 10
/** Green: the tip at most this far from the opening at the entry frame (mm). */
export const CONTACT_ENTRY_GREEN_MM = 5
/** Green: the shift deepened the two bodies' overlap elsewhere by at most this (mm). */
export const CONTACT_CLEAR_MM = 30

export interface ContactSample { tip: Vec3; base: Vec3; o: Vec3; u: Vec3 }

export interface ContactReport {
  frames: number
  entryIndex: number
  entryMm: number
  deepIndex: number
  depthMm: number
  lateralMm: number
  maxLateralMm: number
  axisDeg: number
}

export type ContactLamp = 'green' | 'yellow' | 'red'

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const len = (p: Vec3) => Math.hypot(p[0], p[1], p[2])

function coords(s: ContactSample, shift: Vec3): { s: number; rho: number; rel: Vec3 } {
  const rel = sub(add(s.tip, shift), s.o)
  const a = dot(rel, s.u)
  return { s: a, rho: len(sub(rel, [s.u[0] * a, s.u[1] * a, s.u[2] * a])), rel }
}

/** The entry frame e: the smallest axial tip coordinate (module docstring); −1 without samples. */
export function entryFrame(samples: readonly ContactSample[], shift: Vec3 = [0, 0, 0]): number {
  let best = -1, min = Infinity
  samples.forEach((x, i) => { const c = coords(x, shift).s; if (c < min) { min = c; best = i } })
  return best
}

function det3(m: number[]): number {
  return m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6]) + m[2] * (m[3] * m[7] - m[4] * m[6])
}

/** Δ for the entering figure (world metres; module docstring THE SOLVE); [0, 0, 0] without samples. */
export function solveContactShift(samples: readonly ContactSample[], entryWeight = CONTACT_ENTRY_WEIGHT): Vec3 {
  const e = entryFrame(samples)
  if (e < 0) return [0, 0, 0]
  const M = [0, 0, 0, 0, 0, 0, 0, 0, 0]
  const g = [0, 0, 0]
  for (const x of samples) {
    const r = sub(x.tip, x.o)
    const ur = dot(x.u, r)
    for (let i = 0; i < 3; i++) {
      for (let j = 0; j < 3; j++) M[i * 3 + j] += (i === j ? 1 : 0) - x.u[i] * x.u[j]
      g[i] += r[i] - x.u[i] * ur
    }
  }
  const W = entryWeight * samples.length
  const ue = samples[e].u, ce = dot(ue, sub(samples[e].tip, samples[e].o))
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++) M[i * 3 + j] += W * ue[i] * ue[j]
    g[i] += W * ue[i] * ce
  }
  const D = det3(M)
  if (!(Math.abs(D) > 1e-12)) return [0, 0, 0]
  const out: Vec3 = [0, 0, 0]
  for (let k = 0; k < 3; k++) {
    const Mk = M.slice()
    for (let i = 0; i < 3; i++) Mk[i * 3 + k] = -g[i]
    out[k] = det3(Mk) / D
  }
  return out
}

/** The numbers of `samples` with the entering figure moved by `shift` (module docstring THE REPORT). */
export function contactReport(samples: readonly ContactSample[], shift: Vec3 = [0, 0, 0]): ContactReport {
  const e = entryFrame(samples, shift)
  if (e < 0) return { frames: 0, entryIndex: -1, entryMm: NaN, deepIndex: -1, depthMm: NaN, lateralMm: NaN,
    maxLateralMm: NaN, axisDeg: NaN }
  let d = 0, deep = -Infinity, maxLat = 0
  samples.forEach((x, i) => {
    const c = coords(x, shift)
    if (c.s > deep) { deep = c.s; d = i }
    if (c.s >= 0) maxLat = Math.max(maxLat, c.rho)
  })
  const ce = coords(samples[e], shift), cd = coords(samples[d], shift)
  const shaft = sub(samples[e].tip, samples[e].base)
  const l = len(shaft)
  const cos = l > 0 ? Math.max(-1, Math.min(1, dot(shaft, samples[e].u) / l)) : 1
  return { frames: samples.length, entryIndex: e, entryMm: len(ce.rel) * 1000, deepIndex: d, depthMm: cd.s * 1000,
    lateralMm: cd.rho * 1000, maxLateralMm: maxLat * 1000, axisDeg: Math.acos(cos) * 180 / Math.PI }
}

/** The lamp of a report against the channel (radius r, funnel f, cone α; metres/degrees) and the growth of the body
 *  overlap the shift caused (mm, after − before). */
export function contactLamp(rep: ContactReport, ch: { r: number; funnel: number; coneDeg: number },
  overlapGrowthMm = 0): ContactLamp {
  if (!(rep.depthMm > 0)) return 'red'
  const rMm = ch.r * 1000
  if (rep.entryMm <= CONTACT_ENTRY_GREEN_MM && rep.lateralMm <= rMm && overlapGrowthMm <= CONTACT_CLEAR_MM) return 'green'
  if (rep.lateralMm <= rMm + ch.funnel * Math.tan(ch.coneDeg * Math.PI / 180) * 1000) return 'yellow'
  return 'red'
}

/** The deepest overlap (metres, ≥ 0) of contacts between two figures, skipping `skip` (`"<figure>|<capsule id>"`). */
export function bodyOverlap(contacts: readonly { a: string; capA: string; b: string; capB: string; depth: number }[],
  skip: ReadonlySet<string>): number {
  let worst = 0
  for (const c of contacts) {
    if (skip.has(`${c.a}|${c.capA}`) || skip.has(`${c.b}|${c.capB}`)) continue
    worst = Math.max(worst, c.depth)
  }
  return worst
}
