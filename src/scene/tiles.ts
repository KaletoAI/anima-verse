import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { Room, WorldLocation } from '../types';
import { mapIconUrl } from '../api';
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
  /** Namens-Label — Höhe wird beim Modell-Tausch nachgeführt */
  labelObj?: CSS2DObject;
  shellMats: THREE.MeshStandardMaterial[];
  roofParts: THREE.Object3D[];
  roofMats: THREE.MeshStandardMaterial[];
  roomCenters: Map<string, THREE.Vector3>;
  /** Ausgangspunkt pro Raum (Welt-Koordinaten; Schlüssel: ID und Name) */
  roomExits: Map<string, THREE.Vector3>;
  /** Andockpunkte für Raum-Modelle (AV3D-2): Raum-ID -> Halter + Maße + Platte */
  roomSlots: Map<string, { holder: THREE.Group; w: number; d: number; plate: THREE.Mesh }>;
  /** freie Stellflächen im Raum-Modell (Welt-Koordinaten auf Bodenhöhe) */
  roomSpots: Map<string, THREE.Vector3[]>;
  /** erkannte Sitzflächen (Möbelhöhe, kleine Flächen) */
  roomSitSpots: Map<string, THREE.Vector3[]>;
  /** erkannte Liegeflächen (Möbelhöhe, große zusammenhängende Flächen) */
  roomLieSpots: Map<string, THREE.Vector3[]>;
  /** kuratierte Animations-Marker (AV3D-11): Raum -> Clip-Kind -> Punkte
   *  (rotation = Blickrichtung in Grad, offsetY additiv zur Auflagehöhe) */
  roomMarkers: Map<string, Map<string, { p: THREE.Vector3; rotation?: number; offsetY: number }[]>>;
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
  outlineWalls: { mesh: THREE.Mesh; mid: THREE.Vector2; normal: THREE.Vector2 }[];
  /** Etagen-Bodenplatten des Grundrisses (für Boden-Farbübernahme) */
  levelSlabs: Map<number, THREE.Mesh>;
  /** als outdoor markierte Räume (liefern keine Boden-Farbe fürs Gebäude) */
  roomOutdoor: Set<string>;
  /** 0..1 — Kachel ist als Kamera-Verdecker ausgeblendet */
  occl: number;
  highlightRing: THREE.Mesh;
  fade: number;
  fadeTarget: number;
}

/** Etagenhöhe der Innenansicht (level * STOREY über dem Boden) */
const STOREY = 3;

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

function std(opts: THREE.MeshStandardMaterialParameters): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0.02, transparent: true, ...opts });
}

