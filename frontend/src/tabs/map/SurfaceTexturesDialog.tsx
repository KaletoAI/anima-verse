/**
 * SurfaceTexturesDialog — the global surface-texture library (AV3D-13),
 * opened from the Map tab. Terrain tiles (road, water, …) in the 3D client
 * use these seamless top-down materials as ground instead of the 2D icons;
 * ONE texture per kind (open vocabulary matching the location `terrain`
 * field). Generate runs through the normal image pipeline (use case
 * "surface_texture"); the COMPLETE final prompt is shown and editable
 * before generating. An empty library is fine — the client falls back to
 * its procedural materials.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { TERRAIN_TYPES } from '../world/worldTypes'

interface Tex {
  kind: string
  filename: string
  url: string
  size_m: number
  size: number
}

interface BackendInfo {
  name: string
  prompt_style: string
  prompt_negative: string
}

export function SurfaceTexturesDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [textures, setTextures] = useState<Tex[]>([])
  const [pending, setPending] = useState<string[]>([])
  const [backends, setBackends] = useState<BackendInfo[]>([])
  const [loaded, setLoaded] = useState(false)
  const [kind, setKind] = useState('')
  const [backend, setBackend] = useState('')
  const [prompt, setPrompt] = useState('')
  const [negative, setNegative] = useState('')
  const [promptTouched, setPromptTouched] = useState(false)
  const [armedDel, setArmedDel] = useState('')
  const [cacheBump, setCacheBump] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const uploadKindRef = useRef('')

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ textures?: Tex[]; pending?: string[]; backends?: BackendInfo[] }>(
        '/world/surface-textures')
      setTextures(d.textures || [])
      setPending(d.pending || [])
      setBackends(d.backends || [])
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
    const subject = `${(kind || 'ground').trim()} ground material`
    setPrompt(style ? `${style}, ${subject}` : subject)
    setNegative(backendInfo?.prompt_negative || '')
  }, [kind, backendInfo, promptTouched])

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

  const setSize = useCallback((k: string, v: string) => {
    const n = parseFloat(v)
    if (!Number.isFinite(n) || n <= 0) return
    void apiPost(`/world/surface-textures/${encodeURIComponent(k)}/size`, { size_m: n })
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [load, t, toast])

  const remove = useCallback((k: string) => {
    if (armedDel !== k) {
      setArmedDel(k)
      return
    }
    setArmedDel('')
    void apiDelete(`/world/surface-textures/${encodeURIComponent(k)}`)
      .then(() => load())
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [armedDel, load, t, toast])

  const knownKinds = Array.from(new Set([...TERRAIN_TYPES, 'gravel', 'dirt', 'snow']))

  return (
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ width: 640, maxWidth: '94vw' }}
        onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Surface textures (3D terrain)')}</span>
          <button className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <span className="ga-hint">
            {t('Seamless top-down ground materials for terrain tiles in the 3D client — one texture per kind, matching the terrain field (road, water, …). Without a texture the client uses its built-in materials.')}
          </span>

          {!loaded ? (
            <div className="ga-empty">{t('Loading…')}</div>
          ) : textures.length === 0 ? (
            <div className="ga-empty">{t('No textures yet.')}</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {textures.map((tex) => (
                <div key={tex.kind} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <img
                    src={`${tex.url}?v=${cacheBump}`}
                    alt={tex.kind}
                    style={{ width: 48, height: 48, objectFit: 'cover', borderRadius: 4,
                             border: '1px solid var(--border, #30363d)' }}
                  />
                  <span style={{ fontWeight: 600, minWidth: 70 }}>{tex.kind}</span>
                  {pending.includes(tex.kind) ? (
                    <span className="ga-hint">{t('Generating…')}</span>
                  ) : null}
                  <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center',
                                  fontSize: '0.82em', marginLeft: 'auto' }}
                    title={t('Physical edge length in metres — the client tiles in world scale (10 m cell = 10/size repetitions).')}>
                    {t('Size (m)')}
                    <input
                      className="ga-input"
                      type="number"
                      min={0.1}
                      step={0.5}
                      style={{ width: 64 }}
                      defaultValue={tex.size_m}
                      onBlur={(e) => setSize(tex.kind, e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                    />
                  </label>
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm"
                    onClick={() => { setKind(tex.kind); setPromptTouched(false) }}
                    title={t('Prefill the generator with this kind')}
                  >
                    ↻ {t('Regenerate')}
                  </button>
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm"
                    onClick={() => {
                      uploadKindRef.current = tex.kind
                      uploadRef.current?.click()
                    }}
                    title={t('Replace with an uploaded image (JPEG/PNG/WebP, seamless, top-down)')}
                  >
                    ⬆
                  </button>
                  <button
                    type="button"
                    className={`ga-btn ga-btn-sm ga-btn-danger`}
                    onClick={() => remove(tex.kind)}
                  >
                    {armedDel === tex.kind ? t('Really delete?') : '🗑'}
                  </button>
                </div>
              ))}
            </div>
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
        </div>
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
    </div>
  )
}
