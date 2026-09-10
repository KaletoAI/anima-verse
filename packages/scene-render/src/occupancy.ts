/**
 * occupancy — what EARLIER rows have already planted, so later rows keep
 * clear of it (foreign spacing, 2026-09-10).
 *
 * `min_spacing_m` keeps a row's OWN props apart (`scatterInstances`); this
 * grid is the same idea ACROSS rows and areas. The lamp row along a road, the
 * benches on the rim of a square and the trees spread over it are sampled one
 * after the other — areas in payload order (bottom to top), per area the
 * `along` rows, then the `scatter` rows — and every survivor is filed here
 * with its half-extent. A later candidate is blocked while its own circle
 * would overlap a filed one:
 *
 *     blocked  <=>  hypot(x − ax, z − az) < r + ar     for any filed (ax, az, ar)
 *
 * STRICTLY LESS, like the spacing and the footprint clearance: two props that
 * touch exactly both stand. The caller decides the radius — the 3D client's
 * measured half-width, the editor's `h · 0.5` — and there is no author field
 * for it: the distance is the sum of the half-extents and nothing else (user
 * decision 6, 2026-09-10).
 *
 * ONE GRID PER CELL, created by the caller (`ground.ts` / `mapMath.ts`) and
 * thrown away with the cell. The raster is the unit of the sampling, and a
 * grid that outlived it would make a cell's props depend on the order the
 * cells came into view — the very thing the cell seed exists to rule out.
 *
 * PURELY ADDITIVE. Nothing is ever removed; a candidate that lost is simply
 * not filed. That keeps every verdict a SUBTRACTION, the property every
 * sampler here relies on — a removal would let a later row un-block a spot an
 * earlier row had already decided against.
 *
 * No import, so the smoke loads this file through the same plain transpile
 * as `scatter.ts`. Structurally it is the `ScatterOccupancy` the samplers
 * accept (declared there, for the same no-import reason).
 */

/** The bucket edge in metres. 8 m is a few props wide: a candidate's search
 *  covers ±ceil((r + rMax)/8) buckets, one or two for anything tree-sized, and
 *  the buckets themselves stay a handful of circles each. */
const OCCUPANCY_BUCKET_M = 8

export class OccupancyGrid {
  private readonly bucketM: number
  /** the filed circles, keyed by bucket: `[x, z, r]` each */
  private readonly buckets = new Map<string, Array<[number, number, number]>>()
  /** the largest radius ever filed — how far a search has to reach. A big
   *  occupant (a 30 m crown) must be found from a bucket the small candidate's
   *  own radius would never look into. */
  private rMax = 0

  constructor(bucketM: number = OCCUPANCY_BUCKET_M) {
    const edge = Number(bucketM)
    this.bucketM = Number.isFinite(edge) && edge > 0 ? edge : OCCUPANCY_BUCKET_M
  }

  /** File a circle. A junk centre files nothing; a junk or negative radius
   *  files a point (radius 0), which still blocks anything whose own radius
   *  reaches it. */
  add(x: number, z: number, r: number): void {
    if (!Number.isFinite(x) || !Number.isFinite(z)) return
    const radius = Number.isFinite(r) && r > 0 ? r : 0
    const key = `${Math.floor(x / this.bucketM)},${Math.floor(z / this.bucketM)}`
    const bucket = this.buckets.get(key)
    if (bucket) bucket.push([x, z, radius])
    else this.buckets.set(key, [[x, z, radius]])
    if (radius > this.rMax) this.rMax = radius
  }

  /** Would a circle of radius `r` at `(x, z)` overlap a filed one? */
  blocks(x: number, z: number, r: number): boolean {
    if (this.buckets.size === 0) return false
    if (!Number.isFinite(x) || !Number.isFinite(z)) return false
    const radius = Number.isFinite(r) && r > 0 ? r : 0
    const reach = Math.ceil((radius + this.rMax) / this.bucketM)
    const bx = Math.floor(x / this.bucketM)
    const bz = Math.floor(z / this.bucketM)
    for (let dz = -reach; dz <= reach; dz += 1) {
      for (let dx = -reach; dx <= reach; dx += 1) {
        const near = this.buckets.get(`${bx + dx},${bz + dz}`)
        if (!near) continue
        for (const [ax, az, ar] of near) {
          const ex = x - ax
          const ez = z - az
          const limit = radius + ar
          // Squared on both sides — no square root in the innermost loop, and
          // the strict `<` survives the squaring of non-negative numbers.
          if (ex * ex + ez * ez < limit * limit) return true
        }
      }
    }
    return false
  }
}
