/**
 * Where the doorways are (plan-3d-game stage 3, acceptance finding "you
 * cannot see the doors").
 *
 * Pure maths, exactly like `walk.ts` and `collide.ts`: no Three.js, no module
 * state, no DOM, and no value import at all — the only import is a TYPE, which
 * the transpile in `scripts/smoke_walk_math.mjs` drops, so the file can be
 * imported there as plain ESM and checked with hand-derived numbers.
 *
 * WHY THIS FILE EXISTS. The server draws a door as a GAP: it splits every wall
 * around its openings (`app/core/scene_recipe.py`) and emits nothing over the
 * door's span, which is exactly right for walking (`collide.ts` needs no
 * opening lookup at all) and unreadable for looking — a hole between two wall
 * pieces does not say "door". `main.ts` lays a flat threshold into each gap;
 * this file says where the gaps are. Nothing here draws, and nothing here
 * touches the recipe geometry — the markers are an OVERLAY, like the selection
 * ring and the event pins.
 *
 * WHERE THE SPANS COME FROM. Two sources, because neither covers the other:
 *
 *   1. `rooms[].openings` — every gap a ROOM wall leaves. It carries the type,
 *      and the type is what decides: over a WINDOW the server keeps a sill
 *      piece, a head piece and a glass pane, so a window is not a way through
 *      and gets no marker. Everything else (door, passage, any word a future
 *      contract adds — the vocabulary is open) leaves a full-height gap and
 *      does. Only rooms that actually OWN wall entries on that storey count:
 *      an outdoor or `no_walls` room keeps its openings in the payload but
 *      emits no wall at all, so there is no gap in front of it to mark.
 *   2. the CONTOUR gap — the building entrance. `_contour_walls` punches
 *      ±0.4 m around a room exit that projects onto the contour (or one
 *      central door into the southernmost piece when no exit does), and that
 *      hole appears in NO openings list: the room behind it may stand well
 *      inside the shell. Its signature is its size — two colinear contour
 *      pieces exactly 2 × 0.4 = 0.8 m apart.
 *
 * Deliberately NOT a source: `tile.roomExits`. An exit is ONE point per room
 * with neither width nor direction, and a room with two doors has one exit —
 * it answers "where does this room let you in", not "where are the doorways".
 *
 * COORDINATES. The payload is TILE-LOCAL: world metres around the tile centre
 * (`extent_m` turns a plan fraction into metres, never a constant). `origin`
 * bakes the tile centre in, the same way `wallSegments` does — the lesson of
 * the collision round, where segments 45 m away blocked nothing.
 */

import type { ScenePayload } from '../api';

/** Width of the contour's entrance gap in WORLD metres — 2 × `DOOR_HALF_GAP_M`
 *  of `app/core/scene_recipe.py`. A constant there, so a constant here: it is
 *  not scaled by `k`, unlike every opening width in a room wall. */
export const CONTOUR_DOOR_M = 0.8;

/** How far a measured contour gap may be off the 0.8 m and still count. The
 *  payload rounds to 4 decimals and a contour edge may be slightly slanted, so
 *  exactness is not available; 3 cm is far above that noise and far below the
 *  next thing a gap could be (a whole room stretch the contour yielded). */
const GAP_TOL_M = 0.03;

/** Perpendicular distance under which two contour pieces count as pieces of
 *  the SAME contour line. Without it two parallel walls a doorway apart would
 *  grow a door between them. */
const COLINEAR_TOL_M = 0.05;

/** |cross| of two unit directions under which they count as parallel
 *  (≈ 0.06°). */
const PARALLEL_EPS = 1e-3;

/** Two doorways this close together are ONE doorway seen from both sides — a
 *  shared wall carries the neighbour's opening MIRRORED into its own room, so
 *  the same hole arrives twice. Well below any door width, well above the
 *  payload's rounding. The rule scales with the doorway (see `merge`): the
 *  constant is only the floor for a very small one — Willowbrook is drawn at
 *  k = 0.21, where a full door is 0.21 world metres wide. */
const MERGE_TOL_M = 0.05;

/** Below this a "gap" is rounding, not a way through (world metres). */
const MIN_WIDTH_M = 0.05;

const EPS = 1e-9;

export interface Point { x: number; z: number }

