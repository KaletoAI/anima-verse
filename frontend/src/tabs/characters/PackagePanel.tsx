import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, ConfirmDialog } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { loadCharacters } from '../../lib/refs'
import { useToast } from '../../lib/Toast'
import {
  PanelFieldControl,
  type CharacterOpt,
  type ConditionOpt,
  type ItemOpt,
  type PanelField,
  type PanelRefs,
} from './PackagePanelFields'

/**
 * Package character panel (Characters → Skills → <capability>): the generic
 * renderer of a skill package's own editor. The package answers the whole
 * panel — title, intro, cards with fields/values/status/actions, an optional
 * create form — through
 *   GET  /characters/{c}/panels/{package}?lang=     (describe)
 *   POST /characters/{c}/panels/{package}/save      {card_id|null, values}
 *   POST /characters/{c}/panels/{package}/delete    {card_id}
 *   POST /characters/{c}/panels/{package}/action    {card_id, action_id}
 * and this file only renders it (contract: docs/plugins.md → "Character
 * panels"). Every label arrives translated from the server; after each save,
 * delete or action the panel reloads — the server is the truth. A refusal
 * (`ok: false`) is shown inside its card. No package id appears in this file.
 */

interface PanelAction {
  id: string
  label: string
  confirm: string
  primary: boolean
}
interface PanelCard {
  id: string
  title: string
  subtitle: string
  badges: string[]
  fields: PanelField[]
  values: Record<string, unknown>
  status: string
  actions: PanelAction[]
  deletable: boolean
  delete_confirm: string
}
interface Panel {
  title: string
  intro: string
  cards: PanelCard[]
  create: { label: string; fields: PanelField[] } | null
}
interface OpResult {
  ok: boolean
  error?: string
  message?: string
  card_id?: string
}

const EMPTY_REFS: PanelRefs = { items: [], conditions: [], characters: [] }

function emptyValue(f: PanelField): unknown {
  if (f.type === 'bool') return false
  if (f.type === 'items' || f.type === 'characters') return []
  return ''
}

/** Comparable form of a value: null/undefined read as the empty value. */
function norm(f: PanelField, v: unknown): string {
  return JSON.stringify(v === undefined || v === null ? emptyValue(f) : v)
}

export function PackagePanel({ character, packageId }: { character: string; packageId: string }) {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [panel, setPanel] = useState<Panel | null>(null)
  const [gone, setGone] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [creating, setCreating] = useState(false)
  const [refs, setRefs] = useState<PanelRefs>(EMPTY_REFS)

  const base = `/characters/${encodeURIComponent(character)}/panels/${encodeURIComponent(packageId)}`
  const q = `?lang=${encodeURIComponent(lang)}`

  const reload = useCallback(async () => {
    try {
      const d = await apiGet<Panel>(base + q)
      setPanel(d)
      setGone(false)
      setLoadError('')
    } catch (e) {
      // 404 = the package (or its panel) is gone: show nothing.
      if (e instanceof ApiError && e.status === 404) {
        setGone(true)
        setPanel(null)
      } else {
        setLoadError((e as Error).message)
      }
    }
  }, [base, q])

  useEffect(() => {
    setPanel(null)
    setCreating(false)
    reload()
  }, [reload])

  // Reference lists — only the ones some field of this panel needs.
  const needs = useMemo(() => {
    const types = new Set<string>()
    for (const c of panel?.cards || []) for (const f of c.fields) types.add(f.type)
    for (const f of panel?.create?.fields || []) types.add(f.type)
    return {
      items: types.has('item') || types.has('items'),
      conditions: types.has('condition'),
      characters: types.has('characters'),
    }
  }, [panel])
  useEffect(() => {
    if (!needs.items) return
    apiGet<{ items?: ItemOpt[] }>('/inventory/items?include_shared=1')
      .then((d) => setRefs((r) => ({ ...r, items: d.items || [] })))
      .catch(() => setRefs((r) => ({ ...r, items: [] })))
  }, [needs.items])
  useEffect(() => {
    if (!needs.conditions) return
    apiGet<{ conditions?: ConditionOpt[] }>('/world/conditions/list')
      .then((d) => setRefs((r) => ({ ...r, conditions: d.conditions || [] })))
      .catch(() => setRefs((r) => ({ ...r, conditions: [] })))
  }, [needs.conditions])
  useEffect(() => {
    if (!needs.characters) return
    loadCharacters()
      .then((cs) => setRefs((r) => ({ ...r, characters: cs as CharacterOpt[] })))
      .catch(() => setRefs((r) => ({ ...r, characters: [] })))
  }, [needs.characters])

  const call = useCallback(
    async (op: 'save' | 'delete' | 'action', body: Record<string, unknown>): Promise<OpResult> => {
      try {
        return await apiPost<OpResult>(`${base}/${op}${q}`, body)
      } catch (e) {
        return { ok: false, error: (e as Error).message }
      }
    },
    [base, q],
  )

  if (gone) return null
  if (loadError && !panel) {
    return <div className="ga-pp-error" style={{ marginTop: 14 }}>{t('Failed to load')}: {loadError}</div>
  }
  if (!panel) return <div className="ga-loading" style={{ marginTop: 14 }}>{t('Loading…')}</div>

  return (
    <div className="ga-pp">
      <div className="ga-pp-top">
        <div style={{ minWidth: 0 }}>
          {panel.title ? <div className="ga-fieldset-title" style={{ margin: 0 }}>{panel.title}</div> : null}
          {panel.intro ? <div className="ga-pp-muted">{panel.intro}</div> : null}
        </div>
        {panel.create && !creating ? (
          <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" onClick={() => setCreating(true)}>
            + {panel.create.label || t('New')}
          </button>
        ) : null}
      </div>

      {creating && panel.create ? (
        <CardForm
          key="__create__"
          character={character}
          title={panel.create.label || t('New')}
          fields={panel.create.fields}
          values={{}}
          refs={refs}
          onSave={async (values) => {
            const r = await call('save', { card_id: null, values })
            if (r.ok) {
              toast(t('Saved'))
              setCreating(false)
              await reload()
            }
            return r
          }}
          onCancel={() => setCreating(false)}
        />
      ) : null}

      {panel.cards.length === 0 && !creating ? (
        <div className="ga-placeholder">{t('Nothing here yet.')}</div>
      ) : null}

      {panel.cards.map((card) => (
        <CardForm
          // A changed server value remounts the card, so the draft starts
          // from the truth after a save or an action.
          key={card.id + ':' + JSON.stringify(card.values)}
          character={character}
          card={card}
          title={card.title}
          fields={card.fields}
          values={card.values}
          refs={refs}
          onSave={async (values) => {
            const r = await call('save', { card_id: card.id, values })
            if (r.ok) {
              toast(t('Saved'))
              await reload()
            }
            return r
          }}
          onDelete={async () => {
            const r = await call('delete', { card_id: card.id })
            if (r.ok) {
              toast(t('Deleted'))
              await reload()
            }
            return r
          }}
          onAction={async (actionId) => {
            const r = await call('action', { card_id: card.id, action_id: actionId })
            if (r.ok) {
              if (r.message) toast(r.message)
              await reload()
            }
            return r
          }}
        />
      ))}
    </div>
  )
}

