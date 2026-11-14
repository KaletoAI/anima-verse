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
 *
 * Ruling A33: a view's button runs THAT view of its step alone. Its cost
 * stands beside it before the click (`viewRuns`, the server's per-view plan:
 * the view's hub jobs plus a follow-up — a new drafted front drafts its back
 * again). A view it needs that is not accepted disables it with the plain
 * reason, and a separate "Render … first" button names what it renders first
 * and the hub jobs of the whole click. A pair whose views disagree marks the
 * view to regenerate (a view button never repairs the pair).
 *
 * Ruling A37: every stored attempt tile has "Use this" (0 jobs; the hub jobs
 * of what becomes due after it — later images, mesh — from the server's
 * estimate on the button; fit and assembly on the CPU). A refused attempt
 * taken this way shows "Accepted by you" on the view until an image it was
 * made from changes ("Acceptance voided").
 * Ruling A46: each piece-only view has "Piece-only views from" — Auto, Generated (the image edit) or From the worn view (the
 * worn view minus the body, no hub job). The choice saves on its own and runs nothing; every option names what
 * it makes due (the view, its cut-out, the mesh, the fit — hub jobs, the fit on the CPU) before it is picked,
 * the cell's light says where the view comes from and why, and what is due now stands under the picker.
 * The hair row keeps its own layout (GarmentSteps).
 */
