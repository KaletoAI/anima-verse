import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiPost } from '../../lib/api'
import { cleanupCounts, ACTION_LABELS, type CleanupResult } from './cleanup'

interface CleanupOptions {
  owner: string
  merge_duplicates: boolean
  set_deadlines: boolean
  end_all: boolean
}

export function CleanupDialog({ owners, ownerLabel, expiryLabel, onClose, onApplied }: {
  owners: string[]
  ownerLabel: (owner: string) => string
  expiryLabel: (stamp: string | undefined) => string
  onClose: () => void
  onApplied: (result: CleanupResult) => void
}) {
  const { t } = useI18n()
  const [options, setOptions] = useState<CleanupOptions>({
    owner: '', merge_duplicates: true, set_deadlines: true, end_all: false,
  })
  const [preview, setPreview] = useState<{ options: CleanupOptions; result: CleanupResult } | null>(null)
  const [failure, setFailure] = useState<{ options: CleanupOptions; message: string } | null>(null)
  const [applying, setApplying] = useState(false)
  const selectRef = useRef<HTMLSelectElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const result = preview?.options === options ? preview.result : null
  const error = failure?.options === options ? failure.message : null

  useEffect(() => {
    let cancelled = false
    apiPost<CleanupResult>('/intents/cleanup', { ...options, dry_run: true })
      .then((data) => { if (!cancelled) setPreview({ options, result: data }) })
      .catch((e: Error) => { if (!cancelled) setFailure({ options, message: e.message }) })
    return () => { cancelled = true }
  }, [options])

  useEffect(() => {
    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    selectRef.current?.focus()
    return () => {
      document.body.style.overflow = previousOverflow
      if (previousFocus instanceof HTMLElement) previousFocus.focus()
    }
  }, [])

  async function apply() {
    if (!result || error || applying) return
    setApplying(true)
    try {
      const data = await apiPost<CleanupResult>('/intents/cleanup', { ...options, dry_run: false })
      onApplied(data)
    } catch (e) {
      setFailure({ options, message: (e as Error).message })
    } finally {
      setApplying(false)
    }
  }

  return createPortal(
    <div className="ga-modal-backdrop" onClick={() => { if (!applying) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Clean up…')}
        ref={dialogRef} style={{ maxWidth: 760 }} onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && !applying) onClose()
          if (e.key === 'Tab') {
            const elements = dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), input:not(:disabled)')
            const first = elements?.[0]
            const last = elements?.[elements.length - 1]
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
          }
        }}>
        <div className="ga-modal-header">
          <span>{t('Clean up…')}</span>
          <button type="button" className="ga-modal-close" aria-label={t('Close')}
            disabled={applying} onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          <fieldset disabled={applying} style={{ border: 0, padding: 0, margin: 0 }}>
            <label className="ga-sched-field">
              {t('Character')}
              <select className="ga-input" ref={selectRef} value={options.owner}
                onChange={(e) => setOptions({ ...options, owner: e.target.value, end_all: e.target.value ? options.end_all : false })}>
                <option value="">{t('All characters')}</option>
                {owners.map((owner) => <option key={owner} value={owner}>{ownerLabel(owner)}</option>)}
              </select>
            </label>
            <label style={{ display: 'block', marginTop: 8 }}>
              <input type="checkbox" checked={options.merge_duplicates} disabled={options.end_all}
                onChange={(e) => setOptions({ ...options, merge_duplicates: e.target.checked })} />
              {t('Merge duplicate titles')}
            </label>
            <label style={{ display: 'block', marginTop: 8 }}>
              <input type="checkbox" checked={options.set_deadlines} disabled={options.end_all}
                onChange={(e) => setOptions({ ...options, set_deadlines: e.target.checked })} />
              {t('Give plans without a deadline one')}
            </label>
            <label style={{ display: 'block', marginTop: 8 }}>
              <input type="checkbox" checked={options.end_all} disabled={!options.owner}
                onChange={(e) => setOptions({ ...options, end_all: e.target.checked })} />
              {t('End all open plans of this character')}
            </label>
          </fieldset>
          {error ? <p role="alert">{t('Error')}: {error}</p> : !result ? <p>{t('Loading…')}</p> : <>
            <p role="status">{cleanupCounts(result, t)}</p>
            {result.items.length === 0 ? <p>{t('No plans need cleaning up.')}</p> :
              <div style={{ maxHeight: '40vh', overflow: 'auto' }}>
                <table className="ga-sched-table">
                  <thead><tr><th>{t('Title')}</th><th>{t('Character')}</th><th>{t('Action')}</th></tr></thead>
                  <tbody>{result.items.map((item) => <tr key={`${item.id}:${item.action}`}>
                    <td>{item.title || '—'}</td>
                    <td>{ownerLabel(item.owner) || '—'}</td>
                    <td>{t(ACTION_LABELS[item.action])}{item.expires_at ? `: ${expiryLabel(item.expires_at)}` : ''}</td>
                  </tr>)}</tbody>
                </table>
              </div>}
          </>}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" disabled={applying} onClick={onClose}>{t('Cancel')}</button>
          <button type="button" className={`ga-btn ga-btn-sm ${options.end_all ? 'ga-btn-danger' : 'ga-btn-primary'}`}
            disabled={applying || !result || !!error || !result.items.length} onClick={apply}>
            {applying ? t('Applying…') : t('Apply')}
          </button>
        </div>
      </div>
    </div>, document.body,
  )
}
