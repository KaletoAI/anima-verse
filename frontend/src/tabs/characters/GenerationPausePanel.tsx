/**
 * GenerationPausePanel — the Figure tab header's "Pause automatic generation" (Ruling A42,
 * `app/core/generation_pause.py`).
 *
 * - The switch (a checkbox beside "Build automatically"): pausing costs nothing and stops nothing that runs.
 *   While paused it stays checked and is not unchecked here — Resume does that, with its cost on it.
 * - The status light with its reason in plain words: "Automatic generation paused — N jobs held", what still
 *   runs ("Running now — it finishes: …"), and the Resume button naming the hub jobs that start
 *   ("Resume — 7 hub jobs start").
 * - The waiting jobs as a compact list, one line each ("Waiting: Wardrobe · Blazer · worn 2 + mesh 1 — 3 hub
 *   jobs") with Cancel behind an in-app confirmation (ConfirmDialog — never a native dialog). Cancel uses the
 *   owning queue's own cancel: nothing of the job has run, so nothing is left half done.
 */
import { useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { StepLight } from './FieldHairstyles'
import { PAUSE_REASON, pauseLine, resumeLabel, waitingLine } from './figureModel'
import type { GenerationPause, WaitingJob } from './figureModel'

export function GenerationPauseSwitch({ gp, busy, onPause }: {
  gp: GenerationPause
  busy: boolean
  onPause: () => void
}) {
  const { t } = useI18n()
  return (
    <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: gp.paused ? 'default' : 'pointer' }}
      title={gp.paused ? t('Paused — Resume below lifts it and says how many hub jobs start')
        : t('Nothing automatic starts for this character until you resume: outfit changes, a new body or a finished piece only collect, waiting automatic jobs are held. Buttons you press still run; a running job finishes. No jobs.')}>
      <input type="checkbox" checked={gp.paused} disabled={busy || gp.paused}
        onChange={(e) => { if (e.target.checked) onPause() }} />
      <span>{t('Pause automatic generation')}</span>
    </label>
  )
}

export function GenerationPausePanel({ gp, busy, onResume, onCancel }: {
  gp: GenerationPause
  busy: boolean
  onResume: () => void
  onCancel: (job: WaitingJob) => void
}) {
  const { t } = useI18n()
  const [asking, setAsking] = useState<WaitingJob | null>(null)
  if (!gp.paused) return null
  return (
    <div className="ga-gen-pause" role="status">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <StepLight light="yellow" title={t(PAUSE_REASON)} />
        <strong>{pauseLine(gp, t)}</strong>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy}
          title={t('Lifts the pause: the held jobs start in their original order')} onClick={onResume}>
          {resumeLabel(gp, t)}
        </button>
      </div>
      <div className="ga-hint">{t(PAUSE_REASON)}</div>
      {gp.running.length ? (
        <div className="ga-hint">
          {t('Running now — it finishes')}: {gp.running.join(' · ')}
        </div>
      ) : null}
      {gp.waiting.length ? (
        <ul className="ga-gen-pause-list">
          {gp.waiting.map((job) => (
            <li key={job.id}>
              <span className="ga-gen-pause-text" title={waitingLine(job, t)}>{waitingLine(job, t)}</span>
              <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
                title={t('Takes this job out of the queue — nothing of it has run, so nothing is left half done')}
                onClick={() => setAsking(job)}>{t('Cancel')}</button>
            </li>
          ))}
        </ul>
      ) : <div className="ga-hint">{t('Nothing waits — new automatic jobs are held here until you resume.')}</div>}
      <ConfirmDialog open={asking !== null} title={t('Cancel this waiting job?')}
        message={asking ? t('{job} — it leaves the queue and never runs. Nothing of it has run, so nothing is left half done; a Build you start later makes what is still missing.')
          .replace('{job}', asking.label) : ''}
        confirmLabel={t('Cancel job')} danger
        onConfirm={() => { if (asking) onCancel(asking); setAsking(null) }}
        onClose={() => setAsking(null)} />
    </div>
  )
}
