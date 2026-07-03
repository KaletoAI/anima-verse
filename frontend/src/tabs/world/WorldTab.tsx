import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ListHeader } from '../../components/ListHeader'
import { ImportButton } from '../../components/ImportExport'
import { loadItems, type ItemRef } from '../../lib/refs'
import { STYLE_HINT_OPTIONS } from '../../lib/styleHints'
import { DANGER_LEVELS, type Location, type Selection } from './worldTypes'
import { LocationEditor } from './LocationEditor'
import { RoomEditor } from './RoomEditor'
import { LocationGallery } from './LocationGallery'

export function WorldTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [locations, setLocations] = useState<Location[] | null>(null)
  // Unfiltered list incl. clone placements — for the "used on the map"
  // count in the gallery (clones carry map_image_2d + grid).
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
      {/* Datalist for style-hint suggestions (step 7, May 2026) */}
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
            // Grouping: first unique locations (no passage), then passages.
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

// Entry-room id of a location: the explicit entry_room (when it matches a
// room), otherwise the first room — analogous to get_entry_room_id (backend).
function entryRoomId(loc: Location): string {
  const rooms = loc.rooms || []
  if (!rooms.length) return ''
  const explicit = (loc.entry_room || '').trim()
  if (explicit && rooms.some((r) => r.id === explicit)) return explicit
  return rooms[0]?.id || ''
}

// Danger-level color (0 = no display, 1..5 increasingly red).
const DANGER_COLORS = ['', '#6cc24a', '#d9c200', '#e0930b', '#e0560b', '#d62828']

function LocationTreeRow({ location, selection, onSelect }: LocationTreeRowProps) {
  const { t } = useI18n()
  const isLocSelected = selection?.kind === 'location' && selection.locationId === location.id
  const isExpanded = isLocSelected || selection?.locationId === location.id

  // Passage (passable): the distinction is made via the list grouping
  // (unique locations first), no longer via color.
  const passable = !!location.passable
  // Indoor/outdoor symbol.
  const io = location.indoor === 'indoor'
    ? { icon: '🏠', title: t('Indoor') }
    : location.indoor === 'outdoor'
      ? { icon: '🌳', title: t('Outdoor') }
      : { icon: '', title: '' }
  // Danger-level column.
  const danger = Math.max(0, Math.min(5, location.danger_level || 0))
  const dangerLabel = DANGER_LEVELS.find((d) => d.value === danger)?.label || ''
  // Sort the entry room to the top of the list.
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
