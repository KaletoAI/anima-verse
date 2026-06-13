import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * Known-locations editor (Characters → Locations), als Karten-Kachel-Ansicht
 * wie in der alten UI: Welt-Orte nach Grid-Koordinaten gelegt, bekannt
 * hervorgehoben, aktueller Ort markiert, Besuchszähler. Klick auf eine Kachel
 * schaltet "bekannt" um; Speichern schreibt den vollen Soll-Stand.
 *   GET /characters/{c}/memory/locations
 *   PUT /characters/{c}/known-locations  ({known_locations: [...]})
 */
interface LocItem {
  id: string
  name: string
  grid_x?: number | null
  grid_y?: number | null
  passable: boolean
  danger_level?: number | null
  is_known: boolean
  is_current: boolean
  visit_count: number
  last_visit?: string | null
}

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
  const [showAll, setShowAll] = useState(true)
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

  if (loading) return <div className="ga-loading">{t('Loading…')}</div>

  // Sichtbarkeit: "show all" aus → nur bekannte Kacheln. Editier-Komfort: Default an.
  const visible = items.filter((l) => showAll || known.has(l.id))
  const placed = visible.filter(isPlaced)
  const unplaced = visible.filter((l) => !isPlaced(l))

  let minX = 0, maxX = 0, minY = 0, maxY = 0
  if (placed.length) {
    minX = Math.min(...placed.map((l) => l.grid_x as number))
    maxX = Math.max(...placed.map((l) => l.grid_x as number))
    minY = Math.min(...placed.map((l) => l.grid_y as number))
    maxY = Math.max(...placed.map((l) => l.grid_y as number))
  }
  const cols = placed.length ? maxX - minX + 1 : 0
  const rows = placed.length ? maxY - minY + 1 : 0
  const byPos = new Map<string, LocItem>()
  for (const l of placed) byPos.set(`${(l.grid_x as number) - minX},${(l.grid_y as number) - minY}`, l)

  const knownCount = items.filter((l) => known.has(l.id)).length

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
        <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={!dirty || busy} onClick={save}>
          {busy ? t('Saving…') : t('Save')}
        </button>
        <button className="ga-btn ga-btn-sm" disabled={!dirty || busy} onClick={() => {
          const k = new Set(items.filter((l) => l.is_known).map((l) => l.id)); setKnown(k)
        }}>
          {t('Reset')}
        </button>
        <label className="ga-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.85em' }}>
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          {t('Show all locations')}
        </label>
        <span style={{ fontSize: '0.82em', opacity: 0.6, marginLeft: 'auto' }}>
          {showAll
            ? t('{k} known / {n} total').replace('{k}', String(knownCount)).replace('{n}', String(items.length))
            : t('{k} known locations').replace('{k}', String(knownCount))}
          {dirty ? ' · ' + t('unsaved') : ''}
        </span>
      </div>

      <div style={{ fontSize: '0.8em', opacity: 0.55, marginBottom: 8 }}>
        {t('Click a tile to toggle whether the character knows that location. Empty = knows nothing; entering a location also discovers it automatically.')}
      </div>

      {placed.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(78px, 1fr))`, gap: 6 }}>
          {Array.from({ length: rows * cols }).map((_, idx) => {
            const x = idx % cols
            const y = Math.floor(idx / cols)
            const loc = byPos.get(`${x},${y}`)
            if (!loc) return <div key={idx} />
            return <LocTile key={loc.id} loc={loc} isKnown={known.has(loc.id)} onClick={() => toggle(loc.id)} t={t} />
          })}
        </div>
      )}

      {unplaced.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: '0.78em', opacity: 0.5, marginBottom: 6 }}>{t('Without coordinates')}</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {unplaced.map((loc) => (
              <LocTile key={loc.id} loc={loc} isKnown={known.has(loc.id)} onClick={() => toggle(loc.id)} t={t} fixed />
            ))}
          </div>
        </div>
      )}

      {placed.length === 0 && unplaced.length === 0 && (
        <div className="ga-placeholder">{t('No places')}</div>
      )}
    </div>
  )
}

function LocTile({ loc, isKnown, onClick, t, fixed }: {
  loc: LocItem; isKnown: boolean; onClick: () => void
  t: (s: string) => string; fixed?: boolean
}) {
  const icon = loc.is_current ? '📍' : loc.passable ? '🚶' : '🏠'
  const style: React.CSSProperties = {
    position: 'relative',
    boxSizing: 'border-box',
    width: fixed ? 92 : undefined,
    minHeight: 64,
    padding: '6px 4px',
    borderRadius: 8,
    cursor: 'pointer',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
    textAlign: 'center',
    userSelect: 'none',
    border: '1px solid ' + (isKnown ? 'var(--accent, #6aa9ff)' : 'var(--border, #30363d)'),
    background: isKnown ? 'rgba(120,170,255,0.16)' : 'var(--bg-alt, #0d1117)',
    outline: loc.is_current ? '2px solid var(--accent, #6aa9ff)' : 'none',
    outlineOffset: -1,
    opacity: isKnown ? 1 : 0.5,
  }
  return (
    <div style={style} onClick={onClick}
      title={`${loc.name}${loc.is_known ? '' : ' — ' + t('not known')}`}>
      <div style={{ fontSize: '1.1em', lineHeight: 1 }}>{icon}</div>
      <div style={{ fontSize: '0.72em', lineHeight: 1.15, maxWidth: '100%',
                    overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box',
                    WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
        {loc.name}
      </div>
      {isKnown && loc.visit_count > 0 && (
        <span style={{ position: 'absolute', top: 2, right: 4, fontSize: '0.66em', opacity: 0.6,
                       fontVariantNumeric: 'tabular-nums' }}>{loc.visit_count}×</span>
      )}
    </div>
  )
}
