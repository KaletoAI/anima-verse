/**
 * Entering at authored boundary openings — IN METRES since E4 task 5
 * (plan-3d-lod-und-betreten.md Etappe 3; contract § B1 Nr. 13, § A1.3).
 *
 * Pure maths like walk.ts/proximity.ts — the numbers are checked in
 * `client3d/scripts/smoke_enter_math.mjs`. main.ts looks the arguments up
 * (the tiles around the avatar and the openings of their worldmap rows) and
 * renders the offer; the REAL entry stays the server's, and it is not a step
 * any more but the next position report (`POST /play/pos`), which lets the
 * avatar in only within `boundary_entry`-tolerance of an opening world point
 * and only past `accessible_when` + the access rules.
 *
 * WHAT CHANGED WITH THE CELLS. The grid version asked two questions: is the
 * location 4-ADJACENT, and does the crossed EDGE carry an opening — because a
 * step crossed exactly one cell edge and the server judged that edge. Neither
 * question exists on the free plane: there is no adjacency and no crossed
 * edge, only a point and its distance to the openings. So the rule is now the
 * distance alone, which is also what the server measures.
 *
 * `mayLeaveAcross` went with them. Leaving is judged by the server on the
 * report (`boundary_entry.may_leave` with the room the avatar stands in) and
 * answered with `leave_blocked` — the client no longer walks the avatar into
 * the entry room first, because there is no step to prepare any more.
 *
 * WHAT CHANGED WITH THE SQUARE (contract v6 "Gebiete"). Two things, and both
 * take arithmetic OUT of here:
 *
 *  - AN OPENING ARRIVES FINISHED. The worldmap row carries
 *    `locations[].openings` — edge INDEX, world point, world inward normal,
 *    room link — computed by `boundary_entry.opening_world_frames`, the very
 *    function the entry gate measures with. So this module consumes them
 *    VERBATIM: no edge letter, no half-edge formula off `plan_width_m`, no
 *    tile rotation (deleted, v6 Nr. 15), not even a pin to add. The client's
 *    old second source — anchoring the raw `map3d.boundary_openings` itself
 *    for a location whose scene answers 404 — is gone with it: the row answers
 *    for EVERY location, scene or no scene, which is what that mirror existed
 *    to patch over.
 *  - A FREE boundary — no authored opening, so the whole rim is the way in —
 *    is measured against the DRAWN POLYGON (`polygon.nearestRimPoint`) instead
 *    of against the edges of a square that only ever existed as a special case
 *    of it. `openings.length === 0` IS the free-boundary statement now, so the
 *    three-state `freeBoundaryOf` of the scene-cache era is gone too.
 */

import { nearestRimPoint, type Polygon } from './polygon';

/** A point on the world plane, in metres. Same shape as `walk.Point`. */
export interface Point { x: number; z: number }

/** Radius around an authored opening's WORLD POINT within which "Betreten" is
 *  offered, in metres. Deliberately wider than the server's crossing
 *  tolerance (1.5 m, `_POS_OPENING_TOLERANCE_M` in `app/routes/play.py`): the
 *  offer has to appear while one is still walking UP to the opening, and
 *  accepting it walks the figure to the point, where the crossing report is
 *  then well inside the server's window. */
export const ENTER_RADIUS = 3;

/**
 * Tile-local (x, z) → world metres — the contract's own mapping (§ A1.1,
 * `app/core/world_geometry.local_to_world`):
 *
 *     x = cx + lx·cos(yaw) + lz·sin(yaw)
 *     z = cz − lx·sin(yaw) + lz·cos(yaw)
 *
 * `yaw` in RADIANS, the world-map convention (the same sign the tile group is
 * turned by since task 3). This is the pure twin of `scene/tiles.tileToWorld`,
 * which needs a `Tile` and returns a `THREE.Vector3`; the formula lives here
 * because it has to be checkable without three (§ B5a).
 *
 * OPENINGS DO NOT GO THROUGH IT any more — they arrive in world metres. What
 * is left for it is the FREE boundary, whose rim is measured in the tile's own
 * frame (the outline is local) and turned back afterwards.
 */
export function localToWorld(lx: number, lz: number, cx: number, cz: number,
                             yaw: number): Point {
  const c = Math.cos(yaw);
  const s = Math.sin(yaw);
  return { x: cx + lx * c + lz * s, z: cz - lx * s + lz * c };
}

/** A location's footprint, as much of it as the entry maths needs: centre and
 *  rotation — for the free boundary alone, since that is the one thing still
 *  measured in local metres. */
export interface Footprint { x: number; z: number; yaw: number }

/**
 * One authored pass-through, exactly as `worldmap.locations[].openings`
 * delivers it (§ A1.3): the boundary EDGE INDEX, the point in WORLD metres and
 * the inward unit normal in WORLD axes.
 *
 * Written out here rather than imported so this module keeps its ONE property:
 * no import but the polygon primitives, so the smoke can load it without a
 * bundler (§ B5a). The payload type is `types.MapOpening`, and it is the same
 * shape — structurally, which is how main.ts hands them straight over.
 */
