/**
 * surfaceHeightAt() — THE sampling formula of a baked model surface (spec
 * surface-height § 6.2), once for the 3D client, the admin verify and — as a
 * line-for-line Python twin (`app/core/model_surface.surface_height_at`) —
 * the server's `/play/pos` gate. The two are proven equal on one hand table
 * (client3d/scripts/smoke_surface_math.mjs, scripts/smoke_model_surface.py).
 *
 * It is the exact INVERSE of `placeModelSpec` (place.ts): the placed model is
 * scaled by `s = max_m / extent_snapped`, hung on its own centre, yawed by
 * `Ry(+yaw)` about that point and set on `anchor` with its underside on
 * `bottom_y`. So a tile-local (x, z) walks back through anchor → −yaw → 1/s →
 * +centre into the lattice, and the lattice's centimetres over `box_min.y`
 * scale straight onto `bottom_y`.
 *
 * `lift` is the storey-0 terrain lift the placement was moved by AFTER
 * `place()` seated it (§ A16.9, `reliftPlacement`) — the lattice stands where
 * its model stands, so whoever moved the model hands the same number in here.
 *
 * Pure: no three, no scene state. Answers null wherever the lattice does not
 * — outside its extent or next to a null node — so the caller's next rung
 * (the declaration, the plates, the terrain) has the floor there.
 */
import type { SceneSurface } from './types'

export interface SurfacePlacement {
  anchor: [number, number]
  yaw_deg: number
  bottom_y: number
  max_m?: number
  measure: string
}

export interface PlacedSurface {
  id: string
  spec: SurfacePlacement
  surface: SceneSurface
  /** The § A16.9 terrain lift this placement carries right now (0 until it has
   *  been placed). Kept on the entry, not re-derived: the mount, the re-drape
   *  and the tier swap all move the model through one funnel. */
  lift: number
  /** Storey of the placement (`spec.level`) — a ground ladder must not pull a
   *  figure onto the lattice of another floor. */
  level: number
  /** Room the placement belongs to (`spec.room_id`, `''` for none) — a room's
   *  own stands ask only its own lattices. */
  roomId: string
}

function extentOf(surface: SceneSurface, measure: string): number {
  const [ex, ey, ez] = surface.extent_snapped
  return measure === 'xyz' ? Math.max(ex, ey, ez) : Math.max(ex, ez)
}

/** `max_m` over the snapped extent — the one factor `placeModelSpec` applies. */
export function surfaceScale(surface: SceneSurface, spec: SurfacePlacement): number {
  return (spec.max_m || 1) / (extentOf(surface, spec.measure) || 1)
}

/** Standing height (tile-local metres) of placement `spec` at (x, z), or null
 *  where the lattice does not answer.
 *
 *  The bake's outermost lattice ring is cast 1 mm inside the box but read at
 *  its nominal node coordinate, so when the box extent is not a whole multiple
 *  of `step` the last ring's value extrapolates outward over up to one step of
 *  ground the model does not cover. */
export function surfaceHeightAt(surface: SceneSurface, spec: SurfacePlacement,
                                x: number, z: number, lift = 0): number | null {
  const s = surfaceScale(surface, spec)
  const cx = (surface.box_min[0] + surface.box_max[0]) / 2
  const cz = (surface.box_min[2] + surface.box_max[2]) / 2
  const qx = x - spec.anchor[0]
  const qz = z - spec.anchor[1]
  const th = ((spec.yaw_deg || 0) * Math.PI) / 180
  const c = Math.cos(th)
  const sn = Math.sin(th)
  const lx = qx * c - qz * sn
  const lz = qx * sn + qz * c
  const u = (lx / s + cx - surface.origin[0]) / surface.step
  const v = (lz / s + cz - surface.origin[1]) / surface.step
  const { cols, rows, values } = surface
  if (!(u >= 0 && u <= cols - 1 && v >= 0 && v <= rows - 1)) return null
  const i0 = cols > 1 ? Math.min(Math.floor(u), cols - 2) : 0
  const j0 = rows > 1 ? Math.min(Math.floor(v), rows - 2) : 0
  const fu = u - i0
  const fv = v - j0
  const i1 = Math.min(i0 + 1, cols - 1)
  const j1 = Math.min(j0 + 1, rows - 1)
  const a = values[j0 * cols + i0]
  const b = values[j0 * cols + i1]
  const cc = values[j1 * cols + i0]
  const d = values[j1 * cols + i1]
  if (a == null || b == null || cc == null || d == null) return null
  const top = a + (b - a) * fu
  const bot = cc + (d - cc) * fu
  const val = top + (bot - top) * fv
  return (spec.bottom_y || 0) + lift + (s * val) / 100
}

/** The highest answering surface of a list (a crate on a rock), or null. Each
 *  entry is sampled with ITS OWN lift — two placements on a slope stand at
 *  different heights even when their specs were composed against one datum. */
export function highestSurfaceAt(list: readonly PlacedSurface[], x: number, z: number): number | null {
  let best: number | null = null
  for (const p of list) {
    const y = surfaceHeightAt(p.surface, p.spec, x, z, p.lift)
    if (y !== null && (best === null || y > best)) best = y
  }
  return best
}
