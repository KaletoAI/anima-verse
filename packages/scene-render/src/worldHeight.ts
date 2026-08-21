/**
 * The WORLD relief — the ONE height answer both renderers and every rule use
 * (§ A16, contract addendum "Ein Boden — E1"; plan-ein-boden.md § G1/G2).
 *
 * Not to be confused with `terrain.ts` next door: that one samples the relief
 * of a DETAIL SCENE, a 17 × 17 field over one location's reference square.
 * This one samples the open world — a grid of support points in world metres,
 * anchored at the world origin, delivered by `GET /play/heightfield`. A figure
 * walking cross-country stands on THIS field.
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
 * ONE ANSWER SINCE E2, and that is the whole point of this revision. Until
 * "Ein Boden" this file carried THREE readings of one landscape: the bilinear
 * field (`sampleWorldHeight`), a "drawn ground" that re-interpolated the field
 * along the triangles a renderer had cut it into (`sampleGroundHeight` /
 * `sampleCompositeGroundHeight`), and — through the cell size those two took —
 * whatever the mesh budget had coarsened the cells to. Measured on the live
 * world the drawn reading stood up to 2.433 m (p95 1.584 m) off the field the
 * server judges by, because the client drew 64 m cells while the server read a
 * 2 m lattice. The drawn readings are GONE: the terrain is rendered by a CDLOD
 * patch mesh whose vertices sample this very lattice (`client3d/src/scene/
 * terrainLod.ts`), so the surface the player sees and the number every rule
 * reads are the same function, and `heightAt` below is that function.
 *
 * THE FIELD ARRIVES TWICE (§ A16.3): a coarsenable overview for the distance,
 * and 256 m tiles in an always-fine step (the server's, 2 m today) for
 * everything the ground DECIDES. `sampleWorldHeight` reads ONE grid, overview
 * or tile alike; `heightAt` is the ladder over both.
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
 * What a tile says about ITSELF — the quadtree half of the payload (§ G2,
 * addendum § 4).
 *
 * `min`/`max` are the tile's height span, which is what a node needs for a
 * frustum box and for an occlusion test. `err[k]` is the largest VERTICAL
 * error in metres a renderer makes by drawing the tile on mip level
 * `mip_levels_m[k]` instead of on the base lattice — an exact bound, not a
 * sample (the difference of two bilinear fields is bilinear and takes its
 * extrema in the corners), which is what lets a screen-space error test be a
 * guarantee rather than a guess.
 */
export interface WorldHeightTileStats {
  min: number
  max: number
  err: number[]
}

/**
 * The bilinear mix of four cell corners — THE arithmetic of this file.
 *
 * It exists as its own function for one reason: the same four multiplications
 * run on the CPU (here), in Python (`heightfield.sample_height`) and in the
 * terrain VERTEX SHADER (`terrainLod.ts`, four `texelFetch` and this mix by
 * hand). Three copies of an expression are three chances to write `1 - tz`
 * where the other two write `tz`, and the whole "Ein Boden" contract is that
 * they answer the same number.
 *
 * `h00` is the corner at (i, j), `h10` at (i+1, j), `h01` at (i, j+1), `h11`
 * at (i+1, j+1); `tx`/`tz` are the fractions inside the cell.
 */
export function bilinear(h00: number, h10: number, h01: number, h11: number,
                         tx: number, tz: number): number {
  const north = h00 * (1 - tx) + h10 * tx
  const south = h01 * (1 - tx) + h11 * tx
  return north * (1 - tz) + south * tz
}

/**
 * Bilinear reading of ANY lattice, through a fetch callback.
 *
 * Grid fraction, then cell, then mix:
 *
 *   `fx = clamp((x − originX) / step, 0, cols − 1)`,
 *   `i = min(floor(fx), cols − 2)`, `tx = fx − i` (`fz`/`j`/`tz` likewise),
 *   then `bilinear` of the four corners.
 *
 * OUTSIDE THE GRID the border value applies, and that is exact rather than a
 * fallback: the server always rasters a ring of support points outside every
 * authored area, so the whole border is 0 and clamping there means "the flat
 * world".
 *
 * THE CALLBACK is what makes this one function serve three shapes: the payload
 * arrays (`sampleWorldHeight`), a packed `Float32Array` mip pyramid
 * (`terrainLod.ts`), and the GLSL mirror the smoke evaluates in TypeScript. A
 * lattice smaller than 2 × 2 carries no relief and answers 0.
 */
