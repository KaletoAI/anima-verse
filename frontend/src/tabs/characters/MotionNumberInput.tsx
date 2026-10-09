import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { validNumber } from '../../lib/motionDraft'

/** Keep intermediate text local; blur/Enter commits only valid numbers. */
export function MotionNumberInput({ value, min = 0, max, positive = false, optional = false, onCommit }: {
  value: number | ''; min?: number; max?: number; positive?: boolean; optional?: boolean
  onCommit: (value: string) => void
}) {
  const { t } = useI18n()
  const [editing, setEditing] = useState<string | null>(null)
  const text = editing ?? String(value)
  const valid = (optional && text === '') || validNumber(text, min, max, positive)
  const commit = () => {
    if (valid) onCommit(text)
    setEditing(null)
  }
  return <>
    <input className="ga-input" type="text" inputMode="decimal" value={text}
      aria-invalid={!valid} style={!valid ? { borderColor: 'var(--ga-danger, #c44)' } : undefined}
      placeholder={optional ? t('Unchanged') : undefined}
      onChange={event => setEditing(event.target.value)} onBlur={commit}
      onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); commit() } }} />
    {!valid && <span role="alert">{t('Enter a valid number within the allowed range.')}</span>}
  </>
}
