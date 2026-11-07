/**
 * WHERE THE FIGURES OF ONE LOCATION ARE DRAWN — the pure ladder of
 * `main.computeNpcPlacements` (Task 29 of the native-client plan).
 *
 * `main.ts` groups the worldmap rows by location (travellers, wilderness
 * points and the avatar's special cases are answered before that); for every
 * location with a built tile it hands the rows here together with the tile's
 * VIEW STATE (fade, shown storey, near ring) and its INVENTORY (room centres,
 * storeys, place markers, sit/lie surfaces, corridors). What comes back is the
 * placement of each figure — point, facing, lean, visibility and whether it
 * snaps, walks or stays — in plain numbers. The DOOR ROUTE of a `route`
 * transition stays in `main.ts` (doors, stairs, the lift: NPC walking).
 *
 * THE LADDER, per character, rows sorted by `localeCompare` of the name:
 *
 *  - The interior is REVEALED for it when `tile.fade > 0.5` or its room is an
 *    always-visible one; it is drawn IN its room (`inRoom`) when it has a room
 *    the tile has a centre for and the interior is revealed.
 *  - In its room, first match wins:
 *      seat     the server's `place` names a marker of that room with a slot
 *               (near ring only): the slot point (`seatOf` = `slotFor`), the
 *               marker's `rotation` as the facing (tile-local degrees, the
 *               gaze `(sin a, cos a)` turned by the tile's yaw), its
 *               `tilt`/`roll` as the lean when either is non-zero;
 *      pool     a sitting / lying figure (`animFamily` of
 *               `activity_animation`) takes surface `index mod n` of its
 *               family's pool, the other pool when its own is empty (near
 *               ring only); `index` = position among the room mates of the
 *               sorted list;
 *      corridor the room is a storey corridor: its stand centre;
 *      pos      the server's own `pos` inside the room hull (0.3 m tolerance), at its standing height there
 *               (`roomStandY`), else at the centre's height;
 *      centre   no valid room point: the room's existing centre.
 *  - Otherwise, when its room is the location's GROUND (`is_ground` of the
 *    `/world/locations?view=3d` room list, `tile.groundRooms`) and the row
 *    carries a `pos`: GROUND — exactly that point, at `groundY` there. The
 *    ground has no hull and no centre (it IS the plot, § A13a), so the
 *    server's point is the only place such a figure can be drawn; a made-up
 *    spot would put it next to somebody the server measures 25 m away, and
 *    what the player sees would no longer be who the character can talk to.
 *  - Otherwise the HUDDLE: `huddleOffset` in the tile frame, at
 *    `groundY` of the turned point.
 *  - FACING towards the movement target's place centre (y = 0) when the
 *    target is another known location and no seat set a facing.
 *  - HIDDEN when drawn in a room on another storey than the shown one
 *    (revealed, not always-visible) or when its room's interior is closed
 *    (it has a room with a centre but is not drawn in it).
 *  - TRANSITION = `figureTransition(previous shown placement, {inRoom,
 *    interiorShown})`.
 *
 * PURE: no `three`, no DOM, no module state. Hand oracle:
 * `client3d/scripts/smoke_npc_placement.mjs` (shared/test-vectors/npc_placement.json).
 */
import { animFamily } from '../scene/clipCoverage';
import { tileDirToWorld, tileToWorld } from '../scene/sceneView';
import { worldToLocalXZ } from '@anima/scene-render';
import { figureTransition, type FigureTransition, type ShownPlacement } from './placement';
import { polygonDistance, type Polygon } from './polygon';

/** A WORLD-metre point. */
export interface PlacementPoint { x: number; y: number; z: number }

/** What the ladder reads off a worldmap row (a subset of `MapCharacter`). */
export interface PlacementRow {
  name: string;
  pos?: { x: number; z: number } | null;
  place?: { id: string; slot: number | 'pair' } | null;
  activity_animation?: string;
  movement_target_id?: string;
}

/** What the ladder reads off a place marker (a subset of `PlaceEntry`). */
export interface PlacementMarker {
  group?: string;
  rotation?: number;
  tilt?: number;
  roll?: number;
}

/** The tile as the ladder reads it — view state and inventory in one, the
 *  structural subset of `scene/tiles.Tile`. `yaw` is in RADIANS. */
