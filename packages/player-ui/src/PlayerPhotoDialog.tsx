/**
 * PlayerPhotoDialog — the slim, player-side dialog of the 📷 scene-photo flow
 * (plan-3d-game stage 6, task 4).
 *
 * ScenePanel does not own a photo dialog: it offers the `photoDialog` slot and
 * hands in a `PhotoDialogControl`. /play fills that slot with the game-admin
 * `ImageGenDialog` (model/LoRA/size/reference budget — an authoring tool). The
 * 3D HUD has no game-admin bundle, so it fills the same slot with THIS dialog:
 * the same flow, reduced to what a player decides in the moment.
 *
 * FIELD INVENTORY — `ScenePhotoSubmit` (ScenePanel.tsx) has six fields; this
 * dialog surfaces four of them and deliberately leaves two to the admin dialog:
 *   · `prompt`          → textarea, prefilled with the distilled `ctl.prompt`
 *   · `character_names` → one toggle chip per name (`ctl.subjects` pre-selected)
 *   · `use_room`        → checkbox, on by default (matches the server default,
 *                         ScenePanel sends `use_room !== false`)
 *   · `negative_prompt` → one-line field, empty by default
 *   · `backend`         → NOT offered — picking a model/backend is authoring,
 *                         omitted means the routed default
 *   · `loras`           → NOT offered — same reason (LoRA library is an admin
 *                         surface, scoped per backend)
 * Nothing beyond those fields belongs here; image size and the reference-slot
 * budget are admin-dialog territory and are not part of this payload at all.
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
 * composer sits inside a transformed layout container (react-grid-layout in
 * /play, the HUD dock in client3d) where a position:fixed modal would clip.
 * The `.ga-modal-backdrop` class is load-bearing beyond looks — the 3D client's
 * global Esc chain (client3d/src/main.ts) skips its own handling while such a
 * backdrop is in the document, so Esc closes this dialog and nothing else.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from './I18nProvider'
import type { PhotoDialogControl, ScenePhotoSubmit } from './ScenePanel'

export function PlayerPhotoDialog({
  prompt: initialPrompt,
  subjects,
  available,
  onSubmit,
  onClose,
}: PhotoDialogControl) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(initialPrompt)
  const [negative, setNegative] = useState('')
  const [selected, setSelected] = useState<string[]>(subjects)
  const [useRoom, setUseRoom] = useState(true)
  const [busy, setBusy] = useState(false)
  // The host unmounts this dialog inside its own onSubmit (ScenePanel clears
  // the prepared payload first), so the promise usually resolves after unmount.
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])

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
  const noneSelected = names.length > 0 && selected.length === 0

  const toggle = (name: string) =>
    setSelected((prev) => (prev.includes(name)
      ? prev.filter((x) => x !== name)
      : [...prev, name]))

  const submit = useCallback(async () => {
    if (busy || !prompt.trim() || noneSelected) return
    setBusy(true)
    const payload: ScenePhotoSubmit = {
      prompt: prompt.trim(),
      character_names: selected,
      use_room: useRoom,
      negative_prompt: negative.trim(),
    }
    try {
      await onSubmit(payload)
    } finally {
      if (alive.current) setBusy(false)
    }
  }, [busy, prompt, selected, useRoom, negative, noneSelected, onSubmit])

  // Esc closes — same one-liner the Lightbox uses, and the only Esc mechanism
  // in this package. A generation in flight is not interrupted by it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, busy])

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={() => { if (!busy) onClose() }}>
      <div className="ga-modal" style={{ maxWidth: 520 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Scene photo')}</span>
          <button className="ga-modal-close" onClick={onClose} disabled={busy}>×</button>
        </div>
        <div className="ga-modal-body">
          <label className="ga-field" style={{ marginBottom: 10 }}>
            <span className="ga-field-caption">{t('Prompt')}</span>
            {/* autoFocus: without it the focus stays on the 3D canvas behind
                the modal, where Q/E/WASD keep driving the camera — the
                engine's key handling only stands down for a typing target. */}
            <textarea className="ga-input" rows={5} value={prompt} disabled={busy} autoFocus
              onChange={(e) => setPrompt(e.target.value)} />
          </label>

          <div className="ga-field" style={{ marginBottom: 10 }}>
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
          </div>

          <label className="player-photo-check">
            <input type="checkbox" checked={useRoom} disabled={busy}
              onChange={(e) => setUseRoom(e.target.checked)} />
            <span>{t('Show the room around it')}</span>
          </label>

          <label className="ga-field" style={{ marginTop: 10 }}>
            <span className="ga-field-caption">{t('Negative prompt')}</span>
            <input className="ga-input" type="text" value={negative} disabled={busy}
              onChange={(e) => setNegative(e.target.value)} />
          </label>

          <div className="player-photo-actions">
            <button type="button" className="ga-btn" onClick={onClose} disabled={busy}>
              {t('Cancel')}
            </button>
            <button type="button" className="player-btn-primary" onClick={submit}
              disabled={busy || !prompt.trim() || noneSelected}>
              {busy ? t('Generating…') : t('Generate')}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
