/**
 * RoomModelAdjust — compact adjustment strip for the SELECTED room's active
 * 3D model on the location's Floor-plan tab (AV3D-10 addendum): orientation
 * fix (↻ 90° per axis) plus the two CALIBRATION anchors of the diorama —
 * its real width (which now sets the whole room's scale, § B2a) and the
 * walkable floor height a figure stands at. Both persist immediately on the
 * model's sidecar; the 🧍 toggle puts the fixed 1.70 m reference figure into
 * the room so they can be dialed against something. The walkable height is an
 * OVERRIDE — the server measures the diorama's floor out of the mesh and
 * offers that value as the field's placeholder (M6), so typing one is the
 * correction, not the rule. The height OFFSET is not
 * here — for rooms it lives in the plan (layout.model_offset_y). Full model
 * management (list/select/upload) stays in the room editor's 3D tab.
 */
import { useCallback, useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { notifyModel3dChanged } from './topDownSnapshot'

interface ActiveModel {
  filename: string
  rotation?: { x?: number; y?: number; z?: number }
  /** Real-world width estimate of the room's largest side (metres) —
   *  figures in the room derive their scale from it. */
  width_m?: number
  /** The walkable floor height (REAL metres above the model's lower edge) —
   *  stated by the admin, never measured. undefined = undeclared. */
  walk_y?: number
  active?: boolean
}

export function RoomModelAdjust({ locationId, roomId, roomName,
                                  calibration = false, onCalibration,
                                  calibrationAt, onCalibrationAt,
                                  roomSizeM }: {
  locationId: string
  roomId: string
  roomName: string
  /** Calibration figure showing in the 3D preview for THIS room. */
  calibration?: boolean
  onCalibration?: (on: boolean) => void
  /** Where it stands — METRES from the room's min corner (contract v6 Nr. 2).
   *  Pure UI state, never persisted. */
  calibrationAt?: [number, number]
  onCalibrationAt?: (at: [number, number]) => void
  /** Size of the room in metres — the dials' range, since the position is a
   *  length now and not a ratio. */
  roomSizeM?: [number, number]
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = `${encodeURIComponent(locationId)}/rooms/${encodeURIComponent(roomId)}`
  const [model, setModel] = useState<ActiveModel | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [widthDraft, setWidthDraft] = useState('')
  const [walkDraft, setWalkDraft] = useState('')

  // ``meta`` is the ACTIVE model's sidecar — the only place that says what the
  // admin set by hand.
  const reload = useCallback((reset: boolean) => {
    let stale = false
    if (reset) {
      setLoaded(false)
      setModel(null)
    }
    apiGet<{ models?: ActiveModel[]; meta?: { walk_y?: number } }>(
      `/world/locations/${enc}/model3d/status`)
      .then((d) => {
        if (stale) return
        const found = (d.models || []).find((m) => m.active) || (d.models || [])[0] || null
        const active = found ? { ...found, walk_y: d.meta?.walk_y } : null
        setModel(active)
        setWidthDraft(active?.width_m ? String(active.width_m) : '')
        setWalkDraft(active?.walk_y === undefined ? '' : String(active.walk_y))
        setLoaded(true)
      })
      .catch(() => { if (!stale) setLoaded(true) })
    return () => { stale = true }
  }, [enc])

  useEffect(() => reload(true), [reload])

  // A model that appears while this strip is open (a generation finishing in
  // the room editor) has to reach it — otherwise the model renders and its
  // dials stay hidden until the page is reloaded.
  useEffect(() => {
    const onChanged = (e: Event) => {
      const det = (e as CustomEvent).detail as { roomId?: string } | undefined
      if (!det?.roomId || det.roomId === roomId) reload(false)
    }
    window.addEventListener('anima-model3d-changed', onChanged)
    return () => window.removeEventListener('anima-model3d-changed', onChanged)
  }, [roomId, reload])

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

  // Walkable floor height. Empty input = remove the override (0 is a MEANINGFUL
  // height here, so it must not be treated as "unset"); the server's measured
  // value then applies and shows as the placeholder.
  const commitWalkY = useCallback(async () => {
    if (!model) return
    const raw = walkDraft.trim()
    const v = raw === '' ? null : parseFloat(raw)
    if (v !== null && !Number.isFinite(v)) {
      setWalkDraft(model.walk_y === undefined ? '' : String(model.walk_y))
      return
    }
    if ((v ?? undefined) === model.walk_y) return
    try {
      const d = await apiPost<{ meta: { walk_y?: number } }>(
        `/world/locations/${enc}/model3d/walk_y`,
        { walk_y: v, file: model.filename })
      setModel((prev) => (prev ? { ...prev, walk_y: d.meta?.walk_y } : prev))
      notifyModel3dChanged({ roomId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [model, walkDraft, enc, roomId, t, toast])

  if (!loaded) return null
  // Neutral, not a nag (E5 inventory 1a): a room diorama is optional polish.
  // The room renders from its floor plan and its props without one, so the
  // empty state states a fact instead of asking for a generation.
  if (!model) {
    return (
      <span className="ga-hint">
        {t('{name}: no room diorama (optional).').replace('{name}', roomName)}
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
      <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
        title={t('Walkable floor height (m): how high above the model’s lower edge a figure actually stands, in REAL metres. Modelled floors (a podium, a sunken lounge, a hole in the mesh) cannot be read off a mesh, and nothing guesses it — switch on the calibration figure and dial until it stands on the visible floor. Empty = undeclared, 0 = the lower edge itself.')}>
        {t('Walkable floor (m)')}
        <input
          className="ga-input"
          type="number"
          min={0}
          max={50}
          step={0.05}
          style={{ width: 104 }}
          value={walkDraft}
          placeholder="—"
          onChange={(e) => setWalkDraft(e.target.value)}
          onBlur={() => { void commitWalkY() }}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
        />
      </label>
      {onCalibration ? (
        <button
          type="button"
          className={`ga-btn ga-btn-sm${calibration ? ' ga-btn-primary' : ''}`}
          onClick={() => onCalibration(!calibration)}
          title={t('Calibration figure: puts a FIXED 1.70 m person into this room in the 3D preview. Dial "Room width (m)" until the furniture fits the figure, and the walkable floor height until it stands on the visible floor. Move it with the X/Y dials or by clicking into the room on the 2D plan; the spot is not saved.')}
        >
          🧍
        </button>
      ) : null}
      {/* Where the figure stands — METRES from the room's min corner (v6
          Nr. 2). The click into the 2D plan stays, but it misses whenever a
          prop, a marker or an opening sits under the cursor — these always
          work. */}
      {calibration && onCalibrationAt ? (
        ([['x', 0] as const, ['y', 1] as const]).map(([axis, idx]) => {
          const span = roomSizeM?.[idx] || 0
          const mid = span / 2
          const cur = calibrationAt || [mid, roomSizeM ? roomSizeM[1] / 2 : 0]
          const set = (v: number) => onCalibrationAt(
            idx === 0 ? [v, cur[1]] : [cur[0], v])
          return (
            <label key={axis} style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: '0.82em' }}
              title={t('Position of the calibration figure in the room, in metres from its north-west corner.')}>
              {axis.toUpperCase()}
              <input
                type="range"
                min={0}
                max={span || 10}
                step={0.01}
                value={cur[idx]}
                onChange={(e) => set(Math.round(parseFloat(e.target.value) * 100) / 100)}
                style={{ width: 90 }}
              />
              <input
                className="ga-input"
                type="number"
                min={0}
                max={span || 10}
                step={0.01}
                style={{ width: 66 }}
                value={cur[idx]}
                onChange={(e) => set(
                  Math.round((parseFloat(e.target.value) || 0) * 100) / 100)}
              />
              <span style={{ opacity: 0.7 }}>m</span>
            </label>
          )
        })
      ) : null}
      <span className="ga-hint">
        {t('Persisted on the active model — preview and 3D client pick it up.')}
      </span>
    </div>
  )
}
