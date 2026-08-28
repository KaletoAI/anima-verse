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
 *  - `stay`   the drawn ROOM is the one it was drawn in last time, so nothing
 *             about the placement moved — whatever the figure is doing keeps
 *             running. This is the first question asked, and it is what keeps
 *             a figure walking across the OPEN GROUND from being teleported
 *             onto its spot every time somebody opens a detail view: the view
 *             state of the tile changes, its own placement does not.
 *  - `snap`   put it there, no walk. A VISIBILITY change (the detail view
 *             opened or closed, an always-visible room appeared) is not a
 *             move: the character stood where it stands before and after, only
 *             the client could not draw it there. Same for the very first
 *             placement — a figure has no previous spot to walk from.
 *  - `route`  a real room change with the view state unchanged: walk it
 *             through the DOOR (`doorwayBetween`/`roomDoor`), which includes
 *             room ↔ ground inside an open interior.
 */
export type FigureTransition = 'snap' | 'route' | 'stay';

export function figureTransition(prev: ShownPlacement | null | undefined,
                                 next: ShownPlacement): FigureTransition {
  if (!prev) return 'snap';
  if (prev.room === next.room) return 'stay';
  if (prev.interiorShown !== next.interiorShown) return 'snap';
  return 'route';
}

/**
 * WHERE A PLACE MARKER'S TERRAIN LIFT IS SAMPLED — one prop, one ground
 * (user finding 2026-08-28, the avatar sitting ~40 cm too low on the "Stone
 * bench" above the cliff).
 *
 * A storey-0 placement stands on the ground under its OWN ANCHOR (§ A16.9,
 * `models[].anchor`). The seat marks ON it used to be lifted at the MARKER's
 * own point instead — the anchor plus the marker's offset, decimetres away
 * and, on a slope, at a different height — so the sitter floated over or sank
 * into the bench by exactly the relief between the two points. The prop and
 * everything one sits on it are ONE object and are lifted at ONE point.
 *
 * @param at     the marker's own point (`markers[].at_world`), tile-local
 * @param anchor the placement's anchor (`markers[].anchor`) for a prop
 *               marker; null/absent for a ROOM marker, which has no
 *               placement and keeps its own point. A non-finite anchor is no
 *               anchor — a payload that says nothing must not move a seat to
 *               NaN.
 *
 * Always a fresh point: the caller turns it into the world and must not be
 * able to write back into the payload it came from.
 *
 * PURE, and hand-derived in `client3d/scripts/smoke_place_lift.mjs` [1].
 */
export function markerLiftPoint(at: FreePoint,
                                anchor?: FreePoint | null): FreePoint {
  if (anchor && finite(anchor.x) && finite(anchor.z)) {
    return { x: anchor.x, z: anchor.z };
  }
  return { x: at.x, z: at.z };
}

/**
 * WHETHER A WORLDMAP POLL IS TOO OLD TO SAY ANYTHING ABOUT THE AVATAR'S SEAT
 * (plan-aufstehen.md, plan-posen-plaetze.md § 4).
 *
 * The avatar sits down and stands up WITHOUT waiting for the round trip — the
 * figure walks the moment the key is pressed. A poll asked before the server
 * answered that seat change describes the world before it (the seat just
 * stood up from, no seat where the click has just taken one), and every
 * consumer of the payload has to ignore it wholesale: the place reconcile
 * would snap the figure back into the chair, the position reconcile would
 * walk it back to the chair's point, and the player branch of `npcs.update`
 * would put the seat's `sit` clip back onto a figure that is already walking.
 *
 * @param polledAt   when the poll was ASKED (`performance.now()`).
 * @param ownChangeAt when the server last ANSWERED a seat change of our own:
 *                   `Infinity` while a release is in flight (nothing older
 *                   than "never" can know about it), `0` when none has ever
 *                   been answered — then no poll is ever stale.
 *
 * The same instant is not older, so a poll and an answer that share a
 * millisecond are believed.
 *
 * PURE, and hand-derived in `client3d/scripts/smoke_places_client.mjs` [9].
 */
export function pollIsStale(polledAt: number, ownChangeAt: number): boolean {
  return polledAt < ownChangeAt;
}

/** How much closer a slot has to be to BEAT the leader (metres², i.e. a
 *  micrometre of distance). Without it the documented "a tie falls to the
 *  first entry" would be decided by floating-point noise: two slots 0.7 m
 *  from the hit point differ in the last bit of their squared distance
 *  depending on which side of the hit they lie on. */
const PICK_EPS_M2 = 1e-9;

/** One offered place with the slot points that are FREE, for the pick below.
 *  The points are metres in whatever frame the hit point is measured in
 *  (the client hands in world metres). */
export interface PlacePick {
  id: string;
  free: FreePoint[];
}

/**
 * WHICH PLACE A CLICK ON A PROP OPENS (ruling 2026-08-28).
 *
 * Since the prop mesh itself is the click target — rings are left to the
 * places WITHOUT a prop — one hit object may carry several places (a table
 * with four chairs' worth of seats, a bunk with two beds). The hit POINT
 * decides: the place whose nearest FREE slot lies closest to it, so clicking
 * the left end of a bench offers the left end.
 *
 * Plain XZ distance, and a tie falls to the first entry of the list — the
 * order the payload delivered, so two renderers asked the same question
 * answer the same place. A place without a free slot can never win; a list in
 * which nobody has one answers `null` (total, never a throw — the same
 * contract as `slotFor`).
 *
 * PURE, and hand-derived in `client3d/scripts/smoke_place_lift.mjs` [2].
 */
export function pickablePlaceFor(hit: FreePoint,
                                 places: PlacePick[]): string | null {
  let best: string | null = null;
  let bestD = Infinity;
  for (const place of places) {
    for (const p of place.free) {
      const d = (p.x - hit.x) * (p.x - hit.x) + (p.z - hit.z) * (p.z - hit.z);
      if (d < bestD - PICK_EPS_M2) {
        bestD = d;
        best = place.id;
      }
    }
  }
  return best;
}
