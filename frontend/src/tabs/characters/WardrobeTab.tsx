/**
 * WardrobeTab (Game-Admin) — Inventar + Outfit als Paper-Doll, identisch zum
 * /play-BelongingsPanel, aber für den GEWÄHLTEN Character (nicht den Avatar).
 *
 * Quelle: GET /characters/{c}/belongings (gleiche Form wie /play/belongings).
 * Setter: POST /inventory/characters/{c}/{equip,unequip,apply-outfit-set}.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { apiGet, apiPost, apiDelete } from '../../lib/api'
import { FieldImage } from './FieldImage'
import { PromptPreview } from './PromptPreview'

// Anker-Positionen (x%, y%) im Bild-Koordinatensystem (silhouette.svg).
const SLOT_ANCHOR: Record<string, [number, number]> = {
  head: [50, 6], neck: [50, 19], outer: [33, 40], top: [50, 33],
  underwear_top: [66, 33], bottom: [50, 55], underwear_bottom: [66, 55],
  legs: [50, 73], feet: [50, 92],
}

function ItemIcon({ itemId, hasImage, emoji, size }: { itemId: string; hasImage: boolean; emoji: string; size: number }) {
  const [failed, setFailed] = useState(false)
  return (
    <span style={{
      width: size, height: size, flex: '0 0 auto', borderRadius: 4, overflow: 'hidden',
      background: 'rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center',
      justifyContent: 'center', fontSize: Math.round(size * 0.6), lineHeight: 1,
    }}>
      {hasImage && !failed
        ? <img src={`/inventory/items/${encodeURIComponent(itemId)}/image`} alt=""
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            onError={() => setFailed(true)} />
        : emoji}
    </span>
  )
}

interface Item {
  item_id: string; name: string; description: string; quantity: number; category: string
  consumable: boolean; equipped: boolean; is_outfit: boolean; slots: string[]
  outfit_types: string[]; is_spell: boolean; incantation: string
  image: boolean; rarity: string
}
const RARITY_COLOR: Record<string, string> = {
  common: 'rgba(255,255,255,0.18)', rare: '#5b9cff', unique: '#e0a106',
}
interface Equipped { item_id: string; name: string; image: boolean }
interface Belongings {
  avatar: string; slot_order: string[]; slot_labels: Record<string, string>
  equipped: Record<string, Equipped>; items: Item[]
  outfit_sets: Array<{ id: string; name: string }>; max_slots: number
  // Species package contributions (body-slot core): silhouette asset +
  // per-slot anchor positions; empty = core defaults below.
  silhouette_url?: string
  slot_anchors?: Record<string, [number, number]>
}
const EMPTY: Belongings = {
  avatar: '', slot_order: [], slot_labels: {}, equipped: {}, items: [],
  outfit_sets: [], max_slots: 0,
}


export function WardrobeTab({ character }: { character: string }) {
  const { t } = useI18n()
  const enc = encodeURIComponent(character)
  const [data, setData] = useState<Belongings>(EMPTY)
  const [slotFilter, setSlotFilter] = useState('')
  const [busy, setBusy] = useState(false)
  // Item-Vergabe (Items-an-Character): verfügbare Item-Defs + Auswahl.
  const [allItems, setAllItems] = useState<Array<{ item_id: string; name: string; category?: string }>>([])
  const [pickId, setPickId] = useState('')
  const [pickQty, setPickQty] = useState(1)
  useEffect(() => {
    apiGet<{ items?: Array<{ item_id: string; name: string; category?: string }> }>('/inventory/items')
      .then((d) => setAllItems(d.items || []))
      .catch(() => setAllItems([]))
  }, [])
  const figRef = useRef<HTMLDivElement>(null)
  const [figH, setFigH] = useState(0)
  const avatarReady = data.avatar
  useEffect(() => {
    const el = figRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => setFigH(entries[0].contentRect.height))
    ro.observe(el)
    setFigH(el.getBoundingClientRect().height)
    return () => ro.disconnect()
  }, [avatarReady])

  const load = useCallback(async () => {
    if (!character) { setData(EMPTY); return }
    try { setData(await apiGet<Belongings>(`/characters/${enc}/belongings`)) } catch { /* ignore */ }
  }, [character, enc])
  useEffect(() => { load() }, [load])

  const act = useCallback(async (url: string, body: Record<string, unknown>) => {
    if (busy) return
    setBusy(true)
    try {
      await apiPost(url, { user_id: '', ...body })
      await load()
    } catch { /* ignore */ } finally { setBusy(false) }
  }, [busy, load])

  // Item an den Character geben (POST /inventory/characters/{c}).
  const grant = useCallback(async () => {
    if (!pickId || busy) return
    await act(`/inventory/characters/${enc}`, { item_id: pickId, quantity: pickQty })
    setPickId('')
    setPickQty(1)
  }, [pickId, pickQty, busy, act, enc])

  // Item komplett aus dem Inventar entfernen.
  const removeItem = useCallback(async (itemId: string) => {
    if (busy) return
    setBusy(true)
    try {
      await apiDelete(`/inventory/characters/${enc}/${encodeURIComponent(itemId)}`)
      await load()
    } catch { /* ignore */ } finally { setBusy(false) }
  }, [busy, enc, load])

  // Garderobe zeigt NUR Outfit-Pieces (keine Consumables/Spells/sonstigen Items).
  const filtered = useMemo(() => {
    let list = data.items.filter((it) => it.is_outfit)
    if (slotFilter) list = list.filter((it) => it.slots.includes(slotFilter))
    return list
  }, [data.items, slotFilter])

  const slotOptions = useMemo(() => {
    const s = new Set<string>()
    data.items.forEach((it) => { if (it.is_outfit) it.slots.forEach((x) => s.add(x)) })
    return data.slot_order.filter((x) => s.has(x))
  }, [data.items, data.slot_order])

  if (!character) {
    return <div className="ga-form"><div className="ga-placeholder">{t('No character selected')}</div></div>
  }

  const markerSize = Math.round(Math.max(22, Math.min(80, figH * 0.11)))
  // Anchor positions: species package (slot_anchors) wins, core map is the default.
  const anchorOf = (s: string): [number, number] | undefined =>
    data.slot_anchors?.[s] || SLOT_ANCHOR[s]
  const figureSlots = data.slot_order.filter((s) => anchorOf(s))

  return (
    <div style={{ display: 'flex', gap: 12, height: '100%', minHeight: 0, fontSize: '0.9em' }}>
      {/* ── Links: Item-Vergabe + Slot-Filter + Outfit-Liste ── */}
      <div style={{ flex: '1.5 1 0', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
        {/* Items an den Character geben */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select className="ga-input" style={{ flex: 1, minWidth: 0, padding: '3px 8px', fontSize: '0.85em' }}
            value={pickId} disabled={busy} onChange={(e) => setPickId(e.target.value)}>
            <option value="">{t('Add item to character…')}</option>
            {allItems.map((it) => (
              <option key={it.item_id} value={it.item_id}>{it.name}{it.category ? ` · ${it.category}` : ''}</option>
            ))}
          </select>
          <input className="ga-input" type="number" min={1} max={99} value={pickQty} disabled={busy}
            style={{ width: 56, padding: '3px 6px', fontSize: '0.85em' }}
            onChange={(e) => setPickQty(Math.max(1, Number(e.target.value) || 1))} />
          <button className="ga-btn ga-btn-sm" disabled={!pickId || busy} onClick={grant}>+ {t('Add')}</button>
        </div>
        {slotOptions.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            <button onClick={() => setSlotFilter('')} style={chip(!slotFilter, true)}>{t('All slots')}</button>
            {slotOptions.map((s) => (
              <button key={s} onClick={() => setSlotFilter(s)} style={chip(slotFilter === s, true)}>
                {t(data.slot_labels[s] || s)}
              </button>
            ))}
          </div>
        )}
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
          {filtered.length === 0 && <div className="ga-placeholder">{t('No outfit pieces')}</div>}
          {filtered.map((it) => {
            const sub = it.description || it.slots.map((s) => data.slot_labels[s] || s).join(', ')
            const rarityColor = RARITY_COLOR[it.rarity] || RARITY_COLOR.common
            return (
              <div key={it.item_id} title={it.rarity || 'common'} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px',
                borderRadius: 6, borderLeft: `3px solid ${rarityColor}`,
                background: it.equipped ? 'rgba(120,170,255,0.14)' : 'rgba(255,255,255,0.04)',
              }}>
                <ItemIcon itemId={it.item_id} hasImage={it.image} emoji="👕" size={40} />
                <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {it.name}{it.quantity > 1 ? <span style={{ opacity: 0.6 }}> ×{it.quantity}</span> : null}
                  </span>
                  {sub && (
                    <span style={{ fontSize: '0.72em', opacity: 0.5,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</span>
                  )}
                </div>
                {it.equipped
                  ? <span style={{ fontSize: '0.72em', opacity: 0.6 }}>{t('worn')}</span>
                  : <button disabled={busy} style={btn()} onClick={() => act(`/inventory/characters/${enc}/equip`, { item_id: it.item_id })}>{t('Wear')}</button>}
                <button disabled={busy} title={t('Remove from inventory')} style={{ ...btn(), borderColor: 'rgba(224,86,86,0.4)' }}
                  onClick={() => removeItem(it.item_id)}>✕</button>
              </div>
            )
          })}
        </div>
        {data.outfit_sets.length > 0 && (
          <select className="ga-input" value="" disabled={busy} style={{ width: '100%' }}
            onChange={(e) => e.target.value && act(`/inventory/characters/${enc}/apply-outfit-set`, { outfit_id: e.target.value })}>
            <option value="">{t('Wear a saved outfit…')}</option>
            {data.outfit_sets.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        )}
      </div>

      {/* ── Mitte: Figur + Outfit-Symbole (Paper-Doll) ── */}
      <div style={{ flex: '0 0 auto', maxWidth: '32%', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4, minHeight: 0, overflow: 'hidden' }}>
        <div style={{ flex: 1, minHeight: 0, display: 'flex', justifyContent: 'center', alignItems: 'center', overflow: 'hidden' }}>
          <div ref={figRef} style={{ position: 'relative', height: '100%', display: 'inline-flex' }}>
            <img src={data.silhouette_url || '/static/game_admin/silhouette.svg'} alt={data.avatar}
              style={{ height: '100%', width: 'auto', display: 'block', opacity: 0.45 }} />
            {figureSlots.map((slot) => {
              const a = anchorOf(slot)!
              const eq = data.equipped[slot]
              const common = {
                position: 'absolute' as const, left: `${a[0]}%`, top: `${a[1]}%`,
                transform: 'translate(-50%,-50%)', width: markerSize, height: markerSize,
                borderRadius: 5, boxSizing: 'border-box' as const,
              }
              if (eq) {
                return (
                  <button key={slot} title={`${eq.name} — ${t('take off')}`}
                    onClick={() => act(`/inventory/characters/${enc}/unequip`, { slot })}
                    style={{
                      ...common, padding: 0, cursor: 'pointer', overflow: 'hidden',
                      border: '2px solid var(--accent,#6aa9ff)',
                      boxShadow: '0 0 0 2px rgba(0,0,0,0.5), 0 1px 4px rgba(0,0,0,0.6)',
                      background: 'rgba(20,25,35,0.85)',
                    }}>
                    <ItemIcon itemId={eq.item_id} hasImage={eq.image} emoji="👕" size={markerSize} />
                  </button>
                )
              }
              return (
                <div key={slot} title={`${t(data.slot_labels[slot] || slot)} (${t('empty')})`}
                  style={{ ...common, border: '2px dashed rgba(255,255,255,0.4)', background: 'rgba(0,0,0,0.25)' }} />
              )
            })}
          </div>
        </div>
        <div style={{ opacity: 0.5, fontSize: '0.72em', textAlign: 'center' }}>
          {data.items.filter((it) => it.is_outfit).length} {t('outfit pieces')}
        </div>
        {/* Appearance preview under the paper doll: the full-body render
            depends on the worn outfit, so it lives with the wardrobe. */}
      </div>

      {/* ── Rechts: Vorschaubild oben, Effektiv-Prompts unten — beides
          aktualisiert mit jedem An-/Ausziehen (data reload). ── */}
      <div style={{ flex: '1 1 0', minWidth: 220, display: 'flex', flexDirection: 'column',
                    gap: 10, minHeight: 0, overflow: 'auto' }}>
        <FieldImage character={character} kind="outfit" />
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.12)', paddingTop: 8 }}>
          <PromptPreview character={character}
            refreshKey={JSON.stringify(data.equipped)} />
        </div>
      </div>
    </div>
  )
}

function chip(active: boolean, small = false): CSSProperties {
  return {
    padding: small ? '1px 7px' : '2px 9px', borderRadius: 11, cursor: 'pointer',
    fontSize: small ? '0.72em' : '0.78em',
    border: '1px solid ' + (active ? 'var(--accent,#6aa9ff)' : 'rgba(255,255,255,0.2)'),
    background: active ? 'rgba(120,170,255,0.25)' : 'transparent', color: 'inherit',
  }
}
function btn(): CSSProperties {
  return {
    fontSize: '0.72em', padding: '2px 8px', borderRadius: 6, cursor: 'pointer',
    border: '1px solid rgba(255,255,255,0.25)', background: 'rgba(255,255,255,0.06)', color: 'inherit',
  }
}
