/**
 * groundAreas — the geometry of a PAINTED TERRAIN AREA, for both renderers.
 *
 * The free metre world (plan-freie-weltkarte.md § D) draws its ground from
 * polygons: `GET /play/terrain` delivers a list of areas, each a ring of world
 * points `[x, z]` in metres plus the kind that says how it looks. Turning such
 * a ring into a mesh is geometry, so it lives HERE and not in either app —
 * exactly like `place()` and the room clip. The 3D client lays them out on the
 * world map, the admin preview will show the same polygons under a location.
 *
 * `three` is a PARAMETER, never an import (package rule): the admin bundle
 * loads Three lazily and an import here would drag it into its main chunk. The
 * type-only import below vanishes on compile, which is also what keeps this
 * module loadable by `client3d/scripts/smoke_ground_math.mjs` — the pure ring
 * maths (`signedArea`, `polygonArea`, `cleanRing`, `shapePoints`) is checked
 * there against hand-derived areas, with no bundler and no Three.
 *
 * GROUND_Y DISCIPLINE: nothing here bakes a height in. Every vertex comes out
 * at y = 0; where the ground actually is, is the caller's `ground_y(x, z)` and
 * is applied by positioning the mesh, never by moving vertices. That is why
 * stacked areas are separated by `renderOrder` + `polygonOffset` and not by a
 * y ladder — see `AREA_POLYGON_OFFSET`.
 */
import type { BufferGeometry } from 'three'

type THREE = typeof import('three')

/** A world point on the ground plane: `[x, z]` in metres. */
export type Point2 = [number, number]

/** Below this the ring encloses nothing worth a mesh (m2). Square metres of a
 *  world map — a nanometre-squared sliver is a data artefact, not an area. */
export const AREA_EPS_M2 = 1e-9

/**
 * Depth-bias units for a stacked area, applied as
 * `polygonOffsetFactor = -index * AREA_POLYGON_OFFSET`.
 *
 * Painted areas are COPLANAR by construction: they all lie on the ground
 * plane, and a path drawn across a meadow shares every micrometre of y with
 * it. Separating them by height would break the one rule the whole seamless
 * world rests on (`ground_y` is the ground, full stop) and would show as a
 * visible step at every area edge once relief arrives. So the order of the
 * list — bottom to top, as the server sorts it — becomes `renderOrder` plus a
 * depth bias, and the geometry stays flat.
 */
export const AREA_POLYGON_OFFSET = 1

/**
 * Shoelace of a ring, SIGNED: positive when the ring runs counter-clockwise in
 * the world's XZ plane as seen from +y down, negative the other way.
 *
 *   A = 1/2 * SUM_i ( x_i * z_{i+1} - x_{i+1} * z_i )
 *
 * Fewer than three points enclose nothing and give 0. A repeated closing
 * corner contributes a zero-length edge and therefore changes nothing.
 */
export function signedArea(polygon: readonly Point2[]): number {
  const n = polygon?.length ?? 0
  if (n < 3) return 0
  let sum = 0
  for (let i = 0; i < n; i += 1) {
    const [x0, z0] = polygon[i]
    const [x1, z1] = polygon[(i + 1) % n]
    sum += x0 * z1 - x1 * z0
  }
  return sum / 2
}

/** Enclosed area in square metres — winding-blind, so a ring painted
 *  clockwise measures the same as the one painted the other way. */
export function polygonArea(polygon: readonly Point2[]): number {
  return Math.abs(signedArea(polygon))
}

/**
 * The ring a mesh can actually be built from: non-finite points dropped,
 * consecutive duplicates collapsed and a closing corner equal to the first
 * removed. Order is otherwise preserved and the winding is NOT touched — that
 * is `shapePoints`' job.
 *
 * A painted area may or may not repeat its first corner (the editor closes the
 * ring visually, the store keeps what was drawn), and `THREE.Shape` closes
 * itself: the doubled point would hand earcut a zero-length edge. Fewer than
 * three surviving points are no ring at all and give `[]`.
 */
export function cleanRing(polygon: readonly Point2[] | null | undefined): Point2[] {
  if (!Array.isArray(polygon)) return []
  const out: Point2[] = []
  for (const p of polygon) {
    if (!Array.isArray(p) || p.length < 2) continue
    const x = Number(p[0])
    const z = Number(p[1])
    if (!Number.isFinite(x) || !Number.isFinite(z)) continue
    const last = out[out.length - 1]
    if (last && last[0] === x && last[1] === z) continue
    out.push([x, z])
  }
  // The closing corner: same point as the start, one edge of length zero.
  while (out.length > 1) {
    const first = out[0]
    const last = out[out.length - 1]
    if (first[0] === last[0] && first[1] === last[1]) out.pop()
    else break
  }
  return out.length >= 3 ? out : []
}

/**
 * The ring in `THREE.Shape` space: world `[x, z]` becomes shape `[x, -z]`, and
 * the winding is normalised to counter-clockwise there.
 *
 * `ShapeGeometry` builds in XY with the face normal on +z. The ground wants XZ
 * with the normal UP, which is a -90 deg turn about X:
 *   rotX(-90): (x, y, z) -> (x, z, -y),  so (px, py, 0) -> (px, 0, -py)
 *              and the normal (0,0,1) -> (0,1,0)  — up, which is the point.
 * Hence the z flip on the way in. The flip also negates the shoelace, so a
 * world ring with a POSITIVE signed area is the one that has to be turned
 * around; the reversal keeps the first corner in place ([p0,p1,p2] ->
 * [p0,p2,p1]) so both windings of one polygon land on the identical list.
 *
 * `[]` when there is nothing to build (see `cleanRing`, `AREA_EPS_M2`).
 */
export function shapePoints(polygon: readonly Point2[] | null | undefined): Point2[] {
  const ring = cleanRing(polygon)
  const area = signedArea(ring)
  if (Math.abs(area) < AREA_EPS_M2) return []
  const ordered = area > 0
    ? [ring[0], ...ring.slice(1).reverse()]
    : ring
  return ordered.map(([x, z]) => [x, -z] as Point2)
}

/** What a built area is: the flat geometry plus the ground it covers. */
export interface AreaGeometry {
  /** XZ plane, y = 0 everywhere, normals up. Owned by the caller (dispose). */
  geometry: BufferGeometry
  /** enclosed ground in square metres — the scatter density reads it */
  areaM2: number
}

/**
 * Build the ground mesh geometry of one painted area.
 *
 * `null` when the ring encloses nothing (fewer than three distinct corners,
 * collinear points, a hairline): there is no face, and adding a zero-area mesh
 * would cost a draw call for nothing.
 *
 * The polygon is triangulated by `THREE.ShapeGeometry` (earcut) — concave
 * rings are handled, self-intersecting ones give whatever earcut makes of
 * them, which is the same deal both renderers get everywhere else. Holes are
 * NOT part of the payload: an area lying on top of another IS the hole, drawn
 * later in the list.
 */
export function buildAreaGeometry(T: THREE,
                                  polygon: readonly Point2[] | null | undefined
): AreaGeometry | null {
  const pts = shapePoints(polygon)
  if (!pts.length) return null
  const shape = new T.Shape(pts.map(([x, y]) => new T.Vector2(x, y)))
  const geometry = new T.ShapeGeometry(shape)
  // Flat on the ground, normals up. Nothing else moves the vertices — the
  // world height of this area is set on the MESH by the caller (`ground_y`).
  geometry.rotateX(-Math.PI / 2)
  geometry.computeBoundingSphere()
  return { geometry, areaM2: polygonArea(cleanRing(polygon)) }
}
