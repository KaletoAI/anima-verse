import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { usePersistentState } from '../../lib/usePersistentState'
import './FreeModePanel.css'

/**
 * World Dev "Free (agent)" mode — plan
 * docs/superpowers/plans/2026-11-22-world-dev-free-mode.md, Task 9.
 *
 * The server owns the run (app/core/world_dev_agent.py); this panel only
 * renders it. The live view comes from the run's SSE stream
 * (GET /world-dev/free/{id}/events?after=N): step rows, the model's text and
 * the counters. The run detail (GET /world-dev/free/{id}: journal steps,
 * skipped steps, discard preview) is fetched on mount and on every STATUS
 * change, never polled. Live step rows carry the journal seq, so they merge
 * into the journal list by that number without duplicates on a replay.
 */

const OPEN_STATUSES = ['running', 'awaiting_review', 'interrupted']
const REVIEW_STATUSES = ['awaiting_review', 'interrupted']

interface FreeRun {
  id: string
  task?: string
  model?: string
  provider?: string
  status: string
  turn?: number
  steps?: number
  max_steps?: number
  max_tokens_total?: number
  tokens_in?: number
  tokens_out?: number
  cost_total?: number
  backup_path?: string | null
  note?: string | null
  created_at?: string
  ended_at?: string | null
}

interface StepRow {
  seq: number | null
  tool: string
  kind: string
  line: string
  undone?: boolean
}

interface SkipEntry {
  seq?: number
  line?: string
  reason?: string
}

interface FreeDetail {
  run: FreeRun
  steps: Array<{ seq: number; tool: string; kind: string; line?: string | null;
                 undone_at?: string | null }>
  skipped: SkipEntry[]
  discard_preview: string[]
  busy: boolean
}

interface Counters {
  steps: number
  max_steps: number
  tokens: number
  max_tokens_total: number
  cost: number
}

interface FreeEvent {
  ev: number
  type: string
  text?: string
  tool?: string
  ok?: boolean
  line?: string
  kind?: string
  wrote?: boolean
  seq?: number | null
  status?: string
  note?: string
  tokens_in?: number
  tokens_out?: number
  cost?: number
  steps?: number
  max_steps?: number
  max_tokens_total?: number
  error?: string
}

function countersOf(run: FreeRun): Counters {
  return {
    steps: run.steps || 0,
    max_steps: run.max_steps || 0,
    tokens: (run.tokens_in || 0) + (run.tokens_out || 0),
    max_tokens_total: run.max_tokens_total || 0,
    cost: run.cost_total || 0,
  }
}

function formatUsd(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '$0.00'
  if (value < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}

function shortTime(iso?: string | null): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : ''
}

/** A positive integer from a text field, or undefined (empty / invalid). */
function posInt(raw: string): number | undefined {
  const n = parseInt(raw, 10)
  return Number.isFinite(n) && n > 0 ? n : undefined
}

