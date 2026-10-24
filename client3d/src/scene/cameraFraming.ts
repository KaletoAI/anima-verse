/**
 * The arithmetic of what the camera FRAMES — pure numbers, no `three`, no DOM,
 * so `scripts/smoke_embodied_camera.mjs` can check it without a GL context.
 *
 * The engine (`scene/engine.ts`) owns the camera; this module owns the two
 * decisions that say what ends up in the picture: how steeply the camera looks
 * down at a given distance, and WHICH POINT of a figure it aims at.
 *
 * The second one used to have no home at all: the embodied mode hung the
 * camera on the figure's ROOT, and a root sits at the feet. The aim point is
 * the centre of the picture at every distance, so zooming in walked the eye
 * down to the ankles — at 3 m the head was already out of the frame (the
 * 45° vertical FOV gives a half-frame of 22.5°, and the head stood 33.9°
 * above the centre). Aiming at the EYES instead is what makes a close view
 * read as the avatar's own look at the world.
 */

/** Closest the camera may get to its target. Derived from the smallest figure
 *  that has to be able to fill the frame: with the 45° vertical FOV a height h
 *  fills the picture at dist = h / (2·tan(22.5°)) ≈ 1.21·h. Indoors figures
 *  used to be drawn at scale ~0.3, so a 1.70 m character was ~0.5 m tall and
 *  filled the frame at ~0.61 m — 0.8 m keeps that reachable and still leaves a
 *  little air (visible height 2·0.8·tan(22.5°) ≈ 0.66 m, the figure covers
 *  ~76 % of it). The old 2.5 m could not do this: indoors it framed 2 m of
 *  empty room. */
export const MIN_DIST = 0.8;
/** Furthest the camera may get from its target. */
export const MAX_DIST = 150;

/** Pitch at the near end of the zoom, in degrees — the OVERVIEW value, where
 *  the close-up is an inspection of a thing on the ground and looking down at
 *  it is the point. */
export const OVERVIEW_NEAR_PITCH_DEG = 18;
/** Pitch at the far end of the zoom, in degrees: near enough top-down that a
 *  whole settlement reads as a map. Shared by both modes. */
export const FAR_PITCH_DEG = 62;

/** Pitch at the near end while EMBODIED. Flatter than the overview's 18°,
 *  because the close-up there is not an inspection but a look at where one is
 *  walking: at the embodied zoom floor it puts the horizon 12.8° above the
 *  centre of the picture — inside the 22.5° half-frame, so the world ahead of
 *  the avatar is actually in shot. At 18° it sits at 21.9°, on the very edge. */
export const EMBODY_NEAR_PITCH_DEG = 8;

/** Minimum requested zoom while embodied. Below the third-person stand-off,
 *  the zoom selects first person instead of pushing the lens into the head. */
export const EMBODY_MIN_DIST = MIN_DIST;
/** Keep the third-person lens outside the head until the delayed switch. */
export const THIRD_PERSON_MIN_DIST = 2;

/**
 * Perspective hysteresis in requested orbit metres. A 0.6 m band and 180 ms
 * of continuous input beyond a threshold reject small or fleeting wheel
 * reversals. Owned by the engine; no timers or per-frame allocations.
 */
export class FirstPersonZoom {
  active = false;
  private pendingSeconds = 0;

  update(distance: number, enabled: boolean, dt: number): boolean {
    if (!enabled) {
      this.active = false;
      this.pendingSeconds = 0;
      return false;
    }
    const switching = this.active ? distance >= 1.8 : distance <= 1.2;
    if (!switching) {
      this.pendingSeconds = 0;
      return this.active;
    }
    this.pendingSeconds += dt;
    if (this.pendingSeconds >= 0.18 - 1e-9) {
      this.active = !this.active;
      this.pendingSeconds = 0;
    }
    return this.active;
  }
}

/** Where the eyes sit, as a fraction of standing height. 0.94 is the
 *  anthropometric standard (eye height ≈ 0.936–0.94 of stature) and puts a
 *  1.70 m figure's eyes at 1.598 m. */
