/**
 * RoomLayoutEditor — the floor plan of a location (AV3D-2), embedded in the
 * location editor's "Floor plan" tab. The pane is three columns:
 * [PlanToolbar 44px] [canvas 420px] [PlanSidePanel]. Rooms are drawn as
 * polygon hulls on the building footprint: drag to move, corner handle to
 * resize; the icon toolbar rotates in 90° steps, places the exit and
 * animation markers (spots a figure with a matching animation snaps to —
 * kinds from the OPEN clip vocabulary, nothing hardcoded) with one click
 * inside the room, and draws the building outline / places the elevator
 * (AV3D-12). Everything edits the LOCATION draft (rooms[].layout) and is
 * persisted by the location's Save button — the external 3D client reads the
 * layout from /world/locations; rooms without a layout fall back to its
 * auto-grid.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import {
  CLOSE_TOL_PX, MIN_FRAC, MIN_WINDOW_EDGE_M, OPENING_COLOR, OPENING_DEFAULT,
  SNAP_TOL_PX, absOutline, buildSnapTargets, clamp, edgePointOnEdge,
  edgeSegment, exteriorEdges, fmtM, nearestPolygonEdge,
  normalizeOpeningEdge, outlineOf, r4, rotateOpeningCW, sharedEdges,
  snapDrawPoint, snapMoveOffset,
} from './planGeometry'
import type { EdgeLetter, PolyRoom, SnapResult } from './planGeometry'
import { FurnishDialog, useFurnishJob } from './FurnishDialog'
import { PlanFigure, PlanMetreGrid, PlanScaleBar } from './PlanMeasure'
import { PlanSidePanel } from './PlanSidePanel'
import { PlanToolbar } from './PlanToolbar'
import type { PlanMode } from './PlanToolbar'
import { getRoomModelDims, renderTopDownSnapshot } from './topDownSnapshot'
import type { Map3D, Room, RoomLayout, RoomOpening, SceneRoom, ScenePayload, SurfaceKind } from './worldTypes'

const CANVAS_W = 420

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
  /** Server verdict (Location.has_entrance): does this location carry any
   *  boundary pass-through at all? Without one it cannot be entered — the
   *  boundary-openings section warns with it, it does not re-derive the rule. */
  hasEntrance?: boolean
  /** Reports the selected room id ('' = none) — the Floor-plan tab shows the
   *  model adjustment strip for it. */
  onSelectRoom?: (roomId: string) => void
  /** The server-composed scene of the current draft (useScenePreview in the
   *  parent, shared with the 3D preview). Its per-room block delivers the
   *  neighbours' shared-wall openings and the derived exit in plan
   *  fractions — the editor DRAWS them, it does not derive them. */
  scene?: ScenePayload | null
  /** While the calibration figure is on for this room, a plain click inside
   *  it moves the figure (fraction of the room rectangle, UI state only). */
  calibrationRoomId?: string
  onCalibrationAt?: (at: [number, number]) => void
  /** Rendered at the bottom INSIDE the editor's frame — the Floor-plan tab
   *  slots the model adjustment strip of the selected room here. */
  children?: ReactNode
}

/** How far the pointer has to travel before a press on a room BECOMES a
 *  move. Below it the press is only a selection — clicking a room to work on
 *  it used to nudge it by whatever the hand did (user finding 2026-07-28). */
const MOVE_START_PX = 4

type DragState =
  | { kind: 'move'; roomId: string; startX: number; startY: number; origX: number; origY: number; moving?: boolean }
  | { kind: 'resize'; roomId: string; startX: number; startY: number; origW: number; origD: number }
  | { kind: 'opening'; roomId: string; index: number; edge: number }
  | { kind: 'curveCtl'; roomId: string; edge: number }
  | { kind: 'prop'; roomId: string; index: number }
  | { kind: 'ghost'; roomId: string; index: number }
  | { kind: 'model'; roomId: string }
  | null

/** Real prop dims for true-size footprints — lean mirror of /world/props. */
interface PropDims { name: string; width_m: number; depth_m: number; height_m: number }

