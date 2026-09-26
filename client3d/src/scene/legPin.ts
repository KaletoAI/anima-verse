/**
 * LEG PIN — the pure maths that nails a planted foot to its spot per rig.
 *
 * The client-side counterpart of the importer's foot plant
 * (`app/blender/scripts/_foot_plant.py`, used by `cmu_clip._plant_feet` /
 * `_pin_feet`): the importer bends the legs of the REFERENCE rig so a planted
 * foot stands still on its floor, but a figure with other leg proportions only
 * takes over the rotations, so its feet slide again. `footLockMeasure` runs the
 * same two steps once per model on its own skeleton and bakes them into the
 * adapted clip; this module is the arithmetic, shared cases with the importer:
 *
 * - `twoBoneIk` is the twin of `_foot_plant.two_bone_ik` — same inputs, same
 *   rule, same cases ([P2]/[P3] of `scripts/smoke_foot_plant_math.py`, repeated
 *   verbatim in `client3d/scripts/smoke_leg_pin.mjs`).
 * - `soleDown` is the twin of `_foot_plant.sole_down` ([P8] there, repeated
 *   in the smoke): only a foot standing on its sole is pinned.
 * - `pinRuns` is the run rule of `_foot_plant.foot_planted_frames` (only a
 *   contact with PIN_MIN_S of full weight in one piece counts) with the same
 *   fade over PIN_FADE_S and the same exemption at the take's first and last
 *   frame ([P1]/[P1b] there). It starts from per-frame contact weights that are
 *   already ORed over the foot's points; the detection itself is the client's
 *   (`footLock.contactWeights` on the rig), not the importer's source bands.
 *
 * Pure: no three, no DOM. Quaternions are (w, x, y, z) like the importer's.
 */
import { FULL } from './footLock';
import type { Vec3 } from './footLock';

export type { Vec3 };
/** Unit quaternion (w, x, y, z). */
export type Quat = [number, number, number, number];

/** Shortest contact that is pinned, s (`_foot_plant.PLANT_MIN_S`). */
export const PIN_MIN_S = 0.2;
/** Fade-in/out of a pinned contact's weight, s (`_foot_plant.PLANT_FADE_S`). */
export const PIN_FADE_S = 0.1;

/** Share of the rest foot's ankle-over-ball rise a foot must keep to count
 *  as standing on its sole (`_foot_plant.SOLE_MIN_FRACTION`). */
export const SOLE_MIN_FRACTION = 0.5;

const IDENTITY: Quat = [1, 0, 0, 0];

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 =>
  [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a: Vec3): number => Math.sqrt(dot(a, a));
const unit = (a: Vec3): Vec3 => {
  const n = len(a);
  return n > 1e-12 ? scale(a, 1 / n) : [0, 0, 0];
};

/** `v` turned by the unit quaternion `q` (`_foot_plant._qrot`). */
export function qrot(q: Quat, v: Vec3): Vec3 {
  const [w, x, y, z] = q;
  const qv: Vec3 = [x, y, z];
  const t = scale(cross(qv, v), 2);
  return add(add(v, scale(t, w)), cross(qv, t));
}

/** Shortest rotation taking direction `a` onto direction `b`
 *  (`_foot_plant.rotation_between`). */
export function rotationBetween(a: Vec3, b: Vec3): Quat {
  const ua = unit(a);
  const ub = unit(b);
  const c = dot(ua, ub);
  if (c < -1 + 1e-12) {                   // opposite: 180° about any normal
    let axis = cross(ua, [1, 0, 0]);
    if (len(axis) < 1e-6) axis = cross(ua, [0, 1, 0]);
    axis = unit(axis);
    return [0, axis[0], axis[1], axis[2]];
  }
  const x = cross(ua, ub);
  const q: Quat = [1 + c, x[0], x[1], x[2]];
  const n = Math.hypot(q[0], q[1], q[2], q[3]);
  return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
}

/**
 * World-space rotation deltas `{ upper, lower }` that bend or stretch the
 * chain hip→knee→ankle so the ankle reaches `target` — the twin of
 * `_foot_plant.two_bone_ik`.
 *
 * `upper` turns the thigh about the hip; `lower` turns the shin — already
 * carried along by `upper` — about the new knee. Both segment lengths stay.
 * The knee stays in the plane of the hip→target line and `pole` (the current
 * knee: its own bending plane), on the pole's side. A target out of reach
 * stretches the leg along the hip→target line as far as it goes (never NaN);
 * one closer than |l1 − l2| folds it as far as it goes. A pole on the
 * hip→target line has no side; the plane then falls back to one through the
 * world X axis (Z when the line is X). Degenerate input (a zero-length
 * segment, the target on the hip) answers two identities.
 */
