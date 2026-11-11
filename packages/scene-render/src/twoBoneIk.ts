/**
 * twoBoneIk.ts — the two-bone leg IK and its vector/quaternion arithmetic,
 * pure (no three, no DOM), shared by both renderers.
 *
 * The TypeScript twin of the importer's `app/blender/scripts/_foot_plant.py`
 * (`two_bone_ik`, `rotation_between`, `_qrot`): same inputs, same rule, same
 * hand cases ([P2]/[P3] of `scripts/smoke_foot_plant_math.py`, repeated
 * verbatim in `client3d/scripts/smoke_leg_pin.mjs`). Change one side, change
 * the other and the fixture with it.
 *
 * Consumers: the 3D client's leg pin (`client3d/src/scene/legPin.ts`,
 * `footLockMeasure.ts`) and the shod foot plant of both renderers
 * (`footPlant.ts`). Moved here from `legPin.ts` (2026-11-11, footwear strand).
 *
 * Quaternions are (w, x, y, z) like the importer's; vectors are plain triples
 * in whatever unit the caller works in (the rule is unit-free).
 */
import type { Vec3 } from './footLock';

export type { Vec3 };
/** Unit quaternion (w, x, y, z). */
export type Quat = [number, number, number, number];

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

