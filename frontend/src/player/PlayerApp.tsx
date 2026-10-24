/**
 * PlayerApp — the in-world player surface (plan-room-conversation Phase 2).
 * A SEPARATE page at /play, distinct from the game-admin.
 *
 * Layout: freely movable and resizable react-grid-layout panels,
 * styled for the game. Initial panels: the perceived room scene with
 * composer and a placeholder such as the map. Profile layout persistence
 * and additional panels follow in later steps.
 */
import { cloneElement, useCallback, useEffect, useRef, useState,
  type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import GridLayout, { type Layout } from 'react-grid-layout'
import { useI18n } from '../i18n/I18nProvider'
import { useAuth } from '../lib/AuthGate'
import { useAvatarSwitch } from './AvatarGate'
import { apiDelete, apiGet, apiPost, apiPut, ApiError } from '../lib/api'
import { usePoll } from './usePolling'
import { useToast } from '../lib/Toast'
import { ScenePanel, type SceneData } from './ScenePanel'
import { ImageGenDialog } from '../components/ImageGenDialog'
import { AnimateDialog } from '../components/AnimateDialog'
import { TravelPanel } from './TravelPanel'
import { EnvironmentPanel } from './EnvironmentPanel'
import { type LabelMode, loadLabelMode, nextLabelMode, saveLabelMode } from './MapPanel'
import { TaskPanel } from './TaskPanel'
import { NewsPanel } from './NewsPanel'
// New in stage 6 and package-only from the start — no re-export stub needed,
// the panel never lived in frontend/.
import { SYNC_ENDPOINTS, QuestsPanel, NoticeBanner, useOpenTopics } from '@anima/player-ui'
import { LayoutsPanel } from './LayoutsPanel'
import { SelfPanel } from './SelfPanel'
import { OthersPanel } from './OthersPanel'
import { BelongingsPanel } from './BelongingsPanel'
import { MindPanel } from './MindPanel'
import { AvatarSettingsPanel } from '@anima/player-ui'
import { GalleryPanel } from './GalleryPanel'
import { InstagramPanel } from './InstagramPanel'
import { PhonePanel } from './PhonePanel'
import { GameClock } from '../components/GameClock'
import { Icon, type IconName } from './icons'
import { LightboxProvider } from './Lightbox'
import {
  CELL, MARGIN, DEFAULT_LAYOUT, DEFAULT_BY_ID, PANEL_META, ALL_PANELS,
  GRID_PANELS, DIALOG_PANELS, INITIAL_OPEN, ICON_BY_ID, LABEL_BY_ID,
  PANEL_COLOR, EXPANDABLE, REQUIRES_BY_ID,
} from './panelRegistry'

type IconMode = 'icon' | 'iconText'
type ToolbarAlign = 'left' | 'right'

/** A layout saved in a profile or a preset may still name panels that no
 *  longer exist (the schematic map lost its own tile in the 2026-09 teardown
 *  and lives in the travel panel now). Unknown ids are dropped on the way IN:
 *  `sizedLayout` lets a box with no default through, and the grid would then
 *  render an empty tile for a panel nothing can fill. */
const knownBoxes = (boxes: Layout[]): Layout[] =>
  boxes.filter((l) => !!DEFAULT_BY_ID[l.i])
const knownPanels = (ids: string[]): string[] =>
  ids.filter((id) => ALL_PANELS.includes(id))

export function PlayerApp() {
  const { t } = useI18n()
  const { logout } = useAuth()
  const { chooseAvatar } = useAvatarSwitch()
  const [data, setData] = useState<SceneData | null>(null)
  const { toast } = useToast()
  const [layout, setLayout] = useState<Layout[]>(DEFAULT_LAYOUT)
  const [open, setOpen] = useState<string[]>(INITIAL_OPEN)  // dialogs start closed
  const [autosize, setAutosize] = useState<string[]>([])  // panels with height autosize
  const [panelAlpha, setPanelAlpha] = useState<Record<string, number>>({})  // panel transparency (1 = opaque)
  const [iconMode, setIconMode] = useState<IconMode>('iconText')      // launcher: icon only vs icon+text (default from the saved layout)
  const [toolbarAlign, setToolbarAlign] = useState<ToolbarAlign>('left')  // launcher left/right (default from the saved layout)
  const [appearanceOpen, setAppearanceOpen] = useState(false)    // gear popover
  const [frozen, setFrozen] = useState(false)                    // freeze the layout and scale it with the window
  const [frozenWidth, setFrozenWidth] = useState(0)              // reference width at the moment of freezing
  const [width, setWidth] = useState(1200)
  // "Open topics" badges: unread phone messages + new IG posts.
  const { phone: phoneUnread, instagram: igNew } = useOpenTopics(open.includes('instagram'))
  const [expanded, setExpanded] = useState<string | null>(null)  // panel enlarged in the view-only overlay
  const [expandSeq, setExpandSeq] = useState(0)  // forces a fresh remount of the overlay content on every open (zoom reset)
  const openExpanded = useCallback((id: string) => { setExpanded(id); setExpandSeq((s) => s + 1) }, [])
  const [bgPanel, setBgPanel] = useState<string>('')             // panel id serving as the full-screen background ('' = none)
  const [mapLabelMode, setMapLabelMode] = useState<LabelMode>(loadLabelMode)  // Map labels: all/none
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

  // Load layout + open panels from the profile (once)
  useEffect(() => {
    apiGet<{ layout?: unknown }>('/play/layout')
      .then((r) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const v: any = r?.layout
        if (Array.isArray(v) && v.length) {
          setLayout(knownBoxes(v))  // old format (grid only)
        } else if (v && typeof v === 'object') {
          if (Array.isArray(v.grid) && v.grid.length) setLayout(knownBoxes(v.grid))
          if (Array.isArray(v.open)) setOpen(knownPanels(v.open))
          if (Array.isArray(v.autosize)) setAutosize(v.autosize)
          if (v.panelAlpha && typeof v.panelAlpha === 'object') setPanelAlpha(v.panelAlpha)
          if (v.iconMode === 'icon' || v.iconMode === 'iconText') setIconMode(v.iconMode)
          if (v.toolbarAlign === 'left' || v.toolbarAlign === 'right') setToolbarAlign(v.toolbarAlign)
          if (typeof v.frozenWidth === 'number' && v.frozenWidth > 0) setFrozenWidth(v.frozenWidth)
          if (v.frozen === true) setFrozen(true)
          if (typeof v.bg === 'string') setBgPanel(v.bg)
        }
      })
      .catch(() => { /* keep the default */ })
      .finally(() => { layoutLoaded.current = true })
  }, [])

  // Measure container width to choose a column count with square cells.
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
    // Current contains only open panels. Preserve closed panel positions
    // so reopening restores their previous places.
    const seen = new Set(current.map((i) => i.i))
    const retained = layoutRef.current.filter((i) => !seen.has(i.i))
    const merged = [...current, ...retained]
    layoutRef.current = merged
    setLayout(merged)
    if (!layoutLoaded.current) return  // Do not write back the initial or loaded layout.
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
    // Re-activating brings the panel to the front (last in the z-stack).
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

  // Surroundings as a full-screen background: remove the panel header/tile;
  // its content, including figure dragging, remains interactive.
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
  // Freeze the current width as reference, scaling proportionally with the
  // window like browser zoom instead of changing column count.
  // Unfreezing restores responsive columns.
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
    setFrozen(false)  // Return to responsive mode.
    setBgPanel('')    // Clear the full-screen background.
    persist()
  }, [persist])

  // Named layout presets
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
    const grid = knownBoxes(Array.isArray(p.grid) && p.grid.length ? p.grid : DEFAULT_LAYOUT)
    const op = knownPanels(Array.isArray(p.open) ? p.open : ALL_PANELS)
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
    // Restore toolbar position + labels along with it (older presets without
    // those fields leave the current setting untouched).
    if (p.iconMode === 'icon' || p.iconMode === 'iconText') { iconModeRef.current = p.iconMode; setIconMode(p.iconMode) }
    if (p.toolbarAlign === 'left' || p.toolbarAlign === 'right') { toolbarAlignRef.current = p.toolbarAlign; setToolbarAlign(p.toolbarAlign) }
    persist()  // a loaded preset becomes the active layout as well
    closePanel('layouts')  // the dialog closes once it is loaded
  }, [presets, persist, closePanel])

  const savePreset = useCallback(async (name: string) => {
    const n = (name || '').trim()
    if (!n) return
    try {
      await apiPut('/play/layouts', { name: n, layout: {
        grid: layoutRef.current, open: openRef.current, autosize: autosizeRef.current,
        panelAlpha: panelAlphaRef.current,
        // Toolbar side and labels (icon/icon+text) belong to the preset.
        iconMode: iconModeRef.current, toolbarAlign: toolbarAlignRef.current,
        frozen: frozenRef.current, frozenWidth: frozenWidthRef.current, bg: bgPanelRef.current,
      } })
      await refreshPresets()
      closePanel('layouts')  // Close after saving or overwriting.
    } catch { /* ignore */ }
  }, [refreshPresets, closePanel])

  const deletePreset = useCallback(async (name: string) => {
    if (!name) return
    try {
      await apiDelete(`/play/layouts/${encodeURIComponent(name)}`)
      await refreshPresets()
    } catch { /* ignore */ }
  }, [refreshPresets])

  // Subtle left header icon inherits the header text colour.
  const headIcon = (id: string) =>
    ICON_BY_ID[id]
      ? <Icon name={ICON_BY_ID[id]} size={15} className="player-head-icon" />
      : null
  // Right-aligned header controls: autosize, background, close.
  // CSS marginRight moves buttons away from the northeast RGL resize
  // handle so it cannot intercept clicks on the close button.
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
      {id === 'map' && (
        <button className={`player-ctrl-btn${mapLabelMode !== 'all' ? ' on' : ''}`}
          onClick={cycleMapLabel} onMouseDown={(e) => e.stopPropagation()}
          title={`${t('Map labels')}: ${mapLabelMode === 'all' ? t('all') : t('off')}`}
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

  // Escape closes the enlarged panel overlay.
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  // Content of a panel for the enlarged display. Extensible: return the
  // content per EXPANDABLE panel here. The travel panel keeps its actions in
  // the overlay — the map is only useful large if one can also set off from it.
  const expandedContent = (id: string): ReactNode => {
    if (id === 'map') {
      return (
        <TravelPanel
          key={expandSeq}
          rooms={data?.rooms || []}
          currentRoomId={data?.room_id || ''}
          currentLocationId={data?.location_id || ''}
          travel={data?.travel || null}
          busy={moving}
          blockedReason={data?.capability_blocks?.[data?.capability_actions?.travel || ''] || ''}
          onTravel={handleTravel}
          onCancelTravel={handleCancelTravel}
          onEnterRoom={handleEnterRoom}
          labelMode={mapLabelMode}
          autoFit
          partyFollower={data?.party?.role === 'follower'}
          partyLeaderName={data?.party?.leader || ''}
        />
      )
    }
    return null
  }

  // Scene poll via the shared hub — the ONE `/play/scene` poll of the player
  // surface. `load` stays as a thin refresh wrapper for the remaining callers
  // (step, enter-room); ScenePanel receives the same `refreshScene` as a prop.
  const { data: sceneData, refresh: refreshScene } = usePoll<SceneData>(
    'play-scene', () => apiGet<SceneData>('/play/scene'), SYNC_ENDPOINTS.scene)
  useEffect(() => { if (sceneData) setData(sceneData) }, [sceneData])
  const load = refreshScene

  // Capability gating: skill-bound surfaces disappear when the avatar's
  // capability list (GET /play/scene) lacks the required skill id — a removed
  // skill package degrades the UI automatically. Missing list (initial load)
  // = show everything, no flash-hiding.
  const hasCapability = (skillId: string) =>
    !data?.capabilities || data.capabilities.includes(skillId)
  const capOk = (panelId: string) => {
    const req = REQUIRES_BY_ID[panelId]
    return !req || hasCapability(req)
  }



  const [moving, setMoving] = useState(false)
  // Why the server refused a trip, in one player-facing sentence. An unknown
  // and an unplaced target read ALIKE on purpose: from inside the world
  // "I was never told about this place" and "this place is on no map" are the
  // same statement, and the server keeps them apart only in its log (the same
  // decision the SetLocation skill made for NPCs).
  const travelReason = useCallback((reason: string) => {
    switch (reason) {
      case 'unknown_target':
      case 'unplaced_target':
        return t('You do not know the way there.')
      case 'no_route':
        return t('There is no passable route — water, cliffs or walls block every way.')
      default:
        return t('You cannot travel there right now.')
    }
  }, [t])
  const handleTravel = useCallback(async (locationId: string) => {
    if (moving) return
    setMoving(true)
    try {
      const res = await apiPost<{ journey: { target_name: string } | null; reason: string }>(
        '/play/travel', { target_id: locationId })
      if (res?.journey) toast(`${t('On your way to')} ${res.journey.target_name}`)
      else toast(travelReason(res?.reason || ''), 'error')
      await load()
    } catch (e) {
      // 403 = a leave/enter rule blocked the trip → surface the rule's own
      // (already localized) sentence, so the player knows WHY.
      const err = e as ApiError
      const detail = err?.detail as { message?: string } | string | undefined
      const msg = typeof detail === 'string'
        ? detail
        : (detail && typeof detail === 'object' ? detail.message : undefined)
      if (msg) toast(msg, 'error')
    } finally { setMoving(false) }
  }, [moving, load, toast, t, travelReason])
  const handleCancelTravel = useCallback(async () => {
    if (moving) return
    setMoving(true)
    try { await apiPost('/play/travel/cancel', {}); await load() }
    catch (e) {
      const err = e as ApiError
      const detail = err?.detail as { message?: string } | string | undefined
      const msg = typeof detail === 'string'
        ? detail
        : (detail && typeof detail === 'object' ? detail.message : undefined)
      if (msg) toast(msg, 'error')
    } finally { setMoving(false) }
  }, [moving, load, toast])
  const handleEnterRoom = useCallback(async (roomId: string) => {
    if (moving) return
    setMoving(true)
    try { await apiPost('/play/enter-room', { room_id: roomId }); await load() }
    catch (e) {
      // A refusal (403 block rule, party follower, …) carries its reason in
      // the detail — show it, otherwise the click looks like it did nothing.
      const err = e as ApiError
      const detail = err?.detail as { message?: string } | string | undefined
      const msg = typeof detail === 'string'
        ? detail
        : (detail && typeof detail === 'object' ? detail.message : undefined)
      if (msg) toast(msg, 'error')
    } finally { setMoving(false) }
  }, [moving, load, toast])

  const present = data?.present || []
  // The Others panel is tied purely to presence: visible ⟺ someone else is
  // here. Deliberately INDEPENDENT of the open/saved layout (an old saved
  // layout would otherwise hide it) — auto on/off, no manual toggle.
  const hasOthers = present.length > 0
  // Who stands IN the room (the figures of the environment window) — the
  // header names them, not the earshot roster: a passer-by outside the walls
  // stays addressable (chips) but is not "here".
  const inRoom = (data?.present_detail || []).map((p) => p.name)
  // Bring it to the front when it appears so it never vanishes behind an
  // (overlapping, self-arranged) panel. Z-order only, no touch of `open`.
  useEffect(() => {
    if (hasOthers) {
      setOrder((o) => (o[o.length - 1] === 'others' ? o : [...o.filter((x) => x !== 'others'), 'others']))
    }
  }, [hasOthers])

  // Z-stacking for overlapping windows: the panel touched last comes last in
  // the DOM and is therefore in front. A click or drag brings a panel forward.
  const [order, setOrder] = useState<string[]>(['scene', 'env', 'map', 'tasks', 'self', 'others', 'belongings', 'journal', 'gallery', 'instagram', 'phone', 'news', 'settings', 'layouts'])
  const bringToFront = useCallback((id: string) => {
    setOrder((o) => (o[o.length - 1] === id ? o : [...o.filter((x) => x !== id), id]))
  }, [])
  const sendToBack = useCallback((id: string) => {
    setOrder((o) => (o[0] === id ? o : [id, ...o.filter((x) => x !== id)]))
  }, [])
  // RGL positions the panel div itself (position:absolute), so z-index takes
  // effect right here. The panel touched last (end of `order`) gets the
  // highest z-index.
  const zOf = (id: string) => 10 + Math.max(0, order.indexOf(id))

  const scenePanel = (
    <div key="scene" className="player-panel" style={{ zIndex: zOf('scene') }} onMouseDownCapture={() => bringToFront('scene')}>
          <div className="player-panel-head">
            {headIcon('scene')}
            {data?.avatar || '—'}
            <span className="sub">
              {inRoom.length ? `· ${inRoom.join(', ')}` : `· ${t('You are alone here.')}`}
            </span>
            {headerControls('scene', true)}
          </div>
          {/* photoDialog: the 📷 image-generation dialog belongs to the
              game-admin UI, not to the shared panel package — /play slots it
              in, the 3D HUD deliberately leaves it out. */}
          <ScenePanel data={data} refreshScene={refreshScene} avatar={data?.avatar || ''}
            hasCapability={hasCapability} moving={moving} onEnterRoom={handleEnterRoom}
            photoDialog={(ctl) => (
              <ImageGenDialog
                open
                title={t('Scene photo')}
                defaultPrompt={ctl.prompt}
                showRoomReference
                characterOptions={{ detected: ctl.subjects, available: ctl.available }}
                occasion="photo"
                occasionCharacter={data?.avatar || ''}
                onSubmit={ctl.onSubmit}
                onClose={ctl.onClose}
              />
            )} />
        </div>
  )

  const mapPanel = (
    <div key="map" className="player-panel" style={{ zIndex: zOf('map') }} onMouseDownCapture={() => bringToFront('map')}>
      <div className="player-panel-head">
        {headIcon('map')}
        {data?.room_name || data?.location_name || t('Travel')}
        {data?.location_name && data?.room_name
          ? <span className="sub">· {data.location_name}</span> : null}
        {headerControls('map', true)}
      </div>
      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden', padding: 8 }}>
        <TravelPanel
          rooms={data?.rooms || []}
          currentRoomId={data?.room_id || ''}
          currentLocationId={data?.location_id || ''}
          travel={data?.travel || null}
          busy={moving}
          blockedReason={data?.capability_blocks?.[data?.capability_actions?.travel || ''] || ''}
          onTravel={handleTravel}
          onCancelTravel={handleCancelTravel}
          onEnterRoom={handleEnterRoom}
          labelMode={mapLabelMode}
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

  const questsPanel = (
    <div key="quests" className="player-panel" style={{ zIndex: zOf('quests') }} onMouseDownCapture={() => bringToFront('quests')}>
      <div className="player-panel-head">{headIcon('quests')}{t('Quests')}{headerControls('quests', true)}</div>
      <div className="player-panel-body" style={{ padding: 0, overflow: 'hidden' }}>
        <QuestsPanel />
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
        {/* regenDialog: the regenerate image-generation dialog belongs to the
            game-admin UI, not to the shared panel package — /play slots it in,
            the 3D HUD deliberately leaves it out (no button there). */}
        <GalleryPanel regenDialog={(ctl) => (
          <ImageGenDialog
            open
            title={t('Regenerate image')}
            defaultPrompt={ctl.prompt}
            sourceImageUrl={ctl.sourceImageUrl}
            mode="regenerate"
            showRoomReference
            characterOptions={{ detected: ctl.detected, available: ctl.available }}
            occasion="regenerate"
            // Regenerate is only offered on the player's own avatar's images,
            // and the server routes with that owner as position 0.
            occasionCharacter={data?.avatar || ''}
            onSubmit={ctl.onSubmit}
            onClose={ctl.onClose}
          />
        )} />
      </div>
    </div>
  )

  const instagramPanel = (
    <div key="instagram" className="player-panel" style={{ zIndex: zOf('instagram') }} onMouseDownCapture={() => bringToFront('instagram')}>
      <div className="player-panel-head">{headIcon('instagram')}{t('Instagram')}{headerControls('instagram', true)}</div>
      <div className="player-panel-body" style={{ padding: 10, overflow: 'auto' }}>
        {/* imageGenDialog/animateDialog: both big dialogs of the regenerate and
            animate flows belong to the game-admin UI, not to the shared panel
            package — /play slots them in, the 3D HUD deliberately leaves them
            out (neither button is there). */}
        <InstagramPanel
          imageGenDialog={(ctl) => (
            <ImageGenDialog
              open
              title={t('Regenerate image')}
              defaultPrompt={ctl.prompt}
              sourceImageUrl={ctl.sourceImageUrl}
              mode="regenerate"
              showRoomReference
              characterOptions={{ detected: ctl.detected, available: ctl.available }}
              occasion="regenerate"
              onSubmit={ctl.onSubmit}
              onClose={ctl.onClose}
            />
          )}
          animateDialog={(ctl) => (
            <AnimateDialog
              open
              title={ctl.hasVideo ? t('Re-animate') : t('Animate image')}
              sourceImageUrl={ctl.sourceImageUrl}
              defaultPrompt={ctl.prompt}
              onSuggest={ctl.onSuggest}
              onSubmit={ctl.onSubmit}
              onClose={ctl.onClose}
            />
          )}
        />
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
    scene: scenePanel, env: envPanel, map: mapPanel,
    tasks: tasksPanel, self: selfPanel, others: othersPanel, belongings: belongingsPanel,
    journal: journalPanel, gallery: galleryPanel, instagram: instagramPanel, phone: phonePanel,
    news: newsPanel, quests: questsPanel, settings: settingsPanel,
  }

  // Derive columns from measured width: colWidth ≈ CELL gives square cells.
  const cols = Math.max(1, Math.floor((width + MARGIN) / (CELL + MARGIN)))
  // Always include a layout item for every panel so reopened panels
  // cannot fall back to a tiny 1×1 box.
  const known = new Set(layout.map((l) => l.i))
  const fullLayout = DEFAULT_LAYOUT.some((d) => !known.has(d.i))
    ? [...layout, ...DEFAULT_LAYOUT.filter((d) => !known.has(d.i))]
    : layout
  // Guard against 0×0/1×1 defaults assigned to newly mounted panels by RGL.
  // onLayoutChange could otherwise persist those tiny boxes.
  // Restore default size below the minimum; preserve larger manual sizes.
  const sizedLayout = fullLayout.map((l) => {
    const def = DEFAULT_BY_ID[l.i]
    if (!def) return l
    if (!l.w || !l.h || l.w < (def.minW ?? 2) || l.h < (def.minH ?? 2)) {
      return { ...l, w: def.w, h: def.h }
    }
    return l
  })
  // Render open panels; 'others' additionally requires somebody present.
  // It remains in the open set, appearing automatically when others arrive
  // or the location changes, and disappearing when the avatar is alone.
  const renderedIds = GRID_PANELS.filter(
    (id) => byId[id] && open.includes(id) && id !== bgPanel
      && (id !== 'others' || hasOthers) && capOk(id))
  // The highest z-index panel is active: accent header stripe and stronger
  // shadow identify the frontmost panel.
  const frontId = renderedIds.reduce<string | undefined>(
    (a, b) => (a == null || zOf(b) >= zOf(a) ? b : a), undefined)
  // Frozen grids use reference width and columns, transformed to actual width.
  // Give the wrapper the scaled height for correct scrolling and pass
  // transformScale to RGL for correct drag/resize calculations.
  // Unfrozen grids use responsive columns.
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
  // Remount GridLayout when panels open or close so RGL rebuilds its state
  // from layout instead of reopening as 1×1. Dragging and bringing to front
  // preserve open and therefore avoid remounts and snap-backs.
  const openKey = [...renderedIds].sort().join('|')

  // Autosize measures each enabled, rendered panel’s natural content height
  // and writes grid rows (h). CSS data-autosize makes offsetHeight reflect
  // content height; ResizeObserver refits after content changes.
  // Width remains unchanged.
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
      // Zoom can change reported content size without resizing the body.
      // Observe data-content-w/h mutations as well, so autosize follows zoom.
      const mo = new MutationObserver(() => apply(id))
      mo.observe(body, { attributes: true, subtree: true,
        attributeFilter: ['data-content-w', 'data-content-h'] })
      apply(id)  // Initial measurement.
      return [ro, mo]
    })
    return () => observers.forEach((o) => o.disconnect())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autosizeKey, openKey, persist])

  // --- Toolbar (Launcher) -------------------------------------------------
  const tbBtn = (id: string, label: string, icon: IconName, isOpen: boolean, onClick: () => void, badge = 0, bg = false) => {
    // Background Surroundings retains its accent appearance.
    const col = bg ? '' : PANEL_COLOR[id]
    return (
      <button key={id} onClick={onClick} title={t(label)} aria-label={t(label)} aria-pressed={isOpen}
        className={`play-tbtn${isOpen ? ' open' : ''}${bg ? ' bg' : ''}${iconMode === 'iconText' ? ' with-text' : ''}`}
        style={{
          position: 'relative',
          // Duotone: filled accent chip and line icon in the panel colour.
          // Active buttons use a stronger fill and border.
          ...(col ? { color: col, background: col + (isOpen ? '40' : '20') } : {}),
          ...(isOpen && col ? { borderColor: col } : {}),
        }}>
        <Icon name={icon} size={15} />
        {iconMode === 'iconText' && <span className="play-tbtn-label">{t(label)}</span>}
        {badge > 0 && <span className="play-tbtn-badge">{badge > 99 ? '99+' : badge}</span>}
      </button>
    )
  }
  // Per-panel badges: unread phone messages and new Instagram posts.
  const badgeOf = (id: string) => (id === 'phone' ? phoneUnread : id === 'instagram' ? igNew : 0)
  // Panel toggles follow toolbar position and label preferences. Layouts,
  // Reset and Settings stay fixed on the right.
  const panelToggles = PANEL_META
    .filter((p) => p.kind !== 'dialog')
    .filter((p) => p.id !== 'others' || hasOthers)
    .filter((p) => capOk(p.id))  // skill-bound panels only with capability
    .filter((p) => p.id !== 'tasks')  // Monitoring belongs to the right tool cluster.
    .map((p) => {
      // Background Surroundings has a distinct button; clicking restores
      // its normal panel state.
      if (p.id === bgPanel) {
        return tbBtn(p.id, 'Restore from background', p.icon, true, clearBackground, 0, true)
      }
      return tbBtn(p.id, p.label, p.icon, open.includes(p.id), () => togglePanel(p.id), badgeOf(p.id))
    })
  const layoutsMeta = PANEL_META.find((p) => p.id === 'layouts')!
  const fixedCluster = (
    <>
      <GameClock readOnly showSystem={false} />
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

      {/* Dialog panels as a centred overlay */}
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

    {/* The enlarged panel — a portal to document.body, so the position:fixed
        overlay escapes the react-grid-layout transform. NOT view-only any
        more: the travel panel shown here carries its actions (Travel, cancel
        journey, room change), because a map is only worth enlarging if one
        can also set off from it. */}
    {expanded && createPortal(
      <div onClick={() => setExpanded(null)}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.72)', zIndex: 2000,
                 display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3vh 3vw' }}>
        <div onClick={(e) => e.stopPropagation()} className="player-panel"
          style={{ width: '94vw', height: '94vh', display: 'flex', flexDirection: 'column' }}>
          <div className="player-panel-head">
            {headIcon(expanded)}{t(LABEL_BY_ID[expanded] || 'Travel')}
            <span className="player-head-ctrls">
              {expanded === 'map' && (
                <button className={`player-ctrl-btn${mapLabelMode !== 'all' ? ' on' : ''}`}
                  onClick={cycleMapLabel}
                  title={`${t('Map labels')}: ${mapLabelMode === 'all' ? t('all') : t('off')}`}
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
