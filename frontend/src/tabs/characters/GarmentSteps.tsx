/**
 * GarmentSteps — the generic steps of a garment's edit chain, shared by the
 * Hair tab (FieldHair) and the Wardrobe's own-mesh panel (WardrobeGarment):
 * the image steps (front + back tile each, gate chips, attempts,
 * Regenerate per view), the mesh and the fit (chips, Re-fit), plus the
 * failure block. Every chip's LIMIT comes from the server (the gate
 * constants, `limits` of GET /characters/{n}/hair or
 * /characters/{n}/garments/{item}); this module only knows which number of
 * a record a chip shows and how it reads. Images and previews carry the
 * server's `freshness` (RefImage / Model3DViewer render the badge).
 *
 * Runs go through the caller (`onRun` → POST
 * /characters/{n}/garments/{item}/run {step?, view?, force?}, useGarmentRun).
 * A click answers on the clicked button at once ("Starting…" while the POST
 * is in flight, a refusal beside it); the targeted tile then carries its run
 * state (Queued / Generating… / Will be redone — `runMark`) and the panel's
 * sticky status line (RunStatusLine) says what the item waits for.
 */
import { Fragment } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { EMPTY_TILE, ERROR_STYLE, MESH_CHIPS, ROW, TILE_HEIGHT, WARN_STYLE, flatFit, num } from './garmentStyle'
import type { ChipSpec, GarmentLimits, GarmentRunBody } from './garmentStyle'
import { RefImage } from './RefImage'
import { GARMENT_VIEWS, runMark, runSlot } from './useGarment'
import type {
  GarmentImageInfo, GarmentImageStep, GarmentInfo, GarmentView, GateLimit, GateRecord, RunFeedback, RunMark,
} from './useGarment'

const MARK_LABELS: Record<Exclude<RunMark, null>, string> = {
  queued: 'Queued',
  generating: 'Generating…',
  redo: 'Will be redone',
}

const MARK_COLORS: Record<Exclude<RunMark, null>, string> = {
  queued: 'var(--accent, #6aa9ff)',
  generating: 'var(--accent, #6aa9ff)',
  redo: 'var(--warning, #d29922)',
}

/** The run state of a targeted tile/step: a small pill. */
export function RunBadge({ mark }: { mark: RunMark }) {
  const { t } = useI18n()
  if (!mark) return null
  return (
    <span className={`ga-run-badge${mark === 'generating' ? ' ga-run-badge-live' : ''}`}
      style={{ borderColor: MARK_COLORS[mark], color: MARK_COLORS[mark] }}>
      {t(MARK_LABELS[mark])}
    </span>
  )
}

/** The other garment runs of the character, for the queue and refusal texts. */
function othersText(fb: RunFeedback | undefined, stepLabels: Record<string, string>,
  t: (s: string) => string): string {
  return (fb?.others || [])
    .map((o) => `${o.name} (${t(stepLabels[o.step || ''] || o.step || '')})`)
    .join(', ')
}

/** A run button: "Starting…" while its own POST is in flight (every run
 *  button waits meanwhile), the server's refusal right beside it. */
export function RunButton({ feedback, slot, label, disabled, title, ariaLabel, stepLabels, style, primary,
  onClick }: {
  feedback?: RunFeedback
  slot: string
  label: string
  disabled?: boolean
  title?: string
  ariaLabel?: string
  stepLabels: Record<string, string>
  style?: CSSProperties
  primary?: boolean
  onClick: () => void
}) {
  const { t } = useI18n()
  const starting = feedback?.pending === slot
  const refused = feedback?.refused?.slot === slot ? feedback.refused : null
  const others = othersText(feedback, stepLabels, t)
  return (
    <>
      <button
        type="button"
        className={`ga-btn ga-btn-sm${primary ? ' ga-btn-primary' : ''}`}
        style={style}
        disabled={disabled || feedback?.pending != null}
        title={title}
        aria-label={ariaLabel}
        aria-busy={starting || undefined}
        onClick={onClick}
      >
        {starting ? t('Starting…') : label}
      </button>
      {refused ? (
        <div className="ga-hint" role="status" style={{ ...ERROR_STYLE, flexBasis: '100%' }} title={refused.message}>
          {t('Another piece of this character is being generated — this run was not started')}
          {others ? ` · ${t('Running')}: ${others}` : ''}
        </div>
      ) : null}
    </>
  )
}

/** The panel's status line while the item runs or waits — sticky, so it
 *  stays in view while the steps scroll: Starting… / Queued (behind the
 *  character's other runs) / Running: <step>, with the start time. */
