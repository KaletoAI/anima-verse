/**
 * BuildingModelPanel — the location's 3D building model (AV3D-9), embedded in
 * the location editor's "3D world" tab (no modal). Owns status/poll, generate
 * (backend picker), upload, delete and the persisted orientation fix — moved
 * here from LocationGallery — and adds the map placement: the viewer shows
 * the world tile (2D map icon as ground texture) with the model on it, and
 * yaw + size are edited live and stored in map3d.rotation / map3d.size
 * (the fields the 3D client reads from the worldmap, schnittstellen-3d.md).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MeshBackendDialog, type MeshBackend } from '../../components/MeshBackendDialog'
import { Model3DViewer } from '../characters/Model3DViewer'
import type { Map3D } from './worldTypes'

export interface BuildingModelStatus {
  exists?: boolean
  pending?: boolean
  meta?: {
    source_image?: string
    backend?: string
    created_at?: string
    format?: string
    /** Persisted 90°-step orientation fix — the 3D client applies it too. */
    rotation?: { x?: number; y?: number; z?: number }
  }
  backends?: MeshBackend[]
  default?: string
}

/** Client default when map3d.size is unset (schnittstellen-3d.md). */
const DEFAULT_TILE_SIZE = 0.92

interface BuildingModelPanelProps {
  locationId: string
  /** When set, the panel manages the ROOM model (AV3D-2) instead of the
   *  building: room routes + /play/rooms model URL, no map placement (a
   *  room's position comes from its floor-plan layout). */
  roomId?: string
  /** Ground texture for the tile — the location's current 2D map icon, if any. */
  mapIconUrl?: string
  /** Draft map3d — rotation/size are read from and written into it (building only). */
  map3d?: Map3D
  /** The 2D icon rotation: the client's yaw fallback when map3d.rotation is unset. */
  fallbackYawDeg?: number
  /** Write a placement field into the draft (undefined removes = back to default). */
  onMap3dField?: (key: 'rotation' | 'size', value: number | undefined) => void
  /** Source image picked via 🧊 in the gallery — opens the backend picker. */
  generateSource: string | null
  onGenerateSourceConsumed: () => void
}

