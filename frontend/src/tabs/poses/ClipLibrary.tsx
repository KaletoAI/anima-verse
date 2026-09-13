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
 * Two libraries, one winner: a LICENSED file HIDES a free file of the same
 * name (the local, untracked library wins over the files in git). The hidden
 * one is not in the listing at all — the server resolves the collision before
 * it answers, so a cell tagged "free" and "licensed" holds files of DIFFERENT
 * names, never two versions of one.
 *
 * On top of the matrix sits the LOCOMOTION block: which kind every figure —
 * NPC and avatar alike — plays for `walk` / `run` / `idle` when neither the
 * ground nor the server names a clip. World-independent like the clips
 * (`shared/config/locomotion_clips.json`); a ground's own move/idle clip
 * (water → swim) keeps its precedence in the client. The mapping rides on the
 * listing (`locomotion`) and is fetched here — the listing prop's type does
 * not carry it.
 *
 * Per file the detail column carries the LOOP switch: whether a clip repeats
 * or holds its last frame is the admin's decision AFTER the import
 * (plan-animationen-echtzeit-stehplatz.md E5), not the importer's
 * measurement. It is stored in the `<kind>.json` sidecar and therefore holds
 * for the whole kind in that set — both halves of a pair, every variant.
 *
 * A rename or move onto a name that is already taken is not an error the
 * admin has to work around: the server answers 409, the action box stays open
 * and offers "Replace", which repeats the same call with `overwrite` and lets
 * the incoming file take the place of the one lying there.
 *
 * Under the preview sit the ORIENTATION dials: turn, tilt, roll and height.
 * The preview shows them live against the calibration box of a place type,
 * and "Apply orientation" BAKES them into the file — there is no second
 * truth, because the clients read a pair's root path out of the clip itself.
 * The import's own dial is gone by then and most mocap sources with it, so
 * this is the only way a clip that lies across the bed gets straightened.
 *
 *   GET    /assets/animation-clips                     … + {locomotion}
 *   PUT    /assets/animation-clips/locomotion          {walk?, run?, idle?}
 *   PATCH  /assets/animation-clips/{library}/{rel}     {kind?, set?, library?, loop?, overwrite?}
 *   POST   /assets/animation-clips/{library}/{rel}/orient  {yaw_deg?, tilt_deg?, roll_deg?, height_cm?}
 *   DELETE /assets/animation-clips/{library}/{rel}
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ClipPreview } from './ClipPreview'
import { SliderInput } from '../../components/SliderInput'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut } from '../../lib/api'
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

/** The three roles, in the order the block shows them; the label is the
 *  disambiguated source string ("Run" alone already means "execute"). */
const LOCOMOTION_ROLES: Array<{ role: 'walk' | 'run' | 'idle'; label: string }> = [
  { role: 'walk', label: 'Walk clip' },
  { role: 'run', label: 'Run clip' },
  { role: 'idle', label: 'Idle clip' },
]

interface PoseRef {
  key: string
  animation: string
}

