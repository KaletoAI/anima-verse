import { clearModel3DPanel, publishModel3DPanel, useModel3DPanel } from './model3dPanel'
import { previewMotionSliders } from './motionFieldPreview'
import { ExtensionMotionSliders } from './ExtensionMotionDraft'
import type { Physics } from '../../lib/motionDraft'
import type { SecondaryMotionPayload, ExtensionRigDeclaration, CollisionPayload } from '@anima/scene-render'
import { CollisionScales } from './CollisionScales'
/**
 * FieldModel3D — the character's 3D model for the current outfit. ONE model,
 * produced either way: GENERATE it from the T-pose render (mesh backend) or
 * UPLOAD a GLB/FBX. Both write the same per-outfit slot, so the animated
 * preview always shows the current model regardless of where it came from.
 * Rendered template-driven via the section flag `special: "model3d_gen"`.
 *
 * Backend: GET /characters/{n}/model3d (status), POST .../model3d/generate,
 * POST .../model3d/fetch-job (collect a finished gateway job by its id),
 * POST .../model3d/upload, POST .../model3d/rig, GET .../model3d/file (bytes),
 * DELETE .../model3d.
 *
 * Base-body pipeline (`st.pipeline`, server app/core/model3d_pipeline.py):
 * the outfit model is painted onto the rigged base body, so "Generate" is
 * "Rebuild from base body" (no mesh-backend dialog), re-rig acts on the base
 * body, and upload / "Fetch by job ID" / the upload rig label are not
 * offered (the server refuses them too).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MeshBackendDialog } from '../../components/MeshBackendDialog'
import { Model3DViewer } from './Model3DViewer'
import { ModelSteps } from './ModelSteps'
import { ModelFaceActions } from './ModelFaceActions'
import type { FaceCleanupState } from './ModelFaceActions'
import type { ModelStep } from './ModelSteps'
import type { Freshness } from './FreshnessBadge'
import { OutfitBatchDialog } from './OutfitBatchDialog'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'

/** What Blender measured in the actual geometry — as opposed to what the
 *  file's header claims. Absent until the model has been measured. */
interface Model3DMeasured {
  /** world-space bounding box [x, y, z] in metres */
  dims_m?: number[]
  /** lowest point; 0 means the model stands on the ground plane */
  min_z?: number
  tris?: number
  verts?: number
  bones?: number
  mixamo_bones?: number
  /** bones named as fingers — the Mixamo rig always carries its 30, so the
   *  count alone never says whether they were skinned */
  finger_bones?: number
  /** finger bones that actually drive mesh (own a vertex with weight >= 0.5);
   *  0 with finger_bones > 0 = the hands were rigged as one block */
  finger_bones_weighted?: number
  /** vertices driven by a finger bone, as stored */
  finger_verts?: number
  /** 0 with vertex_colors > 0 = colour lives in the vertices, no UVs */
  uv_layers?: number
  vertex_colors?: number
  at?: string
}

/** Geometry-defect indicators (display only). The suspect verdict needs all
 *  three markers together — each alone is a false-alarm generator, and the
 *  rule is calibrated on one known case. Nothing acts on this. */
interface Model3DDiagnosis {
  data?: {
    skin_spread_max?: number
    skin_spread_bone?: string
    bones_with_verts?: number
    tiny_parts?: number
    loose_parts?: number
  }
  flags?: { skin_spread?: boolean; bones_missing?: boolean; fragments?: boolean }
  suspect?: boolean
  at?: string
}

export interface ExtensionRigResult {
  status?: 'none_applicable' | 'not_found' | 'failed' | 'applied'
  reason?: string
  metrics?: Record<string, unknown>
  per_tier?: Record<string, ExtensionRigResult>
}

export interface Model3DInfo {
  attached_part?: { status: string; reason: string; protrusion_mm: number | null; warning: boolean }
  limb_weights?: { checked: boolean; vertices: number; fully_foreign: number; error: string }
  tpose_status?: 'current' | 'changed' | 'other_outfit' | 'unknown'
  head_twist?: { current: number | null; corrected: number | null }
  clips?: Record<string, { loop: boolean }>
  rig_metrics?: {
    fold?: Record<string, number>
    sym_max_pct?: number
    landmark_fallback?: string[]
    clips?: Record<string, { stretch_p999: number; contact_err_max: number; tail_min_z: number; ik_unreachable: number }>
  }
  face_retexture?: { photo?: { balance: number; skin_recolor?: number | { status: string; reason: string }; tone_match?: number; brightness: number; applied_on?: 'hub' | 'local' | 'none'; reason?: string }; reference?: 'face' | 'front'; status: string; reason?: string; error?: string; at?: string; backend?: string; job_id?: string; face_texture_lost?: boolean; dark_gate?: { ok?: boolean; retried?: boolean; retry_yaw?: number; chosen?: string; dark_share?: number; photo_dark_share?: number; warning?: string }; upscale?: { status: string; backend?: string; in?: number[]; out?: number[]; cached?: boolean; busy?: boolean; error?: string } }
  face_retexture_revert?: 'snapshot' | 'rerig' | null
  face_retexture_snapshot?: { ok: boolean; created_at?: string; error?: string }
  face_retexture_compare_url?: string
  model_rev?: string
  extension_rig?: ExtensionRigResult
  /** The served body's collision capsules (app/core/collision.py); null for
   *  a model that gets none. */
  collision?: CollisionPayload | null
  filename?: string
  /** signature of the SERVED file (nearest match: another combination's) */
  signature?: string
  /** how the served model was found: exact | neutral | nearest */
  match?: string
  /** Base-body pipeline: the served file was built on an older base body
   *  (or before the pipeline) — shown with all its details, plus a hint. */
  stale_base?: boolean
  /** The side overview of an outfit model on the base-body pipeline (server,
   *  app/core/model_overview.py); absent for a model of the old path, which
   *  keeps the overview built here. */
  steps?: ModelStep[]
  /** Current / outdated / no data — the viewer's corner badge. */
  freshness?: Freshness | null
  stale_reason?: 'older_base' | 'before_pipeline' | 'detail_changed' | 'mesh_item_ready'
  /** Base-body pipeline: the face belongs to the base body — the face
   *  dialog and its status act on this signature. */
  face_signature?: string
  format?: string
  rig?: string
  rig_error?: string
  size?: number
  url?: string
  texture_url?: string
  created_at?: string
  backend?: string
  mesh_backend?: string
  rig_backend?: string
  has_unrigged_source?: boolean
  unrigged_source_reason?: string
  /** gateway job id when the model was collected afterwards by that id */
  job_id?: string
  source?: string
  source_filename?: string
  /** what the rig stage was asked for when this model was generated; absent
   *  for uploads. The measurement says what it actually delivered. */
  measured?: Model3DMeasured
  diagnosis?: Model3DDiagnosis
  /** Resolutions that exist for this file: always 'full', plus 'low' once a
   *  reduced version has been built. */
  tiers?: string[]
  low_size?: number
  low_tris?: number
  low_ratio?: number
  refined?: { retexture: boolean; reason?: string; bytes_saved?: number; at?: string }
  lod_error?: string
}

