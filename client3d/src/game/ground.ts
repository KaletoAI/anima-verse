/**
 * Which ray hit on a location's server model counts as WALKABLE GROUND
 * (finding B8). Pure arithmetic, no imports — the raycast itself stays in
 * `scene/tiles.ts` (`tileGroundY`), only the accept rule lives here so it can
 * be checked by hand in `client3d/scripts/smoke_walk_math.mjs`.
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
 */

/** Clearance over a building's walkable surface that still counts as ground,
 *  in metres. Above it starts the roof / the next storey. */
export const ROOF_CLEARANCE_M = 1.2;

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

/**
 * How far the footprint PLATE is lifted over the tile floor at a point — the
 * drawn mirror of `standY`, and derived from it so the two cannot drift.
 *
 * THE PLATE ONLY EVER RISES. `standY` lets the tile answer win where the
 * landscape runs BELOW the footprint, so a plate that followed the world down
 * would sink away under a figure standing at the tile height — the same hole
 * as finding 4, only mirrored (review 2026-08-13, I1). Downhill the lift is
 * therefore 0: the plate stays the tile floor the figure stands on, and the
 * landscape passes underneath it.
 *
 * `worldY` is the world ground at the point, `tileY` the height the tile group
 * already stands on (`footprintCentre`) — only the DIFFERENCE belongs on a
 * vertex, or the plate would climb the hill twice.
 */
export function plateLift(worldY: number, tileY: number): number {
  return standY(tileY, worldY) - (Number.isFinite(tileY) ? tileY : 0);
}

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
 *  - `worldHeight` is the authored WORLD relief (§ A16, `sampleWorldHeight` —
 *    the bilinear reading, the server's own). It is under EVERYTHING, inside a
 *    location as much as out in the wilderness. Until task 4 the client's
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
 * Under a footprint that levels its ground (`level_ground`, § A16.1, opt-in)
 * the world term is FLAT by construction, so this adds the plateau height and
 * not a second slope under the scene. Under an unflagged place the authored
 * landscape simply runs on underneath; the sum is the same one either way,
 * which is why the opt-in changes nothing about this rule.
 */
export function groundLift(worldHeight: number,
                           patches: readonly ScenePatch[]): number {
  let best: ScenePatch | null = null;
  for (const p of patches) {
    if (!best || p.area < best.area) best = p;
  }
  return worldHeight + (best ? best.lift : 0);
}
