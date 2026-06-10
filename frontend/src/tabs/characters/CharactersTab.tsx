import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ExportButton, ImportButton, PublishButton } from '../../components/ImportExport'
import {
  loadActivities,
  loadCharacters,
  loadLocations,
  type ActivityRef,
  type CharacterRef,
  type LocationRef,
  type RoomRef,
} from '../../lib/refs'
import { SoulEditor } from './SoulEditor'
import { DailyScheduleGrid } from './DailyScheduleGrid'
import { ImageOverrides } from './ImageOverrides'
import { GalleryTab } from './GalleryTab'
import { SecretsEditor } from './SecretsEditor'
import { NewCharacterDialog } from './NewCharacterDialog'

/**
 * Game-Admin "Characters" tab — list-detail like Activities / Rules /
 * States / Items. Per-character live state (location, room, activity,
 * feeling) lives here. Template-switch and full profile editing stay
 * in their existing flows; this tab is for the lightweight overrides
 * an admin needs day-to-day.
 */

interface CurrentLocation {
  character: string
  current_location: string
  current_location_id: string
  current_activity: string
  current_room: string
  current_room_name: string
}

interface DraftPlacement {
  locationId: string
  roomId: string
  activity: string
  feeling: string
}

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

type SubTabId = 'general' | 'soul' | 'behavior' | 'image' | 'gallery' | 'home' | 'secrets' | 'others'

interface ScheduleSlot {
  hour: number
  location: string
  role: string
  sleep: boolean
}

// Sentinel home_location value: character sleeps off the map (not in any room).
const OFFMAP_SLEEP = '__offmap__'

const SUB_TABS: Array<{ id: SubTabId; label: string }> = [
  { id: 'general', label: 'General' },
  { id: 'soul', label: 'Soul' },
  { id: 'behavior', label: 'Behavior' },
  { id: 'image', label: 'Image' },
  { id: 'gallery', label: 'Gallery' },
  { id: 'home', label: 'Activity & Home' },
  { id: 'secrets', label: 'Secrets' },
  { id: 'others', label: 'Others' },
]

// Mirrors the language options in shared/templates/character/base-character.json.
const LANGUAGES: Array<{ value: string; label: string }> = [
  { value: 'de', label: 'Deutsch' },
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' },
  { value: 'es', label: 'Español' },
  { value: 'it', label: 'Italiano' },
  { value: 'pt', label: 'Português' },
  { value: 'nl', label: 'Nederlands' },
  { value: 'pl', label: 'Polski' },
  { value: 'ru', label: 'Русский' },
  { value: 'ja', label: '日本語' },
  { value: 'zh', label: '中文' },
  { value: 'ko', label: '한국어' },
]

// Framed group of related fields with an uppercase title.
function FieldSet({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="ga-fieldset">
      <div className="ga-fieldset-title">{title}</div>
      {children}
    </div>
  )
}

