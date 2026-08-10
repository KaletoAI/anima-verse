/**
 * The last of the grid world — a holding cell, not a module with a future.
 *
 * `CELL` and `gridToWorld` used to live in `scene/tiles.ts` and anchored the
 * whole client: a location WAS a 10 m cell. E4 task 3 replaced that with the
 * footprint of § A1.1 (centre `pos_x`/`pos_z`, edge `plan_width_m`, turned by
 * `yaw_deg`), so nothing that DRAWS the world speaks cells any more.
 *
 * ONE importer is left, and it belongs to the task after this one: the FOG
 * rectangles (`game/fog.ts` / `game/fogClouds.ts` and `rebuildFog` in
 * `main.ts`) — E4 task 6 turns them into metres, `world_bounds` minus the
 * known footprints. The step machine, the cell clamps and `scene/pathfind.ts`
 * went in task 5 (free walking over `POST /play/pos`).
 *
 * The fog block is DEAD ALREADY (the server stopped sending grid keys in E3,
 * so every cell it computes is derived from `undefined`); it is kept readable
 * until its own task rewrites it. Parking the constant here rather than
 * leaving it in `tiles.ts` is the point: an import from `game/gridLegacy` says
 * out loud that the reader is legacy, and when task 6 is done this file has no
 * importers and goes.
 *
 * TODO(E4 task 6): delete with the last importer.
 */

/** Edge length of the grid world's cell, in world metres. */
export const CELL = 10;