export function RunStatusLine({ garment, feedback, stepLabels }: {
  garment: GarmentInfo | null
  feedback?: RunFeedback
  stepLabels: Record<string, string>
}) {
  useClockSettings()
  const { t } = useI18n()
  const running = garment?.running_step || null
  if (!running && feedback?.pending == null) return null
  const target = feedback?.target
  const requested = target?.step
    ? `${t(stepLabels[target.step] || target.step)}${target.view
      ? ` · ${target.view === 'front' ? t('Front view') : t('Back view')}` : ''}`
    : ''
  let text: string
  if (!running) {
    text = t('Starting…')
  } else if (running === 'queued') {
    const others = othersText(feedback, stepLabels, t)
    text = others ? t('Queued behind {items}').replace('{items}', others) : t('Queued')
  } else {
    text = `${t('Running')}: ${t(stepLabels[running] || running)}`
  }
  return (
    <div className="ga-hint ga-run-status" role="status">
      {running ? <RunBadge mark={running === 'queued' ? 'queued' : 'generating'} /> : null}
      <span style={{ flex: '1 1 0', minWidth: 0 }}>
        {[
          text,
          requested ? `${t('Requested')}: ${requested}` : '',
          running && garment?.started_at ? `${t('started')} ${formatDateTime(garment.started_at, clockSettings())}` : '',
        ].filter(Boolean).join(' · ')}
      </span>
    </div>
  )
}

const FIT_STATUS: Record<string, string> = {
  accepted: 'Accepted',
  stale: 'Fitted on an older base model',
  outdated: 'Fitted from a replaced mesh',
  missing: 'Not fitted yet',
}


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

