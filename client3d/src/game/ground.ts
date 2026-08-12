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
 *  is unchanged. */
export function acceptsWalkHit(info: GroundModelInfo | null | undefined,
                               y: number): boolean {
  return y < walkCeiling(info);
}
