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
  edgeSegment, exteriorEdges, nearestPolygonEdge, normalizeOpeningEdge,
  outlineOf, r4, rotateOpeningCW, sharedEdges, snapDrawPoint,
} from './planGeometry'
import type { EdgeLetter, PolyRoom, SnapResult } from './planGeometry'
import { PlanSidePanel } from './PlanSidePanel'
import { PlanToolbar } from './PlanToolbar'
import type { PlanMode } from './PlanToolbar'
import { getBuildingDims, getRoomModelDims, renderTopDownSnapshot } from './topDownSnapshot'
import type { Map3D, Room, RoomLayout, RoomOpening } from './worldTypes'

const CANVAS_W = 420

interface RoomLayoutEditorProps {
  rooms: Room[]
  onChange: (rooms: Room[]) => void
  /** Location id — the building-underlay + auto plan width need its model. */
  locationId?: string
  /** 2D icon rotation: yaw fallback for the building underlay. */
  fallbackYawDeg?: number
  /** Location map3d draft — the editor draws/edits the building outline and
   *  the elevator position (AV3D-12) in it. */
  map3d?: Map3D
  onMap3d?: <K extends keyof Map3D>(key: K, value: Map3D[K] | undefined) => void
  /** Reports the selected room id ('' = none) — the Floor-plan tab shows the
   *  model adjustment strip for it. */
  onSelectRoom?: (roomId: string) => void
  /** Rendered at the bottom INSIDE the editor's frame — the Floor-plan tab
   *  slots the model adjustment strip of the selected room here. */
  children?: ReactNode
}

type DragState =
  | { kind: 'move'; roomId: string; startX: number; startY: number; origX: number; origY: number }
  | { kind: 'resize'; roomId: string; startX: number; startY: number; origW: number; origD: number }
  | { kind: 'opening'; roomId: string; index: number; edge: number }
  | null

