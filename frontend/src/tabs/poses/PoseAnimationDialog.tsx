import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Field } from '../../components/Field'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { generatorName } from './generatedClip'

/** One model of the pose_animation chain, as GET /poses/animations/backends lists it. */
interface AnimationBackend {
  name: string
  available: boolean
  motion_meta: { generator?: string; license?: string; max_variants?: number }
}

export interface PoseAnimationRequest {
  mode: 'entry' | 'candidate' | 'free'
  entryKey?: string
  rawText?: string
  prompt?: string
  initialText?: string
  initialHint?: string
  /** a retry preselects the model and variant count of the failed run */
  initialModel?: string
  initialVariants?: number
}

export function PoseAnimationDialog({ open, mode, entryKey, rawText, prompt,
  initialText = '', initialHint = '', initialModel = '', initialVariants, onClose, onStarted,
}: PoseAnimationRequest & {
  open: boolean
  onClose: () => void
  onStarted: (taskId: string, request: PoseAnimationRequest) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [text, setText] = useState(initialText)
  const [hint, setHint] = useState(initialHint)
  const [busy, setBusy] = useState(false)
  const [backends, setBackends] = useState<AnimationBackend[]>([])
  const [model, setModel] = useState(initialModel)
  const [variants, setVariants] = useState(initialVariants || 3)
  const firstField = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)
  const formRef = useRef<HTMLFormElement | null>(null)
  const submitting = useRef(false)
  const title = mode === 'entry' ? t('Generate animation') : t('Generate entry and animation')

  useEffect(() => {
    if (!open) return
    setText(initialText)
    setHint(initialHint)
  }, [open, mode, entryKey, rawText, initialText, initialHint])

  useEffect(() => {
    if (!open) return
    let live = true
    apiGet<{ backends: AnimationBackend[]; default_variants: number }>('/poses/animations/backends')
      .then((result) => {
        if (!live) return
        const listed = result.backends || []
        setBackends(listed)
        // A model that left the chain since the failed run falls back to Auto.
        setModel((current) => (listed.some((b) => b.name === current) ? current : ''))
        setVariants(initialVariants || result.default_variants || 3)
      })
      .catch((error) => { if (live) toast(t('Error') + ': ' + (error as Error).message, 'error') })
    return () => { live = false }
  }, [open, initialVariants, t, toast])

  // Auto runs the first usable chain entry; its limits and licence are what the
  // dialog shows until a model is picked explicitly.
  const chosen = model
    ? backends.find((b) => b.name === model)
    : backends.find((b) => b.available) || backends[0]
  const maxVariants = Math.max(1, Math.min(4, chosen?.motion_meta.max_variants || 4))
  useEffect(() => {
    if (variants > maxVariants) setVariants(maxVariants)
  }, [variants, maxVariants])

  useEffect(() => {
    if (!open) return
    const previousFocus = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    firstField.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !submitting.current) onClose()
      if (event.key === 'Tab') {
        const controls = formRef.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled)',
        )
        if (!controls?.length) {
          event.preventDefault()
          formRef.current?.focus()
          return
        }
        const first = controls[0]
        const last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKey)
      previousFocus?.focus()
    }
  }, [open, onClose])

  const submit = async () => {
    if (submitting.current || (mode === 'free' && !text.trim())) return
    submitting.current = true
    setBusy(true)
    try {
      const result = await apiPost<{ task_id: string }>('/poses/animations/generate', {
        mode,
        ...(mode === 'entry' ? { key: entryKey } : {}),
        ...(mode === 'candidate' ? { raw_text: rawText } : {}),
        ...(mode === 'free' ? { text: text.trim() } : {}),
        hint: hint.trim(),
        backend: model,
        variants,
      })
      onStarted(result.task_id, { mode, entryKey, rawText, prompt })
    } catch (error) {
      toast(t('Error') + ': ' + (error as Error).message, 'error')
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  if (!open) return null
  const close = () => { if (!submitting.current) onClose() }
  return createPortal(
    <div className="ga-modal-backdrop" onClick={close}>
      <form ref={formRef} tabIndex={-1} className="ga-modal" role="dialog" aria-modal="true" aria-label={title}
        style={{ maxWidth: 520 }} onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => { event.preventDefault(); void submit() }}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" aria-label={t('Close')}
            disabled={busy} onClick={close}>×</button>
        </div>
        <div className="ga-modal-body">
          <div className="ga-form">
            {mode === 'entry' ? <>
              <Field label={t('Key')}>
                <input className="ga-input" aria-label={t('Key')} readOnly value={entryKey || ''} />
              </Field>
              <Field label={t('Pose text')}>
                <textarea className="ga-textarea" aria-label={t('Pose text')} readOnly
                  rows={3} value={prompt || ''} />
              </Field>
            </> : mode === 'candidate' ? (
              <Field label={t('Candidate text')}>
                <textarea className="ga-textarea" aria-label={t('Candidate text')} readOnly
                  rows={3} value={rawText || ''} />
              </Field>
            ) : (
              <Field label={t('Describe the activity')}>
                <textarea className="ga-textarea" aria-label={t('Describe the activity')}
                  ref={(element) => { firstField.current = element }} required disabled={busy}
                  rows={4} value={text} onChange={(event) => setText(event.target.value)} />
              </Field>
            )}
            <Field label={t('Additional wish (optional)')}>
              <input className="ga-input" aria-label={t('Additional wish (optional)')}
                ref={(element) => { if (mode !== 'free') firstField.current = element }}
                disabled={busy} value={hint} onChange={(event) => setHint(event.target.value)} />
            </Field>
            <div style={{ display: 'flex', gap: 8 }}>
              <Field label={t('Model')}>
                <select className="ga-input" aria-label={t('Model')} disabled={busy} value={model}
                  onChange={(event) => setModel(event.target.value)}>
                  <option value="">{t('Auto (routing)')}</option>
                  {backends.map((b) => (
                    <option key={b.name} value={b.name} disabled={!b.available}>
                      {b.name}{b.motion_meta.generator ? ` (${generatorName(b.motion_meta.generator)})` : ''}
                      {b.available ? '' : ` — ${t('unavailable')}`}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('Variants')}>
                <select className="ga-input" aria-label={t('Variants')} disabled={busy} value={variants}
                  onChange={(event) => setVariants(Number(event.target.value))}>
                  {Array.from({ length: maxVariants }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="ga-form-hint">
              {chosen
                ? `${generatorName(chosen.motion_meta.generator)} · ${chosen.motion_meta.license || ''} · `
                : ''}
              {t('you pick one variant; the clip goes into the shared library')}
            </div>
          </div>
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={close}>
            {t('Cancel')}
          </button>
          <button type="submit" className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={busy || (mode === 'free' && !text.trim()) || (mode === 'entry' && !entryKey)}>
            {mode === 'entry' ? t('Generate') : t('Generate entry and animation')}
          </button>
        </div>
      </form>
    </div>, document.body,
  )
}
