/**
 * PlanOpeningStrip — the selected opening in a room wall: what kind of hole it
 * is, how big, where it leads, and which door hangs in it.
 *
 * THE THREE SIZES ARE COMMITTED ON BLUR, not on every keystroke: a number
 * field that writes while one types turns "1.2" into a 1 m opening the moment
 * the digit lands, and the plan redraws under the cursor. The `key` on each
 * input carries the stored value, so an outside change (an undo, another
 * strip) still refreshes what the field shows.
 */
import { useI18n } from '../../i18n/I18nProvider'
import { OpeningDoorProp } from './DoorPropPicker'
import type { Room, RoomOpening } from './worldTypes'

interface Props {
  opening: RoomOpening
  /** Index in the room's `openings`, for the door picker's key — the "Custom,
   *  nothing picked yet" state must never travel to the next opening. */
  index: number
  /** Every OTHER room of the location — where a door may lead. */
  otherRooms: Room[]
  /** The location's fallback door prop, named as the first option. */
  defaultDoorPropId: string
  /** Merge a patch into this opening, or remove it when null is passed. */
  onPatch: (patch: Partial<RoomOpening> | null) => void
}

export function PlanOpeningStrip({
  opening: op, index, otherRooms, defaultDoorPropId, onPatch,
}: Props) {
  const { t } = useI18n()

  const numField = (
    field: 'width_m' | 'height_m' | 'sill_m', label: string, max: number,
  ) => (
    <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}>
      {label}
      <input
        key={`${field}-${op[field]}`}
        className="ga-input"
        type="number"
        min={field === 'sill_m' ? 0 : 0.4}
        max={max}
        step={0.1}
        style={{ width: 64 }}
        defaultValue={op[field]}
        onBlur={(e) => {
          const n = parseFloat(e.target.value)
          if (Number.isFinite(n) && n !== op[field]) {
            onPatch({ [field]: Math.round(n * 1000) / 1000 })
          }
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
        }}
      />
    </label>
  )

  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint" style={{ fontWeight: 600 }}>
        🚪 {typeof op.edge === 'string' ? op.edge : `#${op.edge}`} · {op.type}:
      </span>
      <select
        className="ga-input"
        style={{ width: 110 }}
        value={op.type}
        onChange={(e) => onPatch({ type: e.target.value as RoomOpening['type'] })}
        title={t('Door, window or open passage.')}
      >
        <option value="door">{t('Door')}</option>
        <option value="window">{t('Window')}</option>
        <option value="passage">{t('Passage')}</option>
      </select>
      {numField('width_m', t('W (m)'), 10)}
      {numField('height_m', t('H (m)'), 10)}
      {numField('sill_m', t('Sill (m)'), 3)}
      <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Where a door/passage leads — another room or outside. Windows leave it empty.')}>
        {t('to')}
        <select
          className="ga-input"
          style={{ width: 130 }}
          value={op.to ?? ''}
          onChange={(e) => onPatch({ to: e.target.value || undefined })}
        >
          <option value="">{t('— none —')}</option>
          <option value="outside">{t('outside')}</option>
          {otherRooms.map((r) => (
            <option key={r.id} value={r.id}>{r.name || r.id}</option>
          ))}
        </select>
      </label>
      {/* WHICH DOOR hangs in this hole. Only a door has one — a window takes
          no prop and a passage is the open gap by definition
          (`scene_recipe.door_prop_id`). */}
      {op.type === 'door' ? (
        <OpeningDoorProp
          key={index}
          opening={op}
          defaultPropId={defaultDoorPropId}
          onPatch={onPatch}
        />
      ) : null}
      <button
        type="button"
        className="ga-btn ga-btn-sm ga-btn-danger"
        onClick={() => onPatch(null)}
        title={t('Remove this opening')}
      >
        × {t('Remove')}
      </button>
    </div>
  )
}
