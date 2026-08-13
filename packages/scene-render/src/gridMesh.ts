/**
 * Ground geometry ON A GRID — the mesh side of the world relief (§ A16).
 *
 * A flat world needs two triangles for its ground. A world with a relief needs
 * a vertex wherever the height changes, and the world's height changes at the
 * support points of the heightfield — so both pieces of the seamless ground
 * are cut on THAT grid: the base plate (`gridPlate`) is built on it, and every
 * painted area (`subdivideOnGrid`) is cut along the same lines. The caller
 * then lifts every vertex by `sampleWorldHeight` at its own world x/z.
 *
 * WHY NOT `drapeGeometry` (terrain.ts). That one halves every triangle until
 * its longest edge is short enough — five times at most (`MAX_SPLITS`), which
 * is plenty for a plate over one location's reference square and nowhere near
 * enough for a plate over a kilometre of world: 1 490 m of diagonal split five
 * times is still 66 m per edge. And its splits land wherever the triangle
 * happens to be, so the base plate and a meadow lying on it would sample the
 * field at DIFFERENT points and drift apart between them.
 *
 * ONE GRID FOR EVERYTHING is what keeps the ground watertight. The lines are
 * anchored at the field's own origin, so plate and areas share every vertex
 * that falls on a grid line, and a full interior cell comes out as the very
 * same two triangles on both (see `fanTriangles`: the split runs from the
 * cell's minimum corner to its maximum one, on the plate as in an area).
 * What remains are the cells an area's OUTLINE crosses — there the two
 * surfaces are cut differently and can differ inside the cell by a fraction of
 * the cell's own curvature. That is what the hairline lift of the painted
 * areas (`AREA_Y_STEP_M`, ground.ts) is for; a relief authored with a falloff
 * shorter than one cell can still show the plate through an area edge, and the
 * cure for that is a falloff of at least one cell, not a taller ladder.
 *
 * PURE ARITHMETIC, no imports at all — not even a type-only one. That is what
 * lets `client3d/scripts/smoke_relief_math.mjs` transpile this file and check
 * the numbers by hand (§ B5a), and it is the same discipline `worldHeight.ts`
 * and `groundAreas.ts`'s ring maths follow.
 */

/** Flat vertex arrays as three.js wants them: `pos` is `[x, y, z, …]`, `uv` is
 *  `[u, v, …]`, and `index` (when present) three entries per triangle. */
export interface GridGeometry {
  pos: number[]
  uv: number[]
  /** present on the plate (a regular grid indexes well), absent on a
   *  subdivided area (its triangles share nothing worth an index) */
  index?: number[]
}

/** The plate, plus what the caller needs to know about the grid it got. */
export interface PlateGeometry extends GridGeometry {
  index: number[]
  /** the extent actually covered — snapped OUTWARD onto the grid */
  minX: number
  minZ: number
  maxX: number
  maxZ: number
  /** cell size the plate was built at (the possibly doubled step) */
  step: number
  /** support points per axis (cells + 1) */
  cols: number
  rows: number
}

/**
 * How many cells the ground may be cut into, per mesh.
 *
 * Derived from the payload numbers of § A16, not invented: the heightfield's
 * budget is 120 000 support points, so the largest field that can arrive is
 * 346 × 346 points = 1 380 m of world at the 4 m default step. The base plate
 * covers that plus the ground margin on both sides (2 × 60 m,
 * `BASE_MARGIN_M`), i.e. about 1 500 m, which at 4 m cells would be 375 × 375
 * = 140 000 cells — 280 000 triangles for one mesh, and every painted area on
 * top of it free to ask for as many again.
 *
 * 40 000 cells (200 × 200 on a square world, 80 000 triangles) is the ceiling
 * instead, and `gridStepFor` DOUBLES the step until a mesh fits under it. So:
 * a world up to about 800 m keeps the field's native 4 m cells, the largest
 * world the payload can describe drapes at 8 m (187 × 187 = 35 000 cells), and
 * nothing anyone can author melts the client. Doubling — never an arbitrary
 * factor — is what keeps the coarser grid a SUBSET of the field's own lines,
 * exactly as the server coarsens the field itself (§ A16).
 */
