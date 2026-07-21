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
import { CATEGORY_DATALIST_ID } from './propTypes'
import type { PropFull, PropMarker } from './propTypes'

export function PropDetail({ prop, pending, cacheBump, onChanged, onDelete, armedDelete }: {
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
    <>
      <DetailToolbar
        title={prop.name}
        onDelete={onDelete}
        deleteLabel={armedDelete ? t('Really delete?') : t('Delete prop')}
        extra={
          <>
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
      <div className="ga-form">
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

        {/* Editable sidecar fields. */}
        <div className="ga-form-section-label">{t('Properties')}</div>
        <div className="ga-form-row">
          <Field label={t('Category')}>
            <input className="ga-input" list={CATEGORY_DATALIST_ID} value={categoryDraft}
              onChange={(e) => setCategoryDraft(e.target.value)}
              onBlur={() => { if (categoryDraft !== prop.category) void patch({ category: categoryDraft }) }} />
          </Field>
          <Field label={t('Size (m)')} compact hint={t('Largest real edge in metres.')}>
            <input className="ga-input" type="number" min={0.05} step={0.05} value={sizeDraft}
              style={{ width: 90 }}
              onChange={(e) => setSizeDraft(e.target.value)}
              onBlur={() => {
                const n = parseFloat(sizeDraft)
                if (Number.isFinite(n) && n > 0 && n !== prop.size_m) void patch({ size_m: n })
                else setSizeDraft(String(prop.size_m))
              }} />
          </Field>
          <Field label={t('Tags (comma-separated)')}>
            <input className="ga-input" value={tagsDraft}
              onChange={(e) => setTagsDraft(e.target.value)}
              onBlur={() => {
                if (tagsDraft !== prop.tags.join(', ')) void patch({ tags: tagsDraft })
              }} />
          </Field>
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
        <div className="ga-form-section-label">{t('Markers')}</div>
        <span className="ga-hint">
          {t('Object-local spots a figure with a matching animation snaps to — they travel with the prop into any room. at = fraction of the model bounding box (u = width, v = height, w = depth, 0..1); facing in degrees (0 south, 90 east, 180 north, 270 west; empty = client default). Click placement in the viewer comes later.')}
        </span>
        {markers.length === 0 ? (
          <div className="ga-empty" style={{ fontSize: '0.85em' }}>{t('No markers yet.')}</div>
        ) : (
          markers.map((m, i) => (
            <div key={i} className="ga-form-row">
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
      </div>
    </>
  )
}
