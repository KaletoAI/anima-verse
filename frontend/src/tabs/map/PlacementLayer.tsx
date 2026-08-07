/**
 * PlacementLayer — the placed locations of the free world map, drawn INSIDE
 * the `MapCanvas` SVG.
 *
 * A location is a square of edge `map3d.plan_width_m` centred on its metre
 * position and turned by `yaw_deg` (contract § A1.1). The turn happens in SVG
 * (`<g transform="rotate(yaw cx cy)">`) around exactly the point
 * `worldToScreen` returns for the centre, so this layer does NOT re-derive the
 * corner arithmetic of `footprintScreenCorners`: same centre, same angle, same
 * sign — they agree by construction, and there is one place that could be
 * wrong instead of two. `yaw_deg` is written through unchanged; no editor-side
 * sign conversion exists (decision 2026-08-07).
 *
 * Without a scale anchor a location has NO area (§ A1.3). It is still drawn —
 * as a dashed NO_ANCHOR_WIDTH_M placeholder — because an editor that hides a
 * half-configured location leaves the user nothing to click; every surface
 * showing one says so (dashes here, a warning on the selection chip).
 *
 * Moving is the canvas gesture, never HTML5 drag&drop: `pointerdown` on a
 * footprint stops propagation (so `MapCanvas` does not pan), the move runs on
 * window listeners so it survives leaving the canvas, and the commit fires
 * ONCE on `pointerup`. Below CLICK_SLOP_PX the press stays a selection click —
 * the same threshold the canvas uses to tell a pan from a click.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { useMapView } from './MapCanvas'
import { worldToScreen, type ScreenPt } from './mapMath'
import type { EditorLocation } from './mapTypes'

/** Edge a footprint falls back to when the location carries no scale anchor.
 *  A placeholder, and marked as one wherever it is drawn. */
export const NO_ANCHOR_WIDTH_M = 10

/** Below this travel the press is a click, not a move (MapCanvas' value). */
const CLICK_SLOP_PX = 4
/** Under this drawn edge the name would be wider than the place it names. */
const LABEL_MIN_PX = 28
/** A footprint never drops below this on screen — at world zoom a 3 m hut
 *  would otherwise become an unclickable half pixel. */
const MIN_DRAWN_PX = 6

const COL_PLACED = '#8b949e'
const COL_SELECTED = '#58a6ff'
const COL_GHOST = '#3fb950'
const COL_WARN = '#d29922'

/** The scale anchor of a location, or `null` when it has none. Reads
 *  `map3d.plan_width_m` — the ONE anchor field (`location_model3d.py`); the
 *  worldmap payload's hoisted `plan_width_m` is the same number, and unplaced
 *  locations only carry the nested one. */
export function anchorWidthM(loc: EditorLocation): number | null {
  const w = loc.map3d?.plan_width_m
  return typeof w === 'number' && Number.isFinite(w) && w > 0 ? w : null
}

/** Placed = a finite metre position. Anything else stands on no map at all. */
export function isPlaced(loc: EditorLocation): boolean {
  return typeof loc.pos_x === 'number' && Number.isFinite(loc.pos_x)
    && typeof loc.pos_z === 'number' && Number.isFinite(loc.pos_z)
}

/** Cache-busted 2D map icon of a location (404 = no image; an SVG `<image>`
 *  that fails to load simply draws nothing and lets the fill show). */
export function mapIconUrl(locId: string, ver: number): string {
  return `/world/locations/${encodeURIComponent(locId)}/map-icon-2d?v=${ver}`
}

/**
 * One footprint square: fill, optional map icon, outline — all inside the yaw
 * rotation. The icon carries its own 90°-step display rotation
 * (`map_rotation_2d`), which turns the ARTWORK inside the square and is not
 * the location's rotation in the world.
 */
function FootSquare({ p, size, yaw, stroke, strokeWidth, dashed, iconHref, iconRot }: {
  p: ScreenPt
  size: number
  yaw: number
  stroke: string
  strokeWidth: number
  dashed?: boolean
  iconHref?: string
  iconRot?: number
}) {
  const half = size / 2
  return (
    <g transform={`rotate(${yaw} ${p.x} ${p.y})`}>
      <rect x={p.x - half} y={p.y - half} width={size} height={size}
        fill="rgba(139,148,158,0.14)" stroke="none" />
      {iconHref ? (
        <image href={iconHref} x={p.x - half} y={p.y - half} width={size} height={size}
          preserveAspectRatio="xMidYMid slice"
          transform={iconRot ? `rotate(${iconRot} ${p.x} ${p.y})` : undefined} />
      ) : null}
      <rect x={p.x - half} y={p.y - half} width={size} height={size}
        fill="none" stroke={stroke} strokeWidth={strokeWidth}
        strokeDasharray={dashed ? '6 4' : undefined} />
      {/* The local −z edge (the location's "north") — without it a square
          gives no hint which way it was turned. */}
      <line x1={p.x - half} y1={p.y - half} x2={p.x + half} y2={p.y - half}
        stroke={stroke} strokeWidth={strokeWidth + 1} opacity={0.9} />
    </g>
  )
}

export interface GhostSpec {
  /** What the click will do: place an existing location or clone a template. */
  kind: 'place' | 'clone'
  id: string
  name: string
  /** Edge in metres — the placeholder when the source has no anchor. */
  widthM: number
  anchored: boolean
}