export interface PlacementTile<M extends PlacementMarker = PlacementMarker> {
  center: PlacementPoint;
  yaw: number;
  width: number;
  isBuilding: boolean;
  /** View state: interior fade (> 0.5 = revealed) and the shown storey. */
  fade: number;
  levelFilter: number;
  alwaysVisibleRooms: ReadonlySet<string>;
  /** Inventory, keyed by room id AND name like the tile's own maps. */
  roomCenters: ReadonlyMap<string, PlacementPoint>;
  roomLevels: ReadonlyMap<string, number>;
  /** The authoritative room's footprint, in tile metres (including upper storeys). */
  roomFloors: ReadonlyMap<string, { hull: Polygon }>;
  roomMarkers: ReadonlyMap<string, ReadonlyMap<string, M>>;
  roomSitSpots: ReadonlyMap<string, readonly PlacementPoint[]>;
  roomLieSpots: ReadonlyMap<string, readonly PlacementPoint[]>;
  corridors: readonly { roomId: string }[];
  /** The location's ground room — id AND name, like the room maps — as the
   *  `is_ground` flag of the location's room list names it. Never the
   *  reserved id: that constant stays the server's (§ A13). */
  groundRooms: ReadonlySet<string>;
}

/** The lookups the ladder needs from around it. */
export interface PlacementContext<M extends PlacementMarker> {
  /** The location's id (a movement target equal to it is not faced). */
  locId: string;
  /** View state: the tile is in the NEAR ring (seats and surfaces exist). */
  near: boolean;
  /** The room a character is in, as far as the client knows. */
  roomOf: (name: string) => string | undefined;
  /** Where the figure was drawn the last time (`shownPlacement`). */
  shownOf: (name: string) => ShownPlacement | undefined;
  /** The point a held place puts the figure on (`placeSlot.slotFor`). */
  seatOf: (marker: M, slot: number | 'pair') => PlacementPoint | undefined;
  /** The standing height in a room at a tile-local point (`tiles.roomStandY`). */
  roomStandY: (room: string, lx: number, lz: number) => number | null;
  /** Called only when the pos rung rejects a point; the session owner deduplicates diagnostics. */
  stalePos?: (name: string, room: string, point: { x: number; z: number }) => void;
  /** The ground a huddle or ground figure stands on at a world point (`tiles.tileGroundY`). */
  groundY: (x: number, z: number) => number;
  /** The centre of a known location (`places.get(id)?.center`). */
  targetCentre: (id: string) => PlacementPoint | undefined;
}

export type PlacementBranch = 'seat' | 'pool' | 'corridor' | 'pos' | 'centre' | 'ground' | 'huddle';

export interface LocatedFigure<R extends PlacementRow> {
  row: R;
  branch: PlacementBranch;
  pos: PlacementPoint;
  /** World facing direction (y = 0), or undefined = no fixed facing. */
  face?: PlacementPoint;
  lean?: { tilt: number; roll: number };
  surfaceGroup?: string;
  /** The room drawn in, or null (huddle / closed interior). */
  inRoom: string | null;
  interiorShown: boolean;
  hidden: boolean;
  transition: FigureTransition;
}

/** Where a character stands on a tile without a room spot, in TILE-LOCAL
 *  metres: a row of 2.3 m spacing in front of a building (south side, at 0.36
 *  of its edge), a ring of 2.6 m radius on an open place. */
export function huddleOffset(isBuilding: boolean, width: number,
                             index: number, count: number): { x: number; z: number } {
  if (isBuilding) {
    // Line up in front of the building (south side).
    return { x: (index - (count - 1) / 2) * 2.3, z: width * 0.36 };
  }
  const angle = (index / Math.max(count, 1)) * Math.PI * 2;
  return { x: Math.cos(angle) * 2.6, z: Math.sin(angle) * 2.6 };
}

const copy = (p: PlacementPoint): PlacementPoint => ({ x: p.x, y: p.y, z: p.z });

