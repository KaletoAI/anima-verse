/**
 * PlanCanvas — the drawing surface of the floor plan: the square that shows
 * the plot, the building contour, the rooms on the current storey and
 * everything standing in them, and that turns every press, drag and click on
 * it into an edit.
 *
 * IT OWNS NO STATE. Every value it draws and every handler it fires belongs to
 * RoomLayoutEditor; this file is the ~900 lines of SVG and pointer plumbing
 * that used to sit in the middle of that component and made it impossible to
 * read the state next to it. The split is along the one line that was already
 * true: the editor decides WHAT is true, the canvas decides how it looks and
 * what a click on it means.
 *
 * COORDINATES: everything drawn here goes through the four converters handed
 * in (`fx`/`fz` for %-positioned DOM children, `svgX`/`svgZ` for the SVG
 * overlay, which is a 0..100 user-space square). There is no fifth conversion
 * anywhere in the file, and no metre is computed from a pixel except through
 * `pointerM`.
 */
import type { Dispatch, RefObject, SetStateAction } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useToast } from '../../lib/Toast'
import { MapViewCtx } from '../map/MapCanvas'
import { PolygonHandles } from '../map/PolygonHandles'
import { snapToGrid } from '../map/mapMath'
import { groupLabel } from './placeTypes'
import type { PoseCatalog } from './placeTypes'
import { PlanFigure, PlanMetreGrid } from './PlanMeasure'
import { planLog } from './planDebug'
import {
  OPENING_COLOR, STAIR_MAX, absOutline, atOrigin, edgePointOnEdge,
  edgeSegment, fmtM, nearestPolygonEdge, normalizeOpeningEdge, outlineOf,
  planMapView, r4, rM, stairSymbol,
} from './planGeometry'
import type { PlanView, Pt, SnapResult } from './planGeometry'
import type { PlanMode } from './PlanToolbar'
import type {
  Map3D, PlacedLayout, Room, SceneRoom, SceneStairs,
} from './worldTypes'
import type { FurnishJob } from './FurnishDialog'
import type { PropSlot } from '../props/propTypes'

/** The 2D symbol of one wall opening (door swing arc, window double line,
 *  dashed passage) — shared by the editable markers and the mirrored,
 *  render-only ghosts of the neighbours' openings. */
function OpeningGlyph({ type, col }: { type?: string; col: string }) {
  // FULL-BLEED: the symbol spans the whole viewBox width — the container is
  // sized to the opening's true width_m, so any inset here would draw the
  // hole narrower than the 3D preview cuts it (the old 4..20 lines showed
  // two thirds of the real width).
  return (
    <svg viewBox="0 0 24 24" width="100%" height={24}
      preserveAspectRatio="none" style={{ overflow: 'visible' }}>
      {type === 'door' ? (
        <>
          {/* Gap in the edge line + hinge leaf + swing arc (fixed-size
              swing hint at the hinge; the GAP carries the width). */}
          <line x1={0} y1={12} x2={24} y2={12} stroke={col}
            strokeWidth={1} strokeDasharray="1.5 2" opacity={0.5} />
          <line x1={0} y1={12} x2={0} y2={22} stroke={col} strokeWidth={1.5} />
          <path d="M0 22 A10 10 0 0 0 10 12" fill="none" stroke={col} strokeWidth={1.2} />
        </>
      ) : type === 'window' ? (
        <>
          <line x1={0} y1={11} x2={24} y2={11} stroke={col} strokeWidth={1.4} />
          <line x1={0} y1={13} x2={24} y2={13} stroke={col} strokeWidth={1.4} />
        </>
      ) : (
        <line x1={0} y1={12} x2={24} y2={12} stroke={col}
          strokeWidth={2} strokeDasharray="3 2.5" />
      )}
    </svg>
  )
}

export interface PropDims { name: string; width_m: number; depth_m: number; height_m: number
  /** The prop's FILLABLE SURFACES (v5) — what the placement panel offers a
   *  value for. Always present on the library record, `[]` for most props. */
  slots?: PropSlot[] }

/** One shape the plan DRAWS: a room with its rectangle, or the yard with the
 *  rect derived from the location boundary (§ A13a). */
export interface PlanShape { room: Room; lay: PlacedLayout; ground: boolean }

/**
 * ONE PIECE the pointer is over on the plan — a prop footprint (named by its
 * room, because two rooms number their props independently) or a staircase.
 * They are edited in different rows and drawn in different layers, but they
 * are picked by the SAME gesture, so the click has one list of both.
 */
export type PlanPick =
  | { kind: 'prop'; room: string; index: number }
  | { kind: 'stair'; index: number }


interface Props {
  // ── The surface itself ────────────────────────────────────────────────
  /** The canvas element. The editor measures it and listens for the wheel on
   *  it, so the ref belongs to the editor and the element to this file. */
  canvasRef: RefObject<HTMLDivElement>
  /** Base edge in px at zoom 1, and the zoom on top of it. */
  baseW: number
  planZoom: number
  /** The edge as it REALLY is — the aids are stated in pixels. */
  canvasPx: number

  // ── The window the plan shows, and the four converters ────────────────
  /** The square metre window. Everything below is drawn through it. */
  view: PlanView
  /** Local metres → canvas fraction, for the %-positioned DOM children. */
  fx: (x: number) => number
  fz: (z: number) => number
  /** Local metres → the SVG overlay's 0..100 user space. */
  svgX: (x: number) => number
  svgZ: (z: number) => number
  /** SVG user-space units per metre — stroke widths that mean a thickness. */
  uPerM: number
  /** Canvas pixels → local metres. The ONE pixel-to-metre conversion. */
  pointerM: (clientX: number, clientY: number) => Pt

  // ── What is on the plan ───────────────────────────────────────────────
  rooms: Room[]
  map3d?: Map3D
  /** Shapes the plan draws: every room with a rectangle, plus the yard. */
  placed: PlanShape[]
  /** …of those, the ones on the storey being edited. */
  placedHere: PlanShape[]
  /** Rooms with no rectangle anywhere — the empty-plan hint names them. */
  unplaced: Room[]
  /** The composed rooms by id (§ B1) — the server's openings and walls. */
  sceneRooms: Map<string, SceneRoom>
  /** The composed block of one flight, or null while it is unknown. */
  sceneFlightAt: (index: number) => SceneStairs | null
  /** The plot in local metres, and whether it was actually drawn. */
  boundaryM: Pt[]
  hasBoundary: boolean
  /** The location has a pin on the map — the plot is drawn solid then. */
  placedOnMap: boolean
  /** The footprint of the storey on screen, and whether it is its own. */
  levelOutlinePts: Array<[number, number]>
  ownLevelOutline: boolean
  /** The storey being edited. */
  level: number
  /** Display name of the yard (§ A13a). */
  yardName: string
  /** Prop and room-model metadata, for footprints and derived sizes. */
  propDims: Record<string, PropDims>
  modelDims: Record<string, unknown>
  /** The rectangle a room's MODEL prescribes, or null. */
  derivedSize: (roomId: string) => { w: number; d: number } | null
  poseCatalog: PoseCatalog
  /** The room whose model is being calibrated — its figure is drawn. */
  calibrationRoomId: string

