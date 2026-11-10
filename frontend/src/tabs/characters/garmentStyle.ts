/**
 * Shared styles, chip specs and helpers of the garment step views
 * (GarmentSteps, FieldHair, WardrobeGarment) — kept out of the component
 * modules so fast refresh keeps working.
 */
import type { CSSProperties } from 'react'
import type { GarmentImageInfo, GarmentInfo, GateLimit, GateRecord, RecordLimits, RunFeedback } from './useGarment'

export const TILE_HEIGHT = 200

export const EMPTY_TILE: CSSProperties = {
  width: '100%',
  height: TILE_HEIGHT,
  borderRadius: 6,
  border: '1px solid var(--border, #30363d)',
  background: 'rgba(255, 255, 255, 0.04)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  padding: 6,
  boxSizing: 'border-box',
}

export const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }
export const WARN_STYLE: CSSProperties = { color: 'var(--warning, #d29922)', overflowWrap: 'anywhere' }
export const ROW: CSSProperties = { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }

/** The warning of an own-mesh piece the outfit model is missing in outfit body mode mesh: no accepted fit
 *  yet, so it is never meshed into the outfit body (server `base_body.MESH_ITEM_NOT_READY`). */
export function meshNotReadyText(t: (key: string) => string, item: string, reason: string | null | undefined): string {
  return t('{item}: own mesh not ready — not shown until its mesh is accepted ({reason})')
    .replace('{item}', item).replace('{reason}', t(reason || ''))
}

/** The server's chip limits per step (`limits` of the info routes). */
export type GarmentLimits = Partial<Record<string, Record<string, GateLimit>>>

/** The body of POST /characters/{n}/garments/{item}/run. */
export interface GarmentRunBody { step?: string; view?: string; force?: boolean }

/** One chip: which number of a gate record, how it reads, how it scales.
 *  The limit itself always comes from the server. */
export interface ChipSpec {
  key: string
  label: string
  /** Multiplier for display (shares → %, metres → cm). */
  scale: number
  unit: string
  digits: number
  /** A boolean of the record that says whether this number is gated
   *  (false = reported only, e.g. `head_gated` of a piece worn on the head). */
  gatedKey?: string
}

export const MESH_CHIPS: ChipSpec[] = [
  { key: 'largest_component_share', label: 'Component share', scale: 100, unit: '%', digits: 1 },
]

export const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** A HairDeck fit attempt `{attempt, seed, ok, reasons, limits, metrics}`
 *  with its metrics lifted beside attempt/seed, so RecordNumbers lists them. */
export function flatFit(r: GateRecord | null | undefined): unknown {
  if (!r || typeof r.metrics !== 'object' || r.metrics === null) return r
  return { attempt: r.attempt, seed: r.seed, ...(r.metrics as object), reasons: r.reasons }
}

/** Whether `value` passes `limit` (`garment_gates.limits` semantics). */
export function passes(limit: GateLimit, value: number, height: number | null): boolean | null {
  const scaleH = (x: number) => (limit.per_height ? (height === null ? null : x * height) : x)
  if (limit.op === 'range') {
    const [lo, hi] = Array.isArray(limit.value) ? limit.value : [limit.value, limit.value]
    return value >= lo && value <= hi
  }
  const lim = scaleH(Array.isArray(limit.value) ? limit.value[0] : limit.value)
  if (lim === null) return null
  switch (limit.op) {
    case 'lt': return value < lim
    case 'le': return value <= lim
    case 'ge': return value >= lim
    case 'abs_le': return Math.abs(value) <= lim
    default: return null
  }
}

export function limitText(limit: GateLimit, spec: ChipSpec, height: number | null): string {
  const f = (x: number) => `${(x * spec.scale).toFixed(spec.digits)}${spec.unit ? ` ${spec.unit}` : ''}`
  if (limit.op === 'range') {
    const [lo, hi] = Array.isArray(limit.value) ? limit.value : [limit.value, limit.value]
    return `${f(lo)}–${f(hi)}`
  }
  const raw = Array.isArray(limit.value) ? limit.value[0] : limit.value
  const lim = limit.per_height ? (height === null ? null : raw * height) : raw
  if (lim === null) return ''
  const op = limit.op === 'lt' ? '<' : limit.op === 'le' ? '≤' : limit.op === 'ge' ? '≥' : '± ≤'
  return `${op} ${f(lim)}`
}

