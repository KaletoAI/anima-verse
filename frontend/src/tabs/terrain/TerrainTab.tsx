/**
 * TerrainTab — the ground vocabulary of the world as its own Game-Admin tab
 * (Seamless World, E2; the surface assignment of 2026-08-16).
 *
 * It used to be a modal inside the map editor, reachable only while holding a
 * brush, and it had run out of room: every property the ground gained added a
 * column to a table that was already two rows per kind. A ground is not a row —
 * it is a small thing with five aspects (what it is, what it looks like, what
 * it does to a figure, what shape it has, what grows on it), and each of them
 * is a SECTION here. The map editor keeps what it is good at: PAINTING areas.
 *
 * Shell: the standard list-detail layout (`ga-twocol`) of the other tabs — the
 * effective catalog on the left with its origin marked (world row or shared
 * seed), the selected kind or the create form on the right.
 *
 * WHAT IT READS, and why each of the two:
 *   - `GET /world/terrain-types` — the effective catalog plus `sources`, the
 *     one answer that says which kinds exist and where each comes from.
 *   - `GET /assets/surface-textures` — the library the Surface picker offers.
 *     A failed fetch leaves the picker with "none" alone and marks NOTHING as
 *     missing: an empty list is not evidence that a stored id is gone.
 *
 * IT NO LONGER FETCHES `GET /world/height-areas` (2026-08-23). That fetch
 * existed for `tile_step_m` + `max_slope_deg`, the two numbers the micro-relief
 * amplitude sentence was measured against — and the micro-relief is a property
 * of the painted AREA now (§ A16.2), edited in the map's area panel. A kind has
 * no shape to speak of any more, so the tab has nothing to ask the heightfield.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ListHeader } from '../../components/ListHeader'
import { useI18n } from '../../i18n/I18nProvider'
import { apiDelete, apiGet, apiPut } from '../../lib/api'
import { useToast } from '../../lib/Toast'
import type { TerrainType, TerrainTypesResp } from '../map/mapTypes'
import type { SurfaceKind } from '../world/worldTypes'
import { TerrainDetail } from './TerrainDetail'

export function TerrainTab() {
  const { t } = useI18n()
  const { toast } = useToast()
  const [types, setTypes] = useState<TerrainType[]>([])
  const [sources, setSources] = useState<Record<string, 'shared' | 'world'>>({})
  const [surfaces, setSurfaces] = useState<SurfaceKind[]>([])
  const [loaded, setLoaded] = useState(false)
  const [selected, setSelected] = useState('')
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')

  const load = useCallback(async () => {
    try {
      const r = await apiGet<TerrainTypesResp>('/world/terrain-types')
      setTypes(r.types || [])
      setSources(r.sources || {})
    } catch (e) {
      toast(t('Failed to load terrain types') + ': ' + (e as Error).message, 'error')
    } finally {
      setLoaded(true)
    }
  }, [t, toast])

  useEffect(() => { void load() }, [load])

  // The surface library, once. `kind` is the stored value, `name` what the
  // picker shows — the same reading the location editor does.
  useEffect(() => {
    apiGet<Array<{ kind?: string; name?: string; url?: string }>>(
      '/assets/surface-textures')
      .then((list) => setSurfaces(
        (Array.isArray(list) ? list : [])
          .filter((e) => (e?.kind || '').trim())
          .map((e) => ({ kind: e.kind!.trim(),
                         name: (e.name || '').trim() || e.kind!.trim(),
                         url: e.url || '' }))
          .sort((a, b) => a.name.localeCompare(b.name))))
      .catch(() => setSurfaces([]))
  }, [])

  /** Write one entry. Answers the SANITIZED row so the form can refill from
   *  what was stored rather than from what was typed. */
  const putType = useCallback(async (draft: TerrainType): Promise<TerrainType | null> => {
    setBusy(true)
    try {
      const r = await apiPut<{ type?: TerrainType }>(
        `/world/terrain-types/${encodeURIComponent(draft.kind)}`,
        {
          name: draft.name,
          color: draft.color,
          passable: draft.passable,
          speed_factor: draft.speed_factor,
          // ALWAYS sent, empty string included — the route is a full replace.
          surface: draft.surface || '',
          meta: draft.meta || {},
        })
      await load()
      setCreating(false)
      setSelected(draft.kind)
      return r?.type || null
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
      return null
    } finally {
      setBusy(false)
    }
  }, [load, t, toast])

  /** Remove the world row: the seed entry comes back, or the kind is gone when
   *  the seed never had one. Which of the two it was shows in the list right
   *  afterwards, so the selection survives either way. */
  const resetType = useCallback(async (kind: string) => {
    setBusy(true)
    try {
      await apiDelete(`/world/terrain-types/${encodeURIComponent(kind)}`)
      await load()
    } catch (e) {
      toast(t('Error') + ': ' + (e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }, [load, t, toast])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return types
    return types.filter((ty) => ty.kind.toLowerCase().includes(q)
      || (ty.name || '').toLowerCase().includes(q))
  }, [types, query])

  const kinds = useMemo(() => types.map((ty) => ty.kind), [types])
  const selectedType = types.find((ty) => ty.kind === selected) || null
  const selectedSource: 'shared' | 'world' =
    sources[selected] === 'world' ? 'world' : 'shared'

  return (
    <div className="ga-twocol">
      <aside className="ga-twocol-left">
        <ListHeader
          title={t('Terrain types')}
          onNew={() => { setCreating(true); setSelected('') }}
        />
        <div className="ga-form-row" style={{ padding: '0 8px 8px' }}>
          <input className="ga-input" value={query} placeholder={t('Search…')}
            onChange={(e) => setQuery(e.target.value)} />
        </div>
        <ul className="ga-list">
          {!loaded ? (
            <li className="ga-list-empty">{t('Loading…')}</li>
          ) : visible.length === 0 ? (
            <li className="ga-list-empty">
              {types.length ? t('Nothing matches the filter') : t('No terrain types')}
            </li>
          ) : (
            visible.map((ty) => {
              const src = sources[ty.kind] === 'world' ? 'world' : 'shared'
              const isActive = ty.kind === selected
              return (
                <li key={ty.kind}>
                  <button
                    type="button"
                    className={`ga-list-row${isActive ? ' is-active' : ''}`}
                    onClick={() => { setCreating(false); setSelected(ty.kind) }}
                  >
                    <span className="ga-list-row-main">
                      <span className="ga-terrain-swatch"
                        style={{ background: ty.color }} />
                      <span>{ty.name || ty.kind}</span>
                      <span className="ga-list-row-sub">
                        {ty.kind}
                        {ty.passable ? '' : ` · ${t('impassable')}`}
                        {/* Named or NOT named — since the assignment became
                            explicit, "no surface" is a state worth seeing in
                            the list: it is what a kind whose same-named
                            texture used to skin it by itself now looks like,
                            and one click on the right fixes it. */}
                        {ty.surface ? ` · ${ty.surface}` : ` · ${t('no surface')}`}
                      </span>
                    </span>
                    <span className={'ga-source ga-source-' + src}>
                      {src === 'world' ? t('world') : t('shared')}
                    </span>
                  </button>
                </li>
              )
            })
          )}
        </ul>
      </aside>
      <section className="ga-twocol-right">
        {creating ? (
          <TerrainDetail
            key="new"
            type={null}
            source="world"
            existingKinds={kinds}
            surfaces={surfaces}
            busy={busy}
            onSave={putType}
            onCancel={() => setCreating(false)}
          />
        ) : selectedType ? (
          // The source is part of the key on purpose: a reset swaps the whole
          // entry for the seed one underneath it, and a form that kept its
          // draft would go on showing the values that were just deleted.
          // Crossing that line remounts the form with what the server now
          // says. A save on a row that is ALREADY an override does not cross
          // it — that form refills itself from the answer.
          <TerrainDetail
            key={selectedType.kind + ':' + selectedSource}
            type={selectedType}
            source={selectedSource}
            existingKinds={kinds}
            surfaces={surfaces}
            busy={busy}
            onSave={putType}
            onReset={selectedSource === 'world'
              ? () => { void resetType(selectedType.kind) }
              : undefined}
          />
        ) : (
          <div className="ga-placeholder">
            {t('Pick a terrain type or create a new one. Painting areas with them stays in the map editor.')}
          </div>
        )}
      </section>
    </div>
  )
}
