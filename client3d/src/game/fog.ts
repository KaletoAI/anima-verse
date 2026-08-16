/**
 * Fog of war — WHICH PART OF THE WORLD PLANE is still unknown (E4 task 6).
 *
 * The server decides WHAT the avatar knows: `/play/worldmap` delivers only the
 * locations it has discovered (§ A12), plus two facts about the whole map —
 * `world_bounds` over ALL placed locations (deliberately UNFILTERED, so the
 * frame does not move while one discovers) and `fogged`, which says whether
 * this is the filtered view at all. This module turns those into the geometry
 * of the veil, and nothing more: it is the only place that says what is
 * covered.
 *
 * METRES, NOT CELLS. The grid world's fog covered every 10 m CELL of
 * `grid_bounds` that carried no location, and a rectangle was a run of such
 * cells in one row. There is no cell any more (§ A1.1): a location is a square
 * footprint standing anywhere on the free plane, so the veil is the world
 * frame MINUS the footprints of the known locations — continuous geometry,
 * computed the same way whatever scale the world is drawn at.
 *
 * FOG IS ATMOSPHERE, NOT GEOMETRY. A footprint turned by `yaw_deg` is
 * subtracted as its axis-aligned BOUNDING BOX, never as the turned square. On
 * the diagonal that box is √2 times the edge, so a turned location clears a
 * little more sky than it covers — the harmless direction: the veil never lies
 * ON a place one knows, and nobody can tell a cloud edge from a cloud edge two
 * metres further out. Cutting the true rotated polygon would need a general
 * polygon difference, and it would buy a picture nobody can see.
 *
 * HOW MANY RECTANGLES. `n` known places cut the frame into at most `2n + 1`
 * bands with at most `n + 1` runs each; what a real map costs was measured
 * (review of this task, randomised footprints): `n = 100` known locations give
 * about **750** rectangles on average — one shared material, one draw call
 * each, and only rebuilt when something moves. That is comfortable, and it is
 * also where the next lever sits if a world ever gets big enough to feel it:
 * merging vertically adjacent bands with identical runs. It is deliberately
 * NOT done here (see the algorithm note in `fogRects`).
 *
 * The RELIEF cuts those rectangles further (`FOG_TILE_M`), and that lever was
 * pulled in E8 task 5: only a rectangle with actual relief under it is tiled at
 * all, so an unshaped world stays at the 750 above and a shaped one pays for
 * its hills and nothing else. Measured on randomised worlds (1000 × 1000 m,
 * 60 m margin, footprints 10-30 m, 20 runs per row, `smoke_walk_math.mjs`
 * census): at n = 100 a level world is 744 quads, tiling every rectangle
 * unconditionally is 3659, and a world with three 240 m hills in it is 1899.
 * At n = 10 the three rows read 36 / 559 / 399, at n = 50 265 / 1857 / 989.
 *
 * THE VEIL HAS A MEMORY since 2026-08-16 (finding B14, option 2): besides the
 * known footprints it also spares every 64 m cell the avatar has already stood
 * in — the server's record, `GET /play/explored`, fetched on its own signature.
 * A wood between two places therefore clears by being walked through instead of
 * staying dark for the rest of the world's life. It costs quads only where the
 * memory reaches: a run with no explored cell under it is left exactly as the
 * paragraphs above describe it, and only a run that touches one is cut onto the
 * cell raster. The avatar's own close-up mode is unchanged — it draws no veil
 * at all (option 1, `main.ts`).
 *
 * PURE like `walk.ts` and `soundtrack.ts`: no `three`, no DOM, no imports and
 * no module state. That is what lets `client3d/scripts/smoke_walk_math.mjs` check every
 * case by hand — the caller in `main.ts` only turns the rectangles into quads.
 * The fog OPTICS constants below live here for the same reason: `fogClouds.ts`
 * needs `three` and a canvas and cannot be loaded in a smoke at all, so the
 * numbers it is built from are pinned on this side of the line.
 */

/** Extent of the world in METRES (`world_bounds`, § A12). Structurally the
 *  payload's own `WorldBounds`; spelled out here because this module imports
 *  nothing, not even a type. */
export interface FogBounds {
  min_x: number;
  min_z: number;
  max_x: number;
  max_z: number;
}

