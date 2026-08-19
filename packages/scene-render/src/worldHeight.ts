/**
 * The WORLD relief — the ONE height sampler both renderers use (§ A16).
 *
 * Not to be confused with `terrain.ts` next door: that one samples the relief
 * of a DETAIL SCENE, a 17 × 17 field over one location's reference square.
 * This one samples the open world — a grid of support points in world metres,
 * anchored at the world origin, delivered by `GET /play/heightfield`. A figure
 * walking cross-country stands on THIS field; inside a location's footprint
 * the scene field is added on top of it (the server does that addition for
 * every rule it applies, `app/core/relief.ground_lift_at`).
 *
 * THE TWIN. `app/core/heightfield.sample_height` is the same formula in
 * Python, and it has to be the same: the server refuses a walk report whose
 * slope is too steep (§ A15 Nr. 8) using its own reading of this field, so a
 * renderer that drapes the ground half a metre differently produces a figure
 * refused where the picture says the hill is gentle. Both are checked against
 * ONE hand-derived table — `scripts/smoke_heightfield.py` section [8] and
 * `client3d/scripts/smoke_world_height.mjs` — with the same field and the same
 * expected numbers. Change one side, change the table, change the other.
 *
 * SINCE v2 THE FIELD ARRIVES TWICE (§ A16.3): a coarsenable overview for the
 * distance, and 256 m tiles in an always-fine step (the server's own, 2 m
 * today) for everything the
 * ground DECIDES. `sampleWorldHeight` and its rectangle helpers read ONE field
 * and are unchanged by that — they are how a single grid is read, overview or
 * tile alike. The ladder over both lives at the bottom of this file
 * (`WorldHeightTiles`, `sampleCompositeHeight`).
 *
 * `three` is not imported here (nor anything else): this is pure arithmetic,
 * which is what lets the smoke transpile the file and run it on its own.
 */

/** The payload of `GET /play/heightfield` (§ A16). `heights[j][i]` is the
 *  height in metres at `(origin_x + i·step_m, origin_z + j·step_m)`; an empty
 *  world sends `rows`/`cols` 0 and an empty `heights`. */
export interface WorldHeightField {
  origin_x: number
  origin_z: number
  step_m: number
  rows: number
  cols: number
  heights: number[][]
  /** Change signature — identical to `height_sig` in the worldmap payload.
   *  Refetch when that one changes, never otherwise. */
  sig?: string
}

/**
 * Height of the world ground at (x, z) in world metres — bilinear.
 *
 * Grid fraction, then cell, then mix — the very shape `sampleTerrain` uses,
 * with a world origin instead of a plan fraction:
 *
 *   `fx = clamp((x − origin_x) / step, 0, cols − 1)`,
 *   `i = min(floor(fx), cols − 2)`, `tx = fx − i` (`fz`/`j`/`tz` likewise),
 *   then the bilinear mix of `h[j][i]`, `h[j][i+1]`, `h[j+1][i]`,
 *   `h[j+1][i+1]`.
 *
 * OUTSIDE THE GRID the border value applies, and that is exact rather than a
 * fallback: the server always rasters a ring of support points outside every
 * authored area, so the whole border is 0 and clamping there means "the flat
 * world". A field with fewer than 2 × 2 points carries no relief and answers
 * 0 — which is also what an empty world sends.
 */
export function sampleWorldHeight(field: WorldHeightField | null | undefined,
                                  x: number, z: number): number {
  if (!field) return 0
  const h = field.heights
  if (!h || h.length < 2) return 0
  const rows = h.length
  const cols = h[0]?.length || 0
  const step = field.step_m
  if (cols < 2 || !(step > 0)) return 0
  const clamp = (v: number, hi: number) => (v < 0 ? 0 : v > hi ? hi : v)
  const fx = clamp((x - field.origin_x) / step, cols - 1)
  const fz = clamp((z - field.origin_z) / step, rows - 1)
  const i = Math.min(Math.floor(fx), cols - 2)
  const j = Math.min(Math.floor(fz), rows - 2)
  const tx = fx - i
  const tz = fz - j
  const rowN = h[j] || []
  const rowS = h[j + 1] || []
  const north = (rowN[i] || 0) * (1 - tx) + (rowN[i + 1] || 0) * tx
  const south = (rowS[i] || 0) * (1 - tx) + (rowS[i + 1] || 0) * tx
  return north * (1 - tz) + south * tz
}

