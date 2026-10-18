import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { draftChanged, draftOverrides, editDraft, makeDraft, validNumber, type Physics } from '../../lib/motionDraft'
import { MotionPreviewHint } from './MotionPreviewHint'

const fields: Record<string, string> = {
  length: 'Length factor (1 = as modelled)',
  girth: 'Diameter factor (1 = as modelled)',
  straighten_deg: 'Straightening rest angle (degrees, 0 = off)', freetext_clothing_gain: 'Free-text clothing gain',
  spill_max_deg: 'Maximum spill angle (degrees)', head_sag: 'Vertical static pull when not upright',
  freq_hz: 'Frequency (Hz)', zeta: 'Damping ratio', gravity: 'Gravity', gain: 'Gain',
  max_deg: 'Maximum dynamic angle (degrees)', sag_max_deg: 'Maximum static angle (degrees); for chains, bounds the whole chain static droop',
  translate: 'Translation fraction', flatten: 'Flatten', stretch: 'Stretch', spread: 'Spread', flatten_floor: 'Flatten floor', spill: 'Spill', rest_max_deg: 'Maximum rest angle (degrees)',
  axis_gain_lateral: 'Lateral gain', axis_gain_vertical: 'Vertical gain', axis_gain_longitudinal: 'Longitudinal gain',
  squash_min: 'Squash minimum', squash_max: 'Squash maximum',
}
const controlName = (key: string) => key.startsWith('axis_gain_') ? 'axis_gain' : key.startsWith('squash_') ? 'squash' : key

export function ExtensionMotionDraft({ defaults, overrides, controls, disabled, onSave }: {
  controls?: string[] | null
  defaults: Physics; overrides: Physics; disabled: boolean
  onSave: (overrides?: Physics) => Promise<boolean>
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(() => makeDraft({ ...defaults, ...overrides }))
  const valid = (key: string) => validNumber(draft.values[key] ?? '', ['length', 'girth'].includes(key) ? .5 : key === 'squash_max' ? 1 : 0,
    (key.startsWith('axis_gain_') || ['freetext_clothing_gain', 'gain', 'flatten', 'stretch', 'spread', 'flatten_floor', 'spill', 'translate', 'head_sag', 'squash_min'].includes(key)) ? 1 : key === 'girth' ? 2 : key === 'length' ? 3 : key.endsWith('deg') ? 180 : undefined,
    key === 'freq_hz' || key === 'squash_min')
  const changed = draftChanged(draft)
  const visibleFields = Object.entries(fields).filter(([key]) => controls == null || controls.includes(controlName(key)))
  const allValid = visibleFields.every(([key]) => valid(key))
    && ['bounce', 'weight'].every(key => validNumber(draft.values[key], 0.5, 1.5))
  const save = async (reset = false) => {
    if (!reset && (!changed || !allValid || disabled)) return
    const next = reset ? undefined : Object.fromEntries(Object.entries(draftOverrides(draft, defaults, overrides)).filter(([key]) => controls == null || controls.includes(key)))
    if (await onSave(next)) setDraft(makeDraft({ ...defaults, ...next }))
  }
  const content = <>
    {visibleFields.map(([key, label]) => <label key={key}>{t(label)} <MotionPreviewHint field={key.startsWith('axis_gain_') ? 'axis_gain' : key.startsWith('squash_') ? 'squash' : key} />
      <input className="ga-input" type="text" inputMode="decimal" disabled={disabled}
        value={draft.values[key] ?? ''} aria-invalid={!valid(key)}
        style={!valid(key) ? { borderColor: 'var(--ga-danger, #c44)' } : undefined}
        onChange={event => setDraft(previous => editDraft(previous, key, event.target.value))}
        onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void save() } }} />
      {!valid(key) && <span role="alert">{t('Enter a valid number within the allowed range.')}</span>}
    </label>)}
    {changed && <span className="ga-hint">{t('Unsaved changes')}</span>}
    <button type="button" className="ga-btn ga-btn-sm" disabled={disabled || !changed || !allValid} onClick={() => void save()}>{t('Save')}</button>
    <button type="button" className="ga-btn ga-btn-sm" disabled={disabled || !changed || !allValid} onClick={() => setDraft(makeDraft({ ...defaults, ...overrides }))}>{t('Revert')}</button>
    <button type="button" className="ga-btn ga-btn-sm" disabled={disabled} onClick={() => void save(true)}>{t('Reset')}</button>
  </>
  return controls == null ? <details><summary>{t('Advanced')}</summary>{content}</details> : content
}

/** Independent slider draft: saves only the two toolbar values. */
export function ExtensionMotionSliders({ overrides, controls, disabled, onPreview, onSave }: {
  controls?: string[] | null
  overrides: Physics; disabled: boolean
  onPreview: (values: Physics) => void
  onSave: (values: Physics) => Promise<boolean>
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(() => makeDraft({ bounce: overrides.bounce ?? 1, weight: overrides.weight ?? 1 }))
  const changed = draftChanged(draft)
  const current = changed ? draft : makeDraft({ bounce: overrides.bounce ?? 1, weight: overrides.weight ?? 1 })
  const sliders = ['bounce', 'weight'].filter(key => controls == null || controls.includes(key))
  const values = Object.fromEntries(sliders.map(key => [key, Number(current.values[key])]))
  const save = async () => {
    if (disabled || !changed) return
    if (await onSave(values)) setDraft(makeDraft(values))
  }
  return <>
    {sliders.map(key => <label key={key} className="ga-model3d-slider">
      <span className="ga-hint">{t(key === 'bounce' ? 'Bounce' : 'Weight')} <MotionPreviewHint field={key} /> · {Number(current.values[key]).toFixed(2)}</span>
      <input type="range" min={0.5} max={1.5} step={0.05} disabled={disabled}
        value={current.values[key]} onChange={event => {
          const next = editDraft(current, key, event.target.value)
          setDraft(next)
          onPreview(Object.fromEntries(sliders.map(field => [field, Number(next.values[field])])))
        }} />
    </label>)}
    <div className="ga-model3d-save">
      <button type="button" className="ga-btn ga-btn-sm ga-btn-primary" disabled={disabled || !changed} onClick={() => void save()}>{t('Save')}</button>
      <span className="ga-tag" aria-live="polite">{t(changed ? 'Unsaved changes' : 'Saved')}</span>
    </div>
  </>
}
