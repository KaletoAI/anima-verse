import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'

/**
 * The one text-input dialog of the admin UI — the counterpart of
 * `ConfirmDialog` for the cases that need a single value from the user.
 * `window.prompt` is not an option here: it is unstyled, untranslatable and
 * in some browser configurations it is suppressed entirely, which leaves the
 * user unable to perform the action at all.
 *
 * Rendered via createPortal for the same reason as ConfirmDialog, so it also
 * works inside the /play grid layout.
 *
 * Deliberately generic: it knows a title, a field label and one confirming
 * action. The empty value is never submitted (the confirming button stays
 * disabled), cancel and ESC drop the input.
 */
export function PromptDialog({
  open,
  title,
  label,
  message,
  initialValue,
  placeholder,
  confirmLabel,
  onSubmit,
  onClose,
}: {
  open: boolean
  title: string
  /** The field label — what the value means ("Name"). */
  label: string
  /** Optional one-liner above the field, where the title is not enough. */
  message?: string
  /** Prefilled value; re-applied every time the dialog opens. */
  initialValue?: string
  placeholder?: string
  /** Defaults to "OK"; name the action instead ("Create") where you can. */
  confirmLabel?: string
  /** Receives the TRIMMED value; never called with an empty string. */
  onSubmit: (value: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [value, setValue] = useState(initialValue || '')

  // Every opening starts from the caller's value — the dialog is mounted
  // permanently and would otherwise still hold the last input.
  useEffect(() => {
    if (open) setValue(initialValue || '')
  }, [open, initialValue])

  // ESC closes; lock body scroll while open.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  // Focus lands in the field: the user came here to type.
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  if (!open) return null

  const trimmed = value.trim()
  const submit = () => {
    if (!trimmed) return
    onSubmit(trimmed)
  }

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
          {message ? <div className="ga-hint">{message}</div> : null}
          <label className="ga-field-caption" style={{ display: 'block', marginTop: 6 }}>
            {label}
          </label>
          <input
            ref={inputRef}
            className="ga-input"
            style={{ width: '100%' }}
            value={value}
            placeholder={placeholder}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                submit()
              }
            }}
          />
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
            className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={!trimmed}
            onClick={submit}
          >
            {confirmLabel || t('OK')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
