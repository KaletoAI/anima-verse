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
 */

/** A point on the world plane, in metres. Same shape as `walk.Point`; not
 *  imported, so this module keeps its "no imports at all" promise for the
 *  smoke loader. */
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
   *  the whole edge counts and `freeBoundaryOf` above is what reads that. */
  openings: LocalOpening[];
  /** the server refuses this location to THIS avatar (`lockedLocations`,
   *  task C1). It stays a candidate: the offer must not be silent about a
   *  locked place one is standing at — it only loses to every open one. */
  locked?: boolean;
}

export interface EntryOffer {
  locId: string;
  /** the opening the offer is about, in WORLD metres — the point the figure
   *  is walked to when the offer is accepted */
  point: Point;
  edge: Edge;
  dist: number;
}

/**
 * The one enterable location worth offering, or null.
 *
 * - The location the avatar is IN is never a candidate (`myLocId`): one does
 *   not enter where one stands.
 * - A location offers entry within `radius` of one of its opening WORLD
 *   points; a location without openings offers nothing, whatever the distance.
 * - An OPEN location always beats a locked one, however much farther away it
 *   is (task C2): standing between a locked gate and an open one, the offer
 *   the player can act on is the one worth showing. Among equals the nearest
 *   opening wins, so a lone locked place is still the answer — the caller
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
    let near: { edge: Edge; x: number; z: number; dist: number } | null = null;
    for (const o of openingWorldPoints(t.footprint, t.openings)) {
      const dist = Math.hypot(o.x - pos.x, o.z - pos.z);
      if (dist > radius) continue;
      if (!near || dist < near.dist) near = { ...o, dist };
    }
    if (!near) continue;
    const locked = t.locked === true;
    const better = !best || (bestLocked && !locked)
      || (bestLocked === locked && near.dist < best.dist);
    if (better) {
      best = { locId: t.locId, point: { x: near.x, z: near.z },
               edge: near.edge, dist: near.dist };
      bestLocked = locked;
    }
  }
  return best;
}