export interface PlacementLayerProps {
  /** PLACED locations only — the caller decides what belongs on the map. */
  locations: EditorLocation[]
  selectedId: string
  onSelect: (id: string) => void
  /** Commit of a finished move, in world metres (already snapped). */
  onMove: (id: string, x: number, z: number) => void
  /** Snap the moved centre onto the 10 m grid. */
  snapM: number
  /** Cache-buster per location id — bumped after an image change. */
  iconVer: Record<string, number>
  /** An armed tray entry: its footprint follows the cursor and the placed
   *  ones stop taking pointer events, so a click can land on top of them. */
  ghost: GhostSpec | null
  ghostPt: { x: number; z: number } | null
}

export function PlacementLayer({
  locations, selectedId, onSelect, onMove, snapM, iconVer, ghost, ghostPt,
}: PlacementLayerProps) {
  const { view, w, h } = useMapView()
  const [drag, setDrag] = useState<{ id: string; x: number; z: number } | null>(null)

  // Live values for the window listeners, which are installed once.
  const viewRef = useRef(view)
  viewRef.current = view
  const snapRef = useRef(snapM)
  snapRef.current = snapM
  const moveRef = useRef(onMove)
  moveRef.current = onMove
  const dragRef = useRef<{
    id: string; sx: number; sy: number; ox: number; oz: number
    moved: boolean; x: number; z: number
  } | null>(null)

  useEffect(() => {
    const snapV = (v: number) => {
      const s = snapRef.current
      return s > 0 ? Math.round(v / s) * s : Math.round(v * 100) / 100
    }
    const move = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) return
      const dx = e.clientX - d.sx
      const dy = e.clientY - d.sy
      if (!d.moved) {
        if (Math.hypot(dx, dy) < CLICK_SLOP_PX) return
        d.moved = true
      }
      const px = viewRef.current.pxPerM
      d.x = snapV(d.ox + dx / px)
      d.z = snapV(d.oz + dy / px)
      setDrag({ id: d.id, x: d.x, z: d.z })
    }
    const up = () => {
      const d = dragRef.current
      if (!d) return
      dragRef.current = null
      setDrag(null)
      if (d.moved) moveRef.current(d.id, d.x, d.z)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
  }, [])

  const startDrag = useCallback((e: ReactPointerEvent, loc: EditorLocation) => {
    if (e.button !== 0) return
    // The canvas must not pan while a footprint is being moved.
    e.stopPropagation()
    onSelect(loc.id)
    const ox = loc.pos_x as number
    const oz = loc.pos_z as number
    dragRef.current = {
      id: loc.id, sx: e.clientX, sy: e.clientY, ox, oz, moved: false, x: ox, z: oz,
    }
  }, [onSelect])

  if (!w || !h) return null

  // Big first, small last: a hut inside a village square stays clickable.
  // The selection is drawn on top of everything regardless of its size.
  const ordered = [...locations].sort((a, b) => {
    if (a.id === selectedId) return 1
    if (b.id === selectedId) return -1
    return (anchorWidthM(b) ?? NO_ANCHOR_WIDTH_M) - (anchorWidthM(a) ?? NO_ANCHOR_WIDTH_M)
  })

  return (
    <g pointerEvents={ghost ? 'none' : undefined}>
      {ordered.map((loc) => {
        const anchor = anchorWidthM(loc)
        const dragging = drag && drag.id === loc.id
        const cx = dragging ? drag.x : (loc.pos_x as number)
        const cz = dragging ? drag.z : (loc.pos_z as number)
        const p = worldToScreen(cx, cz, view, w, h)
        const size = Math.max(MIN_DRAWN_PX, (anchor ?? NO_ANCHOR_WIDTH_M) * view.pxPerM)
        const selected = loc.id === selectedId
        const yaw = typeof loc.yaw_deg === 'number' && Number.isFinite(loc.yaw_deg)
          ? loc.yaw_deg : 0
        const stroke = selected ? COL_SELECTED : (anchor ? COL_PLACED : COL_WARN)
        return (
          <g key={loc.id} style={{ cursor: 'move' }}
            onPointerDown={(e) => startDrag(e, loc)}>
            <FootSquare p={p} size={size} yaw={yaw} stroke={stroke}
              strokeWidth={selected ? 2 : 1} dashed={!anchor}
              iconHref={mapIconUrl(loc.id, iconVer[loc.id] || 0)}
              iconRot={loc.map_rotation_2d || 0} />
            {size >= LABEL_MIN_PX || selected ? (
              <text x={p.x} y={p.y + size / 2 + 12} fontSize={11} textAnchor="middle"
                fill={selected ? COL_SELECTED : '#c9d1d9'} pointerEvents="none"
                style={{ paintOrder: 'stroke', stroke: '#0d1117', strokeWidth: 3 }}>
                {loc.name}
              </text>
            ) : null}
          </g>
        )
      })}

      {ghost && ghostPt ? (
        <g pointerEvents="none">
          <FootSquare
            p={worldToScreen(ghostPt.x, ghostPt.z, view, w, h)}
            size={Math.max(MIN_DRAWN_PX, ghost.widthM * view.pxPerM)}
            yaw={0} stroke={ghost.anchored ? COL_GHOST : COL_WARN}
            strokeWidth={2} dashed={!ghost.anchored} />
        </g>
      ) : null}
    </g>
  )
}
