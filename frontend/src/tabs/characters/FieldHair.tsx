/**
 * FieldHair — the Hair tab: the character's hair as its own mesh (plan
 * docs/superpowers/plans/2026-11-09-base-body-phase4-hair.md). The hair
 * item is a garment worn in the `hair` mesh slot; its chain renders the
 * base views with hair (haired), the hair alone (hair-only / ghost), squares
 * them into cut-outs, builds and decimates a mesh, and fits it onto the
 * rigged base model. Every step is gated; the tab shows each step's numbers
 * against the server's limits so a refusal is visible, never silent.
 *
 * Backend (app/routes/characters.py, app/core/garments.py):
 * GET /characters/{n}/hair (polled while a step runs — useGarment),
 * POST /characters/{n}/hair (create + wear the item, start the chain),
 * POST /characters/{n}/hair/equipped {equipped},
 * POST /characters/{n}/garments/{item}/run {step?, view?, force?}
 * (409 while a garment run of the character goes).
 *
 * The hair description is DERIVED from Appearance (R3) — read-only here.
 * Changing it does not start GPU work (R14): the tab shows "Hair description
 * changed" and the old hair stays served until Regenerate.
 *
 * Two hair methods (plan docs/superpowers/plans/2026-11-09-hairdeck-hair.md,
 * Task 5): the edit chain above, or HairDeck (the profile picture -> hair
 * cards in one Hub call -> fit). The method selector at the top stores the
 * character's choice (POST /characters/{n}/hair/method, "" = world default);
 * the selected method's section is shown, the other method's last result is
 * collapsed below ("Other method"). A switch generates nothing. The HairDeck
 * colour (POST /characters/{n}/hair/colour) and the placement (POST
 * /characters/{n}/hair/placement {forward_m, tilt_deg}, null = automatic)
 * only re-fit from the stored HairDeck result.
 */
