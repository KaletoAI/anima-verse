/**
 * PLACE GLYPHS (plan-posen-plaetze.md § 4, Task 13): a flat ring on every
 * FREE slot of the avatar's room, so the player sees where the avatar can
 * sit down and can click it. Pure view: which slots are free is the
 * server's word (`GET /play/places`, `free_slots`), the slot points are the
 * tile's own place inventory (`tile.roomMarkers`, world metres), and the
 * group only picks the colour. Rebuilt on every worldmap poll — occupancy
 * changes under the player — and the old group is disposed each time.
 *
 * RINGS ARE FOR PLACES WITHOUT A PROP (ruling 2026-08-28). Where a place sits
 * on a piece of furniture, the FURNITURE is the target: it is what the player
 * looks at, it brightens under the pointer (`highlightProp`) and a click on
 * its mesh opens the same seat menu (`pickableProps` + `hitProp` here,
 * `pickablePlaceFor` in `game/placement.ts`). A ring in front of the bench
 * only competed with it.
 *
 * AND A ROOM DIORAMA IS SUCH A TARGET TOO (plan-diorama-hover.md, user
 * decision 2026-08-29). Furniture inside a diorama has no placement of its
 * own — the whole room is ONE mesh — so those places used to be the "no mesh"
 * case. They are not: the diorama takes the click and lights up in a radius
 * around the hovered slot (`scene/spotHighlight.ts`, uniforms, never a
 * material clone). What keeps its ring is a place with NO mesh at all: a spot
 * on the floor, a window sill, and every diorama place whose room has not
 * loaded its interior yet.
 */
import * as THREE from 'three';
import type { PlaceOffer } from '../api';
import type { PlacePick } from '../game/placement';
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
 *  markers) that has NO PROP under it, skipping the place `skipPlaceId` — the
 *  one the avatar itself holds; its rings would sit under the avatar's own
 *  feet. A place ON a prop (`entry.fixed`, i.e. the payload's
 *  `source: "prop"`) is drawn by nothing here: its mesh is the target, see
 *  the header.
 *
 *  THE FALLBACK: a prop marker WITHOUT an `anchor` keeps its ring. That is a
 *  payload from before the anchor field (a scene a client cached across the
 *  change) — `pickableProps` cannot find its mesh, so taking the ring away
 *  too would leave the place with no target at all. A place one cannot click
 *  is worse than a ring in front of a bench.
 *
 *  AND THE SAME FOR A DIORAMA (plan-diorama-hover.md): a place whose room is
 *  a diorama (`entry.diorama`) has its target in that ONE room mesh, so it
 *  drops its ring — but only while the mesh actually stands. `dioramaRooms`
 *  is the caller's list of rooms whose diorama is MOUNTED; a room missing
 *  from it has no interior loaded yet, and its places keep their rings for
 *  the same reason the anchor-less prop marker does.
 *
 *  Every mesh carries `userData.placeId` for `hitPlace`. ONE geometry and one
 *  material per colour for the whole group — `disposeGlyphs` frees them
 *  once. */
