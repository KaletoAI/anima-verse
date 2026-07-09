import { type Dispatch, type SetStateAction } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { Field } from '../../components/Field'
import type { LocationRef, RoomRef } from '../../lib/refs'
import type { CurrentLocation, DraftPlacement } from './CharactersTab'

// Canonical moods — kept in sync with shared/config/moods.json. Updating
// the file requires updating this list, but moods rarely change so the
// duplication is acceptable; alternative would be a /moods endpoint.
const MOODS: Array<{ id: string; label: string }> = [
  { id: 'pleased', label: 'pleased' },
  { id: 'happy', label: 'happy' },
  { id: 'relaxed', label: 'relaxed' },
  { id: 'refreshed', label: 'refreshed' },
  { id: 'creative', label: 'creative' },
  { id: 'chatty', label: 'chatty' },
  { id: 'chatting', label: 'chatting' },
  { id: 'exuberant', label: 'exuberant' },
  { id: 'euphoric', label: 'euphoric' },
  { id: 'exhausted', label: 'exhausted' },
  { id: 'drunk', label: 'drunk' },
  { id: 'sweating', label: 'sweating' },
]

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
                {r.name || r.id}
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
            {draft.feeling && !MOODS.some((m) => m.id === draft.feeling) ? (
              <option value={draft.feeling}>{draft.feeling}</option>
            ) : null}
            {MOODS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={t('Activity')}
          hint={
            current.current_activity
              ? t('Currently: {name}').replace('{name}', current.current_activity)
              : t('Free text — what the character is currently doing.')
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