/** A known location's footprint square: centre in world metres, edge length
 *  `width`, turned by `yaw` RADIANS (the tile's own `center`/`width`/`yaw` —
 *  what is DRAWN, so the hole in the veil and the tile under it can never
 *  disagree). */
export interface FogFootprint {
  x: number;
  z: number;
  width: number;
  yaw: number;
}

/** An axis-aligned box in world metres, minimum and maximum on both axes. */
export interface FogBox { x0: number; x1: number; z0: number; z1: number }

/** A rectangle of the veil in world metres: `x`/`z` is its MINIMUM corner,
 *  `w`/`d` its extents. The caller centres its quad on it. */
export interface FogRect { x: number; z: number; w: number; d: number }

/** `localStorage` key of the admin's "show all locations" switch. Only ever
 *  honoured for role `admin` — a stale value in anybody else's browser is
 *  ignored, and the server would answer 403 anyway. */
export const SHOW_ALL_KEY = 'av3d.showAllLocations';

// --- The optics of the veil, in ABSOLUTE METRES (E4 task 6) -----------------
//
// These were `CELL · 0.32`, `CELL · 0.18` and `CELL · 4.6` while a location
// WAS a 10 m cell. The cell is gone, so they are the metres those products
// were — the values do not change, their anchor does. `fogClouds.ts` builds
// the material out of them; they are declared in the pure module so
// `client3d/scripts/smoke_walk_math.mjs` can pin them and the identity below.

/** How far a quad is drawn beyond its rectangle, in metres — the whole soft
 *  border lives in here. Enough for a cloud edge to read as torn, little
 *  enough that the cover only laps over the rim of the nearest known place
 *  instead of hiding it. */
export const FOG_OVERHANG_M = 3.2;
/** Width of the alpha ramp in metres. */
export const FOG_FEATHER_M = 1.8;
/** How deep the noise may bite into the margin, in metres.
 *
 *  THE LOAD-BEARING IDENTITY is `FOG_FEATHER_M + FOG_RAGGED_M ===
 *  FOG_OVERHANG_M`: the alpha then reaches 1 exactly AT the true rectangle
 *  border even in the worst case of the bite, so where two rectangles meet
 *  both are fully opaque and the overdraw can never open a translucent seam
 *  into the interior. Derived here rather than written out, so it cannot be
 *  broken by editing one number. */
export const FOG_RAGGED_M = FOG_OVERHANG_M - FOG_FEATHER_M;
/** Metres per texture tile. Bigger than a location, smaller than a region: the
 *  drift is visible without the repeat becoming a pattern. */
export const FOG_TEX_METRES = 46;

/**
 * Edge length a veil rectangle is TILED down to, in metres (E8 task 3).
 *
 * A rectangle used to be as long as the band it came from — a world-wide strip
 * between two rows of known places. That was free while the veil was flat. On
 * a relief it is not: a quad hangs above the highest ground inside its own
 * rectangle, so ONE hill lifted a fifteen-hundred-metre strip fifty metres into
 * the air and the player looked at the underside of a cloud that had nothing to
 * hide there.
 *
 * Tiling costs draw calls and reveals NOTHING: the terrain is never fogged
 * (§ A12), so the draped ground already shows every ridge — a cover that
 * follows it tells no one anything the picture does not. 64 m is a bit more
 * than the cloud texture's own tile (46 m), so the cover still reads as one
 * sky, and small enough that a hill lifts its own neighbourhood only.
 *
 * ONLY WHERE THE GROUND ACTUALLY MOVES (E8 task 5). Tiling every rectangle
 * cost what it was measured to cost: 744 quads at 100 known places became
 * 3659. But the reason is a hill, so a rectangle with no hill under it has no
 * reason to be cut at all — `fogRects` takes a height-range query and keeps
 * such a rectangle whole. A world nobody has shaped is back to exactly the
 * flat world's count, and a shaped one only pays for the parts that are
 * shaped.
 */
export const FOG_TILE_M = 64;

