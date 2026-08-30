import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { highestSurfaceAt, tileDatumStep, worldToLocalXZ } from '@anima/scene-render';
import type { CutoutHandle, PlacedSurface, SceneModelSpec,
  SurfaceMaterialSpec } from '@anima/scene-render';
import type { WorldLocation } from '../types';
import { declaredFloorAt, furnitureUse, plateCeiling, polygonCentroid,
  recipeFloorAt, roomSpotGrid, SPOT_FLAT_M, standY, WALK_CLEARANCE_M,
  type DeclaredFloor, type GroundModelInfo, type WalkPlate } from '../game/ground';
import { pointInPolygon, polygonArea, polygonBounds, sanitizePolygon } from '../game/polygon';
import type { SubmergedGhost } from './submergedGhost';
import type { PlaceEntry } from './placeSlot';

// --- The FOOTPRINT of a location (contract v6 "Gebiete", § A1.1) -------------
//
// CELL is gone, and with it `gridToWorld` and every neighbourhood built out of
// integer arithmetic. And since v6 the SQUARE is gone too: a location is a
// drawn POLYGON — `boundary`, a point sequence in local metres around the pin
// (`pos_x`, `pos_z`), turned by `yaw_deg` about the up axis. A legacy square
// arrives from the server as its four synthesized corners, so nothing here has
// a square code path. The tile's group carries pin and rotation, so everything
// hanging in it is placed in tile-local metres and lands where the server says.

/** Locations already warned about — a missing boundary is a per-location fact,
 *  and a tile is rebuilt on every layout change. */
const widthWarned = new Set<string>();

// THE GROUND RAYCAST IS GONE ("Ein Boden" E5b). `RAY_START_FALLBACK_M` /
// `RAY_START_MARGIN_M` / `setWorldRayStart` existed to start a downward ray
// above the world's relief so it could hit a location model's baked-in ground
// skin. The height ladder reads DATA now — a declaration, a storey plate, the
// terrain — so there is no ray to start and no height to start it above.

/** The world ground under a point, or `null` while nothing has been taken
 *  over — see `setWorldGround`. */
let worldGroundAt: ((x: number, z: number) => number) | null = null;

/**
 * Take over the world's ground sampler — THE GROUND HOOK (§ A16, E8 task 4).
 *
 * A location does not float over its landscape: its tile stands on the world
 * ground under its own centre. Under a BUILT footprint (`draws_built_floor`,
 * § A16.4) that one height IS the whole place, because the bake stamps a flat
 * plateau there; under a natural place the landscape runs on underneath and
 * the centre is simply where the tile sits.
 * `footprintCentre` reads it here and the tile group carries it, which is what
 * lifts a location onto its hill in one
 * move — the scene inside stays tile-local metres and rides along, exactly as
 * it does for position and yaw (`tileToWorld`).
 *
 * Set by `scene/ground.ts`, which owns the field. Nothing here fetches: while
 * no field has arrived the world is flat, which is also what an unrelieved
 * world answers, so a client that never gets one is wrong about nothing.
 */
export function setWorldGround(sampler: (x: number, z: number) => number): void {
  worldGroundAt = sampler;
}

/** The same sampler for consumers OUTSIDE this module — `sceneRecipe.ts` needs
 *  it to lift storey-0 placements onto the terrain under their own anchor
 *  (`storeyGroundLift`, § A16.9). Handed out rather than re-fetched: a second
 *  height source is the twin rule that drifts. `null` while none has arrived,
 *  which the lift reads as "no lift". */
export function worldGroundSampler(): ((x: number, z: number) => number) | null {
  return worldGroundAt;
}

/**
 * WHAT THE WATER IS OVER ONE POINT — the pair every underwater gate needs, and
 * the reason it is a pair.
 *
 * `level` is the drawn mirror (`waterRaster.rasterLevelAt`) and `sd` the signed
 * distance to the authored outline (`waterRaster.rasterSdAt`, positive inside).
 * The LEVEL ALONE IS NOT A MASK: the server dilates it 4 m past every outline,
 * so it answers a mirror on ground that is drawn as bank. The terrain settles
 * that with `waterShade.waterInside(sd)` (`terrainLod.liftedHeight`), and so
 * must anything that decides whether a thing stands in water — hence one
 * sampler handing out both numbers, never two hooks that can drift apart.
 */
export interface WorldWater {
  /** The drawn water surface in world metres; `NaN` where no tile knows. */
  level: number;
  /** Signed distance to the authored outline, > 0 inside; `WATER_SD_DRY`
   *  (`waterRaster.ts`) where no tile knows. */
  sd: number;
}

/** The world's WATER over a point, or `null` while nothing has been taken
 *  over — see `setWorldWater`. */
let worldWaterAt: ((x: number, z: number) => WorldWater) | null = null;

/**
 * Take over the world's water sampler — the mirror twin of the ground hook.
 *
 * It answers the DRAWN water surface: `waterRaster.rasterLevelAt`, the very
 * lattice the terrain's water variant lifts its vertices onto (K-A E2/E3), and
 * `NaN` where no tile knows of water. Nothing else may be used for it — a
 * placement gated against the painted area's profile while the picture is drawn
 * from the raster would put a ghost's waterline somewhere the eye does not see
 * one. It answers the OUTLINE with it ({@link WorldWater}), because the level is
 * dilated and a gate keyed on it alone ghosts things standing on the bank.
 *
 * Set by `scene/ground.ts`, which owns the raster. Read by `sceneRecipe.ts` to
 * decide whether a placement stands under water (`walk.ghostWaterLevel` +
 * `walk.ghostCutY`, `scene/submergedGhost.ts`); a world with no water never
 * registers anything interesting and every placement comes out dry, which is
 * right.
 */
export function setWorldWater(
  sampler: (x: number, z: number) => WorldWater,
): void {
  worldWaterAt = sampler;
}

/** The same sampler for consumers outside this module. `null` while none has
 *  arrived, which every gate reads as "dry". */
export function worldWaterSampler(
): ((x: number, z: number) => WorldWater) | null {
  return worldWaterAt;
}

/**
 * THE footprint outline of a location, in TILE-LOCAL metres — the drawn
 * polygon of contract v6, or `null` when the location has no area at all.
 *
 * Two sources and no third: the worldmap row (the server hoists the EFFECTIVE
 * boundary out of `map3d`, synthesizing the four corners of a legacy square)
 * and the detail record's own `map3d.boundary` for a location the map row says
 * nothing about. `null` is a real state — v6 Nr. 1 struck the "without an
 * anchor, a 10 m square" fallback without replacement, so such a place is a
 * pin: it claims no point on the plane and says so once.
 */
export function footprintBoundary(loc: WorldLocation): [number, number][] | null {
  const pts = sanitizePolygon(loc.boundary ?? loc.map3d?.boundary);
  if (pts) return pts;
  if (!widthWarned.has(loc.id)) {
    widthWarned.add(loc.id);
    console.warn(`[tiles] ${loc.name || loc.id}: no boundary — the location has`
      + ' no area at all (contract v6 Nr. 1), so it claims no ground');
  }
  return null;
}

/** Width of the footprint's BOUNDING BOX in world metres — derived from the
 *  boundary (v6 Nr. 2), with the server's own `plan_width_m` as the fallback
 *  for a location that has a width but no outline. Everything that needs ONE
 *  length reads it: the texture repeat, the selection ring, the load radius. */
export function footprintWidth(loc: WorldLocation): number {
  const b = polygonBounds(loc.boundary ?? loc.map3d?.boundary);
  if (b) return Math.max(b.maxX - b.minX, b.maxZ - b.minZ);
  const w = loc.plan_width_m ?? loc.map3d?.plan_width_m;
  return typeof w === 'number' && Number.isFinite(w) && w > 0 ? w : 0;
}

/**
 * Centre of a location's footprint in world metres, or `null` when it is not
 * placed (§ A1.1 — no point, no tile).
 *
 * This is THE test for "may I build a tile for this": `pos_x`/`pos_z` are
 * nullable on purpose (a template, a place the world editor has not put down
 * yet), and a `?? 0` anywhere on this path would stack every unplaced location
 * on the world origin in one silent heap — which reads as one broken tile, not
 * as missing data.
 *
 * THE y IS THE WORLD GROUND (E8 task 4). Not 0 any more: it is the field at
 * the location's own centre (`setWorldGround`) — under a BUILT footprint
 * (`draws_built_floor`, § A16.4) that is the flat plateau the bake stamped,
 * under any natural place it is the landscape at that point.
 * Because the whole tile group hangs off this one point, everything the place
 * is made of — the shell, the rooms, the scene payload's tile-local metres —
 * climbs the hill together, and nothing inside the location has to know about
 * relief at all.
 */