export function ClipLibrary({
  listing,
  poses,
  onReload,
  rootDropOf,
}: {
  listing: ClipListing
  /** the pose catalog entries — the "Used by" column reads their `animation` */
  poses: PoseRef[]
  /** re-fetch the listing (and the catalog) after a rename/move/delete */
  onReload: () => Promise<void> | void
  /** `root_drop` of a place type (fraction of the figure height) — the preview
   *  sinks the figure that far under the calibration box's top, the way the
   *  server places it. Without it the figure would rest ON the bed. */
  rootDropOf?: (group: string) => number
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
  // The body of a rename/move the server refused with 409 (the name is taken).
  // It is kept so the "Replace" button can send exactly that call again, this
  // time with `overwrite` — the collision is a question, not a dead end.
  const [conflict, setConflict] = useState<Record<string, string | boolean> | null>(null)
  const [busy, setBusy] = useState(false)
  // Bumped after every write so the preview reloads the (possibly renamed) clip
  const [seq, setSeq] = useState(0)
  // The locomotion mapping as the server resolves it, and the edited copy
  const [locomotion, setLocomotion] = useState<Record<string, string> | null>(null)
  const [locoDraft, setLocoDraft] = useState<Record<string, string>>({})
  const [locoBusy, setLocoBusy] = useState(false)
  const [locoError, setLocoError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  // The orientation dials of the selected clip: degrees, degrees, degrees and
  // centimetres. They are a DRAFT — the preview turns live, nothing is written
  // until "Apply orientation".
  const [yawDeg, setYawDeg] = useState(0)
  const [tiltDeg, setTiltDeg] = useState(0)
  const [rollDeg, setRollDeg] = useState(0)
  const [heightCm, setHeightCm] = useState(0)
  // Which place type the preview draws as the calibration box — a view
  // setting, never sent to the server.
  const [footprint, setFootprint] = useState('')
  const [orientBusy, setOrientBusy] = useState(false)
  const [orientError, setOrientError] = useState('')
  const [orientSeconds, setOrientSeconds] = useState<number | null>(null)

  // Fetched with every new listing: a rename or delete may have taken a
  // configured kind away, and the block must show what is in force now.
  useEffect(() => {
    let alive = true
    apiGet<{ locomotion?: Record<string, string> }>('/assets/animation-clips')
      .then((data) => {
        if (!alive) return
        const map = data.locomotion || {}
        setLocomotion(map)
        setLocoDraft(map)
        setLocoError('')
      })
      .catch((e) => {
        if (alive) setLocoError((e as Error).message)
      })
    return () => {
      alive = false
    }
  }, [listing])

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

  /** What a locomotion role may point at: every kind a SOLO file backs — a
   *  pair needs a partner, a missing kind has nothing to play. */
  const locoKinds = useMemo(
    () => rows.filter((r) => !r.pair && !r.missing).map((r) => r.kind),
    [rows],
  )
  const locoDirty = useMemo(
    () => !!locomotion && LOCOMOTION_ROLES.some(({ role }) => (locoDraft[role] || '') !== (locomotion[role] || '')),
    [locoDraft, locomotion],
  )

  const saveLocomotion = useCallback(async () => {
    if (locoBusy || !locomotion) return
    setLocoBusy(true)
    setLocoError('')
    try {
      const body: Record<string, string> = {}
      for (const { role } of LOCOMOTION_ROLES) {
        if ((locoDraft[role] || '') !== (locomotion[role] || '')) body[role] = locoDraft[role] || ''
      }
      const res = await apiPut<{ locomotion: Record<string, string> }>(
        '/assets/animation-clips/locomotion',
        body,
      )
      setLocomotion(res.locomotion)
      setLocoDraft(res.locomotion)
    } catch (e) {
      setLocoError((e as Error).message)
    } finally {
      setLocoBusy(false)
    }
  }, [locoBusy, locoDraft, locomotion])

  const refresh = useCallback(async () => {
    if (refreshing) return
    setRefreshing(true)
    try {
      await onReload()
    } finally {
      setRefreshing(false)
    }
  }, [onReload, refreshing])

  /** Sets the selected kind actually has a clip in — the preview's switch. */
  const rowSets = useMemo(
    () => (row ? orderSets(Array.from(new Set(row.clips.map((c) => c.set || '')))) : []),
    [row],
  )

  /** Back to an untouched clip: the dials are a draft for ONE file. */
  const resetDials = useCallback(() => {
    setYawDeg(0)
    setTiltDeg(0)
    setRollDeg(0)
    setHeightCm(0)
    setOrientError('')
    setOrientSeconds(null)
  }, [])

  const pick = useCallback(
    (kind: string, set?: string) => {
      setSelected(kind)
      resetDials()
      // Clicking the row (no column) previews the set the kind actually has —
      // neutral when there is one, otherwise the first that exists.
      const own = clips.filter((c) => c.kind === kind).map((c) => c.set || '')
      setPreviewSet(set !== undefined ? set : orderSets(Array.from(new Set(own)))[0] || '')
      setAction(null)
      setError('')
      setConflict(null)
    },
    [clips, resetDials],
  )

  /** The file the dials act on: the previewed set's clip, and for a pair its
   *  A half — the server turns the B half with it, in one Blender run. */
  const orientTarget = useMemo(
    () => (row
      ? row.clips.find((c) => (c.set || '') === previewSet && (c.role || '') !== 'b') || null
      : null),
    [previewSet, row],
  )
  const orientDirty = !!(yawDeg || tiltDeg || rollDeg || heightCm)
  // The baked angles live in the sidecar, so a clip without one has nowhere to
  // put them — the block says so instead of earning a 400 after Apply.
  const orientLocked = orientBusy || orientTarget?.has_sidecar === false

  const applyOrientation = useCallback(async () => {
    if (!orientTarget || orientBusy || !orientDirty) return
    setOrientBusy(true)
    setOrientError('')
    try {
      const res = await apiPost<{ seconds?: number }>(`${clipPath(orientTarget)}/orient`, {
        yaw_deg: yawDeg, tilt_deg: tiltDeg, roll_deg: rollDeg, height_cm: heightCm,
      })
      setOrientSeconds(typeof res.seconds === 'number' ? res.seconds : null)
      setYawDeg(0)
      setTiltDeg(0)
      setRollDeg(0)
      setHeightCm(0)
      // The file keeps its URL, so the preview has to be rebuilt AND the
      // clip re-fetched — `seq` does both (component key + cache buster).
      setSeq((n) => n + 1)
      await onReload()
    } catch (e) {
      setOrientError((e as Error).message)
    } finally {
      setOrientBusy(false)
    }
  }, [heightCm, onReload, orientBusy, orientDirty, orientTarget, rollDeg, tiltDeg, yawDeg])

  /** What the FILE already carries — the import's dial plus every earlier
   *  apply. A new angle is added to this, not to zero, so it is named. */
  const bakedNote = useMemo(() => {
    const o = orientTarget?.orientation
    if (!o) return ''
    const parts = [
      o.yaw_deg ? `${t('turn')} ${o.yaw_deg}°` : '',
      o.tilt_deg ? `${t('tilt')} ${o.tilt_deg}°` : '',
      o.roll_deg ? `${t('roll')} ${o.roll_deg}°` : '',
      typeof o.floor_shift_cm === 'number' ? `${t('floor shift')} ${o.floor_shift_cm} cm` : '',
    ].filter(Boolean)
    return parts.length ? parts.join(' · ') : t('nothing turned yet')
  }, [orientTarget, t])

  const openAction = useCallback((clip: ApiClipRow, type: ActionKind) => {
    setError('')
    setConflict(null)
    setAction({ rel: `${libraryOf(clip)}/${relOf(clip)}`, type })
    setValue(type === 'kind' ? clip.kind : type === 'set' ? clip.set || '' : '')
    setCustomSet(false)
  }, [])

  const run = useCallback(
    async (clip: ApiClipRow, body: Record<string, string | boolean> | null) => {
      if (busy) return
      setBusy(true)
      setError('')
      setConflict(null)
      try {
        if (body) await apiPatch(clipPath(clip), body)
        else await apiDelete(clipPath(clip))
        setAction(null)
        setSeq((n) => n + 1)
        await onReload()
        // A renamed kind carries the selection with it, so the detail pane
        // does not fall back to the placeholder after every rename.
        if (typeof body?.kind === 'string') setSelected(body.kind)
        if (typeof body?.set === 'string') setPreviewSet(body.set)
      } catch (e) {
        setError((e as Error).message)
        // 409 is the ONE refusal with an answer: the name at the target is
        // taken. The action box stays open and offers "Replace", which is
        // this very body once more with `overwrite`.
        if (body && e instanceof ApiError && e.status === 409) setConflict(body)
      } finally {
        setBusy(false)
      }
    },
    [busy, onReload],
  )

  /** The offer after a 409 — shown inside the action box that ran into it. */
  const replaceNode = (clip: ApiClipRow) =>
    conflict ? (
      <>
        <span className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>
          {t('That name is taken. Replace overwrites the file lying there — it is gone for good.')}
        </span>
        <button
          type="button"
          className="ga-btn ga-btn-sm ga-btn-danger"
          disabled={busy}
          onClick={() => run(clip, { ...conflict, overwrite: true })}
        >
          {t('Replace')}
        </button>
      </>
    ) : null

  const cellNode = (r: Row, col: string) => {
    const cell = r.cells[col]
    if (!cell || !cell.all.length) {
      return <span style={{ opacity: 0.25 }}>·</span>
    }
    const n = variants(cell.all)
    return (
      <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center', flexWrap: 'wrap' }}>
        {cell.free.length ? (
          <span className="ga-tag ga-tag-tier" title={t('free library (tracked in git)')}>
            {t('free')}
          </span>
        ) : null}
        {cell.licensed.length ? (
          <span className="ga-tag ga-tag-tier" title={t('licensed library (local only)')}>
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
        <div className="ga-form-hint" style={{ marginTop: 2 }}>{facts.join(' · ')}</div>
        <label
          style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}
          title={clip.has_sidecar === false
            ? t('Without a sidecar there is nowhere to store the flag — import the clip again.')
            : t('Applies to the whole kind in this set: both halves of a pair and every variant.')}
        >
          <input
            type="checkbox"
            checked={!!clip.loop}
            disabled={busy || clip.has_sidecar === false}
            onChange={(e) => run(clip, { loop: e.target.checked })}
          />
          <span>{t('Loop')}</span>
          <span className="ga-form-hint">{t('Repeat the clip; off = hold the last frame')}</span>
        </label>
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
            {replaceNode(clip)}
            <span className="ga-hint">
              {t('Lowercase letters, digits, space, "_" and "-"; never "__" (that separates the pair halves) and never a trailing "_<number>" (that is the variant numbering).')}
            </span>
            {usage[clip.kind]?.length ? (
              <span className="ga-hint" style={{ color: 'var(--warn, #d29922)' }}>
                {`${t('Poses that play this kind')}: ${usage[clip.kind].join(', ')} — ${t('they are not updated automatically and will find no clip under the old name.')}`}
              </span>
            ) : null}
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
            {replaceNode(clip)}
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
            {replaceNode(clip)}
          </div>
        ) : null}

        {open === 'delete' ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.82em' }}>
              {clip.role
                ? t('Delete this file? It is one half of a pair — both halves go together.')
                : t('Delete this file?')}
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
          {t('Every installed clip by kind, set and library. A licensed file hides a free one of the same name: only the licensed one is listed and only it is played. A row without any clip is named by a pose but backed by no file — figures fall back to idle there.')}
        </p>

        {/* ── the locomotion roles ── */}
        <div
          style={{
            border: '1px solid var(--border, #30363d)',
            borderRadius: 6,
            padding: '8px 10px',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <strong>{t('Locomotion clips')}</strong>
            <span className="ga-hint">
              {t('What every figure — NPC and avatar alike — plays while walking, running and standing, in every world. A ground with its own clip (water: swim) still wins.')}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            {LOCOMOTION_ROLES.map(({ role, label }) => {
              const current = locoDraft[role] || role
              const known = locoKinds.includes(current)
              return (
                <label key={role} style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: '0.85em' }}>
                  <span>{t(label)}</span>
                  <select
                    className="ga-input"
                    style={{ maxWidth: 170 }}
                    value={current}
                    disabled={!locomotion || locoBusy}
                    onChange={(e) => setLocoDraft((d) => ({ ...d, [role]: e.target.value }))}
                  >
                    {known ? null : (
                      <option value={current}>{`${current} (${t('missing')})`}</option>
                    )}
                    {locoKinds.map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                  </select>
                </label>
              )
            })}
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={!locoDirty || locoBusy}
              onClick={() => void saveLocomotion()}
            >
              {locoBusy ? t('Saving…') : t('Save')}
            </button>
            {locoDirty && !locoBusy ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => setLocoDraft(locomotion || {})}
              >
                {t('Cancel')}
              </button>
            ) : null}
          </div>
          {locoError ? (
            <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)' }}>
              {locoError}
            </div>
          ) : null}
        </div>

        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={refreshing}
            onClick={() => void refresh()}
            title={t('Re-read the clip libraries from disk')}
          >
            {t('Refresh')}
          </button>
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
                  importYaw={yawDeg}
                  importTilt={tiltDeg}
                  importRoll={rollDeg}
                  importHeightM={heightCm / 100}
                  footprint={footprint}
                  rootDrop={footprint ? (rootDropOf?.(footprint) ?? 0) : 0}
                  bust={seq}
                />

                {/* ── the orientation dials ── */}
                {orientTarget ? (
                  <div
                    style={{
                      border: '1px solid var(--border, #30363d)',
                      borderRadius: 6,
                      padding: '8px 10px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 6,
                    }}
                    title={orientTarget.has_sidecar === false
                      ? t('Without a sidecar there is nowhere to store the flag — import the clip again.')
                      : undefined}
                  >
                    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                      <strong>{t('Orientation')}</strong>
                      <span className="ga-hint">
                        {t('Turns and lifts the clip in the FILE — both halves of a pair together. The preview shows it live, Apply writes it; the sources of most clips are gone, so this replaces a re-import.')}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                      <SliderInput
                        label={t('Turn the clip')}
                        unit="°"
                        title={t('Degrees the clip turns about the vertical — the import dial, applied after the fact. A lying clip is aimed at the bed with it.')}
                        min={-180}
                        max={180}
                        step={5}
                        fineStep={1}
                        value={yawDeg}
                        onChange={setYawDeg}
                        disabled={orientLocked}
                        sliderWidth="auto"
                        sliderStyle={{ flex: 1, minWidth: 90 }}
                        style={{ display: 'flex', flex: '1 1 260px' }}
                      />
                      <button type="button" className="ga-btn ga-btn-sm" disabled={orientLocked}
                        onClick={() => setYawDeg((v) => ((v - 90 + 540) % 360) - 180)}>−90°</button>
                      <button type="button" className="ga-btn ga-btn-sm" disabled={orientLocked}
                        onClick={() => setYawDeg((v) => ((v + 90 + 540) % 360) - 180)}>+90°</button>
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                      <SliderInput
                        label={t('Tilt')}
                        unit="°"
                        title={t('Degrees the clip tips forward — a standing figure bows, a lying one rolls onto its face. Positive tips the head towards the clip’s forward axis.')}
                        min={-180}
                        max={180}
                        step={5}
                        fineStep={1}
                        value={tiltDeg}
                        onChange={setTiltDeg}
                        disabled={orientLocked}
                        sliderWidth="auto"
                        sliderStyle={{ flex: 1, minWidth: 70 }}
                        style={{ display: 'flex', flex: '1 1 200px' }}
                      />
                      <SliderInput
                        label={t('Roll')}
                        unit="°"
                        title={t('Degrees the clip tips sideways. Positive tips the figure to its own right.')}
                        min={-180}
                        max={180}
                        step={5}
                        fineStep={1}
                        value={rollDeg}
                        onChange={setRollDeg}
                        disabled={orientLocked}
                        sliderWidth="auto"
                        sliderStyle={{ flex: 1, minWidth: 70 }}
                        style={{ display: 'flex', flex: '1 1 200px' }}
                      />
                      <SliderInput
                        label={t('Height')}
                        unit="cm"
                        title={t('Centimetres the clip is lifted after the turn — a tilted figure that sinks into the floor is raised back out with it.')}
                        min={-50}
                        max={50}
                        step={1}
                        value={heightCm}
                        onChange={setHeightCm}
                        disabled={orientLocked}
                        sliderWidth="auto"
                        sliderStyle={{ flex: 1, minWidth: 70 }}
                        style={{ display: 'flex', flex: '1 1 200px' }}
                      />
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                      <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <span className="ga-hint">{t('Turn against')}</span>
                        <select className="ga-input" value={footprint}
                          onChange={(e) => setFootprint(e.target.value)}>
                          <option value="">{t('grid only')}</option>
                          <option value="lie">{t('bed / lying surface')}</option>
                          <option value="seat">{t('seat')}</option>
                        </select>
                      </label>
                      <button
                        type="button"
                        className="ga-btn ga-btn-sm ga-btn-primary"
                        disabled={!orientDirty || orientLocked}
                        onClick={() => void applyOrientation()}
                      >
                        {orientBusy ? t('Applying…') : t('Apply orientation')}
                      </button>
                      <button
                        type="button"
                        className="ga-btn ga-btn-sm"
                        disabled={!orientDirty || orientLocked}
                        onClick={resetDials}
                      >
                        {t('Reset dials')}
                      </button>
                      {orientSeconds !== null && !orientBusy ? (
                        <span className="ga-hint">{`${t('written in')} ${orientSeconds.toFixed(1)} s`}</span>
                      ) : null}
                    </div>
                    <div className="ga-form-hint">
                      {orientTarget.has_sidecar === false
                        ? t('Without a sidecar there is nowhere to store the flag — import the clip again.')
                        : `${t('Already baked into the file')}: ${bakedNote}`}
                    </div>
                    {orientError ? (
                      <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)' }}>
                        {orientError}
                      </div>
                    ) : null}
                  </div>
                ) : null}

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
