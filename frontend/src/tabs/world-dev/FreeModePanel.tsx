import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { syncHub } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { debounced } from '../../lib/guardedPoll'
import { useToast } from '../../lib/Toast'
import { usePersistentState } from '../../lib/usePersistentState'
import { kToTokens, posInt, tokensK } from './budget'
import './FreeModePanel.css'

/**
 * World Dev free mode (the only World Dev mode) — plan
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

/** Media job row/step statuses (world_dev_runs.MEDIA_STATUSES) → label. */
const MEDIA_STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  done: 'Done',
  failed: 'Failed',
  skipped: 'Skipped',
  cancelled: 'Cancelled',
  removed: 'Removed',
}
/** A burst of "generation" pushes (one per step change) reads the media once. */
const MEDIA_PUSH_DEBOUNCE_MS = 400

/** One media step of an element (GET /free/{id}/media). */
interface MediaStep {
  id: string
  label: string
  status: string
  note: string
}

/** One element the run created or changed, with its newest media job row. */
interface MediaElement {
  kind: 'location' | 'character' | string
  id: string
  name: string
  row_id: number
  status: string
  note: string
  steps: MediaStep[]
  produced: number
}

/** An element an interrupted run renders once accepted (no job row yet). */
interface MediaWaiting {
  kind: 'location' | 'character' | string
  id: string
  name: string
  steps: { id: string; label: string }[]
}

/** The run's media (plan 2026-11-25-world-dev-free-media, Tasks 10/11): the
 *  run switch, the media state (open · accepted · closed) and the elements;
 *  `waiting` lists what an interrupted run renders after Accept (F1). */
interface MediaStatus {
  enabled: boolean
  state: string
  elements: MediaElement[]
  waiting: MediaWaiting[]
}

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
  /** set on an informational record: this character stands in a place the
   *  undo removed — the step WAS reversed, the character must be placed anew */
  occupant?: string
}

/** One turn of the run (GET /free/{id} `turns`): how it ended and how many
 *  of its write rows are undone. */
interface TurnSummary {
  turn: number
  status: 'running' | 'kept' | 'cut_by_budget' | 'rolled_back' | string
  reason: string
  writes: number
  undone: number
}

interface TurnUsage {
  turn: number
  steps: number
  tokens: number
}

interface FreeDetail {
  run: FreeRun
  steps: Array<{ seq: number; tool: string; kind: string; line?: string | null;
                 undone_at?: string | null }>
  skipped: SkipEntry[]
  discard_preview: string[]
  /** per-turn outcome; absent from an older server */
  turns?: TurnSummary[]
  /** write rows of the run not undone — what Accept keeps */
  remaining_writes?: number
  /** the newest turn's counters (null when this server process ran no turn) */
  turn_usage?: TurnUsage | null
  busy: boolean
}

/** Budgets are PER TURN; the run totals are shown beside them. */
interface Counters {
  steps: number
  max_steps: number
  tokens: number
  max_tokens_total: number
  cost: number
  /** this turn's counters, null when unknown (a run from before a restart) */
  turn_steps: number | null
  turn_tokens: number | null
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
  turn?: number
  turn_steps?: number
  turn_tokens?: number
  error?: string
}

