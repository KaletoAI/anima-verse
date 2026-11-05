import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { thumbUrl, thumbWidth } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

/**
 * Field controls of the package character panel (PackagePanel.tsx): the
 * renderer's whole vocabulary — text, textarea, int, bool, item, items,
 * condition, characters, backend, loras. Pickers show pictures and names,
 * never a bare id; an id the reference lists no longer know stays visible,
 * marked "(missing)", and is kept on save.
 */

export interface PanelField {
  key: string
  type: string
  label: string
  hint: string
  required: boolean
  min: number | null
  max: number | null
  unit: string
  filter: string
  placeholder: string
  /** Layout (presentation only): tab id, grid width, textarea height. */
  tab?: string
  width?: string
  rows?: number
  /** `loras` only: the backend field of the same card that scopes the list,
   *  its fallback when empty, and the render target of the list. */
  backend_field?: string
  fallback_field?: string
  target?: string
}

export interface LoraValue {
  name: string
  strength: number
}

export interface ItemOpt {
  id: string
  name?: string
  category?: string
  image?: string
  _shared?: boolean
  [key: string]: unknown
}
export interface ConditionOpt {
  name: string
  label?: string
  icon?: string
}
export interface CharacterOpt {
  name: string
  display_name?: string
  temporary?: boolean
}

export interface PanelRefs {
  items: ItemOpt[]
  conditions: ConditionOpt[]
  characters: CharacterOpt[]
  /** Image generator backend names (`backend` fields). */
  backends: string[]
}

const ITEM_PX = 52
const PORTRAIT_PX = 40

function itemName(it: ItemOpt | undefined, lang: string): string {
  if (!it) return ''
  const local = it[`name_${lang}`]
  return (typeof local === 'string' && local) || it.name || it.id
}

/** Item picture (thumbnail), or a neutral tile when there is none. */
export function ItemThumb({ item, size }: { item: ItemOpt | undefined; size: number }) {
  const [failed, setFailed] = useState(false)
  const src = item && item.image && !failed
    ? thumbUrl(`/inventory/items/${encodeURIComponent(item.id)}/image`, thumbWidth(size))
    : ''
  return (
    <span className="ga-pp-thumb" style={{ width: size, height: size, fontSize: Math.round(size * 0.45) }}>
      {src
        ? <img src={src} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
        : (item ? '◇' : '?')}
    </span>
  )
}

function Portrait({ name, size }: { name: string; size: number }) {
  const [failed, setFailed] = useState(false)
  return (
    <span className="ga-pp-thumb ga-pp-portrait" style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }}>
      {!failed
        ? <img src={thumbUrl(`/characters/${encodeURIComponent(name)}/images/profile`, thumbWidth(size))}
            alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
        : (name.slice(0, 1).toUpperCase() || '?')}
    </span>
  )
}

/** Modal item picker: search + thumbnail grid. `multi` toggles a set, else
 *  one click picks and closes. */