export function footprintCentre(
  loc: { pos_x?: number | null; pos_z?: number | null }
): THREE.Vector3 | null {
  const x = loc.pos_x;
  const z = loc.pos_z;
  if (typeof x !== 'number' || !Number.isFinite(x)) return null;
  if (typeof z !== 'number' || !Number.isFinite(z)) return null;
  const y = worldGroundAt ? worldGroundAt(x, z) : 0;
  return new THREE.Vector3(x, Number.isFinite(y) ? y : 0, z);
}

/**
 * THE TILE'S DATUM ARRIVED LATE, OR MOVED — put the whole frame back on the
 * ground under its own pin (user finding 2026-08-24, the floating "Haus von
 * Kai"; the law is `@anima/scene-render` `tileDatumStep`).
 *
 * `buildTile` reads the pin's ground ONCE (`footprintCentre`) and freezes it
 * into `tile.center.y` and the group's position — but on a fresh load a tile is
 * built before the 2 m height tiles under it land, and after a re-bake the
 * ground under a plot moves while the tile keeps standing on the old number.
 * A placement that carries a LIFT does not care (`lift = ground − datum`, so
 * the datum cancels), which is why `reliftScene` alone made the interior look
 * right and left the BUILDING — the one thing § A16.9 does not lift, because it
 * IS the plot — hanging in the air by exactly the datum's error.
 *
 * The probe existed until "Ein Boden" E3: `main.relevelTiles` compared
 * `footprintCentre(loc).y` against `tile.center.y` every frame and rebuilt the
 * tile when it moved. It was deleted with the ground plate whose drape its
 * SECOND clause watched. This is its first clause, without the rebuild.
 *
 * WHAT MOVES HERE: the frame and nothing else — so every mesh hanging in the
 * group travels with it, and the re-lift that runs right after takes the same
 * amount straight back off every lifted placement (they end up at
 * `ground(anchor) + bottom_y`, the very number they had). What a mounted SCENE
 * composed in world coordinates instead of hanging in the group is the scene's
 * own bookkeeping and rides along in `sceneRecipe.reliftScene`, which is handed
 * this return value for exactly that reason.
 *
 * Returns the move, 0 when the field has nothing new (or nothing at all) to
 * say — a tile evicted from the cache keeps the datum it stands on.
 */
export function redatumTile(tile: Tile): number {
  const step = tileDatumStep(tile.center.y, tile.center.x, tile.center.z,
                             worldGroundAt);
  if (!step.delta) return 0;
  tile.center.y = step.datum;
  tile.group.position.y = step.datum;
  return step.delta;
}

/** Footprint rotation in RADIANS, the world-map convention of § A1.1 — the
 *  same sign the tile group is turned by (`rotation.y = +rad(yaw_deg)`). */
export function footprintYaw(loc: WorldLocation): number {
  const y = loc.yaw_deg;
  return typeof y === 'number' && Number.isFinite(y) ? (y * Math.PI) / 180 : 0;
}

/**
 * Tile-local (x, z) → world, the contract's own mapping (§ A1.1,
 * `app/core/world_geometry.local_to_world`):
 *
 *     x = cx + lx·cos(yaw) + lz·sin(yaw)
 *     z = cz − lx·sin(yaw) + lz·cos(yaw)
 *
 * This is exactly what three.js' `rotation.y = +rad(yaw)` does to a child of
 * the tile group, so a point computed here and a mesh hanging in the group end
 * up in the same place. EVERY local→world conversion goes through this pair:
 * a scene payload is tile-local, and adding the centre without turning it was
 * only ever right while every tile stood at yaw 0.
 */
export function tileToWorld(tile: Tile, lx: number, lz: number,
                            ly = 0): THREE.Vector3 {
  const c = Math.cos(tile.yaw);
  const s = Math.sin(tile.yaw);
  return new THREE.Vector3(
    tile.center.x + lx * c + lz * s,
    tile.center.y + ly,
    tile.center.z - lx * s + lz * c);
}

/** World (x, z) → tile-local — the inverse of `tileToWorld` (a turn by −yaw).
 *
 *  The four lines of arithmetic live in `@anima/scene-render`
 *  (`worldToLocalXZ`): the map editor needs the same turn for its footprints,
 *  and the scatter's footprint exclusion (finding B18) is the third caller —
 *  three copies of one mapping is exactly how the two renderers drift apart. */
export function worldToTile(tile: Tile, x: number, z: number
): { x: number; z: number } {
  return worldToLocalXZ(tile.center.x, tile.center.z, tile.yaw, x, z);
}

/**
 * Does this tile's FOOTPRINT cover a world point (contract v6 Nr. 6)?
 *
 * The point is turned into the tile's own frame first (`worldToTile`, the
 * inverse of § A1.1) and then ray-cast against the drawn polygon — the client's
 * twin of `world_geometry.boundary_contains`, down to the half-open edge rule,
 * so the two sides never disagree about which place a metre belongs to. A tile
 * without a boundary has no area and covers nothing.
 */
export function tileContains(tile: Tile, x: number, z: number): boolean {
  if (!tile.boundary) return false;
  const p = worldToTile(tile, x, z);
  return pointInPolygon(p.x, p.z, tile.boundary);
}

/**
 * The axis-aligned WORLD box of a tile's footprint — every outline point turned
 * by § A1.1 and stretched over. `null` without a boundary.
 *
 * The successor of "a square of edge w turned by yaw spans w/2·(|cos|+|sin|)":
 * that identity holds for a square only, and a drawn outline is not one.
 */
export function tileWorldBounds(tile: Tile
): { minX: number; minZ: number; maxX: number; maxZ: number } | null {
  if (!tile.boundary) return null;
  let minX = Infinity; let minZ = Infinity;
  let maxX = -Infinity; let maxZ = -Infinity;
  for (const [lx, lz] of tile.boundary) {
    const p = tileToWorld(tile, lx, lz);
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.z < minZ) minZ = p.z;
    if (p.z > maxZ) maxZ = p.z;
  }
  return { minX, minZ, maxX, maxZ };
}

/** Turn a tile-local DIRECTION into a world direction (no translation). */
export function tileDirToWorld(tile: Tile, lx: number, lz: number
): { x: number; z: number } {
  const c = Math.cos(tile.yaw);
  const s = Math.sin(tile.yaw);
  return { x: lx * c + lz * s, z: -lx * s + lz * c };
}

type TileStyle = 'forest' | 'road' | 'grass' | 'water' | 'cafe' | 'house' | 'highrise' | 'generic';

/** AV3D-7: tolerantes Terrain-Vokabular (de/en). Leer -> null. */
function terrainKind(raw: string | undefined): TileStyle | null {
  const t = (raw || '').toLowerCase().trim();
  if (!t) return null;
  if (/water|see|lake|meer|ocean|fluss|river|teich|pond/.test(t)) return 'water';
  if (/forest|wald|wood|park/.test(t)) return 'forest';
  if (/road|street|stra|weg|path|asphalt/.test(t)) return 'road';
  if (/grass|wiese|meadow|feld|field|gras/.test(t)) return 'grass';
  return null;
}

/** AV3D-1: map3d.style -> Gebäudestil. Leer/unbekannt -> null. */
function styleKind(raw: string | undefined): TileStyle | null {
  const s = (raw || '').toLowerCase().trim();
  if (!s) return null;
  if (/tower|highrise|high-rise|hochhaus|skyscraper/.test(s)) return 'highrise';
  if (/shop|cafe|caf|store|laden|bar|restaurant/.test(s)) return 'cafe';
  if (/house|haus|home|residence|cottage|villa/.test(s)) return 'house';
  if (/generic|hall|block|building/.test(s)) return 'generic';
  return terrainKind(s); // erlaubt auch style: "lake"/"forest"
}

/** One placed model of the mounted scene, kept for tier swapping (Etappe 3,
 *  plan-3d-lod-und-betreten.md): the spec, the URL that is actually standing
 *  and the object in the graph. `mountScene` writes the records,
 *  `setSceneModelTier` (sceneRecipe.ts) swaps them in place — the old mesh
 *  stays visible until the new one is in. */
