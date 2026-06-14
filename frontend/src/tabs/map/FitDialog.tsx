import { useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'

/**
 * Minimaler, gesperrter Dialog für „Fit to neighbors". Fit ist eine
 * festverdrahtete Funktion: Workflow + Backend kommen aus der Server-Config und
 * sind hier nur Anzeige (read-only) — KEINE Service-/Model-/Clip-/LoRA-Auswahl.
 * Zeigt den 3×3-Nachbar-Canvas als Referenz-Vorschau und den editierbaren
 * Richtungs-Prompt (north/south/east/west).
 */
export function FitDialog({ title, info, canvasUrl, defaultPrompt, onSubmit, onClose }: {
  title: string
  info: string
  canvasUrl: string
  defaultPrompt: string
  onSubmit: (prompt: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(defaultPrompt)
  const [canvasFail, setCanvasFail] = useState(false)

  return (
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ maxWidth: 560 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: '0.8em', opacity: 0.75 }}>{info}</div>

          <div>
            <div style={{ fontSize: '0.8em', fontWeight: 600, marginBottom: 4 }}>
              {t('Reference (neighbor canvas)')}
            </div>
            {canvasFail ? (
              <div className="ga-empty" style={{ fontSize: '0.85em' }}>
                {t('No neighbors with a tile — nothing to fit.')}
              </div>
            ) : (
              <img
                src={canvasUrl}
                alt=""
                onError={() => setCanvasFail(true)}
                style={{ display: 'block', width: '100%', maxHeight: 280, objectFit: 'contain', borderRadius: 6, background: 'var(--bg, #0d1117)' }}
              />
            )}
          </div>

          <div>
            <div style={{ fontSize: '0.8em', fontWeight: 600, marginBottom: 4 }}>{t('Prompt')}</div>
            <textarea
              className="ga-input"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
              style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit' }}
            />
          </div>
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="ga-btn" onClick={onClose}>{t('Cancel')}</button>
          <button className="ga-btn ga-btn-primary" onClick={() => { onSubmit(prompt); onClose() }}>
            {t('Generate')}
          </button>
        </div>
      </div>
    </div>
  )
}
