import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { groundRoomLabel, type NpcSlot, type Room } from './worldTypes'

// ── NPC slots of a location ───────────────────────────────────────────────
// What a place wants staffed (plan-npc-auto-spawn.md § 1). The server fills a
// slot on its own once the avatar walks near: it counts the living NPCs
// tagged with the ROLE and generates — or recycles out of the pool — what is
// missing. So everything here is authoring, not a live roster: who should be
// here, how many, and what the generator should know about them.
interface NpcSlotsEditorProps {
  /** Persisted id — the "Fill now" button needs a saved location. */
  locationId: string
  rooms: Room[]
  value: NpcSlot[] | undefined
  onChange: (next: NpcSlot[]) => void
}

export function NpcSlotsEditor({ locationId, rooms, value, onChange }: NpcSlotsEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [filling, setFilling] = useState(false)
  const slots = value || []

  const update = (idx: number, patch: Partial<NpcSlot>) => {
    onChange(slots.map((s, i) => (i === idx ? { ...s, ...patch } : s)))
  }
  const remove = (idx: number) => onChange(slots.filter((_, i) => i !== idx))
  const add = () =>
    onChange([...slots, { role: '', count_min: 1, count_max: 1, briefing: '', room: '' }])

  const fillNow = async () => {
    setFilling(true)
    try {
      await apiPost(`/npc/slots/${locationId}/fill`, {})
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
          <Field label={t('Room')} compact>
            <select
              className="ga-input"
              value={slot.room || ''}
              onChange={(e) => update(idx, { room: e.target.value })}
            >
              <option value="">— {t('arrival room')} —</option>
              {rooms.filter((r) => !!r.id).map((r) => (
                <option key={r.id} value={r.id || ''}>
                  {r.name?.trim() || groundRoomLabel(r, t)}
                </option>
              ))}
            </select>
          </Field>
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
          disabled={filling || !locationId || slots.length === 0}
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
