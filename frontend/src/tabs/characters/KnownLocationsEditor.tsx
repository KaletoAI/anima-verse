import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * Known-locations editor (Characters → Locations): every placed location as a
 * row with its name, unknown ones dimmed as fog of war. Clicking a row toggles
 * "known"; saving writes the full target state.
 *   GET /characters/{c}/memory/locations
 *   PUT /characters/{c}/known-locations  ({known_locations: [...]})
 *
 * A plain NAME LIST, not a map. This surface is pure selection UI — it never
 * showed distances or routes, and the picture it used to show (the flat 2D map
 * icon) does not exist any more. The map itself lives in the Map tab; here a
 * location only needs to be recognisable by name. The rows are ordered by
 * world position (z, then x) so neighbours on the map stay neighbours in the
 * list and the order is stable across reloads.
 */
interface LocItem {
  id: string
  name: string
  pos_x?: number | null
  pos_z?: number | null
  is_known: boolean
  is_current: boolean
  visit_count: number
}

const GAP = 2
const PAD = 6

/** Placed = it stands somewhere on the world map. Metres are signed — there is
 *  no ">= 0" test, negative coordinates are ordinary positions. */
function isPlaced(l: LocItem): boolean {
  return l.pos_x != null && l.pos_z != null
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

  const rows = useMemo(() => {
    const placed = items.filter(isPlaced)
    if (!placed.length) return null
    placed.sort((a, b) => ((a.pos_z as number) - (b.pos_z as number))
      || ((a.pos_x as number) - (b.pos_x as number)))
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: GAP, padding: PAD }}>
        {placed.map((l) => (
          <LocRow key={l.id} loc={l} isKnown={known.has(l.id)} onClick={() => toggle(l.id)} t={t} />
        ))}
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
        {t('Click a location to toggle whether the character knows it. Dimmed = unknown (fog of war); entering a location also reveals it automatically.')}
      </div>

      {rows ? (
        <div style={{ overflow: 'auto', maxHeight: '60vh', border: '1px solid var(--border, #30363d)',
                      borderRadius: 8, background: 'var(--bg, #0d1117)' }}>
          {rows}
        </div>
      ) : (
        <div className="ga-placeholder">{t('No places')}</div>
      )}
    </div>
  )
}

function LocRow({ loc, isKnown, onClick, t }: {
  loc: LocItem; isKnown: boolean; onClick: () => void; t: (s: string) => string
}) {
  return (
    <button type="button" onClick={onClick}
      className="ga-list-row"
      title={`${loc.name} — ${isKnown ? t('Known') : t('Unknown (fog of war)')}`}
      style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%',
               opacity: isKnown ? 1 : 0.45 }}>
      <span style={{ width: '1.2em', textAlign: 'center' }}>{loc.is_current ? '📍' : (isKnown ? '✓' : '')}</span>
      <span style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{loc.name}</span>
      {loc.visit_count > 0 ? <span style={{ fontSize: '0.8em', opacity: 0.6 }}>{loc.visit_count}×</span> : null}
    </button>
  )
}
