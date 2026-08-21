import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { sampleTerrain, surfaceMaterial, worldToLocalXZ } from '@anima/scene-render';
import type { CutoutHandle, SceneModelSpec, SceneTerrain, SurfaceMaterialSpec } from '@anima/scene-render';
import type { WorldLocation } from '../types';
import { acceptsWalkHit, declaredFloorAt, plateCeiling, plateLift, recipeFloorAt,
  standY, WALK_CLEARANCE_M,
  type DeclaredFloor, type GroundModelInfo, type WalkPlate } from '../game/ground';
import { pointInPolygon, polygonArea, polygonBounds, sanitizePolygon } from '../game/polygon';
import {
  asphaltTexture, grassTexture, paversTexture, waterTexture,
} from './textures';

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

/** How high above the world the ground raycast of `tileGroundY` starts, in
 *  metres, before any relief is known. A ray has to start ABOVE what it is
 *  meant to hit — one that starts inside a hill finds nothing and the figure
 *  falls back to the tile floor on exactly the ground it should be standing
 *  on. */
const RAY_START_FALLBACK_M = 20;
/** Air above the highest ground the ray keeps: a location's model may stand a
 *  little proud of the terrain it is placed on. */
const RAY_START_MARGIN_M = 5;
let rayStartY = RAY_START_FALLBACK_M;

/**
 * Raise the ground raycast above the world's relief (§ A16).
 *
 * Called by `scene/ground.ts` whenever the heightfield is taken over: the
 * relief is clamped at ±50 m, so the fixed 20 m the client used before is
 * INSIDE any hill taller than that. The start only ever grows — the fallback
 * is the floor, because a ray starting lower than it always did would be a
 * regression on the flat world it was chosen for.
 */
export function setWorldRayStart(maxGroundY: number): void {
  const want = (Number.isFinite(maxGroundY) ? maxGroundY : 0) + RAY_START_MARGIN_M;
  rayStartY = Math.max(RAY_START_FALLBACK_M, want);
}

/** The world ground under a point, or `null` while nothing has been taken
 *  over — see `setWorldGround`. */
let worldGroundAt: ((x: number, z: number) => number) | null = null;

/**
 * Take over the world's ground sampler — THE GROUND HOOK (§ A16, E8 task 4).
 *
 * A location does not float over its landscape: its tile stands on the world
 * ground under its own centre. Under a footprint that levels its ground
 * (`level_ground`, § A16.1, opt-in) that one height IS the whole place,
 * because the server flattens the field there; under an unflagged place the
 * landscape runs on underneath and the centre is simply where the tile sits.
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

/**
 * THE footprint outline of a location, in TILE-LOCAL metres — the drawn
 * polygon of contract v6, or `null` when the location has no area at all.
 *
 * Two sources and no third: the worldmap row (the server hoists the EFFECTIVE
 * boundary out of `map3d`, synthesizing the four corners of a legacy square)
 * and the detail record's own `map3d.boundary` for a location the map row says
 * nothing about. `null` is a real state — v6 Nr. 1 struck the "without an
 * anchor, a 10 m square" fallback without replacement, so such a place is a
 * pin: it claims no point, gets no plate, and says so once.
 */
export function footprintBoundary(loc: WorldLocation): [number, number][] | null {
  const pts = sanitizePolygon(loc.boundary ?? loc.map3d?.boundary);
  if (pts) return pts;
  if (!widthWarned.has(loc.id)) {
    widthWarned.add(loc.id);
    console.warn(`[tiles] ${loc.name || loc.id}: no boundary — the location has`
      + ' no area at all (contract v6 Nr. 1), so no plate is drawn');
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
 * the location's own centre (`setWorldGround`) — under a footprint that levels
 * its ground (`level_ground`, § A16.1, opt-in) that is the flat plateau the
 * server made, under any other place it is the landscape at that point.
 * Because the whole tile group hangs off this one point, everything the place
 * is made of — the
 * plate, the shell, the rooms, the scene payload's tile-local metres — climbs
 * the hill together, and nothing inside the location has to know about relief
 * at all.
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
}

export interface Tile {
  loc: WorldLocation;
  /** Fassaden mit Fensterraster — leuchten nachts (emissive) */
  facadeMats?: THREE.MeshStandardMaterial[];
  group: THREE.Group;
  /** Centre of the footprint in world metres — `group.position` (§ A1.1). */
  center: THREE.Vector3;
  /** THE footprint outline in TILE-LOCAL metres (contract v6) — what the plate
   *  is cut to and what `tileAt` tests a point against. `null` = the location
   *  has no area at all, and then this tile claims no point on the plane. */
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
  /** Bezugsrahmen der Begehbarkeits-Abtastung je Raum: Halter auf der
   *  Raum-Mitte in Auflagehöhe + Maße der Raum-Umschließenden */
  roomSlots: Map<string, { holder: THREE.Group; w: number; d: number }>;
  /** freie Stellflächen im Raum-Modell (Welt-Koordinaten auf Bodenhöhe) */
  roomSpots: Map<string, THREE.Vector3[]>;
  /** erkannte Sitzflächen (Möbelhöhe, kleine Flächen) */
  roomSitSpots: Map<string, THREE.Vector3[]>;
  /** erkannte Liegeflächen (Möbelhöhe, große zusammenhängende Flächen) */
  roomLieSpots: Map<string, THREE.Vector3[]>;
  /** kuratierte Animations-Marker (AV3D-11): Raum -> Clip-Kind -> Punkte
   *  (rotation = Blickrichtung in Grad, offsetY additiv zur Auflagehöhe;
   *  fixed = Höhe ist fertig komponiert (prop_markers) und wird von der
   *  Abtastung nicht mehr verfeinert) */
  roomMarkers: Map<string, Map<string, { p: THREE.Vector3; rotation?: number;
    /** Neigung aus dem Payload (Grad): Kopf hoch/tief bzw. seitlich kippen —
     *  ohne sie kann eine Figur nur senkrecht stehen. */
    tilt?: number; roll?: number;
    /** Absatz der Figurenwurzel unter der Fläche (Welt-Meter, Server) —
     *  beim Nachjustieren gegen die abgetastete Oberfläche erneut abziehen. */
    drop: number;
    offsetY: number; fixed?: boolean }[]>>;
  /** komplette Raum-Gruppe je Layout-Raum (für den Fokus-Modus) */
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
   *  about the room's modelled floor and outranks both the drawn plate and the
   *  mesh ray. It is the same number `sampleRoomWalkables` stands the NPC
   *  spots on, so figure and spot cannot end up on two floors. */
  declaredFloors: DeclaredFloor[];
  /** Wand-Materialien je Etage (fürs Etagen-Umschalten). Liste, weil
   *  texturierte Wände je Stück ein eigenes Material mit eigener repeat
   *  brauchen (Szenen-Rezept) — der Legacy-Grundriss trägt genau eines ein. */
  levelWallMats: Map<number, THREE.MeshStandardMaterial[]>;
  /** aktuell gewählte Etage der Innenansicht (Umschalter; Default EG) */
  levelFilter: number;
  /** Pull the in-world storey switch's display state out of `levelFilter`
   *  (its marking and its height). Whoever sets `levelFilter` from outside —
   *  the lift, the avatar changing storey — calls this with it; a tile without
   *  a scene or with a single storey has no switch. */
  levelSwitch?: () => void;
  /** als outdoor markierte Räume (liefern keine Boden-Farbe fürs Gebäude) */
  roomOutdoor: Set<string>;
  /** Boden-/Sockelplatte DIESER Kachel (immer opak, Höhe 0) — die Innenansicht
   *  eines Gebäudes mit Keller muss durch sie hindurchsehen. */
  groundPlate?: THREE.Mesh;
  /** The world ground under the plate's drape lattice at the moment it was
   *  built (`plateGroundSamples`) — the staleness reading of `relevelTiles`.
   *  `undefined` for a tile that carries no plate at all. */
  plateGround?: Float32Array | null;
  /** Szene dieser Kachel nutzt eine Etage < 0 (aus dem Payload abgeleitet,
   *  gesetzt von mountScene). Ohne Keller bleibt der Boden unangetastet. */
  hasBasement?: boolean;
  /** Höhenfeld der montierten Szene (§ B1 Nr. 14) — fehlt = ebene Kachel.
   *  Objekthöhen kommen FERTIG gehoben aus dem Payload; das Feld dient hier
   *  nur dem Drapieren des Bodens und der Standhöhe der Figuren. */
  terrain?: SceneTerrain;
  /** Kantenlänge des Bezugsquadrats, über dem `terrain` liegt (extent_m). */
  terrainExtent?: number;
  /** Ebene Original-Geometrie der Kachelplatte, solange eine Relief-Szene
   *  sie drapiert hat — unmountScene setzt sie zurück. */
  flatGroundGeo?: THREE.BufferGeometry;
  /** Flächen-Location (plan-area-locations.md): das Location-Modell bleibt in
   *  der Innenansicht stehen und bekommt stattdessen Löcher. Das Handle
   *  schaltet sie mit dem Crossfade — Fernsicht intaktes Modell, Innenansicht
   *  Löcher — und gibt beim Remount seine Material-Klone frei. */
  cutouts?: CutoutHandle;
  /** Modell-Platzierungen der montierten Szene (Stufen-Tausch, Etappe 3) */
  placedModels?: PlacedSceneModel[];
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
let grassTex: THREE.Texture | null = null;
let asphaltTex: THREE.Texture | null = null;
let waterTex: THREE.Texture | null = null;

/** Globale Oberflächen-Bibliothek vom Server (kind -> Fläche ODER
 *  Zusammenstellung); Fallback sind die eingebauten prozeduralen Texturen.
 *  Neuer Boden = neuer Bibliotheks-Eintrag, KEINE Client-Änderung. */
interface SurfaceEntry {
  url?: string; sizeM: number;
  /** Materialklasse der Art (Bibliothek) — Wasser wird anders beleuchtet als
   *  Gras, und zwar in BEIDEN Renderern gleich (@anima/scene-render). */
  material?: SurfaceMaterialSpec | null;
}
const serverSurfaces = new Map<string, SurfaceEntry>();
const serverSurfaceCache = new Map<string, THREE.Texture>();
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

/** Tileable surface texture of a terrain kind, repeated over a footprint
 *  `widthM` metres wide (server library first, built-in procedural fallback).
 *
 *  The base image is cached per kind, the REPEAT is per tile: footprints have
 *  different edge lengths now, so one shared texture object could not carry all
 *  of them — a clone is one object per plate and the image is shared. */
function surfaceTexture(kind: string, fallback: THREE.Texture,
                        widthM: number): THREE.Texture {
  const entry = serverSurfaces.get(kind);
  if (!entry?.url) return fallback;
  let tex = serverSurfaceCache.get(kind);
  if (!tex) {
    tex = loader.load(entry.url);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    serverSurfaceCache.set(kind, tex);
  }
  const own = tex.clone();
  own.needsUpdate = true;
  own.wrapS = own.wrapT = THREE.RepeatWrapping;
  own.repeat.set(widthM / entry.sizeM, widthM / entry.sizeM);
  return own;
}

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

function std(opts: THREE.MeshStandardMaterialParameters): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0.02, transparent: true, ...opts });
}