/**
 * Height of the DRAWN ground at (x, z) — the surface a renderer really builds.
 *
 * NOT the same number as `sampleWorldHeight`, and the difference is the whole
 * point. The field is defined bilinear (§ A16) and the server judges by that;
 * a MESH cannot be bilinear, it is triangles. Every renderer here cuts its
 * ground into cells of `cellM` and splits each cell from its minimum corner to
 * its maximum one (`gridMesh.gridPlate`), so within a cell the drawn surface is
 * one of two PLANES:
 *
 *   tz <= tx (the half towards +x):  h00 + tx·(h10 − h00) + tz·(h11 − h10)
 *   tz >  tx (the half towards +z):  h00 + tz·(h01 − h00) + tx·(h11 − h01)
 *
 * with `h00…h11` the four cell corners and `tx`/`tz` the fractions inside it.
 * The two agree on the diagonal, and both agree with the bilinear field at all
 * four corners — they part company INSIDE the cell, by up to a quarter of the
 * cell's twist `|h00 + h11 − h01 − h10|`. Measured on a plain 5 m hill with a
 * 10 m falloff on an 8 m grid that is a full metre.
 *
 * SO EVERYTHING THAT TOUCHES THE GROUND USES THIS ONE: the plate's vertices
 * (where it equals the bilinear reading anyway, they sit on corners), the
 * vertices of a painted area (which land wherever its outline runs — the
 * bilinear reading is what sank a meadow a metre into the plate), and every
 * figure, prop and marker standing on it. `sampleWorldHeight` stays what it
 * always was: the twin of the server's own reading of the field.
 *
 * `cellM` is the size the ground was actually cut at — `gridStepFor`'s answer,
 * which may be a doubling of the field's own `step_m`. Omitting it means "the
 * field's step", which is right whenever nothing was coarsened.
 */
export function sampleGroundHeight(field: WorldHeightField | null | undefined,
                                   x: number, z: number,
                                   cellM?: number): number {
  if (!field) return 0
  const step = cellM && cellM > 0 ? cellM : field.step_m
  if (!(step > 0)) return sampleWorldHeight(field, x, z)
  const i = Math.floor((x - field.origin_x) / step)
  const j = Math.floor((z - field.origin_z) / step)
  const x0 = field.origin_x + i * step
  const z0 = field.origin_z + j * step
  const tx = (x - x0) / step
  const tz = (z - z0) / step
  // The corners are read through the bilinear sampler on purpose: on the
  // field's own grid it returns the support point exactly, and on a COARSENED
  // grid (a doubled step) the corner is still a support point — while outside
  // the field it clamps to the border, which is the flat world the ring quads
  // of the plate lie in.
  const h00 = sampleWorldHeight(field, x0, z0)
  const h10 = sampleWorldHeight(field, x0 + step, z0)
  const h01 = sampleWorldHeight(field, x0, z0 + step)
  const h11 = sampleWorldHeight(field, x0 + step, z0 + step)
  return tz <= tx
    ? h00 + tx * (h10 - h00) + tz * (h11 - h10)
    : h00 + tz * (h01 - h00) + tx * (h11 - h01)
}

/**
 * Lowest and highest support point of the field, in metres.
 *
 * What it is FOR: everything that has to start above the whole world. The 3D
 * client rays its tiles from a fixed height (`scene/tiles.ts`), and a fixed 20
 * used to be that height — with a relief clamped at ±50 m (§ A1.7) a ray from
 * 20 m starts INSIDE a hill and finds nothing, which reads as a figure falling
 * back to the flat world on exactly the ground it should stand on.
 *
 * The support points ARE the extremes: between them the field is bilinear, and
 * a bilinear patch never leaves the range of its four corners. An empty or
 * degenerate field answers 0/0 — the flat world.
 */
export function worldHeightRange(field: WorldHeightField | null | undefined
): { min: number; max: number } {
  let min = 0
  let max = 0
  for (const row of field?.heights ?? []) {
    for (const v of row ?? []) {
      if (typeof v !== 'number' || !Number.isFinite(v)) continue
      if (v < min) min = v
      if (v > max) max = v
    }
  }
  return { min, max }
}

/** How many sample lines per axis `maxWorldHeightIn` may put across a
 *  rectangle. A fog rectangle can span the whole world, and 64 × 64 samples
 *  per rectangle is the budget at which a hundred of them still cost a
 *  millisecond or two on a rebuild that happens when the fog moves and never
 *  per frame. */
const MAX_RECT_LINES = 64

/** The sample coordinates across `[lo, hi]`: both ends plus every grid line
 *  strictly between them, thinned by a stride when there are more than
 *  `MAX_RECT_LINES` of them. */
