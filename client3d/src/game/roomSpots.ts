/**
 * THE STANDS OF ONE ROOM as plain arithmetic — the pure core of
 * `scene/tiles.deriveRoomSpots` (Task 29 of the native-client plan).
 *
 * `deriveRoomSpots` does the lookups (the room's floor plan, the height
 * samplers, the placed props' bounding boxes, the room's place markers) and
 * writes the answer into the tile; WHAT it writes is decided here, with no
 * `three`, no DOM and no module state, so the browser and the native client
 * can be held to the same hand-derived numbers
 * (`client3d/scripts/smoke_room_spots.mjs` [7], `shared/test-vectors/room_spots.json`).
 *
 * THE RULES, in the order the tile applies them:
 *
 *  1. THE RECTANGLE: `roomRectOf(hull)`; a hull without a finite point has
 *     none and the room gets no stands at all (`null`).
 *  2. THE CENTRE: the hull's area centroid when it lies inside the hull, else
 *     the first (nearest) point of the raster `roomSpotGrid(hull, rect)`, else
 *     the rectangle's own centre.
 *  3. THE FLOOR at that centre: `floorAt` (the room's lattices, then its
 *     declaration, then the terrain — `roomFloorLadder`). The centre stands at
 *     that floor plus `WALK_CLEARANCE_M`.
 *  4. SIT / LIE: every placed prop's WORLD bounding box is judged by
 *     `furnitureUse(floorY, top, width, depth)`; a usable one offers its top
 *     face's middle, `WALK_CLEARANCE_M` over the top. Order = prop order.
 *  5. MARKER HEIGHTS: every non-fixed place with slots gets ONE height,
 *     `baseFloorAt(mean slot, tile-local) − drop + offsetY` — the room floor
 *     WITHOUT its lattices under the place; `null` for a skipped marker.
 */
import { furnitureUse, polygonCentroid, roomSpotGrid, WALK_CLEARANCE_M } from './ground';
import { pointInPolygon, type Polygon } from './polygon';
import { roomRectOf, type RoomRect } from './roomAt';
import { tileToWorld, type TileFrame } from '../scene/sceneView';
import { worldToLocalXZ } from '@anima/scene-render';

/** A WORLD-metre point. */
export interface SpotPoint { x: number; y: number; z: number }

/** The WORLD axis-aligned bounding box of one placed prop (never empty). */
export interface SpotBox { min: SpotPoint; max: SpotPoint }

/** A place marker of the room as the height rule reads it (`PlaceEntry`). */
export interface SpotMarker {
  /** The slot points in WORLD metres (only x/z are read). */
  slots: readonly { x: number; z: number }[];
  drop: number;
  offsetY: number;
  fixed?: boolean;
}

export interface RoomSpotsInput {
  /** The room's hull, TILE-LOCAL metres (`floor_plan`). */
  hull: Polygon;
  /** The tile's frame: centre in world metres, yaw in RADIANS. */
  frame: TileFrame;
  /** The room's floor WITH its own lattices at a tile-local point (world y). */
  floorAt: (lx: number, lz: number) => number;
  /** The same floor WITHOUT the lattices (declaration, else terrain). */
  baseFloorAt: (lx: number, lz: number) => number;
  /** World boxes of the room's placed props, in placement order. */
  props: readonly SpotBox[];
  /** The room's place markers, in map order. */
  markers: readonly SpotMarker[];
}

export interface RoomSpots {
  rect: RoomRect;
  /** The centre in the tile frame (x/z) and in the world (with its height). */
  centreLocal: { x: number; z: number };
  centre: SpotPoint;
  /** The floor under the centre (world y, no clearance). */
  floorY: number;
  sit: SpotPoint[];
  lie: SpotPoint[];
  /** One entry per marker: its new slot height, or `null` = left alone. */
  markerY: (number | null)[];
}

export function roomSpotsOf(input: RoomSpotsInput): RoomSpots | null {
  const { hull, frame } = input;
  const rect = roomRectOf(hull);
  if (!rect) return null;
  // THE RASTER, only as the centre's fallback: since the SERVER picks the
  // point a figure stands on (§ A1.4, T4) nothing hands out stands here any
  // more, but an L-shaped room still needs an interior point when its centroid
  // falls outside — and the raster is inside by construction.
  const grid = roomSpotGrid(hull, rect.x, rect.z, rect.w, rect.d);
  // THE CENTRE is the area centroid of the drawn hull. On an L-shaped room
  // that point can lie OUTSIDE the room, and then the nearest raster point is
  // taken instead. A full pole-of-inaccessibility would refine that by a few
  // centimetres and cost a grid search per room — the consumers are a huddle,
  // a label and a walk goal, none of which can tell the difference.
  const cen = polygonCentroid(hull);
  const inside = cen && pointInPolygon(cen.x, cen.z, hull) ? cen : (grid[0] ?? null);
  const cx = inside ? inside.x : rect.x;
  const cz = inside ? inside.z : rect.z;
  const floorY = input.floorAt(cx, cz);
  const w = tileToWorld(frame, cx, cz, 0);
  const centre = { x: w.x, y: floorY + WALK_CLEARANCE_M, z: w.z };

  const sit: SpotPoint[] = [];
  const lie: SpotPoint[] = [];
  for (const box of input.props) {
    const use = furnitureUse(floorY, box.max.y,
                             box.max.x - box.min.x, box.max.z - box.min.z);
    if (!use) continue;
    const at = { x: (box.min.x + box.max.x) / 2,
                 y: box.max.y + WALK_CLEARANCE_M,
                 z: (box.min.z + box.max.z) / 2 };
    (use === 'lie' ? lie : sit).push(at);
  }

  // MARKER HEIGHTS sit on the room's floor plus their own lift over the
  // storey datum the composer measured them against — `offsetY` IS
  // `y_world − datum`, so this is the composed height with the room's real
  // floor put under it. On a built ground floor that reproduces the payload
  // exactly; where the ROOM declares a floor of its own (a podium, a sunken
  // lounge, a hut in a lake, an upper storey's plate) the marker follows it.
  // The floor is the one UNDER THE PLACE (on a slope the terrain counts where
  // the place is) and WITHOUT the room's lattices: the offset already carries
  // the furniture under the place. Sampled once per place, at the mean of its
  // slots — the slots of one place share one height.
  const markerY = input.markers.map((e) => {
    if (e.fixed || !e.slots.length) return null;
    let mx = 0;
    let mz = 0;
    for (const s of e.slots) { mx += s.x; mz += s.z; }
    const at = worldToLocalXZ(frame.center.x, frame.center.z, frame.yaw,
                              mx / e.slots.length, mz / e.slots.length);
    return input.baseFloorAt(at.x, at.z) - e.drop + e.offsetY;
  });

  return { rect, centreLocal: { x: cx, z: cz }, centre, floorY, sit, lie, markerY };
}