/** How fine the footprint plate is cut for the drape, and how many cells it may
 *  cost at most. 2 m is finer than any world field step (§ A16: 4 m and up), so
 *  the plate follows the landscape rather than interpolating over it; the cap
 *  keeps a 500 m area from paying 60 000 quads. */
const DRAPE_STEP_M = 2;
const DRAPE_MAX_SEGMENTS = 48;

/** Below this LIFT anywhere over a footprint the plate stays the ONE quad it
 *  always was (metres). Same idea as the fog tiling of E8 task 5: cut only
 *  where the ground actually moves — a world without relief must cost exactly
 *  what it cost before. The lift is never negative (`plateLift`), so the
 *  largest one IS the spread. */
const DRAPE_FLAT_EPS_M = 0.05;

/** How high a plate rides over the tile floor, in metres — the ground plate of
 *  the footprint and the socle under a building model. The socle is the hair
 *  above the ground plate it always was. Exported so the smoke can measure the
 *  world height of a vertex instead of carrying a copy of the number
 *  (`client3d/scripts/smoke_plate_drape.mjs`). */
export const PLATE_Y_M = 0.04;
export const SOCLE_Y_M = 0.045;

/**
 * WHERE THE TILE'S OWN PLATE GOES WHILE A SCENE IS MOUNTED, in metres.
 *
 * Three states, and the payload alone decides which (§ B1 addendum
 * 2026-08-20 part 2 — the server classifies, the renderer places):
 *
 *  - a DETAIL scene (`area_detail`) makes the plate the BACKSTOP under the
 *    storey-0 surfaces: −0.05, i.e. 0.14 m under the zone plates at 0.09.
 *    1 cm was not enough for the depth buffer at range (z-fighting waves,
 *    user picture 2026-08-03).
 *  - a NATURAL location (`natural_floor`) draws no storey slab at all, so its
 *    zone surfaces sit at 0.01 rather than 0.09 — the SAME 0.14 m of clearance
 *    is 0.01 − 0.14 = −0.13. Without this the plate would bury the very
 *    textures it backs: outside detail mode it sits at 0.04, three centimetres
 *    ABOVE them, and with its own depth bias pulling it forward it wins even
 *    where it is level.
 *  - anything else keeps the plate where the tile built it (0.04) — it lies ON
 *    the world ground there and is not a backstop at all.
 *
 * The tile plate is DRAPED over the world ground (`plateGeometry`) while these
 * scene surfaces are flat, so the clearance is a clearance only where the
 * landscape under the footprint is level with the pin; where the world rises
 * more than 0.14 m above it the plate comes through the zone textures. That is
 * the authored mismatch (a flat drawn zone over a rolling landscape), not a
 * datum question — `level_ground` on the location is what flattens it.
 */
export const BACKSTOP_Y_M = -0.05;
export const NATURAL_BACKSTOP_Y_M = -0.13;

/** The y of the tile's own ground plate for a mounted scene — the ONE rule,
 *  hoisted out of `mountScene` so `smoke_walk_math.mjs` can check it by hand
 *  instead of copying the three numbers. */
export function tilePlateY(scene: { area_detail?: boolean;
                                    natural_floor?: boolean }): number {
  if (scene.natural_floor) return NATURAL_BACKSTOP_Y_M;
  if (scene.area_detail) return BACKSTOP_Y_M;
  return PLATE_Y_M;
}

