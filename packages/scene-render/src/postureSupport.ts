/**
 * POSTURE SUPPORT (Ruling A150) — Auto-align (`pairAlign.ts` over the residuals of `pairFit.ts`) may move and turn
 * the entering figure only as far as the figure stays plausibly SUPPORTED: what carries it (feet standing, knees/shins
 * kneeling, hips/side/thighs lying) stays on the surface — it neither floats nor sinks — and a turn happens about the
 * support, not about the hips in the air. The samples carry a `SupportSample` read from `FigureInspection.capsules`
 * (world).
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
 * THE ORDER of the levers (Ruling A150, the bend taken out 2026-11-20): the clip's root angle (`chainBend.ts` THE ROOT
 * ANGLE, already on the samples) → shift along the surface → a small turn about the support → the residual. Auto-align
 * is rigid: the bend of `chainBend.ts` comes only after it, in the renderers. A shift costs nothing of its own; a
 * turn costs `POSTURE.turnCostM` per radian (× √N), so a turn is taken only where it buys more than it costs. A standing or lying place type allows only a few degrees of turn at all
 * (`postureAngleCapDeg`).
 *
 * THE SUPPORT, ABSOLUTE (owner 2026-11-23, `SURFACE`): Auto-align may now turn the moved role by tens of degrees, and
 * a band around the clip's own posture would carry a body that floats or sinks at the start along with it. So the moved
 * role's LOWEST support capsule (over all of `SUPPORT_CAPSULES`, `SupportSample.low` — whatever touches after the
 * turn) must touch the surface of its place (the place marker's height, `SupportSample.surface`): its gap
 * h_low − surface within [−`SURFACE.sinkM`, +`SURFACE.floatM`] = [−5 mm, +10 mm] (the capsules are fitted a few
 * millimetres outside the skin, `app/core/collision.py` margin 6 mm, so a touching body reads slightly above 0 and a
 * gap below −5 mm is the body in the prop), `POSTURE.weight` per metre beyond. The mode per frame (`supportMode`,
 * from the BASE arrangement): 'surface' — the absolute condition; 'band' — the posture band above, for a role whose
 * support is not the surface: one that stands on its feet (only the shins carry it and they stand upright — a shin
 * capsule ends at the ankle, the sole lies below it, and the clip's ground rule already holds the sole on the floor),
 * and one whose lowest capsule is more than `SURFACE.carriedM` = 50 mm above the surface at the base — carried by
 * the other person (the role on top); there THE CLEARANCE of `pairAlign.ts` keeps the bodies apart.
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
  /** Residual per radian of turn (× √N): a turn must pay for itself. Owner 2026-11-23 (the role turn of up to the
   *  clip's rotation range, its TOTAL from the base): 0.05 m per radian — a 90° turn costs like 8 cm of axis error per
   *  key frame, so a mismatch of 20 cm and more is worth turning for, a few millimetres are not. */
  turnCostM: 0.05,
  /** A frame within this of the band's edge counts as "at the posture limit" (metres). */
  edgeM: 0.002,
})
/** THE SUPPORT, ABSOLUTE (module docstring): the touch band against the surface and the height above it from which a
 *  role counts as carried by someone else (metres). */
export const SURFACE = Object.freeze({ floatM: 0.01, sinkM: 0.005, carriedM: 0.05 })
/** The capsules that may carry a figure (`app/core/collision.py` CAPSULES ids). */
export const SUPPORT_CAPSULES: readonly string[] = ['left_thigh', 'left_shin', 'right_thigh', 'right_shin', 'hips',
  'spine', 'chest', 'outer_hips', 'outer_waist', 'outer_spine', 'outer_chest', 'left_upper_arm', 'right_upper_arm',
  'left_forearm', 'right_forearm', 'head']
/** The largest TILT and ROLL (degrees) a place type allows on top of its support: a standing role stays upright (its yaw
 *  is free). A lying role is held by THE SUPPORT, ABSOLUTE instead (owner 2026-11-23: a turned body must lie ON the
 *  bed, which a cap of a few degrees cannot give). */
export const POSTURE_ANGLE_CAP_DEG: Readonly<Record<string, number>> = Object.freeze({ stand: 3 })
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
  /** The surface height under the figure (world y): THE SUPPORT, ABSOLUTE and the report. */
  surface?: number
  /** Every support capsule's endpoints and radii (not only the supporting ones): the lowest point after a turn. */
  low?: { pts: Vec3[]; r: number[] }
  /** Only the shins carry the figure and they stand upright (it stands on its feet). */
  feet?: boolean
  /** THE SUPPORT, ABSOLUTE: 'surface' = the lowest capsule touches the surface; 'band' (absent) = the posture band. */
  mode?: 'surface' | 'band'
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
  const feet = pick.every((x) => (x.id === 'left_shin' || x.id === 'right_shin')
    && Math.abs(x.a[1] - x.b[1]) > 0.5 * Math.hypot(x.a[0] - x.b[0], x.a[1] - x.b[1], x.a[2] - x.b[2]))
  return { ids: pick.map((x) => x.id), pts: pick.flatMap((x) => [x.a, x.b]), r: pick.flatMap((x) => [x.r, x.r]),
    low: { pts: rows.flatMap((x) => [x.a, x.b]), r: rows.flatMap((x) => [x.r, x.r]) }, feet,
    ...(opts.surface !== undefined ? { surface: opts.surface } : {}) }
}
/** THE SUPPORT, ABSOLUTE: the gap of the lowest support capsule over the surface (metres; null without a surface). */
export function surfaceGap(s: SupportSample | null | undefined, pts?: readonly Vec3[]): number | null {
  if (!s || s.surface === undefined || !s.low) return null
  return supportHeight(pts ?? s.low.pts, s.low.r) - s.surface
}
/** The mode of a frame from its BASE arrangement (module docstring): 'band' for a role on its feet or carried more than
 *  `SURFACE.carriedM` above the surface, 'surface' otherwise (and 'band' without a surface). */
export function supportMode(base: SupportSample | null | undefined): 'surface' | 'band' {
  const g = surfaceGap(base)
  return g === null || base?.feet || g > SURFACE.carriedM ? 'band' : 'surface'
}
/** The touch band's excess of a gap (metres; 0 inside [−`SURFACE.sinkM`, +`SURFACE.floatM`]). */
export function surfaceExcess(gap: number): number {
  return gap > SURFACE.floatM ? gap - SURFACE.floatM : gap < -SURFACE.sinkM ? gap + SURFACE.sinkM : 0
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
