import { useI18n } from '../../i18n/I18nProvider'
import { useStatHistory } from './statHistoryData'

/** One compact sparkline per stat over the recorded history. The row-by-row
 *  list lives in the Mind tab. */
export function StatHistory({ character, revision, label }: {
  character: string; revision: string; label: (key: string) => string
}) {
  const { t } = useI18n()
  const { rows, loading, error, retry } = useStatHistory(character, revision)
  const chronological = [...rows].reverse()
  const keys = [...new Set(chronological.flatMap(row => Object.keys(row.changes)))]
  return <section className="ga-section">
    <h3>{t('History')}</h3>
    {loading ? <div className="ga-loading">{t('Loading…')}</div> : error ? <div role="alert">
      {t('Could not load stat history.')} {error}{' '}
      <button type="button" className="ga-btn ga-btn-sm" onClick={retry}>{t('Retry')}</button>
    </div> : !rows.length ? <p className="ga-hint">{t('No stat changes recorded.')}</p> : <>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        {keys.map(key => {
          const samples = chronological.flatMap((row, index) => {
            const value = row.changes[key]?.new
            return typeof value === 'number' && Number.isFinite(value) ? [{ index, value }] : []
          })
          if (!samples.length) return null
          const low = Math.min(...samples.map(sample => sample.value))
          const high = Math.max(...samples.map(sample => sample.value))
          const points = samples.map(sample => ({
            x: 4 + sample.index / Math.max(1, chronological.length - 1) * 192,
            y: high === low ? 30 : 56 - (sample.value - low) / (high - low) * 52,
          }))
          return <figure key={key} style={{ margin: 0, width: 200 }}>
            <figcaption>{label(key)} ({low}–{high})</figcaption>
            <svg viewBox="0 0 200 60" width="200" height="60" role="img" aria-label={t('History for {stat}').replace('{stat}', label(key))}>
              <title>{t('History for {stat}').replace('{stat}', label(key))}</title>
              <polyline points={points.map(point => `${point.x},${point.y}`).join(' ')} fill="none" stroke="currentColor" strokeWidth="2" />
              {points.map((point, index) => <circle key={index} cx={point.x} cy={point.y} r="2" fill="currentColor" />)}
            </svg>
          </figure>
        })}
      </div>
      <p className="ga-hint">{t('The list of changes with their causes is in the Mind tab.')}</p>
    </>}
  </section>
}