export interface PlacedSceneModel {
  spec: SceneModelSpec;
  /** URL the standing object was loaded from ('' = no mesh / placeholder) */
  url: string;
  /** URL a swap in flight wants — a newer wish supersedes an older answer */
  wantUrl?: string;
  object: THREE.Object3D | null;
  /** group the object hangs in (room group / interior); building models hang
   *  in tile.group and go through applySceneBuilding instead */
  parent?: THREE.Object3D;
  /** object is the grey placeholder box (own geometry/material, disposable) */
  placeholder?: boolean;
  /** THE STOREY-0 TERRAIN LIFT this object is currently standing on (§ A16.9).
   *  Carried on the record and not re-derived from the object, because the
   *  height field MOVES: a scene mounted before its fine tiles arrived is
   *  re-lifted by the difference to this number (`reliftScene`), and a
   *  difference needs the old value. 0 = no lift applied (a building model, a
   *  declared storey, a field that had nothing to say). */
  lift: number;
  /** THIS PLACEMENT'S ENTRY IN `tile.surfaces` (v6), where it has a baked
   *  lattice. Held here so the ONE funnel that lifts a placement
   *  (`reliftPlacement`) writes the lift onto the lattice in the same move —
   *  the surface stands where its model stands, and looking the entry up by a
   *  key would only invite the two to drift. */
  surface?: PlacedSurface;
  /** THE UNDERWATER GHOST of this placement (`scene/submergedGhost.ts`), or
   *  absent while the object has never been gated. A prop whose base stands
   *  under the local water level is redrawn tinted below the waterline, so a
   *  crate on a lake bed or a jetty post is visible through the opaque water.
   *  It belongs to the OBJECT: a tier swap replaces the mesh and the ghost with
   *  it. */
  ghost?: SubmergedGhost;
  /** THE MATERIAL CLONES this placement's texture slots created (§ B2 v5,
   *  `applySlotMaterials`), absent where the spec fills none. They exist PER
   *  PLACEMENT on purpose — the loader cache shares ONE group between all
   *  copies of a prop — and each owns the texture it loaded, so the list is
   *  disposed when the object goes (tier swap, unmount). */
  slotMats?: THREE.Material[];
}

/**
 * ONE DOOR PROP of the mounted scene, ready to swing (v5, user decision
 * 2026-08-27).
 *
 * `placeModelSpec` puts the group's ORIGIN on the hinge edge (`measure:
 * "fit"`, § B2), so opening the door is `group.rotation.y = baseYaw + angle`
 * and nothing else — no pivot, no second object, no geometry a renderer could
 * get wrong. `angle` is PURE VIEW STATE: it is never persisted, never sent to
 * the server and lives and dies with the mount that built it.
 */
export interface SwingingDoor {
  /** The placed group — its origin IS the hinge. */
  group: THREE.Object3D;
  /** Sign of a positive y rotation that opens this door OUTWARD, straight from
   *  `models[].door.swing`: +1 for a left hinge, −1 for a right one. */
  swing: 1 | -1;
  /** Centre of the threshold in TILE-LOCAL metres (`doorways[opening]
   *  .at_world`) — "the avatar stands in front of it" is measured against
   *  this, not against the hinge the group hangs on. */
  at: { x: number; z: number };
  /** Storey of the threshold (`doorways[opening].level`). Doors STACK — a
   *  front door and the balcony door above it share their (x, z) — so the
   *  proximity test is gated on the storey the AVATAR is on, the one its room
   *  sits on. Not `levelFilter`: that is the storey the CAMERA shows, and the
   *  two come apart every time the view is held on another floor. */
  level: number;
  /** The rooms the threshold joins, in payload order — the same list
   *  `applyDoorLocks` hands to `game/locks.doorwayLock`, so a locked door and
   *  a red threshold can never disagree. */
  rooms: string[];
  /** `group.rotation.y` as it was left when the door was registered, read
   *  ONCE and added to every frame instead of accumulated onto the object.
   *  Used ONLY in the no-leaf branch — a mesh Blender has split swings its
   *  `swingNode` about `swingAxis` and never touches the group's yaw.
   *
   *  Today it is ALWAYS 0, and that is not an accident to be tidied away:
   *  `place()` returns its OUTER group, and the placement yaw sits on an inner
   *  one, precisely so that the outer group's own axis runs through the hinge.
   *  Turning that inner group here instead would move the axis off the hinge
   *  and the door would swing about its middle. The field is read rather than
   *  assumed so the swing survives a `place()` that one day seats the yaw
   *  somewhere else. */
  baseYaw: number;
  /** Current opening angle in radians, signed like `swing`. */
  angle: number;
  /** THE LEAF PIVOT (spec-picture-props.md § 6): when the placed model has a
   *  node `leaf` and the payload a `door.leaf_bbox`, that node hangs in a
   *  pivot group on its hinge edge and ONLY this group turns — the frame
   *  stands still. Absent = the whole `group` swings, as before. Rebuilt on
   *  every tier swap (`retargetDoorProp`), because the node lives in the
   *  mesh that was just replaced. */
  swingNode?: THREE.Object3D;
  /** The axis `swingNode` turns about, in the leaf's parent frame — the
   *  FIXED frame's vertical mapped back through the orientation fix
   *  (`leafPivot` of @anima/scene-render, ruling R13); +y for a fix of 0. */
  swingAxis?: THREE.Vector3;
  /** `door.leaf_bbox` and the spec's `fix_euler` as the payload sent them —
   *  kept so a tier swap can hang the pivot again without the spec in hand. */
  leafBbox?: { min: [number, number, number]; max: [number, number, number] };
  fixEuler?: { x?: number; y?: number; z?: number };
  hinge: 'left' | 'right';
}

/**
 * THE FLOOR OF ONE ROOM of a mounted scene, as the spot derivation reads it.
 *
 * `hull` is the room polygon in TILE-LOCAL metres. On storey 0 it comes from
 * `floor_plan[].polygon_world` (§ A19 no. 3) — the scene frame IS the tile
 * frame — and on a declared storey from the room block's own `outline`, which
 * is the same polygon the plate up there is drawn from.
 *
 * `declared` is the floor the payload STATES for this room in tile-local
 * metres: a storey plate, the `overlay.y` of a zone lying on an area model, or
 * a diorama's `walk_y_world`, which outranks both. It is absent exactly where
 * the payload states nothing — a level-0 room without a declaration, whose
 * floor is the terrain and is asked of the height sampler point by point.
 *
 * There is no storey datum in here: a marker already arrives as its own lift
 * OVER that datum (`mountScene` writes `offsetY = y_world − levels[].floor_y`),
 * so keeping the datum a second time would be one number in two places.
 */
export interface RoomFloor {
  hull: [number, number][];
  declared?: number;
}

/**
 * ONE staircase of a scene, in WORLD coordinates — the payload's own `stairs`
 * block turned into the tile's frame (addendum "Treppen v2"), never measured
 * back out of the `stair_*` boxes.
 *
 * The two LANDINGS are what a route needs: they stand on the pad's top face
 * (= that storey's floor plus the prop clearance) exactly like an elevator
 * stop, and `foot.level + 1 === head.level` always holds — a flight spans a
 * single storey.
 *
 * The RUN is what a guided climb needs: `at` is the foot of the first tread,
 * `dir` the unit climb direction in world xz, `runM` its length and `widthM`
 * its width across. Two numbers are deliberately NOT kept, because they are
 * the same fact twice over: the climb is `head.pos.y − foot.pos.y`, and the
 * tread is `runM / steps`.
 */
export interface StairWorldLink {
  foot: { level: number; pos: THREE.Vector3 };
  head: { level: number; pos: THREE.Vector3 };
  /** Foot of the RUN (where the first tread begins) — not the foot LANDING,
   *  which lies a pad's half plus a gap behind it. */
  at: THREE.Vector2;
  /** Unit climb direction in world xz. */
  dir: THREE.Vector2;
  runM: number;
  widthM: number;
  steps: number;
  /** The `widthM × runM` rectangle the flight covers, world xz — the floor it
   *  eats, for whoever has to ask whether a point is ON the flight. */
  footprint: [number, number][];
}

/**
 * A vertical connection AS A CLICK TARGET (bug round 2026-08-30): the `extras`
 * boxes of ONE staircase flight, or all parts of the lift, gathered in one
 * group so the pointer can light them (`highlightProp`) and a click can name
 * what it hit.
 *
 * The grouping follows the payload's own: the lift is ONE structure across all
 * storeys (which is why `applyLevelDisplay` never filters extras), while every
 * flight is its own target — `extras[].stair` says which, and it is the index
 * into the scene's `stairs` block, not a saved identity.
 *
 * Whether a target may be used from where the avatar stands is NOT decided
 * here: the boxes stay visible on every storey, so hover and click ask the
 * same storey condition `stairsAt`/`elevatorAt` ask (main.ts).
 */
export interface VerticalTarget {
  kind: 'stairs' | 'elevator';
  /** Index of the flight in `Tile.stairs`; −1 for the lift. */
  flight: number;
  group: THREE.Group;
}