/** Is the tile's own plate a BACKSTOP under this scene (pushed back in the
 *  depth test) rather than the ground it normally is (pulled forward)? */
export function tilePlateIsBackstop(scene: { area_detail?: boolean;
                                             natural_floor?: boolean }): boolean {
  return !!(scene.area_detail || scene.natural_floor);
}

/**
 * The DEPTH BIAS of a footprint plate — one rung in front of the world ground's
 * own ladder (`scene/ground.AREA_OFFSET_MAX` = 32, so this is −33).
 *
 * The same `polygonOffset` crutch the file already uses for the detail-mode
 * backstop (`sceneRecipe.mountScene`, 2026-08-03: "Z-Fighting-Wellen"), with
 * the SIGN MIRRORED, because the case is mirrored: the backstop must never
 * poke through the zone plates ABOVE it and is pushed back (+), a footprint
 * plate must never be poked through by the terrain BELOW it and is pulled
 * forward (−).
 *
 * WHY IT HAS TO CLEAR THE WHOLE LADDER, not just win by one unit. The painted
 * areas already pull THEMSELVES forward by `−min(index+1, AREA_OFFSET_MAX)`
 * (`scene/ground.ts`) to stack coplanar ground, while the plate carried no
 * bias at all — so the plate's 4 cm of air was competing against up to 32
 * depth units of the area under it. Worked out for this camera (near 0.2, far
 * 800, 24-bit depth: one depth unit at range z is 2.979e−7 · z² metres, so
 * 4 cm equals 134252 / z² units), the plate lost to an area of bias b beyond
 * z = sqrt(134252 / b):
 *
 *      b =  1 -> 366 m      b =  5 -> 164 m      b = 32 -> 65 m
 *      b =  2 -> 259 m      b = 10 -> 116 m
 *
 * which is exactly "the ground plate is partly covered by the texture of the
 * terrain under it, and it changes with view and movement". At one rung above
 * the ceiling the plate wins at every range, and it is no harsher on whatever
 * stands ON it than the topmost painted area already is.
 */
export const PLATE_POLYGON_OFFSET = -33;

/** Put a footprint plate one rung in front of the ground it lies on. Takes the
 *  three fields structurally so the smoke can check the real setter rather than
 *  a copy of it (`smoke_plate_drape.mjs` § 6). */
export function applyPlateDepthBias(mat: {
  polygonOffset: boolean; polygonOffsetFactor: number; polygonOffsetUnits: number;
}): void {
  mat.polygonOffset = true;
  mat.polygonOffsetFactor = PLATE_POLYGON_OFFSET;
  mat.polygonOffsetUnits = PLATE_POLYGON_OFFSET;
}

/**
 * UVs of a plate geometry, in METRES over the bounding box divided by
 * `widthM` — the square case's own mapping, generalised.
 *
 * The texture carries the repeat (`surfaceTexture`: `widthM / sizeM` on both
 * axes), so a uv that runs 0…1 across `widthM` metres puts one tile of the
 * image on every `sizeM` metres, whatever the outline's shape. Both axes are
 * divided by the SAME length, or a long thin place would stretch its grass.
 * `ShapeGeometry` would otherwise write metres straight into the uv and repeat
 * the image once per metre.
 */
function plateUVs(geo: THREE.BufferGeometry, minPX: number, minPY: number,
                  widthM: number): void {
  const pos = geo.attributes.position as THREE.BufferAttribute;
  const span = widthM > 0 ? widthM : 1;
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    uv[i * 2] = (pos.getX(i) - minPX) / span;
    uv[i * 2 + 1] = (pos.getY(i) - minPY) / span;
  }
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
}

/**
 * The drape LATTICE of a footprint polygon: the regular grid over its bounding
 * box the plate's vertices sit on, `DRAPE_STEP_M` apart and capped at
 * `DRAPE_MAX_SEGMENTS` per axis.
 *
 * One function, because two readers walk it and must not drift: the geometry
 * (`platePolygonGeometry`) and the staleness probe that asks whether the ground
 * under an ALREADY BUILT plate has moved (`plateGroundSamples`). `null` for an
 * outline that has no bounds at all.
 */
function plateLattice(boundary: [number, number][]): {
  minX: number; minZ: number; segX: number; segZ: number;
  stepX: number; stepZ: number;
} | null {
  const b = polygonBounds(boundary);
  if (!b) return null;
  const spanX = b.maxX - b.minX;
  const spanZ = b.maxZ - b.minZ;
  const segX = Math.min(DRAPE_MAX_SEGMENTS,
                        Math.max(1, Math.ceil(spanX / DRAPE_STEP_M)));
  const segZ = Math.min(DRAPE_MAX_SEGMENTS,
                        Math.max(1, Math.ceil(spanZ / DRAPE_STEP_M)));
  return { minX: b.minX, minZ: b.minZ, segX, segZ,
           stepX: spanX / segX, stepZ: spanZ / segZ };
}

/**
 * The plate geometry of ONE footprint polygon, in the plate's own frame.
 *
 * THE FRAME. The mesh is turned by −90° about X, so a vertex `(px, py, pz)`
 * sits at tile-local `(px, pz, −py)`: the outline point `(lx, lz)` becomes
 * `(lx, −lz)` and the HEIGHT is the local z. That is the frame the square
 * plate always lived in — only its shape changes here.
 *
 * TWO SHAPES, one rule (contract v6 Nr. 4). Without relief under it the plate
 * is the triangulated polygon itself (`THREE.Shape`, whose ear clipping handles
 * the concave outlines E1.1 allows) — as few triangles as the outline has, and
 * an exact rim. With relief it is the regular grid over the polygon's BOUNDING
 * BOX, `DRAPE_STEP_M` apart, with every cell whose CENTRE lies outside the
 * polygon left out. A cell straddling the rim survives whole: that is a
 * VISUAL matter, not the truth about where the place is — `tileAt` tests the
 * polygon itself, and a hand's breadth of grass past the rim is a hand's
 * breadth of grass.
 *
 * `liftAt` is the world ground over the tile floor at a TILE-LOCAL point
 * (`game/ground.plateLift`); `null` while nothing has been taken over, and then
 * the plate is flat by construction.
 */
