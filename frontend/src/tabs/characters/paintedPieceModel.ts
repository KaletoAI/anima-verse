/**
 * paintedPieceModel — the pure rules of the painted piece dialog (Ruling A148, PaintedPieceDialog): the payload of
 * GET /characters/{c}/figure/painted/{item} (`app/core/painted_piece.py`), each row's light, the "Paint now" button
 * and the head's next-step line (the A140 rules: an enabled button or a visible reason, never a tooltip alone).
 * Strings are English keys for `t()`.
 */
import type { Light } from './hairstylesModel'

export interface PaintedColour { hex: string; strength: number }
export interface PaintedPieceInfo {
  item_id: string
  name: string
  slots: string[]
  regions: string[]
  margin_mm: number
  worn: boolean
  mode: string
  painted: boolean
  signature: string
  texture_key: string
  shared_with: { item_id: string; name: string }[]
  colour: PaintedColour & { presets: { hex: string; name: string }[]; applied: PaintedColour | null }
  build_running: boolean
  region_url: string
  preview_url: string
  note: string
  views?: { view: string; state: 'current' | 'missing'; reason: string; built_at: string | null; jobs: number }[]
  texture?: { state: 'current' | 'colour_due' | 'due' | 'left_out'; reason: string; key: string;
    built_at: string | null; reused: boolean; proof: { texels?: number; delta_e_after?: number } | null }
  paint?: { cpu_steps: string[]; hub_steps: string[]; hub_jobs: number }
  assembly?: { state: 'current' | 'due'; reason: string; built_at: string | null }
}

export const PAINT_NOW = 'Paint now (CPU, 0 hub jobs)'
export const PAINT_WAITS_BUILD = 'Waits for the running Build — it paints too'
export const PAINT_NEEDS_HUB = 'Needs hub work first: {steps} ({cost}) — Build runs it'
export const PAINT_CURRENT = 'The painted texture is current'
export const NEXT_PAINT = 'Next: Paint (CPU, 0 hub jobs) — Paint now below, or the Build'
export const NEXT_HUB = 'Next: {steps} · {cost} — the Build runs it'

/** The light of a row: running Build = blue on what is not current. */
export function rowLight(state: string, buildRunning: boolean): Light {
  if (state === 'current') return 'green'
  if (buildRunning) return 'blue'
  return 'yellow'
}

/** "Paint now": enabled only when the plan's work is CPU only. `cost` renders hub jobs. */
export function paintGate(info: PaintedPieceInfo | null | undefined, cost: (n: number) => string):
  { disabled: boolean; reason: string; vars: Record<string, string> } {
  const p = info?.paint
  if (!info || !p) return { disabled: true, reason: '', vars: {} }
  if (info.build_running) return { disabled: true, reason: PAINT_WAITS_BUILD, vars: {} }
  if (p.hub_steps.length) {
    return { disabled: true, reason: PAINT_NEEDS_HUB, vars: { steps: p.hub_steps.join('; '), cost: cost(p.hub_jobs) } }
  }
  if (!p.cpu_steps.length) return { disabled: true, reason: PAINT_CURRENT, vars: {} }
  return { disabled: false, reason: '', vars: {} }
}

/** The head's line: what is next and what it costs. */
export function paintNextLine(info: PaintedPieceInfo | null | undefined, cost: (n: number) => string):
  { key: string; vars: Record<string, string> } | null {
  const p = info?.paint
  if (!p) return null
  if (p.hub_steps.length) return { key: NEXT_HUB, vars: { steps: p.hub_steps.join(' → '), cost: cost(p.hub_jobs) } }
  if (p.cpu_steps.length) return { key: NEXT_PAINT, vars: {} }
  return { key: 'Everything is current', vars: {} }
}

/** Whether the colour row's draft differs from what is stored. */
export function colourDirty(draft: PaintedColour | null, stored: PaintedColour): boolean {
  if (!draft) return false
  return draft.hex !== stored.hex || Math.abs(draft.strength - stored.strength) > 1e-6
}

export function fill(text: string, vars: Record<string, string>): string {
  return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), text)
}
