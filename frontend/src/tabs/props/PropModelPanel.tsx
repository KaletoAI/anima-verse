/**
 * PropModelPanel — the mesh gallery of ONE model variant of a prop.
 *
 * A prop keeps SEVERAL meshes like a building or a room does (the shared
 * gallery, app/core/model_store.py): one active file per resolution tier
 * (`full` / `low`), plus every older run. The panel lists them, previews any
 * of them in the detail viewer above, assigns a file to a tier, uploads a GLB
 * into a chosen tier, reduces one to a low variant (mesh→mesh) and deletes
 * single files. Its counterpart on the world tab is `BuildingModelPanel`; the
 * rows themselves are the shared `ModelGallery` components.
 *
 * Since E2.3 a prop carries several such galleries — one per MODEL VARIANT,
 * picked in `PropVariantStrip` above. Every call here therefore goes to the
 * variant-scoped routes (`/world/props/{id}/variants/{i}/…`); the unqualified
 * ones remain on the server as the shorthand for the primary variant, but a
 * panel that used them would silently edit variant 1 while the admin looks at
 * variant 3.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  MeshBackendDialog, type FaceTargets, type MeshBackend, type MeshGenerateOpts,
} from '../../components/MeshBackendDialog'
import {
  BuildDistanceMeshButton, DEFAULT_MODEL_TIER, ModelGalleryRow, NoModelRow,
  TierPicker, TierSummary,
  type BlenderStatus, type GalleryModel, type ModelTier,
} from '../../components/ModelGallery'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface PropModelInfo {
  models?: GalleryModel[]
  tiers?: string[]
  none_selected?: boolean
  /** mesh→mesh aliases (category mesh2mesh); empty = the low-variant action
   *  stays disabled. */
  shrink_backends?: MeshBackend[]
  /** Blender refinement state — the gate for the CPU distance-mesh action. */
  blender?: BlenderStatus
}