export function twoBoneIk(hip: Vec3, knee: Vec3, ankle: Vec3, target: Vec3,
                          pole: Vec3): { upper: Quat; lower: Quat } {
  const l1 = len(sub(knee, hip));
  const l2 = len(sub(ankle, knee));
  const toT = sub(target, hip);
  let d = len(toT);
  if (l1 < 1e-9 || l2 < 1e-9 || d < 1e-9) return { upper: IDENTITY, lower: IDENTITY };
  const t = scale(toT, 1 / d);
  d = Math.min(Math.max(d, Math.abs(l1 - l2) + 1e-9), l1 + l2);
  const p = sub(pole, hip);
  let u = sub(p, scale(t, dot(p, t)));
  if (len(u) < 1e-9) {
    u = cross(t, [1, 0, 0]);
    if (len(u) < 1e-6) u = cross(t, [0, 0, 1]);
  }
  u = unit(u);
  const cosA = Math.max(-1, Math.min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)));
  const sinA = Math.sqrt(Math.max(0, 1 - cosA * cosA));
  const newKnee = add(hip, add(scale(t, l1 * cosA), scale(u, l1 * sinA)));
  const reach = add(hip, scale(t, d));
  const upper = rotationBetween(sub(knee, hip), sub(newKnee, hip));
  const shin = qrot(upper, sub(ankle, knee));
  const lower = rotationBetween(shin, sub(reach, newKnee));
  return { upper, lower };
}

/** Longest stretch of full-weight frames inside [a, b]
 *  (`_foot_plant._longest_full`). */
function longestFull(w: readonly number[], a: number, b: number): number {
  let best = 0;
  let cur = 0;
  for (let g = a; g <= b; g++) {
    cur = w[g] >= FULL ? cur + 1 : 0;
    best = Math.max(best, cur);
  }
  return best;
}

/**
 * The pin weight 0..1 per frame from a foot's contact weights `w` (per frame,
 * already the larger of its points') — the run rule and fade of
 * `_foot_plant.foot_planted_frames`.
 *
 * A run of frames with a weight > 0 is pinned only when it holds full weight
 * (≥ FULL) for PIN_MIN_S in one piece — a shorter touch is a step, not a
 * stand. A kept run keeps its weights, faded in and out over PIN_FADE_S:
 * `w'(f) = w(f) · min(1, (f − a + 1)/(F + 1), (b − f + 1)/(F + 1))` for the
 * run [a, b], F = round(PIN_FADE_S · fps) — except on a side where the run
 * touches the take's first or last frame: the take's start is no touchdown,
 * and its last frame is the pose a bridge clip holds, so it keeps the full
 * correction. Every other frame weighs 0.
 */
export function pinRuns(w: readonly number[], fps: number): number[] {
  const n = w.length;
  const out = new Array<number>(n).fill(0);
  const fade = Math.round(PIN_FADE_S * fps);
  let f = 0;
  while (f < n) {
    if (!(w[f] > 0)) { f++; continue; }
    const a = f;
    while (f + 1 < n && w[f + 1] > 0) f++;
    const b = f;
    f++;
    if (longestFull(w, a, b) / fps < PIN_MIN_S - 1e-9) continue;
    for (let g = a; g <= b; g++) {
      const fadeIn = a === 0 ? 1 : (g - a + 1) / (fade + 1);
      const fadeOut = b === n - 1 ? 1 : (b - g + 1) / (fade + 1);
      out[g] = w[g] * Math.min(1, fadeIn, fadeOut);
    }
  }
  return out;
}

/**
 * Per frame: does the foot stand on its SOLE — its ankle above its ball by
 * at least SOLE_MIN_FRACTION of `restRise` (the ankle's height over the ball
 * in the rig's rest pose; a rise ≤ 0 gives threshold 0)? The twin of
 * `_foot_plant.sole_down`: the lift compares a point with the upright stance,
 * which means nothing for a foot on its side (ankle ≈ ball height — the lift
 * could go negative and RAISE it), on its instep or on its heel. Non-finite
 * heights answer false.
 */
export function soleDown(ankleHeights: readonly number[], ballHeights: readonly number[],
                         restRise: number): boolean[] {
  const need = SOLE_MIN_FRACTION * Math.max(restRise, 0);
  return ankleHeights.map((a, f) => {
    const b = ballHeights[f];
    return Number.isFinite(a) && Number.isFinite(b) && a - b >= need;
  });
}
