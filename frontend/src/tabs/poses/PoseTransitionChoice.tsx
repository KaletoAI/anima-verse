import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiGet, apiPost } from '../../lib/api'
import { clipWindow } from './transitionSequence'
import { TransitionSequencePreview } from './TransitionSequencePreview'
import { transitionClip, type TransitionPose, type TransitionRequest } from './PoseTransitionDialog'
import type { ClipListing } from './clipSets'
import { useTransitionModal } from './useTransitionModal'

interface AffectedRule { from: string; to: string; store: string; old_kind: string | null }
export interface TransitionJob {
  task_id: string; status: string; state?: string; phase?: string; error?: string; kind?: string
  affected_rule?: AffectedRule
  request: TransitionRequest
  candidates?: Array<{
    index: number; ok: boolean; error: string; warnings: string[]
    params: { start_time_s: number; max_tokens: number }
    metrics: { hop_cm?: number; flight_cm?: number; foot_slide_cm?: { left: number; right: number }
      final_root_error_cm?: number[]; final_yaw_error_deg?: number[]; drift_cm?: number
      travel_m?: number[]; turn_deg?: number; duration_s?: number }
  }>
}

export function PoseTransitionChoice({ job, poses, listing, onClose, onDecided }: {
  job: TransitionJob; poses: TransitionPose[]; listing: ClipListing; onClose: () => void; onDecided: () => void
}) {
  const { t } = useI18n()
  const [kind, setKind] = useState(job.kind || '')
  const [rule, setRule] = useState<AffectedRule | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const submitting = useRef(false)
  const box = useTransitionModal(onClose, busy)
  const request = job.request
  // Always fetch on reopening; never silently update an already displayed rule.
  useEffect(() => {
    let live = true
    apiGet<AffectedRule>(`/poses/transition-jobs/affected-rule?start=${encodeURIComponent(request.start_pose)}&target=${encodeURIComponent(request.target_pose)}`)
      .then((current) => { if (live) {
        setRule(current)
        const old = job.affected_rule
        if (old && (old.from !== current.from || old.to !== current.to || old.store !== current.store || old.old_kind !== current.old_kind)) setStale(true)
      } })
      .catch((e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [job.affected_rule, request.start_pose, request.target_pose])
  const start = transitionClip(poses, listing, request.start_pose, request.cset)
  const target = transitionClip(poses, listing, request.target_pose, request.cset)
  const decide = async (index?: number) => {
    if (submitting.current) return
    submitting.current = true; setBusy(true); setError('')
    try {
      await apiPost(`/poses/transition-jobs/${job.task_id}/${index === undefined ? 'discard' : 'choose'}`,
        index === undefined ? {} : { index, kind: kind.trim(), expected_old_kind: rule!.old_kind })
      onDecided()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.message === 'rule_changed') setStale(true)
      else setError((e as Error).message)
    } finally { submitting.current = false; setBusy(false) }
  }
  const display = (value: number | number[] | undefined, unit: string) => value === undefined || value === null
    ? '—' : `${(Array.isArray(value) ? value : [value]).map((v) => Number(v).toFixed(2)).join(' / ')} ${unit}`
  return createPortal(<div className="ga-modal-backdrop" onClick={() => { if (!busy) onClose() }}>
    <div ref={box} tabIndex={-1} className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Choose a transition')}
      style={{ maxWidth: 1200, width: '95vw' }} onClick={(e) => e.stopPropagation()}>
      <div className="ga-modal-header"><span>{t('Choose a transition')}</span>
        <button type="button" className="ga-modal-close" aria-label={t('Close')} disabled={busy} onClick={onClose}>×</button></div>
      <div className="ga-modal-body">
        <label>{t('Kind name')} <input className="ga-input" disabled={busy} value={kind} onChange={(e) => setKind(e.target.value)} /></label>
        {rule ? <p>{t('Writes rule: {from} → {to} ({store}) — replaces: {old}')
          .replace('{from}', rule.from).replace('{to}', rule.to).replace('{store}', rule.store).replace('{old}', rule.old_kind || t('nothing'))}</p> : <p>{t('Loading…')}</p>}
        {stale ? <p role="alert">{t('The rule changed meanwhile — reopen to see the current one')}<br />{t('Generate a new transition for the current rule.')}</p> : null}
        {error ? <p role="alert">{t('Error')}: {error}</p> : null}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(290px, 1fr))', gap: 12 }}>
          {(job.candidates || []).map((candidate) => {
            const m = candidate.metrics
            const startTime = candidate.params.start_time_s
            const targetTime = request.target_time_s
            return <div key={candidate.index} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}>
              <strong>{t('Variant {n}').replace('{n}', String(candidate.index + 1))}</strong>
              {candidate.ok ? <>
                {start && target && m.duration_s ? <TransitionSequencePreview segments={[
                  ...clipWindow(start.url, startTime, start.duration_s || 0, !!start.loop, true),
                  { url: `/poses/transition-jobs/${job.task_id}/candidates/${candidate.index}/clip.fbx`, startS: 0, endS: m.duration_s },
                  ...clipWindow(target.url, targetTime, target.duration_s || 0, !!target.loop, false),
                ]} /> : <p>{t('No resolved clip')}</p>}
                <dl>
                  <dt>{t('Hop')}</dt><dd>{display(m.hop_cm, 'cm')}</dd>
                  <dt>{t('Foot slide before foot lock (left / right)')}</dt><dd>{m.foot_slide_cm ? display([m.foot_slide_cm.left, m.foot_slide_cm.right], 'cm') : '—'}</dd>
                  <dt>{t('Final root error')}</dt><dd>{display(m.final_root_error_cm, 'cm')}</dd>
                  <dt>{t('Final yaw error')}</dt><dd>{display(m.final_yaw_error_deg, '°')}</dd>
                  <dt>{t('Drift')}</dt><dd>{display(m.drift_cm, 'cm')}</dd>
                  <dt>{t('Travel')}</dt><dd>{display(m.travel_m, 'm')}</dd>
                  <dt>{t('Turn')}</dt><dd>{display(m.turn_deg, '°')}</dd>
                  <dt>{t('Duration')}</dt><dd>{display(m.duration_s, 's')}</dd>
                </dl>
                <div>{candidate.warnings.map((warning) => <span key={warning} className="ga-badge" style={{ color: 'var(--warning, #ffc857)', marginRight: 6 }}>{t(warning)}</span>)}</div>
                <div className="ga-hint">{t('Start time (s)')}: {startTime.toFixed(2)} · {t('Token budget')}: {candidate.params.max_tokens}</div>
                <button type="button" className="ga-btn ga-btn-primary" disabled={busy || stale || !rule || !kind.trim()}
                  onClick={() => { void decide(candidate.index) }}>{t('Use this')}</button>
              </> : <p role="status">{t('Did not pass the check')}: {candidate.error}</p>}
            </div>
          })}
        </div>
      </div>
      <div className="ga-modal-footer">
        {confirmDiscard ? <><span>{t('Discard every variant of this job?')}</span>
          <button type="button" className="ga-btn" disabled={busy} onClick={() => setConfirmDiscard(false)}>{t('Cancel')}</button>
          <button type="button" className="ga-btn ga-btn-danger" disabled={busy} onClick={() => { void decide() }}>{t('Discard all')}</button></>
          : <button type="button" className="ga-btn" disabled={busy} onClick={() => setConfirmDiscard(true)}>{t('Discard all')}</button>}
        <button type="button" className="ga-btn" disabled={busy} onClick={onClose}>{t('Close')}</button>
      </div>
    </div>
  </div>, document.body)
}
