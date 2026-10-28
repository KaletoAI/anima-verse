#!/usr/bin/env node
/**
 * E7-T1 standalone shared vectors, no live tables, renderer, assets or network.
 * Usage: node client3d/scripts/smoke_embody_vectors.mjs
 *
 * embody.json has ONE canonical source: this smoke. The collected hand tables
 * below come from smoke_offer_resolve, smoke_place_lift and smoke_pos_echo.
 * Numeric label index:
 * [30] nearestOffer: compare finite nonnegative distances, ties talk, elevator,
 *      stairs, enter. 2.4 loses to 1; .5 beats 1.4; 1.2 loses to .4 but beats
 *      1.4. Singletons including zero win; null, negative, NaN and Infinity
 *      cannot win. The source smoke retains the real range-rule integration.
 * [31] Place pick: bench slots x=0,.6; stool x=2. Hits .2 -> bench, 1.9 ->
 *      stool, 1.3 -> tie at .7 and first wins. Hit (.6,.5) -> bench at .5.
 *      Empty free slots never win. Radius .6 includes -.6, excludes -.7 and
 *      (.4,.5) whose hypot=.6403124; Infinity restores ungated selection.
 * [32] Driver: PLAYER adopts J1; missing route arrives; J2 replaces J1.
 *      Input reserves seq 5 and remembers J1; echo 4 is old, 5 acknowledges;
 *      replacement J2 wins before echo 5. Refusal 6 restores SERVER and clears
 *      cancellation; refusal 4 is ignored. PLAYER does not re-adopt J1.
 *      Legacy null is a journey key, distinct from the $NO_CANCEL adapter token.
 * [33] Suppression: CANCELLING hides its own journey (including legacy null);
 *      PLAYER hides remembered non-null J1 forever, but allows legacy null.
 *      SERVER with no remembered cancellation suppresses nothing.
 * [34] Answers: PLAYER owns seq>=floor; SERVER owns none; CANCELLING requires
 *      seq>=its reserved number AND >=floor. Thus 7 fails floor 8; 8 passes.
 * [35] SEND [1,2,3] owns 2 in session-a, not 9, another session or no origin.
 *      SEND 1..65 at cap64 evicts only 1, retaining the explicit list 2..65.
 *      Custom cap2 retains [2,3]. ECHO_RING_CAP=64. This is not a poll cache.
 * [36] Readiness starts empty (approachPin/pendingSnap=null). No place or a
 *      ready place returns false without calls. Unready a pins (a,approach),
 *      then ready a releases it. a->b releases a before pinning b; leaving
 *      releases b. Repeated holds pin again; clear releases only approach.
 * [37] Only an avatar with a nonempty location waits, until resident ring=near
 *      AND ready=true. Missing, far-ready and near-incomplete residents wait.
 * [38] keyForScene=!typing&&!overlayOpen. Esc priority: ignore if keys belong
 *      to HUD, else elevator, else menu, else mode. The table enumerates all
 *      16 typing/overlay/menu/elevator combinations, including both blockers.
 *
 * Collected original hand derivations (historical prop-pick examples are test
 * geometry only; native E7 consumes room markers and dioramas):

 * Smoke: WHICH standing offer the F key answers — `game/offers.nearestOffer`.
 *
 * Usage: direct node call, self-bundling via esbuild (run from anywhere):
 *     node scripts/smoke_offer_resolve.mjs
 *
 * WHY THIS CHECK EXISTS. Four rules offer the avatar something at the same
 * moment, with reaches of DIFFERENT size: talking reaches TALK_RANGE 2.5 m, a
 * stair landing STAIR_RANGE 1.5 m, a lift pad ELEVATOR_RANGE 1.5 m, a location
 * entry ENTER_RADIUS 3 m. F used to walk a fixed chain (talk → lift → stairs →
 * entry) and stop at the first offer standing, so anybody in the same room
 * within 2.5 m took the key away from a staircase the avatar was standing
 * right at — the reported bug. The rule is the MEASURED DISTANCE now, and this
 * file pins it with numbers derived by hand from that geometry, never from the
 * function's own output.
 *
 * The candidates of cases (1), (2) and (7) are produced by the REAL rules
 * (`talkTargetNear`, `stairsAt`, `elevatorAt`), not written down: whether an
 * offer stands at all is their business, and case (7) is precisely the
 * statement that an out-of-reach candidate never reaches the resolution.
 *
 * THE LAYOUT, once, in world metres (scale 1 throughout, i.e. one world metre
 * is one figure metre — § B, k = 1):
 *
 *   - the avatar stands at the ORIGIN (0, 0), location 'L', outdoors (no room)
 *   - NPC "npc-a" at (2.4, 0) → 2.4 m away, inside TALK_RANGE 2.5
 *   - NPC "npc-b"  at (0.5, 0) → 0.5 m
 *   - NPC "npc-c" at (2.6, 0) → 2.6 m, OUTSIDE the talk range
 *   - flight FA: foot landing (1, 0, 0) on level 0, head landing (5, 3, 0) on
 *     level 1 → the foot landing is 1.0 m away, inside STAIR_RANGE 1.5
 *   - flight FB: foot landing (1.4, 0, 0) → 1.4 m away
 *   - flight FC: foot landing (1.6, 0, 0) → 1.6 m, OUTSIDE the stair range
 *   - lift stops at (1.2, 0) on both storeys, rooms 'hall' (level 0) and
 *     'attic' (level 1) → the pad is 1.2 m away, inside ELEVATOR_RANGE 1.5
 *   - lift stops at (1.5, 0) → EXACTLY the range, and the comparison is
 *     strict, so no offer
 *
 * All distances are plain hypotenuses along +x, so every expected number below
 * is the x coordinate itself.
 
 * Smoke check for the two PURE place helpers of the 3D client
 * (`client3d/src/game/placement.ts`): `markerLiftPoint` — WHERE a place
 * marker's storey-0 terrain lift is sampled — and `pickablePlaceFor` — WHICH
 * place a click on a prop mesh opens.
 *
 * Usage:  node client3d/scripts/smoke_place_lift.mjs
 *
 * Like `scripts/smoke_scene_recipe.py` and `smoke_walk_math.mjs`, every
 * expected number below is derived BY HAND from the contract (§ B5a), never
 * recorded from the current output.
 *
 * ==========================================================================
 * [1] markerLiftPoint — ONE PROP, ONE GROUND
 * ==========================================================================
 * The defect it closes (user finding 2026-08-28, the avatar sitting ~40 cm
 * too low on the "Stone bench" above the cliff): a prop stands on the ground
 * under ITS OWN ANCHOR (§ A16.9, `reliftPlacement` samples
 * `models[].anchor`), while the seat marks on it were lifted at the MARKER's
 * own point — the anchor plus the marker offset, decimetres away and, on a
 * slope, at a different height. The seat therefore floated over or sank into
 * the bench by exactly the relief between the two points.
 *
 * The rule: a marker of `source: "prop"` is sampled at its PLACEMENT'S
 * anchor, which the payload now names (`markers[].anchor`, the same `[u, v]`
 * the prop's own spec carries). A room marker has no placement and keeps its
 * own point.
 *
 * Fixture — a bench placed at tile-local (1.0, 2.0), its seat marker offset
 * 0.4 m along +x, i.e. `at_world` (1.4, 2.0), capacity 2 with slots 0.6 m
 * apart across the facing, so slot 0 sits at (1.1, 2.0) and slot 1 at
 * (1.7, 2.0).
 *
 *   markerLiftPoint(at (1.4, 2.0), anchor (1.0, 2.0))  -> (1.0, 2.0)
 *   markerLiftPoint(at (1.4, 2.0), null / undefined)   -> (1.4, 2.0)
 *   a non-finite anchor is NO anchor                   -> (1.4, 2.0)
 *
 * [1b] and what that is worth in metres. Ground `h(x, z) = x` (a 45° slope in
 * x — chosen so the sampled height IS the x coordinate and every number below
 * can be read off the fixture), datum = 0.25:
 *
 *   lift = h(x, z) − datum          (storeyGroundLift, § A16.9, level 0)
 *
 *   at the ANCHOR      x = 1.0 -> 1.00 − 0.25 = 0.75   <- the one right answer
 *   at `at_world`      x = 1.4 -> 1.40 − 0.25 = 1.15   <- the old MOUNT
 *   at slot 0          x = 1.1 -> 1.10 − 0.25 = 0.85   <- the old RE-LIFT
 *
 * Two facts in those three numbers: the seat used to be lifted 0.40 m too
 * high (1.15 vs 0.75), and mount and re-lift disagreed with EACH OTHER by
 * 0.30 m on a bench of capacity > 1, because the mount sampled `at_world` and
 * `reliftScene` sampled `slots[0]`. With one lift point both are 0.75 and
 * `storeyGroundRelift(0.75, …)` moves the seat by delta 0.
 *
 * A DECLARED STOREY is not carried by the terrain at all (§ A16.9): the same
 * marker on level 1 lifts by 0 whatever the ground says.
 *
 * ==========================================================================
 * [2] pickablePlaceFor — the prop IS the click target
 * ==========================================================================
 * Since 2026-08-28 a prop whose markers offer a free slot takes the click
 * itself (rings are left to the places WITHOUT a prop). One prop may carry
 * several places, so the hit point decides: the place whose NEAREST FREE SLOT
 * is closest to it. Distances are plain XZ metres.
 *
 * Fixture — a bench "b1/seat1" with free slots at (0, 0) and (0.6, 0), and a
 * stool "b1/seat2" with one free slot at (2, 0), in that list order.
 *
 *   hit (0.2, 0)  bench min(0.2, 0.4) = 0.2 | stool 1.8   -> "b1/seat1"
 *   hit (1.9, 0)  bench min(1.9, 1.3) = 1.3 | stool 0.1   -> "b1/seat2"
 *   hit (1.3, 0)  bench min(1.3, 0.7) = 0.7 | stool 0.7   -> TIE, and a tie
 *                 falls to the FIRST entry of the list    -> "b1/seat1"
 *                 (this is why the pick needs an epsilon: in binary floats
 *                 (0.6 − 1.3)² = 0.49000000000000010214 and (2 − 1.3)² =
 *                 0.48999999999999993561, so a strict `<` would hand a
 *                 MATHEMATICAL tie to the second entry on noise alone)
 *   hit (0.6, 0.5)  bench min(hypot(0.6, 0.5) = 0.78102496759…,
 *                             0.5) = 0.5
 *                 | stool hypot(1.4, 0.5) = 1.48660687473… -> "b1/seat1"
 *                 (z counts — a hit is a point on the mesh, not an x)
 *   a place with no free slot never wins, and a list in which nobody has one
 *   answers null (total, never a throw — same contract as `slotFor`).
 *
 * ==========================================================================
 * [3] …and the RADIUS GATE a diorama needs (plan-diorama-hover.md)
 * ==========================================================================
 * A room diorama is ONE mesh for the whole room, so every click inside the
 * room hits it — without a gate the nearest seat anywhere in the room would
 * answer, and clicking the floor two metres away would seat the avatar. The
 * optional third argument is that gate: the winner counts only if its nearest
 * free slot lies within `maxDistM` metres of the hit point.
 *
 * `PLACE_PICK_RADIUS_M = 0.6` — the same 0.6 m the spot light fades out over
 * (`spotHighlight.ts`), so what the player sees lit is exactly what the click
 * takes. Measured against ONE place with ONE free slot at the origin, so the
 * hit coordinate IS the distance:
 *
 *   hit (0.4, 0)   -> the place   (0.4 <= 0.6)
 *   hit (-0.6, 0)  -> the place   (ON the radius still counts: the gate
 *                                  squares the same number on both sides, so
 *                                  the comparison is exact)
 *   hit (-0.7, 0)  -> null        (0.7 > 0.6, the click falls through to the
 *                                  ground, as it does today when no place
 *                                  answers)
 *   hit (0.4, 0.5) -> null        (hypot = 0.64031242… > 0.6 — the gate is XZ
 *                                  distance, not an x distance)
 *
 * The gate never changes WHICH place wins — only whether one does at all
 * (shown on the two-place bench fixture above); and WITHOUT the argument the
 * pick is exactly as before (prop targets pass none).
 
 * Driver hand derivation: J1 is adopted, absence arrives, J2 replaces J1.
 * Input reserves 5: origin 4 cannot acknowledge it, 5 can; J2 wins over 5.
 * Refusal 6 retries 5, while 4 cannot decide it. Null differs from NO_CANCEL.
 * Floor 8 excludes 7 forever, and accepts 8.
 * Integration oracle: report 7 in flight -> server drive sets floor 8.
 * Arrival cannot make answer 7 valid again (ok, throttled, 409, or network).
 * A cancel reserves 8 while 7 is in flight; only 7 is in the sent ring until
 * its answer settles. Replacement drops reserved 8 rather than cancelling J2.
 * Usage: node client3d/scripts/smoke_pos_echo.mjs
 * Hand derivation: sent [1,2,3] includes 2, not 9; another session or null
 * origin is foreign. Sending 1..65 to a 64-entry ring evicts only 1, leaving
 * 2..65 (64 numbers). A view switch must publish its revision before fetching;
 * every poll during the switch is discarded, including polls of the new view.
 * Token bytes 0..15 encode as 00,01,...,09,0a,...,0f: exactly 32 hex chars.
 * The HTTP crypto fixture exposes getRandomValues only, as on a LAN origin.
 
 */
import assert from 'node:assert/strict';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { embodyDispatch } from './embodyVectorDispatch.mjs';
let passed = 0, failed = 0;
for (const name of ['walk_control', 'collide', 'enter', 'embody', 'camera']) {
  const result = runVectors(loadVectors(name), embodyDispatch);
  passed += result.passed; failed += result.failed;
  console.log(`${name}: ${result.passed} passed, ${result.failed} failed`);
}
assert.equal(failed, 0, 'all E7 shared vectors');
console.log(`E7 vectors: ${passed} passed, ${failed} failed`);
