/**
 * THE CROSS-PERSON READOUT of one frame (Ruling A110 phase 3): what the Library's place preview prints under its
 * "Collision" and "Channels" toggles, computed from `FigureRuntime.inspect()` of every figure after phase B
 * (`runFigureFrame`) — the same capsules and channels client3d's figures engage, never a second geometry.
 *
 *  - contacts: every pair of capsules of two DIFFERENT figures whose surfaces overlap, depth = r_a + r_b − the
 *    closest distance of their axis segments (metres, > 0 = penetration), deepest first; per figure pair the
 *    closest one (its depth may be negative = the gap);
 *  - engagements: which figure's chain is engaged in which figure's channel, its weight w and the opening radius
 *    the receiving figure's last opening pass used for that channel (metres).
 *
 * Pure: no Three, no state.
 */
import type { Vec3 } from './collision'
import type { FigureInspection } from './figureRuntime'

/** Closest distance between the segments p1–q1 and p2–q2 (clamped closest points, Ericson § 5.1.9). */
export function segmentSegmentDistance(p1: Vec3, q1: Vec3, p2: Vec3, q2: Vec3): number {
  const d1 = [q1[0] - p1[0], q1[1] - p1[1], q1[2] - p1[2]]
  const d2 = [q2[0] - p2[0], q2[1] - p2[1], q2[2] - p2[2]]
  const r = [p1[0] - p2[0], p1[1] - p2[1], p1[2] - p2[2]]
  const dot = (x: number[], y: number[]) => x[0] * y[0] + x[1] * y[1] + x[2] * y[2]
  const a = dot(d1, d1), e = dot(d2, d2), f = dot(d2, r)
  const EPS = 1e-12
  const clamp = (x: number) => Math.min(1, Math.max(0, x))
  let s: number, t: number
  if (a <= EPS && e <= EPS) { s = 0; t = 0 }
  else if (a <= EPS) { s = 0; t = clamp(f / e) }
  else {
    const c = dot(d1, r)
    if (e <= EPS) { t = 0; s = clamp(-c / a) }
    else {
      const b = dot(d1, d2), denom = a * e - b * b
      s = denom > EPS ? clamp((b * f - c * e) / denom) : 0
      t = (b * s + f) / e
      if (t < 0) { t = 0; s = clamp(-c / a) } else if (t > 1) { t = 1; s = clamp((b - c) / a) }
    }
  }
  return Math.hypot(r[0] + d1[0] * s - d2[0] * t, r[1] + d1[1] * s - d2[1] * t, r[2] + d1[2] * s - d2[2] * t)
}

/** One capsule pair of two figures: `depth` = r_a + r_b − axis distance (metres, > 0 overlaps). */
export interface CapsuleContact { a: string; capA: string; b: string; capB: string; depth: number }

export interface FrameInspection {
  /** Overlapping pairs (depth > 0), deepest first. */
  contacts: CapsuleContact[]
  /** Per figure pair (names in entry order) the closest capsule pair, overlapping or not. */
  closest: CapsuleContact[]
  /** Per engaged chain: `by` engaged in `of`'s `channel`; `opening` = the receiving figure's opening radius for that
   *  channel after the last pass (null = not opened yet: the budget deferred its first bind). */
  engagements: { by: string; of: string; channel: string; w: number; opening: number | null }[]
}

/** The readout over every figure of the frame (module docstring); a null inspection is skipped. */
export function inspectFrame(figures: readonly { name: string; inspection: FigureInspection | null }[]): FrameInspection {
  const live = figures.filter(f => f.inspection) as { name: string; inspection: FigureInspection }[]
  const contacts: CapsuleContact[] = []
  const closest: CapsuleContact[] = []
  for (let i = 0; i < live.length; i++) {
    for (let j = i + 1; j < live.length; j++) {
      let best: CapsuleContact | null = null
      for (const ca of live[i].inspection.capsules) {
        for (const cb of live[j].inspection.capsules) {
          const depth = ca.now.r + cb.now.r - segmentSegmentDistance(ca.now.a, ca.now.b, cb.now.a, cb.now.b)
          const row = { a: live[i].name, capA: ca.id, b: live[j].name, capB: cb.id, depth }
          if (depth > 0) contacts.push(row)
          if (!best || depth > best.depth) best = row
        }
      }
      if (best) closest.push(best)
    }
  }
  contacts.sort((p, q) => q.depth - p.depth)
  const byName = new Map(live.map(f => [f.name, f.inspection]))
  const engagements: FrameInspection['engagements'] = []
  for (const f of live) {
    for (const e of f.inspection.engaged) {
      const opening = byName.get(e.partner)?.openings.find(o => o.channel === e.channel)
      engagements.push({ by: f.name, of: e.partner, channel: e.channel, w: e.w, opening: opening ? opening.radius : null })
    }
  }
  return { contacts, closest, engagements }
}
