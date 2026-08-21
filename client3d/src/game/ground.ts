/**
 * Which surface a figure stands on inside a location — the FLOOR OF THE
 * RECIPE (`recipeFloorAt`) and, where the mesh is the ground, which ray hit
 * counts (finding B8). Pure arithmetic; the only import is the equally pure
 * polygon test. The lookups — the raycast, the tile's plate list — stay in
 * `scene/tiles.ts` (`tileGroundY`), only the RULES live here so they can be
 * checked by hand in `client3d/scripts/smoke_walk_math.mjs`.
 *
 * The rule follows the PAYLOAD, not a constant. A building model
 * (`display: "shell"`) is a house: its mesh carries a bit of ground skin
 * around the entrance, and everything well above that skin is roof — a figure
 * must never be put on it. An AREA model (`display: "ground"` /
 * `"shell_area"`, i.e. `map3d.area_model`) is the opposite: the model IS the
 * ground of the location, shore, slope and lake bed included, so its surface
 * is walkable at ANY height. The Mondscheinsee mesh spans y −0.80 … +2.69 m;
 * with a flat 1.2 m cap every hit on the raised shore was rejected and the
 * figure fell back to the tile floor at 0 (the user's B8 symptom: correct on
 * the water, level 0 on the bank).
 *
 * Where the ceiling applies (buildings), it is measured from the model's OWN
 * declared walkable height `walk_y_world` (§ B, `_building_model`) and not
 * from world zero — a building sitting on an offset still gets the same
 * clearance over its entrance skin. Only a building whose spec declares no
 * walk height falls back to the bare 1.2 m the client used before.
 *
 * AND ABOVE BOTH stands a ROOM's own declaration (`declaredFloorAt`, § B
 * addendum part C, 2026-08-20): where a diorama spec carries a
 * `walk_y_world`, that is the floor of that room — before the plate, before
 * the mesh, in every display mode. It is the same number the walkability
 * sampling takes as its floor target, which is what keeps a figure and the
 * NPC spots of its room on ONE surface.
 */

import { pointInPolygon, polygonArea, type Polygon } from './polygon';

/** Clearance over a building's walkable surface that still counts as ground,
 *  in metres. Above it starts the roof / the next storey. */
export const ROOF_CLEARANCE_M = 1.2;

/** How far a figure's feet stand ABOVE the surface they were measured on, in
 *  metres — the hair that keeps a sole out of the floor it stands on.
 *
 *  It is the server's own `PROP_CLEARANCE` (`app/core/scene_recipe.py`): a
 *  prop's `bottom_y` is `plate top + 0.01`, so a figure standing on the same
 *  plate and a chair standing on it are at the SAME height by construction.
 *  Both the recipe-floor answer and the mesh-ray answer of `tileWalkY` add it,
 *  which is what makes the two paths comparable at all. */
export const WALK_CLEARANCE_M = 0.01;

/** One floor plate of the scene recipe, as the walk rule reads it: its
 *  outline in TILE-LOCAL metres and its `top_y`. Level plate and room plate
 *  alike — which of them wins is the rule below, not the caller's business. */
export interface WalkPlate {
  top: number;
  outline: readonly (readonly [number, number])[];
}

/**
 * THE FLOOR OF THE RECIPE under a tile-local point, or `null` where the
 * payload draws none (decision 2026-08-20, § B1/B2 addendum).
 *
 * The highest plate whose hull contains the point and whose top is still
 * BELOW the walk ceiling — the same ceiling the mesh hits are judged by
 * (`walkCeiling`), because this answers the same question a top-down ray
 * does: the highest surface that is not already the next storey. So a
 * ground-floor point answers the ground-floor plate, a room plate (0.10)
 * beats the level plate (0.08) it lies on, and the first storey's 2.90 is
 * out of reach at a ceiling of 1.28.
 *
 * WHY THE PLATE AND NOT THE MESH: a building model is the PICTURE of a
 * house, and where its floor sits inside the mesh is a modelling accident —
 * "Haus von Kai" carries a 0.240 m terrain pad under its walls, so the ray
 * answered 0.000 while the room plate lay at 0.100 and the figure walked
 * 9 cm below the furniture standing in the same room (measured, § B5a). The
 * plate is what the payload draws AND what it stands the props on
 * (`bottom_y = top + PROP_CLEARANCE`), so standing a figure on it makes
 * figure and chair one height by construction.
 */
export function recipeFloorAt(plates: readonly WalkPlate[] | null | undefined,
                              lx: number, lz: number,
                              ceiling: number): number | null {
  let best: number | null = null;
  for (const plate of plates ?? []) {
    if (!(plate.top < ceiling)) continue;
    if (best !== null && plate.top <= best) continue;
    if (pointInPolygon(lx, lz, plate.outline as Polygon)) best = plate.top;
  }
  return best;
}

