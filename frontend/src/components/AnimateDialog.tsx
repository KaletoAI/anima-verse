import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

/**
 * AnimateDialog — image→video dialog (separate from ImageGenDialog, since the
 * options differ fundamentally): an animation Service (comfy/together), a
 * prompt with an LLM "suggest" button (+ optional system-prompt / LLM override),
 * and — for ComfyUI — High-Noise + Low-Noise LoRA slots filtered to WAN*.
 *
 * The caller wires it to a concrete subject (Instagram post or gallery image):
 *  - `onSuggest({system_prompt, llm_override})` → returns a suggested prompt
 *  - `onSubmit({prompt, service, loras_high, loras_low})` → fires the animate
 *    request (fire-and-forget; the caller posts + polls the track_id).
 * Rendered via portal so the fixed modal escapes transformed grid panels (/play).
 * Reuses the ga-modal-* classes (loaded on /play via the game-admin CSS bundle).
 */

export interface AnimateLora {
  name: string
  strength: number
}

export interface AnimateSubmit {
  prompt: string
  service: string
  loras_high: AnimateLora[] | null
  loras_low: AnimateLora[] | null
}

interface AnimateService {
  id: string
  label: string
  enabled?: boolean
  has_loras?: boolean
  default_loras_high?: AnimateLora[]
  default_loras_low?: AnimateLora[]
}

interface Props {
  open: boolean
  title: string
  sourceImageUrl: string
  defaultPrompt: string
  /** Character whose saved animate LoRAs to load (empty = none). */
  characterName?: string
  /** Ask the backend to suggest an animation prompt; returns the suggestion. */
  onSuggest: (opts: { system_prompt: string; llm_override: string }) => Promise<string>
  onSubmit: (payload: AnimateSubmit) => void | Promise<void>
  onClose: () => void
}

const LORA_SLOTS = 4
const emptySlots = (): AnimateLora[] =>
  Array.from({ length: LORA_SLOTS }, () => ({ name: 'None', strength: 1.0 }))

function fillSlots(src?: AnimateLora[] | null): AnimateLora[] {
  return Array.from({ length: LORA_SLOTS }, (_, i) => ({
    name: src?.[i]?.name || 'None',
    strength: src?.[i]?.strength ?? 1.0,
  }))
}

