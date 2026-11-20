/**
 * TemplateCutTextureBox — the template dialog's "Texture from cut" box (plan 2026-11-20-template-cut-uv-texture,
 * Task 10). A top's pattern islands are filled from the ITEM picture by one routed image job (occasion
 * `garment_cut_texture`); the answer is registered, gated, cut and colour-matched on the server and becomes the
 * piece's atlas when the Texture field says "From cut" (a CPU re-assemble, no drape).
 *
 * It shows: the debug pattern sheet of the built piece (as soon as it is built — also with the projection and before
 * any job; click enlarges), the model template / the answer / the atlas side by side, the metrics line, the button
 * with its cost and, under it, why it cannot start. The state comes from `GET …/cut` (polled while the job runs);
 * the button posts `…/cut/generate`. Modals through `createPortal`; no native dialogs.
 */
import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface CutMetrics {
  iou?: number | null
  coverage?: number | null
  de_after?: number | null
}

interface CutRecord {
  state?: 'ready' | 'rejected' | 'failed'
  reason?: string
  metrics?: CutMetrics
  px_per_cm?: number
  upsampler_on?: boolean
  created_at?: string
}

/** `GET …/figure/template/{item}/cut` (`figure._template_cut_payload`). */
export interface TemplateCutState {
  running: boolean
  error: string
  csig: string | null
  record: CutRecord
  can_generate: boolean
  blocked_reason: string
  upscale: boolean
  islands_sha: string
  urls: { template: string; raw: string; atlas: string }
  pattern_url: string
}

const WARN: CSSProperties = { color: 'var(--warning, #d29922)' }
const DANGER: CSSProperties = { color: 'var(--danger, #f85149)' }
const THUMB = 150

/** "IoU 0.94 · coverage 0.99 · ΔE 3.1 · 17.5 px/cm" of a cut record. */
function cutMetricsLine(r: CutRecord, t: (s: string) => string): string {
  const m = r.metrics || {}
  const parts: string[] = []
  if (m.iou != null) parts.push(t('IoU {n}').replace('{n}', m.iou.toFixed(2)))
  if (m.coverage != null) parts.push(t('coverage {n}').replace('{n}', m.coverage.toFixed(2)))
  if (m.de_after != null) parts.push(t('ΔE {n}').replace('{n}', m.de_after.toFixed(1)))
  if (r.px_per_cm) parts.push(t('{n} px/cm').replace('{n}', r.px_per_cm.toFixed(1)))
  return parts.join(' · ')
}

/** A picture enlarged over the page (click closes). */
export function PictureModal({ src, label, onClose }: { src: string; label: string; onClose: () => void }) {
  return createPortal(
    <div className="ga-modal-backdrop" style={{ zIndex: 2000, cursor: 'zoom-out' }} onMouseDown={onClose}
      role="dialog" aria-modal="true" aria-label={label}>
      <img src={src} alt={label}
        style={{ maxWidth: '92vw', maxHeight: '92vh', objectFit: 'contain', margin: 'auto', display: 'block',
          background: '#fff' }} />
    </div>,
    document.body,
  )
}

/** One captioned thumbnail; click enlarges. */
function Thumb({ src, label }: { src: string; label: string }) {
  const { t } = useI18n()
  const [big, setBig] = useState(false)
  return (
    <figure style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 2, width: THUMB }}>
      <button type="button" onClick={() => setBig(true)} title={`${label}\n${t('click to enlarge')}`}
        style={{ width: THUMB, height: THUMB, padding: 0, cursor: 'zoom-in', background: '#fff',
          border: '1px solid var(--border, #30363d)', borderRadius: 4, overflow: 'hidden' }}>
        <img src={src} alt={label} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
      </button>
      <figcaption className="ga-form-hint" style={{ textAlign: 'center' }}>{label}</figcaption>
      {big ? <PictureModal src={src} label={label} onClose={() => setBig(false)} /> : null}
    </figure>
  )
}

export function TemplateCutTextureBox({ path, texture, refreshKey }: {
  /** `/characters/{c}/figure/template/{item}`. */
  path: string
  /** The Texture field as saved on the item ("projection" / "cut"). */
  texture: string
  /** Changes when the drape changes (a re-drape brings new islands, so a new pattern sheet and csig). */
  refreshKey: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [state, setState] = useState<TemplateCutState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const reload = useCallback(() => {
    apiGet<TemplateCutState>(`${path}/cut`).then(setState).catch((e) => setError((e as Error).message))
  }, [path])
  useEffect(() => { reload() }, [reload, refreshKey, texture])
  const running = !!state?.running
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(reload, 2000)
    return () => window.clearInterval(id)
  }, [running, reload])
  const make = async () => {
    setBusy(true)
    setError('')
    try {
      setState(await apiPost<TemplateCutState>(`${path}/cut/generate`, {}))
      toast(t('Texture from cut started — 1 image job'), 'success')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  if (!state) {
    return error ? <div className="ga-hint" style={WARN}>{error}</div> : null
  }
  const r = state.record || {}
  const label = t('Make texture from cut — 1 image job') + (state.upscale ? ` ${t('(+1 upscale)')}` : '')
  const pictures = ([['template', 'Model template'], ['raw', 'Answer'], ['atlas', 'Atlas']] as const)
    .filter(([k]) => state.urls[k])
  return (
    <div role="group" aria-label={t('Texture from cut')} data-template-cut={r.state || 'none'}
      style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '6px 8px',
        border: '1px solid var(--border, #30363d)', borderRadius: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <strong>{t('Texture from cut')}</strong>
        <span className="ga-hint">
          {t('The pattern pieces filled from the item picture by one image job; the result becomes the piece’s texture without a new drape.')}
        </span>
      </div>
      {texture !== 'cut' ? (
        <div className="ga-hint">
          {t('The figure shows the projection: set Texture to “From cut” and save to use the result.')}
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {state.pattern_url ? <Thumb src={state.pattern_url} label={t('Pattern pieces')} /> : null}
        {pictures.map(([k, l]) => (
          <Thumb key={k} src={state.urls[k]} label={t(l)} />
        ))}
      </div>
      {!state.pattern_url ? (
        <div className="ga-hint">{t('The pattern pieces show once the piece is built.')}</div>
      ) : null}
      {r.state === 'ready' ? (
        <div className="ga-hint" data-cut-metrics="">{cutMetricsLine(r, t)}</div>
      ) : null}
      {r.state === 'rejected' || r.state === 'failed' ? (
        <div className="ga-hint" style={r.state === 'failed' ? DANGER : WARN}>
          {t(r.state === 'rejected' ? 'Rejected: {reason} — the projection stays' : 'Failed: {reason} — the projection stays')
            .replace('{reason}', t(r.reason || 'no reason'))}
          {r.metrics && r.state === 'rejected' ? ` (${cutMetricsLine(r, t)})` : ''}
        </div>
      ) : null}
      {r.upsampler_on ? (
        <div className="ga-hint" style={WARN}>
          {t('The backend’s prompt upsampler was on — set use_prompt_upsampler: false on its entry.')}
        </div>
      ) : null}
      {state.error ? <div className="ga-hint" style={DANGER}>{t(state.error)}</div> : null}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-start' }}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy || running || !state.can_generate}
          onClick={() => { void make() }}>
          {running ? t('Rendering…') : label}
        </button>
        {state.blocked_reason ? (
          <span className="ga-hint" style={WARN} data-cut-blocked="">{t(state.blocked_reason)}</span>
        ) : null}
        {error ? <span className="ga-hint" style={DANGER}>{error}</span> : null}
      </div>
    </div>
  )
}
