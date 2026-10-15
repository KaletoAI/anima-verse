import { previewMotionSliders } from './motionFieldPreview'
import { ExtensionMotionDraft, ExtensionMotionSliders } from './ExtensionMotionDraft'
import type { Physics } from '../../lib/motionDraft'
import { MotionPreviewHint } from './MotionPreviewHint'
import type { SecondaryMotionPayload, ExtensionRigDeclaration } from '@anima/scene-render'
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
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MeshBackendDialog } from '../../components/MeshBackendDialog'
import { Field } from '../../components/Field'
import { Model3DViewer } from './Model3DViewer'
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

interface ExtensionRigResult {
  status?: 'none_applicable' | 'not_found' | 'failed' | 'applied'
  reason?: string
  metrics?: Record<string, unknown>
  per_tier?: Record<string, ExtensionRigResult>
}

interface FaceRetextureFinding {
  code: string
  message: string
  fix?: string
  detail?: string
}
interface FaceRetextureCheck {
  ok: boolean
  problems: FaceRetextureFinding[]
  warnings: FaceRetextureFinding[]
  runnable: boolean
  runnable_problems: FaceRetextureFinding[]
}

interface Model3DInfo {
  tpose_status?: 'current' | 'changed' | 'other_outfit' | 'unknown'
  head_twist?: { current: number | null; corrected: number | null }
  clips?: Record<string, { loop: boolean }>
  rig_metrics?: {
    fold?: Record<string, number>
    sym_max_pct?: number
    landmark_fallback?: string[]
    clips?: Record<string, { stretch_p999: number; contact_err_max: number; tail_min_z: number; ik_unreachable: number }>
  }
  face_retexture?: { status: string; at?: string; backend?: string; job_id?: string; face_texture_lost?: boolean; upscale?: { status: string; backend?: string; in?: number[]; out?: number[]; cached?: boolean; busy?: boolean; error?: string } }
  face_retexture_snapshot?: { ok: boolean; created_at?: string; error?: string }
  face_retexture_compare_url?: string
  model_rev?: string
  extension_rig?: ExtensionRigResult
  filename?: string
  /** signature of the SERVED file (nearest match: another combination's) */
  signature?: string
  /** how the served model was found: exact | neutral | nearest */
  match?: string
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

interface Model3DStatus {
  motion?: SecondaryMotionPayload
  motion_defaults?: SecondaryMotionPayload['groups']
  signature?: string
  rig?: string
  has_input?: boolean
  model?: Model3DInfo | null
  options?: { auto_generate?: boolean;
    extension_rig_models?: Record<string, Record<string, { enabled?: boolean; flip?: boolean }>>;
    extension_motion?: Record<string, Physics & { bounce?: number; weight?: number }> }
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
  /** Local Blender install — decides whether measuring is offered at all. */
  blender?: { enabled?: boolean; executable?: string; version?: string; usable?: boolean }
}

interface AnimationClip {
  kind: string
  set: string
  name: string
  filename: string
  url: string
}

// The chosen clip is a VIEW preference, not character data: it survives the
// character switch (and a reload) instead of snapping back on every change.
const CLIP_PREF_KEY = 'model3d.clip'
const DEFAULT_CLIP_KIND = 'idle'
// Sentinel for an explicit "static / no animation" choice — told apart from
// "unset" (which auto-picks the default) so it survives a status reload instead
// of snapping back to idle.
const CLIP_NONE = 'none'

export function FieldModel3D({ character }: { character: string }) {
  // Subscribe to the shared clock settings so the stamps above re-render
  // once the server-configured format and timezone arrive.
  useClockSettings()
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [st, setSt] = useState<Model3DStatus>({})
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [analysisResults, setAnalysisResults] = useState<Array<{ message: string; error: boolean }>>([])
  const [clips, setClips] = useState<AnimationClip[]>([])
  const [clipUrl, setClipUrl] = useState('')
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

  const [rerigOpen, setRerigOpen] = useState(false)
  const [rerigBackend, setRerigBackend] = useState('')
  const rerigTaskRef = useRef('')
  const faceTaskRef = useRef('')
  // Bumped on every Analyze run and on a character switch: a run whose token is
  // no longer current must not write results into another character's panel.
  const analysisRunRef = useRef(0)
  const [faceOpen, setFaceOpen] = useState(false)
  const [faceBackend, setFaceBackend] = useState('')
  const [upscaleFirst, setUpscaleFirst] = useState(true)
  const [upscaleBackend, setUpscaleBackend] = useState('')
  const [faceCheck, setFaceCheck] = useState<FaceRetextureCheck | null>(null)
  const [faceCheckError, setFaceCheckError] = useState('')
  const [faceControls, setFaceControls] = useState({ strength: 1, feather: 0.18, render_resolution: 768, yaw: 0 })
  const [revertFaceOpen, setRevertFaceOpen] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [pendingFbx, setPendingFbx] = useState<File | null>(null)
  // Which resolution the viewer shows — a VIEW state, never sent anywhere.
  const [viewTier, setViewTier] = useState<'full' | 'low'>('full')
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
      if (d && !d.pending && rerigTaskRef.current && d.rerig_result?.task_id === rerigTaskRef.current) {
        toast(d.rerig_result.ok ? t('Re-rig completed') : `${t('Re-rig failed')}: ${d.rerig_result.error || t('Error')}`,
          d.rerig_result.ok ? undefined : 'error')
        rerigTaskRef.current = ''
      }
      if (d && !d.pending && faceTaskRef.current && d.face_retexture_result?.task_id === faceTaskRef.current) {
        toast(d.face_retexture_result.ok ? t('Face retexture completed') : `${t('Face retexture failed')}: ${d.face_retexture_result.error || t('Error')}`,
          d.face_retexture_result.ok ? undefined : 'error')
        faceTaskRef.current = ''
      }
      if (!d?.pending || n >= 200) {
        if (pollRef.current) clearInterval(pollRef.current)
        setBusy(false)
      }
    }, 5000)
  }, [load, t, toast])

  useEffect(() => {
    setConfirmDelete(false)
    setRerigOpen(false)
    rerigTaskRef.current = ''
    faceTaskRef.current = ''
    setFaceOpen(false)
    setRevertFaceOpen(false)
    setFaceCheck(null)
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
      if (d?.pending) startPoll()
    })
    return () => {
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

  // Shared animation clips (world-independent, same rig as the models).
  useEffect(() => {
    apiGet<{ clips?: AnimationClip[] }>('/assets/animation-clips')
      .then((d) => setClips(d.clips || []))
      .catch(() => setClips([]))
  }, [])

  const pickClip = useCallback((url: string) => {
    setClipUrl(url)
    // Remember the KIND, not the URL, so the same choice follows across
    // characters even on a different set (idle -> idle_female). An empty select
    // is an explicit "static" choice (sentinel CLIP_NONE), NOT "unset" — it must
    // survive a status reload instead of snapping back to the default.
    const kind = url ? (clips.find((c) => c.url === url)?.kind || '') : CLIP_NONE
    localStorage.setItem(CLIP_PREF_KEY, kind)
  }, [clips])

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
          ? t('No T-pose render for the current outfit — generate it first')
          : (e as Error).message
        toast(t('Error') + ': ' + msg, 'error')
        setBusy(false)
      }
    },
    [busy, enc, startPoll, t, toast],
  )

  const rerig = async () => {
    if (busy || st.pending) return
    const context = previewContextRef.current
    const q = new URLSearchParams({ signature: st.model?.signature || '' })
    if (rerigBackend) q.set('backend', rerigBackend)
    setBusy(true)
    try {
      const result = await apiPost<{ task_id?: string }>(`/characters/${enc}/model3d/rerig?${q}`, {})
      if (context !== previewContextRef.current) return
      setRerigOpen(false)
      rerigTaskRef.current = result.task_id || ''
      toast(t('Re-rigging…'))
      startPoll()
    } catch (e) {
      if (context !== previewContextRef.current) return
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }

  const faceSignature = st.signature || ''
  useEffect(() => {
    if (!faceOpen) return
    let cancelled = false
    setFaceCheck(null)
    setFaceCheckError('')
    const query = new URLSearchParams({ signature: faceSignature, backend: faceBackend, lang })
    apiGet<FaceRetextureCheck>(`/characters/${enc}/model3d/face-retexture/check?${query}`)
      .then(result => { if (!cancelled) setFaceCheck(result) })
      .catch(error => { if (!cancelled) setFaceCheckError((error as Error).message) })
    return () => { cancelled = true }
  }, [faceOpen, faceSignature, faceBackend, enc, lang])

  const applyFaceRetexture = async () => {
    if (busy || st.pending || !faceCheck?.ok || !faceCheck.runnable) return
    const context = previewContextRef.current
    const query = new URLSearchParams({ signature: faceSignature, backend: faceBackend, lang })
    query.set('upscale', String(upscaleFirst))
    query.set('upscale_backend', upscaleBackend)
    for (const [key, value] of Object.entries(faceControls)) query.set(key, String(value))
    setBusy(true)
    try {
      const result = await apiPost<{ ok?: boolean; status?: string; task_id?: string; problems?: FaceRetextureFinding[] }>(
        `/characters/${enc}/model3d/face-retexture?${query}`, {})
      if (context !== previewContextRef.current) return
      if (result.ok === false) throw new Error((result.problems || []).map(p => `${p.message} ${p.fix || ''}`).join(' · '))
      setFaceOpen(false)
      faceTaskRef.current = result.task_id || ''
      toast(t('Face retexture running…'))
      startPoll()
    } catch (error) {
      if (context !== previewContextRef.current) return
      toast(t('Error') + ': ' + (error as Error).message, 'error')
      setBusy(false)
    }
  }

  const revertFaceRetexture = async () => {
    if (busy || st.pending) return
    const context = previewContextRef.current
    setBusy(true)
    const query = new URLSearchParams({ signature: st.model?.signature || '', lang })
    try {
      const result = await apiPost<{ ok: boolean; error?: string }>(`/characters/${enc}/model3d/face-retexture/revert?${query}`, {})
      if (context !== previewContextRef.current) return
      if (!result.ok) throw new Error(result.error || t('Face retexture revert failed'))
      setRevertFaceOpen(false)
      toast(t('Face retexture reverted'))
      await load()
    } catch (error) {
      if (context !== previewContextRef.current) return
      toast(t('Error') + ': ' + (error as Error).message, 'error')
    } finally {
      if (context === previewContextRef.current) setBusy(false)
    }
  }

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

  // Opt-in: generate the mesh automatically (cheapest backend) once a new
  // outfit combination's T-pose render succeeded.
  const setAutoGenerate = useCallback(
    async (value: boolean) => {
      setSt((prev) => ({ ...prev, options: { ...(prev.options || {}), auto_generate: value } }))
      try {
        const d = await apiPost<{ options: Model3DStatus['options'] }>(
          `/characters/${enc}/model3d/options`, { auto_generate: value })
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
      if (slidersOnly) overrides[id] = { ...overrides[id], bounce: Number(values?.bounce), weight: Number(values?.weight) }
      else if (values === undefined || !Object.keys(values).length) delete overrides[id]
      else overrides[id] = values
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
  }, [enc, load, st.options?.extension_motion, t, toast])

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

  // The character's set CHAIN, most specific first: explicit set, then the
  // derived one (animal / female / male). An explicit set may be incomplete —
  // a "lady" character without sit_lady sits like a female, and only if that
  // is missing too does the plain sit.fbx apply.
  const chain = useMemo(
    () => st.animation_sets || (st.animation_set ? [st.animation_set] : []),
    [st.animation_sets, st.animation_set],
  )
  const myClips = useMemo(
    () => clips.filter((c) => !c.set || chain.includes(c.set)),
    [clips, chain],
  )

  // Pick the best clip of a kind along the chain: explicit set -> derived set
  // -> setless.
  const bestOfKind = useCallback(
    (kind: string): AnimationClip | undefined => {
      const ofKind = clips.filter((c) => c.kind === kind)
      for (const s of chain) {
        const hit = ofKind.find((c) => c.set === s)
        if (hit) return hit
      }
      return ofKind.find((c) => !c.set)
    },
    [clips, chain],
  )

  // Keep the KIND across characters and resolve it per character: the same
  // "idle" pick lands on idle_female for her and idle_animal for the dog.
  useEffect(() => {
    if (!clips.length) return
    setClipUrl((cur) => {
      if (cur && myClips.some((c) => c.url === cur)) return cur
      const pref = localStorage.getItem(CLIP_PREF_KEY)
      // An explicit "static" choice is honoured — do NOT auto-pick a default
      // on top of it (this reruns on every 5 s generation poll).
      if (pref === CLIP_NONE) return ''
      const wanted = pref || DEFAULT_CLIP_KIND
      return (bestOfKind(wanted) || bestOfKind(DEFAULT_CLIP_KIND))?.url || ''
    })
  }, [clips, myClips, bestOfKind])
  // Cache-bust per combination so a re-generated mesh is re-fetched. The tier
  // is part of the URL, so switching it reloads the viewer with the other
  // resolution — same camera, same clip, only the mesh changes.
  const viewerUrl = model
    ? `/characters/${enc}/model3d/file?v=${encodeURIComponent(bust)}`
      + (viewTier === 'low' ? '&tier=low' : '')
    : ''
  const hasLow = !!model?.tiers?.includes('low')
  const sliderContext = `${character}:${model?.signature || st.signature || ''}`
  const previewMotion = useMemo(() => previewMotionSliders(st.motion, st.motion_defaults,
    st.options?.extension_motion, sliderPreview.context === sliderContext ? sliderPreview.groups : {}),
    [st.motion, st.motion_defaults, st.options?.extension_motion, sliderPreview, sliderContext])
  const motionToolbar = st.extension_groups?.map(group => st.motion_defaults?.[group.id] ? (
    <fieldset className="ga-fieldset" key={`${sliderContext}:${group.id}`}>
      <legend>{group.id}</legend>
      <ExtensionMotionSliders overrides={st.options?.extension_motion?.[group.id] ?? {}}
        disabled={pending || rigless}
        onPreview={values => setSliderPreview(previous => ({ context: sliderContext,
          groups: { ...(previous.context === sliderContext ? previous.groups : {}), [group.id]: values } }))}
        onSave={values => setExtensionMotion(group.id, values, true)} />
    </fieldset>
  ) : null)
  const extensionResult = model?.extension_rig?.per_tier?.[viewTier] || model?.extension_rig
  const statusRow = (label: string, value: string, color: string, explanation: string) => (
    <div className="ga-model3d-status-row" title={explanation}>
      <span className={`ga-model3d-status-dot ga-model3d-status-${color}`} />
      <span>{label} · {value}</span>
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
  const faceText = face?.status === 'failed' ? t('Failed') : face?.face_texture_lost ? t('Face texture lost')
    : face?.status === 'applied' ? (up?.status === 'applied' && up.backend
      ? `${up.backend}${up.in?.[0] && up.out?.[0] ? ` ×${+(up.out[0] / up.in[0]).toFixed(1)}` : ''}` : t('applied')) : '–'
  const statusPanel = <div className="ga-model3d-status">
    {statusRow(t('T-pose'), tp === 'current' ? t('current') : tp === 'changed' ? t('re-rendered')
      : tp === 'other_outfit' ? t('other outfit') : t('unknown'),
      tp === 'current' ? 'green' : tp === 'changed' ? 'red' : tp === 'other_outfit' ? 'yellow' : 'grey',
      t('T-pose source freshness'))}
    {statusRow(t('Mesh'), model?.mesh_backend || '–', model?.mesh_backend ? 'green' : 'grey', model?.mesh_backend || t('unknown'))}
    {statusRow(t('Rig'), rigText, model?.rig_error ? 'red' : turned ? 'yellow' : model?.rig_backend && currentTwist != null ? 'green' : 'grey', model?.rig_error || rigText)}
    {statusRow(t('Face'), faceText, face?.status === 'failed' ? 'red' : face?.face_texture_lost ? 'yellow' : face?.status === 'applied' ? 'green' : 'grey', faceText)}
  </div>
  const rigMetrics = model?.rig_metrics
  const hasRigMetrics = rigMetrics && (typeof rigMetrics.sym_max_pct === 'number'
    || Object.values(rigMetrics.fold || {}).some(v => typeof v === 'number')
    || Object.values(rigMetrics.clips || {}).some(v => Object.values(v).some(n => typeof n === 'number'))
    || !!rigMetrics.landmark_fallback?.length)


  return (
    <div className="ga-form">
      {model ? (
        <>
          <div ref={previewRef}>
          <Model3DViewer
            previewTilt
            height={352}
            statusPanel={statusPanel}
            motion={rigless ? undefined : previewMotion}
            motionToolbar={rigless ? undefined : motionToolbar}
            url={viewerUrl}
            format={model.format || 'fbx'}
            clipUrl={mixamo ? clipUrl : ''}
            embeddedTakes={model.rig === 'generic'}
            clipLoops={model.clips}
            textureUrl={model.texture_url ? `${model.texture_url}?v=${bust}` : ''}
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
          {/* The clips of THIS character's set (+ the setless fallbacks). */}
          <div className="ga-model3d-controls">
          {mixamo ? (myClips.length ? (
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span className="ga-hint" style={{ whiteSpace: 'nowrap' }}>
                {t('Animation')}
                {chain.length ? ` (${chain.join(' → ')})` : ''}
              </span>
              <select
                className="ga-input"
                value={clipUrl}
                onChange={(e) => pickClip(e.target.value)}
              >
                <option value="">{t('— none (static) —')}</option>
                {/* Keyed on the URL: since sets became directories the bare
                    file name repeats (idle.fbx exists per set). */}
                {myClips.map((c) => (
                  <option key={c.url} value={c.url}>
                    {c.kind}
                    {c.set ? ` · ${c.set}` : ''}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="ga-hint">
              {clips.length
                ? t('No clips for this animation set — add <kind>_<set>.fbx files or plain <kind>.fbx fallbacks.')
                : t('No animation clips — drop Mixamo FBX files ("Without Skin") into shared/models/clips/.')}
            </div>
          )) : null}
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
                ? `⚠ ${t('Geometry looks broken (all three markers fire): garment surfaces far off their bones, most joints without vertices, many floating fragments. Regenerating with a better T-pose render usually fixes this.')}`
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
          {owned && model.source === 'upload' ? (
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
            : t('No 3D model for this outfit yet — upload one or generate it from the T-pose render.')}
        </div>
      )}
      <label className="ga-check-row"
        title={t('Once the T-pose render of a NEW outfit combination has succeeded, the mesh is generated automatically on the cheapest matching backend — the T-pose is always awaited first.')}>
        <input
          type="checkbox"
          checked={!!st.options?.auto_generate}
          onChange={(e) => setAutoGenerate(e.target.checked)}
        />
        <span>{t('Auto-generate 3D model (cheapest backend)')}</span>
      </label>
      {st.extension_groups?.length ? (
        <fieldset className="ga-form">
          <legend>{t('Extension bones')}</legend>
          <div className="ga-hint" aria-live="polite">
            <strong>{t('Extension bones')} · {viewTier}: </strong>
            {t(extensionResult?.status === 'applied' ? 'Applied'
              : extensionResult?.status === 'failed' ? 'Failed'
              : extensionResult?.status === 'not_found' ? 'Geometry not found'
              : extensionResult?.status === 'none_applicable' ? 'No applicable groups'
              : 'Not processed')}
            {extensionResult?.reason ? ` · ${extensionResult.reason}` : ''}
            {extensionResult?.metrics ? (
              <details>
                <summary>{t('Metrics')}</summary>
                <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                  {JSON.stringify(extensionResult.metrics, null, 2)}
                </pre>
              </details>
            ) : null}
          </div>

          {st.extension_groups.map((group) => (
            <div key={group.id} style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <span>{group.id}</span>
              <label>
                <input type="checkbox" disabled={pending || busy || !st.model?.signature}
                  checked={st.options?.extension_rig_models?.[st.model?.signature || '']?.[group.id]?.enabled !== false}
                  onChange={(event) => setExtensionOption(group.id, 'enabled', event.target.checked)} />
                {' '}{t('Enabled')} <MotionPreviewHint field="enabled" />
              </label>
              {group.op === 'appendage_chain' ? (
                <label>
                  <input type="checkbox" disabled={pending || busy || !st.model?.signature}
                    checked={st.options?.extension_rig_models?.[st.model?.signature || '']?.[group.id]?.flip === true}
                    onChange={(event) => setExtensionOption(group.id, 'flip', event.target.checked)} />
                  {' '}{t('Flip direction')} <MotionPreviewHint field="flip" />
                </label>
              ) : null}
              {st.motion_defaults?.[group.id] ? <ExtensionMotionDraft
                key={`${character}:${st.model?.signature || st.signature || ''}:${group.id}`}
                defaults={st.motion_defaults[group.id] as unknown as Physics}
                overrides={st.options?.extension_motion?.[group.id] ?? {}}
                disabled={pending || busy || rigless}
                onSave={values => setExtensionMotion(group.id, values)} /> : null}
            </div>
          ))}
        {model?.format === 'glb' && mixamo ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={pending || !canMeasure}
            onClick={rebuildExtensions}>{t('Rebuild extension bones')}</button>
        ) : null}
          <span className="ga-hint">{t('Enabled and flip are saved for this model; they take effect after rebuilding its extension bones.')}</span>
        </fieldset>
      ) : null}
      {!st.pending && st.rerig_result ? <div className="ga-hint" role="status">
        {st.rerig_result.ok ? t('Re-rig completed') : `${t('Re-rig failed')}: ${st.rerig_result.error || t('Error')}`}
      </div> : null}
      {model ? <div className="ga-hint">
        {t('Mesh backend')}: {model.mesh_backend || t('Unknown')} · {t('Rig backend')}: {model.rig_backend || t('Unknown')}
      </div> : null}
      {!st.pending && st.face_retexture_result ? <div className="ga-hint" role="status">
        {st.face_retexture_result.ok ? t('Face retexture completed') : `${t('Face retexture failed')}: ${st.face_retexture_result.error || t('Error')}`}
      </div> : null}
      {model?.face_retexture ? <div className="ga-hint" role="status">
        {model.face_retexture.status === 'applied' ? t('Face retexture applied') : t('Face retexture reverted')}
        {model.face_retexture.backend ? ` · ${model.face_retexture.backend}` : ''}
        {model.face_retexture.job_id ? ` · ${model.face_retexture.job_id}` : ''}
        {model.face_retexture.at ? ` · ${formatDateTime(model.face_retexture.at, clockSettings())}` : ''}
        {model.face_retexture_compare_url ? <> · <a href={model.face_retexture_compare_url} target="_blank" rel="noopener noreferrer">{t('Comparison image')}</a></> : null}
      </div> : null}
      {model?.face_retexture?.upscale ? <p className="ga-hint" role="status">
        {model.face_retexture.upscale.status === 'failed'
          ? `${t('Reference upscale failed — using original photo')}${model.face_retexture.upscale.busy ? ` · ${t('Busy')}` : ''} · ${model.face_retexture.upscale.error || ''}`
          : model.face_retexture.upscale.status === 'applied'
            ? `${t('Reference upscaled')} · ${model.face_retexture.upscale.backend || ''} · ${model.face_retexture.upscale.in?.join('×')} → ${model.face_retexture.upscale.out?.join('×')}${model.face_retexture.upscale.cached ? ` · ${t('Cached')}` : ''}`
            : model.face_retexture.upscale.status === 'skipped' ? t('Reference upscale skipped — already large enough') : t('Reference upscale off')}
      </p> : null}
      {model?.face_retexture?.face_texture_lost ? <p className="ga-hint" role="status">
        {t('The rigger changed the baked face texture — the face correction may be lost. Revert restores the previous model.')}
      </p> : null}
      {model?.refined && !model.refined.retexture && model.refined.reason ? <p className="ga-hint" role="status">{t('Texture re-encoding failed — the model was published without this improvement.')}: {model.refined.reason}</p> : null}
      {model?.lod_error ? <p className="ga-hint" role="status">{t('Distance mesh rebuild failed')}: {model.lod_error}</p> : null}
      {faceOpen ? createPortal(
        <div className="ga-modal-backdrop" onClick={() => { if (!busy) setFaceOpen(false) }}>
          <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Face retexture')}
            style={{ maxWidth: 560 }} onClick={e => e.stopPropagation()}>
            <div className="ga-modal-header">{t('Face retexture')}</div>
            <div className="ga-modal-body ga-form">
              <p className="ga-hint">{t('Corrects the face texture from the original photo, then rebuilds the rig and derived meshes. Each run starts from the original unrigged mesh.')}</p>
              <fieldset className="ga-fieldset">
                <legend className="ga-fieldset-title">{t('Source check')}</legend>
                {faceCheckError ? <div className="ga-status-danger" role="alert">✗ {faceCheckError}</div> : null}
                {!faceCheck && !faceCheckError ? <div className="ga-hint" role="status">{t('Checking face retexture eligibility…')}</div> : null}
                {faceCheck ? <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {[...faceCheck.problems, ...faceCheck.runnable_problems].map(p => <div key={p.code} role="alert">
                    <div className="ga-status-danger">✗ {p.message}{p.detail ? ` (${p.detail})` : ''}</div>
                    {p.fix ? <div className="ga-field-hint">→ {p.fix}</div> : null}
                  </div>)}
                  {faceCheck.warnings.map(w => <div key={w.code} className="ga-field-warn">⚠ {w.message}</div>)}
                  {faceCheck.ok && faceCheck.runnable ? <div className="ga-status-ok">✓ {t('Ready for face retexture.')}</div> : null}
                </div> : null}
              </fieldset>
              <fieldset className="ga-fieldset">
                <legend className="ga-fieldset-title">{t('Backends')}</legend>
                <Field label={t('Face retexture backend')}
                  hint={t('Auto uses the routing chain of the occasion "Face retexture". An explicit pick has no fallback.')}>
                  <select className="ga-input" value={faceBackend} disabled={busy}
                    onChange={e => { setFaceCheck(null); setFaceBackend(e.target.value) }}>
                    <option value="">{t('Auto (routing)')}</option>
                    {(st.face_retexture_backends || []).map(b => <option key={b.name} value={b.name}>{b.name}{b.model ? ` · ${b.model}` : ''}</option>)}
                  </select>
                </Field>
                <label className="ga-check-row" style={{ margin: '8px 0 4px' }}>
                  <input type="checkbox" checked={upscaleFirst} disabled={busy} onChange={e => setUpscaleFirst(e.target.checked)} />
                  <span>{t('Upscale reference first')}</span>
                </label>
                {upscaleFirst ? <Field label={t('Upscale backend')}
                  hint={t('A sharper photo gives a sharper face. If the upscaler fails, the original photo is used.')}>
                  <select className="ga-input" value={upscaleBackend} disabled={busy} onChange={e => setUpscaleBackend(e.target.value)}>
                    <option value="">{t('Auto (routing)')}</option>
                    {(st.upscale_backends || []).map(b => <option key={b.name} value={b.name}>{b.name}</option>)}
                  </select>
                </Field> : null}
              </fieldset>
              <fieldset className="ga-fieldset">
                <legend className="ga-fieldset-title">{t('Parameters')}</legend>
                <div className="ga-form-row">
                  <Field label={t('Strength')} compact tip={t('How strongly the photo replaces the face texture (0–1).')}>
                    <input className="ga-input" style={{ width: 90 }} type="number" min={0} max={1} step={0.05}
                      value={faceControls.strength} disabled={busy}
                      onChange={e => setFaceControls(v => ({ ...v, strength: e.target.valueAsNumber }))} />
                  </Field>
                  <Field label={t('Feather')} compact tip={t('Width of the soft blend at the edge of the face (0–0.5).')}>
                    <input className="ga-input" style={{ width: 90 }} type="number" min={0} max={0.5} step={0.01}
                      value={faceControls.feather} disabled={busy}
                      onChange={e => setFaceControls(v => ({ ...v, feather: e.target.valueAsNumber }))} />
                  </Field>
                  <Field label={t('Render resolution')} compact tip={t('Resolution of the render used to align the photo with the mesh (256–2048).')}>
                    <input className="ga-input" style={{ width: 90 }} type="number" min={256} max={2048} step={1}
                      value={faceControls.render_resolution} disabled={busy}
                      onChange={e => setFaceControls(v => ({ ...v, render_resolution: e.target.valueAsNumber }))} />
                  </Field>
                  <Field label={t('Yaw (degrees)')} compact tip={t('Turns only the alignment view. Leave at 0 unless the model does not face forward (−180–180).')}>
                    <input className="ga-input" style={{ width: 90 }} type="number" min={-180} max={180} step={1}
                      value={faceControls.yaw} disabled={busy}
                      onChange={e => setFaceControls(v => ({ ...v, yaw: e.target.valueAsNumber }))} />
                  </Field>
                </div>
              </fieldset>
            </div>
            <div className="ga-modal-footer">
              <button type="button" className="ga-btn" disabled={busy} onClick={() => setFaceOpen(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-primary"
                disabled={pending || !faceCheck?.ok || !faceCheck.runnable || !Number.isFinite(faceControls.strength) || faceControls.strength < 0 || faceControls.strength > 1 || !Number.isFinite(faceControls.feather) || faceControls.feather < 0 || faceControls.feather > 0.5 || !Number.isInteger(faceControls.render_resolution) || faceControls.render_resolution < 256 || faceControls.render_resolution > 2048 || !Number.isFinite(faceControls.yaw) || faceControls.yaw < -180 || faceControls.yaw > 180}
                onClick={applyFaceRetexture}>{t('Start face retexture')}</button>
            </div>
          </div>
        </div>, document.body) : null}
      {revertFaceOpen ? createPortal(
        <div className="ga-modal-backdrop" onClick={() => { if (!busy) setRevertFaceOpen(false) }}>
          <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Revert face retexture')}
            style={{ maxWidth: 520 }} onClick={e => e.stopPropagation()}>
            <div className="ga-modal-header">{t('Revert face retexture')}</div>
            <div className="ga-modal-body">
              <p>{t('Restore the model snapshot from {time}?').replace('{time}', model?.face_retexture_snapshot?.created_at ? formatDateTime(model.face_retexture_snapshot.created_at, clockSettings()) : t('Unknown'))}</p>
              <p>{t('This also resets all later changes to this model, including re-rigging, extension bones and distance meshes. No generation job is started.')}</p>
            </div>
            <div className="ga-modal-footer">
              <button type="button" className="ga-btn" disabled={busy} onClick={() => setRevertFaceOpen(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-primary" disabled={pending || !model?.face_retexture_snapshot?.ok} onClick={revertFaceRetexture}>{t('Revert face retexture')}</button>
            </div>
          </div>
        </div>, document.body) : null}
      {rerigOpen ? createPortal(
        <div className="ga-modal-backdrop" onClick={() => { if (!busy) setRerigOpen(false) }}>
          <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Re-rig from mesh')}
            style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()}>
            <div className="ga-modal-header">{t('Re-rig from mesh')}</div>
            <div className="ga-modal-body ga-form">
              <p className="ga-hint">{t('Reuses the retained mesh and rebuilds the rig, extension bones and existing low tier.')}</p>
              <label>{t('Rigger')}
                <select className="ga-input" value={rerigBackend} disabled={busy} onChange={e => setRerigBackend(e.target.value)}>
                  <option value="">{t('Auto (routing)')}</option>
                  {(st.rig_backends || []).map(b => <option key={b.name} value={b.name}>{b.name}{b.model ? ` · ${b.model}` : ''}</option>)}
                </select>
              </label>
            </div>
            <div className="ga-modal-footer">
              <button type="button" className="ga-btn" disabled={busy} onClick={() => setRerigOpen(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-primary" disabled={pending} onClick={rerig}>{t('Re-rig from mesh')}</button>
            </div>
          </div>
        </div>, document.body) : null}
      <div role="group" aria-label={t('Model')}>
        <div className="ga-form-section-label">{t('Model')}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={pending || !st.has_input}
            onClick={openDialog}
            title={!st.has_input ? t('No T-pose render for the current outfit — generate it first') : undefined}
          >
            {pending ? t('Generating…') : owned ? t('Regenerate') : t('Generate')}
          </button>
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            disabled={pending}
            onClick={() => fileRef.current?.click()}
          >
            {owned ? t('Upload (replace)') : t('Upload GLB/FBX')}
          </button>
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
          <button type="button" className="ga-btn ga-btn-sm" disabled={pending}
            onClick={() => { setUpscaleFirst(!!st.upscale_runnable); setUpscaleBackend(''); setFaceBackend(''); setFaceCheck(null); setFaceControls({ strength: 1, feather: 0.18, render_resolution: 768, yaw: 0 }); setFaceOpen(true) }}>
            {t('Face retexture…')}
          </button>
          {model?.face_retexture_snapshot?.ok ? <button type="button" className="ga-btn ga-btn-sm" disabled={pending}
            onClick={() => setRevertFaceOpen(true)}>{t('Revert face retexture…')}</button> : null}
          <button type="button" className="ga-btn ga-btn-sm"
            disabled={pending || !model?.has_unrigged_source}
            title={!model?.has_unrigged_source ? t('No retained unrigged mesh source. Generate a new model to enable re-rigging.') : undefined}
            onClick={() => { setRerigBackend(''); setRerigOpen(true) }}>
            {t('Re-rig from mesh…')}
          </button>
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
          {model && !model.has_unrigged_source ? <span className="ga-hint">{t('No retained unrigged mesh source. Generate a new model to enable re-rigging.')}</span> : null}
        </div>
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
          {/* Pre-warm the whole wardrobe: one T-pose render + mesh per saved
              outfit, without dressing the character. */}
          <button
            type="button"
            className="ga-btn ga-btn-sm"
            onClick={() => setBatchOpen(true)}
            title={t('Renders the T-pose reference and the mesh for every saved outfit — the character keeps wearing what it wears.')}
          >
            ⚙ {t('All outfits…')}
          </button>
          {st.extension_groups?.length ? (
          <button type="button" className="ga-btn ga-btn-sm" disabled={pending || !canMeasure}
            onClick={queueExtensions}>{t('Rebuild extension bones for all models')}</button>
          ) : null}
        </div>
      {jobOpen ? (
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
