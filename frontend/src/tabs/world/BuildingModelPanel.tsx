/**
 * BuildingModelPanel — the 3D models of a location (building, AV3D-9) or of a
 * room (roomId set, AV3D-2), embedded in the respective editor tab (no modal).
 * Owns status/poll, generate (backend picker), upload and the persisted
 * per-model orientation fix. Like the image gallery, SEVERAL models can be
 * stored — the list below the viewer previews any of them, "Select" makes one
 * the ACTIVE model the 3D clients get; generation/upload auto-select their
 * new model. For buildings the viewer shows the world tile (2D map icon as
 * ground texture) with the model's declared real width (contract v6 Nr. 3 —
 * the plot-share dial map3d.size is gone) and NO placement yaw (v6 Nr. 10 —
 * the orientation fix is the only turn a building mesh has).
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MeshBackendDialog, type MeshBackend, type MeshGenerateOpts } from '../../components/MeshBackendDialog'
import {
  BuildDistanceMeshButton, DEFAULT_MODEL_TIER, ModelGalleryRow, NoModelRow,
  TierPicker, TierSummary,
  type BlenderStatus, type GalleryModel, type ModelTier,
} from '../../components/ModelGallery'
import { Model3DViewer } from '../characters/Model3DViewer'
import { notifyModel3dChanged } from './topDownSnapshot'
import type { Map3D, ScenePayload } from './worldTypes'
import { useActiveMeasure } from './measureKit'

export interface ModelEntry extends GalleryModel {
  /** Persisted 90°-step orientation fix — the 3D client applies it too. */
  rotation?: { x?: number; y?: number; z?: number }
  /** Vertical placement offset in metres (± — negative sinks the model). */
  offset_y?: number
  offset_x?: number
  offset_z?: number
  /** Walkable surface above the model bottom (m) — stand height of overlay
   *  zones on an area location. */
  walk_y?: number
  /** Real-size anchor of the model (0 = undeclared): the real width of its
   *  largest side. THE scale law for rooms AND buildings (v6 Nr. 3); an
   *  undeclared building falls back to the location's own width. */
  width_m?: number
}

export interface BuildingModelStatus {
  exists?: boolean
  pending?: boolean
  models?: ModelEntry[]
  backends?: MeshBackend[]
  /** mesh→mesh aliases (category mesh2mesh) — the "Create low variant"
   *  action. Empty = none configured, the action stays disabled. */
  shrink_backends?: MeshBackend[]
  default?: string
  /** The admin explicitly chose "no model" — distinct from "no files". */
  none_selected?: boolean
  /** The resolution tiers the subject actually has — a missing one is what
   *  the header badge reports. */
  tiers?: string[]
  /** Blender refinement state — the gate for the CPU distance-mesh action. */
  blender?: BlenderStatus
}

/** The declarative build description of a generated roof (schema v1,
 *  docs/llm-blender-models.md). Server-clamped on both ends of the wire. */
export interface RoofDescription {
  form: 'gable' | 'hip' | 'shed' | 'flat'
  pitch_deg: number
  overhang_m: number
  ridge_axis: 'auto' | 'x' | 'z'
  material: { tone: string; kind: 'shingle' | 'thatch' | 'metal' | 'tile' }
  gable_tone?: string
}

/** What the propose step knows before anything is built. */
interface RoofProposal {
  ok?: boolean
  llm?: boolean
  storeys?: number
  storey_height_m?: number
  eaves_height_m?: number
  footprint?: { source?: string; length_m?: number; depth_m?: number }
  description_json?: RoofDescription
}

const ROOF_FORMS: RoofDescription['form'][] = ['gable', 'hip', 'shed', 'flat']
const ROOF_KINDS: RoofDescription['material']['kind'][] =
  ['shingle', 'thatch', 'metal', 'tile']

// The plot-share dial (map3d.size, ]0, 1] of the extent) is GONE with
// contract v6 Nr. 3: a model scales through its declared real width in
// metres, and an undeclared one fills the location's own width — which is
// exactly what size = 1 used to produce.