/** One walk-through gap in the walls of ONE storey. */
export interface DoorMarker {
  /** Centre of the gap, in the same frame as `origin` (world when the tile
   *  centre was passed in). */
  mid: Point;
  /** Unit direction of the wall the gap sits in — the threshold runs ALONG
   *  it, its depth across it. */
  along: Point;
  /** Clear width in world metres. NOT `width_m`: the server clamps an opening
   *  to its edge, so a door on a corner really is narrower than it was drawn. */
  width: number;
  /** Base height of the wall the gap belongs to, in payload metres (add the
   *  tile's own ground height). The floor a figure walks on may be higher —
   *  a sampled diorama floor — so this is the fallback, not the truth. */
  baseY: number;
  /** The rooms this doorway belongs to, in payload order: one for a room's
   *  outside door, two for a shared wall, none for the contour entrance. */
  roomIds: string[];
}

const sub = (a: Point, b: Point): Point => ({ x: a.x - b.x, z: a.z - b.z });
const dot = (a: Point, b: Point) => a.x * b.x + a.z * b.z;
const cross = (a: Point, b: Point) => a.x * b.z - a.z * b.x;
const len = (a: Point) => Math.hypot(a.x, a.z);

/** Reference-square fraction → payload metre (origin = tile centre) — the
 *  server's `_w`, and the ONE place a fraction becomes a length here. */
const toWorld = (frac: number, extent: number) => (frac - 0.5) * extent;

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/**
 * Every doorway of ONE storey. `origin` is added to every point (pass the
 * tile centre to get world coordinates); direction, width and base height are
 * offsets and stay untouched by it.
 */
export function doorMarkers(payload: ScenePayload | null | undefined,
  level: number, origin: Point = { x: 0, z: 0 }): DoorMarker[] {
  const out: DoorMarker[] = [];
  if (!payload) return out;
  const walls = payload.walls ?? [];
  const extent = finite(payload.extent_m) && payload.extent_m > 0 ? payload.extent_m : 0;
  const k = finite(payload.k) && payload.k > 0 ? payload.k : 1;

  // Which rooms own a wall on this storey, and how high its foot sits. A room
  // without an entry emitted none (outdoor, `no_walls`) — there is no gap in
  // front of it, whatever its openings say.
  const roomBase = new Map<string, number>();
  for (const w of walls) {
    if (!w || w.level !== level || !w.room_id) continue;
    const base = finite(w.base_y) ? w.base_y : 0;
    const seen = roomBase.get(w.room_id);
    if (seen === undefined || base < seen) roomBase.set(w.room_id, base);
  }

  if (extent) {
    for (const room of payload.rooms ?? []) {
      const id = room?.room_id;
      if (!id || room.level !== level) continue;
      const base = roomBase.get(id);
      if (base === undefined) continue;
      const pts: Point[] = [];
      for (const p of room.outline ?? []) {
        if (!Array.isArray(p) || !finite(p[0]) || !finite(p[1])) { pts.length = 0; break; }
        pts.push({ x: toWorld(p[0], extent), z: toWorld(p[1], extent) });
      }
      if (pts.length < 3) continue;
      for (const op of room.openings ?? []) {
        if (!op || String(op.type ?? '').toLowerCase() === 'window') continue;
        const i = Number(op.edge);
        if (!Number.isInteger(i) || i < 0 || i >= pts.length) continue;
        const a = pts[i];
        const b = pts[(i + 1) % pts.length];
        const d = sub(b, a);
        const length = len(d);
        if (length < EPS) continue;
        const u = { x: d.x / length, z: d.z / length };
        // The server's span, to the millimetre (`_room_walls`): the opening is
        // clamped to its own edge, so a door on a corner is a HALF door.
        const half = Math.min((finite(op.width_m) ? op.width_m : 0) * k / 2, length / 2);
        const centre = Math.min(1, Math.max(0, finite(op.at) ? op.at : 0)) * length;
        const s0 = Math.max(0, centre - half);
        const s1 = Math.min(length, centre + half);
        const width = s1 - s0;
        if (width < MIN_WIDTH_M) continue;
        const t = (s0 + s1) / 2;
        out.push({
          mid: { x: origin.x + a.x + u.x * t, z: origin.z + a.z + u.z * t },
          along: u,
          width,
          baseY: base,
          roomIds: [id],
        });
      }
    }
  }

  out.push(...contourDoors(walls, level, origin));
  return merge(out);
}

