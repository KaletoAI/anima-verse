/**
 * The extension groups of the SHOWN model in plain words (Ruling A64) — the line the 3D tab's viewer writes beside
 * its toggles (the Figure tab's viewer shows none since Ruling A73), so a missing group is never a mystery: which groups carry bones on this model,
 * which are covered by a worn piece (correct: a covered slot has no part and no bones), which are missing and why.
 *
 * Server: `model3d.extension_presence` — the 3D tab's `model.extension_presence`. The server's English sentences are translated here (de.json keys).
 */
import type { Light } from './hairstylesModel'

type Tr = (s: string) => string
const EN: Tr = (s) => s

export interface ExtensionMissing {
  id: string
  light: Light
  /** "Covered" · "Not built" · "Due" · "Failed" · "Off". */
  state: string
  /** The plain sentence; "{pieces}" is filled with `pieces`. */
  reason: string
  /** The record's own reason (mouse-over). */
  detail: string
  /** The worn pieces that cover the group's slot (names). */
  pieces: string[]
}

export interface ExtensionPresence {
  built: string[]
  missing: ExtensionMissing[]
  /** Package groups that do not apply to this character. */
  not_declared: string[]
}

/** One line of the note: its light (null = no light) and its words. */
export interface PresenceLine { light: Light | null; text: string; title?: string }

/** The note's lines, or [] when there is nothing to say (no payload, or no group anywhere). */
export function presenceLines(p: ExtensionPresence | null | undefined, t: Tr = EN): PresenceLine[] {
  if (!p || (!p.built?.length && !p.missing?.length && !p.not_declared?.length)) return []
  const lines: PresenceLine[] = []
  lines.push(p.built.length
    ? { light: 'green', text: t('Extension bones on this model: {ids}').replace('{ids}', p.built.join(', ')) }
    : { light: null, text: t('Extension bones: none on this model') })
  for (const m of p.missing) {
    const reason = t(m.reason).replace('{pieces}', m.pieces.join(', '))
    lines.push({ light: m.light, text: `${m.id}: ${t(m.state)} — ${reason}`, title: m.detail || undefined })
  }
  if (p.not_declared.length) {
    lines.push({ light: null, text: t('Not declared for this character: {ids}').replace('{ids}', p.not_declared.join(', ')) })
  }
  return lines
}
