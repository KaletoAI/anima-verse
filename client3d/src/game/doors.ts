/**
 * The doorways of a scene, ready to draw and ready to walk through.
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
 * this file says where the gaps are, which rooms each joins, and which one
 * leads a figure out of the building. Nothing here draws, and nothing here
 * touches the recipe geometry — the markers are an OVERLAY, like the selection
 * ring and the event pins.
 *
 * IT READS, IT DOES NOT DERIVE (plan-betreten-und-tueren.md § 4.1). The one
 * source is the payload's `doorways[]`: the server cut the wall AND the
 * building hull from it, so it is the same gap, to the millimetre. Gone with
 * the rehang (task B3) is everything this module used to recompute — the edge
 * clamp and `width_m × k` of every room opening, and the building entrance
 * measured BACK out of the contour pieces by hunting for two colinear
 * stretches exactly 0.8 m apart — together with the six constants that only
 * existed to guess a server decision (`CONTOUR_DOOR_M`, `GAP_TOL_M`,
 * `COLINEAR_TOL_M`, `PARALLEL_EPS`, `MERGE_TOL_M`, `MIN_WIDTH_M`). Merging is
 * gone too: one gap is ONE entry, the server dedupes it.
 *
 * COORDINATES. The payload is TILE-LOCAL: world metres around the tile centre,
 * tile rotation already applied. `origin` bakes the tile centre in, the same
 * way `wallSegments` does — the lesson of the collision round, where segments
 * 45 m away blocked nothing.
 */

import type { ScenePayload, SceneDoorway } from '../api';

export interface Point { x: number; z: number }

/** One walk-through gap in the walls of ONE storey — a `doorways[]` entry in
 *  the client's own vocabulary. Every field is the payload's; none is
 *  recomputed. */
export interface DoorMarker {
  /** Centre of the CLEAR opening, in the same frame as `origin` (world when
   *  the tile centre was passed in). */
  mid: Point;
  /** Unit direction of the wall the gap sits in — the threshold runs ALONG
   *  it, its depth across it. */
  along: Point;
  /** Clear width in world metres, already clamped to the wall edge by the
   *  server: a door on a corner really is narrower than it was drawn. */
  width: number;
  /** Foot of the wall the gap belongs to, in payload metres. The floor a
   *  figure walks on may be higher — a sampled diorama floor — so this is the
   *  fallback, not the truth. */
  baseY: number;
  /** The rooms this doorway joins, in payload order: two for a party wall,
   *  one for a door leading outside. `roomIds[0]` owns the wall it was cut
   *  from; the ground room never appears. */
  roomIds: string[];
  /** true = leads out of the building, onto the ground. */
  outside: boolean;
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** A payload entry in the client's frame, or null when it is not usable. */
function marker(d: SceneDoorway | null | undefined, origin: Point): DoorMarker | null {
  if (!d) return null;
  const at = d.at_world;
  const along = d.along;
  if (!Array.isArray(at) || !finite(at[0]) || !finite(at[1])) return null;
  if (!Array.isArray(along) || !finite(along[0]) || !finite(along[1])) return null;
  if (!finite(d.width_m) || d.width_m <= 0) return null;
  return {
    mid: { x: origin.x + at[0], z: origin.z + at[1] },
    along: { x: along[0], z: along[1] },
    width: d.width_m,
    baseY: finite(d.base_y) ? d.base_y : 0,
    roomIds: (d.rooms ?? []).filter((r): r is string => typeof r === 'string' && !!r),
    outside: d.outside === true,
  };
}

const doorwaysOf = (payload: ScenePayload | null | undefined): SceneDoorway[] =>
  (payload?.doorways ?? []);

/**
 * Every doorway of ONE storey, in payload order. `origin` is added to every
 * point (pass the tile centre to get world coordinates); direction, width and
 * base height are offsets and stay untouched by it.
 */
export function doorMarkers(payload: ScenePayload | null | undefined,
  level: number, origin: Point = { x: 0, z: 0 }): DoorMarker[] {
  const out: DoorMarker[] = [];
  for (const d of doorwaysOf(payload)) {
    if (!d || d.level !== level) continue;
    const m = marker(d, origin);
    if (m) out.push(m);
  }
  return out;
}

/**
 * THE door of one room: the one leading outside, else the first one listed.
 *
 * That is the answer the single exit point used to give badly — it was one
 * point per room whatever its doors, and for a room set back from the shell it
 * was not even on a wall. Two consumers ask this: the floor probe of a diorama
 * (`tiles.ts` — a generated mesh has holes in hidden places but not at its
 * door) and the walk that leaves a building for the ground (`main.ts`).
 */
export function roomDoor(payload: ScenePayload | null | undefined,
  roomId: string, origin: Point = { x: 0, z: 0 }): DoorMarker | null {
  if (!roomId) return null;
  let first: SceneDoorway | null = null;
  for (const d of doorwaysOf(payload)) {
    if (!d || !(d.rooms ?? []).includes(roomId)) continue;
    if (d.outside === true) return marker(d, origin);
    first = first ?? d;
  }
  return marker(first, origin);
}

/**
 * The doorway that joins two rooms — the entry whose `rooms` holds both. Null
 * when they share no wall (then a figure walks out of one and into the other,
 * `roomDoor` twice). Two ids of the same room join nothing.
 */
export function doorwayBetween(payload: ScenePayload | null | undefined,
  a: string, b: string, origin: Point = { x: 0, z: 0 }): DoorMarker | null {
  if (!a || !b || a === b) return null;
  for (const d of doorwaysOf(payload)) {
    const rooms = d?.rooms ?? [];
    if (rooms.includes(a) && rooms.includes(b)) return marker(d, origin);
  }
  return null;
}