/** A contour piece reduced to a line with an interval on it. */
interface Piece { a: Point; u: Point; t0: number; t1: number; baseY: number }

/**
 * The entrance gaps of the building contour: holes of exactly
 * `CONTOUR_DOOR_M` between two colinear contour pieces. Contour walls are the
 * ones without a `room_id` — one wall, one owner (§ A6).
 */
function contourDoors(walls: ScenePayload['walls'], level: number,
  origin: Point): DoorMarker[] {
  const pieces: Piece[] = [];
  for (const w of walls ?? []) {
    if (!w || w.level !== level || w.room_id) continue;
    if (!finite(w.from?.[0]) || !finite(w.from?.[1])
      || !finite(w.to?.[0]) || !finite(w.to?.[1])) continue;
    const a = { x: origin.x + w.from[0], z: origin.z + w.from[1] };
    const b = { x: origin.x + w.to[0], z: origin.z + w.to[1] };
    const d = sub(b, a);
    const length = len(d);
    if (length < EPS) continue;
    pieces.push({
      a, u: { x: d.x / length, z: d.z / length }, t0: 0, t1: length,
      baseY: finite(w.base_y) ? w.base_y : 0,
    });
  }
  const out: DoorMarker[] = [];
  for (let i = 0; i < pieces.length; i += 1) {
    for (let j = i + 1; j < pieces.length; j += 1) {
      const p = pieces[i];
      const q = pieces[j];
      if (Math.abs(cross(p.u, q.u)) > PARALLEL_EPS) continue;
      // Both ends of q measured against p's line: along it (t) and across it.
      const qa = sub(q.a, p.a);
      const qb = sub({ x: q.a.x + q.u.x * q.t1, z: q.a.z + q.u.z * q.t1 }, p.a);
      if (Math.abs(cross(p.u, qa)) > COLINEAR_TOL_M
        || Math.abs(cross(p.u, qb)) > COLINEAR_TOL_M) continue;
      const qLo = Math.min(dot(qa, p.u), dot(qb, p.u));
      const qHi = Math.max(dot(qa, p.u), dot(qb, p.u));
      // The gap between the two intervals, whichever piece comes first.
      const gap = qLo >= p.t1 ? { from: p.t1, size: qLo - p.t1 }
        : p.t0 >= qHi ? { from: qHi, size: p.t0 - qHi }
          : null;
      if (!gap || Math.abs(gap.size - CONTOUR_DOOR_M) > GAP_TOL_M) continue;
      const t = gap.from + gap.size / 2;
      out.push({
        mid: { x: p.a.x + p.u.x * t, z: p.a.z + p.u.z * t },
        along: p.u,
        width: gap.size,
        baseY: p.baseY,
        roomIds: [],
      });
    }
  }
  return out;
}

/**
 * One hole, one marker. Three ways the same doorway arrives twice:
 *   - a shared wall carries the neighbour's opening MIRRORED into its own
 *     room, so both rooms describe it;
 *   - the contour entrance is a gap between two pieces and is found from
 *     either of them;
 *   - a room set back from the shell has its OWN outside door AND the
 *     contour gap in front of it (measured at the Bernstein Academy: 0.09 m
 *     apart — one doorway, two holes, and two stacked quads would only look
 *     like a mistake).
 *
 * "The same" scales with the doorway: two gaps closer than half the narrower
 * one are one way through. The WIDER marker wins the geometry — where a wide
 * opening and a narrow one overlap, the wide one is the actual hole, and
 * keeping the narrow one's centre would shift the threshold off it. Room ids
 * accumulate in the order they were found, so the room that owns the floor
 * stays first.
 */
function merge(markers: DoorMarker[]): DoorMarker[] {
  const out: DoorMarker[] = [];
  for (const m of markers) {
    const twin = out.find((o) => Math.hypot(o.mid.x - m.mid.x, o.mid.z - m.mid.z)
      <= Math.max(MERGE_TOL_M, Math.min(o.width, m.width) / 2)
      && Math.abs(cross(o.along, m.along)) <= PARALLEL_EPS);
    if (!twin) {
      out.push(m);
      continue;
    }
    if (m.width > twin.width) {
      twin.mid = m.mid;
      twin.along = m.along;
      twin.width = m.width;
      twin.baseY = m.baseY;
    }
    for (const id of m.roomIds) if (!twin.roomIds.includes(id)) twin.roomIds.push(id);
  }
  return out;
}
