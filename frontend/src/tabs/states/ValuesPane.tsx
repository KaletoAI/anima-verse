import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Field } from '@anima/player-ui'

type Source = 'shared' | 'world'
interface Rate { condition: string; per_hour: number; label: string }
interface Threshold { min?: number; max?: number; label: string; text: string; need?: { text: string; urgency: 'felt' | 'urgent' } }
interface Rule { key: string; per_hour: number; baseline: number | null; pull: number; rates: Rate[]; thresholds: Threshold[] }
interface Stat { key: string; name: string; effective: Rule; shipped: Rule | null; source: Source }
type Amounts = Record<string, number>
type Groups = Record<string, Amounts>
interface Gate { enabled: boolean; stat: string; below: number }
interface SettingValues { chat_cap_per_hour: number; rewards: Groups; skill_costs: Groups; perception_gate: Gate; event_effects: Groups }
interface Payload {
  stats: Stat[]
  settings: { [K in keyof SettingValues]: { value: SettingValues[K]; shipped: SettingValues[K]; source: Source } }
  skills: { id: string; name: string }[]
  categories: string[]
  occasions: string[]
}

function errorMessages(error: unknown): string[] {
  return error instanceof ApiError && Array.isArray(error.detail)
    ? error.detail.map(String) : [error instanceof Error ? error.message : String(error)]
}

/** Each card owns its draft, so writes cannot replace neighbouring drafts. */
function ValueCard<T,>({ title, path, initial, shipped, source: initialSource, setting = false, children, onRemove }: {
  title: string; path: string; initial: T; shipped: T | null; source: Source; setting?: boolean
  children: (value: T, change: (value: T) => void) => ReactNode; onRemove?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [value, setValue] = useState(() => structuredClone(initial))
  const [source, setSource] = useState(initialSource)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const write = async (reset: boolean) => {
    setBusy(true)
    setErrors([])
    try {
      const result = reset ? await apiDelete<{ ok: boolean }>(path)
        : await apiPut<{ ok: boolean }>(path, setting ? { value } : value)
      if (!result.ok) throw new Error(t('Could not save values.'))
      setSource(reset ? 'shared' : 'world')
      if (reset) {
        if (shipped !== null) setValue(structuredClone(shipped))
        else onRemove?.()
      }
      setConfirm(false)
      toast(t('Saved'))
    } catch (error) {
      setErrors(errorMessages(error))
      toast(t('Error'), 'error')
    } finally { setBusy(false) }
  }
  return <section className="ga-form" style={{ marginBottom: 12 }}>
    <h3>{title} <span className={`ga-source ga-source-${source}`}>{source === 'shared' ? t('Default') : t('World')}</span></h3>
    <fieldset disabled={busy} style={{ border: 0, padding: 0, minWidth: 0 }}>
      {children(value, setValue)}
      {errors.length > 0 && <ul role="alert">{errors.map((error, i) => <li key={i}>{error}</li>)}</ul>}
      <div className="ga-form-row">
        <button type="button" className="ga-btn ga-btn-primary" onClick={() => void write(false)}>{t('Save')}</button>
        {source === 'world' && <button type="button" className="ga-btn ga-btn-sm" onClick={() => setConfirm(true)}>{t('Reset to default')}</button>}
      </div>
      {confirm && <div className="ga-hint" role="group" aria-label={t('Reset to default')}>
        <p>{t('Discard this world override and restore the default?')}</p>
        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => void write(true)}>{t('Reset to default')}</button>{' '}
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => setConfirm(false)}>{t('Cancel')}</button>
      </div>}
    </fieldset>
  </section>
}

function NumberField({ label, value, onChange, min, max, step = 1 }: {
  label: string; value: number | null; onChange: (value: number | null) => void; min: number; max: number; step?: number
}) {
  return <Field label={label}><input className="ga-input" aria-label={label} type="number" min={min} max={max} step={step}
    value={value ?? ''} onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))} /></Field>
}

function ConditionInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useI18n()
  const [warnings, setWarnings] = useState<string[]>([])
  useEffect(() => {
    let alive = true
    setWarnings([])
    if (!value.trim()) return
    const timer = setTimeout(() => {
      apiGet<{ warnings?: string[] }>(`/admin/prompt-filters/validate?condition=${encodeURIComponent(value)}`)
        .then(result => { if (alive) setWarnings(result.warnings || []) })
        .catch(error => { if (alive) setWarnings(errorMessages(error)) })
    }, 350)
    return () => { alive = false; clearTimeout(timer) }
  }, [value])
  return <>
    <input className="ga-input" aria-label={t('Condition')} value={value}
      placeholder={t('condition, e.g. is_sleeping AND at_home')} onChange={e => onChange(e.target.value)} />
    {warnings.length > 0 && <ul className="ga-hint" role="status">{warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}
  </>
}

function RuleEditor({ value, onChange }: { value: Rule; onChange: (value: Rule) => void }) {
  const { t } = useI18n()
  const patch = (changes: Partial<Rule>) => onChange({ ...value, ...changes })
  return <div className="ga-form">
    <div className="ga-form-row">
      <NumberField label={t('Base rate per hour')} value={value.per_hour} min={-100} max={100} onChange={n => patch({ per_hour: n as number })} />
      <NumberField label={t('Baseline (empty = none)')} value={value.baseline} min={0} max={100} onChange={n => patch({ baseline: n })} />
      <NumberField label={t('Pull toward baseline')} value={value.pull} min={0} max={1} step={0.01} onChange={n => patch({ pull: n as number })} />
    </div>
    <h4>{t('Conditional rates')}</h4>
    <div style={{ overflowX: 'auto' }}><table className="ga-sched-table" style={{ minWidth: 700 }}>
      <thead><tr><th>{t('Condition')}</th><th>{t('Rate per hour')}</th><th>{t('Label')}</th><th>{t('Actions')}</th></tr></thead>
      <tbody>{value.rates.map((rate, i) => {
        const update = (changes: Partial<Rate>) => patch({ rates: value.rates.map((r, j) => j === i ? { ...r, ...changes } : r) })
        return <tr key={i}>
          <td><ConditionInput value={rate.condition} onChange={condition => update({ condition })} /></td>
          <td><NumberField label={t('Rate per hour')} value={rate.per_hour} min={-100} max={100} onChange={n => update({ per_hour: n as number })} /></td>
          <td><input className="ga-input" aria-label={t('Label')} value={rate.label} onChange={e => update({ label: e.target.value })} /></td>
          <td><button type="button" className="ga-btn ga-btn-sm" onClick={() => patch({ rates: value.rates.filter((_, j) => j !== i) })}>{t('Remove')}</button></td>
        </tr>
      })}</tbody>
    </table></div>
    <button type="button" className="ga-btn ga-btn-sm" onClick={() => patch({ rates: [...value.rates, { condition: '', per_hour: 0, label: '' }] })}>{t('Add rate')}</button>
    <h4>{t('Thresholds')}</h4>
    <div style={{ overflowX: 'auto' }}><table className="ga-sched-table" style={{ minWidth: 700 }}>
      <thead><tr>{[t('Bound'), t('Label'), t('Text'), t('Need text'), t('Urgency'), t('Actions')].map(label => <th key={label}>{label}</th>)}</tr></thead>
      <tbody>{value.thresholds.map((threshold, i) => {
        const update = (next: Threshold) => patch({ thresholds: value.thresholds.map((r, j) => j === i ? next : r) })
        const bound = threshold.min !== undefined ? 'min' : 'max'
        return <tr key={i}>
          <td><select className="ga-input" aria-label={t('Bound')} value={bound} onChange={e => {
            const next = { ...threshold }; delete next.min; delete next.max
            update({ ...next, [e.target.value]: threshold[bound] })
          }}><option value="min">{t('Minimum')}</option><option value="max">{t('Maximum')}</option></select>
            <NumberField label={t('Bound value')} value={threshold[bound] ?? null} min={0} max={100} onChange={n => update({ ...threshold, [bound]: n })} />
            {threshold.min !== undefined && threshold.max !== undefined && <NumberField label={t('Maximum')} value={threshold.max} min={0} max={100} onChange={n => update({ ...threshold, max: n as number })} />}
          </td>
          <td><input className="ga-input" aria-label={t('Label')} value={threshold.label} onChange={e => update({ ...threshold, label: e.target.value })} /></td>
          <td><textarea className="ga-textarea" aria-label={t('Text')} value={threshold.text} onChange={e => update({ ...threshold, text: e.target.value })} /></td>
          <td><textarea className="ga-textarea" aria-label={t('Need text')} value={threshold.need?.text ?? ''} disabled={!threshold.need}
            onChange={e => update({ ...threshold, need: { text: e.target.value, urgency: threshold.need!.urgency } })} /></td>
          <td><select className="ga-input" aria-label={t('Urgency')} value={threshold.need?.urgency ?? ''} onChange={e => {
            const next = { ...threshold }
            if (!e.target.value) delete next.need
            else next.need = { text: threshold.need?.text ?? '', urgency: e.target.value as 'felt' | 'urgent' }
            update(next)
          }}><option value="">{t('None')}</option><option value="felt">{t('Felt')}</option><option value="urgent">{t('Urgent')}</option></select></td>
          <td><button type="button" className="ga-btn ga-btn-sm" onClick={() => patch({ thresholds: value.thresholds.filter((_, j) => j !== i) })}>{t('Remove')}</button></td>
        </tr>
      })}</tbody>
    </table></div>
    <button type="button" className="ga-btn ga-btn-sm" onClick={() => patch({ thresholds: [...value.thresholds, { min: 0, label: '', text: '' }] })}>{t('Add threshold')}</button>
  </div>
}

