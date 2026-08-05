/**
 * Fog of war — WHICH cells of the map are still unknown (stage 5, task 2).
 *
 * The server decides WHAT the avatar knows: `/play/worldmap` delivers only the
 * locations it has discovered (§ A12), plus two facts about the whole map —
 * `grid_bounds` over ALL placed locations (deliberately UNFILTERED, so the
 * frame does not move while one discovers) and `fogged`, which says whether
 * this is the filtered view at all. This module turns those two into the
 * geometry of the veil, and nothing more: it is the only place that says which
 * cells are covered.
 *
 * PURE like `walk.ts` and `soundtrack.ts`: no `three`, no DOM, no imports and
 * no module state. That is what lets `scripts/smoke_walk_math.mjs` check every
 * case by hand — the caller in `main.ts` only turns the rectangles into quads.
 *
 * WHY RECTANGLES. A map one has barely seen is nearly all fog, and one quad
 * per cell would be hundreds of meshes for a flat grey surface. Neighbouring
 * unknown cells of the SAME row therefore fold into one rectangle. Rows are
 * not merged with each other: the second pass would rarely find a full column
 * run on the shapes a discovered map makes, and every rectangle costs the same
 * one draw call either way.
 */

/** `grid_bounds` of the worldmap payload (§ A12) — inclusive on both ends. */
export interface GridBounds {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

/** A grid cell in map coordinates (the location's `grid_x`/`grid_y`). */
export interface FogCell { x: number; y: number }

/** A run of unknown cells in one row: `w` cells wide starting at `x`, always
 *  one cell high. World metres are the caller's business. */
export interface FogRect { x: number; y: number; w: number; h: number }

/** `localStorage` key of the admin's "show all locations" switch. Only ever
 *  honoured for role `admin` — a stale value in anybody else's browser is
 *  ignored, and the server would answer 403 anyway. */
export const SHOW_ALL_KEY = 'av3d.showAllLocations';

/**
 * Every cell of the frame that has no delivered location, row-major (y outer,
 * x inner) — the order `fogQuadRects` folds in one pass.
 *
 * `bounds` null means no location is placed at all: there is no map to cover,
 * so there is no fog. Known cells outside the frame are simply not in it and
 * subtract nothing.
 */
export function unknownCells(bounds: GridBounds | null | undefined,
                             known: FogCell[]): FogCell[] {
  if (!bounds) return [];
  const seen = new Set(known.map((c) => `${c.x},${c.y}`));
  const out: FogCell[] = [];
  for (let y = bounds.min_y; y <= bounds.max_y; y++) {
    for (let x = bounds.min_x; x <= bounds.max_x; x++) {
      if (!seen.has(`${x},${y}`)) out.push({ x, y });
    }
  }
  return out;
}

/**
 * Fold cells into row runs. The input may arrive in any order and with
 * duplicates (a caller walking its tiles has no reason to sort), so this
 * dedupes and sorts first — the result is the same set of rectangles either
 * way, which is what makes the veil independent of who built the list.
 */
export function fogQuadRects(cells: FogCell[]): FogRect[] {
  const seen = new Set<string>();
  const sorted: FogCell[] = [];
  for (const c of cells) {
    const key = `${c.x},${c.y}`;
    if (seen.has(key)) continue;
    seen.add(key);
    sorted.push(c);
  }
  sorted.sort((a, b) => (a.y - b.y) || (a.x - b.x));

  const rects: FogRect[] = [];
  let run: FogRect | null = null;
  for (const c of sorted) {
    // The run grows only while the next cell touches its right edge in the
    // same row — a gap (a known cell) or a new row starts a fresh rectangle.
    if (run && run.y === c.y && run.x + run.w === c.x) {
      run.w += 1;
      continue;
    }
    run = { x: c.x, y: c.y, w: 1, h: 1 };
    rects.push(run);
  }
  return rects;
}
