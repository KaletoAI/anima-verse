import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'

export interface MeshBackend {
  name: string
  face_num?: number | null
}

/** Per-run overrides next to the backend pick — empty = backend default. */
export interface MeshGenerateOpts {
  face_num?: number
  texture_size?: number
}

const TEXTURE_SIZES = [512, 1024, 2048]

/**
 * Backend picker for a mesh generation — shared by EVERY 3D generate button
 * (character 3D model, building/room models, prop regenerate). ALWAYS a
 * dialog (even with a single backend, which is then preselected); the list is
 * the available mesh backends of the relevant rig. Picking a backend prefills
 * "Face count" with ITS configured default — override it per run. "Texture
 * size" is plumbed the same way and reaches the gateway as soon as its alias
 * declares the parameter. Rendered via createPortal so it also works inside
 * the /play grid.
 */
export function MeshBackendDialog({
  open,
  title,
  backends,
  defaultBackend = '',
  generateLabel,
  onGenerate,
  onClose,
}: {
  open: boolean
  title: string
  backends: MeshBackend[]
  /** Preselected backend (e.g. the admin default when rig-compatible). */
  defaultBackend?: string
  generateLabel?: string
  onGenerate: (backend: string, opts: MeshGenerateOpts) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [picked, setPicked] = useState(defaultBackend)
  const [faceDraft, setFaceDraft] = useState('')
  const [texSize, setTexSize] = useState('')
  // Reset the selection to the default each time the dialog opens (the backends
  // and default may have loaded/changed between opens).
  useEffect(() => {
    if (!open) return
    setPicked(defaultBackend)
    const b = backends.find((x) => x.name === defaultBackend)
    setFaceDraft(b?.face_num ? String(b.face_num) : '')
    setTexSize('')
  }, [open, defaultBackend, backends])

  if (!open) return null
  const none = backends.length === 0

  const pick = (name: string) => {
    setPicked(name)
    // The face field always shows what THIS run would use: the newly picked
    // backend's configured default, ready to be overridden.
    const b = backends.find((x) => x.name === name)
    setFaceDraft(b?.face_num ? String(b.face_num) : '')
  }

  const start = () => {
    const opts: MeshGenerateOpts = {}
    const f = parseInt(faceDraft, 10)
    const selected = backends.find((x) => x.name === picked)
    // Send the face count only when it differs from the backend default —
    // an untouched prefill keeps meaning "backend default".
    if (Number.isFinite(f) && f > 0 && f !== (selected?.face_num || 0)) {
      opts.face_num = f
    }
    const tex = parseInt(texSize, 10)
    if (Number.isFinite(tex) && tex > 0) opts.texture_size = tex
    onGenerate(picked, opts)
  }

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div
        className="ga-modal"
        role="dialog"
        aria-label={title}
        style={{ maxWidth: 460 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="ga-modal-body">
          {none ? (
            <div className="ga-hint">
              {t('No mesh backend available — configure one (api_type openai_mesh) in Media Generation.')}
            </div>
          ) : (
            <div className="ga-form">
              <label className="ga-hint">{t('Backend')}</label>
              <select
                className="ga-input"
                value={picked}
                onChange={(e) => pick(e.target.value)}
              >
                <option value="">{t('— default (cheapest available) —')}</option>
                {backends.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                    {b.face_num ? ` · ${b.face_num.toLocaleString()} ${t('faces')}` : ''}
                  </option>
                ))}
              </select>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 140 }}
                  title={t('Target triangle count for THIS run. Prefilled with the picked backend\'s default — small deco needs far fewer faces than a character (2,000–20,000).')}>
                  <span className="ga-hint">{t('Face count')}</span>
                  <input
                    className="ga-input"
                    type="number"
                    min={500}
                    max={100000}
                    step={500}
                    value={faceDraft}
                    placeholder={t('backend default')}
                    onChange={(e) => setFaceDraft(e.target.value)}
                  />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 140 }}
                  title={t('Texture resolution for THIS run — passed to the gateway as soon as the alias declares a "texture size" parameter; until then it is ignored there. Small props rarely need more than 1024.')}>
                  <span className="ga-hint">{t('Texture size')}</span>
                  <select
                    className="ga-input"
                    value={texSize}
                    onChange={(e) => setTexSize(e.target.value)}
                  >
                    <option value="">{t('— backend default —')}</option>
                    {TEXTURE_SIZES.map((v) => (
                      <option key={v} value={String(v)}>{v} × {v}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="ga-hint">
                {t('Higher face counts mean more detail, bigger files and a slower run.')}
              </div>
            </div>
          )}
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
            {t('Cancel')}
          </button>
          <button
            type="button"
            className="ga-btn ga-btn-sm ga-btn-primary"
            disabled={none}
            onClick={start}
          >
            {generateLabel || t('Generate')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