function platePolygonGeometry(boundary: [number, number][], widthM: number,
                              liftAt: ((lx: number, lz: number) => number) | null
): THREE.BufferGeometry {
  const b = polygonBounds(boundary)!;
  // Plate coordinates: px = lx, py = −lz. The z bounds therefore swap sides.
  const minPX = b.minX;
  const minPY = -b.maxZ;
  const { segX, segZ, stepX, stepZ } = plateLattice(boundary)!;
  // Does the ground move under this footprint at all? Probed on the DRAPE GRID
  // itself, so nothing between the samples can hide (finding I2), and only
  // INSIDE the polygon — a hill in the notch of an L is not under this plate.
  let maxLift = 0;
  if (liftAt) {
    for (let iz = 0; iz <= segZ; iz++) {
      for (let ix = 0; ix <= segX; ix++) {
        const lx = b.minX + ix * stepX;
        const lz = b.minZ + iz * stepZ;
        if (!pointInPolygon(lx, lz, boundary)) continue;
        const h = liftAt(lx, lz);
        if (h > maxLift) maxLift = h;
      }
    }
  }
  if (maxLift <= DRAPE_FLAT_EPS_M) {
    const shape = new THREE.Shape(
      boundary.map(([lx, lz]) => new THREE.Vector2(lx, -lz)));
    const geo = new THREE.ShapeGeometry(shape);
    plateUVs(geo, minPX, minPY, widthM);
    geo.computeVertexNormals();
    return geo;
  }
  // The draped grid: lattice vertices, emitted only where a cell needs them.
  const positions: number[] = [];
  const index: number[] = [];
  const slot = new Map<number, number>();
  const vertexAt = (ix: number, iz: number): number => {
    const key = iz * (segX + 1) + ix;
    const known = slot.get(key);
    if (known !== undefined) return known;
    const lx = b.minX + ix * stepX;
    const lz = b.minZ + iz * stepZ;
    const at = positions.length / 3;
    positions.push(lx, -lz, liftAt ? liftAt(lx, lz) : 0);
    slot.set(key, at);
    return at;
  };
  for (let iz = 0; iz < segZ; iz++) {
    for (let ix = 0; ix < segX; ix++) {
      const cx = b.minX + (ix + 0.5) * stepX;
      const cz = b.minZ + (iz + 0.5) * stepZ;
      if (!pointInPolygon(cx, cz, boundary)) continue;
      const a = vertexAt(ix, iz);
      const c = vertexAt(ix + 1, iz);
      const d = vertexAt(ix + 1, iz + 1);
      const e = vertexAt(ix, iz + 1);
      // py = −lz, so a growing iz means a FALLING py — the winding below is
      // the one that leaves the face pointing at world +Y after the −90° turn.
      index.push(a, e, d, a, d, c);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geo.setIndex(index);
  plateUVs(geo, minPX, minPY, widthM);
  geo.computeVertexNormals();
  return geo;
}

/**
 * The lift of one TILE-LOCAL point over the tile floor, or `null` while no
 * world ground has been taken over (`setWorldGround`) — then every plate is
 * flat by construction, which is also what a world without relief answers.
 *
 * The world lookup is this closure's business, the RULE is
 * `game/ground.plateLift` — the same one the figure stands by. The mapping is
 * § A1.1, the one `tileToWorld` uses, so `at` is the footprint's placement:
 * the centre in WORLD metres plus its yaw, because the vertices are TILE-LOCAL
 * and the world sampler is not.
 */
function plateLiftFn(at: { x: number; y: number; z: number; yaw: number },
): ((lx: number, lz: number) => number) | null {
  const sample = worldGroundAt;
  if (!sample) return null;
  const cos = Math.cos(at.yaw);
  const sin = Math.sin(at.yaw);
  return (lx: number, lz: number): number => plateLift(
    sample(at.x + lx * cos + lz * sin, at.z - lx * sin + lz * cos), at.y);
}

/**
 * The DRAPED plate geometry of a footprint polygon — the ONE entry every plate
 * of a tile is built from, so the ground plate of an open place and the socle
 * under a building model cannot describe two different surfaces.
 *
 * Exported for `client3d/scripts/smoke_plate_drape.mjs`, which measures the
 * world height of every vertex against the ground under it (§ B5a: numbers,
 * never screenshots).
 */
export function plateGeometry(boundary: [number, number][], widthM: number,
                              at: { x: number; y: number; z: number; yaw: number },
): THREE.BufferGeometry {
  return platePolygonGeometry(boundary, widthM, plateLiftFn(at));
}

/**
 * The WORLD GROUND under every point of a plate's drape lattice, in metres —
 * the reading a built plate is frozen against.
 *
 * A plate is draped once, when its tile is built, and the field arrives in
 * pieces: the 256 m height tiles are a WINDOW that follows the player
 * (`scene/heightTiles.ts`), so the ground under a footprint sharpens as
 * somebody walks towards it. `main.relevelTiles` used to ask ONE point whether
 * that had happened — the pin — which is sound for a 10 m square and blind for
 * a v6 outline hundreds of metres across, where the pin and the far rim are in
 * different height tiles. Then the plate kept a stale drape while the ground
 * under it moved, and the terrain grew through it AS THE PLAYER WALKED.
 *
 * `null` while no world ground has been taken over or the place has no outline
 * — there is no plate to be stale then either. `at` needs no y: this is the
 * ground itself, not the lift over the tile floor.
 */
export function plateGroundSamples(boundary: [number, number][] | null | undefined,
                                   at: { x: number; z: number; yaw: number },
): Float32Array | null {
  const sample = worldGroundAt;
  if (!sample || !boundary) return null;
  const grid = plateLattice(boundary);
  if (!grid) return null;
  const cos = Math.cos(at.yaw);
  const sin = Math.sin(at.yaw);
  const out = new Float32Array((grid.segX + 1) * (grid.segZ + 1));
  let n = 0;
  for (let iz = 0; iz <= grid.segZ; iz++) {
    const lz = grid.minZ + iz * grid.stepZ;
    for (let ix = 0; ix <= grid.segX; ix++) {
      const lx = grid.minX + ix * grid.stepX;
      out[n++] = sample(at.x + lx * cos + lz * sin, at.z - lx * sin + lz * cos);
    }
  }
  return out;
}

/** Has the ground under a built plate moved by at least `epsM` ANYWHERE on its
 *  lattice? Two readings that were never taken (no field yet) have not moved;
 *  a lattice of a different size has, because the outline itself was redrawn. */
export function plateGroundMoved(before: Float32Array | null | undefined,
                                 after: Float32Array | null | undefined,
                                 epsM = 1e-3): boolean {
  if (!before || !after) return false;
  if (before.length !== after.length) return true;
  for (let i = 0; i < before.length; i++) {
    if (Math.abs(before[i] - after[i]) >= epsM) return true;
  }
  return false;
}

/** Ground plate of the FOOTPRINT — the surface texture of the location's
 *  terrain kind (server library, else procedural), over the whole drawn
 *  BOUNDARY POLYGON (contract v6 Nr. 4; a legacy square is that polygon's four
 *  corners). The 2D map illustrations are NOT used as ground (baked-in shadows
 *  and objects do not belong in a 3D scene).
 *
 *  THE PLATE FOLLOWS THE LANDSCAPE (finding 4, 2026-08-13), by the same
 *  mechanism the world plate uses (`scene/ground.liftToField`): it is cut into
 *  cells and every vertex is lifted by the world ground under it. Without that
 *  the figure walks at the height of the terrain (`tileGroundY`) while a flat
 *  plate at the centre height cuts straight through the hill it stands on.
 *  Under a levelling footprint (`level_ground`, § A16.1) the field is flat and
 *  every lift is the same zero — the plate stays the ONE quad it was, and so it
 *  does in a world with no relief at all (`DRAPE_FLAT_EPS_M`).
 *
 *  IT ONLY EVER RISES (`game/ground.plateLift`, review finding I1). The figure
 *  stands on `standY` = the HIGHER of tile and world, so downhill the tile wins
 *  and a plate that followed the world down would sink away under it. Worked
 *  through by hand, a footprint whose centre stands on 2.0 m: at a point where
 *  the world reads 3.2 the vertex is lifted 1.2 and the figure walks at 3.2 —
 *  both on the same surface; at a point where the world reads 0.5 the lift is 0,
 *  the plate stays the tile floor 2.0 and the figure walks at 2.0 — again the
 *  same surface, with the landscape passing underneath.
 *
 *  THE FLATNESS PROBE READS THE DRAPE GRID, not a handful of points (review
 *  finding I2): a hill at the quarter point of an 80 m footprint is 28 m from
 *  every corner, edge midpoint and the centre, so a 3 × 3 probe read a spread
 *  of 0 and left the plate flat for exactly the layout the drape is for. The
 *  probe walks the same lattice the vertices sit on — at most 49² samples of
 *  plain arithmetic, once, when the tile is built (`platePolygonGeometry`).
 *
 *  THE MESH FRAME IS UNTOUCHED: the plate keeps its −90° rotation and its
 *  y = 0.04, because `sceneRecipe` writes that height (backstop mode) and
 *  drapes the SCENE relief on top through `drapeGeometry(…, gp.matrix)`. In
 *  that frame world +Y is local +Z, which is where the lift goes — the scene
 *  drape then ADDS its own along the same axis, so the two reliefs stack
 *  instead of overwriting each other.
 *
 *  `at` is the footprint's placement: the centre in WORLD metres plus its yaw,
 *  because the vertices are TILE-LOCAL and the world sampler is not. */
function groundPlate(boundary: [number, number][], widthM: number,
                     tex: THREE.Texture,
                     material: SurfaceMaterialSpec | null | undefined,
                     at: { x: number; y: number; z: number; yaw: number }): THREE.Mesh {
  // The tile surface goes through the same factory as the scene plates: a water
  // location should look on the map the way it looks in the room.
  const mat = surfaceMaterial(THREE, { material, map: tex, transparent: true }) as THREE.MeshStandardMaterial;
  applyPlateDepthBias(mat);
  const plate = new THREE.Mesh(plateGeometry(boundary, widthM, at), mat);
  plate.rotation.x = -Math.PI / 2;
  plate.position.y = PLATE_Y_M;
  plate.receiveShadow = true;
  return plate;
}

// `makeTree` stand hier bis 2026-08-02: prozedurale Kegel-Bäume auf
// forest-Kacheln. Seit Wald & Co. ihre Detailszene aus GESTREUTEN
// Bibliotheks-Props beziehen (plan-area-detail-scenes.md), sind generische
// Deko-Elemente für ALLE Geländearten gestrichen (User-Vorgabe) — das
// Gelände sagt nur noch die Bodentextur, was drauf steht, sagt die Welt.


/** The tile builds only the OUTSIDE: ground plate, socle, label. The
 *  procedural building shell died with the Prop-Welt programme (user decision
 *  2026-08-19) — a location without a server model shows its drawn ground and
 *  nothing invented on top. The interior (plates, walls, elevator, rooms,
 *  models) comes entirely from the scene recipe; `mountScene` (sceneRecipe.ts)
 *  builds it into these same tile fields. A location without a recipe (404)
 *  has, by server definition, neither a room layout nor an outline nor a
 *  building model — there is simply nothing to unfold. */
export function buildTile(loc: WorldLocation): Tile {
  grassTex = grassTex ?? grassTexture();
  asphaltTex = asphaltTex ?? asphaltTexture();
  waterTex = waterTex ?? waterTexture();

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
    roomSlots: new Map(), roomSpots: new Map(),
    roomSitSpots: new Map(), roomLieSpots: new Map(), roomMarkers: new Map(),
    roomGroups: new Map(), roomRects: new Map(), roomLevels: new Map(), alwaysVisibleRooms: new Set(),
    outlineWalls: [], levelSlabs: new Map(), levelWallMats: new Map(), walkPlates: [],
    declaredFloors: [],
    levelFilter: 0, roomOutdoor: new Set(),
    fade: 0, fadeTarget: 0, occl: 0,
  };

  const fallbackFor = (s: string) => (s === 'road' ? asphaltTex! : s === 'water' ? waterTex! : grassTex!);
  // Ground = the surface texture of the terrain kind (server library AV3D-13,
  // else procedural) — 2D map pictures are no fallback any more. The kind comes
  // from the server (`surface_kind`); the legacy style only picks the
  // procedural stand-in texture.
  //
  // NO BOUNDARY, NO PLATE (v6 Nr. 1): a location with no area is a pin, and a
  // plate would be a square nobody drew.
  const groundPlateFor = (): THREE.Mesh | null => {
    if (!boundary) return null;
    const kind = loc.surface_kind || style;
    return groundPlate(boundary, width,
                       surfaceTexture(kind, fallbackFor(style), width),
                       surfaceMaterialSpec(kind),
                       { x: center.x, y: center.y, z: center.z, yaw });
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

  if (!isBuilding) {
    tile.groundPlate = groundPlateFor() ?? undefined;
    if (tile.groundPlate) group.add(tile.groundPlate);
    tile.height = style === 'forest' ? 3 : 0.3;
  } else if (natureSite) {
    tile.groundPlate = groundPlateFor() ?? undefined;
    if (tile.groundPlate) group.add(tile.groundPlate);
    tile.height = style === 'forest' ? 3 : 0.6;
    addLabel();
  } else {
    // Socle plate under a building: the location's declared ground (e.g.
    // grass on a campus) before the paving default — "terrain = grass" is
    // meant to show grass in the room view too, not stones. The kind is the
    // server's (`surface_kind`); the legacy style vocabulary only picks the
    // procedural fallback texture for a terrain the library has no entry for.
    const tStyle = terrainKind(loc.terrain);
    const tKind = loc.surface_kind || tStyle;
    const plinthTex = tKind
      ? surfaceTexture(tKind, fallbackFor(tStyle || ''), width)
      : paversTexture();
    // The socle follows the DRAWN OUTLINE like every other plate (v6 Nr. 4):
    // one shape for the place, whether a house stands on it or not — AND the
    // same drape, through the very same `plateGeometry`. It used to be built
    // flat (`liftAt = null`), which was harmless while the socle was the few
    // metres of paving around a procedural hut; since the shell was struck
    // (2026-08-19) the socle IS the drawn area of the place, and a dead-flat
    // one at the pin's height floats over the valley half of its own outline
    // and lets the hill half grow straight through it. Measured by hand in
    // `smoke_plate_drape.mjs`: on a 40 m outline over a 5 % slope the west rim
    // stood 1.045 m in the air and the east rim was buried 0.955 m deep.
    if (boundary) {
      const plinthMat = std({ map: plinthTex });
      applyPlateDepthBias(plinthMat);
      const plinth = new THREE.Mesh(
        plateGeometry(boundary, width,
                      { x: center.x, y: center.y, z: center.z, yaw }),
        plinthMat);
      plinth.rotation.x = -Math.PI / 2;
      plinth.position.y = SOCLE_Y_M;
      plinth.receiveShadow = true;
      group.add(plinth);
      tile.groundPlate = plinth;
    }

    // No procedural stand-in: until a server model arrives the place is its
    // socle plate. The label height is a fixed reading distance, not a fake
    // building height.
    tile.height = 4;
    addLabel();
  }

  // The ground this plate was draped against — `main.relevelTiles` compares it
  // with a fresh reading whenever the relief moves, so a plate whose landscape
  // sharpened away from the pin is rebuilt instead of left standing stale.
  if (tile.groundPlate) {
    tile.plateGround = plateGroundSamples(boundary,
                                          { x: center.x, z: center.z, yaw });
  }

  tile.facadeMats = tile.shellMats.filter((m) => !!m.emissiveMap);
  return tile;
}


/** Begehbarkeit eines Raum-Aufbaus abtasten (Diorama-Modell ODER
 *  Rezept-Szene aus Hülle + Props): Raster von oben, 20. Perzentil =
 *  Bodenhöhe, deutlich höhere Treffer sind Möbel/Wände (dort keine
 *  Figuren). Füllt roomSpots/-SitSpots/-LieSpots, hebt Mitte/Ausgang auf
 *  die echte Bodenhöhe und verfeinert die Marker-Höhen (außer fertig
 *  komponierte prop_markers, fixed). */
export function sampleRoomWalkables(tile: Tile, roomId: string, root: THREE.Object3D | THREE.Object3D[],
                                    declaredFloor?: number) {
  const slot = tile.roomSlots.get(roomId);
  if (!slot) return;
  const roots = (Array.isArray(root) ? root : [root]).filter(Boolean);
  if (!roots.length) return;
  tile.group.updateMatrixWorld(true);
  // Abtastung unabhängig von der Material-Seitigkeit: generierte Meshes
  // haben teils nach UNTEN orientierte Boden-Dreiecke — einseitig trifft
  // sie der Strahl von oben nicht und fällt auf die Sockelplatte durch
  // (Figuren stehen dann im Boden). Für die Dauer der Abtastung DoubleSide.
  const savedSides: [THREE.Material, THREE.Side][] = [];
  for (const r of roots) {
    r.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        savedSides.push([m, m.side]);
        m.side = THREE.DoubleSide;
      }
    });
  }
  const restoreSides = () => { for (const [m, s] of savedSides) m.side = s; };
  const ray = new THREE.Raycaster();
  const down = new THREE.Vector3(0, -1, 0);
  // RELATIVE to the room's own holder, and that is what makes the 20 m below
  // relief-proof (§ A16): `base` is a world position that travels with the
  // tile, so a location standing on a hill rays from 20 m above ITS floor, not
  // from 20 m above the flat world. The one absolute start in this file is
  // `tileGroundY`'s, and that one follows the field (`setWorldRayStart`).
  const base = slot.holder.getWorldPosition(new THREE.Vector3());
  const N = 6;
  const samples: { p: THREE.Vector3; ix: number; iz: number; uv?: THREE.Vector2; mesh?: THREE.Mesh }[] = [];
  for (let ix = 0; ix < N; ix++) {
    for (let iz = 0; iz < N; iz++) {
      // The slot's w/d are the room's TILE-LOCAL extents, so the raster is
      // laid out in the tile's frame and only then turned into the world — on
      // a location standing at an angle a world-axis raster would sample a
      // square that hangs out of the room on two corners and misses it on the
      // other two. The rays themselves stay vertical, so the hits are world
      // points either way; it is the sampled AREA that has to follow the room.
      const off = tileDirToWorld(tile,
        (ix / (N - 1) - 0.5) * slot.w * 0.78,
        (iz / (N - 1) - 0.5) * slot.d * 0.78);
      const ox = off.x;
      const oz = off.z;
      ray.set(new THREE.Vector3(base.x + ox, base.y + 20, base.z + oz), down);
      const hit = ray.intersectObjects(roots, true)[0];
      if (hit) samples.push({ p: hit.point.clone(), ix, iz, uv: hit.uv?.clone(), mesh: hit.object as THREE.Mesh });
    }
  }
  if (samples.length < 5) { restoreSides(); return; }
  // Bodenhöhe = DOMINANTE Höhenlage (7-cm-Raster) statt 20. Perzentil: bei
  // Dioramen mit sichtbarem Sockelrand erwischte das Perzentil die Sockel-
  // platte und stellte die Figuren IN den eigentlichen Boden. Bei Gleich-
  // stand gewinnt die tiefere Lage (Boden unter Möbeln); Feinwert = Median
  // der Treffer in der Gewinner-Lage.
  const bins = new Map<number, number>();
  for (const s of samples) {
    const b = Math.round(s.p.y / 0.07);
    bins.set(b, (bins.get(b) ?? 0) + 1);
  }
  let floorBin = 0, floorVotes = -1;
  for (const [b, n] of bins) {
    if (n > floorVotes || (n === floorVotes && b < floorBin)) { floorVotes = n; floorBin = b; }
  }
  const inBin = samples.map((s) => s.p.y)
    .filter((y) => Math.abs(y - floorBin * 0.07) < 0.08)
    .sort((a, b) => a - b);
  let floor = inBin[Math.floor(inBin.length / 2)];
  // Reference ray at the room's DOOR (`tile.roomDoors`, straight from the
  // payload's `doorways[]`): generated meshes have HOLES in the floor at
  // hidden places — grid rays fall through them onto the base plate and the
  // dominant layer underestimates the floor (figures stand IN it). At the
  // door the floor is practically always intact (it is what the generation
  // looked at): if the hit there lies A LITTLE above the dominant layer, it
  // IS the floor; clearly higher hits (furniture in front of the door) are
  // not.
  const doorP = tile.roomDoors.get(roomId);
  if (doorP) {
    ray.set(new THREE.Vector3(doorP.x, base.y + 20, doorP.z), down);
    const eh = ray.intersectObjects(roots, true)[0];
    if (eh && eh.point.y > floor + 0.1 && eh.point.y < floor + 0.55) floor = eh.point.y;
  }
  // walk_y (§ B6 Nr. 7): eine DEKLARIERTE Standhöhe schlägt die komplette
  // Heuristik (dominante Lage + Tür-Referenz) — bei modellierten Böden
  // (Podest, Löcher, versenkte Lounge) ist sie von außen nicht messbar.
  // Spots/Sitze filtern dann relativ zum deklarierten Boden.
  //
  // IM RAHMEN DER TREFFER, nicht im Rahmen des Payloads: `floor` ist bis hier
  // eine WELT-Höhe (Strahl-Treffer) und wird auch als solche weitergegeben
  // (Steh-Spots, Raummitte unten), während `walk_y_world` ein KACHEL-Meter ist
  // — das Rezept rechnet um den Kachelboden y = 0, und die Kachel steht auf
  // ihrem Plateau (E8 Task 4, dieselbe Lehre wie in `tileWalkY`). Ohne den
  // Aufschlag fände der Spot-Filter unten auf jedem Plateau keine einzige
  // Probe mehr (Deklaration still wirkungslos), und bei kleinem Plateau sänke
  // die Raummitte um genau die Plateauhöhe ein.
  if (declaredFloor !== undefined) floor = tile.center.y + declaredFloor;
  const spots = samples
    .filter((s) => Math.abs(s.p.y - floor) < 0.12)               // eben genug = begehbar
    .sort((a, b) => a.p.distanceToSquared(base) - b.p.distanceToSquared(base))
    .map((s) => s.p.clone().setY(s.p.y + 0.01));

  // Sitz-/Liegeflächen (Heuristik): flache Treffer in Möbelhöhe — über dem
  // Boden, unter Tischhöhe (Figuren im Raum sind ~0,6 m groß). Große
  // zusammenhängende Flächen = liegen (Bett/Sofa), kleine = sitzen.
  const isFurniture = (s: { p: THREE.Vector3 }) => s.p.y > floor + 0.08 && s.p.y < floor + 0.32;
  const cand = samples.filter(isFurniture);
  const byCell = new Map(cand.map((s) => [`${s.ix},${s.iz}`, s]));
  const visited = new Set<string>();
  const sit: THREE.Vector3[] = [];
  const lie: THREE.Vector3[] = [];
  for (const s of cand) {
    const key = `${s.ix},${s.iz}`;
    if (visited.has(key)) continue;
    const group: typeof cand = [];
    const queue = [s];
    visited.add(key);
    while (queue.length) {
      const cur = queue.pop()!;
      group.push(cur);
      for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
        const nk = `${cur.ix + dx},${cur.iz + dz}`;
        const nb = byCell.get(nk);
        if (nb && !visited.has(nk) && Math.abs(nb.p.y - cur.p.y) < 0.07) {
          visited.add(nk);
          queue.push(nb);
        }
      }
    }
    const pts = group.map((g2) => g2.p.clone().setY(g2.p.y + 0.01));
    if (group.length >= 3) lie.push(...pts);   // große Fläche: Bett/Sofa
    else sit.push(...pts);                     // klein: Stuhl/Hocker/Bank
  }

  // unter denselben Schlüsseln ablegen wie roomCenters (ID und Name)
  const center = tile.roomCenters.get(roomId);
  for (const [key, v] of tile.roomCenters) {
    if (v !== center) continue;
    if (spots.length) tile.roomSpots.set(key, spots);
    if (sit.length) tile.roomSitSpots.set(key, sit);
    if (lie.length) tile.roomLieSpots.set(key, lie);
  }
  if (spots.length) {
    // Mitte auf die echte Bodenhöhe heben (Instanz für ID+Name geteilt)
    center?.setY(floor + 0.01);
  }

  // Marker-Höhen verfeinern, plus Server-Feinjustierung. Sitz-Marker:
  // Wurzel so verankern, dass die vom Clip abgesenkte Hüfte auf der
  // Möbel-Oberkante landet (Oberfläche minus Clip-Sitzhöhe, nie unter dem
  // Boden). Liege-/sonstige Marker liegen auf der Oberfläche (Matratze).
  const markers = tile.roomMarkers.get(roomId);
  if (markers) {
    for (const entries of markers.values()) {
      for (const e of entries) {
        if (e.fixed) continue;   // prop_markers: Höhe kommt fertig vom Server
        ray.set(new THREE.Vector3(e.p.x, base.y + 20, e.p.z), down);
        const hit = ray.intersectObjects(roots, true)[0];
        const surface = hit && hit.point.y < floor + 0.5 ? hit.point.y : floor;
        // Der Absatz kommt vom Server (root_offset) — der Client kennt hier
        // nur die abgetastete FLÄCHE, nicht den Berührpunkt des Clips.
        // BEWUSST ohne Boden-Klemme: bei diesen Clips liegt die Wurzel
        // richtigerweise unter dem Boden. Der Schlaf-Clip trägt den ganzen
        // Körper 0,6 x Figurenhöhe über seiner Wurzel (auf einem Bett
        // animiert), also 1,07 reale Meter — eine Klemme auf den Boden ließe
        // die Figur genau so weit über der Matratze schweben.
        e.p.setY(surface - e.drop + 0.01 + e.offsetY);
      }
    }
  }
  restoreSides();
}