/** One chip of a gate record: the shown number, its limit text and whether
 *  it passes (null = reported only / not computable). */
export interface ChipResult { key: string; label: string; shown: string; lim: string; ok: boolean | null }

/** The chips of `record` under `specs` and the server's `limits` — the
 *  numbers GateChips shows and the tile status icon sums up. */
export function chipResults(specs: ChipSpec[], record: Record<string, unknown> | null | undefined,
  limits: Record<string, GateLimit> | undefined, view?: string): ChipResult[] {
  if (!record) return []
  const height = num(record.H)
  const out: ChipResult[] = []
  for (const spec of specs) {
    const value = num(record[spec.key])
    const gated = !(spec.gatedKey && record[spec.gatedKey] === false)
    const general = gated ? limits?.[spec.key] : undefined
    // A record that carries its own limit (record_key) is judged by it.
    const own = general?.record_key ? num(record[general.record_key]) : null
    const limit = general && own !== null ? { ...general, value: own } : general
    // A limit gated on other views only (the chest on the back) is not shown.
    if (limit?.views && view && !limit.views.includes(view)) continue
    if (value === null) continue
    out.push({
      key: spec.key,
      label: spec.label,
      shown: `${(value * spec.scale).toFixed(spec.digits)}${spec.unit ? ` ${spec.unit}` : ''}`,
      lim: limit ? limitText(limit, spec, height) : '',
      ok: limit ? passes(limit, value, height) : null,
    })
  }
  return out
}

/** The record the tile's chips show: the accepted final's (last of its
 *  attempts), else the newest refused attempt's. */
export function shownRecord(img: GarmentImageInfo | undefined): GateRecord | null {
  if (!img) return null
  const finals = img.gates ? Object.values(img.gates) : []
  if (finals.length) return finals[finals.length - 1]
  const last = img.attempts?.[img.attempts.length - 1]
  return last?.gate ?? null
}

export function upscaleText(upscale: Record<string, unknown> | null | undefined, t: (s: string) => string): string {
  const status = String(upscale?.status || '')
  if (status === 'applied') {
    const scale = num(upscale?.scale)
    const backend = upscale?.backend ? String(upscale.backend) : ''
    return `${t('Upscaled')}${scale ? ` ×${scale}` : ''}${backend ? ` (${backend})` : ''}`
  }
  if (status === 'lanczos') return t('Lanczos only (upscale failed)')
  if (status === 'not_needed') return t('No upscale needed')
  return ''
}


/** "Queued behind <item> · position n" of an item whose run waits in the
 *  character's garment queue: the item in flight and the place from the
 *  polled info (`queue_running` / `queue_position`), else from the start
 *  answer, else the overview's running pieces; item ids shown by name. */
export function queueText(garment: GarmentInfo | null | undefined, fb: RunFeedback | undefined,
  stepLabels: Record<string, string>, t: (s: string) => string): string {
  const name = (id: string) => fb?.names[id] || id
  const ahead = garment?.queue_running
    ? [name(garment.queue_running)]
    : fb?.queue?.behind.length
      ? fb.queue.behind.map(name)
      : (fb?.others || []).map((o) => `${o.name} (${t(stepLabels[o.step || ''] || o.step || '')})`)
  let text = ahead.length ? t('Queued behind {items}').replace('{items}', ahead.join(', ')) : t('Queued')
  const position = garment?.queue_position ?? fb?.queue?.position ?? null
  if (position) text += ` · ${t('position {n}').replace('{n}', String(position))}`
  return text
}

/** A record's limits `{key: ["max" | "min", v]}` as chip limits; undefined without any. */
export function recordLimits(raw: RecordLimits | null | undefined): Record<string, GateLimit> | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const out: Record<string, GateLimit> = {}
  for (const [key, pair] of Object.entries(raw)) {
    if (!Array.isArray(pair) || typeof pair[1] !== 'number') continue
    out[key] = { op: pair[0] === 'min' ? 'ge' : 'le', value: pair[1] }
  }
  return Object.keys(out).length ? out : undefined
}
