/**
 * CONTACT TARGETS (Ruling A139, A159): what the attached part's tip of a pair clip aims at. Auto-align
 * (`channelContact.ts`) and the runtime fit/follow (`pairFit.ts`) solve against ONE target point O with ONE unit axis
 * u. A pair clip names its target (the clip's `<kind>.json` `contact_relations`, or a package default for its kind):
 *
 * - `channel`    — the receiving figure's DECLARED channel that accepts the part (A126): O = opening, u = into the body.
 *                  The mouth never counts here.
 * - `mouth`      — the receiving figure's MOUTH OPENING (Ruling A159, `mouthChannel`): a channel every humanoid figure
 *                  carries on its head, built from the head bones each frame. It works exactly like a declared
 *                  channel — engagement, radial guidance, depth scale, the opening that widens to the entering part's
 *                  surface radius (`channelOpening.ts`), the channel readouts and lamp. Its frame, with H the head
 *                  bone, T the head-top end, L = |T − H| and the head's up h = (T − H)/L — without T, L = `MOUTH.lengthM`
 *                  × the head bone's world scale and h = its +Y (rigs without a head-top end) — and the face direction f (the eyes' midpoint − H, else the head bone's local +Z, made orthogonal to h):
 *                    O = the MEASURED opening on the lips, u = toward the throat (Ruling A193: the collision
 *                        record's `mouth`, `app/core/mouth_landmark.py`, bound to the head joint, so it follows
 *                        every head turn and tilt); a record without one keeps the formula
 *                    O = H + f · `MOUTH.forward` · L + h · `MOUTH.up` · L     (≈ 10 cm forward, 3 cm up for L = 0.2 m)
 *                    u = −f                                                  (into the head, along the face normal)
 *                    D = `MOUTH.depth` · L,  R = `MOUTH.radius` · L,  F = `MOUTH.funnel` · L,  α = `MOUTH.coneDeg`
 *                  accepts the attached-part ops (`POINT_TARGET_OPS`), any running pair interaction, least state length
 *                  `MOUTH.minLength`, least depth scale `MOUTH.compressMin`; an engaged tip inside skips the head
 *                  capsules (`mouthChannel`'s `suppress`, the caller passes the head region's capsule ids).
 * - `hand_left` / `hand_right` — the PALM CENTRE of that hand of the receiving figure:
 *     O = ½ (hand + middle-finger root)      (the middle of the palm along its length)
 *     u = (pinky root − index root) / |…|    (the grip axis across the palm; a gripped shaft runs along it),
 *   oriented by the caller along the shaft (`orientAlong`), since a grip has no "inside".
 * - `none`       — no contact: no fit, no follow, Auto-align refuses.
 *
 * A point target (a hand) is aimed at by the first chain whose op is in `POINT_TARGET_OPS`; a channel and the mouth
 * pick by their `accepts`.
 *
 * The CHECKS report the distance to the target at the entry frame and the lateral off the axis; DEPTH only for a
 * channel or the mouth (a hand has no inside). The lamp of a hand (`targetLamp`): green = entry ≤
 * `CONTACT_ENTRY_GREEN_MM` and the largest lateral ≤ the target's radius (`TARGET_RADIUS_M`), yellow ≤ twice it,
 * red beyond. The mouth uses the channel lamp (`contactLamp`).
 *
 * Bones are read by `normBoneName` (no `mixamorig`, no case): `lefthand`, `lefthandmiddle1`, `lefthandindex1`,
 * `lefthandpinky1` (right likewise), `head`, `headtop_end`, `lefteye`, `righteye`.
 */
import type { Vec3 } from './collision'
import { CONTACT_ENTRY_GREEN_MM, type ContactLamp, type ContactReport } from './channelContact'
import type { ChannelNow } from './channels'

export const CONTACT_TARGETS = ['channel', 'mouth', 'hand_left', 'hand_right', 'none'] as const
export type ContactTarget = typeof CONTACT_TARGETS[number]
/** The point targets (no inside: not a channel, not the mouth, not none). */
export type PointTarget = 'hand_left' | 'hand_right'
export const POINT_TARGETS: readonly PointTarget[] = ['hand_left', 'hand_right']
/** The chain ops that aim at a point target or enter the mouth (an attached part; other op chains — tips,
 *  protrusions — never do). */
