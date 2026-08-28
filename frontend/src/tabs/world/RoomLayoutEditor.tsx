/**
 * RoomLayoutEditor — the floor plan of a location (AV3D-2), embedded in the
 * location editor's "Floor plan" tab.
 *
 * EVERYTHING HERE IS METRES (contract v6 Nr. 2, "the metric wave"). A room's
 * `x`/`y` is its min corner in LOCATION-LOCAL metres around the anchor pin
 * (negative values are ordinary), `w`/`d` are metres, and outline points,
 * markers, props and `model_at` are metres from the room's own min corner.
 * Only an opening's `at` is still a fraction of its edge.
 *
 * THE YARD IS THE ONE EXCEPTION (§ A13a): the ground room has no rectangle —
 * its surface IS the location boundary — so its `props[].at` / `markers[].at`
 * are LOCATION-LOCAL metres directly. The editor derives a VIEW-ONLY rect
 * from the boundary's bounding box (`yardLay`) so the plan's room-local
 * percentage math keeps working, and `atOrigin` is the one place the two
 * frames meet. Nothing derived here is ever stored: the yard's layout leaves
 * this editor carrying placements and nothing else.
 *
 * The canvas shows a square metre WINDOW of that frame (`PlanView`): the
 * bounding box of the drawn boundary — or of the placed rooms when there is no
 * boundary — plus a margin, so the whole plot is always reachable and a room
 * may be drawn ANYWHERE in it. The window is the only place a metre becomes a
 * fraction of the canvas; nothing about it is stored.
 *
 * THREE SHAPES LIE ON THIS PLAN, and the legend under the canvas names all
 * three because nothing else did: the LOCATION BOUNDARY (green — the plot, the
 * outermost shape, `map3d.boundary`), the BUILDING CONTOUR (blue — the house
 * standing on it, `map3d.outline`) and the ROOMS (grey — what can actually be
 * entered). Drawing the contour in the belief that it was a room is what earns
 * the server's correct-but-late `rooms_without_layout` finding, so the contour
 * tool says what it draws while it is armed.
 *
 * The boundary is EDITABLE HERE, with the very `PolygonHandles` gesture the
 * map tab uses, and through the same write path (`boundaryApi`) — the map tab
 * drags its vertices in world metres and converts them back through the § A1.1
 * pin transform, this canvas already draws in the local metres the field is
 * stored in and converts nothing. A location that is NOT placed keeps its
 * boundary (it is the location's own shape, not a piece of the map), and the
 * plan says so instead of showing one polygon for two different states.
 *
 * The pane is three columns:
 * [PlanToolbar 44px] [canvas 420px] [PlanSidePanel]. Rooms are drawn as
 * polygon hulls on the building footprint: drag to move, corner handle to
 * resize; the icon toolbar rotates in 90° steps, places animation markers
 * (spots a figure with a matching animation snaps to —
 * kinds from the OPEN clip vocabulary, nothing hardcoded) with one click
 * inside the room, and draws the building outline / places the elevator
 * (AV3D-12) and the staircases (one flight per storey jump). Everything edits
 * the LOCATION draft (rooms[].layout, map3d) and is
 * persisted by the location's Save button — the external 3D client reads the
 * layout from /world/locations; rooms without a layout fall back to its
 * auto-grid.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { SliderInput } from '../../components/SliderInput'
import {
  CLOSE_TOL_PX, MIN_ROOM_M, MIN_WINDOW_EDGE_M, OPENING_COLOR, OPENING_DEFAULT,
  PLAN_MAX_M, SNAP_TOL_PX, absOutline, buildSnapTargets, clamp,
  edgePointOnEdge, edgeSegment, exteriorEdges, fmtM, localToRoom,
  nearestPolygonEdge, normalizeOpeningEdge, outlineOf, planMapView, r4, rM,
  rotateAbout,
  sharedEdges, snapDrawPoint, snapMoveOffset, snapToGrid,
  stairSymbol, STAIR_MAX, viewFx, viewFz,
  viewMx, viewMz, viewportFor,
} from './planGeometry'
import type { PlanView, PolyRoom, Pt, SnapResult } from './planGeometry'
import {
  BOUNDARY_SEED_M, boundaryComplaint, putLocationBoundary, seedSquare,
} from './boundaryApi'
import { MapViewCtx } from '../map/MapCanvas'
import { PolygonHandles } from '../map/PolygonHandles'
import { FurnishDialog, useFurnishJob } from './FurnishDialog'
import { PlanFigure, PlanMetreGrid, PlanScaleBar } from './PlanMeasure'
import { PlanSidePanel } from './PlanSidePanel'
import { PlanToolbar } from './PlanToolbar'
import type { PlanMode } from './PlanToolbar'
import { PropVariantPicker } from './PropVariantPicker'
import { OpeningDoorProp } from './DoorPropPicker'
import type { PropSlot } from '../props/propTypes'
import { getRoomModelDims, renderTopDownSnapshot } from './topDownSnapshot'
import type { SurfaceMaterialSpec } from '@anima/scene-render'
import type { Map3D, PlacedLayout, Room, RoomLayout, RoomOpening, SceneProblem, SceneRoom, ScenePayload, SurfaceKind } from './worldTypes'
import { GROUND_ROOM_ID, groundRoomLabel, hasRect, readMapWater } from './worldTypes'
import { groupKeys, groupLabel, newId, posesInGroup, usePoseCatalog } from './placeTypes'
import { isWaterKind } from '../map/mapTypes'
import type { TerrainTypesResp } from '../map/mapTypes'

const CANVAS_W = 420
/** Under this side length a room is not a small room but a LEFTOVER: in the
 *  fraction era `layout.x/y/w/d` were shares of a reference square, and the
 *  metre wave reinterprets those numbers as metres without converting them
 *  (contract v6 Nr. 2 — "no migration code, a world from the fraction era
 *  simply delivers tiny rooms"). Half a metre is well below any real room and
 *  well above the centimetre rounding, so it separates the two cleanly. */
const TINY_ROOM_M = 0.5
/** Edge of the drawing window when there is nothing at all to frame — no
 *  boundary, no room, no building outline. Ten metres is a room-sized plot,
 *  which is what a location starts as. */
const FALLBACK_VIEW_M = 10
/** Rasters the grid selector offers, in metres (0 = free hand). */
const GRID_STEPS = [0, 0.1, 0.25, 0.5, 1, 2] as const

/**
 * `?planDebug=1` — trace the DRAW PATH to the console.
 *
 * "I cannot draw" is a report about something that did NOT happen, and every
 * step of the pen has its own early return: the tool may refuse to arm, the
 * click may never reach the canvas, the snap engine may move the point, the
 * commit may reject the hull. Off the flag nothing is logged and nothing is
 * computed; on it, every one of those exits names itself, so the next report
 * carries the exit instead of the symptom.
 */
const PLAN_DEBUG = typeof window !== 'undefined'
  && new URLSearchParams(window.location.search).get('planDebug') === '1'
const planLog = (step: string, data?: unknown) => {
  if (PLAN_DEBUG) console.info(`[plan] ${step}`, data ?? '')
}

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

interface RoomLayoutEditorProps {
  rooms: Room[]
  onChange: (rooms: Room[]) => void
  /** Location id — the building-underlay + auto plan width need its model. */
  locationId?: string
  /** Location map3d draft — the editor draws/edits the building outline and
   *  the elevator position (AV3D-12) in it. */
  map3d?: Map3D
  onMap3d?: <K extends keyof Map3D>(key: K, value: Map3D[K] | undefined) => void
  /** Does the location stand on the world map (`pos_x`/`pos_z` set)?
   *
   *  The BOUNDARY exists either way — it is drawn in the location's own local
   *  metres and survives unplacing by design — but what it MEANS depends on
   *  this: placed, it is ground the location covers right now; unplaced, it is
   *  the shape that will be laid down the moment somebody places it. The plan
   *  says which of the two it is looking at, instead of showing one polygon
   *  for both states (user finding 2026-08-20). */
  placedOnMap?: boolean
  /** Server verdict (Location.has_entrance): does this location carry any
   *  boundary pass-through at all? Since the free-boundary rule (E4 task 5)
   *  that is a HINT, not a verdict on reachability: a location without any
   *  opening can be entered anywhere along its edge, one WITH openings only
   *  across them. The boundary-openings section says so; it does not
   *  re-derive the rule. */
  hasEntrance?: boolean
  /** Reports the selected room id ('' = none) — the Floor-plan tab shows the
   *  model adjustment strip for it. */
  onSelectRoom?: (roomId: string) => void
  /** The server-composed scene of the current draft (useScenePreview in the
   *  parent, shared with the 3D preview). Its per-room block delivers the
   *  neighbours' shared-wall openings in plan fractions — the editor DRAWS
   *  them, it does not derive them. */
  scene?: ScenePayload | null
  /** While the calibration figure is on for this room, a plain click inside
   *  it moves the figure (fraction of the room rectangle, UI state only). */
  calibrationRoomId?: string
  onCalibrationAt?: (at: [number, number]) => void
  /** Pose the 3D preview figures of a marker play, keyed by marker id —
   *  pure VIEW state the parent shares with FloorPlanPreview; absent = the
   *  place type's default pose. The ◀ ▶ cycler in the marker strip writes it. */
  previewPose?: Record<string, string>
  onPreviewPose?: (markerId: string, poseKey: string) => void
  /** The location draft carries unsaved changes. Actions that work on the
   *  STORED world have to know: a room that only exists in this draft does
   *  not exist for them. */
  unsaved?: boolean
  /** The location's `default_door_prop_id` — READ only, so the opening panel
   *  can name the door an opening inherits when it chooses nothing. The
   *  field itself is edited on the Floor-plan tab, beside the plan. */
  defaultDoorPropId?: string
  /** Rendered at the bottom INSIDE the editor's frame — the Floor-plan tab
   *  slots the model adjustment strip of the selected room here. */
  children?: ReactNode
}

/** How far the pointer has to travel before a press on a room BECOMES a
 *  move. Below it the press is only a selection — clicking a room to work on
 *  it used to nudge it by whatever the hand did (user finding 2026-07-28). */
const MOVE_START_PX = 4

type DragState =
  // `mPerPx` is FROZEN at drag start on purpose: the drawing window is derived
  // from the placed rooms, so a room dragged towards the edge widens the
  // window — reading the live scale would then change the metres-per-pixel
  // mid-drag and the rectangle would run away from the cursor.
  | { kind: 'move'; roomId: string; startX: number; startY: number; origX: number; origY: number; mPerPx: number; moving?: boolean }
  | { kind: 'resize'; roomId: string; startX: number; startY: number; origW: number; origD: number; mPerPx: number }
  | { kind: 'opening'; roomId: string; index: number; edge: number }
  | { kind: 'curveCtl'; roomId: string; edge: number }
  // A prop press carries its start point for the SAME `MOVE_START_PX`
  // threshold a room move uses: below it the press stays a click, and only a
  // click may advance the stack cycle (see `startPropDrag`).
  | { kind: 'prop'; roomId: string; index: number; startX: number; startY: number; moving?: boolean }
  | { kind: 'ghost'; roomId: string; index: number }
  | { kind: 'model'; roomId: string }
  | null

/** Real prop dims for true-size footprints — lean mirror of /world/props.
 *
 *  The PRIMARY variant's dims, deliberately: the size belongs to the model
 *  variant (2026-08-25) and the 2D plan draws the object, not one of its
 *  versions — so it uses the same answer every unqualified read gives. The 3D
 *  preview beside it reads the scene payload, which IS resolved per variant
 *  (`props.variant_dims`), so the finished scene is always right — only this
 *  schematic footprint stays the primary variant's. */
interface PropDims { name: string; width_m: number; depth_m: number; height_m: number
  /** The prop's FILLABLE SURFACES (v5) — what the placement panel offers a
   *  value for. Always present on the library record, `[]` for most props. */
  slots?: PropSlot[] }

/** One shape the plan DRAWS: a room with its rectangle, or the yard with the
 *  rect derived from the location boundary (§ A13a). */
interface PlanShape { room: Room; lay: PlacedLayout; ground: boolean }

/**
 * The hulls of a room list as the geometry helpers (`buildSnapTargets`,
 * `sharedEdges`, `exteriorEdges`) want them. Only rooms with a RECTANGLE get
 * in, which is what keeps the yard out of every wall, snap and opening
 * derivation — it has no rectangle at all (§ A13a).
 */
function hullsOf(list: Room[], level: number, skipId = ''): PolyRoom[] {
  const out: PolyRoom[] = []
  for (const r of list) {
    const lay = r.layout
    if (!r.id || r.id === skipId || !hasRect(lay)) continue
    if ((lay.level || 0) !== level) continue
    // `rotation` rides along: the hull a neighbour shares, a snap target or
    // an exterior wall is the room as DRAWN, i.e. turned (v6 addendum).
    out.push({ id: r.id, x: lay.x, y: lay.y, w: lay.w, d: lay.d,
               outline: lay.outline, rotation: lay.rotation })
  }
  return out
}

/**
 * THE ONE PLACE THE TWO PLACEMENT FRAMES MEET (§ A13a).
 *
 * `props[].at` / `markers[].at` are stored ROOM-LOCAL in a room and
 * LOCATION-LOCAL on the yard. This returns the min corner of the shape IN THE
 * COORDINATES THOSE `at` VALUES ARE STORED IN — `[0, 0]` for a room, the
 * derived bounding box's corner for the yard. Two consequences, and they are
 * the whole conversion:
 *
 *   room-local metres (what `rx`/`rz` want) = stored `at` − atOrigin
 *   stored `at` = `storedAt(...)` of the plan point, clamped to
 *                 atOrigin … atOrigin + w/d
 *
 * For an ordinary room both collapse to what the editor always did.
 */
const atOrigin = (lay: PlacedLayout, ground: boolean): Pt =>
  (ground ? [lay.x, lay.y] : [0, 0])

/**
 * A plan point (LOCATION-local metres) in the frame `at` is STORED in: the
 * yard's `at` already is a location metre, a room's is room-local — and a
 * TURNED room's is room-local in its STRAIGHT frame, so the cursor has to be
 * turned back (contract v6 addendum). The inverse of what the room div is
 * drawn with; without it every drag on a turned room would drop the piece
 * somewhere else.
 */
const storedAt = (lay: PlacedLayout, ground: boolean, p: Pt): Pt =>
  (ground ? p : localToRoom(lay, p))

const NO_PREVIEW_POSES: Record<string, string> = {}