export interface Tile {
  loc: WorldLocation;
  /** Fassaden mit Fensterraster — leuchten nachts (emissive) */
  facadeMats?: THREE.MeshStandardMaterial[];
  group: THREE.Group;
  /** Centre of the footprint in world metres — `group.position` (§ A1.1). */
  center: THREE.Vector3;
  /** THE footprint outline in TILE-LOCAL metres (contract v6) — what `tileAt`
   *  tests a point against. `null` = the location has no area at all, and then
   *  this tile claims no point on the plane. */
  boundary: [number, number][] | null;
  /** Enclosed area of `boundary` in m². THE tie-breaker where footprints
   *  overlap: the smallest area wins (v6 Nr. 6). 0 without a boundary. */
  area: number;
  /** Width of the footprint's BOUNDING BOX in world metres (derived from
   *  `boundary`, v6 Nr. 2). The ONE length this tile is scaled by: texture
   *  repeat, selection ring, the occlusion corridor and the basement hole all
   *  come off it — containment and specificity come off `boundary`/`area`. */
  width: number;
  /** Footprint rotation in radians — `group.rotation.y`, § A1.1 sign. */
  yaw: number;
  isBuilding: boolean;
  /** Is this place OPEN GROUND rather than a built plate (`isAreaLocation`)?
   *  Decides how far the terrain pace and move-animation rule reaches into
   *  the footprint (`game/walk.groundScope`). */
  isArea: boolean;
  /** Named nature location (forest, lake, meadow, road) — no building, just
   *  ground with a label; room labels stay off there. */
  natureSite?: boolean;
  height: number;
  interior: THREE.Group | null;
  interiorLabels: CSS2DObject[];
  /** prozedurale Außenhülle — wird durch ein Server-Modell (AV3D-9) ersetzt */
  shell?: THREE.Group;
  /** bereits eingewechseltes Server-Gebäudemodell */
  serverModel?: THREE.Group;
  /** `display: 'ground'` — das Modell IST die Location (Fläche, Dorf, See):
   *  es blendet beim Reinzoomen nie weg, sondern bekommt Löcher. Kommt aus
   *  der Spec, nicht aus dem Vorhandensein von cutouts. */
  modelIsGround?: boolean;
  /** `display: 'shell_area'` (§ B6 Nr. 10) — Flächen-Location im Detail-Modus:
   *  Anker wie `ground`, aber das Modell blendet beim Reinzoomen aus wie eine
   *  Hülle und gibt die komponierte Detailszene darunter frei. Der Kachelboden
   *  folgt dabei dem Fade, statt fest sichtbar oder fest weg zu sein. */
  modelIsShellArea?: boolean;
  /** `walk_y_world` des Location-Modells (§ B) — die vom Server DEKLARIERTE
   *  Standhöhe. `tileGroundY` misst den Dachschutz eines Gebäudes daran statt
   *  an einer festen Marke; bei Flächen-Modellen spielt sie keine Rolle. */
  modelWalkY?: number;
  /** prozedurale Deko (Bäume) — weicht einem Server-Modell */
  /** Namens-Label — Höhe wird beim Modell-Tausch nachgeführt */
  labelObj?: CSS2DObject;
  shellMats: THREE.MeshStandardMaterial[];
  roofParts: THREE.Object3D[];
  roofMats: THREE.MeshStandardMaterial[];
  roomCenters: Map<string, THREE.Vector3>;
  /** THE door of a room, in world coordinates (key: room ID): its outside
   *  door, else its first — read from the payload's `doorways[]`, never
   *  derived (plan-betreten-und-tueren.md § 4.1). The floor sampling shoots
   *  its reference ray there; only x/z matter for that, so the y is the wall
   *  foot the payload names and is not lifted afterwards. */
  roomDoors: Map<string, THREE.Vector3>;
  /** THE STOREY-0 FLOORS of the mounted scene, as the spot derivation reads
   *  them (§ A19 no. 3, "Ein Boden" E5b): the room hull in TILE-LOCAL metres
   *  plus the floor the payload DECLARES for it, where it declares one. Filled
   *  from `floor_plan` (level 0), from the storey plate (level != 0) and from
   *  the overlay block (a zone on an area model); `deriveRoomSpots` turns each
   *  entry into centre, stands and furniture. It replaced the holder groups the
   *  6 x 6 raycast raster was shot from. */
  roomFloors: Map<string, RoomFloor>;
  /** free stands in the room (world coordinates at floor height) */
  roomSpots: Map<string, THREE.Vector3[]>;
  /** detected sit surfaces (furniture height, small faces) */
  roomSitSpots: Map<string, THREE.Vector3[]>;
  /** detected lie surfaces (furniture height, large contiguous faces) */
  roomLieSpots: Map<string, THREE.Vector3[]>;
  /** The PLACES of the location (plan-posen-plaetze.md § 4): room → marker
   *  id → entry with its slot points in world metres (`PlaceEntry`). Keyed by
   *  the marker ID, never by a clip kind: which character sits where is the
   *  server's word (`MapCharacter.place`), and the client only looks the
   *  named seat up. One entry map hangs under the room id AND the room name.
   *  `fixed` (prop markers) = height finished as composed, the floor sampling
   *  leaves it alone; a room marker is re-derived against the room's floor by
   *  `deriveRoomSpots`. */
  roomMarkers: Map<string, Map<string, PlaceEntry>>;
  /** the whole room group per layout room (for the focus mode) */
  roomGroups: Map<string, THREE.Group>;
  /** Room rectangles in TILE-LOCAL metres (E4: a turned rectangle is not a
   *  rectangle, so readers turn their query point with `worldToTile` instead) */
  roomRects: Map<string, { x: number; z: number; w: number; d: number }>;
  /** Etage je Raum (Schlüssel: ID und Name) */
  roomLevels: Map<string, number>;
  /** dauerhaft sichtbare Räume (layout.always_visible; Figuren stehen dort
   *  auch in der Übersicht) */
  alwaysVisibleRooms: Set<string>;
  /** Fahrstuhl-Haltepunkte je Etage (Welt-Koordinaten), AV3D-12 */
  elevatorStops?: Map<number, THREE.Vector3>;
  /** Staircases of this scene, one entry per COMPLETE foot/head pair of the
   *  payload (world coordinates). The second vertical connection next to the
   *  elevator: where a staircase links the two storeys, a route prefers it. */
  stairs?: StairWorldLink[];
  /** The lift and the flights as HOVER/CLICK targets — one group of extras
   *  each (`VerticalTarget`). Undefined while the scene has neither. */
  verticalTargets?: VerticalTarget[];
  /** Grundriss-Wandstücke mit Außennormale (Welt-XZ) — fürs Blickrichtungs-Culling */
  outlineWalls: { mesh: THREE.Mesh; level: number; mid: THREE.Vector2; normal: THREE.Vector2 }[];
  /** Etagen-Bodenplatten des Grundrisses (für Boden-Farbübernahme) */
  levelSlabs: Map<number, THREE.Mesh>;
  /** THE FLOORS OF THE RECIPE, as the walk rule reads them (§ B1 addendum
   *  2026-08-20): one entry per built plate — its outline in TILE-LOCAL metres
   *  and its `top_y`. `tileWalkY` stands a figure on the highest one whose
   *  hull contains the point, which is the surface the payload already puts
   *  the props and markers of that room on. Empty for a tile without a
   *  recipe interior (an area model, a bare pin). */
  walkPlates: WalkPlate[];
  /** THE DECLARED FLOORS of this scene (§ B6 no. 7, user finding 2026-08-20):
   *  one entry per room whose diorama spec carries a `walk_y_world` — that
   *  height plus the room's hull in TILE-LOCAL metres. `tileWalkY` asks this
   *  list FIRST and for every display mode: the admin's dial is a statement
   *  about the room's modelled floor and outranks the storey plate under it.
   *  It is the same number `deriveRoomSpots` stands the NPC spots on, so
   *  figure and spot cannot end up on two floors. */
  declaredFloors: DeclaredFloor[];
  /** THE BAKED MODEL SURFACES of this scene (v6, spec-surface-height): one
   *  entry per placed model that ships a `surface` lattice — every room
   *  diorama and every `walkable` prop. RUNG 0 of `tileWalkY`, above the
   *  declaration: the highest lattice answering at the point wins (a crate on
   *  a rock). Built from the SPEC NUMBERS, never from three's matrices — the
   *  spec decides, the renderer only re-measures. Each entry carries its own
   *  `lift` (§ A16.9, written by `reliftPlacement`), its `level` and its
   *  `roomId`, because WHICH lattices may answer depends on who is asking:
   *  the ground ladder takes storey 0, a room's stands take that room. */
  surfaces: PlacedSurface[];
  /** Wall materials per storey (for the storey switch). A list, because
   *  textured walls need one material with its own repeat per piece (scene
   *  recipe) — the legacy floor plan carries exactly one. */
  levelWallMats: Map<number, THREE.MeshStandardMaterial[]>;
  /** Currently chosen storey of the interior view (switch; default ground) */
  levelFilter: number;
  /** Pull the in-world storey switch's display state out of `levelFilter`
   *  (its marking and its height). Whoever sets `levelFilter` from outside —
   *  the lift, the avatar changing storey — calls this with it; a tile without
   *  a scene or with a single storey has no switch. */
  levelSwitch?: () => void;
  /** als outdoor markierte Räume (liefern keine Boden-Farbe fürs Gebäude) */
  roomOutdoor: Set<string>;
  /** This tile's scene uses a storey < 0 (derived from the payload, set by
   *  mountScene). Read by the camera rule that opens a basement view. */
  hasBasement?: boolean;
  /** Flächen-Location (plan-area-locations.md): das Location-Modell bleibt in
   *  der Innenansicht stehen und bekommt stattdessen Löcher. Das Handle
   *  schaltet sie mit dem Crossfade — Fernsicht intaktes Modell, Innenansicht
   *  Löcher — und gibt beim Remount seine Material-Klone frei. */
  cutouts?: CutoutHandle;
  /** Modell-Platzierungen der montierten Szene (Stufen-Tausch, Etappe 3) */
  placedModels?: PlacedSceneModel[];
  /** The DOOR PROPS of the mounted scene (v5), one per `models[]` entry with a
   *  `door` block. Pure view state and part of the mount: `unmountScene` drops
   *  the list with the groups it points at. */
  doorProps?: SwingingDoor[];
  /** 0..1 — Kachel ist als Kamera-Verdecker ausgeblendet */
  occl: number;
  fade: number;
  fadeTarget: number;
}

