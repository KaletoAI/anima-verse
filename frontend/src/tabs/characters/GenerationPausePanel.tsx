/**
 * GenerationPausePanel — the Figure tab header's "Pause automatic generation" (Ruling A42,
 * `app/core/generation_pause.py`).
 *
 * - The switch (a checkbox beside "Build automatically"): pausing costs nothing and stops nothing that runs.
 *   While paused it stays checked and is not unchecked here — Resume does that, with its cost on it.
 * - The status light with its reason in plain words: "Automatic generation paused — N jobs held", what still
 *   runs ("Running now — it finishes: …"), and the Resume button naming the hub jobs that start
 *   ("Resume · 7 hub", the whole "Resume — 7 hub jobs start" on mouse-over; Ruling A90: notice lines in the right panel).
 * - The waiting jobs as a compact list, one line each ("Waiting: Wardrobe · Blazer · worn 2 + mesh 1 — 3 hub
 *   jobs") with Cancel behind an in-app confirmation (ConfirmDialog — never a native dialog). Cancel uses the
 *   owning queue's own cancel: nothing of the job has run, so nothing is left half done.
 */
import { useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { StepLight } from './StepRows'
import { PAUSE_REASON, pauseLine, resumeLabel, shortCost, waitingLine } from './figureModel'
import { LIGHT_COLOR } from './stepStyle'
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

/**
 * Ruling A90: the pause as notice lines of the Figure tab's right-hand panel (never a box above the viewer) — the
 * light with "Automatic generation paused — N jobs held" (why on mouse-over) and Resume with the hub jobs that start
 * in short form (the whole label on mouse-over); then one line for what still runs and one per waiting job with its
 * Cancel (behind an in-app confirmation).
 */
export function GenerationPausePanel({ gp, busy, onResume, onCancel }: {
  gp: GenerationPause
  busy: boolean
  onResume: () => void
  onCancel: (job: WaitingJob) => void
}) {
  const { t } = useI18n()
  const [asking, setAsking] = useState<WaitingJob | null>(null)
  if (!gp.paused) return null
  const resume = resumeLabel(gp, t)
  const short = gp.waiting.length ? `${shortCost(0, gp.resume_jobs, t)}${gp.resume_unknown ? ' + ?' : ''}` : t('no job')
  return (
    <div className="ga-gen-pause" role="status">
      <div className="ga-notice" title={t(PAUSE_REASON)}>
        <StepLight light="yellow" title={t(PAUSE_REASON)} />
        <span className="ga-one-line ga-notice-text" style={{ color: LIGHT_COLOR.yellow }}>{pauseLine(gp, t)}</span>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy} aria-label={resume}
          title={`${resume}\n${t('Lifts the pause: the held jobs start in their original order')}`} onClick={onResume}>
          {t('Resume')} · {short}
        </button>
      </div>
      {gp.running.length ? (
        <div className="ga-notice is-sub">
          <span className="ga-hint ga-one-line ga-notice-text" title={gp.running.join(' · ')}>
            {t('Running now — it finishes')}: {gp.running.join(' · ')}
          </span>
        </div>
      ) : null}
      {gp.waiting.length ? gp.waiting.map((job) => (
        <div key={job.id} className="ga-notice is-sub">
          <span className="ga-hint ga-one-line ga-notice-text" title={waitingLine(job, t)}>{waitingLine(job, t)}</span>
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
            title={t('Takes this job out of the queue — nothing of it has run, so nothing is left half done')}
            onClick={() => setAsking(job)}>{t('Cancel')}</button>
        </div>
      )) : (
        <div className="ga-notice is-sub">
          <span className="ga-hint ga-one-line ga-notice-text"
            title={t('Nothing waits — new automatic jobs are held here until you resume.')}>
            {t('Nothing waits — new automatic jobs are held here until you resume.')}
          </span>
        </div>
      )}
      <ConfirmDialog open={asking !== null} title={t('Cancel this waiting job?')}
        message={asking ? t('{job} — it leaves the queue and never runs. Nothing of it has run, so nothing is left half done; a Build you start later makes what is still missing.')
          .replace('{job}', asking.label) : ''}
        confirmLabel={t('Cancel job')} danger
        onConfirm={() => { if (asking) onCancel(asking); setAsking(null) }}
        onClose={() => setAsking(null)} />
    </div>
  )
}
