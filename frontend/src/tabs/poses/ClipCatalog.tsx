/**
 * ClipCatalog — browsing the CMU trial archive and lifting a take into the
 * free clip library.
 *
 * The archive holds the WHOLE CMU database (2 435 takes), measured and tagged
 * by `scripts/cmu_enrich_index.py`. Nothing in it is game content: a take
 * becomes a real animation only by being imported here — named, cut to a
 * window, optionally looped and put in place.
 *
 * Three columns: the facets on the left, the hit list in the middle, the take
 * with its preview and the import form on the right.
 *
 * PARTIAL DATA IS THE NORMAL STATE. Both background runs (measuring and
 * converting) fill the catalog while it is being browsed, so a take may carry
 * no `clip` yet ("not converted yet" instead of a preview) and takes may be
 * missing altogether. Nothing here treats that as an error.
 *
 * FACET COUNTS follow the usual rule: a value's count is what the result set
 * would be with every OTHER facet applied but this facet's own selection
 * ignored — otherwise every unselected value in an active facet would read 0
 * and nothing could ever be widened.
 *
 * DUPLICATE GROUPS are collapsed by default: the database has 140 takes called
 * "walk", and an expanded list of them would bury everything else.
 *
 *   GET  /assets/clip-catalog
 *   PUT  /assets/clip-catalog/{take}/status     {favorite?, rejected?}
 *   POST /assets/clip-catalog/{take}/import     {kind, set, start_s, …}
 *   GET  /assets/animation-clips/trial/{rel}    (preview file)
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ClipPreview } from './ClipPreview'
import { Sparkline } from './Sparkline'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

const PAGE_SIZE = 50

interface Metrics {
  posture: string
  hips_rel_median?: number
  hips_rel_min?: number
  hips_rel_max?: number
  energy: string
  speed_mean_m_s?: number
  speed_max_m_s?: number
  travel: string
  travel_m?: number
  path_m?: number
  duration_class: string
  loop_seam?: number
  loopable?: boolean
}

interface ImportTrace { kind: string; set: string; source: string; at: string }
interface TakeStatus { favorite: boolean; rejected: boolean; imported: ImportTrace[] }

interface Take {
  id: string
  subject: number
  trial: number
  description: string
  subject_description: string
  categories: string[]
  category_labels: string[]
  tags: string[]
  group: string
  framerate: number
  duration_s: number
  frames: number
  pair: boolean
  pair_role: string
  pair_partner: string
  clip: string | null
  clip_urls?: { a?: string; b?: string; solo?: string }
  metrics: Metrics
  sparkline: number[]
  status: TakeStatus
}

interface Catalog {
  generated?: string
  credit?: string
  tags: Record<string, { label: string; count: number }>
  facets: Record<string, string[]>
  groups: Record<string, { label: string; take_ids: string[] }>
  takes: Take[]
}

interface ClipEntry { kind: string; set: string; source: string }

type FacetId =
  | 'tags' | 'posture' | 'energy' | 'travel' | 'duration'
  | 'pair' | 'loopable' | 'framerate' | 'status' | 'clip'

type Selection = Record<FacetId, string[]>

interface FacetDef {
  id: FacetId
  label: string
  values: string[]
  /** display label per value; the raw value is used where none is given */
  labels?: Record<string, string>
}

const EMPTY_SELECTION: Selection = {
  tags: [], posture: [], energy: [], travel: [], duration: [],
  pair: [], loopable: [], framerate: [], status: [], clip: [],
}

/** Every facet value a take carries — the ONE place a take is classified. */
function facetValues(take: Take): Record<FacetId, string[]> {
  const m = take.metrics || ({} as Metrics)
  const st = take.status || { favorite: false, rejected: false, imported: [] }
  const status: string[] = []
  if (st.favorite) status.push('favorite')
  if (st.rejected) status.push('rejected')
  if (st.imported?.length) status.push('imported')
  if (!status.length) status.push('untouched')
  return {
    tags: take.tags || [],
    posture: m.posture ? [m.posture] : [],
    energy: m.energy ? [m.energy] : [],
    travel: m.travel ? [m.travel] : [],
    duration: m.duration_class ? [m.duration_class] : [],
    pair: [take.pair ? 'pair' : 'solo'],
    loopable: [m.loopable ? 'yes' : 'no'],
    framerate: [String(take.framerate || '')],
    status,
    clip: [take.clip ? 'converted' : 'pending'],
  }
}