function countersOf(run: FreeRun, usage?: TurnUsage | null): Counters {
  const current = usage && usage.turn === (run.turn || 0) ? usage : null
  return {
    steps: run.steps || 0,
    max_steps: run.max_steps || 0,
    tokens: (run.tokens_in || 0) + (run.tokens_out || 0),
    max_tokens_total: run.max_tokens_total || 0,
    cost: run.cost_total || 0,
    turn_steps: current ? current.steps : null,
    turn_tokens: current ? current.tokens : null,
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

export function FreeModePanel({ model, provider, maxTokens, effort }: {
  model: string
  provider: string
  /** The per-reply budget of the tab's budget select ('' = auto, '0' = none). */
  maxTokens: string
  /** The tab's Effort select (Claude thinking depth; '' = the model's default). */
  effort: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()

  const [task, setTask] = usePersistentState('worlddev.free.task', '')
  // Budget fields: empty = the server default (shown as the placeholder,
  // never written into the persisted value); the token budget is in thousands.
  const [maxCalls, setMaxCalls] = usePersistentState('worlddev.free.maxCalls', '')
  const [maxTotalK, setMaxTotalK] = usePersistentState('worlddev.free.maxTotalK', '')
  const [defaults, setDefaults] = useState<{ max_steps: number | null; max_tokens_total: number | null } | null>(null)
  // The start form's media switch: the server renders what the run builds.
  const [genMedia, setGenMedia] = usePersistentState<boolean>('worlddev.free.media', true)
  const [buildingModels, setBuildingModels] = usePersistentState<string>('worlddev.free.buildings', 'hull')
  const [mediaOpen, setMediaOpen] = usePersistentState<boolean>('worlddev.free.mediaOpen', true)
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
  const [followCalls, setFollowCalls] = useState('')
  const [followTotalK, setFollowTotalK] = useState('')
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [confirmEmptyAccept, setConfirmEmptyAccept] = useState(false)
  const [discardSkipped, setDiscardSkipped] = useState<SkipEntry[] | null>(null)
  const [media, setMedia] = useState<{ run: string; status: MediaStatus } | null>(null)
  const [mediaBusy, setMediaBusy] = useState(false)

  const streamRef = useRef<AbortController | null>(null)
  // The run on screen. Stream events and detail reads of any other run are
  // dropped — switching runs must never mix two runs into one view.
  const runIdRef = useRef('')
  const refreshTimer = useRef<number | null>(null)
  const mounted = useRef(true)
  // The run whose live stream this panel followed since it was attached. A
  // run attached WITHOUT a stream (in review, or after a server restart) has
  // a persisted counter that may come from an earlier server process, whose
  // numbers restart at 1 — a follow-up then streams from 0.
  const streamedRunRef = useRef('')

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

  /** The run's media status — read on every detail read and on every
   *  "generation" push while a run is shown; never polled. */
  const loadMedia = useCallback(async (id: string) => {
    try {
      const d = await apiGet<MediaStatus>(`/world-dev/free/${encodeURIComponent(id)}/media`)
      if (mounted.current && runIdRef.current === id) setMedia({ run: id, status: d })
    } catch {
      // An older server without the media routes, or a passing error: the
      // section keeps its last view; the next push or status change re-reads.
    }
  }, [])

  const loadDetail = useCallback(async (id: string): Promise<FreeDetail | null> => {
    void loadMedia(id)
    try {
      const d = await apiGet<FreeDetail>(`/world-dev/free/${encodeURIComponent(id)}`)
      if (!mounted.current || runIdRef.current !== id) return d
      setDetail(d)
      setLiveStatus(d.run.status)
      setCounters(countersOf(d.run, d.turn_usage))
      // Rows the journal now holds come from the journal from here on.
      const known = new Set(d.steps.map((s) => s.seq))
      setLiveSteps((prev) => prev.filter((r) => r.seq !== null && !known.has(r.seq)))
      return d
    } catch (e) {
      toast(t('Loading the run failed') + ': ' + (e as Error).message, 'error')
      return null
    }
  }, [loadMedia, t, toast])

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
          turn_steps: typeof ev.turn_steps === 'number' ? ev.turn_steps : null,
          turn_tokens: typeof ev.turn_tokens === 'number' ? ev.turn_tokens : null,
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
    streamedRunRef.current = id
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
    streamedRunRef.current = ''
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
    // The keys of the old budget fields held a copied server default (and
    // plain tokens) — drop them so an old default can never come back.
    try {
      sessionStorage.removeItem('worlddev.free.maxSteps')
      sessionStorage.removeItem('worlddev.free.maxTotal')
    } catch { /* storage unavailable */ }
    apiGet<{ max_steps?: number; max_tokens_total?: number }>('/world-dev/free/defaults')
      .then((d) => {
        if (!mounted.current) return
        setDefaults({ max_steps: d.max_steps || null, max_tokens_total: d.max_tokens_total || null })
      })
      .catch(() => { /* no placeholder — the server still applies its defaults */ })
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
  // Occupant records are not skipped steps: the step was reversed, only the
  // character standing in the removed place has to be placed anew.
  const occupants = skipped.filter((s) => s.occupant !== undefined)
  const hardSkips = skipped.filter((s) => s.occupant === undefined)

  // Turns that did not end normally. A discarded run's turns are all undone
  // by the discard itself — its status says so, no per-turn banner.
  const discarded = run?.status === 'rolled_back' || run?.status === 'rollback_incomplete'
  const turnNotices: TurnSummary[] = detail && detail.run.id === runId && !discarded
    ? (detail.turns || []).filter((tr) => tr.status === 'rolled_back' || tr.status === 'cut_by_budget')
    : []
  const remainingWrites = detail && detail.run.id === runId
    ? detail.remaining_writes : undefined

  const start = useCallback(async () => {
    if (!model) { toast(t('Pick a model first'), 'error'); return }
    if (!task.trim()) { toast(t('Describe the task first'), 'error'); return }
    setBusy(true)
    try {
      const perReply = maxTokens.trim() ? parseInt(maxTokens, 10) : undefined
      const d = await apiPost<{ run_id: string }>('/world-dev/free/start', {
        task: task.trim(), model, provider,
        max_tokens: Number.isFinite(perReply) ? perReply : undefined,
        effort: effort || undefined,
        max_steps: posInt(maxCalls),
        max_tokens_total: kToTokens(maxTotalK),
        generate_media: genMedia,
        building_models: buildingModels,
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
  }, [attach, buildingModels, effort, genMedia, loadRuns, maxCalls, maxTokens, maxTotalK, model, provider, rememberEv, runId, t, task, toast])

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

  /** Accept: a run of which nothing remains in the world (every write of
   *  it rolled back) asks first — accepting it keeps nothing. */
  const requestAccept = useCallback(async () => {
    if (!runId) return
    setBusy(true)
    let d: FreeDetail | null = null
    try {
      d = await loadDetail(runId)
    } finally {
      if (mounted.current) setBusy(false)
    }
    if (!d || !mounted.current || runIdRef.current !== runId
        || !REVIEW_STATUSES.includes(d.run.status)) return
    if (d.remaining_writes === 0) setConfirmEmptyAccept(true)
    else void action('accept')
  }, [action, loadDetail, runId])

  const sendFollowUp = useCallback(async () => {
    if (!runId || !followUp.trim()) return
    setBusy(true)
    try {
      await apiPost(`/world-dev/free/${encodeURIComponent(runId)}/message`, {
        text: followUp.trim(),
        max_steps: posInt(followCalls),
        max_tokens_total: kToTokens(followTotalK),
      })
      setFollowUp('')
      setFollowCalls('')
      setFollowTotalK('')
      setDiscardSkipped(null)
      setLiveStatus('running')
      // Detail loaded without a live stream: the stored counter may belong
      // to an earlier server process (its numbers restart at 1 and a small
      // old counter would skip this turn's first events). Replay from 0 —
      // step rows merge by seq, so nothing doubles.
      if (streamedRunRef.current !== runId) rememberEv(runId, 0)
      void connect(runId)
    } catch (e) {
      toast(t('Sending failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [connect, followCalls, followTotalK, followUp, rememberEv, runId, t, toast])

  /** Discard: re-read the run first, so the confirmation lists what exists
   *  NOW (a player chat with a created character during a long review). */
  const openDiscard = useCallback(async () => {
    if (!runId) return
    setBusy(true)
    try {
      const d = await loadDetail(runId)
      if (d && mounted.current && runIdRef.current === runId
          && REVIEW_STATUSES.includes(d.run.status)) setConfirmDiscard(true)
    } finally {
      if (mounted.current) setBusy(false)
    }
  }, [loadDetail, runId])

  const newRun = useCallback(() => {
    streamRef.current?.abort()
    streamRef.current = null
    if (refreshTimer.current !== null) {
      window.clearTimeout(refreshTimer.current)
      refreshTimer.current = null
    }
    runIdRef.current = ''
    streamedRunRef.current = ''
    setRunId('')
    setDetail(null)
    setLiveSteps([])
    setLiveText('')
    setLiveStatus('')
    setCounters(null)
    setDiscardSkipped(null)
  }, [])

  // Live media status: every media row/step change pushes "generation" to
  // the admins; re-read this run's media on it while the run is shown.
  useEffect(() => {
    if (!runId) return
    const onPush = debounced(() => { void loadMedia(runId) }, MEDIA_PUSH_DEBOUNCE_MS)
    const off = syncHub().onTopics(['generation'], onPush)
    return () => { off(); onPush.cancel() }
  }, [loadMedia, runId])

  /** The run's media switch: off cancels the queued jobs (a running one ends
   *  after its step); on queues what is due — only while the run is in review. */
  const switchMedia = useCallback(async (enabled: boolean) => {
    if (!runId) return
    setMediaBusy(true)
    try {
      await apiPost(`/world-dev/free/${encodeURIComponent(runId)}/media-switch`, { enabled })
    } catch (e) {
      toast(t('Media switch failed') + ': ' + (e as Error).message, 'error')
    } finally {
      if (mounted.current) setMediaBusy(false)
      void loadMedia(runId)
    }
  }, [loadMedia, runId, t, toast])

  /** Retry what failed or was skipped (a paused character, an empty chain
   *  configured since): the server re-plans and queues what is due. */
  const retryMedia = useCallback(async () => {
    if (!runId) return
    setMediaBusy(true)
    try {
      const d = await apiPost<{ queued?: number[] }>(
        `/world-dev/free/${encodeURIComponent(runId)}/media/retry`, {})
      const n = (d.queued || []).length
      toast(n ? t('{n} media job(s) queued').replace('{n}', String(n)) : t('Nothing to retry'))
    } catch (e) {
      toast(t('Media retry failed') + ': ' + (e as Error).message, 'error')
    } finally {
      if (mounted.current) setMediaBusy(false)
      void loadMedia(runId)
    }
  }, [loadMedia, runId, t, toast])

  const mediaView = media && media.run === runId ? media.status : null
  // An interrupted run renders nothing before Accept: what it would render.
  const mediaWaiting = mediaView && status === 'interrupted' ? (mediaView.waiting || []) : []
  // An element with a row from an earlier turn AND new due steps shows its
  // waiting steps on that row; only the others get a row of their own, so
  // the header counts each element once.
  const mediaWaitingByKey = new Map(mediaWaiting.map((w) => [`${w.kind}:${w.id}`, w]))
  const mediaElementKeys = new Set((mediaView?.elements || []).map((el) => `${el.kind}:${el.id}`))
  const mediaWaitingOnly = mediaWaiting.filter((w) => !mediaElementKeys.has(`${w.kind}:${w.id}`))
  const mediaRetryable = !!mediaView && mediaView.elements.some((el) => (
    el.status === 'failed' || el.status === 'skipped'
    || el.steps.some((s) => s.status === 'failed' || s.status === 'skipped')))

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
            {inReview && remainingWrites === 0
              ? ' · ' + t('nothing of this run remains in the world')
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
            onClick={() => { void requestAccept() }}>
            {t('Accept')}
          </button>
          <button className="ga-btn ga-btn-sm ga-wd-free-danger" disabled={busy || !inReview}
            title={t('Undo everything the run built')}
            onClick={() => { void openDiscard() }}>
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
              <span>{t('Tool-call budget (per turn)')}</span>
              <input className="ga-input" inputMode="numeric" value={maxCalls}
                placeholder={defaults?.max_steps ? String(defaults.max_steps) : ''}
                onChange={(e) => setMaxCalls(e.target.value)} />
            </label>
            <label className="ga-wd-free-field">
              <span>{t('Token budget per turn (k)')}</span>
              <input className="ga-input" inputMode="numeric" value={maxTotalK}
                placeholder={defaults?.max_tokens_total ? String(Math.round(defaults.max_tokens_total / 1000)) : ''}
                onChange={(e) => setMaxTotalK(e.target.value)} />
            </label>
            <label className="ga-wd-free-check"
              title={t('After each turn the server renders the standard images and 3D models of what the run built; Discard removes them again.')}>
              <input type="checkbox" checked={genMedia}
                onChange={(e) => setGenMedia(e.target.checked)} />
              <span>{t('Generate media')}</span>
            </label>
            <label className="ga-wd-free-field"
              title={t('How the run builds 3D buildings: a Blender hull from the floor plan, or an image-based 3D model')}>
              <span>{t('Buildings')}</span>
              <select className="ga-input" value={buildingModels}
                onChange={(e) => setBuildingModels(e.target.value)}>
                <option value="hull">{t('Blender (from floor plan)')}</option>
                <option value="mesh">{t('3D model (img2mesh)')}</option>
              </select>
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
              <span title={t('The budgets apply to each turn; the run total counts every turn')}>
                <strong>{t('Tool calls this turn')}</strong>{' '}
                {c.turn_steps !== null ? c.turn_steps : '–'} / {c.max_steps}
                <span className="ga-form-hint"> · {t('run total')} {c.steps}</span>
              </span>
              <span title={t('The budgets apply to each turn; the run total counts every turn')}>
                <strong>{t('Tokens this turn (k)')}</strong>{' '}
                {c.turn_tokens !== null ? tokensK(c.turn_tokens) : '–'} / {tokensK(c.max_tokens_total)}
                <span className="ga-form-hint"> · {t('run total')} {tokensK(c.tokens)}</span>
              </span>
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

          {turnNotices.map((tr) => (
            <div key={tr.turn}
              className={`ga-wd-free-turn ga-wd-free-turn-${tr.status === 'rolled_back' ? 'rolled' : 'cut'}`}>
              {tr.status === 'rolled_back'
                ? t('Turn {n} rolled back').replace('{n}', String(tr.turn))
                  + (tr.reason ? ': ' + tr.reason : '')
                  + ' — ' + t('{k} change(s) removed').replace('{k}', String(tr.undone))
                : t('Turn {n} stopped by budget — work kept, send a follow-up to continue')
                  .replace('{n}', String(tr.turn))
                  + (tr.reason ? ': ' + tr.reason : '')
                  + (tr.writes ? ' (' + t('{k} change(s) kept').replace('{k}', String(tr.writes - tr.undone)) + ')' : '')}
            </div>
          ))}

          {mediaView ? (
            <div className="ga-wd-free-media">
              <div className="ga-wd-free-media-head">
                <button type="button" className="ga-wd-free-media-toggle"
                  aria-expanded={mediaOpen} onClick={() => setMediaOpen(!mediaOpen)}>
                  <span aria-hidden="true">{mediaOpen ? '▾' : '▸'}</span>
                  <span className="ga-form-section-label">{t('Media')}</span>
                  <span className="ga-form-hint">({mediaView.elements.length + mediaWaitingOnly.length})</span>
                </button>
                <label className="ga-wd-free-check"
                  title={running && !mediaView.enabled
                    ? t('Media can be switched on again once the turn has ended')
                    : t('After each turn the server renders the standard images and 3D models of what the run built; Discard removes them again.')}>
                  <input type="checkbox" checked={mediaView.enabled}
                    disabled={mediaBusy || !isOpen || (running && !mediaView.enabled)}
                    onChange={(e) => { void switchMedia(e.target.checked) }} />
                  <span>{t('Generate media')}</span>
                </label>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={mediaBusy || !inReview || status === 'interrupted'
                    || !mediaView.enabled || !mediaRetryable}
                  onClick={() => { void retryMedia() }}>
                  {t('Retry failed/skipped')}
                </button>
              </div>
              {mediaOpen ? (
                mediaView.elements.length === 0 && mediaWaiting.length === 0 ? (
                  <div className="ga-form-hint">{t('No media jobs yet.')}</div>
                ) : (
                  <>
                  {mediaWaiting.length ? (
                    <div className="ga-form-hint">
                      {t('This run was interrupted: its media are rendered after Accept; Discard drops them.')}
                    </div>
                  ) : null}
                  <div className="ga-wd-free-media-grid">
                    {mediaView.elements.map((el) => {
                      const waitingHere = mediaWaitingByKey.get(`${el.kind}:${el.id}`)
                      return (
                      <div key={`${el.kind}:${el.id}`} className="ga-wd-free-media-row">
                        <span className="ga-wd-free-media-name" title={el.id}>
                          {el.kind === 'location' ? t('location') : el.kind === 'character' ? t('character') : el.kind} &quot;{el.name || el.id}&quot;
                        </span>
                        <span className={`ga-wd-free-chip ga-wd-free-chip-${el.status}`}
                          title={el.note || undefined}>
                          {t(MEDIA_STATUS_LABELS[el.status] || el.status)}
                        </span>
                        <span className="ga-wd-free-media-steps">
                          {el.steps.map((s) => (
                            <span key={s.id}
                              className={`ga-wd-free-chip ga-wd-free-chip-sm ga-wd-free-chip-${s.status}`}
                              title={(t(MEDIA_STATUS_LABELS[s.status] || s.status))
                                + (s.note ? ' — ' + s.note : '')}>
                              {s.label}
                            </span>
                          ))}
                          {waitingHere ? waitingHere.steps.map((s) => (
                            <span key={`waiting:${s.id}`}
                              className="ga-wd-free-chip ga-wd-free-chip-sm ga-wd-free-chip-waiting"
                              title={t('Waiting for Accept')}>
                              {s.label}
                            </span>
                          )) : null}
                          {el.produced ? (
                            <span className="ga-form-hint">
                              {t('{n} file(s)').replace('{n}', String(el.produced))}
                            </span>
                          ) : null}
                        </span>
                        {el.note ? (
                          <span className="ga-form-hint ga-wd-free-media-note">{el.note}</span>
                        ) : null}
                      </div>
                      )
                    })}
                    {mediaWaitingOnly.map((el) => (
                      <div key={`waiting:${el.kind}:${el.id}`} className="ga-wd-free-media-row">
                        <span className="ga-wd-free-media-name" title={el.id}>
                          {el.kind === 'location' ? t('location') : el.kind === 'character' ? t('character') : el.kind} &quot;{el.name || el.id}&quot;
                        </span>
                        <span className="ga-wd-free-chip ga-wd-free-chip-waiting">
                          {t('Waiting for Accept')}
                        </span>
                        <span className="ga-wd-free-media-steps">
                          {el.steps.map((s) => (
                            <span key={s.id} className="ga-wd-free-chip ga-wd-free-chip-sm ga-wd-free-chip-waiting">
                              {s.label}
                            </span>
                          ))}
                        </span>
                      </div>
                    ))}
                  </div>
                  </>
                )
              ) : null}
            </div>
          ) : null}

          {run.note && !running ? (
            <pre className="ga-wd-free-note">{run.note}</pre>
          ) : null}

          {hardSkips.length > 0 ? (
            <div className="ga-wd-free-skipped">
              <div className="ga-form-section-label">
                {t('Skipped steps')} ({hardSkips.length})
              </div>
              <ul>
                {hardSkips.map((s, i) => (
                  <li key={i}>
                    {s.seq !== undefined ? `#${s.seq} ` : ''}{s.line || ''}
                    {s.reason ? <span className="ga-form-hint"> — {s.reason}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {occupants.length > 0 ? (
            <div className="ga-wd-free-skipped">
              <div className="ga-form-section-label">
                {t('Place anew')} ({occupants.length})
              </div>
              <ul>
                {occupants.map((s, i) => (
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
                <span>{t('Tool-call budget (per turn)')}</span>
                <input className="ga-input" inputMode="numeric" value={followCalls}
                  placeholder={String(run.max_steps ?? '')}
                  title={t('Raise the budget for this and every later turn; empty = keep it')}
                  onChange={(e) => setFollowCalls(e.target.value)} />
              </label>
              <label className="ga-wd-free-field">
                <span>{t('Token budget per turn (k)')}</span>
                <input className="ga-input" inputMode="numeric" value={followTotalK}
                  placeholder={run.max_tokens_total != null ? String(Math.round(run.max_tokens_total / 1000)) : ''}
                  title={t('Raise the budget for this and every later turn; empty = keep it')}
                  onChange={(e) => setFollowTotalK(e.target.value)} />
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
                <th>{t('Tool calls')}</th>
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

      {confirmEmptyAccept && run ? (
        <ConfirmEmptyAccept
          onCancel={() => setConfirmEmptyAccept(false)}
          onConfirm={() => { setConfirmEmptyAccept(false); void action('accept') }}
        />
      ) : null}
    </div>
  )
}

/** Accept on a run with no remaining write — an in-app dialog (no native
 *  box): accepting keeps nothing, which is easy to miss after a rollback. */
function ConfirmEmptyAccept({ onCancel, onConfirm }: {
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useI18n()
  const title = t('Accept this run?')
  return createPortal(
    <div className="ga-modal-backdrop" onClick={onCancel}>
      <div
        className="ga-modal"
        role="dialog"
        aria-label={title}
        style={{ maxWidth: 480, width: 'min(480px, 92vw)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onCancel}>×</button>
        </div>
        <div className="ga-modal-body">
          {t('Nothing of this run remains in the world — accept anyway?')}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onCancel}>{t('Cancel')}</button>
          <button type="button" className="ga-btn ga-btn-primary ga-btn-sm" onClick={onConfirm}>
            {t('Accept')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
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
