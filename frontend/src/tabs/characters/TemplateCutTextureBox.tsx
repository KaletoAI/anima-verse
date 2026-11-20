/**
 * TemplateCutTextureBox — the template dialog's Texture tab (plan 2026-11-20-template-cut-uv-texture, Task 10;
 * reworked after the user's Dario test 2026-11-20). A top's pattern islands are filled from pictures by routed image
 * jobs (occasion `garment_cut_texture`), as ONE flow per click:
 *
 *   back view (when missing) → front job (front panel, sleeves, neckband + the item picture) → back job (the back
 *   panel alone + the piece's back view) → post-processing per job → one atlas → applied to the figure (CPU).
 *
 * The click also selects Texture "From cut" (the result's only use) — said next to the button. While the flow runs
 * every job button of the piece is off (the server refuses a second flow with 409, `piece_jobs`); the tab polls and
 * re-reads the dialog when the flow ends, so the result shows without a second click.
 *
 * Layout (checklist): one status line per step with a traffic light and the plain reason; Run all with its job count
 * ("Everything is current" at 0) and one Redo per job; the pictures as small thumbnails in a grid, click enlarges
 * (in-app lightbox through `createPortal`). No native dialogs.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface CutMetrics {
  iou?: number | null
  coverage?: number | null
  de_after?: number | null
  seam_cross_de?: number | null
}

interface CutJob {
  state?: 'ready' | 'rejected' | 'failed' | 'skipped'
  reason?: string
  metrics?: CutMetrics
  backend?: string
  upsampler_on?: boolean
}

interface CutRecord {
  state?: 'ready' | 'rejected' | 'failed'
  reason?: string
  metrics?: CutMetrics
  jobs?: { front?: CutJob; back?: CutJob }
  px_per_cm?: number
  upsampler_on?: boolean
  created_at?: string
  back_view?: { made?: boolean }
}

/** One click's cost (`garment_cut_texture.job_plan`, the same reuse rule the flow runs): a job whose answer passed is
 *  kept (`reused`), so Run all after a rejected back job renders the back alone. */
export interface CutJobPlan {
  back_view: number; upscale: number; front: number; back: number; total: number; max: number; reused?: string[]
}
export interface CutPlan extends CutJobPlan {
  /** The same per Redo button. */
  redo?: { front?: CutJobPlan; back?: CutJobPlan }
}

/** `GET …/figure/template/{item}/cut` (`figure._template_cut_payload`). */
export interface TemplateCutState {
  running: boolean
  /** Where a running flow is: back_view / upscale / front / back / post / apply. */
  step: string
  error: string
  csig: string | null
  record: CutRecord
  can_generate: boolean
  blocked_reason: string
  /** A ready record exists for the current pictures and pattern. */
  current: boolean
  plan: CutPlan | null
  texture: string
  /** The figure shows the cut atlas now. */
  applied: boolean
  applied_state: string
  upscale: boolean
  has_back: boolean
  islands_sha: string
  /** The Pattern step's own reason ("" = draped with pattern pieces); `draping`: a Build drapes it now. */
  drape_reason: string
  draping: boolean
  draped_at: string
  urls: Record<string, string>
  pattern_url: string
}

const THUMB = 104

/** "IoU 0.94 · coverage 0.99 · ΔE 3.1" of a job or a record. */
function cutMetricsLine(m: CutMetrics | undefined, t: (s: string) => string, pxPerCm?: number): string {
  const parts: string[] = []
  if (m?.iou != null) parts.push(t('IoU {n}').replace('{n}', m.iou.toFixed(2)))
  if (m?.coverage != null) parts.push(t('coverage {n}').replace('{n}', m.coverage.toFixed(2)))
  if (m?.de_after != null) parts.push(t('ΔE {n}').replace('{n}', m.de_after.toFixed(1)))
  if (pxPerCm) parts.push(t('{n} px/cm').replace('{n}', pxPerCm.toFixed(1)))
  return parts.join(' · ')
}