  // ── The selection ─────────────────────────────────────────────────────
  selected: string
  setSelected: (roomId: string) => void
  propSel: number | null
  markerSel: number | null
  setMarkerSel: Dispatch<SetStateAction<number | null>>
  openingSel: number | null
  setOpeningSel: Dispatch<SetStateAction<number | null>>
  stairSel: number | null
  setStairSel: Dispatch<SetStateAction<number | null>>
  elevatorSel: boolean
  setElevatorSel: Dispatch<SetStateAction<boolean>>
  selectedBoundary: number | null
  setSelectedBoundary: Dispatch<SetStateAction<number | null>>
  /** A click on a shape — selects, or applies the armed tool. */
  onRoomClick: (e: React.MouseEvent, shape: PlanShape) => void
  /** Cycle the selection through a stack under the pointer. */
  pickAt: (clientX: number, clientY: number, fallback: PlanPick) => void

  // ── The running gesture ───────────────────────────────────────────────
  clickMode: PlanMode
  setClickMode: Dispatch<SetStateAction<PlanMode>>
  /** Points collected so far (room hull or storey footprint). */
  outlineDraft: Pt[]
  setOutlineDraft: Dispatch<SetStateAction<Pt[]>>
  /** Where the next point would land, snapped — the rubber band. */
  hoverSnap: SnapResult | null
  setHoverSnap: Dispatch<SetStateAction<SnapResult | null>>
  /** What the pen may aim at, and the aiming radius in metres. */
  snapTargets: ReturnType<typeof import('./planGeometry').buildSnapTargets> | null
  snapTolM: number
  computeSnap: (clientX: number, clientY: number, alt: boolean) => SnapResult
  commitOutline: () => void
  commitRoomDraft: () => void
  /** The armed palette prop and its ghost under the cursor. */
  armedProp: string
  /** The room the hull pen is drawing for ('' = the selection's own). */
  drawTarget: string
  propGhost: Pt | null
  setPropGhost: Dispatch<SetStateAction<Pt | null>>
  ghostYaw: number
  /** Drawing raster in metres (0 = free hand). */
  gridStep: number

  // ── Drags (the editor owns the state; these only arm one) ─────────────
  /** Did the last prop press travel far enough to BE a drag? The canvas
   *  clears it, because the click that follows the release must not also
   *  advance the stack cycle. */
  propDraggedRef: { current: boolean }
  startDrag: (e: React.PointerEvent, room: Room, kind: 'move' | 'resize') => void
  /** Drag the room MODEL inside its room (the ⌂ handle). */
  startModelDrag: (e: React.PointerEvent, room: Room) => void
  startPropDrag: (e: React.PointerEvent, room: Room, index: number) => void
  startOpeningDrag: (e: React.PointerEvent, room: Room, index: number,
                     edge: number) => void
  startCurveDrag: (e: React.PointerEvent, room: Room, edge: number) => void
  startGhostDrag: (e: React.PointerEvent, room: Room, index: number) => void

  // ── The furnishing proposal drawn as ghosts ───────────────────────────
  furnish: FurnishJob
  reviewing: boolean
  ghostSel: number | null
  setGhostSel: Dispatch<SetStateAction<number | null>>

  // ── View aids (no geometry, only what is shown) ────────────────────────
  aids: boolean
  underlay: boolean
  bUnderlay: boolean
  underlayUrl: string
  /** The square the underlay picture covers — the SNAPSHOT frame, which is
   *  not the canvas: the canvas is the drawing window, and the two only
   *  coincide for a plot that happens to fill it. */
  snapshotFrame: { center: Pt; size: number }
  /** Where the 1.70 m reference figure stands, and how it is moved. */
  figureAt: [number, number]
  setFigurePos: Dispatch<SetStateAction<[number, number] | null>>

  // ── Writers the canvas gestures need ──────────────────────────────────
  onMap3d?: <K extends keyof Map3D>(key: K, value: Map3D[K] | undefined) => void
  /** Write the plot polygon (the 🟩 tool drags its vertices). */
  writeBoundary: (points: Pt[]) => void
  /** Which opening of the OWNING room a mirrored ghost belongs to. */
  ownerOpeningIndex: (ownerId: string, point: { x: number; y: number }) => number
}