export const GRID_MAX_CELLS = 40_000

/** Hard ceiling on grid lines per axis inside one triangle of
 *  `subdivideOnGrid`. The caller's step already sizes the whole geometry
 *  (`gridStepFor`), so this can only be reached by a geometry whose bounding
 *  box lies about the triangles in it — a guard, not a working limit. */
const MAX_LINES_PER_AXIS = 2048

/** Triangles smaller than this in square metres are dropped: clipping a
 *  polygon at a line that grazes a corner leaves slivers, and a zero-area
 *  triangle is three vertices for no pixels. */
const TRI_EPS_M2 = 1e-9

/**
 * The cell size a mesh over `[minX…maxX] × [minZ…maxZ]` is cut at: the field's
 * `step`, doubled until the mesh stays under `maxCells` cells.
 *
 * Doubling keeps the lines anchored at the same origin — every line of the
 * coarser grid is a line of the finer one — which is what lets a plate cut at
 * 8 m and an area cut at 8 m meet exactly. (The caller passes ONE step for the
 * whole ground for that very reason: a plate at 8 m under an area at 4 m would
 * have the area sampling the field where the plate only interpolates.)
 *
 * A non-positive step, or an extent that is not finite, answers with the step
 * unchanged — the caller draws a flat world then and never asks for cells.
 */
export function gridStepFor(minX: number, minZ: number, maxX: number, maxZ: number,
                            step: number, maxCells = GRID_MAX_CELLS): number {
  const w = maxX - minX
  const d = maxZ - minZ
  if (!(step > 0) || !Number.isFinite(w) || !Number.isFinite(d)) return step
  const limit = maxCells > 0 ? maxCells : GRID_MAX_CELLS
  let out = step
  // Cells, not points: `ceil` on both axes is what the plate really builds.
  for (let guard = 0; guard < 32; guard += 1) {
    const cols = Math.max(1, Math.ceil(w / out))
    const rows = Math.max(1, Math.ceil(d / out))
    if (cols * rows <= limit) return out
    out *= 2
  }
  return out
}

/** Grid coordinate of `v` rounded down / up onto the line grid anchored at
 *  `origin` with spacing `step`. */
function snapDown(v: number, origin: number, step: number): number {
  return origin + Math.floor((v - origin) / step) * step
}
function snapUp(v: number, origin: number, step: number): number {
  return origin + Math.ceil((v - origin) / step) * step
}

/**
 * The base plate as a grid of cells over the world, y = 0 everywhere.
 *
 * The requested extent is snapped OUTWARD onto the grid (`origin + k · step`),
 * so the plate's own vertex lines ARE the field's support lines and every cell
 * is one cell of the field. The snap grows the plate by less than one cell per
 * side; it never shrinks it, because the plate is what keeps a player from
 * walking off the visible world.
 *
 * UVs run 0…1 over the whole plate, exactly as `THREE.PlaneGeometry` lays them
 * out after `rotateX(-90°)`: `u` grows with world x, `v` is 1 at the minimum z
 * edge. The material scales them by metres itself (`ground.ts`).
 *
 * Every cell is split from its MINIMUM corner to its maximum one — the same
 * diagonal `fanTriangles` gives a full cell of a painted area, which is what
 * makes plate and area agree inside a cell and not just on its edges.
 *
 * A step of 0 or a degenerate extent gives the single quad of the flat world.
 */
