/**
 * The horizontal TRAVEL of a clip's root — pure arithmetic, no three.js, so
 * `client3d/scripts/smoke_bridge_root.mjs` checks it by hand.
 *
 * Two users share the path type and its interpolation:
 *  - a PAIR clip's half drives the figure's root inside the anchor frame
 *    (`figures.pairRootAt`, `npcs.tickInteraction`) with the ABSOLUTE root
 *    position of its own clip frame;
 *  - a BRIDGE clip with root motion (`get-up-chair`, `get-up-bed`: the
 *    importer baked a foot-locked travel into the hips track) carries the
 *    figure along its travel while it plays (`figures.Figure`) — that one
 *    uses the offset RELATIVE to frame 0 (`travelAt`), because the figure
 *    starts where it stands, wherever the clip's frame 0 happens to be.
 *
 * Frame of every number here: the clip frame (+Z forward, +X the figure's
 * LEFT), in metres — which unit of metre (the clip's own, a rig's, the world's)
 * is the caller's business.
 */

/** The horizontal root path of a clip: hips XZ per keyframe. */
export interface RootPath {
  times: Float32Array;
  /** x0, z0, x1, z1, … */
  xz: Float32Array;
}

/** Root XZ at clip time `t` (linear between keys, clamped at both ends). */
export function rootPathAt(path: RootPath, t: number): { x: number; z: number } {
  const { times, xz } = path;
  const n = times.length;
  if (n === 0) return { x: 0, z: 0 };
  if (!(t > times[0])) return { x: xz[0], z: xz[1] };   // NaN lands here too
  if (t >= times[n - 1]) return { x: xz[(n - 1) * 2], z: xz[(n - 1) * 2 + 1] };
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid; else hi = mid;
  }
  const span = times[hi] - times[lo] || 1;
  const f = (t - times[lo]) / span;
  return {
    x: xz[lo * 2] + (xz[hi * 2] - xz[lo * 2]) * f,
    z: xz[lo * 2 + 1] + (xz[hi * 2 + 1] - xz[lo * 2 + 1]) * f,
  };
}

/** How far the clip has carried its root at clip time `t`, RELATIVE to
 *  frame 0 — (0, 0) at and before the start, the path's end past it. A path
 *  that does not start at the origin answers the same as the same steps from
 *  the origin: only the travel counts, not where the clip's frame put the
 *  body. */
export function travelAt(path: RootPath, t: number): { x: number; z: number } {
  if (path.times.length === 0) return { x: 0, z: 0 };
  const p = rootPathAt(path, t);
  return { x: p.x - path.xz[0], z: p.z - path.xz[1] };
}

/** A clip-frame offset turned into the WORLD by the figure's yaw (three.js
 *  `rotation.y`, which is the compass facing: forward = (sin f, cos f)):
 *  `x' = x·cos + z·sin`, `z' = −x·sin + z·cos` — the same rotation
 *  `npcs.tickInteraction` applies to a pair clip's root. */
export function toWorld(local: { x: number; z: number }, yaw: number): { x: number; z: number } {
  const c = Math.cos(yaw);
  const s = Math.sin(yaw);
  return { x: local.x * c + local.z * s, z: -local.x * s + local.z * c };
}
