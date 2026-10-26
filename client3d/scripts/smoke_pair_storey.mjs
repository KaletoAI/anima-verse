#!/usr/bin/env node
/**
 * Smoke check: a STANDING pair interaction (§ A8a, `anchor.place_id` null)
 * stays on the storey of its room — the upper floor, the cellar, a storey
 * corridor — instead of dropping onto the terrain under the building.
 *
 * Usage:  node client3d/scripts/smoke_pair_storey.mjs
 *         (needs three and esbuild; no clips, no models, no server)
 *
 * Hand-derived expectations
 * -------------------------
 * § A8a puts a pair figure at `anchor + R_y(yaw) · clipRoot(t)`; the clip
 * frame has its floor at y = 0, so the HEIGHT is the floor the pair stands
 * on. For a pair on a place it is the place's slot height (unchanged here);
 * a pair that met halfway stands on the floor of the ROOM both are in — the
 * same height every other figure the server put on a room point gets
 * (`roomFloorAt + WALK_CLEARANCE_M`, `WALK_CLEARANCE_M` = 0.01, else the
 * room's stand centre for a room without a floor of its own, § A13c).
 *
 * The tile below stands at centre y = 0 and has no baked surfaces, so a
 * room's floor is its DECLARED plate top (`tile.center.y + declared`):
 *
 *   [1] `roomStandY` per room (tile-local point (1, 2)):
 *       og      declared  3.20 → 3.20 + 0.01 =  3.21
 *       keller  declared −2.80 → −2.80 + 0.01 = −2.79
 *       flur    no floor entry, stand centre y 6.41 → 6.41
 *       nowhere neither                          → null
 *
 *   [2] `NpcManager.tick` with one NPC in a pair, the clip root held at
 *       (0.3, 0) in the clip frame, anchor (10, 22), yaw 0 →
 *       x = 10 + 0.3·cos 0 + 0·sin 0 = 10.3, z = 22 − 0.3·sin 0 + 0 = 22.
 *       The terrain stub answers 0.5 everywhere (the ground under the house).
 *       a) room `og` (stand sampler = `roomStandY` above)  → y =  3.21
 *       b) room `keller`                                    → y = −2.79
 *       c) the location's ground (sampler answers null)     → y =  0.5 (terrain)
 *       d) seated on a place, slot height 3.65              → y =  3.65
 *       Before the fix every case but d) came out at 0.5: the pair sat on the
 *       terrain, i.e. on the ground floor.
 *       Extra precedence cases: slot[0].y = 0 beats room 3.21 and slot[1]
 *       height 9; a named but missing place falls back to room 3.21.
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
const { passed, failed } = await runPairVectors('pair_height');
console.log(`\n${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
