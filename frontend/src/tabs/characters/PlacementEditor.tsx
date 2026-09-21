import { type Dispatch, type SetStateAction } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useMoods } from '../../lib/moods'
import { Field } from '../../components/Field'
import type { LocationRef, RoomRef } from '../../lib/refs'
import { roomLabel } from '../world/worldTypes'
import type { CurrentLocation, DraftPlacement } from './CharactersTab'

/**
 * Editable "current state" placement — rendered as a special slot
 * (section.special === "placement") in column 3 of the General tab.
 */
export function PlacementEditor({
  current,
  draft,
  setDraft,
  currentFeeling,
  locations,
  rooms,
}: {
  current: CurrentLocation
  draft: DraftPlacement
  setDraft: Dispatch<SetStateAction<DraftPlacement | null>>
  currentFeeling: string
  locations: LocationRef[]
  rooms: RoomRef[]
}) {
  const { t } = useI18n()
  const moods = useMoods()
  return (
    <>
      <div className="ga-form-row">
        <Field
          label={t('Location')}
          hint={
            current.current_location
              ? t('Currently at: {name}').replace('{name}', current.current_location)
              : t('Currently nowhere — pick a location to place the character.')
          }
        >
          <select
            className="ga-input"
            value={draft.locationId}
            onChange={(e) => setDraft({ ...draft, locationId: e.target.value, roomId: '' })}
          >
            <option value="">— {t('nowhere')} —</option>
            {locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name || l.id}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={t('Room')}
          hint={
            rooms.length === 0
              ? t('Pick a location with rooms to choose a room.')
              : current.current_room_name
                ? t('Currently in: {name}').replace('{name}', current.current_room_name)
                : t('Optional — leave empty for "anywhere in this location".')
          }
        >
          <select
            className="ga-input"
            value={draft.roomId}
            onChange={(e) => setDraft({ ...draft, roomId: e.target.value })}
            disabled={rooms.length === 0}
          >
            <option value="">— {t('any room')} —</option>
            {rooms.map((r) => (
              <option key={r.id} value={r.id || ''}>
                {roomLabel(r, t)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="ga-form-row">
        <Field
          label={t('Mood')}
          hint={
            currentFeeling
              ? t('Currently: {name}').replace('{name}', currentFeeling)
              : t('Canonical mood id from shared/config/moods.json. Empty clears the mood.')
          }
        >
          <select
            className="ga-input"
            value={draft.feeling}
            onChange={(e) => setDraft({ ...draft, feeling: e.target.value })}
          >
            <option value="">— {t('none')} —</option>
            {draft.feeling && !moods.includes(draft.feeling) ? (
              <option value={draft.feeling}>{draft.feeling}</option>
            ) : null}
            {moods.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={t('Activity')}
          hint={
            current.current_activity
              ? t('Currently: {name}').replace('{name}', current.current_activity)
              : t('Free text — what the character is currently doing. Saving wakes a sleeping character.')
          }
        >
          <input
            className="ga-input"
            type="text"
            value={draft.activity}
            placeholder={t('e.g. reading a book')}
            onChange={(e) => setDraft({ ...draft, activity: e.target.value })}
          />
        </Field>
      </div>
    </>
  )
}
