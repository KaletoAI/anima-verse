import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'
import { downloadBlob } from '../lib/download'
import { useToast } from '../lib/Toast'
import { summarizeImport, type ImportResult } from '../lib/importNotes'
import { formatBytes } from '../lib/formatBytes'
import { PackFacts, type PackFactsMap } from '../lib/PackFacts'

export interface ExportOption {
  key: string
  label: string
  default?: boolean
}

/**
 * A small popover that hangs below its anchor button but lives in a portal on
 * `document.body` — an `overflow:hidden/auto` ancestor (every scrolling tab
 * panel here) would otherwise clip it away. Position is `fixed` and derived
 * from the anchor's rect, recomputed on resize/scroll; the box is flipped
 * above the anchor when it would not fit below and clamped into the viewport.
 * Closes on Escape and on a click outside anchor + popover.
 */
function AnchoredPopover({
  anchorRef,
  onClose,
  minWidth,
  padding,
  children,
}: {
  anchorRef: RefObject<HTMLElement | null>
  onClose: () => void
  minWidth: number
  padding: number
  children: ReactNode
}) {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    const place = () => {
      const anchor = anchorRef.current
      const box = boxRef.current
      if (!anchor) return
      const r = anchor.getBoundingClientRect()
      const w = box?.offsetWidth || minWidth
      const h = box?.offsetHeight || 0
      // Right-aligned with the anchor, as the absolute version was.
      const maxLeft = Math.max(8, window.innerWidth - w - 8)
      const left = Math.min(Math.max(8, r.right - w), maxLeft)
      let top = r.bottom + 4
      if (h > 0 && top + h + 8 > window.innerHeight) {
        top = Math.max(8, r.top - 4 - h)
      }
      setPos({ top, left })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    // Content that arrives later (a fetched preview) grows the box — place
    // it again, or it overflows the viewport near the bottom.
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(place) : null
    if (observer && boxRef.current) observer.observe(boxRef.current)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
      observer?.disconnect()
    }
  }, [anchorRef, minWidth])

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node | null
      if (!target) return
      // Clicks inside the portaled box or on the anchor (which toggles itself)
      // are not "outside".
      if (boxRef.current?.contains(target)) return
      if (anchorRef.current?.contains(target)) return
      onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [anchorRef, onClose])

  return createPortal(
    <div
      ref={boxRef}
      style={{
        position: 'fixed',
        top: pos?.top ?? -9999,
        left: pos?.left ?? -9999,
        visibility: pos ? 'visible' : 'hidden',
        zIndex: 1100,
        background: 'var(--bg-container, #161b22)',
        border: '1px solid var(--border, #30363d)',
        borderRadius: 6,
        padding,
        minWidth,
        maxHeight: 'calc(100vh - 16px)',
        overflowY: 'auto',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
      }}
    >
      {children}
    </div>,
    document.body,
  )
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
  const btnRef = useRef<HTMLButtonElement | null>(null)
  const close = useCallback(() => setOpen(false), [])
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
      downloadBlob(await res.blob(), filename)
      toast(t('Exported'))
    } catch (e) {
      toast(t('Export failed') + ': ' + (e as Error).message, 'error')
    }
  }

  const hasOptions = !!options && options.length > 0

  return (
    <span style={{ display: 'inline-block' }}>
      <button
        ref={btnRef}
        className="ga-btn ga-btn-sm"
        disabled={disabled}
        title={title ?? t('Download as ZIP')}
        onClick={() => (hasOptions ? setOpen((o) => !o) : doExport())}
      >
        ↓ {label ?? t('Export')}
      </button>
      {open && hasOptions ? (
        <AnchoredPopover anchorRef={btnRef} onClose={close} minWidth={220} padding={10}>
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
            <button className="ga-btn ga-btn-sm" onClick={close}>
              {t('Cancel')}
            </button>
          </div>
        </AnchoredPopover>
      ) : null}
    </span>
  )
}

interface PublishInspect {
  pack_id: string
  slug: string
  size_bytes: number
  warnings: string[]
  facts: PackFactsMap
  fact_labels: Record<string, string>
  thumbnail: string
}

/**
 * Publish-to-catalog button. Opens a small inline form that asks for the
 * target catalog + name + tags + description and shows what would go up
 * (POST /api/content/publish/inspect: thumbnail, size, facts, warnings), then
 * POSTs to /api/content/publish. The backend uploads the ZIP (and thumbnail)
 * as release assets of the catalog repository and rewrites that type's index
 * — a network call that can take a while for a large pack.
 */
