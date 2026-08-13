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
 * large rectangle can hang a little low. Since the veil is tiled (`fogRects`,
 * ~64 m per quad) no rectangle of a 4 m world grid comes close to that; the
 * stride is the guard for a coarsened grid over a huge world, not the working
 * case.
 */
export function maxWorldHeightIn(field: WorldHeightField | null | undefined,
                                 x0: number, z0: number,
                                 x1: number, z1: number,
                                 cellM?: number): number {
  if (!field) return 0
  const step = cellM && cellM > 0 ? cellM : field.step_m
  const xs = rectLines(Math.min(x0, x1), Math.max(x0, x1), field.origin_x, step)
  const zs = rectLines(Math.min(z0, z1), Math.max(z0, z1), field.origin_z, step)
  let max = -Infinity
  for (const z of zs) {
    for (const x of xs) {
      const h = sampleGroundHeight(field, x, z, step)
      if (h > max) max = h
    }
  }
  return Number.isFinite(max) ? max : 0
}
