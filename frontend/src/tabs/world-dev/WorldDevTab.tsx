import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ModelPicker, type PickerOption } from '../../components/ModelPicker'
import { loadCharacters, loadLocations, type CharacterRef, type LocationRef } from '../../lib/refs'
import { usePersistentState } from '../../lib/usePersistentState'
import {
  MapDraftPreview,
  type MapDraftCounts, type MapDraftWarning, type MapPreviewResponse,
} from './MapDraftPreview'
import {
  LayoutDraftPreview,
  type LayoutDraftCounts, type LayoutDraftWarning, type LayoutPreviewResponse,
} from './LayoutDraftPreview'

interface ModelEntry {
  name: string
  provider?: string
  /** Per 1M tokens, in USD. Local / unpriced models leave these at 0. */
  pricing?: { input?: number; output?: number }
}

interface UsageStats {
  tokens_in: number
  tokens_out: number
  cost_total: number
}

function formatUsd(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '$0.00'
  if (value < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}

interface SchemaInfo {
  name: string
  label: string
}

type Mode = 'new' | 'edit'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface ExtractedData {
  location_data?: Record<string, unknown>
  character_data?: Record<string, unknown>
  outfit_data?: Record<string, unknown>
  soul_data?: Record<string, unknown>
  profile_patch_data?: Record<string, unknown>
}

interface TemplateInfo {
  name: string
  label: string
}

/**
 * The map schema is the one type that is not applied through a per-type
 * `/apply-*` route: a map draft is a whole LAYOUT, so it gets its own
 * preview → apply → restore triple (`plan-freie-weltkarte-e10-…`, § 2.3) and
 * its own inline picture (`MapDraftPreview`) instead of an Apply button next
 * to the extracted JSON.
 *
 * `mode` is shared with the other schemas on purpose. It carries the same two
 * values there (`new` / `edit`) and means the same thing — start from nothing
 * or start from what exists — only the target differs: a location/character
 * picks ONE record via `edit_location_id`, a map has exactly one map, so the
 * server injects the existing one and no target select appears.
 */
const MAP_SCHEMA = 'map'

/**
 * The layout schema is the map's sibling one level down: a whole FLOOR PLAN
 * for ONE location, so it gets the same preview → apply → restore triple
 * instead of a generic Apply button, and its own inline picture
 * (`LayoutDraftPreview`).
 *
 * It differs from the map in exactly one thing: a plan always belongs to a
 * location, so the target select is shown in BOTH modes — there is no such
 * thing as "a floor plan of nothing". `mode` still means what it means
 * everywhere (`new` = plan the place from scratch, `edit` = keep what is
 * drawn), and the server injects the current plan either way, because a plan
 * is always written as a whole.
 */
const LAYOUT_SCHEMA = 'layout'

interface ApplyLayoutResponse {
  status?: string
  applied?: {
    location_id?: string
    updated?: string[]
    created?: string[]
    entry_room?: string
    boundary_openings?: number
  }
  warnings?: LayoutDraftWarning[]
  snapshot_id?: string
}

/** One entry of `GET /world-dev/layout-snapshots` — the undo the floor-plan
 *  editor itself does not have. */
interface LayoutSnapshot {
  id: string
  created_at?: string
  location_id?: string
  location_name?: string
  rooms?: number
}

/** How a map draft is written into the world. `merge` adds its areas next to
 *  what is there; `replace_terrain` clears the painted ground AND the relief
 *  first (placements are never cleared — only the listed ones move). */
type ApplyMode = 'merge' | 'replace_terrain'

interface ApplyMapResponse {
  status?: string
  applied?: MapDraftCounts
  warnings?: MapDraftWarning[]
  snapshot_id?: string
}

/** `POST /world-dev/map-restore`. `removed` are the places the apply after
 *  that snapshot CREATED and the restore deleted again. */
interface MapRestoreCounts extends MapDraftCounts {
  removed?: number
}

/** One entry of `GET /world-dev/map-snapshots` — the undo the map editor
 *  itself does not have. Its `created` count is what a restore would REMOVE:
 *  the places the apply after it brought into being. */
interface MapSnapshot {
  id: string
  created_at?: string
  counts?: Partial<MapDraftCounts>
}

/** What a confirmation modal is about. `null` = no modal. */
type MapAction =
  | { kind: 'apply'; mode: ApplyMode }
  | { kind: 'restore'; snapshotId: string }
type LayoutAction =
  | { kind: 'apply-layout' }
  | { kind: 'restore-layout'; snapshotId: string }
type PendingAction = MapAction | LayoutAction

export function WorldDevTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [models, setModels] = useState<ModelEntry[]>([])
  // Flat, provider-grouped options with a price sublabel — fed to the
  // searchable ModelPicker (both the chat model and the validator model).
  const modelOptions: PickerOption[] = useMemo(() => {
    const fmt = (v: number) =>
      v >= 1 ? v.toFixed(2) : v.toFixed(2).replace(/\.?0+$/, '') || v.toFixed(2)
    return [...models]
      .sort((a, b) => (a.provider || '').localeCompare(b.provider || '')
        || a.name.localeCompare(b.name))
      .map((m) => {
        const inP = m.pricing?.input || 0
        const outP = m.pricing?.output || 0
        const sub = (inP > 0 || outP > 0) ? `$${fmt(inP)} / $${fmt(outP)} per 1M` : ''
        return { value: `${m.provider || ''}|${m.name}`, label: m.name,
                 group: m.provider || '', sublabel: sub }
      })
  }, [models])
  const [schemas, setSchemas] = useState<SchemaInfo[]>([])
  const [templates, setTemplates] = useState<TemplateInfo[]>([])
  const [characters, setCharacters] = useState<CharacterRef[]>([])
  const [locations, setLocations] = useState<LocationRef[]>([])
  // Session-critical state is sessionStorage-backed so the whole World Dev
  // session (chat, generated data, config picks) survives a Game-Admin tab
  // switch — which unmounts this component — and a page reload.
  const [model, setModel] = usePersistentState('worlddev.model', '')
  const [provider, setProvider] = usePersistentState('worlddev.provider', '')
  // Separate model picker for the JSON validator. Defaults to the chat
  // model when empty so users get a sane fallback without a second pick;
  // can be set to a smaller / cheaper model independently.
  // Completion budget for the chat model. Empty = built-in default (32768,
  // grey placeholder, never materialized); explicit 0 = send NO max_tokens.
  const [maxTokens, setMaxTokens] = usePersistentState('worlddev.maxTokens', '')
  const [validateModel, setValidateModel] = usePersistentState('worlddev.validateModel', '')
  const [validateProvider, setValidateProvider] = usePersistentState('worlddev.validateProvider', '')
  const [schema, setSchema] = usePersistentState<string>('worlddev.schema', 'location')
  const [mode, setMode] = usePersistentState<Mode>('worlddev.mode', 'new')
  const [template, setTemplate] = usePersistentState<string>('worlddev.template', 'human-roleplay')
  const [editTarget, setEditTarget] = usePersistentState('worlddev.editTarget', '')
  const [contextLocations, setContextLocations] = usePersistentState<Set<string>>('worlddev.contextLocations', new Set())
  const [contextCharacters, setContextCharacters] = usePersistentState<Set<string>>('worlddev.contextCharacters', new Set())

  const [sessionId, setSessionId] = usePersistentState('worlddev.sessionId', '')
  const [messages, setMessages] = usePersistentState<ChatMessage[]>('worlddev.messages', [])
  const [streaming, setStreaming] = useState(false)
  const [pending, setPending] = useState('')
  const [extracted, setExtracted] = usePersistentState<ExtractedData>('worlddev.extracted', {})
  const [draft, setDraft] = usePersistentState('worlddev.draft', '')
  const [usage, setUsage] = usePersistentState<UsageStats | null>('worlddev.usage', null)

  // The map draft lives next to `extracted`, not inside it: it is applied
  // through its own route with its own confirmation, so a generic
  // "Apply map_data" button would write a whole world layout on one click.
  const [mapDraft, setMapDraft] = usePersistentState<Record<string, unknown> | null>(
    'worlddev.mapDraft', null)
  const [preview, setPreview] = useState<MapPreviewResponse | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [snapshots, setSnapshots] = useState<MapSnapshot[]>([])
  const [snapshotId, setSnapshotId] = useState('')
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [applying, setApplying] = useState(false)
  const [applied, setApplied] = useState(false)

  // The layout draft lives next to `extracted` for the same reason the map
  // draft does: it is applied through its own route, with its own
  // confirmation and its own undo.
  const [layoutDraft, setLayoutDraft] = usePersistentState<Record<string, unknown> | null>(
    'worlddev.layoutDraft', null)
  const [layoutPreview, setLayoutPreview] = useState<LayoutPreviewResponse | null>(null)
  const [layoutPreviewing, setLayoutPreviewing] = useState(false)
  const [layoutPreviewError, setLayoutPreviewError] = useState('')
  const [layoutSnapshots, setLayoutSnapshots] = useState<LayoutSnapshot[]>([])
  const [layoutSnapshotId, setLayoutSnapshotId] = useState('')

  const chatScrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    apiGet<{ providers?: Record<string, { models?: ModelEntry[] }> }>('/characters/available-models')
      .then((d) => {
        const flat: ModelEntry[] = []
        for (const [provName, prov] of Object.entries(d.providers || {})) {
          for (const m of prov.models || []) {
            // Carry pricing through — provider-flat list dropped it before
            // and that's why the dropdown never showed $-prices.
            flat.push({ name: m.name, provider: provName, pricing: m.pricing })
          }
        }
        setModels(flat)
      })
      .catch(() => setModels([]))
    apiGet<{ schemas?: SchemaInfo[] }>('/world-dev/schemas')
      .then((d) => setSchemas(d.schemas || []))
      .catch(() => setSchemas([]))
    apiGet<{ templates?: Array<{ name: string; label?: string }> }>('/world-dev/character-templates')
      .then((d) => {
        const list = (d.templates || []).map((t) => ({ name: t.name, label: t.label || t.name }))
        setTemplates(list)
        // Switch the default template if the previous hard-coded one is
        // no longer in the list (e.g. project removed `human-roleplay`).
        if (list.length && !list.find((t) => t.name === template)) {
          setTemplate(list[0].name)
        }
      })
      .catch(() => setTemplates([]))
    loadCharacters().then(setCharacters).catch(() => setCharacters([]))
    loadLocations().then(setLocations).catch(() => setLocations([]))
  }, [])

  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight
    }
  }, [messages, pending])

  const newSession = useCallback(() => {
    setSessionId('')
    setMessages([])
    setPending('')
    setExtracted({})
    setDraft('')
    setUsage(null)
    setMapDraft(null)
    setPreview(null)
    setPreviewError('')
    setLayoutDraft(null)
    setLayoutPreview(null)
    setLayoutPreviewError('')
    setApplied(false)
  }, [])

  const send = useCallback(async () => {
    if (!model) {
      toast(t('Pick a model first'), 'error')
      return
    }
    if (!draft.trim()) return
    if (streaming) return

    const userMsg = draft.trim()
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }])
    setDraft('')
    setPending('')
    setStreaming(true)
    setExtracted({})

    try {
      const res = await fetch('/world-dev/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          model,
          provider,
          session_id: sessionId,
          max_tokens: maxTokens.trim() ? parseInt(maxTokens, 10) : undefined,
          message: userMsg,
          schema,
          character_template: schema === 'character' ? template : '',
          // The map has exactly one instance, so it takes the mode itself
          // ("new" = draw from scratch, "edit" = the server injects the
          // existing map) and never an edit target.
          mode: schema === MAP_SCHEMA ? mode : undefined,
          // A floor plan always belongs to a location, so the layout schema
          // carries its target in BOTH modes.
          edit_location_id: schema === LAYOUT_SCHEMA
            ? editTarget
            : (mode === 'edit' && schema !== MAP_SCHEMA ? editTarget : ''),
          context_location_ids: Array.from(contextLocations),
          context_character_names: Array.from(contextCharacters),
        }),
      })
      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => '')
        toast(t('Chat failed') + ': ' + (text || `HTTP ${res.status}`), 'error')
        setStreaming(false)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let acc = ''
      const localExtracted: ExtractedData = {}
      let localMap: Record<string, unknown> | null = null
      let localLayout: Record<string, unknown> | null = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const chunk = buffer.slice(0, idx).trim()
          buffer = buffer.slice(idx + 2)
          if (!chunk.startsWith('data:')) continue
          const json = chunk.slice(5).trim()
          if (!json) continue
          try {
            const evt = JSON.parse(json)
            if (evt.session_id) setSessionId(evt.session_id)
            if (evt.content) {
              acc += evt.content
              setPending(acc)
            }
            if (evt.extraction_warning) {
              // Truncated/unparseable json:<type> block — surface WHY there
              // are no Validate/Apply buttons (visible in the chat + toast).
              acc += `\n\n⚠ *${String(evt.extraction_warning)}*`
              setPending(acc)
              toast(String(evt.extraction_warning), 'error')
            }
            if (evt.usage && typeof evt.usage === 'object') {
              setUsage({
                tokens_in: Number(evt.usage.tokens_in) || 0,
                tokens_out: Number(evt.usage.tokens_out) || 0,
                cost_total: Number(evt.usage.cost_total) || 0,
              })
            }
            for (const k of [
              'location_data',
              'character_data',
              'outfit_data',
              'soul_data',
              'profile_patch_data',
            ] as const) {
              if (evt[k]) localExtracted[k] = evt[k]
            }
            // The map block arrives like every other extracted type, but is
            // kept out of `extracted` — it has its own preview and its own
            // apply (see MAP_SCHEMA).
            if (evt.map_data && typeof evt.map_data === 'object') {
              localMap = evt.map_data as Record<string, unknown>
            }
            // Same treatment for the floor plan (see LAYOUT_SCHEMA).
            if (evt.layout_data && typeof evt.layout_data === 'object') {
              localLayout = evt.layout_data as Record<string, unknown>
            }
          } catch {
            /* drop malformed chunks */
          }
        }
      }

      setMessages((prev) => [...prev, { role: 'assistant', content: acc }])
      setPending('')
      setExtracted(localExtracted)
      if (localMap) {
        // A new draft supersedes the previous one — and the "applied" state
        // with it, so the map-editor link never points at an older result.
        setMapDraft(localMap)
        setApplied(false)
      }
      if (localLayout) {
        setLayoutDraft(localLayout)
        setApplied(false)
      }
    } catch (e) {
      toast(t('Chat failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setStreaming(false)
    }
  }, [contextCharacters, contextLocations, draft, editTarget, maxTokens, mode, model, provider, schema, sessionId, streaming, t, template, toast])

  const apply = useCallback(
    async (kind: keyof ExtractedData) => {
      const data = extracted[kind]
      if (!data) return
      // Each apply endpoint expects a different body shape:
      //   /apply          → { location_data: {...} }
      //   /apply-character→ { character_data: {...} }
      //   /apply-outfit   → flat: { character_name, outfit }
      //   /apply-soul     → flat: { character_name, section, content }
      //   /apply-profile-patch → flat: { character_name, fields }
      let path = ''
      let body: Record<string, unknown> = { session_id: sessionId }
      switch (kind) {
        case 'location_data':
          path = '/world-dev/apply'
          body = { ...body, location_data: data }
          break
        case 'character_data':
          path = '/world-dev/apply-character'
          body = { ...body, character_data: data }
          break
        case 'outfit_data':
          path = '/world-dev/apply-outfit'
          body = { ...body, ...(data as object) }
          break
        case 'soul_data':
          path = '/world-dev/apply-soul'
          body = { ...body, ...(data as object) }
          break
        case 'profile_patch_data':
          path = '/world-dev/apply-profile-patch'
          body = { ...body, ...(data as object) }
          break
      }
      try {
        await apiPost(path, body)
        toast(t('Applied'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [extracted, sessionId, t, toast],
  )

  // Validate the most recent extracted JSON via a tool LLM. Result is
  // a plain-text bullet list of missing/incomplete fields, dropped into
  // the chat input so the user can hit Send to ask the RP LLM to fill
  // them in.
  const [validating, setValidating] = useState(false)
  const validate = useCallback(async () => {
    // Pick whichever extracted block is most informative — character or
    // location are the typical cases for a "fill the gaps" prompt.
    const data =
      extracted.character_data ||
      extracted.location_data ||
      extracted.outfit_data ||
      extracted.soul_data ||
      extracted.profile_patch_data
    if (!data) return
    const detected =
      extracted.character_data ? 'character'
      : extracted.location_data ? 'location'
      : schema
    // Use the explicit validator model if the user picked one, otherwise
    // fall back to the chat model so the feature works out of the box.
    const vModel = validateModel || model
    const vProvider = validateModel ? validateProvider : provider
    if (!vModel) {
      toast(t('Pick a model first'), 'error')
      return
    }
    setValidating(true)
    try {
      const res = await apiPost<{ gaps?: string }>('/world-dev/validate-json', {
        schema: detected,
        data,
        model: vModel,
        provider: vProvider,
      })
      const gaps = (res.gaps || '').trim()
      if (!gaps || gaps === 'OK') {
        toast(t('Validation: no gaps detected'))
        return
      }
      const prompt =
        t('Please complete the following missing or incomplete fields:') + '\n\n' + gaps
      // Append to existing draft so user keeps any in-flight text.
      setDraft((prev) => (prev ? `${prev.trim()}\n\n${prompt}` : prompt))
      toast(t('Gaps written into the input'))
    } catch (e) {
      toast(t('Validation failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setValidating(false)
    }
  }, [extracted, schema, model, provider, validateModel, validateProvider, t, toast])

  /* ------------------------------------------------------------- map draft */

  const isMap = schema === MAP_SCHEMA

  // Every new draft is normalised by the SERVER before it is drawn: line
  // recipes widened, unknown kinds dropped, coordinates clamped, warnings
  // collected. The picture must show what an apply would write, so the
  // preview never renders the raw model JSON.
  useEffect(() => {
    if (!mapDraft) { setPreview(null); setPreviewError(''); return }
    let cancelled = false
    setPreviewing(true)
    setPreviewError('')
    apiPost<MapPreviewResponse>('/world-dev/preview-map', { map_data: mapDraft })
      .then((res) => {
        if (cancelled) return
        setPreview(res)
      })
      .catch((e: Error) => {
        if (cancelled) return
        setPreview(null)
        setPreviewError(e.message)
      })
      .finally(() => { if (!cancelled) setPreviewing(false) })
    return () => { cancelled = true }
  }, [mapDraft])

  const loadSnapshots = useCallback(async () => {
    try {
      const list = await apiGet<MapSnapshot[]>('/world-dev/map-snapshots')
      setSnapshots(Array.isArray(list) ? list : [])
    } catch {
      // A world that never applied a map has no snapshot store yet — an empty
      // list is the honest answer, not an error the user can act on.
      setSnapshots([])
    }
  }, [])

  // The snapshot list is read only while the map schema is selected: it is a
  // per-world store that nothing else in this tab touches.
  useEffect(() => { if (isMap) void loadSnapshots() }, [isMap, loadSnapshots])

  const runApply = useCallback(async (applyMode: ApplyMode) => {
    if (!mapDraft) return
    setApplying(true)
    try {
      const res = await apiPost<ApplyMapResponse>('/world-dev/apply-map', {
        map_data: mapDraft,
        mode: applyMode,
        snapshot: true,
      })
      const a = res.applied
      toast(a
        ? t('Applied {a} areas, {h} height areas, {p} positions')
          .replace('{a}', String(a.areas ?? 0))
          .replace('{h}', String(a.heights ?? 0))
          .replace('{p}', String(a.positions ?? 0))
          + (a.created
            ? ', ' + t('{n} new places').replace('{n}', String(a.created))
            : '')
        : t('Applied'), 'success')
      setApplied(true)
      await loadSnapshots()
      if (res.snapshot_id) setSnapshotId(res.snapshot_id)
    } catch (e) {
      toast(t('Apply failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setApplying(false)
    }
  }, [loadSnapshots, mapDraft, t, toast])

  const runRestore = useCallback(async (id: string) => {
    if (!id) return
    setApplying(true)
    try {
      const res = await apiPost<{ restored?: MapRestoreCounts }>(
        '/world-dev/map-restore', { snapshot_id: id })
      const r = res.restored
      toast(r
        ? t('Restored {a} areas, {h} height areas, {p} positions')
          .replace('{a}', String(r.areas ?? 0))
          .replace('{h}', String(r.heights ?? 0))
          .replace('{p}', String(r.positions ?? 0))
          + (r.removed
            ? ', ' + t('{n} new places removed').replace('{n}',
              String(r.removed))
            : '')
        : t('Snapshot restored'), 'success')
      setApplied(true)
    } catch (e) {
      toast(t('Restore failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setApplying(false)
    }
  }, [t, toast])

  /** The map editor is a tab of this very SPA — switching means setting the
   *  hash the shell listens on (`App.readHashTab`), not a page load. */
  const openMapEditor = useCallback(() => {
    window.location.hash = '#/map'
  }, [])

  /* ---------------------------------------------------------- layout draft */

  const isLayout = schema === LAYOUT_SCHEMA

  // Same rule as the map: the SERVER normalises before anything is drawn, so
  // the picture shows what an apply would write and never the raw model JSON.
  useEffect(() => {
    if (!layoutDraft || !editTarget) {
      setLayoutPreview(null); setLayoutPreviewError(''); return
    }
    let cancelled = false
    setLayoutPreviewing(true)
    setLayoutPreviewError('')
    apiPost<LayoutPreviewResponse>('/world-dev/preview-layout', {
      layout_data: layoutDraft, location_id: editTarget,
    })
      .then((res) => { if (!cancelled) setLayoutPreview(res) })
      .catch((e: Error) => {
        if (cancelled) return
        setLayoutPreview(null)
        setLayoutPreviewError(e.message)
      })
      .finally(() => { if (!cancelled) setLayoutPreviewing(false) })
    return () => { cancelled = true }
  }, [layoutDraft, editTarget])

  const loadLayoutSnapshots = useCallback(async (locId: string) => {
    if (!locId) { setLayoutSnapshots([]); return }
    try {
      const list = await apiGet<LayoutSnapshot[]>(
        `/world-dev/layout-snapshots?location_id=${encodeURIComponent(locId)}`)
      setLayoutSnapshots(Array.isArray(list) ? list : [])
    } catch {
      // A location that never had a plan applied has no snapshot store yet —
      // an empty list is the honest answer, not an error to act on.
      setLayoutSnapshots([])
    }
  }, [])

  useEffect(() => {
    if (isLayout) void loadLayoutSnapshots(editTarget)
  }, [isLayout, editTarget, loadLayoutSnapshots])

  const runApplyLayout = useCallback(async () => {
    if (!layoutDraft || !editTarget) return
    setApplying(true)
    try {
      const res = await apiPost<ApplyLayoutResponse>('/world-dev/apply-layout', {
        layout_data: layoutDraft,
        location_id: editTarget,
        snapshot: true,
      })
      const a = res.applied
      toast(a
        ? t('Applied: {u} rooms updated, {c} created')
          .replace('{u}', String(a.updated?.length ?? 0))
          .replace('{c}', String(a.created?.length ?? 0))
        : t('Applied'), 'success')
      setApplied(true)
      await loadLayoutSnapshots(editTarget)
      if (res.snapshot_id) setLayoutSnapshotId(res.snapshot_id)
    } catch (e) {
      toast(t('Apply failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setApplying(false)
    }
  }, [editTarget, layoutDraft, loadLayoutSnapshots, t, toast])

  const runRestoreLayout = useCallback(async (id: string) => {
    if (!id) return
    setApplying(true)
    try {
      const res = await apiPost<{ restored?: { rooms?: number } }>(
        '/world-dev/layout-restore', { snapshot_id: id })
      toast(res.restored
        ? t('Snapshot restored ({n} rooms)')
          .replace('{n}', String(res.restored.rooms ?? 0))
        : t('Snapshot restored'), 'success')
      setApplied(true)
    } catch (e) {
      toast(t('Restore failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setApplying(false)
    }
  }, [t, toast])

  /** The floor-plan editor lives in the World tab of this very SPA. */
  const openWorldEditor = useCallback(() => {
    window.location.hash = '#/world'
  }, [])

  const confirmPending = useCallback(() => {
    const action = pendingAction
    setPendingAction(null)
    if (!action) return
    if (action.kind === 'apply') void runApply(action.mode)
    else if (action.kind === 'restore') void runRestore(action.snapshotId)
    else if (action.kind === 'apply-layout') void runApplyLayout()
    else void runRestoreLayout(action.snapshotId)
  }, [pendingAction, runApply, runApplyLayout, runRestore, runRestoreLayout])

  const targetOptions = useMemo(() => {
    if (schema === 'character') return characters.map((c) => ({ id: c.name, label: c.display_name || c.name }))
    return locations.map((l) => ({ id: l.id, label: l.name || l.id }))
  }, [characters, locations, schema])

  const toggleContextLocation = (id: string) => {
    setContextLocations((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleContextCharacter = (name: string) => {
    setContextCharacters((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  // Filter "Durchgangs-Locations" (passable=true: corridors, doorways,
  // any place that exists only as a transit node) — they're not real
  // contexts the LLM should reason about. Locations without an explicit
  // `passable` flag default to non-passable and stay visible.
  const contextLocationOptions = locations.filter((l) => l.passable !== true)
  const remainingLocations = contextLocationOptions.filter((l) => !contextLocations.has(l.id))
  const remainingCharacters = characters.filter((c) => !contextCharacters.has(c.name))

  return (
    <div className="ga-wd-shell">
      <div className="ga-wd-config">
        <div className="ga-wd-config-row">
          <button className="ga-btn ga-btn-sm" onClick={newSession} title={t('Start a fresh conversation')}>
            ↻ {t('New conversation')}
          </button>
          <ModelPicker
            className="ga-wd-model-select"
            options={modelOptions}
            value={model ? `${provider}|${model}` : ''}
            emptyLabel={t('Pick model')}
            placeholder={t('Pick model')}
            onChange={(v) => {
              if (!v) { setModel(''); setProvider(''); return }
              const [prov, name] = v.split('|', 2)
              setProvider(prov || ''); setModel(name || '')
            }}
          />
          <input
            className="ga-input"
            type="number"
            min={0}
            step={1024}
            style={{ width: 92, flex: '0 0 auto' }}
            value={maxTokens}
            placeholder={t('default')}
            title={t('Max tokens (completion budget). Thinking models spend hidden reasoning tokens from this budget too. Empty = the model\'s LLM-Routing max_tokens, else 32768. 0 = no max_tokens sent — required for vLLM (rejects prompt+max_tokens beyond the context window), but Together then applies a TINY default and cuts after a few tokens.')}
            onChange={(e) => setMaxTokens(e.target.value)}
          />
          <ModelPicker
            className="ga-wd-model-select"
            options={modelOptions}
            value={validateModel ? `${validateProvider}|${validateModel}` : ''}
            emptyLabel={t('Validator: same as chat')}
            placeholder={t('Validator: same as chat')}
            title={t('Model used by the Validate button. Empty = same as chat model.')}
            onChange={(v) => {
              if (!v) { setValidateModel(''); setValidateProvider(''); return }
              const [prov, name] = v.split('|', 2)
              setValidateProvider(prov || ''); setValidateModel(name || '')
            }}
          />
          <select
            className="ga-input ga-wd-compact-select"
            value={mode}
            onChange={(e) => {
              setMode(e.target.value as Mode)
              setEditTarget('')
            }}
            title={t('Mode')}
          >
            {/* Same two values everywhere — only the wording follows the
                subject: a map is drawn from scratch or reworked, a record is
                created or edited. */}
            <option value="new">{isMap ? t('New map') : t('Create new')}</option>
            <option value="edit">{isMap ? t('Edit existing map') : t('Edit')}</option>
          </select>
          <select
            className="ga-input ga-wd-compact-select"
            value={schema}
            onChange={(e) => setSchema(e.target.value)}
            title={t('Schema')}
          >
            {(schemas.length ? schemas : [{ name: 'location', label: 'Location' }]).map((s) => (
              <option key={s.name} value={s.name}>
                {s.label}
              </option>
            ))}
          </select>
          {mode === 'new' && schema === 'character' ? (
            <select
              className="ga-input ga-wd-compact-select"
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
              title={t('Template')}
            >
              {templates.length === 0 ? (
                <option value="">— {t('no templates')} —</option>
              ) : null}
              {templates.map((tp) => (
                <option key={tp.name} value={tp.name}>
                  {tp.label}
                </option>
              ))}
            </select>
          ) : null}
          {/* A map has exactly one instance — there is nothing to pick. A
              floor plan always belongs to a location, so it picks in both
              modes; everything else only when editing. */}
          {(isLayout || (mode === 'edit' && !isMap)) ? (
            <select
              className="ga-input ga-wd-target-select"
              value={editTarget}
              onChange={(e) => setEditTarget(e.target.value)}
              title={isLayout ? t('Location to lay out') : t('Target to edit')}
            >
              <option value="">
                — {isLayout ? t('select location') : t('select target')} —
              </option>
              {targetOptions.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : null}
        </div>

        <div className="ga-wd-context-row">
          <span className="ga-wd-context-label">{t('Locations')}</span>
          <div className="ga-tags-row ga-wd-tags">
            {Array.from(contextLocations).map((id) => {
              const loc = locations.find((l) => l.id === id)
              return (
                <button
                  key={id}
                  type="button"
                  className="ga-tag-pill"
                  onClick={() => toggleContextLocation(id)}
                >
                  {loc?.name || id} ×
                </button>
              )
            })}
            <select
              className="ga-input ga-wd-tag-add"
              value=""
              onChange={(e) => {
                if (e.target.value) toggleContextLocation(e.target.value)
              }}
            >
              <option value="">+ {t('add location')}</option>
              {remainingLocations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name || l.id}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="ga-wd-context-row">
          <span className="ga-wd-context-label">{t('Characters')}</span>
          <div className="ga-tags-row ga-wd-tags">
            {Array.from(contextCharacters).map((name) => {
              const c = characters.find((x) => x.name === name)
              return (
                <button
                  key={name}
                  type="button"
                  className="ga-tag-pill"
                  onClick={() => toggleContextCharacter(name)}
                >
                  {c?.display_name || name} ×
                </button>
              )
            })}
            <select
              className="ga-input ga-wd-tag-add"
              value=""
              onChange={(e) => {
                if (e.target.value) toggleContextCharacter(e.target.value)
              }}
            >
              <option value="">+ {t('add character')}</option>
              {remainingCharacters.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.display_name || c.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="ga-wd-chat" ref={chatScrollRef}>
        {messages.length === 0 && !pending ? (
          <div className="ga-placeholder">
            {mode === 'edit' && editTarget
              ? t('Editing "{name}". Describe your changes below and click Send.').replace(
                  '{name}',
                  targetOptions.find((o) => o.id === editTarget)?.label || editTarget,
                )
              : t('Pick a model and describe what you want to create or edit.')}
          </div>
        ) : null}
        {messages.map((m, idx) => (
          <div key={idx} className={`ga-wd-msg ga-wd-msg-${m.role}`}>
            <div className="ga-wd-msg-role">{m.role === 'user' ? t('You') : t('Assistant')}</div>
            <pre className="ga-wd-msg-body">{m.content}</pre>
          </div>
        ))}
        {pending ? (
          <div className="ga-wd-msg ga-wd-msg-assistant">
            <div className="ga-wd-msg-role">{t('Assistant')}</div>
            <pre className="ga-wd-msg-body">{pending}</pre>
          </div>
        ) : null}
      </div>

      {isMap ? (
        <div className="ga-wd-extracted">
          <div className="ga-form-section-label">{t('Map draft')}</div>
          {previewing ? (
            <div className="ga-form-hint">{t('Checking the draft…')}</div>
          ) : null}
          {previewError ? (
            <div className="ga-form-hint" style={{ color: '#f85149' }}>
              {t('Preview failed')}: {previewError}
            </div>
          ) : null}
          {!mapDraft && !previewing ? (
            <div className="ga-form-hint">
              {t('Describe the layout in the chat — the draft appears here as a map.')}
            </div>
          ) : null}
          {preview ? (
            <MapDraftPreview
              normalized={preview.normalized}
              warnings={preview.warnings || []}
              counts={preview.counts}
            />
          ) : null}
          <div className="ga-form-row" style={{ marginTop: 6 }}>
            <button
              className="ga-btn ga-btn-primary ga-btn-sm"
              disabled={!preview || applying}
              onClick={() => setPendingAction({ kind: 'apply', mode: 'merge' })}
              title={t('Add the draft next to what the world already has')}
            >
              {t('Apply (merge)')}
            </button>
            <button
              className="ga-btn ga-btn-sm"
              disabled={!preview || applying}
              onClick={() => setPendingAction({ kind: 'apply', mode: 'replace_terrain' })}
              title={t('Clear all painted ground and relief first, then write the draft')}
            >
              {t('Apply (replace terrain)')}
            </button>
            {applied ? (
              <button className="ga-btn ga-btn-sm" onClick={openMapEditor}>
                {t('Open in map editor')}
              </button>
            ) : null}
          </div>
          <div className="ga-form-row" style={{ marginTop: 4 }}>
            <span className="ga-wd-context-label" style={{ flex: '0 0 auto' }}>
              {t('Snapshots')}
            </span>
            <select
              className="ga-input ga-wd-target-select"
              value={snapshotId}
              onChange={(e) => setSnapshotId(e.target.value)}
              title={t('A snapshot of the whole map is taken before every apply')}
            >
              <option value="">— {t('select snapshot')} —</option>
              {snapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  {(s.created_at || s.id)
                    + (s.counts
                      ? ` · ${s.counts.areas ?? 0}/${s.counts.heights ?? 0}/${s.counts.positions ?? 0}`
                      : '')}
                </option>
              ))}
            </select>
            <button
              className="ga-btn ga-btn-sm"
              disabled={!snapshotId || applying}
              onClick={() => setPendingAction({ kind: 'restore', snapshotId })}
            >
              {t('Restore snapshot')}
            </button>
          </div>
        </div>
      ) : null}

      {isLayout ? (
        <div className="ga-wd-extracted">
          <div className="ga-form-section-label">{t('Floor plan draft')}</div>
          {!editTarget ? (
            <div className="ga-form-hint">
              {t('Pick the location this plan is for — a floor plan always belongs to one place.')}
            </div>
          ) : null}
          {layoutPreviewing ? (
            <div className="ga-form-hint">{t('Checking the draft…')}</div>
          ) : null}
          {layoutPreviewError ? (
            <div className="ga-form-hint" style={{ color: '#f85149' }}>
              {t('Preview failed')}: {layoutPreviewError}
            </div>
          ) : null}
          {editTarget && !layoutDraft && !layoutPreviewing ? (
            <div className="ga-form-hint">
              {t('Describe the rooms in the chat — the draft appears here as a floor plan.')}
            </div>
          ) : null}
          {layoutPreview ? (
            <LayoutDraftPreview
              normalized={layoutPreview.normalized}
              warnings={layoutPreview.warnings || []}
              counts={layoutPreview.counts}
            />
          ) : null}
          <div className="ga-form-row" style={{ marginTop: 6 }}>
            <button
              className="ga-btn ga-btn-primary ga-btn-sm"
              disabled={!layoutPreview || applying}
              onClick={() => setPendingAction({ kind: 'apply-layout' })}
              title={t('Write the plan through the floor-plan editor’s own save path')}
            >
              {t('Apply floor plan')}
            </button>
            {applied ? (
              <button className="ga-btn ga-btn-sm" onClick={openWorldEditor}>
                {t('Open in floor-plan editor')}
              </button>
            ) : null}
          </div>
          <div className="ga-form-row" style={{ marginTop: 4 }}>
            <span className="ga-wd-context-label" style={{ flex: '0 0 auto' }}>
              {t('Snapshots')}
            </span>
            <select
              className="ga-input ga-wd-target-select"
              value={layoutSnapshotId}
              onChange={(e) => setLayoutSnapshotId(e.target.value)}
              title={t('A snapshot of this location’s whole plan is taken before every apply')}
            >
              <option value="">— {t('select snapshot')} —</option>
              {layoutSnapshots.map((s) => (
                <option key={s.id} value={s.id}>
                  {(s.created_at || s.id)
                    + (s.rooms !== undefined ? ` · ${s.rooms}` : '')}
                </option>
              ))}
            </select>
            <button
              className="ga-btn ga-btn-sm"
              disabled={!layoutSnapshotId || applying}
              onClick={() => setPendingAction({
                kind: 'restore-layout', snapshotId: layoutSnapshotId })}
            >
              {t('Restore snapshot')}
            </button>
          </div>
        </div>
      ) : null}

      {Object.keys(extracted).length > 0 ? (
        <div className="ga-wd-extracted">
          <div className="ga-form-section-label">{t('Extracted JSON')}</div>
          <div className="ga-form-row">
            {(Object.keys(extracted) as Array<keyof ExtractedData>).map((k) => (
              <button key={k} className="ga-btn ga-btn-primary ga-btn-sm" onClick={() => apply(k)}>
                {t('Apply')} {k.replace('_data', '')}
              </button>
            ))}
            <button
              className="ga-btn ga-btn-sm"
              onClick={validate}
              disabled={validating}
              title={t('Run a tool LLM over the JSON and write missing fields into the input below')}
            >
              {validating ? t('Validating…') : t('Validate (find gaps)')}
            </button>
          </div>
        </div>
      ) : null}

      <div className="ga-wd-input">
        <textarea
          className="ga-textarea"
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t('Describe what you want to create or edit… Enter to send, Shift+Enter for newline')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          disabled={streaming}
        />
        <div className="ga-wd-stats" title={t('Session totals — accumulated across all turns of this conversation')}>
          {usage ? (
            <>
              <span>
                <strong>{t('In')}</strong> {usage.tokens_in.toLocaleString()}
              </span>
              <span>
                <strong>{t('Out')}</strong> {usage.tokens_out.toLocaleString()}
              </span>
              <span>
                <strong>{t('Cost')}</strong> {formatUsd(usage.cost_total)}
              </span>
            </>
          ) : (
            <span className="ga-form-hint">{t('No session yet')}</span>
          )}
        </div>
        <button className="ga-btn ga-btn-primary" onClick={send} disabled={streaming || !draft.trim()}>
          {streaming ? t('…') : t('Send')}
        </button>
      </div>

      {pendingAction
        && (pendingAction.kind === 'apply' || pendingAction.kind === 'restore') ? (
          <ConfirmMapAction
            action={pendingAction}
            counts={preview?.counts}
            warningCount={preview?.warnings?.length || 0}
            snapshots={snapshots}
            onCancel={() => setPendingAction(null)}
            onConfirm={confirmPending}
          />
        ) : null}
      {pendingAction
        && (pendingAction.kind === 'apply-layout'
          || pendingAction.kind === 'restore-layout') ? (
          <ConfirmLayoutAction
            action={pendingAction}
            counts={layoutPreview?.counts}
            warningCount={layoutPreview?.warnings?.length || 0}
            snapshots={layoutSnapshots}
            onCancel={() => setPendingAction(null)}
            onConfirm={confirmPending}
          />
        ) : null}
    </div>
  )
}

/**
 * The one confirmation of the map flow — a real dialog, portalled to
 * `document.body`. No native browser dialog: the app builds its own inputs and
 * confirmations, and a native box could not carry the numbers below.
 *
 * It states WHAT will be written, and that a snapshot is taken first, because
 * the map editor itself has no undo — the snapshot is the only way back.
 */
function ConfirmMapAction({
  action, counts, warningCount, snapshots, onCancel, onConfirm,
}: {
  action: MapAction
  counts?: MapDraftCounts
  warningCount: number
  snapshots: MapSnapshot[]
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useI18n()
  const isRestore = action.kind === 'restore'
  const snap = isRestore
    ? snapshots.find((s) => s.id === action.snapshotId) : undefined
  const title = isRestore
    ? t('Restore this snapshot?')
    : action.mode === 'replace_terrain'
      ? t('Replace the terrain with this draft?')
      : t('Merge this draft into the map?')

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onCancel}>
      <div
        className="ga-modal"
        role="dialog"
        aria-label={title}
        style={{ maxWidth: 520, width: 'min(520px, 92vw)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onCancel}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {isRestore ? (
            <>
              <div>
                {t('The whole map is set back to the snapshot: painted ground, relief and every position it recorded.')}
              </div>
              {snap?.counts?.created ? (
                <div style={{ color: '#d29922' }}>
                  {t('The {n} places that apply created are deleted again. A place you made by hand afterwards is not touched.')
                    .replace('{n}', String(snap.counts.created))}
                </div>
              ) : null}
              <div className="ga-form-hint">
                {snap?.created_at || action.snapshotId}
                {snap?.counts
                  ? ` · ${t('{a} areas · {h} height areas · {p} positions')
                    .replace('{a}', String(snap.counts.areas ?? 0))
                    .replace('{h}', String(snap.counts.heights ?? 0))
                    .replace('{p}', String(snap.counts.positions ?? 0))}`
                  : ''}
              </div>
            </>
          ) : (
            <>
              <div>
                {t('This writes {a} terrain areas, {h} height areas and {p} location positions into the world.')
                  .replace('{a}', String(counts?.areas ?? 0))
                  .replace('{h}', String(counts?.heights ?? 0))
                  .replace('{p}', String(counts?.positions ?? 0))}
              </div>
              {counts?.created ? (
                <div style={{ color: '#a371f7' }}>
                  {t('It also CREATES {n} new places. They are stubs: a name, a description and an outline — rooms and prompts come later, through the location schema.')
                    .replace('{n}', String(counts.created))}
                </div>
              ) : null}
              {action.mode === 'replace_terrain' ? (
                <div style={{ color: '#d29922' }}>
                  {t('Every existing terrain area and height area is deleted first. Location positions are kept — only the listed places move.')}
                </div>
              ) : null}
              {warningCount > 0 ? (
                <div className="ga-form-hint">
                  {t('{n} warnings are still open — they do not block the apply.')
                    .replace('{n}', String(warningCount))}
                </div>
              ) : null}
              <div className="ga-form-hint">
                {t('A snapshot of the current map is taken first, so you can restore it from the list below.')}
              </div>
            </>
          )}
        </div>
        <div className="ga-modal-footer"
          style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onCancel}>
            {t('Cancel')}
          </button>
          <button type="button" className="ga-btn ga-btn-primary ga-btn-sm" onClick={onConfirm}>
            {isRestore ? t('Restore') : t('Apply')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/**
 * The one confirmation of the floor-plan flow — the map dialog's sibling, and
 * a real dialog portalled to `document.body` for the same reason: the app
 * builds its own confirmations, and a native box could not carry the numbers.
 *
 * It states WHAT will be written and that a snapshot is taken first, because
 * the floor-plan editor itself has no undo either — the snapshot is the only
 * way back from a plan that replaced every room rectangle at once.
 */
function ConfirmLayoutAction({
  action, counts, warningCount, snapshots, onCancel, onConfirm,
}: {
  action: LayoutAction
  counts?: LayoutDraftCounts
  warningCount: number
  snapshots: LayoutSnapshot[]
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useI18n()
  const isRestore = action.kind === 'restore-layout'
  const snap = isRestore
    ? snapshots.find((s) => s.id === action.snapshotId) : undefined
  const title = isRestore
    ? t('Restore this floor plan?')
    : t('Write this floor plan?')

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onCancel}>
      <div
        className="ga-modal"
        role="dialog"
        aria-label={title}
        style={{ maxWidth: 520, width: 'min(520px, 92vw)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onCancel}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {isRestore ? (
            <>
              <div>
                {t('The location goes back to the room list of the snapshot: every room plan, the plot entrances and the entry room. Rooms created after it are removed.')}
              </div>
              <div className="ga-form-hint">
                {snap?.created_at || action.snapshotId}
                {snap?.location_name ? ` · ${snap.location_name}` : ''}
                {snap?.rooms !== undefined
                  ? ` · ${t('{n} rooms').replace('{n}', String(snap.rooms))}`
                  : ''}
              </div>
            </>
          ) : (
            <>
              <div>
                {t('This writes {r} room plans ({n} of them new rooms), {o} openings and {b} plot entrances into the location.')
                  .replace('{r}', String(counts?.rooms ?? 0))
                  .replace('{n}', String(counts?.new_rooms ?? 0))
                  .replace('{o}', String(counts?.openings ?? 0))
                  .replace('{b}', String(counts?.boundary_openings ?? 0))}
              </div>
              <div className="ga-form-hint">
                {t('Rooms the plan does not mention keep the plan they have.')}
              </div>
              {warningCount > 0 ? (
                <div className="ga-form-hint">
                  {t('{n} warnings are still open — they do not block the apply.')
                    .replace('{n}', String(warningCount))}
                </div>
              ) : null}
              <div className="ga-form-hint">
                {t('A snapshot of the current plan is taken first, so you can restore it from the list below.')}
              </div>
            </>
          )}
        </div>
        <div className="ga-modal-footer"
          style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onCancel}>
            {t('Cancel')}
          </button>
          <button type="button" className="ga-btn ga-btn-primary ga-btn-sm" onClick={onConfirm}>
            {isRestore ? t('Restore') : t('Apply')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
