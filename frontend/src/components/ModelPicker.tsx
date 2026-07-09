import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'

/**
 * Searchable model combobox — replaces the plain <select> for long model
 * lists (World Dev model/validator, Animate suggest-LLM, …). Type to filter;
 * options are grouped (by provider) and may carry a sublabel (e.g. pricing).
 * Generic: each call site maps its models to `PickerOption[]`.
 */
export interface PickerOption {
  value: string
  label: string
  group?: string
  sublabel?: string
}

export function ModelPicker({
  options, value, onChange, placeholder, emptyLabel, title, className,
}: {
  options: PickerOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  /** Label for the "no selection" ('') entry — always offered at the top. */
  emptyLabel?: string
  title?: string
  className?: string
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const selected = useMemo(
    () => options.find((o) => o.value === value) || null,
    [options, value],
  )

  // Close on outside click.
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) =>
      o.label.toLowerCase().includes(q)
      || (o.group || '').toLowerCase().includes(q)
      || (o.sublabel || '').toLowerCase().includes(q),
    )
  }, [options, query])

  // Group filtered options by group, preserving first-seen group order.
  const groups = useMemo(() => {
    const map = new Map<string, PickerOption[]>()
    for (const o of filtered) {
      const g = o.group || ''
      const arr = map.get(g) || []
      arr.push(o)
      map.set(g, arr)
    }
    return Array.from(map.entries())
  }, [filtered])

  const pick = (v: string) => {
    onChange(v)
    setOpen(false)
    setQuery('')
  }

  return (
    <div ref={rootRef} className={className} style={{ position: 'relative' }}>
      <input
        ref={inputRef}
        className="ga-input"
        title={title}
        style={{ width: '100%', cursor: 'text' }}
        value={open ? query : (selected?.label ?? '')}
        placeholder={selected ? undefined : (placeholder || t('Pick model'))}
        onFocus={() => { setOpen(true); setQuery('') }}
        onChange={(e) => { setQuery(e.target.value); if (!open) setOpen(true) }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') { setOpen(false); inputRef.current?.blur() }
          if (e.key === 'Enter' && filtered.length > 0) { e.preventDefault(); pick(filtered[0].value) }
        }}
      />
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
          maxHeight: 320, overflowY: 'auto', marginTop: 2,
          background: 'var(--panel, #161b22)',
          border: '1px solid var(--border, #30363d)', borderRadius: 6,
          boxShadow: '0 6px 20px rgba(0,0,0,0.4)', fontSize: '0.9em',
        }}>
          {emptyLabel !== undefined && (
            <button type="button" className="ga-mp-opt"
              style={optStyle(value === '')} onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick('')}>
              <span style={{ opacity: 0.7 }}>— {emptyLabel} —</span>
            </button>
          )}
          {groups.length === 0 && (
            <div style={{ padding: '6px 10px', opacity: 0.6 }}>{t('No matches')}</div>
          )}
          {groups.map(([g, opts]) => (
            <div key={g || '_'}>
              {g && (
                <div style={{
                  padding: '3px 10px', fontSize: '0.78em', opacity: 0.55,
                  textTransform: 'uppercase', letterSpacing: 0.5,
                  position: 'sticky', top: 0, background: 'var(--panel, #161b22)',
                }}>{g}</div>
              )}
              {opts.map((o) => (
                <button type="button" key={o.value} className="ga-mp-opt"
                  style={optStyle(o.value === value)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => pick(o.value)}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {o.label}
                  </span>
                  {o.sublabel && (
                    <span style={{ flex: '0 0 auto', opacity: 0.55, marginLeft: 8, fontSize: '0.85em' }}>
                      {o.sublabel}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function optStyle(active: boolean): React.CSSProperties {
  return {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    width: '100%', textAlign: 'left', padding: '4px 10px', gap: 8,
    background: active ? 'rgba(120,170,255,0.16)' : 'transparent',
    border: 'none', color: 'inherit', cursor: 'pointer', minWidth: 0,
  }
}
