import { useEffect, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

/**
 * Minimaler, gesperrter Dialog für „Fit to neighbors". Fit ist eine
 * festverdrahtete Funktion: Workflow + Backend kommen aus der Server-Config und
 * sind hier nur Anzeige (read-only) — KEINE Service-/Model-/Clip-/LoRA-Auswahl.
 * Zeigt den 3×3-Nachbar-Canvas als Referenz-Vorschau und den editierbaren
 * Richtungs-Prompt (north/south/east/west).
 */
export function FitDialog({ title, info = '', locId, canvasUrl, workflows = [], defaultWorkflow = '', mapfitPrompts = {}, onSubmit, onClose }: {
  title: string
  info?: string
  locId: string
  canvasUrl: string
  /** Inpaint-Workflows (category=="inpaint") zur Auswahl; leer = Server-Default. */
  workflows?: { name: string; spec: string; family?: string; prompt?: string; gray?: boolean }[]
  defaultWorkflow?: string
  /** mapfit-Default-Prompt pro Familie (natural/keywords) — Fallback ohne Workflow-Prompt. */
  mapfitPrompts?: Record<string, string>
  onSubmit: (prompt: string, workflow: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [wf, setWf] = useState(defaultWorkflow || workflows[0]?.spec || '')
  const [fitHint, setFitHint] = useState('')  // dynamischer Terrain-Hint (/fit-prompt)
  const [prompt, setPrompt] = useState('')
  const [canvasFail, setCanvasFail] = useState(false)

  // Per-Workflow-Instruktion (Fallback: mapfit pro Familie).
  const instrFor = (spec: string): string => {
    const w = workflows.find((x) => x.spec === spec)
    const fam = w?.family || 'natural'
    return (w?.prompt || '').trim() || mapfitPrompts[fam] || mapfitPrompts.natural || ''
  }

  // Terrain-Hint (langsam, vision-basiert) NACH dem Oeffnen asynchron holen.
  useEffect(() => {
    apiGet<{ prompt?: string }>(`/world/locations/${encodeURIComponent(locId)}/fit-prompt`)
      .then((d) => setFitHint(d.prompt || ''))
      .catch(() => { /* ignore */ })
  }, [locId])
  // Prompt = Workflow-Instruktion (+ dynamischer Terrain-Hint NUR bei Fill-
  // Modellen). Edit-Modelle (gray) sehen die Umgebung im grauen Canvas selbst —
  // eine Terrain-Beschreibung waere falsch.
  useEffect(() => {
    const isGray = !!workflows.find((w) => w.spec === wf)?.gray
    setPrompt(isGray ? instrFor(wf) : [instrFor(wf), fitHint].filter(Boolean).join(', '))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wf, fitHint])

  return (
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ maxWidth: 560 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{title}</span>
          <button className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: '0.8em', opacity: 0.75 }}>{info}</div>

          {workflows.length > 0 ? (
            <div>
              <div style={{ fontSize: '0.8em', fontWeight: 600, marginBottom: 4 }}>{t('Inpaint workflow')}</div>
              <select className="ga-input" value={wf} onChange={(e) => setWf(e.target.value)} style={{ width: '100%' }}>
                {workflows.map((w) => (
                  <option key={w.spec} value={w.spec}>{w.name}</option>
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
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
              style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit' }}
            />
          </div>
        </div>
        <div className="ga-modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="ga-btn" onClick={onClose}>{t('Cancel')}</button>
          <button className="ga-btn ga-btn-primary" onClick={() => { onSubmit(prompt, wf); onClose() }}>
            {t('Generate')}
          </button>
        </div>
      </div>
    </div>
  )
}
