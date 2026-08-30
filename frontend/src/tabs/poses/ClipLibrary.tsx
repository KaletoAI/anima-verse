/**
 * ClipLibrary — what is actually INSTALLED in the shared animation libraries,
 * read as one matrix: kind × set × library.
 *
 * The other three surfaces of the Poses tab look at clips from the outside —
 * the catalog entries name a kind, the CMU browser and the inbox produce one.
 * This one looks at the files on disk: which kind exists in which set, in the
 * free or in the licensed library, how long it runs, where it came from, and
 * which pose entries depend on it. A kind a pose names but no file backs is a
 * "missing" row — the one gap that silently leaves a figure standing.
 *
 * Two libraries, one winner: a kind present in BOTH is served from the
 * LICENSED one (the local, untracked library wins over the free files in git),
 * so the cell shows both and marks that one.
 *
 *   GET    /assets/animation-clips
 *   PATCH  /assets/animation-clips/{library}/{rel}   {kind?, set?, library?}
 *   DELETE /assets/animation-clips/{library}/{rel}
 */
import { useCallback, useMemo, useState } from 'react'
import { ClipPreview } from './ClipPreview'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiPatch } from '../../lib/api'
import { orderSets } from './clipSets'
import type { ApiClipRow, ClipListing } from './clipSets'

function libraryOf(c: ApiClipRow): string {
  return c.library || c.source || 'free'
}

/** Path inside the library — the listing carries it; older payloads are
 *  rebuilt from set + filename, which is the same string. */
function relOf(c: ApiClipRow): string {
  if (c.rel) return c.rel
  const file = c.filename || `${c.name || c.kind}.fbx`
  return c.set ? `${c.set}/${file}` : file
}

function clipPath(c: ApiClipRow): string {
  const rel = relOf(c)
    .split('/')
    .map((s) => encodeURIComponent(s))
    .join('/')
  return `/assets/animation-clips/${encodeURIComponent(libraryOf(c))}/${rel}`
}

