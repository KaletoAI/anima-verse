/** Pair entry is view state: real seconds, independent of the game/clip clock. */
export const BLEND_S = 0.4;
export interface PairPose { x: number; y: number; z: number; yaw: number }

/** The pose a figure is SHOWN in when a pair takes it over — the blend's
 *  origin. Normally its root. A figure inside a measured prop entry is the
 *  exception: its root stays on the ACCESS point on the floor while the entry
 *  clip's travel and support lift carry the body onto the seat, and the server
 *  ends the entry in the same commit that starts the pair (the entry is
 *  finished at phase 1 in that very update). Its shown pose is then the entry's
 *  ANCHOR — `y` the body root, yaw compass degrees like every entry angle.
 *  Taking the root there dropped the body onto the floor and blended it back
 *  up onto the seat (2026-11-08, `scripts/smoke_pair_after_entry.mjs`). */
export function pairBlendOrigin(root: { x: number; y: number; z: number }, yaw: number,
  entry: { anchor: { x: number; y: number; z: number; yaw: number } } | null | undefined): PairPose {
  if (entry) {
    const a = entry.anchor;
    return { x: a.x, y: a.y, z: a.z, yaw: a.yaw * Math.PI / 180 };
  }
  return { x: root.x, y: root.y, z: root.z, yaw };
}

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