function StatSelect({ stats, value, onChange, excluded = [] }: {
  stats: Stat[]; value: string; onChange: (value: string) => void; excluded?: string[]
}) {
  const { t } = useI18n()
  return <select className="ga-input" aria-label={t('Stat')} value={value} onChange={e => onChange(e.target.value)}>
    <option value="" disabled>{t('Select stat')}</option>
    {value && !stats.some(stat => stat.key === value) && <option value={value}>{value}</option>}
    {stats.filter(stat => stat.key === value || !excluded.includes(stat.key)).map(stat => <option key={stat.key} value={stat.key}>{stat.name}</option>)}
  </select>
}

function AmountEditor({ value, onChange, stats, cost = false }: { value: Amounts; onChange: (value: Amounts) => void; stats: Stat[]; cost?: boolean }) {
  const { t } = useI18n()
  const available = stats.find(stat => !(stat.key in value))
  return <div className="ga-form">
    {Object.entries(value).map(([stat, amount]) => <div className="ga-form-row" key={stat}>
      <Field label={t('Stat')}><StatSelect stats={stats} value={stat} excluded={Object.keys(value)} onChange={key => {
        const next = { ...value }; delete next[stat]; next[key] = amount; onChange(next)
      }} /></Field>
      <NumberField label={t('Amount')} value={amount} min={cost ? 0 : -100} max={100} onChange={n => onChange({ ...value, [stat]: n as number })} />
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => { const next = { ...value }; delete next[stat]; onChange(next) }}>{t('Remove')}</button>
    </div>)}
    <button type="button" className="ga-btn ga-btn-sm" disabled={!available} onClick={() => { if (available) onChange({ ...value, [available.key]: 0 }) }}>{t('Add stat')}</button>
  </div>
}

function GroupEditor({ value, onChange, groups, stats }: { value: Groups; onChange: (value: Groups) => void; groups: string[]; stats: Stat[] }) {
  const { t } = useI18n()
  const labels: Record<string, string> = {
    intent_done: t('Plan done'), gift_received: t('Gift received'),
    ambient: t('Ambient'), social: t('Social'), disruption: t('Disruption'), danger: t('Danger'),
  }
  return <>{groups.map(group => <Field key={group} label={labels[group] ?? group}>
    <AmountEditor value={value[group] ?? {}} onChange={amounts => onChange({ ...value, [group]: amounts })} stats={stats} />
  </Field>)}</>
}