/** The body's visible floor is independent of the row room and of position-origin echoes. */
export interface AvatarRoomCorrection {
  oldRoom: string; oldLevel: number; room: string; level: number; point: PlacementPoint;
}
export function insidePlacementRoom<M extends PlacementMarker>(tile: PlacementTile<M>, room: string,
  point: { x: number; z: number }): boolean {
  const p = worldToLocalXZ(tile.center.x, tile.center.z, tile.yaw, point.x, point.z);
  return Number.isFinite(point.x) && Number.isFinite(point.z)
    && polygonDistance(p.x, p.z, tile.roomFloors.get(room)?.hull) <= .3;
}
export function avatarRoomCorrection<M extends PlacementMarker>(tile: PlacementTile<M>, body: PlacementPoint,
  room: string, rowPoint: { x: number; z: number },
  floorY: (room: string, x: number, z: number) => number | null, ownRide = false, bodyRoom?: string): AvatarRoomCorrection | null {
  const centre = tile.roomCenters.get(room), level = tile.roomLevels.get(room);
  if (ownRide || !centre || level === undefined || !tile.roomFloors.has(room)) return null;
  const local = worldToLocalXZ(tile.center.x, tile.center.z, tile.yaw, body.x, body.z);
  let oldRoom: string | null = null, oldLevel = 0, best = Infinity, bestInside = false, inLocation = false;
  // Height chooses the floor; containment only breaks ties between adjacent rooms on that floor.
  for (const [id, c] of tile.roomCenters) {
    const candidateLevel = tile.roomLevels.get(id);
    if (candidateLevel === undefined) continue;
    const distance = Math.abs(body.y - (floorY(id, local.x, local.z) ?? c.y));
    const inside = insidePlacementRoom(tile, id, body);
    inLocation ||= inside;
    if (distance < best - 1e-6 || Math.abs(distance - best) <= 1e-6 && inside && !bestInside) {
      oldRoom = id; oldLevel = candidateLevel; best = distance; bestInside = inside;
    }
  }
  // A distant point with a stale room belongs to the ordinary teleport/readiness path.
  if (!inLocation || oldRoom === null || oldLevel === level && (bodyRoom === room || insidePlacementRoom(tile, room, body))) return null;
  const at = worldToLocalXZ(tile.center.x, tile.center.z, tile.yaw, rowPoint.x, rowPoint.z);
  const point = insidePlacementRoom(tile, room, rowPoint)
    ? { x: rowPoint.x, y: floorY(room, at.x, at.z) ?? centre.y, z: rowPoint.z } : copy(centre);
  return { oldRoom: bodyRoom ?? oldRoom, oldLevel, room, level, point };
}

/** Session-owned deduplication, shared by NPC placement and the own avatar's arrival. */
export class RoomPositionDiagnostics {
  private readonly seen = new Set<string>();
  constructor(private readonly log: (line: string) => void) {}
  report(location: string, name: string, room: string, point: { x: number; z: number }): void {
    const key = JSON.stringify([location, name, room, point.x, point.z]);
    if (this.seen.has(key)) return;
    this.seen.add(key);
    this.log(`[figures] ${name}: pos (${point.x},${point.z}) outside room ${room} — placed in the room`);
  }
}

