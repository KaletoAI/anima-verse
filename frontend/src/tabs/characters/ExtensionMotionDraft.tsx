import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { draftChanged, draftOverrides, editDraft, makeDraft, validNumber, type Physics } from '../../lib/motionDraft'
import { MotionPreviewHint } from './MotionPreviewHint'

const fields: Record<string, string> = {
  freq_hz: 'Frequency (Hz)', zeta: 'Damping ratio', gravity: 'Gravity', gain: 'Gain',
  max_deg: 'Maximum dynamic angle (degrees)', sag_max_deg: 'Maximum static angle (degrees)',
  flatten: 'Flatten', spill: 'Spill', rest_max_deg: 'Maximum rest angle (degrees)',
  squash_min: 'Squash minimum', squash_max: 'Squash maximum',
}
export function ExtensionMotionDraft({ defaults, overrides, disabled, onSave }: {
  defaults: Physics; overrides: Physics; disabled: boolean
  onSave: (overrides?: Physics) => Promise<boolean>
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState(() => makeDraft({ ...defaults, ...overrides }))
  const valid = (key: string) => validNumber(draft.values[key] ?? '', key === 'squash_max' ? 1 : 0,
    ['gain', 'flatten', 'spill', 'squash_min'].includes(key) ? 1 : key.endsWith('deg') ? 180 : undefined,
    key === 'freq_hz' || key === 'squash_min')
  const changed = draftChanged(draft)
  const allValid = Object.keys(fields).every(valid)
  const save = async (reset = false) => {
    if (!reset && (!changed || !allValid || disabled)) return
    const next = reset ? undefined : draftOverrides(draft, defaults, overrides)
    if (await onSave(next)) setDraft(makeDraft({ ...defaults, ...next }))
  }
  return <>
    {Object.entries(fields).map(([key, label]) => <label key={key}>{t(label)} <MotionPreviewHint field={key.startsWith('squash_') ? 'squash' : key} />
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
}
