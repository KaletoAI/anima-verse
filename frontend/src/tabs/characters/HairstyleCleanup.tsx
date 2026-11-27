/**
 * "Clean up hairstyles (n)" under the character list's header. Hairstyles are items that no item list shows (they are
 * managed in Characters → Figure → Hairstyles); deleting a character deletes its hairstyles with it
 * (`hairstyle_delete.delete_owned_items`), so what this button finds is what an older deletion or a failed delete
 * left, plus exact copies. It appears only when the world has unneeded hairstyles (GET /characters/hairstyle-cleanup,
 * `hairstyle_sweep.unneeded`: worn by nobody, in no outfit set, referenced nowhere, and either their owner no longer
 * exists or they are an exact copy — same text, mode and settings — of a kept hairstyle of the same owner). Its
 * confirmation names each one, then POST /characters/hairstyle-cleanup removes them with their files. Nothing runs on
 * its own. `rosterKey` changes when the roster does (a character deleted), and the list is read again then.
 */
import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { WARN_STYLE } from './garmentStyle'

type UnneededHairstyle = {
  item_id: string; owner: string; name: string; mode: string; reason: string; kept: string; kept_name: string
}
type CleanupReport = { removed: Array<{ deleted_files: number }>; skipped: Array<{ item_id: string; why: string }> }

export function HairstyleCleanupButton({ rosterKey }: { rosterKey: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [unneeded, setUnneeded] = useState<UnneededHairstyle[]>([])
  const [open, setOpen] = useState(false)
  const [posting, setPosting] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ unneeded?: UnneededHairstyle[] }>('/characters/hairstyle-cleanup')
      setUnneeded(d.unneeded || [])
    } catch {
      // The button only appears with something to clean up; an unreadable list offers nothing.
      setUnneeded([])
    }
  }, [])
  useEffect(() => { void load() }, [load, rosterKey])

  const run = async () => {
    if (posting) return
    setPosting(true)
    try {
      const report = await apiPost<CleanupReport>('/characters/hairstyle-cleanup', {})
      const files = report.removed.reduce((n, r) => n + (r.deleted_files || 0), 0)
      toast(t('{n} hairstyle(s) removed, {files} file(s).').replace('{n}', String(report.removed.length))
        .replace('{files}', String(files)), 'success')
      if (report.skipped.length) {
        toast(t('Kept for now: {list}').replace('{list}',
          report.skipped.map((s) => `${s.item_id} (${s.why})`).join('; ')), 'info')
      }
      setOpen(false)
      void load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setPosting(false)
    }
  }

  if (!unneeded.length) return null
  return (
    <div style={{ marginBottom: 8 }}>
      <button type="button" className="ga-btn ga-btn-sm"
        title={t('Removes hairstyles nobody needs: ones of deleted characters and exact copies — asks first')}
        onClick={() => setOpen(true)}>
        {t('Clean up hairstyles ({n})').replace('{n}', String(unneeded.length))}
      </button>
      {open ? createPortal(
        <div className="ga-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !posting) setOpen(false) }}>
          <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Clean up hairstyles')}
            style={{ maxWidth: 560 }}>
            <div className="ga-modal-header"><h3>{t('Clean up hairstyles')}</h3></div>
            <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
              <div>{t('These hairstyles are worn by nobody, in no outfit set and referenced nowhere:')}</div>
              <ul style={{ margin: 0, paddingLeft: 18, maxHeight: 320, overflowY: 'auto' }}>
                {unneeded.map((u) => (
                  <li key={u.item_id}>
                    {u.name} <span className="ga-hint">({u.mode})</span>
                    <span className="ga-hint"> — {u.reason === 'orphan'
                      ? (u.owner ? t('owner {name} no longer exists').replace('{name}', u.owner) : t('no owner'))
                      : t('{owner}: copy of “{name}”').replace('{owner}', u.owner)
                        .replace('{name}', u.kept_name || u.kept)}</span>
                  </li>
                ))}
              </ul>
              <div className="ga-hint" style={WARN_STYLE}>
                {t('Each goes with its files, like its Delete. Runs no job and no Build. This cannot be undone.')}
              </div>
            </div>
            <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
              <button type="button" className="ga-btn" disabled={posting} onClick={() => setOpen(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-danger" disabled={posting}
                onClick={() => { void run() }}>{posting ? t('Deleting…') : t('Clean up')}</button>
            </div>
          </div>
        </div>,
        document.body,
      ) : null}
    </div>
  )
}
