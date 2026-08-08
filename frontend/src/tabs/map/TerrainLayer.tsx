/**
 * TerrainLayer — the painted ground of the free world map, drawn INSIDE the
 * `MapCanvas` SVG and underneath everything else.
 *
 * A terrain area is a polygon in WORLD METRES (contract § A1.5) — not a
 * location, so it carries no `yaw_deg` and gets NO rotation transform. The
 * footprint squares next door need `rotate(−yaw)` because they are drawn from
 * a centre plus a local frame; a terrain polygon already IS its world
 * coordinates, and turning it would move ground that nobody turned.
 *
 * Paint order is the server's: `areas` arrives bottom-to-top (`z_order` ASC,
 * then insert order) and is rendered in exactly that order, so the last entry
 * covers the ones before it — the same rule `terrain_query` uses to answer
 * "which kind is at this point". The layer never re-sorts.
 *
 * Colours come from the type catalog and from nowhere else. A kind the catalog
 * does not know is drawn grey with a warning glyph instead of being hidden: an
 * area painted with a since-deleted type still exists on the server and still
 * answers point queries, and an editor that draws nothing there would invite
 * painting a second area on top of a problem the user cannot see.
 *
 * An area drawn as a LINE is not a second kind of thing: it is an ordinary
 * polygon that happens to carry its recipe (`meta.stroke`) along. It is filled
 * and outlined like every other area; only when it is SELECTED does the centre
 * line appear, dashed, and the handles move onto it — because a ribbon is
 * reshaped by its line and its width, never by its own outline.
 *
 * All fills — the painted areas AND the default ground — share ONE opacity.
 * The metre grid is drawn by the canvas BEFORE its children, so an opaque
 * ground rectangle would swallow the scale aids ("kein Maß ohne Maßstab");
 * at 45 % the grid reads through, and painted vs. unpainted ground stay
 * directly comparable in colour because both got the same treatment.
 *
 * The polygons themselves take no pointer events. Selecting an area is a
 * point-in-polygon test on the canvas' background click (`mapMath`, the
 * server's algorithm), which is the only way to reach the TOPMOST area under
 * the cursor when several overlap. Only the vertex handles and edges of the
 * area already selected are interactive, and only while editing.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react'
import { useMapView } from './MapCanvas'
import { screenToWorld, strokeToPolygon, worldPolyToPath, worldToScreen } from './mapMath'
import type { TerrainArea, TerrainType } from './mapTypes'

/** One opacity for every fill — see the module docstring. */
const FILL_OPACITY = 0.45
/** A kind the catalog does not know: grey, and marked as unknown. */
export const UNKNOWN_COLOR = '#6e7681'
const COL_SELECTED = '#58a6ff'
const COL_DRAFT = '#3fb950'
const COL_WARN = '#d29922'

/** Vertex handle radius and the click width of an edge, in pixels. */
const HANDLE_R = 5
const EDGE_HIT_PX = 10
/** Below this travel a press on a handle stays a click (MapCanvas' value). */
const CLICK_SLOP_PX = 4

/** Metre coordinates are stored with 2 decimals (`app/models/terrain.py`);
 *  rounding here keeps what the editor draws identical to what it sent. */
const r2 = (v: number): number => Math.round(v * 100) / 100

/** The colour a kind is drawn in — catalog first, grey when unknown. */
export function typeColor(types: Record<string, TerrainType>, kind: string): string {
  const c = types[kind]?.color
  return typeof c === 'string' && c ? c : UNKNOWN_COLOR
}

/** Arithmetic mean of the vertices — good enough to hang a glyph on. */
function centroid(poly: Array<[number, number]>): [number, number] {
  let x = 0
  let z = 0
  for (const [px, pz] of poly) { x += px; z += pz }
  return [x / poly.length, z / poly.length]
}

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

