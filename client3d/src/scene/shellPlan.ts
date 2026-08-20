/**
 * WHERE A LOCATION'S FAR-VIEW SHAPE COMES FROM — the decision alone, without a
 * single mesh.
 *
 * Until 2026-08-19 a building without a server model wore a procedural hut
 * (`tiles.ts → makeTree`/shell). That was struck: a place must not show a shape
 * nobody authored. What was left over, though, was a place with NO shape at all
 * — the socle plate and a floating label, and the walls appeared only once the
 * player entered it (user finding 2026-08-20). The room layout is not "no
 * shape": the scene recipe delivers the outline as finished § B primitives, and
 * those are the very walls the place really has.
 *
 * So there are three sources of a far view and this file says which one applies:
 *
 *   'model'    the payload carries a building model — it IS the far view, and
 *              the recipe shell would stand inside it
 *   'recipe'   no model, but plates/walls exist: the § B primitives stand in
 *              for it (level plates + contour/room walls, openings included
 *              because the walls arrive already split around them). ROOFLESS —
 *              a roof is a primitive family the payload does not have yet, and
 *              an invented one would be exactly the procedural hut again
 *   'ground'   an area location (forest, lake, village, a detail scene): its
 *              far view is the drawn ground, never walls
 *   'none'     nothing to build a shape from
 *
 * PURE AND IMPORT-FREE, like `game/walk.ts` and `scatterLod.ts`: it is a
 * decision over booleans and counts, and that is what lets
 * `client3d/scripts/smoke_far_shell.mjs` check every case by hand.
 */

/** What the far view of a location is built from — see the file header. */
export type FarShellSource = 'model' | 'recipe' | 'ground' | 'none';

/** Everything the decision needs, all of it read straight off the payload and
 *  the tile — no meshes, no camera, no view state. */
export interface FarShellFacts {
  /** `tile.isBuilding` — a built place rather than a passable/template one. */
  isBuilding: boolean;
  /** `tile.natureSite` — a named piece of nature (wood, lake, meadow, road). */
  natureSite: boolean;
  /** `scene.area_detail` — the location is a composed AREA detail scene. */
  areaDetail: boolean;
  /** the payload carries a `role: 'building'` model spec */
  hasBuildingModel: boolean;
  /** `scene.plates.length` and `scene.walls.length` */
  plates: number;
  walls: number;
}

/**
 * Which source the far view of this location has.
 *
 * THE MODEL WINS OVER EVERYTHING, including over an area location: a payload
 * with a building spec is answered with `'model'` whatever else it says,
 * because whether that model is a shell, a ground or a detail area is the
 * SPEC's own business (`display`) and is decided where it is placed
 * (`applySceneBuilding`) — not here.
 *
 * An area location without a model shows its ground and no walls: its "rooms"
 * are zones like Road or Forest, and outlining them with walls would fence the
 * wood in. A building without a model falls to the recipe if it has any
 * primitives at all.
 */
export function farShellSource(facts: FarShellFacts): FarShellSource {
  if (facts.hasBuildingModel) return 'model';
  if (!facts.isBuilding || facts.natureSite || facts.areaDetail) return 'ground';
  const plates = Number(facts.plates);
  const walls = Number(facts.walls);
  const primitives = (Number.isFinite(plates) ? plates : 0)
    + (Number.isFinite(walls) ? walls : 0);
  return primitives > 0 ? 'recipe' : 'none';
}

/** Shorthand for the one caller that only wants the yes/no. */
export function wantsRecipeShell(facts: FarShellFacts): boolean {
  return farShellSource(facts) === 'recipe';
}
