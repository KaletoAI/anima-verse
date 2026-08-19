/**
 * Entering at authored boundary openings — IN METRES since E4 task 5
 * (plan-3d-lod-und-betreten.md Etappe 3; contract § B1 Nr. 13, § A1.1).
 *
 * Pure maths like walk.ts/proximity.ts — the numbers are checked in
 * `client3d/scripts/smoke_enter_math.mjs`. main.ts looks the arguments up
 * (the tiles around the avatar, the openings of their scene payloads) and
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
 * WHAT CHANGED WITH THE SQUARE (contract v6 "Gebiete"). A location with
 * AUTHORED OPENINGS is untouched: the offer is the distance to an opening's
 * world point, exactly as before. A FREE boundary — no authored opening, so
 * the whole rim is the way in — is now measured against the DRAWN POLYGON
 * (`polygon.nearestRimPoint`) instead of against the edges of a square that
 * only ever existed as a special case of it.
 */

import { nearestRimPoint, type Polygon } from './polygon';

/** A point on the world plane, in metres. Same shape as `walk.Point`. */
export interface Point { x: number; z: number }

/** The four edges of a location's footprint, as the payload spells them. */
export type Edge = 'N' | 'E' | 'S' | 'W';

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
 */
export function localToWorld(lx: number, lz: number, cx: number, cz: number,
                             yaw: number): Point {
  const c = Math.cos(yaw);
  const s = Math.sin(yaw);
  return { x: cx + lx * c + lz * s, z: cz - lx * s + lz * c };
}

/** A location's footprint, as much of it as the entry maths needs: centre and
 *  rotation. The edge length does not appear — an opening's own local point
 *  already carries it. */
export interface Footprint { x: number; z: number; yaw: number }

/** One authored opening as the scene payload delivers it: the WORLD edge
 *  letter (the server has already applied `tile_rotation`) and the point in
 *  TILE-LOCAL metres (`at_world`). */
export interface LocalOpening { edge: Edge; at: Point }

/** One clockwise 90° step of `tile_rotation`, and which edges flip their `at`
 *  while taking it — `boundary_entry._EDGE_CW` / `_EDGE_FLIP` verbatim. */
const EDGE_CW: Record<Edge, Edge> = { N: 'E', E: 'S', S: 'W', W: 'N' };
const EDGE_FLIP: Record<Edge, boolean> = { N: false, E: true, S: false, W: true };

/**
 * An authored opening as `map3d` stores it — the RAW form, before the server
 * has composed a scene out of it.
 *
 * `at` is the position along the edge as a fraction (left→right on N/S,
 * top→bottom on E/W), `edge` is the letter in TEMPLATE orientation.
 */
export interface RawOpening { edge: Edge; at: number }

/**
 * Anchor ONE raw opening in the location's own frame — the client's mirror of
 * `app/core/boundary_entry.opening_world_points`, up to the final
 * local→world turn (`localToWorld`, which the caller does with the tile's
 * `yaw_deg`).
 *
 * WHY THE CLIENT COMPUTES THIS AT ALL. The scene payload delivers every
 * opening ready-anchored (`at_world`), but only for a location that HAS a
 * scene: `/play/locations/{id}/scene` answers 404 for a place with no
 * outline, no room layout and no building model — a painted meadow with a
 * gate drawn on it, which the world editor allows long before any layout
 * exists. Such a place was UNREACHABLE ON FOOT: the walker was blocked at its
 * boundary (it has authored openings, so it is not a free boundary) while the
 * entry offer had no opening point to stand at. The server, meanwhile, reads
 * `map3d.boundary_openings` and would let the crossing through. So the client
 * anchors the raw list itself, with the server's own formula.
 *
 * THE FORMULA, hand-derived from the server (`plan_width_m` = w, half = w/2):
 *   free = (at − 0.5)·w        the position along the edge, centred
 *   N → (free, −half)   S → (free, +half)   W → (−half, free)   E → (+half, free)
 * `tileRotationDeg` (`map3d.tile_rotation`) is applied FIRST, in 90° steps:
 * the letter walks N→E→S→W and `at` flips to `1 − at` on every step taken
 * from an E or a W edge — the composer's rule, verbatim.
 *
 * NO ANCHOR, NO POINT. Without a usable `plan_width_m` the location has no
 * edge length, and an opening with no length to sit on has no point: `null`,
 * and the place stays closed exactly as it is today. A made-up default edge
 * would put the offer at a metre nobody authored, and the server would refuse
 * the crossing there.
 */
export function anchorRawOpening(edge: Edge, at: number, planWidthM: number,
                                 tileRotationDeg = 0): Point | null {
  if (!Number.isFinite(planWidthM) || planWidthM <= 0) return null;
  if (!EDGE_CW[edge]) return null;
  // A missing or unusable fraction is the edge MIDPOINT, and one outside the
  // edge is pulled onto it — the server sanitises `at` the same way.
  let f = Number.isFinite(at) ? Math.min(Math.max(at, 0), 1) : 0.5;
  let e: Edge = edge;
  const steps = Number.isFinite(tileRotationDeg)
    ? ((Math.trunc(tileRotationDeg / 90) % 4) + 4) % 4 : 0;
  for (let i = 0; i < steps; i++) {
    if (EDGE_FLIP[e]) f = 1 - f;
    e = EDGE_CW[e];
  }
  const half = planWidthM / 2;
  const free = (f - 0.5) * planWidthM;
  if (e === 'N') return { x: free, z: -half };
  if (e === 'S') return { x: free, z: half };
  if (e === 'W') return { x: -half, z: free };
  return { x: half, z: free };                       // 'E'
}