export function FreeModePanel({ model, provider, maxTokens }: {
  model: string
  provider: string
  /** The per-reply budget of the tab's budget select ('' = auto, '0' = none). */
  maxTokens: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()

  const [task, setTask] = usePersistentState('worlddev.free.task', '')
  const [maxSteps, setMaxSteps] = usePersistentState('worlddev.free.maxSteps', '')
  const [maxTotal, setMaxTotal] = usePersistentState('worlddev.free.maxTotal', '')
  // The last SSE event number seen, per run — a reopened tab resumes the
  // stream behind it instead of replaying the whole buffer.
  const [lastEv, setLastEv] = usePersistentState<{ run: string; ev: number }>(
    'worlddev.free.lastEv', { run: '', ev: 0 })
  const lastEvRef = useRef(lastEv)

  const [runId, setRunId] = useState('')
  const [detail, setDetail] = useState<FreeDetail | null>(null)
  const [liveSteps, setLiveSteps] = useState<StepRow[]>([])
  const [liveText, setLiveText] = useState('')
  const [liveStatus, setLiveStatus] = useState('')
  const [counters, setCounters] = useState<Counters | null>(null)
  const [runs, setRuns] = useState<FreeRun[]>([])
  const [busy, setBusy] = useState(false)
  const [followUp, setFollowUp] = useState('')
  const [followSteps, setFollowSteps] = useState('')
  const [followTotal, setFollowTotal] = useState('')
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [discardSkipped, setDiscardSkipped] = useState<SkipEntry[] | null>(null)

  const streamRef = useRef<AbortController | null>(null)
  // The run on screen. Stream events and detail reads of any other run are
  // dropped — switching runs must never mix two runs into one view.
  const runIdRef = useRef('')
  const refreshTimer = useRef<number | null>(null)
  const mounted = useRef(true)

  const rememberEv = useCallback((run: string, ev: number) => {
    lastEvRef.current = { run, ev }
    setLastEv({ run, ev })
  }, [setLastEv])

  const loadRuns = useCallback(async () => {
    try {
      const d = await apiGet<{ runs?: FreeRun[] }>('/world-dev/free/runs')
      if (mounted.current) setRuns(d.runs || [])
    } catch {
      if (mounted.current) setRuns([])
    }
  }, [])

  const loadDetail = useCallback(async (id: string): Promise<FreeDetail | null> => {
    try {
      const d = await apiGet<FreeDetail>(`/world-dev/free/${encodeURIComponent(id)}`)
      if (!mounted.current || runIdRef.current !== id) return d
      setDetail(d)
      setLiveStatus(d.run.status)
      setCounters(countersOf(d.run))
      // Rows the journal now holds come from the journal from here on.
      const known = new Set(d.steps.map((s) => s.seq))
      setLiveSteps((prev) => prev.filter((r) => r.seq !== null && !known.has(r.seq)))
      return d
    } catch (e) {
      toast(t('Loading the run failed') + ': ' + (e as Error).message, 'error')
      return null
    }
  }, [t, toast])

  /** A status change: re-read the detail (and the runs list) once, coalesced
   *  — a replayed stream can carry several status events in a row. */
  const scheduleRefresh = useCallback((id: string) => {
    if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current)
    refreshTimer.current = window.setTimeout(() => {
      refreshTimer.current = null
      void loadDetail(id)
      void loadRuns()
    }, 200)
  }, [loadDetail, loadRuns])

  const handleEvent = useCallback((id: string, ev: FreeEvent) => {
    if (runIdRef.current !== id) return
    if (ev.type === 'reset') {
      // The server's buffer does not reach back to our counter (a restart):
      // drop the live view and the counter, the detail is the truth.
      setLiveSteps([])
      setLiveText('')
      rememberEv(id, 0)
      scheduleRefresh(id)
      return
    }
    if (ev.ev > 0) rememberEv(id, ev.ev)
    switch (ev.type) {
      case 'text':
        setLiveText((prev) => prev + (ev.text || ''))
        break
      case 'step': {
        // A tool that raised still names its kind — it is a failed row, never a write.
        const kind = !ev.ok ? 'refused' : (ev.kind || (ev.wrote ? 'write' : 'read'))
        const row: StepRow = { seq: typeof ev.seq === 'number' ? ev.seq : null,
                               tool: ev.tool || '', kind, line: ev.line || '' }
        setLiveSteps((prev) => (row.seq !== null && prev.some((r) => r.seq === row.seq)
          ? prev : [...prev, row]))
        // A new step closes the model's text before it.
        setLiveText('')
        break
      }
      case 'usage':
        setCounters({
          steps: ev.steps || 0,
          max_steps: ev.max_steps || 0,
          tokens: (ev.tokens_in || 0) + (ev.tokens_out || 0),
          max_tokens_total: ev.max_tokens_total || 0,
          cost: ev.cost || 0,
        })
        break
      case 'status':
        setLiveStatus(ev.status || '')
        if (ev.status !== 'running') setLiveText('')
        scheduleRefresh(id)
        break
      case 'error':
        toast(t('Event stream failed') + ': ' + (ev.error || ''), 'error')
        break
    }
  }, [rememberEv, scheduleRefresh, t, toast])

  /** Follow the run's event stream until its turn ends. */
  const connect = useCallback(async (id: string) => {
    streamRef.current?.abort()
    const ctl = new AbortController()
    streamRef.current = ctl
    const after = lastEvRef.current.run === id ? lastEvRef.current.ev : 0
    if (lastEvRef.current.run !== id) rememberEv(id, 0)
    let sawEnd = false
    try {
      const res = await fetch(
        `/world-dev/free/${encodeURIComponent(id)}/events?after=${after}`,
        { credentials: 'same-origin', signal: ctl.signal })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const chunk = buffer.slice(0, idx).trim()
          buffer = buffer.slice(idx + 2)
          if (!chunk.startsWith('data:')) continue
          try {
            const ev = JSON.parse(chunk.slice(5).trim()) as FreeEvent
            // The LAST status counts: a replay of a later turn carries the
            // earlier turn's closing status before this turn's 'running'.
            if (ev.type === 'status') sawEnd = ev.status !== 'running'
            handleEvent(id, ev)
          } catch { /* drop a malformed frame */ }
        }
      }
    } catch (e) {
      if (ctl.signal.aborted) return
      toast(t('Event stream failed') + ': ' + (e as Error).message, 'error')
    } finally {
      if (streamRef.current === ctl) streamRef.current = null
    }
    if (ctl.signal.aborted || !mounted.current || sawEnd || runIdRef.current !== id) return
    // The stream ended without a closing status (a dropped connection): read
    // the run once and follow it again while its turn is still working.
    const d = await loadDetail(id)
    if (d && d.busy && d.run.status === 'running' && mounted.current) {
      window.setTimeout(() => {
        if (mounted.current && !streamRef.current && runIdRef.current === id) void connect(id)
      }, 1000)
    }
  }, [handleEvent, loadDetail, rememberEv, t, toast])

  /** Show a run: its detail, and its live stream while it runs. */
  const attach = useCallback(async (id: string) => {
    // Leave the previous run's stream and pending refresh behind.
    streamRef.current?.abort()
    streamRef.current = null
    if (refreshTimer.current !== null) {
      window.clearTimeout(refreshTimer.current)
      refreshTimer.current = null
    }
    runIdRef.current = id
    setRunId(id)
    setLiveStatus('')
    setCounters(null)
    setLiveSteps([])
    setLiveText('')
    setDiscardSkipped(null)
    void loadRuns()
    const d = await loadDetail(id)
    if (d && d.run.status === 'running' && runIdRef.current === id) void connect(id)
  }, [connect, loadDetail, loadRuns])

  useEffect(() => {
    mounted.current = true
    apiGet<{ max_steps?: number; max_tokens_total?: number }>('/world-dev/free/defaults')
      .then((d) => {
        if (!mounted.current) return
        setMaxSteps((prev) => prev || String(d.max_steps || ''))
        setMaxTotal((prev) => prev || String(d.max_tokens_total || ''))
      })
      .catch(() => { /* the fields stay empty — the server applies its defaults */ })
    void loadRuns()
    apiGet<{ run?: FreeRun | null }>('/world-dev/free/open')
      .then((d) => { if (d.run && mounted.current) void attach(d.run.id) })
      .catch(() => { /* no open run to show */ })
    return () => {
      mounted.current = false
      streamRef.current?.abort()
      streamRef.current = null
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const run = detail && detail.run.id === runId ? detail.run : null
  const status = liveStatus || run?.status || ''
  const isOpen = OPEN_STATUSES.includes(status)
  const inReview = REVIEW_STATUSES.includes(status)
  const running = status === 'running'
  // An open run other than the one on screen (an old run is being viewed):
  // the world is still paused by it, so the banner leads back to it.
  const otherOpen = run && isOpen ? null
    : runs.find((r) => OPEN_STATUSES.includes(r.status) && r.id !== runId) || null

  const rows: StepRow[] = useMemo(() => {
    const base: StepRow[] = (detail && detail.run.id === runId ? detail.steps : []).map((s) => ({
      seq: s.seq, tool: s.tool, kind: s.kind, line: s.line || '', undone: !!s.undone_at,
    }))
    const known = new Set(base.map((r) => r.seq))
    const extra = liveSteps.filter((r) => r.seq === null || !known.has(r.seq))
    const numbered = [...base, ...extra.filter((r) => r.seq !== null)]
      .sort((a, b) => (a.seq || 0) - (b.seq || 0))
    return [...numbered, ...extra.filter((r) => r.seq === null)]
  }, [detail, liveSteps, runId])

  const skipped: SkipEntry[] = discardSkipped && discardSkipped.length
    ? discardSkipped : (run?.status !== 'accepted' ? detail?.skipped || [] : [])

  const start = useCallback(async () => {
    if (!model) { toast(t('Pick a model first'), 'error'); return }
    if (!task.trim()) { toast(t('Describe the task first'), 'error'); return }
    setBusy(true)
    try {
      const perReply = maxTokens.trim() ? parseInt(maxTokens, 10) : undefined
      const d = await apiPost<{ run_id: string }>('/world-dev/free/start', {
        task: task.trim(), model, provider,
        max_tokens: Number.isFinite(perReply) ? perReply : undefined,
        max_steps: posInt(maxSteps),
        max_tokens_total: posInt(maxTotal),
      })
      rememberEv(d.run_id, 0)
      await attach(d.run_id)
      void loadRuns()
    } catch (e) {
      toast(t('Start failed') + ': ' + (e as Error).message, 'error')
      // A 409 names a run that is already open — show it.
      try {
        const o = await apiGet<{ run?: FreeRun | null }>('/world-dev/free/open')
        if (o.run && o.run.id !== runId) await attach(o.run.id)
      } catch { /* nothing to show */ }
    } finally {
      setBusy(false)
    }
  }, [attach, loadRuns, maxSteps, maxTokens, maxTotal, model, provider, rememberEv, runId, t, task, toast])

  const action = useCallback(async (what: 'stop' | 'accept' | 'discard') => {
    if (!runId) return
    setBusy(true)
    try {
      const d = await apiPost<{ ok?: boolean; report?: { skipped?: SkipEntry[] } }>(
        `/world-dev/free/${encodeURIComponent(runId)}/${what}`, {})
      if (what === 'discard') {
        setDiscardSkipped(d.report?.skipped || [])
        toast(t('Run discarded'))
      } else if (what === 'accept') {
        toast(t('Run accepted'))
      }
      // Stop ends in a status event on the live stream; accept and discard
      // are status changes of a run nobody streams any more.
      if (what !== 'stop' || !streamRef.current) {
        await loadDetail(runId)
        void loadRuns()
      }
    } catch (e) {
      toast(t('Action failed') + ': ' + (e as Error).message, 'error')
      await loadDetail(runId)
    } finally {
      setBusy(false)
    }
  }, [loadDetail, loadRuns, runId, t, toast])

  const sendFollowUp = useCallback(async () => {
    if (!runId || !followUp.trim()) return
    setBusy(true)
    try {
      await apiPost(`/world-dev/free/${encodeURIComponent(runId)}/message`, {
        text: followUp.trim(),
        max_steps: posInt(followSteps),
        max_tokens_total: posInt(followTotal),
      })
      setFollowUp('')
      setFollowSteps('')
      setFollowTotal('')
      setDiscardSkipped(null)
      setLiveStatus('running')
      void connect(runId)
    } catch (e) {
      toast(t('Sending failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [connect, followSteps, followTotal, followUp, runId, t, toast])

  const newRun = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
    if (refreshTimer.current !== null) {
      window.clearTimeout(refreshTimer.current)
      refreshTimer.current = null
    }
    runIdRef.current = ''
    setRunId('')
    setDetail(null)
    setLiveSteps([])
    setLiveText('')
    setLiveStatus('')
    setCounters(null)
    setDiscardSkipped(null)
  }, [])

  const c = counters

  return (
    <div className="ga-wd-free">
      {run && isOpen ? (
        <div className={`ga-wd-free-banner${running ? ' ga-wd-free-banner-running' : ''}`}>
          <span className="ga-wd-free-banner-text">
            {running
              ? t('World paused — free-mode run working')
              : t('World paused — free-mode run in review')}
            {status === 'interrupted'
              ? ' · ' + t('the server stopped during a turn')
              : ''}
          </span>
          {running ? (
            <button className="ga-btn ga-btn-sm" disabled={busy}
              onClick={() => { void action('stop') }}>
              {t('Stop')}
            </button>
          ) : null}
          <button className="ga-btn ga-btn-primary ga-btn-sm" disabled={busy || !inReview}
            title={t('Keep everything the run built and resume the world')}
            onClick={() => { void action('accept') }}>
            {t('Accept')}
          </button>
          <button className="ga-btn ga-btn-sm ga-wd-free-danger" disabled={busy || !inReview}
            title={t('Undo everything the run built')}
            onClick={() => setConfirmDiscard(true)}>
            {t('Discard')}
          </button>
        </div>
      ) : otherOpen ? (
        <div className="ga-wd-free-banner">
          <span className="ga-wd-free-banner-text">
            {otherOpen.status === 'running'
              ? t('World paused — free-mode run working')
              : t('World paused — free-mode run in review')}
            {otherOpen.task ? ' · ' + otherOpen.task : ''}
          </span>
          <button className="ga-btn ga-btn-primary ga-btn-sm"
            onClick={() => { void attach(otherOpen.id) }}>
            {t('Show the open run')}
          </button>
        </div>
      ) : null}

      {!run ? (
        <div className="ga-wd-free-start">
          <textarea
            className="ga-textarea"
            rows={4}
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder={t('Describe the task in plain language — the model builds it directly in the paused world, and you accept or discard the result.')}
          />
          <div className="ga-wd-free-row">
            <label className="ga-wd-free-field">
              <span>{t('Step budget')}</span>
              <input className="ga-input" inputMode="numeric" value={maxSteps}
                onChange={(e) => setMaxSteps(e.target.value)} />
            </label>
            <label className="ga-wd-free-field">
              <span>{t('Token budget (run)')}</span>
              <input className="ga-input" inputMode="numeric" value={maxTotal}
                onChange={(e) => setMaxTotal(e.target.value)} />
            </label>
            <button className="ga-btn ga-btn-primary" disabled={busy || !task.trim() || !model}
              onClick={() => { void start() }}>
              {t('Start')}
            </button>
          </div>
        </div>
      ) : (
        <div className="ga-wd-free-run">
          <div className="ga-wd-free-head">
            <span className={`ga-wd-free-status ga-wd-free-status-${status}`}>{status}</span>
            <span className="ga-wd-free-task" title={run.task || ''}>{run.task}</span>
            <span className="ga-form-hint">{run.model}</span>
            {!isOpen ? (
              <button className="ga-btn ga-btn-sm" onClick={newRun}>{t('New run')}</button>
            ) : null}
          </div>
          {c ? (
            <div className="ga-wd-free-counters">
              <span><strong>{t('Steps')}</strong> {c.steps} / {c.max_steps}</span>
              <span><strong>{t('Tokens')}</strong> {c.tokens.toLocaleString()} / {c.max_tokens_total.toLocaleString()}</span>
              <span><strong>{t('Cost')}</strong> {formatUsd(c.cost)}</span>
            </div>
          ) : null}

          <div className="ga-wd-free-steps">
            {rows.length === 0 && !liveText ? (
              <div className="ga-form-hint">{running ? t('Waiting for the model…') : t('No steps.')}</div>
            ) : null}
            {rows.map((r, i) => (
              <div key={r.seq ?? `live-${i}`}
                className={`ga-wd-free-step ga-wd-free-step-${r.kind}${r.undone ? ' ga-wd-free-step-undone' : ''}`}>
                <span className="ga-wd-free-step-seq">{r.seq !== null ? `#${r.seq}` : '#?'}</span>
                <span className="ga-wd-free-step-tool">{r.tool}</span>
                <span className="ga-wd-free-step-mark">
                  {r.kind === 'write' ? '✓' : r.kind === 'refused' ? '!' : '→'}
                </span>
                <span className="ga-wd-free-step-line">{r.line}</span>
                {r.undone ? <span className="ga-form-hint">({t('undone')})</span> : null}
              </div>
            ))}
            {liveText ? <pre className="ga-wd-free-live">{liveText}</pre> : null}
          </div>

          {run.note && !running ? (
            <pre className="ga-wd-free-note">{run.note}</pre>
          ) : null}

          {skipped.length > 0 ? (
            <div className="ga-wd-free-skipped">
              <div className="ga-form-section-label">
                {t('Skipped steps')} ({skipped.length})
              </div>
              <ul>
                {skipped.map((s, i) => (
                  <li key={i}>
                    {s.seq !== undefined ? `#${s.seq} ` : ''}{s.line || ''}
                    {s.reason ? <span className="ga-form-hint"> — {s.reason}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {run.backup_path ? (
            <div className="ga-form-hint">{t('Backup')}: <code>{run.backup_path}</code></div>
          ) : null}

          {status === 'awaiting_review' ? (
            <div className="ga-wd-free-follow">
              <textarea
                className="ga-textarea"
                rows={2}
                value={followUp}
                onChange={(e) => setFollowUp(e.target.value)}
                placeholder={t('Follow-up for the model (a new turn of this run)…')}
              />
              <label className="ga-wd-free-field">
                <span>{t('Step budget')}</span>
                <input className="ga-input" inputMode="numeric" value={followSteps}
                  placeholder={String(run.max_steps ?? '')}
                  title={t('Raise the budget of this run; empty = keep it')}
                  onChange={(e) => setFollowSteps(e.target.value)} />
              </label>
              <label className="ga-wd-free-field">
                <span>{t('Token budget (run)')}</span>
                <input className="ga-input" inputMode="numeric" value={followTotal}
                  placeholder={String(run.max_tokens_total ?? '')}
                  title={t('Raise the budget of this run; empty = keep it')}
                  onChange={(e) => setFollowTotal(e.target.value)} />
              </label>
              <button className="ga-btn ga-btn-primary" disabled={busy || !followUp.trim()}
                onClick={() => { void sendFollowUp() }}>
                {t('Send')}
              </button>
            </div>
          ) : null}
        </div>
      )}

      <div className="ga-wd-free-runs">
        <div className="ga-form-section-label">{t('Runs')}</div>
        {runs.length === 0 ? (
          <div className="ga-form-hint">{t('No runs yet.')}</div>
        ) : (
          <table className="ga-wd-free-table">
            <thead>
              <tr>
                <th>{t('Task')}</th>
                <th>{t('Model')}</th>
                <th>{t('Status')}</th>
                <th>{t('Steps')}</th>
                <th>{t('Time')}</th>
                <th>{t('Backup')}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className={r.id === runId ? 'ga-wd-free-current' : undefined}
                  onClick={() => { if (r.id !== runId) void attach(r.id) }}>
                  <td className="ga-wd-free-task" title={r.task || ''}>{r.task}</td>
                  <td>{r.model}</td>
                  <td>{r.status}</td>
                  <td>{r.steps ?? 0}</td>
                  <td>{shortTime(r.created_at)}</td>
                  <td className="ga-wd-free-path" title={r.backup_path || ''}>{r.backup_path || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {confirmDiscard && run ? (
        <ConfirmDiscard
          preview={detail?.discard_preview || []}
          onCancel={() => setConfirmDiscard(false)}
          onConfirm={() => { setConfirmDiscard(false); void action('discard') }}
        />
      ) : null}
    </div>
  )
}

/** The Discard confirmation — an in-app dialog (no native box), listing what
 *  the undo will remove: every element the run created that still exists. */
function ConfirmDiscard({ preview, onCancel, onConfirm }: {
  preview: string[]
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useI18n()
  const title = t('Discard this run?')
  return createPortal(
    <div className="ga-modal-backdrop" onClick={onCancel}>
      <div
        className="ga-modal"
        role="dialog"
        aria-label={title}
        style={{ maxWidth: 560, width: 'min(560px, 92vw)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onCancel}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div>
            {t('Every change of the run is undone, newest first. A value someone else changed since is skipped and listed afterwards.')}
          </div>
          {preview.length ? (
            <>
              <div className="ga-form-section-label">{t('Removed with it')}</div>
              <ul className="ga-wd-free-preview">
                {preview.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </>
          ) : (
            <div className="ga-form-hint">{t('The run created nothing that still exists.')}</div>
          )}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onCancel}>{t('Cancel')}</button>
          <button type="button" className="ga-btn ga-btn-primary ga-btn-sm" onClick={onConfirm}>
            {t('Discard')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
