/**
 * WorldPropLayer — the AUTHORED props on the world plane (§ A9a) as map
 * markers: a landmark rock, a signpost, a bench in the wilderness.
 *
 * A world prop is a POINT, not an area, so this layer follows
 * `PlacementLayer` rather than `TerrainLayer`: every marker carries its own
 * pointer handler with a transparent hit disc, and the drag is the same
 * window-listener gesture (slop, live preview, ONE commit on release).
 *
 * Geometry only — no text, no `t()`. Everything the user reads lives in the
 * chip and the tray of `MapTab`, the same split the placement layer keeps.
 *
 * The yaw sign is the placement layer's: a stored `yaw_deg` is a § A1.1 world
 * angle, and an SVG `rotate()` turns the other way, so it is NEGATED for the
 * marker and its direction pin.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useMapView } from './MapCanvas'
import { worldToScreen } from './mapMath'
import type { WorldProp } from './mapTypes'

/** Movement below this is a click, not a drag (the placement layer's slop). */
const CLICK_SLOP_PX = 4
/** Marker radius and the invisible disc that keeps it clickable when zoomed out. */
const MARK_R = 5
const HIT_PX = 12
/** How far the facing pin sticks out of the marker. */
const FACE_PX = 14

const COL_PROP = '#a371f7'
const COL_SELECTED = '#58a6ff'
const COL_GHOST = '#3fb950'

interface WorldPropLayerProps {
  worldProps: readonly WorldProp[]
  selectedId: string
  onSelect: (id: string) => void
  /** Commits ONE finished drag in world metres. */
  onMove: (id: string, x: number, z: number) => void
  /** Metre grid the drag snaps to; 0 = centimetres. */
  snapM: number
  /** Armed prop preview: where the pointer is, or null. */
  ghostPt: { x: number; z: number } | null
}

export function WorldPropLayer({ worldProps, selectedId, onSelect, onMove,
                                snapM, ghostPt }: WorldPropLayerProps) {
  const { view, w, h } = useMapView()
  const [drag, setDrag] = useState<{ id: string; x: number; z: number } | null>(null)

  const viewRef = useRef(view); viewRef.current = view
  const snapRef = useRef(snapM); snapRef.current = snapM
  const moveRef = useRef(onMove); moveRef.current = onMove
  const dragRef = useRef<{
    id: string; sx: number; sy: number; ox: number; oz: number
    moved: boolean; x: number; z: number
  } | null>(null)

  // Bound ONCE: a drag that leaves the marker (or the canvas) has to keep
  // arriving, and re-binding on every state change would drop it mid-gesture.
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
      // ONE write per gesture — a PUT per pointermove would be a hundred.
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

  const startDrag = useCallback((e: React.PointerEvent, wp: WorldProp) => {
    if (e.button !== 0) return
    e.stopPropagation()          // the canvas must not pan
    onSelect(wp.id)
    dragRef.current = { id: wp.id, sx: e.clientX, sy: e.clientY,
                        ox: wp.x, oz: wp.z, moved: false, x: wp.x, z: wp.z }
  }, [onSelect])

  if (!w || !h) return null

  // Selection LAST so it is never covered by a marker drawn after it.
  const ordered = [...worldProps].sort((a, b) => (
    a.id === selectedId ? 1 : b.id === selectedId ? -1 : 0))

  return (
    <g>
      {ordered.map((wp) => {
        const dragging = drag && drag.id === wp.id
        const p = worldToScreen(dragging ? drag.x : wp.x,
                                dragging ? drag.z : wp.z, view, w, h)
        const sel = wp.id === selectedId
        const col = sel ? COL_SELECTED : wp.missing ? '#d29922' : COL_PROP
        const rad = ((wp.yaw_deg || 0) * Math.PI) / 180
        // Local −z is "forward" (§ A1.1), and screen z grows downwards.
        const fx = p.x - FACE_PX * Math.sin(rad)
        const fy = p.y - FACE_PX * Math.cos(rad)
        return (
          <g key={wp.id} style={{ cursor: 'move' }}
             onPointerDown={(e) => startDrag(e, wp)}>
            <line x1={p.x} y1={p.y} x2={fx} y2={fy}
                  stroke={col} strokeWidth={1.5} strokeOpacity={0.9} />
            <circle cx={p.x} cy={p.y} r={MARK_R} fill={col} fillOpacity={0.55}
                    stroke={col} strokeWidth={sel ? 2 : 1} />
            {wp.missing ? (
              <circle cx={p.x} cy={p.y} r={MARK_R + 3} fill="none"
                      stroke={col} strokeWidth={1} strokeDasharray="3 3" />
            ) : null}
            <circle cx={p.x} cy={p.y} r={HIT_PX} fill="transparent" stroke="none" />
          </g>
        )
      })}
      {ghostPt ? (() => {
        const p = worldToScreen(ghostPt.x, ghostPt.z, view, w, h)
        return (
          <g pointerEvents="none">
            <circle cx={p.x} cy={p.y} r={MARK_R} fill={COL_GHOST}
                    fillOpacity={0.4} stroke={COL_GHOST} strokeWidth={1.5} />
            <circle cx={p.x} cy={p.y} r={MARK_R + 5} fill="none"
                    stroke={COL_GHOST} strokeWidth={1} strokeDasharray="3 3" />
          </g>
        )
      })() : null}
    </g>
  )
}
