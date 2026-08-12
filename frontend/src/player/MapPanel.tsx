/**
 * MapPanel — the player's SCHEMATIC map of the metre world (read-only).
 *
 * The tile grid is gone (contract § A1). The world is one continuous plane in
 * metres, so this panel draws exactly what the two metre payloads say and
 * decides no geometry of its own:
 *   - `GET /play/worldmap` (§ A1.3/§ A11/§ A12) — locations with their metre
 *     position, yaw and footprint edge, characters with their metre `pos` and
 *     their running journey, the events per location, `world_bounds` and the
 *     terrain signature.
 *   - `GET /play/terrain` (§ A1.5) — the painted ground: the type catalog with
 *     its colours plus the areas, bottom-to-top. Never fogged.
 *
 * The drawing surface is the map editor's `MapCanvas`: it owns the two
 * gestures (cursor-anchored wheel zoom via `zoomAt`, pan by dragging), the
 * metre grid and the scale bar with the 1.70 m figure. Reusing it is the point
 * — a second pan/zoom implementation would drift away from the first, exactly
 * as the clip shader once did. Everything above it is a layer of this file,
 * bottom to top:
 *   1. `GroundLayer`   — the unpainted ground in the `default_kind` colour,
 *                        `world_bounds` plus 40 m of air, so the edge of the
 *                        world is visible as an edge.
 *   2. `TerrainAreas`  — `terrain.areas` in delivered order (= z-order),
 *                        colour from the catalog (`typeColor`, grey when the
 *                        kind is unknown), even-odd like the editor.
 *   3. `Footprints`    — the location squares in REAL size via
 *                        `footprintScreenCorners`, name label by label mode,
 *                        📍 on the avatar's location, 🔥/❗ event pin.
 *   4. `TravelLines`   — the REST of a journey, dashed (avatar only under fog:
 *                        `waypoints` is null for everyone else, § A12).
 *   5. `Characters`    — every character with a `pos` (in a location or out in
 *                        the wilderness), the avatar bigger and in the accent
 *                        colour, foreign faces only once the zoom can carry
 *                        them.
 * No game action lives here: travelling is the TravelPanel's job.
 *
 * Fills are translucent (55 %) because the canvas draws its metre grid BEFORE
 * its children — an opaque ground would swallow the scale aids.
 *
 * Two numbers this panel is pinned to (§ B5a — arithmetic, not screenshots):
 *
 *   SCALE BAR (drawn by `MapCanvas.MapMeasureLegend`, kept honest here):
 *     bar metres = niceDown(140 / pxPerM), drawn length = bar × pxPerM px in
 *     four equal segments.
 *       pxPerM 2   -> 140/2 = 70 m -> niceDown = 50 m -> 100 px, segments 25 px
 *       pxPerM 0.5 -> 280 m       -> niceDown = 200 m -> 100 px, segments 25 px
 *       pxPerM 20  -> 7 m         -> niceDown = 5 m  -> 100 px, segments 25 px
 *     (the nice values are 0.25/0.5/1/2/5/10/20/50/100/200/500 m, so the bar
 *     lands between 70 and 140 px at every zoom.)
 *
 *   FOOT POINT of a travel line (`nearestOnPolyline`, hand-derived there):
 *     route [(0,0), (10,0), (10,10)], the server reports the walker at
 *     `pos` (4, 1). Segment 0 has direction (10,0) and |d|² = 100, so
 *     t = (4·10 + 1·0)/100 = 0.4 -> foot (4,0), distance 1 m; segment 1 gives
 *     foot (10,1) at distance 6 m. Segment 0 wins, and the drawn rest is
 *     [(4,0), (10,0), (10,10)] — the line starts under the figure and ends at
 *     the target, never behind the walker.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { useAuth } from '../lib/AuthGate'
import { apiGet } from '../lib/api'
import { usePoll } from './usePolling'
import { MapCanvas, useMapView } from '../tabs/map/MapCanvas'
import { typeColor } from '../tabs/map/TerrainLayer'
import {
  FIT_FALLBACK_PX_PER_M, fitBounds, footprintScreenCorners, nearestOnPolyline,
  worldPolyToPath, worldToScreen, type MapBounds, type View,
} from '../tabs/map/mapMath'
import type {
  TerrainArea, TerrainPayload, TerrainType, WorldmapCharacter,
  WorldmapLocationRow, WorldmapPayload,
} from '../tabs/map/mapTypes'

/** View persistence. NEW key: the old one carried grid semantics (zoom plus a
 *  scroll offset in cell pixels) and means nothing on a metre plane. */
