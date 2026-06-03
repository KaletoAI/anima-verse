/**
 * MovePad — kompakte Bewegungssteuerung (präsentational).
 * plan-room-conversation Phase 2.
 *
 * Aufbau: oben Raumwechsel (Chips), darunter abgetrennt das Richtungs-D-Pad —
 * beides horizontal zentriert. Wird das Panel schmal, blendet die
 * Pfeil-Beschriftung (Nachbarort-Name) aus (Selbst-Messung via ResizeObserver).
 *
 * Reine Anzeige: Aktionen + Refresh liegen in PlayerApp (onStep/onEnterRoom).
 */
import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'

interface RoomInfo { id: string; name: string; is_entry: boolean }
interface Neighbor { id: string; name: string }
type Dir = 'north' | 'south' | 'east' | 'west'
type Neighbors = Partial<Record<Dir, Neighbor | null>>

export function MovePad({
  rooms, currentRoomId, neighbors, atEntryRoom, entryRoomName, busy,
  onStep, onEnterRoom,
}: {
  rooms: RoomInfo[]
  currentRoomId: string
  neighbors: Neighbors
  atEntryRoom: boolean
  entryRoomName: string
  busy: boolean
  onStep: (dir: Dir) => void
  onEnterRoom: (roomId: string) => void
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

  const compact = w < 200  // zu schmal → Pfeil-Beschriftung ausblenden
  const gated = !atEntryRoom
  // Festes Raster → alle Pfeil-Zellen exakt gleich groß (unabhängig von Label).
  // ohne Schrift: halb so groß · mit Schrift: breiter (130%) + flacher (70%).
  const CW = compact ? 24 : 60     // Zellbreite
  const RH = compact ? 20 : 38     // Zellhöhe

  const cell = (dir: Dir, glyph: string) => {
    const dest = neighbors[dir] || null
    const disabled = !dest || busy || gated
    return (
      <button onClick={() => onStep(dir)} disabled={disabled} title={dest?.name || ''}
        style={{
          width: '100%', height: '100%', padding: '2px 3px', borderRadius: 6,
          boxSizing: 'border-box', overflow: 'hidden',
          cursor: disabled ? 'default' : 'pointer',
          border: '1px solid var(--border, #30363d)',
          background: disabled ? 'transparent' : 'var(--bg-hover, #1f2937)',
          color: 'inherit', opacity: dest ? (gated ? 0.4 : 1) : 0.25,
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

  return (
    <div ref={rootRef} style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      {/* oben fest: Pfeile, zentriert */}
      <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
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
        {gated && (
          <div style={{ opacity: 0.6, fontSize: '0.78em', textAlign: 'center' }}>
            {t('To leave the place, go to the entry room:')} {entryRoomName}
          </div>
        )}
      </div>

      {/* optische Trennung */}
      {rooms.length > 1 && (
        <div style={{ flex: '0 0 auto', height: 1, width: '85%', alignSelf: 'center', background: 'var(--border, #30363d)', opacity: 0.6 }} />
      )}

      {/* unten: Räume, scrollt wenn zu klein */}
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
                title={r.is_entry ? t('Entry / exit room') : ''}
                style={{
                  padding: '2px 8px', borderRadius: 10, fontSize: '0.8em', height: 'fit-content',
                  cursor: cur ? 'default' : 'pointer',
                  border: '1px solid var(--border, #30363d)',
                  background: cur ? 'var(--accent, #6aa9ff)' : 'transparent',
                  color: cur ? '#fff' : 'inherit', opacity: cur ? 1 : 0.85,
                }}>
                {r.name}{r.is_entry ? ' ⌂' : ''}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
