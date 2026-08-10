/**
 * Wall collision for the player-steered figure (plan-3d-game stage 3,
 * acceptance finding "the avatar walks through walls indoors").
 *
 * Pure maths, exactly like `walk.ts`: no Three.js, no module state, no DOM,
 * and no value import at all — the only import is a TYPE, which the transpile
 * in `scripts/smoke_walk_math.mjs` drops, so the file can be imported there as
 * plain ESM and checked with hand-derived numbers.
 *
 * WHERE THE GEOMETRY COMES FROM. Not from this file and not from the renderer:
 * the scene payload (`docs/schnittstellen-3d.md` § B1) already carries every
 * wall as a finished primitive in world metres —
 *   walls: [{ level, from: [x,z], to: [x,z], base_y, height, thickness,
 *             glass?, room_id?, outward_normal }]
 * — and the server has ALREADY split each wall around its openings
 * (`app/core/scene_recipe.py`, `_room_walls` / `_contour_walls`). That split is
 * what makes "doors let you through, windows do not" free of any opening
 * lookup here:
 *
 *   - a DOOR or PASSAGE leaves a full-height GAP: the payload contains no
 *     wall entry over its span at all;
 *   - a WINDOW keeps a sill piece below it, a head piece above it and fills
 *     the hole with a glass pane — three entries that all span the opening;
 *   - the building CONTOUR is walls too, with a gap punched where an outside
 *     doorway projects onto it, so
 *     "out of the building only through the door" needs no extra rule either.
 *
 * So: everything left in `walls` blocks, the gaps are the doors. There is
 * deliberately NO vertical filter (`base_y`/`height` are ignored) — the only
 * entries that sit above head height are window heads, and a window blocks
 * anyway through its own sill and pane.
 *
 * Collision applies INSIDE the interior view only. Outdoors the figure walks
 * freely over the metre plane (E4 task 5): `walk.slideBlocked` holds it out of
 * impassable terrain and foreign footprints, and the server judges the
 * reported point (`POST /play/pos`) — there is no per-boundary permission any
 * more.
 */

import type { ScenePayload } from '../api';

/** Half width of the walking body, in FIGURE metres — which since E4 are world
 *  metres, because `k` is the constant 1 (§ B). The `k` factor is still
 *  threaded through `bodyRadius`/`wallSegments` as the no-op it now is, pinned
 *  as such by the hand-derived cases in `scripts/smoke_walk_math.mjs`. 0.25 m
 *  is a grown figure's shoulder half width against the 1.70 m the payload
 *  scales figures to (§ A3); it was also `walk.EDGE_MARGIN`, which went with
 *  the step machine (E4 task 5), so the body width is now one constant for one
 *  boundary: the wall. */
export const BODY_RADIUS_M = 0.25;

/** How much wider than drawn a doorway collides, in FIGURE metres (× k).
 *  The gap in the payload is exactly as wide as the visible door, so a figure
 *  of radius r would have to thread r of clearance past each cheek; brushing
 *  one of them reads as "stuck in the frame" — the worst kind of stuck,
 *  because the door is plainly open on screen. 0.12 m per cheek widens a 1.00
 *  m door to 1.24 m of collision, which is under half a body width of slack:
 *  enough to never catch, far too little to slip past a wall end. */
export const DOOR_EASE_M = 0.12;

/** Slack of the clearance guarantee (world metres) — floating-point noise
 *  only, well below anything the payload can express. */
const CLEAR_TOL = 1e-6;

/** Two wall ends this close together count as ONE joint (world metres). The
 *  payload rounds its coordinates to 4 decimals and a contour piece meets a
 *  room hull through a projection, so exact equality is not available; a
 *  centimetre is orders of magnitude above that error and orders of magnitude
 *  below any real gap. */
const JOINT_TOL = 0.01;

/** Never eat more than this share of a wall piece per end — a short stub
 *  between two openings must not collapse into nothing. */
const MAX_EASE_SHARE = 0.4;

const EPS = 1e-9;