export function PlanCanvas({
  canvasRef, baseW, planZoom, canvasPx, view, fx, fz, svgX, svgZ, uPerM,
  pointerM, rooms, map3d, placed, placedHere, unplaced, sceneRooms,
  sceneFlightAt, boundaryM, hasBoundary, placedOnMap, levelOutlinePts,
  ownLevelOutline, level, yardName, propDims, modelDims, derivedSize,
  poseCatalog, calibrationRoomId, selected, setSelected, propSel, markerSel,
  setMarkerSel, openingSel, setOpeningSel, stairSel, setStairSel, elevatorSel,
  setElevatorSel, selectedBoundary, setSelectedBoundary, onRoomClick, pickAt,
  clickMode, setClickMode, outlineDraft, setOutlineDraft, hoverSnap,
  setHoverSnap, snapTargets, snapTolM, computeSnap, commitOutline,
  commitRoomDraft, armedProp, propGhost, setPropGhost, ghostYaw, gridStep,
  propDraggedRef, startDrag, startModelDrag, startPropDrag, startOpeningDrag,
  startCurveDrag, startGhostDrag, furnish, reviewing, ghostSel, setGhostSel,
  aids, underlay, bUnderlay, underlayUrl, snapshotFrame, drawTarget,
  figureAt, setFigurePos, onMap3d,
  writeBoundary, ownerOpeningIndex,
}: Props) {
  const { t } = useI18n()
  const { toast } = useToast()
  return (
  <div
    ref={canvasRef}
    style={{
      position: 'relative',
      // SQUARE, always: the height follows the width the browser really
      // gives us. With a fixed height a narrow pane would shrink only the
      // width and squeeze every fraction-drawn overlay horizontally — on
      // a surface that claims to show metres, that is not acceptable.
      width: baseW * planZoom, aspectRatio: '1 / 1',
      maxWidth: planZoom === 1 ? '100%' : undefined,
      border: '1px solid var(--border, #30363d)', borderRadius: 6,
      background: 'rgba(255,255,255,0.03)', overflow: 'hidden', touchAction: 'none',
      cursor: clickMode || armedProp ? 'crosshair' : undefined,
    }}

    onClick={() => { if (!clickMode) setSelected('') }}
    onPointerMove={(e) => {
      if (armedProp) {
        // Placement ghost — the cursor in LOCAL METRES, on the raster
        // unless Shift asks for free hand (the click itself rasters the
        // same way, so the ghost never lies about where the prop lands).
        const [gx, gz] = pointerM(e.clientX, e.clientY)
        setPropGhost(e.shiftKey ? [gx, gz]
          : [snapToGrid(gx, gridStep), snapToGrid(gz, gridStep)])
        return
      }
      if (clickMode !== 'outline' && clickMode !== 'draw-room') return
      setHoverSnap(computeSnap(e.clientX, e.clientY, e.shiftKey))
    }}
    onPointerLeave={() => { setHoverSnap(null); setPropGhost(null) }}
    onClickCapture={(e) => {
      // Canvas-level drawing/placement (outline or room hull points,
      // elevator, boundary pass-throughs) applies at CANVAS coordinates,
      // also when the click lands inside a room — capture phase keeps
      // the room handlers out of the way.
      if (clickMode !== 'outline' && clickMode !== 'draw-room'
          && clickMode !== 'elevator' && clickMode !== 'boundary-door'
          && clickMode !== 'stairs') {
        planLog('canvas click ignored: no drawing/placement mode armed',
          { clickMode, target: (e.target as HTMLElement).tagName })
        return
      }
      e.stopPropagation()
      if (clickMode === 'outline' || clickMode === 'draw-room') {
        // Clicks go through the snap engine (Shift = free-hand); landing on
        // the first vertex closes the polygon.
        const res = computeSnap(e.clientX, e.clientY, e.shiftKey)
        planLog('canvas click -> draft point', {
          clickMode,
          drawTarget,
          raw: pointerM(e.clientX, e.clientY),
          snapped: res.p,
          kind: res.kind,
          tolM: snapTolM,
          targets: snapTargets
            ? { points: snapTargets.points.length,
                segments: snapTargets.segments.length }
            : null,
          draftLen: outlineDraft.length,
        })
        if (res.kind === 'close') {
          if (clickMode === 'outline') commitOutline()
          else commitRoomDraft()
        } else {
          setOutlineDraft((prev) => [...prev, res.p])
        }
      } else if (clickMode === 'boundary-door') {
        // Pass-through at the LOCATION edge (plan-area-detail-scenes.md):
        // the click snaps to the nearest BOUNDARY EDGE, and what is
        // stored is that edge's index plus the fraction along it
        // (contract v6 Nr. 5) — the same pair the server reads back with
        // `polygon_edge_frame`. The letters N/E/S/W are gone with the
        // square.
        const hit0 = pointerM(e.clientX, e.clientY)
        const cur = map3d?.boundary_openings || []
        if (cur.length >= 8) {
          toast(t('At most 8 boundary pass-throughs per location.'), 'error')
        } else {
          const hit = nearestPolygonEdge(boundaryM, hit0)
          onMap3d?.('boundary_openings', [...cur, {
            edge: hit.edge, at: r4(hit.at), width_m: 3,
            type: 'passage' as const,
          }])
          setSelectedBoundary(cur.length)
        }
        setClickMode('')
      } else if (clickMode === 'stairs') {
        // ONE FLIGHT PER STOREY JUMP: the click sets the FOOT, the storey
        // being edited is where it starts, and it always arrives one level
        // up — so a climb over two storeys is two clicks, one per level.
        // A fresh flight climbs south (0° = +y); the ↻ button in the row
        // below turns it in quarter steps.
        const [sx, sz] = pointerM(e.clientX, e.clientY)
        const cur = map3d?.stairs || []
        if (cur.length >= STAIR_MAX) {
          toast(t('At most {n} staircases per location.')
            .replace('{n}', String(STAIR_MAX)), 'error')
        } else {
          onMap3d?.('stairs', [...cur, {
            at: [rM(e.shiftKey ? sx : snapToGrid(sx, gridStep)),
              rM(e.shiftKey ? sz : snapToGrid(sz, gridStep))] as [number, number],
            from_level: level,
            dir_deg: 0,
          }])
          setStairSel(cur.length)
          setElevatorSel(false)
        }
        setClickMode('')
      } else {
        // The elevator is LOCAL METRES since v6 Nr. 2, like the boundary
        // it stands in.
        const [ex, ez] = pointerM(e.clientX, e.clientY)
        onMap3d?.('elevator', [
          rM(e.shiftKey ? ex : snapToGrid(ex, gridStep)),
          rM(e.shiftKey ? ez : snapToGrid(ez, gridStep))])
        setClickMode('')
      }
    }}
  >
    {/* Location boundary + building outline (existing + draft) + snap
        feedback as an SVG overlay. ALWAYS mounted: the boundary is what
        the window is built around, and a plan that does not show its own
        plot is the state this wave exists to end. */}
    <svg viewBox="0 0 100 100" preserveAspectRatio="none"
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
        {/* THE LOCATION BOUNDARY (v6 Nr. 1) — the outermost of the three
            shapes on this plan: the plot itself, the polygon whose EDGES
            the pass-throughs sit on and that every room belongs inside.
            Green, like the yard surface it encloses, so the legend under
            the plan names a colour the eye can find.

            THREE STATES, THREE STROKES, and they are the sentence the
            editor used to leave unsaid:
              * drawn AND placed — solid: ground the location covers now;
              * drawn but NOT placed — dashed: the shape a placement will
                lay down (the chip next to the plan says so in words);
              * not drawn at all — faint and dashed: this is the pin square
                standing in, not a boundary anybody drew. */}
        <polygon
          points={boundaryM.map(([x, z]) => `${svgX(x)},${svgZ(z)}`).join(' ')}
          fill="none" stroke="#3fb950" strokeWidth={0.45}
          strokeDasharray={hasBoundary && placedOnMap ? undefined : '2 1.6'}
          opacity={hasBoundary ? 0.9 : 0.35}
        />
        {/* Boundary pass-throughs: gold bars ALONG their boundary edge —
            the only overlay children that take pointer events (select).
            Point and direction come from the edge itself, so a slanted or
            concave outline carries them exactly as a square does. */}
        {(map3d?.boundary_openings || []).map((bo, i) => {
          const n = boundaryM.length
          if (!(bo.edge >= 0 && bo.edge < n)) return null
          const { a, b } = edgeSegment(boundaryM, bo.edge)
          const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
          const ux = (b[0] - a[0]) / len
          const uy = (b[1] - a[1]) / len
          const p = edgePointOnEdge(boundaryM, bo.edge, bo.at)
          // Half the opening width in SVG units — the width is metres and
          // the viewBox is 100 units across the window.
          const half = (bo.width_m / 2) * uPerM
          return (
            <line key={`bo-${i}`}
              x1={svgX(p.x) - ux * half} y1={svgZ(p.y) - uy * half}
              x2={svgX(p.x) + ux * half} y2={svgZ(p.y) + uy * half}
              stroke="#e0a356" strokeWidth={2.4} strokeLinecap="butt"
              opacity={selectedBoundary === i ? 1 : 0.7}
              style={{ pointerEvents: 'auto', cursor: 'pointer' }}
              onClick={(ev) => { ev.stopPropagation(); setSelectedBoundary(i) }}
            >
              <title>{`${t('Edge')} ${bo.edge} · ${bo.width_m} m`}</title>
            </line>
          )
        })}
        {/* THE BUILDING ON THIS STOREY (§ G). Its OWN footprint is
            drawn solid; one it merely INHERITS is dashed and paler, so a
            glance says whether this floor decides its own shape or
            follows the one below it. */}
        {levelOutlinePts.length >= 3 ? (
          <polygon
            points={levelOutlinePts.map(([x, z]) => `${svgX(x)},${svgZ(z)}`).join(' ')}
            fill={ownLevelOutline
              ? 'rgba(88,166,255,0.07)' : 'rgba(88,166,255,0.03)'}
            stroke="#58a6ff"
            strokeOpacity={ownLevelOutline ? 1 : 0.55}
            strokeWidth={0.6}
            strokeDasharray={ownLevelOutline ? undefined : '2 1.6'}
          />
        ) : null}
        {outlineDraft.length ? (
          <polyline
            points={outlineDraft.map(([x, z]) => `${svgX(x)},${svgZ(z)}`).join(' ')}
            fill="none" stroke="#e0a356" strokeWidth={0.6} strokeDasharray="2 1.4"
          />
        ) : null}
        {/* Rubber band: the running segment ends at the SNAPPED cursor,
            and the closing line back to the start point is always
            visible. */}
        {(clickMode === 'outline' || clickMode === 'draw-room') && outlineDraft.length ? (() => {
          const first = outlineDraft[0]
          const last = outlineDraft[outlineDraft.length - 1]
          const cur = hoverSnap?.p || last
          return (
            <>
              {hoverSnap ? (
                <line x1={svgX(last[0])} y1={svgZ(last[1])}
                  x2={svgX(hoverSnap.p[0])} y2={svgZ(hoverSnap.p[1])}
                  stroke="#e0a356" strokeWidth={0.6} />
              ) : null}
              {(outlineDraft.length >= 2 || hoverSnap) ? (
                <line x1={svgX(cur[0])} y1={svgZ(cur[1])}
                  x2={svgX(first[0])} y2={svgZ(first[1])}
                  stroke="#e0a356" strokeWidth={0.45}
                  strokeDasharray="1.2 1.2" opacity={0.75} />
              ) : null}
            </>
          )
        })() : null}
        {/* Snap feedback: guide ray (angle), highlighted target segment
            (edge), ring on the snapped vertex; closing rings the first
            vertex. */}
        {(clickMode === 'outline' || clickMode === 'draw-room') && hoverSnap ? (
          <>
            {hoverSnap.guide ? (
              <line x1={svgX(hoverSnap.guide.a[0])} y1={svgZ(hoverSnap.guide.a[1])}
                x2={svgX(hoverSnap.guide.b[0])} y2={svgZ(hoverSnap.guide.b[1])}
                stroke="#58a6ff" strokeWidth={0.35}
                strokeDasharray="1 1" opacity={0.8} />
            ) : null}
            {hoverSnap.seg ? (
              <line x1={svgX(hoverSnap.seg.a[0])} y1={svgZ(hoverSnap.seg.a[1])}
                x2={svgX(hoverSnap.seg.b[0])} y2={svgZ(hoverSnap.seg.b[1])}
                stroke="#58a6ff" strokeWidth={0.9} opacity={0.9} />
            ) : null}
            {hoverSnap.kind === 'vertex' || hoverSnap.kind === 'close' ? (
              <circle cx={svgX(hoverSnap.p[0])} cy={svgZ(hoverSnap.p[1])}
                r={hoverSnap.kind === 'close' ? 2.2 : 1.6} fill="none"
                stroke="#58a6ff" strokeWidth={0.5} />
            ) : null}
            {/* Length readback: `matchLen` IS metres since v6 — nothing
                multiplies a fraction by a plan width any more. The running
                segment always names its own length, so a wall is drawn to
                a number rather than to a feeling. */}
            {hoverSnap.kind === 'length' && hoverSnap.matchLen && hoverSnap.guide ? (
              <text
                x={(svgX(hoverSnap.guide.a[0]) + svgX(hoverSnap.guide.b[0])) / 2}
                y={(svgZ(hoverSnap.guide.a[1]) + svgZ(hoverSnap.guide.b[1])) / 2 - 1.5}
                fontSize={3} fill="#3fb950" textAnchor="middle"
                style={{ paintOrder: 'stroke', stroke: '#0d1117', strokeWidth: 0.6 }}>
                {`= ${fmtM(hoverSnap.matchLen)} m`}
              </text>
            ) : null}
            {outlineDraft.length ? (() => {
              const last = outlineDraft[outlineDraft.length - 1]
              const run = Math.hypot(hoverSnap.p[0] - last[0],
                                     hoverSnap.p[1] - last[1])
              if (run < 1e-6) return null
              return (
                <text
                  x={(svgX(last[0]) + svgX(hoverSnap.p[0])) / 2}
                  y={(svgZ(last[1]) + svgZ(hoverSnap.p[1])) / 2 + 3}
                  fontSize={3} fill="#e0a356" textAnchor="middle"
                  style={{ paintOrder: 'stroke', stroke: '#0d1117', strokeWidth: 0.6 }}>
                  {`${fmtM(run)} m`}
                </text>
              )
            })() : null}
          </>
        ) : null}
        {outlineDraft.map(([x, z], i) => (
          <circle key={i} cx={svgX(x)} cy={svgZ(z)} r={1.1} fill="#e0a356" />
        ))}
        {/* Placement ghost: the armed prop's TRUE footprint (dims / plan
            width) under the cursor, rotated by the R-key yaw — NEGATED,
            because SVG turns clockwise on a y-down screen while § A1.1
            does not (same reasoning and the same hand-checked case as
            PlacementLayer.tsx:105). */}
        {armedProp && propGhost ? (() => {
          const dims = propDims[armedProp]
          const gw = (dims?.width_m || 1) * uPerM
          const gd = (dims?.depth_m || 1) * uPerM
          return (
            <g transform={`translate(${svgX(propGhost[0])} ${svgZ(propGhost[1])}) rotate(${-(ghostYaw || 0)})`}
              pointerEvents="none">
              <rect x={-gw / 2} y={-gd / 2} width={gw} height={gd}
                fill="rgba(210,153,34,0.25)" stroke="#d29922"
                strokeWidth={0.5} strokeDasharray="1.4 1" />
              {/* Facing tick: the ghost's local -y edge (front). */}
              <line x1={0} y1={-gd / 2} x2={0} y2={-gd / 2 - 1.6}
                stroke="#d29922" strokeWidth={0.5} />
            </g>
          )
        })() : null}
    </svg>
    {/* The underlay covers the SNAPSHOT SQUARE, not the canvas: the
        canvas is the drawing window now, and the two only coincide for a
        plot that happens to fill it. Placed by the same metres the camera
        was pointed at, so plan and picture line up. */}
    {(underlay || bUnderlay) && underlayUrl ? (
      <img src={underlayUrl} alt="" style={{
        position: 'absolute',
        left: `${fx(snapshotFrame.center[0] - snapshotFrame.size / 2) * 100}%`,
        top: `${fz(snapshotFrame.center[1] - snapshotFrame.size / 2) * 100}%`,
        width: `${(snapshotFrame.size / view.size) * 100}%`,
        height: `${(snapshotFrame.size / view.size) * 100}%`,
        opacity: 0.9, pointerEvents: 'none',
      }} />
    ) : null}
    {aids ? (
      <PlanMetreGrid view={view} canvasPx={canvasPx} />
    ) : null}
    {placed.map((shape) => {
      const { room, lay, ground } = shape
      const isSel = room.id === selected
      // ROOM-LOCAL metres -> percent of the shape's own box. Everything
      // inside the div (hull points, curve handles, markers, props,
      // openings) goes through these two; the box itself is placed
      // with the window's `fx`/`fz`.
      const rx = (u: number) => (lay.w > 0 ? u / lay.w : 0) * 100
      const rz = (v: number) => (lay.d > 0 ? v / lay.d : 0) * 100
      // Where this shape's placements are STORED (§ A13a): `[0, 0]` in a
      // room, the yard's own min corner on the yard — `ax`/`az` are the
      // `rx`/`rz` that take a stored `at`.
      const o = atOrigin(lay, ground)
      const ax = (u: number) => rx(u - o[0])
      const az = (v: number) => rz(v - o[1])
      // The STORED layout: the yard's derived `lay` carries the shape,
      // never its content.
      const content = room.layout
      // Holes owned by a NEIGHBOUR that pierce this room's wall too:
      // WHICH ones and WHERE is the server's answer (scene payload, in
      // room-local metres) — the editor only draws them and routes a
      // click to the owning room.
      const sceneRoom = sceneRooms.get(room.id || '')
      const mirrored = (sceneRoom?.openings || []).filter((o2) => o2.mirrored)
      return (
        <div
          key={room.id}
          onPointerDown={(e) => startDrag(e, room, 'move')}
          onClick={(e) => {
            e.stopPropagation()
            if (clickMode || armedProp) onRoomClick(e, shape)
            else if (room.id && room.id === calibrationRoomId) onRoomClick(e, shape)
            else setSelected(room.id || '')
          }}
          title={ground ? `${yardName} — ${t('the location surface')}`
            : (room.name || room.id)}
          style={{
            position: 'absolute',
            left: `${fx(lay.x) * 100}%`, top: `${fz(lay.y) * 100}%`,
            width: `${(lay.w / view.size) * 100}%`,
            height: `${(lay.d / view.size) * 100}%`,
            // A drawn hull renders as its polygon (SVG below) — the div
            // stays the bbox for selection/drag but hides its rectangle.
            // The yard IS a hull (the boundary), so it never draws a box.
            border: lay.outline?.length ? 'none'
              : `2px solid ${isSel ? 'var(--accent, #58a6ff)' : 'rgba(139,148,158,0.7)'}`,
            background: lay.outline?.length ? 'transparent'
              : isSel ? 'rgba(88,166,255,0.18)' : 'rgba(139,148,158,0.12)',
            borderRadius: 4, boxSizing: 'border-box',
            // THE ROOM IS DRAWN TURNED (contract v6 addendum). One CSS
            // rotation about the box centre carries the whole shape with
            // it — hull path, curve handles, openings, markers, props,
            // label — because every child is placed in this box's own
            // frame. NEGATED for the screen: a positive plan angle turns
            // counter-clockwise in world axes (§ A1.1) while CSS turns
            // clockwise on a y-down screen, the same negation the prop
            // yaw uses below. Hit tests undo exactly this turn
            // (`localToRoom`).
            ...(lay.rotation ? {
              transform: `rotate(${-lay.rotation}deg)`,
              transformOrigin: '50% 50%',
            } : {}),
            // The yard cannot be moved — it is the plot, not a rectangle
            // on it (§ A13a).
            cursor: clickMode || armedProp ? 'crosshair'
              : ground ? 'default' : 'move',
            userSelect: 'none',
          }}
        >
          {lay.outline?.length ? (
            <svg viewBox="0 0 100 100" preserveAspectRatio="none"
              style={{ position: 'absolute', inset: 0, width: '100%',
                height: '100%', pointerEvents: 'none', overflow: 'visible' }}>
              {(() => {
                // Curved edges render as quadratic beziers — display
                // only; the committed geometry is the server's
                // tessellated payload (plan-area-detail-scenes.md).
                const pts = lay.outline!
                const curves = new Map((lay.outline_curves || [])
                  .map((c) => [c.edge, c.c] as [number, [number, number]]))
                let d = `M ${rx(pts[0][0])},${rz(pts[0][1])}`
                for (let i = 0; i < pts.length; i++) {
                  const q = pts[(i + 1) % pts.length]
                  const c = curves.get(i)
                  d += c
                    ? ` Q ${rx(c[0])},${rz(c[1])} ${rx(q[0])},${rz(q[1])}`
                    : ` L ${rx(q[0])},${rz(q[1])}`
                }
                // The YARD is the ground itself, not a built shape:
                // green and dashed, and quiet enough that the rooms
                // standing on it stay the loudest thing on the plan.
                return (
                  <path d={d + ' Z'}
                    fill={ground
                      ? (isSel ? 'rgba(63,185,80,0.14)' : 'rgba(63,185,80,0.06)')
                      : (isSel ? 'rgba(88,166,255,0.18)' : 'rgba(139,148,158,0.12)')}
                    stroke={ground
                      ? (isSel ? '#3fb950' : 'rgba(63,185,80,0.55)')
                      : (isSel ? 'var(--accent, #58a6ff)' : 'rgba(139,148,158,0.7)')}
                    strokeDasharray={ground ? '5 4' : undefined}
                    strokeWidth={2} vectorEffect="non-scaling-stroke"
                  />
                )
              })()}
              {isSel ? (lay.outline_curves || []).map((cv) => {
                const { a, b } = edgeSegment(outlineOf(lay), cv.edge)
                return (
                  <g key={cv.edge} opacity={0.6}>
                    <line x1={rx(a[0])} y1={rz(a[1])}
                      x2={rx(cv.c[0])} y2={rz(cv.c[1])}
                      stroke="#e0a356" strokeWidth={1}
                      strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
                    <line x1={rx(b[0])} y1={rz(b[1])}
                      x2={rx(cv.c[0])} y2={rz(cv.c[1])}
                      stroke="#e0a356" strokeWidth={1}
                      strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
                  </g>
                )
              }) : null}
            </svg>
          ) : null}
          {isSel && lay.outline?.length ? (lay.outline_curves || []).map((cv) => (
            <span
              key={`ctl-${cv.edge}`}
              title={t('Curve control point — drag to bend the edge; click the edge with the ◡ tool to remove the curve.')}
              onPointerDown={(e) => startCurveDrag(e, room, cv.edge)}
              onClick={(e) => {
                if (clickMode || armedProp) return
                e.stopPropagation()
              }}
              style={{
                position: 'absolute',
                left: `${rx(cv.c[0])}%`, top: `${rz(cv.c[1])}%`,
                width: 10, height: 10, marginLeft: -5, marginTop: -5,
                borderRadius: '50%', background: '#e0a356',
                border: '1px solid #0d1117', cursor: 'grab', zIndex: 5,
              }}
            />
          )) : null}
          <span style={{
            position: 'absolute', left: 3, top: 2, right: 3, fontSize: 10,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            pointerEvents: 'none',
          }}>
            {ground ? `⬚ ${yardName}` : (room.name || room.id)}
            {lay.rotation ? ` ↻${lay.rotation}°` : ''}
          </span>
          {/* The value ON the stretch it means: what this rectangle is in
              REAL metres. Hidden when the room is too small on screen to
              hold the text, and absent without a scale anchor. */}
          {(lay.w / view.size) * canvasPx >= 52
            && (lay.d / view.size) * canvasPx >= 26 ? (
            <span
              title={ground
                ? t('Bounding box of the location boundary in real metres — the yard is the boundary itself, not this rectangle.')
                : lay.outline?.length
                  ? t('Bounding box of the room hull in real metres.')
                  : t('Room size in real metres.')}
              style={{
                position: 'absolute', left: 3, bottom: 2, fontSize: 9,
                lineHeight: '11px', cursor: 'inherit',
                opacity: isSel ? 0.95 : 0.55,
                textShadow: '0 0 3px #0d1117, 0 0 3px #0d1117',
              }}
            >
              {fmtM(lay.w)} × {fmtM(lay.d)} m
            </span>
          ) : null}
          {/* Diorama-model anchor: positioned in the PLAN like a prop
              (layout.model_at, default = centre). Drag moves it; the
              strip below fine-tunes X/Y/height. */}
          {!ground && room.id === selected && modelDims[room.id] ? (() => {
            // Absent = centred, and the centre is METRES now (w/2, d/2).
            const mAt = lay.model_at || [lay.w / 2, lay.d / 2]
            return (
              <span
                title={t('Room model anchor — drag it like a prop; fine-tune X/Y/height in the strip below.')}
                onPointerDown={(e) => {
                  startModelDrag(e, room)
                }}
                onClick={(e) => {
                  if (clickMode || armedProp) return
                  e.stopPropagation()
                }}
                style={{
                  position: 'absolute',
                  left: `calc(${rx(mAt[0])}% - 9px)`,
                  top: `calc(${rz(mAt[1])}% - 9px)`,
                  width: 18, height: 18, borderRadius: 3,
                  border: '1.5px dashed #d29922',
                  background: 'rgba(210,153,34,0.18)',
                  display: 'flex', alignItems: 'center',
                  justifyContent: 'center', fontSize: 11,
                  cursor: 'grab', userSelect: 'none',
                }}
              >
                ⌂
              </span>
            )
          })() : null}
          {(content?.markers || []).map((m, i) => (
            <span
              key={`${m.group}-${i}`}
              title={`${i + 1} · ${groupLabel(poseCatalog.groups, m.group)}`}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                // An armed tool owns the click — it must reach the room
                // (a marker sitting where a prop belongs would otherwise
                // eat the placement).
                if (clickMode || armedProp) return
                e.stopPropagation()
                setSelected(room.id || '')
                setMarkerSel(i)
              }}
              style={{
                position: 'absolute',
                left: `calc(${ax(m.at[0])}% - 5px)`,
                top: `calc(${az(m.at[1])}% - 5px)`,
                width: 10, height: 10, borderRadius: '50%',
                background: '#3fb950',
                border: `2px solid ${room.id === selected && markerSel === i ? '#fff' : '#0d1117'}`,
                cursor: 'pointer',
              }}
            />
          ))}
          {/* Placed props: TRUE-size footprints (dims / plan width, never
              fit-scaled) at their room-local spot, rotated by yaw. Click
              selects, drag moves; fine-tuning in the strip below.
              The yaw is NEGATED for the screen: a plan yaw turns
              counter-clockwise in world axes (§ A1.1, and since E4 the
              renderers turn a prop with rotation.y = +rad(yaw)), while a
              CSS/SVG rotation turns clockwise on a y-down screen. Same
              reasoning and the same hand-checked case as
              PlacementLayer.tsx:105 — yaw 90 must send the local (+5, +5)
              corner to screen (+5, −5), which only rotate(−yaw) does. */}
          {(content?.props || []).map((p, i) => {
            const dims = propDims[p.prop_id]
            // True size: the prop's own metres over the room's metres.
            const fw = rx(dims?.width_m || 1)
            const fd = rz(dims?.depth_m || 1)
            const sel = room.id === selected && propSel === i
            return (
              <div
                key={`prop-${i}`}
                title={`${dims?.name || p.prop_id}${dims ? `\n${dims.width_m}×${dims.depth_m}×${dims.height_m} m` : ` · ${t('unknown prop')}`}`}
                onPointerDown={(e) => startPropDrag(e, room, i)}
                onClick={(e) => {
                  if (clickMode || armedProp) return
                  e.stopPropagation()
                  // A DRAG NEVER CYCLES: it already moved and selected its
                  // own piece (move handler, `MOVE_START_PX`). Only a
                  // press that stayed put reaches the cycle below.
                  if (propDraggedRef.current) {
                    propDraggedRef.current = false
                    return
                  }
                  // Stacked footprints — and a staircase over them:
                  // repeated clicks on the same spot walk through
                  // everything under the cursor (`pickAt`). The piece
                  // this event was raised on is the fallback for a
                  // pointer that covers nothing else.
                  pickAt(e.clientX, e.clientY,
                    { kind: 'prop', room: room.id || '', index: i })
                }}
                style={{
                  position: 'absolute',
                  left: `${ax(p.at[0])}%`, top: `${az(p.at[1])}%`,
                  width: `${fw}%`, height: `${fd}%`,
                  transform: `translate(-50%, -50%) rotate(${-(p.yaw || 0)}deg)`,
                  border: `1.5px ${dims ? 'solid' : 'dashed'} ${sel ? '#fff' : '#d29922'}`,
                  background: 'rgba(210,153,34,0.22)', borderRadius: 2,
                  boxSizing: 'border-box',
                  cursor: clickMode || armedProp ? 'crosshair' : 'grab',
                }}
              />
            )
          })}
          {/* Pending furnishing (plan-room-furnish.md): the proposed
              placements as dashed, translucent TRUE-size footprints —
              same drawing as a placed prop, amber and see-through. Click
              selects, drag moves, Del removes; nothing is stored until
              Accept. */}
          {reviewing && room.id === selected
            ? furnish.ghosts.map((p, i) => {
              const dims = propDims[p.prop_id]
              // Ghosts are placements like any other — metres from the
              // room's min corner, true size from the prop's own dims
              // (the furnish solver emits metres since the server wave).
              const fw = rx(dims?.width_m || 1)
              const fd = rz(dims?.depth_m || 1)
              return (
                <div
                  key={`ghost-${i}`}
                  title={`${t('Proposed')}: ${dims?.name || p.prop_id}`}
                  onPointerDown={(e) => startGhostDrag(e, room, i)}
                  onClick={(e) => {
                    if (clickMode || armedProp) return
                    e.stopPropagation()
                    setGhostSel(i)
                  }}
                  style={{
                    position: 'absolute',
                    left: `${ax(p.at[0])}%`, top: `${az(p.at[1])}%`,
                    width: `${fw}%`, height: `${fd}%`,
                    transform: `translate(-50%, -50%) rotate(${-(p.yaw || 0)}deg)`,
                    border: `1.5px dashed ${ghostSel === i ? '#fff' : '#d29922'}`,
                    background: 'rgba(210,153,34,0.14)', borderRadius: 2,
                    boxSizing: 'border-box', opacity: 0.75,
                    cursor: clickMode || armedProp ? 'crosshair' : 'grab',
                  }}
                />
              )
            }) : null}
          {/* Wall openings on the hull edges: door = gap + swing arc,
              window = double line, passage = dashed gap. Fixed-size SVG
              rotated to the edge's SCREEN direction — with clockwise
              winding the symbol's interior side (its local +y) then faces
              into the room; drag it along its edge. */}
          {(lay.openings || []).map((op, i) => {
            const outline = outlineOf(lay)
            const { edge, at } = normalizeOpeningEdge(op)
            if (edge >= outline.length) return null
            const pt = edgePointOnEdge(outline, edge, at)
            const seg = edgeSegment(outline, edge)
            // The hull is METRES now and so is the window, so the screen
            // angle is the edge's own angle — no aspect correction left to
            // make (the room div is w × d metres of a square canvas).
            const deg = Math.atan2(seg.b[1] - seg.a[1],
                                   seg.b[0] - seg.a[0]) * 180 / Math.PI
            const sel = room.id === selected && openingSel === i
            const col = sel ? '#fff' : (OPENING_COLOR[op.type] || '#e0a356')
            // TRUE width: the symbol spans the opening's real width_m,
            // floor 14 px so tiny openings stay clickable.
            const wPct = rx(op.width_m || 1)
            return (
              <div
                key={`op-${i}`}
                title={`${op.type} · ${op.width_m}×${op.height_m} m`}
                onPointerDown={(e) => {
                  if (clickMode) return
                  startOpeningDrag(e, room, i, edge)
                }}
                onClick={(e) => {
                  if (clickMode) return
                  e.stopPropagation()
                  setSelected(room.id || '')
                  setOpeningSel(i)
                }}
                style={{
                  position: 'absolute',
                  left: `${rx(pt.x)}%`, top: `${rz(pt.y)}%`,
                  width: `max(14px, ${wPct}%)`, height: 24,
                  transform: `translate(-50%, -50%) rotate(${deg}deg)`,
                  cursor: clickMode ? 'crosshair' : 'grab',
                }}
              >
                <OpeningGlyph type={op.type} col={col} />
              </div>
            )
          })}
          {/* Mirrored openings: one physical hole, two walls — these are
              owned by a neighbour and only RENDERED here (edit them in
              the owning room). */}
          {mirrored.map((op, i) => {
            const outline = outlineOf(lay)
            if (op.edge >= outline.length) return null
            const pt = edgePointOnEdge(outline, op.edge, op.at)
            const seg = edgeSegment(outline, op.edge)
            const deg = Math.atan2(seg.b[1] - seg.a[1],
                                   seg.b[0] - seg.a[0]) * 180 / Math.PI
            const mwPct = rx(op.width_m || 1)
            // `to` names the owning room (that is where the door leads
            // from here); the original is edited there.
            const ownerId = op.to || ''
            const ownerName = rooms.find((r) => r.id === ownerId)?.name || ownerId
            return (
              <div
                key={`mop-${i}`}
                title={`${op.type} · ${t('defined in {room} — click to edit it there').replace('{room}', ownerName)}`}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  // A shared-wall opening is one hole seen from two
                  // rooms — whichever side catches the click, EDITING
                  // happens on the original in the owning room.
                  e.stopPropagation()
                  if (clickMode || armedProp) return
                  setSelected(ownerId)
                  const idx = ownerOpeningIndex(ownerId, edgePointOnEdge(
                    absOutline(lay), op.edge, op.at))
                  if (idx >= 0) setOpeningSel(idx)
                }}
                style={{
                  position: 'absolute',
                  left: `${rx(pt.x)}%`, top: `${rz(pt.y)}%`,
                  width: `max(14px, ${mwPct}%)`, height: 24,
                  transform: `translate(-50%, -50%) rotate(${deg}deg)`,
                  opacity: 0.4, cursor: 'pointer',
                }}
              >
                <OpeningGlyph type={op.type}
                  col={OPENING_COLOR[op.type] || '#e0a356'} />
              </div>
            )
          })}
          {/* Resize handle (bottom-right) — hidden in anchored mode for
              rooms whose size DERIVES from the model's declared width
              (there is nothing to resize then, only to position). Rooms
              with a drawn hull always resize — the handle scales the
              whole polygon (points are bbox-local). */}
          {ground
            || (room.id && !lay.outline?.length && derivedSize(room.id)) ? null : (
            <span
              onPointerDown={(e) => startDrag(e, room, 'resize')}
              style={{
                position: 'absolute', right: -1, bottom: -1, width: 12, height: 12,
                cursor: 'nwse-resize',
                borderRight: '3px solid var(--accent, #58a6ff)',
                borderBottom: '3px solid var(--accent, #58a6ff)',
                borderBottomRightRadius: 4,
                opacity: isSel ? 1 : 0.35,
              }}
            />
          )}
        </div>
      )
    })}
    {map3d?.elevator ? (() => {
      // True-size elevator footprint per the client recipe: the shaft is
      // 1.8 REAL metres, so its share of the WINDOW is 1.8 / view.size.
      // On top of the rooms so it stays clickable; click selects it for
      // the sliders.
      const frac = 1.8 / view.size
      return (
        <div
          title={t('Elevator (all levels) — true shaft size from above (1.8 m × figure scale). Click to fine-tune with the sliders below.')}
          onClick={(e) => {
            if (clickMode) return
            e.stopPropagation()
            setElevatorSel(true)
            setStairSel(null)
            setMarkerSel(null)
          }}
          style={{
            position: 'absolute',
            left: `${(fx(map3d.elevator![0]) - frac / 2) * 100}%`,
            top: `${(fz(map3d.elevator![1]) - frac / 2) * 100}%`,
            width: `${frac * 100}%`, height: `${frac * 100}%`,
            background: 'rgba(139,148,158,0.5)',
            border: elevatorSel ? '2px solid #fff' : '1px solid #8b949e',
            borderRadius: 2, boxSizing: 'border-box',
            cursor: clickMode ? 'crosshair' : 'pointer',
          }}
        />
      )
    })() : null}
    {/* THE STAIRCASES — true size from above, like the elevator square:
        a 1.2 m wide rectangle running `run` metres in the climb direction,
        a line per tread, and an arrowhead at the head end that says which
        way is UP. Its own overlay ABOVE the room divs, so a flight inside
        a room stays visible and clickable; the SVG itself takes no pointer
        events, only the flights do.
        WHICH ONES: the flights that START on the level being edited, plus
        the ones ARRIVING here from the storey below — drawn faint, because
        they belong to that storey's plan and are only shown so the author
        sees where one steps out. */}
    {map3d?.stairs?.length ? (
      <svg viewBox="0 0 100 100" preserveAspectRatio="none"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
        {map3d.stairs.map((st, i) => {
          const arriving = st.from_level + 1 === level
          if (st.from_level !== level && !arriving) return null
          // THE SERVER'S FLIGHT, drawn (planGeometry.stairSymbol): the
          // rectangle, the tread lines and the arrow all sit on the
          // composed `stairs` block, so the plan cannot state a run the
          // scene does not have. No symbol = the preview has not answered
          // yet, and then nothing is drawn rather than a guess.
          const flight = sceneFlightAt(i)
          const sym = flight ? stairSymbol(flight) : null
          if (!sym) return null
          const { steps, run, outline, treads, arrow } = sym
          const sel = stairSel === i
          const col = sel ? '#f0c088' : '#8a7a66'
          return (
            <g key={`stair-${i}`}
              opacity={arriving ? 0.35 : 1}
              style={{ pointerEvents: clickMode ? 'none' : 'auto', cursor: 'pointer' }}
              onClick={(ev) => {
                ev.stopPropagation()
                // The SAME walk the prop footprints use: this overlay
                // lies over the room divs, so without it a prop under a
                // flight could never be reached (2026-08-29).
                pickAt(ev.clientX, ev.clientY, { kind: 'stair', index: i })
              }}
            >
              <title>{t('Staircase: level {a} → {b}, {n} steps, {run} m of floor')
                .replace('{a}', String(st.from_level))
                .replace('{b}', String(st.from_level + 1))
                .replace('{n}', String(steps))
                .replace('{run}', fmtM(run))}</title>
              <polygon
                points={outline.map(([x, z]) => `${svgX(x)},${svgZ(z)}`).join(' ')}
                fill="rgba(138,122,102,0.28)" stroke={col}
                strokeWidth={sel ? 0.7 : 0.45}
              />
              {treads.map(([a, b], s) => (
                <line key={s} x1={svgX(a[0])} y1={svgZ(a[1])}
                  x2={svgX(b[0])} y2={svgZ(b[1])}
                  stroke={col} strokeWidth={0.25} opacity={0.8} />
              ))}
              <polyline
                points={arrow.map(([x, z]) => `${svgX(x)},${svgZ(z)}`).join(' ')}
                fill="none" stroke={col} strokeWidth={0.6} />
            </g>
          )
        })}
      </svg>
    ) : null}
    {/* Empty plan: say where the pen is, not just that there is nothing.
        "Below" used to mean a chip row past the scale bar and three other
        blocks; the ⬠ buttons in the banner sit right above the canvas.
        Gone while a mode is armed — a sentence about the empty plan on
        top of the plan being drawn is in the way. */}
    {placedHere.length === 0 && !clickMode ? (
      <span className="ga-hint" style={{
        position: 'absolute', inset: 0, display: 'flex',
        alignItems: 'center', justifyContent: 'center', pointerEvents: 'none',
      }}>
        {unplaced.length
          ? t('No rooms on this level yet — start one with the ⬠ buttons above the plan.')
          : t('No rooms on this level yet.')}
      </span>
    ) : null}
    {/* Topmost aid: the person is what everything else is compared to. */}
    {aids ? (
      <PlanFigure view={view} pos={figureAt} onPos={setFigurePos}
        canvasRef={canvasRef} interactive={!clickMode && !armedProp} />
    ) : null}
    {/* THE BOUNDARY HANDLES — the ONE point-editing gesture of this
        codebase, the very component the map tab, the painted ground and
        the world relief are reshaped with.

        It speaks the MAP CANVAS' vocabulary (a centre + a zoom, read from
        `MapViewCtx`), so the plan window is translated once, by
        `planMapView`, and nothing else here converts anything: this canvas
        already draws in the location's LOCAL metres, which is the frame
        `map3d.boundary` is stored in. No § A1.1 pin transform is involved,
        unlike on the map — that is what makes the same gesture fit here.

        The SVG carries no viewBox on purpose: one user unit must BE one
        CSS pixel, because that is what `worldToScreen` returns. It is last
        in the canvas, so a handle sits above every room, and it is mounted
        ONLY while the tool is armed — an inline SVG hit-tests its whole
        box, so a permanently mounted overlay would eat every click meant
        for the plan. While the tool IS armed that is the wanted behaviour:
        no other gesture of this canvas is live then (rooms refuse to drag,
        the plan refuses to deselect), so a click that misses a vertex is a
        click on nothing. */}
    {clickMode === 'boundary' && hasBoundary && onMap3d ? (
      <svg style={{ position: 'absolute', inset: 0, width: '100%',
        height: '100%', overflow: 'visible' }}>
        <MapViewCtx.Provider value={planMapView(view, canvasPx)}>
          <PolygonHandles
            points={boundaryM.map(([x, z]) => [x, z] as [number, number])}
            closed
            color="#3fb950"
            minPoints={3}
            // Snapping like every other tool (user finding 2026-08-20:
            // raw handles cannot produce a straight edge): first align to
            // the NEIGHBOUR vertices' axes — that is what squares a
            // corner — then the metre grid; Shift is the universal
            // free-hand escape. Tolerance is the same pixel-constant
            // metre tolerance the room tools use.
            snap={(x, z, i, shift) => {
              if (shift) return [x, z]
              let nx = x
              let nz = z
              const n = boundaryM.length
              if (n >= 2) {
                for (const k of [(i - 1 + n) % n, (i + 1) % n]) {
                  if (k === i) continue
                  const [ax, az] = boundaryM[k]
                  if (Math.abs(nx - ax) <= snapTolM) nx = ax
                  if (Math.abs(nz - az) <= snapTolM) nz = az
                }
              }
              if (gridStep > 0) {
                // The grid must not undo an axis alignment — it only
                // rasters the coordinate the neighbours left free.
                if (nx === x) nx = snapToGrid(nx, gridStep)
                if (nz === z) nz = snapToGrid(nz, gridStep)
              }
              return [nx, nz]
            }}
            onMove={(i, x, z) => { void writeBoundary(
              boundaryM.map((pt, k) => (k === i ? [x, z] as Pt : pt))) }}
            onDelete={(i) => { void writeBoundary(
              boundaryM.filter((_, k) => k !== i)) }}
            onInsert={(i, x, z) => {
              const pts = [...boundaryM]
              pts.splice(i, 0, [x, z])
              void writeBoundary(pts)
            }}
          />
        </MapViewCtx.Provider>
      </svg>
    ) : null}
  </div>

  )
}