import { Fragment } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useEnlarge } from '../../components/ZoomButton'
import { useI18n } from '../../i18n/I18nProvider'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import { RunBadge, RunButton } from './GarmentSteps'
import type { ImageStepSpec } from './GarmentSteps'
import {
  MESH_CHIPS, PIECE_VIEW_FROM, PIECE_VIEW_MADE, PIECE_VIEW_SOURCE, chipResults, num, pieceViewDueText,
  pieceViewReason, queueText, shownRecord, upscaleText,
} from './garmentStyle'
import type { ChipSpec, GarmentLimits, GarmentRunBody } from './garmentStyle'
import { MeshJobFetch } from './MeshJobFetch'
import { RefImage } from './RefImage'
import { GARMENT_VIEWS, runMark, runSlot } from './useGarment'
import type {
  AttemptUsePlan, AttemptUsePlans, GarmentImageStep, GarmentInfo, GarmentRunState, GarmentView, GateLimit,
  GateRecord, PieceViewChoice, PieceViewDue, PieceViewInfo, PieceViewOption, RunFeedback, ViewNeed, ViewRunPlan,
  ViewRunPlans,
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

/** The steps after a "Use this", named as the grid names them (the estimate's step keys). */
const FOLLOW_STEP_WORDS: Record<string, string> = {
  worn: 'worn views', ghost: 'piece-only views', cutout: 'cut-outs', mesh: 'mesh', fit: 'fit',
}

/** "Use this" on one stored attempt (Ruling A37): 0 jobs for the click itself; the label names the hub jobs of
 *  what becomes due after it (the server's estimate), the tooltip what the click does — a refused attempt is
 *  accepted by the user ("Accepted by you"), voided when an image it was made from changes. */
function UseAttemptButton({ plan, label, attempt, disabled, onUse }: {
  plan: AttemptUsePlan
  label: string
  attempt: number
  disabled: boolean
  onUse: () => void
}) {
  const { t } = useI18n()
  if (plan.in_use) {
    return <span className="ga-hint" style={{ fontSize: '0.7em' }} title={t('This attempt is the image in use')}>{t('In use')}</span>
  }
  const follow = plan.follow_up
  const jobs = follow?.hub_jobs
  const cost = follow == null ? '' : jobs == null ? t('cost unknown')
    : jobs === 0 ? t('then no hub job') : jobs === 1 ? t('then 1 hub job') : t('then {n} hub jobs').replace('{n}', String(jobs))
  const steps = (follow?.steps || []).map((s) => t(FOLLOW_STEP_WORDS[s] || s)).join(', ')
  const title = [
    `${t('Use this')}: ${label} · ${t('Attempt')} ${attempt}`,
    plan.block ? t(plan.block) : '',
    !plan.block ? t('The click itself spends no hub job.') : '',
    !plan.block && plan.passing ? t('Its gate passed: it becomes the accepted image.') : '',
    !plan.block && !plan.passing
      ? t('Its gate refused it: you accept it ("Accepted by you"). Any change of an image it was made from voids that.')
      : '',
    follow ? `${t('Then due')}: ${steps || t('nothing')} — ${follow.note}` : '',
    follow ? t('The fit and the assembly run on the CPU.') : '',
  ].filter(Boolean).join('\n')
  return (
    <button type="button" className="ga-btn ga-btn-sm" style={{ fontSize: '0.68em', padding: '0 4px' }}
      disabled={disabled || !!plan.block} title={title} aria-label={title.split('\n')[0]}
      onClick={onUse}>
      {plan.block ? t('Use this') : `${t('Use this')}${cost ? ` · ${cost}` : ''}`}
    </button>
  )
}

/** The refused/replaced attempts of an image as tiny thumbnails (click =
 *  lightbox, reason and numbers on hover) — with "Use this" under each when
 *  the caller passes the plans (Ruling A37; the clothing grid). */
export function AttemptThumbs({ attempts, label, chips, limits, view, uses, busy = false, onUse }: {
  attempts: Array<{ attempt: number; gate: GateRecord | null; url: string }>
  label: string
  chips?: ChipSpec[]
  limits?: Record<string, GateLimit>
  view: string
  /** "Use this" per attempt number (`use_runs` of the panel); absent = no button. */
  uses?: Record<string, AttemptUsePlan>
  busy?: boolean
  onUse?: (attempt: number) => void
}) {
  const { t } = useI18n()
  const enlarge = useEnlarge()
  if (!attempts.length) return null
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      {attempts.map((a) => {
        const alt = `${label} · ${t('Attempt')} ${a.attempt}`
        const zoom = enlarge({ src: a.url, alt })
        const refused = a.gate?.ok === false || !!a.gate?.reasons?.length
        const tip = [
          alt,
          a.gate ? (refused ? t('Refused') : t('Passed')) : '',
          ...chipResults(chips || [], a.gate, limits, view)
            .filter((c) => c.ok === false).map((c) => `✕ ${t(c.label)} ${c.shown} (${c.lim})`),
          ...(Array.isArray(a.gate?.reasons) ? (a.gate?.reasons as string[]) : []),
        ].filter(Boolean).join('\n')
        const plan = uses?.[String(a.attempt)]
        return (
          <div key={a.attempt} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
            <img src={a.url} alt={alt} {...zoom} title={tip}
              style={{
                ...zoom.style, width: 26, height: 34, objectFit: 'cover', borderRadius: 3,
                border: `1px solid ${refused ? 'var(--danger, #f85149)' : 'var(--success, #3fb950)'}`,
              }} />
            {plan && onUse ? (
              <UseAttemptButton plan={plan} label={label} attempt={a.attempt} disabled={busy}
                onUse={() => onUse(a.attempt)} />
            ) : null}
          </div>
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
  worn: 'Worn views: the base body wearing this piece — the front an image edit of the base front, the back a draft composited onto the base back on the CPU (no second render; when nothing of the piece shows from behind, the back stays the base back). Regenerate: one hub image job for that view (a second attempt when the gate refuses it) — that view only; a new front drafts the back again from it in the same run. The later images and the mesh are dropped, Run all or the Build makes them again.',
  ghost: 'Piece-only views: the piece alone, the body removed, aligned to the worn view. The front takes its length from the accepted back, so the back comes first. Each view comes from the image edit (Generated) or from the worn view minus the base body (no hub job) — “Piece-only views from” under the view; Auto keeps the edit for a loose piece and takes the worn view when the edit is refused or adds a part the worn piece does not have. Regenerate: one hub image job for a generated view (a second attempt when the gate refuses it), none from the worn view — that view only; the later images of the view and the mesh are dropped, Run all or the Build makes them again.',
  cutout: 'Cut-outs: the piece-only views squared and upscaled as the mesh input. Regenerate: local crop plus a routed upscale job — this step only; the mesh is dropped, Run all or the Build makes it and the fit again.',
  mesh: 'Mesh: a 3D mesh built from both cut-outs and decimated. Regenerate: one hub mesh job (a second attempt when the gate refuses it) — this step only; the fit then reads outdated and stays in use until Re-fit, Run all or the Build fits it again.',
  fit: 'Fit: the mesh fitted onto the rigged body it is worn on (the plain body, or a body shape). Re-fit runs locally — no hub job.',
}

/** Why a view needs another one, said on its disabled button (Ruling A33). */
const NEED_TEXT: Record<ViewNeed, string> = {
  source: 'This image is made from that one.',
  draft: 'The back is drafted from the front.',
  pair: 'The front takes its length from the back.',
}

/** Ruling A46b: an accepted image gated under an older gate version, being re-gated in the background. */
const CHECKING_TEXT = 'Checking against the current gate…'

function dueJobs(due: PieceViewDue[]): number {
  return due.reduce((n, d) => n + d.jobs, 0)
}

/** "Piece-only views from" of one piece-only view (Ruling A46): the picker (each option with what it makes due), the plain
 *  reason under it and what is due now. Saving runs nothing. */
function PieceViewSourcePicker({ info, label, disabled, onSet }: {
  info: PieceViewInfo
  label: string
  disabled: boolean
  onSet: (choice: PieceViewChoice) => void
}) {
  const { t } = useI18n()
  const options = info.options
  if (!options) return null
  // Ruling A46b: while the accepted image is re-gated under the current gate version, Auto names no source yet.
  const checking = !!info.checking
  const text = (choice: PieceViewChoice) => {
    const o = options[choice]
    const name = choice === 'auto'
      ? `${t('Auto')} (→ ${checking ? t('Checking…') : t(PIECE_VIEW_SOURCE[o.source])})`
      : t(PIECE_VIEW_SOURCE[choice])
    if (choice === info.choice || !o.due.length) return name
    return `${name} · ${t('then {n}').replace('{n}', upToText(dueJobs(o.due), t))} + ${t('fit')}`
  }
  const reason = info.why ? pieceViewReason(info as PieceViewOption, t) : ''
  const due = info.due || []
  const title = [
    `${t('Piece-only views from')} · ${label}`,
    checking ? t(CHECKING_TEXT) : reason,
    ...(['auto', 'generated', 'worn'] as PieceViewChoice[]).map((c) => {
      const o = options[c]
      return `${text(c)}${o.due.length ? ` — ${t('makes due')}: ${pieceViewDueText(o.due, t)}` : ` — ${t('nothing becomes due')}`}`
    }),
    t('Saving runs nothing: Run all or the Build makes what is due.'),
  ].filter(Boolean).join('\n')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <label style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', fontSize: '0.75em' }}
        title={title}>
        <span>{t('Piece-only views from')}</span>
        <select className="ga-input" style={{ fontSize: '0.95em', padding: '0 2px', maxWidth: '100%' }}
          value={info.choice} disabled={disabled} aria-label={`${t('Piece-only views from')} · ${label}`}
          onChange={(e) => onSet(e.target.value as PieceViewChoice)}>
          {(['auto', 'generated', 'worn'] as PieceViewChoice[]).map((c) => (
            <option key={c} value={c}>{text(c)}</option>
          ))}
        </select>
      </label>
      {checking ? (
        <div className="ga-hint" style={{ fontSize: '0.7em' }}>{t(CHECKING_TEXT)}</div>
      ) : due.length ? (
        <div className="ga-hint" style={{ fontSize: '0.7em', color: 'var(--warning, #d29922)' }} title={reason}>
          {t('Now due')}: {pieceViewDueText(due, t)}
        </div>
      ) : null}
    </div>
  )
}

/** "1 hub job" / "3 hub jobs" / "no hub job". */
function jobsText(n: number, t: (s: string) => string): string {
  return n === 0 ? t('no hub job') : n === 1 ? t('1 hub job') : t('{n} hub jobs').replace('{n}', String(n))
}

/** "up to 1 hub job" / "up to 3 hub jobs" / "no hub job" (first attempts; a refused attempt retries). */
function upToText(n: number, t: (s: string) => string): string {
  return n === 0 ? t('no hub job') : n === 1 ? t('up to 1 hub job') : t('up to {n} hub jobs').replace('{n}', String(n))
}

export function GarmentStepGrid({ garment, imageSteps, stepLabels, limits, fitChips, busy, onRun, feedback,
  viewRuns = null, useRuns = null, onUse, onPieceView, meshFetchUrl = null, onMeshFetched }: {
  garment: GarmentInfo | null
  imageSteps: ImageStepSpec[]
  stepLabels: Record<string, string>
  limits: GarmentLimits
  fitChips: ChipSpec[]
  busy: boolean
  onRun: (body: GarmentRunBody, slot?: string) => void
  feedback?: RunFeedback
  /** Each view button's cost and prerequisites (the panel's `view_runs`, Ruling A33); null = unknown. */
  viewRuns?: ViewRunPlans | null
  /** "Use this" on each stored attempt (the panel's `use_runs`, Ruling A37); null = no button. */
  useRuns?: AttemptUsePlans | null
  /** "Use this" clicked on `attempt` of `view` of `step` (0 jobs; the caller posts it and reloads). */
  onUse?: (step: string, view: GarmentView, attempt: number) => void
  /** Ruling A46: "Piece-only views from" of a view changed (saves only; the caller posts it and reloads). Absent =
   *  no picker. */
  onPieceView?: (view: GarmentView, choice: PieceViewChoice) => void
  /** "Fetch finished job…" on the mesh row (MeshJobFetch): its POST url, null hides it. */
  meshFetchUrl?: string | null
  /** The mesh record changed through a fetched job: reload the panel. */
  onMeshFetched?: () => void
}) {
  useClockSettings()
  const { t } = useI18n()
  const viewLabel = (view: GarmentView) => (view === 'front' ? t('Front view') : t('Back view'))
  /** "Piece-only · Back view" — a view of a step, as the cells name it. */
  const viewName = (step: string, view: GarmentView) => `${t(stepLabels[step] || step)} · ${viewLabel(view)}`
  const steps = garment?.steps ?? {}
  // A view left out after an empty drafted back counts as done.
  const accepted = (step: GarmentImageStep, view: GarmentView) =>
    !!steps[step]?.[view]?.accepted || !!steps[step]?.[view]?.skipped
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
    const plan: ViewRunPlan | undefined = viewRuns?.[step]?.[view]
    const missing = plan?.missing ?? []
    // Ruling A33: the server's plan names every view this one needs; without a plan the grid's own rule stands.
    const needs = missing.length
      ? t('Needs {what} first').replace('{what}', missing.length === 1 ? viewName(missing[0].step, missing[0].view)
        : t('{n} views').replace('{n}', String(missing.length)))
      : undefined
    const blocked = img?.skipped ? t('Not made: nothing of the piece shows from behind')
      : needs ?? (!plan && prev && !accepted(prev, view) ? t('Run the previous step first') : undefined)
    const label = viewName(step, view)
    const cost = plan && !img?.skipped
      ? `${jobsText(plan.jobs, t)}${plan.follow_up_jobs ? ` + ${t('{n} follow-up').replace('{n}', String(plan.follow_up_jobs))}` : ''}`
      : ''
    const costTitle = plan ? [
      `${t('This view')}: ${jobsText(plan.jobs, t)}`,
      ...plan.follow_up.map((f) => `${t('Then')} ${viewName(f.step, f.view)}: ${jobsText(f.jobs, t)} — ${t(NEED_TEXT[f.why])}`),
      t('First attempts — a refused attempt is tried once more.'),
    ].join('\n') : ''
    const needsTitle = missing.length ? [
      ...missing.map((m) => `${viewName(m.step, m.view)} — ${t(NEED_TEXT[m.why])}`),
    ].join('\n') : ''
    const firstTotal = plan ? plan.prerequisite_jobs + plan.jobs + plan.follow_up_jobs : 0
    const firstSlot = `${runSlot({ step, view })}|first`
    const pairRedo = garment?.pair && !garment.pair.agree && garment.pair.step === step && garment.pair.redo === view
    const mark = runMark(feedback, garment, order, step, view)
    const slot = runSlot({ step, view })
    const ring = mark === 'redo' ? 'var(--warning, #d29922)' : mark || feedback?.pending === slot
      ? 'var(--accent, #6aa9ff)' : null
    // Ruling A46: where a piece-only view comes from, and why — in the cell's light.
    const pieceView = step === 'ghost' && !img?.skipped ? garment?.piece_views?.[view] : undefined
    // Ruling A46b: re-gated under the current gate version now — the stored verdict's source and reason wait.
    const checking = !!garment?.regate_checking?.some((c) => c.step === step && c.view === view)
    const sourceLines = pieceView?.why ? [
      pieceView.made_from ? t(PIECE_VIEW_MADE[pieceView.made_from]) : '',
      !checking && pieceView.made_from && pieceView.source && pieceView.source !== pieceView.made_from
        ? t('Due: made again from {source}').replace('{source}', t(PIECE_VIEW_FROM[pieceView.source])) : '',
      checking ? '' : pieceViewReason(pieceView as PieceViewOption, t),
    ].filter(Boolean) : []
    const stateLines = [
      label,
      img?.url ? (img.accepted ? t('Accepted') : t('Not accepted')) : img?.skipped ? t('Not made: nothing of the piece shows from behind') : t('No render yet'),
      checking ? t(CHECKING_TEXT) : '',
      ...sourceLines,
      img?.empty ? t('Nothing of the piece shows from behind — the base back unchanged') : '',
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
          <div className="ga-step-grid-empty" title={img?.skipped ? t('Not made: nothing of the piece shows from behind') : t('No render yet')}>
            {img?.skipped ? t('Not made: nothing of the piece shows from behind') : t('No render yet')}
          </div>
        )}
        <div className="ga-step-grid-side">
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
            {img?.url || img?.attempts?.length ? (
              <GateIcon specs={chips || []} record={shownRecord(img)} limits={chips ? limits[step] : undefined}
                view={view} extra={stateLines} />
            ) : null}
            {img?.url && img.user_accepted?.holds ? (
              <span className="ga-run-badge"
                title={[t('Its gate refused it; you chose it with “Use this”.'), ...img.user_accepted.reasons].join('\n')}
                style={{ borderColor: 'var(--success, #3fb950)', color: 'var(--success, #3fb950)' }}>
                {t('Accepted by you')}
              </span>
            ) : img?.url && !img.accepted ? (
              <span className="ga-run-badge"
                title={img.user_accepted ? t('Your acceptance no longer holds: an image it was made from changed') : undefined}
                style={{ borderColor: 'var(--danger, #f85149)', color: 'var(--danger, #f85149)' }}>
                {img.user_accepted ? t('Acceptance voided') : t('Refused')}
              </span>
            ) : null}
            <RunBadge mark={mark}
              title={mark === 'queued' ? queueText(garment, feedback, stepLabels, t) : undefined} />
            {pairRedo ? (
              <span className="ga-run-badge"
                title={[garment?.pair?.error || '', t('Regenerate this view — or Run all renders it again.')]
                  .filter(Boolean).join('\n')}
                style={{ borderColor: 'var(--warning, #d29922)', color: 'var(--warning, #d29922)' }}>
                {t('Does not match the other view')}
              </span>
            ) : null}
          </div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
            <RunButton
              feedback={feedback}
              slot={slot}
              disabled={busy || !garment || !!blocked}
              title={blocked ? [blocked, needsTitle].filter(Boolean).join('\n')
                : [`${img?.url ? t('Regenerate') : t('Generate')}: ${label}`, costTitle, t(STEP_HELP[step] || '')]
                  .filter(Boolean).join('\n')}
              ariaLabel={`${img?.url ? t('Regenerate') : t('Generate')} · ${label}${cost ? ` · ${cost}` : ''}`}
              label={img?.url ? '↻' : t('Generate')}
              startingLabel="…"
              onClick={() => onRun({ step, view, force: true })}
            />
            {cost ? <span className="ga-hint" title={costTitle}>{cost}</span> : null}
          </div>
          {pieceView?.options && onPieceView ? (
            <PieceViewSourcePicker info={pieceView} label={label} disabled={busy || !garment}
              onSet={(choice) => onPieceView(view, choice)} />
          ) : null}
          {needs ? (
            <>
              <div className="ga-hint" title={needsTitle}>{needs}</div>
              <RunButton
                feedback={feedback}
                slot={firstSlot}
                disabled={busy || !garment}
                title={[
                  ...missing.map((m) => `${viewName(m.step, m.view)}: ${jobsText(m.jobs, t)} — ${t(NEED_TEXT[m.why])}`),
                  `${t('Then')} ${label}: ${jobsText(plan?.jobs ?? 0, t)}`,
                  ...(plan?.follow_up ?? []).map((f) => `${t('Then')} ${viewName(f.step, f.view)}: ${jobsText(f.jobs, t)}`),
                  t('First attempts — a refused attempt is tried once more.'),
                ].join('\n')}
                label={`${t('Render {what} first').replace('{what}', missing.length === 1
                  ? viewName(missing[0].step, missing[0].view) : t('{n} views').replace('{n}', String(missing.length)))}`
                  + ` — ${upToText(firstTotal, t)}`}
                onClick={() => onRun({ step, view, force: true, prerequisites: true }, firstSlot)}
              />
            </>
          ) : null}
          <AttemptThumbs attempts={img?.attempts ?? []} label={label} chips={chips}
            limits={chips ? limits[step] : undefined} view={view} uses={useRuns?.[step]?.[view]} busy={busy || !garment}
            onUse={onUse ? (n) => onUse(step, view, n) : undefined} />
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
        <MeshJobFetch url={garment ? meshFetchUrl : null} disabled={busy} onDone={() => onMeshFetched?.()} />
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
