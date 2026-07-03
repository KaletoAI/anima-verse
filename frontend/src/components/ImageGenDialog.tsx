import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet, apiPost } from '../lib/api'
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

interface ImagegenOption {
  name: string
  label: string
  available?: boolean
  has_loras?: boolean
  lora_options?: string[] // LoRA names for the backend (from the LoRA Library, endpoint-filtered)
  ref_slot_count?: number // number of reference-image slots (0 = none)
  category?: string // 'inpaint' = only for Map-Fit/Match-Edges, not for normal renders
}

interface ImagegenOptionsResponse {
  options: ImagegenOption[]
  default_location?: string
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
    const match = def ? entries.find((e) => e.name === def) : null
    setOptionKey((match || entries[0]).name)
  }, [entries, defaultLocationOpt, optionKey])

  const currentOption = useMemo<ImagegenOption | null>(
    () => entries.find((e) => e.name === optionKey) || null, [entries, optionKey])

  // Reset LoRA slots when the backend changes.
  useEffect(() => {
    if (!currentOption) return
    setLoraSlots(
      Array.from({ length: LORA_SLOTS }, () => ({ name: 'None', strength: 1.0 })),
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

  // LoRA names come straight from the backend option (LoRA Library,
  // endpoint-filtered, delivered by the server).
  const filteredLoras = useMemo(() => {
    if (!currentOption || !currentOption.has_loras) return []
    return currentOption.lora_options || []
  }, [currentOption])

  const handleSubmit = useCallback(async () => {
    if (!currentOption) return
    // Assemble the full prompt: prefix + base + suffix (all editable). The
    // server then does not re-append the independent config parts.
    const fullPrompt = [prefixText.trim(), prompt.trim(), suffixText.trim()]
      .filter(Boolean).join(', ')
    const payload: ImageGenSubmit = { prompt: fullPrompt }
    if (settingsPrefix || settingsSuffix) payload.prompt_settings_applied = true
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
    setSubmitting(true)
    try {
      await onSubmit(payload)
      onClose()
    } finally {
      setSubmitting(false)
    }
  }, [currentOption, prompt, prefixText, suffixText, settingsPrefix,
      settingsSuffix, loraSlots, onSubmit, onClose, isRegen, showCreateNew, createNew,
      improvement, hideNegative, negative, characterOptions, selectedChars,
      showRoomReference, useRoom, sourceImageUrl, useSource])

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