function SkillCosts({ value, onChange, payload }: { value: Groups; onChange: (value: Groups) => void; payload: Payload }) {
  const { t } = useI18n()
  const available = payload.skills.find(skill => !(skill.id in value))
  return <>
    {Object.entries(value).map(([id, amounts]) => <div key={id} className="ga-section">
      <Field label={t('Skill')}><select className="ga-input" aria-label={t('Skill')} value={id} onChange={e => {
        const next = { ...value }; delete next[id]; next[e.target.value] = amounts; onChange(next)
      }}>
        {!payload.skills.some(skill => skill.id === id) && <option value={id}>{id}</option>}
        {payload.skills.filter(skill => skill.id === id || !(skill.id in value)).map(skill => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
      </select></Field>
      <AmountEditor value={amounts} stats={payload.stats} cost onChange={next => onChange({ ...value, [id]: next })} />
      <button type="button" className="ga-btn ga-btn-sm" onClick={() => { const next = { ...value }; delete next[id]; onChange(next) }}>{t('Remove skill')}</button>
    </div>)}
    <button type="button" className="ga-btn ga-btn-sm" disabled={!available} onClick={() => { if (available) onChange({ ...value, [available.id]: {} }) }}>{t('Add skill')}</button>
  </>
}

export function ValuesPane() {
  const { t } = useI18n()
  const [payload, setPayload] = useState<Payload | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let alive = true
    setErrors([])
    apiGet<Payload>('/admin/stat-rules').then(data => { if (alive) setPayload(data) })
      .catch(error => { if (alive) setErrors(errorMessages(error)) })
    return () => { alive = false }
  }, [attempt])
  if (!payload) return errors.length ? <div role="alert">{errors.join(', ')}{' '}
    <button type="button" className="ga-btn" onClick={() => setAttempt(n => n + 1)}>{t('Retry')}</button>
  </div> : <div className="ga-loading">{t('Loading…')}</div>
  const settingCard = <K extends keyof SettingValues>(name: K, title: string, render: (value: SettingValues[K], change: (value: SettingValues[K]) => void) => ReactNode) => {
    const setting = payload.settings[name]
    return <ValueCard key={name} title={title} path={`/admin/stat-rules/setting/${name}`} setting
      initial={setting.value} shipped={setting.shipped} source={setting.source}>{render}</ValueCard>
  }
  return <div className="ga-page-scroll">
    <h2>{t('Values')}</h2>
    {payload.stats.map(stat => <ValueCard key={stat.key} title={stat.name} path={`/admin/stat-rules/stat/${encodeURIComponent(stat.key)}`}
      initial={stat.effective} shipped={stat.shipped} source={stat.source}
      onRemove={() => setPayload(current => current && ({ ...current, stats: current.stats.filter(row => row.key !== stat.key) }))}>
      {(value, change) => <RuleEditor value={value} onChange={change} />}
    </ValueCard>)}
    <h2>{t('Settings')}</h2>
    {settingCard('chat_cap_per_hour', t('Chat cap per hour'), (value, change) => <NumberField label={t('Chat cap per hour')} value={value} min={0} max={100} onChange={n => change(n as number)} />)}
    {settingCard('rewards', t('Rewards'), (value, change) => <GroupEditor value={value} onChange={change} groups={payload.occasions} stats={payload.stats} />)}
    {settingCard('skill_costs', t('Skill costs'), (value, change) => <SkillCosts value={value} onChange={change} payload={payload} />)}
    {settingCard('perception_gate', t('Perception gate'), (value, change) => <div className="ga-form-row">
      <Field label={t('Enabled')}><input type="checkbox" aria-label={t('Enabled')} checked={value.enabled} onChange={e => change({ ...value, enabled: e.target.checked })} /></Field>
      <Field label={t('Stat')}><StatSelect stats={payload.stats} value={value.stat} onChange={stat => change({ ...value, stat })} /></Field>
      <NumberField label={t('Below')} value={value.below} min={0} max={100} onChange={n => change({ ...value, below: n as number })} />
    </div>)}
    {settingCard('event_effects', t('Event effects'), (value, change) => <GroupEditor value={value} onChange={change} groups={payload.categories} stats={payload.stats} />)}
  </div>
}
