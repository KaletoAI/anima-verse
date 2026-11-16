/**
 * CLIP CALIBRATION — the alignment DRAFT of the Library over a clip's SAVED orientation, for one figure on one
 * place (Ruling A110 phase 2, spec 2026-11-16-poses-tab-redesign-design.md § 2.2 "Draft flow").
 *
 * The orientation bake (`app/blender/scripts/clip_orient.py`, `animation_clips.orient_clip`) rewrites the clip:
 * every role's hips path P becomes  P' = R · (P + S_role)  and every hips rotation Q becomes  R · Q, with
 * R = Ry(yaw) · Rx(tilt) · Rz(roll) (three's Euler order `YXZ`) and S_role the role shift (a pair's partner B,
 * a group's roles) applied BEFORE the turn. The renderer-only `shift_cm` and the per-surface height corrections
 * are never baked: they stay sidecar values the placement adds in WORLD axes (shift turned by the place yaw only).
 *
 * This module predicts that bake for a draft that is not written yet, so "what the preview shows" = "what Apply
 * writes": the figure root is placed so that the hips land on the BAKED hips point and the body turns by the
 * baked rotation. After Apply the clip carries R and S itself, the draft is reset to zero, and the same formula
 * with the draft at zero gives the same hips point — the "no jump" of phase 2
 * (`scripts/smoke_clip_calibration.mjs`, numbers derived in its docstring).
 *
 * Pure maths, no three.js: the callers turn `rootQuat` / `rootPos` into their own objects.
 */
import { clipHeightGroup, clipHipsDrop, clipShiftM, FIGURE_HEIGHT_M } from './figure'
import type { ClipHeightOffsetsCm, ClipShiftCm } from './figure'

export type Vec3 = { x: number; y: number; z: number }
type Mat3 = [number, number, number, number, number, number, number, number, number]

/** The Library's alignment draft for ONE clip — every field 0 / empty = nothing dialled. */
export interface AlignmentDraft {
  /** The three bake angles (degrees). */
  yawDeg: number
  tiltDeg: number
  rollDeg: number
  /** Renderer-only [side, forward] cm, added to the saved `shift_cm`. */
  shiftCm: ClipShiftCm
  /** Baked role shifts, clip frame metres [side, up, forward] per role (a pair: `b`; a group: any of a…e). */
  roleShiftM: Readonly<Record<string, readonly [number, number, number]>>
  /** Draft surface corrections in cm per surface group; a group not named keeps its saved value. */
  heightCm: ClipHeightOffsetsCm
  /** Ruling A129: a pair's partner B turned about its hips, renderer-only [tilt, roll] degrees (`partnerTurnFix`). */
  partnerTurnDeg?: readonly [number, number]
}

export const EMPTY_DRAFT: AlignmentDraft = Object.freeze({
  yawDeg: 0, tiltDeg: 0, rollDeg: 0, shiftCm: [0, 0] as const, roleShiftM: {}, heightCm: {},
}) as AlignmentDraft

/** What the clip's sidecar already holds of the non-baked calibration. */
export interface SavedCalibration {
  shiftCm?: ClipShiftCm | null
  heightOffsetsCm?: ClipHeightOffsetsCm | null
}

/** `draft` has nothing to apply. */
export function isEmptyDraft(d: AlignmentDraft): boolean {
  return !d.yawDeg && !d.tiltDeg && !d.rollDeg && !d.shiftCm[0] && !d.shiftCm[1]
    && !Object.values(d.roleShiftM).some((v) => v.some((x) => x))
    && !Object.keys(d.heightCm).length && !(d.partnerTurnDeg && (d.partnerTurnDeg[0] || d.partnerTurnDeg[1]))
}

const RAD = Math.PI / 180

/** Ry(y) · Rx(x) · Rz(z) — three's `Euler(x, y, z, 'YXZ')` as a row-major 3×3. */
export function eulerYXZ(x: number, y: number, z: number): Mat3 {
  const cx = Math.cos(x), sx = Math.sin(x), cy = Math.cos(y), sy = Math.sin(y), cz = Math.cos(z), sz = Math.sin(z)
  return [
    cy * cz + sy * sx * sz, -cy * sz + sy * sx * cz, sy * cx,
    cx * sz, cx * cz, -sx,
    -sy * cz + cy * sx * sz, sy * sz + cy * sx * cz, cy * cx,
  ]
}

