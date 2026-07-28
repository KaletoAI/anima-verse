/**
 * FilterChipRow — the chip row the wardrobe and the item list filter with.
 *
 * It lived once in the character wardrobe (slots + outfit types) and the item
 * list had a plain <select> for slots instead, so the same job looked and
 * behaved differently depending on where you stood. One component now, used
 * by both — including the "all" chip, which is the state a filter starts in.
 */
import type { CSSProperties } from 'react'

export interface ChipOption {
  value: string
  label?: string
}

export function FilterChipRow({ allLabel, value, options, onChange, title }: {
  /** Label of the leading "no filter" chip. */
  allLabel: string
  value: string
  /** Plain strings, or {value,label} when the id is not what to show. */
  options: Array<string | ChipOption>
  onChange: (value: string) => void
  title?: string
}) {
  if (!options.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }} title={title}>
      <button type="button" onClick={() => onChange('')} style={chip(!value)}>
        {allLabel}
      </button>
      {options.map((opt) => {
        const v = typeof opt === 'string' ? opt : opt.value
        const label = typeof opt === 'string' ? opt : (opt.label || opt.value)
        return (
          <button key={v} type="button" onClick={() => onChange(v)}
            style={chip(value === v)}>
            {label}
          </button>
        )
      })}
    </div>
  )
}

function chip(active: boolean): CSSProperties {
  return {
    padding: '1px 7px', borderRadius: 11, cursor: 'pointer', fontSize: '0.72em',
    border: '1px solid ' + (active ? 'var(--accent,#6aa9ff)' : 'rgba(255,255,255,0.2)'),
    background: active ? 'rgba(120,170,255,0.25)' : 'transparent', color: 'inherit',
  }
}
