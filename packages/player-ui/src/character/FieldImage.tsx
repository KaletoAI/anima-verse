/**
 * FieldImage — image + "Generate" button under an appearance prompt field.
 * Template-driven via the field flag `image_preview`:
 * Appearance/outfit images use the set-local expression endpoint; explicit
 * generation is a POST followed by attempt-specific read-only status polling.
 * Profile image generation retains its existing independent dialog and route.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../I18nProvider'
import { apiGet, apiPost } from '../api'
import { useToast } from '../Toast'
import { useCharacterFormHost, type FieldImageSubmit } from './CharacterFormHost'
import { useEnlarge } from '../ZoomButton'
import { useExpressionAttempt } from './useExpressionAttempt'

export function FieldImage({ character, kind }: { character: string; kind: string }) {
  const host = useCharacterFormHost()
  const { t } = useI18n()
  const { toast } = useToast()
  const enlarge = useEnlarge()
  const enc = encodeURIComponent(character)
  const [bust, setBust] = useState(1)
  const [localBusy, setBusy] = useState(false)
  const expression = useExpressionAttempt(character)
  const busy = localBusy || expression.busy
  const [profileFile, setProfileFile] = useState<string>('')
  const [genOpen, setGenOpen] = useState(false)  // Profile image: ImageGenDialog
  const [genPrompt, setGenPrompt] = useState('')  // Preloaded appearance (default prompt)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadProfile = useCallback(async () => {
    if (kind !== 'profile' || !character) return
    try {
      const d = await apiGet<{ profile_image?: string | null }>(`/characters/${enc}/images`)
      setProfileFile(d.profile_image || '')
    } catch {
      setProfileFile('')
    }
  }, [character, kind, enc])

  useEffect(() => {
    loadProfile()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [loadProfile])

  const src =
    kind === 'profile'
      ? profileFile
        ? `/characters/${enc}/images/${encodeURIComponent(profileFile)}?v=${bust}`
        : ''
      : kind === 'outfit'
        ? `/characters/${enc}/outfit-expression?fallback=default&v=${expression.contentVersion || bust}`
        : `/characters/${enc}/outfit-expression?override=1&pieces=&items=&fallback=default&v=${expression.contentVersion || bust}`

  // Poll briefly after triggering the asynchronous queued generation, refreshing
  // the image URL with a cache buster until the real image becomes available.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    let n = 0
    pollRef.current = setInterval(async () => {
      n += 1
      if (kind === 'profile') await loadProfile()
      setBust((b) => b + 1)
      if (n >= 14) {
        if (pollRef.current) clearInterval(pollRef.current)
        setBusy(false)
      }
    }, 3000)
  }, [kind, loadProfile])

  const fileRef = useRef<HTMLInputElement>(null)
  // Upload a profile image: file → /characters/{n}/images (multipart) →
  // select it as the profile image via /characters/{n}/profile-image/{filename}.
  const upload = useCallback(async (file: File) => {
    if (!file || busy) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(`/characters/${enc}/images`, { method: 'POST', body: fd, credentials: 'same-origin' })
      const d = await r.json()
      if (d?.filename) {
        await apiPost(`/characters/${enc}/profile-image/${encodeURIComponent(d.filename)}`, {})
      }
      await loadProfile()
      setBust((b) => b + 1)
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [busy, enc, loadProfile, t, toast])

  // Explicit expressions follow a frozen attempt even if the outfit changes.
  const generate = useCallback(async () => {
    if (busy) return
    await expression.start(kind === 'outfit'
      ? { force: true }
      : { override: true, pieces: {}, items: [], force: true })
  }, [busy, expression, kind])

  // Profile image: comes from the ImageGenDialog (backend/LoRAs selectable)
  // -> /generate-profile-image with the dialog params. Empty prompt =
  // server uses the appearance.
  const submitGenerate = useCallback(async (payload: FieldImageSubmit) => {
    setGenOpen(false)
    setBusy(true)
    try {
      const body: Record<string, unknown> = {
        prompt: payload.prompt,
        use_source_as_reference: !!payload.use_source_as_reference,
      }
      if (payload.backend) body.backend = payload.backend
      if (payload.loras && payload.loras.length) {
        body.loras = payload.loras.map((l) => ({ file: l.name, strength: l.strength }))
      }
      if (payload.negative_prompt) body.negative_prompt = payload.negative_prompt
      await apiPost(`/characters/${enc}/generate-profile-image`, body)
      toast(t('Generating…'))
      startPoll()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }, [enc, t, toast, startPoll])

  // Load the resolved appearance as the editable default prompt before opening
  // the profile-image dialog.
  const openProfileDialog = useCallback(async () => {
    try {
      const d = await apiGet<{ prompt?: string }>(`/characters/${enc}/profile-image-prompt`)
      setGenPrompt(d.prompt || '')
    } catch {
      setGenPrompt('')
    }
    setGenOpen(true)
  }, [enc])

  return (
    <div className="tpl-field-image">
      {src ? (
        <img
          src={src}
          alt=""
          {...enlarge({ src, alt: t('Preview') })}
          onLoad={e => { e.currentTarget.style.visibility = 'visible' }}
          onError={(e) => {
            ;(e.target as HTMLImageElement).style.visibility = 'hidden'
          }}
        />
      ) : (
        <div className="tpl-field-image-empty">{t('No image yet')}</div>
      )}
      {expression.error && <div role="alert" className="ga-form-hint">{expression.error}</div>}
      <div style={{ display: 'flex', gap: 6 }}>
        {host.renderImageDialog ? <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
          onClick={kind === 'profile' ? openProfileDialog : generate}>
          {busy ? t('Generating…') : t('Generate')}
        </button> : null}
        {kind === 'profile' ? (
          <>
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => fileRef.current?.click()}>
              {t('Upload')}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) upload(f)
                e.target.value = ''
              }}
            />
          </>
        ) : null}
      </div>
      {kind === 'profile' && genOpen ? host.renderImageDialog?.({
        prompt: genPrompt,
        character,
        sourceImageUrl: src || undefined,
        onSubmit: submitGenerate,
        onClose: () => setGenOpen(false),
      }) : null}
    </div>
  )
}
