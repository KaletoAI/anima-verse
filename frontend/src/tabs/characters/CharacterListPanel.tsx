import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ImportButton } from '../../components/ImportExport'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import type { CharacterRef } from '../../lib/refs'

interface PooledNpc { name: string; role?: string; standing_task?: string; reason?: string }
interface NpcLimits { alive?: number; max_alive?: number; wanderer_quota?: number; pool_size?: number }

/**
 * Left-hand character list: header + New/Import actions + the selectable
 * character rows. `characters` is expected pre-sorted by the parent.
 *
 * Temporary NPCs ride in the same list payload and are split off into their
 * own group here — the split is by the `temporary` flag the backend derives
 * from the character's TEMPLATE, never by a name pattern. A second kind of
 * NPC is another template with the same flag and lands in this group too.
 *
 * The RECYCLING POOL is the exception: a pooled NPC is out of every roster
 * (that is what pooling means), so it does not ride in `characters` and is
 * fetched separately. It is the only surface that shows those profiles at
 * all — spawns re-use them, and this is where one can be dropped for good.
 */
export function CharacterListPanel({
  characters,
  selected,
  onSelect,
  onNew,
  onNewNpc,
  onImported,
}: {
  characters: CharacterRef[]
  selected: string
  onSelect: (name: string) => void
  onNew: () => void
  onNewNpc: () => void
  onImported: () => void
}) {
  const { t } = useI18n()
  const regular = useMemo(() => characters.filter((c) => !c.temporary), [characters])
  const npcs = useMemo(() => characters.filter((c) => c.temporary), [characters])
  const [pooled, setPooled] = useState<PooledNpc[]>([])
  const [limits, setLimits] = useState<NpcLimits>({})

  const loadPool = useCallback(() => {
    apiGet<{ pooled?: PooledNpc[]; limits?: NpcLimits }>('/npc/list')
      .then((r) => { setPooled(r.pooled || []); setLimits(r.limits || {}) })
      .catch(() => { setPooled([]); setLimits({}) })
  }, [])
  // Re-read whenever the roster changed: a spawn takes an NPC out of the pool
  // and the TTL sweep puts one in, and both show up as a roster change.
  useEffect(() => { loadPool() }, [loadPool, characters.length])

  const retire = async (name: string) => {
    try { await apiPost(`/npc/${encodeURIComponent(name)}/pool`, {}) } finally {
      onImported()      // the parent's list reload
      loadPool()
    }
  }
  const drop = async (name: string) => {
    try { await apiDelete(`/characters/${encodeURIComponent(name)}`) } finally {
      loadPool()
    }
  }

  const row = (c: CharacterRef, marker?: string) => {
    const isActive = c.name === selected
    return (
      <li key={c.name}>
        <button
          type="button"
          className={`ga-list-row${isActive ? ' is-active' : ''}`}
          onClick={() => onSelect(c.name)}
        >
          <span className="ga-list-row-main">
            <strong>{marker ? `${marker} ` : ''}{c.display_name || c.name}</strong>
          </span>
        </button>
      </li>
    )
  }

  return (
    <aside className="ga-twocol-left">
      <div className="ga-twocol-header">
        <h3>{t('Characters')}</h3>
        <div className="ga-twocol-header-actions">
          <button type="button" className="ga-btn ga-btn-primary" onClick={onNew}>
            {t('New character')}
          </button>
          <ImportButton
            endpoint="/characters/import"
            overwriteSupported
            onImported={onImported}
          />
        </div>
      </div>
      <ul className="ga-list">
        {regular.length === 0 ? (
          <li className="ga-list-empty">{t('No characters')}</li>
        ) : (
          regular.map((c) => row(c))
        )}
      </ul>
      <div className="ga-twocol-header" style={{ marginTop: 12 }}>
        <h3>
          {t('Temporary NPCs')}
          {limits.max_alive !== undefined && (
            <span className="ga-muted"> {npcs.length}/{limits.max_alive}</span>
          )}
        </h3>
        <div className="ga-twocol-header-actions">
          <button type="button" className="ga-btn" onClick={onNewNpc}>
            {t('New NPC')}
          </button>
        </div>
      </div>
      <ul className="ga-list">
        {npcs.length === 0 ? (
          <li className="ga-list-empty">{t('No temporary NPCs')}</li>
        ) : (
          npcs.map((c) => (
            <li key={c.name} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <button
                type="button"
                className={`ga-list-row${c.name === selected ? ' is-active' : ''}`}
                style={{ flex: 1 }}
                onClick={() => onSelect(c.name)}
              >
                <span className="ga-list-row-main">
                  <strong>✦ {c.display_name || c.name}</strong>
                </span>
              </button>
              <button
                type="button"
                className="ga-btn ga-btn-sm"
                title={t('Take out of the world, keep the profile for a later spawn')}
                onClick={() => retire(c.name)}
              >
                {t('Pool')}
              </button>
            </li>
          ))
        )}
      </ul>
      <div className="ga-twocol-header" style={{ marginTop: 12 }}>
        <h3>
          {t('NPC pool')}
          {limits.pool_size !== undefined && (
            <span className="ga-muted"> {pooled.length}/{limits.pool_size}</span>
          )}
        </h3>
      </div>
      <ul className="ga-list">
        {pooled.length === 0 ? (
          <li className="ga-list-empty">{t('Pool is empty')}</li>
        ) : (
          pooled.map((p) => (
            <li key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span className="ga-list-row" style={{ flex: 1 }}>
                <span className="ga-list-row-main">
                  <strong>♺ {p.name}</strong>
                  {p.role ? <span className="ga-muted"> · {p.role}</span> : null}
                  {/* Why this one is in the pool. For an automatic spawn held
                      back by the finish gate ("waiting for profile_image,
                      model3d") this is the only place the state is visible at
                      all — the reason text comes from the server. */}
                  {p.reason ? <span className="ga-muted"> · {p.reason}</span> : null}
                </span>
              </span>
              <button
                type="button"
                className="ga-btn ga-btn-sm ga-btn-danger"
                title={t('Delete this profile for good')}
                onClick={() => drop(p.name)}
              >
                {t('Delete')}
              </button>
            </li>
          ))
        )}
      </ul>
    </aside>
  )
}
