import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { getAt, type Json } from './schemaValues'

type Physics = Record<string, number | number[]>
type Group = { id: string; defaults: Physics }
const fields: Record<string, string> = {
  freq_hz: 'Frequency (Hz)', zeta: 'Damping ratio', gravity: 'Gravity', spill: 'Spill', gain: 'Gain',
  max_deg: 'Maximum dynamic angle (degrees)', rest_max_deg: 'Maximum rest angle (degrees)',
}

/** Package declarations supply the rows; only deviations are stored in the world. */
export function ExtensionMotion({ values, onChange }: {
  values: Json; onChange: (path: string, next: Json) => void
}) {
  const { t } = useI18n()
  const [groups, setGroups] = useState<Group[]>([])
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    let live = true
    apiGet<{ groups: Group[] }>('/admin/world-settings/extension-motion')
      .then(data => { if (live) { setGroups(data.groups); setLoaded(true) } })
      .catch(e => { if (live) setError(String(e)) })
    return () => { live = false }
  }, [])
  const overrides = (getAt(values, 'extension_motion.groups') ?? {}) as Record<string, Physics>
  const update = (id: string, key?: string, value?: number | number[]) => {
    const next = structuredClone(values) as Record<string, Json>
    const all = structuredClone(overrides)
    if (key === undefined) delete all[id]
    else {
      const row = { ...all[id] }
      const shipped = groups.find(group => group.id === id)!.defaults[key]
      if (JSON.stringify(shipped) === JSON.stringify(value)) delete row[key]
      else row[key] = value!
      if (Object.keys(row).length) all[id] = row
      else delete all[id]
    }
    next.extension_motion = { groups: all }
    onChange('extension_motion.groups', next)
  }
  if (error) return <div role="alert">{t('Failed to load')}: {error}</div>
  if (!loaded) return <div>{t('Loading…')}</div>
  return <div className="ga-form">
    <p>{t('Package defaults apply unless overridden in this world.')}</p>
    {!groups.length && <p>{t('No extension motion groups are loaded.')}</p>}
    {groups.map(group => {
      const effective = { ...group.defaults, ...overrides[group.id] }
      return <fieldset key={group.id}>
        <legend>{group.id}</legend>
        {Object.entries(fields).map(([key, label]) => <label key={key}>{t(label)}
          <input className="ga-input" type="number" step="any"
            min={0}
            max={(key === 'gain' || key === 'spill') ? 1 : key.endsWith('deg') ? 180 : undefined}
            value={effective[key] as number}
            onChange={e => {
              if (e.target.value && e.target.validity.valid && (key !== 'freq_hz' || Number(e.target.value) > 0))
                update(group.id, key, Number(e.target.value))
            }} />
        </label>)}
        {[0, 1].map(index => <label key={index}>{t(index === 0 ? 'Squash minimum' : 'Squash maximum')}
          <input className="ga-input" type="number" step="any" min={index === 0 ? 0.000001 : 1}
            max={index === 0 ? 1 : undefined} value={(effective.squash as number[])[index]}
            onChange={e => {
              if (!e.target.value || !e.target.validity.valid) return
              const squash = [...effective.squash as number[]]
              squash[index] = Number(e.target.value)
              update(group.id, 'squash', squash)
            }} />
        </label>)}
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => update(group.id)}>
          {t('Reset to package default')}
        </button>
      </fieldset>
    })}
  </div>
}
