/**
 * GarmentStepGrid — the clothing chain of an own-mesh piece as one compact
 * grid (the Wardrobe's piece dialog, WardrobeGarment): one ROW per step
 * (worn → piece-only → cut-outs → mesh → fit), the views as COLUMNS. Each
 * image cell is a small thumbnail (a click enlarges it in the shared
 * lightbox) with its run badge, one status icon whose tooltip lists the gate
 * chips, a Regenerate icon button and the refused attempts as tiny thumbnails
 * (reason on hover). A missing image is a slim placeholder.
 *
 * The step names carry a tooltip with what the step makes and what a
 * Regenerate costs (hub jobs). Run clicks go through the caller (`onRun`,
 * useGarmentRun) and keep their immediate feedback (RunButton, runMark).
 * The Hair tab keeps its own layout (GarmentSteps).
 */
import { Fragment } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useEnlarge } from '../../components/ZoomButton'
import { useI18n } from '../../i18n/I18nProvider'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { RunBadge, RunButton } from './GarmentSteps'
import type { ImageStepSpec } from './GarmentSteps'
import { MESH_CHIPS, chipResults, num, queueText, shownRecord, upscaleText } from './garmentStyle'
import type { ChipSpec, GarmentLimits, GarmentRunBody } from './garmentStyle'
import { RefImage } from './RefImage'
import { GARMENT_VIEWS, runMark, runSlot } from './useGarment'
import type {
  GarmentImageStep, GarmentInfo, GarmentRunState, GarmentView, GateLimit, GateRecord, RunFeedback,
} from './useGarment'

/** Thumbnail height of an image cell (px). */
const THUMB_H = 112
const THUMB_W = 84

const FIT_STATUS: Record<string, string> = {
  accepted: 'Accepted',
  stale: 'Fitted on an older base model',
  outdated: 'Fitted from a replaced mesh',
  missing: 'Not fitted yet',
}

const STATUS_ICON: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  width: 18, height: 18, borderRadius: 9, fontSize: 11, fontWeight: 700, cursor: 'help', flex: 'none',
}

/** One status icon for a gate record: ✓ every gated number passes, ✕ one
 *  fails (or the record names reasons), • numbers only; the tooltip lists
 *  every chip with its limit and the reasons. */
export function GateIcon({ specs, record, limits, view, extra }: {
  specs: ChipSpec[]
  record: Record<string, unknown> | null | undefined
  limits: Record<string, GateLimit> | undefined
  view?: string
  /** Lines put before the chips (state, metrics without a chip). */
  extra?: string[]
}) {
  const { t } = useI18n()
  if (!record && !extra?.length) return null
  const chips = chipResults(specs, record, limits, view)
  const reasons = Array.isArray((record as GateRecord | null | undefined)?.reasons)
    ? ((record as GateRecord).reasons as string[]) : []
  const failed = chips.some((c) => c.ok === false) || reasons.length > 0 || (record as GateRecord)?.ok === false
  const passed = !failed && chips.some((c) => c.ok === true)
  const lines = [
    ...(extra || []),
    ...chips.map((c) => `${c.ok === false ? '✕' : c.ok ? '✓' : '·'} ${t(c.label)} ${c.shown}${c.lim
      ? ` (${t('Limit')} ${c.lim})` : ` (${t('Reported, not gated')})`}`),
    ...reasons.map((r) => `✕ ${r}`),
  ]
  const color = failed ? 'var(--danger, #f85149)' : passed ? 'var(--success, #3fb950)' : 'var(--text-muted, #8b949e)'
  return (
    <span role="img" aria-label={lines.join('; ')} title={lines.join('\n')}
      style={{ ...STATUS_ICON, border: `1px solid ${color}`, color }}>
      {failed ? '✕' : passed ? '✓' : 'i'}
    </span>
  )
}

/** The refused/replaced attempts of an image as tiny thumbnails (click =
 *  lightbox, reason and numbers on hover). */
