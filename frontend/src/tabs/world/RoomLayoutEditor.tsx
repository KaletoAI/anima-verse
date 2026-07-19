/**
 * RoomLayoutEditor — the floor plan of a location (AV3D-2), embedded in the
 * location editor's "Floor plan" tab. Rooms are placed as rectangles on the
 * building footprint: drag to move, corner handle to resize; the toolbar at
 * the right of the plan rotates in 90° steps, places the exit and animation
 * markers (spots a figure with a matching animation snaps to — kinds from
 * the OPEN clip vocabulary, nothing hardcoded) with one click inside the
 * room, and draws the building outline / places the elevator (AV3D-12).
 * Everything edits the LOCATION draft (rooms[].layout)
 * and is persisted by the location's Save button — the external 3D client
 * reads the layout from /world/locations; rooms without a layout fall back
 * to its auto-grid.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { getBuildingDims, getRoomModelDims, renderTopDownSnapshot } from './topDownSnapshot'
import type { Map3D, Room, RoomLayout } from './worldTypes'

const CANVAS_W = 420
const MIN_FRAC = 0.05

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
  | null

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
const r4 = (v: number) => Math.round(v * 10000) / 10000

export function RoomLayoutEditor({ rooms, onChange, locationId = '', fallbackYawDeg = 0, map3d, onMap3d, onSelectRoom, children }: RoomLayoutEditorProps) {
  const { t } = useI18n()
  const [level, setLevel] = useState(0)
  const [selected, setSelectedRaw] = useState<string>('')
  const setSelected = useCallback((id: string) => {
    setSelectedRaw(id)
    setMarkerSel(null)
    setElevatorSel(false)
    onSelectRoom?.(id)
  }, [onSelectRoom])
  // Click-to-place modes: the next click inside the room sets the exit point
  // or drops an animation marker of the chosen kind.
  const [clickMode, setClickMode] = useState<'' | 'exit' | 'marker' | 'marker-move' | 'outline' | 'elevator'>('')
  const [markerKind, setMarkerKind] = useState('')
  // Building outline drawing (AV3D-12): points collected while in outline
  // mode, committed to map3d.outline on finish (>= 3 points).
  const [outlineDraft, setOutlineDraft] = useState<Array<[number, number]>>([])
  // Cursor position while drawing the outline — feeds the rubber-band lines.
  const [hoverPt, setHoverPt] = useState<[number, number] | null>(null)
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
      const ds = r.id ? derivedSize(r.id) : null
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

  // Pointer interactions: move on the rect body, resize on the corner handle.
  // Window listeners so a drag survives leaving the canvas; fractions clamped
  // to keep the room inside the footprint.
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const drag = dragRef.current
      const canvas = canvasRef.current
      if (!drag || !canvas) return
      e.preventDefault()
      const dx = (e.clientX - drag.startX) / canvas.clientWidth
      const dy = (e.clientY - drag.startY) / canvas.clientHeight
      const room = roomsRef.current.find((r) => r.id === drag.roomId)
      const lay = room?.layout
      if (!lay) return
      if (drag.kind === 'move') {
        updateLayout(drag.roomId, {
          x: r4(clamp(drag.origX + dx, 0, 1 - lay.w)),
          y: r4(clamp(drag.origY + dy, 0, 1 - lay.d)),
        })
      } else {
        updateLayout(drag.roomId, {
          w: r4(clamp(drag.origW + dx, MIN_FRAC, 1 - lay.x)),
          d: r4(clamp(drag.origD + dy, MIN_FRAC, 1 - lay.y)),
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
    }
    setClickMode('')
  }, [clickMode, markerKind, markerSel, selected, updateLayout])

  const selectedRoom = rooms.find((r) => r.id === selected && r.layout)

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
    })
  }

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      <div className="ga-form-section-label">{t('Room layout (floor plan)')}</div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}>
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
        <label className="ga-check-row" style={{ fontSize: '0.82em' }}>
          <input type="checkbox" checked={underlay}
            onChange={(e) => setUnderlay(e.target.checked)} />
          <span>{t('Models behind the plan')}</span>
        </label>
        <label className="ga-check-row" style={{ fontSize: '0.82em' }}
          title={t('Lay the building model (roof view = real footprint) behind the plan — for tracing the outline polygon.')}>
          <input type="checkbox" checked={bUnderlay}
            onChange={(e) => setBUnderlay(e.target.checked)} />
          <span>{t('Building behind the plan')}</span>
        </label>
        <span className="ga-hint">
          {t('0 = ground floor, negative = basement. Saved with the location.')}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
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
          if (clickMode !== 'outline') return
          const rect = (canvasRef.current as HTMLDivElement).getBoundingClientRect()
          setHoverPt([r4(clamp((e.clientX - rect.left) / rect.width, 0, 1)),
                      r4(clamp((e.clientY - rect.top) / rect.height, 0, 1))])
        }}
        onPointerLeave={() => setHoverPt(null)}
        onClickCapture={(e) => {
          // Building-level placement (outline points / elevator) applies at
          // CANVAS coordinates, also when the click lands inside a room —
          // capture phase keeps the room handlers out of the way.
          if (clickMode !== 'outline' && clickMode !== 'elevator') return
          e.stopPropagation()
          const rect = (canvasRef.current as HTMLDivElement).getBoundingClientRect()
          const px = r4(clamp((e.clientX - rect.left) / rect.width, 0, 1))
          const py = r4(clamp((e.clientY - rect.top) / rect.height, 0, 1))
          if (clickMode === 'outline') {
            setOutlineDraft((prev) => [...prev, [px, py]])
          } else {
            onMap3d?.('elevator', [px, py])
            setClickMode('')
          }
        }}
      >
        {/* Building outline (existing + draft) as an SVG overlay. */}
        {(map3d?.outline?.length || outlineDraft.length) ? (
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
            {/* Rubber band: the running segment follows the cursor, and the
                closing line back to the start point is always visible. */}
            {clickMode === 'outline' && outlineDraft.length ? (() => {
              const first = outlineDraft[0]
              const last = outlineDraft[outlineDraft.length - 1]
              const cur = hoverPt || last
              return (
                <>
                  {hoverPt ? (
                    <line x1={last[0] * 100} y1={last[1] * 100}
                      x2={hoverPt[0] * 100} y2={hoverPt[1] * 100}
                      stroke="#e0a356" strokeWidth={0.6} />
                  ) : null}
                  {(outlineDraft.length >= 2 || hoverPt) ? (
                    <line x1={cur[0] * 100} y1={cur[1] * 100}
                      x2={first[0] * 100} y2={first[1] * 100}
                      stroke="#e0a356" strokeWidth={0.45}
                      strokeDasharray="1.2 1.2" opacity={0.75} />
                  ) : null}
                </>
              )
            })() : null}
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
                border: `2px solid ${isSel ? 'var(--accent, #58a6ff)' : 'rgba(139,148,158,0.7)'}`,
                background: isSel ? 'rgba(88,166,255,0.18)' : 'rgba(139,148,158,0.12)',
                borderRadius: 4, boxSizing: 'border-box',
                cursor: clickMode ? 'crosshair' : 'move', userSelect: 'none',
              }}
            >
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
              {/* Resize handle (bottom-right) — hidden in anchored mode for
                  rooms whose size DERIVES from the model's declared width
                  (there is nothing to resize then, only to position). */}
              {room.id && derivedSize(room.id) ? null : (
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

      {/* Toolbar at the right side of the plan — room tools on top,
          building tools (outline/elevator) below. */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width: 118, flex: '0 0 auto' }}>
        <span className="ga-hint">{t('Room')}</span>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={!selectedRoom}
          onClick={rotateSelected}
          title={t('Rotate the room 90° clockwise — rectangle, exit point and 3D model turn together.')}
        >
          ↻ 90° ({selectedRoom?.layout?.rotation || 0}°)
        </button>
        <button
          type="button"
          className={`ga-btn ga-btn-sm${clickMode === 'exit' ? ' ga-btn-primary' : ''}`}
          disabled={!selectedRoom}
          onClick={() => setClickMode((m) => (m === 'exit' ? '' : 'exit'))}
          title={t('Then click inside the room to place the walk-in/out point.')}
        >
          🚪 {clickMode === 'exit' ? '…' : t('Exit')}
        </button>
        {selectedRoom?.layout?.exit ? (
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={() => updateLayout(selectedRoom.id || '', { exit: undefined })}
            title={t('Remove the exit point — the client falls back to the edge facing the building centre.')}
          >
            🗑 {t('Exit')}
          </button>
        ) : null}
        {clipKinds.length ? (
          <>
            <select
              className="ga-input"
              style={{ width: '100%' }}
              value={markerKind}
              disabled={!selectedRoom}
              onChange={(e) => setMarkerKind(e.target.value)}
              title={t('Animation kind — the open clip vocabulary, nothing hardcoded.')}
            >
              {clipKinds.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'marker' ? ' ga-btn-primary' : ''}`}
              disabled={!selectedRoom}
              onClick={() => setClickMode((m) => (m === 'marker' ? '' : 'marker'))}
              title={t('Then click inside the room to drop the marker — figures with this animation snap to it.')}
            >
              🎯 {clickMode === 'marker' ? '…' : t('Marker')}
            </button>
          </>
        ) : null}
        <button
          type="button"
          className="ga-btn ga-btn-sm ga-btn-danger"
          disabled={!selectedRoom}
          onClick={() => { updateLayout(selectedRoom?.id || '', null); setSelected('') }}
          title={t('Remove from the floor plan — the 3D client auto-grids this room again.')}
        >
          ✕ {t('Unplace')}
        </button>
        {onMap3d ? (
          <>
            <span className="ga-hint" style={{ marginTop: 6 }}>{t('Building')}</span>
            {clickMode === 'outline' ? (
              <>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm ga-btn-primary"
                  disabled={outlineDraft.length < 3}
                  onClick={() => {
                    onMap3d('outline', outlineDraft)
                    setOutlineDraft([])
                    setHoverPt(null)
                    setClickMode('')
                  }}
                  title={t('Finish outline')}
                >
                  ✓ ({outlineDraft.length})
                </button>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  onClick={() => { setOutlineDraft([]); setHoverPt(null); setClickMode('') }}
                >
                  {t('Cancel')}
                </button>
              </>
            ) : (
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => { setOutlineDraft([]); setClickMode('outline') }}
                title={t('Draw the building outline as a polygon (fractions of the reference square) — the 3D client renders floor plates and walls from it.')}
              >
                🏗 {t('Outline')}
              </button>
            )}
            {map3d?.outline?.length && clickMode !== 'outline' ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-danger"
                onClick={() => onMap3d('outline', undefined)}
                title={t('Remove the outline — the client falls back to the rectangle.')}
              >
                🗑 {t('Outline')}
              </button>
            ) : null}
            <button
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'elevator' ? ' ga-btn-primary' : ''}`}
              onClick={() => setClickMode((m) => (m === 'elevator' ? '' : 'elevator'))}
              title={t('Place the elevator with one click — it serves ALL levels (the client builds the shaft).')}
            >
              🛗 {clickMode === 'elevator' ? '…' : t('Elevator')}
            </button>
            {map3d?.elevator && clickMode !== 'elevator' ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-danger"
                onClick={() => onMap3d('elevator', undefined)}
                title={t('Remove the elevator')}
              >
                🗑 {t('Elevator')}
              </button>
            ) : null}
          </>
        ) : null}
        {/* Markers of the selected room — appended dynamically; the
            adjustment sliders stay below the plan. */}
        {selectedRoom?.layout?.markers?.length ? (
          <>
            <span className="ga-hint" style={{ marginTop: 6 }}>{t('Markers')}</span>
            {selectedRoom.layout.markers.map((m, i) => (
              <button
                key={`${m.animation}-${i}`}
                type="button"
                className={`ga-btn ga-btn-sm${markerSel === i ? ' ga-btn-primary' : ''}`}
                style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                onClick={() => setMarkerSel(markerSel === i ? null : i)}
                title={t('Select this marker to adjust facing/height or remove it.')}
              >
                🎯 {i + 1} · {m.animation}
              </button>
            ))}
          </>
        ) : null}
      </div>
      </div>

      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {selectedRoom ? (
          <label className="ga-check-row" style={{ fontSize: '0.82em' }}
            title={t('Show this room permanently in the 3D client, independent of the interior view — for outdoor rooms the building model does not cover.')}>
            <input
              type="checkbox"
              checked={!!selectedRoom.layout?.always_visible}
              onChange={(e) => updateLayout(selectedRoom.id || '', {
                always_visible: e.target.checked || undefined,
              })}
            />
            <span>{t('Always visible')}</span>
          </label>
        ) : null}
        {!selectedRoom ? (
          <span className="ga-hint">{t('Select a room rectangle — the toolbar next to the plan works on it.')}</span>
        ) : null}
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
          {unplaced.map((room, i) => (
            <button
              key={room.id || room.name}
              type="button"
              className="ga-btn ga-btn-sm"
              onClick={() => {
                updateLayout(room.id || '', {
                  level,
                  x: r4(clamp(0.05 + (i % 3) * 0.32, 0, 0.7)),
                  y: r4(clamp(0.05 + Math.floor(i / 3) * 0.32, 0, 0.7)),
                  w: 0.3,
                  d: 0.3,
                })
                setSelected(room.id || '')
              }}
              title={t('Place this room on the current level.')}
            >
              + {room.name || room.id}
            </button>
          ))}
        </div>
      ) : null}

      {children}
    </div>
  )
}
