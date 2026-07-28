import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { surfaceMaterial } from '@anima/scene-render';
import type { CutoutHandle, SurfaceMaterialSpec } from '@anima/scene-render';
import type { WorldLocation } from '../types';
import {
  asphaltTexture, awningTexture, facadeEmissive, facadeTexture, grassTexture, paversTexture, seededRandom, waterTexture,
} from './textures';

export const CELL = 10;

export function gridToWorld(gx: number, gy: number): THREE.Vector3 {
  return new THREE.Vector3(gx * CELL, 0, gy * CELL);
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

export interface Tile {
  loc: WorldLocation;
  /** Fassaden mit Fensterraster — leuchten nachts (emissive) */
  facadeMats?: THREE.MeshStandardMaterial[];
  group: THREE.Group;
  center: THREE.Vector3;
  isBuilding: boolean;
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
  /** prozedurale Deko (Bäume) — weicht einem Server-Modell */
  decor?: THREE.Group;
  /** Namens-Label — Höhe wird beim Modell-Tausch nachgeführt */
  labelObj?: CSS2DObject;
  shellMats: THREE.MeshStandardMaterial[];
  roofParts: THREE.Object3D[];
  roofMats: THREE.MeshStandardMaterial[];
  roomCenters: Map<string, THREE.Vector3>;
  /** Ausgangspunkt pro Raum (Welt-Koordinaten; Schlüssel: ID und Name) */
  roomExits: Map<string, THREE.Vector3>;
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
  /** Raum-Rechtecke in Welt-Koordinaten (Fokus-Erkennung) */
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
  /** Zoom-Zugabe für die Innenansicht bei mehrgeschossigen Gebäuden:
   *  Obergeschosse brauchen mehr Kameradistanz, sonst springt die Ansicht
   *  beim Rauszoomen zurück auf die Hülle, bevor man sie sehen kann */
  interiorLift: number;
  /** als outdoor markierte Räume (liefern keine Boden-Farbe fürs Gebäude) */
  roomOutdoor: Set<string>;
  /** Boden-/Sockelplatte DIESER Kachel (immer opak, Höhe 0) — die Innenansicht
   *  eines Gebäudes mit Keller muss durch sie hindurchsehen. */
  groundPlate?: THREE.Mesh;
  /** Szene dieser Kachel nutzt eine Etage < 0 (aus dem Payload abgeleitet,
   *  gesetzt von mountScene). Ohne Keller bleibt der Boden unangetastet. */
  hasBasement?: boolean;
  /** Flächen-Location (plan-area-locations.md): das Location-Modell bleibt in
   *  der Innenansicht stehen und bekommt stattdessen Löcher. Das Handle
   *  schaltet sie mit dem Crossfade — Fernsicht intaktes Modell, Innenansicht
   *  Löcher — und gibt beim Remount seine Material-Klone frei. */
  cutouts?: CutoutHandle;
  /** 0..1 — Kachel ist als Kamera-Verdecker ausgeblendet */
  occl: number;
  highlightRing: THREE.Mesh;
  fade: number;
  fadeTarget: number;
}

/** Etagenhöhe der Innenansicht (level * STOREY über dem Boden) */
const STOREY = 3;

/** Maßstabs-Anker pro Location, gesetzt aus dem Szenen-Payload:
 *  k = Welt-Meter pro Real-Meter (extent_m / plan_width_m); storeyWorld =
 *  Etagenhöhe in Welt-Metern (storey_height_m x k). */
const locationAnchors = new Map<string, { k: number; storeyWorld: number }>();

/** Anker setzen/aktualisieren; true = Wert hat sich geändert (Tile neu bauen). */
export function setLocationAnchor(locId: string, anchor: { k: number; storeyWorld: number }): boolean {
  const prev = locationAnchors.get(locId);
  if (prev && Math.abs(prev.k - anchor.k) < 1e-4 && Math.abs(prev.storeyWorld - anchor.storeyWorld) < 1e-4) {
    return false;
  }
  locationAnchors.set(locId, anchor);
  return true;
}

export function locationAnchor(loc: WorldLocation) {
  return locationAnchors.get(loc.id);
}

/** Etagenhöhe einer Location in Welt-Metern: Anker-Wert aus dem Payload,
 *  sonst der prozedurale Default (Location ohne Szene). */
export function storeyHeight(loc: WorldLocation): number {
  return locationAnchors.get(loc.id)?.storeyWorld ?? STOREY;
}

/** Figuren-Maßstab in Räumen: k aus dem Payload (Figuren in Real-Metern ×
 *  Kompressionsfaktor); ohne Szene der prozedurale Default. */
export function roomFigureScale(loc: WorldLocation): number {
  return locationAnchors.get(loc.id)?.k ?? 1 / 3;
}

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
interface SurfaceBlend {
  toward: string;
  zones: { kind: string; until?: number }[];
  noise?: number;
}
interface SurfaceEntry {
  url?: string; sizeM: number; blend?: SurfaceBlend;
  /** Materialklasse der Art (Bibliothek) — Wasser wird anders beleuchtet als
   *  Gras, und zwar in BEIDEN Renderern gleich (@anima/scene-render). */
  material?: SurfaceMaterialSpec | null;
}
const serverSurfaces = new Map<string, SurfaceEntry>();
const serverSurfaceCache = new Map<string, THREE.Texture>();
export function setSurfaceTextures(list: { kind: string; url?: string; size_m?: number;
                                           blend?: SurfaceBlend;
                                           material?: SurfaceMaterialSpec | null }[]) {
  for (const t of list) {
    serverSurfaces.set(t.kind.toLowerCase(), {
      url: t.url, sizeM: t.size_m || 3, blend: t.blend, material: t.material ?? null });
  }
}

/** Materialklasse einer Art ('' / unbekannt = matt, also wie bisher). */
export function surfaceMaterialSpec(kind: string | undefined): SurfaceMaterialSpec | null {
  return serverSurfaces.get((kind || '').toLowerCase())?.material ?? null;
}

export function hasSurfaceTexture(kind: string): boolean {
  return serverSurfaces.has(kind);
}

/** Terrain-Arten der Nachbar-Kacheln ("gx,gy" -> kind) für Zusammenstellungen. */
const terrainGrid = new Map<string, string>();
export function setTerrainGrid(entries: { gx: number; gy: number; kind: string }[]) {
  terrainGrid.clear();
  for (const e of entries) terrainGrid.set(`${e.gx},${e.gy}`, e.kind);
}

/** Oberflächen-Art fürs Nachbarschafts-Grid (Zusammenstellungen). */
export function gridSurfaceKind(loc: WorldLocation): string {
  return surfaceKindOf(loc, detectStyle(loc));
}

/** Oberflächen-Art einer Location: terrain als Bibliotheks-kind (offenes
 *  Vokabular) vor dem normalisierten Legacy-Vokabular. */
export function surfaceKindOf(loc: WorldLocation, style: string): string {
  const raw = (loc.terrain || '').toLowerCase().trim();
  if (raw && serverSurfaces.has(raw)) return raw;
  return style;   // Legacy: road/grass/water/forest (prozedurale Fallbacks)
}

/** Kachelbare Oberflächen-Textur für einen Terrain-Typ: Server-Bibliothek
 *  vor eingebautem Fallback; Wiederholung im Welt-Maßstab (CELL/size_m). */
function surfaceTexture(kind: string, fallback: THREE.Texture): THREE.Texture {
  const entry = serverSurfaces.get(kind);
  if (!entry?.url) return fallback;
  let tex = serverSurfaceCache.get(kind);
  if (!tex) {
    tex = loader.load(entry.url);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(CELL / entry.sizeM, CELL / entry.sizeM);
    serverSurfaceCache.set(kind, tex);
  }
  return tex;
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

/** Bild einer Art fürs Canvas-Compositing laden (Server-Bild oder das
 *  Canvas der prozeduralen Fallback-Textur). */
async function surfaceImage(kind: string, fallback: THREE.Texture): Promise<{ img: CanvasImageSource; sizeM: number }> {
  const entry = serverSurfaces.get(kind);
  if (entry?.url) {
    const tex = await loader.loadAsync(entry.url);
    return { img: tex.image as CanvasImageSource, sizeM: entry.sizeM };
  }
  return { img: fallback.image as CanvasImageSource, sizeM: 3 };
}

/** Wert-Rauschen (deterministisch je Kachel) für organische Zonengrenzen. */
function makeNoise(seed: string): (x: number, y: number) => number {
  const rnd = seededRandom('surface:' + seed);
  const grid: number[] = Array.from({ length: 64 }, () => rnd());
  const at = (ix: number, iy: number) => grid[((iy & 7) * 8 + (ix & 7))];
  return (x, y) => {
    const fx = x * 7, fy = y * 7;
    const ix = Math.floor(fx), iy = Math.floor(fy);
    const tx = fx - ix, ty = fy - iy;
    const lerp = (a: number, b: number, t: number) => a + (b - a) * (t * t * (3 - 2 * t));
    return lerp(
      lerp(at(ix, iy), at(ix + 1, iy), tx),
      lerp(at(ix, iy + 1), at(ix + 1, iy + 1), tx),
      ty
    );
  };
}

/** Zusammenstellung backen (z.B. Küste): Zonen-Verlauf Richtung der
 *  toward-Nachbarn, Zonengrenzen mit Rauschen, Texturen im Welt-Maßstab. */
async function bakeBlendTexture(
  loc: WorldLocation, blend: SurfaceBlend, fallbackFor: (kind: string) => THREE.Texture
): Promise<THREE.CanvasTexture | null> {
  const gx = loc.grid_x!, gy = loc.grid_y!;
  // Richtungen der toward-Nachbarn (4er-Nachbarschaft; +y = Süden)
  const dirs: [number, number][] = [];
  for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
    if (terrainGrid.get(`${gx + dx},${gy + dy}`) === blend.toward) dirs.push([dx, dy]);
  }
  if (!dirs.length) return null;   // kein toward-Nachbar -> Landzone pur
  // Land-Art: häufigste Nachbar-Art, die nicht toward ist
  const counts = new Map<string, number>();
  for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
    const k = terrainGrid.get(`${gx + dx},${gy + dy}`);
    if (k && k !== blend.toward) counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const neighborKind = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'grass';

  const N = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = N;
  const ctx = canvas.getContext('2d')!;
  const noise = makeNoise(loc.id);
  const amp = blend.noise ?? 0.06;

  // Zonen auflösen (kind "neighbor" ersetzen) und Muster vorbereiten
  const zones = blend.zones.map((z) => ({
    kind: z.kind === 'neighbor' ? neighborKind : z.kind,
    until: z.until ?? 1.01,
  }));
  const patterns: CanvasPattern[] = [];
  for (const z of zones) {
    const { img, sizeM } = await surfaceImage(z.kind, fallbackFor(z.kind));
    const px = Math.max(8, Math.round((sizeM / CELL) * N));   // Musterkachel in Pixeln
    const pc = document.createElement('canvas');
    pc.width = pc.height = px;
    pc.getContext('2d')!.drawImage(img, 0, 0, px, px);
    patterns.push(ctx.createPattern(pc, 'repeat')!);
  }

  // Pro Zone eine Maske aus dem Abstand zur toward-Kante malen
  const cell = 4;                                   // Masken-Auflösung (64x64 Blöcke)
  for (let zi = 0; zi < zones.length; zi++) {
    const prev = zi === 0 ? -1 : zones[zi - 1].until;
    ctx.save();
    ctx.beginPath();
    for (let by = 0; by < N; by += cell) {
      for (let bx = 0; bx < N; bx += cell) {
        const ux = (bx + cell / 2) / N, uy = (by + cell / 2) / N;
        let ramp = 0;
        for (const [dx, dy] of dirs) {
          const r = dx > 0 ? ux : dx < 0 ? 1 - ux : dy > 0 ? uy : 1 - uy;
          ramp = Math.max(ramp, r);
        }
        const d = 1 - ramp + (noise(ux, uy) - 0.5) * 2 * amp;   // Abstand zur Wasserkante
        if (d > prev && d <= zones[zi].until) ctx.rect(bx, by, cell, cell);
      }
    }
    ctx.clip();
    ctx.fillStyle = patterns[zi];
    ctx.fillRect(0, 0, N, N);
    ctx.restore();
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
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

/** Bodenplatte der Zelle — Oberflächen-Textur des Terrain-Typs (Server-
 *  Bibliothek, sonst prozedural). Die 2D-Kartenbilder werden NICHT mehr
 *  als Boden verwendet (Illustrationen mit eingebackenen Schatten/Objekten
 *  passen nicht in die 3D-Szene). */
function groundPlate(_loc: WorldLocation, tex: THREE.Texture,
                    material?: SurfaceMaterialSpec | null): THREE.Mesh {
  // Die Kachel-Oberfläche geht durch dieselbe Fabrik wie die Szenen-Platten:
  // eine Wasser-Location soll auf der Karte so aussehen wie im Raum.
  const mat = surfaceMaterial(THREE, { material, map: tex, transparent: true }) as THREE.MeshStandardMaterial;
  const plate = new THREE.Mesh(new THREE.PlaneGeometry(CELL, CELL), mat);
  plate.rotation.x = -Math.PI / 2;
  plate.position.y = 0.04;
  plate.receiveShadow = true;
  return plate;
}

function makeTree(rnd: () => number): THREE.Group {
  const g = new THREE.Group();
  const trunk = box(0.3, 0.8, 0.3, std({ color: 0x6b4a2f }));
  trunk.position.y = 0.4;
  const c1 = new THREE.Mesh(new THREE.ConeGeometry(1.1 + rnd() * 0.4, 1.8, 7), std({ color: 0x3e6b35 }));
  c1.position.y = 1.6;
  const c2 = new THREE.Mesh(new THREE.ConeGeometry(0.8 + rnd() * 0.3, 1.4, 7), std({ color: 0x4a7d3e }));
  c2.position.y = 2.5;
  c1.castShadow = c2.castShadow = true;
  g.add(trunk, c1, c2);
  const s = 0.8 + rnd() * 0.7;
  g.scale.setScalar(s);
  return g;
}

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
  const center = gridToWorld(loc.grid_x!, loc.grid_y!);
  const group = new THREE.Group();
  group.position.copy(center);
  group.userData.locationId = loc.id;

  const ringMat = new THREE.MeshBasicMaterial({ color: 0xf2cd6e, transparent: true, opacity: 0.85 });
  const ring = new THREE.Mesh(new THREE.RingGeometry(CELL * 0.42, CELL * 0.48, 40), ringMat);
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.09;
  ring.visible = false;

  const tile: Tile = {
    loc, group, center, isBuilding, height: 0,
    interior: null, interiorLabels: [], shellMats: [], roofParts: [], roofMats: [],
    roomCenters: new Map(), roomExits: new Map(), roomSlots: new Map(), roomSpots: new Map(),
    roomSitSpots: new Map(), roomLieSpots: new Map(), roomMarkers: new Map(),
    roomGroups: new Map(), roomRects: new Map(), roomLevels: new Map(), alwaysVisibleRooms: new Set(),
    outlineWalls: [], levelSlabs: new Map(), levelWallMats: new Map(), levelFilter: 0, interiorLift: 0, roomOutdoor: new Set(),
    highlightRing: ring, fade: 0, fadeTarget: 0, occl: 0,
  };

  const rnd = seededRandom(loc.id);
  const fallbackFor = (s: string) => (s === 'road' ? asphaltTex! : s === 'water' ? waterTex! : grassTex!);
  // Boden = Oberflächen-Textur des Terrain-Typs (Server-Bibliothek AV3D-13,
  // sonst prozedural) — 2D-Kartenbilder sind kein Fallback mehr.
  // Boden: Art auflösen (terrain als Bibliotheks-kind vor Legacy-Stil);
  // Zusammenstellungen (blend, z.B. Küste) werden asynchron gebacken und
  // ersetzen die Start-Textur, sobald fertig.
  const groundPlateFor = (): THREE.Mesh => {
    const kind = surfaceKindOf(loc, style);
    const entry = serverSurfaces.get(kind);
    const plate = groundPlate(loc, surfaceTexture(kind, fallbackFor(style)),
                              surfaceMaterialSpec(kind));
    if (entry?.blend) {
      void bakeBlendTexture(loc, entry.blend, (k) => fallbackFor(k)).then((tex) => {
        if (tex) {
          const m = plate.material as THREE.MeshStandardMaterial;
          m.map = tex;
          m.needsUpdate = true;
        }
      });
    }
    return plate;
  };
  // Benannte Natur-Location (z.B. See, Waldlichtung): kein Gebäude, aber Label/Räume
  const natureSite = isBuilding && (style === 'water' || style === 'forest' || style === 'grass' || style === 'road');

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
    if (style === 'forest') {
      const decor = new THREE.Group();
      for (let i = 0; i < 8; i++) {
        const tree = makeTree(rnd);
        tree.position.set((rnd() - 0.5) * (CELL - 3), 0, (rnd() - 0.5) * (CELL - 3));
        decor.add(tree);
      }
      group.add(decor);
      tile.decor = decor;
    }
    tile.height = style === 'forest' ? 3 : 0.3;
  } else if (natureSite) {
    tile.groundPlate = groundPlateFor();
    group.add(tile.groundPlate);
    if (style === 'forest') {
      // Bäume am Rand, Mitte bleibt frei für die Raum-Slabs
      const decor = new THREE.Group();
      for (let i = 0; i < 7; i++) {
        const tree = makeTree(rnd);
        const a = (i / 7) * Math.PI * 2 + rnd() * 0.5;
        tree.position.set(Math.cos(a) * (3.2 + rnd()), 0, Math.sin(a) * (3.2 + rnd()));
        decor.add(tree);
      }
      group.add(decor);
      tile.decor = decor;
    }
    tile.height = style === 'forest' ? 3 : 0.6;
    addLabel();
  } else {
    // Sockel-Platte unter Gebäuden: deklariertes Terrain der Location
    // (z.B. grass beim Campus) vor dem Pflaster-Default — "Terrain = grass"
    // soll auch in der Raumansicht Gras zeigen, nicht Steine
    const tKind = terrainKind(loc.terrain);
    const plinthTex = tKind
      ? surfaceTexture(surfaceKindOf(loc, tKind), fallbackFor(tKind))
      : paversTexture();
    const plinth = new THREE.Mesh(new THREE.PlaneGeometry(CELL, CELL), std({ map: plinthTex }));
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
      const ox = (ix / (N - 1) - 0.5) * slot.w * 0.78;
      const oz = (iz / (N - 1) - 0.5) * slot.d * 0.78;
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
  // Referenzmessung am Exit: generierte Meshes haben an verdeckten Stellen
  // LÖCHER im Boden — Raster-Strahlen fallen dort auf die Sockelplatte
  // durch und die dominante Lage unterschätzt den Boden (Figuren stehen im
  // Boden). An der Tür ist der Boden praktisch immer intakt (Sichtfeld der
  // Generierung): liegt der Treffer dort ETWAS über der dominanten Lage,
  // ist ER der Boden; deutlich höhere Treffer (Möbel vor der Tür) nicht.
  const exitP = tile.roomExits.get(roomId);
  if (exitP) {
    ray.set(new THREE.Vector3(exitP.x, base.y + 20, exitP.z), down);
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
    // Mitte/Ausgang auf die echte Bodenhöhe heben (Instanz für ID+Name geteilt)
    center?.setY(floor + 0.01);
    tile.roomExits.get(roomId)?.setY(floor + 0.01);
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
        // nur die abgetastete FLÄCHE, nicht die Sitzhöhe des Clips. Nie unter
        // den Boden: eine Sitzfläche knapp über dem Boden darf die Figur
        // nicht versenken.
        e.p.setY(Math.max(floor, surface - e.drop) + 0.01 + e.offsetY);
      }
    }
  }
  restoreSides();
}

