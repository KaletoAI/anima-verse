/**
 * FurnishDialog — the "✨ Furnish" workflow of one room (plan-furnish-v2.md).
 *
 * The dialog is only a VIEW on the persisted job behind
 * /world/rooms/{id}/furnish: it may be closed and reopened at any time, the
 * job keeps running. `useFurnishJob` owns the single poll and the ghost list
 * (the pending placements the floor-plan editor renders as ghosts) so dialog
 * and canvas never poll twice — the editor holds the hook and passes it in.
 *
 *   no job        → current furnishing + "Suggest furnishing" / "Clear room"
 *                   / "Sync description with inventory" (E8)
 *   selecting     → spinner (the dialog may be closed)
 *   proposal_ready→ ONE editable need list + the surfaces row + "Place"
 *   placing       → spinner · review_ready → per-pass summary + Accept/Discard
 *   generating    → meshes n/m, the room already carries placeholder boxes
 *   error         → message + Retry / Reset; stalled → Continue
 *
 * PLACING COMES BEFORE GENERATING (decision E6): the ghosts are there within
 * minutes, the meshes arrive after Accept while the room is already usable.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { SurfaceKindSelect } from './SurfaceKindSelect'
import type { RoomPropPlacement, SurfaceKind } from './worldTypes'
import { newId, usePoseCatalog } from './placeTypes'
import { DescriptionSyncPanel } from './DescriptionSyncPanel'
import { FurnishNeedsList } from './FurnishNeedsList'
import { MOUNT_GROUPS, NEED_ID_PREFIX, propMount, type FurnishActResult,
  type FurnishJob, type FurnishLibProp, type FurnishNeed,
  type FurnishProposal, type FurnishStatus,
  type FurnishSurfaces } from './furnishTypes'

export type { FurnishJob, FurnishState, FurnishStatus } from './furnishTypes'

const POLL_OPEN_MS = 3000
const POLL_IDLE_MS = 15000

/** Words that make a piece a SEAT, a bed or a counter — something a character
 *  uses by standing/sitting/lying at it. Without a place marker such a prop is
 *  furniture nobody can use (plan-furnish-v2.md § 2b B18). */
const PLACE_WORDS = ['chair', 'sofa', 'bench', 'stool', 'bed', 'counter', 'bar']
/** …matched as WHOLE WORDS. A substring test warned about a "bedside table"
 *  (bed) and a "barrel" (bar) — pieces nobody sits on — which trains the admin
 *  to ignore the warning. */
const PLACE_WORD_RE = new RegExp(`\\b(${PLACE_WORDS.join('|')})\\b`)

/**
 * The single source of truth for one target's furnishing job. `open` = the
 * dialog is visible (fast poll); a closed dialog still polls slowly so the
 * ghost layer notices a job that finished in the background.
 *
 * `roomId` is the room's own id — EXCEPT for a location's yard (§ A13a),
 * whose id `__ground__` is reserved and therefore repeats in every location:
 * a yard job is addressed by the composite `__ground__@<locationId>`, which
 * the server splits again. Callers build that string; everything here just
 * passes it through.
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
        // EVERY GHOST GETS AN ID before it is drawn (decision E1): a pending
        // piece may stand ON another one, and a support can only be named
        // once it has a name. The server mints the same 8-char base32 shape
        // on save and keeps a client-sent id verbatim, so minting here costs
        // nothing and makes the relation editable before Accept.
        setGhosts((status.placements?.placed || [])
          .map((p) => (p.id ? p : { ...p, id: newId() })))
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

  // The RESPONSE BODY is handed back, not swallowed: `accept` answers with the
  // placements as they were written into the room (real prop ids), and the
  // editor needs exactly those for its draft.
  const act = useCallback(async (action: string,
                                 body?: unknown): Promise<FurnishActResult> => {
    if (!roomId) return {}
    setBusy(true)
    try {
      const res = await apiPost<FurnishActResult>(
        `/world/rooms/${encodeURIComponent(roomId)}/furnish/${action}`, body || {})
      await refresh()
      return res || {}
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
  /** Surface-texture kinds, loaded once by the editor — the same list its own
   *  floor/wall pickers offer (E9: what the LLM may propose is what the admin
   *  could have picked). */
  surfaceKinds: SurfaceKind[]
  /** Kinds the terrain catalog calls water: never offered as a room floor —
   *  the server strips such a pick at the write path (W1). */
  waterKinds: Set<string>
  /** Empties layout.props in the editor draft — Save stays with the admin. */
  onClearRoom: () => void
  /** Accept the CURRENT ghost positions (the editor owns the merge into the
   *  draft, so the dialog does not call the route itself). */
  onAccept: () => void | Promise<void>
  /** A description stored by the sync panel (E8) — the editor draft carries
   *  the room objects and would write the old text back on its next save. */
  onDescriptionApplied?: (description: string) => void
  onClose: () => void
}

