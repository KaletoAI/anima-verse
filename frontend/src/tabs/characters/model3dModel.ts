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

/** Whether the 3D tab has an "Extension bones" sub-tab (Ruling A66): only OFF the base-body pipeline (an animal, a
 *  temporary NPC — the served model's own box) and only when that model carries extension groups. On the pipeline the
 *  groups, their switches and the state preview live in the Base body tab (Ruling A45), so the 3D tab has none. */
export function hasExtensionSection(st: { pipeline?: unknown; extension_groups?: readonly unknown[] }): boolean {
  return !st.pipeline && !!st.extension_groups?.length
}