// THE SCALE ANCHOR STORE IS GONE (E4 task 3). It held two numbers per
// location: `k` (world metres per real metre) and the storey height in world
// metres. Since k = 1 (task 1) the first is the constant 1 and the second is
// simply `map3d.storey_height_m` — and the accessors that made anything of
// them (`roomFigureScale`, `storeyHeight`, `locationAnchor`) had no readers
// left once the double scale went. The payload's `storey_m` is read where it
// is needed, in `sceneRecipe.ts`, out of the payload itself.

function detectStyle(loc: WorldLocation): TileStyle {
  // Priorität: map3d.style (AV3D-1) > terrain (AV3D-7) > Namens-Heuristik
  const explicit = styleKind(loc.map3d?.style) ?? terrainKind(loc.terrain);
  if (explicit) return explicit;

  const n = (loc.name || '').toLowerCase();
  if (loc.passable || loc.template_location_id) {
    if (/forest|wald|park|wood/.test(n)) return 'forest';
    if (/street|stra|road|weg|alley/.test(n)) return 'road';
    return 'grass';
  }
  if (/high-rise|highrise|tower|hochhaus|skyscraper|building/.test(n)) return 'highrise';
  if (/caf|bar|restaurant|shop|laden|store|diner/.test(n)) return 'cafe';
  if (/residence|house|haus|home|cottage|villa/.test(n)) return 'house';
  return 'generic';
}

/**
 * Is this location OPEN GROUND rather than a built plate? The client twin of
 * `world_geometry.is_area_location` (user decision 2026-08-13, round 2 of the
 * E8 acceptance) — it decides how far the terrain pace and move-animation
 * rule reaches into the footprint (`game/walk.groundScope`).
 *
 * Two AUTHORED flags off the worldmap entry say it, and nothing else:
 *  - `passable` — a transit location one walks THROUGH (road/forest clones);
 *  - `map3d.area_model` — "the model IS the ground of this place"
 *    (`area_detail` is only ever set on top of it, so it is covered).
 *
 * Deliberately NOT `detectStyle`: that vocabulary guesses a procedural
 * fallback TEXTURE from a name, and a guess from a word must not decide how
 * fast a character walks. A lake meant to be waded says so with the flag.
 */
export function isAreaLocation(loc: WorldLocation): boolean {
  return !!loc.passable || !!loc.map3d?.area_model;
}

const loader = new THREE.TextureLoader();

/** The server's global surface library (kind -> surface). A new ground kind is
 *  a new library entry, NOT a client change. The built-in procedural stand-ins
 *  went with the footprint plate ("Ein Boden" E3): the only reader left is the
 *  scene recipe, and a payload primitive names a kind the library has. */
interface SurfaceEntry {
  url?: string; sizeM: number;
  /** Materialklasse der Art (Bibliothek) — Wasser wird anders beleuchtet als
   *  Gras, und zwar in BEIDEN Renderern gleich (@anima/scene-render). */
  material?: SurfaceMaterialSpec | null;
}
const serverSurfaces = new Map<string, SurfaceEntry>();
export function setSurfaceTextures(list: { kind: string; url?: string; size_m?: number;
                                           material?: SurfaceMaterialSpec | null }[]) {
  for (const t of list) {
    serverSurfaces.set(t.kind.toLowerCase(), {
      url: t.url, sizeM: t.size_m || 3, material: t.material ?? null });
  }
}

/** Materialklasse einer Art ('' / unbekannt = matt, also wie bisher). */
export function surfaceMaterialSpec(kind: string | undefined): SurfaceMaterialSpec | null {
  return serverSurfaces.get((kind || '').toLowerCase())?.material ?? null;
}

export function hasSurfaceTexture(kind: string): boolean {
  return serverSurfaces.has(kind);
}

// SURFACE COMPOSITIONS ("blend", e.g. a coast fading towards the water) are
// GONE with the grid (E4 task 3). They were baked per tile out of the terrain
// kinds of the FOUR NEIGHBOURING CELLS — a neighbourhood built from integer
// arithmetic, which § A1.1 strikes: "distance is a distance, neighbourhood is
// nearness". In the metre world the ground between the locations is the painted
// terrain of `/play/terrain` (`scene/ground.ts`, task 2), and a shoreline is a
// polygon an admin draws, not a texture the client guesses from a grid. Gone
// with it: `setTerrainGrid`, `gridSurfaceKind`, the noise/zone baker and the
// canvas compositing.

// Die Boden-Kachelung der Etagen-/Raumplatten läuft seit dem Szenen-Rezept
// über `surfaceFor` (Kind kommt als `texture_kind` mit dem Primitiv, Maßstab
// als size_m × k) — die beiden früheren Sonder-Caches dafür sind entfallen.

/** Surface-Texturen für die Szenen-Primitive (jedes Stück klont sie und setzt
 *  eigene repeat-Werte): Klone eines noch ladenden Bildes blieben leer,
 *  daher gibt surfaceFor nur FERTIG geladene Texturen heraus — der Mount
 *  ruft vorher preloadSurfaceTexture für die benötigten Kinds. */
const recipeSurfaceCache = new Map<string, THREE.Texture>();
const recipeSurfacePending = new Map<string, Promise<void>>();
export function preloadSurfaceTexture(kind: string | undefined): Promise<void> {
  const key = (kind ?? '').toLowerCase();
  const entry = serverSurfaces.get(key);
  if (!entry?.url || recipeSurfaceCache.has(key)) return Promise.resolve();
  let pending = recipeSurfacePending.get(key);
  if (!pending) {
    pending = loader
      .loadAsync(entry.url)
      .then((tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        recipeSurfaceCache.set(key, tex);
      })
      .catch(() => { /* Fallback-Farben der Hülle */ })
      .finally(() => recipeSurfacePending.delete(key));
    recipeSurfacePending.set(key, pending);
  }
  return pending;
}

/** Aktive Surface-Textur eines Kinds für Platten und Wände der Szene.
 *  Ohne eigenen Eintrag fällt der Boden auf das globale "floor"-Kind zurück
 *  (Vertrag: „ohne Eintrag/Textur wie bisher"); Wände haben kein globales
 *  Kind -> null = Farb-Fallback aus `style`. */
export function surfaceFor(
  kind: string | undefined,
  use: 'floor' | 'wall'
): { texture: THREE.Texture; sizeM: number } | null {
  const chain = use === 'floor' ? [kind, 'floor'] : [kind];
  for (const c of chain) {
    const key = (c ?? '').toLowerCase();
    const entry = serverSurfaces.get(key);
    const tex = recipeSurfaceCache.get(key);
    if (entry && tex) return { texture: tex, sizeM: entry.sizeM };
  }
  return null;
}

// THE TILE'S OWN GROUND DIED HERE ("Ein Boden" E3, plan § 3.1). Until 2026-08-21
// every tile drew a second ground of its own: a footprint plate draped over the
// world field (`plateGeometry`/`groundPlate`, y 0.04), a socle under a building
// model (0.045), a backstop ladder that shoved that plate under a mounted scene
// (`tilePlateY` −0.05/−0.13), a depth-bias rung in front of the terrain
// (`PLATE_POLYGON_OFFSET` −33) and a staleness probe that re-draped it whenever
// the height window sharpened (`plateGroundSamples`/`relevelTiles`). All of it
// existed to hide the seam between two independent grounds. There is one ground
// now — the CDLOD terrain composites the painted layers per texel and runs on
// under every location — so the plate has nothing left to cover and every
// crutch that kept it in front of the landscape goes with it, without
// replacement. The tile still owns everything ABOVE the ground: label, height,
// rooms, scene primitives, models.


