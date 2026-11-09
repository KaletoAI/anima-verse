/**
 * OutfitBatchDialog — pre-warm the 3D chain (T-pose reference → mesh) for
 * outfit-piece COMBINATIONS of a character, without dressing them.
 *
 * The filter matrix is the dialog: one block per slot, inside it "(empty)"
 * plus every piece of that slot. The combinations are the cartesian product
 * over the slots, so unticking one piece can remove thousands of renders —
 * which is why the count and the estimated duration are recomputed on every
 * click (debounced) and shown in full above the matrix. Large numbers are NOT
 * blocked: the user decides, deliberately.
 *
 * The dialog is only a VIEW on the queued job behind
 * /characters/{n}/outfit-batch: it may be closed at any time, the task keeps
 * running at low priority, and reopening shows the queue state plus whatever
 * progress there is. After a server restart the in-process detail is gone but
 * the queue state and the counts (derived from the caches) are still right.
 *
 * Backend: GET /characters/{n}/outfit-batch, POST .../outfit-batch/estimate,
 * POST .../outfit-batch/start, POST .../outfit-batch/stop.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

export interface OutfitPieceOption {
  item_id: string
  name: string
}

export interface OutfitBatchResult {
  signature: string
  name: string
  ok: boolean
  cached: boolean
  error: string
}

export interface OutfitBatchStatus {
  running: boolean
  total: number
  done: number
  skipped: number
  failed: number
  current: { name: string; step: 'ref' | 'mesh' } | null
  results: OutfitBatchResult[]
}

export interface OutfitBatchQueue {
  state: 'pending' | 'running' | 'none'
  task_id: string
}

interface Stats {
  total: number
  total_exact: boolean
  missing: number
  missing_exact: boolean
  est_seconds: number
}

interface CacheSide {
  total: number
  valid: number
  stale: number
  stale_bytes: number
}

export interface CacheReport {
  refs: CacheSide
  meshes: CacheSide
  /** Garment files (hair meshes, their images and fits) of stale
   *  fingerprints — their keys are part of `stale_signatures` too. */
  garments?: CacheSide
  stale_signatures: string[]
  protected: string[]
}

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 MB'
  const mb = bytes / 1e6
  return mb < 1 ? `${Math.round(bytes / 1e3)} kB` : `${mb.toFixed(1)} MB`
}

const POLL_MS = 3000
const ESTIMATE_DEBOUNCE_MS = 300
/** Marks the "slot stays empty" option inside the picked sets. */
const EMPTY = '\u0000empty'

/** Coarse but honest: a run of this size is measured in days, so minutes of
 *  precision would be noise. */
function humanDuration(seconds: number, t: (s: string) => string): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '—'
  const min = seconds / 60
  if (min < 1) return `${Math.round(seconds)} ${t('s')}`
  if (min < 90) return `${Math.round(min)} ${t('min')}`
  const hours = min / 60
  if (hours < 36) return `${hours.toFixed(1)} ${t('h')}`
  const days = hours / 24
  if (days < 365) return `${days.toFixed(days < 10 ? 1 : 0)} ${t('days')}`
  return `${(days / 365).toFixed(1)} ${t('years')}`
}

