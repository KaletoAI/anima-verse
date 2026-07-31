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
 *   - the building CONTOUR is walls too, with a gap punched where a room exit
 *     projects onto it (or one central door in the southernmost piece), so
 *     "out of the building only through the door" needs no extra rule either.
 *
 * So: everything left in `walls` blocks, the gaps are the doors. There is
 * deliberately NO vertical filter (`base_y`/`height` are ignored) — the only
 * entries that sit above head height are window heads, and a window blocks
 * anyway through its own sill and pane.
 *
 * Collision applies INSIDE the interior view only. Crossing a location border
 * outdoors stays what it was: the cell logic in `main.ts` plus the server's
 * step permission.
 */

import type { ScenePayload } from '../api';

/** Half width of the walking body, in FIGURE metres — multiply by the scene's
 *  `k` to get world metres (`bodyRadius`). 0.25 m is a grown figure's shoulder
 *  half width against the 1.70 m the payload scales figures to (§ A3), and it
 *  is the same number `walk.ts` uses as `EDGE_MARGIN` to hold a figure inside
 *  its cell — one body width, one constant, two boundaries. */
export const BODY_RADIUS_M = 0.25;

/** How much wider than drawn a doorway collides, in FIGURE metres (× k).
 *  The gap in the payload is exactly as wide as the visible door, so a figure
 *  of radius r would have to thread r of clearance past each cheek; brushing
 *  one of them reads as "stuck in the frame" — the worst kind of stuck,
 *  because the door is plainly open on screen. 0.12 m per cheek widens a 1.00
 *  m door to 1.24 m of collision, which is under half a body width of slack:
 *  enough to never catch, far too little to slip past a wall end. */
export const DOOR_EASE_M = 0.12;

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
 * The blocking wall lines of ONE storey, with the door gaps already widened.
 *
 * Everything the payload lists for `level` becomes a segment; the only work
 * done here is the ease: a wall end that no OTHER wall end meets is a doorway
 * cheek (or the free end of a stub), and it is pulled back by
 * `DOOR_EASE_M * k`. Corners and the sill/head/glass joints of a window share
 * their endpoints, so they keep their full length.
 */
export function wallSegments(payload: ScenePayload | null | undefined,
  level: number): Segment[] {
  const walls = payload?.walls ?? [];
  const raw: Segment[] = [];
  for (const w of walls) {
    if (!w || w.level !== level) continue;
    const seg = { ax: w.from[0], az: w.from[1], bx: w.to[0], bz: w.to[1] };
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

/** Do the two closed segments touch or intersect? Plain orientation test —
 *  collinear overlap counts as a crossing, which is what we want: a move that
 *  runs ALONG the inside of a wall must not be read as free. */
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
    return Math.max(0, Math.min(t0, t1)) <= Math.min(1, Math.max(t0, t1)) + EPS;
  }
  const t = cross(qpx, qpz, sx, sz) / denom;
  const u = cross(qpx, qpz, rx, rz) / denom;
  return t >= -EPS && t <= 1 + EPS && u >= -EPS && u <= 1 + EPS;
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

/**
 * Clamp a steering goal so the way there crosses no wall.
 *
 * Same shape as the cell-boundary clamp in `walk.ts`: the figure does not stop
 * dead at a wall, it SLIDES — the component of the move parallel to the wall
 * survives, only the component into it is dropped. Three stages:
 *
 *  1. Tunnel guard. A goal on the far side of a wall is projected onto that
 *     wall's direction. Done twice, so a slide that runs into a second wall
 *     (a corner) is caught as well.
 *  2. Push-out. Whatever is left is pushed out of every wall's capsule until
 *     it stands `radius` clear. Repeated a few times so a corner settles.
 *  3. Last word. If the pushing shoved the goal through a wall after all
 *     (a corner, a gap thinner than the body), the figure stands still — a
 *     stopped avatar is recoverable, one outside the building is not.
 *
 * `from` is the figure's current position and is assumed wall-legal; it stays
 * that way because the goal never gets closer than `radius` to a wall.
 */
export function clampAgainstWalls(from: Point, to: Point,
  segments: readonly Segment[], radius: number): Point {
  if (!segments.length) return { x: to.x, z: to.z };
  let p: Point = { x: to.x, z: to.z };

  for (let pass = 0; pass < 2; pass += 1) {
    const hit = firstCrossed(from, p, segments);
    if (!hit) break;
    p = slideAlong(from, p, hit);
  }

  for (let pass = 0; pass < 3; pass += 1) {
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
        // Dead on the wall line: push towards the side the figure is on.
        const ux = s.bx - s.ax;
        const uz = s.bz - s.az;
        const len = Math.hypot(ux, uz) || 1;
        nx = uz / len;
        nz = -ux / len;
        if ((from.x - c.x) * nx + (from.z - c.z) * nz < 0) { nx = -nx; nz = -nz; }
      }
      p = { x: c.x + nx * radius, z: c.z + nz * radius };
      moved = true;
    }
    if (!moved) break;
  }

  if (firstCrossed(from, p, segments)) return { x: from.x, z: from.z };
  return p;
}