export function AnimateDialog({
  open, title, sourceImageUrl, defaultPrompt, characterName,
  onSuggest, onSubmit, onClose,
}: Props) {
  const { t } = useI18n()
  const [services, setServices] = useState<AnimateService[] | null>(null)
  const [serviceId, setServiceId] = useState('')
  const [allLoras, setAllLoras] = useState<string[]>([])
  const [lorasHigh, setLorasHigh] = useState<AnimateLora[]>(emptySlots)
  const [lorasLow, setLorasLow] = useState<AnimateLora[]>(emptySlots)
  const [prompt, setPrompt] = useState(defaultPrompt)
  const [llmModels, setLlmModels] = useState<string[]>([])
  const [llmOverride, setLlmOverride] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => { if (open) setPrompt(defaultPrompt) }, [open, defaultPrompt])

  // Load services, WAN LoRAs, saved per-character LoRAs and LLM list once.
  useEffect(() => {
    if (!open || services !== null) return
    apiGet<AnimateService[]>('/characters/animate/services')
      .then((list) => {
        const arr = Array.isArray(list) ? list : []
        setServices(arr)
        const first = arr.find((s) => s.enabled) || arr[0]
        if (first) setServiceId(first.id)
      })
      .catch(() => setServices([]))
    apiGet<{ loras?: string[] }>('/characters/animate/available-loras')
      .then((d) => setAllLoras(d.loras || ['None']))
      .catch(() => setAllLoras(['None']))
    apiGet<{ providers?: Record<string, { models?: { name: string }[] }> }>('/characters/available-models')
      .then((d) => {
        const out: string[] = []
        for (const [prov, pd] of Object.entries(d.providers || {})) {
          for (const m of pd.models || []) out.push(`${prov}::${m.name}`)
        }
        setLlmModels(out)
      })
      .catch(() => setLlmModels([]))
    if (characterName) {
      apiGet<{ loras_high?: AnimateLora[]; loras_low?: AnimateLora[] }>(
        `/characters/${encodeURIComponent(characterName)}/animate/loras`,
      )
        .then((d) => {
          if (d.loras_high) setLorasHigh(fillSlots(d.loras_high))
          if (d.loras_low) setLorasLow(fillSlots(d.loras_low))
        })
        .catch(() => { /* keep defaults */ })
    }
  }, [open, services, characterName])

  const currentService = useMemo<AnimateService | null>(
    () => services?.find((s) => s.id === serviceId) || null,
    [services, serviceId],
  )

  // When switching to a service and no saved LoRAs were applied, seed from the
  // service defaults (only if the current slots are still empty).
  useEffect(() => {
    if (!currentService) return
    const stillEmpty = (slots: AnimateLora[]) => slots.every((s) => s.name === 'None')
    if (currentService.default_loras_high && stillEmpty(lorasHigh)) {
      setLorasHigh(fillSlots(currentService.default_loras_high))
    }
    if (currentService.default_loras_low && stillEmpty(lorasLow)) {
      setLorasLow(fillSlots(currentService.default_loras_low))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentService])

  // ESC closes; lock body scroll.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !submitting) onClose() }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [open, submitting, onClose])

  const doSuggest = useCallback(async () => {
    setSuggesting(true)
    try {
      const s = await onSuggest({ system_prompt: systemPrompt.trim(), llm_override: llmOverride.trim() })
      if (s) setPrompt(s)
    } finally {
      setSuggesting(false)
    }
  }, [onSuggest, systemPrompt, llmOverride])

  const handleSubmit = useCallback(async () => {
    if (!serviceId) return
    const active = (slots: AnimateLora[]) => {
      const a = slots.filter((l) => l.name && l.name !== 'None')
      return a.length ? a : null
    }
    const payload: AnimateSubmit = {
      prompt: prompt.trim(),
      service: serviceId,
      loras_high: currentService?.has_loras ? active(lorasHigh) : null,
      loras_low: currentService?.has_loras ? active(lorasLow) : null,
    }
    setSubmitting(true)
    try {
      await onSubmit(payload)
      onClose()
    } finally {
      setSubmitting(false)
    }
  }, [serviceId, prompt, currentService, lorasHigh, lorasLow, onSubmit, onClose])

  if (!open) return null

  const renderLoraGroup = (label: string, slots: AnimateLora[], set: (s: AnimateLora[]) => void) => (
    <>
      <label className="ga-imagegen-label">{label}</label>
      <div className="ga-imagegen-loras">
        {slots.map((slot, i) => {
          const choices = slot.name && slot.name !== 'None' && !allLoras.includes(slot.name)
            ? [slot.name, ...allLoras] : allLoras
          return (
            <div key={i} className="ga-imagegen-lora-row">
              <span className="ga-imagegen-lora-label">LoRA {i + 1}</span>
              <select
                className="ga-input"
                value={slot.name}
                disabled={submitting}
                onChange={(e) => set(slots.map((s, idx) => (idx === i ? { ...s, name: e.target.value } : s)))}
              >
                {choices.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
              <input
                type="number"
                className="ga-input ga-imagegen-lora-strength"
                min={-2} max={2} step={0.05}
                disabled={submitting || slot.name === 'None'}
                value={slot.strength}
                onChange={(e) => set(slots.map((s, idx) =>
                  idx === i ? { ...s, strength: parseFloat(e.target.value) || 0 } : s))}
              />
            </div>
          )
        })}
      </div>
    </>
  )

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !submitting) onClose() }}>
      <div className="ga-modal" role="dialog" aria-label={title} style={{ maxWidth: 820 }}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button className="ga-modal-close" onClick={onClose} disabled={submitting} aria-label={t('Close')}>×</button>
        </div>
        <div className="ga-modal-body">
          {!services ? (
            <div className="ga-loading">{t('Loading…')}</div>
          ) : !services.length ? (
            <div className="ga-form-hint">{t('No animation services available.')}</div>
          ) : (
            // Two columns: left = service + LoRAs, right = image + prompt.
            // flex-wrap collapses to one column on a narrow dialog.
            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 320px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <label className="ga-imagegen-label">{t('Animation service')}</label>
                <select className="ga-input" value={serviceId} disabled={submitting}
                  onChange={(e) => setServiceId(e.target.value)}>
                  {services.map((s) => (
                    <option key={s.id} value={s.id} disabled={s.enabled === false}>
                      {s.label}{s.enabled === false ? ` (${t('disabled')})` : ''}
                    </option>
                  ))}
                </select>
                {currentService?.has_loras ? (
                  <>
                    {renderLoraGroup(t('LoRAs — High Noise'), lorasHigh, setLorasHigh)}
                    {renderLoraGroup(t('LoRAs — Low Noise'), lorasLow, setLorasLow)}
                  </>
                ) : null}
              </div>

              <div style={{ flex: '1 1 320px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {sourceImageUrl ? (
                  <img src={sourceImageUrl} alt="" style={{ maxHeight: 170, maxWidth: '100%', objectFit: 'contain', alignSelf: 'center', borderRadius: 6 }} />
                ) : null}
                <label className="ga-imagegen-label">{t('Animation prompt')}</label>
                <textarea className="ga-textarea" rows={5} value={prompt} disabled={submitting}
                  onChange={(e) => setPrompt(e.target.value)} />
                <div className="ga-form-row" style={{ gap: 8 }}>
                  <button type="button" className="ga-btn ga-btn-sm" disabled={suggesting || submitting} onClick={doSuggest}>
                    {suggesting ? t('Suggesting…') : '✨ ' + t('Suggest prompt')}
                  </button>
                  <button type="button" className="ga-btn ga-btn-sm" onClick={() => setShowAdvanced((v) => !v)}>
                    {showAdvanced ? '▾' : '▸'} {t('Advanced')}
                  </button>
                </div>
                {showAdvanced ? (
                  <>
                    <label className="ga-imagegen-label">{t('Suggest LLM (optional)')}</label>
                    <select className="ga-input" value={llmOverride} disabled={submitting}
                      onChange={(e) => setLlmOverride(e.target.value)}>
                      <option value="">— {t('default')} —</option>
                      {llmModels.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                    <label className="ga-imagegen-label">{t('Suggest system prompt (optional)')}</label>
                    <textarea className="ga-textarea" rows={3}
                      placeholder={t('Empty = backend default')}
                      value={systemPrompt} disabled={submitting}
                      onChange={(e) => setSystemPrompt(e.target.value)} />
                  </>
                ) : null}
              </div>
            </div>
          )}
        </div>
        <div className="ga-modal-footer">
          <button className="ga-btn" onClick={onClose} disabled={submitting}>{t('Cancel')}</button>
          <button className="ga-btn ga-btn-primary" onClick={handleSubmit} disabled={submitting || !serviceId || !prompt.trim()}>
            {submitting ? '…' : '🎬 ' + t('Animate')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