export function AttemptThumbs({ attempts, label, chips, limits, view }: {
  attempts: Array<{ attempt: number; gate: GateRecord | null; url: string }>
  label: string
  chips?: ChipSpec[]
  limits?: Record<string, GateLimit>
  view: string
}) {
  const { t } = useI18n()
  const enlarge = useEnlarge()
  if (!attempts.length) return null
  return (
    <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
      {attempts.map((a) => {
        const alt = `${label} · ${t('Attempt')} ${a.attempt}`
        const zoom = enlarge({ src: a.url, alt })
        const tip = [
          alt,
          ...chipResults(chips || [], a.gate, limits, view)
            .filter((c) => c.ok === false).map((c) => `✕ ${t(c.label)} ${c.shown} (${c.lim})`),
          ...(Array.isArray(a.gate?.reasons) ? (a.gate?.reasons as string[]) : []),
        ].join('\n')
        return (
          <img key={a.attempt} src={a.url} alt={alt} {...zoom} title={tip}
            style={{
              ...zoom.style, width: 26, height: 34, objectFit: 'cover', borderRadius: 3,
              border: `1px solid ${a.gate?.ok === false || a.gate?.reasons?.length
                ? 'var(--danger, #f85149)' : 'var(--border, #30363d)'}`,
            }} />
        )
      })}
    </div>
  )
}

/** The step name cell: name, tooltip (what it makes, what Regenerate costs),
 *  the step's own state (running / failed). */
export function StepLabel({ garment, step, label, help }: {
  garment: GarmentRunState | null
  step: string
  label: string
  help: string
}) {
  const { t } = useI18n()
  const failed = garment?.failed?.step === step && !garment.running_step ? garment.failed : null
  return (
    <div className="ga-step-grid-label" title={t(help)}>
      <span>{t(label)} <span aria-hidden className="ga-step-grid-help">?</span></span>
      {garment?.running_step === step ? <RunBadge mark="generating" /> : null}
      {failed ? (
        <span className="ga-run-badge" title={failed.error}
          style={{ borderColor: 'var(--danger, #f85149)', color: 'var(--danger, #f85149)' }}>
          {t('Failed')}
        </span>
      ) : null}
    </div>
  )
}

/** What each step makes and what its Regenerate costs (tooltips). */
const STEP_HELP: Record<string, string> = {
  worn: 'Worn views: the base body wearing this piece, front and back (image edits of the base views). Regenerate: one hub image job for that view (a second attempt when the gate refuses it), then every later step runs again.',
  ghost: 'Piece-only views: the piece alone, the body removed, aligned to the worn view. Regenerate: one hub image job for that view (a second attempt when the gate refuses it), then every later step runs again.',
  cutout: 'Cut-outs: the piece-only views squared and upscaled as the mesh input. Regenerate: local crop plus a routed upscale job, then the mesh and the fit run again.',
  mesh: 'Mesh: a 3D mesh built from both cut-outs and decimated. Regenerate: one hub mesh job (a second attempt when the gate refuses it), then the fit runs again.',
  fit: 'Fit: the mesh fitted onto the rigged base model. Re-fit runs locally — no hub job.',
}

