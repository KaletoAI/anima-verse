/**
 * ModelFaceActions — the face and rig steps of ONE model with a retained
 * unrigged source, in the tab where that model lives: the Base body tab on
 * the base-body pipeline (the base body owns the face; every outfit model is
 * painted onto it), the 3D tab off it (each outfit model has its own source).
 *
 * The chain these act on (app/core/model3d.py): mesher → FACE CLEANUP
 * (app/core/face_cleanup.py, lashes + lips, on the source before it is
 * stored) → face retexture ("Improve face before rigging", or the dialog
 * here) → rig → normalize, extension bones, collision capsules.
 *
 * - Switches (POST /characters/{n}/model3d/options): `face_cleanup` and
 *   `face_before_rig` — they decide the NEXT mesher run.
 * - "Re-apply face cleanup…" (POST .../model3d/face-cleanup): brings the
 *   cleanup onto the STORED source and rebuilds what follows it; the server
 *   says which hub jobs that costs (`face_cleanup.jobs`), the dialog repeats
 *   it before anything starts.
 * - "Face retexture…" (POST .../model3d/face-retexture, check + photo
 *   preview first), "Revert face retexture…" (.../face-retexture/revert) and
 *   "Re-rig…" (.../model3d/rerig) — moved here unchanged from FieldModel3D.
 *
 * On the pipeline every face/rig route acts on the base signature whatever
 * the caller sends (characters.py `_face_retexture_signature`, rerig).
 * The caller owns the status (`st`, GET .../model3d) and its poll: `onStarted`
 * asks it to poll until the run ends; completion toasts are raised here.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Field } from '@anima/player-ui'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { clockSettings, formatDateTime, useClockSettings } from '../../lib/clockFormat'
import type { Model3DInfo, Model3DStatus } from './FieldModel3D'

/** The face cleanup of the retained source (server `model3d.face_cleanup_state`). */
export interface FaceCleanupState {
  signature: string
  enabled: boolean
  humanoid: boolean
  stored: boolean
  status: 'applied' | 'skipped' | 'failed' | 'missing' | 'none'
  summary: string
  version?: number | null
  current_version: number
  /** What a re-apply runs after the cleanup. */
  follow_up: 'face_retexture' | 'rerig'
  /** Its hub jobs, fixed English phrases. */
  jobs: string[]
  can_reapply: boolean
  /** Why a re-apply is refused (English), '' when it can run. */
  blocked: string
  running: boolean
  result?: { ok: boolean; error?: string; task_id: string; follow_up: string } | null
}

/** The face fields of the model the face acts on (`model3d.face_info`). */
export type FaceFields = Pick<Model3DInfo, 'face_retexture' | 'face_retexture_revert'
  | 'face_retexture_snapshot' | 'face_retexture_compare_url' | 'face_signature'>

interface FaceRetextureFinding {
  code: string
  message: string
  fix?: string
  detail?: string
}
interface FaceRetextureCheck {
  photo_controls: 'hub' | 'local'
  skin_recolor_supported: boolean
  reference: 'face' | 'front'
  face_available: boolean
  face_problem?: FaceRetextureFinding | null
  ok: boolean
  problems: FaceRetextureFinding[]
  warnings: FaceRetextureFinding[]
  runnable: boolean
  runnable_problems: FaceRetextureFinding[]
}

const CLEANUP_STATUS: Record<FaceCleanupState['status'], string> = {
  applied: 'Applied',
  skipped: 'Skipped',
  failed: 'Failed',
  missing: 'Not recorded (made before the step)',
  none: 'No stored mesh',
}

const WARN = { color: 'var(--ga-warn, #c77d0a)' }

