import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, ConfirmDialog } from '@anima/player-ui'
import { PromptDialog } from '../../components/PromptDialog'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { isGeneratorBackend } from '../../lib/imageBackends'
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
 *   POST /characters/{c}/panels/{package}/action    {card_id, action_id, value?}
 * and this file only renders it (contract: docs/plugins.md → "Character
 * panels"). Every label arrives translated from the server; after each save,
 * delete or action the panel reloads — the server is the truth. A refusal
 * (`ok: false`) is shown inside its card. No package id appears in this file.
 *
 * Layout: a chip strip selects ONE card (or the create form); the card head
 * (title, badges, status, actions, Delete/Discard/Save) stays above the
 * card's tabs; inside a tab the fields sit on a 12-column grid by their
 * `width`. The draft lives per shown card, so a tab switch keeps it; a card
 * switch with unsaved edits asks first. Panel-level actions (no card) sit in
 * the top bar; an action with `input` asks for one line of text first.
 */

interface PanelAction {
  id: string
  label: string
  confirm: string
  primary: boolean
  /** Ask for one line of text first; it is sent as `value`. */
  input?: { label: string; placeholder: string; message: string }
}
interface PanelTab {
  id: string
  label: string
  hint: string
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
  tabs?: PanelTab[]
  /** Panel-level actions, not bound to a card (run with card_id ""). */
  actions?: PanelAction[]
  cards: PanelCard[]
  create: { label: string; fields: PanelField[] } | null
}
interface OpResult {
  ok: boolean
  error?: string
  message?: string
  card_id?: string
}

/** Selection value of the create form in the chip strip. */
const CREATE = '__create__'
const EMPTY_REFS: PanelRefs = { items: [], conditions: [], characters: [], backends: [] }
/** Grid span (of 12) per field `width`. */
const WIDTH_SPAN: Record<string, number> = { s: 3, m: 4, l: 6, full: 12 }
/** Types that default to the full row; everything else defaults to `m`. */
const WIDE_TYPES = new Set(['textarea', 'items', 'characters', 'loras'])

function emptyValue(f: PanelField): unknown {
  if (f.type === 'bool') return false
  if (f.type === 'items' || f.type === 'characters' || f.type === 'loras') return []
  return ''
}

/** Comparable form of a value: null/undefined read as the empty value. */
function norm(f: PanelField, v: unknown): string {
  return JSON.stringify(v === undefined || v === null ? emptyValue(f) : v)
}

/** Client-side check of `required` (the server checks again on save). */
function missingRequired(f: PanelField, v: unknown): boolean {
  if (!f.required || f.type === 'bool') return false
  if (v === undefined || v === null) return true
  if (Array.isArray(v)) return v.length === 0
  return String(v).trim() === ''
}

function fieldSpan(f: PanelField): number {
  const w = f.width && WIDTH_SPAN[f.width] ? f.width : (WIDE_TYPES.has(f.type) ? 'full' : 'm')
  return WIDTH_SPAN[w]
}

export function PackagePanel({ character, packageId }: { character: string; packageId: string }) {
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const [panel, setPanel] = useState<Panel | null>(null)
  const [gone, setGone] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [refs, setRefs] = useState<PanelRefs>(EMPTY_REFS)
  // The shown card id, CREATE, or null (no card, create form closed).
  const [selected, setSelected] = useState<string | null>(null)
  // The open tab — kept here so a save (which remounts the card) or a card
  // switch stays on the same tab.
  const [activeTab, setActiveTab] = useState('')
  const [dirty, setDirty] = useState(false)
  const [pendingSwitch, setPendingSwitch] = useState<{ to: string | null } | null>(null)
  // A panel-level action waiting for its confirmation or its input.
  const [panelPending, setPanelPending] = useState<PanelAction | null>(null)
  const [panelBusy, setPanelBusy] = useState(false)
  const [panelError, setPanelError] = useState('')

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
    setSelected(null)
    setActiveTab('')
    reload()
  }, [reload])

  // Keep the selection valid: a deleted card (or none chosen yet) falls back
  // to the first card.
  useEffect(() => {
    if (!panel) return
    if (selected === CREATE && panel.create) return
    if (selected && panel.cards.some((c) => c.id === selected)) return
    const first = panel.cards[0]?.id ?? null
    if (first !== selected) setSelected(first)
  }, [panel, selected])

  // Reference lists — only the ones some field of this panel needs.
  const needs = useMemo(() => {
    const types = new Set<string>()
    for (const c of panel?.cards || []) for (const f of c.fields) types.add(f.type)
    for (const f of panel?.create?.fields || []) types.add(f.type)
    return {
      items: types.has('item') || types.has('items'),
      conditions: types.has('condition'),
      characters: types.has('characters'),
      backends: types.has('backend'),
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
  useEffect(() => {
    if (!needs.backends) return
    // Generator backends only, as in ImageOverrides.tsx (no inpaint/upscale/video).
    apiGet<{ options?: Array<{ name?: string; category?: string; media?: string }> }>('/world/imagegen-options')
      .then((d) => setRefs((r) => ({
        ...r,
        backends: (d.options || []).filter((o) => o.name && isGeneratorBackend(o)).map((o) => o.name as string),
      })))
      .catch(() => setRefs((r) => ({ ...r, backends: [] })))
  }, [needs.backends])

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

  /** Run a panel-level action (card_id ""); `value` = the asked-for text. */
  const runPanelAction = async (a: PanelAction, value?: string) => {
    setPanelBusy(true)
    setPanelError('')
    try {
      const r = await call('action', { card_id: '', action_id: a.id, ...(value !== undefined ? { value } : {}) })
      if (r.ok) {
        if (r.message) toast(r.message)
        await reload()
      } else {
        setPanelError(r.error || t('That did not work.'))
      }
    } finally {
      setPanelBusy(false)
    }
  }
  const startPanelAction = (a: PanelAction) => {
    if (a.input || a.confirm) setPanelPending(a)
    else void runPanelAction(a)
  }

  const select = (to: string | null) => {
    if (to === selected) return
    if (dirty) setPendingSwitch({ to })
    else setSelected(to)
  }

  if (gone) return null
  if (loadError && !panel) {
    return <div className="ga-pp-error" style={{ marginTop: 14 }}>{t('Failed to load')}: {loadError}</div>
  }
  if (!panel) return <div className="ga-loading" style={{ marginTop: 14 }}>{t('Loading…')}</div>

  const tabs = panel.tabs || []
  const panelActions = panel.actions || []
  const createLabel = panel.create?.label || t('New')
  const card = selected && selected !== CREATE ? panel.cards.find((c) => c.id === selected) : undefined
  const creating = selected === CREATE && !!panel.create

  return (
    <div className="ga-pp">
      {panel.title || panel.intro || panelActions.length || (panel.create && panel.cards.length === 0 && !creating) ? (
        <div className="ga-pp-top">
          <div style={{ minWidth: 0 }}>
            {panel.title ? <div className="ga-fieldset-title" style={{ margin: 0 }}>{panel.title}</div> : null}
            {panel.intro ? <div className="ga-pp-muted">{panel.intro}</div> : null}
          </div>
          <div className="ga-pp-head-btns">
            {panelActions.map((a) => (
              <button key={a.id} type="button" disabled={panelBusy}
                className={'ga-btn ga-btn-sm' + (a.primary ? ' ga-btn-primary' : '')}
                onClick={() => startPanelAction(a)}>{a.label}</button>
            ))}
            {panel.create && panel.cards.length === 0 && !creating ? (
              <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" onClick={() => select(CREATE)}>
                + {createLabel}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {panelError ? <div className="ga-pp-error">{panelError}</div> : null}

      {panel.cards.length > 0 ? (
        <div className="ga-pp-selector" role="tablist">
          {panel.cards.map((c) => (
            <button key={c.id} type="button" role="tab" aria-selected={c.id === selected}
              className={'ga-pp-sel' + (c.id === selected ? ' ga-pp-sel-on' : '')}
              title={c.subtitle || c.title} onClick={() => select(c.id)}>
              <span className="ga-pp-sel-title">{c.title || c.id}</span>
              {c.badges.map((b) => <span key={b} className="ga-tag ga-tag-tier">{b}</span>)}
            </button>
          ))}
          {panel.create ? (
            <button type="button" role="tab" aria-selected={creating}
              className={'ga-pp-sel ga-pp-sel-add' + (creating ? ' ga-pp-sel-on' : '')}
              onClick={() => select(CREATE)}>+ {createLabel}</button>
          ) : null}
        </div>
      ) : null}

      {creating && panel.create ? (
        <CardForm
          key={CREATE}
          character={character}
          title={createLabel}
          fields={panel.create.fields}
          values={{}}
          tabs={tabs}
          activeTab={activeTab}
          onTab={setActiveTab}
          onDirty={setDirty}
          refs={refs}
          onSave={async (values) => {
            const r = await call('save', { card_id: null, values })
            if (r.ok) {
              toast(t('Saved'))
              await reload()
              setDirty(false)
              setSelected(r.card_id || null)
            }
            return r
          }}
          onCancel={() => { setDirty(false); setSelected(panel.cards[0]?.id ?? null) }}
        />
      ) : null}

      {panel.cards.length === 0 && !creating ? (
        <div className="ga-placeholder">{t('Nothing here yet.')}</div>
      ) : null}

      {card ? (
        <CardForm
          // A changed server value remounts the card, so the draft starts
          // from the truth after a save or an action.
          key={card.id + ':' + JSON.stringify(card.values)}
          character={character}
          card={card}
          title={card.title}
          fields={card.fields}
          values={card.values}
          tabs={tabs}
          activeTab={activeTab}
          onTab={setActiveTab}
          onDirty={setDirty}
          refs={refs}
          onSave={async (values) => {
            const r = await call('save', { card_id: card.id, values })
            if (r.ok) {
              toast(t('Saved'))
              await reload()
              setSelected(r.card_id || card.id)
            }
            return r
          }}
          onDelete={async () => {
            const r = await call('delete', { card_id: card.id })
            if (r.ok) {
              toast(t('Deleted'))
              setDirty(false)
              await reload()
            }
            return r
          }}
          onAction={async (actionId, value) => {
            const r = await call('action', {
              card_id: card.id, action_id: actionId, ...(value !== undefined ? { value } : {}),
            })
            if (r.ok) {
              if (r.message) toast(r.message)
              await reload()
            }
            return r
          }}
        />
      ) : null}

      <ConfirmDialog
        open={!!pendingSwitch}
        title={t('Discard unsaved changes?')}
        message={t('The changes to this entry are lost.')}
        confirmLabel={t('Discard')}
        danger
        onConfirm={() => {
          const p = pendingSwitch
          setPendingSwitch(null)
          if (!p) return
          setDirty(false)
          setSelected(p.to)
        }}
        onClose={() => setPendingSwitch(null)}
      />
      <ConfirmDialog
        open={!!panelPending && !panelPending.input}
        title={panelPending?.label || ''}
        message={panelPending?.confirm || ''}
        confirmLabel={panelPending?.label || ''}
        onConfirm={() => {
          const a = panelPending
          setPanelPending(null)
          if (a) void runPanelAction(a)
        }}
        onClose={() => setPanelPending(null)}
      />
      <PromptDialog
        open={!!panelPending?.input}
        title={panelPending?.label || ''}
        label={panelPending?.input?.label || ''}
        message={panelPending?.input?.message || panelPending?.confirm || undefined}
        placeholder={panelPending?.input?.placeholder || undefined}
        confirmLabel={panelPending?.label || undefined}
        onSubmit={(value) => {
          const a = panelPending
          setPanelPending(null)
          if (a) void runPanelAction(a, value)
        }}
        onClose={() => setPanelPending(null)}
      />
    </div>
  )
}

function CardForm({
  character, card, title, fields, values, tabs, activeTab, onTab, onDirty, refs,
  onSave, onCancel, onDelete, onAction,
}: {
  character: string
  card?: PanelCard
  title: string
  fields: PanelField[]
  values: Record<string, unknown>
  tabs: PanelTab[]
  activeTab: string
  onTab: (id: string) => void
  onDirty: (dirty: boolean) => void
  refs: PanelRefs
  onSave: (values: Record<string, unknown>) => Promise<OpResult>
  onCancel?: () => void
  onDelete?: () => Promise<OpResult>
  onAction?: (actionId: string, value?: string) => Promise<OpResult>
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
  const changed = fields.some((f) => norm(f, draft[f.key]) !== norm(f, initial[f.key]))
  useEffect(() => { onDirty(changed) }, [changed, onDirty])
  useEffect(() => () => onDirty(false), [onDirty])

  // Tabs: a field with no (or an unknown) tab belongs to the first tab; the
  // bar appears only when the fields fill two tabs or more.
  const tabOf = (f: PanelField) =>
    (f.tab && tabs.some((x) => x.id === f.tab) ? f.tab : tabs[0]?.id || '')
  const usedTabs = tabs.filter((x) => fields.some((f) => tabOf(f) === x.id))
  const current = usedTabs.length >= 2 ? (usedTabs.find((x) => x.id === activeTab) || usedTabs[0]) : null
  const shown = current ? fields.filter((f) => tabOf(f) === current.id) : fields
  const badTabs = new Set(fields.filter((f) => missingRequired(f, draft[f.key])).map(tabOf))

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
    a.confirm || a.input ? setPending({ kind: 'action', action: a }) : run(() => onAction!(a.id))
  // A card without fields (a status-only card) has nothing to save.
  const editable = fields.length > 0

  return (
    <div className="ga-fieldset ga-pp-card">
      <div className="ga-pp-head">
        <div className="ga-pp-head-info">
          <strong>{title || (isNew ? t('New') : '')}</strong>
          {(card?.badges || []).map((b) => <span key={b} className="ga-tag ga-tag-tier">{b}</span>)}
          {card?.subtitle ? <span className="ga-pp-muted">{card.subtitle}</span> : null}
          {card?.status ? <span className="ga-pp-status" title={card.status}>{card.status}</span> : null}
        </div>
        <div className="ga-pp-head-btns">
          {(card?.actions || []).map((a) => (
            <button key={a.id} type="button" disabled={busy}
              className={'ga-btn ga-btn-sm' + (a.primary ? ' ga-btn-primary' : '')}
              onClick={() => doAction(a)}>{a.label}</button>
          ))}
          {card?.actions.length ? <span className="ga-pp-sep" /> : null}
          {card?.deletable ? (
            <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" disabled={busy}
              onClick={() => setPending({ kind: 'delete' })}>{t('Delete')}</button>
          ) : null}
          {onCancel ? (
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy} onClick={onCancel}>
              {t('Cancel')}
            </button>
          ) : null}
          {!isNew && editable ? (
            <button type="button" className="ga-btn ga-btn-sm" disabled={busy || !changed}
              onClick={() => { setDraft(initial); setError('') }}>{t('Discard')}</button>
          ) : null}
          {editable ? (
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={busy || !(isNew || changed)}
              onClick={save}>{busy ? t('Saving…') : t('Save')}</button>
          ) : null}
        </div>
      </div>

      {error ? <div className="ga-pp-error">{error}</div> : null}

      {current ? (
        <div>
          <div className="ga-pp-tabs" role="tablist">
            {usedTabs.map((x) => (
              <button key={x.id} type="button" role="tab" aria-selected={x.id === current.id}
                className={'ga-tab' + (x.id === current.id ? ' is-active' : '')}
                onClick={() => onTab(x.id)}>
                {x.label}
                {badTabs.has(x.id)
                  ? <span className="ga-pp-tab-bad" title={t('A required field is empty.')}> ●</span>
                  : null}
              </button>
            ))}
          </div>
          {current.hint ? <div className="ga-pp-tabhint" title={current.hint}>{current.hint}</div> : null}
        </div>
      ) : null}

      <div className="ga-pp-body">
        <div className="ga-pp-fields">
          {shown.map((f) => (
            <div key={f.key} className={`ga-pp-f ga-pp-w${fieldSpan(f)}`}>
              <div className="ga-pp-label">
                {f.label}{f.required ? <span className="ga-pp-req"> *</span> : null}
              </div>
              <PanelFieldControl field={f} value={draft[f.key]} refs={refs} character={character} draft={draft}
                onChange={(v) => { setDraft((d) => ({ ...d, [f.key]: v })); setError('') }} />
              {f.hint ? <div className="ga-pp-hint" title={f.hint}>{f.hint}</div> : null}
            </div>
          ))}
        </div>
      </div>

      <PromptDialog
        open={pending?.kind === 'action' && !!pending.action.input}
        title={pending?.kind === 'action' ? pending.action.label : ''}
        label={pending?.kind === 'action' ? pending.action.input?.label || '' : ''}
        message={pending?.kind === 'action'
          ? pending.action.input?.message || pending.action.confirm || undefined : undefined}
        placeholder={pending?.kind === 'action' ? pending.action.input?.placeholder || undefined : undefined}
        confirmLabel={pending?.kind === 'action' ? pending.action.label : undefined}
        onSubmit={(value) => {
          const p = pending
          setPending(null)
          if (p?.kind === 'action') void run(() => onAction!(p.action.id, value))
        }}
        onClose={() => setPending(null)}
      />
      <ConfirmDialog
        open={!!pending && !(pending.kind === 'action' && pending.action.input)}
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
