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
 * geometry that both renderers would have to share.
 *
 * THE LEAF NODE (spec-picture-props.md § 6, D7). A door model that Blender
 * has split carries its leaf as its own glTF node `leaf`, and the payload
 * says where that node's box sits (`door.leaf_bbox`, raw y-up model metres).
 * Then ONLY the leaf swings, about a pivot the renderer hangs on the leaf's
 * hinge edge — `leafPivot` below is that one pure piece of arithmetic. (Not
 * the wall piece `leaf` of `walls[]`, the flat panel in a door hole; that is
 * a wall.)
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
 * How far the avatar is from THIS door, as the swing rule counts it: the plain
 * distance while the door is on the storey the AVATAR is on, and `Infinity` —
 * "nobody is standing in front of it" — while it is not.
 *
 * The storey has to be part of the answer because doors STACK: a front door
 * and the balcony door above it share their (x, z) to the millimetre, and a
 * plain 2D distance would swing both of them open at once.
 *
 * `avatarLevel` is the FIGURE'S storey — the one its room sits on — and never
 * the displayed one. `levelFilter` is the in-world storey BUTTON, i.e. what
 * the CAMERA shows, and the two come apart as a matter of course: the follow
 * is edge-triggered and the button deliberately holds the view. Gating on the
 * camera's storey would swing the door directly ABOVE the avatar open, with
 * nobody in front of it and the avatar itself hidden. The same distinction is
 * drawn for the wall clamp and for the room-change heuristic in `main.ts`.
 *
 * `Infinity` rather than "skip this door": a door left open on the floor one
 * has just left has to ease SHUT, not freeze at the angle it stood at.
 */
export function doorDistance(doorLevel: number, avatarLevel: number,
                             distM: number): number {
  return doorLevel === avatarLevel ? distM : Infinity;
}

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

/** `door.leaf_bbox` of the payload: the leaf node's box in RAW y-up model
 *  metres — the coordinates the node's own vertices are in, before the fit
 *  scaling `place()` puts on an ANCESTOR of that node. */
export interface LeafBox {
  min: [number, number, number];
  max: [number, number, number];
}

/**
 * The x of the leaf's hinge edge in model space — `bbox.min.x`, for BOTH
 * hinges (ruling R12, 2026-08-28).
 *
 * Why the hinge does not pick a side: `place()` seats every `fit` model on
 * its local −x edge (the group origin IS that edge), and the server's
 * `yaw_deg` turns a RIGHT-hinged door 180° about that very edge
 * (`_door_prop_models`: "+x onto the direction the leaf runs, away from its
 * hinge"). So in the model's own frame the hinge is the −x side whichever
 * way the door opens — a right-hinged door is the same model turned round,
 * not mirrored. `max.x` for a right hinge would swing the leaf about its
 * FREE edge, through the frame. `hinge` stays in the signature so a call
 * site reads its intent and so this stays the one place that states the
 * rule; it only ever feeds the SIGN of the swing (`doorTargetAngle`).
 */
export function leafPivotX(bbox: LeafBox, hinge: 'left' | 'right'): number {
  void hinge;
  return bbox.min[0];
}

/**
 * Where the pivot group goes, in the leaf node's PARENT frame (= model
 * space for every GLB Blender writes: `frame` and `leaf` are root nodes with
 * identity transforms): the hinge edge `leafPivotX`, the box's underside and
 * the middle of its thickness — a rotation about the local y axis through
 * that point turns the leaf on its hinge line.
 */
export function leafPivot(bbox: LeafBox, hinge: 'left' | 'right'
): { x: number; y: number; z: number } {
  return { x: leafPivotX(bbox, hinge), y: bbox.min[1],
           z: (bbox.min[2] + bbox.max[2]) / 2 };
}
