/**
 * POSTURE SUPPORT (Ruling A150) — a pair fit (`pairFit.ts`) may move and turn the entering figure only as far as the
 * figure stays plausibly SUPPORTED: what carries it (feet standing, knees/shins kneeling, hips/side/thighs lying) stays
 * on the surface — it neither floats nor sinks — and a turn happens about the support, not about the hips in the air.
 * One geometry for both renderers: Auto-align, the pair check, the place preview's live fit and client3d's runtime fit
 * read the same `FigureInspection.capsules` (world) and hand the same `SupportSample` in.
 *
 * THE SUPPORT of one frame: among the figure's body capsules of `SUPPORT_CAPSULES` (legs, trunk, upper arms) the
 * capsule's lowest point is min(a_y, b_y) − r (world up = +Y). The SUPPORTING capsules are those whose lowest point lies
 * within `POSTURE.bandM` of the lowest one — so the clip itself says what carries the figure (feet when standing, the
 * shins when kneeling, the side and thighs when lying), never a table per pose. The support height h = the lowest
 * point of the supporting capsules (their endpoints `pts` with radii `r`).
 *
 * THE BASELINE: `base` = h of the same frame in the clip's own posture (no partner fix). The fix may change h by
 * Δ = h(fix) − base only within [−`POSTURE.sinkM`, +`POSTURE.floatM`] — a residual of `POSTURE.weight` per metre
 * beyond the band (`postureResidual`). Since h moves with the vertical shift AND with any turn that lifts or lowers the
 * support, the least squares can still shift along the surface freely, and can only turn about a pivot ON the support
 * (a turn about the hips plus the vertical shift that brings the support back).
 *
 * THE ORDER of the levers (Ruling A150): root pitch (`chainBend.ts` THE ROOT) → chain bend → shift along the surface →
 * a small turn about the support → the residual. The bend comes first by construction (residuals after the bend); a
 * turn costs `POSTURE.turnCostM` per radian (× √N) against `BEND_STAY`'s 0.05 per metre of shift, so a turn is taken
 * only where it buys more than it costs. A standing or lying place type allows only a few degrees of turn at all
 * (`postureAngleCapDeg`).
 *
 * THE REPORT (`postureReport`): per frame Δ; `gapMm` = the largest float (Δ > 0), `sinkMm` = the largest sink (Δ < 0),
 * `heightMm` = the largest h − surface (the support's own height above the surface, informational: a shin capsule
 * ends at the ankle), `limited` = some frame sits at the band's edge (within `POSTURE.edgeM`) — the solve wanted more
 * than the posture allows: the lamp's reason "posture limit".
 */
import type { Vec3 } from './collision'

export const POSTURE = Object.freeze({
  /** Supporting capsules: lowest points within this of the lowest one (metres). */
  bandM: 0.04,
  /** The fix may lift the support by at most this (metres) — "no floating". */
  floatM: 0.015,
  /** … and lower it by at most this (metres) — "no sinking". */
  sinkM: 0.01,
  /** Residual weight per metre beyond the band (1 cm beyond costs like 3 m of tip lateral in one frame): a near-hard
   *  limit — the entry condition (`CONTACT_ENTRY_WEIGHT` × N) must not buy a float or a sink. */
  weight: 300,
  /** Residual per radian of turn (× √N): a turn must pay for itself. */
  turnCostM: 0.15,
  /** A frame within this of the band's edge counts as "at the posture limit" (metres). */
  edgeM: 0.002,
})
/** The capsules that may carry a figure (`app/core/collision.py` CAPSULES ids). */
export const SUPPORT_CAPSULES: readonly string[] = ['left_thigh', 'left_shin', 'right_thigh', 'right_shin', 'hips',
  'spine', 'chest', 'outer_hips', 'outer_waist', 'outer_spine', 'outer_chest', 'left_upper_arm', 'right_upper_arm',
  'left_forearm', 'right_forearm', 'head']
