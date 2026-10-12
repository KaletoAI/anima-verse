import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ClipPreview } from './ClipPreview'
import { generatorName } from './generatedClip'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/** One variant of a finished generation job, as the job listing carries it. */
export interface AnimationCandidate {
  index: number
  ok: boolean
  reasons: string[]
  frames?: number | null
  duration_s?: number | null
  preview: boolean
}

/** Pick one variant of a job that waits for a choice — or drop them all. Only
 *  the chosen variant becomes the pose's clip and catalog entry. */
export function PoseAnimationChoice({ taskId, poseKey, generator, candidates, onClose, onDecided }: {
  taskId: string
  poseKey?: string | null
  generator?: string | null
  candidates: AnimationCandidate[]
  onClose: () => void
  /** after a successful choice (with the published kind) or discard (kind '') */
  onDecided: (kind: string) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const choose = async (index: number) => {
    setBusy(true)
    try {
      const result = await apiPost<{ kind: string }>(`/poses/animations/${taskId}/choose`, { index })
      toast(t('Animation ready') + (poseKey ? `: ${poseKey}` : ''))
      onDecided(result.kind)
    } catch (error) {
      toast(t('Error') + ': ' + (error as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const discard = async () => {
    setBusy(true)
    try {
      await apiPost(`/poses/animations/${taskId}/discard`, {})
      toast(t('Variants discarded'))
      onDecided('')
    } catch (error) {
      toast(t('Error') + ': ' + (error as Error).message, 'error')
    } finally {
      setBusy(false)
      setConfirmDiscard(false)
    }
  }

  const title = t('Choose a variant') + (poseKey ? `: ${poseKey}` : '')
  return createPortal(
    <div className="ga-modal-backdrop" onClick={() => { if (!busy) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={title}
        style={{ maxWidth: 1100, width: '95vw' }} onClick={(event) => event.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{title}{generator ? ` · ${generatorName(generator)}` : ''}</span>
          <button type="button" className="ga-modal-close" aria-label={t('Close')}
            disabled={busy} onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          <div style={{ display: 'grid', gap: 10,
            gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
            {candidates.map((cand) => (
              <div key={cand.index} style={{ padding: 8, opacity: cand.ok ? 1 : 0.55,
                border: '1px solid var(--border, #30363d)', borderRadius: 6 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>
                  {t('Variant {n}').replace('{n}', String(cand.index + 1))}
                  {cand.duration_s ? ` · ${cand.duration_s.toFixed(1)} s` : ''}
                </div>
                {cand.ok && cand.preview ? (
                  <ClipPreview height={220}
                    urls={{ solo: `/poses/animations/${taskId}/candidates/${cand.index}/clip.fbx` }} />
                ) : (
                  <div className="ga-form-hint" style={{ minHeight: 80 }}>
                    {t('Did not pass the check')}: {cand.reasons.join(' ')}
                  </div>
                )}
                {cand.ok ? (
                  <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
                    style={{ marginTop: 6 }} disabled={busy} onClick={() => { void choose(cand.index) }}>
                    {t('Use this')}
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          {confirmDiscard ? (
            <>
              <span className="ga-form-hint" style={{ alignSelf: 'center' }}>
                {t('Discard every variant of this job?')}
              </span>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                onClick={() => setConfirmDiscard(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={busy}
                onClick={() => { void discard() }}>{t('Discard all')}</button>
            </>
          ) : (
            <>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                onClick={() => setConfirmDiscard(true)}>{t('Discard all')}</button>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={onClose}>
                {t('Close')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>, document.body,
  )
}
