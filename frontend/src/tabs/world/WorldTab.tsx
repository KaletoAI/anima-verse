import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ListHeader } from '../../components/ListHeader'
import { ExportButton, ImportButton, PublishButton } from '../../components/ImportExport'
import { loadItems, type ItemRef } from '../../lib/refs'
import { STYLE_HINT_OPTIONS } from '../../lib/styleHints'
import { ImageGenDialog, type ImageGenSubmit } from '../../components/ImageGenDialog'

interface Room {
  id?: string
  name?: string
  description?: string
  // Decency (plan-outfit-system-rethink.md §1.1) — ersetzt das alte outfit_type-Modell
  decency?: '' | 'public' | 'private' | 'nude_ok'
  style_hint?: string
  swim_allowed?: boolean
  activity_hint?: string
  image_prompt_day?: string
  image_prompt_night?: string
}

interface EventSettings {
  event_probability?: number
  max_concurrent_events?: number
  event_cooldown_hours?: number
  allowed_categories?: string[]
  event_blacklist?: string[]
}

interface Location {
  id: string
  name: string
  description?: string
  rooms?: Room[]
  entry_room?: string
  danger_level?: number
  indoor?: string
  decency?: '' | 'public' | 'private' | 'nude_ok'
  style_hint?: string
  swim_allowed?: boolean
  activity_hint?: string
  knowledge_item_id?: string
  passable?: boolean
  image_prompt_day?: string
  image_prompt_night?: string
  image_prompt_map_2d?: string
  image_count?: number
  is_template?: boolean
  template_location_id?: string
  grid_x?: number | null
  grid_y?: number | null
  map_image_2d?: string
  event_settings?: EventSettings
}

const EVENT_CATEGORIES = ['ambient', 'social', 'disruption', 'danger'] as const

// Danger level scale (0–5). Drives hourly stamina/stat drain (danger_system.py)
// and danger-based block rules. Labels describe what each step means.
const DANGER_LEVELS: Array<{ value: number; label: string }> = [
  { value: 0, label: 'Safe' },
  { value: 1, label: 'Low' },
  { value: 2, label: 'Moderate' },
  { value: 3, label: 'High' },
  { value: 4, label: 'Severe' },
  { value: 5, label: 'Extreme' },
]

interface GalleryResponse {
  images: string[]
  image_rooms?: Record<string, string>
  image_types?: Record<string, string>
  image_metas?: Record<string, { backend?: string; model?: string; loras?: string[] }>
}

const IMAGE_TYPES = ['', 'day', 'night', 'map_2d'] as const

type Selection =
  | { kind: 'location'; locationId: string }
  | { kind: 'room'; locationId: string; roomId: string }
  | null

