/**
 * WHICH ROOM a tile-local point stands in — the pure half of main.ts'
 * `roomAt` / `corridorAt` and of `deriveRoomSpots`' room rectangle.
 *
 * Three small rules that several callers lean on (the room ambience under the
 * light focus, the open-view room of a ground / plan-hull model, the walk
 * scope) and that the native client ports one to one, so they live here as
 * plain functions with no `three`, no DOM and no module state. The callers
 * turn the world point into the tile frame first (`worldToTile`); everything
 * below is TILE-LOCAL metres. Hand oracles: `client3d/scripts/smoke_ambience.mjs`
 * (cases in shared/test-vectors/ambience.json).
 */
import { pointInPolygon } from './polygon';

/** A room's axis-aligned rectangle in the tile frame: centre and size. */
export interface RoomRect { x: number; z: number; w: number; d: number }

/** The storey corridor block the corridor test reads (`TileCorridor`). */
export interface CorridorOutline {
  roomId: string;
  level: number;
  outline: ReadonlyArray<readonly number[]>;
}

/**
 * The rectangle `deriveRoomSpots` files under `tile.roomRects`: the bounding
 * box of the room's hull, at least 0.5 m on each side (a sliver room still
 * answers a point near its middle). `null` for a hull without a finite point.
 */
export function roomRectOf(hull: ReadonlyArray<readonly number[]>): RoomRect | null {
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const [px, pz] of hull) {
    if (px < minX) minX = px;
    if (px > maxX) maxX = px;
    if (pz < minZ) minZ = pz;
    if (pz > maxZ) maxZ = pz;
  }
  if (!Number.isFinite(minX)) return null;
  return {
    x: (minX + maxX) / 2,
    z: (minZ + maxZ) / 2,
    w: Math.max(maxX - minX, 0.5),
    d: Math.max(maxZ - minZ, 0.5),
  };
}

/**
 * The SMALLEST room rectangle that covers a tile-local point, or null — "the
 * most specific wins", like the footprints. The edges count as inside
 * (`|p − centre| > half size` is the only rejection). On equal areas the room
 * met first stays.
 */
export function roomAtRects(rects: Iterable<readonly [string, RoomRect]>,
                            x: number, z: number): string | null {
  let best: string | null = null;
  let bestArea = Infinity;
  for (const [id, r] of rects) {
    if (Math.abs(x - r.x) > r.w / 2 || Math.abs(z - r.z) > r.d / 2) continue;
    const area = r.w * r.d;
    if (area < bestArea) { best = id; bestArea = area; }
  }
  return best;
}

/**
 * The storey CORRIDOR that covers a tile-local point, or null. A corridor is
 * the complement of its storey's rooms (§ A13b), so it has no rectangle; the
 * LOWEST storey at or above ground (level ≥ 0; the first of equal levels) is
 * the line between hallway and yard, tested with the half-open ray cast of
 * `pointInPolygon`. An outline under three points answers nothing.
 */
export function corridorAtOutline(corridors: readonly CorridorOutline[],
                                  x: number, z: number): string | null {
  let lowest: CorridorOutline | null = null;
  for (const c of corridors) {
    if (c.level >= 0 && (!lowest || c.level < lowest.level)) lowest = c;
  }
  if (!lowest || lowest.outline.length < 3) return null;
  return pointInPolygon(x, z, lowest.outline) ? lowest.roomId : null;
}