export function PublishButton({
  packType,
  entityId,
  defaultName,
  label,
}: {
  packType: 'character' | 'item' | 'rule' | 'states' | 'location' | 'prop'
  entityId?: string
  defaultName?: string
  label?: string
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [catalogs, setCatalogs] = useState<{ id: string; name: string; host_limit: number }[]>([])
  const [catalogsLoaded, setCatalogsLoaded] = useState(false)
  const [catalogId, setCatalogId] = useState<string>('')
  const [name, setName] = useState<string>(defaultName || entityId || '')
  const [tags, setTags] = useState<string>('')
  const [description, setDescription] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [inspect, setInspect] = useState<PublishInspect | null>(null)
  const [inspectError, setInspectError] = useState('')
  const btnRef = useRef<HTMLButtonElement | null>(null)
  const close = useCallback(() => setOpen(false), [])
  const hostLimit = catalogs.find((c) => c.id === catalogId)?.host_limit || 0

  // What would be published — built ONCE per opening (a full export on the
  // server), after the catalog list is in; the host's per-file limit comes
  // with that list, so switching catalogs needs no second export. `name`
  // only names a pack without an entity id (states), hence not a dependency.
  useEffect(() => {
    if (!open || !catalogsLoaded) return
    let cancelled = false
    setInspect(null)
    setInspectError('')
    fetch('/api/content/publish/inspect', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pack_type: packType, entity_id: entityId || '', name }),
    })
      .then(async (r) => {
        const d = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`)
        return d as PublishInspect
      })
      .then((d) => { if (!cancelled) setInspect(d) })
      .catch((e) => { if (!cancelled) setInspectError((e as Error).message) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, catalogsLoaded, packType, entityId])

  useEffect(() => {
    if (!open) return
    fetch('/api/content/catalogs', { credentials: 'same-origin' })
      .then((r) => r.json())
      .then((d) => {
        const list = (d.catalogs || []) as { id: string; name: string; host_limit: number }[]
        setCatalogs(list)
        if (list.length > 0 && !catalogId) setCatalogId(list[0].id)
      })
      .catch(() => {})
      .finally(() => setCatalogsLoaded(true))
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
      // ONE toast: the toast area holds a single message, so warnings ride
      // along with the outcome instead of replacing it.
      const warnings = (result.warnings || []) as string[]
      const outcome = result.status === 'no_change'
        ? t('Already up to date in catalog')
        : t('Published as {id}').replace('{id}', result.pack_id || name)
      toast([outcome, ...warnings].join(' — '), warnings.length ? 'info' : 'success')
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
    <span style={{ display: 'inline-block' }}>
      <button
        ref={btnRef}
        className="ga-btn ga-btn-sm"
        onClick={() => setOpen((o) => !o)}
        title={t('Publish to a marketplace catalog')}
      >
        ↑↑ {label ?? t('Publish')}
      </button>
      {open ? (
        <AnchoredPopover anchorRef={btnRef} onClose={close} minWidth={280} padding={12}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 340 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              {inspect?.thumbnail ? (
                <img src={inspect.thumbnail} alt=""
                  style={{ width: 72, height: 72, objectFit: 'contain', borderRadius: 4, background: '#0d1117' }} />
              ) : null}
              <div style={{ fontSize: 12, minWidth: 0 }}>
                {inspect ? (
                  <>
                    <div style={{ color: '#8b949e' }}>
                      {inspect.pack_id} · {formatBytes(inspect.size_bytes)}
                    </div>
                    <PackFacts facts={inspect.facts} labels={inspect.fact_labels} />
                  </>
                ) : inspectError ? (
                  <div style={{ color: '#f85149' }}>{inspectError}</div>
                ) : (
                  <div style={{ color: '#8b949e' }}>{t('Checking pack…')}</div>
                )}
              </div>
            </div>
            {[...(inspect?.warnings || []),
              ...(inspect && hostLimit && inspect.size_bytes > hostLimit
                ? [t("Over the catalog host's per-file limit ({mb} MB) — the publish will be refused.")
                    .replace('{mb}', String(Math.floor(hostLimit / (1024 * 1024))))]
                : [])].map((w) => (
              <div key={w} style={{ fontSize: 11, color: '#d29922' }}>⚠ {w}</div>
            ))}
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
              <button className="ga-btn ga-btn-sm" onClick={close} disabled={busy}>
                {t('Cancel')}
              </button>
            </div>
          </div>
        </AnchoredPopover>
      ) : null}
    </span>
  )
}

interface BulkJob {
  id: string
  status: 'running' | 'done' | 'error'
  total: number
  done: number
  error: string
  items: { entity_id: string; status: string; pack_id: string; error: string; warnings: string[] }[]
}

/**
 * Publish MANY entities at once — each as its own pack, named after itself
 * (POST /api/content/publish/bulk). The server works in the background; this
 * polls the job and shows the progress, then sums the outcome up.
 */
export function BulkPublishButton({
  packType,
  entityIds,
  onDone,
  onRunningChange,
}: {
  packType: 'prop'
  entityIds: string[]
  onDone?: () => void
  /** Told when a job starts and ends — the host must keep this button
   *  mounted meanwhile, or the progress and the summary are lost. */
  onRunningChange?: (running: boolean) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [catalogs, setCatalogs] = useState<{ id: string; name: string }[]>([])
  const [catalogId, setCatalogId] = useState('')
  const [tags, setTags] = useState('')
  const [job, setJob] = useState<BulkJob | null>(null)
  const btnRef = useRef<HTMLButtonElement | null>(null)
  const running = job?.status === 'running'
  const close = useCallback(() => { if (!running) setOpen(false) }, [running])
  // The poller reads these through refs, so a new callback identity does not
  // restart the interval.
  const doneRef = useRef(onDone)
  doneRef.current = onDone
  const runningRef = useRef(onRunningChange)
  runningRef.current = onRunningChange
  useEffect(() => { runningRef.current?.(running) }, [running])

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

  // Poll the running job; sum it up once it ends.
  const jobId = job?.id
  useEffect(() => {
    if (!jobId || !running) return
    const timer = setInterval(async () => {
      try {
        const r = await fetch(`/api/content/publish/jobs/${encodeURIComponent(jobId)}`,
          { credentials: 'same-origin' })
        const d = (await r.json()) as BulkJob
        if (!r.ok) return
        setJob(d)
        if (d.status !== 'running') {
          const count = (s: string) => d.items.filter((i) => i.status === s).length
          toast(t('Published {ok}, unchanged {same}, failed {bad}')
            .replace('{ok}', String(count('success')))
            .replace('{same}', String(count('no_change')))
            .replace('{bad}', String(count('error') + count('skipped'))),
          d.status === 'done' && !count('error') ? 'success' : 'error')
          doneRef.current?.()
        }
      } catch {
        // a missed poll is retried on the next tick
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [jobId, running, t, toast])

  const start = async () => {
    try {
      const res = await fetch('/api/content/publish/bulk', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ catalog_id: catalogId, pack_type: packType, entity_ids: entityIds, tags }),
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`)
      setJob(d as BulkJob)
    } catch (e) {
      toast(t('Publish failed') + ': ' + (e as Error).message, 'error')
    }
  }

  const failures = (job?.items || []).filter((i) => i.status === 'error' || i.status === 'skipped')
  return (
    <span style={{ display: 'inline-block' }}>
      <button ref={btnRef} className="ga-btn ga-btn-sm" disabled={entityIds.length === 0 && !running}
        onClick={() => setOpen((o) => (running ? true : !o))}
        title={t('Publish every selected entry as its own pack')}>
        ↑↑ {t('Publish selected')} ({entityIds.length})
      </button>
      {open ? (
        <AnchoredPopover anchorRef={btnRef} onClose={close} minWidth={300} padding={12}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 360 }}>
            <label style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {t('Catalog')}
              <select className="ga-input" value={catalogId} disabled={running || catalogs.length === 0}
                onChange={(e) => setCatalogId(e.target.value)}>
                {catalogs.length === 0 ? (
                  <option value="">{t('No catalogs configured')}</option>
                ) : catalogs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {t('Tags')} <span style={{ color: '#8b949e', fontSize: 10 }}>{t('comma-separated, for every pack')}</span>
              <input className="ga-input" value={tags} disabled={running}
                onChange={(e) => setTags(e.target.value)} />
            </label>
            {job ? (
              <div style={{ fontSize: 12 }}>
                <progress max={job.total || 1} value={job.done} style={{ width: '100%' }} />
                <div style={{ color: '#8b949e' }}>
                  {job.done}/{job.total}
                  {job.status === 'running' ? ` · ${t('publishing…')}` : ''}
                  {job.status === 'error' && job.error ? ` · ${job.error}` : ''}
                </div>
                {failures.length > 0 ? (
                  <ul style={{ margin: '6px 0 0', paddingLeft: 16, maxHeight: 120, overflow: 'auto' }}>
                    {failures.map((i) => (
                      <li key={i.entity_id} style={{ color: '#f85149' }}>
                        {i.entity_id}: {i.error || t('skipped')}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <button className="ga-btn ga-btn-sm ga-btn-primary" onClick={start}
                disabled={running || !catalogId || entityIds.length === 0}>
                {running ? t('Publishing…') : t('Publish {n} packs').replace('{n}', String(entityIds.length))}
              </button>
              <button className="ga-btn ga-btn-sm" onClick={close} disabled={running}>
                {t('Close')}
              </button>
            </div>
          </div>
        </AnchoredPopover>
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
 */
export function ImportButton({
  accept = '.zip',
  onImported,
  label,
  title,
}: {
  accept?: string
  onImported?: (result: unknown) => void
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
  // Character-Import: full clone vs fresh start ("neu zugezogen") + Intro-Memory.
  const [mode, setMode] = useState<'full' | 'fresh'>('full')
  // Collections only: their preview reports every sub-pack as exists=false (a
  // collection cannot know what its packs will find), so the per-element
  // "will overwrite" flags cannot derive the flag here. This checkbox is the
  // only way the user can ask for an UPDATE of the parts already present.
  const [collUpdate, setCollUpdate] = useState(false)
  const [intro, setIntro] = useState('')
  const [introBusy, setIntroBusy] = useState(false)
  // Post-import warning that must not vanish with a 2-second toast (a location
  // import can name props the target world does not have).
  const [warn, setWarn] = useState<string | null>(null)

  const close = () => {
    setFile(null); setPreview(null); setPicked({}); setMode('full'); setIntro('')
    setCollUpdate(false)
    setWarn(null)
  }

  const regenIntro = async () => {
    if (!file) return
    setIntroBusy(true)
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await fetch('/api/content/character-intro-suggest', {
        method: 'POST', credentials: 'same-origin', body: fd })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
      setIntro((body.intro || '').trim())
      // Suggestion unavailable (LLM busy/down) — the import still works, the
      // intro can be typed manually.
      if (body.warning) toast(String(body.warning), 'error')
    } catch (e) {
      toast(t('Intro suggestion failed (import still possible)') + ': ' + (e as Error).message, 'error')
    } finally {
      setIntroBusy(false)
    }
  }

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
      || (preview.type === 'collection' && collUpdate)
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      // Only send selected_ids for multi-element bundles; single-element types
      // import as a whole.
      if (preview.multi) fd.append('selected_ids', selected.map((e) => e.id).join(','))
      fd.append('overwrite', overwrite ? 'true' : 'false')
      if (preview.type === 'character') {
        fd.append('mode', mode)
        if (mode === 'fresh') fd.append('intro', intro.trim())
      }
      const res = await fetch('/api/content/import', { method: 'POST', credentials: 'same-origin', body: fd })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
      // The route answers {status, result: <importer dict>}, so the importer's
      // own fields sit under `result` (app/routes/content_packs.py, /import).
      const result = (body as { result?: ImportResult }).result || {}
      const { summary, wentWrong, notes } = summarizeImport(result, t)

      if (summary) {
        toast(summary, wentWrong ? 'error' : 'info')
      } else if (result.status === 'exists') {
        // An importer may answer "this is already here, nothing was touched"
        // (a prop keeps its id, so it is never duplicated) — saying "Imported"
        // there would claim a change that did not happen.
        toast(t('Already present — nothing changed. Tick the entry to overwrite.'), 'error')
      } else if (result.status === 'failed') {
        toast(t('Nothing was imported.'), 'error')
      } else {
        toast(t('Imported'))
      }
      onImported?.(body)

      // Everything that must NOT vanish with a 2-second toast stays in the
      // dialog until the user closes it (summarizeImport says what).
      if (notes.length > 0) {
        setWarn(notes.join('\n'))
      } else {
        close()
      }
    } catch (e) {
      // The importer's refusals are full sentences (a fraction-era location
      // pack names why and what to do) — a toast is gone before they are read.
      const msg = t('Import failed') + ': ' + (e as Error).message
      toast(msg, 'error')
      setWarn(msg)
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

      {(loading || preview || warn) && (
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
              {warn && (
                <div style={{ color: '#e0a356', border: '1px solid #e0a356', borderRadius: 6,
                              padding: '8px 10px', fontSize: '0.85em', wordBreak: 'break-word',
                              whiteSpace: 'pre-wrap' }}>
                  {warn}
                </div>
              )}
              {!warn && loading && <div className="ga-loading">{t('Loading…')}</div>}
              {!warn && preview && preview.elements.length === 0 && (
                <div className="ga-placeholder">{t('No importable elements in this file.')}</div>
              )}
              {!warn && preview && preview.elements.length > 0 && (
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

              {!warn && preview && preview.type === 'character' && (
                <div style={{ marginTop: 12, borderTop: '1px solid var(--border, #30363d)', paddingTop: 10 }}>
                  <div style={{ fontSize: '0.82em', fontWeight: 600, marginBottom: 6 }}>{t('Import mode')}</div>
                  <label style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '3px 0', cursor: 'pointer' }}>
                    <input type="radio" name="char-import-mode" checked={mode === 'full'} onChange={() => setMode('full')} />
                    <span>{t('Full clone')} <span style={{ opacity: 0.55, fontSize: '0.82em' }}>— {t('keep all history (same/compatible world)')}</span></span>
                  </label>
                  <label style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '3px 0', cursor: 'pointer' }}>
                    <input type="radio" name="char-import-mode" checked={mode === 'fresh'}
                      onChange={() => { setMode('fresh'); if (!intro.trim()) void regenIntro() }} />
                    <span>{t('Fresh start (newly arrived)')} <span style={{ opacity: 0.55, fontSize: '0.82em' }}>— {t('keep identity, drop world-bound history')}</span></span>
                  </label>
                  {mode === 'fresh' && (
                    <div style={{ marginTop: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ fontSize: '0.78em', opacity: 0.7 }}>{t('Intro memory')}</span>
                        <button className="ga-btn ga-btn-sm" style={{ marginLeft: 'auto' }}
                          onClick={() => void regenIntro()} disabled={introBusy}>
                          {introBusy ? t('Generating…') : t('Regenerate')}
                        </button>
                      </div>
                      <textarea className="ga-input" rows={3} value={intro}
                        onChange={(e) => setIntro(e.target.value)}
                        placeholder={t('Short intro memory for the new arrival (editable)…')}
                        style={{ width: '100%', resize: 'vertical' }} />
                    </div>
                  )}
                </div>
              )}

              {!warn && preview && preview.type === 'collection' && (
                <div style={{ marginTop: 12, borderTop: '1px solid var(--border, #30363d)', paddingTop: 10 }}>
                  <label style={{ display: 'flex', alignItems: 'baseline', gap: 8, cursor: 'pointer' }}>
                    <input type="checkbox" checked={collUpdate}
                      onChange={(e) => setCollUpdate(e.target.checked)} />
                    <span>
                      {t('Update existing parts')}{' '}
                      <span style={{ opacity: 0.55, fontSize: '0.82em' }}>
                        — {t('without this, parts already present are reported as "exists" and left alone; locations are added again either way')}
                      </span>
                    </span>
                  </label>
                </div>
              )}
            </div>

            <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border, #30363d)',
                          display: 'flex', alignItems: 'center', gap: 10 }}>
              {!warn && preview && overwriteCount > 0 && (
                <span style={{ fontSize: '0.78em', color: '#e0a356' }}>
                  {t('{n} will be overwritten').replace('{n}', String(overwriteCount))}
                </span>
              )}
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                <button className="ga-btn ga-btn-sm" onClick={close} disabled={busy}>
                  {warn ? t('Close') : t('Cancel')}
                </button>
                {!warn && (
                  <button className="ga-btn ga-btn-sm ga-btn-primary" onClick={doImport}
                    disabled={busy || !preview || selCount === 0}>
                    {busy ? t('Importing…') : t('Import {n}').replace('{n}', String(selCount))}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
