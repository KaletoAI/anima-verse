/**
 * Shared styles, chip specs and helpers of the garment step views
 * (GarmentSteps, WardrobeGarment, HairstyleParts) — kept out of the component
 * modules so fast refresh keeps working.
 */
import type { CSSProperties } from 'react'
import type { Freshness } from './FreshnessBadge'
import type {
  AttemptUsePlan, FootwearInfo, FromWornNumbers, GarmentImageInfo, GarmentRunState, GateLimit, GateRecord,
  PieceViewDue, PieceViewInfo, PieceViewOption, PieceViewSource, RecordLimits, RunFeedback,
} from './useGarment'

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
/** POST …/garments/{item}/run. With a `step`: only that step (the steps dialog's buttons), unless `chain` — then
 *  the chain from it (Re-render, the hair's Regenerate, footwear). Without one: the chain from the first missing step.
 *  With a `view` (Ruling A33): that view of the step alone; a view it needs that is not accepted is a 409 before
 *  anything is spent, unless `prerequisites` — the button's explicit "first" action — lets the run make it first. */
export interface GarmentRunBody {
  step?: string; view?: string; force?: boolean; chain?: boolean; prerequisites?: boolean
  /** Ruling A50: with step "fit", the body shape the Re-fit fits on (an outfit body id); absent = the plain body. */
  body?: string
}

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

/** The HairDeck fit's chips (the Hairstyles tab). */
export const HAIRDECK_FIT_CHIPS: ChipSpec[] = [
  { key: 'max_push_m', label: 'Max push', scale: 100, unit: 'cm', digits: 1 },
  { key: 'moved_share', label: 'Moved', scale: 100, unit: '%', digits: 1 },
  { key: 'icp_resid_p95_m', label: 'Head match (p95)', scale: 1000, unit: 'mm', digits: 1 },
  // Reported, not gated.
  { key: 'icp_scale', label: 'Scale', scale: 1, unit: '', digits: 3 },
  { key: 'cap_tris', label: 'Scalp cap triangles', scale: 1, unit: '', digits: 0 },
  { key: 'forward_m', label: 'Forward shift', scale: 1000, unit: 'mm', digits: 1 },
  { key: 'tilt_deg', label: 'Forward tilt', scale: 1, unit: '°', digits: 1 },
  { key: 'width_scale', label: 'Hair width', scale: 1, unit: '×', digits: 2 },
]

/** The step names of a hair chain (`garment_store.steps_for` of HairDeck). */
export const HAIR_STEP_LABELS: Record<string, string> = {
  queued: 'Queued',
  hairdeck: 'HairDeck',
  haar: 'HAAR strands',
  fit: 'Fit',
}

/** The step names of a footwear piece (FootwearSteps, the dialog's run status line). */
export const FOOTWEAR_STEP_LABELS: Record<string, string> = {
  queued: 'Queued',
  source: 'Item image',
  empty: 'Empty shoe',
  cutout: 'Cut-out',
  mesh: 'Mesh',
  insole: 'Insole',
  fit: 'Fit',
}

/** What a footwear step costs when it runs (the shoe source is shared by every wearer). */
const FOOTWEAR_STEP_COST: Record<string, string> = {
  source: 'upscale job when small',
  empty: 'hub image job',
  cutout: 'local',
  mesh: 'hub mesh job',
  insole: 'local',
  fit: 'local',
}

/** "Runs: Empty shoe (hub image job), Mesh (hub mesh job), Insole (local)" — the steps a default run
 *  (POST …/run {}) of a footwear piece runs, read off the server's step list in its order: every step
 *  that is not accepted or whose freshness is stale (the fit while it is still `pending` runs nothing);
 *  '' when nothing would run. */
export function footwearRunPlan(info: FootwearInfo, t: (s: string) => string): string {
  const parts: string[] = []
  for (const [step, data] of Object.entries(info.steps || {})) {
    if (!data) continue
    if (step === 'fit' && (data as { pending?: boolean }).pending) continue
    const stale = (data as { freshness?: { state?: string } | null }).freshness?.state === 'stale'
    if (data.status === 'accepted' && !stale) continue
    const cost = FOOTWEAR_STEP_COST[step]
    parts.push(`${t(FOOTWEAR_STEP_LABELS[step] || step)}${cost ? ` (${t(cost)})` : ''}`)
  }
  return parts.length ? t('Runs: {steps}').replace('{steps}', parts.join(', ')) : ''
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
export interface ChipResult {
  key: string
  label: string
  shown: string
  lim: string
  ok: boolean | null
  /** The record carries the key with a null value: the measure could not be taken on this
   *  fit (footwear_fit: a boot shaft with no ring above the band) — shown as "n/a", never
   *  as a passing number. */
  na?: boolean
  /** Ruling A46c: the limit only warns (`GateLimit.warn`) — beyond it the gate does not refuse. */
  warn?: boolean
}

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
    if (value === null) {
      if (!(spec.key in record) || record[spec.key] !== null) continue
      out.push({ key: spec.key, label: spec.label, shown: 'n/a', lim: limit ? limitText(limit, spec, height) : '', ok: null, na: true })
      continue
    }
    out.push({
      key: spec.key,
      label: spec.label,
      shown: `${(value * spec.scale).toFixed(spec.digits)}${spec.unit ? ` ${spec.unit}` : ''}`,
      lim: limit ? limitText(limit, spec, height) : '',
      ok: limit ? passes(limit, value, height) : null,
      ...(limit?.warn ? { warn: true } : {}),
    })
  }
  return out
}

