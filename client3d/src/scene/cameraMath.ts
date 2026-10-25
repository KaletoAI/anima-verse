/**
 * The OVERVIEW camera's arithmetic — pure numbers, no `three`, no DOM, so the
 * browser smoke (`client3d/scripts/smoke_camera_math.mjs`) and the native
 * client's C# tests check the same rules against the same hand-derived cases
 * (`shared/test-vectors/camera.json`).
 *
 * The engine (`scene/engine.ts`) owns the camera and its input events; this
 * module owns what those events DO to the numbers: the wheel's zoom factor and
 * its limits, the pull towards the cursor, the per-frame easing, the fly-to
 * curve, the orbit drag, the pitch limits and where the lens ends up. The
 * boot framing of the world (`worldCentreXZ`, `fitDistance`) lives here too,
 * because it is the same lens arithmetic seen from the other end.
 *
 * `basePitchDeg` stays in `cameraFraming.ts` (it is shared with the embodied
 * framing); the vectors cover it all the same.
 *
 * Vectors are plain tuples (`[x, y, z]`, `[x, z]`), never `THREE.Vector3`, so
 * the C# port reads the cases as they stand.
 */
import { MAX_DIST, MIN_DIST } from './cameraFraming';

export type Vec3 = [number, number, number];

/** The rectangle the server places the world in (`world_bounds`), in metres. */
export interface BoundsXZ {
  min_x: number;
  max_x: number;
  min_z: number;
  max_z: number;
}

/** The three.js clamp, `max(lo, min(hi, v))` — the same order, so a `lo`
 *  above `hi` answers `lo` exactly as `THREE.MathUtils.clamp` does. */
function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** `THREE.MathUtils.DEG2RAD`, spelled the same way so `deg * DEG2RAD` gives
 *  the bit-identical radians `degToRad` gave before this module existed. */
const DEG2RAD = Math.PI / 180;

// --- Framing the world (§ A12, E4 task 3) -----------------------------------
//
// The map camera is an orbit camera with a 45° VERTICAL field of view
// (`engine.ts`), so a sphere of radius R fits the picture at
//
//     d = R / sin(22.5°) = 2.6131 · R
//
// and the fit below is exactly that, over the bounding sphere of
// `world_bounds` — the simplest framing that can be checked by hand. It is
// deliberately GENEROUS: the camera looks down at an angle, so the ground it
// actually covers is wider than the sphere test assumes, and the horizontal
// field is wider still on a landscape window.

/** Half the vertical field of view of the map camera, in radians. */
export const CAMERA_HALF_FOV = (22.5 * Math.PI) / 180;
/** Air around the bounds, as a factor on the fitted radius. 15 % keeps the
 *  outermost footprint off the edge of the picture. */
export const CAMERA_FIT_MARGIN = 1.15;
/** Fit distance for a world with nothing placed: the old boot default, so an
 *  empty world looks exactly as it always did. */
export const CAMERA_FIT_EMPTY = 70;

/** Centre of `world_bounds` on the ground plane, or the world origin when
 *  nothing is placed. The HEIGHT there is the caller's (§ A16): the camera
 *  looks at a point of the world, and in a world whose middle is a hilltop the
 *  y = 0 plane lies inside the hill — `main.ts` samples the terrain at this
 *  point. */
export function worldCentreXZ(b: BoundsXZ | null | undefined): [number, number] {
  const x = b ? (b.min_x + b.max_x) / 2 : 0;
  const z = b ? (b.min_z + b.max_z) / 2 : 0;
  return [x, z];
}

/** Camera distance at which `world_bounds` fits the picture, clamped to what
 *  the camera can actually be set to: the engine snaps anything below
 *  `MIN_DIST` on its first update anyway, and handing it a smaller number
 *  would mean the boot distance and the camera's distance disagree from frame
 *  one — a tiny world (a single 4 m location) is exactly that case. A world
 *  too large for `MAX_DIST` simply starts as far out as the camera can go. */
export function fitDistance(b: BoundsXZ | null | undefined): number {
  if (!b) return CAMERA_FIT_EMPTY;
  const r = Math.hypot(b.max_x - b.min_x, b.max_z - b.min_z) / 2;
  if (!Number.isFinite(r) || r <= 0) return CAMERA_FIT_EMPTY;
  return clamp((r * CAMERA_FIT_MARGIN) / Math.sin(CAMERA_HALF_FOV), MIN_DIST, MAX_DIST);
}

// --- Zoom --------------------------------------------------------------------

/** Wheel sensitivity: one wheel notch (deltaY ≈ 100 on most mice) scales the
 *  distance by e^0.12 ≈ 1.1275 — exponential, so every notch is the same
 *  RATIO at any distance. */
export const WHEEL_ZOOM_RATE = 0.0012;

/** The zoom factor of one wheel event. */
export function wheelFactor(deltaY: number): number {
  return Math.exp(deltaY * WHEEL_ZOOM_RATE);
}

/** The highest distance the USER may zoom to: the mode's `cap`, never beyond
 *  `MAX_DIST`, and never below the floor (a cap under the floor pins the zoom
 *  to the floor rather than inverting the range). `floor` is the already
 *  effective floor of `zoomFloorOf`. */
export function zoomCeiling(floor: number, cap: number | null): number {
  return Math.max(floor, cap === null ? MAX_DIST : Math.min(cap, MAX_DIST));
}

/** The lowest distance the camera may be set to: the mode's `floor`, never
 *  below `MIN_DIST`. */
export function zoomFloorOf(floor: number | null): number {
  return floor === null ? MIN_DIST : Math.max(floor, MIN_DIST);
}

