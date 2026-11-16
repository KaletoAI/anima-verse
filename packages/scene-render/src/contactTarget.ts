/**
 * CONTACT TARGETS (Ruling A139): what the attached part's tip of a pair clip aims at. Auto-align (`channelContact.ts`)
 * and the runtime fit/follow (`pairFit.ts`) solve against ONE target point O with ONE unit axis u; until A139 that was
 * always a channel's opening and its axis into the body. A pair clip names its target (the clip's `<kind>.json`
 * `contact_target`, or a package default for its kind):
 *
 * - `channel`    — the receiving figure's channel that accepts the part (A126): O = opening, u = into the body.
 * - `hand_left` / `hand_right` — the PALM CENTRE of that hand of the receiving figure:
 *     O = ½ (hand + middle-finger root)      (the middle of the palm along its length)
 *     u = (pinky root − index root) / |…|    (the grip axis across the palm; a gripped shaft runs along it),
 *   oriented by the caller along the shaft (`orientAlong`), since a grip has no "inside".
 * - `head_front` — a STAND-IN for a mouth (PROVISIONAL: there is no mouth opening yet, see the unified-worn-pieces spec
 *   open items): with H the head bone, T the head-top end, L = |T − H| (fallback `HEAD_FRONT.lengthM`), the head's up
 *   h = (T − H)/L and the face direction f (the eyes' midpoint − H, else the head bone's local +Z, made orthogonal to
 *   h):  O = H + f · `HEAD_FRONT.forward` · L + h · `HEAD_FRONT.up` · L  (≈ 10 cm forward, 3 cm up for a 0.2 m head —
 *   mouth height in front of the face), u = −f (towards the head).
 * - `none`       — no contact: no fit, no follow, Auto-align refuses.
 *
 * A point target is aimed at by the first chain whose op is in `POINT_TARGET_OPS` (a channel picks by its `accepts`).
 *
 * The CHECKS report the distance to the target at the entry frame and the lateral off the axis; DEPTH only for a
 * channel (a hand or the head stand-in has no inside). The lamp of a non-channel target (`targetLamp`): green = entry
 * ≤ `CONTACT_ENTRY_GREEN_MM` and the largest lateral ≤ the target's radius (`TARGET_RADIUS_M`), yellow ≤ twice it,
 * red beyond.
 *
 * Bones are read by `normBoneName` (no `mixamorig`, no case): `lefthand`, `lefthandmiddle1`, `lefthandindex1`,
 * `lefthandpinky1` (right likewise), `head`, `headtop_end`, `lefteye`, `righteye`.
 */
import type { Vec3 } from './collision'
import { CONTACT_ENTRY_GREEN_MM, type ContactLamp, type ContactReport } from './channelContact'

export const CONTACT_TARGETS = ['channel', 'hand_left', 'hand_right', 'head_front', 'none'] as const
export type ContactTarget = typeof CONTACT_TARGETS[number]
/** The point targets (not a channel, not none). */
export type PointTarget = 'hand_left' | 'hand_right' | 'head_front'
export const POINT_TARGETS: readonly PointTarget[] = ['hand_left', 'hand_right', 'head_front']
/** The chain ops that aim at a point target (an attached part; other op chains — tips, protrusions — never do). */
export const POINT_TARGET_OPS: readonly string[] = ['attached_part', 'appendage_chain']
/** Targets that only stand in for something not built yet. */
export const PROVISIONAL_TARGETS: readonly ContactTarget[] = ['head_front']
/** The lamp's radius of a point target (metres). */
export const TARGET_RADIUS_M: Readonly<Record<PointTarget, number>> = Object.freeze({
  hand_left: 0.025, hand_right: 0.025, head_front: 0.02 })
/** The head stand-in as fractions of the head length L (module docstring). */
export const HEAD_FRONT = Object.freeze({ forward: 0.5, up: 0.15, lengthM: 0.2 })

export function isContactTarget(v: unknown): v is ContactTarget {
  return typeof v === 'string' && (CONTACT_TARGETS as readonly string[]).includes(v)
}
export function isPointTarget(v: unknown): v is PointTarget {
  return typeof v === 'string' && (POINT_TARGETS as readonly string[]).includes(v)
}