function box(w: number, h: number, d: number, mat: THREE.Material | THREE.Material[]): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** Bodenplatte der Zelle; versucht das 2D-Kartensymbol des Backends als Textur. */
function groundPlate(loc: WorldLocation, fallback: THREE.Texture): THREE.Mesh {
  const mat = std({ map: fallback });
  const plate = new THREE.Mesh(new THREE.PlaneGeometry(CELL, CELL), mat);
  plate.rotation.x = -Math.PI / 2;
  plate.position.y = 0.04;
  plate.receiveShadow = true;
  loader.load(mapIconUrl(loc.id), (tex) => {
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.center.set(0.5, 0.5);
    tex.rotation = -THREE.MathUtils.degToRad(loc.map_rotation_2d || 0);
    mat.map = tex;
    mat.needsUpdate = true;
  }, undefined, () => { /* kein Icon vorhanden -> Fallback-Textur bleibt */ });
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

/** Innenansicht: Raum-Slabs im Auto-Grid, Labels, Eingangs-Marker. */
function buildInterior(tile: Tile, spec: BuildingSpec, opts: { walls?: boolean; markers?: boolean } = {}) {
  const loc = tile.loc;
  if (!loc.rooms.length) return;
  const g = new THREE.Group();
  g.visible = false;

  const W = spec.w;
  const D = spec.d;
  if (opts.walls !== false) {
    const floorMat = std({ color: 0xd8d0c2 });
    const floor = box(W, 0.25, D, floorMat);
    floor.position.y = 0.125;
    g.add(floor);

    // niedrige Außenwände, damit man "hineinsehen" kann
    const wallMat = std({ color: 0xa89a86 });
    const t = 0.22, wh = 1.1;
    for (const [w, d, x, z] of [
      [W, t, 0, -D / 2], [W, t, 0, D / 2], [t, D, -W / 2, 0], [t, D, W / 2, 0],
    ] as const) {
      const wall = box(w, wh, d, wallMat);
      wall.position.set(x, wh / 2 + 0.25, z);
      g.add(wall);
    }
  }

  const open = opts.walls === false; // Naturfläche: flacher + durchscheinend
  const addRoomCommon = (room: Room, x: number, z: number, floorY: number, hue: number, rw: number, rd: number, parent: THREE.Group = g): THREE.Mesh => {
    const plate = box(rw, open ? 0.08 : 0.18, rd, std({
      color: new THREE.Color(`hsl(${hue}, 42%, 72%)`),
      opacity: open ? 0.55 : 1,
    }));
    plate.position.set(x, floorY + (open ? 0.18 : 0.35), z);
    parent.add(plate);

    const el = document.createElement('div');
    el.className = 'room-label';
    el.textContent = room.name;
    const label = new CSS2DObject(el);
    label.position.set(x, floorY + 1.5, z);
    parent.add(label);
    tile.interiorLabels.push(label);

    const worldPos = tile.center.clone().add(new THREE.Vector3(x, floorY + 0.45, z));
    tile.roomCenters.set(room.id, worldPos);
    tile.roomCenters.set(room.name, worldPos);
    return plate;
  };

  // Räume ohne Layout: Auto-Grid im Erdgeschoss (bisheriges Verhalten)
  const autoRooms = loc.rooms.filter((r) => !r.layout);
  const n = autoRooms.length;
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const gap = 0.35;
  const rw = n ? (W - 0.6 - gap * (cols - 1)) / cols : 0;
  const rd = n ? (D - 0.6 - gap * (rows - 1)) / rows : 0;
  autoRooms.forEach((room, i) => {
    const x = -W / 2 + 0.3 + (i % cols) * (rw + gap) + rw / 2;
    const z = -D / 2 + 0.3 + Math.floor(i / cols) * (rd + gap) + rd / 2;
    addRoomCommon(room, x, z, 0, (i * 67) % 360, rw, rd);

    if (opts.markers && loc.entry_room && room.id === loc.entry_room) {
      const mark = new THREE.Mesh(new THREE.CircleGeometry(0.45, 20), std({ color: 0xe0b64a }));
      mark.rotation.x = -Math.PI / 2;
      mark.position.set(x, 0.46, z + rd / 2 - 0.5);
      g.add(mark);
    }
  });

  // Räume mit Layout (AV3D-2): Position/Größe/Etage vom Server.
  // Referenzfläche ist ein FESTES 8x8-m-Quadrat zentriert auf der Kachel —
  // unabhängig vom Gebäudestil, damit Editor/Admin-Vorschau/Client dieselbe
  // Geometrie sehen (Vertrag: schnittstellen-3d.md, Platzierungs-Semantik).
  const LW = 8, LD = 8;
  const usedLevels = new Set<number>();
  const exitPtsL0: THREE.Vector2[] = [];   // EG-Ausgänge (lokal) -> Türen im Grundriss
  loc.rooms.forEach((room, i) => {
    const lay = room.layout;
    if (!lay) return;
    const roomW = Math.max(lay.w * LW, 0.5);
    const roomD = Math.max(lay.d * LD, 0.5);
    const x = -LW / 2 + (lay.x + lay.w / 2) * LW;
    const z = -LD / 2 + (lay.y + lay.d / 2) * LD;
    const floorY = (lay.level ?? 0) * STOREY;
    usedLevels.add(lay.level ?? 0);
    tile.roomLevels.set(room.id, lay.level ?? 0);
    tile.roomLevels.set(room.name, lay.level ?? 0);
    if ((room.indoor ?? '').toLowerCase() === 'outdoor') {
      tile.roomOutdoor.add(room.id);
      tile.roomOutdoor.add(room.name);
    }
    // eigene Gruppe pro Raum — für den Fokus-Modus komplett ausblendbar.
    // always_visible (Server-Entscheidung, Default aus): Raum hängt direkt
    // an der Kachel und ist damit dauerhaft sichtbar — für Outdoor-Räume,
    // die nicht schon im Gebäude-Modell abgebildet sind.
    const rg = new THREE.Group();
    if (lay.always_visible === true) {
      tile.group.add(rg);
      tile.alwaysVisibleRooms.add(room.id);
      tile.alwaysVisibleRooms.add(room.name);
    } else {
      g.add(rg);
    }
    tile.roomGroups.set(room.id, rg);
    tile.roomRects.set(room.id, { x: tile.center.x + x, z: tile.center.z + z, w: roomW, d: roomD });
    const plate = addRoomCommon(room, x, z, floorY, (i * 67) % 360, roomW, roomD, rg);

    // Andockpunkt für das Raum-Modell: knapp über der Etagen-Platte (+0.08),
    // damit der Modell-Boden fast mit dem Etagen-Boden verschmilzt — die
    // Platzhalter-Platte wird beim Modell-Einwechseln ohnehin ausgeblendet.
    // layout.rotation dreht den Raum-INHALT (analog map3d.rotation).
    const holder = new THREE.Group();
    holder.position.set(x, floorY + 0.06, z);
    holder.rotation.y = -THREE.MathUtils.degToRad(lay.rotation ?? 0);
    rg.add(holder);
    tile.roomSlots.set(room.id, { holder, w: roomW, d: roomD, plate });

    // Animations-Marker (AV3D-11): Welt-Positionen auf Platten-Höhe;
    // applyRoomModel verfeinert die Höhe später per Abtastung
    if (lay.markers?.length) {
      const byKind = new Map<string, { p: THREE.Vector3; rotation?: number; offsetY: number }[]>();
      for (const m of lay.markers) {
        if (!m?.at || !m.animation) continue;
        const mx = -LW / 2 + (lay.x + m.at[0] * lay.w) * LW;
        const mz = -LD / 2 + (lay.y + m.at[1] * lay.d) * LD;
        const p = tile.center.clone().add(new THREE.Vector3(mx, floorY + 0.45 + (m.offset_y ?? 0), mz));
        const entry = { p, rotation: m.rotation, offsetY: m.offset_y ?? 0 };
        (byKind.get(m.animation) ?? byKind.set(m.animation, []).get(m.animation)!).push(entry);
        if (opts.markers) {   // Debug-/Editor-Ansicht: Marker als türkise Punkte
          const dot = new THREE.Mesh(new THREE.CircleGeometry(0.22, 16), std({ color: 0x4ac3e0 }));
          dot.rotation.x = -Math.PI / 2;
          dot.position.set(mx, floorY + 0.47, mz);
          rg.add(dot);
        }
      }
      tile.roomMarkers.set(room.id, byKind);
      tile.roomMarkers.set(room.name, byKind);
    }

    // Ausgangspunkt: vom Server (exit) oder Mitte der dem Zentrum
    // zugewandten Raumkante als Fallback
    const ex = lay.exit
      ? -LW / 2 + (lay.x + lay.exit[0] * lay.w) * LW
      : x - Math.sign(x) * roomW / 2 * (Math.abs(x) > Math.abs(z) ? 1 : 0);
    const ez = lay.exit
      ? -LD / 2 + (lay.y + lay.exit[1] * lay.d) * LD
      : z - Math.sign(z) * roomD / 2 * (Math.abs(z) >= Math.abs(x) ? 1 : 0);
    const exitWorld = tile.center.clone().add(new THREE.Vector3(ex, floorY + 0.45, ez));
    tile.roomExits.set(room.id, exitWorld);
    tile.roomExits.set(room.name, exitWorld);
    if ((lay.level ?? 0) === 0) exitPtsL0.push(new THREE.Vector2(ex, ez));
    if (opts.markers) {
      const mark = new THREE.Mesh(new THREE.CircleGeometry(0.3, 18), std({ color: 0xe0b64a }));
      mark.rotation.x = -Math.PI / 2;
      mark.position.set(ex, floorY + 0.46, ez);
      rg.add(mark);
    }
  });

  // AV3D-12: gezeichneter GEBÄUDE-Grundriss (map3d.outline) — pro genutzter
  // Etage Boden + Wände entlang der Kontur; Türöffnung im Erdgeschoss am
  // südlichsten Wandstück (Räume selbst bleiben Rechtecke)
  const outline = (loc.map3d?.outline ?? []).filter((p) => Array.isArray(p) && p.length === 2);
  if (outline.length >= 3 && usedLevels.size) {
    const pts = outline.map(([fx, fz]) => new THREE.Vector2(-LW / 2 + fx * LW, -LD / 2 + fz * LD));
    const floorShape = new THREE.Shape(pts);
    const WALL_H = 0.8, DOOR_HALF = 0.4;
    // Polygon-Umlaufrichtung -> Außennormale der Wandstücke (fürs Culling)
    let area = 0;
    for (let k = 0; k < pts.length; k++) {
      const a = pts[k], b = pts[(k + 1) % pts.length];
      area += a.x * b.y - b.x * a.y;
    }
    const ccw = area > 0;
    const wallSeg = (a: THREE.Vector2, b: THREE.Vector2, floorY: number, mat: THREE.Material) => {
      const len = a.distanceTo(b);
      if (len < 0.06) return;
      const seg = box(len, WALL_H, 0.07, mat);
      seg.position.set((a.x + b.x) / 2, floorY + 0.08 + WALL_H / 2, (a.y + b.y) / 2);
      seg.rotation.y = -Math.atan2(b.y - a.y, b.x - a.x);
      seg.receiveShadow = false;
      g.add(seg);
      const dx = (b.x - a.x) / len, dz = (b.y - a.y) / len;
      tile.outlineWalls.push({
        mesh: seg,
        mid: new THREE.Vector2(tile.center.x + (a.x + b.x) / 2, tile.center.z + (a.y + b.y) / 2),
        normal: ccw ? new THREE.Vector2(dz, -dx) : new THREE.Vector2(-dz, dx),
      });
    };
    // Türen im EG: überall dort, wo ein Erdgeschoss-Exit auf der Kontur
    // liegt; findet sich keiner, ersatzweise das südlichste Wandstück
    let southIdx = 0, southZ = -Infinity;
    for (let k = 0; k < pts.length; k++) {
      const mid = (pts[k].y + pts[(k + 1) % pts.length].y) / 2;
      if (mid > southZ) { southZ = mid; southIdx = k; }
    }
    for (const level of usedLevels) {
      const floorY = level * STOREY;
      // Obergeschosse halbtransparent — sonst verdecken sie in der
      // Draufsicht das Erdgeschoss vollständig
      const upper = level > 0;
      const wallMat = std({ color: 0xcfc4b2, opacity: upper ? 0.45 : 1 });
      const slabMat = std({ color: 0xd8d0c2, opacity: upper ? 0.4 : 1 });
      const slab = new THREE.Mesh(
        new THREE.ExtrudeGeometry(floorShape, { depth: 0.14, bevelEnabled: false }),
        slabMat
      );
      slab.rotation.x = Math.PI / 2;                 // Shape-XY -> Boden-XZ
      // nach UNTEN extrudiert: Oberkante knapp über der Etage, damit die
      // Böden der Raum-Modelle (ab +0.12) nicht überdeckt werden
      slab.position.y = floorY + 0.08;
      slab.castShadow = level > 0;
      g.add(slab);
      tile.levelSlabs.set(level, slab);
      let doorsCut = 0;
      for (let k = 0; k < pts.length; k++) {
        const a = pts[k], b = pts[(k + 1) % pts.length];
        const len = a.distanceTo(b);
        const dir = b.clone().sub(a).divideScalar(Math.max(len, 1e-6));
        // Tür-Positionen auf diesem Wandstück sammeln (nur EG)
        const cuts: number[] = [];
        if (level === 0) {
          for (const e of exitPtsL0) {
            const t = THREE.MathUtils.clamp(e.clone().sub(a).dot(dir), 0, len);
            const closest = a.clone().addScaledVector(dir, t);
            if (closest.distanceTo(e) < 0.45) cuts.push(t);
          }
          if (!cuts.length && k === southIdx && !exitPtsL0.length) cuts.push(len / 2);
        }
        if (cuts.length) {
          doorsCut += cuts.length;
          cuts.sort((p, q2) => p - q2);
          let start = 0;
          for (const t of cuts) {
            wallSeg(a.clone().addScaledVector(dir, start), a.clone().addScaledVector(dir, Math.max(start, t - DOOR_HALF)), floorY, wallMat);
            start = Math.min(len, t + DOOR_HALF);
          }
          wallSeg(a.clone().addScaledVector(dir, start), b, floorY, wallMat);
        } else {
          wallSeg(a, b, floorY, wallMat);
        }
      }
      // EG ganz ohne Tür (Exits liegen alle im Inneren): Süd-Fallback
      if (level === 0 && doorsCut === 0) {
        const a = pts[southIdx], b = pts[(southIdx + 1) % pts.length];
        // vorhandenes Wandstück des Fallback-Randes entfernen und neu mit Tür bauen
        const idx = tile.outlineWalls.findIndex((w) =>
          Math.abs(w.mid.x - (tile.center.x + (a.x + b.x) / 2)) < 1e-4 &&
          Math.abs(w.mid.y - (tile.center.z + (a.y + b.y) / 2)) < 1e-4);
        if (idx >= 0) {
          const [w] = tile.outlineWalls.splice(idx, 1);
          g.remove(w.mesh);
          const len = a.distanceTo(b);
          const dir = b.clone().sub(a).divideScalar(len);
          const wm = w.mesh.material as THREE.Material;
          wallSeg(a, a.clone().addScaledVector(dir, Math.max(0, len / 2 - DOOR_HALF)), 0, wm);
          wallSeg(a.clone().addScaledVector(dir, Math.min(len, len / 2 + DOOR_HALF)), b, 0, wm);
        }
      }
    }
  }

  // AV3D-12: Fahrstuhl (map3d.elevator) — auf allen Etagen; Haltepunkte
  // fürs Routing beim Etagenwechsel
  const elev = loc.map3d?.elevator;
  if (elev?.length === 2 && usedLevels.size) {
    const exl = -LW / 2 + elev[0] * LW;
    const ezl = -LD / 2 + elev[1] * LD;
    const stopLevels = new Set([0, ...usedLevels]);
    const maxLevel = Math.max(...stopLevels);
    const topY = maxLevel * STOREY + 1.4;
    const postMat = std({ color: 0x8a93a0 });
    for (const [px, pz] of [[-0.4, -0.4], [0.4, -0.4], [-0.4, 0.4], [0.4, 0.4]] as const) {
      const post = box(0.06, topY, 0.06, postMat);
      post.position.set(exl + px, topY / 2, ezl + pz);
      post.receiveShadow = false;
      g.add(post);
    }
    tile.elevatorStops = new Map();
    for (const level of stopLevels) {
      const floorY = level * STOREY;
      const plat = box(0.75, 0.06, 0.75, std({ color: 0xaab4be }));
      plat.position.set(exl, floorY + 0.42, ezl);
      g.add(plat);
      tile.elevatorStops.set(level, tile.center.clone().add(new THREE.Vector3(exl, floorY + 0.45, ezl)));
    }
  }

  tile.interior = g;
  tile.group.add(g);
}

export interface BuildTileOpts {
  /** Eingangs-/Exit-Marker (gelbe Punkte) zeigen — nur für die
   *  Grundriss-Vorschau; im Spiel-Client bleiben sie aus. */
  markers?: boolean;
}

export function buildTile(loc: WorldLocation, opts: BuildTileOpts = {}): Tile {
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
    outlineWalls: [], levelSlabs: new Map(), roomOutdoor: new Set(),
    highlightRing: ring, fade: 0, fadeTarget: 0, occl: 0,
  };

  const rnd = seededRandom(loc.id);
  const fallbackFor = (s: string) => (s === 'road' ? asphaltTex! : s === 'water' ? waterTex! : grassTex!);
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
    group.add(groundPlate(loc, fallbackFor(style)));
    if (style === 'forest') {
      for (let i = 0; i < 8; i++) {
        const tree = makeTree(rnd);
        tree.position.set((rnd() - 0.5) * (CELL - 3), 0, (rnd() - 0.5) * (CELL - 3));
        group.add(tree);
      }
    }
    tile.height = style === 'forest' ? 3 : 0.3;
  } else if (natureSite) {
    group.add(groundPlate(loc, fallbackFor(style)));
    if (style === 'forest') {
      // Bäume am Rand, Mitte bleibt frei für die Raum-Slabs
      for (let i = 0; i < 7; i++) {
        const tree = makeTree(rnd);
        const a = (i / 7) * Math.PI * 2 + rnd() * 0.5;
        tree.position.set(Math.cos(a) * (3.2 + rnd()), 0, Math.sin(a) * (3.2 + rnd()));
        group.add(tree);
      }
    }
    tile.height = style === 'forest' ? 3 : 0.6;
    const spec: BuildingSpec = { w: 8, d: 8, h: 0, build() { /* Naturfläche */ } };
    buildInterior(tile, spec, { walls: false, markers: opts.markers });
    addLabel();
  } else {
    // Sockel-Platte unter Gebäuden (Pflaster)
    const plinth = new THREE.Mesh(new THREE.PlaneGeometry(CELL, CELL), std({ map: paversTexture() }));
    plinth.rotation.x = -Math.PI / 2;
    plinth.position.y = 0.045;
    plinth.receiveShadow = true;
    group.add(plinth);

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
    buildInterior(tile, spec, { markers: opts.markers });
    addLabel();
  }

  group.add(ring);
  tile.facadeMats = tile.shellMats.filter((m) => !!m.emissiveMap);
  return tile;
}