/** Ruling A46c: the light of a gate record. `refused` — what the gate refuses: a gated chip beyond its limit, a
 *  reason, or `ok` false; `warned` — the gate passes it, but a chip whose limit only warns (`warn`, the
 *  registration caps) is beyond it; `passed` — a gated chip passes and nothing warns; `info` — numbers only. */
export type LightState = 'refused' | 'warned' | 'passed' | 'info'

export interface GateLight {
  state: LightState
  chips: ChipResult[]
  reasons: string[]
}

export function gateLight(specs: ChipSpec[], record: Record<string, unknown> | null | undefined,
  limits: Record<string, GateLimit> | undefined, view?: string): GateLight {
  const chips = chipResults(specs, record, limits, view)
  const raw = (record as GateRecord | null | undefined)?.reasons
  const reasons = Array.isArray(raw) ? (raw as string[]) : []
  const refused = chips.some((c) => c.ok === false && !c.warn) || reasons.length > 0
    || (record as GateRecord | null | undefined)?.ok === false
  const warned = !refused && chips.some((c) => c.ok === false && c.warn)
  const state: LightState = refused ? 'refused' : warned ? 'warned'
    : chips.some((c) => c.ok === true) ? 'passed' : 'info'
  return { state, chips, reasons }
}

/** The warnings of a light in plain words: per chip beyond a limit that only warns, what it is and that the gate
 *  does not refuse for it; a registration cap (`reg_*`) also says what that meant for the image. */
export function warningLines(light: GateLight, t: (s: string) => string): string[] {
  const out: string[] = []
  for (const c of light.chips) {
    if (c.ok !== false || !c.warn) continue
    out.push(t('{label} {value} is outside {limit}: a warning, the gate does not refuse for it')
      .replace('{label}', t(c.label)).replace('{value}', c.shown).replace('{limit}', c.lim))
    if (c.key.startsWith('reg_')) {
      out.push(t('The image was not moved onto the worn view; the gate measured it as rendered.'))
    }
  }
  return out
}

/** Ruling A46c: the chips that apply to an image made from `source` — a chip whose limit is `generated_only` (the
 *  registration of a generated ghost onto the worn view) never applies to one made from the worn view. */
export function chipsForSource(specs: ChipSpec[], limits: Record<string, GateLimit> | undefined,
  source: PieceViewSource | null | undefined): ChipSpec[] {
  return source === 'worn' ? specs.filter((s) => !limits?.[s.key]?.generated_only) : specs
}

/** Ruling A46c: what drives a piece-only cell — the image in use for the view. `image`: the accepted image was
 *  made from the source the view resolves to (or no source is resolved, or the view is being re-checked under
 *  the current gate, A46b) — it drives the light. `pending`: the accepted image was made from the OTHER source
 *  and is due to be made again from `source` — no image drives the cell, its light is information only, and the
 *  accepted image shows as a small tile ("To be replaced"). */
export function pieceCellMode(img: GarmentImageInfo | undefined, pieceView: PieceViewInfo | undefined,
  checking: boolean): 'image' | 'pending' {
  if (!img?.url || !pieceView || checking || !pieceView.made_from || !pieceView.source) return 'image'
  return pieceView.made_from === pieceView.source ? 'image' : 'pending'
}

/** The light's lines of a piece-only view made from the worn view (Ruling A46c): its mask numbers — coverage,
 *  holes filled, skin removed — and whether the pair agrees (`pair` of the garment, its pair step's views). */
export function fromWornLines(numbers: FromWornNumbers | null | undefined,
  pair: { step: string; agree: boolean } | null | undefined, t: (s: string) => string): string[] {
  if (!numbers) return []
  const share = num(numbers.piece_share)
  const holes = num(numbers.holes_filled)
  const skin = num(numbers.skin_removed_px)
  return [
    share !== null ? t('Piece: {pct} % of the figure').replace('{pct}', (share * 100).toFixed(1)) : '',
    holes !== null ? t('Holes filled: {n}').replace('{n}', String(holes)) : '',
    numbers.skin_removed ? t('Skin areas kept: the piece has the skin’s colour')
      : skin !== null ? t('Skin areas removed: {n} px').replace('{n}', skin.toLocaleString('en-US')) : '',
    pair && pair.step === 'ghost'
      ? (pair.agree ? t('Matches the other view') : t('Does not match the other view')) : '',
  ].filter(Boolean)
}

/** Ruling A46c: the tile meta beside a light — "current" never stands beside a refusal: a refused image keeps
 *  its stale/no-data badge, a current one shows none (the light and the Refused badge say what it is). */