/** A picture enlarged over the page (click or Escape closes). */
export function PictureModal({ src, label, onClose }: { src: string; label: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div className="ga-modal-backdrop" style={{ zIndex: 2000, cursor: 'zoom-out', flexDirection: 'column', gap: 6 }}
      onMouseDown={(e) => { e.stopPropagation(); onClose() }} role="dialog" aria-modal="true" aria-label={label}>
      <img src={src} alt={label}
        style={{ maxWidth: '92vw', maxHeight: '88vh', objectFit: 'contain', display: 'block', background: '#fff' }} />
      <span style={{ color: '#fff', fontSize: 12 }}>{label}</span>
    </div>,
    document.body,
  )
}

/** One captioned thumbnail; click enlarges. An empty `src` shows the `empty` text in the frame. */
export function Thumb({ src, label, empty, size = THUMB, tip }: {
  src: string; label: string; empty?: string; size?: number; tip?: string
}) {
  const { t } = useI18n()
  const [big, setBig] = useState(false)
  const frame: CSSProperties = { width: size, height: size, padding: 0, borderRadius: 4, overflow: 'hidden',
    border: '1px solid var(--border, #30363d)', display: 'flex', alignItems: 'center', justifyContent: 'center' }
  return (
    <figure style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 2, width: size }}>
      {src ? (
        <button type="button" onClick={() => setBig(true)} title={`${tip || label}\n${t('click to enlarge')}`}
          style={{ ...frame, cursor: 'zoom-in', background: '#fff' }}>
          <img src={src} alt={label} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
        </button>
      ) : (
        <div style={{ ...frame, background: 'var(--bg, #0d1117)', fontSize: 10, textAlign: 'center', padding: 4 }}
          className="ga-hint" title={tip}>{empty || t('Not made yet')}</div>
      )}
      <figcaption className="ga-form-hint" style={{ textAlign: 'center', fontSize: 10, lineHeight: 1.2 }}>{label}</figcaption>
      {big ? <PictureModal src={src} label={label} onClose={() => setBig(false)} /> : null}
    </figure>
  )
}

export type Light = 'green' | 'yellow' | 'red' | 'grey' | 'blue'

/** One step line: a traffic light, the step's name and its state in plain words (the reason on mouse-over too). */
export function StepLine({ light, label, text, tip, testid }: {
  light: Light; label: string; text: string; tip?: string; testid?: string
}) {
  const colour = light === 'blue' ? 'var(--accent, #6aa9ff)' : undefined
  return (
    <div className="ga-model3d-status-row" style={{ fontSize: 12, cursor: tip ? 'help' : 'default' }}
      title={tip || text} data-step={testid} data-light={light}>
      <span className={`ga-model3d-status-dot ga-model3d-status-${light === 'blue' ? 'grey' : light}`}
        style={{ flex: '0 0 8px', width: 8, height: 8, ...(colour ? { background: colour } : {}) }} />
      <strong style={{ flex: '0 0 auto', fontWeight: 600 }}>{label}</strong>
      <span style={{ minWidth: 0, color: 'var(--text-muted, #8b949e)', overflowWrap: 'anywhere' }}>{text}</span>
    </div>
  )
}

/** The words of a running flow's step. */
const RUN_STEP: Record<string, string> = {
  back_view: 'Rendering the back view…',
  upscale: 'Upscaling the item picture…',
  front: 'Rendering the front job…',
  back: 'Rendering the back job…',
  post: 'Checking and cutting the answer (CPU)…',
  apply: 'Applying the atlas to the figure (CPU)…',
}

/** "3 image jobs (+1 for the back view, +1 upscale)" — the cost of one click of Run all. */
function planCost(plan: CutJobPlan, t: (s: string) => string): string {
  const jobs = plan.front + plan.back
  const extra: string[] = []
  if (plan.back_view) extra.push(t('+1 for the back view, at most +2'))
  if (plan.upscale) extra.push(t('+1 upscale'))
  return t(jobs === 1 ? '{n} image job' : '{n} image jobs').replace('{n}', String(jobs))
    + (extra.length ? ` (${extra.join(', ')})` : '')
}

