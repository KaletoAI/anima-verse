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

interface BlendZone {
  kind: string
  until?: number
}

interface Blend {
  toward: string
  zones: BlendZone[]
  noise?: number
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
  // Compositions (AV3D-13 v2): zone gradients toward a neighbor kind —
  // "coast" = water → sand → whatever the other neighbors are.
  const [blends, setBlends] = useState<Record<string, Blend>>({})
  const [blendEdit, setBlendEdit] = useState<{ kind: string; blend: Blend } | null>(null)
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
        backends?: BackendInfo[]; subjects?: Record<string, string>
        blends?: Record<string, Blend> }>(
        '/world/surface-textures')
      setTextures(d.textures || [])
      setPending(d.pending || [])
      setBackends(d.backends || [])
      setSubjects(d.subjects || {})
      setBlends(d.blends || {})
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
          ? t('This kind is already generating on that backend.')
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

  const saveBlend = useCallback(() => {
    if (!blendEdit) return
    const k = blendEdit.kind.trim().toLowerCase()
    if (!k) return
    void apiPost(`/world/surface-textures/blends/${encodeURIComponent(k)}`,
      { blend: blendEdit.blend })
      .then(() => { setBlendEdit(null); void load() })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [blendEdit, load, t, toast])

  const removeBlend = useCallback((k: string) => {
    if (armedDel !== `blend:${k}`) {
      setArmedDel(`blend:${k}`)
      return
    }
    setArmedDel('')
    void apiDelete(`/world/surface-textures/blends/${encodeURIComponent(k)}`)
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

        <div className="ga-form-section-label">{t('Compositions (blends)')}</div>
        <span className="ga-hint">
          {t('A composition is a zone gradient toward a neighbor kind instead of a texture — e.g. coast: water → sand → whatever the other neighbors are. The tiles involved need their terrain set (sea: water, coast: coast). A composition wins over textures of the same kind.')}
        </span>
        {Object.keys(blends).length === 0 && !blendEdit ? (
          <div className="ga-empty">{t('No compositions yet.')}</div>
        ) : null}
        {Object.entries(blends).map(([bk, b]) => (
          <div key={bk} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, minWidth: 70 }}>{bk}</span>
            <span className="ga-hint">
              → {b.toward} · {b.zones.map((z) =>
                z.until != null ? `${z.kind} ${Math.round(z.until * 100)}%` : z.kind).join(' · ')}
              {b.noise != null ? ` · ${t('noise')} ${b.noise}` : ''}
            </span>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              style={{ marginLeft: 'auto' }}
              onClick={() => setBlendEdit({ kind: bk, blend: JSON.parse(JSON.stringify(b)) })}
            >
              {t('Edit')}
            </button>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => removeBlend(bk)}
            >
              {armedDel === `blend:${bk}` ? t('Really delete?') : '🗑'}
            </button>
          </div>
        ))}
        {blendEdit ? (
          <div className="ga-form" style={{ gap: 6 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                className="ga-input"
                style={{ width: 120 }}
                placeholder={t('kind (coast, …)')}
                value={blendEdit.kind}
                onChange={(e) => setBlendEdit({ ...blendEdit, kind: e.target.value })}
              />
              <span className="ga-hint">{t('toward')}</span>
              <input
                className="ga-input"
                list="surface-kind-options"
                style={{ width: 110 }}
                value={blendEdit.blend.toward}
                title={t('The neighbor kind the gradient runs to (from the map grid).')}
                onChange={(e) => setBlendEdit({ ...blendEdit,
                  blend: { ...blendEdit.blend, toward: e.target.value } })}
              />
              <span className="ga-hint">{t('noise')}</span>
              <input
                className="ga-input"
                type="number"
                min={0}
                max={0.5}
                step={0.01}
                style={{ width: 64 }}
                value={blendEdit.blend.noise ?? ''}
                placeholder="0.06"
                title={t('Border fraying (0..0.5).')}
                onChange={(e) => {
                  const n = parseFloat(e.target.value)
                  setBlendEdit({ ...blendEdit, blend: { ...blendEdit.blend,
                    noise: Number.isFinite(n) ? n : undefined } })
                }}
              />
            </div>
            {blendEdit.blend.zones.map((z, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span className="ga-hint" style={{ width: 52 }}>{t('Zone')} {i + 1}</span>
                <input
                  className="ga-input"
                  list="surface-zone-options"
                  style={{ width: 120 }}
                  value={z.kind}
                  title={t('A library kind — or "neighbor" for the dominant non-toward neighbor kind.')}
                  onChange={(e) => {
                    const zones = blendEdit.blend.zones.map((zz, j) =>
                      j === i ? { ...zz, kind: e.target.value } : zz)
                    setBlendEdit({ ...blendEdit, blend: { ...blendEdit.blend, zones } })
                  }}
                />
                <input
                  className="ga-input"
                  type="number"
                  min={0.01}
                  max={1}
                  step={0.01}
                  style={{ width: 72 }}
                  value={z.until ?? ''}
                  placeholder={i === blendEdit.blend.zones.length - 1 ? t('rest') : '0.5'}
                  title={t('Share of the transition path (0..1, ascending) — the last zone may stay empty (= rest).')}
                  onChange={(e) => {
                    const n = parseFloat(e.target.value)
                    const zones = blendEdit.blend.zones.map((zz, j) =>
                      j === i ? { ...zz, until: Number.isFinite(n) ? n : undefined } : zz)
                    setBlendEdit({ ...blendEdit, blend: { ...blendEdit.blend, zones } })
                  }}
                />
                <button
                  type="button"
                  className="ga-btn ga-btn-sm"
                  disabled={blendEdit.blend.zones.length <= 1}
                  onClick={() => setBlendEdit({ ...blendEdit, blend: { ...blendEdit.blend,
                    zones: blendEdit.blend.zones.filter((_, j) => j !== i) } })}
                >
                  ✕
                </button>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                disabled={blendEdit.blend.zones.length >= 8}
                onClick={() => setBlendEdit({ ...blendEdit, blend: { ...blendEdit.blend,
                  zones: [...blendEdit.blend.zones, { kind: 'neighbor' }] } })}
              >
                + {t('Zone')}
              </button>
              <button type="button" className="ga-btn ga-btn-primary" onClick={saveBlend}
                disabled={!blendEdit.kind.trim() || !blendEdit.blend.toward.trim()}>
                {t('Save')}
              </button>
              <button type="button" className="ga-btn" onClick={() => setBlendEdit(null)}>
                {t('Cancel')}
              </button>
            </div>
            <datalist id="surface-zone-options">
              {['neighbor', ...knownKinds].map((k) => <option key={k} value={k} />)}
            </datalist>
          </div>
        ) : (
          <div>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              onClick={() => setBlendEdit({ kind: 'coast', blend: {
                toward: 'water',
                zones: [{ kind: 'water', until: 0.42 }, { kind: 'sand', until: 0.62 }, { kind: 'neighbor' }],
                noise: 0.08,
              } })}
              title={t('Prefilled with the contract example (coast: water → sand → neighbor).')}
            >
              + {t('New composition')}
            </button>
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
