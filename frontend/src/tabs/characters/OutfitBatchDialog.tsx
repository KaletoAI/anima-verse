/**
 * OutfitBatchDialog — pre-warm the 3D chain (T-pose reference → mesh) for ALL
 * saved outfits of a character, without dressing them.
 *
 * The dialog is only a VIEW on the in-process job behind
 * /characters/{n}/outfit-batch: it may be closed at any time, the job keeps
 * running, and reopening shows the plan plus whatever progress there is. After
 * a server restart the job is gone but the plan simply reflects the caches —
 * starting again is idempotent, everything finished is skipped.
 *
 * Backend: GET /characters/{n}/outfit-batch, POST .../outfit-batch/start,
 * POST .../outfit-batch/stop.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

export interface OutfitBatchRow {
  outfit_id: string
  name: string
  signature: string | null
  has_ref: boolean
  has_model: boolean
  /** Non-empty = this outfit cannot be rendered (e.g. "no pieces"). */
  skip_reason: string
  /** Outfit id this one shares its combination with — rendered only once. */
  duplicate_of: string | null
}

export interface OutfitBatchResult {
  outfit_id: string
  name: string
  ok: boolean
  cached: boolean
  error: string
}

export interface OutfitBatchStatus {
  running: boolean
  stop_requested: boolean
  total: number
  done: number
  current: { outfit_id: string; name: string; step: 'ref' | 'mesh' } | null
  results: OutfitBatchResult[]
}

