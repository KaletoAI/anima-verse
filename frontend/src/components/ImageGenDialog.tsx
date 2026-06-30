import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { useHelp } from '../help/HelpContext'

/**
 * Modal dialog for image-generation overrides — provider/workflow,
 * model, LoRAs, prompt. Pre-fills from `/world/imagegen-options`,
 * `/world/imagegen-models`, `/world/imagegen-loras`. Submit fires the
 * caller-supplied `onSubmit(payload)` and closes; the caller is
 * responsible for posting the request and refreshing the UI. The
 * server enqueues the job, so submit is fire-and-forget.
 */

interface LoraDefault {
  name: string
  strength: number
}

interface ImagegenOption {
  type: 'workflow' | 'backend'
  name: string
  label: string
  has_loras?: boolean
  default_loras?: LoraDefault[]
  model_type?: string
  default_model?: string
  filter?: string
  models?: string[] // for non-comfy backends with their own model list
  lora_options?: string[] // LoRA names for backend options (from the LoRA Library, endpoint-filtered)
  ref_slot_count?: number // number of reference-image slots (0 = none)
  compatible_backends?: string[] // ComfyUI instances this workflow runs on (empty = all)
  category?: string // 'inpaint' = nur für Map-Fit/Match-Edges, nicht für normale Renders
}

interface ComfyBackend {
  name: string
  available: boolean
}

interface ImagegenOptionsResponse {
  options: ImagegenOption[]
  comfy_backends?: ComfyBackend[]
  default_location?: string
}

// Ein Eintrag im „Service (match)"-Dropdown. Entweder ein reiner Match
// (Workflow auto / Cloud-Backend) oder ein Workflow mit gepinntem ComfyUI-
// Endpoint (backendOverride). `option` traegt die Metadaten (ref_slot_count,
// LoRAs, Model) — der Override aendert nur, welche Instanz angesprochen wird.
interface SelectEntry {
  id: string
  group: string
  label: string
  option: ImagegenOption
  // Was als payload.workflow gesendet wird: bei „auto" der Filter-Glob (Match),
  // bei „fixed endpoint" der EXAKTE Workflow-Name (sonst kann der Server zwei
  // Workflows mit gleichem Glob — z.B. „Qwen*" — nicht unterscheiden).
  workflowSpec?: string
  backendOverride?: string
}

export interface ImageGenSubmit {
  prompt: string
  workflow?: string
  backend?: string
  model_override?: string
  loras?: LoraDefault[] | null
  // Optional faithful-regenerate extras (Instagram/Gallery). Only emitted when
  // the corresponding prop enables the field.
  create_new?: boolean
  improvement_request?: string
  negative_prompt?: string
  character_names?: string[]
  // True when the prompt already includes the independent config parts
  // (prefix/suffix) from the dialog → the backend must NOT re-append them.
  prompt_settings_applied?: boolean
  // Reference-slot toggles (managed against the workflow's ref_slot_count budget).
  use_room?: boolean
  use_source_as_reference?: boolean
}

