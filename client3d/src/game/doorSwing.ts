/**
 * When a door prop stands open, and how far — the swing rule of the 3D client
 * (v5 door props, user decision 2026-08-27).
 *
 * Pure maths like `walk.ts`, `doors.ts` and `locks.ts`: no Three.js, no module
 * state, no DOM and no import at all, so `client3d/scripts/smoke_door_swing.mjs`
 * can transpile the file and check both functions against hand-derived numbers.
 *
 * WHY THIS IS THE CLIENT'S BUSINESS. The server states the door — the prop,
 * its opening, its hinge and the SIGN that opens it outward (`models[].door`,
 * spec addendum "Tür-Props + Slots (v5)") — and it states nothing about the
 * angle. It cannot: whether a door stands open depends on where THIS player's
 * avatar is standing at THIS millisecond, which is view state and belongs to
 * the app that draws it. Nothing here is ever persisted or sent back, and
 * the two renderers are free to answer it differently.
 *
 * THE GEOMETRY IS ALREADY DONE. `placeModelSpec` puts the placed group's
 * ORIGIN on the hinge edge (`measure: "fit"`, § B2), so opening the door is a
 * rotation of that group about its own y axis and nothing else — there is no
 * pivot to compute here and no geometry that both renderers would have to
 * share.
 *
 * A LOCKED DOOR STAYS SHUT. `enterable` is the server's verdict for the rooms
 * behind the threshold (`game/locks.doorwayLock`), and a door that swung open
 * in front of a ban would promise a way in that `/play/enter-room` refuses.
 * The threshold's red look says the same thing; this is that statement in the
 * third dimension.
 */

/** How close the avatar has to be to the threshold, in world metres, for the
 *  door to count as "somebody is standing in front of it". */
export const DOOR_OPEN_RANGE = 2.0;

/** How far a door swings open, in degrees. Not 90°: a leaf flat against the
 *  wall reads as a hole again, and 85° keeps it visibly a door. */
export const DOOR_OPEN_DEG = 85;

/** How fast it gets there, in radians per second — about half a second for the
 *  full 85°. */
export const DOOR_SWING_RATE = 3.0;

const OPEN_RAD = (DOOR_OPEN_DEG * Math.PI) / 180;

/**
 * The angle this door WANTS to stand at, in radians, signed by `swing`.
 *
 * `swing` is the payload's own sign for "a positive rotation about y opens
 * this door outward" (+1 for a left hinge, −1 for a right one), so the sign
 * question is answered by the server and never re-derived here.
 *
 * A non-finite distance — no avatar in the scene, no tile under it — is not
 * near: both `NaN <= r` and `Infinity <= r` are false, so the door shuts
 * without a guard of its own.
 */
export function doorTargetAngle(distM: number, enterable: boolean,
                                swing: 1 | -1): number {
  if (!enterable) return 0;
  return distM <= DOOR_OPEN_RANGE ? swing * OPEN_RAD : 0;
}

/**
 * One frame of the swing: at most `rate · dt` radians towards `target`, and
 * never past it.
 *
 * The clamp is what keeps a door still once it is open — a step that could
 * overshoot would leave the leaf jittering around its end stop every frame.
 */
export function easeAngle(current: number, target: number, dt: number,
                          rate: number = DOOR_SWING_RATE): number {
  const step = Math.max(0, rate) * Math.max(0, dt);
  const diff = target - current;
  if (Math.abs(diff) <= step) return target;
  return current + Math.sign(diff) * step;
}
