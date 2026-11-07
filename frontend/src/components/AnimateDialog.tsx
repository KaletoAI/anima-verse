import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { ModelPicker, type PickerOption } from './ModelPicker'
import { apiGet, apiPost } from '../lib/api'
import { useEnlarge } from './ZoomButton'

/**
 * AnimateDialog — image→video dialog (separate from ImageGenDialog, since the
 * options differ fundamentally): an animation Service selector and a prompt
 * with an LLM "suggest" button (+ optional system-prompt / LLM override) and
 * the "Improvement request" row of the image dialogs (POST
 * /world/imagegen-enhance-prompt with mode "video": the LLM keeps motion,
 * camera and pacing).
 *
 * Services and their LoRAs come from ONE source, the video occasion of
 * GET /world/imagegen-options: the video backends, what "Auto (routing)"
 * resolves to, and per backend `has_loras` + its LoRA-library entries — the
 * LoRA slots show only for a backend that takes LoRAs.
 *
 * The caller wires it to a concrete subject (Instagram post or gallery image):
 *  - `onSuggest({system_prompt, llm_override})` → returns a suggested prompt
 *  - `onSubmit({prompt, service?})` → fires the animate request (fire-and-forget;
 *    the caller posts + polls the track_id).
 * The preselected service entry is "Auto (routing)": it sends NO `service`, so
 * the server renders on the "video" chain of the image routing (with fallback
 * + marker). A concrete pick sends `service` — explicit, that backend or an error.
 * Rendered via portal so the fixed modal escapes transformed grid panels (/play).
 * Reuses the ga-modal-* classes (loaded on /play via the game-admin CSS bundle).
 */

export interface AnimateSubmit {
  prompt: string
  /** Absent = "Auto (routing)" (the server routes the video occasion). */
  service?: string
  /** Optional LoRAs for gateway video aliases — ONE half of a Wan high/low
   *  pair suffices, the gateway resolves the counterpart. */
  loras?: Array<{ name: string; strength: number }>
  /** Optional video length in seconds (empty = backend default). */
  seconds?: number
}

/** One video-backend row of GET /world/imagegen-options?occasion=video. */
interface AnimateService {
  name: string
  /** Server label — "(offline?)" appended for an unreachable backend. */
  label?: string
  available?: boolean
  /** The backend takes LoRAs at all; only then are `lora_options` offered. */
  has_loras?: boolean
  /** This video alias' LoRAs from the LoRA library (backend-scoped; entries
   *  flagged missing stay offered, rendered as "name (missing)"). */
  lora_options?: Array<{ name: string; missing?: boolean }>
}