function mb(bytes?: number): string {
  if (!bytes) return ''
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Variants of a kind, not files: the two halves of a pair are ONE clip. */
function variants(clips: ApiClipRow[]): number {
  return clips.filter((c) => (c.role || '') !== 'b').length
}

interface Cell {
  free: ApiClipRow[]
  licensed: ApiClipRow[]
  all: ApiClipRow[]
}

interface Row {
  kind: string
  pair: boolean
  /** pose keys whose `animation` is this kind */
  used: string[]
  cells: Record<string, Cell>
  clips: ApiClipRow[]
  /** named by a pose, but no file anywhere */
  missing: boolean
}

type ActionKind = 'kind' | 'set' | 'library' | 'delete'

interface PoseRef {
  key: string
  animation: string
}

export function ClipLibrary({
  listing,
  poses,
  onReload,
}: {
  listing: ClipListing
  /** the pose catalog entries — the "Used by" column reads their `animation` */
  poses: PoseRef[]
  /** re-fetch the listing (and the catalog) after a rename/move/delete */
  onReload: () => Promise<void> | void
}) {
  const { t } = useI18n()
  const [search, setSearch] = useState('')
  const [libFilter, setLibFilter] = useState('')
  // '*' = every set; '' is the neutral set and a value of its own
  const [setFilter, setSetFilter] = useState('*')
  const [onlyUsed, setOnlyUsed] = useState(false)
  const [onlyUnused, setOnlyUnused] = useState(false)
  const [selected, setSelected] = useState('')
  const [previewSet, setPreviewSet] = useState('')
  // Which clip has an action open, and the value being typed for it
  const [action, setAction] = useState<{ rel: string; type: ActionKind } | null>(null)
  const [value, setValue] = useState('')
  // "Move to set" with a set that does not exist yet — the select then hands
  // over to a free text field instead of snapping back on every keystroke.
  const [customSet, setCustomSet] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // Bumped after every write so the preview reloads the (possibly renamed) clip
  const [seq, setSeq] = useState(0)

  const clips = useMemo(() => listing.clips || [], [listing.clips])
  const pairKinds = useMemo(
    () => new Set(listing.pair_kinds || []),
    [listing.pair_kinds],
  )

  /** Columns: everything selectable on a character plus every set that has
   *  files — a set whose directory exists but is not offered anywhere would
   *  otherwise hide its clips. */
  const columns = useMemo(() => {
    const all = new Set<string>([''])
    for (const s of listing.sets || []) all.add(s)
    for (const s of listing.clip_sets || []) all.add(s)
    for (const c of clips) all.add(c.set || '')
    return orderSets(Array.from(all))
  }, [clips, listing.clip_sets, listing.sets])

  const usage = useMemo(() => {
    const out: Record<string, string[]> = {}
    for (const p of poses) {
      const k = (p.animation || '').trim()
      if (!k) continue
      ;(out[k] = out[k] || []).push(p.key)
    }
    return out
  }, [poses])

  const rows = useMemo<Row[]>(() => {
    const kinds = new Set<string>(listing.kinds || [])
    for (const c of clips) kinds.add(c.kind)
    // A kind a pose names but no file backs — the gap this view exists to show
    for (const k of Object.keys(usage)) kinds.add(k)
    return Array.from(kinds)
      .sort()
      .map((kind) => {
        const own = clips.filter((c) => c.kind === kind)
        const cells: Record<string, Cell> = {}
        for (const col of columns) {
          const inSet = own.filter((c) => (c.set || '') === col)
          cells[col] = {
            free: inSet.filter((c) => libraryOf(c) === 'free'),
            licensed: inSet.filter((c) => libraryOf(c) === 'licensed'),
            all: inSet,
          }
        }
        return {
          kind,
          pair: pairKinds.has(kind) || own.some((c) => (c.role || '') === 'b'),
          used: usage[kind] || [],
          cells,
          clips: own,
          missing: !own.length,
        }
      })
  }, [clips, columns, listing.kinds, pairKinds, usage])

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (q && !r.kind.toLowerCase().includes(q)) return false
      if (libFilter && !r.clips.some((c) => libraryOf(c) === libFilter)) return false
      if (setFilter !== '*' && !r.clips.some((c) => (c.set || '') === setFilter)) return false
      if (onlyUsed && !r.used.length) return false
      if (onlyUnused && r.used.length) return false
      return true
    })
  }, [libFilter, onlyUnused, onlyUsed, rows, search, setFilter])

  const row = useMemo(() => rows.find((r) => r.kind === selected) || null, [rows, selected])

  /** Sets the selected kind actually has a clip in — the preview's switch. */
  const rowSets = useMemo(
    () => (row ? orderSets(Array.from(new Set(row.clips.map((c) => c.set || '')))) : []),
    [row],
  )

  const pick = useCallback(
    (kind: string, set?: string) => {
      setSelected(kind)
      // Clicking the row (no column) previews the set the kind actually has —
      // neutral when there is one, otherwise the first that exists.
      const own = clips.filter((c) => c.kind === kind).map((c) => c.set || '')
      setPreviewSet(set !== undefined ? set : orderSets(Array.from(new Set(own)))[0] || '')
      setAction(null)
      setError('')
    },
    [clips],
  )

  const openAction = useCallback((clip: ApiClipRow, type: ActionKind) => {
    setError('')
    setAction({ rel: `${libraryOf(clip)}/${relOf(clip)}`, type })
    setValue(type === 'kind' ? clip.kind : type === 'set' ? clip.set || '' : '')
    setCustomSet(false)
  }, [])

  const run = useCallback(
    async (clip: ApiClipRow, body: Record<string, string> | null) => {
      if (busy) return
      setBusy(true)
      setError('')
      try {
        if (body) await apiPatch(clipPath(clip), body)
        else await apiDelete(clipPath(clip))
        setAction(null)
        setSeq((n) => n + 1)
        await onReload()
        // A renamed kind carries the selection with it, so the detail pane
        // does not fall back to the placeholder after every rename.
        if (body?.kind) setSelected(body.kind)
        if (body && 'set' in body) setPreviewSet(body.set)
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [busy, onReload],
  )

  const cellNode = (r: Row, col: string) => {
    const cell = r.cells[col]
    if (!cell || !cell.all.length) {
      return <span style={{ opacity: 0.25 }}>·</span>
    }
    const n = variants(cell.all)
    const both = !!cell.free.length && !!cell.licensed.length
    return (
      <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center', flexWrap: 'wrap' }}>
        {cell.free.length ? (
          <span
            className={`ga-tag${both ? '' : ' ga-tag-tier'}`}
            title={both ? t('Also in the free library — the licensed file is the one served.') : t('free library (tracked in git)')}
          >
            {t('free')}
          </span>
        ) : null}
        {cell.licensed.length ? (
          <span
            className="ga-tag ga-tag-tier"
            title={both ? t('In both libraries — the licensed file wins.') : t('licensed library (local only)')}
          >
            {t('licensed')}
          </span>
        ) : null}
        {n > 1 ? <span style={{ opacity: 0.7 }}>×{n}</span> : null}
      </span>
    )
  }

  const clipNode = (clip: ApiClipRow) => {
    const lib = libraryOf(clip)
    const rel = `${lib}/${relOf(clip)}`
    const open = action?.rel === rel ? action.type : null
    const other = lib === 'licensed' ? 'free' : 'licensed'
    const facts = [
      clip.role ? `${t('half')} ${clip.role.toUpperCase()}` : '',
      clip.duration_s ? `${clip.duration_s.toFixed(1)} s` : '',
      clip.fps ? `${clip.fps} fps` : '',
      clip.frames ? `${clip.frames} ${t('frames')}` : '',
      clip.loop ? t('loop') : '',
      clip.origin && clip.origin !== 'unknown' ? clip.origin : '',
      mb(clip.size),
      clip.has_sidecar === false ? t('no sidecar') : '',
    ].filter(Boolean)
    return (
      <li key={rel} style={{ padding: '6px 0', borderBottom: '1px solid var(--border, #30363d)' }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <code style={{ wordBreak: 'break-all' }}>{clip.filename || relOf(clip)}</code>
          <span className={`ga-tag${lib === 'licensed' ? ' ga-tag-tier' : ''}`}>{t(lib)}</span>
        </div>
        <div className="ga-hint" style={{ marginTop: 2 }}>{facts.join(' · ')}</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => openAction(clip, 'kind')}>
            {t('Rename kind')}
          </button>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => openAction(clip, 'set')}>
            {t('Move to set')}
          </button>
          <button type="button" className="ga-btn ga-btn-sm" onClick={() => openAction(clip, 'library')}>
            {other === 'free' ? t('Move to free library') : t('Move to licensed library')}
          </button>
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-danger"
            onClick={() => openAction(clip, 'delete')}
          >
            {t('Delete')}
          </button>
        </div>

        {open === 'kind' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <input
              className="ga-input"
              style={{ maxWidth: 200 }}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy || !value.trim()}
              onClick={() => run(clip, { kind: value.trim().toLowerCase() })}
            >
              {t('Apply')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAction(null)}>
              {t('Cancel')}
            </button>
            <span className="ga-hint">
              {t('Lowercase letters, digits, space, "_" and "-"; never "__" (that separates the pair halves).')}
            </span>
          </div>
        ) : null}

        {open === 'set' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <select
              className="ga-input"
              style={{ maxWidth: 160 }}
              value={customSet ? '__custom' : value}
              onChange={(e) => {
                const v = e.target.value
                setCustomSet(v === '__custom')
                setValue(v === '__custom' ? '' : v)
              }}
            >
              {columns.map((s) => (
                <option key={s || 'neutral'} value={s}>
                  {s || t('— neutral —')}
                </option>
              ))}
              <option value="__custom">{t('— a new set —')}</option>
            </select>
            {!customSet ? null : (
              <input
                className="ga-input"
                style={{ maxWidth: 160 }}
                placeholder={t('new set')}
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            )}
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy}
              onClick={() => run(clip, { set: value.trim().toLowerCase() })}
            >
              {t('Apply')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAction(null)}>
              {t('Cancel')}
            </button>
          </div>
        ) : null}

        {open === 'library' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.82em' }}>
              {other === 'free'
                ? t('Move to the free library? Everything there is committed to git — only do this when the licence allows passing the raw file on.')
                : t('Move to the licensed library? It stays local and is never committed.')}
            </span>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={busy}
              onClick={() => run(clip, { library: other })}
            >
              {t('Move')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAction(null)}>
              {t('Cancel')}
            </button>
          </div>
        ) : null}

        {open === 'delete' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.82em' }}>
              {t('Delete this file?')}
              {usage[clip.kind]?.length
                ? ` ${t('Poses that play this kind')}: ${usage[clip.kind].join(', ')}`
                : ''}
            </span>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              disabled={busy}
              onClick={() => run(clip, null)}
            >
              {t('Delete')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={() => setAction(null)}>
              {t('Cancel')}
            </button>
          </div>
        ) : null}
      </li>
    )
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(320px, 1.3fr) minmax(320px, 1fr)',
        gap: 14,
        alignItems: 'stretch',
        flex: 1,
        minHeight: 0,
      }}
    >
      {/* ── the matrix ── */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, minHeight: 0 }}>
        <p className="ga-sched-muted" style={{ margin: 0 }}>
          {t('Every installed clip by kind, set and library. A kind present in both libraries is served from the licensed one. A row without any clip is named by a pose but backed by no file — figures fall back to idle there.')}
        </p>

        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            className="ga-input"
            style={{ maxWidth: 180 }}
            placeholder={t('Search kind…')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            className="ga-input"
            style={{ maxWidth: 140 }}
            value={libFilter}
            onChange={(e) => setLibFilter(e.target.value)}
          >
            <option value="">{t('all libraries')}</option>
            <option value="free">{t('free')}</option>
            <option value="licensed">{t('licensed')}</option>
          </select>
          <select
            className="ga-input"
            style={{ maxWidth: 140 }}
            value={setFilter}
            onChange={(e) => setSetFilter(e.target.value)}
          >
            <option value="*">{t('all sets')}</option>
            {columns.map((s) => (
              <option key={s || 'neutral'} value={s}>
                {s || t('neutral')}
              </option>
            ))}
          </select>
          <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: '0.8em' }}>
            <input
              type="checkbox"
              checked={onlyUsed}
              onChange={(e) => {
                setOnlyUsed(e.target.checked)
                if (e.target.checked) setOnlyUnused(false)
              }}
            />
            <span>{t('only used')}</span>
          </label>
          <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: '0.8em' }}>
            <input
              type="checkbox"
              checked={onlyUnused}
              onChange={(e) => {
                setOnlyUnused(e.target.checked)
                if (e.target.checked) setOnlyUsed(false)
              }}
            />
            <span>{t('only unused')}</span>
          </label>
        </div>

        <div style={{ overflow: 'auto', minHeight: 0, flex: 1 }}>
          <table className="ga-sched-table">
            <thead>
              <tr>
                <th>{t('Clip kind')}</th>
                {columns.map((s) => (
                  <th key={s || 'neutral'}>{s || t('neutral')}</th>
                ))}
                <th>{t('Used by')}</th>
              </tr>
            </thead>
            <tbody>
              {!shown.length ? (
                <tr>
                  <td colSpan={columns.length + 2}>{t('No clips')}</td>
                </tr>
              ) : null}
              {shown.map((r) => (
                <tr
                  key={r.kind}
                  onClick={() => pick(r.kind)}
                  style={{
                    cursor: 'pointer',
                    background: r.kind === selected ? 'var(--bg-secondary, #21262d)' : undefined,
                  }}
                >
                  <td>
                    <code style={{ color: r.missing ? 'var(--warn, #d29922)' : undefined }}>
                      {r.kind}
                    </code>
                    {r.pair ? (
                      <span className="ga-tag" style={{ marginLeft: 4 }} title={t('Pair animation — needs a partner')}>
                        {t('pair')}
                      </span>
                    ) : null}
                    {r.missing ? (
                      <span className="ga-tag ga-tag-missing" style={{ marginLeft: 4 }}>
                        {t('missing')}
                      </span>
                    ) : null}
                  </td>
                  {columns.map((s) => (
                    <td
                      key={s || 'neutral'}
                      onClick={(e) => {
                        e.stopPropagation()
                        pick(r.kind, s)
                      }}
                    >
                      {cellNode(r, s)}
                    </td>
                  ))}
                  <td title={r.used.join(', ')}>{r.used.length || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── the selected kind ── */}
      <section style={{ minWidth: 0, minHeight: 0, overflowY: 'auto', paddingRight: 4 }}>
        {!row ? (
          <div className="ga-placeholder">{t('Pick a kind to see its files.')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <h3 style={{ margin: '0 0 2px' }}>{row.kind}</h3>
              <div className="ga-hint">
                {row.used.length
                  ? `${t('Used by')}: ${row.used.join(', ')}`
                  : t('No pose entry plays this kind.')}
              </div>
            </div>

            {error ? (
              <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)' }}>
                {error}
              </div>
            ) : null}

            {row.missing ? (
              <div className="ga-form-hint" style={{ color: 'var(--warn, #d29922)' }}>
                {t('No file for this kind in any set — import one, or point the poses above at another kind.')}
              </div>
            ) : (
              <>
                {rowSets.length > 1 ? (
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {rowSets.map((s) => (
                      <button
                        key={s || 'neutral'}
                        type="button"
                        className={`ga-btn ga-btn-sm${previewSet === s ? ' ga-btn-primary' : ''}`}
                        onClick={() => setPreviewSet(s)}
                      >
                        {s || t('neutral')}
                      </button>
                    ))}
                  </div>
                ) : null}
                <ClipPreview
                  key={`${row.kind}:${previewSet}:${seq}`}
                  kind={row.kind}
                  set={previewSet}
                  height={280}
                />

                {rowSets.map((s) => (
                  <div key={s || 'neutral'}>
                    <h4 style={{ margin: '6px 0 2px' }}>{s || t('neutral')}</h4>
                    <ul className="ga-list" style={{ minWidth: 0 }}>
                      {row.clips.filter((c) => (c.set || '') === s).map(clipNode)}
                    </ul>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
