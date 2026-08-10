/**
 * Pure walking maths of the embodied mode — FREE WALKING since E4 task 5.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM. That is what makes `scripts/smoke_walk_math.mjs` able to
 * check it with hand-derived numbers — the file is transpiled and imported as
 * plain ESM, so it must stay IMPORT-FREE as well.
 *
 * THE CELL FUNCTIONS ARE GONE (E4 task 5). `cellOf`, `clampToCell`,
 * `splitDiagonal`, `stepDirection`, `keepAhead` and `EDGE_MARGIN` were the
 * step machine of the grid world: the figure was held inside its cell until
 * the server granted the crossing. The metre world has no cells and no
 * per-boundary permission — the client walks freely and REPORTS where it
 * stands (`POST /play/pos`), and what stops the figure is geometry:
 * `game/collide.ts` for walls inside an open interior, `slideBlocked` below
 * for impassable terrain and foreign footprints outdoors.
 */

/** A point on the world plane, in METRES. The one shape every walking
 *  function here speaks; `THREE.Vector3` is the renderer's business. */
export interface Point { x: number; z: number }

/** Is that world point off limits for the walking figure? Supplied by
 *  `main.ts`, which knows the terrain areas (impassable kinds) and the
 *  footprints of the locations the avatar is not in. */
export type BlockedFn = (x: number, z: number) => boolean;

/**
 * Camera-relative walk direction (unit length) from the held keys, or null
 * when nothing is pressed or opposite keys cancel out.
 *
 * Uses the SAME basis as the engine's camera pan: forward
 * `(-sin yaw, 0, -cos yaw)`, right `(-fwd.z, 0, fwd.x)`. If these ever
 * disagree, "forward" means two different things on one screen.
 */
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

/**
 * Hold a step out of blocked ground, sliding ALONG the boundary instead of
 * stopping dead.
 *
 * The ideal is the tangent projection: the part of the movement that runs
 * along the boundary survives, the part that runs into it is dropped. What
 * this does is the documented simplification of that (plan task 5, "simple
 * per-axis fallback is acceptable"): the two axes are the two tangents an
 * axis-aligned obstacle can offer, and the boundaries out here are exactly
 * that kind — the edges of terrain polygons and of footprint squares.
 *
 *  1. the full step, if its target is free;
 *  2. otherwise the LARGER of the two axis components alone (deterministic:
 *     ties go to x) — a figure walking mostly north into a wall on its east
 *     keeps going north;
 *  3. otherwise the smaller one alone;
 *  4. otherwise stand still.
 *
 * Only the TARGET point is asked about, never the way there. A step is at
 * most `WALK_SPEED × dt` long (a few centimetres at any sane frame rate),
 * and both blockers are areas metres across — a step cannot jump one.
 */
export function slideBlocked(from: Point, to: Point, blocked: BlockedFn): Point {
  if (!blocked(to.x, to.z)) return to;
  const dx = to.x - from.x;
  const dz = to.z - from.z;
  const alongX = { x: to.x, z: from.z };
  const alongZ = { x: from.x, z: to.z };
  const first = Math.abs(dx) >= Math.abs(dz) ? alongX : alongZ;
  const second = first === alongX ? alongZ : alongX;
  if ((first === alongX ? dx : dz) !== 0 && !blocked(first.x, first.z)) return first;
  if ((second === alongX ? dx : dz) !== 0 && !blocked(second.x, second.z)) return second;
  return { x: from.x, z: from.z };
}
