import type { ReactNode } from 'react'
import { useHelp } from '../help/HelpContext'

/**
 * Caption above a form field. Captions never end with a colon — the
 * separator is the line break, not punctuation.
 *
 *   <Field label="Storage">
 *     <select>...</select>
 *   </Field>
 *
 * - `hint`: small muted helper text below the control.
 * - `inline`: caption left, control right (for tight rows like checkboxes).
 * - `compact`: don't stretch this field to fill the row — use the control's
 *   own width. Useful for narrow number inputs or checkboxes inside a
 *   `.ga-form-row` where the rest of the fields share width equally.
 * - `help`: topic key for the context help panel — set as the active topic
 *   when a control inside this field gains focus.
 */
export function Field({
  label,
  hint,
  inline,
  compact,
  help,
  children,
}: {
  label: string
  hint?: ReactNode
  inline?: boolean
  compact?: boolean
  help?: string
  children: ReactNode
}) {
  const { setTopic } = useHelp()
  const cls = ['ga-field']
  if (inline) cls.push('ga-field-inline')
  if (compact) cls.push('ga-field-compact')
  return (
    <div className={cls.join(' ')}>
      <label className="ga-field-caption">{label}</label>
      <div
        className="ga-field-control"
        onFocusCapture={help ? () => setTopic(help) : undefined}
      >{children}</div>
      {hint ? <div className="ga-field-hint">{hint}</div> : null}
    </div>
  )
}