// `makeTree` stand hier bis 2026-08-02: prozedurale Kegel-Bäume auf
// forest-Kacheln. Seit Wald & Co. ihre Detailszene aus GESTREUTEN
// Bibliotheks-Props beziehen (plan-area-detail-scenes.md), sind generische
// Deko-Elemente für ALLE Geländearten gestrichen (User-Vorgabe) — das
// Gelände sagt nur noch die Bodentextur, was drauf steht, sagt die Welt.


/** The tile builds only the OUTSIDE, and since "Ein Boden" E3 that is the LABEL
 *  and the reading height it hangs at — nothing else. The tile draws no ground
 *  of its own any more: the terrain under it IS the ground of the place (plan
 *  § 3.1), painted per texel by the one terrain material. The procedural
 *  building shell died before it with the Prop-Welt programme (user decision
 *  2026-08-19). The interior (plates, walls, elevator, rooms, models) comes
 *  entirely from the scene recipe; `mountScene` (sceneRecipe.ts) builds it into
 *  these same tile fields. A location without a recipe (404) has, by server
 *  definition, neither a room layout nor an outline nor a building model —
 *  there is simply nothing to unfold. */
export function buildTile(loc: WorldLocation): Tile {
  const style = detectStyle(loc);
  const isBuilding = !(loc.passable || loc.template_location_id);
  const isArea = isAreaLocation(loc);
  // THE footprint (contract v6, § A1.1): the drawn polygon `boundary` in local
  // metres, pinned at (pos_x, pos_z) and turned by `yaw_deg`. Position AND
  // rotation sit on the group, so every child is placed in tile-local metres —
  // the same frame the scene payload speaks. The callers filter on
  // `footprintCentre` (`placeableOf`, `addTile`), so an unplaced location never
  // gets this far; if one ever does it says so rather than joining a silent
  // heap on the origin.
  const boundary = footprintBoundary(loc);
  const width = footprintWidth(loc);
  const yaw = footprintYaw(loc);
  const placed = footprintCentre(loc);
  if (!placed) {
    console.warn(`[tiles] ${loc.name || loc.id}: built without a position`
      + ' (pos_x/pos_z) — the tile stands on the world origin (§ A1.1)');
  }
  const center = placed ?? new THREE.Vector3(0, 0, 0);
  const group = new THREE.Group();
  group.position.copy(center);
  group.rotation.y = yaw;
  group.userData.locationId = loc.id;

  const tile: Tile = {
    loc, group, center, boundary, area: polygonArea(boundary),
    width, yaw, isBuilding, isArea, height: 0,
    interior: null, interiorLabels: [], shellMats: [], roofParts: [], roofMats: [],
    roomCenters: new Map(), roomDoors: new Map(),
    roomFloors: new Map(), roomSpots: new Map(),
    roomSitSpots: new Map(), roomLieSpots: new Map(), roomMarkers: new Map(),
    roomGroups: new Map(), roomRects: new Map(), roomLevels: new Map(), alwaysVisibleRooms: new Set(),
    outlineWalls: [], levelSlabs: new Map(), levelWallMats: new Map(), walkPlates: [],
    declaredFloors: [], surfaces: [],
    levelFilter: 0, roomOutdoor: new Set(),
    fade: 0, fadeTarget: 0, occl: 0,
  };

  // Benannte Natur-Location (z.B. See, Waldlichtung): kein Gebäude, aber Label/Räume
  const natureSite = isBuilding && (style === 'water' || style === 'forest' || style === 'grass' || style === 'road');
  tile.natureSite = natureSite;

  const addLabel = () => {
    const el = document.createElement('div');
    el.className = 'loc-label';
    el.textContent = loc.name;
    const label = new CSS2DObject(el);
    label.position.set(0, tile.height + 2.2, 0);
    group.add(label);
    tile.labelObj = label;
  };

  // The three branches only set the READING HEIGHT of the label now: a
  // transit place hangs it low, a named nature site a hand higher, a building
  // at a fixed 4 m until its server model reports a real one
  // (`applySceneBuilding`). The ground each branch used to draw for itself is
  // the terrain (see the note above `buildTile`).
  if (!isBuilding) {
    tile.height = style === 'forest' ? 3 : 0.3;
  } else if (natureSite) {
    tile.height = style === 'forest' ? 3 : 0.6;
    addLabel();
  } else {
    tile.height = 4;
    addLabel();
  }

  tile.facadeMats = tile.shellMats.filter((m) => !!m.emissiveMap);
  return tile;
}


/**
 * THE STANDS OF ONE ROOM, derived from the payload — the successor of the
 * 6 x 6 raycast raster ("Ein Boden" E5b).
 *
 * WHAT IT REPLACES. Until E5b this shot 36 rays down at the room's plate mesh,
 * read the floor out of the dominant 7 cm height bin, repaired that with a
 * reference ray at the door (generated meshes have holes), and called
 * everything within 12 cm of it a stand. Storey 0 draws no plate to ray any
 * more, so the two halves come from where they always belonged: the SHAPE from
 * `floor_plan` (§ A19 no. 3) and the HEIGHT from the one height function at the
 * point being asked about.
 *
 * THE FLOOR, in data rungs only (`roomFloorWorldY`): the BAKED SURFACE where
 * one answers (v6, the same rung 0 `tileWalkY` asks — a spot on a diorama's
 * hillock stands on the hillock), else the room's declared floor where the
 * payload states one (a diorama `walk_y_world`, a storey plate, an overlay
 * zone on an area model), otherwise the TERRAIN — and under a built plot the
 * terrain IS the flat plateau the bake stamped there
 * (§ G5), which is why a built interior comes out level without anybody
 * levelling it.
 *
 * THE FURNITURE STILL GETS MEASURED, and that is not a contradiction: a seat
 * height is a property of an OBJECT, so it is read off the placed prop's own
 * bounding box. What is no longer measured is the FLOOR it is judged against —
 * that is the data height above (`furnitureUse`, `game/ground.ts`).
 */
export function deriveRoomSpots(tile: Tile, roomId: string,
                                props: readonly THREE.Object3D[] = []): void {
  const floor = tile.roomFloors.get(roomId);
  if (!floor) return;
  tile.group.updateMatrixWorld(true);
  const { hull } = floor;
  // The room's OWN frame: the bounding box of its hull carries the raster and
  // the label rectangle, the area centroid carries the centre.
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const [px, pz] of hull) {
    if (px < minX) minX = px;
    if (px > maxX) maxX = px;
    if (pz < minZ) minZ = pz;
    if (pz > maxZ) maxZ = pz;
  }
  if (!Number.isFinite(minX)) return;
  const bx = (minX + maxX) / 2;
  const bz = (minZ + maxZ) / 2;
  const w = Math.max(maxX - minX, 0.5);
  const d = Math.max(maxZ - minZ, 0.5);
  tile.roomRects.set(roomId, { x: bx, z: bz, w, d });

  // THE RASTER FIRST, because the centre may need it. `roomSpotGrid` is the
  // very raster the rays were shot on, with the polygon test where the ray hit
  // used to be (`game/ground.ts`).
  const grid = roomSpotGrid(hull, bx, bz, w, d);
  // THE CENTRE is the area centroid of the drawn hull. On an L-shaped room
  // that point can lie OUTSIDE the room, and then the nearest raster point is
  // taken instead: it is inside by construction (the raster is filtered by the
  // hull) and it is already computed. A full pole-of-inaccessibility would
  // refine that by a few centimetres and cost a grid search per room — the
  // consumers are a huddle, a label and a walk goal, none of which can tell
  // the difference.
  const cen = polygonCentroid(hull);
  const inside = cen && pointInPolygon(cen.x, cen.z, hull) ? cen : (grid[0] ?? null);
  const cx = inside ? inside.x : bx;
  const cz = inside ? inside.z : bz;

  const floorAt = (lx: number, lz: number) => roomFloorWorldY(tile, roomId, floor, lx, lz);
  const floorY = floorAt(cx, cz);
  // The centre, ONE instance under id AND name — the readers key by both.
  const centre = tileToWorld(tile, cx, cz, 0).setY(floorY + WALK_CLEARANCE_M);
  tile.roomCenters.set(roomId, centre);
  const roomName = tile.loc.rooms.find((r) => r.id === roomId)?.name;
  if (roomName) tile.roomCenters.set(roomName, centre);

  // THE STANDS, each at ITS OWN ground and gated by the room's floor: a point
  // whose ground runs more than `SPOT_FLAT_M` away from the room's own floor is
  // the hillside an open zone happens to climb, not part of that floor. Under a
  // built room the gate is inert — the plateau is flat to the millimetre.
  const spots: THREE.Vector3[] = [];
  for (const g of grid) {
    const y = floorAt(g.x, g.z);
    if (Math.abs(y - floorY) > SPOT_FLAT_M) continue;
    spots.push(tileToWorld(tile, g.x, g.z, 0).setY(y + WALK_CLEARANCE_M));
  }

  // SIT / LIE: the top face of a placed prop, measured on the prop. Its own
  // bounding box says how high and how large the surface is; `furnitureUse`
  // says what a 1.70 m figure can do with it.
  const sit: THREE.Vector3[] = [];
  const lie: THREE.Vector3[] = [];
  const box = new THREE.Box3();
  for (const obj of props) {
    if (!obj) continue;
    box.setFromObject(obj);
    if (box.isEmpty()) continue;
    const use = furnitureUse(floorY, box.max.y,
                             box.max.x - box.min.x, box.max.z - box.min.z);
    if (!use) continue;
    const at = new THREE.Vector3((box.min.x + box.max.x) / 2,
                                 box.max.y + WALK_CLEARANCE_M,
                                 (box.min.z + box.max.z) / 2);
    (use === 'lie' ? lie : sit).push(at);
  }

  const put = (map: Map<string, THREE.Vector3[]>, list: THREE.Vector3[]) => {
    if (!list.length) return;
    map.set(roomId, list);
    if (roomName) map.set(roomName, list);
  };
  put(tile.roomSpots, spots);
  put(tile.roomSitSpots, sit);
  put(tile.roomLieSpots, lie);

  // MARKER HEIGHTS sit on the room's floor plus their own lift over the storey
  // datum the composer measured them against — `offsetY` IS `y_world − datum`
  // (`mountScene`), so this is the composed height with the room's real floor
  // put under it. On a built ground floor `floorY` is the storey datum and the
  // line reproduces the payload exactly; where the ROOM declares a floor of its
  // own (a podium, a sunken lounge, a hut in a lake, an upper storey's plate)
  // the marker follows it.
  //
  // WRITTEN ABSOLUTELY, never as a delta: a model tier swap re-derives the same
  // room (`setSceneModelTier`), and a relative correction would apply twice.
  // `fixed` markers (prop markers) are finished and are never touched. Every
  // SLOT of a place is written, in place — a figure the server seated holds
  // a reference to its slot vector and follows it.
  for (const e of tile.roomMarkers.get(roomId)?.values() ?? []) {
    if (e.fixed) continue;
    for (const s of e.slots) s.setY(floorY - e.drop + e.offsetY);
  }
}

