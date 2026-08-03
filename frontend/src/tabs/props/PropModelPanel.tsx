/**
 * PropModelPanel — the mesh gallery of one prop.
 *
 * A prop keeps SEVERAL meshes like a building or a room does (the shared
 * gallery, app/core/model_store.py): one active file per resolution tier
 * (`full` / `low`), plus every older run. The panel lists them, previews any
 * of them in the detail viewer above, assigns a file to a tier, uploads a GLB
 * into a chosen tier and deletes single files. Its counterpart on the world
 * tab is `BuildingModelPanel`; the rows themselves are the shared
 * `ModelGallery` components.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  DEFAULT_MODEL_TIER, ModelGalleryRow, NoModelRow, TierPicker, TierSummary,
  type GalleryModel, type ModelTier,
} from '../../components/ModelGallery'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface PropModelInfo {
  models?: GalleryModel[]
  tiers?: string[]
  none_selected?: boolean
}

export function PropModelPanel({ propId, reloadKey, preview, onPreview, onChanged }: {
  propId: string
  /** Bumped by the container when a generation finished — reloads the list. */
  reloadKey: number
  /** Filename the detail viewer shows ('' = the active model). */
  preview: string
  onPreview: (filename: string) => void
  /** Reload the prop record — selecting/deleting a mesh changes has_model and
   *  may re-measure the dims. */
  onChanged: () => Promise<unknown>
}) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(propId)
  const [info, setInfo] = useState<PropModelInfo | null>(null)
  const [armedDel, setArmedDel] = useState<string | null>(null)
  const [uploadTier, setUploadTier] = useState<ModelTier>(DEFAULT_MODEL_TIER)
  const uploadRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      setInfo(await apiGet<PropModelInfo>(`/world/props/${enc}/models`))
    } catch {
      setInfo(null)
    }
  }, [enc])

  useEffect(() => {
    setArmedDel(null)
    void load()
  }, [load, reloadKey])

  const select = useCallback(async (filename: string, tier: ModelTier) => {
    try {
      await apiPost(`/world/props/${enc}/models/select`, { file: filename, tier })
      await load()
      await onChanged()
      toast(t('Active model set'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, load, onChanged, t, toast])

  const remove = useCallback(async (filename: string) => {
    setArmedDel(null)
    try {
      await apiDelete(`/world/props/${enc}/models?file=${encodeURIComponent(filename)}`)
      if (preview === filename) onPreview('')
      await load()
      await onChanged()
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [enc, preview, onPreview, load, onChanged, t, toast])

  // Upload a GLB as a NEW mesh of the chosen tier (validated server-side;
  // surface the 422 reasons instead of a bare status code).
  const upload = useCallback(async (file: File) => {
    if (!file) return
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(
        `/world/props/${enc}/upload?tier=${encodeURIComponent(uploadTier)}`,
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
  }, [enc, uploadTier, onPreview, load, onChanged, t, toast])

  const models = info?.models || []
  // The row the viewer shows: the explicit preview, else the active file.
  const shownFile = models.find((m) => m.filename === preview)?.filename
    || models.find((m) => m.active)?.filename
    || ''

  return (
    <>
      <div className="ga-form-section-label">{t('3D models')}</div>
      <TierSummary tiers={info?.tiers} />
      {models.length === 0 ? (
        <span className="ga-hint">
          {t('No mesh stored yet — generate one (🧊) or upload a GLB.')}
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
            />
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="ga-btn ga-btn-sm"
          onClick={() => uploadRef.current?.click()}
          title={t('Upload a GLB as a new mesh of this prop.')}>
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
