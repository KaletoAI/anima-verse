import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { sampleTerrain, surfaceMaterial, worldToLocalXZ } from '@anima/scene-render';
import type { CutoutHandle, SceneModelSpec, SceneTerrain, SurfaceMaterialSpec } from '@anima/scene-render';
import type { WorldLocation } from '../types';
import { acceptsWalkHit, type GroundModelInfo } from '../game/ground';
import {
  asphaltTexture, awningTexture, facadeEmissive, facadeTexture, grassTexture, paversTexture, seededRandom, waterTexture,
} from './textures';

// --- The FOOTPRINT of a location (E4 task 3, § A1.1) -------------------------
//
// CELL is gone, and with it `gridToWorld` and every neighbourhood built out of
// integer arithmetic. A location is a SQUARE: edge length `plan_width_m`,
// centre (`pos_x`, `pos_z`), turned by `yaw_deg` about the up axis. The tile's
// group carries exactly that — position and rotation — so everything hanging in
// it is placed in tile-local metres and lands where the server says it does.

/** Edge length of a location whose geometry declares no scale anchor
 *  (`plan_width_m` missing or ≤ 0), in metres.
 *
 *  The old world's cell was 10 m and every location filled one, so 10 keeps
 *  such a location the size it has always been drawn at — and `footprintWidth`
 *  says out loud when it had to fall back, because an unanchored location is a
 *  world-data defect, not a supported state (§ A1.1: without a positive anchor
 *  a location has no area at all). */
export const FOOTPRINT_FALLBACK_M = 10;

/** Locations already warned about — the fallback is a per-location fact, and a
 *  tile is rebuilt on every layout change. */
const widthWarned = new Set<string>();

