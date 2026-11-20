/**
 * PAIR SCALE (owner decision 2026-11-20: "the alignment is per pair; it must be general") — how a pair/group clip
 * whose alignment was measured on two 1.70 m figures is placed for figures of their REAL heights.
 *
 * THE PROBLEM. A pair clip's alignment (partner shift, tilt/roll/yaw, root angle, renderer shift) is measured in the
 * Pose library's place preview, where every figure is scaled to `FIGURE_HEIGHT_M` = 1.70 m. In the game each figure
 * has its own height; its hips HEIGHT track is rescaled per rig, but the HORIZONTAL root path of its half (the hips XZ
 * of the clip in metres of the clip frame) is not. Two figures of 1.60 m and 1.85 m would stand exactly as far apart
 * as two 1.70 m figures, so a contact that is exact at 1.70 m misses by centimetres.
 *
 * THE RULE. Let a_i = h_i / 1.70 be figure i's scale (`pairFigureScale`). In the normalised clip at a frame, figure
 * i's root is p_i (clip frame, horizontal, relative to the place anchor) and a contact between figures A and B is the
 * point C = p_A + c_A = p_B + c_B, c_i the body-fixed offset of the contact point from the figure's root. A body-fixed
 * offset scales with the body (c_i → a_i·c_i), so placing every figure at
 *     p_i' = C + a_i·(p_i − C)                                                      (`scalePairRoot`)
 * keeps the contact exactly: p_A' + a_A·c_A = C + a_A·(p_A + c_A − C) = C = p_B' + a_B·c_B. Each figure's root
 * path is scaled by ITS OWN ratio about the clip's CONTACT PIVOT C. All a_i = 1 returns p_i itself (no arithmetic at
 * all, so today's placement is reproduced bit for bit); the Pose library preview always normalises to 1.70 m and
 * therefore never scales.
 *
 * THE PIVOT C (`pairPivotOf`), in the clip frame, horizontal [side (+X), forward (+Z)]:
 *   - a clip with a stored `pair_pivot_cm` (its `<kind>.json`, written by Auto-align's Save): that point. Auto-align
 *     measures it on the aligned pair at its DEEPEST key frame — the contact target's point (the channel opening or the
 *     point target) of the receiving figure, turned into the clip frame of the place anchor (`clipFramePivot`); a
 *     clip with several contact relations stores the mean of them (`pairPivotCm`), which keeps no single contact
 *     exact but splits the error. One point, not a per-frame track: during a stroke the receiving figure's opening is
 *     body-fixed and nearly still, and the entering figure's part slides THROUGH it — the moving contact point lies on
 *     the part (its body-fixed offset changes, which the rule allows), not in the clip frame.
 *   - a pair/group clip WITHOUT a stored pivot: the clip frame's origin (0, 0). By the clip-pair contract (§ A8a) the
 *     origin IS the centroid of the roles' roots at the anchor frame (the closest approach; for a pair the midpoint of
 *     the two roots), so every pair clip is scaled — the ones without a pivot about the midpoint of the pair.
 *
 * THE VERTICAL. Figures stand on their ground/surface and their hips height already scales per rig, so only the
 * HORIZONTAL components scale about C. The vertical mismatch of two bodies of different size cannot be removed by
 * placement: a contact at height d above the floor in the 1.70 m clip sits at a_A·d on A and a_B·d on B, a residual of
 * (a_B − a_A)·d. For 1.60 m and 1.85 m (a = 0.941176 / 1.088235, Δa = 0.147059) on a standing clip with the contact at
 * hip height (d ≈ 0.53 × 1.70 m = 0.90 m) that is 0.147059 × 0.90 = 0.132 m — 13.2 cm, left to the root angle and the
 * chain bend (which only reach a few centimetres of it on a short part).
 *
 * THE OTHER STORED VALUES. Partner B's tilt/roll/yaw are angles and stay as stored; their pivot (`pairFit.fixPivot`)
 * is B's scaled root plus its own bind hips, a length of B's real body — so the turn follows the rule by itself. The
 * renderer-only `shift_cm` of a pair/group half is part of the measured arrangement (the root effectively sits at
 * p_i + s_i), so it is a LENGTH of the 1.70 m arrangement and scales with its figure: C + a_i·(p_i + s_i − C) =
 * p_i' + a_i·s_i (`scalePairShift`). The baked partner/role shifts are already inside p_i. A solo clip's `shift_cm`
 * stays absolute (§ A8, "Horizontal clip calibration").
 *
 * Pure maths, no three.js.
 */
