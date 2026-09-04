/**
 * The live queue: what the idle engine will work on, in the order it will do
 * it, with the gate that decides whether it may start at all.
 *
 * The order is the SERVER's (`GET /improvements/queue` numbers every row from
 * 1) — this view never sorts. Both feeds poll through the shared hub, so the
 * queue and its status head refresh together without two timers of their own.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { usePoll } from '../../player/usePolling'
import { FilterChipRow } from '../../components/FilterChipRow'
import { fetchQueue, fetchStatus, fetchTypes, saveSettings } from './api'
import { STEP_STATUS_LABELS } from './types'
import type {
  EngineStatus, ImprovementType, QueueSnapshot, Settings,
} from './types'

const POLL_INTERVAL_MS = 5000

/** One colour per entry, so a long queue still reads as blocks of work. */
const ENTRY_COLORS = [
  '#79c0ff', '#d2a8ff', '#7ee2a8', '#e3b341',
  '#ff9ec7', '#8fd17f', '#ffae8a', '#b388ff',
]

/**
 * The colour is a property of the ENTRY, not of its place in the snapshot:
 * indexing by position would recolour the whole queue every time the head
 * entry drains. A small string hash keeps a block of work the same colour for
 * as long as it is in the queue.
 */
function colorOf(improvementId: string): string {
  let hash = 0
  for (let i = 0; i < improvementId.length; i++) {
    hash = (hash * 31 + improvementId.charCodeAt(i)) | 0
  }
  return ENTRY_COLORS[Math.abs(hash) % ENTRY_COLORS.length]
}

/** m:ss — the countdown is minutes, and a bare number of seconds is unreadable. */
function mmss(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** A system stamp (technical, not game time) rendered as a wall clock. */
function clockTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString()
}

/** The same stamp WITH its date, in the locale's short form and without
 *  seconds — for a list that spans days, where a bare clock time cannot say
 *  which day it belongs to. The running queue keeps `clockTime`: there every
 *  stamp is from now, and the compact row must not widen. */
function clockDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? '' : d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