/**
 * How much the ground may rise and fall under ONE veil rectangle before it is
 * tiled, in metres (E8 task 5).
 *
 * The quad hangs `FOG_CLEARANCE_M` (5 cm) above the HIGHEST ground inside its
 * rectangle, so an untiled rectangle floats up to this much plus that clearance
 * above its lowest ground — 30 cm of air in the worst case, seen from the
 * overview camera 70 m up, which is the only mode the veil is drawn in. That is
 * invisible, and it is two orders below the failure this tiling exists for (one
 * hill lifting a world-wide band fifty metres).
 *
 * Not zero: a field is floating-point, and a "flat" world sampled through a
 * drawn surface answers in the last bits. A hand's breadth of slack keeps the
 * flat world at one quad per rectangle instead of losing it to noise.
 */
export const FOG_FLAT_EPS_M = 0.25;

/**
 * Edge length of one EXPLORATION cell in metres (Fog-Gedächtnis, 2026-08-16).
 *
 * The server remembers where the avatar has stood as cells of this size,
 * anchored at the WORLD ORIGIN (`app/core/exploration.py`), and the veil spares
 * them in addition to the known footprints — a wood between two places clears
 * by being walked through instead of staying dark forever (finding B14,
 * option 2).
 *
 * It is the SAME number as `FOG_TILE_M`, and that is the whole reason this fits
 * into the existing tiling instead of needing a new one: a spared cell is one
 * tile that is not built, never a hole cut into a quad. Both sides say the
 * number themselves — the server in `EXPLORED_CELL_M`, the client here — and
 * `client3d/scripts/smoke_fog_memory.mjs` pins that they agree.
 */
export const EXPLORED_CELL_M = 64;

/** The cell index a world coordinate falls into. `Math.floor`, so −1 m is cell
 *  −1 and the raster stays continuous across the origin — the twin of
 *  `exploration.cell_of`. */
export function exploredCellOf(v: number): number {
  return Math.floor(v / EXPLORED_CELL_M);
}

/** Wire form of one cell, `"cx,cz"` — what `GET /play/explored` sends and what
 *  the lookup set below is keyed by (`exploration.cell_key`). */
export function exploredCellKey(cx: number, cz: number): string {
  return `${cx},${cz}`;
}

/** The cells the avatar has already been in, as `exploredCellKey` strings.
 *  An empty set (or none at all) is a world nobody has walked yet, and then
 *  everything below behaves exactly as it did before the memory existed. */
export type ExploredCells = ReadonlySet<string>;

/** How much the ground rises and falls inside an axis-aligned world rectangle,
 *  in metres — `worldHeightRangeIn` of the ground module, handed in as a
 *  function because this module imports nothing (see the header). A caller
 *  that has no field at all passes nothing and gets the tiling unconditionally,
 *  which is the safe direction: it is what the veil did before. */
export type FogHeightRange =
  (x0: number, z0: number, x1: number, z1: number) => number;

/** Extents below this are not worth a draw call (metres). A sliver of a
 *  micrometre between two footprints is not a hole in the cloud cover, it is
 *  floating-point noise — and a quad for it would still be drawn 3.2 m
 *  oversized on every side. */
const EPS_M = 1e-6;

/**
 * The axis-aligned box of a footprint square, or `null` when the location has
 * no usable geometry.
 *
 * A square of edge `w` turned by `yaw` reaches `(w / 2) · (|cos yaw| +
 * |sin yaw|)` from its centre along EITHER world axis — the two corner offsets
 * projected onto that axis, and the same value on both because the shape is a
 * square. Unturned that is `w / 2`, at 45° it is `(w / 2) · √2.`
 *
 * `null` for a non-finite centre or a width ≤ 0: such a location has no area
 * at all (§ A1.1), it subtracts nothing and stays under the veil — which is
 * the honest picture of a world-data defect, not a repair.
 */
export function footprintBox(fp: FogFootprint): FogBox | null {
  const { x, z, width, yaw } = fp;
  if (!Number.isFinite(x) || !Number.isFinite(z)) return null;
  if (!Number.isFinite(width) || width <= 0) return null;
  const turn = Number.isFinite(yaw) ? yaw : 0;
  const half = (width / 2) * (Math.abs(Math.cos(turn)) + Math.abs(Math.sin(turn)));
  return { x0: x - half, x1: x + half, z0: z - half, z1: z + half };
}

