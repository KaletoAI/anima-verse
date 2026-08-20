import { useState, type CSSProperties, type ReactNode } from 'react'

/**
 * A slider that can also be TYPED into.
 *
 * A bare `<input type="range">` can only be dragged, and dragging cannot hit
 * an exact number — a prop that has to stand at 2.35 m is unreachable with a
 * mouse. Every dial in the game admin therefore pairs the slider with a small
 * number field; both edit the same value, so whichever is more convenient
 * wins.
 *
 * The number field keeps a local DRAFT while it is being edited and commits
 * on Enter or blur (Escape reverts). Committing per keystroke — what the
 * hand-rolled pairs used to do — fights the typist: clearing the field to
 * type a new number reads as `''` and snaps the value to 0, and an
 * intermediate `"1."` or `"-"` is not a number at all. The draft holds the
 * raw text until it is a whole number again.
 *
 * The slider keeps committing live while dragging, which is what a slider is
 * for. Both paths go through the SAME `onChange`, so a call site that writes
 * to the server (debounced or not) behaves identically no matter which
 * control the user touched.
 *
 * Precision: `step` is the slider's granularity. `fineStep` (a number, or
 * `'any'`) lets the number field accept values BETWEEN the slider's stops —
 * useful for metre fields where the slider sweeps in centimetres but the
 * exact value is known. Committed values are rounded to the decimals implied
 * by the finer of the two, which reproduces the rounding the call sites did
 * by hand.
 *
 *   <SliderInput label="X" unit="m" min={0} max={lay.w} step={0.01}
 *     value={at[0]} onChange={(v) => setAt(0, v)} />
 *
 * `clearable` gives the field an empty state for dials whose "unset" is a
 * real value (a marker facing that means "face the neighbours"): clearing the
 * text and committing calls `onClear` instead of `onChange`.
 */
export interface SliderInputProps {
  /** Current value. `undefined` renders the number field empty and parks the slider on `fallback`. */
  value: number | undefined
  /** Commit of a real number — from the slider (live) or the number field (Enter/blur). */
  onChange: (v: number) => void
  /** Commit of the empty field. Needs `clearable`; without it an empty field reverts. */
  onClear?: () => void
  /** Where the slider sits while `value` is undefined. Default 0. */
  fallback?: number
  min: number
  max: number
  /** Slider granularity. Default 1. */
  step?: number
  /** Number-field granularity; `'any'` accepts anything. Default: `step`. */
  fineStep?: number | 'any'
  /** Round a committed value. Default: round to the decimals implied by step/fineStep. */
  round?: (v: number) => number
  /** Leading caption inside the label (text, an icon, an emoji). */
  label?: ReactNode
  /** Trailing unit shown after the number field, e.g. `"m"` or `"°"`. */
  unit?: ReactNode
  /** Extra readback after the unit, e.g. a compass letter or a derived length. */
  readback?: ReactNode
  /** Allow the number field to be emptied; pairs with `onClear`. */
  clearable?: boolean
  placeholder?: string
  title?: string
  disabled?: boolean
  /** Width of the range track. Default 100. */
  sliderWidth?: number | string
  /** Extra style for the range track, e.g. `{ flex: 1 }` in a stretching row. */
  sliderStyle?: CSSProperties
  /** Width of the number field. Default 72. */
  inputWidth?: number | string
  /** Accessible name for both controls when `label` is an icon. */
  ariaLabel?: string
  style?: CSSProperties
  className?: string
  /** Trailing extras inside the label, e.g. a reset button. */
  children?: ReactNode
}

/** Decimals a step implies: 0.01 -> 2, 0.5 -> 1, 1 -> 0. */
function decimalsOf(step: number): number {
  if (!Number.isFinite(step) || step <= 0) return 3
  const s = String(step)
  if (s.includes('e-')) return Math.min(6, parseInt(s.split('e-')[1], 10))
  const dot = s.indexOf('.')
  return dot < 0 ? 0 : Math.min(6, s.length - dot - 1)
}

const clampTo = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)

export function SliderInput({
  value,
  onChange,
  onClear,
  fallback = 0,
  min,
  max,
  step = 1,
  fineStep,
  round,
  label,
  unit,
  readback,
  clearable = false,
  placeholder,
  title,
  disabled = false,
  sliderWidth = 100,
  sliderStyle,
  inputWidth = 72,
  ariaLabel,
  style,
  className,
  children,
}: SliderInputProps) {
  // Non-null while the user is typing: the raw text, uncommitted. Null means
  // "show the value" — so a slider drag or an outside change is picked up
  // without an effect fighting the keyboard.
  const [draft, setDraft] = useState<string | null>(null)

  const numberStep = fineStep ?? step
  const decimals = numberStep === 'any'
    ? 6
    : Math.max(decimalsOf(step), decimalsOf(numberStep))
  const factor = 10 ** decimals
  const snap = round ?? ((v: number) => Math.round(v * factor) / factor)

  const shown = value ?? fallback
  // Display at FULL precision, only stripping float noise (0.30000000000000004).
  // Rendering `snap(value)` instead would hide the extra decimals of a value
  // that was placed by clicking rather than dialled — and, worse, offer that
  // shortened number back as the field's content.
  const text = value === undefined ? '' : String(Math.round(value * 1e6) / 1e6)

  const commit = (raw: string) => {
    setDraft(null)
    const trimmed = raw.trim()
    if (trimmed === '') {
      // Only a dial that HAS an unset state may be emptied; otherwise the
      // field snaps back to what it had.
      if (clearable && onClear) onClear()
      return
    }
    const n = parseFloat(trimmed)
    if (!Number.isFinite(n)) return
    const next = snap(clampTo(n, min, max))
    if (next !== value) onChange(next)
  }

  return (
    <label
      className={className}
      title={title}
      style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em', ...style }}
    >
      {label}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={shown}
        disabled={disabled}
        aria-label={ariaLabel}
        style={{ width: sliderWidth, minWidth: 0, ...sliderStyle }}
        onChange={(e) => {
          setDraft(null)
          const n = e.target.valueAsNumber
          if (Number.isFinite(n)) onChange(snap(clampTo(n, min, max)))
        }}
      />
      <input
        className="ga-input"
        type="number"
        min={min}
        max={max}
        step={numberStep}
        value={draft ?? text}
        placeholder={placeholder}
        disabled={disabled}
        aria-label={ariaLabel}
        style={{ width: inputWidth, flex: '0 0 auto' }}
        onChange={(e) => setDraft(e.target.value)}
        // Only an EDITED field commits. Focusing and leaving without typing
        // must not write anything back — re-committing the displayed number
        // would quietly re-round a value that carries more precision than the
        // step (a marker dropped by clicking the mesh, say).
        onBlur={(e) => { if (draft !== null) commit(e.target.value) }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            if (draft !== null) commit((e.target as HTMLInputElement).value)
          } else if (e.key === 'Escape') {
            e.preventDefault()
            setDraft(null)
          }
        }}
      />
      {unit ? <span style={{ opacity: 0.7 }}>{unit}</span> : null}
      {readback}
      {children}
    </label>
  )
}
