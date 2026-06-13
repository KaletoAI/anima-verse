import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'

/**
 * Known-locations editor (Characters → Activity & Home).
 * Strict membership: which world locations the character knows / may travel to.
 * Empty = knows nothing; auto-discovery on entering extends it at runtime.
 *   GET /characters/{c}/memory/locations  (all world locations + is_known/visit)
 *   PUT /characters/{c}/known-locations    ({known_locations: [...]})
 */
interface LocItem {
  id: string
  name: string
  passable: boolean
  danger_level?: number | null
  is_known: boolean
  is_current: boolean
  visit_count: number
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

  const dirty = useMemo(
    () => Array.from(known).sort().join(',') !== baseline,
    [known, baseline],
  )

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

  return (
    <div>
      <div className="ga-form-hint" style={{ marginBottom: 8 }}>
        {t('Which locations the character knows and may travel to. Empty = knows nothing; the character also discovers locations automatically when entering them.')}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="ga-btn ga-btn-sm ga-btn-primary" disabled={!dirty || busy} onClick={save}>
          {busy ? t('Saving…') : t('Save')}
        </button>
        <button className="ga-btn ga-btn-sm" disabled={busy} onClick={() => setKnown(new Set(items.map((l) => l.id)))}>
          {t('Select all')}
        </button>
        <button className="ga-btn ga-btn-sm" disabled={busy} onClick={() => setKnown(new Set())}>
          {t('Select none')}
        </button>
        <span style={{ fontSize: '0.8em', opacity: 0.6 }}>
          {t('{n} known').replace('{n}', String(known.size))}
          {dirty ? ' · ' + t('unsaved') : ''}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '2px 14px' }}>
        {items.map((l) => (
          <label key={l.id}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 4px',
                     cursor: 'pointer', minWidth: 0, fontSize: '0.88em' }}>
            <input type="checkbox" checked={known.has(l.id)} onChange={() => toggle(l.id)} />
            <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {l.name || l.id}
            </span>
            {l.is_current ? (
              <span title={t('current location')} style={{ flex: '0 0 auto', color: 'var(--accent, #6aa9ff)', fontSize: '0.8em' }}>●</span>
            ) : null}
            {l.passable ? (
              <span title={t('passable terrain tile')} style={{ flex: '0 0 auto', opacity: 0.4, fontSize: '0.8em' }}>⤳</span>
            ) : null}
            {l.visit_count > 0 ? (
              <span style={{ flex: '0 0 auto', opacity: 0.4, fontSize: '0.78em', marginLeft: 'auto' }}>
                {l.visit_count}×
              </span>
            ) : null}
          </label>
        ))}
      </div>
    </div>
  )
}