import { FIGURE_HEIGHT_M } from './figure'
import { keyFrames } from './pairAlign'
import type { Vec3 } from './collision'

/** A horizontal point of the clip frame, metres (+X = side, +Z = forward). */
export interface PairXZ { x: number; z: number }

/** The bound of a stored pivot, cm per component (the server's `PAIR_PIVOT_BOUND_CM`). */
export const PAIR_PIVOT_BOUND_CM = 300

/** The pivot of a clip without a stored one: the clip frame's origin. */
export const PAIR_PIVOT_ORIGIN: Readonly<PairXZ> = Object.freeze({ x: 0, z: 0 })

/** Figure i's scale a_i = height / 1.70 m; 1 for a missing or non-positive height. */
export function pairFigureScale(heightM?: number | null): number {
  return typeof heightM === 'number' && Number.isFinite(heightM) && heightM > 0 ? heightM / FIGURE_HEIGHT_M : 1
}

/** The clip's contact pivot C (metres) from its stored `pair_pivot_cm` [side, forward]; the origin without a valid one. */
export function pairPivotOf(storedCm?: readonly unknown[] | null): PairXZ {
  const ok = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= PAIR_PIVOT_BOUND_CM
  if (!Array.isArray(storedCm) || storedCm.length !== 2 || !ok(storedCm[0]) || !ok(storedCm[1])) return PAIR_PIVOT_ORIGIN
  return { x: storedCm[0] / 100, z: storedCm[1] / 100 }
}

/** p' = C + a·(p − C) for one figure's root (clip frame, metres); a = 1 returns `root` itself (bit for bit). */
export function scalePairRoot<T extends PairXZ>(root: T, pivot: PairXZ, a: number): T | PairXZ {
  if (a === 1) return root
  return { x: pivot.x + a * (root.x - pivot.x), z: pivot.z + a * (root.z - pivot.z) }
}

/** The renderer-only shift of a pair/group half for a figure of scale `a`: a·s (a = 1: `shift` itself). */
export function scalePairShift<T extends PairXZ>(shift: T, a: number): T | PairXZ {
  return a === 1 ? shift : { x: a * shift.x, z: a * shift.z }
}

/** A world point (stage space) in the clip frame of a place anchor turned by `placeYaw` (radians): the inverse of
 *  `x = ax + rx·cos + rz·sin, z = az − rx·sin + rz·cos` — rx = cos·dx − sin·dz, rz = sin·dx + cos·dz. */
export function clipFramePivot(point: readonly number[], anchor: { x: number; z: number }, placeYaw: number): PairXZ {
  const dx = point[0] - anchor.x, dz = point[2] - anchor.z
  const c = Math.cos(placeYaw), s = Math.sin(placeYaw)
  return { x: c * dx - s * dz, z: s * dx + c * dz }
}

/** Auto-align's pivot (cm, 0.1 cm, [side, forward]): per contact relation the target's point `o` at its DEEPEST key
 *  frame (`keyFrames`), in the clip frame of `anchor`/`placeYaw`, averaged over the relations; null for none. */
export function pairPivotCm(relations: readonly (readonly { tip: Vec3; o: Vec3; u: Vec3 }[])[],
  anchor: { x: number; z: number }, placeYaw: number): [number, number] | null {
  const pts: PairXZ[] = []
  for (const samples of relations) {
    const k = keyFrames(samples)
    if (k) pts.push(clipFramePivot(samples[k.deep].o, anchor, placeYaw))
  }
  if (!pts.length) return null
  const r = (v: number) => Math.round(v * 1000) / 10 || 0
  const x = pts.reduce((a, p) => a + p.x, 0) / pts.length, z = pts.reduce((a, p) => a + p.z, 0) / pts.length
  const b = (v: number) => Math.max(-PAIR_PIVOT_BOUND_CM, Math.min(PAIR_PIVOT_BOUND_CM, r(v)))
  return [b(x), b(z)]
}