export function gridPlate(minX: number, minZ: number, maxX: number, maxZ: number,
                          step: number, originX = 0, originZ = 0): PlateGeometry {
  const flat = !(step > 0) || !(maxX > minX) || !(maxZ > minZ)
  const x0 = flat ? minX : snapDown(minX, originX, step)
  const x1 = flat ? maxX : snapUp(maxX, originX, step)
  const z0 = flat ? minZ : snapDown(minZ, originZ, step)
  const z1 = flat ? maxZ : snapUp(maxZ, originZ, step)
  const cols = flat ? 1 : Math.max(1, Math.round((x1 - x0) / step))
  const rows = flat ? 1 : Math.max(1, Math.round((z1 - z0) / step))
  const w = x1 - x0
  const d = z1 - z0
  const pos: number[] = []
  const uv: number[] = []
  const index: number[] = []
  for (let j = 0; j <= rows; j += 1) {
    const z = j === rows ? z1 : z0 + (d * j) / rows
    for (let i = 0; i <= cols; i += 1) {
      const x = i === cols ? x1 : x0 + (w * i) / cols
      pos.push(x, 0, z)
      uv.push(w > 0 ? (x - x0) / w : 0, d > 0 ? (z1 - z) / d : 0)
    }
  }
  const at = (i: number, j: number) => j * (cols + 1) + i
  for (let j = 0; j < rows; j += 1) {
    for (let i = 0; i < cols; i += 1) {
      const a = at(i, j)          // minimum corner (min x, min z)
      const b = at(i + 1, j)
      const c = at(i + 1, j + 1)  // maximum corner
      const e = at(i, j + 1)
      // Wound so the face normal points UP after the caller leaves y = 0
      // alone: in world XZ with +y towards the viewer, (a, e, c) turns
      // counter-clockwise seen from above.
      index.push(a, e, c, a, c, b)
    }
  }
  return { pos, uv, index, minX: x0, minZ: z0, maxX: x1, maxZ: z1,
           step: flat ? 0 : step, cols: cols + 1, rows: rows + 1 }
}

/** One vertex while it is being cut: world position plus its UV. */
interface Vert { x: number; y: number; z: number; u: number; v: number }

function lerpVert(a: Vert, b: Vert, t: number): Vert {
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
    z: a.z + (b.z - a.z) * t,
    u: a.u + (b.u - a.u) * t,
    v: a.v + (b.v - a.v) * t,
  }
}

/**
 * Cut a convex polygon at the axis-aligned line `axis = c` — `axis` 0 is x, 1
 * is z. Answers `[low, high]`, the part on the ≤ side and the part on the ≥
 * side; either may be empty when the polygon lies wholly on one side.
 *
 * Sutherland–Hodgman, run for both half-planes in one pass. Vertices exactly
 * ON the line go into BOTH parts and no crossing point is computed for them,
 * which is what keeps the seam watertight: the two parts then share the very
 * same numbers, not two roundings of one intersection.
 */
function splitAt(poly: Vert[], axis: 0 | 1, c: number): [Vert[], Vert[]] {
  const low: Vert[] = []
  const high: Vert[] = []
  const key = axis === 0 ? 'x' : 'z'
  const n = poly.length
  for (let i = 0; i < n; i += 1) {
    const a = poly[i]
    const b = poly[(i + 1) % n]
    const da = (a[key] as number) - c
    const db = (b[key] as number) - c
    if (da <= 0) low.push(a)
    if (da >= 0) high.push(a)
    // Strict sign change only: an endpoint on the line is already in both.
    if ((da < 0 && db > 0) || (da > 0 && db < 0)) {
      const t = da / (da - db)
      const m = lerpVert(a, b, t)
      // Pin the coordinate the cut is about, so both sides read the identical
      // number instead of two roundings of one division.
      if (axis === 0) m.x = c
      else m.z = c
      low.push(m)
      high.push(m)
    }
  }
  return [low.length >= 3 ? low : [], high.length >= 3 ? high : []]
}

/** Twice the XZ area of a triangle — the sliver test of `fanTriangles`. */
function area2(a: Vert, b: Vert, c: Vert): number {
  return Math.abs((b.x - a.x) * (c.z - a.z) - (c.x - a.x) * (b.z - a.z))
}

/**
 * Fan a convex polygon into triangles, starting at its MINIMUM corner (lowest
 * x, then lowest z).
 *
 * Starting there is the whole trick: a full grid cell is a rectangle whichever
 * way it was cut out, and a fan from its minimum corner always splits it along
 * the minimum-to-maximum diagonal — the same one `gridPlate` uses. Plate and
 * painted area therefore describe the SAME surface over every full cell, and
 * neither can poke through the other there.
 */
