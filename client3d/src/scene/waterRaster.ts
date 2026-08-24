/**
 * THE WORLD'S WATER AS A FIELD — the client half of the water raster
 * (Wasser v2, K-A E1/E2; `recherche-wasser-v2.md` § 4 K-A, § 6).
 *
 * Until this stage the mirror of a water area was a MESH: the client took the
 * authored polygon, cut it at the axis knots, triangulated the pieces and
 * lifted every vertex onto `waterLevelAt`. That is the surface being BUILT.
 * Under K-A it is SAMPLED instead: the server bakes the mirror into the height
 * tiles as a second field, exactly as it bakes the ground, and this file is
 * how a client reads it.
 *
 * WHAT IT IS NOT. `waterPlaneMath.waterLevelAt` — the exact profile function —
 * stays where it is and stays what the GAMEPLAY reads (`floatRootY`, wading and
 * swimming): there the mirror has to be exact, not rastered. This is the
 * RENDER field, and the two answer the same number wherever the raster has a
 * support point, by construction: the server's `HeightModel.water_at` IS
 * `water_level_at` evaluated on the lattice.
 *
 * NO THREE, NO FETCHING, NO STATE — pure arithmetic over the wire shape, which
 * is what lets `client3d/scripts/smoke_world_height.mjs` derive its numbers by
 * hand instead of observing them from a running client.
 *
 * ── THE DRY SENTINEL ────────────────────────────────────────────────────────
 * A support point without water carries `null` on the wire and NaN here. NaN
 * and not 0 or -Infinity: a water level is an ordinary world y and every finite
 * number is a legal one, so "no water" needs a value that cannot be mistaken
 * for one — and NaN survives the Float32Array of a data texture, where the
 * shader will read it back with the same test (K-A E3).
 */
import { tileKeyAt } from '@anima/scene-render';

/**
 * One tile's water field, merged with the tile geometry it rides on.
 *
 * The wire ships `level`/`flow_x`/`flow_z` inside the tile and nothing else:
 * the lattice is the HEIGHT tile's, so the origin, the step and the size are
 * copied over when the batch is taken (`scene/ground.ts`). A field of its own
 * geometry would be a second answer to "where are the support points".
 *
 * `flow` is null for a still water — the server omits both components where
 * the whole tile has no flow, and that absence reads as "(0, 0) everywhere".
 */
export interface WaterTileField {
  originX: number;
  originZ: number;
  step: number;
  /** `level[j][i]` in metres, NaN where the point carries no water. */
  level: number[][];
  flowX: number[][] | null;
  flowZ: number[][] | null;
}

/** The water field as a client holds it — the twin of `WorldHeightTiles`, and
 *  deliberately a map of its own rather than a member of it: a tile may exist
 *  without water, and every reader here asks a different question from every
 *  reader there. `tileM` is the payload's, never a constant. */
export interface WaterRaster {
  tileM: number;
  tiles: Map<string, WaterTileField>;
}

/** An empty raster — the world before a tile has arrived, and a world without a
 *  drop of water. Both read as "dry everywhere", which is the correct answer
 *  for both. */
export function emptyWaterRaster(): WaterRaster {
  return { tileM: 0, tiles: new Map() };
}

/** The wire's `null` as this module's NaN, and anything unreadable with it. */
function cell(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : NaN;
}

/**
 * ONE tile's water field out of the wire shape, on the tile's own lattice.
 *
 * `level` is copied cell by cell so the sentinel is converted ONCE, at the
 * boundary: every reader below then works on plain numbers and NaN, and
 * nothing downstream has to remember that `null` was ever a thing.
 */
export function waterTileFrom(originX: number, originZ: number, step: number,
                              wire: { level?: (number | null)[][];
                                      flow_x?: number[][];
                                      flow_z?: number[][] } | null | undefined
): WaterTileField | null {
  const rows = wire?.level;
  if (!rows || rows.length < 2 || !(step > 0)) return null;
  return {
    originX,
    originZ,
    step,
    level: rows.map((row) => (row ?? []).map(cell)),
    flowX: wire?.flow_x ? wire.flow_x.map((row) => (row ?? []).map(cell)) : null,
    flowZ: wire?.flow_z ? wire.flow_z.map((row) => (row ?? []).map(cell)) : null,
  };
}

