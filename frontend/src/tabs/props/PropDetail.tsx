/**
 * PropDetail — detail panel of one prop: 3D viewer + persisted orientation
 * fix + the editable sidecar fields + object-local markers + GLB upload and
 * the armed two-step delete (both in the sticky toolbar).
 *
 * Markers are OBJECT-LOCAL (`at` = [u, v, w] fractions of the model bounding
 * box), so they travel with the prop into any room.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DetailToolbar } from '../../components/DetailToolbar'
import { Field } from '../../components/Field'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Model3DViewer } from '../characters/Model3DViewer'
import { orientedDims } from './dims'
import { CATEGORY_DATALIST_ID } from './propTypes'
import type { PropFull, PropMarker } from './propTypes'

type DimKey = 'width_m' | 'depth_m' | 'height_m'

/** The three real dims in display order; `axis` indexes orientedDims(),
 *  which returns [width(x), height(y), depth(z)]. */
const DIM_FIELDS: Array<{ key: DimKey; label: string; axis: number }> = [
  { key: 'width_m', label: 'Width (m)', axis: 0 },
  { key: 'depth_m', label: 'Depth (m)', axis: 2 },
  { key: 'height_m', label: 'Height (m)', axis: 1 },
]

// Marker `at` = fractions of the RAW box in the order [X, Y, Z] — mirrors
// props.MARKER_AT_MIN/MAX: half a box of slack per axis, because seats and
// lying surfaces sit ON the hull or just outside it.
const AT_MIN = -0.5
const AT_MAX = 1.5
// The height axis reaches a FULL box below (props.MARKER_AT_Y_MIN) — deep
// seat positions in tall machines sit far under the box top.
const AT_AXES: Array<{ label: string; dim: DimKey; min: number }> = [
  { label: 'X (width)', dim: 'width_m', min: AT_MIN },
  { label: 'Y (height)', dim: 'height_m', min: -1 },
  { label: 'Z (depth)', dim: 'depth_m', min: AT_MIN },
]
const MARKER_SAVE_DEBOUNCE_MS = 400

