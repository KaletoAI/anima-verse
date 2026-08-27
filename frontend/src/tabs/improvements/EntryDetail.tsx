/**
 * The step log of one entry — every candidate the type found, what happened
 * to it and why.
 *
 * This is where a stuck entry is diagnosed: `skipped` is the only status a
 * human can act on (the step ran out of attempts, or its subject was busy
 * every time), so it is the only one that gets a Retry button. `pending` will
 * run on its own, `running` is running, and `done`/`failed` are history.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { fetchSteps, retryStep } from './api'
import type { Improvement, Step } from './types'

/** A system stamp (technical, not game time) rendered as a wall clock. */
function clockTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString()
}

/** Green for a finished step, red for one that ended badly, muted for the
 *  ones that are still on their way. */
function statusClass(status: string): string {
  if (status === 'done') return 'ga-status-ok'
  if (status === 'failed' || status === 'skipped') return 'ga-status-danger'
  return 'ga-status-paused'
}

function duration(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return ''
  return seconds >= 60
    ? `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')} min`
    : `${seconds.toFixed(1)} s`
}

export function EntryDetail({
  improvement,
  statusLabel,
  onClose,
  onChanged,
}: {
  improvement: Improvement
  /** The tab's shared step-status translation — one wording for both views. */
  statusLabel: (value: string) => string
  onClose: () => void
  /** A retry moved a step back into the queue — the counters changed. */
  onChanged: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [steps, setSteps] = useState<Step[] | null>(null)
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try {
      setSteps(await fetchSteps(improvement.id))
    } catch (e) {
      setSteps([])
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [improvement.id, t, toast])

  useEffect(() => { load() }, [load])

  const retry = useCallback(async (candidateKey: string) => {
    setBusy(candidateKey)
    try {
      await retryStep(improvement.id, candidateKey)
      await load()
      onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy('')
    }
  }, [improvement.id, load, onChanged, t, toast])

  return (
    <div className="ga-imp-detail">
      <div className="ga-imp-detail-head">
        <span className="ga-form-section-label">
          {t('Steps')} — {improvement.label || improvement.type_id}
        </span>
        <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
          {t('Close')}
        </button>
      </div>
      {steps === null ? (
        <div className="ga-loading">{t('Loading…')}</div>
      ) : steps.length === 0 ? (
        <div className="ga-list-empty">{t('No steps yet')}</div>
      ) : (
        <div className="ga-imp-steps-wrap">
          <table className="ga-imp-steps">
            <thead>
              <tr>
                <th>{t('Candidate')}</th>
                <th>{t('Status')}</th>
                <th>{t('Attempts')}</th>
                <th>{t('Error')}</th>
                <th>{t('Duration')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {steps.map((step) => (
                <tr key={step.candidate_key}>
                  <td>{step.candidate_label || step.candidate_key}</td>
                  <td className={statusClass(step.status)}>
                    {statusLabel(step.status)}
                  </td>
                  <td>{step.attempts || 0}</td>
                  <td className="ga-imp-steps-error" title={step.error || ''}>
                    {step.error || ''}
                  </td>
                  <td>
                    {duration(step.duration_s) || clockTime(step.finished_at)}
                  </td>
                  <td>
                    {step.status === 'skipped' ? (
                      <button type="button" className="ga-btn ga-btn-sm"
                        disabled={busy === step.candidate_key}
                        onClick={() => retry(step.candidate_key)}>
                        {t('Retry')}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