export function ModelFaceActions({ character, st, face, signature, cleanup, hasModel, canRerig,
  rerigBlocked, onReload, onStarted }: {
  character: string
  st: Model3DStatus
  /** Face fields of the model the face acts on; null without a model. */
  face: FaceFields | null
  /** Signature the face routes are called with (mapped to the base on the pipeline). */
  signature: string
  cleanup: FaceCleanupState | null | undefined
  hasModel: boolean
  canRerig: boolean
  /** Why a re-rig is not possible (shown as the button's tooltip). */
  rerigBlocked: string
  /** Re-read the status (after a switch or a revert). */
  onReload: () => Promise<unknown> | void
  /** A run started: the caller polls until `st.pending` clears. */
  onStarted: () => void
}) {
  useClockSettings()
  const { t, lang } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const pipeline = !!st.pipeline
  const humanoid = !st.rig || st.rig === 'mixamo'
  const [busy, setBusy] = useState(false)
  const pending = !!st.pending || busy

  // Completion toasts: the task id of the run started here, per kind.
  const startedRef = useRef<{ kind: 'rerig' | 'face' | 'cleanup'; task: string } | null>(null)
  useEffect(() => {
    const started = startedRef.current
    if (!started || st.pending) return
    const result = started.kind === 'rerig' ? st.rerig_result
      : started.kind === 'face' ? st.face_retexture_result : st.face_cleanup?.result
    if (!result || result.task_id !== started.task) return
    startedRef.current = null
    const label = started.kind === 'rerig' ? t('Re-rig') : started.kind === 'face' ? t('Face retexture') : t('Face cleanup')
    toast(result.ok ? `${label}: ${t('Done')}` : `${label}: ${t('Failed')} · ${result.error || t('Error')}`,
      result.ok ? undefined : 'error')
  }, [st, t, toast])
  // The click's own busy flag ends with the next status read (by then the
  // server reports the run as `pending`).
  useEffect(() => { setBusy(false) }, [st])

  const setOption = useCallback(async (key: 'face_before_rig' | 'face_cleanup', value: boolean) => {
    try {
      await apiPost(`/characters/${enc}/model3d/options`, { [key]: value })
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
    await onReload()
  }, [enc, onReload, t, toast])

  // --- Re-apply face cleanup -------------------------------------------
  const [cleanupOpen, setCleanupOpen] = useState(false)
  const reapplyCleanup = async () => {
    if (pending) return
    setBusy(true)
    try {
      const d = await apiPost<{ status?: string; task_id?: string }>(
        `/characters/${enc}/model3d/face-cleanup?${new URLSearchParams({ signature })}`, {})
      setCleanupOpen(false)
      if (d.status === 'already_running') {
        toast(t('A 3D model generation is already running for this character'))
        setBusy(false)
        return
      }
      startedRef.current = { kind: 'cleanup', task: d.task_id || '' }
      toast(t('Face cleanup running…'))
      onStarted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }

  // --- Re-rig -----------------------------------------------------------
  const [rerigOpen, setRerigOpen] = useState(false)
  const [rerigBackend, setRerigBackend] = useState('')
  const rerig = async () => {
    if (pending) return
    const q = new URLSearchParams({ signature: st.pipeline?.base_signature || signature })
    if (rerigBackend) q.set('backend', rerigBackend)
    setBusy(true)
    try {
      const result = await apiPost<{ task_id?: string }>(`/characters/${enc}/model3d/rerig?${q}`, {})
      setRerigOpen(false)
      startedRef.current = { kind: 'rerig', task: result.task_id || '' }
      toast(t('Re-rigging…'))
      onStarted()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      setBusy(false)
    }
  }

  // --- Face retexture (dialog with check + photo preview) ----------------
  const [facePhoto, setFacePhoto] = useState({ balance: 1, tone_match: 1, skin_recolor: 1, brightness: 1 })
  const [photoPreviewResult, setPhotoPreview] = useState<{ key?: string; original?: string; adjusted?: string; error?: string }>({})
  const photoPreviewRequest = useRef(0)
  const [faceOpen, setFaceOpen] = useState(false)
  const [faceBackend, setFaceBackend] = useState('')
  const [faceReference, setFaceReference] = useState<'' | 'face' | 'front'>('')
  const [upscaleFirst, setUpscaleFirst] = useState(true)
  const [upscaleBackend, setUpscaleBackend] = useState('')
  const [faceCheck, setFaceCheck] = useState<FaceRetextureCheck | null>(null)
  const [faceCheckError, setFaceCheckError] = useState('')
  const [faceControls, setFaceControls] = useState({ strength: 1, feather: 0.18, render_resolution: 768, yaw: 0 })
  const [revertFaceOpen, setRevertFaceOpen] = useState(false)

  const faceSignature = face?.face_signature || signature
  const hubPhotoControls = faceCheck?.photo_controls === 'hub'
  const photoPreviewKey = JSON.stringify([faceOpen, enc, faceSignature, faceReference, facePhoto, faceBackend, hubPhotoControls])
  const photoPreview = photoPreviewResult.key === photoPreviewKey ? photoPreviewResult : {}
  const photoPreviewReady = !!photoPreview.adjusted && !photoPreview.error
  useEffect(() => {
    if (!faceOpen) return
    let cancelled = false
    setFaceCheck(null)
    setFaceCheckError('')
    const query = new URLSearchParams({ signature: faceSignature, backend: faceBackend, reference: faceReference, lang })
    apiGet<FaceRetextureCheck>(`/characters/${enc}/model3d/face-retexture/check?${query}`)
      .then(result => {
        if (cancelled) return
        setFaceCheck(result)
        if (!faceReference) {
          setFaceReference(result.reference)
          setUpscaleFirst(result.reference === 'front' && !!st.upscale_runnable)
        }
      })
      .catch(error => { if (!cancelled) setFaceCheckError((error as Error).message) })
    return () => { cancelled = true }
  }, [faceOpen, faceSignature, faceBackend, faceReference, st.upscale_runnable, enc, lang])

  useEffect(() => {
    const request = ++photoPreviewRequest.current
    if (!faceOpen || !faceReference) return
    setPhotoPreview({})
    const controller = new AbortController()
    const urls: string[] = []
    const timer = window.setTimeout(async () => {
      const load = async (balance: number, brightness: number) => {
        const q = new URLSearchParams({ signature: faceSignature, reference: faceReference, backend: faceBackend, balance: String(balance), brightness: String(brightness) })
        const response = await fetch(`/characters/${enc}/model3d/face-photo-preview?${q}`, { signal: controller.signal })
        if (!response.ok) {
          const body = await response.json()
          throw new Error(body.detail || response.statusText)
        }
        const blob = await response.blob()
        controller.signal.throwIfAborted()
        const url = URL.createObjectURL(blob)
        urls.push(url)
        return url
      }
      try {
        const original = await load(0, 1)
        const adjusted = await load(faceReference === 'front' && !hubPhotoControls ? 0 : facePhoto.balance, facePhoto.brightness)
        if (!controller.signal.aborted && request === photoPreviewRequest.current) setPhotoPreview({ key: photoPreviewKey, original, adjusted })
      } catch (error) {
        if (!controller.signal.aborted && request === photoPreviewRequest.current) setPhotoPreview({ key: photoPreviewKey, error: (error as Error).message })
      }
    }, 300)
    return () => { photoPreviewRequest.current = request + 1; window.clearTimeout(timer); controller.abort(); urls.forEach(URL.revokeObjectURL) }
  }, [faceOpen, faceReference, faceSignature, facePhoto, faceBackend, hubPhotoControls, enc, photoPreviewKey])

  const openFaceDialog = () => {
    setFacePhoto({ balance: st.options?.face_photo?.balance ?? 1, tone_match: st.options?.face_photo?.tone_match ?? 1,
      skin_recolor: st.options?.face_photo?.skin_recolor ?? 1, brightness: st.options?.face_photo?.brightness ?? 1 })
    setFaceReference('')
    setUpscaleFirst(!!st.upscale_runnable)
    setUpscaleBackend('')
    setFaceBackend('')
    setFaceCheck(null)
    setFaceControls({ strength: 1, feather: 0.18, render_resolution: 768, yaw: 0 })
    setFaceOpen(true)
  }

  const applyFaceRetexture = async () => {
    if (pending || !faceCheck?.ok || !faceCheck.runnable || !photoPreviewReady) return
    const query = new URLSearchParams({ signature: faceSignature, backend: faceBackend, reference: faceReference, lang })
    query.set('reference', faceReference || faceCheck.reference)
    query.set('upscale', String(upscaleFirst))
    query.set('upscale_backend', upscaleBackend)
    query.set('balance', String(faceReference === 'front' && !hubPhotoControls ? 0 : facePhoto.balance))
    query.set('brightness', String(facePhoto.brightness))
    query.set('tone_match', String(facePhoto.tone_match))
    query.set('skin_recolor', String(facePhoto.skin_recolor))
    for (const [key, value] of Object.entries(faceControls)) query.set(key, String(value))
    setBusy(true)
    try {
      const result = await apiPost<{ ok?: boolean; status?: string; task_id?: string; problems?: FaceRetextureFinding[] }>(
        `/characters/${enc}/model3d/face-retexture?${query}`, {})
      if (result.ok === false) throw new Error((result.problems || []).map(p => `${p.message} ${p.fix || ''}`).join(' · '))
      setFaceOpen(false)
      startedRef.current = { kind: 'face', task: result.task_id || '' }
      toast(t('Face retexture running…'))
      onStarted()
    } catch (error) {
      toast(t('Error') + ': ' + (error as Error).message, 'error')
      setBusy(false)
    }
  }

  const revertFaceRetexture = async () => {
    if (pending) return
    setBusy(true)
    const query = new URLSearchParams({ signature: faceSignature, lang })
    try {
      const request = apiPost<{ ok: boolean; error?: string }>(`/characters/${enc}/model3d/face-retexture/revert?${query}`, {})
      // A re-rig revert holds the request for the whole rig job: poll
      // meanwhile, so the tab shows the run and reloads the model when it
      // ends even if this response never arrives.
      if (face?.face_retexture_revert === 'rerig') onStarted()
      const result = await request
      if (!result.ok) throw new Error(result.error || t('Face retexture revert failed'))
      setRevertFaceOpen(false)
      toast(t('Face retexture reverted'))
      await onReload()
    } catch (error) {
      toast(t('Error') + ': ' + (error as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const fr = face?.face_retexture
  const up = fr?.upscale
  const photo = fr?.status === 'applied' && fr.photo ? fr.photo : null
  const photoText = photo ? `${photo.balance ? ` · ${t('Light balance')} ${Math.round(photo.balance * 100)} %` : ''}${photo.tone_match != null && photo.tone_match !== 1 ? ` · ${t('Skin tone match')} ${Math.round(photo.tone_match * 100)} %` : ''}${typeof photo.skin_recolor === 'number' && photo.skin_recolor !== 1 ? ` · ${t('Skin colour correction')} ${Math.round(photo.skin_recolor * 100)} %` : ''}${photo.brightness !== 1 ? ` · ${t('Face brightness')} ${Math.round(photo.brightness * 100)} %` : ''}${photo.applied_on === 'hub' ? ' (hub)' : photo.applied_on === 'none' ? '' : ' (local)'}` : ''
  const optionsDisabled = !humanoid
  const jobsText = (cleanup?.jobs || []).map((job) => t(job)).join(' → ')
  const notOnStored = !!cleanup?.enabled && !!cleanup.stored && cleanup.status !== 'applied'

  return (
    <div className="ga-face-actions" role="group" aria-label={t('Face and rig')}>
      <label className="ga-check-row"
        title={!humanoid ? t('Humanoid models only.')
          : t('Before the face retexture, lash flaps the mesher built from painted lashes are pressed back onto the lids and over-saturated lips in the raw texture are neutralised. Recorded in the model overview as "Face cleanup". Humanoid models only.')}>
        <input type="checkbox" checked={!!st.options?.face_cleanup} disabled={optionsDisabled || pending}
          onChange={(e) => { void setOption('face_cleanup', e.target.checked) }} />
        <span>{t('Face cleanup before the face retexture (lashes, lips)')}</span>
      </label>
      {cleanup && cleanup.status !== 'none' ? (
        <div className="ga-face-actions-row">
          <span className="ga-hint ga-face-actions-state"
            title={[cleanup.summary, cleanup.version ? `v${cleanup.version}` : ''].filter(Boolean).join(' · ') || undefined}
            style={cleanup.status === 'failed' || notOnStored ? WARN : undefined}>
            {t('Stored mesh')}: {t(CLEANUP_STATUS[cleanup.status] || cleanup.status)}
            {notOnStored ? ` · ${t('not applied to the stored mesh')}` : ''}
          </span>
          <button type="button" className="ga-btn ga-btn-sm"
            disabled={pending || !cleanup.can_reapply}
            title={cleanup.can_reapply
              ? `${t('Cleans the stored mesh, then rebuilds')}: ${jobsText}`
              : t(cleanup.blocked)}
            onClick={() => setCleanupOpen(true)}>
            {t('Re-apply face cleanup…')}
          </button>
        </div>
      ) : null}
      {cleanup?.result && !cleanup.running ? (
        <div className="ga-hint" role="status" style={cleanup.result.ok ? undefined : WARN}>
          {cleanup.result.ok ? t('Face cleanup re-applied') : `${t('Face cleanup failed')}: ${cleanup.result.error || t('Error')}`}
        </div>
      ) : null}
      <label className="ga-check-row"
        title={!humanoid ? t('Humanoid models only.')
          : pipeline ? t('The base body model gets the face correction (upscaler + face retexture) before its first rig; outfit models take the face from it.')
          : t('New meshes get the face correction (upscaler + face retexture) before the first rig, so the rigger runs once. Independent of auto-generate. Humanoid models only.')}>
        <input type="checkbox" checked={!!st.options?.face_before_rig} disabled={optionsDisabled || pending}
          onChange={(e) => { void setOption('face_before_rig', e.target.checked) }} />
        <span>{t('Improve face before rigging')}</span>
      </label>
      <div className="ga-face-actions-row">
        <button type="button" className="ga-btn ga-btn-sm" disabled={pending || !hasModel || !humanoid}
          title={t('Corrects the face texture from the original photo, then rebuilds the rig and derived meshes. Each run starts from the original unrigged mesh.')}
          onClick={openFaceDialog}>
          {t('Face retexture…')}
        </button>
        {face?.face_retexture_revert ? <button type="button" className="ga-btn ga-btn-sm" disabled={pending}
          onClick={() => setRevertFaceOpen(true)}>{t('Revert face retexture…')}</button> : null}
        <button type="button" className="ga-btn ga-btn-sm"
          disabled={pending || !canRerig}
          title={!canRerig ? rerigBlocked
            : pipeline ? t('Re-rigs the base body; every outfit model is rebuilt from it.') : undefined}
          onClick={() => { setRerigBackend(''); setRerigOpen(true) }}>
          {pipeline ? t('Re-rig base body…') : t('Re-rig from mesh…')}
        </button>
      </div>
      {!st.pending && st.rerig_result ? <div className="ga-hint" role="status">
        {st.rerig_result.ok ? t('Re-rig completed') : `${t('Re-rig failed')}: ${st.rerig_result.error || t('Error')}`}
      </div> : null}
      {!st.pending && st.face_retexture_result ? <div className="ga-hint" role="status">
        {st.face_retexture_result.ok ? t('Face retexture completed') : `${t('Face retexture failed')}: ${st.face_retexture_result.error || t('Error')}`}
      </div> : null}
      {fr ? (
        // Short: status and time; every detail (photo settings, reference,
        // backend, job) is the tooltip.
        <div className="ga-hint" role="status" title={[
          fr.error || fr.reason || '',
          photoText.replace(/^ · /, ''),
          fr.reference === 'face' ? t('Face view') : '',
          fr.backend || '', fr.job_id || '',
        ].filter(Boolean).join(' · ') || undefined}>
          {fr.status === 'applied' ? t('Face retexture applied') : fr.status === 'failed' ? t('Face retexture failed') : fr.status === 'skipped' ? t('Skipped') : t('Face retexture reverted')}
          {fr.status === 'failed' && fr.error ? ` · ${fr.error}` : ''}
          {fr.at ? ` · ${formatDateTime(fr.at, clockSettings())}` : ''}
          {face?.face_retexture_compare_url ? <> · <a href={face.face_retexture_compare_url} target="_blank" rel="noopener noreferrer">{t('Comparison image')}</a></> : null}
        </div>
      ) : null}
      {/* A face-view reference is never upscaled: the line above already says "Face view". */}
      {up && !(fr?.reference === 'face' && up.status === 'off') ? <p className="ga-hint" role="status">
        {up.status === 'failed'
          ? `${t('Reference upscale failed — using original photo')}${up.busy ? ` · ${t('Busy')}` : ''} · ${up.error || ''}`
          : up.status === 'applied'
            ? `${t('Reference upscaled')} · ${up.backend || ''} · ${up.in?.join('×')} → ${up.out?.join('×')}${up.cached ? ` · ${t('Cached')}` : ''}`
            : up.status === 'skipped' ? t('Reference upscale skipped — already large enough') : t('Reference upscale off')}
      </p> : null}
      {fr?.dark_gate?.warning ? <p className="ga-hint" role="status" style={WARN}>
        {t('The face projection left dark texels in the face (a black eye socket?) — check the comparison image; a retry with another yaw did not fix it')}
        {typeof fr.dark_gate.dark_share === 'number' ? ` · ${(fr.dark_gate.dark_share * 100).toFixed(1)} %` : ''}
      </p> : null}
      {fr?.face_texture_lost ? <p className="ga-hint" role="status">
        {t('The rigger changed the baked face texture — the face correction may be lost. Revert restores the previous model.')}
      </p> : null}

      {cleanupOpen && cleanup ? createPortal(
        <div className="ga-modal-backdrop" onClick={() => { if (!busy) setCleanupOpen(false) }}>
          <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Re-apply face cleanup')}
            style={{ maxWidth: 520 }} onClick={e => e.stopPropagation()}>
            <div className="ga-modal-header">{t('Re-apply face cleanup')}</div>
            <div className="ga-modal-body">
              <p>{t('The stored mesh is cleaned in place (lashes pressed back onto the lids, lips neutralised), then everything after it is rebuilt from it.')}</p>
              <p><strong>{t('Hub jobs')}:</strong> {jobsText}</p>
              <p className="ga-hint">{t('Normalize, extension bones and collision capsules follow the rig locally.')}</p>
              {pipeline ? <p className="ga-hint">{t('Every outfit model is painted onto the base body: each one turns stale and is rebuilt on its next trigger.')}</p> : null}
              {cleanup.status === 'applied' ? <p className="ga-hint">{t('The stored mesh was cleaned by an older version; the new version runs on that mesh.')}</p> : null}
            </div>
            <div className="ga-modal-footer">
              <button type="button" className="ga-btn" disabled={busy} onClick={() => setCleanupOpen(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-primary" disabled={pending || !cleanup.can_reapply}
                onClick={() => { void reapplyCleanup() }}>{t('Re-apply face cleanup')}</button>
            </div>
          </div>
        </div>, document.body) : null}
      {faceOpen ? createPortal(
        <div className="ga-modal-backdrop" onClick={() => { if (!busy) setFaceOpen(false) }}>
          <div className="ga-modal" role="dialog" aria-modal="true" aria-label={t('Face retexture')}
            style={{ maxWidth: 560 }} onClick={e => e.stopPropagation()}>
            <div className="ga-modal-header">{t('Face retexture')}</div>
            <div className="ga-modal-body ga-form">
              <p className="ga-hint">{t('Corrects the face texture from the original photo, then rebuilds the rig and derived meshes. Each run starts from the original unrigged mesh.')}</p>
              {pipeline ? <p className="ga-hint" role="status">{t('Face applies to the base body; outfits are rebuilt.')}</p> : null}
              <fieldset className="ga-fieldset">
                <legend className="ga-fieldset-title">{t('Source check')}</legend>
                <Field label={t('Reference image')}>
                  <select className="ga-input" value={faceReference || faceCheck?.reference || 'front'}
                    disabled={busy || !faceCheck} onChange={e => {
                      const reference = e.target.value as 'face' | 'front'
                      setFaceReference(reference)
                      setUpscaleFirst(reference === 'front' && !!st.upscale_runnable)
                      setFaceCheck(null)
                    }}>
                    <option value="face" disabled={!faceCheck?.face_available}>{t('Face view')}</option>
                    <option value="front">{t('Front view (pose render)')}</option>
                  </select>
                  {faceCheck?.face_problem ? <div className="ga-field-hint">
                    {faceCheck.face_problem.message} {faceCheck.face_problem.fix}
                  </div> : null}
                </Field>
                <Field label={`${t('Light balance')} ${Math.round(facePhoto.balance * 100)} %`}
                  tip={t('Removes broad light from the face photo: side light and, on the hub (GLBFaceRetexture 1.2), the darker face edges that show as a shadow along the projection border. Features stay; nothing is mirrored.')}>
                  <input type="range" min={0} max={100} step={5} value={facePhoto.balance * 100}
                    disabled={busy || (!hubPhotoControls && faceReference !== 'face')}
                    title={!hubPhotoControls && faceReference !== 'face' ? t('Light balance needs the face view (a cut-out head)') : undefined}
                    onChange={e => setFacePhoto(v => ({ ...v, balance: e.target.valueAsNumber / 100 }))} />
                </Field>
                <Field label={`${t('Skin tone match')} ${Math.round(facePhoto.tone_match * 100)} %`}
                  tip={t("Pulls the face's overall skin colour and brightness toward the model's own face skin, so the projection blends in without a seam. Runs on the hub (needs GLBFaceRetexture 1.1.1).")}>
                  <input type="range" min={0} max={100} step={5} value={facePhoto.tone_match * 100}
                    disabled={busy || !hubPhotoControls}
                    title={!hubPhotoControls ? t('the face retexture backend does not support tone match (needs node GLBFaceRetexture >= 1.1)') : undefined}
                    onChange={e => setFacePhoto(v => ({ ...v, tone_match: e.target.valueAsNumber / 100 }))} />
                </Field>
                <Field label={`${t('Skin colour correction')} ${Math.round(facePhoto.skin_recolor * 100)} %`}
                  tip={t("Recolours the model's own skin (face, neck, arms, hands) toward the photo's skin tone — for meshes that came out too red. Clothes and hair stay. Runs on the hub (needs GLBFaceRetexture 1.3).")}>
                  <input type="range" min={0} max={100} step={5} value={facePhoto.skin_recolor * 100}
                    disabled={busy || !faceCheck?.skin_recolor_supported}
                    title={!faceCheck?.skin_recolor_supported ? t('needs GLBFaceRetexture >= 1.3') : undefined}
                    onChange={e => setFacePhoto(v => ({ ...v, skin_recolor: e.target.valueAsNumber / 100 }))} />
                </Field>
                <Field label={`${t('Face brightness')} ${Math.round(facePhoto.brightness * 100)} %`}
                  tip={t("Scales the photo's brightness before projection — lower it when the face looks too bright on the model.")}>
                  <input type="range" min={50} max={150} step={5} value={facePhoto.brightness * 100} disabled={busy}
                    onChange={e => setFacePhoto(v => ({ ...v, brightness: e.target.valueAsNumber / 100 }))} />
                </Field>
                {photoPreview.error ? <div role="alert">{t(photoPreview.error)}</div> : <div style={{ display: 'flex', gap: 12 }}>
                  <div>{t('Original')}{photoPreview.original ? <img src={photoPreview.original} alt={t('Original')} style={{ display: 'block', maxWidth: 160, maxHeight: 160 }} /> : null}</div>
                  <div>{t('Adjusted')}{photoPreview.adjusted ? <img src={photoPreview.adjusted} alt={t('Adjusted')} style={{ display: 'block', maxWidth: 160, maxHeight: 160 }} /> : null}</div>
                </div>}
                {hubPhotoControls ? <div className="ga-field-hint">{t('Light balance and tone match run on the hub with face landmarks; the preview is an approximation without tone match.')}</div> : null}
                {faceCheckError ? <div className="ga-status-danger" role="alert">✗ {faceCheckError}</div> : null}
                {!faceCheck && !faceCheckError ? <div className="ga-hint" role="status">{t('Checking face retexture eligibility…')}</div> : null}
                {faceCheck ? <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {[...faceCheck.problems, ...faceCheck.runnable_problems].map(p => <div key={p.code} role="alert">
                    <div className="ga-status-danger">✗ {p.message}{p.detail ? ` (${p.detail})` : ''}</div>
                    {p.fix ? <div className="ga-field-hint">→ {p.fix}</div> : null}
                  </div>)}
                  {faceCheck.warnings.map(w => <div key={w.code} className="ga-field-warn">⚠ {w.message}</div>)}
                  {faceCheck.ok && faceCheck.runnable && photoPreviewReady ? <div className="ga-status-ok">✓ {t('Ready for face retexture.')}</div> : null}
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
                disabled={pending || !faceCheck?.ok || !faceCheck.runnable || !photoPreviewReady || !Number.isFinite(faceControls.strength) || faceControls.strength < 0 || faceControls.strength > 1 || !Number.isFinite(faceControls.feather) || faceControls.feather < 0 || faceControls.feather > 0.5 || !Number.isInteger(faceControls.render_resolution) || faceControls.render_resolution < 256 || faceControls.render_resolution > 2048 || !Number.isFinite(faceControls.yaw) || faceControls.yaw < -180 || faceControls.yaw > 180}
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
              {face?.face_retexture_revert === 'rerig' ? <p>{t('Re-rig the original mesh without face correction? This starts a rigging job and rebuilds the model.')}</p> : <>
              <p>{t('Restore the model snapshot from {time}?').replace('{time}', face?.face_retexture_snapshot?.created_at ? formatDateTime(face.face_retexture_snapshot.created_at, clockSettings()) : t('Unknown'))}</p>
              <p>{t('This also resets all later changes to this model, including re-rigging, extension bones and distance meshes. No generation job is started.')}</p>
              </>}
            </div>
            <div className="ga-modal-footer">
              <button type="button" className="ga-btn" disabled={busy} onClick={() => setRevertFaceOpen(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-primary" disabled={pending || !face?.face_retexture_revert} onClick={revertFaceRetexture}>{t('Revert face retexture')}</button>
            </div>
          </div>
        </div>, document.body) : null}
      {rerigOpen ? createPortal(
        <div className="ga-modal-backdrop" onClick={() => { if (!busy) setRerigOpen(false) }}>
          <div className="ga-modal" role="dialog" aria-modal="true" aria-label={pipeline ? t('Re-rig base body') : t('Re-rig from mesh')}
            style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()}>
            <div className="ga-modal-header">{pipeline ? t('Re-rig base body') : t('Re-rig from mesh')}</div>
            <div className="ga-modal-body ga-form">
              <p className="ga-hint">{pipeline
                ? t('Re-rigs the base body from its retained mesh. Every outfit model is painted onto the base body, so each one is rebuilt on its next trigger.')
                : t('Reuses the retained mesh and rebuilds the rig, extension bones and existing low tier.')}</p>
              <label>{t('Rigger')}
                <select className="ga-input" value={rerigBackend} disabled={busy} onChange={e => setRerigBackend(e.target.value)}>
                  <option value="">{t('Auto (routing)')}</option>
                  {(st.rig_backends || []).map(b => <option key={b.name} value={b.name}>{b.name}{b.model ? ` · ${b.model}` : ''}</option>)}
                </select>
              </label>
            </div>
            <div className="ga-modal-footer">
              <button type="button" className="ga-btn" disabled={busy} onClick={() => setRerigOpen(false)}>{t('Cancel')}</button>
              <button type="button" className="ga-btn ga-btn-primary" disabled={pending} onClick={rerig}>{pipeline ? t('Re-rig base body') : t('Re-rig from mesh')}</button>
            </div>
          </div>
        </div>, document.body) : null}
    </div>
  )
}
