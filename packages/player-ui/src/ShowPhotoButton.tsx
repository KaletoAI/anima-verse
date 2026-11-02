import { useRef, useState } from 'react'
import { apiPost } from './api'
import { useI18n } from './I18nProvider'
import { useToast } from './Toast'

/** Both the photo completion and own gallery use the room's image-chat path. */
export function ShowPhotoButton({ filename, onShown }: {
  filename: string
  onShown?: () => void | Promise<void>
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const show = async () => {
    if (pending.current) return
    pending.current = true
    setBusy(true)
    try {
      const result = await apiPost<{ ok: boolean }>('/play/say', { photo_filename: filename })
      if (!result.ok) throw new Error(t('Could not show the photo.'))
      toast(t('Photo shown in chat.'), 'success')
      await onShown?.()
    } catch (error) {
      toast((error as Error).message || t('Could not show the photo.'), 'error')
    } finally {
      pending.current = false
      setBusy(false)
    }
  }
  return <button type="button" className="ga-btn" disabled={busy} onClick={show}>
    {busy ? t('Sending…') : t('Show in chat')}
  </button>
}

/** Result actions live in the persistent, non-modal HUD notice. */
export function PhotoReadyActions({ filename, onOpenGallery, onShown }: {
  filename: string
  onOpenGallery?: () => void
  onShown?: () => void | Promise<void>
}) {
  const { t } = useI18n()
  return <span className="player-photo-actions">
    <ShowPhotoButton filename={filename} onShown={onShown} />
    {onOpenGallery && <button type="button" className="ga-btn" onClick={onOpenGallery}>
      {t('Open gallery')}
    </button>}
  </span>
}