export interface Point { x: number; z: number }

/** A wall reduced to what collision needs: a line in the world XZ plane. */
export interface Segment { ax: number; az: number; bx: number; bz: number }

/** Body radius in WORLD metres for a scene drawn at scale `k`. Indoors a world
 *  metre is not a figure metre (Willowbrook runs at k = 0.21), so an unscaled
 *  radius would be five body widths wide and wedge the figure in its own
 *  room. */
export function bodyRadius(k: number): number {
  return BODY_RADIUS_M * (Number.isFinite(k) && k > 0 ? k : 1);
}

/**
 * The blocking wall lines of ONE storey, in WORLD coordinates, with the door
 * gaps already widened.
 *
 * The payload is tile-LOCAL — `scene_recipe._w()` yields metres around the
 * centre of the tile — while the positions the clamp is compared against come
 * from `npcs.positionOf()` and are absolute. Something has to bridge the two,
 * or the segments of a building 45 m away block nothing (the collision round's
 * C1 finding).
 *
 * `origin` is that bridge as a plain OFFSET, and since E4 the 3D client no
 * longer uses it: a footprint may stand TURNED (§ A1.1) and a turn is not an
 * offset, so the caller asks in the tile frame (`origin` 0/0) and puts both
 * ends of every segment through `tileToWorld` itself. A line has to be turned
 * end by end — which is precisely why it cannot be done here, where only one
 * point at a time is in hand.
 *
 * Apart from the offset the only work done here is the ease: a wall end that
 * no OTHER wall end meets is pulled back by `DOOR_EASE_M * k`. That is a
 * FREE END, not literally a door — a doorway cheek is the case it exists for,
 * but a wall stub that simply ends in the room (and, in a payload with a
 * single wall on a storey, both of its corners) is treated the same. Corners
 * of a closed hull and the sill/head/glass joints of a window share their
 * endpoints and keep their full length.
 */
export function wallSegments(payload: ScenePayload | null | undefined,
  level: number, origin: Point = { x: 0, z: 0 }): Segment[] {
  const walls = payload?.walls ?? [];
  const raw: Segment[] = [];
  for (const w of walls) {
    if (!w || w.level !== level) continue;
    const seg = { ax: origin.x + w.from[0], az: origin.z + w.from[1],
                  bx: origin.x + w.to[0], bz: origin.z + w.to[1] };
    if (!Number.isFinite(seg.ax) || !Number.isFinite(seg.az)
      || !Number.isFinite(seg.bx) || !Number.isFinite(seg.bz)) continue;
    if (Math.hypot(seg.bx - seg.ax, seg.bz - seg.az) < EPS) continue;
    raw.push(seg);
  }
  const ease = DOOR_EASE_M * (Number.isFinite(payload?.k as number)
    && (payload?.k as number) > 0 ? payload!.k : 1);
  const ends: Point[] = [];
  for (const s of raw) {
    ends.push({ x: s.ax, z: s.az });
    ends.push({ x: s.bx, z: s.bz });
  }
  /** How many wall ends sit on this point — 1 = only its own, so it is free. */
  const shared = (x: number, z: number) =>
    ends.filter((e) => Math.hypot(e.x - x, e.z - z) <= JOINT_TOL).length > 1;

  return raw.map((s) => {
    const dx = s.bx - s.ax;
    const dz = s.bz - s.az;
    const len = Math.hypot(dx, dz);
    const cut = Math.min(ease, len * MAX_EASE_SHARE);
    const ux = dx / len;
    const uz = dz / len;
    const a = shared(s.ax, s.az) ? 0 : cut;
    const b = shared(s.bx, s.bz) ? 0 : cut;
    return {
      ax: s.ax + ux * a, az: s.az + uz * a,
      bx: s.bx - ux * b, bz: s.bz - uz * b,
    };
  });
}

