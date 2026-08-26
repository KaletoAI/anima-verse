import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { groundRoomLabel, type NpcSlot, type Room } from './worldTypes'

// ── NPC slots of a location or of a painted area ──────────────────────────
// What a place wants staffed (plan-npc-auto-spawn.md § 1). The server fills a
// slot on its own once the avatar walks near: it counts the living NPCs
// tagged with the ROLE and generates — or recycles out of the pool — what is
// missing. So everything here is authoring, not a live roster: who should be
// here, how many, and what the generator should know about them.
//
// "Active" is the slot's time window in GAME time (spec § E2): outside it
// nobody is generated and the NPCs standing in the slot go back into the pool
// — the forest's robbers are gone by daylight. It is stored in one field,
// `when`: '' = always, 'night'/'day' follow the season's sunrise/sunset, and
// a custom window is the literal 'HH:MM-HH:MM' the two clock inputs build.
//
// "Radius (m)" is the slot's HOME AREA (spec § E3.1): 0 places the NPC in a
// room as before, anything above it puts it at a free point that many metres
// around the place, where it roams instead of changing rooms. It WINS over
// the room — which is why the room select goes dead as soon as it is set.
//
// The same editor authors the slots of a PAINTED TERRAIN AREA (§ E3.2,
// `variant="area"`). There the polygon IS the home, so neither of those two
// fields exists: no rooms to pick and no radius to draw a second shape with.

const CUSTOM_DEFAULT = '20:00-06:00'

type WhenMode = 'always' | 'night' | 'day' | 'custom'

/** The select's value for a stored `when` — anything with a dash is custom. */
function whenMode(when: string | undefined): WhenMode {
  const v = (when || '').trim().toLowerCase()
  if (!v) return 'always'
  if (v === 'night' || v === 'day') return v
  return 'custom'
}

/** The two halves of a custom window; the default for everything else. */
function whenSpan(when: string | undefined): [string, string] {
  const parts = (when || '').split('-')
  if (parts.length !== 2) return CUSTOM_DEFAULT.split('-') as [string, string]
  return [parts[0].trim(), parts[1].trim()]
}
interface NpcSlotsEditorProps {
  /** Persisted id — the "Fill now" button needs a saved location. Only the
   *  `location` variant has one. */
  locationId?: string
  /** The painted area's id, for the `area` variant — same role as above. */
  areaId?: string
  rooms?: Room[]
  value: NpcSlot[] | undefined
  onChange: (next: NpcSlot[]) => void
  /**
   * WHAT DECLARES THESE SLOTS — a place or a painted terrain area
   * (spec § E3.2). An AREA is itself the NPC's home, so the two fields that
   * describe a place's inside are not offered at all: it has no rooms, and a
   * radius would draw a second shape beside the polygon the author painted.
   * The server forces both to empty on the way in (`terrain.sanitize_area`),
   * so this is the surface half of one rule, not a second one.
   */
  variant?: 'location' | 'area'
}