interface VideoOptions {
  options?: AnimateService[]
  resolved?: string | null
  media_generation_enabled?: boolean
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

// Service-select value of "Auto (routing)" — never a backend name.
const AUTO = '__auto__'

export function AnimateDialog({
  open, title, sourceImageUrl, defaultPrompt,
  onSuggest, onSubmit, onClose,
}: Props) {
  const { t } = useI18n()
  const enlarge = useEnlarge()
  const [services, setServices] = useState<AnimateService[] | null>(null)
  const [serviceId, setServiceId] = useState(AUTO)
  // Video backend the "video" chain resolves to right now ('' = none).
  const [routedName, setRoutedName] = useState('')
  const [mediaOff, setMediaOff] = useState(false)
  const isAuto = serviceId === AUTO
  // Under "Auto" the LoRA offer follows the backend the chain resolves to.
  const effectiveService = isAuto ? routedName : serviceId
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
  const [improvement, setImprovement] = useState('')
  const [enhancing, setEnhancing] = useState(false)
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

  // LoRAs of the picked (or auto-resolved) backend — none when it takes none.
  const svcLoras = useMemo(() => {
    const svc = services?.find((s) => s.name === effectiveService)
    return svc?.has_loras ? svc.lora_options || [] : []
  }, [services, effectiveService])

  // A service switch resets picks the new service does not offer.
  useEffect(() => {
    const offered = new Set(svcLoras.map((l) => l.name))
    setLoraSlots((prev) => {
      if (prev.every((s) => !s.name || offered.has(s.name))) return prev
      return prev.map((s) => (!s.name || offered.has(s.name) ? s : { name: '', strength: '1.0' }))
    })
  }, [svcLoras])

  // Load services and the LLM list once.
  useEffect(() => {
    if (!open || services !== null) return
    apiGet<VideoOptions>('/world/imagegen-options?occasion=video')
      .then((d) => {
        setServices(Array.isArray(d?.options) ? d.options : [])
        setRoutedName(d?.resolved || '')
        setMediaOff(d?.media_generation_enabled === false)
        setServiceId(AUTO)
      })
      .catch(() => { setServices([]); setRoutedName('') })
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

  // "Improve": the LLM rewrites the motion prompt — from the change request,
  // or (empty request) just optimised for the video model — into the prompt
  // field (visible/editable before animating), like the image dialogs.
  const applyImprovement = useCallback(async () => {
    const base = prompt.trim()
    if (!base || enhancing) return
    setEnhancing(true)
    try {
      const res = await apiPost<{ prompt?: string }>('/world/imagegen-enhance-prompt', {
        prompt: base, improvement_request: improvement.trim(), mode: 'video',
      })
      if (res?.prompt) {
        setPrompt(res.prompt)
        setImprovement('')
      }
    } catch {
      /* Fail silently — the user can still adjust the prompt by hand. */
    } finally {
      setEnhancing(false)
    }
  }, [prompt, improvement, enhancing])

  const handleSubmit = useCallback(async () => {
    if (!effectiveService) return
    setSubmitting(true)
    try {
      const loras = loraSlots
        .map((s) => ({ name: s.name, strength: parseFloat(s.strength) || 1.0 }))
        .filter((l) => l.name && l.name !== 'None')
      const secs = parseInt(seconds, 10)
      // "Auto (routing)": no service — the server routes the video occasion.
      await onSubmit({ prompt: prompt.trim(), ...(isAuto ? {} : { service: serviceId }),
                       loras: loras.length ? loras : undefined,
                       seconds: Number.isFinite(secs) && secs > 0 ? secs : undefined })
      onClose()
    } finally {
      setSubmitting(false)
    }
  }, [effectiveService, isAuto, serviceId, prompt, loraSlots, seconds, onSubmit, onClose])

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
                <option value={AUTO}>
                  {routedName ? `${t('Auto (routing)')} → ${routedName}`
                    : t('Auto (routing) — no backend available')}
                </option>
                {services.map((s) => (
                  <option key={s.name} value={s.name}>{s.label || s.name}</option>
                ))}
              </select>
              {mediaOff ? (
                <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)' }}>
                  {t('Media generation is disabled for this world (Admin → Settings → Media Generation)')}
                </div>
              ) : null}

              {(() => {
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
                          {svcLoras.map((l) => (
                            <option key={l.name} value={l.name}>
                              {l.name}{l.missing ? ` ${t('(missing)')}` : ''}
                            </option>
                          ))}
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
                <img src={sourceImageUrl} alt=""
                  {...enlarge({ src: sourceImageUrl, alt: t('Source image') },
                    { maxHeight: 170, maxWidth: '100%', objectFit: 'contain', alignSelf: 'center', borderRadius: 6 })} />
              ) : null}
              <label className="ga-imagegen-label">{t('Animation prompt')}</label>
              <textarea className="ga-textarea" rows={5} value={prompt} disabled={submitting || enhancing}
                onChange={(e) => setPrompt(e.target.value)} />
              <label className="ga-imagegen-label">{t('Improvement request')}</label>
              <textarea className="ga-textarea" rows={2}
                placeholder={t('What to change (optional)')}
                value={improvement} disabled={submitting || enhancing}
                onChange={(e) => setImprovement(e.target.value)} />
              <div className="ga-form-row" style={{ gap: 8 }}>
                <button type="button" className="ga-btn ga-btn-sm"
                  disabled={submitting || enhancing || suggesting || !prompt.trim()}
                  onClick={() => { void applyImprovement() }}
                  title={improvement.trim()
                    ? t('Rewrite the prompt with this change via LLM')
                    : t('Optimise the prompt for the video model via LLM (content stays the same)')}>
                  {enhancing ? '…' : `✨ ${t('Improve prompt')}`}
                </button>
                <button type="button" className="ga-btn ga-btn-sm" disabled={suggesting || submitting || enhancing} onClick={doSuggest}>
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
          <button className="ga-btn ga-btn-primary" onClick={handleSubmit} disabled={submitting || enhancing || mediaOff || !effectiveService || !prompt.trim()}>
            {submitting ? '…' : '🎬 ' + t('Animate')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
