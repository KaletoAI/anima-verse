import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'

/**
 * „Kanten angleichen" — gesperrter Dialog (gleicher mapfit-Workflow/Backend wie
 * Fit). Man klickt die anzugleichenden Seiten DIREKT auf dem Tile an: nur Seiten
 * mit Nachbar sind aktiv, vorausgewählt. Maske (Rahmen) + Prompt entstehen aus
 * der Auswahl; der Prompt wird serverseitig dynamisch ermittelt und ist editierbar.
 */
type Side = 'north' | 'south' | 'east' | 'west'
const SIDES: Side[] = ['north', 'south', 'east', 'west']

export function EdgeDialog({ locId, locName, available, info, rotation, onSubmit, onClose }: {
  locId: string
  locName: string
  /** side -> neighbor name (only sides that have a neighbor with a tile). */
  available: Partial<Record<Side, string>>
  info: string
  /** Cell display rotation (map_rotation_2d) — preview shown as on the map. */
  rotation?: number
  onSubmit: (sides: Side[], prompt: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const availSides = useMemo(() => SIDES.filter((s) => available[s]), [available])
  const [sel, setSel] = useState<Set<Side>>(() => new Set(availSides))
  const [prompt, setPrompt] = useState('')

  const toggle = useCallback((s: Side) => {
    if (!available[s]) return
    setSel((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s); else next.add(s)
      return next
    })
  }, [available])

  // Prompt serverseitig aus der aktuellen Seitenauswahl ermitteln.
  const selKey = useMemo(() => availSides.filter((s) => sel.has(s)).join(','), [availSides, sel])
  useEffect(() => {
    if (!selKey) { setPrompt(''); return }
    apiGet<{ prompt?: string }>(
      `/world/locations/${encodeURIComponent(locId)}/edge-prompt?sides=${encodeURIComponent(selKey)}`)
      .then((d) => setPrompt(d.prompt || ''))
      .catch(() => { /* ignore */ })
  }, [locId, selKey])

  // Kanten-Leiste: aktiv (Nachbar) + gewählt = Akzent; aktiv-ungewählt = dezent;
  // ohne Nachbar = sehr blass, nicht klickbar.
  const bar = (s: Side, style: React.CSSProperties): React.CSSProperties => {
    const has = !!available[s]
    const on = sel.has(s)
    return {
      position: 'absolute', cursor: has ? 'pointer' : 'default',
      background: on ? 'rgba(106,169,255,0.55)' : has ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.04)',
      border: on ? '2px solid var(--accent, #6aa9ff)' : '1px dashed rgba(255,255,255,0.25)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: '#fff', fontSize: '0.7em', textShadow: '0 1px 2px #000', userSelect: 'none',
      opacity: has ? 1 : 0.4, ...style,
    }
  }
  const BW = 34  // Leistenbreite
  const arrow: Record<Side, string> = { north: '▲', south: '▼', east: '▶', west: '◀' }

  return (
    <div className="ga-modal-backdrop" onMouseDown={onClose}>
      <div className="ga-modal" style={{ maxWidth: 520 }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="ga-modal-header">
          <span>{t('Match edges — {name}').replace('{name}', locName)}</span>
          <button className="ga-modal-close" onClick={onClose}>×</button>
        </div>
        <div className="ga-modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: '0.8em', opacity: 0.75 }}>{info}</div>
          <div style={{ fontSize: '0.8em', opacity: 0.85 }}>
            {t('Click the edges to blend (only sides with a neighbor are active).')}
          </div>

          <div style={{ position: 'relative', width: 300, height: 300, margin: '0 auto', borderRadius: 6, overflow: 'hidden', background: 'var(--bg, #0d1117)' }}>
            <img
              src={`/world/locations/${encodeURIComponent(locId)}/map-icon-2d`}
              alt=""
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover',
                transform: rotation ? `rotate(${rotation}deg)` : undefined }}
            />
            <div style={bar('north', { top: 0, left: BW, right: BW, height: BW })}
              title={available.north || t('no neighbor')} onClick={() => toggle('north')}>{arrow.north}</div>
            <div style={bar('south', { bottom: 0, left: BW, right: BW, height: BW })}
              title={available.south || t('no neighbor')} onClick={() => toggle('south')}>{arrow.south}</div>
            <div style={bar('west', { left: 0, top: BW, bottom: BW, width: BW })}
              title={available.west || t('no neighbor')} onClick={() => toggle('west')}>{arrow.west}</div>
            <div style={bar('east', { right: 0, top: BW, bottom: BW, width: BW })}
              title={available.east || t('no neighbor')} onClick={() => toggle('east')}>{arrow.east}</div>
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
          <button
            className="ga-btn ga-btn-primary"
            disabled={!selKey}
            onClick={() => { onSubmit(availSides.filter((s) => sel.has(s)), prompt); onClose() }}
          >
            {t('Match edges')}
          </button>
        </div>
      </div>
    </div>
  )
}