/**
 * The whole raw list, anchored — the openings a 404-scene location offers.
 *
 * Openings without an anchor drop out (see `anchorRawOpening`), so an empty
 * answer means "this location cannot be entered at a point we know", which is
 * the closed state and never a free boundary.
 */
export function anchorRawOpenings(raw: RawOpening[] | null | undefined,
                                  planWidthM: number,
                                  tileRotationDeg = 0): LocalOpening[] {
  const out: LocalOpening[] = [];
  for (const o of raw ?? []) {
    // The ROTATED letter is what the point belongs to, and `anchorRawOpening`
    // is where the rotation happens — so it is re-derived here rather than
    // read off the raw entry, or a turned location would carry a point on one
    // edge under the name of another.
    const at = anchorRawOpening(o.edge, o.at, planWidthM, tileRotationDeg);
    if (!at) continue;
    out.push({ edge: rotatedEdge(o.edge, tileRotationDeg), at });
  }
  return out;
}

/** The world edge letter of a template edge under `tile_rotation`. */
export function rotatedEdge(edge: Edge, tileRotationDeg = 0): Edge {
  const steps = Number.isFinite(tileRotationDeg)
    ? ((Math.trunc(tileRotationDeg / 90) % 4) + 4) % 4 : 0;
  let e: Edge = edge;
  for (let i = 0; i < steps; i++) e = EDGE_CW[e];
  return e;
}

/**
 * The INWARD unit normal of an edge, tile-local — the direction one walks to
 * get from the opening into the location.
 *
 * The scene payload carries this per opening (`inward`, § B1 Nr. 13); this is
 * the same vector for the raw openings that have no payload. N is the −z edge,
 * so inward from it is +z, and so on around the square.
 */
export function inwardOf(edge: Edge): Point {
  if (edge === 'N') return { x: 0, z: 1 };
  if (edge === 'S') return { x: 0, z: -1 };
  if (edge === 'W') return { x: 1, z: 0 };
  return { x: -1, z: 0 };                            // 'E'
}

/** The openings of one location in WORLD metres — `localToWorld` per opening,
 *  the client's mirror of `boundary_entry.opening_world_points`. */
export function openingWorldPoints(fp: Footprint, openings: LocalOpening[]
): { edge: Edge; x: number; z: number }[] {
  return openings.map((o) => {
    const p = localToWorld(o.at.x, o.at.z, fp.x, fp.z, fp.yaw);
    return { edge: o.edge, x: p.x, z: p.z };
  });
}

/**
 * Does a location let one in ANYWHERE — the client's mirror of the server's
 * free-boundary rule (`app/routes/play.py`: "NO AUTHORED OPENINGS AT ALL = a
 * free boundary")?
 *
 * TWO inputs, because the client has two sources and the server has one.
 *
 * `scene` is the location's SCENE PAYLOAD as the client's cache answers it,
 * and all three of its states mean something different:
 *
 *  - a payload — its own `boundary_openings` decide. Empty = free, and one
 *    authored opening makes the openings the only way in.
 *  - `undefined` — still in flight, nothing is known. The honest answer is
 *    the closed one: reading "not loaded" as "no openings" would open every
 *    unloaded footprint for the seconds until it arrives, and the figure would
 *    walk into a place the server then refuses.
 *  - `null` — the scene endpoint answered 404. That means "no building
 *    outline, no room with a layout and no building model" and NOTHING ELSE:
 *    the server reads the openings from `map3d.boundary_openings`, which the
 *    world editor lets an author draw BEFORE any layout exists. So a 404 does
 *    not imply "no openings", and `authoredOpenings` is what decides here.
 *
 * `authoredOpenings` is the raw `map3d.boundary_openings` count of that
 * location (the worldmap row carries it, § A12), and it only ever matters in
 * the `null` case — with a payload the composed list is the better answer,
 * with nothing loaded we do not walk anyway.
 *
 * BOTH divergences are what this closes. Reading 404 as a wall bounced the
 * walker off a painted meadow the server would have let it stroll into
 * (task-5 ledger finding); reading 404 as free would have let it stroll into
 * a place whose author HAD drawn a gate — straight into a `no_opening` 403
 * and a snap back, on every attempt.
 */
export function freeBoundaryOf(
  scene: { boundary_openings?: unknown[] | null } | null | undefined,
  authoredOpenings: number,
): boolean {
  if (scene === undefined) return false;
  if (scene === null) return authoredOpenings <= 0;
  return (scene.boundary_openings ?? []).length === 0;
}

export interface EntryTile {
  locId: string;
  footprint: Footprint;
  /** authored openings of this location, TILE-LOCAL (the payload's
   *  `at_world`). NON-EMPTY = these are the only ways in (strictness decision
   *  2026-08-04, the server refuses a crossing anywhere else); EMPTY = a FREE
   *  boundary (E4 task 5) — the location never said where its way in is, so
   *  the whole RIM counts and `freeBoundaryOf` above is what reads that. */
  openings: LocalOpening[];
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
  /** the footprint edge the point sits on, or `null` on a free boundary: v6
   *  numbers polygon edges instead of naming them N/E/S/W, and a rim point is
   *  not an authored opening to begin with. */
  edge: Edge | null;
  dist: number;
  /** the INWARD unit normal at `point`, in WORLD metres — only set for a free
   *  boundary, where there is no authored opening to look the normal up on.
   *  The caller walks the figure one step along it to make the crossing. */
  inward?: Point;
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
      for (const o of openingWorldPoints(t.footprint, t.openings)) {
        const dist = Math.hypot(o.x - pos.x, o.z - pos.z);
        if (dist > radius) continue;
        if (!near || dist < near.dist) {
          near = { locId: t.locId, point: { x: o.x, z: o.z },
                   edge: o.edge, dist };
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