export function FurnishDialog({ roomId, roomName, job, propInfo, placements,
  surfaceKinds, waterKinds, onClearRoom, onAccept, onDescriptionApplied,
  onClose }: FurnishDialogProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  // Place-type labels for the proposal's markers (a group key is stored).
  const poseCatalog = usePoseCatalog()
  const { status, busy, ghosts, act } = job
  const state = status?.state
  // Editable copy of the need list — seeded once per job revision.
  const [needs, setNeeds] = useState<FurnishNeed[]>([])
  const [surfaces, setSurfaces] = useState<FurnishSurfaces>({})
  const [applySurfaces, setApplySurfaces] = useState(true)
  const seededRef = useRef('')
  const [confirmClear, setConfirmClear] = useState(false)
  // Direct mode (skip LLM proposal + generation, user requirement
  // 2026-07-23): pick library props by hand, the job enters at placement.
  const [pickMode, setPickMode] = useState(false)
  // Library pre-filter for the LLM proposal (start view): excluded props /
  // categories / keywords are not offered as "available", so rooms stop
  // all picking THE one bed — the need list then asks for a fresh piece.
  const [filterOpen, setFilterOpen] = useState(false)
  const [exCats, setExCats] = useState<Record<string, boolean>>({})
  const [exProps, setExProps] = useState<Record<string, boolean>>({})
  const [exKeywords, setExKeywords] = useState('')
  const [libProps, setLibProps] = useState<FurnishLibProp[] | null>(null)
  const [pickCounts, setPickCounts] = useState<Record<string, number>>({})

  // THE LIBRARY IS NEEDED BY MORE THAN THE PICKER NOW: the match select of a
  // need offers it, and the review's marker warning reads `marker_count` off
  // it. One fetch per open dialog, refreshed whenever a new job state could
  // have created props (the job builds its own).
  const wantsLib = pickMode || filterOpen || state === 'proposal_ready'
    || state === 'review_ready'
  useEffect(() => {
    if (!wantsLib || libProps !== null) return
    let stale = false
    apiGet<{ props?: Array<{ id: string; name?: string; category?: string
      mount?: string; width_m?: number; depth_m?: number; height_m?: number
      has_model?: boolean; dims_estimated?: boolean
      marker_count?: number }> }>('/world/props')
      .then((d) => {
        if (stale) return
        setLibProps((d.props || []).map((p) => ({
          id: p.id, name: p.name || p.id, category: p.category,
          mount: p.mount, width_m: p.width_m, depth_m: p.depth_m,
          height_m: p.height_m, has_model: p.has_model,
          dims_estimated: p.dims_estimated,
          marker_count: p.marker_count })))
      })
      .catch(() => { if (!stale) setLibProps([]) })
    return () => { stale = true }
  }, [wantsLib, libProps])

  const run = useCallback(async (action: string, body?: unknown) => {
    try {
      await act(action, body)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [act, t, toast])

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
    setNeeds((status.proposal.needs || []).map((n) => ({ ...n })))
    setSurfaces({ ...(status.proposal.surfaces || {}) })
    setApplySurfaces(true)
  }, [state, status])

  // Aggregated "what stands in the room right now" (name × count).
  const current = new Map<string, number>()
  for (const p of placements) {
    const name = propInfo[p.prop_id]?.name || p.prop_id
    current.set(name, (current.get(name) || 0) + 1)
  }

  const confirmProposal = () => {
    if (!needs.length) {
      toast(t('Add at least one piece.'), 'error')
      return
    }
    const clean = needs
      .map((n) => ({ ...n,
        kind: (n.kind || '').trim(),
        // The server drops a need without a generation subject — a row the
        // admin only typed a kind into is meant, not a mistake.
        description: (n.description || '').trim() || (n.kind || '').trim() }))
      .filter((n) => n.kind)
    if (!clean.length) {
      toast(t('Every need has to say what kind of piece it is.'), 'error')
      return
    }
    const proposal: FurnishProposal = {
      needs: clean,
      surfaces: applySurfaces && (surfaces.floor || surfaces.wall)
        ? surfaces : null,
    }
    void run('confirm', { proposal })
  }

  /** The pass a piece failed in, as the group heading calls it — the server
   *  answers the mount token ("floor", "wall", "surface"). */
  const passLabel = (pass: string): string => {
    const group = MOUNT_GROUPS.find((g) => g.mount === pass)
    return group ? t(group.label) : pass
  }

  /** The kind a placeholder placement stands for — a `need:<key>` prop id
   *  names the need it was planned from, and only the proposal knows it. */
  const needKind = (propId: string): string => {
    const key = propId.slice(NEED_ID_PREFIX.length)
    const need = (status?.proposal?.needs || []).find((n) => n.key === key)
    return need?.kind || key
  }

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
          {t('The LLM writes what the room needs, matches the library against it and a solver places the result. Nothing is removed — furnishing is additive.')}
        </div>
        {/* THE DESCRIPTION IS WHAT THE WORLD READS (E8). After a furnishing
            run it and the inventory have drifted apart; this button closes
            that gap with a preview the admin confirms. */}
        <DescriptionSyncPanel roomId={roomId} onApplied={onDescriptionApplied} />
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
  } else if (state === 'proposal_ready') {
    const floorKinds = surfaceKinds.filter((s) => !waterKinds.has(s.kind))
    body = (
      <>
        <div className="ga-form-hint">
          {t('What the room needs. Each row is served by a library piece or built — the choice in the right-hand select decides. Nothing is generated before you accept the placement.')}
        </div>
        <FurnishNeedsList
          needs={needs}
          onChange={setNeeds}
          lib={libProps}
          dropped={status.proposal?.dropped}
          poseGroups={poseCatalog.groups}
          onLeave={onClose}
        />
        {/* THE BARE ROOM GETS ITS SKIN (E9). Proposed only for a room that
            names no kinds of its own; the accept writes the two slots. */}
        {status.proposal?.surfaces ? (
          <div className="ga-form" style={{ gap: 6, border: '1px solid var(--border, #30363d)',
            borderRadius: 8, padding: 8 }}>
            <label className="ga-check-row" style={{ display: 'flex', gap: 6 }}>
              <input type="checkbox" checked={applySurfaces}
                onChange={(e) => setApplySurfaces(e.target.checked)} />
              <span>{t('Apply these textures on accept')}</span>
            </label>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <SurfaceKindSelect label="Floor" value={surfaces.floor || ''}
                kinds={floorKinds}
                emptyLabel="— none —"
                title={t('Floor texture of this room.')}
                onChange={(kind) => setSurfaces((s) => ({ ...s, floor: kind }))} />
              <SurfaceKindSelect label="Wall" value={surfaces.wall || ''}
                kinds={surfaceKinds}
                emptyLabel="— none —"
                title={t('Wall texture of this room.')}
                onChange={(kind) => setSurfaces((s) => ({ ...s, wall: kind }))} />
            </div>
          </div>
        ) : null}
        <div className="ga-furnish-actions">
          <button className="ga-btn ga-btn-sm" disabled={busy}
            onClick={() => { void run('reset') }}>
            {t('Reset')}
          </button>
          <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy}
            onClick={confirmProposal}>
            {t('Place')}
          </button>
        </div>
      </>
    )
  } else if (state === 'placing') {
    body = (
      <>
        <div className="ga-loading">{t('Planning the placement…')}</div>
        <div className="ga-form-hint">
          {t('The LLM arranges the pieces relationally and a solver turns that into geometry. Nothing is generated yet — this runs in the background and the dialog may be closed.')}
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
    const counts = status.phase_counts || {}
    const byId = new Map((libProps || []).map((p) => [p.id, p]))
    // B18: a seat or a lying surface WITHOUT a place marker is furniture
    // nobody can use. One warning per prop, not per copy.
    const seen = new Set<string>()
    const markerWarnings: Array<{ id: string; name: string }> = []
    for (const g of ghosts) {
      const prop = byId.get(g.prop_id)
      if (!prop || seen.has(g.prop_id)) continue
      seen.add(g.prop_id)
      if (propMount(prop) !== 'floor' || (prop.marker_count || 0) > 0) continue
      const hay = `${prop.category || ''} ${prop.name || ''}`.toLowerCase()
      if (PLACE_WORD_RE.test(hay)) {
        markerWarnings.push({ id: prop.id, name: prop.name })
      }
    }
    // One row per PIECE that has yet to be built, not per copy of it — six
    // chairs of one need are one thing being made.
    const placeholders = Array.from(new Set(ghosts
      .map((g) => g.prop_id)
      .filter((id) => id.startsWith(NEED_ID_PREFIX))))
    body = (
      <>
        <div className="ga-plan-panel-title">
          {t('{done} of {total} placed')
            .replace('{done}', String(ghosts.length))
            .replace('{total}', String(ghosts.length + unplaced.length))}
        </div>
        <div className="ga-hint">
          {MOUNT_GROUPS.map(({ mount, label }) => {
            const c = counts[mount]
            if (!c || (!c.placed && !c.unplaced)) return null
            return `${t(label)} ${c.placed}/${c.placed + c.unplaced}`
          }).filter(Boolean).join(' · ')}
        </div>
        {/* What did NOT fit, grouped by the pass it failed in — the reason
            names one concrete alternative (repair rule, constraint 5). */}
        {unplaced.length ? (
          <>
            {[...MOUNT_GROUPS.map((g) => g.mount as string), ''].map((pass) => {
              const rows = unplaced.filter(
                (u) => (u.pass || '') === pass
                  // A pass this client does not know still has to be shown,
                  // and it belongs nowhere else than the trailing group.
                  || (pass === '' && !MOUNT_GROUPS.some(
                    (g) => g.mount === u.pass)))
              if (!rows.length) return null
              return (
                <div key={pass || 'other'}>
                  <span className="ga-hint">
                    {pass ? passLabel(pass) : t('Not placed')}
                  </span>
                  <ul className="ga-furnish-list">
                    {rows.map((u, i) => (
                      <li key={i}>{u.name} — {u.reason}</li>
                    ))}
                  </ul>
                </div>
              )
            })}
          </>
        ) : null}
        {placeholders.length ? (
          <ul className="ga-furnish-list">
            {placeholders.map((propId) => (
              <li key={propId}>
                {t('{kind} (new — built after accept)')
                  .replace('{kind}', needKind(propId))}
              </li>
            ))}
          </ul>
        ) : null}
        {markerWarnings.length ? (
          <div className="ga-furnish-banner" style={{ flexDirection: 'column',
            alignItems: 'flex-start' }}>
            {markerWarnings.map((w) => (
              <span key={w.id}>
                ⚠ {t('{name}: no place marker — characters cannot use it.')
                  .replace('{name}', w.name)}{' '}
                <a href="#/props" onClick={() => onClose()}>{t('Props tab')}</a>
              </span>
            ))}
          </div>
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
  } else if (state === 'generating') {
    const done = status.progress?.done || 0
    const total = status.progress?.total || 0
    body = (
      <>
        <div className="ga-loading">
          {t('Building meshes {done}/{total} — the room already shows placeholder boxes; the job closes itself when done.')
            .replace('{done}', String(done)).replace('{total}', String(total))}
        </div>
        <div className="ga-form-hint">
          {t('Every new piece runs the normal image → mesh chain; this takes minutes and can be watched in the queue panel. The dialog may be closed.')}
        </div>
        <div className="ga-furnish-actions">
          {status.stalled ? (
            <>
              <span className="ga-hint">{t('The job is not running — the server was restarted.')}</span>
              <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy}
                onClick={() => { void run('continue') }}>
                {t('Continue')}
              </button>
            </>
          ) : null}
          <button className="ga-btn ga-btn-sm" disabled
            title={t('meshes are being generated')}>
            {t('Discard')}
          </button>
        </div>
      </>
    )
  } else if (state === 'error') {
    body = (
      <>
        <div className="ga-furnish-error">{status.error || t('Unknown error')}</div>
        <div className="ga-form-hint">
          {t('The job kept its state — Retry re-enters the failed step, Reset throws the whole run away.')}
        </div>
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
