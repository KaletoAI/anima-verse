/**
 * IsoMapPanel — isometrische 2.5D-Weltkarte (read-only) im Player-UI.
 * Eigenes Fenster ZUSÄTZLICH zur flachen 2D-Karte (MapPanel). Portiert aus der
 * alten worldmap: Iso-Tiles mit Map-Icons + Z-Order (map_z_offset), Character-
 * Avatare am Ort (inkl. „unterwegs"-Badge), Event-Pins (disruption/danger) und
 * ein Tray für heimatlose/schlafende Characters. Pan (Ziehen auf leerer Fläche)
 * + Zoom (Mausrad Richtung Cursor); Zoom & Verschiebung werden in localStorage
 * gespeichert und beim erneuten Öffnen wiederhergestellt. Bewegung bleibt im
 * Move-Pad — die Karte ist nur Anzeige.
 * Reuse der worldmap-* Klassen aus /static/themes/base.css.
 * Quelle: GET /play/worldmap (aggregiert).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

const COLS = 10
const ROWS = 10
const TILE_W = 180
const TILE_H = 90
const VIEW_KEY = 'anima.isomap.view'

interface WLoc {
  id: string; name: string; grid_x?: number | null; grid_y?: number | null
  passable: boolean; template_location_id: string; map_z_offset: number
}
interface WChar {
  name: string; location_id: string; activity: string
  movement_target_id: string; movement_target_name: string; avatar_url: string
}
interface WEvent { category: string; text: string }
interface WorldMap {
  avatar: string; current_location_id: string
  locations: WLoc[]; characters: WChar[]; events_by_location: Record<string, WEvent[]>
}

interface View { zoom: number; sx: number; sy: number }
function loadView(): View | null {
  try {
    const raw = localStorage.getItem(VIEW_KEY)
    if (!raw) return null
    const v = JSON.parse(raw)
    if (v && typeof v.zoom === 'number') return v
  } catch { /* ignore */ }
  return null
}

// Avatar image with a first-letter fallback when no profile image exists.
function Avatar({ c }: { c: WChar }) {
  const [fail, setFail] = useState(false)
  if (!c.avatar_url || fail) {
    return (
      <span className="worldmap-avatar" style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--accent, #2f81f7)', color: '#fff', fontSize: 11, fontWeight: 600,
      }}>{c.name.charAt(0).toUpperCase()}</span>
    )
  }
  return <img className="worldmap-avatar" src={c.avatar_url} alt={c.name} onError={() => setFail(true)} />
}

function CellContent({ loc, isActive, chars, events, travellingTo }: {
  loc: WLoc; isActive: boolean; chars: WChar[]; events: WEvent[]; travellingTo: string
}) {
  const [imgFail, setImgFail] = useState(false)
  const hasDanger = events.some((e) => e.category === 'danger')
  const tooltip = events.map((e) => `${(e.category || '').toUpperCase()}: ${e.text || ''}`).join('\n')
  return (
    <>
      <div className="worldmap-cell-content">
        {!imgFail ? (
          <img className="worldmap-map-bg" src={`/world/locations/${encodeURIComponent(loc.id)}/map-icon`}
            alt="" onError={() => setImgFail(true)} />
        ) : (
          <div className="worldmap-cell-emoji">{isActive ? '📍' : '🏠'}</div>
        )}
      </div>
      <div className="worldmap-cell-name">{loc.name}</div>
      {events.length > 0 ? (
        <div className={`worldmap-event-pin ${hasDanger ? 'worldmap-event-pin-danger' : 'worldmap-event-pin-disruption'}`}
          title={tooltip}>
          {hasDanger ? '🔥' : '❗'}
          {events.length > 1 ? <span className="worldmap-event-count">{events.length}</span> : null}
        </div>
      ) : null}
      {chars.length > 0 ? (
        <div className="worldmap-cell-avatars">
          {chars.map((c) => {
            const traveling = !!c.movement_target_id && c.movement_target_id !== loc.id
            const title = c.name + (traveling
              ? ` — ${travellingTo} ${c.movement_target_name || c.movement_target_id}` : '')
            return (
              <span key={c.name} className={traveling ? 'worldmap-avatar-wrap traveling' : 'worldmap-avatar-wrap'}
                title={title}>
                <Avatar c={c} />
                {traveling ? <span className="worldmap-travel-badge">🚶</span> : null}
              </span>
            )
          })}
        </div>
      ) : null}
    </>
  )
}