/**
 * A room's DECLARED walking floor: the `walk_y_world` of its diorama spec
 * plus the hull it is declared inside, both in TILE-LOCAL metres.
 *
 * The same shape as a plate on purpose — it answers the same question — but
 * it is a different KIND of answer and therefore a different list: a plate is
 * DRAWN geometry the rule may outrank, a declaration is the admin's word and
 * outranks everything (§ B6 no. 7, "walk_y is a statement, never a
 * measurement").
 */
export interface DeclaredFloor extends WalkPlate {
  /** The room that declared it — the key a tier swap replaces its entry by. */
  roomId: string;
}

/**
 * THE DECLARED floor under a tile-local point, or `null` when no room
 * declares one there (user finding 2026-08-20: Mondhütte).
 *
 * A declared `walk_y` beats the height heuristic in `sampleRoomWalkables`
 * since the dial exists — but the WALKING figure never asked it: `tileWalkY`
 * knew the drawn plates and the mesh ray and nothing else, so the dial moved
 * the NPC spots and the room centre while the figure kept standing on the
 * plate (or, in an area location without a mesh, on the bare tile floor).
 * Two floors in one room, which is exactly what the one-datum law of
 * 2026-08-20 forbids. This is the missing half of that law: ONE lookup, asked
 * FIRST, by every consumer of the walking height.
 *
 * It applies whatever the location's `display` is. A declaration is not a
 * property of the surrounding mesh — it is a statement about the room's own
 * modelled floor (a podium, a sunken lounge, a hut standing in a lake), and a
 * hut does not stop having a floor because the place around it is an area.
 *
 * WHERE SEVERAL DECLARATIONS COVER THE POINT the smallest hull wins — the
 * innermost answer, the same most-specific-first tie-break the footprints use
 * (v6 no. 6, `polygonArea`) and `groundLift` repeats for scene reliefs. Rooms
 * are not supposed to overlap, but an always-visible outdoor zone spanning
 * half the location legally contains a hut standing in it.
 */
export function declaredFloorAt(floors: readonly WalkPlate[] | null | undefined,
                                lx: number, lz: number): number | null {
  let best: WalkPlate | null = null;
  let bestArea = -1;                       // < 0 = not measured yet
  for (const floor of floors ?? []) {
    if (!Number.isFinite(floor.top)) continue;
    // Containment FIRST, and the area only for the hulls that answer at all:
    // this runs per figure per frame, overlapping declarations are the rare
    // case, and the tie-break must not cost a shoelace pass over every room
    // hull of the location on every one of them. A hull of fewer than three
    // points contains nothing (`pointInPolygon`), so it never declares.
    if (!pointInPolygon(lx, lz, floor.outline as Polygon)) continue;
    if (!best) { best = floor; continue; }
    if (bestArea < 0) bestArea = polygonArea(best.outline as Polygon);
    const area = polygonArea(floor.outline as Polygon);
    if (area > 0 && (bestArea <= 0 || area < bestArea)) {
      best = floor;
      bestArea = area;
    }
  }
  return best ? best.top : null;
}

/** What the scene payload says about the location's own model. `display` is
 *  the spec word of § B6 no. 10, `walkY` its `walk_y_world`. */
export interface GroundModelInfo {
  display?: 'shell' | 'ground' | 'shell_area';
  /** Declared walkable height of the model in WORLD metres, if the spec
   *  carries one. */
  walkY?: number;
}

/** Highest world y a hit may have and still count as ground. `Infinity` for
 *  area models — they bring their own relief and nothing above them is roof. */
export function walkCeiling(info: GroundModelInfo | null | undefined): number {
  const display = info?.display ?? 'shell';
  if (display === 'ground' || display === 'shell_area') return Infinity;
  return plateCeiling(info);
}

/**
 * The ceiling that judges DRAWN PLATES — the storey question, never the mesh.
 *
 * For a building it IS `walkCeiling`: one clearance over the model's declared
 * standing height, so the storey above is out of reach. For an AREA location
 * the two part ways, and that is the point: `walkCeiling` is `Infinity` there
 * because a shore, a slope and a lake bed are all ground and no mesh HIT above
 * them is roof (finding B8) — but an area location's plates are still storeys,
 * and an uncapped plate pick would put a figure on a level-1 plate at 2.90 m
 * from the ground floor. The mesh keeps its exception, the plates do not.
 */
export function plateCeiling(info: GroundModelInfo | null | undefined): number {
  const walk = info?.walkY;
  const base = typeof walk === 'number' && Number.isFinite(walk) ? walk : 0;
  return base + ROOF_CLEARANCE_M;
}

/** Does this hit height count as walkable ground? Strictly below the ceiling,
 *  so the old `< 1.2` behaviour of a building without a declared walk height
 *  is unchanged.
 *
 *  `y` is measured FROM THE TILE, not from the world: `walk_y_world` is a
 *  scene metre and the tile stands on its plateau since E8 task 4, so the
 *  caller (`scene/tiles.tileGroundY`) subtracts the tile height before asking. */