export function RoomLayoutEditor({ rooms, onChange, locationId = '', fallbackYawDeg = 0, map3d, onMap3d, onSelectRoom, children }: RoomLayoutEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [level, setLevel] = useState(0)
  const [selected, setSelectedRaw] = useState<string>('')
  const setSelected = useCallback((id: string) => {
    setSelectedRaw(id)
    setMarkerSel(null)
    setOpeningSel(null)
    setElevatorSel(false)
    onSelectRoom?.(id)
  }, [onSelectRoom])
  // Click-to-place modes: the next click inside the room sets the exit point,
  // drops an animation marker of the chosen kind, or places a wall opening on
  // the nearest edge.
  const [clickMode, setClickMode] = useState<PlanMode>('')
  // Prop palette open in the side panel (🪑 tool) — presentation only, the
  // placement logic is not part of this editor yet.
  const [propsOpen, setPropsOpen] = useState(false)
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
  // Top-down underlay: the placed room models rendered straight from above,
  // laid behind the rectangles — markers can be dropped on real furniture.
  const [underlay, setUnderlay] = useState(false)
  // Building layer behind the plan — the roof view is the real footprint,
  // for tracing the outline polygon.
  const [bUnderlay, setBUnderlay] = useState(false)
  const [underlayUrl, setUnderlayUrl] = useState('')
  const canvasRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState>(null)
  const roomsRef = useRef(rooms)
  roomsRef.current = rooms

  // The contract's reference surface is a fixed 8×8 m SQUARE — the canvas
  // is square too, whatever the building footprint says.
  const canvasH = CANVAS_W

  const placed = rooms.filter((r) => r.layout && (r.layout.level || 0) === level)
  const unplaced = rooms.filter((r) => !r.layout)
  const levels = Array.from(
    new Set(rooms.filter((r) => r.layout).map((r) => r.layout!.level || 0)),
  ).sort((a, b) => a - b)

  // Re-render the underlay (debounced — drags update per pointermove) when
  // the level or any placed geometry changes. Alignment comes for free: the
  // snapshot places models with the same layout fractions as the rectangles.
  const geomKey = JSON.stringify(rooms.filter((r) => r.layout).map((r) => [
    r.id, r.layout!.level || 0, r.layout!.x, r.layout!.y, r.layout!.w,
    r.layout!.d, r.layout!.rotation || 0,
  ]))
  useEffect(() => {
    if (!underlay && !bUnderlay) {
      setUnderlayUrl('')
      return
    }
    const tid = setTimeout(() => {
      renderTopDownSnapshot({
        rooms: roomsRef.current, level, includeRooms: underlay,
        building: bUnderlay && locationId
          ? { locationId, map3d, fallbackYawDeg }
          : undefined,
      })
        .then((url) => setUnderlayUrl(url || ''))
        .catch(() => setUnderlayUrl(''))
    }, 350)
    return () => clearTimeout(tid)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [underlay, bUnderlay, level, geomKey, locationId, fallbackYawDeg,
      map3d?.rotation, map3d?.size])

  // Anchored mode (map3d.plan_width_m set): room-rectangle sizes DERIVE
  // from the models' declared real width — long side = width_m /
  // plan_width_m, short side via the model's footprint aspect. Dims are
  // loaded per room once; rooms without model/width keep free resize.
  const [bDims, setBDims] = useState<{ heightM: number
    widthPerHeight: number } | null>(null)
  useEffect(() => {
    if (!locationId) return
    let stale = false
    getBuildingDims(locationId)
      .then((d) => { if (!stale && d) setBDims({ heightM: d.heightM, widthPerHeight: d.widthPerHeight }) })
      .catch(() => undefined)
    return () => { stale = true }
  }, [locationId])
  // ANY model mutation (panel, adjust strip, preview toolbar) lands here
  // via the generic refresh channel: refetch the fresh metas — plan width,
  // rect derivation and the underlay recompute from them.
  useEffect(() => {
    const onChanged = (e: Event) => {
      const det = (e as CustomEvent).detail as { locationId?: string; roomId?: string }
      if (det?.roomId) {
        const rid = det.roomId
        getRoomModelDims(rid)
          .then((d) => setModelDims((prev) => ({ ...prev, [rid]: d })))
          .catch(() => undefined)
      }
      if (det?.locationId === locationId) {
        getBuildingDims(locationId)
          .then((d) => setBDims(d ? { heightM: d.heightM, widthPerHeight: d.widthPerHeight } : null))
          .catch(() => undefined)
      }
    }
    window.addEventListener('anima-model3d-changed', onChanged)
    return () => window.removeEventListener('anima-model3d-changed', onChanged)
  }, [locationId])
  // Explicit anchor wins; otherwise auto-derived from the building model
  // (declared height × the mesh's width-per-height ratio).
  const planW = map3d?.plan_width_m
    || (bDims && bDims.heightM > 0 ? bDims.heightM * bDims.widthPerHeight : 0)
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

  // Snapping while drawing (always on, Alt = free-hand): targets are the
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
      extraPoints: outlineDraft,
    })
  }, [clickMode, rooms, level, outlineDraft, drawTarget, map3d?.outline])

  const computeSnap = useCallback((clientX: number, clientY: number,
      alt: boolean): SnapResult => {
    const rect = (canvasRef.current as HTMLDivElement).getBoundingClientRect()
    const raw: [number, number] = [(clientX - rect.left) / rect.width,
                                   (clientY - rect.top) / rect.height]
    const planWEff = planW || 8
    const tol = Math.min(0.05, Math.max(SNAP_TOL_PX / CANVAS_W, 0.15 / planWEff))
    const prev = outlineDraft.length ? outlineDraft[outlineDraft.length - 1] : undefined
    const prev2 = outlineDraft.length >= 2 ? outlineDraft[outlineDraft.length - 2] : undefined
    return snapDrawPoint(raw, {
      prev,
      prevDir: prev && prev2 ? [prev[0] - prev2[0], prev[1] - prev2[1]] : undefined,
      first: outlineDraft[0],
      draftLen: outlineDraft.length,
      targets: snapTargets || { points: [], segments: [] },
      tol,
      closeTol: CLOSE_TOL_PX / CANVAS_W,
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
  // mode toggle go through here.
  const cancelDraw = useCallback(() => {
    setClickMode('')
    setOutlineDraft([])
    setHoverSnap(null)
    setDrawTarget('')
  }, [])

  // Esc cancels any armed mode and the current draft.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cancelDraw()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [cancelDraw])

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
        const dx = (e.clientX - drag.startX) / canvas.clientWidth
        const dy = (e.clientY - drag.startY) / canvas.clientHeight
        updateLayout(drag.roomId, {
          x: r4(clamp(drag.origX + dx, 0, 1 - lay.w)),
          y: r4(clamp(drag.origY + dy, 0, 1 - lay.d)),
        })
      } else if (drag.kind === 'resize') {
        const dx = (e.clientX - drag.startX) / canvas.clientWidth
        const dy = (e.clientY - drag.startY) / canvas.clientHeight
        updateLayout(drag.roomId, {
          w: r4(clamp(drag.origW + dx, MIN_FRAC, 1 - lay.x)),
          d: r4(clamp(drag.origD + dy, MIN_FRAC, 1 - lay.y)),
        })
      } else {
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

  // Click-to-place: one click inside a room sets the exit point or drops an
  // animation marker — both as fractions of the ROOM rectangle (contract).
  const onRoomClick = useCallback((e: React.MouseEvent, room: Room) => {
    if (!clickMode || !room.id || !room.layout) return
    e.stopPropagation()
    const target = e.currentTarget as HTMLDivElement
    const rect = target.getBoundingClientRect()
    const px = r4(clamp((e.clientX - rect.left) / rect.width, 0, 1))
    const py = r4(clamp((e.clientY - rect.top) / rect.height, 0, 1))
    if (clickMode === 'exit') {
      updateLayout(room.id, { exit: [px, py] })
    } else if (clickMode === 'marker-move') {
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
    } else if (clickMode === 'opening') {
      // Place a door on the nearest hull edge at the clicked position.
      const { edge, at } = nearestPolygonEdge(outlineOf(room.layout), [px, py])
      const openings: RoomOpening[] = [...(room.layout.openings || []),
        { edge, at, ...OPENING_DEFAULT }]
      updateLayout(room.id, { openings })
      setOpeningSel(openings.length - 1)
    }
    setClickMode('')
  }, [clickMode, markerKind, markerSel, selected, updateLayout])

  const selectedRoom = rooms.find((r) => r.id === selected && r.layout)

  // Arm a click mode from the toolbar (clicking the armed tool disarms it).
  // Drawing modes start with an empty draft; redrawing targets the selected
  // room — the "Not on the plan" chips arm the same mode for a new room.
  const armMode = useCallback((m: PlanMode) => {
    if (clickMode === m || !m) {
      cancelDraw()
      return
    }
    if (m === 'draw-room') {
      if (!selectedRoom?.id) return
      setDrawTarget(selectedRoom.id)
    }
    setOutlineDraft([])
    setHoverSnap(null)
    setClickMode(m)
  }, [clickMode, selectedRoom, cancelDraw])

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
      ...(lay.openings?.length
        ? { openings: lay.openings.map((o) => (typeof o.edge === 'string'
            ? { ...o, ...rotateOpeningCW(o.edge as EdgeLetter, o.at) }
            : lay.outline?.length ? o : { ...o, edge: (o.edge + 1) % 4 })) }
        : {}),
    })
  }

  // "Suggest openings": a door on every shared wall (once per pair, on the
  // room that triggers it, `to` = the neighbour) + a window on every exterior
  // edge ≥ 2.5 m. Suggestions are normal, editable openings; the button never
  // overwrites — it skips any edge that already carries an opening.
  const suggestOpenings = () => {
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
        for (const s of sharedEdges(hulls[i], [hulls[j]], planW)) {
          if (edgeTaken(hulls[i].id, s.edge)) continue
          add(hulls[i].id, { edge: s.edge, at: s.at, type: 'door',
            width_m: 1.0, height_m: 2.1, sill_m: 0, to: s.neighborId })
        }
      }
    }
    // Windows on exterior edges ≥ 2.5 m (needs planW to know the edge length).
    if (planW > 0) {
      for (const a of hulls) {
        const oa = absOutline(a)
        for (const e of exteriorEdges(a, hulls.filter((r) => r.id !== a.id), planW)) {
          const seg = edgeSegment(oa, e)
          const edgeLenM = Math.hypot(seg.b[0] - seg.a[0], seg.b[1] - seg.a[1]) * planW
          if (edgeLenM < MIN_WINDOW_EDGE_M || edgeTaken(a.id, e)) continue
          add(a.id, { edge: e, at: 0.5, type: 'window',
            width_m: 1.2, height_m: 1.2, sill_m: 0.9 })
        }
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
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <PlanToolbar
        mode={clickMode}
        hasSelection={!!selectedRoom}
        selectionRotation={selectedRoom?.layout?.rotation || 0}
        hasExit={!!selectedRoom?.layout?.exit}
        canMarker={clipKinds.length > 0}
        hasOutline={!!map3d?.outline?.length}
        outlineDraftLen={outlineDraft.length}
        hasElevator={!!map3d?.elevator}
        building={!!onMap3d}
        canSuggest={placed.length > 0}
        showModels={underlay}
        showBuilding={bUnderlay}
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
        onToggleModels={() => setUnderlay((v) => !v)}
        onToggleBuilding={() => setBUnderlay((v) => !v)}
        onProps={() => setPropsOpen((v) => !v)}
      />
      <div
        ref={canvasRef}
        style={{
          position: 'relative', width: CANVAS_W, height: canvasH, maxWidth: '100%',
          border: '1px solid var(--border, #30363d)', borderRadius: 6,
          background: 'rgba(255,255,255,0.03)', overflow: 'hidden', touchAction: 'none',
          cursor: clickMode ? 'crosshair' : undefined,
        }}
        onClick={() => { if (!clickMode) setSelected('') }}
        onPointerMove={(e) => {
          if (clickMode !== 'outline' && clickMode !== 'draw-room') return
          setHoverSnap(computeSnap(e.clientX, e.clientY, e.altKey))
        }}
        onPointerLeave={() => setHoverSnap(null)}
        onClickCapture={(e) => {
          // Canvas-level drawing/placement (outline or room hull points,
          // elevator) applies at CANVAS coordinates, also when the click
          // lands inside a room — capture phase keeps the room handlers out
          // of the way.
          if (clickMode !== 'outline' && clickMode !== 'draw-room'
              && clickMode !== 'elevator') return
          e.stopPropagation()
          if (clickMode === 'outline' || clickMode === 'draw-room') {
            // Clicks go through the snap engine (Alt = free-hand); landing on
            // the first vertex closes the polygon.
            const res = computeSnap(e.clientX, e.clientY, e.altKey)
            if (res.kind === 'close') {
              if (clickMode === 'outline') commitOutline()
              else commitRoomDraft()
            } else {
              setOutlineDraft((prev) => [...prev, res.p])
            }
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
          || (hoverSnap && (clickMode === 'outline' || clickMode === 'draw-room'))) ? (
          <svg viewBox="0 0 100 100" preserveAspectRatio="none"
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
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
              </>
            ) : null}
            {outlineDraft.map(([x, y], i) => (
              <circle key={i} cx={x * 100} cy={y * 100} r={1.1} fill="#e0a356" />
            ))}
          </svg>
        ) : null}
        {(underlay || bUnderlay) && underlayUrl ? (
          <img src={underlayUrl} alt="" style={{
            position: 'absolute', inset: 0, width: '100%', height: '100%',
            opacity: 0.9, pointerEvents: 'none',
          }} />
        ) : null}
        {placed.map((room) => {
          const lay = room.layout!
          const isSel = room.id === selected
          return (
            <div
              key={room.id}
              onPointerDown={(e) => startDrag(e, room, 'move')}
              onClick={(e) => {
                e.stopPropagation()
                if (clickMode) onRoomClick(e, room)
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
                  <polygon
                    points={lay.outline.map(([u, v]) => `${u * 100},${v * 100}`).join(' ')}
                    fill={isSel ? 'rgba(88,166,255,0.18)' : 'rgba(139,148,158,0.12)'}
                    stroke={isSel ? 'var(--accent, #58a6ff)' : 'rgba(139,148,158,0.7)'}
                    strokeWidth={2} vectorEffect="non-scaling-stroke"
                  />
                </svg>
              ) : null}
              <span style={{
                position: 'absolute', left: 3, top: 2, right: 3, fontSize: 10,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                pointerEvents: 'none',
              }}>
                {room.name || room.id}
                {lay.rotation ? ` ↻${lay.rotation}°` : ''}
              </span>
              {lay.exit ? (
                <span
                  title={t('Exit point')}
                  style={{
                    position: 'absolute',
                    left: `calc(${lay.exit[0] * 100}% - 5px)`,
                    top: `calc(${lay.exit[1] * 100}% - 5px)`,
                    width: 10, height: 10, borderRadius: '50%',
                    background: '#e0a356', border: '1px solid #0d1117',
                    pointerEvents: 'none',
                  }}
                />
              ) : null}
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
                      width: 24, height: 24,
                      transform: `translate(-50%, -50%) rotate(${deg}deg)`,
                      cursor: clickMode ? 'crosshair' : 'grab',
                    }}
                  >
                    <svg viewBox="0 0 24 24" width={24} height={24} style={{ overflow: 'visible' }}>
                      {op.type === 'door' ? (
                        <>
                          {/* Gap in the edge line + hinge leaf + swing arc. */}
                          <line x1={4} y1={12} x2={20} y2={12} stroke={col}
                            strokeWidth={1} strokeDasharray="1.5 2" opacity={0.5} />
                          <line x1={4} y1={12} x2={4} y2={22} stroke={col} strokeWidth={1.5} />
                          <path d="M4 22 A10 10 0 0 0 14 12" fill="none" stroke={col} strokeWidth={1.2} />
                        </>
                      ) : op.type === 'window' ? (
                        <>
                          <line x1={4} y1={11} x2={20} y2={11} stroke={col} strokeWidth={1.4} />
                          <line x1={4} y1={13} x2={20} y2={13} stroke={col} strokeWidth={1.4} />
                        </>
                      ) : (
                        <line x1={4} y1={12} x2={20} y2={12} stroke={col}
                          strokeWidth={2} strokeDasharray="3 2.5" />
                      )}
                    </svg>
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
          // True-size elevator footprint per the client recipe: shaft outer
          // = 1.8 m × figure scale k (anchored 8/plan width, legacy
          // level_height/3) on the 8 m square. On top of the rooms so it
          // stays clickable; click selects it for the sliders.
          const kEl = planW > 0 ? 8 / planW : ((map3d?.level_height || 3) / 3)
          const frac = Math.min((1.8 * kEl) / 8, 0.5)
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
      </div>

      <PlanSidePanel
        room={selectedRoom || null}
        clipKinds={clipKinds}
        markerKind={markerKind}
        onMarkerKind={setMarkerKind}
        markerSel={markerSel}
        onSelectMarker={setMarkerSel}
        onAlwaysVisible={(v) => updateLayout(selectedRoom?.id || '', {
          always_visible: v || undefined,
        })}
      />
      </div>

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
              <span style={{ minWidth: 40 }}>{marker.at[0].toFixed(3)}</span>
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
              <span style={{ minWidth: 40 }}>{marker.at[1].toFixed(3)}</span>
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
              <span style={{ minWidth: 58 }}>
                {fac === undefined ? '—' : `${fac}°${FACING[fac] ? ` (${FACING[fac]})` : ''}`}
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
              <span style={{ minWidth: 44 }}>{(marker.offset_y ?? 0).toFixed(2)}</span>
            </label>
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

      {unplaced.length ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ga-hint">{t('Not on the plan:')}</span>
          {unplaced.map((room) => (
            <button
              key={room.id || room.name}
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'draw-room' && drawTarget === room.id ? ' ga-btn-primary' : ''}`}
              onClick={() => {
                setSelected(room.id || '')
                setDrawTarget(room.id || '')
                setOutlineDraft([])
                setHoverSnap(null)
                setClickMode('draw-room')
              }}
              title={t('Draw this room on the current level — click to place points, click the first point to close, Alt = free-hand, Esc = cancel.')}
            >
              ⬠ {room.name || room.id}
            </button>
          ))}
        </div>
      ) : null}

      {children}
    </div>
  )
}