interface Props {
  open: boolean
  title: string
  defaultPrompt: string
  /** Optional thumbnail of the current image (shown for recreate/regenerate). */
  sourceImageUrl?: string
  /**
   * Independent config prompt parts to show as EDITABLE, marked fields (instead of
   * the backend appending them). Each: a label (shown as „from settings: <label>")
   * and the prefilled text. On submit they are joined into the full prompt and
   * `prompt_settings_applied` is set so the backend skips re-adding them.
   */
  settingsPrefix?: { label: string; text: string }
  settingsSuffix?: { label: string; text: string }
  /** Show a "Room / background" reference toggle (counts against the slot budget). */
  showRoomReference?: boolean
  /** Initial state of the "use current image as reference" toggle. */
  defaultUseSource?: boolean
  /**
   * Require the source image to actually be used as a reference: the chosen
   * workflow must expose a reference slot (ref_slot_count > 0) and the
   * "current image as reference" toggle must be on. Otherwise the Generate
   * button is blocked with a hint to pick a reference-capable workflow
   * (e.g. Flux2/Qwen). Use for "adjust this image"-style regenerate, where a
   * non-reference workflow would silently produce a fresh image instead.
   */
  requireSourceReference?: boolean
  /**
   * Show the "add as new image vs. replace the current one" checkbox even
   * outside `mode='regenerate'` (e.g. the location gallery regenerate). Emits
   * `create_new` in the payload. `defaultCreateNew` sets its initial state.
   */
  showCreateNew?: boolean
  defaultCreateNew?: boolean
  /**
   * Endpoint for the "Improve" button next to the improvement-request field
   * (POST { prompt, improvement_request } -> { prompt }). The rewritten prompt
   * is written back into the Prompt field. Default: generic, character-less
   * `/world/imagegen-enhance-prompt`.
   */
  enhanceEndpoint?: string
  onSubmit: (payload: ImageGenSubmit) => void | Promise<void>
  onClose: () => void
  /**
   * Field visibility is opt-OUT: generic fields (workflow, prompt, LoRAs, negative
   * prompt) show by default so new generic features land in every caller. Only
   * context-specific fields are gated:
   *  - `mode='regenerate'` adds the "improvement request" field + the "add as new
   *    image vs. replace" toggle (only meaningful when regenerating an existing image).
   *  - `characterOptions` adds the character checkboxes (only for images with people).
   *  - `hideNegative` hides the negative-prompt field for the rare backend that
   *    ignores a custom negative (e.g. world backgrounds).
   */
  mode?: 'create' | 'regenerate'
  hideNegative?: boolean
  /** Show character checkboxes (detected pre-selected) to pin who is in the image. */
  characterOptions?: { detected: CharOpt[]; available: CharOpt[] }
}

// Charakter-Eintrag: manche Endpunkte liefern Strings, andere {name, type}-Objekte
// (z.B. /instagram/.../detect-characters). Immer auf den reinen Namen normalisieren,
// sonst rendert React ein Objekt als Kind → Error #31.
type CharOpt = string | { name: string; type?: string }
const charName = (c: CharOpt): string => (typeof c === 'string' ? c : c?.name || '')

// Match-Wert einer Option wie das Admin-Feld „…/Vorschau Default (Match)":
//   workflow:<glob>  (Glob aus dem Workflow-filter, sonst Name)
//   backend:<name>   (Provider, exakter Name matcht sich selbst)
// Wird nach Verfügbarkeit serverseitig aufgelöst (resolve_imagegen_target).
const optMatch = (o: ImagegenOption): string =>
  o.type === 'workflow' ? `workflow:${o.filter || o.name}` : `backend:${o.name}`

const LORA_SLOTS = 4

function globToRegex(glob: string): RegExp {
  const esc = glob.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')
  return new RegExp('^' + esc + '$', 'i')
}

function filterByWorkflowName(items: string[], workflowName: string, filter: string): string[] {
  if (filter) {
    const re = globToRegex(filter)
    const matched = items.filter((l) => {
      if (l === 'None') return true
      const base = l.includes('/') ? l.split('/').pop()! : l
      return re.test(base)
    })
    if (matched.length > 1) return matched
  } else if (workflowName) {
    const prefix = workflowName.toLowerCase()
    let matched = items.filter((l) => {
      if (l === 'None') return true
      const base = l.includes('/') ? l.split('/').pop()! : l
      return base.toLowerCase().startsWith(prefix)
    })
    if (matched.length <= 1) {
      matched = items.filter((l) => {
        if (l === 'None') return true
        const base = l.includes('/') ? l.split('/').pop()! : l
        return base.toLowerCase().includes(prefix)
      })
    }
    if (matched.length > 1) return matched
  }
  return items
}