const POLL_MS = 3000

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
  const [plan, setPlan] = useState<OutfitBatchRow[]>([])
  const [status, setStatus] = useState<OutfitBatchStatus | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [force, setForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  // Which (character, open) the default selection was seeded for — later polls
  // must not overwrite what the admin ticked.
  const seededRef = useRef('')
  const runningRef = useRef(false)
  // Held in a ref so an unmemoized parent callback does not restart the poll.
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  const refresh = useCallback(async () => {
    if (!character) return
    try {
      const d = await apiGet<{ plan: OutfitBatchRow[]; status: OutfitBatchStatus }>(
        `/characters/${enc}/outfit-batch`)
      setPlan(d.plan || [])
      setStatus(d.status || null)
      // A run that just ended invalidates the 3D field's own status.
      if (runningRef.current && !d.status?.running) onDoneRef.current?.()
      runningRef.current = !!d.status?.running
    } catch {
      setPlan([])
      setStatus(null)
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

  // Default selection: everything that has no mesh yet and can be rendered.
  useEffect(() => {
    if (!open || !loaded) return
    const key = `${character}:${open}`
    if (seededRef.current === key) return
    seededRef.current = key
    setPicked(new Set(plan
      .filter((r) => !r.skip_reason && !r.duplicate_of && !r.has_model)
      .map((r) => r.outfit_id)))
  }, [open, loaded, plan, character])

  useEffect(() => {
    if (!open) seededRef.current = ''
  }, [open])

  const toggle = useCallback((outfitId: string) => {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(outfitId)) next.delete(outfitId)
      else next.add(outfitId)
      return next
    })
  }, [])

  const renderable = useMemo(
    () => plan.filter((r) => !r.skip_reason && !r.duplicate_of), [plan])

  const selectAll = useCallback((all: boolean) => {
    setPicked(all ? new Set(renderable.map((r) => r.outfit_id)) : new Set())
  }, [renderable])

  const start = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      const d = await apiPost<{ count: number }>(
        `/characters/${enc}/outfit-batch/start`,
        { outfit_ids: Array.from(picked), force })
      toast(t('Started') + ` — ${d.count}`)
      await refresh()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [busy, enc, force, picked, refresh, t, toast])

  const stop = useCallback(async () => {
    try {
      await apiPost(`/characters/${enc}/outfit-batch/stop`, {})
      await refresh()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, refresh, t, toast])

  if (!open) return null

  const running = !!status?.running
  const results = status?.results || []
  const byId = new Map(results.map((r) => [r.outfit_id, r]))

  const rowStatus = (r: OutfitBatchRow) => {
    if (r.skip_reason) return `⏭ ${r.skip_reason === 'no pieces' ? t('no pieces') : r.skip_reason}`
    if (r.duplicate_of) {
      const orig = plan.find((o) => o.outfit_id === r.duplicate_of)
      return `⏭ ${t('same combination as')} ${orig?.name || r.duplicate_of}`
    }
    if (r.has_model) return `✓ ${t('mesh')}`
    if (r.has_ref) return `🖼 ${t('reference only')}`
    return '—'
  }

  return createPortal(
    <div className="ga-modal-backdrop"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="ga-modal" role="dialog"
        aria-label={t('3D models for all outfits')}
        style={{ maxWidth: 720, width: 'min(720px, 94vw)' }}>
        <div className="ga-modal-header">
          <span>⚙ {t('3D models for all outfits')} — {character}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}
            aria-label={t('Close')}>×</button>
        </div>
        <div className="ga-modal-body">
          <div className="ga-hint">
            {t('Renders the T-pose reference and the mesh for each selected outfit, one after another — without changing what the character wears. Carried items are not part of these combinations.')}
          </div>

          {!loaded ? (
            <div className="ga-loading">{t('Loading…')}</div>
          ) : !plan.length ? (
            <div className="ga-hint">{t('This character has no saved outfits.')}</div>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={running} onClick={() => selectAll(true)}>
                  {t('Select all')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={running} onClick={() => selectAll(false)}>
                  {t('Select none')}
                </button>
                <label className="ga-check-row" style={{ marginLeft: 'auto' }}>
                  <input type="checkbox" checked={force} disabled={running}
                    onChange={(e) => setForce(e.target.checked)} />
                  <span>{t('Re-render existing')}</span>
                </label>
              </div>

              <div className="ga-outfit-batch-list">
                {plan.map((r) => {
                  const blocked = !!r.skip_reason || !!r.duplicate_of
                  const res = byId.get(r.outfit_id)
                  return (
                    <div key={r.outfit_id} className="ga-outfit-batch-row">
                      <input type="checkbox"
                        checked={picked.has(r.outfit_id)}
                        disabled={blocked || running}
                        onChange={() => toggle(r.outfit_id)} />
                      <span className="ga-outfit-batch-name">{r.name}</span>
                      <span className="ga-hint">{rowStatus(r)}</span>
                      {res ? (
                        <span className="ga-hint">
                          {res.ok ? (res.cached ? `· ${t('skipped')}` : `· ${t('done')}`) : `· ${res.error}`}
                        </span>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </>
          )}

          {status && (running || status.total) ? (
            <div className="ga-form-hint">
              {running ? (
                <>
                  {t('Rendering')} {status.done + 1}/{status.total}
                  {status.current ? ` — ${status.current.name} (${
                    status.current.step === 'ref' ? t('reference render') : t('mesh')})` : ''}
                  {status.stop_requested ? ` · ${t('stopping after this outfit')}` : ''}
                </>
              ) : (
                <>{t('Last run')}: {status.done}/{status.total}
                  {' · '}
                  {results.filter((r) => r.ok).length} {t('ok')}
                  {', '}
                  {results.filter((r) => !r.ok).length} {t('failed')}
                </>
              )}
            </div>
          ) : null}

          {running ? (
            <div className="ga-form-hint">
              {t('This runs in the background — you can close the dialog and come back later.')}
            </div>
          ) : null}
        </div>
        <div className="ga-modal-footer">
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
            {t('Close')}
          </button>
          {running ? (
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={!!status?.stop_requested} onClick={() => { void stop() }}>
              {status?.stop_requested ? t('Stopping…') : t('Stop after current')}
            </button>
          ) : (
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy || !picked.size} onClick={() => { void start() }}>
              {t('Start')} {picked.size ? `(${picked.size})` : ''}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