export function buildGlyphs(entries: Map<string, PlaceEntry> | undefined, offers: PlaceOffer[],
                            skipPlaceId = '',
                            dioramaRooms: ReadonlySet<string> = new Set()): THREE.Group {
  const group = new THREE.Group();
  group.name = 'placeGlyphs';
  if (!entries) return group;
  const geometry = new THREE.RingGeometry(RING_INNER_M, RING_OUTER_M, 32);
  const materials = new Map<number, THREE.MeshBasicMaterial>();
  for (const offer of offers) {
    if (offer.id === skipPlaceId || offer.free <= 0) continue;
    const entry = entries.get(offer.id);
    if (!entry) continue;
    if (entry.fixed && entry.anchor) continue;               // its prop is the target
    if (entry.diorama && dioramaRooms.has(entry.roomId)) continue;   // its room is
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
  // NOTHING TO DRAW is now the normal case in a furnished room — every place
  // of it sits on a prop. `disposeGlyphs` frees what it finds under the
  // CHILDREN, so a geometry allocated for nobody would never be reached.
  if (!group.children.length) {
    geometry.dispose();
    for (const material of materials.values()) material.dispose();
  }
  return group;
}

/** What a placement is to a place: `prop` = a piece of furniture with a
 *  placement of its own, `room` = the room's DIORAMA, one mesh for everything
 *  standing in it. The two differ in how they find their places and in how
 *  they light up — see `pickableProps` and `scene/spotHighlight.ts`. */
export type PlaceTargetRole = 'prop' | 'room';

/** A placed mesh together with the places its markers offer — what a click
 *  and a hover pick from. `places` is never empty (a target without a free
 *  slot is not pickable at all). */
export interface PickableProp {
  role: PlaceTargetRole;
  object: THREE.Object3D;
  places: PlacePick[];
}

/** The facts `pickableProps` needs about a mounted placement, so this module
 *  stays clear of `scene/tiles`: what it is, which room it stands in, where
 *  in it, and what was drawn there. `anchor` is the payload's own
 *  `models[].anchor`, tile-local — the link a PROP's markers name
 *  (`PlaceEntry.anchor`) and unread for a diorama; `object` is null while the
 *  mesh has not loaded, and a placement without a mesh is nothing to click. */
export interface PlacedPropRef {
  role: PlaceTargetRole;
  roomId: string;
  anchor: [number, number];
  object: THREE.Object3D | null;
}

/**
 * WHICH MOUNTED PROPS TAKE A SEAT CLICK (ruling 2026-08-28) — every placement
 * that carries at least one place with a FREE slot.
 *
 * The link is the ROOM plus the placement ANCHOR: `models[].anchor` and the
 * prop marker's `anchor` are the same two numbers out of the same recipe
 * placement, rounded once by the server, so they compare exactly;
 * `models[].id` could not do the job, being the PROP id that every copy of a
 * bench shares. The room is in the key because an anchor is only unique
 * WITHIN one room — it is a metre point in the room's own frame, so a bench
 * standing in the same corner of two rooms carries the same pair, and anchor
 * alone would cross-link the two. A room marker carries no anchor and is
 * never matched.
 *
 * A DIORAMA (`role: 'room'`) matches differently, and has to
 * (plan-diorama-hover.md): the furniture inside it has no placement, so its
 * places carry no anchor to compare — every place of the SAME ROOM that the
 * payload marked `diorama` belongs to it. That is also why the two roles
 * partition the room's places instead of competing for them: a place is
 * either on a prop (anchor) or on the diorama (`diorama`), never both.
 *
 * `offers` is the server's word on occupancy (`GET /play/places`) and decides
 * both which places count and WHICH slots of them are free — the same data
 * the rings used to read, so a prop offers exactly what a ring would have.
 */
export function pickableProps(props: PlacedPropRef[],
                              entries: Map<string, PlaceEntry> | undefined,
                              offers: PlaceOffer[]): PickableProp[] {
  const out: PickableProp[] = [];
  if (!entries) return out;
  const free = new Map<string, number[]>();
  for (const offer of offers) {
    if (offer.free > 0 && offer.free_slots.length) free.set(offer.id, offer.free_slots);
  }
  if (!free.size) return out;
  for (const prop of props) {
    if (!prop.object) continue;
    const places: PlacePick[] = [];
    for (const [id, entry] of entries) {
      if (entry.roomId !== prop.roomId) continue;
      if (prop.role === 'room') {
        if (!entry.diorama) continue;
      } else {
        if (!entry.anchor) continue;
        if (entry.anchor[0] !== prop.anchor[0] || entry.anchor[1] !== prop.anchor[1]) continue;
      }
      const slots = free.get(id);
      if (!slots) continue;
      // The payload's capacity and the server's may disagree for one poll —
      // an index without a slot point is simply not offered (`buildGlyphs`
      // draws no ring for it either).
      const points = slots.map((i) => entry.slots[i]).filter((p) => !!p)
        .map((p) => ({ x: p.x, z: p.z }));
      if (points.length) places.push({ id, free: points });
    }
    if (places.length) out.push({ role: prop.role, object: prop.object, places });
  }
  return out;
}

/** The pickable prop the ray hits first with the world point it hit, or null.
 *  Asked AFTER the figures (`NpcManager.characterAt`) and BEFORE the ground,
 *  for the click as for the hover — one order, one answer. */
export function hitProp(props: PickableProp[], raycaster: THREE.Raycaster):
    { prop: PickableProp; point: THREE.Vector3 } | null {
  if (!props.length) return null;
  const byRoot = new Map<THREE.Object3D, PickableProp>();
  for (const p of props) byRoot.set(p.object, p);
  const hits = raycaster.intersectObjects([...byRoot.keys()], true);
  for (const hit of hits) {
    for (let o: THREE.Object3D | null = hit.object; o; o = o.parent) {
      const prop = byRoot.get(o);
      if (prop) return { prop, point: hit.point };
    }
  }
  return null;
}

/** How much emissive a hovered prop gains. A flat colour, not a factor: the
 *  point is that the piece of furniture under the pointer reads as "this one"
 *  against its neighbours, and a factor would leave an already dark prop dark. */
export const HOVER_EMISSIVE = 0x6a6555;

/** What a hover took off a prop, so leaving it can put it back exactly:
 *  one entry per mesh with the material (or material list) it wore. */
export interface PropHighlight {
  object: THREE.Object3D;
  worn: { mesh: THREE.Mesh; material: THREE.Material | THREE.Material[] }[];
  clones: THREE.Material[];
}

/**
 * BRIGHTEN THE PROP UNDER THE POINTER — on CLONES, never on the material the
 * object wears.
 *
 * The prop loader hands every copy of a prop ONE cached group, so the
 * materials on a mounted placement are shared with every other copy of the
 * same bench in the world (that is exactly why `applySlotMaterials` clones
 * per placement). Writing `emissive` onto them would light up every bench in
 * the location, and a missed restore would leave them lit for good. So the
 * hover swaps in clones and `clearPropHighlight` swaps the originals back and
 * disposes them — a hover transition happens at human speed, a handful of
 * clones per transition is nothing.
 *
 * A material without an `emissive` channel (a basic/line material) is left
 * alone rather than replaced by something that has one: the cursor already
 * says the prop is clickable.
 */
export function highlightProp(object: THREE.Object3D): PropHighlight {
  const h: PropHighlight = { object, worn: [], clones: [] };
  object.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh || !mesh.material) return;
    const worn = mesh.material;
    const list = Array.isArray(worn) ? worn : [worn];
    let touched = false;
    const lit = list.map((m) => {
      if (!('emissive' in m)) return m;
      const clone = m.clone() as THREE.MeshStandardMaterial;
      clone.emissive = new THREE.Color(HOVER_EMISSIVE);
      clone.emissiveIntensity = 1;
      h.clones.push(clone);
      touched = true;
      return clone as THREE.Material;
    });
    if (!touched) return;
    h.worn.push({ mesh, material: worn });
    mesh.material = Array.isArray(worn) ? lit : lit[0];
  });
  return h;
}

/** Put the prop's own materials back and free the clones the hover made. */
export function clearPropHighlight(h: PropHighlight): void {
  for (const entry of h.worn) entry.mesh.material = entry.material;
  for (const clone of h.clones) clone.dispose();
  h.worn.length = 0;
  h.clones.length = 0;
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