export function WorldTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [locations, setLocations] = useState<Location[] | null>(null)
  // Ungefilterte Liste inkl. Klon-Platzierungen — fuer die „auf der Karte
  // verwendet"-Zaehlung in der Galerie (Klone tragen map_image_2d + grid).
  const [placements, setPlacements] = useState<Location[]>([])
  const [selection, setSelection] = useState<Selection>(null)
  const [items, setItems] = useState<ItemRef[]>([])

  const reload = useCallback(async () => {
    try {
      const data = await apiGet<{ locations?: Location[] }>('/world/locations')
      // Show templates (and normal locations); hide their thin clone
      // placements. Clones only carry grid_x/grid_y plus a pointer to
      // the template — all editable data (description, prompts, rooms)
      // lives on the template. Editing happens here in the World tab;
      // placement (clones) lives in the Map tab.
      const all = data.locations || []
      setPlacements(all)
      const visible = all.filter((l) => !(l.template_location_id || '').trim())
      // Dedupe by lowercased name as a final guard against legacy data
      // with duplicate labels.
      const seen = new Map<string, Location>()
      for (const loc of visible) {
        const key = (loc.name || loc.id || '').toLowerCase().trim()
        if (!key) continue
        if (!seen.has(key)) seen.set(key, loc)
      }
      setLocations(Array.from(seen.values()))
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    }
  }, [t, toast])

  useEffect(() => {
    reload()
    loadItems().then(setItems).catch(() => setItems([]))
  }, [reload])

  const newLocation = useCallback(async () => {
    const name = window.prompt(t('Name of the new location'))
    if (!name?.trim()) return
    try {
      await apiPost('/world/locations', { name: name.trim(), description: '', rooms: [] })
      toast(t('Location created'))
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [reload, t, toast])

  const copyLocation = useCallback(async () => {
    if (!locations || !selection || selection.kind !== 'location') return
    const src = locations.find((l) => l.id === selection.locationId)
    if (!src) return
    const newName = window.prompt(t('Name of the copy'), `${src.name} (copy)`)
    if (!newName?.trim()) return
    try {
      await apiPost('/world/locations', {
        name: newName.trim(),
        description: src.description || '',
        // Drop each room's id so the backend assigns FRESH ones — otherwise the
        // copy keeps the source's room IDs and everything keyed by room id
        // (gallery image_rooms, room items, image gen with room_id) collides.
        rooms: (src.rooms || []).map(({ id: _id, ...rest }) => rest),
        image_prompt_day: src.image_prompt_day || '',
        image_prompt_night: src.image_prompt_night || '',
        image_prompt_map_2d: src.image_prompt_map_2d || '',
        danger_level: src.danger_level,
        indoor: src.indoor || '',
        decency: src.decency,
        style_hint: src.style_hint,
        swim_allowed: src.swim_allowed,
        activity_hint: src.activity_hint,
        knowledge_item_id: src.knowledge_item_id,
        passable: src.passable,
      })
      toast(t('Location copied'))
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [locations, selection, reload, t, toast])

  const selectedLocation = useMemo(() => {
    if (!locations || !selection) return null
    return locations.find((l) => l.id === selection.locationId) || null
  }, [locations, selection])

  const selectedRoom = useMemo(() => {
    if (!selectedLocation || selection?.kind !== 'room') return null
    return (selectedLocation.rooms || []).find((r) => r.id === selection.roomId) || null
  }, [selectedLocation, selection])

  if (locations === null) return <div className="ga-loading">{t('Loading…')}</div>

  return (
    <div className="ga-world-grid">
      {/* Datalist fuer Style-Hint-Vorschlaege (Schritt 7, May 2026) */}
      <datalist id="style-hint-options">
        {STYLE_HINT_OPTIONS.map((v) => (
          <option key={v} value={v} />
        ))}
      </datalist>
      <aside className="ga-world-list-col">
        <ListHeader
          title={t('Places')}
          onNew={newLocation}
          onCopy={copyLocation}
          copyDisabled={selection?.kind !== 'location'}
          extra={
            <ImportButton
              endpoint="/world/locations/import"
              onImported={() => reload()}
            />
          }
        />
        <ul className="ga-list">
          {locations.length === 0 ? (
            <li className="ga-list-empty">{t('No places yet')}</li>
          ) : (() => {
            // Gruppierung: erst eindeutige Orte (kein Durchgang), dann Durchgänge.
            const unique = locations.filter((l) => !l.passable)
            const passages = locations.filter((l) => l.passable)
            const both = unique.length > 0 && passages.length > 0
            const headStyle = {
              padding: '6px 8px 2px', fontSize: '0.68em', fontWeight: 700,
              letterSpacing: '0.04em', textTransform: 'uppercase' as const, opacity: 0.55,
            }
            const out: ReactNode[] = []
            const push = (rows: Location[], key: string, label: string) => {
              if (!rows.length) return
              if (both) out.push(<li key={key} style={headStyle}>{label}</li>)
              rows.forEach((l) => out.push(
                <LocationTreeRow key={l.id} location={l} selection={selection} onSelect={setSelection} />))
            }
            push(unique, 'h-unique', t('Unique'))
            push(passages, 'h-passages', t('Passages'))
            return out
          })()}
        </ul>
      </aside>
      <section className="ga-world-form-col">
        {selection?.kind === 'location' && selectedLocation ? (
          <LocationEditor
            location={selectedLocation}
            items={items}
            onChanged={reload}
            onDeleted={() => {
              setSelection(null)
              reload()
            }}
          />
        ) : selection?.kind === 'room' && selectedLocation && selectedRoom ? (
          <RoomEditor
            location={selectedLocation}
            room={selectedRoom}
            items={items}
            onChanged={reload}
            onDeleted={() => {
              setSelection({ kind: 'location', locationId: selectedLocation.id })
              reload()
            }}
          />
        ) : (
          <div className="ga-placeholder">{t('Select a place or room.')}</div>
        )}
      </section>
      <aside className="ga-world-gallery-col">
        {selectedLocation ? (
          <LocationGallery
            locationId={selectedLocation.id}
            location={selectedLocation}
            room={selectedRoom || null}
            roomFilter={selectedRoom?.id || undefined}
            allLocations={locations}
            placements={placements}
          />
        ) : (
          <div className="ga-placeholder">{t('Select a place to view its gallery.')}</div>
        )}
      </aside>
    </div>
  )
}

interface LocationTreeRowProps {
  location: Location
  selection: Selection
  onSelect: (s: Selection) => void
}

// Entry-Room-id einer Location: explizites entry_room (wenn es einen Raum
// matched), sonst der erste Raum — analog get_entry_room_id (Backend).
function entryRoomId(loc: Location): string {
  const rooms = loc.rooms || []
  if (!rooms.length) return ''
  const explicit = (loc.entry_room || '').trim()
  if (explicit && rooms.some((r) => r.id === explicit)) return explicit
  return rooms[0]?.id || ''
}

// Danger-Level-Farbe (0 = keine Anzeige, 1..5 zunehmend rot).
const DANGER_COLORS = ['', '#6cc24a', '#d9c200', '#e0930b', '#e0560b', '#d62828']

function LocationTreeRow({ location, selection, onSelect }: LocationTreeRowProps) {
  const { t } = useI18n()
  const isLocSelected = selection?.kind === 'location' && selection.locationId === location.id
  const isExpanded = isLocSelected || selection?.locationId === location.id

  // Durchgang (passable): Unterscheidung erfolgt über die Gruppierung der Liste
  // (eindeutige Orte zuerst), nicht mehr über Farbe.
  const passable = !!location.passable
  // Indoor/Outdoor-Symbol.
  const io = location.indoor === 'indoor'
    ? { icon: '🏠', title: t('Indoor') }
    : location.indoor === 'outdoor'
      ? { icon: '🌳', title: t('Outdoor') }
      : { icon: '', title: '' }
  // Danger-Level-Spalte.
  const danger = Math.max(0, Math.min(5, location.danger_level || 0))
  const dangerLabel = DANGER_LEVELS.find((d) => d.value === danger)?.label || ''
  // Entry-Room ans Listen-Anfang sortieren.
  const eid = entryRoomId(location)
  const rooms = [...(location.rooms || [])].sort(
    (a, b) => (a.id === eid ? -1 : 0) - (b.id === eid ? -1 : 0))

  return (
    <li>
      <button
        type="button"
        className={`ga-list-row${isLocSelected ? ' is-active' : ''}`}
        onClick={() => onSelect({ kind: 'location', locationId: location.id })}
        title={passable ? t('Passage (transit location)') : t('Fixed location')}
      >
        <span className="ga-list-row-main" style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <span style={{ width: '1.2em', flex: '0 0 auto', textAlign: 'center' }}
            title={io.title || undefined} aria-label={io.title || undefined}>{io.icon}</span>
          <strong style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {location.name}
          </strong>
          {location.is_template ? <span className="ga-source ga-source-shared">tpl</span> : null}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8, flex: '0 0 auto', marginLeft: 8 }}>
          {danger > 0 ? (
            <span title={`${t('Danger')}: ${t(dangerLabel)}`}
              style={{ fontSize: '0.72em', fontWeight: 700, color: '#fff', background: DANGER_COLORS[danger],
                borderRadius: 4, padding: '0 5px', lineHeight: 1.6 }}>
              ⚠{danger}
            </span>
          ) : null}
          <span className="ga-form-hint">
            {(location.rooms || []).length} {(location.rooms || []).length === 1 ? 'room' : 'rooms'}
          </span>
        </span>
      </button>
      {isExpanded && rooms.length > 0 ? (
        <ul className="ga-list-nested">
          {rooms.map((r) => {
            const isRoomSelected =
              selection?.kind === 'room' && selection.locationId === location.id && selection.roomId === r.id
            const isEntry = !!r.id && r.id === eid
            return (
              <li key={r.id}>
                <button
                  type="button"
                  className={`ga-list-row ga-list-row-nested${isRoomSelected ? ' is-active' : ''}`}
                  onClick={() => onSelect({ kind: 'room', locationId: location.id, roomId: r.id || '' })}
                  title={isEntry ? t('Entry room') : undefined}
                >
                  <span className="ga-list-row-main">
                    {isEntry ? '🚪' : '↳'} {r.name || r.id}
                  </span>
                  {r.decency ? <span className="ga-source ga-source-world">{r.decency}</span> : null}
                </button>
              </li>
            )
          })}
        </ul>
      ) : null}
    </li>
  )
}

// ── Location editor ────────────────────────────────────────────────────────

interface LocationEditorProps {
  location: Location
  items: ItemRef[]
  onChanged: () => void
  onDeleted: () => void
}

function LocationEditor({ location, items, onChanged, onDeleted }: LocationEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [draft, setDraft] = useState<Location>(() => ({ ...location }))

  useEffect(() => {
    setDraft({ ...location })
  }, [location])

  const upd = useCallback(<K extends keyof Location>(k: K, v: Location[K]) => {
    setDraft((prev) => ({ ...prev, [k]: v }))
  }, [])

  const save = useCallback(async () => {
    try {
      await apiPut(`/world/locations/${encodeURIComponent(location.id)}`, {
        name: draft.name,
        description: draft.description,
        rooms: draft.rooms,
        entry_room: draft.entry_room || '',
        danger_level: draft.danger_level,
        indoor: draft.indoor || '',
        decency: draft.decency,
        style_hint: draft.style_hint,
        swim_allowed: draft.swim_allowed,
        activity_hint: draft.activity_hint,
        knowledge_item_id: draft.knowledge_item_id,
        passable: draft.passable,
        image_prompt_day: draft.image_prompt_day,
        image_prompt_night: draft.image_prompt_night,
        image_prompt_map_2d: draft.image_prompt_map_2d,
        event_settings: draft.event_settings,
      })
      toast(t('Saved'))
      onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [draft, location.id, onChanged, t, toast])

  const remove = useCallback(async () => {
    if (!window.confirm(t('Delete location "{name}"?').replace('{name}', location.name))) return
    try {
      await apiDelete(`/world/locations/${encodeURIComponent(location.name)}`)
      toast(t('Deleted'))
      onDeleted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [location.name, onDeleted, t, toast])

  const addRoom = useCallback(() => {
    const name = window.prompt(t('Room name:'))
    if (!name?.trim()) return
    const id = name.trim().toLowerCase().replace(/\s+/g, '_')
    setDraft((prev) => {
      const rooms = [...(prev.rooms || []), { id, name: name.trim(), description: '' }]
      return { ...prev, rooms }
    })
  }, [t])

  return (
    <>
      <DetailToolbar
        title={location.name}
        onSave={save}
        onDelete={remove}
        extra={
          <>
            <ExportButton
              endpoint={`/world/locations/${encodeURIComponent(location.id)}/export`}
              filename={`location_${location.id}.zip`}
            />
            <PublishButton
              packType="location"
              entityId={location.id}
              defaultName={location.name || location.id}
            />
          </>
        }
      />
      <div className="ga-form">
        <div className="ga-form-row">
          <Field label={t('Name')}>
            <input
              className="ga-input"
              value={draft.name || ''}
              onChange={(e) => upd('name', e.target.value)}
            />
          </Field>
          <Field
            label={t('Entry')}
            hint={t('Room used as entry/exit. Avatar must be there to leave; arrivals land here.')}
          >
            <select
              className="ga-input"
              value={draft.entry_room || ''}
              onChange={(e) => upd('entry_room', e.target.value)}
              disabled={!draft.rooms || draft.rooms.length === 0}
            >
              {(draft.rooms || []).length === 0 ? (
                <option value="">— {t('no rooms')} —</option>
              ) : null}
              {(draft.rooms || []).map((r) => (
                <option key={r.id || r.name} value={r.id || ''}>
                  {r.name || r.id || '?'}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="ga-form-row">
          <Field label={t('Passable')} inline>
            <input
              type="checkbox"
              checked={draft.passable !== false}
              onChange={(e) => upd('passable', e.target.checked)}
            />
          </Field>
          <Field label={t('Danger level')}
            hint={t('Drives hourly stamina/stat drain and danger-based rules; higher = more dangerous.')}>
            <select
              className="ga-input"
              value={draft.danger_level ?? 0}
              onChange={(e) => upd('danger_level', parseInt(e.target.value, 10) || 0)}
            >
              {DANGER_LEVELS.map((d) => (
                <option key={d.value} value={d.value}>{d.value} — {t(d.label)}</option>
              ))}
            </select>
          </Field>
        </div>

        <Field label={t('Description')}>
          <textarea
            className="ga-textarea"
            rows={2}
            value={draft.description || ''}
            onChange={(e) => upd('description', e.target.value)}
          />
        </Field>

        <div className="ga-form-row">
          <Field label={t('Indoor/Outdoor')} hint={t('Used as a coherence hint for event generation and storyteller narration.')}>
            <select
              className="ga-input"
              value={draft.indoor || ''}
              onChange={(e) => upd('indoor', e.target.value)}
            >
              <option value="">{t('— not set —')}</option>
              <option value="indoor">{t('Indoor')}</option>
              <option value="outdoor">{t('Outdoor')}</option>
            </select>
          </Field>
          <Field label={t('Decency')} hint={t('Hard rule: public requires top+bottom covered. private allows nudity when alone/intimate. nude_ok always allows.')}>
            <select
              className="ga-input"
              value={draft.decency || ''}
              onChange={(e) => upd('decency', (e.target.value || '') as Location['decency'])}
            >
              <option value="">{t('— inherit / default public —')}</option>
              <option value="public">public</option>
              <option value="private">private</option>
              <option value="nude_ok">nude_ok</option>
            </select>
          </Field>
          <Field label={t('Knowledge item')} hint={t('Item that grants knowledge of this location.')}>
            <select
              className="ga-input"
              value={draft.knowledge_item_id || ''}
              onChange={(e) => upd('knowledge_item_id', e.target.value)}
            >
              <option value="">— {t('none')} —</option>
              {items.map((it) => (
                <option key={it.id} value={it.id}>
                  {it.name || it.id}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="ga-form-row">
          <Field label={t('Style hint')} hint={t('Soft suggestion for the LLM (e.g. business, elegant, casual). No code effect.')}>
            <input
              className="ga-input"
              list="style-hint-options"
              value={draft.style_hint || ''}
              onChange={(e) => upd('style_hint', e.target.value)}
            />
          </Field>
          <Field label={t('Swim allowed')} hint={t('If true, top/bottom can be replaced by swimwear when the character is wet.')}>
            <label className="ga-form-check">
              <input
                type="checkbox"
                checked={!!draft.swim_allowed}
                onChange={(e) => upd('swim_allowed', e.target.checked)}
              />
              <span>{t('Allow swimwear when wet')}</span>
            </label>
          </Field>
          <Field label={t('Activity hint')} hint={t('Free-text: what people usually do here. Goes to the LLM as inspiration.')}>
            <textarea
              className="ga-textarea"
              rows={2}
              value={draft.activity_hint || ''}
              onChange={(e) => upd('activity_hint', e.target.value)}
            />
          </Field>
        </div>

        <div className="ga-loc-twocol">
          <div>
            <div className="ga-form-section-label">{t('Image prompts')}</div>
            <div className="ga-form">
              <Field label={t('Day prompt')}>
                <textarea
                  className="ga-textarea"
                  rows={2}
                  value={draft.image_prompt_day || ''}
                  onChange={(e) => upd('image_prompt_day', e.target.value)}
                />
              </Field>
              <Field label={t('Night prompt')}>
                <textarea
                  className="ga-textarea"
                  rows={2}
                  value={draft.image_prompt_night || ''}
                  onChange={(e) => upd('image_prompt_night', e.target.value)}
                />
              </Field>
              <Field label={t('2D map icon prompt')}>
                <textarea
                  className="ga-textarea"
                  rows={2}
                  value={draft.image_prompt_map_2d || ''}
                  onChange={(e) => upd('image_prompt_map_2d', e.target.value)}
                />
              </Field>
            </div>
          </div>
          <div>
            <div className="ga-form-section-label">{t('Random events')}</div>
            <RandomEventsEditor
              value={draft.event_settings}
              onChange={(es) => upd('event_settings', es)}
            />
          </div>
        </div>

        {/* Rooms list intentionally omitted — the location tree on the
            left already shows the rooms below the location, no need to
            duplicate them here. The "+ Room" action stays so new rooms
            can be added from the location editor. */}
        <button className="ga-btn ga-btn-sm" onClick={addRoom}>
          + {t('Room')}
        </button>
      </div>
    </>
  )
}

// ── Per-location random-events overrides ──────────────────────────────────
// Mirrors the global "Random events" config block but lets a location set
// its own probability / cooldown / categories. Hint text matches the global
// admin's "Pro Location ueberschreibbar" promise — without this section the
// override claim was dead since the React migration.
interface RandomEventsEditorProps {
  value: EventSettings | undefined
  onChange: (next: EventSettings) => void
}

function RandomEventsEditor({ value, onChange }: RandomEventsEditorProps) {
  const { t } = useI18n()
  const settings: EventSettings = value || {}
  const probabilityPct = Math.round(((settings.event_probability ?? 0.1) as number) * 100)
  const allowed = settings.allowed_categories || [...EVENT_CATEGORIES]
  const blacklistText = (settings.event_blacklist || []).join(', ')

  const update = (patch: Partial<EventSettings>) => {
    onChange({ ...settings, ...patch })
  }

  return (
    <div className="ga-form">
      <div className="ga-form-row">
        <Field
          label={t('Probability %')}
          hint={t('Per hour. Overrides the global default.')}
        >
          <input
            type="number"
            className="ga-input"
            min={0}
            max={50}
            step={1}
            value={probabilityPct}
            onChange={(e) =>
              update({ event_probability: (parseInt(e.target.value, 10) || 0) / 100 })
            }
          />
        </Field>
        <Field label={t('Max')}>
          <input
            type="number"
            className="ga-input"
            min={1}
            max={10}
            value={settings.max_concurrent_events ?? 1}
            onChange={(e) =>
              update({ max_concurrent_events: parseInt(e.target.value, 10) || 1 })
            }
          />
        </Field>
        <Field label={t('Cooldown h')}>
          <input
            type="number"
            className="ga-input"
            min={0}
            max={48}
            value={settings.event_cooldown_hours ?? 2}
            onChange={(e) =>
              update({ event_cooldown_hours: parseInt(e.target.value, 10) || 0 })
            }
          />
        </Field>
      </div>
      <Field label={t('Allowed categories')}>
        <div className="ga-form-row" style={{ gap: 10, flexWrap: 'wrap' }}>
          {EVENT_CATEGORIES.map((cat) => {
            const checked = allowed.includes(cat)
            return (
              <label key={cat} className="ga-form-check">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...allowed.filter((c) => c !== cat), cat]
                      : allowed.filter((c) => c !== cat)
                    update({ allowed_categories: next })
                  }}
                />
                {cat}
              </label>
            )
          })}
        </div>
      </Field>
      <Field label={t('Blacklist')} hint={t('Comma-separated event names that must never fire here.')}>
        <input
          className="ga-input"
          value={blacklistText}
          placeholder="z.B. Feuer, Erdbeben"
          onChange={(e) =>
            update({
              event_blacklist: e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
      </Field>
    </div>
  )
}

// ── Room editor ────────────────────────────────────────────────────────────

interface RoomEditorProps {
  location: Location
  room: Room
  items: ItemRef[]
  onChanged: () => void
  onDeleted: () => void
}

function RoomEditor({ location, room, items, onChanged, onDeleted }: RoomEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [draft, setDraft] = useState<Room>(() => ({ ...room }))

  useEffect(() => {
    setDraft({ ...room })
  }, [room])

  const upd = useCallback(<K extends keyof Room>(k: K, v: Room[K]) => {
    setDraft((prev) => ({ ...prev, [k]: v }))
  }, [])

  const save = useCallback(async () => {
    try {
      const rooms = (location.rooms || []).map((r) => (r.id === room.id ? { ...r, ...draft } : r))
      await apiPut(`/world/locations/${encodeURIComponent(location.id)}`, { rooms })
      toast(t('Saved'))
      onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [draft, location, room.id, onChanged, t, toast])

  const remove = useCallback(async () => {
    if (!window.confirm(t('Remove room "{name}"?').replace('{name}', room.name || room.id || ''))) return
    try {
      const rooms = (location.rooms || []).filter((r) => r.id !== room.id)
      await apiPut(`/world/locations/${encodeURIComponent(location.id)}`, { rooms })
      toast(t('Removed'))
      onDeleted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [location, room, onDeleted, t, toast])

  return (
    <>
      <DetailToolbar
        title={`${location.name} / ${room.name || room.id || t('room')}`}
        onSave={save}
        onDelete={remove}
        deleteLabel={t('Remove room')}
      />
      <div className="ga-form">
        <div className="ga-form-row">
          <Field label={t('Room ID (read-only)')} hint={t('Permanent identifier — set when the room was created.')}>
            <input
              className="ga-input"
              value={draft.id || ''}
              readOnly
              disabled
              style={{ fontFamily: 'monospace', opacity: 0.7 }}
            />
          </Field>
          <Field label={t('Name')}>
            <input
              className="ga-input"
              value={draft.name || ''}
              onChange={(e) => upd('name', e.target.value)}
            />
          </Field>
        </div>
        <Field label={t('Description')}>
          <textarea
            className="ga-textarea"
            rows={2}
            value={draft.description || ''}
            onChange={(e) => upd('description', e.target.value)}
          />
        </Field>
        <div className="ga-form-row">
          <Field label={t('Decency')} hint={t('Overrides the location decency for this room. Empty = inherit.')}>
            <select
              className="ga-input"
              value={draft.decency || ''}
              onChange={(e) => upd('decency', (e.target.value || '') as Room['decency'])}
            >
              <option value="">{t('— inherit from location —')}</option>
              <option value="public">public</option>
              <option value="private">private</option>
              <option value="nude_ok">nude_ok</option>
            </select>
          </Field>
          <Field label={t('Style hint')} hint={t('Soft suggestion for the LLM (no code effect).')}>
            <input
              className="ga-input"
              list="style-hint-options"
              value={draft.style_hint || ''}
              onChange={(e) => upd('style_hint', e.target.value)}
            />
          </Field>
        </div>
        <div className="ga-form-row">
          <Field label={t('Swim allowed')}>
            <label className="ga-form-check">
              <input
                type="checkbox"
                checked={!!draft.swim_allowed}
                onChange={(e) => upd('swim_allowed', e.target.checked)}
              />
              <span>{t('Allow swimwear when wet')}</span>
            </label>
          </Field>
          <Field label={t('Activity hint')} hint={t('Free-text: what people usually do in this room.')}>
            <textarea
              className="ga-textarea"
              rows={2}
              value={draft.activity_hint || ''}
              onChange={(e) => upd('activity_hint', e.target.value)}
            />
          </Field>
        </div>

        <div>
          <div className="ga-form-section-label">{t('Image prompts')}</div>
          <div className="ga-form">
            <Field
              label={t('Day prompt')}
              hint={t('Per-room override. Falls back to the location day prompt when empty.')}
            >
              <textarea
                className="ga-textarea"
                rows={2}
                value={draft.image_prompt_day || ''}
                onChange={(e) => upd('image_prompt_day', e.target.value)}
              />
            </Field>
            <Field
              label={t('Night prompt')}
              hint={t('Per-room override. Falls back to the location night prompt when empty.')}
            >
              <textarea
                className="ga-textarea"
                rows={2}
                value={draft.image_prompt_night || ''}
                onChange={(e) => upd('image_prompt_night', e.target.value)}
              />
            </Field>
          </div>
        </div>

        <RoomItems locationId={location.id} roomId={room.id || ''} items={items} />
      </div>
    </>
  )
}

// ── Gallery — list, type-change, night-variant, delete, enlarge. ───────────

function LocationGallery({
  locationId,
  location,
  room,
  roomFilter,
  allLocations,
  placements,
}: {
  locationId: string
  location: Location
  room: Room | null
  /** When set, only images assigned to this room are shown. */
  roomFilter?: string
  /** All places (for the "move image to another location" picker). */
  allLocations: Location[]
  /** Ungefilterte Liste inkl. Klon-Platzierungen (fuer den Map-Usage-Zaehler). */
  placements: Location[]
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [data, setData] = useState<GalleryResponse | null>(null)
  const [zoom, setZoom] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [dialogType, setDialogType] = useState<'day' | 'night' | 'map_2d' | null>(null)
  // „Regenerate"-Ziel: ein bestehendes Karten-Bild als Referenz neu erzeugen.
  const [regenTarget, setRegenTarget] = useState<{ filename: string; type: string } | null>(null)
  // Unabhängige Config-Suffixe für Karten-Icons (editierbar im Dialog statt
  // serverseitig angehängt). Einmalig laden.
  const [mapSuffix, setMapSuffix] = useState({ map_2d: '' })
  // „Bild verschieben": offenes Bild + gewählte Ziel-Location.
  const [moveImage, setMoveImage] = useState<string | null>(null)
  const [moveTarget, setMoveTarget] = useState('')
  useEffect(() => {
    apiGet<{ map_2d_image_prompt_suffix?: string }>('/world/imagegen-options')
      .then((d) => setMapSuffix({ map_2d: d.map_2d_image_prompt_suffix || '' }))
      .catch(() => { /* ignore */ })
  }, [])

  const reload = useCallback(async () => {
    try {
      const d = await apiGet<GalleryResponse>(
        `/world/locations/${encodeURIComponent(locationId)}/gallery`,
      )
      setData({
        images: d.images || [],
        image_rooms: d.image_rooms || {},
        image_types: d.image_types || {},
        image_metas: d.image_metas || {},
      })
    } catch {
      setData({ images: [] })
    }
  }, [locationId])

  useEffect(() => {
    reload()
  }, [reload])

  // Bild in eine andere Location verschieben (Datei + Prompt/Typ/Meta).
  const submitMove = useCallback(async () => {
    if (!moveImage || !moveTarget) return
    try {
      await apiPost(
        `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(moveImage)}/move`,
        { target: moveTarget },
      )
      toast(t('Image moved'))
      setMoveImage(null)
      setMoveTarget('')
      await reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [moveImage, moveTarget, locationId, reload, t, toast])

  const allImages = data?.images || []
  const rooms = data?.image_rooms || {}
  const types = data?.image_types || {}
  const metas = data?.image_metas || {}

  // Wie oft wird jedes Map-Bild aktuell auf der Karte verwendet: platzierte Zellen,
  // deren Galerie-Owner diese Location ist (Klone teilen die Template-Galerie), und
  // die genau diese Datei als 2D-Tile gewaehlt haben. Datei -> Anzahl.
  const mapUsage = useMemo(() => {
    const m: Record<string, number> = {}
    for (const l of placements) {
      if (l.grid_x == null || l.grid_y == null || l.grid_x < 0 || l.grid_y < 0) continue
      if (((l.template_location_id || '').trim() || l.id) !== locationId) continue
      const f = (l.map_image_2d || '').trim()
      if (f) m[f] = (m[f] || 0) + 1
    }
    return m
  }, [placements, locationId])

  // Filter to the selected room (if provided): keep images explicitly
  // assigned to it; images without a room assignment fall back to the
  // location level and stay visible at the location detail.
  const images = roomFilter
    ? allImages.filter((f) => (rooms[f] || '') === roomFilter)
    : allImages.filter((f) => !rooms[f] || rooms[f] === '')

  const setType = useCallback(
    async (image: string, type: string) => {
      setBusy(image)
      try {
        await apiPost(
          `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(image)}/type`,
          { type },
        )
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(null)
      }
    },
    [locationId, reload, t, toast],
  )

  const generateNight = useCallback(
    async (image: string) => {
      setBusy(image)
      try {
        await apiPost(
          `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(image)}/time-variant`,
          { target_type: 'night' },
        )
        toast(t('Night variant queued'))
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(null)
      }
    },
    [locationId, reload, t, toast],
  )

  // Build the prompt that pre-fills the dialog. Mirrors the server's
  // resolution order in routes/world.py:generate_gallery_image — room
  // first, then location, falling back to description. The user can
  // edit it before submitting; edits are not persisted.
  const buildDefaultPrompt = useCallback(
    (promptType: string): string => {
      const fromRoom = (key: 'image_prompt_day' | 'image_prompt_night') =>
        (room && (room as Record<string, unknown>)[key]) as string | undefined
      const isMap = promptType === 'map_2d'
      let desc = ''
      if (room && !isMap) {
        if (promptType === 'day') desc = (fromRoom('image_prompt_day') || '').trim()
        else if (promptType === 'night') desc = (fromRoom('image_prompt_night') || '').trim()
        if (!desc) desc = (fromRoom('image_prompt_day') || room.description || '').trim()
      }
      if (!desc && promptType === 'day') desc = (location.image_prompt_day || '').trim()
      if (!desc && promptType === 'night') desc = (location.image_prompt_night || '').trim()
      if (!desc && promptType === 'map_2d') desc = (location.image_prompt_map_2d || '').trim()
      if (!desc) desc = location.description || location.name || ''
      // 2D map icon: subject only. The style suffix is admin-managed (Server Admin →
      // Image Generation) and appended server-side, so it isn't duplicated here.
      if (isMap) {
        return desc
      }
      return `${desc}, wide angle establishing shot, no people, atmospheric, cinematic lighting, background wallpaper, 16:9 aspect ratio`
    },
    [location, room],
  )

  // Submit handler the dialog calls on Generate. Truly fire-and-forget —
  // the function returns immediately so ImageGenDialog can close right
  // away. The POST + reload run on a detached promise. Errors land in
  // the toast bus, not on the dialog (which is already gone).
  const submitGenerate = useCallback(
    async (payload: ImageGenSubmit) => {
      if (!dialogType) return
      const body: Record<string, unknown> = {
        prompt_type: dialogType,
        prompt: payload.prompt,
      }
      if (roomFilter && dialogType !== 'map_2d') body.room_id = roomFilter
      if (payload.workflow) body.workflow = payload.workflow
      if (payload.backend) body.backend = payload.backend
      if (payload.model_override) body.model_override = payload.model_override
      if (payload.loras) body.loras = payload.loras
      // Dialog hat den Karten-Icon-Suffix schon im Prompt → Server nicht doppeln.
      if (payload.prompt_settings_applied) body.settings_applied = true

      // Detached: do NOT await. handleSubmit will see a resolved Promise
      // immediately and trigger onClose() in the next microtask.
      void apiPost(
        `/world/locations/${encodeURIComponent(locationId)}/gallery`,
        body,
      )
        // Kein Auto-Refresh: die periodischen Reloads stören, wenn man parallel
        // etwas anderes editiert. Neues Bild erscheint beim nächsten Galerie-Reload.
        .then(() => toast(t('Image queued')))
        .catch((e) => {
          toast(t('Error') + ': ' + (e as Error).message, 'error')
        })
    },
    [dialogType, locationId, roomFilter, t, toast],
  )

  // Regenerate eines bestehenden Karten-Bilds — mit ihm selbst als Referenz.
  // Landet immer als NEUES Gallery-Bild (per Zelle wählbar).
  const submitRegenRef = useCallback(
    async (payload: ImageGenSubmit, target: { filename: string; type: string }) => {
      const body: Record<string, unknown> = {
        prompt_type: target.type,
        prompt: payload.prompt,
        reference_image: target.filename,
      }
      if (payload.workflow) body.workflow = payload.workflow
      if (payload.backend) body.backend = payload.backend
      if (payload.model_override) body.model_override = payload.model_override
      if (payload.loras) body.loras = payload.loras
      if (payload.prompt_settings_applied) body.settings_applied = true
      // Regenerate mit dem bestehenden Bild als Selbst-Referenz.
      if (payload.use_source_as_reference) body.use_source_as_reference = true
      // Haken aus: das bestehende Bild in-place ersetzen statt ein neues anzulegen.
      if (payload.create_new === false) body.replace_source = true
      // Optionaler "Was willst Du ändern"-Wunsch → Server lässt den Prompt per LLM
      // umschreiben (gleiche enhance_prompt-Funktion wie Character/Instagram).
      if (payload.improvement_request) body.improvement_request = payload.improvement_request
      void apiPost(`/world/locations/${encodeURIComponent(locationId)}/gallery`, body)
        .then(() => toast(t('Image queued')))
        .catch((e) => { toast(t('Error') + ': ' + (e as Error).message, 'error') })
    },
    [locationId, t, toast],
  )

  const remove = useCallback(
    async (image: string) => {
      if (!window.confirm(t('Delete image "{name}"?').replace('{name}', image))) return
      setBusy(image)
      try {
        await apiDelete(
          `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(image)}`,
        )
        await reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(null)
      }
    },
    [locationId, reload, t, toast],
  )

  // Hintergrundbild für diesen Ort (optional Raum, wenn roomFilter gesetzt)
  // hochladen statt generieren.
  const uploadRef = useRef<HTMLInputElement>(null)
  const uploadBg = useCallback(async (file: File) => {
    if (!file) return
    setBusy('upload')
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (roomFilter) fd.append('room_id', roomFilter)
      await fetch(`/world/locations/${encodeURIComponent(locationId)}/background/upload`, {
        method: 'POST', body: fd, credentials: 'same-origin',
      })
      await reload()
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(null)
    }
  }, [locationId, roomFilter, reload, t, toast])

  const generatePanel = (
    <div className="ga-gallery-generate">
      <button
        className="ga-btn ga-btn-sm"
        disabled={!!busy}
        onClick={() => setDialogType('day')}
        title={t('Open the image generation dialog with the day prompt.')}
      >
        ☀️ {t('Generate day')}
      </button>
      <button
        className="ga-btn ga-btn-sm"
        disabled={!!busy}
        onClick={() => setDialogType('night')}
        title={t('Open the image generation dialog with the night prompt.')}
      >
        🌙 {t('Generate night')}
      </button>
      {!roomFilter ? (
        <button
          className="ga-btn ga-btn-sm"
          disabled={!!busy}
          onClick={() => setDialogType('map_2d')}
          title={t('Open the image generation dialog for the flat 2D map icon.')}
        >
          🟦 {t('Generate 2D icon')}
        </button>
      ) : null}
      <button
        className="ga-btn ga-btn-sm"
        disabled={!!busy}
        onClick={() => uploadRef.current?.click()}
        title={roomFilter ? t('Upload a background image for this room.') : t('Upload a background image for this place.')}
      >
        ⬆ {t('Upload')}
      </button>
      <input
        ref={uploadRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadBg(f); e.target.value = '' }}
      />
      <button
        className="ga-btn ga-btn-sm"
        disabled={!!busy}
        onClick={() => { void reload() }}
        title={t('Reload the gallery (show newly generated images)')}
      >
        🔄 {t('Refresh')}
      </button>
    </div>
  )

  const dialog = dialogType ? (
    <ImageGenDialog
      open
      title={
        dialogType === 'day'
          ? t('Generate day image — {name}').replace('{name}', room?.name || location.name)
          : dialogType === 'night'
            ? t('Generate night image — {name}').replace('{name}', room?.name || location.name)
            : t('Generate 2D map icon — {name}').replace('{name}', location.name)
      }
      defaultPrompt={buildDefaultPrompt(dialogType)}
      hideNegative
      settingsSuffix={
        dialogType === 'map_2d' && mapSuffix.map_2d
          ? { label: t('2D map icon'), text: mapSuffix.map_2d }
          : undefined
      }
      onSubmit={submitGenerate}
      onClose={() => setDialogType(null)}
    />
  ) : null

  const regenDialog = regenTarget ? (
    <ImageGenDialog
      open
      title={t('Adjust image — {name}').replace('{name}', room?.name || location.name)}
      mode="regenerate"
      defaultPrompt={buildDefaultPrompt(regenTarget.type)}
      hideNegative
      sourceImageUrl={`/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(regenTarget.filename)}`}
      defaultUseSource
      requireSourceReference
      defaultCreateNew
      settingsSuffix={
        regenTarget.type === 'map_2d' && mapSuffix.map_2d
          ? { label: t('2D map icon'), text: mapSuffix.map_2d }
          : undefined
      }
      onSubmit={(payload) => submitRegenRef(payload, regenTarget)}
      onClose={() => setRegenTarget(null)}
    />
  ) : null

  if (!data) return <div className="ga-loading">{t('Loading…')}</div>
  if (!images.length) {
    return (
      <>
        {generatePanel}
        {dialog}
        {regenDialog}
        <div className="ga-form-hint" style={{ padding: 8 }}>
          {roomFilter
            ? t('No gallery images for this room yet.')
            : t('No gallery images yet.')}
        </div>
      </>
    )
  }

  return (
    <>
      {generatePanel}
      {dialog}
      {regenDialog}
      <div className="ga-form-section-label">
        {t('Gallery')} ({images.length})
      </div>
      <div className="ga-gallery-list">
        {images.map((filename) => {
          const meta = metas[filename] || {}
          const type = types[filename] || ''
          const url = `/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(filename)}`
          const isBusy = busy === filename
          return (
            <div key={filename} className="ga-gallery-card">
              <button
                type="button"
                className="ga-gallery-thumb"
                onClick={() => setZoom(url)}
                title={t('Click to enlarge')}
              >
                <img src={url} alt={filename} />
                {type === 'map_2d' ? (
                  <span
                    className="ga-gallery-usage"
                    title={t('How many map cells currently use this image')}
                  >
                    {mapUsage[filename] || 0}
                  </span>
                ) : null}
              </button>
              <div className="ga-gallery-card-body">
                <div className="ga-gallery-meta">
                  {meta.model ? (
                    <div>
                      <strong>{t('Model')}</strong> {meta.model}
                    </div>
                  ) : null}
                  {meta.loras && meta.loras.length > 0 ? (
                    <div>
                      <strong>{t('LoRAs')}</strong> {meta.loras.join(', ')}
                    </div>
                  ) : null}
                  {meta.backend ? (
                    <div>
                      <strong>{t('Provider')}</strong> {meta.backend}
                    </div>
                  ) : null}
                </div>
                <div className="ga-gallery-actions">
                  <select
                    className="ga-input ga-gallery-type-select"
                    value={type}
                    disabled={isBusy}
                    onChange={(e) => setType(filename, e.target.value)}
                    title={t('Image type')}
                  >
                    <option value="">— {t('type')} —</option>
                    {IMAGE_TYPES.filter((x) => x !== '').map((tp) => (
                      <option key={tp} value={tp}>
                        {tp}
                      </option>
                    ))}
                  </select>
                  <button
                    className="ga-btn ga-btn-sm"
                    disabled={isBusy}
                    onClick={() => generateNight(filename)}
                    title={t('Generate a night variant from this image')}
                  >
                    🌙
                  </button>
                  <button
                    className="ga-btn ga-btn-sm"
                    disabled={isBusy}
                    onClick={() => setRegenTarget({ filename, type })}
                    title={t('Adjust this image via a reference workflow + prompt (saved as a new image)')}
                  >
                    ♻
                  </button>
                  <button
                    className="ga-btn ga-btn-sm"
                    disabled={isBusy}
                    onClick={() => { setMoveImage(filename); setMoveTarget('') }}
                    title={t('Move this image to another location')}
                  >
                    ⇄
                  </button>
                  <button
                    className="ga-btn ga-btn-sm ga-btn-danger"
                    disabled={isBusy}
                    onClick={() => remove(filename)}
                  >
                    ×
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {zoom ? (
        <div className="ga-gallery-lightbox" onClick={() => setZoom(null)} role="dialog">
          <img src={zoom} alt="" />
          <button
            type="button"
            className="ga-gallery-lightbox-close"
            onClick={() => setZoom(null)}
            aria-label={t('Close')}
          >
            ×
          </button>
        </div>
      ) : null}

      {moveImage ? (
        <div className="ga-modal-backdrop" onMouseDown={() => setMoveImage(null)}>
          <div className="ga-modal" style={{ maxWidth: 460 }} onMouseDown={(e) => e.stopPropagation()}>
            <div className="ga-modal-header">
              <span>{t('Move image to…')}</span>
              <button className="ga-modal-close" onClick={() => setMoveImage(null)}>×</button>
            </div>
            <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <img
                src={`/world/locations/${encodeURIComponent(locationId)}/gallery/${encodeURIComponent(moveImage)}`}
                alt=""
                style={{ display: 'block', width: '100%', maxHeight: 220, objectFit: 'contain', borderRadius: 6, background: 'var(--bg, #0d1117)' }}
              />
              <label style={{ fontSize: '0.85em' }}>
                {t('Target location')}
                <select
                  className="ga-input"
                  value={moveTarget}
                  onChange={(e) => setMoveTarget(e.target.value)}
                  style={{ width: '100%', marginTop: 4 }}
                >
                  <option value="">— {t('select')} —</option>
                  {allLocations.filter((l) => l.id !== locationId).map((l) => (
                    <option key={l.id} value={l.id}>{l.name}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="ga-btn" onClick={() => setMoveImage(null)}>{t('Cancel')}</button>
              <button className="ga-btn ga-btn-primary" disabled={!moveTarget} onClick={submitMove}>
                {t('Move')}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}

// ── Room items panel ───────────────────────────────────────────────────────

interface RoomItem {
  item_id: string
  item_name?: string
  item_description?: string
  quantity?: number
  hidden?: boolean
}

function RoomItems({
  locationId,
  roomId,
  items,
}: {
  locationId: string
  roomId: string
  items: ItemRef[]
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [roomItems, setRoomItems] = useState<RoomItem[] | null>(null)
  const [addId, setAddId] = useState('')
  const [addQty, setAddQty] = useState(1)
  const [addHidden, setAddHidden] = useState(false)

  const reload = useCallback(async () => {
    if (!locationId || !roomId) return
    try {
      const d = await apiGet<{ items?: RoomItem[] }>(
        `/inventory/rooms/${encodeURIComponent(locationId)}/${encodeURIComponent(roomId)}`,
      )
      setRoomItems(d.items || [])
    } catch {
      setRoomItems([])
    }
  }, [locationId, roomId])

  useEffect(() => {
    reload()
  }, [reload])

  const removeItem = useCallback(
    async (itemId: string) => {
      if (!window.confirm(t('Remove item from room?'))) return
      try {
        await apiDelete(
          `/inventory/rooms/${encodeURIComponent(locationId)}/${encodeURIComponent(roomId)}/${encodeURIComponent(itemId)}`,
        )
        toast(t('Removed'))
        reload()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [locationId, roomId, reload, t, toast],
  )

  const addItem = useCallback(async () => {
    if (!addId) return
    try {
      await apiPost(
        `/inventory/rooms/${encodeURIComponent(locationId)}/${encodeURIComponent(roomId)}`,
        { item_id: addId, quantity: addQty, hidden: addHidden },
      )
      toast(t('Added'))
      setAddId('')
      setAddQty(1)
      setAddHidden(false)
      reload()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [addId, addQty, addHidden, locationId, roomId, reload, t, toast])

  return (
    <div className="ga-section">
      <div className="ga-form-section-label">{t('Items in this room')}</div>
      {roomItems === null ? (
        <div className="ga-form-hint">{t('Loading…')}</div>
      ) : roomItems.length === 0 ? (
        <div className="ga-form-hint">{t('Empty')}</div>
      ) : (
        <ul className="ga-room-mini-list">
          {roomItems.map((it) => (
            <li key={it.item_id}>
              <strong>{it.item_name || it.item_id}</strong>
              {it.quantity && it.quantity > 1 ? ` ×${it.quantity}` : ''}
              {it.hidden ? <span className="ga-form-hint"> · {t('hidden')}</span> : null}
              <button className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => removeItem(it.item_id)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="ga-form-row" style={{ marginTop: 6 }}>
        <Field label={t('Add item')}>
          <select className="ga-input" value={addId} onChange={(e) => setAddId(e.target.value)}>
            <option value="">— {t('select')} —</option>
            {items.map((it) => (
              <option key={it.id} value={it.id}>
                {it.name || it.id}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('Quantity')}>
          <input
            type="number"
            className="ga-input"
            min={1}
            max={99}
            value={addQty}
            onChange={(e) => setAddQty(parseInt(e.target.value, 10) || 1)}
          />
        </Field>
      </div>
      <div className="ga-form-row">
        <Field label={t('Hidden')} inline compact hint={t('Items hidden in the room are not visible to characters until discovered.')}>
          <input type="checkbox" checked={addHidden} onChange={(e) => setAddHidden(e.target.checked)} />
        </Field>
        <button
          className="ga-btn ga-btn-sm ga-btn-primary"
          onClick={addItem}
          disabled={!addId}
          style={{ marginLeft: 'auto', alignSelf: 'flex-end' }}
        >
          + {t('Add')}
        </button>
      </div>
    </div>
  )
}
