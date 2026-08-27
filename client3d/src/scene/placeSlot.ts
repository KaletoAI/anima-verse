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
}

/** The slot a held place puts the figure on: a pair sits on the anchor (slot
 *  0), an index out of range (capacity shrank under the sitter) too. */
export function slotFor(entry: PlaceEntry, slot: number | 'pair'): THREE.Vector3 {
  const i = typeof slot === 'number' && slot >= 0 && slot < entry.slots.length ? slot : 0;
  return entry.slots[i];
}
