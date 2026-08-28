/**
 * PLACE GLYPHS (plan-posen-plaetze.md § 4, Task 13): a flat ring on every
 * FREE slot of the avatar's room, so the player sees where the avatar can
 * sit down and can click it. Pure view: which slots are free is the
 * server's word (`GET /play/places`, `free_slots`), the slot points are the
 * tile's own place inventory (`tile.roomMarkers`, world metres), and the
 * group only picks the colour. Rebuilt on every worldmap poll — occupancy
 * changes under the player — and the old group is disposed each time.
 */
import * as THREE from 'three';
import type { PlaceOffer } from '../api';
import type { PlaceEntry } from './placeSlot';

/** Ring colour per place group — the five groups the catalog knows. */
export const GLYPH_COLOUR_SEAT = 0xf2cd6e;     // the HUD's gold
export const GLYPH_COLOUR_BED = 0x8fb3ff;
export const GLYPH_COLOUR_FLOOR = 0x9fd48a;
export const GLYPH_COLOUR_COUNTER = 0xf0a060;
export const GLYPH_COLOUR_STAND = 0xd9d0bd;
const GLYPH_COLOUR_UNKNOWN = 0x9a9a9a;
const GLYPH_COLOURS: Record<string, number> = {
  seat: GLYPH_COLOUR_SEAT, bed: GLYPH_COLOUR_BED, floor: GLYPH_COLOUR_FLOOR,
  counter: GLYPH_COLOUR_COUNTER, stand: GLYPH_COLOUR_STAND,
};
/** Inner/outer radius of the ring (metres) — a foot's width, not a target. */
const RING_INNER_M = 0.25;
const RING_OUTER_M = 0.32;
/** Lift over the slot point so the ring never z-fights the floor it lies on
 *  (the depth test is off anyway — the lift keeps it on the right side of a
 *  floor plate whose surface IS the slot height). */
const RING_LIFT_M = 0.03;
/** Drawn after the scene's opaque and transparent passes: with the depth
 *  test off the ring shows through the chair it marks. */
const RING_RENDER_ORDER = 20;

export function glyphColour(group: string): number {
  return GLYPH_COLOURS[group] ?? GLYPH_COLOUR_UNKNOWN;
}

/** One ring per FREE slot of every offered place in `entries` (the room's
 *  markers), skipping the place `skipPlaceId` — the one the avatar itself
 *  holds; its rings would sit under the avatar's own feet. Every mesh carries
 *  `userData.placeId` for `hitPlace`. ONE geometry and one material per
 *  colour for the whole group — `disposeGlyphs` frees them once. */
export function buildGlyphs(entries: Map<string, PlaceEntry> | undefined, offers: PlaceOffer[],
                            skipPlaceId = ''): THREE.Group {
  const group = new THREE.Group();
  group.name = 'placeGlyphs';
  if (!entries) return group;
  const geometry = new THREE.RingGeometry(RING_INNER_M, RING_OUTER_M, 32);
  const materials = new Map<number, THREE.MeshBasicMaterial>();
  for (const offer of offers) {
    if (offer.id === skipPlaceId || offer.free <= 0) continue;
    const entry = entries.get(offer.id);
    if (!entry) continue;
    const colour = glyphColour(offer.group);
    let material = materials.get(colour);
    if (!material) {
      material = new THREE.MeshBasicMaterial({
        color: colour, transparent: true, opacity: 0.85,
        depthTest: false, depthWrite: false, side: THREE.DoubleSide,
      });
      materials.set(colour, material);
    }
    for (const i of offer.free_slots) {
      const p = entry.slots[i];
      if (!p) continue;    // the payload's capacity and the server's disagree: no ring
      const mesh = new THREE.Mesh(geometry, material);
      mesh.rotation.x = -Math.PI / 2;    // RingGeometry lies in XY — lay it flat
      mesh.position.set(p.x, p.y + RING_LIFT_M, p.z);
      mesh.renderOrder = RING_RENDER_ORDER;
      mesh.userData.placeId = offer.id;
      group.add(mesh);
    }
  }
  return group;
}

/** The place whose ring the ray hits first, or null. Rings only — figures
 *  are `NpcManager.characterAt`'s business and are asked first. */
export function hitPlace(group: THREE.Group, raycaster: THREE.Raycaster): string | null {
  for (const hit of raycaster.intersectObjects(group.children, false)) {
    const id = hit.object.userData.placeId;
    if (typeof id === 'string') return id;
  }
  return null;
}

/** Take the group out of the scene and free what `buildGlyphs` allocated —
 *  the shared geometry and materials once each. */
export function disposeGlyphs(group: THREE.Group): void {
  group.removeFromParent();
  const freed = new Set<THREE.BufferGeometry | THREE.Material>();
  for (const child of group.children) {
    if (!(child instanceof THREE.Mesh)) continue;
    for (const res of [child.geometry as THREE.BufferGeometry, child.material as THREE.Material]) {
      if (freed.has(res)) continue;
      freed.add(res);
      res.dispose();
    }
  }
  group.clear();
}
