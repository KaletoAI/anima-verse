import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../../i18n/I18nProvider'
import { ImportButton } from '../../components/ImportExport'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import type { CharacterRef } from '../../lib/refs'

interface PooledNpc {
  name: string
  role?: string
  standing_task?: string
  reason?: string
  /** Profile-image URL, the same path the living roster uses. "" = none. */
  image_url?: string
  /** role · standing task · appearance, empty halves skipped. */
  description?: string
}
interface NpcLimits { alive?: number; max_alive?: number; wanderer_quota?: number; pool_size?: number }

/**
 * One LIVING temporary NPC, as `npc_ops.npc_summary` builds it. Only the few
 * fields this list renders are declared.
 */
interface LivingNpc {
  name: string
  /** The home area in words — "within 60 m of Old Mill", or the painted area's
   *  label. "" for an NPC that lives in a room. */
  home?: string
  /** The painted area whose slot this NPC holds. "" for a location slot. */
  slot_area?: string
}

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
  const [living, setLiving] = useState<Record<string, LivingNpc>>({})

  const loadPool = useCallback(() => {
    apiGet<{ npcs?: LivingNpc[]; pooled?: PooledNpc[]; limits?: NpcLimits }>('/npc/list')
      .then((r) => {
        setPooled(r.pooled || [])
        setLimits(r.limits || {})
        setLiving(Object.fromEntries((r.npcs || []).map((n) => [n.name, n])))
      })
      .catch(() => { setPooled([]); setLimits({}); setLiving({}) })
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

  // Hover card of a pool row. A pooled NPC appears on no other surface, and
  // an LLM-invented name alone says nothing about who it is — so the portrait
  // and the one-line description are shown on mouse-over. Positioned from the
  // row's own rect and rendered into document.body: the pool list scrolls
  // (`overflow-y: auto`), so a card inside it would be clipped at the edge.
  const [preview, setPreview] = useState<{ npc: PooledNpc; top: number; left: number } | null>(null)
  const openPreview = (npc: PooledNpc, el: HTMLElement) => {
    if (!npc.image_url && !npc.description) return
    const r = el.getBoundingClientRect()
    setPreview({
      npc,
      top: Math.max(8, Math.min(r.top, window.innerHeight - 160)),
      left: Math.min(r.right + 8, window.innerWidth - 340),
    })
  }

  /** "roams the Hunting Ground" / "roams within 60 m of Old Mill", or "". */
  const roams = (name: string) => {
    const n = living[name]
    const home = (n?.home || '').trim()
    if (!home) return ''
    return n?.slot_area
      ? t('roams the {area}').replace('{area}', home)
      : t('roams {where}').replace('{where}', home)
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
                  {/* WHERE this NPC lives, and the only place it is visible:
                      an NPC with a home area stands out in the open, so it
                      has no location, no room and no place on any room list
                      (spec § E3). The server words the area itself; a painted
                      area is named, a circle is a distance from a place. */}
                  {roams(c.name)
                    ? <span className="ga-muted"> · {roams(c.name)}</span>
                    : null}
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
            <li
              key={p.name}
              style={{ display: 'flex', alignItems: 'center', gap: 4 }}
              onMouseEnter={(e) => openPreview(p, e.currentTarget)}
              onMouseLeave={() => setPreview(null)}
            >
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
      {preview && createPortal(
        <div className="ga-pool-preview" style={{ top: preview.top, left: preview.left }}>
          {preview.npc.image_url ? (
            <img src={preview.npc.image_url} alt="" />
          ) : null}
          <div>
            <strong>{preview.npc.name}</strong>
            <p className="ga-muted">
              {preview.npc.description || t('No description yet.')}
            </p>
          </div>
        </div>,
        document.body,
      )}
    </aside>
  )
}
