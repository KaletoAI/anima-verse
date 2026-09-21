import { Fragment, useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface Job {
  id?: string
  agent?: string
  character?: string
  trigger?: Record<string, unknown>
  action?: { type?: string; [k: string]: unknown }
  enabled?: boolean
}

/**
 * One row of `GET /scheduler/jobs/{id}/logs`. `game_label` is the WORLD-time
 * label the server rendered from `game_ts` — this tab never formats a
 * calendar itself (CLAUDE.md: the server computes labels, clients render).
 * `timestamp` is the system stamp the rows are ordered by and the only thing
 * a row written before `game_ts` existed has.
 */
interface JobLog {
  timestamp?: string
  game_ts?: string
  game_label?: string
  status?: string
  manual?: boolean
  result?: unknown
}

/** What `POST /scheduler/jobs/{id}/run` answers. */
interface RunOutcome {
  status?: string
  reason?: string
  action?: string
  error?: string
  result?: unknown
}

/** The last N runs the expandable log shows — the route's own default is 100. */
const LOG_LIMIT = 20

/** One line about what a run did, out of the handler's own result dict.
 *  A stored log row carries the dict JSON-encoded (that is what the column
 *  holds), a fresh run hands it over as an object — both arrive here. */
function describeResult(result: unknown): string {
  if (result === null || result === undefined) return ''
  if (typeof result === 'string') {
    const text = result.trim()
    if (text.startsWith('{')) {
      try {
        return describeResult(JSON.parse(text))
      } catch {
        return text
      }
    }
    return text
  }
  if (typeof result !== 'object') return String(result)
  const r = result as Record<string, unknown>
  for (const key of ['error', 'reason', 'note', 'result', 'action']) {
    const v = r[key]
    if (typeof v === 'string' && v) return v
  }
  return JSON.stringify(result).slice(0, 160)
}

/**
 * Cron triggers run on the WORLD CALENDAR, not on real dates
 * (plan-game-calendar.md §2.6): the date fields are `season` (season key),
 * `day_of_season` and `weekday` — the latter only in a world that defines
 * week days. The calendar itself comes from GET /world/game-time, so this
 * tab never hardcodes season names or lengths.
 */
interface SeasonInfo {
  key: string
  name: string
  days: number
}

interface CalendarInfo {
  seasons: SeasonInfo[]
  week_days: string[]
}

const EMPTY_CALENDAR: CalendarInfo = { seasons: [], week_days: [] }

type TriggerKind = 'cron-hourly' | 'cron-daily' | 'interval-minutes' | 'date'
type ActionKind = 'extract_files' | 'notify'

interface FormState {
  trigger: TriggerKind
  extra: string
  action: ActionKind
  payload: string
  agent: string
  /** season KEY, '' = any */
  season: string
  /** 1-based day within the season, '' = any */
  dayOfSeason: string
  /** week-day index as a string, '' = any */
  weekday: string
}

const POLL_INTERVAL_MS = 15_000

const INITIAL_FORM: FormState = {
  trigger: 'cron-hourly',
  extra: '',
  action: 'extract_files',
  payload: '',
  agent: '',
  season: '',
  dayOfSeason: '',
  weekday: '',
}

function isCron(kind: TriggerKind): boolean {
  return kind === 'cron-hourly' || kind === 'cron-daily'
}

/** The calendar constraints of a cron trigger — omitted fields mean "any". */
function cronCalendarFields(form: FormState): Record<string, unknown> {
  const fields: Record<string, unknown> = {}
  if (form.season) fields.season = form.season
  const day = parseInt(form.dayOfSeason, 10)
  if (Number.isFinite(day) && day > 0) fields.day_of_season = day
  const weekday = parseInt(form.weekday, 10)
  if (Number.isFinite(weekday) && weekday >= 0) fields.weekday = weekday
  return fields
}

function buildTrigger(form: FormState): Record<string, unknown> {
  const extra = form.extra.trim()
  switch (form.trigger) {
    case 'cron-hourly':
      return { type: 'cron', minute: 0, ...cronCalendarFields(form) }
    case 'cron-daily': {
      const m = extra.match(/^(\d{1,2}):(\d{2})$/)
      const hour = m ? parseInt(m[1], 10) : 3
      const minute = m ? parseInt(m[2], 10) : 0
      return { type: 'cron', hour, minute, ...cronCalendarFields(form) }
    }
    case 'interval-minutes':
      return { type: 'interval', minutes: parseInt(extra, 10) || 30 }
    case 'date':
      return { type: 'date', run_date: extra }
  }
}

function buildAction(form: FormState): Record<string, unknown> {
  const payload = form.payload.trim()
  if (form.action === 'extract_files') {
    return { type: 'extract_files', extraction_prompt: payload }
  }
  return { type: 'notify', message: payload || 'admin notify' }
}

function intField(trigger: Record<string, unknown>, key: string): number | null {
  const raw = trigger[key]
  if (raw === undefined || raw === null || raw === '' || raw === '*') return null
  const n = typeof raw === 'number' ? raw : parseInt(String(raw), 10)
  return Number.isFinite(n) ? n : null
}

function two(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

/** One-line summary of a job's trigger, in world-calendar terms. */
function describeTrigger(
  trigger: Record<string, unknown> | undefined,
  calendar: CalendarInfo,
  t: (s: string) => string,
): string {
  if (!trigger) return ''
  const type = String(trigger.type ?? '')
  if (type === 'marker') return t('display only')
  if (type === 'date') {
    return t('once at {when}').replace('{when}', String(trigger.run_date ?? '?'))
  }
  if (type === 'interval') {
    const units: Array<[string, string]> = [
      ['days', 'd'],
      ['hours', 'h'],
      ['minutes', 'min'],
      ['seconds', 's'],
    ]
    const span = units
      .map(([key, unit]) => {
        const n = intField(trigger, key)
        return n && n > 0 ? `${n}${unit}` : ''
      })
      .filter(Boolean)
      .join(' ')
    return t('every {span}').replace('{span}', span || '?')
  }
  if (type === 'cron') {
    const hour = intField(trigger, 'hour')
    const minute = intField(trigger, 'minute')
    const bits: string[] = []
    if (hour !== null) bits.push(`${two(hour)}:${two(minute ?? 0)}`)
    else if (minute !== null) bits.push(t('hourly at :{m}').replace('{m}', two(minute)))
    else bits.push(t('every minute'))
    const seasonKey = String(trigger.season ?? '')
    if (seasonKey) {
      const season = calendar.seasons.find((s) => s.key === seasonKey)
      bits.push(season ? season.name : seasonKey)
    }
    const day = intField(trigger, 'day_of_season')
    if (day !== null) bits.push(t('day {n}').replace('{n}', String(day)))
    const weekday = intField(trigger, 'weekday')
    if (weekday !== null) {
      bits.push(calendar.week_days[weekday] ?? `#${weekday}`)
    }
    return bits.join(' · ')
  }
  return JSON.stringify(trigger).slice(0, 80)
}

export function SchedulerTab() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(INITIAL_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [calendar, setCalendar] = useState<CalendarInfo>(EMPTY_CALENDAR)
  // A frozen world makes the scheduler refuse EVERY run, manual ones
  // included (SchedulerManager._execute_job checks is_world_frozen first), so
  // the button says so instead of producing a "skipped" toast.
  const [frozen, setFrozen] = useState(false)
  const [running, setRunning] = useState('')
  const [openLog, setOpenLog] = useState('')
  const [logs, setLogs] = useState<JobLog[] | null>(null)

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<{ data?: Job[] }>('/scheduler/jobs')
      setJobs(data.data || [])
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
    try {
      const f = await apiGet<{ frozen?: boolean }>('/world/freeze-status')
      setFrozen(!!f.frozen)
    } catch {
      // A failing freeze probe must not grey out the buttons — the run
      // itself reports a frozen world as a skip.
      setFrozen(false)
    }
  }, [])

  useEffect(() => {
    reload()
    const id = window.setInterval(reload, POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [reload])

  // The world calendar drives the cron date fields; read defensively so a
  // world without a configured calendar simply offers no seasons.
  useEffect(() => {
    let cancelled = false
    apiGet<{ calendar?: Partial<CalendarInfo> }>('/world/game-time')
      .then((data) => {
        if (cancelled) return
        setCalendar({
          seasons: data.calendar?.seasons ?? [],
          week_days: data.calendar?.week_days ?? [],
        })
      })
      .catch(() => {
        if (!cancelled) setCalendar(EMPTY_CALENDAR)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const maxDayOfSeason = useMemo(() => {
    const picked = calendar.seasons.find((s) => s.key === form.season)
    if (picked) return picked.days
    return calendar.seasons.reduce((max, s) => Math.max(max, s.days), 0) || 0
  }, [calendar.seasons, form.season])

  // Asking and deleting are two steps: the question is an in-app dialog, so
  // the click only arms it and the dialog's confirm does the work.
  const [pendingDelete, setPendingDelete] = useState('')
  const handleDelete = useCallback((id: string) => { setPendingDelete(id) }, [])
  const confirmDelete = useCallback(
    async () => {
      const id = pendingDelete
      setPendingDelete('')
      if (!id) return
      try {
        await apiDelete(`/scheduler/jobs/${encodeURIComponent(id)}`)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
      await reload()
    },
    [pendingDelete, reload, t, toast],
  )

  const loadLogs = useCallback(async (id: string) => {
    try {
      const data = await apiGet<{ data?: JobLog[] }>(
        `/scheduler/jobs/${encodeURIComponent(id)}/logs`
        + `?limit=${LOG_LIMIT}&lang=${encodeURIComponent(lang)}`)
      setLogs(data.data || [])
    } catch (e) {
      setLogs([])
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [lang, t, toast])

  // "Run now" runs the job ONCE, out of band: the server leaves the
  // schedule untouched (no re-anchoring, no double fire on the next tick),
  // and answers with what actually happened.
  const handleRun = useCallback(
    async (id: string) => {
      setRunning(id)
      try {
        const res = await apiPost<{ outcome?: RunOutcome }>(
          `/scheduler/jobs/${encodeURIComponent(id)}/run`, {})
        const outcome = res.outcome || {}
        if (outcome.status === 'skipped') {
          const why = outcome.reason === 'world_frozen'
            ? t('the world is frozen')
            : outcome.reason === 'character_asleep'
              ? t('the character is asleep')
              : outcome.reason || ''
          toast(t('Job {id} did not run — {why}').replace('{id}', id)
            .replace('{why}', why), 'error')
        } else if (outcome.status === 'error') {
          toast(t('Job {id} failed').replace('{id}', id)
            + ': ' + (outcome.error || ''), 'error')
        } else {
          const note = describeResult(outcome.result)
          toast(t('Job {id} ran').replace('{id}', id) + (note ? ': ' + note : ''))
        }
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setRunning('')
      }
      if (openLog === id) await loadLogs(id)
      await reload()
    },
    [loadLogs, openLog, reload, t, toast],
  )

  const toggleLog = useCallback(
    async (id: string) => {
      if (openLog === id) {
        setOpenLog('')
        setLogs(null)
        return
      }
      setOpenLog(id)
      setLogs(null)
      await loadLogs(id)
    },
    [openLog, loadLogs],
  )

  const handleToggle = useCallback(
    async (id: string) => {
      try {
        await apiPut(`/scheduler/jobs/${encodeURIComponent(id)}/toggle`, {})
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
      await reload()
    },
    [reload, t, toast],
  )

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault()
      setSubmitting(true)
      try {
        await apiPost('/scheduler/jobs', {
          agent: form.agent.trim(),
          trigger: buildTrigger(form),
          action: buildAction(form),
          enabled: true,
        })
        setForm({ ...INITIAL_FORM, trigger: form.trigger, action: form.action })
        toast(t('Job created'))
        await reload()
      } catch (err) {
        toast(t('Create failed') + ': ' + (err as Error).message, 'error')
      } finally {
        setSubmitting(false)
      }
    },
    [form, reload, t, toast],
  )

  return (
    <div className="ga-page-scroll">
      <h2 style={{ fontSize: 16, marginBottom: 6 }}>{t('Scheduler — Background Jobs')}</h2>

      <section className="ga-sched-section">
        <h3>{t('All jobs')}</h3>
        <p className="ga-sched-muted">
          {t(
            'Admin jobs (e.g. memory consolidation, file extraction) are highlighted as "admin". Per-character jobs from the legacy scheduler still surface here for visibility and can be deleted, but should no longer be created — character actions belong in the AgentLoop.',
          )}
        </p>
        <table className="ga-sched-table">
          <thead>
            <tr>
              <th>{t('Job ID')}</th>
              <th>{t('Owner')}</th>
              <th>{t('Trigger')}</th>
              <th>{t('Action')}</th>
              <th>{t('Status')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td colSpan={6}>error: {error}</td>
              </tr>
            ) : jobs === null ? (
              <tr>
                <td colSpan={6} className="ga-sched-muted">
                  {t('Loading…')}
                </td>
              </tr>
            ) : jobs.length === 0 ? (
              <tr>
                <td colSpan={6} className="ga-sched-muted">
                  {t('No jobs scheduled.')}
                </td>
              </tr>
            ) : (
              jobs.map((job) => {
                const owner = (job.agent || job.character || '').trim()
                const enabled = job.enabled !== false
                const trig = describeTrigger(job.trigger, calendar, t)
                const id = job.id || ''
                // A marker job is a display row the dispatcher never fires
                // (SchedulerManager._schedule_job) — running it by hand would
                // hand its non-action to the executor.
                const isMarker = String(job.trigger?.type ?? '') === 'marker'
                return (
                  <Fragment key={id}>
                  <tr>
                    <td>{id || '?'}</td>
                    <td>
                      {owner ? (
                        <span className="ga-tag ga-tag-char">{owner}</span>
                      ) : (
                        <span className="ga-tag ga-tag-admin">admin</span>
                      )}
                    </td>
                    <td>{trig}</td>
                    <td>{job.action?.type || '?'}</td>
                    <td className={enabled ? 'ga-status-ok' : 'ga-status-paused'}>
                      {enabled ? t('enabled') : t('paused')}
                    </td>
                    <td className="ga-or-actions-col">
                      <button
                        className="ga-btn ga-btn-sm"
                        disabled={!!running || frozen || isMarker}
                        title={frozen
                          ? t('The world is frozen — the scheduler refuses every run until it is resumed.')
                          : isMarker
                            ? t('A display-only job has nothing to run.')
                            : t('Run this job once now. Its schedule stays as it is — the next regular run is not moved.')}
                        onClick={() => { void handleRun(id) }}
                      >
                        {running === id ? t('Running…') : t('Run now')}
                      </button>{' '}
                      <button
                        className="ga-btn ga-btn-sm"
                        title={t('The last runs of this job')}
                        onClick={() => { void toggleLog(id) }}
                      >
                        {openLog === id ? t('Hide log') : t('Log')}
                      </button>{' '}
                      <button className="ga-btn ga-btn-sm" onClick={() => handleToggle(id)}>
                        {enabled ? t('Pause') : t('Resume')}
                      </button>{' '}
                      <button
                        className="ga-btn ga-btn-sm ga-btn-danger"
                        onClick={() => handleDelete(id)}
                      >
                        {t('Delete')}
                      </button>
                    </td>
                  </tr>
                  {openLog === id ? (
                    <tr>
                      <td colSpan={6}>
                        {logs === null ? (
                          <span className="ga-sched-muted">{t('Loading…')}</span>
                        ) : logs.length === 0 ? (
                          <span className="ga-sched-muted">
                            {t('This job has not run yet.')}
                          </span>
                        ) : (
                          <table className="ga-sched-table">
                            <thead>
                              <tr>
                                <th>{t('When (world time)')}</th>
                                <th>{t('Outcome')}</th>
                                <th>{t('Message')}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {logs.slice().reverse().map((row, i) => (
                                <tr key={`${row.timestamp ?? ''}-${i}`}>
                                  <td>
                                    {/* The server renders the world label; a
                                        row from before `game_ts` existed has
                                        only its system stamp. */}
                                    {row.game_label || row.timestamp || '?'}
                                    {row.manual ? ' · ' + t('manual') : ''}
                                  </td>
                                  <td
                                    className={row.status === 'success'
                                      ? 'ga-status-ok'
                                      : 'ga-status-paused'}
                                  >
                                    {row.status || '?'}
                                  </td>
                                  <td>{describeResult(row.result)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </td>
                    </tr>
                  ) : null}
                  </Fragment>
                )
              })
            )}
          </tbody>
        </table>
      </section>

      <section className="ga-sched-section">
        <h3>{t('Create admin job')}</h3>
        <form className="ga-sched-form" onSubmit={handleSubmit}>
          <div className="ga-sched-form-row">
            <div className="ga-sched-field">
              <label>{t('Trigger')}</label>
              <select
                className="ga-input"
                value={form.trigger}
                onChange={(e) => setForm((f) => ({ ...f, trigger: e.target.value as TriggerKind }))}
                required
              >
                <option value="cron-hourly">{t('Every hour at :00')}</option>
                <option value="cron-daily">{t('Once a day')}</option>
                <option value="interval-minutes">{t('Every N minutes')}</option>
                <option value="date">{t('One-shot at date/time')}</option>
              </select>
            </div>
            <div className="ga-sched-field">
              <label>{t('Detail')}</label>
              <input
                className="ga-input"
                value={form.extra}
                onChange={(e) => setForm((f) => ({ ...f, extra: e.target.value }))}
                placeholder={t('e.g. 30 (minutes), 03:00 (HH:MM) or Y0002-D109T08:00:00 (game time)')}
              />
            </div>
            <div className="ga-sched-field">
              <label>{t('Action')}</label>
              <select
                className="ga-input"
                value={form.action}
                onChange={(e) => setForm((f) => ({ ...f, action: e.target.value as ActionKind }))}
              >
                <option value="extract_files">extract_files (knowledge)</option>
                <option value="notify">notify (UI message)</option>
              </select>
            </div>
            <div className="ga-sched-field" style={{ flex: 1, minWidth: 240 }}>
              <label>{t('Payload')}</label>
              <input
                className="ga-input"
                value={form.payload}
                onChange={(e) => setForm((f) => ({ ...f, payload: e.target.value }))}
                placeholder={t('extract: optional prompt — notify: message text')}
              />
            </div>
            <div className="ga-sched-field">
              <label>{t('Agent (optional)')}</label>
              <input
                className="ga-input"
                value={form.agent}
                onChange={(e) => setForm((f) => ({ ...f, agent: e.target.value }))}
              />
            </div>
            <div>
              <button type="submit" className="ga-btn ga-btn-primary" disabled={submitting}>
                {submitting ? t('Creating…') : t('Create')}
              </button>
            </div>
          </div>

          {isCron(form.trigger) && (
            <div className="ga-sched-form-row">
              <div className="ga-sched-field">
                <label>{t('Season')}</label>
                <select
                  className="ga-input"
                  value={form.season}
                  onChange={(e) =>
                    setForm((f) => {
                      const season = e.target.value
                      const picked = calendar.seasons.find((s) => s.key === season)
                      const day = parseInt(f.dayOfSeason, 10)
                      // A day beyond the new season's length would never match.
                      const dayOfSeason =
                        picked && Number.isFinite(day) && day > picked.days
                          ? String(picked.days)
                          : f.dayOfSeason
                      return { ...f, season, dayOfSeason }
                    })
                  }
                >
                  <option value="">{t('Any season')}</option>
                  {calendar.seasons.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="ga-sched-field">
                <label>{t('Day of season')}</label>
                <input
                  className="ga-input"
                  type="number"
                  min={1}
                  max={maxDayOfSeason || undefined}
                  value={form.dayOfSeason}
                  onChange={(e) => setForm((f) => ({ ...f, dayOfSeason: e.target.value }))}
                  placeholder={
                    maxDayOfSeason
                      ? t('any (1–{max})').replace('{max}', String(maxDayOfSeason))
                      : t('any')
                  }
                />
              </div>
              {calendar.week_days.length > 0 && (
                <div className="ga-sched-field">
                  <label>{t('Weekday')}</label>
                  <select
                    className="ga-input"
                    value={form.weekday}
                    onChange={(e) => setForm((f) => ({ ...f, weekday: e.target.value }))}
                  >
                    <option value="">{t('Any weekday')}</option>
                    {calendar.week_days.map((name, idx) => (
                      <option key={name} value={String(idx)}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}

          <p className="ga-sched-muted" style={{ margin: '6px 0 0 0' }}>
            {t(
              'Cron jobs follow the WORLD calendar: season, day of season and — where the world has weeks — weekday. Empty means "any". One-shot jobs take a game-time stamp (Y0002-D109T08:00:00).',
            )}
          </p>
          <p className="ga-sched-muted" style={{ margin: '6px 0 0 0' }}>
            {t(
              'Per-character actions (send_message, set_status, execute_tool) are not exposed here — they belong in the AgentLoop. Daily Rhythm: Character Editor → Daily schedule.',
            )}
          </p>
        </form>
      </section>

      <ConfirmDialog
        open={!!pendingDelete}
        title={t('Delete job')}
        message={t('Job {id} is removed from the scheduler.').replace('{id}', pendingDelete)}
        confirmLabel={t('Delete')}
        danger
        onConfirm={() => { void confirmDelete() }}
        onClose={() => setPendingDelete('')}
      />
    </div>
  )
}