import { useCallback, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { Model3DViewer } from './Model3DViewer'
import { RefImage } from './RefImage'
import { GARMENT_VIEWS, garmentRunning, useGarment } from './useGarment'
import type {
  GarmentImageInfo, GarmentImageStep, GarmentInfo, GarmentView, GateLimit, GateRecord, HairDeckPanel, HairInfo,
  HairMethod, HairPlacement, OtherMethodInfo,
} from './useGarment'

const TILE_HEIGHT = 200

const EMPTY_TILE: CSSProperties = {
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

const ERROR_STYLE: CSSProperties = { color: 'var(--danger, #f85149)', overflowWrap: 'anywhere' }
const WARN_STYLE: CSSProperties = { color: 'var(--warning, #d29922)', overflowWrap: 'anywhere' }
const ROW: CSSProperties = { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }

const STEP_LABELS: Record<string, string> = {
  queued: 'Queued',
  haired: 'Haired views',
  ghost: 'Hair-only views',
  cutout: 'Cut-outs',
  mesh: 'Mesh',
  hairdeck: 'HairDeck',
  fit: 'Fit',
}

const METHOD_LABELS: Record<HairMethod, string> = {
  edit_chain: 'Edit chain',
  hairdeck: 'HairDeck',
}

const HAIRDECK_STATUS: Record<string, string> = {
  accepted: 'Accepted',
  refused: 'Refused',
  missing: 'Not run yet',
}

const HAIRDECK_TILES: Array<['input' | 'prep' | 'model_input', string]> = [
  ['input', 'Input (profile picture)'],
  ['prep', 'Prepared'],
  ['model_input', 'Model input'],
]

const STALE_LABELS: Record<string, string> = {
  description_changed: 'Hair description changed',
  base_changed: 'Base body changed',
  base_model_changed: 'Base model changed',
  hairdeck_changed: 'Profile picture or HairDeck settings changed',
  colour_changed: 'Hair colour changed',
  placement_changed: 'Hair placement changed',
}

const FIT_STATUS: Record<string, string> = {
  accepted: 'Accepted',
  stale: 'Fitted on an older base model',
  outdated: 'Fitted from a replaced mesh',
  missing: 'Not fitted yet',
}

/** One chip: which number of a gate record, how it reads, how it scales.
 *  The limit itself always comes from the server (`HairInfo.limits`). */
interface ChipSpec {
  key: string
  label: string
  /** Multiplier for display (shares → %, metres → cm). */
  scale: number
  unit: string
  digits: number
}

const HAIRED_CHIPS: ChipSpec[] = [
  { key: 'body_xor', label: 'Body change', scale: 100, unit: '%', digits: 2 },
  { key: 'body_dRGB', label: 'Colour change', scale: 1, unit: '', digits: 2 },
  { key: 'chest_dRGB', label: 'Chest', scale: 1, unit: '', digits: 2 },
]

const GHOST_CHIPS: ChipSpec[] = [
  { key: 'top_dy', label: 'Top offset', scale: 1, unit: 'px', digits: 0 },
  { key: 'centre_dx', label: 'Centre offset', scale: 1, unit: 'px', digits: 1 },
  { key: 'w_ratio', label: 'Width ratio', scale: 1, unit: '', digits: 3 },
  { key: 'body_left', label: 'Body left', scale: 100, unit: '%', digits: 2 },
]

const MESH_CHIPS: ChipSpec[] = [
  { key: 'largest_component_share', label: 'Component share', scale: 100, unit: '%', digits: 1 },
]

const FIT_CHIPS: ChipSpec[] = [
  { key: 'bib_cm2', label: 'Bib', scale: 1, unit: 'cm²', digits: 1 },
  { key: 'poke_share', label: 'Crown poke', scale: 100, unit: '%', digits: 2 },
  { key: 'scalp_uncovered_share', label: 'Scalp uncovered', scale: 100, unit: '%', digits: 1 },
  { key: 'max_push_m', label: 'Max push', scale: 100, unit: 'cm', digits: 1 },
  { key: 'moved_share', label: 'Moved', scale: 100, unit: '%', digits: 1 },
  { key: 'largest_component_share', label: 'Largest part', scale: 100, unit: '%', digits: 1 },
  // Reported, not gated (R7): its plausible range depends on the hair length.
  { key: 'drop_below_chin_m', label: 'Drop below chin', scale: 100, unit: 'cm', digits: 1 },
]

const HAIRDECK_FIT_CHIPS: ChipSpec[] = [
  { key: 'max_push_m', label: 'Max push', scale: 100, unit: 'cm', digits: 1 },
  { key: 'moved_share', label: 'Moved', scale: 100, unit: '%', digits: 1 },
  { key: 'icp_resid_p95_m', label: 'Head match (p95)', scale: 1000, unit: 'mm', digits: 1 },
  // Reported, not gated.
  { key: 'icp_scale', label: 'Scale', scale: 1, unit: '', digits: 3 },
  { key: 'cap_tris', label: 'Scalp cap triangles', scale: 1, unit: '', digits: 0 },
  { key: 'forward_m', label: 'Forward shift', scale: 1000, unit: 'mm', digits: 1 },
  { key: 'tilt_deg', label: 'Forward tilt', scale: 1, unit: '°', digits: 1 },
]

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** Whether `value` passes `limit` (`garment_gates.limits` semantics). */
function passes(limit: GateLimit, value: number, height: number | null): boolean | null {
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

function limitText(limit: GateLimit, spec: ChipSpec, height: number | null): string {
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

function GateChips({ specs, record, limits, view }: {
  specs: ChipSpec[]
  record: Record<string, unknown> | null | undefined
  limits: Record<string, GateLimit> | undefined
  view?: string
}) {
  const { t } = useI18n()
  if (!record) return null
  const height = num(record.H)
  const chips: ReactNode[] = []
  for (const spec of specs) {
    const value = num(record[spec.key])
    const limit = limits?.[spec.key]
    // A limit gated on other views only (the chest on the back) is not shown.
    if (limit?.views && view && !limit.views.includes(view)) continue
    if (value === null) continue
    const ok = limit ? passes(limit, value, height) : null
    const color = ok === null ? 'var(--border, #30363d)' : ok ? 'var(--success, #3fb950)' : 'var(--danger, #f85149)'
    const shown = `${(value * spec.scale).toFixed(spec.digits)}${spec.unit ? ` ${spec.unit}` : ''}`
    const lim = limit ? limitText(limit, spec, height) : ''
    chips.push(
      <span
        key={spec.key}
        title={lim ? `${t('Limit')}: ${lim}` : t('Reported, not gated')}
        style={{
          display: 'inline-block',
          padding: '1px 6px',
          borderRadius: 10,
          border: `1px solid ${color}`,
          color: ok === false ? 'var(--danger, #f85149)' : undefined,
          fontSize: '0.85em',
          whiteSpace: 'nowrap',
        }}
      >
        {t(spec.label)} {shown}{lim ? ` (${lim})` : ''}
      </span>,
    )
  }
  if (!chips.length) return null
  return <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>{chips}</div>
}

/** Every number and reason of one gate record — the generic list for
 *  refused attempts (both attempts' numbers, plan review focus 5). */
function RecordNumbers({ label, record }: { label: string; record: unknown }) {
  if (!record || typeof record !== 'object') return null
  const rec = record as GateRecord
  const numbers = Object.entries(rec)
    .filter(([, v]) => typeof v === 'number')
    .map(([k, v]) => `${k} ${Number.isInteger(v) ? v : (v as number).toFixed(4)}`)
  const reasons = Array.isArray(rec.reasons) ? rec.reasons : []
  return (
    <div className="ga-hint" style={{ overflowWrap: 'anywhere' }}>
      <strong>{label}</strong>{numbers.length ? ` — ${numbers.join(' · ')}` : ''}
      {reasons.map((r) => <div key={r} style={ERROR_STYLE}>{r}</div>)}
    </div>
  )
}

/** The gate records of a failure, labelled: per attempt, per view (the
 *  front/back bottoms check) or the fit's single record. */
function failureRecords(gates: Record<string, unknown> | null, t: (s: string) => string): Array<[string, unknown]> {
  if (!gates) return []
  if (Array.isArray(gates.attempts)) {
    return (gates.attempts as GateRecord[]).map((r, i) => [`${t('Attempt')} ${num(r?.attempt) ?? i + 1}`, flatFit(r)])
  }
  if (gates.front || gates.back) {
    return [[t('Front view'), gates.front], [t('Back view'), gates.back]]
  }
  if (gates.metrics && typeof gates.metrics === 'object') {
    return [[t('Fit'), { ...(gates.metrics as object), reasons: gates.reasons }]]
  }
  return [[t('Gate'), gates]]
}

/** A HairDeck fit attempt `{attempt, seed, ok, reasons, limits, metrics}`
 *  with its metrics lifted beside attempt/seed, so RecordNumbers lists them. */
function flatFit(r: GateRecord | null | undefined): unknown {
  if (!r || typeof r.metrics !== 'object' || r.metrics === null) return r
  return { attempt: r.attempt, seed: r.seed, ...(r.metrics as object), reasons: r.reasons }
}

function Swatch({ hex }: { hex: string }) {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block', width: 18, height: 18, borderRadius: 4, background: hex,
        border: '1px solid var(--border, #30363d)', verticalAlign: 'middle',
      }}
    />
  )
}

/** The HairDeck hair colour: HairDeck's own (automatic) or a manual one.
 *  Keyed by the server values, so the draft starts from them after a save. */
function HairColour({ colour, busy, running, onApply }: {
  colour: HairDeckPanel['colour']
  busy: boolean
  /** A hair run is active: the colour waits for it. */
  running: boolean
  onApply: (hex: string) => void
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(colour.target || colour.auto || '#7f6248')
  return (
    <>
      <div style={ROW}>
        <span className="ga-hint">{t('Automatic')}:</span>
        {colour.auto ? <Swatch hex={colour.auto} /> : null}
        <span className="ga-hint">{colour.auto ? t("HairDeck's own colours") : t('HairDeck has not run yet')}</span>
        <span className="ga-hint">·</span>
        <span className="ga-hint">{t('In use')}:</span>
        {colour.target ? <Swatch hex={colour.target} /> : null}
        <span className="ga-hint">{colour.target ? `${t('Manual')} ${colour.target}` : t('Automatic')}</span>
      </div>
      <div style={ROW}>
        <input
          type="color"
          value={draft}
          disabled={busy}
          aria-label={t('Hair colour')}
          onChange={(e) => setDraft(e.target.value.toLowerCase())}
        />
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || draft === colour.target}
          onClick={() => onApply(draft)}
        >
          {t('Apply')}
        </button>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !colour.target}
          onClick={() => onApply('')}
        >
          {t('Reset to automatic')}
        </button>
        {running ? <span className="ga-hint" style={WARN_STYLE}>{t('Wait for the running hair job')}</span> : null}
      </div>
      <div className="ga-hint">
        {t('A colour change re-fits the hair from the stored HairDeck result — HairDeck does not run again.')}
      </div>
    </>
  )
}

