/**
 * PropImageDialog — render a NEW source image for an existing prop
 * (plan-area-detail-scenes.md follow-up: images used to be regenerable only
 * as part of the whole source→mesh chain). The dialog shows the COMPLETE
 * final prompt (final-prompt rule), composed FRESH from the TARGET VARIANT's
 * current description (the prop's where the variant has none of its own, the
 * name as the last fallback) + the picked backend's use-case style — exactly
 * like the create form, so an edited description flows into the next render
 * (the OLD image's prompt stays readable in the panel caption).
 * Manual edits stick; picking another backend recomposes an untouched
 * prompt. The mesh is untouched — re-meshing from the new image is the
 * separate "3D from this image" step.
 *
 * IT DOES NOT CLOSE ON AN OUTSIDE CLICK (2026-08-24). The prompt in here is
 * written, not confirmed, and the Prompt Help panel it is meant to be written
 * with sits OUTSIDE the dialog — a backdrop that closes on any stray click
 * throws the text away mid-edit. Cancel, the × and Escape close it.
 *
 * The prompt field is a declared PROMPT field (`data-prompt-context`), so the
 * Prompt Help picks it up on focus and can write its improved version back —
 * the same recognition the surface-texture and ImageGenDialog prompts get.
 * The context tells the assistant this is img2mesh input, not a scene.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useHelp } from '../../help/HelpContext'
import { useI18n } from '../../i18n/I18nProvider'
import { PROP_PROMPT_CONTEXT, type ImageBackendInfo, type PropFull,
  type PropSourceImage } from './propTypes'

/** Same composition rule as the create form: style + subject. The subject is
 *  the TARGET VARIANT's text (its own description, else the prop's — the
 *  server resolves an empty prompt the same way, `props.variant_description`);
 *  the prop's own description stands in until the strip has loaded, and the
 *  name is the last fallback. */
const composePrompt = (prop: PropFull, backend?: ImageBackendInfo,
                       variantSubject?: string): string => {
  const subject = (variantSubject || prop.description || prop.name || '').trim()
  const style = (backend?.prompt_style || '').trim()
  return style ? (subject ? `${style}, ${subject}` : style) : subject
}

export function PropImageDialog({ prop, variant, subject, image, backends,
  onGenerate, onClose }: {
  /** null = closed. */
  prop: PropFull | null
  /** Model variant the render targets — the image belongs to the variant, so
   *  this is also whose current picture the defaults come from. */
  variant: number
  /** What THIS variant renders from: its own description where it has one,
   *  the prop's otherwise. Absent = the prop's text stands in. */
  subject?: string
  /** That variant's current image record (absent = it has none yet). */
  image?: PropSourceImage
  backends: ImageBackendInfo[]
  onGenerate: (imageBackend: string, prompt: string, negative: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const { setTopic } = useHelp()
  const [picked, setPicked] = useState('')
  const [prompt, setPrompt] = useState('')
  const [touched, setTouched] = useState(false)
  const [negative, setNegative] = useState('')

  // Re-arm per open: THIS VARIANT's current image keeps its backend
  // preselected, but the prompt composes fresh from the (possibly just
  // edited) description. A variant without an image yet starts on the first
  // backend — there is nothing of its own to continue from.
  useEffect(() => {
    if (!prop) return
    const known = backends.find((b) => b.name === image?.backend)
    const initial = known || backends[0]
    setPicked(initial?.name || '')
    setPrompt(composePrompt(prop, initial, subject))
    setTouched(false)
    setNegative(image?.negative || initial?.prompt_negative || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prop?.id, variant])

  // Escape closes — the keyboard half of "no backdrop close": the dialog is
  // still dismissable without aiming at the ×, just not by accident.
  useEffect(() => {
    if (!prop) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [prop, onClose])

  if (!prop) return null

  return createPortal(
    // No onClick on the backdrop: an outside click must NOT discard a prompt
    // that is being written (see the module header).
    <div className="ga-modal-backdrop">
      <div className="ga-modal" role="dialog"
        aria-label={t('Regenerate source image')}
        style={{ maxWidth: 520 }}>
        <div className="ga-modal-header">
          <span>
            {t('Regenerate source image')} — {prop.name}
            {' · '}{t('Variant')} {variant + 1}
          </span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          {backends.length === 0 ? (
            <div className="ga-hint">
              {t('No image backend available — configure one in Media Generation.')}
            </div>
          ) : (
            <div className="ga-form">
              <label className="ga-hint">{t('Backend')}</label>
              <select className="ga-input" value={picked}
                onChange={(e) => {
                  setPicked(e.target.value)
                  const b = backends.find((x) => x.name === e.target.value)
                  // Another backend has another style — recompose an
                  // UNTOUCHED prompt; manual edits stick. Same for the
                  // negative default.
                  if (!touched) setPrompt(composePrompt(prop, b, subject))
                  if (!negative.trim()) setNegative(b?.prompt_negative || '')
                }}>
                {backends.map((b) => (
                  <option key={b.name} value={b.name}>{b.name}</option>
                ))}
              </select>
              {/* The prompt field, declared as a PROMPT field for the Prompt
                  Help panel: `data-prompt-context` is what makes the panel
                  take the text over on focus and write its improved version
                  back, and it carries the rules a prop render must not lose
                  (img2mesh input, not a scene). `display: contents` keeps the
                  form's own spacing — the wrapper exists for the DOM lookup
                  (`el.closest(...)` in HelpContext), not for the layout. */}
              <div style={{ display: 'contents' }}
                data-help="image_prompt"
                data-prompt-context={PROP_PROMPT_CONTEXT}
                onFocusCapture={() => setTopic('image_prompt')}>
                <label className="ga-hint"
                  title={`${t('The full prompt sent to the render — composed from the backend style and THIS variant’s description (the prop’s name as the fallback). Empty = the server composes the same thing.')} ${t('Click into the field and the Prompt Help panel on the right takes it over — it improves it as an img2mesh product shot and writes the result back.')}`}>
                  {t('Final prompt (sent to the render)')}
                </label>
                <textarea className="ga-textarea" rows={4} value={prompt}
                  onChange={(e) => { setPrompt(e.target.value); setTouched(true) }} />
              </div>
              {backends.find((b) => b.name === picked)?.supports_negative_prompt === false ? (
                <span className="ga-hint">
                  {t('This backend has no negative input — negations are part of the prompt above.')}
                </span>
              ) : (
                <>
                  <label className="ga-hint">{t('Negative prompt')}</label>
                  <textarea className="ga-textarea" rows={2} value={negative}
                    onChange={(e) => setNegative(e.target.value)} />
                </>
              )}
              <span className="ga-hint">
                {t('The picture belongs to this variant — only its image is replaced, and its 3D model stays until you re-mesh it with “3D from this image”.')}
              </span>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
                  {t('Cancel')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
                  onClick={() => onGenerate(picked, prompt, negative)}>
                  🖼 {t('Render')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
