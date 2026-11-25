/**
 * ShapeViewRegenerate — Regenerate ONE view of the worn body shape (round 2026-11-25, Henrik's naked back): a button
 * that opens the in-app confirmation (ConfirmDialog, a portal) naming the cost — the view's image jobs (front 1, a
 * back or side 2: the turn and the draft) and that the next Build meshes the body shape anew — and then posts
 * `POST /characters/{c}/figure/shape-view {view}` (admin-only; 409 while a Build or another body step runs).
 * Used by the Figure tab's Body sub-tab (beside each shape thumbnail) and its Dressed views (the back's way back to
 * the shape it is copied from).
 */
import { useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { SHAPE_VIEW_LABELS, shapeViewCost } from './shapeViewModel'

export function ShapeViewRegenerate({ character, view, jobs, label, disabledReason, onStarted }: {
  character: string
  view: string
  /** Image jobs of this view's Regenerate (server: `base_body.shape_view_jobs_of`). */
  jobs: number
  /** The button text; defaults to "↻ Regenerate · N image jobs". */
  label?: string
  /** Why the button cannot be used now (a Build runs …), null when it can. */
  disabledReason?: string | null
  onStarted?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [posting, setPosting] = useState(false)
  const viewName = t(SHAPE_VIEW_LABELS[view] || view)
  const run = async () => {
    setOpen(false)
    if (posting) return
    setPosting(true)
    try {
      await apiPost(`/characters/${encodeURIComponent(character)}/figure/shape-view`, { view })
      toast(t('Started — the body shape’s view renders anew'), 'success')
      onStarted?.()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }
  const short = jobs === 1 ? t('1 image job') : t('{n} image jobs').replace('{n}', String(jobs))
  return (
    <>
      <button type="button" className="ga-btn ga-btn-sm" disabled={!!disabledReason || posting}
        title={disabledReason || shapeViewCost(jobs, t)} onClick={() => setOpen(true)}>
        {label ?? `↻ ${t('Regenerate')} · ${short}`}
      </button>
      <ConfirmDialog open={open} title={t('Regenerate this body shape view: {view}?').replace('{view}', viewName)}
        message={`${t('A new draft is made, never the stored one reused; a draft that loses the clothing is refused and tried again, never published.')} ${shapeViewCost(jobs, t)}`}
        confirmLabel={t('Regenerate')} onConfirm={() => { void run() }} onClose={() => setOpen(false)} />
    </>
  )
}