const VIEW_KEY = 'anima.map2d.v2.view'
const LABELS_KEY = 'anima.map2d.labels'

/** Air around `world_bounds` the ground is painted over, in metres. */
const GROUND_MARGIN_M = 40
/** One opacity for every fill — the canvas' metre grid must read through. */
const FILL_OPACITY = 0.55
/** From this zoom on a foreign character gets its face; below it the map
 *  would be a wall of portraits at world zoom. */
const CHIP_MIN_PX_PER_M = 2
/** Radius of a character dot in px (the avatar's, and everyone else's). */
const DOT_R_AVATAR = 6
const DOT_R_OTHER = 4

const COL_ACCENT = '#6aa9ff'
const COL_STONE = '#8b949e'
const COL_TEXT = '#f0f6fc'
const COL_DARK = '#0d1117'

// Size of the panel's own header row (admin checkbox + fit button).
const HEAD_H = 24

// Label display: all / only unique / none. "Unique" = not passable, i.e. named
// single places; transit elements (a road, a district) drop out. The mode is
// held in PlayerApp (button in the panel header) and only applied here; the
// persistence helpers are exported with it.
export type LabelMode = 'all' | 'unique' | 'none'
const LABEL_CYCLE: LabelMode[] = ['all', 'unique', 'none']
export function loadLabelMode(): LabelMode {
  try {
    const v = localStorage.getItem(LABELS_KEY)
    if (v === 'all' || v === 'unique' || v === 'none') return v
  } catch { /* ignore */ }
  return 'all'
}
export function nextLabelMode(m: LabelMode): LabelMode {
  return LABEL_CYCLE[(LABEL_CYCLE.indexOf(m) + 1) % LABEL_CYCLE.length]
}
export function saveLabelMode(m: LabelMode): void {
  try { localStorage.setItem(LABELS_KEY, m) } catch { /* ignore */ }
}

/** The stored view, or null when there is none (or it is not a view). */
function loadView(): View | null {
  try {
    const raw = localStorage.getItem(VIEW_KEY)
    if (!raw) return null
    const v = JSON.parse(raw)
    if (v && typeof v.cx === 'number' && typeof v.cz === 'number'
      && typeof v.pxPerM === 'number' && v.pxPerM > 0) {
      return { cx: v.cx, cz: v.cz, pxPerM: v.pxPerM }
    }
  } catch { /* ignore */ }
  return null
}

function saveView(v: View): void {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify(v)) } catch { /* ignore */ }
}

/** Layer 1 — the unpainted ground: the world box plus 40 m of air. Outside it
 *  the canvas background stays bare, which is what "here the world ends"
 *  looks like. Empty until the terrain catalog has answered. */
function GroundLayer({ bounds, color }: { bounds: MapBounds | null; color: string }) {
  const { view, w, h } = useMapView()
  if (!bounds || !color) return null
  const a = worldToScreen(bounds.min_x - GROUND_MARGIN_M,
    bounds.min_z - GROUND_MARGIN_M, view, w, h)
  const b = worldToScreen(bounds.max_x + GROUND_MARGIN_M,
    bounds.max_z + GROUND_MARGIN_M, view, w, h)
  return (
    <rect x={a.x} y={a.y} width={Math.max(0, b.x - a.x)} height={Math.max(0, b.y - a.y)}
      fill={color} fillOpacity={FILL_OPACITY} pointerEvents="none" />
  )
}

/** Layer 2 — the painted areas, in the order the server sent them (bottom to
 *  top). Even-odd, like the editor and like the server's point query. */
function TerrainAreas({ areas, types }: {
  areas: TerrainArea[]
  types: Record<string, TerrainType>
}) {
  const { view, w, h } = useMapView()
  return (
    <g pointerEvents="none">
      {areas.map((a) => (a.polygon.length >= 3 ? (
        <path key={a.id} d={worldPolyToPath(a.polygon, view, w, h)}
          fill={typeColor(types, (a.kind || '').toLowerCase())}
          fillOpacity={FILL_OPACITY} fillRule="evenodd" />
      ) : null))}
    </g>
  )
}

