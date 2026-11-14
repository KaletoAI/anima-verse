/**
 * model3dModel — the pure helpers of the 3D tab (Task UI5, the tab checklist): the flow head's light and words,
 * the cost words of its local single steps and the extension groups only an outfit model carries. No React, no
 * fetch — scripts/check_model3d_ui.mjs bundles this file alone.
 */
import type { Light } from './hairstylesModel'

type Tr = (s: string) => string
const EN: Tr = (s) => s

/** What the flow head reads off GET …/model3d. */
export interface Model3DHeadInput {
  /** A model job runs for the character (`pending`, or the tab's own request). */
  pending: boolean
  hasModel: boolean
  rigError: boolean
  /** Another combination's model is served (pipeline `fallback`, or `match: nearest`). */
  standIn: boolean
  /** The served model is outdated (its freshness `stale`, or `stale_base`). */
  stale: boolean
}

/**
 * The flow head: a model job running → blue "Building now"; no model → yellow "Not built yet"; its rig failed →
 * red "Rig failed"; a stand-in served → yellow "Showing a stand-in"; outdated → yellow "Outdated"; else green
 * "Up to date" (in this order: what is running or missing outranks what is shown).
 */
export function model3dHead(s: Model3DHeadInput, t: Tr = EN): { light: Light; words: string } {
  if (s.pending) return { light: 'blue', words: t('Building now') }
  if (!s.hasModel) return { light: 'yellow', words: t('Not built yet') }
  if (s.rigError) return { light: 'red', words: t('Rig failed') }
  if (s.standIn) return { light: 'yellow', words: t('Showing a stand-in') }
  if (s.stale) return { light: 'yellow', words: t('Outdated') }
  return { light: 'green', words: t('Up to date') }
}

/** A local single step's button, its cost before the click: "Analyze — local, no hub job". */
export function localAction(label: string, t: Tr = EN): string {
  return `${t(label)} — ${t('local, no hub job')}`
}

/**
 * The extension groups the served outfit model carries that its base model does not (a part built only with this
 * outfit): their ids in the outfit's order. Null base groups (no base model stored) → none; a group id twice → once.
 */
export function outfitOnlyGroups(outfit: readonly string[], base: readonly string[] | null | undefined): string[] {
  if (!base) return []
  const known = new Set(base)
  return outfit.filter((id, index) => !known.has(id) && outfit.indexOf(id) === index)
}

/** The read-only line naming them (the 3D tab's Extension bones on the pipeline). */
export function outfitOnlyLine(ids: readonly string[], t: Tr = EN): string {
  if (!ids.length) return ''
  return t('Only on this outfit model: {ids} — built with the outfit; no switch for them, a character with a base '
    + 'body switches its extension bones on the base body').replace('{ids}', ids.join(', '))
}
