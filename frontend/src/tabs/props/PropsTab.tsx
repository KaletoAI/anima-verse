/**
 * PropsTab — the prop library (plan-room-props.md) as its own Game-Admin tab
 * (next to Surface textures). A prop is ONE furnishing object (chair, table,
 * plant …) as its own GLB mesh, generated from a product-shot render
 * (use case "prop") → img2mesh, or uploaded. Each prop carries object-local
 * animation markers so a marker travels WITH the object into any room.
 *
 * Pattern: SurfaceTexturesTab (cards / provenance / generate form with the
 * full editable final prompt) + BuildingModelPanel (Model3DViewer, persisted
 * orientation fix, GLB upload). An empty library is the normal starting state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Model3DViewer } from '../characters/Model3DViewer'

export interface PropMarker {
  animation: string
  /** Object-local position: fractions of the model bounding box (0..1). */
  at: [number, number, number]
  /** Facing in degrees (0 south / 90 east / 180 north / 270 west). */
  facing?: number
}

export interface PropFull {
  id: string
  name: string
  category: string
  size_m: number
  tags: string[]
  marker_count: number
  has_model: boolean
  rotation?: { x?: number; y?: number; z?: number }
  markers?: PropMarker[]
  has_source?: boolean
  created_at?: string
  source?: string
  backend?: string
  prompt?: string
  model_url?: string
  source_url?: string
}

interface ImageBackendInfo {
  name: string
  prompt_style: string
  prompt_negative: string
}

interface MeshBackendInfo {
  name: string
  face_num?: number | null
}

// Suggested categories (open vocabulary — free text via datalist). The base
// ones (chair/bed/bench/…) are what the client's category→animation mapping
// keys on (AV3D-6); everything else is decoration.
const CATEGORY_SUGGESTIONS = [
  'chair', 'table', 'bed', 'sofa', 'bench', 'stool', 'shelf', 'cabinet',
  'desk', 'lamp', 'plant', 'rug', 'decoration', 'appliance', 'misc',
]