/** Layer 3 — the location squares in real size, plus label, position pin and
 *  event pin. A location without a metre position or without a scale anchor
 *  has NO area (§ A1.1) and is not drawn. */
function Footprints({ locations, currentId, events, labelMode }: {
  locations: WorldmapLocationRow[]
  currentId: string
  events: Record<string, Array<{ category: string; text: string }>>
  labelMode: LabelMode
}) {
  const { view, w, h } = useMapView()
  return (
    <g>
      {locations.map((loc) => {
        const corners = footprintScreenCorners(loc, view, w, h)
        if (!corners) return null
        const here = loc.id === currentId
        const evs = events[loc.id] || []
        const danger = evs.some((e) => e.category === 'danger')
        const pts = corners.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
        const minX = Math.min(...corners.map((p) => p.x))
        const maxX = Math.max(...corners.map((p) => p.x))
        const minY = Math.min(...corners.map((p) => p.y))
        const maxY = Math.max(...corners.map((p) => p.y))
        const cx = (minX + maxX) / 2
        const showLabel = labelMode === 'all'
          || (labelMode === 'unique' && !loc.passable)
        return (
          <g key={loc.id}>
            <polygon points={pts}
              fill={here ? COL_ACCENT : COL_STONE}
              fillOpacity={here ? 0.35 : loc.passable ? 0.12 : 0.28}
              stroke={here ? COL_ACCENT : COL_STONE} strokeWidth={1}
              strokeOpacity={here ? 1 : 0.7}
              strokeDasharray={loc.passable ? '5 4' : undefined}>
              <title>{loc.name}</title>
            </polygon>
            {showLabel ? (
              <text x={cx} y={maxY + 11} fontSize={10} textAnchor="middle"
                fill={COL_TEXT} pointerEvents="none"
                fontStyle={loc.passable ? 'italic' : undefined}
                opacity={loc.passable ? 0.7 : 0.95}>
                {loc.name}
              </text>
            ) : null}
            {here ? (
              <text x={maxX + 2} y={minY + 2} fontSize={12} pointerEvents="none">📍</text>
            ) : null}
            {evs.length ? (
              <text x={minX - 2} y={minY + 2} fontSize={12} textAnchor="end">
                <title>
                  {evs.map((e) => `${(e.category || '').toUpperCase()}: ${e.text || ''}`)
                    .join('\n')}
                </title>
                {danger ? '🔥' : '❗'}{evs.length > 1 ? ` ${evs.length}` : ''}
              </text>
            ) : null}
          </g>
        )
      })}
    </g>
  )
}

/** Layer 4 — what is LEFT of a journey: from the foot point under the walker
 *  to the target, dashed. `waypoints` is the avatar's alone under fog, so a
 *  foreign traveller shows as a point and nothing more. */
function TravelLines({ chars }: { chars: WorldmapCharacter[] }) {
  const { view, w, h } = useMapView()
  return (
    <g pointerEvents="none">
      {chars.map((c) => {
        const wp = c.travel?.waypoints
        if (!wp || wp.length < 2 || !c.pos) return null
        const near = nearestOnPolyline(wp, c.pos.x, c.pos.z)
        if (!near) return null
        const rest: Array<[number, number]> = [
          [near.x, near.z], ...wp.slice(near.index + 1),
        ]
        if (rest.length < 2) return null
        return (
          <path key={c.name} d={worldPolyToPath(rest, view, w, h, false)}
            fill="none" stroke={COL_ACCENT} strokeWidth={1.5}
            strokeDasharray="6 4" strokeOpacity={0.85} />
        )
      })}
    </g>
  )
}

/** Layer 5 — the characters at their metre position. `pos` is the truth: a
 *  character standing in the wilderness has no `location_id` and is drawn all
 *  the same. */