/** A wanted distance clamped into [floor, ceiling]. `null` = the engine's own
 *  `MIN_DIST` / `MAX_DIST`. A `flyTo` passes `cap = null`: the cap binds the
 *  user's wheel and keys, not a deliberate camera move of the app. */
export function clampZoom(dist: number, floor: number | null, cap: number | null): number {
  const lo = zoomFloorOf(floor);
  return clamp(dist, lo, zoomCeiling(lo, cap));
}

/** The distance one wheel event asks for: `targetDist · e^(deltaY · 0.0012)`,
 *  clamped by `clampZoom`. */
export function wheelZoom(targetDist: number, deltaY: number,
                          floor: number | null, cap: number | null): number {
  return clampZoom(targetDist * wheelFactor(deltaY), floor, cap);
}

/**
 * Zooming IN pulls the aim point towards the ground point under the cursor,
 * by exactly the fraction of the distance that was just given up
 * (`1 − newDist / oldDist`), so the point under the cursor stays roughly under
 * it. `hit` is that point on the y = 0 plane (`[x, z]`; its height is 0, and
 * the target's height is pulled towards 0 by the same fraction). Zooming out,
 * standing still or a miss (`hit` null) leaves the target where it is.
 * `oldDist` is a clamped distance and therefore ≥ MIN_DIST > 0.
 */
export function zoomTowardCursor(target: Vec3, hit: [number, number] | null,
                                 oldDist: number, newDist: number): Vec3 {
  if (!hit || !(newDist < oldDist)) return [target[0], target[1], target[2]];
  const k = 1 - newDist / oldDist;
  return [
    target[0] + (hit[0] - target[0]) * k,
    target[1] + (0 - target[1]) * k,
    target[2] + (hit[1] - target[2]) * k,
  ];
}

// --- Easing ------------------------------------------------------------------

/** The longest frame step the camera eases over, in seconds: a stalled tab
 *  must not jump the camera on its first frame back. */
export const MAX_FRAME_DT = 0.1;

/** The per-frame share of the remaining gap that `dist`, `yaw` and the view
 *  shift close: `1 − e^(−8·dt)`, frame-rate independent (two frames of dt/2
 *  close the same gap as one of dt). */
export function damp(dt: number): number {
  return 1 - Math.exp(-8 * Math.min(dt, MAX_FRAME_DT));
}

/** How fast a `flyTo` runs through its curve, in units per second: the whole
 *  flight takes 1 / 1.6 = 0.625 s. */
export const FLY_RATE = 1.6;

/** The fly parameter after a frame of `dt` seconds, stopping at 1. */
export function flyAdvance(t: number, dt: number): number {
  return Math.min(1, t + dt * FLY_RATE);
}

/** The fly-to curve: smoothstep `3t² − 2t³`, flat at both ends. */
export function flyEase(t: number): number {
  return t * t * (3 - 2 * t);
}

// --- Orbit and pose ------------------------------------------------------------

/** Radians of yaw per pixel of horizontal drag. */
export const ORBIT_YAW_PER_PX = 0.005;
/** Degrees of free pitch per pixel of vertical drag. */
export const ORBIT_PITCH_DEG_PER_PX = 0.25;
/** How far the free pitch may leave the base curve, in degrees. In first
 *  person the view may look almost straight up and down instead. */
export const PITCH_OFFSET_LIMIT_DEG = 35;
export const FIRST_PERSON_PITCH_OFFSET_LIMIT_DEG = 85;

/** One orbit drag of `dx`/`dy` pixels: dragging right turns the camera left
 *  around its target (yaw falls), dragging down tilts it steeper. */
export function orbitStep(targetYaw: number, pitchOffset: number, dx: number, dy: number,
                          firstPerson = false): { targetYaw: number; pitchOffset: number } {
  const limit = firstPerson ? FIRST_PERSON_PITCH_OFFSET_LIMIT_DEG : PITCH_OFFSET_LIMIT_DEG;
  return {
    targetYaw: targetYaw - dx * ORBIT_YAW_PER_PX,
    pitchOffset: clamp(pitchOffset + dy * ORBIT_PITCH_DEG_PER_PX, -limit, limit),
  };
}

/** The pitch the camera is drawn at, in degrees: base curve plus free pitch,
 *  held between 8° (never flat onto the ground) and 85° (never straight down,
 *  where the yaw would lose its meaning). In first person the lower limit is
 *  −85°: the view may look up. */
export function clampPitchDeg(deg: number, firstPerson = false): number {
  return clamp(deg, firstPerson ? -85 : 8, 85);
}

/** The unit vector from the target to the lens for an orbit at `yaw`
 *  (radians, 0 = the camera on +Z looking −Z) and `pitchDeg` above the
 *  horizon. Written into `out` so the frame loop allocates nothing. */
export function orbitOffset(yaw: number, pitchDeg: number, out: Vec3 = [0, 0, 0]): Vec3 {
  const p = pitchDeg * DEG2RAD;
  out[0] = Math.sin(yaw) * Math.cos(p);
  out[1] = Math.sin(p);
  out[2] = Math.cos(yaw) * Math.cos(p);
  return out;
}

/** Where the lens stands: `target + orbitOffset(yaw, pitchDeg) · dist`; it
 *  then looks at `target`. */
export function cameraPose(target: Vec3, dist: number, yaw: number,
                           pitchDeg: number): { pos: Vec3 } {
  const o = orbitOffset(yaw, pitchDeg);
  return { pos: [target[0] + o[0] * dist, target[1] + o[1] * dist, target[2] + o[2] * dist] };
}
