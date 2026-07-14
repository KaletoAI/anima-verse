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
import { ApiError, apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'

interface ModelMeta {
  format?: string
  rig?: string
  size?: number
  has_texture?: boolean
  uploaded_at?: string
  original_filename?: string
  source?: string
}

const RIG_VALUES = ['mixamo', 'generic'] as const

export function FieldModel({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [meta, setMeta] = useState<ModelMeta | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [pendingFbx, setPendingFbx] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const texRef = useRef<HTMLInputElement>(null)

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

  // GLB = one file (rig + mesh + textures inside). FBX = two files: an FBX
  // embeds no texture, so its basecolor PNG (from the SAME run) must come
  // with it. The server validates both shapes and answers 422 with the
  // concrete reasons — surface them instead of a bare "failed".
  const uploadFiles = useCallback(
    async (file: File, texture: File | null) => {
      if (!file || busy) return
      setBusy(true)
      try {
        const fd = new FormData()
        fd.append('file', file)
        if (texture) fd.append('texture', texture)
        const res = await fetch(`/characters/${enc}/model`, {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        })
        const body = await res.json().catch(() => null)
        if (!res.ok) {
          const detail = body?.detail
          const errs: string[] = Array.isArray(detail?.errors) ? detail.errors : []
          throw new Error(errs.length ? errs.join(' · ') : (detail?.toString?.() || `HTTP ${res.status}`))
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

  // An FBX pick asks for its texture next; a GLB uploads straight away.
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
            {meta.has_texture ? ` · +${t('texture')}` : ''}
            {meta.source === 'generated' ? ` · ${t('generated')}` : ''}
            {meta.uploaded_at ? ` · ${new Date(meta.uploaded_at).toLocaleDateString()}` : ''}
            {meta.original_filename ? ` · ${meta.original_filename}` : ''}
          </div>
          {meta.source === 'generated' ? (
            <div className="ga-hint">
              {t('This is the generated mesh of the current outfit. An upload here overrides it.')}
            </div>
          ) : (
            <>
              <label className="ga-hint" htmlFor="model3d-rig">
                {t('Rig')}
              </label>
              <select
                id="model3d-rig"
                className="ga-input"
                value={meta.rig || 'mixamo'}
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
                {t('mixamo: 52-bone humanoid skeleton — the shared animation clips apply. generic: no standard skeleton, no clips.')}
              </div>
            </>
          )}
        </>
      ) : (
        <div className="ga-hint">
          {t('No 3D model yet — 3D clients fall back to the portrait marker.')}
        </div>
      )}
      <div className="ga-hint">
        {t('GLB (humanoid): one file with the 52-bone rig and embedded textures. FBX (generic): the basecolor PNG of the same run is asked for right after.')}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          {busy ? t('Uploading…') : meta ? t('Replace') : t('Upload GLB/FBX')}
        </button>
        {meta ? (
          <>
            <a className="ga-btn ga-btn-sm" href={`/characters/${enc}/model`} download>
              {t('Download')}
            </a>
            {meta.source !== 'generated' ? (
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                disabled={busy}
                onClick={remove}
                onBlur={() => setConfirmDelete(false)}
              >
                {confirmDelete ? t('Really delete?') : t('Delete')}
              </button>
            ) : null}
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
    </div>
  )
}