export function BuildingModelPanel({
  locationId,
  roomId = '',
  mapIconUrl,
  map3d,
  fallbackYawDeg = 0,
  onMap3dField,
  generateSource,
  onGenerateSourceConsumed,
}: BuildingModelPanelProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const encLoc = encodeURIComponent(locationId)
  // Admin API base + client model URL switch between building and room.
  const enc = roomId
    ? `${encLoc}/rooms/${encodeURIComponent(roomId)}`
    : encLoc
  const modelUrl = roomId
    ? `/play/rooms/${encodeURIComponent(roomId)}/model`
    : `/play/locations/${encLoc}/model`
  const label = roomId ? t('3D room model') : t('3D building model')
  const [model3d, setModel3d] = useState<BuildingModelStatus | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    try {
      const d = await apiGet<BuildingModelStatus>(`/world/locations/${enc}/model3d/status`)
      setModel3d(d)
      return d
    } catch {
      setModel3d(null)
      return null
    }
  }, [enc])

  // Poll while the backend reports a running generation — the pending state is
  // derived from the polled status, never a local never-reset flag. Meshing
  // takes minutes and may queue behind other jobs, so there is NO give-up —
  // after ~2 min the poll merely slows down; the interval dies with the
  // component / on location switch.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    let n = 0
    const tick = async () => {
      n += 1
      const d = await load()
      if (!d?.pending) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = null
        return
      }
      if (n === 40) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(tick, 15000)
      }
    }
    pollRef.current = setInterval(tick, 3000)
  }, [load])

  useEffect(() => {
    setConfirmDel(false)
    load().then((d) => {
      if (d?.pending) startPoll()
    })
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [load, startPoll])

  // Fire the generation from the chosen backend + the gallery image picked via 🧊.
  const generate = useCallback(
    (backend: string) => {
      const src = generateSource
      onGenerateSourceConsumed()
      if (!src) return
      void apiPost(`/world/locations/${enc}/model3d/generate`, { source_image: src, backend })
        .then(() => { toast(t('Generating the 3D model…')); startPoll() })
        .catch((e) => { toast(t('Error') + ': ' + (e as Error).message, 'error') })
    },
    [generateSource, onGenerateSourceConsumed, enc, startPoll, t, toast],
  )

  // Persisted 90°-step orientation fix: generated meshes come out arbitrarily
  // oriented — each click rotates one axis by +90°, the viewer applies it live
  // and the 3D client reads it from /model/meta.
  const rotate = useCallback(
    async (axis: 'x' | 'y' | 'z') => {
      const cur = model3d?.meta?.rotation || {}
      const next = {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0,
        [axis]: ((cur[axis] || 0) + 90) % 360,
      }
      try {
        const d = await apiPost<{ meta: BuildingModelStatus['meta'] }>(
          `/world/locations/${enc}/model3d/rotation`, next)
        setModel3d((prev) => (prev ? { ...prev, meta: d.meta } : prev))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [model3d, enc, t, toast],
  )

  // Two-step delete (no window.confirm — in-app confirmation via button pair).
  const [confirmDel, setConfirmDel] = useState(false)
  const deleteModel = useCallback(async () => {
    setConfirmDel(false)
    try {
      await apiDelete(`/world/locations/${enc}/model3d`)
      await load()
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, load, t, toast])

  // Upload a GLB as the building model (validated; surface 422 reasons).
  const uploadRef = useRef<HTMLInputElement>(null)
  const upload = useCallback(async (file: File) => {
    if (!file) return
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`/world/locations/${enc}/model3d/upload`, {
        method: 'POST', body: fd, credentials: 'same-origin',
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const errs: string[] = Array.isArray(body?.detail?.errors) ? body.detail.errors : []
        throw new Error(errs.length ? errs.join(' · ') : (body?.detail?.toString?.() || `HTTP ${res.status}`))
      }
      await load()
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, load, t, toast])

  const yaw = map3d?.rotation
  const size = map3d?.size
  const effectiveYaw = yaw ?? fallbackYawDeg
  const effectiveSize = size ?? DEFAULT_TILE_SIZE

  const uploadButton = (
    <>
      <button
        className="ga-btn ga-btn-sm"
        onClick={() => uploadRef.current?.click()}
        title={roomId
          ? t('Upload a GLB as this room’s 3D model.')
          : t('Upload a GLB as the location’s 3D building model.')}
      >
        ⬆ {t('Upload model')}
      </button>
      <input
        ref={uploadRef}
        type="file"
        accept=".glb"
        style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = '' }}
      />
    </>
  )

  const picker = (
    <MeshBackendDialog
      open={generateSource !== null}
      title={roomId ? t('Generate 3D room model') : t('Generate 3D building model')}
      backends={model3d?.backends || []}
      defaultBackend={
        model3d?.default
          || ((model3d?.backends || []).length === 1 ? (model3d?.backends || [])[0].name : '')
      }
      onGenerate={generate}
      onClose={onGenerateSourceConsumed}
    />
  )

  if (!model3d?.exists) {
    return (
      <div className="ga-form" style={{ gap: 6 }}>
        {picker}
        <div className="ga-form-section-label">{label}</div>
        {model3d?.pending ? (
          <span className="ga-hint">{t('Generating the 3D model — this takes a few minutes.')}</span>
        ) : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="ga-hint">
              {roomId
                ? t('No model yet — generate it from a gallery image assigned to this room (🧊 on a tile) or upload a GLB.')
                : t('No model yet — generate it from a building image (🧊 on a gallery tile below) or upload a GLB.')}
            </span>
            {uploadButton}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      {picker}
      <div className="ga-form-section-label">{label}</div>
      {model3d.pending ? (
        <span className="ga-hint">{t('Generating a new model — the current one stays until it is done.')}</span>
      ) : null}
      <Model3DViewer
        url={`${modelUrl}?v=${encodeURIComponent(model3d.meta?.created_at || '')}`}
        format={model3d.meta?.format || 'glb'}
        height={380}
        rotation={model3d.meta?.rotation}
        groundTextureUrl={roomId ? undefined : mapIconUrl}
        placement={roomId ? undefined : { yawDeg: effectiveYaw, size: effectiveSize }}
      />

      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {(['x', 'y', 'z'] as const).map((axis) => (
          <button
            key={axis}
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={() => { void rotate(axis) }}
          >
            ↻ {axis.toUpperCase()} +90° ({model3d.meta?.rotation?.[axis] || 0}°)
          </button>
        ))}
        <span className="ga-hint">
          {t('Orientation fix — persisted; the 3D map client applies it too.')}
        </span>
      </div>

      {/* Map placement (map3d.rotation / map3d.size) — building only: a room
          gets its position from the floor-plan layout instead. Edits the
          LOCATION draft, so it is applied live in the viewer above but
          persisted via the location's Save button, like every other map3d
          field. */}
      {!roomId && onMap3dField ? (
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: '0.82em' }}>
          {t('Rotation on tile (°)')}
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input
              type="range"
              min={0}
              max={359}
              step={1}
              value={effectiveYaw}
              onChange={(e) => onMap3dField('rotation', parseInt(e.target.value, 10) || 0)}
              style={{ width: 140 }}
            />
            <input
              className="ga-input"
              type="number"
              min={0}
              max={359}
              style={{ width: 70 }}
              value={yaw ?? ''}
              placeholder={String(fallbackYawDeg)}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10)
                onMap3dField('rotation', Number.isFinite(n) ? ((n % 360) + 360) % 360 : undefined)
              }}
            />
            {yaw !== undefined ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => onMap3dField('rotation', undefined)}
                title={t('Back to default: follow the 2D icon rotation.')}
              >
                ↺
              </button>
            ) : null}
          </span>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: '0.82em' }}>
          {t('Size (fraction of tile)')}
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input
              type="range"
              min={0.05}
              max={1}
              step={0.01}
              value={effectiveSize}
              onChange={(e) => onMap3dField('size', parseFloat(e.target.value) || DEFAULT_TILE_SIZE)}
              style={{ width: 140 }}
            />
            <input
              className="ga-input"
              type="number"
              min={0.05}
              max={1}
              step={0.01}
              style={{ width: 70 }}
              value={size ?? ''}
              placeholder={String(DEFAULT_TILE_SIZE)}
              onChange={(e) => {
                const n = parseFloat(e.target.value)
                onMap3dField('size', Number.isFinite(n) && n > 0 && n <= 1 ? n : undefined)
              }}
            />
            {size !== undefined ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                onClick={() => onMap3dField('size', undefined)}
                title={t('Back to default ({n}).').replace('{n}', String(DEFAULT_TILE_SIZE))}
              >
                ↺
              </button>
            ) : null}
          </span>
        </label>
        <span className="ga-hint" style={{ paddingBottom: 4 }}>
          {t('Placement on the world tile — saved with the location.')}
        </span>
      </div>
      ) : null}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {model3d.meta?.source_image ? (
          <span className="ga-hint">
            {t('from')} {model3d.meta.source_image}
            {model3d.meta.backend ? ` · ${model3d.meta.backend}` : ''}
          </span>
        ) : null}
        {uploadButton}
        {confirmDel ? (
          <span style={{ display: 'inline-flex', gap: 6 }}>
            <button className="ga-btn ga-btn-sm ga-btn-danger" onClick={() => { void deleteModel() }}>
              {t('Delete the model?')}
            </button>
            <button className="ga-btn ga-btn-sm" onClick={() => setConfirmDel(false)}>
              {t('Cancel')}
            </button>
          </span>
        ) : (
          <button
            className="ga-btn ga-btn-sm ga-btn-danger"
            onClick={() => setConfirmDel(true)}
            title={t('Delete the 3D building model')}
          >
            🗑 {t('Delete model')}
          </button>
        )}
      </div>
    </div>
  )
}