/** Server-Gebäudemodell (AV3D-9) einwechseln: ersetzt die prozedurale Hülle.
 *  Fürs Reinzoomen verhält sich das ganze Modell wie ein Dach — es blendet
 *  aus und gibt den Blick auf die Räume frei. */
export function applyBuildingModel(tile: Tile, model: THREE.Group) {
  if (!tile.isBuilding || tile.serverModel) return;
  tile.serverModel = model;
  // prozedurale Hülle ersetzen; Natur-Flächen (z.B. terrain "road"/"forest")
  // haben keine — dort kommt das Modell auf die Bodenplatte dazu
  if (tile.shell) {
    tile.group.remove(tile.shell);
    tile.shell = undefined;
  }

  // Ausrichtung & Größe bestimmt der Server pro Location (map3d.rotation in
  // Grad, map3d.size als Kachel-Anteil); map_rotation_2d dreht als Fallback
  // synchron zum 2D-Icon. Ohne Angaben: wie generiert, 92 % der Kachel.
  const yawDeg = tile.loc.map3d?.rotation ?? tile.loc.map_rotation_2d ?? 0;
  model.rotation.y = -THREE.MathUtils.degToRad(yawDeg);
  const frac = tile.loc.map3d?.size;
  const k = frac && frac > 0.05 && frac <= 1.5 ? frac / 0.92 : 1;
  model.scale.setScalar(k);

  // Fade-Verwaltung auf das Modell umziehen: Materialien pro Tile klonen
  // (Vorlage wird geteilt) und als "Dach" registrieren.
  tile.shellMats = [];
  tile.roofMats = [];
  tile.roofParts = [model];
  tile.facadeMats = [];
  model.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    if (Array.isArray(mesh.material)) {
      mesh.material = mesh.material.map((m) => {
        const c = m.clone();
        c.transparent = true;
        tile.roofMats.push(c as THREE.MeshStandardMaterial);
        return c;
      });
    } else {
      const c = mesh.material.clone();
      c.transparent = true;
      mesh.material = c;
      tile.roofMats.push(c as THREE.MeshStandardMaterial);
    }
  });
  tile.group.add(model);

  const h = ((model.userData.height as number) || tile.height) * k;
  tile.height = h;
  tile.labelObj?.position.set(0, h + 2.2, 0);
}

