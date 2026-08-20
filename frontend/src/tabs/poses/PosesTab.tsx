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
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '../../components/Field'
import { DetailToolbar } from '../../components/DetailToolbar'
import { ListHeader } from '../../components/ListHeader'

type Axis = 'pose' | 'expression'

interface Entry {
  key: string
  prompt: string
  synonyms: string[]
  animation: string
  solo: boolean
  is_default?: boolean
  axis?: Axis
}

interface CatalogData {
  entries: Entry[]
  kinds: string[]
  /** kinds that exist as a PAIR clip (two halves) — two-person poses */
  pair_kinds?: string[]
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

const EMPTY: Entry = { key: '', prompt: '', synonyms: [], animation: '', solo: true }

export function PosesTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [axis, setAxis] = useState<Axis>('pose')
  const [data, setData] = useState<CatalogData>({ entries: [], kinds: [], problems: [] })
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [selected, setSelected] = useState<string>('')
  const [draft, setDraft] = useState<Entry | null>(null)
  const [isNew, setIsNew] = useState(false)
  // raw_text of the candidate the open draft was started from ('' = plain new entry)
  const [approveOf, setApproveOf] = useState('')
  const [search, setSearch] = useState('')
  const [onlyMissing, setOnlyMissing] = useState(false)
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
  }, [axis])

  const list = useMemo(() => {
    const q = search.trim().toLowerCase()
    return data.entries.filter((p) => {
      if (isPose && onlyMissing && p.animation) return false
      if (!q) return true
      return (
        p.key.includes(q) ||
        p.prompt.toLowerCase().includes(q) ||
        p.synonyms.some((s) => s.includes(q))
      )
    })
  }, [data.entries, search, onlyMissing, isPose])

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
    try {
      const body = {
        axis,
        key,
        prompt: draft.prompt,
        synonyms: draft.synonyms,
        ...(isPose ? { animation: draft.animation, solo: draft.solo } : {}),
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

  return (
    <div className="ga-twocol">
      <aside className="ga-twocol-left">
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
                    <span className="ga-list-row-sub" style={{ opacity: p.animation ? 1 : 0.4 }}>
                      — {p.animation || t('no animation')}
                    </span>
                  ) : null}
                </span>
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
            <div className="ga-form">
              <div className="ga-form-row">
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
                {isPose ? (
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
                          {k}
                        </option>
                      ))}
                      {/* keep an animation whose clip has since been removed */}
                      {draft.animation && !data.kinds.includes(draft.animation) ? (
                        <option value={draft.animation}>
                          {draft.animation} ({t('no clip')})
                        </option>
                      ) : null}
                    </select>
                    {data.pair_kinds?.includes(draft.animation) ? (
                      <div className="ga-hint" style={{ marginTop: 4 }}>
                        {t('Pair clip: two figures play its two halves together at one anchor — this pose needs a partner (Solo is off).')}
                      </div>
                    ) : null}
                  </Field>
                ) : null}
              </div>

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