export function latticeSample(at: (i: number, j: number) => number,
                              cols: number, rows: number,
                              originX: number, originZ: number, step: number,
                              x: number, z: number): number {
  if (!(cols >= 2) || !(rows >= 2) || !(step > 0)) return 0
  const clamp = (v: number, hi: number) => (v < 0 ? 0 : v > hi ? hi : v)
  const fx = clamp((x - originX) / step, cols - 1)
  const fz = clamp((z - originZ) / step, rows - 1)
  const i = Math.min(Math.floor(fx), cols - 2)
  const j = Math.min(Math.floor(fz), rows - 2)
  return bilinear(at(i, j), at(i + 1, j), at(i, j + 1), at(i + 1, j + 1),
                  fx - i, fz - j)
}

/**
 * Height of the world ground at (x, z) in world metres — bilinear, ONE grid.
 *
 * THE SHAPE IS TAKEN FROM THE ARRAY, not from `rows`/`cols`: those two are a
 * description of the data and this function is on the walk path. A row shorter
 * than the rest must make a reader sample a slightly wrong height, never
 * throw. The server's twin reads the array the same way.
 */
export function sampleWorldHeight(field: WorldHeightField | null | undefined,
                                  x: number, z: number): number {
  if (!field) return 0
  const h = field.heights
  if (!h || h.length < 2) return 0
  const rows = h.length
  const cols = h[0]?.length || 0
  return latticeSample((i, j) => {
    const v = h[j]?.[i]
    return typeof v === 'number' && Number.isFinite(v) ? v : 0
  }, cols, rows, field.origin_x, field.origin_z, field.step_m, x, z)
}

/**
 * Lowest and highest support point of the field, in metres.
 *
 * What it is FOR: everything that has to start above the whole world — the
 * analytic click march below clips its ray to this slab, and the tile ray of
 * `scene/tiles.ts` starts above it.
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

/**
 * The TILED height field as a client holds it (§ A16.3) — the coarse overview,
 * whichever fine tiles have arrived, and what those tiles say about themselves.
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
 *
 * `stats` and `mipLevelsM` are the E1 addendum (§ G2) and are OPTIONAL because
 * nothing that stands on the ground needs them: they steer the RENDERER's
 * quadtree (which node at which level, and whether its error is worth another
 * split). A composite without them draws at the distance rule alone.
 */