/** A kind proposal from the take's description: the first words, slugged. */
function slugKind(description: string): string {
  const slug = (description || '')
    .toLowerCase()
    .replace(/\(.*?\)/g, ' ')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug.split('-').filter(Boolean).slice(0, 3).join('-')
}

export function ClipCatalog({ onCreatePose }: { onCreatePose?: (kind: string) => void }) {
  const { t } = useI18n()
  const { toast } = useToast()

  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [clips, setClips] = useState<ClipEntry[]>([])
  const [sets, setSets] = useState<string[]>([])

  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'id' | 'duration' | 'energy' | 'loop_seam'>('id')
  const [sel, setSel] = useState<Selection>(EMPTY_SELECTION)
  const [tagFilter, setTagFilter] = useState('')
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState<string[]>([])
  const [selectedId, setSelectedId] = useState('')

  // import form
  const [kind, setKind] = useState('')
  const [clipSet, setClipSet] = useState('')
  const [startS, setStartS] = useState('0')
  const [endS, setEndS] = useState('')
  const [loopOn, setLoopOn] = useState(false)
  const [loopS, setLoopS] = useState('1.5')
  const [inPlace, setInPlace] = useState(true)
  const [overwrite, setOverwrite] = useState(false)
  const [importing, setImporting] = useState(false)
  const [lastImported, setLastImported] = useState('')

  const loadClips = useCallback(async () => {
    try {
      const r = await apiGet<{ clips?: ClipEntry[]; sets?: string[] }>('/assets/animation-clips')
      setClips(r.clips || [])
      setSets(r.sets || [])
    } catch {
      setClips([])
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setCatalog(await apiGet<Catalog>('/assets/clip-catalog'))
      setError('')
    } catch (e) {
      setCatalog(null)
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    void loadClips()
  }, [load, loadClips])

  const takes = useMemo(() => catalog?.takes || [], [catalog])
  const byId = useMemo(() => {
    const m = new Map<string, Take>()
    takes.forEach((k) => m.set(k.id, k))
    return m
  }, [takes])

  const classified = useMemo(
    () => takes.map((take) => ({ take, values: facetValues(take) })),
    [takes],
  )

  const textMatch = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return () => true
    return (take: Take) => {
      const label = catalog?.groups?.[take.group]?.label || ''
      return (
        take.id.toLowerCase().includes(q) ||
        (take.description || '').toLowerCase().includes(q) ||
        (take.subject_description || '').toLowerCase().includes(q) ||
        label.toLowerCase().includes(q)
      )
    }
  }, [search, catalog])

  /** Takes passing the search plus every facet EXCEPT `skip`. */
  const passing = useCallback(
    (skip?: FacetId) =>
      classified.filter(({ take, values }) => {
        if (!textMatch(take)) return false
        for (const id of Object.keys(sel) as FacetId[]) {
          if (id === skip) continue
          const picked = sel[id]
          if (!picked.length) continue
          if (!picked.some((v) => values[id].includes(v))) return false
        }
        return true
      }),
    [classified, sel, textMatch],
  )

  const results = useMemo(() => passing().map((r) => r.take), [passing])

  const counts = useMemo(() => {
    const out = {} as Record<FacetId, Record<string, number>>
    for (const id of Object.keys(EMPTY_SELECTION) as FacetId[]) {
      const c: Record<string, number> = {}
      for (const { values } of passing(id)) {
        for (const v of values[id]) c[v] = (c[v] || 0) + 1
      }
      out[id] = c
    }
    return out
  }, [passing])

  const sortKey = useCallback(
    (take: Take) => {
      if (sort === 'duration') return take.duration_s || 0
      if (sort === 'energy') return take.metrics?.speed_mean_m_s || 0
      if (sort === 'loop_seam') return take.metrics?.loop_seam ?? 999
      return 0
    },
    [sort],
  )

  /** Result rows: one per duplicate group, singles stay plain rows. */
  const rows = useMemo(() => {
    const groups = new Map<string, Take[]>()
    for (const take of results) {
      const key = take.group || `#${take.id}`
      const list = groups.get(key)
      if (list) list.push(take)
      else groups.set(key, [take])
    }
    const out = Array.from(groups.entries()).map(([key, list]) => {
      const sorted = [...list].sort((a, b) =>
        sort === 'id' ? a.id.localeCompare(b.id) : sortKey(a) - sortKey(b),
      )
      return {
        key,
        label: catalog?.groups?.[key]?.label || sorted[0].description || key,
        takes: sorted,
      }
    })
    out.sort((a, b) =>
      sort === 'id'
        ? a.takes[0].id.localeCompare(b.takes[0].id)
        : sortKey(a.takes[0]) - sortKey(b.takes[0]),
    )
    return out
  }, [results, catalog, sort, sortKey])

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const pageRows = rows.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)

  useEffect(() => {
    setPage(0)
  }, [search, sel, sort])

  const selected = selectedId ? byId.get(selectedId) || null : null

  // A newly picked take resets the import form to that take's own defaults.
  useEffect(() => {
    if (!selected) return
    setKind(slugKind(selected.description))
    setStartS('0')
    setEndS(String(Number((selected.duration_s || 0).toFixed(2))))
    setLoopOn(false)
    setLoopS('1.5')
    setInPlace(!selected.pair)
    setOverwrite(false)
    setLastImported('')
  }, [selected])

  const toggle = useCallback((facet: FacetId, value: string) => {
    setSel((prev) => {
      const picked = prev[facet]
      return {
        ...prev,
        [facet]: picked.includes(value)
          ? picked.filter((v) => v !== value)
          : [...picked, value],
      }
    })
  }, [])

  const setStatus = useCallback(
    async (take: Take, patch: { favorite?: boolean; rejected?: boolean }) => {
      try {
        const r = await apiPut<{ status: TakeStatus }>(
          `/assets/clip-catalog/${encodeURIComponent(take.id)}/status`,
          patch,
        )
        setCatalog((prev) =>
          prev
            ? {
                ...prev,
                takes: prev.takes.map((k) =>
                  k.id === take.id ? { ...k, status: r.status } : k,
                ),
              }
            : prev,
        )
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [t, toast],
  )

  const existingKinds = useMemo(
    () =>
      new Set(
        clips
          .filter((c) => c.source === 'free' && (c.set || '') === clipSet)
          .map((c) => c.kind),
      ),
    [clips, clipSet],
  )
  const kindExists = existingKinds.has(kind.trim().toLowerCase())

  const runImport = useCallback(async () => {
    if (!selected || importing) return
    setImporting(true)
    try {
      const body: Record<string, unknown> = {
        kind: kind.trim().toLowerCase(),
        set: clipSet,
        start_s: Number(startS) || 0,
        end_s: endS === '' ? null : Number(endS),
        loop_s: loopOn ? Number(loopS) || 1 : null,
        in_place: inPlace,
        overwrite,
        target: 'free',
      }
      const r = await apiPost<{ kind: string; status: TakeStatus; seconds: number }>(
        `/assets/clip-catalog/${encodeURIComponent(selected.id)}/import`,
        body,
      )
      toast(`${t('Imported as')} ${r.kind} (${(r.seconds || 0).toFixed(1)} s)`)
      setLastImported(r.kind)
      setCatalog((prev) =>
        prev
          ? {
              ...prev,
              takes: prev.takes.map((k) =>
                k.id === selected.id ? { ...k, status: r.status } : k,
              ),
            }
          : prev,
      )
      await loadClips()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setImporting(false)
    }
  }, [clipSet, endS, importing, inPlace, kind, loadClips, loopOn, loopS,
      overwrite, selected, startS, t, toast])

  // ── facet definitions (label + the values offered) ──
  const facetDefs = useMemo<FacetDef[]>(() => {
      const f = catalog?.facets || {}
      const defs: FacetDef[] = [
        { id: 'posture', label: t('Posture'), values: f.posture || [] },
        { id: 'energy', label: t('Energy'), values: f.energy || [] },
        { id: 'travel', label: t('Travel'), values: f.travel || [] },
        { id: 'duration', label: t('Duration'), values: f.duration || [] },
        {
          id: 'pair', label: t('Subjects'), values: ['solo', 'pair'],
          labels: { solo: t('solo'), pair: t('pair') },
        },
        {
          id: 'loopable', label: t('Loopable'), values: ['yes', 'no'],
          labels: { yes: t('loopable'), no: t('no clean loop') },
        },
        {
          id: 'framerate', label: t('Capture rate'),
          values: Object.keys(counts.framerate || {}).sort(),
          labels: {},
        },
        {
          id: 'clip', label: t('Trial clip'), values: ['converted', 'pending'],
          labels: { converted: t('converted'), pending: t('not converted yet') },
        },
        {
          id: 'status', label: t('Review'),
          values: ['favorite', 'rejected', 'imported', 'untouched'],
          labels: {
            favorite: t('favorite'), rejected: t('rejected'),
            imported: t('imported'), untouched: t('not reviewed yet'),
          },
        },
      ]
      return defs
    }, [catalog, counts, t])

  const tagRows = useMemo(() => {
    const all = catalog?.tags || {}
    const q = tagFilter.trim().toLowerCase()
    return Object.keys(all)
      .filter((k) => !q || k.includes(q) || (all[k].label || '').toLowerCase().includes(q))
      .map((k) => ({ id: k, label: all[k].label || k, count: counts.tags?.[k] || 0 }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
  }, [catalog, counts, tagFilter])

  const activeCount = (Object.keys(sel) as FacetId[]).reduce((n, id) => n + sel[id].length, 0)

  if (loading) return <div className="ga-placeholder">{t('Loading…')}</div>
  if (!catalog) {
    return (
      <div className="ga-placeholder">
        <div>{t('No CMU trial catalog on this installation.')}</div>
        <div className="ga-hint" style={{ marginTop: 6 }}>{error}</div>
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '220px minmax(320px, 1.1fr) minmax(340px, 1.2fr)', gap: 14,
                  alignItems: 'stretch', flex: 1, minHeight: 0 }}>
      {/* ── facets ── */}
      <aside style={{ display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong>{t('Filters')}</strong>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={!activeCount}
            onClick={() => setSel(EMPTY_SELECTION)}
          >
            {t('Reset')} {activeCount ? `(${activeCount})` : ''}
          </button>
        </div>

        <FacetBox label={t('Tags')}>
          <input
            className="ga-input"
            style={{ marginBottom: 4 }}
            placeholder={t('Filter tags…')}
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
          />
          <div style={{ maxHeight: 220, overflowY: 'auto' }}>
            {tagRows.map((tag) => (
              <FacetValue
                key={tag.id}
                label={tag.label}
                count={tag.count}
                checked={sel.tags.includes(tag.id)}
                onToggle={() => toggle('tags', tag.id)}
              />
            ))}
          </div>
        </FacetBox>

        {facetDefs.map((f) => (
          <FacetBox key={f.id} label={f.label}>
            {f.values.map((v) => (
              <FacetValue
                key={v}
                label={f.labels?.[v] || v}
                count={counts[f.id]?.[v] || 0}
                checked={sel[f.id].includes(v)}
                onToggle={() => toggle(f.id, v)}
              />
            ))}
          </FacetBox>
        ))}
      </aside>

      {/* ── hit list ── */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <input
            className="ga-input"
            style={{ flex: '1 1 180px' }}
            placeholder={t('Search description, subject, id…')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            className="ga-input"
            style={{ maxWidth: 150 }}
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
          >
            <option value="id">{t('Sort: take id')}</option>
            <option value="duration">{t('Sort: duration')}</option>
            <option value="energy">{t('Sort: energy')}</option>
            <option value="loop_seam">{t('Sort: loop seam')}</option>
          </select>
        </div>

        <div className="ga-hint">
          {results.length} {t('takes')} · {rows.length} {t('groups')} ·{' '}
          {t('page')} {page + 1}/{pageCount}
          {catalog.takes.length ? '' : ` · ${t('catalog still filling')}`}
        </div>

        <ul className="ga-list" style={{ minWidth: 0 }}>
          {!pageRows.length ? <li className="ga-list-empty">{t('Nothing matches')}</li> : null}
          {pageRows.map((row) => {
            const isGroup = row.takes.length > 1
            const open = expanded.includes(row.key)
            return (
              <li key={row.key} style={{ minWidth: 0 }}>
                {isGroup ? (
                  <button
                    type="button"
                    className="ga-list-row"
                    onClick={() =>
                      setExpanded((prev) =>
                        prev.includes(row.key)
                          ? prev.filter((k) => k !== row.key)
                          : [...prev, row.key],
                      )
                    }
                  >
                    <span className="ga-list-row-main">
                      <span style={{ opacity: 0.6, marginRight: 6 }}>{open ? '▾' : '▸'}</span>
                      {row.label}
                    </span>
                    <span className="ga-source">×{row.takes.length}</span>
                  </button>
                ) : null}
                {(!isGroup || open) && (
                  <div style={{ paddingLeft: isGroup ? 14 : 0 }}>
                    {row.takes.map((take) => (
                      <TakeRow
                        key={take.id}
                        take={take}
                        active={take.id === selectedId}
                        onSelect={() => setSelectedId(take.id)}
                        t={t}
                      />
                    ))}
                  </div>
                )}
              </li>
            )
          })}
        </ul>

        {pageCount > 1 ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <button type="button" className="ga-btn ga-btn-sm" disabled={!page} onClick={() => setPage((p) => p - 1)}>
              {t('Previous')}
            </button>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={page >= pageCount - 1}
              onClick={() => setPage((p) => p + 1)}
            >
              {t('Next')}
            </button>
          </div>
        ) : null}
      </section>

      {/* ── detail + import ── */}
      <section style={{ minWidth: 0, minHeight: 0, overflowY: 'auto', paddingRight: 4 }}>
        {!selected ? (
          <div className="ga-placeholder">{t('Pick a take to see its metrics and import it.')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <h3 style={{ margin: '0 0 2px' }}>
                <code>{selected.id}</code> — {selected.description}
              </h3>
              <div className="ga-hint">
                {selected.category_labels?.join(' · ')}
                {selected.subject_description ? ` — ${selected.subject_description}` : ''}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button
                type="button"
                className={`ga-btn ga-btn-sm${selected.status.favorite ? ' ga-btn-primary' : ''}`}
                onClick={() => setStatus(selected, { favorite: !selected.status.favorite })}
              >
                ★ {t('Favorite')}
              </button>
              <button
                type="button"
                className={`ga-btn ga-btn-sm${selected.status.rejected ? ' ga-btn-danger' : ''}`}
                onClick={() => setStatus(selected, { rejected: !selected.status.rejected })}
              >
                ✕ {t('Rejected')}
              </button>
            </div>

            <Metric label={t('Posture')} value={selected.metrics.posture} />
            <Metric
              label={t('Energy')}
              value={`${selected.metrics.energy} — ${(selected.metrics.speed_mean_m_s ?? 0).toFixed(2)} ${t('m/s mean')}, ${(selected.metrics.speed_max_m_s ?? 0).toFixed(2)} ${t('peak')}`}
            />
            <Metric
              label={t('Travel')}
              value={`${selected.metrics.travel} — ${(selected.metrics.travel_m ?? 0).toFixed(2)} m ${t('start→end')}, ${(selected.metrics.path_m ?? 0).toFixed(2)} m ${t('walked')}`}
            />
            <Metric
              label={t('Duration')}
              value={`${(selected.duration_s || 0).toFixed(2)} s · ${selected.frames} ${t('frames')} @ ${selected.framerate} Hz · ${selected.metrics.duration_class}`}
            />
            <Metric
              label={t('Loop')}
              value={`${t('seam')} ${(selected.metrics.loop_seam ?? 0).toFixed(2)} — ${selected.metrics.loopable ? t('closes into a cycle') : t('no clean loop')}`}
            />
            <Metric
              label={t('Hip height')}
              value={`${(selected.metrics.hips_rel_min ?? 0).toFixed(2)} … ${(selected.metrics.hips_rel_median ?? 0).toFixed(2)} … ${(selected.metrics.hips_rel_max ?? 0).toFixed(2)} ${t('leg lengths')}`}
            />
            {selected.pair ? (
              <Metric
                label={t('Pair')}
                value={`${t('role')} ${(selected.pair_role || 'a').toUpperCase()} · ${t('partner')} ${selected.pair_partner || '–'}`}
              />
            ) : null}
            {selected.status.imported?.length ? (
              <Metric
                label={t('Imported')}
                value={selected.status.imported
                  .map((i) => `${i.set ? `${i.set}/` : ''}${i.kind}`)
                  .join(', ')}
              />
            ) : null}

            <div>
              <div className="ga-hint">{t('Hip height over the take — the green/red markers are the import window.')}</div>
              <div style={{ background: '#0d1117', borderRadius: 6, padding: 6 }}>
                <Sparkline
                  values={selected.sparkline || []}
                  width={320}
                  height={54}
                  from={Number(startS) || 0}
                  to={endS === '' ? selected.duration_s : Number(endS)}
                  duration={selected.duration_s}
                  title={t('hip height')}
                />
              </div>
            </div>

            {selected.clip && selected.clip_urls && (selected.clip_urls.solo || selected.clip_urls.a) ? (
              <ClipPreview urls={selected.clip_urls} height={280} />
            ) : (
              <div className="ga-form-hint">
                {t('Not converted yet — the bulk conversion has not reached this take. It can still be imported: the import converts the original recording directly.')}
              </div>
            )}

            {/* ── import form ── */}
            <div style={{ borderTop: '1px solid var(--border, #30363d)', paddingTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <strong>{t('Import into the free clip library')}</strong>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <span className="ga-hint">{t('Clip kind (the file stem, lowercase, no "__")')}</span>
                <input className="ga-input" value={kind} onChange={(e) => setKind(e.target.value)} />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <span className="ga-hint">{t('Set (a subdirectory — empty is the neutral figure)')}</span>
                <select className="ga-input" value={clipSet} onChange={(e) => setClipSet(e.target.value)}>
                  <option value="">{t('— neutral —')}</option>
                  {sets.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>

              <div style={{ display: 'flex', gap: 8 }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
                  <span className="ga-hint">{t('Start (s)')}</span>
                  <input className="ga-input" type="number" step="0.1" min="0" value={startS}
                    onChange={(e) => setStartS(e.target.value)} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
                  <span className="ga-hint">{t('End (s)')}</span>
                  <input className="ga-input" type="number" step="0.1" min="0" value={endS}
                    onChange={(e) => setEndS(e.target.value)} />
                </label>
              </div>

              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={loopOn} disabled={selected.pair}
                  onChange={(e) => setLoopOn(e.target.checked)} />
                <span>{t('Cut to a seamless loop of at least')}</span>
                <input className="ga-input" type="number" step="0.5" min="0.5" style={{ width: 70 }}
                  value={loopS} disabled={!loopOn || selected.pair}
                  onChange={(e) => setLoopS(e.target.value)} />
                <span>s</span>
              </label>

              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={inPlace} disabled={selected.pair}
                  onChange={(e) => setInPlace(e.target.checked)} />
                <span>
                  {t('In place (strip the horizontal root travel)')}
                  {selected.pair ? ` — ${t('pairs keep their contact geometry')}` : ''}
                </span>
              </label>

              {kindExists ? (
                <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
                  <span style={{ color: 'var(--warn, #d29922)' }}>
                    {t('Overwrite the existing clip of this kind')}
                  </span>
                </label>
              ) : null}

              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm ga-btn-primary"
                  disabled={importing || !kind.trim()}
                  onClick={runImport}
                >
                  {importing ? t('Converting with Blender…') : t('Import')}
                </button>
                {lastImported ? (
                  <>
                    <span className="ga-source">{t('imported as')} {lastImported}</span>
                    {onCreatePose ? (
                      <button type="button" className="ga-btn ga-btn-sm"
                        onClick={() => onCreatePose(lastImported)}>
                        {t('Create pose entry')}
                      </button>
                    ) : null}
                  </>
                ) : null}
              </div>
              <div className="ga-hint">
                {selected.pair
                  ? t('This is a pair take — both halves are converted into one kind (__a / __b).')
                  : t('One Blender run of a few seconds; the new kind is selectable in the pose editor right after.')}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

function FacetBox({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: '0.78em', textTransform: 'uppercase', opacity: 0.6, marginBottom: 3 }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function FacetValue({ label, count, checked, onToggle }:
  { label: string; count: number; checked: boolean; onToggle: () => void }) {
  return (
    <label
      style={{
        display: 'flex', gap: 5, alignItems: 'center', fontSize: '0.85em',
        opacity: count || checked ? 1 : 0.4, cursor: 'pointer',
      }}
    >
      <input type="checkbox" checked={checked} onChange={onToggle} />
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {label}
      </span>
      <span style={{ opacity: 0.6 }}>{count}</span>
    </label>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: '0.86em' }}>
      <span style={{ width: 96, opacity: 0.6, flexShrink: 0 }}>{label}</span>
      <span style={{ minWidth: 0, wordBreak: 'break-word' }}>{value}</span>
    </div>
  )
}

function TakeRow({ take, active, onSelect, t }:
  { take: Take; active: boolean; onSelect: () => void; t: (s: string) => string }) {
  const m = take.metrics || ({} as Metrics)
  const badges = [
    m.posture, m.energy, m.travel,
    `${(take.duration_s || 0).toFixed(1)}s`,
    take.pair ? t('pair') : '',
    take.framerate === 60 ? '60 Hz' : '',
    m.loopable ? t('loop') : '',
  ].filter(Boolean)
  return (
    <button
      type="button"
      className={`ga-list-row${active ? ' is-active' : ''}`}
      style={{ alignItems: 'flex-start' }}
      onClick={onSelect}
    >
      <span className="ga-list-row-main" style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
          <code>{take.id}</code>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {take.description}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', fontSize: '0.72em', opacity: 0.7, marginTop: 2 }}>
          {badges.map((b) => (
            <span key={b} style={{ border: '1px solid var(--border, #30363d)', borderRadius: 3, padding: '0 4px' }}>
              {b}
            </span>
          ))}
          {(take.tags || []).slice(0, 4).map((tag) => (
            <span key={tag} style={{ opacity: 0.8 }}>#{tag}</span>
          ))}
        </div>
      </span>
      <span style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
        <Sparkline values={take.sparkline || []} width={70} height={20} />
        {take.status?.favorite ? <span title={t('favorite')}>★</span> : null}
        {take.status?.rejected ? <span title={t('rejected')}>✕</span> : null}
        {take.status?.imported?.length ? <span title={t('imported')}>⤓</span> : null}
        {!take.clip ? <span style={{ opacity: 0.4 }} title={t('not converted yet')}>◌</span> : null}
      </span>
    </button>
  )
}