export interface TerrainLayerProps {
  /** Bottom-to-top, as the server sent them. Never re-sorted here. */
  areas: TerrainArea[]
  /** The effective catalog by kind — the ONLY source of colours. */
  types: Record<string, TerrainType>
  /** Colour of the unpainted ground (the `default_kind`), empty while the
   *  catalog has not answered yet. */
  groundColor: string
  /** Vertex handles are live only while the edit-area mode is on. */
  editing: boolean
  /** The selected area may be RESHAPED. False for an area whose kind the
   *  catalog no longer knows: every write is a full replace and the server
   *  rejects the unknown kind before it reads the polygon, so offering
   *  handles would only produce a 400 per drag. The selection outline still
   *  shows — the area is selectable, just not editable until its kind is. */
  editable: boolean
  selectedId: string
  /** The CENTRE LINE of the selected area, when it was drawn as a line
   *  (`meta.stroke`, already checked by the caller) — null for an ordinary
   *  painted area. It is what the handles edit, and it is drawn dashed
   *  whenever the area is selected: the polygon is the truth, the line is the
   *  recipe, and only the recipe can be dragged back into shape. */
  centerline: Array<[number, number]> | null
  /** Width of that stroke in metres — the outline preview is regenerated from
   *  it while a line point is being dragged. */
  centerlineWidthM: number
  /** The polygon being painted (world metres) and the cursor it follows. */
  draft: Array<[number, number]>
  draftCursor: { x: number; z: number } | null
  /** The running draft is a centre LINE, not an outline: it is drawn open and
   *  the ribbon it would become is previewed underneath it. */
  draftLine: boolean
  /** Width the line draft would get, in metres. */
  draftWidthM: number
  /** Colour of the armed paint kind. */
  draftColor: string
  /** The cursor sits inside the close tolerance of the first vertex — the
   *  next click will close the ring. Always false for a line draft, which has
   *  no first point to come back to. */
  draftWillClose: boolean
  /** A finished vertex drag, in world metres. Indices are into whatever the
   *  handles sit on — the centre line when there is one, the polygon
   *  otherwise. */
  onVertexMove: (index: number, x: number, z: number) => void
  onVertexDelete: (index: number) => void
  /** Insert a vertex AT `index` (the position it takes in that list). */
  onEdgeInsert: (index: number, x: number, z: number) => void
}

