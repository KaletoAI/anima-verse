import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { WorldLocation } from '../types';
import { mapIconUrl } from '../api';
import {
  asphaltTexture, awningTexture, facadeTexture, grassTexture, paversTexture, seededRandom,
} from './textures';

export const CELL = 10;

export function gridToWorld(gx: number, gy: number): THREE.Vector3 {
  return new THREE.Vector3(gx * CELL, 0, gy * CELL);
}

type TileStyle = 'forest' | 'road' | 'grass' | 'cafe' | 'house' | 'highrise' | 'generic';

export interface Tile {
  loc: WorldLocation;
  group: THREE.Group;
  center: THREE.Vector3;
  isBuilding: boolean;
  height: number;
  interior: THREE.Group | null;
  interiorLabels: CSS2DObject[];
  shellMats: THREE.MeshStandardMaterial[];
  roofParts: THREE.Object3D[];
  roofMats: THREE.MeshStandardMaterial[];
  roomCenters: Map<string, THREE.Vector3>;
  highlightRing: THREE.Mesh;
  fade: number;
  fadeTarget: number;
}

function detectStyle(loc: WorldLocation): TileStyle {
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
      const floors = Math.max(5, Math.min(10, 4 + loc.rooms.length * 2));
      return {
        w: 6.4, d: 6.4, h: floors * 2,
        build(tile, _rnd) {
          const h = this.h;
          const facade = facadeTexture('#8fa3b0', 4, floors, loc.id);
          const wallMat = std({ map: facade });
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
          const wallMat = std({ map: facadeTexture('#cdb694', 3, 1, loc.id) });
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
          const wallMat = std({ map: facadeTexture('#dbc9a9', 3, 1, loc.id) });
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
    default:
      return {
        w: 7, d: 6, h: 6,
        build(tile, _rnd) {
          const wallMat = std({ map: facadeTexture('#b3a48f', 3, 3, loc.id) });
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

/** Innenansicht: Raum-Slabs im Auto-Grid, Labels, Eingangs-Marker. */
function buildInterior(tile: Tile, spec: BuildingSpec) {
  const loc = tile.loc;
  if (!loc.rooms.length) return;
  const g = new THREE.Group();
  g.visible = false;

  const W = spec.w;
  const D = spec.d;
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

  const n = loc.rooms.length;
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const gap = 0.35;
  const rw = (W - 0.6 - gap * (cols - 1)) / cols;
  const rd = (D - 0.6 - gap * (rows - 1)) / rows;

  loc.rooms.forEach((room, i) => {
    const cx = i % cols;
    const cz = Math.floor(i / cols);
    const x = -W / 2 + 0.3 + cx * (rw + gap) + rw / 2;
    const z = -D / 2 + 0.3 + cz * (rd + gap) + rd / 2;
    const hue = (i * 67) % 360;
    const plate = box(rw, 0.18, rd, std({ color: new THREE.Color(`hsl(${hue}, 42%, 72%)`) }));
    plate.position.set(x, 0.35, z);
    g.add(plate);

    const el = document.createElement('div');
    el.className = 'room-label';
    el.textContent = room.name;
    const label = new CSS2DObject(el);
    label.position.set(x, 1.5, z);
    g.add(label);
    tile.interiorLabels.push(label);

    const worldPos = tile.center.clone().add(new THREE.Vector3(x, 0.45, z));
    tile.roomCenters.set(room.id, worldPos);
    tile.roomCenters.set(room.name, worldPos);

    if (loc.entry_room && room.id === loc.entry_room) {
      const mark = new THREE.Mesh(new THREE.CircleGeometry(0.45, 20), std({ color: 0xe0b64a }));
      mark.rotation.x = -Math.PI / 2;
      mark.position.set(x, 0.46, z + rd / 2 - 0.5);
      g.add(mark);
    }
  });

  tile.interior = g;
  tile.group.add(g);
}

export function buildTile(loc: WorldLocation, fallbacks?: { grass: THREE.Texture; asphalt: THREE.Texture }): Tile {
  grassTex = fallbacks?.grass ?? grassTex ?? grassTexture();
  asphaltTex = fallbacks?.asphalt ?? asphaltTex ?? asphaltTexture();

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
    roomCenters: new Map(), highlightRing: ring, fade: 0, fadeTarget: 0,
  };

  const rnd = seededRandom(loc.id);

  if (!isBuilding) {
    const fallbackTex = style === 'road' ? asphaltTex : grassTex;
    group.add(groundPlate(loc, fallbackTex));
    if (style === 'forest') {
      for (let i = 0; i < 8; i++) {
        const tree = makeTree(rnd);
        tree.position.set((rnd() - 0.5) * (CELL - 3), 0, (rnd() - 0.5) * (CELL - 3));
        group.add(tree);
      }
    }
    tile.height = style === 'forest' ? 3 : 0.3;
  } else {
    // Sockel-Platte unter Gebäuden (Pflaster)
    const plinth = new THREE.Mesh(new THREE.PlaneGeometry(CELL, CELL), std({ map: paversTexture() }));
    plinth.rotation.x = -Math.PI / 2;
    plinth.position.y = 0.045;
    plinth.receiveShadow = true;
    group.add(plinth);

    const spec = buildingSpec(style, loc);
    spec.build(tile, rnd);
    tile.height = spec.h;
    buildInterior(tile, spec);

    const el = document.createElement('div');
    el.className = 'loc-label';
    el.textContent = loc.name;
    const label = new CSS2DObject(el);
    label.position.set(0, tile.height + 2.2, 0);
    group.add(label);
  }

  group.add(ring);
  return tile;
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
  for (const m of tile.shellMats) m.opacity = 1 - f * 0.88;
  tile.interior.visible = f > 0.03;
  for (const l of tile.interiorLabels) l.visible = f > 0.5;
}