/** A placement draft field as a number; '' = automatic (null), NaN = invalid. */
function draftNumber(text: string, scale: number): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const n = Number(trimmed.replace(',', '.'))
  return Number.isFinite(n) ? n / scale : NaN
}

const draftText = (v: number | null, scale: number) => (v === null ? '' : String(Math.round(v * scale * 100) / 100))

/** The HairDeck placement: forward shift (shown in mm) and forward tilt (°).
 *  Empty = automatic. Keyed by the server values, so the drafts restart
 *  from them after a save. */
function HairPlacementForm({ placement, busy, running, onApply }: {
  placement: HairPlacement
  busy: boolean
  /** A hair run is active: the placement waits for it. */
  running: boolean
  onApply: (forward_m: number | null, tilt_deg: number | null) => void
}) {
  const { t } = useI18n()
  const [forward, setForward] = useState(draftText(placement.forward_m, 1000))
  const [tilt, setTilt] = useState(draftText(placement.tilt_deg, 1))
  const f = draftNumber(forward, 1000)
  const a = draftNumber(tilt, 1)
  const valid = (v: number | null, limit: number) => v === null || (!Number.isNaN(v) && Math.abs(v) <= limit)
  const ok = valid(f, placement.limits.forward_m) && valid(a, placement.limits.tilt_deg)
  const same = f === placement.forward_m && a === placement.tilt_deg
  const manual = placement.forward_m !== null || placement.tilt_deg !== null
  const fitted = placement.fitted
  const src = (s: string | null | undefined) => (s === 'manual' ? t('Manual') : t('Automatic'))
  return (
    <>
      <div style={ROW}>
        <label className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {t('Forward shift (mm)')}
          <input
            className="ga-input"
            type="number"
            step="1"
            style={{ width: 90 }}
            value={forward}
            placeholder={t('Auto')}
            disabled={busy}
            onChange={(e) => setForward(e.target.value)}
          />
        </label>
        <label className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {t('Forward tilt (°)')}
          <input
            className="ga-input"
            type="number"
            step="0.5"
            style={{ width: 90 }}
            value={tilt}
            placeholder={t('Auto')}
            disabled={busy}
            onChange={(e) => setTilt(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !ok || same}
          title={!ok ? t('Value out of range') : undefined}
          onClick={() => onApply(f, a)}
        >
          {t('Apply')}
        </button>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !manual}
          onClick={() => onApply(null, null)}
        >
          {t('Reset to automatic')}
        </button>
        {running ? <span className="ga-hint" style={WARN_STYLE}>{t('Wait for the running hair job')}</span> : null}
      </div>
      {fitted && fitted.forward_m !== null && fitted.tilt_deg !== null ? (
        <div className="ga-hint">
          {t('Last fit')}: {t('Forward shift')} {(fitted.forward_m * 1000).toFixed(1)} mm ({src(fitted.forward_source)})
          {' · '}{t('Forward tilt')} {fitted.tilt_deg.toFixed(1)}° ({src(fitted.tilt_source)})
          {fitted.hairline_y !== null
            ? ` · ${t('Hairline')} ${fitted.hairline_y.toFixed(3)} m`
              + (fitted.hairline_target_y !== null ? ` (${t('target')} ${fitted.hairline_target_y.toFixed(3)} m)` : '')
            : ''}
        </div>
      ) : null}
      <div className="ga-hint">
        {t('Empty = automatic: a small forward shift and the tilt that brings the front hairline down to the brow line.')}
        {' '}
        {t('A placement change re-fits the hair from the stored HairDeck result — HairDeck does not run again.')}
      </div>
    </>
  )
}

