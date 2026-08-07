/**
 * MapCanvas — the drawing surface of the free world map.
 *
 * A controlled viewport onto one continuous plane in METRES: the parent owns
 * the `View` (world centre + px per metre), the canvas owns only the two
 * gestures that change it — cursor-anchored wheel zoom and pan by dragging
 * empty ground. Every child draws in SCREEN pixels and gets the current view
 * plus the measured canvas size from `MapViewCtx`; a child that wants its own
 * drag stops the pointerdown from propagating, exactly like the room-layout
 * editor's pieces do.
 *
 * "Kein Maß ohne Maßstab" (the plan editor's doctrine, PlanMeasure.tsx) holds
 * here too, and on an endless plane it matters more: the canvas ALWAYS draws a
 * metre grid whose step follows the zoom, a scale bar that names the length it
 * draws, and the 1.70 m person seen from above. The figure disappears once its
 * drawn extent (the 0.60 m of space a standing person occupies) falls under
 * 4 px — a two-pixel blob labelled "1.70 m" would be the very lie the doctrine
 * is about, and at that zoom the grid and the bar carry the scale alone.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode } from 'react'
import { fmtM, niceDown, niceUp } from '../world/planGeometry'
import { FIT_FALLBACK_PX_PER_M, screenToWorld, visibleWorldRect, zoomAt, type View } from './mapMath'

const AID_COLOR = '#f0f6fc'
const GRID_COLOR = '#8b949e'
const BG_COLOR = '#0d1117'

/** Wheel notch = one step; the same discrete feel as the plan editor's zoom. */
const ZOOM_STEP = 1.2
/** Below this the press stays a click — no click after a pan. */
const CLICK_SLOP_PX = 4
/** Smallest gap between grid lines; `niceUp` rounds the step up from it. */
const GRID_MIN_PX = 60
/** Safety net against a pathological view producing thousands of lines. */
const GRID_MAX_LINES = 200

/** The 1.70 m person from above, in REAL metres (PlanMeasure's figure with its
 *  fractions resolved against the 0.60 m circle of occupied space). */
const FIG = {
  spaceM: 0.6,
  shoulderRxM: 0.225,
  shoulderRyM: 0.15,
  headRM: 0.096,
  headDyM: -0.054,
  hideBelowPx: 4,
}

export interface MapViewInfo {
  view: View
  /** Measured canvas size in CSS pixels (0 until the first observation). */
  w: number
  h: number
}

/** What children read to place themselves. Outside a canvas the size is 0,
 *  which every consumer already has to survive (first paint); the default zoom
 *  is the same one `fitBounds` falls back to, so there is one "no information
 *  yet" zoom in the codebase, not two. */
export const MapViewCtx = createContext<MapViewInfo>({
  view: { cx: 0, cz: 0, pxPerM: FIT_FALLBACK_PX_PER_M }, w: 0, h: 0,
})

export const useMapView = (): MapViewInfo => useContext(MapViewCtx)

export interface MapCanvasProps {
  view: View
  onViewChange: (view: View) => void
  children?: ReactNode
  /** A click on empty ground (no child took the pointer) that was NOT a pan.
   *  The event comes along so a tool can read its modifier keys. */
  onBackgroundClick?: (wx: number, wz: number, e: PointerEvent) => void
  /** Cursor position in world metres — for a coordinate readout or a rubber
   *  band. Fires on every move over the canvas. */
  onPointerWorldMove?: (wx: number, wz: number) => void
  className?: string
  /** Cursor over empty ground; a parent with an armed tool says 'crosshair'. */
  cursor?: string
}

/** Grid in whole metres over the visible world rectangle. The step follows the
 *  zoom (lines never crowd closer than GRID_MIN_PX), every fifth line is
 *  stronger and carries its world coordinate. */
