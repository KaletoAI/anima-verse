/**
 * A187: the confirm dialog of a piece's mesh Regenerate (own-mesh clothing and shoes) with its backend choice.
 * "Auto (routing)" is preselected — the piece's occasion chain (`mesh_garment` / `mesh_footwear`), what it resolves
 * to now in brackets; every enabled img2mesh backend follows. A pick bypasses the routing with no fallback: the
 * server checks it before anything is queued (503 when it is not available). Each choice costs one hub job.
 * The choices come from `GET …/garments/{item}/mesh-backends`. Rendered via createPortal (HUD rule).
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

interface MeshBackendChoices {
  occasion: string
  default: string
  backends: Array<{ name: string; model?: string }>
}

export function MeshRegenerateDialog({ open, url, title, onConfirm, onClose }: {
  open: boolean
  /** `GET …/garments/{item}/mesh-backends`. */
  url: string | null
  title: string
  /** "" = Auto (routing), else the backend's name. */
  onConfirm: (backend: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [choices, setChoices] = useState<MeshBackendChoices | null>(null)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState('')
  useEffect(() => {
    if (!open || !url) return
    let stale = false
    setPicked('')
    setError('')
    apiGet<MeshBackendChoices>(url)
      .then((d) => { if (!stale) setChoices(d) })
      .catch((e: Error) => { if (!stale) setError(e.message) })
    return () => { stale = true }
  }, [open, url])
  if (!open) return null
  const one = t('1 hub job')
  const auto = choices?.default
    ? `${t('Auto (routing)')} → ${choices.default} · ${one}` : `${t('Auto (routing)')} · ${one}`
  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div className="ga-modal" role="dialog" aria-label={title} style={{ maxWidth: 460 }}
        onClick={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          <div className="ga-form">
            <div className="ga-hint">
              {t('Makes a new mesh of this piece from its cut-outs, then fits it on the CPU.')}
            </div>
            <label className="ga-hint">{t('Backend')}</label>
            <select className="ga-input" value={picked} onChange={(e) => setPicked(e.target.value)}
              disabled={!choices}>
              <option value="">{auto}</option>
              {(choices?.backends || []).map((b) => (
                <option key={b.name} value={b.name}>{`${b.name}${b.model ? ` · ${b.model}` : ''} · ${one}`}</option>
              ))}
            </select>
            <div className="ga-hint">
              {picked
                ? t('Only this backend — no routing and no fallback; refused at once when it is not available.')
                : t("The piece's routing chain decides, with its fallbacks.")}
            </div>
            {error ? <div className="ga-hint" style={{ color: 'var(--danger, #f85149)' }}>{t('Error')}: {error}</div> : null}
          </div>
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <button type="button" className="ga-btn" onClick={onClose}>{t('Cancel')}</button>
          <button type="button" className="ga-btn ga-btn-primary" onClick={() => onConfirm(picked)}>
            {`${t('Regenerate')} (${one})`}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
