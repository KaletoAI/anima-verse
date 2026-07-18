/**
 * SurfaceTexturesTab — the global surface-texture library (AV3D-13) as its
 * own Game-Admin tab (next to the Map). Terrain tiles (road, water, …) in
 * the 3D client use these seamless top-down materials as ground instead of
 * the 2D icons. Like the galleries, SEVERAL versions per kind are stored —
 * one is ACTIVE (what the client gets); each version shows HOW it was made
 * (backend/upload + date, full prompt in the lightbox). Generate runs
 * through the normal image pipeline (use case "surface_texture"); the
 * COMPLETE final prompt is shown and editable before generating. An empty
 * library is fine — the client falls back to its procedural materials.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { TERRAIN_TYPES } from '../world/worldTypes'

interface TexVersion {
  filename: string
  url: string
  size_m: number
  created_at: string
  source: string
  backend: string
  prompt: string
  negative: string
  active: boolean
}

interface TexGroup {
  kind: string
  versions: TexVersion[]
}

interface BackendInfo {
  name: string
  prompt_style: string
  prompt_negative: string
}

export function SurfaceTexturesTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [textures, setTextures] = useState<TexGroup[]>([])
  const [pending, setPending] = useState<string[]>([])
  const [backends, setBackends] = useState<BackendInfo[]>([])
  // Per-kind subject phrases (curated server-side) — the visual character
  // of the material; unknown kinds get the generic fallback.
  const [subjects, setSubjects] = useState<Record<string, string>>({})
  const [loaded, setLoaded] = useState(false)
  const [kind, setKind] = useState('')
  const [backend, setBackend] = useState('')
  const [prompt, setPrompt] = useState('')
  const [negative, setNegative] = useState('')
  const [promptTouched, setPromptTouched] = useState(false)
  const [armedDel, setArmedDel] = useState('')
  const [zoom, setZoom] = useState<{ kind: string; v: TexVersion } | null>(null)
  const [cacheBump, setCacheBump] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const uploadKindRef = useRef('')

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ textures?: TexGroup[]; pending?: string[]
        backends?: BackendInfo[]; subjects?: Record<string, string> }>(
        '/world/surface-textures')
      setTextures(d.textures || [])
      setPending(d.pending || [])
      setBackends(d.backends || [])
      setSubjects(d.subjects || {})
      setLoaded(true)
      return d
    } catch {
      setLoaded(true)
      return null
    }
  }, [])

  // Poll while a generation runs — same pattern as the building models:
  // pending comes from the server, never a local never-reset flag.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      const d = await load()
      if (!d?.pending?.length) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = null
        setCacheBump((b) => b + 1)
      }
    }, 3000)
  }, [load])

  useEffect(() => {
    load().then((d) => { if (d?.pending?.length) startPoll() })
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [load, startPoll])

  const backendInfo = backends.find((b) => b.name === backend) || backends[0]

  // The final prompt = use-case style of the chosen backend + the material
  // subject from the kind — shown in full and editable; manual edits stick.
  useEffect(() => {
    if (promptTouched) return
    const style = backendInfo?.prompt_style || ''
    const k = kind.trim().toLowerCase()
    // Same composition as the server: curated phrase, else the generic
    // "surface of <kind>" fallback.
    const subject = !k ? 'a natural ground surface'
      : (subjects[k] || `the surface of ${k} seen straight from above`)
    setPrompt(style ? `${style}, ${subject}` : subject)
    setNegative(backendInfo?.prompt_negative || '')
  }, [kind, backendInfo, subjects, promptTouched])

  const generate = useCallback(() => {
    const k = kind.trim().toLowerCase()
    if (!k) return
    void apiPost<{ status?: string }>('/world/surface-textures/generate', {
      kind: k, backend: backendInfo?.name || '', prompt, negative,
    })
      .then((d) => {
        toast(d?.status === 'already_running'
          ? t('This kind is already generating.')
          : t('Generating the texture…'))
        startPoll()
        void load()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [kind, backendInfo, prompt, negative, load, startPoll, t, toast])

  const upload = useCallback((k: string, file: File) => {
    void apiUpload(`/world/surface-textures/${encodeURIComponent(k)}/upload`, file)
      .then(() => { setCacheBump((b) => b + 1); void load() })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [load, t, toast])

  const setSize = useCallback((k: string, filename: string, raw: string) => {
    const n = parseFloat(raw)
    if (!Number.isFinite(n) || n <= 0) return
    void apiPost(`/world/surface-textures/${encodeURIComponent(k)}/size`,
      { size_m: n, file: filename })
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [load, t, toast])

  const select = useCallback((k: string, filename: string) => {
    void apiPost(`/world/surface-textures/${encodeURIComponent(k)}/select`, { file: filename })
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [load, t, toast])

  const remove = useCallback((k: string, filename: string) => {
    if (armedDel !== filename) {
      setArmedDel(filename)
      return
    }
    setArmedDel('')
    void apiDelete(`/world/surface-textures/${encodeURIComponent(k)}?file=${encodeURIComponent(filename)}`)
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [armedDel, load, t, toast])

  // Compact "how was this made" label: backend for generated versions,
  // upload marker for uploads, em dash for legacy files without meta.
  const madeWith = (v: TexVersion) =>
    v.source === 'generated' ? (v.backend || t('generated'))
      : v.source === 'uploaded' ? t('uploaded') : '—'

  const dateShort = (iso: string) => {
    if (!iso) return ''
    const d = new Date(iso)
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  }

  const knownKinds = Array.from(new Set([...TERRAIN_TYPES, 'gravel', 'dirt', 'snow']))

  return (
    <div style={{ padding: 16, height: '100%', overflow: 'auto' }}>
      <div className="ga-form" style={{ maxWidth: 860, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="ga-form-section-label">{t('Surface textures (3D terrain)')}</div>
        <span className="ga-hint">
          {t('Seamless top-down ground materials for terrain tiles in the 3D client — one texture per kind, matching the terrain field (road, water, …). Without a texture the client uses its built-in materials.')}
          {' '}
          {t('Several versions per kind can be stored — the ⭐ active one is what the client gets; click a thumbnail to enlarge.')}
        </span>

        {!loaded ? (
          <div className="ga-empty">{t('Loading…')}</div>
        ) : textures.length === 0 ? (
          <div className="ga-empty">{t('No textures yet.')}</div>
        ) : (
          textures.map((tx) => (
            <div key={tx.kind} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontWeight: 600 }}>{tx.kind}</span>
                {pending.includes(tx.kind) ? (
                  <span className="ga-hint">{t('Generating…')}</span>
                ) : null}
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  onClick={() => { setKind(tx.kind); setPromptTouched(false) }}
                  title={t('Prefill the generator with this kind')}
                >
                  ↻ {t('Regenerate')}
                </button>
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  onClick={() => {
                    uploadKindRef.current = tx.kind
                    uploadRef.current?.click()
                  }}
                  title={t('Upload a new version for this kind (JPEG/PNG/WebP, seamless, top-down)')}
                >
                  ⬆
                </button>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {tx.versions.map((v) => (
                  <div
                    key={v.filename}
                    style={{
                      display: 'flex', flexDirection: 'column', gap: 4, width: 128,
                      padding: 6, borderRadius: 6,
                      border: v.active
                        ? '2px solid var(--accent, #58a6ff)'
                        : '1px solid var(--border, #30363d)',
                    }}
                  >
                    <img
                      src={`${v.url}?v=${cacheBump}`}
                      alt={`${tx.kind} ${v.filename}`}
                      style={{ width: '100%', height: 96, objectFit: 'cover',
                               borderRadius: 4, cursor: 'zoom-in' }}
                      title={t('Click to enlarge')}
                      onClick={() => setZoom({ kind: tx.kind, v })}
                    />
                    <span className="ga-hint" style={{ fontSize: '0.75em', lineHeight: 1.25 }}
                      title={v.prompt || undefined}>
                      {madeWith(v)}
                      {dateShort(v.created_at) ? ` · ${dateShort(v.created_at)}` : ''}
                    </span>
                    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <input
                        className="ga-input"
                        type="number"
                        min={0.1}
                        step={0.5}
                        style={{ width: 52 }}
                        defaultValue={v.size_m}
                        title={t('Physical edge length in metres — the client tiles in world scale (10 m cell = 10/size repetitions).')}
                        onBlur={(e) => setSize(tx.kind, v.filename, e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                      />
                      {v.active ? (
                        <span title={t('Active — this version is what the 3D client gets.')}>⭐</span>
                      ) : (
                        <button
                          type="button"
                          className="ga-btn ga-btn-sm"
                          onClick={() => select(tx.kind, v.filename)}
                          title={t('Make this version the active one (what the 3D client gets)')}
                        >
                          {t('Select')}
                        </button>
                      )}
                      <button
                        type="button"
                        className="ga-btn ga-btn-sm ga-btn-danger"
                        style={{ marginLeft: 'auto' }}
                        onClick={() => remove(tx.kind, v.filename)}
                      >
                        {armedDel === v.filename ? t('Really delete?') : '🗑'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}

        <div className="ga-form-section-label">{t('Generate texture')}</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            className="ga-input"
            list="surface-kind-options"
            style={{ width: 130 }}
            placeholder={t('kind (road, …)')}
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            title={t('Open vocabulary — must match the terrain field of the tiles it should cover.')}
          />
          <datalist id="surface-kind-options">
            {knownKinds.map((k) => <option key={k} value={k} />)}
          </datalist>
          <select
            className="ga-input"
            style={{ flex: 1, minWidth: 160 }}
            value={backendInfo?.name || ''}
            onChange={(e) => { setBackend(e.target.value); setPromptTouched(false) }}
          >
            {backends.map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
          </select>
          <button
            type="button"
            className="ga-btn ga-btn-primary"
            disabled={!kind.trim() || !backends.length}
            onClick={generate}
          >
            {t('Generate')}
          </button>
          <button
            type="button"
            className="ga-btn"
            disabled={!kind.trim()}
            onClick={() => {
              uploadKindRef.current = kind.trim().toLowerCase()
              uploadRef.current?.click()
            }}
            title={t('Upload an image for this kind instead of generating')}
          >
            ⬆ {t('Upload')}
          </button>
        </div>
        <label className="ga-field">
          <span className="ga-field-caption">{t('Final prompt')}</span>
          <textarea
            className="ga-textarea"
            rows={3}
            value={prompt}
            onChange={(e) => { setPrompt(e.target.value); setPromptTouched(true) }}
          />
        </label>
        <label className="ga-field">
          <span className="ga-field-caption">{t('Negative prompt')}</span>
          <textarea
            className="ga-textarea"
            rows={2}
            value={negative}
            onChange={(e) => { setNegative(e.target.value); setPromptTouched(true) }}
          />
        </label>
        <input
          ref={uploadRef}
          type="file"
          accept=".jpg,.jpeg,.png,.webp"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f && uploadKindRef.current) upload(uploadKindRef.current, f)
            e.target.value = ''
          }}
        />
      </div>

      {zoom ? (
        <div className="ga-gallery-lightbox" onClick={() => setZoom(null)} role="dialog">
          <img src={`${zoom.v.url}?v=${cacheBump}`} alt={zoom.kind} />
          {/* Provenance caption — kind, how it was made, date, full prompt. */}
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              position: 'absolute', left: '50%', bottom: 16, transform: 'translateX(-50%)',
              maxWidth: '84vw', maxHeight: '30vh', overflow: 'auto', cursor: 'auto',
              background: 'rgba(0,0,0,0.75)', color: '#e6edf3', borderRadius: 6,
              padding: '8px 12px', fontSize: '0.85em', lineHeight: 1.4,
            }}
          >
            <div style={{ fontWeight: 600 }}>
              {zoom.kind} · {madeWith(zoom.v)}
              {dateShort(zoom.v.created_at) ? ` · ${dateShort(zoom.v.created_at)}` : ''}
              {` · ${zoom.v.size_m} m`}
            </div>
            {zoom.v.prompt ? (
              <div style={{ opacity: 0.85, marginTop: 4 }}>{zoom.v.prompt}</div>
            ) : null}
            {zoom.v.negative ? (
              <div style={{ opacity: 0.6, marginTop: 2 }}>{t('Negative prompt')}: {zoom.v.negative}</div>
            ) : null}
          </div>
          <button
            type="button"
            className="ga-gallery-lightbox-close"
            onClick={() => setZoom(null)}
            aria-label={t('Close')}
          >
            ×
          </button>
        </div>
      ) : null}
    </div>
  )
}
