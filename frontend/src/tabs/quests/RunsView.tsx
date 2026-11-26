import { Fragment, useCallback, useEffect, useState } from 'react'
import { ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { cancelRun, fetchRuns, questError } from './api'
import type { RunRow } from './api'
import { RUN_OPEN_STATES, RUN_STATES, questErrorText, stepProgress } from './questsModel'

const POLL_INTERVAL_MS = 15_000
const FILTER_KEY = 'ga-quests-runs-state'

const STATE_LABELS: Record<string, string> = {
  preparing: 'Preparing',
  hidden: 'Hidden',
  open: 'Open',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
  broken: 'Broken',
}

function stateClass(state: string): string {
  if (state === 'open' || state === 'done') return 'ga-tag ga-status-ok'
  if (state === 'failed' || state === 'broken') return 'ga-tag ga-tag-missing'
  return 'ga-tag ga-status-paused'
}

/** One binding (D6) as a single readable value: the label frozen at start (a name), else the raw ids. */
function bindingText(b: Record<string, string>, label: string | undefined): string {
  if (label) return label
  if (b.name) return b.name
  if (b.item_id) return b.item_id
  return [b.location_id, b.room_id].filter(Boolean).join(' / ')
}

function initialFilter(): string {
  try {
    const v = localStorage.getItem(FILTER_KEY) || ''
    return (RUN_STATES as readonly string[]).includes(v) ? v : ''
  } catch { return '' }
}

/**
 * The quest runs: every not yet ended run first, then the newest ended ones (the server's order). A state filter,
 * ↻ Refresh plus a 15 s poll; a row expands to its bindings, step log and issues. Cancel ends a not yet ended run
 * after a confirmation.
 */
export function RunsView() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [runs, setRuns] = useState<RunRow[] | null>(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState(initialFilter)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [pendingCancel, setPendingCancel] = useState<RunRow | null>(null)

  const reload = useCallback(async () => {
    try {
      setRuns(await fetchRuns(filter, lang))
      setError('')
    } catch (e) {
      setError(questErrorText(questError(e), t))
      setRuns((prev) => prev || [])
    }
  }, [filter, lang, t])

  useEffect(() => {
    void reload()
    const id = window.setInterval(() => { void reload() }, POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [reload])

  const changeFilter = (value: string) => {
    setFilter(value)
    try { localStorage.setItem(FILTER_KEY, value) } catch { /* Storage can be disabled. */ }
  }

  const toggle = (id: string) => setExpanded((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const doCancel = async () => {
    const run = pendingCancel
    setPendingCancel(null)
    if (!run) return
    try {
      const res = await cancelRun(run.id)
      toast(res.ok ? t('Run cancelled') : t('The run had already ended'), res.ok ? 'success' : 'info')
    } catch (e) {
      toast(t('Error') + ': ' + questErrorText(questError(e), t), 'error')
    }
    await reload()
  }

  return (
    <div className="ga-page-scroll">
      <div className="ga-form-row ga-quest-runs-bar">
        <select className="ga-input" value={filter} aria-label={t('State')} onChange={(e) => changeFilter(e.target.value)}>
          <option value="">{t('All states')}</option>
          {RUN_STATES.map((s) => <option key={s} value={s}>{t(STATE_LABELS[s])}</option>)}
        </select>
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => { void reload() }}>↻ {t('Refresh')}</button>
      </div>
      {error ? <p className="ga-quest-error" role="alert">{error}</p> : null}
      {runs === null ? (
        <div className="ga-loading">{t('Loading…')}</div>
      ) : runs.length === 0 ? (
        <div className="ga-placeholder">
          {filter ? t('No runs in this state.') : t('No quest runs yet. Start one from a ready template.')}
        </div>
      ) : (
        <table className="ga-sched-table">
          <thead>
            <tr>
              <th>{t('Quest')}</th>
              <th>{t('State')}</th>
              <th>{t('Step')}</th>
              <th>{t('Who did what')}</th>
              <th>{t('Started')}</th>
              <th>{t('Time limit ends')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const isOpen = expanded.has(run.id)
              const canCancel = RUN_OPEN_STATES.includes(run.state)
              return (
                <Fragment key={run.id}>
                  <tr>
                    <td>
                      <button type="button" className="ga-btn ga-btn-sm" aria-expanded={isOpen}
                        onClick={() => toggle(run.id)}>{isOpen ? '▾' : '▸'}</button>{' '}
                      {run.title || run.id}
                      {run.issues.length ? <>{' '}<span className="ga-tag ga-tag-missing">{run.issues.length}</span></> : null}
                    </td>
                    <td><span className={stateClass(run.state)}>{t(STATE_LABELS[run.state] || run.state)}</span></td>
                    <td>{stepProgress(run.current_step, run.step_count)}</td>
                    <td>
                      {run.step_log.length
                        ? run.step_log.map((e) => `${e.step + 1}: ${e.avatar}`).join(' · ')
                        : '—'}
                    </td>
                    <td>{run.started_game_label || '—'}</td>
                    <td>{run.expires_label || '—'}</td>
                    <td>
                      {canCancel ? (
                        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                          onClick={() => setPendingCancel(run)}>{t('Cancel run')}</button>
                      ) : null}
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr className="ga-quest-run-detail">
                      <td colSpan={7}>
                        <strong>{t('Roles')}</strong>
                        {Object.keys(run.bindings).length ? (
                          <ul>
                            {Object.entries(run.bindings).map(([role, b]) => (
                              <li key={role}><code>{role}</code> {bindingText(b, run.binding_labels?.[role])}</li>
                            ))}
                          </ul>
                        ) : <p className="ga-form-hint">—</p>}
                        <strong>{t('Step log')}</strong>
                        {run.step_log.length ? (
                          <ul>
                            {run.step_log.map((e, n) => (
                              <li key={n}>
                                {t('Step {n}').replace('{n}', String(e.step + 1))}: {e.avatar}
                                {e.mind && e.mind !== e.avatar ? ` (${e.mind})` : ''}
                                {e.game_label ? ` — ${e.game_label}` : ''}
                              </li>
                            ))}
                          </ul>
                        ) : <p className="ga-form-hint">{t('No step done yet.')}</p>}
                        {run.issues.length ? (
                          <div className="ga-quest-error" role="alert">
                            <ul>{run.issues.map((i, n) => <li key={n}><code>{i.path || '—'}</code> {i.message}</li>)}</ul>
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      )}
      <ConfirmDialog
        open={!!pendingCancel}
        title={t('Cancel quest run')}
        message={t('The run of "{name}" ends as cancelled; steps already done stay in its log.')
          .replace('{name}', pendingCancel ? pendingCancel.title || pendingCancel.id : '')}
        confirmLabel={t('Cancel run')}
        danger
        onConfirm={() => { void doCancel() }}
        onClose={() => setPendingCancel(null)}
      />
    </div>
  )
}
