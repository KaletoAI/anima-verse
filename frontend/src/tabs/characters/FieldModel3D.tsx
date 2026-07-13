/**
 * FieldModel3D — generated 3D model of a character (img2mesh), cached per
 * outfit combination. Rendered template-driven via the section flag
 * `special: "model3d_gen"` on the 3D tab.
 *
 * The T-pose reference render is the INPUT; a mesh backend (gateway alias,
 * e.g. Trellis2-Low) turns it into a model file (FBX). Manual trigger today —
 * the outfit-change trigger reuses the same endpoint.
 *
 * Backend: GET /characters/{n}/model3d (status), POST .../model3d/generate,
 * GET .../model3d/file (bytes), DELETE .../model3d.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ApiError, apiDelete, apiGet, apiPost } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import { Model3DViewer } from './Model3DViewer'

interface Model3DInfo {
  filename?: string
  format?: string
  size?: number
  url?: string
  created_at?: string
  backend?: string
  source_filename?: string
}

interface Model3DStatus {
  signature?: string
  has_input?: boolean
  model?: Model3DInfo | null
  pending?: boolean
}

interface AnimationClip {
  kind: string
  name: string
  filename: string
  url: string
}

export function FieldModel3D({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)
  const [st, setSt] = useState<Model3DStatus>({})
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [clips, setClips] = useState<AnimationClip[]>([])
  const [clipUrl, setClipUrl] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

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

  useEffect(() => {
    setConfirmDelete(false)
    load()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [load])

  // Shared animation clips (world-independent, same rig as the models).
  useEffect(() => {
    apiGet<{ clips?: AnimationClip[] }>('/assets/animation-clips')
      .then((d) => setClips(d.clips || []))
      .catch(() => setClips([]))
  }, [])

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

  const generate = useCallback(
    async (force: boolean) => {
      if (busy) return
      setBusy(true)
      try {
        await apiPost(`/characters/${enc}/model3d/generate${force ? '?force=1' : ''}`, {})
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
  // Cache-bust per combination so a re-generated mesh is re-fetched.
  const viewerUrl = model
    ? `/characters/${enc}/model3d/file?v=${encodeURIComponent(model.created_at || st.signature || '')}`
    : ''

  return (
    <div className="ga-form">
      {model ? (
        <>
          <Model3DViewer url={viewerUrl} format={model.format || 'fbx'} clipUrl={clipUrl} />
          {clips.length ? (
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span className="ga-hint" style={{ whiteSpace: 'nowrap' }}>{t('Animation')}</span>
              <select
                className="ga-input"
                value={clipUrl}
                onChange={(e) => setClipUrl(e.target.value)}
              >
                <option value="">{t('— none (static) —')}</option>
                {clips.map((c) => (
                  <option key={c.filename} value={c.url}>
                    {c.kind} · {c.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="ga-hint">
              {t('No animation clips — drop Mixamo FBX files ("Without Skin") into shared/models/clips/.')}
            </div>
          )}
          <div className="ga-hint">
            {(model.format || '').toUpperCase()}
            {sizeMb ? ` · ${sizeMb} MB` : ''}
            {model.backend ? ` · ${model.backend}` : ''}
            {model.created_at ? ` · ${new Date(model.created_at).toLocaleString()}` : ''}
            {model.source_filename ? ` · ${model.source_filename}` : ''}
          </div>
        </>
      ) : (
        <div className="ga-hint">
          {pending
            ? t('Generating the 3D model — this takes a few minutes.')
            : st.has_input
              ? t('No 3D model for this outfit yet.')
              : t('No T-pose render for the current outfit — generate it first')}
        </div>
      )}
      <div className="ga-hint">
        {t('Generated from the T-pose render of the currently worn outfit and cached per outfit combination.')}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="ga-btn ga-btn-sm"
          disabled={pending || !st.has_input}
          onClick={() => generate(!!model)}
        >
          {pending ? t('Generating…') : model ? t('Regenerate') : t('Generate 3D model')}
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
    </div>
  )
}
