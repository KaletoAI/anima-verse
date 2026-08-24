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
 *
 * Beside the marker each placement draws its GROUND FOOTPRINT (§ A9b): the
 * rotated rectangle the prop really covers, in true metres, out of the server's
 * `prop_boxes` and the shared `propBoxFootprint` — the same shape the scatter
 * keeps clear and the 3D client stands the mesh in. A marker says WHERE a
 * bench is, only the rectangle says whether it fits between two houses.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { propBoxFootprint } from '@anima/scene-render'
import { useMapView } from './MapCanvas'
import {
  GRID_MIN_SPACING_PX, gridLinesInView, snapToGrid, worldPolyToPath,
  worldToScreen,
} from './mapMath'
import type { WorldProp, WorldPropBox } from './mapTypes'

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
/** The snap raster. Drawn ON TOP of the ground, so it has to stay faint —
 *  it is an aid for the hand, not a layer of the world. Every fifth line
 *  reads a little stronger, the same rhythm the canvas' metre grid uses. */
const COL_GRID = '#58a6ff'

/** Below this SHORTER on-screen edge a footprint stops being a rectangle and
 *  becomes a smudge under the marker — the same reason (and the same number)
 *  the metre grid stops drawing its lines at `GRID_MIN_SPACING_PX`. The prop
 *  still stands there and its marker still shows; only the outline waits for
 *  a zoom level at which it says something. */
const BOX_MIN_PX = GRID_MIN_SPACING_PX

interface WorldPropLayerProps {
  worldProps: readonly WorldProp[]
  selectedId: string
  onSelect: (id: string) => void
  /** Commits ONE finished drag in world metres. */
  onMove: (id: string, x: number, z: number) => void
  /** Metre grid the drag snaps to AND the layer draws; 0 = off (centimetres).
   *  The caller zeroes it outside the props tool, so nothing is drawn and
   *  nothing snaps where props are not being edited. */
  snapM: number
  /** Armed prop preview: where the pointer is, or null. */
  ghostPt: { x: number; z: number } | null
  /** The GROUND BOX of every placement (§ A9b) as the server resolved it —
   *  half the real width and depth of the VARIANT the placement shows, plus
   *  the server's margin. Only the two half-extents are read here: the centre
   *  and the turn are taken from the live (dragged, just-rotated) placement,
   *  so the rectangle follows the hand instead of the last save. */
  boxes?: readonly WorldPropBox[]
  /** Draw those rectangles at all. The caller turns them on inside the props
   *  tool: a footprint is an authoring aid, and outside that tool the map is
   *  about locations. */
  showBoxes?: boolean
}

export function WorldPropLayer({ worldProps, selectedId, onSelect, onMove,
                                snapM, ghostPt, boxes,
                                showBoxes }: WorldPropLayerProps) {
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
      // SHIFT is the escape hatch — the same modifier the boundary handles
      // already call "free-hand, as everywhere" (`PolygonHandles.snap`). Hold
      // it and the raster lets go for this one move, so a rock can sit where
      // no line runs. One modifier for one meaning across the whole tab.
      const step = e.shiftKey ? 0 : snapRef.current
      d.x = snapToGrid(d.ox + dx / px, step)
      d.z = snapToGrid(d.oz + dy / px, step)
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

  /** The raster to draw. Empty whenever the grid is off OR its lines would
   *  crowd closer than `GRID_MIN_SPACING_PX` on screen — `gridLinesInView`
   *  decides both, so the drawing and the smoke check agree by construction. */
  const grid = useMemo(() => gridLinesInView(view, w, h, snapM),
    [view, w, h, snapM])

  /** `id -> the two half-extents of that placement's ground box`, in metres.
   *  A placement the server handed no box (its prop record is gone, or it
   *  stands inside a location's outline — § A9b names both) is not in here
   *  and draws no rectangle: there is no size to draw. */
  const halves = useMemo(() => {
    const out = new Map<string, { hw: number; hd: number }>()
    for (const box of boxes || []) {
      const hw = Number(box.half_w)
      const hd = Number(box.half_d)
      if (hw > 0 && hd > 0) out.set(box.id, { hw, hd })
    }
    return out
  }, [boxes])

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

  // The world x/z of a grid line as a canvas pixel. `worldToScreen` answers
  // both coordinates at once; only one of them is wanted per axis.
  const gx = (x: number) => worldToScreen(x, 0, view, w, h).x
  const gz = (z: number) => worldToScreen(0, z, view, w, h).y

  return (
    <g>
      {/* The snap raster, FIRST — under every marker, and inert: a click on a
          grid line is a click on the ground. */}
      {grid.xs.length || grid.zs.length ? (
        <g pointerEvents="none" stroke={COL_GRID} strokeWidth={1}>
          {grid.xs.map((x) => (
            <line key={`gx${x}`} x1={gx(x)} y1={0} x2={gx(x)} y2={h}
              opacity={Math.round(x / snapM) % 5 === 0 ? 0.34 : 0.14} />
          ))}
          {grid.zs.map((z) => (
            <line key={`gz${z}`} x1={0} y1={gz(z)} x2={w} y2={gz(z)}
              opacity={Math.round(z / snapM) % 5 === 0 ? 0.34 : 0.14} />
          ))}
        </g>
      ) : null}
      {ordered.map((wp) => {
        const dragging = drag && drag.id === wp.id
        const wx = dragging ? drag.x : wp.x
        const wz = dragging ? drag.z : wp.z
        const p = worldToScreen(wx, wz, view, w, h)
        const sel = wp.id === selectedId
        const col = sel ? COL_SELECTED : wp.missing ? '#d29922' : COL_PROP
        const rad = ((wp.yaw_deg || 0) * Math.PI) / 180
        // The GROUND the prop really covers (§ A9b): the server's half-extents
        // — the ones of the VARIANT this placement shows — around the LIVE
        // point and the LIVE turn, through the one rotation the sampler and
        // the 3D client run on (`propBoxFootprint`). Nothing is measured here;
        // this layer only draws what the server resolved.
        const half = showBoxes ? halves.get(wp.id) : undefined
        const foot = half && Math.min(half.hw, half.hd) * 2 * view.pxPerM
          >= BOX_MIN_PX
          ? propBoxFootprint({ x: wx, z: wz, yaw_deg: wp.yaw_deg || 0,
                               half_w: half.hw, half_d: half.hd })
          : null
        // Local −z is "forward" (§ A1.1), and screen z grows downwards.
        const fx = p.x - FACE_PX * Math.sin(rad)
        const fy = p.y - FACE_PX * Math.cos(rad)
        return (
          <g key={wp.id} style={{ cursor: 'move' }}
             onPointerDown={(e) => startDrag(e, wp)}>
            {foot ? (
              <path d={worldPolyToPath(foot.points, view, w, h)}
                    fill="none" stroke={col} strokeWidth={1}
                    strokeOpacity={sel ? 0.85 : 0.5} pointerEvents="none" />
            ) : null}
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
