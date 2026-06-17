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

export function FieldImage({ character, kind }: { character: string; kind: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [bust, setBust] = useState(1)
  const [busy, setBusy] = useState(false)
  const [profileFile, setProfileFile] = useState<string>('')
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

  const generate = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      if (kind === 'profile') {
        await apiPost(`/characters/${enc}/generate-profile-image`, {})
      } else {
        // Override + trigger + force: leeres Outfit (no clothes), Default-Pose,
        // neu rendern. GET (Bild/202), Antwort ignorieren — danach gepollt.
        await fetch(`/characters/${enc}/outfit-expression?override=1&trigger=1&force=1&pieces=&items=`, {
          credentials: 'same-origin',
        })
      }
      toast(t('Generating…'))
      startPoll()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }, [busy, kind, enc, t, toast, startPoll])

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
      <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={generate}>
        {busy ? t('Generating…') : t('Generate')}
      </button>
    </div>
  )
}
