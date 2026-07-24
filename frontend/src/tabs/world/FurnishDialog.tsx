/**
 * FurnishDialog — the "✨ Furnish" workflow of one room (plan-room-furnish.md).
 *
 * The dialog is only a VIEW on the persisted job behind
 * /world/rooms/{id}/furnish: it may be closed and reopened at any time, the
 * job keeps running. `useFurnishJob` owns the single poll and the ghost list
 * (the pending placements the floor-plan editor renders as ghosts) so dialog
 * and canvas never poll twice — the editor holds the hook and passes it in.
 *
 *   no job        → current furnishing + "Suggest furnishing" / "Clear room"
 *   selecting     → spinner (the dialog may be closed)
 *   proposal_ready→ two editable lists + "Generate & place" / "Reset"
 *   generating    → n/m progress · placing → spinner
 *   review_ready  → placed/unplaced summary + Accept / Discard
 *   error         → message + Retry / Reset; stalled → Continue
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { RoomPropPlacement } from './worldTypes'

export type FurnishState = 'selecting' | 'proposal_ready' | 'generating'
  | 'placing' | 'review_ready' | 'error'

export interface FurnishPick { prop_id: string; count: number }

export interface FurnishNewPiece {
  name: string
  description: string
  category?: string
  width_m: number
  depth_m: number
  height_m: number
  marker?: { animation: string; at: [number, number, number] } | null
  count: number
  prop_id?: string | null
}

export interface FurnishProposal {
  existing: FurnishPick[]
  new: FurnishNewPiece[]
}

export interface FurnishStatus {
  room_id: string
  location_id: string
  state: FurnishState
  proposal?: FurnishProposal | null
  placements?: { placed: RoomPropPlacement[]
    unplaced: Array<{ name: string; reason: string }> } | null
  error?: string
  progress?: { done: number; total: number }
  running?: boolean
  stalled?: boolean
  updated_at?: string
}

export interface FurnishJob {
  status: FurnishStatus | null
  busy: boolean
  /** Pending placements while the job waits for review — FE state only, the
   *  ghost layer edits them and Accept sends them back. */
  ghosts: RoomPropPlacement[]
  setGhosts: (next: RoomPropPlacement[]) => void
  refresh: () => Promise<void>
  act: (action: string, body?: unknown) => Promise<void>
}

const POLL_OPEN_MS = 3000
const POLL_IDLE_MS = 15000

/**
 * The single source of truth for one room's furnishing job. `open` = the
 * dialog is visible (fast poll); a closed dialog still polls slowly so the
 * ghost layer notices a job that finished in the background.
 */
export function useFurnishJob(roomId: string, open: boolean): FurnishJob {
  const [status, setStatus] = useState<FurnishStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [ghosts, setGhosts] = useState<RoomPropPlacement[]>([])
  // Which (room, job revision) the ghosts were seeded from — a fresh review
  // seeds them, later polls must not overwrite the admin's adjustments.
  const seededRef = useRef('')

  const refresh = useCallback(async () => {
    if (!roomId) {
      setStatus(null)
      return
    }
    try {
      const data = await apiGet<FurnishStatus>(
        `/world/rooms/${encodeURIComponent(roomId)}/furnish`)
      setStatus(data)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setStatus(null)
    }
  }, [roomId])

  // Seed / clear the ghost layer from the job state.
  useEffect(() => {
    if (status?.state === 'review_ready') {
      const key = `${status.room_id}:${status.updated_at || ''}`
      if (seededRef.current !== key) {
        seededRef.current = key
        setGhosts(status.placements?.placed || [])
      }
      return
    }
    seededRef.current = ''
    setGhosts((prev) => (prev.length ? [] : prev))
  }, [status])

  useEffect(() => {
    setStatus(null)
    seededRef.current = ''
    setGhosts([])
    void refresh()
  }, [roomId, refresh])

  useEffect(() => {
    if (!roomId) return
    const id = window.setInterval(() => { void refresh() },
      open ? POLL_OPEN_MS : POLL_IDLE_MS)
    return () => window.clearInterval(id)
  }, [roomId, open, refresh])

  const act = useCallback(async (action: string, body?: unknown) => {
    if (!roomId) return
    setBusy(true)
    try {
      await apiPost(
        `/world/rooms/${encodeURIComponent(roomId)}/furnish/${action}`, body || {})
      await refresh()
    } finally {
      setBusy(false)
    }
  }, [roomId, refresh])

  return { status, busy, ghosts, setGhosts, refresh, act }
}