export function placeAtLocation<R extends PlacementRow, M extends PlacementMarker>(
  rows: readonly R[], tile: PlacementTile<M>, ctx: PlacementContext<M>,
): LocatedFigure<R>[] {
  const chars = [...rows].sort((a, b) => a.name.localeCompare(b.name));
  const roomMates = new Map<string, string[]>();
  for (const c of chars) {
    const room = ctx.roomOf(c.name);
    if (room) (roomMates.get(room) ?? roomMates.set(room, []).get(room)!).push(c.name);
  }
  return chars.map((c, i) => {
    let branch: PlacementBranch;
    let pos: PlacementPoint;
    let face: PlacementPoint | undefined;
    let lean: { tilt: number; roll: number } | undefined;
    let surfaceGroup: string | undefined;
    const room = ctx.roomOf(c.name);
    const roomCenter = room ? tile.roomCenters.get(room) : undefined;
    // A pure VIEW state: whether the client can draw the character inside.
    const interiorShown = tile.fade > 0.5
      || (!!room && tile.alwaysVisibleRooms.has(room));
    const inRoom = roomCenter && room && interiorShown ? room : null;
    if (inRoom && roomCenter) {
      const mates = roomMates.get(inRoom)!;
      const idx = mates.indexOf(c.name);
      const kind = c.activity_animation || '';
      const held = ctx.near && c.place ? tile.roomMarkers.get(inRoom)?.get(c.place.id) : undefined;
      // `undefined` for a marker without slots: it falls down the ladder.
      const seat = held && c.place ? ctx.seatOf(held, c.place.slot) : undefined;
      const sit = ctx.near ? tile.roomSitSpots.get(inRoom) : undefined;
      const lieDown = ctx.near ? tile.roomLieSpots.get(inRoom) : undefined;
      // The surface choice runs over the FAMILY — `sit-cmu` is a sitting and
      // belongs on the sit surfaces.
      const family = animFamily(kind);
      const pool = family === 'lie' ? (lieDown?.length ? lieDown : sit)
        : family === 'sit' ? (sit?.length ? sit : lieDown) : undefined;
      if (held && seat) {
        // The server seated this figure: its slot, its facing, its lean —
        // nothing is chosen here.
        branch = 'seat';
        pos = copy(seat);
        surfaceGroup = held.group;
        if (held.rotation !== undefined) {
          // `facing` is TILE-LOCAL like every other payload angle, and a gaze
          // is a DIRECTION: it turns with the footprint but is not shifted by
          // its centre. Without the turn a seated figure on a rotated location
          // sits in the right chair looking off by the location's yaw. The
          // counter-sense of `facing` itself (scene_recipe.py
          // `_marker_facing`) is untouched — this changes the FRAME, not the
          // convention.
          const a = held.rotation * (Math.PI / 180);
          const dir = tileDirToWorld(tile, Math.sin(a), Math.cos(a));
          face = { x: dir.x, y: 0, z: dir.z };
        }
        if (held.tilt || held.roll) lean = { tilt: held.tilt || 0, roll: held.roll || 0 };
      } else if (pool?.length) {
        branch = 'pool';
        pos = copy(pool[idx % pool.length]);
        surfaceGroup = pool === lieDown ? 'lie' : 'seat';
      } else if (tile.corridors.some((cor) => cor.roomId === inRoom)) {
        // A STOREY CORRIDOR (§ A13c) is no room with a hull: the server picks
        // no standing point in it, and `pos` is whatever point the figure
        // last stood on. Its own anchor (`floor_anchor`: inside the outline,
        // outside every room, largest clearance) is the server's answer for
        // that storey, so the figure is drawn there.
        branch = 'corridor';
        pos = copy(roomCenter);
      } else {
        branch = 'centre';
        pos = copy(roomCenter);
        if (c.pos) {
          const local = worldToLocalXZ(tile.center.x, tile.center.z, tile.yaw, c.pos.x, c.pos.z);
          // Use this room's hull on its storey, with wall/door threshold tolerance.
          // A floor-height lookup also answers outside the footprint.
          if (insidePlacementRoom(tile, inRoom, c.pos)) {
            branch = 'pos';
            pos = { x: c.pos.x, y: ctx.roomStandY(inRoom, local.x, local.z) ?? roomCenter.y, z: c.pos.z };
          } else ctx.stalePos?.(c.name, inRoom, c.pos);
        }
      }
    } else if (room && tile.groundRooms.has(room) && c.pos
               && Number.isFinite(c.pos.x) && Number.isFinite(c.pos.z)) {
      // On the GROUND the server's point is the whole answer: no hull to test
      // it against, no centre to fall back on.
      branch = 'ground';
      pos = { x: c.pos.x, y: ctx.groundY(c.pos.x, c.pos.z), z: c.pos.z };
    } else {
      branch = 'huddle';
      const slot = huddleOffset(tile.isBuilding, tile.width, i, chars.length);
      const w = tileToWorld(tile, slot.x, slot.z);
      pos = { x: w.x, y: ctx.groundY(w.x, w.z), z: w.z };
    }
    const shown: ShownPlacement = { room: inRoom, interiorShown };
    const transition = figureTransition(ctx.shownOf(c.name), shown);
    const target = c.movement_target_id ? ctx.targetCentre(c.movement_target_id) : undefined;
    if (target && c.movement_target_id !== ctx.locId && !face) {
      face = { x: target.x - pos.x, y: 0, z: target.z - pos.z };
    }
    const wrongStorey = !!inRoom && tile.fade > 0.5
      && !tile.alwaysVisibleRooms.has(inRoom)
      && (tile.roomLevels.get(inRoom) ?? 0) !== tile.levelFilter;
    const roomIsClosed = !inRoom && !!room && !!roomCenter;
    return { row: c, branch, pos, face, lean, surfaceGroup, inRoom, interiorShown,
             hidden: wrongStorey || roomIsClosed, transition };
  });
}
