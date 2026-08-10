/**
 * The last of the grid world — a holding cell, not a module with a future.
 *
 * `CELL` and `gridToWorld` used to live in `scene/tiles.ts` and anchored the
 * whole client: a location WAS a 10 m cell. E4 task 3 replaced that with the
 * footprint of § A1.1 (centre `pos_x`/`pos_z`, edge `plan_width_m`, turned by
 * `yaw_deg`), so nothing that DRAWS the world speaks cells any more.
 *
 * What still does is the machinery the later tasks of the same plan own:
 *  - the step machine, the cell clamps and the passability lookups in
 *    `main.ts` plus `scene/pathfind.ts` — E4 task 5 (free walking over
 *    `POST /play/pos`),
 *  - the fog rectangles in `game/fog.ts` / `game/fogClouds.ts` — E4 task 6
 *    (rectangles in metres, `world_bounds` minus the known footprints).
 *
 * Those blocks are DEAD ALREADY (the server stopped sending grid keys in E3,
 * so every cell they compute is derived from `undefined`); they are kept
 * readable until their own task rewrites them. Parking the constant here
 * rather than leaving it in `tiles.ts` is the point: an import from
 * `game/gridLegacy` says out loud that the reader is legacy, and when the two
 * tasks are done this file has no importers and goes.
 *
 * TODO(E4 tasks 5 + 6): delete with the last importer.
 */

/** Edge length of the grid world's cell, in world metres. */
export const CELL = 10;