export function CharactersTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [characters, setCharacters] = useState<CharacterRef[]>([])
  const [locations, setLocations] = useState<LocationRef[]>([])
  const [activities, setActivities] = useState<ActivityRef[]>([])
  const [selected, setSelected] = useState<string>('')
  const [current, setCurrent] = useState<CurrentLocation | null>(null)
  const [currentFeeling, setCurrentFeeling] = useState<string>('')
  const [draft, setDraft] = useState<DraftPlacement | null>(null)
  const [saving, setSaving] = useState(false)
  // Per-character config (chat_mode, behavior toggles, …) + profile language.
  // Config fields save immediately on change via /config; language via /profile.
  const [cfg, setCfg] = useState<Record<string, unknown>>({})
  const [language, setLanguage] = useState<string>('')
  const [decencyPref, setDecencyPref] = useState<string>('')
  const [savingField, setSavingField] = useState<string>('')
  const [subTab, setSubTab] = useState<SubTabId>('general')
  // Dynamic TTS option lists (Others tab) — loaded once on mount.
  const [ttsVoices, setTtsVoices] = useState<Array<{ value: string; label: string }>>([])
  const [ttsSpeakers, setTtsSpeakers] = useState<Array<{ value: string; label: string }>>([])
  // Activity & Home: home/sleep location + daily rhythm (grid is self-managed).
  const [homeLoc, setHomeLoc] = useState<{ home_location: string; home_room: string }>({
    home_location: '',
    home_room: '',
  })
  const [schedule, setSchedule] = useState<{ enabled: boolean; slots: ScheduleSlot[] }>({
    enabled: false,
    slots: [],
  })
  const [homeLoading, setHomeLoading] = useState(false)
  // "New character" dialog — open state only; the dialog manages its own form.
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    loadCharacters().then(setCharacters).catch(() => setCharacters([]))
    loadLocations().then(setLocations).catch(() => setLocations([]))
    loadActivities().then(setActivities).catch(() => setActivities([]))
    apiGet<{ voices?: Array<{ value: string; label: string }> }>('/tts/voices')
      .then((d) => setTtsVoices(d.voices || []))
      .catch(() => setTtsVoices([]))
    apiGet<{ speakers?: Array<{ value: string; label: string }> }>('/tts/speakers')
      .then((d) => setTtsSpeakers(d.speakers || []))
      .catch(() => setTtsSpeakers([]))
  }, [])

  // Load home location + daily rhythm when the Activity & Home tab opens.
  useEffect(() => {
    if (subTab !== 'home' || !selected) return
    let cancelled = false
    setHomeLoading(true)
    ;(async () => {
      try {
        const [home, sched] = await Promise.all([
          apiGet<{ home_location?: string; home_room?: string }>(
            `/characters/${encodeURIComponent(selected)}/home-location`,
          ),
          apiGet<{ schedule?: { enabled?: boolean; slots?: ScheduleSlot[] } }>(
            `/scheduler/daily-schedule?character=${encodeURIComponent(selected)}`,
          ),
        ])
        if (cancelled) return
        setHomeLoc({
          home_location: home.home_location || '',
          home_room: home.home_room || '',
        })
        setSchedule({
          enabled: !!sched.schedule?.enabled,
          slots: (sched.schedule?.slots || []).map((s) => ({
            hour: Number(s.hour) || 0,
            location: s.location || '',
            role: s.role || '',
            sleep: !!s.sleep,
          })),
        })
      } catch (e) {
        if (!cancelled) toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      } finally {
        if (!cancelled) setHomeLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selected, subTab, t, toast])

  const reloadCurrent = useCallback(
    async (name: string) => {
      setCurrent(null)
      setCurrentFeeling('')
      setDraft(null)
      if (!name) return
      try {
        const [loc, feel, cfgResp] = await Promise.all([
          apiGet<CurrentLocation>(`/characters/${encodeURIComponent(name)}/current-location`),
          apiGet<{ current_feeling?: string }>(`/characters/${encodeURIComponent(name)}/current-feeling`),
          apiGet<{ config?: Record<string, unknown> }>(`/characters/${encodeURIComponent(name)}/config`),
        ])
        setCurrent(loc)
        setCurrentFeeling(feel.current_feeling || '')
        const config = cfgResp.config || {}
        setCfg(config)
        // /config injects the profile language as tts_language (see get_character_config)
        setLanguage(String(config.tts_language || ''))
        setDecencyPref(String(config.decency_preference || ''))
        setDraft({
          locationId: loc.current_location_id || '',
          roomId: loc.current_room || '',
          activity: loc.current_activity || '',
          feeling: feel.current_feeling || '',
        })
      } catch (e) {
        toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
      }
    },
    [t, toast],
  )

  const onSelect = useCallback(
    (name: string) => {
      setSelected(name)
      reloadCurrent(name)
    },
    [reloadCurrent],
  )

  const selectedLocation: LocationRef | undefined = useMemo(
    () => locations.find((l) => l.id === draft?.locationId),
    [locations, draft],
  )

  const rooms: RoomRef[] = selectedLocation?.rooms || []

  // Group activities by their `_group` for the dropdown — same shape
  // the Library tab uses, makes the long list scannable.
  const activitiesByGroup = useMemo(() => {
    const groups = new Map<string, ActivityRef[]>()
    for (const a of activities) {
      const g = a._group || 'Other'
      if (!groups.has(g)) groups.set(g, [])
      groups.get(g)!.push(a)
    }
    for (const list of groups.values()) {
      list.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [activities])

  const dirty = useMemo(() => {
    if (!current || !draft) return false
    const curLoc = current.current_location_id || ''
    const curRoom = current.current_room || ''
    const curAct = current.current_activity || ''
    const curFeel = currentFeeling || ''
    return (
      draft.locationId !== curLoc ||
      (draft.roomId || '') !== curRoom ||
      (draft.activity || '') !== curAct ||
      (draft.feeling || '') !== curFeel
    )
  }, [current, currentFeeling, draft])

  const save = useCallback(async () => {
    if (!selected || !draft || !current) return
    setSaving(true)
    try {
      const tasks: Promise<unknown>[] = []
      // Only POST what actually changed — fewer side-effects (e.g. the
      // location POST also runs the avatar-room-entry hook). Compare
      // against `current`, not against the pre-edit baseline that lives
      // in `draft` itself.
      const curLoc = current.current_location_id || ''
      const curRoom = current.current_room || ''
      const curAct = current.current_activity || ''
      if (draft.locationId !== curLoc || (draft.roomId || '') !== curRoom) {
        tasks.push(
          apiPost(`/characters/${encodeURIComponent(selected)}/current-location`, {
            current_location: draft.locationId,
            current_room: draft.roomId,
          }),
        )
      }
      if ((draft.activity || '') !== curAct) {
        tasks.push(
          apiPost(`/characters/${encodeURIComponent(selected)}/current-activity`, {
            current_activity: draft.activity,
          }),
        )
      }
      if ((draft.feeling || '') !== (currentFeeling || '')) {
        tasks.push(
          apiPost(`/characters/${encodeURIComponent(selected)}/current-feeling`, {
            current_feeling: draft.feeling,
          }),
        )
      }
      await Promise.all(tasks)
      toast(t('Saved'))
      await reloadCurrent(selected)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [current, currentFeeling, draft, reloadCurrent, selected, t, toast])

  // Save a single config field immediately (optimistic), via /config bulk-update.
  const saveCfg = useCallback(
    async (key: string, value: unknown) => {
      if (!selected) return
      setCfg((prev) => ({ ...prev, [key]: value }))
      setSavingField(key)
      try {
        await apiPost(`/characters/${encodeURIComponent(selected)}/config`, {
          fields: { [key]: value },
        })
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setSavingField('')
      }
    },
    [selected, t, toast],
  )

  // Language is a profile field (not config) — saved via /profile.
  const saveLanguage = useCallback(
    async (value: string) => {
      if (!selected) return
      setLanguage(value)
      setSavingField('language')
      try {
        await apiPost(`/characters/${encodeURIComponent(selected)}/profile`, {
          fields: { language: value },
        })
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setSavingField('')
      }
    },
    [selected, t, toast],
  )

  // decency_preference — free-text styling hint, profile field (saved via /profile).
  const saveDecencyPref = useCallback(
    async (value: string) => {
      if (!selected) return
      setSavingField('decency_preference')
      try {
        await apiPost(`/characters/${encodeURIComponent(selected)}/profile`, {
          fields: { decency_preference: value },
        })
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setSavingField('')
      }
    },
    [selected, t, toast],
  )

  // Expression-Cache dieses Characters löschen (regeneriert bei Bedarf neu).
  const clearExprCache = useCallback(async () => {
    if (!selected) return
    setSavingField('clear_expr_cache')
    try {
      const r = await apiPost<{ deleted?: number }>(
        `/characters/${encodeURIComponent(selected)}/clear-expression-cache`, {})
      const n = typeof r?.deleted === 'number' ? r.deleted : 0
      toast(t('Expression cache cleared') + ` (${n})`)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSavingField('')
    }
  }, [selected, t, toast])

  // Home/sleep location — saved immediately via /home-location.
  const saveHome = useCallback(
    async (next: { home_location: string; home_room: string }) => {
      if (!selected) return
      setHomeLoc(next)
      setSavingField('home_location')
      try {
        await apiPost(`/characters/${encodeURIComponent(selected)}/home-location`, next)
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setSavingField('')
      }
    },
    [selected, t, toast],
  )

  const sortedCharacters = useMemo(
    () => [...characters].sort((a, b) => a.name.localeCompare(b.name)),
    [characters],
  )

  return (
    <div className="ga-twocol">
      <aside className="ga-twocol-left">
        <div className="ga-twocol-header">
          <h3>{t('Characters')}</h3>
          <div className="ga-twocol-header-actions">
            <button type="button" className="ga-btn ga-btn-primary" onClick={() => setCreating(true)}>
              {t('New character')}
            </button>
            <ImportButton
              endpoint="/characters/import"
              overwriteSupported
              onImported={() => {
                loadCharacters().then(setCharacters).catch(() => {})
              }}
            />
          </div>
        </div>
        <ul className="ga-list">
          {sortedCharacters.length === 0 ? (
            <li className="ga-list-empty">{t('No characters')}</li>
          ) : (
            sortedCharacters.map((c) => {
              const isActive = c.name === selected
              return (
                <li key={c.name}>
                  <button
                    type="button"
                    className={`ga-list-row${isActive ? ' is-active' : ''}`}
                    onClick={() => onSelect(c.name)}
                  >
                    <span className="ga-list-row-main">
                      <strong>{c.display_name || c.name}</strong>
                    </span>
                  </button>
                </li>
              )
            })
          )}
        </ul>
      </aside>
      <section className="ga-twocol-right">
        {!selected ? (
          <div className="ga-placeholder">{t('Pick a character to edit their settings.')}</div>
        ) : !current || !draft ? (
          <div className="ga-loading">{t('Loading…')}</div>
        ) : (
          <>
            <DetailToolbar
              title={selected}
              onSave={dirty ? save : undefined}
              onCancel={dirty ? () => reloadCurrent(selected) : undefined}
              cancelLabel={t('Revert')}
              disabled={saving}
              extra={
                <>
                  <ExportButton
                    endpoint={`/characters/${encodeURIComponent(selected)}/export`}
                    filename={`${selected}_export.zip`}
                    options={[
                      { key: 'include_chats', label: t('Include chat history') },
                      { key: 'include_stories', label: t('Include story progress') },
                    ]}
                  />
                  <PublishButton
                    packType="character"
                    entityId={selected}
                    defaultName={selected}
                  />
                </>
              }
            />
            <nav className="ga-subtabs">
              {SUB_TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={`ga-btn ga-btn-sm${subTab === tab.id ? ' ga-btn-primary' : ''}`}
                  onClick={() => setSubTab(tab.id)}
                >
                  {t(tab.label)}
                </button>
              ))}
            </nav>

            {subTab === 'general' ? (
              <div className="ga-form">
                <FieldSet title={t('Identity')}>
                <div className="ga-form-row">
                  <Field label={t('Name')} hint={t('Character identifier — not editable here.')}>
                    <input className="ga-input" value={selected} disabled readOnly />
                  </Field>
                  <Field
                    label={t('Language')}
                    hint={t('Language the character thinks and speaks in.')}
                  >
                    <select
                      className="ga-input"
                      value={language}
                      disabled={savingField === 'language'}
                      onChange={(e) => saveLanguage(e.target.value)}
                    >
                      {LANGUAGES.map((l) => (
                        <option key={l.value} value={l.value}>
                          {l.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>

                </FieldSet>
                <FieldSet title={t('Current state')}>
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
                  <Field
                    label={t('Activity')}
                    hint={
                      current.current_activity
                        ? t('Currently: {name}').replace('{name}', current.current_activity)
                        : t('Setting an activity may auto-move the character into a matching room.')
                    }
                  >
                    <select
                      className="ga-input"
                      value={draft.activity}
                      onChange={(e) => setDraft({ ...draft, activity: e.target.value })}
                    >
                      <option value="">— {t('none')} —</option>
                      {/* current value may not be a library id (e.g. flag-derived
                          "Sleeping") — surface it so the field is never blank-mysterious */}
                      {draft.activity &&
                      !activities.some((a) => a.id === draft.activity) ? (
                        <option value={draft.activity}>{draft.activity}</option>
                      ) : null}
                      {activitiesByGroup.map(([group, list]) => (
                        <optgroup key={group} label={group}>
                          {list.map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name || a.id}
                            </option>
                          ))}
                        </optgroup>
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
                </div>
                </FieldSet>
              </div>
            ) : subTab === 'behavior' ? (
              <div className="ga-form">
                <FieldSet title={t('Behavior')}>
                <div className="ga-form-row">
                  <Field
                    label={t('Chat mode')}
                    hint={t(
                      'Single: chat-LLM handles RP and tool decisions in one call. RP-First: chat-LLM writes clean RP, then a tool-LLM decides on tools — better for RP-finetuned models. With no skills active it is always no_tools.',
                    )}
                  >
                    <select
                      className="ga-input"
                      value={String(cfg.chat_mode ?? '')}
                      disabled={savingField === 'chat_mode'}
                      onChange={(e) => saveCfg('chat_mode', e.target.value)}
                    >
                      <option value="">{t('Single (chat-LLM handles all)')}</option>
                      <option value="rp_first">{t('RP-First (chat-LLM + tool-LLM)')}</option>
                    </select>
                  </Field>
                  <Field
                    label={t('Relationships')}
                    hint={t('Track and evolve relationships with other characters.')}
                  >
                    <select
                      className="ga-input"
                      value={String(cfg.relationships_enabled ?? 'true')}
                      disabled={savingField === 'relationships_enabled'}
                      onChange={(e) => saveCfg('relationships_enabled', e.target.value)}
                    >
                      <option value="true">{t('On')}</option>
                      <option value="false">{t('Off')}</option>
                    </select>
                  </Field>
                  <Field
                    label={t('Mood tracking')}
                    hint={t('Character ends responses with their current emotional state.')}
                  >
                    <select
                      className="ga-input"
                      value={String(cfg.mood_tracking ?? 'true')}
                      disabled={savingField === 'mood_tracking'}
                      onChange={(e) => saveCfg('mood_tracking', e.target.value)}
                    >
                      <option value="true">{t('Yes')}</option>
                      <option value="false">{t('No')}</option>
                    </select>
                  </Field>
                </div>
                <div className="ga-form-row">
                  <Field
                    label={t('Photographer mode')}
                    hint={t('On: takes photos of others (not in own shots). Off: appears in own photos.')}
                  >
                    <select
                      className="ga-input"
                      value={String(cfg.photographer_mode ?? 'false')}
                      disabled={savingField === 'photographer_mode'}
                      onChange={(e) => saveCfg('photographer_mode', e.target.value)}
                    >
                      <option value="false">{t('Off (appears in own photos)')}</option>
                      <option value="true">{t('On (takes photos of others)')}</option>
                    </select>
                  </Field>
                </div>
                <div className="ga-form-row">
                  <Field
                    label={t('Dressing preference')}
                    hint={t('Free-text personal style hint used when generating outfits, e.g. "often barefoot, no underwear, shirtless at home". Coverage is still enforced by the room decency (public/private/nude_ok) — this only nudges style.')}
                  >
                    <textarea
                      className="ga-textarea"
                      rows={2}
                      value={decencyPref}
                      disabled={savingField === 'decency_preference'}
                      onChange={(e) => setDecencyPref(e.target.value)}
                      onBlur={(e) => saveDecencyPref(e.target.value)}
                    />
                  </Field>
                </div>
                <div className="ga-form-row">
                  <Field
                    label={t('Expression cache')}
                    hint={t('Delete all cached expression images for this character. They regenerate on demand (now limited via pose variants + LRU).')}
                  >
                    <button
                      type="button"
                      className="ga-btn ga-btn-sm ga-btn-danger"
                      disabled={savingField === 'clear_expr_cache'}
                      onClick={clearExprCache}
                    >
                      {t('Clear expression cache')}
                    </button>
                  </Field>
                </div>
                </FieldSet>
              </div>
            ) : subTab === 'soul' ? (
              <div className="ga-form">
                <FieldSet title={t('Thinking')}>
                <div className="ga-form-row">
                  <Field
                    label={t('Thoughts')}
                    hint={t(
                      'If active, the character periodically thinks and can autonomously act (talk, send messages, change activity, …).',
                    )}
                  >
                    <select
                      className="ga-input"
                      value={String(cfg.thoughts_enabled ?? 'false')}
                      disabled={savingField === 'thoughts_enabled'}
                      onChange={(e) => saveCfg('thoughts_enabled', e.target.value)}
                    >
                      <option value="true">{t('Yes')}</option>
                      <option value="false">{t('No')}</option>
                    </select>
                  </Field>
                  <Field
                    label={t('Importance')}
                    hint={t('How often this character gets to think relative to others. High = 3× as often as Low.')}
                  >
                    <select
                      className="ga-input"
                      value={String(cfg.importance ?? '1')}
                      disabled={savingField === 'importance'}
                      onChange={(e) => saveCfg('importance', e.target.value)}
                    >
                      <option value="1">{t('Low')}</option>
                      <option value="2">{t('Medium')}</option>
                      <option value="3">{t('High')}</option>
                    </select>
                  </Field>
                  <Field
                    label={t('Retrospect')}
                    hint={t(
                      'If active, the character periodically reflects on recent events to update beliefs, lessons and goals.',
                    )}
                  >
                    <select
                      className="ga-input"
                      value={String(cfg.retrospect_enabled ?? 'true')}
                      disabled={savingField === 'retrospect_enabled'}
                      onChange={(e) => saveCfg('retrospect_enabled', e.target.value)}
                    >
                      <option value="true">{t('Yes')}</option>
                      <option value="false">{t('No')}</option>
                    </select>
                  </Field>
                </div>
                </FieldSet>
                <FieldSet title={t('Soul texts')}>
                <SoulEditor character={selected} />
                </FieldSet>
              </div>
            ) : subTab === 'others' ? (
              <div className="ga-form">
                <FieldSet title={t('Speech (TTS)')}>
                <div className="ga-form-row">
                  <Field label={t('TTS enabled')} hint={t('Generate speech audio for this character.')}>
                    <select
                      className="ga-input"
                      value={String(cfg.tts_enabled ?? 'false')}
                      disabled={savingField === 'tts_enabled'}
                      onChange={(e) => saveCfg('tts_enabled', e.target.value)}
                    >
                      <option value="true">{t('Yes')}</option>
                      <option value="false">{t('No')}</option>
                    </select>
                  </Field>
                  <Field label={t('Auto-play')} hint={t('Speak responses automatically without a click.')}>
                    <select
                      className="ga-input"
                      value={String(cfg.tts_auto ?? 'false')}
                      disabled={savingField === 'tts_auto'}
                      onChange={(e) => saveCfg('tts_auto', e.target.value)}
                    >
                      <option value="true">{t('Yes')}</option>
                      <option value="false">{t('No')}</option>
                    </select>
                  </Field>
                  <Field label={t('ComfyUI TTS mode')} hint={t('Voice Clone uses a WAV reference. Voice Name generates a voice from the description.')}>
                    <select
                      className="ga-input"
                      value={String(cfg.tts_comfyui_mode ?? '')}
                      disabled={savingField === 'tts_comfyui_mode'}
                      onChange={(e) => saveCfg('tts_comfyui_mode', e.target.value)}
                    >
                      <option value="">{t('Default (from .env)')}</option>
                      <option value="voiceclone">{t('Voice Clone (reference audio)')}</option>
                      <option value="auto">{t('Voice Name (from description)')}</option>
                    </select>
                  </Field>
                </div>
                <div className="ga-form-row">
                  <Field label={t('Voice (Magpie)')} hint={t('Voice for the Magpie backend.')}>
                    <select
                      className="ga-input"
                      value={String(cfg.tts_voice ?? '')}
                      disabled={savingField === 'tts_voice'}
                      onChange={(e) => saveCfg('tts_voice', e.target.value)}
                    >
                      <option value="">— {t('default')} —</option>
                      {String(cfg.tts_voice ?? '') &&
                      !ttsVoices.some((v) => v.value === cfg.tts_voice) ? (
                        <option value={String(cfg.tts_voice)}>{String(cfg.tts_voice)}</option>
                      ) : null}
                      {ttsVoices.map((v) => (
                        <option key={v.value} value={v.value}>
                          {v.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label={t('Reference voice (XTTS / F5 / ComfyUI)')} hint={t('Reference WAV for voice cloning.')}>
                    <select
                      className="ga-input"
                      value={String(cfg.tts_speaker_wav ?? '')}
                      disabled={savingField === 'tts_speaker_wav'}
                      onChange={(e) => saveCfg('tts_speaker_wav', e.target.value)}
                    >
                      <option value="">— {t('none')} —</option>
                      {String(cfg.tts_speaker_wav ?? '') &&
                      !ttsSpeakers.some((s) => s.value === cfg.tts_speaker_wav) ? (
                        <option value={String(cfg.tts_speaker_wav)}>{String(cfg.tts_speaker_wav)}</option>
                      ) : null}
                      {ttsSpeakers.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label={t('Voice description')} hint={t('For ComfyUI Voice-Name mode, e.g. “young woman, warm and slightly husky voice”.')}>
                    <textarea
                      className="ga-textarea"
                      rows={3}
                      value={String(cfg.tts_voice_description ?? '')}
                      onChange={(e) => setCfg((p) => ({ ...p, tts_voice_description: e.target.value }))}
                      onBlur={(e) => saveCfg('tts_voice_description', e.target.value)}
                    />
                  </Field>
                </div>
                </FieldSet>
                <FieldSet title={t('Telegram')}>
                <div className="ga-form-row">
                  <Field
                    label={t('Bot token')}
                    hint={t('Telegram bot token from @BotFather. Each character needs its own bot. Reload polling after saving.')}
                  >
                    <input
                      className="ga-input"
                      type="password"
                      autoComplete="off"
                      value={String(cfg.telegram_bot_token ?? '')}
                      onChange={(e) => setCfg((p) => ({ ...p, telegram_bot_token: e.target.value }))}
                      onBlur={(e) => saveCfg('telegram_bot_token', e.target.value)}
                    />
                  </Field>
                  <Field
                    label={t('Partner character')}
                    hint={t('In-world character the human on the other side of this bot controls. Empty = no identity tagging.')}
                  >
                    <select
                      className="ga-input"
                      value={String(cfg.telegram_partner_character ?? '')}
                      disabled={savingField === 'telegram_partner_character'}
                      onChange={(e) => saveCfg('telegram_partner_character', e.target.value)}
                    >
                      <option value="">— {t('none')} —</option>
                      {sortedCharacters.map((c) => (
                        <option key={c.name} value={c.name}>
                          {c.display_name || c.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                </FieldSet>
              </div>
            ) : subTab === 'home' ? (
              homeLoading ? (
                <div className="ga-loading">{t('Loading…')}</div>
              ) : (
                <div className="ga-form">
                  <FieldSet title={t('Home / sleep location')}>
                  <div className="ga-form-row">
                    <Field
                      label={t('Home location')}
                      hint={t('Where the character lives and returns to sleep. “Off-map” takes them off the grid while sleeping.')}
                    >
                      <select
                        className="ga-input"
                        value={homeLoc.home_location}
                        disabled={savingField === 'home_location'}
                        onChange={(e) =>
                          saveHome({ home_location: e.target.value, home_room: '' })
                        }
                      >
                        <option value="">— {t('none')} —</option>
                        <option value={OFFMAP_SLEEP}>{t('Off-map (sleeps away)')}</option>
                        {locations.map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.name || l.id}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field
                      label={t('Home room')}
                      hint={t('Optional room within the home location.')}
                    >
                      <select
                        className="ga-input"
                        value={homeLoc.home_room}
                        disabled={
                          savingField === 'home_location' ||
                          homeLoc.home_location === OFFMAP_SLEEP ||
                          !homeLoc.home_location
                        }
                        onChange={(e) =>
                          saveHome({ home_location: homeLoc.home_location, home_room: e.target.value })
                        }
                      >
                        <option value="">— {t('any room')} —</option>
                        {(locations.find((l) => l.id === homeLoc.home_location)?.rooms || []).map(
                          (r) => (
                            <option key={r.id} value={r.id || ''}>
                              {r.name || r.id}
                            </option>
                          ),
                        )}
                      </select>
                    </Field>
                  </div>
                  </FieldSet>

                  <FieldSet title={t('Daily rhythm')}>
                  <DailyScheduleGrid
                    character={selected}
                    locations={locations}
                    roles={String(cfg.roles ?? '')
                      .split(',')
                      .map((r) => r.trim())
                      .filter(Boolean)}
                    initialEnabled={schedule.enabled}
                    initialSlots={schedule.slots}
                  />
                  </FieldSet>
                </div>
              )
            ) : subTab === 'image' ? (
              <ImageOverrides character={selected} />
            ) : subTab === 'gallery' ? (
              <GalleryTab character={selected} />
            ) : subTab === 'secrets' ? (
              <SecretsEditor character={selected} />
            ) : (
              <div className="ga-form">
                <div className="ga-placeholder">
                  {t('“{tab}” settings move here next.').replace(
                    '{tab}',
                    t(SUB_TABS.find((s) => s.id === subTab)?.label || ''),
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </section>
      {creating && (
        <NewCharacterDialog
          existing={characters.map((c) => c.name)}
          onClose={() => setCreating(false)}
          onCreated={(name) => {
            setCreating(false)
            loadCharacters()
              .then((list) => {
                setCharacters(list)
                onSelect(name)
              })
              .catch(() => onSelect(name))
          }}
        />
      )}
    </div>
  )
}
