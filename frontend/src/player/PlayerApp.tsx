/**
 * PlayerApp — the in-world player surface (plan-room-conversation Phase 2).
 * A SEPARATE page at /play, distinct from the game-admin.
 *
 * Layout: react-grid-layout — frei verschieb-/größenveränderbare Panels
 * ("Fenster"), Optik komplett unsere (game-tauglich). Erste Panels: Szene
 * (wahrgenommene Raum-Szene + Composer) und ein Platzhalter (z.B. Karte).
 * Layout-Persistenz ins User-Profil + weitere Panels folgen als nächste Schritte.
 */
import { cloneElement, useCallback, useEffect, useRef, useState,
  type ReactElement, type ReactNode,
  type ClipboardEvent as ReactClipboardEvent, type DragEvent as ReactDragEvent } from 'react'
import { createPortal } from 'react-dom'
import GridLayout, { type Layout } from 'react-grid-layout'
import { useI18n } from '../i18n/I18nProvider'
import { useAuth } from '../lib/AuthGate'
import { useAvatarSwitch } from './AvatarGate'
import { apiDelete, apiGet, apiPost, apiPut, apiUpload } from '../lib/api'
import { usePoll } from './usePolling'
import { useToast } from '../lib/Toast'
import { ChatGalleryPicker } from './ChatGalleryPicker'
import { GiftPicker, type GiftResult } from './GiftPicker'
import { SceneView, type SceneLine } from '../components/SceneView'
import { ImageGenDialog, type ImageGenSubmit } from '../components/ImageGenDialog'
import { ScenesRecap } from './ScenesRecap'
import { MovePad } from './MovePad'
import { EnvironmentPanel } from './EnvironmentPanel'
import { MapPanel, type LabelMode, loadLabelMode, nextLabelMode, saveLabelMode } from './MapPanel'
import { TaskPanel } from './TaskPanel'
import { NewsPanel } from './NewsPanel'
import { LayoutsPanel } from './LayoutsPanel'
import { SelfPanel } from './SelfPanel'
import { OthersPanel } from './OthersPanel'
import { BelongingsPanel } from './BelongingsPanel'
import { MindPanel } from './MindPanel'
import { AvatarSettingsPanel } from './AvatarSettingsPanel'
import { GalleryPanel } from './GalleryPanel'
import { InstagramPanel } from './InstagramPanel'
import { PhonePanel } from './PhonePanel'
import { NoticeBanner } from './NoticeBanner'
import { useQueue } from './useQueue'
import { Icon, type IconName } from './icons'
import { LightboxProvider, useLightbox } from './Lightbox'
import {
  CELL, MARGIN, DEFAULT_LAYOUT, DEFAULT_BY_ID, PANEL_META, ALL_PANELS,
  GRID_PANELS, DIALOG_PANELS, INITIAL_OPEN, ICON_BY_ID, LABEL_BY_ID,
  PANEL_COLOR, EXPANDABLE,
} from './panelRegistry'

