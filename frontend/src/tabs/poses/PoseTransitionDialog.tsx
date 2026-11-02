import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { ClipPreview } from './ClipPreview'
import { TransitionPlacementPreview } from './TransitionPlacementPreview'
import { orderSets, setLabel, type ClipListing } from './clipSets'
import { useTransitionModal } from './useTransitionModal'
import { transitionClip, transitionOptions, transitionSets, type TransitionPose } from './transitionSelection'

export interface TransitionRequest {
  start_pose: string; target_pose: string; start_role: string; target_role: string; cset: string; start_time_s: number; target_time_s: number
  forward_m: number; left_m: number; yaw_deg: number; variants: number; backend: string
}

export function PoseTransitionDialog({ poses, listing, onClose, onStarted }: {
  poses: TransitionPose[]; listing: ClipListing; onClose: () => void; onStarted: () => void
}) {
  const { t } = useI18n()
  const [request, setRequest] = useState<TransitionRequest>({ start_pose: 'walking', target_pose: 'sitting',
    start_role: '', target_role: '', cset: '', start_time_s: 0, target_time_s: 0, forward_m: -0.25, left_m: 0, yaw_deg: 0, variants: 3, backend: '' })
  const [guideEnabled, setGuideEnabled] = useState(false)
  const [guide, setGuide] = useState({ kind: '', time_s: 0, forward_m: 0, left_m: 0, yaw_deg: 0 })
  const [backends, setBackends] = useState<Array<{ name: string; available: boolean }>>([])
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  const [error, setError] = useState('')
  const box = useTransitionModal(onClose, busy)
  useEffect(() => {
    let live = true
    apiGet<{ backends: typeof backends }>('/poses/transition-jobs/backends')
      .then((r) => { if (live) setBackends(r.backends) })
      .catch((e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [])
  const start = transitionClip(poses, listing, request.start_pose, request.cset, request.start_role)
  const target = transitionClip(poses, listing, request.target_pose, request.cset, request.target_role)
  const guideClips = listing.clips.filter((c) => !c.role && /\.fbx(?:\?|$)/i.test(c.url)
    && ((c.set || '') === request.cset || !c.set))
  const guideClip = guideClips.find((c) => c.kind === guide.kind && (c.set || '') === request.cset)
    || guideClips.find((c) => c.kind === guide.kind)
  const options = transitionOptions(poses, listing)
  const elsewhere = (pose: string, role: string) => {
    const sets = transitionSets(poses, listing, pose, role)
    return sets.includes(request.cset) || sets.includes('') ? '' : sets.map((set) => setLabel(set, t)).join(', ')
  }
  const targetPartners = request.target_role && target ? options.filter((o) => o.pose === request.target_pose && o.role !== request.target_role)
    .map((o) => transitionClip(poses, listing, o.pose, request.cset, o.role)).filter((c) => c !== undefined) : []
  const constrained = ['seat', 'ground', 'lie'].includes(poses.find((p) => p.key === request.target_pose)?.group || '')
  const numberField = (label: string, value: number, min: number, max: number, step: number, change: (v: number) => void) => (
    <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
      <span style={{ minWidth: 130 }}>{label}</span>
      <input aria-label={label} type="range" min={min} max={max} step={step} value={value} disabled={busy}
        onChange={(e) => change(Number(e.target.value))} />
      <input aria-label={label} className="ga-input" style={{ width: 90 }} type="number" required
        min={min} max={max} step={step} value={value} disabled={busy}
        onChange={(e) => change(Number(e.target.value))} />
    </label>
  )
  const submit = async () => {
    if (submitting.current || !start || !target) return
    submitting.current = true; setBusy(true); setError('')
    try {
      await apiPost('/poses/transition-jobs/generate', { ...request,
        yaw_deg: request.yaw_deg === -180 ? 180 : request.yaw_deg,
        guide: guideEnabled ? { ...guide, set: request.cset, yaw_deg: guide.yaw_deg === -180 ? 180 : guide.yaw_deg } : null })
      onStarted()
    } catch (e) { setError((e as Error).message) }
    finally { submitting.current = false; setBusy(false) }
  }
  return createPortal(<div className="ga-modal-backdrop" onClick={() => { if (!busy) onClose() }}>
    <div ref={box} tabIndex={-1} className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Generate transition')}
      style={{ maxWidth: 1000, width: '95vw' }} onClick={(e) => e.stopPropagation()}>
      <form style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }} onSubmit={(e) => { e.preventDefault(); void submit() }}>
        <div className="ga-modal-header"><span>{t('Generate transition')}</span>
          <button type="button" className="ga-modal-close" aria-label={t('Close')} disabled={busy} onClick={onClose}>×</button></div>
        <div className="ga-modal-body">
          <label>{t('Set')} <select className="ga-input" disabled={busy} value={request.cset} onChange={(e) => {
            setRequest({ ...request, cset: e.target.value, start_time_s: 0, target_time_s: 0 }); setGuide({ ...guide, time_s: 0 })
          }}>{orderSets([...new Set(['', 'female', 'male', ...(listing.clip_sets || listing.sets || []), ...listing.clips.map((c) => c.set || '')])])
              .map((set) => <option key={set} value={set}>{setLabel(set, t)}</option>)}</select></label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}>
            {(['start', 'target'] as const).map((side) => {
              const clip = side === 'start' ? start : target
              const poseField = side === 'start' ? 'start_pose' : 'target_pose'
              const roleField = side === 'start' ? 'start_role' : 'target_role'
              const timeField = side === 'start' ? 'start_time_s' : 'target_time_s'
              return <div key={side}>
                <label>{side === 'start' ? t('Start pose') : t('Target pose')}
                  <select className="ga-input" disabled={busy} value={`${request[poseField]}:${request[roleField]}`} onChange={(e) => {
                    const [pose, role] = e.target.value.split(':')
                    setRequest({ ...request, [poseField]: pose, [roleField]: role, [timeField]: 0 })
                  }}>
                    {options.map(({ pose, role }) => {
                      const only = elsewhere(pose, role)
                      const label = role ? `${pose} (${role.toUpperCase()})` : pose
                      return <option key={`${pose}:${role}`} value={`${pose}:${role}`} disabled={!!only}>
                        {only ? `${label} — ${t('only in set')} ${only}` : label}</option>
                    })}
                  </select></label>
                {clip ? <ClipPreview urls={{ solo: clip.url }} height={190} /> : <p>{elsewhere(request[poseField], request[roleField])
                  ? `${t('Not in this set — choose the set')}: ${elsewhere(request[poseField], request[roleField])}` : t('No resolved clip')}</p>}
                {numberField(side === 'start' ? t('Start time (s)') : t('Target time (s)'), request[timeField],
                  0, clip?.duration_s || 0, 0.01, (value) => setRequest({ ...request, [timeField]: value }))}
              </div>
            })}
          </div>
          {numberField(t('Forward (m)'), request.forward_m, -2, 2, 0.01, (v) => setRequest({ ...request, forward_m: v }))}
          {numberField(t('Left (m)'), request.left_m, -2, 2, 0.01, (v) => setRequest({ ...request, left_m: v }))}
          {numberField(t('Turn (°)'), request.yaw_deg, -180, 180, 1, (v) => setRequest({ ...request, yaw_deg: v }))}
          {start && target ? <TransitionPlacementPreview startUrl={start.url} targetUrl={target.url}
            startTimeS={request.start_time_s} targetTimeS={request.target_time_s}
            forwardM={request.forward_m} leftM={request.left_m} yawDeg={request.yaw_deg} targetClip={target} targetPartners={targetPartners}
            targetGroup={poses.find((p) => p.key === request.target_pose)?.group} /> : null}
          <details><summary>{t('Guide (optional)')}</summary>
            <label><input type="checkbox" checked={guideEnabled} disabled={busy} onChange={(e) => setGuideEnabled(e.target.checked)} />{t('Enable guide')}</label>
            {guideEnabled ? <>
              <label>{t('Clip kind')} <select required className="ga-input" disabled={busy} value={guide.kind}
                onChange={(e) => setGuide({ ...guide, kind: e.target.value, time_s: 0 })}>
                <option value="">{t('Choose a clip')}</option>
                {[...new Set(guideClips.map((c) => c.kind))].map((kind) => <option key={kind}>{kind}</option>)}
              </select></label>
              {numberField(t('Guide time (s)'), guide.time_s, 0, guideClip?.duration_s || 0, 0.01, (v) => setGuide({ ...guide, time_s: v }))}
              {numberField(t('Forward (m)'), guide.forward_m, -2, 2, 0.01, (v) => setGuide({ ...guide, forward_m: v }))}
              {numberField(t('Left (m)'), guide.left_m, -2, 2, 0.01, (v) => setGuide({ ...guide, left_m: v }))}
              {numberField(t('Turn (°)'), guide.yaw_deg, -180, 180, 1, (v) => setGuide({ ...guide, yaw_deg: v }))}
            </> : null}
          </details>
          <details><summary>{t('Advanced')}</summary>
            <p>{t('Fixed target settings')}: {t('Pose count')} {constrained ? 1 : 4}; {t('Hips constrained')} {constrained ? t('Yes') : t('No')}; {t('Early frames')} 0</p>
            <p>{t('Fixed guide settings')}: {t('Pose count')} 4; {t('Hips constrained')} {t('No')}; {t('Early frames')} 10</p>
          </details>
          <label>{t('Variants')} <select className="ga-input" disabled={busy} value={request.variants}
            onChange={(e) => setRequest({ ...request, variants: Number(e.target.value) })}>
            {[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}</select></label>
          <label>{t('Model')} <select className="ga-input" disabled={busy} value={request.backend}
            onChange={(e) => setRequest({ ...request, backend: e.target.value })}>
            <option value="">{t('Auto (routing)')}</option>
            {backends.map((b) => <option key={b.name} disabled={!b.available} value={b.name}>{b.name}{b.available ? '' : ` — ${t('unavailable')}`}</option>)}
          </select></label>
          {error ? <p role="alert">{t('Error')}: {error}</p> : null}
        </div>
        <div className="ga-modal-footer"><button type="button" className="ga-btn" disabled={busy} onClick={onClose}>{t('Cancel')}</button>
          <button type="submit" className="ga-btn ga-btn-primary" disabled={busy || !start || !target || (!!request.start_role && !!request.target_role && request.start_role !== request.target_role) || request.start_pose === request.target_pose || (guideEnabled && !guideClip)}>{t('Generate')}</button></div>
      </form>
    </div>
  </div>, document.body)
}
