/**
 * Click-to-walk of the embodied mode — FREE WALKING since E4 task 5.
 *
 * Pure like `walk.ts`: no Three.js, no DOM, no module state, and the only
 * import is a type from `walk.ts` itself, which the transpile in
 * `scripts/smoke_walk_math.mjs` drops — so the file loads there as plain ESM
 * and is checked with hand-derived numbers.
 *
 * NO CLIENT A* IN E4 (plan-freie-weltkarte-e4-3d-client.md, task 5). A click
 * plans exactly one thing: the point to walk at. The figure then heads there
 * in a straight line and SLIDES along whatever it meets on the way
 * (`walk.slideBlocked` outdoors, `collide.clampAgainstWalls` inside an open
 * interior) — the very same movement WASD produces, only with the direction
 * coming from a goal instead of from the keys.
 *
 * That is a deliberate step back from the grid world's route planning, and it
 * is honest about what it costs: a goal behind a building is not reached, the
 * figure ends up pressed against the wall and the walk gives up (`walkStalled`
 * below). A pathfinder over the free plane is E5+ work ("nach Bedarf"), and
 * inventing one here would mean a second movement model beside the one the
 * server judges — the client would walk routes the pos reports cannot follow.
 */
import type { BlockedFn, Point } from './walk';

/** Reached-the-goal threshold in metres. Must stay above the 0.05 that
 *  `NpcManager.tick()` needs to count a figure as moving, otherwise the last
 *  centimetres would never be walked and the walk would never finish. */
export const GOAL_ARRIVE_M = 0.2;

/** A step shorter than this counts as NO progress (metres). Well under one
 *  frame of walking (3.4 m/s × 1/60 s ≈ 0.057 m) and far above floating-point
 *  noise, so only a figure that really is held up trips it. */
export const STALL_STEP_M = 0.01;

/** How many stalled frames in a row end the walk. At 60 fps that is a third
 *  of a second of getting nowhere — long enough to slide around a corner,
 *  short enough that a marker over an unreachable goal does not sit there. */
export const STALL_FRAMES = 20;

/**
 * The goal a ground click walks at, or null when there is nothing to walk.
 *
 * Three answers, and the null one matters as much as the others: a click that
 * plans nothing falls through to the tile's info panel, which is how one
 * inspects a place one cannot walk into.
 *
 *  1. the clicked point is BLOCKED (impassable terrain, a foreign footprint):
 *     null — the figure would only run into it. Entering a location is the
 *     explicit offer at its opening (`enterLocation.ts`), never a click into
 *     the middle of it;
 *  2. the point is where the figure already stands (within `GOAL_ARRIVE_M`):
 *     null, nothing to do;
 *  3. otherwise the point itself, unchanged. There is no clamping any more —
 *     a metre point IS the goal, and the walk stops when it gets there.
 */
export function planClickWalk(from: Point, to: Point, blocked: BlockedFn
): Point | null {
  if (blocked(to.x, to.z)) return null;
  if (Math.hypot(to.x - from.x, to.z - from.z) < GOAL_ARRIVE_M) return null;
  return { x: to.x, z: to.z };
}

/** Has the figure arrived at its goal? */
export function reachedGoal(pos: Point, goal: Point): boolean {
  return Math.hypot(goal.x - pos.x, goal.z - pos.z) < GOAL_ARRIVE_M;
}

/** Unit direction from `pos` towards `goal` plus the distance left, or null
 *  when the two coincide (no direction to speak of). The distance is what
 *  caps the frame's step, so the figure stops ON the goal instead of walking
 *  circles around it. */
export function goalDir(pos: Point, goal: Point
): { x: number; z: number; dist: number } | null {
  const dx = goal.x - pos.x;
  const dz = goal.z - pos.z;
  const dist = Math.hypot(dx, dz);
  if (dist < 1e-6) return null;
  return { x: dx / dist, z: dz / dist, dist };
}

/** Did this frame move the figure at all? A walk that answers "no" for
 *  `STALL_FRAMES` frames in a row is stuck against something the straight
 *  line cannot get round, and the caller drops it. */
export function walkStalled(before: Point, after: Point): boolean {
  return Math.hypot(after.x - before.x, after.z - before.z) < STALL_STEP_M;
}
