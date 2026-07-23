/**
 * FieldModel3D — the character's 3D model for the current outfit. ONE model,
 * produced either way: GENERATE it from the T-pose render (mesh backend) or
 * UPLOAD a GLB/FBX. Both write the same per-outfit slot, so the animated
 * preview always shows the current model regardless of where it came from.
 * Rendered template-driven via the section flag `special: "model3d_gen"`.
 *
 * Backend: GET /characters/{n}/model3d (status), POST .../model3d/generate,
 * POST .../model3d/upload, POST .../model3d/rig, GET .../model3d/file (bytes),
 * DELETE .../model3d.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { MeshBackendDialog } from '../../components/MeshBackendDialog'
import { Model3DViewer } from './Model3DViewer'
import { OutfitBatchDialog } from './OutfitBatchDialog'

interface Model3DInfo {
  filename?: string
  format?: string
  rig?: string
  size?: number
  url?: string
  texture_url?: string
  created_at?: string
  backend?: string
  source?: string
  source_filename?: string
}

interface MeshBackend {
  name: string
  model?: string
  cost?: number
  face_num?: number | null
}

interface Model3DStatus {
  signature?: string
  rig?: string
  has_input?: boolean
  model?: Model3DInfo | null
  options?: { no_fingers?: boolean | null; auto_generate?: boolean }
  backends?: MeshBackend[]
  default?: string
  animation_set?: string
  animation_sets?: string[]
  animation_set_derived?: string
  pending?: boolean
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
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [st, setSt] = useState<Model3DStatus>({})
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [clips, setClips] = useState<AnimationClip[]>([])
  const [clipUrl, setClipUrl] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [pendingFbx, setPendingFbx] = useState<File | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const texRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    if (!character) return
    try {
      const d = await apiGet<Model3DStatus>(`/characters/${enc}/model3d`)
      setSt(d)
      return d
    } catch {
      setSt({})
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
    setConfirmDelete(false)
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
    async (force: boolean, backend: string) => {
      if (busy) return
      setDialogOpen(false)
      setBusy(true)
      try {
        const q = new URLSearchParams()
        if (force) q.set('force', '1')
        if (backend) q.set('backend', backend)
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

  // Per-character override of the alias param "no fingers".
  // '' = backend default (never materialized), '1' = on, '0' = off.
  const setNoFingers = useCallback(
    async (raw: string) => {
      const value = raw === '' ? null : raw === '1'
      setSt((prev) => ({ ...prev, options: { ...(prev.options || {}), no_fingers: value } }))
      try {
        const d = await apiPost<{ options: Model3DStatus['options'] }>(
          `/characters/${enc}/model3d/options`, { no_fingers: value })
        setSt((prev) => ({ ...prev, options: d.options }))
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
        load()
      }
    },
    [enc, load, t, toast],
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
  const pending = !!st.pending || busy
  const sizeMb = model?.size ? (model.size / (1024 * 1024)).toFixed(1) : ''
  // Only a Mixamo rig can play the shared clips (humanoid characters).
  const mixamo = (model?.rig || st.rig) !== 'generic'
  const bust = model?.created_at || st.signature || ''

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
  // Cache-bust per combination so a re-generated mesh is re-fetched.
  const viewerUrl = model
    ? `/characters/${enc}/model3d/file?v=${encodeURIComponent(bust)}`
    : ''

  return (
    <div className="ga-form">
      {model ? (
        <>
          <Model3DViewer
            url={viewerUrl}
            format={model.format || 'fbx'}
            clipUrl={mixamo ? clipUrl : ''}
            textureUrl={model.texture_url ? `${model.texture_url}?v=${bust}` : ''}
          />
          {/* The clips of THIS character's set (+ the setless fallbacks). */}
          {myClips.length ? (
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
                {myClips.map((c) => (
                  <option key={c.filename} value={c.url}>
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
          )}
          {/* Mixamo clips need the Mixamo skeleton — a generic rig has none. */}
          {!mixamo ? (
            <div className="ga-hint">
              {t('Generic rig (no standard skeleton) — Mixamo clips will not drive this model.')}
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
            {model.created_at ? ` · ${new Date(model.created_at).toLocaleString()}` : ''}
            {model.source_filename ? ` · ${model.source_filename}` : ''}
          </div>
          {/* Rig only means something for an UPLOAD — a generated model's
              skeleton is fixed by the backend alias. It decides whether the
              shared clips apply. */}
          {model.source === 'upload' ? (
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
      <div className="ga-hint">
        {t('One model per outfit combination — upload a GLB/FBX or generate it from the T-pose render.')}
      </div>
      <label className="ga-check-row"
        title={t('Once the T-pose render of a NEW outfit combination has succeeded, the mesh is generated automatically on the cheapest matching backend — the T-pose is always awaited first.')}>
        <input
          type="checkbox"
          checked={!!st.options?.auto_generate}
          onChange={(e) => setAutoGenerate(e.target.checked)}
        />
        <span>{t('Auto-generate 3D model (cheapest backend)')}</span>
      </label>
      {/* "no fingers" is a humanoid-alias param — the generic ones don't take it. */}
      {mixamo ? (
        <>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <span className="ga-hint" style={{ whiteSpace: 'nowrap' }}>{t('No fingers')}</span>
            <select
              className="ga-input"
              value={st.options?.no_fingers == null ? '' : st.options.no_fingers ? '1' : '0'}
              disabled={pending}
              onChange={(e) => setNoFingers(e.target.value)}
            >
              <option value="">{t('— backend default —')}</option>
              <option value="1">{t('On (no separate fingers)')}</option>
              <option value="0">{t('Off (model the fingers)')}</option>
            </select>
          </label>
          <div className="ga-hint">
            {t('Overrides the mesh backend setting for this character. Takes effect on the next generation — use Regenerate for the current outfit.')}
          </div>
        </>
      ) : null}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={pending || !st.has_input}
          onClick={openDialog}
          title={!st.has_input ? t('No T-pose render for the current outfit — generate it first') : undefined}
        >
          {pending ? t('Generating…') : model ? t('Regenerate') : t('Generate')}
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
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={pending}
          onClick={() => fileRef.current?.click()}
        >
          {model ? t('Upload (replace)') : t('Upload GLB/FBX')}
        </button>
        {model ? (
          <>
            <a className="ga-btn ga-btn-sm" href={`/characters/${enc}/model3d/file`} download>
              {t('Download')}
            </a>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={pending}
              onClick={remove}
              onBlur={() => setConfirmDelete(false)}
            >
              {confirmDelete ? t('Really delete?') : t('Delete')}
            </button>
          </>
        ) : null}
      </div>
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
        onGenerate={(backend) => generate(!!model, backend)}
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
