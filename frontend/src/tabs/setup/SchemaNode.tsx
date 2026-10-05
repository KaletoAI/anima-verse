import { useEffect, useState } from 'react'
import { Field } from '../../components/Field'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { deleteAt, getAt, originOf, setAt, type Json } from './schemaValues'

export type SchemaFieldDef = {
  type: string
  label?: string
  description?: string
  text?: string
  default?: Json
  min?: number
  max?: number
  step?: number
  choices?: (string | number)[]
  visible_when?: Record<string, Json>
  endpoint?: string
  method?: string
  body_from?: string[]
  confirm?: string
  preview_url?: string
  url?: string
  meta_url?: string
}
export type SchemaNodeDef = {
  label?: string
  description?: string
  fields?: Record<string, SchemaFieldDef>
  subsections?: Record<string, SchemaNodeDef>
  is_array?: boolean
  item_label_field?: string
}
export type SchemaProps = {
  node: SchemaNodeDef
  path: string
  values: Json
  shipped: Json
  overrides: string[]
  inListItem?: boolean
  onChange: (path: string, next: Json) => void
  onReset: (path: string) => void
}

export function Origin({ path, overrides, onReset }: Pick<SchemaProps, 'path' | 'overrides' | 'onReset'>) {
  const { t } = useI18n()
  const world = originOf(path, overrides) === 'world'
  return <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
    <span className="ga-badge">{world ? t('World') : t('Default')}</span>
    {world && <button type="button" className="ga-btn ga-btn-sm" onClick={() => onReset(path)}>{t('Reset to default')}</button>}
  </span>
}

function ImagePreview({ field, revision }: { field: SchemaFieldDef; revision: number }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [meta, setMeta] = useState<Json>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let alive = true
    setFailed(false)
    if (field.meta_url) apiGet<Json>(field.meta_url).then(data => { if (alive) setMeta(data) })
      .catch(error => { if (alive) toast(t('Error') + ': ' + (error as Error).message, 'error') })
    return () => { alive = false }
  }, [field.meta_url, revision, t, toast])
  return <Field label={field.label ?? ''} hint={field.description}>
    {failed ? <span>{t('Not generated yet')}</span> : <img style={{ maxWidth: '100%', maxHeight: 400 }}
      src={`${field.url}${field.url?.includes('?') ? '&' : '?'}_=${revision}`} alt={field.label ?? ''} onError={() => setFailed(true)} />}
    {meta !== null && <div className="ga-form-hint">{JSON.stringify(meta)}</div>}
  </Field>
}

