/**
 * RoomLayoutEditor — the floor plan of a location (AV3D-2), embedded in the
 * location editor's "3D world" tab. Rooms are placed as rectangles on the
 * building footprint: drag to move, corner handle to resize, ↻ rotates in
 * 90° steps, "Set exit" places the walk-in/out point with one click inside
 * the room, and animation markers (spots a figure with a matching animation
 * snaps to — kinds from the OPEN clip vocabulary, nothing hardcoded) are
 * placed the same way. Everything edits the LOCATION draft (rooms[].layout)
 * and is persisted by the location's Save button — the external 3D client
 * reads the layout from /world/locations; rooms without a layout fall back
 * to its auto-grid.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { renderTopDownSnapshot } from './topDownSnapshot'
import type { Map3D, Room, RoomLayout } from './worldTypes'

const CANVAS_W = 420
const MIN_FRAC = 0.05

interface RoomLayoutEditorProps {
  rooms: Room[]
  onChange: (rooms: Room[]) => void
  /** Location map3d draft — the editor draws/edits the building outline and
   *  the elevator position (AV3D-12) in it. */
  map3d?: Map3D
  onMap3d?: <K extends keyof Map3D>(key: K, value: Map3D[K] | undefined) => void
  /** Reports the selected room id ('' = none) — the Floor-plan tab shows the
   *  model adjustment strip for it. */
  onSelectRoom?: (roomId: string) => void
}

type DragState =
  | { kind: 'move'; roomId: string; startX: number; startY: number; origX: number; origY: number }
  | { kind: 'resize'; roomId: string; startX: number; startY: number; origW: number; origD: number }
  | null

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
const r4 = (v: number) => Math.round(v * 10000) / 10000