export function OutfitBatchDialog({
  open,
  character,
  onClose,
  onDone,
}: {
  open: boolean
  character: string
  onClose: () => void
  /** Called when a run finished — lets the 3D field reload its own status. */
  onDone?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [options, setOptions] = useState<Record<string, OutfitPieceOption[]>>({})
  const [status, setStatus] = useState<OutfitBatchStatus | null>(null)
  const [queue, setQueue] = useState<OutfitBatchQueue>({ state: 'none', task_id: '' })
  /** slot -> selected options; EMPTY stands for "slot stays empty". */
  const [picked, setPicked] = useState<Record<string, Set<string>>>({})
  const [stats, setStats] = useState<Stats | null>(null)
  const [statsError, setStatsError] = useState('')
  const [force, setForce] = useState(false)
  // Coherence filter, on by default: cutting the set down to combinations
  // that actually go together is the point of the feature.
  const [coherentOnly, setCoherentOnly] = useState(true)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  // Cache section — never auto-loaded: the enumeration behind it can cost
  // seconds on a big inventory, so it runs only when asked for.
  const [cache, setCache] = useState<CacheReport | null>(null)
  const [cacheError, setCacheError] = useState('')
  const [cacheBusy, setCacheBusy] = useState(false)
  const [armed, setArmed] = useState(false)
  // Which (character, open) the default selection was seeded for — later polls
  // must not overwrite what the admin ticked.
  const seededRef = useRef('')
  const activeRef = useRef(false)
  // Held in a ref so an unmemoized parent callback does not restart the poll.
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  const refresh = useCallback(async () => {
    if (!character) return
    try {
      const d = await apiGet<{
        options: Record<string, OutfitPieceOption[]>
        status: OutfitBatchStatus
        queue: OutfitBatchQueue
      }>(`/characters/${enc}/outfit-batch`)
      setOptions(d.options || {})
      setStatus(d.status || null)
      setQueue(d.queue || { state: 'none', task_id: '' })
      // A task that just left the queue invalidates the 3D field's own status.
      const active = (d.queue?.state || 'none') !== 'none'
      if (activeRef.current && !active) onDoneRef.current?.()
      activeRef.current = active
    } catch {
      setOptions({})
      setStatus(null)
      setQueue({ state: 'none', task_id: '' })
    } finally {
      setLoaded(true)
    }
  }, [character, enc])

  useEffect(() => {
    if (!open) return
    setLoaded(false)
    void refresh()
    const id = setInterval(() => { void refresh() }, POLL_MS)
    return () => clearInterval(id)
  }, [open, refresh])

  // Default selection: everything ticked, "(empty)" included — that IS the
  // full set of combinations.
  useEffect(() => {
    if (!open || !loaded) return
    const key = `${character}:${open}`
    if (seededRef.current === key) return
    seededRef.current = key
    const next: Record<string, Set<string>> = {}
    for (const [slot, pieces] of Object.entries(options)) {
      next[slot] = new Set([EMPTY, ...pieces.map((p) => p.item_id)])
    }
    setPicked(next)
  }, [open, loaded, options, character])

  useEffect(() => {
    if (!open) seededRef.current = ''
  }, [open])

  /** The picked sets as the backend's filter: item ids plus null for empty. */
  const filter = useMemo(() => {
    const out: Record<string, Array<string | null>> = {}
    for (const [slot, pieces] of Object.entries(options)) {
      const sel = picked[slot]
      if (!sel) continue
      const values: Array<string | null> = []
      if (sel.has(EMPTY)) values.push(null)
      for (const p of pieces) if (sel.has(p.item_id)) values.push(p.item_id)
      out[slot] = values
    }
    return out
  }, [options, picked])

  const complete = useMemo(
    () => Object.keys(options).length > 0
      && Object.keys(options).every((slot) => (filter[slot] || []).length > 0),
    [options, filter])

  // Every toggle recomputes count and duration — debounced, because a click
  // series (All / None) would otherwise fire one request per slot.
  useEffect(() => {
    if (!open || !loaded || !complete) {
      if (!complete) setStats(null)
      return
    }
    let cancelled = false
    const id = setTimeout(() => {
      void (async () => {
        try {
          const d = await apiPost<Stats>(
            `/characters/${enc}/outfit-batch/estimate`,
            { slots: filter, force, coherent_only: coherentOnly })
          if (!cancelled) { setStats(d); setStatsError('') }
        } catch (e) {
          if (!cancelled) { setStats(null); setStatsError((e as Error).message) }
        }
      })()
    }, ESTIMATE_DEBOUNCE_MS)
    return () => { cancelled = true; clearTimeout(id) }
  }, [open, loaded, complete, enc, filter, force, coherentOnly])

  const busyQueue = queue.state !== 'none'

  const toggle = useCallback((slot: string, value: string) => {
    setPicked((prev) => {
      const sel = new Set(prev[slot] || [])
      if (sel.has(value)) {
        // The last option of a slot may not be removed — a slot without an
        // option would make the whole product zero.
        if (sel.size <= 1) return prev
        sel.delete(value)
      } else {
        sel.add(value)
      }
      return { ...prev, [slot]: sel }
    })
  }, [])

  const setSlot = useCallback((slot: string, values: string[]) => {
    setPicked((prev) => ({ ...prev, [slot]: new Set(values) }))
  }, [])

  const start = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      const d = await apiPost<{ total: number; missing: number }>(
        `/characters/${enc}/outfit-batch/start`,
        { slots: filter, force, coherent_only: coherentOnly })
      toast(`${t('Queued')} — ${d.missing.toLocaleString()} / ${d.total.toLocaleString()}`)
      await refresh()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [busy, coherentOnly, enc, filter, force, refresh, t, toast])

  const verifyCache = useCallback(async () => {
    if (cacheBusy) return
    setCacheBusy(true)
    setArmed(false)
    try {
      const d = await apiGet<CacheReport>(`/characters/${enc}/outfit-batch/cache`)
      setCache(d)
      setCacheError('')
    } catch (e) {
      setCache(null)
      setCacheError((e as Error).message)
    } finally {
      setCacheBusy(false)
    }
  }, [cacheBusy, enc])

  const purgeCache = useCallback(async () => {
    if (cacheBusy || !cache?.stale_signatures.length) return
    setCacheBusy(true)
    try {
      const d = await apiPost<{ deleted_files: number; freed_bytes: number }>(
        `/characters/${enc}/outfit-batch/cache/purge`,
        { signatures: cache.stale_signatures })
      toast(`${t('Deleted')}: ${d.deleted_files} — ${fmtBytes(d.freed_bytes)}`)
      setArmed(false)
      setCacheBusy(false)
      await verifyCache()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setCacheBusy(false)
    }
  }, [cache, cacheBusy, enc, t, toast, verifyCache])

  const stop = useCallback(async () => {
    try {
      await apiPost(`/characters/${enc}/outfit-batch/stop`, {})
      await refresh()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, refresh, t, toast])

  if (!open) return null

  const slots = Object.keys(options)
  const results = status?.results || []

  return createPortal(
    <div className="ga-modal-backdrop"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="ga-modal" role="dialog"
        aria-label={t('3D models for all outfit combinations')}
        style={{ maxWidth: 760, width: 'min(760px, 94vw)' }}>
        <div className="ga-modal-header">
          <span>⚙ {t('3D models for all outfit combinations')} — {character}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}
            aria-label={t('Close')}>×</button>
        </div>
        <div className="ga-modal-body">
          <div className="ga-hint">
            {t('Renders the T-pose reference and the mesh for every combination of the outfit pieces in this inventory — per slot one piece or nothing, without changing what the character wears. Carried items are not part of these combinations, and combinations that already have a mesh are skipped.')}
          </div>

          {!loaded ? (
            <div className="ga-loading">{t('Loading…')}</div>
          ) : !slots.length ? (
            <div className="ga-hint">{t('This inventory has no outfit pieces.')}</div>
          ) : (
            <>
              <div className="ga-outfit-batch-summary">
                {statsError ? (
                  <span className="ga-hint">{statsError}</span>
                ) : !stats ? (
                  <span className="ga-hint">{t('Calculating…')}</span>
                ) : (
                  <>
                    <span>{t('Combinations')}: <b>
                      {stats.total_exact ? '' : `${t('up to')} `}
                      {stats.total.toLocaleString()}</b></span>
                    <span>{t('missing')}: <b>
                      {stats.missing_exact ? '' : `${t('up to')} `}
                      {stats.missing.toLocaleString()}</b></span>
                    <span>{t('estimated')}: <b>~{humanDuration(stats.est_seconds, t)}</b></span>
                  </>
                )}
                <label className="ga-check-row" style={{ marginLeft: 'auto' }}
                  title={t('Only render combinations whose visible pieces share an outfit type (casual, business, beach, …) — a party shirt with work trousers is dropped. Pieces without a type fit everything.')}>
                  <input type="checkbox" checked={coherentOnly} disabled={busyQueue}
                    onChange={(e) => setCoherentOnly(e.target.checked)} />
                  <span>{t('Only matching combinations')}</span>
                </label>
                <label className="ga-check-row">
                  <input type="checkbox" checked={force} disabled={busyQueue}
                    onChange={(e) => setForce(e.target.checked)} />
                  <span>{t('Re-render cached')}</span>
                </label>
              </div>

              <div className="ga-outfit-batch-list">
                {slots.map((slot) => {
                  const pieces = options[slot] || []
                  const sel = picked[slot] || new Set<string>()
                  const only = sel.size <= 1
                  return (
                    <div key={slot}>
                      <div className="ga-outfit-batch-slot-head">
                        <span>{slot}</span>
                        <button type="button" className="ga-btn ga-btn-sm"
                          disabled={busyQueue}
                          onClick={() => setSlot(slot,
                            [EMPTY, ...pieces.map((p) => p.item_id)])}>
                          {t('All')}
                        </button>
                        <button type="button" className="ga-btn ga-btn-sm"
                          disabled={busyQueue}
                          title={t('Keep this slot empty in every combination.')}
                          onClick={() => setSlot(slot, [EMPTY])}>
                          {t('None')}
                        </button>
                      </div>
                      <div className="ga-outfit-batch-row">
                        <label className="ga-outfit-batch-opt">
                          <input type="checkbox" checked={sel.has(EMPTY)}
                            disabled={busyQueue || (only && sel.has(EMPTY))}
                            onChange={() => toggle(slot, EMPTY)} />
                          <span className="ga-hint">{t('(empty)')}</span>
                        </label>
                        {/* The "only" button sits NEXT to the label, not
                            inside it — inside, a click would activate the
                            label and toggle the checkbox as well. */}
                        {pieces.map((p) => (
                          <span key={p.item_id} className="ga-outfit-batch-opt">
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                              <input type="checkbox" checked={sel.has(p.item_id)}
                                disabled={busyQueue || (only && sel.has(p.item_id))}
                                onChange={() => toggle(slot, p.item_id)} />
                              <span className="ga-outfit-batch-name">{p.name}</span>
                            </label>
                            <button type="button" className="ga-btn ga-btn-sm"
                              disabled={busyQueue}
                              title={t('Use only this piece in this slot.')}
                              onClick={() => setSlot(slot, [p.item_id])}>
                              {t('only')}
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          )}

          {/* Cache section: what is lying in the two caches that no
              combination can reach any more (deleted pieces, signature-rule
              changes). Deliberately on demand — see verifyCache. */}
          <div className="ga-outfit-batch-summary">
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={cacheBusy}
              title={t('Check both render caches against this inventory: which reference renders and meshes belong to combinations that can no longer exist.')}
              onClick={() => { void verifyCache() }}>
              {cacheBusy ? t('Checking…') : t('Verify cache')}
            </button>
            {cacheError ? (
              <span className="ga-hint">{cacheError}</span>
            ) : cache ? (
              <>
                <span>{t('Refs')}: {cache.refs.total}
                  {cache.refs.stale ? ` (${cache.refs.stale} ${t('stale')})` : ''}</span>
                <span>{t('Meshes')}: {cache.meshes.total}
                  {cache.meshes.stale ? ` (${cache.meshes.stale} ${t('stale')})` : ''}</span>
                {cache.garments?.total ? (
                  <span>{t('Garments')}: {cache.garments.total}
                    {cache.garments.stale ? ` (${cache.garments.stale} ${t('stale')})` : ''}</span>
                ) : null}
                <span>{t('reclaim')} ~{fmtBytes(
                  cache.refs.stale_bytes + cache.meshes.stale_bytes + (cache.garments?.stale_bytes ?? 0))}</span>
              </>
            ) : (
              <span className="ga-hint">{t('Not checked yet.')}</span>
            )}
            {cache?.stale_signatures.length ? (
              armed ? (
                <>
                  <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                    disabled={cacheBusy} onClick={() => { void purgeCache() }}>
                    {t('Sure?')}
                  </button>
                  <button type="button" className="ga-btn ga-btn-sm"
                    onClick={() => setArmed(false)}>
                    {t('Cancel')}
                  </button>
                </>
              ) : (
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={cacheBusy} onClick={() => setArmed(true)}>
                  {t('Delete stale')} ({cache.stale_signatures.length})
                </button>
              )
            ) : null}
          </div>

          {queue.state === 'pending' ? (
            <div className="ga-form-hint">
              {t('Queued at low priority — it starts once the normal work is done.')}
            </div>
          ) : null}

          {status && (status.running || status.total) ? (
            <div className="ga-form-hint">
              {status.running ? (
                <>
                  {t('Rendering')} {status.done + 1}/{status.total}
                  {status.skipped ? ` · ${status.skipped} ${t('cached')}` : ''}
                  {status.current ? ` — ${status.current.name} (${
                    status.current.step === 'ref' ? t('reference render') : t('mesh')})` : ''}
                </>
              ) : (
                <>{t('Last run')}: {status.done}/{status.total}
                  {' · '}{status.skipped} {t('cached')}
                  {' · '}{status.failed} {t('failed')}
                </>
              )}
            </div>
          ) : null}

          {results.length ? (
            <div className="ga-form-hint">
              {t('Last')}: {results.slice(-3).reverse().map((r) => (
                r.ok ? r.name : `${r.name} — ${r.error}`)).join(' | ')}
            </div>
          ) : null}

          {busyQueue ? (
            <div className="ga-form-hint">
              {t('This runs in the background — you can close the dialog and come back later. It also survives a server restart and continues where it left off.')}
            </div>
          ) : null}
        </div>
        <div className="ga-modal-footer">
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
            {t('Close')}
          </button>
          {busyQueue ? (
            <button type="button" className="ga-btn ga-btn-sm"
              onClick={() => { void stop() }}>
              {t('Stop after current combination')}
            </button>
          ) : (
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy || !complete || !stats?.missing}
              onClick={() => { void start() }}>
              {t('Start')}{stats ? ` (${stats.missing.toLocaleString()})` : ''}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
