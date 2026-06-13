import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * Known-locations editor (Characters → Locations): die echte 2D-Welt-Karte
 * (map-icon-2d Kacheln im Grid wie MapPanel), unbekannte Orte als Fog-of-War
 * abgedunkelt. Klick auf eine Kachel schaltet "bekannt" um; Speichern schreibt
 * den vollen Soll-Stand.
 *   GET /characters/{c}/memory/locations
 *   PUT /characters/{c}/known-locations  ({known_locations: [...]})
 */
interface LocItem {
  id: string
  name: string
  grid_x?: number | null
  grid_y?: number | null
  map_rotation_2d?: number
  passable: boolean
  is_known: boolean
  is_current: boolean
  visit_count: number
}

const CELL = 78
const GAP = 4
const PAD = 6

function isPlaced(l: LocItem): boolean {
  return l.grid_x != null && l.grid_y != null && (l.grid_x as number) >= 0 && (l.grid_y as number) >= 0
}

export function KnownLocationsEditor({ character }: { character: string }) {
  const { t } = useI18n()
  const { toast } = useToast()
  const enc = encodeURIComponent(character)

  const [items, setItems] = useState<LocItem[]>([])
  const [known, setKnown] = useState<Set<string>>(new Set())
  const [baseline, setBaseline] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await apiGet<{ items: LocItem[] }>(`/characters/${enc}/memory/locations`)
      const locs = d.items || []
      setItems(locs)
      const k = new Set(locs.filter((l) => l.is_known).map((l) => l.id))
      setKnown(k)
      setBaseline(Array.from(k).sort().join(','))
    } catch (e) {
      toast(t('Failed to load') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }, [enc, t, toast])

  useEffect(() => { load() }, [load])

  const dirty = useMemo(() => Array.from(known).sort().join(',') !== baseline, [known, baseline])

  const toggle = (id: string) => {
    setKnown((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const save = async () => {
    setBusy(true)
    try {
      await apiPut(`/characters/${enc}/known-locations`, { known_locations: Array.from(known) })
      toast(t('Saved'), 'success')
      setBaseline(Array.from(known).sort().join(','))
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const grid = useMemo(() => {
    const placed = items.filter(isPlaced)
    if (!placed.length) return null
    const xs = placed.map((l) => l.grid_x as number)
    const ys = placed.map((l) => l.grid_y as number)
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const cols = maxX - minX + 1
    const byCell = new Map<string, LocItem>()
    placed.forEach((l) => byCell.set(`${l.grid_x},${l.grid_y}`, l))
    const els: React.ReactNode[] = []
    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        const l = byCell.get(`${x},${y}`)
        if (!l) { els.push(<div key={`${x},${y}`} style={{ width: CELL, height: CELL }} />); continue }
        els.push(<MapCell key={l.id} loc={l} isKnown={known.has(l.id)} onClick={() => toggle(l.id)} t={t} />)
      }
    }
    return (
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, ${CELL}px)`, gap: GAP, padding: PAD }}>
        {els}
      </div>
    )
  }, [items, known, t])

  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  const knownCount = items.filter((l) => known.has(l.id)).length

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={!dirty || busy} onClick={save}>
          {busy ? t('Saving…') : t('Save')}
        </button>
        <button className="ga-btn ga-btn-sm" disabled={!dirty || busy} onClick={() => {
          setKnown(new Set(items.filter((l) => l.is_known).map((l) => l.id)))
        }}>
          {t('Reset')}
        </button>
        <span style={{ fontSize: '0.82em', opacity: 0.6, marginLeft: 'auto' }}>
          {t('{k} known / {n} total').replace('{k}', String(knownCount)).replace('{n}', String(items.length))}
          {dirty ? ' · ' + t('unsaved') : ''}
        </span>
      </div>

      <div style={{ fontSize: '0.8em', opacity: 0.55, marginBottom: 8 }}>
        {t('Click a tile to toggle whether the character knows that place. Darkened = unknown (fog of war); entering a location also reveals it automatically.')}
      </div>

      {grid ? (
        <div style={{ overflow: 'auto', maxHeight: '60vh', border: '1px solid var(--border, #30363d)',
                      borderRadius: 8, background: 'var(--bg, #0d1117)' }}>
          {grid}
        </div>
      ) : null}

      {!grid && <div className="ga-placeholder">{t('No places')}</div>}
    </div>
  )
}

function MapCell({ loc, isKnown, onClick, t }: {
  loc: LocItem; isKnown: boolean; onClick: () => void; t: (s: string) => string
}) {
  const [imgFail, setImgFail] = useState(false)
  const rot = loc.map_rotation_2d || 0
  return (
    <div
      onClick={onClick}
      title={`${loc.name}${isKnown ? '' : ' — ' + t('unknown (fog of war)')}`}
      style={{
        width: CELL, height: CELL, position: 'relative', borderRadius: 6, overflow: 'hidden',
        cursor: 'pointer', userSelect: 'none', boxSizing: 'border-box',
        border: isKnown ? '1px solid var(--border, #30363d)' : '1px solid rgba(255,255,255,0.08)',
        outline: loc.is_current ? '2px solid var(--accent, #6aa9ff)' : 'none', outlineOffset: -2,
        background: 'var(--bg, #0d1117)',
      }}
    >
      {/* Karten-Kachel */}
      {!imgFail && (
        <img src={`/world/locations/${encodeURIComponent(loc.id)}/map-icon-2d`} alt={loc.name}
          onError={() => setImgFail(true)}
          style={{
            position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover',
            transform: rot ? `rotate(${rot}deg)` : undefined,
            // Fog-of-War: unbekannt → entsaettigt + abgedunkelt.
            filter: isKnown ? undefined : 'grayscale(0.85) brightness(0.4)',
          }} />
      )}
      {/* Fog-Schleier zusaetzlich (auch ohne Bild) */}
      {!isKnown && (
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)' }} />
      )}
      {/* Name */}
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0, fontSize: '0.58em', lineHeight: 1.15,
        textAlign: 'center', background: 'rgba(0,0,0,0.6)', color: '#fff', padding: '1px 2px',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        fontStyle: loc.passable ? 'italic' : 'normal', opacity: isKnown ? 1 : 0.7,
      }}>{loc.name}</div>
      {/* Marker */}
      {loc.is_current && (
        <div style={{ position: 'absolute', top: 1, right: 2, fontSize: '0.85em', zIndex: 2 }}>📍</div>
      )}
      {isKnown && loc.visit_count > 0 && (
        <span style={{ position: 'absolute', top: 1, left: 3, fontSize: '0.6em', color: '#fff',
                       textShadow: '0 0 3px #000', fontVariantNumeric: 'tabular-nums' }}>
          {loc.visit_count}×
        </span>
      )}
    </div>
  )
}
