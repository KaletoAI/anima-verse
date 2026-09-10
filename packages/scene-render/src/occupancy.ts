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
 *                                                      OF ANOTHER ROW
 *
 * STRICTLY LESS, like the spacing and the footprint clearance: two props that
 * touch exactly both stand. The caller decides the radius — the 3D client's
 * measured half-width, the editor's `h · 0.5` — and there is no author field
 * for it: the distance is the sum of the half-extents and nothing else (user
 * decision 6, 2026-09-10).
 *
 * FOREIGN ONLY (fix wave 2026-09-10). A filed circle carries the TAG of the
 * row that planted it, and `blocks` skips every entry whose tag is the
 * querying row's own: within a row the author's `min_spacing_m` is the
 * distance, and a row without one is meant to stand as dense as its density
 * says. The first cut judged a row against itself with `2 · clearM`, which
 * capped a wood of 8 m trees at one or two per 100 m² whatever the author
 * wrote, and thinned every existing world by an order of magnitude. An entry
 * or a query WITHOUT a tag never matches by tag — it always counts — so a
 * caller that files nothing but foreign points may leave the tag off.
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
 * Structurally it is the `ScatterOccupancy` the samplers accept (declared in
 * `scatter.ts`, which stays import-free); this file imports the cell mapping
 * from there for `cellOccupancy`, so the smoke bundles it (`loadBundled`)
 * rather than transpiling it on its own.
 */
import { scatterCellAt } from './scatter'
import type { ScatterOccupancy } from './scatter'

/** The bucket edge in metres. 8 m is a few props wide: a candidate's search
 *  covers ±ceil((r + rMax)/8) buckets, one or two for anything tree-sized, and
 *  the buckets themselves stay a handful of circles each. */
const OCCUPANCY_BUCKET_M = 8

/** One filed circle: centre, radius, and the tag of the row that filed it
 *  (`undefined` = untagged, counts against everybody). */
type Filed = [number, number, number, string | undefined]

export class OccupancyGrid {
  private readonly bucketM: number
  /** the filed circles, keyed by bucket */
  private readonly buckets = new Map<string, Filed[]>()
  /** the largest radius ever filed — how far a search has to reach. A big
   *  occupant (a 30 m crown) must be found from a bucket the small candidate's
   *  own radius would never look into. */
  private rMax = 0

  constructor(bucketM: number = OCCUPANCY_BUCKET_M) {
    const edge = Number(bucketM)
    this.bucketM = Number.isFinite(edge) && edge > 0 ? edge : OCCUPANCY_BUCKET_M
  }

  /** File a circle under the row `tag`. A junk centre files nothing; a junk
   *  or negative radius files a point (radius 0), which still blocks anything
   *  whose own radius reaches it. No tag = the circle counts for every row. */
  add(x: number, z: number, r: number, tag?: string): void {
    if (!Number.isFinite(x) || !Number.isFinite(z)) return
    const radius = Number.isFinite(r) && r > 0 ? r : 0
    const key = `${Math.floor(x / this.bucketM)},${Math.floor(z / this.bucketM)}`
    const bucket = this.buckets.get(key)
    if (bucket) bucket.push([x, z, radius, tag])
    else this.buckets.set(key, [[x, z, radius, tag]])
    if (radius > this.rMax) this.rMax = radius
  }

  /** Would a circle of radius `r` at `(x, z)` overlap a filed one of ANOTHER
   *  row? Entries filed under the same `tag` are the querying row's own and
   *  do not count; an untagged entry, or an untagged query, always counts. */
  blocks(x: number, z: number, r: number, tag?: string): boolean {
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
        for (const [ax, az, ar, atag] of near) {
          // The row's own props are its own business (`min_spacing_m`).
          // Only a DEFINED tag can be one's own — `undefined === undefined`
          // must not read as a match, or an untagged grid would block nothing.
          if (tag !== undefined && atag === tag) continue
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

/** The grids of one rebuild pass, keyed `"cx,cz"` — see `cellOccupancy`. */
export type CellGrids = Map<string, OccupancyGrid>

/** What `cellOccupancy` hands a renderer: the grid of a named cell, and one
 *  `ScatterOccupancy` that routes to the grid of whatever cell a point is in. */
export interface CellOccupancy {
  /** the grid of cell (cx, cz), made on first use */
  gridOf(cx: number, cz: number): OccupancyGrid
  /** the routing adapter for a row computed for its whole line or rim */
  grid: ScatterOccupancy
}

/**
 * ONE GRID PER CELL, FOR A WHOLE PASS — the glue both renderers need between
 * the grids and the samplers, kept here so it exists once (§ A9; the clip
 * shader precedent).
 *
 * A `spread` row samples cell by cell and takes the cell's own grid
 * (`gridOf`). A row computed for its WHOLE line or rim (`strokeStations`,
 * `scatterEdgeInstances`, `scatterCenterInstance`) does not know cells, so
 * it takes `grid`: every `add` files the point into the grid of the cell it
 * stands in, every `blocks` asks the grid of the cell the QUERIED point is in
 * — and no other. The cell is the unit of the sampling, and a station just
 * over a cell border is therefore judged by its own cell's grid, exactly as
 * the cell sampler would judge a candidate there; that is what makes a cell
 * read the same whether a row was computed for it alone or for the shape.
 * The row tag travels through unchanged on both calls.
 *
 * `blocks` on a cell nobody has filed anything in answers false without
 * making a grid; `add` makes the grid. `grids` is the caller's map for the
 * pass — one per rebuild, shared by every area, thrown away with it.
 */
export function cellOccupancy(grids: CellGrids): CellOccupancy {
  const gridOf = (cx: number, cz: number): OccupancyGrid => {
    const key = `${cx},${cz}`
    let g = grids.get(key)
    if (!g) { g = new OccupancyGrid(); grids.set(key, g) }
    return g
  }
  return {
    gridOf,
    grid: {
      blocks: (x, z, r, tag) => grids.get(`${scatterCellAt(x)},${scatterCellAt(z)}`)
        ?.blocks(x, z, r, tag) ?? false,
      add: (x, z, r, tag) => gridOf(scatterCellAt(x), scatterCellAt(z)).add(x, z, r, tag),
    },
  }
}