interface BuildingModelPanelProps {
  locationId: string
  /** When set, the panel manages the ROOM models (AV3D-2) instead of the
   *  building: room routes, no map placement (a room's position comes from
   *  its floor-plan layout). */
  roomId?: string
  /** Ground texture for the tile — the location's current 2D map icon, if any. */
  mapIconUrl?: string
  /** Draft map3d — the panel READS the tile rotation to show the model the way
   *  the world will (the dial itself lives in the location's placement block). */
  map3d?: Map3D
  /** The server-composed scene of the current draft — the panel renders the
   *  building's placement spec out of it instead of computing its own. That
   *  is what makes the walk-height dial visible here: it moves `bottom_y`. */
  scene?: ScenePayload | null
  /** Tells the owner which stored model is previewed ('' = the active one)
   *  so the scene recipe is computed for that file. */
  onPreviewFileChange?: (filename: string) => void
  /** Source image picked via 🧊 in the gallery — opens the backend picker. */
  generateSource: string | null
  onGenerateSourceConsumed: () => void
}

export function BuildingModelPanel({
  locationId,
  roomId = '',
  mapIconUrl,
  map3d,
  scene,
  onPreviewFileChange,
  generateSource,
  onGenerateSourceConsumed,
}: BuildingModelPanelProps) {
  const { t } = useI18n()
  const { toast } = useToast()
  const buildingSpec = roomId ? null
    : (scene?.models || []).find((m) => m.role === 'building') || null
  // Which metre dial is being edited — drives the reference sizes in the
  // viewer (a number in real metres is guesswork without them).
  const { measure, bind: bindMeasure } = useActiveMeasure()
  const encLoc = encodeURIComponent(locationId)
  // Admin API base switches between building and room routes.
  const enc = roomId
    ? `${encLoc}/rooms/${encodeURIComponent(roomId)}`
    : encLoc
  const label = roomId ? t('3D room model') : t('3D building model')
  const [model3d, setModel3d] = useState<BuildingModelStatus | null>(null)
  // Which stored model the viewer shows ('' = follow the active one).
  const [preview, setPreview] = useState('')
  // Two-step delete per list entry (no window.confirm).
  const [armedDel, setArmedDel] = useState<string | null>(null)
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
        // A generation just finished. Only this panel knew — the adjust
        // strip, the floor-plan preview and the scene payload kept their
        // stale "no model yet" state until a full reload (user finding
        // 2026-07-28: "es wird dargestellt, aber einstellen kann man nicht").
        notifyModel3dChanged(roomId ? { roomId } : { locationId })
        return
      }
      if (n === 40) {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(tick, 15000)
      }
    }
    pollRef.current = setInterval(tick, 3000)
  }, [load, locationId, roomId])

  useEffect(() => {
    setArmedDel(null)
    setPreview('')
    load().then((d) => {
      if (d?.pending) startPoll()
    })
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [load, startPoll])

  // Fire the generation from the chosen backend + the gallery image picked via 🧊.
  const generate = useCallback(
    (backend: string, opts?: MeshGenerateOpts) => {
      const src = generateSource
      onGenerateSourceConsumed()
      if (!src) return
      void apiPost<{ status?: string }>(`/world/locations/${enc}/model3d/generate`,
        { source_image: src, backend,
          ...(opts?.face_num ? { face_num: opts.face_num } : {}),
          ...(opts?.texture_size ? { texture_size: opts.texture_size } : {}),
          ...(opts?.lod_faces ? { lod_faces: opts.lod_faces } : {}),
          ...(opts?.tier ? { tier: opts.tier } : {}) })
        .then((d) => {
          // already_running = double-click guard for the SAME image with the
          // SAME backend and tier; other images — and the same image through
          // another backend — queue up on the backend channel.
          toast(d?.status === 'already_running'
            ? t('This image is already being meshed with this backend — the model appears when it finishes.')
            : t('Generating the 3D model…'))
          setPreview('')
          startPoll()
        })
        .catch((e) => { toast(t('Error') + ': ' + (e as Error).message, 'error') })
    },
    [generateSource, onGenerateSourceConsumed, enc, startPoll, t, toast],
  )

  // Stored file waiting in the low-variant dialog (mesh→mesh reduction of
  // THAT file — not a fresh generation, so it has its own dialog instance and
  // its own backend list).
  const [shrinkFile, setShrinkFile] = useState<string | null>(null)
  const shrinkBackends = model3d?.shrink_backends || []
  const shrink = useCallback((backend: string, opts?: MeshGenerateOpts) => {
    const file = shrinkFile
    setShrinkFile(null)
    if (!file) return
    void apiPost<{ status?: string }>(`/world/locations/${enc}/model3d/shrink`,
      { file, backend,
        ...(opts?.face_num ? { face_num: opts.face_num } : {}),
        ...(opts?.texture_size ? { texture_size: opts.texture_size } : {}) })
      .then((d) => {
        toast(d?.status === 'already_running'
          ? t('This model is already being reduced.')
          : t('Creating the low variant…'))
        startPoll()
      })
      .catch((e) => { toast(t('Error') + ': ' + (e as Error).message, 'error') })
  }, [shrinkFile, enc, startPoll, t, toast])

  const models = model3d?.models || []
  const noneSelected = !!model3d?.none_selected
  const current = models.find((m) => m.filename === preview)
    || models.find((m) => m.active)
    || models[0]
  // A previewed NON-active model needs its own scene spec (its sidecar is
  // what the dials write to); previewing the active one = default.
  const previewedNonActive = current && !current.active ? current.filename : ''
  useEffect(() => { onPreviewFileChange?.(previewedNonActive) },
            [previewedNonActive, onPreviewFileChange])

  // Persisted orientation fix of the PREVIEWED model: generated meshes
  // come out arbitrarily oriented AND often slightly tilted — ↻ adds a
  // coarse +90°, the degree field sets a FREE exact angle per axis; the
  // viewer applies it live and the 3D client reads it from /model/meta.
  const setRotationAxis = useCallback(
    async (axis: 'x' | 'y' | 'z', raw: string) => {
      if (!current) return
      const n = parseFloat(raw)
      const v = Number.isFinite(n) ? ((n % 360) + 360) % 360 : 0
      if (v === (current.rotation?.[axis] || 0)) return
      const cur = current.rotation || {}
      try {
        const d = await apiPost<{ meta: { rotation?: ModelEntry['rotation'] } }>(
          `/world/locations/${enc}/model3d/rotation`,
          { x: cur.x || 0, y: cur.y || 0, z: cur.z || 0, [axis]: v,
            file: current.filename })
        setModel3d((prev) => (prev ? {
          ...prev,
          models: (prev.models || []).map((m) =>
            m.filename === current.filename ? { ...m, rotation: d.meta?.rotation } : m),
        } : prev))
        notifyModel3dChanged(roomId ? { roomId } : { locationId })
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [current, enc, locationId, roomId, t, toast],
  )

  const rotate = useCallback(
    async (axis: 'x' | 'y' | 'z') => {
      if (!current) return
      const cur = current.rotation || {}
      const next = {
        x: cur.x || 0, y: cur.y || 0, z: cur.z || 0,
        [axis]: ((cur[axis] || 0) + 90) % 360,
        file: current.filename,
      }
      try {
        const d = await apiPost<{ meta: { rotation?: ModelEntry['rotation'] } }>(
          `/world/locations/${enc}/model3d/rotation`, next)
        setModel3d((prev) => (prev ? {
          ...prev,
          models: (prev.models || []).map((m) =>
            m.filename === current.filename ? { ...m, rotation: d.meta?.rotation } : m),
        } : prev))
        notifyModel3dChanged(roomId ? { roomId } : { locationId })
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [current, enc, locationId, roomId, t, toast],
  )

  // Placement offsets of the PREVIEWED model — model properties like the
  // orientation fix: Y sinks/raises (socket thicknesses differ), X/Z shift
  // the model on the tile plane (world axes after the yaw: +x east,
  // +z south). Drafts in local fields, committed on blur/Enter.
  type OffsetKey = 'offset_y' | 'offset_x' | 'offset_z' | 'walk_y'
  const [offsetDrafts, setOffsetDrafts] = useState<Record<OffsetKey, string>>(
    { offset_y: '0', offset_x: '0', offset_z: '0', walk_y: '0' })
  useEffect(() => {
    setOffsetDrafts({
      offset_y: String(current?.offset_y ?? 0),
      offset_x: String(current?.offset_x ?? 0),
      offset_z: String(current?.offset_z ?? 0),
      walk_y: String(current?.walk_y ?? 0),
    })
  }, [current?.filename, current?.offset_y, current?.offset_x, current?.offset_z, current?.walk_y])
  const commitOffset = useCallback(async (key: OffsetKey) => {
    if (!current) return
    const v = parseFloat(offsetDrafts[key])
    if (!Number.isFinite(v) || v === (current[key] ?? 0)) {
      setOffsetDrafts((d) => ({ ...d, [key]: String(current[key] ?? 0) }))
      return
    }
    try {
      const d = await apiPost<{ meta: Partial<Record<OffsetKey, number>> }>(
        `/world/locations/${enc}/model3d/offset`,
        { [key]: v, file: current.filename })
      setModel3d((prev) => (prev ? {
        ...prev,
        models: (prev.models || []).map((m) =>
          m.filename === current.filename ? { ...m,
            offset_y: d.meta?.offset_y || 0,
            offset_x: d.meta?.offset_x || 0,
            offset_z: d.meta?.offset_z || 0,
            walk_y: d.meta?.walk_y || 0 } : m),
      } : prev))
      notifyModel3dChanged(roomId ? { roomId } : { locationId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [current, offsetDrafts, enc, locationId, roomId, t, toast])

  // The former "Model height (m)" and "Model storeys" dials are gone
  // (2026-07-28): both fed a Y-only scaling that no longer exists. A model is
  // scaled by ONE factor on all three axes, and since v6 Nr. 3 that factor
  // comes from the declared real width below — for buildings exactly as for
  // room dioramas. The storey height stays a location dial in real metres.

  const [widthDraft, setWidthDraft] = useState('')
  useEffect(() => {
    setWidthDraft(current?.width_m ? String(current.width_m) : '')
  }, [current?.filename, current?.width_m])
  const commitWidth = useCallback(async () => {
    if (!current) return
    const n = parseFloat(widthDraft)
    const widthM = Number.isFinite(n) && n > 0 ? n : 0
    if (widthM === (current.width_m || 0)) {
      setWidthDraft(current.width_m ? String(current.width_m) : '')
      return
    }
    try {
      const d = await apiPost<{ meta: { width_m?: number } }>(
        `/world/locations/${enc}/model3d/width`,
        { width_m: widthM, file: current.filename })
      setModel3d((prev) => (prev ? {
        ...prev,
        models: (prev.models || []).map((m) =>
          m.filename === current.filename ? { ...m, width_m: d.meta?.width_m || 0 } : m),
      } : prev))
      notifyModel3dChanged(roomId ? { roomId } : { locationId })
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [current, roomId, widthDraft, enc, locationId, t, toast])

  // Make a stored model the active one of a resolution tier (what the 3D
  // clients get for that tier).
  const select = useCallback(async (filename: string,
                                    tier: ModelTier = DEFAULT_MODEL_TIER) => {
    try {
      await apiPost(`/world/locations/${enc}/model3d/select`, { file: filename, tier })
      await load()
      notifyModel3dChanged(roomId ? { roomId } : { locationId })
      toast(t('Active model set'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, load, locationId, roomId, t, toast])

  const deleteModel = useCallback(async (filename: string) => {
    setArmedDel(null)
    try {
      await apiDelete(`/world/locations/${enc}/model3d?file=${encodeURIComponent(filename)}`)
      if (preview === filename) setPreview('')
      await load()
      notifyModel3dChanged(roomId ? { roomId } : { locationId })
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, preview, load, locationId, roomId, t, toast])

  // Upload a GLB as a NEW model of the chosen tier (validated; surface 422
  // reasons).
  const uploadRef = useRef<HTMLInputElement>(null)
  const [uploadTier, setUploadTier] = useState<ModelTier>(DEFAULT_MODEL_TIER)
  const upload = useCallback(async (file: File) => {
    if (!file) return
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('tier', uploadTier)
      const res = await fetch(`/world/locations/${enc}/model3d/upload`, {
        method: 'POST', body: fd, credentials: 'same-origin',
      })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const errs: string[] = Array.isArray(body?.detail?.errors) ? body.detail.errors : []
        throw new Error(errs.length ? errs.join(' · ') : (body?.detail?.toString?.() || `HTTP ${res.status}`))
      }
      setPreview('')
      await load()
      notifyModel3dChanged(roomId ? { roomId } : { locationId })
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, load, locationId, roomId, uploadTier, t, toast])

  // What an UNDECLARED building width falls back to: the location's own
  // width — the boundary's bounding box (scene.extent_m = plan_width_m).
  const boundaryWidthM = scene?.extent_m || map3d?.plan_width_m || 0

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
      <TierPicker value={uploadTier} onChange={setUploadTier} />
      <input
        ref={uploadRef}
        type="file"
        accept=".glb"
        style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = '' }}
      />
    </>
  )

  // The parametric way to a building model — buildings only: a room has no
  // outline of its own to roof, its walls ARE the building's.
  const roofBuilder = roomId ? null : (
    <RoofBuilder
      apiBase={enc}
      blender={model3d?.blender}
      pending={!!model3d?.pending}
      onStarted={startPoll}
    />
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
      showTier
      onGenerate={generate}
      onClose={onGenerateSourceConsumed}
    />
  )

  const shrinkPicker = (
    <MeshBackendDialog
      open={shrinkFile !== null}
      title={t('Create low variant')}
      hint={t('The stored mesh itself is reduced (mesh→mesh) — no new generation, no source image. The result becomes this gallery’s “low” model.')}
      backends={shrinkBackends}
      defaultBackend={shrinkBackends.length === 1 ? shrinkBackends[0].name : ''}
      defaultTextureSize={1024}
      generateLabel={t('Create')}
      onGenerate={shrink}
      onClose={() => setShrinkFile(null)}
    />
  )

  if (!current) {
    return (
      <div className="ga-form" style={{ gap: 6 }}>
        {picker}
        {shrinkPicker}
        <div className="ga-form-section-label">{label}</div>
        {model3d?.pending ? (
          <span className="ga-hint">{t('Generating the 3D model — this takes a few minutes.')}</span>
        ) : (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {/* Neutral, not a nag (E5 inventory 1a): a 3D model is optional
                polish, not a missing step. A location renders from its scene
                recipe and its props without one — the lake is the proof. The
                two ways to get one are still named, as an offer. */}
            <span className="ga-hint">
              {roomId
                ? t('No room model (optional). A room renders from its floor plan and its props; a diorama is polish — generate one from a gallery image assigned to this room (🧊 on a tile) or upload a GLB.')
                : t('No building model (optional). The location renders from its outline and its props; a model is polish — generate one from a building image (🧊 on a gallery tile below) or upload a GLB.')}
            </span>
            {uploadButton}
          </div>
        )}
        {model3d?.pending ? null : roofBuilder}
      </div>
    )
  }

  return (
    <div className="ga-form" style={{ gap: 6 }}>
      {picker}
      {shrinkPicker}
      <div className="ga-form-section-label">{label}</div>
      {model3d?.pending ? (
        <span className="ga-hint">{t('Generating a new model — the current one stays until it is done.')}</span>
      ) : null}
      <Model3DViewer
        url={`/world/locations/${enc}/model3d/files/${encodeURIComponent(current.filename)}?v=${encodeURIComponent(current.created_at || '')}`}
        format={current.format || 'glb'}
        height={380}
        rotation={current.rotation}
        offsetY={current.offset_y || 0}
        offsetX={current.offset_x || 0}
        offsetZ={current.offset_z || 0}
        groundTextureUrl={roomId ? undefined : mapIconUrl}
        placement={roomId
          // Rooms get a neutral ground plate as the zero level — without it
          // the height offset has no visible reference (the model just
          // floats centred). The real placement comes from the floor plan.
          ? { yawDeg: 0, size: 0.9, extentM: 10 }
          // Buildings render their SCENE SPEC: same square, same numbers as
          // the floor-plan preview, and the walk-height dial visibly moves
          // the model against the square (which is level 0).
          : { extentM: scene?.extent_m || map3d?.plan_width_m || 10,
            // No yaw of its own any more (v6 Nr. 10): the SPEC carries it,
            // and for a building that is constant 0 — the mesh is turned by
            // its orientation fix, the location by its anchor pin. The
            // viewer reads `spec.yaw_deg` wherever a spec is given anyway.
            spec: buildingSpec, yawDeg: 0,
            measure, k: scene?.k, planWidthM: map3d?.plan_width_m,
            storeyWorld: scene?.storey_m,
            storeyRealM: map3d?.storey_height_m || 3,
            figureHeightWorld: scene?.figures?.base_height_m_world }}
      />

      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
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
              key={`${axis}-${current.filename}-${current.rotation?.[axis] || 0}`}
              className="ga-input"
              type="number"
              min={-360}
              max={720}
              step={1}
              style={{ width: 62 }}
              defaultValue={current.rotation?.[axis] || 0}
              title={t('Exact angle in degrees — free rotation for meshes that came out tilted.')}
              onBlur={(e) => { void setRotationAxis(axis, e.target.value) }}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            />
          </span>
        ))}
        {/* Buildings only: a ROOM's height offset lives in the floor plan
            (layout.model_offset_y, adjust strip) — the sidecar setter
            rejects rooms, so no offset field is shown for them. */}
        {(roomId ? [] : [
          // An AREA location has no height offset: its model IS the terrain,
          // so its walkable surface belongs on the level-0 floor. Offering
          // the dial anyway let the ground drift to a level that does not
          // exist (Willowbrook's village square sat at basement height).
          ...(map3d?.area_model ? [] : [{
            key: 'offset_y' as const, label: t('Height offset (m)'),
            hint: t('Vertical: negative sinks the model into the terrain.'),
          }]),
          { key: 'offset_x' as const, label: t('Shift X (m)'),
            hint: t('Tile plane, world axes after the yaw: + = east.') },
          { key: 'offset_z' as const, label: t('Shift Z (m)'),
            hint: t('Tile plane, world axes after the yaw: + = south.') },
          { key: 'walk_y' as const, label: t('Walk height (m)'),
            hint: map3d?.area_model
              ? t('How high above the model’s lower edge the walkable ground lies, in REAL metres. THE dial of an area location: the ground always lands on the level-0 floor, so this value alone decides how deep the mesh hangs below it. Nothing measures it — set the calibration figure on the visible ground.')
              : t('How high above the model’s lower edge a figure stands, in REAL metres. Nothing measures it; 0 = the lower edge itself.') },
        ]).map(({ key, label, hint }) => (
          <label key={key} title={hint}
            style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}>
            {label}
            <input
              className="ga-input"
              type="number"
              step={0.05}
              style={{ width: 90 }}
              value={offsetDrafts[key]}
              onChange={(e) => setOffsetDrafts((d) => ({ ...d, [key]: e.target.value }))}
              onFocus={(key === 'walk_y' || key === 'offset_y')
                ? bindMeasure(key).onFocus : undefined}
              onBlur={(e) => {
                if (key === 'walk_y' || key === 'offset_y') bindMeasure(key).onBlur()
                void commitOffset(key)
                void e
              }}
              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
            />
          </label>
        ))}
        {/* THE scale dial (contract v6 Nr. 3), for rooms AND buildings: the
            model's largest side in real metres, dialled against the 1.70 m
            reference figure in the viewer — never a fraction of anything.
            Undeclared, a building falls back to the location's own width. */}
        <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em' }}
          title={roomId
            ? t('Estimated real-world width of the room (largest side, from the source image, e.g. 6). Placement is unchanged — the value sets the room’s content scale, and figures in the room size themselves from it automatically.')
            : t('Real-world width of the building in metres (its largest side, measured after the yaw). Dial it against the 1.70 m reference figure. Empty = the location’s own width stands in.')}>
          {roomId ? t('Room width (m)') : t('Model width (m)')}
          <input
            className="ga-input"
            type="number"
            min={0}
            max={500}
            step={0.5}
            style={{ width: 72 }}
            value={widthDraft}
            placeholder={roomId || !(boundaryWidthM > 0)
              ? '—' : boundaryWidthM.toFixed(1)}
            {...(roomId ? {} : bindMeasure('model_width'))}
            onChange={(e) => setWidthDraft(e.target.value)}
            onBlur={(e) => {
              if (!roomId) bindMeasure('model_width').onBlur()
              void commitWidth()
              void e
            }}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          />
          {!roomId && !(current.width_m) && boundaryWidthM > 0 ? (
            <span className="ga-hint">
              {t('undeclared — boundary width {n} m')
                .replace('{n}', boundaryWidthM.toFixed(1))}
            </span>
          ) : null}
        </label>
        <span className="ga-hint">
          {t('Orientation fix + height offset of the shown model — persisted; negative sinks it into the terrain, the 3D client applies both.')}
        </span>
      </div>

      {/* "Rotation on tile (°)" used to stand here, then moved to the
          location's own placement block — and is GONE altogether with v6
          Nr. 10: it turned the mesh around the very axis the orientation fix
          above already turns. One axis, one dial.

          The former "Size (fraction of the extent)" dial is gone as well
          (v6 Nr. 3): a model states its real width in metres up in the model
          row, like every other model in the contract. An AREA location said
          so already — its model IS the place and fills the whole extent. */}
      {!roomId && map3d?.area_model ? (
        <span className="ga-hint" style={{ fontSize: '0.82em' }}>
          {t('Area location: the model IS the ground — the height offset does not apply. Set the extent on the floor plan, the model width and the walk height above.')}
        </span>
      ) : null}

      {/* Stored models — like the image gallery: click previews, the tier
          buttons make a file the model the 3D clients get for that tier. */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <TierSummary tiers={model3d?.tiers} />
        {/* The CPU way to the missing low mesh — no backend, no queue, and
            the only one that works without a mesh→mesh alias. The endpoint
            follows `enc`, so this one button covers building AND room. */}
        {(model3d?.tiers || []).includes('full') ? (
          <BuildDistanceMeshButton
            url={`/world/locations/${enc}/model3d/lod`}
            hasLow={(model3d?.tiers || []).includes('low')}
            blender={model3d?.blender}
            disabled={!!model3d?.pending}
            onDone={async () => {
              await load()
              notifyModel3dChanged(roomId ? { roomId } : { locationId })
            }}
          />
        ) : null}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {models.length > 0 ? (
          <NoModelRow noneSelected={noneSelected} onSelect={() => { void select('') }} />
        ) : null}
        {models.map((m) => (
          <ModelGalleryRow
            key={m.filename}
            model={m}
            shown={m.filename === current.filename}
            armedDelete={armedDel === m.filename}
            onPreview={() => setPreview(m.filename)}
            onSelect={(tier) => { void select(m.filename, tier) }}
            onArmDelete={setArmedDel}
            onDelete={() => { void deleteModel(m.filename) }}
            onShrink={() => setShrinkFile(m.filename)}
            shrinkAvailable={shrinkBackends.length > 0}
            shrinkPending={!!model3d?.pending}
          />
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {uploadButton}
        <span className="ga-hint">
          {t('Generate more models via 🧊 on a gallery tile — new ones become the active model of their target tier.')}
        </span>
      </div>
      {roofBuilder}
    </div>
  )
}

/**
 * THE GENERATED ROOF (docs/llm-blender-models.md) — parametric geometry over
 * the outline the location already has, instead of image-to-3D.
 *
 * PROPOSE, THEN BUILD, deliberately in two steps: the LLM picks a form and the
 * user SEES those numbers and may change every one of them before a single
 * vertex exists. Nothing here happens silently, and a build with the LLM
 * unrouted is still a working feature — the proposal is simply the default
 * gable then (the panel says which of the two it is showing).
 */
function RoofBuilder({ apiBase, blender, pending, onStarted }: {
  apiBase: string
  blender?: BlenderStatus
  pending: boolean
  onStarted: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [proposal, setProposal] = useState<RoofProposal | null>(null)
  const [desc, setDesc] = useState<RoofDescription | null>(null)

  // Blender builds the roof locally — without it the button would only ever
  // produce a 503, so it is not offered (the distance-mesh action next to it
  // is gated the same way).
  if (!blender?.usable) return null

  const patch = (part: Partial<RoofDescription>) =>
    setDesc((d) => (d ? { ...d, ...part } : d))

  const propose = async () => {
    setBusy(true)
    try {
      const d = await apiPost<RoofProposal>(`/world/locations/${apiBase}/roof/propose`, {})
      setProposal(d)
      setDesc(d.description_json || null)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const build = async () => {
    if (!desc) return
    setBusy(true)
    try {
      const d = await apiPost<{ status?: string }>(
        `/world/locations/${apiBase}/roof/generate`, { description: desc })
      toast(d?.status === 'already_running'
        ? t('A roof is already being built for this location.')
        : t('Building the roof…'))
      setProposal(null)
      setDesc(null)
      onStarted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const row: CSSProperties = {
    display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: '0.82em',
  }
  const fp = proposal?.footprint || {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          className="ga-btn ga-btn-sm"
          disabled={busy || pending}
          onClick={() => { void propose() }}
          title={t('Build a roof onto the location’s outline — parametric geometry, not image-to-3D. The LLM proposes form, pitch and material; you edit them before the build.')}
        >
          🏠 {t('Generate roof (LLM)')}
        </button>
        <span className="ga-hint">
          {t('The roof is built from the outline and the storey height. It is stored as a roof-only building model — the walls of the scene recipe stay visible underneath it.')}
        </span>
      </div>

      {desc ? (
        <div className="ga-form" style={{ gap: 6, padding: 8,
          border: '1px solid var(--ga-border, #444)', borderRadius: 6 }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: '0.82em' }}>
            <span>{t('Footprint')}: {fp.length_m ?? '?'} × {fp.depth_m ?? '?'} m
              {' '}({t('from')} {fp.source || '?'})</span>
            <span>{t('Storeys')}: {proposal?.storeys ?? '?'}</span>
            <span>{t('Eaves height')}: {proposal?.eaves_height_m ?? '?'} m</span>
            <span className="ga-hint">
              {proposal?.llm ? t('proposed by the LLM') : t('default — no LLM answer')}
            </span>
          </div>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <label style={row} title={t('Gable = two slopes with a ridge · hip = four slopes · shed = one slope · flat = a slab.')}>
              {t('Form')}
              <select className="ga-input" value={desc.form}
                onChange={(e) => patch({ form: e.target.value as RoofDescription['form'] })}>
                {ROOF_FORMS.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </label>
            <label style={row} title={t('Slope of the roof surface against the horizontal. A flat roof has none.')}>
              {t('Pitch (°)')}
              <input
                type="range" min={5} max={60} step={1}
                style={{ width: 110 }}
                disabled={desc.form === 'flat'}
                value={desc.pitch_deg}
                onChange={(e) => patch({ pitch_deg: parseFloat(e.target.value) })}
              />
              <span style={{ width: 26, textAlign: 'right' }}>
                {desc.form === 'flat' ? '—' : desc.pitch_deg}
              </span>
            </label>
            <label style={row} title={t('How far the eaves stick out past the wall, in metres.')}>
              {t('Overhang (m)')}
              <input
                className="ga-input" type="number" min={0} max={1} step={0.05}
                style={{ width: 72 }}
                value={desc.overhang_m}
                onChange={(e) => patch({ overhang_m: parseFloat(e.target.value) || 0 })}
              />
            </label>
            <label style={row} title={t('Auto runs the ridge along the long side of the footprint.')}>
              {t('Ridge')}
              <select className="ga-input" value={desc.ridge_axis}
                onChange={(e) => patch({ ridge_axis: e.target.value as RoofDescription['ridge_axis'] })}>
                {(['auto', 'x', 'z'] as const).map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </label>
            <label style={row} title={t('The look of the roofing — it sets the surface roughness.')}>
              {t('Material')}
              <select className="ga-input" value={desc.material.kind}
                onChange={(e) => patch({ material: { ...desc.material,
                  kind: e.target.value as RoofDescription['material']['kind'] } })}>
                {ROOF_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </label>
            <label style={row} title={t('Roof colour — the weathered surface, not a paint chip.')}>
              {t('Tone')}
              <input
                type="color"
                value={desc.material.tone}
                onChange={(e) => patch({ material: { ...desc.material, tone: e.target.value } })}
              />
            </label>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="ga-btn ga-btn-sm" disabled={busy || pending}
              onClick={() => { void build() }}>
              {t('Build roof')}
            </button>
            <button className="ga-btn ga-btn-sm" disabled={busy}
              onClick={() => { setProposal(null); setDesc(null) }}>
              {t('Cancel')}
            </button>
            <span className="ga-hint">
              {t('The result becomes the active building model of this location (roof only) and is served to the 3D clients like any other.')}
            </span>
          </div>
        </div>
      ) : null}
    </div>
  )
}