/** Edge length of a location's footprint square in world metres. */
export function footprintWidth(loc: WorldLocation): number {
  const w = loc.plan_width_m ?? loc.map3d?.plan_width_m;
  if (typeof w === 'number' && Number.isFinite(w) && w > 0) return w;
  if (!widthWarned.has(loc.id)) {
    widthWarned.add(loc.id);
    console.warn(`[tiles] ${loc.name || loc.id}: no plan_width_m — drawing the`
      + ` footprint at the fallback ${FOOTPRINT_FALLBACK_M} m (§ A1.1)`);
  }
  return FOOTPRINT_FALLBACK_M;
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
 */
export function footprintCentre(
  loc: { pos_x?: number | null; pos_z?: number | null }
): THREE.Vector3 | null {
  const x = loc.pos_x;
  const z = loc.pos_z;
  if (typeof x !== 'number' || !Number.isFinite(x)) return null;
  if (typeof z !== 'number' || !Number.isFinite(z)) return null;
  return new THREE.Vector3(x, 0, z);
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
  /** Edge length of the footprint square in world metres (`plan_width_m`, or
   *  `FOOTPRINT_FALLBACK_M`). The ONE size this tile is drawn at: plate,
   *  plinth, selection ring, the occlusion corridor and the basement hole all
   *  come off it — there is no cell any more. */
  width: number;
  /** Footprint rotation in radians — `group.rotation.y`, § A1.1 sign. */
  yaw: number;
  isBuilding: boolean;
  /** Benannte Natur-Location (Wald, See, Wiese, Straße) — kein Gebäude,
   *  nur Gelände mit Label; Raum-Labels bleiben dort aus. */
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
  highlightRing: THREE.Mesh;
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

function box(w: number, h: number, d: number, mat: THREE.Material | THREE.Material[]): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** Ground plate of the FOOTPRINT — the surface texture of the location's
 *  terrain kind (server library, else procedural), over the whole
 *  `plan_width_m` square. The 2D map illustrations are NOT used as ground
 *  (baked-in shadows and objects do not belong in a 3D scene). */
function groundPlate(widthM: number, tex: THREE.Texture,
                    material?: SurfaceMaterialSpec | null): THREE.Mesh {
  // Die Kachel-Oberfläche geht durch dieselbe Fabrik wie die Szenen-Platten:
  // eine Wasser-Location soll auf der Karte so aussehen wie im Raum.
  const mat = surfaceMaterial(THREE, { material, map: tex, transparent: true }) as THREE.MeshStandardMaterial;
  const plate = new THREE.Mesh(new THREE.PlaneGeometry(widthM, widthM), mat);
  plate.rotation.x = -Math.PI / 2;
  plate.position.y = 0.04;
  plate.receiveShadow = true;
  return plate;
}

// `makeTree` stand hier bis 2026-08-02: prozedurale Kegel-Bäume auf
// forest-Kacheln. Seit Wald & Co. ihre Detailszene aus GESTREUTEN
// Bibliotheks-Props beziehen (plan-area-detail-scenes.md), sind generische
// Deko-Elemente für ALLE Geländearten gestrichen (User-Vorgabe) — das
// Gelände sagt nur noch die Bodentextur, was drauf steht, sagt die Welt.

interface BuildingSpec {
  w: number; d: number; h: number;
  build(tile: Tile, rnd: () => number): void;
}

function buildingSpec(style: TileStyle, loc: WorldLocation): BuildingSpec {
  switch (style) {
    case 'highrise': {
      const floors = Math.min(14, Math.max(2, loc.map3d?.floors ?? Math.max(5, Math.min(10, 4 + loc.rooms.length * 2))));
      return {
        w: 6.4, d: 6.4, h: floors * 2,
        build(tile, _rnd) {
          const h = this.h;
          const facade = facadeTexture(loc.map3d?.color || '#8fa3b0', 4, floors, loc.id);
          const wallMat = std({ map: facade, emissiveMap: facadeEmissive(4, floors, loc.id), emissive: new THREE.Color(0xffd98a), emissiveIntensity: 0 });
          const walls = box(this.w, h, this.d, wallMat);
          walls.position.y = h / 2;
          tile.group.add(walls);
          tile.shellMats.push(wallMat);
          const roofMat = std({ color: 0x62707a });
          const roof = box(this.w + 0.3, 0.4, this.d + 0.3, roofMat);
          roof.position.y = h + 0.2;
          const acMat = std({ color: 0x9aa8b2 });
          const ac = box(1.6, 0.9, 1.2, acMat);
          ac.position.set(1.2, h + 0.85, -0.8);
          tile.group.add(roof, ac);
          tile.roofParts.push(roof, ac);
          tile.roofMats.push(roofMat, acMat);
        },
      };
    }
    case 'cafe':
      return {
        w: 7, d: 5.2, h: 3.4,
        build(tile, rnd) {
          const wallMat = std({ map: facadeTexture(loc.map3d?.color || '#cdb694', 3, 1, loc.id), emissiveMap: facadeEmissive(3, 1, loc.id), emissive: new THREE.Color(0xffd98a), emissiveIntensity: 0 });
          const walls = box(this.w, this.h, this.d, wallMat);
          walls.position.set(0, this.h / 2, -1.2);
          tile.group.add(walls);
          tile.shellMats.push(wallMat);

          const roofMat = std({ color: 0x8c6d4f });
          const roof = box(this.w + 0.5, 0.35, this.d + 0.5, roofMat);
          roof.position.set(0, this.h + 0.17, -1.2);
          tile.group.add(roof);
          tile.roofParts.push(roof);
          tile.roofMats.push(roofMat);

          const awnMat = std({ map: awningTexture('#b8443c', '#efe6d4'), side: THREE.DoubleSide });
          const awning = new THREE.Mesh(new THREE.PlaneGeometry(this.w + 0.4, 1.6), awnMat);
          awning.rotation.x = -Math.PI / 3.1;
          awning.position.set(0, this.h - 0.5, 1.05);
          awning.castShadow = true;
          tile.group.add(awning);
          tile.roofParts.push(awning);
          tile.roofMats.push(awnMat);

          // kleine Terrasse mit Sonnenschirmen
          for (let i = 0; i < 2; i++) {
            const px = -1.8 + i * 3.6;
            const table = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.1, 10), std({ color: 0xd9d2c0 }));
            table.position.set(px, 0.75, 2.9);
            const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.75, 6), std({ color: 0x777 }));
            leg.position.set(px, 0.37, 2.9);
            const umb = new THREE.Mesh(new THREE.ConeGeometry(1.1, 0.5, 8), std({ color: i ? 0xb8443c : 0xe0a832 }));
            umb.position.set(px, 2.0, 2.9);
            umb.castShadow = true;
            const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.4, 6), std({ color: 0x8a8a8a }));
            pole.position.set(px, 1.2, 2.9);
            tile.group.add(table, leg, umb, pole);
          }
          void rnd;
        },
      };
    case 'house':
      return {
        w: 6.6, d: 5.6, h: 3,
        build(tile, _rnd) {
          const wallMat = std({ map: facadeTexture(loc.map3d?.color || '#dbc9a9', 3, 1, loc.id), emissiveMap: facadeEmissive(3, 1, loc.id), emissive: new THREE.Color(0xffd98a), emissiveIntensity: 0 });
          const walls = box(this.w, this.h, this.d, wallMat);
          walls.position.y = this.h / 2;
          tile.group.add(walls);
          tile.shellMats.push(wallMat);

          const roofMat = std({ color: 0x9e4f38 });
          const roof = new THREE.Mesh(new THREE.ConeGeometry(Math.hypot(this.w, this.d) / 2 + 0.3, 2.3, 4), roofMat);
          roof.rotation.y = Math.PI / 4;
          roof.scale.z = this.d / this.w;
          roof.position.y = this.h + 1.15;
          roof.castShadow = true;
          const chimMat = std({ color: 0x7d6a5a });
          const chim = box(0.6, 1.4, 0.6, chimMat);
          chim.position.set(this.w / 4, this.h + 1.6, -this.d / 5);
          tile.group.add(roof, chim);
          tile.roofParts.push(roof, chim);
          tile.roofMats.push(roofMat, chimMat);

          const hedge = box(this.w + 2, 0.7, 0.7, std({ color: 0x4a7d3e }));
          hedge.position.set(0, 0.35, this.d / 2 + 1.6);
          tile.group.add(hedge);
        },
      };
    default: {
      const floors = Math.min(6, Math.max(1, loc.map3d?.floors ?? 2));
      return {
        w: 7, d: 6, h: floors * 3,
        build(tile, _rnd) {
          const wallMat = std({ map: facadeTexture(loc.map3d?.color || '#b3a48f', 3, floors + 1, loc.id), emissiveMap: facadeEmissive(3, floors + 1, loc.id), emissive: new THREE.Color(0xffd98a), emissiveIntensity: 0 });
          const walls = box(this.w, this.h, this.d, wallMat);
          walls.position.y = this.h / 2;
          tile.group.add(walls);
          tile.shellMats.push(wallMat);
          const roofMat = std({ color: 0x776a58 });
          const roof = box(this.w + 0.3, 0.35, this.d + 0.3, roofMat);
          roof.position.y = this.h + 0.17;
          tile.group.add(roof);
          tile.roofParts.push(roof);
          tile.roofMats.push(roofMat);
        },
      };
    }
  }
}

