/**
 * PropsPalette — the prop library as a compact picker inside the floor plan's
 * side panel. Purely presentational: it lists what /world/props holds
 * (search + category filter + thumbnail grid) and reports a click through
 * `onPick`; `armedPropId` marks the card the caller considers armed. The
 * placement itself (ghost footprint, drag, adjustment strip) is NOT here.
 *
 * The library is fetched once on mount — props change through the Props tab,
 * not while a floor plan is being edited, so a Refresh button beats a poll.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { ZoomButton } from '../../components/ZoomButton'
import type { PropFull } from '../props/propTypes'

interface PropsPaletteProps {
  /** Fires on card click — the caller decides what "picked" means. */
  onPick: (prop: PropFull) => void
  /** Card to mark as armed ('' = none). */
  armedPropId: string
}

export function PropsPalette({ onPick, armedPropId }: PropsPaletteProps) {
  const { t } = useI18n()
  const [props, setProps] = useState<PropFull[]>([])
  const [loaded, setLoaded] = useState(false)
  const [query, setQuery] = useState('')
  const [catFilter, setCatFilter] = useState('')
  // Bumped by Refresh so freshly generated thumbnails are not served stale.
  const [cacheBump, setCacheBump] = useState(0)

  const load = useCallback(() => {
    apiGet<{ props?: PropFull[] }>('/world/props')
      .then((d) => setProps(d.props || []))
      .catch(() => setProps([]))
      .finally(() => setLoaded(true))
  }, [])
  useEffect(() => { load() }, [load])

  const categories = useMemo(() => {
    const set = new Set<string>()
    for (const p of props) if (p.category) set.add(p.category)
    return Array.from(set).sort()
  }, [props])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return props.filter((p) => {
      if (catFilter && p.category !== catFilter) return false
      if (!q) return true
      return p.name.toLowerCase().includes(q)
        || (p.tags || []).some((tag) => tag.toLowerCase().includes(q))
    })
  }, [props, query, catFilter])

  return (
    <>
      <div className="ga-plan-panel-title">{t('Props')}</div>
      <div style={{ display: 'flex', gap: 4 }}>
        <input
          className="ga-input"
          style={{ flex: 1, minWidth: 0 }}
          value={query}
          placeholder={t('Search…')}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          onClick={() => { setCacheBump((b) => b + 1); load() }}
          title={t('Reload the prop library')}
        >
          ↻
        </button>
      </div>
      {categories.length ? (
        <select
          className="ga-input"
          style={{ width: '100%' }}
          value={catFilter}
          onChange={(e) => setCatFilter(e.target.value)}
        >
          <option value="">{t('All categories')}</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      ) : null}
      {!loaded ? (
        <span className="ga-hint">{t('Loading…')}</span>
      ) : !props.length ? (
        <span className="ga-hint">
          {t('The prop library is empty — the Props tab generates or uploads objects.')}
        </span>
      ) : !visible.length ? (
        <span className="ga-hint">{t('Nothing matches the filter')}</span>
      ) : (
        <div className="ga-props-palette-grid">
          {visible.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`ga-props-palette-card${p.id === armedPropId ? ' is-armed' : ''}${p.has_model ? '' : ' is-modelless'}`}
              onClick={() => onPick(p)}
              title={`${p.name}${p.category ? ` · ${p.category}` : ''}\n${p.width_m}×${p.depth_m}×${p.height_m} m`}
              style={{ position: 'relative' }}
            >
              {p.has_source ? (
                <>
                  <img
                    className="ga-props-palette-thumb"
                    alt=""
                    src={`/assets/props/${encodeURIComponent(p.id)}/source?v=${cacheBump}`}
                  />
                  <ZoomButton item={{ src: `/assets/props/${encodeURIComponent(p.id)}/source?v=${cacheBump}`, alt: p.name }} />
                </>
              ) : (
                <span className="ga-props-palette-thumb" style={{ fontSize: 22 }}>📦</span>
              )}
              <span className="ga-props-palette-name">{p.name}</span>
              <span className="ga-props-palette-dims">
                {`${p.width_m}×${p.depth_m}×${p.height_m} m`}
              </span>
              {!p.has_model ? (
                <span className="ga-source">{t('no model')}</span>
              ) : null}
            </button>
          ))}
        </div>
      )}
    </>
  )
}
