/**
 * MapPanel — flache 2D-Weltkarte (read-only) im Player-UI, das einzige
 * Karten-Panel. Zeigt das flache Grid (2D-Tile + Per-Zell-Rotation, Highlight
 * des aktuellen Orts) und
 * darüber die Live-Infos aus /play/worldmap: Character-Avatare am Ort (inkl.
 * „unterwegs"-Badge), Event-Pins (disruption/danger) und ein Tray für heimat-
 * lose + schlafende Characters. Pan (Ziehen auf leerer Fläche) + Zoom (Mausrad
 * Richtung Cursor), in localStorage gespeichert. Bewegung bleibt im Move-Pad.
 * Reuse der layout-neutralen worldmap-* Klassen aus /static/themes/base.css.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

const CELL = 72
const GAP = 4
const PAD = 6
const VIEW_KEY = 'anima.map2d.view'

interface WLoc {
  id: string; name: string; grid_x?: number | null; grid_y?: number | null
  passable: boolean; template_location_id: string; map_rotation_2d?: number
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

// Flat 2D map tile, hidden if none exists. The per-cell 90° rotation is a
// display-only transform.
function MapIcon({ loc }: { loc: WLoc }) {
  const [hidden, setHidden] = useState(false)
  if (hidden) return null
  const rot = loc.map_rotation_2d || 0
  return (
    <img src={`/world/locations/${encodeURIComponent(loc.id)}/map-icon-2d`}
      alt={loc.name} onError={() => setHidden(true)}
      style={{
        position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover',
        transform: rot ? `rotate(${rot}deg)` : undefined,
      }} />
  )
}

function Cell({ loc, isActive, chars, events, travellingTo }: {
  loc: WLoc; isActive: boolean; chars: WChar[]; events: WEvent[]; travellingTo: string
}) {
  const hasDanger = events.some((e) => e.category === 'danger')
  const tooltip = events.map((e) => `${(e.category || '').toUpperCase()}: ${e.text || ''}`).join('\n')
  return (
    <div style={{
      width: CELL, height: CELL, borderRadius: 6, position: 'relative', overflow: 'visible',
      border: isActive ? '2px solid var(--accent, #6aa9ff)' : '1px solid var(--border, #30363d)',
      background: 'var(--bg, #0d1117)', opacity: loc.passable ? 0.85 : 1,
    }} title={loc.name}>
      <div style={{ position: 'absolute', inset: 0, borderRadius: 6, overflow: 'hidden' }}>
        <MapIcon loc={loc} />
      </div>
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0, fontSize: '0.6em',
        textAlign: 'center', background: 'rgba(0,0,0,0.55)', color: '#fff',
        padding: '1px 2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        fontStyle: loc.passable ? 'italic' : 'normal', borderRadius: '0 0 6px 6px',
      }}>{loc.name}</div>
      {isActive ? <div style={{ position: 'absolute', top: 1, right: 2, fontSize: '0.8em', zIndex: 5 }}>📍</div> : null}
      {events.length > 0 ? (
        <div className={`worldmap-event-pin ${hasDanger ? 'worldmap-event-pin-danger' : 'worldmap-event-pin-disruption'}`}
          title={tooltip} style={{ fontSize: 12 }}>
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
    </div>
  )
}

export function MapPanel({ currentLocationId, autoFit = false }:
  { currentLocationId: string; autoFit?: boolean }) {
  const { t } = useI18n()
  const [data, setData] = useState<WorldMap | null>(null)
  // autoFit (vergrößertes Overlay): gespeicherte Ansicht ignorieren, stattdessen
  // die Karte in den Container einpassen — und NICHT zurückschreiben.
  const savedRef = useRef<View | null>(autoFit ? null : loadView())
  const [zoom, setZoom] = useState(savedRef.current?.zoom ?? 1)
  const zoomRef = useRef(zoom)
  const containerRef = useRef<HTMLDivElement>(null)
  const restoredRef = useRef(false)
  const panRef = useRef({ on: false, sx: 0, sy: 0, scx: 0, scy: 0 })

  // Persist zoom + scroll offset so the view is restored next time.
  const persist = useCallback(() => {
    if (autoFit) return  // Overlay-Instanz darf die gespeicherte Panel-Ansicht nicht überschreiben
    const c = containerRef.current
    if (!c) return
    try {
      localStorage.setItem(VIEW_KEY, JSON.stringify({ zoom: zoomRef.current, sx: c.scrollLeft, sy: c.scrollTop }))
    } catch { /* ignore */ }
  }, [autoFit])

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

  // Drag-to-pan on empty area (cells stop propagation? no — pan anywhere except
  // when starting on an avatar/pin which have their own pointer handling).
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

  const current = currentLocationId || data?.current_location_id || ''
  const travellingTo = t('travelling to')

  const { cells, gridW, gridH, homeless, sleeping } = useMemo(() => {
    const empty = { cells: null as React.ReactNode, gridW: 0, gridH: 0, homeless: [] as WChar[], sleeping: [] as WChar[] }
    if (!data) return empty
    // Placed = echte Orte + platzierte Klone passierbarer Templates (keine
    // unplatzierten Terrain-Definitionen).
    const placed: WLoc[] = data.locations.filter((l) =>
      l.grid_x != null && l.grid_y != null && (l.grid_x as number) >= 0 && (l.grid_y as number) >= 0 &&
      !(l.passable && !(l.template_location_id || '').trim()))
    if (!placed.length) return empty
    const xs = placed.map((l) => l.grid_x as number)
    const ys = placed.map((l) => l.grid_y as number)
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const cols = maxX - minX + 1
    const rows = maxY - minY + 1
    const byCell = new Map<string, WLoc>()
    placed.forEach((l) => byCell.set(`${l.grid_x},${l.grid_y}`, l))
    const charsAt = (id: string) => data.characters.filter((c) => c.location_id === id)

    const els: React.ReactNode[] = []
    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        const l = byCell.get(`${x},${y}`)
        if (!l) {
          els.push(<div key={`${x},${y}`} style={{ width: CELL, height: CELL, opacity: 0.12 }} />)
          continue
        }
        els.push(
          <Cell key={`${x},${y}`} loc={l} isActive={l.id === current}
            chars={charsAt(l.id)} events={data.events_by_location[l.id] || []} travellingTo={travellingTo} />,
        )
      }
    }
    const grid = (
      <div style={{
        display: 'grid', gridTemplateColumns: `repeat(${cols}, ${CELL}px)`,
        gap: GAP, padding: PAD,
      }}>{els}</div>
    )
    const gW = cols * CELL + (cols - 1) * GAP + PAD * 2
    const gH = rows * CELL + (rows - 1) * GAP + PAD * 2

    const locIds = new Set(data.locations.map((l) => l.id))
    const isSleeping = (c: WChar) => !c.location_id && (c.activity || '').toLowerCase() === 'sleeping'
    const sleepingChars = data.characters.filter(isSleeping)
    const homelessChars = data.characters.filter(
      (c) => !isSleeping(c) && (!c.location_id || !locIds.has(c.location_id)),
    )
    return { cells: grid, gridW: gW, gridH: gH, homeless: homelessChars, sleeping: sleepingChars }
  }, [data, current, travellingTo])

  // Restore saved scroll once after first load, else center the grid.
  useEffect(() => {
    if (!data || !gridW || restoredRef.current) return
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
  }, [data, gridW])

  // autoFit: Karte in den Container einpassen (und bei Resize nachführen), damit
  // sie im vergrößerten Overlay wirklich größer wird statt nur mehr Leerraum.
  useEffect(() => {
    if (!autoFit || !gridW || !gridH) return
    const fit = () => {
      const c = containerRef.current
      if (!c || !c.clientWidth || !c.clientHeight) return
      const z = Math.min(c.clientWidth / gridW, c.clientHeight / gridH)
      if (!isFinite(z) || z <= 0) return
      setZoom(Math.max(0.2, Math.min(z * 0.98, 6)))
      requestAnimationFrame(() => {
        const cc = containerRef.current
        if (!cc) return
        cc.scrollLeft = (cc.scrollWidth - cc.clientWidth) / 2
        cc.scrollTop = (cc.scrollHeight - cc.clientHeight) / 2
      })
    }
    fit()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(fit) : null
    if (ro && containerRef.current) ro.observe(containerRef.current)
    return () => ro?.disconnect()
  }, [autoFit, gridW, gridH])

  if (!data) return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('Loading…')}</div>
  if (!gridW && !data.characters.length) {
    return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No map positions yet.')}</div>
  }

  const onDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    const c = containerRef.current
    if (!c) return
    panRef.current = { on: true, sx: e.clientX, sy: e.clientY, scx: c.scrollLeft, scy: c.scrollTop }
    c.style.cursor = 'grabbing'
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div ref={containerRef} onMouseDown={onDown}
        style={{ flex: 1, minHeight: 0, overflow: 'auto', cursor: 'grab' }}>
        <div style={{ width: gridW * zoom, height: gridH * zoom }}>
          <div style={{ width: gridW, height: gridH, transformOrigin: '0 0', transform: `scale(${zoom})` }}>
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