/** Server-Raummodell (AV3D-2) auf seine Bodenplatte setzen. Das Modell ist
 *  auf Einheits-Grundfläche normalisiert und wird in den Raum eingepasst.
 *  Danach wird die begehbare Fläche abgetastet: Fußhöhe + freie Stellen. */
export function applyRoomModel(tile: Tile, roomId: string, model: THREE.Group) {
  const slot = tile.roomSlots.get(roomId);
  if (!slot || slot.holder.children.length) return;
  const fp = (model.userData.footprint as { x: number; z: number }) ?? { x: 1, z: 1 };
  model.scale.setScalar(Math.min(slot.w / fp.x, slot.d / fp.z) * 0.96);
  model.position.y = (model.userData.offsetY as number) || 0;   // Server-Feinjustierung (Meter)
  slot.holder.add(model);
  slot.plate.visible = false;   // Platte nur als Platzhalter ohne Modell

  // Begehbarkeit abtasten: Raster von oben, 20. Perzentil = Bodenhöhe,
  // deutlich höhere Treffer sind Möbel/Wände (dort keine Figuren).
  tile.group.updateMatrixWorld(true);
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
      const hit = ray.intersectObject(model, true)[0];
      if (hit) samples.push({ p: hit.point.clone(), ix, iz, uv: hit.uv?.clone(), mesh: hit.object as THREE.Mesh });
    }
  }
  if (samples.length < 5) return;
  const heights = samples.map((s) => s.p.y).sort((a, b) => a - b);
  const floor = heights[Math.floor(heights.length * 0.2)];
  const spots = samples
    .filter((s) => s.p.y < floor + 0.12)                         // eben genug = begehbar
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

  // Boden-TEXTUR eines gewählten Raums auf die Etagen-Platte übernehmen
  // (layout.floor_source; solange kein Raum markiert ist, testweise die
  // Bibliothek). Die begehbaren Treffer spannen den UV-Bereich des Bodens
  // im Texturatlas auf; der Ausschnitt wird im Welt-Maßstab gekachelt
  // (Extrude-UVs der Platte sind Welt-Koordinaten in Metern).
  const sourceRoom = tile.loc.rooms.find((r) => r.id === roomId);
  const level = tile.roomLevels.get(roomId) ?? 0;
  // pro ETAGE gilt: der dort markierte Raum liefert den Boden seiner Platte;
  // nur wenn auf der Etage keiner markiert ist, greift der Bibliothek-Test
  const anySourceOnLevel = tile.loc.rooms.some(
    (r) => r.layout?.floor_source === true && (r.layout?.level ?? 0) === level
  );
  const isFloorSource = sourceRoom?.layout?.floor_source === true
    || (!anySourceOnLevel && sourceRoom?.name === 'Bibliothek');
  const slab = tile.levelSlabs.get(level);
  if (slab && isFloorSource) {
    const floorSamples = samples.filter((s) => s.p.y < floor + 0.12 && s.uv && s.mesh);
    const m0 = floorSamples[0]?.mesh;
    const same = floorSamples.filter((s) => s.mesh === m0);
    const mat0 = m0 ? (Array.isArray(m0.material) ? m0.material[0] : m0.material) as THREE.MeshStandardMaterial : null;
    const img = mat0?.map?.image as (CanvasImageSource & { width: number; height: number }) | undefined;
    if (img?.width && same.length >= 4) {
      let u0 = 1, u1 = 0, v0 = 1, v1 = 0;
      const worldBox = new THREE.Box3();
      for (const s of same) {
        u0 = Math.min(u0, s.uv!.x); u1 = Math.max(u1, s.uv!.x);
        v0 = Math.min(v0, s.uv!.y); v1 = Math.max(v1, s.uv!.y);
        worldBox.expandByPoint(s.p);
      }
      const wSize = worldBox.getSize(new THREE.Vector3());
      if (u1 - u0 > 0.02 && v1 - v0 > 0.02 && wSize.x > 0.3 && wSize.z > 0.3) {
        try {
          const C = 256;
          const canvas = document.createElement('canvas');
          canvas.width = canvas.height = C;
          const ctx = canvas.getContext('2d')!;
          ctx.drawImage(
            img,
            u0 * img.width, v0 * img.height,
            (u1 - u0) * img.width, (v1 - v0) * img.height,
            0, 0, C, C
          );
          const tex = new THREE.CanvasTexture(canvas);
          tex.colorSpace = THREE.SRGBColorSpace;
          tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
          tex.repeat.set(1 / Math.max(wSize.x, 0.5), 1 / Math.max(wSize.z, 0.5));
          const sm = slab.material as THREE.MeshStandardMaterial;
          sm.map = tex;
          sm.color.set(0xffffff);
          sm.needsUpdate = true;
          console.info('[rooms] Etagen-Boden übernimmt die Bibliotheks-Bodentextur');
        } catch { /* Bild nicht zeichenbar -> Platte bleibt einfarbig */ }
      }
    }
  }

  // Marker-Höhen verfeinern, plus Server-Feinjustierung. Sitz-Marker:
  // Wurzel so verankern, dass die vom Clip abgesenkte Hüfte auf der
  // Möbel-Oberkante landet (Oberfläche minus Clip-Sitzhöhe, nie unter dem
  // Boden). Liege-/sonstige Marker liegen auf der Oberfläche (Matratze).
  const markers = tile.roomMarkers.get(roomId);
  if (markers) {
    const seatDrop = 0.44 * (tile.loc.map3d?.figure_scale || 1 / 3);   // Mixamo-Sitzhöhe x Raum-Maßstab
    for (const [kind, entries] of markers) {
      for (const e of entries) {
        ray.set(new THREE.Vector3(e.p.x, base.y + 20, e.p.z), down);
        const hit = ray.intersectObject(model, true)[0];
        const surface = hit && hit.point.y < floor + 0.5 ? hit.point.y : floor;
        const anchor = kind === 'sit' ? Math.max(floor, surface - seatDrop) : surface;
        e.p.setY(anchor + 0.01 + e.offsetY);
      }
    }
  }
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
 *  Außenseite zur Kamera zeigt, stehen zwischen Kamera und Innenraum. */
export function applyWallCulling(tile: Tile, camX: number, camZ: number) {
  for (const w of tile.outlineWalls) {
    w.mesh.visible = (camX - w.mid.x) * w.normal.x + (camZ - w.mid.y) * w.normal.y <= 0;
  }
}

/** Fokus-Modus: füllt EIN Raum das Bild, werden die Nachbar-Räume der
 *  Kachel ausgeblendet (null = alle zeigen). */
export function applyRoomFocus(tile: Tile, focusRoomId: string | null) {
  for (const [id, rg] of tile.roomGroups) {
    rg.visible = !focusRoomId || id === focusRoomId;
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
  if (!tile.interior) return;

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
