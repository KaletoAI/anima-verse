/**
 * LayoutDraftPreview — the floor plan an LLM proposed, drawn as a read-only
 * mini plan next to the chat it came out of.
 *
 * READ-ONLY, and structurally so: there is not a single pointer handler on the
 * geometry. The draft is not persisted either — it lives in the World-Dev
 * session until "Apply" writes it through `/world-dev/apply-layout`.
 *
 * THE GEOMETRY IS THE SERVER'S. `POST /world-dev/preview-layout` runs the raw
 * model JSON through the very sanitizer the floor-plan editor saves with
 * (`world_ops._sanitize_room_layout`), and this component only projects what
 * came back: rooms already in location-local metres, outlines already folded
 * onto their own min corner, openings already clamped. Nothing is recomputed
 * here — a preview that derived its own rectangles would show a plan the apply
 * would not produce.
 *
 * Everything is METRES in the location's own frame (contract v6 Nr. 2): `x`
 * grows east, `y` grows south, the origin is the location's anchor pin, and a
 * room is placed by its MINIMUM corner. The view therefore needs no transform
 * beyond a fit — and it carries the scale aids that make a metre readable: a
 * 1 m grid, a scale bar, and the 1.70 m reference figure seen from above.
 */
import { useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
// The staircase symbol comes from the plan geometry the floor-plan EDITOR
// draws with — one routine, so a flight looks the same before and after the
// apply, and the run is never computed a second way.
import { stairSymbol } from '../world/planGeometry'
import type { StairSpec } from '../world/planGeometry'

/* ------------------------------------------------------------------ types */

/** One finding of `POST /world-dev/preview-layout`. Never an error — the apply
 *  runs regardless; this is what the author is asked to look at. */
export interface LayoutDraftWarning {
  code: string
  message: string
  /** Which room it is about: a room id, or two joined by `|` for an overlap. */
  ref?: string | null
}

export interface LayoutOpening {
  /** Polygon edge INDEX (0 = north on a plain rectangle), or a legacy letter. */
  edge: number | string
  /** Centre of the opening along that edge, 0…1 — the one ratio in the plan. */
  at: number
  width_m: number
  height_m: number
  sill_m?: number
  type: string
  to?: string
}

export interface LayoutRoomEntry {
  room_id: string
  name: string
  description?: string
  is_new?: boolean
  layout: {
    x: number
    y: number
    w: number
    d: number
    level?: number
    /** Metres relative to the room's OWN min corner, spanning 0…w / 0…d. */
    outline?: Array<[number, number]>
    no_walls?: boolean
    always_visible?: boolean
    surfaces?: { floor?: string; wall?: string }
    openings?: LayoutOpening[]
  }
}

export interface LayoutBoundaryOpening {
  edge: number
  at: number
  width_m: number
  room?: string
}

export interface LayoutDraftNormalized {
  summary?: string
  location_id: string
  location_name?: string
  /** The plot outline in local metres; empty when the location has none. */
  boundary?: Array<[number, number]>
  entry_room?: string
  rooms: LayoutRoomEntry[]
  boundary_openings?: LayoutBoundaryOpening[] | null
  /** One entry per FLIGHT — per storey jump (`map3d.stairs`), already through
   *  the map3d sanitizer, so every `dir_deg` here is one of the four quarter
   *  turns. `null` = the draft never mentioned stairs. */
  stairs?: StairSpec[] | null
  /** The location's storey height in metres — how much floor a flight eats
   *  follows from it. Absent = 3, the scene's own default. */
  storey_height_m?: number
}

export interface LayoutDraftCounts {
  rooms: number
  new_rooms: number
  openings: number
  boundary_openings: number
  stairs: number
}

/** `POST /world-dev/preview-layout`. */
export interface LayoutPreviewResponse {
  normalized: LayoutDraftNormalized
  warnings?: LayoutDraftWarning[]
  counts?: LayoutDraftCounts
}

/* -------------------------------------------------------------- constants */

const PANE_PX = 340
/** Air around the fitted plan, in metres — a plan ending exactly at the pane
 *  edge reads as if it continued. */
const PAD_M = 2
/** A person 1.70 m tall seen from above is about half a metre across. */
const FIGURE_D_M = 0.5

const COL_PLOT = '#8b949e'
const COL_ROOM = '#3fb950'
const COL_ROOM_NEW = '#58a6ff'
const COL_OPENING = '#d29922'
/** Masonry, not machinery — the warm stone the scene gives a staircase
 *  (`STYLE["stair_color"]`), so the plan and the 3D view agree. */
const COL_STAIR = '#8a7a66'
const COL_GRID = 'rgba(139,148,158,0.18)'

type Pt = [number, number]

/* ---------------------------------------------------------------- geometry */

/** A room's shell in LOCATION-local metres — the outline shifted onto its min
 *  corner, or the plain rectangle when it has none. The server already folded
 *  the outline so it spans 0…w / 0…d, so this is an addition, not a fit. */
function roomShell(room: LayoutRoomEntry): Pt[] {
  const { x, y, w, d, outline } = room.layout
  if (outline && outline.length >= 3) {
    return outline.map((p) => [x + p[0], y + p[1]] as Pt)
  }
  // Edge order of the implicit box: 0 = north, 1 = east, 2 = south, 3 = west.
  return [[x, y], [x + w, y], [x + w, y + d], [x, y + d]]
}

const LETTER_EDGE: Record<string, number> = { N: 0, E: 1, S: 2, W: 3 }

/** The two endpoints of one polygon edge, or null when the index does not
 *  exist (edge i runs from point i to point i+1). */
function edgeOf(pts: Pt[], edge: number | string): [Pt, Pt] | null {
  const i = typeof edge === 'number' ? edge : LETTER_EDGE[String(edge).toUpperCase()]
  if (!Number.isInteger(i) || i < 0 || i >= pts.length) return null
  return [pts[i], pts[(i + 1) % pts.length]]
}

/** The stretch an opening occupies on its edge: centre at `at` along the edge,
 *  `width_m` long, clipped to the edge itself. */
function openingSpan(pts: Pt[], edge: number | string, at: number,
                     widthM: number): [Pt, Pt] | null {
  const e = edgeOf(pts, edge)
  if (!e) return null
  const [a, b] = e
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const len = Math.hypot(dx, dy)
  if (len <= 0) return null
  const half = Math.min(widthM, len) / 2
  const s = Math.min(Math.max(at * len, half), len - half)
  const ux = dx / len
  const uy = dy / len
  return [
    [a[0] + ux * (s - half), a[1] + uy * (s - half)],
    [a[0] + ux * (s + half), a[1] + uy * (s + half)],
  ]
}

/** A "nice" step for the scale bar: 1, 2, 5, 10, 20, 50 … metres. */
function niceStep(rawM: number): number {
  const pow = Math.pow(10, Math.floor(Math.log10(Math.max(rawM, 0.01))))
  const n = rawM / pow
  return (n >= 5 ? 5 : n >= 2 ? 2 : 1) * pow
}

/* --------------------------------------------------------------- component */

export function LayoutDraftPreview({
  normalized, warnings, counts,
}: {
  normalized: LayoutDraftNormalized
  warnings: LayoutDraftWarning[]
  counts?: LayoutDraftCounts
}) {
  const { t } = useI18n()
  // Memoised because both are `?? []` fallbacks: a fresh empty array on every
  // render would re-run every useMemo below it for nothing.
  const rooms = useMemo(() => normalized.rooms || [], [normalized.rooms])
  const boundary = useMemo(
    () => (normalized.boundary || []) as Pt[], [normalized.boundary])
  const stairs = useMemo(() => normalized.stairs || [], [normalized.stairs])
  /** How much floor a flight eats follows from the storey height; the scene
   *  composes with 3 m when a location declares none. */
  const storeyM = normalized.storey_height_m || 3

  const levels = useMemo(() => {
    const set = new Set<number>()
    for (const r of rooms) set.add(Number(r.layout.level ?? 0))
    return Array.from(set).sort((a, b) => a - b)
  }, [rooms])
  const [level, setLevel] = useState<number | null>(null)
  const shownLevel = level !== null && levels.includes(level) ? level
    : (levels.includes(0) ? 0 : levels[0] ?? 0)

  /** Fit everything — plot, rooms AND staircases, so a room outside the plot
   *  (or a flight that overshoots it) stays visible; hiding the very thing a
   *  warning is about would be perverse. */
  const view = useMemo(() => {
    const xs: number[] = []
    const ys: number[] = []
    for (const p of boundary) { xs.push(p[0]); ys.push(p[1]) }
    for (const r of rooms) {
      for (const p of roomShell(r)) { xs.push(p[0]); ys.push(p[1]) }
    }
    for (const st of stairs) {
      const sym = stairSymbol(st, storeyM)
      for (const p of sym?.outline || []) { xs.push(p[0]); ys.push(p[1]) }
    }
    if (!xs.length) return null
    const minX = Math.min(...xs) - PAD_M
    const maxX = Math.max(...xs) + PAD_M
    const minY = Math.min(...ys) - PAD_M
    const maxY = Math.max(...ys) + PAD_M
    const spanX = Math.max(maxX - minX, 0.01)
    const spanY = Math.max(maxY - minY, 0.01)
    const scale = Math.min(PANE_PX / spanX, PANE_PX / spanY)
    return { minX, minY, spanX, spanY, scale,
             w: spanX * scale, h: spanY * scale }
  }, [boundary, rooms, stairs, storeyM])

  const toPx = (p: Pt): [number, number] => [
    (p[0] - (view?.minX ?? 0)) * (view?.scale ?? 1),
    (p[1] - (view?.minY ?? 0)) * (view?.scale ?? 1),
  ]
  const path = (pts: Pt[]) =>
    pts.map((p, i) => `${i ? 'L' : 'M'}${toPx(p).map((v) => v.toFixed(1)).join(' ')}`)
      .join(' ') + ' Z'

  if (!view) {
    return <div className="ga-form-hint">{t('The draft has no geometry to draw.')}</div>
  }

  // A grid line every metre while that stays legible, else every 5 m.
  const gridStep = view.scale >= 10 ? 1 : view.scale >= 4 ? 5 : 10
  const gridLines: Array<[number, number, number, number]> = []
  for (let gx = Math.ceil(view.minX / gridStep) * gridStep;
       gx <= view.minX + view.spanX; gx += gridStep) {
    const [px] = toPx([gx, 0])
    gridLines.push([px, 0, px, view.h])
  }
  for (let gy = Math.ceil(view.minY / gridStep) * gridStep;
       gy <= view.minY + view.spanY; gy += gridStep) {
    const [, py] = toPx([0, gy])
    gridLines.push([0, py, view.w, py])
  }
  const barM = niceStep(view.spanX / 4)
  const barPx = barM * view.scale

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {normalized.summary ? (
        <div className="ga-form-hint">{normalized.summary}</div>
      ) : null}

      {levels.length > 1 ? (
        <div className="ga-form-row">
          <span className="ga-wd-context-label" style={{ flex: '0 0 auto' }}>
            {t('Level')}
          </span>
          {levels.map((lv) => (
            <button
              key={lv}
              type="button"
              className={`ga-btn ga-btn-sm${lv === shownLevel ? ' ga-btn-primary' : ''}`}
              onClick={() => setLevel(lv)}
            >
              {lv}
            </button>
          ))}
        </div>
      ) : null}

      <svg
        width={view.w}
        height={view.h}
        viewBox={`0 0 ${view.w} ${view.h}`}
        style={{ maxWidth: '100%', background: 'rgba(0,0,0,0.15)',
                 borderRadius: 4 }}
        role="img"
        aria-label={t('Floor plan of the draft')}
      >
        <g pointerEvents="none">
          {gridLines.map((l, i) => (
            <line key={i} x1={l[0]} y1={l[1]} x2={l[2]} y2={l[3]}
              stroke={COL_GRID} strokeWidth={1} />
          ))}

          {boundary.length >= 3 ? (
            <path d={path(boundary)} fill="rgba(139,148,158,0.08)"
              stroke={COL_PLOT} strokeWidth={1.5} strokeDasharray="4 3" />
          ) : null}

          {(normalized.boundary_openings || []).map((op, i) => {
            const span = openingSpan(boundary, op.edge, op.at, op.width_m)
            if (!span) return null
            const [a, b] = [toPx(span[0]), toPx(span[1])]
            return (
              <line key={`bo${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
                stroke={COL_OPENING} strokeWidth={4} strokeLinecap="round" />
            )
          })}

          {rooms.map((room) => {
            const onLevel = Number(room.layout.level ?? 0) === shownLevel
            const shell = roomShell(room)
            const col = room.is_new ? COL_ROOM_NEW : COL_ROOM
            const centre = toPx([
              room.layout.x + room.layout.w / 2,
              room.layout.y + room.layout.d / 2,
            ])
            return (
              <g key={room.room_id} opacity={onLevel ? 1 : 0.22}>
                <path
                  d={path(shell)}
                  fill={room.layout.no_walls ? 'none' : `${col}22`}
                  stroke={col}
                  strokeWidth={room.layout.no_walls ? 1 : 2}
                  strokeDasharray={room.layout.no_walls ? '3 3' : undefined}
                />
                {(room.layout.openings || []).map((op, i) => {
                  const span = openingSpan(shell, op.edge, op.at, op.width_m)
                  if (!span) return null
                  const [a, b] = [toPx(span[0]), toPx(span[1])]
                  return (
                    <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
                      stroke={op.type === 'window' ? '#79c0ff' : COL_OPENING}
                      strokeWidth={3} strokeLinecap="round" />
                  )
                })}
                <text x={centre[0]} y={centre[1]} fill="#e6edf3" fontSize={11}
                  textAnchor="middle" dominantBaseline="middle">
                  {room.name}
                </text>
                <text x={centre[0]} y={centre[1] + 12} fill="#8b949e"
                  fontSize={9} textAnchor="middle" dominantBaseline="middle">
                  {`${room.layout.w} × ${room.layout.d} m`}
                </text>
              </g>
            )
          })}

          {/* STAIRCASES — the true footprint a flight covers, not a glyph:
              1.2 m across, the run its climb really needs, a line per tread
              and an arrowhead pointing UP the flight. Drawn over the rooms,
              because whether a flight cuts through one is exactly what an
              author has to see here. A flight belongs to two storeys: full
              strength on the one it starts from, faint on the one it arrives
              at, and as faint as an off-level room everywhere else. */}
          {stairs.map((st, i) => {
            const sym = stairSymbol(st, storeyM)
            if (!sym) return null
            const onLevel = st.from_level === shownLevel
            const arriving = st.from_level + 1 === shownLevel
            return (
              <g key={`stair${i}`}
                opacity={onLevel ? 1 : arriving ? 0.35 : 0.22}>
                <path d={path(sym.outline)} fill="rgba(138,122,102,0.28)"
                  stroke={COL_STAIR} strokeWidth={1.5} />
                {sym.treads.map(([a, b], s) => {
                  const [pa, pb] = [toPx(a), toPx(b)]
                  return (
                    <line key={s} x1={pa[0]} y1={pa[1]} x2={pb[0]} y2={pb[1]}
                      stroke={COL_STAIR} strokeWidth={0.8} opacity={0.8} />
                  )
                })}
                <polyline
                  points={sym.arrow.map((p) => toPx(p).map((v) => v.toFixed(1)).join(' ')).join(', ')}
                  fill="none" stroke={COL_STAIR} strokeWidth={2} />
              </g>
            )
          })}

          {/* Scale aids — no measurement without a yardstick. */}
          <g transform={`translate(8 ${view.h - 10})`}>
            <line x1={0} y1={0} x2={barPx} y2={0} stroke="#e6edf3"
              strokeWidth={2} />
            <text x={barPx + 6} y={3} fill="#e6edf3" fontSize={10}>
              {`${barM} m`}
            </text>
            <circle cx={barPx + 46} cy={-1} r={(FIGURE_D_M / 2) * view.scale}
              fill="#e6edf3" />
            <text x={barPx + 54} y={3} fill="#8b949e" fontSize={9}>
              {t('1.70 m')}
            </text>
          </g>
        </g>
      </svg>

      <div className="ga-form-hint">
        {counts
          ? t('{r} rooms ({n} new) · {o} openings · {b} plot entrances · {s} staircases')
            .replace('{r}', String(counts.rooms))
            .replace('{n}', String(counts.new_rooms))
            .replace('{o}', String(counts.openings))
            .replace('{b}', String(counts.boundary_openings))
            .replace('{s}', String(counts.stairs ?? 0))
          : ''}
        {normalized.entry_room
          ? ` · ${t('entry room')}: ${rooms.find((r) => r.room_id === normalized.entry_room)?.name || normalized.entry_room}`
          : ''}
      </div>

      {warnings.length ? (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12,
                     color: '#d29922' }}>
          {warnings.map((w, i) => (
            <li key={i}>
              <code>{w.code}</code>
              {w.ref ? ` (${rooms.find((r) => r.room_id === w.ref)?.name || w.ref})` : ''}
              {' — '}
              {w.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
