import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { useToast } from '../lib/Toast'

export interface ExportOption {
  key: string
  label: string
  default?: boolean
}

/**
 * Download-button for ZIP exports. If `options` is provided, opens a
 * small popover with checkboxes before the download starts and appends
 * the picked ones as `?key=true` query params.
 */
export function ExportButton({
  endpoint,
  filename,
  options,
  disabled,
  label,
  title,
}: {
  endpoint: string
  filename: string
  options?: ExportOption[]
  disabled?: boolean
  label?: string
  title?: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [opts, setOpts] = useState<Record<string, boolean>>(() =>
    Object.fromEntries((options || []).map((o) => [o.key, !!o.default])),
  )

  const doExport = async () => {
    setOpen(false)
    try {
      const qs = new URLSearchParams()
      for (const [k, v] of Object.entries(opts)) if (v) qs.set(k, 'true')
      const url = qs.toString() ? `${endpoint}?${qs}` : endpoint
      const res = await fetch(url, { credentials: 'same-origin' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const blob = await res.blob()
      const dl = document.createElement('a')
      dl.href = URL.createObjectURL(blob)
      dl.download = filename
      document.body.appendChild(dl)
      dl.click()
      dl.remove()
      URL.revokeObjectURL(dl.href)
      toast(t('Exported'))
    } catch (e) {
      toast(t('Export failed') + ': ' + (e as Error).message, 'error')
    }
  }

  const hasOptions = !!options && options.length > 0

  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <button
        className="ga-btn ga-btn-sm"
        disabled={disabled}
        title={title ?? t('Download as ZIP')}
        onClick={() => (hasOptions ? setOpen((o) => !o) : doExport())}
      >
        ↓ {label ?? t('Export')}
      </button>
      {open && hasOptions ? (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            right: 0,
            zIndex: 50,
            background: 'var(--bg-container, #161b22)',
            border: '1px solid var(--border, #30363d)',
            borderRadius: 6,
            padding: 10,
            minWidth: 220,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          }}
        >
          {options!.map((o) => (
            <label
              key={o.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 2px',
                fontSize: 12,
              }}
            >
              <input
                type="checkbox"
                checked={!!opts[o.key]}
                onChange={(e) => setOpts({ ...opts, [o.key]: e.target.checked })}
              />
              {o.label}
            </label>
          ))}
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <button className="ga-btn ga-btn-sm ga-btn-primary" onClick={doExport}>
              {t('Download')}
            </button>
            <button className="ga-btn ga-btn-sm" onClick={() => setOpen(false)}>
              {t('Cancel')}
            </button>
          </div>
        </div>
      ) : null}
    </span>
  )
}

/**
 * Publish-to-catalog button. Opens a small inline form that asks for the
 * target catalog + name + tags + description, then POSTs to /api/content/publish.
 * The backend clones the catalog's git repo, drops the ZIP, updates index.json,
 * and pushes — so this is a heavyweight call (network + git).
 */
