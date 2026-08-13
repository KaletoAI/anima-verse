/**
 * Pure walking maths of the embodied mode — FREE WALKING since E4 task 5.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM. That is what makes `client3d/scripts/smoke_walk_math.mjs` able to
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
/**
 * Does PAINTED GROUND stop the figure at that point? The client's half of
 * the server rule of `POST /play/pos` (§ A15), pulled out of `main.ts` so it
 * can be checked by hand instead of only being read.
 *
 * FOOTPRINT WINS (decision 2026-08-13). Terrain judges the WILDERNESS, never
 * the inside of a placed location: the server derives the location of the
 * reported point FIRST and asks `passability_at` only for
 * `location_id == ""`. A place is put ON the world and does not inherit the
 * ground somebody painted under it — a hall on a rock plateau is a place one
 * can stand in, and E8 levels the heightmap under a footprint for exactly
 * that reason. Who may go IN is decided elsewhere (openings, rules — the
 * foreign-footprint half of `main.ts` `blockedFor`); this predicate never
 * had anything to say about it.
 *
 * `passable` is the terrain answer at the point (`ground.passableAt`),
 * `insideFootprint` whether ANY placed footprint covers it (`main.ts`
 * `tileAt(x, z) !== null`) — the avatar's own as much as a foreign one.
 * Both are lookups, which is why they are the caller's job and not this
 * file's: what is derivable is the RULE, and the rule is that a footprint
 * point is never refused for its ground.
 *
 * ONLY THE REFUSAL is a wilderness question. How FAST that ground is walked
 * and WITH WHICH CLIP counts everywhere — see `terrainPace` and `moveClip`
 * below (finding 3).
 */
export function terrainBlocks(passable: boolean, insideFootprint: boolean
): boolean {
  return !insideFootprint && !passable;
}

/** Lowest pace a ground may actually impose on the walking figure.
 *
 *  A pace multiplies the walking LEAD, and the lead is what the stall
 *  detection of `game/clickmove.walkStalled` measures: below
 *  `STALL_STEP_M` = 0.01 m a frame counts as "got nowhere" and a click order
 *  is dropped after a few of them. A 60 fps frame walks 3.4/60 = 0.0567 m, so
 *  a quarter of it is 0.0142 m — still a real step. Anything slower would be
 *  a ground one cannot walk a click route over, which is a wall pretending to
 *  be mud; the server's own clamp sits lower (0.1, `terrain_query
 *  .MIN_SPEED_FACTOR`) because it guards a COST against infinity, not a
 *  frame against a threshold. */
export const MIN_PACE = 0.25;

/**
 * How fast the figure walks on that ground — the client's half of the pace
 * rule of `terrain_query.effective_speed_factor` (finding 3 of the E8
 * acceptance, 2026-08-13).
 *
 * THE TOPMOST TERRAIN'S FACTOR COUNTS EVERYWHERE, inside a placed footprint
 * as much as out in the wilderness: painted water slows a walker down in a
 * village on a lake exactly as it does outside it, and painting the ground of
 * a place is how one says so. Only the PASSABILITY is a wilderness question
 * (`terrainBlocks`).
 *
 * The one footprint exception is a factor of 0: that is not a pace but a
 * "this ground was never meant to be walked" (rock), and there the plate
 * really does replace the ground — at the neutral 1. Everything else is
 * clamped up to `MIN_PACE`.
 *
 * `speedFactor` is the caller's lookup (`ground.typeAt(x, z).speed_factor`),
 * `insideFootprint` whether ANY placed footprint covers the point (`main.ts`
 * `tileAt(x, z) !== null`) — what is derivable is the RULE, and only the rule
 * lives in this import-free file.
 */
export function terrainPace(speedFactor: number, insideFootprint: boolean
): number {
  // A world whose catalog hands out nonsense walks at the normal pace rather
  // than at NaN — one NaN in the lead and the figure never moves again.
  if (!Number.isFinite(speedFactor)) return 1;
  if (insideFootprint && speedFactor <= 0) return 1;
  return Math.max(speedFactor, MIN_PACE);
}

/**
 * WHICH CLIP a moving figure plays — the animation half of the same rule.
 *
 * A ground may name the clip one moves over it with (`meta.move_anim`, § A9 —
 * `swim` on water). It replaces walk AND run: a figure crossing a lake does
 * not sprint through it, and there is no second speed of swimming to choose
 * from. Without one the old pair stands, run past `RUN_DISTANCE` and walk
 * below it.
 *
 * The clip kind goes into the open vocabulary of `Figure.play` unchecked —
 * a kind no model carries falls back through `figures.CLIP_FALLBACK` (swim →
 * walk) and finally to idle, which is the same road every other kind takes.
 * STANDING is untouched by this: an activity clip or the server's own
 * `animation` wins there, and this function is never asked.
 */
export function moveClip(moveAnim: string, running: boolean): string {
  const kind = (moveAnim || '').trim();
  if (kind) return kind;
  return running ? 'run' : 'walk';
}

/** Below this horizontal distance a height change counts as a STEP, above it
 *  as a SLOPE (metres) — the mirror of `STEP_DISTANCE_M` in
 *  `app/core/relief.py`. One metre is the scale of a position report itself,
 *  which is what makes it the line between "one has to climb that" and "one
 *  walks up that". */
export const STEP_DISTANCE_M = 1;

/**
 * Does a height change of `dh` over `dist` metres stop the figure? The
 * client's half of the E8 height gate of `POST /play/pos` (§ A15), and the
 * exact mirror of `relief.slope_blocks` on the server.
 *
 * THE TWO LIMITS APPLY TOGETHER, and the step is the ADDITIONAL one:
 *
 *   - the SLOPE limit holds at EVERY distance: blocked when
 *     `atan(|dh| / dist) > maxSlope` degrees;
 *   - BELOW `STEP_DISTANCE_M` the step limit holds on top: blocked when
 *     `|dh| > maxStep`, however gentle the angle would call it.
 *
 * It was an either/or once, and that broke this mirror in particular (review
 * 2026-08-13): the client tests a walking LEAD of ~0.15 m while the server
 * tests a REPORT step of ~1.12 m, so with an either/or the whole band from
 * `maxSlope` up to the angle the same rise makes over a lead — 40° to 69° at
 * the defaults — was invisible here and refused there. The figure walked on
 * while the server snapped it back three times a second. (It also made every
 * slope climbable by crawling: 0.1 m per report turns a 76° wall into a legal
 * "step".)
 *
 * Direction does not matter — dropping off a cliff is as impossible as
 * climbing it, and a walker allowed down where it cannot come back up is a
 * walker one can strand. Level ground never blocks, which is what keeps the
 * whole gate inert in a world without relief.
 *
 * `dh` is the caller's lookup (`main.ts` `reliefLiftAt` at both points),
 * `maxStep`/`maxSlope` the world settings off the worldmap payload — what is
 * derivable is the RULE, and only the rule lives in this import-free file.
 */
export function slopeBlocks(dh: number, dist: number, maxStep: number,
                            maxSlope: number): boolean {
  const rise = Math.abs(dh);
  if (!rise) return false;
  return (dist < STEP_DISTANCE_M && rise > maxStep)
    || Math.atan2(rise, dist) * 180 / Math.PI > maxSlope;
}

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
