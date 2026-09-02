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

/** Closest the camera may get while embodied, in metres. The engine's own
 *  `MIN_DIST` is the lens; this is the rule of the game: aiming at the eyes
 *  means 0.8 m would put the camera inside the avatar's head. 2 m leaves it
 *  ~1.95 m behind and 0.34 m above the crown of a 1.70 m figure — the closest
 *  over-the-shoulder shot that still shows a head rather than a scalp. */
export const EMBODY_MIN_DIST = 2.0;

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
