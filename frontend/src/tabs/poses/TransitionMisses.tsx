import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { setLabel } from './clipSets'

/** One switch an avatar (or someone in an interaction with one) made without
 *  a bridge clip — `GET /poses/transition-misses`. */
export interface TransitionMiss {
  start_pose: string; target_pose: string; start_role: string; target_role: string; cset: string
  count: number; last_seen: string; last_game_ts: string; names: string[]; ready: boolean; problem: string
}

/** The suggested transitions: a click opens the transition dialog filled in
 *  with the row (`onPick`), "Ignore" hides it for good. A row whose rule
 *  has been written since is no longer listed by the server. */
export function TransitionMisses({ refresh, onPick }: { refresh: number; onPick: (miss: TransitionMiss) => void }) {
  const { t } = useI18n()
  const [misses, setMisses] = useState<TransitionMiss[]>([])
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let live = true
    apiGet<{ misses: TransitionMiss[] }>('/poses/transition-misses')
      .then((r) => { if (live) { setMisses(r.misses); setError('') } })
      .catch((e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [refresh, reload])
  const dismiss = (m: TransitionMiss) => {
    void apiPost('/poses/transition-misses/dismiss', {
      start_pose: m.start_pose, target_pose: m.target_pose, start_role: m.start_role, target_role: m.target_role, cset: m.cset,
    }).then(() => setReload((n) => n + 1)).catch((e: Error) => setError(e.message))
  }
  const side = (pose: string, role: string) => (role ? `${pose} (${role})` : pose)
  return (
    <div style={{ marginTop: 10 }}>
      <div className="ga-hint">{t('Suggested transitions — switches of avatars and their partners that had no transition clip')}</div>
      {error ? <p role="alert">{t('Error')}: {error}</p> : null}
      {!misses.length && !error ? <div className="ga-hint">{t('None so far.')}</div> : null}
      {misses.map((m) => (
        <div key={[m.start_pose, m.target_pose, m.start_role, m.target_role, m.cset].join('|')}
          style={{ display: 'flex', gap: 8, padding: 6, alignItems: 'center' }}>
          <button type="button" className="ga-btn ga-btn-sm" disabled={!m.ready} title={m.problem || undefined}
            onClick={() => onPick(m)}>
            {side(m.start_pose, m.start_role)} → {side(m.target_pose, m.target_role)}
          </button>
          <span className="ga-hint">
            {`${setLabel(m.cset, t)} · ${m.count}× · ${m.names.join(', ')}${m.last_game_ts ? ` · ${m.last_game_ts}` : ''}`}
          </span>
          {m.problem ? <span className="ga-hint" role="note">{m.problem}</span> : null}
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => dismiss(m)}>{t('Ignore')}</button>
        </div>
      ))}
    </div>
  )
}
