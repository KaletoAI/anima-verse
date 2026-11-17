/**
 * Ruling A146, corrected by A149: the post-process operations of the plain body's FULL-BODY REFERENCE. Ruling A151:
 * one compact line per operation INSIDE the reference tile, under Gallery / Upload / Clear; the state, cost and what a
 * click makes due are on mouse-over, and Preview shows the processed picture in the reference's own place. The operation runs on that one picture only; the
 * front and every view are generated from the processed copy, no generated view is processed.
 * One compact row per operation a package supplies (server `base_body.postprocess_info`; hidden without one):
 * Ruling A196: a checkbox per option for this character (no world default) — a CPU operation over the reference or a
 * text-only option of the front edit (`image_op` false: no preview, cost "Text of the front edit, no image job"; a click
 * outdates a front made from a picture, `prompt_changes`). The row shows the cost line, what a click makes
 * due (the reference changes → the front is outdated → the next Run all / Build renders the views and the base
 * model again, counted in hub jobs by the server — `postprocess_followup`), and a before/after preview of the
 * reference that stores nothing (POST …/base-body/postprocess-preview/{op}).
 * The checkbox saves at once and renders nothing: POST …/base-body/postprocess/{op} {enabled: true|false}.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { hubJobs } from './viewFacingModel'

export interface PostprocessFollowup {
  kind: 'no_reference' | 'no_front' | 'unchanged' | 'changes' | 'may_change' | string
  jobs: number | null
  /** The server's cost line of the rebuild (`base_rebuild_cost`). */
  note?: string
  dressed: boolean
}

export interface PostprocessOperation {
  id: string
  label: string
  description?: string
  /** Checked for this character (Ruling A196: a checkbox per character, no world default). */
  enabled: boolean
  /** A CPU operation over the reference (true) or a text-only option of the front edit (false). */
  image_op?: boolean
  /** What clicking the checkbox now makes due. */
  followup?: PostprocessFollowup | null
}

export interface BasePostprocessInfo {
  operations: PostprocessOperation[]
  reference?: {
    /** A full-body reference is set (without one nothing is processed). */
    set: boolean
    /** The front is made from a processed copy now. */
    processed: boolean
    steps: { op: string; found: number; seconds: number }[]
    error: string
    /** On, but the copy is not made yet (it is made when the front next reads the reference). */
    pending: boolean
  } | null
}

const POSTPROCESS_COST = 'CPU, no image job'
const PROMPT_OPTION_COST = 'Text of the front edit, no image job'
const FOLLOWUP: Record<string, string> = {
  no_reference: 'Nothing changes — there is no full-body reference to process.',
  no_front: 'No front yet — it is made from the reference as switched when it is rendered.',
  unchanged: 'The reference stays the same picture — nothing becomes due.',
  changes: 'The reference changes: the front shows as outdated, and the next Run all or Build renders the four views and the base model again ({jobs}).',
  prompt_changes: 'The front edit text changes: the front shows as outdated, and the next Run all or Build renders the four views and the base model again ({jobs}).',
  may_change: 'If it finds something, the reference changes: the front shows as outdated, and the next Run all or Build renders the four views and the base model again ({jobs}).',
}
const POSTPROCESS_DRESSED = 'Dressed views made on these views follow at their next Build.'

/** The followup sentence of a click (judged by the server). */
function postprocessDue(f: PostprocessFollowup | null | undefined, t: (s: string) => string): string {
  if (!f) return ''
  const text = FOLLOWUP[f.kind]
  const line = text ? t(text).replace('{jobs}', hubJobs(f.jobs, t)) : ''
  return [line, f.dressed ? t(POSTPROCESS_DRESSED) : ''].filter(Boolean).join(' ')
}