/**
 * The veil: the world frame grown by `marginM`, minus the boxes of the known
 * footprints, cut into axis-aligned rectangles.
 *
 * `bounds` null means nothing is placed at all: there is no map, so there is
 * no fog. `fogged: false` (the admin's unfiltered view) is the CALLER's
 * business — it draws no veil at all and never asks.
 *
 * `marginM` is how far the veil reaches past the outermost footprint. The
 * caller passes the GROUND's own margin, so the cover ends exactly where the
 * drawn world does; a bare plane sticking out from under the clouds would
 * advertise the edge of the map.
 *
 * THE SUBDIVISION. Every box is first clipped into the outer rectangle, so
 * nothing outside the frame has any say. The frame is then swept in Z: the
 * band boundaries are the outer edges plus every box edge, which means inside
 * ONE band a box either spans it completely or not at all. A band is therefore
 * a 1-D problem — the outer x interval minus the x intervals of the boxes that
 * live in it — and each remaining run becomes one rectangle.
 *
 * `heightRange` is the ground's own "how much does it move in here" (see
 * `FOG_FLAT_EPS_M`). Every run is asked once: over level ground it stays ONE
 * rectangle, over relief it is cut into `FOG_TILE_M` tiles. Omitting it tiles
 * everything, which is what this did before the query existed.
 *
 * `explored` is the avatar's MEMORY (see `EXPLORED_CELL_M`): every cell in it
 * is spared, on top of the footprints. A run that touches no explored cell is
 * untouched by this and keeps the counts in the module header; a run that does
 * is cut on the ORIGIN-ANCHORED cell raster and the explored cells simply
 * produce no rectangle. Those pieces are never tiled afterwards — a cell is
 * `FOG_TILE_M` wide, so each piece is already at most one tile in both axes,
 * which is exactly what the relief tiling exists to guarantee.
 *
 * Bands are NOT merged with each other afterwards, exactly as the grid version
 * did not merge rows into columns: two stacked bands with identical runs are
 * rare on the shapes a discovered map makes, and every rectangle costs the
 * same one draw call either way. The measured count is in the module header —
 * that merge is the lever to pull if it ever stops being comfortable.
 *
 * Deterministic: bands ascending in z, runs ascending in x, and the input
 * order of `known` cannot change the result (the caller iterates a Map).
 */