interface MeshBackend {
  name: string
  model?: string
  cost?: number
  face_num?: number | null
  /** Hard ceiling of the face count (0/absent = none). */
  face_num_max?: number | null
  /** Alias can bake reduced LOD stages in the same job (from its schema). */
  lod_stages?: boolean
}

export interface Model3DStatus {
  motion?: SecondaryMotionPayload
  motion_defaults?: SecondaryMotionPayload['groups']
  signature?: string
  rig?: string
  has_input?: boolean
  model?: Model3DInfo | null
  options?: { auto_generate?: boolean; face_before_rig?: boolean; face_cleanup?: boolean; face_photo?: { balance?: number; skin_recolor?: number; tone_match?: number; brightness?: number };
    extension_rig_models?: Record<string, Record<string, { enabled?: boolean; flip?: boolean }>>;
    extension_motion?: Record<string, Physics & { bounce?: number; weight?: number }>
    collision_scales?: Record<string, number> }
  extension_groups?: ExtensionRigDeclaration[]
  rig_backends?: MeshBackend[]
  upscale_backends?: MeshBackend[]
  upscale_runnable?: boolean
  face_retexture_backends?: MeshBackend[]
  face_retexture_result?: { task_id: string; ok: boolean; error?: string }
  rerig_result?: { task_id: string; ok: boolean; error?: string }
  backends?: MeshBackend[]
  default?: string
  animation_set?: string
  animation_sets?: string[]
  animation_set_derived?: string
  pending?: boolean
  /** Base-body pipeline state; null/absent off the pipeline. */
  pipeline?: {
    base_signature: string
    /** status of the current base model: ready | running | failed | unrigged; null = none */
    base_model?: string | null
    /** the base model's unrigged source is retained — what a re-rig needs */
    rerig_source: boolean
    /** every dressed view of the current outfit matches the current base */
    dressed_current: boolean
    rebuilding: boolean
  } | null
  /** The face cleanup of the source the face acts on (the base body's on
   *  the pipeline) — server `model3d.face_cleanup_state`. */
  face_cleanup?: FaceCleanupState | null
  /** Local Blender install — decides whether measuring is offered at all. */
  blender?: { enabled?: boolean; executable?: string; version?: string; usable?: boolean }
}