function jobLight(job: CutJob | undefined, running: boolean): Light {
  if (running) return 'blue'
  if (!job?.state) return 'grey'
  return job.state === 'ready' ? 'green' : job.state === 'failed' ? 'red' : job.state === 'skipped' ? 'grey' : 'yellow'
}

function jobText(job: CutJob | undefined, made: string, t: (s: string) => string, pxPerCm?: number): string {
  if (!job?.state) return t('Not made yet')
  if (job.state === 'ready') return `${t(made)} · ${cutMetricsLine(job.metrics, t, pxPerCm)}`
  if (job.state === 'skipped') return t('Not run — the job before it did not pass')
  return t(job.state === 'rejected' ? 'Rejected: {reason}' : 'Failed: {reason}')
    .replace('{reason}', t(job.reason || 'no reason'))
}

/** The Texture tab's traffic light: running blue · in use green · rejected yellow · failed red · not wanted grey ·
 *  wanted but not made (or out of date) yellow. */
function cutLight(s: TemplateCutState): Light {
  if (s.running) return 'blue'
  if (s.applied) return 'green'
  if (s.record?.state === 'failed') return 'red'
  if (s.record?.state === 'rejected') return 'yellow'
  return s.texture === 'cut' ? 'yellow' : 'grey'
}

export function TemplateCutTextureBox({ path, refreshKey, onChanged, onLight }: {
  /** `/characters/{c}/figure/template/{item}`. */
  path: string
  /** Changes when the drape changes (a re-drape brings new islands, so a new pattern sheet and csig). */
  refreshKey: string
  /** The flow ended or started (the texture field and the views changed on the server): the dialog re-reads. */
  onChanged: () => void
  /** The tab's traffic light and its reason (the box stays mounted while another tab shows, so it keeps polling). */
  onLight?: (light: Light, tip: string) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [state, setState] = useState<TemplateCutState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const wasRunning = useRef(false)
  const reload = useCallback(() => {
    apiGet<TemplateCutState>(`${path}/cut`).then(setState).catch((e) => setError((e as Error).message))
  }, [path])
  useEffect(() => { reload() }, [reload, refreshKey])
  const running = !!state?.running
  useEffect(() => {
    if (!state || !onLight) return
    const tip = state.running ? t(RUN_STEP[state.step] || 'Starting…')
      : state.applied ? t('In use — the figure was assembled again with it (CPU, 0 hub jobs)')
        : state.record?.state ? t(state.record.state === 'failed' ? 'Failed: {reason}' : 'Rejected: {reason}')
          .replace('{reason}', t(state.record.reason || 'no reason'))
          : state.texture === 'cut' ? t('The projection is shown until the texture from cut is made')
            : t('Not in use — Texture is “Projection”; making the cut selects “From cut”')
    onLight(cutLight(state), tip)
  }, [state, onLight, t])
  useEffect(() => {
    if (running) wasRunning.current = true
    else if (wasRunning.current) {
      wasRunning.current = false
      onChanged()           // the result, the texture field and the back view are new: the dialog re-reads
    }
  }, [running, onChanged])
  useEffect(() => {
    // poll while the flow runs; slowly otherwise, so a Build started elsewhere or a second tab shows up
    const id = window.setInterval(reload, running ? 2000 : 8000)
    return () => window.clearInterval(id)
  }, [running, reload])
  const make = async (only: '' | 'front' | 'back') => {
    setBusy(true)
    setError('')
    try {
      setState(await apiPost<TemplateCutState>(`${path}/cut/generate`, { only }))
      toast(t('Texture from cut started'), 'success')
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  if (!state) {
    return error ? <div className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>{error}</div>
      : <div className="ga-hint">{t('Loading…')}</div>
  }
  const r = state.record || {}
  const jobs = r.jobs || {}
  const plan = state.plan
  const step = state.running ? state.step : ''
  const off = busy || running || !state.can_generate
  // the drape's reason is said by the Pattern line; under the button only what else keeps it off
  const why = state.blocked_reason && state.blocked_reason !== state.drape_reason ? t(state.blocked_reason) : ''
  const offTip = state.blocked_reason ? t(state.blocked_reason) : ''
  const u = state.urls || {}
  // a Redo is offered once there is something to redo; its label carries the server's count (`plan.redo`), which is 2
  // image jobs when the other job's answer did not pass (then nothing can be kept)
  const redoFront = plan?.redo?.front
  const redoBack = plan?.redo?.back
  const canRedoFront = !!r.state && !!redoFront
  const canRedoBack = !!r.state && !!redoBack
  const redoTip = (job: 'front' | 'back', p: CutJobPlan | undefined): string => {
    if (!p) return ''
    const other = job === 'front' ? 'back' : 'front'
    if (state.has_back && !(p.reused || []).includes(other)) {
      return t(job === 'front'
        ? 'Renders both jobs: the back job’s answer did not pass, so there is nothing to keep'
        : 'Renders both jobs: the front job’s answer did not pass, so there is nothing to keep')
    }
    return t(job === 'front' ? 'Renders the front job again and keeps the back job’s answer'
      : 'Renders the back job again and keeps the front job’s answer')
  }
  const runLabel = state.current
    ? t('Everything is current')
    : `${t('Make texture from cut')} — ${plan ? planCost(plan, t) : ''}`
  const runTitle = state.current ? t('Nothing to make: the texture from cut matches the pattern and the pictures') : ''
  const appliedText = state.applied
    ? t('In use — the figure was assembled again with it (CPU, 0 hub jobs)')
    : state.texture !== 'cut'
      ? t('Not in use — Texture is “Projection”; making the cut selects “From cut”')
      : r.state === 'ready'
        ? t('Waiting for the figure to be assembled again (CPU)')
        : t('The projection is shown until the texture from cut is made')
  return (
    <div role="group" aria-label={t('Texture from cut')} data-template-cut={r.state || 'none'}
      data-cut-running={running ? step || 'start' : ''}
      style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 14, alignItems: 'start' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
        <div className="ga-hint">
          {t('The pattern pieces are filled from pictures: the front job paints the front panel, the sleeves and the neckband from the item picture; the back job paints the back panel from the piece’s back view. The atlas replaces the projection without a new drape.')}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }} aria-label={t('Steps')}>
          <StepLine testid="drape" label={t('Pattern')}
            light={state.draping ? 'blue' : state.drape_reason ? 'yellow' : 'green'}
            text={state.drape_reason ? t(state.drape_reason)
              : t('Draped {at} — the pattern pieces are ready').replace('{at}', state.draped_at.replace('T', ' ').slice(0, 16))} />
          {state.has_back ? (
            <StepLine testid="back_view" label={t('Back view')}
              light={step === 'back_view' ? 'blue' : plan?.back_view ? 'yellow' : 'green'}
              text={step === 'back_view' ? t(RUN_STEP.back_view)
                : plan?.back_view ? t('Missing — Make texture from cut renders it first (1 image job, at most 2)')
                  : t('Ready — Picture 2 of the back job (Views tab)')} />
          ) : null}
          <StepLine testid="front" label={t('Front job')} light={jobLight(jobs.front, step === 'front' || step === 'upscale')}
            text={step === 'front' || step === 'upscale' ? t(RUN_STEP[step]) : jobText(jobs.front, 'Made', t, r.px_per_cm)}
            tip={jobs.front?.backend ? `${t('Backend')}: ${jobs.front.backend}` : undefined} />
          {state.has_back ? (
            <StepLine testid="back" label={t('Back job')} light={jobLight(jobs.back, step === 'back')}
              text={step === 'back' ? t(RUN_STEP.back) : jobText(jobs.back, 'Made', t)}
              tip={jobs.back?.backend ? `${t('Backend')}: ${jobs.back.backend}` : undefined} />
          ) : null}
          <StepLine testid="atlas" label={t('Atlas')}
            light={step === 'post' ? 'blue' : r.state === 'ready' ? 'green' : r.state ? (r.state === 'failed' ? 'red' : 'yellow') : 'grey'}
            text={step === 'post' ? t(RUN_STEP.post) : r.state === 'ready'
              ? `${t('Composed from both jobs')}${r.metrics?.seam_cross_de != null ? ` · ${t('front/back seams ΔE {n}').replace('{n}', r.metrics.seam_cross_de.toFixed(1))}` : ''}`
              : r.state ? t(r.state === 'failed' ? 'Failed: {reason}' : 'Rejected: {reason}').replace('{reason}', t(r.reason || 'no reason'))
                + ` — ${t('the projection stays')}` : t('Not made yet')} />
          <StepLine testid="figure" label={t('On the figure')}
            light={step === 'apply' ? 'blue' : state.applied ? 'green' : r.state === 'ready' ? 'yellow' : 'grey'}
            text={step === 'apply' ? t(RUN_STEP.apply) : appliedText} />
        </div>
        {r.upsampler_on ? (
          <div className="ga-hint" style={{ color: 'var(--warning, #d29922)' }}>
            {t('The backend’s prompt upsampler was on — set use_prompt_upsampler: false on its entry.')}
          </div>
        ) : null}
        {state.error ? <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{t(state.error)}</div> : null}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <button type="button" className="ga-btn ga-btn-primary ga-btn-sm" data-cut-run=""
              disabled={off || state.current} title={runTitle || offTip || undefined}
              onClick={() => { void make('') }}>
              {running ? t(RUN_STEP[step] || 'Starting…') : runLabel}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" disabled={off || !canRedoFront} data-cut-redo="front"
              title={offTip || (canRedoFront ? redoTip('front', redoFront) : t('Make the texture from cut first'))}
              onClick={() => { void make('front') }}>
              {`${t('Redo front job')} — ${redoFront ? planCost(redoFront, t) : ''}`}
            </button>
            {state.has_back ? (
              <button type="button" className="ga-btn ga-btn-sm" disabled={off || !canRedoBack} data-cut-redo="back"
                title={offTip || (canRedoBack ? redoTip('back', redoBack) : t('Make the texture from cut first'))}
                onClick={() => { void make('back') }}>
                {`${t('Redo back job')} — ${redoBack ? planCost(redoBack, t) : ''}`}
              </button>
            ) : null}
          </div>
          {why && !running ? <span className="ga-hint" style={{ color: 'var(--warning, #d29922)' }} data-cut-blocked="">{why}</span> : null}
          {running ? <span className="ga-hint" style={{ color: 'var(--accent, #6aa9ff)' }}>
            {t('The other job buttons of this piece are off until it is done.')}</span> : null}
          {state.texture !== 'cut' && !running ? (
            <span className="ga-hint" data-cut-selects="">{t('Starting it also sets Texture to “From cut” — that is the only use of the result.')}</span>
          ) : null}
          {error ? <span className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{error}</span> : null}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(4, ${THUMB}px)`, gap: '6px 8px' }} data-cut-thumbs="">
        <Thumb src={state.pattern_url} label={t('Pattern pieces')} empty={t('Shown once draped')} />
        <Thumb src={u.template_front || ''} label={t('Front template')} />
        <Thumb src={u.item || ''} label={t('Item picture')} tip={t('Picture 2 of the front job')} />
        <Thumb src={u.raw_front || ''} label={t('Front answer')} />
        <Thumb src={u.atlas || ''} label={t('Atlas')} />
        {state.has_back ? (
          <>
            <Thumb src={u.template_back || ''} label={t('Back template')} />
            <Thumb src={u.back_ref || ''} label={t('Back view')} tip={t('Picture 2 of the back job')} />
            <Thumb src={u.raw_back || ''} label={t('Back answer')} />
          </>
        ) : null}
      </div>
    </div>
  )
}
