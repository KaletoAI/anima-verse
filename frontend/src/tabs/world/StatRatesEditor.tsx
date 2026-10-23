import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { Field } from '../../components/Field'
import type { StatRate } from './worldTypes'

export function StatRatesEditor({ value, onChange }: {
  value: StatRate[]
  onChange: (rates: StatRate[]) => void
}) {
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

  return <Field label={t('Stat rates')} hint={t('Added each game hour. Up to 10 rates, from -50 to 50 per hour.')}>
    {failed && <p role="alert">{t('Could not load stat keys.')}</p>}
    {value.map((rate, index) => <div className="ga-form-row" key={index}>
      <select className="ga-input" aria-label={t('Stat')} value={rate.stat}
        onChange={e => onChange(value.map((row, i) => i === index ? { ...row, stat: e.target.value } : row))}>
        <option value="">{t('Select stat')}</option>
        {rate.stat && !keys.includes(rate.stat) && <option value={rate.stat}>{rate.stat}</option>}
        {keys.map(key => <option key={key} value={key}>{key}</option>)}
      </select>
      <input className="ga-input" type="number" min={-50} max={50} step={1}
        aria-label={t('Per hour')} value={rate.per_hour}
        onChange={e => onChange(value.map((row, i) => i === index
          ? { ...row, per_hour: Math.max(-50, Math.min(50, Math.trunc(Number(e.target.value) || 0))) } : row))} />
      <button type="button" className="ga-btn ga-btn-sm"
        onClick={() => onChange(value.filter((_, i) => i !== index))}>{t('Remove')}</button>
    </div>)}
    <button type="button" className="ga-btn ga-btn-sm" disabled={value.length >= 10}
      onClick={() => onChange([...value, { stat: keys[0] || '', per_hour: 0 }])}>{t('Add rate')}</button>
  </Field>
}