/**
 * THE MASKED BILINEAR MIX — the one piece of arithmetic that is not the height
 * field's, and the reason it is spelled out here.
 *
 * A corner with weight 0 is NOT read. Plain floating point would propagate its
 * NaN through `NaN · 0 = NaN`, and that is not a rounding detail: a sample
 * sitting exactly ON a lattice line has `tx = 0`, so it would be dragged to NaN
 * by the dry texel one step away — the dilation ring would be eroded by a full
 * texel at every lattice line, and every water would read dry along a grid of
 * lines through its own surface.
 *
 * With the rule as written the answer is NaN exactly when a corner that really
 * CONTRIBUTES is dry, which is the statement the server's dilation is built
 * against: a corner of a wet sample's cell lies at most one cell diagonal
 * (sqrt(2) steps) outside the outline and the raster is written two steps out,
 * so **every point inside a water polygon reads four wet corners on the base
 * lattice**. A NaN answer therefore means dry ground, never a gap in the data.
 */
export function waterBilinear(h00: number, h10: number, h01: number,
                              h11: number, tx: number, tz: number): number {
  const w00 = (1 - tx) * (1 - tz);
  const w10 = tx * (1 - tz);
  const w01 = (1 - tx) * tz;
  const w11 = tx * tz;
  let sum = 0;
  if (w00 !== 0) sum += h00 * w00;
  if (w10 !== 0) sum += h10 * w10;
  if (w01 !== 0) sum += h01 * w01;
  if (w11 !== 0) sum += h11 * w11;
  return sum;
}

/** Grid fraction, cell and the two fractions — the `latticeSample` rule of
 *  `@anima/scene-render`, reimplemented here only because the mix above is not
 *  that module's. Same clamps, same `min(floor(f), n − 2)`, so the water field
 *  and the height field of one tile address the very same cell. */
function cellAt(f: number, n: number): [number, number] {
  const clamped = f < 0 ? 0 : f > n - 1 ? n - 1 : f;
  const i = Math.min(Math.floor(clamped), n - 2);
  return [i, clamped - i];
}

/** One tile's water level at (x, z) — bilinear, NaN where dry. */
export function sampleWaterTile(field: WaterTileField | null | undefined,
                                x: number, z: number): number {
  const rows = field?.level;
  if (!field || !rows || rows.length < 2) return NaN;
  const cols = rows[0]?.length ?? 0;
  if (cols < 2) return NaN;
  const [i, tx] = cellAt((x - field.originX) / field.step, cols);
  const [j, tz] = cellAt((z - field.originZ) / field.step, rows.length);
  const at = (a: number, b: number): number => cell(rows[b]?.[a]);
  return waterBilinear(at(i, j), at(i + 1, j), at(i, j + 1), at(i + 1, j + 1),
                       tx, tz);
}

/**
 * THE WATER LEVEL AT (x, z) — the store's ladder, and the twin of `heightAt`.
 *
 *   the tile containing the point, if its water field is loaded → bilinear
 *   else                                                        → NaN (dry)
 *
 * There is no overview rung, and there cannot be one: the overview grid carries
 * no water at all. A point in an unloaded tile is therefore "no water known
 * here", which is exactly what a renderer must draw — a mirror invented from a
 * coarse raster would be a surface no lattice of the model describes.
 */
export function rasterLevelAt(raster: WaterRaster | null | undefined,
                              x: number, z: number): number {
  if (!raster) return NaN;
  return sampleWaterTile(raster.tiles?.get(tileKeyAt(raster.tileM, x, z)),
                         x, z);
}

/**
 * THE FLOW VECTOR AT (x, z) — the same ladder, and (0, 0) wherever there is
 * none.
 *
 * A tile whose water is still ships no flow arrays at all, and a point outside
 * every loaded tile has no flow either; both answer (0, 0), which is what
 * "still" already means to a ripple. The components are mixed with the SAME
 * masked bilinear the level uses, so the flow of a shore texel is not dragged
 * to NaN by a dry neighbour that carries no weight — and a NaN that did get
 * through is answered as (0, 0) rather than handed on, because a NaN direction
 * would poison a ripple where a still one is merely wrong.
 */
export function rasterFlowAt(raster: WaterRaster | null | undefined,
                             x: number, z: number): [number, number] {
  const field = raster?.tiles?.get(tileKeyAt(raster.tileM, x, z));
  if (!field || !field.flowX || !field.flowZ) return [0, 0];
  const rows = field.flowX.length;
  const cols = field.flowX[0]?.length ?? 0;
  if (rows < 2 || cols < 2) return [0, 0];
  const [i, tx] = cellAt((x - field.originX) / field.step, cols);
  const [j, tz] = cellAt((z - field.originZ) / field.step, rows);
  const mix = (grid: number[][]): number => waterBilinear(
    cell(grid[j]?.[i]), cell(grid[j]?.[i + 1]),
    cell(grid[j + 1]?.[i]), cell(grid[j + 1]?.[i + 1]), tx, tz);
  const fx = mix(field.flowX);
  const fz = mix(field.flowZ);
  return Number.isFinite(fx) && Number.isFinite(fz) ? [fx, fz] : [0, 0];
}
