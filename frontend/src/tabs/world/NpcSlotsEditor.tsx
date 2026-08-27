import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
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
// "Character" BINDS the slot to one existing temporary NPC. A bound slot never
// generates anybody: it revives exactly that sheet out of the recycling pool
// or, when the NPC is alive somewhere else, stamps the slot on it and moves it
// here — without pooling it, so it keeps everything the world remembers about
// it. Only temporary NPCs can be bound; a full character has a place of its
// own in this world.
//
// The same editor authors the slots of a PAINTED TERRAIN AREA (§ E3.2,
// `variant="area"`). There the polygon IS the home, so neither of those two
// fields exists: no rooms to pick and no radius to draw a second shape with.

const CUSTOM_DEFAULT = '20:00-06:00'

/** One NPC the slot may be bound to — living or waiting in the pool. */
interface BindableNpc {
  name: string
  /** Its current slot role, only used to tell two invented names apart. */
  role?: string
}

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
  // Everything a slot may be bound to: the LIVING temporary NPCs and the
  // pooled sheets, in one list — a pooled NPC is on no other roster, and it is
  // the more interesting half (binding is what brings a kept sheet back).
  const [bindable, setBindable] = useState<BindableNpc[]>([])
  useEffect(() => {
    apiGet<{ npcs?: { name: string; slot_role?: string }[]
             pooled?: { name: string; role?: string }[] }>('/npc/list')
      .then((r) => {
        const seen = new Set<string>()
        const out: BindableNpc[] = []
        for (const n of [
          ...(r.npcs || []).map((n) => ({ name: n.name, role: n.slot_role })),
          ...(r.pooled || []).map((p) => ({ name: p.name, role: p.role })),
        ]) {
          if (!n.name || seen.has(n.name)) continue
          seen.add(n.name)
          out.push(n)
        }
        setBindable(out)
      })
      .catch(() => setBindable([]))
  }, [])
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
        ? { role: '', character: '', count_min: 1, count_max: 1, briefing: '', when: '' }
        : {
          role: '',
          character: '',
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
      {/* Three rows per slot, not one: the eight controls do not fit a single
          line at a usual editor width, and stretching them until they do is
          what made every one of them a sliver. Identity and counts first, the
          placement/window second, the free text last. */}
      {slots.map((slot, idx) => (
        <div
          key={idx}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            paddingBottom: 8,
            borderBottom: '1px solid var(--border, #30363d)',
          }}
        >
        <div className="ga-form-row" style={{ alignItems: 'flex-end' }}>
          <Field
            label={t('Role')}
            tip={t('The tag an NPC of this slot carries. Also what a recycled NPC is matched on.')}
          >
            <input
              className="ga-input"
              value={slot.role || ''}
              placeholder={t('e.g. barkeeper')}
              onChange={(e) => update(idx, { role: e.target.value })}
            />
          </Field>
          <Field
            label={t('Character')}
            tip={t('Bind this slot to one existing NPC — only temporary NPCs. It is revived from the pool or moved here from wherever it stands, and nobody new is ever generated for this slot.')}
          >
            <select
              className="ga-input"
              value={slot.character || ''}
              onChange={(e) => update(idx, { character: e.target.value })}
            >
              <option value="">— {t('generate new')} —</option>
              {bindable.map((n) => (
                <option key={n.name} value={n.name}>
                  {n.role ? `${n.name} (${n.role})` : n.name}
                </option>
              ))}
              {/* A bound name the list does not know any more — an NPC deleted
                  since, or one the list has not loaded yet. Kept as an option
                  so opening the editor cannot silently unbind the slot. */}
              {!!slot.character && !bindable.some((n) => n.name === slot.character) && (
                <option value={slot.character}>{slot.character}</option>
              )}
            </select>
          </Field>
          <Field
            label={t('Min')}
            compact
            tip={slot.character ? t('A bound slot is exactly one NPC.') : undefined}
          >
            <input
              type="number"
              className="ga-input"
              min={0}
              max={20}
              disabled={!!slot.character}
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
              disabled={!!slot.character}
              style={{ width: 70 }}
              value={slot.count_max ?? 1}
              onChange={(e) => update(idx, { count_max: parseInt(e.target.value, 10) || 0 })}
            />
          </Field>
        </div>
        <div className="ga-form-row" style={{ alignItems: 'flex-end' }}>
          {!isArea && (
          <Field
            label={t('Room')}
            compact
            tip={
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
            tip={t("0 = inside the location's rooms. Above 0 the NPC stands at a free point within this many metres of the place and roams there.")}
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
            tip={t('Outside its window nobody is placed here and the NPCs of this slot go back into the pool.')}
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
            <Field label={t('Game time')} compact tip={t('From (inclusive) — to (exclusive); a window may span midnight.')}>
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
        </div>
        <div className="ga-form-row" style={{ alignItems: 'flex-end' }}>
          <Field
            label={t('Briefing')}
            tip={t('What the generator should know about this person.')}
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
