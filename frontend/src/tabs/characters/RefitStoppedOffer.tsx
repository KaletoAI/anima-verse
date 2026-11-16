/**
 * Ruling A162 — the piece dialog's offer after a refused CPU refit. After a base change the Build first refits the
 * existing mesh on the CPU (0 hub jobs); when that refit is refused the run STOPS for the piece and spends nothing
 * on its own. This row says why (`refit_stopped.reason`) and offers the three choices, each with its cost:
 *   - Keep the old fit as it is (0 hub jobs)  → POST …/garments/{item}/keep-previous-fit
 *   - Accept the refit anyway (0 hub jobs)    → POST …/garments/{item}/fits/plain/accept (only with a kept attempt)
 *   - Make a new mesh ({n} hub jobs)          → the forced chain from the first step (`regenerate`)
 * After "Keep" the row turns into a green note: the old fit is served; Make a new mesh stays offered.
 */
import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { RunButton } from './GarmentSteps'
import { ROW, WARN_STYLE } from './garmentStyle'
import type { GarmentRunBody } from './garmentStyle'
import type { RefitStopped, RunFeedback } from './useGarment'

export function RefitStoppedOffer({ character, itemId, stopped, regenerate, feedback, busy, onRun, onChanged }: {
  character: string
  itemId: string
  stopped: RefitStopped
  regenerate?: { step: string; hub_jobs: number | null } | null
  feedback?: RunFeedback
  busy: boolean
  onRun: (body: GarmentRunBody, slot?: string) => void
  onChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [posting, setPosting] = useState(false)
  const base = `/characters/${encodeURIComponent(character)}/garments/${encodeURIComponent(itemId)}`
  const post = async (path: string, done: string) => {
    setPosting(true)
    try {
      await apiPost(base + path, {})
      toast(t(done))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
      onChanged()
    }
  }
  const jobs = regenerate ? (regenerate.hub_jobs == null ? '?' : String(regenerate.hub_jobs)) : null
  const off = busy || posting
  return (
    <div role="status" style={{ ...ROW, gap: 8, padding: '4px 8px', borderRadius: 6,
      border: `1px solid ${stopped.kept ? 'var(--success, #3fb950)' : 'var(--warning, #d29922)'}` }}>
      {stopped.kept ? (
        <span title={stopped.reason}>{t('The old fit is kept as it is — the refit on the new body was refused.')}</span>
      ) : (
        <span style={WARN_STYLE} title={stopped.reason}>
          {t('Refit failed ({reason}) — no new mesh was made on its own.').replace('{reason}', stopped.reason)}
        </span>
      )}
      {!stopped.kept && stopped.keep_available ? (
        <button type="button" className="ga-btn ga-btn-sm" disabled={off}
          title={t('Serve the previous fit on the new body unchanged. No fit, no hub job; the figure is re-assembled on the CPU.')}
          onClick={() => void post('/keep-previous-fit', 'The old fit is kept — the figure is re-assembled (CPU only).')}>
          {t('Keep the old fit as it is (0 hub jobs)')}
        </button>
      ) : null}
      {!stopped.kept && stopped.attempt ? (
        <button type="button" className="ga-btn ga-btn-sm" disabled={off}
          title={t('Use the refused refit as it is (shown in the viewer with the failing region marked). No hub job.')}
          onClick={() => void post('/fits/plain/accept', 'Accepted — nothing spent.')}>
          {t('Accept the refit anyway (0 hub jobs)')}
        </button>
      ) : null}
      {regenerate ? (
        <RunButton feedback={feedback} slot="regenerate" disabled={off}
          onClick={() => onRun({ step: regenerate.step, force: true, chain: true }, 'regenerate')}
          title={t('New images and a new mesh for this body — the only choice here that spends hub jobs.')}
          label={t('Make a new mesh ({n} hub jobs)').replace('{n}', jobs || '?')} />
      ) : null}
    </div>
  )
}