/**
 * THE BAKED SURFACE under a tile-local point, in WORLD metres, or `null` where
 * no lattice answers — the ONE place `tile.surfaces` is read (rung 0 of every
 * ladder there is: the walking figure, a room's stands, the avatar indoors).
 *
 * `keep` says WHICH lattices may answer, and that is not a detail: the ground
 * ladder takes storey 0 only, or a figure on an upper floor would be pulled
 * onto the diorama below it; a room's stands take that room's own lattices on
 * any storey. The clearance is NOT added here — every caller carries its own
 * (`WALK_CLEARANCE_M` for a standing height, none for a floor number).
 */
export function bakedFloorAt(tile: Tile, lx: number, lz: number,
                             keep: (e: PlacedSurface) => boolean): number | null {
  if (!tile.surfaces.length) return null;
  const baked = highestSurfaceAt(tile.surfaces.filter(keep), lx, lz);
  return baked === null ? null : tile.center.y + baked;
}

/** The floor of ONE room at a tile-local point, in WORLD metres: the baked
 *  surface where one answers, else the payload's declaration where there is
 *  one, else the terrain. `NaN` from a sampler that has nothing to say reads
 *  as the tile's own datum — a room must not put its stands at no height.
 *
 *  RUNG 0 IS THE SAME SAMPLER `tileWalkY` asks, in the same order (ruling R1,
 *  spec-surface-height) — but scoped to THIS ROOM's own lattices, on any
 *  storey: a room's stands and the figure walking over them must come out on
 *  ONE floor (law 2026-08-20), so a spot on a diorama's hillock stands on the
 *  hillock, while the diorama of the room next door has no say here. The
 *  `SPOT_FLAT_M` gate in `deriveRoomSpots` still keeps the room's stands
 *  together — a lattice cell that runs far away from the room's own floor
 *  drops out of the raster exactly as a climbing piece of terrain does. */
function roomFloorWorldY(tile: Tile, roomId: string, floor: RoomFloor,
                         lx: number, lz: number): number {
  const baked = bakedFloorAt(tile, lx, lz, (e) => e.roomId === roomId);
  if (baked !== null) return baked;
  if (floor.declared !== undefined) return tile.center.y + floor.declared;
  const w = tileToWorld(tile, lx, lz, 0);
  const y = worldGroundAt ? worldGroundAt(w.x, w.z) : NaN;
  return Number.isFinite(y) ? y : tile.center.y;
}

/**
 * WHERE A FIGURE STANDS on this tile, in WORLD metres.
 *
 * Two answers reconciled by `game/ground.standY`: the TILE's own
 * (`tileWalkY` — a declared floor, a storey plate) and the WORLD's (the one
 * height function, `heightAt` via `setWorldGround`). The higher wins, which
 * under a BUILT location is a no-op by construction — the bake stamps the plot
 * flat to exactly the height the tile stands on (§ G5) — and under a natural
 * one is what keeps a figure on the landscape that runs on underneath.
 *
 * No sampler yet answers `NaN`, not a flat 0: a tile whose plateau lies below
 * zero must not be lifted to it by a field that has not arrived.
 */
export function tileGroundY(tile: Tile, at: THREE.Vector3): number {
  return standY(tileWalkY(tile, at),
                worldGroundAt ? worldGroundAt(at.x, at.z) : NaN);
}

/**
 * The TILE's own answer, measured from its centre — DATA ONLY since "Ein
 * Boden" E5b. Split off so the world term above wraps the whole answer instead
 * of one of its exits.
 *
 * FOUR RUNGS, in this order:
 *
 *  0. THE BAKED SURFACES (`bakedFloorAt`, spec-surface-height 2026-08-27):
 *     a diorama's or a walkable prop's measured lattice — the highest one
 *     answering wins (a crate on a rock), and where none answers the ladder
 *     goes on. It outranks the declaration (ruling R1): `walk_y` was the
 *     stand-in for the measurement that did not exist; a crate above the
 *     declared floor forces the order anyway. No `plateCeiling` cap: the head
 *     room is baked in. STOREY 0 ONLY, because this is the GROUND ladder —
 *     outdoors, on a passable tile, in an always-visible zone; a figure on an
 *     upper floor must never be pulled down onto the diorama below it (the
 *     avatar indoors asks its own room instead, `main.roomFloorY`). The mesh
 *     ray of E5b is NOT back — this is DATA the server baked, not a
 *     measurement the renderer takes.
 *  1. A ROOM'S DECLARATION (`declaredFloorAt`, user finding 2026-08-20,
 *     Mondhütte). A room whose diorama spec carries a `walk_y_world` states
 *     where its own modelled floor is — a podium, a sunken lounge, a hut
 *     standing in a lake — and that statement outranks everything, in every
 *     display mode. It is the same number `deriveRoomSpots` stands the room's
 *     NPC spots on, which is what keeps a figure and its room's stands on ONE
 *     surface.
 *  2. THE STOREY PLATES (`recipeFloorAt`), which since E5a are the DECLARED
 *     storeys only: an upper floor, a basement. On the ground floor this
 *     answers `null` and the terrain has the floor. The pick is capped by
 *     `plateCeiling` so a figure on the ground floor is never hoisted onto the
 *     2.90 m slab above it.
 *
 * AND THE LAST RUNG IS THE TERRAIN, which is `lift` — the tile's own centre,
 * i.e. the field at the location's anchor, with the world term of `tileGroundY`
 * over it. The MESH RAY that used to sit between the plates and the ground is
 * DELETED: an area model's walkable surface is the `walk_y_world` it declares,
 * and where it declares none the terrain under it is the ground it was drawn
 * over. Asking the triangles was a way of finding out which of two grounds was
 * in front; there is one.
 */
function tileWalkY(tile: Tile, at: THREE.Vector3): number {
  const lift = tile.center.y;
  // ONE turn into the tile's frame for all three data rungs — they ask about
  // the same point, and turning it three times only invited them to drift.
  const local = worldToTile(tile, at.x, at.z);
  const baked = bakedFloorAt(tile, local.x, local.z, (e) => e.level === 0);
  if (baked !== null) return baked + WALK_CLEARANCE_M;
  if (tile.declaredFloors.length) {
    const declared = declaredFloorAt(tile.declaredFloors, local.x, local.z);
    if (declared !== null) return tile.center.y + declared + WALK_CLEARANCE_M;
  }
  if (tile.walkPlates.length) {
    const info: GroundModelInfo = {
      display: tile.modelIsGround ? 'ground'
        : tile.modelIsShellArea ? 'shell_area' : 'shell',
      walkY: tile.modelWalkY,
    };
    const floor = recipeFloorAt(tile.walkPlates, local.x, local.z,
                                plateCeiling(info));
    if (floor !== null) return tile.center.y + floor + WALK_CLEARANCE_M;
  }
  return lift;
}

