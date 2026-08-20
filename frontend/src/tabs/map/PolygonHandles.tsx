/**
 * PolygonHandles — the ONE point-editing gesture of the map canvas.
 *
 * Drag a vertex to move it, double-click it to remove it, click an edge to
 * insert one. Three gestures, one implementation: the painted terrain edits
 * its outlines (or the centre line of a ribbon) with it, and the world relief
 * edits the outlines of its height areas with it. They used to be the same
 * ninety lines twice — including the window-level pointer listeners, which is
 * exactly the kind of thing that drifts silently (one side gets a fix for a
 * drag that survives leaving the canvas, the other does not).
 *
 * The DRAG LIVES HERE, and that is why the outline is drawn here too: while a
 * point is being dragged the shape has to follow the cursor, and only this
 * component knows where the cursor is. A caller whose outline is not simply
 * the dragged points — a ribbon generated from a centre line — passes
 * `outlineOf` and gets the same live preview.
 *
 * Nothing in here writes: every gesture ends in a callback, the parent decides
 * what that means (optimistic patch, PUT, refusal).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react'
import { useMapView } from './MapCanvas'
import { screenToWorld, worldPolyToPath, worldToScreen } from './mapMath'

/** Vertex handle radius and the click width of an edge, in pixels. */
const HANDLE_R = 5
const EDGE_HIT_PX = 10
/** Below this travel a press on a handle stays a click (MapCanvas' value). */
const CLICK_SLOP_PX = 4

/** Metre coordinates are stored with 2 decimals (`app/models/terrain.py`,
 *  `app/models/heightfield.py`); rounding here keeps what the editor draws
 *  identical to what it sent. */
const r2 = (v: number): number => Math.round(v * 100) / 100

/** The point on segment a→b closest to p, so an inserted vertex lands ON the
 *  edge the user clicked and not next to it. */
function projectOnSegment(a: [number, number], b: [number, number],
  px: number, pz: number): [number, number] {
  const dx = b[0] - a[0]
  const dz = b[1] - a[1]
  const len2 = dx * dx + dz * dz
  if (!(len2 > 0)) return [a[0], a[1]]
  const t = Math.min(1, Math.max(0, ((px - a[0]) * dx + (pz - a[1]) * dz) / len2))
  return [a[0] + t * dx, a[1] + t * dz]
}

export interface PolygonHandlesProps {
  /** What the handles sit on, in world metres. */
  points: Array<[number, number]>
  /** A ring wraps (its last edge closes it); an open line does not, and its
   *  last point has no edge after it. */
  closed: boolean
  /** Colour of the outline and the handles. */
  color: string
  /** The shape the points DESCRIBE, when it is not the points themselves — a
   *  centre line describes the ribbon around it. Called with the live (dragged)
   *  points; returning null keeps the last usable shape, which is what stops a
   *  momentarily degenerate drag from blanking the preview. */
  outlineOf?: (pts: Array<[number, number]>) => Array<[number, number]> | null
  /** Draw the points themselves dashed on top — the recipe behind a generated
   *  outline, visible while it is being dragged. */
  dashed?: boolean
  /** Fewer points than this and nothing is drawn at all. */
  minPoints: number
  /** Snap hook for drags and edge inserts: receives the raw point, the
   *  vertex index it applies to and whether Shift is held (the universal
   *  free-hand escape), returns the point to use. The HOST owns the rule —
   *  a floor plan aligns to neighbour axes and its metre grid, painted
   *  terrain stays free-hand by simply not passing one. */
  snap?: (x: number, z: number, index: number, shift: boolean) => [number, number]
  /** A finished drag, in world metres. */
  onMove: (index: number, x: number, z: number) => void
  onDelete: (index: number) => void
  /** Insert a vertex AT `index` (the position it takes in the list). */
  onInsert: (index: number, x: number, z: number) => void
}