/** The collapsed last result of the method that is not selected. */
function OtherMethod({ other, method, limits }: {
  other: OtherMethodInfo | null
  method: HairMethod
  limits: HairInfo['limits']
}) {
  useClockSettings()
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const otherMethod: HairMethod = method === 'hairdeck' ? 'edit_chain' : 'hairdeck'
  if (!other) {
    return (
      <div className="ga-hint">
        {t('Other method')} ({t(METHOD_LABELS[otherMethod])}): {t('no result yet')}
      </div>
    )
  }
  const hairdeck = other.method === 'hairdeck'
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="ga-hint" style={{ cursor: 'pointer' }}>
        {t('Other method')} ({t(METHOD_LABELS[other.method])}): {t('last result')}
        {other.created_at ? ` · ${formatDateTime(other.created_at, clockSettings())}` : ''}
      </summary>
      {!other.on_current_base ? (
        <div className="ga-hint" style={WARN_STYLE}>{t('Fitted on an older base model')}</div>
      ) : null}
      {other.colour?.target ? (
        <div style={ROW}>
          <span className="ga-hint">{t('Hair colour')}:</span>
          <Swatch hex={other.colour.target} />
          <span className="ga-hint">{other.colour.target}</span>
        </div>
      ) : null}
      <GateChips
        specs={hairdeck ? HAIRDECK_FIT_CHIPS : FIT_CHIPS}
        record={other.metrics}
        limits={hairdeck ? limits.hairdeck_fit : limits.fit}
      />
      {open && other.preview_url ? (
        <Model3DViewer key={other.preview_url} url={other.preview_url} format="glb" height={300}
          freshness={other.preview_freshness} />
      ) : null}
      <div className="ga-hint">
        {t('Select this method above to use it again — its files stay, the switch generates nothing.')}
      </div>
    </details>
  )
}

/** The record the tile's chips show: the accepted final's (last of its
 *  attempts), else the newest refused attempt's. */
function shownRecord(img: GarmentImageInfo | undefined): GateRecord | null {
  if (!img) return null
  const finals = img.gates ? Object.values(img.gates) : []
  if (finals.length) return finals[finals.length - 1]
  const last = img.attempts?.[img.attempts.length - 1]
  return last?.gate ?? null
}