/** Point of `s` closest to `p`. */
function closestOn(p: Point, s: Segment): Point {
  const dx = s.bx - s.ax;
  const dz = s.bz - s.az;
  const len2 = dx * dx + dz * dz;
  if (len2 < EPS) return { x: s.ax, z: s.az };
  let t = ((p.x - s.ax) * dx + (p.z - s.az) * dz) / len2;
  t = Math.min(1, Math.max(0, t));
  return { x: s.ax + dx * t, z: s.az + dz * t };
}

const cross = (ax: number, az: number, bx: number, bz: number) => ax * bz - az * bx;

/**
 * Does the move `p0 -> p1` run into `s`? Plain orientation test; a collinear
 * overlap counts too, so a move that runs ALONG the inside of a wall is not
 * read as free.
 *
 * Contact exactly AT `p0` does not count. `p0` is where the figure already
 * stands, and it can stand on a wall line after a server-side put-back — if
 * that touch counted, every direction would be a crossing and the figure
 * would be frozen there for good. Only what lies BEYOND its own position
 * blocks it.
 */
function segmentsCross(p0: Point, p1: Point, s: Segment): boolean {
  const rx = p1.x - p0.x;
  const rz = p1.z - p0.z;
  const sx = s.bx - s.ax;
  const sz = s.bz - s.az;
  const denom = cross(rx, rz, sx, sz);
  const qpx = s.ax - p0.x;
  const qpz = s.az - p0.z;
  if (Math.abs(denom) < EPS) {
    // Parallel: only a collinear overlap can touch.
    if (Math.abs(cross(qpx, qpz, rx, rz)) > EPS) return false;
    const r2 = rx * rx + rz * rz;
    if (r2 < EPS) return false;
    const t0 = (qpx * rx + qpz * rz) / r2;
    const t1 = t0 + (sx * rx + sz * rz) / r2;
    const lo = Math.max(0, Math.min(t0, t1));
    const hi = Math.min(1, Math.max(t0, t1));
    return hi > EPS && lo <= hi + EPS;
  }
  const t = cross(qpx, qpz, sx, sz) / denom;
  const u = cross(qpx, qpz, rx, rz) / denom;
  return t > EPS && t <= 1 + EPS && u >= -EPS && u <= 1 + EPS;
}

/** First segment the straight move `from -> to` runs into, or null. */
function firstCrossed(from: Point, to: Point, segments: readonly Segment[]
): Segment | null {
  if (Math.hypot(to.x - from.x, to.z - from.z) < EPS) return null;
  for (const s of segments) if (segmentsCross(from, to, s)) return s;
  return null;
}

/** Keep only the part of the move that runs ALONG `s`. */
function slideAlong(from: Point, to: Point, s: Segment): Point {
  const dx = s.bx - s.ax;
  const dz = s.bz - s.az;
  const len = Math.hypot(dx, dz);
  if (len < EPS) return { x: from.x, z: from.z };
  const ux = dx / len;
  const uz = dz / len;
  const along = (to.x - from.x) * ux + (to.z - from.z) * uz;
  return { x: from.x + ux * along, z: from.z + uz * along };
}

/** Distance of a point to the nearest wall line. */
function minDistance(p: Point, segments: readonly Segment[]): number {
  let best = Infinity;
  for (const s of segments) {
    const c = closestOn(p, s);
    best = Math.min(best, Math.hypot(p.x - c.x, p.z - c.z));
  }
  return best;
}

/**
 * Push a point out of every wall capsule until it stands `radius` clear.
 *
 * An ITERATION, not a solution: between two walls closer together than twice
 * the radius it cannot converge and just ping-pongs, which is why the caller
 * checks the result instead of trusting it. `hint` decides the side when the
 * point sits exactly ON a wall line, where no side information exists.
 */