interface FurnishDialogProps {
  roomId: string
  roomName: string
  job: FurnishJob
  /** Prop library records (id → name + real dims) — names everywhere,
   *  dims as a hint on the library picks (they carry no editable fields,
   *  which otherwise makes them look broken next to the new pieces). */
  propInfo: Record<string, { name: string
    width_m?: number; depth_m?: number; height_m?: number }>
  /** The room's CURRENT placements (editor draft). */
  placements: RoomPropPlacement[]
  /** Empties layout.props in the editor draft — Save stays with the admin. */
  onClearRoom: () => void
  /** Accept the CURRENT ghost positions (the editor owns the merge into the
   *  draft, so the dialog does not call the route itself). */
  onAccept: () => void | Promise<void>
  onClose: () => void
}

export function FurnishDialog({ roomId, roomName, job, propInfo, placements,
  onClearRoom, onAccept, onClose }: FurnishDialogProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const { status, busy, ghosts, act } = job
  const state = status?.state
  // Editable copy of the proposal — seeded once per job revision.
  const [draft, setDraft] = useState<FurnishProposal | null>(null)
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const seededRef = useRef('')
  const [confirmClear, setConfirmClear] = useState(false)
  // Direct mode (skip LLM proposal + generation, user requirement
  // 2026-07-23): pick library props by hand, the job enters at placement.
  const [pickMode, setPickMode] = useState(false)
  // Library pre-filter for the LLM proposal (start view): excluded props /
  // categories / keywords are not offered as "available", so rooms stop
  // all picking THE one bed — furnish_new proposes a fresh piece instead.
  const [filterOpen, setFilterOpen] = useState(false)
  const [exCats, setExCats] = useState<Record<string, boolean>>({})
  const [exProps, setExProps] = useState<Record<string, boolean>>({})
  const [exKeywords, setExKeywords] = useState('')
  const [libProps, setLibProps] = useState<Array<{ id: string; name: string
    category?: string; width_m?: number; depth_m?: number; height_m?: number
    has_model?: boolean }> | null>(null)
  const [pickCounts, setPickCounts] = useState<Record<string, number>>({})

  useEffect(() => {
    if ((!pickMode && !filterOpen) || libProps !== null) return
    let stale = false
    apiGet<{ props?: Array<{ id: string; name?: string; category?: string
      width_m?: number; depth_m?: number; height_m?: number
      has_model?: boolean }> }>('/world/props')
      .then((d) => {
        if (stale) return
        setLibProps((d.props || []).map((p) => ({
          id: p.id, name: p.name || p.id, category: p.category,
          width_m: p.width_m, depth_m: p.depth_m, height_m: p.height_m,
          has_model: p.has_model })))
      })
      .catch(() => { if (!stale) setLibProps([]) })
    return () => { stale = true }
  }, [pickMode, filterOpen, libProps])

  const startDirect = () => {
    const existing = Object.entries(pickCounts)
      .filter(([, c]) => c > 0)
      .map(([prop_id, count]) => ({ prop_id, count }))
    if (!existing.length) return
    setPickMode(false)
    void run('direct', { proposal: { existing } })
  }

  useEffect(() => {
    if (state !== 'proposal_ready' || !status?.proposal) {
      seededRef.current = ''
      return
    }
    const key = `${status.room_id}:${status.updated_at || ''}`
    if (seededRef.current === key) return
    seededRef.current = key
    setDraft({
      existing: status.proposal.existing.map((e) => ({ ...e })),
      new: status.proposal.new.map((n) => ({ ...n })),
    })
    const on: Record<string, boolean> = {}
    status.proposal.existing.forEach((e) => { on[`e:${e.prop_id}`] = true })
    status.proposal.new.forEach((_, i) => { on[`n:${i}`] = true })
    setPicked(on)
  }, [state, status])

  const run = useCallback(async (action: string, body?: unknown) => {
    try {
      await act(action, body)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [act, t, toast])

  // Aggregated "what stands in the room right now" (name × count).
  const current = new Map<string, number>()
  for (const p of placements) {
    const name = propInfo[p.prop_id]?.name || p.prop_id
    current.set(name, (current.get(name) || 0) + 1)
  }

  const setNew = (index: number, patch: Partial<FurnishNewPiece>) => {
    setDraft((prev) => prev && ({
      ...prev,
      new: prev.new.map((n, i) => (i === index ? { ...n, ...patch } : n)),
    }))
  }

  const confirmProposal = () => {
    if (!draft) return
    const proposal: FurnishProposal = {
      existing: draft.existing.filter((e) => picked[`e:${e.prop_id}`]),
      new: draft.new.filter((_, i) => picked[`n:${i}`]),
    }
    if (!proposal.existing.length && !proposal.new.length) {
      toast(t('Pick at least one piece.'), 'error')
      return
    }
    void run('confirm', { proposal })
  }

  const numField = (label: string, value: number,
    onValue: (v: number) => void) => (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
      title={label}>
      <span className="ga-hint">{label}</span>
      <input className="ga-input" type="number" step={0.05} min={0.05} max={5}
        style={{ width: 74 }}
        value={value} onChange={(e) => onValue(Number(e.target.value))} />
    </label>
  )

  let body: ReactNode
  if (!status && pickMode) {
    const total = Object.values(pickCounts).reduce((a, c) => a + (c > 0 ? c : 0), 0)
    body = (
      <>
        <div className="ga-plan-panel-title">{t('Place from library')}</div>
        <div className="ga-form-hint">
          {t('Pick the pieces by hand — no LLM proposal, nothing is generated. The solver places them automatically; you review the ghosts as usual.')}
        </div>
        {libProps === null ? (
          <div className="ga-loading">{t('Loading…')}</div>
        ) : libProps.length ? (
          <div style={{ maxHeight: 380, overflowY: 'auto' }}>
            {libProps.map((p) => (
              <div key={p.id} className="ga-furnish-row">
                <span style={{ flex: 1 }}>
                  {p.name}
                  <span className="ga-hint" style={{ marginLeft: 8 }}>
                    {p.width_m}×{p.depth_m}×{p.height_m} m
                    {p.has_model ? '' : ` · ${t('no model yet — placeholder')}`}
                  </span>
                </span>
                <input className="ga-input" type="number" min={0} max={12}
                  style={{ width: 56 }}
                  value={pickCounts[p.id] || 0}
                  onChange={(ev) => setPickCounts((prev) => ({
                    ...prev,
                    [p.id]: Math.max(0, Math.min(12, Number(ev.target.value) || 0)),
                  }))} />
              </div>
            ))}
          </div>
        ) : (
          <div className="ga-form-hint">{t('The library is empty.')}</div>
        )}
        <div className="ga-furnish-actions">
          <button className="ga-btn ga-btn-sm" onClick={() => setPickMode(false)}>
            {t('Back')}
          </button>
          <button className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={busy || total === 0} onClick={startDirect}>
            {t('Place {n} pieces').replace('{n}', String(total))}
          </button>
        </div>
      </>
    )
  } else if (!status) {
    body = (
      <>
        <div className="ga-plan-panel-title">{t('Currently in the room')}</div>
        {current.size ? (
          <ul className="ga-furnish-list">
            {Array.from(current, ([name, count]) => (
              <li key={name}>{count}× {name}</li>
            ))}
          </ul>
        ) : (
          <div className="ga-form-hint">{t('The room is empty.')}</div>
        )}
        <div className="ga-form-hint">
          {t('The LLM picks library props and proposes the missing pieces; a solver places them. Nothing is removed — furnishing is additive.')}
        </div>
        {/* Library pre-filter: what is EXCLUDED here is not offered to the
            LLM as available — the room gets fresh proposals instead of the
            same library piece every time. */}
        <button type="button" className="ga-btn ga-btn-sm"
          style={{ alignSelf: 'flex-start' }}
          onClick={() => setFilterOpen((v) => !v)}>
          🔎 {t('Library filter')}
          {(() => {
            const n = Object.values(exCats).filter(Boolean).length
              + Object.values(exProps).filter(Boolean).length
              + exKeywords.split(',').map((k) => k.trim()).filter(Boolean).length
            return n ? ` (${n})` : ''
          })()}
        </button>
        {filterOpen ? (
          <div className="ga-form" style={{ gap: 6, border: '1px solid var(--border, #30363d)', borderRadius: 8, padding: 8 }}>
            <div className="ga-form-hint">
              {t('Excluded categories, keywords and props are NOT offered to the LLM as available — it proposes fresh pieces instead (they are generated and join the library). The filter applies to this run only.')}
            </div>
            {libProps === null ? (
              <div className="ga-loading">{t('Loading…')}</div>
            ) : (
              <>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {Array.from(new Set(libProps.map((p) => (p.category || '').trim()).filter(Boolean)))
                    .sort()
                    .map((cat) => (
                      <button key={cat} type="button"
                        className={`ga-btn ga-btn-sm${exCats[cat] ? ' ga-btn-danger' : ''}`}
                        title={t('Exclude this category from the LLM catalog.')}
                        onClick={() => setExCats((p) => ({ ...p, [cat]: !p[cat] }))}>
                        {exCats[cat] ? '🚫 ' : ''}{cat}
                      </button>
                    ))}
                </div>
                <input className="ga-input" value={exKeywords}
                  placeholder={t('Exclude keywords (comma-separated, matches name + tags)')}
                  onChange={(e) => setExKeywords(e.target.value)} />
                <div style={{ maxHeight: 160, overflowY: 'auto' }}>
                  {libProps.map((p) => (
                    <label key={p.id} className="ga-check-row" style={{ display: 'flex', gap: 6 }}>
                      <input type="checkbox" checked={!!exProps[p.id]}
                        onChange={(e) => setExProps((prev) => ({ ...prev, [p.id]: e.target.checked }))} />
                      <span style={{ opacity: exProps[p.id] ? 0.5 : 1 }}>
                        {p.name}
                        <span className="ga-hint" style={{ marginLeft: 6 }}>{p.category || ''}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : null}
        <div className="ga-furnish-actions">
          {confirmClear ? (
            <>
              <span className="ga-hint">
                {t('Remove every placement from this room? This only changes the editor draft — nothing is stored until you save the location.')}
              </span>
              <button className="ga-btn ga-btn-sm" onClick={() => setConfirmClear(false)}>
                {t('Cancel')}
              </button>
              <button className="ga-btn ga-btn-sm ga-btn-danger"
                onClick={() => { onClearRoom(); setConfirmClear(false) }}>
                {t('Yes, clear')}
              </button>
            </>
          ) : (
            <>
              <button className="ga-btn ga-btn-sm" disabled={!placements.length}
                onClick={() => setConfirmClear(true)}
                title={t('Empties the room in the editor draft — your Save decides.')}>
                {t('Clear room')}
              </button>
              <button className="ga-btn ga-btn-sm" disabled={busy}
                onClick={() => setPickMode(true)}
                title={t('Skip the LLM proposal and the generation — pick library props by hand, only the placement runs.')}>
                📦 {t('Place from library')}
              </button>
              <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy}
                onClick={() => {
                  const categories = Object.keys(exCats).filter((c) => exCats[c])
                  const prop_ids = Object.keys(exProps).filter((i) => exProps[i])
                  const keywords = exKeywords.split(',')
                    .map((k) => k.trim()).filter(Boolean)
                  const exclude = categories.length || prop_ids.length || keywords.length
                    ? { categories, prop_ids, keywords } : undefined
                  void run('start', exclude ? { exclude } : undefined)
                }}>
                ✨ {t('Suggest furnishing')}
              </button>
            </>
          )}
        </div>
      </>
    )
  } else if (state === 'selecting') {
    body = (
      <>
        <div className="ga-loading">{t('Asking the LLM…')}</div>
        <div className="ga-form-hint">
          {t('This runs in the background — you can close the dialog and come back later.')}
        </div>
      </>
    )
  } else if (state === 'proposal_ready' && draft) {
    body = (
      <>
        <div className="ga-plan-panel-title">{t('From the library')}</div>
        {draft.existing.length ? draft.existing.map((e, i) => (
          <div key={e.prop_id} className="ga-furnish-row">
            <input type="checkbox" checked={!!picked[`e:${e.prop_id}`]}
              onChange={(ev) => setPicked((p) => ({ ...p, [`e:${e.prop_id}`]: ev.target.checked }))} />
            <span style={{ flex: 1 }}>
              {propInfo[e.prop_id]?.name || e.prop_id}
              {propInfo[e.prop_id]?.width_m ? (
                <span className="ga-hint" style={{ marginLeft: 8 }}>
                  {propInfo[e.prop_id]!.width_m}×{propInfo[e.prop_id]!.depth_m}×{propInfo[e.prop_id]!.height_m} m
                  {' · '}{t('from the library — placed as-is')}
                </span>
              ) : null}
            </span>
            <input className="ga-input" type="number" min={1} max={12} value={e.count}
              style={{ width: 56 }}
              onChange={(ev) => setDraft((prev) => prev && ({
                ...prev,
                existing: prev.existing.map((x, j) => (j === i
                  ? { ...x, count: Math.max(1, Math.min(12, Number(ev.target.value) || 1)) }
                  : x)),
              }))} />
          </div>
        )) : <div className="ga-form-hint">{t('Nothing suitable in the library.')}</div>}

        <div className="ga-plan-panel-title">{t('New pieces (will be generated)')}</div>
        {draft.new.length ? draft.new.map((n, i) => (
          <div key={i} className="ga-furnish-new">
            {/* Row 1: everything scalar — name, count, the three dims. The
                generation subject gets the full second row (it is the field
                that actually needs width). */}
            <div className="ga-furnish-row" style={{ flexWrap: 'wrap' }}>
              <input type="checkbox" checked={!!picked[`n:${i}`]}
                onChange={(ev) => setPicked((p) => ({ ...p, [`n:${i}`]: ev.target.checked }))} />
              <input className="ga-input" style={{ flex: '2 1 160px' }} value={n.name}
                title={t('Name')}
                onChange={(ev) => setNew(i, { name: ev.target.value })} />
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                title={t('Count')}>
                <span className="ga-hint">×</span>
                <input className="ga-input" type="number" min={1} max={12} value={n.count}
                  style={{ width: 56 }}
                  onChange={(ev) => setNew(i, { count: Math.max(1, Math.min(12, Number(ev.target.value) || 1)) })} />
              </label>
              {numField(t('W (m)'), n.width_m, (v) => setNew(i, { width_m: v }))}
              {numField(t('D (m)'), n.depth_m, (v) => setNew(i, { depth_m: v }))}
              {numField(t('H (m)'), n.height_m, (v) => setNew(i, { height_m: v }))}
            </div>
            <textarea className="ga-input" rows={3} style={{ width: '100%' }}
              value={n.description}
              title={t('The generation subject — describe the isolated object, never a scene.')}
              onChange={(ev) => setNew(i, { description: ev.target.value })} />
            <span className="ga-hint">
              {n.marker
                ? t('Marker: {kind} (adjust it by hand on the prop later)')
                  .replace('{kind}', n.marker.animation)
                : t('No marker')}
              {n.prop_id ? ` · ${t('already generated')}` : ''}
            </span>
          </div>
        )) : <div className="ga-form-hint">{t('No new pieces proposed.')}</div>}

        <div className="ga-furnish-actions">
          <button className="ga-btn ga-btn-sm" disabled={busy}
            onClick={() => { void run('reset') }}>
            {t('Reset')}
          </button>
          <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy}
            onClick={confirmProposal}>
            {t('Generate & place')}
          </button>
        </div>
      </>
    )
  } else if (state === 'generating' || state === 'placing') {
    const done = status.progress?.done || 0
    const total = status.progress?.total || 0
    body = (
      <>
        <div className="ga-loading">
          {state === 'generating'
            ? t('Generating pieces {done}/{total}…')
              .replace('{done}', String(done)).replace('{total}', String(total))
            : t('Placing the furniture…')}
        </div>
        <div className="ga-form-hint">
          {t('Every new piece runs the normal image → mesh chain; this takes minutes. The dialog may be closed.')}
        </div>
        {status.stalled ? (
          <div className="ga-furnish-actions">
            <span className="ga-hint">{t('The job is not running — the server was restarted.')}</span>
            <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy}
              onClick={() => { void run('continue') }}>
              {t('Continue')}
            </button>
          </div>
        ) : null}
      </>
    )
  } else if (state === 'review_ready') {
    const unplaced = status.placements?.unplaced || []
    const total = ghosts.length + unplaced.length
    body = (
      <>
        <div className="ga-plan-panel-title">
          {t('{done} of {total} placed').replace('{done}', String(ghosts.length))
            .replace('{total}', String(total))}
        </div>
        {unplaced.length ? (
          <ul className="ga-furnish-list">
            {unplaced.map((u, i) => (
              <li key={i}>{propInfo[u.name]?.name || u.name} — {u.reason}</li>
            ))}
          </ul>
        ) : null}
        <div className="ga-form-hint">
          {t('The proposal is drawn as amber ghosts on the floor plan — drag or delete them there before accepting.')}
        </div>
        <div className="ga-furnish-actions">
          <button className="ga-btn ga-btn-sm" disabled={busy}
            onClick={() => { void run('discard') }}>
            {t('Discard')}
          </button>
          <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy || !ghosts.length}
            onClick={() => { void onAccept() }}>
            {t('Accept {n} pieces').replace('{n}', String(ghosts.length))}
          </button>
        </div>
      </>
    )
  } else if (state === 'error') {
    body = (
      <>
        <div className="ga-furnish-error">{status.error || t('Unknown error')}</div>
        <div className="ga-furnish-actions">
          <button className="ga-btn ga-btn-sm" disabled={busy}
            onClick={() => { void run('reset') }}>
            {t('Reset')}
          </button>
          <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy}
            onClick={() => { void run('retry') }}>
            {t('Retry')}
          </button>
        </div>
      </>
    )
  } else {
    body = <div className="ga-loading">{t('Loading…')}</div>
  }

  return createPortal(
    <div className="ga-modal-backdrop"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="ga-modal" role="dialog"
        aria-label={t('Furnish room')}
        style={{ maxWidth: 1080, width: 'min(1080px, 94vw)' }}>
        <div className="ga-modal-header">
          <span>✨ {t('Furnish')} — {roomName || roomId}</span>
          <button className="ga-modal-close" onClick={onClose} aria-label={t('Close')}>×</button>
        </div>
        <div className="ga-modal-body ga-furnish-body">{body}</div>
      </div>
    </div>,
    document.body,
  )
}
