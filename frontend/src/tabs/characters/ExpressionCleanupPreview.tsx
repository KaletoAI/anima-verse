import { useEffect, useRef, useState } from 'react'
import { ApiError, apiGet, apiPost } from '../../lib/api'
import { useI18n } from '../../i18n/I18nProvider'

interface CleanupFile { file: string; action: 'keep' | 'adopt' | 'remove' | 'review'; reason: string; target?: string }
interface CleanupPreview { revision: string; counts: Record<CleanupFile['action'], number>; files: CleanupFile[] }

export function ExpressionCleanupPreview({ character, onChanged }: { character: string; onChanged: () => Promise<void> }) {
  const { t } = useI18n()
  const [preview, setPreview] = useState<CleanupPreview | null>(null)
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')
  const generation = useRef(0)
  const base = `/characters/${encodeURIComponent(character)}`
  useEffect(() => {
    generation.current += 1
    setPreview(null); setArmed(false); setBusy(false); setError(''); setResult('')
    return () => { generation.current += 1 }
  }, [character])
  const load = async () => {
    const current = generation.current
    setBusy(true); setArmed(false); setError(''); setResult('')
    try {
      const response = await apiGet<CleanupPreview>(`${base}/expression-cleanup`)
      if (current === generation.current) setPreview(response)
    } catch (e) { if (current === generation.current) setError((e as Error).message) }
    finally { if (current === generation.current) setBusy(false) }
  }
  const apply = async () => {
    if (!preview || busy) return
    const current = generation.current
    setBusy(true); setError('')
    try {
      const response = await apiPost<Record<string, number>>(`${base}/expression-cleanup`, { revision: preview.revision })
      if (current !== generation.current) return
      setResult(`${t('Cleanup applied')}: ${t('Adopted')} ${response.adopted}, ${t('Removed')} ${response.removed}`)
      setPreview(null); setArmed(false)
      await onChanged()
    } catch (e) {
      if (current !== generation.current) return
      setArmed(false)
      if (e instanceof ApiError && e.status === 409) {
        try {
          const refreshed = await apiGet<CleanupPreview>(`${base}/expression-cleanup`)
          if (current === generation.current) {
            setPreview(refreshed)
            setError(t('The preview changed. Review the refreshed actions before applying.'))
          }
        } catch (refreshError) {
          if (current === generation.current) {
            setPreview(null)
            setError((refreshError as Error).message)
          }
        }
      } else if (e instanceof ApiError && e.detail && typeof e.detail === 'object') {
        const detail = e.detail as { message?: string; completed?: Record<string, number> }
        setError(`${detail.message || e.message}${detail.completed ? ` — ${t('Completed operations')}: ${JSON.stringify(detail.completed)}` : ''}`)
        setPreview(null)
        await onChanged()
      } else setError((e as Error).message)
    } finally { if (current === generation.current) setBusy(false) }
  }
  const labels: Record<CleanupFile['action'], string> = { keep: t('Keep'), adopt: t('Adopt'), remove: t('Remove'), review: t('Manual review') }
  return <section className="ga-section" style={{ marginBottom: 12 }}>
    <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={() => void load()}>{t('Preview expression cleanup')}</button>
    <p className="ga-field-hint">{t('Preview does not change files. Unverified files and valid images of other outfits are retained.')}</p>
    {error && <p role="alert" style={{ color: 'var(--error)' }}>{error}</p>}
    {result && <p role="status">{result}</p>}
    {preview && <>
      <p>{Object.entries(preview.counts).map(([action, n]) => `${labels[action as CleanupFile['action']]}: ${n}`).join(' · ')}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10, maxHeight: 380, overflow: 'auto' }}>
        {preview.files.map(row => <div key={row.file} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 6 }}>
          {/\.(png|jpe?g|webp)$/i.test(row.file) && <img loading="lazy" src={`${base}/expressions/${encodeURIComponent(row.file)}?v=${preview.revision}`}
            alt={row.file} style={{ width: '100%', height: 100, objectFit: 'contain' }} />}
          <strong>{labels[row.action]}</strong>
          <div style={{ fontSize: '0.75em', overflowWrap: 'anywhere' }}>{row.file}</div>
          <p style={{ fontSize: '0.8em' }}>{row.reason}</p>
          {row.target && row.target !== row.file && <code style={{ fontSize: '0.7em', overflowWrap: 'anywhere' }}>{row.target}</code>}
        </div>)}
      </div>
      {armed ? <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span>{t('Apply exactly these adoption and removal actions?')}</span>
        <button type="button" className="ga-btn ga-btn-danger" disabled={busy} onClick={() => void apply()}>{t('Confirm cleanup')}</button>
        <button type="button" className="ga-btn" onClick={() => setArmed(false)}>{t('Cancel')}</button>
      </div> : <button type="button" className="ga-btn ga-btn-danger" style={{ marginTop: 10 }} disabled={busy || !(preview.counts.adopt + preview.counts.remove)} onClick={() => setArmed(true)}>
        {t('Apply previewed cleanup')}
      </button>}
      <button type="button" className="ga-btn" style={{ marginLeft: 8 }} disabled={busy} onClick={() => { setPreview(null); setArmed(false) }}>{t('Close preview')}</button>
    </>}
  </section>
}