export function PolygonHandles({
  points, closed, color, outlineOf, dashed, minPoints,
  snap, onMove, onDelete, onInsert,
}: PolygonHandlesProps) {
  const { view, w, h } = useMapView()
  const [drag, setDrag] = useState<{ i: number; x: number; z: number } | null>(null)

  // Live values for the window listeners, which are installed once.
  const viewRef = useRef(view)
  viewRef.current = view
  const moveRef = useRef(onMove)
  moveRef.current = onMove
  const snapRef = useRef(snap)
  snapRef.current = snap
  const dragRef = useRef<{
    i: number; sx: number; sy: number; ox: number; oz: number
    moved: boolean; x: number; z: number
  } | null>(null)

  useEffect(() => {
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
      let nx = d.ox + dx / px
      let nz = d.oz + dy / px
      const sn = snapRef.current
      if (sn) [nx, nz] = sn(nx, nz, d.i, e.shiftKey)
      d.x = r2(nx)
      d.z = r2(nz)
      setDrag({ i: d.i, x: d.x, z: d.z })
    }
    const up = () => {
      const d = dragRef.current
      if (!d) return
      dragRef.current = null
      setDrag(null)
      if (d.moved) moveRef.current(d.i, d.x, d.z)
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

  /** Pointer position in world metres. The SVG is measured instead of trusting
   *  the context size — a one-pixel border between the two would put every
   *  inserted vertex slightly off the edge it was aimed at. */
  const worldAt = useCallback((e: ReactPointerEvent | ReactMouseEvent) => {
    const svg = (e.currentTarget as SVGElement).ownerSVGElement
    if (!svg) return null
    const r = svg.getBoundingClientRect()
    return screenToWorld(e.clientX - r.left, e.clientY - r.top,
      viewRef.current, r.width, r.height)
  }, [])

  const startDrag = useCallback((e: ReactPointerEvent, i: number,
    pt: [number, number]) => {
    if (e.button !== 0) return
    // The canvas must not pan while a vertex is being moved.
    e.stopPropagation()
    dragRef.current = {
      i, sx: e.clientX, sy: e.clientY, ox: pt[0], oz: pt[1],
      moved: false, x: pt[0], z: pt[1],
    }
  }, [])

  if (!w || !h || points.length < minPoints) return null

  // The dragged point follows the cursor; everything else stays where the
  // server has it.
  const pts: Array<[number, number]> = points.map((p, i) => (
    drag && drag.i === i ? [drag.x, drag.z] as [number, number] : p))
  const outline = outlineOf ? (outlineOf(pts) || []) : pts

  return (
    <g>
      {/* The shape again, on top of every fill: the selected area may well be
          buried under later ones. */}
      {outline.length >= 3 ? (
        <path d={worldPolyToPath(outline, view, w, h)} fill="none"
          stroke={color} strokeWidth={2} pointerEvents="none" />
      ) : null}
      {dashed ? (
        <path d={worldPolyToPath(pts, view, w, h, closed)} fill="none"
          stroke={color} strokeWidth={1.5} strokeDasharray="7 4"
          strokeOpacity={0.9} pointerEvents="none" />
      ) : null}
      {pts.map((a, i) => {
        // The closing edge exists only on a ring; a line ends where the last
        // point is, and an "edge" back to the start would insert points into a
        // segment that is not there.
        if (!closed && i === pts.length - 1) return null
        const b = pts[(i + 1) % pts.length]
        const pa = worldToScreen(a[0], a[1], view, w, h)
        const pb = worldToScreen(b[0], b[1], view, w, h)
        return (
          // `pointerEvents="stroke"` says so outright: the line is only there
          // to be clicked, and a transparent stroke must hit-test whatever the
          // default rule would have made of it.
          <line key={`e${i}`} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
            stroke="transparent" strokeWidth={EDGE_HIT_PX}
            pointerEvents="stroke" style={{ cursor: 'copy' }}
            onPointerDown={(e) => { e.stopPropagation() }}
            onClick={(e) => {
              const p = worldAt(e)
              if (!p) return
              let on = projectOnSegment(a, b, p.x, p.z)
              const sn = snapRef.current
              if (sn) on = sn(on[0], on[1], i + 1, e.shiftKey)
              onInsert(i + 1, r2(on[0]), r2(on[1]))
            }} />
        )
      })}
      {pts.map((p, i) => {
        const s = worldToScreen(p[0], p[1], view, w, h)
        return (
          <circle key={`v${i}`} cx={s.x} cy={s.y} r={HANDLE_R}
            fill={drag && drag.i === i ? color : '#0d1117'}
            stroke={color} strokeWidth={2}
            style={{ cursor: 'move' }}
            onPointerDown={(e) => startDrag(e, i, p)}
            onDoubleClick={(e) => { e.stopPropagation(); onDelete(i) }} />
        )
      })}
    </g>
  )
}
