import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
import { RES_GRID, RES_MAX, RES_MIN, ratioLabel, snapResolution } from '../lib/imageSize'
import { useHelp } from '../help/HelpContext'

/**
 * Modal dialog for image-generation overrides — backend, LoRAs, prompt.
 * Pre-fills from `/world/imagegen-options`. Submit fires the
 * caller-supplied `onSubmit(payload)` and closes; the caller is
 * responsible for posting the request and refreshing the UI. The
 * server enqueues the job, so submit is fire-and-forget.
 */

interface LoraDefault {
  name: string
  strength: number
}

export interface LoraOption {
  name: string
  // Library entry whose LoRA vanished from this backend's listing — still
  // offered (the flag can be stale), rendered as "name (missing)".
  missing?: boolean
}

interface ImagegenOption {
  name: string
  label: string
  available?: boolean
  has_loras?: boolean
  lora_options?: LoraOption[] // this backend's LoRAs from the LoRA library
  ref_slot_count?: number // number of reference-image slots (0 = none)
  category?: string // 'inpaint' = only for Map-Fit/Match-Edges, not for normal renders
  // false = the backend has no negative input (distilled/guidance-free model);
  // the server folds the negative into the prompt as negations.
  supports_negative_prompt?: boolean
  // Use-case styles resolved per backend (family + model) — shown as an
  // editable prompt part when the caller sets `styleUseCase`.
  prompt_styles?: Record<string, string>
}

interface ImagegenOptionsResponse {
  options: ImagegenOption[]
  default_location?: string
}

/** Answer of POST /world/compose-preview (app/core/prompt_compose.py). */
interface ComposePreview {
  prompt?: string
  negative?: string
  warnings?: string[]
  use_case?: string
  llm_composed?: boolean
  cache_hit?: boolean
}

