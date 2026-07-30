/**
 * Pure walking maths of the embodied mode (plan-3d-game stage 3, task 3).
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM. That is what makes `scripts/smoke_walk_math.mjs` able to
 * check it with hand-derived numbers — the file is transpiled and imported as
 * plain ESM, so it must stay IMPORT-FREE as well.
 *
 * The grid anchoring is NOT re-declared here. `tiles.ts` owns it
 * (`gridToWorld(gx, gy) = (gx * CELL, 0, gy * CELL)`, `CELL = 10`) and the
 * caller passes `CELL` in as `cellSize`; the brief's `origin` parameter is
 * gone because that mapping has no offset — cell centres sit on multiples of
 * CELL, so the inverse is a plain rounding and an origin would only be a
 * second place to get it wrong.
 */

/** Inset used when a figure is held inside its cell. Not cosmetic: clamping
 *  to exactly ±cellSize/2 lands ON the boundary, and `cellOf` breaks that tie
 *  towards the higher cell — the figure would read as already gone over. */
export const EDGE_MARGIN = 0.25;

export interface Cell { gx: number; gy: number }
export type StepDirection = 'north' | 'south' | 'east' | 'west';

/** Grid cell containing a world position — the inverse of `gridToWorld`.
 *  A position exactly on a boundary counts towards the higher cell. */
export function cellOf(x: number, z: number, cellSize: number): Cell {
  return { gx: Math.round(x / cellSize), gy: Math.round(z / cellSize) };
}

/** Which compass step moves from cell `a` to the ADJACENT cell `b`, or null
 *  when `b` is not exactly one orthogonal step away (diagonal, same cell,
 *  farther). Mapping as the server does it (`world_ops.move_avatar_step`):
 *  north = -gy, south = +gy, east = +gx, west = -gx. */
export function stepDirection(a: Cell, b: Cell): StepDirection | null {
  const dx = b.gx - a.gx;
  const dy = b.gy - a.gy;
  if (dx === 0 && dy === -1) return 'north';
  if (dx === 0 && dy === 1) return 'south';
  if (dx === 1 && dy === 0) return 'east';
  if (dx === -1 && dy === 0) return 'west';
  return null;
}

/** Hold a cosmetic position inside `cell` while its boundary must not be
 *  crossed — the figure slides along the edge instead of stopping dead. */
export function clampToCell(x: number, z: number, cell: Cell, cellSize: number
): { x: number; z: number } {
  const half = cellSize / 2 - EDGE_MARGIN;
  const cx = cell.gx * cellSize;
  const cz = cell.gy * cellSize;
  return {
    x: Math.min(cx + half, Math.max(cx - half, x)),
    z: Math.min(cz + half, Math.max(cz - half, z)),
  };
}

/** Camera-relative walk direction (unit length) from the held keys, or null
 *  when nothing is pressed or opposite keys cancel out.
 *
 *  Uses the SAME basis as the engine's camera pan: forward
 *  `(-sin yaw, 0, -cos yaw)`, right `(-fwd.z, 0, fwd.x)`. If these ever
 *  disagree, "forward" means two different things on one screen. */
export function walkDir(keys: ReadonlySet<string>, yaw: number
): { x: number; z: number } | null {
  const fx = -Math.sin(yaw);
  const fz = -Math.cos(yaw);
  const rx = -fz;
  const rz = fx;
  let x = 0;
  let z = 0;
  if (keys.has('w') || keys.has('arrowup')) { x += fx; z += fz; }
  if (keys.has('s') || keys.has('arrowdown')) { x -= fx; z -= fz; }
  if (keys.has('d') || keys.has('arrowright')) { x += rx; z += rz; }
  if (keys.has('a') || keys.has('arrowleft')) { x -= rx; z -= rz; }
  const len = Math.hypot(x, z);
  if (len < 1e-6) return null;
  return { x: x / len, z: z / len };
}