/** World positions (and the head bone's local +Z in the world) a figure's targets are built from; any may be absent. */
export interface TargetBones {
  lefthand?: Vec3; lefthandmiddle1?: Vec3; lefthandindex1?: Vec3; lefthandpinky1?: Vec3
  righthand?: Vec3; righthandmiddle1?: Vec3; righthandindex1?: Vec3; righthandpinky1?: Vec3
  head?: Vec3; headtop_end?: Vec3; lefteye?: Vec3; righteye?: Vec3
  /** The head bone's local +Z axis in the world (unit). */
  headZ?: Vec3
}
export const TARGET_BONE_NAMES: readonly (keyof TargetBones)[] = ['lefthand', 'lefthandmiddle1', 'lefthandindex1',
  'lefthandpinky1', 'righthand', 'righthandmiddle1', 'righthandindex1', 'righthandpinky1', 'head', 'headtop_end',
  'lefteye', 'righteye']

/** One resolved target of a figure (world). */
export interface TargetFrame { id: PointTarget; o: Vec3; u: Vec3; r: number; provisional: boolean }

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const mul = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const len = (p: Vec3) => Math.hypot(p[0], p[1], p[2])
const unit = (p: Vec3): Vec3 | null => { const l = len(p); return l > 1e-9 ? mul(p, 1 / l) : null }

/** The target `id` from `bones` (module docstring), or null when its bones are missing. */
export function targetFrame(id: PointTarget, bones: TargetBones): TargetFrame | null {
  if (id === 'hand_left' || id === 'hand_right') {
    const s = id === 'hand_left' ? 'left' : 'right'
    const hand = bones[`${s}hand` as const], idx = bones[`${s}handindex1` as const], pin = bones[`${s}handpinky1` as const]
    if (!hand || !idx || !pin) return null
    const mid = bones[`${s}handmiddle1` as const] ?? mul(add(idx, pin), 0.5)
    const u = unit(sub(pin, idx))
    if (!u) return null
    return { id, o: mul(add(hand, mid), 0.5), u, r: TARGET_RADIUS_M[id], provisional: false }
  }
  const H = bones.head
  if (!H) return null
  const top = bones.headtop_end
  const L = top ? len(sub(top, H)) : HEAD_FRONT.lengthM
  const h = (top && unit(sub(top, H))) || [0, 1, 0] as Vec3
  let f: Vec3 | null = null
  if (bones.lefteye && bones.righteye) f = sub(mul(add(bones.lefteye, bones.righteye), 0.5), H)
  else if (bones.headZ) f = bones.headZ
  if (!f) return null
  f = unit(sub(f, mul(h, dot(f, h))))
  if (!f) return null
  const o = add(add(H, mul(f, HEAD_FRONT.forward * L)), mul(h, HEAD_FRONT.up * L))
  return { id, o, u: mul(f, -1), r: TARGET_RADIUS_M.head_front, provisional: true }
}

/** Every point target `bones` resolve (the inspection's `targets`). */
export function targetFrames(bones: TargetBones): TargetFrame[] {
  return POINT_TARGETS.map((id) => targetFrame(id, bones)).filter((x): x is TargetFrame => !!x)
}

/** A grip has no inside: its axis is turned to run along the shaft (base → tip). Other targets keep theirs. */
export function orientAlong(id: string, u: Vec3, tip: Vec3, base: Vec3): Vec3 {
  if (id !== 'hand_left' && id !== 'hand_right') return u
  return dot(u, sub(tip, base)) < 0 ? mul(u, -1) : u
}

/** The lamp of a point target (module docstring). */
export function targetLamp(rep: ContactReport, radiusM: number): ContactLamp {
  const rMm = radiusM * 1000
  if (!(rep.frames > 0)) return 'red'
  if (rep.entryMm <= CONTACT_ENTRY_GREEN_MM && rep.maxLateralMm <= rMm) return 'green'
  if (rep.entryMm <= 2 * rMm && rep.maxLateralMm <= 2 * rMm) return 'yellow'
  return 'red'
}
