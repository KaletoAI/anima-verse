/** Shared portal and submission lifecycle for the slim player dialogs. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from './I18nProvider'

export function PlayerDialogFrame({ title, action, disabled, pending = false, onSubmit, onClose, children }: {
  title: string; action: string; disabled: boolean; pending?: boolean
  onSubmit: () => void | Promise<void>; onClose: () => void; children: ReactNode
}) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const submitting = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const locked = busy || pending
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !locked) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [locked, onClose])
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={() => { if (!locked) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={title}
        style={{ maxWidth: 520 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button className="ga-modal-close" aria-label={t('Close')} disabled={locked} onClick={onClose}>×</button>
        </div>
        <form className="ga-modal-body" onSubmit={async (e) => {
          e.preventDefault()
          if (disabled || locked || submitting.current) return
          submitting.current = true
          setBusy(true)
          setError('')
          try {
            await onSubmit()
            if (alive.current) onClose()
          }
          catch (err) { if (alive.current) setError(err instanceof Error ? err.message : t('Generation failed.')) }
          finally { submitting.current = false; if (alive.current) setBusy(false) }
        }}>
          <fieldset disabled={locked} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
            {children}
          </fieldset>
          {error && <div className="player-photo-hint" role="alert">{error}</div>}
          <div className="player-photo-actions">
            <button type="button" className="ga-btn" disabled={locked} onClick={onClose}>{t('Cancel')}</button>
            <button type="submit" className="player-btn-primary" disabled={disabled || locked}>
              {busy ? t('Generating…') : action}
            </button>
          </div>
        </form>
      </div>
    </div>, document.body,
  )
}