export const POINT_TARGET_OPS: readonly string[] = ['attached_part', 'appendage_chain']
/** The lamp's radius of a point target (metres). */
export const TARGET_RADIUS_M: Readonly<Record<PointTarget, number>> = Object.freeze({ hand_left: 0.025, hand_right: 0.025 })
/** The mouth channel's id (in `FigureInspection.channels`, the partner snapshot, the opening state). */
export const MOUTH_CHANNEL_ID = 'mouth'
/** The mouth opening as fractions of the head length L (module docstring), and its gates. */
export const MOUTH = Object.freeze({ forward: 0.5, up: 0.15, lengthM: 0.2, depth: 0.5, radius: 0.1, funnel: 0.15,
  coneDeg: 35, minLength: 0, compressMin: 0.6 })

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
  /** The head bone's local +Y column in the world, NOT normalised (its length = the head bone's world scale). */
  headY?: Vec3
  /** The MEASURED mouth opening and a point toward the throat (collision v9 `mouth`, through the head joint;
   *  Ruling A193). Both present = they replace the formula's O and u. */
  mouthO?: Vec3
  mouthB?: Vec3
}
export const TARGET_BONE_NAMES: readonly (keyof TargetBones)[] = ['lefthand', 'lefthandmiddle1', 'lefthandindex1',
  'lefthandpinky1', 'righthand', 'righthandmiddle1', 'righthandindex1', 'righthandpinky1', 'head', 'headtop_end',
  'lefteye', 'righteye']

/** One resolved target of a figure (world). */
export interface TargetFrame { id: PointTarget; o: Vec3; u: Vec3; r: number }

const sub = (p: Vec3, q: Vec3): Vec3 => [p[0] - q[0], p[1] - q[1], p[2] - q[2]]
const add = (p: Vec3, q: Vec3): Vec3 => [p[0] + q[0], p[1] + q[1], p[2] + q[2]]
const mul = (p: Vec3, k: number): Vec3 => [p[0] * k, p[1] * k, p[2] * k]
const dot = (p: Vec3, q: Vec3) => p[0] * q[0] + p[1] * q[1] + p[2] * q[2]
const len = (p: Vec3) => Math.hypot(p[0], p[1], p[2])
const unit = (p: Vec3): Vec3 | null => { const l = len(p); return l > 1e-9 ? mul(p, 1 / l) : null }

/** The target `id` from `bones` (module docstring), or null when its bones are missing. */
export function targetFrame(id: PointTarget, bones: TargetBones): TargetFrame | null {
  const s = id === 'hand_left' ? 'left' : 'right'
  const hand = bones[`${s}hand` as const], idx = bones[`${s}handindex1` as const], pin = bones[`${s}handpinky1` as const]
  if (!hand || !idx || !pin) return null
  const mid = bones[`${s}handmiddle1` as const] ?? mul(add(idx, pin), 0.5)
  const u = unit(sub(pin, idx))
  if (!u) return null
  return { id, o: mul(add(hand, mid), 0.5), u, r: TARGET_RADIUS_M[id] }
}

/** The head frame the mouth is built on (module docstring): H, the head length L, up h and face direction f. */
function headFrame(bones: TargetBones): { H: Vec3; L: number; h: Vec3; f: Vec3 } | null {
  const H = bones.head
  if (!H) return null
  const top = bones.headtop_end
  // Without a head-top end: the head bone's own +Y and world scale stand in for the head's up and size.
  const L = top ? len(sub(top, H)) : MOUTH.lengthM * (bones.headY ? len(bones.headY) : 1)
  if (!(L > 1e-6)) return null
  const h = (top && unit(sub(top, H))) || (bones.headY && unit(bones.headY)) || [0, 1, 0] as Vec3
  let f: Vec3 | null = null
  if (bones.lefteye && bones.righteye) f = sub(mul(add(bones.lefteye, bones.righteye), 0.5), H)
  else if (bones.headZ) f = bones.headZ
  if (!f) return null
  f = unit(sub(f, mul(h, dot(f, h))))
  return f ? { H, L, h, f } : null
}

/** The MOUTH OPENING of a figure from its head bones (module docstring), or null without a head frame. `suppress`:
 *  the ids of the figure's head capsules an engaged tip inside skips. */
export function mouthChannel(bones: TargetBones, suppress: ReadonlySet<string> = new Set()): ChannelNow | null {
  const fr = headFrame(bones)
  if (!fr) return null
  const { H, L, h, f } = fr
  const measured = bones.mouthO && bones.mouthB ? unit(sub(bones.mouthB, bones.mouthO)) : null
  return {
    id: MOUTH_CHANNEL_ID,
    o: measured ? bones.mouthO! : add(add(H, mul(f, MOUTH.forward * L)), mul(h, MOUTH.up * L)),
    u: measured ?? mul(f, -1),
    depth: MOUTH.depth * L, r: MOUTH.radius * L, coneDeg: MOUTH.coneDeg, funnel: MOUTH.funnel * L,
    accepts: POINT_TARGET_OPS, minLength: MOUTH.minLength, compressMin: MOUTH.compressMin, kinds: null, suppress,
  }
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
