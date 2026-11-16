import { useEffect, useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { setLabel } from './clipSets'
import { LampDot } from './StatusLamp'

/** One switch an avatar (or someone in an interaction with one) made without
 *  a bridge clip — `GET /poses/transition-misses`. */
export interface TransitionMiss {
  start_pose: string; target_pose: string; start_role: string; target_role: string; cset: string
  count: number; last_seen: string; last_game_ts: string; names: string[]; ready: boolean; problem: string
}

/** The dialog's defaults — what "Run all" sends for every suggestion (the dialog opens with the same). */
const RUN_ALL_DEFAULTS = { start_time_s: 0, target_time_s: 0, forward_m: -0.25, left_m: 0, yaw_deg: 0, backend: '', guide: null }

/** The suggested transitions: a click opens the transition dialog filled in
 *  with the row (`onPick`), "Ignore" hides it for good, "Run all" bridges every
 *  ready row with the dialog's defaults. A row whose rule has been written since
 *  is no longer listed by the server. */
export function TransitionMisses({ refresh, onPick, onCount, onStarted }: {
  refresh: number
  onPick: (miss: TransitionMiss) => void
  onCount?: (n: number) => void
  onStarted?: () => void
}) {
  const { t } = useI18n()
  const [misses, setMisses] = useState<TransitionMiss[]>([])
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [variants, setVariants] = useState(1)
  const [confirm, setConfirm] = useState(false)
  const [running, setRunning] = useState('')
  useEffect(() => {
    let live = true
    apiGet<{ misses: TransitionMiss[] }>('/poses/transition-misses')
      .then((r) => { if (live) { setMisses(r.misses); setError(''); onCount?.(r.misses.length) } })
      .catch((e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [refresh, reload, onCount])
  const dismiss = (m: TransitionMiss) => {
    void apiPost('/poses/transition-misses/dismiss', {
      start_pose: m.start_pose, target_pose: m.target_pose, start_role: m.start_role, target_role: m.target_role, cset: m.cset,
    }).then(() => setReload((n) => n + 1)).catch((e: Error) => setError(e.message))
  }
  const side = (pose: string, role: string) => (role ? `${pose} (${role})` : pose)
  const ready = misses.filter((m) => m.ready)
  const runAll = async () => {
    setConfirm(false)
    const failed: string[] = []
    for (const [i, m] of ready.entries()) {
      setRunning(`${i + 1}/${ready.length}`)
      try {
        await apiPost('/poses/transition-jobs/generate', { ...RUN_ALL_DEFAULTS, variants,
          start_pose: m.start_pose, target_pose: m.target_pose, start_role: m.start_role, target_role: m.target_role, cset: m.cset })
      } catch (e) {
        failed.push(`${side(m.start_pose, m.start_role)} → ${side(m.target_pose, m.target_role)}: ${(e as Error).message}`)
      }
    }
    setRunning('')
    setError(failed.join('; '))
    onStarted?.()
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 }}>
      <div data-testid="transitions-run-all" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {ready.length ? <>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={!!running}
            title={t('Generates a bridge for every ready suggestion with the dialog defaults (start and target at 0 s, 0.25 m apart, no guide). Each job ends with variants to choose from.')}
            onClick={() => setConfirm(true)}>
            {running ? t('Starting {n}…').replace('{n}', running)
              : t('Run all: bridge {n} (+{jobs} jobs)').replace('{n}', String(ready.length))
                .replace('{jobs}', String(ready.length * variants))}
          </button>
          <label className="ga-hint" style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            {t('Variants each')}
            <select className="ga-input" style={{ width: 'auto' }} value={variants} disabled={!!running}
              onChange={(e) => setVariants(Number(e.target.value))}>
              {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </> : <span className="ga-hint">{t('Everything is current — no suggestion is ready to bridge.')}</span>}
        <span className="ga-hint" title={t('Suggested transitions — switches of avatars and their partners that had no transition clip')}>
          {t('Switches of avatars and their partners that had no transition clip.')}
        </span>
      </div>
      {error ? <p role="alert" className="ga-hint">{t('Error')}: {error}</p> : null}
      {!misses.length && !error ? <div className="ga-hint">{t('None so far.')}</div> : null}
      <div style={{ overflowY: 'auto', minHeight: 0 }}>
        {misses.map((m) => (
          <div key={[m.start_pose, m.target_pose, m.start_role, m.target_role, m.cset].join('|')}
            style={{ display: 'grid', gridTemplateColumns: '12px minmax(0, 1.4fr) minmax(0, 2fr) auto auto', gap: 8,
              padding: '3px 0', alignItems: 'center', borderBottom: '1px solid var(--border, #30363d)' }}>
            <LampDot lamp={m.ready ? 'yellow' : 'red'}
              title={m.ready ? t('Ready to bridge — both clips exist in this set.') : m.problem || t('Not ready')} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {side(m.start_pose, m.start_role)} → {side(m.target_pose, m.target_role)}
            </span>
            <span className="ga-hint" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              title={m.problem || undefined}>
              {`${setLabel(m.cset, t)} · ${m.count}× · ${m.names.join(', ')}${m.last_game_ts ? ` · ${m.last_game_ts}` : ''}`}
              {m.problem ? ` · ${m.problem}` : ''}
            </span>
            <button type="button" className="ga-btn ga-btn-sm" disabled={!m.ready} title={m.problem || undefined}
              onClick={() => onPick(m)}>{t('Open…')}</button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => dismiss(m)}>{t('Ignore')}</button>
          </div>
        ))}
      </div>
      <ConfirmDialog open={confirm} title={t('Bridge every suggested transition')}
        confirmLabel={t('Start {jobs} jobs').replace('{jobs}', String(ready.length * variants))}
        message={t('{n} transitions × {v} variants = {jobs} hub jobs. Each ends with variants to choose from in Jobs.')
          .replace('{n}', String(ready.length)).replace('{v}', String(variants)).replace('{jobs}', String(ready.length * variants))}
        onConfirm={() => { void runAll() }} onClose={() => setConfirm(false)} />
    </div>
  )
}
