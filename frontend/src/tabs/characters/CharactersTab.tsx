import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiPut, apiDelete } from '../../lib/api'
import { setUnsavedGuard } from '../../lib/unsavedGuard'
import { useToast } from '../../lib/Toast'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ExportButton, PublishButton } from '../../components/ImportExport'
import {
  loadCharacters,
  loadLocations,
  type CharacterRef,
  type LocationRef,
  type RoomRef,
} from '../../lib/refs'
import { SoulEditor } from './SoulEditor'
import { ImageOverrides } from './ImageOverrides'
import { GalleryTab } from './GalleryTab'
import { ExpressionsTab } from './ExpressionsTab'
import { type TmplSection } from './TemplateSectionForm'
import { TemplateTab } from './TemplateTab'
import { BodyEditor } from './BodyEditor'
import { FieldModel3D } from './FieldModel3D'
import { FieldModelRefs } from './FieldModelRefs'
import { TemplateSelector } from './TemplateSelector'
import { tmplText, type DynamicData } from './TemplateField'
import { SecretsEditor } from './SecretsEditor'
import { SkillsTab } from './SkillsTab'
import { WardrobeTab } from './WardrobeTab'
import { KnownLocationsEditor } from './KnownLocationsEditor'
import { NewCharacterDialog } from './NewCharacterDialog'
import { NewNpcDialog } from './NewNpcDialog'
import { FieldSet } from './FieldSet'
import { PlacementEditor } from './PlacementEditor'
import { ActivityHomeTab } from './ActivityHomeTab'
import { CharacterListPanel } from './CharacterListPanel'
import {
  CONFIG_TARGET,
  IMAGEGEN_TARGET,
  PROFILE_TARGET,
  bodyTarget,
  emptyFields,
  pendingFieldCount,
  queueFields,
  targetPatch,
  toSaveBody,
  type PendingFields,
} from './pendingFields'

/**
 * Game-Admin "Characters" tab — list-detail like Activities / Rules /
 * States / Items. Per-character live state (location, room, activity,
 * feeling) lives here. Template-switch and full profile editing stay
 * in their existing flows; this tab is for the lightweight overrides
 * an admin needs day-to-day.
 */

export interface CurrentLocation {
  character: string
  current_location: string
  current_location_id: string
  current_activity: string
  current_room: string
  current_room_name: string
}

export interface DraftPlacement {
  locationId: string
  roomId: string
  activity: string
  feeling: string
}

export interface ScheduleSlot {
  hour: number
  location: string
  role: string
  sleep: boolean
}

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

// Special sections this editor can render (keys of `specialSlots` below).
// A tab made up ONLY of special sections — like the 3D tab — is visible
// exactly when its sections have a slot here; without this it would be
// filtered out as "no generic fields".
const SPECIAL_SLOTS = new Set([
  'placement', 'body_editor', 'model_refs', 'model3d_gen',
])

function sectionIsRenderable(s: TmplSectionRaw): boolean {
  if (s.special) return SPECIAL_SLOTS.has(String(s.special))
  return sectionIsGeneric(s)
}

