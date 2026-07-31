/**
 * Click-to-walk planning of the embodied mode (plan-3d-game stage 3, task 4).
 *
 * Pure like `walk.ts`: no Three.js, no DOM, no module state, and the only
 * import is `walk.ts` itself — that is what lets
 * `scripts/smoke_walk_math.mjs` transpile and check it with hand-derived
 * numbers. The pathfinder is NOT imported: the frozen `PathGrid.findPath`
 * needs Three (it returns `Vector3`s), so main.ts hands it in as a closure
 * over cells. Passability comes in the same way, from the one set main.ts
 * also builds the pathfinder with.
 *
 * The result is deliberately thin: cell waypoints plus ONE exact goal point.
 * Walking them is the frame hook's job, with the very same boundary logic
 * WASD uses — there is no second movement path in this client.
 */
import { cellOf, clampToCell, type Cell } from './walk';

/** A planned walk: `cells` are the waypoint cells to steer at in order (the
 *  last one is where the walk ends), `goal` is the exact point inside that
 *  last cell. Waypoints are the pathfinder's CORNERS, not every cell on the
 *  way — the straight run between two corners crosses the cells in between,
 *  and each of those crossings is an ordinary cell boundary that the frame
 *  hook clears with the server. */
export interface ClickRoute {
  cells: Cell[];
  goal: { x: number; z: number };
}

/** Is that cell steppable at all (the same rule the pathfinder is built
 *  with: buildings block, road and nature carry, unknown cells are off-map). */
export type PassableFn = (gx: number, gy: number) => boolean;

/** Cell path from `a` to `b`, EXCLUDING `a` and ending with `b`, or null when
 *  there is no way. Contract of `PathGrid.findPath` (collinear cells in
 *  between are dropped, so what arrives are the corners). */
export type AstarFn = (a: Cell, b: Cell) => Cell[] | null;

/** The 8 cells around `to` that are passable, best approach first: closest to
 *  the clicked cell, ties broken by closeness to the figure and then by
 *  coordinates, so the choice never depends on iteration luck. */
function approachCells(to: Cell, from: Cell, isPassable: PassableFn): Cell[] {
  const out: Array<{ cell: Cell; toGoal: number; toFigure: number }> = [];
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      if (!dx && !dy) continue;
      const cell = { gx: to.gx + dx, gy: to.gy + dy };
      if (!isPassable(cell.gx, cell.gy)) continue;
      out.push({
        cell,
        toGoal: Math.hypot(dx, dy),
        toFigure: Math.hypot(cell.gx - from.gx, cell.gy - from.gy),
      });
    }
  }
  out.sort((a, b) => a.toGoal - b.toGoal || a.toFigure - b.toFigure
    || a.cell.gx - b.cell.gx || a.cell.gy - b.cell.gy);
  return out.map((c) => c.cell);
}

/**
 * Plan the walk for a ground click, or null when there is nothing to walk.
 *
 * Three cases:
 *  1. The click lands in the figure's OWN cell — no pathfinder, the figure
 *     just walks across the cell to the point.
 *  2. The clicked cell is passable — the pathfinder gives the corners.
 *  3. The clicked cell is NOT passable (a building): walk to the closest
 *     passable cell around it that can be reached, and stop on the edge
 *     facing the building. Is that cell the one the figure already stands in,
 *     there is nothing to do (null) — a click on a building the figure stands
 *     next to must not make it shuffle sideways.
 *
 * The goal point is always the click point CLAMPED into the last cell of the
 * route, so the walk ends safely inside it (see `clampToCell`: clamping to
 * the bare boundary would already read as the neighbour cell) and, in case 3,
 * exactly on the side of the cell that faces the building.
 *
 * `cellSize` is passed in for the same reason as in `walk.ts`: `tiles.ts`
 * owns the grid anchoring and re-declaring it here would be a second place to
 * get it wrong.
 */
export function planRoute(
  fromWorld: { x: number; z: number },
  toWorld: { x: number; z: number },
  isPassable: PassableFn,
  astar: AstarFn,
  cellSize: number,
): ClickRoute | null {
  const from = cellOf(fromWorld.x, fromWorld.z, cellSize);
  const to = cellOf(toWorld.x, toWorld.z, cellSize);

  // The goal always belongs to the cell the route really ENDS in, which is
  // the last one the pathfinder returned — so route and goal cannot drift
  // apart even if the pathfinder ever answered something unexpected.
  const routeTo = (cells: Cell[]): ClickRoute => ({
    cells,
    goal: clampToCell(toWorld.x, toWorld.z, cells[cells.length - 1], cellSize),
  });

  if (to.gx === from.gx && to.gy === from.gy) return routeTo([from]);

  if (isPassable(to.gx, to.gy)) {
    const cells = astar(from, to);
    return cells && cells.length ? routeTo(cells) : null;
  }

  for (const cand of approachCells(to, from, isPassable)) {
    // The best reachable spot is where the figure stands: no walk. Checked
    // inside the loop on purpose — a closer candidate that IS reachable still
    // wins, only when the figure's own cell comes up first does it stop here.
    if (cand.gx === from.gx && cand.gy === from.gy) return null;
    const cells = astar(from, cand);
    if (cells && cells.length) return routeTo(cells);
  }
  return null;
}
