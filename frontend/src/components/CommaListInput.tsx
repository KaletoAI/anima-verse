/** A text input whose VALUE is a list of strings, spelled comma-separated.
 *
 * Why this exists: the obvious spelling round-trips the text through the list
 * on every keystroke —
 *
 *     value={items.join(', ')}
 *     onChange={(e) => set(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
 *
 * — and that input cannot be typed into. A comma makes `["a", ""]`, the empty
 * element is filtered away, the join gives back `"a"` and the comma is gone
 * before the next key arrives; the space after it is eaten by `trim` the same
 * way. Every dropped character also shortens the value, which sends the caret
 * to the end. The field reads as if it were stuttering and swallowing keys.
 *
 * So the raw TEXT is what the field shows while it is being edited, and it is
 * never written back from the list under the caret. The list is still reported
 * on EVERY keystroke, so a form that saves on a button click has the current
 * value whether or not the field lost focus first — nothing here depends on
 * blur. Leaving the field only tidies the text to its canonical spelling.
 * While the field is not focused the text follows the list from outside, so a
 * value changed elsewhere still shows up.
 */
import { useEffect, useRef, useState } from 'react'

/** The text spelling of the list, back to a list. Kept private:
 *  exporting it beside the component costs fast refresh. */
function splitList(text: string): string[] {
  return text.split(',').map((s) => s.trim()).filter(Boolean)
}

export function CommaListInput({
  value, onChange, className = 'ga-input', placeholder, id,
}: {
  value: string[]
  onChange: (next: string[]) => void
  className?: string
  placeholder?: string
  id?: string
}) {
  const [text, setText] = useState(() => value.join(', '))
  /** the last list this field itself put out — anything else is news */
  const reported = useRef<string[]>(value)

  // Follow the outside value only when the change did NOT come from here:
  // otherwise a half-written entry would be rewritten under the caret ("a, "
  // parses to ["a"], which joins back to "a" and eats the comma again). This
  // deliberately does not ask whether the field has focus, so switching to
  // another record refreshes the text even if the caret never left.
  useEffect(() => {
    const mine = reported.current
    const same = mine.length === value.length
      && mine.every((s, i) => s === value[i])
    if (!same) {
      reported.current = value
      setText(value.join(', '))
    }
  }, [value])

  const report = (raw: string) => {
    const next = splitList(raw)
    if (next.length !== value.length || next.some((s, i) => s !== value[i])) {
      reported.current = next
      onChange(next)
    }
  }

  return (
    <input
      id={id}
      className={className}
      placeholder={placeholder}
      value={text}
      onChange={(e) => {
        setText(e.target.value)
        report(e.target.value)
      }}
      onBlur={() => {
        // Tidy to the canonical spelling once the caret has left — "a,,b  ,"
        // becomes "a, b". The list itself was already reported.
        setText(splitList(text).join(', '))
      }}
    />
  )
}
