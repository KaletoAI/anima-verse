# door_swing

- Origin: the browser scene's deleted `smoke_door_swing.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/DoorSwingVectorTests.cs`
- Vectors: `shared/test-vectors/door_swing.json`

## Derivation

```text
/**
 * Smoke check for the DOOR SWING maths of the 3D client (v5 door props,
 * user decision 2026-08-27) — the browser scene's `doorSwing.ts`.
 *
 * Usage:  node the browser scene's deleted smoke_door_swing.mjs
 *
 * Like every other check here, each expected number below is derived BY HAND
 * from the contract (§ B5a: numbers, never a screenshot, and never a value
 * recorded from the current output).
 *
 * WHAT THE MODULE IS. A door prop is a `models[]` entry with `measure: "fit"`
 * whose placed group has its ORIGIN ON THE HINGE (spec addendum "Tür-Props +
 * Slots (v5)"), so "the door opens" is a rotation of that group about its own
 * y axis. WHEN it opens and HOW FAR is view state and lives per app; these two
 * pure functions are that rule, and `main.ts` does nothing but feed them the
 * distance and hang the result on `group.rotation.y`.
 *
 * THE CONSTANTS (user decision 2026-08-27):
 *   DOOR_OPEN_RANGE = 2.0 m   — "the avatar stands in front of it"
 *   DOOR_OPEN_DEG   = 85°     — how far a door swings open
 *   DOOR_SWING_RATE = 3.0 rad/s — how fast it gets there
 *
 * --- doorTargetAngle(distM, enterable, swing) -----------------------------
 * The open angle in RADIANS, signed by `swing` (+1 left hinge, −1 right):
 *
 *   open = 85 · π / 180 = 1.4835298641951802 rad
 *
 *   (1.9, true,  +1) ->  +1.4835298641951802   inside the range, open
 *   (2.1, true,  +1) ->   0                    outside it, shut
 *   (2.0, true,  +1) ->  +1.4835298641951802   the range is inclusive
 *   (1.9, false, +1) ->   0                    LOCKED stays shut, however
 *                                              close one stands (§ 3
 *                                              decision 2: a ban is visible)
 *   (1.9, true,  -1) ->  -1.4835298641951802   right hinge, other way round
 *   (2.1, false, -1) ->   0                    both reasons at once
 *
 * A non-finite distance (no avatar in the scene) is not "near": `NaN <= 2.0`
 * and `Infinity <= 2.0` are both false, so the door shuts.
 *
 * --- doorDistance(doorLevel, avatarLevel, distM) --------------------------
 * DOORS STACK. A front door and the balcony door above it share their (x, z)
 * to the millimetre, so a plain 2D distance opens both at once. The gate is
 * the storey the AVATAR is on (the storey of its room), never the displayed
 * one: `levelFilter` is the in-world storey BUTTON, and "avatar on storey 0,
 * view on storey 1" is an everyday state — gating on the camera would open
 * the door directly overhead with nobody in front of it.
 *
 *   (0, 0, 1.9) -> 1.9        same storey, the distance stands
 *   (1, 0, 0.1) -> Infinity   the door overhead, however close in plan
 *   (0, 1, 0.1) -> Infinity   ...and the one under one's feet
 *   (-1,-1, 0.4) -> 0.4       a basement door seen from the basement
 *
 * Fed onward, `Infinity` is exactly "nobody is in front of it", so
 *   doorTargetAngle(doorDistance(1, 0, 0.1), true, 1) = 0
 * while the same door on the avatar's own storey stands open. `Infinity`
 * rather than skipping the door: one left open on the floor one has just
 * ridden away from must ease SHUT, not freeze.
 *
 * --- easeAngle(current, target, dt, rate) ---------------------------------
 * One frame of the swing: at most `rate · dt` radians towards the target, and
 * never past it. At 60 fps and 3.0 rad/s one step is
 *
 *   3.0 / 60 = 0.05 rad
 *
 *   (0,     1.4835298641951802, 1/60, 3.0) -> 0.05
 *        the difference is 1.4835 > 0.05, so a full step: 0 + 0.05
 *   (1.4,   1.4835298641951802, 1/60, 3.0) -> 1.45
 *        difference 0.0835298641951802 > 0.05, another full step
 *   (1.45,  1.4835298641951802, 1/60, 3.0) -> 1.4835298641951802
 *        difference 0.0335298641951802 <= 0.05, so it CLAMPS at the target —
 *        no overshoot, and the door does not jitter around its end stop
 *   (0,    -1.4835298641951802, 1/60, 3.0) -> -0.05      symmetric
 *   (-1.45,-1.4835298641951802, 1/60, 3.0) -> -1.4835298641951802
 *   (1.2,   0,                  1/60, 3.0) -> 1.15       shutting again
 *   (x, x, …) -> x                                        already there
 *   (0.3,   1.4835298641951802, 0,    3.0) -> 0.3        a frame of no time
 *                                                        moves nothing
 *
 *   (0,    1, 1/60) -> 0.05     the rate defaults to DOOR_SWING_RATE 3.0
 *
 * --- the whole swing, frame by frame (60 fps) -----------------------------
 *   1.4835298641951802 / 0.05 = 29.67 → 30 frames from shut to fully open
 *   (standing 1.0 m away), and 30 frames back to shut from fully open when
 *   the avatar stands 3.0 m away.
 *
 * VECTORS: the cases above are in shared/test-vectors/door_swing.json (shared
 * with the native client's C# tests). JSON wrappers: a `null` distance
 * argument is Infinity and a returned Infinity is `null`;
 * `doorConstants()` = {range, openDeg, rate}; `doorSwingFrames(from, distM)`
 * counts 60-fps frames of easeAngle towards doorTargetAngle(distM, true, +1)
 * until the angle stands exactly on it (at most 100). NaN has no JSON
 * spelling, so that case stays inline below, as does the stacked-door chain.
 *
 * The LEAF PIVOT (where the leaf node turns, ruling R13) is NOT here: it is
 * `leafPivot` of @anima/scene-render, checked by scripts/smoke_leaf_pivot.mjs.
 */
```