export interface Opening {
  edge: number;
  at_world: [number, number];
  inward: [number, number];
  room?: string;
}

export interface EntryTile {
  locId: string;
  footprint: Footprint;
  /** authored openings of this location, in WORLD metres straight off the
   *  worldmap row. NON-EMPTY = these are the only ways in (strictness decision
   *  2026-08-04, the server refuses a crossing anywhere else); EMPTY = a FREE
   *  boundary (E4 task 5) — the location never said where its way in is, so
   *  the whole RIM counts. */
  openings: Opening[];
  /** the drawn footprint outline in TILE-LOCAL metres (contract v6). It is
   *  what the FREE-boundary case is measured against; with authored openings it
   *  is not read at all. Absent = the location has no area, and then a free
   *  boundary offers nothing (there is no rim to stand at). */
  boundary?: Polygon | null;
  /** the server refuses this location to THIS avatar (`lockedLocations`,
   *  task C1). It stays a candidate: the offer must not be silent about a
   *  locked place one is standing at — it only loses to every open one. */
  locked?: boolean;
}

export interface EntryOffer {
  locId: string;
  /** the opening — or, on a free boundary, the point of the RIM — the offer is
   *  about, in WORLD metres: the point the figure is walked to when the offer
   *  is accepted */
  point: Point;
  /** the boundary EDGE INDEX the point sits on, or `null` on a free boundary:
   *  a rim point is not an authored opening to begin with. */
  edge: number | null;
  dist: number;
  /** the INWARD unit normal at `point`, in WORLD metres — the opening's own
   *  where there is one, the rim's where there is not. The caller walks the
   *  figure one step along it to make the crossing, and never picks a second
   *  time. */
  inward: Point;
}

/**
 * The one enterable location worth offering, or null.
 *
 * - The location the avatar is IN is never a candidate (`myLocId`): one does
 *   not enter where one stands.
 * - A location WITH authored openings offers entry within `radius` of one of
 *   their world points, and nowhere else — the server refuses a crossing
 *   anywhere else (strictness decision 2026-08-04).
 * - A location with a FREE boundary offers entry within `radius` of its RIM
 *   (contract v6: the drawn polygon, `polygon.nearestRimPoint`) — it never said
 *   where its way in is, so anywhere along the outline is one. Without a
 *   boundary such a location has no rim and offers nothing.
 * - An OPEN location always beats a locked one, however much farther away it
 *   is (task C2): standing between a locked gate and an open one, the offer
 *   the player can act on is the one worth showing. Among equals the nearest
 *   point wins, so a lone locked place is still the answer — the caller
 *   turns it into the server's refusal instead of a "press F" that leads
 *   nowhere.
 */
export function entryOfferNear(
  pos: Point,
  myLocId: string,
  tiles: EntryTile[],
  radius: number = ENTER_RADIUS,
): EntryOffer | null {
  let best: EntryOffer | null = null;
  let bestLocked = true;
  for (const t of tiles) {
    if (t.locId === myLocId) continue;
    let near: EntryOffer | null = null;
    if (t.openings.length) {
      // WORLD metres already — the server computed point and normal with the
      // function its own entry gate measures with, so nothing is derived here.
      for (const o of t.openings) {
        const [ox, oz] = o.at_world;
        const dist = Math.hypot(ox - pos.x, oz - pos.z);
        if (dist > radius) continue;
        if (!near || dist < near.dist) {
          near = { locId: t.locId, point: { x: ox, z: oz }, edge: o.edge,
                   dist, inward: { x: o.inward[0], z: o.inward[1] } };
        }
      }
    } else if (t.boundary) {
      // The rim is measured in the TILE's own frame — the boundary is local
      // metres — and the answer is turned back with the same § A1.1 mapping
      // every other payload point goes through (`localToWorld`, and its
      // rotation-only twin for the normal).
      const fp = t.footprint;
      const c = Math.cos(fp.yaw);
      const s = Math.sin(fp.yaw);
      const local = { x: (pos.x - fp.x) * c - (pos.z - fp.z) * s,
                      z: (pos.x - fp.x) * s + (pos.z - fp.z) * c };
      const rim = nearestRimPoint(local.x, local.z, t.boundary);
      if (rim && rim.dist <= radius) {
        const at = localToWorld(rim.x, rim.z, fp.x, fp.z, fp.yaw);
        near = {
          locId: t.locId, point: at, edge: null, dist: rim.dist,
          inward: { x: rim.inward.x * c + rim.inward.z * s,
                    z: -rim.inward.x * s + rim.inward.z * c },
        };
      }
    }
    if (!near) continue;
    const locked = t.locked === true;
    const better = !best || (bestLocked && !locked)
      || (bestLocked === locked && near.dist < best.dist);
    if (better) {
      best = near;
      bestLocked = locked;
    }
  }
  return best;
}
