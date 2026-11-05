/**
 * PlayerPhotoDialog — the slim, player-side dialog of the 📷 scene-photo flow
 * (plan-3d-game stage 6, task 4).
 *
 * ScenePanel does not own a photo dialog: it offers the `photoDialog` slot and
 * hands in a `PhotoDialogControl`. The 3D HUD has no game-admin bundle (whose
 * `ImageGenDialog` is an authoring tool: model/LoRA/size/reference budget), so
 * it fills the slot with THIS dialog: the same flow, reduced to what a player
 * decides in the moment.
 *
 * FIELD INVENTORY — editable `ScenePhotoSubmit` fields (ScenePanel.tsx):
 *   · `prompt`          → textarea, prefilled with the distilled `ctl.prompt`
 *                         plus the optional LLM "Improve prompt" / "Check pose"
 *                         row (`PromptImprover`, rewrites the textarea in place)
 *   · `pose_check`      → "Pose check before generating" checkbox, only when
 *                         the occasion renders people; preset from its routing
 *                         switch (`backends.pose_check`), sent as an override
 *   · `character_names` → one toggle chip per name (`ctl.subjects` pre-selected)
 *   · `use_room`        → checkbox, on by default (matches the server default,
 *                         ScenePanel sends `use_room !== false`)
 *   · `negative_prompt` → one-line field, empty by default
 *   · `backend`         → select, "Auto (routing)" preselected (user request
 *                         2026-10-24). Auto sends no backend — the server
 *                         routes the "photo" occasion for the avatar with its
 *                         fallback; any other entry is an explicit pick that
 *                         renders there or nowhere. The list is
 *                         `GET /world/imagegen-options?occasion=photo`, the same
 *                         answer the admin dialog reads (already filtered to
 *                         ordinary image generators by the server).
 *   · `loras`           → four slots (name + strength) of the CURRENT
 *                         backend's LoRA-library entries — under Auto the
 *                         backend Auto resolves to. Only when that backend has
 *                         LoRAs; a backend switch clears picks it does not
 *                         offer. Sent only when anything is picked (else
 *                         null = the backend's/character's own defaults). An
 *                         explicit backend gates the picks hard (400), Auto
 *                         drops one the routed backend does not know.
 * Nothing beyond those fields belongs here; image size and the reference-slot
 * budget are admin-dialog territory. A screenshot reference may be supplied by the host.
 *
 * "NOBODY" IS NOT EXPRESSIBLE YET. An empty `character_names` reaches the
 * backend as an empty list, and `app/core/scene_photo.py` treats that as "not
 * specified" and falls back to the distiller's own subjects — i.e. deselecting
 * everyone would put back exactly the people the player removed. Until the
 * backend can tell "nobody" from "not specified" apart, this dialog refuses to
 * send an empty selection: Generate stays disabled and says why. A photo
 * genuinely without people is therefore not orderable here.
 *
 * Portal-rendered onto document.body like GiftPicker/ChatGalleryPicker: the
 * composer sits inside the HUD dock, a clipping container where a
 * position:fixed modal would clip.
 * The `.ga-modal-backdrop` class is load-bearing beyond looks — the 3D client's
 * global Esc chain (client3d/src/main.ts) skips its own handling while such a
 * backdrop is in the document, so Esc closes this dialog and nothing else.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from './I18nProvider'
import { PromptImprover, usePoseCheck } from './PromptImprover'
import { ImageBackendPicker } from './ImageBackendPicker'
import { useImageBackendPicker, type BackendOptions } from './useImageBackendPicker'
export type { BackendOptions } from './useImageBackendPicker'
import type { PhotoDialogControl, ScenePhotoSubmit } from './ScenePanel'

interface PlayerPhotoDialogProps extends PhotoDialogControl {
  title?: string
  /** Non-photo occasions resolve globally, without the avatar's photo override. */
  occasion?: 'photo' | 'scene_view'
  /** Saved scenes keep their original people and reference policy. */
  hideSceneControls?: boolean
  error?: string
  /** Prepared with the saved scene's actual references; do not re-resolve it. */
  backendOptions?: BackendOptions
}

