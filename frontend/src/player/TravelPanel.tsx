/**
 * TravelPanel — the avatar's movement control (was the MovePad compass).
 *
 * Two movements, one panel:
 *  - TRAVEL, to another location: THE DESTINATION IS PICKED ON THE MAP. The
 *    schematic map (`MapPanel`) fills the upper half, a click on a location
 *    outline selects it, and the bar under the map names the pick with its
 *    straight-line distance plus the one Travel button (`POST /play/travel`).
 *    A bare click never starts a journey. The world is a metre plane since E1,
 *    so there is no "one cell north" any more — a trip is a timed journey to a
 *    NAMED place, and while it runs the map gives way to its status (target,
 *    arrival on the game clock, metres left) with a Cancel button.
 *  - ROOM CHANGE, inside the current location: the chips below, unchanged
 *    (`POST /play/enter-room`).
 *
 * Where the pick's data comes from: `GET /play/worldmap`, FOGGED — that
 * payload IS the avatar's knowledge of the world (§ A12), so a place the
 * avatar has never heard of is neither drawn nor pickable, and no second
 * endpoint has to reproduce the same fog rule. Polled under the very key
 * MapPanel uses, so panel and map share ONE request.
 *
 * The distance is the STRAIGHT LINE, a rough sense of how far it is — the
 * walked route is longer and only the server knows it (§ B5a, by hand):
 *   avatar at (4, 1), the picked location's pin at (10, 9)
 *   -> hypot(10 - 4, 9 - 1) = hypot(6, 8) = sqrt(36 + 64) = 10
 *   -> the bar shows "10 m".
 *
 * The actions live in PlayerApp (onTravel/onCancelTravel/onEnterRoom); this
 * component decides nothing the server has not already decided. Locks are the
 * server's word (task C2): `enterable === false` with the rule's own `reason`
 * marks a room chip as barred, and the reason is LOCALIZED BY THE SERVER and
 * shown as it is — running it through `t()` would look up a sentence no
 * translation file has.
 */
import { useEffect, useMemo, useState } from 'react'
import { apiGet } from '../lib/api'
import { useI18n } from '../i18n/I18nProvider'
import { usePoll } from './usePolling'
import { MapPanel, type LabelMode } from './MapPanel'
import type { TravelInfo } from './ScenePanel'

/** One room of the current location (`/play/scene → rooms[]`, § A14).
 *  `is_ground` marks the location's ground, `is_floor` the corridor of a
 *  storey (§ A13b) — both are rooms like any other, entered by their id, and
 *  the flags exist so a client can label them without knowing the reserved
 *  ids. `level` is the storey, `null` for a room without a layout. */
interface RoomInfo {
  id: string; name: string; is_entry: boolean; is_ground: boolean
  is_floor: boolean; level: number | null
  enterable: boolean; reason: string
}

/** The slice of the worldmap payload the pick bar needs — the MAP reads the
 *  full payload itself, under the same poll key. */
interface WorldMapLocation {
  id: string; name: string
  pos_x: number | null; pos_z: number | null
}
interface WorldMapLite {
  avatar: string
  locations: WorldMapLocation[]
  characters: Array<{ name: string; pos: { x: number; z: number } | null }>
}

/** The place the player clicked on the map — never a journey yet. */
interface Picked { id: string; name: string; distance_m: number | null }