function MetreGrid({ view, w, h }: MapViewInfo) {
  const { lines, step } = useMemo(() => {
    const s = niceUp(GRID_MIN_PX / view.pxPerM)
    const r = visibleWorldRect(view, w, h)
    const first = Math.ceil(r.min_x / s)
    const lastX = Math.floor(r.max_x / s)
    const firstZ = Math.ceil(r.min_z / s)
    const lastZ = Math.floor(r.max_z / s)
    const xs: number[] = []
    const zs: number[] = []
    for (let n = first; n <= lastX && xs.length < GRID_MAX_LINES; n++) xs.push(n)
    for (let n = firstZ; n <= lastZ && zs.length < GRID_MAX_LINES; n++) zs.push(n)
    return { lines: { xs, zs }, step: s }
  }, [view, w, h])

  const sx = (n: number) => w / 2 + (n * step - view.cx) * view.pxPerM
  const sy = (n: number) => h / 2 + (n * step - view.cz) * view.pxPerM

  return (
    <g pointerEvents="none">
      {lines.xs.map((n) => (
        <line key={`x${n}`} x1={sx(n)} y1={0} x2={sx(n)} y2={h}
          stroke={GRID_COLOR} strokeWidth={1} opacity={n % 5 === 0 ? 0.4 : 0.17} />
      ))}
      {lines.zs.map((n) => (
        <line key={`z${n}`} x1={0} y1={sy(n)} x2={w} y2={sy(n)}
          stroke={GRID_COLOR} strokeWidth={1} opacity={n % 5 === 0 ? 0.4 : 0.17} />
      ))}
      {lines.xs.filter((n) => n % 5 === 0).map((n) => (
        <text key={`lx${n}`} x={sx(n) + 3} y={11} fontSize={10} fill={GRID_COLOR}>
          {fmtM(n * step)}
        </text>
      ))}
      {lines.zs.filter((n) => n % 5 === 0).map((n) => (
        <text key={`lz${n}`} x={3} y={sy(n) - 3} fontSize={10} fill={GRID_COLOR}>
          {fmtM(n * step)}
        </text>
      ))}
    </g>
  )
}

/** The classic four-segment scale bar plus the 1.70 m figure, bottom left. */
function MapMeasureLegend({ view, h }: MapViewInfo) {
  const barM = niceDown(140 / view.pxPerM)
  const segPx = (barM * view.pxPerM) / 4
  const barY = h - 18
  const figPx = FIG.spaceM * view.pxPerM
  const showFig = figPx >= FIG.hideBelowPx
  const figCx = 14 + figPx / 2
  const figCy = barY - 16 - figPx / 2
  const px = (m: number) => m * view.pxPerM
  return (
    <g pointerEvents="none">
      {[0, 1, 2, 3].map((i) => (
        <rect key={i} x={14 + i * segPx} y={barY} width={segPx} height={6}
          fill={i % 2 ? AID_COLOR : BG_COLOR} stroke={AID_COLOR} strokeWidth={1} />
      ))}
      <text x={14 + 4 * segPx + 6} y={barY + 7} fontSize={10} fill={AID_COLOR}>
        {fmtM(barM)} m
      </text>
      {showFig && (
        <g>
          <circle cx={figCx} cy={figCy} r={figPx / 2} fill="rgba(240,246,252,0.10)"
            stroke={AID_COLOR} strokeWidth={1} strokeDasharray="3 2" opacity={0.6} />
          <ellipse cx={figCx} cy={figCy + px(0.012)}
            rx={px(FIG.shoulderRxM)} ry={px(FIG.shoulderRyM)}
            fill="rgba(240,246,252,0.85)" stroke={BG_COLOR} strokeWidth={1} />
          <circle cx={figCx} cy={figCy + px(FIG.headDyM)} r={px(FIG.headRM)}
            fill={AID_COLOR} stroke={BG_COLOR} strokeWidth={1} />
          <text x={figCx + figPx / 2 + 6} y={figCy + 4} fontSize={10} fill={AID_COLOR}>
            1.70 m
          </text>
        </g>
      )}
    </g>
  )
}