export function FieldModel3D({ character, onOpenBaseBody }: {
  character: string
  /** Switches to the Base body tab (where the base body's face, rig and
   *  collision live on the pipeline). */
  onOpenBaseBody?: () => void
}) {
  // Subscribe to the shared clock settings so the stamps above re-render
  // once the server-configured format and timezone arrive.
  useClockSettings()
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [st, setSt] = useState<Model3DStatus>({})
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [analysisResults, setAnalysisResults] = useState<Array<{ message: string; error: boolean }>>([])
  const panel = useModel3DPanel(character)
  useEffect(() => () => clearModel3DPanel(character), [character])
  const [clip, setClip] = useState({ character: '', url: '' })
  const playSituation = useCallback((url: string) => setClip({ character, url }), [character])
  const [sliderPreview, setSliderPreview] = useState<{ context: string; groups: Record<string, Physics> }>({ context: '', groups: {} })
  const [previewState, setPreviewState] = useState('')
  const [previewFilters, setPreviewFilters] = useState<Array<{ id: string; label?: string; bone_pose?: Record<string, unknown> }>>([])
  const previewRef = useRef<HTMLDivElement>(null)
  const previewRequestRef = useRef(0)
  const previewContextRef = useRef('')
  previewContextRef.current = `${enc}:${previewState}`
  const previewStateRef = useRef(previewState)
  previewStateRef.current = previewState
  useEffect(() => {
    let cancelled = false
    apiGet<{ filters?: typeof previewFilters }>('/admin/prompt-filters/data')
      .then(data => { if (!cancelled) setPreviewFilters((data.filters || []).filter(row => Object.keys(row.bone_pose || {}).length > 0)) })
      .catch(() => { if (!cancelled) setPreviewFilters([]) })
    return () => { cancelled = true }
  }, [])

  // Bumped on every Analyze run and on a character switch: a run whose token is
  // no longer current must not write results into another character's panel.
  const analysisRunRef = useRef(0)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [pendingFbx, setPendingFbx] = useState<File | null>(null)
  // Which resolution the viewer shows — a VIEW state, never sent anywhere.
  const [viewTier, setViewTier] = useState<'full' | 'low'>('full')
  /** Slider preview of the collision scales (CollisionScales) — shown in the viewer instead of the stored set. */
  const [collisionPreview, setCollisionPreview] = useState<CollisionPayload | null>(null)
  // "Fetch by job ID": a mesh run that outlived our own poll is collected from
  // the gateway afterwards. jobErrors holds a failed model check, which the
  // admin may override with "Store anyway".
  const [jobOpen, setJobOpen] = useState(false)
  const [jobId, setJobId] = useState('')
  const [jobErrors, setJobErrors] = useState<string[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const texRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    if (!character) return
    const context = previewContextRef.current
    const selected = previewStateRef.current
    try {
      const d = await apiGet<Model3DStatus>(`/characters/${enc}/model3d${selected ? `?preview_states=${encodeURIComponent(selected)}` : ''}`)
      if (context !== previewContextRef.current) return
      setSt(d)
      return d
    } catch {
      if (context === previewContextRef.current) setSt({})
    }
  }, [character, enc])

  // Meshing takes minutes — poll until the backend reports it finished.
  const startPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    let n = 0
    pollRef.current = setInterval(async () => {
      n += 1
      const d = await load()
      if (!d?.pending || n >= 200) {
        if (pollRef.current) clearInterval(pollRef.current)
        setBusy(false)
      }
    }, 5000)
  }, [load])

  useEffect(() => {
    let cancelled = false
    setConfirmDelete(false)
    analysisRunRef.current += 1
    setAnalysisResults([])
    setJobOpen(false)
    setJobId('')
    setJobErrors([])
    // A fresh character carries no in-flight click from the previous one — the
    // local busy flag must not bleed across the switch (it would otherwise pin
    // "Generating…" on every character). The authoritative state is st.pending.
    setBusy(false)
    load().then((d) => {
      // Backend still meshing (switched in / reloaded mid-run)? Track it to
      // completion so the display clears on its own.
      if (!cancelled && d?.pending) startPoll()
    })
    return () => {
      cancelled = true
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [load, startPoll])

  useEffect(() => {
    let cancelled = false
    let visible = false
    let pending = false
    const context = `${enc}:${previewState}`
    const refresh = async () => {
      if (cancelled || pending || !visible || document.visibilityState !== 'visible') return
      pending = true
      const token = ++previewRequestRef.current
      try {
        const data = await apiGet<Model3DStatus>(`/characters/${enc}/model3d${previewState ? `?preview_states=${encodeURIComponent(previewState)}` : ''}`)
        if (!cancelled && context === previewContextRef.current && token === previewRequestRef.current) setSt(data)
      } catch { /* Keep the last successful preview during temporary request failures. */ }
      finally { pending = false }
    }
    const observer = new IntersectionObserver(entries => {
      visible = entries.some(entry => entry.isIntersecting)
      if (visible) void refresh()
    })
    if (previewRef.current) observer.observe(previewRef.current)
    const timer = previewState === '' ? setInterval(() => void refresh(), 5000) : undefined
    document.addEventListener('visibilitychange', refresh)
    return () => {
      cancelled = true
      observer.disconnect()
      clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [enc, previewState, st.model?.url])

  // Open the picker (the dialog preselects the admin default / only backend).
  const openDialog = useCallback(() => setDialogOpen(true), [])

  const generate = useCallback(
    async (force: boolean, backend: string,
           opts?: { face_num?: number; texture_size?: number }) => {
      if (busy) return
      setDialogOpen(false)
      setBusy(true)
      try {
        const q = new URLSearchParams()
        if (force) q.set('force', '1')
        if (backend) q.set('backend', backend)
        if (opts?.face_num) q.set('face_num', String(opts.face_num))
        if (opts?.texture_size) q.set('texture_size', String(opts.texture_size))
        const qs = q.toString()
        await apiPost(`/characters/${enc}/model3d/generate${qs ? `?${qs}` : ''}`, {})
        toast(t('Generating…'))
        startPoll()
      } catch (e) {
        const msg = e instanceof ApiError && e.status === 409
          ? t('No pose render for the current outfit — generate it first')
          : (e as Error).message
        toast(t('Error') + ': ' + msg, 'error')
        setBusy(false)
      }
    },
    [busy, enc, startPoll, t, toast],
  )

  // Base-body pipeline: no backend dialog — the server dresses stale views
  // first, then builds the outfit model anew from the current base body.
  const rebuildFromBase = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      const d = await apiPost<{ status?: string }>(`/characters/${enc}/model3d/generate`, {})
      toast(d?.status === 'already_running'
        ? t('A 3D model generation is already running for this character')
        : d?.status === 'queued' ? t('Rebuild queued — it starts when the running model job ends')
          : t('Rebuilding from the base body…'))
      startPoll()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }, [busy, enc, startPoll, t, toast])

  // Collects a finished gateway job as the current outfit's model. A job that
  // is still queued/running changes nothing and only reports its progress.
  const fetchJob = useCallback(
    async (force: boolean) => {
      const id = jobId.trim()
      if (!id || busy) return
      setBusy(true)
      try {
        const q = new URLSearchParams({ job: id })
        if (force) q.set('force', '1')
        const d = await apiPost<{ status?: string; progress?: number | null; warnings?: string[] }>(
          `/characters/${enc}/model3d/fetch-job?${q.toString()}`, {})
        if (d.status === 'stored') {
          setJobErrors([])
          setJobOpen(false)
          setJobId('')
          await load()
          const warn = d.warnings || []
          toast(warn.length ? `${t('Saved')} — ${warn.join(' · ')}` : t('Saved'))
        } else {
          const pct = typeof d.progress === 'number' ? ` — ${Math.round(d.progress * 100)} %` : ''
          toast(`${d.status === 'queued' ? t('Job is still queued on the gateway') : t('Job is still running on the gateway')}${pct}`)
        }
      } catch (e) {
        const detail = e instanceof ApiError ? (e.detail as { errors?: unknown } | null) : null
        const errs = Array.isArray(detail?.errors) ? (detail.errors as string[]) : []
        if (errs.length) {
          setJobErrors(errs)
        } else {
          toast(t('Error') + ': ' + (e as Error).message, 'error')
        }
      } finally {
        setBusy(false)
      }
    },
    [busy, enc, jobId, load, t, toast],
  )

  // Independent per-character generation options.
  const setModelOption = useCallback(
    async (key: 'auto_generate', value: boolean) => {
      setSt((prev) => ({ ...prev, options: { ...(prev.options || {}), [key]: value } }))
      try {
        const d = await apiPost<{ options: Model3DStatus['options'] }>(
          `/characters/${enc}/model3d/options`, { [key]: value })
        setSt((prev) => ({ ...prev, options: d.options }))
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        load()
      }
    },
    [enc, load, t, toast],
  )

  // Upload a model AS the current-outfit model. GLB = one file; FBX = two
  // (the basecolor PNG is asked for right after). Validation errors come back
  // as 422 with concrete reasons — surface them, not a bare "failed".
  const uploadFiles = useCallback(
    async (file: File, texture: File | null) => {
      if (!file || busy) return
      setBusy(true)
      try {
        const fd = new FormData()
        fd.append('file', file)
        if (texture) fd.append('texture', texture)
        const res = await fetch(`/characters/${enc}/model3d/upload`, {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        })
        const body = await res.json().catch(() => null)
        if (!res.ok) {
          const errs: string[] = Array.isArray(body?.detail?.errors) ? body.detail.errors : []
          throw new Error(errs.length ? errs.join(' · ') : (body?.detail?.toString?.() || `HTTP ${res.status}`))
        }
        const warn: string[] = Array.isArray(body?.warnings) ? body.warnings : []
        await load()
        toast(warn.length ? `${t('Saved')} — ${warn.join(' · ')}` : t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(false)
        setPendingFbx(null)
      }
    },
    [busy, enc, load, t, toast],
  )

  const pickFile = useCallback(
    (file: File) => {
      if (file.name.toLowerCase().endsWith('.fbx')) {
        setPendingFbx(file)
        texRef.current?.click()
        return
      }
      uploadFiles(file, null)
    },
    [uploadFiles],
  )

  const setRig = useCallback(
    async (rig: string) => {
      try {
        await apiPost(`/characters/${enc}/model3d/rig`, { rig })
        await load()
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [enc, load, t, toast],
  )

  // Both checks write the sidecar, so run sequentially and retain both results.
  const analyze = useCallback(async () => {
    const run = ++analysisRunRef.current
    const current = () => analysisRunRef.current === run
    setBusy(true)
    setAnalysisResults([])
    try {
      for (const [action, success] of [['measure', t('Measured')], ['diagnose', t('Geometry checked')]]) {
        let message = success
        let error = false
        try {
          const result = await apiPost<{ ok?: boolean; status?: string; error?: string }>(
            `/characters/${enc}/model3d/${action}?force=1`, {})
          if (!current()) return
          if (result.ok === false || result.status === 'stale' || result.error) {
            error = true
            message = `${success}: ${result.status || t('Error')}${result.error ? ` · ${result.error}` : ''}`
          }
          await load()
        } catch (e) {
          error = true
          message = `${success}: ${t('Error')}: ${(e as Error).message}`
        }
        if (!current()) return
        setAnalysisResults(results => [...results, { message, error }])
        toast(message, error ? 'error' : undefined)
      }
    } finally {
      if (current()) setBusy(false)
    }
  }, [enc, load, t, toast])

  // Re-encodes the textures. Writes the model, so it is offered only for a
  // model this outfit actually owns.
  const retexture = useCallback(async () => {
    setBusy(true)
    try {
      const d = await apiPost<{ applied?: boolean; reason?: string; bytes_saved?: number }>(
        `/characters/${enc}/model3d/retexture`, {})
      await load()
      toast(
        d.applied
          ? `${t('Textures re-encoded')} — ${(((d.bytes_saved || 0) / (1024 * 1024))).toFixed(1)} MB ${t('saved')}`
          : `${t('Left unchanged')}: ${d.reason || t('nothing to do')}`,
      )
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [enc, load, t, toast])

  // Builds the distance mesh at the detail configured for characters
  // (Media Generation → Blender Refinement).
  const buildLod = useCallback(async () => {
    setBusy(true)
    try {
      const d = await apiPost<{ tris?: number; tris_before?: number }>(
        `/characters/${enc}/model3d/lod`, {})
      await load()
      toast(`${t('Distance mesh built')}: ${d.tris_before?.toLocaleString()} → ${d.tris?.toLocaleString()} ${t('tris')}`)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [enc, load, t, toast])

  const rebuildExtensions = useCallback(async () => {
    setBusy(true)
    try {
      const query = new URLSearchParams({ signature: st.model?.signature || '', tier: viewTier, force: 'true' })
      const result = await apiPost<{ ok?: boolean; reason?: string; error?: string; status?: string; extension_rig?: ExtensionRigResult }>(
        `/characters/${enc}/model3d/extension-rig?${query}`, {})
      await load()
      toast(`${t('Extension bones')}: ${result.reason || result.error || result.extension_rig?.reason || result.extension_rig?.status || result.status || t('Updated')}`,
        result.ok === false ? 'error' : undefined)
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setBusy(false) }
  }, [enc, load, st.model?.signature, viewTier, t, toast])

  const queueExtensions = useCallback(async () => {
    setBusy(true)
    try {
      await apiPost(`/characters/${enc}/model3d/extension-rig/batch`, {})
      toast(t('Queued in Improvements'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setBusy(false) }
  }, [enc, t, toast])

  const setExtensionOption = useCallback(async (id: string, key: 'enabled' | 'flip', value: boolean) => {
    const sig = st.model?.signature
    if (!sig) return
    setBusy(true)
    try {
      const modelOverrides = st.options?.extension_rig_models?.[sig]
      const overrides = { ...modelOverrides,
        [id]: { ...modelOverrides?.[id], [key]: value } }
      const result = await apiPost<{ options: Model3DStatus['options'] }>(
        `/characters/${enc}/model3d/options`, { signature: sig, extension_rig: overrides })
      setSt((previous) => ({ ...previous, options: result.options }))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally { setBusy(false) }
  }, [enc, st.model?.signature, st.options?.extension_rig_models, t, toast])

  const setExtensionMotion = useCallback(async (id: string, values?: Physics, slidersOnly = false) => {
    setBusy(true)
    try {
      const overrides = structuredClone(st.options?.extension_motion ?? {})
      if (slidersOnly) overrides[id] = { ...overrides[id], ...values }
      else if (values === undefined || !Object.keys(values).length) delete overrides[id]
      else overrides[id] = values
      for (const group of st.extension_groups ?? []) {
        if (group.controls != null && overrides[group.id]) {
          overrides[group.id] = Object.fromEntries(Object.entries(overrides[group.id]).filter(([key]) => group.controls!.includes(key)))
        }
      }
      const result = await apiPost<{ options: Model3DStatus['options'] }>(
        `/characters/${enc}/model3d/extension-motion`, { extension_motion: overrides })
      setSt(previous => ({ ...previous, options: result.options }))
      toast(t('Saved'))
      await load()
      if (slidersOnly) setSliderPreview(previous => {
        const groups = { ...previous.groups }
        delete groups[id]
        return { ...previous, groups }
      })
      return true
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      return false
    } finally { setBusy(false) }
  }, [enc, load, st.extension_groups, st.options?.extension_motion, t, toast])

  const remove = useCallback(async () => {
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setConfirmDelete(false)
    try {
      await apiDelete(`/characters/${enc}/model3d`)
      await load()
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [confirmDelete, enc, load, t, toast])

  const model = st.model
  const pipeline = st.pipeline || null
  const baseReady = pipeline?.base_model === 'ready'
  const canRerig = pipeline ? pipeline.rerig_source : !!model?.has_unrigged_source
  // A nearest match is another combination's model served as stand-in —
  // there is nothing stored for THIS outfit to replace or delete.
  const owned = !!model && model.match !== 'nearest'
  const pending = !!st.pending || busy
  const sizeMb = model?.size ? (model.size / (1024 * 1024)).toFixed(1) : ''
  const measured = model?.measured
  const canMeasure = !!st.blender?.usable
  // Finger verdict from the measurement: bones alone say nothing (the Mixamo
  // rig always carries its 30), so it is the WEIGHTED finger bones that
  // decide. A measurement from before this field asks for a re-measure.
  const fingers = ((): { label: string } => {
    if (!measured || typeof measured.finger_bones !== 'number') {
      return { label: t('fingers: measure again to see') }
    }
    if (measured.finger_bones === 0) {
      return { label: `${t('no finger bones')}` }
    }
    const weighted = measured.finger_bones_weighted ?? 0
    if (weighted === 0) {
      return {
        label: `${t('fingers not rigged — bones without mesh, the hand moves as one block')}`,
      }
    }
    return {
      label: `${t('fingers rigged')} (${weighted}/${measured.finger_bones} ${t('finger bones drive mesh')})`,
    }
  })()
  // Only a Mixamo rig can play the shared clips (humanoid characters).
  const mixamo = (model?.rig || st.rig) === 'mixamo'
  const rigless = model?.rig === 'none'
  const bust = model?.model_rev || model?.created_at || st.signature || ''

  // Cache-bust per combination so a re-generated mesh is re-fetched. The tier
  // is part of the URL, so switching it reloads the viewer with the other
  // resolution — same camera, same clip, only the mesh changes.
  const viewerUrl = model
    ? `/characters/${enc}/model3d/file?v=${encodeURIComponent(bust)}`
      + (viewTier === 'low' ? '&tier=low' : '')
    : ''
  const hasLow = !!model?.tiers?.includes('low')
  const sliderContext = `${character}:${model?.signature || st.signature || ''}`
  const previewMotion = useMemo(() => {
    const overrides = { ...st.options?.extension_motion }
    for (const group of st.extension_groups ?? []) {
      if (group.controls != null && overrides[group.id]) {
        overrides[group.id] = Object.fromEntries(Object.entries(overrides[group.id]).filter(([key]) => group.controls!.includes(key)))
      }
    }
    return previewMotionSliders(st.motion, st.motion_defaults,
      overrides, sliderPreview.context === sliderContext ? sliderPreview.groups : {})
  }, [st.motion, st.motion_defaults, st.extension_groups, st.options?.extension_motion, sliderPreview, sliderContext])
  const motionToolbar = st.extension_groups?.map(group => st.motion_defaults?.[group.id] && (group.controls == null || group.controls.some(key => ['bounce', 'weight'].includes(key))) ? (
    <fieldset className="ga-fieldset ga-model3d-group" key={`${sliderContext}:${group.id}`}>
      <legend>{group.id}</legend>
      <ExtensionMotionSliders controls={group.controls} overrides={st.options?.extension_motion?.[group.id] ?? {}}
        disabled={pending || rigless}
        onPreview={values => setSliderPreview(previous => ({ context: sliderContext,
          groups: { ...(previous.context === sliderContext ? previous.groups : {}), [group.id]: values } }))}
        onSave={values => setExtensionMotion(group.id, values, true)} />
    </fieldset>
  ) : null)
  const extensionResult = model?.extension_rig?.per_tier?.[viewTier] || model?.extension_rig
  const panelSnapshot = useMemo(() => ({
    st, pending, busy, rigless, mixamo, viewTier, extensionResult, canMeasure, model,
    setModelOption, setExtensionOption, setExtensionMotion, rebuildExtensions,
    playUrl: clip.character === character ? clip.url : '', setPlayUrl: playSituation,
  }), [st, pending, busy, rigless, mixamo, viewTier, extensionResult, canMeasure, model,
    setModelOption, setExtensionOption, setExtensionMotion, rebuildExtensions, clip, character, playSituation])
  useEffect(() => { publishModel3DPanel(character, panelSnapshot) }, [character, panelSnapshot])

  // One line per check (dot + label + short state); everything else in the tooltip.
  const statusRow = (label: string, value: string, color: string, explanation: string) => (
    <div className="ga-model3d-status-row"
      title={[`${label}: ${value}`, explanation && explanation !== value ? explanation : ''].filter(Boolean).join('\n')}>
      <span className={`ga-model3d-status-dot ga-model3d-status-${color}`} />
      <span className="ga-model3d-status-text">{label} · {value}</span>
    </div>
  )
  const tp = model?.tpose_status || 'unknown'
  const currentTwist = model?.head_twist?.current
  const fixedTwist = model?.head_twist?.corrected
  const turned = currentTwist != null && Math.abs(currentTwist) > 2
  const rigText = model?.rig_error ? t('Error') : turned
    ? `${t('head {n}° turned').replace('{n}', String(Math.abs(Math.round(currentTwist))))} → ${t('Re-rig')}`
    : `${model?.rig_backend || '–'}${fixedTwist != null ? ` · ${t('head {n}° fixed').replace('{n}', String(Math.abs(Math.round(fixedTwist))))}` : ''}`
  const face = model?.face_retexture
  const up = face?.upscale
  const faceText = face?.status === 'failed' ? t('Failed') : face?.status === 'skipped' ? t('Skipped') : face?.face_texture_lost ? t('Face texture lost')
    : face?.status === 'applied' ? (face.reference === 'face' ? t('Face view') : up?.status === 'applied' && up.backend
      ? `${up.backend}${up.in?.[0] && up.out?.[0] ? ` ×${+(up.out[0] / up.in[0]).toFixed(1)}` : ''}` : t('applied')) : '–'
  const photoText = face?.status === 'applied' && face.photo ? `${face.photo.balance ? ` · ${t('Light balance')} ${Math.round(face.photo.balance * 100)} %` : ''}${face.photo.tone_match != null && face.photo.tone_match !== 1 ? ` · ${t('Skin tone match')} ${Math.round(face.photo.tone_match * 100)} %` : ''}${typeof face.photo.skin_recolor === 'number' && face.photo.skin_recolor !== 1 ? ` · ${t('Skin colour correction')} ${Math.round(face.photo.skin_recolor * 100)} %` : ''}${face.photo.brightness !== 1 ? ` · ${t('Face brightness')} ${Math.round(face.photo.brightness * 100)} %` : ''}${face.photo.applied_on === 'hub' ? ' (hub)' : face.photo.applied_on === 'none' ? '' : ' (local)'}` : ''
  const part = model?.attached_part
  const partBuilt = part?.status === 'built' || part?.status === 'applied'
  const partText = partBuilt ? (part?.warning
    ? t('built — body still shows a protrusion of {n} mm; regenerate the pose render').replace('{n}', String(part.protrusion_mm))
    : t('built')) : part?.reason || t('not built')
  const weights = model?.limb_weights
  const weightsText = weights?.error ? t('Error') : !weights?.checked ? t('not checked')
    : weights.vertices > 0 ? t('{n} vertices repaired').replace('{n}', String(weights.vertices)) : t('clean')
  const statusPanel = model?.steps?.length ? <ModelSteps steps={model.steps} /> : <div className="ga-model3d-status">
    {statusRow(t('Pose render'), tp === 'current' ? t('current') : tp === 'changed' ? t('re-rendered')
      : tp === 'other_outfit' ? t('other outfit') : t('unknown'),
      tp === 'current' ? 'green' : tp === 'changed' ? 'red' : tp === 'other_outfit' ? 'yellow' : 'grey',
      t('Pose render freshness'))}
    {statusRow(t('Mesh'), model?.mesh_backend || '–', model?.mesh_backend ? 'green' : 'grey', model?.mesh_backend || t('unknown'))}
    {statusRow(t('Rig'), rigText, model?.rig_error ? 'red' : turned ? 'yellow' : model?.rig_backend && currentTwist != null ? 'green' : 'grey', model?.rig_error || rigText)}
    {mixamo && statusRow(t('Weights'), weightsText, weights?.error ? 'red' : weights?.checked ? 'green' : 'yellow',
      weights?.error || (weights?.checked ? weightsText : t('Run the improvement "Repair rig weights"')))}
    {part && statusRow(t('Part'), partText, !partBuilt ? 'red' : part.warning ? 'yellow' : 'green', partText)}
    {statusRow(t('Face'), faceText, face?.status === 'failed' ? 'red' : face?.face_texture_lost ? 'yellow' : face?.status === 'applied' ? 'green' : 'grey', [face?.error || face?.reason, photoText.replace(/^ · /, '')].filter(Boolean).join('\n'))}
  </div>
  const rigMetrics = model?.rig_metrics
  const hasRigMetrics = rigMetrics && (typeof rigMetrics.sym_max_pct === 'number'
    || Object.values(rigMetrics.fold || {}).some(v => typeof v === 'number')
    || Object.values(rigMetrics.clips || {}).some(v => Object.values(v).some(n => typeof n === 'number'))
    || !!rigMetrics.landmark_fallback?.length)


  // Collision capsules beside the viewer, so a slider's effect shows while it
  // moves. On the pipeline the set belongs to the base body (outfit models
  // inherit it) and is edited in the Base body tab.
  const collisionPanel = model && mixamo && model.format === 'glb' && model.collision !== undefined ? (
    pipeline ? (
      <div className="ga-hint" title={t('Outfit models on the base body inherit its capsule set.')}>
        {t('Collision capsules')}: {t('from the base body')}
        {model.collision?.capsules ? ` · ${t('{n} capsules').replace('{n}', String(model.collision.capsules.length))}` : ''}
      </div>
    ) : (
      <CollisionScales character={character} collision={model.collision}
        scales={st.options?.collision_scales} disabled={pending}
        onPreview={setCollisionPreview} onSaved={load} />
    )
  ) : null
  const asideTools = collisionPanel || (!rigless && motionToolbar?.some(Boolean))
    ? <>{collisionPanel}{rigless ? null : motionToolbar}</> : undefined

  return (
    <div className="ga-form ga-model3d-tab">
      {model ? (
        <>
          <div ref={previewRef} className="ga-model3d-fit">
          <Model3DViewer
            previewTilt
            height={480}
            statusPanel={statusPanel}
            freshness={model.freshness}
            motion={rigless ? undefined : previewMotion}
            motionToolbar={asideTools}
            url={viewerUrl}
            format={model.format || 'fbx'}
            clipUrl={mixamo ? panel?.playUrl || '' : ''}
            embeddedTakes={model.rig === 'generic'}
            clipLoops={model.clips}
            textureUrl={model.texture_url ? `${model.texture_url}?v=${bust}` : ''}
            collision={collisionPreview ?? model.collision}
            showCollision={!!collisionPreview}
          />
          </div>
          {hasRigMetrics && model.rig_metrics ? (
            <fieldset className="ga-fieldset">
              <legend>{t('Rig metrics')}</legend>
              {Object.entries(model.rig_metrics.fold || {}).filter(([, value]) => typeof value === 'number').map(([leg, fold]) => <div key={leg}>{t('Leg fold')}: {leg} — {fold.toFixed(3)}</div>)}
              {typeof model.rig_metrics.sym_max_pct === 'number' ? <div>{t('Symmetry error')}: {model.rig_metrics.sym_max_pct.toFixed(3)} %</div> : null}
              {Object.entries(model.rig_metrics.clips || {}).filter(([, value]) => Object.values(value).some(n => typeof n === 'number')).map(([name, metrics]) => (
                <div key={name}>{name}: {[
                  typeof metrics.stretch_p999 === 'number' ? `${t('Stretch p99.9')} ${metrics.stretch_p999.toFixed(3)}` : '',
                  typeof metrics.contact_err_max === 'number' ? `${t('Contact error')} ${metrics.contact_err_max.toFixed(3)} %` : '',
                  typeof metrics.tail_min_z === 'number' ? `${t('Tail minimum')} ${metrics.tail_min_z.toFixed(4)} m` : '',
                  typeof metrics.ik_unreachable === 'number' ? `${t('IK unreachable')} ${metrics.ik_unreachable}` : '',
                ].filter(Boolean).join(' · ')}</div>
              ))}
              {model.rig_metrics.landmark_fallback?.length ? <p className="ga-hint">{t('Landmark fallback')}: {model.rig_metrics.landmark_fallback.join(', ')}</p> : null}
            </fieldset>
          ) : null}
          {/* Shown whenever Blender is around, not only once a distance mesh
              exists: asking for one that is missing is what makes the server
              build it. The button says so, and a reload has it. */}
          {canMeasure && model.format === 'glb' && !rigless ? (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span className="ga-hint" style={{ whiteSpace: 'nowrap' }}>{t('Showing')}</span>
              <button
                type="button"
                className={`ga-btn ga-btn-sm${viewTier === 'full' ? ' ga-btn-primary' : ''}`}
                aria-pressed={viewTier === 'full'}
                onClick={() => setViewTier('full')}
              >
                {t('Full')}
                {measured?.tris ? ` · ${measured.tris.toLocaleString()}` : ''}
              </button>
              <button
                type="button"
                className={`ga-btn ga-btn-sm${viewTier === 'low' ? ' ga-btn-primary' : ''}`}
                aria-pressed={viewTier === 'low'}
                onClick={() => setViewTier('low')}
              >
                {t('Distance')}
                {model.low_tris ? ` · ${model.low_tris.toLocaleString()}` : ''}
              </button>
              {!hasLow ? (
                <span className="ga-hint">
                  {t('none built yet — asking for it starts the build, reload in a moment')}
                </span>
              ) : null}
            </div>
          ) : null}
          <div className="ga-model3d-controls">
          <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}><span className="ga-hint">{t('Preview state')}</span>
            <select className="ga-input" value={previewState} disabled={rigless} onChange={event => setPreviewState(event.target.value)}>
              <option value="">{t('Current (live)')}</option>
              <option value="none">{t('None')}</option>
              {previewFilters.map(row => <option key={row.id} value={row.id}>{row.label || row.id}</option>)}
            </select>
          </label>
          </div>
          {/* Only a Mixamo skeleton can play the shared clips. */}
          {rigless ? (
            <div className="ga-hint" role="status" style={model.rig_error ? { color: 'var(--ga-warn, #c77d0a)' } : undefined}>
              {st.pending
                ? t('Mesh retained — rigging is running. Showing the new mesh statically.')
                : model.rig_error
                  ? `${t('Mesh retained — rigging failed. Showing the new mesh statically.')}: ${model.rig_error}`
                  : t('Mesh retained — no rig yet. Use Re-rig from mesh to animate it.')}
            </div>
          ) : !mixamo ? (
            <div className="ga-hint">
              {t('Generic rig (no standard skeleton) — Mixamo clips will not drive this model.')}
            </div>
          ) : null}
          {model.stale_base ? (
            <div className="ga-hint" role="status" style={{ color: 'var(--ga-warn, #c77d0a)' }}>
              {model.stale_reason === 'before_pipeline'
                ? t('Built before the base body pipeline — rebuild it')
                : model.stale_reason === 'detail_changed'
                  ? t('Built for another body detail under the clothing — rebuild it')
                  : model.stale_reason === 'mesh_item_ready'
                    ? t('An own-mesh piece painted on here has its garment mesh now — rebuild it')
                    : t('Built on an older base body — rebuild it')}
            </div>
          ) : null}
          {model.match === 'nearest' ? (
            <div className="ga-hint">
              {t('No model for the current outfit yet — showing the stored model with the most similar outfit combination until one is generated.')}
            </div>
          ) : null}
          <div className="ga-hint">
            {model.source === 'upload' ? t('uploaded') : t('generated')}
            {' · '}
            {(model.format || '').toUpperCase()}
            {model.rig ? ` · ${t('rig')}: ${model.rig}` : ''}
            {sizeMb ? ` · ${sizeMb} MB` : ''}
            {model.texture_url ? ` · +${t('texture')}` : ''}
            {model.backend ? ` · ${model.backend}` : ''}
            {model.job_id ? ` · ${t('job')} ${model.job_id}` : ''}
            {model.created_at ? ` · ${formatDateTime(model.created_at, clockSettings())}` : ''}
            {model.source_filename ? ` · ${model.source_filename}` : ''}
          </div>
          {/* What is actually IN the file, measured by Blender — the line
              above only repeats what the container claims. */}
          {measured ? (
            <div className="ga-hint">
              {/* Named axes, not three bare numbers: the height is the third
                  one, and read as the first it looks like the figure is the
                  wrong size when it is only the width. */}
              <span title={t('Raw size of the mesh as stored. The 3D client scales every figure to the character height, so this is not the size on screen.')}>
                {`${t('measured')}: ${t('h')} ${(measured.dims_m?.[2] ?? 0).toFixed(2)} m`}
                {` · ${t('w')} ${(measured.dims_m?.[0] ?? 0).toFixed(2)} · ${t('d')} ${(measured.dims_m?.[1] ?? 0).toFixed(2)}`}
              </span>
              {measured.bones
                ? ` · ${measured.bones} ${t('bones')}${measured.mixamo_bones ? ' (mixamo)' : ''}`
                : ''}
              {/* Are the fingers rigged? Not a bone count — the Mixamo rig
                  always ships its finger bones — but whether those bones own
                  vertices. */}
              {measured.bones ? (
                <span
                  title={t('Finger bones that own at least one vertex with weight ≥ 0.5. A "No fingers" bake keeps the bones but skins the whole hand to the hand bone.')}
                >
                  {` · ${fingers.label}`}
                </span>
              ) : null}
              {measured.uv_layers === 0 && (measured.vertex_colors || 0) > 0
                ? ` · ${t('no UVs, colour in the vertices')}`
                : ''}
              {typeof measured.min_z === 'number' && Math.abs(measured.min_z) > 0.01
                ? ` · ${t('centred on the origin, not standing on the ground')}`
                : ''}
            </div>
          ) : null}
          {/* Defect indicators (display only): the verdict needs all three
              markers together; single markers are listed as numbers so a
              mermaid tail does not read as a defect. */}
          {model.diagnosis ? (
            <div className="ga-hint" style={model.diagnosis.suspect ? { color: 'var(--ga-warn, #c77d0a)' } : undefined}>
              {model.diagnosis.suspect
                ? `⚠ ${t('Geometry looks broken (all three markers fire): garment surfaces far off their bones, most joints without vertices, many floating fragments. Regenerating with a better pose render usually fixes this.')}`
                : `${t('geometry check')}: ${t('no defect pattern')}`}
              {model.diagnosis.data
                ? ` · ${t('spread')} ${(model.diagnosis.data.skin_spread_max ?? 0).toFixed(1)}`
                  + `${model.diagnosis.data.skin_spread_bone ? ` (${model.diagnosis.data.skin_spread_bone})` : ''}`
                  + ` · ${model.diagnosis.data.bones_with_verts ?? 0} ${t('joints with mesh')}`
                  + ` · ${model.diagnosis.data.tiny_parts ?? 0} ${t('fragments')}`
                : ''}
            </div>
          ) : null}
          {/* Upload rig declarations decide whether shared clips apply.
              (owned: the update writes the CURRENT combination's sidecar —
              a nearest stand-in has none.) */}
          {owned && model.source === 'upload' && !pipeline ? (
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span className="ga-hint" style={{ whiteSpace: 'nowrap' }}>{t('Rig')}</span>
              <select
                className="ga-input"
                value={model.rig || 'mixamo'}
                disabled={pending}
                onChange={(e) => setRig(e.target.value)}
              >
                <option value="mixamo">mixamo</option>
                <option value="generic">generic</option>
              </select>
            </label>
          ) : null}
        </>
      ) : (
        <div className="ga-hint">
          {pending
            ? t('Generating the 3D model — this takes a few minutes.')
            : pipeline
              ? t('No 3D model for this outfit yet — it is built from the base body (Rebuild from base body).')
              : t('No 3D model for this outfit yet — upload one or generate it from the pose render.')}
        </div>
      )}
      {model ? <div className="ga-hint">
        {pipeline
          ? `${t('Built from the base body')} · ${pipeline.base_signature}`
          : <>{t('Mesh backend')}: {model.mesh_backend || t('Unknown')} · {t('Rig backend')}: {model.rig_backend || t('Unknown')}</>}
      </div> : null}
      {model?.refined && !model.refined.retexture && model.refined.reason ? <p className="ga-hint" role="status">{t('Texture re-encoding failed — the model was published without this improvement.')}: {model.refined.reason}</p> : null}
      {model?.lod_error ? <p className="ga-hint" role="status">{t('Distance mesh rebuild failed')}: {model.lod_error}</p> : null}
      <div role="group" aria-label={t('Model')}>
        <div className="ga-form-section-label">{t('Model')}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {pipeline ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={pending || !baseReady}
              onClick={rebuildFromBase}
              title={!baseReady ? t('Generate the rigged base model first (Base body tab)')
                : t('Builds the outfit model anew from the current base body. Dressed views that no longer match the base body are rendered first; no mesh backend is involved.')}
            >
              {pending ? t('Generating…') : t('Rebuild from base body')}
            </button>
          ) : (
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={pending || !st.has_input}
              onClick={openDialog}
              title={!st.has_input ? t('No pose render for the current outfit — generate it first') : undefined}
            >
              {pending ? t('Generating…') : owned ? t('Regenerate') : t('Generate')}
            </button>
          )}
          {!pipeline ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={pending}
              onClick={() => fileRef.current?.click()}
            >
              {owned ? t('Upload (replace)') : t('Upload GLB/FBX')}
            </button>
          ) : null}
          {model ? (
            <a className="ga-btn ga-btn-sm" href={`/characters/${enc}/model3d/file?download=true`} download>
              {t('Download')}
            </a>
          ) : null}
          {/* Delete targets the CURRENT combination's entry — a nearest
              stand-in belongs to another combination and has none to delete. */}
          {owned ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              style={{ marginInlineStart: 12 }}
              disabled={pending}
              onClick={remove}
              onBlur={() => setConfirmDelete(false)}
            >
              {confirmDelete ? t('Really delete?') : t('Delete')}
            </button>
          ) : null}
        </div>
      </div>
      <div role="group" aria-label={t('Improve')}>
        <div className="ga-form-section-label">{t('Improve')}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Only for a GLB this outfit owns — it rewrites the stored file. */}
          {owned && canMeasure && model?.format === 'glb' ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={pending}
              onClick={retexture}
              title={t('Re-encodes the textures to JPEG — typically 60–90 % smaller with the geometry untouched. The original is kept, and the result is only used if it still validates.')}
            >
              {t('Shrink textures')}
            </button>
          ) : null}
          {owned && canMeasure && model?.format === 'glb' ? (
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={pending}
              onClick={buildLod}
              title={t('Builds a reduced copy of this mesh for viewing at a distance. The full model is untouched — the client picks whichever fits the camera distance.')}
            >
              {model.tiers?.includes('low') ? t('Rebuild distance mesh') : t('Build distance mesh')}
            </button>
          ) : null}
        </div>
        {/* Face cleanup, face retexture and the rig act on the model with
            the retained source: off the pipeline this outfit's model, on it
            the base body — whose actions live in the Base body tab. */}
        {pipeline ? (
          <div className="ga-face-actions-row">
            <span className="ga-hint">{t('Face cleanup, face retexture, re-rig and collision capsules act on the base body.')}</span>
            {onOpenBaseBody ? (
              <button type="button" className="ga-btn ga-btn-sm" onClick={onOpenBaseBody}>{t('Open Base body tab')}</button>
            ) : null}
          </div>
        ) : (
          <ModelFaceActions character={character} st={st} face={model ?? null}
            signature={model?.signature || st.signature || ''} cleanup={st.face_cleanup}
            hasModel={!!model} canRerig={canRerig}
            rerigBlocked={t('No retained unrigged mesh source. Generate a new model to enable re-rigging.')}
            onReload={load} onStarted={startPoll} />
        )}
      </div>
      <div role="group" aria-label={t('Inspect')}>
        <div className="ga-form-section-label">{t('Inspect')}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {model && canMeasure ? (
            <button type="button" className="ga-btn ga-btn-sm" disabled={pending} onClick={analyze}
              title={`${t('Reads the real size, triangle count and bone names out of the file. Does not change the model.')} ${t('Checks the geometry for the known bake defect (garments turned into flat surfaces). Reads only — the finding is shown, nothing is changed.')}`}>
              {t('Analyze')}
            </button>
          ) : null}
        </div>
      </div>
      <div aria-live="polite">
        {analysisResults.map((result, index) => <div key={index} className="ga-hint" role="status"
          style={result.error ? { color: 'var(--ga-warn, #c77d0a)' } : undefined}>{result.message}</div>)}
      </div>
      <details>
        <summary className="ga-form-section-label" style={{ cursor: 'pointer' }}>{t('Advanced')}</summary>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginTop: 6 }}>
          {/* A gateway mesh job is an img2mesh result — the pipeline builds
              its outfit models from the base body instead. */}
          {!pipeline ? (
          <button
            type="button"
            className={`ga-btn ga-btn-sm${jobOpen ? ' ga-btn-primary' : ''}`}
            disabled={pending}
            aria-expanded={jobOpen}
            onClick={() => setJobOpen((v) => !v)}
            title={t('Collects a mesh job that finished on the gateway after the generation here gave up waiting — by the job id from the log.')}
          >
            {t('Fetch by job ID…')}
          </button>
          ) : null}
          {/* Pre-warm the whole wardrobe: one T-pose render + mesh per saved
              outfit, without dressing the character. */}
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={() => setBatchOpen(true)}
            title={pipeline
              ? t('Dresses the base body views and builds the outfit model for every saved outfit — the character keeps wearing what it wears.')
              : t('Renders the pose reference and the mesh for every saved outfit — the character keeps wearing what it wears.')}
          >
            ⚙ {t('All outfits…')}
          </button>
          {st.extension_groups?.length ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={pending || !canMeasure}
            onClick={queueExtensions}>{t('Rebuild extension bones for all models')}</button>
          ) : null}
        </div>
      {jobOpen && !pipeline ? (
        <div className="ga-form" style={{ gap: 6 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              className="ga-input"
              style={{ flex: '1 1 12rem', minWidth: 0 }}
              value={jobId}
              placeholder={t('Job ID, e.g. 466a4e41b73d')}
              aria-label={t('Job ID')}
              disabled={pending}
              onChange={(e) => {
                setJobId(e.target.value)
                setJobErrors([])
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') fetchJob(false)
              }}
            />
            <button
              type="button"
              className="ga-btn ga-btn-sm ga-btn-primary"
              disabled={pending || !jobId.trim()}
              onClick={() => fetchJob(false)}
            >
              {t('Fetch')}
            </button>
          </div>
          <div className="ga-hint">
            {t('Stored as the model of the outfit worn right now, replacing the current one. A job that is still running changes nothing — try again once it is done.')}
          </div>
          <div className="ga-hint">
            {t('A valid unrigged delivery is retained as the static current mesh. Use Re-rig from mesh afterwards; no Store anyway override is needed.')}
          </div>
          {jobErrors.length ? (
            <div className="ga-hint" style={{ color: 'var(--ga-warn, #c77d0a)' }}>
              {`${t('The delivered model fails the check')}: ${jobErrors.join(' · ')}`}
              {' '}
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                disabled={pending}
                onClick={() => fetchJob(true)}
              >
                {t('Store anyway')}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
      </details>
      <input
        ref={fileRef}
        type="file"
        accept=".glb,.fbx"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) pickFile(f)
          e.target.value = ''
        }}
      />
      {/* Second step of the FBX case: its basecolor PNG. */}
      <input
        ref={texRef}
        type="file"
        accept="image/png,image/jpeg"
        style={{ display: 'none' }}
        onChange={(e) => {
          const tex = e.target.files?.[0] || null
          if (pendingFbx) uploadFiles(pendingFbx, tex)
          e.target.value = ''
        }}
      />

      <MeshBackendDialog
        open={dialogOpen}
        title={model ? t('Regenerate') : t('Generate 3D model')}
        backends={st.backends || []}
        defaultBackend={
          st.default || ((st.backends || []).length === 1 ? (st.backends || [])[0].name : '')
        }
        onGenerate={(backend, opts) => generate(!!model, backend, opts)}
        onClose={() => setDialogOpen(false)}
      />

      <OutfitBatchDialog
        open={batchOpen}
        character={character}
        onClose={() => setBatchOpen(false)}
        onDone={load}
      />
    </div>
  )
}