export function mulVec(m: Mat3, v: Vec3): Vec3 {
  return { x: m[0] * v.x + m[1] * v.y + m[2] * v.z, y: m[3] * v.x + m[4] * v.y + m[5] * v.z,
    z: m[6] * v.x + m[7] * v.y + m[8] * v.z }
}

/** Quaternion [x, y, z, w] of a rotation matrix (Shepperd). */
export function matQuat(m: Mat3): [number, number, number, number] {
  const [a, b, c, d, e, f, g, h, i] = m
  const tr = a + e + i
  if (tr > 0) {
    const s = 0.5 / Math.sqrt(tr + 1)
    return [(h - f) * s, (c - g) * s, (d - b) * s, 0.25 / s]
  }
  if (a > e && a > i) {
    const s = 2 * Math.sqrt(1 + a - e - i)
    return [0.25 * s, (b + d) / s, (c + g) / s, (h - f) / s]
  }
  if (e > i) {
    const s = 2 * Math.sqrt(1 + e - a - i)
    return [(b + d) / s, 0.25 * s, (f + h) / s, (c - g) / s]
  }
  const s = 2 * Math.sqrt(1 + i - a - e)
  return [(c + g) / s, (f + h) / s, 0.25 * s, (d - b) / s]
}

/** The calibration of one clip on one place. */
export interface ClipCalibration {
  /** The bake rotation R of the draft (row-major). */
  bake: Mat3
  /** Root rotation = Ry(placeYaw) · R, as Euler YXZ radians [x, y, z] and as a matrix. */
  euler: [number, number, number]
  frame: Mat3
  /** The place yaw alone (radians) — turns clip-frame points into world axes. */
  placeYaw: number
  /** World offset of the non-baked calibration: horizontal shift (saved + draft, turned by the place yaw) and the
   *  surface height correction of the place's group (the draft's value when it names the group, else saved). */
  offset: Vec3
  /** The draft role shift of `role` (clip frame metres). */
  roleShift(role: string): Vec3
}

/** Combine `draft` over `saved` for a clip played on a place of `group`, yawed by `placeYawRad` (solo: the place
 *  facing; pair/group: `pairYaw(facing, yaw_offset)`). */
export function clipCalibration(draft: AlignmentDraft, saved: SavedCalibration, placeYawRad: number,
  group?: string | null, figureHeight = FIGURE_HEIGHT_M): ClipCalibration {
  const tilt = (draft.tiltDeg || 0) * RAD
  const yaw = (draft.yawDeg || 0) * RAD
  const roll = (draft.rollDeg || 0) * RAD
  const bake = eulerYXZ(tilt, yaw, roll)
  const frame = eulerYXZ(tilt, placeYawRad + yaw, roll)
  const s0 = saved.shiftCm ?? [0, 0]
  const shift = clipShiftM([(s0[0] || 0) + (draft.shiftCm[0] || 0), (s0[1] || 0) + (draft.shiftCm[1] || 0)], placeYawRad)
  const g = clipHeightGroup(group)
  const cm = draft.heightCm[g] ?? saved.heightOffsetsCm?.[g] ?? 0
  const heightM = typeof cm === 'number' && Number.isFinite(cm) ? cm / 100 * figureHeight / FIGURE_HEIGHT_M : 0
  return {
    bake, frame, placeYaw: placeYawRad, euler: [tilt, placeYawRad + yaw, roll],
    offset: { x: shift.x, y: heightM, z: shift.z },
    roleShift(role: string): Vec3 {
      const v = draft.roleShiftM[role]
      return v ? { x: v[0] || 0, y: v[1] || 0, z: v[2] || 0 } : { x: 0, y: 0, z: 0 }
    },
  }
}

/** The figure's hips point in the clip frame AFTER the draft's bake: P' = R · (P + S_role). */
export function bakedHips(cal: ClipCalibration, role: string, hips: Vec3): Vec3 {
  const s = cal.roleShift(role)
  return mulVec(cal.bake, { x: hips.x + s.x, y: hips.y + s.y, z: hips.z + s.z })
}