function ItemPickerDialog({
  title, items, selected, multi, allowNone, onPick, onClose,
}: {
  title: string
  items: ItemOpt[]
  selected: string[]
  multi: boolean
  allowNone: boolean
  onPick: (ids: string[]) => void
  onClose: () => void
}) {
  const { t, lang } = useI18n()
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<string[]>(selected)
  const searchRef = useRef<HTMLInputElement | null>(null)
  useEffect(() => { searchRef.current?.focus() }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = q
      ? items.filter((it) => itemName(it, lang).toLowerCase().includes(q) || it.id.toLowerCase().includes(q))
      : items
    return [...list].sort((a, b) => itemName(a, lang).localeCompare(itemName(b, lang)))
  }, [items, query, lang])

  const click = (id: string) => {
    if (!multi) { onPick([id]); return }
    setChosen((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div className="ga-modal" role="dialog" aria-label={title} style={{ maxWidth: 640 }}
        onClick={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          <input ref={searchRef} className="ga-input" placeholder={t('Search…')} value={query}
            onChange={(e) => setQuery(e.target.value)} />
          {shown.length === 0 ? (
            <div className="ga-placeholder">{t('No matches.')}</div>
          ) : (
            <div className="ga-pp-grid">
              {shown.map((it) => {
                const on = (multi ? chosen : selected).includes(it.id)
                return (
                  <button type="button" key={it.id} title={itemName(it, lang)}
                    className={'ga-pp-tile' + (on ? ' ga-pp-tile-on' : '')}
                    onClick={() => click(it.id)}>
                    <ItemThumb item={it} size={64} />
                    <span className="ga-pp-tile-name">{itemName(it, lang)}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
        <div className="ga-modal-footer">
          {!multi && allowNone && selected.length > 0 ? (
            <button type="button" className="ga-btn ga-btn-sm" style={{ marginRight: 'auto' }}
              onClick={() => onPick([])}>{t('Clear')}</button>
          ) : null}
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>{t('Cancel')}</button>
          {multi ? (
            <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
              onClick={() => onPick(chosen)}>{t('Done')}</button>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}

function asList(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)).filter(Boolean) : []
}

function asLoras(v: unknown): LoraValue[] {
  if (!Array.isArray(v)) return []
  return v
    .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object')
    .map((x) => ({ name: String(x.name ?? ''), strength: Number(x.strength ?? 1) }))
    .filter((x) => x.name)
}

/** LoRA list of a panel field: rows (name, strength, remove) plus an add
 *  row. The options are the LoRA library scoped to `backend` (the draft value
 *  of the card's backend field; "" = the character's routed backend) and are
 *  fetched again when it changes. Same behaviour as the LoRA lists of
 *  ImageOverrides.tsx, compact. */
function LoraControl({
  value, onChange, character, backend, target,
}: {
  value: unknown
  onChange: (v: unknown) => void
  character: string
  backend: string
  target: string
}) {
  const { t } = useI18n()
  const list = asLoras(value)
  const [options, setOptions] = useState<Array<{ name: string; missing?: boolean }>>([])
  const [add, setAdd] = useState('')
  useEffect(() => {
    let cancelled = false
    const q = `?character_name=${encodeURIComponent(character)}&target=${encodeURIComponent(target)}`
      + `&backend=${encodeURIComponent(backend)}`
    // Short delay: a fallback field may be a typed glob — one request per pause, not per key.
    const timer = window.setTimeout(() => {
      apiGet<{ loras?: Array<{ name: string; missing?: boolean }> }>(`/characters/outfit-lora-options${q}`)
        .then((d) => { if (!cancelled) setOptions((d.loras || []).filter((l) => l.name && l.name !== 'None')) })
        .catch(() => { if (!cancelled) setOptions([]) })
    }, 250)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [character, target, backend])
  const known = new Set(options.map((o) => o.name))
  const addable = options.filter((o) => !list.some((x) => x.name === o.name))

  return (
    <div className="ga-pp-loras">
      {list.length === 0 ? <span className="ga-pp-muted">{t('No LoRAs.')}</span> : null}
      {list.map((l, i) => (
        <div key={l.name} className="ga-pp-lora">
          <span className={'ga-pp-lora-name' + (known.has(l.name) ? '' : ' ga-pp-missing')} title={l.name}>
            {l.name}{known.has(l.name) ? '' : ' ' + t('(missing)')}
          </span>
          <input className="ga-input" type="number" step={0.05} min={-4} max={4} title={t('Strength')}
            value={l.strength}
            onChange={(e) => {
              const strength = parseFloat(e.target.value)
              onChange(list.map((x, j) => (j === i ? { ...x, strength: isNaN(strength) ? 1 : strength } : x)))
            }} />
          <button type="button" className="ga-btn ga-btn-sm" title={t('Remove')}
            onClick={() => onChange(list.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <div className="ga-pp-lora ga-pp-lora-add">
        <select className="ga-input" value={add} onChange={(e) => setAdd(e.target.value)}>
          <option value="">— {t('pick a LoRA')} —</option>
          {addable.map((o) => (
            <option key={o.name} value={o.name}>{o.name}{o.missing ? ` ${t('(missing)')}` : ''}</option>
          ))}
        </select>
        <button type="button" className="ga-btn ga-btn-sm" disabled={!add}
          onClick={() => {
            if (!add) return
            onChange([...list, { name: add, strength: 1 }])
            setAdd('')
          }}>{t('Add LoRA')}</button>
      </div>
    </div>
  )
}

/** The control of one field. `value` is the draft value; `onChange` the
 *  local edit (saving is the card's Save button). */
export function PanelFieldControl({
  field, value, onChange, refs, character, draft,
}: {
  field: PanelField
  value: unknown
  onChange: (v: unknown) => void
  refs: PanelRefs
  character: string
  /** The whole card draft — a `loras` field reads its backend field from it. */
  draft: Record<string, unknown>
}) {
  const { t, lang } = useI18n()
  const [picking, setPicking] = useState(false)
  const itemsById = useMemo(() => {
    const m: Record<string, ItemOpt> = {}
    for (const it of refs.items) m[it.id] = it
    return m
  }, [refs.items])
  const pickable = useMemo(
    () => (field.filter === 'outfit'
      ? refs.items.filter((it) => it.category === 'outfit_piece')
      : refs.items),
    [field.filter, refs.items],
  )

  switch (field.type) {
    case 'textarea':
      return (
        <textarea className="ga-textarea" rows={field.rows && field.rows > 0 ? field.rows : 3}
          placeholder={field.placeholder || undefined}
          value={value == null ? '' : String(value)} onChange={(e) => onChange(e.target.value)} />
      )
    case 'int':
      return (
        <span className="ga-pp-inline">
          <input className="ga-input" type="number" step={1} style={{ width: 90 }}
            min={field.min ?? undefined} max={field.max ?? undefined}
            value={value == null ? '' : String(value)}
            onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
          {field.unit ? <span className="ga-pp-muted">{field.unit}</span> : null}
        </span>
      )
    case 'bool':
      return (
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
      )
    case 'condition': {
      const cur = value == null ? '' : String(value)
      const known = refs.conditions.some((c) => c.name === cur)
      return (
        <select className="ga-input" value={cur} onChange={(e) => onChange(e.target.value)}>
          <option value="">{t('— none —')}</option>
          {refs.conditions.map((c) => (
            <option key={c.name} value={c.name}>
              {(c.icon ? c.icon + ' ' : '') + (c.label || c.name)}
            </option>
          ))}
          {cur && !known ? <option value={cur}>{cur + ' ' + t('(missing)')}</option> : null}
        </select>
      )
    }
    case 'backend': {
      const cur = value == null ? '' : String(value)
      return (
        <select className="ga-input" value={cur} onChange={(e) => onChange(e.target.value)}>
          <option value="">{t('— default —')}</option>
          {refs.backends.map((b) => <option key={b} value={b}>{b}</option>)}
          {cur && !refs.backends.includes(cur) ? <option value={cur}>{cur + ' ' + t('(missing)')}</option> : null}
        </select>
      )
    }
    case 'loras': {
      const pick = (key?: string) => (key && draft[key] != null ? String(draft[key]).trim() : '')
      const backend = pick(field.backend_field) || pick(field.fallback_field)
      return (
        <LoraControl value={value} onChange={onChange} character={character}
          backend={backend} target={field.target === 'tpose' ? 'tpose' : 'render'} />
      )
    }
    case 'item': {
      const cur = value == null ? '' : String(value)
      const it = cur ? itemsById[cur] : undefined
      return (
        <>
          <button type="button" className="ga-pp-pick" onClick={() => setPicking(true)}
            title={cur ? cur : undefined}>
            {cur ? <ItemThumb item={it} size={36} /> : null}
            <span className={cur && !it ? 'ga-pp-missing' : ''}>
              {cur ? (it ? itemName(it, lang) : cur + ' ' + t('(missing)')) : t('Choose item…')}
            </span>
            <span className="ga-pp-muted">▾</span>
          </button>
          {picking ? (
            <ItemPickerDialog title={field.label} items={pickable} selected={cur ? [cur] : []}
              multi={false} allowNone={!field.required}
              onPick={(ids) => { onChange(ids[0] || ''); setPicking(false) }}
              onClose={() => setPicking(false)} />
          ) : null}
        </>
      )
    }
    case 'items': {
      const cur = asList(value)
      return (
        <>
          <div className="ga-pp-wrap">
            {cur.map((id) => {
              const it = itemsById[id]
              return (
                <span key={id} className="ga-pp-chip" title={it ? itemName(it, lang) : id}>
                  <ItemThumb item={it} size={ITEM_PX} />
                  <span className={'ga-pp-tile-name' + (it ? '' : ' ga-pp-missing')}>
                    {it ? itemName(it, lang) : t('(missing)')}
                  </span>
                  <button type="button" className="ga-pp-x" title={t('Remove')}
                    onClick={() => onChange(cur.filter((x) => x !== id))}>×</button>
                </span>
              )
            })}
            <button type="button" className="ga-pp-chip ga-pp-add" onClick={() => setPicking(true)}>
              <span className="ga-pp-thumb" style={{ width: ITEM_PX, height: ITEM_PX, fontSize: 22 }}>+</span>
              <span className="ga-pp-tile-name">{t('Add')}</span>
            </button>
          </div>
          {picking ? (
            <ItemPickerDialog title={field.label} items={pickable} selected={cur} multi allowNone
              onPick={(ids) => {
                // Keep ids the library no longer knows — they are only shown
                // as "(missing)", never dropped behind the user's back.
                const missing = cur.filter((id) => !itemsById[id])
                onChange([...missing, ...ids.filter((id) => !missing.includes(id))])
                setPicking(false)
              }}
              onClose={() => setPicking(false)} />
          ) : null}
        </>
      )
    }
    case 'characters': {
      const cur = asList(value)
      const own = character.toLowerCase()
      const roster = refs.characters
        .filter((c) => c.name.toLowerCase() !== own)
        .sort((a, b) => Number(!!a.temporary) - Number(!!b.temporary)
          || (a.display_name || a.name).localeCompare(b.display_name || b.name))
      const names = new Set(roster.map((c) => c.name))
      const missing = cur.filter((n) => !names.has(n))
      const toggle = (n: string) =>
        onChange(cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n])
      if (!roster.length && !missing.length) {
        return <span className="ga-pp-muted">{t('No other characters.')}</span>
      }
      return (
        <div className="ga-pp-wrap">
          {roster.map((c) => (
            <label key={c.name} className={'ga-pp-person' + (cur.includes(c.name) ? ' ga-pp-person-on' : '')}>
              <input type="checkbox" checked={cur.includes(c.name)} onChange={() => toggle(c.name)} />
              <Portrait name={c.name} size={PORTRAIT_PX} />
              <span>{c.display_name || c.name}</span>
            </label>
          ))}
          {missing.map((n) => (
            <label key={n} className="ga-pp-person ga-pp-person-on">
              <input type="checkbox" checked onChange={() => toggle(n)} />
              <span className="ga-pp-missing">{n + ' ' + t('(missing)')}</span>
            </label>
          ))}
        </div>
      )
    }
    default:
      return (
        <input className="ga-input" type="text" placeholder={field.placeholder || undefined}
          value={value == null ? '' : String(value)} onChange={(e) => onChange(e.target.value)} />
      )
  }
}
