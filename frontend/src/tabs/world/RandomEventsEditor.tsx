import { useEffect, useState } from 'react'
import { apiGet } from '../../lib/api'
import { useI18n } from '../../i18n/I18nProvider'
import { Field } from '../../components/Field'
import { EVENT_CATEGORIES, type EventSettings } from './worldTypes'
import { CommaListInput } from '../../components/CommaListInput'

// Per-location probability, categories and immediate stat effects.
interface RandomEventsEditorProps {
  value: EventSettings | undefined
  onChange: (next: EventSettings) => void
}

export function RandomEventsEditor({ value, onChange }: RandomEventsEditorProps) {
  const { t } = useI18n()
  const [keys, setKeys] = useState<string[]>([])
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    apiGet<{ keys: string[] }>('/world/stat-keys')
      .then(data => { if (active) setKeys(data.keys) })
      .catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [])
  const settings: EventSettings = value || {}
  const probabilityPct = Math.round(((settings.event_probability ?? 0.1) as number) * 100)
  const allowed = settings.allowed_categories || [...EVENT_CATEGORIES]

  const update = (patch: Partial<EventSettings>) => {
    onChange({ ...settings, ...patch })
  }

  return (
    <div className="ga-form">
      <div className="ga-form-row">
        <Field
          label={t('Probability %')}
          hint={t('Per hour. Overrides the global default.')}
        >
          <input
            type="number"
            className="ga-input"
            min={0}
            max={50}
            step={1}
            value={probabilityPct}
            onChange={(e) =>
              update({ event_probability: (parseInt(e.target.value, 10) || 0) / 100 })
            }
          />
        </Field>
        <Field label={t('Max')}>
          <input
            type="number"
            className="ga-input"
            min={1}
            max={10}
            value={settings.max_concurrent_events ?? 1}
            onChange={(e) =>
              update({ max_concurrent_events: parseInt(e.target.value, 10) || 1 })
            }
          />
        </Field>
        <Field label={t('Cooldown h')}>
          <input
            type="number"
            className="ga-input"
            min={0}
            max={48}
            value={settings.event_cooldown_hours ?? 2}
            onChange={(e) =>
              update({ event_cooldown_hours: parseInt(e.target.value, 10) || 0 })
            }
          />
        </Field>
      </div>
      <Field label={t('Allowed categories')}>
        <div className="ga-form-row" style={{ gap: 10, flexWrap: 'wrap' }}>
          {EVENT_CATEGORIES.map((cat) => {
            const checked = allowed.includes(cat)
            return (
              <label key={cat} className="ga-form-check">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...allowed.filter((c) => c !== cat), cat]
                      : allowed.filter((c) => c !== cat)
                    update({ allowed_categories: next })
                  }}
                />
                {cat}
              </label>
            )
          })}
        </div>
      </Field>
      <Field label={t('Immediate stat effects')} hint={t('Applied once per event and character. Use world defaults or override each category; an empty override applies nothing.')}>
        {failed && <p role="alert">{t('Could not load stat keys.')}</p>}
        {EVENT_CATEGORIES.map(category => {
          const effects = settings.stat_effects || {}
          const overridden = Object.prototype.hasOwnProperty.call(effects, category)
          const rows = Object.entries(effects[category] || {})
          const setEffects = (next: Record<string, number>) => update({ stat_effects: { ...effects, [category]: next } })
          return <fieldset key={category}>
            <legend>{category}</legend>
            <label className="ga-form-check">
              <input type="checkbox" checked={overridden} onChange={e => {
                const next = { ...effects }
                if (e.target.checked) next[category] = {}
                else delete next[category]
                update({ stat_effects: next })
              }} />
              {t('Override world effects')}
            </label>
            {overridden && <>
              {rows.length === 0 && <p>{t('No immediate effects.')}</p>}
              {rows.map(([stat, amount]) => <div className="ga-form-row" key={stat}>
                <select className="ga-input" aria-label={t('Stat')} value={stat} onChange={e => {
                  const next = { ...effects[category] }
                  delete next[stat]
                  next[e.target.value] = amount
                  setEffects(next)
                }}>
                  {!keys.includes(stat) && <option value={stat}>{stat}</option>}
                  {keys.filter(key => key === stat || !Object.prototype.hasOwnProperty.call(effects[category], key))
                    .map(key => <option key={key} value={key}>{key}</option>)}
                </select>
                <input className="ga-input" type="number" min={-100} max={100} step={1}
                  aria-label={t('Amount')} value={amount} onChange={e => setEffects({
                    ...effects[category], [stat]: Math.max(-100, Math.min(100, Math.trunc(Number(e.target.value) || 0))),
                  })} />
                <button type="button" className="ga-btn ga-btn-sm" onClick={() => {
                  const next = { ...effects[category] }
                  delete next[stat]
                  setEffects(next)
                }}>{t('Remove')}</button>
              </div>)}
              <button type="button" className="ga-btn ga-btn-sm"
                disabled={!keys.some(key => !Object.prototype.hasOwnProperty.call(effects[category], key))}
                onClick={() => {
                  const key = keys.find(key => !Object.prototype.hasOwnProperty.call(effects[category], key))
                  if (key) setEffects({ ...effects[category], [key]: 0 })
                }}>{t('Add effect')}</button>
            </>}
          </fieldset>
        })}
      </Field>
      <Field label={t('Blacklist')} hint={t('Comma-separated event names that must never fire here.')}>
        <CommaListInput
          value={settings.event_blacklist || []}
          placeholder={t('e.g. Fire, Earthquake')}
          onChange={(next) => update({ event_blacklist: next })}
        />
      </Field>
    </div>
  )
}