export interface ImageGenSubmit {
  prompt: string
  backend?: string
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
  // Reference-slot toggles (managed against the backend's ref_slot_count budget).
  use_room?: boolean
  use_source_as_reference?: boolean
  // Output resolution in pixels — only emitted when `showResolution` is on and
  // the field carries a value; otherwise the server keeps its use-case default.
  width?: number
  height?: number
  // Where the shown prompt came from (server-composed dialogs only) — the
  // render path logs it, so a dialog render is traceable in the JSONL.
  llm_composed?: boolean
  cache_hit?: boolean
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
  /**
   * Use-case key ('location' | 'map' | 'building' | 'room_model'): show the
   * use case's prompt STYLE (resolved per backend family) as an editable
   * field above the prompt — the dialog then displays the COMPLETE final
   * prompt (house rule) and submits with `prompt_settings_applied`, so the
   * server prepends nothing. Swapping the backend re-fills the style.
   */
  styleUseCase?: string
  /**
   * Server-composed prefill. The object is the POST body for
   * `/world/compose-preview` minus `backend` (the dialog fills that in): on
   * open and on every backend switch the dialog asks the server for the
   * finished prompt + negative and shows both as editable fields, plus the
   * composer's warnings. Use INSTEAD of `styleUseCase` — style, subject and
   * shape hints are then woven together server-side (app/core/prompt_compose.py),
   * by the same composer the batch path uses. Submit stays literal
   * (`prompt_settings_applied`).
   *
   * With `subject_only: true` the server answers with the bare subject
   * instead of a composed prompt (the regenerate dialog, whose prompt is a
   * literal adjustment order) — the "Compose with AI" button stays hidden.
   */
  composeRequest?: Record<string, unknown>
  /**
   * Show the optional output-resolution fields (width × height plus a live
   * aspect display). Empty fields = the server keeps its use-case/backend
   * default. Only for callers whose endpoint honours the values — today the
   * location gallery (day/night/room-model renders); map tiles stay square by
   * contract and do not get the fields.
   */
  showResolution?: boolean
  /**
   * Prefill for the resolution fields — e.g. the aspect of a room's
   * floor-plan rectangle, so a 2 × 5 room is not rendered as a square box.
   * Absent/null leaves them empty.
   */
  defaultResolution?: { width: number; height: number } | null
  /** Show a "Room / background" reference toggle (counts against the slot budget). */
  showRoomReference?: boolean
  /** Initial state of the "use current image as reference" toggle. */
  defaultUseSource?: boolean
  /**
   * Require the source image to actually be used as a reference: the chosen
   * backend must expose a reference slot (ref_slot_count > 0) and the
   * "current image as reference" toggle must be on. Otherwise the Generate
   * button is blocked with a hint to pick a reference-capable backend
   * (e.g. Flux/Qwen). Use for "adjust this image"-style regenerate, where a
   * non-reference backend would silently produce a fresh image instead.
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
   * Field visibility is opt-OUT: generic fields (backend, prompt, LoRAs, negative
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

const LORA_SLOTS = 4

export function ImageGenDialog({
  open, title, defaultPrompt, sourceImageUrl, settingsPrefix, settingsSuffix,
  styleUseCase, composeRequest,
  showResolution, defaultResolution,
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
  // Reference-slot toggles (managed against the backend's ref_slot_count budget).
  const [useRoom, setUseRoom] = useState(true)
  const [useSource, setUseSource] = useState(!!defaultUseSource)
  const [improvement, setImprovement] = useState('')
  const [negative, setNegative] = useState('')
  const [selectedChars, setSelectedChars] = useState<string[]>([])
  const [options, setOptions] = useState<ImagegenOption[] | null>(null)
  const [defaultLocationOpt, setDefaultLocationOpt] = useState<string>('')
  const [optionKey, setOptionKey] = useState<string>('') // selected backend name
  const [loraSlots, setLoraSlots] = useState<LoraDefault[]>(
    () => Array.from({ length: LORA_SLOTS }, () => ({ name: 'None', strength: 1.0 })),
  )
  const [submitting, setSubmitting] = useState(false)
  const [enhancing, setEnhancing] = useState(false)
  // Output size as TEXT: empty is a meaningful state ("keep the default"), so
  // the fields never coerce an empty input to a number.
  const [widthText, setWidthText] = useState('')
  const [heightText, setHeightText] = useState('')
  const resRatio = useMemo(
    () => ratioLabel(parseFloat(widthText), parseFloat(heightText)),
    [widthText, heightText])

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
    // With a server-composed prefill the prompt comes from compose-preview —
    // the caller's defaultPrompt would only overwrite it on every rerender.
    if (open && !composeRequest) setPrompt(defaultPrompt)
  }, [open, defaultPrompt, composeRequest])
  useEffect(() => {
    if (open) setPrefixText(settingsPrefix?.text || '')
  }, [open, settingsPrefix?.text])
  useEffect(() => {
    if (open) setSuffixText(settingsSuffix?.text || '')
  }, [open, settingsSuffix?.text])
  useEffect(() => {
    if (open) { setUseRoom(true); setUseSource(!!defaultUseSource) }
  }, [open, defaultUseSource])
  useEffect(() => {
    if (!open) return
    setWidthText(defaultResolution?.width ? String(defaultResolution.width) : '')
    setHeightText(defaultResolution?.height ? String(defaultResolution.height) : '')
  }, [open, defaultResolution?.width, defaultResolution?.height])

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

  // Load options once when dialog first opens.
  useEffect(() => {
    if (!open || options !== null) return
    apiGet<ImagegenOptionsResponse>('/world/imagegen-options')
      .then((d) => {
        setOptions(d.options || [])
        setDefaultLocationOpt(d.default_location || '')
      })
      .catch(() => setOptions([]))
  }, [open, options])

  // Selectable backends: inpaint targets belong only in the Map-Fit/Match-Edges
  // dialogs, never in the normal render selection. Available backends first,
  // offline ones keep their "(offline?)" label from the server.
  const entries = useMemo<ImagegenOption[]>(() => {
    if (!options) return []
    const list = options.filter((o) => o.category !== 'inpaint')
    return [...list.filter((o) => o.available !== false),
            ...list.filter((o) => o.available === false)]
  }, [options])

  // Pick initial entry once the list arrives (default spec may carry a
  // legacy "backend:" prefix — compare against the bare backend name).
  useEffect(() => {
    if (!entries.length || optionKey) return
    const def = defaultLocationOpt.replace(/^backend:/i, '').trim()
    let match = def ? entries.find((e) => e.name === def) : null
    // "Adjust this image" NEEDS a reference slot — preselecting a slotless
    // default would only show the blocked-submit hint. Prefer the first
    // reference-capable backend (available ones sort first) instead.
    if (requireSourceReference && (match?.ref_slot_count || 0) === 0) {
      match = entries.find((e) => (e.ref_slot_count || 0) > 0) || match
    }
    setOptionKey((match || entries[0]).name)
  }, [entries, defaultLocationOpt, optionKey, requireSourceReference])

  const currentOption = useMemo<ImagegenOption | null>(
    () => entries.find((e) => e.name === optionKey) || null, [entries, optionKey])

  // Use-case style of the CURRENT backend as an editable prompt part — the
  // final prompt is fully visible in the dialog; a backend swap re-fills the
  // text (families phrase their styles differently).
  const [styleText, setStyleText] = useState('')
  useEffect(() => {
    if (open && styleUseCase) {
      setStyleText(currentOption?.prompt_styles?.[styleUseCase] || '')
    }
  }, [open, styleUseCase, currentOption])

  // Server-composed prefill: ask the composer for the finished prompt when
  // the dialog opens and whenever the backend changes (the prompt family and
  // the resolved style depend on it). No debounce/live reload while typing —
  // the text is the user's from the first keystroke on.
  const [composeWarnings, setComposeWarnings] = useState<string[]>([])
  // Whether the shown prompt came out of the LLM stage (and from its cache) —
  // set by the use-case flag on prefill or by the "Compose with AI" button.
  const [composeLlm, setComposeLlm] = useState<{ llm: boolean; cached: boolean }>(
    { llm: false, cached: false })
  const [composing, setComposing] = useState(false)
  const composeKey = useMemo(
    () => (composeRequest ? JSON.stringify(composeRequest) : ''), [composeRequest])
  useEffect(() => {
    if (!open || !composeKey || !optionKey) return
    let dropped = false
    apiPost<ComposePreview>(
      '/world/compose-preview',
      { ...(JSON.parse(composeKey) as Record<string, unknown>), backend: optionKey },
    )
      .then((r) => {
        if (dropped) return
        setPrompt(r.prompt || '')
        setNegative(r.negative || '')
        setComposeWarnings(r.warnings || [])
        setComposeLlm({ llm: !!r.llm_composed, cached: !!r.cache_hit })
      })
      .catch(() => { if (!dropped) setComposeWarnings([]) })
    return () => { dropped = true }
  }, [open, composeKey, optionKey])

  // "Compose with AI": the same endpoint with llm=true — the LLM stage runs on
  // the mechanical result and its output lands in the (editable) prompt field.
  // The negative stays as composed; submit stays literal, no second call.
  const composeWithLlm = useCallback(async () => {
    if (!composeKey || !optionKey || composing) return
    setComposing(true)
    try {
      const r = await apiPost<ComposePreview>('/world/compose-preview', {
        ...(JSON.parse(composeKey) as Record<string, unknown>),
        backend: optionKey, llm: true,
      })
      setPrompt(r.prompt || '')
      setComposeWarnings(r.warnings || [])
      setComposeLlm({ llm: !!r.llm_composed, cached: !!r.cache_hit })
    } catch {
      /* The mechanical prompt stays in the field — nothing is lost. */
    } finally {
      setComposing(false)
    }
  }, [composeKey, optionKey, composing])

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

  // LoRA options of the CURRENT backend, from the LoRA library (selection is
  // backend-scoped; entries flagged missing stay offered, marked "(missing)").
  const backendLoras = useMemo<LoraOption[]>(() => {
    if (!currentOption || !currentOption.has_loras) return []
    return currentOption.lora_options || []
  }, [currentOption])

  // A backend switch resets picks the new backend does not offer.
  useEffect(() => {
    const offered = new Set(backendLoras.map((l) => l.name))
    setLoraSlots((prev) => {
      if (prev.every((s) => s.name === 'None' || offered.has(s.name))) return prev
      return prev.map((s) =>
        s.name === 'None' || offered.has(s.name) ? s : { name: 'None', strength: 1.0 })
    })
  }, [backendLoras])

  const handleSubmit = useCallback(async () => {
    if (!currentOption) return
    // Assemble the full prompt: style + prefix + base + suffix (all
    // editable). The server then does not re-append any config parts.
    const fullPrompt = [styleText.trim(), prefixText.trim(), prompt.trim(), suffixText.trim()]
      .filter(Boolean).join(', ')
    const payload: ImageGenSubmit = { prompt: fullPrompt }
    if (settingsPrefix || settingsSuffix || styleUseCase || composeRequest) {
      payload.prompt_settings_applied = true
    }
    if (composeLlm.llm) {
      payload.llm_composed = true
      payload.cache_hit = composeLlm.cached
    }
    // Exact backend name — backends match their own name on the server.
    payload.backend = currentOption.name
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
    if (showResolution) {
      const w = snapResolution(parseFloat(widthText))
      const h = snapResolution(parseFloat(heightText))
      if (w) payload.width = w
      if (h) payload.height = h
    }
    setSubmitting(true)
    try {
      await onSubmit(payload)
      onClose()
    } finally {
      setSubmitting(false)
    }
  }, [currentOption, prompt, prefixText, suffixText, settingsPrefix,
      settingsSuffix, styleText, styleUseCase, composeRequest, composeLlm,
      loraSlots, onSubmit, onClose,
      isRegen, showCreateNew, createNew,
      improvement, hideNegative, negative, characterOptions, selectedChars,
      showRoomReference, useRoom, sourceImageUrl, useSource,
      showResolution, widthText, heightText])

  // Reference-slot budget: how many ref images may be used (backend ref_slot_count).
  // Persons + room + current-image each consume one slot.
  const slotBudget = currentOption?.ref_slot_count || 0
  const usedSlots = selectedChars.length
    + (showRoomReference && useRoom ? 1 : 0)
    + (sourceImageUrl && useSource ? 1 : 0)
  const atBudget = slotBudget > 0 && usedSlots >= slotBudget
  // Regenerate-as-edit: the source image MUST land in a reference slot. Block
  // submit (and explain) when the chosen backend has no slot or the toggle is off.
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
              <label className="ga-imagegen-label">{t('Backend')}</label>
              <select
                className="ga-input"
                value={optionKey}
                disabled={submitting}
                onChange={(e) => setOptionKey(e.target.value)}
              >
                {entries.map((e) => (
                  <option key={e.name} value={e.name}>{e.label || e.name}</option>
                ))}
              </select>

              {showResolution ? (
                <>
                  <label className="ga-imagegen-label">{t('Output size (px)')}</label>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input
                      className="ga-input"
                      type="number"
                      min={RES_MIN}
                      max={RES_MAX}
                      step={RES_GRID}
                      style={{ width: 84 }}
                      value={widthText}
                      placeholder={t('auto')}
                      disabled={submitting}
                      aria-label={t('Width in pixels')}
                      onChange={(e) => setWidthText(e.target.value)}
                      onBlur={() => setWidthText((cur) => {
                        const v = snapResolution(parseFloat(cur))
                        return v ? String(v) : ''
                      })}
                    />
                    <span aria-hidden>×</span>
                    <input
                      className="ga-input"
                      type="number"
                      min={RES_MIN}
                      max={RES_MAX}
                      step={RES_GRID}
                      style={{ width: 84 }}
                      value={heightText}
                      placeholder={t('auto')}
                      disabled={submitting}
                      aria-label={t('Height in pixels')}
                      onChange={(e) => setHeightText(e.target.value)}
                      onBlur={() => setHeightText((cur) => {
                        const v = snapResolution(parseFloat(cur))
                        return v ? String(v) : ''
                      })}
                    />
                    {resRatio ? (
                      <span className="ga-hint" style={{ whiteSpace: 'nowrap' }}>{resRatio}</span>
                    ) : null}
                  </div>
                  <div className="ga-form-hint">
                    {t('Empty = the backend default. Snaps to 64-pixel steps, 256–2048. A long narrow room needs an image of the same shape — a square one turns it into a box.')}
                  </div>
                </>
              ) : null}

              {currentOption?.has_loras ? (
                <>
                  <label className="ga-imagegen-label">{t('LoRAs')}</label>
                  <div className="ga-imagegen-loras">
                    {loraSlots.map((slot, i) => (
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
                          {/* 'None' first (= default + deselect). */}
                          <option value="None">None</option>
                          {backendLoras.filter((l) => l.name !== 'None').map((l) => (
                            <option key={l.name} value={l.name}>
                              {l.name}{l.missing ? ` ${t('(missing)')}` : ''}
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
                    ))}
                  </div>
                </>
              ) : null}
              </div>

              <div style={{ flex: '1 1 320px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {sourceImageUrl ? (
                <img src={sourceImageUrl} alt="" style={{ maxHeight: 150, maxWidth: '100%', objectFit: 'contain', alignSelf: 'center', borderRadius: 6 }} />
              ) : null}

              {styleUseCase ? (
                <div className="ga-imagegen-settings-part">
                  <label className="ga-imagegen-label ga-imagegen-settings-label">
                    {t('From use-case style')} ({styleUseCase})
                  </label>
                  <textarea className="ga-textarea" rows={3} value={styleText}
                    disabled={submitting} onChange={(e) => setStyleText(e.target.value)} />
                </div>
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

              {composeWarnings.length ? (
                <div className="ga-form-hint" style={{ color: 'var(--warn, #e0a356)' }}>
                  <strong>{t('Prompt composer')}:</strong>
                  {composeWarnings.map((w, i) => <div key={i}>{w}</div>)}
                </div>
              ) : null}

              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <label className="ga-imagegen-label" style={{ margin: 0 }}>{t('Prompt')}</label>
                {composeRequest && !composeRequest.subject_only ? (
                  <>
                    <button
                      type="button"
                      className="ga-btn ga-btn-sm"
                      disabled={submitting || composing}
                      onClick={() => { void composeWithLlm() }}
                      title={t('Let an LLM rewrite the composed prompt into one coherent, positively exhaustive English prompt. The result stays editable.')}
                    >
                      {composing ? '…' : `✨ ${t('Compose with AI')}`}
                    </button>
                    {composeLlm.llm ? (
                      <span className="ga-hint" style={{ fontSize: '0.78em' }}>
                        {composeLlm.cached
                          ? t('LLM-composed (cached)')
                          : t('LLM-composed')}
                      </span>
                    ) : null}
                  </>
                ) : null}
              </div>
              <textarea
                className="ga-textarea"
                rows={12}
                value={prompt}
                disabled={submitting || enhancing || composing}
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
                  {t('This backend has no reference-image slot — pick a reference-capable backend (e.g. Flux/Qwen) so the current image can be adjusted instead of recreated.')}
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
                    rows={4}
                    placeholder={t('What to avoid (optional)')}
                    value={negative}
                    disabled={submitting}
                    onChange={(e) => setNegative(e.target.value)}
                  />
                  {currentOption?.supports_negative_prompt === false ? (
                    <div className="ga-form-hint">
                      {t('This backend has no negative input — these will be folded into the prompt as negations.')}
                    </div>
                  ) : null}
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
