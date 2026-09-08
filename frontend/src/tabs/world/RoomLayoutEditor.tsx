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
import { apiGet } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import {
  CLOSE_TOL_PX, MIN_ROOM_M, MIN_WINDOW_EDGE_M, OPENING_DEFAULT,
  PLAN_MAX_M, SNAP_TOL_PX, absOutline, buildSnapTargets, clamp,
  edgePointOnEdge, edgeSegment, exteriorEdges, localToRoom,
  atOrigin, levelOutline, nearestPolygonEdge, normalizeOpeningEdge,
  outlineOf,
  outlineSourceLevel, r4, rM,
  rotateAbout, storedAt,
  sharedEdges, snapDrawPoint, snapMoveOffset, snapToGrid,
  stairSymbol, viewFx, viewFz,
  viewMx, viewMz, viewportFor,
} from './planGeometry'
import type { PlanView, PolyRoom, Pt, SnapResult } from './planGeometry'
import {
  BOUNDARY_SEED_M, boundaryComplaint, putLocationBoundary, seedSquare,
} from './boundaryApi'
import { FurnishDialog, useFurnishJob } from './FurnishDialog'
import { NEED_ID_PREFIX } from './furnishTypes'
import { PlanInspector, type InspectorTab } from './PlanInspector'
import { PlanInspectorLevel } from './PlanInspectorLevel'
import { PlanFindings } from './PlanFindings'
import { PlanElevatorStrip } from './PlanElevatorStrip'
import { PlanRoomPicker } from './PlanRoomPicker'
import { PlanStairStrip } from './PlanStairStrip'
import { PlanOpeningStrip } from './PlanOpeningStrip'
import { PlanMarkerStrip } from './PlanMarkerStrip'
import { PlanModelPlacement } from './PlanModelPlacement'
import { PlanPropStrip } from './PlanPropStrip'
import { planLog } from './planDebug'
import { PlanCanvas } from './PlanCanvas'
import type { PlanPick, PlanShape, PropDims } from './PlanCanvas'
import { PlanScaleBar } from './PlanMeasure'
import { PlanSidePanel } from './PlanSidePanel'
import { PlanToolbar } from './PlanToolbar'
import type { PlanMode } from './PlanToolbar'
import { getRoomModelDims, renderTopDownSnapshot } from './topDownSnapshot'
import type { SurfaceMaterialSpec } from '@anima/scene-render'
import type { Map3D, PlacedLayout, Room, RoomLayout, RoomOpening, RoomPropPlacement, SceneProblem, SceneRoom, ScenePayload, SceneStairs, SurfaceKind } from './worldTypes'
import { GROUND_ROOM_ID, groundRoomLabel, hasRect, readMapWater } from './worldTypes'
import { groupKeys, newId, usePoseCatalog } from './placeTypes'
import { composePlacements, dependentIndices, pickSupport, toSupportFrame, withPropHeights } from './placementCompose'
import { pointInPolygon } from '../map/mapMath'
import { isWaterKind } from '../map/mapTypes'
import type { TerrainTypesResp } from '../map/mapTypes'

/** Narrowest the 2D plan is ever drawn, in px. SINCE THE WORKBENCH REBUILD
 *  (plan-grundriss-werkbank.md § W1) A FLOOR, NOT THE WIDTH: the canvas takes
 *  whatever the plan column gives it, clamped into [CANVAS_MIN_W, CANVAS_MAX_W],
 *  because a plan pinned at 420 px could never use a wide screen. */
const CANVAS_MIN_W = 420
/** Widest the plan grows on its own. Past this a bigger screen buys detail
 *  nobody asked for and the inspector beside it starts to look lost; the zoom
 *  is the way past it. */
const CANVAS_MAX_W = 1000
/** Width kept free for the scroll viewport's vertical scrollbar when the plan
 *  column is measured — a fixed allowance on purpose, see the observer. */
const SCROLLBAR_PX = 16
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
  /** The location's `default_door_prop_id`. The opening panel names the door
   *  an opening inherits when it chooses nothing, and the inspector's Storey
   *  tab edits it — it is a setting OF this plan, and it used to stand as a
   *  lone full-width row above the whole editor. */
  defaultDoorPropId?: string
  /** Absent = the field is read-only here (the tab did not hand a writer). */
  onDefaultDoorProp?: (id: string) => void
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

const NO_PREVIEW_POSES: Record<string, string> = {}