export const EYE_FRACTION = 0.94;

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

/**
 * How steeply the camera looks down at distance `dist`, in degrees, before the
 * player's own free pitch (`Engine.pitchOffset`) is added.
 *
 * `zoomK` is normalised against `MIN_DIST`, not against the mode's own floor,
 * so the curve is ONE curve: an embodied camera at 2 m and an overview camera
 * at 2 m sit at the same point of it and differ only by where it starts. The
 * square root spends most of the range near the ground, where the difference
 * between 18° and 26° is a different picture, and compresses the far end,
 * where everything is a map anyway.
 */
export function basePitchDeg(dist: number,
                             nearPitchDeg = OVERVIEW_NEAR_PITCH_DEG): number {
  const zoomK = clamp((dist - MIN_DIST) / (MAX_DIST - MIN_DIST), 0, 1);
  return nearPitchDeg + (FAR_PITCH_DEG - nearPitchDeg) * Math.sqrt(zoomK);
}

/** Eye height of a figure of `heightM` standing height, in metres — the offset
 *  from its root (the feet) to the point a camera should aim at. */
export function eyeHeight(heightM: number): number {
  return heightM * EYE_FRACTION;
}

/**
 * THE FIRST-PERSON LENS ON THE HEAD BONE. In first person the own body stays
 * drawn, so the lens has to sit where its eyes are in the CURRENT pose —
 * `eyeHeight` above the feet is a standing eye, and a seated avatar looked
 * down on its own lap from 1.60 m. The lens is therefore fixed to the head
 * bone, at an offset measured once in the rest pose:
 * - height: `EYE_HEAD_FRACTION` of the way from the head joint (the skull
 *   base on a Mixamo rig) to the crown end bone; without a crown bone the
 *   standing `eyeHeight`,
 * - forward: `EYE_FORWARD_FRACTION` of the standing height ahead of the head
 *   joint, along the figure's own +Z (glTF front) — 0.094 m on a 1.70 m figure,
 *   the distance from the neck axis to the eyes.
 */
export const EYE_HEAD_FRACTION = 0.45;
export const EYE_FORWARD_FRACTION = 0.055;

/** Rest-pose eye point of a figure, in its own frame (feet at y = 0, facing
 *  +Z): `head` is the head joint, `crown` the crown end bone or null. */
export function restEyePoint(head: [number, number, number],
                             crown: [number, number, number] | null,
                             heightM: number): [number, number, number] {
  const y = crown ? head[1] + (crown[1] - head[1]) * EYE_HEAD_FRACTION : eyeHeight(heightM);
  return [head[0], y, head[2] + heightM * EYE_FORWARD_FRACTION];
}

/** How far the view may turn from a STANDING body in first person before the
 *  body turns after it, in degrees. Inside it only the head looks around; past
 *  it the body turns to the view, so looking back never looks through one's
 *  own back. An animation (dancing, sitting, a bridge) is never turned: there
 *  only the view moves and the clip plays on. */
export const BODY_TURN_DEG = 60;

/** The facing yaw (three.js Y rotation, 0 = +Z, as `Figure.faceTowards`
 *  writes it) the camera looks along, for the engine's orbit yaw: the camera
 *  sits at `(sin yaw, ·, cos yaw)` from its target and looks back at it. */
export function viewHeading(cameraYaw: number): number {
  return Math.atan2(-Math.sin(cameraYaw), -Math.cos(cameraYaw));
}

/** The yaw a standing first-person body turns to, or null while the view is
 *  within `BODY_TURN_DEG` of it. Both yaws may be unwrapped. */
export function bodyYawForView(bodyYaw: number, viewYaw: number,
                               thresholdDeg = BODY_TURN_DEG): number | null {
  let d = (viewYaw - bodyYaw) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return Math.abs(d) > thresholdDeg * Math.PI / 180 ? viewYaw : null;
}
