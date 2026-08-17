/**
 * TravelPanel — the avatar's movement control (was the MovePad compass).
 *
 * Two movements, two lists, one panel:
 *  - TRAVEL, to another location: a destination list with a Travel button
 *    each (`POST /play/travel`). The world is a metre plane since E1, so
 *    there is no "one cell north" any more — a trip is a timed journey to a
 *    NAMED place, and while it runs the list gives way to its status (target,
 *    arrival on the game clock, metres left) with a Cancel button.
 *  - ROOM CHANGE, inside the current location: the chips below, unchanged
 *    (`POST /play/enter-room`).
 *
 * Where the destinations come from: `GET /play/worldmap`, FOGGED — that
 * payload IS the avatar's knowledge of the world (§ A12), so a place the
 * avatar has never heard of cannot even be offered, and no second endpoint
 * has to reproduce the same fog rule. Polled under the very key MapPanel
 * uses, so both panels share ONE request, and only while a panel is mounted.
 * Transit tiles (`passable`) are dropped: a road is walked THROUGH, never
 * travelled TO — the same rule the LLM's target list applies.
 *
 * The actions live in PlayerApp (onTravel/onCancelTravel/onEnterRoom); this
 * component decides nothing the server has not already decided. Locks are the
 * server's word (task C2): `enterable === false` with the rule's own `reason`
 * marks a room chip as barred, and the reason is LOCALIZED BY THE SERVER and
 * shown as it is — running it through `t()` would look up a sentence no
 * translation file has.
 */
import { useMemo } from 'react'
import { apiGet } from '../lib/api'
import { useI18n } from '../i18n/I18nProvider'
import { usePoll } from './usePolling'
import type { TravelInfo } from './ScenePanel'

interface RoomInfo {
  id: string; name: string; is_entry: boolean; is_ground: boolean
  enterable: boolean; reason: string
}

/** The slice of the worldmap payload the destination list needs. */
interface WorldMapLocation {
  id: string; name: string
  pos_x: number | null; pos_z: number | null
  /** The location's edge in metres — null when it has no scale anchor. */
  plan_width_m: number | null
  passable?: boolean
}
interface WorldMapLite {
  avatar: string
  current_location_id: string
  locations: WorldMapLocation[]
  characters: Array<{ name: string; pos: { x: number; z: number } | null }>
}

interface Destination { id: string; name: string; distance_m: number | null }