/** Standing height on TILE level (a figure outside the rooms, e.g. at the
 *  entrance): building meshes often carry a baked-in ground skin or terrain
 *  around the door — the figure stands on that actual surface instead of
 *  sinking into it at y = 0. A ray from above; with no hit it stays on the
 *  tile floor.
 *
 *  WHICH hit counts is decided by the spec and no longer by a fixed 1.2 m mark
 *  (finding B8): the roof guard applies to BUILDING models and measures from
 *  their declared standing height (`walk_y_world`), while an AREA model
 *  (`display: ground`/`shell_area`) IS the ground and is not capped at all —
 *  otherwise the figure drops back to level 0 on a raised shore. The rule is a
 *  pure function in `game/ground.ts`.
 *
 *  EVERYTHING MEASURES RELATIVE TO THE TILE (E8 task 4). Since the tile stands
 *  on its plateau (`footprintCentre`), the ray hits are WORLD y while the spec
 *  number `walk_y_world` is a tile metre (the recipe computes around the tile
 *  floor y = 0). Without the subtraction here the roof limit would sit exactly
 *  the plateau height too low on a hill, and EVERY hit of a building on raised
 *  ground would read as "roof" — the figure would fall back to the tile floor,
 *  which is finding B8 all over again, only from above.
 *
 *  AND THE WORLD RUNS ON UNDERNEATH (finding 4 of the acceptance round
 *  2026-08-13). Everything above is measured from the tile's own centre, so it
 *  only ever knew ONE world height for the whole footprint. Under an unflagged
 *  place the landscape does not stop at the border: the figure walked at plate
 *  height while the ground rose through the plate, and at the border it jumped,
 *  because a traveller outside is sampled off the world field. The higher of the
 *  two wins (`game/ground.standY`), which is ALSO where both consumers of this
 *  function — the NPC placement and the walk/click height — inherit it from.
 *  Under a BUILT location the world term IS the plateau the bake stamped there
 *  (§ G5, no flag any more since E1), so the rule is a no-op by construction.
 *
 *  THE ONE SAMPLER ANSWERS (`heightAt` via `setWorldGround`). It used to be
 *  worth saying which of two: the client had a "drawn" height for the
 *  triangles on the screen and a bilinear one for predicting the server, and
 *  they were up to 2.433 m apart. Since "Ein Boden" E2 the terrain's own
 *  vertices come out of the bilinear lattice, so there is one number and the
 *  walk gate's mirror (`main.ts` `reliefLiftAt`) reads the very same one. */