export interface WorldHeightTiles {
  tileM: number
  overview: WorldHeightField | null
  tiles: Map<string, WorldHeightField>
  stats?: Map<string, WorldHeightTileStats>
  mipLevelsM?: number[]
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
 * THE height of the world ground at (x, z) — the one answer, for everything.
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
 * AND THE TWO SOURCES ARE NEVER MIXED for one point. A tile and a coarsened
 * overview are not two accuracies of one number: at 32 m fifteen of sixteen
 * support points per axis are gone, so a 22 m hill has none left and simply
 * does not exist in the overview. Averaging or blending them would invent
 * ground that neither raster claims. A loaded tile therefore answers ALONE,
 * including where it has no support point for the question:
 * `sampleWorldHeight` clamps to the tile's border, and that clamp is the
 * tile's statement, not a gap the overview may fill.
 *
 * SINCE E1 THE TWO AGREE WHERE THEY OVERLAP anyway — the server's height is
 * one pure function of (x, z) sampled on two lattices, and no step of the bake
 * measures in raster cells any more (addendum § 1). What is left of the
 * difference is resolution, which is what the LOD morph is for and no longer a
 * data change under the player's feet.
 */
export function heightAt(c: WorldHeightTiles | null | undefined,
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
 * The FINEST lattice step the composite holds, in metres — 0 without any.
 *
 * A loaded tile decides it whenever there is one; without any tile the
 * overview's own grid is the finest thing there is. WHICH tile we take is
 * irrelevant: all tile origins are congruent modulo the step, so they all
 * describe the same lattice.
 *
 * TWO SERVER GUARANTEES CARRY THAT. First, `tile_m` is a multiple of the fine
 * step (256 / 2), so every tile origin lies on the fine grid. Second, the
 * OVERVIEW's origin lies on it as well: `heightfield._axis_origin` snaps it to
 * a multiple of the overview's own step, and `_step_for` only ever DOUBLES the
 * fine step — so overview lines are a subset of tile lines, never an offset
 * raster.
 */
export function finestStep(c: WorldHeightTiles | null | undefined): number {
  if (!c) return 0
  let best = 0
  for (const tile of c.tiles?.values() ?? []) {
    if (tile && tile.step_m > 0 && (best === 0 || tile.step_m < best)) best = tile.step_m
  }
  if (best > 0) return best
  const ov = c.overview
  return ov && ov.step_m > 0 ? ov.step_m : 0
}

/** How many march steps `rayGroundHit` may take before it gives up. A click
 *  ray over a 2 km world at a 2 m lattice is 1 000 steps when it runs flat
 *  along the ground; past this the step is stretched instead, which costs
 *  accuracy on a ray nobody can aim that precisely anyway. */
const MAX_MARCH_STEPS = 4096
/** Bisection rounds after the sign change. 40 halvings of a metre-sized
 *  bracket land far below the millimetre the picture is drawn in. */
const BISECT_ROUNDS = 40

/** What `rayGroundHit` needs to know besides the ray. */
export interface RayGroundOpts {
  /** The height slab the world lies in — `worldHeightRange` widened by
   *  whatever the caller adds on top of the field. The march is clipped to it,
   *  which is what keeps a ray fired at the sky from walking 4 000 samples
   *  before admitting it missed. */
  minY: number
  maxY: number
  /** How far along the ray to look, metres. Default 4 000 — past the far
   *  plane of any view this client draws. */
  maxDistM?: number
  /** Horizontal advance per march step, metres. Defaults to the composite's
   *  finest lattice step, which is the resolution the ground is defined at. */
  stepM?: number
}

/**
 * Where a ray meets the ground — ANALYTIC, against the field itself.
 *
 * WHY IT IS NOT A RAYCAST ANY MORE. Click-to-walk used to intersect the ray
 * with the one big drawn base mesh, which meant the goal was read off whatever
 * triangles the mesh budget had left — 64 m cells in the live world, up to
 * 2.433 m off the field the server judges the walk by. The ground is now a
 * CDLOD mesh whose triangles change with the camera, so a raycast would give a
 * different goal at a different zoom for the same pixel. So the ray is solved
 * against the DATA: march `f(t) = ray.y(t) − heightAt(ray.xz(t))` until it
 * changes sign, then bisect.
 *
 * THE STEP is one lattice cell of horizontal advance, so no cell is skipped.
 * The honest limit: inside a cell the field along a slanted line is quadratic
 * and can carry one interior extremum, so a ray that grazes a single 2 m bump
 * and comes back out can be missed. That is a pixel-wide aiming case on a
 * click, and the alternative — a half-step march — doubles the cost of every
 * click for it.
 *
 * A RAY THAT STARTS BELOW THE GROUND hits at once (`t0`), which is the honest
 * answer for a camera that has dipped into a hill: the player clicked, and the
 * ground under the click is right there.
 *
 * Answers `null` for a miss — a ray into the sky, a ray parallel to and above
 * the world, a composite with no field at all.
 */
export function rayGroundHit(c: WorldHeightTiles | null | undefined,
                             ox: number, oy: number, oz: number,
                             dx: number, dy: number, dz: number,
                             opts: RayGroundOpts
): { x: number; y: number; z: number } | null {
  if (!c) return null
  const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
  if (!(len > 0) || !Number.isFinite(len)) return null
  const ux = dx / len
  const uy = dy / len
  const uz = dz / len
  const maxDist = opts.maxDistM && opts.maxDistM > 0 ? opts.maxDistM : 4000
  // The slab, widened by a metre so a ray aimed exactly at the highest support
  // point still gets a bracket to bisect in.
  const loY = Math.min(opts.minY, opts.maxY) - 1
  const hiY = Math.max(opts.minY, opts.maxY) + 1
  let t0 = 0
  let t1 = maxDist
  if (Math.abs(uy) > 1e-9) {
    const tA = (loY - oy) / uy
    const tB = (hiY - oy) / uy
    t0 = Math.max(0, Math.min(tA, tB))
    t1 = Math.min(maxDist, Math.max(tA, tB))
  } else if (oy < loY || oy > hiY) {
    return null   // running flat, above or below the whole world
  }
  if (!(t1 > t0)) return null
  const f = (t: number): number =>
    (oy + t * uy) - heightAt(c, ox + t * ux, oz + t * uz)
  if (f(t0) <= 0) {
    return { x: ox + t0 * ux, y: oy + t0 * uy, z: oz + t0 * uz }
  }
  const lattice = opts.stepM && opts.stepM > 0 ? opts.stepM : finestStep(c)
  const hs = Math.sqrt(ux * ux + uz * uz)
  let dt = lattice > 0 && hs > 1e-9 ? lattice / hs : (t1 - t0)
  if (!(dt > 0)) dt = t1 - t0
  if ((t1 - t0) / dt > MAX_MARCH_STEPS) dt = (t1 - t0) / MAX_MARCH_STEPS
  let ta = t0
  for (let tb = t0 + dt; ; tb += dt) {
    if (tb > t1) tb = t1
    const fb = f(tb)
    if (fb <= 0) {
      // Bracketed: [ta, tb] holds the crossing. Bisect on the sign of `f`.
      let lo = ta
      let hi = tb
      for (let k = 0; k < BISECT_ROUNDS; k += 1) {
        const mid = (lo + hi) / 2
        if (f(mid) > 0) lo = mid
        else hi = mid
      }
      return { x: ox + hi * ux, y: oy + hi * uy, z: oz + hi * uz }
    }
    ta = tb
    if (tb >= t1) break
  }
  return null
}