export function CharactersTab() {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [characters, setCharacters] = useState<CharacterRef[]>([])
  const [locations, setLocations] = useState<LocationRef[]>([])
  const [selected, setSelected] = useState<string>('')
  const [current, setCurrent] = useState<CurrentLocation | null>(null)
  const [currentFeeling, setCurrentFeeling] = useState<string>('')
  const [draft, setDraft] = useState<DraftPlacement | null>(null)
  const [saving, setSaving] = useState(false)
  // ── THE DRAFT (2026-08-30) ───────────────────────────────────────────────
  // Every template-field edit of this character, waiting for one explicit
  // Save. Keyed by STORE ("profile" / "config" / "imagegen" / "body:<slot>")
  // and merged field by field — see `pendingFields` for the rules. The
  // placement below (`draft`) is the same idea, older and shaped by its three
  // routes; both feed the one Save and the one dirty count.
  const [buf, setBuf] = useState<PendingFields>(emptyFields)
  /** The Discard button's second click (no `window.confirm` in this UI). */
  const [discardArmed, setDiscardArmed] = useState(false)
  /** Bumped by a Discard. The field tab remounts on it, so text a user typed
   *  but never blurred — it never reached the buffer — goes back to the
   *  server's value as well. */
  const [discardSignal, setDiscardSignal] = useState(0)
  /** Bumped by a SUCCESSFUL Save. Panels whose choices are computed by the
   *  server from STORED values — the LoRA suggestions behind the image
   *  overrides are resolved from the saved backend match — reload on it,
   *  because until the Save those choices answered the previous match. */
  const [savedSignal, setSavedSignal] = useState(0)
  /** The character the selection wants to move to while the draft is full.
   *  Answered with real UI, never with window.confirm. */
  const [leaveTo, setLeaveTo] = useState<string | null>(null)
  /** How much is unsaved, readable from an event handler without making every
   *  handler depend on the count (the guards below are registered once). */
  const dirtyRef = useRef(0)
  // Per-character config (chat_mode, behavior toggles, …).
  const [cfg, setCfg] = useState<Record<string, unknown>>({})
  const [savingField, setSavingField] = useState<string>('')
  const [subTab, setSubTab] = useState<string>('general')
  // Aufgelöstes Template des gewählten Characters — Quelle der generischen
  // Feld-Sektionen (Identity/Appearance/Behavior/…).
  const [template, setTemplate] = useState<{ sections?: TmplSectionRaw[]; tabs?: TmplTabRaw[]; features?: Record<string, boolean> } | null>(null)
  const [templateId, setTemplateId] = useState<string>('')
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
  // "New NPC" dialog — same deal; it runs the temporary-NPC pipeline itself.
  const [creatingNpc, setCreatingNpc] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmWipe, setConfirmWipe] = useState(false)
  const [wiping, setWiping] = useState(false)
  const [consolidating, setConsolidating] = useState(false)

  useEffect(() => {
    loadCharacters().then(setCharacters).catch(() => setCharacters([]))
    loadLocations().then(setLocations).catch(() => setLocations([]))
    apiGet<{ voices?: Array<{ value: string; label: string }> }>('/tts/voices')
      .then((d) => setTtsVoices(d.voices || []))
      .catch(() => setTtsVoices([]))
    apiGet<{ speakers?: Array<{ value: string; label: string }> }>('/tts/speakers')
      .then((d) => setTtsSpeakers(d.speakers || []))
      .catch(() => setTtsSpeakers([]))
  }, [])

  // A template can switch the whole activity/home subject off — the same
  // truth the sub-tab gate below uses. Kept here as well because `subTab`
  // survives a character switch: selecting a temporary NPC while the tab was
  // open would otherwise fetch its home/schedule for one commit, before the
  // reset effect moves the selection to an existing tab.
  const homeGateOk = (template?.features || {}).activity_home_enabled !== false

  // Load home location + daily rhythm when the Activity & Home tab opens.
  useEffect(() => {
    if (subTab !== 'home' || !selected || !homeGateOk) return
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
  }, [selected, subTab, homeGateOk, t, toast])

  const reloadCurrent = useCallback(
    async (name: string) => {
      setCurrent(null)
      setCurrentFeeling('')
      setDraft(null)
      setTemplate(null)
      setTemplateId('')
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
        setTemplateId(tmplId)
        if (tmplId) {
          apiGet<{ sections?: TmplSectionRaw[]; tabs?: TmplTabRaw[]; features?: Record<string, boolean> }>(`/templates/${encodeURIComponent(tmplId)}`)
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

  const goTo = useCallback(
    (name: string) => {
      setLeaveTo(null)
      setConfirmDel(false)
      setSelected(name)
      reloadCurrent(name)
    },
    [reloadCurrent],
  )

  /** Open another character — asking first when the sheet still holds a draft.
   *  A character switch never leaves this tab, so the shell's guard
   *  (`lib/unsavedGuard`) never sees it: that question has to be ours.
   *  Selecting the character that is already open is not a navigation. */
  const onSelect = useCallback(
    (name: string) => {
      if (dirtyRef.current > 0 && name !== selected) {
        setLeaveTo(name)
        return
      }
      goTo(name)
    },
    [goTo, selected],
  )

  // Character vollständig löschen (DELETE /characters/{name}). In-App-Bestätigung.
  // Run the full memory consolidation for this character right now (test the
  // per-NPC amount caps without waiting for the 6h background cycle).
  const consolidateNow = useCallback(async () => {
    if (!selected || consolidating) return
    setConsolidating(true)
    try {
      const r = await apiPost<{ removed?: number }>(
        `/characters/${encodeURIComponent(selected)}/memory/consolidate`, {})
      toast(t('Consolidation done: {n} entries removed')
        .replace('{n}', String(r.removed ?? 0)))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setConsolidating(false)
    }
  }, [selected, consolidating, t, toast])

  // Memory wipe (admin test tool for the consolidation pipeline): clears the
  // character's derived memory artifacts — memories, summaries + rollups, the
  // whole day timeline (diary entries, thoughts, mood/state/evolution history,
  // action log) and the day cursor. Chat history + shared scenes stay.
  const wipeMemory = useCallback(async () => {
    if (!selected || wiping) return
    setWiping(true)
    try {
      const r = await apiPost<{ memories?: number; summaries?: number }>(
        `/characters/${encodeURIComponent(selected)}/memory/wipe`, {})
      toast(t('Memory wiped: {m} memories, {s} summaries')
        .replace('{m}', String(r.memories ?? 0))
        .replace('{s}', String(r.summaries ?? 0)))
      setConfirmWipe(false)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setWiping(false)
    }
  }, [selected, wiping, t, toast])

  const deleteCharacter = useCallback(async () => {
    if (!selected || deleting) return
    setDeleting(true)
    try {
      await apiDelete(`/characters/${encodeURIComponent(selected)}`)
      toast(t('Character deleted'))
      setConfirmDel(false)
      setSelected('')
      setCurrent(null)
      setDraft(null)
      setTemplate(null)
      loadCharacters().then(setCharacters).catch(() => {})
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setDeleting(false)
    }
  }, [selected, deleting, t, toast])

  const selectedLocation: LocationRef | undefined = useMemo(
    () => locations.find((l) => l.id === draft?.locationId),
    [locations, draft],
  )

  const rooms: RoomRef[] = selectedLocation?.rooms || []

  // The placement's share of the dirty count, as FIELDS — one per statement
  // the admin made, which is also one per request the Save will send.
  // Location and room count as ONE ("where they are"): they travel in one
  // request, and picking a location always resets the room with it.
  const placementDirty = useMemo(() => {
    if (!current || !draft) return 0
    let n = 0
    if (
      draft.locationId !== (current.current_location_id || '') ||
      (draft.roomId || '') !== (current.current_room || '')
    ) n += 1
    if ((draft.activity || '') !== (current.current_activity || '')) n += 1
    if ((draft.feeling || '') !== (currentFeeling || '')) n += 1
    return n
  }, [current, currentFeeling, draft])

  /** Everything unsaved on this sheet — the number in the Save button. */
  const dirtyCount = pendingFieldCount(buf) + placementDirty
  dirtyRef.current = dirtyCount
  // A Discard that is armed while nothing is left to throw away would fire on
  // the next unrelated click.
  useEffect(() => { if (!dirtyCount) setDiscardArmed(false) }, [dirtyCount])

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

      // The template fields, one request per STORE — not per field. Both
      // stores take many fields at once, which is exactly what a sheet full
      // of edits is; a store nobody touched is not addressed at all.
      const enc = encodeURIComponent(selected)
      const body = toSaveBody(buf)
      const fieldTasks: Promise<unknown>[] = []
      if (body.profile) fieldTasks.push(apiPost(`/characters/${enc}/profile`, { fields: body.profile }))
      if (body.config) fieldTasks.push(apiPost(`/characters/${enc}/config`, { fields: body.config }))
      // The image override is ONE record — its route takes the whole thing,
      // so the patch IS the body. The body slots are one request each.
      if (body.imagegen) fieldTasks.push(apiPut(`/characters/${enc}/outfit-imagegen`, body.imagegen))
      for (const [slotId, values] of Object.entries(body.body || {})) {
        fieldTasks.push(
          apiPost(`/characters/${enc}/body-slots/${encodeURIComponent(slotId)}`, { values }),
        )
      }
      await Promise.all(fieldTasks)

      setBuf(emptyFields())
      setSavedSignal((n) => n + 1)
      toast(t('Saved'))
      // Re-reading is not politeness here: fields flagged `reload_after_save`
      // make the server derive SIBLING keys the form never sent (the
      // temporary-NPC lifetime recomputes `expires_at`). `reloadCurrent`
      // drops the template, so the field tab remounts and refetches
      // profile/config — one reload covers those, the placement view and the
      // now-empty draft alike.
      await reloadCurrent(selected)
    } catch (e) {
      // Nothing here writes partially per field, so the draft stays exactly
      // as it is and Save can simply be pressed again.
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setSaving(false)
    }
  }, [buf, current, currentFeeling, draft, reloadCurrent, selected, t, toast])

  /** Throw the whole draft away — the buffered fields AND the placement — and
   *  take what the server has. Two clicks, no window.confirm. */
  const discard = useCallback(() => {
    setBuf(emptyFields())
    setDiscardArmed(false)
    setDiscardSignal((n) => n + 1)
    if (current) {
      setDraft({
        locationId: current.current_location_id || '',
        roomId: current.current_room || '',
        activity: current.current_activity || '',
        feeling: currentFeeling || '',
      })
    }
  }, [current, currentFeeling])

  // Leaving with a full buffer must not happen silently: the browser's own
  // question for a reload or a closed tab, the shell's for a tab switch (the
  // tab is unmounted then, and the draft would die with it), ours for a
  // switch to another character (see `onSelect`).
  useEffect(() => {
    if (!dirtyCount) return
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      // The browser shows its own generic wording; the value only needs to be
      // non-null for legacy engines.
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirtyCount])
  useEffect(() => {
    setUnsavedGuard(() => dirtyRef.current > 0)
    return () => setUnsavedGuard(null)
  }, [])

  // A character switch (and a deletion) starts a fresh sheet — a draft of the
  // previous one would write its fields onto this character.
  useEffect(() => {
    setBuf(emptyFields())
    setDiscardArmed(false)
  }, [selected])

  /** Remember one template field's new value instead of POSTing it.
   *  `TemplateTab` calls this in place of its immediate save; the fourth
   *  argument (`reload_after_save`) needs no handling here, because `save`
   *  reloads the stores in every case. */
  const queueField = useCallback(
    (scope: 'profile' | 'config', key: string, value: unknown) => {
      setBuf((b) => queueFields(b, scope === 'config' ? CONFIG_TARGET : PROFILE_TARGET, { [key]: value }))
    },
    [],
  )

  /** The draft as the field tab reads it — laid OVER the server's values so a
   *  refetch beside it cannot eat unsaved work. */
  const templateDraft = useMemo(
    () => ({ profile: targetPatch(buf, PROFILE_TARGET), config: targetPatch(buf, CONFIG_TARGET) }),
    [buf],
  )

  /** Remember the image-override record instead of PUTting it. Its route
   *  stores the record AS A WHOLE, so `ImageOverrides` hands over all four of
   *  its keys on every edit and this only merges them under the one target. */
  const queueImagegen = useCallback((patch: Record<string, unknown>) => {
    setBuf((b) => queueFields(b, IMAGEGEN_TARGET, patch))
  }, [])

  /** Remember one body slot's attributes instead of POSTing them. Each slot
   *  is its own request at Save time, hence its own target. */
  const queueBody = useCallback((slotId: string, patch: Record<string, unknown>) => {
    setBuf((b) => queueFields(b, bodyTarget(slotId), patch))
  }, [])

  /** The image-override draft as its panel reads it — laid OVER what the GET
   *  returned, so re-opening the sub-tab shows the unsaved edits. */
  const imagegenDraft = useMemo(() => targetPatch(buf, IMAGEGEN_TARGET), [buf])

  /** The same for one body slot. A function rather than a map, because only
   *  the slot editor knows which slots the species package declares. */
  const bodyDraftFor = useCallback(
    (slotId: string) => targetPatch(buf, bodyTarget(slotId)),
    [buf],
  )

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
  // Template features are the truth about what a character KIND has —
  // npc-temporary switches memory/thoughts/telegram/… off. A section whose
  // `visible_when.feature` names a disabled feature is dropped here, ONCE,
  // before tabs and forms ever see it; a tab left without sections vanishes.
  // A temporary NPC is a different KIND of character sheet, not a stripped
  // one — a few surfaces read differently for it (see the Expressions gate).
  const isTempNpc = ((template?.features || {}) as Record<string, boolean>).temporary_npc === true

  const visibleSections = useMemo(() => {
    const features = (template?.features || {}) as Record<string, boolean>
    return (template?.sections || []).filter((s) => {
      const f = (s.visible_when as { feature?: string } | undefined)?.feature
      return !f || features[f] !== false
    })
  }, [template])

  const fieldTabs = useMemo(() => {
    const tabs = template?.tabs || []
    return tabs
      .filter((tb) => !tb.special && Array.isArray(tb.columns) && tb.columns.length > 0)
      .filter((tb) =>
        visibleSections.some((s) => sectionIsRenderable(s) && (tb.columns || []).includes(s.column || 1)),
      )
      .map((tb) => ({ id: `tab:${tb.id}`, label: tmplText(tb, 'label', lang) || tb.id, tab: tb }))
  }, [template, visibleSections, lang])

  // Reihenfolge: Feld-Tabs (General/Aussehen), dann direkt Image · Wardrobe ·
  // Secrets, dann die restlichen Feld-Tabs (Configuration) und Spezial-Tabs.
  // Wunsch: Bild hinter Aussehen, Garderobe+Secrets zwischen Bild und Config.
  const subTabs = useMemo(() => {
    // Special tabs whose whole subject a template can switch off — same
    // truth as the section gates above. No entry = always visible.
    const specialGate: Record<string, string> = {
      soul: 'soul_enabled',
      wardrobe: 'outfit_system_enabled',
      secrets: 'secrets_enabled',
      expressions: 'expression_variants_enabled',
      home: 'activity_home_enabled',
    }
    const features = (template?.features || {}) as Record<string, boolean>
    const gateOk = (id: string) => {
      // The ONE exception: a temporary NPC has `expression_variants_enabled`
      // false — no moods, no poses, no grid — and yet exactly ONE variant,
      // the default one the 2D client shows it by (npc_assets' fourth finish
      // criterion). Hiding the tab hid the only picture the NPC has, with no
      // way to look at it or ask for it again, so the tab stays — read-only.
      if (id === 'expressions' && isTempNpc) return true
      const f = specialGate[id]
      return !f || features[f] !== false
    }
    const afterAussehen = [
      { id: 'image', label: 'Image' },
      { id: 'wardrobe', label: 'Wardrobe' },
      { id: 'secrets', label: 'Secrets' },
    ].filter((s) => gateOk(s.id))
    const placed = new Set(['image', 'wardrobe', 'secrets'])
    const out: Array<{ id: string; label: string }> = []
    let inserted = false
    for (const ft of fieldTabs) {
      out.push({ id: ft.id, label: ft.label })
      if (ft.tab.id === 'aussehen') {
        out.push(...afterAussehen)
        inserted = true
      }
    }
    if (!inserted) out.push(...afterAussehen)
    out.push(...SPECIAL_TABS.filter((s) => !placed.has(s.id) && gateOk(s.id)))
    return out
  }, [fieldTabs, template, isTempNpc])

  // Den gewählten Reiter beim Character-Wechsel BEHALTEN. Nur dann auf den
  // ersten Feld-Tab springen, wenn der aktuelle Reiter für diesen Character
  // gar nicht existiert (z.B. Erst-Laden mit Default 'general', oder das neue
  // Template hat diesen Tab nicht).
  useEffect(() => {
    if (fieldTabs.length && !subTabs.some((s) => s.id === subTab)) {
      setSubTab(fieldTabs[0].id)
    }
  }, [subTabs, subTab, fieldTabs])

  // Animation sets: the base sets (female/male/animal — they follow from
  // gender + the humanoid feature) plus every set found in the clips. The
  // endpoint returns both merged, so the vocabulary stays open.
  const [animationSets, setAnimationSets] = useState<Array<{ value: string; label: string }>>([])
  useEffect(() => {
    apiGet<{ sets?: string[] }>('/assets/animation-clips')
      .then((d) => setAnimationSets((d.sets || []).map((s) => ({ value: s, label: s }))))
      .catch(() => setAnimationSets([]))
  }, [])

  // "Not set" is not "no set": the character still DERIVES one from its gender
  // and the humanoid feature. Show which — a blank field otherwise looks like
  // the figure animates neutrally when it does not.
  const [derivedSet, setDerivedSet] = useState('')
  useEffect(() => {
    if (!selected) {
      setDerivedSet('')
      return
    }
    let cancelled = false
    apiGet<{ animation_set_derived?: string }>(
      `/characters/${encodeURIComponent(selected)}/model3d`)
      .then((d) => { if (!cancelled) setDerivedSet(d.animation_set_derived || '') })
      .catch(() => { if (!cancelled) setDerivedSet('') })
    return () => { cancelled = true }
  }, [selected])

  // The empty option carries the derivation, so it belongs to the options, not
  // to the generic select's built-in placeholder.
  const animationSetOptions = useMemo(
    () => [
      { value: '', label: `${t('Automatic')} (${derivedSet || t('neutral')})` },
      ...animationSets,
    ],
    [animationSets, derivedSet, t],
  )

  // Dynamic option sources for the template selects.
  const dynamicData: DynamicData = useMemo(
    () => ({
      tts_voices: ttsVoices,
      tts_speakers: ttsSpeakers,
      characters: sortedCharacters.map((c) => ({ value: c.name, label: c.display_name || c.name })),
      animation_sets: animationSetOptions,
    }),
    [ttsVoices, ttsSpeakers, sortedCharacters, animationSetOptions],
  )

  // Editable "current state" placement — rendered as a special slot
  // (section.special === "placement") in column 3 of the General tab.
  const placementUI =
    current && draft ? (
      <PlacementEditor
        current={current}
        draft={draft}
        setDraft={setDraft}
        currentFeeling={currentFeeling}
        locations={locations}
        rooms={rooms}
      />
    ) : null

  return (
    <div className="ga-twocol">
      <CharacterListPanel
        characters={sortedCharacters}
        selected={selected}
        onSelect={onSelect}
        onNew={() => setCreating(true)}
        onNewNpc={() => setCreatingNpc(true)}
        onImported={() => {
          loadCharacters().then(setCharacters).catch(() => {})
        }}
      />
      <section className="ga-twocol-right">
        {!selected ? (
          <div className="ga-placeholder">{t('Pick a character to edit their settings.')}</div>
        ) : !current || !draft ? (
          <div className="ga-loading">{t('Loading…')}</div>
        ) : (
          <>
            <DetailToolbar
              title={selected}
              // THE DRAFT. Save exists only while there IS one — a permanently
              // greyed-out button teaches nothing about when it would do
              // something — and its number is the only place the size of the
              // unsaved work is visible. `disabled` gates the bar while the
              // requests are in flight.
              onSave={dirtyCount > 0 ? () => { void save() } : undefined}
              saveLabel={saving
                ? t('Saving…')
                : t('Save ({n})').replace('{n}', String(dirtyCount))}
              disabled={saving}
              extra={
                <>
                  {dirtyCount > 0 ? (
                    <>
                      <button type="button"
                        className={'ga-btn ga-btn-sm' + (discardArmed ? ' ga-btn-danger' : '')}
                        disabled={saving}
                        title={t('Throw the unsaved field changes away and take what the server has')}
                        onClick={() => {
                          if (discardArmed) discard()
                          else setDiscardArmed(true)
                        }}>
                        {discardArmed
                          ? t('Really discard {n}').replace('{n}', String(dirtyCount))
                          : t('Discard')}
                      </button>
                      {discardArmed ? (
                        <button type="button" className="ga-btn ga-btn-sm"
                          onClick={() => setDiscardArmed(false)}>
                          {t('Cancel')}
                        </button>
                      ) : null}
                    </>
                  ) : null}
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
                  <button
                    className="ga-btn ga-btn-sm"
                    disabled={consolidating}
                    title={t('Run the 5-phase memory consolidation for this character now (cleanup, caps, daily/weekly/monthly rollup) — normally runs every 6h in the background.')}
                    onClick={() => { void consolidateNow() }}
                  >
                    {consolidating ? t('Consolidating…') : `♻ ${t('Consolidate now')}`}
                  </button>
                  {confirmWipe ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: '0.82em', color: '#e0a356' }}>
                        {t('Wipe ALL memory of {name}? Memories, summaries, rollups and the whole day timeline (diary, thoughts, mood/state history) — chat history stays. Irreversible.').replace('{name}', selected)}
                      </span>
                      <button className="ga-btn ga-btn-sm ga-btn-danger" disabled={wiping} onClick={() => { void wipeMemory() }}>
                        {wiping ? t('Wiping…') : t('Wipe')}
                      </button>
                      <button className="ga-btn ga-btn-sm" disabled={wiping} onClick={() => setConfirmWipe(false)}>
                        {t('Cancel')}
                      </button>
                    </span>
                  ) : (
                    <button
                      className="ga-btn ga-btn-sm"
                      title={t('Delete all derived memory: memories, summaries + weekly/season rollups, and the entire day timeline — diary entries, thoughts, mood/state/evolution history, action log, day cursor. Chat history and shared scenes stay. Test tool for the consolidation pipeline.')}
                      onClick={() => setConfirmWipe(true)}
                    >
                      🧹 {t('Wipe memory')}
                    </button>
                  )}
                  {confirmDel ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: '0.82em', color: '#e0a356' }}>
                        {t('Delete {name}? DB, images, memories — irreversible.').replace('{name}', selected)}
                      </span>
                      <button className="ga-btn ga-btn-sm ga-btn-danger" disabled={deleting} onClick={deleteCharacter}>
                        {deleting ? t('Deleting…') : t('Delete')}
                      </button>
                      <button className="ga-btn ga-btn-sm" disabled={deleting} onClick={() => setConfirmDel(false)}>
                        {t('Cancel')}
                      </button>
                    </span>
                  ) : (
                    <button className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => setConfirmDel(true)}>
                      {t('Delete character')}
                    </button>
                  )}
                </>
              }
            />
            <TemplateSelector
              character={selected}
              templateId={templateId}
              onSwitched={() => reloadCurrent(selected)}
              locked={(template?.features || {}).temporary_npc === true}
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
                    sections={visibleSections}
                    dynamicData={dynamicData}
                    // With these three the field tab stops writing through on
                    // blur and collects into the toolbar's draft instead.
                    queueField={queueField}
                    draft={templateDraft}
                    discardSignal={discardSignal}
                    specialSlots={{
                      placement: placementUI,
                      body_editor: (
                        <BodyEditor
                          character={selected}
                          queueBody={queueBody}
                          draftFor={bodyDraftFor}
                          discardSignal={discardSignal}
                        />
                      ),
                      model_refs: <FieldModelRefs character={selected} kinds={['tpose']} />,
                      model3d_gen: <FieldModel3D character={selected} />,
                    }}
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
              <ActivityHomeTab
                selected={selected}
                locations={locations}
                homeLoc={homeLoc}
                savingField={savingField}
                saveHome={saveHome}
                schedule={schedule}
                cfg={cfg}
                homeLoading={homeLoading}
              />
            ) : subTab === 'locations' ? (
              <KnownLocationsEditor character={selected} />
            ) : subTab === 'image' ? (
              <ImageOverrides
                character={selected}
                queueImagegen={queueImagegen}
                draft={imagegenDraft}
                discardSignal={discardSignal}
                savedSignal={savedSignal}
              />
            ) : subTab === 'gallery' ? (
              <GalleryTab character={selected} />
            ) : subTab === 'expressions' ? (
              <ExpressionsTab character={selected} readOnly={isTempNpc} />
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
        {/* The character-switch guard. The same question the shell asks
            before a tab switch, asked here because a character switch stays
            inside the tab — and asked as UI, never as window.confirm. */}
        {leaveTo !== null ? (
          <div className="ga-modal-backdrop" role="presentation">
            <div className="ga-modal" role="dialog" aria-modal="true"
              aria-label={t('Unsaved changes')} style={{ maxWidth: 460 }}>
              <div className="ga-modal-header">
                <h3>{t('Unsaved changes')}</h3>
              </div>
              <div className="ga-modal-body">
                {t('This character holds {n} field changes that were never saved. Opening another character discards them.')
                  .replace('{n}', String(dirtyCount))}
              </div>
              <div className="ga-modal-footer">
                <button className="ga-btn" onClick={() => setLeaveTo(null)}>
                  {t('Stay')}
                </button>
                <button className="ga-btn ga-btn-danger"
                  onClick={() => goTo(leaveTo)}>
                  {t('Leave and discard')}
                </button>
              </div>
            </div>
          </div>
        ) : null}
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
      {creatingNpc && (
        <NewNpcDialog
          locations={locations}
          defaultLocationId={draft?.locationId || ''}
          onClose={() => setCreatingNpc(false)}
          onCreated={(name) => {
            setCreatingNpc(false)
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
