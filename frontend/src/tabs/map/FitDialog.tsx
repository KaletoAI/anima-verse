import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { useHelp } from '../../help/HelpContext'

/**
 * Minimal, locked-down dialog for "Fit to neighbors". Fit is a hardwired
 * function: the inpaint backend comes from the server config — NO
 * model/LoRA selection here. Shows the 3×3 neighbor canvas as a reference
 * preview and the editable directional prompt (north/south/east/west).
 */
export function FitDialog({ title, info = '', locId, canvasUrl, backends = [], defaultBackend = '', mapfitPrompts = {}, onSubmit, onClose }: {
  title: string
  info?: string
  locId: string
  canvasUrl: string
  /** Inpaint backends (category=="inpaint") to pick from; empty = server default. */
  backends?: { name: string; family?: string; prompt?: string; terrainHint?: boolean }[]
  defaultBackend?: string
  /** mapfit default prompt per family (natural/keywords) — fallback without a backend prompt. */
  mapfitPrompts?: Record<string, string>
  onSubmit: (prompt: string, backend: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const { setTopic } = useHelp()
  // Default may carry a legacy "backend:" prefix — match against the bare name.
  const defName = defaultBackend.replace(/^backend:/i, '').trim()
  const [be, setBe] = useState(() =>
    (backends.find((b) => b.name === defName) || backends[0])?.name || '')
  const [fitHint, setFitHint] = useState('')  // dynamic terrain hint (/fit-prompt)
  const [prompt, setPrompt] = useState('')
  const [canvasFail, setCanvasFail] = useState(false)

  // Per-backend instruction (fallback: mapfit prompt per family).
  const instrFor = (name: string): string => {
    const b = backends.find((x) => x.name === name)
    const fam = b?.family || 'natural'
    return (b?.prompt || '').trim() || mapfitPrompts[fam] || mapfitPrompts.natural || ''
  }

  // Fetch the terrain hint (slow, vision-based) asynchronously AFTER opening.
  useEffect(() => {
    apiGet<{ prompt?: string }>(`/world/locations/${encodeURIComponent(locId)}/fit-prompt`)
      .then((d) => setFitHint(d.prompt || ''))
      .catch(() => { /* ignore */ })
  }, [locId])
  // Prompt = instruction (+ dynamic terrain hint ONLY if the target wants it,
  // terrain_hint). Edit models without the hint see the surroundings in the gray canvas.
  useEffect(() => {
    const wantsHint = !!backends.find((b) => b.name === be)?.terrainHint
    setPrompt(wantsHint ? [instrFor(be), fitHint].filter(Boolean).join(', ') : instrFor(be))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [be, fitHint])

  return (
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ maxWidth: 560 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: '0.8em', opacity: 0.75 }}>{info}</div>

          {backends.length > 0 ? (
            <div>
              <div style={{ fontSize: '0.8em', fontWeight: 600, marginBottom: 4 }}>{t('Inpaint backend')}</div>
              <select className="ga-input" value={be} onChange={(e) => setBe(e.target.value)} style={{ width: '100%' }}>
                {backends.map((b) => (
                  <option key={b.name} value={b.name}>{b.name}</option>
                ))}
              </select>
            </div>
          ) : null}

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
              onFocus={() => setTopic('image_prompt')}
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
              style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit' }}
            />
          </div>
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="ga-btn" onClick={onClose}>{t('Cancel')}</button>
          <button className="ga-btn ga-btn-primary" onClick={() => { onSubmit(prompt, be); onClose() }}>
            {t('Generate')}
          </button>
        </div>
      </div>
    </div>
  )
}
