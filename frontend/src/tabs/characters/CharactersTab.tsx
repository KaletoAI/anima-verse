import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
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
import { ExpressionsTab } from './ExpressionsTab'
import { type TmplSection } from './TemplateSectionForm'
import { TemplateTab } from './TemplateTab'
import { tmplText, type DynamicData } from './TemplateField'
import { SecretsEditor } from './SecretsEditor'
import { SkillsTab } from './SkillsTab'
import { WardrobeTab } from './WardrobeTab'
import { KnownLocationsEditor } from './KnownLocationsEditor'
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

interface ScheduleSlot {
  hour: number
  location: string
  role: string
  sleep: boolean
}

// Sentinel home_location value: character sleeps off the map (not in any room).
const OFFMAP_SLEEP = '__offmap__'

// Spezial-Tabs mit dedizierter UI (keine reinen Template-Feld-Sektionen). Die
// Feld-Tabs (General/Aussehen/Config/…) kommen generisch aus `template.tabs`
// (Spalten-Layout) und werden davor eingehängt — siehe fieldTabs.
// „Image" wird im subTabs-Build direkt hinter den „Aussehen"-Feld-Tab gesetzt
// (siehe subTabs). „Current state"/„Preferences" sind keine eigenen Tabs mehr:
// die Platzierung lebt in General col3, die Dressing-Preference in „Eigenschaften".
const SPECIAL_TABS: Array<{ id: string; label: string }> = [
  { id: 'soul', label: 'Soul' },
  { id: 'gallery', label: 'Gallery' },
  { id: 'expressions', label: 'Expressions' },
  { id: 'home', label: 'Activity & Home' },
  { id: 'locations', label: 'Locations' },
  { id: 'skills', label: 'Skills' },
  { id: 'wardrobe', label: 'Wardrobe' },
  { id: 'secrets', label: 'Secrets' },
]

interface TmplSectionRaw extends TmplSection {
  special?: unknown
  column?: number
  row?: number
}
interface TmplTabRaw {
  [k: string]: unknown
  id: string
  label?: string
  label_de?: string
  columns?: number[]
  special?: unknown
}

