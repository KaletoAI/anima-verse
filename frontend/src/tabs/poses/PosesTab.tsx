/**
 * PosesTab — the editor for the two finite render-key axes.
 *
 * `pose` and `expression` are the ONLY keys under which image variants are
 * cached and animation clips are resolved. Free text never creates an entry:
 * text the resolver could not absorb lands in the CANDIDATES list below, and
 * grows the catalog only when an admin approves it — as a new entry or as a
 * synonym of an existing one.
 *
 * The animation vocabulary (pose axis only) is NOT hardcoded: the dropdown is
 * filled from the clips that actually exist (/assets/animation-clips).
 *
 * Catalog:    GET/POST /poses · PUT/DELETE /poses/{key}   (?axis=…)
 * Candidates: GET /poses/candidates · POST /poses/candidates/approve|dismiss
 * Images:     POST /poses/expression-images/clear
 *
 * The image cache is keyed by the catalog KEY, not by the prompt text, so
 * editing an entry's prompt does NOT invalidate the images already rendered
 * under it — that is what the clear button next to the editor is for.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ClipCatalog } from './ClipCatalog'
import { ClipInbox } from './ClipInbox'
import { ClipPreview } from './ClipPreview'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ListHeader } from '../../components/ListHeader'

type Axis = 'pose' | 'expression'
/** The tab has three surfaces: the catalog entries, the CMU clip pool the
 *  animation kinds themselves come from, and the inbox of foreign files
 *  waiting to be imported. */
type View = 'entries' | 'catalog' | 'inbox'

/** One place type: the vocabulary a marker speaks. `root_drop` is a FRACTION
 *  of the figure height, so it reads back as metres against a 1.70 m figure. */
interface PlaceType {
  label: string
  root_drop: number
  default: string
}

interface Entry {
  key: string
  prompt: string
  synonyms: string[]
  animation: string
  solo: boolean
  is_default?: boolean
  axis?: Axis
  /** place fields — pose axis only, an expression has no place */
  group?: string
  /** slots of the anchor marker a PAIR pose consumes (solo poses: always 1) */
  places?: 1 | 2
  /** degrees the pair clip's frame turns against the marker facing */
  yaw_offset?: number
}

interface CatalogData {
  entries: Entry[]
  kinds: string[]
  /** kinds that exist as a PAIR clip (two halves) — two-person poses */
  pair_kinds?: string[]
  /** place types, keyed by group id (pose axis only) */
  groups?: Record<string, PlaceType>
  problems: string[]
}

interface Candidate {
  raw_text: string
  nearest_key: string
  distance: number | null
  count: number
  first_seen: string
  last_seen: string
}

const EMPTY: Entry = { key: '', prompt: '', synonyms: [], animation: '', solo: true, group: '' }

/** Figure height the root drop is read back against — the reference figure of
 *  every metre readout in the admin UI. */
const REFERENCE_HEIGHT_M = 1.7

