/**
 * RoomModelAdjust — compact adjustment strip for the SELECTED room's active
 * 3D model on the location's Floor-plan tab (AV3D-10 addendum): orientation
 * fix (↻ 90° per axis) + height offset in metres, persisted immediately on
 * the model's sidecar — no window switching while dialing a room in. The
 * full model management (list/select/upload) stays in the room editor's
 * 3D tab; the built-in preview re-reads the meta on its next model load.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { notifyModel3dChanged } from './topDownSnapshot'

interface ActiveModel {
  filename: string
  rotation?: { x?: number; y?: number; z?: number }
  offset_y?: number
  /** Real-world width estimate of the room's largest side (metres) —
   *  figures in the room derive their scale from it. */
  width_m?: number
  active?: boolean
}

export function RoomModelAdjust({ locationId, roomId, roomName,
                                  calibration = false, onCalibration }: {
  locationId: string
  roomId: string
  roomName: string
  /** Calibration figure showing in the 3D preview for THIS room. */
  calibration?: boolean
  onCalibration?: (on: boolean) => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = `${encodeURIComponent(locationId)}/rooms/${encodeURIComponent(roomId)}`
  const [model, setModel] = useState<ActiveModel | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [offsetDraft, setOffsetDraft] = useState('0')
  const [widthDraft, setWidthDraft] = useState('')

  useEffect(() => {
    let stale = false
    setLoaded(false)
    setModel(null)
    apiGet<{ models?: ActiveModel[] }>(`/world/locations/${enc}/model3d/status`)
      .then((d) => {
        if (stale) return
        const active = (d.models || []).find((m) => m.active) || (d.models || [])[0] || null
        setModel(active)
        setOffsetDraft(String(active?.offset_y ?? 0))
        setWidthDraft(active?.width_m ? String(active.width_m) : '')
        setLoaded(true)
      })
      .catch(() => { if (!stale) setLoaded(true) })
    return () => { stale = true }
  }, [enc])

  const setRotationAxis = useCallback(async (axis: 'x' | 'y' | 'z', raw: string) => {
    if (!model) return
    const n = parseFloat(raw)
    const v = Number.isFinite(n) ? ((n % 360) + 360) % 360 : 0
    if (v === (model.rotation?.[axis] || 0)) return
    const cur = model.rotation || {}
    try {
      const d = await apiPost<{ meta: { rotation?: ActiveModel['rotation'] } }>(
        `/world/locations/${enc}/model3d/rotation`,
        { x: cur.x || 0, y: cur.y || 0, z: cur.z || 0, [axis]: v,
          file: model.filename })
      setModel((prev) => (prev ? { ...prev, rotation: d.meta?.rotation } : prev))
      notifyModel3dChanged({ roomId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [model, enc, roomId, t, toast])

  const rotate = useCallback(async (axis: 'x' | 'y' | 'z') => {
    if (!model) return
    const cur = model.rotation || {}
    const next = {
      x: cur.x || 0, y: cur.y || 0, z: cur.z || 0,
      [axis]: ((cur[axis] || 0) + 90) % 360,
      file: model.filename,
    }
    try {
      const d = await apiPost<{ meta: { rotation?: ActiveModel['rotation'] } }>(
        `/world/locations/${enc}/model3d/rotation`, next)
      setModel((prev) => (prev ? { ...prev, rotation: d.meta?.rotation } : prev))
      notifyModel3dChanged({ roomId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [model, enc, roomId, t, toast])

  const commitWidth = useCallback(async () => {
    if (!model) return
    const n = parseFloat(widthDraft)
    const v = Number.isFinite(n) && n > 0 ? n : 0
    if (v === (model.width_m || 0)) {
      setWidthDraft(model.width_m ? String(model.width_m) : '')
      return
    }
    try {
      const d = await apiPost<{ meta: { width_m?: number } }>(
        `/world/locations/${enc}/model3d/width`,
        { width_m: v, file: model.filename })
      setModel((prev) => (prev ? { ...prev, width_m: d.meta?.width_m || 0 } : prev))
      notifyModel3dChanged({ roomId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [model, widthDraft, enc, roomId, t, toast])

  const commitOffset = useCallback(async () => {
    if (!model) return
    const v = parseFloat(offsetDraft)
    if (!Number.isFinite(v) || v === (model.offset_y ?? 0)) {
      setOffsetDraft(String(model.offset_y ?? 0))
      return
    }
    try {
      const d = await apiPost<{ meta: { offset_y?: number } }>(
        `/world/locations/${enc}/model3d/offset`,
        { offset_y: v, file: model.filename })
      setModel((prev) => (prev ? { ...prev, offset_y: d.meta?.offset_y || 0 } : prev))
      notifyModel3dChanged({ roomId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [model, offsetDraft, enc, roomId, t, toast])

  if (!loaded) return null
  if (!model) {
    return (
      <span className="ga-hint">
        {t('{name}: no room model yet — generate one in the room editor’s 3D tab.')
          .replace('{name}', roomName)}
      </span>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="ga-hint" style={{ fontWeight: 600 }}>{roomName}:</span>
      {(['x', 'y', 'z'] as const).map((axis) => (
        <span key={axis} style={{ display: 'inline-flex', gap: 2, alignItems: 'center' }}>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={() => { void rotate(axis) }}
            title={t('+90°')}
          >
            ↻ {axis.toUpperCase()}
          </button>
          <input
            key={`${axis}-${model.filename}-${model.rotation?.[axis] || 0}`}
            className="ga-input"
            type="number"
            min={-360}
            max={720}
            step={1}
            style={{ width: 58 }}
            defaultValue={model.rotation?.[axis] || 0}
            title={t('Exact angle in degrees — free rotation for meshes that came out tilted.')}
            onBlur={(e) => { void setRotationAxis(axis, e.target.value) }}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          />
        </span>
      ))}
      <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}>
        {t('Height offset (m)')}
        <input
          className="ga-input"
          type="number"
          step={0.05}
          style={{ width: 90 }}
          value={offsetDraft}
          onChange={(e) => setOffsetDraft(e.target.value)}
          onBlur={() => { void commitOffset() }}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
        />
      </label>
      <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Real-world width of the room (largest side). Calibrate it against the reference figure instead of estimating: the diorama scales by this value like a prop does, so furniture, props and NPCs in the room share ONE scale. The room rectangle no longer affects it.')}>
        {t('Room width (m)')}
        <input
          className="ga-input"
          type="number"
          min={0}
          max={500}
          step={0.5}
          style={{ width: 72 }}
          value={widthDraft}
          placeholder="—"
          onChange={(e) => setWidthDraft(e.target.value)}
          onBlur={() => { void commitWidth() }}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
        />
      </label>
      {onCalibration ? (
        <button
          type="button"
          className={`ga-btn ga-btn-sm${calibration ? ' ga-btn-primary' : ''}`}
          onClick={() => onCalibration(!calibration)}
          title={t('Calibration figure: puts a FIXED 1.70 m person into this room in the 3D preview. Dial "Room width (m)" until the furniture fits the figure, and the walkable floor height until it stands on the visible floor. Click inside the room on the 2D plan to move it; the spot is not saved.')}
        >
          🧍
        </button>
      ) : null}
      <span className="ga-hint">
        {t('Persisted on the active model — preview and 3D client pick it up.')}
      </span>
    </div>
  )
}
