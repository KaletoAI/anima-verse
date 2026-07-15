import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n/I18nProvider'

export interface MeshBackend {
  name: string
  face_num?: number | null
}

/**
 * Backend picker for a mesh generation — shared by the character 3D model field
 * and the location building-model gallery. ALWAYS a dialog (even with a single
 * backend, which is then preselected); the list is the available mesh backends
 * of the relevant rig, with a face-count hint and a "cheapest available"
 * default. Rendered via createPortal so it also works inside the /play grid.
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
  onGenerate: (backend: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [picked, setPicked] = useState(defaultBackend)
  // Reset the selection to the default each time the dialog opens (the backends
  // and default may have loaded/changed between opens).
  useEffect(() => {
    if (open) setPicked(defaultBackend)
  }, [open, defaultBackend])

  if (!open) return null
  const none = backends.length === 0
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
                onChange={(e) => setPicked(e.target.value)}
              >
                <option value="">{t('— default (cheapest available) —')}</option>
                {backends.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                    {b.face_num ? ` · ${b.face_num.toLocaleString()} ${t('faces')}` : ''}
                  </option>
                ))}
              </select>
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
            onClick={() => onGenerate(picked)}
          >
            {generateLabel || t('Generate')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