export function NpcSlotsEditor({
  locationId, areaId, rooms, value, onChange, variant = 'location',
}: NpcSlotsEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [filling, setFilling] = useState(false)
  const slots = value || []
  const isArea = variant === 'area'
  const ownerId = (isArea ? areaId : locationId) || ''
  const roomList = rooms || []

  const update = (idx: number, patch: Partial<NpcSlot>) => {
    onChange(slots.map((s, i) => (i === idx ? { ...s, ...patch } : s)))
  }
  const remove = (idx: number) => onChange(slots.filter((_, i) => i !== idx))
  const add = () =>
    onChange([
      ...slots,
      isArea
        // No `room`/`radius_m` at all: the area is the home, and sending two
        // keys the server forces empty would only make the stored slot and
        // the drafted one look different.
        ? { role: '', count_min: 1, count_max: 1, briefing: '', when: '' }
        : {
          role: '',
          count_min: 1,
          count_max: 1,
          briefing: '',
          room: '',
          when: '',
          radius_m: 0,
        },
    ])

  const fillNow = async () => {
    setFilling(true)
    try {
      await apiPost(isArea
        ? `/npc/areas/${ownerId}/fill`
        : `/npc/slots/${ownerId}/fill`, {})
      toast(t('Spawn check queued — the NPCs appear once the generator is done.'))
    } catch (e) {
      toast(String(e), 'error')
    } finally {
      setFilling(false)
    }
  }

  return (
    <div className="ga-form">
      {slots.length === 0 && (
        <div className="ga-muted" style={{ marginBottom: 8 }}>
          {t('No NPC slots — nobody is placed here automatically.')}
        </div>
      )}
      {isArea && slots.length > 0 && (
        <div className="ga-muted" style={{ marginBottom: 8 }}>
          {t('The area itself is the home: its NPCs stand at a free point inside the outline and roam there. No rooms, no radius.')}
        </div>
      )}
      {slots.map((slot, idx) => (
        <div key={idx} className="ga-form-row" style={{ alignItems: 'flex-end' }}>
          <Field
            label={t('Role')}
            hint={t('The tag an NPC of this slot carries. Also what a recycled NPC is matched on.')}
          >
            <input
              className="ga-input"
              value={slot.role || ''}
              placeholder={t('e.g. barkeeper')}
              onChange={(e) => update(idx, { role: e.target.value })}
            />
          </Field>
          <Field label={t('Min')} compact>
            <input
              type="number"
              className="ga-input"
              min={0}
              max={20}
              style={{ width: 70 }}
              value={slot.count_min ?? 1}
              onChange={(e) => update(idx, { count_min: parseInt(e.target.value, 10) || 0 })}
            />
          </Field>
          <Field label={t('Max')} compact>
            <input
              type="number"
              className="ga-input"
              min={0}
              max={20}
              style={{ width: 70 }}
              value={slot.count_max ?? 1}
              onChange={(e) => update(idx, { count_max: parseInt(e.target.value, 10) || 0 })}
            />
          </Field>
          {!isArea && (
          <Field
            label={t('Room')}
            compact
            hint={
              (slot.radius_m || 0) > 0
                ? t('Ignored — this slot has a home area instead of a room.')
                : undefined
            }
          >
            <select
              className="ga-input"
              disabled={(slot.radius_m || 0) > 0}
              value={slot.room || ''}
              onChange={(e) => update(idx, { room: e.target.value })}
            >
              <option value="">— {t('arrival room')} —</option>
              {roomList.filter((r) => !!r.id).map((r) => (
                <option key={r.id} value={r.id || ''}>
                  {r.name?.trim() || groundRoomLabel(r, t)}
                </option>
              ))}
            </select>
          </Field>
          )}
          {!isArea && (
          <Field
            label={t('Radius (m)')}
            compact
            hint={t("0 = inside the location's rooms. Above 0 the NPC stands at a free point within this many metres of the place and roams there.")}
          >
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input
                type="number"
                className="ga-input"
                min={0}
                max={2000}
                step={5}
                style={{ width: 90 }}
                value={slot.radius_m ?? 0}
                onChange={(e) =>
                  update(idx, { radius_m: Math.max(0, parseInt(e.target.value, 10) || 0) })
                }
              />
              {(slot.radius_m || 0) > 0 && (
                <span className="ga-muted" style={{ whiteSpace: 'nowrap' }}>
                  {t('{n} m across').replace('{n}', String((slot.radius_m || 0) * 2))}
                </span>
              )}
            </div>
          </Field>
          )}
          <Field
            label={t('Active')}
            compact
            hint={t('Outside its window nobody is placed here and the NPCs of this slot go back into the pool.')}
          >
            <select
              className="ga-input"
              value={whenMode(slot.when)}
              onChange={(e) => {
                const mode = e.target.value as WhenMode
                update(idx, {
                  when:
                    mode === 'always'
                      ? ''
                      : mode === 'custom'
                        ? whenSpan(slot.when).join('-')
                        : mode,
                })
              }}
            >
              <option value="always">{t('always')}</option>
              <option value="night">{t('at night')}</option>
              <option value="day">{t('by day')}</option>
              <option value="custom">{t('time window…')}</option>
            </select>
          </Field>
          {whenMode(slot.when) === 'custom' && (
            <Field label={t('Game time')} compact hint={t('From (inclusive) — to (exclusive); a window may span midnight.')}>
              <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <input
                  type="time"
                  className="ga-input"
                  style={{ width: 110 }}
                  value={whenSpan(slot.when)[0]}
                  onChange={(e) =>
                    update(idx, { when: `${e.target.value || '00:00'}-${whenSpan(slot.when)[1]}` })
                  }
                />
                <span className="ga-muted">–</span>
                <input
                  type="time"
                  className="ga-input"
                  style={{ width: 110 }}
                  value={whenSpan(slot.when)[1]}
                  onChange={(e) =>
                    update(idx, { when: `${whenSpan(slot.when)[0]}-${e.target.value || '00:00'}` })
                  }
                />
              </div>
            </Field>
          )}
          <Field
            label={t('Briefing')}
            hint={t('What the generator should know about this person.')}
          >
            <textarea
              className="ga-textarea"
              rows={2}
              value={slot.briefing || ''}
              onChange={(e) => update(idx, { briefing: e.target.value })}
            />
          </Field>
          <button className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => remove(idx)}>
            {t('Remove')}
          </button>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <button className="ga-btn ga-btn-sm" onClick={add}>
          {t('+ NPC slot')}
        </button>
        <button
          className="ga-btn ga-btn-sm"
          disabled={filling || !ownerId || slots.length === 0}
          onClick={fillNow}
          title={t('Runs the same check the avatar triggers by walking near.')}
        >
          {filling ? t('Queueing…') : t('Fill now')}
        </button>
        <span className="ga-muted">
          {t('Save first — the check reads the stored slots.')}
        </span>
      </div>
    </div>
  )
}
