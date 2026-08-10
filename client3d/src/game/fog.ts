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
 * PURE like `walk.ts` and `soundtrack.ts`: no `three`, no DOM, no imports and
 * no module state. That is what lets `scripts/smoke_walk_math.mjs` check every
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
// `scripts/smoke_walk_math.mjs` can pin them and the identity below.

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
 * Bands are NOT merged with each other afterwards, exactly as the grid version
 * did not merge rows into columns: two stacked bands with identical runs are
 * rare on the shapes a discovered map makes, and every rectangle costs the
 * same one draw call either way.
 *
 * Deterministic: bands ascending in z, runs ascending in x, and the input
 * order of `known` cannot change the result (the caller iterates a Map).
 */
export function fogRects(bounds: FogBounds | null | undefined,
                         known: FogFootprint[],
                         marginM: number): FogRect[] {
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
      if (s.x0 - cur > EPS_M) rects.push({ x: cur, z: za, w: s.x0 - cur, d: zb - za });
      if (s.x1 > cur) cur = s.x1;      // overlapping boxes are ONE hole
      if (x1 - cur <= EPS_M) break;
    }
    if (x1 - cur > EPS_M) rects.push({ x: cur, z: za, w: x1 - cur, d: zb - za });
  }
  return rects;
}
