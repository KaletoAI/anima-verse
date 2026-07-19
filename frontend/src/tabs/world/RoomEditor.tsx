import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'
import { type ItemRef } from '../../lib/refs'
import { type Location, type Room } from './worldTypes'
import { RoomItems } from './RoomItems'
import { BuildingModelPanel } from './BuildingModelPanel'

// ── Room editor ────────────────────────────────────────────────────────────

interface RoomEditorProps {
  location: Location
  room: Room
  items: ItemRef[]
  /** Gallery image picked via 🧊 for the room model — wired through WorldTab. */
  modelGenSource: string | null
  onModelGenConsumed: () => void
  onChanged: () => void
  onDeleted: () => void
}

export function RoomEditor({ location, room, items, modelGenSource, onModelGenConsumed, onChanged, onDeleted }: RoomEditorProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [draft, setDraft] = useState<Room>(() => ({ ...room }))
  // Two tabs, mirroring the location editor: General (fields + items) and
  // 3D world (the room model). One draft spans both — Save persists it all.
  const [tab, setTab] = useState<'general' | '3d'>('general')

  useEffect(() => {
    setDraft({ ...room })
  }, [room])

  // 🧊 in the room gallery picks a source image — the backend picker lives in
  // the model panel on the 3D tab, so switch there or the dialog stays unseen.
  useEffect(() => {
    if (modelGenSource) setTab('3d')
  }, [modelGenSource])

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
      <nav className="ga-subtabs">
        {([
          { id: 'general', label: 'General' },
          { id: '3d', label: '3D world' },
        ] as Array<{ id: 'general' | '3d'; label: string }>).map((tb) => (
          <button
            key={tb.id}
            type="button"
            className={`ga-btn ga-btn-sm${tab === tb.id ? ' ga-btn-primary' : ''}`}
            onClick={() => setTab(tb.id)}
          >
            {t(tb.label)}
          </button>
        ))}
      </nav>
      {tab === '3d' ? (
        <div className="ga-form">
          <BuildingModelPanel
            locationId={location.id}
            roomId={room.id || ''}
            generateSource={modelGenSource}
            onGenerateSourceConsumed={onModelGenConsumed}
          />
        </div>
      ) : (
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
          <Field label={t('Indoor/Outdoor')} hint={t('Overrides the location for this room (e.g. a pool room in an indoor house = outdoor). Empty = inherit location.')}>
            <select className="ga-input" value={draft.indoor || ''}
              onChange={(e) => upd('indoor', e.target.value)}>
              <option value="">{t('Inherit from location')}</option>
              <option value="indoor">{t('Indoor')}</option>
              <option value="outdoor">{t('Outdoor')}</option>
            </select>
          </Field>
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
              help="image_prompt"
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
              help="image_prompt"
              hint={t('Per-room override. Falls back to the location night prompt when empty.')}
            >
              <textarea
                className="ga-textarea"
                rows={2}
                value={draft.image_prompt_night || ''}
                onChange={(e) => upd('image_prompt_night', e.target.value)}
              />
            </Field>
            <Field
              label={t('3D model prompt')}
              help="image_prompt"
              hint={t('Subject for the 3D-model source image (🧊). Falls back to the room description when empty.')}
            >
              <textarea
                className="ga-textarea"
                rows={2}
                value={draft.image_prompt_building || ''}
                onChange={(e) => upd('image_prompt_building', e.target.value)}
              />
            </Field>
          </div>
        </div>

        <RoomItems locationId={location.id} roomId={room.id || ''} items={items} />
      </div>
      )}
    </>
  )
}