export function QueueView() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [types, setTypes] = useState<ImprovementType[]>([])
  const [entryFilter, setEntryFilter] = useState('')
  const [idleInput, setIdleInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [editingIdle, setEditingIdle] = useState(false)

  /**
   * The client's ONE source of truth for the two settings. The polled status
   * only SEEDS it: afterwards it changes on a PUT answer, and on a poll only
   * while nothing is in flight and the user is not typing. Two controls used to
   * read `status` independently, so a blur (idle minutes) plus a click (engine)
   * one second apart each sent the other's five-second-old value and the last
   * PUT to land undid the first one.
   */
  const [settings, setSettings] = useState<Settings | null>(null)
  /** The same value readable SYNCHRONOUSLY — a handler must not wait for a render. */
  const settingsRef = useRef<Settings | null>(null)
  /** One PUT at a time; a commit made during a save waits here and replaces it. */
  const savingRef = useRef(false)
  const pendingRef = useRef<Settings | null>(null)

  const applySettings = useCallback((next: Settings) => {
    settingsRef.current = next
    setSettings(next)
  }, [])

  const { data: snapshot, error: queueError, refresh: refreshQueue } =
    usePoll<QueueSnapshot>('improvements-queue', fetchQueue,
      { intervalMs: POLL_INTERVAL_MS })
  const { data: status, error: statusError, refresh: refreshStatus } =
    usePoll<EngineStatus>('improvements-status', fetchStatus,
      { intervalMs: POLL_INTERVAL_MS })

  /** The last failure of either feed — polling continues either way. */
  const pollError = statusError || queueError

  useEffect(() => {
    fetchTypes().then(setTypes).catch(() => setTypes([]))
  }, [])

  // The field follows the server until the user types into it — the poll would
  // otherwise overwrite half-entered digits every five seconds.
  const serverIdle = status ? String(status.idle_minutes) : ''
  useEffect(() => {
    setIdleInput((current) => (current === '' ? serverIdle : current))
  }, [serverIdle])

  // Seed from the first status, and keep following the server afterwards — but
  // never while our own PUT is in flight or the user is mid-edit, or the poll
  // would hand back the very value the user just changed.
  useEffect(() => {
    if (!status) return
    if (savingRef.current || editingIdle) return
    const current = settingsRef.current
    if (current && current.enabled === status.enabled
      && current.idle_minutes === status.idle_minutes) return
    applySettings({
      enabled: status.enabled, idle_minutes: status.idle_minutes,
    })
  }, [applySettings, editingIdle, status])

  const typeLabel = useCallback((typeId: string) => {
    const found = types.find((x) => x.id === typeId)
    return found ? found.label : typeId
  }, [types])

  const statusLabel = useCallback((value: string) => (
    STEP_STATUS_LABELS[value] ? t(STEP_STATUS_LABELS[value]) : value
  ), [t])

  const queue = useMemo(() => snapshot?.queue ?? [], [snapshot])
  const recent = snapshot?.recent ?? []

  /** Distinct entries in queue order — the chips AND the colour index. */
  const entries = useMemo(() => {
    const out: Array<{ value: string; label: string }> = []
    for (const row of queue) {
      if (!out.some((e) => e.value === row.improvement_id)) {
        out.push({ value: row.improvement_id, label: row.label })
      }
    }
    return out
  }, [queue])

  const visible = entryFilter
    ? queue.filter((row) => row.improvement_id === entryFilter)
    : queue

  /**
   * Takes the FULL pair, applies it locally before awaiting anything (so the
   * next handler in the same blur+click pair already reads the new value) and
   * sends exactly one PUT at a time.
   */
  const commitSettings = useCallback(async (next: Settings) => {
    applySettings(next)
    if (savingRef.current) {
      pendingRef.current = next
      return
    }
    savingRef.current = true
    setSaving(true)
    try {
      let send: Settings | null = next
      while (send) {
        const stored = await saveSettings(send.enabled, send.idle_minutes)
        // The stored answer wins over the optimistic value — unless another
        // commit came in meanwhile, which is sent next and wins in turn.
        send = pendingRef.current
        pendingRef.current = null
        if (!send) {
          applySettings({
            enabled: stored.enabled, idle_minutes: stored.idle_minutes,
          })
          setIdleInput(String(stored.idle_minutes))
        }
      }
      await refreshStatus()
      await refreshQueue()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      pendingRef.current = null
      savingRef.current = false
      setSaving(false)
    }
  }, [applySettings, refreshQueue, refreshStatus, t, toast])

  const toggleEngine = useCallback(() => {
    const current = settingsRef.current
    if (!current) return
    commitSettings({ ...current, enabled: !current.enabled })
  }, [commitSettings])

  const commitIdle = useCallback(() => {
    setEditingIdle(false)
    const current = settingsRef.current
    if (!current) return
    const minutes = parseInt(idleInput, 10)
    if (!Number.isFinite(minutes) || minutes === current.idle_minutes) {
      setIdleInput(String(current.idle_minutes))
      return
    }
    commitSettings({ ...current, idle_minutes: minutes })
  }, [commitSettings, idleInput])

  const onIdleKey = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') e.currentTarget.blur()
  }, [])

  // A failing feed must not leave the tab on "Loading…" forever — the poll
  // hub keeps retrying, so the message says what is wrong and stays put.
  if (!status) {
    return pollError
      ? <div className="ga-imp-error">
          {t('Error')}: {errorText(pollError)}
        </div>
      : <div className="ga-loading">{t('Loading…')}</div>
  }

  const gate = (() => {
    switch (status.reason) {
      case 'disabled': return t('Engine off')
      case 'frozen': return t('World frozen')
      case 'busy': return t('Step running')
      case 'active':
        return `${t('Next step allowed in')} ${mmss(status.next_allowed_in_s)}`
      default: return t('Ready to run')
    }
  })()

  // Until the seeding effect has run once, the freshly polled status IS the
  // local state — the switch is never rendered without a value.
  const shown: Settings = settings
    ?? { enabled: status.enabled, idle_minutes: status.idle_minutes }

  const estimateHours = status.estimate_s
    ? (status.estimate_s / 3600).toFixed(1)
    : ''

  return (
    <div className="ga-page-scroll">
      {/* Data is on screen, so the list stays — but a stale feed has to say so
          rather than quietly showing the last good snapshot forever. */}
      {pollError ? (
        <div className="ga-imp-error">{t('Error')}: {errorText(pollError)}</div>
      ) : null}
      <div className="ga-imp-head">
        {/* A switch, not a state-labelled button: the old label read as a
            status ("Engine off") and nobody clicked it. It stays clickable
            while a save runs — the reported flow is "type minutes → click the
            switch", where the blur's save is still in flight and a disabled
            checkbox would swallow the click; `commitSettings` queues it. */}
        <label className="ga-imp-switch">
          <input type="checkbox" checked={shown.enabled}
            onChange={toggleEngine} />
          {' '}{t('Engine')}
        </label>
        <label className="ga-imp-idle">
          {t('Idle minutes')}
          <input type="number" min={1} max={1440} className="ga-input"
            value={idleInput} disabled={saving}
            onFocus={() => setEditingIdle(true)}
            onChange={(e) => setIdleInput(e.target.value)}
            onBlur={commitIdle} onKeyDown={onIdleKey} />
        </label>
        <span className="ga-form-hint">
          {t('Idle since')} {mmss(status.idle_seconds)} · {gate}
        </span>
      </div>

      {status.running_step ? (
        <div className="ga-imp-running">
          <span className="ga-status-ok">{t('Step running')}</span>{' '}
          {status.running_step.candidate_label || status.running_step.candidate_key}
          {status.running_step.started_at
            ? <span className="ga-list-row-sub">
                {clockTime(status.running_step.started_at)}
              </span>
            : null}
        </div>
      ) : null}

      {/* An active filter keeps the row visible even when its entry was the
          last one left — otherwise the "All" chip disappears with it and the
          view stays filtered with no way back. */}
      {entries.length > 1 || entryFilter ? (
        <div className="ga-imp-filter">
          <FilterChipRow allLabel={t('All')} value={entryFilter}
            options={entries} onChange={setEntryFilter} />
        </div>
      ) : null}

      <ul className="ga-list">
        {visible.length === 0 ? (
          <li className="ga-list-empty">{t('Nothing queued')}</li>
        ) : visible.map((row) => (
          <li key={`${row.improvement_id}:${row.candidate_key}`}
            className="ga-list-row">
            <span className="ga-list-row-main">
              <span className="ga-list-row-sub">{row.pos}.</span>
              <span className="ga-imp-dot"
                style={{ background: colorOf(row.improvement_id) }} />
              <span>{row.label}</span>
              <span className="ga-list-row-sub">{typeLabel(row.type_id)}</span>
              <span className="ga-list-row-sub">
                {row.candidate_label || row.candidate_key}
              </span>
            </span>
            <span className={row.status === 'running'
              ? 'ga-status-ok' : 'ga-status-paused'}>
              {statusLabel(row.status)}
            </span>
          </li>
        ))}
      </ul>

      <div className="ga-imp-foot">
        <span>{t('{n} steps pending').replace('{n}',
          String(status.pending_total))}</span>
        {estimateHours
          ? <span>{t('~{h} h estimated').replace('{h}', estimateHours)}</span>
          : null}
      </div>

      {recent.length ? (
        <div className="ga-imp-recent">
          <div className="ga-form-section-label">{t('Recently finished')}</div>
          <ul className="ga-list">
            {recent.map((row) => (
              <li key={`${row.improvement_id}:${row.candidate_key}`}
                className="ga-list-row">
                <span className="ga-list-row-main">
                  <span>{row.label}</span>
                  <span className="ga-list-row-sub">
                    {row.candidate_label || row.candidate_key}
                  </span>
                  {row.error
                    ? <span className="ga-list-row-sub">{row.error}</span>
                    : null}
                </span>
                <span className={row.status === 'done'
                  ? 'ga-status-ok' : 'ga-status-paused'}>
                  {statusLabel(row.status)} {clockDateTime(row.finished_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