export function RoomLayoutEditor({ rooms, onChange, map3d, onMap3d, onSelectRoom }: RoomLayoutEditorProps) {
  const { t } = useI18n()
  const [level, setLevel] = useState(0)
  const [selected, setSelectedRaw] = useState<string>('')
  const setSelected = useCallback((id: string) => {
    setSelectedRaw(id)
    setMarkerSel(null)
    onSelectRoom?.(id)
  }, [onSelectRoom])
  // Click-to-place modes: the next click inside the room sets the exit point
  // or drops an animation marker of the chosen kind.
  const [clickMode, setClickMode] = useState<'' | 'exit' | 'marker' | 'marker-move' | 'outline' | 'elevator'>('')
  const [markerKind, setMarkerKind] = useState('')
  // Building outline drawing (AV3D-12): points collected while in outline
  // mode, committed to map3d.outline on finish (>= 3 points).
  const [outlineDraft, setOutlineDraft] = useState<Array<[number, number]>>([])
  // Selected marker (index into the selected room's markers) for the
  // per-marker controls: facing, height offset, remove.
  const [markerSel, setMarkerSel] = useState<number | null>(null)
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
    if (!underlay) {
      setUnderlayUrl('')
      return
    }
    const tid = setTimeout(() => {
      renderTopDownSnapshot({ rooms: roomsRef.current, level })
        .then((url) => setUnderlayUrl(url || ''))
        .catch(() => setUnderlayUrl(''))
    }, 350)
    return () => clearTimeout(tid)
  }, [underlay, level, geomKey])

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
        <span className="ga-hint">
          {t('0 = ground floor, negative = basement. Saved with the location.')}
        </span>
      </div>

      {onMap3d ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          {clickMode === 'outline' ? (
            <>
              <span className="ga-hint">{t('Click corner points on the canvas…')}</span>
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-primary"
                disabled={outlineDraft.length < 3}
                onClick={() => {
                  onMap3d('outline', outlineDraft)
                  setOutlineDraft([])
                  setClickMode('')
                }}
              >
                ✓ {t('Finish outline')} ({outlineDraft.length})
              </button>
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => { setOutlineDraft([]); setClickMode('') }}
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
              🏗 {map3d?.outline?.length ? t('Redraw outline') : t('Draw outline')}
            </button>
          )}
          {map3d?.outline?.length && clickMode !== 'outline' ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => onMap3d('outline', undefined)}
              title={t('Remove the outline — the client falls back to the rectangle.')}
            >
              ✕ {t('Clear outline')}
            </button>
          ) : null}
          <button
            type="button"
            className={`ga-btn ga-btn-sm${clickMode === 'elevator' ? ' ga-btn-primary' : ''}`}
            onClick={() => setClickMode((m) => (m === 'elevator' ? '' : 'elevator'))}
            title={t('Place the elevator with one click — it serves ALL levels (the client builds the shaft).')}
          >
            🛗 {clickMode === 'elevator' ? t('Click on the canvas…') : (map3d?.elevator ? t('Move elevator') : t('Set elevator'))}
          </button>
          {map3d?.elevator && clickMode !== 'elevator' ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => onMap3d('elevator', undefined)}
              title={t('Remove the elevator')}
            >
              ✕
            </button>
          ) : null}
        </div>
      ) : null}

      <div
        ref={canvasRef}
        style={{
          position: 'relative', width: CANVAS_W, height: canvasH, maxWidth: '100%',
          border: '1px solid var(--border, #30363d)', borderRadius: 6,
          background: 'rgba(255,255,255,0.03)', overflow: 'hidden', touchAction: 'none',
          cursor: clickMode ? 'crosshair' : undefined,
        }}
        onClick={() => { if (!clickMode) setSelected('') }}
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
            {outlineDraft.map(([x, y], i) => (
              <circle key={i} cx={x * 100} cy={y * 100} r={1.1} fill="#e0a356" />
            ))}
          </svg>
        ) : null}
        {map3d?.elevator ? (
          <span title={t('Elevator (all levels)')} style={{
            position: 'absolute',
            left: `calc(${map3d.elevator[0] * 100}% - 9px)`,
            top: `calc(${map3d.elevator[1] * 100}% - 9px)`,
            fontSize: 15, lineHeight: '18px', pointerEvents: 'none',
            filter: 'drop-shadow(0 0 2px #0d1117)',
          }}>🛗</span>
        ) : null}
        {underlay && underlayUrl ? (
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
              {/* Resize handle (bottom-right) */}
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
            </div>
          )
        })}
        {placed.length === 0 ? (
          <span className="ga-hint" style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center', pointerEvents: 'none',
          }}>
            {t('No rooms on this level yet — click a room below to place it.')}
          </span>
        ) : null}
      </div>

      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {selectedRoom ? (
          <>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              onClick={() => {
                // Rotate the room AS A UNIT (clockwise on the plan): the
                // rectangle swaps w/d around its centre, the exit point
                // turns with the content ((x,y) -> (1-y, x)) and rotation
                // yaws the room MODEL inside the rectangle — plan, exit and
                // 3D model stay in sync (x/y/w/d are always the rectangle AS
                // PLACED, rotation only orients the content).
                const lay = selectedRoom.layout
                if (!lay) return
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
                  // Markers are content points too — they turn with the room.
                  ...(lay.markers?.length
                    ? { markers: lay.markers.map((m) => ({
                        ...m,
                        at: [r4(1 - m.at[1]), r4(m.at[0])] as [number, number],
                        ...(m.rotation !== undefined
                          ? { rotation: (m.rotation + 90) % 360 }
                          : {}),
                      })) }
                    : {}),
                })
              }}
              title={t('Rotate the room 90° clockwise — rectangle, exit point and 3D model turn together.')}
            >
              ↻ +90° ({selectedRoom.layout?.rotation || 0}°)
            </button>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${clickMode === 'exit' ? ' ga-btn-primary' : ''}`}
              onClick={() => setClickMode((m) => (m === 'exit' ? '' : 'exit'))}
              title={t('Then click inside the room to place the walk-in/out point.')}
            >
              🚪 {clickMode === 'exit' ? t('Click into the room…') : t('Set exit')}
            </button>
            {selectedRoom.layout?.exit ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => updateLayout(selectedRoom.id || '', { exit: undefined })}
                title={t('Remove the exit point — the client falls back to the edge facing the building centre.')}
              >
                {t('Clear exit')}
              </button>
            ) : null}
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
            {clipKinds.length ? (
              <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                <select
                  className="ga-input"
                  style={{ width: 110 }}
                  value={markerKind}
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
                  onClick={() => setClickMode((m) => (m === 'marker' ? '' : 'marker'))}
                  title={t('Then click inside the room to drop the marker — figures with this animation snap to it.')}
                >
                  🎯 {clickMode === 'marker' ? t('Click into the room…') : t('Add marker')}
                </button>
              </span>
            ) : null}
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => { updateLayout(selectedRoom.id || '', null); setSelected('') }}
              title={t('Remove from the floor plan — the 3D client auto-grids this room again.')}
            >
              ✕ {t('Unplace')}
            </button>
          </>
        ) : (
          <span className="ga-hint">{t('Select a room rectangle to rotate it or set its exit.')}</span>
        )}
      </div>

      {selectedRoom?.layout?.markers?.length ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ga-hint">{t('Markers:')}</span>
          {selectedRoom.layout.markers.map((m, i) => (
            <button
              key={`${m.animation}-${i}`}
              type="button"
              className={`ga-btn ga-btn-sm${markerSel === i ? ' ga-btn-primary' : ''}`}
              onClick={() => setMarkerSel(markerSel === i ? null : i)}
              title={t('Select this marker to adjust facing/height or remove it.')}
            >
              🎯 {i + 1} · {m.animation}
            </button>
          ))}
        </div>
      ) : null}

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
    </div>
  )
}