/** Die Kachel baut nur noch das ÄUSSERE: Boden, prozedurale Hülle, Deko,
 *  Label, Auswahlring. Die Innenansicht (Platten, Wände, Fahrstuhl, Räume,
 *  Modelle) kommt vollständig aus dem Szenen-Rezept und wird von
 *  `mountScene` (sceneRecipe.ts) in dieselben Tile-Felder gebaut. Eine
 *  Location ohne Rezept (404) hat per Server-Definition weder Raum-Layout
 *  noch Grundriss noch Gebäudemodell — es gibt dort schlicht nichts
 *  aufzuklappen. */
export function buildTile(loc: WorldLocation): Tile {
  grassTex = grassTex ?? grassTexture();
  asphaltTex = asphaltTex ?? asphaltTexture();
  waterTex = waterTex ?? waterTexture();

  const style = detectStyle(loc);
  const isBuilding = !(loc.passable || loc.template_location_id);
  // THE footprint (§ A1.1): centre at (pos_x, pos_z), edge `plan_width_m`,
  // turned by `yaw_deg`. Position AND rotation sit on the group, so every
  // child is placed in tile-local metres — the same frame the scene payload
  // speaks. The callers filter on `footprintCentre` (`placeableOf`, `addTile`),
  // so an unplaced location never gets this far; if one ever does it says so
  // rather than joining a silent heap on the origin.
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

  const ringMat = new THREE.MeshBasicMaterial({ color: 0xf2cd6e, transparent: true, opacity: 0.85 });
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(width * 0.42, width * 0.48, 40), ringMat);
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.09;
  ring.visible = false;

  const tile: Tile = {
    loc, group, center, width, yaw, isBuilding, height: 0,
    interior: null, interiorLabels: [], shellMats: [], roofParts: [], roofMats: [],
    roomCenters: new Map(), roomDoors: new Map(),
    roomSlots: new Map(), roomSpots: new Map(),
    roomSitSpots: new Map(), roomLieSpots: new Map(), roomMarkers: new Map(),
    roomGroups: new Map(), roomRects: new Map(), roomLevels: new Map(), alwaysVisibleRooms: new Set(),
    outlineWalls: [], levelSlabs: new Map(), levelWallMats: new Map(), levelFilter: 0, roomOutdoor: new Set(),
    highlightRing: ring, fade: 0, fadeTarget: 0, occl: 0,
  };

  const rnd = seededRandom(loc.id);
  const fallbackFor = (s: string) => (s === 'road' ? asphaltTex! : s === 'water' ? waterTex! : grassTex!);
  // Boden = Oberflächen-Textur des Terrain-Typs (Server-Bibliothek AV3D-13,
  // sonst prozedural) — 2D-Kartenbilder sind kein Fallback mehr. Die Art
  // kommt vom Server (`surface_kind`), der Legacy-Stil wählt nur noch die
  // prozedurale Ersatztextur.
  const groundPlateFor = (): THREE.Mesh => {
    const kind = loc.surface_kind || style;
    return groundPlate(width, surfaceTexture(kind, fallbackFor(style), width),
                       surfaceMaterialSpec(kind));
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
    tile.groundPlate = groundPlateFor();
    group.add(tile.groundPlate);
    tile.height = style === 'forest' ? 3 : 0.3;
  } else if (natureSite) {
    tile.groundPlate = groundPlateFor();
    group.add(tile.groundPlate);
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
    const plinth = new THREE.Mesh(
      new THREE.PlaneGeometry(width, width), std({ map: plinthTex }));
    plinth.rotation.x = -Math.PI / 2;
    plinth.position.y = 0.045;
    plinth.receiveShadow = true;
    group.add(plinth);
    tile.groundPlate = plinth;

    const spec = buildingSpec(style, loc);
    // Hülle in eigene Gruppe kapseln, damit ein Server-Modell (AV3D-9) sie
    // später ersetzen kann — build() fügt direkt in tile.group ein.
    const before = new Set(group.children);
    spec.build(tile, rnd);
    const shell = new THREE.Group();
    for (const child of [...group.children]) {
      if (!before.has(child)) {
        group.remove(child);
        shell.add(child);
      }
    }
    group.add(shell);
    tile.shell = shell;
    tile.height = spec.h;
    addLabel();
  }

  group.add(ring);
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
  if (declaredFloor !== undefined) floor = declaredFloor;
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