export function TravelPanel({
  rooms, currentRoomId, currentLocationId, travel, busy,
  onTravel, onCancelTravel, onEnterRoom, labelMode = 'all', autoFit = false,
  partyFollower = false, partyLeaderName = '',
}: {
  rooms: RoomInfo[]
  currentRoomId: string
  /** The location the avatar stands in — the map marks it and refuses it as
   *  a destination. */
  currentLocationId: string
  /** The running journey from `/play/scene`, or null while standing still. */
  travel: TravelInfo | null
  busy: boolean
  onTravel: (locationId: string) => void
  onCancelTravel: () => void
  onEnterRoom: (roomId: string) => void
  /** Label mode of the map, held by PlayerApp (header button). */
  labelMode?: LabelMode
  /** The enlarged overlay always fits the world and never writes the docked
   *  panel's view back. */
  autoFit?: boolean
  /** The avatar is a party follower: no movement of its own (travel + room
   *  chips off), the leader pulls it along. */
  partyFollower?: boolean
  partyLeaderName?: string
}) {
  const { t } = useI18n()
  // Same key + interval as MapPanel: the hub shares one in-flight request and
  // its result, so the map below and this bar cost a single poll.
  const { data: world } = usePoll<WorldMapLite>(
    'play-worldmap', () => apiGet<WorldMapLite>('/play/worldmap'),
    { intervalMs: 10000, enabled: !partyFollower })

  // What the player clicked on the map. Which outlines may be clicked at all
  // is the map's decision (`onPickLocation` + anchored footprint) — here only
  // the name and the distance of the pick are looked up.
  //
  // The lookup runs against the FOGGED payload. An admin playing with the
  // map's "Show all locations" switch on can therefore pick an outline this
  // panel cannot resolve; the reset effect below drops such a pick right
  // away — the outline loses its selection and the bar falls back to the
  // hint. Accepted: the switch is an admin tool, and one plays with it off.
  const [pickedId, setPickedId] = useState('')
  const picked = useMemo<Picked | null>(() => {
    const l = (world?.locations || []).find((x) => x.id === pickedId)
    if (!l || l.pos_x === null || l.pos_z === null) return null
    const me = (world?.characters || []).find((c) => c.name === world?.avatar)
    const d = me?.pos ? Math.hypot(l.pos_x - me.pos.x, l.pos_z - me.pos.z) : null
    return { id: l.id, name: l.name || l.id, distance_m: d }
  }, [world, pickedId])
  // The pick is forgotten as soon as it stops being a destination: a journey
  // starts (the status block takes the map's place), the avatar ARRIVES there
  // (or is carried there by its party leader), or the place drops out of the
  // payload altogether. Otherwise the bar would keep offering a trip to the
  // very spot one is standing on.
  useEffect(() => {
    if (travel || pickedId === currentLocationId
      || (pickedId && !world?.locations?.some((l) => l.id === pickedId))) {
      setPickedId('')
    }
  }, [travel, pickedId, currentLocationId, world])

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
      {/* On top: the running journey, or the map one picks a destination on. */}
      {travel ? (
        // The status box keeps its natural height; the wrapper takes the rest
        // of the panel, so the room chips stay where they were.
        <div style={{ flex: '1 1 auto', minHeight: 0, overflowY: 'auto' }}>
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
        </div>
      ) : (
        <div style={{ flex: '1 1 auto', minHeight: 120, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <MapPanel currentLocationId={currentLocationId} labelMode={labelMode}
              autoFit={autoFit} onPickLocation={setPickedId} pickedId={pickedId} />
          </div>
          {/* The pick bar: what was clicked, how far it is as the crow flies,
              and the ONE button that actually sets off. */}
          <div style={{
            flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 6,
            fontSize: '0.82em', padding: '4px 0',
          }}>
            {picked ? (
              <>
                <span style={{
                  flex: '1 1 auto', minWidth: 0, overflow: 'hidden',
                  textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }} title={picked.name}>{picked.name}</span>
                {picked.distance_m !== null && (
                  <span style={{ flex: '0 0 auto', fontSize: '0.9em', opacity: 0.55 }}>
                    {Math.round(picked.distance_m)} m
                  </span>
                )}
                <button onClick={() => onTravel(picked.id)} disabled={busy}
                  style={{
                    flex: '0 0 auto', padding: '2px 8px', borderRadius: 10,
                    fontSize: '0.92em', cursor: busy ? 'default' : 'pointer',
                    border: '1px solid var(--border, #30363d)',
                    background: 'var(--bg-hover, #1f2937)', color: 'inherit',
                  }}>
                  {t('Travel')}
                </button>
              </>
            ) : (
              <span style={{ opacity: 0.6 }}>
                {t('Pick a place on the map to travel there.')}
              </span>
            )}
          </div>
        </div>
      )}

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
