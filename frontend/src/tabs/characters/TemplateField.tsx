/**
 * TemplateField — renders ONE character field generically from its template
 * definition (`type`/`options`/`source`/`allow_custom`/`multiline`/`readonly`).
 * No hardcoding: every property comes from the template field.
 *
 * The value is handed back via `onCommit(value)` — immediately for selects,
 * onBlur for text/number. `allow_custom` shows a "Custom…" entry that switches
 * to a free-text field (like the old UI).
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
  help?: string  // topic key for the context-sensitive help panel
  default?: unknown
  store?: string
  source_file?: string
  editor_visible?: boolean
  visible_when?: { field: string; values: unknown[] }
  /** This field is an INPUT the server derives other fields from, so saving it
   *  changes keys the form never sent (the temp-NPC lifetime recomputes
   *  `expires_at`). The renderers re-read the stores after such a save, or the
   *  readonly display right next to the control keeps showing the old value. */
  reload_after_save?: boolean
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

  // Option source: dynamic (source) or static (options).
  const opts =
    type === 'character_select'
      ? dynamicData.characters || []
      : field.source
        ? dynamicData[field.source] || []
        : normOpts(field.options)
  const inOpts = opts.some((o) => o.value === local)
  // An option source may bring its OWN empty entry when "not set" needs a
  // label (e.g. "Automatic (female)"). Then the built-in placeholder below
  // would render a second, unlabelled empty row.
  const hasEmptyOpt = opts.some((o) => o.value === '')

  // Custom mode: free text active for allow_custom (value not among options).
  const [custom, setCustom] = useState<boolean>(!!field.allow_custom && local !== '' && !inOpts)
  useEffect(() => {
    if (field.allow_custom && local !== '' && !opts.some((o) => o.value === local)) setCustom(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  // ---- Text (multiline) ----
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

  // ---- Number ----
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
        {hasEmptyOpt ? null : <option value="">— —</option>}
        {/* Keep an imported value that is not among the options */}
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

  // ---- Text (single line, default) ----
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
