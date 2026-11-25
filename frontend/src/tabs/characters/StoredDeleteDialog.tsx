/**
 * StoredDeleteDialog — the in-app confirmation of deleting ONE stored body shape or texture body (Ruling A64): it
 * loads what the Delete would do (GET …/figure/stored/{key}/preview) and lists it — the files with their size, the
 * outfit models built on a shape, what becomes due — or, when the entry cannot be deleted, why (the figure stands
 * on it, an outfit would be built on it, a run works on it) with no Delete button. Delete runs DELETE
 * …/figure/stored/{key} (admin-only, the server checks the key's shape and keeps every path inside the character
 * folder). Used by the Figure tab's stored list (FigureStored) and the piece dialog's body switch (FitBodySwitch).
 *
 * Round 2026-11-25 (Arvid's six body shapes): `more` adds further entries — the stored list's "Delete all not
 * needed…". Every entry's preview is loaded; the confirmation sums them (files, MB, outfit models), an entry that
 * cannot be deleted any more is named and left out, and Delete removes the deletable ones one after the other.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { deleteLines, refusalText, sumPreviews } from './storedDeleteModel'
import type { StoredDeletePreview } from './storedDeleteModel'

const WARN = { color: 'var(--warning, #d29922)' }

export function StoredDeleteDialog({ character, entryKey, kind, label, more = [], onClose, onDeleted }: {
  character: string
  entryKey: string
  kind: 'shape' | 'texture'
  /** How the caller names it ("Body shape (Casual)"). */
  label: string
  /** Further entries deleted with it (the bulk Delete). */
  more?: Array<{ key: string; label: string }>
  onClose: () => void
  onDeleted: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const base = `/characters/${encodeURIComponent(character)}/figure/stored/`
  const keys = [entryKey, ...more.map((m) => m.key)]
  const keyList = keys.join('|')
  const bulk = keys.length > 1
  const [previews, setPreviews] = useState<StoredDeletePreview[] | null>(null)
  const [error, setError] = useState('')
  const [posting, setPosting] = useState(false)
  useEffect(() => {
    let gone = false
    Promise.all(keyList.split('|').map((k) => apiGet<StoredDeletePreview>(`${base}${encodeURIComponent(k)}/preview`)))
      .then((p) => { if (!gone) setPreviews(p) })
      .catch((e) => { if (!gone) setError((e as Error).message) })
    return () => { gone = true }
  }, [base, keyList])
  const deletable = (previews || []).filter((p) => p.deletable)
  const kept = (previews || []).filter((p) => !p.deletable)
  const preview = previews ? (bulk ? sumPreviews(previews) : previews[0]) : null
  const remove = async () => {
    if (posting) return
    setPosting(true)
    let done = 0
    try {
      for (const p of deletable) {
        await apiDelete(`${base}${encodeURIComponent(p.key)}`)
        done += 1
      }
      toast(bulk ? t('Deleted: {n}').replace('{n}', String(done)) : t('Deleted'), 'success')
      onDeleted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      if (done) onDeleted()
      else setPosting(false)
    }
  }
  const title = bulk ? t('Delete everything not needed now?')
    : kind === 'shape' ? t('Delete this body shape?') : t('Delete this texture body?')
  const refusal = !bulk && preview && !preview.deletable ? refusalText(preview.refusal, preview.reason, t) : ''
  const lines = preview && preview.deletable ? deleteLines(preview, t) : null
  const labelOf = (key: string) => key === entryKey ? label : more.find((m) => m.key === key)?.label || key
  return createPortal(
    <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !posting) onClose() }}>
      <div className="ga-modal" role="dialog" aria-modal="true" aria-label={title} style={{ maxWidth: 600 }}>
        <div className="ga-modal-header"><h3>{title}</h3></div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
          {bulk ? (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {deletable.map((p) => <li key={p.key}>{labelOf(p.key)} <span className="ga-hint"
                style={{ fontFamily: 'monospace' }}>{p.key}</span></li>)}
            </ul>
          ) : <div>{label} <span className="ga-hint" style={{ fontFamily: 'monospace' }}>{entryKey}</span></div>}
          {bulk && kept.length ? (
            <div className="ga-hint" style={WARN}>{t('Kept, no longer deletable: {names}')
              .replace('{names}', kept.map((p) => `${labelOf(p.key)} (${refusalText(p.refusal, p.reason, t)})`).join('; '))}</div>
          ) : null}
          {error ? <div className="ga-hint" style={WARN}>{error}</div> : null}
          {!preview && !error ? <div className="ga-hint">{t('Loading…')}</div> : null}
          {refusal ? <div style={WARN}>{t('Not deleted')}: {refusal}</div> : null}
          {lines ? (
            <>
              <div>
                <div className="ga-form-hint">{t('Removed')}</div>
                <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>
                  {lines.removed.map((line) => <li key={line}>{line}</li>)}
                </ul>
                <div style={{ maxHeight: 150, overflow: 'auto', marginTop: 4, padding: '4px 6px', borderRadius: 4,
                  border: '1px solid var(--border, #30363d)', fontFamily: 'monospace', fontSize: 11 }}>
                  {(bulk ? deletable.flatMap((p) => p.files.map((f) => `${p.key}: ${f}`)) : preview?.files ?? [])
                    .map((f) => <div key={f}>{f}</div>)}
                </div>
              </div>
              <div>
                <div className="ga-form-hint">{t('Becomes due')}</div>
                <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>
                  {lines.due.map((line) => <li key={line}>{line}</li>)}
                </ul>
              </div>
              <div className="ga-hint" style={WARN}>{t('This cannot be undone.')}</div>
            </>
          ) : null}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
          <button type="button" className="ga-btn" disabled={posting} onClick={onClose}>
            {preview && !preview.deletable ? t('Close') : t('Cancel')}
          </button>
          {preview && !preview.deletable ? null : (
            <button type="button" className="ga-btn ga-btn-danger" disabled={!preview || posting}
              onClick={() => { void remove() }}>{posting ? t('Deleting…') : t('Delete')}</button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
