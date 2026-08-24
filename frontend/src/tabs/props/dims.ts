/**
 * Prop dims geometry — the client half of the size model (plan-room-props.md).
 *
 * Kept in LOCKSTEP with `oriented_dims` in app/core/props.py: same Euler
 * order, same corner rotation, same rounding — change both or neither.
 */

/** The three real edges in metres, in the order the forms show them. */
export type DimKey = 'width_m' | 'depth_m' | 'height_m'

/** …as a list, for the loops that have to touch all three. */
export const DIM_KEYS: DimKey[] = ['width_m', 'depth_m', 'height_m']

/**
 * The window a stored edge lives in — `props._coerce_dim_m` keeps `(0, 100]`
 * rounded to three decimals, so 0.001 m is the smallest number that survives
 * the trip: anything under it rounds to zero there, and a zero CLEARS the key
 * instead of storing a size.
 */
export const DIM_MIN_M = 0.001
export const DIM_MAX_M = 100

/**
 * `[width(x), height(y), depth(z)]` = the AABB extents of the raw mesh box
 * AFTER the orientation fix: the 8 corners are rotated by Rx·Ry·Rz (degrees,
 * three.js 'XYZ' order) and re-measured.
 *
 * Rotating an AABB overestimates for non-90° fixes (it measures a box around
 * the box), which is fine and deterministic — these numbers are used as
 * PROPORTIONS, not as a hull.
 */
export function orientedDims(bbox: [number, number, number],
  rot?: { x?: number; y?: number; z?: number }): [number, number, number] {
  const b = bbox.map((v) => Math.abs(Number(v) || 0))
  const rad = (v?: number) => ((Number(v) || 0) * Math.PI) / 180
  const rx = rad(rot?.x)
  const ry = rad(rot?.y)
  const rz = rad(rot?.z)
  const cx = Math.cos(rx), sx = Math.sin(rx)
  const cy = Math.cos(ry), sy = Math.sin(ry)
  const cz = Math.cos(rz), sz = Math.sin(rz)
  // M = Rx · Ry · Rz
  const m = [
    [cy * cz, -cy * sz, sy],
    [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
    [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
  ]
  const half = b.map((v) => v / 2)
  const lo = [Infinity, Infinity, Infinity]
  const hi = [-Infinity, -Infinity, -Infinity]
  for (const i of [-1, 1]) {
    for (const j of [-1, 1]) {
      for (const k of [-1, 1]) {
        const p = [i * half[0], j * half[1], k * half[2]]
        for (let r = 0; r < 3; r++) {
          const v = m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2]
          if (v < lo[r]) lo[r] = v
          if (v > hi[r]) hi[r] = v
        }
      }
    }
  }
  const r5 = (v: number) => Math.round(v * 100000) / 100000
  return [r5(hi[0] - lo[0]), r5(hi[1] - lo[1]), r5(hi[2] - lo[2])]
}

const round3 = (v: number) => Math.round(v * 1000) / 1000
const clampM = (v: number) => Math.min(Math.max(v, DIM_MIN_M), DIM_MAX_M)

/**
 * ONE edited edge, three answers — the size trio rescaled along a fixed
 * aspect (user decision 2026-08-24: "change the height of variant 2 and the
 * width and the depth follow").
 *
 * WHY ALL THREE MOVE. A prop is never squeezed on one axis: `place()` in
 * `@anima/scene-render` scales the mesh UNIFORMLY so that its largest oriented
 * edge becomes `max(width, depth, height)`. The trio therefore has exactly one
 * degree of freedom — it says how BIG the object is, and its ratios say what
 * SHAPE it is. Moving one number alone would not resize the object, it would
 * only rewrite what the other two claim about a shape that never changed.
 *
 * `ratios` is any triple with the variant's proportions — a measured mesh box
 * (via `orientedDims`) or the dims it already renders at; only the quotients
 * matter, never the unit. The edited value is clamped and rounded to what the
 * server really keeps (`DIM_MIN_M`…`DIM_MAX_M`, three decimals) BEFORE the
 * factor is taken, so the stored trio is exactly proportional — no drift
 * between what was sent and what comes back.
 *
 * Returns `null` when the redistribution has no meaning: a value that is not a
 * positive number, or a ratio source with a non-positive edge (a flat mesh
 * box). The caller then writes the edited field alone rather than a zero.
 *
 * A follower that would leave the window is clamped, and the aspect no longer
 * holds exactly — a visible number the admin can correct, which beats silently
 * storing a 400 m edge.
 */
export function variantRedistribute(
  editedKey: DimKey,
  value: number,
  ratios: Record<DimKey, number>,
): Record<DimKey, number> | null {
  if (!Number.isFinite(value) || value <= 0) return null
  const base = Number(ratios?.[editedKey])
  if (!Number.isFinite(base) || base <= 0) return null
  const edited = round3(clampM(value))
  const factor = edited / base
  const out = {} as Record<DimKey, number>
  for (const key of DIM_KEYS) {
    if (key === editedKey) {
      out[key] = edited
      continue
    }
    const r = Number(ratios[key])
    if (!Number.isFinite(r) || r <= 0) return null
    out[key] = round3(clampM(r * factor))
  }
  return out
}
