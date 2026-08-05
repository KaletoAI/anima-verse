/**
 * Entering and leaving at authored boundary openings
 * (plan-3d-lod-und-betreten.md Etappe 3; contract § B1 Nr. 13).
 *
 * Pure maths like walk.ts/proximity.ts — the numbers are checked in
 * scripts/smoke_walk_math.mjs. main.ts looks the arguments up (neighbour
 * tiles, opening positions in world coordinates) and renders the offer; the
 * REAL entry stays the server's step (`/world/avatar/step`).
 *
 * Both rules here MIRROR `app/core/boundary_entry.py` — the server decides,
 * this only spares the player a refusal they could not have foreseen. An
 * opening belongs to ONE edge, so both the offer and the departure gate are
 * questions about the edge a step crosses, never about distance alone.
 */
import type { Cell } from './walk';

/** Radius around an authored boundary opening within which "Betreten" is
 *  offered, in WORLD metres. An opening is at most as wide as the location
 *  edge (server sanitizer): 3 m reads as "standing at it" while staying well
 *  under half a cell (CELL = 10), so the offer never fires from the far side
 *  of the cell. */
export const ENTER_RADIUS = 3;

/** The four edges of a location tile, as the payload spells them. */
export type Edge = 'N' | 'E' | 'S' | 'W';

/** World edge the avatar EXITS through per step direction — the client's copy
 *  of the server's `EDGE_OF_DIRECTION`. */
export const EXIT_EDGE_OF: Record<'north' | 'south' | 'east' | 'west', Edge> = {
  north: 'N', south: 'S', east: 'E', west: 'W',
};

/**
 * The edge of `to` that a step from `from` crosses — the server's
 * `OPPOSITE_EDGE[EDGE_OF_DIRECTION[dir]]`, seen from the target. Null for
 * anything that is not one 4-adjacent step.
 *
 * Stepping north (gy − 1) reaches the target over ITS south edge, and so on.
 */
export function entryEdgeBetween(from: Cell, to: Cell): Edge | null {
  const dx = to.gx - from.gx;
  const dy = to.gy - from.gy;
  if (dx === 0 && dy === -1) return 'S';
  if (dx === 0 && dy === 1) return 'N';
  if (dx === 1 && dy === 0) return 'W';
  if (dx === -1 && dy === 0) return 'E';
  return null;
}

export interface EntryTile {
  locId: string;
  cell: Cell;
  /** authored openings of this location in WORLD coordinates (the tile
   *  centre is already added), each with the WORLD edge it sits on (the
   *  payload has already applied `tile_rotation`); EMPTY list = no way in:
   *  since the strictness decision of 2026-08-04 only an authored opening is
   *  an entrance (the server refuses the step as well). */
  openings: { x: number; z: number; edge: Edge }[];
}

export interface EntryOffer { locId: string; cell: Cell; dist: number }

/**
 * The one enterable neighbour location worth offering, or null.
 *
 * - Only 4-adjacent tiles count: a step crosses exactly one edge, and the
 *   offer performs a step.
 * - Only openings ON THAT edge count. An opening on the north edge is not a
 *   way in for someone stepping in from the west, however close they stand
 *   at the corner — the server refuses that step (`opening_on_edge`), so
 *   offering it would promise something it does not grant.
 * - A tile offers entry within `radius` of such an opening; a tile with no
 *   opening on the crossed edge offers nothing.
 */
export function entryOfferNear(
  pos: { x: number; z: number },
  cell: Cell,
  tiles: EntryTile[],
  radius: number = ENTER_RADIUS,
): EntryOffer | null {
  let best: EntryOffer | null = null;
  for (const t of tiles) {
    const entryEdge = entryEdgeBetween(cell, t.cell);
    if (!entryEdge) continue;   // not 4-adjacent: no single step gets there
    let dist: number | null = null;
    for (const o of t.openings) {
      if (o.edge !== entryEdge) continue;
      const d = Math.hypot(o.x - pos.x, o.z - pos.z);
      if (d <= radius && (dist === null || d < dist)) dist = d;
    }
    if (dist !== null && (!best || dist < best.dist)) {
      best = { locId: t.locId, cell: t.cell, dist };
    }
  }
  return best;
}

/**
 * Whether the avatar may leave its location across `exitEdge` — the client's
 * mirror of `boundary_entry.may_leave`, so the figure is not walked to the
 * entry room for a step the server would have granted.
 *
 * Three ways out, in the server's order:
 * - across an authored opening ON THAT EDGE, from the room it links to — an
 *   opening without a link leads onto the ground, so the ground is what that
 *   one requires;
 * - from the entry room, the gate for every other edge;
 * - from anywhere when the location declares no entry room.
 *
 * `groundRoomId` may still be empty while the first payload is in flight;
 * then a link-less opening decides nothing rather than matching a roomless
 * avatar by accident.
 */
export function mayLeaveAcross(
  exitEdge: Edge,
  currentRoom: string,
  entryRoom: string,
  openings: { edge: Edge; room_id?: string }[],
  groundRoomId: string,
): boolean {
  for (const o of openings) {
    if (o.edge !== exitEdge) continue;
    const gate = o.room_id || groundRoomId;
    if (gate && gate === currentRoom) return true;
  }
  if (!entryRoom) return true;
  return currentRoom === entryRoom;
}