/** Standhöhe auf KACHEL-Ebene (Figur außerhalb der Räume, z.B. am
 *  Eingang): Gebäude-Meshes haben oft eine eingebackene Bodenhaut/Gelände
 *  um den Eingang — die Figur steht auf der tatsächlichen Oberfläche statt
 *  bei y=0 darin zu versinken. Strahl von oben, ohne Treffer bleibt es beim
 *  Kachel-Boden.
 *
 *  WELCHER Treffer zählt, entscheidet die Spec und nicht mehr eine feste
 *  1,2-m-Marke (Befund B8): der Dachschutz gilt für GEBÄUDE-Modelle und misst
 *  ab deren deklarierter Standhöhe (`walk_y_world`), ein FLÄCHEN-Modell
 *  (`display: ground`/`shell_area`) IST der Boden und wird gar nicht
 *  gedeckelt — sonst fällt die Figur am erhöhten Ufer auf Ebene 0 zurück.
 *  Die Regel steht als reine Funktion in `game/ground.ts`. */
export function tileGroundY(tile: Tile, at: THREE.Vector3): number {
  const lift = terrainLiftAt(tile, at.x, at.z);
  const target = tile.serverModel;
  if (!target) return lift;
  const info: GroundModelInfo = {
    display: tile.modelIsGround ? 'ground'
      : tile.modelIsShellArea ? 'shell_area' : 'shell',
    walkY: tile.modelWalkY,
  };
  const ray = new THREE.Raycaster(
    new THREE.Vector3(at.x, 20, at.z), new THREE.Vector3(0, -1, 0));
  for (const h of ray.intersectObject(target, true)) {
    if (acceptsWalkHit(info, h.point.y)) return h.point.y + 0.01 + lift;
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

  const ringMat = tile.highlightRing.material as THREE.MeshBasicMaterial;
  ringMat.opacity = 0.7 * Math.max(0, 1 - f * 2);
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
