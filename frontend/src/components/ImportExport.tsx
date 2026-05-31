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

/**
 * File-picker button for ZIP imports. Posts the file as `multipart/form-data`
 * to `endpoint`. If the server returns 409 and `overwriteSupported` is set,
 * prompts the user and retries with `?overwrite=true`.
 */
export function ImportButton({
  endpoint,
  accept = '.zip',
  onImported,
  overwriteSupported,
  label,
  title,
}: {
  endpoint: string
  accept?: string
  onImported?: (result: unknown) => void
  overwriteSupported?: boolean
  label?: string
  title?: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const fileRef = useRef<HTMLInputElement | null>(null)

  const upload = async (file: File, overwrite = false) => {
    const url = overwrite ? `${endpoint}?overwrite=true` : endpoint
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        body: fd,
      })
      if (res.status === 409 && overwriteSupported && !overwrite) {
        const body = await res.json().catch(() => ({}))
        const msg = body.detail || t('Already exists — overwrite?')
        if (window.confirm(msg + '\n\n' + t('Overwrite?'))) {
          await upload(file, true)
        }
        return
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const result = await res.json().catch(() => ({}))
      toast(t('Imported'))
      onImported?.(result)
    } catch (e) {
      toast(t('Import failed') + ': ' + (e as Error).message, 'error')
    }
  }

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
          // Reset so picking the same file twice fires onChange again.
          e.target.value = ''
          if (f) upload(f)
        }}
      />
    </>
  )
}
