/** Pair entry is view state: real seconds, independent of the game/clip clock. */
export const BLEND_S = 0.4;
export interface PairPose { x: number; y: number; z: number; yaw: number }

/** Blend the adoption pose toward this frame's moving root, taking the shortest yaw. */
export function pairBlend(from: PairPose, target: PairPose, elapsedS: number): PairPose & { weight: number } {
  const u = Math.max(0, Math.min(1, elapsedS / BLEND_S));
  const weight = u * u * (3 - 2 * u);
  const delta = Math.atan2(Math.sin(target.yaw - from.yaw), Math.cos(target.yaw - from.yaw));
  return {
    weight,
    x: from.x + (target.x - from.x) * weight,
    y: from.y + (target.y - from.y) * weight,
    z: from.z + (target.z - from.z) * weight,
    yaw: from.yaw + delta * weight,
  };
}