export function PropsTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [props, setProps] = useState<PropFull[]>([])
  const [pending, setPending] = useState<string[]>([])
  const [imageBackends, setImageBackends] = useState<ImageBackendInfo[]>([])
  const [meshBackends, setMeshBackends] = useState<MeshBackendInfo[]>([])
  const [loaded, setLoaded] = useState(false)
  const [selected, setSelected] = useState('')
  const [armedDel, setArmedDel] = useState('')
  const [cacheBump, setCacheBump] = useState(0)

  // Generate / create form.
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [sizeM, setSizeM] = useState('1')
  const [imageBackend, setImageBackend] = useState('')
  const [meshBackend, setMeshBackend] = useState('')
  const [style, setStyle] = useState('')
  const [negative, setNegative] = useState('')
  const [styleTouched, setStyleTouched] = useState(false)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<{ props?: PropFull[]; pending?: string[]
        image_backends?: ImageBackendInfo[]; mesh_backends?: MeshBackendInfo[] }>(
        '/world/props')
      setProps(d.props || [])
      setPending(d.pending || [])
      setImageBackends(d.image_backends || [])
      setMeshBackends(d.mesh_backends || [])
      setLoaded(true)
      return d
    } catch {
      setLoaded(true)
      return null
    }
  }, [])

  // Poll while a generation runs — pending comes from the server (same as the
  // surface textures / building models), never a local never-reset flag.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    let n = 0
    const tick = async () => {
      n += 1
      const d = await load()
      if (!d?.pending?.length) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = null
        setCacheBump((b) => b + 1)
        return
      }
      // Meshing takes minutes — slow the poll down after ~2 min, never give up.
      if (n === 40) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(tick, 15000)
      }
    }
    pollRef.current = setInterval(tick, 3000)
  }, [load])

  useEffect(() => {
    load().then((d) => { if (d?.pending?.length) startPoll() })
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [load, startPoll])

  const imageBackendInfo = imageBackends.find((b) => b.name === imageBackend) || imageBackends[0]

  // The final prompt = the use-case style of the chosen image backend + the
  // object subject (description, else the name). Style is its OWN editable
  // field (final-prompt rule); manual edits stick.
  useEffect(() => {
    if (styleTouched) return
    setStyle(imageBackendInfo?.prompt_style || '')
    setNegative(imageBackendInfo?.prompt_negative || '')
  }, [imageBackendInfo, styleTouched])

  const subject = (description.trim() || name.trim())
  const finalPrompt = style.trim()
    ? (subject ? `${style.trim()}, ${subject}` : style.trim())
    : subject

  const resetForm = () => {
    setName('')
    setDescription('')
    setCategory('')
    setSizeM('1')
    setStyleTouched(false)
  }

  const sizeValue = () => {
    const n = parseFloat(sizeM)
    return Number.isFinite(n) && n > 0 ? n : 1
  }

  const generate = useCallback(() => {
    if (!name.trim()) return
    void apiPost<{ status?: string; prop?: PropFull }>('/world/props/generate', {
      name: name.trim(), category: category.trim(), size_m: sizeValue(),
      prompt: finalPrompt, negative,
      image_backend: imageBackendInfo?.name || '', mesh_backend: meshBackend,
    })
      .then((d) => {
        toast(t('Generating the prop…'))
        if (d?.prop?.id) setSelected(d.prop.id)
        resetForm()
        startPoll()
        void load()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, category, sizeM, finalPrompt, negative, imageBackendInfo, meshBackend, load, startPoll, t, toast])

  const createEmpty = useCallback(() => {
    if (!name.trim()) return
    void apiPost<{ status?: string; prop?: PropFull }>('/world/props', {
      name: name.trim(), category: category.trim(), size_m: sizeValue(),
    })
      .then((d) => {
        toast(t('Prop created — upload a GLB or generate its model.'))
        if (d?.prop?.id) setSelected(d.prop.id)
        resetForm()
        void load()
      })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, category, sizeM, load, t, toast])

  const remove = useCallback((id: string) => {
    if (armedDel !== id) {
      setArmedDel(id)
      return
    }
    setArmedDel('')
    void apiDelete(`/world/props/${encodeURIComponent(id)}`)
      .then(() => { if (selected === id) setSelected(''); void load() })
      .catch((e) => toast(t('Error') + ': ' + (e as Error).message, 'error'))
  }, [armedDel, selected, load, t, toast])

  const selectedProp = props.find((p) => p.id === selected) || null

  return (
    <div style={{ padding: 16, height: '100%', overflow: 'auto' }}>
      <div className="ga-form" style={{ maxWidth: 900, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="ga-form-section-label">{t('Prop library')}</div>
        <span className="ga-hint">
          {t('Single furnishing objects (chair, table, plant …) as their own 3D models — generated from a product-shot render or uploaded. Each prop carries object-local animation markers that travel with it into any room. The 3D client reads the library from /assets/props.')}
        </span>

        {/* ── Library cards ── */}
        {!loaded ? (
          <div className="ga-empty">{t('Loading…')}</div>
        ) : props.length === 0 ? (
          <div className="ga-empty">{t('No props yet.')}</div>
        ) : (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {props.map((p) => {
              const isSel = p.id === selected
              const busy = pending.includes(p.id)
              return (
                <div
                  key={p.id}
                  onClick={() => setSelected(isSel ? '' : p.id)}
                  style={{
                    width: 150, padding: 8, borderRadius: 8, cursor: 'pointer',
                    display: 'flex', flexDirection: 'column', gap: 4,
                    border: isSel
                      ? '2px solid var(--accent, #58a6ff)'
                      : '1px solid var(--border, #30363d)',
                    background: isSel ? 'rgba(88,166,255,0.08)' : 'transparent',
                  }}
                >
                  <div style={{
                    width: '100%', height: 110, borderRadius: 4, overflow: 'hidden',
                    background: 'rgba(255,255,255,0.04)', display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                  }}>
                    {p.has_source ? (
                      <img
                        src={`/assets/props/${encodeURIComponent(p.id)}/source?v=${cacheBump}`}
                        alt={p.name}
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      />
                    ) : (
                      <span style={{ fontSize: 32, opacity: 0.5 }}>📦</span>
                    )}
                  </div>
                  <span style={{ fontWeight: 600, fontSize: '0.9em', overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.name}
                  </span>
                  <span className="ga-hint" style={{ fontSize: '0.75em' }}>
                    {p.category || '—'} · {p.size_m} m
                    {p.marker_count ? ` · 🎯${p.marker_count}` : ''}
                    {!p.has_model ? ` · ${t('no model')}` : ''}
                    {busy ? ` · ${t('generating…')}` : ''}
                  </span>
                  {p.tags.length ? (
                    <span className="ga-hint" style={{ fontSize: '0.72em', opacity: 0.75,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.tags.join(', ')}
                    </span>
                  ) : null}
                </div>
              )
            })}
          </div>
        )}

        {/* ── Detail of the selected prop ── */}
        {selectedProp ? (
          <PropDetail
            prop={selectedProp}
            pending={pending.includes(selectedProp.id)}
            cacheBump={cacheBump}
            onChanged={load}
            onDelete={() => remove(selectedProp.id)}
            armedDelete={armedDel === selectedProp.id}
          />
        ) : null}

        {/* ── Generate / create form ── */}
        <div className="ga-form-section-label">{t('Generate prop')}</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label className="ga-field" style={{ flex: '1 1 200px' }}>
            <span className="ga-field-caption">{t('Name')}</span>
            <input className="ga-input" value={name}
              placeholder={t('e.g. Oak dining chair')}
              onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="ga-field" style={{ flex: '0 0 150px' }}>
            <span className="ga-field-caption">{t('Category')}</span>
            <input className="ga-input" list="prop-category-options" value={category}
              placeholder={t('chair, table, …')}
              onChange={(e) => setCategory(e.target.value)} />
            <datalist id="prop-category-options">
              {CATEGORY_SUGGESTIONS.map((c) => <option key={c} value={c} />)}
            </datalist>
          </label>
          <label className="ga-field" style={{ flex: '0 0 130px' }}
            title={t('Largest real edge in metres — the mesh loses its scale, so the client sizes the object by this. Mandatory.')}>
            <span className="ga-field-caption">{t('Size (m)')}</span>
            <input className="ga-input" type="number" min={0.05} step={0.05}
              value={sizeM} onChange={(e) => setSizeM(e.target.value)} />
          </label>
        </div>
        <label className="ga-field">
          <span className="ga-field-caption">{t('Object description (subject)')}</span>
          <input className="ga-input" value={description}
            placeholder={t('Defaults to the name — describe materials, colour, style.')}
            onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <label className="ga-field" style={{ flex: '1 1 200px' }}>
            <span className="ga-field-caption">{t('Image backend (render)')}</span>
            <select className="ga-input" value={imageBackendInfo?.name || ''}
              onChange={(e) => { setImageBackend(e.target.value); setStyleTouched(false) }}>
              {imageBackends.map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
            </select>
          </label>
          <label className="ga-field" style={{ flex: '1 1 200px' }}>
            <span className="ga-field-caption">{t('Mesh backend (img2mesh)')}</span>
            <select className="ga-input" value={meshBackend}
              onChange={(e) => setMeshBackend(e.target.value)}>
              <option value="">{t('— default (cheapest available) —')}</option>
              {meshBackends.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name}{b.face_num ? ` · ${b.face_num.toLocaleString()} ${t('faces')}` : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="ga-field">
          <span className="ga-field-caption">{t('Style (use-case)')}</span>
          <textarea className="ga-textarea" rows={2} value={style}
            onChange={(e) => { setStyle(e.target.value); setStyleTouched(true) }} />
        </label>
        <label className="ga-field">
          <span className="ga-field-caption">{t('Negative prompt')}</span>
          <textarea className="ga-textarea" rows={2} value={negative}
            onChange={(e) => { setNegative(e.target.value); setStyleTouched(true) }} />
        </label>
        <label className="ga-field">
          <span className="ga-field-caption">{t('Final prompt (sent to the render)')}</span>
          <textarea className="ga-textarea" rows={2} value={finalPrompt} readOnly
            style={{ opacity: 0.85 }} />
        </label>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" className="ga-btn ga-btn-primary"
            disabled={!name.trim() || !meshBackends.length || !imageBackends.length}
            onClick={generate}>
            {t('Generate')}
          </button>
          <button type="button" className="ga-btn"
            disabled={!name.trim()}
            onClick={createEmpty}
            title={t('Create the record only — then upload a GLB in its detail panel.')}>
            {t('Create empty (upload later)')}
          </button>
          {!meshBackends.length ? (
            <span className="ga-hint">
              {t('No img2mesh backend configured (api_type openai_mesh) — you can still create empty props and upload GLBs.')}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/** Detail panel of one prop: viewer + orientation fix + size/category/tags
 *  editor + GLB upload + two-step delete. Object-local markers (A4) attach
 *  here as their own section. */
function PropDetail({ prop, pending, cacheBump, onChanged, onDelete, armedDelete }: {
  prop: PropFull
  pending: boolean
  cacheBump: number
  onChanged: () => Promise<unknown>
  onDelete: () => void
  armedDelete: boolean
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(prop.id)
  const uploadRef = useRef<HTMLInputElement>(null)

  const [categoryDraft, setCategoryDraft] = useState(prop.category)
  const [sizeDraft, setSizeDraft] = useState(String(prop.size_m))
  const [tagsDraft, setTagsDraft] = useState(prop.tags.join(', '))
  useEffect(() => {
    setCategoryDraft(prop.category)
    setSizeDraft(String(prop.size_m))
    setTagsDraft(prop.tags.join(', '))
  }, [prop.id, prop.category, prop.size_m, prop.tags])

  const patch = useCallback(async (body: Record<string, unknown>) => {
    try {
      await apiPost(`/world/props/${enc}`, body)
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, onChanged, t, toast])

  const rotate = useCallback(async (axis: 'x' | 'y' | 'z') => {
    const cur = prop.rotation || {}
    try {
      await apiPost(`/world/props/${enc}/rotation`, {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0,
        [axis]: ((cur[axis] || 0) + 90) % 360,
      })
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [prop.rotation, enc, onChanged, t, toast])

  const setRotationAxis = useCallback(async (axis: 'x' | 'y' | 'z', raw: string) => {
    const n = parseFloat(raw)
    const v = Number.isFinite(n) ? ((n % 360) + 360) % 360 : 0
    if (v === (prop.rotation?.[axis] || 0)) return
    const cur = prop.rotation || {}
    try {
      await apiPost(`/world/props/${enc}/rotation`, {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0, [axis]: v,
      })
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [prop.rotation, enc, onChanged, t, toast])

  const upload = useCallback(async (file: File) => {
    if (!file) return
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`/world/props/${enc}/upload`, {
        method: 'POST', body: fd, credentials: 'same-origin',
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const errs: string[] = Array.isArray(body?.detail?.errors) ? body.detail.errors : []
        throw new Error(errs.length ? errs.join(' · ') : (body?.detail?.toString?.() || `HTTP ${res.status}`))
      }
      await onChanged()
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, onChanged, t, toast])

  // Object-local markers (A4) — same vocabulary as room markers, but the
  // frame is the object's own bounding box: `at` = [u, v, w] fractions
  // (0..1), `facing` = degrees. No click placement yet (deliberate) — the
  // fields are edited by hand. The clip vocabulary is the open one.
  const [clipKinds, setClipKinds] = useState<string[]>([])
  useEffect(() => {
    apiGet<{ kinds?: string[] }>('/assets/animation-clips')
      .then((d) => setClipKinds(d.kinds || []))
      .catch(() => setClipKinds([]))
  }, [])
  // Local draft, reset only on prop switch — a server reload after save must
  // not clobber an in-progress field edit.
  const [markers, setMarkers] = useState<PropMarker[]>(prop.markers || [])
  useEffect(() => { setMarkers(prop.markers || []) }, [prop.id])  // eslint-disable-line react-hooks/exhaustive-deps

  const saveMarkers = useCallback(async (next: PropMarker[]) => {
    setMarkers(next)
    try {
      await apiPost(`/world/props/${enc}/markers`, { markers: next })
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, onChanged, t, toast])

  const patchMarker = (i: number, patch: Partial<PropMarker>) =>
    saveMarkers(markers.map((m, idx) => (idx === i ? { ...m, ...patch } : m)))
  const setMarkerAt = (i: number, axis: 0 | 1 | 2, raw: string) => {
    const n = parseFloat(raw)
    const v = Number.isFinite(n) ? Math.min(Math.max(n, 0), 1) : 0
    const at = [...markers[i].at] as [number, number, number]
    at[axis] = Math.round(v * 10000) / 10000
    patchMarker(i, { at })
  }
  const addMarker = () =>
    saveMarkers([...markers, { animation: clipKinds[0] || 'idle', at: [0.5, 0, 0.5] }])
  const removeMarker = (i: number) => saveMarkers(markers.filter((_, idx) => idx !== i))

  const kindOptions = useMemo(() => {
    // Offer the open clip vocabulary plus any kind already used on this prop.
    const set = new Set<string>(clipKinds)
    for (const m of markers) if (m.animation) set.add(m.animation)
    return Array.from(set).sort()
  }, [clipKinds, markers])

  return (
    <div className="ga-form" style={{ gap: 8, padding: 10, borderRadius: 8,
      border: '1px solid var(--border, #30363d)' }}>
      <div className="ga-form-section-label">{prop.name}</div>
      {pending ? (
        <span className="ga-hint">{t('Generating the model — this takes a few minutes.')}</span>
      ) : null}
      {prop.has_model ? (
        <Model3DViewer
          url={`/assets/props/${enc}/model?v=${encodeURIComponent(prop.created_at || '')}-${cacheBump}`}
          format="glb"
          height={340}
          rotation={prop.rotation}
        />
      ) : (
        <div className="ga-empty">
          {t('No model yet — generate it or upload a GLB below.')}
        </div>
      )}

      {/* Orientation fix — ↻ adds +90°, the field sets a free exact angle. */}
      {prop.has_model ? (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          {(['x', 'y', 'z'] as const).map((axis) => (
            <span key={axis} style={{ display: 'inline-flex', gap: 2, alignItems: 'center' }}>
              <button type="button" className="ga-btn ga-btn-sm"
                onClick={() => { void rotate(axis) }} title={t('+90°')}>
                ↻ {axis.toUpperCase()}
              </button>
              <input
                key={`${axis}-${prop.rotation?.[axis] || 0}`}
                className="ga-input" type="number" min={-360} max={720} step={0.1}
                style={{ width: 64 }}
                defaultValue={prop.rotation?.[axis] || 0}
                title={t('Exact angle in degrees — free rotation for meshes that came out tilted.')}
                onBlur={(e) => { void setRotationAxis(axis, e.target.value) }}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
              />
            </span>
          ))}
          <span className="ga-hint">{t('Orientation fix — persisted; the 3D client applies it on load.')}</span>
        </div>
      ) : null}

      {/* Editable sidecar fields. */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label className="ga-field" style={{ flex: '0 0 150px' }}>
          <span className="ga-field-caption">{t('Category')}</span>
          <input className="ga-input" list="prop-category-options" value={categoryDraft}
            onChange={(e) => setCategoryDraft(e.target.value)}
            onBlur={() => { if (categoryDraft !== prop.category) void patch({ category: categoryDraft }) }} />
        </label>
        <label className="ga-field" style={{ flex: '0 0 120px' }}
          title={t('Largest real edge in metres.')}>
          <span className="ga-field-caption">{t('Size (m)')}</span>
          <input className="ga-input" type="number" min={0.05} step={0.05} value={sizeDraft}
            onChange={(e) => setSizeDraft(e.target.value)}
            onBlur={() => {
              const n = parseFloat(sizeDraft)
              if (Number.isFinite(n) && n > 0 && n !== prop.size_m) void patch({ size_m: n })
              else setSizeDraft(String(prop.size_m))
            }} />
        </label>
        <label className="ga-field" style={{ flex: '1 1 200px' }}>
          <span className="ga-field-caption">{t('Tags (comma-separated)')}</span>
          <input className="ga-input" value={tagsDraft}
            onChange={(e) => setTagsDraft(e.target.value)}
            onBlur={() => {
              if (tagsDraft !== prop.tags.join(', ')) void patch({ tags: tagsDraft })
            }} />
        </label>
      </div>

      {prop.prompt ? (
        <span className="ga-hint" style={{ fontSize: '0.78em' }} title={prop.prompt}>
          {prop.source === 'generated' ? t('Generated') : t('Source')}
          {prop.backend ? ` · ${prop.backend}` : ''} · {prop.prompt}
        </span>
      ) : null}

      {/* Object-local markers — a figure with a matching activity snaps to the
          spot in the object's own frame, so the marker travels with the prop
          into any room. `at` = [u, v, w] fractions of the model bounding box. */}
      <div className="ga-form-section-label" style={{ marginTop: 4 }}>{t('Markers')}</div>
      <span className="ga-hint">
        {t('Object-local spots a figure with a matching animation snaps to — they travel with the prop into any room. at = fraction of the model bounding box (u = width, v = height, w = depth, 0..1); facing in degrees (0 south, 90 east, 180 north, 270 west; empty = client default). Click placement in the viewer comes later.')}
      </span>
      {markers.length === 0 ? (
        <div className="ga-empty" style={{ fontSize: '0.85em' }}>{t('No markers yet.')}</div>
      ) : (
        markers.map((m, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint" style={{ minWidth: 20 }}>🎯 {i + 1}</span>
            <select
              className="ga-input"
              style={{ width: 130 }}
              value={m.animation}
              title={t('Animation kind — the open clip vocabulary, nothing hardcoded.')}
              onChange={(e) => patchMarker(i, { animation: e.target.value })}
            >
              {kindOptions.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            {(['u', 'v', 'w'] as const).map((axisLabel, ax) => (
              <label key={axisLabel} style={{ display: 'inline-flex', gap: 3, alignItems: 'center', fontSize: '0.8em' }}>
                {axisLabel}
                <input
                  key={`${axisLabel}-${m.at[ax]}`}
                  className="ga-input"
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  style={{ width: 62 }}
                  defaultValue={m.at[ax]}
                  onBlur={(e) => setMarkerAt(i, ax as 0 | 1 | 2, e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                />
              </label>
            ))}
            <label style={{ display: 'inline-flex', gap: 3, alignItems: 'center', fontSize: '0.8em' }}
              title={t('Facing in degrees — empty for the client default.')}>
              🧭
              <input
                key={`facing-${m.facing ?? ''}`}
                className="ga-input"
                type="number"
                min={0}
                max={359}
                step={1}
                style={{ width: 66 }}
                defaultValue={m.facing ?? ''}
                placeholder="—"
                onBlur={(e) => {
                  const raw = e.target.value.trim()
                  if (raw === '') { if (m.facing !== undefined) patchMarker(i, { facing: undefined }) }
                  else {
                    const n = parseInt(raw, 10)
                    patchMarker(i, { facing: Number.isFinite(n) ? ((n % 360) + 360) % 360 : undefined })
                  }
                }}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
              />
            </label>
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-danger"
              onClick={() => removeMarker(i)}
              title={t('Remove this marker')}
            >
              ×
            </button>
          </div>
        ))
      )}
      <div>
        <button type="button" className="ga-btn ga-btn-sm" onClick={addMarker}>
          + {t('Marker')}
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm"
          onClick={() => uploadRef.current?.click()}
          title={t('Upload a GLB as this prop’s 3D model.')}>
          ⬆ {t('Upload model')}
        </button>
        <input ref={uploadRef} type="file" accept=".glb" style={{ display: 'none' }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = '' }} />
        <button type="button" className="ga-btn ga-btn-sm ga-btn-danger"
          style={{ marginLeft: 'auto' }} onClick={onDelete}>
          {armedDelete ? t('Really delete?') : `🗑 ${t('Delete prop')}`}
        </button>
      </div>
    </div>
  )
}
