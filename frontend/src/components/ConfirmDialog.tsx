import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'

/**
 * The one confirmation dialog of the admin UI — `window.confirm` is not an
 * option here (it blocks the render loop and cannot be styled or translated).
 * Rendered via createPortal so it also works inside the /play grid layout,
 * where a modal nested in a react-grid-layout item ends up as an empty
 * floating window.
 *
 * Deliberately generic: it knows a title, a message and one confirming
 * action. Anything the caller needs to decide (what is deleted, whether the
 * action is destructive) travels in via props.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  danger,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  /** The consequence, in one or two sentences — not a repeat of the title. */
  message: string
  /** Defaults to "OK"; name the action instead ("Delete") where you can. */
  confirmLabel?: string
  /** Paints the confirming button as destructive. */
  danger?: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const { t } = useI18n()
  if (!open) return null

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div
        className="ga-modal"
        role="dialog"
        aria-label={title}
        style={{ maxWidth: 420 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          <div className="ga-hint">{message}</div>
        </div>
        <div
          className="ga-modal-footer"
          style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}
        >
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
            {t('Cancel')}
          </button>
          <button
            type="button"
            className={'ga-btn ga-btn-sm '
              + (danger ? 'ga-btn-danger' : 'ga-btn-primary')}
            onClick={onConfirm}
          >
            {confirmLabel || t('OK')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
