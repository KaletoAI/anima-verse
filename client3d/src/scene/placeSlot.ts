/**
 * PLACES on the client (plan-posen-plaetze.md § 4): what the scene payload's
 * `markers[]` become on a tile, and the ONE rule that turns a seat the
 * SERVER assigned (`MapCharacter.place`) into the point the figure stands on.
 *
 * The client chooses nothing here. Which place a character holds and which
 * of its slots is the server's word (it rides in the worldmap row); the
 * slot points themselves are the payload's `slots[]`, composed by the
 * server's own slot formula. Numbers: client3d/scripts/smoke_places_client.mjs.
 */
import type * as THREE from 'three';

/** One place of a room, keyed by its marker id in `tile.roomMarkers`. */
export interface PlaceEntry {
  /** The slot points in WORLD metres, one per unit of capacity, at the
   *  figure-root height (surface − `drop`, plus the terrain lift). Re-lifted
   *  IN PLACE by `deriveRoomSpots` / `reliftScene` — a seat is never copied
   *  out of here, so a held reference follows the ground. */
  slots: THREE.Vector3[];
  /** The place type — the pose vocabulary this marker speaks. */
  group: string;
  /** Facing in degrees, tile-local like every payload angle. */
  rotation?: number;
  /** Lean out of the upright (degrees): head up/down, sideways. */
  tilt?: number;
  roll?: number;
  /** How far the figure root sits BELOW the marked surface (world metres,
   *  the payload's `root_offset`) — subtracted again on every re-derivation
   *  against the sampled floor. */
  drop: number;
  /** The marker's own lift over the storey datum (`y_world − datum`); a
   *  room marker is re-derived from the room's floor plus this. */
  offsetY: number;
  /** Composed and finished (a prop marker): the floor sampling leaves its
   *  height alone; only the terrain re-lift moves it. */
  fixed?: boolean;
  /** Storey of the room — only 0 is carried by the terrain. */
  level: number;
  /** The storey-0 terrain lift already baked into the slot heights. */
  lift: number;
  /** WHERE that lift is sampled, in WORLD metres (`markerLiftPoint` turned
   *  into the world at mount time). For a PROP marker that is its
   *  placement's anchor — the very point the prop mesh itself is lifted at
   *  (§ A16.9), so the bench and every seat on it rise by the same amount on
   *  a slope; for a room marker it is the marker's own point. The MOUNT and
   *  the RE-LIFT (`reliftScene`) both sample here, which is also what stops
   *  the two from disagreeing on a bench of capacity > 1. */
  liftAt: { x: number; z: number };
  /** PROP MARKERS ONLY: the placement's anchor as the payload states it
   *  (`markers[].anchor`, TILE-LOCAL metres) — the link to the mesh, whose
   *  `models[]` spec carries the identical `anchor`. That is how a click on
   *  the prop finds the places on it. */
  anchor?: [number, number];
}

/** The point a held place puts the figure on: a numbered slot is that slot
 *  (the entry's OWN vector — a re-lift reaches it without a copy; callers
 *  `clone()`), an index out of range (the capacity shrank under the sitter)
 *  falls back to slot 0, and a PAIR sits on the place's CENTRE — the mean
 *  of the slots, the server's `centre_of` and the pair's anchor (a fresh
 *  vector). `undefined` for an entry without slots: total, never a throw. */
export function slotFor(entry: PlaceEntry, slot: number | 'pair'): THREE.Vector3 | undefined {
  const slots = entry.slots;
  if (!slots.length) return undefined;
  if (slot === 'pair') {
    const c = slots[0].clone();
    for (let i = 1; i < slots.length; i++) c.add(slots[i]);
    return c.multiplyScalar(1 / slots.length);
  }
  return slots[slot >= 0 && slot < slots.length ? slot : 0];
}
