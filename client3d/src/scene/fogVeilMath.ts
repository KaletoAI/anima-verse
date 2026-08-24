/**
 * THE ARITHMETIC OF THE VEIL — where a cell lies, how soft its edge is, and
 * how much haze the camera's height is worth.
 *
 * Pure, no imports, no `three`, no module state — the shape of
 * `naturalGroundMath.ts` and `waterPlaneMath.ts`, and for the same reason:
 * every number the GPU spends is derived here and hand-checked in
 * `client3d/scripts/smoke_fog_veil.mjs` (§ B5a — numbers, never screenshots).
 *
 * ── THE RASTER IS THE SERVER'S ──────────────────────────────────────────────
 * The unit is the 64 m cell of `app/core/exploration.py` (`EXPLORED_CELL_M`),
 * anchored at the WORLD ORIGIN: cell (cx, cz) covers [cx·64, (cx+1)·64) on x
 * and the same on z, `cx = floor(x / 64)`. Not a number of this client's own —
 * `GET /play/explored` hands over exactly those cell indices as `"cx,cz"`
 * keys, and a renderer that re-cut them at its own edge length would draw a
 * veil the server does not mean. :func:`fogCellOf` is the twin of the
 * server's `cell_of`, floor division included, so a world that reaches across
 * the origin has one continuous raster instead of a double-width cell at 0.
 *
 * ── WHY A DATA TEXTURE, AND WHERE THE SOFT EDGE COMES FROM ─────────────────
 * The explored set reaches the shader as ONE texture with one texel per cell:
 * 1 where the avatar has been, 0 where it has not. Sampled LINEARLY, and that
 * single choice IS the soft edge the plan asks for — no blur pass, no second
 * texture, no per-cell geometry:
 *
 *   texel centres sit on CELL CENTRES (`fogTexUv`), so between the centre of
 *   an explored cell (1) and the centre of its unexplored neighbour (0) the
 *   sampled value falls linearly over the 64 m between them. It passes 0.5
 *   exactly on the shared cell BOUNDARY, which means the transition reaches
 *   FOG_BLEND_M = 32 m — half a cell — into each of the two. That is the
 *   plan's "~32 m blend, no hard raster", and it costs one texture fetch.
 *
 * The grid is the bounding box of the explored cells GROWN BY ONE CELL on
 * every side (`FOG_PAD_CELLS`). The ring matters: the texture is sampled with
 * clamp-to-edge, so without a border of zeros an explored cell at the edge of
 * the box would smear its 1 across the whole world outside the box, and the
 * veil would end at the memory's bounding box instead of at its cells.
 *
 * ── THE HEIGHT RAMP ────────────────────────────────────────────────────────
 * The veil is an OVERVIEW effect: near the ground one sees what is around one,
 * from high up one sees only what one has walked. So the opacity is a pure
 * function of how high the camera stands above the point it looks at, and the
 * two ends are taken from the zoom tiers this client already has (`main.ts`):
 *
 *   - the embodied zoom wall, camera distance 34 m (EMBODY_MAX_DIST). At the
 *     pitch the engine gives that distance (38.8°) the camera stands
 *     34 · sin(38.8°) = 21.3 m above its target -> FOG_CLEAR_H_M = 20, the
 *     height at which the veil is exactly gone. Everything the embodied mode
 *     can reach is therefore veil-free, which is the rule "no veil in the
 *     close mode" without a mode flag reaching this file.
 *   - the distance at which the open detail view closes, 60 m
 *     (CLOSE_CAM_DIST) — "you have left the place, this is the overview".
 *     Pitch there is 45.7°, so 60 · sin(45.7°) = 42.9 m above the target
 *     -> FOG_FULL_H_M = 45, where the haze reaches its full strength.
 *
 * Between the two the ramp is a smoothstep, not a line: a linear ramp has a
 * corner at both ends, and a corner in an opacity that follows a wheel is
 * visible as a jolt while the wheel turns at constant speed.
 */

/** Edge length of one exploration cell in world metres — the server's
 *  `EXPLORED_CELL_M`, mirrored. Changing it here alone draws a veil at the
 *  wrong scale; it is one number in two places by contract (§ A12). */
export const FOG_CELL_M = 64;

/** How far the grid is grown past the explored bounding box, in cells. ONE is
 *  what the linear filter needs to see a zero beside every border cell (see
 *  the header) — a second ring would only cost texels. */
export const FOG_PAD_CELLS = 1;

/** How far the soft edge reaches into a cell, in metres. DERIVED, not chosen:
 *  the bilinear ramp spans the 64 m between two texel centres and is centred
 *  on the cell boundary they share. Exported so the smoke can check the one
 *  number against the mapping that produces it rather than against itself. */
export const FOG_BLEND_M = FOG_CELL_M / 2;

/** Camera height (metres above the point it looks at) at which the veil is
 *  exactly gone — the embodied zoom wall's own height, see the header. */
export const FOG_CLEAR_H_M = 20;

/** …and the height from which it is at full strength — the overview
 *  threshold's own height. */
export const FOG_FULL_H_M = 45;

/**
 * How much of the ground colour the veil may take at most.
 *
 * NOT 1: "haze, not black" is the whole point of the round (plan § 3). At 0.72
 * a ridge is still a ridge and a lake is still darker than the meadow beside
 * it, while nothing on that ground can be told apart — which is exactly the
 * job, because the figures that would be worth telling apart never left the
 * server (`world_ops`, the § A12 figure filter).
 */
export const FOG_ALPHA_MAX = 0.72;