/** Inputs of `calibratedRoot` for one figure at one instant. */
export interface RootInput {
  /** Where the clip frame's origin stands (world): a solo slot, or a pair/group place centre, at root height. */
  anchor: Vec3
  /** The role ('' = solo) and its hips point NOW in the SAVED clip (clip frame metres, `rootAt(path, t)`). */
  role: string
  hips: Vec3
  /** Solo clips play in place: the horizontal hips travel is dropped (after the bake, as playback does). */
  inPlace: boolean
  /** The figure's hips at bind, in root space (metres) — the point the skeleton turns about. */
  hipsBind: Vec3
  /** The standing hips reference of the library (metres; `standHipsRef`), 0 = none. */
  standRefM: number
}

/** World root position for `cal` — the hips land where the BAKED clip would put them, the root turned by `frame`.
 *
 *  After a bake the root is at  anchor + Ry · L'  with  L' = (P'x, −drop(P'y), P'z)  and no extra turn, so the
 *  hips sit at  anchor + Ry · (L' + H)  (H = hips bind). With the draft the root also turns by R about its own
 *  origin, which would carry the hips to  Ry · R · H ; the root is therefore moved by  Ry · (H − R · H)  so the
 *  hips end on the same point. Plus the world offset (shift, height). */
export function calibratedRoot(cal: ClipCalibration, inp: RootInput): Vec3 {
  const p = bakedHips(cal, inp.role, inp.hips)
  const drop = clipHipsDrop(inp.hipsBind.y, p.y, inp.standRefM)
  const local = { x: inp.inPlace ? 0 : p.x, y: -drop, z: inp.inPlace ? 0 : p.z }
  const rh = mulVec(cal.bake, inp.hipsBind)
  const l = { x: local.x + inp.hipsBind.x - rh.x, y: local.y + inp.hipsBind.y - rh.y, z: local.z + inp.hipsBind.z - rh.z }
  const ry = eulerYXZ(0, cal.placeYaw, 0)
  const w = mulVec(ry, l)
  return { x: inp.anchor.x + w.x + cal.offset.x, y: inp.anchor.y + w.y + cal.offset.y, z: inp.anchor.z + w.z + cal.offset.z }
}

// ── the readout (D4) ──

export type AlignmentLamp = 'green' | 'yellow' | 'red'

/** D4: green ≤ 3° and ≤ 2 cm, yellow ≤ 10° and ≤ 6 cm, red beyond — judged on the loop MEDIAN. */
export const ALIGN_GREEN = { deg: 3, cm: 2 } as const
export const ALIGN_YELLOW = { deg: 10, cm: 6 } as const

export function alignmentLamp(dyawDeg: number, dposCm: number): AlignmentLamp {
  const y = Math.abs(dyawDeg), p = Math.abs(dposCm)
  if (y <= ALIGN_GREEN.deg && p <= ALIGN_GREEN.cm) return 'green'
  if (y <= ALIGN_YELLOW.deg && p <= ALIGN_YELLOW.cm) return 'yellow'
  return 'red'
}

/** Signed angle a − b wrapped into (−180, 180] degrees. */
export function wrapDeg(d: number): number {
  let v = ((d + 180) % 360 + 360) % 360 - 180
  if (v === -180) v = 180
  return v
}

/** Median of samples (the mean of the middle two for an even count); NaN for none. */
export function median(values: readonly number[]): number {
  if (!values.length) return NaN
  const s = [...values].sort((a, b) => a - b)
  const m = s.length >> 1
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

/** Δyaw (deg) of a body forward (world XZ) against a facing in degrees (+Z = 0, +X = 90), and Δpos (cm) of the
 *  hips XZ against the slot point. */
export function alignmentDelta(forward: { x: number; z: number }, facingDeg: number,
  hips: { x: number; z: number }, slot: { x: number; z: number }): { dyaw: number; dpos: number } {
  const yaw = Math.atan2(forward.x, forward.z) / RAD
  return { dyaw: wrapDeg(yaw - facingDeg), dpos: Math.hypot(hips.x - slot.x, hips.z - slot.z) * 100 }
}
