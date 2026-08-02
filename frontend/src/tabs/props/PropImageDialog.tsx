/**
 * PropImageDialog — render a NEW source image for an existing prop
 * (plan-area-detail-scenes.md follow-up: images used to be regenerable only
 * as part of the whole source→mesh chain). The dialog shows the COMPLETE
 * final prompt (final-prompt rule): prefilled with the prompt the current
 * image was rendered with, or the picked backend's use-case style when the
 * prop has no record; an emptied prompt lets the server compose one from the
 * stored description/name. The mesh is untouched — re-meshing from the new
 * image is the separate "3D from this image" step.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import type { ImageBackendInfo, PropFull } from './propTypes'

export function PropImageDialog({ prop, backends, onGenerate, onClose }: {
  /** null = closed. */
  prop: PropFull | null
  backends: ImageBackendInfo[]
  onGenerate: (imageBackend: string, prompt: string, negative: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [picked, setPicked] = useState('')
  const [prompt, setPrompt] = useState('')
  const [negative, setNegative] = useState('')

  // Re-arm per open: prefer the CURRENT image's record (backend + final
  // prompt), fall back to the first backend and its use-case style.
  useEffect(() => {
    if (!prop) return
    const known = backends.find((b) => b.name === prop.backend_image)
    const initial = known || backends[0]
    setPicked(initial?.name || '')
    setPrompt(prop.prompt || '')
    setNegative(prop.negative ?? (initial?.prompt_negative || ''))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prop?.id])

  if (!prop) return null

  return createPortal(
    <div className="ga-modal-backdrop" onClick={onClose}>
      <div className="ga-modal" role="dialog"
        aria-label={t('Regenerate source image')}
        style={{ maxWidth: 520 }}
        onClick={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Regenerate source image')} — {prop.name}</span>
          <button type="button" className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body">
          {backends.length === 0 ? (
            <div className="ga-hint">
              {t('No image backend available — configure one in Media Generation.')}
            </div>
          ) : (
            <div className="ga-form">
              <label className="ga-hint">{t('Backend')}</label>
              <select className="ga-input" value={picked}
                onChange={(e) => {
                  setPicked(e.target.value)
                  // A fresh backend pick refreshes the negative default only
                  // when the admin has not written an own one.
                  if (!negative.trim()) {
                    const b = backends.find((x) => x.name === e.target.value)
                    setNegative(b?.prompt_negative || '')
                  }
                }}>
                {backends.map((b) => (
                  <option key={b.name} value={b.name}>{b.name}</option>
                ))}
              </select>
              <label className="ga-hint"
                title={t('The full prompt sent to the render. Empty = the server composes it from the prop description/name and the backend\'s style.')}>
                {t('Final prompt (sent to the render)')}
              </label>
              <textarea className="ga-textarea" rows={4} value={prompt}
                onChange={(e) => setPrompt(e.target.value)} />
              <label className="ga-hint">{t('Negative prompt')}</label>
              <textarea className="ga-textarea" rows={2} value={negative}
                onChange={(e) => setNegative(e.target.value)} />
              <span className="ga-hint">
                {t('The current 3D model stays — use “3D from this image” afterwards to re-mesh.')}
              </span>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" className="ga-btn ga-btn-sm" onClick={onClose}>
                  {t('Cancel')}
                </button>
                <button type="button" className="ga-btn ga-btn-sm ga-btn-primary"
                  onClick={() => onGenerate(picked, prompt, negative)}>
                  🖼 {t('Render')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
