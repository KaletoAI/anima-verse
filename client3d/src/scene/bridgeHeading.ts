/**
 * THE HEADING OF A BRIDGE CLIP'S PELVIS, frame by frame — pure arithmetic, no
 * three.js, so `client3d/scripts/smoke_bridge_heading.mjs` checks it by hand.
 * TS-only (no Python twin): the importer knows nothing of it.
 *
 * Why (Task C2 of plan-bruecken-feinschliff): a HOLDING bridge can turn the
 * whole body — `get-up-bed` swings the figure ~105° round while it sits up on
 * the bed's edge. That turn lives in the clip's hips track, so the clip after
 * the bridge (idle, hips facing the figure root's forward again) swung the
 * body back by the same angle the moment it faded in. `footLockMeasure`
 * measures the turn with `headingTrack` on each rig, takes it out of the hips
 * track and stores it on the clip (`bridgeTravel.setClipRootTurn`); `Figure`
 * turns its root by it while the bridge plays and keeps the end turn.
 *
 * WHICH way the pelvis faces: the vector from the RIGHT UpLeg to the LEFT one
 * (the hips' cross axis), projected onto the ground and turned by −90° into
 * the forward direction. Not the hips bone's own twist about the world's Y:
 * mid-turn that disagrees with the legs by up to 15° and depends on the rig's
 * bone axes; the two UpLeg joints are the same two points on every rig.
 *
 * Frame: the clip frame (+Z forward, +X the figure's LEFT); a yaw f means
 * forward (sin f, cos f), as in `bridgeTravel.toWorld` and three.js
 * `rotation.y`. With L = left − right, heading = atan2(L.x, L.z) − π/2.
 */
import type { Vec3 } from './footLock';

/** Least share of the cross vector that must lie in the ground plane for a
 *  frame to have a heading at all. A pelvis rolled onto its side (lying on
 *  the back or side, the cross vector near vertical) says nothing about
 *  which way the body faces; such a frame keeps the last valid heading. */
export const HEADING_MIN_HORIZONTAL = 0.5;

/** An angle wrapped into (−π, π]. */
function wrapAngle(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

/**
 * The pelvis heading per frame (radians), RELATIVE to frame 0 and unwrapped
 * (a turn through ±180° goes on to −190°, never jumps to +170°).
 * `leftUpLeg[f]` / `rightUpLeg[f]` are the two joints' positions in frame f,
 * in any one unit and a frame whose Y is up. A frame whose cross vector is
 * less than `HEADING_MIN_HORIZONTAL` horizontal keeps the previous value;
 * frames before the first valid one take the first valid value (so they are
 * 0). A take without any valid frame is all 0.
 */
export function headingTrack(leftUpLeg: readonly Vec3[], rightUpLeg: readonly Vec3[]): Float32Array {
  const n = Math.min(leftUpLeg.length, rightUpLeg.length);
  const out = new Float32Array(n);
  let prev: number | null = null;
  let acc = 0;
  for (let f = 0; f < n; f++) {
    const l = leftUpLeg[f];
    const r = rightUpLeg[f];
    const x = l[0] - r[0];
    const y = l[1] - r[1];
    const z = l[2] - r[2];
    const flat = Math.hypot(x, z);
    const len = Math.hypot(x, y, z);
    if (len > 0 && flat / len >= HEADING_MIN_HORIZONTAL) {
      const h = Math.atan2(x, z) - Math.PI / 2;
      if (prev !== null) acc += wrapAngle(h - prev);
      prev = h;
    }
    out[f] = acc;
  }
  return out;
}
