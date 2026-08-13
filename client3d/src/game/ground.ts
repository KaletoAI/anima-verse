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

/** One location's scene relief at the point being asked about: how WIDE its
 *  footprint is and how high its own field lifts the ground there. Only
 *  locations that both CONTAIN the point and carry a field are handed in —
 *  the geometry is the caller's lookup, the rule is here. */
export interface ScenePatch { width: number; lift: number }

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
 *    the narrowest footprint among the patches wins, which is `tileAt`'s
 *    smallest-wins rule restricted to those that answer at all.
 *
 * Inside a footprint the world term is FLAT by construction — the server
 * levels the heightfield under every place (the plateau pass) — so this adds
 * the plateau height, not a second slope under the scene.
 */
export function groundLift(worldHeight: number,
                           patches: readonly ScenePatch[]): number {
  let best: ScenePatch | null = null;
  for (const p of patches) {
    if (!best || p.width < best.width) best = p;
  }
  return worldHeight + (best ? best.lift : 0);
}
