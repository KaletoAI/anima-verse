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

/** Is that cell WALKING ground (the same rule the pathfinder is built with:
 *  buildings block, road and nature carry, unknown cells are off-map). It
 *  governs the cells a route travels THROUGH. */
export type PassableFn = (gx: number, gy: number) => boolean;

/** Does a location sit on that cell at all — the question that decides whether
 *  it may be a DESTINATION. The server has no passability check in its step
 *  (`world_ops.move_avatar_step`: entry-room gate and block rules, nothing
 *  else), so a plot or a building is enterable on foot and the client must not
 *  clamp it away; a cell without a location is not, the server answers 404
 *  for a step onto nothing. */
export type KnownFn = (gx: number, gy: number) => boolean;

/** Cell path from `a` to `b`, EXCLUDING `a` and ending with `b`, or null when
 *  there is no way. Contract of `PathGrid.findPath` (collinear cells in
 *  between are dropped, so what arrives are the corners). */
export type AstarFn = (a: Cell, b: Cell) => Cell[] | null;

/**
 * Does the walk only touch cells it is allowed to enter?
 *
 * It has to be asked, because the pathfinder and the walk do NOT share a
 * passability model: `PathGrid.walkable()` blocks only cells it knows as
 * impassable, so a cell with no location at all counts as walkable there
 * (with a cost penalty) — while the walk can never enter it, the server
 * answers 404 for a step onto nothing. Unchecked, such a route dies silently
 * at the first gap: the frame hook bars the crossing and drops the route, and
 * the player sees the marker vanish for no reason.
 *
 * Checked are all cells the figure really enters, not just the corners:
 *  - the cells a straight leg passes through (the corner list skips them),
 *  - for a diagonal leg BOTH orthogonal cells of every step, because the
 *    frame hook turns a corner crossing into a single-axis step and is free
 *    to take either one.
 * The cell the figure starts in is not checked — it is standing there.
 * A leg that is neither straight nor exactly diagonal cannot come from this
 * pathfinder; it counts as invalid rather than being guessed at.
 *
 * `enterLast` is the ONE exception, and it is exactly one cell wide: the very
 * last cell of the route may be impassable, because a route into a plot or a
 * building ends there on purpose (the server allows that step). Everything
 * before it stays strictly passable — a known cell on the WAY is still a wall,
 * and even the last step keeps its diagonal corner cells under the strict
 * rule, since the frame hook walks the corner through one of them.
 */
function walkStaysPassable(from: Cell, cells: Cell[], isPassable: PassableFn,
  enterLast = false): boolean {
  let at = from;
  for (let leg = 0; leg < cells.length; leg++) {
    const dx = cells[leg].gx - at.gx;
    const dy = cells[leg].gy - at.gy;
    if (dx && dy && Math.abs(dx) !== Math.abs(dy)) return false;
    const steps = Math.max(Math.abs(dx), Math.abs(dy));
    const sx = Math.sign(dx);
    const sy = Math.sign(dy);
    for (let i = 1; i <= steps; i++) {
      const gx = at.gx + sx * i;
      const gy = at.gy + sy * i;
      const final = enterLast && leg === cells.length - 1 && i === steps;
      if (!final && !isPassable(gx, gy)) return false;
      if (sx && sy) {
        // the two cells the diagonal step could go round the corner by
        if (!isPassable(gx, gy - sy) || !isPassable(gx - sx, gy)) return false;
      }
    }
    at = cells[leg];
  }
  return true;
}

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
 * Four cases:
 *  1. The click lands in the figure's OWN cell — no pathfinder, the figure
 *     just walks across the cell to the point.
 *  2. The clicked cell is passable — the pathfinder gives the corners.
 *  3. The clicked cell is not passable but a KNOWN location (a plot, a
 *     building): walk to the closest passable cell around it that can be
 *     reached and take ONE more step INTO it. Stands the figure already in one
 *     of those approach cells, the route is exactly that one step — no
 *     pathfinder, and no sidestep along the wall to a "closer" spot. That the
 *     step is allowed at all is the SERVER's call (it may refuse with a block
 *     rule or the entry-room gate); the frame hook asks for every crossing
 *     anyway and handles the refusal.
 *  4. The clicked cell carries no location — nothing to walk to (null), and
 *     the click falls through to the tile panel.
 *
 * In cases 2 and 3 the planned way is validated against the SAME passability
 * the walk uses (`walkStaysPassable`) — the pathfinder's is wider, and a
 * route it invents over unknown ground would die silently on the first step.
 * The target exception of case 3 is one cell wide: the destination itself.
 *
 * The goal point is always the click point CLAMPED into the last cell of the
 * route, so the walk ends safely inside it (see `clampToCell`: clamping to
 * the bare boundary would already read as the neighbour cell).
 *
 * `cellSize` is passed in for the same reason as in `walk.ts`: `tiles.ts`
 * owns the grid anchoring and re-declaring it here would be a second place to
 * get it wrong.
 */
export function planRoute(
  fromWorld: { x: number; z: number },
  toWorld: { x: number; z: number },
  isPassable: PassableFn,
  isKnown: KnownFn,
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
    if (!cells || !cells.length) return null;
    return walkStaysPassable(from, cells, isPassable) ? routeTo(cells) : null;
  }

  if (!isKnown(to.gx, to.gy)) return null;

  // Every route below ends with the step INTO the target cell — that last
  // cell is the one `walkStaysPassable` is allowed to let through impassable.
  const enter = (lead: Cell[]): ClickRoute | null => {
    const cells = [...lead, to];
    return walkStaysPassable(from, cells, isPassable, true) ? routeTo(cells) : null;
  };
  const approaches = approachCells(to, from, isPassable);
  const standsInFront = approaches.some((c) => c.gx === from.gx && c.gy === from.gy);
  if (standsInFront) {
    // Straight in from where the figure stands. May still fail: a diagonal
    // step needs both of its corner cells, and then walking round is right.
    const direct = enter([]);
    if (direct) return direct;
  }
  for (const cand of approaches) {
    if (cand.gx === from.gx && cand.gy === from.gy) continue;
    const lead = astar(from, cand);
    if (!lead || !lead.length) continue;
    const route = enter(lead);
    if (route) return route;
  }
  return null;
}