export function PublishButton({
  packType,
  entityId,
  defaultName,
  label,
}: {
  packType: 'character' | 'item' | 'rule' | 'states' | 'location'
  entityId?: string
  defaultName?: string
  label?: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [catalogs, setCatalogs] = useState<{ id: string; name: string }[]>([])
  const [catalogId, setCatalogId] = useState<string>('')
  const [name, setName] = useState<string>(defaultName || entityId || '')
  const [tags, setTags] = useState<string>('')
  const [description, setDescription] = useState<string>('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    fetch('/api/content/catalogs', { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((d) => {
        const list = (d.catalogs || []) as { id: string; name: string }[]
        setCatalogs(list)
        if (list.length > 0 && !catalogId) setCatalogId(list[0].id)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (open && defaultName) setName(defaultName)
  }, [open, defaultName])

  const submit = async () => {
    if (!catalogId) {
      toast(t('Pick a catalog first'), 'error')
      return
    }
    if (!name.trim()) {
      toast(t('Name required'), 'error')
      return
    }
    setBusy(true)
    try {
      const res = await fetch('/api/content/publish', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          catalog_id: catalogId,
          pack_type: packType,
          entity_id: entityId || '',
          name,
          tags,
          description,
        }),
      })
      const result = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(result.detail || `HTTP ${res.status}`)
      }
      if (result.status === 'no_change') {
        toast(t('Already up to date in catalog'))
      } else {
        toast(t('Published as {id}').replace('{id}', result.pack_id || name))
      }
      setOpen(false)
      setTags('')
      setDescription('')
    } catch (e) {
      toast(t('Publish failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <button
        className="ga-btn ga-btn-sm"
        onClick={() => setOpen((o) => !o)}
        title={t('Publish to a marketplace catalog')}
      >
        ↑↑ {label ?? t('Publish')}
      </button>
      {open ? (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            right: 0,
            zIndex: 50,
            background: 'var(--bg-container, #161b22)',
            border: '1px solid var(--border, #30363d)',
            borderRadius: 6,
            padding: 12,
            minWidth: 280,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <label style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {t('Catalog')}
            <select
              className="ga-input"
              value={catalogId}
              onChange={(e) => setCatalogId(e.target.value)}
              disabled={busy || catalogs.length === 0}
            >
              {catalogs.length === 0 ? (
                <option value="">{t('No catalogs configured')}</option>
              ) : (
                catalogs.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))
              )}
            </select>
          </label>
          <label style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {t('Name')}
            <input
              className="ga-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
            />
          </label>
          <label style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {t('Tags')} <span style={{ color: '#8b949e', fontSize: 10 }}>{t('comma-separated')}</span>
            <input
              className="ga-input"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              disabled={busy}
              placeholder="business, outfit"
            />
          </label>
          <label style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {t('Description')}
            <textarea
              className="ga-input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={busy}
              rows={2}
            />
          </label>
          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <button
              className="ga-btn ga-btn-sm ga-btn-primary"
              onClick={submit}
              disabled={busy}
            >
              {busy ? t('Publishing…') : t('Publish')}
            </button>
            <button className="ga-btn ga-btn-sm" onClick={() => setOpen(false)} disabled={busy}>
              {t('Cancel')}
            </button>
          </div>
        </div>
      ) : null}
    </span>
  )
}

interface PreviewElement { kind: string; id: string; name: string; exists: boolean }
interface PreviewResult { type: string; multi: boolean; elements: PreviewElement[] }

/**
 * File-picker button for ZIP imports. Opens a generic preview dialog: every
 * importable element is listed with a checkbox, and elements that would
 * overwrite an existing one are flagged. Works for ALL export types via the
 * generic /api/content/preview + /api/content/import endpoints.
 *
 * `endpoint`/`overwriteSupported` are kept for API compatibility but no longer
 * used — the generic endpoints dispatch by the ZIP's manifest type.
 */