export function PropDetail({ prop, pending, cacheBump, onChanged, onDelete,
  armedDelete, onRegenerate, onRegenerateMesh, onRegenerateImage,
  onRefresh }: {
  prop: PropFull
  pending: boolean
  cacheBump: number
  onChanged: () => Promise<unknown>
  onDelete: () => void
  armedDelete: boolean
  /** Re-mesh the EXISTING source image (skips the image render). */
  onRegenerateMesh: () => void
  /** Re-run the source→mesh chain with the stored description/name. */
  onRegenerate: () => void
  /** Render a NEW source image only — the mesh stays until re-meshed. */
  onRegenerateImage: () => void
  /** Reload the prop + bust the image cache — generations run in the
   *  background, this fetches the current state on demand. */
  onRefresh: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(prop.id)
  const uploadRef = useRef<HTMLInputElement>(null)

  const [nameDraft, setNameDraft] = useState(prop.name)
  const [descDraft, setDescDraft] = useState(prop.description || '')
  const [categoryDraft, setCategoryDraft] = useState(prop.category)
  const [tagsDraft, setTagsDraft] = useState(prop.tags.join(', '))
  // The three real dims as string drafts — committed on blur/Enter, reverted
  // to the server value when the input is not a positive number.
  const [dims, setDims] = useState({
    width_m: String(prop.width_m), depth_m: String(prop.depth_m),
    height_m: String(prop.height_m),
  })
  // Drafts re-arm on PROP CHANGE only — the background poll reloads the
  // list every few seconds while a generation runs, and resetting on every
  // fresh object identity overwrote whatever the admin was typing (user
  // finding 2026-08-02: the description reverted mid-edit).
  useEffect(() => {
    setNameDraft(prop.name)
    setDescDraft(prop.description || '')
    setCategoryDraft(prop.category)
    setTagsDraft(prop.tags.join(', '))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prop.id])
  // The dims drafts sync separately WITH guards: after a commit the server
  // echoes the values back through onChanged(), and blindly resetting here
  // stomped whatever the admin was already typing in the next field (fast
  // edits scrambled the trio). Skip the reset while a dims input is focused
  // and when the incoming values are just our own commit coming back.
  const dimsEditingRef = useRef(false)
  const sentDimsRef = useRef('')
  const propIdRef = useRef(prop.id)
  useEffect(() => {
    const incoming = {
      width_m: String(prop.width_m), depth_m: String(prop.depth_m),
      height_m: String(prop.height_m),
    }
    const idChanged = propIdRef.current !== prop.id
    propIdRef.current = prop.id
    if (!idChanged) {
      if (dimsEditingRef.current) return
      if (JSON.stringify(incoming) === sentDimsRef.current) return
    }
    sentDimsRef.current = ''
    setDims(incoming)
  }, [prop.id, prop.width_m, prop.depth_m, prop.height_m])

  // Proportional assist: editing one dim pulls the OTHER two along the model's
  // proportions — unless they were edited too ("pinned"). Pins and the live
  // box reset only when another prop is selected.
  const [pinned, setPinned] = useState<Record<DimKey, boolean>>({
    width_m: false, depth_m: false, height_m: false,
  })
  const [liveBbox, setLiveBbox] = useState<[number, number, number] | null>(null)
  // Source image beside the model (left pane of the split preview) — 404 =
  // uploaded prop without a render, the pane then shows a placeholder.
  const [srcOk, setSrcOk] = useState(true)
  useEffect(() => {
    setPinned({ width_m: false, depth_m: false, height_m: false })
    setLiveBbox(null)
  }, [prop.id])
  useEffect(() => { setSrcOk(true) }, [prop.id, cacheBump])

  // Per render, so turning the orientation fix updates the suggestions live —
  // the viewer's measured box wins over the stored one.
  const bbox = liveBbox ?? prop.bbox
  const ratios = bbox ? orientedDims(bbox, prop.rotation) : null

  const editDim = (field: typeof DIM_FIELDS[number], raw: string) => {
    setPinned((p) => ({ ...p, [field.key]: true }))
    setDims((d) => {
      const next = { ...d, [field.key]: raw }
      const n = parseFloat(raw)
      if (ratios && Number.isFinite(n) && n > 0 && ratios[field.axis] > 0) {
        for (const other of DIM_FIELDS) {
          if (other.key === field.key || pinned[other.key]) continue
          const v = (n * ratios[other.axis]) / ratios[field.axis]
          // Suggestions round to 2 decimals — centimetre precision reads
          // honestly; the admin may still type finer values.
          next[other.key] = String(Math.round(v * 100) / 100)
        }
      }
      return next
    })
  }

  const patch = useCallback(async (body: Record<string, unknown>) => {
    try {
      await apiPost(`/world/props/${enc}`, body)
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, onChanged, t, toast])

  // Commit all three at once: an invalid field falls back to the server value,
  // and nothing is sent when the trio is unchanged.
  const commitDims = useCallback(() => {
    const next: Record<string, number> = {}
    let changed = false
    for (const { key } of DIM_FIELDS) {
      const n = parseFloat(dims[key])
      if (Number.isFinite(n) && n > 0) {
        next[key] = n
        if (n !== prop[key]) changed = true
      } else {
        next[key] = prop[key]
        setDims((d) => ({ ...d, [key]: String(prop[key]) }))
      }
    }
    if (changed) {
      sentDimsRef.current = JSON.stringify({
        width_m: String(next.width_m), depth_m: String(next.depth_m),
        height_m: String(next.height_m),
      })
      void patch(next)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dims, prop.width_m, prop.depth_m, prop.height_m, patch])

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
  // frame is the object's own bounding box: `at` = [u, v, w] fractions,
  // `facing` = degrees. The fractions may leave the box by half a box per
  // axis (seats sit ON the hull, see props.sanitize_markers). The clip
  // vocabulary is the open one.
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

  // Saving is DEBOUNCED (trailing): dragging a slider changes the state on
  // every frame, and one POST per frame would flood the route. The UI (and
  // the viewer, which reads `markers` live) stays immediate; the write
  // follows once the drag rests. Discrete edits (add/remove/click placement)
  // skip the wait.
  const markerTimer = useRef<number | null>(null)
  const markerPending = useRef<PropMarker[] | null>(null)
  const flushMarkers = useCallback(async () => {
    if (markerTimer.current !== null) {
      window.clearTimeout(markerTimer.current)
      markerTimer.current = null
    }
    const next = markerPending.current
    markerPending.current = null
    if (!next) return
    try {
      await apiPost(`/world/props/${enc}/markers`, { markers: next })
      await onChanged()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, onChanged, t, toast])
  const flushRef = useRef(flushMarkers)
  flushRef.current = flushMarkers
  // Unmount or a prop switch flushes what is still pending — with the flush
  // captured at SETUP time, so it posts to the prop the markers belong to.
  useEffect(() => {
    const flush = flushRef.current
    return () => { void flush() }
  }, [prop.id])

  const saveMarkers = useCallback((next: PropMarker[], immediate = false) => {
    setMarkers(next)
    markerPending.current = next
    if (immediate) {
      void flushMarkers()
      return
    }
    if (markerTimer.current !== null) window.clearTimeout(markerTimer.current)
    markerTimer.current = window.setTimeout(() => { void flushMarkers() },
                                            MARKER_SAVE_DEBOUNCE_MS)
  }, [flushMarkers])

  const patchMarker = (i: number, patch: Partial<PropMarker>, immediate = false) =>
    saveMarkers(markers.map((m, idx) => (idx === i ? { ...m, ...patch } : m)),
                immediate)
  const setMarkerAt = (i: number, axis: 0 | 1 | 2, raw: number | string) => {
    const n = typeof raw === 'number' ? raw : parseFloat(raw)
    const lo = AT_AXES[axis].min
    const v = Number.isFinite(n) ? Math.min(Math.max(n, lo), AT_MAX) : 0
    const at = [...markers[i].at] as [number, number, number]
    at[axis] = Math.round(v * 10000) / 10000
    patchMarker(i, { at })
  }
  const addMarker = () =>
    saveMarkers([...markers, { animation: clipKinds[0] || 'idle', at: [0.5, 0, 0.5] }],
                true)
  const removeMarker = (i: number) =>
    saveMarkers(markers.filter((_, idx) => idx !== i), true)

  // Floor-plan-style placement: arm ('add' or a marker index), then click the
  // mesh in the viewer — the hit lands as raw-box fractions. Esc disarms.
  const [placing, setPlacing] = useState<'add' | number | null>(null)
  useEffect(() => { setPlacing(null) }, [prop.id])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPlacing(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const onPickPoint = useCallback((at: [number, number, number]) => {
    setPlacing((cur) => {
      if (cur === 'add') {
        saveMarkers([...markers, { animation: clipKinds[0] || 'idle', at }], true)
      } else if (cur !== null && markers[cur]) {
        saveMarkers(markers.map((m, idx) => (idx === cur ? { ...m, at } : m)), true)
      }
      return null
    })
  }, [markers, clipKinds, saveMarkers])

  const kindOptions = useMemo(() => {
    // Offer the open clip vocabulary plus any kind already used on this prop.
    const set = new Set<string>(clipKinds)
    for (const m of markers) if (m.animation) set.add(m.animation)
    return Array.from(set).sort()
  }, [clipKinds, markers])

  return (
    <>
      <DetailToolbar
        title={prop.name}
        onDelete={onDelete}
        deleteLabel={armedDelete ? t('Really delete?') : t('Delete prop')}
        extra={
          <>
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={pending}
              onClick={onRegenerate}
              title={t('Re-render the source image from the stored description (name as fallback) and mesh it again — replaces the model, dims and markers stay.')}>
              🧊 {pending ? t('Generating…') : t('Regenerate')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm"
              onClick={() => uploadRef.current?.click()}
              title={t('Upload a GLB as this prop’s 3D model.')}>
              ⬆ {t('Upload model')}
            </button>
            <input ref={uploadRef} type="file" accept=".glb" style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = '' }} />
          </>
        }
      />
      <div className="ga-detail-cols">
        {/* Inputs: everything the sidecar stores. */}
        <div className="ga-form">
          {/* Editable sidecar fields. */}
          <div className="ga-form-section-label">{t('Properties')}</div>
          <div className="ga-form-row">
            <Field label={t('Name')}>
              <input className="ga-input" value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onBlur={() => {
                  const nm = nameDraft.trim()
                  if (nm && nm !== prop.name) void patch({ name: nm })
                  else setNameDraft(prop.name)
                }}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
            </Field>
            <Field label={t('Category')}>
              <input className="ga-input" list={CATEGORY_DATALIST_ID} value={categoryDraft}
                onChange={(e) => setCategoryDraft(e.target.value)}
                onBlur={() => { if (categoryDraft !== prop.category) void patch({ category: categoryDraft }) }} />
            </Field>
            <Field label={t('Tags (comma-separated)')}>
              <input className="ga-input" value={tagsDraft}
                onChange={(e) => setTagsDraft(e.target.value)}
                onBlur={() => {
                  if (tagsDraft !== prop.tags.join(', ')) void patch({ tags: tagsDraft })
                }} />
            </Field>
          </div>

          <Field label={t('Description (generation subject)')}
            hint={t('Feeds the render prompt when (re)generating — materials, colour, style. Empty = the name is used.')}>
            <textarea className="ga-textarea" rows={2} value={descDraft}
              onChange={(e) => setDescDraft(e.target.value)}
              onBlur={() => {
                if (descDraft.trim() !== (prop.description || ''))
                  void patch({ description: descDraft })
              }} />
          </Field>

          {/* Real size in metres — the mesh loses its scale, so the client sizes
              the object by these three values (after the orientation fix). */}
          <div className="ga-form-row">
            {DIM_FIELDS.map((field) => (
              <Field key={field.key} label={t(field.label)} compact>
                <input className="ga-input" type="number" min={0.01} step={0.05}
                  style={{ width: 90 }} value={dims[field.key]}
                  onFocus={() => { dimsEditingRef.current = true }}
                  onChange={(e) => editDim(field, e.target.value)}
                  onBlur={() => { dimsEditingRef.current = false; commitDims() }}
                  onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
              </Field>
            ))}
          </div>
          <span className="ga-hint">
            {ratios
              ? t('Linked to the model’s proportions — edit one value, the other two follow; a field you edited stays pinned until you switch props.')
              : t('No model box yet — enter all three by hand.')}
          </span>
          {prop.dims_estimated ? (
            <span className="ga-hint">
              {t('Estimated — refined automatically when the model arrives.')}
            </span>
          ) : null}

          {prop.prompt ? (
            <span className="ga-hint" style={{ fontSize: '0.78em' }} title={prop.prompt}>
              {prop.source === 'generated' ? t('Generated') : t('Source')}
              {prop.backend ? ` · ${prop.backend}` : ''} · {prop.prompt}
            </span>
          ) : null}

          {/* Object-local markers — a figure with a matching activity snaps to the
              spot in the object's own frame, so the marker travels with the prop
              into any room. `at` = [u, v, w] fractions of the model bounding box. */}
          <div className="ga-form-section-label">{t('Markers')}</div>
          <span className="ga-hint">
            {t('Object-local spots a figure with a matching animation snaps to — they travel with the prop into any room. at = fraction of the model bounding box (X = width, Y = height, Z = depth); the range reaches from -0.5 to 1.5, because seats and lying surfaces sit on the hull or just outside it. Place roughly with ✥, fine-tune with the sliders — the figure in the preview follows live.')}
          </span>
          {markers.length === 0 ? (
            <div className="ga-empty" style={{ fontSize: '0.85em' }}>{t('No markers yet.')}</div>
          ) : (
            markers.map((m, i) => (
              <div key={i} className="ga-marker-card">
                <div className="ga-form-row">
                  <span className="ga-hint" style={{ minWidth: 20 }}>🎯 {i + 1}</span>
                  <select
                    className="ga-input"
                    style={{ flex: 1, minWidth: 0 }}
                    value={m.animation}
                    title={t('Animation kind — the open clip vocabulary, nothing hardcoded.')}
                    onChange={(e) => patchMarker(i, { animation: e.target.value }, true)}
                  >
                    {kindOptions.map((k) => <option key={k} value={k}>{k}</option>)}
                  </select>
                  <button
                    type="button"
                    className={`ga-btn ga-btn-sm${placing === i ? ' ga-btn-primary' : ''}`}
                    onClick={() => setPlacing((cur) => (cur === i ? null : i))}
                    title={t('Then click the spot on the model in the viewer to move this marker there (Esc cancels).')}
                  >
                    ✥
                  </button>
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm ga-btn-danger"
                    onClick={() => removeMarker(i)}
                    title={t('Remove this marker')}
                  >
                    ×
                  </button>
                </div>
                {AT_AXES.map((axis, ax) => {
                  // Metres = fraction × the TYPED dim, so the seat height is
                  // directly dialable in real units.
                  const dimM = parseFloat(dims[axis.dim]) || prop[axis.dim]
                  return (
                    <div key={axis.label} className="ga-marker-axis">
                      <span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>
                        {t(axis.label)}
                      </span>
                      <input
                        type="range"
                        min={axis.min}
                        max={AT_MAX}
                        step={0.005}
                        value={m.at[ax]}
                        style={{ flex: 1, minWidth: 60 }}
                        onChange={(e) => setMarkerAt(i, ax as 0 | 1 | 2, e.target.valueAsNumber)}
                      />
                      <input
                        className="ga-input"
                        type="number"
                        min={axis.min}
                        max={AT_MAX}
                        step={0.005}
                        style={{ width: 72, flex: '0 0 auto' }}
                        value={m.at[ax]}
                        onChange={(e) => setMarkerAt(i, ax as 0 | 1 | 2, e.target.value)}
                      />
                      <span className="ga-hint" style={{ width: 58, flex: '0 0 auto', textAlign: 'right' }}
                        title={t('Fraction × the dimension typed above.')}>
                        {(m.at[ax] * dimM).toFixed(2)} m
                      </span>
                    </div>
                  )
                })}
                <div className="ga-marker-axis"
                  title={t('Facing in degrees: 0 south, 90 east, 180 north, 270 west. Unset = the client default (face the neighbours).')}>
                  <span className="ga-hint" style={{ width: 66, flex: '0 0 auto' }}>🧭 {t('Facing')}</span>
                  <input
                    type="range"
                    min={0}
                    max={360}
                    step={5}
                    value={m.facing ?? 0}
                    style={{ flex: 1, minWidth: 60 }}
                    onChange={(e) => patchMarker(i, {
                      facing: ((e.target.valueAsNumber % 360) + 360) % 360,
                    })}
                  />
                  <input
                    className="ga-input"
                    type="number"
                    min={0}
                    max={359}
                    step={1}
                    style={{ width: 72, flex: '0 0 auto' }}
                    value={m.facing ?? ''}
                    placeholder="—"
                    onChange={(e) => {
                      const raw = e.target.value.trim()
                      if (raw === '') { patchMarker(i, { facing: undefined }); return }
                      const n = parseInt(raw, 10)
                      patchMarker(i, {
                        facing: Number.isFinite(n) ? ((n % 360) + 360) % 360 : undefined,
                      })
                    }}
                  />
                  <button
                    type="button"
                    className="ga-btn ga-btn-sm"
                    style={{ width: 58, flex: '0 0 auto' }}
                    disabled={m.facing === undefined}
                    onClick={() => patchMarker(i, { facing: undefined }, true)}
                    title={t('Unset the facing — the client decides.')}
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))
          )}
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              className={`ga-btn ga-btn-sm${placing === 'add' ? ' ga-btn-primary' : ''}`}
              disabled={!prop.has_model}
              onClick={() => setPlacing((cur) => (cur === 'add' ? null : 'add'))}
              title={t('Then click the spot on the model in the viewer to drop a marker there (Esc cancels) — like placing markers on the floor plan.')}
            >
              🎯 {placing === 'add' ? t('Click the model…') : t('Place marker')}
            </button>
            <button type="button" className="ga-btn ga-btn-sm" onClick={addMarker}
              title={t('Add a marker at the box centre — position it with ✥ or the X/Y/Z sliders.')}>
              + {t('Marker')}
            </button>
          </div>
        </div>

        {/* Preview: the viewer plus the orientation fix that steers it —
            sticky, so it stays in view while a long marker list scrolls. */}
        <div className="ga-form ga-detail-cols-sticky">
          {pending ? (
            <span className="ga-hint">{t('Generating the model — this takes a few minutes.')}</span>
          ) : null}
          {/* Split preview: the SOURCE IMAGE the mesh came from on the left,
              the model on the right — and the image can be re-meshed
              directly (dialog picks backend / face count / texture size;
              the image render is skipped). */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'stretch', flexWrap: 'wrap' }}>
          <div style={{ flex: '0 1 220px', minWidth: 160, display: 'flex',
            flexDirection: 'column', gap: 4 }}>
            {srcOk ? (
              <img
                src={`/assets/props/${enc}/source?v=${encodeURIComponent(prop.created_at || '')}-${cacheBump}`}
                alt={t('Source image')}
                onError={() => setSrcOk(false)}
                style={{ width: '100%', flex: 1, maxHeight: 340,
                  objectFit: 'contain', borderRadius: 8,
                  border: '1px solid var(--border, #30363d)',
                  background: 'rgba(255,255,255,0.04)' }}
              />
            ) : (
              <div className="ga-empty" style={{ flex: 1 }}>
                {t('No source image (uploaded model).')}
              </div>
            )}
            {/* Provenance of the CURRENT image: what it was generated with.
                Full prompt/negative in the tooltip — the caption stays one
                line. Uploaded/legacy images have no record and say so. */}
            {srcOk ? (
              <span className="ga-hint" style={{ fontSize: 10, lineHeight: '13px' }}
                title={prop.prompt
                  ? `${t('Prompt')}: ${prop.prompt}${prop.negative
                    ? `\n${t('Negative prompt')}: ${prop.negative}` : ''}`
                  : t('No generation record for this image.')}>
                {prop.backend_image
                  ? `🖼 ${prop.backend_image}${prop.source_generated_at
                    ? ` · ${prop.source_generated_at.slice(0, 10)}` : ''}`
                  : t('No generation record for this image.')}
              </span>
            ) : null}
            <div style={{ display: 'flex', gap: 4 }}>
              <button type="button" className="ga-btn ga-btn-sm"
                style={{ flex: 1 }}
                disabled={pending}
                onClick={onRegenerateImage}
                title={t('Render a NEW source image (backend and prompt in the dialog). The current 3D model stays until you re-mesh from the new image.')}>
                🖼 {pending ? t('Generating…') : t('New image')}
              </button>
              <button type="button" className="ga-btn ga-btn-sm"
                onClick={onRefresh}
                title={t('Reload — fetch the current image and metadata (the render runs in the background).')}>
                🔄
              </button>
            </div>
            <button type="button" className="ga-btn ga-btn-sm"
              disabled={pending || !srcOk}
              onClick={onRegenerateMesh}
              title={t('Mesh THIS image again — no new render; backend, face count and texture size come from the dialog. Dims and markers stay.')}>
              ⚙ {t('3D from this image')}
            </button>
          </div>
          <div style={{ flex: '1 1 260px', minWidth: 240 }}>
          {prop.has_model ? (
            <Model3DViewer
              url={`/assets/props/${enc}/model?v=${encodeURIComponent(prop.created_at || '')}-${cacheBump}`}
              format="glb"
              height={340}
              rotation={prop.rotation}
              onBounds={(b) => setLiveBbox(b.size)}
              markers={markers.map((m) => ({
                at: m.at, animation: m.animation, facing: m.facing,
              }))}
              dimsOverlay={{
                width_m: parseFloat(dims.width_m) || prop.width_m,
                depth_m: parseFloat(dims.depth_m) || prop.depth_m,
                height_m: parseFloat(dims.height_m) || prop.height_m,
              }}
              // 1.7 m in MESH units — real prop scale = max dim over the raw
              // box's largest edge; the preview figure sizes itself to that.
              figureHeight={(() => {
                const bb = liveBbox ?? prop.bbox
                if (!bb) return 0
                const maxExtent = Math.max(bb[0], bb[1], bb[2])
                const maxDim = Math.max(
                  parseFloat(dims.width_m) || prop.width_m,
                  parseFloat(dims.depth_m) || prop.depth_m,
                  parseFloat(dims.height_m) || prop.height_m) || 1
                return 1.7 * (maxExtent / maxDim)
              })()}
              picking={placing !== null}
              onPickPoint={onPickPoint}
            />
          ) : (
            <div className="ga-empty">
              {t('No model yet — generate it or upload a GLB below.')}
            </div>
          )}
          </div>
          </div>

          {/* Orientation fix — ↻ adds +90°, the field sets a free exact angle. */}
          {prop.has_model ? (
            <>
              <div className="ga-form-section-label">{t('Orientation fix')}</div>
              <div className="ga-form-row">
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
              </div>
              <span className="ga-hint">{t('Orientation fix — persisted; the 3D client applies it on load.')}</span>
            </>
          ) : null}
        </div>
      </div>
    </>
  )
}