// Eine Sektion ist generisch renderbar, wenn sie KEIN Spezial-Panel ist und
// mindestens ein editierbares Feld hat (kein Soul-`source_file`, nicht nur
// readonly wie die „Current state"-Sektion).
function sectionIsGeneric(s: TmplSectionRaw): boolean {
  if (s.special) return false
  const fs = (s.fields || []).filter((f) => f.editor_visible !== false && !f.source_file)
  return fs.some((f) => !f.readonly)
}

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
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [characters, setCharacters] = useState<CharacterRef[]>([])
  const [locations, setLocations] = useState<LocationRef[]>([])
  const [activities, setActivities] = useState<ActivityRef[]>([])
  const [selected, setSelected] = useState<string>('')
  const [current, setCurrent] = useState<CurrentLocation | null>(null)
  const [currentFeeling, setCurrentFeeling] = useState<string>('')
  const [draft, setDraft] = useState<DraftPlacement | null>(null)
  const [saving, setSaving] = useState(false)
  // Per-character config (chat_mode, behavior toggles, …).
  // Config fields save immediately on change via /config.
  const [cfg, setCfg] = useState<Record<string, unknown>>({})
  const [savingField, setSavingField] = useState<string>('')
  const [subTab, setSubTab] = useState<string>('general')
  // Aufgelöstes Template des gewählten Characters — Quelle der generischen
  // Feld-Sektionen (Identity/Appearance/Behavior/…).
  const [template, setTemplate] = useState<{ sections?: TmplSectionRaw[]; tabs?: TmplTabRaw[] } | null>(null)
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
      setTemplate(null)
      if (!name) return
      try {
        const [loc, feel, cfgResp, profResp] = await Promise.all([
          apiGet<CurrentLocation>(`/characters/${encodeURIComponent(name)}/current-location`),
          apiGet<{ current_feeling?: string }>(`/characters/${encodeURIComponent(name)}/current-feeling`),
          apiGet<{ config?: Record<string, unknown> }>(`/characters/${encodeURIComponent(name)}/config`),
          apiGet<{ profile?: Record<string, unknown> }>(`/characters/${encodeURIComponent(name)}/profile`),
        ])
        setCurrent(loc)
        setCurrentFeeling(feel.current_feeling || '')
        const config = cfgResp.config || {}
        setCfg(config)
        // Template laden (generische Feld-Sektionen)
        const tmplId = String(profResp.profile?.template || '')
        if (tmplId) {
          apiGet<{ sections?: TmplSectionRaw[]; tabs?: TmplTabRaw[] }>(`/templates/${encodeURIComponent(tmplId)}`)
            .then((tmpl) => setTemplate(tmpl))
            .catch(() => setTemplate(null))
        }
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

  // Feld-Tabs aus dem Template: jeder Tab besitzt einen Spalten-Bereich
  // (`columns`); ein Tab erscheint, wenn er KEIN Spezial-Tab ist und in seinen
  // Spalten mindestens eine generisch renderbare Section liegt. Reihenfolge =
  // Tab-Reihenfolge im Template.
  const fieldTabs = useMemo(() => {
    const tabs = template?.tabs || []
    const secs = template?.sections || []
    return tabs
      .filter((tb) => !tb.special && Array.isArray(tb.columns) && tb.columns.length > 0)
      .filter((tb) =>
        secs.some((s) => sectionIsGeneric(s) && (tb.columns || []).includes(s.column || 1)),
      )
      .map((tb) => ({ id: `tab:${tb.id}`, label: tmplText(tb, 'label', lang) || tb.id, tab: tb }))
  }, [template, lang])

  // Feld-Tabs zuerst, dann die Spezial-Tabs. „Image" wird direkt hinter den
  // „Aussehen"-Tab eingefügt (Wunsch: Reiter Bild hinter Reiter Aussehen).
  const subTabs = useMemo(() => {
    const out: Array<{ id: string; label: string }> = []
    let imagePlaced = false
    for (const ft of fieldTabs) {
      out.push({ id: ft.id, label: ft.label })
      if (ft.tab.id === 'aussehen') {
        out.push({ id: 'image', label: 'Image' })
        imagePlaced = true
      }
    }
    if (!imagePlaced) out.push({ id: 'image', label: 'Image' })
    out.push(...SPECIAL_TABS)
    return out
  }, [fieldTabs])

  // Beim Character-Wechsel einmalig auf den ersten Feld-Tab (z.B. „General")
  // springen, sobald das Template geladen ist — statt auf „Current state".
  const autoTabFor = useRef<string>('')
  useEffect(() => {
    if (selected && fieldTabs.length && autoTabFor.current !== selected) {
      autoTabFor.current = selected
      setSubTab(fieldTabs[0].id)
    }
  }, [selected, fieldTabs])

  // Dynamische Optionsquellen für Template-Selects.
  const dynamicData: DynamicData = useMemo(
    () => ({
      tts_voices: ttsVoices,
      tts_speakers: ttsSpeakers,
      characters: sortedCharacters.map((c) => ({ value: c.name, label: c.display_name || c.name })),
    }),
    [ttsVoices, ttsSpeakers, sortedCharacters],
  )

  // Editierbare „Aktueller Zustand"-Platzierung — wird als Spezial-Slot
  // (section.special === "placement") in Spalte 3 des General-Tabs gerendert.
  const placementUI =
    current && draft ? (
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
              {draft.activity && !activities.some((a) => a.id === draft.activity) ? (
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
      </>
    ) : null

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
              {subTabs.map((tab) => (
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

            {subTab.startsWith('tab:') ? (
              (() => {
                const ft = fieldTabs.find((g) => g.id === subTab)
                return ft ? (
                  <TemplateTab
                    character={selected}
                    tab={ft.tab}
                    sections={template?.sections || []}
                    dynamicData={dynamicData}
                    specialSlots={{ placement: placementUI }}
                  />
                ) : null
              })()
            ) : subTab === 'soul' ? (
              <div className="ga-form">
                <FieldSet title={t('Soul texts')}>
                <SoulEditor character={selected} />
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
            ) : subTab === 'locations' ? (
              <KnownLocationsEditor character={selected} />
            ) : subTab === 'image' ? (
              <ImageOverrides character={selected} />
            ) : subTab === 'gallery' ? (
              <GalleryTab character={selected} />
            ) : subTab === 'expressions' ? (
              <ExpressionsTab character={selected} />
            ) : subTab === 'skills' ? (
              <SkillsTab character={selected} />
            ) : subTab === 'wardrobe' ? (
              <WardrobeTab character={selected} />
            ) : subTab === 'secrets' ? (
              <SecretsEditor character={selected} />
            ) : (
              <div className="ga-form">
                <div className="ga-placeholder">
                  {t('“{tab}” settings move here next.').replace(
                    '{tab}',
                    t(subTabs.find((s) => s.id === subTab)?.label || ''),
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
