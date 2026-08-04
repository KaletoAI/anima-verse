/**
 * The "Betreten" offer at location entries (plan-3d-lod-und-betreten.md
 * Etappe 3; contract § B1 Nr. 13).
 *
 * Pure maths like walk.ts/proximity.ts — the numbers are checked in
 * scripts/smoke_walk_math.mjs. main.ts looks the arguments up (neighbour
 * tiles, opening positions in world coordinates) and renders the offer; the
 * REAL entry stays the server's step (`/world/avatar/step`).
 */
import type { Cell } from './walk';

/** Radius around an authored boundary opening within which "Betreten" is
 *  offered, in WORLD metres. Openings are passage-sized (width_m 0.5–10 m,
 *  sanitizer): 3 m reads as "standing at it" while staying well under half a
 *  cell (CELL = 10), so the offer never fires from the far side of the cell. */
export const ENTER_RADIUS = 3;

export interface EntryTile {
  locId: string;
  cell: Cell;
  /** authored openings of this location in WORLD coordinates (the tile
   *  centre is already added); EMPTY list = no way in: since the strictness
   *  decision of 2026-08-04 only an authored opening is an entrance (the
   *  server refuses the step as well). */
  openings: { x: number; z: number }[];
}

export interface EntryOffer { locId: string; cell: Cell; dist: number }

/**
 * The one enterable neighbour location worth offering, or null.
 *
 * - Only 4-adjacent tiles count: a step crosses exactly one edge, and the
 *   offer performs a step.
 * - A tile offers entry within `radius` of one of its authored openings; a
 *   tile with no openings offers nothing.
 */
export function entryOfferNear(
  pos: { x: number; z: number },
  cell: Cell,
  tiles: EntryTile[],
  radius: number = ENTER_RADIUS,
): EntryOffer | null {
  let best: EntryOffer | null = null;
  for (const t of tiles) {
    const adjacency = Math.abs(t.cell.gx - cell.gx) + Math.abs(t.cell.gy - cell.gy);
    if (adjacency !== 1) continue;
    let dist: number | null = null;
    for (const o of t.openings) {
      const d = Math.hypot(o.x - pos.x, o.z - pos.z);
      if (d <= radius && (dist === null || d < dist)) dist = d;
    }
    if (dist !== null && (!best || dist < best.dist)) {
      best = { locId: t.locId, cell: t.cell, dist };
    }
  }
  return best;
}