export function TravelPanel({
  rooms, currentRoomId, travel, busy,
  onTravel, onCancelTravel, onEnterRoom,
  partyFollower = false, partyLeaderName = '',
}: {
  rooms: RoomInfo[]
  currentRoomId: string
  /** The running journey from `/play/scene`, or null while standing still. */
  travel: TravelInfo | null
  busy: boolean
  onTravel: (locationId: string) => void
  onCancelTravel: () => void
  onEnterRoom: (roomId: string) => void
  /** The avatar is a party follower: no movement of its own (travel + room
   *  chips off), the leader pulls it along. */
  partyFollower?: boolean
  partyLeaderName?: string
}) {
  const { t } = useI18n()
  // Same key + interval as MapPanel: the hub shares one in-flight request and
  // its result, so opening both panels costs a single poll.
  const { data: world } = usePoll<WorldMapLite>(
    'play-worldmap', () => apiGet<WorldMapLite>('/play/worldmap'),
    { intervalMs: 10000, enabled: !partyFollower })

  const destinations = useMemo<Destination[]>(() => {
    const here = world?.current_location_id || ''
    const me = (world?.characters || []).find((c) => c.name === world?.avatar)
    const from = me?.pos || null
    return (world?.locations || [])
      // Placed AND anchored: `start_journey` needs a `placed_footprint`, and
      // that is exactly position + scale anchor (`plan_width_m`). A location
      // with a point but no anchor stands on no walkable map — offering it
      // would only ever produce an `unplaced_target` refusal.
      .filter((l) => l.id && l.id !== here && !l.passable
        && l.pos_x !== null && l.pos_z !== null && l.plan_width_m !== null)
      .map((l) => ({
        id: l.id,
        name: l.name || l.id,
        // Straight-line metres, a rough sense of distance for the choice —
        // the walked route is longer and only the server knows it.
        distance_m: from
          ? Math.hypot((l.pos_x as number) - from.x, (l.pos_z as number) - from.z)
          : null,
      }))
      .sort((a, b) => (a.distance_m ?? Infinity) - (b.distance_m ?? Infinity)
        || a.name.localeCompare(b.name))
  }, [world])

  // Party follower: no movement of its own — travel + room chips off, only a
  // note. The leader pulls the avatar along.
  if (partyFollower) {
    return (
      <div style={{
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

  const remaining = travel
    ? Math.max(0, Math.round(travel.total_m - travel.progress_m))
    : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
      {/* On top: the journey, or the places one can set off for. */}
      <div style={{
        flex: '1 1 auto', minHeight: 0, overflowY: 'auto',
        display: 'flex', flexDirection: 'column', gap: 4,
      }}>
        {travel ? (
          <div style={{
            display: 'flex', flexDirection: 'column', gap: 6, padding: 8,
            borderRadius: 8, border: '1px solid var(--border, #30363d)',
          }}>
            <div style={{ fontSize: '0.86em' }}>
              🚶 {t('On the road to')} <strong>{travel.target_name}</strong>
            </div>
            <div style={{ fontSize: '0.76em', opacity: 0.75 }}>
              {/* Arrival on the world calendar — clock time inline, the full
                  label ("Summer, day 17 · 14:00 · Year 3") in the tooltip. */}
              {t('Arrival')}{' '}
              <span title={travel.eta_label || undefined}>{travel.eta_hhmm}</span>
              {' · '}{remaining} m {t('to go')}
            </div>
            <button onClick={onCancelTravel} disabled={busy}
              style={{
                alignSelf: 'flex-start', padding: '2px 10px', borderRadius: 10,
                fontSize: '0.8em', cursor: busy ? 'default' : 'pointer',
                border: '1px solid var(--border, #30363d)',
                background: 'transparent', color: 'inherit',
              }}>
              {t('Cancel journey')}
            </button>
          </div>
        ) : destinations.length === 0 ? (
          <div style={{ opacity: 0.6, fontSize: '0.78em', textAlign: 'center', padding: 8 }}>
            {t('You know no other place to travel to yet.')}
          </div>
        ) : (
          destinations.map((d) => (
            <div key={d.id} style={{
              display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82em',
            }}>
              <span style={{
                flex: '1 1 auto', minWidth: 0, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }} title={d.name}>{d.name}</span>
              {d.distance_m !== null && (
                <span style={{ flex: '0 0 auto', fontSize: '0.9em', opacity: 0.55 }}>
                  {Math.round(d.distance_m)} m
                </span>
              )}
              <button onClick={() => onTravel(d.id)} disabled={busy}
                style={{
                  flex: '0 0 auto', padding: '2px 8px', borderRadius: 10,
                  fontSize: '0.92em', cursor: busy ? 'default' : 'pointer',
                  border: '1px solid var(--border, #30363d)',
                  background: 'var(--bg-hover, #1f2937)', color: 'inherit',
                }}>
                {t('Travel')}
              </button>
            </div>
          ))
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
          flex: '0 1 auto', minHeight: 0, maxHeight: '45%', overflowY: 'auto',
          display: 'flex', flexWrap: 'wrap', gap: 4,
          justifyContent: 'center', alignContent: 'flex-start',
        }}>
          {rooms.map((r) => {
            const cur = r.id === currentRoomId
            // The server refuses this room for this avatar — the same verdict
            // `/play/enter-room` would answer with, so the chip is dead before
            // it is clicked and carries the rule's own sentence. The room one
            // is IN is never locked away from itself.
            const locked = !cur && r.enterable === false
            return (
              <button key={r.id} disabled={cur || busy || locked} onClick={() => onEnterRoom(r.id)}
                title={locked
                  ? (r.reason || t('locked'))
                  : r.is_ground
                    ? t('The ground of this location — the area no room takes up')
                    : r.is_entry ? t('Entry / exit room') : ''}
                style={{
                  padding: '2px 8px', borderRadius: 10, fontSize: '0.8em', height: 'fit-content',
                  cursor: cur || locked ? 'default' : 'pointer',
                  border: locked
                    ? '1px solid var(--danger, #da3633)'
                    : '1px solid var(--border, #30363d)',
                  background: cur ? 'var(--accent, #6aa9ff)' : 'transparent',
                  color: cur ? '#fff' : 'inherit',
                  opacity: locked ? 0.45 : cur ? 1 : 0.85,
                  textDecoration: locked ? 'line-through' : 'none',
                }}>
                {locked ? '🔒 ' : r.is_ground ? '🌐 ' : ''}{r.name}{r.is_entry ? ' ⌂' : ''}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
