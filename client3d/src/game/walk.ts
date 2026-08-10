/**
 * Pure walking maths of the embodied mode (plan-3d-game stage 3, task 3).
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM. That is what makes `scripts/smoke_walk_math.mjs` able to
 * check it with hand-derived numbers — the file is transpiled and imported as
 * plain ESM, so it must stay IMPORT-FREE as well.
 *
 * The grid anchoring is NOT re-declared here: the caller passes its cell size
 * in as `cellSize` (`gridToWorld(gx, gy) = (gx·CELL, 0, gy·CELL)`, so cell
 * centres sit on multiples of CELL and the inverse is a plain rounding). Since
 * E4 task 3 that anchor is `game/gridLegacy.ts` — `tiles.ts` builds footprints
 * in metres and has no cell any more.
 * TODO(E4 task 5): the cell functions here (`cellOf`, `clampToCell`,
 * `splitDiagonal`, `stepDirection`, `keepAhead`, `EDGE_MARGIN`) go with the
 * step machine; `walkDir` is the part of this file that survives free walking.
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

/** Keep a goal from falling BEHIND the figure (per axis, along the walking
 *  direction). Needed because `clampToCell` pulls the goal to the inset edge
 *  while the figure may already stand closer to the boundary than that: the
 *  goal would then lie behind it, `tick()` would walk backwards, the next
 *  frame forwards again — the figure vibrates on the edge and flips its
 *  facing every frame. An axis whose goal points against the direction simply
 *  stands still; the other axis keeps sliding along the edge. */
export function keepAhead(goal: { x: number; z: number }, pos: { x: number; z: number },
  dir: { x: number; z: number }): { x: number; z: number } {
  return {
    x: dir.x > 0 ? Math.max(goal.x, pos.x) : dir.x < 0 ? Math.min(goal.x, pos.x) : goal.x,
    z: dir.z > 0 ? Math.max(goal.z, pos.z) : dir.z < 0 ? Math.min(goal.z, pos.z) : goal.z,
  };
}

/** Reduce a goal that crosses BOTH cell axes at once (a corner) to a single-
 *  axis crossing by pulling the axis with the SMALLER overshoot back into the
 *  current cell. A diagonal crossing has no compass step, and treating it as
 *  blocked would nail the avatar to the corner — reachable in practice, since
 *  the camera's default yaw is 45° and Q/E turn in exact 45° steps. What is
 *  left over is an ordinary one-cell step; the next frame takes the other
 *  axis. Ties go to x, deterministically. A goal that crosses at most one
 *  axis is returned unchanged. */
export function splitDiagonal(x: number, z: number, from: Cell, cellSize: number
): { x: number; z: number } {
  const to = cellOf(x, z, cellSize);
  if (to.gx === from.gx || to.gy === from.gy) return { x, z };
  const half = cellSize / 2;
  const overX = Math.abs(x - from.gx * cellSize) - half;
  const overZ = Math.abs(z - from.gy * cellSize) - half;
  const held = clampToCell(x, z, from, cellSize);
  return overX <= overZ ? { x: held.x, z } : { x, z: held.z };
}

// `walkSpeedScale` and `MIN_WALK_SCALE` are GONE (E4 task 3). They slowed the
// avatar down by the scale its figure was drawn at, because a world metre
// inside a room used to be a fraction of a human metre. With k = 1 there is no
// second scale to follow: `WALK_SPEED` is 3.4 metres a second, indoors and out.

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
