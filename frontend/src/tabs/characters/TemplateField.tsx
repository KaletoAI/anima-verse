/**
 * TemplateField — rendert EIN Character-Feld generisch nach seiner Template-
 * Definition (`type`/`options`/`source`/`allow_custom`/`multiline`/`readonly`).
 * Kein Hardcoding: alle Eigenschaften kommen aus dem Template-Feld.
 *
 * Wert wird über `onCommit(value)` zurückgegeben — bei Selects sofort, bei
 * Text/Zahl onBlur. `allow_custom` zeigt einen „Custom…"-Eintrag, der auf ein
 * Freitext-Feld umschaltet (wie die alte UI).
 */
import { useEffect, useState } from 'react'

export interface TmplFieldDef {
  [k: string]: unknown
  key: string
  type?: string
  options?: Array<string | { value?: string; id?: string; label?: string }>
  source?: string
  allow_custom?: boolean
  multiline?: boolean
  readonly?: boolean
  required?: boolean
  placeholder?: string
  placeholder_de?: string
  label?: string
  label_de?: string
  hint?: string
  hint_de?: string
  help?: string  // Topic-Key fuers kontextsensitive Help-Panel
  default?: unknown
  store?: string
  source_file?: string
  editor_visible?: boolean
  visible_when?: { field: string; values: unknown[] }
}

export type DynamicData = Record<string, Array<{ value: string; label: string }>>

function normOpts(
  raw: Array<string | { value?: string; id?: string; label?: string }> | undefined,
): Array<{ value: string; label: string }> {
  return (raw || []).map((o) =>
    typeof o === 'string'
      ? { value: o, label: o }
      : { value: String(o.value ?? o.id ?? ''), label: String(o.label ?? o.value ?? o.id ?? '') },
  )
}

export function tmplText(
  field: { [k: string]: unknown },
  key: 'label' | 'hint' | 'placeholder',
  lang: string,
): string {
  const de = field[`${key}_de`]
  if (lang === 'de' && typeof de === 'string' && de) return de
  const base = field[key]
  return typeof base === 'string' ? base : ''
}

export function TemplateField({
  field,
  value,
  dynamicData,
  disabled,
  lang,
  onCommit,
}: {
  field: TmplFieldDef
  value: unknown
  dynamicData: DynamicData
  disabled?: boolean
  lang: string
  onCommit: (value: string) => void
}) {
  const [local, setLocal] = useState(String(value ?? ''))
  useEffect(() => {
    setLocal(String(value ?? ''))
  }, [value])

  const type = field.type || 'text'
  const placeholder = tmplText(field, 'placeholder', lang)

  // Option-Quelle: dynamisch (source) oder statisch (options).
  const opts =
    type === 'character_select'
      ? dynamicData.characters || []
      : field.source
        ? dynamicData[field.source] || []
        : normOpts(field.options)
  const inOpts = opts.some((o) => o.value === local)

  // Custom-Modus: aktiver Freitext bei allow_custom (Wert nicht in Optionen).
  const [custom, setCustom] = useState<boolean>(!!field.allow_custom && local !== '' && !inOpts)
  useEffect(() => {
    if (field.allow_custom && local !== '' && !opts.some((o) => o.value === local)) setCustom(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  // ---- Text (mehrzeilig) ----
  if (type === 'text' && field.multiline) {
    return (
      <textarea
        className="ga-input"
        rows={Number(field.rows) > 0 ? Number(field.rows) : 3}
        value={local}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={() => {
          if (local !== String(value ?? '')) onCommit(local)
        }}
      />
    )
  }

  // ---- Zahl ----
  if (type === 'number') {
    return (
      <input
        className="ga-input"
        type="number"
        value={local}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={() => {
          if (local !== String(value ?? '')) onCommit(local)
        }}
      />
    )
  }

  // ---- Select / character_select ----
  if (type === 'select' || type === 'character_select') {
    if (field.allow_custom && custom) {
      return (
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            className="ga-input"
            type="text"
            value={local}
            placeholder={placeholder}
            disabled={disabled}
            style={{ flex: 1, minWidth: 0 }}
            onChange={(e) => setLocal(e.target.value)}
            onBlur={() => {
              if (local !== String(value ?? '')) onCommit(local)
            }}
          />
          <button
            type="button"
            className="ga-btn"
            title="Back to list"
            disabled={disabled}
            onClick={() => {
              setCustom(false)
              setLocal('')
              if (value) onCommit('')
            }}
          >
            ↩
          </button>
        </div>
      )
    }
    return (
      <select
        className="ga-input"
        value={local}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value
          if (v === '__custom__') {
            setCustom(true)
            setLocal('')
            return
          }
          setLocal(v)
          onCommit(v)
        }}
      >
        <option value="">— —</option>
        {/* Import-Wert erhalten, falls nicht in den Optionen */}
        {local && !inOpts ? <option value={local}>{local}</option> : null}
        {opts.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        {field.allow_custom ? <option value="__custom__">✏ Custom…</option> : null}
      </select>
    )
  }

  // ---- Text (einzeilig, Default) ----
  return (
    <input
      className="ga-input"
      type="text"
      value={local}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => setLocal(e.target.value)}
      onBlur={() => {
        if (local !== String(value ?? '')) onCommit(local)
      }}
    />
  )
}
