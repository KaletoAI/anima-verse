/**
 * ClipTransitions — the bridge clips, read as one table: from × to × clip.
 *
 * A figure must not jump from one state into the next: a rule names the clip
 * that has to play BETWEEN two poses (stand up before walking away), and how
 * much speed the body picks up while it plays. `"*"` is the wildcard — on the
 * TO side it makes an exit clip ("stand up, whatever comes next"), on the FROM
 * side an enter clip; the more precise rule wins. A rule leaving a PAIR pose
 * may name one bridge per clip role. Entering a pair or group can do the
 * same; each figure receives the bridge of its role.
 *
 * Free bridges can live in the shared seed; licensed bridges stay in the
 * world layer. The whole effective list travels on every save: they are few,
 * the table shows all of them, and a partial write would only invite two
 * editors to disagree about what the list is.
 *
 *   GET  /assets/animation-clips               … {kinds, pair_kinds, transitions}
 *   PUT  /assets/animation-clips/transitions   {transitions:[…]}
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ClipPreview } from './ClipPreview'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'

import { bridgeKinds as kindsOf } from './clipSets'
import type { ClipListing, PoseTransition as Transition, RoleKinds } from './clipSets'

export interface PoseRef { key: string; solo?: boolean; animation?: string }

const TRANSITION_ANY = '*'

export function ClipTransitions({ poses, onSaved }: {
  poses: PoseRef[]
  onSaved: () => void
}) {
  const { t } = useI18n()
  // The rules as the server stores them, and the edited copy
  const [transitions, setTransitions] = useState<Transition[] | null>(null)
  const [draft, setDraft] = useState<Transition[]>([])
  // Which row the preview on the right follows (index into `draft`)
  const [selected, setSelected] = useState<number | null>(null)
  const [kinds, setKinds] = useState<string[]>([])
  const [freeKinds, setFreeKinds] = useState<Set<string>>(() => new Set())
  const [clipRoles, setClipRoles] = useState<Record<string, string[]>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // One fetch carries both halves of this view: the rules and the vocabulary
  // they may name.
  useEffect(() => {
    let alive = true
    apiGet<ClipListing>(
      '/assets/animation-clips')
      .then((data) => {
        if (!alive) return
        // A bridge is played by ONE figure, so only solo kinds can be one —
        // the server refuses a pair kind here anyway.
        setKinds([...new Set(data.clips.filter((c) => !c.role).map((c) => c.kind))])
        const roles: Record<string, string[]> = {}
        for (const c of data.clips) if (c.role && !(roles[c.kind] || []).includes(c.role)) (roles[c.kind] ||= []).push(c.role)
        setClipRoles(roles)
        const free = new Set(data.clips.filter((c) => c.library === 'free' && !c.role).map((c) => c.kind))
        setFreeKinds(free)
        const rules = (data.transitions || []).map((r) => ({
          ...r, store: kindsOf(r.kind).every((k) => free.has(k)) ? r.store : 'world' as const,
        }))
        setTransitions(rules)
        setDraft(rules)
        setError('')
      })
      .catch((e) => {
        if (alive) setError((e as Error).message)
      })
    return () => {
      alive = false
    }
  }, [])

  const poseKeys = useMemo(() => poses.map((p) => p.key).sort(), [poses])
  const pairPoses = useMemo(() => new Set(poses.filter((p) => p.solo === false).map((p) => p.key)), [poses])
  const rolesOf = useCallback((rule: Transition) => {
    const of = (key: string) => clipRoles[poses.find((p) => p.key === key)?.animation || ''] || []
    const a = of(rule.from); const b = of(rule.to)
    return (a.length && b.length ? a.filter((r) => b.includes(r)) : a.length ? a : b).slice().sort()
  }, [clipRoles, poses])
  const allFree = useCallback((kind: Transition['kind']) => kindsOf(kind).every((k) => freeKinds.has(k)), [freeKinds])

  const dirty = useMemo(
    () => !!transitions && JSON.stringify(draft) !== JSON.stringify(transitions),
    [draft, transitions],
  )

  const patch = useCallback((i: number, part: Partial<Transition>) => {
    setDraft((d) => d.map((r, j) => {
      if (j !== i) return r
      const next = { ...r, ...part }
      if (next.from !== 'walking' && next.to.startsWith('@')) next.to = TRANSITION_ANY
      // Either multi-person side can select bridges per role.
      if (typeof next.kind !== 'string' && !pairPoses.has(next.from) && !pairPoses.has(next.to)) next.kind = kindsOf(next.kind)[0] || ''
      if (typeof next.kind !== 'string' && (part.from !== undefined || part.to !== undefined)) {
        const roles = rolesOf(next)
        next.kind = Object.fromEntries(Object.entries(next.kind).filter(([r]) => roles.includes(r)))
      }
      if (!allFree(next.kind)) next.store = 'world'
      return next
    }))
  }, [allFree, pairPoses, rolesOf])

  const removeRule = useCallback((i: number) => {
    setDraft((d) => d.filter((_, j) => j !== i))
    // The rows below move up by one, so the selection has to move with them.
    setSelected((s) => (s === null ? s : s === i ? null : s > i ? s - 1 : s))
  }, [])

  const addRule = useCallback(() => {
    // The new row is the last one, and the preview follows it right away.
    setSelected(draft.length)
    setDraft((d) => [...d, { from: TRANSITION_ANY, to: TRANSITION_ANY, kind: kinds[0] || '', accel: 0, store: freeKinds.has(kinds[0]) ? 'shared' : 'world' }])
  }, [draft.length, kinds, freeKinds])

  const save = useCallback(async () => {
    if (busy || !transitions) return
    setBusy(true)
    setError('')
    try {
      // The WHOLE list travels — the editor shows all of it, so a partial
      // write would only invite two editors to disagree about what it is.
      const res = await apiPut<{ transitions: Transition[] }>(
        '/assets/animation-clips/transitions',
        { transitions: draft.filter((r) => r.from && r.to && kindsOf(r.kind).length).map(({ from, to, kind, accel, store }) => ({ from, to, kind, accel, store })) },
      )
      setTransitions(res.transitions)
      setDraft(res.transitions)
      setSelected(null)
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [busy, draft, transitions, onSaved])

  const row = selected !== null ? draft[selected] : undefined

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
      {/* ── the rules ── */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, minHeight: 0 }}>
        <p className="ga-form-hint" style={{ margin: 0 }}>
          {t('The clip that has to play BETWEEN two poses, so a figure does not jump'
             + ' from one state into the next. Write "*" for "anything" — on the To'
             + ' side that makes an exit clip, on the From side an enter clip, and the'
             + ' more precise rule wins.')}
        </p>

        <div style={{ overflow: 'auto', minHeight: 0, flex: 1 }}>
          <table className="ga-sched-table">
            <thead>
              <tr>
                <th>{t('From')}</th>
                <th>{t('To')}</th>
                <th>{t('Bridge clip')}</th>
                <th>{t('Store')}</th>
                <th
                  title={t('Fraction of normal speed the figure gains per second while the'
                           + ' clip plays: 0 holds it on the spot for the whole clip'
                           + ' (getting out of a seat), 1 has it at full speed after a'
                           + ' second (starting to walk). Above 0 the body also turns into'
                           + ' the new direction at once instead of easing into it.')}
                >
                  {t('Speed-up')}
                </th>
                <th />
              </tr>
            </thead>
            <tbody>
              {!draft.length ? (
                <tr>
                  <td colSpan={6}>{t('No rules — every pose change is instant.')}</td>
                </tr>
              ) : null}
              {draft.map((rule, i) => (
                <tr
                  key={i}
                  onClick={() => setSelected(i)}
                  style={{
                    cursor: 'pointer',
                    background: i === selected ? 'var(--bg-secondary, #21262d)' : undefined,
                  }}
                >
                  <td>
                    <select className="ga-input" style={{ maxWidth: 190 }}
                      value={rule.from} disabled={busy}
                      onChange={(e) => patch(i, { from: e.target.value })}>
                      <option value={TRANSITION_ANY}>{TRANSITION_ANY}</option>
                      {rule.from !== TRANSITION_ANY && !poseKeys.includes(rule.from) ? (
                        <option value={rule.from}>{rule.from} ({t('unknown pose')})</option>
                      ) : null}
                      {poseKeys.map((key) => <option key={key} value={key}>{key}</option>)}
                    </select>
                  </td>
                  <td>
                    <select className="ga-input" style={{ maxWidth: 190 }}
                      value={rule.to} disabled={busy}
                      onChange={(e) => patch(i, { to: e.target.value })}>
                      <option value={TRANSITION_ANY}>{TRANSITION_ANY}</option>
                      {rule.to !== TRANSITION_ANY && !poseKeys.includes(rule.to)
                        && !(rule.from === 'walking' && ['@seat', '@lie', '@ground', '@stand'].includes(rule.to)) ? (
                        <option value={rule.to}>{rule.to} ({t('unknown pose')})</option>
                      ) : null}
                      {rule.from === 'walking' ? <>
                        <option value="@seat">{t('Any seat place (@seat)')}</option>
                        <option value="@lie">{t('Any lie place (@lie)')}</option>
                        <option value="@ground">{t('Any ground place (@ground)')}</option>
                        <option value="@stand">{t('Any stand place (@stand)')}</option>
                      </> : null}
                      {poseKeys.map((key) => <option key={key} value={key}>{key}</option>)}
                    </select>
                  </td>
                  <td>
                    {typeof rule.kind === 'string' ? (
                      <KindSelect value={rule.kind} kinds={kinds} disabled={busy}
                        onChange={(kind) => patch(i, { kind })} />
                    ) : rolesOf(rule).map((role) => {
                      const perRole = rule.kind as RoleKinds
                      return (
                        <label key={role} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span>{role.toUpperCase()}</span>
                          <KindSelect value={perRole[role] || ''} kinds={kinds} disabled={busy} allowNone
                            onChange={(kind) => patch(i, { kind: { ...perRole, [role]: kind } })} />
                        </label>
                      )
                    })}
                    {(pairPoses.has(rule.from) || pairPoses.has(rule.to)) ? (
                      <label className="ga-form-hint" style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                        title={t('Choose a bridge for each role. A role without one blends over.')}>
                        <input type="checkbox" disabled={busy} checked={typeof rule.kind !== 'string'}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => patch(i, {
                            kind: e.target.checked
                              ? Object.fromEntries(rolesOf(rule).map((r) => [r, kindsOf(rule.kind)[0] || '']))
                              : kindsOf(rule.kind)[0] || '',
                          })} />
                        {t('one per role')}
                      </label>
                    ) : null}
                    <div className="ga-form-hint">
                      {t('local: {from_kind} → {to_kind} · public: {from_public_kind} → {to_public_kind}')
                        .replace('{from_kind}', rule.from_kind || '—')
                        .replace('{to_kind}', rule.to_kind || '—')
                        .replace('{from_public_kind}', rule.from_public_kind || '—')
                        .replace('{to_public_kind}', rule.to_public_kind || '—')}
                    </div>
                    {rule.bridge_public === false ? <div className="ga-field-warn">{t('Licensed clip — only on this installation')}</div> : null}
                    {rule.conflict ? <div className="ga-field-warn">{t('Overlaps an earlier rule')}</div> : null}
                  </td>
                  <td>
                    {rule.store === 'world' ? <span className="ga-source">{t('world')}</span> : null}
                    <select className="ga-input" value={rule.store} disabled={busy}
                      aria-label={t('Store')}
                      onChange={(e) => patch(i, { store: e.target.value as Transition['store'] })}>
                      <option value="shared" disabled={!allFree(rule.kind)}>{t('shared')}</option>
                      <option value="world">{t('world')}</option>
                    </select>
                    {!allFree(rule.kind) ? (
                      <div className="ga-form-hint">{t('Licensed bridge clips stay in this world.')}</div>
                    ) : null}
                  </td>
                  <td>
                    <input
                      className="ga-input" type="number" min={0} max={8} step={0.1}
                      style={{ maxWidth: 80 }}
                      value={rule.accel} disabled={busy}
                      onChange={(e) => patch(i, {
                        accel: Math.max(0, Math.min(8, Number(e.target.value) || 0)),
                      })}
                    />
                  </td>
                  <td>
                    <button
                      type="button" className="ga-btn ga-btn-sm" disabled={busy}
                      title={t('Remove this rule')}
                      onClick={(e) => {
                        e.stopPropagation()
                        removeRule(i)
                      }}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="ga-form-hint" style={{ margin: 0 }}>
          {t('Entry clips: a rule from walking to a place type applies to every pose of that type; a rule for one pose wins.')}
        </p>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button" className="ga-btn ga-btn-sm" disabled={busy || !transitions}
            onClick={addRule}
          >
            {t('Add rule')}
          </button>
          <button
            type="button" className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={!dirty || busy}
            onClick={() => void save()}
          >
            {busy ? t('Saving…') : t('Save')}
          </button>
          {dirty && !busy ? (
            <button
              type="button" className="ga-btn ga-btn-sm"
              onClick={() => {
                setDraft(transitions || [])
                setSelected(null)
              }}
            >
              {t('Cancel')}
            </button>
          ) : null}
        </div>
        {error ? (
          <div className="ga-form-hint" style={{ color: 'var(--danger, #f85149)' }}>
            {error}
          </div>
        ) : null}
      </section>

      {/* ── the bridge clip of the picked rule ── */}
      <section style={{ minWidth: 0, minHeight: 0, overflowY: 'auto', paddingRight: 4 }}>
        {!row || !kindsOf(row.kind).length ? (
          <div className="ga-placeholder">{t('Pick a rule to see its bridge clip.')}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <h3 style={{ margin: '0 0 2px' }}>{kindsOf(row.kind).join(' / ')}</h3>
              <div className="ga-form-hint">
                <code>{row.from || TRANSITION_ANY}</code> → <code>{row.to || TRANSITION_ANY}</code>
              </div>
            </div>
            {/* The neutral set, like every other clip preview that is not
                looking at one figure in particular — one per role. */}
            {typeof row.kind === 'string' ? (
              <ClipPreview kind={row.kind} set="" height={360} />
            ) : rolesOf(row).filter((role) => (row.kind as RoleKinds)[role]).map((role) => (
              <div key={role}>
                <div className="ga-form-hint">{t('Role {role}').replace('{role}', role.toUpperCase())}</div>
                <ClipPreview kind={(row.kind as RoleKinds)[role] || ''} set="" height={260} />
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

/** One bridge clip: the solo kinds, a missing one kept visible, and — for a
 *  role of a per-role rule — "none" (that role blends over). */
function KindSelect({ value, kinds, disabled, allowNone, onChange }: {
  value: string
  kinds: string[]
  disabled: boolean
  allowNone?: boolean
  onChange: (kind: string) => void
}) {
  const { t } = useI18n()
  return (
    <select className="ga-input" style={{ maxWidth: 200 }} value={value} disabled={disabled}
      onChange={(e) => onChange(e.target.value)}>
      {allowNone ? <option value="">{t('— none —')}</option> : null}
      {!value || kinds.includes(value) ? null : (
        <option value={value}>{`${value} (${t('missing')})`}</option>
      )}
      {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
    </select>
  )
}