export function PlayerPhotoDialog({
  prompt: initialPrompt,
  preparing = false,
  promptEdited = false,
  onPromptChange,
  referenceImageId,
  referenceImageUrl,
  subjects,
  available,
  avatar,
  onSubmit,
  onClose,
  title,
  occasion = 'photo',
  hideSceneControls = false,
  error,
  backendOptions,
}: PlayerPhotoDialogProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(initialPrompt)
  const edited = useRef(promptEdited)
  useEffect(() => { if (!edited.current) setPrompt(initialPrompt) }, [initialPrompt])
  const editPrompt = (value: string) => {
    edited.current = true
    setPrompt(value)
    onPromptChange?.(value)
  }
  const [negative, setNegative] = useState('')
  const [selected, setSelected] = useState<string[]>(subjects)
  useEffect(() => { setSelected(subjects) }, [subjects])
  const [useRoom, setUseRoom] = useState(true)
  const [secret, setSecret] = useState(false)
  const picker = useImageBackendPicker(occasion, avatar, backendOptions)
  const { backend, backends, mediaOff, picked } = picker
  // LLM pose check: offered when the occasion renders people, preset from its routing switch.
  const pose = usePoseCheck(backends?.pose_check)
  const [busy, setBusy] = useState(false)
  const [improving, setImproving] = useState(false)  // LLM rewrites the prompt
  const dialog = useRef<HTMLDivElement>(null)
  // A successful submit can unmount this dialog before its promise resolves.
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  // Everyone offerable: the distiller's subjects may name someone the scene
  // payload no longer lists, and dropping such a name silently would change
  // the picture without saying so. `available` keeps its order, extra subjects
  // follow.
  const names = useMemo(
    () => Array.from(new Set([...available, ...subjects])),
    [available, subjects],
  )

  // See the file head: an empty selection means "distiller's choice" to the
  // backend, not "nobody" — so it must not be sendable while there is anyone
  // to pick. With nobody offered at all the field carries no meaning and the
  // empty list is the honest payload.
  const noneSelected = !hideSceneControls && names.length > 0 && selected.length === 0

  const toggle = (name: string) =>
    setSelected((prev) => (prev.includes(name)
      ? prev.filter((x) => x !== name)
      : [...prev, name]))

  const submit = useCallback(async () => {
    if (busy || improving || !prompt.trim() || noneSelected || mediaOff) return
    setBusy(true)
    const payload: ScenePhotoSubmit = {
      prompt: prompt.trim(),
      ...(referenceImageId ? { reference_image_id: referenceImageId } : {}),
      backend,
      loras: picked.length ? picked : null,
      character_names: selected,
      use_room: useRoom,
      ...(occasion === 'photo' ? { secret } : {}),
      negative_prompt: negative.trim(),
      ...(pose.value !== undefined ? { pose_check: pose.value } : {}),
    }
    try {
      await onSubmit(payload)
    } finally {
      if (alive.current) setBusy(false)
    }
  }, [busy, improving, pose.value, referenceImageId, prompt, selected, useRoom, secret, occasion, negative, noneSelected, mediaOff, backend, picked, onSubmit])

  // Esc closes — same one-liner the Lightbox uses, and the only Esc mechanism
  // in this package. A generation in flight is not interrupted by it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, busy])

  useEffect(() => {
    if (!hideSceneControls) return
    function trapFocus(event: KeyboardEvent) {
      if (event.key !== 'Tab' || document.querySelector('.lb-overlay')) return
      const fields = dialog.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)',
      )
      if (!fields?.length) {
        event.preventDefault()
        dialog.current?.focus()
        return
      }
      const first = fields[0]
      const last = fields[fields.length - 1]
      if (!dialog.current?.contains(document.activeElement)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', trapFocus, true)
    return () => window.removeEventListener('keydown', trapFocus, true)
  }, [hideSceneControls])

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={() => { if (!busy) onClose() }}>
      <div ref={dialog} className="ga-modal" role="dialog" aria-modal="true"
        aria-label={title ? t(title) : t('Scene photo')} tabIndex={-1}
        style={{ maxWidth: 520 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{title ? t(title) : t('Scene photo')}</span>
          <button className="ga-modal-close" onClick={onClose} disabled={busy}>×</button>
        </div>
        <div className="ga-modal-body">
          {referenceImageUrl && <div style={{ marginBottom: 10 }}>
            <img src={referenceImageUrl} alt={t('Screenshot reference')}
              style={{ display: 'block', width: '100%', maxHeight: 240, objectFit: 'contain' }} />
            <div className="player-photo-hint">
              {t('The screenshot sets composition and angle; the picture follows the photo style.')}
            </div>
          </div>}
          <label className="ga-field" style={{ marginBottom: 10 }}>
            <span className="ga-field-caption">{t('Prompt')}</span>
            {/* autoFocus: without it the focus stays on the 3D canvas behind
                the modal, where Q/E/WASD keep driving the camera — the
                engine's key handling only stands down for a typing target. */}
            <textarea className="ga-input" rows={5} value={prompt} disabled={busy} autoFocus
              placeholder={preparing ? t('Describing the scene…') : undefined}
              aria-busy={preparing}
              onChange={(e) => editPrompt(e.target.value)} />
          </label>
          <PromptImprover prompt={prompt} onPrompt={editPrompt} disabled={busy}
            onBusyChange={setImproving} pose={pose} />

          {!hideSceneControls && <div className="ga-field" style={{ marginBottom: 10 }}>
            <span className="ga-field-caption">{t('Who is in the picture')}</span>
            {names.length === 0 ? (
              <div className="ga-placeholder">{t('Nobody to put in the picture.')}</div>
            ) : (
              <div className="player-photo-chips">
                {names.map((name) => (
                  <button key={name} type="button" disabled={busy}
                    className={`player-photo-chip${selected.includes(name) ? ' on' : ''}`}
                    aria-pressed={selected.includes(name)}
                    onClick={() => toggle(name)}>{name}</button>
                ))}
              </div>
            )}
            {noneSelected && (
              <div className="player-photo-hint">{t('Select at least one character.')}</div>
            )}
          </div>}

          <ImageBackendPicker picker={picker} busy={busy} />
          {!hideSceneControls && <label className="player-photo-check">
            <input type="checkbox" checked={useRoom} disabled={busy}
              onChange={(e) => setUseRoom(e.target.checked)} />
            <span>{t('Show the room around it')}</span>
          </label>}

          {occasion === 'photo' && <label className="player-photo-check">
            <input type="checkbox" checked={secret} disabled={busy}
              onChange={(e) => setSecret(e.target.checked)} />
            <span>{t('Secretly')}</span>
          </label>}

          <label className="ga-field" style={{ marginTop: 10 }}>
            <span className="ga-field-caption">{t('Negative prompt')}</span>
            <input className="ga-input" type="text" value={negative} disabled={busy}
              onChange={(e) => setNegative(e.target.value)} />
          </label>

          {error && <div className="player-photo-hint" role="alert">{error}</div>}

          <div className="player-photo-actions">
            <button type="button" className="ga-btn" onClick={onClose} disabled={busy}>
              {t('Cancel')}
            </button>
            <button type="button" className="player-btn-primary" onClick={submit}
              disabled={busy || improving || !prompt.trim() || noneSelected || mediaOff}>
              {busy ? t('Generating…') : t('Generate')}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
