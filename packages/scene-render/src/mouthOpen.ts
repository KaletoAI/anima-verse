/**
 * THE OPEN MOUTH (Ruling A203). A body whose mouth channel was built (`app/blender/scripts/mouth_part.py`) carries
 * the morph target `mouth_open` (0 = closed, lips meeting; 1 = the jaw fully open): the lower lip, the chin and the
 * channel's lower wall turn about the jaw's hinge, the upper lip lifts. One number drives it, from two sources:
 *
 * - CONTACT: a partner's chain engaged in the figure's mouth channel opens it as far as the entering part needs —
 *   `mouthOpenFor(radius, openHeight)` = (2 · radius + `MOUTH_OPEN_MARGIN_M`) / openHeight, clamped to [0, 1], with
 *   `radius` the occupant's largest segment radius × its engagement weight w (the same value the opening pass
 *   widens the surface to, `channelOpening.ts`) and `openHeight` the height of the opening at `mouth_open` 1 as the
 *   build measured it (the channel record's `open_height`). The surface pass still runs on top and shapes the lips
 *   around the part.
 * - MANUAL: `setManual` (a preview slider, an expression) — the larger of the two applies.
 *
 * `bindMouthOpen` finds every skinned mesh of an instance that carries the target; null when none does (a body
 * built before A203, or one whose build found no lip line), and nothing is driven.
 */
import type { Object3D, SkinnedMesh } from 'three'

/** The morph target's name (the Blender shape key, the glTF `targetNames` entry). */
export const MOUTH_OPEN_TARGET = 'mouth_open'
/** Room around an entering part: the opening's height is its diameter plus this (metres). */
export const MOUTH_OPEN_MARGIN_M = 0.004

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

/** Bind the `mouth_open` target of `instance` (module docstring). Null when no mesh carries it. */
export function bindMouthOpen(instance: Object3D): MouthOpen | null {
  const slots: { mesh: SkinnedMesh; index: number }[] = []
  instance.traverse(o => {
    const mesh = o as SkinnedMesh
    const index = mesh.morphTargetDictionary?.[MOUTH_OPEN_TARGET]
    if (mesh.morphTargetInfluences && index !== undefined) slots.push({ mesh, index })
  })
  if (!slots.length) return null
  let contact = 0, manual = 0, value = 0
  const apply = () => {
    value = Math.max(contact, manual)
    for (const s of slots) s.mesh.morphTargetInfluences![s.index] = value
  }
  apply()
  return {
    setContact(v) { contact = clamp01(v); apply() },
    setManual(v) { manual = clamp01(v); apply() },
    get value() { return value },
  }
}