function OperationRow({ character, op, hasReference, stateLine, busy, onChanged, onPreview }: {
  character: string
  op: PostprocessOperation
  /** A full-body reference is set (the preview needs it). */
  hasReference: boolean
  /** The reference's state sentence (on mouse-over). */
  stateLine: string
  busy: boolean
  onChanged: () => void
  /** Shows a picture in the reference's place (null = the reference again). */
  onPreview: (url: string | null) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [posting, setPosting] = useState(false)
  const [previewing, setPreviewing] = useState(false)

  const stopPreview = () => { setPreviewing(false); onPreview(null) }

  const set = async (enabled: boolean) => {
    setPosting(true)
    try {
      const d = await apiPost<{ enabled: boolean; reference?: { error?: string } | null }>(
        `/characters/${enc}/base-body/postprocess/${encodeURIComponent(op.id)}`, { enabled })
      if (d?.reference?.error) toast(t(d.reference.error), 'error')
      else if (op.image_op === false) toast(t('Saved — nothing renders now'))
      else toast(t(d?.enabled ? 'Applied to the full-body reference — nothing renders now' : 'The original full-body reference is used again — nothing renders now'))
      stopPreview()
      onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }

  const togglePreview = async () => {
    if (previewing) { stopPreview(); return }
    setPosting(true)
    try {
      const d = await apiPost<{ before: string | null; after: string | null; found: number; seconds: number }>(
        `/characters/${enc}/base-body/postprocess-preview/${encodeURIComponent(op.id)}`, {})
      if (d?.after) { setPreviewing(true); onPreview(d.after) }
      toast(d?.after
        ? t('{n} found, {s} s').replace('{n}', String(d.found)).replace('{s}', d.seconds.toFixed(2))
        : t('Nothing found in the reference — it stays as it is.'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }

  const imageOp = op.image_op !== false
  const due = postprocessDue(op.followup, t)
  const dueLine = due ? `${t(op.enabled ? 'Unchecking it:' : 'Checking it:')} ${due}` : ''
  const cost = t(imageOp ? POSTPROCESS_COST : PROMPT_OPTION_COST)
  const title = [op.description ? t(op.description) : '', imageOp ? stateLine : '', cost, dueLine]
    .filter(Boolean).join('\n')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }} title={title}>
          <input type="checkbox" checked={op.enabled} disabled={busy || posting}
            onChange={(e) => { void set(e.target.checked) }} />
          <span>{t(op.label)}</span>
        </label>
        {imageOp && hasReference ? (
          <button type="button" className={`ga-btn ga-btn-sm${previewing ? ' ga-btn-primary' : ''}`} disabled={busy || posting}
            aria-pressed={previewing} onClick={() => { void togglePreview() }}
            title={t(previewing ? 'Show the reference as it is again' : 'Shows the processed reference in its place — nothing is stored.')}>
            {t('Preview')}
          </button>
        ) : null}
      </div>
      <div className="ga-hint ga-one-line" title={title}>
        {[t('Saved at once'), cost, dueLine].filter(Boolean).join(' · ')}
      </div>
    </div>
  )
}

export function ViewPostprocessPanel({ character, info, busy, onChanged, onPreview }: {
  character: string
  info: BasePostprocessInfo | null | undefined
  busy: boolean
  onChanged: () => void
  onPreview: (url: string | null) => void
}) {
  const { t } = useI18n()
  if (!info?.operations?.length) return null
  const ref = info.reference
  const found = (ref?.steps || []).reduce((n, s) => n + (s.found || 0), 0)
  const state = !ref?.set ? t('No full-body reference — nothing is processed.')
    : ref.error ? `${t('Post-process failed — the front is made from the original reference')}: ${ref.error}`
    : ref.processed ? t('The front is made from the processed reference ({n} found; the original is kept).').replace('{n}', String(found))
    : ref.pending ? t('The processed copy is made when the front next reads the reference.')
    : t('The front is made from the original reference.')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {info.operations.map((op) => (
        <OperationRow key={op.id} character={character} op={op} hasReference={!!ref?.set} stateLine={state}
          busy={busy} onChanged={onChanged} onPreview={onPreview} />
      ))}
      {ref?.error ? <div className="ga-hint ga-one-line" style={{ color: 'var(--danger, #e66)' }} title={state}>{state}</div> : null}
    </div>
  )
}