export function RoomLayoutEditor({ rooms, onChange, locationId = '', map3d, onMap3d, placedOnMap = true, hasEntrance, onSelectRoom, scene = null, calibrationRoomId = '', onCalibrationAt, previewPose = NO_PREVIEW_POSES, onPreviewPose, unsaved = false, defaultDoorPropId = '', children }: RoomLayoutEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [level, setLevel] = useState(0)
  const [selected, setSelectedRaw] = useState<string>('')
  const setSelected = useCallback((id: string) => {
    setSelectedRaw(id)
    setMarkerSel(null)
    setOpeningSel(null)
    setPropSel(null)
    setElevatorSel(false)
    setStairSel(null)
    onSelectRoom?.(id)
  }, [onSelectRoom])
  // Click-to-place modes: the next click inside the room drops an animation
  // marker of the chosen kind, or places a wall opening on the nearest edge.
  const [clickMode, setClickMode] = useState<PlanMode>('')
  // Prop palette open in the side panel (🪑 tool) — presentation only, the
  // placement logic is not part of this editor yet. The armed prop is just
  // the highlighted palette card; nothing on the plan reads it so far.
  const [propsOpen, setPropsOpen] = useState(false)
  const [armedProp, setArmedProp] = useState('')
  // Selected placement (index into the selected room's layout.props) for the
  // adjustment strip below the plan.
  const [propSel, setPropSel] = useState<number | null>(null)
  // Ghost while placing: snapped-to-nothing cursor in PLAN fractions + the
  // yaw the R key steps in 90° increments (fine yaw lives in the strip).
  const [propGhost, setPropGhost] = useState<[number, number] | null>(null)
  const [ghostYaw, setGhostYaw] = useState(0)
  // Furnishing job of the SELECTED room ("✨ Furnish", plan-room-furnish.md).
  // One hook for dialog AND ghost layer — a single poll, one ghost list.
  const [furnishOpen, setFurnishOpen] = useState(false)
  const [ghostSel, setGhostSel] = useState<number | null>(null)
  // WHICH job the ✨ Furnish button drives. The yard's reserved id repeats in
  // every location, so its job is keyed by the composite `__ground__@<loc>`
  // (server contract, § A13a); an ordinary room is its own id.
  const furnishTarget = selected === GROUND_ROOM_ID && locationId
    ? `${GROUND_ROOM_ID}@${locationId}` : selected
  const furnish = useFurnishJob(furnishTarget, furnishOpen)
  const furnishRef = useRef(furnish)
  furnishRef.current = furnish
  const reviewing = furnish.status?.state === 'review_ready'
  // Real dims per prop id — true-size footprints/ghost need them. One fetch;
  // refreshed when the palette opens or a furnishing proposal arrives (both
  // may have gained props meanwhile — the job generates its own).
  const [propDims, setPropDims] = useState<Record<string, PropDims>>({})
  useEffect(() => {
    if (!propsOpen && !reviewing && Object.keys(propDims).length) return
    apiGet<{ props?: Array<{ id: string } & PropDims> }>('/world/props')
      .then((d) => {
        const map: Record<string, PropDims> = {}
        for (const p of d.props || []) {
          map[p.id] = { name: p.name, width_m: p.width_m,
            depth_m: p.depth_m, height_m: p.height_m, slots: p.slots }
        }
        setPropDims(map)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propsOpen, reviewing])
  // The room whose hull is being drawn ('draw-room' mode) — set by the
  // "Not on the plan" chips (first placement) and the redraw tool.
  const [drawTarget, setDrawTarget] = useState('')
  // Selected opening (index into the selected room's openings) for the
  // per-opening controls below the plan.
  const [openingSel, setOpeningSel] = useState<number | null>(null)
  // Place type the 🎯 tool drops (a pose-catalog group key, never a clip).
  const [markerGroup, setMarkerGroup] = useState('')
  // Building outline drawing (AV3D-12): points collected while in outline
  // mode, committed to map3d.outline on finish (>= 3 points; clicking the
  // first vertex closes too).
  const [outlineDraft, setOutlineDraft] = useState<Array<[number, number]>>([])
  // Snapped cursor while drawing — feeds the rubber band AND the snap
  // feedback (guide ray, highlighted target, vertex ring).
  const [hoverSnap, setHoverSnap] = useState<SnapResult | null>(null)
  // Selected marker (index into the selected room's markers) for the
  // per-marker controls: facing, height offset, remove.
  const [markerSel, setMarkerSel] = useState<number | null>(null)
  // Elevator selected on the plan → the slider row below fine-tunes it.
  const [elevatorSel, setElevatorSel] = useState(false)
  // Selected staircase — the INDEX in map3d.stairs, which is the flight's
  // identity here. The `stair` number a scene payload carries is NOT: it
  // counts the flights the server accepted, so a refused entry shifts it.
  const [stairSel, setStairSel] = useState<number | null>(null)
  // Selected boundary pass-through (index into map3d.boundary_openings) —
  // highlights its bar on the frame and its edit row below the plan.
  const [selectedBoundary, setSelectedBoundary] = useState<number | null>(null)
  // The pose catalog: its place types feed the 🎯 picker, its poses the
  // preview cycler of the selected marker.
  const poseCatalog = usePoseCatalog()
  useEffect(() => {
    const first = groupKeys(poseCatalog.groups)[0] || ''
    setMarkerGroup((g) => (g && poseCatalog.groups[g] ? g : first))
  }, [poseCatalog])
  // Surface-texture kinds for the room shell (floor/wall). The route answers
  // a BARE array mixing texture entries ({kind, url, size_m}) and blend
  // entries ({kind, blend}) — the picker wants the deduplicated kinds, with a
  // thumbnail wherever one exists.
  // What a picker STORES is the id; what it SHOWS is the name — the library
  // ships both, so no dropdown has to display "dark_stone" any more.
  // `material` travels along because the renderers need to know HOW a kind is
  // lit (§ A9). It no longer answers "is this water?" — since W1 that is the
  // terrain catalog's `meta.water` and nothing else (`waterKinds` below).
  const [surfaceKinds, setSurfaceKinds] = useState<SurfaceKind[]>([])
  useEffect(() => {
    apiGet<Array<{ kind?: string; name?: string; url?: string
                   material?: SurfaceMaterialSpec | null }>>(
      '/assets/surface-textures')
      .then((list) => {
        const byKind = new Map<string, Omit<SurfaceKind, 'kind'>>()
        for (const entry of Array.isArray(list) ? list : []) {
          const kind = (entry?.kind || '').trim()
          if (!kind || byKind.has(kind)) continue
          byKind.set(kind, { name: (entry.name || '').trim() || kind,
                             url: entry.url || '',
                             material: entry.material ?? null })
        }
        setSurfaceKinds(Array.from(byKind, ([kind, v]) => ({ kind, ...v }))
          .sort((a, b) => a.name.localeCompare(b.name)))
      })
      .catch(() => setSurfaceKinds([]))
  }, [])
  // WHICH GROUNDS ARE WATER — the terrain catalog's own flag (W1). The floor
  // picker must not offer one: `world_ops._sanitize_room_layout` strips a water
  // floor kind at the one write path, so a pick would vanish on the next save
  // with nothing said. A failed fetch leaves the set EMPTY and therefore
  // filters nothing — "no catalog" and "no water kinds" are not the same
  // statement, and guessing the difference is how a name match creeps back in.
  const [waterKinds, setWaterKinds] = useState<Set<string>>(new Set())
  useEffect(() => {
    apiGet<TerrainTypesResp>('/world/terrain-types')
      .then((d) => setWaterKinds(new Set(
        (d.types || []).filter(isWaterKind).map((ty) => ty.kind))))
      .catch(() => setWaterKinds(new Set()))
  }, [])
  // Top-down underlay: the placed room models rendered straight from above,
  // laid behind the rectangles — markers can be dropped on real furniture.
  const [underlay, setUnderlay] = useState(false)
  // Building layer behind the plan — the roof view is the real footprint,
  // for tracing the outline polygon.
  const [bUnderlay, setBUnderlay] = useState(false)
  const [underlayUrl, setUnderlayUrl] = useState('')
  // Reference sizes on the plan (metre grid + the 1.70 m person). On by
  // default — a plan whose rectangles carry no real size is exactly the
  // problem these aids exist for. The scale bar has no switch at all.
  const [aids, setAids] = useState(true)
  // Position of the reference figure in LOCAL METRES; null = "wherever the
  // window's bottom-left is right now", so it starts visible whatever the plot
  // looks like and stays where the user last put it afterwards.
  const [figurePos, setFigurePos] = useState<[number, number] | null>(null)
  // The canvas is CANVAS_W at zoom 1 — unless a narrow pane shrinks it via
  // maxWidth. The scale bar and the grid step are stated in PIXELS, so they
  // measure the edge instead of assuming it.
  const [canvasPx, setCanvasPx] = useState(CANVAS_W)
  const canvasRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState>(null)
  // Did the last prop press travel past `MOVE_START_PX`, i.e. was it a DRAG?
  // `dragRef` is already cleared on pointerup, and the click that follows the
  // release still has to know — a drag positions and selects its own piece
  // and must never advance the stack cycle.
  const propDraggedRef = useRef(false)
  const roomsRef = useRef(rooms)
  roomsRef.current = rooms

  // The contract's reference surface is a fixed 8×8 m SQUARE — the canvas
  // is square too, whatever the building footprint says.
  const canvasH = CANVAS_W
  // 2D-plan zoom (1x..3x): the canvas renders LARGER inside a scroll
  // container — children are %-positioned and every handler works on
  // getBoundingClientRect fractions, so zooming needs no interaction math.
  const [planZoom, setPlanZoom] = useState(1)
  const planZoomRef = useRef(planZoom)
  planZoomRef.current = planZoom
  const zoomViewportRef = useRef<HTMLDivElement>(null)

  // Plain mouse wheel zooms, anchored at the cursor (native non-passive
  // listener — React's synthetic wheel cannot preventDefault reliably).
  // At the 1x lower bound the event passes through so the page scrolls.
  useEffect(() => {
    const canvas = canvasRef.current
    const vp = zoomViewportRef.current
    if (!canvas || !vp) return
    const onWheel = (e: WheelEvent) => {
      const cur = planZoomRef.current
      const nz = Math.min(3, Math.max(1,
        Math.round((cur + (e.deltaY < 0 ? 0.25 : -0.25)) * 4) / 4))
      if (nz === cur) return
      e.preventDefault()
      const rect = canvas.getBoundingClientRect()
      const fx = (e.clientX - rect.left) / rect.width
      const fy = (e.clientY - rect.top) / rect.height
      const vpRect = vp.getBoundingClientRect()
      setPlanZoom(nz)
      // After the resize, scroll so the point under the cursor stays put.
      requestAnimationFrame(() => {
        vp.scrollLeft = fx * CANVAS_W * nz - (e.clientX - vpRect.left)
        vp.scrollTop = fy * CANVAS_W * nz - (e.clientY - vpRect.top)
      })
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [])

  // Live canvas width for the pixel-stated aids (zoom changes resize the
  // element, so this covers them too).
  useEffect(() => {
    const el = canvasRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      setCanvasPx(el.getBoundingClientRect().width || CANVAS_W)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Width of the location in REAL metres. SINCE v6 A DERIVED VALUE: the
  // server overwrites it with the boundary's bounding-box width on every save
  // (world_ops._sanitize_map3d), and nothing here scales by it any more — the
  // layouts carry their own metres. It survives as the fallback edge for a
  // location that has no boundary at all.
  const planW = map3d?.plan_width_m || 0
  /**
   * The location BOUNDARY in LOCAL METRES (contract v6 Nr. 1) — the very
   * numbers `map3d.boundary` stores, no conversion.
   *
   * Boundary pass-throughs sit on its EDGES, so the plan reads the polygon
   * straight. Without a drawn boundary the square around the pin stands in —
   * the same degradation `world_geometry.effective_boundary` applies, so the
   * edge indices mean the same on both sides (0 = north, 1 = east, 2 = south,
   * 3 = west).
   */
  const boundaryM = useMemo<Pt[]>(() => {
    const pts = map3d?.boundary
    if (pts && pts.length >= 3) return pts.map(([x, z]) => [x, z] as Pt)
    const h = (planW || FALLBACK_VIEW_M) / 2
    return [[-h, -h], [h, -h], [h, h], [-h, h]]
  }, [map3d?.boundary, planW])

  /**
   * THE YARD'S VIEW SHAPE (§ A13a) — null while no boundary is DRAWN.
   *
   * The ground room has no rectangle; its surface is the boundary polygon. To
   * keep the plan's room-local percentage math working, the boundary's
   * bounding box stands in as a rect and the polygon becomes its hull, in
   * metres relative to that corner exactly like a drawn room hull. NONE of it
   * is ever written back: the stored yard layout is placements only, and
   * `atOrigin` translates between the frames.
   *
   * The pin-square fallback of `boundaryM` deliberately does NOT apply — no
   * drawn boundary means no area anywhere (v6 preamble), so there is no yard
   * to furnish either.
   */
  const yardLay = useMemo<PlacedLayout | null>(() => {
    if (!(map3d?.boundary && map3d.boundary.length >= 3)) return null
    const xs = boundaryM.map((p) => p[0])
    const zs = boundaryM.map((p) => p[1])
    const x = Math.min(...xs)
    const y = Math.min(...zs)
    const w = Math.max(...xs) - x
    const d = Math.max(...zs) - y
    if (!(w > 0 && d > 0)) return null
    return { x, y, w, d, level: 0,
             outline: boundaryM.map(([px, pz]) => [px - x, pz - y] as Pt) }
  }, [map3d?.boundary, boundaryM])
  /** Is there a DRAWN boundary at all, or is `boundaryM` the pin square
   *  standing in for one? Every statement about the plot hangs off this. */
  const hasBoundary = !!(map3d?.boundary && map3d.boundary.length >= 3)

  /**
   * WRITE THE LOCATION BOUNDARY — the same polygon the map tab reshapes, in
   * the same one write path (`boundaryApi`).
   *
   * NO PIN TRANSFORM HERE, and that is the whole reason the gesture fits: the
   * map canvas draws in WORLD metres and has to send every vertex back through
   * § A1.1, while THIS canvas already draws in the location's LOCAL metres —
   * the very frame `map3d.boundary` is stored in. What `PolygonHandles` hands
   * over is therefore the stored value verbatim.
   *
   * The write goes to the server immediately, like it does on the map tab,
   * and the STORED answer is read back into the draft (centimetre rounding,
   * one winding, derived `plan_width_m`) — the handles have to sit on the
   * points that really exist. The location's own Save button is untouched by
   * this: it writes the same `map3d` again, which is idempotent. It must NOT
   * reload the parent though — that would throw away every unsaved room edit
   * in the draft.
   */
  const writeBoundary = useCallback(async (points: Pt[]) => {
    if (!locationId || !onMap3d) return
    const bad = boundaryComplaint(points)
    if (bad) {
      toast(t(bad.message).replace('{n}', String(bad.n)), 'error')
      return
    }
    // Optimistic: the polygon must follow the hand, not the round trip.
    onMap3d('boundary', points)
    try {
      const stored = await putLocationBoundary(locationId, map3d, points)
      if (stored) {
        onMap3d('boundary', stored.boundary)
        onMap3d('plan_width_m', stored.plan_width_m)
      }
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [locationId, map3d, onMap3d, t, toast])

  /** The first shape: a centred square the author then drags into the outline
   *  they mean — the same seed the map tab writes, so a location gets the same
   *  starting polygon whichever surface it was drawn from. Its edge is the
   *  location's own derived width when it still has one, otherwise the shared
   *  placeholder. */
  const seedBoundary = useCallback(() => {
    if (hasBoundary) return
    void writeBoundary(seedSquare(planW > 0 ? planW : BOUNDARY_SEED_M))
  }, [hasBoundary, planW, writeBoundary])

  /** The ground room itself — the server ships one with every location. */
  const groundRoom = rooms.find((r) => r.id === GROUND_ROOM_ID)
  /** Its label: the author's name for it, else the ONE shared default —
   *  the same word the room tree uses, never a second name for one room. */
  const yardName = groundRoomLabel(groundRoom, t)

  /** Everything the plan DRAWS on this level: the rooms with a rectangle plus
   *  — on level 0, once a boundary exists — the yard. */
  const placed = useMemo<PlanShape[]>(() => {
    const out: PlanShape[] = []
    for (const room of rooms) {
      if (hasRect(room.layout) && room.id !== GROUND_ROOM_ID
          && (room.layout.level || 0) === level) {
        out.push({ room, lay: room.layout, ground: false })
      }
    }
    // FIRST in the list = first in the DOM = underneath: the rooms stand ON
    // the yard, so it must not paint over them or swallow their clicks. The
    // server appends the ground room LAST to the room list, which is exactly
    // the wrong order here.
    const yard = rooms.find((r) => r.id === GROUND_ROOM_ID)
    if (yard && level === 0 && yardLay) {
      out.unshift({ room: yard, lay: yardLay, ground: true })
    }
    return out
  }, [rooms, level, yardLay])
  /** Rooms only — the yard is never "placed" by an author, so it must not
   *  answer the questions that ask whether anybody drew anything yet. */
  const placedHere = placed.filter((p) => !p.ground)
  /** Fraction-era leftovers: rooms whose rectangle is a few centimetres
   *  across because it was a [0,1] share before rooms were stored in metres.
   *  NOTHING repairs them by itself — a room with a diorama model heals from
   *  the model's declared real width, a room without one has no width to heal
   *  from — so the editor names them instead of leaving the author wondering
   *  why their plan is a speck near the pin. All levels, not just this one:
   *  the answer must not depend on which floor happens to be open. */
  const tinyRooms = useMemo(() => rooms.filter((r) =>
    r.id !== GROUND_ROOM_ID && hasRect(r.layout)
    && (r.layout.w < TINY_ROOM_M || r.layout.d < TINY_ROOM_M)), [rooms])
  // The yard is not a room to be drawn: it can never be "not on the plan",
  // it simply is the location's surface (§ A13a).
  const unplaced = rooms.filter((r) => !r.layout && r.id !== GROUND_ROOM_ID)
  /** Does ANY room of this location have a floor plan — on any level? That is
   *  the question the server's `rooms_without_layout` finding asks, so the
   *  editor's nudge has to ask it the same way and not per level. */
  const anyRoomPlaced = rooms.some((r) => r.id !== GROUND_ROOM_ID
    && hasRect(r.layout))

  /** One server finding in the editor's language. The SERVER owns the wording
   *  — its message is English source text, so it goes straight through `t()`
   *  as its own translation key. Repeating the sentence here would give it two
   *  owners and let them drift apart silently. Named rooms are prefixed, so
   *  the reader sees WHERE. */
  const problemText = (p: SceneProblem) => {
    const room = p.room_id
      ? (rooms.find((r) => r.id === p.room_id)?.name || p.room_id) : ''
    return room ? `${room}: ${t(p.message)}` : t(p.message)
  }
  const placedRooms = rooms.filter((r) => hasRect(r.layout) && r.id)
  const levels = Array.from(
    new Set(rooms.filter((r) => hasRect(r.layout)).map((r) => r.layout!.level || 0)),
  ).sort((a, b) => a - b)

  // Signature of the placed geometry — the auto-size correction below reruns
  // on it.
  const geomKey = JSON.stringify(rooms.filter((r) => hasRect(r.layout)).map((r) => [
    r.id, r.layout!.level || 0, r.layout!.x, r.layout!.y, r.layout!.w,
    r.layout!.d, r.layout!.rotation || 0,
  ]))
  // Anchored mode (map3d.plan_width_m set): room-rectangle sizes DERIVE
  // from the models' declared real width — long side = width_m /
  // plan_width_m, short side via the model's footprint aspect. Dims are
  // loaded per room once; rooms without model/width keep free resize.
  // ANY model mutation (panel, adjust strip, preview toolbar) lands here
  // via the generic refresh channel: refetch the fresh metas — rect
  // derivation and the underlay recompute from them.
  useEffect(() => {
    const onChanged = (e: Event) => {
      const det = (e as CustomEvent).detail as { locationId?: string; roomId?: string }
      if (det?.roomId) {
        const rid = det.roomId
        getRoomModelDims(rid)
          .then((d) => setModelDims((prev) => ({ ...prev, [rid]: d })))
          .catch(() => undefined)
      }
    }
    window.addEventListener('anima-model3d-changed', onChanged)
    return () => window.removeEventListener('anima-model3d-changed', onChanged)
  }, [locationId])
  /**
   * THE DRAWING VIEWPORT: the square metre window the canvas shows.
   *
   * Its content is the boundary AND every placed room hull — a room dragged
   * past the plot's edge stays visible instead of vanishing, and a location
   * whose boundary has not been drawn yet still gets a window around whatever
   * is on the plan. Plus a margin (8 %, at least 1 m) so an edge is never
   * flush with the canvas border, which is what made the boundary
   * unreachable before: the old canvas WAS the pin-centred reference square,
   * and everything the boundary put outside it could not be clicked.
   */
  const view = useMemo<PlanView>(() => {
    const pts: Pt[] = [...boundaryM]
    for (const r of rooms) {
      const lay = r.layout
      // The yard has no rectangle to frame — it IS the boundary, which is
      // already in the list (§ A13a).
      if (!hasRect(lay)) continue
      pts.push([lay.x, lay.y], [lay.x + lay.w, lay.y + lay.d])
    }
    for (const p of map3d?.outline || []) pts.push([p[0], p[1]])
    const base = viewportFor(pts, 0, FALLBACK_VIEW_M)
    const m = Math.max(1, base.size * 0.08)
    return { x0: base.x0 - m, z0: base.z0 - m, size: base.size + 2 * m }
  }, [boundaryM, rooms, map3d?.outline])
  // Canvas fraction ⇄ local metres. Every handler and every %-position goes
  // through these four; there is no second conversion anywhere in the file.
  const fx = useCallback((x: number) => viewFx(view, x), [view])
  const fz = useCallback((z: number) => viewFz(view, z), [view])
  const viewRef = useRef(view)
  viewRef.current = view
  /** Pointer position in LOCAL METRES (the canvas rect is the whole window). */
  const pointerM = useCallback((clientX: number, clientY: number): Pt => {
    const rect = (canvasRef.current as HTMLDivElement).getBoundingClientRect()
    const v = viewRef.current
    return [viewMx(v, (clientX - rect.left) / rect.width),
            viewMz(v, (clientY - rect.top) / rect.height)]
  }, [])
  /**
   * The square the top-down UNDERLAY covers: edge `scene.extent_m`, centred on
   * the boundary's bounding box — the frame the whole scene is composed in.
   * The snapshot camera is pointed at this centre and the image is laid at
   * this rectangle, so the two agree by construction instead of by both
   * assuming the pin.
   */
  const snapshotFrame = useMemo(() => {
    const xs = boundaryM.map((p) => p[0])
    const zs = boundaryM.map((p) => p[1])
    // WIDER side, not the x side: `plan_width_m` (and with it the payload's
    // `extent_m`) is the wider bbox side, so the fallback has to be the same
    // number — otherwise a plot that is deeper than it is wide gets a frame
    // too small for its own outline (the map derives it the same way in
    // `PlacementLayer.pictureFrameLocal`).
    const size = scene?.extent_m
      || Math.max(Math.max(...xs) - Math.min(...xs),
                  Math.max(...zs) - Math.min(...zs))
      || FALLBACK_VIEW_M
    return { center: [(Math.min(...xs) + Math.max(...xs)) / 2,
                      (Math.min(...zs) + Math.max(...zs)) / 2] as [number, number],
             size }
  }, [boundaryM, scene?.extent_m])
  const snapCx = snapshotFrame.center[0]
  const snapCz = snapshotFrame.center[1]
  // Re-render the underlay (debounced — drags update per pointermove)
  // whenever the SERVER's scene payload or the snapshot frame changes: the
  // snapshot places models from the same specs as the 3D preview, so both
  // match by construction.
  useEffect(() => {
    if (!underlay && !bUnderlay) {
      setUnderlayUrl('')
      return
    }
    if (!scene) return   // payload pending — keep the last underlay
    const tid = setTimeout(() => {
      renderTopDownSnapshot({
        models: scene.models || [], extentM: scene.extent_m,
        // The snapshot square sits over the BOUNDARY's bounding box, like the
        // server's terrain frame — a v6 plot drawn off to one side of its pin
        // would otherwise be half outside the picture.
        centerM: [snapCx, snapCz],
        level, includeRooms: underlay,
        buildingId: bUnderlay && locationId ? locationId : undefined,
      })
        .then((url) => setUnderlayUrl(url || ''))
        .catch(() => setUnderlayUrl(''))
    }, 350)
    return () => clearTimeout(tid)
  }, [underlay, bUnderlay, level, locationId, scene, snapCx, snapCz])

  // Drawing raster in metres (0 = off, Shift is the per-click escape). Half a
  // metre by default: fine enough for a doorway, coarse enough that two walls
  // meant to line up actually do.
  const [gridStep, setGridStep] = useState(0.5)
  const gridStepRef = useRef(gridStep)
  gridStepRef.current = gridStep
  // ── Server-composed room vocabulary (contract § B1 `rooms`) ──────────
  // Shared-wall openings are TRUTH, not cosmetics — they come from the same
  // scene payload the 3D preview renders, in plan fractions. The editor
  // draws them; it never re-derives them.
  const sceneRooms = useMemo(
    () => new Map((scene?.rooms || []).map((r) => [r.room_id, r] as [string, SceneRoom])),
    [scene])
  // ── The composed FLIGHTS (contract § B1 `stairs`) ────────────────────
  // Same law as the openings above: the run, the step count and the floor a
  // flight eats are the server's numbers, keyed by the position of the flight
  // in `map3d.stairs` (`id`). The plan used to compute them from the storey
  // height with a copy of the server's formula; it reads them now, so what an
  // author sees on the plan is what the client walks on. Until the preview has
  // answered (it is debounced), a freshly placed flight has no symbol yet.
  const sceneStairs = useMemo(
    () => new Map((scene?.stairs || []).map((s) => [s.id, s])),
    [scene])
  // A mirrored opening is one hole seen from the other side — find the
  // ORIGINAL in the owning room so a click can select it there. Identity by
  // position (plan fractions), since the payload does not index back.
  const ownerOpeningIndex = useCallback(
    (ownerId: string, point: { x: number; y: number }): number => {
      const owner = rooms.find((r) => r.id === ownerId)
      const ownerScene = sceneRooms.get(ownerId)
      if (!hasRect(owner?.layout) || !ownerScene) return -1
      const hull = absOutline(owner.layout)
      let best = -1
      let bestD = Infinity
      // `openings` is optional in the payload — a room without any is simply
      // absent, it does not arrive as an empty list.
      ;(ownerScene.openings || []).forEach((o, i) => {
        if (o.mirrored || o.edge >= hull.length) return
        const p = edgePointOnEdge(hull, o.edge, o.at)
        const dist = Math.hypot(p.x - point.x, p.y - point.y)
        if (dist < bestD) { bestD = dist; best = i }
      })
      return bestD < 0.02 ? best : -1
    }, [rooms, sceneRooms])
  // Refs for the window-level drag handler (its effect closure would go
  // stale on level/anchor changes otherwise).
  const map3dRef = useRef(map3d)
  map3dRef.current = map3d
  const boundaryRef = useRef(boundaryM)
  boundaryRef.current = boundaryM
  // The yard's derived shape for the window-level drag handler (same reason
  // as `viewRef`: its closure would go stale on a boundary edit).
  const yardLayRef = useRef(yardLay)
  yardLayRef.current = yardLay
  const [modelDims, setModelDims] = useState<Record<string,
    { widthM: number; fpX: number; fpZ: number } | null>>({})
  useEffect(() => {
    let stale = false
    for (const room of roomsRef.current) {
      const id = room.id || ''
      if (!id || id in modelDims) continue
      getRoomModelDims(id)
        .then((d) => { if (!stale) setModelDims((prev) => ({ ...prev, [id]: d })) })
        .catch(() => { if (!stale) setModelDims((prev) => ({ ...prev, [id]: null })) })
    }
    return () => { stale = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rooms.length])

  /**
   * THE SNAP RADIUS IN METRES — one derivation, two readers.
   *
   * A pixel radius converted through the window's live metres-per-pixel, with
   * a 0.05 m floor so a zoomed-out 400 m plot does not snap across half a
   * house. `computeSnap` aims with it and `snapTargets` decides with it which
   * hulls may be aimed at at all; deriving it twice would let the two drift.
   */
  const snapTolM = useMemo(
    () => Math.max(SNAP_TOL_PX * (view.size / (CANVAS_W * planZoom)), 0.05),
    [view.size, planZoom])

  // Snapping while drawing (always on, Shift = free-hand): targets are the
  // hulls of the placed rooms on the current level plus the draft's own
  // vertices; tolerances blend a pixel radius with a 0.15 m floor.
  const snapTargets = useMemo(() => {
    if (clickMode !== 'outline' && clickMode !== 'draw-room') return null
    // A HULL SMALLER THAN THE SNAP RADIUS IS A TRAP, NOT AN ANCHOR.
    //
    // `snapDrawPoint` gives a vertex inside `tol` unconditional priority over
    // the metre grid (rule 2), so a shape whose whole bounding box fits inside
    // `tol` cannot be aimed AT — it can only steal clicks that were meant for
    // the ground next to it, and the drawn shape is never the shape that was
    // clicked (user finding 2026-08-20). This is what fraction-era debris
    // looks like: `layout.x/y/w/d` were shares of a reference square before
    // rooms were stored in metres, so the room is now a few centimetres wide
    // and its corners sit in a box around the pin — exactly where an author
    // starts a new plan.
    //
    // MEASURED ON THE HULL, NOT ON THE STORED RECTANGLE: what enters
    // `buildSnapTargets` is `absOutline(hull)`, and a fraction-era room
    // carries a UNIT-SQUARE outline (its points were shares of the rect too),
    // so its rectangle and the box it really occupies are different numbers —
    // 0.15 m against 1 m for the reported world. Filtering on the rectangle
    // therefore measured the wrong box in both directions.
    //
    // The floor stays MIN_ROOM_M: a hull under the smallest room this editor
    // lets anyone draw is debris at every zoom level. Above it the rule is
    // relative, so a real 0.4 m nook stays a snap target on a 5 m plot
    // (tol ≈ 0.11 m) and stops being one on a 74 m plot (tol ≈ 1.76 m), where
    // it is 2 px wide and unaimable anyway. Such rooms stay drawn, selectable
    // and editable — they just stop steering the pen; the banner under the
    // plan says why they are specks.
    const minHullM = Math.max(MIN_ROOM_M, snapTolM)
    const hulls = hullsOf(rooms, level,
      clickMode === 'draw-room' ? drawTarget : '')
      .filter((hh) => {
        const pts = absOutline(hh)
        const xs = pts.map((p) => p[0])
        const ys = pts.map((p) => p[1])
        return Math.max(...xs) - Math.min(...xs) >= minHullM
          && Math.max(...ys) - Math.min(...ys) >= minHullM
      })
    return buildSnapTargets(hulls, {
      // Rooms snap onto the building outline; while the OUTLINE itself is
      // being redrawn it is not a target.
      buildingOutline: clickMode === 'draw-room' ? map3d?.outline : undefined,
      // The location BOUNDARY is always a target: corners, edge midpoints and
      // the edges — a room meant to touch the plot's edge really touches it
      // (plan-area-detail-scenes.md). Since v6 that is the drawn polygon, not
      // a reference square.
      boundary: boundaryM,
      extraPoints: outlineDraft,
    })
  }, [clickMode, rooms, level, outlineDraft, drawTarget, map3d?.outline,
    boundaryM, snapTolM])

  const computeSnap = useCallback((clientX: number, clientY: number,
      alt: boolean): SnapResult => {
    const raw = pointerM(clientX, clientY)
    // Tolerances in METRES: the aiming radius is `snapTolM`, the ONE
    // derivation the target list was filtered with; only the closing radius
    // is its own number.
    const mPerPx = view.size / (CANVAS_W * planZoomRef.current)
    const tol = snapTolM
    const prev = outlineDraft.length ? outlineDraft[outlineDraft.length - 1] : undefined
    const prev2 = outlineDraft.length >= 2 ? outlineDraft[outlineDraft.length - 2] : undefined
    return snapDrawPoint(raw, {
      prev,
      prevDir: prev && prev2 ? [prev[0] - prev2[0], prev[1] - prev2[1]] : undefined,
      first: outlineDraft[0],
      draft: outlineDraft,
      draftLen: outlineDraft.length,
      targets: snapTargets || { points: [], segments: [] },
      tol,
      closeTol: CLOSE_TOL_PX * mPerPx,
      grid: gridStep,
      alt,
    })
  }, [outlineDraft, snapTargets, pointerM, view.size, gridStep, snapTolM])

  const commitOutline = useCallback(() => {
    if (outlineDraft.length < 3) {
      planLog('commitOutline refused: fewer than 3 points',
        { draftLen: outlineDraft.length })
      return
    }
    onMap3d?.('outline', outlineDraft)
    setOutlineDraft([])
    setHoverSnap(null)
    setClickMode('')
  }, [outlineDraft, onMap3d])

  // Drops any armed mode plus the running draft — Esc, the ✕ tool and every
  // mode toggle go through here. Disarms the prop tool too (the palette
  // stays open — re-picking is one click).
  const cancelDraw = useCallback(() => {
    setClickMode('')
    setOutlineDraft([])
    setHoverSnap(null)
    setDrawTarget('')
    setArmedProp('')
    setPropGhost(null)
  }, [])

  // Esc cancels any armed mode and the current draft; R steps the placement
  // ghost's yaw by 90°; Del/Backspace drops the selected furnishing ghost
  // (never while typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName || ''
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === 'Escape') cancelDraw()
      else if (e.key === 'Delete' || e.key === 'Backspace') {
        setGhostSel((sel) => {
          if (sel === null) return sel
          const job = furnishRef.current
          job.setGhosts(job.ghosts.filter((_, i) => i !== sel))
          return null
        })
      } else if ((e.key === 'r' || e.key === 'R')) setGhostYaw((y) => (y + 90) % 360)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [cancelDraw])

  // Selecting another room closes the dialog and drops the ghost selection —
  // both belong to the room that was selected before.
  useEffect(() => { setGhostSel(null); setFurnishOpen(false) }, [selected])
  // Leaving the review state invalidates the ghost indices.
  useEffect(() => { if (!reviewing) setGhostSel(null) }, [reviewing])

  // The room rectangle a diorama model asks for, IN METRES: its declared real
  // width is the long side, the mesh's own footprint aspect gives the short
  // one. No plan width divides anything any more (v6 Nr. 2) — the model's
  // metres go straight onto the plan's metres.
  const derivedSize = useCallback((roomId: string):
      { w: number; d: number } | null => {
    const dims = modelDims[roomId]
    if (!dims || !(dims.widthM > 0)) return null
    const long = Math.min(dims.widthM, PLAN_MAX_M)
    const aspect = Math.min(dims.fpX, dims.fpZ) / (Math.max(dims.fpX, dims.fpZ) || 1)
    const short = Math.max(long * aspect, MIN_ROOM_M)
    // The model's X side carries the largest extent when fpX >= fpZ.
    return dims.fpX >= dims.fpZ ? { w: long, d: short } : { w: short, d: long }
  }, [modelDims])

  // Auto-correct placed rooms to their derived size. NO rotation swap any
  // more (v6 addendum): the stored rectangle is the room's own STRAIGHT
  // frame, and the model stands in that same frame — the turn is applied to
  // rect and model together on the way out, so the derived size is the
  // model's unturned footprint. (Until the addendum the rect stayed straight
  // while only the model turned, and the swap was the compensation for that
  // gap.) Runs whenever dims change; centimetre rounding keeps it from
  // oscillating. The rectangle grows around its own centre — there is no
  // square to clamp it into.
  useEffect(() => {
    let changed = false
    const next = roomsRef.current.map((r) => {
      const lay = r.layout
      // A drawn hull is authoritative — width_m-derived sizing only applies
      // to legacy diorama-model rooms without an outline (D4).
      const ds = r.id && !r.layout?.outline?.length ? derivedSize(r.id) : null
      if (!hasRect(lay) || !ds) return r
      const wantW = rM(ds.w)
      const wantD = rM(ds.d)
      if (Math.abs(lay.w - wantW) < 0.005 && Math.abs(lay.d - wantD) < 0.005) return r
      changed = true
      return { ...r, layout: { ...lay,
        w: wantW, d: wantD,
        x: rM(lay.x + (lay.w - wantW) / 2),
        y: rM(lay.y + (lay.d - wantD) / 2) } }
    })
    if (changed) onChange(next)
  }, [derivedSize, geomKey, onChange])

  // Fit the SELECTED room's plan to its 3D model — the manual counterpart of
  // the auto-sizing above, which deliberately leaves drawn hulls alone. After
  // calibrating a model against the reference figure the plan is usually the
  // one thing left too big (user finding 2026-07-28, Handwerker Hütte).
  const fitToModel = useCallback(() => {
    const room = roomsRef.current.find((r) => r.id === selectedRef.current)
    const lay = room?.layout
    const dims = room?.id ? modelDimsRef.current[room.id] : null
    // The yard has no rectangle to fit and no model to fit it to (§ A13a).
    if (!hasRect(lay) || !room?.id || !dims || dims.widthM <= 0) return
    // The model's footprint IN METRES: its declared real width is the long
    // side, the short one follows the mesh's own aspect (same rule as
    // derivedSize).
    const long = Math.min(dims.widthM, PLAN_MAX_M)
    const aspect = Math.min(dims.fpX, dims.fpZ) / (Math.max(dims.fpX, dims.fpZ) || 1)
    const short = Math.max(long * aspect, MIN_ROOM_M)
    // No rotation swap (v6 addendum): rect and model share the room's
    // straight frame and are turned together afterwards.
    let wantW = dims.fpX >= dims.fpZ ? long : short
    let wantD = dims.fpX >= dims.fpZ ? short : long
    let scaleHull = 1
    if (lay.outline?.length) {
      // A drawn hull keeps the SHAPE it was drawn in — only its size follows
      // the model, so the longest side matches and the rest scales with it.
      scaleHull = Math.max(wantW, wantD) / (Math.max(lay.w, lay.d) || 1)
      wantW = lay.w * scaleHull
      wantD = lay.d * scaleHull
    }
    wantW = clamp(rM(wantW), MIN_ROOM_M, PLAN_MAX_M)
    wantD = clamp(rM(wantD), MIN_ROOM_M, PLAN_MAX_M)
    updateLayoutRef.current?.(room.id, {
      w: wantW,
      d: wantD,
      x: rM(lay.x + (lay.w - wantW) / 2),
      y: rM(lay.y + (lay.d - wantD) / 2),
      // The hull's points are METRES from the room's corner now, so a scaled
      // room has to scale them too — in the fraction era they were relative
      // and rode along for free. Markers/props/model_at sit on the room's
      // content, which does NOT grow with the shell, so they stay put.
      ...(lay.outline?.length
        ? { outline: lay.outline.map(([u, v]) =>
            [rM(u * scaleHull), rM(v * scaleHull)] as [number, number]),
          ...(lay.outline_curves?.length
            ? { outline_curves: lay.outline_curves.map((cv) => ({ ...cv,
                c: [rM(cv.c[0] * scaleHull), rM(cv.c[1] * scaleHull)] as
                  [number, number] })) }
            : {}) }
        : {}),
    })
  }, [])

  const updateLayout = useCallback((roomId: string, patch: Partial<RoomLayout> | null) => {
    const next = roomsRef.current.map((r) => {
      if (r.id !== roomId) return r
      if (patch === null) {
        const rest = { ...r }
        delete rest.layout
        return rest
      }
      // Default for a room that gets a layout without being drawn: a 3 × 3 m
      // box at the pin. Metres, like everything else since v6 Nr. 2.
      // THE YARD GETS NOTHING (§ A13a): its layout is placements only, so the
      // first prop on it starts from an empty object — a rectangle written
      // here would be geometry the ground room must never carry.
      const base: RoomLayout = r.layout
        || (roomId === GROUND_ROOM_ID ? {} : { level, x: -1.5, y: -1.5, w: 3, d: 3 })
      return { ...r, layout: { ...base, ...patch } }
    })
    onChange(next)
  }, [onChange, level])
  // Refs so `fitToModel` stays identity-stable (it sits in the toolbar props).
  const updateLayoutRef = useRef(updateLayout)
  updateLayoutRef.current = updateLayout
  const modelDimsRef = useRef(modelDims)
  modelDimsRef.current = modelDims
  const selectedRef = useRef(selected)
  selectedRef.current = selected

  // Close a drawn room hull: the bbox becomes x/y/w/d in LOCATION-LOCAL
  // METRES (the rectangle-only reader keeps working), the points become
  // metres relative to that bbox's min corner with clockwise winding —
  // mirroring the server sanitizer, which now folds by TRANSLATION and no
  // longer renormalizes. Redrawing clears the openings (their edge indices
  // point into the OLD hull); the markers stay.
  const commitRoomDraft = useCallback(() => {
    if (!drawTarget || outlineDraft.length < 3) {
      planLog('commitRoomDraft refused: no target or fewer than 3 points',
        { drawTarget, draftLen: outlineDraft.length })
      return
    }
    const xs = outlineDraft.map((p) => p[0])
    const ys = outlineDraft.map((p) => p[1])
    const minX = Math.min(...xs)
    const minY = Math.min(...ys)
    const w = Math.max(...xs) - minX
    const d = Math.max(...ys) - minY
    if (w < MIN_ROOM_M || d < MIN_ROOM_M) {
      planLog('commitRoomDraft refused: bbox under MIN_ROOM_M',
        { w, d, min: MIN_ROOM_M, draft: outlineDraft })
      toast(t('The shape is too small — keep drawing or press Esc.'), 'error')
      return
    }
    let pts = outlineDraft.map(([x, y]) =>
      [x - minX, y - minY] as [number, number])
    const shoelace = pts.reduce((sum, p, i) => {
      const q = pts[(i + 1) % pts.length]
      return sum + p[0] * q[1] - q[0] * p[1]
    }, 0)
    // In metres an "area" threshold is a real area: 0.04 m² is a 20 cm square,
    // the same slip of the hand MIN_ROOM_M catches on a side.
    if (Math.abs(shoelace) / 2 < MIN_ROOM_M * MIN_ROOM_M) {
      planLog('commitRoomDraft refused: area under MIN_ROOM_M²',
        { areaM2: Math.abs(shoelace) / 2, draft: outlineDraft })
      toast(t('The shape has no area — keep drawing or press Esc.'), 'error')
      return
    }
    if (shoelace < 0) pts = [...pts].reverse()
    const target = roomsRef.current.find((r) => r.id === drawTarget)
    if (target?.layout?.openings?.length)
      toast(t('Openings were cleared — they sat on the old hull.'), 'info')
    updateLayout(drawTarget, {
      level,
      x: rM(minX), y: rM(minY), w: rM(w), d: rM(d),
      outline: pts.map(([u, v]) => [rM(u), rM(v)] as [number, number]),
      openings: [],
      // Curves sat on the OLD hull's edges — they go with the openings.
      outline_curves: undefined,
    })
    setSelected(drawTarget)
    setDrawTarget('')
    setOutlineDraft([])
    setHoverSnap(null)
    setClickMode('')
  }, [drawTarget, outlineDraft, level, updateLayout, setSelected, t, toast])

  // Pointer interactions: move on the rect body, resize on the corner handle.
  // Window listeners so a drag survives leaving the canvas. EVERY delta is
  // metres — the pixel travel times the window's metres-per-pixel — and
  // nothing is clamped into a square: a room may sit anywhere in the plot's
  // frame, the ±500 m plan window is the only bound (the server's own).
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const drag = dragRef.current
      const canvas = canvasRef.current
      if (!drag || !canvas) return
      e.preventDefault()
      const room = roomsRef.current.find((r) => r.id === drag.roomId)
      // The yard's shape is DERIVED (§ A13a): only its placements drag, and
      // they drag exactly like a room's — what differs is the frame their
      // `at` is stored in, which `atOrigin` below settles.
      const ground = drag.roomId === GROUND_ROOM_ID
      const lay = ground ? yardLayRef.current : room?.layout
      if (!room || !hasRect(lay)) return
      const mPerPx = drag.kind === 'move' || drag.kind === 'resize'
        ? drag.mPerPx
        : viewRef.current.size / (canvas.clientWidth || CANVAS_W)
      const step = gridStepRef.current
      if (drag.kind === 'move') {
        // A press selects; only a real movement moves. Once past the
        // threshold the drag stays live, so a slow hand does not stutter.
        if (!drag.moving) {
          if (Math.hypot(e.clientX - drag.startX,
                         e.clientY - drag.startY) < MOVE_START_PX) return
          drag.moving = true
          // Re-base on the crossing point, otherwise the room jumps by the
          // threshold at the very moment the drag begins.
          drag.startX = e.clientX
          drag.startY = e.clientY
        }
        const dx = (e.clientX - drag.startX) * mPerPx
        const dy = (e.clientY - drag.startY) * mPerPx
        let nx = clamp(drag.origX + dx, -PLAN_MAX_M, PLAN_MAX_M)
        let ny = clamp(drag.origY + dy, -PLAN_MAX_M, PLAN_MAX_M)
        // Moving snaps like drawing does (Shift = free-hand): the moved
        // hull's vertices align with neighbour / building-outline / boundary
        // vertices — x and y independently, so gaps close one wall at a time.
        // Nothing in range: the metre raster catches the corner instead.
        if (!e.shiftKey) {
          const hulls = hullsOf(roomsRef.current, lay.level || 0, drag.roomId)
          const targets = buildSnapTargets(hulls, {
            buildingOutline: map3dRef.current?.outline,
            boundary: boundaryRef.current })
          const tol = Math.max(SNAP_TOL_PX * mPerPx, 0.05)
          const [sx, sy] = snapMoveOffset(
            absOutline({ ...lay, x: nx, y: ny }), targets, tol)
          nx = sx ? nx + sx : snapToGrid(nx, step)
          ny = sy ? ny + sy : snapToGrid(ny, step)
        }
        updateLayout(drag.roomId, { x: rM(nx), y: rM(ny) })
      } else if (drag.kind === 'resize') {
        // w/d live in the room's STRAIGHT frame, so the cursor's travel is
        // turned back into it (v6 addendum) — otherwise dragging the handle
        // of a turned room grew it sideways to the hand.
        const [dx, dy] = rotateAbout(
          [(e.clientX - drag.startX) * mPerPx,
           (e.clientY - drag.startY) * mPerPx], [0, 0], -(lay.rotation || 0))
        const nw = e.shiftKey ? drag.origW + dx : snapToGrid(drag.origW + dx, step)
        const nd = e.shiftKey ? drag.origD + dy : snapToGrid(drag.origD + dy, step)
        const wantW = clamp(rM(nw), MIN_ROOM_M, PLAN_MAX_M)
        const wantD = clamp(rM(nd), MIN_ROOM_M, PLAN_MAX_M)
        // A DRAWN hull is metres from the room corner, so resizing the bbox
        // has to scale the polygon with it — otherwise the shape would sit
        // unchanged inside a grown rectangle (the fraction era got this for
        // free). Curve control points ride along; room CONTENT does not.
        const sx = lay.w > 0 ? wantW / lay.w : 1
        const sy = lay.d > 0 ? wantD / lay.d : 1
        updateLayout(drag.roomId, {
          w: wantW,
          d: wantD,
          ...(lay.outline?.length
            ? { outline: lay.outline.map(([u, v]) =>
                [rM(u * sx), rM(v * sy)] as [number, number]),
              ...(lay.outline_curves?.length
                ? { outline_curves: lay.outline_curves.map((cv) => ({ ...cv,
                    c: [rM(cv.c[0] * sx), rM(cv.c[1] * sy)] as [number, number] })) }
                : {}) }
            : {}),
        })
      } else if (drag.kind === 'opening') {
        // Opening drag: slide it along its polygon edge — project the cursor
        // onto the edge in LOCATION-LOCAL METRES. `at` itself stays a fraction
        // of the edge (v6 Nr. 2 leaves that one ratio alone). The write
        // normalizes a legacy letter opening to the index vocabulary (the
        // editor only writes indices).
        const [fx, fy] = pointerM(e.clientX, e.clientY)
        const seg = edgeSegment(absOutline(lay), drag.edge)
        const dx = seg.b[0] - seg.a[0]
        const dy = seg.b[1] - seg.a[1]
        const len2 = dx * dx + dy * dy
        const along = len2 > 0
          ? ((fx - seg.a[0]) * dx + (fy - seg.a[1]) * dy) / len2
          : 0.5
        const at = r4(clamp(along, 0, 1))
        updateLayout(drag.roomId, {
          openings: (lay.openings || []).map((o, idx) =>
            idx === drag.index ? { ...o, edge: drag.edge, at } : o),
        })
      } else if (drag.kind === 'curveCtl') {
        // Bezier control point (plan-area-detail-scenes.md): METRES from the
        // room's min corner, and it may legitimately leave the hull (a road
        // bend does) — the server clamps it to the plain ±500 m plan window
        // since v6, not to a bbox-relative one, so this does the same.
        const [cu, cv] = localToRoom(lay, pointerM(e.clientX, e.clientY))
        const c: [number, number] = [
          rM(clamp(cu, -PLAN_MAX_M, PLAN_MAX_M)),
          rM(clamp(cv, -PLAN_MAX_M, PLAN_MAX_M)),
        ]
        updateLayout(drag.roomId, {
          outline_curves: (lay.outline_curves || []).map((cv) =>
            cv.edge === drag.edge ? { ...cv, c } : cv),
        })
      } else {
        // Prop / ghost / model drag: reposition inside the room — METRES from
        // the room's min corner. The piece keeps its real size, only `at`
        // moves; the raster applies unless Shift asks for free hand.
        if (drag.kind === 'prop' && !drag.moving) {
          // Same threshold a room move uses: a press that barely twitches is a
          // CLICK (it cycles the stack, see the prop layer below), and only
          // real travel turns it into a drag. Crossing it is also the moment
          // the dragged piece becomes the selection — the press itself must
          // not select, or the cycle could never leave the topmost piece.
          if (Math.hypot(e.clientX - drag.startX,
                         e.clientY - drag.startY) < MOVE_START_PX) return
          drag.moving = true
          propDraggedRef.current = true
          setPropSel(drag.index)
        }
        const raster = (v: number) => (e.shiftKey ? v : snapToGrid(v, step))
        const o = atOrigin(lay, ground)
        const [su, sv] = storedAt(lay, ground,
                                 pointerM(e.clientX, e.clientY))
        const at: [number, number] = [
          rM(clamp(raster(su), o[0], o[0] + lay.w)),
          rM(clamp(raster(sv), o[1], o[1] + lay.d)),
        ]
        if (drag.kind === 'model') {
          // The room's DIORAMA model is positioned like a prop: the anchor
          // lives in the PLAN (layout.model_at), not on the model sidecar.
          updateLayout(drag.roomId, { model_at: at })
          return
        }
        if (drag.kind === 'ghost') {
          // Pending placements live in FE state only — nothing is stored
          // until Accept.
          const job = furnishRef.current
          job.setGhosts(job.ghosts.map((p, idx) =>
            idx === drag.index ? { ...p, at } : p))
          return
        }
        updateLayout(drag.roomId, {
          props: (lay.props || []).map((p, idx) =>
            idx === drag.index ? { ...p, at } : p),
        })
      }
    }
    const up = () => { dragRef.current = null }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [updateLayout, pointerM])

  // Move / resize the room RECTANGLE. Never the yard: it has no rectangle —
  // moving or resizing the location's surface is a boundary edit on the map
  // tab, not a floor-plan one (§ A13a).
  const startDrag = useCallback((e: React.PointerEvent, room: Room, kind: 'move' | 'resize') => {
    if (clickMode || room.id === GROUND_ROOM_ID) return
    const lay = room.layout
    if (!hasRect(lay) || !room.id) return
    e.preventDefault()
    e.stopPropagation()
    setSelected(room.id)
    const mPerPx = view.size
      / (canvasRef.current?.clientWidth || CANVAS_W * planZoomRef.current)
    dragRef.current = kind === 'move'
      ? { kind, roomId: room.id, startX: e.clientX, startY: e.clientY,
          origX: lay.x, origY: lay.y, mPerPx }
      : { kind, roomId: room.id, startX: e.clientX, startY: e.clientY,
          origW: lay.w, origD: lay.d, mPerPx }
  }, [clickMode, setSelected, view.size])

  // Drag a placed opening along its edge (no drag while placing). `edge` is
  // the NORMALIZED polygon edge index.
  const startOpeningDrag = useCallback(
    (e: React.PointerEvent, room: Room, index: number, edge: number) => {
      if (clickMode || !room.id) return
      e.preventDefault()
      e.stopPropagation()
      setSelected(room.id)
      setOpeningSel(index)
      dragRef.current = { kind: 'opening', roomId: room.id, index, edge }
    }, [clickMode, setSelected])

  // Drag a curve control point (allowed while the ◡ tool is armed — the
  // handle IS that tool's editing surface).
  const startCurveDrag = useCallback(
    (e: React.PointerEvent, room: Room, edge: number) => {
      if (!room.id) return
      e.preventDefault()
      e.stopPropagation()
      dragRef.current = { kind: 'curveCtl', roomId: room.id, edge }
    }, [])

  // Drag a placed prop within its room (no drag while a tool is armed).
  //
  // THE PRESS SELECTS NOTHING. Only the topmost footprint of a stack receives
  // the pointer events, so a press that selected its own index would rewrite
  // `propSel` to that same top piece before EVERY click — the cycle below
  // would restart there each time and the pieces underneath stayed
  // unreachable (user finding 2026-08-24). The selection is therefore made in
  // exactly two places: the click handler (cycling) and the move handler
  // (once a real drag begins). Selecting the ROOM is safe — it cannot break a
  // cycle inside a room that was not selected yet — but only when it actually
  // changes, because `setSelected` clears `propSel`.
  const startPropDrag = useCallback(
    (e: React.PointerEvent, room: Room, index: number) => {
      if (clickMode || armedProp || !room.id) return
      e.preventDefault()
      e.stopPropagation()
      if (room.id !== selectedRef.current) setSelected(room.id)
      propDraggedRef.current = false
      dragRef.current = { kind: 'prop', roomId: room.id, index,
                          startX: e.clientX, startY: e.clientY }
    }, [clickMode, armedProp, setSelected])

  // Drag a pending furnishing ghost within its room.
  const startGhostDrag = useCallback(
    (e: React.PointerEvent, room: Room, index: number) => {
      if (clickMode || armedProp || !room.id) return
      e.preventDefault()
      e.stopPropagation()
      setGhostSel(index)
      dragRef.current = { kind: 'ghost', roomId: room.id, index }
    }, [clickMode, armedProp])

  // Accept: the server appends the CURRENT ghost positions to layout.props —
  // the editor draft has to follow, or the next Save would write the room
  // back without them.
  const acceptFurnish = useCallback(async () => {
    const job = furnishRef.current
    const room = roomsRef.current.find((r) => r.id === selected)
    const list = job.ghosts
    // The yard may still have NO layout at all — accepting a furnishing is
    // exactly what creates one there (§ A13a), so the room itself is enough.
    if (!room || !list.length) return
    try {
      await job.act('accept', { placements: list })
      updateLayout(room.id || '', { props: [...(room.layout?.props || []), ...list] })
      setGhostSel(null)
      toast(t('{n} pieces added to the room').replace('{n}', String(list.length)))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [selected, updateLayout, t, toast])

  // All prop indices whose TRUE-size footprint covers a point in the SHAPE's
  // own metres (from its min corner) — in render order (the last entry draws
  // topmost). Clicking stacked props cycles the selection through this list.
  // `o` is the placements' stored origin (`atOrigin`), so the yard's
  // location-local `at` is compared in the same frame as the probe.
  const propsAtPoint = useCallback((lay: NonNullable<Room['layout']>, o: Pt,
      px: number, py: number): number[] => {
    const hits: number[] = []
    ;(lay.props || []).forEach((p, i) => {
      const dims = propDims[p.prop_id]
      // Metres from the placement's own anchor — the prop's dims are metres
      // too, so nothing converts.
      const cx = px - (p.at[0] - o[0])
      const cy = py - (p.at[1] - o[1])
      // The hit test undoes exactly the rotation the footprint is DRAWN with,
      // and that one is rotate(−yaw) on a y-down screen (see the prop layer
      // below / PlacementLayer.tsx:105). With +yaw here the test was the
      // inverse of the wrong turn — a 90°-turned prop could only be clicked
      // where it is not.
      const rad = (-(p.yaw || 0) * Math.PI) / 180
      const cos = Math.cos(rad)
      const sin = Math.sin(rad)
      const lx = cx * cos + cy * sin
      const ly = -cx * sin + cy * cos
      if (Math.abs(lx) <= (dims?.width_m || 1) / 2
          && Math.abs(ly) <= (dims?.depth_m || 1) / 2) hits.push(i)
    })
    return hits
  }, [propDims])

  // Click-to-place: one click inside a room drops an animation marker or a
  // prop placement — both as METRES from the room's min corner (contract v6
  // Nr. 2). The raster applies unless Shift asks for free hand.
  const onRoomClick = useCallback((e: React.MouseEvent, shape: PlanShape) => {
    const { room, lay, ground } = shape
    // BOUNDARY EDITING IS NOT A ROOM GESTURE: its handles are a canvas-level
    // overlay, and a click that misses one is a click on nothing. Without this
    // the fall-through at the bottom would disarm the tool the moment the hand
    // slipped off a vertex onto a room.
    if (clickMode === 'boundary') return
    if ((!clickMode && !armedProp && !calibrationRoomId) || !room.id) return
    e.stopPropagation()
    const raster = (v: number) => (e.shiftKey ? v : snapToGrid(v, gridStep))
    // In the frame the shape STORES its placements in: room-local for a room
    // (its STRAIGHT frame — a turned room turns the cursor back), and
    // location-local on the yard (§ A13a).
    const o = atOrigin(lay, ground)
    const [mxRaw, myRaw] = storedAt(lay, ground,
                                    pointerM(e.clientX, e.clientY))
    const px = rM(clamp(raster(mxRaw), o[0], o[0] + lay.w))
    const py = rM(clamp(raster(myRaw), o[1], o[1] + lay.d))
    if (!clickMode && !armedProp) {
      // Calibration figure armed: a click inside ITS room moves the
      // reference person there (UI state only, never stored).
      if (room.id === calibrationRoomId) onCalibrationAt?.([px, py])
      return
    }
    // The STORED layout — on the yard it may not exist yet (its first prop
    // creates it), and it never carries the derived rect `lay` shows.
    const stored = room.layout
    if (armedProp) {
      // Place the armed prop at the clicked spot. REAL-size rule: only
      // position + yaw are stored — the prop's own dims scale it. The tool
      // stays armed for multiple placements; Esc or re-picking ends it.
      const placements = [...(stored?.props || []),
        { prop_id: armedProp, at: [px, py] as [number, number],
          ...(ghostYaw ? { yaw: ghostYaw } : {}) }]
      updateLayout(room.id, { props: placements })
      setSelected(room.id)
      setPropSel(placements.length - 1)
      return
    }
    if (clickMode === 'marker-move') {
      // Reposition the SELECTED marker — only inside its own room.
      if (room.id === selected && markerSel !== null) {
        updateLayout(room.id, {
          markers: (stored?.markers || []).map((m, idx) =>
            idx === markerSel ? { ...m, at: [px, py] as [number, number] } : m),
        })
      }
    } else if (clickMode === 'marker' && markerGroup) {
      // The id is minted HERE so the preview cycler can address the marker
      // before the first save — the server keeps a client-sent id verbatim.
      updateLayout(room.id, {
        markers: [...(stored?.markers || []),
                  { id: newId(), group: markerGroup, at: [px, py] as [number, number] }],
      })
      setMarkerSel((stored?.markers || []).length)
    } else if (ground) {
      // Everything below is ROOM GEOMETRY — hull curves, doors, windows. The
      // yard has none of it (§ A13a); the toolbar disables these tools there,
      // this is the same refusal for a click that got through anyway.
      return
    } else if (clickMode === 'curve') {
      // Toggle a bezier control point on the nearest hull edge of the
      // SELECTED room (plan-area-detail-scenes.md). The mode stays armed —
      // a road bends more than once.
      const lay0 = lay
      if (room.id !== selected || !lay0.outline || lay0.outline.length < 3) return
      const { edge } = nearestPolygonEdge(outlineOf(lay0), [px, py])
      const cur = lay0.outline_curves || []
      let next: NonNullable<RoomLayout['outline_curves']>
      if (cur.some((c) => c.edge === edge)) {
        next = cur.filter((c) => c.edge !== edge)
      } else {
        // Start the control point at the edge midpoint pushed OUTWARD by a
        // quarter edge length: hulls wind clockwise in screen coords, the
        // interior lies right of a→b, so outward is (dy, −dx).
        const { a, b } = edgeSegment(outlineOf(lay0), edge)
        const dx = b[0] - a[0]
        const dy = b[1] - a[1]
        const c: [number, number] = [
          rM(clamp((a[0] + b[0]) / 2 + dy * 0.25, -PLAN_MAX_M, PLAN_MAX_M)),
          rM(clamp((a[1] + b[1]) / 2 - dx * 0.25, -PLAN_MAX_M, PLAN_MAX_M)),
        ]
        next = [...cur, { edge, c }]
      }
      updateLayout(room.id, { outline_curves: next.length ? next : undefined })
      return
    } else if (clickMode === 'door' || clickMode === 'window') {
      // Place a door/window on the nearest hull edge at the clicked
      // position. `to` follows from where the edge leads: a shared wall
      // points at the neighbour, an exterior wall at "outside" — editable
      // in the panel.
      const { edge, at } = nearestPolygonEdge(outlineOf(lay), [px, py])
      if ((lay.outline_curves || []).some((c) => c.edge === edge)) {
        // The server rejects these (v1) — refuse up front instead of
        // silently losing the opening on save.
        toast(t('Openings cannot sit on a curved edge — remove the curve first.'), 'error')
        return
      }
      const lay0 = lay
      const others = hullsOf(roomsRef.current, lay0.level || 0, room.id)
      const hull: PolyRoom = { id: room.id, x: lay0.x, y: lay0.y,
        w: lay0.w, d: lay0.d, outline: lay0.outline,
        rotation: lay0.rotation }
      const shared = sharedEdges(hull, others).find((sh) => sh.edge === edge)
      const openings: RoomOpening[] = [...(lay.openings || []),
        clickMode === 'window'
          ? { edge, at, type: 'window', width_m: 1.2, height_m: 1.2,
              sill_m: 0.9, to: shared ? shared.neighborId : 'outside' }
          : { edge, at, ...OPENING_DEFAULT,
              to: shared ? shared.neighborId : 'outside' }]
      updateLayout(room.id, { openings })
      setOpeningSel(openings.length - 1)
      // Single shot: back to normal mode — an armed tool made it too easy
      // to stack several doors/windows on top of each other.
    }
    setClickMode('')
  }, [clickMode, armedProp, ghostYaw, markerGroup, markerSel, selected,
    setSelected, updateLayout, calibrationRoomId, onCalibrationAt, t, toast,
    pointerM, gridStep])

  // The selected shape. A room qualifies once it has a RECTANGLE; the yard
  // qualifies as soon as the location has a boundary — it needs no layout of
  // its own to be worked on, its first prop is what creates one (§ A13a).
  const selectedRoom = rooms.find((r) => r.id === selected
    && (hasRect(r.layout) || (r.id === GROUND_ROOM_ID && !!yardLay)))
  /** The yard is the selected shape — room geometry is off for all of it. */
  const groundSel = !!selectedRoom && selectedRoom.id === GROUND_ROOM_ID
  /** The selected shape's rectangle: its own, or the yard's derived one. */
  const selLay: PlacedLayout | null = groundSel
    ? yardLay
    : (hasRect(selectedRoom?.layout) ? selectedRoom.layout : null)
  /** Where the selected shape's placements are stored (§ A13a). */
  const selOrigin: Pt = selLay ? atOrigin(selLay, groundSel) : [0, 0]
  /** Why a room tool is off on the yard — one sentence, one owner. */
  const yardNoGeometry = t('The yard has no room geometry — it is the location surface.')
  /**
   * Does the SELECTED room stand on painted water (W1 § 6)?
   *
   * The answer is the SERVER's, read off the composed scene
   * (`floor_plan[].map_water`) and not recomputed here: the containment test is
   * a majority-by-area vote on a fixed raster, with the paint order breaking
   * ties, and a second implementation of that in the editor would be exactly
   * the drifting second opinion the shared scene recipe exists to prevent.
   * The yard is never in the floor plan — it IS the plot, not a room on it.
   */
  const selectedMapWater = useMemo(() => {
    if (!selectedRoom || groundSel) return null
    const floor = (scene?.floor_plan || [])
      .find((f) => f.room_id === selectedRoom.id)
    return readMapWater(floor)
  }, [groundSel, scene, selectedRoom])

  // Model presence for the SELECTED room — the plan-placement handle and
  // strip only show when a diorama model exists (anchored mode loads dims
  // for all rooms anyway; this covers the legacy mode too).
  useEffect(() => {
    if (!selected || selected === GROUND_ROOM_ID || selected in modelDims) return
    getRoomModelDims(selected)
      .then((d) => setModelDims((prev) => ({ ...prev, [selected]: d })))
      .catch(() => setModelDims((prev) => ({ ...prev, [selected]: null })))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected])

  // Arm a click mode from the toolbar (clicking the armed tool disarms it).
  // Drawing modes start with an empty draft; redrawing targets the selected
  // room — the "Not on the plan" chips arm the same mode for a new room.
  const armMode = useCallback((m: PlanMode) => {
    if (clickMode === m || !m) {
      cancelDraw()
      return
    }
    // NO SCALE-ANCHOR LOCK ANY MORE (v6 Nr. 2). A layout carries its own
    // metres, so there is nothing for a plan width to anchor — and the lock
    // was what made a boundary-less location undrawable at all, since the
    // server now DERIVES `plan_width_m` from the boundary and overwrites
    // whatever the field here sent.
    // The yard has no hull, no walls and no rectangle: every mode that edits
    // room geometry is refused there (§ A13a). Markers and props are not
    // geometry — they are content, and they stay.
    if (groundSel && (m === 'draw-room' || m === 'curve' || m === 'door'
        || m === 'window')) {
      planLog('armMode refused: the yard has no room geometry', { mode: m })
      return
    }
    if (m === 'draw-room') {
      if (!selectedRoom?.id) {
        planLog('armMode refused: no room selected', { selected })
        return
      }
      setDrawTarget(selectedRoom.id)
    }
    // Curves bend hull edges — without a drawn hull there is nothing to bend.
    if (m === 'curve' && !selectedRoom?.layout?.outline?.length) {
      planLog('armMode refused: the selected room has no drawn hull')
      return
    }
    setOutlineDraft([])
    setHoverSnap(null)
    setClickMode(m)
    planLog('armed', { mode: m })
  }, [clickMode, selected, selectedRoom, groundSel, cancelDraw])

  /**
   * Arm the hull pen ON A NAMED ROOM — the route that does NOT go through the
   * selection.
   *
   * The toolbar's ⬠ redraws the SELECTED shape, and only a room that is
   * already on the plan (or the yard, which refuses) can be selected. A
   * location whose rooms have no layout yet therefore has nothing selectable
   * but the yard, and the yard turns every room tool off: pressing ⬠ there
   * did nothing and said nothing (user finding 2026-08-20 — a location with a
   * drawn boundary, no pin and not one placed room). This is the way in for
   * exactly that state, and the "Not on the plan" chips use it too — one
   * arming path, not two.
   */
  const armDrawFor = useCallback((roomId: string) => {
    if (!roomId || roomId === GROUND_ROOM_ID) {
      planLog('armDrawFor refused: no room id, or the yard', { roomId })
      return
    }
    planLog('armDrawFor', { roomId })
    setSelected(roomId)
    setDrawTarget(roomId)
    setOutlineDraft([])
    setHoverSnap(null)
    setArmedProp('')
    setPropGhost(null)
    setClickMode('draw-room')
  }, [setSelected])

  // Room shell: pick the surface-texture kind for floor or wall. Empty keys
  // are pruned, an all-empty map drops the field — the client then falls back
  // to the global kind / its own default.
  const setSurface = useCallback((key: 'floor' | 'wall', kind: string) => {
    const lay = roomsRef.current.find((r) => r.id === selected)?.layout
    // The yard has no shell to skin — its ground kind is the location's
    // `terrain`, set on the 3D-world tab (§ A13a).
    if (!lay || selected === GROUND_ROOM_ID) return
    const merged = { ...(lay.surfaces || {}), [key]: kind.trim() }
    const surfaces: { floor?: string; wall?: string } = {}
    if (merged.floor) surfaces.floor = merged.floor
    if (merged.wall) surfaces.wall = merged.wall
    updateLayout(selected, {
      surfaces: Object.keys(surfaces).length ? surfaces : undefined,
    })
  }, [selected, updateLayout])

  // ROTATION IS ONE FIELD NOW (contract v6 addendum, 2026-08-20).
  //
  // `layout.rotation` turns the WHOLE room about its rect centre — hull,
  // walls, openings, markers, props and the 3D model in one move — so this
  // button no longer BAKES a turn into every stored coordinate. It sets the
  // angle, nothing else: the rectangle keeps its size (there is no w/d swap
  // any more, the room's own frame stays straight), the openings keep their
  // edge indices, and the drawing is turned on the way out.
  //
  // That also ends an old inconsistency: the bake turned the geometry
  // CLOCKWISE on the plan while the very same call bumped `rotation` +90,
  // which turns counter-clockwise in world axes (§ A1.1). One angle, one
  // sense, one field.
  /** Write the selected room's angle (0…359; 0 drops the field). */
  const setRotation = (deg: number) => {
    if (!selectedRoom || groundSel || !hasRect(selectedRoom.layout)) return
    const norm = ((Math.round(deg) % 360) + 360) % 360
    updateLayout(selectedRoom.id || '', { rotation: norm || undefined })
  }

  const rotateSelected = (step = 90) => {
    const lay = selectedRoom?.layout
    // Turning the yard would mean turning the location boundary — a map-tab
    // edit, not a floor-plan one (§ A13a).
    if (!hasRect(lay) || !selectedRoom || groundSel) return
    setRotation((lay.rotation || 0) + step)
  }

  // "Suggest openings": a door on every shared wall (once per pair, on the
  // room that triggers it, `to` = the neighbour), an ENTRANCE door for every
  // room that would otherwise stay sealed, and a window on every exterior
  // edge ≥ 2.5 m. Suggestions are normal, editable openings; the button never
  // overwrites — it skips any edge that already carries an opening.
  const suggestOpenings = () => {
    // Everything below is metres now (v6 Nr. 2) — no plan width converts a
    // tolerance or an edge length any more.
    // The yard is out (`hullsOf`): it has no hull, no walls and no openings
    // (§ A13a).
    const onLevel = rooms.filter((r) => r.id && hasRect(r.layout)
      && (r.layout.level || 0) === level)
    const hulls = hullsOf(onLevel, level)
    const additions = new Map<string, RoomOpening[]>()
    const layoutOf = (id: string) => onLevel.find((r) => r.id === id)!.layout!
    const edgeTaken = (id: string, edge: number) =>
      (layoutOf(id).openings || []).some((o) => normalizeOpeningEdge(o).edge === edge)
      || (additions.get(id) || []).some((o) => o.edge === edge)
    const add = (id: string, op: RoomOpening) => {
      const list = additions.get(id) || []
      list.push(op)
      additions.set(id, list)
    }

    // Doors on shared edges — once per pair (i < j = the trigger room).
    for (let i = 0; i < hulls.length; i++) {
      for (let j = i + 1; j < hulls.length; j++) {
        for (const s of sharedEdges(hulls[i], [hulls[j]])) {
          if (edgeTaken(hulls[i].id, s.edge)) continue
          add(hulls[i].id, { edge: s.edge, at: s.at, type: 'door',
            width_m: 1.0, height_m: 2.1, sill_m: 0, to: s.neighborId })
        }
      }
    }
    // Entrance guarantee: a room the shared-wall pass left without ANY door
    // would be sealed (a single-room location got nothing at all before).
    // It gets an outside door on its longest exterior edge — no `to`.
    for (const a of hulls) {
      const hasDoor = (layoutOf(a.id).openings || []).some((o) => o.type === 'door')
        || (additions.get(a.id) || []).some((o) => o.type === 'door')
      if (hasDoor) continue
      const oa = absOutline(a)
      const candidates = exteriorEdges(a, hulls.filter((r) => r.id !== a.id))
        .map((e) => {
          const seg = edgeSegment(oa, e)
          return { edge: e,
            len: Math.hypot(seg.b[0] - seg.a[0], seg.b[1] - seg.a[1]) }
        })
        .sort((x, y) => y.len - x.len)
      if (!candidates.length) continue
      // Prefer a free edge; if every exterior edge already carries something
      // (windows all round), share the longest one — several openings per
      // edge are legal, so the door sits next to the window.
      const free = candidates.find((c) => !edgeTaken(a.id, c.edge))
      const target = free || candidates[0]
      add(a.id, { edge: target.edge, at: free ? 0.5 : 0.35, type: 'door',
        width_m: 1.0, height_m: 2.1, sill_m: 0, to: 'outside' })
    }
    // Windows on exterior edges ≥ 2.5 m (needs the plan width for the length).
    for (const a of hulls) {
      const oa = absOutline(a)
      for (const e of exteriorEdges(a, hulls.filter((r) => r.id !== a.id))) {
        const seg = edgeSegment(oa, e)
        const edgeLenM = Math.hypot(seg.b[0] - seg.a[0], seg.b[1] - seg.a[1])
        if (edgeLenM < MIN_WINDOW_EDGE_M || edgeTaken(a.id, e)) continue
        add(a.id, { edge: e, at: 0.5, type: 'window',
          width_m: 1.2, height_m: 1.2, sill_m: 0.9, to: 'outside' })
      }
    }

    if (additions.size === 0) return
    onChange(rooms.map((r) => (r.id && r.layout && additions.has(r.id)
      ? { ...r, layout: { ...r.layout, openings: [...(r.layout.openings || []), ...additions.get(r.id)!] } }
      : r)))
  }

  // Metres -> the overlay SVG's own units (its viewBox is 100 units across the
  // window, so one metre is 100 / view.size units). The %-positioned DOM
  // children use `fx`/`fz` directly.
  const svgX = (x: number) => fx(x) * 100
  const svgZ = (z: number) => fz(z) * 100
  const uPerM = 100 / view.size
  // Where the reference figure stands when the user has not moved it: bottom
  // left of the window, clear of the scale bar.
  const figureAt: [number, number] = figurePos
    ?? [view.x0 + view.size * 0.12, view.z0 + view.size * 0.86]

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      <div className="ga-form-section-label">{t('Room layout (floor plan)')}</div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
          title={t('0 = ground floor, negative = basement. Saved with the location.')}>
          {t('Level')}
          <input
            className="ga-input"
            type="number"
            style={{ width: 64 }}
            value={level}
            onChange={(e) => {
              const n = parseInt(e.target.value, 10)
              setLevel(Number.isFinite(n) ? n : 0)
              setSelected('')
              setClickMode('')
            }}
          />
        </label>
        {levels.length > 0 ? (
          <span style={{ display: 'inline-flex', gap: 4 }}>
            {levels.map((lv) => (
              <button
                key={lv}
                type="button"
                className={`ga-btn ga-btn-sm${lv === level ? ' ga-btn-primary' : ''}`}
                onClick={() => { setLevel(lv); setSelected(''); setClickMode('') }}
                title={t('Rooms on this level: {n}').replace('{n}',
                  String(rooms.filter((r) => hasRect(r.layout)
                    && (r.layout.level || 0) === lv).length))}
              >
                {lv}
              </button>
            ))}
          </span>
        ) : null}
        <span aria-hidden style={{ width: 1, alignSelf: 'stretch',
          background: 'var(--border, #30363d)', margin: '0 2px' }} />
        {/* Underlay toggles — up here instead of the tool column, they are
            view state, not tools. */}
        <button
          type="button"
          className={`ga-btn ga-btn-sm${underlay ? ' ga-btn-primary' : ''}`}
          onClick={() => setUnderlay((v) => !v)}
          title={t('Lay the placed room models (top-down view) behind the plan — markers can be dropped on real furniture.')}
        >
          🖼
        </button>
        <button
          type="button"
          className={`ga-btn ga-btn-sm${bUnderlay ? ' ga-btn-primary' : ''}`}
          onClick={() => setBUnderlay((v) => !v)}
          title={t('Lay the building model (roof view = real footprint) behind the plan — for tracing the outline polygon.')}
        >
          🏢
        </button>
        <button
          type="button"
          className={`ga-btn ga-btn-sm${aids ? ' ga-btn-primary' : ''}`}
          onClick={() => setAids((v) => !v)}
          title={t('Reference sizes: a metre grid labelled in metres from the anchor pin, and the 1.70 m person from above, draggable. The scale bar at the bottom left stays either way.')}
        >
          📏
        </button>
        {/* Drawing raster. Every drawn point, every dragged rectangle and
            every placement falls onto it; Shift is the per-click escape, and
            real geometry (a wall, a boundary edge, a vertex) always beats the
            raster. */}
        <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
          title={t('Snap grid: drawing, dragging and placing fall onto this raster. Hold Shift for free hand; snapping to an existing wall, vertex or boundary edge always wins over the raster.')}>
          ⊞
          <select className="ga-input" style={{ width: 84 }}
            value={String(gridStep)}
            onChange={(e) => setGridStep(Number(e.target.value) || 0)}>
            {GRID_STEPS.map((g) => (
              <option key={g} value={g}>
                {g ? `${g} m` : t('free')}
              </option>
            ))}
          </select>
        </label>
        <span aria-hidden style={{ width: 1, alignSelf: 'stretch',
          background: 'var(--border, #30363d)', margin: '0 2px' }} />
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={planZoom <= 1}
          onClick={() => setPlanZoom((z) => Math.max(1, z - 0.25))}
          title={t('Zoom the 2D plan out (mouse wheel over the plan works too).')}>
          ➖
        </button>
        <button type="button" className="ga-btn ga-btn-sm"
          onClick={() => setPlanZoom(1)}
          title={t('Reset the plan zoom to 100%.')}
          style={{ minWidth: 52 }}>
          {Math.round(planZoom * 100)}%
        </button>
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={planZoom >= 3}
          onClick={() => setPlanZoom((z) => Math.min(3, z + 0.25))}
          title={t('Zoom the 2D plan in for precise placement (mouse wheel over the plan works too).')}>
          ➕
        </button>
        {onMap3d ? (
          <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Floor texture of THIS storey: the client tiles the whole level plate with the kind; a room floor kind overrides only its own area. Empty = the global floor kind.')}>
            🟫
            <select
              className="ga-input"
              style={{ maxWidth: 130 }}
              value={map3d?.level_floors?.[String(level)] || ''}
              onChange={(e) => {
                const merged = { ...(map3d?.level_floors || {}) }
                if (e.target.value) merged[String(level)] = e.target.value
                else delete merged[String(level)]
                onMap3d('level_floors',
                  Object.keys(merged).length ? merged : undefined)
              }}
            >
              <option value="">{t('Level floor: global')}</option>
              {surfaceKinds.map((k) => (
                <option key={k.kind} value={k.kind}>{k.name}</option>
              ))}
            </select>
          </label>
        ) : null}
        {onMap3d ? (
          <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Wall texture of the whole building shell: the client tiles every contour wall with the kind. Not per storey — one shell, one kind. A room wall keeps its own wall kind. Empty = plain shell colour.')}>
            🧱
            <select
              className="ga-input"
              style={{ maxWidth: 130 }}
              value={map3d?.wall_kind || ''}
              onChange={(e) => onMap3d('wall_kind', e.target.value || undefined)}
            >
              <option value="">{t('Building walls: none')}</option>
              {surfaceKinds.map((k) => (
                <option key={k.kind} value={k.kind}>{k.name}</option>
              ))}
            </select>
          </label>
        ) : null}
        {onMap3d ? (
          <label className="ga-check-row" style={{ fontSize: '0.82em' }}
            title={t('For villages, lakes and other AREAS: the location model stays in the interior view and gets holes cut into it — the floor plan plus every indoor room placed outside it. Outdoor rooms outside the plan become walkable zones on the model surface. Off = single building, the model fades out.')}>
            <input type="checkbox" checked={!!map3d?.area_model}
              onChange={(e) => {
                onMap3d('area_model', e.target.checked || undefined)
                if (!e.target.checked) onMap3d('area_detail', undefined)
              }} />
            <span>{t('Area location (model stays in interior view)')}</span>
          </label>
        ) : null}
        {onMap3d && map3d?.area_model ? (
          <label className="ga-check-row" style={{ fontSize: '0.82em' }}
            title={t('Detail scene: the area model becomes a fading shell — zooming in fades it out like a building and shows the drawn rooms (ground textures, scattered props) instead. No holes are cut into the model any more.')}>
            <input type="checkbox" checked={!!map3d?.area_detail}
              onChange={(e) => onMap3d('area_detail', e.target.checked || undefined)} />
            <span>{t('Detail scene (model fades on zoom-in)')}</span>
          </label>
        ) : null}
        {/* THE SCENE'S OWN RELIEF IS GONE ("Ein Boden" E5a, decision 1 of
            the plan): the amplitude/seed/wave dials and the per-room "Keep
            flat" opt-out that stood here rolled a 17 × 17 height field that
            existed nowhere but in this one scene — a second ground next to
            the world's. Local relief is authored on the map's HEIGHT AREAS
            now, and every consumer reads the one field (`h_final`). */}
      </div>

      {/* NO BOUNDARY DRAWN. The location's footprint IS the drawn polygon, and
          `plan_width_m` is only its derived bounding-box width — not an input
          any more, the server ignores a submitted one (closing wave
          2026-08-19). So there is no width field here: without an outline the
          place has no area anywhere, and the only fix is drawing one on the
          map tab. It is not a lock on these tools either — rooms carry their
          own metres and can be drawn right away; the plan window falls back to
          a {FALLBACK_VIEW_M} m square around the pin until the plot exists. */}
      {!hasBoundary ? (
        <div className="ga-anchor-banner">
          <span style={{ flex: 1, minWidth: 200 }}>
            ⚠ {t('No boundary drawn — this location has no area anywhere. Draw one here or on the map tab; until then the plan works on a {n} m square around the pin.')
              .replace('{n}', String(FALLBACK_VIEW_M))}
          </span>
          {onMap3d && locationId ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              onClick={seedBoundary}
              title={t('Write a centred square as the boundary — the same seed the map tab lays down. Then reshape it with the 🟩 tool: drag a vertex, click an edge to insert one, double-click a vertex to remove it.')}
            >
              ✎ {t('Draw boundary')}
            </button>
          ) : null}
        </div>
      ) : !placedOnMap ? (
        // DRAWN, BUT ON NO MAP. The boundary survives unplacing by design —
        // it is the location's own shape, in its own local metres — so it
        // stays fully editable here, and the plan says out loud what it is
        // looking at instead of showing a polygon that could mean either
        // state (user finding 2026-08-20).
        <div className="ga-anchor-banner">
          <span style={{ flex: 1, minWidth: 200 }}>
            ℹ {t('Not placed on the map — this boundary is used when you place it.')}
          </span>
        </div>
      ) : null}

      {/* NOTHING IS ON THE PLAN YET. The ⬠ tool in the strip redraws the
          SELECTED shape, and with no room placed there is nothing selectable
          but the yard — which turns every room tool off. The way in used to be
          a chip at the very bottom of this column, below the canvas, the scale
          bar, the findings and two more rows; the plan itself just sat there
          refusing every click without a word (user finding 2026-08-20). So the
          way in is stated HERE, above the canvas, and it is the same one
          arming path. */}
      {!placedHere.length && unplaced.length ? (
        <div className="ga-anchor-banner">
          <span style={{ flex: 1, minWidth: 200 }}>
            {t('No room of this location is on the plan yet — the ⬠ tool in the strip redraws a room that already has a shape. Pick a room here to draw its first one:')}
          </span>
          {unplaced.map((room) => (
            <button
              key={room.id || room.name}
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'draw-room' && drawTarget === room.id ? ' ga-btn-primary' : ''}`}
              onClick={() => armDrawFor(room.id || '')}
              title={t('Draw this room on the current level — click to place points, click the first point to close, Shift = free-hand, Esc = cancel.')}
            >
              ⬠ {room.name || room.id}
            </button>
          ))}
        </div>
      ) : null}

      {/* Review banner: a furnishing proposal is waiting for the selected
          room — the ghosts on the plan are exactly what Accept stores. */}
      {reviewing ? (
        <div className="ga-furnish-banner">
          <span>
            ✨ {t('Proposed furnishing')} — {t('{n} ghosts on the plan')
              .replace('{n}', String(furnish.ghosts.length))}
            {furnish.status?.placements?.unplaced?.length
              ? ` · ${t('{n} not placed').replace('{n}',
                String(furnish.status.placements.unplaced.length))}`
              : ''}
          </span>
          <span style={{ flex: 1 }} />
          <button type="button" className="ga-btn ga-btn-sm"
            disabled={furnish.busy}
            onClick={() => { void furnish.act('discard') }}>
            {t('Discard')}
          </button>
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={furnish.busy || !furnish.ghosts.length}
            onClick={() => { void acceptFurnish() }}>
            {t('Accept')}
          </button>
        </div>
      ) : null}

      {/* THE NUDGE AT THE MOMENT OF THE MISTAKE. Drawing the building contour
          while not one room has a floor plan is the exact gesture that earns
          the server's `rooms_without_layout` finding — correct, and useless
          after the fact, because the author drew that polygon believing it was
          a room (user finding 2026-08-20). One line, while the pen is armed;
          not a modal, and nothing is refused. */}
      {clickMode === 'outline' && !anyRoomPlaced ? (
        <div className="ga-hint" style={{ fontSize: '0.8em' }}>
          ℹ {t('The contour outlines the building — rooms are drawn with the room tool (⬠), and a location needs at least one of them to be enterable.')}
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <PlanToolbar
        mode={clickMode}
        hasSelection={!!selectedRoom}
        selectionRotation={selectedRoom?.layout?.rotation || 0}
        hasOutline={!!map3d?.outline?.length}
        hasBoundary={hasBoundary}
        outlineDraftLen={outlineDraft.length}
        hasElevator={!!map3d?.elevator}
        stairCount={map3d?.stairs?.length || 0}
        stairLevel={level}
        building={!!onMap3d}
        canSuggest={placedHere.length > 0}
        canFitToModel={!groundSel && !!(selectedRoom?.id
          && (modelDims[selectedRoom.id]?.widthM || 0) > 0)}
        canCurve={!groundSel && !!selectedRoom?.layout?.outline?.length}
        ground={groundSel}
        groundHint={yardNoGeometry}
        noSelectionHint={t('Nothing is selected — these tools work on ONE shape. Pick a room with the chips under the plan; a room that has no shape yet is drawn with its own ⬠ button in the hint above the plan.')}
        onFitToModel={fitToModel}
        propsOpen={propsOpen}
        onMode={armMode}
        onRotate={rotateSelected}
        onUnplace={() => { updateLayout(selectedRoom?.id || '', null); setSelected('') }}
        onRemoveOutline={() => onMap3d?.('outline', undefined)}
        onRemoveElevator={() => onMap3d?.('elevator', undefined)}
        onCommitOutline={commitOutline}
        onCommitRoom={commitRoomDraft}
        onCancelDraw={cancelDraw}
        onSuggest={suggestOpenings}
        onProps={() => setPropsOpen((v) => !v)}
      />
      {/* Zoom viewport: the canvas grows with the zoom, this box keeps the
          layout footprint and scrolls (Ctrl+wheel zooms on the canvas). The
          frame around it carries the scale bar — inside the viewport a
          zoomed-in plan would scroll its own scale out of sight. */}
      <div style={{ position: 'relative', flex: '0 1 auto', maxWidth: '100%' }}>
      <div ref={zoomViewportRef} style={{ overflow: 'auto', maxWidth: '100%',
        maxHeight: canvasH + 14 }}>
      <div
        ref={canvasRef}
        style={{
          position: 'relative',
          // SQUARE, always: the height follows the width the browser really
          // gives us. With a fixed height a narrow pane would shrink only the
          // width and squeeze every fraction-drawn overlay horizontally — on
          // a surface that claims to show metres, that is not acceptable.
          width: CANVAS_W * planZoom, aspectRatio: '1 / 1',
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
            {map3d?.outline?.length ? (
              <polygon
                points={map3d.outline.map(([x, z]) => `${svgX(x)},${svgZ(z)}`).join(' ')}
                fill="rgba(88,166,255,0.07)" stroke="#58a6ff" strokeWidth={0.6}
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
                      if (clickMode || armedProp || !room.id) return
                      e.preventDefault()
                      e.stopPropagation()
                      dragRef.current = { kind: 'model', roomId: room.id }
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
                      setSelected(room.id || '')
                      // Stacked footprints: repeated clicks on the same spot
                      // walk through everything under the cursor. `hits` is
                      // ASCENDING BY PLACEMENT INDEX — the same order the
                      // stacking rule uses (later placement wins ties, it is
                      // drawn and picked on top), so `hits[last]` is the
                      // topmost piece and the one a fresh click takes. Each
                      // further click moves ONE ENTRY ON in that list and
                      // wraps, so the walk runs top → bottom → upwards → top
                      // and reaches every piece of the stack.
                      // Metres from the shape's min corner — through the
                      // CANVAS, not through the room box: a turned box has a
                      // rotated bounding rect, and its client rect would be
                      // the wrong frame (v6 addendum).
                      const hit = storedAt(lay, ground,
                                           pointerM(e.clientX, e.clientY))
                      const hits = propsAtPoint(content || {}, o,
                        hit[0] - o[0], hit[1] - o[1])
                      if (hits.length < 2) {
                        setPropSel(i)
                        return
                      }
                      // `propSel` is the selection as it stood BEFORE this
                      // click (the press no longer touches it) — that is what
                      // makes the cycle advance instead of restarting. A
                      // selection from elsewhere is not in `hits`, so the
                      // click falls back to the topmost piece.
                      const pos = room.id === selected && propSel !== null
                        ? hits.indexOf(propSel) : -1
                      setPropSel(pos >= 0
                        ? hits[(pos + 1) % hits.length]
                        : hits[hits.length - 1])
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
              const flight = sceneStairs.get(i)
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
                    setStairSel(i)
                    setElevatorSel(false)
                    setMarkerSel(null)
                    // Picking an ARRIVING flight takes the plan down to the
                    // storey it starts on — that is where it is edited, and
                    // the numbers in the row below belong to that storey.
                    if (st.from_level !== level) setLevel(st.from_level)
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
      </div>
      <PlanScaleBar view={view} canvasPx={canvasPx} />
      {/* THE THREE SHAPES, NAMED. The plan draws a plot, a house and rooms on
          top of each other, and until this line existed nothing said which was
          which — an author who drew the building contour expecting a room got
          a correct but unhelpful "no room has a floor plan" and no way to tell
          the shapes apart (user finding 2026-08-20). One line, always visible,
          in the colours and strokes the canvas really uses. */}
      <div className="ga-hint" style={{ display: 'flex', gap: 10,
        flexWrap: 'wrap', alignItems: 'center', marginTop: 4,
        fontSize: '0.76em' }}>
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
          title={t('The plot itself — the ground this location covers. Editable here with the 🟩 tool and on the map tab; solid once the location is placed, dashed while it is not.')}>
          <svg width={20} height={8} aria-hidden>
            <line x1={1} y1={4} x2={19} y2={4} stroke="#3fb950" strokeWidth={2}
              strokeDasharray={hasBoundary && placedOnMap ? undefined : '4 3'} />
          </svg>
          {t('location boundary')}
        </span>
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
          title={t('The building standing on the plot — the 🏗 tool draws it. It is NOT a room: a contour with no room inside holds nothing anybody can enter.')}>
          <svg width={20} height={8} aria-hidden>
            <line x1={1} y1={4} x2={19} y2={4} stroke="#58a6ff" strokeWidth={2} />
          </svg>
          {t('building contour')}
        </span>
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
          title={t('The rooms — what can actually be entered. Drawn with the ⬠ tool; every location needs at least one.')}>
          <svg width={20} height={8} aria-hidden>
            <rect x={1} y={1} width={18} height={6} fill="rgba(139,148,158,0.12)"
              stroke="#8b949e" strokeWidth={1.5} />
          </svg>
          {t('rooms')}
        </span>
      </div>
      {/* The editor's OWN finding, not the server's: rooms left over from the
          fraction era. Gentle — it is a "here is why", not an error, and it
          names the rooms so the author can go and fix the right ones. */}
      {tinyRooms.length ? (
        <div className="ga-form" style={{ gap: 4, marginTop: 6 }}>
          <div className="ga-anchor-banner">
            <span>⚠ {t('{rooms} — smaller than {n} m. These are leftovers from before rooms were stored in metres; their old share of the reference square is now read as metres. Nothing repairs them automatically: delete them, or redraw their hull with ⬠.')
              .replace('{rooms}', tinyRooms.map((r) => r.name || r.id).join(', '))
              .replace('{n}', String(TINY_ROOM_M))}</span>
          </div>
        </div>
      ) : null}
      {/* Findings of the SERVER about this floor plan (§ 4.3,
          plan-betreten-und-tueren.md): the composer states them, the editor
          only shows them — at the room it names, otherwise at the location. */}
      {(scene?.problems || []).length ? (
        <div className="ga-form" style={{ gap: 4, marginTop: 6 }}>
          {(scene?.problems || []).map((p, i) => (
            <div key={`${p.kind}-${p.room_id || ''}-${i}`}
              className="ga-anchor-banner">
              <span>⚠ {problemText(p)}</span>
            </div>
          ))}
        </div>
      ) : null}
      {/* Boundary pass-throughs (plan-area-detail-scenes.md): building-level
          data, so the rows live under the plan, not in the room panel. An
          ordinary means of every location, not a speciality of area/detail
          ones (ruling 2026-08-04) — shown with zero openings too, when the
          server reports no entrance at all (has_entrance false), which is
          exactly where one gets added. */}
      {onMap3d
        && (map3d?.boundary_openings?.length || hasEntrance === false) ? (
        <div className="ga-form" style={{ gap: 4, marginTop: 6 }}>
          <div className="ga-form-section-label">{t('Boundary pass-throughs')}</div>
          {hasEntrance === false ? (
            <div className="ga-anchor-banner">
              <span>ℹ {t('No pass-through drawn: characters may enter anywhere along the boundary. Draw openings to channel entry.')}</span>
            </div>
          ) : null}
          {(map3d?.boundary_openings || []).map((bo, i) => {
            const write = (patch: Partial<typeof bo>) =>
              onMap3d('boundary_openings', (map3d?.boundary_openings || [])
                .map((b, j) => (j === i ? { ...b, ...patch } : b)))
            return (
              <div key={i} onClick={() => setSelectedBoundary(i)}
                style={{ display: 'flex', gap: 6, alignItems: 'center',
                  fontSize: '0.82em', padding: '2px 4px', borderRadius: 4,
                  background: selectedBoundary === i
                    ? 'rgba(224,163,86,0.15)' : undefined }}>
                {/* WHICH boundary edge the pass-through sits on (v6 Nr. 5):
                    an index, labelled with the two points it runs between so
                    it can be picked without counting vertices on the plan.
                    Clicking the gold bar selects the row; clicking the plan
                    in "pass-through" mode picks the nearest edge outright. */}
                <select className="ga-input" style={{ width: 168 }}
                  value={bo.edge}
                  title={t('Boundary edge the pass-through sits on')}
                  onChange={(e) => write({ edge: Number(e.target.value) })}>
                  {boundaryM.map((_p, ei) => {
                    const { a, b } = edgeSegment(boundaryM, ei)
                    // The points ARE local metres — the label just rounds.
                    const m = (v: number) => Math.round(v * 10) / 10
                    return (
                      <option key={ei} value={ei}>
                        {`${t('Edge')} ${ei}: (${m(a[0])},${m(a[1])})→(${m(b[0])},${m(b[1])})`}
                      </option>
                    )
                  })}
                  {bo.edge >= boundaryM.length ? (
                    <option value={bo.edge}>
                      {`${t('Edge')} ${bo.edge} — ${t('outside the boundary')}`}
                    </option>
                  ) : null}
                </select>
                <input className="ga-input" type="number" min={0} max={1}
                  step={0.01} style={{ width: 64 }} value={bo.at}
                  title={t('Position along the edge (0..1)')}
                  onChange={(e) => {
                    const v = Number(e.target.value)
                    if (Number.isFinite(v)) write({ at: r4(clamp(v, 0, 1)) })
                  }} />
                {/* The pass-through lies ON a boundary edge, and the
                    location's own width is its maximum (plan_width_m — the
                    bounding box of the drawn outline). Without the anchor the
                    server's 10 m fallback applies — the same rule on both
                    sides. */}
                <input className="ga-input" type="number" min={0.5}
                  max={planW || 10}
                  step={0.5} style={{ width: 64 }} value={bo.width_m}
                  title={t('Width (m) — at most the length of the edge')}
                  onChange={(e) => {
                    const v = Number(e.target.value)
                    if (Number.isFinite(v)) {
                      write({ width_m: clamp(v, 0.5, planW || 10) })
                    }
                  }} />
                <select className="ga-input" style={{ flex: 1, minWidth: 90 }}
                  value={bo.room || ''}
                  title={t('Linked room — where the pass-through leads (feeds the future journey walk-through).')}
                  onChange={(e) => write({ room: e.target.value || undefined })}>
                  <option value="">{t('No room link')}</option>
                  {placedRooms.map((r) => (
                    <option key={r.id} value={r.id}>{r.name || r.id}</option>
                  ))}
                </select>
                <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
                  title={t('Remove')}
                  onClick={(e) => {
                    e.stopPropagation()
                    const next = (map3d?.boundary_openings || [])
                      .filter((_, j) => j !== i)
                    onMap3d('boundary_openings', next.length ? next : undefined)
                    setSelectedBoundary(null)
                  }}>✕</button>
              </div>
            )
          })}
        </div>
      ) : null}
      </div>

      <PlanSidePanel
        room={selectedRoom || null}
        ground={groundSel}
        groundName={yardName}
        groups={poseCatalog.groups}
        markerGroup={markerGroup}
        onMarkerGroup={setMarkerGroup}
        markerSel={markerSel}
        onSelectMarker={setMarkerSel}
        markerMode={clickMode === 'marker'}
        onArmMarker={() => armMode('marker')}
        onAlwaysVisible={(v) => updateLayout(selectedRoom?.id || '', {
          always_visible: v || undefined,
        })}
        onRotation={setRotation}
        onLayout={(patch) => updateLayout(selectedRoom?.id || '', patch)}
        onNoWalls={(v) => updateLayout(selectedRoom?.id || '', {
          no_walls: v || undefined,
        })}
        onFloorOffset={(v) => updateLayout(selectedRoom?.id || '', {
          floor_offset_y: v,
        })}
        surfaceKinds={surfaceKinds}
        waterKinds={waterKinds}
        onSurface={setSurface}
        mapWater={selectedMapWater}
        furnishState={furnish.status?.state || ''}
        // Furnish reads the SAVED world, not the draft (the job runs
        // server-side): a freshly drawn room that is not saved yet would
        // 409 with "no floor plan" — the same rule Generate-in-scene
        // already enforces (user finding 2026-08-20, bedroom level 1).
        furnishDisabled={!selectedRoom || unsaved}
        furnishHint={!selectedRoom
          ? t('Select a room with a floor plan first.')
          : unsaved
            ? t('Save the location first — furnishing works on the saved floor plan.')
            : groundSel
            ? t('Let the LLM furnish the yard: it picks library props and a solver places them inside the location boundary, clear of the rooms and the entrances.')
            : t('Let the LLM furnish this room: it picks library props, proposes the missing pieces and a solver places them.')}
        onFurnish={() => setFurnishOpen(true)}
        propsOpen={propsOpen}
        armedPropId={armedProp}
        onPickProp={(p) => {
          // Arming the prop tool drops any other armed mode/draft; picking
          // the armed prop again disarms.
          setClickMode('')
          setOutlineDraft([])
          setHoverSnap(null)
          setDrawTarget('')
          setArmedProp((cur) => (cur === p.id ? '' : p.id))
        }}
      />
      </div>

      {furnishOpen && selectedRoom ? (
        <FurnishDialog
          roomId={furnishTarget}
          roomName={groundSel ? yardName : (selectedRoom.name || selectedRoom.id || '')}
          job={furnish}
          propInfo={propDims}
          placements={selectedRoom.layout?.props || []}
          onClearRoom={() => {
            updateLayout(selectedRoom.id || '', { props: undefined })
            setPropSel(null)
          }}
          onAccept={acceptFurnish}
          onClose={() => setFurnishOpen(false)}
        />
      ) : null}

      {selectedRoom && propSel !== null && selectedRoom.layout?.props?.[propSel] ? (() => {
        const placement = selectedRoom.layout!.props![propSel]
        const dims = propDims[placement.prop_id]
        const patchProp = (patch: Partial<typeof placement> | null) => {
          const list = (selectedRoom.layout?.props || [])
            .map((p, idx) => (idx === propSel ? { ...p, ...patch } : p))
            .filter((_, idx) => !(patch === null && idx === propSel))
          if (patch === null) setPropSel(null)
          updateLayout(selectedRoom.id || '', { props: list.length ? list : undefined })
        }
        // Everything standing on this exact spot — the same turned-box test
        // that cycles the selection through a stack, asked at the placement's
        // own spot instead of at the cursor. Same ASCENDING-BY-INDEX order as
        // there (later placement wins ties = topmost), so `n/N` counts from
        // the bottom of the stack and N is the whole stack. The selection
        // itself always hits its own footprint, hence it is always in here.
        const stackHits = propsAtPoint(
          selectedRoom.layout || {}, selOrigin,
          placement.at[0] - selOrigin[0], placement.at[1] - selOrigin[1],
        )
        // Which OTHER placements this one stands over. It decides only
        // whether the button is offered; the height comes from the server.
        const stackSupports = stackHits.filter((i) => i !== propSel)
        const placeOnTop = async () => {
          try {
            const res = await apiPost<{ offset_y?: number | null }>(
              '/world/props/stack-y',
              { props: selectedRoom.layout?.props || [], index: propSel })
            if (res?.offset_y === null || res?.offset_y === undefined) {
              toast(t('Nothing underneath: move the prop over another one first.'),
                    'error')
              return
            }
            patchProp({ offset_y: res.offset_y || undefined })
          } catch (e) {
            toast(t('Error') + ': ' + (e as Error).message, 'error')
          }
        }
        return (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ fontWeight: 600 }}>
              🪑 {dims?.name || placement.prop_id}:
            </span>
            {/* What the LLM calls this place — names the placement's markers
                in chips and prompts ("armchair by the window"). ≤ 60 chars,
                the server trims the rest. */}
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('A name for this placement as a PLACE — the LLM and the marker chips call it that. Empty = the prop’s own name.')}>
              {t('Label')}
              <input
                type="text"
                className="ga-input"
                maxLength={60}
                style={{ width: 200 }}
                value={placement.label || ''}
                placeholder={t('e.g. armchair by the window — what the LLM calls this place')}
                onChange={(e) => patchProp({ label: e.target.value.slice(0, 60) || undefined })}
              />
            </label>
            {/* A stack is invisible on the plan — the top footprint covers the
                rest. This says how deep the selection sits and that there is
                anything else here at all, so the cycling click is
                discoverable instead of a secret. */}
            {stackHits.length > 1 ? (
              <span
                className="ga-hint"
                title={t('Click the same spot again to select the next prop in this stack.')}
                style={{ border: '1px solid #444c56', borderRadius: 10,
                         padding: '1px 7px', cursor: 'help' }}
              >
                {t('{n}/{N} here')
                  .replace('{n}', String(stackHits.indexOf(propSel) + 1))
                  .replace('{N}', String(stackHits.length))}
              </span>
            ) : null}
            {/* Position in METRES from the shape's min corner (v6 Nr. 2), so
                the slider runs over its own box and the readback is a length
                one can measure against the 1.70 m figure on the plan. On the
                YARD the very same field is location-local metres (§ A13a), so
                the range starts at the boundary box's corner instead of 0. */}
            <SliderInput
              label="X"
              ariaLabel={t('Prop position X (m)')}
              title={groundSel
                ? t('Fine-tune the position: metres east of the anchor pin (negative = west).')
                : t('Fine-tune the position: metres from the room’s west edge.')}
              min={selOrigin[0]}
              max={selOrigin[0] + (selLay?.w || 0)}
              step={0.01}
              value={placement.at[0]}
              onChange={(v) => patchProp({
                at: [rM(v), placement.at[1]] as [number, number],
              })}
              unit="m"
              sliderWidth={100}
              readback={<span style={{ minWidth: 52 }}>{fmtM(placement.at[0])} m</span>}
            />
            <SliderInput
              label="Y"
              ariaLabel={t('Prop position Y (m)')}
              title={groundSel
                ? t('Fine-tune the position: metres south of the anchor pin (negative = north).')
                : t('Fine-tune the position: metres from the room’s north edge.')}
              min={selOrigin[1]}
              max={selOrigin[1] + (selLay?.d || 0)}
              step={0.01}
              value={placement.at[1]}
              onChange={(v) => patchProp({
                at: [placement.at[0], rM(v)] as [number, number],
              })}
              unit="m"
              sliderWidth={100}
              readback={<span style={{ minWidth: 52 }}>{fmtM(placement.at[1])} m</span>}
            />
            <SliderInput
              label="↻"
              ariaLabel={t('Prop yaw (°)')}
              title={t('Yaw in degrees — free values; R while placing steps 90°.')}
              min={0}
              max={359.5}
              step={0.5}
              fineStep={0.1}
              value={placement.yaw || 0}
              onChange={(v) => patchProp({ yaw: v || undefined })}
              unit="°"
              sliderWidth={120}
              inputWidth={68}
            />
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Vertical offset in metres, additive to the floor (e.g. a picture on the wall).')}>
              ↕ m
              <input
                type="number" min={-5} max={5} step={0.05}
                value={placement.offset_y ?? 0}
                onChange={(e) => {
                  const v = Math.round((parseFloat(e.target.value) || 0) * 1000) / 1000
                  patchProp({ offset_y: v || undefined })
                }}
                style={{ width: 70 }}
                className="ga-input"
              />
            </label>
            {/* Set it down ON the piece it stands over — the teapot onto the
                table. The button is OFFERED by the same footprint test that
                picks a prop out of a stack here (`propsAtPoint`); the height
                itself is the SERVER's answer (`POST /world/props/stack-y`,
                `props.stack_offset_y`), so the plan, the preview and the 3D
                client cannot each arrive at their own surface. */}
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={!stackSupports.length}
              title={stackSupports.length
                ? t('Set this prop down on the top surface of the prop underneath it (the topmost one, if several).')
                : t('Nothing underneath: move the prop over another one first.')}
              onClick={() => { void placeOnTop() }}
            >
              ⬒ {t('Place on top')}
            </button>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={!placement.offset_y}
              title={t('Back down onto the floor — clears the vertical offset.')}
              onClick={() => patchProp({ offset_y: undefined })}
            >
              ⬓ {t('Place on floor')}
            </button>
            {/* DEPTH CUT (§ B2 addendum 2026-08-23): how much of the prop's
                depth survives — half a table against a wall is this table
                with a plane through it, not a second library entry. 100 % =
                uncut and the placement stores no key at all. The plane is the
                SERVER's (`cut_plane` on the scene spec); this dial only says
                how much and from which side. */}
            <SliderInput
              label="✂"
              ariaLabel={t('Depth cut (%)')}
              title={t('Cut the prop across its depth: how many percent of it remain. 100 = whole prop. The cut face stays open, so put it against a wall.')}
              min={5}
              max={100}
              step={5}
              value={Math.round((placement.cut_keep ?? 1) * 100)}
              onChange={(v) => patchProp({
                cut_keep: v >= 100 ? undefined : Math.round(v) / 100,
                cut_side: v >= 100 ? undefined
                  : (placement.cut_side || 'back'),
              })}
              unit="%"
              sliderWidth={100}
              inputWidth={62}
            />
            {placement.cut_keep && placement.cut_keep < 1 ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                title={t('Which half remains: “front” is the top of the footprint on the plan, “back” the bottom — turned with the prop’s yaw.')}
                onClick={() => patchProp({
                  cut_side: placement.cut_side === 'front' ? 'back' : 'front',
                })}
              >
                {placement.cut_side === 'front' ? t('Keep front') : t('Keep back')}
              </button>
            ) : null}
            {/* Scatter (v5.2 Nr. 12): a placement property — this anchor
                throws `scatter_count` copies over the room from its own
                seed; spacing alone rules the density (0 = may overlap). */}
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={groundSel
                ? t('Scatter: throw copies of THIS prop over the yard. The placement stays as the anchor; positions come from the seed and stay inside the location boundary — the rooms, the entrances and the markers stay clear.')
                : t('Scatter: throw copies of THIS prop over the room area. The placement stays as the anchor; positions come from the seed — the road, openings and markers stay clear.')}>
              <input
                type="checkbox"
                checked={!!placement.scatter_count}
                onChange={(e) => patchProp(e.target.checked
                  ? { scatter_count: 10,
                      scatter_seed: crypto.getRandomValues(new Uint32Array(1))[0] }
                  : { scatter_count: undefined, scatter_seed: undefined,
                      scatter_spacing_m: undefined })}
              />
              <span>{t('Scatter')}</span>
            </label>
            {placement.scatter_count ? (
              <>
                <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
                  title={t('Number of scattered copies (Σ 120 per room; the anchor is extra).')}>
                  n
                  <input
                    type="number" min={1} max={120} step={1}
                    value={placement.scatter_count}
                    onChange={(e) => {
                      const v = Math.round(parseFloat(e.target.value) || 0)
                      if (v >= 1) patchProp({ scatter_count: Math.min(120, v) })
                    }}
                    style={{ width: 62 }}
                    className="ga-input"
                  />
                </label>
                <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
                  title={t('Minimum centre distance between the copies in metres — the whole density rule. 0 = they may overlap (a forest’s crowns do).')}>
                  ↔ m
                  <input
                    type="number" min={0} max={5} step={0.1}
                    value={placement.scatter_spacing_m ?? 0}
                    onChange={(e) => {
                      const v = Math.round((parseFloat(e.target.value) || 0) * 100) / 100
                      patchProp({ scatter_spacing_m: v > 0 ? Math.min(5, v) : undefined })
                    }}
                    style={{ width: 62 }}
                    className="ga-input"
                  />
                </label>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  title={t('Reroll — a new seed gives a new arrangement.')}
                  onClick={() => patchProp({
                    scatter_seed: crypto.getRandomValues(new Uint32Array(1))[0] })}
                >
                  🎲
                </button>
              </>
            ) : null}
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              onClick={() => patchProp(null)}
            >
              × {t('Remove')}
            </button>
            {/* Which model variant THIS placement shows — a dial like the
                others beside it, so it belongs in the same strip. */}
            <PropVariantPicker
              propId={placement.prop_id}
              variant={placement.variant}
              onVariant={(v) => patchProp({ variant: v })}
            />
          </div>
        )
      })() : null}

      {/* Model calibration strip (rotation fix, room width, walkable floor)
          — placed BEFORE the model-placement strip so the three calibration
          anchors read in order: width_m → walk_y → model_offset_y. */}
      {children}

      {/* Model-placement strip: X/Y sliders + height for the selected
          room's diorama model — mirrors the prop strip; ↺ recentres. */}
      {selectedRoom && !groundSel && hasRect(selectedRoom.layout)
        && modelDims[selectedRoom.id || ''] ? (() => {
        const lay = selectedRoom.layout
        // Absent = centred, which in metres is (w/2, d/2).
        const mAt = lay.model_at || [lay.w / 2, lay.d / 2]
        const setAt = (axis: 0 | 1, v: number) => {
          const next: [number, number] = [mAt[0], mAt[1]]
          next[axis] = rM(clamp(v, 0, axis === 0 ? lay.w : lay.d))
          updateLayout(selectedRoom.id || '', { model_at: next })
        }
        return (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ fontWeight: 600 }}>
              ⌂ {t('Model placement')}:
            </span>
            {(['X', 'Y'] as const).map((label, axis) => (
              <SliderInput
                key={label}
                label={label}
                ariaLabel={t('Room model anchor')}
                title={t('Anchor of the room model: metres from the room’s min corner.')}
                min={0}
                max={axis === 0 ? lay.w : lay.d}
                step={0.01}
                value={mAt[axis]}
                onChange={(v) => setAt(axis as 0 | 1, v)}
                unit="m"
                sliderWidth={110}
                style={{ gap: 4 }}
              />
            ))}
            <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Height offset of the MODEL in real metres, relative to the room floor — negative sinks it.')}>
              {t('Model height (m)')}
              <input className="ga-input" type="number" step={0.05}
                style={{ width: 78 }}
                value={lay.model_offset_y ?? 0}
                onChange={(e) => {
                  const v = Number(e.target.value)
                  updateLayout(selectedRoom.id || '', {
                    model_offset_y: Number.isFinite(v) && v !== 0 ? v : undefined,
                  })
                }} />
            </label>
            {/* Shell clip (§ B1): a real-size diorama may be bigger than its
                floor plan — with this on, the renderer cuts it at the room
                hull. An outdoor room has no hull, so the server ignores it. */}
            {!lay.always_visible ? (
              <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
                title={t('Cut the model at the room hull: everything sticking out over the floor plan is hidden (the drawn polygon counts, not just the rectangle). Looking into a cut edge shows the room’s inside — there is no cap surface.')}>
                <input type="checkbox"
                  checked={!!lay.clip_model}
                  onChange={(e) => updateLayout(selectedRoom.id || '', {
                    clip_model: e.target.checked ? true : undefined,
                  })} />
                {t('Clip model to room bounds')}
              </label>
            ) : null}
            {/* "Render walls" used to stand here and was therefore invisible
                until a room HAD a diorama — a wall-less zone is exactly a room
                that has none (E5 inventory 1a). It lives in the side panel
                now, with the room's other shell properties. */}
            <button type="button" className="ga-btn ga-btn-sm"
              title={t('Back to the centred default placement.')}
              onClick={() => updateLayout(selectedRoom.id || '', {
                model_at: undefined, model_offset_y: undefined,
              })}>
              ↺
            </button>
          </div>
        )
      })() : null}

      {selectedRoom && markerSel !== null && selectedRoom.layout?.markers?.[markerSel] ? (() => {
        const marker = selectedRoom.layout!.markers![markerSel]
        const patchMarker = (patch: Partial<typeof marker> | null) => {
          const markers = (selectedRoom.layout?.markers || [])
            .map((m, idx) => (idx === markerSel ? { ...m, ...patch } : m))
            .filter((_, idx) => !(patch === null && idx === markerSel))
          if (patch === null) setMarkerSel(null)
          updateLayout(selectedRoom.id || '', { markers })
        }
        // Facing per contract: 0 = south, 90 = east, 180 = north, 270 = west;
        // unset = the client's face-the-neighbours default.
        const FACING: Record<number, string> = { 0: 'S', 90: 'E', 180: 'N', 270: 'W' }
        const fac = marker.rotation
        const capacity = marker.capacity || 1
        // Preview cycler: the poses of the marker's place type, default
        // first. VIEW state only, keyed by marker id — a marker stored before
        // ids existed gets one minted into the draft on the first click, so
        // the preview (which reads the payload's id) can find it.
        const poses = posesInGroup(poseCatalog, marker.group)
        const poseIdx = Math.max(0, poses.indexOf(
          (marker.id && previewPose[marker.id]) || poses[0]))
        const setPreview = (pose: string) => {
          const id = marker.id || newId()
          if (!marker.id) patchMarker({ id })
          onPreviewPose?.(id, pose)
        }
        return (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ fontWeight: 600 }}>
              🎯 {markerSel + 1} · {groupLabel(poseCatalog.groups, marker.group)}
              {capacity > 1 ? ` ×${capacity}` : ''}:
            </span>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'marker-move' ? ' ga-btn-primary' : ''}`}
              onClick={() => setClickMode((m) => (m === 'marker-move' ? '' : 'marker-move'))}
              title={t('Then click inside the room to move this marker there.')}
            >
              ✥ {clickMode === 'marker-move' ? t('Click into the room…') : t('Move')}
            </button>
            {/* Fine X/Y correction after the coarse mouse placement — METRES
                from the room's min corner (v6 Nr. 2). */}
            <SliderInput
              label="X"
              ariaLabel={t('Marker position X (m)')}
              title={groundSel
                ? t('Fine-tune the marker position: metres east of the anchor pin (negative = west).')
                : t('Fine-tune the marker position: metres from the room’s west edge.')}
              min={selOrigin[0]}
              max={selOrigin[0] + (selLay?.w || 0)}
              step={0.01}
              value={marker.at[0]}
              onChange={(v) => patchMarker({
                at: [rM(v), marker.at[1]] as [number, number],
              })}
              unit="m"
              sliderWidth={100}
              inputWidth={74}
            />
            <SliderInput
              label="Y"
              ariaLabel={t('Marker position Y (m)')}
              title={groundSel
                ? t('Fine-tune the marker position: metres south of the anchor pin (negative = north).')
                : t('Fine-tune the marker position: metres from the room’s north edge.')}
              min={selOrigin[1]}
              max={selOrigin[1] + (selLay?.d || 0)}
              step={0.01}
              value={marker.at[1]}
              onChange={(v) => patchMarker({
                at: [marker.at[0], rM(v)] as [number, number],
              })}
              unit="m"
              sliderWidth={100}
              inputWidth={74}
            />
            <SliderInput
              label="🧭"
              ariaLabel={t('Marker facing (°)')}
              title={t('Facing of the figure (0 south, 90 east, 180 north, 270 west; — = face the neighbours).')}
              min={0}
              max={359}
              step={1}
              value={fac}
              fallback={0}
              clearable
              placeholder="—"
              onChange={(v) => patchMarker({ rotation: v })}
              onClear={() => patchMarker({ rotation: undefined })}
              sliderWidth={120}
              inputWidth={62}
              readback={(
                <span style={{ minWidth: 34 }}>
                  {fac !== undefined && FACING[fac] ? FACING[fac] : ''}
                </span>
              )}
            >
              {fac !== undefined ? (
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  onClick={() => patchMarker({ rotation: undefined })}
                  title={t('Back to default: face the neighbours.')}
                >
                  ↺
                </button>
              ) : null}
            </SliderInput>
            {/* A place with room for several: the SERVER composes `capacity`
                slots `spacing_m` apart across the facing (payload
                `markers[].slots`); the plan shows one dot, the preview one
                figure per slot. */}
            <SliderInput
              label={t('Capacity')}
              ariaLabel={t('Marker capacity (figures)')}
              title={t('How many figures this place takes — a bench seats several. The slots line up across the facing.')}
              min={1}
              max={8}
              step={1}
              value={capacity}
              onChange={(v) => {
                const cap = Math.max(1, Math.min(8, Math.round(v)))
                patchMarker(cap > 1
                  ? { capacity: cap }
                  : { capacity: undefined, spacing_m: undefined })
              }}
              sliderWidth={80}
              inputWidth={52}
            />
            {capacity > 1 ? (
              <SliderInput
                label={t('Spacing')}
                ariaLabel={t('Marker slot spacing (m)')}
                title={t('Distance between neighbouring slots in metres (0.6 = a bench seat).')}
                min={0.2}
                max={3}
                step={0.05}
                value={marker.spacing_m ?? 0.6}
                onChange={(v) => patchMarker({ spacing_m: rM(v) })}
                unit="m"
                sliderWidth={90}
                inputWidth={62}
              />
            ) : null}
            {poses.length ? (
              <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}
                title={t('Which pose of this place type the preview figures play — view only, nothing is stored. Every slot shows it; a pair pose seats both halves around the marker.')}>
                <span className="ga-hint">{t('Preview pose')}</span>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={() => setPreview(poses[(poseIdx + poses.length - 1) % poses.length])}>
                  ◀
                </button>
                <span className="ga-hint">{poses[poseIdx]} ({poseIdx + 1}/{poses.length})</span>
                <button type="button" className="ga-btn ga-btn-sm"
                  onClick={() => setPreview(poses[(poseIdx + 1) % poses.length])}>
                  ▶
                </button>
              </span>
            ) : null}
            <SliderInput
              label={t('Height offset (m)')}
              ariaLabel={t('Marker height offset (m)')}
              title={t('Additive to the seat height the client samples under the marker.')}
              min={-1}
              max={1}
              step={0.01}
              value={marker.offset_y ?? 0}
              onChange={(v) => patchMarker({ offset_y: v === 0 ? undefined : v })}
              sliderWidth={120}
              inputWidth={74}
            />
            {/* Lean axes: a figure on a slope is not upright, and the compass
                alone cannot say that. Applied after the facing, in the
                figure's own frame. */}
            {([['tilt', '⤢', t('Tilt (°): head up (+) or down (−) — for lying or leaning figures.')],
              ['roll', '⤡', t('Roll (°): lean sideways — right (+) or left (−).')]] as const)
              .map(([key, icon, hint]) => (
                <SliderInput
                  key={key}
                  label={icon}
                  ariaLabel={hint}
                  title={hint}
                  min={-90}
                  max={90}
                  step={1}
                  value={marker[key] ?? 0}
                  onChange={(v) => patchMarker({ [key]: v === 0 ? undefined : v })}
                  unit="°"
                  sliderWidth={100}
                  inputWidth={62}
                />
              ))}
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => patchMarker(null)}
              title={t('Remove this marker')}
            >
              × {t('Remove')}
            </button>
          </div>
        )
      })() : null}

      {selectedRoom && openingSel !== null && selectedRoom.layout?.openings?.[openingSel] ? (() => {
        const op = selectedRoom.layout!.openings![openingSel]
        const patchOpening = (patch: Partial<RoomOpening> | null) => {
          const list = (selectedRoom.layout?.openings || [])
            .map((o, idx) => (idx === openingSel ? { ...o, ...patch } : o))
            .filter((_, idx) => !(patch === null && idx === openingSel))
          if (patch === null) setOpeningSel(null)
          updateLayout(selectedRoom.id || '', { openings: list })
        }
        const numField = (
          field: 'width_m' | 'height_m' | 'sill_m', label: string, max: number,
        ) => (
          <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}>
            {label}
            <input
              key={`${field}-${op[field]}`}
              className="ga-input"
              type="number"
              min={field === 'sill_m' ? 0 : 0.4}
              max={max}
              step={0.1}
              style={{ width: 64 }}
              defaultValue={op[field]}
              onBlur={(e) => {
                const n = parseFloat(e.target.value)
                if (Number.isFinite(n) && n !== op[field]) patchOpening({ [field]: Math.round(n * 1000) / 1000 })
              }}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            />
          </label>
        )
        // Connectivity target: another room (same building) or 'outside'.
        const otherRooms = rooms.filter((r) => r.id && r.id !== selectedRoom.id)
        return (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ fontWeight: 600 }}>
              🚪 {typeof op.edge === 'string' ? op.edge : `#${op.edge}`} · {op.type}:
            </span>
            <select
              className="ga-input"
              style={{ width: 110 }}
              value={op.type}
              onChange={(e) => patchOpening({ type: e.target.value as RoomOpening['type'] })}
              title={t('Door, window or open passage.')}
            >
              <option value="door">{t('Door')}</option>
              <option value="window">{t('Window')}</option>
              <option value="passage">{t('Passage')}</option>
            </select>
            {numField('width_m', t('W (m)'), 10)}
            {numField('height_m', t('H (m)'), 10)}
            {numField('sill_m', t('Sill (m)'), 3)}
            <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Where a door/passage leads — another room or outside. Windows leave it empty.')}>
              {t('to')}
              <select
                className="ga-input"
                style={{ width: 130 }}
                value={op.to ?? ''}
                onChange={(e) => patchOpening({ to: e.target.value || undefined })}
              >
                <option value="">{t('— none —')}</option>
                <option value="outside">{t('outside')}</option>
                {otherRooms.map((r) => (
                  <option key={r.id} value={r.id}>{r.name || r.id}</option>
                ))}
              </select>
            </label>
            {/* WHICH DOOR hangs in this hole. Only a door has one — a window
                takes no prop and a passage is the open gap by definition
                (`scene_recipe.door_prop_id`). Keyed on the selection so the
                control's "Custom, nothing picked yet" state never travels to
                the next opening. */}
            {op.type === 'door' ? (
              <OpeningDoorProp
                key={openingSel}
                opening={op}
                defaultPropId={defaultDoorPropId}
                onPatch={patchOpening}
              />
            ) : null}
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => patchOpening(null)}
              title={t('Remove this opening')}
            >
              × {t('Remove')}
            </button>
          </div>
        )
      })() : null}

      {elevatorSel && map3d?.elevator ? (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ga-hint" style={{ fontWeight: 600 }}>🛗 {t('Elevator')}:</span>
          <button
            type="button"
            className={`ga-btn ga-btn-sm${clickMode === 'elevator' ? ' ga-btn-primary' : ''}`}
            onClick={() => setClickMode((m) => (m === 'elevator' ? '' : 'elevator'))}
            title={t('Then click on the plan to move the elevator there.')}
          >
            ✥ {clickMode === 'elevator' ? t('Click on the plan…') : t('Move')}
          </button>
          {/* Metres from the anchor pin (v6 Nr. 2) — the same frame the
              boundary is drawn in, so the sliders sweep the whole window. */}
          <SliderInput
            label="X"
            ariaLabel={t('Elevator position X (m)')}
            title={t('Fine-tune the elevator position: metres east of the anchor pin (negative = west).')}
            min={view.x0}
            max={view.x0 + view.size}
            step={0.05}
            fineStep={0.01}
            value={map3d.elevator[0]}
            onChange={(v) => onMap3d?.('elevator',
              [rM(v), map3d.elevator![1]] as [number, number])}
            unit="m"
            sliderWidth={100}
            readback={<span style={{ minWidth: 56 }}>{fmtM(map3d.elevator[0])} m</span>}
          />
          <SliderInput
            label="Y"
            ariaLabel={t('Elevator position Y (m)')}
            title={t('Fine-tune the elevator position: metres south of the anchor pin (negative = north).')}
            min={view.z0}
            max={view.z0 + view.size}
            step={0.05}
            fineStep={0.01}
            value={map3d.elevator[1]}
            onChange={(v) => onMap3d?.('elevator',
              [map3d.elevator![0], rM(v)] as [number, number])}
            unit="m"
            sliderWidth={100}
            readback={<span style={{ minWidth: 56 }}>{fmtM(map3d.elevator[1])} m</span>}
          />

        </div>
      ) : null}

      {/* THE SELECTED FLIGHT. A staircase has exactly three things one does to
          it: turn it, move its foot, take it away — and the two numbers that
          decide whether it fits (its steps and the floor it eats) are stated
          rather than left to be measured on the plan. */}
      {/* THE FLIGHT AND THE STOREY BELONG TOGETHER. Every path that changes
          the level clears the selection (they all run through `setSelected`),
          and picking a flight pulls the plan to its own storey — so this
          guard has nothing to hide today. It is the invariant written down:
          the row never states the steps and the run of a flight the plan above
          it is not showing. */}
      {stairSel !== null && map3d?.stairs?.[stairSel]
        && map3d.stairs[stairSel].from_level === level ? (() => {
        const st = map3d.stairs![stairSel]
        const list = map3d.stairs || []
        // The two numbers that decide whether a flight fits are the SERVER's
        // (§ B1 `stairs`), not a formula repeated here. Absent = the scene
        // preview has not answered for this draft yet.
        const flight = sceneStairs.get(stairSel)
        const patch = (next: typeof st | null) => {
          const rest = list.filter((_, i) => i !== stairSel)
          if (!next) {
            onMap3d?.('stairs', rest.length ? rest : undefined)
            setStairSel(null)
            return
          }
          onMap3d?.('stairs', list.map((s, i) => (i === stairSel ? next : s)))
        }
        return (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ fontWeight: 600 }}>
              🪜 {t('Staircase')} {stairSel + 1}:
            </span>
            <span className="ga-hint">
              {(flight
                ? t('Level {a} → {b} · {n} steps · {run} m of floor · {deg}°')
                  .replace('{n}', String(flight.steps))
                  .replace('{run}', fmtM(flight.run_m))
                : t('Level {a} → {b} · {deg}° · measuring the flight…'))
                .replace('{a}', String(st.from_level))
                .replace('{b}', String(st.from_level + 1))
                .replace('{deg}', String(st.dir_deg))}
            </span>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              onClick={() => patch({ ...st, dir_deg: (st.dir_deg + 90) % 360 })}
              title={t('Turn the climb direction by a quarter — 0° climbs south (+y), 90° east (+x), 180° north (−y), 270° west (−x). The foot stays where it is.')}
            >
              ↻ {t('Rotate 90°')}
            </button>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'stairs' ? ' ga-btn-primary' : ''}`}
              onClick={() => setClickMode((m) => (m === 'stairs' ? '' : 'stairs'))}
              title={t('Then click on the plan to place ANOTHER flight on this level.')}
            >
              + {clickMode === 'stairs' ? t('Click on the plan…') : t('Add')}
            </button>
            {/* Metres from the anchor pin, the frame the whole plan is drawn
                in — the foot is what the flight is anchored by. */}
            <SliderInput
              label="X"
              ariaLabel={t('Staircase foot X (m)')}
              title={t('Fine-tune the foot of the flight: metres east of the anchor pin (negative = west).')}
              min={view.x0}
              max={view.x0 + view.size}
              step={0.05}
              fineStep={0.01}
              value={st.at[0]}
              onChange={(v) => patch({ ...st, at: [rM(v), st.at[1]] })}
              unit="m"
              sliderWidth={100}
              readback={<span style={{ minWidth: 56 }}>{fmtM(st.at[0])} m</span>}
            />
            <SliderInput
              label="Y"
              ariaLabel={t('Staircase foot Y (m)')}
              title={t('Fine-tune the foot of the flight: metres south of the anchor pin (negative = north).')}
              min={view.z0}
              max={view.z0 + view.size}
              step={0.05}
              fineStep={0.01}
              value={st.at[1]}
              onChange={(v) => patch({ ...st, at: [st.at[0], rM(v)] })}
              unit="m"
              sliderWidth={100}
              readback={<span style={{ minWidth: 56 }}>{fmtM(st.at[1])} m</span>}
            />
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => patch(null)}
              title={t('Remove this staircase — the storeys it connected fall back to the elevator, if there is one.')}
            >
              × {t('Remove')}
            </button>
          </div>
        )
      })() : null}

      {/* Pick a room WITHOUT touching the plan — small, overlapping or
          stacked rooms are hard to hit, and hitting them used to move them.
          THE YARD IS ALWAYS FIRST (§ A13a): it is the one shape nobody draws,
          it lies under everything else and it is the hardest thing on the plan
          to hit on purpose. */}
      {placedRooms.length || groundRoom ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ga-hint">{t('On the plan:')}</span>
          {groundRoom ? (
            <button
              type="button"
              className={`ga-btn ga-btn-sm${selected === GROUND_ROOM_ID ? ' ga-btn-primary' : ''}`}
              disabled={!yardLay}
              onClick={() => { setLevel(0); setSelected(GROUND_ROOM_ID) }}
              title={yardLay
                ? t('Select the yard — the location surface. Props, scattered props and markers stand on the terrain here; it has no room geometry.')
                : t('No boundary drawn: this location has no area, so it has no yard to furnish either. Draw its footprint on the map tab first.')}
            >
              ⬚ {yardName}
            </button>
          ) : null}
          {placedRooms.map((room) => (
            <button
              key={room.id || room.name}
              type="button"
              className={`ga-btn ga-btn-sm${selected === room.id ? ' ga-btn-primary' : ''}`}
              onClick={() => setSelected(room.id || '')}
              title={t('Select this room — nothing on the plan moves.')}
            >
              {(room.layout?.level || 0) !== 0
                ? `${room.name || room.id} · ${room.layout?.level}`
                : (room.name || room.id)}
            </button>
          ))}
        </div>
      ) : null}

      {unplaced.length ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ga-hint">{t('Not on the plan:')}</span>
          {unplaced.map((room) => (
            <button
              key={room.id || room.name}
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'draw-room' && drawTarget === room.id ? ' ga-btn-primary' : ''}`}
              onClick={() => armDrawFor(room.id || '')}
              title={t('Draw this room on the current level — click to place points, click the first point to close, Shift = free-hand, Esc = cancel.')}
            >
              ⬠ {room.name || room.id}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
