/**
 * MIRROR PANES (preset `mirror`, plan-spiegelflaechen.md) — a slot material
 * becomes a planar reflector on ITS OWN faces.
 *
 * Part 1 (this half of the file) is pure arithmetic, so a smoke can pin it
 * without WebGL: the plane a pane is measured from, and the per-frame budget.
 *
 * THE PLANE IS MEASURED HERE, ONCE. The server's area detection reports a
 * centroid and a normal on the model sidecar, but the payload carries only
 * `{preset: "mirror"}`: the pane's plane is a property of the mesh in front of
 * the renderer, both renderers call this one routine, and a value measured in
 * one place cannot drift between them. `scripts/smoke_mirror_plane.mjs` pins
 * the arithmetic with hand-derived numbers and can cross-check a local prop
 * against its sidecar (§ B5a — numbers, never screenshots).
 */

export interface MirrorPlane {
  /** Area-weighted centroid of the faces, in the geometry's own space. */
  point: [number, number, number]
  /** Unit normal by the faces' winding (right-hand rule). The render hook
   *  flips it towards the camera per frame, so the sign only has to be
   *  consistent, not "outward". */
  normal: [number, number, number]
}

/**
 * The plane through a set of triangles. `ranges` are `[start, count]` pairs in
 * three's `geometry.groups` convention — INDEX units when `index` is given,
 * VERTEX units otherwise; a `count` past the end is clamped (three itself
 * stores `Infinity` for "the rest"). Returns `null` when the faces have no
 * area (a pane nothing can be measured from is not a mirror; the caller then
 * leaves the material as modelled).
 */
export function planeOfFaces(
  positions: ArrayLike<number>,
  index: ArrayLike<number> | null,
  ranges: ReadonlyArray<readonly [number, number]>,
): MirrorPlane | null {
  const total = index ? index.length : Math.floor(positions.length / 3)
  const vert = (i: number): [number, number, number] => {
    const v = index ? index[i] : i
    return [positions[v * 3], positions[v * 3 + 1], positions[v * 3 + 2]]
  }
  let nx = 0, ny = 0, nz = 0          // sum of (b-a)×(c-a) = 2·area·normal
  let cx = 0, cy = 0, cz = 0          // sum of centroid·(2·area)
  let weight = 0
  for (const [start, count] of ranges) {
    const s = Math.max(0, Math.floor(start))
    const end = Math.min(total, s + Math.max(0, Math.floor(count)))
    for (let i = s; i + 2 < end; i += 3) {
      const a = vert(i), b = vert(i + 1), c = vert(i + 2)
      const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2]
      const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2]
      const fx = uy * vz - uz * vy
      const fy = uz * vx - ux * vz
      const fz = ux * vy - uy * vx
      const twiceArea = Math.sqrt(fx * fx + fy * fy + fz * fz)
      if (twiceArea <= 0) continue
      nx += fx; ny += fy; nz += fz
      cx += (a[0] + b[0] + c[0]) / 3 * twiceArea
      cy += (a[1] + b[1] + c[1]) / 3 * twiceArea
      cz += (a[2] + b[2] + c[2]) / 3 * twiceArea
      weight += twiceArea
    }
  }
  const len = Math.sqrt(nx * nx + ny * ny + nz * nz)
  if (weight <= 1e-12 || len <= 1e-12) return null
  return {
    point: [cx / weight, cy / weight, cz / weight],
    normal: [nx / len, ny / len, nz / len],
  }
}

/**
 * How many reflections a frame may render, across every mirror of the app.
 *
 * The frame is `renderer.info.render.frame`, and every reflection IS a nested
 * `renderer.render`, which bumps that counter by one before the next hook of
 * the same top-level frame runs. So "the same frame" is `frame === expected`
 * where `expected` is the last frame seen plus the nested renders granted
 * since; anything else is a new frame and resets the count.
 */
export class MirrorBudget {
  private used = 0
  private expected = Number.NaN
  constructor(private readonly maxPerFrame: number) {}

  allow(frame: number): boolean {
    if (frame !== this.expected) this.used = 0
    this.expected = frame
    if (this.used >= this.maxPerFrame) return false
    this.used += 1
    this.expected = frame + 1
    return true
  }
}