export function GarmentStepGrid({ garment, imageSteps, stepLabels, limits, fitChips, busy, onRun, feedback }: {
  garment: GarmentInfo | null
  imageSteps: ImageStepSpec[]
  stepLabels: Record<string, string>
  limits: GarmentLimits
  fitChips: ChipSpec[]
  busy: boolean
  onRun: (body: GarmentRunBody, slot?: string) => void
  feedback?: RunFeedback
}) {
  useClockSettings()
  const { t } = useI18n()
  const viewLabel = (view: GarmentView) => (view === 'front' ? t('Front view') : t('Back view'))
  const steps = garment?.steps ?? {}
  const accepted = (step: GarmentImageStep, view: GarmentView) => !!steps[step]?.[view]?.accepted
  const lastImage = imageSteps[imageSteps.length - 1]?.step
  const order = [...imageSteps.map((s) => s.step), 'mesh', 'fit']
  const mesh = steps.mesh
  const fit = steps.fit
  const cutoutsReady = !!lastImage && GARMENT_VIEWS.every((v) => accepted(lastImage, v))
  const columns = `minmax(110px, 140px) repeat(${GARMENT_VIEWS.length}, minmax(0, 1fr))`

  const imageCell = (spec: ImageStepSpec, index: number, view: GarmentView): ReactNode => {
    const { step, chips } = spec
    const img = steps[step]?.[view]
    const prev = index > 0 ? imageSteps[index - 1].step : undefined
    const blocked = prev && !accepted(prev, view) ? t('Run the previous step first') : undefined
    const label = `${t(stepLabels[step] || step)} · ${viewLabel(view)}`
    const mark = runMark(feedback, garment, order, step, view)
    const slot = runSlot({ step, view })
    const ring = mark === 'redo' ? 'var(--warning, #d29922)' : mark || feedback?.pending === slot
      ? 'var(--accent, #6aa9ff)' : null
    const stateLines = [
      label,
      img?.url ? (img.accepted ? t('Accepted') : t('Not accepted')) : t('No render yet'),
      img?.created_at ? formatDateTime(img.created_at, clockSettings()) : '',
      step === 'cutout' && img?.url
        ? [img.side ? `${t('Square side')} ${img.side} px` : '', upscaleText(img.upscale, t)].filter(Boolean).join(' · ')
        : '',
    ].filter(Boolean)
    return (
      <div key={view} className="ga-step-grid-cell"
        style={ring ? { outline: `2px solid ${ring}`, outlineOffset: -1 } : undefined}>
        {img?.url ? (
          <RefImage key={img.url} src={img.url} width={THUMB_W} height={THUMB_H} label={label} meta={img} compact />
        ) : (
          <div className="ga-step-grid-empty" title={t('No render yet')}>{t('No render yet')}</div>
        )}
        <div className="ga-step-grid-side">
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
            {img?.url || img?.attempts?.length ? (
              <GateIcon specs={chips || []} record={shownRecord(img)} limits={chips ? limits[step] : undefined}
                view={view} extra={stateLines} />
            ) : null}
            {img?.url && !img.accepted ? (
              <span className="ga-run-badge"
                style={{ borderColor: 'var(--danger, #f85149)', color: 'var(--danger, #f85149)' }}>
                {t('Refused')}
              </span>
            ) : null}
            <RunBadge mark={mark}
              title={mark === 'queued' ? queueText(garment, feedback, stepLabels, t) : undefined} />
          </div>
          <RunButton
            feedback={feedback}
            slot={slot}
            disabled={busy || !garment || !!blocked}
            title={blocked || `${img?.url ? t('Regenerate') : t('Generate')}: ${label}\n${t(STEP_HELP[step] || '')}`}
            ariaLabel={`${img?.url ? t('Regenerate') : t('Generate')} · ${label}`}
            label={img?.url ? '↻' : t('Generate')}
            startingLabel="…"
            onClick={() => onRun({ step, view, force: true })}
          />
          <AttemptThumbs attempts={img?.attempts ?? []} label={label} chips={chips}
            limits={chips ? limits[step] : undefined} view={view} />
        </div>
      </div>
    )
  }

  const meshText = [
    !mesh || mesh.status === 'missing' ? t('Not built yet') : mesh.status === 'refused' ? t('Refused') : t('Accepted'),
    mesh?.metrics.tris_raw != null && mesh.metrics.tris_prepared != null
      ? `${t('Triangles')} ${mesh.metrics.tris_raw.toLocaleString()} → ${mesh.metrics.tris_prepared.toLocaleString()}`
      : '',
    mesh?.metrics.backend || '',
    mesh?.created_at ? formatDateTime(mesh.created_at, clockSettings()) : '',
  ].filter(Boolean).join(' · ')
  const meshAttempts = mesh?.status === 'refused'
    ? mesh.gates.map((g, i) => `${t('Attempt')} ${num(g.attempt) ?? i + 1}: ${(g.reasons || []).join('; ') || '–'}`)
    : []
  const fitRecord = fit && fit.status !== 'missing'
    ? fit.metrics
    : garment?.failed?.step === 'fit' && garment.failed.gates?.metrics
      ? (garment.failed.gates.metrics as Record<string, unknown>)
      : null
  // garment_fit.scale_retry: the factor a too-small piece was widened by (1.0 = not widened), the largest tried.
  const widened = num(fitRecord?.scale_retry)
  const triedUpTo = num(fitRecord?.scale_retry_max)
  const widenText = widened != null && widened > 1
    ? t('Widened {pct} % to fit').replace('{pct}', String(Math.round((widened - 1) * 100)))
    : triedUpTo != null && triedUpTo > 1
      ? t('Widened up to {pct} %, still too small').replace('{pct}', String(Math.round((triedUpTo - 1) * 100)))
      : ''
  const fitText = [
    t(FIT_STATUS[fit?.status || 'missing']),
    widenText,
    fit?.tris ? `${t('Triangles')} ${fit.tris.toLocaleString()}` : '',
    fit?.created_at ? formatDateTime(fit.created_at, clockSettings()) : '',
  ].filter(Boolean).join(' · ')

  return (
    <div className="ga-step-grid" style={{ gridTemplateColumns: columns }}>
      <div />
      {GARMENT_VIEWS.map((v) => <div key={v} className="ga-step-grid-head">{viewLabel(v)}</div>)}

      {imageSteps.map((spec, index) => (
        <Fragment key={spec.step}>
          <StepLabel garment={garment} step={spec.step} label={stepLabels[spec.step] || spec.step}
            help={STEP_HELP[spec.step] || ''} />
          {GARMENT_VIEWS.map((view) => imageCell(spec, index, view))}
        </Fragment>
      ))}

      <StepLabel garment={garment} step="mesh" label={stepLabels.mesh || 'Mesh'} help={STEP_HELP.mesh} />
      <div className="ga-step-grid-row" style={{ gridColumn: `span ${GARMENT_VIEWS.length}` }}>
        <GateIcon specs={MESH_CHIPS} record={mesh?.metrics} limits={limits.mesh} extra={[meshText, ...meshAttempts]} />
        <RunBadge mark={runMark(feedback, garment, order, 'mesh')} />
        <span className="ga-hint" style={{ minWidth: 0 }}>{meshText}</span>
        <RunButton
          feedback={feedback}
          slot={runSlot({ step: 'mesh' })}
          disabled={busy || !garment || !cutoutsReady}
          title={garment && !cutoutsReady ? t('Run the previous step first') : t(STEP_HELP.mesh)}
          label={mesh && mesh.status !== 'missing' ? t('Regenerate') : t('Generate')}
          onClick={() => onRun({ step: 'mesh', force: true })}
        />
      </div>

      <StepLabel garment={garment} step="fit" label={stepLabels.fit || 'Fit'} help={STEP_HELP.fit} />
      <div className="ga-step-grid-row" style={{ gridColumn: `span ${GARMENT_VIEWS.length}` }}>
        <GateIcon specs={fitChips} record={fitRecord} limits={limits.fit} extra={[fitText]} />
        <RunBadge mark={runMark(feedback, garment, order, 'fit')} />
        <span className="ga-hint" style={{ minWidth: 0 }}>{fitText}</span>
        <RunButton
          feedback={feedback}
          slot={runSlot({ step: 'fit' })}
          disabled={busy || !garment || mesh?.status !== 'accepted'}
          title={garment && mesh?.status !== 'accepted' ? t('Run the previous step first') : t(STEP_HELP.fit)}
          label={t('Re-fit')}
          onClick={() => onRun({ step: 'fit', force: true })}
        />
      </div>
    </div>
  )
}
