/**
 * FieldModel — 3D model asset (GLB/VRM) of a character (AV3D-5 stage 1).
 * Rendered template-driven via the section flag `special: "model3d"` (slot
 * wired in CharactersTab only — the player avatar panel does not offer it).
 *
 * Backend contract: POST/GET/DELETE /characters/{name}/model plus
 * GET/POST .../model/meta ({format, rig, size, uploaded_at}). `rig` tells
 * the consuming 3D client whether its shared Mixamo animation-clip library
 * applies; orientation/scale are normalized client-side on purpose.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPost, apiUpload } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface ModelMeta {
  format?: string
  rig?: string
  size?: number
  uploaded_at?: string
  original_filename?: string
}

const RIG_VALUES = ['mixamo', 'custom', 'none'] as const

export function FieldModel({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [meta, setMeta] = useState<ModelMeta | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    if (!character) return
    try {
      setMeta(await apiGet<ModelMeta>(`/characters/${enc}/model/meta`))
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMeta(null)
    }
  }, [character, enc])

  useEffect(() => {
    setConfirmDelete(false)
    load()
  }, [load])

  const upload = useCallback(
    async (file: File) => {
      if (!file || busy) return
      setBusy(true)
      try {
        await apiUpload(`/characters/${enc}/model`, file, 'file', {
          rig: meta?.rig || 'mixamo',
        })
        await load()
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      } finally {
        setBusy(false)
      }
    },
    [busy, enc, load, meta, t, toast],
  )

  const setRig = useCallback(
    async (rig: string) => {
      try {
        setMeta(await apiPost<ModelMeta>(`/characters/${enc}/model/meta`, { rig }))
        toast(t('Saved'))
      } catch (e) {
        toast(t('Error') + ': ' + (e as Error).message, 'error')
      }
    },
    [enc, t, toast],
  )

  const remove = useCallback(async () => {
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setConfirmDelete(false)
    try {
      await apiDelete(`/characters/${enc}/model`)
      setMeta(null)
      toast(t('Deleted'))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    }
  }, [confirmDelete, enc, t, toast])

  const sizeMb = meta?.size ? (meta.size / (1024 * 1024)).toFixed(1) : ''

  return (
    <div className="ga-form">
      {meta ? (
        <>
          <div className="ga-hint">
            {(meta.format || '').toUpperCase()}
            {sizeMb ? ` · ${sizeMb} MB` : ''}
            {meta.uploaded_at ? ` · ${new Date(meta.uploaded_at).toLocaleDateString()}` : ''}
            {meta.original_filename ? ` · ${meta.original_filename}` : ''}
          </div>
          <label className="ga-hint" htmlFor="model3d-rig">
            {t('Rig')}
          </label>
          <select
            id="model3d-rig"
            className="ga-input"
            value={meta.rig || 'custom'}
            disabled={busy}
            onChange={(e) => setRig(e.target.value)}
          >
            {RIG_VALUES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <div className="ga-hint">
            {t('mixamo: the shared animation-clip library of the 3D client applies. custom/none: model is shown without shared clips.')}
          </div>
        </>
      ) : (
        <div className="ga-hint">
          {t('No 3D model yet — 3D clients fall back to the portrait marker.')}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          {busy ? t('Uploading…') : meta ? t('Replace') : t('Upload GLB/VRM')}
        </button>
        {meta ? (
          <>
            <a className="ga-btn ga-btn-sm" href={`/characters/${enc}/model`} download>
              {t('Download')}
            </a>
            <button
              type="button"
              className="ga-btn ga-btn-sm"
              disabled={busy}
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
        accept=".glb,.vrm"
        style={{ display: 'none' }}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) upload(f)
          e.target.value = ''
        }}
      />
    </div>
  )
}
