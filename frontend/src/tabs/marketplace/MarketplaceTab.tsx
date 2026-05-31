import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * Marketplace — browse an online catalog of content packs and install them
 * into the current world. Catalog URL is configured in admin settings under
 * `content_marketplace.catalog_url`. Each pack carries `type` (character /
 * item / item_bundle / rule / states / location), tags, size, and an
 * optional preview image. Install streams the ZIP to the backend, which
 * dispatches to the matching importer (same code path used by the local
 * tab buttons).
 */

interface Pack {
  id: string
  type: string
  name?: string
  slug?: string
  version?: string
  size_bytes?: number
  image_count?: number
  room_count?: number
  tags?: string[]
  description?: string
  preview_image?: string
  download_url?: string
  checksum_sha256?: string
  // Only present on type=collection — the index.json may include a contents
  // list so the UI can preview what's inside without downloading the ZIP.
  contents?: Array<{ type: string; name: string }>
}

interface Catalog {
  packs: Pack[]
  configured?: boolean
  stale?: boolean
  source_url?: string
  catalog_id?: string
  catalog_name?: string
  _fetched_at?: number
}

interface CatalogRef {
  id: string
  name: string
  url: string
}

const PRETTY_TYPE: Record<string, string> = {
  character: 'Character',
  item: 'Item',
  item_bundle: 'Item Bundle',
  rule: 'Rule',
  states: 'States',
  location: 'Location',
  collection: 'Collection',
}