function Characters({ chars, avatar, tooltip }: {
  chars: WorldmapCharacter[]
  avatar: string
  /** Name plus, while travelling, where to and when — built by the panel so
   *  the translated words stay in one place. */
  tooltip: (c: WorldmapCharacter) => string
}) {
  const { view, w, h } = useMapView()
  const chips = view.pxPerM >= CHIP_MIN_PX_PER_M
  return (
    <g>
      {chars.map((c) => {
        if (!c.pos) return null
        const p = worldToScreen(c.pos.x, c.pos.z, view, w, h)
        const me = c.name === avatar
        const r = me ? DOT_R_AVATAR : DOT_R_OTHER
        const showChip = chips && !me && !!c.avatar_url
        return (
          // The tooltip sits on the GROUP: with a chip the circle is only a
          // ring (`fill="none"`), so hanging the title on it would leave the
          // face itself — the part one actually points at — silent.
          <g key={c.name}>
            <title>{tooltip(c)}</title>
            {showChip ? (
              <image href={c.avatar_url} x={p.x - r * 2} y={p.y - r * 2}
                width={r * 4} height={r * 4} preserveAspectRatio="xMidYMid slice"
                style={{ clipPath: 'circle(50%)' }} />
            ) : null}
            <circle cx={p.x} cy={p.y} r={showChip ? r * 2 : r}
              fill={showChip ? 'none' : me ? COL_ACCENT : COL_STONE}
              stroke={me ? COL_ACCENT : COL_DARK} strokeWidth={1.5}
              strokeOpacity={0.9} />
            {c.travel ? (
              <text x={p.x + r + 1} y={p.y - r} fontSize={10} pointerEvents="none">🚶</text>
            ) : null}
          </g>
        )
      })}
    </g>
  )
}

