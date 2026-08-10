/**
 * WHERE a worldmap figure is drawn, and WHETHER it walks there
 * (E4 acceptance findings B2 + B5).
 *
 * Two decisions that used to sit inline in `computeNpcStates` and were both
 * wrong for the same reason — they read one state and answered two questions:
 *
 *  - `placementOf` (B2): "no tile" was taken as "not on the map", so a
 *    character standing in the WILDERNESS (`location_id: ""`, a legal state
 *    since E1) fell out of the figure list and `npcs.update` removed its
 *    figure — the player's own included. A free point IS a place to stand.
 *  - `figureTransition` (B5): `shownRoom` mixed "the view is closed" with
 *    "outdoors", so OPENING a detail view looked like a room change and the
 *    figure walked in from the outside huddle spot through the front door,
 *    although the game state had it inside all along.
 *
 * PURE like `walk.ts`, `doors.ts` and `minimap.ts`: no `three`, no DOM, no
 * module state and no value import — that is what lets
 * `client3d/scripts/smoke_walk_math.mjs` derive every case by hand.
 */

/** A metre point on the ground plane — the worldmap's `pos` shape. */
export interface FreePoint {
  x: number;
  z: number;
}

/**
 * How a NON-travelling character is placed.
 *
 * `tile` = the location placement decides (room spot, marker or the huddle in
 * front of the building); `free` = a standing figure at that world point;
 * `offmap` = nothing to draw at all.
 */
export type Placement =
  | { kind: 'tile' }
  | { kind: 'free'; pos: FreePoint }
  | { kind: 'offmap' };

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/**
 * The placement of a character that is not on a journey.
 *
 * @param hasTile whether the client has BUILT a tile for its `location_id`
 *                (`tiles.has`) — the location placement needs one, and a
 *                location that is only known but not yet mounted has none.
 * @param pos     the payload's free metre point, or null/absent.
 *
 * A character with a tile is placed by that tile — its `pos` is the same
 * information in a coarser form. Without one, the point is the whole answer:
 * out in the open (no location at all) it is the ONLY answer, and for a
 * character whose location has not been mounted yet it is a better one than
 * dropping the figure for a poll or two.
 */
export function placementOf(hasTile: boolean,
                            pos: FreePoint | null | undefined): Placement {
  if (hasTile) return { kind: 'tile' };
  if (pos && finite(pos.x) && finite(pos.z)) return { kind: 'free', pos: { x: pos.x, z: pos.z } };
  return { kind: 'offmap' };
}

/** What a figure was doing the last time it was placed. `room` null = it stood
 *  on the ground; `interiorShown` says whether the location's inside was
 *  REVEALED at that moment (open detail view, or an always-visible room). */
export interface ShownPlacement {
  room: string | null;
  interiorShown: boolean;
}

/**
 * What the figure has to do to get from `prev` to `next`.
 *
 *  - `snap`   put it there, no walk. A VISIBILITY change (the detail view
 *             opened or closed, an always-visible room appeared) is not a
 *             move: the character stood where it stands before and after, only
 *             the client could not draw it there. Same for the very first
 *             placement — a figure has no previous spot to walk from.
 *  - `route`  a real room change with the view state unchanged: walk it
 *             through the DOOR (`doorwayBetween`/`roomDoor`), which includes
 *             room ↔ ground inside an open interior.
 *  - `stay`   nothing changed; whatever the figure is doing keeps running.
 */
export type FigureTransition = 'snap' | 'route' | 'stay';

export function figureTransition(prev: ShownPlacement | null | undefined,
                                 next: ShownPlacement): FigureTransition {
  if (!prev) return 'snap';
  if (prev.interiorShown !== next.interiorShown) return 'snap';
  if (prev.room !== next.room) return 'route';
  return 'stay';
}
