import { useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useMoods } from '../../lib/moods'
import { actionId, createRequirement, effectTimings, type ActionCatalog } from './propActionAuthoring'
import type { ActionDefinition, ActionEffect, ActionRequirement, ActionTarget } from './propTypes'

export const referenceLabel = (key: string) => key.replace(/_/g, ' ').replace(/^./, letter => letter.toUpperCase())
export function ActionField({ label, children }: { label: string; children: ReactNode }) {
  return <label className="prop-action-field"><span>{label}</span>{children}</label>
}
export function ActionReference({ value, options, onChange, path, label }: {
  value: string; options: { value: string; label: string }[]; onChange: (value: string) => void; path: string; label: string
}) {
  const { t } = useI18n()
  const unknown = !!value && !options.some(option => option.value === value)
  return <ActionField label={label}><select className="ga-input" value={value}
    data-author-path={path} aria-invalid={unknown || !value} onChange={event => onChange(event.target.value)}>
    <option value="">{t("Please select")}</option>
    {unknown && <option value={value}>{t("Unknown reference")}: {value}</option>}
    {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
  </select>{unknown && <span className="prop-action-error">{t("Reference is retained. Reassign it or remove this row.")}</span>}</ActionField>
}
export function GameDuration({ value, onChange, path, label }: { value: number; onChange: (seconds: number) => void; path: string; label: string }) {
  const { t } = useI18n()
  const [unit, setUnit] = useState(60)
  return <ActionField label={label}><span className="prop-action-duration">
    <input className="ga-input" type="number" min={0} step="any" data-author-path={path}
      value={Number.isFinite(value) ? value / unit : ''} aria-label={label} aria-invalid={!Number.isFinite(value) || value <= 0}
      onChange={event => onChange(event.target.value === '' ? NaN : Number(event.target.value) * unit)} />
    <select className="ga-input" aria-label={t("Game time unit")} value={unit} onChange={event => setUnit(Number(event.target.value))}>
      <option value={1}>{t("Game seconds")}</option><option value={60}>{t("Game minutes")}</option><option value={3600}>{t("Game hours")}</option>
    </select></span></ActionField>
}
function TargetField({ action, value, onChange, path }: { action: ActionDefinition; value: ActionTarget; onChange: (target: ActionTarget) => void; path: string }) {
  const { t } = useI18n()
  const options = [{ value: 'actor', label: t("Actor") }]
  if (action.participants === 2) options.push({ value: 'partner', label: t("Partner") }, { value: 'both', label: t("Both people") })
  return <ActionReference value={value} options={options} label={t("Target person")} path={path} onChange={target => onChange(target as ActionTarget)} />
}

export function PropActionRequirements({ action, catalog, path, onChange, onReloadCatalog }: {
  action: ActionDefinition; catalog: ActionCatalog; path: string; onChange: (rows: ActionRequirement[]) => void
  onReloadCatalog?: () => void
}) {
  const { t } = useI18n()
  const update = (id: string, next: ActionRequirement) => onChange(action.requirements.map(row => row.id === id ? next : row))
  return <section className="prop-action-section"><h4>{t("Requirements")}</h4>
    <p className="ga-hint">{t("All requirements must be met. Unknown or unreadable values block the action. Always checked again on arrival.")}</p>
    {action.requirements.map((row, index) => {
      const rowPath = `${path}.requirements.${index}`
      return <fieldset key={row.id} className="prop-action-row"><legend>{t("Requirement")} {index + 1}</legend>
        <div className="prop-action-grid"><ActionField label={t("Type")}><select className="ga-input" value={row.type} data-author-path={`${rowPath}.type`}
          onChange={event => update(row.id, event.target.value === 'stat'
            ? { id: row.id, target: row.target, type: 'stat', stat: catalog.stats[0] || '', op: 'ge', value: 0 }
            : { id: row.id, target: row.target, type: 'condition', condition_id: catalog.conditions[0]?.name || '', present: true })}>
          <option value="stat">{t("Compare stat")}</option><option value="condition">{t("Check condition")}</option></select></ActionField>
          <TargetField action={action} value={row.target} path={`${rowPath}.target`} onChange={target => update(row.id, { ...row, target })} />
          {row.type === 'stat' ? <>
            <ActionReference value={row.stat} label={t("Existing stat")} path={`${rowPath}.stat`} options={catalog.stats.map(value => ({ value, label: t(referenceLabel(value)) }))} onChange={stat => update(row.id, { ...row, stat })} />
            <ActionField label={t("Comparison")}><select className="ga-input" value={row.op} data-author-path={`${rowPath}.op`} onChange={event => update(row.id, { ...row, op: event.target.value as typeof row.op })}>
              {([['lt', "Less than"], ['le', "At most"], ['eq', "Equal to"], ['ge', "At least"], ['gt', "Greater than"]] as const).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
            </select></ActionField>
            <ActionField label={t("Threshold")}><input className="ga-input" type="number" step="any" value={Number.isFinite(row.value) ? row.value : ''} data-author-path={`${rowPath}.value`}
              onChange={event => update(row.id, { ...row, value: event.target.value === '' ? NaN : Number(event.target.value) })} /></ActionField>
          </> : <>
            <ActionReference value={row.condition_id} label={t("Existing condition")} path={`${rowPath}.condition_id`} options={catalog.conditions.map(condition => ({ value: condition.name, label: condition.label || referenceLabel(condition.name) }))} onChange={condition_id => update(row.id, { ...row, condition_id })} />
            <ActionField label={t("Required condition")}><select className="ga-input" value={String(row.present)} data-author-path={`${rowPath}.present`} onChange={event => update(row.id, { ...row, present: event.target.value === 'true' })}>
              <option value="true">{t("Must be present")}</option><option value="false">{t("Must be absent")}</option>
            </select></ActionField>
          </>}
        </div><button type="button" className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => onChange(action.requirements.filter(item => item.id !== row.id))}>{t("Remove requirement")}</button>
      </fieldset>
    })}
    <button type="button" className="ga-btn ga-btn-sm" disabled={!catalog.stats.length && !catalog.conditions.length} onClick={() => {
      const row = createRequirement(catalog)
      if (row) onChange([...action.requirements, row])
    }}>{t("Add requirement")}</button>
    {catalog.status !== 'ready' && <p role={catalog.status === 'error' ? 'alert' : 'status'}>{t(catalog.status === 'loading'
      ? "Loading stats and conditions. A requirement can be added once a selection is available."
      : "Could not load stats and conditions. Reload the catalog.")}</p>}
    {catalog.status === 'ready' && !catalog.stats.length && !catalog.conditions.length && <p role="status">{t("No stats or conditions in the world catalog. Create a world stat or condition first, then reload the catalog.")}</p>}
    {onReloadCatalog && <button type="button" className="ga-btn ga-btn-sm" disabled={catalog.status === 'loading'} onClick={onReloadCatalog}>{t("Reload catalog")}</button>}
  </section>
}

export function PropActionEffects({ action, catalog, path, onChange }: {
  action: ActionDefinition; catalog: ActionCatalog; path: string; onChange: (rows: ActionEffect[]) => void
}) {
  const { t } = useI18n()
  const moods = useMoods()
  const update = (id: string, next: ActionEffect) => onChange(action.effects.map(row => row.id === id ? next : row))
  const newEffect = (type: ActionEffect['type'], id: string = actionId(), target: ActionTarget = 'actor', previousWhen?: ActionEffect['when']): ActionEffect => {
    const allowed = effectTimings(action, type)
    const when = previousWhen && allowed.includes(previousWhen) ? previousWhen : allowed.includes('success') ? 'success' : type === 'stat_delta' && allowed.includes('active') ? 'active' : 'start'
    const base = { id, target, when }
    return type === 'stat_delta' ? { ...base, type, stat: catalog.stats[0] || '', amount: 1 }
      : type === 'mood' ? { ...base, type, mood: moods[0] || '' }
        : type === 'condition_add' ? { ...base, type, condition_id: catalog.conditions[0]?.name || '', duration_game_s: 3600, repeat: 'refresh' }
          : { ...base, type, condition_id: catalog.conditions[0]?.name || '' }
  }
  const summary = action.effects.map(row => {
    const timing = t(row.when === 'active' ? 'While active:' : row.when === 'success' ? 'On success:' : 'On start:')
    const target = row.target === 'actor' ? '' : ` (${t(row.target === 'partner' ? 'Partner' : 'Both')})`
    const text = row.type === 'stat_delta' ? `${t(referenceLabel(row.stat))} ${row.amount >= 0 ? '+' : ''}${row.amount}${row.when === 'active' ? t('/min') : ''}`
      : row.type === 'mood' ? `${t('Mood')} ${row.mood}` : `${t(row.type === 'condition_add' ? 'Add condition' : 'Remove condition')} ${row.condition_id}`
    return `${timing} ${text}${target}`
  }).join(' · ')
  return <details className="prop-action-section"><summary>{t('Effects')} · {summary || t('No effects')}</summary>
    <p className="ga-hint">{t("One-time effects apply at the selected moment. Stat rates count only active game minutes, excluding approach, freeze and cancellation time.")}</p>
    {action.ability === 'sleep' && <p className="ga-hint">{t("Sleep and recovery belong to the existing sleep mechanics. No additional active regeneration on the bed.")}</p>}
    {(action.ability === 'pose' || action.ability === 'pair') && <p className="ga-hint">{t("Until explicitly ended: no completion bonus for briefly starting and stopping.")}</p>}
    {action.effects.map((row, index) => {
      const rowPath = `${path}.effects.${index}`
      const allowed = effectTimings(action, row.type)
      return <fieldset key={row.id} className="prop-action-row"><legend>{t("Effect")} {index + 1}</legend><div className="prop-action-grid">
        <ActionField label={t("Effect type")}><select className="ga-input" value={row.type} data-author-path={`${rowPath}.type`} onChange={event => update(row.id, newEffect(event.target.value as ActionEffect['type'], row.id, row.target, row.when))}>
          <option value="stat_delta">{t("Change stat")}</option><option value="mood">{t("Set mood")}</option><option value="condition_add">{t("Add condition")}</option><option value="condition_remove">{t("Remove condition")}</option>
        </select></ActionField>
        <TargetField action={action} value={row.target} path={`${rowPath}.target`} onChange={target => update(row.id, { ...row, target })} />
        <ActionField label={t("Timing")}><select className="ga-input" value={row.when} data-author-path={`${rowPath}.when`} aria-invalid={!allowed.includes(row.when)} onChange={event => update(row.id, { ...row, when: event.target.value as ActionEffect['when'] })}>
          {!allowed.includes(row.when) && <option value={row.when}>{t("Invalid timing")} ({t(row.when === 'success' ? "On success" : row.when === 'active' ? "While active" : "On start")})</option>}
          {allowed.map(when => <option key={when} value={when}>{t(when === 'start' ? "When active at the destination" : when === 'success' ? action.ability === 'sleep' ? "When actually falling asleep" : "After successful drinking" : "Per active game minute")}</option>)}
        </select></ActionField>
        {row.type === 'stat_delta' && <>
          <ActionReference value={row.stat} label={t("Existing stat")} path={`${rowPath}.stat`} options={catalog.stats.map(value => ({ value, label: t(referenceLabel(value)) }))} onChange={stat => update(row.id, { ...row, stat })} />
          <ActionField label={t(row.when === 'active' ? "Change per game minute" : "Change (amount)")}><input className="ga-input" type="number" step="any" value={Number.isFinite(row.amount) ? row.amount : ''} data-author-path={`${rowPath}.amount`}
            onChange={event => update(row.id, { ...row, amount: event.target.value === '' ? NaN : Number(event.target.value) })} /></ActionField>
        </>}
        {row.type === 'mood' && <ActionField label={t("Mood")}><input className="ga-input" value={row.mood} list={`prop-action-moods-${row.id}`} data-author-path={`${rowPath}.mood`} onChange={event => update(row.id, { ...row, mood: event.target.value })} />
          <datalist id={`prop-action-moods-${row.id}`}>{moods.map(mood => <option key={mood} value={mood}>{t(referenceLabel(mood))}</option>)}</datalist>
          <span className="ga-hint">{t("Existing suggestions or free text. A fixed mood does not revert automatically; use a condition for a temporary effect.")}</span></ActionField>}
        {(row.type === 'condition_add' || row.type === 'condition_remove') && <ActionReference value={row.condition_id} label={t("Existing condition")} path={`${rowPath}.condition_id`} options={catalog.conditions.map(condition => ({ value: condition.name, label: condition.label || referenceLabel(condition.name) }))} onChange={condition_id => update(row.id, { ...row, condition_id })} />}
        {row.type === 'condition_add' && <>
          <GameDuration label={t("Condition duration")} value={row.duration_game_s} path={`${rowPath}.duration_game_s`} onChange={duration_game_s => update(row.id, { ...row, duration_game_s })} />
          <ActionField label={t("If the condition already exists")}><select className="ga-input" value={row.repeat} data-author-path={`${rowPath}.repeat`} onChange={event => update(row.id, { ...row, repeat: event.target.value as 'ignore' | 'refresh' })}>
            <option value="ignore">{t("Keep the existing condition unchanged")}</option><option value="refresh">{t("Refresh duration (do not stack)")}</option>
          </select></ActionField>
        </>}
      </div><button type="button" className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => onChange(action.effects.filter(item => item.id !== row.id))}>{t("Remove effect")}</button></fieldset>
    })}
    <button type="button" className="ga-btn ga-btn-sm" onClick={() => onChange([...action.effects, newEffect(catalog.stats.length ? 'stat_delta' : 'mood')])}>{t("Add effect")}</button>
    <p className="ga-hint">{t("Temporary stat bonuses belong in the condition, not as an identical base stat bonus here.")}
      {' '}<a href="#states">{t("Open condition definitions")}</a></p>
  </details>
}
