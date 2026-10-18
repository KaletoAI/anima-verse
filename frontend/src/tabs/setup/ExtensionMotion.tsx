import { MotionNumberInput } from '../characters/MotionNumberInput'
import { MotionPreviewHint } from '../characters/MotionPreviewHint'
import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { getAt, type Json } from './schemaValues'

type Physics = Record<string, number | number[]>
type Group = { id: string; controls?: string[] | null; defaults: Physics }
const fields: Record<string, string> = {
  length: 'Length factor (1 = as modelled)',
  girth: 'Diameter factor (1 = as modelled)',
  straighten_deg: 'Straightening rest angle (degrees, 0 = off)', freetext_clothing_gain: 'Free-text clothing gain',
  spill_max_deg: 'Maximum spill angle (degrees)', head_sag: 'Vertical static pull when not upright',
  freq_hz: 'Frequency (Hz)', zeta: 'Damping ratio', gravity: 'Gravity', spill: 'Spill', translate: 'Translation fraction', flatten: 'Flatten', stretch: 'Stretch', spread: 'Spread', flatten_floor: 'Flatten floor', sag_max_deg: 'Maximum static angle (degrees)', gain: 'Gain',
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
    for (const group of groups) {
      if (group.controls != null && all[group.id]) {
        all[group.id] = Object.fromEntries(Object.entries(all[group.id]).filter(([field]) => group.controls!.includes(field)))
      }
    }
    next.extension_motion = { groups: all }
    onChange('extension_motion.groups', next)
  }
  if (error) return <div role="alert">{t('Failed to load')}: {error}</div>
  if (!loaded) return <div>{t('Loading…')}</div>
  return <div className="ga-form">
    <p className="ga-hint">{t('Changes are saved with Save at the top.')}</p>
    <p>{t('Package defaults apply unless overridden in this world.')}</p>
    {!groups.length && <p>{t('No extension motion groups are loaded.')}</p>}
    {groups.map(group => {
      const effective = { ...group.defaults, ...overrides[group.id] }
      return <fieldset key={group.id}>
        <legend>{group.id}</legend>
        {Object.entries(fields).filter(([key]) => group.controls == null || group.controls.includes(key)).map(([key, label]) => <label key={key}>{t(label)} <MotionPreviewHint field={key} />
          <MotionNumberInput value={effective[key] as number} min={['length', 'girth'].includes(key) ? .5 : 0} positive={key === 'freq_hz'}
            max={['freetext_clothing_gain', 'gain', 'spill', 'flatten', 'stretch', 'spread', 'flatten_floor', 'translate', 'head_sag'].includes(key) ? 1 : key === 'girth' ? 2 : key === 'length' ? 3 : key.endsWith('deg') ? 180 : undefined}
            onCommit={text => update(group.id, key, Number(text))} />
        </label>)}
        {(group.controls == null || group.controls.includes('axis_gain')) && ['Lateral gain', 'Vertical gain', 'Longitudinal gain'].map((label, index) => <label key={label}>{t(label)} <MotionPreviewHint field="axis_gain" />
          <MotionNumberInput value={(effective.axis_gain as number[])[index]} min={0} max={1}
            onCommit={text => {
              const axisGain = [...effective.axis_gain as number[]]
              axisGain[index] = Number(text)
              update(group.id, 'axis_gain', axisGain)
            }} />
        </label>)}
        {(group.controls == null || group.controls.includes('squash')) && [0, 1].map(index => <label key={index}>{t(index === 0 ? 'Squash minimum' : 'Squash maximum')} <MotionPreviewHint field="squash" />
          <MotionNumberInput value={(effective.squash as number[])[index]}
            min={index === 0 ? 0 : 1} positive={index === 0} max={index === 0 ? 1 : undefined}
            onCommit={text => {
              const squash = [...effective.squash as number[]]
              squash[index] = Number(text)
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