/** The largest turn (degrees) a place type allows on top of its support: standing and lying stay nearly level. */
export const POSTURE_ANGLE_CAP_DEG: Readonly<Record<string, number>> = Object.freeze({ stand: 3, lie: 5 })
export function postureAngleCapDeg(group: string | null | undefined, bound: number): number {
  const cap = group ? POSTURE_ANGLE_CAP_DEG[group] : undefined
  return cap === undefined ? bound : Math.min(bound, cap)
}

export interface SupportSample {
  /** The supporting capsules (ids, for re-selecting the same ones in another pass). */
  ids: string[]
  /** Their endpoints (world) and each endpoint's radius. */
  pts: Vec3[]
  r: number[]
  /** The support height of the clip's own posture this frame (world y); absent = this sample's own height. */
  base?: number
  /** The surface height under the figure (world y), for the report only. */
  surface?: number
}

interface CapsuleLike { id: string; now: { a: readonly number[]; b: readonly number[]; r: number } }

/** The support of one frame (module docstring THE SUPPORT); `ids` = re-use these capsules (another pass of the same
 *  frame), `map` = to the caller's space (points). Null when the figure has none of the capsules. */
export function supportSample(capsules: readonly CapsuleLike[], opts: { ids?: readonly string[] | null; surface?: number;
  map?: (p: readonly number[]) => Vec3 } = {}): SupportSample | null {
  const map = opts.map ?? ((p: readonly number[]) => [p[0], p[1], p[2]] as Vec3)
  const rows = capsules.filter((c) => SUPPORT_CAPSULES.includes(c.id)).map((c) => {
    const a = map(c.now.a), b = map(c.now.b)
    return { id: c.id, a, b, r: c.now.r, low: Math.min(a[1], b[1]) - c.now.r }
  })
  if (!rows.length) return null
  let pick = opts.ids ? rows.filter((x) => opts.ids!.includes(x.id)) : []
  if (!pick.length) {
    const lo = Math.min(...rows.map((x) => x.low))
    pick = rows.filter((x) => x.low <= lo + POSTURE.bandM)
  }
  return { ids: pick.map((x) => x.id), pts: pick.flatMap((x) => [x.a, x.b]), r: pick.flatMap((x) => [x.r, x.r]),
    ...(opts.surface !== undefined ? { surface: opts.surface } : {}) }
}

/** The support height of points `pts` (radii `r`): the lowest capsule point. */
export function supportHeight(pts: readonly Vec3[], r: readonly number[]): number {
  let h = Infinity
  for (let i = 0; i < pts.length; i++) h = Math.min(h, pts[i][1] - r[i])
  return h
}
/** The band excess of Δ (metres; 0 inside [−sinkM, +floatM]). */
export function postureExcess(delta: number): number {
  return delta > POSTURE.floatM ? delta - POSTURE.floatM : delta < -POSTURE.sinkM ? delta + POSTURE.sinkM : 0
}

export interface PostureReport {
  frames: number
  gapMm: number
  sinkMm: number
  heightMm: number | null
  limited: boolean
}
/** THE REPORT over samples whose support points are where they are rendered (`movedPts(i)` = frame i's points). */
export function postureReport(rows: readonly { support?: SupportSample | null; pts?: readonly Vec3[] }[]): PostureReport {
  let gap = 0, sink = 0, height: number | null = null, limited = false, frames = 0
  for (const x of rows) {
    const s = x.support
    if (!s) continue
    frames++
    const h = supportHeight(x.pts ?? s.pts, s.r)
    const base = s.base ?? supportHeight(s.pts, s.r)
    const d = h - base
    gap = Math.max(gap, d); sink = Math.max(sink, -d)
    if (d >= POSTURE.floatM - POSTURE.edgeM || d <= -POSTURE.sinkM + POSTURE.edgeM) limited = true
    if (s.surface !== undefined) height = Math.max(height ?? -Infinity, h - s.surface)
  }
  return { frames, gapMm: gap * 1000, sinkMm: sink * 1000, heightMm: height === null ? null : height * 1000, limited }
}