export function GateChips({ specs, record, limits, view }: {
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
    const gated = !(spec.gatedKey && record[spec.gatedKey] === false)
    const limit = gated ? limits?.[spec.key] : undefined
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
export function RecordNumbers({ label, record }: { label: string; record: unknown }) {
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

/** The record the tile's chips show: the accepted final's (last of its
 *  attempts), else the newest refused attempt's. */
function shownRecord(img: GarmentImageInfo | undefined): GateRecord | null {
  if (!img) return null
  const finals = img.gates ? Object.values(img.gates) : []
  if (finals.length) return finals[finals.length - 1]
  const last = img.attempts?.[img.attempts.length - 1]
  return last?.gate ?? null
}

function ImageTile({ img, label, small, chips, limits, view, busy, blockedTitle, onRegenerate, extra, feedback,
  slot, mark, stepLabels }: {
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
  feedback?: RunFeedback
  slot: string
  mark: RunMark
  stepLabels: Record<string, string>
}) {
  const { t } = useI18n()
  const url = img?.url || null
  const height = small ? 120 : TILE_HEIGHT
  const attempts = img?.attempts ?? []
  const starting = feedback?.pending === slot
  const ring = mark ? MARK_COLORS[mark] : starting ? 'var(--accent, #6aa9ff)' : null
  return (
    <div style={{
      flex: 1, minWidth: 0, borderRadius: 6, padding: 3, margin: -3,
      outline: ring ? `2px solid ${ring}` : undefined, outlineOffset: -1,
    }}>
      <div className="ga-hint" style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span>{label}</span>
        <RunBadge mark={mark} />
      </div>
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
      <RunButton
        feedback={feedback}
        slot={slot}
        style={{ marginTop: 4 }}
        disabled={busy || !!blockedTitle}
        title={blockedTitle}
        onClick={onRegenerate}
        ariaLabel={`${t('Regenerate')} · ${label}`}
        label={url ? t('Regenerate') : t('Generate')}
        stepLabels={stepLabels}
      />
    </div>
  )
}

export function StepState({ garment, step }: { garment: GarmentInfo; step: string }) {
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

/** The fit: status, Re-fit, the chips of the fit record (or of a refused
 *  fit's numbers), the distance tier and the step state. */
export function FitBlock({ garment, chips, limits, ready, busy, onRun, lowFailedText, feedback, order,
  stepLabels }: {
  garment: GarmentInfo | null
  chips: ChipSpec[]
  limits: Record<string, GateLimit> | undefined
  /** The step before the fit is accepted. */
  ready: boolean
  busy: boolean
  onRun: (body: GarmentRunBody) => void
  /** Shown with the error when the distance tier failed (the full mesh is used). */
  lowFailedText: string
  feedback?: RunFeedback
  /** The method's step order (the run marks). */
  order: readonly string[]
  stepLabels: Record<string, string>
}) {
  useClockSettings()
  const { t } = useI18n()
  const fit = garment?.steps.fit
  const fitRecord = fit && fit.status !== 'missing'
    ? fit.metrics
    : garment?.failed?.step === 'fit' && garment.failed.gates?.metrics
      ? (garment.failed.gates.metrics as Record<string, unknown>)
      : null
  return (
    <>
      <div className="ga-fieldset-title">{t('Fit')}</div>
      <div style={ROW}>
        <RunBadge mark={runMark(feedback, garment, order, 'fit')} />
        <span className="ga-hint">
          {t(FIT_STATUS[fit?.status || 'missing'])}
          {fit?.tris ? ` · ${t('Triangles')} ${fit.tris.toLocaleString()}` : ''}
          {fit?.created_at ? ` · ${formatDateTime(fit.created_at, clockSettings())}` : ''}
        </span>
        <RunButton
          feedback={feedback}
          slot={runSlot({ step: 'fit' })}
          disabled={busy || !garment || !ready}
          title={garment && !ready ? t('Run the previous step first') : undefined}
          onClick={() => { onRun({ step: 'fit', force: true }) }}
          label={t('Re-fit')}
          stepLabels={stepLabels}
        />
      </div>
      <GateChips specs={chips} record={fitRecord} limits={limits} />
      {fit?.low && fit.low.ok === false ? (
        <div className="ga-hint" style={WARN_STYLE}>
          {t(lowFailedText)}: {fit.low.error}
        </div>
      ) : null}
      {garment ? <StepState garment={garment} step="fit" /> : null}
    </>
  )
}

/** The failed step with its error and the numbers of the refused attempts. */
export function GarmentFailure({ garment, stepLabels }: {
  garment: GarmentInfo | null
  stepLabels: Record<string, string>
}) {
  const { t } = useI18n()
  if (!garment?.failed || garment.running_step) return null
  const failures = failureRecords(garment.failed.gates, t)
  return (
    <div>
      <div className="ga-hint" style={ERROR_STYLE}>
        {t('Failed')} · {t(stepLabels[garment.failed.step] || garment.failed.step)}: {garment.failed.error}
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
  )
}

/** One image step of the chain in its order, with the chips of its gate. */
export interface ImageStepSpec {
  step: GarmentImageStep
  chips?: ChipSpec[]
}

/** The edit chain: the image steps (each needs the previous one accepted
 *  per view), the mesh (needs both cut-outs) and the fit (needs the mesh). */
export function GarmentSteps({ garment, imageSteps, stepLabels, limits, fitChips, busy, onRun, lowFailedText,
  compact = false, feedback }: {
  garment: GarmentInfo | null
  imageSteps: ImageStepSpec[]
  stepLabels: Record<string, string>
  limits: GarmentLimits
  fitChips: ChipSpec[]
  busy: boolean
  onRun: (body: GarmentRunBody) => void
  lowFailedText: string
  /** Small image tiles everywhere (a narrow panel). */
  compact?: boolean
  /** The panel's own run clicks (useGarmentRun). */
  feedback?: RunFeedback
}) {
  useClockSettings()
  const { t } = useI18n()
  const viewLabel = (view: GarmentView) => (view === 'front' ? t('Front view') : t('Back view'))
  const steps = garment?.steps ?? {}
  const accepted = (step: GarmentImageStep, view: GarmentView) => !!steps[step]?.[view]?.accepted
  const lastImage = imageSteps[imageSteps.length - 1]?.step
  const mesh = steps.mesh
  const order = [...imageSteps.map((s) => s.step), 'mesh', 'fit']

  const imageRow = ({ step, chips }: ImageStepSpec, index: number) => {
    const prev = index > 0 ? imageSteps[index - 1].step : undefined
    return (
      <Fragment key={step}>
        <div className="ga-fieldset-title">{t(stepLabels[step] || step)}</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {GARMENT_VIEWS.map((view) => {
            const img = steps[step]?.[view]
            const blocked = prev && !accepted(prev, view) ? t('Run the previous step first') : undefined
            return (
              <ImageTile
                key={view}
                img={img}
                label={viewLabel(view)}
                small={compact || step === 'cutout'}
                chips={chips}
                limits={chips ? limits[step] : undefined}
                view={view}
                busy={busy || !garment}
                blockedTitle={blocked}
                onRegenerate={() => { onRun({ step, view, force: true }) }}
                feedback={feedback}
                slot={runSlot({ step, view })}
                mark={runMark(feedback, garment, order, step, view)}
                stepLabels={stepLabels}
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
      </Fragment>
    )
  }

  const cutoutsReady = !!lastImage && GARMENT_VIEWS.every((v) => accepted(lastImage, v))
  return (
    <>
      {imageSteps.map(imageRow)}

      <div className="ga-fieldset-title">{t('Mesh')}</div>
      <div style={ROW}>
        <RunBadge mark={runMark(feedback, garment, order, 'mesh')} />
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
        <RunButton
          feedback={feedback}
          slot={runSlot({ step: 'mesh' })}
          disabled={busy || !garment || !cutoutsReady}
          title={garment && !cutoutsReady ? t('Run the previous step first') : undefined}
          onClick={() => { onRun({ step: 'mesh', force: true }) }}
          label={mesh && mesh.status !== 'missing' ? t('Regenerate') : t('Generate')}
          stepLabels={stepLabels}
        />
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

      <FitBlock garment={garment} chips={fitChips} limits={limits.fit} ready={mesh?.status === 'accepted'}
        busy={busy} onRun={onRun} lowFailedText={lowFailedText} feedback={feedback} order={order}
        stepLabels={stepLabels} />
    </>
  )
}
