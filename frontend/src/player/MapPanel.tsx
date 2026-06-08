/**
 * MapPanel — read-only 2D-Weltkarte (eigenständiges Panel).
 * plan-room-conversation Phase 2.
 *
 * Orte aus GET /world/locations (grid_x/grid_y), Kachelbild je Ort aus
 * GET /world/locations/{id}/map-icon. Aktueller Ort wird hervorgehoben.
 * Bewegung bleibt bewusst im Move-Panel — die Karte ist hier nur Anzeige.
 */
import { useEffect, useState } from 'react'
import { useI18n } from '../i18n/I18nProvider'
import { apiGet } from '../lib/api'

interface Loc { id: string; name: string; grid_x?: number | null; grid_y?: number | null }

const CELL = 64
const GAP = 4

// Flat 2D icon for the 2D map, with fallback to the iso map-icon, then hide.
function MapIcon({ loc }: { loc: Loc }) {
  const [stage, setStage] = useState(0) // 0 = 2D icon, 1 = iso icon, 2 = hidden
  if (stage >= 2) return null
  const src = stage === 0
    ? `/world/locations/${encodeURIComponent(loc.id)}/map-icon-2d`
    : `/world/locations/${encodeURIComponent(loc.id)}/map-icon`
  return (
    <img src={src} alt={loc.name} onError={() => setStage((s) => s + 1)}
      style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
  )
}

export function MapPanel({ currentLocationId }: { currentLocationId: string }) {
  const { t } = useI18n()
  const [locs, setLocs] = useState<Loc[]>([])

  useEffect(() => {
    apiGet<{ locations?: Loc[] }>('/world/locations')
      .then((d) => setLocs((d.locations || []).filter(
        (l) => l.grid_x != null && l.grid_y != null &&
          (l.grid_x as number) >= 0 && (l.grid_y as number) >= 0)))
      .catch(() => { /* ignore */ })
  }, [])

  if (!locs.length) {
    return <div style={{ opacity: 0.5, fontSize: '0.85em' }}>{t('No map positions yet.')}</div>
  }

  const xs = locs.map((l) => l.grid_x as number)
  const ys = locs.map((l) => l.grid_y as number)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const cols = maxX - minX + 1

  const byCell = new Map<string, Loc>()
  locs.forEach((l) => byCell.set(`${l.grid_x},${l.grid_y}`, l))

  const cells = []
  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      const l = byCell.get(`${x},${y}`)
      const cur = !!l && l.id === currentLocationId
      cells.push(
        <div key={`${x},${y}`} style={{
          width: CELL, height: CELL, borderRadius: 6, position: 'relative', overflow: 'hidden',
          border: cur ? '2px solid var(--accent, #6aa9ff)' : '1px solid var(--border, #30363d)',
          background: 'var(--bg, #0d1117)', opacity: l ? 1 : 0.12,
        }}>
          {l && <MapIcon loc={l} />}
          {l && (
            <div style={{
              position: 'absolute', left: 0, right: 0, bottom: 0, fontSize: '0.6em',
              textAlign: 'center', background: 'rgba(0,0,0,0.55)', color: '#fff',
              padding: '1px 2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{l.name}</div>
          )}
          {cur && <div style={{ position: 'absolute', top: 1, right: 2, fontSize: '0.8em' }}>📍</div>}
        </div>,
      )
    }
  }

  return (
    <div style={{ overflow: 'auto', height: '100%' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: `repeat(${cols}, ${CELL}px)`,
        gap: GAP, padding: 4, width: 'max-content',
      }}>
        {cells}
      </div>
    </div>
  )
}