type IconMode = 'icon' | 'iconText'
type ToolbarAlign = 'left' | 'right'

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
  party?: { role: 'leader' | 'follower'; leader: string; members: string[] } | null
  party_invites?: Array<{ invite_id: string; inviter: string }>
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
  const { logout } = useAuth()
  const { chooseAvatar } = useAvatarSwitch()
  const [data, setData] = useState<SceneData | null>(null)
  const [text, setText] = useState('')
  const [volume, setVolume] = useState('normal')
  const [addressees, setAddressees] = useState<string[]>([])
  const [sending, setSending] = useState(false)
  // Chat image attachment (#5 upload / #6 gallery). Exactly one source is set:
  // `image_id` for an upload, `image_url` for a library pick. `preview` is the
  // URL shown in the composer thumbnail. `uploading` gates send during upload.
  const [attach, setAttach] = useState<
    { image_id?: string; image_url?: string; preview: string; uploading?: boolean } | null
  >(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [giftOpen, setGiftOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const lightbox = useLightbox()
  const { toast } = useToast()
  const [layout, setLayout] = useState<Layout[]>(DEFAULT_LAYOUT)
  const [open, setOpen] = useState<string[]>(INITIAL_OPEN)  // Dialoge starten geschlossen
  const [autosize, setAutosize] = useState<string[]>([])  // Panels mit Höhen-Autosize
  const [panelAlpha, setPanelAlpha] = useState<Record<string, number>>({})  // Panel-Transparenz (1 = deckend)
  const [iconMode, setIconMode] = useState<IconMode>('iconText')      // Launcher: nur Icon vs Icon+Text (Default aus gespeichertem Layout)
  const [toolbarAlign, setToolbarAlign] = useState<ToolbarAlign>('left')  // Launcher links/rechts (Default aus gespeichertem Layout)
  const [appearanceOpen, setAppearanceOpen] = useState(false)    // Zahnrad-Popover
  const [frozen, setFrozen] = useState(false)                    // Layout einfrieren + mitskalieren
  const [frozenWidth, setFrozenWidth] = useState(0)              // Referenzbreite beim Einfrieren
  const [width, setWidth] = useState(1200)
  // Badges „offene Themen": ungelesene Telefon-Nachrichten + neue IG-Posts.
  const [phoneUnread, setPhoneUnread] = useState(0)
  const [igNew, setIgNew] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)  // Panel im View-only-Overlay vergrößert
  const [expandSeq, setExpandSeq] = useState(0)  // erzwingt frischen Remount des Overlay-Inhalts je Öffnen (Zoom-Reset)
  const openExpanded = useCallback((id: string) => { setExpanded(id); setExpandSeq((s) => s + 1) }, [])
  const [bgPanel, setBgPanel] = useState<string>('')             // Panel-id, die als Vollbild-Hintergrund dient ('' = keine)
  const [mapLabelMode, setMapLabelMode] = useState<LabelMode>(loadLabelMode)  // Map-Beschriftungen: all/unique/none
  const igSeenRef = useRef<string | null>(null)  // zuletzt gesehene IG-Post-id
  const rootRef = useRef<HTMLDivElement | null>(null)
  const layoutLoaded = useRef(false)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const layoutRef = useRef(layout)
  const openRef = useRef(open)
  const autosizeRef = useRef(autosize)
  const panelAlphaRef = useRef(panelAlpha)
  const iconModeRef = useRef(iconMode)
  const toolbarAlignRef = useRef(toolbarAlign)
  const frozenRef = useRef(frozen)
  const frozenWidthRef = useRef(frozenWidth)
  const widthRef = useRef(width)
  const bgPanelRef = useRef(bgPanel)
  bgPanelRef.current = bgPanel
  layoutRef.current = layout
  openRef.current = open
  autosizeRef.current = autosize
  panelAlphaRef.current = panelAlpha
  iconModeRef.current = iconMode
  toolbarAlignRef.current = toolbarAlign
  frozenRef.current = frozen
  frozenWidthRef.current = frozenWidth
  widthRef.current = width

  const persist = useCallback(() => {
    apiPut('/play/layout', { layout: {
      grid: layoutRef.current, open: openRef.current, autosize: autosizeRef.current,
      panelAlpha: panelAlphaRef.current,
      iconMode: iconModeRef.current, toolbarAlign: toolbarAlignRef.current,
      frozen: frozenRef.current, frozenWidth: frozenWidthRef.current,
      bg: bgPanelRef.current,
    } }).catch(() => { /* best-effort */ })
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
          if (v.panelAlpha && typeof v.panelAlpha === 'object') setPanelAlpha(v.panelAlpha)
          if (v.iconMode === 'icon' || v.iconMode === 'iconText') setIconMode(v.iconMode)
          if (v.toolbarAlign === 'left' || v.toolbarAlign === 'right') setToolbarAlign(v.toolbarAlign)
          if (typeof v.frozenWidth === 'number' && v.frozenWidth > 0) setFrozenWidth(v.frozenWidth)
          if (v.frozen === true) setFrozen(true)
          if (typeof v.bg === 'string') setBgPanel(v.bg)
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
  // Badges pollen: Telefon-Unread (Server-Summe) + neue IG-Posts seit der zuletzt
  // gesehenen id (localStorage). Ist das IG-Panel offen oder beim allerersten Lauf,
  // gilt alles als gesehen → kein Badge.
  const refreshBadges = useCallback(async () => {
    try {
      const m = await apiGet<{ conversations?: Array<{ unread?: number }> }>('/play/messages')
      setPhoneUnread((m.conversations || []).reduce((s, c) => s + (c.unread || 0), 0))
    } catch { /* ignore */ }
    try {
      const f = await apiGet<{ posts?: Array<{ id: string }> }>('/instagram/feed?limit=50')
      const posts = f.posts || []
      const newest = posts[0]?.id || null
      if (openRef.current.includes('instagram') || !igSeenRef.current) {
        igSeenRef.current = newest
        if (newest) { try { localStorage.setItem('play.ig.seen', newest) } catch { /* ignore */ } }
        setIgNew(0)
      } else {
        const idx = posts.findIndex((p) => p.id === igSeenRef.current)
        setIgNew(idx < 0 ? Math.min(posts.length, 99) : idx)
      }
    } catch { /* ignore */ }
  }, [])
  const togglePanel = useCallback((id: string) => {
    const isOpen = openRef.current.includes(id)
    setOpenAnd(isOpen
      ? openRef.current.filter((x) => x !== id)
      : [...openRef.current, id])
    // Wieder-Aktivieren → in den Vordergrund holen (Z-Stacking ans Ende).
    if (!isOpen) setOrder((o) => (o[o.length - 1] === id ? o : [...o.filter((x) => x !== id), id]))
    // IG öffnen → sofort als gesehen markieren (Badge weg), Stand nachziehen.
    if (!isOpen && id === 'instagram') { setIgNew(0); refreshBadges() }
  }, [setOpenAnd, refreshBadges])
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
  // Panel transparency: header button cycles 100% → 75% → 50% → 25% (same
  // pattern as the map-label cycle); persisted with the layout.
  const cycleAlpha = useCallback((id: string) => {
    const steps = [1, 0.75, 0.5, 0.25]
    const cur = panelAlphaRef.current[id] ?? 1
    const next = steps[(steps.indexOf(cur) + 1) % steps.length] ?? 1
    const map = { ...panelAlphaRef.current }
    if (next >= 1) delete map[id]
    else map[id] = next
    panelAlphaRef.current = map
    setPanelAlpha(map)
    if (layoutLoaded.current) persist()
  }, [persist])

  // Surroundings als Vollbild-Hintergrund: Panel verliert Kopf/Kachel, der
  // Inhalt (inkl. Figuren-Drag) läuft als interaktiver Background weiter.
  const setAsBackground = useCallback((id: string) => {
    bgPanelRef.current = id
    setBgPanel(id)
    if (layoutLoaded.current) persist()
  }, [persist])
  const clearBackground = useCallback(() => {
    bgPanelRef.current = ''
    setBgPanel('')
    if (layoutLoaded.current) persist()
  }, [persist])
  const cycleMapLabel = useCallback(() => {
    setMapLabelMode((m) => { const n = nextLabelMode(m); saveLabelMode(n); return n })
  }, [])

  const chooseIconMode = useCallback((m: IconMode) => {
    iconModeRef.current = m
    setIconMode(m)
    if (layoutLoaded.current) persist()
  }, [persist])
  const chooseToolbarAlign = useCallback((a: ToolbarAlign) => {
    toolbarAlignRef.current = a
    setToolbarAlign(a)
    if (layoutLoaded.current) persist()
  }, [persist])
  // Einfrieren: aktuelle Breite als Referenz festhalten → das Grid skaliert
  // fortan proportional mit der Fenstergröße (wie der Browser-Zoom), statt die
  // Spaltenzahl zu ändern. Aufheben → wieder responsives Spalten-Verhalten.
  const toggleFreeze = useCallback(() => {
    if (frozenRef.current) {
      frozenRef.current = false
      setFrozen(false)
    } else {
      const ref = Math.round(widthRef.current) || 1200
      frozenRef.current = true
      frozenWidthRef.current = ref
      setFrozenWidth(ref)
      setFrozen(true)
    }
    if (layoutLoaded.current) persist()
  }, [persist])

  const resetLayout = useCallback(() => {
    layoutRef.current = DEFAULT_LAYOUT
    openRef.current = INITIAL_OPEN
    autosizeRef.current = []
    frozenRef.current = false
    bgPanelRef.current = ''
    setLayout(DEFAULT_LAYOUT)
    setOpen(INITIAL_OPEN)
    setAutosize([])
    setFrozen(false)  // zurück in den responsiven Modus
    setBgPanel('')    // Vollbild-Hintergrund aufheben
    persist()
  }, [persist])

  // Benannte Layout-Presets
  const [presets, setPresets] = useState<Record<string, { grid?: Layout[]; open?: string[]; autosize?: string[]; panelAlpha?: Record<string, number>; iconMode?: IconMode; toolbarAlign?: ToolbarAlign; frozen?: boolean; frozenWidth?: number; bg?: string }>>({})
  const refreshPresets = useCallback(async () => {
    try {
      const d = await apiGet<{ presets?: Record<string, { grid?: Layout[]; open?: string[]; autosize?: string[]; panelAlpha?: Record<string, number>; iconMode?: IconMode; toolbarAlign?: ToolbarAlign; frozen?: boolean; frozenWidth?: number; bg?: string }> }>('/play/layouts')
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
    const pa = p.panelAlpha && typeof p.panelAlpha === 'object' ? p.panelAlpha : {}
    layoutRef.current = grid
    openRef.current = op
    autosizeRef.current = az
    panelAlphaRef.current = pa
    setLayout(grid)
    setOpen(op)
    setAutosize(az)
    setPanelAlpha(pa)
    // Toolbar-Position + Labels mit-wiederherstellen (aeltere Presets ohne diese
    // Felder lassen die aktuelle Einstellung unveraendert).
    if (p.iconMode === 'icon' || p.iconMode === 'iconText') { iconModeRef.current = p.iconMode; setIconMode(p.iconMode) }
    if (p.toolbarAlign === 'left' || p.toolbarAlign === 'right') { toolbarAlignRef.current = p.toolbarAlign; setToolbarAlign(p.toolbarAlign) }
    persist()  // geladenes Preset wird auch zum aktiven Layout
    closePanel('layouts')  // Dialog schließt nach dem Laden
  }, [presets, persist, closePanel])

  const savePreset = useCallback(async (name: string) => {
    const n = (name || '').trim()
    if (!n) return
    try {
      await apiPut('/play/layouts', { name: n, layout: {
        grid: layoutRef.current, open: openRef.current, autosize: autosizeRef.current,
        panelAlpha: panelAlphaRef.current,
        // Toolbar-Position (links/rechts) + Labels (Icon/Icon+Text) gehoeren zum Preset.
        iconMode: iconModeRef.current, toolbarAlign: toolbarAlignRef.current,
        frozen: frozenRef.current, frozenWidth: frozenWidthRef.current, bg: bgPanelRef.current,
      } })
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

  // Panel-Icon links im Kopf (dezent, erbt die Kopf-Textfarbe).
  const headIcon = (id: string) =>
    ICON_BY_ID[id]
      ? <Icon name={ICON_BY_ID[id]} size={15} className="player-head-icon" />
      : null
  // Kopf-Steuerung: Autosize · in den Hintergrund · schließen — rechtsbündig.
  // marginRight (CSS) rückt die Buttons aus der Ecke, damit der RGL-Resize-Griff
  // (ne) nicht den Klick auf × abfängt.
  const headerControls = (id: string, withBack: boolean, withClose = true) => (
    <span className="player-head-ctrls">
      {withBack && (
        <button className={`player-ctrl-btn${autosize.includes(id) ? ' on' : ''}`}
          onClick={() => toggleAutosize(id)} onMouseDown={(e) => e.stopPropagation()}
          title={t('Autosize height to content')} aria-label={t('Autosize height to content')}
          aria-pressed={autosize.includes(id)}>
          <Icon name="autosize" size={14} />
        </button>
      )}
      {withBack && (
        <button className={`player-ctrl-btn${(panelAlpha[id] ?? 1) < 1 ? ' on' : ''}`}
          onClick={() => cycleAlpha(id)} onMouseDown={(e) => e.stopPropagation()}
          title={`${t('Panel transparency')}: ${Math.round((panelAlpha[id] ?? 1) * 100)}%`}
          aria-label={t('Panel transparency')}>
          <Icon name="transparency" size={14} />
        </button>
      )}
      {withBack && (
        <button className="player-ctrl-btn"
          onClick={() => sendToBack(id)} onMouseDown={(e) => e.stopPropagation()}
          title={t('Send to back')} aria-label={t('Send to back')}>
          <Icon name="sendBack" size={14} />
        </button>
      )}
      {EXPANDABLE.has(id) && (
        <button className="player-ctrl-btn"
          onClick={() => openExpanded(id)} onMouseDown={(e) => e.stopPropagation()}
          title={t('Enlarge')} aria-label={t('Enlarge')}>
          <Icon name="maximize" size={14} />
        </button>
      )}
      {id === 'env' && (
        <button className="player-ctrl-btn"
          onClick={() => setAsBackground('env')} onMouseDown={(e) => e.stopPropagation()}
          title={t('Set as background')} aria-label={t('Set as background')}>
          <Icon name="background" size={14} />
        </button>
      )}
      {id === 'worldmap' && (
        <button className={`player-ctrl-btn${mapLabelMode !== 'all' ? ' on' : ''}`}
          onClick={cycleMapLabel} onMouseDown={(e) => e.stopPropagation()}
          title={`${t('Map labels')}: ${mapLabelMode === 'all' ? t('all') : mapLabelMode === 'unique' ? t('unique') : t('off')}`}
          aria-label={t('Map labels')}>
          <Icon name="tag" size={14} />
        </button>
      )}
      {withClose && (
        <button className="player-ctrl-btn player-ctrl-close"
          onClick={() => closePanel(id)} onMouseDown={(e) => e.stopPropagation()}
          title={t('Close')} aria-label={t('Close')}>
          <Icon name="close" size={15} />
        </button>
      )}
    </span>
  )

  // Esc schließt das vergrößerte Panel-Overlay.
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  // View-only-Inhalt eines Panels für die vergrößerte Anzeige. Erweiterbar:
  // hier pro EXPANDABLE-Panel den (read-only) Inhalt zurückgeben.
  const expandedContent = (id: string): ReactNode => {
    if (id === 'worldmap') return <MapPanel key={expandSeq} currentLocationId={data?.location_id || ''} autoFit labelMode={mapLabelMode} />
    return null
  }

  // Scene poll via the shared hub; `load` stays as a thin refresh wrapper so
  // the many `await load()` callers (send, step, enter-room, party) work as before.
  const { data: sceneData, refresh: refreshScene } = usePoll<SceneData>(
    'play-scene', () => apiGet<SceneData>('/play/scene'), { intervalMs: 5000 })
  useEffect(() => { if (sceneData) setData(sceneData) }, [sceneData])
  const load = refreshScene

  // Badges: remember the seen IG id once, then poll slowly (open topics).
  useEffect(() => {
    try { igSeenRef.current = localStorage.getItem('play.ig.seen') } catch { /* ignore */ }
  }, [])
  usePoll('play-badges', refreshBadges, { intervalMs: 20000 })

  const toggleAddressee = useCallback((name: string) => {
    setAddressees((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name])
  }, [])

  const send = useCallback(async () => {
    // An attached image alone is a valid message; an upload still in flight is not.
    const hasImage = !!(attach && (attach.image_id || attach.image_url))
    if ((!text.trim() && !hasImage) || sending || attach?.uploading) return
    setSending(true)
    try {
      const addr = volume === 'whisper' ? addressees.slice(0, 1) : addressees
      await apiPost('/play/say', {
        content: text, volume, addressees: addr,
        ...(attach?.image_id ? { image_id: attach.image_id } : {}),
        ...(attach?.image_url ? { image_url: attach.image_url } : {}),
      })
      setText('')
      setAttach(null)
      await load()
    } catch {
      /* swallow for the scaffold; api handles auth redirect */
    } finally {
      setSending(false)
    }
  }, [text, volume, addressees, sending, attach, load])

  // 📷 scene photo: step 1 distills the prompt from the recent room
  // conversation (+ person descriptions) and opens the image-gen dialog
  // (model/LoRA/prompt editable); step 2 generates into the avatar's
  // gallery + narrator line in the chat (present characters can react).
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoDlg, setPhotoDlg] = useState<{ prompt: string; subjects: string[]; present: string[] } | null>(null)
  const takePhoto = useCallback(async () => {
    if (photoBusy) return
    setPhotoBusy(true)
    try {
      const d = await apiPost<{ ok?: boolean; prompt?: string; subjects?: string[]; present?: string[] }>(
        '/play/scene-photo/prepare', {})
      if (d?.ok) {
        setPhotoDlg({ prompt: d.prompt || '', subjects: d.subjects || [], present: d.present || [] })
      } else {
        toast(t('Photo failed.'), 'error')
      }
    } catch (e) {
      toast((e as Error).message || t('Photo failed.'), 'error')
    } finally {
      setPhotoBusy(false)
    }
  }, [photoBusy, toast, t])
  const submitPhoto = useCallback(async (payload: ImageGenSubmit) => {
    setPhotoDlg(null)
    setPhotoBusy(true)
    try {
      const d = await apiPost<{ ok?: boolean }>('/play/scene-photo', {
        prompt: payload.prompt,
        backend: payload.backend || '',
        loras: payload.loras || null,
        negative_prompt: payload.negative_prompt || '',
        character_names: payload.character_names || null,
        use_room: payload.use_room !== false,
      })
      if (d?.ok) {
        toast(t('Photo saved to your gallery.'), 'success')
        await load()
      } else {
        toast(t('Photo failed.'), 'error')
      }
    } catch (e) {
      toast((e as Error).message || t('Photo failed.'), 'error')
    } finally {
      setPhotoBusy(false)
    }
  }, [toast, t, load])

  // Upload a picked/pasted/dropped file → attach by image_id. A local object URL
  // is shown immediately as the preview while the upload resolves.
  const uploadImage = useCallback(async (file: File) => {
    if (!file.type.startsWith('image/')) return
    const localPreview = URL.createObjectURL(file)
    setAttach({ preview: localPreview, uploading: true })
    try {
      const r = await apiUpload<{ image_id: string }>('/chat/me/upload-image', file)
      setAttach({ image_id: r.image_id, preview: localPreview, uploading: false })
    } catch {
      setAttach(null)
      URL.revokeObjectURL(localPreview)
    }
  }, [])

  const onComposerPaste = useCallback((e: ReactClipboardEvent) => {
    const item = Array.from(e.clipboardData.items).find((it) => it.type.startsWith('image/'))
    if (item) {
      const f = item.getAsFile()
      if (f) { e.preventDefault(); uploadImage(f) }
    }
  }, [uploadImage])

  const onComposerDrop = useCallback((e: ReactDragEvent) => {
    const f = Array.from(e.dataTransfer.files).find((x) => x.type.startsWith('image/'))
    if (f) { e.preventDefault(); uploadImage(f) }
  }, [uploadImage])

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
  // Party (gemeinsam reisen): Einladung im Chat-Fenster beantworten. Das
  // Verlassen sitzt im NoticeBanner (persistenter Party-Streifen).
  const handlePartyRespond = useCallback(async (inviteId: string, accept: boolean) => {
    try { await apiPost('/play/party/respond', { invite_id: inviteId, accept }); await load() }
    catch { /* ignore */ }
  }, [load])

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
  const [order, setOrder] = useState<string[]>(['scene', 'env', 'map', 'worldmap', 'tasks', 'self', 'others', 'belongings', 'journal', 'gallery', 'instagram', 'phone', 'news', 'settings', 'layouts'])
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
            {headIcon('scene')}
            {data?.avatar || '—'}
            <span className="sub">
              {present.length ? `· ${present.join(', ')}` : `· ${t('You are alone here.')}`}
            </span>
            {headerControls('scene', true)}
          </div>
          <div className="player-scene-body">
            <ScenesRecap />
            <div className="player-scene-scroll" ref={sceneScrollRef} onScroll={onSceneScroll}>
              <SceneView lines={lines} emptyHint={t('Nothing here yet.')} thinking={thinkingHere}
                onOpenImage={(u) => lightbox.open({ src: u })} />
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
                      className="player-chip player-chip-follow">
                      {t('Follow')}
                    </button>
                  </span>
                ))}
              </div>
            )}

            {(data?.party_invites?.length ?? 0) > 0 && (
              <div style={{
                flex: '0 0 auto', padding: '6px 12px', display: 'flex', flexWrap: 'wrap',
                gap: 10, alignItems: 'center', borderTop: '1px solid var(--border, #30363d)',
                background: 'rgba(120,170,255,0.10)',
              }}>
                {data!.party_invites!.map((inv) => (
                  <span key={inv.invite_id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82em' }}>
                    <span style={{ fontStyle: 'italic', color: '#78aaff' }}>
                      👥 {inv.inviter} {t('invites you to travel together.')}
                    </span>
                    <button onClick={() => handlePartyRespond(inv.invite_id, true)}
                      className="player-chip player-chip-follow">
                      {t('Join')}
                    </button>
                    <button onClick={() => handlePartyRespond(inv.invite_id, false)}
                      className="player-chip">
                      {t('Decline')}
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="player-composer"
              onDragOver={(e) => { if (Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault() }}
              onDrop={onComposerDrop}>
              {present.length > 0 && (
                <div className="player-address-row">
                  <span className="player-address-label">{t('Address')}:</span>
                  {present.map((name) => {
                    const on = addressees.includes(name)
                    return (
                      <button key={name} onClick={() => toggleAddressee(name)}
                        className={`player-chip${on ? ' on' : ''}`}>
                        {name}
                      </button>
                    )
                  })}
                </div>
              )}
              {attach && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={{ position: 'relative', flex: '0 0 auto' }}>
                    <img src={attach.preview} alt={t('Attached image')}
                      style={{
                        width: 56, height: 56, objectFit: 'cover', borderRadius: 6,
                        border: '1px solid var(--border, #30363d)',
                        opacity: attach.uploading ? 0.5 : 1,
                      }} />
                    <button type="button" onClick={() => setAttach(null)} title={t('Remove')}
                      style={{
                        position: 'absolute', top: -6, right: -6, width: 18, height: 18,
                        borderRadius: '50%', border: 'none', cursor: 'pointer',
                        background: 'var(--danger, #da3633)', color: '#fff', fontSize: 11,
                        lineHeight: '18px', padding: 0,
                      }}>×</button>
                  </div>
                  <span style={{ fontSize: '0.8em', opacity: 0.7 }}>
                    {attach.uploading ? t('Uploading…') : t('Image attached')}
                  </span>
                </div>
              )}
              <textarea className="player-composer-input" rows={3} value={text} disabled={sending}
                onChange={(e) => setText(e.target.value)}
                onPaste={onComposerPaste}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
                placeholder={sending ? t('Waiting for a reply…') : t('Say something…')} />
              <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadImage(f); e.target.value = '' }} />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
                <select className="ga-input" value={volume} onChange={(e) => setVolume(e.target.value)}
                  style={{ flex: '0 0 auto', width: 'auto' }}>
                  <option value="whisper">{t('whisper')}</option>
                  <option value="normal">{t('normal')}</option>
                  <option value="shout">{t('shout')}</option>
                </select>
                <button type="button" className="player-chip" title={t('Upload image')}
                  onClick={() => fileInputRef.current?.click()} disabled={sending}>📎</button>
                <button type="button" className="player-chip" title={t('Pick from gallery')}
                  onClick={() => setPickerOpen(true)} disabled={sending}>🖼</button>
                <button type="button" className="player-chip" title={t('Give a gift')}
                  onClick={() => setGiftOpen(true)} disabled={sending || present.length === 0}>🎁</button>
                <button type="button" className="player-chip" style={{ marginLeft: 12 }}
                  title={t('Take a photo of the current moment (saved to your gallery)')}
                  onClick={takePhoto} disabled={photoBusy}>
                  {photoBusy ? '⌛' : '📷'}
                </button>
                <span style={{ flex: 1 }} />
                <button className="player-btn-primary" onClick={send}
                  disabled={sending || attach?.uploading || (!text.trim() && !attach)}>
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
          {pickerOpen && (
            <ChatGalleryPicker
              onClose={() => setPickerOpen(false)}
              onPick={(url) => { setAttach({ image_url: url, preview: url }); setPickerOpen(false) }}
            />
          )}
          {photoDlg && (
            <ImageGenDialog
              open
              title={t('Scene photo')}
              defaultPrompt={photoDlg.prompt}
              showRoomReference
              characterOptions={{
                detected: photoDlg.subjects,
                available: Array.from(new Set([...photoDlg.present, ...(data?.avatar ? [data.avatar] : [])])),
              }}
              onSubmit={submitPhoto}
              onClose={() => setPhotoDlg(null)}
            />
          )}
          {giftOpen && (
            <GiftPicker
              avatar={data?.avatar || ''}
              recipients={present}
              defaultRecipient={addressees.length === 1 ? addressees[0] : undefined}
              onClose={() => setGiftOpen(false)}
              onGifted={(r: GiftResult) => {
                setGiftOpen(false)
                toast(
                  `${t('Gift sent')}: ${r.item_name} → ${r.to_character}` +
                    (r.boost ? ` (+${r.boost} ${t('relationship')})` : ''),
                  'success',
                )
                load()
              }}
            />
          )}
        </div>
  )

  const mapPanel = (
    <div key="map" className="player-panel" style={{ zIndex: zOf('map') }} onMouseDownCapture={() => bringToFront('map')}>
      <div className="player-panel-head">
        {headIcon('map')}
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
          partyFollower={data?.party?.role === 'follower'}
          partyLeaderName={data?.party?.leader || ''}
        />
      </div>
    </div>
  )

  const envContent = (
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
  )
  const envPanel = (
    <div key="env" className="player-panel" style={{ zIndex: zOf('env') }} onMouseDownCapture={() => bringToFront('env')}>
      <div className="player-panel-head">{headIcon('env')}{t('Surroundings')}{headerControls('env', true)}</div>
      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden' }}>
        {envContent}
      </div>
    </div>
  )

  const worldMapPanel = (
    <div key="worldmap" className="player-panel" style={{ zIndex: zOf('worldmap') }} onMouseDownCapture={() => bringToFront('worldmap')}>
      <div className="player-panel-head">{headIcon('worldmap')}{t('Map')}{headerControls('worldmap', true)}</div>
      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden', padding: 4 }}>
        <MapPanel currentLocationId={data?.location_id || ''} labelMode={mapLabelMode} />
      </div>
    </div>
  )

  const tasksPanel = (
    <div key="tasks" className="player-panel" style={{ zIndex: zOf('tasks') }} onMouseDownCapture={() => bringToFront('tasks')}>
      <div className="player-panel-head">{headIcon('tasks')}{t('Tasks')}{headerControls('tasks', true)}</div>
      <div className="player-panel-body">
        <TaskPanel />
      </div>
    </div>
  )

  const newsPanel = (
    <div key="news" className="player-panel" style={{ zIndex: zOf('news') }} onMouseDownCapture={() => bringToFront('news')}>
      <div className="player-panel-head">{headIcon('news')}{t('News')}{headerControls('news', true)}</div>
      <div className="player-panel-body" style={{ padding: 0, overflow: 'hidden' }}>
        <NewsPanel />
      </div>
    </div>
  )

  const selfPanel = (
    <div key="self" className="player-panel" style={{ zIndex: zOf('self') }} onMouseDownCapture={() => bringToFront('self')}>
      <div className="player-panel-head">{headIcon('self')}{data?.avatar || t('Self')}{headerControls('self', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'auto' }}>
        <SelfPanel />
      </div>
    </div>
  )

  const belongingsPanel = (
    <div key="belongings" className="player-panel" style={{ zIndex: zOf('belongings') }} onMouseDownCapture={() => bringToFront('belongings')}>
      <div className="player-panel-head">{headIcon('belongings')}{t('Inventory')}{headerControls('belongings', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <BelongingsPanel onClose={() => closePanel('belongings')} />
      </div>
    </div>
  )

  const journalPanel = (
    <div key="journal" className="player-panel" style={{ zIndex: zOf('journal') }} onMouseDownCapture={() => bringToFront('journal')}>
      <div className="player-panel-head">{headIcon('journal')}{t('Mind')}{headerControls('journal', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <MindPanel character={data?.avatar || ''} />
      </div>
    </div>
  )

  const galleryPanel = (
    <div key="gallery" className="player-panel" style={{ zIndex: zOf('gallery') }} onMouseDownCapture={() => bringToFront('gallery')}>
      <div className="player-panel-head">{headIcon('gallery')}{t('Gallery')}{headerControls('gallery', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <GalleryPanel />
      </div>
    </div>
  )

  const instagramPanel = (
    <div key="instagram" className="player-panel" style={{ zIndex: zOf('instagram') }} onMouseDownCapture={() => bringToFront('instagram')}>
      <div className="player-panel-head">{headIcon('instagram')}{t('Instagram')}{headerControls('instagram', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'auto' }}>
        <InstagramPanel />
      </div>
    </div>
  )

  const othersPanel = (
    <div key="others" className="player-panel" style={{ zIndex: zOf('others') }} onMouseDownCapture={() => bringToFront('others')}>
      <div className="player-panel-head">{headIcon('others')}{t('Others')}{headerControls('others', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <OthersPanel />
      </div>
    </div>
  )

  const phonePanel = (
    <div key="phone" className="player-panel" style={{ zIndex: zOf('phone') }} onMouseDownCapture={() => bringToFront('phone')}>
      <div className="player-panel-head">{headIcon('phone')}{t('Phone')}{headerControls('phone', true)}</div>
      <div className="player-panel-body" style={{ padding: 0, overflow: 'hidden' }}>
        <PhonePanel />
      </div>
    </div>
  )

  const settingsPanel = (
    <div key="settings" className="player-panel" style={{ zIndex: zOf('settings') }} onMouseDownCapture={() => bringToFront('settings')}>
      <div className="player-panel-head">{headIcon('settings')}{t('Avatar')}{headerControls('settings', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'hidden' }}>
        <AvatarSettingsPanel avatar={data?.avatar || ''} />
      </div>
    </div>
  )

  const byId: Record<string, ReactNode> = {
    scene: scenePanel, env: envPanel, map: mapPanel, worldmap: worldMapPanel,
    tasks: tasksPanel, self: selfPanel, others: othersPanel, belongings: belongingsPanel,
    journal: journalPanel, gallery: galleryPanel, instagram: instagramPanel, phone: phonePanel,
    news: newsPanel, settings: settingsPanel,
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
    (id) => byId[id] && open.includes(id) && id !== bgPanel && (id !== 'others' || hasOthers))
  // Vorderstes Panel (höchster z-index) = aktiv → bekommt einen dezenten
  // Akzent-Streifen am Kopf + stärkeren Schatten, damit klar ist welches vorn liegt.
  const frontId = renderedIds.reduce<string | undefined>(
    (a, b) => (a == null || zOf(b) >= zOf(a) ? b : a), undefined)
  // Eingefroren: Grid in fixer Referenzbreite/-Spaltenzahl rendern und per
  // CSS-transform an die echte Breite skalieren (Browser-Zoom-Verhalten). Der
  // Wrapper bekommt die *skalierte* Höhe, damit der Scrollbereich stimmt; RGL
  // erhält `transformScale`, sodass Ziehen/Resize trotz CSS-Skalierung korrekt
  // rechnen. Nicht eingefroren = unverändertes responsives Spalten-Verhalten.
  const frozenActive = frozen && frozenWidth > 0
  const activeCols = frozenActive
    ? Math.max(1, Math.floor((frozenWidth + MARGIN) / (CELL + MARGIN)))
    : cols
  const renderWidth = frozenActive ? frozenWidth : width
  const fitScale = frozenActive ? width / frozenWidth : 1
  const renderedBottom = sizedLayout
    .filter((l) => renderedIds.includes(l.i))
    .reduce((m, l) => Math.max(m, (l.y || 0) + (l.h || 0)), 0)
  const gridContentH = renderedBottom * (CELL + MARGIN) + MARGIN
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
      const headH = head ? head.offsetHeight : 0
      const minH = DEFAULT_BY_ID[id]?.minH ?? 4
      const minW = DEFAULT_BY_ID[id]?.minW ?? 4
      // Content may report its natural size itself (e.g. the map via
      // data-content-w/h) since DOM measurement fails for internally
      // scrolling content. Then WIDTH + height come from it; otherwise
      // only the height via offsetHeight.
      const reporter = body.querySelector('[data-content-w]') as HTMLElement | null
      const reportedW = reporter ? parseFloat(reporter.getAttribute('data-content-w') || '') : NaN
      const reportedH = reporter ? parseFloat(reporter.getAttribute('data-content-h') || '') : NaN
      const contentH = (reporter && reportedH > 0 ? reportedH : body.offsetHeight) + headH
      const cur = layoutRef.current.find((l) => l.i === id)
      if (!cur) return
      let rows = Math.max(minH, Math.ceil((contentH + MARGIN) / (CELL + MARGIN)))
      let newW = (reporter && reportedW > 0)
        ? Math.max(minW, Math.ceil((reportedW + MARGIN) / (CELL + MARGIN)))
        : cur.w
      // Viewport cap: autosize must never grow a panel past the visible
      // browser area (that would create page scrollbars at the edges).
      // Measured in screen px and converted through the panel's actual
      // on-screen cell size — this also accounts for the frozen-mode CSS
      // scale transform without needing fitScale in this closure.
      const rect = panel.getBoundingClientRect()
      const unit = CELL + MARGIN
      const scale = (cur.h > 0 && rect.height > 0)
        ? rect.height / (cur.h * unit - MARGIN) : 1
      const maxRows = Math.max(minH,
        Math.floor((window.innerHeight - Math.max(0, rect.top)) / (scale || 1) / unit))
      const maxCols = Math.max(minW,
        Math.floor((window.innerWidth - Math.max(0, rect.left)) / (scale || 1) / unit))
      rows = Math.min(rows, maxRows)
      newW = Math.min(newW, maxCols)
      if (cur.h === rows && cur.w === newW) return
      const next = layoutRef.current.map((l) => (l.i === id ? { ...l, h: rows, w: newW } : l))
      layoutRef.current = next
      setLayout(next)
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(persist, 800)
    }
    const observers = active.flatMap((id) => {
      const body = bodyOf(id)
      if (!body) return []
      const ro = new ResizeObserver(() => apply(id))
      ro.observe(body)
      // Selbst-gemeldete Größe (data-content-w/h, z.B. Map) ändert sich bei
      // Zoom OHNE Body-Resize → der ResizeObserver feuert nicht. Attribut-
      // Mutationen separat beobachten, damit Autosize der Zoomstufe folgt.
      const mo = new MutationObserver(() => apply(id))
      mo.observe(body, { attributes: true, subtree: true,
        attributeFilter: ['data-content-w', 'data-content-h'] })
      apply(id)  // initiale Messung
      return [ro, mo]
    })
    return () => observers.forEach((o) => o.disconnect())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autosizeKey, openKey, persist])

  // --- Toolbar (Launcher) -------------------------------------------------
  const tbBtn = (id: string, label: string, icon: IconName, isOpen: boolean, onClick: () => void, badge = 0, bg = false) => {
    // bg-Modus (Surroundings als Hintergrund) behaelt seinen Accent-Look.
    const col = bg ? '' : PANEL_COLOR[id]
    return (
      <button key={id} onClick={onClick} title={t(label)} aria-label={t(label)} aria-pressed={isOpen}
        className={`play-tbtn${isOpen ? ' open' : ''}${bg ? ' bg' : ''}${iconMode === 'iconText' ? ' with-text' : ''}`}
        style={{
          position: 'relative',
          // Duotone: gefuellter Farb-Chip (Akzent) + Linien-Icon in derselben
          // Panel-Farbe. Aktiv kraeftiger + Rahmen.
          ...(col ? { color: col, background: col + (isOpen ? '40' : '20') } : {}),
          ...(isOpen && col ? { borderColor: col } : {}),
        }}>
        <Icon name={icon} size={15} />
        {iconMode === 'iconText' && <span className="play-tbtn-label">{t(label)}</span>}
        {badge > 0 && <span className="play-tbtn-badge">{badge > 99 ? '99+' : badge}</span>}
      </button>
    )
  }
  // Badge je Panel-id (offene Themen): Telefon-Unread, neue IG-Posts.
  const badgeOf = (id: string) => (id === 'phone' ? phoneUnread : id === 'instagram' ? igNew : 0)
  // Panel-Umschalter folgen der Position/Label-Einstellung. 'layouts' nicht hier:
  // der Layouts-Button + Reset + Zahnrad bleiben fest rechts (Wunsch).
  const panelToggles = PANEL_META
    .filter((p) => p.kind !== 'dialog')
    .filter((p) => p.id !== 'others' || hasOthers)
    .filter((p) => p.id !== 'tasks')  // Tasks = Ueberwachung -> rechts in den Werkzeug-Cluster
    .map((p) => {
      // Surroundings im Background-Modus: Button anders darstellen, Klick stellt
      // den normalen Panel-Zustand wieder her.
      if (p.id === bgPanel) {
        return tbBtn(p.id, 'Restore from background', p.icon, true, clearBackground, 0, true)
      }
      return tbBtn(p.id, p.label, p.icon, open.includes(p.id), () => togglePanel(p.id), badgeOf(p.id))
    })
  const layoutsMeta = PANEL_META.find((p) => p.id === 'layouts')!
  const fixedCluster = (
    <>
      {tbBtn('tasks', 'Tasks', 'tasks', open.includes('tasks'), () => togglePanel('tasks'))}
      {tbBtn('layouts', layoutsMeta.label, layoutsMeta.icon, open.includes('layouts'), () => togglePanel('layouts'))}
      <button onClick={toggleFreeze} aria-pressed={frozen}
        title={frozen ? t('Unfreeze layout (responsive columns)') : t('Freeze layout (scale with window)')}
        aria-label={frozen ? t('Unfreeze layout') : t('Freeze layout')}
        className={`play-tbtn${frozen ? ' open' : ''}`}>
        <Icon name={frozen ? 'lock' : 'unlock'} size={15} />
      </button>
      <button onClick={resetLayout} title={t('Reset layout')} aria-label={t('Reset layout')} className="play-tbtn">
        <Icon name="reset" size={15} />
      </button>
      <div style={{ position: 'relative' }}>
        <button onClick={() => setAppearanceOpen((o) => !o)} title={t('Toolbar settings')}
          aria-label={t('Toolbar settings')} aria-pressed={appearanceOpen}
          className={`play-tbtn${appearanceOpen ? ' open' : ''}`}>
          <Icon name="settings" size={15} />
        </button>
        {appearanceOpen && (
          <>
            <div className="play-pop-backdrop" onMouseDown={() => setAppearanceOpen(false)} />
            <div className="play-appearance-pop" onMouseDown={(e) => e.stopPropagation()}>
              <div className="play-pop-row">
                <span className="play-pop-label">{t('Labels')}</span>
                <div className="play-seg">
                  <button className={iconMode === 'icon' ? 'on' : ''} onClick={() => chooseIconMode('icon')}>{t('Icon')}</button>
                  <button className={iconMode === 'iconText' ? 'on' : ''} onClick={() => chooseIconMode('iconText')}>{t('Icon + text')}</button>
                </div>
              </div>
              <div className="play-pop-row">
                <span className="play-pop-label">{t('Position')}</span>
                <div className="play-seg">
                  <button className={toolbarAlign === 'left' ? 'on' : ''} onClick={() => chooseToolbarAlign('left')}>{t('Left')}</button>
                  <button className={toolbarAlign === 'right' ? 'on' : ''} onClick={() => chooseToolbarAlign('right')}>{t('Right')}</button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
      <button onClick={chooseAvatar} title={t('Switch avatar')} aria-label={t('Switch avatar')} className="play-tbtn">
        <span style={{ fontSize: 14, lineHeight: 1 }}>⇄</span>
      </button>
      <button onClick={() => { void logout() }} title={t('Logout')} aria-label={t('Logout')} className="play-tbtn">
        <span style={{ fontSize: 14, lineHeight: 1 }}>⎋</span>
      </button>
    </>
  )

  return (
    <LightboxProvider>
    <div className={`player-root${bgPanel ? ' has-bg' : ''}`} ref={rootRef}>
      {bgPanel === 'env' && (
        <div className="player-bg-layer">{envContent}</div>
      )}
      <div className="play-toolbar">
        <div className="play-toolbar-group play-toolbar-start">
          {toolbarAlign === 'left' && panelToggles}
        </div>
        <div className="play-toolbar-group play-toolbar-end">
          {toolbarAlign === 'right' && panelToggles}
          {fixedCluster}
        </div>
      </div>
      <NoticeBanner />
      <div className="play-grid-wrap" style={frozenActive ? { width, height: gridContentH * fitScale, overflow: 'hidden' } : undefined}>
        <div style={frozenActive
          ? { width: renderWidth, transform: `scale(${fitScale})`, transformOrigin: 'top left' }
          : undefined}>
          <GridLayout
            key={openKey}
            className="layout"
            layout={sizedLayout}
            onLayoutChange={onLayoutChange}
            onDragStart={(_l, item) => bringToFront(item.i)}
            onResizeStart={(_l, item) => bringToFront(item.i)}
            cols={activeCols}
            width={renderWidth}
            transformScale={fitScale}
            rowHeight={CELL}
            margin={[MARGIN, MARGIN]}
            draggableHandle=".player-panel-head"
            resizeHandles={['s', 'w', 'e', 'n', 'sw', 'nw', 'se', 'ne']}
            allowOverlap
            compactType={null}
            preventCollision={false}
          >
            {renderedIds.map((id) => {
              const el = byId[id] as ReactElement
              const alpha = panelAlpha[id] ?? 1
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const baseStyle = (el.props as any).style
              return cloneElement(el, {
                'data-panel-id': id,
                'data-autosize': autosize.includes(id) ? '1' : undefined,
                className: `player-panel${id === frontId ? ' player-panel-front' : ''}`,
                // Per-panel transparency (header cycle button). RGL merges its
                // positional styles over this — opacity survives untouched.
                style: alpha < 1 ? { ...baseStyle, opacity: alpha } : baseStyle,
              })
            })}
          </GridLayout>
        </div>
      </div>

      {/* Dialog-Panels als zentriertes Overlay */}
      {DIALOG_PANELS.filter((id) => open.includes(id)).map((id) => (
        <div key={id} className="player-modal-backdrop" onMouseDown={() => closePanel(id)}>
          <div className="player-modal" onMouseDown={(e) => e.stopPropagation()}>
            <div className="player-panel-head">
              {headIcon(id)}
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

    {/* Vergrößertes Panel (view-only) — Portal an document.body, damit das
        position:fixed-Overlay dem react-grid-layout-Transform entkommt. */}
    {expanded && createPortal(
      <div onClick={() => setExpanded(null)}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.72)', zIndex: 2000,
                 display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3vh 3vw' }}>
        <div onClick={(e) => e.stopPropagation()} className="player-panel"
          style={{ width: '94vw', height: '94vh', display: 'flex', flexDirection: 'column' }}>
          <div className="player-panel-head">
            {headIcon(expanded)}{t(LABEL_BY_ID[expanded] || 'Map')}
            <span className="player-head-ctrls">
              {expanded === 'worldmap' && (
                <button className={`player-ctrl-btn${mapLabelMode !== 'all' ? ' on' : ''}`}
                  onClick={cycleMapLabel}
                  title={`${t('Map labels')}: ${mapLabelMode === 'all' ? t('all') : mapLabelMode === 'unique' ? t('unique') : t('off')}`}
                  aria-label={t('Map labels')}>
                  <Icon name="tag" size={14} />
                </button>
              )}
              <button className="player-ctrl-btn player-ctrl-close"
                onClick={() => setExpanded(null)} title={t('Close')} aria-label={t('Close')}>
                <Icon name="close" size={15} />
              </button>
            </span>
          </div>
          <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden', padding: 6 }}>
            {expandedContent(expanded)}
          </div>
        </div>
      </div>,
      document.body,
    )}
    </LightboxProvider>
  )
}