export function ImportButton({
  accept = '.zip',
  onImported,
  label,
  title,
}: {
  endpoint?: string
  accept?: string
  onImported?: (result: unknown) => void
  overwriteSupported?: boolean
  label?: string
  title?: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)

  const close = () => { setFile(null); setPreview(null); setPicked({}) }

  const onFile = async (f: File) => {
    setFile(f); setPreview(null); setLoading(true)
    try {
      const fd = new FormData(); fd.append('file', f)
      const res = await fetch('/api/content/preview', { method: 'POST', credentials: 'same-origin', body: fd })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
      const p = body as PreviewResult
      setPreview(p)
      setPicked(Object.fromEntries(p.elements.map((e) => [e.id, true])))
    } catch (e) {
      toast(t('Import failed') + ': ' + (e as Error).message, 'error')
      close()
    } finally {
      setLoading(false)
    }
  }

  const doImport = async () => {
    if (!file || !preview) return
    const selected = preview.elements.filter((e) => picked[e.id])
    const overwrite = selected.some((e) => e.exists)
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      // Only send selected_ids for multi-element bundles; single-element types
      // import as a whole.
      if (preview.multi) fd.append('selected_ids', selected.map((e) => e.id).join(','))
      fd.append('overwrite', overwrite ? 'true' : 'false')
      const res = await fetch('/api/content/import', { method: 'POST', credentials: 'same-origin', body: fd })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
      toast(t('Imported'))
      onImported?.(body)
      close()
    } catch (e) {
      toast(t('Import failed') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const selCount = preview ? preview.elements.filter((e) => picked[e.id]).length : 0
  const overwriteCount = preview ? preview.elements.filter((e) => picked[e.id] && e.exists).length : 0

  return (
    <>
      <button
        className="ga-btn ga-btn-sm"
        title={title ?? t('Upload a ZIP exported earlier')}
        onClick={() => fileRef.current?.click()}
      >
        ↑ {label ?? t('Import')}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0]
          e.target.value = ''
          if (f) onFile(f)
        }}
      />

      {(loading || preview) && (
        <div onClick={close} style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 1000,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div onClick={(e) => e.stopPropagation()} style={{
            background: 'var(--bg-container, #161b22)', border: '1px solid var(--border, #30363d)',
            borderRadius: 10, width: 'min(560px, 92vw)', maxHeight: '82vh',
            display: 'flex', flexDirection: 'column', overflow: 'hidden',
          }}>
            <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border, #30363d)',
                          display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <strong>{t('Import')}</strong>
              {preview ? <span style={{ opacity: 0.55, fontSize: '0.85em' }}>{preview.type}</span> : null}
            </div>

            <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '8px 14px' }}>
              {loading && <div className="ga-loading">{t('Loading…')}</div>}
              {preview && preview.elements.length === 0 && (
                <div className="ga-placeholder">{t('No importable elements in this file.')}</div>
              )}
              {preview && preview.elements.length > 0 && (
                <>
                  {preview.multi && (
                    <div style={{ display: 'flex', gap: 10, marginBottom: 8, fontSize: '0.8em' }}>
                      <button className="ga-btn ga-btn-sm"
                        onClick={() => setPicked(Object.fromEntries(preview.elements.map((e) => [e.id, true])))}>
                        {t('Select all')}
                      </button>
                      <button className="ga-btn ga-btn-sm"
                        onClick={() => setPicked({})}>
                        {t('Select none')}
                      </button>
                    </div>
                  )}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {preview.elements.map((el) => (
                      <label key={el.id} className="ga-form-check"
                        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 4px',
                                 borderRadius: 6, cursor: 'pointer' }}>
                        <input type="checkbox" checked={!!picked[el.id]}
                          onChange={(e) => setPicked((p) => ({ ...p, [el.id]: e.target.checked }))} />
                        <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {el.name}
                        </span>
                        <code style={{ opacity: 0.4, fontSize: '0.75em' }}>{el.kind}</code>
                        {el.exists && (
                          <span style={{ flex: '0 0 auto', color: '#e0a356', fontSize: '0.75em',
                                         border: '1px solid #e0a356', borderRadius: 8, padding: '0 6px' }}>
                            {t('will overwrite')}
                          </span>
                        )}
                      </label>
                    ))}
                  </div>
                </>
              )}
            </div>

            <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border, #30363d)',
                          display: 'flex', alignItems: 'center', gap: 10 }}>
              {preview && overwriteCount > 0 && (
                <span style={{ fontSize: '0.78em', color: '#e0a356' }}>
                  {t('{n} will be overwritten').replace('{n}', String(overwriteCount))}
                </span>
              )}
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                <button className="ga-btn ga-btn-sm" onClick={close} disabled={busy}>{t('Cancel')}</button>
                <button className="ga-btn ga-btn-sm ga-btn-primary" onClick={doImport}
                  disabled={busy || !preview || selCount === 0}>
                  {busy ? t('Importing…') : t('Import {n}').replace('{n}', String(selCount))}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