function rectLines(lo: number, hi: number, origin: number, step: number): number[] {
  const out: number[] = [lo]
  if (step > 0 && hi > lo) {
    const first = Math.floor((lo - origin) / step) + 1
    const last = Math.ceil((hi - origin) / step) - 1
    const count = last - first + 1
    const stride = count > MAX_RECT_LINES ? Math.ceil(count / MAX_RECT_LINES) : 1
    for (let k = first; k <= last; k += stride) {
      const c = origin + k * step
      if (c > lo && c < hi) out.push(c)
    }
  }
  if (hi > lo) out.push(hi)
  return out
}

/**
 * Highest ground inside an axis-aligned rectangle of world metres.
 *
 * WHAT IT IS FOR: the fog quads (§ A12). A veil is one flat rectangle over
 * ground that is no longer flat, so it has to hang above the highest thing
 * under it — a quad on the average height sticks out of every hill it covers,
 * and the mountain pokes through the cloud.
 *
 * It reads the DRAWN ground (`sampleGroundHeight`), because that is what a
 * cloud can stick out of. Over each half-cell that surface is a PLANE, so its
 * maximum over any sub-rectangle sits at a corner of that piece: sampling the
 * rectangle's own edges plus every cell line inside it visits them all bar the
 * points where the cell diagonal leaves the rectangle, and those lie between
 * two corner heights that are themselves visited whenever they are inside.
 *
 * THE APPROXIMATION is the stride (`MAX_RECT_LINES`): a rectangle spanning
 * more than 64 cells per axis is sampled on every n-th line instead, so a
 * single peak between two sampled lines can be missed and the veil over a very
 * large rectangle can hang a little low. A TILED rectangle (`fogRects`, ~64 m
 * per quad) never comes close on a 4 m grid. A rectangle that stayed whole
 * because this very sampling found no relief under it (E8 task 5,
 * `worldHeightRangeIn`) can be world-wide — but then the same samples that
 * would have to miss the peak already say the ground is level, and a peak thin
 * enough to hide between two sample lines is thin enough to be a cloud's worth
 * of nothing. The stride is a guard, not the working case.
 */
export function maxWorldHeightIn(field: WorldHeightField | null | undefined,
                                 x0: number, z0: number,
                                 x1: number, z1: number,
                                 cellM?: number): number {
  return scanRect(field, x0, z0, x1, z1, cellM).max
}

/**
 * How much the drawn ground RISES AND FALLS inside a rectangle, in metres —
 * `max − min` over the same samples `maxWorldHeightIn` takes.
 *
 * WHAT IT IS FOR: the fog's tiling decision (E8 task 5). A veil rectangle is
 * cut into 64 m quads so one hill cannot lift a world-wide band into the sky —
 * but over ground that does not move, all those quads hang at the very same
 * height, and the tiling buys nothing but draw calls. This is the question
 * "does the ground under this rectangle move at all", and `fogRects` keeps a
 * rectangle whole whenever the answer is "not enough to see".
 *
 * 0 for a missing field: a world with no relief is flat everywhere, which is
 * exactly what "no range" says.
 */
export function worldHeightRangeIn(field: WorldHeightField | null | undefined,
                                   x0: number, z0: number,
                                   x1: number, z1: number,
                                   cellM?: number): number {
  const { min, max } = scanRect(field, x0, z0, x1, z1, cellM)
  return max - min
}

/** The one scan both rectangle queries share: the drawn ground's lowest and
 *  highest sample inside the rectangle (0/0 without a field). */
function scanRect(field: WorldHeightField | null | undefined,
                  x0: number, z0: number, x1: number, z1: number,
                  cellM?: number): { min: number; max: number } {
  if (!field) return { min: 0, max: 0 }
  const step = cellM && cellM > 0 ? cellM : field.step_m
  const xs = rectLines(Math.min(x0, x1), Math.max(x0, x1), field.origin_x, step)
  const zs = rectLines(Math.min(z0, z1), Math.max(z0, z1), field.origin_z, step)
  let max = -Infinity
  let min = Infinity
  for (const z of zs) {
    for (const x of xs) {
      const h = sampleGroundHeight(field, x, z, step)
      if (h > max) max = h
      if (h < min) min = h
    }
  }
  if (!Number.isFinite(max) || !Number.isFinite(min)) return { min: 0, max: 0 }
  return { min, max }
}

