import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useMoods } from '../../lib/moods'
import { Field } from '../../components/Field'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { ApiError, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { LocationRef, RoomRef } from '../../lib/refs'
import { roomLabel } from '../world/worldTypes'
import type { CurrentLocation, DraftPlacement } from './CharactersTab'

/**
 * Editable "current state" placement — rendered as a special slot
 * (section.special === "placement") in column 3 of the General tab.
 *
 * The selects feed the sheet's own Save (POST .../current-location). Next to
 * them sits the ADMIN TELEPORT: "Place here" puts the character at the picked
 * location/room immediately via POST /characters/{name}/place-on-map, which
 * cancels a running journey first and then goes through the normal arrival —
 * activity reset, standing point, discovery, party pull. It is admin-only and
 * refuses a party FOLLOWER (only the leader moves); the dialog offers to let
 * the follower leave the party instead.
 */
export function PlacementEditor({
  character,
  current,
  draft,
  setDraft,
  currentFeeling,
  locations,
  rooms,
  onPlaced,
}: {
  character: string
  current: CurrentLocation
  draft: DraftPlacement
  setDraft: Dispatch<SetStateAction<DraftPlacement | null>>
  currentFeeling: string
  locations: LocationRef[]
  rooms: RoomRef[]
  /** Called after a successful placement so the sheet re-reads the state. */
  onPlaced: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const moods = useMoods()
  const [placing, setPlacing] = useState(false)
  /** Set while the server refused because the character follows a party. */
  const [followerNote, setFollowerNote] = useState('')

  const place = useCallback(
    async (leaveParty: boolean) => {
      if (!character || !draft.locationId || placing) return
      setPlacing(true)
      try {
        await apiPost(`/characters/${encodeURIComponent(character)}/place-on-map`, {
          location_id: draft.locationId,
          current_room: draft.roomId || '',
          leave_party: leaveParty,
        })
        setFollowerNote('')
        toast(t('Character placed'))
        onPlaced()
      } catch (e) {
        const err = e as ApiError
        const detail = err.detail as { reason?: string; message?: string } | undefined
        if (err.status === 409 && detail?.reason === 'party_follower') {
          setFollowerNote(detail.message || '')
        } else {
          toast(t('Error') + ': ' + (e as Error).message, 'error')
        }
      } finally {
        setPlacing(false)
      }
    },
    [character, draft.locationId, draft.roomId, onPlaced, placing, t, toast],
  )

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
      <div className="ga-form-row">
        <Field
          label={t('Place on the map')}
          hint={t('Puts the character at the picked location right away — a teleport: a running journey is cancelled, the activity is reset and a party follows along. Without a room it lands in the entry room.')}
        >
          <button
            className="ga-btn ga-btn-sm"
            type="button"
            disabled={!draft.locationId || placing}
            onClick={() => { void place(false) }}
          >
            {placing ? t('Placing…') : t('Place here')}
          </button>
        </Field>
      </div>
      <ConfirmDialog
        open={!!followerNote}
        title={t('Leave the party?')}
        message={followerNote}
        confirmLabel={t('Leave the party and place')}
        onConfirm={() => { void place(true) }}
        onClose={() => setFollowerNote('')}
      />
    </>
  )
}