export function RoomLayoutEditor({ rooms, onChange, locationId = '', map3d, onMap3d, hasEntrance, onSelectRoom, scene = null, calibrationRoomId = '', onCalibrationAt, children }: RoomLayoutEditorProps) {
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
    onSelectRoom?.(id)
  }, [onSelectRoom])
  // Click-to-place modes: the next click inside the room sets the exit point,
  // drops an animation marker of the chosen kind, or places a wall opening on
  // the nearest edge.
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
  const furnish = useFurnishJob(selected, furnishOpen)
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
            depth_m: p.depth_m, height_m: p.height_m }
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
  const [markerKind, setMarkerKind] = useState('')
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
  // Selected boundary pass-through (index into map3d.boundary_openings) —
  // highlights its bar on the frame and its edit row below the plan.
  const [selectedBoundary, setSelectedBoundary] = useState<number | null>(null)
  const [clipKinds, setClipKinds] = useState<string[]>([])
  useEffect(() => {
    apiGet<{ kinds?: string[] }>('/assets/animation-clips')
      .then((d) => {
        const kinds = d.kinds || []
        setClipKinds(kinds)
        setMarkerKind((k) => k || kinds[0] || '')
      })
      .catch(() => setClipKinds([]))
  }, [])
  // Surface-texture kinds for the room shell (floor/wall). The route answers
  // a BARE array mixing texture entries ({kind, url, size_m}) and blend
  // entries ({kind, blend}) — the picker wants the deduplicated kinds, with a
  // thumbnail wherever one exists.
  // What a picker STORES is the id; what it SHOWS is the name — the library
  // ships both, so no dropdown has to display "dark_stone" any more.
  const [surfaceKinds, setSurfaceKinds] = useState<SurfaceKind[]>([])
  useEffect(() => {
    apiGet<Array<{ kind?: string; name?: string; url?: string }>>(
      '/assets/surface-textures')
      .then((list) => {
        const byKind = new Map<string, { name: string; url: string }>()
        for (const entry of Array.isArray(list) ? list : []) {
          const kind = (entry?.kind || '').trim()
          if (!kind || byKind.has(kind)) continue
          byKind.set(kind, { name: (entry.name || '').trim() || kind,
                             url: entry.url || '' })
        }
        setSurfaceKinds(Array.from(byKind, ([kind, v]) => ({ kind, ...v }))
          .sort((a, b) => a.name.localeCompare(b.name)))
      })
      .catch(() => setSurfaceKinds([]))
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
  // Bottom-left, but clear of the scale bar in the corner below it.
  const [figurePos, setFigurePos] = useState<[number, number]>([0.05, 0.84])
  // The canvas is CANVAS_W at zoom 1 — unless a narrow pane shrinks it via
  // maxWidth. The scale bar and the grid step are stated in PIXELS, so they
  // measure the edge instead of assuming it.
  const [canvasPx, setCanvasPx] = useState(CANVAS_W)
  const canvasRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState>(null)
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

  const placed = rooms.filter((r) => r.layout && (r.layout.level || 0) === level)
  const unplaced = rooms.filter((r) => !r.layout)
  const placedRooms = rooms.filter((r) => r.layout && r.id)
  const levels = Array.from(
    new Set(rooms.filter((r) => r.layout).map((r) => r.layout!.level || 0)),
  ).sort((a, b) => a - b)

  // Re-render the underlay (debounced — drags update per pointermove)
  // whenever the SERVER's scene payload changes: the snapshot places models
  // from the same specs as the 3D preview, so both match by construction.
  const geomKey = JSON.stringify(rooms.filter((r) => r.layout).map((r) => [
    r.id, r.layout!.level || 0, r.layout!.x, r.layout!.y, r.layout!.w,
    r.layout!.d, r.layout!.rotation || 0,
  ]))
  useEffect(() => {
    if (!underlay && !bUnderlay) {
      setUnderlayUrl('')
      return
    }
    if (!scene) return   // payload pending — keep the last underlay
    const tid = setTimeout(() => {
      renderTopDownSnapshot({
        models: scene.models || [], extentM: scene.extent_m,
        level, includeRooms: underlay,
        buildingId: bUnderlay && locationId ? locationId : undefined,
      })
        .then((url) => setUnderlayUrl(url || ''))
        .catch(() => setUnderlayUrl(''))
    }, 350)
    return () => clearTimeout(tid)
  }, [underlay, bUnderlay, level, locationId, scene])

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
  // The ONLY scale anchor (2026-07-28): how many REAL metres the location is
  // wide. Nothing derives it from a model any more.
  const planW = map3d?.plan_width_m || 0
  // Relief wave width, said in something a person can picture: the server
  // turns the authored metres into a grid over the plan (cells = plan width /
  // wave, half-up, clamped to 2…22 — RELIEF_CELLS_MIN/MAX in
  // app/core/scatter_curves.py, whose upper bound is what the drape can
  // resolve), so the caption reports the swell count the current setting
  // actually produces. Without a wave width the default is the fixed 16 cells
  // every location had before the setting existed — the number the empty
  // field's placeholder shows.
  const reliefWaveDefaultM = planW > 0 ? Math.round((planW / 16) * 10) / 10 : 0
  const reliefWaveM = map3d?.relief?.wave_m || reliefWaveDefaultM
  const reliefSwells = reliefWaveM > 0 && planW > 0
    ? Math.max(2, Math.min(22, Math.round(planW / reliefWaveM)))
    : 0
  // MANDATORY for floor-plan work (Abnahme round 4): a layout without it has
  // no real size. Existing data stays readable and selectable; only the
  // geometry tools are locked.
  const anchorMissing = planW <= 0 && (
    rooms.some((r) => r.layout) || !!map3d?.outline?.length)
  // ── Server-composed room vocabulary (contract § B1 `rooms`) ──────────
  // Shared-wall openings and the derived exit are TRUTH, not cosmetics —
  // they come from the same scene payload the 3D preview renders, in plan
  // fractions. The editor draws them; it never re-derives them.
  const sceneRooms = useMemo(
    () => new Map((scene?.rooms || []).map((r) => [r.room_id, r] as [string, SceneRoom])),
    [scene])
  // A mirrored opening is one hole seen from the other side — find the
  // ORIGINAL in the owning room so a click can select it there. Identity by
  // position (plan fractions), since the payload does not index back.
  const ownerOpeningIndex = useCallback(
    (ownerId: string, point: { x: number; y: number }): number => {
      const owner = rooms.find((r) => r.id === ownerId)
      const ownerScene = sceneRooms.get(ownerId)
      if (!owner?.layout || !ownerScene) return -1
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
  const planWRef = useRef(planW)
  planWRef.current = planW
  const [modelDims, setModelDims] = useState<Record<string,
    { widthM: number; fpX: number; fpZ: number } | null>>({})
  useEffect(() => {
    if (!planW) return
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
  }, [planW, rooms.length])

  // Snapping while drawing (always on, Shift = free-hand): targets are the
  // hulls of the placed rooms on the current level plus the draft's own
  // vertices; tolerances blend a pixel radius with a 0.15 m floor.
  const snapTargets = useMemo(() => {
    if (clickMode !== 'outline' && clickMode !== 'draw-room') return null
    const hulls: PolyRoom[] = rooms
      .filter((r) => r.id && r.layout && (r.layout.level || 0) === level
        && !(clickMode === 'draw-room' && r.id === drawTarget))
      .map((r) => ({ id: r.id!, x: r.layout!.x, y: r.layout!.y,
        w: r.layout!.w, d: r.layout!.d, outline: r.layout!.outline }))
    return buildSnapTargets(hulls, {
      // Rooms snap onto the building outline; while the OUTLINE itself is
      // being redrawn it is not a target.
      buildingOutline: clickMode === 'draw-room' ? map3d?.outline : undefined,
      // The reference-square frame is always a target: corners, edge
      // midpoints and the edges — a room meant to touch the cell edge
      // really touches it (plan-area-detail-scenes.md).
      frame: true,
      extraPoints: outlineDraft,
    })
  }, [clickMode, rooms, level, outlineDraft, drawTarget, map3d?.outline])

  const computeSnap = useCallback((clientX: number, clientY: number,
      alt: boolean): SnapResult => {
    const rect = (canvasRef.current as HTMLDivElement).getBoundingClientRect()
    const raw: [number, number] = [(clientX - rect.left) / rect.width,
                                   (clientY - rect.top) / rect.height]
    const planWEff = planW || 8
    const zoomW = CANVAS_W * planZoomRef.current
    const tol = Math.min(0.05, Math.max(SNAP_TOL_PX / zoomW, 0.15 / planWEff))
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
      closeTol: CLOSE_TOL_PX / zoomW,
      alt,
    })
  }, [outlineDraft, snapTargets, planW])

  const commitOutline = useCallback(() => {
    if (outlineDraft.length < 3) return
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

  const derivedSize = useCallback((roomId: string):
      { w: number; d: number } | null => {
    if (!planW) return null
    const dims = modelDims[roomId]
    if (!dims || !(dims.widthM > 0)) return null
    const long = Math.min(dims.widthM / planW, 1)
    const aspect = Math.min(dims.fpX, dims.fpZ) / (Math.max(dims.fpX, dims.fpZ) || 1)
    const short = Math.max(long * aspect, MIN_FRAC)
    // The model's X side carries the largest extent when fpX >= fpZ.
    return dims.fpX >= dims.fpZ ? { w: long, d: short } : { w: short, d: long }
  }, [planW, modelDims])

  // Auto-correct placed rooms to their derived size (rotation 90/270 swaps
  // w/d, matching the rotate-as-unit behavior). Runs whenever anchors or
  // dims change; r4 rounding keeps it from oscillating.
  useEffect(() => {
    if (!planW) return
    let changed = false
    const next = roomsRef.current.map((r) => {
      const lay = r.layout
      // A drawn hull is authoritative — width_m-derived sizing only applies
      // to legacy diorama-model rooms without an outline (D4).
      const ds = r.id && !r.layout?.outline?.length ? derivedSize(r.id) : null
      if (!lay || !ds) return r
      const swap = ((lay.rotation || 0) % 180) === 90
      const wantW = r4(swap ? ds.d : ds.w)
      const wantD = r4(swap ? ds.w : ds.d)
      if (Math.abs(lay.w - wantW) < 0.0005 && Math.abs(lay.d - wantD) < 0.0005) return r
      changed = true
      return { ...r, layout: { ...lay,
        w: wantW, d: wantD,
        x: r4(clamp(lay.x + (lay.w - wantW) / 2, 0, 1 - wantW)),
        y: r4(clamp(lay.y + (lay.d - wantD) / 2, 0, 1 - wantD)) } }
    })
    if (changed) onChange(next)
  }, [planW, derivedSize, geomKey, onChange])

  // Fit the SELECTED room's plan to its 3D model — the manual counterpart of
  // the auto-sizing above, which deliberately leaves drawn hulls alone. After
  // calibrating a model against the reference figure the plan is usually the
  // one thing left too big (user finding 2026-07-28, Handwerker Hütte).
  const fitToModel = useCallback(() => {
    const room = roomsRef.current.find((r) => r.id === selectedRef.current)
    const lay = room?.layout
    const dims = room?.id ? modelDimsRef.current[room.id] : null
    if (!lay || !room?.id || !dims || dims.widthM <= 0 || planWRef.current <= 0) return
    // The model's footprint in PLAN fractions: its declared real width over
    // the plan width, the short side via the mesh's own aspect. The long side
    // caps at the plan square BEFORE the short side derives from it (same
    // rule as derivedSize) — clamping the two axes independently afterwards
    // would change the aspect, not just the size.
    const long = Math.min(dims.widthM / planWRef.current, 1)
    const aspect = Math.min(dims.fpX, dims.fpZ) / (Math.max(dims.fpX, dims.fpZ) || 1)
    const short = Math.max(long * aspect, MIN_FRAC)
    let wantW = dims.fpX >= dims.fpZ ? long : short
    let wantD = dims.fpX >= dims.fpZ ? short : long
    if (((lay.rotation || 0) % 180) === 90) [wantW, wantD] = [wantD, wantW]
    if (lay.outline?.length) {
      // A drawn hull keeps the SHAPE it was drawn in — only its size follows
      // the model, so the longest side matches and the rest scales with it.
      // The factor caps where the scaled hull would leave the plan square,
      // for the same reason the long side caps above.
      const f = Math.min(Math.max(wantW, wantD) / (Math.max(lay.w, lay.d) || 1),
                         1 / (lay.w || 1), 1 / (lay.d || 1))
      wantW = lay.w * f
      wantD = lay.d * f
    }
    wantW = clamp(r4(wantW), MIN_FRAC, 1)
    wantD = clamp(r4(wantD), MIN_FRAC, 1)
    updateLayoutRef.current?.(room.id, {
      w: wantW,
      d: wantD,
      x: r4(clamp(lay.x + (lay.w - wantW) / 2, 0, 1 - wantW)),
      y: r4(clamp(lay.y + (lay.d - wantD) / 2, 0, 1 - wantD)),
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
      const base: RoomLayout = r.layout || { level, x: 0.05, y: 0.05, w: 0.3, d: 0.3 }
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

  // Close a drawn room hull: bbox becomes x/y/w/d (the legacy client keeps
  // reading only those), the points renormalize to bbox-local [0,1]² with
  // clockwise winding — mirroring the server sanitizer. Redrawing clears the
  // openings (their edge indices point into the OLD hull); exit and markers
  // stay (still valid room fractions, one click to adjust).
  const commitRoomDraft = useCallback(() => {
    if (!drawTarget || outlineDraft.length < 3) return
    const xs = outlineDraft.map((p) => p[0])
    const ys = outlineDraft.map((p) => p[1])
    const minX = Math.min(...xs)
    const minY = Math.min(...ys)
    const w = Math.max(...xs) - minX
    const d = Math.max(...ys) - minY
    if (w < MIN_FRAC || d < MIN_FRAC) {
      toast(t('The shape is too small — keep drawing or press Esc.'), 'error')
      return
    }
    let pts = outlineDraft.map(([x, y]) =>
      [(x - minX) / w, (y - minY) / d] as [number, number])
    const shoelace = pts.reduce((sum, p, i) => {
      const q = pts[(i + 1) % pts.length]
      return sum + p[0] * q[1] - q[0] * p[1]
    }, 0)
    if (Math.abs(shoelace) / 2 < 1e-4) {
      toast(t('The shape has no area — keep drawing or press Esc.'), 'error')
      return
    }
    if (shoelace < 0) pts = [...pts].reverse()
    const target = roomsRef.current.find((r) => r.id === drawTarget)
    if (target?.layout?.openings?.length)
      toast(t('Openings were cleared — they sat on the old hull.'), 'info')
    updateLayout(drawTarget, {
      level,
      x: r4(minX), y: r4(minY), w: r4(w), d: r4(d),
      outline: pts.map(([u, v]) => [r4(u), r4(v)] as [number, number]),
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
  // Window listeners so a drag survives leaving the canvas; fractions clamped
  // to keep the room inside the footprint.
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const drag = dragRef.current
      const canvas = canvasRef.current
      if (!drag || !canvas) return
      e.preventDefault()
      const room = roomsRef.current.find((r) => r.id === drag.roomId)
      const lay = room?.layout
      if (!lay) return
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
        const dx = (e.clientX - drag.startX) / canvas.clientWidth
        const dy = (e.clientY - drag.startY) / canvas.clientHeight
        let nx = clamp(drag.origX + dx, 0, 1 - lay.w)
        let ny = clamp(drag.origY + dy, 0, 1 - lay.d)
        // Moving snaps like drawing does (Shift = free-hand): the moved
        // hull's vertices align with neighbour/building-outline vertices —
        // x and y independently, so gaps close one wall at a time.
        if (!e.shiftKey) {
          const hulls: PolyRoom[] = roomsRef.current
            .filter((r) => r.id && r.id !== drag.roomId && r.layout
              && (r.layout.level || 0) === (lay.level || 0))
            .map((r) => ({ id: r.id!, x: r.layout!.x, y: r.layout!.y,
              w: r.layout!.w, d: r.layout!.d, outline: r.layout!.outline }))
          const targets = buildSnapTargets(hulls,
            { buildingOutline: map3dRef.current?.outline })
          const planWEff = planWRef.current || 8
          const tol = Math.min(0.05,
            Math.max(SNAP_TOL_PX / (CANVAS_W * planZoomRef.current),
                     0.15 / planWEff))
          const [sx, sy] = snapMoveOffset(
            absOutline({ ...lay, x: nx, y: ny }), targets, tol)
          nx = clamp(nx + sx, 0, 1 - lay.w)
          ny = clamp(ny + sy, 0, 1 - lay.d)
        }
        updateLayout(drag.roomId, { x: r4(nx), y: r4(ny) })
      } else if (drag.kind === 'resize') {
        const dx = (e.clientX - drag.startX) / canvas.clientWidth
        const dy = (e.clientY - drag.startY) / canvas.clientHeight
        updateLayout(drag.roomId, {
          w: r4(clamp(drag.origW + dx, MIN_FRAC, 1 - lay.x)),
          d: r4(clamp(drag.origD + dy, MIN_FRAC, 1 - lay.y)),
        })
      } else if (drag.kind === 'opening') {
        // Opening drag: slide it along its polygon edge — project the cursor
        // onto the edge in PLAN fractions. The write normalizes a legacy
        // letter opening to the index vocabulary (the editor only writes
        // indices).
        const rect = canvas.getBoundingClientRect()
        const fx = (e.clientX - rect.left) / rect.width
        const fy = (e.clientY - rect.top) / rect.height
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
        // Bezier control point (plan-area-detail-scenes.md): room-local
        // fractions, clamped to the server's [-1, 2] validity window — a
        // bulge may leave the bbox on purpose.
        const rect = canvas.getBoundingClientRect()
        const fx = (e.clientX - rect.left) / rect.width
        const fy = (e.clientY - rect.top) / rect.height
        const c: [number, number] = [
          r4(clamp((fx - lay.x) / (lay.w || 1), -1, 2)),
          r4(clamp((fy - lay.y) / (lay.d || 1), -1, 2)),
        ]
        updateLayout(drag.roomId, {
          outline_curves: (lay.outline_curves || []).map((cv) =>
            cv.edge === drag.edge ? { ...cv, c } : cv),
        })
      } else {
        // Prop / ghost drag: reposition inside the room (room-local
        // fractions). The piece keeps its real size — only `at` moves.
        const rect = canvas.getBoundingClientRect()
        const fx = (e.clientX - rect.left) / rect.width
        const fy = (e.clientY - rect.top) / rect.height
        const at: [number, number] = [
          r4(clamp((fx - lay.x) / (lay.w || 1), 0, 1)),
          r4(clamp((fy - lay.y) / (lay.d || 1), 0, 1)),
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
  }, [updateLayout])

  const startDrag = useCallback((e: React.PointerEvent, room: Room, kind: 'move' | 'resize') => {
    if (clickMode) return
    const lay = room.layout
    if (!lay || !room.id) return
    e.preventDefault()
    e.stopPropagation()
    setSelected(room.id)
    dragRef.current = kind === 'move'
      ? { kind, roomId: room.id, startX: e.clientX, startY: e.clientY, origX: lay.x, origY: lay.y }
      : { kind, roomId: room.id, startX: e.clientX, startY: e.clientY, origW: lay.w, origD: lay.d }
  }, [clickMode, setSelected])

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
  const startPropDrag = useCallback(
    (e: React.PointerEvent, room: Room, index: number) => {
      if (clickMode || armedProp || !room.id) return
      e.preventDefault()
      e.stopPropagation()
      setSelected(room.id)
      setPropSel(index)
      dragRef.current = { kind: 'prop', roomId: room.id, index }
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
    if (!room?.layout || !list.length) return
    try {
      await job.act('accept', { placements: list })
      updateLayout(room.id || '', { props: [...(room.layout.props || []), ...list] })
      setGhostSel(null)
      toast(t('{n} pieces added to the room').replace('{n}', String(list.length)))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [selected, updateLayout, t, toast])

  // All prop indices whose TRUE-size footprint covers a room-local point —
  // in render order (the last entry draws topmost). Clicking stacked props
  // cycles the selection through this list.
  const propsAtPoint = useCallback((lay: NonNullable<Room['layout']>,
      px: number, py: number): number[] => {
    const planWEff = planWRef.current || 8
    const hits: number[] = []
    ;(lay.props || []).forEach((p, i) => {
      const dims = propDims[p.prop_id]
      // Canvas units (the plan square is 1×1; the room spans w×d of it).
      const cx = (px - p.at[0]) * (lay.w || 1)
      const cy = (py - p.at[1]) * (lay.d || 1)
      const rad = ((p.yaw || 0) * Math.PI) / 180
      const cos = Math.cos(rad)
      const sin = Math.sin(rad)
      const lx = cx * cos + cy * sin
      const ly = -cx * sin + cy * cos
      if (Math.abs(lx) <= ((dims?.width_m || 1) / planWEff) / 2
          && Math.abs(ly) <= ((dims?.depth_m || 1) / planWEff) / 2) hits.push(i)
    })
    return hits
  }, [propDims])

  // Click-to-place: one click inside a room sets the exit point, drops an
  // animation marker or a prop placement — all as fractions of the ROOM
  // rectangle (contract).
  const onRoomClick = useCallback((e: React.MouseEvent, room: Room) => {
    if ((!clickMode && !armedProp && !calibrationRoomId) || !room.id || !room.layout) return
    e.stopPropagation()
    const target = e.currentTarget as HTMLDivElement
    const rect = target.getBoundingClientRect()
    const px = r4(clamp((e.clientX - rect.left) / rect.width, 0, 1))
    const py = r4(clamp((e.clientY - rect.top) / rect.height, 0, 1))
    if (!clickMode && !armedProp) {
      // Calibration figure armed: a click inside ITS room moves the
      // reference person there (UI state only, never stored).
      if (room.id === calibrationRoomId) onCalibrationAt?.([px, py])
      return
    }
    if (armedProp) {
      // Place the armed prop at the clicked spot. REAL-size rule: only
      // position + yaw are stored — the prop's own dims scale it. The tool
      // stays armed for multiple placements; Esc or re-picking ends it.
      const placements = [...(room.layout.props || []),
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
          markers: (room.layout.markers || []).map((m, idx) =>
            idx === markerSel ? { ...m, at: [px, py] as [number, number] } : m),
        })
      }
    } else if (clickMode === 'marker' && markerKind) {
      updateLayout(room.id, {
        markers: [...(room.layout.markers || []),
                  { at: [px, py] as [number, number], animation: markerKind }],
      })
      setMarkerSel((room.layout.markers || []).length)
    } else if (clickMode === 'curve') {
      // Toggle a bezier control point on the nearest hull edge of the
      // SELECTED room (plan-area-detail-scenes.md). The mode stays armed —
      // a road bends more than once.
      const lay0 = room.layout
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
          r4(clamp((a[0] + b[0]) / 2 + dy * 0.25, -1, 2)),
          r4(clamp((a[1] + b[1]) / 2 - dx * 0.25, -1, 2)),
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
      const { edge, at } = nearestPolygonEdge(outlineOf(room.layout), [px, py])
      if ((room.layout.outline_curves || []).some((c) => c.edge === edge)) {
        // The server rejects these (v1) — refuse up front instead of
        // silently losing the opening on save.
        toast(t('Openings cannot sit on a curved edge — remove the curve first.'), 'error')
        return
      }
      const lay0 = room.layout
      const others: PolyRoom[] = roomsRef.current
        .filter((r) => r.id && r.id !== room.id && r.layout
          && (r.layout.level || 0) === (lay0.level || 0))
        .map((r) => ({ id: r.id!, x: r.layout!.x, y: r.layout!.y,
          w: r.layout!.w, d: r.layout!.d, outline: r.layout!.outline }))
      const hull: PolyRoom = { id: room.id, x: lay0.x, y: lay0.y,
        w: lay0.w, d: lay0.d, outline: lay0.outline }
      const shared = sharedEdges(hull, others, planWRef.current || 8)
        .find((sh) => sh.edge === edge)
      const openings: RoomOpening[] = [...(room.layout.openings || []),
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
  }, [clickMode, armedProp, ghostYaw, markerKind, markerSel, selected,
    setSelected, updateLayout, calibrationRoomId, onCalibrationAt, t, toast])

  const selectedRoom = rooms.find((r) => r.id === selected && r.layout)

  // Model presence for the SELECTED room — the plan-placement handle and
  // strip only show when a diorama model exists (anchored mode loads dims
  // for all rooms anyway; this covers the legacy mode too).
  useEffect(() => {
    if (!selected || selected in modelDims) return
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
    // Geometry that carries a real size stays locked without a scale anchor
    // (the toolbar disables these too — this is the second lock).
    if (planW <= 0 && (m === 'draw-room' || m === 'outline' || m === 'marker'
        || m === 'curve')) return
    if (m === 'draw-room') {
      if (!selectedRoom?.id) return
      setDrawTarget(selectedRoom.id)
    }
    // Curves bend hull edges — without a drawn hull there is nothing to bend.
    if (m === 'curve' && !selectedRoom?.layout?.outline?.length) return
    setOutlineDraft([])
    setHoverSnap(null)
    setClickMode(m)
  }, [clickMode, selectedRoom, cancelDraw, planW])

  // Room shell: pick the surface-texture kind for floor or wall. Empty keys
  // are pruned, an all-empty map drops the field — the client then falls back
  // to the global kind / its own default.
  const setSurface = useCallback((key: 'floor' | 'wall', kind: string) => {
    const lay = roomsRef.current.find((r) => r.id === selected)?.layout
    if (!lay) return
    const merged = { ...(lay.surfaces || {}), [key]: kind.trim() }
    const surfaces: { floor?: string; wall?: string } = {}
    if (merged.floor) surfaces.floor = merged.floor
    if (merged.wall) surfaces.wall = merged.wall
    updateLayout(selected, {
      surfaces: Object.keys(surfaces).length ? surfaces : undefined,
    })
  }, [selected, updateLayout])

  // Rotate the room AS A UNIT (clockwise on the plan): the rectangle swaps
  // w/d around its centre, exit and markers turn with the content
  // ((x,y) -> (1-y, x)), rotation yaws the room MODEL inside the rectangle.
  const rotateSelected = () => {
    const lay = selectedRoom?.layout
    if (!lay || !selectedRoom) return
    const w = lay.d
    const d = lay.w
    updateLayout(selectedRoom.id || '', {
      rotation: (((lay.rotation || 0) + 90) % 360) || undefined,
      w,
      d,
      x: r4(clamp(lay.x + (lay.w - w) / 2, 0, 1 - w)),
      y: r4(clamp(lay.y + (lay.d - d) / 2, 0, 1 - d)),
      ...(lay.exit
        ? { exit: [r4(1 - lay.exit[1]), r4(lay.exit[0])] as [number, number] }
        : {}),
      ...(lay.model_at
        ? { model_at: [r4(1 - lay.model_at[1]), r4(lay.model_at[0])] as [number, number] }
        : {}),
      ...(lay.markers?.length
        ? { markers: lay.markers.map((m) => ({
            ...m,
            at: [r4(1 - m.at[1]), r4(m.at[0])] as [number, number],
            ...(m.rotation !== undefined ? { rotation: (m.rotation + 90) % 360 } : {}),
          })) }
        : {}),
      // Openings turn with the room. A drawn outline rotates by baking the
      // point transform, so its edge indices stay put; on the implicit unit
      // square an index steps one edge clockwise (at is measured along the
      // clockwise direction and stays); legacy letters keep their own rule.
      ...(lay.outline?.length
        ? { outline: lay.outline.map(
            ([u, v]) => [r4(1 - v), r4(u)] as [number, number]) }
        : {}),
      // Curve control points bake the same transform as the outline points;
      // edge indices stay (the hull's vertex order is unchanged).
      ...(lay.outline?.length && lay.outline_curves?.length
        ? { outline_curves: lay.outline_curves.map((cv) => ({ ...cv,
            c: [r4(1 - cv.c[1]), r4(cv.c[0])] as [number, number] })) }
        : {}),
      ...(lay.openings?.length
        ? { openings: lay.openings.map((o) => (typeof o.edge === 'string'
            ? { ...o, ...rotateOpeningCW(o.edge as EdgeLetter, o.at) }
            : lay.outline?.length ? o : { ...o, edge: (o.edge + 1) % 4 })) }
        : {}),
    })
  }

  // "Suggest openings": a door on every shared wall (once per pair, on the
  // room that triggers it, `to` = the neighbour), an ENTRANCE door for every
  // room that would otherwise stay sealed, and a window on every exterior
  // edge ≥ 2.5 m. Suggestions are normal, editable openings; the button never
  // overwrites — it skips any edge that already carries an opening.
  const suggestOpenings = () => {
    // planW is guaranteed by the anchor gate; the fallback only keeps the
    // helpers' tolerances sane if it ever slips through as 0.
    const planWEff = planW || 8
    const onLevel = rooms.filter((r) => r.id && r.layout && (r.layout.level || 0) === level)
    const hulls: PolyRoom[] = onLevel.map((r) => ({
      id: r.id!, x: r.layout!.x, y: r.layout!.y, w: r.layout!.w, d: r.layout!.d,
      outline: r.layout!.outline,
    }))
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
        for (const s of sharedEdges(hulls[i], [hulls[j]], planWEff)) {
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
      const candidates = exteriorEdges(a, hulls.filter((r) => r.id !== a.id), planWEff)
        .map((e) => {
          const seg = edgeSegment(oa, e)
          return { edge: e,
            len: Math.hypot(seg.b[0] - seg.a[0], seg.b[1] - seg.a[1]) * planWEff }
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
      for (const e of exteriorEdges(a, hulls.filter((r) => r.id !== a.id), planWEff)) {
        const seg = edgeSegment(oa, e)
        const edgeLenM = Math.hypot(seg.b[0] - seg.a[0], seg.b[1] - seg.a[1]) * planWEff
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
                  String(rooms.filter((r) => r.layout && (r.layout.level || 0) === lv).length))}
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
          disabled={planW <= 0}
          onClick={() => setAids((v) => !v)}
          title={planW <= 0
            ? t('Set the plan width (m) first — without a scale anchor the plan has no real size to show.')
            : t('Reference sizes: a grid in whole metres and the 1.70 m person from above, draggable. The scale bar at the bottom left stays either way.')}
        >
          📏
        </button>
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
        {/* Terrain relief (v5.2 Nr. 14). A detail scene without a diorama is
            dead flat; the amplitude rolls the ground and the server lifts
            everything standing on it — no prop height is ever set by hand.
            The seed is written WITH the first amplitude: the field is
            deterministic, so a relief without a seed has no identity. */}
        {onMap3d && map3d?.area_detail ? (
          <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Terrain relief: swing of the ground in real metres (0 = flat). A deterministic height field rolls the whole location; the server lifts props, markers and exits onto it, indoor rooms stay level. Outdoor rooms can opt out per room ("Keep flat").')}>
            ⛰
            <span>{t('Relief (m)')}</span>
            <input
              className="ga-input"
              type="number"
              min={0}
              max={5}
              step={0.05}
              style={{ width: 72 }}
              value={map3d?.relief?.amplitude_m ?? ''}
              onChange={(e) => {
                const v = Number(e.target.value)
                if (!e.target.value.trim() || !Number.isFinite(v) || v <= 0) {
                  onMap3d('relief', undefined)
                  return
                }
                onMap3d('relief', {
                  ...map3d?.relief,
                  amplitude_m: v,
                  seed: map3d?.relief?.seed
                    ?? crypto.getRandomValues(new Uint32Array(1))[0],
                })
              }}
            />
            {map3d?.relief ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                title={t('Roll a new height field — same amplitude, different hills.')}
                onClick={() => onMap3d('relief', {
                  ...map3d.relief!,
                  seed: crypto.getRandomValues(new Uint32Array(1))[0],
                })}
              >
                🎲
              </button>
            ) : null}
          </label>
        ) : null}
        {/* The relief's SECOND axis: the amplitude says how high the ground
            swings, this says how far apart the swells sit. Without it the
            only way to get more relief was a steeper version of the same 16
            humps — past half a metre that reads as a ploughed field. */}
        {onMap3d && map3d?.area_detail && map3d?.relief ? (
          <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Wave width: how wide ONE ground swell is, in real metres. Small values make a choppy, ploughed-field look, large values make long, gentle rolls. Empty = the default of 16 swells across the plan.')}>
            〰
            <span>{t('Wave (m)')}</span>
            <input
              className="ga-input"
              type="number"
              min={1}
              max={200}
              step={1}
              style={{ width: 72 }}
              placeholder={reliefWaveDefaultM ? String(reliefWaveDefaultM) : ''}
              value={map3d.relief.wave_m ?? ''}
              onChange={(e) => {
                const v = Number(e.target.value)
                // Clamped to the SERVER's window (1…200 m, 2 decimals — the
                // relief block of _sanitize_map3d). `min`/`max` do not stop a
                // typed value, and the sanitizer drops a wave width outside
                // its window entirely, falling back to the default grid — so
                // an unclamped 0.5 would let the caption promise swells the
                // server never builds.
                const wave = e.target.value.trim() && Number.isFinite(v) && v > 0
                  ? Math.round(Math.min(200, Math.max(1, v)) * 100) / 100
                  : undefined
                onMap3d('relief', { ...map3d.relief!, wave_m: wave })
              }}
            />
            <span style={{ opacity: 0.7 }}>
              {reliefSwells
                ? (map3d.relief.wave_m
                  ? t('≈ {n} swells across the {w} m plan')
                  : t('default: ≈ {n} swells across the {w} m plan'))
                  .replace('{n}', String(reliefSwells))
                  .replace('{w}', String(planW))
                : t('Set the plan width to see what a wave width means here.')}
            </span>
          </label>
        ) : null}
      </div>

      {/* Scale anchor missing: floor-plan geometry has no real size without
          it, so the tools are locked until the plan width is set here (or a
          building model declares its height). Pure viewing stays free. */}
      {planW <= 0 && onMap3d ? (
        <div className="ga-anchor-banner">
          <span style={{ flex: 1, minWidth: 200 }}>
            ⚠ {t('No scale anchor — the 3D client falls back to a legacy scale (24 m plan width) that does not match the storey height.')}
            {anchorMissing
              ? ' ' + t('The layouts already drawn here are affected.')
              : ''}
          </span>
          <label className="ga-check-row"
            title={t('Real-world width the floor-plan square represents. With a building model that declares a height the value is derived automatically — set one here only when there is no model.')}>
            <span>📐 {t('Plan width (m)')}</span>
            <input
              className="ga-input"
              type="number"
              min={0.5}
              max={500}
              step={0.5}
              style={{ width: 80 }}
              value={map3d?.plan_width_m ?? ''}
              onChange={(e) => {
                const n = parseFloat(e.target.value)
                onMap3d('plan_width_m', Number.isFinite(n) && n > 0 ? n : undefined)
              }}
            />
          </label>
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

      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <PlanToolbar
        mode={clickMode}
        hasSelection={!!selectedRoom}
        selectionRotation={selectedRoom?.layout?.rotation || 0}
        hasExit={!!selectedRoom?.layout?.exit}
        hasOutline={!!map3d?.outline?.length}
        outlineDraftLen={outlineDraft.length}
        hasElevator={!!map3d?.elevator}
        building={!!onMap3d}
        noAnchor={planW <= 0}
        canSuggest={placed.length > 0}
        canFitToModel={!!(selectedRoom?.id && planW > 0
          && (modelDims[selectedRoom.id]?.widthM || 0) > 0)}
        canCurve={!!selectedRoom?.layout?.outline?.length}
        onFitToModel={fitToModel}
        propsOpen={propsOpen}
        onMode={armMode}
        onRotate={rotateSelected}
        onUnplace={() => { updateLayout(selectedRoom?.id || '', null); setSelected('') }}
        onRemoveExit={() => updateLayout(selectedRoom?.id || '', { exit: undefined })}
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
            // Placement ghost — raw cursor, no snapping (v1).
            const rect = (canvasRef.current as HTMLDivElement).getBoundingClientRect()
            setPropGhost([clamp((e.clientX - rect.left) / rect.width, 0, 1),
                          clamp((e.clientY - rect.top) / rect.height, 0, 1)])
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
              && clickMode !== 'elevator' && clickMode !== 'boundary-door') return
          e.stopPropagation()
          if (clickMode === 'outline' || clickMode === 'draw-room') {
            // Clicks go through the snap engine (Shift = free-hand); landing on
            // the first vertex closes the polygon.
            const res = computeSnap(e.clientX, e.clientY, e.shiftKey)
            if (res.kind === 'close') {
              if (clickMode === 'outline') commitOutline()
              else commitRoomDraft()
            } else {
              setOutlineDraft((prev) => [...prev, res.p])
            }
          } else if (clickMode === 'boundary-door') {
            // Pass-through at the LOCATION edge (plan-area-detail-scenes.md):
            // snap the click to the nearest frame edge; `at` follows the
            // room-opening letter convention (left→right on N/S, top→bottom
            // on E/W).
            const rect = (canvasRef.current as HTMLDivElement).getBoundingClientRect()
            const fx = clamp((e.clientX - rect.left) / rect.width, 0, 1)
            const fy = clamp((e.clientY - rect.top) / rect.height, 0, 1)
            const cur = map3d?.boundary_openings || []
            if (cur.length >= 8) {
              toast(t('At most 8 boundary pass-throughs per location.'), 'error')
            } else {
              const cand = [
                { edge: 'N' as const, dist: fy, at: fx },
                { edge: 'E' as const, dist: 1 - fx, at: fy },
                { edge: 'S' as const, dist: 1 - fy, at: fx },
                { edge: 'W' as const, dist: fx, at: fy },
              ].sort((a, b) => a.dist - b.dist)[0]
              onMap3d?.('boundary_openings', [...cur, {
                edge: cand.edge, at: r4(cand.at), width_m: 3,
                type: 'passage' as const,
              }])
              setSelectedBoundary(cur.length)
            }
            setClickMode('')
          } else {
            const rect = (canvasRef.current as HTMLDivElement).getBoundingClientRect()
            onMap3d?.('elevator', [
              r4(clamp((e.clientX - rect.left) / rect.width, 0, 1)),
              r4(clamp((e.clientY - rect.top) / rect.height, 0, 1))])
            setClickMode('')
          }
        }}
      >
        {/* Building outline (existing + draft) + snap feedback as an SVG
            overlay. */}
        {(map3d?.outline?.length || outlineDraft.length
          || map3d?.boundary_openings?.length
          || (hoverSnap && (clickMode === 'outline' || clickMode === 'draw-room'))
          || (armedProp && propGhost)) ? (
          <svg viewBox="0 0 100 100" preserveAspectRatio="none"
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
            {/* Boundary pass-throughs: gold bars ON the frame edge — the
                only overlay children that take pointer events (select). */}
            {(map3d?.boundary_openings || []).map((bo, i) => {
              const half = (bo.width_m / (planW || 8)) * 50
              const horiz = bo.edge === 'N' || bo.edge === 'S'
              const cx = horiz ? bo.at * 100 : (bo.edge === 'E' ? 100 : 0)
              const cy = horiz ? (bo.edge === 'S' ? 100 : 0) : bo.at * 100
              return (
                <rect key={`bo-${i}`}
                  x={horiz ? cx - half : cx - 1.2}
                  y={horiz ? cy - 1.2 : cy - half}
                  width={horiz ? half * 2 : 2.4}
                  height={horiz ? 2.4 : half * 2}
                  fill="#e0a356" opacity={selectedBoundary === i ? 1 : 0.7}
                  style={{ pointerEvents: 'auto', cursor: 'pointer' }}
                  onClick={(ev) => { ev.stopPropagation(); setSelectedBoundary(i) }}
                >
                  <title>{`${bo.edge} · ${bo.width_m} m`}</title>
                </rect>
              )
            })}
            {map3d?.outline?.length ? (
              <polygon
                points={map3d.outline.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')}
                fill="rgba(88,166,255,0.07)" stroke="#58a6ff" strokeWidth={0.6}
              />
            ) : null}
            {outlineDraft.length ? (
              <polyline
                points={outlineDraft.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')}
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
                    <line x1={last[0] * 100} y1={last[1] * 100}
                      x2={hoverSnap.p[0] * 100} y2={hoverSnap.p[1] * 100}
                      stroke="#e0a356" strokeWidth={0.6} />
                  ) : null}
                  {(outlineDraft.length >= 2 || hoverSnap) ? (
                    <line x1={cur[0] * 100} y1={cur[1] * 100}
                      x2={first[0] * 100} y2={first[1] * 100}
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
                  <line x1={hoverSnap.guide.a[0] * 100} y1={hoverSnap.guide.a[1] * 100}
                    x2={hoverSnap.guide.b[0] * 100} y2={hoverSnap.guide.b[1] * 100}
                    stroke="#58a6ff" strokeWidth={0.35}
                    strokeDasharray="1 1" opacity={0.8} />
                ) : null}
                {hoverSnap.seg ? (
                  <line x1={hoverSnap.seg.a[0] * 100} y1={hoverSnap.seg.a[1] * 100}
                    x2={hoverSnap.seg.b[0] * 100} y2={hoverSnap.seg.b[1] * 100}
                    stroke="#58a6ff" strokeWidth={0.9} opacity={0.9} />
                ) : null}
                {hoverSnap.kind === 'vertex' || hoverSnap.kind === 'close' ? (
                  <circle cx={hoverSnap.p[0] * 100} cy={hoverSnap.p[1] * 100}
                    r={hoverSnap.kind === 'close' ? 2.2 : 1.6} fill="none"
                    stroke="#58a6ff" strokeWidth={0.5} />
                ) : null}
                {hoverSnap.kind === 'length' && hoverSnap.matchLen && hoverSnap.guide ? (
                  <text
                    x={(hoverSnap.guide.a[0] + hoverSnap.guide.b[0]) / 2 * 100}
                    y={(hoverSnap.guide.a[1] + hoverSnap.guide.b[1]) / 2 * 100 - 1.5}
                    fontSize={3} fill="#3fb950" textAnchor="middle"
                    style={{ paintOrder: 'stroke', stroke: '#0d1117', strokeWidth: 0.6 }}>
                    {`= ${(hoverSnap.matchLen * (planW || 8)).toFixed(1)} m`}
                  </text>
                ) : null}
              </>
            ) : null}
            {outlineDraft.map(([x, y], i) => (
              <circle key={i} cx={x * 100} cy={y * 100} r={1.1} fill="#e0a356" />
            ))}
            {/* Placement ghost: the armed prop's TRUE footprint (dims / plan
                width) under the cursor, rotated by the R-key yaw. */}
            {armedProp && propGhost ? (() => {
              const dims = propDims[armedProp]
              const planWEff = planW || 8
              const gw = ((dims?.width_m || 1) / planWEff) * 100
              const gd = ((dims?.depth_m || 1) / planWEff) * 100
              return (
                <g transform={`translate(${propGhost[0] * 100} ${propGhost[1] * 100}) rotate(${ghostYaw})`}
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
        ) : null}
        {(underlay || bUnderlay) && underlayUrl ? (
          <img src={underlayUrl} alt="" style={{
            position: 'absolute', inset: 0, width: '100%', height: '100%',
            opacity: 0.9, pointerEvents: 'none',
          }} />
        ) : null}
        {aids ? (
          <PlanMetreGrid planWidthM={planW} canvasPx={canvasPx} />
        ) : null}
        {placed.map((room) => {
          const lay = room.layout!
          const isSel = room.id === selected
          // Holes owned by a NEIGHBOUR that pierce this room's wall too:
          // WHICH ones and WHERE is the server's answer (scene payload, plan
          // fractions) — the editor only draws them and routes a click to
          // the owning room.
          const sceneRoom = sceneRooms.get(room.id || '')
          const mirrored = (sceneRoom?.openings || []).filter((o) => o.mirrored)
          return (
            <div
              key={room.id}
              onPointerDown={(e) => startDrag(e, room, 'move')}
              onClick={(e) => {
                e.stopPropagation()
                if (clickMode || armedProp) onRoomClick(e, room)
                else if (room.id && room.id === calibrationRoomId) onRoomClick(e, room)
                else setSelected(room.id || '')
              }}
              title={room.name || room.id}
              style={{
                position: 'absolute',
                left: `${lay.x * 100}%`, top: `${lay.y * 100}%`,
                width: `${lay.w * 100}%`, height: `${lay.d * 100}%`,
                // A drawn hull renders as its polygon (SVG below) — the div
                // stays the bbox for selection/drag but hides its rectangle.
                border: lay.outline?.length ? 'none'
                  : `2px solid ${isSel ? 'var(--accent, #58a6ff)' : 'rgba(139,148,158,0.7)'}`,
                background: lay.outline?.length ? 'transparent'
                  : isSel ? 'rgba(88,166,255,0.18)' : 'rgba(139,148,158,0.12)',
                borderRadius: 4, boxSizing: 'border-box',
                cursor: clickMode ? 'crosshair' : 'move', userSelect: 'none',
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
                    let d = `M ${pts[0][0] * 100},${pts[0][1] * 100}`
                    for (let i = 0; i < pts.length; i++) {
                      const q = pts[(i + 1) % pts.length]
                      const c = curves.get(i)
                      d += c
                        ? ` Q ${c[0] * 100},${c[1] * 100} ${q[0] * 100},${q[1] * 100}`
                        : ` L ${q[0] * 100},${q[1] * 100}`
                    }
                    return (
                      <path d={d + ' Z'}
                        fill={isSel ? 'rgba(88,166,255,0.18)' : 'rgba(139,148,158,0.12)'}
                        stroke={isSel ? 'var(--accent, #58a6ff)' : 'rgba(139,148,158,0.7)'}
                        strokeWidth={2} vectorEffect="non-scaling-stroke"
                      />
                    )
                  })()}
                  {isSel ? (lay.outline_curves || []).map((cv) => {
                    const { a, b } = edgeSegment(outlineOf(lay), cv.edge)
                    return (
                      <g key={cv.edge} opacity={0.6}>
                        <line x1={a[0] * 100} y1={a[1] * 100}
                          x2={cv.c[0] * 100} y2={cv.c[1] * 100}
                          stroke="#e0a356" strokeWidth={1}
                          strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
                        <line x1={b[0] * 100} y1={b[1] * 100}
                          x2={cv.c[0] * 100} y2={cv.c[1] * 100}
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
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    position: 'absolute',
                    left: `${cv.c[0] * 100}%`, top: `${cv.c[1] * 100}%`,
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
                {room.name || room.id}
                {lay.rotation ? ` ↻${lay.rotation}°` : ''}
              </span>
              {/* The value ON the stretch it means: what this rectangle is in
                  REAL metres. Hidden when the room is too small on screen to
                  hold the text, and absent without a scale anchor. */}
              {planW > 0 && lay.w * canvasPx >= 52 && lay.d * canvasPx >= 26 ? (
                <span
                  title={lay.outline?.length
                    ? t('Bounding box of the room hull in real metres.')
                    : t('Room size in real metres.')}
                  style={{
                    position: 'absolute', left: 3, bottom: 2, fontSize: 9,
                    lineHeight: '11px', cursor: 'inherit',
                    opacity: isSel ? 0.95 : 0.55,
                    textShadow: '0 0 3px #0d1117, 0 0 3px #0d1117',
                  }}
                >
                  {fmtM(lay.w * planW)} × {fmtM(lay.d * planW)} m
                </span>
              ) : null}
              {lay.exit ? (
                <span
                  title={t('Exit point (override)')}
                  style={{
                    position: 'absolute',
                    left: `calc(${lay.exit[0] * 100}% - 5px)`,
                    top: `calc(${lay.exit[1] * 100}% - 5px)`,
                    width: 10, height: 10, borderRadius: '50%',
                    background: '#e0a356', border: '1px solid #0d1117',
                    pointerEvents: 'none',
                  }}
                />
              ) : (() => {
                // No explicit exit: the payload's DERIVED one — an absolute
                // plate fraction (exit_derived flags the frame), converted
                // into the room-local fractions this markup positions with.
                const src = sceneRoom?.exit_derived ? sceneRoom.exit : null
                const auto: [number, number] | null = src
                  ? [clamp((src[0] - lay.x) / (lay.w || 1), 0, 1),
                     clamp((src[1] - lay.y) / (lay.d || 1), 0, 1)]
                  : null
                return auto ? (
                  <span
                    title={t('Exit (auto — derived from the door)')}
                    style={{
                      position: 'absolute',
                      left: `calc(${auto[0] * 100}% - 5px)`,
                      top: `calc(${auto[1] * 100}% - 5px)`,
                      width: 10, height: 10, borderRadius: '50%',
                      border: '2px dashed #e0a356', boxSizing: 'border-box',
                      opacity: 0.8, pointerEvents: 'none',
                    }}
                  />
                ) : null
              })()}
              {/* Diorama-model anchor: positioned in the PLAN like a prop
                  (layout.model_at, default = centre). Drag moves it; the
                  strip below fine-tunes X/Y/height. */}
              {room.id === selected && modelDims[room.id] ? (() => {
                const mAt = lay.model_at || [0.5, 0.5]
                return (
                  <span
                    title={t('Room model anchor — drag it like a prop; fine-tune X/Y/height in the strip below.')}
                    onPointerDown={(e) => {
                      if (clickMode || armedProp || !room.id) return
                      e.preventDefault()
                      e.stopPropagation()
                      dragRef.current = { kind: 'model', roomId: room.id }
                    }}
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      position: 'absolute',
                      left: `calc(${mAt[0] * 100}% - 9px)`,
                      top: `calc(${mAt[1] * 100}% - 9px)`,
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
              {(lay.markers || []).map((m, i) => (
                <span
                  key={`${m.animation}-${i}`}
                  title={`${i + 1} · ${m.animation}`}
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => {
                    e.stopPropagation()
                    if (clickMode) return
                    setSelected(room.id || '')
                    setMarkerSel(i)
                  }}
                  style={{
                    position: 'absolute',
                    left: `calc(${m.at[0] * 100}% - 5px)`,
                    top: `calc(${m.at[1] * 100}% - 5px)`,
                    width: 10, height: 10, borderRadius: '50%',
                    background: '#3fb950',
                    border: `2px solid ${room.id === selected && markerSel === i ? '#fff' : '#0d1117'}`,
                    cursor: 'pointer',
                  }}
                />
              ))}
              {/* Placed props: TRUE-size footprints (dims / plan width, never
                  fit-scaled) at their room-local spot, rotated by yaw. Click
                  selects, drag moves; fine-tuning in the strip below. */}
              {(lay.props || []).map((p, i) => {
                const dims = propDims[p.prop_id]
                const planWEff = planW || 8
                const fw = ((dims?.width_m || 1) / planWEff) / (lay.w || 1) * 100
                const fd = ((dims?.depth_m || 1) / planWEff) / (lay.d || 1) * 100
                const sel = room.id === selected && propSel === i
                return (
                  <div
                    key={`prop-${i}`}
                    title={`${dims?.name || p.prop_id}${dims ? `\n${dims.width_m}×${dims.depth_m}×${dims.height_m} m` : ` · ${t('unknown prop')}`}`}
                    onPointerDown={(e) => startPropDrag(e, room, i)}
                    onClick={(e) => {
                      if (clickMode || armedProp) return
                      e.stopPropagation()
                      setSelected(room.id || '')
                      // Stacked footprints: repeated clicks cycle through
                      // everything under the cursor (topmost first).
                      const host = e.currentTarget.parentElement as HTMLDivElement
                      const rect = host.getBoundingClientRect()
                      const hits = propsAtPoint(lay,
                        (e.clientX - rect.left) / rect.width,
                        (e.clientY - rect.top) / rect.height)
                      if (hits.length < 2) {
                        setPropSel(i)
                        return
                      }
                      const pos = room.id === selected && propSel !== null
                        ? hits.indexOf(propSel) : -1
                      setPropSel(pos >= 0
                        ? hits[(pos + 1) % hits.length]
                        : hits[hits.length - 1])
                    }}
                    style={{
                      position: 'absolute',
                      left: `${p.at[0] * 100}%`, top: `${p.at[1] * 100}%`,
                      width: `${fw}%`, height: `${fd}%`,
                      transform: `translate(-50%, -50%) rotate(${p.yaw || 0}deg)`,
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
                  const planWEff = planW || 8
                  const fw = ((dims?.width_m || 1) / planWEff) / (lay.w || 1) * 100
                  const fd = ((dims?.depth_m || 1) / planWEff) / (lay.d || 1) * 100
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
                        left: `${p.at[0] * 100}%`, top: `${p.at[1] * 100}%`,
                        width: `${fw}%`, height: `${fd}%`,
                        transform: `translate(-50%, -50%) rotate(${p.yaw || 0}deg)`,
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
                // Screen angle needs the room's pixel aspect (w vs d — the
                // canvas itself is square), or diagonals of non-square rooms
                // would skew.
                const deg = Math.atan2((seg.b[1] - seg.a[1]) * lay.d,
                                       (seg.b[0] - seg.a[0]) * lay.w) * 180 / Math.PI
                const sel = room.id === selected && openingSel === i
                const col = sel ? '#fff' : (OPENING_COLOR[op.type] || '#e0a356')
                // TRUE width: the symbol spans the opening's real width_m
                // (isotropic — px lengths survive the rotation), floor 14px
                // so tiny openings stay clickable.
                const wPct = ((op.width_m || 1) / (planW || 8)) / (lay.w || 1) * 100
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
                      left: `${pt.x * 100}%`, top: `${pt.y * 100}%`,
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
                const deg = Math.atan2((seg.b[1] - seg.a[1]) * lay.d,
                                       (seg.b[0] - seg.a[0]) * lay.w) * 180 / Math.PI
                const mwPct = ((op.width_m || 1) / (planW || 8)) / (lay.w || 1) * 100
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
                      left: `${pt.x * 100}%`, top: `${pt.y * 100}%`,
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
              {room.id && !lay.outline?.length && derivedSize(room.id) ? null : (
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
          // 1.8 REAL metres, so its share of the plan square is 1.8 / plan
          // width — frame-independent, the extent cancels out. On top of the
          // rooms so it stays clickable; click selects it for the sliders.
          const frac = Math.min(planW > 0 ? 1.8 / planW : 0.18, 0.5)
          return (
            <div
              title={t('Elevator (all levels) — true shaft size from above (1.8 m × figure scale). Click to fine-tune with the sliders below.')}
              onClick={(e) => {
                if (clickMode) return
                e.stopPropagation()
                setElevatorSel(true)
                setMarkerSel(null)
              }}
              style={{
                position: 'absolute',
                left: `${(map3d.elevator![0] - frac / 2) * 100}%`,
                top: `${(map3d.elevator![1] - frac / 2) * 100}%`,
                width: `${frac * 100}%`, height: `${frac * 100}%`,
                background: 'rgba(139,148,158,0.5)',
                border: elevatorSel ? '2px solid #fff' : '1px solid #8b949e',
                borderRadius: 2, boxSizing: 'border-box',
                cursor: clickMode ? 'crosshair' : 'pointer',
              }}
            />
          )
        })() : null}
        {placed.length === 0 ? (
          <span className="ga-hint" style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center', pointerEvents: 'none',
          }}>
            {t('No rooms on this level yet — click a room below to place it.')}
          </span>
        ) : null}
        {/* Topmost aid: the person is what everything else is compared to. */}
        {aids ? (
          <PlanFigure planWidthM={planW} pos={figurePos} onPos={setFigurePos}
            canvasRef={canvasRef} interactive={!clickMode && !armedProp} />
        ) : null}
      </div>
      </div>
      <PlanScaleBar planWidthM={planW} canvasPx={canvasPx} />
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
              <span>⚠ {t('No pass-through: this location cannot be entered. Add one below.')}</span>
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
                <span style={{ width: 16, textAlign: 'center' }}>{bo.edge}</span>
                <input className="ga-input" type="number" min={0} max={1}
                  step={0.01} style={{ width: 64 }} value={bo.at}
                  title={t('Position along the edge (0..1)')}
                  onChange={(e) => {
                    const v = Number(e.target.value)
                    if (Number.isFinite(v)) write({ at: r4(clamp(v, 0, 1)) })
                  }} />
                {/* The pass-through lies ON the location edge, so the edge is
                    its maximum: plan_width_m metres (the reference square is
                    a square). Without the anchor the server's 10 m fallback
                    applies — the same rule on both sides. */}
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
        clipKinds={clipKinds}
        markerKind={markerKind}
        onMarkerKind={setMarkerKind}
        markerSel={markerSel}
        onSelectMarker={setMarkerSel}
        markerMode={clickMode === 'marker'}
        onArmMarker={() => armMode('marker')}
        onAlwaysVisible={(v) => updateLayout(selectedRoom?.id || '', {
          always_visible: v || undefined,
        })}
        onReliefFlat={(v) => updateLayout(selectedRoom?.id || '', {
          relief_flat: v || undefined,
        })}
        onFloorOffset={(v) => updateLayout(selectedRoom?.id || '', {
          floor_offset_y: v,
        })}
        surfaceKinds={surfaceKinds}
        onSurface={setSurface}
        furnishState={furnish.status?.state || ''}
        furnishDisabled={!selectedRoom || planW <= 0}
        furnishHint={!selectedRoom
          ? t('Select a room with a floor plan first.')
          : planW <= 0
            ? t('Set the plan width (m) first — without a scale anchor the room has no real size.')
            : t('Let the LLM furnish this room: it picks library props, proposes the missing pieces and a solver places them.')}
        onFurnish={() => setFurnishOpen(true)}
        noAnchor={planW <= 0}
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
          roomId={selectedRoom.id || ''}
          roomName={selectedRoom.name || selectedRoom.id || ''}
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
        return (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ fontWeight: 600 }}>
              🪑 {dims?.name || placement.prop_id}:
            </span>
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Fine-tune the position (fraction of the room rectangle).')}>
              X
              <input
                type="range" min={0} max={1} step={0.005}
                value={placement.at[0]}
                onChange={(e) => patchProp({
                  at: [r4(parseFloat(e.target.value) || 0), placement.at[1]] as [number, number],
                })}
                style={{ width: 100 }}
              />
              <span style={{ minWidth: 40 }}>{placement.at[0].toFixed(3)}</span>
            </label>
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Fine-tune the position (fraction of the room rectangle).')}>
              Y
              <input
                type="range" min={0} max={1} step={0.005}
                value={placement.at[1]}
                onChange={(e) => patchProp({
                  at: [placement.at[0], r4(parseFloat(e.target.value) || 0)] as [number, number],
                })}
                style={{ width: 100 }}
              />
              <span style={{ minWidth: 40 }}>{placement.at[1].toFixed(3)}</span>
            </label>
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Yaw in degrees — free values; R while placing steps 90°.')}>
              ↻
              <input
                type="range" min={0} max={359.5} step={0.5}
                value={placement.yaw || 0}
                onChange={(e) => {
                  const v = Math.round((parseFloat(e.target.value) || 0) * 10) / 10
                  patchProp({ yaw: v || undefined })
                }}
                style={{ width: 120 }}
              />
              <span style={{ minWidth: 44 }}>{(placement.yaw || 0).toFixed(1)}°</span>
            </label>
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
            {/* Scatter (v5.2 Nr. 12): a placement property — this anchor
                throws `scatter_count` copies over the room from its own
                seed; spacing alone rules the density (0 = may overlap). */}
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Scatter: throw copies of THIS prop over the room area. The placement stays as the anchor; positions come from the seed — the road, openings and markers stay clear.')}>
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
          </div>
        )
      })() : null}

      {/* Model calibration strip (rotation fix, room width, walkable floor)
          — placed BEFORE the model-placement strip so the three calibration
          anchors read in order: width_m → walk_y → model_offset_y. */}
      {children}

      {/* Model-placement strip: X/Y sliders + height for the selected
          room's diorama model — mirrors the prop strip; ↺ recentres. */}
      {selectedRoom && selectedRoom.layout && modelDims[selectedRoom.id || ''] ? (() => {
        const lay = selectedRoom.layout
        const mAt = lay.model_at || [0.5, 0.5]
        const setAt = (axis: 0 | 1, v: number) => {
          const next: [number, number] = [mAt[0], mAt[1]]
          next[axis] = r4(clamp(v, 0, 1))
          updateLayout(selectedRoom.id || '', { model_at: next })
        }
        return (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ fontWeight: 600 }}>
              ⌂ {t('Model placement')}:
            </span>
            {(['X', 'Y'] as const).map((label, axis) => (
              <label key={label} style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}>
                {label}
                <input type="range" min={0} max={1} step={0.005}
                  value={mAt[axis]}
                  style={{ width: 110 }}
                  onChange={(e) => setAt(axis as 0 | 1, e.target.valueAsNumber)} />
                <input className="ga-input" type="number" min={0} max={1} step={0.005}
                  style={{ width: 72 }} value={mAt[axis]}
                  onChange={(e) => setAt(axis as 0 | 1, Number(e.target.value) || 0)} />
              </label>
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
            {/* Walls opt-out: open zones, pavilions, areas inside an area
                model. The UI is positive ("render walls"), the stored field
                is negative — so the default (no field) means walls. Shown for
                outdoor rooms too: an open zone with window openings in the
                plan should still be able to render wall-less. */}
            <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Off: this room gets no walls at all — no segments, no window sill or head, no glass. Its floor, exit and openings stay (the plan keeps drawing them), and the building outline is unaffected.')}>
              <input type="checkbox"
                checked={!lay.no_walls}
                onChange={(e) => updateLayout(selectedRoom.id || '', {
                  no_walls: e.target.checked ? undefined : true,
                })} />
              {t('Render walls')}
            </label>
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
        return (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ fontWeight: 600 }}>
              🎯 {markerSel + 1} · {marker.animation}:
            </span>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'marker-move' ? ' ga-btn-primary' : ''}`}
              onClick={() => setClickMode((m) => (m === 'marker-move' ? '' : 'marker-move'))}
              title={t('Then click inside the room to move this marker there.')}
            >
              ✥ {clickMode === 'marker-move' ? t('Click into the room…') : t('Move')}
            </button>
            {/* Fine X/Y correction after the coarse mouse placement. */}
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Fine-tune the marker position (fraction of the room rectangle).')}>
              X
              <input
                type="range"
                min={0}
                max={1}
                step={0.005}
                value={marker.at[0]}
                onChange={(e) => patchMarker({
                  at: [r4(parseFloat(e.target.value) || 0), marker.at[1]] as [number, number],
                })}
                style={{ width: 100 }}
              />
              <input
                className="ga-input"
                type="number"
                min={0}
                max={1}
                step={0.001}
                value={marker.at[0]}
                onChange={(e) => patchMarker({
                  at: [r4(parseFloat(e.target.value) || 0), marker.at[1]] as [number, number],
                })}
                style={{ width: 74 }}
              />
            </label>
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Fine-tune the marker position (fraction of the room rectangle).')}>
              Y
              <input
                type="range"
                min={0}
                max={1}
                step={0.005}
                value={marker.at[1]}
                onChange={(e) => patchMarker({
                  at: [marker.at[0], r4(parseFloat(e.target.value) || 0)] as [number, number],
                })}
                style={{ width: 100 }}
              />
              <input
                className="ga-input"
                type="number"
                min={0}
                max={1}
                step={0.001}
                value={marker.at[1]}
                onChange={(e) => patchMarker({
                  at: [marker.at[0], r4(parseFloat(e.target.value) || 0)] as [number, number],
                })}
                style={{ width: 74 }}
              />
            </label>
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Facing of the figure (0 south, 90 east, 180 north, 270 west; — = face the neighbours).')}>
              🧭
              <input
                type="range"
                min={0}
                max={359}
                step={1}
                value={fac ?? 0}
                onChange={(e) => patchMarker({ rotation: parseInt(e.target.value, 10) || 0 })}
                style={{ width: 120 }}
              />
              <input
                className="ga-input"
                type="number"
                min={0}
                max={359}
                step={1}
                value={fac ?? ''}
                placeholder="—"
                onChange={(e) => {
                  const n = parseInt(e.target.value, 10)
                  patchMarker({ rotation: Number.isFinite(n) ? n : undefined })
                }}
                style={{ width: 62 }}
              />
              <span style={{ minWidth: 34 }}>
                {fac !== undefined && FACING[fac] ? FACING[fac] : ''}
              </span>
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
            </label>
            <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Additive to the seat height the client samples under the marker.')}>
              {t('Height offset (m)')}
              <input
                type="range"
                min={-1}
                max={1}
                step={0.01}
                value={marker.offset_y ?? 0}
                onChange={(e) => {
                  const v = Math.round(parseFloat(e.target.value) * 100) / 100
                  patchMarker({ offset_y: v === 0 ? undefined : v })
                }}
                style={{ width: 120 }}
              />
              <input
                className="ga-input"
                type="number"
                min={-1}
                max={1}
                step={0.01}
                value={marker.offset_y ?? 0}
                onChange={(e) => {
                  const v = Math.round((parseFloat(e.target.value) || 0) * 100) / 100
                  patchMarker({ offset_y: v === 0 ? undefined : v })
                }}
                style={{ width: 74 }}
              />
            </label>
            {/* Lean axes: a figure on a slope is not upright, and the compass
                alone cannot say that. Applied after the facing, in the
                figure's own frame. */}
            {([['tilt', '⤢', t('Tilt (°): head up (+) or down (−) — for lying or leaning figures.')],
              ['roll', '⤡', t('Roll (°): lean sideways — right (+) or left (−).')]] as const)
              .map(([key, icon, hint]) => (
                <label key={key} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
                  title={hint}>
                  {icon}
                  <input
                    type="range"
                    min={-90}
                    max={90}
                    step={1}
                    value={marker[key] ?? 0}
                    onChange={(e) => {
                      const v = Math.round(parseFloat(e.target.value) || 0)
                      patchMarker({ [key]: v === 0 ? undefined : v })
                    }}
                    style={{ width: 100 }}
                  />
                  <input
                    className="ga-input"
                    type="number"
                    min={-90}
                    max={90}
                    step={1}
                    value={marker[key] ?? 0}
                    onChange={(e) => {
                      const v = Math.round(parseFloat(e.target.value) || 0)
                      patchMarker({ [key]: v === 0 ? undefined : v })
                    }}
                    style={{ width: 62 }}
                  />
                </label>
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
          <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Fine-tune the elevator position (fraction of the reference square).')}>
            X
            <input
              type="range"
              min={0}
              max={1}
              step={0.005}
              value={map3d.elevator[0]}
              onChange={(e) => onMap3d?.('elevator',
                [r4(parseFloat(e.target.value) || 0), map3d.elevator![1]] as [number, number])}
              style={{ width: 100 }}
            />
            <span style={{ minWidth: 40 }}>{map3d.elevator[0].toFixed(3)}</span>
          </label>
          <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
            title={t('Fine-tune the elevator position (fraction of the reference square).')}>
            Y
            <input
              type="range"
              min={0}
              max={1}
              step={0.005}
              value={map3d.elevator[1]}
              onChange={(e) => onMap3d?.('elevator',
                [map3d.elevator![0], r4(parseFloat(e.target.value) || 0)] as [number, number])}
              style={{ width: 100 }}
            />
            <span style={{ minWidth: 40 }}>{map3d.elevator[1].toFixed(3)}</span>
          </label>
        </div>
      ) : null}

      {/* Pick a room WITHOUT touching the plan — small, overlapping or
          stacked rooms are hard to hit, and hitting them used to move them. */}
      {placedRooms.length ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ga-hint">{t('On the plan:')}</span>
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
              disabled={planW <= 0}
              onClick={() => {
                setSelected(room.id || '')
                setDrawTarget(room.id || '')
                setOutlineDraft([])
                setHoverSnap(null)
                setClickMode('draw-room')
              }}
              title={planW <= 0
                ? t('Set the plan width (m) first')
                : t('Draw this room on the current level — click to place points, click the first point to close, Shift = free-hand, Esc = cancel.')}
            >
              ⬠ {room.name || room.id}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
