/**
 * MovePad — the compact movement control (presentational).
 * plan-room-conversation phase 2.
 *
 * Layout: room changes on top (chips), the direction pad below them, both
 * horizontally centred. On a narrow panel the arrow labels (the neighbour
 * location's name) disappear (self-measured via ResizeObserver).
 *
 * Display only: the actions + refresh live in PlayerApp (onStep/onEnterRoom).
 *
 * The departure gate is NOT recomputed here: every neighbour carries the
 * server's own `may_leave` for its direction (`boundary_entry.may_leave`),
 * because an authored pass-through opens exactly its own edge — the pad used
 * to hold a copy of an older rule and greyed out steps the server allows.
 */
import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'

interface RoomInfo { id: string; name: string; is_entry: boolean; is_ground: boolean }
interface Neighbor { id: string; name: string; may_leave: boolean }
type Dir = 'north' | 'south' | 'east' | 'west'
type Neighbors = Partial<Record<Dir, Neighbor | null>>

const DIRS: Dir[] = ['north', 'south', 'east', 'west']

export function MovePad({
  rooms, currentRoomId, neighbors, entryRoomName, busy,
  onStep, onEnterRoom, partyFollower = false, partyLeaderName = '',
}: {
  rooms: RoomInfo[]
  currentRoomId: string
  neighbors: Neighbors
  entryRoomName: string
  busy: boolean
  onStep: (dir: Dir) => void
  onEnterRoom: (roomId: string) => void
  /** The avatar is a party follower: no movement of its own (compass + room
   *  chips off), the leader pulls it along. */
  partyFollower?: boolean
  partyLeaderName?: string
}) {
  const { t } = useI18n()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [w, setW] = useState(300)

  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width
      if (cw && cw > 0) setW(cw)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const compact = w < 200  // too narrow → hide the arrow labels
  // Every direction that leads anywhere, and whether the server lets one out
  // that way. All four barred = the pad is useless here and the hint takes
  // its place; a single open direction keeps the pad on screen.
  const dests = DIRS.map((d) => neighbors[d]).filter((n): n is Neighbor => !!n)
  const gated = dests.length > 0 && !dests.some((n) => n.may_leave !== false)
  // Fixed grid → every arrow cell exactly the same size (label or not).
  // Without text: half as big · with text: wider (130%) + flatter (70%).
  const CW = compact ? 24 : 60     // cell width
  const RH = compact ? 20 : 38     // cell height

  const cell = (dir: Dir, glyph: string) => {
    const dest = neighbors[dir] || null
    const barred = !!dest && dest.may_leave === false
    const disabled = !dest || busy || barred
    return (
      <button onClick={() => onStep(dir)} disabled={disabled}
        title={dest
          ? (barred
            ? `${dest.name} — ${t('not from this room')}`
            : dest.name)
          : ''}
        style={{
          width: '100%', height: '100%', padding: '2px 3px', borderRadius: 6,
          boxSizing: 'border-box', overflow: 'hidden',
          cursor: disabled ? 'default' : 'pointer',
          border: '1px solid var(--border, #30363d)',
          background: disabled ? 'transparent' : 'var(--bg-hover, #1f2937)',
          color: 'inherit', opacity: dest ? (barred ? 0.4 : 1) : 0.25,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', lineHeight: 1.1,
        }}>
        <span style={{ fontSize: '1.1em' }}>{glyph}</span>
        {dest && !compact && (
          <span style={{ fontSize: '0.68em', opacity: 0.7, maxWidth: CW - 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{dest.name}</span>
        )}
      </button>
    )
  }
  const blank = <span />

  // Party follower: no movement of its own — compass + room chips off, only
  // a note. The leader pulls the avatar along.
  if (partyFollower) {
    return (
      <div ref={rootRef} style={{
        display: 'flex', flexDirection: 'column', height: '100%',
        alignItems: 'center', justifyContent: 'center', gap: 8,
        padding: 12, textAlign: 'center', opacity: 0.8,
      }}>
        <div style={{ fontSize: '1.6em' }}>👥</div>
        <div style={{ fontSize: '0.86em' }}>
          {partyLeaderName
            ? `${t('You are following the party of')} ${partyLeaderName}.`
            : t('You are part of a party.')}
        </div>
        <div style={{ fontSize: '0.74em', opacity: 0.7 }}>
          {t('You move together — leave the party to move on your own.')}
        </div>
      </div>
    )
  }

  return (
    <div ref={rootRef} style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      {/* Fixed on top: the arrows, centred. No way out from this room at all
          → hide the (fully disabled) pad and leave the hint alone (saves
          space). A single open direction keeps the whole pad. */}
      <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
        {!gated && (
          <div style={{
            display: 'grid', gridTemplateColumns: `repeat(3, ${CW}px)`,
            gridAutoRows: `${RH}px`, gap: 4, justifyContent: 'center',
          }}>
            {blank}{cell('north', '↑')}{blank}
            {cell('west', '←')}
            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 0.35 }}>◉</span>
            {cell('east', '→')}
            {blank}{cell('south', '↓')}{blank}
          </div>
        )}
        {gated && (
          <div style={{ opacity: 0.6, fontSize: '0.78em', textAlign: 'center' }}>
            {t('To leave the place, go to the entry room:')} {entryRoomName}
          </div>
        )}
      </div>

      {/* visual separator */}
      {rooms.length > 1 && (
        <div style={{ flex: '0 0 auto', height: 1, width: '85%', alignSelf: 'center', background: 'var(--border, #30363d)', opacity: 0.6 }} />
      )}

      {/* Below: the rooms, scrolling when the panel is too small. The ground
          is one of them, so a location with a single authored room already
          has two chips — there is always a way back onto the ground. */}
      {rooms.length > 1 && (
        <div style={{
          flex: '1 1 auto', minHeight: 0, overflowY: 'auto',
          display: 'flex', flexWrap: 'wrap', gap: 4,
          justifyContent: 'center', alignContent: 'flex-start',
        }}>
          {rooms.map((r) => {
            const cur = r.id === currentRoomId
            return (
              <button key={r.id} disabled={cur || busy} onClick={() => onEnterRoom(r.id)}
                title={r.is_ground
                  ? t('The ground of this location — the area no room takes up')
                  : r.is_entry ? t('Entry / exit room') : ''}
                style={{
                  padding: '2px 8px', borderRadius: 10, fontSize: '0.8em', height: 'fit-content',
                  cursor: cur ? 'default' : 'pointer',
                  border: '1px solid var(--border, #30363d)',
                  background: cur ? 'var(--accent, #6aa9ff)' : 'transparent',
                  color: cur ? '#fff' : 'inherit', opacity: cur ? 1 : 0.85,
                }}>
                {r.is_ground ? '🌐 ' : ''}{r.name}{r.is_entry ? ' ⌂' : ''}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
