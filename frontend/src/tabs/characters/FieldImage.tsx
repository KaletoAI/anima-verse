/**
 * FieldImage — Bild + „Generieren"-Button unter einem Aussehen-Prompt-Feld.
 * Template-getrieben über das Feld-Flag `image_preview`:
 *   - "appearance" → Aussehen-Bild mit Default-Pose/Expression + leerem Outfit
 *     (no clothes): GET /outfit-expression?override=1&pieces=&items=
 *     (trigger=1 startet die Generierung, force=1 regeneriert).
 *   - "profile"    → Profilbild: POST /generate-profile-image.
 * Kein neues Backend — nutzt die vorhandenen Endpoints.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { ImageGenDialog, type ImageGenSubmit } from '../../components/ImageGenDialog'

export function FieldImage({ character, kind }: { character: string; kind: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [bust, setBust] = useState(1)
  const [busy, setBusy] = useState(false)
  const [profileFile, setProfileFile] = useState<string>('')
  const [genOpen, setGenOpen] = useState(false)  // Profilbild: ImageGenDialog
  const [genPrompt, setGenPrompt] = useState('')  // vorgeladene Appearance (Default-Prompt)
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
      : `/characters/${enc}/outfit-expression?override=1&pieces=&items=&fallback=default&v=${bust}`

  // Nach dem Trigger einige Sekunden nachladen (Generierung läuft async in der
  // Queue) — Bild-URL per Cache-Buster auffrischen, bis das echte Bild da ist.
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
  // Profilbild hochladen: Datei → /characters/{n}/images (multipart) → als
  // Profilbild setzen → /characters/{n}/profile-image/{filename}.
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

  // Aussehen-Bild (kind!='profile'): direkter Trigger (leeres Outfit, Default-Pose).
  const generate = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      await fetch(`/characters/${enc}/outfit-expression?override=1&trigger=1&force=1&pieces=&items=`, {
        credentials: 'same-origin',
      })
      toast(t('Generating…'))
      startPoll()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }, [busy, enc, t, toast, startPoll])

  // Profilbild: kommt aus dem ImageGenDialog (Backend/Workflow/Modell/LoRAs
  // waehlbar) -> /generate-profile-image mit den Dialog-Params. Leerer Prompt =
  // Server nimmt die Appearance.
  const submitGenerate = useCallback(async (payload: ImageGenSubmit) => {
    setGenOpen(false)
    setBusy(true)
    try {
      const body: Record<string, unknown> = { prompt: payload.prompt }
      if (payload.workflow) body.workflow = payload.workflow
      if (payload.backend) body.backend = payload.backend
      if (payload.model_override) body.model_override = payload.model_override
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

  // Profilbild-Dialog oeffnen: vorher die aufgeloeste Appearance als Default-
  // Prompt laden (editierbar im Dialog), dann oeffnen.
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
          onError={(e) => {
            ;(e.target as HTMLImageElement).style.visibility = 'hidden'
          }}
        />
      ) : (
        <div className="tpl-field-image-empty">{t('No image yet')}</div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
          onClick={kind === 'profile' ? openProfileDialog : generate}>
          {busy ? t('Generating…') : t('Generate')}
        </button>
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
      {kind === 'profile' && genOpen ? (
        <ImageGenDialog
          open
          title={t('Generate profile image')}
          defaultPrompt={genPrompt}
          onSubmit={submitGenerate}
          onClose={() => setGenOpen(false)}
        />
      ) : null}
    </div>
  )
}