/**
 * The TILED height field as a client holds it (§ A16.3) — the coarse overview
 * plus whichever fine tiles have arrived.
 *
 * WHY THERE ARE TWO GRIDS AT ALL: one grid cannot be both. The overview covers
 * the whole world and is therefore coarsened as soon as somebody paints far
 * out — measured 4 m → 32 m — and at 32 m the ground a walker is judged against
 * is no longer the ground anybody authored. So the fine raster is delivered
 * in 256 m tiles on demand, every rule reads those, and the overview is a
 * PICTURE for the distance and nothing else.
 *
 * `tileM` is the payload's `tile_m`, never a constant in this file: the tile
 * size is a server decision, and a renderer that hardcodes 256 keeps answering
 * with a straight face the day that number moves. `tiles` holds what is LOADED;
 * which tiles EXIST is the loader's business, and it does not have to be told
 * here — an unindexed tile and a not-yet-fetched one read the same way, through
 * the overview.
 */
export interface WorldHeightTiles {
  tileM: number
  overview: WorldHeightField | null
  tiles: Map<string, WorldHeightField>
}

/**
 * Which tile owns (x, z) — `"tx,tz"`, the key of the tiles map (§ A16.3).
 *
 * THE ONE KEY MAPPING. Everything below goes through it so the floor rule lives
 * in a single place: a second `Math.floor` elsewhere is a second answer to
 * "which tile", and two answers part company on the seams first — exactly where
 * a wrong tile is a visible step in the ground.
 *
 * A point ON a seam belongs to the tile east/south of it. That choice is
 * invisible in the height and only decides which array is read: both neighbours
 * carry the shared support point, with the same number (the tile grids
 * duplicate their borders on purpose).
 */
export function tileKeyAt(tileM: number, x: number, z: number): string {
  // No tile size, no tile: without this line the division is ±Infinity or NaN
  // and EVERY point answers the same key — which a loader would then look up
  // and, having stored something under it once, actually find.
  if (!(tileM > 0)) return ''
  return `${Math.floor(x / tileM)},${Math.floor(z / tileM)}`
}

/**
 * Height of the world ground at (x, z) from the tiled field — fine tile first.
 *
 * THE PRECEDENCE IS BINDING FOR EVERY READER (§ A16.3):
 *
 *   the tile containing the point, if it is loaded  → bilinear out of IT
 *   else the overview                               → bilinear out of IT
 *   else 0                                          (the flat world)
 *
 * The server's own reading (`heightfield.world_height`) is the same ladder
 * minus its middle rung — it never looks at the overview at all.
 *
 * AND THE TWO SOURCES ARE NEVER MIXED for one point, which is the part that
 * looks over-strict until you see why. A tile and a coarsened overview are not
 * two accuracies of one number, they are two different landscapes: at 32 m
 * seven of eight support points per axis are gone, so a 22 m hill has none left
 * and simply does not exist in the overview — and the levelling ramp around a
 * footprint (§ A16.1) is "one cell wide", i.e. 32 m there against 4 m in the
 * tile, so a levelled place reaches differently far in the two rasters even
 * where resolution alone would explain nothing. Averaging or blending them
 * would invent ground that neither raster claims.
 *
 * A loaded tile therefore answers ALONE, including where it has no support
 * point for the question: `sampleWorldHeight` clamps to the tile's border, and
 * that clamp is the tile's statement, not a gap the overview may fill.
 */
export function sampleCompositeHeight(c: WorldHeightTiles | null | undefined,
                                      x: number, z: number): number {
  if (!c) return 0
  // No guard on `tileM` here: `tileKeyAt` owns that rule and answers `''` for a
  // composite without a tile size, which no map of tiles has an entry for.
  const tile = c.tiles?.get(tileKeyAt(c.tileM, x, z))
  if (tile) return sampleWorldHeight(tile, x, z)
  // `sampleWorldHeight` answers 0 for a missing field, so the last rung of the
  // ladder needs no branch of its own.
  return sampleWorldHeight(c.overview, x, z)
}

/**
 * The lattice the rectangle helpers walk: the FINEST grid the composite holds.
 *
 * A loaded tile decides it whenever there is one — its `step_m` is the step
 * that never coarsens, and its origin is a multiple of the tile size, hence a
 * point of the one world-origin-anchored grid. WHICH tile we take is therefore
 * irrelevant: all tile origins are congruent modulo the step, so they all
 * describe the same lattice. Without any tile the overview's own grid is the
 * finest thing there is, and with neither there is no ground to walk at all.
 *
 * TWO SERVER GUARANTEES CARRY THAT, and both are worth naming because the
 * congruence is what the whole file leans on. First, `tile_m` is a multiple of
 * the fine step (256 / 4), so every tile origin lies on the fine grid. Second,
 * the OVERVIEW's origin lies on it as well: `heightfield._axis_origin` snaps it
 * to a multiple of the overview's own step, and `_step_for` only ever DOUBLES
 * the fine step — so overview lines are a subset of tile lines, never an offset
 * raster. Break either and the two grids describe different points and the
 * lattice below would depend on which field answered.
 */
