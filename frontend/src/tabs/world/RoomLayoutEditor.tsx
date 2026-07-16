/**
 * RoomLayoutEditor — the floor plan of a location (AV3D-2), embedded in the
 * location editor's "3D world" tab. Rooms are placed as rectangles on the
 * building footprint: drag to move, corner handle to resize, ↻ rotates in
 * 90° steps, "Set exit" places the walk-in/out point with one click inside
 * the room. Everything edits the LOCATION draft (rooms[].layout) and is
 * persisted by the location's Save button — the external 3D client reads the
 * layout from /world/locations; rooms without a layout fall back to its
 * auto-grid.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import type { Room, RoomLayout } from './worldTypes'

const CANVAS_W = 420
const MIN_FRAC = 0.05

interface RoomLayoutEditorProps {
  rooms: Room[]
  /** Building footprint in grid cells (map3d.footprint) — sets the canvas
   *  aspect ratio only; all layout values stay fractions. */
  footprint?: number[]
  onChange: (rooms: Room[]) => void
}

type DragState =
  | { kind: 'move'; roomId: string; startX: number; startY: number; origX: number; origY: number }
  | { kind: 'resize'; roomId: string; startX: number; startY: number; origW: number; origD: number }
  | null

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
const r4 = (v: number) => Math.round(v * 10000) / 10000

export function RoomLayoutEditor({ rooms, footprint, onChange }: RoomLayoutEditorProps) {
  const { t } = useI18n()
  const [level, setLevel] = useState(0)
  const [selected, setSelected] = useState<string>('')
  const [exitMode, setExitMode] = useState(false)
  const canvasRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState>(null)
  const roomsRef = useRef(rooms)
  roomsRef.current = rooms

  const fw = Math.max(1, footprint?.[0] || 1)
  const fd = Math.max(1, footprint?.[1] || 1)
  const canvasH = Math.round((CANVAS_W * fd) / fw)

  const placed = rooms.filter((r) => r.layout && (r.layout.level || 0) === level)
  const unplaced = rooms.filter((r) => !r.layout)
  const levels = Array.from(
    new Set(rooms.filter((r) => r.layout).map((r) => r.layout!.level || 0)),
  ).sort((a, b) => a - b)

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
    if (exitMode) return
    const lay = room.layout
    if (!lay || !room.id) return
    e.preventDefault()
    e.stopPropagation()
    setSelected(room.id)
    dragRef.current = kind === 'move'
      ? { kind, roomId: room.id, startX: e.clientX, startY: e.clientY, origX: lay.x, origY: lay.y }
      : { kind, roomId: room.id, startX: e.clientX, startY: e.clientY, origW: lay.w, origD: lay.d }
  }, [exitMode])

  // Exit mode: one click inside a room sets the walk-in/out point as a
  // fraction of the ROOM rectangle (client contract).
  const onRoomClick = useCallback((e: React.MouseEvent, room: Room) => {
    if (!exitMode || !room.id || !room.layout) return
    e.stopPropagation()
    const target = e.currentTarget as HTMLDivElement
    const rect = target.getBoundingClientRect()
    const ex = r4(clamp((e.clientX - rect.left) / rect.width, 0, 1))
    const ey = r4(clamp((e.clientY - rect.top) / rect.height, 0, 1))
    updateLayout(room.id, { exit: [ex, ey] })
    setExitMode(false)
  }, [exitMode, updateLayout])

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
              setExitMode(false)
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
                onClick={() => { setLevel(lv); setSelected(''); setExitMode(false) }}
                title={t('Rooms on this level: {n}').replace('{n}',
                  String(rooms.filter((r) => r.layout && (r.layout.level || 0) === lv).length))}
              >
                {lv}
              </button>
            ))}
          </span>
        ) : null}
        <span className="ga-hint">
          {t('0 = ground floor, negative = basement. Saved with the location.')}
        </span>
      </div>

      <div
        ref={canvasRef}
        style={{
          position: 'relative', width: CANVAS_W, height: canvasH, maxWidth: '100%',
          border: '1px solid var(--border, #30363d)', borderRadius: 6,
          background: 'rgba(255,255,255,0.03)', overflow: 'hidden', touchAction: 'none',
          cursor: exitMode ? 'crosshair' : undefined,
        }}
        onClick={() => { if (!exitMode) setSelected('') }}
      >
        {placed.map((room) => {
          const lay = room.layout!
          const isSel = room.id === selected
          return (
            <div
              key={room.id}
              onPointerDown={(e) => startDrag(e, room, 'move')}
              onClick={(e) => {
                e.stopPropagation()
                if (exitMode) onRoomClick(e, room)
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
                cursor: exitMode ? 'crosshair' : 'move', userSelect: 'none',
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
              onClick={() => updateLayout(selectedRoom.id || '', {
                rotation: (((selectedRoom.layout?.rotation || 0) + 90) % 360) || undefined,
              })}
              title={t('Rotate the room 90° around the vertical axis (the 3D client applies it).')}
            >
              ↻ +90° ({selectedRoom.layout?.rotation || 0}°)
            </button>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${exitMode ? ' ga-btn-primary' : ''}`}
              onClick={() => setExitMode((v) => !v)}
              title={t('Then click inside the room to place the walk-in/out point.')}
            >
              🚪 {exitMode ? t('Click into the room…') : t('Set exit')}
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
