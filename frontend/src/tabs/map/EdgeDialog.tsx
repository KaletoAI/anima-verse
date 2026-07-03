import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet } from '../../lib/api'
import { useHelp } from '../../help/HelpContext'

/**
 * "Match edges" — locked-down dialog (same mapfit inpaint backend as Fit).
 * The sides to blend are clicked DIRECTLY on the tile: only sides with a
 * neighbor are active, preselected. Mask (frame) + prompt derive from the
 * selection; the prompt is determined server-side and stays editable.
 */
type Side = 'north' | 'south' | 'east' | 'west'
const SIDES: Side[] = ['north', 'south', 'east', 'west']

export function EdgeDialog({ locId, locName, available, info = '', rotation, backends = [], defaultBackend = '', mapfitPrompts = {}, onSubmit, onClose }: {
  locId: string
  locName: string
  /** side -> neighbor name (only sides that have a neighbor with a tile). */
  available: Partial<Record<Side, string>>
  info?: string
  /** Cell display rotation (map_rotation_2d) — preview shown as on the map. */
  rotation?: number
  /** Inpaint backends (category=="inpaint") to pick from; empty = server default. */
  backends?: { name: string; family?: string; prompt?: string; terrainHint?: boolean }[]
  defaultBackend?: string
  /** mapfit default prompt per family (natural/keywords) — fallback without a backend prompt. */
  mapfitPrompts?: Record<string, string>
  onSubmit: (sides: Side[], prompt: string, backend: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const { setTopic } = useHelp()
  const availSides = useMemo(() => SIDES.filter((s) => available[s]), [available])
  // Exactly ONE edge between two map elements.
  const [sel, setSel] = useState<Side | ''>(() => availSides[0] || '')
  // Default may carry a legacy "backend:" prefix — match against the bare name.
  const [be, setBe] = useState(() => {
    const defName = defaultBackend.replace(/^backend:/i, '').trim()
    return (backends.find((b) => b.name === defName) || backends[0])?.name || ''
  })
  const [edgeHint, setEdgeHint] = useState('')  // dynamic terrain hint (/edge-prompt)
  const [prompt, setPrompt] = useState('')

  // Per-backend instruction (fallback: mapfit prompt per family).
  const instrFor = (name: string): string => {
    const b = backends.find((x) => x.name === name)
    const fam = b?.family || 'natural'
    return (b?.prompt || '').trim() || mapfitPrompts[fam] || mapfitPrompts.natural || ''
  }

  const pick = useCallback((s: Side) => {
    if (available[s]) setSel(s)
  }, [available])

  // selKey = gewaehlte Kante (eine Seite).
  const selKey = sel
  // Dynamischen Kanten-Uebergangs-Hint (terrain-bewusst, pro Seiten) serverseitig holen.
  useEffect(() => {
    if (!selKey) { setEdgeHint(''); return }
    apiGet<{ prompt?: string }>(
      `/world/locations/${encodeURIComponent(locId)}/edge-prompt?sides=${encodeURIComponent(selKey)}`)
      .then((d) => setEdgeHint(d.prompt || ''))
      .catch(() => { /* ignore */ })
  }, [locId, selKey])
  // Prompt = instruction (+ dynamic terrain hint ONLY if the target wants it,
  // terrain_hint). Edit models without the hint see the surroundings in the gray canvas.
  useEffect(() => {
    const wantsHint = !!backends.find((b) => b.name === be)?.terrainHint
    setPrompt(wantsHint ? [instrFor(be), edgeHint].filter(Boolean).join(', ') : instrFor(be))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [be, edgeHint])

  // Kanten-Leiste: aktiv (Nachbar) + gewählt = Akzent; aktiv-ungewählt = dezent;
  // ohne Nachbar = sehr blass, nicht klickbar.
  const bar = (s: Side, style: React.CSSProperties): React.CSSProperties => {
    const has = !!available[s]
    const on = sel === s
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
            {t('Click ONE edge to blend with that neighbor (only sides with a neighbor are active).')}
          </div>

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

          <div style={{ position: 'relative', width: 300, height: 300, margin: '0 auto', borderRadius: 6, overflow: 'hidden', background: 'var(--bg, #0d1117)' }}>
            <img
              src={`/world/locations/${encodeURIComponent(locId)}/map-icon-2d`}
              alt=""
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover',
                transform: rotation ? `rotate(${rotation}deg)` : undefined }}
            />
            <div style={bar('north', { top: 0, left: BW, right: BW, height: BW })}
              title={available.north || t('no neighbor')} onClick={() => pick('north')}>{arrow.north}</div>
            <div style={bar('south', { bottom: 0, left: BW, right: BW, height: BW })}
              title={available.south || t('no neighbor')} onClick={() => pick('south')}>{arrow.south}</div>
            <div style={bar('west', { left: 0, top: BW, bottom: BW, width: BW })}
              title={available.west || t('no neighbor')} onClick={() => pick('west')}>{arrow.west}</div>
            <div style={bar('east', { right: 0, top: BW, bottom: BW, width: BW })}
              title={available.east || t('no neighbor')} onClick={() => pick('east')}>{arrow.east}</div>
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
          <button
            className="ga-btn ga-btn-primary"
            disabled={!sel}
            onClick={() => { if (sel) onSubmit([sel], prompt, be); onClose() }}
          >
            {t('Match edge')}
          </button>
        </div>
      </div>
    </div>
  )
}