function pushOut(start: Point, segments: readonly Segment[], radius: number,
  hint: Point): Point {
  let p = start;
  for (let pass = 0; pass < PUSH_PASSES; pass += 1) {
    let moved = false;
    for (const s of segments) {
      const c = closestOn(p, s);
      const dx = p.x - c.x;
      const dz = p.z - c.z;
      const d = Math.hypot(dx, dz);
      if (d >= radius - EPS) continue;
      let nx: number;
      let nz: number;
      if (d > EPS) {
        nx = dx / d;
        nz = dz / d;
      } else {
        const ux = s.bx - s.ax;
        const uz = s.bz - s.az;
        const len = Math.hypot(ux, uz) || 1;
        nx = uz / len;
        nz = -ux / len;
        if ((hint.x - c.x) * nx + (hint.z - c.z) * nz < 0) { nx = -nx; nz = -nz; }
      }
      p = { x: c.x + nx * radius, z: c.z + nz * radius };
      moved = true;
    }
    if (!moved) break;
  }
  return p;
}

/** How often the push-out may go round. Enough for a corner (two walls settle
 *  in two), bounded because a corridor narrower than the body never settles. */
const PUSH_PASSES = 8;

/**
 * Clamp a steering goal so the way there crosses no wall.
 *
 * Same shape as the outdoor slide in `walk.slideBlocked`: the figure does not stop
 * dead at a wall, it SLIDES — the component of the move parallel to the wall
 * survives, only the component into it is dropped.
 *
 * THE ORIGIN IS NOT ASSUMED LEGAL. Walking never brings the figure closer to a
 * wall than `radius`, but the server can put it anywhere wall-blind — the
 * put-back after a refused step (`snapPlayerTo`), a teleport, a party pull.
 * So the origin is pushed clear first and everything below is measured from
 * THERE — but that lift is itself a move and is held to the same rules: it
 * may not end closer to a wall than the figure stood and it may not cross
 * one. A `from` sitting exactly ON a wall line is fine either way, because
 * contact at the figure's own position is not a crossing (`segmentsCross`);
 * without that exemption every direction would block and the figure would be
 * frozen there for good.
 *
 * WHAT IS GUARANTEED. Not "`radius` clear of every wall" — that is
 * unreachable in a corridor narrower than the body, and pretending otherwise
 * is how a figure ends up standing 2 mm inside a wall. The promise is
 * relative: the result never crosses a wall on the way, and is never CLOSER
 * to one than the figure already was (capped at `radius`). Three candidates
 * are tried in order — pushed goal, plain slide, the origin itself — and the
 * first that keeps the promise wins. The origin always keeps it, so there is
 * always an answer, and a too-narrow corridor stays walkable instead of
 * freezing.
 */
export function clampAgainstWalls(from: Point, to: Point,
  segments: readonly Segment[], radius: number): Point {
  if (!segments.length) return { x: to.x, z: to.z };

  // The origin, pushed clear — but only if that actually helps. Two ways it
  // does not: in a corridor narrower than the body the push ends up CLOSER
  // than the figure stood, and in a niche it cannot resolve (a room hull and
  // the building contour 0.089 m apart) it ping-pongs straight OVER a wall and
  // would teleport the figure to the far side — out of the building, for the
  // niche that matters. The lift is therefore a move like any other and has to
  // survive the same crossing test; when it does not, the figure keeps its
  // spot, close to the wall, and the candidates below stay conservative.
  const fromClear = minDistance(from, segments);
  const lifted = pushOut(from, segments, radius, to);
  const base = !firstCrossed(from, lifted, segments)
    && minDistance(lifted, segments) >= Math.min(radius, fromClear) - CLEAR_TOL
    ? lifted : from;
  const need = Math.min(radius, minDistance(base, segments));

  // Tunnel guard: a goal on the far side of a wall keeps only its component
  // ALONG that wall. Twice, so a slide into a second wall (a corner) is caught.
  let slid: Point = { x: to.x, z: to.z };
  for (let pass = 0; pass < 2; pass += 1) {
    const hit = firstCrossed(base, slid, segments);
    if (!hit) break;
    slid = slideAlong(base, slid, hit);
  }

  for (const candidate of [pushOut(slid, segments, radius, base), slid, base]) {
    if (firstCrossed(base, candidate, segments)) continue;
    if (minDistance(candidate, segments) < need - CLEAR_TOL) continue;
    return candidate;
  }
  return base;
}
