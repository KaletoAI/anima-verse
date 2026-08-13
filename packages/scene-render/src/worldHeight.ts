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
