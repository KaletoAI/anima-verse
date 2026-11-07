import { useI18n } from '../../i18n/I18nProvider'
import type { CleanupFile, ExpressionCleanup } from './useExpressionCleanup'

export function ExpressionCleanupButton({ cleanup }: { cleanup: ExpressionCleanup }) {
  const { t } = useI18n()
  return <button type="button" className="ga-btn ga-btn-sm" disabled={cleanup.busy}
    onClick={() => void cleanup.load()}>{t('Preview expression cleanup')}</button>
}

export function ExpressionCleanupPreview({ cleanup }: { cleanup: ExpressionCleanup }) {
  const { t } = useI18n()
  const { base, preview, setPreview, armed, setArmed, busy, error, result, apply } = cleanup
  const labels: Record<CleanupFile['action'], string> = { keep: t('Keep'), adopt: t('Adopt'), remove: t('Remove'), review: t('Manual review') }
  return <section className="ga-section" style={{ marginBottom: 12 }}>
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