export function tileGroundY(tile: Tile, at: THREE.Vector3): number {
  // No sampler yet = no world answer at all (NaN), not a flat 0: a tile whose
  // plateau is below zero must not be lifted to it by a missing field.
  return standY(tileWalkY(tile, at),
                worldGroundAt ? worldGroundAt(at.x, at.z) : NaN);
}

/** The downward probe of `tileWalkY`, hoisted: it runs for every figure of
 *  every frame since the travellers share this height, and a Raycaster plus two
 *  vectors per call is garbage nobody needs. */
const walkRay = new THREE.Raycaster();
const walkRayFrom = new THREE.Vector3();
const WALK_RAY_DOWN = new THREE.Vector3(0, -1, 0);

/** The TILE's own answer — plate, model skin and scene relief, all measured
 *  from the tile centre. Split off so the world term above wraps the whole
 *  answer instead of one of its three exits.
 *
 *  THE RECIPE'S FLOOR COMES FIRST for a building (decision 2026-08-20). A
 *  `shell` model is the PICTURE of a house; the floor of that house is the
 *  plate the payload draws and the surface it stands the room's props and
 *  markers on (`bottom_y = plate top + 0.01`). Raying the mesh instead asked a
 *  second, unrelated surface: "Haus von Kai" carries a 0.24 m ground pad under
 *  its walls, so the ray answered 0.000 while the room plate lay at 0.100 —
 *  the figure walked 9 cm below the floor its own furniture stood on, at the
 *  height of the tile's grass socle (0.045). Measured, § B5a.
 *
 *  THE MESH STILL ANSWERS where it IS the ground and nowhere else: an area
 *  model (`ground` / `shell_area`, whose shore, slope and lake bed are the
 *  terrain of the place) and every point of a building tile that no plate
 *  covers — the yard around the house, a place whose payload draws no plates
 *  at all.
 *
 *  AND A DECLARATION COMES BEFORE ALL OF IT (user finding 2026-08-20,
 *  Mondhütte): a room whose diorama spec carries a `walk_y_world` states where
 *  its own modelled floor is, and that dial used to reach only the NPC spots
 *  (`sampleRoomWalkables`) while the figure walked on the plate — or, in an
 *  area location, on nothing at all. Measured on Mondhütte inside the area
 *  location Mondscheinsee: room plate 0.09, diorama `bottom_y` −0.19, so a
 *  dialled `walk_y` 0.35 is `walk_y_world` 0.16 and the figure belongs at
 *  0.17 — it stood at 0.00, the bare tile floor, because `shell_area` skips
 *  the plate branch and the location has no mesh to ray.
 *
 *  THE PLATES ALSO ANSWER WHERE THERE IS NO MESH, whatever the display: an
 *  area location whose model was never generated (Mondscheinsee) draws its
 *  zone plates and nothing else, and those plates ARE its ground — the sand at
 *  0.09 that the figure stood 9 cm below. Where a mesh exists the area rule is
 *  untouched and the ray keeps answering (finding B8: shore, slope, lake bed).
 *  The plate pick is judged by `plateCeiling`, not by `walkCeiling`: the area
 *  exception is about mesh HITS, and an uncapped plate pick would hoist a
 *  ground-floor figure onto a level-1 plate. */
