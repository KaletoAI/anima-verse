/**
 * placeGeometry.ts — WHERE THE SLOTS OF A PLACE AND THE HALVES OF A PAIR
 * STAND, for a renderer that has no composed payload to read them off
 * (plan-posen-plaetze.md § 3.3 / § 6).
 *
 * THE AUTHORITY IS THE SERVER: `app/core/scene_recipe.marker_slots` writes
 * `markers[].slots` into every scene payload, and `app/core/places.pair_yaw`
 * + `interaction_engine._rotate` put a seated pair on the map. A renderer
 * that shows a placed scene reads those numbers and computes nothing. The
 * routines here exist for the two admin previews that show a marker BEFORE
 * any composition — the prop viewer (one uncomposed prop) and the clip
 * preview (a virtual marker) — and for the floor-plan preview's pair halves,
 * which the payload does not carry. They mirror the server formulas line
 * for line; a change there is a change here (smoke:
 * `packages/scene-render/scripts/smoke_place_geometry.mjs`, the same
 * hand-derived numbers as `scripts/smoke_scene_recipe.py` block [M] and
 * `scripts/smoke_interaction.py` [9]).
 *
 * Conventions (§ B): compass facing in degrees, 0 = south (+z), 90 = east
 * (+x); XZ tuples in whatever length unit the caller measures in (world
 * metres, or a mesh's own units — scale `spacingM` and the role offsets
 * accordingly). No three.js: numbers in, tuples out.
 */

export type XZ = [number, number]

const deg = (v: number | undefined) => ((v || 0) * Math.PI) / 180

/**
 * The slot points of one place — `scene_recipe.marker_slots`: `capacity`
 * seats `spacingM` apart on the axis ACROSS the facing (a bench runs
 * sideways), centred on the marker. The lateral unit vector is the facing
 * turned by +90°, `(cos f, −sin f)`; slot i sits at `(i − (n−1)/2) ·
 * spacingM` along it. Capacity 1 is the marker itself. Unrounded — the
 * server rounds its world metres to centimetres for the payload.
 */
export function markerSlots(at: XZ, facingDeg: number | undefined,
                            capacity: number, spacingM: number): XZ[] {
  const n = Math.max(1, Math.round(capacity || 1))
  if (n === 1) return [[at[0], at[1]]]
  const f = deg(facingDeg)
  const lx = Math.cos(f)
  const lz = -Math.sin(f)
  return Array.from({ length: n }, (_, i) => {
    const d = (i - (n - 1) / 2) * spacingM
    return [at[0] + d * lx, at[1] + d * lz] as XZ
  })
}

/**
 * Y rotation (radians) of a pair clip on a marker — `places.pair_yaw`: the
 * clip's +X (role A → role B) falls along the marker's facing, which for
 * compass f is the world direction (sin f, cos f), mapped by
 * `atan2(−cos f, sin f)` = f − 90°; the pose's `yaw_offset` turns the frame
 * further. No facing reads as 0 = south.
 */
export function pairYaw(facingDeg: number | undefined, yawOffsetDeg: number): number {
  return deg((facingDeg ?? 0) - 90 + (yawOffsetDeg || 0))
}

/**
 * A clip-frame point turned by `yawRad` about Y — `interaction_engine
 * ._rotate`: `(x·c + z·s, −x·s + z·c)`. That is exactly what three.js does
 * to a child of a group with `rotation.y = yawRad`, so a figure placed here
 * and a figure parented under a turned group agree.
 */
export function rotateXZ(x: number, z: number, yawRad: number): XZ {
  const c = Math.cos(yawRad)
  const s = Math.sin(yawRad)
  return [x * c + z * s, -x * s + z * c]
}

/**
 * Where the two halves of a pair stand — the server's seating of a pair on
 * a place: the anchor is the place CENTRE (`places.centre_of`), the frame
 * is turned by `pairYaw`, and each role stands at its sidecar
 * `anchor_xz_m` in that frame (`start_interaction`).
 */
export function pairPoints(centre: XZ, facingDeg: number | undefined,
                           yawOffsetDeg: number,
                           roles: { a: XZ; b: XZ }): { a: XZ; b: XZ } {
  const yaw = pairYaw(facingDeg, yawOffsetDeg)
  const at = (o: XZ): XZ => {
    const [dx, dz] = rotateXZ(o[0], o[1], yaw)
    return [centre[0] + dx, centre[1] + dz]
  }
  return { a: at(roles.a), b: at(roles.b) }
}
