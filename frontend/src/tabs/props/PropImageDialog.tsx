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
 * SINCE 2026-09-02 it renders ONE OF FOUR VIEWS (`view`). The front is the
 * historic source image; back, left and right are mesh input beside it and
 * replace nothing. The view decides which use-case style and negative are
 * prefilled (`prop` / `prop_back` / `prop_side`, resolved server-side in
 * `prompt_styles` / `prompt_negatives`) and puts its phrase in front of the
 * subject — the same words `app/core/view_prompts.py` would weave, because
 * the dialog sends the FINAL prompt. An extra view may additionally slot the
 * variant's front image as its appearance reference, where the variant has
 * one and the backend has a reference slot.
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
import { composePropPrompt, PROP_PROMPT_CONTEXT, type ImageBackendInfo,
  type PropFull, type PropSourceImage, type PropView } from './propTypes'

/** Human name of each view — the dialog title and nothing else; the
 *  wording that reaches the RENDER is `VIEW_PHRASE` below. */
const VIEW_LABEL: Record<PropView, string> = {
  front: 'Front', back: 'Back', left: 'Left', right: 'Right',
}

/** Which prop use case a view composes from — `view_prompts.view_use_case`:
 *  the front keeps `prop`, the back has its own style and negative, left and
 *  right share `prop_side` (the side itself is said in the phrase). The flat
 *  `prompt_style` is the fallback for a backend list without the per-view
 *  styles. */
const styleFor = (backend: ImageBackendInfo | undefined, view: PropView): string => {
  const key = view === 'front' ? 'prop' : view === 'back' ? 'prop_back' : 'prop_side'
  return backend?.prompt_styles?.[key] ?? backend?.prompt_style ?? ''
}

/** The negative of that same use case — same key rule, and for the front this
 *  is exactly the flat `prompt_negative`. */
const negativeFor = (backend: ImageBackendInfo | undefined, view: PropView): string => {
  const key = view === 'front' ? 'prop' : view === 'back' ? 'prop_back' : 'prop_side'
  return backend?.prompt_negatives?.[key] ?? backend?.prompt_negative ?? ''
}

/** The phrase that names the view, prepended to the subject because early
 *  tokens steer diffusion. BYTE-IDENTICAL to `_VIEW_PREFIX` in
 *  `app/core/view_prompts.py` — this dialog shows and SENDS the final prompt,
 *  so it has to weave the same words the server would; change the two
 *  together. */
const VIEW_PHRASE: Record<PropView, string> = {
  front: '',
  back: 'seen directly from behind, the rear side facing the camera',
  left: 'seen from the left side, the left flank facing the camera',
  right: 'seen from the right side, the right flank facing the camera',
}

/** Same composition rule as the create form — one shared weaver
 *  (`composePropPrompt`), so the text this dialog SENDS is the text the server
 *  would have composed for the same style and subject. The 3D-asset framing
 *  belongs to the use-case style, not to this file. The subject is the TARGET
 *  VARIANT's text (its own description, else the prop's — the server resolves
 *  an empty prompt the same way, `props.variant_description`); the prop's own
 *  description stands in until the strip has loaded, and the name is the last
 *  fallback. An extra view puts its phrase IN FRONT of that subject, exactly
 *  like `view_prompts.view_subject`. */
const composePrompt = (prop: PropFull, backend: ImageBackendInfo | undefined,
                       view: PropView, variantSubject?: string): string => {
  const subject = variantSubject || prop.description || prop.name || ''
  const phrase = VIEW_PHRASE[view]
  return composePropPrompt(styleFor(backend, view),
                           phrase ? `${phrase}, ${subject}` : subject)
}