export function PosesTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [axis, setAxis] = useState<Axis>('pose')
  const [view, setView] = useState<View>('entries')
  const [data, setData] = useState<CatalogData>({ entries: [], kinds: [], problems: [] })
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [selected, setSelected] = useState<string>('')
  const [draft, setDraft] = useState<Entry | null>(null)
  const [isNew, setIsNew] = useState(false)
  // raw_text of the candidate the open draft was started from ('' = plain new entry)
  const [approveOf, setApproveOf] = useState('')
  const [search, setSearch] = useState('')
  const [onlyMissing, setOnlyMissing] = useState(false)
  // '' = no place-type filter on the list
  const [groupFilter, setGroupFilter] = useState('')
  // Editable copy of the whole `groups` block — PUT /poses/groups replaces it
  // as a whole, so it is edited as a whole and saved with one button.
  const [groupsDraft, setGroupsDraft] = useState<Record<string, PlaceType>>({})
  const [newGroupKey, setNewGroupKey] = useState('')
  // The place-type editor is collapsed by default: it lives above the catalog
  // list in the narrow left column and would otherwise squeeze the list.
  const [showGroups, setShowGroups] = useState(false)
  const [confirmDismiss, setConfirmDismiss] = useState<string | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [busy, setBusy] = useState(false)

  const isPose = axis === 'pose'

  const load = useCallback(async () => {
    try {
      setData(await apiGet<CatalogData>(`/poses?axis=${axis}`))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
    try {
      const r = await apiGet<{ candidates: Candidate[] }>(`/poses/candidates?axis=${axis}`)
      setCandidates(r.candidates || [])
    } catch {
      setCandidates([])
    }
  }, [axis, t, toast])

  useEffect(() => {
    load()
  }, [load])

  // Switching the axis drops the open draft — the two catalogs share no keys.
  useEffect(() => {
    setDraft(null)
    setSelected('')
    setIsNew(false)
    setApproveOf('')
    setConfirmDismiss(null)
    setGroupFilter('')
  }, [axis])

  // The server is the truth for the place types: every (re)load restarts the
  // editable copy from what was just fetched.
  useEffect(() => {
    setGroupsDraft({ ...(data.groups || {}) })
    setNewGroupKey('')
  }, [data.groups])

  const list = useMemo(() => {
    const q = search.trim().toLowerCase()
    return data.entries.filter((p) => {
      if (isPose && onlyMissing && p.animation) return false
      if (isPose && groupFilter && (p.group || '') !== groupFilter) return false
      if (!q) return true
      return (
        p.key.includes(q) ||
        p.prompt.toLowerCase().includes(q) ||
        p.synonyms.some((s) => s.includes(q))
      )
    })
  }, [data.entries, search, onlyMissing, groupFilter, isPose])

  const missingCount = useMemo(
    () => data.entries.filter((p) => !p.animation).length,
    [data.entries],
  )

  const select = useCallback(
    (key: string) => {
      const p = data.entries.find((x) => x.key === key)
      if (!p) return
      setSelected(key)
      setIsNew(false)
      setApproveOf('')
      setDraft({ ...p, synonyms: [...p.synonyms] })
    },
    [data.entries],
  )

  const addNew = useCallback(() => {
    setSelected('')
    setIsNew(true)
    setApproveOf('')
    setDraft({ ...EMPTY })
  }, [])

  /** "Create pose entry" out of the catalog browser: back to the entry editor
   *  with a fresh pose draft whose animation is the kind just imported. The
   *  axis is already 'pose' — switching INTO the catalog forces it, so the
   *  axis-change effect below cannot wipe the draft right after it was set. */
  const startFromClip = useCallback(
    async (animation: string) => {
      setView('entries')
      setSelected('')
      setIsNew(true)
      setApproveOf('')
      setDraft({ ...EMPTY, key: animation, animation })
      await load()
    },
    [load],
  )

  const startApprove = useCallback((c: Candidate) => {
    setSelected('')
    setIsNew(true)
    setApproveOf(c.raw_text)
    setDraft({ ...EMPTY, key: c.raw_text })
  }, [])

  const save = useCallback(async () => {
    if (!draft) return
    const key = draft.key.trim().toLowerCase()
    if (!key || !draft.prompt.trim()) {
      toast(t('Key and prompt text are required'), 'error')
      return
    }
    if (isPose && !draft.animation.trim()) {
      toast(t('An animation kind is required for poses'), 'error')
      return
    }
    if (isPose && !draft.group) {
      toast(t('A place type is required for poses'), 'error')
      return
    }
    try {
      const body = {
        axis,
        key,
        prompt: draft.prompt,
        synonyms: draft.synonyms,
        ...(isPose
          ? {
              animation: draft.animation,
              solo: draft.solo,
              group: draft.group,
              // Pair fields only: a solo pose occupies one place and never
              // turns, and the server drops them again when solo is set.
              ...(draft.solo
                ? {}
                : { places: draft.places ?? 2, yaw_offset: draft.yaw_offset ?? 0 }),
            }
          : {}),
      }
      if (approveOf) {
        await apiPost('/poses/candidates/approve', { ...body, raw_text: approveOf })
        toast(t('Candidate approved'))
      } else if (isNew) {
        await apiPost('/poses', body)
        toast(t('Saved'))
      } else {
        await apiPut(`/poses/${encodeURIComponent(key)}?axis=${axis}`, body)
        toast(t('Saved'))
      }
      setIsNew(false)
      setApproveOf('')
      setSelected(key)
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [approveOf, axis, draft, isNew, isPose, load, t, toast])

  const remove = useCallback(async () => {
    if (!draft || isNew) return
    try {
      await apiDelete(`/poses/${encodeURIComponent(draft.key)}?axis=${axis}`)
      toast(t('Deleted'))
      setDraft(null)
      setSelected('')
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [axis, draft, isNew, load, t, toast])

  const asSynonym = useCallback(
    async (c: Candidate, target: string) => {
      if (!target || busy) return
      setBusy(true)
      try {
        await apiPost('/poses/candidates/approve', {
          axis,
          raw_text: c.raw_text,
          as_synonym_of: target,
        })
        toast(t('Added as synonym') + `: ${target}`)
        await load()
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(false)
      }
    },
    [axis, busy, load, t, toast],
  )

  const dismiss = useCallback(
    async (c: Candidate) => {
      if (busy) return
      setBusy(true)
      try {
        await apiPost('/poses/candidates/dismiss', { axis, raw_text: c.raw_text })
        setCandidates((prev) => prev.filter((x) => x.raw_text !== c.raw_text))
        setConfirmDismiss(null)
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(false)
      }
    },
    [axis, busy, t, toast],
  )

  const clearExpressionImages = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      const r = await apiPost<{ images_deleted?: number }>(
        '/poses/expression-images/clear',
        {},
      )
      toast(`${t('Rendered expression images cleared')}: ${r?.images_deleted ?? 0}`)
      setConfirmClear(false)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [busy, t, toast])

  const upd = useCallback(<K extends keyof Entry>(k: K, v: Entry[K]) => {
    setDraft((prev) => (prev ? { ...prev, [k]: v } : prev))
  }, [])

  // ── Place types ────────────────────────────────────────────────────────
  /** How many catalog entries name each place type — a type still in use
   *  cannot be removed, because its poses would become unplaceable. */
  const groupUsage = useMemo(() => {
    const out: Record<string, number> = {}
    for (const p of data.entries) {
      const g = p.group || ''
      if (g) out[g] = (out[g] || 0) + 1
    }
    return out
  }, [data.entries])

  const patchGroup = useCallback((key: string, patch: Partial<PlaceType>) => {
    setGroupsDraft((prev) =>
      prev[key] ? { ...prev, [key]: { ...prev[key], ...patch } } : prev,
    )
  }, [])

  const addGroup = useCallback(() => {
    const key = newGroupKey.trim().toLowerCase()
    if (!key) {
      toast(t('A key is required for a place type'), 'error')
      return
    }
    if (groupsDraft[key]) {
      toast(t('This place type already exists'), 'error')
      return
    }
    setGroupsDraft((prev) => ({ ...prev, [key]: { label: key, root_drop: 0, default: '' } }))
    setNewGroupKey('')
  }, [groupsDraft, newGroupKey, t, toast])

  const removeGroup = useCallback((key: string) => {
    setGroupsDraft((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
  }, [])

  const saveGroups = useCallback(async () => {
    try {
      await apiPut('/poses/groups', { groups: groupsDraft })
      toast(t('Saved'))
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [groupsDraft, load, t, toast])

  const viewSwitch = (
    <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
      {(['entries', 'catalog', 'inbox'] as View[]).map((v) => (
        <button
          key={v}
          type="button"
          className={`ga-btn ga-btn-sm${view === v ? ' ga-btn-primary' : ''}`}
          onClick={() => {
            // Both import surfaces only ever produce POSE animations — pinning
            // the axis here keeps "create pose entry" from landing on the
            // expression catalog (and from being wiped by the axis-change reset).
            if (v !== 'entries') setAxis('pose')
            setView(v)
          }}
        >
          {v === 'entries' ? t('Entries') : v === 'catalog' ? t('CMU clip catalog') : t('Import files')}
        </button>
      ))}
    </div>
  )

  if (view === 'catalog' || view === 'inbox') {
    // Full-height column: the browser's panes scroll on their own inside it
    // (facets, list, preview+import), the page itself does not — otherwise
    // the import button sat below the browser's bottom edge.
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
        {viewSwitch}
        {view === 'catalog'
          ? <ClipCatalog onCreatePose={startFromClip} />
          : <ClipInbox onCreatePose={startFromClip} />}
      </div>
    )
  }

  return (
    <div className="ga-twocol">
      <aside className="ga-twocol-left">
        {viewSwitch}
        <ListHeader
          title={t('Catalog')}
          onNew={addNew}
          extra={
            confirmClear ? (
              <>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm ga-btn-danger"
                  disabled={busy}
                  onClick={clearExpressionImages}
                >
                  {busy ? t('Clearing…') : t('Really clear?')}
                </button>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  onClick={() => setConfirmClear(false)}
                >
                  {t('Cancel')}
                </button>
              </>
            ) : (
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-danger"
                title={t('Deletes every rendered expression image of every character. The image cache is keyed by the catalog key, not by the prompt text — use this after editing a prompt, otherwise the old images stay.')}
                onClick={() => setConfirmClear(true)}
              >
                {t('Clear rendered expression images')}
              </button>
            )
          }
        />
        <p className="ga-sched-muted">
          {t('The catalog is the closed set of render keys: a pose key carries the body-posture prompt and the animation kind, an expression key the facial prompt. Free text is matched onto a key — it never creates one.')}
        </p>

        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          {(['pose', 'expression'] as Axis[]).map((a) => (
            <button
              key={a}
              type="button"
              className={`ga-btn ga-btn-sm${axis === a ? ' ga-btn-primary' : ''}`}
              onClick={() => setAxis(a)}
            >
              {a === 'pose' ? t('Poses') : t('Expressions')}
            </button>
          ))}
        </div>

        {data.problems.length ? (
          <div className="ga-form-hint" style={{ color: 'var(--warn, #d29922)' }}>
            {data.problems.map((p) => (
              <div key={p}>⚠ {p}</div>
            ))}
          </div>
        ) : null}

        {/* Place types — the finite vocabulary a marker speaks. Collapsed by
            default so it does not eat the catalog list's height. */}
        {isPose ? (
          <div style={{ marginBottom: 8 }}>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              style={{ width: '100%' }}
              onClick={() => setShowGroups((v) => !v)}
            >
              {showGroups ? '▾' : '▸'} {t('Place types')} ({Object.keys(groupsDraft).length})
            </button>
            {showGroups ? (
              <div style={{ marginTop: 6 }}>
                <p className="ga-form-hint" style={{ margin: '0 0 6px' }}>
                  {t('A marker names a place type; every pose belongs to exactly one. Root drop × 1.70 m is how far a figure’s root sinks below the marked surface.')}
                </p>
                {Object.entries(groupsDraft).map(([key, g]) => {
                  const used = groupUsage[key] || 0
                  const poses = data.entries.filter((p) => (p.group || '') === key)
                  return (
                    <div key={key} className="ga-fieldset">
                      <div
                        className="ga-fieldset-title"
                        style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                      >
                        <code style={{ flex: 1 }}>{key}</code>
                        <button
                          type="button"
                          className="ga-btn ga-btn-sm ga-btn-danger"
                          disabled={used > 0}
                          title={
                            used
                              ? `${t('Still in use — reassign these poses first')} (${used})`
                              : t('Remove this place type')
                          }
                          onClick={() => removeGroup(key)}
                        >
                          ×
                        </button>
                      </div>
                      <Field label={t('Label')}>
                        <input
                          className="ga-input"
                          value={g.label}
                          onChange={(e) => patchGroup(key, { label: e.target.value })}
                        />
                      </Field>
                      <Field
                        label={t('Root drop')}
                        hint={`× 1.70 m = ${(g.root_drop * REFERENCE_HEIGHT_M).toFixed(2)} m`}
                      >
                        <input
                          className="ga-input"
                          type="number"
                          min={0}
                          max={1}
                          step={0.001}
                          value={g.root_drop}
                          onChange={(e) =>
                            patchGroup(key, { root_drop: Number(e.target.value) })
                          }
                        />
                      </Field>
                      <Field
                        label={t('Default pose')}
                        hint={t('The pose a click on such a marker sets. It has to be a pose of this place type — only a place type without poses may stay empty.')}
                      >
                        <select
                          className="ga-input"
                          value={g.default}
                          onChange={(e) => patchGroup(key, { default: e.target.value })}
                        >
                          {!poses.length ? (
                            // A place type only just added has no poses yet: a
                            // pose can only name a type that already exists, so
                            // the default arrives with the first pose.
                            <option value="">{t('— none —')}</option>
                          ) : !g.default ? (
                            // With poses the server demands a real default —
                            // show the gap instead of silently rendering the
                            // first pose while the value is still empty.
                            <option value="" disabled>
                              {t('— pick a default pose —')}
                            </option>
                          ) : null}
                          {poses.map((p) => (
                            <option key={p.key} value={p.key}>
                              {p.key}
                            </option>
                          ))}
                        </select>
                      </Field>
                    </div>
                  )
                })}
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <input
                    className="ga-input"
                    style={{ flex: 1, minWidth: 90 }}
                    placeholder={t('new key')}
                    value={newGroupKey}
                    onChange={(e) => setNewGroupKey(e.target.value)}
                  />
                  <button type="button" className="ga-btn ga-btn-sm" onClick={addGroup}>
                    + {t('Place type')}
                  </button>
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm ga-btn-primary"
                    onClick={saveGroups}
                  >
                    {t('Save place types')}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
          <input
            className="ga-input"
            placeholder={t('Search…')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {isPose ? (
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '0.8em' }}>
              <input
                type="checkbox"
                checked={onlyMissing}
                onChange={(e) => setOnlyMissing(e.target.checked)}
              />
              <span>
                {t('Without animation')} ({missingCount})
              </span>
            </label>
          ) : null}
          {isPose && Object.keys(data.groups || {}).length ? (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {Object.entries(data.groups || {}).map(([key, g]) => (
                <button
                  key={key}
                  type="button"
                  className={`ga-btn ga-btn-sm${groupFilter === key ? ' ga-btn-primary' : ''}`}
                  title={`${g.label} (${groupUsage[key] || 0})`}
                  // clicking the active chip clears the filter again
                  onClick={() => setGroupFilter((prev) => (prev === key ? '' : key))}
                >
                  {g.label || key}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <ul className="ga-list">
          {!list.length ? <li className="ga-list-empty">{t('No entries')}</li> : null}
          {list.map((p) => (
            <li key={p.key}>
              <button
                type="button"
                className={`ga-list-row${selected === p.key ? ' is-active' : ''}`}
                onClick={() => select(p.key)}
              >
                <span className="ga-list-row-main">
                  <code>{p.key}</code>
                  {isPose ? (
                    <span
                      className="ga-list-row-sub"
                      style={{ opacity: p.animation && p.group ? 1 : 0.4 }}
                    >
                      — {p.animation || t('no animation')} ·{' '}
                      {p.group || t('no place type')}
                    </span>
                  ) : null}
                </span>
                {isPose && data.pair_kinds?.includes(p.animation) ? (
                  <span className="ga-source" title={t('Pair animation — needs a partner')}>
                    {t('pair')}
                  </span>
                ) : null}
                {p.is_default ? <span className="ga-source">{t('default')}</span> : null}
              </button>
            </li>
          ))}
        </ul>

        {/* Candidates: free text the resolver could not absorb */}
        <div style={{ marginTop: 16 }}>
          <h4 style={{ margin: '0 0 4px' }}>
            {t('Candidates')} ({candidates.length})
          </h4>
          <p className="ga-sched-muted" style={{ marginTop: 0 }}>
            {t('Free text that landed on the default key. Approve it as its own entry, attach it as a synonym, or dismiss it. "Seen" counts first sightings per server run.')}
          </p>
          {!candidates.length ? (
            <div className="ga-list-empty">{t('No open candidates')}</div>
          ) : (
            <ul className="ga-list">
              {candidates.map((c) => (
                <li
                  key={c.raw_text}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                    padding: '6px 0',
                    borderBottom: '1px solid var(--border, #30363d)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <code style={{ wordBreak: 'break-word' }}>{c.raw_text}</code>
                    <span style={{ fontSize: '0.75em', opacity: 0.6, whiteSpace: 'nowrap' }}>
                      {t('seen')} {c.count}× · {t('nearest')}: {c.nearest_key || '–'}
                    </span>
                  </div>
                  {confirmDismiss === c.raw_text ? (
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span style={{ fontSize: '0.82em' }}>{t('Dismiss this candidate?')}</span>
                      <button
                        type="button"
                        className="ga-btn ga-btn-sm ga-btn-danger"
                        disabled={busy}
                        onClick={() => dismiss(c)}
                      >
                        {t('Dismiss')}
                      </button>
                      <button
                        type="button"
                        className="ga-btn ga-btn-sm"
                        onClick={() => setConfirmDismiss(null)}
                      >
                        {t('Cancel')}
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        className="ga-btn ga-btn-sm"
                        onClick={() => startApprove(c)}
                      >
                        {t('Approve')}
                      </button>
                      <select
                        className="ga-input"
                        style={{ maxWidth: 180 }}
                        value=""
                        disabled={busy}
                        onChange={(e) => asSynonym(c, e.target.value)}
                      >
                        <option value="">{t('As synonym of…')}</option>
                        {data.entries.map((p) => (
                          <option key={p.key} value={p.key}>
                            {p.key}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="ga-btn ga-btn-sm"
                        onClick={() => setConfirmDismiss(c.raw_text)}
                      >
                        {t('Dismiss')}
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <section className="ga-twocol-right">
        {!draft ? (
          <div className="ga-placeholder">{t('Pick an entry or create a new one.')}</div>
        ) : (
          <>
            <DetailToolbar
              title={
                approveOf
                  ? `${t('Approve candidate')}: ${approveOf}`
                  : isNew
                    ? isPose
                      ? t('New pose')
                      : t('New expression')
                    : draft.key
              }
              onSave={save}
              onDelete={isNew ? undefined : remove}
            />
            {/* Two columns: the catalog text on the left, the 3D animation
                with its preview on the right — the preview needs the room. */}
            <div className="ga-form" style={{ display: 'grid',
              gridTemplateColumns: isPose ? 'minmax(260px, 1fr) minmax(320px, 1.2fr)' : '1fr',
              gap: 16, alignItems: 'start' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Field
                  label={t('Key')}
                  hint={t('Canonical name, lowercase (e.g. sitting). This is the render and cache key.')}
                >
                  <input
                    className="ga-input"
                    value={draft.key}
                    disabled={!isNew}
                    onChange={(e) => upd('key', e.target.value)}
                  />
                </Field>

              <Field
                label={isPose ? t('Pose text') : t('Expression text')}
                hint={
                  isPose
                    ? t('Body posture for the image generation — arms, legs, posture. Third person, no names.')
                    : t('Facial expression for the image generation — brow, eyes, mouth. Third person, no names.')
                }
              >
                <textarea
                  className="ga-textarea"
                  rows={3}
                  value={draft.prompt}
                  onChange={(e) => upd('prompt', e.target.value)}
                />
              </Field>

              <Field
                label={t('Synonyms')}
                hint={t('Comma-separated. Free text matching one of these lands on this key directly, without an embedding lookup.')}
              >
                <input
                  className="ga-input"
                  value={draft.synonyms.join(', ')}
                  onChange={(e) =>
                    upd(
                      'synonyms',
                      e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                    )
                  }
                />
              </Field>

              {isPose ? (
                <Field
                  label={t('Solo')}
                  hint={t('Off = the pose needs a second person (kissing, embracing). Those keys are skipped when a single-character image is rendered.')}
                >
                  <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input
                      type="checkbox"
                      checked={draft.solo !== false}
                      onChange={(e) => upd('solo', e.target.checked)}
                    />
                    <span>{t('Works with one character alone')}</span>
                  </label>
                </Field>
              ) : null}

              </div>
              {isPose ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <Field
                    label={t('Animation')}
                    hint={t('Clip kind a 3D figure plays. Options come from the clips present in shared/models/clips.')}
                  >
                    <select
                      className="ga-input"
                      value={draft.animation}
                      onChange={(e) => {
                        const kind = e.target.value
                        // a pair clip has no solo half: the pose becomes a two-person one
                        setDraft((d) => (d ? { ...d, animation: kind,
                          solo: data.pair_kinds?.includes(kind) ? false : d.solo } : d))
                      }}
                    >
                      <option value="">{t('— pick a kind —')}</option>
                      {data.kinds.map((k) => (
                        <option key={k} value={k}>
                          {data.pair_kinds?.includes(k) ? `${k} — ${t('pair')}` : k}
                        </option>
                      ))}
                      {/* keep an animation whose clip has since been removed */}
                      {draft.animation && !data.kinds.includes(draft.animation) ? (
                        <option value={draft.animation}>
                          {draft.animation} ({t('no clip')})
                        </option>
                      ) : null}
                    </select>
                  </Field>
                  {data.pair_kinds?.includes(draft.animation) ? (
                    <div className="ga-form-hint">
                      {t('Pair clip: two figures play its two halves together at one anchor — this pose needs a partner (Solo is off).')}
                    </div>
                  ) : null}
                  <Field
                    label={t('Place type')}
                    hint={t('The kind of marker this pose can be played on. Every pose belongs to exactly one place type.')}
                  >
                    <select
                      className="ga-input"
                      value={draft.group || ''}
                      onChange={(e) => upd('group', e.target.value)}
                    >
                      <option value="">{t('— pick a place type —')}</option>
                      {Object.entries(data.groups || {}).map(([key, g]) => (
                        <option key={key} value={key}>
                          {g.label ? `${g.label} (${key})` : key}
                        </option>
                      ))}
                      {/* keep a place type that has since been removed visible */}
                      {draft.group && !(data.groups || {})[draft.group] ? (
                        <option value={draft.group}>
                          {draft.group} ({t('unknown')})
                        </option>
                      ) : null}
                    </select>
                  </Field>

                  {draft.solo === false ? (
                    <div className="ga-form-row">
                      <Field
                        label={t('Places')}
                        hint={t('How many slots of the anchor marker the pair uses: 2 = both on the bench, 1 = one on the bed edge, the other beside it')}
                      >
                        <div style={{ display: 'flex', gap: 12 }}>
                          {([1, 2] as const).map((n) => (
                            <label
                              key={n}
                              style={{ display: 'flex', gap: 4, alignItems: 'center' }}
                            >
                              <input
                                type="radio"
                                name="pose-places"
                                checked={(draft.places ?? 2) === n}
                                onChange={() => upd('places', n)}
                              />
                              <span>{n}</span>
                            </label>
                          ))}
                        </div>
                      </Field>
                      <Field
                        label={t('Yaw offset')}
                        hint={t('Degrees the pair clip’s frame turns against the marker facing.')}
                      >
                        <input
                          className="ga-input"
                          type="number"
                          min={-180}
                          max={180}
                          step={1}
                          value={draft.yaw_offset ?? 0}
                          onChange={(e) => upd('yaw_offset', Number(e.target.value))}
                        />
                        <span style={{ alignSelf: 'center' }}>°</span>
                      </Field>
                    </div>
                  ) : null}

                  {/* Below the select, not inside the Field: .ga-field-control
                      is a flex ROW and would put the canvas beside the select. */}
                  {draft.animation ? <ClipPreview kind={draft.animation} height={360} /> : null}
                </div>
              ) : null}
              {draft.is_default ? (
                <div className="ga-form-hint">
                  {t('Default entry: every free text the catalog cannot absorb falls back to this key. It cannot be deleted.')}
                </div>
              ) : null}
            </div>
          </>
        )}
      </section>
    </div>
  )
}