function compositeLattice(c: WorldHeightTiles
): { originX: number; originZ: number; step: number } | null {
  for (const tile of c.tiles?.values() ?? []) {
    if (tile && tile.step_m > 0) {
      return { originX: tile.origin_x, originZ: tile.origin_z, step: tile.step_m }
    }
  }
  const ov = c.overview
  if (ov && ov.step_m > 0) {
    return { originX: ov.origin_x, originZ: ov.origin_z, step: ov.step_m }
  }
  return null
}

/**
 * The cell grid the composite ground is DRAWN on: where its cells begin and how
 * big they are. The composite twin of the `cellM` argument that runs through
 * `sampleGroundHeight` and `scanRect`.
 *
 * THE ORIGIN IS THE OVERVIEW'S, and that is not a preference. Both renderers
 * cut their ground with `gridMesh` anchored at the FIELD's origin — `ground.ts`
 * hands `field.origin_x`/`origin_z` to `gridPlate` and `subdivideOnGrid`, and
 * that field is the overview — so a sampler anchoring its cells anywhere else
 * would answer for a different pair of triangles than the mesh is built of,
 * i.e. off the drawn surface by up to a quarter of a cell's twist. Tile origins
 * are congruent to the overview's modulo the fine step (the two guarantees
 * above), so the fine grid remains a subgrid whichever anchor one takes — but
 * only ONE of them is where the mesh was actually cut.
 *
 * `cellM` is the size the ground was really cut at (`gridStepFor`, a doubling
 * of the field's own step). Omitting it — or a non-positive one — means "the
 * finest thing the composite holds", which is what the field itself describes
 * when nobody has coarsened anything.
 */
function drawnLattice(c: WorldHeightTiles, cellM?: number
): { originX: number; originZ: number; step: number } | null {
  const fine = compositeLattice(c)
  if (!fine) return null
  const ov = c.overview && c.overview.step_m > 0 ? c.overview : null
  return {
    originX: ov ? ov.origin_x : fine.originX,
    originZ: ov ? ov.origin_z : fine.originZ,
    step: cellM && cellM > 0 ? cellM : fine.step,
  }
}

/**
 * Height of the DRAWN ground at (x, z) on the tiled field — the composite twin
 * of `sampleGroundHeight`, and for the very same reason (§ A16.3).
 *
 * A mesh is triangles. Over each cell of `cellM` the ground is the two planes
 * `sampleGroundHeight` describes, and a figure placed at the bilinear reading
 * instead sits off that surface by up to a quarter of the cell's twist — a
 * measured metre on a 5 m hill. So everything that TOUCHES the drawn ground
 * asks here, and only the mirror of the server's own rule (which judges the
 * field, not the mesh) asks `sampleCompositeHeight`.
 *
 * The four corners are read through the composite ladder, one by one. A cell
 * lying across the border of the loaded tiles therefore takes some corners from
 * a tile and some from the overview — which is not a mixture but exactly what
 * the plate does: its vertices were lifted by this same ladder, and the plane
 * between them IS the drawn ground there. That seam sits at the loading radius,
 * far outside the fog (`heightTiles.ts`).
 */
export function sampleCompositeGroundHeight(c: WorldHeightTiles | null | undefined,
                                            x: number, z: number,
                                            cellM?: number): number {
  if (!c) return 0
  const lat = drawnLattice(c, cellM)
  if (!lat) return 0
  const step = lat.step
  const i = Math.floor((x - lat.originX) / step)
  const j = Math.floor((z - lat.originZ) / step)
  const x0 = lat.originX + i * step
  const z0 = lat.originZ + j * step
  const tx = (x - x0) / step
  const tz = (z - z0) / step
  const h00 = sampleCompositeHeight(c, x0, z0)
  const h10 = sampleCompositeHeight(c, x0 + step, z0)
  const h01 = sampleCompositeHeight(c, x0, z0 + step)
  const h11 = sampleCompositeHeight(c, x0 + step, z0 + step)
  return tz <= tx
    ? h00 + tx * (h10 - h00) + tz * (h11 - h10)
    : h00 + tz * (h01 - h00) + tx * (h11 - h01)
}