function fanTriangles(poly: Vert[], pos: number[], uv: number[]): void {
  if (poly.length < 3) return
  let start = 0
  for (let i = 1; i < poly.length; i += 1) {
    const p = poly[i]
    const q = poly[start]
    if (p.x < q.x || (p.x === q.x && p.z < q.z)) start = i
  }
  const n = poly.length
  const a = poly[start]
  for (let k = 1; k < n - 1; k += 1) {
    const b = poly[(start + k) % n]
    const c = poly[(start + k + 1) % n]
    if (area2(a, b, c) < 2 * TRI_EPS_M2) continue
    pos.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z)
    uv.push(a.u, a.v, b.u, b.v, c.u, c.v)
  }
}

/** The grid lines strictly between `lo` and `hi`, anchored at `origin`. */
function linesBetween(lo: number, hi: number, origin: number, step: number): number[] {
  const out: number[] = []
  const first = Math.floor((lo - origin) / step) + 1
  const last = Math.ceil((hi - origin) / step) - 1
  if (last - first + 1 > MAX_LINES_PER_AXIS) return out
  for (let k = first; k <= last; k += 1) {
    const c = origin + k * step
    if (c > lo && c < hi) out.push(c)
  }
  return out
}

/**
 * Cut a flat triangle soup along the grid — the painted-area half of the
 * draping (§ A16).
 *
 * `pos`/`uv` are a NON-INDEXED triangle list as `buildAreaGeometry` produces
 * it (three vertices per triangle, y = 0, UVs in world metres). Every triangle
 * is clipped at the grid lines of `step` anchored at `(originX, originZ)`,
 * first along x, then along z, and each piece is fanned from its minimum
 * corner. Positions and UVs are interpolated linearly, which is EXACT here:
 * a shape geometry's UV is an affine function of its position, so world metres
 * stay world metres however often the triangle is cut.
 *
 * The input is untouched; the answer is a fresh pair of arrays with y still 0
 * — lifting the vertices onto the field is the caller's step, and it is what
 * turns this grid into a draped ground.
 */
export function subdivideOnGrid(pos: readonly number[], uv: readonly number[] | null,
                                step: number, originX = 0, originZ = 0): GridGeometry {
  const outP: number[] = []
  const outU: number[] = []
  if (!(step > 0)) {
    return { pos: [...pos], uv: uv ? [...uv] : [] }
  }
  for (let t = 0, k = 0; t + 8 < pos.length; t += 9, k += 6) {
    const tri: Vert[] = [0, 1, 2].map((n) => ({
      x: pos[t + n * 3], y: pos[t + n * 3 + 1], z: pos[t + n * 3 + 2],
      u: uv ? uv[k + n * 2] : 0, v: uv ? uv[k + n * 2 + 1] : 0,
    }))
    let minX = Infinity; let maxX = -Infinity
    let minZ = Infinity; let maxZ = -Infinity
    for (const p of tri) {
      if (p.x < minX) minX = p.x
      if (p.x > maxX) maxX = p.x
      if (p.z < minZ) minZ = p.z
      if (p.z > maxZ) maxZ = p.z
    }
    if (!Number.isFinite(minX) || !Number.isFinite(minZ)) continue
    // Columns first: cut off everything left of each line and carry the rest
    // forward, so each piece belongs to exactly one column.
    let rest: Vert[] = tri
    const columns: Vert[][] = []
    for (const c of linesBetween(minX, maxX, originX, step)) {
      const [low, high] = splitAt(rest, 0, c)
      if (low.length) columns.push(low)
      if (!high.length) { rest = []; break }
      rest = high
    }
    if (rest.length) columns.push(rest)
    for (const column of columns) {
      let cz = Infinity; let cZ = -Infinity
      for (const p of column) {
        if (p.z < cz) cz = p.z
        if (p.z > cZ) cZ = p.z
      }
      let tail: Vert[] = column
      for (const c of linesBetween(cz, cZ, originZ, step)) {
        const [low, high] = splitAt(tail, 1, c)
        if (low.length) fanTriangles(low, outP, outU)
        if (!high.length) { tail = []; break }
        tail = high
      }
      if (tail.length) fanTriangles(tail, outP, outU)
    }
  }
  return { pos: outP, uv: outU }
}