/** How long a newly explored cell takes to open up, in seconds. Short enough
 *  to feel like a consequence of walking there, long enough not to be a pop —
 *  the fade is a crossfade between the old and the new explored texture, so
 *  nothing but the changed cells moves. */
export const FOG_FADE_S = 0.6;

/** Largest grid edge in texels. A world would have to reach 131 km to hit it
 *  (2048 · 64 m); it exists so a corrupt payload cannot ask for a gigabyte of
 *  texture, not because a world is expected to come close. */
export const FOG_TEX_MAX = 2048;

/** The cell index a world coordinate falls into — the server's `cell_of`. */
export function fogCellOf(v: number): number {
  return Math.floor(v / FOG_CELL_M);
}

/** Where the explored texture lies in the world, in CELLS: its lowest cell
 *  index on each axis and how many texels it has. */
export interface FogGrid {
  /** cell index of texel column 0 */
  cx0: number;
  /** cell index of texel row 0 */
  cz0: number;
  cols: number;
  rows: number;
}

/**
 * The grid for a set of `"cx,cz"` keys — the bounding box plus the zero ring.
 *
 * `null` for an empty (or entirely unparseable) set: there is no box then, and
 * the caller answers that state with the neutral one-texel texture rather than
 * with a grid nobody can index into. A key that is not two integers is
 * SKIPPED, never guessed at: `"3.5,1"` and `"a,b"` are a server this client
 * does not understand, and a grid stretched to a NaN would veil the world.
 */
export function fogGrid(cells: Iterable<string>): FogGrid | null {
  let minX = Infinity; let minZ = Infinity;
  let maxX = -Infinity; let maxZ = -Infinity;
  let seen = 0;
  for (const key of cells) {
    const cell = fogParseCell(key);
    if (!cell) continue;
    seen += 1;
    if (cell[0] < minX) minX = cell[0];
    if (cell[0] > maxX) maxX = cell[0];
    if (cell[1] < minZ) minZ = cell[1];
    if (cell[1] > maxZ) maxZ = cell[1];
  }
  if (!seen) return null;
  const p = FOG_PAD_CELLS;
  return {
    cx0: minX - p,
    cz0: minZ - p,
    cols: Math.min(maxX - minX + 1 + 2 * p, FOG_TEX_MAX),
    rows: Math.min(maxZ - minZ + 1 + 2 * p, FOG_TEX_MAX),
  };
}

/**
 * One `"cx,cz"` key as a pair of cell indices, or `null`.
 *
 * STRICTLY TWO INTEGERS, optional sign, nothing else — the discipline of
 * `decodeIsolation`: `Number()` would take `"3.5"`, `"3e2"` and `" 3 "` and
 * turn a payload this client cannot read into a veil in the wrong place.
 */
export function fogParseCell(key: string): [number, number] | null {
  if (typeof key !== 'string') return null;
  const m = /^(-?\d+),(-?\d+)$/.exec(key);
  if (!m) return null;
  return [Number(m[1]), Number(m[2])];
}

/**
 * World point -> texture coordinate of the explored grid.
 *
 * The mapping of the shader (`fogUvOf` in `fogVeil.ts`), here as the readable
 * twin: texel i covers `[i/cols, (i+1)/cols]` and its CENTRE `(i+0.5)/cols`
 * has to be the centre of cell `cx0 + i`, i.e. world `(cx0+i+0.5)·64`. Solving
 * that gives `u = (x/64 − cx0) / cols`, with no half-texel term left over —
 * the half texel is already in the cell's own half.
 */
export function fogTexUv(x: number, z: number, grid: FogGrid): [number, number] {
  return [(x / FOG_CELL_M - grid.cx0) / grid.cols,
          (z / FOG_CELL_M - grid.cz0) / grid.rows];
}

/** The texel index of one cell, or `-1` when the cell lies outside the grid
 *  (which the `FOG_TEX_MAX` clamp can produce on an absurd world). */
export function fogTexIndex(cx: number, cz: number, grid: FogGrid): number {
  const i = cx - grid.cx0;
  const j = cz - grid.cz0;
  if (i < 0 || j < 0 || i >= grid.cols || j >= grid.rows) return -1;
  return j * grid.cols + i;
}

/** Clamp to 0…1 — spelled out because it is used three times below and a
 *  hand-rolled `Math.min(Math.max())` in three places is three chances to get
 *  an end wrong. */
function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return v < 0 ? 0 : (v > 1 ? 1 : v);
}

/**
 * Camera height above its target -> how much of the veil is spent, 0…1.
 *
 * Smoothstep between `FOG_CLEAR_H_M` and `FOG_FULL_H_M` (see the header for
 * where those two come from). Below the first the answer is exactly 0 — not
 * "almost", so an embodied player pays nothing for the veil at all, neither in
 * pixels nor in the shader's own branch.
 */
export function fogHeightAlpha(heightM: number): number {
  const t = clamp01((heightM - FOG_CLEAR_H_M) / (FOG_FULL_H_M - FOG_CLEAR_H_M));
  return t * t * (3 - 2 * t);
}

/**
 * The finished opacity of the veil at one fragment: `explored` is what the
 * texture answered (1 = walked, 0 = never seen, anything between = the soft
 * edge), `heightM` the camera's height above its target.
 *
 * The product is deliberately in this order — unexplored ground near the
 * ground is clear, explored ground from high up is clear, and only the two
 * together make haze.
 */
export function fogVeilAlpha(heightM: number, explored: number): number {
  return FOG_ALPHA_MAX * (1 - clamp01(explored)) * fogHeightAlpha(heightM);
}
