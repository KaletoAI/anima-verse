import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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

/** Keep the result actionable even when the host automatically hides idle chat. */
export function PhotoSavedDialog({ filename, onClose, onShown }: {
  filename: string
  onClose: () => void
  onShown?: () => void | Promise<void>
}) {
  const { t } = useI18n()
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [onClose])
  return createPortal(<div className="ga-modal-backdrop" onMouseDown={onClose}>
    <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Scene photo')}
      style={{ maxWidth: 420 }} onMouseDown={event => event.stopPropagation()}>
      <div className="ga-modal-body">
        <p>{t('Photo saved to your gallery.')}</p>
        <div className="player-photo-actions">
          <ShowPhotoButton filename={filename} onShown={async () => {
            onClose()
            await onShown?.()
          }} />
          <button type="button" className="ga-btn" onClick={onClose} autoFocus>{t('Close')}</button>
        </div>
      </div>
    </div>
  </div>, document.body)
}