export function fogRects(bounds: FogBounds | null | undefined,
                         known: FogFootprint[],
                         marginM: number,
                         heightRange?: FogHeightRange,
                         explored?: ExploredCells): FogRect[] {
  if (!bounds) return [];
  const margin = Number.isFinite(marginM) ? marginM : 0;
  const x0 = bounds.min_x - margin;
  const x1 = bounds.max_x + margin;
  const z0 = bounds.min_z - margin;
  const z1 = bounds.max_z + margin;
  if (!(Number.isFinite(x0) && Number.isFinite(x1)
        && Number.isFinite(z0) && Number.isFinite(z1))) return [];
  if (x1 - x0 <= EPS_M || z1 - z0 <= EPS_M) return [];

  const boxes: FogBox[] = [];
  for (const fp of known) {
    const box = footprintBox(fp);
    if (!box) continue;
    const c: FogBox = {
      x0: Math.max(box.x0, x0), x1: Math.min(box.x1, x1),
      z0: Math.max(box.z0, z0), z1: Math.min(box.z1, z1),
    };
    if (c.x1 - c.x0 <= EPS_M || c.z1 - c.z0 <= EPS_M) continue;
    boxes.push(c);
  }

  const cuts = [z0, z1];
  for (const b of boxes) {
    if (b.z0 > z0 && b.z0 < z1) cuts.push(b.z0);
    if (b.z1 > z0 && b.z1 < z1) cuts.push(b.z1);
  }
  cuts.sort((a, b) => a - b);

  const rects: FogRect[] = [];
  /**
   * The MEMORY's share of one run (2026-08-16). Answers whether it handled the
   * run: `false` means no explored cell lies under it and the caller carries on
   * exactly as before.
   *
   * When it does handle it, the run is cut on the ORIGIN-ANCHORED cell raster —
   * `cx` from `exploredCellOf(x)` to the cell the far edge falls in — and every
   * cell the avatar has NOT been in becomes one rectangle, clipped to the run.
   * The explored ones produce nothing, which is the hole in the veil.
   *
   * The far edge is asked at `x + w − EPS_M`: a run ending exactly on a cell
   * border belongs to the cell BEFORE it, and without the nudge every such run
   * would carry an empty column of zero width along.
   */
  const spare = (x: number, z: number, w: number, d: number): boolean => {
    const cx0 = exploredCellOf(x);
    const cx1 = exploredCellOf(x + w - EPS_M);
    const cz0 = exploredCellOf(z);
    const cz1 = exploredCellOf(z + d - EPS_M);
    let any = false;
    for (let cx = cx0; cx <= cx1 && !any; cx++) {
      for (let cz = cz0; cz <= cz1; cz++) {
        if (explored!.has(exploredCellKey(cx, cz))) { any = true; break; }
      }
    }
    if (!any) return false;
    for (let cx = cx0; cx <= cx1; cx++) {
      const px0 = Math.max(x, cx * EXPLORED_CELL_M);
      const px1 = Math.min(x + w, (cx + 1) * EXPLORED_CELL_M);
      if (px1 - px0 <= EPS_M) continue;
      for (let cz = cz0; cz <= cz1; cz++) {
        if (explored!.has(exploredCellKey(cx, cz))) continue;
        const pz0 = Math.max(z, cz * EXPLORED_CELL_M);
        const pz1 = Math.min(z + d, (cz + 1) * EXPLORED_CELL_M);
        if (pz1 - pz0 <= EPS_M) continue;
        rects.push({ x: px0, z: pz0, w: px1 - px0, d: pz1 - pz0 });
      }
    }
    return true;
  };
  /** One run of the sweep, cut into tiles of at most `FOG_TILE_M` (see there)
   *  — but ONLY where the ground under it moves. The pieces are EQUAL —
   *  dividing by the count instead of stepping by the tile size avoids a sliver
   *  at the far end, which would be a draw call for a hand's breadth of cloud.
   *
   *  The flatness question is asked ONCE per run, over the whole run: a run
   *  that is level end to end needs no cut anywhere in it, and a run that is
   *  not is cut throughout — a per-tile question would cost one range scan per
   *  tile to save quads over the flat half of a hillside, which is paying the
   *  rebuild to save the frame. */
  const push = (x: number, z: number, w: number, d: number): void => {
    // THE MEMORY FIRST (2026-08-16). Explored ground is spared whatever the
    // relief under it does — a cover over a hill one has walked over is still a
    // cover over ground one knows. Only a run that ACTUALLY touches an explored
    // cell is cut this way: without that every run in a walked world would be
    // cut onto the cell raster, which is the quad census the flat-world case
    // exists to keep down.
    if (explored && explored.size && spare(x, z, w, d)) return;
    // Whole unless the ground is DEMONSTRABLY level: no query, or a range that
    // is not a number, means tile — the picture the veil had before.
    if (heightRange && heightRange(x, z, x + w, z + d) <= FOG_FLAT_EPS_M) {
      rects.push({ x, z, w, d });
      return;
    }
    const nx = Math.max(1, Math.ceil(w / FOG_TILE_M - 1e-9));
    const nz = Math.max(1, Math.ceil(d / FOG_TILE_M - 1e-9));
    const tw = w / nx;
    const td = d / nz;
    for (let ix = 0; ix < nx; ix++) {
      for (let iz = 0; iz < nz; iz++) {
        rects.push({ x: x + ix * tw, z: z + iz * td, w: tw, d: td });
      }
    }
  };
  for (let i = 0; i < cuts.length - 1; i++) {
    const za = cuts[i];
    const zb = cuts[i + 1];
    if (zb - za <= EPS_M) continue;   // duplicate cut (two boxes ending alike)
    // A box either spans the whole band or misses it, so its MIDDLE decides —
    // no interval arithmetic, and no dependence on which end is inclusive.
    const mid = (za + zb) / 2;
    const spans = boxes.filter((b) => b.z0 <= mid && b.z1 >= mid)
      .sort((a, b) => a.x0 - b.x0);
    let cur = x0;
    for (const s of spans) {
      if (s.x0 - cur > EPS_M) push(cur, za, s.x0 - cur, zb - za);
      if (s.x1 > cur) cur = s.x1;      // overlapping boxes are ONE hole
      if (x1 - cur <= EPS_M) break;
    }
    if (x1 - cur > EPS_M) push(cur, za, x1 - cur, zb - za);
  }
  return rects;
}
