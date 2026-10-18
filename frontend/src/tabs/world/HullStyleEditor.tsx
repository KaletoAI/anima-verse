import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPut } from '../../lib/api'

export interface HullStyle {
  id: string
  name: string
  description: string
  origin: string
  [key: string]: unknown
}

export function HullStyleEditor({ style, onClose, onSaved }: {
  style: HullStyle
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { t } = useI18n()
  const [text, setText] = useState(() => {
    const doc: Record<string, unknown> = { ...style }
    delete doc.id
    delete doc.origin
    return JSON.stringify(doc, null, 2)
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const dialog = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    dialog.current?.focus()
    return () => previous?.focus()
  }, [])

  const save = async (reset: boolean) => {
    setBusy(true)
    setError('')
    try {
      const path = `/world/hull-styles/${encodeURIComponent(style.id)}`
      if (reset) await apiDelete(path)
      else {
        const doc: unknown = JSON.parse(text)
        if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
          setError(t('Style JSON must be an object.'))
          return
        }
        await apiPut(path, doc)
      }
      await onSaved()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={() => { if (!busy) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Edit hull style')}
        tabIndex={-1} ref={dialog} style={{ maxWidth: 760 }}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && !busy) onClose()
          if (e.key === 'Tab') {
            const controls = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea')
            if (!controls?.length) return
            const first = controls[0], last = controls[controls.length - 1]
            if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
              e.preventDefault(); last.focus()
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault(); first.focus()
            }
          }
        }}>
        <div className="ga-modal-header">
          <h3>{t('Edit hull style')}: {style.name}</h3>
          <button className="ga-modal-close" disabled={busy} onClick={onClose} aria-label={t('Close')}>×</button>
        </div>
        <div className="ga-modal-body ga-form">
          <label>{t('Style JSON')}
            <textarea className="ga-input" rows={22} value={text} disabled={busy}
              spellCheck={false} style={{ width: '100%', fontFamily: 'monospace' }}
              onChange={(e) => setText(e.target.value)} />
          </label>
          {error ? <div role="alert">{error}</div> : null}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 8 }}>
          <button className="ga-btn ga-btn-sm" disabled={busy} onClick={() => { void save(false) }}>{t('Save as world override')}</button>
          {style.origin === 'world' ? <button className="ga-btn ga-btn-sm" disabled={busy}
            onClick={() => { void save(true) }}>{t('Reset to shipped')}</button> : null}
          <button className="ga-btn ga-btn-sm" disabled={busy} onClick={onClose}>{t('Cancel')}</button>
        </div>
      </div>
    </div>, document.body,
  )
}