export function MapPanel({ currentLocationId, autoFit = false, labelMode = 'all' }:
  { currentLocationId: string; autoFit?: boolean; labelMode?: LabelMode }) {
  const { t } = useI18n()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  // Admin-only view switch (component state, off by default — admins play
  // too). It decides WHICH view is fetched, so the poll key carries the flag:
  // a fogged and an unfogged payload must never share one cache entry. The
  // fogged key is the one TravelPanel shares — renaming it would cost the
  // player a second request.
  const [showAll, setShowAll] = useState(false)
  const allView = isAdmin && showAll
  const { data } = usePoll<WorldmapPayload>(
    allView ? 'play-worldmap-all' : 'play-worldmap',
    () => apiGet<WorldmapPayload>(allView ? '/play/worldmap?all=1' : '/play/worldmap'),
    { intervalMs: 10000 })

  // The painted ground is loaded ONCE and re-fetched only when the worldmap
  // poll reports a different signature (§ A1.5) — it is never fogged, so
  // every logged-in user gets the same landscape.
  //
  // The effect hangs on `data`, not on `sig` alone: every poll hands back a
  // freshly parsed payload, so a failed fetch is retried on the next tick
  // (~10 s) even in a world whose signature never changes. `loadedSig` is
  // what actually suppresses the repeat once the load succeeded.
  const [terrain, setTerrain] = useState<TerrainPayload | null>(null)
  const sig = data?.terrain_sig || ''
  const loadedSig = useRef('')
  useEffect(() => {
    if (!sig || loadedSig.current === sig) return
    let cancelled = false
    apiGet<TerrainPayload>('/play/terrain').then((p) => {
      if (cancelled) return
      loadedSig.current = sig
      setTerrain(p)
    }).catch(() => { /* bare frame until the next poll tick retries */ })
    return () => { cancelled = true }
  }, [sig, data])

  // The view: restored from localStorage, or fitted to the world once the
  // bounds and the pane size are known. The enlarge overlay (`autoFit`) always
  // fits and never writes the docked panel's view back.
  const savedRef = useRef<View | null>(autoFit ? null : loadView())
  const [view, setView] = useState<View>(() => savedRef.current
    || { cx: 0, cz: 0, pxPerM: FIT_FALLBACK_PX_PER_M })
  const fittedRef = useRef(!!savedRef.current)

  // The pane is measured here as well: `fitBounds` needs the pixel size, and
  // the size the canvas measures for itself lives inside its own context. A
  // CALLBACK ref, not a mount effect — this panel renders a placeholder while
  // the first payload is missing, so the pane does not exist on first commit.
  const [pane, setPane] = useState({ w: 0, h: 0 })
  const paneObsRef = useRef<ResizeObserver | null>(null)
  const setPaneEl = useCallback((el: HTMLDivElement | null) => {
    paneObsRef.current?.disconnect()
    paneObsRef.current = null
    if (!el) return
    const read = () => {
      const r = el.getBoundingClientRect()
      setPane({ w: Math.round(r.width), h: Math.round(r.height) })
    }
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    paneObsRef.current = ro
  }, [])
  useEffect(() => () => paneObsRef.current?.disconnect(), [])

  const bounds = data?.world_bounds || null
  useEffect(() => {
    if (fittedRef.current || !bounds || !pane.w || !pane.h) return
    fittedRef.current = true
    setView(fitBounds(bounds, pane.w, pane.h))
  }, [bounds, pane])

  const fitView = useCallback(() => {
    if (!bounds || !pane.w || !pane.h) return
    setView(fitBounds(bounds, pane.w, pane.h))
  }, [bounds, pane])

  // Persist pan and zoom — but never from the enlarge overlay, which would
  // otherwise overwrite the docked panel's view with its own, and never
  // before the first fit: the placeholder view is "nothing known yet", not a
  // view the player chose.
  useEffect(() => {
    if (autoFit || !fittedRef.current) return
    saveView(view)
  }, [view, autoFit])

  // The catalog by kind, lower-cased: the colour of an area comes from HERE
  // and from nowhere else (§ A1.5).
  const types = useMemo(() => {
    const out: Record<string, TerrainType> = {}
    for (const ty of terrain?.types || []) out[(ty.kind || '').toLowerCase()] = ty
    return out
  }, [terrain])
  const groundColor = terrain
    ? typeColor(types, (terrain.default_kind || '').toLowerCase()) : ''

  const travellingTo = t('travelling to')
  const arrivesAt = t('arrives ~')
  const tooltip = useCallback((c: WorldmapCharacter): string => {
    // Fog (§ A12): an empty target name means the avatar does not know the
    // destination — then the tooltip says nothing about it, never the raw id.
    const target = c.movement_target_name || ''
    if (!c.movement_target_id || !target) return c.name
    const eta = c.travel?.eta_game ? c.travel.eta_game.slice(11, 16) : ''
    return `${c.name} — ${travellingTo} ${target}`
      + (eta ? ` (${arrivesAt} ${eta})` : '')
  }, [travellingTo, arrivesAt])

  const current = currentLocationId || data?.current_location_id || ''

  if (!data) return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('Loading…')}</div>
  if (!bounds && !data.characters.length) {
    return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No map positions yet.')}</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, height: HEAD_H,
        fontSize: '0.78em', opacity: 0.75, whiteSpace: 'nowrap',
      }} onMouseDown={(e) => e.stopPropagation()}>
        {isAdmin ? (
          <label style={{
            display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
            userSelect: 'none',
          }}>
            <input type="checkbox" checked={showAll}
              onChange={(e) => setShowAll(e.target.checked)} />
            {t('Show all locations (admin)')}
          </label>
        ) : null}
        <button onClick={fitView} disabled={!bounds}
          style={{
            marginLeft: 'auto', padding: '1px 8px', borderRadius: 10,
            fontSize: '0.95em', cursor: bounds ? 'pointer' : 'default',
            border: '1px solid var(--border, #30363d)', background: 'transparent',
            color: 'inherit',
          }}>
          {t('Fit view')}
        </button>
      </div>
      {/* `map2d-pane`: a map has no content height of its own, so under the
          autosize toggle (which makes the panel body content-sized) it would
          collapse to nothing and the canvas would measure 0×0. The class lets
          player.css give it a declared height in EXACTLY that mode — a fixed
          minimum here would clip the scale bar in a small hand-sized panel. */}
      <div ref={setPaneEl} className="map2d-pane" style={{ flex: 1, minHeight: 0 }}>
        <MapCanvas view={view} onViewChange={setView}>
          <GroundLayer bounds={bounds} color={groundColor} />
          <TerrainAreas areas={terrain?.areas || []} types={types} />
          <Footprints locations={data.locations} currentId={current}
            events={data.events_by_location || {}} labelMode={labelMode} />
          <TravelLines chars={data.characters} />
          <Characters chars={data.characters} avatar={data.avatar} tooltip={tooltip} />
        </MapCanvas>
      </div>
    </div>
  )
}