function CardForm({
  character, card, title, fields, values, refs, onSave, onCancel, onDelete, onAction,
}: {
  character: string
  card?: PanelCard
  title: string
  fields: PanelField[]
  values: Record<string, unknown>
  refs: PanelRefs
  onSave: (values: Record<string, unknown>) => Promise<OpResult>
  onCancel?: () => void
  onDelete?: () => Promise<OpResult>
  onAction?: (actionId: string) => Promise<OpResult>
}) {
  const { t } = useI18n()
  const initial = useMemo(() => {
    const v: Record<string, unknown> = {}
    for (const f of fields) v[f.key] = values[f.key] ?? emptyValue(f)
    return v
  }, [fields, values])
  const [draft, setDraft] = useState<Record<string, unknown>>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState<
    { kind: 'delete' } | { kind: 'action'; action: PanelAction } | null
  >(null)

  const isNew = !card
  const dirty = isNew || fields.some((f) => norm(f, draft[f.key]) !== norm(f, initial[f.key]))

  const run = async (fn: () => Promise<OpResult>) => {
    setBusy(true)
    setError('')
    try {
      const r = await fn()
      if (!r.ok) setError(r.error || t('That did not work.'))
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(() => onSave(draft))
  const doAction = (a: PanelAction) =>
    a.confirm ? setPending({ kind: 'action', action: a }) : run(() => onAction!(a.id))

  return (
    <div className="ga-fieldset ga-pp-card">
      <div className="ga-pp-head">
        <strong>{title || (isNew ? t('New') : '')}</strong>
        {(card?.badges || []).map((b) => <span key={b} className="ga-tag ga-tag-tier">{b}</span>)}
        {card?.subtitle ? <span className="ga-pp-muted">{card.subtitle}</span> : null}
      </div>

      <div className="ga-pp-rows">
        {fields.map((f) => (
          <div key={f.key} className="ga-pp-row">
            <div className="ga-pp-label">{f.label}{f.required ? <span className="ga-pp-req"> *</span> : null}</div>
            <div className="ga-pp-control">
              <PanelFieldControl field={f} value={draft[f.key]} refs={refs} character={character}
                onChange={(v) => { setDraft((d) => ({ ...d, [f.key]: v })); setError('') }} />
              {f.hint ? <div className="ga-pp-hint" title={f.hint}>{f.hint}</div> : null}
            </div>
          </div>
        ))}
      </div>

      {card?.status ? (
        <div className="ga-pp-row ga-pp-status">
          <div className="ga-pp-label">{t('Status')}</div>
          <div className="ga-pp-control">{card.status}</div>
        </div>
      ) : null}

      {error ? <div className="ga-pp-error">{error}</div> : null}

      <div className="ga-pp-foot">
        {(card?.actions || []).map((a) => (
          <button key={a.id} type="button" disabled={busy}
            className={'ga-btn ga-btn-sm' + (a.primary ? ' ga-btn-primary' : '')}
            onClick={() => doAction(a)}>{a.label}</button>
        ))}
        <span style={{ flex: 1 }} />
        {card?.deletable ? (
          <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={busy}
            onClick={() => setPending({ kind: 'delete' })}>{t('Delete')}</button>
        ) : null}
        {onCancel ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={onCancel}>
            {t('Cancel')}
          </button>
        ) : null}
        {!isNew && dirty ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={busy}
            onClick={() => { setDraft(initial); setError('') }}>{t('Discard')}</button>
        ) : null}
        <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy || !dirty}
          onClick={save}>{busy ? t('Saving…') : t('Save')}</button>
      </div>

      <ConfirmDialog
        open={!!pending}
        title={pending?.kind === 'action' ? pending.action.label : t('Delete')}
        message={pending?.kind === 'action'
          ? pending.action.confirm
          : (card?.delete_confirm || t('This entry is removed for good.'))}
        confirmLabel={pending?.kind === 'action' ? pending.action.label : t('Delete')}
        danger={pending?.kind !== 'action'}
        onConfirm={() => {
          const p = pending
          setPending(null)
          if (!p) return
          if (p.kind === 'delete') void run(() => onDelete!())
          else void run(() => onAction!(p.action.id))
        }}
        onClose={() => setPending(null)}
      />
    </div>
  )
}
