/**
 * The step log of one entry — every candidate the type found, what happened
 * to it and why.
 *
 * This is where a stuck entry is diagnosed: `skipped` is the only status a
 * human can act on (the step ran out of attempts, or its subject was busy
 * every time), so it is the only one that gets a Retry button. `pending` will
 * run on its own, `running` is running, and `done`/`failed` are history.
 *
 * A REFUSED skip is the exception: its subject's own gates said no (or its
 * chain recorded a failure the automatic triggers honour), so the server
 * answers Retry with 409 "refused". The button stays visible but disabled,
 * with the explicit path beside it — spending that chain again is a person's
 * decision in the Wardrobe or the 3D tab, never the idle engine's.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { ApiError } from '../../lib/api'
import { fetchSteps, retryStep } from './api'
import { hubJobsText, stepStatus } from './types'
import type { Improvement, Step } from './types'
import { clockSettings, formatTime, useClockSettings } from '../../lib/clockFormat'

/** A system stamp (technical, not game time) rendered as a wall clock — in the
 *  configured world timezone and clock format. */
function clockTime(iso: string | null | undefined): string {
  return formatTime(iso, clockSettings())
}

const REFUSED_HINT =
  'Refused by its gates — run it explicitly from the Wardrobe or the 3D tab'

/** Green for a finished step, red for one that ended badly, muted for the
 *  ones that are still on their way. */
function statusClass(status: string): string {
  if (status === 'done') return 'ga-status-ok'
  if (status === 'failed' || status === 'skipped' || status === 'refused') {
    return 'ga-status-danger'
  }
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
  // Subscribe to the shared clock settings so the stamps above re-render
  // once the server-configured format and timezone arrive.
  useClockSettings()
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
      if (e instanceof ApiError && e.status === 409 && e.detail === 'refused') {
        // The step was refused after this log was loaded — show it as such.
        toast(t(REFUSED_HINT), 'error')
        await load()
      } else {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
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
                <th>{t('Cost')}</th>
                <th>{t('Error')}</th>
                <th>{t('Duration')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {steps.map((step) => (
                <tr key={step.candidate_key}>
                  <td>{step.candidate_label || step.candidate_key}</td>
                  <td className={statusClass(stepStatus(step))}>
                    {statusLabel(stepStatus(step))}
                  </td>
                  <td>{step.attempts || 0}</td>
                  <td>{hubJobsText(step.hub_jobs, t)}</td>
                  <td className="ga-imp-steps-error"
                    title={[step.error, step.note].filter(Boolean).join('\n')}>
                    {step.error || ''}
                    {step.note ? (
                      <div className="ga-imp-steps-note">{step.note}</div>
                    ) : null}
                  </td>
                  <td>
                    {duration(step.duration_s) || clockTime(step.finished_at)}
                  </td>
                  <td>
                    {step.status === 'skipped' && step.refused ? (
                      <>
                        <button type="button" className="ga-btn ga-btn-sm" disabled>
                          {t('Retry')}
                        </button>
                        <span className="ga-imp-refused-hint">
                          {t(REFUSED_HINT)}
                        </span>
                      </>
                    ) : step.status === 'skipped' ? (
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
