/**
 * PlayerApp — the in-world player surface (plan-room-conversation Phase 2).
 * A SEPARATE page at /play, distinct from the game-admin.
 *
 * Layout: react-grid-layout — frei verschieb-/größenveränderbare Panels
 * ("Fenster"), Optik komplett unsere (game-tauglich). Erste Panels: Szene
 * (wahrgenommene Raum-Szene + Composer) und ein Platzhalter (z.B. Karte).
 * Layout-Persistenz ins User-Profil + weitere Panels folgen als nächste Schritte.
 */
import { cloneElement, useCallback, useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import GridLayout, { type Layout } from 'react-grid-layout'
import { useI18n } from '../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../lib/api'
import { SceneView, type SceneLine } from '../components/SceneView'
import { ScenesRecap } from './ScenesRecap'
import { MovePad } from './MovePad'
import { EnvironmentPanel } from './EnvironmentPanel'
import { MapPanel } from './MapPanel'
import { TaskPanel } from './TaskPanel'
import { LayoutsPanel } from './LayoutsPanel'
import { SelfPanel } from './SelfPanel'
import { OthersPanel } from './OthersPanel'
import { BelongingsPanel } from './BelongingsPanel'
import { JournalPanel } from './JournalPanel'
import { GalleryPanel } from './GalleryPanel'
import { InstagramPanel } from './InstagramPanel'
import { NoticeBanner } from './NoticeBanner'
import { useQueue } from './useQueue'

// Quadratische, browser-unabhängige Zellen: feste Zellgröße in px. Die
// Spaltenzahl wird aus der gemessenen Breite berechnet, sodass die Spaltenbreite
// == rowHeight ist (CELL). Breiterer Browser = MEHR Spalten, nicht breitere.
const CELL = 14
const MARGIN = 4

const DEFAULT_LAYOUT: Layout[] = [
  { i: 'scene', x: 0, y: 0, w: 24, h: 26, minW: 8, minH: 8 },
  { i: 'env', x: 24, y: 0, w: 17, h: 15, minW: 6, minH: 5 },
  { i: 'map', x: 24, y: 15, w: 17, h: 12, minW: 6, minH: 5 },
  { i: 'worldmap', x: 0, y: 26, w: 24, h: 12, minW: 6, minH: 5 },
  { i: 'self', x: 41, y: 0, w: 13, h: 20, minW: 6, minH: 8 },
  { i: 'others', x: 41, y: 20, w: 13, h: 18, minW: 8, minH: 8 },
  { i: 'belongings', x: 0, y: 38, w: 24, h: 16, minW: 10, minH: 8 },
  { i: 'journal', x: 24, y: 37, w: 17, h: 14, minW: 8, minH: 6 },
  { i: 'gallery', x: 0, y: 54, w: 20, h: 14, minW: 8, minH: 6 },
  { i: 'instagram', x: 20, y: 54, w: 21, h: 18, minW: 10, minH: 8 },
  { i: 'tasks', x: 24, y: 27, w: 17, h: 10, minW: 6, minH: 4 },
  { i: 'layouts', x: 24, y: 37, w: 17, h: 14, minW: 6, minH: 6 },
]

// Default-Box je Panel-id — Quelle der Wahrheit fuer Mindest-/Anfangsgroesse.
const DEFAULT_BY_ID: Record<string, Layout> = Object.fromEntries(
  DEFAULT_LAYOUT.map((d) => [d.i, d]))

// Launcher-Labels + Art. kind:'dialog' → zentriertes Overlay (kommt/geht)
// statt Grid-Kachel; generell für „Werkzeug"-Fenster nutzbar.
const PANEL_META: { id: string; label: string; kind?: 'grid' | 'dialog' }[] = [
  { id: 'scene', label: 'Chat' },
  { id: 'env', label: 'Surroundings' },
  { id: 'map', label: 'Move' },
  { id: 'worldmap', label: 'Map' },
  { id: 'self', label: 'Self' },
  { id: 'others', label: 'Others' },
  { id: 'belongings', label: 'Inventory' },
  { id: 'journal', label: 'Journal' },
  { id: 'gallery', label: 'Gallery' },
  { id: 'instagram', label: 'Instagram' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'layouts', label: 'Layouts', kind: 'dialog' },
]
const ALL_PANELS = PANEL_META.map((p) => p.id)
const GRID_PANELS = PANEL_META.filter((p) => p.kind !== 'dialog').map((p) => p.id)
const DIALOG_PANELS = PANEL_META.filter((p) => p.kind === 'dialog').map((p) => p.id)

interface RoomInfo { id: string; name: string; is_entry: boolean }
interface Neighbor { id: string; name: string }
type Dir = 'north' | 'south' | 'east' | 'west'

interface SceneData {
  avatar: string
  location_id: string
  location_name: string
  room_id: string
  room_name: string
  present: string[]
  present_detail: Array<{ name: string; avatar_url: string; expr_version?: string }>
  scene: Array<{ ts: string; content: string; kind: string; meta?: Record<string, unknown> }>
  follow_suggestions?: Array<{ character: string; room_id: string; room_name: string }>
  rooms: RoomInfo[]
  neighbors: Partial<Record<Dir, Neighbor | null>>
  at_entry_room: boolean
  entry_room_name: string
  avatar_expr_version?: string
  bg_version?: string
  bg_id?: string
}

export function PlayerApp() {
  const { t } = useI18n()
  const [data, setData] = useState<SceneData | null>(null)
  const [text, setText] = useState('')
  const [volume, setVolume] = useState('normal')
  const [addressees, setAddressees] = useState<string[]>([])
  const [sending, setSending] = useState(false)
  const [layout, setLayout] = useState<Layout[]>(DEFAULT_LAYOUT)
  const [open, setOpen] = useState<string[]>(GRID_PANELS)  // Dialoge starten geschlossen
  const [autosize, setAutosize] = useState<string[]>([])  // Panels mit Höhen-Autosize
  const [width, setWidth] = useState(1200)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const layoutLoaded = useRef(false)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const layoutRef = useRef(layout)
  const openRef = useRef(open)
  const autosizeRef = useRef(autosize)
  layoutRef.current = layout
  openRef.current = open
  autosizeRef.current = autosize

  const persist = useCallback(() => {
    apiPut('/play/layout', { layout: { grid: layoutRef.current, open: openRef.current, autosize: autosizeRef.current } })
      .catch(() => { /* best-effort */ })
  }, [])

  // Layout + offene Panels aus dem Profil laden (einmalig)
  useEffect(() => {
    apiGet<{ layout?: unknown }>('/play/layout')
      .then((r) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const v: any = r?.layout
        if (Array.isArray(v) && v.length) {
          setLayout(v)  // altes Format (nur grid)
        } else if (v && typeof v === 'object') {
          if (Array.isArray(v.grid) && v.grid.length) setLayout(v.grid)
          if (Array.isArray(v.open)) setOpen(v.open)
          if (Array.isArray(v.autosize)) setAutosize(v.autosize)
        }
      })
      .catch(() => { /* Default behalten */ })
      .finally(() => { layoutLoaded.current = true })
  }, [])

  // Containerbreite messen → Spaltenzahl so wählen, dass Zellen quadratisch sind.
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width
      if (w && w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const onLayoutChange = useCallback((current: Layout[]) => {
    // `current` enthält nur die offenen Panels. Positionen GESCHLOSSENER Panels
    // beibehalten, damit sie beim Wieder-Öffnen an ihrer letzten Stelle erscheinen.
    const seen = new Set(current.map((i) => i.i))
    const retained = layoutRef.current.filter((i) => !seen.has(i.i))
    const merged = [...current, ...retained]
    layoutRef.current = merged
    setLayout(merged)
    if (!layoutLoaded.current) return  // initiales/geladenes Layout nicht zurückschreiben
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(persist, 800)
  }, [persist])

  const setOpenAnd = useCallback((next: string[]) => {
    openRef.current = next
    setOpen(next)
    if (layoutLoaded.current) persist()
  }, [persist])
  const togglePanel = useCallback((id: string) => {
    const isOpen = openRef.current.includes(id)
    setOpenAnd(isOpen
      ? openRef.current.filter((x) => x !== id)
      : [...openRef.current, id])
    // Wieder-Aktivieren → in den Vordergrund holen (Z-Stacking ans Ende).
    if (!isOpen) setOrder((o) => (o[o.length - 1] === id ? o : [...o.filter((x) => x !== id), id]))
  }, [setOpenAnd])
  const closePanel = useCallback((id: string) => {
    setOpenAnd(openRef.current.filter((x) => x !== id))
  }, [setOpenAnd])
  const toggleAutosize = useCallback((id: string) => {
    const next = autosizeRef.current.includes(id)
      ? autosizeRef.current.filter((x) => x !== id)
      : [...autosizeRef.current, id]
    autosizeRef.current = next
    setAutosize(next)
    if (layoutLoaded.current) persist()
  }, [persist])

  const resetLayout = useCallback(() => {
    layoutRef.current = DEFAULT_LAYOUT
    openRef.current = GRID_PANELS
    autosizeRef.current = []
    setLayout(DEFAULT_LAYOUT)
    setOpen(GRID_PANELS)
    setAutosize([])
    persist()
  }, [persist])

  // Benannte Layout-Presets
  const [presets, setPresets] = useState<Record<string, { grid?: Layout[]; open?: string[]; autosize?: string[] }>>({})
  const refreshPresets = useCallback(async () => {
    try {
      const d = await apiGet<{ presets?: Record<string, { grid?: Layout[]; open?: string[]; autosize?: string[] }> }>('/play/layouts')
      setPresets(d?.presets || {})
    } catch { /* ignore */ }
  }, [])
  useEffect(() => { refreshPresets() }, [refreshPresets])

  const loadPreset = useCallback((name: string) => {
    const p = presets[name]
    if (!p) return
    const grid = Array.isArray(p.grid) && p.grid.length ? p.grid : DEFAULT_LAYOUT
    const op = Array.isArray(p.open) ? p.open : ALL_PANELS
    const az = Array.isArray(p.autosize) ? p.autosize : []
    layoutRef.current = grid
    openRef.current = op
    autosizeRef.current = az
    setLayout(grid)
    setOpen(op)
    setAutosize(az)
    persist()  // geladenes Preset wird auch zum aktiven Layout
    closePanel('layouts')  // Dialog schließt nach dem Laden
  }, [presets, persist, closePanel])

  const savePreset = useCallback(async (name: string) => {
    const n = (name || '').trim()
    if (!n) return
    try {
      await apiPut('/play/layouts', { name: n, layout: { grid: layoutRef.current, open: openRef.current, autosize: autosizeRef.current } })
      await refreshPresets()
      closePanel('layouts')  // Dialog schließt nach Speichern/Überschreiben
    } catch { /* ignore */ }
  }, [refreshPresets, closePanel])

  const deletePreset = useCallback(async (name: string) => {
    if (!name) return
    try {
      await apiDelete(`/play/layouts/${encodeURIComponent(name)}`)
      await refreshPresets()
    } catch { /* ignore */ }
  }, [refreshPresets])

  const ctrlBtn: React.CSSProperties = {
    cursor: 'pointer', background: 'transparent', border: 'none', color: 'inherit',
    opacity: 0.55, lineHeight: 1, padding: '0 2px',
  }
  // Kopf-Steuerung: optional „in den Hintergrund" + Schließen, rechtsbündig.
  const headerControls = (id: string, withBack: boolean, withClose = true) => (
    // marginRight rückt die Buttons aus der oberen-rechten Ecke, damit der
    // RGL-Resize-Griff (ne) nicht den Klick auf × abfängt.
    <span style={{ marginLeft: 'auto', marginRight: 14, flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8, position: 'relative', zIndex: 2 }}>
      {withBack && (
        <button onClick={() => toggleAutosize(id)} onMouseDown={(e) => e.stopPropagation()}
          title={t('Autosize height to content')} aria-label={t('Autosize height to content')}
          aria-pressed={autosize.includes(id)}
          style={{ ...ctrlBtn, fontSize: '0.95em', opacity: autosize.includes(id) ? 1 : 0.55 }}>⇕</button>
      )}
      {withBack && (
        <button onClick={() => sendToBack(id)} onMouseDown={(e) => e.stopPropagation()}
          title={t('Send to back')} aria-label={t('Send to back')}
          style={{ ...ctrlBtn, fontSize: '0.95em' }}>⌄</button>
      )}
      {withClose && (
        <button onClick={() => closePanel(id)} onMouseDown={(e) => e.stopPropagation()}
          title={t('Close')} aria-label={t('Close')}
          style={{ ...ctrlBtn, fontSize: '1.15em' }}>×</button>
      )}
    </span>
  )

  const load = useCallback(async () => {
    try {
      setData(await apiGet<SceneData>('/play/scene'))
    } catch {
      /* api.ts redirects to login on 401/403 */
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [load])

  const toggleAddressee = useCallback((name: string) => {
    setAddressees((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name])
  }, [])

  const send = useCallback(async () => {
    if (!text.trim() || sending) return
    setSending(true)
    try {
      const addr = volume === 'whisper' ? addressees.slice(0, 1) : addressees
      await apiPost('/play/say', { content: text, volume, addressees: addr })
      setText('')
      await load()
    } catch {
      /* swallow for the scaffold; api handles auth redirect */
    } finally {
      setSending(false)
    }
  }, [text, volume, addressees, sending, load])

  const [moving, setMoving] = useState(false)
  const handleStep = useCallback(async (dir: Dir) => {
    if (moving) return
    setMoving(true)
    try { await apiPost('/world/avatar/step', { direction: dir }); await load() }
    catch { /* 404 = kein Nachbar */ } finally { setMoving(false) }
  }, [moving, load])
  const handleEnterRoom = useCallback(async (roomId: string) => {
    if (moving) return
    setMoving(true)
    try { await apiPost('/play/enter-room', { room_id: roomId }); await load() }
    catch { /* ignore */ } finally { setMoving(false) }
  }, [moving, load])

  const lines: SceneLine[] = (data?.scene || []).map((p) => ({
    ts: p.ts, content: p.content, kind: p.kind, meta: p.meta,
  }))
  const present = data?.present || []
  // "Others"-Panel ist rein an Anwesenheit gekoppelt: sichtbar ⟺ jemand anderes
  // ist da. Bewusst UNABHÄNGIG vom open-/gespeicherten-Layout (sonst blendet ein
  // altes gespeichertes Layout es aus) — auto ein/aus, kein manuelles Toggle.
  const hasOthers = present.length > 0
  // Beim Erscheinen nach vorne holen, damit es nie hinter einem (überlappenden,
  // selbst angeordneten) Panel verschwindet. Nur z-Reihenfolge, kein open-Touch.
  useEffect(() => {
    if (hasOthers) {
      setOrder((o) => (o[o.length - 1] === 'others' ? o : [...o.filter((x) => x !== 'others'), 'others']))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasOthers])
  // Szene-Indikator: NUR Antworten ("X antwortet …"), keine Hintergrund-Gedanken.
  // Das Task-Panel zeigt unabhängig davon alle LLM-Calls (auch Gedanken).
  const { agentActivity } = useQueue(2000)
  const thinkingHere = present
    .filter((p) => agentActivity[p]?.responding)
    .map((p) => ({ name: p, responding: true }))

  // Auto-Scroll der Szene ans Ende (neueste Wahrnehmung unten). "Stick to bottom":
  // nur nachziehen, wenn der User ohnehin unten ist — sonst nicht beim Hochscrollen
  // zum Lesen wegreißen.
  const sceneScrollRef = useRef<HTMLDivElement>(null)
  const sceneStickRef = useRef(true)
  const onSceneScroll = useCallback(() => {
    const el = sceneScrollRef.current
    if (!el) return
    sceneStickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  }, [])
  useEffect(() => {
    const el = sceneScrollRef.current
    if (el && sceneStickRef.current) el.scrollTop = el.scrollHeight
  }, [lines.length, thinkingHere.length])

  // Adressaten-Auswahl beschneiden, sobald sich die Anwesenden ändern (z.B. nach
  // einem Raum-/Ortswechsel) — sonst bleibt jemand vom alten Raum adressiert,
  // der hier gar nicht ist. Backend filtert zusätzlich, das hier ist die UI-Seite.
  const presentKey = present.join('')
  useEffect(() => {
    setAddressees((prev) => {
      const next = prev.filter((n) => present.includes(n))
      return next.length === prev.length ? prev : next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presentKey])

  // Z-Stacking für überlappende Fenster: zuletzt angefasstes Panel steht zuletzt
  // im DOM → vorderstes. Klick/Drag auf ein Panel holt es nach vorn.
  const [order, setOrder] = useState<string[]>(['scene', 'env', 'map', 'worldmap', 'tasks', 'self', 'others', 'belongings', 'journal', 'gallery', 'layouts'])
  const bringToFront = useCallback((id: string) => {
    setOrder((o) => (o[o.length - 1] === id ? o : [...o.filter((x) => x !== id), id]))
  }, [])
  const sendToBack = useCallback((id: string) => {
    setOrder((o) => (o[0] === id ? o : [id, ...o.filter((x) => x !== id)]))
  }, [])
  // RGL positioniert das Panel-Div selbst (position:absolute) → z-index greift
  // direkt hier. Zuletzt angefasstes Panel (Ende von order) = höchster z-index.
  const zOf = (id: string) => 10 + Math.max(0, order.indexOf(id))

  const scenePanel = (
    <div key="scene" className="player-panel" style={{ zIndex: zOf('scene') }} onMouseDownCapture={() => bringToFront('scene')}>
          <div className="player-panel-head">
            {data?.avatar || '—'}
            <span className="sub">
              {present.length ? `· ${present.join(', ')}` : `· ${t('You are alone here.')}`}
            </span>
            {headerControls('scene', true)}
          </div>
          <div className="player-scene-body">
            <ScenesRecap />
            <div className="player-scene-scroll" ref={sceneScrollRef} onScroll={onSceneScroll}>
              <SceneView lines={lines} emptyHint={t('Nothing here yet.')} thinking={thinkingHere} />
            </div>

            {(data?.follow_suggestions?.length ?? 0) > 0 && (
              <div style={{
                flex: '0 0 auto', padding: '6px 12px', display: 'flex', flexWrap: 'wrap',
                gap: 10, alignItems: 'center', borderTop: '1px solid var(--border, #30363d)',
                background: 'rgba(214,176,106,0.08)',
              }}>
                {data!.follow_suggestions!.map((f) => (
                  <span key={f.character} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82em' }}>
                    <span style={{ fontStyle: 'italic', color: '#d6b06a' }}>
                      {f.character} {t('went to')} {f.room_name}.
                    </span>
                    <button onClick={() => handleEnterRoom(f.room_id)} disabled={moving}
                      style={{
                        padding: '2px 10px', borderRadius: 12, cursor: 'pointer',
                        border: '1px solid #d6b06a', background: 'rgba(214,176,106,0.18)', color: 'inherit',
                      }}>
                      {t('Follow')}
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="player-composer">
              {present.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                  <span style={{ opacity: 0.6, fontSize: '0.85em', alignSelf: 'center' }}>{t('Address')}:</span>
                  {present.map((name) => {
                    const on = addressees.includes(name)
                    return (
                      <button key={name} onClick={() => toggleAddressee(name)}
                        style={{
                          padding: '2px 10px', borderRadius: 12, cursor: 'pointer',
                          border: '1px solid rgba(255,255,255,0.25)',
                          background: on ? 'rgba(120,170,255,0.35)' : 'transparent',
                          color: 'inherit',
                        }}>
                        {name}
                      </button>
                    )
                  })}
                </div>
              )}
              <textarea rows={3} value={text} disabled={sending}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
                placeholder={sending ? t('Waiting for a reply…') : t('Say something…')}
                style={{
                  display: 'block', width: '100%', boxSizing: 'border-box',
                  minHeight: 64, resize: 'vertical',
                  padding: '8px 10px', borderRadius: 6,
                  border: '1px solid rgba(255,255,255,0.35)',
                  background: 'rgba(255,255,255,0.06)', color: 'inherit',
                  font: 'inherit',
                  opacity: sending ? 0.55 : 1, cursor: sending ? 'wait' : 'auto',
                }} />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
                <select className="ga-input" value={volume} onChange={(e) => setVolume(e.target.value)}
                  style={{ flex: '0 0 auto', width: 'auto' }}>
                  <option value="whisper">{t('whisper')}</option>
                  <option value="normal">{t('normal')}</option>
                  <option value="shout">{t('shout')}</option>
                </select>
                <span style={{ flex: 1 }} />
                <button onClick={send} disabled={sending || !text.trim()}>
                  {sending ? t('Sending…') : t('Send')}
                </button>
              </div>
              {volume === 'whisper' && addressees.length !== 1 && (
                <div style={{ opacity: 0.6, fontSize: '0.8em', marginTop: 4 }}>
                  {t('Whispering needs exactly one addressee.')}
                </div>
              )}
            </div>
          </div>
        </div>
  )

  const mapPanel = (
    <div key="map" className="player-panel" style={{ zIndex: zOf('map') }} onMouseDownCapture={() => bringToFront('map')}>
      <div className="player-panel-head">
        {data?.room_name || data?.location_name || t('Move')}
        {data?.location_name && data?.room_name
          ? <span className="sub">· {data.location_name}</span> : null}
        {headerControls('map', true)}
      </div>
      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden', padding: 8 }}>
        <MovePad
          rooms={data?.rooms || []}
          currentRoomId={data?.room_id || ''}
          neighbors={data?.neighbors || {}}
          atEntryRoom={data?.at_entry_room !== false}
          entryRoomName={data?.entry_room_name || ''}
          busy={moving}
          onStep={handleStep}
          onEnterRoom={handleEnterRoom}
        />
      </div>
    </div>
  )

  const envPanel = (
    <div key="env" className="player-panel" style={{ zIndex: zOf('env') }} onMouseDownCapture={() => bringToFront('env')}>
      <div className="player-panel-head">{t('Surroundings')}{headerControls('env', true)}</div>
      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden' }}>
        <EnvironmentPanel
          locationId={data?.location_id || ''}
          roomId={data?.room_id || ''}
          locationName={data?.location_name || ''}
          roomName={data?.room_name || ''}
          present={data?.present_detail || []}
          avatarName={data?.avatar || ''}
          avatarExprVersion={data?.avatar_expr_version || ''}
          bgVersion={data?.bg_version || ''}
          bgId={data?.bg_id || ''}
        />
      </div>
    </div>
  )

  const worldMapPanel = (
    <div key="worldmap" className="player-panel" style={{ zIndex: zOf('worldmap') }} onMouseDownCapture={() => bringToFront('worldmap')}>
      <div className="player-panel-head">{t('Map')}{headerControls('worldmap', true)}</div>
      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden', padding: 4 }}>
        <MapPanel currentLocationId={data?.location_id || ''} />
      </div>
    </div>
  )

  const tasksPanel = (
    <div key="tasks" className="player-panel" style={{ zIndex: zOf('tasks') }} onMouseDownCapture={() => bringToFront('tasks')}>
      <div className="player-panel-head">{t('Tasks')}{headerControls('tasks', true)}</div>
      <div className="player-panel-body">
        <TaskPanel />
      </div>
    </div>
  )

  const selfPanel = (
    <div key="self" className="player-panel" style={{ zIndex: zOf('self') }} onMouseDownCapture={() => bringToFront('self')}>
      <div className="player-panel-head">{data?.avatar || t('Self')}{headerControls('self', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'auto' }}>
        <SelfPanel />
      </div>
    </div>
  )

  const belongingsPanel = (
    <div key="belongings" className="player-panel" style={{ zIndex: zOf('belongings') }} onMouseDownCapture={() => bringToFront('belongings')}>
      <div className="player-panel-head">{t('Inventory')}{headerControls('belongings', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <BelongingsPanel />
      </div>
    </div>
  )

  const journalPanel = (
    <div key="journal" className="player-panel" style={{ zIndex: zOf('journal') }} onMouseDownCapture={() => bringToFront('journal')}>
      <div className="player-panel-head">{t('Journal')}{headerControls('journal', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <JournalPanel />
      </div>
    </div>
  )

  const galleryPanel = (
    <div key="gallery" className="player-panel" style={{ zIndex: zOf('gallery') }} onMouseDownCapture={() => bringToFront('gallery')}>
      <div className="player-panel-head">{t('Gallery')}{headerControls('gallery', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <GalleryPanel />
      </div>
    </div>
  )

  const instagramPanel = (
    <div key="instagram" className="player-panel" style={{ zIndex: zOf('instagram') }} onMouseDownCapture={() => bringToFront('instagram')}>
      <div className="player-panel-head">{t('Instagram')}{headerControls('instagram', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'auto' }}>
        <InstagramPanel />
      </div>
    </div>
  )

  const othersPanel = (
    <div key="others" className="player-panel" style={{ zIndex: zOf('others') }} onMouseDownCapture={() => bringToFront('others')}>
      <div className="player-panel-head">{t('Others')}{headerControls('others', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <OthersPanel />
      </div>
    </div>
  )

  const byId: Record<string, ReactNode> = {
    scene: scenePanel, env: envPanel, map: mapPanel, worldmap: worldMapPanel,
    tasks: tasksPanel, self: selfPanel, others: othersPanel, belongings: belongingsPanel,
    journal: journalPanel, gallery: galleryPanel, instagram: instagramPanel,
  }

  // Spaltenzahl aus gemessener Breite: colWidth ≈ CELL → quadratische Zellen.
  const cols = Math.max(1, Math.floor((width + MARGIN) / (CELL + MARGIN)))
  // Sicherstellen, dass das Layout IMMER ein Item für jedes Panel hat (sonst
  // erscheint ein wieder-geöffnetes Panel als winziges 1×1-Default).
  const known = new Set(layout.map((l) => l.i))
  const fullLayout = DEFAULT_LAYOUT.some((d) => !known.has(d.i))
    ? [...layout, ...DEFAULT_LAYOUT.filter((d) => !known.has(d.i))]
    : layout
  // Schutz gegen 0×0/1×1: react-grid-layout vergibt einem frisch gemounteten
  // Panel manchmal eine Mini-Default-Box, die sich via onLayoutChange ins
  // gespeicherte Layout "einbrennt". Faellt eine Box unter ihre Mindestgroesse,
  // auf die Default-Groesse zwingen (groesseres/manuelles Resizing bleibt).
  const sizedLayout = fullLayout.map((l) => {
    const def = DEFAULT_BY_ID[l.i]
    if (!def) return l
    if (!l.w || !l.h || l.w < (def.minW ?? 2) || l.h < (def.minH ?? 2)) {
      return { ...l, w: def.w, h: def.h }
    }
    return l
  })
  // Tatsächlich gerenderte Grid-Panels: am open-Set wie üblich; 'others' ist
  // zusätzlich an Anwesenheit gegated (steht standardmäßig im open-Set, kein
  // Effekt entfernt es → erscheint automatisch sobald jemand da ist, auch beim
  // Location-Wechsel; verschwindet wenn man allein ist).
  const renderedIds = GRID_PANELS.filter(
    (id) => byId[id] && open.includes(id) && (id !== 'others' || hasOthers))
  // Beim Öffnen/Schließen den GridLayout neu mounten, damit RGL seinen internen
  // State frisch aus dem layout-Prop ableitet (sonst erscheint ein wieder-
  // geöffnetes Panel als 1×1). Ziehen/Bring-to-front ändern `open` NICHT → kein
  // Remount → keine Snap-backs.
  const openKey = [...renderedIds].sort().join('|')

  // Autosize: für jedes aktivierte (und gerenderte) Panel die natürliche
  // Inhaltshöhe messen und als Grid-Rows (h) zurückspielen. Der Body ist via
  // CSS (data-autosize) inhaltsgroß → seine offsetHeight = Inhaltshöhe; ein
  // ResizeObserver feuert bei Inhaltsänderung (z.B. Others bei Character-Wechsel)
  // und re-fittet automatisch. Breite (w) bleibt unangetastet.
  const autosizeKey = autosize.filter((id) => renderedIds.includes(id)).sort().join('|')
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const active = autosizeRef.current.filter((id) => renderedIds.includes(id))
    if (!active.length) return
    const bodyOf = (id: string): HTMLElement | null => {
      const panel = root.querySelector(`[data-panel-id="${id}"]`)
      if (!panel) return null
      const head = panel.querySelector('.player-panel-head')
      return (Array.from(panel.children).find(
        (el) => el !== head && !el.classList.contains('react-resizable-handle')) as HTMLElement) || null
    }
    const apply = (id: string) => {
      const panel = root.querySelector(`[data-panel-id="${id}"]`) as HTMLElement | null
      const body = bodyOf(id)
      if (!panel || !body) return
      const head = panel.querySelector('.player-panel-head') as HTMLElement | null
      const contentH = body.offsetHeight + (head ? head.offsetHeight : 0)
      const minH = DEFAULT_BY_ID[id]?.minH ?? 4
      const rows = Math.max(minH, Math.ceil((contentH + MARGIN) / (CELL + MARGIN)))
      const cur = layoutRef.current.find((l) => l.i === id)
      if (!cur || cur.h === rows) return
      const next = layoutRef.current.map((l) => (l.i === id ? { ...l, h: rows } : l))
      layoutRef.current = next
      setLayout(next)
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(persist, 800)
    }
    const observers = active.map((id) => {
      const body = bodyOf(id)
      if (!body) return null
      const ro = new ResizeObserver(() => apply(id))
      ro.observe(body)
      apply(id)  // initiale Messung
      return ro
    })
    return () => observers.forEach((o) => o?.disconnect())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autosizeKey, openKey, persist])

  return (
    <div className="player-root" ref={rootRef}>
      <NoticeBanner />
      <div style={{
        position: 'fixed', top: 6, right: 10, zIndex: 1000,
        display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap',
        justifyContent: 'flex-end', maxWidth: '72vw',
      }}>
        {PANEL_META.filter((p) => p.id !== 'others' || hasOthers).map((p) => {
          const isOpen = open.includes(p.id)
          return (
            <button key={p.id} onClick={() => togglePanel(p.id)} title={t(p.label)}
              style={{
                fontSize: '0.72em', padding: '2px 8px', borderRadius: 10, cursor: 'pointer',
                border: '1px solid var(--border, #30363d)',
                background: isOpen ? 'var(--bg-hover, #1f2937)' : 'transparent',
                color: 'inherit', opacity: isOpen ? 1 : 0.4,
              }}>
              {t(p.label)}
            </button>
          )
        })}
        <button onClick={resetLayout} title={t('Reset layout')}
          style={{
            fontSize: '0.72em', padding: '2px 8px', borderRadius: 10, cursor: 'pointer',
            border: '1px solid var(--border, #30363d)',
            background: 'var(--bg-container, #161b22)', color: 'inherit', opacity: 0.7,
          }}>↺</button>
      </div>
      <GridLayout
        key={openKey}
        className="layout"
        layout={sizedLayout}
        onLayoutChange={onLayoutChange}
        onDragStart={(_l, item) => bringToFront(item.i)}
        onResizeStart={(_l, item) => bringToFront(item.i)}
        cols={cols}
        width={width}
        rowHeight={CELL}
        margin={[MARGIN, MARGIN]}
        draggableHandle=".player-panel-head"
        resizeHandles={['s', 'w', 'e', 'n', 'sw', 'nw', 'se', 'ne']}
        allowOverlap
        compactType={null}
        preventCollision={false}
      >
        {renderedIds.map((id) => cloneElement(byId[id] as ReactElement, {
          'data-panel-id': id,
          'data-autosize': autosize.includes(id) ? '1' : undefined,
        }))}
      </GridLayout>

      {/* Dialog-Panels als zentriertes Overlay */}
      {DIALOG_PANELS.filter((id) => open.includes(id)).map((id) => (
        <div key={id} className="player-modal-backdrop" onMouseDown={() => closePanel(id)}>
          <div className="player-modal" onMouseDown={(e) => e.stopPropagation()}>
            <div className="player-panel-head">
              {t(PANEL_META.find((p) => p.id === id)?.label || '')}
              {headerControls(id, false)}
            </div>
            <div className="player-panel-body">
              {id === 'layouts' && (
                <LayoutsPanel presets={presets} onSave={savePreset} onLoad={loadPreset} onDelete={deletePreset} />
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