export function IsoMapPanel({ currentLocationId }: { currentLocationId: string }) {
  const { t } = useI18n()
  const [data, setData] = useState<WorldMap | null>(null)
  const savedRef = useRef<View | null>(loadView())
  const [zoom, setZoom] = useState(savedRef.current?.zoom ?? 1)
  const zoomRef = useRef(zoom)
  const containerRef = useRef<HTMLDivElement>(null)
  const restoredRef = useRef(false)
  const panRef = useRef({ on: false, sx: 0, sy: 0, scx: 0, scy: 0 })

  // Persist zoom + scroll offset so the view is restored next time.
  const persist = useCallback(() => {
    const c = containerRef.current
    if (!c) return
    try {
      localStorage.setItem(VIEW_KEY, JSON.stringify({ zoom: zoomRef.current, sx: c.scrollLeft, sy: c.scrollTop }))
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try { const d = await apiGet<WorldMap>('/play/worldmap'); if (alive) setData(d) } catch { /* ignore */ }
    }
    tick()
    const id = setInterval(tick, 10000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  useEffect(() => { zoomRef.current = zoom; persist() }, [zoom, persist])

  // Drag-to-pan on empty tiles (occupied cells are skipped).
  useEffect(() => {
    const move = (e: MouseEvent) => {
      const p = panRef.current
      const c = containerRef.current
      if (!p.on || !c) return
      e.preventDefault()
      c.scrollLeft = p.scx - (e.clientX - p.sx)
      c.scrollTop = p.scy - (e.clientY - p.sy)
    }
    const up = () => {
      panRef.current.on = false
      if (containerRef.current) containerRef.current.style.cursor = ''
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    window.addEventListener('blur', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      window.removeEventListener('blur', up)
    }
  }, [])

  // Persist scroll position (throttled via rAF) — covers pan and wheel scroll.
  useEffect(() => {
    const c = containerRef.current
    if (!c) return
    let raf = 0
    const onScroll = () => {
      if (raf) return
      raf = requestAnimationFrame(() => { raf = 0; persist() })
    }
    c.addEventListener('scroll', onScroll, { passive: true })
    return () => { c.removeEventListener('scroll', onScroll); if (raf) cancelAnimationFrame(raf) }
  }, [data, persist])

  // Wheel zoom toward cursor — native non-passive listener so preventDefault works.
  useEffect(() => {
    const c = containerRef.current
    if (!c) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const delta = e.deltaY > 0 ? -0.1 : 0.1
      setZoom((z) => {
        const nz = Math.min(3, Math.max(0.3, z + delta))
        if (nz === z) return z
        const rect = c.getBoundingClientRect()
        const mx = e.clientX - rect.left + c.scrollLeft
        const my = e.clientY - rect.top + c.scrollTop
        const ratio = nz / z
        requestAnimationFrame(() => {
          c.scrollLeft = mx * ratio - (e.clientX - rect.left)
          c.scrollTop = my * ratio - (e.clientY - rect.top)
        })
        return nz
      })
    }
    c.addEventListener('wheel', onWheel, { passive: false })
    return () => c.removeEventListener('wheel', onWheel)
  }, [data])

  // Restore saved scroll once after first load, else center the iso grid.
  useEffect(() => {
    if (!data || restoredRef.current) return
    restoredRef.current = true
    requestAnimationFrame(() => {
      const c = containerRef.current
      if (!c) return
      const s = savedRef.current
      if (s && (s.sx || s.sy)) {
        c.scrollLeft = s.sx
        c.scrollTop = s.sy
      } else {
        c.scrollLeft = (c.scrollWidth - c.clientWidth) / 2
        c.scrollTop = (c.scrollHeight - c.clientHeight) / 2
      }
    })
  }, [data])

  const current = currentLocationId || data?.current_location_id || ''

  const offsetX = (ROWS - 1) * (TILE_W / 2)
  const totalW = (COLS + ROWS - 1) * (TILE_W / 2) + TILE_W
  const totalH = (COLS + ROWS - 1) * (TILE_H / 2) + TILE_H + 60

  const travellingTo = t('travelling to')
  const { cells, homeless, sleeping } = useMemo(() => {
    if (!data) return { cells: [] as ReactElement[], homeless: [] as WChar[], sleeping: [] as WChar[] }
    const placed: Record<string, WLoc> = {}
    for (const loc of data.locations) {
      if (loc.passable && !(loc.template_location_id || '').trim()) continue
      if (loc.grid_x != null && loc.grid_y != null && loc.grid_x >= 0 && loc.grid_y >= 0) {
        placed[`${loc.grid_x},${loc.grid_y}`] = loc
      }
    }
    const charsAt = (id: string) => data.characters.filter((c) => c.location_id === id)
    const cellEls: ReactElement[] = []
    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        const loc = placed[`${x},${y}`]
        const isActive = !!loc && loc.id === current
        const left = (x - y) * (TILE_W / 2) + offsetX
        const top = (x + y) * (TILE_H / 2)
        const zIdx = (x + y) * (COLS + 1) + y + (loc?.map_z_offset || 0) * 10000
        const cls = ['worldmap-grid-cell']
        if (loc) cls.push('occupied')
        if (isActive) cls.push('worldmap-tile-active')
        if (loc?.passable) cls.push('worldmap-tile-passable')
        cellEls.push(
          <div key={`${x},${y}`} className={cls.join(' ')} style={{ left, top, zIndex: zIdx }}>
            {loc ? (
              <CellContent loc={loc} isActive={isActive} chars={charsAt(loc.id)}
                events={data.events_by_location[loc.id] || []} travellingTo={travellingTo} />
            ) : null}
          </div>,
        )
      }
    }
    const locIds = new Set(data.locations.map((l) => l.id))
    const isSleeping = (c: WChar) => !c.location_id && (c.activity || '').toLowerCase() === 'sleeping'
    const sleepingChars = data.characters.filter(isSleeping)
    const homelessChars = data.characters.filter(
      (c) => !isSleeping(c) && (!c.location_id || !locIds.has(c.location_id)),
    )
    return { cells: cellEls, homeless: homelessChars, sleeping: sleepingChars }
  }, [data, current, offsetX, travellingTo])

  if (!data) return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('Loading…')}</div>
  if (!data.locations.length && !data.characters.length) {
    return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No map positions yet.')}</div>
  }

  const onDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    if ((e.target as HTMLElement).closest('.worldmap-grid-cell.occupied')) return
    const c = containerRef.current
    if (!c) return
    e.preventDefault()
    panRef.current = { on: true, sx: e.clientX, sy: e.clientY, scx: c.scrollLeft, scy: c.scrollTop }
    c.style.cursor = 'grabbing'
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div className="worldmap-grid-container" ref={containerRef} onMouseDown={onDown} style={{ cursor: 'grab' }}>
        <div className="worldmap-iso-wrapper"
          style={{ width: totalW, height: totalH, transform: `scale(${zoom})` }}>
          <div className="worldmap-spatial-grid" style={{ width: totalW, height: totalH }}>
            {cells}
          </div>
        </div>
      </div>

      {homeless.length > 0 || sleeping.length > 0 ? (
        <div className="worldmap-tray">
          {homeless.length > 0 ? (
            <div className="worldmap-homeless">
              <div className="worldmap-homeless-title">{t('No location')}</div>
              <div className="worldmap-homeless-list">
                {homeless.map((c) => (
                  <div key={c.name} className="worldmap-homeless-btn" title={c.name}>
                    <Avatar c={c} /><span>{c.name}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {sleeping.length > 0 ? (
            <div className="worldmap-homeless worldmap-sleeping">
              <div className="worldmap-homeless-title">🌙 {t('Sleeping (off-map)')}</div>
              <div className="worldmap-homeless-list">
                {sleeping.map((c) => (
                  <div key={c.name} className="worldmap-homeless-btn worldmap-sleeping-btn" title={c.name}>
                    <Avatar c={c} /><span>{c.name}</span><span className="worldmap-sleep-badge">💤</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
