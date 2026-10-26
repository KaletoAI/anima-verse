/** Pure NPC walking and facing arithmetic. Points are world metres; yaw is radians. */
import { canRun, MOVE_EPS_M, type MovementType } from './walk';

export interface WalkPoint { x: number; y: number; z: number }
/** Shared with player steering: metres per real second. */
export const WALK_SPEED = 3.4;
export const RUN_DISTANCE = 6;
/** Door and route stations are generous; stair rides supply their tight radius. */
export const WAYPOINT_ARRIVE_M = 1.5;

/** Retire stations in 3D, then measure the chosen goal horizontally. Inputs stay untouched. */
export function npcGoal(pos: WalkPoint, target: WalkPoint, waypoints: readonly WalkPoint[],
                        retireM = WAYPOINT_ARRIVE_M) {
  let retired = 0;
  while (retired < waypoints.length) {
    const p = waypoints[retired];
    const dx = pos.x - p.x, dy = pos.y - p.y, dz = pos.z - p.z;
    if (!(Math.sqrt(dx * dx + dy * dy + dz * dz) < retireM)) break;
    retired++;
  }
  const goal = waypoints[retired] ?? target;
  const delta = { x: goal.x - pos.x, y: 0, z: goal.z - pos.z };
  const distToGoal = Math.sqrt(delta.x * delta.x + delta.z * delta.z);
  return { goal, retired, delta, distToGoal,
    dist: retired < waypoints.length ? distToGoal + 10 : distToGoal,
    moving: distToGoal > MOVE_EPS_M };
}

/** Pace limits scale the already capped step, including a measured traveller step. */
export function npcStep(goal: ReturnType<typeof npcGoal>, movement: MovementType,
                        reckoning: boolean, dt: number, pace: number, paceLimit: number,
                        reckonedStep: number | null = null) {
  const running = !reckoning && goal.dist > RUN_DISTANCE && canRun(movement);
  const step = !goal.moving || paceLimit <= 0 ? 0
    : (reckonedStep ?? Math.min(goal.distToGoal,
        WALK_SPEED * dt * pace * (running ? 1.8 : 1))) * paceLimit;
  return { running, step };
}

/** Strict 4.5 m sphere, in list order; the caller excludes the figure itself. */
export function neighbourFacing(pos: WalkPoint, others: readonly WalkPoint[]): WalkPoint | null {
  const c = { x: 0, y: 0, z: 0 };
  let count = 0;
  for (const p of others) {
    const dx = p.x - pos.x, dy = p.y - pos.y, dz = p.z - pos.z;
    if (Math.sqrt(dx * dx + dy * dy + dz * dz) < 4.5) {
      c.x += p.x; c.y += p.y; c.z += p.z; count++;
    }
  }
  if (!count) return null;
  const inverse = 1 / count;
  return { x: c.x * inverse, y: c.y * inverse, z: c.z * inverse };
}

/** A view yaw wins, then the marker, then the neighbour centroid; no request keeps facing. */
export function standingFacing(pos: WalkPoint, marker: WalkPoint | null,
                               neighbour: WalkPoint | null, viewYaw: number | null): WalkPoint | null {
  if (viewYaw !== null) return { x: Math.sin(viewYaw), y: 0, z: Math.cos(viewYaw) };
  if (marker) return { ...marker };
  return neighbour ? { x: neighbour.x - pos.x, y: 0, z: neighbour.z - pos.z } : null;
}

export function facingYaw(dir: WalkPoint): number | null {
  if (dir.x * dir.x + dir.y * dir.y + dir.z * dir.z < 1e-6) return null;
  return Math.atan2(dir.x, dir.z);
}

export function easeNpcYaw(current: number, target: number, dt: number): number {
  let d = target - current;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  return current + d * Math.min(1, dt * 10);
}

export function easeNpcY(current: number, target: number, dt: number): number {
  return current + (target - current) * Math.min(1, dt * 4);
}

/** NPC lift fallback: each missing storey uses level zero, preserving board/exit order. */
export function liftStops<T>(stops: ReadonlyMap<number, T>, from: number, to: number): T[] {
  const out: T[] = [];
  const a = stops.get(from) ?? stops.get(0);
  const b = stops.get(to) ?? stops.get(0);
  if (a) out.push(a);
  if (b) out.push(b);
  return out;
}
