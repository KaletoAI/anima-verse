/**
 * THE OPEN MOUTH (Ruling A203). A body whose mouth channel was built (`app/blender/scripts/mouth_part.py`) carries
 * the bone `Jaw` (a child of Head at the jaw's hinge, owning the chin, the lower lip and the channel's lower wall by
 * computed weights) and the morph target `mouth_open` (the upper lip's lift and the channel's dome). ONE number, 0 =
 * closed with the lips meeting … 1 = fully open, drives both: the jaw turns about the body's side axis by
 * value × its full angle (the bone's `mouth_open_deg`, `JAW_OPEN_DEG` without one), the target's influence is the
 * value. A body of build 2 has no bone and its target carries the turn as well; the same number opens it.
 *
 * The jaw's turn: local quaternion = rest · Q(a, angle), with a = the model's +X (the side axis the build turned
 * about; + opens, the chin goes down) read in the bone's own bind frame — the first ROW of its bind rotation (the
 * inverse of its inverse bind matrix). While the value is 0 and was never above it the bone is left alone, so a clip
 * that animates `Jaw` keeps its say.
 *
 * The number comes from two sources:
 *
 * - CONTACT: a partner's chain engaged in the figure's mouth channel opens it as far as the entering part needs —
 *   `mouthOpenFor(radius, openHeight)` = (2 · radius + `MOUTH_OPEN_MARGIN_M`) / openHeight, clamped to [0, 1], with
 *   `radius` the occupant's largest segment radius × its engagement weight w (the same value the opening pass
 *   widens the surface to, `channelOpening.ts`) and `openHeight` the height of the opening at `mouth_open` 1 as the
 *   build measured it (the channel record's `open_height`). A body with TEETH (Ruling A206) passes `teeth_gap`
 *   instead — the free height between the incisal edges at the same opening, which is smaller — so the mouth opens
 *   far enough that the part clears the teeth (`mouthPassHeight`). The surface pass still runs on top and shapes
 *   the lips around the part; it moves the rigid teeth as whole rows out of the part's way, never bends them
 *   (`channelOpening.ts`, THE TEETH).
 * - MANUAL: `setManual` (a preview slider, an expression) — the larger of the two applies.
 *
 * `bindMouthOpen` finds every skinned mesh of an instance that carries the target and the jaw bone of its skeleton;
 * null when the instance has neither (a body built before A203, or one whose build found no lip line), and nothing
 * is driven.
 */
import type { Bone, Object3D, Quaternion, SkinnedMesh } from 'three'
import { normBoneName } from './clipRetarget'

/** The morph target's name (the Blender shape key, the glTF `targetNames` entry). */
export const MOUTH_OPEN_TARGET = 'mouth_open'
/** The jaw bone's name by `normBoneName`, and its full angle when the bone carries none (degrees). */
export const JAW_BONE = 'jaw'
export const JAW_OPEN_DEG = 30
/** Room around an entering part: the opening's height is its diameter plus this (metres). */
export const MOUTH_OPEN_MARGIN_M = 0.004

/** The height a part must pass with the mouth fully open: the free height between the teeth (`teeth_gap`, Ruling
 *  A206) when the body has teeth, else the lips' opening (`open_height`); 0 without either. */
export function mouthPassHeight(channel: { open_height?: number; teeth_gap?: number } | null | undefined): number {
  const gap = channel?.teeth_gap
  if (typeof gap === 'number' && gap > 0) return gap
  const height = channel?.open_height
  return typeof height === 'number' && height > 0 ? height : 0
}

/** How far the mouth must open for a part of `radius` (metres) when the fully open mouth is `openHeight` high. */
export function mouthOpenFor(radius: number, openHeight: number): number {
  if (!(radius > 0) || !(openHeight > 0)) return 0
  return Math.min(1, Math.max(0, (2 * radius + MOUTH_OPEN_MARGIN_M) / openHeight))
}

export interface MouthOpen {
  /** The value the contact asks for this frame (0 without an occupant). */
  setContact(value: number): void
  /** The value a preview or an expression asks for; stays until changed. */
  setManual(value: number): void
  /** The value applied now: max(contact, manual), clamped to [0, 1]. */
  readonly value: number
}

const clamp01 = (v: number) => (Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0)

/** Bind the open mouth of `instance` (module docstring). Null when it has neither the target nor the jaw bone. */
export function bindMouthOpen(instance: Object3D): MouthOpen | null {
  const slots: { mesh: SkinnedMesh; index: number }[] = []
  const jaws = new Map<Bone, { rest: Quaternion; turn: Quaternion; axis: { x: number; y: number; z: number }; full: number }>()
  instance.traverse(o => {
    const mesh = o as SkinnedMesh
    const index = mesh.morphTargetDictionary?.[MOUTH_OPEN_TARGET]
    if (mesh.morphTargetInfluences && index !== undefined) slots.push({ mesh, index })
    if (!mesh.isSkinnedMesh || !mesh.skeleton) return
    mesh.skeleton.bones.forEach((bone, i) => {
      if (jaws.has(bone) || normBoneName(bone.name) !== JAW_BONE || !mesh.skeleton.boneInverses[i]) return
      // The bone's bind frame in the model space; its first row is the model's +X in the bone's own axes.
      const e = mesh.skeleton.boneInverses[i].clone().invert().elements
      const n = Math.hypot(e[0], e[4], e[8]) || 1
      const deg = Number((bone.userData as { mouth_open_deg?: unknown } | undefined)?.mouth_open_deg)
      jaws.set(bone, { rest: bone.quaternion.clone(), turn: bone.quaternion.clone(),
        axis: { x: e[0] / n, y: e[4] / n, z: e[8] / n }, full: (deg > 0 && deg <= 90 ? deg : JAW_OPEN_DEG) * Math.PI / 180 })
    })
  })
  if (!slots.length && !jaws.size) return null
  let contact = 0, manual = 0, value = 0, driven = false
  const apply = () => {
    value = Math.max(contact, manual)
    for (const s of slots) s.mesh.morphTargetInfluences![s.index] = value
    if (!(value > 0) && !driven) return
    driven = value > 0
    for (const [bone, jaw] of jaws) {
      jaw.turn.setFromAxisAngle(jaw.axis as Parameters<Quaternion['setFromAxisAngle']>[0], value * jaw.full)
      bone.quaternion.copy(jaw.rest).multiply(jaw.turn)
    }
  }
  apply()
  return {
    setContact(v) { contact = clamp01(v); apply() },
    setManual(v) { manual = clamp01(v); apply() },
    get value() { return value },
  }
}