export function PropModelPanel({ propId, variant, reloadKey, preview, onPreview,
  onChanged, pending = false, faceTargets = {}, onGenerating }: {
  propId: string
  /** Index of the model variant this gallery belongs to (0 = the first one;
   *  the primary variant is the first ACTIVE one, which the strip marks). */
  variant: number
  /** Bumped by the container when a generation finished — reloads the list. */
  reloadKey: number
  /** Filename the detail viewer shows ('' = the active model). */
  preview: string
  onPreview: (filename: string) => void
  /** Reload the prop record — selecting/deleting a mesh changes has_model and
   *  may re-measure the dims. */
  onChanged: () => Promise<unknown>
  /** A generation of THIS VARIANT is running (server state, from the
   *  container) — the gallery below belongs to one variant, and a run in
   *  another one blocks nothing here. */
  pending?: boolean
  /** What THIS variant states it should cost in triangles (v2 E5). The
   *  distance-mesh button names the low budget, the reduction dialog opens on
   *  it — both would otherwise say nothing about how small the result gets. */
  faceTargets?: FaceTargets
  /** Start the container's pending poll — a low variant runs in the
   *  background like every mesh job. */
  onGenerating?: () => void
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(propId)
  // Everything this panel touches belongs to ONE variant — one base, so a
  // route can never be reached unqualified by accident.
  const base = `/world/props/${enc}/variants/${variant}`
  const [info, setInfo] = useState<PropModelInfo | null>(null)
  const [armedDel, setArmedDel] = useState<string | null>(null)
  const [uploadTier, setUploadTier] = useState<ModelTier>(DEFAULT_MODEL_TIER)
  const uploadRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      setInfo(await apiGet<PropModelInfo>(`${base}/models`))
    } catch {
      setInfo(null)
    }
  }, [base])

  useEffect(() => {
    setArmedDel(null)
    void load()
  }, [load, reloadKey])

  const select = useCallback(async (filename: string, tier: ModelTier) => {
    try {
      await apiPost(`${base}/models/select`, { file: filename, tier })
      await load()
      await onChanged()
      toast(t('Active model set'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [base, load, onChanged, t, toast])

  const remove = useCallback(async (filename: string) => {
    setArmedDel(null)
    try {
      await apiDelete(`${base}/models?file=${encodeURIComponent(filename)}`)
      if (preview === filename) onPreview('')
      await load()
      await onChanged()
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [base, preview, onPreview, load, onChanged, t, toast])

  // Upload a GLB as a NEW mesh of the chosen tier (validated server-side;
  // surface the 422 reasons instead of a bare status code). The variant route
  // takes the tier as a FORM field, not as a query parameter.
  const upload = useCallback(async (file: File) => {
    if (!file) return
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('tier', uploadTier)
      const res = await fetch(`${base}/upload`,
        { method: 'POST', body: fd, credentials: 'same-origin' })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const errs: string[] = Array.isArray(body?.detail?.errors) ? body.detail.errors : []
        throw new Error(errs.length ? errs.join(' · ')
          : (body?.detail?.toString?.() || `HTTP ${res.status}`))
      }
      onPreview('')
      await load()
      await onChanged()
      toast(t('Saved'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [base, uploadTier, onPreview, load, onChanged, t, toast])

  // Stored mesh waiting in the low-variant dialog (mesh→mesh reduction of
  // THAT file — the prop's dims stay untouched, they belong to the full mesh).
  const [shrinkFile, setShrinkFile] = useState<string | null>(null)
  const shrinkBackends = info?.shrink_backends || []
  const shrink = useCallback((backend: string, opts?: MeshGenerateOpts) => {
    const file = shrinkFile
    setShrinkFile(null)
    if (!file) return
    void apiPost<{ status?: string }>(`${base}/models/shrink`,
      { file, backend,
        ...(opts?.face_num ? { face_num: opts.face_num } : {}),
        ...(opts?.texture_size ? { texture_size: opts.texture_size } : {}) })
      .then((d) => {
        toast(d?.status === 'already_running'
          ? t('This model is already being reduced.')
          : t('Creating the low variant…'))
        onGenerating?.()
      })
      .catch((e) => { toast(t('Error') + ': ' + (e as Error).message, 'error') })
  }, [shrinkFile, base, onGenerating, t, toast])

  const models = info?.models || []
  const tiers = info?.tiers || []
  // The row the viewer shows: the explicit preview, else the active file.
  const shownFile = models.find((m) => m.filename === preview)?.filename
    || models.find((m) => m.active)?.filename
    || ''

  return (
    <>
      <MeshBackendDialog
        open={shrinkFile !== null}
        title={t('Create low variant')}
        hint={t('The stored mesh itself is reduced (mesh→mesh) — no new generation, no source image. The result becomes this gallery’s “low” model.')}
        backends={shrinkBackends}
        defaultBackend={shrinkBackends.length === 1 ? shrinkBackends[0].name : ''}
        defaultTextureSize={1024}
        generateLabel={t('Create')}
        // The reduction IS this variant's distance mesh, so it opens on the
        // budget the variant states for THAT (v2 E5). It goes into the
        // dialog's `high` slot because this dialog has no tier choice: its one
        // face field IS the target of this run, and that target is the low
        // budget.
        faceTargets={{ high: faceTargets.low }}
        onGenerate={shrink}
        onClose={() => setShrinkFile(null)}
      />
      {/* Which variant these rows belong to — the strip above selects it, and
          without the reminder a gallery of four files reads as "the prop's"
          rather than "this variant's". */}
      <div className="ga-form-section-label">
        {t('3D models')} · {t('Variant')} {variant + 1}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <TierSummary tiers={info?.tiers} />
        {/* The CPU way to the missing low mesh — no backend, no queue, and
            the only one that works without a mesh→mesh alias. */}
        {tiers.includes('full') ? (
          <BuildDistanceMeshButton
            url={`${base}/models/lod`}
            hasLow={tiers.includes('low')}
            blender={info?.blender}
            disabled={pending}
            targetFaces={faceTargets.low || 0}
            onDone={async () => { await load(); await onChanged() }}
          />
        ) : null}
      </div>
      {models.length === 0 ? (
        <span className="ga-hint">
          {/* "Generate" (🧊) appends ANOTHER variant since E2.3 — the action
              that fills THIS slot is the re-mesh beside the source image. */}
          {t('No mesh in this variant yet — mesh the source image into it (⚙ “3D from this image”) or upload a GLB.')}
        </span>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <NoModelRow
            noneSelected={!!info?.none_selected}
            onSelect={() => { void select('', DEFAULT_MODEL_TIER) }}
          />
          {models.map((m) => (
            <ModelGalleryRow
              key={m.filename}
              model={m}
              shown={m.filename === shownFile}
              armedDelete={armedDel === m.filename}
              onPreview={() => onPreview(m.filename)}
              onSelect={(tier) => { void select(m.filename, tier) }}
              onArmDelete={setArmedDel}
              onDelete={() => { void remove(m.filename) }}
              onShrink={() => setShrinkFile(m.filename)}
              shrinkAvailable={shrinkBackends.length > 0}
              shrinkPending={pending}
            />
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm"
          onClick={() => uploadRef.current?.click()}
          title={t('Upload a GLB as a new mesh of the selected variant.')}>
          ⬆ {t('Upload model')}
        </button>
        <input ref={uploadRef} type="file" accept=".glb" style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void upload(f)
            e.target.value = ''
          }} />
        <TierPicker value={uploadTier} onChange={setUploadTier} />
        <span className="ga-hint">
          {t('Clicking a row previews that mesh; the tier buttons decide which file the 3D clients get.')}
        </span>
      </div>
    </>
  )
}