function ImageTile({ img, label, small, chips, limits, view, busy, blockedTitle, onRegenerate, extra }: {
  img: GarmentImageInfo | undefined
  label: string
  small?: boolean
  chips?: ChipSpec[]
  limits?: Record<string, GateLimit>
  view: GarmentView
  busy: boolean
  blockedTitle?: string
  onRegenerate: () => void
  extra?: ReactNode
}) {
  const { t } = useI18n()
  const url = img?.url || null
  const height = small ? 120 : TILE_HEIGHT
  const attempts = img?.attempts ?? []
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div className="ga-hint">{label}</div>
      {url ? (
        <RefImage key={url} src={url} height={height} label={label} meta={img} compact={small} />
      ) : (
        <div className="ga-hint" style={{ ...EMPTY_TILE, height }}>{t('No render yet')}</div>
      )}
      {url && img && !img.accepted ? <div className="ga-hint" style={WARN_STYLE}>{t('Not accepted')}</div> : null}
      {chips ? <GateChips specs={chips} record={shownRecord(img)} limits={limits} view={view} /> : null}
      {extra}
      {attempts.length ? (
        <details style={{ marginTop: 4 }}>
          <summary className="ga-hint" style={{ cursor: 'pointer' }}>
            {t('Attempts')} ({attempts.length})
          </summary>
          {attempts.map((a) => (
            <div key={a.attempt} style={{ display: 'flex', gap: 6, alignItems: 'flex-start', marginTop: 4 }}>
              <RefImage src={a.url} width={96} height={96} label={`${label} · ${t('Attempt')} ${a.attempt}`}
                meta={a} compact />
              <div style={{ minWidth: 0 }}>
                {chips ? <GateChips specs={chips} record={a.gate} limits={limits} view={view} /> : null}
                <RecordNumbers label={`${t('Attempt')} ${a.attempt}`} record={a.gate} />
              </div>
            </div>
          ))}
        </details>
      ) : null}
      <button
        type="button"
        className="ga-btn ga-btn-sm"
        style={{ marginTop: 4 }}
        disabled={busy || !!blockedTitle}
        title={blockedTitle}
        onClick={onRegenerate}
        aria-label={`${t('Regenerate')} · ${label}`}
      >
        {url ? t('Regenerate') : t('Generate')}
      </button>
    </div>
  )
}

function StepState({ garment, step }: { garment: GarmentInfo; step: string }) {
  const { t } = useI18n()
  if (garment.running_step === step) return <div className="ga-hint">{t('Generating…')}</div>
  if (garment.failed?.step === step) {
    return <div className="ga-hint" style={ERROR_STYLE}>{t('Failed')}: {garment.failed.error}</div>
  }
  return null
}

