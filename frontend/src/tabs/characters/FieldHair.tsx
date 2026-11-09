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
 */
import { useCallback, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { useEnlarge } from '../../components/ZoomButton'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { Model3DViewer } from './Model3DViewer'
import { GARMENT_VIEWS, garmentRunning, useGarment } from './useGarment'
import type {
  GarmentImageInfo, GarmentImageStep, GarmentInfo, GarmentView, GateLimit, GateRecord, HairInfo,
} from './useGarment'

const TILE_STYLE: CSSProperties = {
  display: 'block',
  width: '100%',
  height: 200,
  objectFit: 'contain',
  borderRadius: 6,
  border: '1px solid var(--border, #30363d)',
  background: 'rgba(255, 255, 255, 0.04)',
}

const EMPTY_TILE: CSSProperties = {
  ...TILE_STYLE,
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
  fit: 'Fit',
}

const STALE_LABELS: Record<string, string> = {
  description_changed: 'Hair description changed',
  base_changed: 'Base body changed',
  base_model_changed: 'Base model changed',
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
    return (gates.attempts as GateRecord[]).map((r, i) => [`${t('Attempt')} ${num(r?.attempt) ?? i + 1}`, r])
  }
  if (gates.front || gates.back) {
    return [[t('Front view'), gates.front], [t('Back view'), gates.back]]
  }
  if (gates.metrics && typeof gates.metrics === 'object') {
    return [[t('Fit'), { ...(gates.metrics as object), reasons: gates.reasons }]]
  }
  return [[t('Gate'), gates]]
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
  const enlarge = useEnlarge()
  const url = img?.url || null
  const zoom = url ? enlarge({ src: url, alt: label }) : null
  const tile = small ? { ...TILE_STYLE, height: 120 } : TILE_STYLE
  const attempts = img?.attempts ?? []
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div className="ga-hint">{label}</div>
      {url && zoom ? (
        <img key={url} src={url} alt="" {...zoom} style={{ ...zoom.style, ...tile }} />
      ) : (
        <div className="ga-hint" style={{ ...EMPTY_TILE, height: tile.height }}>{t('No render yet')}</div>
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
              <img src={a.url} alt="" style={{ ...TILE_STYLE, width: 72, height: 72, flex: 'none' }} />
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
    async (path: string, body: unknown, after?: (d: unknown) => void) => {
      if (posting) return
      setPosting(true)
      try {
        const d = await apiPost(path, body)
        after?.(d)
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

  if (!info) return <div className="ga-hint">{t('Loading…')}</div>
  if (!info.humanoid) {
    return <div className="ga-hint">{t('Hair as its own mesh is for humanoid characters only.')}</div>
  }
  if (!info.pipeline) {
    return (
      <div className="ga-hint">
        {t('Hair as its own mesh needs the base body pipeline — switch it on in the Pose tab')}
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

  return (
    <div className="ga-form">
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
            <span className="ga-hint">{t('Renders the hair views, builds the mesh and fits it onto the base model.')}</span>
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
              disabled={busy || !garment || mesh?.status !== 'accepted'}
              title={garment && mesh?.status !== 'accepted' ? t('Run the previous step first') : undefined}
              onClick={() => { void run({ step: 'fit', force: true }) }}
            >
              {t('Re-fit')}
            </button>
          </div>
          <GateChips specs={FIT_CHIPS} record={fitRecord} limits={limits.fit} />
          {fit?.low && fit.low.ok === false ? (
            <div className="ga-hint" style={WARN_STYLE}>
              {t('Distance tier failed — the full hair is used')}: {fit.low.error}
            </div>
          ) : null}
          {garment ? <StepState garment={garment} step="fit" /> : null}

          <div className="ga-fieldset-title">{t('Preview')}</div>
          {garment?.preview_url ? (
            <Model3DViewer key={garment.preview_url} url={garment.preview_url} format="glb" height={360} />
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
        </>
      )}
    </div>
  )
}