/** Standhöhe auf KACHEL-Ebene (Figur außerhalb der Räume, z.B. am
 *  Eingang): Gebäude-Meshes haben oft eine eingebackene Bodenhaut/Gelände
 *  um den Eingang — die Figur steht auf der tatsächlichen Oberfläche statt
 *  bei y=0 darin zu versinken. Strahl von oben; Dach-Treffer (alles über
 *  1,2 m) werden übersprungen, ohne Treffer bleibt es beim Kachel-Boden. */
export function tileGroundY(tile: Tile, at: THREE.Vector3): number {
  const target = tile.serverModel;
  if (!target) return 0;
  const ray = new THREE.Raycaster(
    new THREE.Vector3(at.x, 20, at.z), new THREE.Vector3(0, -1, 0));
  for (const h of ray.intersectObject(target, true)) {
    if (h.point.y < 1.2) return h.point.y + 0.01;
  }
  return 0;
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
    w.mesh.visible = cullOk && w.level <= tile.levelFilter;
  }
}

/** Etagen-Auswahl anwenden: gewählte Etage voll, darunter gedimmter
 *  Kontext, darüber ausgeblendet. */
export function applyLevelDisplay(tile: Tile) {
  for (const [lv, slab] of tile.levelSlabs) {
    slab.visible = lv <= tile.levelFilter;
    const m = slab.material as THREE.MeshStandardMaterial;
    m.opacity = lv === tile.levelFilter ? 1 : 0.85;
  }
  for (const [lv, mats] of tile.levelWallMats) {
    for (const mat of mats) mat.opacity = lv === tile.levelFilter ? 1 : 0.45;
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

/** Crossfade Außenansicht <-> Raumansicht (fade 0..1). */
export function applyTileFade(tile: Tile, dt: number) {
  tile.fade = THREE.MathUtils.lerp(tile.fade, tile.fadeTarget, 1 - Math.exp(-6 * dt));
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

  // Flächen-Location: statt das Modell wegzublenden werden seine Löcher
  // geschaltet — derselbe Zustand, andere Wirkung. Fernsicht zeigt die
  // Location intakt, die Innenansicht schneidet Grundriss und abseits
  // stehende Räume heraus, damit das Rezept-Innenleben darin sichtbar wird.
  tile.cutouts?.setEnabled(f > 0.03);
  // Bei EINGEBLENDETER Unter-Etage tritt das Area-Modell ganz beiseite
  // (User-Befund 2026-07-28: die vergrößerte Boden-Öffnung war da, aber das
  // nie fadende Location-Modell stand davor). Gleiche Semantik wie der
  // Etagen-Umschalter für Platten (lv <= filter sichtbar) und die
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