function formatBytes(n?: number): string {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export function MarketplaceTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [catalogs, setCatalogs] = useState<CatalogRef[]>([])
  const [activeId, setActiveId] = useState<string>('')
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [loading, setLoading] = useState(false)
  const [installing, setInstalling] = useState<string | null>(null)
  const [selected, setSelected] = useState<Pack | null>(null)
  const [filterType, setFilterType] = useState<string>('')
  const [filterTag, setFilterTag] = useState<string>('')
  const [search, setSearch] = useState<string>('')

  const load = useCallback(
    async (force: boolean, id?: string) => {
      const targetId = id ?? activeId
      setLoading(true)
      try {
        const qs = new URLSearchParams()
        if (targetId) qs.set('catalog_id', targetId)
        if (force) qs.set('force', 'true')
        const data = await apiGet<Catalog>(
          `/api/content/catalog${qs.toString() ? '?' + qs : ''}`,
        )
        setCatalog(data)
        setSelected(null)
        if (data.stale) {
          toast(t('Catalog is stale — fetch failed, showing cache'), 'error')
        }
      } catch (e) {
        toast(t('Failed to load catalog') + ': ' + (e as Error).message, 'error')
        setCatalog(null)
      } finally {
        setLoading(false)
      }
    },
    [activeId, t, toast],
  )

  // Load the catalog list once. Pick the first one by default; the
  // /catalog endpoint also defaults to it when catalog_id is empty.
  useEffect(() => {
    apiGet<{ catalogs: CatalogRef[] }>('/api/content/catalogs')
      .then((d) => {
        setCatalogs(d.catalogs || [])
        if (d.catalogs && d.catalogs.length > 0 && !activeId) {
          setActiveId(d.catalogs[0].id)
        }
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (activeId) load(false, activeId)
  }, [activeId, load])

  const allTags = useMemo(() => {
    const set = new Set<string>()
    for (const p of catalog?.packs || []) for (const tg of p.tags || []) set.add(tg)
    return Array.from(set).sort()
  }, [catalog])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (catalog?.packs || []).filter((p) => {
      if (filterType && p.type !== filterType) return false
      if (filterTag && !(p.tags || []).includes(filterTag)) return false
      if (q) {
        const hay = `${p.name || ''} ${p.slug || ''} ${p.description || ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [catalog, filterType, filterTag, search])

  const install = useCallback(
    async (pack: Pack) => {
      setInstalling(pack.id)
      try {
        const result = await apiPost<{ result?: { status?: string } }>(
          '/api/content/install',
          { pack_id: pack.id, catalog_id: activeId },
        )
        toast(t('Installed: {name}').replace('{name}', pack.name || pack.id))
        // Soft hint: tell the user which local tab to check.
        const where = PRETTY_TYPE[pack.type] || pack.type
        toast(t('Visit the {tab} tab to use it').replace('{tab}', where))
        return result
      } catch (e) {
        toast(t('Install failed') + ': ' + (e as Error).message, 'error')
      } finally {
        setInstalling(null)
      }
    },
    [activeId, t, toast],
  )

  if (loading && !catalog) return <div className="ga-loading">{t('Loading…')}</div>

  if (catalogs.length === 0) {
    return (
      <div className="ga-placeholder" style={{ padding: 24 }}>
        <p>
          <strong>{t('Marketplace not configured')}</strong>
        </p>
        <p>
          {t('Add at least one catalog under')}{' '}
          <code>content_marketplace.catalogs</code>{' '}
          {t('in admin settings.')}
        </p>
      </div>
    )
  }

  return (
    <div className="ga-twocol">
      <aside className="ga-twocol-left">
        <div className="ga-twocol-header">
          <h3>{t('Marketplace')}</h3>
          <div className="ga-twocol-header-actions">
            <button
              className="ga-btn ga-btn-sm"
              onClick={() => load(true)}
              disabled={loading}
              title={t('Re-fetch the catalog from source')}
            >
              ⟳ {t('Refresh')}
            </button>
          </div>
        </div>
        {catalogs.length > 1 ? (
          <select
            className="ga-input"
            value={activeId}
            onChange={(e) => setActiveId(e.target.value)}
            title={t('Switch between configured catalogs')}
          >
            {catalogs.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        ) : null}
        <input
          className="ga-input"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('Search…')}
        />
        <div className="ga-form-row" style={{ marginTop: 4 }}>
          <select
            className="ga-input"
            style={{ flex: 1 }}
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
          >
            <option value="">{t('All types')}</option>
            {Object.entries(PRETTY_TYPE).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          <select
            className="ga-input"
            style={{ flex: 1 }}
            value={filterTag}
            onChange={(e) => setFilterTag(e.target.value)}
          >
            <option value="">{t('All tags')}</option>
            {allTags.map((tg) => (
              <option key={tg} value={tg}>
                {tg}
              </option>
            ))}
          </select>
        </div>
        {catalog?.stale ? (
          <div
            style={{
              marginTop: 6,
              padding: '4px 8px',
              background: '#d2992222',
              border: '1px solid #d2992255',
              borderRadius: 4,
              fontSize: 11,
              color: '#d29922',
            }}
          >
            {t('Showing cached catalog — last fetch failed.')}
          </div>
        ) : null}
        <ul className="ga-list" style={{ marginTop: 6 }}>
          {filtered.length === 0 ? (
            <li className="ga-list-empty">{t('No packs')}</li>
          ) : (
            filtered.map((p) => {
              const isActive = selected?.id === p.id
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    className={`ga-list-row${isActive ? ' is-active' : ''}`}
                    onClick={() => setSelected(p)}
                  >
                    <span className="ga-list-row-main">
                      <strong>{p.name || p.id}</strong>
                      <span className="ga-list-row-sub">
                        — {PRETTY_TYPE[p.type] || p.type}
                        {p.size_bytes ? ` · ${formatBytes(p.size_bytes)}` : ''}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })
          )}
        </ul>
      </aside>
      <section className="ga-twocol-right">
        {!selected ? (
          <div className="ga-placeholder">{t('Pick a pack to see its details.')}</div>
        ) : (
          <div className="ga-form" style={{ padding: 16 }}>
            {selected.preview_image ? (
              <img
                src={selected.preview_image}
                alt=""
                style={{
                  maxWidth: '100%',
                  maxHeight: 240,
                  objectFit: 'contain',
                  borderRadius: 6,
                  marginBottom: 12,
                }}
                onError={(e) => {
                  ;(e.target as HTMLImageElement).style.display = 'none'
                }}
              />
            ) : null}
            <h2 style={{ fontSize: 18, margin: '0 0 4px' }}>
              {selected.name || selected.id}
            </h2>
            <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 12 }}>
              {PRETTY_TYPE[selected.type] || selected.type}
              {selected.version ? ` · v${selected.version}` : ''}
              {selected.size_bytes ? ` · ${formatBytes(selected.size_bytes)}` : ''}
            </div>
            {selected.tags && selected.tags.length > 0 ? (
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 12 }}>
                {selected.tags.map((tg) => (
                  <span
                    key={tg}
                    style={{
                      fontSize: 11,
                      padding: '2px 6px',
                      borderRadius: 10,
                      background: '#21262d',
                      color: '#c9d1d9',
                    }}
                  >
                    {tg}
                  </span>
                ))}
              </div>
            ) : null}
            {selected.description ? (
              <p style={{ fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                {selected.description}
              </p>
            ) : null}
            {selected.type === 'collection' && selected.contents && selected.contents.length > 0 ? (
              <div style={{ marginTop: 4, marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 4 }}>
                  {t('Contents')} ({selected.contents.length}):
                </div>
                <ul
                  style={{
                    margin: 0,
                    padding: '6px 8px',
                    listStyle: 'none',
                    background: '#0d1117',
                    border: '1px solid #30363d',
                    borderRadius: 6,
                    fontSize: 12,
                    maxHeight: 220,
                    overflowY: 'auto',
                  }}
                >
                  {selected.contents.map((c, i) => (
                    <li
                      key={i}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        padding: '3px 4px',
                        borderBottom:
                          i < selected.contents!.length - 1 ? '1px solid #21262d' : 'none',
                      }}
                    >
                      <span>{c.name}</span>
                      <span style={{ color: '#8b949e' }}>
                        {PRETTY_TYPE[c.type] || c.type}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {selected.type === 'location' && selected.room_count ? (
              <p style={{ fontSize: 12, color: '#8b949e' }}>
                {selected.room_count} {t('rooms')}
                {selected.image_count ? `, ${selected.image_count} ${t('images')}` : ''}
              </p>
            ) : null}
            <div style={{ marginTop: 16 }}>
              <button
                className="ga-btn ga-btn-primary"
                disabled={installing === selected.id || !selected.download_url}
                onClick={() => install(selected)}
              >
                {installing === selected.id ? t('Installing…') : t('Install')}
              </button>
              {!selected.download_url ? (
                <span style={{ marginLeft: 8, fontSize: 12, color: '#f85149' }}>
                  {t('No download_url in pack')}
                </span>
              ) : null}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
