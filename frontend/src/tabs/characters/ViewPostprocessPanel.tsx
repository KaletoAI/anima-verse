/**
 * Ruling A146: the reference-view post-process operations under the base views (Characters → Base body → Views).
 * One compact row per operation a package supplies (server `base_body.postprocess_info`; hidden without one):
 * the switch (this character: on / off / world default), the cost line "CPU, no image job", what a click makes
 * due (the stored base model's rebuild, judged by the server — `postprocess_followup`), and a before/after
 * preview of one view that stores nothing (POST …/base-body/images/{view}/postprocess-preview/{op}).
 * The switch saves and applies at once: POST …/base-body/postprocess/{op} {enabled}.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { RefImage } from './RefImage'
import { FOLLOWUP_TEXT, hubJobs } from './viewFacingModel'
import type { BaseView } from './useBaseBody'

export interface PostprocessFollowup {
  kind: string
  jobs: number | null
  views: BaseView[]
  dressed: boolean
}

export interface PostprocessOperation {
  id: string
  label: string
  description?: string
  views?: BaseView[]
  /** The character's own choice (null/undefined = the world default). */
  own?: boolean | null
  world_default: boolean
  enabled: boolean
  /** What clicking the switch now makes due. */
  followup?: PostprocessFollowup | null
}

export interface BasePostprocessInfo {
  operations: PostprocessOperation[]
}

const POSTPROCESS_COST = 'CPU, no image job'
const POSTPROCESS_DRESSED = 'Dressed views composited onto these views follow them at their next Build.'

/** The followup sentence of a click (the mirror's texts: the same base-model record decides). */
function postprocessDue(f: PostprocessFollowup | null | undefined, t: (s: string) => string): string {
  if (!f) return ''
  const text = FOLLOWUP_TEXT[f.kind]
  const line = text ? t(text).replace('{jobs}', hubJobs(f.jobs, t)) : ''
  return [line, f.dressed && f.kind !== 'no_model' ? t(POSTPROCESS_DRESSED) : ''].filter(Boolean).join(' ')
}

function OperationRow({ character, op, stored, busy, onChanged }: {
  character: string
  op: PostprocessOperation
  /** Views with a stored image. */
  stored: BaseView[]
  busy: boolean
  onChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [posting, setPosting] = useState(false)
  const views = (op.views || []).filter((v) => stored.includes(v))
  const [view, setView] = useState<BaseView | ''>(views[0] || '')
  const [preview, setPreview] = useState<{ before: string | null; after: string | null; found: number; seconds: number } | null>(null)

  const set = async (enabled: boolean | null) => {
    setPosting(true)
    try {
      const d = await apiPost<{ enabled: boolean; errors?: Record<string, string> }>(
        `/characters/${enc}/base-body/postprocess/${encodeURIComponent(op.id)}`, { enabled })
      const errs = Object.entries(d?.errors || {})
      if (errs.length) toast(errs.map(([v, e]) => `${v}: ${t(e)}`).join('\n'), 'error')
      else toast(t(d?.enabled ? 'Applied to the stored views — no image job' : 'Stored views restored — no image job'))
      setPreview(null)
      onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }

  const runPreview = async () => {
    if (!view) return
    setPosting(true)
    try {
      setPreview(await apiPost(`/characters/${enc}/base-body/images/${view}/postprocess-preview/${encodeURIComponent(op.id)}`, {}))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }

  const choice = op.own === true ? 'on' : op.own === false ? 'off' : 'world'
  const due = postprocessDue(op.followup, t)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="ga-chip" title={op.description ? t(op.description) : ''}
          style={{ background: op.enabled ? 'var(--success-bg, #1f3d2a)' : undefined }}>
          {t(op.label)}: {op.enabled ? t('on') : t('off')}
        </span>
        <select className="ga-input ga-input-sm" style={{ width: 'auto' }} disabled={busy || posting} value={choice}
          title={t('This character: on, off, or the world default (Game-Admin → Setup). Saving applies it to the stored views at once.')}
          onChange={(e) => { void set(e.target.value === 'on' ? true : e.target.value === 'off' ? false : null) }}
          aria-label={t('Post-process for this character')}>
          <option value="world">{t('World default')} ({op.world_default ? t('on') : t('off')})</option>
          <option value="on">{t('On for this character')}</option>
          <option value="off">{t('Off for this character')}</option>
        </select>
        <span className="ga-hint">{t(POSTPROCESS_COST)}</span>
        {views.length ? (
          <>
            <select className="ga-input ga-input-sm" style={{ width: 'auto' }} value={view}
              onChange={(e) => { setView(e.target.value as BaseView); setPreview(null) }} aria-label={t('Preview view')}>
              {views.map((v) => <option key={v} value={v}>{t(v)}</option>)}
            </select>
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy || posting} onClick={() => { void runPreview() }}
              title={t('Shows before and after on this view — nothing is stored.')}>
              {t('Preview')}
            </button>
          </>
        ) : null}
      </div>
      {due ? <div className="ga-hint" style={{ overflowWrap: 'anywhere' }}>
        {t(op.enabled ? 'Turning it off:' : 'Turning it on:')} {due}</div> : null}
      {preview ? (
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          {preview.before ? <div style={{ width: 90 }}><RefImage src={preview.before} height={140} label={t('Before')} compact /></div> : null}
          {preview.after ? <div style={{ width: 90 }}><RefImage src={preview.after} height={140} label={t('After')} compact /></div>
            : <span className="ga-hint">{t('Nothing found in this view — it stays as it is.')}</span>}
          <span className="ga-hint">
            {t('{n} found, {s} s').replace('{n}', String(preview.found)).replace('{s}', preview.seconds.toFixed(2))}
          </span>
        </div>
      ) : null}
    </div>
  )
}

export function ViewPostprocessPanel({ character, info, stored, busy, onChanged }: {
  character: string
  info: BasePostprocessInfo | null | undefined
  stored: BaseView[]
  busy: boolean
  onChanged: () => void
}) {
  const { t } = useI18n()
  if (!info?.operations?.length) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="ga-hint">{t('Post-processing of the stored views (runs on the CPU after a view is rendered; the original is kept):')}</div>
      {info.operations.map((op) => (
        <OperationRow key={op.id} character={character} op={op} stored={stored} busy={busy} onChanged={onChanged} />
      ))}
    </div>
  )
}