export function TerrainLayer({
  areas, types, groundColor, editing, editable, selectedId, centerline,
  centerlineWidthM, draft, draftCursor, draftLine, draftWidthM, draftColor,
  draftWillClose, onVertexMove, onVertexDelete, onEdgeInsert,
}: TerrainLayerProps) {
  const { view, w, h } = useMapView()
  const [drag, setDrag] = useState<{ i: number; x: number; z: number } | null>(null)

  // Live values for the window listeners, which are installed once.
  const viewRef = useRef(view)
  viewRef.current = view
  const moveRef = useRef(onVertexMove)
  moveRef.current = onVertexMove
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
      d.x = r2(d.ox + dx / px)
      d.z = r2(d.oz + dy / px)
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

  const selected = useMemo(
    () => areas.find((a) => a.id === selectedId) || null,
    [areas, selectedId],
  )

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

  /** The draft as it is drawn: the clicked points plus, while the cursor is
   *  over the canvas, the point the next click would add. */
  const draftPts = useMemo(() => (draftCursor
    ? [...draft, [draftCursor.x, draftCursor.z] as [number, number]]
    : draft), [draft, draftCursor])

  /** The ribbon a LINE draft would become — regenerated on every click and on
   *  every cursor move. The centre line alone is not a preview: the width is
   *  what actually gets painted, and only the generated outline shows it. */
  const draftRibbon = useMemo(() => (
    draftLine && draftPts.length >= 2 ? strokeToPolygon(draftPts, draftWidthM) : null
  ), [draftLine, draftPts, draftWidthM])

  if (!w || !h) return null

  // What the handles sit on as it is being edited: the CENTRE LINE of a stroke
  // area, the polygon of an ordinary one. The dragged point follows the
  // cursor, everything else stays where the server has it.
  const editPts: Array<[number, number]> = selected
    ? (centerline || selected.polygon).map((p, i) => (
      drag && drag.i === i ? [drag.x, drag.z] as [number, number] : p))
    : []
  // A centre line is OPEN: no wrap-around edge, and two points already make
  // one — a polygon needs three and closes.
  const editClosed = !centerline
  const editMin = centerline ? 2 : 3
  // While a line point is dragged the OUTLINE follows it live; the filled area
  // underneath only catches up once the write comes back. Should the dragged
  // line degenerate on the way, the stored polygon is shown instead of nothing.
  const editOutline: Array<[number, number]> = centerline
    ? (strokeToPolygon(editPts, centerlineWidthM) || selected?.polygon || [])
    : editPts

  return (
    <g>
      <g pointerEvents="none">
        {/* Unpainted ground: the default kind, same treatment as a painted
            area so the two can be compared by eye. Empty until the catalog
            has answered — colouring the whole world grey to mean "not loaded
            yet" would be a statement about the ground, not about the load. */}
        {groundColor ? (
          <rect x={0} y={0} width={w} height={h} fill={groundColor}
            fillOpacity={FILL_OPACITY} />
        ) : null}
        {areas.map((a) => {
          if (a.polygon.length < 3) return null
          const known = !!types[a.kind]
          const color = typeColor(types, a.kind)
          const isSel = a.id === selectedId
          const c = centroid(a.polygon)
          const cp = worldToScreen(c[0], c[1], view, w, h)
          return (
            <g key={a.id}>
              {/* evenodd, not SVG's nonzero default: the engine answers point
                  queries by ray casting (`world_geometry.point_in_polygon`),
                  which IS the even-odd rule. On a bow tie the two disagree —
                  nonzero would paint a centre the engine calls OUTSIDE. */}
              <path d={worldPolyToPath(a.polygon, view, w, h)}
                fill={color} fillOpacity={FILL_OPACITY} fillRule="evenodd"
                stroke={isSel ? COL_SELECTED : color}
                strokeWidth={isSel ? 2 : 1}
                strokeOpacity={isSel ? 1 : 0.75}
                strokeDasharray={known ? undefined : '5 4'} />
              {known ? null : (
                <text x={cp.x} y={cp.y + 5} fontSize={15} textAnchor="middle"
                  fill={COL_WARN}>⚠</text>
              )}
            </g>
          )
        })}
      </g>

      {/* The centre line of the selected stroke area, dashed — the recipe is
          not the shape, so it is drawn as a hint over it and stays visible
          even where no handles are offered. */}
      {selected && centerline && editPts.length >= 2 ? (
        <path d={worldPolyToPath(editPts, view, w, h, false)} fill="none"
          stroke={COL_SELECTED} strokeWidth={1.5} strokeDasharray="7 4"
          strokeOpacity={0.9} pointerEvents="none" />
      ) : null}

      {/* Handles of the selected area — the only interactive part. */}
      {editing && selected && editPts.length >= editMin ? (
        <g>
          {/* Its outline again, on top of every fill: the selected area may
              well be buried under later ones. */}
          <path d={worldPolyToPath(editOutline, view, w, h)} fill="none"
            stroke={COL_SELECTED} strokeWidth={2} pointerEvents="none" />
          {editable ? editPts.map((a, i) => {
            // The closing edge exists only on a ring; a line ends where the
            // last point is, and an "edge" back to the start would insert
            // points into a segment that is not there.
            if (!editClosed && i === editPts.length - 1) return null
            const b = editPts[(i + 1) % editPts.length]
            const pa = worldToScreen(a[0], a[1], view, w, h)
            const pb = worldToScreen(b[0], b[1], view, w, h)
            return (
              // `pointerEvents="stroke"` says so outright: the line is only
              // there to be clicked, and a transparent stroke must hit-test
              // whatever the default rule would have made of it.
              <line key={`e${i}`} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                stroke="transparent" strokeWidth={EDGE_HIT_PX}
                pointerEvents="stroke" style={{ cursor: 'copy' }}
                onPointerDown={(e) => { e.stopPropagation() }}
                onClick={(e) => {
                  const p = worldAt(e)
                  if (!p) return
                  const on = projectOnSegment(a, b, p.x, p.z)
                  onEdgeInsert(i + 1, r2(on[0]), r2(on[1]))
                }} />
            )
          }) : null}
          {editable ? editPts.map((p, i) => {
            const s = worldToScreen(p[0], p[1], view, w, h)
            return (
              <circle key={`v${i}`} cx={s.x} cy={s.y} r={HANDLE_R}
                fill={drag && drag.i === i ? COL_SELECTED : '#0d1117'}
                stroke={COL_SELECTED} strokeWidth={2}
                style={{ cursor: 'move' }}
                onPointerDown={(e) => startDrag(e, i, p)}
                onDoubleClick={(e) => { e.stopPropagation(); onVertexDelete(i) }} />
            )
          }) : null}
        </g>
      ) : null}

      {/* The polygon being painted: an OPEN line to the cursor, closed only
          when the click actually closes it. A LINE draft never closes — what
          it fills is the generated ribbon under the centre line. */}
      {draft.length ? (
        <g pointerEvents="none">
          {/* Same even-odd rule as a saved area: the preview must show the
              shape the engine will read back, self-crossings included. */}
          {draftLine ? (
            <>
              {draftRibbon ? (
                <path d={worldPolyToPath(draftRibbon, view, w, h)}
                  fill={draftColor} fillOpacity={FILL_OPACITY * 0.6}
                  fillRule="evenodd"
                  stroke={draftColor} strokeWidth={1} strokeOpacity={0.8} />
              ) : null}
              <path d={worldPolyToPath(draftPts, view, w, h, false)} fill="none"
                stroke={COL_DRAFT} strokeWidth={2} strokeDasharray="6 3" />
            </>
          ) : (
            <path d={worldPolyToPath(draftPts, view, w, h, draft.length >= 3)}
              fill={draft.length >= 3 ? draftColor : 'none'}
              fillOpacity={draft.length >= 3 ? FILL_OPACITY * 0.6 : 0}
              fillRule="evenodd"
              stroke={COL_DRAFT} strokeWidth={2} strokeDasharray="6 3" />
          )}
          {draft.map((p, i) => {
            const s = worldToScreen(p[0], p[1], view, w, h)
            const first = i === 0
            return (
              <circle key={`d${i}`} cx={s.x} cy={s.y}
                r={first && draftWillClose ? HANDLE_R + 3 : 3}
                fill={first && draftWillClose ? COL_DRAFT : '#0d1117'}
                stroke={COL_DRAFT} strokeWidth={2} />
            )
          })}
        </g>
      ) : null}
    </g>
  )
}
