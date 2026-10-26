import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

type Store = 'shared' | 'world'
interface ExpressionSet {
  id: string
  label: string
  default: string
  pose_prompt: string
  members: string[]
  store: Store
}
interface Props {
  selected: string
  reloadKey: string
  labels: Record<string, string>
  worldOnlyMembers: string[]
  onSelect: (id: string) => void
  onSaved: () => Promise<void>
}

/** Set metadata only; the existing catalog editor below owns member CRUD. */
export function ExpressionSetsEditor({ selected, reloadKey, labels, worldOnlyMembers, onSelect, onSaved }: Props) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [sets, setSets] = useState<Record<string, ExpressionSet>>({})
  const [draft, setDraft] = useState<ExpressionSet | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [creating, setCreating] = useState(false)
  const [initialPrompt, setInitialPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmRemove, setConfirmRemove] = useState(false)
  const edited = useRef(false)
  const previousSelection = useRef(selected)
  const update = (patch: Partial<ExpressionSet>) => {
    edited.current = true
    setDraft(current => current ? { ...current, ...patch } : current)
  }
  const load = useCallback(async () => {
    try {
      const result = await apiGet<{ sets: Record<string, ExpressionSet> }>('/poses/expression-sets')
      setSets(result.sets)
      setError('')
      return result.sets
    } catch (e) { setError((e as Error).message) }
  }, [])
  useEffect(() => { void load() }, [load, reloadKey])
  useEffect(() => {
    if (!edited.current || previousSelection.current !== selected) {
      setDraft(sets[selected] ? { ...sets[selected], members: [...sets[selected].members] } : null)
      setCreating(false)
      setConfirmRemove(false)
      edited.current = false
    }
    previousSelection.current = selected
  }, [selected, sets])
  const changed = creating || (draft && JSON.stringify(draft) !== JSON.stringify(sets[selected]))
  const [leaveTo, setLeaveTo] = useState<string | null>(null)
  const choose = (id: string) => {
    if (changed) setLeaveTo(id)
    else onSelect(id)
  }
  const begin = () => {
    edited.current = true
    setCreating(true)
    setExpanded(true)
    setInitialPrompt('')
    setDraft({ id: '', label: '', default: '', pose_prompt: '', members: [], store: 'world' })
  }
  const save = async () => {
    if (!draft || busy) return
    const id = draft.id.trim()
    const initialKey = `${id}_neutral`
    if (!id || !draft.label.trim() || !draft.pose_prompt.trim() || (creating && !initialPrompt.trim())) {
      setError(t('A set needs an id, label, fixed pose and an initial expression.'))
      return
    }
    setBusy(true)
    try {
      await apiPut(`/poses/expression-sets/${encodeURIComponent(id)}`, {
        ...draft,
        ...(creating ? { default: initialKey, members: [initialKey], entries: {
          [initialKey]: { label: 'Neutral', prompt: initialPrompt, synonyms: ['neutral'] },
        } } : {}),
      })
      toast(t('Saved'))
      edited.current = false
      await load()
      await onSaved()
      if (creating) onSelect(id)
      setCreating(false)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!draft || busy) return
    setBusy(true)
    try {
      await apiDelete(`/poses/expression-sets/${encodeURIComponent(draft.id)}?store=${draft.store}`)
      setConfirmRemove(false)
      edited.current = false
      const remaining = await load()
      if (remaining?.[selected]) await onSaved()
      else onSelect('humanoid')
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <section className="ga-section" style={{ marginBottom: 12, flexShrink: 0 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <label htmlFor="expression-set-picker">{t('Expression set')}</label>
      <select id="expression-set-picker" className="ga-input" style={{ width: 'auto', minWidth: 180 }} value={selected} onChange={e => choose(e.target.value)} disabled={busy}>
        {Object.values(sets).map(s => <option key={s.id} value={s.id}>{s.label} ({s.members.length})</option>)}
      </select>
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => setExpanded(v => !v)}>{t('Edit set')}</button>
      <button type="button" className="ga-btn ga-btn-sm" disabled={!!changed || busy} onClick={begin}>{t('New set')}</button>
    </div>
    <p className="ga-field-hint">{t('One image per outfit and expression. Activity poses and temporary states do not create extra images.')}</p>
    {error && <p role="alert" style={{ color: 'var(--error)' }}>{error}</p>}
    {leaveTo !== null && <div className="ga-form">
      <span>{t('Discard unsaved set changes?')}</span>
      <button type="button" className="ga-btn" onClick={() => { onSelect(leaveTo); setLeaveTo(null) }}>{t('Discard')}</button>
      <button type="button" className="ga-btn" onClick={() => setLeaveTo(null)}>{t('Cancel')}</button>
    </div>}
    {expanded && draft && <div className="ga-form" style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 240px), 1fr))', gap: 8, maxHeight: 'min(40vh, 340px)', overflowY: 'auto' }}>
      <label>{t('Set id')}<input className="ga-input" value={draft.id} disabled={!creating || busy} onChange={e => update({ id: e.target.value })} /></label>
      <label>{t('Label')}<input className="ga-input" value={draft.label} disabled={busy} onChange={e => update({ label: e.target.value })} /></label>
      <label>{t('Fixed image pose')}<textarea className="ga-input" rows={3} value={draft.pose_prompt} disabled={busy} onChange={e => update({ pose_prompt: e.target.value })} /></label>
      <label>{t('Store')}<select className="ga-input" value={draft.store} disabled={busy} onChange={e => update({ store: e.target.value as Store })}>
        <option value="world">{t('World')}</option><option value="shared">{t('Shared')}</option>
      </select></label>
      {creating ? <label>{t('Initial neutral expression')}<textarea className="ga-input" rows={3} value={initialPrompt} onChange={e => setInitialPrompt(e.target.value)} /></label>
        : <label>{t('Default expression')}<select className="ga-input" value={draft.default} disabled={busy} onChange={e => update({ default: e.target.value })}>
          {draft.members.map(key => <option key={key} value={key}>{labels[key] || key}</option>)}
        </select></label>}
      {!creating && <p className="ga-field-hint" style={{ gridColumn: '1 / -1' }}>{t('Edit the members and their synonyms in the catalog below.')} {draft.members.map(key => labels[key] || key).join(', ')}</p>}
      {!creating && draft.store === 'shared' && worldOnlyMembers.length > 0 && <p role="status" className="ga-field-hint" style={{ gridColumn: '1 / -1' }}>
        {t('Saving this set to Shared also publishes these World-only members:')} {worldOnlyMembers.map(key => `${labels[key] || key} (${key})`).join(', ')}
      </p>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, gridColumn: '1 / -1' }}>
        <button type="button" className="ga-btn ga-btn-primary" disabled={busy || !changed} onClick={() => void save()}>{t('Save set')}</button>
        <button type="button" className="ga-btn" disabled={busy} onClick={() => { edited.current = false; setDraft(sets[selected] || null); setCreating(false); setError('') }}>{t('Discard')}</button>
        {!creating && <button type="button" className="ga-btn ga-btn-danger" disabled={busy || (draft.store === 'shared' && ['humanoid', 'animal'].includes(draft.id))} onClick={() => setConfirmRemove(true)}>
          {draft.store === 'world' ? t('Remove World definition') : t('Delete set')}
        </button>}
      </div>
      {confirmRemove && <div style={{ gridColumn: '1 / -1' }}>
        <p>{t('Remove this set definition and its exclusive members? A Shared definition, if present, becomes visible again. Characters using a custom set prevent its deletion.')}</p>
        <button type="button" className="ga-btn ga-btn-danger" disabled={busy} onClick={() => void remove()}>{t('Confirm')}</button>
        <button type="button" className="ga-btn" onClick={() => setConfirmRemove(false)}>{t('Cancel')}</button>
      </div>}
    </div>}
  </section>
}
