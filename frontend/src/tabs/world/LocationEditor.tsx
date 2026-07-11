import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ExportButton, PublishButton } from '../../components/ImportExport'
import { type ItemRef } from '../../lib/refs'
import { DANGER_LEVELS, MAP3D_STYLES, TERRAIN_TYPES, type Location, type Map3D } from './worldTypes'
import { RandomEventsEditor } from './RandomEventsEditor'

// ── Location editor ────────────────────────────────────────────────────────

interface LocationEditorProps {
  location: Location
  items: ItemRef[]
  onChanged: () => void
  onDeleted: () => void
}

export function LocationEditor({ location, items, onChanged, onDeleted }: LocationEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [draft, setDraft] = useState<Location>(() => ({ ...location }))

  useEffect(() => {
    setDraft({ ...location })
  }, [location])

  const upd = useCallback(<K extends keyof Location>(k: K, v: Location[K]) => {
    setDraft((prev) => ({ ...prev, [k]: v }))
  }, [])

  // undefined removes the key; the backend drops an all-empty map3d object
  const updMap3d = useCallback(<K extends keyof Map3D>(k: K, v: Map3D[K] | undefined) => {
    setDraft((prev) => {
      const m3 = { ...(prev.map3d || {}) }
      if (v === undefined) delete m3[k]
      else m3[k] = v
      return { ...prev, map3d: m3 }
    })
  }, [])

  const footprint = draft.map3d?.footprint || []
  const setFootprint = useCallback((idx: 0 | 1, raw: string) => {
    const n = parseInt(raw, 10)
    setDraft((prev) => {
      const cur = prev.map3d?.footprint || []
      const next = [cur[0] || 0, cur[1] || 0]
      next[idx] = Number.isFinite(n) && n > 0 ? n : 0
      const m3 = { ...(prev.map3d || {}) }
      if (!next[0] && !next[1]) delete m3.footprint
      else m3.footprint = [next[0] || 1, next[1] || 1]
      return { ...prev, map3d: m3 }
    })
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
        terrain: draft.terrain,
        map3d: draft.map3d,
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
            hint={t('Drives stamina/stat drain per GAME hour (game clock) and danger-based rules; higher = more dangerous.')}>
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

        <div className="ga-form-section-label">{t('Map metadata (3D clients)')}</div>
        <div className="ga-form-row">
          <Field label={t('Terrain')} hint={t('Ground type of this map cell. Free text; without it, clients guess from the name.')}>
            <input
              className="ga-input"
              list="terrain-type-options"
              value={draft.terrain || ''}
              placeholder={t('auto (from name)')}
              onChange={(e) => upd('terrain', e.target.value)}
            />
            <datalist id="terrain-type-options">
              {TERRAIN_TYPES.map((v) => (
                <option key={v} value={v} />
              ))}
            </datalist>
          </Field>
          <Field label={t('Building style')} hint={t('Style class for procedural 3D buildings. Free text; suggestions provided.')}>
            <input
              className="ga-input"
              list="map3d-style-options"
              value={draft.map3d?.style || ''}
              placeholder={t('auto')}
              onChange={(e) => updMap3d('style', e.target.value.trim() ? e.target.value : undefined)}
            />
            <datalist id="map3d-style-options">
              {MAP3D_STYLES.map((v) => (
                <option key={v} value={v} />
              ))}
            </datalist>
          </Field>
          <Field label={t('Floors')} hint={t('Number of floors of the building.')}>
            <input
              className="ga-input"
              type="number"
              min={1}
              value={draft.map3d?.floors ?? ''}
              placeholder={t('auto')}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10)
                updMap3d('floors', Number.isFinite(n) && n > 0 ? n : undefined)
              }}
            />
          </Field>
        </div>
        <div className="ga-form-row">
          <Field label={t('Footprint (W × D)')} hint={t('Building base size in map grid cells.')}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <input
                className="ga-input"
                type="number"
                min={1}
                style={{ width: 70 }}
                value={footprint[0] || ''}
                placeholder="1"
                onChange={(e) => setFootprint(0, e.target.value)}
              />
              <span>×</span>
              <input
                className="ga-input"
                type="number"
                min={1}
                style={{ width: 70 }}
                value={footprint[1] || ''}
                placeholder="1"
                onChange={(e) => setFootprint(1, e.target.value)}
              />
            </div>
          </Field>
          <Field label={t('Building color')} hint={t('Base color for procedural buildings (hex).')}>
            <div style={{ display: 'flex', gap: 4 }}>
              <input
                type="color"
                value={draft.map3d?.color || '#8fa3b0'}
                onChange={(e) => updMap3d('color', e.target.value)}
              />
              <input
                className="ga-input"
                value={draft.map3d?.color || ''}
                placeholder="#8fa3b0"
                onChange={(e) => updMap3d('color', e.target.value.trim() ? e.target.value.trim() : undefined)}
              />
            </div>
          </Field>
        </div>

        <div className="ga-loc-twocol">
          <div>
            <div className="ga-form-section-label">{t('Image prompts')}</div>
            <div className="ga-form">
              <Field label={t('Day prompt')} help="image_prompt">
                <textarea
                  className="ga-textarea"
                  rows={2}
                  value={draft.image_prompt_day || ''}
                  onChange={(e) => upd('image_prompt_day', e.target.value)}
                />
              </Field>
              <Field label={t('Night prompt')} help="image_prompt">
                <textarea
                  className="ga-textarea"
                  rows={2}
                  value={draft.image_prompt_night || ''}
                  onChange={(e) => upd('image_prompt_night', e.target.value)}
                />
              </Field>
              <Field label={t('2D map icon prompt')} help="image_prompt">
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
