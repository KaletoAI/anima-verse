import { useState, type ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { useMoods } from '../../lib/moods'
import { actionId, effectTimings, type ActionCatalog } from './propActionAuthoring'
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
    <option value="">{t('Bitte wählen')}</option>
    {unknown && <option value={value}>{t('Unbekannter Verweis')}: {value}</option>}
    {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
  </select>{unknown && <span className="prop-action-error">{t('Verweis bleibt erhalten. Bitte neu zuordnen oder diese Zeile entfernen.')}</span>}</ActionField>
}
export function GameDuration({ value, onChange, path, label }: { value: number; onChange: (seconds: number) => void; path: string; label: string }) {
  const { t } = useI18n()
  const [unit, setUnit] = useState(60)
  return <ActionField label={label}><span className="prop-action-duration">
    <input className="ga-input" type="number" min={0} step="any" data-author-path={path}
      value={Number.isFinite(value) ? value / unit : ''} aria-label={label} aria-invalid={!Number.isFinite(value) || value <= 0}
      onChange={event => onChange(event.target.value === '' ? NaN : Number(event.target.value) * unit)} />
    <select className="ga-input" aria-label={t('Spielzeiteinheit')} value={unit} onChange={event => setUnit(Number(event.target.value))}>
      <option value={1}>{t('Spielsekunden')}</option><option value={60}>{t('Spielminuten')}</option><option value={3600}>{t('Spielstunden')}</option>
    </select></span></ActionField>
}
function TargetField({ action, value, onChange, path }: { action: ActionDefinition; value: ActionTarget; onChange: (target: ActionTarget) => void; path: string }) {
  const { t } = useI18n()
  const options = [{ value: 'actor', label: t('Ausführende Person') }]
  if (action.participants === 2) options.push({ value: 'partner', label: t('Partnerperson') }, { value: 'both', label: t('Beide Personen') })
  return <ActionReference value={value} options={options} label={t('Zielperson')} path={path} onChange={target => onChange(target as ActionTarget)} />
}

export function PropActionRequirements({ action, catalog, path, onChange }: {
  action: ActionDefinition; catalog: ActionCatalog; path: string; onChange: (rows: ActionRequirement[]) => void
}) {
  const { t } = useI18n()
  const update = (id: string, next: ActionRequirement) => onChange(action.requirements.map(row => row.id === id ? next : row))
  return <section className="prop-action-section"><h4>{t('Voraussetzungen')}</h4>
    <p className="ga-hint">{t('Alle Voraussetzungen müssen erfüllt sein. Unbekannte oder bei der Testperson nicht lesbare Werte sperren die Handlung. Bei Ankunft wird immer erneut geprüft.')}</p>
    {action.requirements.map((row, index) => {
      const rowPath = `${path}.requirements.${index}`
      return <fieldset key={row.id} className="prop-action-row"><legend>{t('Voraussetzung')} {index + 1}</legend>
        <div className="prop-action-grid"><ActionField label={t('Art')}><select className="ga-input" value={row.type} data-author-path={`${rowPath}.type`}
          onChange={event => update(row.id, event.target.value === 'stat'
            ? { id: row.id, target: row.target, type: 'stat', stat: catalog.stats[0] || '', op: 'ge', value: 0 }
            : { id: row.id, target: row.target, type: 'condition', condition_id: catalog.conditions[0]?.name || '', present: true })}>
          <option value="stat">{t('Wert vergleichen')}</option><option value="condition">{t('Zustand prüfen')}</option></select></ActionField>
          <TargetField action={action} value={row.target} path={`${rowPath}.target`} onChange={target => update(row.id, { ...row, target })} />
          {row.type === 'stat' ? <>
            <ActionReference value={row.stat} label={t('Vorhandener Wert')} path={`${rowPath}.stat`} options={catalog.stats.map(value => ({ value, label: t(referenceLabel(value)) }))} onChange={stat => update(row.id, { ...row, stat })} />
            <ActionField label={t('Vergleich')}><select className="ga-input" value={row.op} data-author-path={`${rowPath}.op`} onChange={event => update(row.id, { ...row, op: event.target.value as typeof row.op })}>
              {([['lt', 'Kleiner als'], ['le', 'Höchstens'], ['eq', 'Gleich'], ['ge', 'Mindestens'], ['gt', 'Größer als']] as const).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
            </select></ActionField>
            <ActionField label={t('Schwellenwert')}><input className="ga-input" type="number" step="any" value={Number.isFinite(row.value) ? row.value : ''} data-author-path={`${rowPath}.value`}
              onChange={event => update(row.id, { ...row, value: event.target.value === '' ? NaN : Number(event.target.value) })} /></ActionField>
          </> : <>
            <ActionReference value={row.condition_id} label={t('Vorhandener Zustand')} path={`${rowPath}.condition_id`} options={catalog.conditions.map(condition => ({ value: condition.name, label: condition.label || referenceLabel(condition.name) }))} onChange={condition_id => update(row.id, { ...row, condition_id })} />
            <ActionField label={t('Erforderlicher Zustand')}><select className="ga-input" value={String(row.present)} data-author-path={`${rowPath}.present`} onChange={event => update(row.id, { ...row, present: event.target.value === 'true' })}>
              <option value="true">{t('Muss vorhanden sein')}</option><option value="false">{t('Darf nicht vorhanden sein')}</option>
            </select></ActionField>
          </>}
        </div><button type="button" className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => onChange(action.requirements.filter(item => item.id !== row.id))}>{t('Voraussetzung entfernen')}</button>
      </fieldset>
    })}
    <button type="button" className="ga-btn ga-btn-sm" disabled={!catalog.stats.length && !catalog.conditions.length} onClick={() => onChange([...action.requirements, catalog.stats.length
      ? { id: actionId(), target: 'actor', type: 'stat', stat: catalog.stats[0], op: 'ge', value: 0 }
      : { id: actionId(), target: 'actor', type: 'condition', condition_id: catalog.conditions[0].name, present: true }])}>{t('Voraussetzung hinzufügen')}</button>
  </section>
}

export function PropActionEffects({ action, catalog, path, onChange }: {
  action: ActionDefinition; catalog: ActionCatalog; path: string; onChange: (rows: ActionEffect[]) => void
}) {
  const { t } = useI18n()
  const moods = useMoods()
  const update = (id: string, next: ActionEffect) => onChange(action.effects.map(row => row.id === id ? next : row))
  const newEffect = (type: ActionEffect['type'], id = actionId(), target: ActionTarget = 'actor', previousWhen?: ActionEffect['when']): ActionEffect => {
    const allowed = effectTimings(action, type)
    const when = previousWhen && allowed.includes(previousWhen) ? previousWhen : allowed.includes('success') ? 'success' : type === 'stat_delta' && allowed.includes('active') ? 'active' : 'start'
    const base = { id, target, when }
    return type === 'stat_delta' ? { ...base, type, stat: catalog.stats[0] || '', amount: 1 }
      : type === 'mood' ? { ...base, type, mood: moods[0] || '' }
        : type === 'condition_add' ? { ...base, type, condition_id: catalog.conditions[0]?.name || '', duration_game_s: 3600, repeat: 'refresh' }
          : { ...base, type, condition_id: catalog.conditions[0]?.name || '' }
  }
  return <section className="prop-action-section"><h4>{t('Wirkungen')}</h4>
    <p className="ga-hint">{t('Einmalige Wirkungen gelten zum gewählten Zeitpunkt. Laufende Werteänderungen zählen ausschließlich aktive Spielminuten, nicht Anlauf, Freeze oder Abbruchzeit.')}</p>
    {action.ability === 'sleep' && <p className="ga-hint">{t('Schlaf und Erholung gehören der bestehenden Schlafmechanik. Keine zusätzliche laufende Regeneration am Bett.')}</p>}
    {(action.ability === 'pose' || action.ability === 'pair') && <p className="ga-hint">{t('Bis ausdrücklich beendet: kein Abschlussbonus für kurzes Starten und Stoppen.')}</p>}
    {action.effects.map((row, index) => {
      const rowPath = `${path}.effects.${index}`
      const allowed = effectTimings(action, row.type)
      return <fieldset key={row.id} className="prop-action-row"><legend>{t('Wirkung')} {index + 1}</legend><div className="prop-action-grid">
        <ActionField label={t('Wirkungsart')}><select className="ga-input" value={row.type} data-author-path={`${rowPath}.type`} onChange={event => update(row.id, newEffect(event.target.value as ActionEffect['type'], row.id, row.target, row.when))}>
          <option value="stat_delta">{t('Wert ändern')}</option><option value="mood">{t('Stimmung setzen')}</option><option value="condition_add">{t('Zustand hinzufügen')}</option><option value="condition_remove">{t('Zustand entfernen')}</option>
        </select></ActionField>
        <TargetField action={action} value={row.target} path={`${rowPath}.target`} onChange={target => update(row.id, { ...row, target })} />
        <ActionField label={t('Zeitpunkt')}><select className="ga-input" value={row.when} data-author-path={`${rowPath}.when`} aria-invalid={!allowed.includes(row.when)} onChange={event => update(row.id, { ...row, when: event.target.value as ActionEffect['when'] })}>
          {!allowed.includes(row.when) && <option value={row.when}>{t('Ungültiger Zeitpunkt')} ({t(row.when === 'success' ? 'Bei Erfolg' : row.when === 'active' ? 'Während aktiv' : 'Beim Start')})</option>}
          {allowed.map(when => <option key={when} value={when}>{t(when === 'start' ? 'Beim Aktivwerden am Ziel' : when === 'success' ? action.ability === 'sleep' ? 'Beim echten Einschlafen' : 'Nach erfolgreichem Trinken' : 'Pro aktiver Spielminute')}</option>)}
        </select></ActionField>
        {row.type === 'stat_delta' && <>
          <ActionReference value={row.stat} label={t('Vorhandener Wert')} path={`${rowPath}.stat`} options={catalog.stats.map(value => ({ value, label: t(referenceLabel(value)) }))} onChange={stat => update(row.id, { ...row, stat })} />
          <ActionField label={t(row.when === 'active' ? 'Änderung pro Spielminute' : 'Änderung (Betrag)')}><input className="ga-input" type="number" step="any" value={Number.isFinite(row.amount) ? row.amount : ''} data-author-path={`${rowPath}.amount`}
            onChange={event => update(row.id, { ...row, amount: event.target.value === '' ? NaN : Number(event.target.value) })} /></ActionField>
        </>}
        {row.type === 'mood' && <ActionField label={t('Stimmung')}><input className="ga-input" value={row.mood} list={`prop-action-moods-${row.id}`} data-author-path={`${rowPath}.mood`} onChange={event => update(row.id, { ...row, mood: event.target.value })} />
          <datalist id={`prop-action-moods-${row.id}`}>{moods.map(mood => <option key={mood} value={mood}>{t(referenceLabel(mood))}</option>)}</datalist>
          <span className="ga-hint">{t('Vorhandene Vorschläge oder freier Text. Eine feste Stimmung springt nicht automatisch zurück; für zeitweilige Wirkung einen Zustand verwenden.')}</span></ActionField>}
        {(row.type === 'condition_add' || row.type === 'condition_remove') && <ActionReference value={row.condition_id} label={t('Vorhandener Zustand')} path={`${rowPath}.condition_id`} options={catalog.conditions.map(condition => ({ value: condition.name, label: condition.label || referenceLabel(condition.name) }))} onChange={condition_id => update(row.id, { ...row, condition_id })} />}
        {row.type === 'condition_add' && <>
          <GameDuration label={t('Zustandsdauer')} value={row.duration_game_s} path={`${rowPath}.duration_game_s`} onChange={duration_game_s => update(row.id, { ...row, duration_game_s })} />
          <ActionField label={t('Wenn der Zustand schon besteht')}><select className="ga-input" value={row.repeat} data-author-path={`${rowPath}.repeat`} onChange={event => update(row.id, { ...row, repeat: event.target.value as 'ignore' | 'refresh' })}>
            <option value="ignore">{t('Bestehenden Zustand unverändert lassen')}</option><option value="refresh">{t('Dauer auffrischen (nicht stapeln)')}</option>
          </select></ActionField>
        </>}
      </div><button type="button" className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => onChange(action.effects.filter(item => item.id !== row.id))}>{t('Wirkung entfernen')}</button></fieldset>
    })}
    <button type="button" className="ga-btn ga-btn-sm" onClick={() => onChange([...action.effects, newEffect(catalog.stats.length ? 'stat_delta' : 'mood')])}>{t('Wirkung hinzufügen')}</button>
    <p className="ga-hint">{t('Temporäre Wertboni werden im Zustand gepflegt, nicht noch einmal als identischer Basiswertbonus hier.')}
      {' '}<a href="#states">{t('Zustandsdefinitionen öffnen')}</a></p>
  </section>
}