export function SchemaField({ field, fieldKey, revision, refresh, ...props }: SchemaProps & {
  field: SchemaFieldDef; fieldKey: string; revision: number; refresh: (url?: string) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [confirm, setConfirm] = useState(false)
  const [running, setRunning] = useState(false)
  const path = `${props.path}.${fieldKey}`
  const value = getAt(props.values, path)
  const defaultValue = props.inListItem ? field.default : getAt(props.shipped, path) ?? field.default
  const change = (next: Json | undefined) => props.onChange(path,
    next === undefined ? deleteAt(props.values, path) : setAt(props.values, path, next))
  if (field.visible_when && !Object.entries(field.visible_when).every(([key, expected]) => {
    const sibling = getAt(props.values, `${props.path}.${key}`) ?? props.node.fields?.[key]?.default
    return Array.isArray(expected) ? expected.includes(sibling ?? null) : sibling === expected
  })) return null
  if (field.type === 'group_header') return <h3>{field.label}</h3>
  if (field.type === 'note') return <p className="ga-form-hint">{field.text ?? field.description}</p>
  if (field.type === 'image_preview') return <ImagePreview field={field} revision={revision} />
  const run = async () => {
    setConfirm(false)
    setRunning(true)
    try {
      const body: Record<string, Json> = {}
      for (const key of field.body_from ?? []) {
        const sibling = getAt(props.values, `${props.path}.${key}`) ?? props.node.fields?.[key]?.default
        if (sibling !== undefined) body[key] = sibling
      }
      const endpoint = field.endpoint!
      switch ((field.method ?? 'POST').toUpperCase()) {
        case 'GET': await apiGet(endpoint); break
        case 'PUT': await apiPut(endpoint, body); break
        case 'DELETE': await apiDelete(endpoint); break
        case 'POST': await apiPost(endpoint, body); break
        default: throw new Error(`Unsupported method: ${field.method}`)
      }
      refresh(field.preview_url)
    } catch (error) { toast(t('Error') + ': ' + (error as Error).message, 'error') }
    finally { setRunning(false) }
  }
  if (field.type === 'button') return <Field label={field.label ?? t('Run')} hint={field.description}>
    <button type="button" className="ga-btn" disabled={running} onClick={() => field.confirm ? setConfirm(true) : void run()}>{field.label ?? t('Run')}</button>
    <ConfirmDialog open={confirm} title={field.label ?? t('Run')} message={field.confirm ?? ''}
      confirmLabel={t('Run')} onConfirm={() => void run()} onClose={() => setConfirm(false)} />
  </Field>
  const scalarDefault = defaultValue !== undefined && defaultValue !== null && typeof defaultValue !== 'object'
    ? String(defaultValue) : ''
  const hint = <>{field.description}{scalarDefault.length > 0 && scalarDefault.length <= 80 &&
    <div>{t('Default')}: {scalarDefault}</div>}</>
  let control
  if (field.type === 'bool') control = <input type="checkbox" aria-label={field.label} checked={Boolean(value ?? defaultValue)} onChange={event => change(event.target.checked)} />
  else if (field.type === 'select') control = <select className="ga-input" aria-label={field.label} value={String(value ?? defaultValue ?? '')}
    onChange={event => change(field.choices?.find(choice => String(choice) === event.target.value) ?? event.target.value)}>
    {(field.choices ?? []).map(choice => <option key={choice} value={choice}>{choice}</option>)}
  </select>
  else if (field.type === 'text') control = <textarea className="ga-textarea" aria-label={field.label} rows={4} value={String(value ?? '')}
    placeholder={scalarDefault} onChange={event => change(event.target.value)} />
  else {
    const numeric = ['int', 'float', 'number'].includes(field.type)
    control = <input className="ga-input" aria-label={field.label} type={numeric ? 'number' : field.type === 'password' ? 'password' : 'text'}
      min={field.min} max={field.max} step={field.step ?? (field.type === 'int' ? 1 : numeric ? 'any' : undefined)}
      value={String(value ?? '')} placeholder={scalarDefault} onChange={event => change(numeric
        ? event.target.value === '' ? undefined : Number(event.target.value) : event.target.value)} />
  }
  return <Field label={field.label ?? fieldKey} hint={hint}>
    {!props.inListItem && <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
      <Origin path={path} overrides={props.overrides} onReset={props.onReset} />
    </div>}
    {control}
  </Field>
}

export function SchemaList(props: SchemaProps) {
  const { t } = useI18n()
  const raw = getAt(props.values, props.path)
  const items = Array.isArray(raw) ? raw : []
  const update = (next: Json[]) => props.onChange(props.path, setAt(props.values, props.path, next))
  const move = (index: number, delta: number) => {
    const next = [...items]
    ;[next[index], next[index + delta]] = [next[index + delta], next[index]]
    update(next)
  }
  return <div>
    <h3>{props.node.label} {!props.inListItem && <Origin {...props} />}</h3>
    {items.map((item, index) => <div className="ga-form" key={index} style={{ border: '1px solid var(--border)', padding: 12, marginBottom: 12 }}>
      <h4>{String(getAt(item, props.node.item_label_field ?? 'name') ?? index + 1)}</h4>
      <div className="ga-form-row">
        <button type="button" className="ga-btn ga-btn-sm" disabled={index === 0} onClick={() => move(index, -1)}>{t('Move up')}</button>
        <button type="button" className="ga-btn ga-btn-sm" disabled={index === items.length - 1} onClick={() => move(index, 1)}>{t('Move down')}</button>
        <button type="button" className="ga-btn ga-btn-sm" onClick={() => update(items.filter((_, i) => i !== index))}>{t('Remove')}</button>
      </div>
      <SchemaNode {...props} node={{ ...props.node, is_array: false }} path={`${props.path}.${index}`} inListItem />
    </div>)}
    <button type="button" className="ga-btn" onClick={() => {
      const item: Record<string, Json> = {}
      for (const [key, field] of Object.entries(props.node.fields ?? {})) if (field.default !== undefined) item[key] = structuredClone(field.default)
      update([...items, item])
    }}>{t('Add')}</button>
  </div>
}

export function SchemaNode(props: SchemaProps) {
  const [revisions, setRevisions] = useState<Record<string, number>>({})
  if (props.node.is_array) return <SchemaList {...props} />
  const refresh = (url?: string) => setRevisions(previous => {
    const next = { ...previous }
    for (const field of Object.values(props.node.fields ?? {})) {
      if (field.type === 'image_preview' && field.url && (!url || field.url === url)) next[field.url] = (next[field.url] ?? 0) + 1
    }
    return next
  })
  return <div className="ga-form">
    {Object.entries(props.node.fields ?? {}).map(([key, field]) => <SchemaField {...props} key={key} field={field} fieldKey={key}
      revision={revisions[field.url ?? ''] ?? 0} refresh={refresh} />)}
    {Object.entries(props.node.subsections ?? {}).map(([key, node]) => <section key={key} style={{ border: '1px solid var(--border)', padding: 12 }}>
      <h3>{node.label}</h3>{node.description && <p className="ga-form-hint">{node.description}</p>}
      <SchemaNode {...props} node={node} path={`${props.path}.${key}`} />
    </section>)}
  </div>
}