function upscaleText(upscale: Record<string, unknown> | null | undefined, t: (s: string) => string): string {
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

export function FieldHair({ character, onEditAppearance }: {
  character: string
  /** Opens the Appearance tab, where the hair text is edited. */
  onEditAppearance?: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const { info, setInfo, startPoll } = useGarment(character)
  // The user's own click, until the request answered (the poll then shows
  // the server's running state).
  const [posting, setPosting] = useState(false)

  const call = useCallback(
    async (path: string, body: unknown, after?: (d: unknown) => void | Promise<unknown>) => {
      if (posting) return
      setPosting(true)
      try {
        const d = await apiPost(path, body)
        await after?.(d)
        startPoll(300)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        startPoll()
      } finally {
        setPosting(false)
      }
    },
    [posting, startPoll, t, toast],
  )

  const itemId = info?.item_id || ''
  const run = useCallback(
    (body: { step?: string; view?: string; force?: boolean }) =>
      call(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, body),
    [call, enc, itemId],
  )

  const create = useCallback(
    () => call(`/characters/${enc}/hair`, {}, (d) => {
      if ((d as { started?: boolean })?.started === false) {
        toast(t('A hair run is already going for this character'))
      }
    }),
    [call, enc, t, toast],
  )

  const setEquipped = useCallback(
    (equipped: boolean) => call(`/characters/${enc}/hair/equipped`, { equipped }, () => {
      setInfo((prev: HairInfo | null) => (prev ? { ...prev, equipped } : prev))
    }),
    [call, enc, setInfo],
  )

  const setMethod = useCallback(
    (method: '' | HairMethod) => call(`/characters/${enc}/hair/method`, { method }),
    [call, enc],
  )

  // Store the colour, then re-fit (only the fit runs: the HairDeck result is cached).
  const applyColour = useCallback(
    (hex: string) => call(`/characters/${enc}/hair/colour`, { hex }, () => (
      itemId && info?.method === 'hairdeck'
        ? apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, {})
        : undefined
    )),
    [call, enc, info?.method, itemId],
  )

  // Store the placement, then re-fit (like the colour: only the fit runs).
  const applyPlacement = useCallback(
    (forward_m: number | null, tilt_deg: number | null) => call(
      `/characters/${enc}/hair/placement`, { forward_m, tilt_deg }, () => (
        itemId && info?.method === 'hairdeck'
          ? apiPost(`/characters/${enc}/garments/${encodeURIComponent(itemId)}/run`, {})
          : undefined
      )),
    [call, enc, info?.method, itemId],
  )

  if (!info) return <div className="ga-hint">{t('Loading…')}</div>
  if (!info.humanoid) {
    return <div className="ga-hint">{t('Hair as its own mesh is for humanoid characters only.')}</div>
  }
  if (!info.pipeline) {
    return (
      <div className="ga-hint">
        {t('Hair as its own mesh needs the base body pipeline — switch it on in the Base body tab')}
      </div>
    )
  }

  const editButton = onEditAppearance ? (
    <button type="button" className="ga-btn ga-btn-sm" onClick={onEditAppearance}>
      {t('Edit in Appearance')}
    </button>
  ) : null

  const garment = info.garment
  const busy = posting || garmentRunning(info)
  const limits = info.limits || {}
  const viewLabel = (view: GarmentView) => (view === 'front' ? t('Front view') : t('Back view'))
  const steps = garment?.steps ?? {}
  const accepted = (step: GarmentImageStep, view: GarmentView) => !!steps[step]?.[view]?.accepted
  const previous: Partial<Record<GarmentImageStep, GarmentImageStep>> = { ghost: 'haired', cutout: 'ghost' }

  const imageRow = (step: GarmentImageStep, chips?: ChipSpec[]) => (
    <>
      <div className="ga-fieldset-title">{t(STEP_LABELS[step])}</div>
      <div style={{ display: 'flex', gap: 6 }}>
        {GARMENT_VIEWS.map((view) => {
          const img = steps[step]?.[view]
          const prev = previous[step]
          const blocked = prev && !accepted(prev, view) ? t('Run the previous step first') : undefined
          return (
            <ImageTile
              key={view}
              img={img}
              label={viewLabel(view)}
              small={step === 'cutout'}
              chips={chips}
              limits={chips ? limits[step as 'haired' | 'ghost'] : undefined}
              view={view}
              busy={busy || !garment}
              blockedTitle={blocked}
              onRegenerate={() => { void run({ step, view, force: true }) }}
              extra={step === 'cutout' && img?.url ? (
                <div className="ga-hint" title={img.upscale?.reason ? String(img.upscale.reason) : undefined}>
                  {[
                    img.side ? `${t('Square side')} ${img.side} px` : '',
                    upscaleText(img.upscale, t),
                  ].filter(Boolean).join(' · ')}
                </div>
              ) : null}
            />
          )
        })}
      </div>
      {garment ? <StepState garment={garment} step={step} /> : null}
    </>
  )

  const mesh = steps.mesh
  const fit = steps.fit
  const fitRecord = fit && fit.status !== 'missing'
    ? fit.metrics
    : garment?.failed?.step === 'fit' && garment.failed.gates?.metrics
      ? (garment.failed.gates.metrics as Record<string, unknown>)
      : null
  const failures = garment?.failed ? failureRecords(garment.failed.gates, t) : []
  const hd = info.hairdeck
  const isHairDeck = info.method === 'hairdeck'
  const noHair = !!garment && !garment.served_fsig && !garment.running_step && fit?.status !== 'accepted'

  const fitBlock = (chips: ChipSpec[], fitLimits: Record<string, GateLimit> | undefined, ready: boolean) => (
    <>
      <div className="ga-fieldset-title">{t('Fit')}</div>
      <div style={ROW}>
        <span className="ga-hint">
          {t(FIT_STATUS[fit?.status || 'missing'])}
          {fit?.tris ? ` · ${t('Triangles')} ${fit.tris.toLocaleString()}` : ''}
          {fit?.created_at ? ` · ${formatDateTime(fit.created_at, clockSettings())}` : ''}
        </span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !garment || !ready}
          title={garment && !ready ? t('Run the previous step first') : undefined}
          onClick={() => { void run({ step: 'fit', force: true }) }}
        >
          {t('Re-fit')}
        </button>
      </div>
      <GateChips specs={chips} record={fitRecord} limits={fitLimits} />
      {fit?.low && fit.low.ok === false ? (
        <div className="ga-hint" style={WARN_STYLE}>
          {t('Distance tier failed — the full hair is used')}: {fit.low.error}
        </div>
      ) : null}
      {garment ? <StepState garment={garment} step="fit" /> : null}
    </>
  )

  const editChainSection = (
    <>
      {imageRow('haired', HAIRED_CHIPS)}
      {imageRow('ghost', GHOST_CHIPS)}
      {imageRow('cutout')}

      <div className="ga-fieldset-title">{t('Mesh')}</div>
      <div style={ROW}>
        <span className="ga-hint">
          {!mesh || mesh.status === 'missing' ? t('Not built yet')
            : mesh.status === 'refused' ? t('Refused')
            : t('Accepted')}
          {mesh?.metrics.tris_raw != null && mesh.metrics.tris_prepared != null
            ? ` · ${t('Triangles')} ${mesh.metrics.tris_raw.toLocaleString()} → ${mesh.metrics.tris_prepared.toLocaleString()}`
            : ''}
          {mesh?.metrics.backend ? ` · ${mesh.metrics.backend}` : ''}
          {mesh?.created_at ? ` · ${formatDateTime(mesh.created_at, clockSettings())}` : ''}
        </span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !garment || !GARMENT_VIEWS.every((v) => accepted('cutout', v))}
          title={garment && !GARMENT_VIEWS.every((v) => accepted('cutout', v)) ? t('Run the previous step first') : undefined}
          onClick={() => { void run({ step: 'mesh', force: true }) }}
        >
          {mesh && mesh.status !== 'missing' ? t('Regenerate') : t('Generate')}
        </button>
      </div>
      <GateChips specs={MESH_CHIPS} record={mesh?.metrics} limits={limits.mesh} />
      {mesh?.status === 'refused' && mesh.gates.length ? (
        <details>
          <summary className="ga-hint" style={{ cursor: 'pointer' }}>{t('Attempts')} ({mesh.gates.length})</summary>
          {mesh.gates.map((g, i) => (
            <RecordNumbers key={i} label={`${t('Attempt')} ${num(g.attempt) ?? i + 1}`} record={g} />
          ))}
        </details>
      ) : null}
      {garment ? <StepState garment={garment} step="mesh" /> : null}

      {fitBlock(FIT_CHIPS, limits.fit, mesh?.status === 'accepted')}
    </>
  )

  const hairdeckSection = hd ? (
    <>
      <div className="ga-fieldset-title">{t('HairDeck')}</div>
      <div style={{ display: 'flex', gap: 6 }}>
        {HAIRDECK_TILES.map(([key, label]) => {
          const img = hd.images[key]
          return (
            <div key={key} style={{ flex: 1, minWidth: 0 }}>
              <div className="ga-hint">{t(label)}</div>
              {img ? (
                <RefImage key={img.url} src={img.url} height={TILE_HEIGHT} label={t(label)} meta={img} />
              ) : (
                <div className="ga-hint" style={EMPTY_TILE}>
                  {key === 'input' ? t('No profile picture') : t('No render yet')}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div style={ROW}>
        <span className="ga-hint">
          {t(HAIRDECK_STATUS[hd.status] || hd.status)}
          {hd.attempt ? ` · ${t('Attempt')} ${hd.attempt}` : ''}
          {hd.seed != null ? ` · ${t('Seed')} ${hd.seed}` : ''}
          {hd.backend ? ` · ${hd.backend}` : ''}
          {hd.created_at ? ` · ${formatDateTime(hd.created_at, clockSettings())}` : ''}
        </span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy || !garment || !hd.images.input}
          title={!hd.images.input ? t('Set a profile picture first') : undefined}
          onClick={() => { void run({ step: 'hairdeck', force: true }) }}
        >
          {t('Regenerate hair (HairDeck)')}
        </button>
      </div>
      {hd.notes.length ? <div className="ga-hint">{t('Notes')}: {hd.notes.join(' · ')}</div> : null}
      {hd.status === 'refused' && hd.error ? <div className="ga-hint" style={ERROR_STYLE}>{hd.error}</div> : null}
      {garment ? <StepState garment={garment} step="hairdeck" /> : null}

      <div className="ga-fieldset-title">{t('Hair colour')}</div>
      <HairColour
        key={`${hd.colour.target || ''}|${hd.colour.auto || ''}`}
        colour={hd.colour}
        busy={busy}
        running={garmentRunning(info)}
        onApply={(hex) => { void applyColour(hex) }}
      />

      {hd.placement ? (
        <>
          <div className="ga-fieldset-title">{t('Hair placement')}</div>
          <HairPlacementForm
            key={`${hd.placement.forward_m ?? ''}|${hd.placement.tilt_deg ?? ''}`}
            placement={hd.placement}
            busy={busy}
            running={garmentRunning(info)}
            onApply={(forward, tilt) => { void applyPlacement(forward, tilt) }}
          />
        </>
      ) : null}

      {fitBlock(HAIRDECK_FIT_CHIPS, limits.hairdeck_fit, hd.status === 'accepted')}
      {hd.attempts.length ? (
        <details>
          <summary className="ga-hint" style={{ cursor: 'pointer' }}>
            {t('Refused fit attempts')} ({hd.attempts.length})
          </summary>
          {hd.attempts.map((g, i) => (
            <RecordNumbers key={i} label={`${t('Attempt')} ${num(g.attempt) ?? i + 1}`} record={flatFit(g)} />
          ))}
        </details>
      ) : null}
    </>
  ) : null

  return (
    <div className="ga-form">
      <div className="ga-fieldset-title">{t('Hair method')}</div>
      <div style={ROW}>
        <select
          className="ga-input"
          value={info.method_source === 'character' ? info.method : ''}
          disabled={busy}
          title={garmentRunning(info) ? t('Wait for the running hair job') : undefined}
          aria-label={t('Hair method')}
          onChange={(e) => { void setMethod(e.target.value as '' | HairMethod) }}
        >
          <option value="">{t('World default')} ({t(METHOD_LABELS[info.world_method])})</option>
          <option value="edit_chain">{t('Edit chain')}</option>
          <option value="hairdeck">{t('HairDeck')}</option>
        </select>
        <span className="ga-hint">
          {isHairDeck
            ? t('HairDeck makes hair cards from the profile picture in one step.')
            : t('The edit chain renders the hair views and builds a mesh from them.')}
        </span>
        {garmentRunning(info) ? (
          <span className="ga-hint" style={WARN_STYLE}>{t('Wait for the running hair job')}</span>
        ) : null}
      </div>

      <div className="ga-fieldset-title">{t('Hair description')}</div>
      {info.description ? (
        <div style={ROW}>
          <span>{info.description}</span>
          {editButton}
        </div>
      ) : (
        <div style={ROW}>
          <span className="ga-hint">{t('No hair set in Appearance')}</span>
          {editButton}
        </div>
      )}

      {!info.item_id ? (
        info.description ? (
          <div style={ROW}>
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={posting} onClick={() => { void create() }}>
              {t('Create hair')}
            </button>
            <span className="ga-hint">
              {isHairDeck
                ? t('Makes hair cards from the profile picture and fits them onto the base model.')
                : t('Renders the hair views, builds the mesh and fits it onto the base model.')}
            </span>
          </div>
        ) : null
      ) : (
        <>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={info.equipped}
              disabled={posting}
              onChange={(e) => { void setEquipped(e.target.checked) }}
            />
            <span>{t('Wear hair')}</span>
          </label>

          {garment?.running_step ? (
            <div className="ga-hint">
              {t('Running')}: {t(STEP_LABELS[garment.running_step] || garment.running_step)}
              {garment.started_at ? ` · ${formatDateTime(garment.started_at, clockSettings())}` : ''}
            </div>
          ) : null}

          {garment && garment.stale_reasons.length ? (
            <div style={{ ...ROW, padding: 8, borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
              <span style={WARN_STYLE}>
                {garment.stale_reasons.map((r) => t(STALE_LABELS[r] || r)).join(' · ')}
              </span>
              <span className="ga-hint">{t('The previous hair stays in use until the new one is fitted.')}</span>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => { void run({}) }}>
                {t('Regenerate')}
              </button>
            </div>
          ) : null}

          {garment?.failed && !garment.running_step ? (
            <div>
              <div className="ga-hint" style={ERROR_STYLE}>
                {t('Failed')} · {t(STEP_LABELS[garment.failed.step] || garment.failed.step)}: {garment.failed.error}
              </div>
              {failures.length ? (
                <details>
                  <summary className="ga-hint" style={{ cursor: 'pointer' }}>
                    {t('Numbers of the refused attempts')} ({failures.length})
                  </summary>
                  {failures.map(([label, record]) => (
                    <RecordNumbers key={label} label={label} record={record} />
                  ))}
                </details>
              ) : null}
            </div>
          ) : null}

          {noHair ? (
            <div style={{ ...ROW, padding: 8, borderRadius: 6, border: '1px solid var(--warning, #d29922)' }}>
              <span style={WARN_STYLE}>{t('No hair from this method yet')}</span>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => { void run({}) }}>
                {t('Regenerate')}
              </button>
            </div>
          ) : null}

          {isHairDeck ? hairdeckSection : editChainSection}

          <div className="ga-fieldset-title">{t('Preview')}</div>
          {garment?.preview_url ? (
            <Model3DViewer key={garment.preview_url} url={garment.preview_url} format="glb" height={360}
              freshness={garment.preview_freshness} />
          ) : (
            <div className="ga-hint">{t('No fitted hair yet')}</div>
          )}
          <div className="ga-hint">
            {t('Hair has no collision yet — it can pass through arms and shoulders when they move')}
          </div>

          <div style={ROW}>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={busy || !garment}
              title={t('Runs every step that is missing or out of date')}
              onClick={() => { void run({}) }}
            >
              {garmentRunning(info) ? t('Generating…') : t('Run all')}
            </button>
          </div>

          <OtherMethod other={info.other} method={info.method} limits={limits} />
        </>
      )}
    </div>
  )
}
