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
 * - `tip`: the same help, but as a "ⓘ" glyph next to the caption instead of a
 *   paragraph under the control. Use it in crowded rows: a hint is laid out as
 *   content, so the longest help text — not the control — decides how wide the
 *   column gets, and eight helpful sentences squeeze eight inputs into slivers.
 * - `inline`: caption left, control right (for tight rows like checkboxes).
 * - `compact`: don't stretch this field to fill the row — use the control's
 *   own width. Useful for narrow number inputs or checkboxes inside a
 *   `.ga-form-row` where the rest of the fields share width equally.
 * - `help`: topic key for the context help panel — set as the active topic
 *   when a control inside this field gains focus.
 * - `promptContext`: marks the control as an image-PROMPT field and tells the
 *   Prompt Help what it is improving. Without it the assistant only sees a
 *   string and "improves" it into whatever an image prompt usually is — for a
 *   seamless tiling texture that means perspective and shadows, i.e. a worse
 *   result. One sentence here is the difference between help and harm.
 */
export function Field({
  label,
  hint,
  tip,
  inline,
  compact,
  help,
  promptContext,
  children,
}: {
  label: string
  hint?: ReactNode
  tip?: string
  inline?: boolean
  compact?: boolean
  help?: string
  promptContext?: string
  children: ReactNode
}) {
  const { setTopic } = useHelp()
  const cls = ['ga-field']
  if (inline) cls.push('ga-field-inline')
  if (compact) cls.push('ga-field-compact')
  return (
    <div className={cls.join(' ')}>
      <label className="ga-field-caption">
        {label}
        {tip ? (
          <span className="ga-field-tip" role="img" title={tip} aria-label={tip}>ⓘ</span>
        ) : null}
      </label>
      <div
        className="ga-field-control"
        data-help={help || undefined}
        data-prompt-context={promptContext || undefined}
        onFocusCapture={() => setTopic(help || null)}
      >{children}</div>
      {hint ? <div className="ga-field-hint">{hint}</div> : null}
    </div>
  )
}