function tileWalkY(tile: Tile, at: THREE.Vector3): number {
  const lift = tile.center.y + terrainLiftAt(tile, at.x, at.z);
  const target = tile.serverModel;
  const info: GroundModelInfo = {
    display: tile.modelIsGround ? 'ground'
      : tile.modelIsShellArea ? 'shell_area' : 'shell',
    walkY: tile.modelWalkY,
  };
  if (tile.declaredFloors.length) {
    const local = worldToTile(tile, at.x, at.z);
    const declared = declaredFloorAt(tile.declaredFloors, local.x, local.z);
    // No terrain lift on top: the declared height is derived from the
    // diorama's `bottom_y`, which the recipe already raised onto the relief at
    // the model's anchor (`_diorama_model`, contract v5.2 no. 14). Adding it
    // again would count the hill twice — and `sampleRoomWalkables` takes the
    // same number bare, which is what keeps figure and NPC spot on ONE floor.
    if (declared !== null) return tile.center.y + declared + WALK_CLEARANCE_M;
  }
  if (tile.walkPlates.length && (info.display === 'shell' || !target)) {
    const local = worldToTile(tile, at.x, at.z);
    const floor = recipeFloorAt(tile.walkPlates, local.x, local.z,
                                plateCeiling(info));
    if (floor !== null) {
      return tile.center.y + floor + WALK_CLEARANCE_M
        + terrainLiftAt(tile, at.x, at.z);
    }
  }
  if (!target) return lift;
  walkRay.set(walkRayFrom.set(at.x, rayStartY, at.z), WALK_RAY_DOWN);
  for (const h of walkRay.intersectObject(target, true)) {
    // The hit is world y, the ceiling a tile height: compare them in the SAME
    // frame of reference, or the rule tips over with the plateau.
    if (acceptsWalkHit(info, h.point.y - tile.center.y)) {
      return h.point.y + WALK_CLEARANCE_M + terrainLiftAt(tile, at.x, at.z);
    }
  }
  return lift;
}