export function PropImageDialog({ prop, variant, view, hasFront, subject,
  image, backends, onGenerate, onClose }: {
  /** null = closed. */
  prop: PropFull | null
  /** Model variant the render targets — the image belongs to the variant, so
   *  this is also whose current picture the defaults come from. */
  variant: number
  /** WHICH of the four views this render fills. The front is the historic
   *  source image; an extra view is a mesh input beside it and never replaces
   *  it. It decides the use-case style, the negative and the view phrase. */
  view: PropView
  /** Does the target variant HAVE a front image? Only then can it be slotted
   *  as the appearance reference of an extra view. */
  hasFront: boolean
  /** What THIS variant renders from: its own description where it has one,
   *  the prop's otherwise. Absent = the prop's text stands in. */
  subject?: string
  /** That variant's current record FOR THIS VIEW (absent = the view has no
   *  image yet). Its stored prompt/negative is what the dialog continues
   *  from. */
  image?: PropSourceImage
  backends: ImageBackendInfo[]
  /** `frontReference` = slot the variant's front image as the appearance
   *  reference of this render (extra views only). */
  onGenerate: (imageBackend: string, prompt: string, negative: string,
    frontReference: boolean) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const { setTopic } = useHelp()
  const [picked, setPicked] = useState('')
  const [prompt, setPrompt] = useState('')
  const [touched, setTouched] = useState(false)
  const [negative, setNegative] = useState('')
  // Extra views default to "keep the front's appearance" — that is what the
  // reference slot is for, and the text still decides which side is shown.
  const [useFront, setUseFront] = useState(true)

  // Re-arm per open: THIS VARIANT's current image keeps its backend
  // preselected, but the prompt composes fresh from the (possibly just
  // edited) description. A variant without an image yet starts on the first
  // backend — there is nothing of its own to continue from.
  useEffect(() => {
    if (!prop) return
    const known = backends.find((b) => b.name === image?.backend)
    const initial = known || backends[0]
    setPicked(initial?.name || '')
    setPrompt(composePrompt(prop, initial, view, subject))
    setTouched(false)
    setNegative(image?.negative || negativeFor(initial, view))
    setUseFront(true)
    // The VIEW is part of the identity of an open: the same variant's back
    // tile must not inherit the front's composed prompt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prop?.id, variant, view])

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
        aria-label={t('Render source image')}
        style={{ maxWidth: 520 }}>
        <div className="ga-modal-header">
          <span>
            {t('Render source image')} — {prop.name}
            {' · '}{t('Variant')} {variant + 1}
            {' · '}{t(VIEW_LABEL[view])}
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
                  if (!touched) setPrompt(composePrompt(prop, b, view, subject))
                  if (!negative.trim()) setNegative(negativeFor(b, view))
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
              {/* An extra view is meant to be the SAME object from another
                  side — the front goes into the backend's first reference
                  slot so the appearance carries over, while the text above
                  keeps deciding which side is rendered. Impossible without a
                  front image or without a slot, and then said so. */}
              {view !== 'front' ? (
                (() => {
                  const slots = backends.find((b) => b.name === picked)?.ref_slot_count || 0
                  return (
                    <label className="ga-check-row"
                      title={t('The variant’s front image goes into the backend’s first reference slot so the view keeps the same appearance. Text still decides the view.')}>
                      <input type="checkbox" checked={useFront && hasFront && slots > 0}
                        disabled={!hasFront || slots === 0}
                        onChange={(e) => setUseFront(e.target.checked)} />
                      <span>
                        {t('Use the front image as reference')}
                        {!hasFront ? ` — ${t('no front image yet')}`
                          : slots === 0 ? ` — ${t('this backend has no reference slot')}` : ''}
                      </span>
                    </label>
                  )
                })()
              ) : null}
              <span className="ga-hint">
                {view === 'front'
                  ? t('The picture belongs to this variant — only its image is replaced, and its 3D model stays until you re-mesh it with “3D from this image”.')
                  : t('This view is a mesh input beside the front image — it replaces nothing else, and it reaches the model only when you re-mesh with this view picked.')}
              </span>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
                  {t('Cancel')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
                  onClick={() => onGenerate(picked, prompt, negative,
                    view !== 'front' && useFront && hasFront)}>
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