export function acceptsWalkHit(info: GroundModelInfo | null | undefined,
                               y: number): boolean {
  return y < walkCeiling(info);
}

/**
 * WHERE A FIGURE STANDS when the tile and the world disagree — THE HIGHER ONE
 * WINS (user decision 2026-08-13, acceptance finding 4).
 *
 * A tile's walking height is a TILE answer: the plate it carries, the model
 * skin it rays, the scene relief on top — all measured from the location's own
 * centre. The WORLD relief (§ A16) runs on underneath a footprint that does not
 * level its ground (`level_ground` is opt-in), and until this rule the client
 * never asked it inside a footprint: the figure walked at plate height while
 * the landscape rose through the plate around it, and crossing the footprint
 * border it JUMPED, because a traveller outside was already sampled off the
 * world field.
 *
 * Under a levelling footprint this is inert by construction: the server
 * flattens the field there to exactly the plateau the tile stands on, so both
 * answers are the same number and the maximum is that number.
 *
 * The price is named in the spec (§ A16): a model that dips BELOW the world
 * ground — the lake bed of an area model, a sunken courtyard — is undercut by
 * the landscape, and that is an authoring matter, not a case for the renderer.
 *
 * NaN is not a height. A sampler that answers nonsense (no field yet, a broken
 * payload) must not put a figure at NaN, from which no frame ever recovers:
 * a non-finite TILE answer reads as the tile floor 0 (and the world may still
 * win over it — `standY(NaN, −0.8)` is 0, not −0.8), a non-finite WORLD answer
 * leaves the tile answer alone, and with both gone the figure stands on 0.
 */
export function standY(walkY: number, terrainY: number): number {
  const walk = Number.isFinite(walkY) ? walkY : 0;
  const terrain = Number.isFinite(terrainY) ? terrainY : walk;
  return Math.max(walk, terrain);
}

// `plateLift` stood here until 2026-08-21 ("Ein Boden" E3, plan § 3.1): the
// drawn mirror of `standY` that lifted every vertex of a tile's own footprint
// plate onto the world ground, clamped so the plate never sank below the floor
// the figure walked on. The tile draws no plate any more — the terrain IS the
// ground under a location — so the rule has nothing left to lift. `standY`
// itself stays: the figure still has to reconcile a tile answer (declared
// floor, scene plate, model skin) with the terrain under it.

/** One location's scene relief at the point being asked about: how LARGE its
 *  footprint is in m² and how high its own field lifts the ground there. Only
 *  locations that both CONTAIN the point and carry a field are handed in —
 *  the geometry is the caller's lookup, the rule is here. */
export interface ScenePatch { area: number; lift: number }

/**
 * The ground at a world point, in metres — THE client's mirror of the server's
 * `relief.ground_lift_at` (E8 task 4).
 *
 * TWO HEIGHT SOURCES, ONE ANSWER, and that is the whole rule:
 *
 *  - `worldHeight` is the authored WORLD relief (§ A16, `@anima/scene-render`
 *    `heightAt` — the bilinear reading of the data, and since "Ein Boden" E2
 *    the ONLY one the client has: the terrain's own vertices are placed from
 *    it, so the number this rule adds up is the number the picture is built
 *    from AND the number the server judges by). It is under EVERYTHING, inside
 *    a location as much as out in the wilderness. Until task 4 the client's
 *    mirror left this term out and knew only the scene relief, which is
 *    exactly the rubber band the acceptance list described: the figure walked
 *    up a world hill the client thought was flat and the server pulled it
 *    back three times a second.
 *  - a SCENE relief adds on top of it, and only the INNERMOST enclosing one
 *    that actually has a field counts (finding F3): a place carrying no relief
 *    of its own does not flatten the ground it stands on, it stands ON it. So
 *    the SMALLEST-AREA footprint among the patches wins (contract v6 Nr. 6),
 *    which is `tileAt`'s smallest-wins rule restricted to those that answer at
 *    all — the same order, now measured in m² rather than in edge length.
 *
 * Under a BUILT location the world term is FLAT by construction — the bake
 * stamps a plateau there (§ G5; since E1 that follows from the location
 * drawing a floor, there is no `level_ground` flag any more) — so this adds
 * the plateau height and not a second slope under the scene. Under a natural
 * place the authored landscape simply runs on underneath; the sum is the same
 * one either way, which is why the stamp changes nothing about this rule.
 */
export function groundLift(worldHeight: number,
                           patches: readonly ScenePatch[]): number {
  let best: ScenePatch | null = null;
  for (const p of patches) {
    if (!best || p.area < best.area) best = p;
  }
  return worldHeight + (best ? best.lift : 0);
}
