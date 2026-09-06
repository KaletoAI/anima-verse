/**
 * PlanRoomPicker — pick a room WITHOUT touching the plan.
 *
 * Small, overlapping or stacked rooms are hard to hit, and hitting them used
 * to move them. Two lists: what is ON the plan (a click selects, nothing
 * moves) and what is NOT (a click arms the hull pen for that room, which is
 * the way in for a location whose rooms have no layout yet — there is nothing
 * selectable on the plan then except the yard, and the yard turns every room
 * tool off).
 *
 * THE YARD IS ALWAYS FIRST (§ A13a): it is the one shape nobody draws, it lies
 * under everything else, and it is the hardest thing on the plan to hit on
 * purpose.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { GROUND_ROOM_ID } from './worldTypes'
import type { Room } from './worldTypes'

interface Props {
  /** Rooms with a rectangle on the plan, any storey. */
  placed: Room[]
  /** Rooms this location has that are not drawn anywhere yet. */
  unplaced: Room[]
  /** The yard exists as a room at all (§ A13a). */
  hasYard: boolean
  /** …and has a layout to select. Without a drawn boundary it has no area,
   *  so the chip is offered but disabled and says why. */
  yardPlaced: boolean
  yardName: string
  selected: string
  onSelect: (roomId: string) => void
  /** Selecting the yard pulls the editor to storey 0, where it lives. */
  onSelectYard: () => void
  /** The hull pen is armed for this room right now ('' = for none). */
  drawTarget: string
  drawing: boolean
  onDraw: (roomId: string) => void
}

export function PlanRoomPicker({
  placed, unplaced, hasYard, yardPlaced, yardName, selected, onSelect,
  onSelectYard, drawTarget, drawing, onDraw,
}: Props) {
  const { t } = useI18n()
  return (
    <>
      {placed.length || hasYard ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="ga-hint">{t('On the plan:')}</span>
          {hasYard ? (
            <button
              type="button"
              className={`ga-btn ga-btn-sm${selected === GROUND_ROOM_ID ? ' ga-btn-primary' : ''}`}
              disabled={!yardPlaced}
              onClick={onSelectYard}
              title={yardPlaced
                ? t('Select the yard — the location surface. Props, scattered props and markers stand on the terrain here; it has no room geometry.')
                : t('No boundary drawn: this location has no area, so it has no yard to furnish either. Draw its footprint on the map tab first.')}
            >
              ⬚ {yardName}
            </button>
          ) : null}
          {placed.map((room) => (
            <button
              key={room.id || room.name}
              type="button"
              className={`ga-btn ga-btn-sm${selected === room.id ? ' ga-btn-primary' : ''}`}
              onClick={() => onSelect(room.id || '')}
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
              className={`ga-btn ga-btn-sm${drawing && drawTarget === room.id ? ' ga-btn-primary' : ''}`}
              onClick={() => onDraw(room.id || '')}
              title={t('Draw this room on the current level — click to place points, click the first point to close, Shift = free-hand, Esc = cancel.')}
            >
              ⬠ {room.name || room.id}
            </button>
          ))}
        </div>
      ) : null}
    </>
  )
}