/** Höhe des Geländereliefs an einem WELT-Punkt dieser Kachel (0 ohne Szene
 *  oder ohne Relief) — der Aufschlag auf den ebenen Boden.
 *
 *  Das ist die EINZIGE Stelle, an der der Client eine Relief-Höhe selbst
 *  ermittelt, und sie gilt nur für den Boden und die Figuren darauf: alles,
 *  was der Payload als Objekt beschreibt (Props, Marker, Ausgänge), kommt
 *  bereits gehoben — dort nochmals zu sampeln zählte die Hebung doppelt
 *  (Vertrag v5.2 Nr. 14, „Arbeitsteilung"). Das Payload rechnet um das
 *  KACHELZENTRUM, die Aufrufer reichen Weltkoordinaten herein. */
export function terrainLiftAt(tile: Tile, x: number, z: number): number {
  if (!tile.terrain) return 0;
  // The height field is TILE-LOCAL, so a world point has to be turned back
  // into the tile's frame first — subtracting the centre alone was only right
  // while every tile stood at yaw 0.
  const local = worldToTile(tile, x, z);
  return sampleTerrain(tile.terrain, local.x, local.z,
                       tile.terrainExtent || tile.width);
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

  // Ein Keller (Etage < 0) liegt UNTER dem Kachelboden — und der ist die
  // eigene, immer opake Platte dieser Kachel, kein Teil des Szenen-Rezepts.
  // Solange die Innenansicht einer Szene mit Unter-Etage steht, wird er zum
  // Geist, sonst sieht man den Keller nie. Nachbarkacheln bleiben bewusst
  // unangetastet — der Schrägblick durch fremdes Gelände ist akzeptiert.
  const gp = tile.groundPlate;
  if (gp) {
    const gm = gp.material as THREE.MeshStandardMaterial;
    if (tile.modelIsShellArea) {
      // Detail-Modus (§ B6 Nr. 10): die Kachelplatte folgt dem FADE. Fern ist
      // sie weg, weil das Modell dort seinen eigenen Boden mitbringt (Nr. 5) —
      // eine Platte auf y 0,04 schnitte sein Gelände genau dort ab (der alte
      // Mondscheinsee-Befund). Nah ist das Modell ausgeblendet und die Platte
      // ist der Backstop unter der Detailszene, wo deren Raum-Platten die Zelle
      // nicht abdecken. Gegenläufig zu roofMats unten, mit demselben Faktor:
      // wo die Hülle bei 1/1,4 verschwunden ist, steht der Boden voll.
      // Das Material gehört dieser Kachel allein (buildTile legt pro Platte
      // eines an) — die Deckkraft hier zieht keine Nachbarkachel mit.
      // Die Platte startet durchscheinend, der Zweig unten dreht das aber ab,
      // solange die Kachel kein Detail-Modell trug (Umschalten per Remount).
      // OHNE Server-Modell gibt es keine Fernsicht, die die Platte ersetzen
      // könnte — dann bleibt sie IMMER voll da (Fernboden UND Backstop in
      // einem). Gemessen 2026-08-03: v=0/o=0 bei dist 30 ließ die Zonen
      // ohne Erde in der Luft stehen, der Fade-Übergang flackerte
      // halbtransparent (die „grünen Flecken").
      const fades = !!tile.serverModel;
      if (gm.transparent !== fades) {
        gm.transparent = fades;
        gm.needsUpdate = true;
      }
      gp.visible = fades ? f > 0.03 : true;
      gm.opacity = fades ? Math.min(1, f * 1.4) : 1;
    } else {
      const ghost = !!tile.hasBasement && f > 0.03;
      if (gm.transparent !== ghost) {
        gm.transparent = ghost;
        // Ohne Tiefen-Schreiben verdeckt die Platte nichts mehr, was unter ihr
        // liegt — der eigentliche Punkt der Übung.
        gm.depthWrite = !ghost;
        gm.needsUpdate = true;
      }
      gm.opacity = ghost ? Math.max(0.15, 1 - f * 0.85) : 1;
    }
  }

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