export function MapCanvas({
  view, onViewChange, children, onBackgroundClick, onPointerWorldMove,
  className, cursor,
}: MapCanvasProps) {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [panning, setPanning] = useState(false)

  // Live values for the window/native listeners, which are installed once.
  const viewRef = useRef(view)
  viewRef.current = view
  const emitRef = useRef(onViewChange)
  emitRef.current = onViewChange
  const clickRef = useRef(onBackgroundClick)
  clickRef.current = onBackgroundClick

  const dragRef = useRef<{
    sx: number; sy: number; cx: number; cz: number; moved: boolean
  } | null>(null)

  // Measured size: the aids are stated in PIXELS, so they measure the element
  // instead of assuming a width (PlanMeasure's rule).
  useEffect(() => {
    const el = boxRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const read = () => {
      const r = el.getBoundingClientRect()
      setSize({ w: Math.round(r.width), h: Math.round(r.height) })
    }
    read()
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Wheel zoom, anchored at the cursor. Native non-passive listener — React's
  // synthetic wheel cannot preventDefault reliably.
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!e.deltaY) return
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const next = zoomAt(viewRef.current, e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP,
        e.clientX - r.left, e.clientY - r.top, r.width, r.height)
      if (next !== viewRef.current) emitRef.current(next)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // Pan on window listeners so a drag survives leaving the canvas. A press
  // that never travels past the slop stays a click on the ground.
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) return
      const dx = e.clientX - d.sx
      const dy = e.clientY - d.sy
      if (!d.moved) {
        if (Math.hypot(dx, dy) < CLICK_SLOP_PX) return
        d.moved = true
        setPanning(true)
      }
      const v = viewRef.current
      emitRef.current({
        cx: d.cx - dx / v.pxPerM, cz: d.cz - dy / v.pxPerM, pxPerM: v.pxPerM,
      })
    }
    const up = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d) return
      dragRef.current = null
      setPanning(false)
      const el = boxRef.current
      if (d.moved || !el || !clickRef.current) return
      const r = el.getBoundingClientRect()
      const p = screenToWorld(e.clientX - r.left, e.clientY - r.top,
        viewRef.current, r.width, r.height)
      clickRef.current(p.x, p.z, e)
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

  const onPointerDown = useCallback((e: ReactPointerEvent) => {
    // Only the ground pans: a child with its own drag stops propagation.
    if (e.button !== 0 && e.button !== 1) return
    const v = viewRef.current
    dragRef.current = { sx: e.clientX, sy: e.clientY, cx: v.cx, cz: v.cz, moved: false }
  }, [])

  const onPointerMove = useCallback((e: ReactPointerEvent) => {
    if (!onPointerWorldMove) return
    const el = boxRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const p = screenToWorld(e.clientX - r.left, e.clientY - r.top,
      viewRef.current, r.width, r.height)
    onPointerWorldMove(p.x, p.z)
  }, [onPointerWorldMove])

  const ctx = useMemo<MapViewInfo>(() => ({ view, w: size.w, h: size.h }),
    [view, size.w, size.h])

  return (
    <div
      ref={boxRef}
      className={className}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      style={{
        position: 'relative', width: '100%', height: '100%', overflow: 'hidden',
        background: BG_COLOR, touchAction: 'none', userSelect: 'none',
        cursor: panning ? 'grabbing' : (cursor || 'grab'),
      }}
    >
      {size.w > 0 && size.h > 0 && (
        <svg width={size.w} height={size.h} viewBox={`0 0 ${size.w} ${size.h}`}
          style={{ position: 'absolute', inset: 0, display: 'block' }}>
          <MetreGrid view={view} w={size.w} h={size.h} />
          <MapViewCtx.Provider value={ctx}>{children}</MapViewCtx.Provider>
          <MapMeasureLegend view={view} w={size.w} h={size.h} />
        </svg>
      )}
    </div>
  )
}