/** Kachel als Kamera-Verdecker aus-/einblenden (weich). Nachbarn zwischen
 *  Kamera und einer geöffneten Innenansicht verdecken sonst den Blick. */
export function applyTileOcclusion(tile: Tile, hide: boolean, dt: number) {
  if (tile.occl === 0 && !hide) return;            // Normalzustand — nichts zu tun
  tile.occl = THREE.MathUtils.lerp(tile.occl, hide ? 1 : 0, 1 - Math.exp(-8 * dt));
  if (tile.occl < 0.02 && !hide) tile.occl = 0;
  tile.group.visible = tile.occl < 0.95;           // blendet auch die Labels aus

  tile.group.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      const mat = m as THREE.MeshStandardMaterial;
      if (mat.userData.baseOpacity === undefined) {
        mat.userData.baseOpacity = mat.opacity;
        mat.userData.baseTransparent = mat.transparent;
      }
      if (tile.occl === 0) {
        mat.opacity = mat.userData.baseOpacity;
        mat.transparent = mat.userData.baseTransparent;
      } else {
        mat.transparent = true;
        mat.opacity = mat.userData.baseOpacity * (1 - tile.occl);
      }
    }
  });
}

/** Grundriss-Wände in Blickrichtung ausblenden: Wandstücke, deren
 *  Außenseite zur Kamera zeigt, stehen zwischen Kamera und Innenraum.
 *  Wände oberhalb der gewählten Etage bleiben aus. */
export function applyWallCulling(tile: Tile, camX: number, camZ: number) {
  for (const w of tile.outlineWalls) {
    const cullOk = (camX - w.mid.x) * w.normal.x + (camZ - w.mid.y) * w.normal.y <= 0;
    // Exactly the chosen storey — see applyLevelDisplay. A room of an
    // always-visible (outdoor) zone cannot lose walls to this: the payload
    // emits none for it at all (app/core/scene_recipe.py, `always_visible`
    // or `no_walls` -> no segments).
    w.mesh.visible = cullOk && w.level === tile.levelFilter;
  }
}

/** Apply the storey choice: with the interior open EXACTLY the chosen storey
 *  is there — the ones above and the ones below are gone, not dimmed.
 *
 *  Until the acceptance round of 2026-07-31 the rule was `lv <= levelFilter`,
 *  "everything below as dimmed context". Dimmed, though, was only what the
 *  recipe builds transparent anyway (`opacity_role: upper`): a contour wall of
 *  the ground floor is an OPAQUE material and its `opacity` does nothing at
 *  all — so from the first floor the ground floor's shell stood solid in the
 *  picture. Visibility decides this now, not opacity.
 *
 *  Deliberately NOT storey-filtered (storey-less, not "foreign"): the lift
 *  (shaft, glass, cabin, holding pads) is ONE structure across all storeys,
 *  and the in-world storey switch itself. */
export function applyLevelDisplay(tile: Tile) {
  for (const [lv, slab] of tile.levelSlabs) {
    slab.visible = lv === tile.levelFilter;
    (slab.material as THREE.MeshStandardMaterial).opacity = 1;
  }
  // Only the visible storey gets its full opacity back; the others are gone
  // via `mesh.visible` (applyWallCulling), and setting their opacity would be
  // misleading busywork — an opaque material ignores it.
  for (const mat of tile.levelWallMats.get(tile.levelFilter) ?? []) {
    mat.opacity = 1;
  }
}

/** Raum-Sichtbarkeit: NUR die Etage entscheidet. Räume der gewählten Etage
 *  sind sichtbar, dauerhaft sichtbare Outdoor-Räume immer.
 *
 *  Bis v4 blendete diese Funktion zusätzlich alle Nachbarräume aus, sobald
 *  ein Raum das Bild füllte („Raum-Fokus"). Das ist ersatzlos gestrichen:
 *  der Zielpunkt der Kamera wandert beim Zoomen und Schwenken über den
 *  Boden, wodurch der Fokus bei kleinen Räumen zwischen Nachbarn hin- und
 *  herkippte und Räume samt Diorama und Props winkelabhängig verschwanden.
 *  Seit die Rezept-Wände ihr eigenes Blickrichtungs-Culling haben
 *  (applyWallCulling), braucht es das Ausblenden nicht mehr — auf einer
 *  Etage wird außer Wänden nichts versteckt. */
export function applyRoomVisibility(tile: Tile) {
  for (const [id, rg] of tile.roomGroups) {
    rg.visible = tile.alwaysVisibleRooms.has(id)
      || (tile.roomLevels.get(id) ?? 0) === tile.levelFilter;
  }
}

/** Nachtbeleuchtung: Fenster der Fassaden leuchten (0 = Tag, 1 = Nacht). */
export function applyNightGlow(tile: Tile, night: number) {
  for (const m of tile.facadeMats ?? []) {
    m.emissiveIntensity = night * 1.2;
  }
}

/** Rate of the crossfade below. Since the fade is EVENT-driven (open/close of
 *  the one detail view, Etappe 3) it is a deliberate transition, not a zoom
 *  side effect: τ = 1/4 s reaches 95 % in ~0.75 s — the "~0.8 s feel" of the
 *  plan. The old 6 (≈0.5 s) read as a snap once the camera no longer moved
 *  with it. */
const FADE_RATE = 4;

/** Crossfade Außenansicht <-> Raumansicht (fade 0..1). */
export function applyTileFade(tile: Tile, dt: number) {
  tile.fade = THREE.MathUtils.lerp(tile.fade, tile.fadeTarget, 1 - Math.exp(-FADE_RATE * dt));
  const f = tile.fade;
  // Kein Y-Morph mehr: die Spec liefert EINEN Maßstab, und der gilt in jeder
  // Zoomstufe. Wer hier wieder etwas skaliert, erzeugt genau die Divergenz
  // zur Admin-Vorschau, die 2026-07-28 vermessen wurde.
  const sm = tile.serverModel;
  if (!tile.interior) return;

  // THE GROUND-PLATE BRANCHES OF THIS FADE ARE GONE ("Ein Boden" E3): the tile
  // owns no ground any more, so there is nothing here to ghost for a basement
  // view and nothing to fade in behind a vanishing detail model. Both branches
  // only ever dealt with the tile's own second ground — the terrain below is
  // the world's and stays whole through the crossfade. (The basement's own
  // discard rides on the terrain material now, plan § 3.4.)

  // Flächen-Location: statt das Modell wegzublenden werden seine Löcher
  // geschaltet — derselbe Zustand, andere Wirkung. Fernsicht zeigt die
  // Location intakt, die Innenansicht schneidet Grundriss und abseits
  // stehende Räume heraus, damit das Rezept-Innenleben darin sichtbar wird.
  // Der Detail-Modus hat keine Löcher (sein Innenleben komponiert wie ein
  // Gebäude-Interieur) — dort deckt der Fade des Modells selbst auf.
  if (!tile.modelIsShellArea) tile.cutouts?.setEnabled(f > 0.03);
  // Bei EINGEBLENDETER Unter-Etage tritt das Area-Modell ganz beiseite
  // (User-Befund 2026-07-28: die vergrößerte Boden-Öffnung war da, aber das
  // nie fadende Location-Modell stand davor). Gleiche Semantik wie der
  // Etagen-Umschalter für Platten (seit 2026-07-31: lv === filter) und die
  // Admin-Solo-Ansicht: Level < 0 gewählt → das Modell (die Level-0+-Optik)
  // verschwindet, bis eine Etage >= 0 oder die Fernsicht zurückkommt.
  if (tile.modelIsGround && sm) {
    sm.visible = !(f > 0.03 && tile.levelFilter < 0);
  }

  for (const m of tile.roofMats) m.opacity = Math.max(0, 1 - f * 1.4);
  for (const o of tile.roofParts) o.visible = f < 0.95;
  // Aufgedeckter Innenraum: Hülle wirft keinen Schatten mehr, sonst stehen
  // die Figuren im Dunkeln
  const shellShadow = f < 0.4;
  tile.group.traverse((o) => {
    if ((o as THREE.Mesh).isMesh && o.castShadow !== shellShadow && tile.interior && !tile.interior.getObjectById(o.id)) {
      o.castShadow = shellShadow;
    }
  });
  for (const m of tile.shellMats) m.opacity = 1 - f * 0.88;
  tile.interior.visible = f > 0.03;
  for (const l of tile.interiorLabels) l.visible = f > 0.5;
}