export function RoomLayoutEditor({ rooms, onChange, locationId = '', map3d, onMap3d, placedOnMap = true, hasEntrance, onSelectRoom, scene = null, calibrationRoomId = '', onCalibrationAt, previewPose = NO_PREVIEW_POSES, onPreviewPose, unsaved = false, defaultDoorPropId = '', onDefaultDoorProp, children }: RoomLayoutEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [level, setLevel] = useState(0)
  // WHICH storey a running footprint draft belongs to (§ G). Recorded when the
  // 🏗 tool is armed, not read when it commits: switching storeys mid-draw
  // must not land the points on a floor nobody drew them on.
  const [outlineLevel, setOutlineLevel] = useState(0)
  const outlineLevelRef = useRef(outlineLevel)
  outlineLevelRef.current = outlineLevel
  // Which pane the inspector dock shows, and whether it is folded away. VIEW
  // state, so it is remembered per browser and never travels with the world.
  const [inspTab, setInspTab] = useState<InspectorTab>('selection')
  const [inspCollapsed, setInspCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('av.floorplan.inspectorOff') === '1'
    } catch { return false }
  })
  const setInspCollapsedStored = useCallback((v: boolean) => {
    setInspCollapsed(v)
    try {
      window.localStorage.setItem('av.floorplan.inspectorOff', v ? '1' : '0')
    } catch { /* storage off — the dock simply starts open next time. */ }
  }, [])
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
  // WHICH MODEL VARIANT the armed prop is dropped as (undefined = the primary
  // one). It belongs to the ARMING, not to a placement: the same prop may be
  // set down as v2 here and as the primary one two clicks later, and picking
  // a different card is a new statement — so it resets with the pick.
  const [armedVariant, setArmedVariant] = useState<number | undefined>(undefined)
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
  /** A ghost delete waiting for confirmation, because pieces stand on it. */
  const [ghostDrop, setGhostDrop] =
    useState<{ index: number; dependents: number } | null>(null)
  // The key handler is bound once; the selection it acts on must be the
  // current one, not the one that existed when it was bound.
  const ghostSelRef = useRef<number | null>(null)
  ghostSelRef.current = ghostSel

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
  // …PLUS the pieces that do not exist yet. A ghost of an unbuilt need carries
  // the temporary `need:<key>` prop id, which no library record answers — so
  // without this the review drew every piece still to be made as an unnamed
  // 1×1 m box, and seeing the room BEFORE it is built is the whole point of
  // the review (E6). The need's own size and kind stand in until the prop is
  // real. ONE map for every dims lookup on the plan: placed props are
  // untouched (their ids are real and win by being in `propDims`).
  const ghostDims = useMemo<Record<string, PropDims>>(() => {
    const needs = furnish.status?.proposal?.needs || []
    if (!needs.length) return propDims
    const map: Record<string, PropDims> = { ...propDims }
    for (const n of needs) {
      const id = `${NEED_ID_PREFIX}${n.key || ''}`
      if (!n.key || map[id]) continue
      map[id] = { name: n.kind || id, width_m: n.width_m,
                  depth_m: n.depth_m, height_m: n.height_m }
    }
    return map
  }, [propDims, furnish.status])
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
  // What the canvas edge REALLY is in px (`baseW * planZoom`, or less when a
  // narrow pane clips it). The scale bar and the grid step are stated in
  // PIXELS, so they measure the edge instead of assuming it.
  const [canvasPx, setCanvasPx] = useState(CANVAS_MIN_W)
  // The callbacks below convert pixels to metres and run outside React's
  // render, so they read the measurement by ref — a stale `canvasPx` would
  // mis-scale a drag by exactly the amount the pane last changed.
  const canvasPxRef = useRef(canvasPx)
  canvasPxRef.current = canvasPx
  // BASE width at zoom 1: what the plan column offers, clamped. The canvas is
  // `baseW * planZoom`; before the workbench rebuild this was a constant and
  // the plan could not use a wide pane, however much room the screen had.
  const [baseW, setBaseW] = useState(CANVAS_MIN_W)
  const baseWRef = useRef(baseW)
  baseWRef.current = baseW
  const canvasRef = useRef<HTMLDivElement>(null)
  /** The plan COLUMN — the element whose width the canvas may fill. */
  const planColRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState>(null)
  // Did the last prop press travel past `MOVE_START_PX`, i.e. was it a DRAG?
  // `dragRef` is already cleared on pointerup, and the click that follows the
  // release still has to know — a drag positions and selects its own piece
  // and must never advance the stack cycle.
  const propDraggedRef = useRef(false)
  const roomsRef = useRef(rooms)
  roomsRef.current = rooms

  // The contract's reference surface is a fixed 8×8 m SQUARE — the canvas
  // is square too, whatever the building footprint says. Its height is
  // therefore whatever width the browser really gave it (`canvasPx`), never
  // a nominal constant — see the zoom viewport below.
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
        vp.scrollLeft = fx * baseWRef.current * nz - (e.clientX - vpRect.left)
        vp.scrollTop = fy * baseWRef.current * nz - (e.clientY - vpRect.top)
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
      setCanvasPx(el.getBoundingClientRect().width || CANVAS_MIN_W)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // THE PLAN TAKES THE COLUMN IT IS GIVEN (§ W1).
  //
  // MEASURED ON THE COLUMN, NOT ON THE VIEWPORT. The scroll viewport grows a
  // vertical scrollbar as soon as the square canvas is taller than its cap,
  // so measuring IT would feed the scrollbar's width back into the canvas
  // width and the two would flip back and forth around that threshold. The
  // column outside it never scrolls; SCROLLBAR_PX is the fixed allowance for
  // the bar that will appear inside, and 2 px are the canvas border.
  useEffect(() => {
    const el = planColRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth - SCROLLBAR_PX - 2
      setBaseW(Math.round(Math.min(CANVAS_MAX_W,
                                   Math.max(CANVAS_MIN_W, w || CANVAS_MIN_W))))
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
    // WHICH STOREY, when the finding is about one. A narrowed building earns
    // findings that read identically on every floor ("this storey's own
    // footprint"), and the author is standing on one floor at a time.
    const where = p.levels?.length
      ? t('Storeys {n}').replace('{n}', p.levels.join(', '))
      : typeof p.level === 'number'
        ? t('Storey {n}').replace('{n}', String(p.level))
        : ''
    const lead = [where, room].filter(Boolean).join(' · ')
    return lead ? `${lead}: ${t(p.message)}` : t(p.message)
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
  /** The footprint the storey on screen is built on — its own entry, the
   *  nearest lower one, or the building's `outline` (§ G cascade). */
  const levelOutlinePts = useMemo(
    () => levelOutline(map3d, level), [map3d, level])
  /** …and whether that shape is THIS storey's own. Level 0 always is: the
   *  building's outline IS the ground floor's. */
  const ownLevelOutline = level === 0
    ? !!map3d?.outline?.length
    : outlineSourceLevel(map3d?.level_outlines, level) === level

  const view = useMemo<PlanView>(() => {
    const pts: Pt[] = [...boundaryM]
    for (const r of rooms) {
      const lay = r.layout
      // The yard has no rectangle to frame — it IS the boundary, which is
      // already in the list (§ A13a).
      if (!hasRect(lay)) continue
      pts.push([lay.x, lay.y], [lay.x + lay.w, lay.y + lay.d])
    }
    // EVERY storey's footprint frames the view, not just the one on screen:
    // switching to a narrower top floor must not make the plan jump.
    for (const p of map3d?.outline || []) pts.push([p[0], p[1]])
    for (const pl of Object.values(map3d?.level_outlines || {})) {
      for (const p of pl || []) pts.push([p[0], p[1]])
    }
    const base = viewportFor(pts, 0, FALLBACK_VIEW_M)
    const m = Math.max(1, base.size * 0.08)
    return { x0: base.x0 - m, z0: base.z0 - m, size: base.size + 2 * m }
  }, [boundaryM, rooms, map3d?.outline, map3d?.level_outlines])
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
  // in `map3d.stairs` (`id` — `_stair_flights` enumerates that very list). The
  // plan used to compute them from the storey height with a copy of the
  // server's formula; it reads them now, so what an author sees on the plan is
  // what the client walks on. Until the preview has answered (it is debounced),
  // a freshly placed flight has no symbol yet.
  //
  // THE INDEX IS THE IDENTITY, AND AN INDEX GOES STALE. The preview is a
  // debounced round trip, so between deleting or reordering a flight and the
  // answer arriving, `id` 0 still describes the flight that used to be first —
  // and the plan would draw ITS rectangle at the new first flight's place while
  // the number row mixed those steps and that run with the live `dir_deg`.
  // So the index is not trusted on its own: the composed block echoes the
  // author's own `at`/`dir_deg`/`from_level` (rounded to 4 decimals), and a
  // block that does not match the flight at that index is treated as ABSENT —
  // no symbol, "measuring the flight…" — exactly like a flight the preview has
  // never seen. Nothing stale is ever drawn or stated.
  const sceneFlightAt = useCallback((i: number): SceneStairs | null => {
    const local = map3d?.stairs?.[i]
    const block = (scene?.stairs || []).find((s) => s.id === i)
    if (!local || !block) return null
    const same = Math.abs(block.at[0] - local.at[0]) < 1e-3
      && Math.abs(block.at[1] - local.at[1]) < 1e-3
      && block.dir_deg === ((Math.trunc(local.dir_deg) % 360) + 360) % 360
      && block.from_level === local.from_level
    return same ? block : null
  }, [scene, map3d])
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
    () => Math.max(SNAP_TOL_PX * (view.size / (canvasPx || CANVAS_MIN_W)), 0.05),
    [view.size, canvasPx])

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
      buildingOutline: clickMode === 'draw-room'
        ? levelOutline(map3d, level) : undefined,
      // The location BOUNDARY is always a target: corners, edge midpoints and
      // the edges — a room meant to touch the plot's edge really touches it
      // (plan-area-detail-scenes.md). Since v6 that is the drawn polygon, not
      // a reference square.
      boundary: boundaryM,
      extraPoints: outlineDraft,
    })
  }, [clickMode, rooms, level, outlineDraft, drawTarget, map3d,
    boundaryM, snapTolM])

  const computeSnap = useCallback((clientX: number, clientY: number,
      alt: boolean): SnapResult => {
    const raw = pointerM(clientX, clientY)
    // Tolerances in METRES: the aiming radius is `snapTolM`, the ONE
    // derivation the target list was filtered with; only the closing radius
    // is its own number.
    const mPerPx = view.size / (canvasPxRef.current || CANVAS_MIN_W)
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

  /** Write ONE storey's footprint (§ G). Level 0 is the building's own
   *  `map3d.outline` — there is no storey below it to inherit from, so a
   *  separate entry for it would be a second name for the same shape. Every
   *  other storey lands in `level_outlines`; passing null drops its entry and
   *  it inherits again. */
  const writeLevelOutline = useCallback((lv: number,
      pts: Array<[number, number]> | null) => {
    if (lv === 0) {
      onMap3d?.('outline', pts && pts.length >= 3 ? pts : undefined)
      return
    }
    const merged: Record<string, Array<[number, number]>> = {
      ...(map3dRef.current?.level_outlines || {}) }
    if (pts && pts.length >= 3) merged[String(lv)] = pts
    else delete merged[String(lv)]
    onMap3d?.('level_outlines',
      Object.keys(merged).length ? merged : undefined)
  }, [onMap3d])

  const commitOutline = useCallback(() => {
    if (outlineDraft.length < 3) {
      planLog('commitOutline refused: fewer than 3 points',
        { draftLen: outlineDraft.length })
      return
    }
    // THE DRAFT BELONGS TO THE STOREY IT WAS STARTED ON, not to whichever one
    // the editor shows now: arming the tool records the level, so switching
    // storeys mid-draw cannot land the points on a floor nobody drew them on.
    writeLevelOutline(outlineLevelRef.current, outlineDraft)
    setOutlineDraft([])
    setHoverSnap(null)
    setClickMode('')
  }, [outlineDraft, writeLevelOutline])

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

  /** Drop ONE ghost and everything standing on it (decision E1). Returns how
   *  many pieces went — the caller turns 0 into "nothing selected". */
  const dropGhost = useCallback((sel: number): number => {
    const job = furnishRef.current
    const doomed = new Set(dependentIndices(job.ghosts, sel))
    job.setGhosts(job.ghosts.filter((_, i) => !doomed.has(i)))
    setGhostSel(null)
    return doomed.size
  }, [])

  // Esc cancels any armed mode and the current draft; R steps the placement
  // ghost's yaw by 90°; Del/Backspace drops the selected furnishing ghost
  // (never while typing in a field). A ghost that CARRIES others asks first —
  // the confirmation bar below the plan, never a browser dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName || ''
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === 'Escape') {
        setGhostDrop(null)
        cancelDraw()
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        const sel = ghostSelRef.current
        if (sel === null) return
        const job = furnishRef.current
        const n = dependentIndices(job.ghosts, sel).length - 1
        if (n > 0) setGhostDrop({ index: sel, dependents: n })
        else dropGhost(sel)
      } else if ((e.key === 'r' || e.key === 'R')) setGhostYaw((y) => (y + 90) % 360)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [cancelDraw, dropGhost])

  // Selecting another room closes the dialog and drops the ghost selection —
  // both belong to the room that was selected before.
  useEffect(() => {
    setGhostSel(null)
    setGhostDrop(null)
    setFurnishOpen(false)
  }, [selected])
  // Leaving the review state invalidates the ghost indices.
  useEffect(() => {
    if (!reviewing) {
      setGhostSel(null)
      setGhostDrop(null)
    }
  }, [reviewing])

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
  // The drag handler is bound once and needs the CURRENT library heights to
  // compose a child's support pose.
  const propDimsRef = useRef(ghostDims)
  propDimsRef.current = ghostDims
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
        : viewRef.current.size / (canvas.clientWidth || canvasPxRef.current)
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
            buildingOutline: levelOutline(map3dRef.current,
                                          lay.level || 0),
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
        // A CHILD MOVES IN ITS SUPPORT'S FRAME (decision E1). Dragging a
        // SUPPORT costs nothing extra — its children are stored relative and
        // come along by themselves; dragging a CHILD writes back the relative
        // pair, or the piece would jump the next time the support turns.
        // `stored` is the placements' real home: the yard's `lay` is a
        // DERIVED shape and carries none (§ A13a).
        const stored = room.layout?.props || []
        const childAt = (list: RoomPropPlacement[], idx: number,
                         point: [number, number]): [number, number] => {
          const child = list[idx]
          if (!child?.on) return point
          const support = list.findIndex((q) => q.id === child.on)
          if (support < 0) return point
          const rel = toSupportFrame(point, child.yaw || 0,
            composePlacements(withPropHeights(list, propDimsRef.current))[support])
          return [rM(rel.at[0]), rM(rel.at[1])]
        }
        if (drag.kind === 'ghost') {
          // Pending placements live in FE state only — nothing is stored
          // until Accept. A ghost may stand on another ghost OR on a piece
          // that is already in the room, so it composes over both lists.
          const job = furnishRef.current
          const next = childAt([...stored, ...job.ghosts],
                               stored.length + drag.index, at)
          job.setGhosts(job.ghosts.map((p, idx) =>
            idx === drag.index ? { ...p, at: next } : p))
          return
        }
        const moved = childAt(stored, drag.index, at)
        updateLayout(drag.roomId, {
          props: stored.map((p, idx) =>
            idx === drag.index ? { ...p, at: moved } : p),
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
      / (canvasRef.current?.clientWidth || canvasPxRef.current)
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

  /** Drag the room MODEL inside its room — the ⌂ handle on the plan. Its own
   *  starter like every other drag, so the canvas never touches `dragRef`. */
  const startModelDrag = useCallback((e: React.PointerEvent, room: Room) => {
    if (clickMode || armedProp || !room.id) return
    e.preventDefault()
    e.stopPropagation()
    dragRef.current = { kind: 'model', roomId: room.id }
  }, [clickMode, armedProp])

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
  //
  // WHAT IS APPENDED IS THE SERVER'S ANSWER, not the ghosts that were sent: a
  // ghost of an unbuilt piece carries the temporary `need:<key>` prop id, and
  // the server rewrote every one of them to the prop it just created. With the
  // ghosts in the draft the editor would be dirty against a room it matches,
  // and the next location save would send ids that `_sanitize_room_props`
  // refuses (the colon) — the whole accepted furnishing would vanish.
  const acceptFurnish = useCallback(async () => {
    const job = furnishRef.current
    const room = roomsRef.current.find((r) => r.id === selected)
    const list = job.ghosts
    // The yard may still have NO layout at all — accepting a furnishing is
    // exactly what creates one there (§ A13a), so the room itself is enough.
    if (!room || !list.length) return
    try {
      const res = await job.act('accept', { placements: list })
      const written = res?.placements?.length ? res.placements : list
      updateLayout(room.id || '', { props: [...(room.layout?.props || []), ...written] })
      setGhostSel(null)
      toast(t('{n} pieces added to the room')
        .replace('{n}', String(written.length)))
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
    // COMPOSED poses (decision E1): a piece standing on another one is drawn
    // where its support carries it, so that is where it is clicked too.
    const composed = composePlacements(
      withPropHeights(lay.props || [], ghostDims))
    ;(lay.props || []).forEach((p, i) => {
      const dims = ghostDims[p.prop_id]
      const pose = composed[i]
      // Metres from the placement's own anchor — the prop's dims are metres
      // too, so nothing converts.
      const cx = px - (pose.at[0] - o[0])
      const cy = py - (pose.at[1] - o[1])
      // The hit test undoes exactly the rotation the footprint is DRAWN with,
      // and that one is rotate(−yaw) on a y-down screen (see the prop layer
      // below / PlacementLayer.tsx:105). With +yaw here the test was the
      // inverse of the wrong turn — a 90°-turned prop could only be clicked
      // where it is not.
      const rad = (-pose.yaw * Math.PI) / 180
      const cos = Math.cos(rad)
      const sin = Math.sin(rad)
      const lx = cx * cos + cy * sin
      const ly = -cx * sin + cy * cos
      if (Math.abs(lx) <= (dims?.width_m || 1) / 2
          && Math.abs(ly) <= (dims?.depth_m || 1) / 2) hits.push(i)
    })
    return hits
  }, [ghostDims])

  // ── ONE PILE UNDER THE POINTER ───────────────────────────────────────
  // The plan draws in layers: room divs carry the prop footprints, and the
  // staircases sit in an overlay ABOVE them so a flight inside a room stays
  // visible. That layering used to decide the SELECTION too — a flight took
  // the click and stopped it there, so a prop under a staircase could not be
  // reached at all (user finding 2026-08-29). Both kinds now go into one
  // list and one cycle: the same "click the same spot again" that walks a
  // stack of props walks the flight with them.

  /** WHICH staircases cover a plan point (LOCAL metres). The flights this
   *  level shows, the ones ARRIVING from below included — they are drawn and
   *  clickable, so they are pickable. The polygon is the composed footprint,
   *  the very outline the overlay draws. */
  const stairsAtPoint = useCallback((p: Pt): number[] => {
    const out: number[] = []
    ;(map3d?.stairs || []).forEach((st, i) => {
      if (st.from_level !== level && st.from_level + 1 !== level) return
      const flight = sceneFlightAt(i)
      const sym = flight ? stairSymbol(flight) : null
      if (sym && pointInPolygon(p[0], p[1], sym.outline)) out.push(i)
    })
    return out
  }, [map3d?.stairs, level, sceneFlightAt])

  /** EVERYTHING under the pointer, BOTTOM PIECE FIRST: the prop footprints of
   *  every shape in draw order (`placed` runs yard → rooms, and inside a room
   *  the later placement wins ties), then the staircases, which draw over all
   *  of it. So the last entry is the topmost piece — the one a fresh click
   *  takes. */
  const picksAt = useCallback((clientX: number, clientY: number): PlanPick[] => {
    const p = pointerM(clientX, clientY)
    const out: PlanPick[] = []
    for (const s of placed) {
      // Each shape stores its placements in its own frame (§ A13a), so the
      // probe is turned into that frame per shape — the same two steps the
      // click handler does for the shape it was raised on.
      const o = atOrigin(s.lay, s.ground)
      const q = storedAt(s.lay, s.ground, p)
      for (const i of propsAtPoint(s.room.layout || {}, o,
                                   q[0] - o[0], q[1] - o[1])) {
        out.push({ kind: 'prop', room: s.room.id || '', index: i })
      }
    }
    for (const i of stairsAtPoint(p)) out.push({ kind: 'stair', index: i })
    return out
  }, [placed, pointerM, propsAtPoint, stairsAtPoint])

  /** Put ONE pick in hand. A prop and a flight are edited in different rows,
   *  so taking one always drops the other — the plan never holds two. */
  const applyPick = useCallback((pick: PlanPick) => {
    if (pick.kind === 'prop') {
      setStairSel(null)
      // `setSelected` clears `propSel`, so the room is set FIRST and only
      // when it really changes.
      if (pick.room !== selectedRef.current) setSelected(pick.room)
      setPropSel(pick.index)
      return
    }
    setPropSel(null)
    setStairSel(pick.index)
    setElevatorSel(false)
    setMarkerSel(null)
    // Picking an ARRIVING flight takes the plan down to the storey it starts
    // on — that is where it is edited, and the numbers in the row below
    // belong to that storey.
    const st = map3d?.stairs?.[pick.index]
    if (st && st.from_level !== level) setLevel(st.from_level)
  }, [map3d?.stairs, level, setSelected])

  /** THE CLICK, for props and staircases alike: walk the pile under the
   *  pointer. A fresh click takes the topmost piece; each further click on
   *  the same spot moves ONE entry on and wraps, so the walk runs top →
   *  bottom → upwards → top and reaches every piece. What makes it ADVANCE
   *  rather than restart is the selection as it stood BEFORE this click — a
   *  selection from elsewhere is not in the list, and then the click falls
   *  back to the top. `fallback` is the piece the event was raised on: with
   *  nothing else under the pointer there is nothing to cycle. */
  const pickAt = useCallback((clientX: number, clientY: number,
                              fallback: PlanPick) => {
    const hits = picksAt(clientX, clientY)
    if (hits.length < 2) { applyPick(fallback); return }
    const cur: PlanPick | null = stairSel !== null
      ? { kind: 'stair', index: stairSel }
      : (propSel !== null
        ? { kind: 'prop', room: selected, index: propSel }
        : null)
    const pos = cur === null ? -1 : hits.findIndex((h) => (
      cur.kind === 'stair'
        ? h.kind === 'stair' && h.index === cur.index
        : h.kind === 'prop' && h.index === cur.index && h.room === cur.room))
    applyPick(pos >= 0 ? hits[(pos + 1) % hits.length] : hits[hits.length - 1])
  }, [picksAt, applyPick, stairSel, propSel, selected])

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
      // The id is minted HERE, in the same 8-char base32 shape the server
      // uses (`places_migration.new_place_id`): a piece can only be named as
      // the SUPPORT of another one once it has an id, and waiting for the
      // save would make "place the candle on this table" a two-step gesture.
      const placements = [...(stored?.props || []),
        { id: newId(), prop_id: armedProp, at: [px, py] as [number, number],
          ...(ghostYaw ? { yaw: ghostYaw } : {}),
          // Only a non-primary pick is written down: an absent `variant` IS
          // the primary one everywhere else, and a stored 0 would say the
          // same thing in a second way.
          ...(armedVariant ? { variant: armedVariant } : {}) }]
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
  }, [clickMode, armedProp, armedVariant, ghostYaw, markerGroup, markerSel,
    selected, setSelected, updateLayout, calibrationRoomId, onCalibrationAt,
    t, toast, pointerM, gridStep])

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
    if (m === 'outline') setOutlineLevel(level)
    setClickMode(m)
    planLog('armed', { mode: m, ...(m === 'outline' ? { level } : {}) })
  }, [clickMode, selected, selectedRoom, groundSel, cancelDraw, level])

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

  // A CLICK ON THE PLAN IS A REQUEST TO SEE WHAT WAS CLICKED. Without this
  // the inspector could sit on the storey settings while the author drags a
  // prop, and the strip that edits it would be one tab away — the exact
  // stacking problem the dock was built to remove, only sideways.
  useEffect(() => {
    if (selected || propSel !== null || markerSel !== null
        || openingSel !== null || stairSel !== null || elevatorSel) {
      setInspTab('selection')
    }
  }, [selected, propSel, markerSel, openingSel, stairSel, elevatorSel])

  // How much the findings tab is holding, and what the selection tab is about
  // — the label says WHAT is selected, which is worth more on a tab than the
  // word "Selection" is.
  // WHAT THE BADGE COUNTS: things waiting to be fixed. The server's findings
  // and the leftover rooms — not the pass-throughs (data the author placed)
  // and not the ℹ note about a location without one, which describes a legal
  // state and would paint a red badge on a plan with nothing wrong.
  const findings = (scene?.problems || []).length + tinyRooms.length
  const selectionLabel = propSel !== null ? t('Prop')
    : markerSel !== null ? t('Marker')
      : openingSel !== null ? t('Opening')
        : stairSel !== null ? t('Stairs')
          : elevatorSel ? t('Lift')
            : groundSel ? t('Yard')
              : selectedRoom ? t('Room')
                : t('Nothing')

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
        {/* THE STOREY'S FLOOR AND WALL TEXTURES AND THE AREA SWITCHES MOVED
            INTO THE INSPECTOR'S "Storey" TAB (§ W3). Two selects behind a
            brown and a brick emoji used to sit here, in the row that is meant
            to say WHERE one is — and they said nothing about the texture they
            held. The picker there shows the tile itself. */}
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

      {/* THE WORKBENCH ROW (§ W): tool rail — plan — inspector dock. The row
          may shrink below its content (`minWidth: 0`), which is what lets the
          plan column measure the width it really has instead of the width its
          canvas wants. */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start',
        minWidth: 0 }}>
      <PlanToolbar
        mode={clickMode}
        hasSelection={!!selectedRoom}
        selectionRotation={selectedRoom?.layout?.rotation || 0}
        hasOutline={ownLevelOutline}
        hasBoundary={hasBoundary}
        outlineDraftLen={outlineDraft.length}
        hasElevator={!!map3d?.elevator}
        stairCount={map3d?.stairs?.length || 0}
        editLevel={level}
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
        onRemoveOutline={() => writeLevelOutline(level, null)}
        onRemoveElevator={() => onMap3d?.('elevator', undefined)}
        onCommitOutline={commitOutline}
        onCommitRoom={commitRoomDraft}
        onCancelDraw={cancelDraw}
        onSuggest={suggestOpenings}
        onProps={() => setPropsOpen((v) => !v)}
      />
      {/* Zoom viewport: the canvas grows with the zoom, this box scrolls it
          in BOTH axes (wheel zooms on the canvas). Its height follows the
          canvas BASE width — the canvas is 1:1, so a fixed cap clipped every
          zoom step (and every wide pane) vertically while the width grew. The viewport-relative cap keeps a
          3x plan from pushing the rest of the editor off the page; past it
          the box scrolls vertically like it always scrolled horizontally.
          The frame right around the viewport carries the scale bar — inside
          the viewport a zoomed-in plan would scroll its own scale out of
          sight, and anchored one level higher (on the column that also holds
          the status line) its "bottom: 8" would land on the status line's
          buttons instead of the plan's corner. */}
      <div ref={planColRef}
        style={{ flex: '1 1 auto', minWidth: 0, maxWidth: '100%' }}>
      <div style={{ position: 'relative' }}>
      <div ref={zoomViewportRef} style={{ overflow: 'auto', maxWidth: '100%',
        maxHeight: `min(${baseW + 14}px, 85vh)` }}>
      <PlanCanvas
        canvasRef={canvasRef}
        baseW={baseW}
        planZoom={planZoom}
        canvasPx={canvasPx}
        view={view}
        fx={fx}
        fz={fz}
        svgX={svgX}
        svgZ={svgZ}
        uPerM={uPerM}
        pointerM={pointerM}
        rooms={rooms}
        map3d={map3d}
        placed={placed}
        placedHere={placedHere}
        unplaced={unplaced}
        sceneRooms={sceneRooms}
        sceneFlightAt={sceneFlightAt}
        boundaryM={boundaryM}
        hasBoundary={hasBoundary}
        placedOnMap={placedOnMap}
        levelOutlinePts={levelOutlinePts}
        ownLevelOutline={ownLevelOutline}
        level={level}
        yardName={yardName}
        propDims={ghostDims}
        modelDims={modelDims}
        derivedSize={derivedSize}
        poseCatalog={poseCatalog}
        calibrationRoomId={calibrationRoomId}
        selected={selected}
        setSelected={setSelected}
        propSel={propSel}
        markerSel={markerSel}
        setMarkerSel={setMarkerSel}
        openingSel={openingSel}
        setOpeningSel={setOpeningSel}
        stairSel={stairSel}
        setStairSel={setStairSel}
        elevatorSel={elevatorSel}
        setElevatorSel={setElevatorSel}
        selectedBoundary={selectedBoundary}
        setSelectedBoundary={setSelectedBoundary}
        onRoomClick={onRoomClick}
        pickAt={pickAt}
        clickMode={clickMode}
        setClickMode={setClickMode}
        outlineDraft={outlineDraft}
        setOutlineDraft={setOutlineDraft}
        hoverSnap={hoverSnap}
        setHoverSnap={setHoverSnap}
        snapTargets={snapTargets}
        snapTolM={snapTolM}
        computeSnap={computeSnap}
        commitOutline={commitOutline}
        commitRoomDraft={commitRoomDraft}
        armedProp={armedProp}
        drawTarget={drawTarget}
        propGhost={propGhost}
        setPropGhost={setPropGhost}
        ghostYaw={ghostYaw}
        gridStep={gridStep}
        propDraggedRef={propDraggedRef}
        startDrag={startDrag}
        startModelDrag={startModelDrag}
        startPropDrag={startPropDrag}
        startOpeningDrag={startOpeningDrag}
        startCurveDrag={startCurveDrag}
        startGhostDrag={startGhostDrag}
        furnish={furnish}
        reviewing={reviewing}
        ghostSel={ghostSel}
        setGhostSel={setGhostSel}
        aids={aids}
        underlay={underlay}
        bUnderlay={bUnderlay}
        underlayUrl={underlayUrl}
        snapshotFrame={snapshotFrame}
        figureAt={figureAt}
        setFigurePos={setFigurePos}
        onMap3d={onMap3d}
        writeBoundary={writeBoundary}
        ownerOpeningIndex={ownerOpeningIndex}
      />
      </div>
      <PlanScaleBar view={view} canvasPx={canvasPx} />
      </div>
      {/* THE ONE LINE UNDER THE PLAN (§ W3). Everything that used to stack
          here — the legend, the leftover-room warning, the server's findings
          and the pass-through rows — lives in the inspector's Findings tab
          now and costs the plan no height when there is nothing to say. What
          is left is a pointer: how many findings are waiting, and a click
          that opens them. */}
      <div className="ga-plan-status">
        {findings ? (
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            title={t('Open the findings — what the composer and this editor have to say about the plan.')}
            onClick={() => {
              setInspTab('findings'); setInspCollapsedStored(false)
            }}
          >
            ⚠ {t('{n} findings').replace('{n}', String(findings))}
          </button>
        ) : null}
        {map3d?.boundary_openings?.length ? (
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            title={t('Open the boundary pass-throughs.')}
            onClick={() => {
              setInspTab('findings'); setInspCollapsedStored(false)
            }}
          >
            {t('{n} pass-throughs').replace('{n}',
              String(map3d.boundary_openings.length))}
          </button>
        ) : null}
      </div>
      </div>

      {/* ── The inspector dock (§ W3) ────────────────────────────────────
          Three panes as nodes, not as props: the selection pane below is
          built from closures over the drag state, the running draft and the
          server calls of this very component. */}
      <PlanInspector
        tab={inspTab}
        onTab={setInspTab}
        collapsed={inspCollapsed}
        onCollapsed={setInspCollapsedStored}
        selectionLabel={selectionLabel}
        findingCount={findings}
        level={(
          <PlanInspectorLevel
            level={level}
            map3d={map3d}
            onMap3d={onMap3d
              ? (key, value) => onMap3d(key as never, value as never)
              : undefined}
            surfaceKinds={surfaceKinds}
            defaultDoorPropId={defaultDoorPropId || ''}
            onDefaultDoorProp={onDefaultDoorProp}
            drawingOutline={clickMode === 'outline' && outlineLevel === level}
            canForkOutline={levelOutlinePts.length >= 3}
            onDrawOutline={() => armMode('outline')}
            onForkOutline={() => writeLevelOutline(level,
              levelOutlinePts.map((p) => [p[0], p[1]] as [number, number]))}
            onDropOutline={() => writeLevelOutline(level, null)}
          />
        )}
        findings={(
          <PlanFindings
            hasBoundary={hasBoundary}
            placedOnMap={placedOnMap}
            tinyRooms={tinyRooms}
            tinyRoomM={TINY_ROOM_M}
            problems={scene?.problems || []}
            problemText={problemText}
            map3d={map3d}
            onMap3d={onMap3d
              ? (key, value) => onMap3d(key as never, value as never)
              : undefined}
            boundaryM={boundaryM}
            planW={planW}
            placedRooms={placedRooms}
            selectedBoundary={selectedBoundary}
            onSelectBoundary={setSelectedBoundary}
            hasEntrance={hasEntrance}
          />
        )}
        selection={(
        <>
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
        armedVariant={armedVariant}
        onArmedVariant={setArmedVariant}
        onPickProp={(p) => {
          // Arming the prop tool drops any other armed mode/draft; picking
          // the armed prop again disarms.
          setClickMode('')
          setOutlineDraft([])
          setHoverSnap(null)
          setDrawTarget('')
          setArmedProp((cur) => (cur === p.id ? '' : p.id))
          // Another card is another object — its variants are not this one's.
          setArmedVariant(undefined)
        }}
      />

      {/* The furnishing proposal is a MODAL and renders through a portal, so
          it does not care that it is written inside the inspector pane. */}
      {furnishOpen && selectedRoom ? (
        <FurnishDialog
          roomId={furnishTarget}
          roomName={groundSel ? yardName : (selectedRoom.name || selectedRoom.id || '')}
          job={furnish}
          propInfo={propDims}
          placements={selectedRoom.layout?.props || []}
          surfaceKinds={surfaceKinds}
          waterKinds={waterKinds}
          onDescriptionApplied={(description) => {
            // The sync panel (E8) stored the text SERVER-SIDE; the draft here
            // still carries the old one and would write it back on the next
            // location save.
            onChange(rooms.map((r) => (r.id === selectedRoom.id
              ? { ...r, description } : r)))
          }}
          onClearRoom={() => {
            updateLayout(selectedRoom.id || '', { props: undefined })
            setPropSel(null)
          }}
          onAccept={acceptFurnish}
          onClose={() => setFurnishOpen(false)}
        />
      ) : null}

      {/* A GHOST DELETE THAT TAKES OTHERS WITH IT asks here (decision E1):
          Del on a pending piece that carries others states how many go before
          the click that drops them. In-app, never `window.confirm`. */}
      {ghostDrop ? (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center',
                      flexWrap: 'wrap' }}>
          <span className="ga-hint">
            {t('Also removes {n} piece(s) standing on it.')
              .replace('{n}', String(ghostDrop.dependents))}
          </span>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={() => { dropGhost(ghostDrop.index); setGhostDrop(null) }}
          >
            × {t('Remove all')}
          </button>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={() => setGhostDrop(null)}
          >
            {t('Cancel')}
          </button>
        </div>
      ) : null}

      {selectedRoom && propSel !== null
        && selectedRoom.layout?.props?.[propSel] ? (() => {
        const list = selectedRoom.layout?.props || []
        const placement = list[propSel]
        // COMPOSED poses (decision E1): everything below asks WHERE the pieces
        // really stand, which for a child is not what it stores.
        const withDims = withPropHeights(list, ghostDims)
        const composed = composePlacements(withDims)
        const pose = composed[propSel]
        const patchProp = (patch: Partial<typeof placement> | null) => {
          // A delete takes the whole subtree: a piece whose support is gone
          // has no frame left to be positioned in (`dependentIndices`).
          const doomed = patch === null
            ? new Set(dependentIndices(list, propSel))
            : new Set<number>()
          const next = list
            .map((p, i) => (i === propSel && patch ? { ...p, ...patch } : p))
            .filter((_, i) => !doomed.has(i))
          if (patch === null) setPropSel(null)
          updateLayout(selectedRoom.id || '',
                       { props: next.length ? next : undefined })
        }
        // Everything standing on this exact spot — the same turned-box test
        // that cycles the selection through a stack, asked at the placement's
        // own spot instead of at the cursor. Same ASCENDING-BY-INDEX order as
        // there (later placement wins ties = topmost), so the counter in the
        // strip reads from the bottom. The selection always hits its own
        // footprint, hence it is always in here.
        const stackHits = propsAtPoint(
          selectedRoom.layout || {}, selOrigin,
          pose.at[0] - selOrigin[0], pose.at[1] - selOrigin[1],
        )
        // WHICH of them carries the piece — the topmost surface that is not
        // part of this piece's own subtree (`pickSupport`, which owns both
        // rules and is checked by `scripts/smoke_placement_compose.mjs`). The
        // plan never computes the resulting HEIGHT: what is stored is the
        // relation, and the metres are composed server-side.
        const support = pickSupport(withDims, composed, propSel, stackHits)
        // SET IT DOWN ON THAT PIECE. What is written is the parent link plus
        // the pose in the support's frame — no height at all: the server
        // composes it from the support's top surface, so plan, preview and 3D
        // client cannot each arrive at their own answer.
        const placeOnTop = () => {
          if (support === null) return
          const supportId = list[support].id || newId()
          const rel = toSupportFrame(pose.at, pose.yaw, composed[support])
          const next = list.map((p, i) => {
            if (i === support) return { ...p, id: supportId }
            if (i !== propSel) return p
            return { ...p, on: supportId,
                     at: [rM(rel.at[0]), rM(rel.at[1])] as [number, number],
                     yaw: rel.yaw ? rM(rel.yaw) : undefined,
                     offset_y: undefined }
          })
          updateLayout(selectedRoom.id || '', { props: next })
        }
        // BACK ONTO THE FLOOR: the link goes and the composed pose becomes the
        // stored one, so the piece does not move while it is set down.
        const placeOnFloor = () => {
          patchProp({ on: undefined, offset_y: undefined,
                      at: [rM(pose.at[0]), rM(pose.at[1])],
                      yaw: pose.yaw ? rM(pose.yaw) : undefined })
        }
        const supportIdx = placement.on
          ? list.findIndex((p) => p.id === placement.on) : -1
        return (
          <PlanPropStrip
            placement={placement}
            index={propSel}
            name={ghostDims[placement.prop_id]?.name}
            origin={selOrigin}
            size={{ w: selLay?.w || 0, d: selLay?.d || 0 }}
            ground={groundSel}
            stackHits={stackHits}
            support={supportIdx >= 0 ? {
              label: list[supportIdx].label
                || ghostDims[list[supportIdx].prop_id]?.name
                || list[supportIdx].prop_id,
              width_m: ghostDims[list[supportIdx].prop_id]?.width_m || 1,
              depth_m: ghostDims[list[supportIdx].prop_id]?.depth_m || 1,
            } : undefined}
            dependents={dependentIndices(list, propSel).length - 1}
            onPlaceOnTop={support !== null ? placeOnTop : undefined}
            onPlaceOnFloor={placeOnFloor}
            onPatch={patchProp}
          />
        )
      })() : null}

      {/* Model calibration strip (rotation fix, room width, walkable floor)
          — placed BEFORE the model-placement strip so the three calibration
          anchors read in order: width_m → walk_y → model_offset_y. */}
      {children}

      {/* Model-placement strip: X/Y sliders + height for the selected
          room's diorama model — mirrors the prop strip; ↺ recentres. */}
      {selectedRoom && !groundSel && hasRect(selectedRoom.layout)
        && modelDims[selectedRoom.id || ''] ? (
        <PlanModelPlacement
          layout={selectedRoom.layout}
          onPatch={(patch) => updateLayout(selectedRoom.id || '', patch)}
        />
      ) : null}

      {selectedRoom && markerSel !== null
        && selectedRoom.layout?.markers?.[markerSel] ? (
        <PlanMarkerStrip
          marker={selectedRoom.layout.markers[markerSel]}
          index={markerSel}
          catalog={poseCatalog}
          origin={selOrigin}
          size={{ w: selLay?.w || 0, d: selLay?.d || 0 }}
          ground={groundSel}
          mode={clickMode}
          onMode={setClickMode}
          previewPose={previewPose}
          onPreviewPose={onPreviewPose}
          onPatch={(patch) => {
            const markers = (selectedRoom.layout?.markers || [])
              .map((m, i) => (i === markerSel ? { ...m, ...patch } : m))
              .filter((_, i) => !(patch === null && i === markerSel))
            if (patch === null) setMarkerSel(null)
            updateLayout(selectedRoom.id || '', { markers })
          }}
        />
      ) : null}

      {selectedRoom && openingSel !== null
        && selectedRoom.layout?.openings?.[openingSel] ? (
        <PlanOpeningStrip
          opening={selectedRoom.layout.openings[openingSel]}
          index={openingSel}
          otherRooms={rooms.filter((r) => r.id && r.id !== selectedRoom.id)}
          defaultDoorPropId={defaultDoorPropId}
          onPatch={(patch) => {
            const list = (selectedRoom.layout?.openings || [])
              .map((o, i) => (i === openingSel ? { ...o, ...patch } : o))
              .filter((_, i) => !(patch === null && i === openingSel))
            if (patch === null) setOpeningSel(null)
            updateLayout(selectedRoom.id || '', { openings: list })
          }}
        />
      ) : null}

      {elevatorSel && map3d?.elevator ? (
        <PlanElevatorStrip
          at={map3d.elevator}
          view={view}
          mode={clickMode}
          onMode={setClickMode}
          onMove={(at) => onMap3d?.('elevator', at)}
        />
      ) : null}

      {/* THE FLIGHT AND THE STOREY BELONG TOGETHER. Every path that changes
          the level clears the selection (they all run through `setSelected`),
          and picking a flight pulls the plan to its own storey — so this
          guard has nothing to hide today. It is the invariant written down:
          the row never states the steps and the run of a flight the plan above
          it is not showing. */}
      {stairSel !== null && map3d?.stairs?.[stairSel]
        && map3d.stairs[stairSel].from_level === level ? (
        <PlanStairStrip
          index={stairSel}
          flight={map3d.stairs[stairSel]}
          composed={sceneFlightAt(stairSel)}
          view={view}
          mode={clickMode}
          onMode={setClickMode}
          onPatch={(next) => {
            const list = map3d.stairs || []
            if (!next) {
              const rest = list.filter((_, i) => i !== stairSel)
              onMap3d?.('stairs', rest.length ? rest : undefined)
              setStairSel(null)
              return
            }
            onMap3d?.('stairs',
              list.map((st, i) => (i === stairSel ? next : st)))
          }}
        />
      ) : null}

      {/* Pick a room WITHOUT touching the plan (PlanRoomPicker). */}
      <PlanRoomPicker
        placed={placedRooms}
        unplaced={unplaced}
        hasYard={!!groundRoom}
        yardPlaced={!!yardLay}
        yardName={yardName}
        selected={selected}
        onSelect={setSelected}
        onSelectYard={() => { setLevel(0); setSelected(GROUND_ROOM_ID) }}
        drawTarget={drawTarget}
        drawing={clickMode === 'draw-room'}
        onDraw={armDrawFor}
      />
        </>
        )}
      />
      </div>
    </div>
  )
}