export function ImageGenDialog({
  open, title, defaultPrompt, sourceImageUrl, settingsPrefix, settingsSuffix,
  showRoomReference, defaultUseSource, requireSourceReference,
  showCreateNew, defaultCreateNew,
  enhanceEndpoint = '/world/imagegen-enhance-prompt', onSubmit, onClose,
  mode = 'create', hideNegative, characterOptions,
}: Props) {
  const isRegen = mode === 'regenerate'
  const { t } = useI18n()
  const { setTopic } = useHelp()
  const [prompt, setPrompt] = useState(defaultPrompt)
  // Editierbare, markierte unabhaengige Config-Teile (Prefix/Suffix).
  const [prefixText, setPrefixText] = useState(settingsPrefix?.text || '')
  const [suffixText, setSuffixText] = useState(settingsSuffix?.text || '')
  const [createNew, setCreateNew] = useState(!!defaultCreateNew)
  // Referenz-Slot-Toggles (gegen das ref_slot_count-Budget des Workflows gemanagt).
  const [useRoom, setUseRoom] = useState(true)
  const [useSource, setUseSource] = useState(!!defaultUseSource)
  const [improvement, setImprovement] = useState('')
  const [negative, setNegative] = useState('')
  const [selectedChars, setSelectedChars] = useState<string[]>([])
  const [options, setOptions] = useState<ImagegenOption[] | null>(null)
  const [comfyBackends, setComfyBackends] = useState<ComfyBackend[]>([])
  const [defaultLocationOpt, setDefaultLocationOpt] = useState<string>('')
  const [optionKey, setOptionKey] = useState<string>('') // SelectEntry.id
  const [allLoras, setAllLoras] = useState<string[]>([])
  const [loraSlots, setLoraSlots] = useState<LoraDefault[]>(
    () => Array.from({ length: LORA_SLOTS }, () => ({ name: 'None', strength: 1.0 })),
  )
  const [submitting, setSubmitting] = useState(false)
  const [enhancing, setEnhancing] = useState(false)

  // "Improve": laesst den Prompt per LLM aus dem Aenderungswunsch umschreiben
  // und schreibt das Ergebnis ins Prompt-Feld (sichtbar/editierbar vor dem
  // Generieren). Danach ist das Improvement-Feld leer -> Generierung woertlich.
  const applyImprovement = useCallback(async () => {
    const base = prompt.trim()
    const wish = improvement.trim()
    if (!base || !wish || enhancing) return
    setEnhancing(true)
    try {
      const res = await apiPost<{ prompt?: string }>(enhanceEndpoint, {
        prompt: base, improvement_request: wish,
      })
      if (res?.prompt) {
        setPrompt(res.prompt)
        setImprovement('')
      }
    } catch {
      /* Fehler still — der Nutzer kann den Prompt auch manuell anpassen. */
    } finally {
      setEnhancing(false)
    }
  }, [prompt, improvement, enhancing, enhanceEndpoint])

  // Resync prompt + independent config parts when the caller changes them
  // (e.g. day → night, or map → map_2d with a different suffix).
  useEffect(() => {
    if (open) setPrompt(defaultPrompt)
  }, [open, defaultPrompt])
  useEffect(() => {
    if (open) setPrefixText(settingsPrefix?.text || '')
  }, [open, settingsPrefix?.text])
  useEffect(() => {
    if (open) setSuffixText(settingsSuffix?.text || '')
  }, [open, settingsSuffix?.text])
  useEffect(() => {
    if (open) { setUseRoom(true); setUseSource(!!defaultUseSource) }
  }, [open, defaultUseSource])

  // Reset the regenerate extras when (re)opening; pre-select detected characters.
  const detNames = (characterOptions?.detected || []).map(charName)
  const availNames = (characterOptions?.available || []).map(charName)
  const detectedKey = detNames.join('|')
  useEffect(() => {
    if (!open) return
    setCreateNew(!!defaultCreateNew)
    setImprovement('')
    setNegative('')
    setSelectedChars(detNames)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, detectedKey])

  // Load options + loras once when dialog first opens.
  useEffect(() => {
    if (!open || options !== null) return
    apiGet<ImagegenOptionsResponse>('/world/imagegen-options')
      .then((d) => {
        // KEIN globaler Dedup mehr: die Fixed-Endpoint-Eintraege brauchen jeden
        // einzelnen Workflow (auch zwei mit gleichem Glob, z.B. „Flux2 NVFP4"
        // und „Flux2 Q5"). Der Dedup passiert nur noch in der „auto"-Gruppe.
        setOptions(d.options || [])
        setComfyBackends(d.comfy_backends || [])
        setDefaultLocationOpt(d.default_location || '')
      })
      .catch(() => setOptions([]))
    apiGet<{ loras: string[] }>('/world/imagegen-loras')
      .then((d) => setAllLoras(d.loras || []))
      .catch(() => setAllLoras([]))
  }, [open, options])

  // Gruppierte Auswahl-Eintraege bauen: pro Workflow ein „auto"-Match plus je
  // einen Eintrag pro kompatibler ComfyUI-Instanz (gepinnter Endpoint). Nicht-
  // Comfy-Backends (Cloud) als eigene Gruppe.
  const entries = useMemo<SelectEntry[]>(() => {
    if (!options) return []
    const auto: SelectEntry[] = []
    const fixed: SelectEntry[] = []
    const cloud: SelectEntry[] = []
    const seenGlob = new Set<string>()
    for (const o of options) {
      // Inpaint-Ziele gehören nur in die Map-Fit/Match-Edges-Dialoge, nie in die
      // normale Render-Auswahl.
      if (o.category === 'inpaint') continue
      if (o.type === 'workflow') {
        // „auto": ein Eintrag pro Filter-Glob (Match waehlt Workflow + Endpoint).
        const fspec = o.filter || o.name
        const key = `workflow:${fspec}`
        if (!seenGlob.has(key)) {
          seenGlob.add(key)
          auto.push({ id: `auto:${key}`, group: t('Workflows (auto)'), label: optMatch(o), option: o, workflowSpec: fspec })
        }
        // „fixed endpoint": exakter Workflow-Name × jede kompatible ComfyUI-Instanz.
        const compat = o.compatible_backends || []
        const eps = comfyBackends.filter((b) => compat.length === 0 || compat.includes(b.name))
        for (const ep of eps) {
          fixed.push({
            id: `fix:${o.name}@${ep.name}`,
            group: t('Fixed endpoints'),
            label: `${o.name} @ ${ep.name}${ep.available ? '' : ' (offline?)'}`,
            option: o,
            workflowSpec: o.name,
            backendOverride: ep.name,
          })
        }
      } else {
        cloud.push({ id: `be:${o.name}`, group: t('Cloud backends'), label: optMatch(o), option: o })
      }
    }
    return [...auto, ...fixed, ...cloud]
  }, [options, comfyBackends, t])

  // Gruppen in Render-Reihenfolge (erste Vorkommnisse), fuer die <optgroup>s.
  const entryGroups = useMemo<string[]>(() => {
    const seen = new Set<string>()
    const order: string[] = []
    for (const e of entries) if (!seen.has(e.group)) { seen.add(e.group); order.push(e.group) }
    return order
  }, [entries])

  // Pick initial entry once the list arrives.
  useEffect(() => {
    if (!entries.length || optionKey) return
    const match = defaultLocationOpt
      ? entries.find(
          (e) => e.backendOverride === undefined && (
            `${e.option.type}:${e.option.name}` === defaultLocationOpt ||
            e.option.name === defaultLocationOpt),
        )
      : null
    setOptionKey((match || entries[0]).id)
  }, [entries, defaultLocationOpt, optionKey])

  const currentEntry = useMemo<SelectEntry | null>(
    () => entries.find((e) => e.id === optionKey) || null, [entries, optionKey])

  const currentOption = useMemo<ImagegenOption | null>(() => {
    return currentEntry?.option || null
  }, [currentEntry])

  // Reset LoRA slots when workflow changes; pull defaults from the option.
  useEffect(() => {
    if (!currentOption) return
    const defaults = currentOption.default_loras || []
    setLoraSlots(
      Array.from({ length: LORA_SLOTS }, (_, i) => ({
        name: defaults[i]?.name || 'None',
        strength: defaults[i]?.strength ?? 1.0,
      })),
    )
  }, [currentOption])

  // ESC closes; lock body scroll while open.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, submitting, onClose])

  const filteredLoras = useMemo(() => {
    if (!currentOption || !currentOption.has_loras) return []
    // Backend-Optionen (z.B. openai_diffusion): LoRA-Namen direkt aus der
    // LoRA-Library (endpoint-gefiltert, vom Server geliefert). Workflows:
    // ComfyUI-Scan nach Workflow-Name/Filter.
    if (currentOption.type === 'backend') return currentOption.lora_options || []
    return filterByWorkflowName(allLoras, currentOption.name, currentOption.filter || '')
  }, [allLoras, currentOption])

  const handleSubmit = useCallback(async () => {
    if (!currentOption) return
    // Vollen Prompt zusammensetzen: Prefix + Basis + Suffix (alle editierbar). Der
    // Server haengt die unabhaengigen Config-Teile dann nicht erneut an.
    const fullPrompt = [prefixText.trim(), prompt.trim(), suffixText.trim()]
      .filter(Boolean).join(', ')
    const payload: ImageGenSubmit = { prompt: fullPrompt }
    if (settingsPrefix || settingsSuffix) payload.prompt_settings_applied = true
    // Match-Glob senden (workflow:<filter> / backend:<name>) — der Server löst ihn
    // nach Verfügbarkeit auf (match_workflow / match_backend), wie im Admin-Default.
    if (currentOption.type === 'workflow') {
      // „auto" sendet den Filter-Glob, „fixed endpoint" den exakten Namen.
      payload.workflow = currentEntry?.workflowSpec || currentOption.filter || currentOption.name
      // Gepinnter Endpoint: Workflow bleibt, diese ComfyUI-Instanz wird erzwungen.
      if (currentEntry?.backendOverride) payload.backend = currentEntry.backendOverride
    } else {
      payload.backend = currentOption.name
    }
    if (currentOption.has_loras) {
      const active = loraSlots.filter((l) => l.name && l.name !== 'None')
      payload.loras = active.length ? active : null
    }
    if (isRegen || showCreateNew) payload.create_new = createNew
    if (isRegen && improvement.trim()) payload.improvement_request = improvement.trim()
    if (!hideNegative && negative.trim()) payload.negative_prompt = negative.trim()
    if (characterOptions) payload.character_names = selectedChars
    if (showRoomReference) payload.use_room = useRoom
    if (sourceImageUrl) payload.use_source_as_reference = useSource
    setSubmitting(true)
    try {
      await onSubmit(payload)
      onClose()
    } finally {
      setSubmitting(false)
    }
  }, [currentOption, currentEntry, prompt, prefixText, suffixText, settingsPrefix,
      settingsSuffix, loraSlots, onSubmit, onClose, isRegen, showCreateNew, createNew,
      improvement, hideNegative, negative, characterOptions, selectedChars,
      showRoomReference, useRoom, sourceImageUrl, useSource])

  // Reference-slot budget: how many ref images may be used (workflow ref_slot_count).
  // Persons + room + current-image each consume one slot.
  const slotBudget = currentOption?.ref_slot_count || 0
  const usedSlots = selectedChars.length
    + (showRoomReference && useRoom ? 1 : 0)
    + (sourceImageUrl && useSource ? 1 : 0)
  const atBudget = slotBudget > 0 && usedSlots >= slotBudget
  // Regenerate-as-edit: the source image MUST land in a reference slot. Block
  // submit (and explain) when the chosen workflow has no slot or the toggle is off.
  const sourceRefBlocked = !!requireSourceReference
    && (!currentOption || slotBudget === 0 || !useSource)

  if (!open) return null

  // Render via portal to document.body so the fixed-position modal escapes any
  // transformed ancestor (e.g. react-grid-layout panels in /play, which use CSS
  // transform — a fixed child would otherwise be positioned relative to the
  // panel and appear clipped/offscreen as an "empty window").
  return createPortal(
    <div
      className="ga-modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose()
      }}
    >
      <div className="ga-modal" role="dialog" aria-label={title} style={{ maxWidth: 820 }}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button
            className="ga-modal-close"
            onClick={onClose}
            disabled={submitting}
            aria-label={t('Close')}
          >
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          {!options ? (
            <div className="ga-loading">{t('Loading…')}</div>
          ) : !options.length ? (
            <div className="ga-form-hint">{t('No image generation backends available.')}</div>
          ) : (
            // Zwei Spalten (wie der Animate-Dialog): links Service + LoRAs,
            // rechts (aktuelles) Bild + Prompt + Optionen. Bricht auf schmalem
            // Dialog via flex-wrap auf eine Spalte um.
            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 300px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <label className="ga-imagegen-label">{t('Service (match)')}</label>
              <select
                className="ga-input"
                value={optionKey}
                disabled={submitting}
                onChange={(e) => setOptionKey(e.target.value)}
              >
                {entryGroups.map((g) => (
                  <optgroup key={g} label={g}>
                    {entries.filter((e) => e.group === g).map((e) => (
                      <option key={e.id} value={e.id}>{e.label}</option>
                    ))}
                  </optgroup>
                ))}
              </select>

              {currentOption?.has_loras ? (
                <>
                  <label className="ga-imagegen-label">{t('LoRAs')}</label>
                  <div className="ga-imagegen-loras">
                    {loraSlots.map((slot, i) => {
                      const rest =
                        slot.name && slot.name !== 'None' && !filteredLoras.includes(slot.name)
                          ? [slot.name, ...filteredLoras]
                          : filteredLoras
                      // 'None' immer als erste Option (= Default + Abwahl moeglich).
                      const choices = ['None', ...rest.filter((l) => l !== 'None')]
                      return (
                        <div key={i} className="ga-imagegen-lora-row">
                          <span className="ga-imagegen-lora-label">LoRA {i + 1}</span>
                          <select
                            className="ga-input"
                            value={slot.name}
                            disabled={submitting}
                            onChange={(e) =>
                              setLoraSlots((prev) =>
                                prev.map((s, idx) =>
                                  idx === i ? { ...s, name: e.target.value } : s,
                                ),
                              )
                            }
                          >
                            {choices.map((l) => (
                              <option key={l} value={l}>
                                {l}
                              </option>
                            ))}
                          </select>
                          <input
                            type="number"
                            className="ga-input ga-imagegen-lora-strength"
                            min={-2}
                            max={2}
                            step={0.05}
                            disabled={submitting || slot.name === 'None'}
                            value={slot.strength}
                            onChange={(e) =>
                              setLoraSlots((prev) =>
                                prev.map((s, idx) =>
                                  idx === i
                                    ? { ...s, strength: parseFloat(e.target.value) || 0 }
                                    : s,
                                ),
                              )
                            }
                          />
                        </div>
                      )
                    })}
                  </div>
                </>
              ) : null}
              </div>

              <div style={{ flex: '1 1 320px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {sourceImageUrl ? (
                <img src={sourceImageUrl} alt="" style={{ maxHeight: 150, maxWidth: '100%', objectFit: 'contain', alignSelf: 'center', borderRadius: 6 }} />
              ) : null}

              {settingsPrefix ? (
                <div className="ga-imagegen-settings-part">
                  <label className="ga-imagegen-label ga-imagegen-settings-label">
                    {t('From settings')}: {settingsPrefix.label}
                  </label>
                  <textarea className="ga-textarea" rows={2} value={prefixText}
                    disabled={submitting} onChange={(e) => setPrefixText(e.target.value)} />
                </div>
              ) : null}

              <label className="ga-imagegen-label">{t('Prompt')}</label>
              <textarea
                className="ga-textarea"
                rows={6}
                value={prompt}
                disabled={submitting || enhancing}
                onFocus={() => setTopic('image_prompt')}
                onChange={(e) => setPrompt(e.target.value)}
              />

              {settingsSuffix ? (
                <div className="ga-imagegen-settings-part">
                  <label className="ga-imagegen-label ga-imagegen-settings-label">
                    {t('From settings')}: {settingsSuffix.label}
                  </label>
                  <textarea className="ga-textarea" rows={2} value={suffixText}
                    disabled={submitting} onChange={(e) => setSuffixText(e.target.value)} />
                </div>
              ) : null}

              {(characterOptions || (slotBudget > 0 && (showRoomReference || sourceImageUrl))) ? (
                <>
                  <label className="ga-imagegen-label">
                    {slotBudget > 0 ? t('Reference images') : t('Characters in the image')}
                    {slotBudget > 0 ? ` (${usedSlots}/${slotBudget})` : ''}
                  </label>
                  {characterOptions && (availNames.length ? availNames : detNames).length === 0 ? (
                    <div className="ga-form-hint">{t('No characters detected.')}</div>
                  ) : characterOptions ? (
                    <div className="ga-imagegen-chars">
                      {(availNames.length ? availNames : detNames).map((name) => {
                        const on = selectedChars.includes(name)
                        return (
                          <label key={name} className="ga-check-row">
                            <input
                              type="checkbox"
                              checked={on}
                              disabled={submitting || (!on && atBudget)}
                              onChange={() =>
                                setSelectedChars((prev) =>
                                  on ? prev.filter((x) => x !== name) : [...prev, name],
                                )
                              }
                            />
                            <span>{name}</span>
                          </label>
                        )
                      })}
                    </div>
                  ) : null}
                  {slotBudget > 0 && showRoomReference ? (
                    <label className="ga-check-row">
                      <input type="checkbox" checked={useRoom}
                        disabled={submitting || (!useRoom && atBudget)}
                        onChange={(e) => setUseRoom(e.target.checked)} />
                      <span>{t('Room / background')}</span>
                    </label>
                  ) : null}
                  {slotBudget > 0 && sourceImageUrl ? (
                    <label className="ga-check-row">
                      <input type="checkbox"
                        checked={requireSourceReference ? true : useSource}
                        disabled={submitting || !!requireSourceReference || (!useSource && atBudget)}
                        onChange={(e) => setUseSource(e.target.checked)} />
                      <span>
                        {t('Current image as reference')}
                        {requireSourceReference ? ` (${t('required')})` : ''}
                      </span>
                    </label>
                  ) : null}
                </>
              ) : null}

              {requireSourceReference && currentOption && slotBudget === 0 ? (
                <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)' }}>
                  {t('This workflow has no reference-image slot — pick a reference-capable workflow (e.g. Flux2/Qwen) so the current image can be adjusted instead of recreated.')}
                </div>
              ) : null}
              {requireSourceReference && currentOption && slotBudget > 0 && !useSource ? (
                <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)' }}>
                  {t('Enable "Current image as reference" to adjust this image.')}
                </div>
              ) : null}

              {isRegen ? (
                <>
                  <label className="ga-imagegen-label">{t('Improvement request')}</label>
                  <textarea
                    className="ga-textarea"
                    rows={2}
                    placeholder={t('What to change (optional)')}
                    value={improvement}
                    disabled={submitting || enhancing}
                    onChange={(e) => setImprovement(e.target.value)}
                  />
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm"
                    style={{ alignSelf: 'flex-start' }}
                    disabled={submitting || enhancing || !prompt.trim() || !improvement.trim()}
                    onClick={() => { void applyImprovement() }}
                    title={t('Rewrite the prompt with this change via LLM')}
                  >
                    {enhancing ? '…' : `✨ ${t('Improve prompt')}`}
                  </button>
                </>
              ) : null}

              {!hideNegative ? (
                <>
                  <label className="ga-imagegen-label">{t('Negative prompt')}</label>
                  <textarea
                    className="ga-textarea"
                    rows={2}
                    placeholder={t('What to avoid (optional)')}
                    value={negative}
                    disabled={submitting}
                    onChange={(e) => setNegative(e.target.value)}
                  />
                </>
              ) : null}

              {(isRegen || showCreateNew) ? (
                <label className="ga-check-row" style={{ marginTop: 8 }}>
                  <input
                    type="checkbox"
                    checked={createNew}
                    disabled={submitting}
                    onChange={(e) => setCreateNew(e.target.checked)}
                  />
                  <span>{t('Add as new image (keep the current one)')}</span>
                </label>
              ) : null}
              </div>
            </div>
          )}
        </div>
        <div className="ga-modal-footer">
          <button className="ga-btn" onClick={onClose} disabled={submitting}>
            {t('Cancel')}
          </button>
          <button
            className="ga-btn ga-btn-primary"
            onClick={handleSubmit}
            disabled={submitting || enhancing || !currentOption || sourceRefBlocked}
          >
            {submitting ? '…' : t('Generate')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
