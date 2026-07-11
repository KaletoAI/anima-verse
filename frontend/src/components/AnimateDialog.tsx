import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { ModelPicker, type PickerOption } from './ModelPicker'
import { apiGet } from '../lib/api'

/**
 * AnimateDialog — image→video dialog (separate from ImageGenDialog, since the
 * options differ fundamentally): an animation Service selector and a prompt
 * with an LLM "suggest" button (+ optional system-prompt / LLM override).
 *
 * The caller wires it to a concrete subject (Instagram post or gallery image):
 *  - `onSuggest({system_prompt, llm_override})` → returns a suggested prompt
 *  - `onSubmit({prompt, service})` → fires the animate request (fire-and-forget;
 *    the caller posts + polls the track_id).
 * Rendered via portal so the fixed modal escapes transformed grid panels (/play).
 * Reuses the ga-modal-* classes (loaded on /play via the game-admin CSS bundle).
 */

export interface AnimateSubmit {
  prompt: string
  service: string
  /** Optional LoRAs for gateway video aliases — ONE half of a Wan high/low
   *  pair suffices, the gateway resolves the counterpart. */
  loras?: Array<{ name: string; strength: number }>
  /** Optional video length in seconds (empty = backend default). */
  seconds?: number
}

interface AnimateService {
  id: string
  label: string
  enabled?: boolean
  /** LoRAs discovered for this video alias (gateway lora_url). */
  loras?: string[]
}

interface Props {
  open: boolean
  title: string
  sourceImageUrl: string
  defaultPrompt: string
  /** Ask the backend to suggest an animation prompt; returns the suggestion. */
  onSuggest: (opts: { system_prompt: string; llm_override: string }) => Promise<string>
  onSubmit: (payload: AnimateSubmit) => void | Promise<void>
  onClose: () => void
}

export function AnimateDialog({
  open, title, sourceImageUrl, defaultPrompt,
  onSuggest, onSubmit, onClose,
}: Props) {
  const { t } = useI18n()
  const [services, setServices] = useState<AnimateService[] | null>(null)
  const [serviceId, setServiceId] = useState('')
  const [prompt, setPrompt] = useState(defaultPrompt)
  const [llmModels, setLlmModels] = useState<string[]>([])
  // 'provider::name' entries → searchable ModelPicker options (grouped).
  const llmModelOptions: PickerOption[] = useMemo(
    () => llmModels.map((m) => {
      const [prov, name] = m.includes('::') ? m.split('::', 2) : ['', m]
      return { value: m, label: name || m, group: prov }
    }), [llmModels])
  const [llmOverride, setLlmOverride] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  // Three optional LoRA slots (gateway maximum) — offered when the selected
  // video backend discovered LoRAs via its lora_url.
  const [loraSlots, setLoraSlots] = useState<Array<{ name: string; strength: string }>>(
    [{ name: '', strength: '1.0' }, { name: '', strength: '1.0' }, { name: '', strength: '1.0' }],
  )
  const setLoraSlot = (i: number, patch: Partial<{ name: string; strength: string }>) =>
    setLoraSlots((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)))
  // Video length in seconds — empty = backend default (shown greyed).
  const [seconds, setSeconds] = useState('')

  useEffect(() => { if (open) setPrompt(defaultPrompt) }, [open, defaultPrompt])

  // Load services and the LLM list once.
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
    apiGet<{ providers?: Record<string, { models?: { name: string }[] }> }>('/characters/available-models')
      .then((d) => {
        const out: string[] = []
        for (const [prov, pd] of Object.entries(d.providers || {})) {
          for (const m of pd.models || []) out.push(`${prov}::${m.name}`)
        }
        setLlmModels(out)
      })
      .catch(() => setLlmModels([]))
  }, [open, services])

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
    setSubmitting(true)
    try {
      const loras = loraSlots
        .map((s) => ({ name: s.name, strength: parseFloat(s.strength) || 1.0 }))
        .filter((l) => l.name && l.name !== 'None')
      const secs = parseInt(seconds, 10)
      await onSubmit({ prompt: prompt.trim(), service: serviceId,
                       loras: loras.length ? loras : undefined,
                       seconds: Number.isFinite(secs) && secs > 0 ? secs : undefined })
      onClose()
    } finally {
      setSubmitting(false)
    }
  }, [serviceId, prompt, loraSlots, seconds, onSubmit, onClose])

  if (!open) return null

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !submitting) onClose() }}>
      <div className="ga-modal" role="dialog" aria-label={title} style={{ maxWidth: 560 }}>
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
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <label className="ga-imagegen-label">{t('Animation service')}</label>
              <select className="ga-input" value={serviceId} disabled={submitting}
                onChange={(e) => setServiceId(e.target.value)}>
                {services.map((s) => (
                  <option key={s.id} value={s.id} disabled={s.enabled === false}>
                    {s.label}{s.enabled === false ? ` (${t('disabled')})` : ''}
                  </option>
                ))}
              </select>

              {(() => {
                const svcLoras = services.find((s) => s.id === serviceId)?.loras || []
                if (!svcLoras.length) return null
                return (
                  <>
                    <label className="ga-imagegen-label">{t('LoRAs (optional)')}</label>
                    {loraSlots.map((s, i) => (
                      <div key={i} className="ga-form-row" style={{ gap: 8, alignItems: 'center' }}>
                        <select className="ga-input" style={{ flex: 1 }} value={s.name}
                          disabled={submitting} aria-label={`LoRA ${i + 1}`}
                          onChange={(e) => setLoraSlot(i, { name: e.target.value })}>
                          <option value="">— {t('none')} —</option>
                          {svcLoras.map((l) => <option key={l} value={l}>{l}</option>)}
                        </select>
                        <input className="ga-input" type="number" step={0.05} min={0} max={2}
                          style={{ width: 76, flex: '0 0 auto' }} value={s.strength}
                          disabled={submitting} title={t('Strength')}
                          onChange={(e) => setLoraSlot(i, { strength: e.target.value })} />
                      </div>
                    ))}
                    <div className="ga-form-hint">
                      {t('One half of a high/low pair is enough — the gateway adds the counterpart.')}
                    </div>
                  </>
                )
              })()}
              <div className="ga-form-row" style={{ gap: 8, alignItems: 'center' }}>
                <label className="ga-imagegen-label" style={{ margin: 0 }}>{t('Length (s)')}</label>
                <input className="ga-input" type="number" min={1} max={30} step={1}
                  style={{ width: 76, flex: '0 0 auto' }} value={seconds}
                  disabled={submitting} placeholder={t('default')}
                  title={t('Video length in seconds. Empty = backend default.')}
                  onChange={(e) => setSeconds(e.target.value)} />
              </div>
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
                  <ModelPicker
                    options={llmModelOptions}
                    value={llmOverride}
                    emptyLabel={t('default')}
                    placeholder={t('default')}
                    onChange={setLlmOverride}
                  />
                  <label className="ga-imagegen-label">{t('Suggest system prompt (optional)')}</label>
                  <textarea className="ga-textarea" rows={3}
                    placeholder={t('Empty = backend default')}
                    value={systemPrompt} disabled={submitting}
                    onChange={(e) => setSystemPrompt(e.target.value)} />
                </>
              ) : null}
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