export function metaBesideLight<T extends { freshness?: Freshness | null }>(meta: T, state: LightState): T {
  return state === 'refused' && meta.freshness?.state === 'current' ? { ...meta, freshness: null } : meta
}

/** One small attempt tile of a cell (AttemptThumbs). `note` replaces "Use this" (the image the view no longer
 *  uses, Ruling A46c). */
export interface AttemptTile {
  key: string
  attempt: number
  gate: GateRecord | null
  url: string
  note?: string
  noteTitle?: string
  /** The accepted image itself (no attempt file holds its bytes): named "Accepted", not by its attempt. */
  accepted?: boolean
}

/** The attempt tiles of an image cell (Ruling A46c): every stored attempt, the one in use (`uses[n].in_use`: the
 *  accepted file's bytes) judged by the accepted image's NEWEST record — a re-gate (A46b) writes the final's
 *  record only, so its old attempt sidecar may still read "passed". `replaced` (a pending piece-only cell): the
 *  accepted image is not used any more — the attempt in use carries the note, and without one in use the
 *  accepted image becomes a tile of its own. */
export function attemptTiles(img: GarmentImageInfo | undefined, uses: Record<string, AttemptUsePlan> | undefined,
  replaced?: { note: string; title: string }): AttemptTile[] {
  if (!img) return []
  const finals = img.gates ? Object.values(img.gates) : []
  const finalRecord = finals.length ? finals[finals.length - 1] : null
  const inUse = Object.entries(uses || {}).find(([, p]) => p.in_use)?.[0]
  const tiles: AttemptTile[] = (img.attempts || []).map((a) => {
    const used = inUse === String(a.attempt)
    return {
      key: `attempt-${a.attempt}`, attempt: a.attempt, url: a.url,
      gate: used && finalRecord ? finalRecord : a.gate,
      ...(used && replaced ? { note: replaced.note, noteTitle: replaced.title } : {}),
    }
  })
  if (replaced && img.url && inUse === undefined) {
    tiles.unshift({ key: 'accepted', attempt: num(finalRecord?.attempt) ?? 0, url: img.url, gate: finalRecord,
      note: replaced.note, noteTitle: replaced.title, accepted: true })
  }
  return tiles
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
 *  answer, else the overview's running pieces; item ids shown by name.
 *  A CPU refit running beside the queue (`queue_beside`, Ruling A30) waits
 *  behind nothing: "Starting…" until its fit step shows. */
export function queueText(garment: GarmentRunState | null | undefined, fb: RunFeedback | undefined,
  stepLabels: Record<string, string>, t: (s: string) => string): string {
  if (garment?.queue_beside && !garment.queue_position) return t('Starting…')
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

/** Ruling A46: the reasons of the piece-only view's source (`garment_from_worn.REASONS`, same keys and words). */
const PIECE_VIEW_REASONS: Record<string, string> = {
  set_generated: 'Generated: you chose the image edit (the body removed by the edit model)',
  set_worn: 'From the worn view: you chose it (the worn view minus the body, no hub job)',
  loose: 'Auto → Generated: a loose piece — the body hides parts of it in the worn view (the inside at the neck, sleeves or hem), only the edit draws them',
  by_hand: 'Auto → Generated: you took this attempt with “Use this”',
  added: 'Auto → From the worn view: the generated view adds a part the worn piece does not have',
  refused: 'Auto → From the worn view: the generated view was refused',
  passes: 'Auto → Generated: a close-fitting piece — the edit is used while it passes its gate; refused, the view is made from the worn view',
}

export const PIECE_VIEW_SOURCE: Record<string, string> = { generated: 'Generated', worn: 'From the worn view' }
/** The light's line on the accepted image's source. */
export const PIECE_VIEW_MADE: Record<string, string> = {
  generated: 'Made by the image edit', worn: 'Made from the worn view minus the body',
}
export const PIECE_VIEW_FROM: Record<string, string> = {
  generated: 'the image edit', worn: 'the worn view minus the body',
}

/** The reason of a source in the UI language; a reach (`added`) reads as a share of the figure height. */
export function pieceViewReason(o: Pick<PieceViewOption, 'why' | 'detail' | 'reason'>,
  t: (s: string) => string): string {
  const base = PIECE_VIEW_REASONS[o.why]
  if (!base) return o.reason
  if (!o.detail) return t(base)
  const reach = Number(o.detail)
  return o.why === 'added' && Number.isFinite(reach)
    ? `${t(base)} (${t('it reaches {pct} % of the figure height past it').replace('{pct}', (reach * 100).toFixed(1))})`
    : `${t(base)}: ${o.detail}`
}

/** What a source change makes due, in words: "piece-only view: no hub job · cut-out: 1 hub job · …". */
export function pieceViewDueText(due: PieceViewDue[], t: (s: string) => string): string {
  return due.map((d) => {
    const word = d.step === 'ghost' ? t('piece-only view') : d.step === 'cutout' ? t('cut-out')
      : d.step === 'mesh' ? t('mesh') : t('fit')
    return `${word}: ${d.step === 'fit' ? t('on the CPU') : (d.jobs === 0 ? t('no hub job') : d.jobs === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(d.jobs)))}`
  }).join(' · ')
}
